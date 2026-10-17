"""web_fetch SSRF guard (model_harness._guarded_fetch).

The fetch URL is chosen by the model, which reads untrusted text — a
prompt injection must not point the host's HTTP client at the metadata
server, localhost or private ranges, directly or through a redirect.
"""
import socket

import httpx
import pytest

from services.page_builder import model_harness as mh

PUBLIC = "93.184.216.34"


@pytest.fixture
def dns(monkeypatch):
    table = {
        "data.gov.il": [PUBLIC],
        "www.gov.il": [PUBLIC],
        "evil.example": ["169.254.169.254"],
        "rebind.example": [PUBLIC, "10.0.0.5"],
        "lan.example": ["192.168.1.10"],
        "cgnat.example": ["100.64.1.1"],
        "v6local.example": ["::1"],
        "v6mapped.example": ["::ffff:127.0.0.1"],
        "v6ll.example": ["fe80::1%eth0"],
        "mcast.example": ["224.0.0.1"],
        "zero.example": ["0.0.0.0"],
    }

    def fake_getaddrinfo(host, port, *a, **k):
        if host not in table:
            raise socket.gaierror(-2, "Name or service not known")
        out = []
        for ip in table[host]:
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            sockaddr = (ip, port, 0, 0) if fam == socket.AF_INET6 else (ip, port)
            out.append((fam, socket.SOCK_STREAM, 6, "", sockaddr))
        return out

    monkeypatch.setattr(mh.socket, "getaddrinfo", fake_getaddrinfo)
    return table


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://data.gov.il/x",
        "gopher://data.gov.il/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://metadata/computeMetadata/v1/",
        "http://localhost:8080/",
        "http://foo.localhost/",
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://10.1.2.3/",
        "http://172.16.0.1/",
        "http://192.168.0.1/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://evil.example/",
        "http://rebind.example/",
        "http://lan.example/",
        "http://cgnat.example/",
        "http://v6local.example/",
        "http://v6mapped.example/",
        "http://v6ll.example/",
        "http://mcast.example/",
        "http://zero.example/",
    ],
)
def test_blocked_urls(url, dns):
    err = mh._validate_fetch_url(url)
    assert err and err.startswith("blocked"), (url, err)


def test_public_urls_allowed(dns):
    assert mh._validate_fetch_url("https://data.gov.il/api/3/action/package_show?id=x") is None
    assert mh._validate_fetch_url("http://www.gov.il/he/departments") is None


def test_dns_failure_is_a_tool_error(dns):
    err = mh._validate_fetch_url("https://no-such-host.example/")
    assert err and "DNS lookup failed" in err


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_redirect_to_metadata_is_blocked(dns):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/computeMetadata/v1/"})

    r = mh._guarded_fetch(_client(handler), "https://data.gov.il/x", headers={}, timeout=5)
    assert isinstance(r, str) and r.startswith("blocked")
    assert seen == ["https://data.gov.il/x"]  # the internal hop was never requested


def test_relative_redirect_followed_and_revalidated(dns):
    def handler(req):
        if req.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return httpx.Response(200, text="final")

    r = mh._guarded_fetch(_client(handler), "https://data.gov.il/a", headers={}, timeout=5)
    assert not isinstance(r, str)
    assert r.status_code == 200 and r.text == "final"
    assert str(r.url) == "https://data.gov.il/b"


def test_redirect_loop_is_capped(dns):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(302, headers={"location": "https://data.gov.il/loop"})

    r = mh._guarded_fetch(_client(handler), "https://data.gov.il/loop", headers={}, timeout=5)
    assert isinstance(r, str) and "redirects" in r
    assert len(calls) == mh.WEB_FETCH_MAX_REDIRECTS + 1


def test_blocked_url_never_hits_network(dns):
    def handler(req):  # pragma: no cover - must not be reached
        raise AssertionError("request should not be sent")

    r = mh._guarded_fetch(_client(handler), "http://127.0.0.1:8080/", headers={}, timeout=5)
    assert isinstance(r, str) and r.startswith("blocked")


def test_numeric_host_forms_resolve_through_dns(monkeypatch):
    # `http://2130706433/` is 127.0.0.1 to the resolver — the guard checks
    # what getaddrinfo actually returns, not the spelling.
    monkeypatch.setattr(
        mh.socket, "getaddrinfo",
        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))],
    )
    err = mh._validate_fetch_url("http://2130706433/")
    assert err and err.startswith("blocked")
