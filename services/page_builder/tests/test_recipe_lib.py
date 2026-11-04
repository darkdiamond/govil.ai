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
from govlib import fmt, frame, geo

FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
DS = "11111111-2222-3333-4444-555555555555"
RID = "aaaaaaaa-0000-0000-0000-000000000001"
COLS = ["שנה", "חודש", "מחוז", "מספר אירועים"]


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
