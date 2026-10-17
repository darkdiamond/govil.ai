"""LocalSandbox privilege separation.

In the builder container the host process is root and every agent tool
command must drop to the unprivileged `sandbox` user, so a prompt-injected
command can't read the host's /proc/<pid>/environ secrets or rewrite the
image's check.py. Off-root (local dev, CI) nothing may change.
"""
import os
import subprocess
from types import SimpleNamespace

import pytest

from services.page_builder import agent_contract
from services.page_builder import local_sandbox as ls
from services.page_builder import model_harness as mh

UID, GID = 10001, 10001


class _RunRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, stdout=b"ok\n", stderr=b"")


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
    monkeypatch.setattr(ls.subprocess, "run", rec)
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


def test_adopt_after_handover_chowns_new_dirs(tmp_path, as_root):
    wd = tmp_path / "s1"
    sb = ls.LocalSandbox.create(wd)
    sb.run_code("true", language="bash")
    as_root.chowns.clear()
    (wd / "late").mkdir()
    f = wd / "late" / "x.csv"
    f.write_text("x")
    os.chmod(f, 0o600)
    sb.adopt(f)
    assert [p for p, *_ in as_root.chowns] == [str(wd / "late")]
    assert f.stat().st_mode & 0o004


def test_provision_path_adopts_into_sandbox(tmp_path):
    adopted = []
    sb = SimpleNamespace(workdir=tmp_path, adopt=lambda p: adopted.append(p))
    src = tmp_path.parent / f"{tmp_path.name}-src.csv"
    src.write_text("a\n1\n")
    try:
        mh._provision_path(sb, src, str(tmp_path / "data" / "data_1.csv"))
        mh._provision_file(sb, b"print(1)", str(tmp_path / "check.py"))
    finally:
        src.unlink()
    assert adopted == [
        (tmp_path / "data" / "data_1.csv").resolve(),
        (tmp_path / "check.py").resolve(),
    ]


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
    monkeypatch.setattr(ls.subprocess, "run", rec)
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


# ── host check always runs the image's check.py, isolated ──
def test_host_check_uses_image_copy(tmp_path, monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="OK misc", stderr="")

    monkeypatch.setattr(agent_contract.subprocess, "run", fake_run)
    agent_contract.run_host_check("<p>x</p>", "{}", tmp_path)
    assert seen["argv"][1] == "-I"
    assert seen["argv"][2] == str(agent_contract.CHECK_SCRIPT_PATH)
    assert str(agent_contract.CHECK_SCRIPT_PATH).endswith("agent/skills/check.py")
    assert (tmp_path / "validated-content.html").read_text() == "<p>x</p>"
