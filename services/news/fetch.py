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
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

UA = "Mozilla/5.0 (compatible; govdata-news/1.0; +https://govil.ai/news/about/)"
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 4
TIMEOUT = 20.0
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class FetchRefused(Exception):
    """The URL is not one we fetch (scheme, host, address, size, type)."""


@dataclass
class Page:
    url: str          # final URL after redirects
    title: str
    text: str


def _check_url(url: str, resolve=socket.getaddrinfo) -> None:
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
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise FetchRefused(f"{host} resolves to a non-public address")


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


def fetch_page(url: str, *, client: httpx.Client | None = None, resolve=socket.getaddrinfo) -> Page:
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=False)
    try:
        for _ in range(MAX_REDIRECTS + 1):
            _check_url(url, resolve)
            with client.stream("GET", url) as r:
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
                raw = body.decode(r.encoding or "utf-8", errors="replace")
                if ctype == "text/plain":
                    return Page(url, "", raw.strip())
                title, text = html_to_text(raw)
                return Page(url, title, text)
        raise FetchRefused("too many redirects")
    finally:
        if own:
            client.close()
