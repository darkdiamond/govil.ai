"""services/shared: the GitHub helpers, the CKAN User-Agent, and import hygiene
(the shared layer and the packages below page_builder must not pull it in)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.shared import ckan, github

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_default_repo_and_token_come_from_the_env(monkeypatch):
    monkeypatch.delenv("PUBLISH_GITHUB_REPO", raising=False)
    monkeypatch.delenv("GITHUB_DISPATCH_TOKEN", raising=False)
    assert github.default_repo() == github.DEFAULT_REPO and github.token() == ""
    monkeypatch.setenv("PUBLISH_GITHUB_REPO", "o/r")
    monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", " tok \n")
    assert github.default_repo() == "o/r" and github.token() == "tok"


def test_api_headers_carry_the_token_only_when_given():
    assert "Authorization" not in github.api_headers(None)
    assert github.api_headers("t")["Authorization"] == "Bearer t"
    assert github.api_headers("t")["X-GitHub-Api-Version"] == "2022-11-28"


def test_dispatch_without_a_token_sends_nothing(monkeypatch):
    monkeypatch.delenv("GITHUB_DISPATCH_TOKEN", raising=False)
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("posted"))
    assert github.dispatch_workflow("o/r", "publish.yml", "main") is None


@pytest.mark.parametrize("status, expected", [
    (204, "gh-actions:o/r/publish.yml@main"),
    (422, None),
])
def test_dispatch_posts_the_ref_and_follows_redirects(monkeypatch, status, expected):
    monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "tok")
    import httpx

    seen = {}

    def post(url, **kw):
        seen.update(url=url, **kw)
        return SimpleNamespace(status_code=status, text="no")

    monkeypatch.setattr(httpx, "post", post)
    assert github.dispatch_workflow("o/r", "publish.yml", "main") == expected
    assert seen["url"] == "https://api.github.com/repos/o/r/actions/workflows/publish.yml/dispatches"
    assert seen["json"] == {"ref": "main"} and seen["follow_redirects"] is True
    assert seen["headers"]["Authorization"] == "Bearer tok"


def test_user_agent_is_read_at_call_time(monkeypatch):
    monkeypatch.delenv("CKAN_USER_AGENT", raising=False)
    assert ckan.user_agent() == "Mozilla/5.0 (compatible; govdata-builder/1.0)"
    monkeypatch.setenv("CKAN_USER_AGENT", "  X/1  ")
    assert ckan.user_agent() == "X/1"


def test_lower_packages_do_not_import_page_builder():
    """providers and the scanner's CKAN client sit below page_builder; the
    shared modules must stay light (no page_builder, scanner, or firestore)."""
    code = (
        "import sys\n"
        "import services.providers, services.scanner.client\n"
        "import services.shared.ckan, services.shared.fetch_types, services.shared.github\n"
        "import services.shared.model_history, services.shared.states\n"
        "import services.shared.lease, services.shared.schedule\n"
        "bad = sorted(m for m in sys.modules if m.startswith('services.page_builder'))\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=REPO_ROOT)


def test_shared_modules_import_nothing_heavy():
    code = (
        "import sys\n"
        "import services.shared.ckan, services.shared.fetch_types, services.shared.github\n"
        "import services.shared.model_history, services.shared.states\n"
        "import services.shared.lease, services.shared.schedule\n"
        "bad = sorted(m for m in sys.modules if m.startswith(('services.scanner',"
        " 'services.page_builder', 'google.cloud.', 'google.api_core', 'grpc', 'httpx',"
        " 'pydantic')))\n"  # bare `google`/`google.cloud` come from a site .pth

        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=REPO_ROOT)
