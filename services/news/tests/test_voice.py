"""The checks against machine-sounding copy: number density, overused words,
the desk's stock phrases, length by kind."""
from __future__ import annotations

from services.news import gates
from services.news.stock import stock_phrases
from services.news.tests.test_ledger_gates import FILLER, _draft, _setup


def _check(draft, **kw):
    series, led, cat, _ = _setup()
    return gates.check(draft, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"}, **kw)


def _with_lead(f1, lead: str) -> dict:
    d = _draft(f1)
    d["blocks"][0] = {"type": "p", "text": "לפי [[נתוני בנק ישראל|ds:boi-mortgage-rates]] " + lead
                                           + " " + FILLER * 3}
    return d


def test_a_paragraph_with_too_many_numbers_is_sent_back():
    _, _, _, f1 = _setup()
    t = f"{{{f1.id}:num2}}"
    _, ok = _check(_with_lead(f1, " ".join([f"היקף של {t} מיליארד."] * gates.MAX_NUMBERS_PER_PARAGRAPH)))
    assert not [p for p in ok if "numbers in one paragraph" in p]
    _, bad = _check(_with_lead(f1, " ".join([f"היקף של {t} מיליארד."] * (gates.MAX_NUMBERS_PER_PARAGRAPH + 1))))
    assert [p for p in bad if "numbers in one paragraph" in p]


def test_a_number_in_parentheses_is_sent_back():
    _, _, _, f1 = _setup()
    _, probs = _check(_with_lead(f1, f"ההיקף עלה (לעומת {{{f1.id}:num2}} מיליארד בחודש הקודם)."))
    assert [p for p in probs if "number in parentheses" in p]
    # parentheses without a number are fine
    _, probs = _check(_with_lead(f1, "ההיקף עלה (בעיקר במסלול הקבוע)."))
    assert not [p for p in probs if "parentheses" in p]


def test_overused_words_over_their_cap():
    _, _, _, f1 = _setup()
    _, probs = _check(_with_lead(f1, "אחד ההסברים האפשריים הוא הריבית."))
    assert [p for p in probs if "overused: «אחד ההסברים האפשריים»" in p]
    _, probs = _check(_with_lead(f1, "ההיקף נמוך בלבד. והפער קטן בלבד."))
    assert [p for p in probs if "overused: «בלבד» 2×" in p]
    _, probs = _check(_with_lead(f1, "ההיקף נמוך בלבד."))
    assert not [p for p in probs if "overused" in p]
    # prefixes count, a longer word doesn't
    _, probs = _check(_with_lead(f1, "ובמקביל עלה. במקביל ירד. מקבילים רבים."))
    assert [p for p in probs if "overused: «במקביל» 2×" in p]


def test_a_stock_phrase_may_appear_once():
    _, _, _, f1 = _setup()
    d = _with_lead(f1, "הנתונים צפויים להתפרסם בדצמבר. נתוני ינואר צפויים להתפרסם בפברואר.")
    _, probs = _check(d, stock=["צפויים להתפרסם"])
    assert [p for p in probs if "stock phrase: «צפויים להתפרסם» appears 2×" in p]
    _, probs = _check(_with_lead(f1, "הנתונים צפויים להתפרסם בדצמבר."), stock=["צפויים להתפרסם"])
    assert not [p for p in probs if "stock phrase" in p]


def test_body_length_depends_on_the_kind():
    _, _, _, f1 = _setup()
    d = _draft(f1)
    d["blocks"][3] = {"type": "p", "text": "[[לפי הודעת הריבית|s1]] הוועדה לא שינתה את הריבית. "
                                           + FILLER * 36}
    _, news = _check(d)
    _, feature = _check(d, article_kind="feature")
    assert [p for p in news if p.startswith("body length")]
    assert not [p for p in feature if p.startswith("body length")]


def _art(*paras):
    return {"blocks": [{"type": "p", "runs": [{"t": "text", "v": p}]} for p in paras]}


TOPICS = ["החג", "הריבית", "המלחמה", "מזג האוויר", "הבחירות", "השביתה", "הייצוא", "התיירות"]


def test_stock_phrases_are_shared_runs_minus_names_and_grammar():
    arts = [_art(f"אחד ההסברים האפשריים הוא {t}. לפי נתוני הלשכה המרכזית לסטטיסטיקה, עלייה של 4% "
                 f"בספטמבר.", f"פסקה על {t} בלבד.") for t in TOPICS]
    got = stock_phrases(arts)
    assert got == ["אחד ההסברים האפשריים"]          # the 2-word parts fold into it
    assert not any("לסטטיסטיקה" in p for p in got)  # a publisher's name
    assert not any(p.endswith(" של") for p in got)  # ends on grammar
    assert stock_phrases(arts[:3]) == []            # too few articles to say
    assert stock_phrases(arts, names=["אחד ההסברים האפשריים בעולם"]) == []


def test_stock_phrases_need_a_share_of_the_articles():
    arts = ([_art(f"אחד ההסברים האפשריים הוא {t}.") for t in TOPICS[:4]]
            + [_art(f"{t} {i}.") for i in range(2) for t in TOPICS])
    assert stock_phrases(arts) == []                 # 4 of 20 is under 30%
    assert stock_phrases(arts, min_share=0.2) == ["אחד ההסברים האפשריים"]


def test_the_examples_model_every_rule_they_teach():
    """The writer imitates its examples: each must pass the checks it is held to."""
    from pathlib import Path

    from services.news import writer

    files = sorted((Path(gates.__file__).parent / "prompts" / "exemplars").glob("*.md"))
    assert len(files) >= 4
    for f in files:
        t = f.read_text(encoding="utf-8")
        prose = "\n".join(line for line in t.splitlines() if not line.startswith("("))
        assert not [p for p in gates.BANNED if p in prose], f.name
        assert not [why for rx, why in gates.PUNCTUATION if rx.search(prose)], f.name
        assert not [label for label, rx, cap, _ in gates.OVERUSED if len(rx.findall(prose)) > cap], f.name
        assert "!" not in prose and "?" not in prose, f.name
    # a news brief gets news examples first, rotated by its signals
    a, b = writer.exemplars("news", "k1"), writer.exemplars("news", "k2")
    assert len(a) == writer.EXEMPLARS and a != b
    assert all("(news" in x for x in a[:2]) and "(feature" in a[2]
    assert all("(feature" in x for x in writer.exemplars("feature", "k1")[:2])
    assert "# Examples of the target voice" in writer.system_prompt("news", "k1")
