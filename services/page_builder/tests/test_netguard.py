"""netguard: recipe compute gets no network (seccomp-bpf, Linux x86_64).

The filter is irreversible, so every test that installs it does so in a child
process, never in the pytest process.
"""
from __future__ import annotations

import csv
import json
import platform
import shutil
import socket
import struct
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from services.page_builder import netguard
from services.page_builder import refresh as rf
from services.page_builder.recipe import Recipe, RecipeError
from services.page_builder.tests.test_recipe_refresh import (  # noqa: F401
    COLS,
    DS,
    FIXTURES,
    RID,
    FakeCkan,
    FakeStore,
    _bump,
    _rows,
    _run,
    _src,
    env,
)
from services.shared.states import FailReason

SUPPORTED = platform.system() == "Linux" and platform.machine() == "x86_64"
linux_x86_64 = pytest.mark.skipif(not SUPPORTED, reason="netguard is Linux x86_64 only")

# ── the BPF program, emulated (runs anywhere) ────────────────────────────

ALLOW, KILL, EPERM = 0x7FFF0000, 0x80000000, 0x00050001


def _emulate(nr, arch=0xC000003E, arg0=0):
    """Run netguard's BPF program on one seccomp_data; return the action."""
    data = struct.pack("=iIQ6Q", nr, arch, 0, arg0, 0, 0, 0, 0, 0)
    prog = [struct.unpack("=HBBI", ins) for ins in netguard.build_filter()]
    pc, acc = 0, 0
    for _ in range(len(prog) + 1):
        code, jt, jf, k = prog[pc]
        if code == 0x20:
            acc = struct.unpack_from("=I", data, k)[0]
            pc += 1
        elif code == 0x15:
            pc += 1 + (jt if acc == k else jf)
        elif code == 0x35:
            pc += 1 + (jt if acc >= k else jf)
        elif code == 0x06:
            return k
        else:
            raise AssertionError(f"unexpected BPF opcode {code:#x}")
    raise AssertionError("BPF program did not return")


def test_filter_decisions():
    assert _emulate(41, arg0=1) == ALLOW            # socket(AF_UNIX)
    for domain in (2, 10, 16, 17, 0, 0x100000001):  # INET, INET6, NETLINK, PACKET, ...
        assert _emulate(41, arg0=domain) == (ALLOW if domain & 0xFFFFFFFF == 1 else EPERM)
    assert _emulate(53, arg0=1) == ALLOW            # socketpair
    for nr in (101, 310, 311, 425, 426, 427):
        assert _emulate(nr) == EPERM
    for nr in (0, 1, 2, 42, 56, 57, 59, 231, 257, 317):  # read, write, connect, clone, ...
        assert _emulate(nr) == ALLOW
    assert _emulate(41 | 0x40000000, arg0=2) == EPERM   # x32 ABI socket
    assert _emulate(0x40000000) == EPERM
    assert _emulate(41, arch=0x40000003, arg0=1) == KILL  # i386
    assert len(netguard.build_filter()) < 64


def test_install_refuses_other_machines(monkeypatch):
    monkeypatch.setattr(netguard.platform, "machine", lambda: "aarch64")
    with pytest.raises(RuntimeError, match="x86_64 only"):
        netguard.install()


# ── the real filter, in a child ──────────────────────────────────────────

_PROBES = textwrap.dedent("""
    import json, os, socket, subprocess, sys, threading, time, urllib.request
    port = int(sys.argv[1])
    out = {}

    def denied(fn):
        try:
            fn()
        except PermissionError:
            return True
        except OSError as e:
            return repr(e)
        return False

    out["inet"] = denied(lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
    out["inet_udp"] = denied(lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
    out["inet6"] = denied(lambda: socket.socket(socket.AF_INET6))
    out["connect_local"] = denied(lambda: socket.create_connection(("127.0.0.1", port), 2))
    s = socket.socket(socket.AF_UNIX); s.close()
    a, b = socket.socketpair(); a.sendall(b"x"); out["socketpair"] = b.recv(1) == b"x"
    t0 = time.monotonic()
    try:
        urllib.request.urlopen("http://169.254.169.254/", timeout=10)
        out["metadata"] = False
    except Exception as e:
        reason = getattr(e, "reason", e)
        out["metadata"] = isinstance(reason, PermissionError)
    out["metadata_s"] = time.monotonic() - t0
    child = "import socket; socket.socket(socket.AF_INET)"
    out["subprocess_rc"] = subprocess.run([sys.executable, "-c", child],
                                          capture_output=True).returncode
    # Deliberately a shell: the filter must bind processes a shell starts too.
    out["os_system_rc"] = os.system(f"{sys.executable} -c '{child}' 2>/dev/null")
    res = {}
    def worker():
        res["sum"] = sum(range(1000))
        res["inet"] = denied(lambda: socket.socket(socket.AF_INET))
    th = threading.Thread(target=worker); th.start(); th.join()
    out["thread"] = res

    import numpy as np
    import pandas as pd
    df = pd.DataFrame({"k": ["a", "b", "a"], "v": [1, 2, 3],
                       "d": ["2024-01-01", "2024-02-01", "2024-03-01"]})
    df["d"] = pd.to_datetime(df["d"])
    g = df.groupby("k")["v"].sum().reset_index()
    m = df.merge(g, on="k", suffixes=("", "_sum"))
    back = pd.read_json(__import__("io").StringIO(m.to_json(orient="records")))
    out["pandas"] = [int(x) for x in back["v_sum"]] == [4, 2, 4] and float(np.mean(df["v"])) == 2.0
    print(json.dumps(out))
""")


def _listener():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    return srv


def _run_child(code: str, port: int) -> dict:
    r = subprocess.run([sys.executable, "-c", code, str(port)],
                       check=False, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@linux_x86_64
def test_no_network_after_install():
    with _listener() as srv:
        out = _run_child(netguard.child_prologue() + _PROBES, srv.getsockname()[1])
    assert out["inet"] is True and out["inet_udp"] is True and out["inet6"] is True
    assert out["connect_local"] is True
    assert out["socketpair"] is True
    assert out["metadata"] is True and out["metadata_s"] < 2  # refused, not timed out
    assert out["subprocess_rc"] != 0 and out["os_system_rc"] != 0  # inherited
    assert out["thread"] == {"sum": 499500, "inet": True}
    assert out["pandas"] is True


@linux_x86_64
def test_same_probes_without_the_filter_reach_the_network():
    """Control: the denials above come from netguard, not from the test host."""
    with _listener() as srv:
        out = _run_child(_PROBES, srv.getsockname()[1])
    assert out["inet"] is False and out["inet6"] is False
    assert out["connect_local"] is False
    assert out["subprocess_rc"] == 0 and out["os_system_rc"] == 0


@linux_x86_64
def test_filter_cannot_be_lifted():
    code = netguard.child_prologue() + textwrap.dedent("""
        import ctypes, socket
        libc = ctypes.CDLL(None, use_errno=True)
        # PR_SET_NO_NEW_PRIVS can't be cleared; seccomp mode can't drop to 0.
        print(libc.prctl(38, 0, 0, 0, 0), libc.prctl(22, 0, 0, 0, 0))
        try:
            socket.socket(socket.AF_INET)
            print("open")
        except PermissionError:
            print("denied")
    """)
    r = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    first, last = r.stdout.split("\n")[:2]
    assert "0" not in first.split() and last == "denied"


def test_prologue_failure_is_reported():
    """An install that raises exits INSTALL_FAILED_EXIT with the marker, and
    nothing after the prologue runs."""
    code = _failing_prologue() + "print('recipe code ran')\n"
    r = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True, timeout=60)
    assert r.returncode == netguard.INSTALL_FAILED_EXIT
    assert "recipe code ran" not in r.stdout
    assert netguard.install_failed(f"exit code {r.returncode}", r.stderr)
    assert not netguard.install_failed("exit code 1", r.stderr)
    assert not netguard.install_failed(f"exit code {r.returncode}", "Traceback ...")


_REAL_PROLOGUE = netguard.child_prologue


def _failing_prologue() -> str:
    return _REAL_PROLOGUE().replace(
        "def install():",
        "def install():\n    raise OSError(1, 'simulated')\n\n\ndef _install_unused():",
        1,
    )


# ── the refresh's knob and failure mapping ───────────────────────────────


def test_knob_default_denies(monkeypatch):
    monkeypatch.delenv("REFRESH_COMPUTE_NETWORK", raising=False)
    assert rf._network_guard() == netguard.child_prologue()
    monkeypatch.setenv("REFRESH_COMPUTE_NETWORK", "nonsense")  # fail closed
    assert rf._network_guard() == netguard.child_prologue()


def test_knob_allow_installs_nothing(monkeypatch, caplog):
    monkeypatch.setenv("REFRESH_COMPUTE_NETWORK", "allow")
    monkeypatch.setattr(rf, "_network_allow_warned", False)
    with caplog.at_level("WARNING"):
        assert rf._network_guard() == ""
        assert rf._network_guard() == ""
    assert sum("REFRESH_COMPUTE_NETWORK=allow" in r.message for r in caplog.records) == 1


def _probe_recipe(tmp_path: Path) -> Recipe:
    """The fixture recipe, with compute() also reporting whether it got a socket."""
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    c = recipes / DS / "compute.py"
    c.write_text(
        c.read_text() + (
            "\n\n_real = compute\n\n\n"
            "def compute(frames):\n"
            "    import socket\n"
            "    model = _real(frames)\n"
            "    try:\n"
            "        socket.socket(socket.AF_INET).close()\n"
            "        model['probe'] = 'open'\n"
            "    except PermissionError:\n"
            "        model['probe'] = 'denied'\n"
            "    return model\n"
        ),
        encoding="utf-8",
    )
    return Recipe.load(recipes / DS)


def _compute(tmp_path, recipe):
    f = tmp_path / "in.csv"
    with open(f, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        w.writerows([[2025, m, "צפון", 10] for m in range(1, 13)])
    part = rf.FetchedInput(file=f, resource_id=RID, resource_name="events", rows=12)
    return rf.run_compute(recipe, {recipe.manifest.inputs[0].name: [part]}, tmp_path / "work")


@linux_x86_64
def test_run_compute_denies_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("REFRESH_COMPUTE_NETWORK", raising=False)
    assert _compute(tmp_path, _probe_recipe(tmp_path))["probe"] == "denied"


def test_run_compute_allow_keeps_the_network(tmp_path, monkeypatch):
    monkeypatch.setenv("REFRESH_COMPUTE_NETWORK", "allow")
    assert _compute(tmp_path, _probe_recipe(tmp_path))["probe"] == "open"


def test_install_failure_is_sandbox_failed(tmp_path, monkeypatch):
    monkeypatch.delenv("REFRESH_COMPUTE_NETWORK", raising=False)
    monkeypatch.setattr(rf.netguard, "child_prologue", _failing_prologue)
    with pytest.raises(RecipeError) as ei:
        _compute(tmp_path, Recipe.load(FIXTURES / DS))
    assert ei.value.reason == FailReason.SANDBOX_FAILED


def test_install_failure_keeps_the_page_and_opens_no_issue(env, monkeypatch):  # noqa: F811
    monkeypatch.delenv("REFRESH_COMPUTE_NETWORK", raising=False)
    store = FakeStore(_src())
    assert _run(env, store, FakeCkan(_rows([2024, 2025])))["refreshed"] == [DS]
    staged = dict(env.staged)
    _bump(store, "2026-11-01")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(rf.netguard, "child_prologue", _failing_prologue)
        s = _run(env, store, FakeCkan(_rows([2024, 2025, 2026])))
    assert s["outcomes"][0]["reason"] == "sandbox_failed"
    assert env.issues == [] and env.staged == staged
    # Not locked: once the platform is fixed the same data renders.
    s = _run(env, store, FakeCkan(_rows([2024, 2025, 2026])))
    assert s["refreshed"] == [DS]
