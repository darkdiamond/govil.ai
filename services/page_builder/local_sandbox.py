"""Subprocess sandbox for recipe `compute.py` runs (services/page_builder/refresh.py).

Surface: `run_code` (returns an `_Execution`), `files.read`, `kill`. It
executes directly in the builder container via `subprocess` — Cloud Run
can't nest containers, so the (single-tenant, ephemeral) container itself
is the outer isolation boundary. Each compute run gets a private working
directory. (Built for the retired agent builder's tool sessions; "session"
below means one sandbox lifetime.)

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
  GitHub token or other key vars (HOME — and, privilege-separated,
  TMPDIR — point into the session workdir).
- per-command wall-clock timeout (default 120s, SIGKILL on expiry); at
  session end, privilege-separated, every process still running as the
  sandbox uid is killed before the workdir is removed (sessions run one at
  a time, so whatever that uid still runs is this session's leftover), and
  `max_procs` caps the uid's processes + threads per command
  (RLIMIT_NPROC), so a runaway fork loop stops at the cap.
- bounded read-back: of everything a command prints, the host keeps only
  the last `max_output_bytes` of stdout and of stderr (default 64KB each;
  the rest is read from the pipe and dropped), and `files.read` refuses a
  file over `max_read_bytes` with `OutputTooLarge`. What the sandbox writes
  to its workdir is bounded by the caller's RLIMIT_FSIZE prologue
  (refresh.py `_memory_guard`), not here.

When the builder is NOT root (local dev, tests) none of the privilege
separation applies and commands run as the invoking user, as before.

Accepted residual risk (documented in CLAUDE.md): with privilege
separation, tool processes can no longer read the builder process's
environment (/proc/<pid>/environ is same-uid only) or modify the image's
code under /app (root-owned, not writable by `sandbox`) — including the
host-side agent/skills/check.py gate. Network: this class doesn't cut it;
the refresh's compute prologue does (refresh.py `_network_guard`): under
REFRESH_COMPUTE_NETWORK=deny (the default) the child installs a seccomp
filter (netguard.py) that refuses every non-AF_UNIX socket before recipe
code loads, so compute can't reach the GCP metadata server and the builder
service account's token. Other code run through this class (none in prod
today) has no such filter. The SA must still stay minimal: Firestore + the
staging bucket + running the publish trigger only. Concurrent sessions
share the one `sandbox` uid, so a hostile session could in principle
tamper with a sibling session's workdir; each sibling's output still has
to pass the host-side check on its own. (The refresh runs one compute at a
time; a second concurrent privilege-separated session would be killed by
the first one's end-of-session reap.)
"""
from __future__ import annotations

import logging
import os
import pwd
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_BASE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
_DEFAULT_SANDBOX_USER = "sandbox"
# Tail of stdout / stderr the host keeps per command. Callers quote at most
# the last 1,500 characters of stderr in errors and issues.
DEFAULT_OUTPUT_TAIL_BYTES = 64 * 1024
_PIPE_CHUNK = 64 * 1024
# End-of-session reap: how long to keep killing + reaping the sandbox uid's
# processes before giving up (a normal compute leaves none: one /proc scan).
_REAP_WAIT_S = 3.0
_PR_SET_CHILD_SUBREAPER = 36
_subreaper = False


def _pids_of_uid(uid: int) -> list[int]:
    """Every process (zombies too) whose /proc entry belongs to `uid`."""
    out = []
    try:
        names = os.listdir("/proc")
    except OSError:
        return out
    for name in names:
        if name.isdigit():
            try:
                if os.stat(f"/proc/{name}").st_uid == uid:
                    out.append(int(name))
            except OSError:
                continue
    return out


def _become_subreaper() -> None:
    """Make this (root host) process the subreaper of everything it spawns:
    a sandbox process that outlives its parent is re-parented here, not to
    PID 1, so `_reap_stragglers` can wait for it. Once per process; Linux
    only, best effort."""
    global _subreaper
    if _subreaper:
        return
    try:
        import ctypes

        if ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_CHILD_SUBREAPER)")
        _subreaper = True
    except (OSError, AttributeError) as e:
        log.warning("LocalSandbox: can't become the child subreaper (%s): orphaned "
                    "sandbox processes go to PID 1", e)


class OutputTooLarge(Exception):
    """A sandbox file is bigger than the reader's `max_read_bytes`."""


@dataclass
class _Logs:
    stdout: str = ""
    stderr: str = ""


@dataclass
class _Error:
    name: str
    value: str


@dataclass
class _Execution:
    logs: _Logs = field(default_factory=_Logs)
    error: _Error | None = None


def _resolve_sandbox_identity() -> tuple[int, int] | None:
    """(uid, gid) tool commands should drop to, or None to run unchanged.

    Only a root host can (and needs to) drop privileges. SANDBOX_USER
    picks the account; an empty value disables privilege separation. A
    missing *default* user degrades to the legacy behaviour with a
    warning (local authoring, an older image), except inside the Cloud Run
    job (`CLOUD_RUN_JOB` set), where it refuses rather than run recipe code
    as root; an explicitly named user that doesn't exist is a configuration
    error.
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
        if os.environ.get("CLOUD_RUN_JOB"):
            raise RuntimeError(
                f"no {name!r} user in this image: refusing to run recipe code as root "
                "inside the job (SANDBOX_USER='' opts out explicitly)"
            ) from None
        log.warning(
            "LocalSandbox: no %r user in this image — tool commands run as root",
            name,
        )
        return None
    if pw.pw_uid == 0:
        raise RuntimeError(f"SANDBOX_USER={name!r} resolves to uid 0")
    return pw.pw_uid, pw.pw_gid


class _Files:
    def __init__(self, sb: LocalSandbox):
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
        with open(p, "rb") as f:
            return _read_capped(f, p, self._sb.max_read_bytes)


def _read_capped(f, p: Path, max_bytes: int | None) -> bytes:
    """Read an open file whole, refusing it past `max_bytes` (None = no cap)
    by its size and by what is actually read, in case it grows meanwhile."""
    if max_bytes is None:
        return f.read()
    size = os.fstat(f.fileno()).st_size
    if size > max_bytes:
        raise OutputTooLarge(f"{p.name} is {size:,} bytes, over the {max_bytes:,}-byte cap")
    data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise OutputTooLarge(f"{p.name} is over the {max_bytes:,}-byte cap")
    return data


def _killpg(proc: subprocess.Popen) -> None:
    """SIGKILL the child's whole process group (it leads its own session),
    so a background process it left can't hold the pipes open. Called before
    the child is reaped, so its pid (= the group id) can't have been reused."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _run_capped(
    argv: list[str], *, timeout: int, max_output_bytes: int, **popen_kw
) -> tuple[int | None, bytes, bytes]:
    """Run `argv`; return (returncode, stdout tail, stderr tail).

    Like `subprocess.run(capture_output=True, timeout=...)` (both pipes are
    drained on this thread until EOF or the deadline), except that the host
    holds at most `max_output_bytes` of each stream. returncode None means
    the timeout expired: the child's process group is SIGKILLed and the
    output read so far is returned. Pipes held open after the child exits
    (a background process) count against the same timeout. Nothing reads
    either pipe once this returns.
    """
    deadline = time.monotonic() + timeout
    with subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True, **popen_kw,
    ) as proc:
        tails = {proc.stdout.fileno(): bytearray(), proc.stderr.fileno(): bytearray()}
        try:
            timed_out = False
            with selectors.DefaultSelector() as sel:
                for fd in tails:
                    sel.register(fd, selectors.EVENT_READ)
                while sel.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        break
                    for key, _ in sel.select(remaining):
                        chunk = os.read(key.fd, _PIPE_CHUNK)
                        if not chunk:
                            sel.unregister(key.fd)
                            continue
                        tail = tails[key.fd]
                        tail += chunk
                        if len(tail) > max_output_bytes:
                            del tail[:-max_output_bytes]
            if not timed_out:
                try:
                    proc.wait(timeout=max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
        except BaseException:
            # Interrupted (Ctrl-C, SystemExit, an unexpected OSError): the child
            # leads its own session, so no terminal signal reaches it. Kill it.
            _killpg(proc)
            proc.kill()
            proc.wait()
            raise
        if timed_out:
            _killpg(proc)
            proc.kill()
            proc.wait()
        rc = None if timed_out else proc.returncode
        return rc, bytes(tails[proc.stdout.fileno()]), bytes(tails[proc.stderr.fileno()])


class LocalSandbox:
    """Per-session subprocess executor with a private workdir."""

    def __init__(
        self,
        workdir: Path,
        ident: tuple[int, int] | None = None,
        *,
        max_read_bytes: int | None = None,
        max_procs: int | None = None,
    ):
        self.workdir = workdir
        self.ident = ident
        # RLIMIT_NPROC for each command, privilege-separated only (it counts
        # every process of the uid: unprivileged, that is the whole user
        # session). None/0 = no cap.
        self.max_procs = max_procs
        # Largest file `files.read` returns; None = no cap.
        self.max_read_bytes = max_read_bytes
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
    def create(cls, workdir: str | Path, *, max_read_bytes: int | None = None,
               max_procs: int | None = None) -> LocalSandbox:
        wd = Path(workdir)
        (wd / "outputs").mkdir(parents=True, exist_ok=True)
        ident = _resolve_sandbox_identity()
        if ident is not None:
            # Root-owned and private until handover (first run_code), so no
            # sandbox-uid process can plant links while the host is still
            # provisioning check.py / the prefetched CSVs into it.
            os.chmod(wd, 0o700)
            (wd / ".tmp").mkdir(exist_ok=True)
            _become_subreaper()
        log.info(
            "LocalSandbox: workdir=%s%s",
            wd,
            f" (tools run as uid {ident[0]})" if ident else "",
        )
        return cls(wd, ident, max_read_bytes=max_read_bytes, max_procs=max_procs)

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
                return _read_capped(f, p, self.max_read_bytes)
        finally:
            os.close(fd)

    def _reap_stragglers(self) -> int:
        """SIGKILL every process still running as the sandbox uid, and reap
        the dead ones; return how many were killed.

        By uid alone: a process that changed its environment, its session or
        its process group is still caught. Sessions run one at a time (the
        refresh's computes are sequential), so all of that uid is this
        session's. The host is the orphans' subreaper (`_become_subreaper`),
        so it waits for them itself: a zombie still counts toward the uid's
        RLIMIT_NPROC, and the job's PID 1 (the builder) would never reap it.
        Rescans until the uid holds nothing, for at most `_REAP_WAIT_S`.
        """
        uid = self.ident[0]
        killed: set[int] = set()
        deadline = time.monotonic() + _REAP_WAIT_S
        while True:
            pids = _pids_of_uid(uid)
            for pid in pids:
                if pid not in killed:
                    try:
                        os.kill(pid, signal.SIGKILL)
                        killed.add(pid)
                    except OSError:
                        pass
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:  # not ours: its own parent reaps it
                    pass
                except OSError:
                    pass
            if not pids or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        if killed:
            left = len(_pids_of_uid(uid))
            log.warning("LocalSandbox: killed %d process(es) left running as uid %d%s",
                        len(killed), uid, f"; {left} not reaped yet" if left else "")
        return len(killed)

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
        max_output_bytes: int = DEFAULT_OUTPUT_TAIL_BYTES,
    ) -> _Execution:
        if language == "bash":
            argv = ["bash", "-c", code]
        elif language in ("python", "py"):
            argv = [sys.executable, "-c", code]
        else:
            return _Execution(error=_Error(name="UnsupportedLanguage", value=language))
        privsep: dict = {}
        if self.ident is not None and self.max_procs and self.max_procs > 0:
            n = int(self.max_procs)
            # Set by the command itself, already as the sandbox uid (no
            # preexec_fn: the builder process has gRPC threads).
            if language == "bash":
                argv[2] = f"ulimit -u {n}\n{code}"
            else:
                argv[2] = ("import resource as _r; "
                           f"_r.setrlimit(_r.RLIMIT_NPROC, ({n}, {n})); del _r\n{code}")
        if self.ident is not None:
            self.handover()
            uid, gid = self.ident
            privsep = {"user": uid, "group": gid, "extra_groups": [], "umask": 0o077}
        # A failing compute is an _Execution error, not an exception.
        rc, out_b, err_b = _run_capped(
            argv,
            cwd=self.workdir,
            env=self._env,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            **privsep,
        )
        logs = _Logs(
            stdout=out_b.decode("utf-8", errors="replace"),
            stderr=err_b.decode("utf-8", errors="replace"),
        )
        if rc is None:
            return _Execution(
                logs=logs, error=_Error(name="Timeout", value=f"killed after {timeout}s")
            )
        error = _Error(name="NonZeroExit", value=f"exit code {rc}") if rc != 0 else None
        return _Execution(logs=logs, error=error)
