"""Central Bureau of Statistics (הלמ"ס): price indices from the Index API (no key).

    {base}/data/price?id=<code>[,<code>…]&format=json&lang=he&coef=true
                     [&startPeriod=MM-YYYY]&PageSize=1000&Page=<n>

returns `{"month": [...], "quarter": [...], "paging": {...}}`, each list one
object per code: `{code, name, date: [{year, month|quarter, percent,
percentYear, currBase: {baseDesc, value}, prevBase: [...]}, …]}`, newest
first. No period parameters means the code's whole history (CPI: 1951→).
PageSize tops out at 1000 rows (more answers `{"Message": "Error: Price
Data"}`), and one code's history can be split across pages. An unknown code
answers 200 with `month: null, quarter: null, total_items: 0`.

**Bases.** CBS rebases an index every ~2 years. Each row's `value` is on the
base in force when it was published (CPI since 1990 spans 15 bases), so raw
values from different bases can't be compared. With `coef=true` each row also
carries `prevBase`: the official chaining coefficients, newest to oldest,
`{coeff, baseDesc, value}`, where `value` is the row's value carried back to
that older base. `download()` uses the newest row's chain to put every row of
a code on the newest base (`VALUE_CHAINED`), once, so no recipe re-derives
base linking.

The catalog (`catalog/catalog` → chapters, `catalog/chapter?id=` → subjects,
`catalog/subject?id=` → codes) is walked by the `catalog` CLI below.

Reuse is under CBS's open license (רישיון פתוח למידע, v2.1), the same as the
`cbs_releases` provider; the credit block is shared with it.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .base import (
    Availability,
    ProviderError,
    ProviderFacts,
    ProviderResource,
    ProviderSettings,
    SourceConfig,
    SourcePresentation,
    SourceProvider,
)
from .cbs import CbsReleasesProvider

PAGE_SIZE = 1000  # the API's maximum
_MAX_PAGES = 200
_HEALTH_CODE = 120010  # CPI, general: always published
_BRIEF_MAX_CODES = 200
_SIG_DIGITS = 7

COLUMNS = ("CODE", "NAME_HE", "FREQ", "TIME_PERIOD", "DATE", "YEAR", "PERIOD", "VALUE",
           "BASE_DESC", "PERCENT", "PERCENT_YEAR", "VALUE_CHAINED", "CHAIN_BASE")
_FREQS = {"month": ("M", "month"), "quarter": ("Q", "quarter")}


def _num(v) -> str:
    """A float as plain decimal text (no exponent), "" for missing."""
    if v is None or v == "":
        return ""
    x = float(v)
    if not math.isfinite(x):
        return ""
    if x == 0:
        return "0"
    digits = _SIG_DIGITS - math.floor(math.log10(abs(x))) - 1
    s = format(Decimal(repr(round(x, digits))), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


class CbsIndexResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    codes: list[int] = Field(min_length=1, max_length=60)
    # MM-YYYY; omitted = the whole history.
    start: str | None = Field(None, pattern=r"^(0[1-9]|1[0-2])-\d{4}$")
    frequency: Literal["month", "quarter", "both"] = "both"

    @field_validator("codes")
    @classmethod
    def _unique_codes(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("codes must be unique")
        if any(c <= 0 for c in v):
            raise ValueError("codes must be positive")
        return v


class CbsIndexDatasetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resources: list[CbsIndexResource] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [r.id for r in self.resources]
        if len(ids) != len(set(ids)):
            raise ValueError("resource ids must be unique")
        return self


def _period(freq: str, row: dict) -> tuple[int, int]:
    year = int(row["year"])
    n = int(row["month"] if freq == "month" else row["quarter"])
    if not (1 <= n <= (12 if freq == "month" else 4)):
        raise ProviderError(f"bad {freq} number {n!r} in {year}")
    return year, n


def _date(freq: str, year: int, n: int) -> tuple[str, str]:
    """(TIME_PERIOD, DATE): `2026-09` / `2026-09-01`, or `1993-Q4` / `1993-10-01`."""
    if freq == "month":
        return f"{year}-{n:02d}", f"{year}-{n:02d}-01"
    return f"{year}-Q{n}", f"{year}-{3 * n - 2:02d}-01"


def chain_factors(newest: dict) -> tuple[str, dict[str, float]]:
    """From a code's newest row: (its base, {base: factor}). A value on base B
    divided by factor[B] is on the newest base. `prevBase` lists the older
    bases newest first, each `coeff` linking it to the one before."""
    curr = (newest.get("currBase") or {}).get("baseDesc")
    if not curr:
        raise ProviderError("newest row has no currBase")
    factors = {curr: 1.0}
    f = 1.0
    for p in newest.get("prevBase") or []:
        desc, coeff = p.get("baseDesc"), p.get("coeff")
        if not desc or not coeff:
            raise ProviderError(f"unreadable chaining coefficient {p!r}")
        f *= float(coeff)
        factors.setdefault(desc, f)
    return curr, factors


def rows_csv(payload_pages: list[dict], codes: list[int], frequency: str) -> bytes:
    """The API's pages for one query → the normalized table (unsorted; the
    caller's `normalize_csv` sorts). Raises when a requested code has no row."""
    # (code) → {"name", "rows": [(freq, row)]}; a code may span pages.
    by_code: dict[int, dict] = defaultdict(lambda: {"name": "", "rows": []})
    freqs = ("month", "quarter") if frequency == "both" else (frequency,)
    for page in payload_pages:
        for freq in freqs:
            for series in page.get(freq) or []:
                try:
                    code = int(series["code"])
                except (KeyError, TypeError, ValueError) as e:
                    raise ProviderError(f"series without a code: {e}") from e
                entry = by_code[code]
                entry["name"] = entry["name"] or (series.get("name") or "").strip()
                entry["rows"].extend((freq, r) for r in series.get("date") or [])
    missing = [c for c in codes if not by_code.get(c, {}).get("rows")]
    if missing:
        raise ProviderError(f"CBS index answered no {frequency} rows for code(s) {missing}")
    out = io.StringIO(newline="")
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLUMNS)
    for code in codes:
        entry = by_code[code]
        dated = []
        for freq, r in entry["rows"]:
            year, n = _period(freq, r)
            tp, date = _date(freq, year, n)
            dated.append((date, freq, tp, year, n, r))
        # The newest row (latest DATE; monthly before quarterly on a tie)
        # carries the chain to every older base.
        newest = max(dated, key=lambda d: (d[0], d[1] == "month"))[5]
        chain_base, factors = chain_factors(newest)
        seen = set()
        for date, freq, tp, year, n, r in dated:
            if (freq, tp) in seen:
                raise ProviderError(f"code {code}: duplicate {freq} row {tp}")
            seen.add((freq, tp))
            base = (r.get("currBase") or {})
            desc, value = base.get("baseDesc"), base.get("value")
            if value is None:
                chained = None
            elif desc in factors:
                chained = float(value) / factors[desc]
            else:
                raise ProviderError(
                    f"code {code} {tp}: base {desc!r} is not in the chain from {chain_base!r}"
                )
            w.writerow([code, entry["name"], _FREQS[freq][0], tp, date, year, n, _num(value),
                        desc or "", _num(r.get("percent")), _num(r.get("percentYear")),
                        _num(chained), chain_base])
    return out.getvalue().encode("utf-8")


class CbsIndexProvider(SourceProvider):
    key = "cbs_index"
    id_prefix = "cbs-index-"
    label = "הלשכה המרכזית לסטטיסטיקה (מדדי מחירים)"
    DatasetConfig = CbsIndexDatasetConfig
    default_settings = ProviderSettings(
        base_url="https://api.cbs.gov.il/index",
        timeout_s=60.0,
        retries=2,
        min_interval_s=0.5,
        max_bytes=50_000_000,
    )
    sort_keys = ("CODE", "FREQ", "DATE")

    ORGANIZATION: ClassVar[dict[str, str | None]] = CbsReleasesProvider.ORGANIZATION
    LICENSE_TITLE = CbsReleasesProvider.LICENSE_TITLE
    HOME_URL = CbsReleasesProvider.HOME_URL
    TERMS_URL = CbsReleasesProvider.TERMS_URL

    def _url(self, path: str, **query) -> str:
        return f"{self.settings.base_url.rstrip('/')}/{path}?{urlencode(query, safe=',')}"

    def _query(self, r: CbsIndexResource | dict) -> dict:
        r = r if isinstance(r, CbsIndexResource) else CbsIndexResource.model_validate(r)
        q = {"id": ",".join(str(c) for c in r.codes), "lang": "he"}
        if r.start:
            q["startPeriod"] = r.start
        return q

    def download_url(self, r: CbsIndexResource | dict) -> str:
        """CBS's own CSV export of the resource's codes (the page's download
        button; cp1255, one page of up to 1000 rows)."""
        return self._url("data/price", **self._query(r), format="csv", PageSize=PAGE_SIZE)

    def _get_json(self, url: str) -> dict:
        r = self.http_get(url)
        if r.status_code != 200:
            raise ProviderError(f"HTTP {r.status_code} from the CBS Index API for {url[:160]}")
        try:
            data = r.json()
        except ValueError as e:
            raise ProviderError(f"CBS Index API answered non-JSON for {url[:160]}: {e}") from e
        if not isinstance(data, dict):
            raise ProviderError(f"CBS Index API answered {type(data).__name__} for {url[:160]}")
        return data

    # ── facts ────────────────────────────────────────────────────────────

    def facts(self, dataset_id: str, source: SourceConfig,
              cfg: CbsIndexDatasetConfig) -> ProviderFacts:
        return ProviderFacts(
            title=source.title,
            notes=source.notes,
            organization=dict(self.ORGANIZATION),
            license_title=self.LICENSE_TITLE,
            tags=source.tags,
            update_frequency=source.update_frequency,
            source_url=source.source_url or self.HOME_URL,
            resources=[
                ProviderResource(id=r.id, name=r.name, format="CSV", url=self.download_url(r),
                                 params=r.model_dump(exclude={"id", "name"}))
                for r in cfg.resources
            ],
        )

    def presentation(self) -> SourcePresentation:
        return SourcePresentation(
            source_name_he="הלשכה המרכזית לסטטיסטיקה",
            home_url=self.HOME_URL,
            terms_url=self.TERMS_URL,
            attribution_he="מקור הנתונים: הלשכה המרכזית לסטטיסטיקה, מאגר המדדים.",
            download_label_he="הורדת CSV מהלמ\"ס",
            explorer=False,
        )

    # ── data ─────────────────────────────────────────────────────────────

    def _resource(self, resource: dict) -> CbsIndexResource:
        return CbsIndexResource.model_validate(
            {"id": resource["id"], "name": resource.get("name") or resource["id"],
             **(resource.get("params") or {})})

    def pages(self, r: CbsIndexResource) -> list[dict]:
        out, page = [], 1
        while True:
            data = self._get_json(self._url("data/price", **self._query(r), format="json",
                                            coef="true", PageSize=PAGE_SIZE, Page=page))
            if "paging" not in data:
                raise ProviderError(f"{r.id}: CBS Index API error: {str(data)[:200]}")
            out.append(data)
            last = int((data.get("paging") or {}).get("last_page") or 0)
            if page >= last:
                return out
            page += 1
            if page > _MAX_PAGES:
                raise ProviderError(f"{r.id}: more than {_MAX_PAGES} pages")

    def download(self, resource: dict) -> bytes:
        r = self._resource(resource)
        try:
            return rows_csv(self.pages(r), r.codes, r.frequency)
        except ProviderError as e:
            raise ProviderError(f"{r.id}: {e}") from e

    # ── liveness ─────────────────────────────────────────────────────────

    def _latest(self, codes: str) -> dict:
        return self._get_json(self._url("data/price", id=codes, format="json", lang="he",
                                        last=1))

    def healthcheck(self) -> bool:
        data = self._latest(str(_HEALTH_CODE))
        return bool(data.get("month"))

    def probe_available(self, resources: list[dict]) -> Availability:
        # Definite only while the API itself answers (an outage looks the
        # same for every code).
        if not resources or not self.healthy():
            return "unknown"
        found = []
        for res in resources:
            try:
                r = self._resource(res)
                data = self._latest(",".join(str(c) for c in r.codes))
            except (ProviderError, ValueError):
                return "unknown"
            total = int((data.get("paging") or {}).get("total_items") or 0)
            found.append(total > 0)
        if all(found):
            return "alive"
        # Gone only when no code of any resource answers: one retired code
        # fails the refresh and asks for a human instead.
        if not any(found):
            return "gone"
        return "unknown"

    # ── authoring ────────────────────────────────────────────────────────

    def brief_section(self, resource: dict, csv_path: Path) -> str:
        stats: dict[tuple[str, str], dict] = {}
        with open(csv_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                k = (row["CODE"], row["FREQ"])
                s = stats.setdefault(k, {"name": row["NAME_HE"], "n": 0, "first": None,
                                         "last": None, "last_row": None, "bases": set(),
                                         "chain": row["CHAIN_BASE"]})
                s["n"] += 1
                s["bases"].add(row["BASE_DESC"])
                if s["first"] is None or row["DATE"] < s["first"]:
                    s["first"] = row["DATE"]
                if s["last"] is None or row["DATE"] >= s["last"]:
                    s["last"], s["last_row"] = row["DATE"], row
        r = self._resource(resource)
        out = io.StringIO()
        out.write(f"- CBS Index API codes {', '.join(map(str, r.codes))} "
                  f"(frequency `{r.frequency}`, start `{r.start or 'full history'}`)\n\n")
        out.write("| CODE | NAME_HE | FREQ | rows | first | last | last VALUE (base) | "
                  "last PERCENT / PERCENT_YEAR | bases | CHAIN_BASE |\n")
        out.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for i, ((code, freq), s) in enumerate(sorted(stats.items())):
            if i >= _BRIEF_MAX_CODES:
                out.write(f"\n… {len(stats) - _BRIEF_MAX_CODES} more not listed\n")
                break
            lr = s["last_row"]
            out.write(f"| {code} | {s['name']} | {freq} | {s['n']:,} | {s['first'][:7]} | "
                      f"{s['last'][:7]} | {lr['VALUE']} ({lr['BASE_DESC']}) | "
                      f"{lr['PERCENT']} / {lr['PERCENT_YEAR']} | {len(s['bases'])} | "
                      f"{s['chain']} |\n")
        return out.getvalue()

    def authoring_notes(self) -> str:
        return (
            "- Rows are observations: one row per (CODE, FREQ, TIME_PERIOD). FREQ is M or Q;\n"
            "  TIME_PERIOD is `YYYY-MM` or `YYYY-Qn`, DATE the period's first day. Numbers are\n"
            "  strings: parse with float() and skip blanks.\n"
            "- **VALUE is on the base in force at the time (BASE_DESC), which changes every ~2\n"
            "  years.** Never compare or chart VALUE across bases. VALUE_CHAINED puts every\n"
            "  row of a code on its newest base (CHAIN_BASE) with CBS's official chaining\n"
            "  coefficients: use it for charts, long-run changes and \"index level\" figures,\n"
            "  and name CHAIN_BASE as the base (e.g. \"בסיס: ממוצע 2024 = 100\").\n"
            "- PERCENT (vs the previous period) and PERCENT_YEAR (vs the same period a year\n"
            "  earlier) are CBS's published changes, rounded to 0.1. Quote them as published;\n"
            "  a change recomputed from VALUE_CHAINED can differ by 0.1.\n"
            "- A code can have both M and Q rows in different eras (housing prices: quarterly\n"
            "  to 1993, monthly after). Pick FREQ explicitly.\n"
            "- Don't assume an index starts at 100. Some are linked to a parent index at\n"
            "  their start (the housing district and new-dwelling indices begin in Oct 2017\n"
            "  at the national index's level, 414.5, under the label \"2017 אוקטובר\"). Read\n"
            "  the levels in the brief, and prefer PERCENT_YEAR or ratios over levels.\n"
            "- The API answers HTTP 500 for some codes when the range reaches before the\n"
            "  code's real start (new dwellings, 70000, before 12-2018). Put such a code in\n"
            "  its own resource with a `start`, rather than shortening every series.\n"
            "- Publication: CPI and most indices come out on the 15th (or the working day\n"
            "  before) for the previous month; housing prices lag about two months. Say which\n"
            "  period the latest figure covers (the latest TIME_PERIOD), not the run date.\n"
            "- Pick series by CODE. NAME_HE is CBS's own label; short display labels may\n"
            "  live in compute.py, but an unknown code must still render (fall back to\n"
            "  NAME_HE).\n"
            "- The page shell has NO live data explorer for this source: every chart needs its\n"
            "  own <details><table>. No GovExplorer / GovMap. ECharts only.\n"
            "- Credit the source in the intro text as \"הלשכה המרכזית לסטטיסטיקה\". The shell adds\n"
            "  the download link and attribution; do not link to data.gov.il."
        )

    # ── catalog (authoring) ──────────────────────────────────────────────

    def catalog(self, chapter: str | None = None) -> list[dict]:
        """Chapters → subjects → codes, for choosing a page's codes."""
        chapters = self._get_json(self._url("catalog/catalog", format="json", lang="he"))
        out, done = [], set()
        for ch in chapters.get("chapters") or []:
            cid = ch.get("chapterId")
            if not cid or cid in done or (chapter and cid != chapter):
                continue
            done.add(cid)
            subj = self._get_json(self._url("catalog/chapter", id=cid, format="json", lang="he"))
            subjects = []
            for s in subj.get("subject") or []:
                codes = self._get_json(self._url("catalog/subject", id=s["subjectId"],
                                                 format="json", lang="he"))
                subjects.append({
                    "id": s["subjectId"], "name": s.get("subjectName") or "",
                    "codes": [{"code": c.get("codeId"), "name": (c.get("codeName") or "").strip(),
                               "level": c.get("codeLevel"), "monthly": c.get("isMonth"),
                               "from": c.get("codeFromDate")}
                              for c in codes.get("code") or []],
                })
            out.append({"id": cid, "name": ch.get("chapterName") or "",
                        "main_code": ch.get("mainCode"), "subjects": subjects})
        return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m services.providers.cbs_index")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog", help="CBS index chapters → subjects → codes")
    c.add_argument("--chapter", help="one chapter id (a, aa, b, …)")
    c.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    provider = CbsIndexProvider.from_env()
    rows = provider.catalog(args.chapter)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for ch in rows:
        print(f"[{ch['id']}] {ch['name']}  (main code {ch['main_code']})")
        for s in ch["subjects"]:
            print(f"  subject {s['id']}: {s['name']}  ({len(s['codes'])} codes)")
            for code in s["codes"]:
                indent = "    " + "  " * max(0, ((code["level"] or 1) - 1) // 2)
                print(f"{indent}{code['code']}  {code['name']}"
                      + ("" if code["monthly"] else "  [quarterly]"))
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["CbsIndexDatasetConfig", "CbsIndexProvider", "chain_factors", "rows_csv"]
