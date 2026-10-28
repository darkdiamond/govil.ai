"""Subprocess sandbox for production agent sessions.

Same surface as `podman_sandbox.PodmanSandbox` (`run_code`, `files.read`,
`files.list`, `kill`) but executes directly in the builder container via
`subprocess` — Cloud Run can't nest containers, so the (single-tenant,
ephemeral) container itself is the outer isolation boundary. Each session
gets a private working directory; the agent's prompt uses relative scratch
paths and the per-session OUTPUTS_DIR, so concurrent sessions in one
container never share files.

Hardening within that boundary:
- privilege separation: when the builder runs as root (the container) and
  the unprivileged `sandbox` user exists (Dockerfile; override the name
  with SANDBOX_USER, empty string disables), every tool command runs as
  that user (setuid/setgid, no supplementary groups, umask 077). The
  workdir stays root-owned 0700 while the host provisions check.py and
  the prefetched CSVs, and is handed to the sandbox user (directories
  chowned, host-written files left root-owned + world-readable, i.e.
  read-only to the agent) right before the first command runs. Outputs
  are read back refusing symlinks and files the sandbox user doesn't own,
  so a session can't trick the root host into reading /proc/1/environ or
  any other host file into the published page.
- scrubbed env: PATH/HOME/LANG only — no GCP credentials vars, no
  OPENROUTER key (HOME — and, privilege-separated, TMPDIR — point into
  the session workdir).
- per-command wall-clock timeout (default 120s, SIGKILL on expiry); at
  session end, privilege-separated, stray background processes the
  session left running are killed before the workdir is removed.
- output size is capped by the caller (model_harness truncation).

When the builder is NOT root (local dev, tests) none of the privilege
separation applies and commands run as the invoking user, as before.

Accepted residual risk (documented in CLAUDE.md): with privilege
separation, tool processes can no longer read the builder process's
environment (/proc/<pid>/environ is same-uid only) or modify the image's
code under /app (root-owned, not writable by `sandbox`) — including the
host-side agent/skills/check.py gate. They CAN still reach the network,
including the GCP metadata server, and so obtain the builder service
account's token. The SA must therefore stay minimal: Firestore + the
staging bucket + running the publish trigger only. Concurrent sessions
share the one `sandbox` uid, so a hostile session could in principle
tamper with a sibling session's workdir; each sibling's output still has
to pass the host-side check on its own.
"""
from __future__ import annotations

import logging
import os
import pwd
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .podman_sandbox import _Error, _Execution, _FileEntry, _Logs

log = logging.getLogger(__name__)

_BASE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
_DEFAULT_SANDBOX_USER = "sandbox"


def _resolve_sandbox_identity() -> Optional[tuple[int, int]]:
    """(uid, gid) tool commands should drop to, or None to run unchanged.

    Only a root host can (and needs to) drop privileges. SANDBOX_USER
    picks the account; an empty value disables privilege separation. A
    missing *default* user degrades to the legacy behaviour with a
    warning (e.g. an older image); an explicitly named user that doesn't
    exist is a configuration error.
    """
    if os.geteuid() != 0:
        return None
    explicit = "SANDBOX_USER" in os.environ
    name = os.environ.get("SANDBOX_USER", _DEFAULT_SANDBOX_USER).strip()
    if not name:
        log.warning("LocalSandbox: SANDBOX_USER='' — tool commands run as root")
        return None
    try:
        pw = pwd.getpwnam(name)
    except KeyError:
        if explicit:
            raise RuntimeError(f"SANDBOX_USER={name!r} does not exist") from None
        log.warning(
            "LocalSandbox: no %r user in this image — tool commands run as root",
            name,
        )
        return None
    if pw.pw_uid == 0:
        raise RuntimeError(f"SANDBOX_USER={name!r} resolves to uid 0")
    return pw.pw_uid, pw.pw_gid


class _Files:
    def __init__(self, sb: "LocalSandbox"):
        self._sb = sb

    def _abs(self, path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else self._sb.workdir / p

    def read(self, path: str) -> bytes:
        p = self._abs(path)
        if self._sb.ident is not None:
            return self._sb._read_untrusted(p)
        if not p.is_file():
            raise FileNotFoundError(f"sandbox file not readable: {p}")
        return p.read_bytes()

    def list(self, path: str) -> list[_FileEntry]:
        p = self._abs(path)
        if not p.is_dir():
            return []
        return [
            _FileEntry(name=c.name, path=str(c))
            for c in sorted(p.iterdir())
        ]


class LocalSandbox:
    """Per-session subprocess executor with a private workdir."""

    def __init__(self, workdir: Path, ident: Optional[tuple[int, int]] = None):
        self.workdir = workdir
        self.ident = ident
        self.files = _Files(self)
        self._closed = False
        self._handed_over = False
        # The interpreter's bin dir carries the pip-installed deps agent
        # sessions expect from bash (`python3` + pandas). In the builder
        # container that's /usr/local/bin — already on _BASE_PATH, so this
        # is a no-op there; on a local venv run it resolves python3 to the
        # venv interpreter instead of the bare system one.
        interp_bin = str(Path(sys.executable).parent)
        path = (
            _BASE_PATH
            if interp_bin in _BASE_PATH.split(":")
            else f"{interp_bin}:{_BASE_PATH}"
        )
        self._env = {
            "PATH": path,
            "HOME": str(workdir),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
        }
        if ident is not None:
            # /tmp is shared by every session; keep scratch inside this
            # session's own 0700 tree.
            self._env["TMPDIR"] = str(workdir / ".tmp")

    @classmethod
    def create(cls, workdir: str | Path) -> "LocalSandbox":
        wd = Path(workdir)
        (wd / "outputs").mkdir(parents=True, exist_ok=True)
        ident = _resolve_sandbox_identity()
        if ident is not None:
            # Root-owned and private until handover (first run_code), so no
            # sandbox-uid process can plant links while the host is still
            # provisioning check.py / the prefetched CSVs into it.
            os.chmod(wd, 0o700)
            (wd / ".tmp").mkdir(exist_ok=True)
        log.info(
            "LocalSandbox: workdir=%s%s",
            wd,
            f" (tools run as uid {ident[0]})" if ident else "",
        )
        return cls(wd, ident)

    # ── privilege separation ────────────────────────────────────────────
    def handover(self) -> None:
        """Give the workdir to the sandbox user (idempotent).

        Directories become sandbox-owned 0700 so the agent can create
        files anywhere in its tree; files the HOST wrote (check.py copy,
        prefetched CSVs — possibly hardlinks shared across attempts) stay
        root-owned and are made world-readable, i.e. read-only to the
        agent. Nothing is ever chowned through a symlink.
        """
        if self.ident is None or self._handed_over:
            return
        uid, gid = self.ident
        for root, _dirs, files in os.walk(self.workdir, followlinks=False):
            os.chown(root, uid, gid, follow_symlinks=False)
            os.chmod(root, 0o700)
            for name in files:
                fp = os.path.join(root, name)
                st = os.lstat(fp)
                if stat.S_ISREG(st.st_mode):
                    os.chmod(fp, (st.st_mode & 0o777) | 0o444)
        self._handed_over = True

    def adopt(self, path: str | Path) -> None:
        """Make a host-written file under the workdir usable by the agent.

        Before handover this is a no-op (handover covers it). After it,
        any host-owned directory between the workdir and `path` is chowned
        to the sandbox user and a host-owned file made world-readable.
        """
        if self.ident is None or not self._handed_over:
            return
        uid, gid = self.ident
        p = Path(path)
        try:
            rel = p.relative_to(self.workdir)
        except ValueError:
            return
        cur = self.workdir
        for part in rel.parts[:-1]:
            cur = cur / part
            st = os.lstat(cur)
            if stat.S_ISDIR(st.st_mode) and st.st_uid != uid:
                os.chown(cur, uid, gid, follow_symlinks=False)
                os.chmod(cur, 0o700)
        st = os.lstat(p)
        if stat.S_ISREG(st.st_mode) and st.st_uid != uid:
            os.chmod(p, (st.st_mode & 0o777) | 0o444)

    def _read_untrusted(self, p: Path) -> bytes:
        """Read a file the sandbox user produced, as the root host.

        The path must resolve inside the workdir with no symlink anywhere,
        and the opened inode must be a regular file OWNED by the sandbox
        user — a symlink or hardlink to /proc/1/environ or any root file
        is refused, whatever race the session plays (the ownership check
        is on the opened fd).
        """
        wd = os.path.realpath(self.workdir)
        absp = os.path.abspath(p)
        real = os.path.realpath(absp)
        if real != absp or os.path.commonpath([wd, real]) != wd:
            raise FileNotFoundError(
                f"sandbox file not readable (symlink or outside workdir): {p}"
            )
        try:
            fd = os.open(real, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as e:
            raise FileNotFoundError(f"sandbox file not readable: {p} ({e})") from e
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != self.ident[0]:
                raise FileNotFoundError(
                    "sandbox file not readable (not a regular file owned by "
                    f"the sandbox user): {p}"
                )
            with os.fdopen(fd, "rb", closefd=False) as f:
                return f.read()
        finally:
            os.close(fd)

    def _reap_stragglers(self) -> None:
        """SIGKILL background processes this session left running.

        Matched by uid + the session's unique HOME in their environment
        (root can read any /proc/<pid>/environ). Best-effort: a process
        that scrubbed its own env escapes this and dies with the container.
        """
        uid = self.ident[0]
        marker = f"HOME={self.workdir}".encode()
        try:
            pids = [d for d in os.listdir("/proc") if d.isdigit()]
        except OSError:
            return
        for pid in pids:
            try:
                if os.stat(f"/proc/{pid}").st_uid != uid:
                    continue
                with open(f"/proc/{pid}/environ", "rb") as f:
                    env = f.read().split(b"\0")
                if marker in env:
                    os.kill(int(pid), signal.SIGKILL)
            except (OSError, ValueError):
                continue

    def kill(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.ident is not None and self._handed_over:
            self._reap_stragglers()
        # rmtree is symlink-attack safe on Linux (fd-based), so a
        # sandbox-planted link can't redirect the root delete.
        shutil.rmtree(self.workdir, ignore_errors=True)

    def run_code(
        self,
        code: str,
        *,
        language: str = "python",
        timeout: int = 120,
    ) -> _Execution:
        if language == "bash":
            argv = ["bash", "-c", code]
        elif language in ("python", "py"):
            argv = [sys.executable, "-c", code]
        else:
            return _Execution(error=_Error(name="UnsupportedLanguage", value=language))
        privsep: dict = {}
        if self.ident is not None:
            self.handover()
            uid, gid = self.ident
            privsep = {"user": uid, "group": gid, "extra_groups": [], "umask": 0o077}
        try:
            proc = subprocess.run(
                argv,
                cwd=self.workdir,
                env=self._env,
                capture_output=True,
                timeout=timeout,
                **privsep,
            )
        except subprocess.TimeoutExpired as e:
            return _Execution(
                logs=_Logs(
                    stdout=(e.stdout or b"").decode("utf-8", errors="replace"),
                    stderr=(e.stderr or b"").decode("utf-8", errors="replace"),
                ),
                error=_Error(name="Timeout", value=f"killed after {timeout}s"),
            )
        out = proc.stdout.decode("utf-8", errors="replace")
        err = proc.stderr.decode("utf-8", errors="replace")
        error = (
            _Error(name="NonZeroExit", value=f"exit code {proc.returncode}")
            if proc.returncode != 0
            else None
        )
        return _Execution(logs=_Logs(stdout=out, stderr=err), error=error)
