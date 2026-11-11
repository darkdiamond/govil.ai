"""LocalSandbox privilege separation.

In the builder container the host process is root and every agent tool
command must drop to the unprivileged `sandbox` user, so a prompt-injected
command can't read the host's /proc/<pid>/environ secrets or rewrite the
image's check.py. Off-root (local dev, CI) nothing may change.
"""
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from services.page_builder import local_sandbox as ls
from services.page_builder import page_gate

UID, GID = 10001, 10001


class _RunRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return 0, b"ok\n", b""


@pytest.fixture
def as_root(monkeypatch):
    """Pretend the host is root and a `sandbox` user exists; record chowns."""
    chowns = []
    monkeypatch.setattr(ls.os, "geteuid", lambda: 0)
    monkeypatch.delenv("SANDBOX_USER", raising=False)

    def getpwnam(name):
        if name != "sandbox":
            raise KeyError(name)
        return SimpleNamespace(pw_uid=UID, pw_gid=GID)

    monkeypatch.setattr(ls.pwd, "getpwnam", getpwnam)
    monkeypatch.setattr(
        ls.os, "chown",
        lambda path, uid, gid, *, follow_symlinks=True: chowns.append(
            (str(path), uid, gid, follow_symlinks)
        ),
    )
    rec = _RunRecorder()
    monkeypatch.setattr(ls, "_run_capped", rec)
    return SimpleNamespace(chowns=chowns, run=rec)


def test_root_drops_to_sandbox_user(tmp_path, as_root):
    wd = tmp_path / "s1"
    sb = ls.LocalSandbox.create(wd)
    assert sb.ident == (UID, GID)
    assert (wd.stat().st_mode & 0o777) == 0o700
    # Nothing handed over yet: the host may still be provisioning.
    assert as_root.chowns == []

    # Host provisions a data file + check.py before the first command.
    (wd / "data").mkdir()
    (wd / "data" / "data_1.csv").write_text("a,b\n1,2\n")
    (wd / "check.py").write_text("print('OK')\n")
    os.chmod(wd / "check.py", 0o600)

    exe = sb.run_code("echo hi", language="bash")
    assert exe.error is None
    (argv, kw), = as_root.run.calls
    assert argv == ["bash", "-c", "echo hi"]
    assert kw["user"] == UID and kw["group"] == GID
    assert kw["extra_groups"] == []
    assert kw["umask"] == 0o077
    assert kw["env"]["HOME"] == str(wd)
    assert kw["env"]["TMPDIR"] == str(wd / ".tmp")
    assert "OPENROUTER_API_KEY" not in kw["env"]

    # Every directory (workdir, outputs/, data/, .tmp/) went to the
    # sandbox user, never through a symlink; host files did not change
    # owner but became readable to it.
    chowned = {p for p, *_ in as_root.chowns}
    for d in (wd, wd / "outputs", wd / "data", wd / ".tmp"):
        assert str(d) in chowned
    assert all(u == UID and g == GID and fs is False for _, u, g, fs in as_root.chowns)
    assert str(wd / "check.py") not in chowned
    assert (wd / "check.py").stat().st_mode & 0o004
    assert (wd / "data" / "data_1.csv").stat().st_mode & 0o004

    # Handover is one-shot.
    n = len(as_root.chowns)
    sb.run_code("print(1)", language="python")
    assert len(as_root.chowns) == n
    assert as_root.run.calls[1][1]["user"] == UID


def test_sandbox_user_env_overrides(tmp_path, as_root, monkeypatch):
    monkeypatch.setenv("SANDBOX_USER", "")
    assert ls.LocalSandbox.create(tmp_path / "a").ident is None
    monkeypatch.setenv("SANDBOX_USER", "nosuchuser")
    with pytest.raises(RuntimeError):
        ls.LocalSandbox.create(tmp_path / "b")
    monkeypatch.setattr(
        ls.pwd, "getpwnam",
        lambda n: SimpleNamespace(pw_uid=0, pw_gid=0),
    )
    monkeypatch.setenv("SANDBOX_USER", "root")
    with pytest.raises(RuntimeError):
        ls.LocalSandbox.create(tmp_path / "c")


def test_root_without_default_user_degrades(tmp_path, as_root, monkeypatch):
    monkeypatch.setattr(ls.pwd, "getpwnam", lambda n: (_ for _ in ()).throw(KeyError(n)))
    sb = ls.LocalSandbox.create(tmp_path / "a")
    assert sb.ident is None
    sb.run_code("true", language="bash")
    assert "user" not in as_root.run.calls[0][1]


def test_non_root_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(ls.os, "geteuid", lambda: 1000)
    rec = _RunRecorder()
    monkeypatch.setattr(ls, "_run_capped", rec)
    chowns = []
    monkeypatch.setattr(ls.os, "chown", lambda *a, **k: chowns.append(a))
    sb = ls.LocalSandbox.create(tmp_path / "s")
    assert sb.ident is None
    sb.run_code("echo hi", language="bash")
    (_, kw), = rec.calls
    for k in ("user", "group", "extra_groups", "umask"):
        assert k not in kw
    assert "TMPDIR" not in kw["env"]
    assert chowns == []


def test_non_root_real_subprocess_roundtrip(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("exercises the unprivileged path")
    sb = ls.LocalSandbox.create(tmp_path / "s")
    exe = sb.run_code("echo '<p>x</p>' > outputs/content.html && echo done", language="bash")
    assert exe.error is None and "done" in exe.logs.stdout
    assert sb.files.read("outputs/content.html") == b"<p>x</p>\n"
    sb.kill()
    assert not (tmp_path / "s").exists()


# ── reading outputs back as root: refuse anything the agent didn't make ──
def _privsep_reader(tmp_path, uid=None):
    wd = tmp_path / "w"
    (wd / "outputs").mkdir(parents=True)
    me = os.getuid() if uid is None else uid
    return wd, ls.LocalSandbox(wd, ident=(me, os.getgid()))


def test_read_untrusted_accepts_sandbox_owned_file(tmp_path):
    wd, sb = _privsep_reader(tmp_path)
    (wd / "outputs" / "content.html").write_text("<p>ok</p>")
    assert sb.files.read(str(wd / "outputs" / "content.html")) == b"<p>ok</p>"


def test_read_untrusted_rejects_symlink(tmp_path):
    wd, sb = _privsep_reader(tmp_path)
    secret = tmp_path / "environ"
    secret.write_text("OPENROUTER_API_KEY=sk-secret")
    (wd / "outputs" / "content.html").symlink_to(secret)
    with pytest.raises(FileNotFoundError):
        sb.files.read(str(wd / "outputs" / "content.html"))


def test_read_untrusted_rejects_symlinked_parent(tmp_path):
    wd, sb = _privsep_reader(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "content.html").write_text("x")
    (wd / "outputs").rmdir()
    (wd / "outputs").symlink_to(other)
    with pytest.raises(FileNotFoundError):
        sb.files.read(str(wd / "outputs" / "content.html"))


def test_read_untrusted_rejects_foreign_owned_file(tmp_path):
    # A hardlink to a root-owned file keeps root as owner → refused.
    wd, sb = _privsep_reader(tmp_path, uid=os.getuid() + 12345)
    (wd / "outputs" / "content.html").write_text("x")
    with pytest.raises(FileNotFoundError):
        sb.files.read(str(wd / "outputs" / "content.html"))


def test_read_untrusted_rejects_fifo_without_blocking(tmp_path):
    wd, sb = _privsep_reader(tmp_path)
    os.mkfifo(wd / "outputs" / "content.html")
    with pytest.raises(FileNotFoundError):
        sb.files.read(str(wd / "outputs" / "content.html"))


# ── what the host reads back is bounded ──
@pytest.mark.parametrize("privsep", [False, True])
def test_read_refuses_oversized_output(tmp_path, privsep):
    if privsep:
        wd = tmp_path / "w"
        (wd / "outputs").mkdir(parents=True)
        sb = ls.LocalSandbox(wd, ident=(os.getuid(), os.getgid()), max_read_bytes=1_000_000)
    else:
        sb = ls.LocalSandbox.create(tmp_path / "w", max_read_bytes=1_000_000)
        wd = sb.workdir
    (wd / "outputs" / "model.json").write_bytes(b"x" * 2_000_000)
    with pytest.raises(ls.OutputTooLarge):
        sb.files.read("outputs/model.json")
    (wd / "outputs" / "model.json").write_bytes(b"x" * 1_000_000)
    assert len(sb.files.read("outputs/model.json")) == 1_000_000


def test_huge_output_keeps_a_bounded_tail(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("exercises the unprivileged path")
    import tracemalloc

    sb = ls.LocalSandbox.create(tmp_path / "s")
    code = (
        "import sys\n"
        "chunk = 'x' * 1_000_000\n"
        "for _ in range(50):\n"
        "    sys.stdout.write(chunk); sys.stderr.write(chunk)\n"
        "sys.stdout.write('OUT-END'); sys.stderr.write('ERR-END')\n"
        "sys.exit(3)\n"
    )
    tracemalloc.start()
    try:
        exe = sb.run_code(code, language="python", timeout=60, max_output_bytes=64 * 1024)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        sb.kill()
    assert exe.error is not None and exe.error.value == "exit code 3"
    assert exe.logs.stdout.endswith("OUT-END") and exe.logs.stderr.endswith("ERR-END")
    assert len(exe.logs.stdout) <= 64 * 1024 and len(exe.logs.stderr) <= 64 * 1024
    assert peak < 8_000_000  # 100MB went through the pipes, not into host memory


def test_timeout_keeps_output_so_far(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("exercises the unprivileged path")
    sb = ls.LocalSandbox.create(tmp_path / "s")
    exe = sb.run_code("echo started; echo oops >&2; sleep 30", language="bash", timeout=1)
    sb.kill()
    assert exe.error is not None and exe.error.name == "Timeout"
    assert exe.logs.stdout == "started\n" and exe.logs.stderr == "oops\n"


def test_small_output_is_returned_whole(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("exercises the unprivileged path")
    sb = ls.LocalSandbox.create(tmp_path / "s")
    exe = sb.run_code("printf 'a\\nb\\n'; printf 'שגיאה\\n' >&2; exit 1", language="bash")
    sb.kill()
    assert exe.error is not None and exe.error.value == "exit code 1"
    assert exe.logs.stdout == "a\nb\n" and exe.logs.stderr == "שגיאה\n"


def _gone(pid: int, wait_s: float = 3.0) -> bool:
    """The process no longer runs (gone or a zombie awaiting its reaper)."""
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        try:
            with open(f"/proc/{pid}/stat") as f:
                if f.read().rsplit(")", 1)[1].split()[0] == "Z":
                    return True
        except (FileNotFoundError, ProcessLookupError):  # it exited mid-read
            return True
        time.sleep(0.05)
    return False


# A background process keeps stdout/stderr open and writes after the parent
# exits (or while it still runs).
_HOLDS_PIPE = {
    "parent_exits": "(sleep 1.5; echo LATE; echo LATE >&2; sleep 30) & echo $!",
    "parent_runs": "(sleep 1.5; echo LATE; sleep 30) & echo $!; sleep 30",
}


@pytest.mark.parametrize("case", sorted(_HOLDS_PIPE))
def test_background_process_holding_the_pipes_is_killed_and_nothing_reads_later(case):
    threads_before = threading.active_count()
    started = time.monotonic()
    rc, out, err = ls._run_capped(
        ["bash", "-c", _HOLDS_PIPE[case]], timeout=1, max_output_bytes=64 * 1024
    )
    elapsed = time.monotonic() - started
    assert rc is None and elapsed < 1.5, elapsed
    assert threading.active_count() == threads_before
    assert b"LATE" not in out and err == b""
    assert _gone(int(out.split()[0]))
    # Descriptors opened after the return get every byte written to them.
    time.sleep(1.0)  # past the moment the background process would have written
    pipes = [os.pipe() for _ in range(3)]
    for r, w in pipes:
        os.write(w, b"x" * 210)
        os.close(w)
    for r, _ in pipes:
        got = b""
        while chunk := os.read(r, 4096):
            got += chunk
        os.close(r)
        assert got == b"x" * 210


def test_normal_exit_returns_at_once_and_keeps_the_contract():
    started = time.monotonic()
    rc, out, err = ls._run_capped(
        ["bash", "-c", "(sleep 30 >/dev/null 2>&1 &); echo ok; echo e >&2; exit 4"],
        timeout=10, max_output_bytes=64 * 1024,
    )
    assert (rc, out, err) == (4, b"ok\n", b"e\n")
    assert time.monotonic() - started < 2


# ── host check always runs the image's check.py, isolated ──
def test_host_check_uses_image_copy(tmp_path, monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="OK misc", stderr="")

    monkeypatch.setattr(page_gate.subprocess, "run", fake_run)
    page_gate.run_host_check("<p>x</p>", "{}", tmp_path)
    assert seen["argv"][1] == "-I"
    assert seen["argv"][2] == str(page_gate.CHECK_SCRIPT_PATH)
    assert str(page_gate.CHECK_SCRIPT_PATH).endswith("agent/skills/check.py")
    assert (tmp_path / "validated-content.html").read_text() == "<p>x</p>"


def test_grpc_fork_support_disabled_by_package_import():
    """Sandbox spawns fork the host; gRPC's atfork handlers abort children."""
    env = {k: v for k, v in os.environ.items() if k != "GRPC_ENABLE_FORK_SUPPORT"}
    out = subprocess.run(
        [sys.executable, "-c",
         "import os, services.page_builder; print(os.environ['GRPC_ENABLE_FORK_SUPPORT'])"],
        env=env, capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "0"
