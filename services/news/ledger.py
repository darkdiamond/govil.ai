"""The fact ledger: every number an article prints, and every outside claim.

The writer never types a number. Each value it may use is a registered
`Fact` (from a series point, a SQL result cell, a KPI, or a `calc` over other
facts), and prose refers to it as `{f12}` or `{f12:fmt}`; this module renders
it with govlib's formatters. A number in the prose that is not a token is a
gate failure (`stray_numbers`), so a hallucinated figure cannot reach a page.

Outside claims link to a fetched page: `[[anchor text|s3]]`. Links to our own
dataset pages: `[[anchor text|ds:<dataset id>]]`.

Rendered text is a list of runs for the frontend to draw as text nodes (no
model-written HTML reaches a page):
    {"t": "text", "v": "…"}
    {"t": "link", "v": "anchor", "href": "https://…", "kind": "source" | "dataset"}
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

from services.page_builder.recipe_lib.govlib import fmt

TOKEN = re.compile(r"\{(f\d+)(?::([a-z0-9_]+))?\}")
LINK = re.compile(r"\[\[([^\[\]|]+)\|(s\d+|ds:[A-Za-z0-9-]+)\]\]")
MONTHS = "|".join(fmt.MONTHS_HE + ["מרס"])
# Digits prose may keep: a day of a named month ("3 במרץ"), and a calendar
# year — but only where the words around it make it a date ("ב-2025",
# "בשנת 2025", "מרץ 2025", "מאז 2019", "2019–2025"), so a typed count that
# happens to look like a year ("נמכרו 1980 דירות") still fails.
_DAY_OF_MONTH = re.compile(rf"(?<![\d.,])(?:[1-9]|[12]\d|3[01])(?=\s*(?:ב|ל|ה|-)?\s*(?:{MONTHS}))")
_YEAR = re.compile(r"(?<![\d.,])(?:19[4-9]\d|20[0-4]\d)(?![\d.,%])")
_YEAR_LEAD = re.compile(
    rf"(?:(?:^|[\s(\"'״])[ובלמהשכ]{{1,3}}-?"
    rf"|(?:{MONTHS}|שנת|שנות|שנים|מאז|עד|לפני|אחרי|לעומת|מול|בין|מתחילת|מסוף|בשנים|בשנת)\s+"
    rf"|\(|[–-]\s*)$"
)
_DIGITS = re.compile(r"\d")
SCALE_FACTORS = {1e-9, 1e-6, 1e-3, 1e3, 1e6}
# A quantity spelled in words ("שמונה אחוזים", "שלושה מיליארד שקל") is a typed
# number too. Words alone ("שלוש שנים", "חודשיים") are ordinary prose.
_NUMBER_WORD = (r"(?:אחד|אחת|שתיים|שניים|שתי|שני|שלוש|שלושה|ארבע|ארבעה|חמש|חמישה|שש|שישה|שבע|"
                r"שבעה|שמונה|תשע|תשעה|עשר|עשרה|עשרים|שלושים|ארבעים|חמישים|שישים|שבעים|שמונים|"
                r"תשעים|מאה|מאתיים|מאות|אלף|אלפיים|אלפים|חצי|רבע|שליש)")
_SPELLED = re.compile(rf"(?<![א-ת])[ובלמהש]?{_NUMBER_WORD}(?:\s+(?:ו?{_NUMBER_WORD}))*\s+"
                      r"(?:אחוז|אחוזים|נקודות\s+אחוז|נקודות|מיליון|מיליארד|מיליארדי|אלף|שקל|שקלים|ש\"ח|₪)(?![א-ת])")


def spelled_numbers(text: str) -> list[str]:
    """Quantities written out in Hebrew words instead of fact tokens."""
    return [m[0] for m in _SPELLED.finditer(LINK.sub(lambda m: f" {m[1]} ", TOKEN.sub(" ", text)))]


@dataclass
class Fact:
    id: str
    value: float
    label: str
    provenance: str            # how it was obtained: "series:<ds>:<path>@<period>", "sql:…", "calc:…"
    unit: str | None = None    # count | pct | ils | rate | index | None
    period: str | None = None
    dataset_id: str | None = None


@dataclass
class Source:
    id: str
    url: str
    title: str
    text: str = field(repr=False)
    kind: str = "fetched"      # fetched | search_extract


FORMATS = ("auto", "int", "num0", "num1", "num2", "pct", "pct0", "spct", "abs", "abs1", "abs_pct", "pp")


def format_value(v: float, spec: str | None = None) -> str:
    """One number as Hebrew page text (minus sign U+2212, thousands commas)."""
    spec = spec or "auto"
    if not math.isfinite(v):
        raise ValueError(f"cannot print {v}")
    if spec == "auto":
        if float(v).is_integer():
            spec = "int"
        else:
            spec = "num2" if abs(v) < 10 else "num1"
    neg = v < 0
    a = abs(v)
    if spec == "int":
        s = fmt.int_he(a)
    elif spec in ("num0", "num1", "num2"):
        s = fmt.num_he(a, int(spec[-1]))
    elif spec in ("pct", "pct0"):
        s = fmt.pct_of(a, 0 if spec == "pct0" else 1)
    elif spec == "spct":
        return fmt.isolate(fmt.signed_pct(v / 100))
    elif spec == "abs":
        return fmt.int_he(a) if float(a).is_integer() else fmt.num_he(a, 1)
    elif spec == "abs1":
        return fmt.num_he(a, 1)
    elif spec == "abs_pct":
        return fmt.pct_of(a, 1)
    elif spec == "pp":
        s = fmt.num_he(a, 2 if a < 1 else 1)
        return fmt.isolate(("+" if v > 0 else fmt.MINUS if neg else "") + s)
    else:
        raise ValueError(f"unknown format {spec!r}")
    return fmt.isolate(fmt.MINUS + s) if neg else s


class Ledger:
    def __init__(self):
        self.facts: dict[str, Fact] = {}
        self.sources: dict[str, Source] = {}
        self._by_prov: dict[str, str] = {}
        self._by_url: dict[str, str] = {}

    def add(self, value: float, *, label: str, provenance: str, unit: str | None = None,
            period: str | None = None, dataset_id: str | None = None) -> Fact:
        """Register a value (the same provenance gets the same id)."""
        v = float(value)
        if not math.isfinite(v):
            raise ValueError("facts must be finite numbers")
        if (fid := self._by_prov.get(provenance)) is not None:
            return self.facts[fid]
        f = Fact(f"f{len(self.facts) + 1}", v, label, provenance, unit, period, dataset_id)
        self.facts[f.id] = f
        self._by_prov[provenance] = f.id
        return f

    def add_source(self, url: str, title: str, text: str, *, kind: str = "fetched") -> Source:
        """`kind`: fetched (we read the page) | search_extract (the search
        provider's extract — the only way to quote gov.il, which renders with
        JavaScript). A page we fetch replaces an extract of the same URL."""
        if url.startswith("http://"):  # search engines hand back http:// for https sites
            url = "https://" + url[len("http://"):]
        if not url.startswith("https://"):
            raise ValueError(f"not a web URL: {url[:60]}")
        if (sid := self._by_url.get(url)) is not None:
            s = self.sources[sid]
            if kind == "fetched" and s.kind != "fetched":
                s.text, s.title, s.kind = text, title or s.title, "fetched"
            return s
        s = Source(f"s{len(self.sources) + 1}", url, title, text, kind)
        self.sources[s.id] = s
        self._by_url[url] = s.id
        return s

    def calc(self, op: str, a: str, b: str | None = None, *, label: str = "",
             factor: float | None = None) -> Fact:
        """A derived fact, traceable to its inputs."""
        fa = self.facts[a]
        fb = self.facts[b] if b else None
        if op == "diff":
            v, unit = fa.value - fb.value, fa.unit
        elif op == "pct_change":
            if not fb.value:
                raise ValueError("pct_change from zero")
            v, unit = (fa.value - fb.value) / abs(fb.value) * 100, "pct"
        elif op == "ratio":
            if not fb.value:
                raise ValueError("ratio over zero")
            v, unit = fa.value / fb.value, None
        elif op == "share":
            if not fb.value:
                raise ValueError("share of zero")
            v, unit = fa.value / fb.value * 100, "pct"
        elif op == "sum":
            v, unit = fa.value + fb.value, fa.unit
        elif op == "abs":
            v, unit = abs(fa.value), fa.unit
        elif op == "scale":
            # Unit changes only (thousands → millions …), so a powers-of-ten factor.
            if factor not in SCALE_FACTORS:
                raise ValueError(f"scale factor must be one of {sorted(SCALE_FACTORS)}")
            v, unit = fa.value * factor, fa.unit
        else:
            raise ValueError(f"unknown op {op!r}")
        extra = f":{factor}" if op == "scale" else ""
        return self.add(v, label=label or f"{op}({a}{', ' + b if b else ''})",
                        provenance=f"calc:{op}:{a}:{b or ''}{extra}", unit=unit,
                        period=fa.period, dataset_id=fa.dataset_id)

    def dump(self) -> dict:
        return {"facts": [asdict(f) for f in self.facts.values()],
                "sources": [{"id": s.id, "url": s.url, "title": s.title, "kind": s.kind}
                            for s in self.sources.values()]}


def stray_numbers(text: str) -> list[str]:
    """Digits in prose that are not fact tokens (years and day-of-month dates
    excepted). Empty means the text is clean."""
    t = TOKEN.sub(" ", text)
    t = LINK.sub(lambda m: f" {m[1]} ", t)
    t = _DAY_OF_MONTH.sub(" ", t)
    t = _YEAR.sub(lambda m: " " if _YEAR_LEAD.search(t[max(0, m.start() - 14):m.start()]) else m[0], t)
    return [m for m in re.findall(r"\S*\d\S*", t) if _DIGITS.search(m)]


def render(text: str, ledger: Ledger, dataset_href) -> tuple[list[dict], list[str]]:
    """Text with tokens/links → runs. `dataset_href(id)` → page URL or None.
    Returns (runs, problems); any problem means the text must not ship."""
    problems: list[str] = []

    def fill(s: str) -> str:
        def one(m):
            f = ledger.facts.get(m[1])
            if f is None:
                problems.append(f"unknown fact {m[1]}")
                return m[0]
            try:
                return format_value(f.value, m[2])
            except ValueError as e:
                problems.append(f"{m[0]}: {e}")
                return m[0]
        return TOKEN.sub(one, s)

    runs: list[dict] = []
    pos = 0
    for m in LINK.finditer(text):
        if m.start() > pos:
            runs.append({"t": "text", "v": fill(text[pos:m.start()])})
        anchor, ref = fill(m[1]), m[2]
        if ref.startswith("ds:"):
            href = dataset_href(ref[3:])
            if href is None:
                problems.append(f"unknown dataset {ref[3:]}")
            runs.append({"t": "link", "v": anchor, "href": href, "kind": "dataset", "id": ref[3:]})
        else:
            src = ledger.sources.get(ref)
            if src is None:
                problems.append(f"unknown source {ref}")
            runs.append({"t": "link", "v": anchor, "href": src.url if src else None, "kind": "source"})
        pos = m.end()
    if pos < len(text):
        runs.append({"t": "text", "v": fill(text[pos:])})
    leftovers = [r["v"] for r in runs if r["t"] == "text" and ("[[" in r["v"] or "]]" in r["v"])]
    if leftovers:
        problems.append("malformed link markup")
    return runs, problems


def plain(runs: list[dict]) -> str:
    return "".join(r["v"] for r in runs)
