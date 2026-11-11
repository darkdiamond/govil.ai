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
import unicodedata
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
# A full numeric date ("14.9.2026", "9/11/2026") is a date whatever precedes it.
_DATE_DMY = re.compile(
    r"(?<![\d.,/])(?:[1-9]|[12]\d|3[01])[./](?:0?[1-9]|1[0-2])[./](?:19[4-9]\d|20[0-4]\d)(?![\d%]|[.,]\d)"
)
# A year, optionally a two-year span ("2025/26", "2025-26"). A sentence-ending
# period or comma after it is punctuation ("…בדצמבר 2026."); only a '%' or a
# period/comma followed by a digit makes it a number ("2025%", "2026.5").
_YEAR = re.compile(r"(?<![\d.,])(?:19[4-9]\d|20[0-4]\d)(?:[/–-]\d{2}(?!\d))?(?![\d%]|[.,]\d)")
YEARLIKE = re.compile(r"\D*(?:19[4-9]\d|20[0-4]\d)(?:[/–-]\d{2})?\D*")
_YEAR_LEAD = re.compile(
    # No "כ": "כ-1980" is "about 1980", a count, not a year.
    rf"(?:(?:^|[\s(\"'״])[ובלמהש]{{1,3}}[-־–]?"
    rf"|(?:{MONTHS}|שנת|שנות|שנים|מאז|עד|לפני|אחרי|לעומת|מול|בין|מתחילת|מסוף|בשנים|בשנת)\s+"
    # "שנת התקציב 2025", "בשנת הלימודים 2024-25": one word between
    r"|(?:שנת|בשנת|שנות|בשנות)\s+[א-ת\"״']+\s+"
    # the second year of a range ("2019–2025", "מרץ–2025"); a hyphen after
    # any other word is not one
    rf"|\(|(?:\d|{MONTHS})\s*[–-]\s*)$"
)
_DIGITS = re.compile(r"\d")
SCALE_FACTORS = {1e-9, 1e-6, 1e-3, 1e3, 1e6}
# A quantity spelled in words ("שמונה אחוזים", "שלושה מיליארד שקל") is a typed
# number too. Words alone ("שלוש שנים", "חודשיים") are ordinary prose.
_NUMBER_WORD = (r"(?:אחד|אחת|שתיים|שניים|שתי|שני|שלוש|שלושה|ארבע|ארבעה|חמש|חמישה|שש|שישה|שבע|"
                r"שבעה|שמונה|תשע|תשעה|עשר|עשרה|עשרים|שלושים|ארבעים|חמישים|שישים|שבעים|שמונים|"
                r"תשעים|מאה|מאתיים|מאות|אלף|אלפיים|אלפים|חצי|רבע|שליש)")
_SPELLED = re.compile(rf"(?<![א-ת])[ובלמהשכ]{{0,3}}{_NUMBER_WORD}(?:\s+(?:ו?{_NUMBER_WORD})){{0,6}}\s+"
                      r"(?:אחוז|אחוזים|נקודות\s+אחוז|נקודת\s+אחוז|נקודות|מיליון|מיליוני|מיליארד|מיליארדי|"
                      r"אלף|אלפי|שקל|שקלים|ש\"ח|₪)(?![א-ת])")
# More spelled quantities, each one precise enough not to catch ordinary prose:
# - a count of three or more (or a teen) before a noun that is not a time unit
#   ("חמש מאות דירות", "שבעים דירות", "אלפיים דירות"). אחד/שני/שתי and friends
#   alone are left out on purpose: "אחד הגורמים", "שני הצדדים", "מצד שני" are
#   prose. So are a definite next word ("שלוש הערים"; also keeps "המאה העשרים"),
#   a function word, a month ("שבעה באוקטובר" is a date), "באר שבע", a per-N
#   denominator ("לכל מאה חוזים", like "לכל 1,000 תושבים"), and the construct
#   forms (שלושת, חמשת), which mostly read as reference ("שלושת הבנקים
#   הגדולים"), not as a figure.
# - "פי <number word>" ("עלה פי שלושה"; "על פי" is "according to").
# - a fraction of something: חצי/שליש/רבע/מחצית… before a מ-word ("חצי
#   מהתושבים"; "חצי שנה" is a duration and stays), or a plural fraction after a
#   number word ("שני שלישים", "שלושה רבעים").
# - a bare magnitude: "מיליון שקלים", "כמיליארד שקל" (not after a fact token or a
#   digit: "{f1:num2} מיליארד" is the token's scale).
# Vague magnitudes with no number ("עשרות", "מאות", "אלפי תושבים", "מיליוני
# שקלים") are left alone: they say "many", not a figure (a judgment call).
_TIME_UNIT = (r"(?:שנה|שנים|שנות|שנתיים|שנתי|חודש|חודשים|חודשי|חודשיים|שבוע|שבועות|שבועיים|יום|ימים|"
              r"ימי|יומיים|יממה|יממות|שעה|שעות|שעתיים|דקה|דקות|דקתיים|רבעון|רבעונים|עשור|עשורים)")
_COUNT_WORD = (r"(?:שלושה|שלוש|ארבעה|ארבע|חמישה|חמש|שישה|שש|שבעה|שבע|שמונה|תשעה|תשע|עשרה|עשר|"
               r"עשרים|שלושים|ארבעים|חמישים|שישים|שבעים|שמונים|תשעים|מאתיים|מאה|אלפיים|אלף|"
               r"(?:אחד|אחת|שניים|שנים|שתיים|שתים|שני|שתי)\s+עשרה?)")
_FUNCTION_WORD = r"(?:של|את|עם|על|אל|או|גם|עד|כל|כי|אם|לא|זה|זו|הם|הן|היו|היה|הייתה|אחרי|לפני|מתוך)"
# ש+מונה ("who was appointed") is told from the count שמונה only by what follows:
# the verb's own followers (by, in <year>, to/as a role, recently). Anything else
# after שמונה reads as a count, so "שמונה בנקים" / "שמונה לקוחות" are flagged;
# an appointment phrased some other way fails closed (flagged; the writer rephrases).
_ROLE = (r"(?:תפקיד|מנכ|יו[\"״]ר|יועץ(?![א-ת])|ראש|סגנ|סגן|נשיא|שופט|שר(?![א-ת])|חבר(?![א-ת])|מנהל|ממונה|"
         r"דירקטור|מפכ|רמטכ|נציב|מבקר|כהונ|ועד|וועד)")
_APPOINTED = (rf"שמונה\s+(?:על(?![א-ת])|ע[\"״׳']י|ב(?:-|\d|שנת|מקומ|מקום|תפקיד)|לאחרונה"
              rf"|[לכ]{_ROLE})")
# Number-word repeats are bounded ({0,6}: no real number phrase has more parts),
# so a long run of number words in model text can't backtrack quadratically.
_COUNT = re.compile(
    rf"(?<![א-ת])(?<!באר )(?<!באר-)(?<!לכל )[ובלמכש]{{0,3}}"
    # "שבע רצון" is "satisfied"
    rf"(?!{_APPOINTED})(?!שבע\s+רצון){_COUNT_WORD}"
    rf"(?:\s+ו?[בלמכש]?{_NUMBER_WORD}(?![א-ת])){{0,6}}"
    rf"\s+(?!ה)(?![ובלמהשכ]{{0,3}}(?:{_TIME_UNIT}|{_NUMBER_WORD}|{MONTHS})(?![א-ת]))"
    rf"(?!{_FUNCTION_WORD}(?![א-ת]))[א-ת]+")
_TIMES = re.compile(rf"(?<![א-ת])(?<!על )(?<!על-)ו?פי\s+[כ]?{_NUMBER_WORD}(?![א-ת])")
_FRACTION = re.compile(
    r"(?<![א-ת])[ובלמהשכ]{0,3}(?:חצי|שליש|רבע|מחצית|חמישית|עשירית)\s+"
    r"(?!(?:מאה|מאות|מאתיים|מיליון|מיליוני|מיליארד|מיליארדי)(?![א-ת]))מ[א-ת-]+"
    rf"|(?<![א-ת])[ובלמהשכ]{{0,3}}{_NUMBER_WORD}\s+(?:שלישים|רבעים|חמישיות|עשיריות)(?![א-ת])")
_MAGNITUDE = re.compile(r"(?<![א-ת])[ובלמהשכ]{0,3}(?:מיליון|מיליארד|טריליון)(?![א-ת])")
# A _COUNT match that is "אלף" alone before a noun: in prose a figure ("אלף
# דירות"), in a label the thousand scale ("אלף טון", "אלף דונם"), like "מיליון".
_THOUSAND_SCALE = re.compile(r"[ובלמכש]{0,3}אלף\s+[א-ת]+")
_TOKEN_MARK = "\ue000"   # a fact token's place: a magnitude right after it is its scale


def spelled_numbers(text: str, *, scale_ok: bool = False) -> list[str]:
    """Quantities written out in Hebrew words instead of fact tokens.
    `scale_ok`: a bare magnitude is a scale, not a figure (a chart unit or
    title, a series name, the stat block's label: "מיליון ש\"ח", "אלף טון")."""
    t = unicodedata.normalize("NFKC", text)
    t = LINK.sub(lambda m: f" {m[1]} ", TOKEN.sub(f" {_TOKEN_MARK} ", t))
    spans = [m.span() for m in _SPELLED.finditer(t)]
    spans += [m.span() for m in _TIMES.finditer(t)] + [m.span() for m in _FRACTION.finditer(t)]
    for rx in (_COUNT,) if scale_ok else (_COUNT, _MAGNITUDE):
        for m in rx.finditer(t):
            if scale_ok and _THOUSAND_SCALE.fullmatch(m[0]):
                continue
            i = m.start() - 1   # the last character before it, past spaces and dashes
            while i >= 0 and t[i] in " \t\n-־–":
                i -= 1
            if i < 0 or not (t[i].isdigit() or t[i] == _TOKEN_MARK):
                spans.append(m.span())
    out, end = [], -1
    for a, b in sorted(spans):   # overlapping matches are one quantity
        if a >= end:
            out.append([a, b])
        else:
            out[-1][1] = max(out[-1][1], b)
        end = max(end, b)
    return [t[a:b].strip() for a, b in out]


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
        self._by_prov: dict[tuple[str, float], str] = {}
        self._by_url: dict[str, str] = {}

    def add(self, value: float, *, label: str, provenance: str, unit: str | None = None,
            period: str | None = None, dataset_id: str | None = None) -> Fact:
        """Register a value (the same provenance and value get the same id; a
        new value under a known provenance is a new fact)."""
        v = float(value)
        if not math.isfinite(v):
            raise ValueError("facts must be finite numbers")
        if (fid := self._by_prov.get((provenance, v))) is not None:
            return self.facts[fid]
        f = Fact(f"f{len(self.facts) + 1}", v, label, provenance, unit, period, dataset_id)
        self.facts[f.id] = f
        self._by_prov[(provenance, v)] = f.id
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
    excepted). Empty means the text is clean. NFKC first: "½", "²", "①" are
    digits too."""
    t = TOKEN.sub(" ", unicodedata.normalize("NFKC", text))
    t = LINK.sub(lambda m: f" {m[1]} ", t)
    t = _DATE_DMY.sub(" ", t)
    t = _DAY_OF_MONTH.sub(" ", t)
    t = _YEAR.sub(lambda m: " " if _YEAR_LEAD.search(t[max(0, m.start() - 24):m.start()]) else m[0], t)
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
