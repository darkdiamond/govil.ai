"""Suite-wide test speedups that don't change what is tested."""
from __future__ import annotations

import hashlib
import os

import pytest

from services.page_builder import agent_contract, refresh

_PASS = "PASS"


@pytest.fixture(autouse=True, scope="session")
def _memoize_host_check(tmp_path_factory):
    """Run the real check.py once per distinct page, not once per render.

    The refresh/verify tests render the same fixture pages over and over
    (~124 check.py spawns for ~19 distinct pages, ~0.3s each). check.py is
    a pure function of its two input files and its own source, so the cache
    key is exactly those bytes; a failing check is cached and re-raised.
    The cache lives in the session's tmp root, shared by all xdist workers.
    Only `refresh.run_host_check` (the name the refresh pipeline and `author
    verify` call) is wrapped; tests of `agent_contract.run_host_check`
    itself still spawn it every time.
    """
    real = agent_contract.run_host_check
    script = agent_contract.CHECK_SCRIPT_PATH.read_bytes()
    root = tmp_path_factory.getbasetemp()
    if os.environ.get("PYTEST_XDIST_WORKER"):
        root = root.parent  # pytest-N/, the parent of every worker's basetemp
    cache = root / "host-check-memo"
    cache.mkdir(exist_ok=True)

    def memoized(content_html, agent_data_json, workdir, *, recipe=False):
        h = hashlib.sha256(script)
        for part in (content_html, agent_data_json, str(recipe)):
            h.update(b"\0" + part.encode("utf-8"))
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
