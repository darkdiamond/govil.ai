#!/usr/bin/env python3
"""Self-check for agent-emitted content.html + agent_data.json.

Invoked by the agent before end_turn:
    python3 /workspace/check.py content.html agent_data.json

Exits 0 with "OK" on success; non-zero with a one-line diagnostic on
failure. The agent fixes the offending file and re-runs.

This script is the single source of truth for the post-output rules
listed in the system prompt. The publisher's `_sanitize_content_html`
auto-fixes a subset (CDN scripts, escaped </script>, integrity attrs,
unbalanced tags, JS-string control chars), but does NOT cover the
quality/truth classes here — palette correctness, Heebo refs, max-w-*
outers, missing icon headers, missing <ul>/<li> insights, the 50KB
inline-data cap, percent-conflict across year contexts. Hence the
runtime check.

Copied into each session's private workdir (CHECK_SCRIPT in
services/page_builder/agent_contract.py) so the agent can self-check
in-session, and run again host-side on the sanitized body by
services/page_builder/agent_runner.py before anything persists.
"""
from __future__ import annotations

import json
import re
import sys

# Pure-Python ES parser backing the JS-SYNTAX catch-all below (there is
# no Node in the builder image). Optional import so this script still
# runs standalone elsewhere; without it the parse gate no-ops, which is
# why services/page_builder/requirements.txt pins it and
# services/page_builder/tests/test_check_js_parse.py asserts it is
# importable — the gate must not silently vanish from prod.
try:
    import esprima as _esprima
except ImportError:  # pragma: no cover - exercised via monkeypatch
    _esprima = None

VALID_DATASET_KINDS = {"map", "timeseries", "registry", "rankings", "misc"}

# HTML hygiene — combined regex for forbidden tags / attrs / classes /
# colors / hosts. Keeping these in one pass mirrors the original bash
# grep so a regression on any one of them is reported with the same
# message.
HYGIENE_RE = re.compile(
    r"<(?:html|head|body|header|footer|nav)\b"
    r"|<link\b"
    r"|<script[^>]*\bsrc="
    r'|\bintegrity\s*='
    r"|\bcrossorigin\b"
    r"|<\\/script"
    r'|class="[^"]*\bmax-w-(?:6xl|7xl|3xl|4xl|5xl|full)\b'
    r"|#(?:6f42c1|856404|fd7e14|e83e8c|20c997|6610f2|d63384|0B3D91|EAB308|FAFAF7)"
    r"|\bHeebo\b"
    r"|https?://(?:aws-)?e\.data\.gov\.il"
    r"|/cdn-cgi/"
    r"|\bdata-cfemail="
    r'|class="[^"]*\b__cf_email__\b'
    r"|<h3[^>]*>\s*(?:פרטים|משאבים)\s*</h3>",
    re.IGNORECASE,
)
INLINE_STYLE_RE = re.compile(r'style="[^"]*\b(?:line-height|color)\s*:')
SPACING_RHYTHM_RE = re.compile(
    r'class="[^"]*\bcard\b[^"]*\bp-5\b[^"]*\bmb-(?:[0-57-9]|[0-9]{2,})\b'
)
# Legacy geresh trap (two consecutive gereshes after a Hebrew letter).
GERESH_RE = re.compile(r"[א-ת]''")

# The shell renders the data explorer (search + paginated table with
# server-side full-text search) below the agent's content for every
# datastore-active resource. Agent output must not build its own:
# no GovExplorer calls, no id="explorer…" elements.
EXPLORER_RE = re.compile(r'\bGovExplorer\b|\bid="explorer')

SCRIPT_BLOCK_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script\s*>", re.DOTALL | re.IGNORECASE
)

# Same blocks, but keeping the attributes so the parse gate can tell a
# JS block from a <script type="application/json"> data island (valid
# JSON is not a valid JS *statement* — parsing one as script would
# reject a body that is perfectly fine).
SCRIPT_TAG_RE = re.compile(
    r"<script\b([^>]*)>(.*?)</script\s*>", re.DOTALL | re.IGNORECASE
)
SCRIPT_TYPE_RE = re.compile(r"""type\s*=\s*["']?([^"'\s>]+)""", re.IGNORECASE)

TOP_CARD_BARE_H2_RE = re.compile(
    r'<section\s+class="[^"]*\bcard\b[^"]*\bmb-6\b[^"]*"[^>]*>\s*<h2',
    re.IGNORECASE | re.DOTALL,
)

INSIGHT_HEADING_RE = re.compile(r"<h2[^>]*>\s*(?:תובנות|ממצאים)[^<]*</h2>")
LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.DOTALL | re.IGNORECASE)
UL_OPEN_RE = re.compile(r"<ul\b([^>]*)>")


# ── SECURITY gate ──────────────────────────────────────────────────────
# The agent reads untrusted text (CKAN cells, fetched web pages, search
# results), and a passing body auto-publishes to govil.ai. A prompt
# injection that talks the agent into emitting exfiltration / redirect /
# code-loading JS must die here, not in the browser. Every rule below was
# verified to produce ZERO hits across the 552 published bodies
# (frontend/public/datasets/*/content.html, 2026-10-17) — a new rule that
# trips the corpus must be narrowed, never shipped as-is. These are a
# speed bump against an injected payload, not a sandbox: the real
# browser-side containment is the site's CSP + the frontend runtime.
#
# Deliberately NOT banned (legit corpus usage): `.innerHTML =` /
# `.outerHTML =` (15 pages build table rows with them) and `a.href =`
# (1 page). Escaping dataset strings in tooltips is the frontend
# runtime's job (it wraps ECharts formatters), not a gate here.

# The only inline event handlers the corpus uses — both benign. They are
# blanked out before scanning; any OTHER on*= attribute is rejected.
_SAFE_HANDLER_RE = re.compile(
    r"""\s(?i:onerror)\s*=\s*"\s*this\.(?:style\.(?:visibility\s*=\s*'hidden'"""
    r"""|display\s*=\s*'none')|remove\(\))\s*;?\s*\""""
    r"""|\s(?i:onclick)\s*=\s*"\s*window\.open\('https://(?:www\.)?data\.gov\.il/"""
    r"""[^'"<>\s\\]*'\s*,\s*'_blank'\)\s*;?\s*\""""
)

# (rule, pattern, actionable fix). HTML-level rules are case-insensitive
# (HTML is); JS-API rules are case-sensitive (JS is — `EVAL(` is not eval).
_SEC_HTML_RULES: list[tuple[str, "re.Pattern[str]", str]] = [
    (
        "EMBEDDED-DOCUMENT",
        re.compile(
            r"<(?:iframe|frame|frameset|object|embed|applet|portal|base|meta)\b"
            r"|\ssrcdoc\s*=",
            re.IGNORECASE,
        ),
        "content.html is a body fragment rendered inside govil.ai — no "
        "<iframe>/<frame>/<object>/<embed>/<base>/<meta> or srcdoc=. Remove "
        "the element; if you want to point at a source page, use a normal "
        '<a href="https://…" target="_blank" rel="noopener"> link.',
    ),
    (
        "FORM",
        re.compile(r"<form\b|\sformaction\s*=", re.IGNORECASE),
        "no <form> elements — the page must never submit data anywhere. If "
        "you need a filter control, use a bare <input>/<select>/<button> "
        "wired with addEventListener inside your <script>.",
    ),
    (
        "SCRIPT-URL",
        re.compile(r"(?:java|vb)script\s*:|data\s*:\s*text/html", re.IGNORECASE),
        "no javascript:/vbscript:/data:text/html URLs anywhere (href, src, "
        "strings). Links must be plain https:// URLs; behaviour goes in "
        "your <script> via addEventListener.",
    ),
    (
        "INLINE-HANDLER",
        re.compile(r"<[a-z][^<>]*?[\s\"'/]on[a-z]+\s*=", re.IGNORECASE),
        "no inline on*= event-handler attributes (onclick, onload, "
        "onmouseover, …). Give the element an id and attach the handler "
        "with addEventListener inside your <script>. (The only allowed "
        "forms: onerror=\"this.style.display='none'\" on an <img>, and a "
        "data.gov.il window.open onclick.)",
    ),
    (
        "SCRIPT-MODULE",
        re.compile(r"<script\b[^>]*\btype\s*=\s*[\"']?\s*module", re.IGNORECASE),
        "no <script type=\"module\"> — use a plain <script> (IIFE). Every "
        "library you may use is already a page global (echarts, L, GovMap).",
    ),
    (
        "EXTERNAL-RESOURCE",
        re.compile(
            r"@import\b|url\(\s*[\"']?\s*(?:https?:)?//|\sping\s*=|\ssrcset\s*="
            r"|<image\b|\sxlink:href\s*=",
            re.IGNORECASE,
        ),
        "no external resource loads from CSS or markup (@import, url(http…), "
        "ping=, srcset=, SVG <image>/xlink:href). Icons come from /icons/*.svg "
        "via a plain <img src>.",
    ),
]

_SEC_JS_RULES: list[tuple[str, "re.Pattern[str]", str]] = [
    (
        "NETWORK-API",
        re.compile(
            r"\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bEventSource\b"
            r"|\bnavigator\s*\.|\bimportScripts\b|\bnew\s+(?:Shared)?Worker\b"
            r"|\bnew\s+Image\b|\.src\s*=(?!=)"
            r"|\bsetAttribute\s*\(\s*['\"`]\s*(?:src|href|srcdoc|on\w+)\b"
        ),
        "page scripts must not make network requests or create loading "
        "elements (fetch, XMLHttpRequest, WebSocket, sendBeacon, new Image, "
        ".src =, setAttribute('src'…)). All data must be computed in Python "
        "at build time and inlined as a literal in the <script>.",
    ),
    (
        "STORAGE-API",
        re.compile(
            r"\bdocument\s*\.\s*cookie\b|\b(?:localStorage|sessionStorage|indexedDB)\b"
        ),
        "page scripts must not touch document.cookie, localStorage, "
        "sessionStorage or indexedDB — a dataset page keeps no state. "
        "Remove that code.",
    ),
    (
        "DYNAMIC-CODE",
        re.compile(
            r"\beval\s*\(|\bnew\s+Function\b|\bFunction\s*\(|\bimport\s*\("
            r"|\bset(?:Timeout|Interval)\s*\(\s*['\"`]"
            r"|\bcreateElement\s*\(\s*['\"`]\s*script\b"
            r"|\bwindow\s*\[\s*['\"`]"
            r"|\bglobalThis\b|\.\s*constructor\b"
            r"|\b(?:self|top|parent|document|frames)\s*\["
            r"|\bdocument\s*\.\s*write(?:ln)?\s*\(|\binsertAdjacentHTML\b"
            r"|\bpostMessage\b|\bdocument\s*\.\s*domain\b"
        ),
        "no dynamic code or script injection (eval, new Function, import(), "
        "string setTimeout, createElement('script'), window['…'], "
        "globalThis, .constructor, self/top/parent/document[…], "
        "document.write, insertAdjacentHTML, postMessage). Write the chart "
        "code directly as plain JavaScript; for tables use createElement + "
        "textContent.",
    ),
    (
        "NAVIGATION",
        re.compile(
            r"\b(?:window|top|parent|self|document|globalThis)\s*\.\s*location\b"
            r"|(?<![\w.$])location\s*(?:\.\s*href\s*)?=(?!=)"
            r"|(?<![\w.$])location\s*\.\s*(?:assign|replace)\s*\("
            r"|\bwindow\s*\.\s*open\s*\("
        ),
        "page scripts must never navigate or open windows (location =, "
        "location.href/assign/replace, window.open). Use a normal "
        '<a href="https://…" target="_blank" rel="noopener"> link.',
    ),
]

# Absolute URLs in src= must point at gov.il / OpenStreetMap (images,
# tiles). Relative paths (/icons/…) and inline raster data: images pass.
_SRC_ATTR_RE = re.compile(
    r"<[a-z][^<>]*?\s(?:src|poster|background|data)\s*=\s*([\"']?)\s*([^\"'\s>]*)",
    re.IGNORECASE,
)
_SRC_DATA_IMAGE_RE = re.compile(
    r"data:image/(?:png|jpe?g|gif|webp);base64,", re.IGNORECASE
)
_SRC_ALLOWED_HOSTS = ("gov.il", "openstreetmap.org")
# Browsers drop ASCII tab/newline anywhere in a URL and trim C0 controls +
# space at the ends, so `java\tscript:` is `javascript:` to them.
_URL_STRIP_RE = re.compile(r"[\x00-\x20\x7f]")


def _src_allowed(val: str) -> bool:
    """Parse, don't prefix-match: `https://gov.il:@evil.com/` is userinfo
    `gov.il:` on host evil.com to a browser."""
    from urllib.parse import urlsplit

    if _SRC_DATA_IMAGE_RE.match(val):
        return True
    if "\\" in val:
        return False  # browsers treat \ as / in http(s) authorities
    try:
        u = urlsplit(val)
        port = u.port
    except ValueError:
        return False
    host = (u.hostname or "").lower().rstrip(".")
    if u.scheme.lower() != "https" or "@" in u.netloc or port not in (None, 443):
        return False
    return any(host == h or host.endswith("." + h) for h in _SRC_ALLOWED_HOSTS)
_HAS_SCHEME_RE = re.compile(r"^(?:[a-z][a-z0-9+.\-]*:|//|\\\\)", re.IGNORECASE)

# Identifier names that must never appear as code, matched on esprima's
# *cooked* token values so whitespace/comment/unicode-escape tricks
# (`ev/**/al(`, `eval(`) can't slip past the regexes above.
_BANNED_IDENTIFIERS = {
    "eval", "Function", "fetch", "XMLHttpRequest", "WebSocket", "EventSource",
    "importScripts", "localStorage", "sessionStorage", "indexedDB",
    "sendBeacon", "postMessage", "insertAdjacentHTML", "cookie", "Worker",
    "SharedWorker", "serviceWorker", "execScript", "globalThis", "constructor",
}


def _sec_fail(rule: str, body: str, start: int, end: int, fix: str) -> None:
    near = body[max(0, start - 30):end + 40]
    fail(f"SECURITY/{rule}: forbidden construct near {near!r} — {fix}", code=11)


def check_security(body: str) -> None:
    import html as _html

    scan = _SAFE_HANDLER_RE.sub(" ", body)
    decoded = _html.unescape(scan)
    # `java\tscript:` / `java&#9;script:` — browsers strip the control char.
    compact = _URL_STRIP_RE.sub("", decoded)
    for rule, rx, fix in _SEC_HTML_RULES:
        texts = (scan, decoded, compact) if rule == "SCRIPT-URL" else (scan, decoded)
        for text in texts:  # entity-encoded `java&#115;cript:`
            m = rx.search(text)
            if m:
                _sec_fail(rule, text, m.start(), m.end(), fix)
    for rule, rx, fix in _SEC_JS_RULES:
        m = rx.search(scan)
        if m:
            _sec_fail(rule, scan, m.start(), m.end(), fix)
    for m in _SRC_ATTR_RE.finditer(scan):
        val = _URL_STRIP_RE.sub("", _html.unescape(m.group(2)))
        if not val or not _HAS_SCHEME_RE.match(val):
            continue  # relative path, or a JS-concatenated src="' + x + '"
        if not _src_allowed(val):
            _sec_fail(
                "EXTERNAL-SRC", scan, m.start(), m.end(),
                f"src={val[:80]!r} loads from a host outside the allowlist. "
                "Only relative paths (/icons/…), https://*.gov.il and "
                "https://*.openstreetmap.org may appear in src=. Drop the "
                "element or use a local /icons/*.svg icon.",
            )
    check_js_tokens(body)


def check_js_tokens(body: str) -> None:
    if _esprima is None:
        return
    for n, (attrs, src) in enumerate(SCRIPT_TAG_RE.findall(body), 1):
        if not src.strip():
            continue
        m = SCRIPT_TYPE_RE.search(attrs)
        if m and "json" in m.group(1).lower():
            continue
        try:
            tokens = _esprima.tokenize(src, {"range": True})
        except Exception:
            continue  # unparseable — JS-SYNTAX reports it
        for t in tokens:
            if t.type not in ("Identifier", "Keyword"):
                continue
            r0, r1 = t.range
            # esprima-python reports escaped identifiers inconsistently
            # (raw value, or cooked value with a short range) — any of the
            # three signals means the source spelled a name with escapes.
            if "\\" in t.value or "\\" in src[r0:r1] or src[r0:r1] != t.value:
                fail(
                    f"SECURITY/ESCAPED-IDENTIFIER (script #{n}): an identifier "
                    f"is written with a unicode escape near "
                    f"{src[max(0, r0 - 30):r1 + 30]!r}. Write every "
                    "identifier in plain ASCII.",
                    code=11,
                )
            if t.type == "Identifier" and t.value in _BANNED_IDENTIFIERS:
                fail(
                    f"SECURITY/FORBIDDEN-API (script #{n}): `{t.value}` near "
                    f"{src[max(0, r0 - 40):r1 + 30]!r}. Page scripts may only "
                    "render charts/maps/tables from data inlined at build "
                    "time — no network, storage, messaging or dynamic-code "
                    "APIs. Remove it and inline the computed result instead.",
                    code=11,
                )


def fail(msg: str, code: int = 1) -> "None":
    print(msg)
    sys.exit(code)


def check_html_hygiene(body: str) -> None:
    m = HYGIENE_RE.search(body)
    if m:
        fail(f"HYGIENE: forbidden token near {body[max(0,m.start()-20):m.end()+20]!r}")
    m = INLINE_STYLE_RE.search(body)
    if m:
        fail(
            "INLINE-STYLE: line-height / color belong on Tailwind utilities, "
            f"not inline style — near {body[max(0,m.start()-20):m.end()+40]!r}"
        )
    m = SPACING_RHYTHM_RE.search(body)
    if m:
        fail(
            "SPACING-RHYTHM: top-level card.p-5 blocks must use mb-6 — "
            f"found mb-N != 6 near {body[max(0,m.start()-10):m.end()+10]!r}"
        )
    m = GERESH_RE.search(body)
    if m:
        fail(
            "GERESH-TRAP: legacy two-consecutive-geresh after Hebrew letter — "
            f"near {body[max(0,m.start()-10):m.end()+10]!r}"
        )
    m = EXPLORER_RE.search(body)
    if m:
        fail(
            "SHELL-EXPLORER: the shell renders the data explorer — remove "
            f'GovExplorer / id="explorer…" near {body[max(0,m.start()-20):m.end()+40]!r}'
        )


def check_inline_data_cap(blocks: list[str]) -> None:
    # Any single <script> block over 50 KB means a row dump was inlined
    # into HTML. Use GovMap for point-set maps; row browsing is provided
    # by the shell — compute aggregates in Python instead.
    for i, b in enumerate(blocks, 1):
        if len(b) > 51_200:
            fail(
                f"INLINE-DATA: <script> block #{i} is {len(b)} bytes (>50KB cap). "
                "Use GovMap for point maps; row browsing is provided by the "
                "shell — compute aggregates in Python instead.",
                code=1,
            )


_SMOOTH_TRUE = re.compile(r"\bsmooth\s*:\s*true\b")


def check_no_spline(blocks: list[str]) -> None:
    # Line charts render measured values, not curves: spline smoothing
    # interpolates values that were never measured and rounds off real
    # peaks. The prompt forbids `smooth: true`; enforce it here.
    for i, b in enumerate(blocks, 1):
        m = _SMOOTH_TRUE.search(b)
        if m:
            fail(
                f"SPLINE: <script> block #{i} sets `smooth: true` — line "
                "charts must use straight segments (remove the smooth "
                "option entirely).",
                code=1,
            )


_CATEGORY_YAXIS_RE = re.compile(r"yAxis\s*:\s*\{[^}]*['\"]category['\"]")
_LABEL_POS_LEFT_RE = re.compile(r"position\s*:\s*['\"]left['\"]")


def check_hbar_label_position(blocks: list[str]) -> None:
    # Horizontal bars (category yAxis) grow left→right; a value label at
    # position 'left' sits at the bar's BASE, on top of the y-axis
    # category names (ECharts positions are geometric even on RTL
    # pages). The bar's end is 'right' / 'insideRight'.
    for i, b in enumerate(blocks, 1):
        # Per-chart granularity: a block often holds several setOption
        # calls, and `position: 'left'` is legitimate on other chart
        # types — only flag it inside the same chart config as a
        # category yAxis.
        segments = re.split(r"\.setOption\(", b)[1:] or [b]
        for seg in segments:
            if _CATEGORY_YAXIS_RE.search(seg) and _LABEL_POS_LEFT_RE.search(seg):
                fail(
                    f"HBAR-LABEL: <script> block #{i} has a horizontal bar "
                    "(category yAxis) with a label `position: 'left'` — the "
                    "value lands on the category names. Use `position: "
                    "'right'` (or 'insideRight' for near-max bars).",
                    code=6,
                )


_FMT_HELPER_DEF_RE = re.compile(
    r"function\s+(\w+)\s*\(\s*(\w+)\s*\)\s*\{\s*return\s+(\w+)\s*"
    r"\.to(?:LocaleString|Fixed)"
)
_FMT_ARROW_DEF_RE = re.compile(
    r"(?:var|let|const)\s+(\w+)\s*=\s*\(?\s*(\w+)\s*\)?\s*=>\s*(\w+)\s*"
    r"\.to(?:LocaleString|Fixed)"
)
_FMT_INLINE_RE = re.compile(
    r"label\s*:\s*\{[^{}]*formatter\s*:\s*"
    r"(?:function\s*\(\s*(\w+)\s*\)\s*\{\s*return\s+(\w+)\s*\.to(?:LocaleString|Fixed)"
    r"|\(?\s*(\w+)\s*\)?\s*=>\s*(\w+)\s*\.to(?:LocaleString|Fixed))"
)


def check_label_formatter_params(blocks: list[str]) -> None:
    # ECharts label formatters receive a params OBJECT, not the value.
    # A raw-value helper (`function numFmt(v){ return v.toLocaleString }`)
    # passed as `label.formatter` renders "[object Object]" on every bar.
    # Format `p.value` instead.
    msg = (
        "FMT-PARAMS: <script> block #%d passes a raw-value number "
        "formatter as a label formatter — ECharts calls it with a params "
        "OBJECT, rendering '[object Object]'. Use "
        "`formatter: function(p){ return numFmt(p.value); }`."
    )
    for i, b in enumerate(blocks, 1):
        m = _FMT_INLINE_RE.search(b)
        if m and (
            (m.group(1) and m.group(1) == m.group(2))
            or (m.group(3) and m.group(3) == m.group(4))
        ):
            fail(msg % i, code=7)
        helpers = {
            m.group(1)
            for m in _FMT_HELPER_DEF_RE.finditer(b)
            if m.group(2) == m.group(3)
        } | {
            m.group(1)
            for m in _FMT_ARROW_DEF_RE.finditer(b)
            if m.group(2) == m.group(3)
        }
        for h in helpers:
            if re.search(
                r"label\s*:\s*\{[^{}]*formatter\s*:\s*" + re.escape(h) + r"\s*[,}]", b
            ):
                fail(msg % i, code=7)


# A body must be FINAL HTML, never the Python str.format()/f-string
# template the agent built it with. Two signatures of a leaked template,
# either one conclusive (neither can occur in valid browser JS):
#   • a Python stdlib call left inside a placeholder — `json.dumps(...)`,
#     `ensure_ascii=…`. In the browser `{json.dumps(...)}` parses as an
#     object literal → "Unexpected token '.'", killing the whole <script>.
#   • str.format-escaped object braces — `{{ prop: ...`  paired with `}}`.
_TEMPLATE_LEAK_RE = re.compile(
    r"json\.dumps\s*\("  # Python stdlib call — impossible in valid JS
    r"|ensure_ascii"  # Python json.dumps kwarg
    r"|\{\{\s*[A-Za-z_]\w*\s*:"  # `.format()`-escaped object literal `{{ x:`
)

# A model's own placeholder convention left unsubstituted: `const c1 =
# __C1__;`. Unlike the Python-template leak above this is *valid* JS (an
# undefined-identifier reference), so the syntax/balance checks pass — but
# the browser throws `ReferenceError: __C1__ is not defined`, killing the
# whole <script> so no chart initialises. Match ALL-CAPS dunder-wrapped
# tokens (`__C1__`, `__CHART_DATA__`); real dunder identifiers are lowercase
# (`__proto__`) and constants like `Number.MAX_SAFE_INTEGER` aren't wrapped
# in trailing `__`, so neither trips this. Verified zero hits across the
# whole published corpus.
_PLACEHOLDER_LEAK_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")


def check_unrendered_template(blocks: list[str]) -> None:
    for i, b in enumerate(blocks, 1):
        if _TEMPLATE_LEAK_RE.search(b):
            fail(
                f"TEMPLATE-LEAK: <script> block #{i} is an unrendered Python "
                "template (`{json.dumps(...)}` placeholders / `{{ }}` escaped "
                "braces), not final JavaScript — in the browser this throws a "
                "SyntaxError and no chart initialises. Render the template "
                "(str.format / f-string) and write the RESULT, not the "
                "template source.",
                code=8,
            )
        m = _PLACEHOLDER_LEAK_RE.search(b)
        if m:
            fail(
                f"PLACEHOLDER-LEAK: <script> block #{i} references an "
                f"unsubstituted placeholder token {m.group(0)!r} — a marker "
                "you meant to replace with the actual data array/object but "
                "left as a literal. In the browser it throws `ReferenceError: "
                f"{m.group(0)} is not defined`, killing the whole <script> so "
                "no chart initialises. Inline the real data in place of the "
                "placeholder.",
                code=8,
            )


# Cause classifiers for the JS-SYNTAX diagnostic. Hebrew letter butted
# against a quote is the ג"לג"וליה / מ' shape; the control-char class
# is a raw line terminator (LF/CR/U+2028/U+2029) inside a literal.
_HEB_ADJACENT_QUOTE_RE = re.compile("[\u05d0-\u05ea][\"']")
_RAW_CTRL_IN_JS_RE = re.compile("[\"'][^\"'\\n\\r]*[\\n\\r\u2028\u2029]")


def _js_syntax_hint(src: str, idx: "int | None") -> str:
    # Name the likely cause so RETRY_FEEDBACK gives the next attempt
    # something to act on, not just a parser position. Replaces the
    # per-shape rules this gate absorbed (JS-BALANCE, GERESH-IN-SQ-STR,
    # CTRL-CHAR-IN-JS-STR), which each existed mainly for their message.
    window = src if idx is None else src[max(0, idx - 80):idx + 20]
    if _RAW_CTRL_IN_JS_RE.search(window):
        return (
            " Likely a raw line terminator or control char inside a string "
            "literal — CKAN name/address fields routinely carry them. "
            "JSON.stringify the value instead of hand-quoting it."
        )
    if _HEB_ADJACENT_QUOTE_RE.search(window):
        return (
            " Likely a Hebrew value carrying a quote inside a string closed "
            'by that same quote (e.g. ג"לג"וליה in a "…" literal, or מ\' in '
            "a '…' literal) — it ends the literal early. Emit data values "
            "with JSON.stringify, or switch that literal to the other quote."
        )
    return (
        " If a delimiter is unbalanced, count the brackets in the enclosing "
        "setOption call; if a data value is interpolated, JSON.stringify it."
    )


def check_js_parses(body: str) -> None:
    # Catch-all: every JS <script> block must actually parse, checked with
    # a real ES parser rather than per-shape lexical rules. It subsumes the
    # three hand-rolled walkers this replaced — measured over 2,146 seeded
    # mutants of the published corpus with V8 as oracle: 0 cases they
    # caught that this misses, 61 they missed that this catches, and 4
    # valid-JS false positives of theirs (2 on real published pages, where
    # a single-quoted Hebrew string simply ended in a Hebrew letter) that
    # this does not reproduce.
    #
    # The case that motivated it (live page, 2026-08-06): the place name
    # ג'לג'וליה emitted as ג"לג"וליה inside a double-quoted string. Quote
    # parity stays even and delimiters stay balanced, so every lexical
    # rule passed — but it parses as `"ג"` `לג` `"וליה"`, three adjacent
    # primaries. One <script> held all 7 chart inits, so the page went
    # live chartless with check.py reporting OK.
    if _esprima is None:
        return
    for n, (attrs, src) in enumerate(SCRIPT_TAG_RE.findall(body), 1):
        if not src.strip():
            continue
        m = SCRIPT_TYPE_RE.search(attrs)
        if m and "json" in m.group(1).lower():
            continue
        try:
            _esprima.parseScript(src)
        except Exception as exc:  # esprima.Error, plus tokenizer surprises
            idx = getattr(exc, "index", None)
            idx = idx if isinstance(idx, int) else None
            where = "" if idx is None else f" near {src[max(0, idx - 60):idx + 20]!r}"
            fail(
                f"JS-SYNTAX (script #{n}): {getattr(exc, 'message', None) or exc}"
                f"{where}. The block does not parse, so nothing in it runs — "
                f"every chart it initialises stays blank.{_js_syntax_hint(src, idx)}",
                code=9,
            )


# JS string-literal escapes are consumed by the JS lexer BEFORE JSON.parse
# runs. A Hebrew abbreviation carrying a quote (מל"ל, רב"ט, ג'לג'וליה)
# hand-escaped as `\"` inside a '…' literal therefore reaches JSON.parse
# as a bare, unescaped `"` mid-string and throws `SyntaxError: Expected
# ',' or ']' after array element` — killing the whole <script> so no
# chart initialises. esprima cannot see it: the JS itself is perfectly
# legal. Motivating case (live page b5fecfa2, 2026-09-16):
#   JSON.parse('{"min_cats": ["חוץ", "מל\"ל", "בריאות"], …}')
# — the `\\"` is valid JS, invalid JSON at runtime. Only unescaping the
# literal the way JS would and json.loads-ing the result catches it.
_JSON_PARSE_LIT_RE = re.compile(
    r"JSON\.parse\(\s*"
    r"(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\")"
    r"\s*[,)]"
)
_JS_UNESCAPE_SIMPLE = {
    "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
    "v": "\v", "0": "\0", "\\": "\\", "'": "'", '"': '"',
    "`": "`", "\n": "",  # line continuation
}


def _js_unescape(lit: str) -> str:
    # Simulate how the JS lexer unescapes a string literal body, so the
    # text JSON.parse will actually receive can be validated.
    out: list[str] = []
    i = 0
    while i < len(lit):
        c = lit[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        nxt = lit[i + 1] if i + 1 < len(lit) else ""
        if nxt == "x" and len(lit) >= i + 4:
            out.append(chr(int(lit[i + 2:i + 4], 16)))
            i += 4
        elif nxt == "u" and len(lit) >= i + 6 and lit[i + 2] != "{":
            out.append(chr(int(lit[i + 2:i + 6], 16)))
            i += 6
        elif nxt == "u" and lit[i + 2:i + 3] == "{":
            end = lit.find("}", i + 3)
            if end < 0:
                out.append(nxt)
                i += 2
            else:
                out.append(chr(int(lit[i + 3:end], 16)))
                i = end + 1
        else:
            out.append(_JS_UNESCAPE_SIMPLE.get(nxt, nxt))
            i += 2
    return "".join(out)


def check_json_parse_literals(blocks: list[str]) -> None:
    # Every JSON.parse('<literal>') whose argument is a single string
    # literal must be valid JSON after JS unescaping. Concatenated
    # arguments ('[' + …) and variable/JSON.stringify arguments are not
    # matched here — only the hand-escaped-literal shape, which is the
    # one that ships broken.
    for i, b in enumerate(blocks, 1):
        for m in _JSON_PARSE_LIT_RE.finditer(b):
            raw = m.group(1) if m.group(1) is not None else m.group(2)
            try:
                json.loads(_js_unescape(raw))
            except Exception as exc:
                fail(
                    f"JSON-ESCAPE: <script> block #{i} calls JSON.parse on a "
                    "string literal whose JS-unescaped text is not valid JSON "
                    f"({exc}). JS consumes the literal's backslash escapes "
                    "BEFORE JSON.parse runs — a quote hand-escaped as \\\" "
                    "inside a '…' literal reaches JSON as a bare quote and "
                    "throws, killing the whole <script> so no chart "
                    "initialises. Write Hebrew quotes as the gershayim "
                    "character (״) with no escaping, or double-escape as "
                    "\\\\\" — or better, build the payload with Python "
                    "json.dumps and paste the RESULT directly as an object "
                    "literal (no JSON.parse at all).",
                    code=10,
                )


def check_icon_headers(body: str) -> None:
    # Top-level <section class="card ... mb-6"> must open with the
    # icon-paired flex wrapper, not a bare <h2>. Sub-cards inside grids
    # (no mb-6) are exempt.
    m = TOP_CARD_BARE_H2_RE.search(body)
    if m:
        fail(
            "MISSING-ICON-HEADER: top-level card opens with bare <h2> instead "
            'of <div class="flex items-center gap-2 mb-3 text-brand">'
            '<img src="/icons/<name>.svg" .../><h2.../></div>. Near '
            f"{body[m.start():m.start()+120]!r}",
            code=5,
        )


def check_insights(body: str) -> None:
    # The תובנות / ממצאים section MUST contain <ul> with at least one <li>;
    # the <ul> must use list-disc (Tailwind restores the disc bullet) OR
    # every <li> must contain its own <img> icon — otherwise Tailwind's
    # preflight strips the marker and the items are visually invisible.
    for m in INSIGHT_HEADING_RE.finditer(body):
        sec_start = body.rfind("<section", 0, m.start())
        sec_end = body.find("</section>", m.end())
        if sec_start < 0 or sec_end < 0:
            fail(
                f"INSIGHTS-NOT-IN-SECTION: heading at byte {m.start()} is "
                "not wrapped in <section>...</section>",
                code=6,
            )
        chunk = body[sec_start:sec_end]
        if "<ul" not in chunk or "<li" not in chunk:
            fail(
                f"INSIGHTS-NO-BULLETS: תובנות/ממצאים section at byte "
                f"{sec_start} has no <ul>/<li>. Use "
                '<ul class="list-disc ps-5 m-0 space-y-2 text-sm '
                'marker:text-brand"><li>…</li></ul>.',
                code=7,
            )
        ul = UL_OPEN_RE.search(chunk)
        if ul:
            ul_attrs = ul.group(1)
            if "list-disc" not in ul_attrs and "list-decimal" not in ul_attrs:
                items = LI_RE.findall(chunk)
                bad = [i for i, it in enumerate(items) if "<img" not in it.lower()]
                if bad:
                    fail(
                        "INSIGHTS-NO-MARKER: <ul> in תובנות/ממצאים has neither "
                        "`list-disc` (with optional `marker:text-brand`) nor "
                        "an <img> inside every <li>. Tailwind preflight kills "
                        "default bullets — pick one of the two patterns from "
                        f"BODY SKELETON. Bad <li> indices: {bad[:3]}",
                        code=8,
                    )


def check_percent_consistency(body: str) -> None:
    # Same % appearing >=2 times with conflicting year contexts.
    # Cross-paragraph "different %s for same trend" cases are NOT
    # detected — reconcile those by reading both yourself.
    YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
    pcts = re.findall(r"(\d+(?:[.,]\d+)?)\s*%", body)
    seen: dict[str, int] = {}
    for p in pcts:
        seen[p] = seen.get(p, 0) + 1
    for p, n in sorted(seen.items()):
        if n < 2:
            continue
        year_sets = []
        for m in re.finditer(rf"(.{{0,60}}){re.escape(p)}\s*%(.{{0,60}})", body):
            ctx = m.group(1) + p + "%" + m.group(2)
            years = YEAR_RE.findall(ctx)
            if years:
                year_sets.append(tuple(sorted(set(years))))
        if len(set(year_sets)) >= 2:
            fail(
                f"PERCENT-CONFLICT: {p}% appears {n}x with conflicting year "
                f"contexts {year_sets}",
                code=2,
            )


def main(argv: list[str]) -> int:
    # --recipe: the body was rendered by a deterministic recipe
    # (services/page_builder/refresh.py), not written by a model. Skips only
    # PERCENT-CONFLICT, a guard against an LLM contradicting itself: recipe
    # numbers are recomputed nightly, so two figures can coincide by chance
    # and fail a correct refresh. Every other rule still applies.
    recipe = "--recipe" in argv[1:]
    argv = [a for a in argv if a != "--recipe"]
    if len(argv) != 3:
        print(f"usage: {argv[0]} [--recipe] content.html agent_data.json", file=sys.stderr)
        return 64
    html_path, json_path = argv[1], argv[2]

    with open(html_path, encoding="utf-8") as f:
        body = f.read()
    with open(json_path, encoding="utf-8") as f:
        d = json.load(f)

    # agent_data.json shape
    if not d.get("summary_he"):
        fail("AGENT-DATA: summary_he missing or empty")
    if d.get("dataset_kind") not in VALID_DATASET_KINDS:
        fail(f"AGENT-DATA: dataset_kind invalid: {d.get('dataset_kind')!r}")
    suggested = d.get("suggested_tags") or []
    if not isinstance(suggested, list) or not (1 <= len(suggested) <= 8):
        fail(
            f"AGENT-DATA: suggested_tags must be a list of 1-8 short Hebrew "
            f"topic labels, got {suggested!r}"
        )
    if any(not isinstance(t, str) or not t.strip() for t in suggested):
        fail("AGENT-DATA: suggested_tags entries must be non-empty strings")

    check_html_hygiene(body)
    # Security gate before every quality rule: an injected payload must be
    # reported as such, not masked by a cosmetic diagnostic.
    check_security(body)

    blocks = SCRIPT_BLOCK_RE.findall(body)
    check_inline_data_cap(blocks)
    check_no_spline(blocks)
    # Template leaks first: a leaked placeholder is sometimes valid JS (a
    # bare identifier reference) and sometimes a parse error, and
    # TEMPLATE-LEAK names the fix better than a parser position would.
    check_unrendered_template(blocks)
    # Then the catch-all, which absorbed the per-shape lexical walkers.
    check_js_parses(body)
    check_json_parse_literals(blocks)
    check_hbar_label_position(blocks)
    check_label_formatter_params(blocks)

    check_icon_headers(body)
    check_insights(body)
    if not recipe:
        check_percent_consistency(body)

    print(f"OK {d['dataset_kind']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
