"""Quality gates between a draft and the site — the human editor we don't have.

`check(draft)` is deterministic and runs first: it renders every token, link
and chart, and lists every problem (any one blocks publication):

  - a number typed into prose (not a fact token), an unknown fact/source/dataset id
  - a linked source without a verbatim quote that appears in the fetched page
  - a dataset in `dataset_ids` never linked from the text, or unknown to us
  - a chart that doesn't resolve to real series/facts; none, or more than 3
  - banned AI-slop phrases and punctuation (em dashes, dash-as-punctuation,
    ellipses, exclamation marks), question subheads
  - headline/dek/body length, too little Hebrew

`critique()` then asks the model, as copy chief, for pass / revise / kill
(prompts/critic.md). The writer gets one revision round for either kind of
problem.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from . import charts as charts_mod
from .fetch import official_source
from .ledger import (
    FORMATS,
    LINK,
    TOKEN,
    YEARLIKE,
    Ledger,
    format_value,
    plain,
    render,
    spelled_numbers,
    stray_numbers,
)
from .series import parse_period

PROMPTS = Path(__file__).with_name("prompts")
HEADLINE_MAX, DEK_MAX = 95, 180
WORDS_MIN, WORDS_MAX = 300, 1100
QUOTE_MIN = 20
MAX_CHARTS = 3
HEBREW_MIN = 0.85
BANNED = [
    "חשוב לציין", "ראוי לציין", "יש לציין", "כדאי לציין", "לסיכום", "בסופו של דבר",
    "השורה התחתונה", "בעידן ה", "בעולם המשתנה", "צלילה", "נצלול", "צוללים", "מרתק",
    "מעורר השראה", "פורץ דרך", "מהפכני", "חשוב להבין", "כפי שניתן לראות", "במאמר זה",
    "נבחן את", "נסקור", "לא תאמינו", "הסיבה המפתיעה",
]
_NOT_ONLY = re.compile(r"לא רק\b.{0,80}?\bאלא גם")
PUNCTUATION = [
    (re.compile("—"), "no em dashes: use a comma, a period, or two sentences"),
    (re.compile(r"(?<!\d)\s[–-]\s|\s[–-]\s(?!\d)"), "no dash as punctuation between words"),
    (re.compile("…|\\.\\.\\."), "no ellipses"),
    (re.compile(r"[\U0001F300-\U0001FAFF☀-➿]"), "no emoji or symbols"),
]
_MONTHS = "ינואר|פברואר|מרץ|מרס|אפריל|מאי|יוני|יולי|אוגוסט|ספטמבר|אוקטובר|נובמבר|דצמבר"
# Tautologies the first real drafts leaned on (2026-11-09 dry runs), and raw
# source units a reader shouldn't see.
PATTERNS = [
    (re.compile(r"(?:19|20)\d\d\s+אשתקד"), "a year plus אשתקד — one or the other"),
    (re.compile(rf"(?:{_MONTHS})\s+(?:19|20)\d\d\s+(?:הנוכחי|האחרון|הקרוב|שעבר)"),
     "month + year + הנוכחי/האחרון — the date already says it"),
    (re.compile(r"ועד כה|ועד היום|ומאז החל|באותה תקופה"), "filler after a date"),
    (re.compile(r"אלפי (?:שקלים|ש\"ח|ש״ח)"), "thousands of shekels — scale to millions/billions (calc scale)"),
]
_HEB = re.compile(r"[א-ת]")
_LAT = re.compile(r"[A-Za-z]")


# Chart labels only (never prose, the stat label or the image alt): a category
# or legend label may be, in its entirety, a period: a year span ("2024/25",
# "2024-25") or a period the series code parses ("2025", "2024-11", "2024-Q3",
# "מאי 2024"). A unit may name a per-N denominator of 10 to 100,000
# ("לכל 1,000 תושבים", "ל-100 ק\"ג"; not "ל-100 אלף"). Every other digit is
# checked as in prose.
_YEAR_SPAN = re.compile(r"(?:19|20)\d\d[/–-]\d\d")
_PER_N = re.compile(r"(?<![א-ת])(?:ל-?|לכל\s+)(?:10|100|1,?000|10,?000|100,?000)"
                    r"(?=\s+(?!(?:אלף|אלפי|מיליון|מיליוני|מיליארד)(?![א-ת]))[א-ת])")


def _chart_numbers_text(s: str, kind: str) -> str:
    """The part of a chart label or unit the number checks still read."""
    if kind == "label" and (parse_period(s.strip()) or _YEAR_SPAN.fullmatch(s.strip())):
        return ""
    if kind == "unit":
        return _PER_N.sub(" ", s)
    return s


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub("[\u200e\u200f\u2066-\u2069\u202a-\u202e]", "", s)  # bidi marks
    s = re.sub(r"[\"'״׳“”„‘’`]", "", s)                                   # quote variants
    return re.sub(r"\s+", " ", s).strip().lower()


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:80].strip("-")


def check(draft: dict, *, ledger: Ledger, series_by_ds: dict, catalog: dict,
          vocab: set[str]) -> tuple[dict, list[str]]:
    """(rendered article core, problems)."""
    problems: list[str] = []
    if not isinstance(draft, dict):
        return {}, ["the article must be a JSON object"]
    # Model JSON: keep only entries of the expected shape, and say so.
    for key in ("charts", "blocks", "sources"):
        items = draft.get(key) or []
        if not isinstance(items, list):
            problems.append(f"{key}: must be a list")
            items = []
        kept = [x for x in items if isinstance(x, dict)]
        if len(kept) != len(items):
            problems.append(f"{key}: every entry must be an object")
        draft = {**draft, key: kept}
    draft = {**draft, "tags": [t for t in draft.get("tags") or [] if isinstance(t, str)]
             if isinstance(draft.get("tags"), list) else []}

    def href(ds):
        if ds in catalog:
            return f"/datasets/{catalog[ds].get('page_slug') or ds}/"
        return f"/datasets/{ds}/" if ds in series_by_ds else None

    def text(field_name: str, s, *, numbers_ok=False) -> tuple[list[dict], str]:
        s = str(s or "")
        if not numbers_ok and (bad := stray_numbers(s)):
            # A year has no fact token: telling the writer to use one gives it
            # nothing to fix (the 2026-11-09 live story died on exactly that).
            years = [b for b in bad if YEARLIKE.fullmatch(b)]
            others = [b for b in bad if b not in years]
            if others:
                problems.append(f"{field_name}: typed numbers {others[:5]} — use fact tokens")
            if years:
                problems.append(
                    f"{field_name}: years without date context {years[:5]} — write the year as "
                    "a date ('בשנת 2025', 'ב-2025', after a month name, 'מאז 2019', a range "
                    "'2019–2025'); if it is a count that only looks like a year, use a fact token")
        if not numbers_ok and (bad := spelled_numbers(s)):
            problems.append(f"{field_name}: quantities spelled in words {bad[:3]} — a number from "
                            "data needs a fact token; one from a source needs that source linked "
                            "and quoted, or leave it out")
        runs, probs = render(s, ledger, href)
        problems.extend(f"{field_name}: {p}" for p in probs)
        return runs, plain(runs)

    # Fields printed as written (chart labels, image alt): the same number
    # checks as prose, no tokens or links (they would print raw), and the text
    # joins the punctuation and banned-phrase scan below.
    printed: list[str] = []

    def raw_field(field_name: str, s, chart: str | None = None) -> None:
        s = str(s or "")
        text(field_name, _chart_numbers_text(s, chart) if chart else s)
        if TOKEN.search(s) or LINK.search(s):
            problems.append(f"{field_name}: no fact tokens or links here")
        printed.append(s)

    head_runs, headline = text("headline", draft.get("headline"))
    _, dek = text("dek", draft.get("dek"))
    if not 15 <= len(headline) <= HEADLINE_MAX:
        problems.append(f"headline length {len(headline)} (15–{HEADLINE_MAX})")
    if ":" in headline:
        problems.append("headline: no colon formula")
    if any(r["t"] == "link" for r in head_runs):
        problems.append("headline: no links")
    if not 20 <= len(dek) <= DEK_MAX:
        problems.append(f"dek length {len(dek)} (20–{DEK_MAX})")

    ds_ids = [d for d in draft.get("dataset_ids") or [] if isinstance(d, str)]
    if not ds_ids:
        problems.append("dataset_ids: at least one dataset")
    for d in ds_ids:
        if href(d) is None:
            problems.append(f"dataset_ids: unknown dataset {d}")

    charts_out, chart_ids = [], set()
    for spec in (draft.get("charts") or [])[:MAX_CHARTS + 1]:
        try:
            c = charts_mod.resolve(spec, series_by_ds, ledger)
            charts_out.append(c)
            chart_ids.add(c["id"])
            # The strings the chart prints, fallbacks included (a bar with no
            # label prints its fact's label, which the model can write too).
            cname = f"chart {c['id']}"
            raw_field(f"{cname} title", c["title"])
            raw_field(f"{cname} unit", c["unit"], "unit")
            if c["type"] == "line":
                for j, (r, ser) in enumerate(zip(spec["series"], c["option"]["series"], strict=True)):
                    own = "" if r.get("name") else " (the series' own name: give it an explicit name)"
                    raw_field(f"{cname} series {j} name{own}", ser["name"], "label")
                for x in dict.fromkeys(c["option"]["xAxis"]["data"]):
                    raw_field(f"{cname} x label", x, "label")
            else:
                for j, (r, x) in enumerate(zip(spec["bars"], c["option"]["xAxis"]["data"], strict=True)):
                    own = "" if r.get("label") else " (the fact's own label: give the bar an explicit label)"
                    raw_field(f"{cname} bar {j} label{own}", x, "label")
        except charts_mod.ChartError as e:
            problems.append(f"chart: {e}")
        except (AttributeError, TypeError, KeyError) as e:  # a mis-shaped spec
            problems.append(f"chart: malformed spec ({type(e).__name__})")
    if not charts_out:
        problems.append("charts: at least one chart")
    if len(draft.get("charts") or []) > MAX_CHARTS:
        problems.append(f"charts: at most {MAX_CHARTS}")

    blocks, body_text, linked_sources, linked_ds, stats = [], [], set(), set(), 0
    placed = set()
    for i, b in enumerate(draft.get("blocks") or []):
        kind = (b or {}).get("type")
        if kind == "p":
            raw = str(b.get("text") or "")
            for m in LINK.finditer(raw):
                (linked_ds.add(m[2][3:]) if m[2].startswith("ds:") else linked_sources.add(m[2]))
            runs, ptxt = text(f"block {i}", raw)
            blocks.append({"type": "p", "runs": runs})
            body_text.append(ptxt)
        elif kind == "h2":
            _, htxt = text(f"block {i}", b.get("text"))
            if "?" in htxt:
                problems.append(f"block {i}: question subhead")
            blocks.append({"type": "h2", "text": htxt})
            body_text.append(htxt)
        elif kind == "chart":
            cid = b.get("chart")
            if cid not in chart_ids:
                problems.append(f"block {i}: unknown chart {cid}")
            else:
                placed.add(cid)
                blocks.append({"type": "chart", "chart": cid})
        elif kind == "stat":
            stats += 1
            f = ledger.facts.get(b.get("fact"))
            _, label = text(f"block {i} label", b.get("label"))
            printed.append(label)
            sfmt = b.get("fmt") or None
            if f is None:
                problems.append(f"block {i}: unknown fact {b.get('fact')}")
            elif sfmt is not None and sfmt not in FORMATS:
                problems.append(f"block {i}: format {str(sfmt)[:40]!r} is not one of {list(FORMATS)}")
            else:
                # The value is the formatted fact and nothing else.
                try:
                    value = format_value(f.value, sfmt)
                except ValueError as e:
                    problems.append(f"block {i}: {e}")
                else:
                    blocks.append({"type": "stat", "value": value, "label": label})
        else:
            problems.append(f"block {i}: unknown type {kind!r}")
    if stats > 1:
        problems.append("at most one stat block")
    for c in charts_out:
        if c["id"] not in placed:
            problems.append(f"chart {c['id']} is never placed in the blocks")
    for d in ds_ids:
        if d not in linked_ds:
            problems.append(f"dataset {d} is never linked in the text ([[…|ds:{d}]])")

    body = "\n".join(body_text)
    words = len(re.findall(r"\S+", body))
    if not WORDS_MIN <= words <= WORDS_MAX:
        problems.append(f"body length {words} words ({WORDS_MIN}–{WORDS_MAX})")
    every = prose = f"{headline} {dek} {body}"
    heb, lat = len(_HEB.findall(every)), len(_LAT.findall(every))
    if heb + lat and heb / (heb + lat) < HEBREW_MIN:
        problems.append("too little Hebrew")
    raw_field("image_alt_he", draft.get("image_alt_he"))
    every = "\n".join([every, *printed])
    low = every.lower()
    hits = [p for p in BANNED if p in low]
    if _NOT_ONLY.search(every):
        hits.append("לא רק … אלא גם")
    for rx, why in PATTERNS:
        if m := rx.search(prose):
            problems.append(f"style: «{m[0]}» — {why}")
    if hits:
        problems.append(f"banned phrases: {hits}")
    if "!" in every:
        problems.append("no exclamation marks")
    # Punctuation that reads as machine-written (user rule, 2026-11-09). A
    # dash between two numbers is a range ("2019–2025") and stays.
    for rx, why in PUNCTUATION:
        if m := rx.search(every):
            problems.append(f"punctuation: «{every[max(0, m.start() - 15):m.end() + 15]}» — {why}")

    quotes = {s.get("id"): str(s.get("quote") or "") for s in draft.get("sources") or []
              if isinstance(s, dict)}
    sources = []
    for sid in sorted(linked_sources, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0):
        src = ledger.sources.get(sid)
        if src is None:
            continue  # already reported by render()
        if not official_source(src.url):
            # The user's rule: articles cite government data only. The web is
            # read for context and possible reasons, never linked.
            problems.append(f"source {sid}: {src.url} is not an official government source — "
                            "articles link only our dataset pages and official data publishers; "
                            "use what you read elsewhere as context, without a link")
            continue
        q = quotes.get(sid, "")
        if len(_norm(q)) < QUOTE_MIN:
            problems.append(f"source {sid}: a verbatim quote of ≥{QUOTE_MIN} chars is required")
        elif _norm(q) not in _norm(src.text):
            problems.append(f"source {sid}: quote not found in the fetched page")
        url = "https://" + src.url[len("http://"):] if src.url.startswith("http://") else src.url
        sources.append({"id": sid, "url": url, "title": src.title, "quote": q, "kind": src.kind})

    tags = [t for t in draft.get("tags") or [] if t in vocab][:5]
    if not tags:
        tags = sorted({t for d in ds_ids for t in (catalog.get(d) or {}).get("tags", []) if t in vocab})[:5]

    core = {
        "headline": headline, "dek": dek, "slug": slugify(draft.get("slug_en") or ""),
        "dataset_ids": ds_ids, "tags": tags, "blocks": blocks, "charts": charts_out,
        "sources": sources, "image_brief": str(draft.get("image_brief") or "")[:600],
        "image_alt": str(draft.get("image_alt_he") or "")[:200], "words": words,
    }
    if len(core["slug"]) < 8:
        problems.append("slug_en: a descriptive English slug")
    return core, problems


def as_markdown(core: dict) -> str:
    """The rendered article as the critic reads it."""
    out = [f"# {core['headline']}", f"_{core['dek']}_", ""]
    charts = {c["id"]: c for c in core["charts"]}
    for b in core["blocks"]:
        if b["type"] == "p":
            out.append("".join(f"[{r['v']}]({r['href']})" if r["t"] == "link" else r["v"]
                               for r in b["runs"]))
        elif b["type"] == "h2":
            out.append(f"## {b['text']}")
        elif b["type"] == "chart":
            c = charts[b["chart"]]
            out.append(f"[תרשים: {c['title']} ({c['unit']}), {len(c['table']) - 1} נקודות]")
        elif b["type"] == "stat":
            out.append(f"**{b['value']}** ({b['label']})")
        out.append("")
    if core["sources"]:
        # Shown to the critic only: the site renders the sources list itself.
        out.append("[for review — the quotes the reporter gave for each linked source]")
        out += [f"- {s['title']} <{s['url']}>: \"{s['quote']}\"" for s in core["sources"]]
    return "\n".join(out)


def critique(llm, core: dict) -> dict:
    style = (PROMPTS / "style_he.md").read_text(encoding="utf-8")
    system = (PROMPTS / "critic.md").read_text(encoding="utf-8") + "\n\n# Style guide\n\n" + style
    verdict = llm.chat_json([{"role": "system", "content": system},
                             {"role": "user", "content": as_markdown(core)}], temperature=0.2)
    v = verdict.get("verdict")
    scores = verdict.get("scores") or {}
    if v == "pass" and any((not isinstance(s, int | float)) or s < 4 for s in scores.values()):
        v = "revise"  # the rubric says pass needs every score ≥ 4
    if v not in ("pass", "revise", "kill"):
        v = "revise"
    return {"verdict": v, "scores": scores, "issues": verdict.get("issues") or [],
            "fixes": verdict.get("fixes") or []}
