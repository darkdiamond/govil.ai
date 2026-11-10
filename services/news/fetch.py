"""Fetch a public web page as text, for the writer's sources.

The news job holds a service-account token reachable through the metadata
server, and the URLs come from a model reading the open web, so every hop is
checked: https only, standard port, every resolved address public (no
loopback, private, link-local — 169.254.169.254 — reserved or multicast),
redirects re-checked hop by hop, a size cap, HTML/text only. Page text is
data for the model, never markup for our pages.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

UA = "Mozilla/5.0 (compatible; govdata-news/1.0; +https://govil.ai/news/about/)"
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 4
TIMEOUT = 20.0          # per network operation
TOTAL_TIMEOUT = 60.0    # wall clock for the whole fetch, redirects included
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class FetchRefused(Exception):
    """The URL is not one we fetch (scheme, host, address, size, type)."""


# Sites the writer may read and cite. Only their text enters the agent's
# context (search results from elsewhere are dropped too), which keeps
# arbitrary pages — and any instructions planted in them — out of an
# unreviewed article. NEWS_SOURCE_DOMAINS (comma-separated) replaces the list.
DEFAULT_SOURCE_DOMAINS = (
    # official
    "gov.il", "boi.org.il", "knesset.gov.il", "idf.il", "court.gov.il",
    # research
    "idi.org.il", "taubcenter.org.il", "oecd.org", "imf.org", "worldbank.org", "bis.org",
    # established news
    "ynet.co.il", "haaretz.co.il", "themarker.com", "calcalist.co.il", "globes.co.il",
    "maariv.co.il", "walla.co.il", "mako.co.il", "n12.co.il", "kan.org.il", "israelhayom.co.il",
    "bizportal.co.il", "davar1.co.il", "timesofisrael.com", "jpost.com", "reuters.com",
    "apnews.com", "bloomberg.com", "ft.com", "bbc.com", "bbc.co.uk",
)


def source_domains() -> tuple[str, ...]:
    import os

    env = os.environ.get("NEWS_SOURCE_DOMAINS", "").strip()
    return tuple(d.strip().lower().lstrip(".") for d in env.split(",") if d.strip()) if env \
        else DEFAULT_SOURCE_DOMAINS


OFFICIAL_DOMAINS = ("gov.il", "boi.org.il")   # gov.il covers data.gov.il, cbs.gov.il, knesset.gov.il …


def official_source(url: str) -> bool:
    """A government data publisher's page — the only kind of page an article
    may link (everything else the writer reads is context only)."""
    return allowed_source(url, OFFICIAL_DOMAINS)


def allowed_source(url: str, domains: tuple[str, ...] | None = None) -> bool:
    """A plain web URL on an allowed domain. The scheme, credentials and port
    are checked too: these URLs become links on our pages, so a
    `javascript://www.gov.il/…` must never pass on its host alone."""
    # Parser differentials: a browser (WHATWG) reads `https://evil.com\.gov.il/`
    # as host evil.com, Python's urlparse as host evil.com\.gov.il. So no
    # backslash, whitespace or control characters anywhere, and the authority
    # must be a plain DNS name (optionally :port) before the suffix check.
    if not isinstance(url, str) or _UNSAFE_URL_CHARS.search(url):
        return False
    try:
        u = urlparse(url)
        port = u.port
    except ValueError:
        return False
    if u.scheme not in ("https", "http") or u.username or u.password or port not in (None, 80, 443):
        return False
    if not _AUTHORITY.fullmatch(u.netloc.lower()):
        return False
    host = (u.hostname or "").rstrip(".").lower()
    return any(host == d or host.endswith("." + d) for d in (domains or source_domains()))


_UNSAFE_URL_CHARS = re.compile(r"[\\\s\x00-\x1f\x7f]")
_AUTHORITY = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\.?(?::\d{1,5})?")


@dataclass
class Page:
    url: str          # final URL after redirects
    title: str
    text: str


def _check_url(url: str, resolve=socket.getaddrinfo) -> str:
    """Vet the URL and return the address to connect to. The host is
    resolved once here and the connection goes to that address, so a second
    DNS answer (rebinding) can't point it somewhere else."""
    u = urlparse(url)
    if u.scheme != "https":
        raise FetchRefused(f"only https is fetched: {url[:80]}")
    if not u.hostname or u.username or u.password:
        raise FetchRefused("no host, or credentials in the URL")
    if u.port not in (None, 443):
        raise FetchRefused(f"non-standard port {u.port}")
    host = u.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise FetchRefused(f"internal host {host}")
    try:
        infos = resolve(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise FetchRefused(f"cannot resolve {host}") from e
    ips = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not ips:
        raise FetchRefused(f"cannot resolve {host}")
    for ip in ips:
        if not ip.is_global or ip.is_multicast:
            raise FetchRefused(f"{host} resolves to a non-public address")
    # Cloud Run egress is IPv4, so prefer an IPv4 address when there is one.
    return str(next((ip for ip in ips if ip.version == 4), ips[0]))


def html_to_text(html: str) -> tuple[str, str]:
    """(title, readable text) — scripts, styles and page chrome dropped."""
    import lxml.html

    try:
        doc = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):
        return "", ""
    title = (doc.findtext(".//title") or "").strip()
    for bad in doc.xpath("//script|//style|//noscript|//nav|//footer|//header|//form|//svg|//iframe"):
        bad.drop_tree()
    text = doc.text_content()
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return title, text.strip()


def fetch_page(url: str, *, client: httpx.Client | None = None, resolve=socket.getaddrinfo,
               clock=time.monotonic) -> Page:
    own = client is None
    # No keep-alive: a pooled connection is keyed by IP, and one verified for
    # one hostname must not carry a request for another on the same address.
    client = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=False,
                                    limits=httpx.Limits(max_keepalive_connections=0))
    deadline = clock() + TOTAL_TIMEOUT
    try:
        for _ in range(MAX_REDIRECTS + 1):
            addr = _check_url(url, resolve)
            if not allowed_source(url):
                raise FetchRefused("not on the source allowlist (NEWS_SOURCE_DOMAINS)")
            if clock() > deadline:
                raise FetchRefused("fetch took longer than the time limit")
            # Connect to the vetted address; TLS SNI, certificate verification
            # and the Host header still use the hostname.
            target = httpx.URL(url)
            with client.stream("GET", target.copy_with(host=addr), headers={"Host": target.netloc.decode("ascii")},
                               extensions={"sni_hostname": target.host}) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    raise FetchRefused(f"HTTP {r.status_code}")
                ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
                if ctype not in _TEXT_TYPES:
                    raise FetchRefused(f"content type {ctype or 'unknown'} is not a text page")
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise FetchRefused("page larger than the size cap")
                    if clock() > deadline:
                        raise FetchRefused("fetch took longer than the time limit")
                raw = body.decode(r.encoding or "utf-8", errors="replace")
                if ctype == "text/plain":
                    return Page(url, "", raw.strip())
                title, text = html_to_text(raw)
                return Page(url, title, text)
        raise FetchRefused("too many redirects")
    finally:
        if own:
            client.close()
