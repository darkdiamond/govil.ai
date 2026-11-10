"""Fact ledger rendering and the deterministic gate."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from services.news import gates
from services.news.ledger import Ledger, format_value, render, stray_numbers
from services.news.series import extract_series

FIX = Path(__file__).parent / "fixtures" / "models"
MINUS = "−"


@pytest.mark.parametrize("v, spec, want", [
    (1234.0, None, "1,234"),
    (12.345, None, "12.3"),
    (1.2345, None, "1.23"),
    (23.6, "pct", "23.6%"),
    (-34.1, "abs_pct", "34.1%"),
    (1500.4, "abs", "1,500.4"),
])
def test_format_value(v, spec, want):
    assert format_value(v, spec) == want


def test_signed_formats_are_isolated_with_a_real_minus():
    s = format_value(-5.0, "spct")
    assert MINUS in s and "5.0%" in s and "-" not in s
    assert "+" in format_value(0.25, "pp")


@pytest.mark.parametrize("text, bad", [
    ("בשנת 2025 נרשמה ירידה", []),
    ("ב-3 במרץ 2026 פורסם הנתון", []),
    ("עלייה של {f1:pct} לעומת 2024", []),
    ("ירידה של 34% בהיקף", ["34%"]),
    ("נרשמו 1,200 עסקאות", ["1,200"]),
    ("הריבית ירדה ל-4.25", ["ל-4.25"]),
    ("[[לפי 12 מקורות|s1]] נמסר", ["12"]),
    ("מאז 2019 ובשנים 2019–2025 ובמרץ 2024 (2023) ובשנת 2020", []),
    ("נמכרו 1980 דירות", ["1980"]),
    ("2025 הייתה שנה חלשה", ["2025"]),
    # 2026-11-09 live run: a year closing a sentence was rejected as a typed number.
    ("הנתונים יתפרסמו בדצמבר 2026.", []),
    ("מאז 2019, ועד ינואר 2026, הנתון ירד.", []),
    ("עלה ל-2026.5 נקודות", ["ל-2026.5"]),
    ("הנתונים פורסמו ב-14.9.2026 ובתאריך 9/11/2026.", []),
    ("בשנת התקציב 2025/26 ובשנת הלימודים 2024-25", []),
    ("2019-2025", ["2019-"]),                    # a range still needs a lead for its first year
    ("עלייה של 2025%", ["2025%"]),
    ("נרשמו 2025,5 נקודות", ["2025,5"]),
    # "כ-" means "about": a count, never a year.
    ("נמכרו כ-1980 דירות", ["כ-1980"]),
    ("כ-2040 עסקאות", ["כ-2040"]),
    ("כ-1950 נפגעים", ["כ-1950"]),
    ("ב-2025 ומ-2019 ול-2026 והחל מ-2020", []),
    ("בין 2019 ל-2025, ינואר-2025 ומרץ–2026", []),
    ("ב–2024 וב־2025", []),
    ("כ־1980 וכ–1990 דירות", ["כ־1980", "וכ–1990"]),
])
def test_stray_numbers(text, bad):
    assert stray_numbers(text) == bad


def test_render_runs_and_problems():
    led = Ledger()
    f = led.add(12.5, label="x", provenance="p")
    s = led.add_source("https://www.boi.org.il/x", "הודעה", "טקסט")
    runs, probs = render(f"ירידה של {{{f.id}:abs_pct}} לפי [[ההודעה|{s.id}]] ו[[העמוד|ds:abc]]",
                         led, lambda d: "/datasets/abc/" if d == "abc" else None)
    assert probs == []
    assert [r["t"] for r in runs] == ["text", "link", "text", "link"]
    assert runs[0]["v"] == "ירידה של 12.5% לפי " and runs[1]["href"] == "https://www.boi.org.il/x"
    assert runs[3] == {"t": "link", "v": "העמוד", "href": "/datasets/abc/", "kind": "dataset", "id": "abc"}
    _, probs = render("{f99} [[x|s9]] [[y|ds:zzz]]", led, lambda d: None)
    assert len(probs) == 3


def test_calc_traces_inputs():
    led = Ledger()
    a = led.add(110, label="a", provenance="a")
    b = led.add(100, label="b", provenance="b")
    c = led.calc("pct_change", a.id, b.id)
    assert c.value == pytest.approx(10.0) and c.unit == "pct" and c.provenance.startswith("calc:")
    assert led.add(110, label="again", provenance="a").id == a.id  # same provenance, same fact


# ── the gate ─────────────────────────────────────────────────────────────

FILLER = ("הנתון החודשי מראה שינוי בהיקף הפעילות לעומת התקופה המקבילה אשתקד ולעומת החודש הקודם, "
          "והוא מצטרף למגמה שנמשכת כבר כמה חודשים בשוק המשכנתאות בישראל. ")
QUOTE = "הוועדה המוניטרית החליטה להותיר את הריבית ללא שינוי"


def _setup():
    model = json.loads((FIX / "boi-mortgage-rates.json").read_text(encoding="utf-8"))
    series = {"boi-mortgage-rates": extract_series(model, "boi-mortgage-rates", date(2026, 11, 9))}
    led = Ledger()
    s = next(x for x in series["boi-mortgage-rates"] if x.path == "volume.y")
    _, v = s.complete[-1]
    f1 = led.add(v, label="volume", provenance="series:volume", dataset_id="boi-mortgage-rates")
    led.add_source("https://www.boi.org.il/r", "הודעת הריבית", f"פתיח. {QUOTE} בשלב זה. סוף.")
    catalog = {"boi-mortgage-rates": {"title": "משכנתאות", "page_slug": "boi-mortgage-rates",
                                      "tags": ["משכנתאות"]}}
    return series, led, catalog, f1


def _draft(f1, **over):
    d = {
        "headline": f"היקף המשכנתאות בספטמבר עמד על {{{f1.id}:num2}} מיליארד שקל",
        "dek": "נתוני בנק ישראל מראים שינוי לעומת החודש הקודם ולעומת השנה שעברה.",
        "slug_en": "mortgage-volume-september-2026",
        "dataset_ids": ["boi-mortgage-rates"],
        "tags": ["משכנתאות", "לא-בתגיות"],
        "image_brief": "a house and a key", "image_alt_he": "איור של בית",
        "blocks": [
            {"type": "p", "text": f"לפי [[נתוני בנק ישראל|ds:boi-mortgage-rates]] נלקחו בספטמבר "
                                  f"משכנתאות בהיקף של {{{f1.id}:num2}} מיליארד שקל. " + FILLER * 3},
            {"type": "chart", "chart": "c1"},
            {"type": "h2", "text": "ההקשר"},
            {"type": "p", "text": "[[לפי הודעת הריבית|s1]] הוועדה לא שינתה את הריבית. " + FILLER * 10},
            {"type": "stat", "fact": f1.id, "fmt": "num2", "label": "מיליארד שקל בספטמבר"},
        ],
        "charts": [{"id": "c1", "type": "line", "title": "היקף משכנתאות חודשי", "unit": "מיליארדי ש\"ח",
                    "series": [{"dataset_id": "boi-mortgage-rates", "series_path": "volume.y",
                                "name": "היקף", "from": "2020-01"}]}],
        "sources": [{"id": "s1", "quote": QUOTE}],
    }
    d.update(over)
    return d


def test_good_draft_passes_and_renders():
    series, led, cat, f1 = _setup()
    core, problems = gates.check(_draft(f1), ledger=led, series_by_ds=series, catalog=cat,
                                 vocab={"משכנתאות"})
    assert problems == []
    assert core["slug"] == "mortgage-volume-september-2026" and core["tags"] == ["משכנתאות"]
    assert core["charts"][0]["option"]["xAxis"]["data"][0] == "2020-01"
    assert core["sources"][0]["url"] == "https://www.boi.org.il/r"
    assert "{" not in core["headline"] and core["blocks"][-1]["type"] == "stat"
    assert "for review" in gates.as_markdown(core)


@pytest.mark.parametrize("mutate, needle", [
    (lambda d, f: d["blocks"][0].__setitem__("text", d["blocks"][0]["text"] + " נרשמו 1,200 עסקאות."),
     "typed numbers"),
    (lambda d, f: d["blocks"][3].__setitem__("text", "חשוב לציין " + d["blocks"][3]["text"]),
     "banned phrases"),
    (lambda d, f: d.__setitem__("sources", [{"id": "s1", "quote": "משפט שלא מופיע בעמוד בכלל ואינו שם"}]),
     "quote not found"),
    (lambda d, f: d.__setitem__("sources", []), "verbatim quote"),
    (lambda d, f: d["blocks"][3].__setitem__("text", d["blocks"][3]["text"].replace("|s1]]", "|s7]]")),
     "unknown source"),
    (lambda d, f: d["blocks"][0].__setitem__("text", d["blocks"][0]["text"].replace("|ds:boi-mortgage-rates", "|ds:nope")),
     "never linked"),
    (lambda d, f: d["charts"][0]["series"][0].__setitem__("series_path", "made.up"), "no series"),
    (lambda d, f: (d.__setitem__("charts", []), d["blocks"].pop(1)), "at least one chart"),
    (lambda d, f: d["blocks"].insert(2, {"type": "h2", "text": "האם המגמה תימשך?"}), "question subhead"),
    (lambda d, f: d.__setitem__("headline", "משכנתאות: הנתון החדש"), "colon"),
    (lambda d, f: d.__setitem__("blocks", d["blocks"][:2]), "body length"),
    (lambda d, f: d.__setitem__("slug_en", "x"), "slug"),
    # The stat block's format is model output: only a known ledger format.
    (lambda d, f: d["blocks"][4].__setitem__("fmt", "int} עלייה של 99% {"), "block 4: format"),
    (lambda d, f: d["blocks"][4].__setitem__("fmt", "5"), "block 4: format"),
    # Every printed free-text field gets the body's number and punctuation checks.
    (lambda d, f: d["charts"][0].__setitem__("title", "המחירים זינקו ב-47% בשנה"), "chart c1 title: typed numbers"),
    (lambda d, f: d["charts"][0].__setitem__("title", "המחירים זינקו — שיא"), "punctuation"),
    (lambda d, f: d["charts"][0].__setitem__("unit", "אלפי 12 ש\"ח"), "chart c1 unit: typed numbers"),
    (lambda d, f: d["charts"][0]["series"][0].__setitem__("name", "סדרה 55%"), "chart c1 series 0 name: typed numbers"),
    (lambda d, f: d["charts"][0]["series"][0].__setitem__("name", "היקף — שיא"), "punctuation"),
    (lambda d, f: d["charts"][0]["series"][0].__setitem__("name", "שלושה מיליארד שקל"), "spelled in words"),
    (lambda d, f: d["charts"].append({"id": "c2", "type": "bar", "title": "השוואה", "unit": "%",
                                      "bars": [{"label": "ירושלים 73% מהמקרים", "fact": f.id}]}),
     "chart c2 bar 0 label: typed numbers"),
    (lambda d, f: d["charts"].append({"id": "c2", "type": "bar", "title": "השוואה", "unit": "%",
                                      "bars": [{"label": "ירושלים!", "fact": f.id}]}),
     "no exclamation marks"),
    (lambda d, f: d["charts"][0].__setitem__("title", "היקף {" + f.id + "}"), "no fact tokens or links"),
    (lambda d, f: d.__setitem__("image_alt_he", "גרף שמראה עלייה של 300%"), "image_alt_he: typed numbers"),
    (lambda d, f: d.__setitem__("image_alt_he", "גרף שמראה עלייה דרמטית!"), "no exclamation marks"),
    (lambda d, f: d.__setitem__("image_alt_he", "איור מרתק של בית"), "banned phrases"),
    (lambda d, f: d["blocks"][4].__setitem__("label", "מיליארד שקל — שיא"), "punctuation"),
    # A bar with no label prints its fact's label, which the model can write too.
    (lambda d, f: d["charts"].append({"id": "c2", "type": "bar", "title": "השוואה", "unit": "%", "bars": [
        {"fact": d["_led"].calc("scale", f.id, label="עלייה של 300% — דרמטית!", factor=1e-6).id}]}),
     "give the bar an explicit label"),
    # Chart labels may be a bare period and units a per-N denominator; nothing wider.
    (lambda d, f: d["charts"].append({"id": "c2", "type": "bar", "title": "השוואה", "unit": "%",
                                      "bars": [{"label": "2025 שיא", "fact": f.id}]}),
     "chart c2 bar 0 label: years without date context"),
    (lambda d, f: d["charts"].append({"id": "c2", "type": "bar", "title": "השוואה", "unit": "%",
                                      "bars": [{"label": "2024-11-03 עלייה של 300%", "fact": f.id}]}),
     "chart c2 bar 0 label: typed numbers"),
    (lambda d, f: d["charts"][0]["series"][0].__setitem__("name", "2024-11-03 300%"),
     "chart c1 series 0 name: typed numbers"),
    (lambda d, f: d["charts"][0]["series"][0].__setitem__("name", "2024-11-03T99"),
     "chart c1 series 0 name: typed numbers"),
    (lambda d, f: d["charts"][0].__setitem__("unit", "47%"), "chart c1 unit: typed numbers"),
    (lambda d, f: d["charts"][0].__setitem__("unit", "לכל 1,000 תושבים 55%"), "chart c1 unit: typed numbers"),
    (lambda d, f: d["charts"][0].__setitem__("unit", "לכל 1,500 תושבים"), "chart c1 unit: typed numbers"),
    (lambda d, f: d["charts"][0].__setitem__("unit", "ל-100 מיליון ש\"ח"), "chart c1 unit: typed numbers"),
    (lambda d, f: d["charts"][0].__setitem__("title", "2025"), "chart c1 title: years without date context"),
    (lambda d, f: d["blocks"][4].__setitem__("label", "2025"), "block 4 label: years without date context"),
    (lambda d, f: d.__setitem__("image_alt_he", "לכל 1,000 תושבים"), "image_alt_he: typed numbers"),
    # The minimum quote length is measured after normalization.
    (lambda d, f: d.__setitem__("sources", [{"id": "s1", "quote": '"' * 19 + "a"}]), "verbatim quote"),
    (lambda d, f: d.__setitem__("sources", [{"id": "s1", "quote": " " * 25}]), "verbatim quote"),
])
def test_gate_catches(mutate, needle):
    series, led, cat, f1 = _setup()
    d = _draft(f1, _led=led)
    mutate(d, f1)
    _, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    assert any(needle in p for p in problems), problems


@pytest.mark.parametrize("labels, unit, name", [
    (["2025", "2024/25", "2024-25", "2024-Q3", "Q3 2024", "2024 Q3", "2024-11", "מאי 2024", "2024-11-03",
      "3.11.2024"], "%", "2025"),
    (["תל אביב"], "לכל 1,000 תושבים", "היקף"),
    (["תל אביב"], "ש\"ח ל-100 ק\"ג", "היקף"),
    (["תל אביב"], "ל-100,000 נפש", "היקף"),
    (["תל אביב"], "לכל 10000 תושבים", "היקף"),
])
def test_chart_labels_may_be_periods_and_units_per_n(labels, unit, name):
    series, led, cat, f1 = _setup()
    d = _draft(f1)
    d["charts"][0]["series"][0]["name"] = name
    d["charts"].append({"id": "c2", "type": "bar", "title": "השוואה", "unit": unit,
                        "bars": [{"label": lb, "fact": f1.id} for lb in labels]})
    d["blocks"].insert(2, {"type": "chart", "chart": "c2"})
    _, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    assert problems == []


@pytest.mark.parametrize("text, hits", [
    ("מס הרכישה נותר ברמה של שמונה אחוזים", 1),
    ("גידול של שלושה מיליארד שקל", 1),
    ("ירידה של חצי נקודת אחוז", 0),       # no "נקודות"/"אחוז" right after a number word
    ("ירידה של שתי נקודות אחוז", 1),
    ("זו הפעם הרביעית ברציפות, אחרי שלוש שנים", 0),
    ("בחמש השנים האחרונות", 0),
    ("גידול של כשלושה מיליון שקל", 1),
    ("כחצי מיליון נוסעים", 1),
    ("הוצאה של שלושה מיליוני שקלים", 1),
    ("השקעה של כחמישה מיליארד שקל", 1),
    ("פי שלושה מבעבר", 0),
    ("וכחצי מיליון נוסעים", 1),
    ("בכשלושה מיליון שקל", 1),
])
def test_spelled_numbers(text, hits):
    from services.news.ledger import spelled_numbers

    assert len(spelled_numbers(text)) == hits


def test_no_outside_link_is_needed():
    """User rule (2026-11-09): hedged explanations need no source."""
    series, led, cat, f1 = _setup()
    d = _draft(f1)
    d["blocks"][3]["text"] = d["blocks"][3]["text"].replace("[[לפי הודעת הריבית|s1]]", "ייתכן ש")
    d["sources"] = []
    core, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    assert problems == [] and core["sources"] == []


def test_news_sites_are_never_linked():
    series, led, cat, f1 = _setup()
    led.add_source("https://www.calcalist.co.il/real-estate", "כלכליסט", "כותרת. " + QUOTE + " סוף.")
    d = _draft(f1)
    d["blocks"][3]["text"] = d["blocks"][3]["text"].replace("|s1]]", "|s2]]")
    d["sources"] = [{"id": "s2", "quote": QUOTE}]
    _, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    assert any("not an official government source" in p for p in problems)


@pytest.mark.parametrize("text, needle", [
    ("לעומת אוגוסט 2025 אשתקד", "אשתקד"),
    ("באוגוסט 2026 האחרון", "the date already says it"),
    ("מאז 2011 ועד כה", "filler"),
    ("סכום של 888,769 אלפי שקלים", "thousands of shekels"),
])
def test_style_patterns(text, needle):
    series, led, cat, f1 = _setup()
    d = _draft(f1)
    d["blocks"][3]["text"] += " " + text.replace("888,769", "{" + f1.id + "}")
    _, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    assert any(needle in p for p in problems), problems


@pytest.mark.parametrize("text, bad", [
    ("ההיקף עלה — ובחדות", True),
    ("ההיקף עלה – ובחדות", True),
    ("ההיקף עלה - ובחדות", True),
    ("ההיקף עלה…", True),
    ("ההיקף עלה...", True),
    ("ההיקף עלה 📈", True),
    ("בשנים 2019–2025 ההיקף עלה, ובחדות.", False),   # a range between numbers is fine
    ("תל אביב-יפו ובית־שמש", False),                 # hyphen/maqaf inside names
])
def test_ai_punctuation(text, bad):
    series, led, cat, f1 = _setup()
    d = _draft(f1)
    d["blocks"][3]["text"] += " " + text
    _, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    assert any(p.startswith("punctuation") for p in problems) is bad, problems


def test_prompts_have_no_ai_punctuation():
    """Models copy their prompt's style: the prompts model the punctuation rule."""
    from pathlib import Path

    for p in (Path(gates.__file__).parent / "prompts").glob("*.md"):
        t = p.read_text(encoding="utf-8")
        assert "—" not in t and "…" not in t, p.name


def test_calc_scale():
    led = Ledger()
    a = led.add(888769, label="k NIS", provenance="a")
    assert led.calc("scale", a.id, factor=0.001).value == pytest.approx(888.769)
    with pytest.raises(ValueError):
        led.calc("scale", a.id, factor=0.37)


def test_same_provenance_new_value_gets_a_new_fact():
    led = Ledger()
    a = led.add(1, label="x", provenance="p")
    assert led.add(1, label="x", provenance="p").id == a.id
    b = led.add(2, label="x", provenance="p")
    assert b.id != a.id and b.value == 2 and led.facts[a.id].value == 1
    assert led.add(2, label="x", provenance="p").id == b.id
    assert led.add(1, label="x", provenance="p").id == a.id


class _StubQuery:
    def __init__(self, res):
        self.res = res

    def run(self, query):
        return self.res


def _sql_toolbox(res):
    from services.news.tools import Toolbox

    tb = Toolbox(ledger=Ledger(), series={}, models={}, catalog={})
    tb._queries["ds1"] = _StubQuery(res)
    return tb


def test_sql_duplicate_column_names_get_their_own_facts():
    tb = _sql_toolbox({"columns": ["cnt", "cnt"], "rows": [[120, 95]], "truncated": False})
    cells = tb.t_sql("ds1", "SELECT a.cnt, b.cnt FROM t a JOIN t b ON true")["rows"][0]
    assert cells[0]["fact"] != cells[1]["fact"]
    for c in cells:
        assert tb.ledger.facts[c["fact"]].value == c["v"]


def test_sql_rerun_in_another_order_keeps_values_with_their_facts():
    tb = _sql_toolbox({"columns": ["city", "n"], "rows": [["a", 10], ["b", 20]], "truncated": False})
    q = "SELECT city, count(*) n FROM t GROUP BY city LIMIT 2"
    tb.t_sql("ds1", q)
    tb._queries["ds1"].res = {"columns": ["city", "n"], "rows": [["b", 20], ["a", 10]],
                              "truncated": False}
    for r in tb.t_sql("ds1", q)["rows"]:
        assert tb.ledger.facts[r[1]["fact"]].value == r[1]["v"]


def test_only_official_search_results_are_citable():
    from services.news.tools import Toolbox

    class LLM:
        def web_search(self, q):
            return [{"url": "https://www.gov.il/he/pages/x", "title": "מס רכישה",
                     "snippet": "שיעור מס הרכישה על דירה נוספת עודכן, כך לפי רשות המסים. " * 3},
                    {"url": "https://www.globes.co.il/a", "title": "גלובס",
                     "snippet": "משקיעים מתרחקים משוק הדירות על רקע מס הרכישה והריבית הגבוהה. " * 3}]

    led = Ledger()
    res = Toolbox(ledger=led, series={}, models={}, catalog={}, llm=LLM()).t_web_search("q")["results"]
    assert res[0]["source"] == "s1"
    assert "source" not in res[1] and res[1]["context_only"]
    assert len(led.sources) == 1


def test_stray_year_gets_actionable_feedback():
    series, led, cat, f1 = _setup()
    d = _draft(f1)
    d["blocks"][3]["text"] += " 2025 הייתה שנה חלשה, ונרשמו 1,200 עסקאות."
    _, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    assert any("years without date context ['2025']" in p for p in problems)
    assert any("typed numbers ['1,200']" in p for p in problems)


def test_slugify():
    assert gates.slugify("Mortgage Volume — Sept. 2026!") == "mortgage-volume-sept-2026"
