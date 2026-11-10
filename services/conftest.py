"""Suite-wide test speedups that don't change what is tested."""
from __future__ import annotations

import hashlib
import os

import pytest

from services.page_builder import page_gate, refresh

_PASS = "PASS"


def pytest_xdist_auto_num_workers(config):
    """`-n auto` (pytest.ini) runs in-process when only named tests were asked for.

    Spawning a worker per core costs ~4s of startup + collection, more than a
    handful of `file::test` nodes take to run. Directory/file runs still fan out.
    """
    args = config.args
    if args and all("::" in a for a in args):
        return 0
    return None  # fall through to xdist's default (one per core)


@pytest.fixture(autouse=True, scope="session")
def _memoize_host_check(tmp_path_factory, worker_id):
    """Run the real check.py once per distinct page, not once per render.

    The refresh/verify tests render the same fixture pages over and over
    (~124 check.py spawns for ~19 distinct pages, ~0.3s each). check.py is
    a pure function of its two input files and its own source, so the cache
    key is exactly those bytes; a failing check is cached and re-raised.
    The cache lives in the session's tmp root, shared by all xdist workers.
    Only `refresh.run_host_check` (the name the refresh pipeline and `author
    verify` call) is wrapped; tests of `page_gate.run_host_check`
    itself still spawn it every time.
    """
    real = page_gate.run_host_check
    root = tmp_path_factory.getbasetemp()
    if worker_id != "master":
        root = root.parent  # pytest-N/, the parent of every worker's basetemp
    cache = root / "host-check-memo"
    cache.mkdir(exist_ok=True)

    def memoized(content_html, agent_data_json, workdir, *, recipe=False):
        h = hashlib.sha256()
        # Length-prefixed, so no two different inputs can share a key.
        for part in (page_gate.CHECK_SCRIPT_PATH.read_bytes(),
                     content_html.encode("utf-8"), agent_data_json.encode("utf-8"),
                     str(recipe).encode()):
            h.update(len(part).to_bytes(8, "big") + part)
        entry = cache / h.hexdigest()
        if entry.is_file():
            result = entry.read_text(encoding="utf-8")
        else:
            try:
                real(content_html, agent_data_json, workdir, recipe=recipe)
                result = _PASS
            except RuntimeError as e:
                result = str(e)
            tmp = entry.with_suffix(f".{os.getpid()}")
            tmp.write_text(result, encoding="utf-8")
            os.replace(tmp, entry)  # atomic: a concurrent reader sees all or nothing
        if result != _PASS:
            raise RuntimeError(result)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(refresh, "run_host_check", memoized)
        yield


@pytest.fixture(autouse=True)
def _no_retry_pass_wait(monkeypatch):
    """The refresh's end-of-run retry pass waits REFRESH_RETRY_DELAY_S (120s)
    for CKAN to recover; tests that want the wait inject `sleep`."""
    monkeypatch.setenv("REFRESH_RETRY_DELAY_S", "0")
