"""govlib (recipe_lib/govlib) and the shared gov.j2 macros."""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

from services.page_builder import refresh as rf
from services.page_builder.recipe import Recipe, render_template

sys.path.insert(0, str(rf.RECIPE_LIB_DIR))
from govlib import cbs, fmt, frame, geo

FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
DS = "11111111-2222-3333-4444-555555555555"
RID = "aaaaaaaa-0000-0000-0000-000000000001"
COLS = ["שנה", "חודש", "מחוז", "מספר אירועים"]


# ── cbs ──────────────────────────────────────────────────────────────────


def _cbs_frame(rows, release="2026-11-04"):
    width = max(len(r) for r in rows)
    return pd.DataFrame([{"RELEASE_NO": "1/2026", "RELEASE_DATE": release, "SHEET_NO": "01",
                          "SHEET": "s", "ROW": f"{i:05d}",
                          **{f"C{j + 1:02d}": (r[j] if j < len(r) else "") for j in range(width)}}
                         for i, r in enumerate(rows, 1)])


def test_cbs_clean_and_num():
    assert cbs.clean(" 2026 * ") == "2026"
    assert cbs.clean("Trend(R)") == "Trend"
    assert cbs.clean("תיירים (1) (2)  - סך הכל") == "תיירים - סך הכל"
    assert [cbs.num(v) for v in ("152.4", "..", "-", "x", "1,234", "abc")] == [
        152.4, None, None, None, 1234.0, None]


def test_cbs_grid_takes_the_newest_edition_in_row_order():
    old = _cbs_frame([["old"]], release="2026-10-07")
    new = _cbs_frame([["b"], ["a"]]).iloc[::-1]  # shuffled
    rows = cbs.grid(pd.concat([old, new]), "t1")
    assert rows == [["b"], ["a"]]
    with pytest.raises(ValueError, match="empty grid"):
        cbs.grid(old.iloc[0:0], "t1")


def test_cbs_grid_takes_one_edition_when_two_share_a_date():
    a = _cbs_frame([["a1"], ["a2"]]).assign(RELEASE_NO="99/2026")
    b = _cbs_frame([["b1"], ["b2"]]).assign(RELEASE_NO="345/2026")
    rows = cbs.grid(pd.concat([a, b]).sample(frac=1, random_state=1), "t1")
    assert rows == [["b1"], ["b2"]]  # the higher release number, not interleaved


def test_cbs_latest_release_orders_like_grid():
    rel = pd.DataFrame([
        {"RELEASE_NO": "99/2026", "RELEASE_DATE": "2026-11-04", "TITLE": "a"},
        {"RELEASE_NO": "100/2026", "RELEASE_DATE": "2026-11-04", "TITLE": "b"},
        {"RELEASE_NO": "345/2026", "RELEASE_DATE": "2026-10-01", "TITLE": "old"},
        {"RELEASE_NO": "400/2026", "RELEASE_DATE": "", "TITLE": "undated"},
    ])
    latest = cbs.latest_release(rel.sample(frac=1, random_state=2))
    assert latest["RELEASE_NO"] == "100/2026" and latest["TITLE"] == "b"
    with pytest.raises(ValueError, match="no edition"):
        cbs.latest_release(rel[rel["RELEASE_DATE"] == ""])


def test_cbs_header_lookups_raise_when_missing():
    rows = [["", "Total", "Grand Total"], ["Cruise", "By Air", "Total"]]
    assert cbs.row_with(rows, "Cruise") == 1
    assert cbs.col_after(rows[1], "Total", 1) == 2
    assert cbs.row_with(rows, "Grand", contains=True) == 0
    with pytest.raises(ValueError, match="'Trend' not found"):
        cbs.row_with(rows, "Trend", name="t2")
    with pytest.raises(ValueError):
        cbs.col_after(rows[1], "Cruise", 1)


def test_cbs_periods_find_label_columns_by_content():
    rows = [
        ["2900", "", "2016"],       # a data value that looks like a year
        ["3613", "", "2017"],
        ["957", "I-X", "2026"],
        ["58.6", "I", "2024"],
        ["67.5", "II", ""],
        ["foot", "", ""],
    ]
    got = cbs.periods(rows, 0, len(rows))
    assert got == [(0, 2016, None, None), (1, 2017, None, None), (2, 2026, 1, 10),
                   (3, 2024, 1, None), (4, 2024, 2, None)]


def test_cbs_monthly_runs_count_months_and_check_marks():
    rows = [["2019", "I", "250"], ["", "", "298"], ["", "III", "368"],
            ["2020", "I", "268"], ["", "", ""], ["", "", "302"]]
    assert cbs.monthly_runs(rows, 0, len(rows), 2) == [
        (0, 2019, 1), (1, 2019, 2), (2, 2019, 3), (3, 2020, 1), (5, 2020, 2)]
    rows[2][1] = "VI"
    with pytest.raises(ValueError, match="month mark VI on month 3"):
        cbs.monthly_runs(rows, 0, len(rows), 2)


# ── fmt ──────────────────────────────────────────────────────────────────


def test_int_he_rounds_half_up():
    # The corpus's int(v) copies truncate; round() would give 2 here.
    assert fmt.int_he(2.5) == "3"
    assert fmt.int_he(-2.5) == "-3"
    assert fmt.int_he(1234.4) == "1,234"


def test_pct_names_say_the_scale():
    assert fmt.pct(0.236) == "23.6%"
    assert fmt.pct_of(23.6) == "23.6%"
    assert fmt.pct(0.5, digits=0) == "50%"


def test_signed_pct():
    assert fmt.signed_pct(0.05) == "+5.0%"
    assert fmt.signed_pct(-0.05) == "−5.0%"
    assert fmt.signed_pct(-0.0001) == "0.0%"
    assert fmt.signed_pct("0.05") == "+5.0%"
    with pytest.raises(ValueError):
        fmt.signed_pct(float("nan"))


def test_join_he_vav_before_digits_and_latin():
    assert fmt.join_he(["חיפה"]) == "חיפה"
    assert fmt.join_he(["חיפה", "עכו"]) == "חיפה ועכו"
    assert fmt.join_he(["2022", "2023", "2024"]) == "2022, 2023 ו-2024"
    assert fmt.join_he(["א", "ABC"]) == "א ו-ABC"


def test_dates():
    ts = pd.Timestamp("2024-03-05")
    assert fmt.d_he(ts) == "5 במרץ 2024"
    assert fmt.month_he(ts) == "מרץ 2024"


# ── frame ────────────────────────────────────────────────────────────────


def test_ranked_breaks_ties_by_value():
    s = pd.Series(["ג", "ב", "א", "ב", "ג"])
    assert list(frame.ranked(s).items()) == [("ב", 2), ("ג", 2), ("א", 1)]


def test_top_other():
    counts = pd.Series([5, 4, 3, 2, 1], index=list("abcde"))
    assert frame.top_other(counts, 2) == (["a", "b", "אחר"], [5, 4, 6])
    # one leftover is shown by name, not as "אחר"
    assert frame.top_other(counts, 4) == (list("abcde"), [5, 4, 3, 2, 1])


def test_clean_and_num():
    for empty in (None, float("nan"), pd.NA, pd.NaT):
        assert frame.clean(empty) == "", empty
    assert frame.clean("  תל   אביב ") == "תל אביב"
    got = frame.num(pd.Series(["1,234", "₪ 5", "12%", "−3", "x", "", "inf", "-Infinity"]))
    assert got.iloc[:4].tolist() == [1234.0, 5.0, 12.0, -3.0]
    assert got.iloc[4:].isna().all()


# ── geo ──────────────────────────────────────────────────────────────────


def _decode(flat, origin, scale=geo.SCALE):
    # Mirror of GovMap.ring in frontend/scripts/gov-map.js.
    x, y, out = origin[0], origin[1], []
    for i in range(0, len(flat) - 1, 2):
        x += flat[i]
        y += flat[i + 1]
        out.append((x / scale, y / scale))
    return out


def test_encode_round_trips_within_a_unit():
    ring = [(34.78123, 32.08011), (34.78201, 32.08013), (34.78199, 32.08102), (34.78123, 32.08011)]
    o = geo.origin([p[0] for p in ring], [p[1] for p in ring])
    (flat,) = geo.encode([ring], o)
    for (lon, lat), (dlon, dlat) in zip(ring, _decode(flat, o)):
        assert abs(lon - dlon) <= 1e-5 and abs(lat - dlat) <= 1e-5


def test_simplify_keeps_a_ring_closed_and_at_least_four_points():
    square = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    assert geo.simplify(square, 100) == square           # would collapse below 4
    line = [(0, 0), (5, 1), (10, 0)]
    assert geo.simplify(line, 2, ring=False) == [(0, 0), (10, 0)]
    assert geo.simplify(line, 0.5, ring=False) == line


def test_rendered_len_matches_the_template():
    item = [3, "רחוב <הרצל> & 'בן'", [1, -2, 3]]
    out = render_template("{{ model.x | tojson }}", {"x": item})
    assert geo.rendered_len(item) == len(out)


def test_pack_stays_within_budget_as_rendered():
    items = [[i, "שכונה " * (i % 7), list(range(i % 50))] for i in range(400)]
    chunks = geo.pack(items, budget=2_000)
    assert [x for c in chunks for x in c] == items
    for c in chunks:
        assert len(render_template("{{ model.c | tojson }}", {"c": c})) <= 2_000
    with pytest.raises(ValueError):
        geo.pack([list(range(1000))], budget=500)


def test_haversine():
    # Tel Aviv – Jerusalem, ~54 km
    assert 53 < geo.haversine_km(32.0853, 34.7818, 31.7683, 35.2137) < 55


# ── gov.j2 macros ────────────────────────────────────────────────────────


def test_macros_render_escaped():
    out = render_template(
        '{% import "gov.j2" as gov %}{{ gov.lede(model.t) }}{{ gov.kpi(model.k, "שורות") }}'
        '{{ gov.table("c", ["a", "b"], [["<x>", "1"]], ltr=(1,)) }}',
        {"t": "<b>", "k": {"tone": "brand", "display": "1,234"}},
    )
    assert "&lt;b&gt;" in out and "&lt;x&gt;" in out
    assert '<td dir="ltr">1</td>' in out
    assert 'text-brand mb-1" dir="ltr">1,234<' in out


def test_templates_load_only_the_macros_dir():
    with pytest.raises(Exception, match="TemplateNotFound"):
        render_template('{% include "../recipe.py" %}', {})


# ── refresh: staged into the sandbox, hashed only where used ─────────────


def _using_govlib(tmp_path):
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    c = recipes / DS / "compute.py"
    c.write_text(
        "from govlib import fmt\n" + c.read_text() + (
            "\n\n_real = compute\n\n\n"
            "def compute(frames):\n"
            "    model = _real(frames)\n"
            "    model['probe'] = fmt.int_he(2.5)\n"
            "    return model\n"
        ),
        encoding="utf-8",
    )
    return Recipe.load(recipes / DS)


def test_compute_can_import_govlib(tmp_path):
    f = tmp_path / "in.csv"
    with open(f, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        w.writerows([[2025, m, "צפון", 10] for m in range(1, 13)])
    recipe = _using_govlib(tmp_path)
    part = rf.FetchedInput(file=f, resource_id=RID, resource_name="events", rows=12)
    model = rf.run_compute(recipe, {recipe.manifest.inputs[0].name: [part]}, tmp_path / "work")
    assert model["probe"] == "3"


def test_lib_hash_folds_only_into_recipes_that_use_it(tmp_path, monkeypatch):
    plain = Recipe.load(FIXTURES / DS)
    using = _using_govlib(tmp_path)
    before = (rf.recipe_identity(plain), rf.recipe_identity(using))
    monkeypatch.setattr(rf, "_recipe_lib_hash", lambda: "changed")
    assert rf.recipe_identity(plain) == before[0]
    assert rf.recipe_identity(using) != before[1]


@pytest.mark.parametrize("compute_head, template_head", [
    ("import math, govlib\n", ""),
    ("from govlib.fmt import int_he\n", ""),
    ("", '{% import "gov.j2" as gov %}\n'),
    ("", "{%+ from 'gov.j2' import kpi %}\n"),
])
def test_any_import_form_counts_as_use(tmp_path, compute_head, template_head):
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    for name, head in (("compute.py", compute_head), ("template.html.j2", template_head)):
        f = recipes / DS / name
        f.write_text(head + f.read_text(encoding="utf-8"), encoding="utf-8")
    assert rf._uses_recipe_lib(Recipe.load(recipes / DS))
    assert not rf._uses_recipe_lib(Recipe.load(FIXTURES / DS))


def test_macros_change_moves_the_failure_lock(monkeypatch):
    # gov.j2 isn't .py, so only the explicit fold puts it in the lock hash.
    rf._builder_code_hash.cache_clear()
    before = rf._builder_code_hash()
    monkeypatch.setattr(rf, "_recipe_lib_hash", lambda: "changed")
    rf._builder_code_hash.cache_clear()
    try:
        assert rf._builder_code_hash() != before
    finally:
        rf._builder_code_hash.cache_clear()
