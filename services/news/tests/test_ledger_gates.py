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
    assert runs[3] == {"t": "link", "v": "העמוד", "href": "/datasets/abc/", "kind": "dataset"}
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
    assert "מקורות" in gates.as_markdown(core)


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
])
def test_gate_catches(mutate, needle):
    series, led, cat, f1 = _setup()
    d = _draft(f1)
    mutate(d, f1)
    _, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    assert any(needle in p for p in problems), problems


def test_slugify():
    assert gates.slugify("Mortgage Volume — Sept. 2026!") == "mortgage-volume-sept-2026"
