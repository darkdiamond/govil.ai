"""firebase.json cache rules: pages, data and feeds revalidate; hashed assets
stay immutable; no request path gets two Cache-Control rules.

Firebase matches header rules against the REQUEST path, so clean URLs
(/news/) are never covered by a `*.html` glob — that is how every page sat
on Firebase's default max-age=3600 until 2026-11-09.
"""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

FIREBASE = Path(__file__).resolve().parents[3] / "firebase.json"
REVALIDATE = "max-age=0, must-revalidate"


def _rules():
    out = []
    for r in json.loads(FIREBASE.read_text(encoding="utf-8"))["hosting"]["headers"]:
        cc = next((h["value"] for h in r["headers"] if h["key"].lower() == "cache-control"), None)
        if cc:
            out.append((r.get("regex"), r.get("source"), cc))
    return out


def _glob(pattern: str, path: str) -> bool:
    """Firebase's extglob subset used here: **, *, @(a|b)."""
    m = re.fullmatch(r"(.*)@\(([^)]*)\)(.*)", pattern)
    if m:
        return any(_glob(m[1] + alt + m[3], path) for alt in m[2].split("|"))
    return fnmatch.fnmatchcase(path, pattern.replace("**/", "*").replace("/**", "/*"))


def _cache_for(path: str) -> str | None:
    """The Cache-Control Firebase serves: rules apply in order and the LAST
    match wins (verified live 2026-11-09: /_nuxt/*.js matches both the js/css
    rule and the later /_nuxt/** rule and is served immutable)."""
    hit = None
    for regex, source, cc in _rules():
        if (regex and re.search(regex, path)) or (source and _glob(source, path)):
            hit = cc
    return hit


def test_pages_data_and_feeds_revalidate():
    for path in ["/", "/news/", "/news/some-article/", "/datasets/x-1/", "/tags/דיור/",
                 "/news/index.json", "/news/some-article/article.json", "/data/manifest.json",
                 "/datasets/abc/data.json", "/sitemap.xml", "/news-sitemap.xml", "/news/feed.xml"]:
        cc = _cache_for(path)
        assert cc and REVALIDATE in cc, (path, cc)


def test_hashed_assets_stay_immutable():
    for path in ["/_nuxt/entry.abc123.js", "/_nuxt/builds/meta/61950048.json",
                 "/news/x/hero-16x9-cf5d863a94.jpg", "/fonts/rubik.woff2"]:
        cc = _cache_for(path)
        assert cc and "immutable" in cc, (path, cc)
