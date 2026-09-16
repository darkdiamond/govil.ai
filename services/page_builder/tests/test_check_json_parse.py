"""JSON-ESCAPE rule: a `JSON.parse('<string literal>')` whose argument is
only valid-looking JS — but invalid JSON after JS unescaping — must fail
validation, because esprima cannot see it and the browser kills the whole
<script> so no chart initialises.

Motivating case (live page b5fecfa2, 2026-09-16): the Hebrew abbreviation
מל"ל hand-escaped as `\"` inside a '…' literal. JS consumes the escape
before JSON.parse runs, so JSON receives a bare, unescaped `"` mid-string
and throws `SyntaxError: Expected ',' or ']' after array element`.
"""
import importlib.util
from pathlib import Path

import pytest

_CHECK_PATH = (
    Path(__file__).resolve().parents[3] / "agent" / "skills" / "check.py"
)
_spec = importlib.util.spec_from_file_location("agent_check_json_esc", _CHECK_PATH)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


# ── exact shape shipped by b5fecfa2 (single-quoted literal, `\"`) ──
def test_b5fecfa2_shape_fails():
    with pytest.raises(SystemExit):
        check.check_json_parse_literals(
            ["""const D = JSON.parse('{"cont_cats": ["אפריקה", "אירופה"], \
"min_cats": ["חוץ", "מל\\"ל", "בריאות"], "min_vals": [206, 205, 192]}');"""]
        )


# ── same trap in a double-quoted JS literal ──
def test_double_quoted_literal_fails():
    with pytest.raises(SystemExit):
        check.check_json_parse_literals(
            ['''const D = JSON.parse("{\\"name\\": \\"רב\\"ט\\"}");''']
        )


# ── the fixes the diagnostic recommends must pass ──
def test_gershayim_passes():
    check.check_json_parse_literals(
        ["const D = JSON.parse('{\"min_cats\": [\"חוץ\", \"מל״ל\", \"בריאות\"]}');"]
    )


def test_doubly_escaped_quote_passes():
    # `\\"` in a '…' literal reaches JSON as `\"` — valid JSON.
    check.check_json_parse_literals(
        ["const D = JSON.parse('{\"min_cats\": [\"חוץ\", \"מל\\\\\"ל\"]}');"]
    )


def test_plain_valid_json_passes():
    check.check_json_parse_literals(
        ["const D = JSON.parse('{\"a\": [1, 2, 3], \"b\": \"שלום\"}');"]
    )


# ── non-literal arguments must not be matched (no false positives) ──
def test_concatenated_argument_ignored():
    # The a5aa4b26 page builds the literal from concatenated strings.
    check.check_json_parse_literals(["const D = JSON.parse('[' + '\\n' + '{}');"])


def test_variable_argument_ignored():
    check.check_json_parse_literals(["const D = JSON.parse(rawText);"])


def test_json_stringify_argument_ignored():
    check.check_json_parse_literals(["const D = JSON.parse(JSON.stringify(obj));"])


# ── unescaping fidelity ──
def test_js_unescape_basics():
    assert check._js_unescape("a\\nb") == "a\nb"
    assert check._js_unescape("a\\\\b") == "a\\b"
    assert check._js_unescape("\\u05d0") == "א"
    assert check._js_unescape("a\\") == "a"  # trailing dangling backslash
