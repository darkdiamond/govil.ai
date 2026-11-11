"""clarity_analyze: --out handling and quota-safe retries (HTTP layer stubbed)."""
from __future__ import annotations

import httpx
import pytest
from tenacity import wait_none

from services.page_builder.cli import clarity_analyze as ca


@pytest.fixture
def calls(monkeypatch):
    """Stub the Clarity HTTP call; the test sets `calls.respond` to shape replies."""
    state = type("Calls", (), {"n": 0, "respond": None})()

    async def fake_get(self, url, params=None, headers=None):
        state.n += 1
        if state.respond is not None:
            return state.respond(url)
        return httpx.Response(200, json=[{"metricName": "Traffic"}],
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(ca, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(ca, "INTER_REQUEST_DELAY_S", 0)
    monkeypatch.setattr(ca._fetch.retry, "wait", wait_none())
    monkeypatch.setenv("GOVIL_CLARITY_API", "test-token")
    return state


def test_out_outside_repo_writes_readme(tmp_path, calls):
    out = tmp_path / "clarity"
    assert ca.main(["--out", str(out)]) == 0
    (readme,) = out.glob("README*")
    assert str(out) in readme.read_text(encoding="utf-8")
    assert calls.n == len(ca.REQUESTS)


def test_relative_out_writes_readme(tmp_path, monkeypatch, calls):
    monkeypatch.chdir(tmp_path)
    assert ca.main(["--out", "rel/clarity"]) == 0
    assert list((tmp_path / "rel" / "clarity").glob("README*"))


def test_unusable_out_fails_before_any_request(tmp_path, calls):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    assert ca.main(["--out", str(blocker / "clarity")]) == 2
    assert ca.main(["--out", str(blocker)]) == 2
    assert calls.n == 0


def test_read_timeout_is_not_retried(tmp_path, calls):
    def timeout(url):
        raise httpx.ReadTimeout("read timed out", request=httpx.Request("GET", url))

    calls.respond = timeout
    assert ca.main(["--out", str(tmp_path / "clarity")]) == 1
    assert calls.n == len(ca.REQUESTS)


def test_connect_error_is_retried(tmp_path, calls):
    def refused(url):
        raise httpx.ConnectError("refused", request=httpx.Request("GET", url))

    calls.respond = refused
    assert ca.main(["--out", str(tmp_path / "clarity")]) == 1
    assert calls.n == 3 * len(ca.REQUESTS)
