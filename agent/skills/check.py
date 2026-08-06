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
    r"|https?://e\.data\.gov\.il"
    r"|/cdn-cgi/"
    r"|\bdata-cfemail="
    r'|class="[^"]*\b__cf_email__\b'
    r"|<h3[^>]*>\s*(?:פרטים|משאבים)\s*</h3>"
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
    if len(argv) != 3:
        print(f"usage: {argv[0]} content.html agent_data.json", file=sys.stderr)
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

    blocks = SCRIPT_BLOCK_RE.findall(body)
    check_inline_data_cap(blocks)
    check_no_spline(blocks)
    # Template leaks first: a leaked placeholder is sometimes valid JS (a
    # bare identifier reference) and sometimes a parse error, and
    # TEMPLATE-LEAK names the fix better than a parser position would.
    check_unrendered_template(blocks)
    # Then the catch-all, which absorbed the per-shape lexical walkers.
    check_js_parses(body)
    check_hbar_label_position(blocks)
    check_label_formatter_params(blocks)

    check_icon_headers(body)
    check_insights(body)
    check_percent_consistency(body)

    print(f"OK {d['dataset_kind']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
