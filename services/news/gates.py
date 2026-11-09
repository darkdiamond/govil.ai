"""Quality gates between a draft and the site — the human editor we don't have.

`check(draft)` is deterministic and runs first: it renders every token, link
and chart, and lists every problem (any one blocks publication):

  - a number typed into prose (not a fact token), an unknown fact/source/dataset id
  - a linked source without a verbatim quote that appears in the fetched page
  - a dataset in `dataset_ids` never linked from the text, or unknown to us
  - a chart that doesn't resolve to real series/facts; none, or more than 3
  - banned AI-slop phrases, exclamation marks, question subheads, em-dash chains
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
from .ledger import LINK, Ledger, plain, render, stray_numbers

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
_HEB = re.compile(r"[א-ת]")
_LAT = re.compile(r"[A-Za-z]")


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
            problems.append(f"{field_name}: typed numbers {bad[:5]} — use fact tokens")
        runs, probs = render(s, ledger, href)
        problems.extend(f"{field_name}: {p}" for p in probs)
        return runs, plain(runs)

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
            charts_out.append(charts_mod.resolve(spec, series_by_ds, ledger))
            chart_ids.add(charts_out[-1]["id"])
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
            if ptxt.count("—") > 1:
                problems.append(f"block {i}: em-dash chain")
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
            if f is None:
                problems.append(f"block {i}: unknown fact {b.get('fact')}")
            else:
                runs, _ = render("{" + f.id + (":" + b["fmt"] if b.get("fmt") else "") + "}", ledger, href)
                blocks.append({"type": "stat", "value": plain(runs), "label": label})
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
    every = f"{headline} {dek} {body}"
    heb, lat = len(_HEB.findall(every)), len(_LAT.findall(every))
    if heb + lat and heb / (heb + lat) < HEBREW_MIN:
        problems.append("too little Hebrew")
    low = every.lower()
    hits = [p for p in BANNED if p in low]
    if _NOT_ONLY.search(every):
        hits.append("לא רק … אלא גם")
    if hits:
        problems.append(f"banned phrases: {hits}")
    if "!" in every:
        problems.append("no exclamation marks")

    quotes = {s.get("id"): str(s.get("quote") or "") for s in draft.get("sources") or []
              if isinstance(s, dict)}
    sources = []
    for sid in sorted(linked_sources, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0):
        src = ledger.sources.get(sid)
        if src is None:
            continue  # already reported by render()
        q = quotes.get(sid, "")
        if len(q) < QUOTE_MIN:
            problems.append(f"source {sid}: a verbatim quote of ≥{QUOTE_MIN} chars is required")
        elif _norm(q) not in _norm(src.text):
            problems.append(f"source {sid}: quote not found in the fetched page")
        sources.append({"id": sid, "url": src.url, "title": src.title, "quote": q})

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
            out.append(f"**{b['value']}** — {b['label']}")
        out.append("")
    out.append("מקורות:")
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
