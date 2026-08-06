"""JS-SYNTAX rule in agent/skills/check.py.

A catch-all parse gate over agent-emitted <script> blocks: a real ES
parser, so *any* SyntaxError class is caught before the body persists.

The class that motivated it shipped a broken live page on 2026-08-06:
the Hebrew place name ג'לג'וליה was emitted with ASCII double quotes
(ג"לג"וליה) inside a double-quoted JS string. Quote parity stayed even,
so nothing lexical tripped — but the parse is `"ג"` `לג` `"וליה"`, three
adjacent primaries, i.e. `Unexpected identifier`. The single <script>
block held all 7 chart inits, so the whole page rendered chartless while
check.py reported OK.

This gate replaced three hand-rolled walkers (JS-BALANCE,
GERESH-IN-SQ-STR, CTRL-CHAR-IN-JS-STR). Their cases live on below, under
"absorbed from test_check_balance.py" and the string-hygiene tests, so
the shapes they covered stay pinned. Subsumption was measured over 2,146
seeded mutants of the published corpus with V8 as oracle: 0 misses
relative to the old rules, 61 additional catches, and none of their 4
false positives on valid JS.
"""
import importlib.util
from pathlib import Path

import pytest

_CHECK_PATH = (
    Path(__file__).resolve().parents[3] / "agent" / "skills" / "check.py"
)
_spec = importlib.util.spec_from_file_location("agent_check", _CHECK_PATH)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def _body(script: str, attrs: str = "") -> str:
    return f"<section><script{attrs}>{script}</script></section>"


def _run(script: str, attrs: str = "") -> None:
    check.check_js_parses(_body(script, attrs))


def test_esprima_is_installed():
    # The gate degrades to a no-op without the parser; if the dependency
    # goes missing from requirements.txt this fails loudly rather than
    # letting the gate silently disappear in prod.
    assert check._esprima is not None


# --- the regression -------------------------------------------------

def test_gershayim_in_double_quoted_string_fails():
    with pytest.raises(SystemExit):
        _run(
            'var names = ["טייבה", "ג"לג"וליה", "אורנית"];'
        )


def test_geresh_spelling_of_same_name_passes():
    # What the source data actually holds, and what the fix restored.
    _run('var names = ["טייבה", "ג\'לג\'וליה", "אורנית"];')


# --- classes the hand-rolled rules already cover, re-asserted here ---

def test_geresh_in_single_quoted_string_fails():
    with pytest.raises(SystemExit):
        _run("var a = 'ג'לג';")


def test_raw_line_terminator_in_string_fails():
    with pytest.raises(SystemExit):
        _run('var a = "פתח\nתקוה";')


def test_unbalanced_delimiter_fails():
    with pytest.raises(SystemExit):
        _run("chart.setOption({ series: [] };")


# --- must not fire on valid bodies ----------------------------------

def test_typical_chart_block_passes():
    _run(
        """
        const numFmt = function(v) { return Number(v).toLocaleString('he-IL'); };
        (function() {
          const el = document.getElementById('chart-trend');
          const c = echarts.init(el);
          c.setOption(window.GovEcharts.option({
            tooltip: { trigger: 'axis' },
            xAxis: { type: 'category', data: [2018, 2019, 2022] },
            series: [{ name: "הכנסות", type: 'bar', data: [67.79, 71.25, 81.44] }]
          }));
          window.addEventListener('resize', function() { c.resize(); });
        })();
        """
    )


def test_modern_syntax_passes():
    # Shapes that appear across published bodies — a parser too old for
    # these would reject good pages and block the daily publish.
    _run(
        "const f = (a, b = 2) => ({ ...a, b });"
        "let [x, ...rest] = [1, 2, 3];"
        "const s = `סה\"כ ${x} רשויות`;"
        "for (const [k, v] of Object.entries({a: 1})) { void k; void v; }"
    )


def test_regex_literal_and_division_pass():
    _run("var s = name.replace(/[{]/g, ''); var pct = (done / total) * 100;")


def test_hebrew_apostrophes_in_double_quoted_strings_pass():
    _run('var a = ["שבלי-אום אל ג\'נם", "בוסתאן אל-מרג\'", "סאג\'ור"];')


# --- block selection ------------------------------------------------

def test_json_data_block_is_not_parsed_as_js():
    # Real bodies stage chart data in <script type="application/json">.
    # Valid JSON is not a valid JS *statement* — parsing it as script
    # would reject two currently-published pages.
    _run('{"regionNames": ["טבריה"], "counts": [9]}',
         attrs=' id="chart-data" type="application/json"')


def test_empty_block_is_skipped():
    _run("   \n  ")


def test_gate_is_noop_without_parser(monkeypatch):
    monkeypatch.setattr(check, "_esprima", None)
    _run('var names = ["ג"לג"וליה"];')


# --- absorbed from test_check_balance.py (JS-BALANCE) ----------------

def test_extra_closing_brace_fails():
    # The bddf37d6 incident: one stray `}` after the tooltip object.
    with pytest.raises(SystemExit):
        _run(
            """
            c.setOption(window.GovEcharts.option({
              tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' } },
              legend: { bottom: 0 }
            }));
            """
        )


def test_mismatched_delimiter_kind_fails():
    with pytest.raises(SystemExit):
        _run("var a = foo(bar[1)];")


def test_braces_in_strings_ignored():
    _run("var f = 'a } b } c'; var g = \"{{{\"; var h = `x } ${'{'} y`;")


def test_braces_in_comments_ignored():
    _run("// } } }\n/* { { */\nvar a = (1 + 2);")


# --- the diagnostic names a likely cause (RETRY_FEEDBACK acts on it) --

def _msg(script: str) -> str:
    recorded = {}
    original = check.fail

    def capture(msg, code=1):
        recorded["msg"] = msg
        raise SystemExit(code)

    check.fail = capture
    try:
        with pytest.raises(SystemExit):
            _run(script)
    finally:
        check.fail = original
    return recorded["msg"]


def test_hint_points_at_quote_in_same_quoted_string():
    m = _msg('var names = ["טייבה", "ג"לג"וליה"];')
    assert "JS-SYNTAX" in m
    assert "JSON.stringify" in m
    assert "same quote" in m


def test_hint_points_at_control_char():
    m = _msg('var a = "פתח\nתקוה";')
    assert "control char" in m or "line terminator" in m
    assert "JSON.stringify" in m


def test_hint_falls_back_to_delimiter_advice():
    m = _msg("chart.setOption({ series: [] };")
    assert "delimiter" in m
