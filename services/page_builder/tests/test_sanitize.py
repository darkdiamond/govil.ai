"""Tests for the page-body sanitizer (services.page_builder.sanitize).

Catches the recurring LLM hallucination modes that broke
dataset 27b4b40e-…: fabricated SRI hashes on Leaflet, JSON-escaped
script-end tags (`<\\/script>`), and any `<script src=CDN>` /
`<link href=CDN>` references the agent prompt now forbids.

Run directly: `python -m services.page_builder.tests.test_sanitize`
Or via pytest if available.
"""
from __future__ import annotations

import logging

from services.page_builder.sanitize import sanitize_content_html


def _logs(caplog_or_none, *, dataset_id="x", body):
    logger = logging.getLogger("services.page_builder.sanitize")
    records: list[logging.LogRecord] = []

    class H(logging.Handler):
        def emit(self, record):
            records.append(record)

    h = H()
    logger.addHandler(h)
    try:
        return sanitize_content_html(body, dataset_id=dataset_id), records
    finally:
        logger.removeHandler(h)


def test_replaces_escaped_script_end_tag() -> None:
    src = '<script src="/lib/x.js"><\\/script>\n<script>alert(1);<\\/script>'
    out, recs = _logs(None, body=src)
    assert "<\\/script>" not in out
    assert out.count("</script>") == 2
    assert any("</script>" in r.getMessage() for r in recs)


def test_strips_integrity_and_crossorigin() -> None:
    src = (
        '<script src="https://unpkg.com/leaflet/leaflet.js" '
        'integrity="sha256-bad" crossorigin=""></script>\n'
        '<link rel="stylesheet" href="/lib/leaflet.css" '
        'integrity="sha256-bad2" crossorigin>'
    )
    out, recs = _logs(None, body=src)
    assert "integrity=" not in out
    assert "crossorigin" not in out
    msgs = " ".join(r.getMessage() for r in recs)
    assert "integrity" in msgs
    assert "crossorigin" in msgs


def test_drops_cdn_script_and_link_tags() -> None:
    src = (
        '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>\n'
        '<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css">\n'
        '<script>echarts.init(...)</script>'
    )
    out, recs = _logs(None, body=src)
    assert "unpkg.com" not in out
    assert "jsdelivr" not in out
    # Inline script kept.
    assert "echarts.init" in out
    msgs = " ".join(r.getMessage() for r in recs)
    assert "<script src=CDN>" in msgs
    assert "<link href=CDN>" in msgs


def test_decodes_cloudflare_email_span_form() -> None:
    # Form the agent copies from a gov.il page behind Cloudflare: nested
    # <span class="__cf_email__" data-cfemail> inside an email-protection <a>.
    # 016c...  XOR-decodes to matpim@102.gov.il.
    src = (
        '<a href="/cdn-cgi/l/email-protection#80ede1f4f0e9edc0b1b0b2aee7eff6aee9ec" '
        'class="text-brand"><span class="__cf_email__" '
        'data-cfemail="016c607571686c413031332f666e772f686d">'
        "[email&#160;protected]</span></a>"
    )
    out, recs = _logs(None, body=src)
    assert "cdn-cgi" not in out
    assert "__cf_email__" not in out
    assert "data-cfemail" not in out
    assert '<a href="mailto:matpim@102.gov.il">matpim@102.gov.il</a>' in out
    assert any("Cloudflare email-protection" in r.getMessage() for r in recs)


def test_decodes_cloudflare_email_anchor_form() -> None:
    # Second form: __cf_email__ + data-cfemail live on the <a> itself.
    src = (
        '<a href="/cdn-cgi/l/email-protection" class="__cf_email__" '
        'data-cfemail="355d5c5954575447750405071b525a431b5c59">'
        "[email&#160;protected]</a>"
    )
    out, _ = _logs(None, body=src)
    assert "cdn-cgi" not in out
    assert '<a href="mailto:hilabar@102.gov.il">hilabar@102.gov.il</a>' in out


def test_drops_cloudflare_email_decode_script() -> None:
    src = '<script data-cfasync="false" src="/cdn-cgi/scripts/x/email-decode.min.js"></script>\n<p>ok</p>'
    out, recs = _logs(None, body=src)
    assert "cdn-cgi" not in out
    assert "<p>ok</p>" in out
    assert any("/cdn-cgi/" in r.getMessage() for r in recs)


def test_clean_input_pass_through_no_warnings() -> None:
    src = (
        '<h1>Title</h1>\n'
        '<div id="map" class="h-80"></div>\n'
        '<script>const m = L.map("map");</script>\n'
        '<script>echarts.init(document.getElementById("c"));</script>'
    )
    out, recs = _logs(None, body=src)
    assert out == src
    # No sanitizer rule should fire on already-clean input.
    assert not [r for r in recs if "sanitizer:" in r.getMessage()]


def test_does_not_drop_local_lib_scripts() -> None:
    """Non-CDN script srcs (like our own /lib/) must be left alone."""
    src = '<script src="/lib/echarts.min.js"></script>\n<script>x</script>'
    out, _ = _logs(None, body=src)
    assert out == src


def test_real_world_27b4b40e_pattern() -> None:
    """The exact failure mode we hit on dataset 27b4b40e-…: bad SRI +
    escaped script-end tags. After sanitize, both classes are gone."""
    src = (
        '<link rel="stylesheet" '
        'href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" '
        'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" '
        'crossorigin="" />\n'
        '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" '
        'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV/XN/WLs=" '
        'crossorigin=""><\\/script>\n'
        '<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js" '
        'crossorigin=""><\\/script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"><\\/script>\n'
        '<script>const map = L.map("map");<\\/script>'
    )
    out, _ = _logs(None, body=src)
    assert "<\\/script>" not in out
    assert "integrity=" not in out
    assert "crossorigin" not in out
    assert "unpkg.com" not in out
    assert "jsdelivr" not in out
    # The inline init script is preserved (with proper </script> close).
    assert 'L.map("map")' in out
    assert out.count("</script>") == 1


def _raises_unbalanced(src: str) -> str:
    try:
        sanitize_content_html(src, dataset_id="x")
    except ValueError as e:
        return str(e)
    raise AssertionError(f"expected ValueError for unbalanced body: {src!r}")


def test_unclosed_script_raises() -> None:
    """Real failure mode from dataset e4a5e2d7-…: an inline <script> opened
    but never closed swallows the rest of the document. Appending a closer at
    the end never yields a correct page, so the render must fail instead."""
    msg = _raises_unbalanced('<h1>x</h1>\n<script>\n(function(){console.log(1);})();\n')
    assert "<script>" in msg and "1 opening" in msg and "0 closing" in msg


def test_two_unclosed_scripts_raise() -> None:
    msg = _raises_unbalanced("<script>(function(){a();})();\n<script>(function(){b();})();\n")
    assert "2 opening" in msg and "0 closing" in msg


def test_unclosed_style_raises() -> None:
    """An unclosed <style> turns the rest of the page into CSS text: the page
    renders blank and check.py has no rule that notices."""
    msg = _raises_unbalanced(
        '<style>.kpi{color:red;}\n<section class="card p-5 mb-6"><p>x</p>'
        "<script>var a = 1;</script></section>"
    )
    assert "<style>" in msg and "1 opening" in msg and "0 closing" in msg


def test_unclosed_style_minimal_raises() -> None:
    _raises_unbalanced("<style>a{}<section>x</section>")


def test_unclosed_json_island_raises() -> None:
    """An unclosed JSON data island swallows the rest of the body, and
    check.py skips JSON blocks when it parses scripts."""
    msg = _raises_unbalanced(
        '<script type="application/json" id="d">{"a": 1}\n<p>x</p>\n'
        "<script>var a = 1;</script>"
    )
    assert "<script>" in msg and "2 opening" in msg and "1 closing" in msg


def test_extra_closing_script_raises() -> None:
    msg = _raises_unbalanced("<p>hi</p></script>")
    assert "<script>" in msg and "0 opening" in msg and "1 closing" in msg


def test_extra_closing_style_raises() -> None:
    msg = _raises_unbalanced("<style>.a{}</style></style>")
    assert "<style>" in msg and "1 opening" in msg and "2 closing" in msg


def test_many_unclosed_scripts_raise() -> None:
    _raises_unbalanced("<script>a\n<script>b\n<script>c\n<script>d\n<script>e\n<script>f\n")


def test_balanced_input_unchanged() -> None:
    src = '<script>x</script>\n<style>.a{}</style>'
    out, recs = _logs(None, body=src)
    assert out == src
    assert not [r for r in recs if "appended" in r.getMessage()]


def test_balanced_bodies_byte_identical() -> None:
    """Balanced bodies pass through unchanged, logging nothing, including a
    JSON island and a JS string holding an escaped end tag."""
    for src in (
        '<style>.a{}</style>\n<section><p>x</p></section>\n',
        (
            '<script type="application/json" id="d">{"a": [1, 2]}</script>\n'
            '<script>var d = JSON.parse(document.getElementById("d").textContent);</script>'
        ),
        '<script>var s = "<\\/p>"; var t = "a<b";</script><style>.b>.c{}</style>',
        '<div id="c"></div><script>(function(){echarts.init(1);})();</script>',
    ):
        out, recs = _logs(None, body=src)
        assert out == src, src
        assert not recs, [r.getMessage() for r in recs]


def test_commented_out_script_does_not_count() -> None:
    """An <!-- <script> --> comment must not be treated as an opener."""
    src = '<!-- <script>old</script> -->\n<script>x</script>'
    out, recs = _logs(None, body=src)
    assert out == src
    assert not [r for r in recs if "appended" in r.getMessage()]


def test_real_world_e4a5e2d7_pattern() -> None:
    """Exact failure shape from dataset e4a5e2d7-…: the inline ECharts
    IIFE is the only <script>, it never gets closed, and the file ends
    on `})();\\n`. The render must fail so the last-good page stays."""
    src = (
        '<h1>title</h1>\n'
        '<div id="chart-monthly"></div>\n'
        '<script>\n'
        '(function(){\n'
        '  const el = document.getElementById("chart-monthly");\n'
        '  echarts.init(el).setOption({});\n'
        '})();\n'
    )
    _raises_unbalanced(src)


def test_escapes_raw_lf_in_double_quoted_js_string() -> None:
    src = '<script>const x = "before\nafter";</script>'
    out, recs = _logs(None, body=src)
    assert '"before\\nafter"' in out
    assert "\nafter" not in out  # raw LF must be gone
    msgs = " ".join(r.getMessage() for r in recs)
    assert "escaped 1 raw control char" in msgs


def test_escapes_raw_lf_in_single_quoted_js_string() -> None:
    src = "<script>const x = 'a\nb';</script>"
    out, _ = _logs(None, body=src)
    assert "'a\\nb'" in out


def test_escapes_cr_tab_and_u2028_inside_string() -> None:
    src = '<script>const x = "a\rb\tc\u2028d";</script>'
    out, _ = _logs(None, body=src)
    assert '"a\\rb\\tc\\u2028d"' in out


def test_leaves_template_literal_newlines_alone() -> None:
    """Backtick strings legally span lines; do not touch them."""
    src = "<script>const x = `multi\nline`;</script>"
    out, recs = _logs(None, body=src)
    assert out == src
    assert not [r for r in recs if "raw control char" in r.getMessage()]


def test_leaves_application_json_block_alone() -> None:
    src = (
        '<script type="application/ld+json">{"@context":"https://schema.org",'
        '"name":"line1\nline2"}</script>'
    )
    out, recs = _logs(None, body=src)
    assert out == src
    assert not [r for r in recs if "raw control char" in r.getMessage()]


def test_does_not_misread_lf_inside_line_comment() -> None:
    """Line comments have a literal newline at their end; the scanner must
    not enter a string from a `'` that lives inside a comment."""
    src = "<script>// don't break here\nconst x = \"safe\";</script>"
    out, recs = _logs(None, body=src)
    assert out == src
    assert not [r for r in recs if "raw control char" in r.getMessage()]


def test_preserves_existing_backslash_escape_inside_string() -> None:
    """An escaped quote like `\\\"` must not terminate the string and must
    survive the pass byte-for-byte. Then the trailing raw LF still gets
    escaped."""
    src = '<script>const a = "he said \\"hi\\"\nok";</script>'
    out, _ = _logs(None, body=src)
    assert '\\"hi\\"' in out
    assert '"hi\\"\\nok"' in out


def test_real_world_b2370286_pattern() -> None:
    """Exact failure shape from dataset b2370286-…: a JS array literal of
    site rows, one of which has a leading-space + LF inside a `"…"` value.
    Before the fix, V8 aborted the whole <script> with `Invalid or
    unexpected token`. After sanitize there must be no raw newline inside
    any `"…"` string in the script body."""
    src = (
        "<script>\n"
        "const sites = [\n"
        '  [32.05, 34.77, " \nתחנת דלק"],\n'
        '  [32.06, 34.78, "מלון התעשייה\n"],\n'
        "];\n"
        "</script>"
    )
    out, recs = _logs(None, body=src)
    # Walk the inner script and assert no raw LF/CR appears inside any
    # "…"/'…' string literal. (Outside strings, the agent's existing
    # newlines between statements must remain.)
    import re as _re
    inner = _re.search(r"<script>(.*)</script>", out, _re.DOTALL | _re.IGNORECASE).group(1)
    in_str = None
    escape = False
    for ch in inner:
        if escape:
            escape = False
            continue
        if in_str:
            if ch == "\\":
                escape = True
                continue
            if ch == in_str:
                in_str = None
                continue
            assert ch not in ("\n", "\r"), (
                f"raw {ch!r} still inside {in_str} string after sanitize"
            )
            continue
        if ch in ('"', "'"):
            in_str = ch
    assert '" \\nתחנת דלק"' in inner
    assert '"מלון התעשייה\\n"' in inner
    msgs = " ".join(r.getMessage() for r in recs)
    assert "escaped 2 raw control char" in msgs


def test_end_tag_spellings_the_parser_accepts_count_as_closers() -> None:
    """`</script >`, `</SCRIPT foo>` and `</style/>` end the raw-text block in
    a browser, so they must close it here too: no spurious closer appended,
    no stray-closer warning."""
    for src in (
        "<script>x</script >",
        "<script>x</SCRIPT foo>",
        "<script>x</script\t\n bar>",
        "<style>.a{}</style/>",
    ):
        out, recs = _logs(None, body=src)
        assert out == src, src
        assert not [r for r in recs if "appended" in r.getMessage() or "stray" in r.getMessage()], src


def test_comment_closed_by_bang_does_not_count() -> None:
    """A comment also ends at `--!>`; a <script> inside it is not an opener."""
    src = "<!-- <script>old --!>\n<script>x</script>"
    out, recs = _logs(None, body=src)
    assert out == src
    assert not [r for r in recs if "appended" in r.getMessage()]



def test_drops_cdn_script_with_any_end_tag_spelling() -> None:
    """The CDN drop takes the end tag with the opener, whatever its spelling,
    so no stray </script > is left behind."""
    for end in ("</script>", "</script >", "</SCRIPT foo>"):
        src = f'<script src="https://unpkg.com/leaflet.js">{end}<p>x</p>'
        out, recs = _logs(None, body=src)
        assert out == "<p>x</p>", (end, out)
        assert not [r for r in recs if "stray" in r.getMessage()], end


def main() -> None:
    tests = [
        test_replaces_escaped_script_end_tag,
        test_strips_integrity_and_crossorigin,
        test_drops_cdn_script_and_link_tags,
        test_clean_input_pass_through_no_warnings,
        test_does_not_drop_local_lib_scripts,
        test_real_world_27b4b40e_pattern,
        test_unclosed_script_raises,
        test_two_unclosed_scripts_raise,
        test_unclosed_style_raises,
        test_unclosed_style_minimal_raises,
        test_unclosed_json_island_raises,
        test_extra_closing_script_raises,
        test_extra_closing_style_raises,
        test_many_unclosed_scripts_raise,
        test_balanced_input_unchanged,
        test_balanced_bodies_byte_identical,
        test_commented_out_script_does_not_count,
        test_real_world_e4a5e2d7_pattern,
        test_escapes_raw_lf_in_double_quoted_js_string,
        test_escapes_raw_lf_in_single_quoted_js_string,
        test_escapes_cr_tab_and_u2028_inside_string,
        test_leaves_template_literal_newlines_alone,
        test_leaves_application_json_block_alone,
        test_does_not_misread_lf_inside_line_comment,
        test_preserves_existing_backslash_escape_inside_string,
        test_real_world_b2370286_pattern,
        test_decodes_cloudflare_email_span_form,
        test_decodes_cloudflare_email_anchor_form,
        test_drops_cloudflare_email_decode_script,
        test_end_tag_spellings_the_parser_accepts_count_as_closers,
        test_comment_closed_by_bang_does_not_count,
        test_drops_cdn_script_with_any_end_tag_spelling,
    ]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed")


if __name__ == "__main__":
    main()
