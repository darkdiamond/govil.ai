"""Central Bureau of Statistics (הלמ"ס): recurring press releases (no key).

CBS publishes ~380 press releases a year. Many are recurring reports
(monthly visitor arrivals, average wage, labour force survey, …), each
edition with the same numbered tables as Excel files. One page here follows
one recurring report and re-renders when CBS publishes the next edition.

The release list is the media-release site's SharePoint list (open REST):

    {base}/_api/web/lists/getbytitle('דפים')/items?$top=…&$orderby=Created desc

One query per run serves every CBS page. A release's files live in
`{base}/DocLib/<year>/<no>/`, named `<chapter>_<yy>_<no>t<N>.xlsx|xls|pdf`
(`b.pdf` is the written report). The same report flips between `.xls`
(BIFF, cp1255) and `.xlsx` from one edition to the next, so tables are
matched by stem (`t1`) and read with python-calamine, which reads both
formats through one API.

Tables are laid out for print (titles, multi-row bilingual headers,
footnotes), so `download()` emits a lossless *grid*: one CSV row per
non-empty sheet row, `RELEASE_NO, RELEASE_DATE, SHEET_NO, SHEET, ROW,
C01..Cnn`. Each recipe's compute.py finds its rows and columns by label.

Reuse is under CBS's open license (רישיון פתוח למידע, v2.1, 2016):
commercial use and derivative works allowed, with credit to CBS.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import io
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .base import (
    ProviderDatasetConfig,
    ProviderError,
    ProviderFacts,
    ProviderResource,
    ProviderSettings,
    ProviderTooLarge,
    SourceConfig,
    SourcePresentation,
    SourceProvider,
)

SITE = "https://www.cbs.gov.il"
LIST_TITLE = "דפים"
# ~1500 items reach ~3 years back (to 2022-11, measured 2026-11: 2.3 s,
# 0.95 MB per run): 2–3 editions of a yearly report, a monthly report's full
# history. Still one list query per run for every CBS page.
LIST_WINDOW = 1500
_LIST_FIELDS = ("Title,CbsPubNumber,CbsDataPublishDate,Created,CbsPublishingFolderLevel1,"
                "CbsPublishingFolderLevel2,CbsMMDInterval,CbsMMDSubjects,cbsBodyText,FileRef")
_JSON = {"Accept": "application/json;odata=nometadata"}
IL_TZ = ZoneInfo("Asia/Jerusalem")

GRID_KEYS = ("RELEASE_NO", "RELEASE_DATE", "SHEET_NO", "SHEET", "ROW")
RELEASE_COLUMNS = ("RELEASE_NO", "RELEASE_DATE", "TITLE", "HEADLINE", "PAGE_URL",
                   "REPORT_PDF_URL")
_ROW_WIDTH = 5  # ROW "00042": string order == row order
_TABLE_EXTS = (".xlsx", ".xls")  # preference order
_BRIEF_ROWS = 60
_BRIEF_CELL = 60
# A release younger than this may still be gaining files (`listing_key`).
_SETTLE_DAYS = 3


def _code_hash() -> str:
    """This module, base.py and the workbook reader's version: a parser
    change must not hide behind an unchanged `listing_key`."""
    try:
        from importlib.metadata import version
        calamine = version("python-calamine")
    except Exception:  # noqa: BLE001
        calamine = "?"
    h = hashlib.sha256(calamine.encode())
    for f in (Path(__file__), Path(__file__).with_name("base.py")):
        h.update(f.read_bytes())
    return h.hexdigest()


_CODE_HASH = _code_hash()


# ── config ───────────────────────────────────────────────────────────────


class CbsReport(BaseModel):
    """Which releases belong to the page."""

    model_config = ConfigDict(extra="forbid")

    # Matched against the release title with re.search. Anchor it (`^…`) and
    # exclude special editions with a lookahead, e.g. `^כניסות של מבקרים
    # לישראל ב(?!שנת)` (the yearly summary is also labelled monthly).
    title_regex: str = Field(min_length=1)
    # File prefix (`28` in `28_26_345t1.xlsx`): a release whose folder has no
    # file with it doesn't match.
    chapter: str | None = Field(None, pattern=r"^\d{1,3}$")
    # CbsMMDInterval label: חודשי / רבעוני / שנתי / …
    interval: str | None = None

    @field_validator("title_regex")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"title_regex does not compile: {e}") from e
        return v


class CbsResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    kind: Literal["table", "releases"] = "table"
    # `t3`, or a lettered sub-table such as `t3a` (CBS's 3א).
    table: str | None = Field(None, pattern=r"^t\d{1,3}[a-z]?$")
    # A table some editions lack (a chart sheet that comes and goes): an
    # edition without it adds no rows, instead of failing the page's sync.
    # When no edition has it, the resource is an empty grid (header only)
    # and compute must cope with an empty frame.
    optional: bool = False
    # releases: how many recent editions to list.
    limit: int = Field(12, ge=1, le=60)

    @model_validator(mode="after")
    def _table_needs_stem(self):
        if self.kind == "table" and not self.table:
            raise ValueError(f"{self.id}: a table resource needs `table` (e.g. \"t1\")")
        if self.kind == "releases" and self.table:
            raise ValueError(f"{self.id}: a releases resource takes no `table`")
        if self.kind == "releases" and self.optional:
            raise ValueError(f"{self.id}: only a table resource can be `optional`")
        return self


class CbsDatasetConfig(ProviderDatasetConfig):
    report: CbsReport
    # Editions stacked into each table resource, newest first. More than 1
    # only for reports whose tables show just the current period.
    history_releases: int = Field(1, ge=1, le=24)
    resources: list[CbsResource] = Field(min_length=1)


# ── releases ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Release:
    pub_no: str  # "345/2026"
    year: str  # folder level 1
    number: str  # folder level 2 ("345", "069")
    published: dt.datetime  # UTC
    title: str
    headline: str
    interval: tuple[str, ...]
    file_ref: str

    @property
    def date(self) -> str:
        """Israel-local publication date."""
        return self.published.astimezone(IL_TZ).date().isoformat()

    @property
    def folder(self) -> str:
        return f"/he/mediarelease/DocLib/{self.year}/{self.number}"

    @property
    def page_url(self) -> str:
        return SITE + quote(self.file_ref)


def _parse_time(v: str | None) -> dt.datetime | None:
    if not v:
        return None
    try:
        return dt.datetime.fromisoformat(v).astimezone(dt.UTC)
    except ValueError:
        return None


def _strip_html(v: str | None) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", v or ""))
    return re.sub(r"\s+", " ", text).strip()


def _release(item: dict) -> Release | None:
    """A list item as a Release; None for one without a title or folder."""
    title = (item.get("Title") or "").strip()
    year = str(item.get("CbsPublishingFolderLevel1") or "").strip()
    number = str(item.get("CbsPublishingFolderLevel2") or "").strip()
    when = _parse_time(item.get("CbsDataPublishDate")) or _parse_time(item.get("Created"))
    if not (title and year and number and when):
        return None
    if not (re.fullmatch(r"\d{4}", year) and re.fullmatch(r"\d{1,5}", number)):
        return None
    return Release(
        pub_no=(item.get("CbsPubNumber") or f"{number}/{year}").strip(),
        year=year, number=number, published=when,
        title=re.sub(r"\s+", " ", title),
        headline=_strip_html(item.get("cbsBodyText")),
        interval=tuple(i.get("Label", "") for i in item.get("CbsMMDInterval") or []
                       if isinstance(i, dict)),
        file_ref=item.get("FileRef") or "",
    )


# ── cells → grid ─────────────────────────────────────────────────────────


def cell_text(v) -> str:
    """One cell as text, the same for a value read from .xls or .xlsx."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            return ""
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time() else v.isoformat()
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return cell_text(v.total_seconds())
    return re.sub(r"\s+", " ", str(v)).strip()


def workbook_grid(data: bytes) -> list[tuple[int, str, list[tuple[int, list[str]]]]]:
    """`[(sheet_no, sheet_name, [(row_no, cells), …]), …]` for every sheet,
    skipping empty rows, trailing empty cells trimmed. Rows are 1-based."""
    try:
        from python_calamine import CalamineWorkbook
    except ImportError as e:  # pragma: no cover - the image installs it
        raise ProviderError("python-calamine is not installed") from e
    try:
        wb = CalamineWorkbook.from_filelike(io.BytesIO(data))
        sheets = []
        for i, name in enumerate(wb.sheet_names, 1):
            rows = []
            for r, raw in enumerate(wb.get_sheet_by_name(name).to_python(skip_empty_area=False), 1):
                cells = [cell_text(c) for c in raw]
                while cells and cells[-1] == "":
                    cells.pop()
                if cells:
                    rows.append((r, cells))
            sheets.append((i, cell_text(name), rows))
        return sheets
    except ProviderError:
        raise
    except Exception as e:  # calamine raises its own error types
        raise ProviderError(f"unreadable workbook: {type(e).__name__}: {e}") from e


def grid_csv(parts: list[tuple[Release, bytes]]) -> bytes:
    """Workbooks (one per release) as one grid CSV, columns padded to the
    widest row across all of them."""
    rows: list[list[str]] = []
    for rel, data in parts:
        for sheet_no, sheet, sheet_rows in workbook_grid(data):
            for r, cells in sheet_rows:
                if r >= 10 ** _ROW_WIDTH:
                    raise ProviderError(f"{rel.pub_no}: sheet {sheet!r} has over "
                                        f"{10 ** _ROW_WIDTH - 1:,} rows")
                rows.append([rel.pub_no, rel.date, f"{sheet_no:02d}", sheet,
                             f"{r:0{_ROW_WIDTH}d}", *cells])
    width = max((len(r) - len(GRID_KEYS) for r in rows), default=0)
    width = max(width, 1)
    out = io.StringIO(newline="")
    w = csv.writer(out, lineterminator="\n")
    w.writerow([*GRID_KEYS, *(f"C{i:02d}" for i in range(1, width + 1))])
    for r in rows:
        w.writerow(r + [""] * (len(GRID_KEYS) + width - len(r)))
    return out.getvalue().encode("utf-8")


# ── provider ─────────────────────────────────────────────────────────────


class CbsReleasesProvider(SourceProvider):
    key = "cbs_releases"
    id_prefix = "cbs-"
    label = "הלשכה המרכזית לסטטיסטיקה (הודעות לתקשורת)"
    DatasetConfig = CbsDatasetConfig
    default_settings = ProviderSettings(
        base_url=f"{SITE}/he/mediarelease",
        timeout_s=60.0,
        retries=2,
        min_interval_s=0.5,
        max_bytes=50_000_000,
    )
    sort_keys = ("RELEASE_DATE", "SHEET_NO", "ROW")

    ORGANIZATION: ClassVar[dict[str, str | None]] = {
        "id": "cbs",
        "name": "cbs",
        "title": "הלשכה המרכזית לסטטיסטיקה",
        "logo_url": None,
    }
    LICENSE_TITLE = "הלמ\"ס: רישיון פתוח למידע (גרסה 2.1)"
    HOME_URL = f"{SITE}/"
    TERMS_URL = f"{SITE}/he/Pages/%D7%A8%D7%99%D7%A9%D7%99%D7%95%D7%9F-%D7%A9%D7%99%D7%9E%D7%95%D7%A9.aspx"
    RELEASES_URL = f"{SITE}/he/mediarelease/Pages/default.aspx"

    def __init__(self, settings: ProviderSettings):
        super().__init__(settings)
        self._releases: list[Release] | None = None
        self._folders: dict[str, list[dict]] = {}
        # cache key → [(pub_no, file name)] behind the last download (BRIEF.md)
        self._files_used: dict[str, list[tuple[str, str]]] = {}

    # ── HTTP helpers ─────────────────────────────────────────────────────

    def _api(self, path: str) -> str:
        return f"{self.settings.base_url.rstrip('/')}/_api/web/{path}"

    def _get_json(self, url: str) -> dict:
        return self.get_json(url, source="CBS", headers=_JSON)

    def list_items(self, top: int = LIST_WINDOW) -> list[dict]:
        url = self._api(f"lists/getbytitle('{quote(LIST_TITLE)}')/items"
                        f"?$top={top}&$orderby=Created%20desc&$select={_LIST_FIELDS}")
        data = self._get_json(url)
        if not isinstance(data.get("value"), list):
            raise ProviderError("CBS release list has no `value` array")
        return data["value"]

    def releases(self) -> list[Release]:
        """The newest releases, newest first; one list query per run. A page
        item CBS created ahead of its publication time (CbsDataPublishDate
        still in the future) is embargoed and left out until then."""
        with self._lock:
            if self._releases is None:
                now = dt.datetime.now(dt.UTC)
                rels = [r for r in map(_release, self.list_items())
                        if r is not None and r.published <= now]
                rels.sort(key=lambda r: (r.published, r.year, r.number.zfill(5)), reverse=True)
                self._releases = rels
            return self._releases

    def folder_files(self, rel: Release) -> list[dict]:
        """`[{"Name", "Length"}, …]` of a release's DocLib folder (cached)."""
        with self._lock:
            if rel.folder not in self._folders:
                url = self._api(f"GetFolderByServerRelativeUrl('{quote(rel.folder)}')"
                                "/Files?$select=Name,Length")
                files = self._get_json(url).get("value")
                if not isinstance(files, list):
                    raise ProviderError(f"{rel.pub_no}: CBS folder listing has no `value`")
                self._folders[rel.folder] = sorted(
                    ({"Name": str(f.get("Name") or ""), "Length": int(f.get("Length") or 0)}
                     for f in files if isinstance(f, dict)), key=lambda f: f["Name"])
            return self._folders[rel.folder]

    def file_url(self, rel: Release, name: str) -> str:
        return f"{SITE}{quote(rel.folder)}/{quote(name)}"

    def clear_cache(self) -> None:
        super().clear_cache()
        with self._lock:
            self._releases = None
            self._folders.clear()
            self._files_used.clear()

    # ── matching ─────────────────────────────────────────────────────────

    def matching(self, report: CbsReport | dict, n: int) -> list[Release]:
        """The newest `n` releases of the report, newest first. Raises when
        none match: the sync then leaves the page last-good."""
        report = report if isinstance(report, CbsReport) else CbsReport.model_validate(report)
        out = []
        for rel in self.candidates(report):
            if report.chapter and not any(
                f["Name"].startswith(f"{report.chapter}_") for f in self.folder_files(rel)
            ):
                continue
            out.append(rel)
            if len(out) >= n:
                break
        if not out:
            raise ProviderError(
                f"no CBS release in the newest {LIST_WINDOW} matches {report.model_dump()}"
            )
        return out

    def candidates(self, report: CbsReport | dict) -> list[Release]:
        """Every release in the list window that `matching` could pick, before
        its chapter filter (which needs a folder listing per release)."""
        report = report if isinstance(report, CbsReport) else CbsReport.model_validate(report)
        rx = re.compile(report.title_regex)
        return [rel for rel in self.releases() if rx.search(rel.title)
                and (not report.interval or report.interval in rel.interval)]

    def listing_key(self, dataset_id: str, source: SourceConfig, cfg: CbsDatasetConfig) -> str:
        """The report's candidate releases, from the one list query that serves
        every CBS page, plus this parser's code.

        Each page is built only from those releases' folders and files, so an
        unchanged key means unchanged facts and CSVs, provided CBS doesn't
        edit a published release's files in place (the periodic full check
        catches that). A new edition, a withdrawn one, an edited title or
        headline, or an old edition sliding out of the list window all
        change the key and force a full sync.

        A fresh release's folder is not settled yet: CBS can list the page
        before its tables land, and `matching` then skips it by chapter or
        `table_file` finds no table. So the folder listing (names + sizes) of
        every candidate younger than `_SETTLE_DAYS` is in the key too: files
        arriving late move it. Older reports cost no requests beyond the
        list query."""
        h = hashlib.sha256(_CODE_HASH.encode())
        settled = dt.datetime.now(dt.UTC) - dt.timedelta(days=_SETTLE_DAYS)
        for rel in self.candidates(cfg.report):
            files = self.folder_files(rel) if rel.published > settled else None
            h.update(json.dumps([rel.pub_no, rel.year, rel.number, rel.published.isoformat(),
                                 rel.title, rel.headline, list(rel.interval), rel.file_ref,
                                 files], ensure_ascii=False).encode())
        return h.hexdigest()

    def find_table_file(self, rel: Release, stem: str) -> dict | None:
        """The release's `<…><stem>.xlsx`, else `.xls`, else None. The stem
        matches whole: `t3` never picks `t3a` or `t13`, nor `t3a` a `t3`."""
        files = self.folder_files(rel)
        for ext in _TABLE_EXTS:
            rx = re.compile(rf"\d{re.escape(stem.lower())}{re.escape(ext)}$")
            hits = [f for f in files if rx.search(f["Name"].lower())]
            if hits:
                return hits[0]
        return None

    def table_file(self, rel: Release, stem: str) -> dict:
        f = self.find_table_file(rel, stem)
        if f is None:
            raise ProviderError(f"{rel.pub_no}: no {stem}.xlsx/.xls in {rel.folder}")
        return f

    def report_pdf(self, rel: Release) -> str:
        """The written report (`…b.pdf`), or "" when the release has none."""
        hits = [f["Name"] for f in self.folder_files(rel) if re.search(r"\db\.pdf$", f["Name"].lower())]
        return self.file_url(rel, hits[0]) if hits else ""

    # ── facts ────────────────────────────────────────────────────────────

    @staticmethod
    def _params(cfg: CbsDatasetConfig, r: CbsResource) -> dict:
        p = {"kind": r.kind, "report": cfg.report.model_dump(exclude_none=True)}
        if r.kind == "table":
            p.update(table=r.table, history_releases=cfg.history_releases)
            if r.optional:
                p["optional"] = True
        else:
            p["limit"] = r.limit
        return p

    def facts(self, dataset_id: str, source: SourceConfig, cfg: CbsDatasetConfig) -> ProviderFacts:
        latest = self.matching(cfg.report, 1)[0]
        resources = []
        for r in cfg.resources:
            f = self.find_table_file(latest, r.table) if r.kind == "table" else None
            if f is not None:
                url, fmt = self.file_url(latest, f["Name"]), "XLSX"
                if url.lower().endswith(".xls"):
                    fmt = "XLS"
            elif r.kind == "table" and not r.optional:
                self.table_file(latest, r.table)  # raises: a required table is missing
            else:  # releases, or an optional table the newest edition lacks
                url, fmt = latest.page_url, "HTML"
            resources.append(ProviderResource(id=r.id, name=r.name, format=fmt, url=url,
                                              params=self._params(cfg, r)))
        return ProviderFacts(
            title=source.title,
            notes=source.notes,
            organization=dict(self.ORGANIZATION),
            license_title=self.LICENSE_TITLE,
            tags=source.tags,
            update_frequency=source.update_frequency,
            source_url=source.source_url or self.RELEASES_URL,
            resources=resources,
        )

    def presentation(self) -> SourcePresentation:
        return SourcePresentation(
            source_name_he="הלשכה המרכזית לסטטיסטיקה",
            home_url=self.HOME_URL,
            terms_url=self.TERMS_URL,
            attribution_he="מקור הנתונים: הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), הודעות לתקשורת.",
            download_label_he="לקובץ באתר הלמ\"ס",
            explorer=False,
        )

    # ── data ─────────────────────────────────────────────────────────────

    def _cache_key(self, resource: dict) -> str:
        # Keyed by params too: two pages may share a latest file but stack a
        # different number of editions.
        return resource["url"] + "#" + json.dumps(resource.get("params") or {}, sort_keys=True,
                                                  ensure_ascii=False)

    def download(self, resource: dict) -> bytes:
        p = resource.get("params") or {}
        report = p.get("report")
        if not report:
            raise ProviderError(f"{resource['id']}: resource has no report params")
        if p.get("kind", "table") == "releases":
            return self._releases_csv(self.matching(report, int(p.get("limit") or 12)))
        stem = p.get("table")
        if not stem:
            raise ProviderError(f"{resource['id']}: table resource has no `table`")
        optional = bool(p.get("optional"))
        parts, used = [], []
        for rel in self.matching(report, int(p.get("history_releases") or 1)):
            f = self.find_table_file(rel, stem) if optional else self.table_file(rel, stem)
            if f is None:
                continue  # optional: this edition has no such table
            if f["Length"] > self.settings.max_bytes:
                # `too_large` like the capped read below, not a failed preview.
                raise ProviderTooLarge(f"{rel.pub_no} {f['Name']}: {f['Length']:,} bytes > "
                                       f"max_bytes {self.settings.max_bytes:,}")
            # The listing's Length is only a hint: the read itself stops at the cap.
            r = self.http_get(self.file_url(rel, f["Name"]), max_bytes=self.settings.max_bytes)
            if r.status_code != 200:
                raise ProviderError(f"{rel.pub_no} {f['Name']}: HTTP {r.status_code}")
            parts.append((rel, r.content))
            used.append((rel.pub_no, f["Name"]))
        self._files_used[self._cache_key(resource)] = used
        return grid_csv(parts)

    def _releases_csv(self, rels: list[Release]) -> bytes:
        out = io.StringIO(newline="")
        w = csv.writer(out, lineterminator="\n")
        w.writerow(RELEASE_COLUMNS)
        for rel in rels:
            w.writerow([rel.pub_no, rel.date, rel.title, rel.headline, rel.page_url,
                        self.report_pdf(rel)])
        return out.getvalue().encode("utf-8")

    # ── liveness ─────────────────────────────────────────────────────────

    def healthcheck(self) -> bool:
        self.list_items(top=1)  # raises on an HTTP error or a non-list answer
        return True

    # probe_available: the base "unknown". A discontinued report just stops
    # updating; CBS gives no definite "gone" signal.

    # ── authoring ────────────────────────────────────────────────────────

    def brief_section(self, resource: dict, csv_path: Path) -> str:
        with open(csv_path, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        p = resource.get("params") or {}
        out = io.StringIO()
        if p.get("kind") == "releases":
            out.write(f"- {len(rows)} matching release(s), newest first:\n\n")
            out.write("| RELEASE_NO | RELEASE_DATE | TITLE | HEADLINE |\n|---|---|---|---|\n")
            for r in sorted(rows, key=lambda r: r["RELEASE_DATE"], reverse=True):
                out.write(f"| {r['RELEASE_NO']} | {r['RELEASE_DATE']} | {_md(r['TITLE'])} | "
                          f"{_md(r['HEADLINE'])} |\n")
            return out.getvalue()
        used = self._files_used.get(self._cache_key(resource)) or []
        files = ", ".join(f"{n} `{f}`" for n, f in used)
        if not files:
            files = "none (optional table, absent from every edition)" if p.get("optional") else "?"
        out.write(f"- table `{p.get('table')}`"
                  + (" (optional)" if p.get("optional") else "")
                  + f", grid of {len(rows):,} non-empty sheet rows; files: {files}\n")
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            groups[(r["RELEASE_DATE"], r["RELEASE_NO"], r["SHEET_NO"], r["SHEET"])].append(r)
        for (date, no, sheet_no, sheet), grp in sorted(groups.items(), reverse=True):
            cols = [c for c in grp[0] if c.startswith("C") and any(g[c] for g in grp)]
            out.write(f"\n**{no} ({date}), sheet {sheet_no} `{sheet}`** — {len(grp)} rows"
                      + (f", first {_BRIEF_ROWS}" if len(grp) > _BRIEF_ROWS else "") + ":\n\n")
            out.write("| ROW | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols) + "\n")
            for g in grp[:_BRIEF_ROWS]:
                out.write(f"| {g['ROW']} | " + " | ".join(_md(g[c]) for c in cols) + " |\n")
        return out.getvalue()

    def authoring_notes(self) -> str:
        return (
            "- Each table resource is a GRID of one CBS Excel table: one row per non-empty\n"
            "  sheet row, columns `RELEASE_NO, RELEASE_DATE, SHEET_NO, SHEET, ROW, C01..Cnn`.\n"
            "  Cells are text exactly as in the sheet (numbers as `152` / `74.5`, dates ISO).\n"
            "  Sheets are print layouts: titles, multi-row Hebrew + English headers (often\n"
            "  right-to-left, labels in the last columns), data, footnotes.\n"
            "- Find header and data rows BY LABEL TEXT (Hebrew or English), never by fixed\n"
            "  ROW numbers or fixed Cxx positions: rows shift between editions (76 vs 78\n"
            "  rows in two visitor-arrivals tables). Locate a label cell, then read its row\n"
            "  or column. Year/period labels often appear only on the first row of a block\n"
            "  (forward-fill them).\n"
            "- Treat `..`, `-`, `—`, `x` and blank as missing. Strip footnote markers like\n"
            "  `(1)` / `*` from labels before matching.\n"
            "- When a HEADER label (what a column means: `Original data`, `Grand total`,\n"
            "  the period row) is not found, RAISE (ValueError naming the label). The\n"
            "  refresh then fails as recipe_failed, keeps the last-good page and opens an\n"
            "  issue. No silent fallback, no default numbers.\n"
            "- DATA rows (periods, countries, crossings) are found by pattern and may come\n"
            "  and go between editions: a missing one means fewer points, not an error.\n"
            "  `author verify` re-runs on the first 70% of grid rows, which cuts off the\n"
            "  bottom of each table; headers sit at the top and survive it. Only a row a\n"
            "  KPI can't do without (the latest period, the grand total) should raise. A\n"
            "  header that sits low in the sheet (a table's SA / trend section) is optional\n"
            "  for the same reason: a missing one leaves its series empty.\n"
            "- Use `from govlib import cbs`: `cbs.grid(frame)` (newest edition, cleaned\n"
            "  cells), `row_with` / `col_after` (header lookups that raise), `periods` and\n"
            "  `monthly_runs` (year/month rows), `num` / `val` (CBS missing marks → None).\n"
            "  `recipes/cbs-visitor-arrivals/` and `recipes/cbs-average-wage/` are worked\n"
            "  examples.\n"
            "- Pick period/label COLUMNS by content (the column holding the most roman\n"
            "  month numerals, the most 4-digit years), not by position: a numeric data\n"
            "  column can hold a value like `2900`.\n"
            "- With `history_releases` > 1 the grid stacks several editions; filter by\n"
            "  RELEASE_DATE (the newest is max()). Later editions revise earlier figures:\n"
            "  for an overlapping period, the newest edition wins.\n"
            "- The `.xls`/`.xlsx` flip between editions is invisible here (same grid).\n"
            "- A table resource with `\"optional\": true` (source.json) may be an EMPTY\n"
            "  grid (header only) when no edition in the window has that table; with\n"
            "  `history_releases` > 1 an edition lacking it just adds no rows. Check\n"
            "  `frame.empty` before `cbs.grid()` (which raises on an empty grid) and drop\n"
            "  that section. Lettered sub-tables (CBS's 3א/3ב) are stems `t3a`/`t3b`.\n"
            "- For the \"latest edition\" card use `cbs.latest_release(frames[\"releases\"])`:\n"
            "  the same edition `cbs.grid()` reads (newest date, then higher number).\n"
            "- A `releases` resource lists recent editions: RELEASE_NO, RELEASE_DATE, TITLE,\n"
            "  HEADLINE (CBS's one-line summary), PAGE_URL, REPORT_PDF_URL. Use it for a\n"
            "  \"latest edition\" line linking the official release.\n"
            "- The page shell has NO live data explorer for this source: every chart needs\n"
            "  its own <details><table>. `data-fallback=\"explorer\"` is rejected by verify.\n"
            "  No GovExplorer / GovMap. ECharts only.\n"
            "- Credit the source in the page intro as \"הלשכה המרכזית לסטטיסטיקה\" (הלמ\"ס).\n"
            "  The CBS license forbids implying CBS endorses the page: no \"מאושר\"/\"רשמי\"\n"
            "  wording about govil.ai. The shell adds the download link and attribution.\n"
        )


def _md(v: str) -> str:
    v = (v or "").replace("|", "\\|")
    return v if len(v) <= _BRIEF_CELL else v[: _BRIEF_CELL - 1] + "…"


# ── catalog CLI ──────────────────────────────────────────────────────────

_MONTHS = ("ינואר", "פברואר", "מרץ", "מרס", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
           "ספטמבר", "אוקטובר", "נובמבר", "דצמבר")
_PERIOD_WORDS = ("רבעון", "הרבעון", "רבעונים", "הרבעונים", "חודש", "בחודש", "החודש",
                 "חודשים", "בחודשים", "שנת", "בשנת", "בשנים", "שנים", "ראשון", "הראשון",
                 "שני", "השני", "שלישי", "השלישי", "רביעי", "הרביעי", "מחצית", "המחצית",
                 "לחודש", "לרבעון", "לשנת", "לשנים")
_HEB_PREFIX = "בהולמשכ"
_HEB_YEAR = re.compile(r"(?<!\S)[בלוה]?תש[א-ת]?\"?[א-ת](?!\S)")


def normalize_title(title: str) -> str:
    """A title with its period removed, so editions of one report collide:
    `כניסות של מבקרים לישראל באוקטובר 2026` → `כניסות של מבקרים לישראל`."""
    t = re.sub(r"\(.*?\)", " ", title or "")
    t = _HEB_YEAR.sub(" ", t)
    t = re.sub(r"\d+", " ", t)
    t = re.sub(r"[-–—:,./\"'׳״]", " ", t)
    words = []
    for w in t.split():
        core = w
        if core in _PERIOD_WORDS:
            continue
        if core in _MONTHS or (len(core) > 1 and core[0] in _HEB_PREFIX and core[1:] in _MONTHS):
            continue
        if len(core) > 2 and core[:2] in ("וב", "של", "מה") and core[2:] in _MONTHS:
            continue
        words.append(core)
    return " ".join(words).strip()


_RX_SPECIAL = set(r".^$*+?{}[]\|()")


def _rx_escape(s: str) -> str:
    return "".join("\\" + c if c in _RX_SPECIAL else c for c in s)


def suggest_regex(titles: list[str]) -> str:
    """`^` + the titles' longest common prefix, cut back to a whole word."""
    prefix = titles[0]
    for t in titles[1:]:
        i = 0
        while i < min(len(prefix), len(t)) and prefix[i] == t[i]:
            i += 1
        prefix = prefix[:i]
    if not all(len(t) == len(prefix) for t in titles) and " " in prefix:
        prefix = prefix[: prefix.rfind(" ") + 1]
    return "^" + _rx_escape(prefix)


def catalog(provider: CbsReleasesProvider, months: int = 12, min_count: int = 2,
            stems: bool = True) -> list[dict]:
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=round(months * 30.44))
    items = provider.list_items(top=min(5000, max(LIST_WINDOW, months * 40)))
    rels = [r for r in map(_release, items) if r is not None and r.published >= since]
    groups: dict[str, list[Release]] = defaultdict(list)
    for r in rels:
        groups[normalize_title(r.title)].append(r)
    out = []
    for key, grp in groups.items():
        if len(grp) < min_count:
            continue
        grp.sort(key=lambda r: r.published, reverse=True)
        last = grp[0]
        entry = {
            "key": key,
            "count": len(grp),
            "interval": Counter(i for r in grp for i in r.interval).most_common(1)[0][0]
            if any(r.interval for r in grp) else "",
            "last_release": last.pub_no,
            "last_date": last.date,
            "last_title": last.title,
            "title_regex": suggest_regex([r.title for r in grp]),
        }
        if stems:
            try:
                names = [f["Name"] for f in provider.folder_files(last)]
            except ProviderError as e:
                names, entry["error"] = [], str(e)
            chapters = Counter(n.split("_", 1)[0] for n in names if "_" in n)
            entry["chapter"] = chapters.most_common(1)[0][0] if chapters else ""
            entry["tables"] = sorted(
                {m.group(1) + "." + m.group(2) for n in names
                 if (m := re.search(r"\d(t\d+[a-z]?)\.(xlsx?)$", n.lower()))},
                key=lambda s: (int(re.sub(r"\D", "", s.split(".")[0])), s))
        out.append(entry)
    order = {"חודשי": 0, "רבעוני": 1, "שנתי": 2}
    out.sort(key=lambda e: (order.get(e["interval"], 3), -e["count"], e["key"]))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m services.providers.cbs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog", help="recurring CBS reports in the release list")
    c.add_argument("--months", type=int, default=12)
    c.add_argument("--min-count", type=int, default=2)
    c.add_argument("--no-tables", action="store_true", help="skip the per-report folder listing")
    c.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    provider = CbsReleasesProvider.from_env()
    rows = catalog(provider, args.months, args.min_count, stems=not args.no_tables)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for e in rows:
        print(f"{e['count']:>3}  {e['interval'] or '-':<8} ch {e.get('chapter', '?'):<3} "
              f"{e['last_release']:<10} {e['last_date']}  {e['last_title']}")
        print(f"     title_regex {json.dumps(e['title_regex'], ensure_ascii=False)}"
              + (f"  tables {' '.join(e['tables'])}" if e.get("tables") else ""))
    print(f"\n{len(rows)} recurring report(s) over {args.months} months", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["CbsDatasetConfig", "CbsReleasesProvider", "Release", "catalog", "cell_text",
           "grid_csv", "normalize_title", "workbook_grid"]
