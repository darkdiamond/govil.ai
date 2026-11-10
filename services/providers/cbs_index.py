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
that older base. `download()` uses the chain to put every row of a code on the
newest base (`VALUE_CHAINED`), once, so no recipe re-derives base linking.
Some codes (seasonal fresh produce) lack coefficients for a switch; `_links`
then links it with the published PERCENT or PERCENT_YEAR, and a switch with neither leaves
VALUE_CHAINED blank for the older rows. A scale break hidden under one label
(CBS's 1985 rows) is split off and linked by PERCENT (`_segments`).

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
    normalize_csv,
)
from .cbs import CbsReleasesProvider

PAGE_SIZE = 1000  # the API's maximum
_MAX_PAGES = 200
_HEALTH_CODE = 120010  # CPI, general: always published
_BRIEF_MAX_CODES = 200
_SIG_DIGITS = 7
# A value ratio this far from the published PERCENT (either way) is a scale
# break hidden under one base label, not rounding (see `_segments`).
_SCALE_BREAK = 1.5

COLUMNS = ("CODE", "NAME_HE", "FREQ", "TIME_PERIOD", "DATE", "YEAR", "PERIOD", "VALUE",
           "BASE_DESC", "PERCENT", "PERCENT_YEAR", "VALUE_CHAINED", "CHAIN_BASE")
_FREQS = {"month": "M", "quarter": "Q"}


def _num(v, *, sig: int | None = None) -> str:
    """A number as plain decimal text (no exponent), "" for missing. Exact
    unless `sig` (significant digits) is given: CBS's published figures pass
    through as published; only computed ones are rounded."""
    if v is None or v == "":
        return ""
    x = float(v)
    if not math.isfinite(x):
        return ""
    if x == 0:
        return "0"
    if sig is not None:
        x = round(x, sig - math.floor(math.log10(abs(x))) - 1)
    s = format(Decimal(repr(x)), "f")
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


def _pct_link(old: dict, new: dict, pct) -> float | None:
    """The coeff taking `new`'s value onto `old`'s scale, from the published change
    between them, or None when a figure is missing or the link isn't positive (a
    zero value or a -100% change can't scale anything)."""
    va = (old.get("currBase") or {}).get("value")
    vb = (new.get("currBase") or {}).get("value")
    if va is None or vb is None or pct is None or not float(vb):
        return None
    c = float(va) * (1 + float(pct) / 100) / float(vb)
    return c if c > 0 else None


def _segments(data_rows: list[tuple]) -> tuple[dict[int, str], dict[str, tuple[str, float]]]:
    """Each row's effective base, and the links between a base's own segments.

    A label can hide a scale break: CBS's CPI rows for 1985 say "1980 ממוצע" but
    sit on a scale 100 times smaller than 1984's (Dec 1984 10754.8, Jan 1985
    113.2 with PERCENT 5.3). Consecutive rows on one label whose ratio is off
    from their published PERCENT by more than half split the label; its newest
    segment keeps the label (CBS's coefficients name it), older ones become
    `<label>#1`, `#2`, … linked by that PERCENT. Segments are numbered per
    frequency: a label's monthly and quarterly rows are the same base unless a
    break splits them."""
    eff: dict[int, str] = {}
    breaks: list[tuple[int, int, float]] = []  # (newer row id, older row id, coeff)
    starts: dict[tuple[str, str], list[tuple[str, list[int]]]] = defaultdict(list)
    by_freq: dict[str, list[tuple]] = defaultdict(list)
    for d in data_rows:
        by_freq[d[1]].append(d)
    for ds in by_freq.values():
        ds.sort(key=lambda d: d[0])
        per_year = 12 if ds[0][1] == "month" else 4
        seg: list[int] = []
        for i, d in enumerate(ds):
            label = (d[5].get("currBase") or {}).get("baseDesc")
            prev = ds[i - 1] if i else None
            plabel = (prev[5].get("currBase") or {}).get("baseDesc") if prev else None
            split = prev is None or label != plabel
            if not split and (d[3] * per_year + d[4]) - (prev[3] * per_year + prev[4]) == 1:
                c = _pct_link(prev[5], d[5], d[5].get("percent"))
                if c is not None and not (1 / _SCALE_BREAK < c < _SCALE_BREAK):
                    split = True
                    breaks.append((id(d[5]), id(prev[5]), c))
            if split:
                seg = []
                starts[(d[1], label or "")].append((d[0], seg))
            seg.append(id(d[5]))
    for (_, label), segs in starts.items():
        for n, (_, ids) in enumerate(sorted(segs, key=lambda s: s[0], reverse=True)):
            for rid in ids:
                eff[rid] = label if n == 0 else f"{label}#{n}"
    return eff, {eff[new]: (eff[old], c) for new, old, c in breaks}


def _links(chain_rows: list[tuple], data_rows: list[tuple]
           ) -> tuple[dict[str, tuple[str, float]], dict[int, str]]:
    """({base: (the base before it, coeff)}, {row id: base}): a value on `base`
    times coeff is on the older base. Bases are the effective ones from
    `_segments`, whose in-label links come first. Then CBS's own coefficients
    (each row's `prevBase` walks its bases back, newest first), joining a
    label's oldest segment to the older label. CBS leaves some out (seasonal fresh
    produce: a newest row with an empty `prevBase`, or a link missing from every
    row, and months missing out of season), so a missing link is then derived
    from the earliest row on the new base whose previous period (with its
    PERCENT) or same period a year earlier (with its PERCENT_YEAR) is on another
    base. Both are published rounded to 0.1, so such a link is good to ~0.1%."""
    eff, links = _segments(data_rows)
    oldest: dict[str, str] = {}
    for key in eff.values():
        label, _, n = key.partition("#")
        if int(n or 0) >= int(oldest.get(label, label).partition("#")[2] or 0):
            oldest[label] = key
    for d in sorted(chain_rows, key=lambda d: d[0], reverse=True) + sorted(
            data_rows, key=lambda d: d[0], reverse=True):
        r = d[5]
        prev = (r.get("currBase") or {}).get("baseDesc")
        for pb in r.get("prevBase") or []:
            desc, coeff = pb.get("baseDesc"), pb.get("coeff")
            if not desc or not coeff:
                raise ProviderError(f"unreadable chaining coefficient {pb!r}")
            if prev and prev != desc:
                links.setdefault(oldest.get(prev, prev), (desc, float(coeff)))
            prev = desc
    by_freq: dict[str, dict[int, dict]] = defaultdict(dict)
    for d in data_rows:
        per_year = 12 if d[1] == "month" else 4
        by_freq[d[1]][d[3] * per_year + d[4]] = d[5]

    def base(r: dict) -> str | None:
        return eff.get(id(r)) or (r.get("currBase") or {}).get("baseDesc")

    for rows in by_freq.values():
        # A coefficient that contradicts the published PERCENT at its own switch
        # by a scale factor belongs to another segment of the label (1985 again:
        # CBS's 1985 → 1980 coefficient fits 1984's scale, not 1985's rows).
        for k in sorted(rows):
            new_base, old = base(rows[k]), rows.get(k - 1)
            old_base = base(old) if old else None
            if not old_base or new_base == old_base or links.get(new_base, ("",))[0] != old_base:
                continue
            c = _pct_link(old, rows[k], rows[k].get("percent"))
            if c is not None and not (1 / _SCALE_BREAK < links[new_base][1] / c < _SCALE_BREAK):
                links[new_base] = (old_base, c)
    for freq, rows in by_freq.items():
        per_year = 12 if freq == "month" else 4
        for k in sorted(rows):
            new_base = base(rows[k])
            if not new_base or new_base in links:
                continue
            for lag, field in ((1, "percent"), (per_year, "percentYear")):
                old = rows.get(k - lag)
                old_base = base(old) if old else None
                if old_base and old_base != new_base:
                    c = _pct_link(old, rows[k], rows[k].get(field))
                    if c is not None:
                        links[new_base] = (old_base, c)
                        break
    return links, eff


def _factors(newest_base: str, links: dict[str, tuple[str, float]]) -> dict[str, float]:
    """{base: factor} for every base reachable from the newest one; a value on base B
    divided by factor[B] is on the newest base."""
    factors, b, f = {newest_base: 1.0}, newest_base, 1.0
    while b in links:
        b, coeff = links[b]
        if b in factors:
            break
        f *= coeff
        factors[b] = f
    return factors


def _series_rows(pages: list[dict], freqs: tuple[str, ...]) -> dict[int, dict]:
    """code → {"name", "rows": [(freq, row)]}, merged across pages (one code's
    history can be split between two)."""
    by_code: dict[int, dict] = defaultdict(lambda: {"name": "", "rows": []})
    for page in pages:
        for freq in freqs:
            for series in page.get(freq) or []:
                try:
                    code = int(series["code"])
                except (KeyError, TypeError, ValueError) as e:
                    raise ProviderError(f"series without a code: {e}") from e
                entry = by_code[code]
                entry["name"] = entry["name"] or (series.get("name") or "").strip()
                entry["rows"].extend((freq, r) for r in series.get("date") or [])
    return by_code


def _dated(rows: list[tuple[str, dict]]) -> list[tuple]:
    out = []
    for freq, r in rows:
        year, n = _period(freq, r)
        tp, date = _date(freq, year, n)
        out.append((date, freq, tp, year, n, r))
    return out


def _newest(dated: list[tuple]) -> dict:
    """The newest row (latest DATE; monthly before quarterly on a tie)."""
    return max(dated, key=lambda d: (d[0], d[1] == "month"))[5]


def rows_csv(payload_pages: list[dict], codes: list[int], frequency: str,
             chain_pages: list[dict] | None = None) -> bytes:
    """The API's pages for one query → the normalized table (unsorted; the
    caller's `normalize_csv` sorts). Raises when a requested code has no row.

    Each code's newest row usually carries the chain to every older base. The
    data pages may be fetched without `coef` (it multiplies the payload ~6x);
    `chain_pages` is then a `last=1&coef=true` answer for the same codes.
    Without it the chain is read from the data pages themselves. Gaps in CBS's
    coefficients are bridged by `_links`; a row on a base still unreachable
    gets a blank VALUE_CHAINED."""
    freqs = ("month", "quarter") if frequency == "both" else (frequency,)
    by_code = _series_rows(payload_pages, freqs)
    chains = _series_rows(chain_pages, freqs) if chain_pages is not None else by_code
    missing = [c for c in codes if not by_code.get(c, {}).get("rows")]
    if missing:
        raise ProviderError(f"CBS index answered no {frequency} rows for code(s) {missing}")
    out = io.StringIO(newline="")
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLUMNS)
    for code in codes:
        entry = by_code[code]
        dated = _dated(entry["rows"])
        chain_rows = chains.get(code, {}).get("rows")
        if not chain_rows:
            raise ProviderError(f"code {code}: no row with chaining coefficients")
        chain_dated = _dated(chain_rows)
        chain_base = (_newest(chain_dated).get("currBase") or {}).get("baseDesc")
        if not chain_base:
            raise ProviderError(f"code {code}: newest row has no currBase")
        links, eff = _links(chain_dated, dated)
        factors = _factors(chain_base, links)
        seen = set()
        for date, freq, tp, year, n, r in dated:
            if (freq, tp) in seen:
                raise ProviderError(f"code {code}: duplicate {freq} row {tp}")
            seen.add((freq, tp))
            base = (r.get("currBase") or {})
            desc, value = base.get("baseDesc"), base.get("value")
            # A base CBS gives no link to (no coefficient, no consecutive switch
            # with a PERCENT) leaves VALUE_CHAINED blank for its rows and older.
            key = eff.get(id(r), desc)
            chained = (float(value) / factors[key]
                       if value is not None and key in factors else None)
            w.writerow([code, entry["name"], _FREQS[freq], tp, date, year, n, _num(value),
                        desc or "", _num(r.get("percent")), _num(r.get("percentYear")),
                        _num(chained, sig=_SIG_DIGITS), chain_base])
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

    def _query(self, r: CbsIndexResource) -> dict:
        q = {"id": ",".join(str(c) for c in r.codes), "lang": "he"}
        if r.start:
            q["startPeriod"] = r.start
        return q

    def download_url(self, r: CbsIndexResource) -> str:
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

    def _cached(self, resource: dict) -> tuple[bytes, int]:
        # Two resources can share a URL (same codes and start) and differ in
        # `frequency`, which the CSV export URL doesn't carry.
        freq = (resource.get("params") or {}).get("frequency") or "both"
        key = f"{resource['url']}#frequency={freq}"
        if key not in self._cache:
            self._cache[key] = normalize_csv(self.download(resource), self.sort_keys,
                                             count=True)
        return self._cache[key]

    def pages(self, r: CbsIndexResource) -> list[dict]:
        """The resource's rows, every page, without chaining coefficients."""
        out, page, total, got = [], 1, None, 0
        while True:
            data = self._get_json(self._url("data/price", **self._query(r), format="json",
                                            PageSize=PAGE_SIZE, Page=page))
            paging = data.get("paging")
            if not isinstance(paging, dict):
                raise ProviderError(f"{r.id}: CBS Index API error: {str(data)[:200]}")
            out.append(data)
            n = sum(len(s.get("date") or []) for f in ("month", "quarter")
                    for s in data.get(f) or [] if isinstance(s, dict))
            got += n
            last = paging.get("last_page")
            last = last if isinstance(last, int) and not isinstance(last, bool) else None
            if page == 1:
                t = paging.get("total_items")
                total = t if isinstance(t, int) and not isinstance(t, bool) else None
                if last is None and total is None and n > 1:
                    raise ProviderError(f"{r.id}: CBS Index API answered {n} rows with no "
                                        f"usable paging: {str(paging)[:200]}")
            if last is None or page >= last:
                # A walk cut short (a missing last_page, a row withdrawn
                # between pages) would publish a truncated history.
                if total is not None and got < total:
                    raise ProviderError(f"{r.id}: CBS Index API returned {got} of {total} rows")
                return out
            page += 1
            if page > _MAX_PAGES:
                raise ProviderError(f"{r.id}: more than {_MAX_PAGES} pages")

    def chain_pages(self, r: CbsIndexResource) -> list[dict]:
        """Each code's newest row per frequency, with its chaining coefficients."""
        data = self._get_json(self._url("data/price", id=",".join(map(str, r.codes)),
                                        format="json", lang="he", coef="true", last=1,
                                        PageSize=PAGE_SIZE))
        if "paging" not in data:
            raise ProviderError(f"{r.id}: CBS Index API error: {str(data)[:200]}")
        return [data]

    def download(self, resource: dict) -> bytes:
        r = self._resource(resource)
        try:
            return rows_csv(self.pages(r), r.codes, r.frequency, self.chain_pages(r))
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
            # Only a well-formed answer counts: an error body (no paging) or
            # an inconsistent one says nothing about the codes.
            paging = data.get("paging")
            total = paging.get("total_items") if isinstance(paging, dict) else None
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                return "unknown"
            if total == 0 and (data.get("month") or data.get("quarter")):
                return "unknown"
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
                                         "last": None, "last_row": None, "first_tp": "",
                                         "bases": set(), "unchained": 0,
                                         "chain": row["CHAIN_BASE"]})
                s["n"] += 1
                s["bases"].add(row["BASE_DESC"])
                s["unchained"] += row["VALUE"] != "" and row["VALUE_CHAINED"] == ""
                if s["first"] is None or row["DATE"] < s["first"]:
                    s["first"], s["first_tp"] = row["DATE"], row["TIME_PERIOD"]
                if s["last"] is None or row["DATE"] >= s["last"]:
                    s["last"], s["last_row"] = row["DATE"], row
        r = self._resource(resource)
        out = io.StringIO()
        out.write(f"- CBS Index API codes {', '.join(map(str, r.codes))} "
                  f"(frequency `{r.frequency}`, start `{r.start or 'full history'}`)\n\n")
        out.write("| CODE | NAME_HE | FREQ | rows | first | last | last VALUE (base) | "
                  "last PERCENT / PERCENT_YEAR | bases | CHAIN_BASE | unchained |\n")
        out.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
        for i, ((code, freq), s) in enumerate(sorted(stats.items())):
            if i >= _BRIEF_MAX_CODES:
                out.write(f"\n… {len(stats) - _BRIEF_MAX_CODES} more not listed\n")
                break
            lr = s["last_row"]
            out.write(f"| {code} | {s['name']} | {freq} | {s['n']:,} | {s['first_tp']} | "
                      f"{lr['TIME_PERIOD']} | {lr['VALUE']} ({lr['BASE_DESC']}) | "
                      f"{lr['PERCENT']} / {lr['PERCENT_YEAR']} | {len(s['bases'])} | "
                      f"{s['chain']} | {s['unchained']} |\n")
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
            "- Where CBS publishes no coefficient for a base switch (seasonal produce), the\n"
            "  link uses the published PERCENT or PERCENT_YEAR at the switch (~0.1%\n"
            "  precision). Where neither\n"
            "  exists, VALUE_CHAINED is BLANK for the rows before the break: the brief's\n"
            "  `unchained` column counts them. Chart only the chained span (drop blanks), and\n"
            "  never splice VALUE onto it.\n"
            "- CBS's 1985 rows (CPI, housing) are labelled \"1980 ממוצע\" but sit on a scale\n"
            "  100x smaller; the provider detects such breaks against PERCENT and chains them\n"
            "  correctly, so VALUE_CHAINED needs no repair in compute.\n"
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


__all__ = ["CbsIndexDatasetConfig", "CbsIndexProvider", "rows_csv"]
