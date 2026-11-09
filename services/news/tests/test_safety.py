"""The two boundaries between model output and the job's environment: the
SQL tool (DuckDB locked down) and the URL fetcher (SSRF guard)."""
from __future__ import annotations

import socket

import pandas as pd
import pytest

from services.news.fetch import FetchRefused, _check_url, fetch_page, html_to_text
from services.news.query import QueryError, TableQuery


@pytest.fixture
def q():
    pytest.importorskip("duckdb")
    t = TableQuery({"t": pd.DataFrame({"year": ["2024", "2025", "2025"], "city": ["א", "ב", "א"],
                                       "n": ["1,200", "5", "7"]})})
    yield t
    t.close()


def test_select_works_and_numbers_are_typed(q):
    out = q.run("SELECT year, SUM(n) AS s FROM t GROUP BY year ORDER BY year")
    assert out["columns"] == ["year", "s"]
    assert out["rows"] == [[2024, 1200.0], [2025, 12.0]]
    assert dict(q.schema["t"])["city"] == "VARCHAR"


def test_row_cap(q):  # q: skips when duckdb is absent
    small = TableQuery({"t": pd.DataFrame({"x": [str(i) for i in range(200)]})}, max_rows=10)
    out = small.run("SELECT x FROM t")
    assert len(out["rows"]) == 10 and out["truncated"]


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_text('/etc/hostname')",
    "SELECT * FROM 'https://example.com/x.csv'",
    "COPY t TO 'out.csv'",
    "SELECT 1; SELECT 2",
    "INSTALL httpfs",
    "LOAD httpfs",
    "SET enable_external_access = true",
    "ATTACH 'other.db'",
    "CREATE TABLE z AS SELECT 1",
    "DROP TABLE t",
    "PRAGMA database_list",
    "SELECT * FROM glob('/*')",
])
def test_refused(q, sql):
    with pytest.raises(QueryError):
        q.run(sql)


def test_timeout_interrupts():
    pytest.importorskip("duckdb")
    t = TableQuery({"t": pd.DataFrame({"x": [str(i) for i in range(10)]})}, timeout_s=0.5)
    with pytest.raises(QueryError, match="longer"):
        t.run("SELECT count(*) FROM range(1000000000000) a, range(1000) b")


def _resolver(addr):
    def resolve(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", (addr, port))]
    return resolve


@pytest.mark.parametrize("url, addr", [
    ("http://example.com/", "93.184.216.34"),          # not https
    ("https://example.com:8443/", "93.184.216.34"),    # odd port
    ("https://user:pw@example.com/", "93.184.216.34"),
    ("https://metadata.google.internal/", "169.254.169.254"),
    ("https://evil.example/", "169.254.169.254"),       # public name, metadata address
    ("https://evil.example/", "10.0.0.5"),
    ("https://evil.example/", "127.0.0.1"),
    ("https://evil.example/", "192.168.1.1"),
    ("https://localhost/", "127.0.0.1"),
])
def test_ssrf_guard(url, addr):
    with pytest.raises(FetchRefused):
        _check_url(url, _resolver(addr))


def test_public_https_passes():
    _check_url("https://www.cbs.gov.il/he/Pages/default.aspx", _resolver("104.18.1.1"))


def test_redirect_to_metadata_is_refused():
    import httpx

    def handler(req):
        if req.url.host == "ok.example":
            return httpx.Response(302, headers={"location": "https://meta.example/computeMetadata/v1/"})
        return httpx.Response(200, text="token", headers={"content-type": "text/plain"})

    def resolve(host, port, proto=0):
        addr = "169.254.169.254" if host == "meta.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", (addr, port))]

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    with pytest.raises(FetchRefused, match="non-public"):
        fetch_page("https://ok.example/a", client=client, resolve=resolve)


def test_html_to_text_drops_scripts_and_chrome():
    pytest.importorskip("lxml")
    title, text = html_to_text("<html><head><title>כותרת</title><script>x()</script></head>"
                               "<body><nav>תפריט</nav><p>הלמ\"ס פרסמה</p><footer>f</footer></body></html>")
    assert title == "כותרת" and "פרסמה" in text and "x()" not in text and "תפריט" not in text
