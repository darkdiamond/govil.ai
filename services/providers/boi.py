"""Bank of Israel statistics — the BoI SDMX web service (no key).

    {base}/data/dataflow/BOI.STATISTICS/<FLOW>/<VERSION>/<KEY>?format=csv

returns one row per observation: `SERIES_CODE, FREQ, <dimension codes…>,
TIME_PERIOD, OBS_VALUE, RELEASE_STATUS`. An empty KEY is the whole
dataflow. Unknown flows and keys answer 404 (an HTML gov.il error page).
There is no ETag/Last-Modified, so versions are content hashes.

Series carry `CONF_STATUS = F` ("Free (free for publication)"). The CSV has
no series names, so `download()` also asks for the same query as SDMX-JSON
(Hebrew, one observation per series) and adds BoI's own Hebrew series name
as a `SERIES_NAME_HE` column: a series BoI adds later arrives labelled.
"""
from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

AGENCY = "BOI.STATISTICS"
# A small, always-published series: is the service up at all?
_HEALTH_PATH = "EXR/1.0/RER_USD_ILS"
_BRIEF_MAX_SERIES = 150
# Columns that are the observation itself, not a series dimension.
_OBS_COLUMNS = ("SERIES_CODE", "SERIES_NAME_HE", "TIME_PERIOD", "OBS_VALUE",
                "RELEASE_STATUS", "COMMENTS")
NAME_COLUMN = "SERIES_NAME_HE"


def _with_names(data: bytes, names: dict[str, str]) -> bytes:
    """Insert SERIES_NAME_HE after SERIES_CODE (blank for an unnamed code)."""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))
    if not rows or "SERIES_CODE" not in rows[0]:
        raise ProviderError("BoI CSV has no SERIES_CODE column")
    i = rows[0].index("SERIES_CODE")
    out = io.StringIO(newline="")
    w = csv.writer(out, lineterminator="\n")
    w.writerow(rows[0][: i + 1] + [NAME_COLUMN] + rows[0][i + 1:])
    for r in rows[1:]:
        if r:
            code = r[i] if i < len(r) else ""
            w.writerow(r[: i + 1] + [names.get(code, "")] + r[i + 1:])
    return out.getvalue().encode("utf-8")


class BoiResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    dataflow: str = Field(pattern=r"^[A-Z0-9_]+$")
    version: str = Field("1.0", pattern=r"^\d+(\.\d+)*$")
    # SDMX key: series codes joined with "+", or "" for the whole flow.
    key: str = Field("", pattern=r"^[A-Za-z0-9_.+]*$")
    startperiod: Optional[str] = Field(None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")


class BoiDatasetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resources: list[BoiResource] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [r.id for r in self.resources]
        if len(ids) != len(set(ids)):
            raise ValueError("resource ids must be unique")
        return self


class BoiSdmxProvider(SourceProvider):
    key = "boi_sdmx"
    id_prefix = "boi-"
    label = "בנק ישראל (SDMX)"
    DatasetConfig = BoiDatasetConfig
    default_settings = ProviderSettings(
        base_url="https://edge.boi.org.il/FusionEdgeServer/sdmx/v2",
        # A whole mortgage-rates flow (BIR_MRTG_99) takes ~40 s to answer.
        timeout_s=180.0,
        retries=2,
        min_interval_s=1.0,
        max_bytes=100_000_000,
    )
    sort_keys = ("SERIES_CODE", "TIME_PERIOD")

    ORGANIZATION = {
        "id": "bank-of-israel",
        "name": "bank-of-israel",
        "title": "בנק ישראל",
        "logo_url": None,
    }
    LICENSE_TITLE = "בנק ישראל: חופשי לפרסום"
    HOME_URL = "https://www.boi.org.il/"
    TERMS_URL = "https://www.boi.org.il/website_terms/"

    def _data_url(self, r: BoiResource | dict, **extra) -> str:
        r = r if isinstance(r, BoiResource) else BoiResource.model_validate(r)
        query = {"format": "csv"}
        if r.startperiod:
            query["startperiod"] = r.startperiod
        query.update(extra)
        base = self.settings.base_url.rstrip("/")
        return f"{base}/data/dataflow/{AGENCY}/{r.dataflow}/{r.version}/{r.key}?{urlencode(query)}"

    # ── facts ────────────────────────────────────────────────────────────

    def facts(self, dataset_id: str, source: SourceConfig, cfg: BoiDatasetConfig) -> ProviderFacts:
        return ProviderFacts(
            title=source.title,
            notes=source.notes,
            organization=dict(self.ORGANIZATION),
            license_title=self.LICENSE_TITLE,
            tags=source.tags,
            update_frequency=source.update_frequency,
            source_url=source.source_url or self.HOME_URL,
            resources=[
                ProviderResource(
                    id=r.id, name=r.name, format="CSV", url=self._data_url(r),
                    params=r.model_dump(exclude={"id", "name"}),
                )
                for r in cfg.resources
            ],
        )

    def presentation(self) -> SourcePresentation:
        return SourcePresentation(
            source_name_he="בנק ישראל",
            home_url=self.HOME_URL,
            terms_url=self.TERMS_URL,
            attribution_he="מקור הנתונים: בנק ישראל, סדרות סטטיסטיות (SDMX).",
            download_label_he="הורדת CSV מבנק ישראל",
            explorer=False,
        )

    # ── data ─────────────────────────────────────────────────────────────

    def _params(self, resource: dict) -> dict:
        return {"id": resource["id"], "name": resource.get("name") or resource["id"],
                **(resource.get("params") or {})}

    def download(self, resource: dict) -> bytes:
        url = self._data_url(self._params(resource))
        r = self.http_get(url)
        if r.status_code != 200:
            raise ProviderError(f"{resource['id']}: HTTP {r.status_code} from BoI")
        if "csv" not in r.headers.get("content-type", ""):
            raise ProviderError(
                f"{resource['id']}: BoI answered {r.headers.get('content-type')!r}, not CSV"
            )
        return _with_names(r.content, self.series_names(resource))

    def series_names(self, resource: dict) -> dict[str, str]:
        """SERIES_CODE → BoI's Hebrew series name, for the resource's query.
        A failure fails the download: a page must not lose its labels."""
        url = self._data_url(self._params(resource), format="sdmx-json", lastNObservations="1")
        r = self.http_get(url, headers={"Accept-Language": "he"})
        if r.status_code != 200:
            raise ProviderError(f"{resource['id']}: HTTP {r.status_code} for series names")
        try:
            data = r.json()["data"]
            structure = (data.get("structures") or [data.get("structure")])[0]
            dims = structure["dimensions"]["series"]
            codes = next(d for d in dims if d["id"] == "SERIES_CODE")
            return {v["id"]: (v.get("name") or "").strip() for v in codes["values"]}
        except (ValueError, KeyError, IndexError, StopIteration, TypeError) as e:
            raise ProviderError(f"{resource['id']}: unreadable SDMX-JSON series names: {e}") from e

    # ── liveness ─────────────────────────────────────────────────────────

    def healthcheck(self) -> bool:
        base = self.settings.base_url.rstrip("/")
        r = self.http_get(
            f"{base}/data/dataflow/{AGENCY}/{_HEALTH_PATH}?format=csv&lastNObservations=1"
        )
        return r.status_code == 200 and "csv" in r.headers.get("content-type", "")

    def probe_available(self, resources: list[dict]) -> Availability:
        # A 404 is definite only while the service itself is up (a gov.il
        # outage serves the same error page for everything).
        if not resources or not self.healthy():
            return "unknown"
        statuses = []
        for res in resources:
            try:
                r = self.http_get(self._data_url(self._params(res), lastNObservations="1"))
            except ProviderError:
                return "unknown"
            statuses.append(r.status_code)
        if all(s == 200 for s in statuses):
            return "alive"
        # Gone only when every query is: one retired series doesn't remove a
        # dataset (its refresh fails as schema_changed and asks for a human).
        if all(s == 404 for s in statuses):
            return "gone"
        return "unknown"

    # ── authoring ────────────────────────────────────────────────────────

    def brief_section(self, resource: dict, csv_path: Path) -> str:
        """Every series in the file: BoI's Hebrew name, the dimension codes
        that tell series apart, span and last value."""
        series: dict[str, dict] = defaultdict(lambda: {"n": 0, "first": None, "last": None,
                                                       "last_value": None, "dims": {},
                                                       "name": ""})
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            dims = [c for c in reader.fieldnames or [] if c not in _OBS_COLUMNS]
            for row in reader:
                s = series[row.get("SERIES_CODE", "")]
                s["n"] += 1
                t = row.get("TIME_PERIOD", "")
                if s["first"] is None or t < s["first"]:
                    s["first"] = t
                if s["last"] is None or t >= s["last"]:
                    s["last"], s["last_value"] = t, row.get("OBS_VALUE")
                if not s["dims"]:
                    s["dims"] = {d: row.get(d, "") for d in dims}
                    s["name"] = row.get(NAME_COLUMN, "")
        # Dimensions that differ between series are the ones that say what a
        # series is; constant ones are listed once.
        varying = [d for d in dims if len({s["dims"].get(d) for s in series.values()}) > 1]
        constant = {d: next(iter(series.values()))["dims"].get(d) for d in dims
                    if d not in varying} if series else {}
        p = self._params(resource)
        out = io.StringIO()
        out.write(f"- BoI dataflow `{p.get('dataflow')}` key `{p.get('key') or '(all)'}` — "
                  f"{len(series)} series\n")
        out.write(f"- constant dimensions: `{json.dumps(constant, ensure_ascii=False)}`\n")
        out.write(f"- per series (varying dimensions: {', '.join(varying) or 'none'}):\n\n")
        out.write(f"| SERIES_CODE | {NAME_COLUMN} | " + " | ".join(varying)
                  + " | obs | first | last | last value |\n")
        out.write("|---|---|" + "---|" * len(varying) + "---|---|---|---|\n")
        for i, (code, s) in enumerate(sorted(series.items())):
            if i >= _BRIEF_MAX_SERIES:
                out.write(f"\n… {len(series) - _BRIEF_MAX_SERIES} more series not listed\n")
                break
            cells = [s["dims"].get(d, "") for d in varying]
            out.write(f"| {code} | {s['name']} | " + " | ".join(cells)
                      + f" | {s['n']:,} | {s['first']} | {s['last']} | {s['last_value']} |\n")
        return out.getvalue()

    def authoring_notes(self) -> str:
        return "\n".join([
            "- Rows are observations: one row per (SERIES_CODE, TIME_PERIOD). OBS_VALUE is a",
            "  string; parse with float() and skip blanks. FREQ tells D/M/Q/A; TIME_PERIOD",
            "  is `YYYY-MM-DD`, `YYYY-MM`, `YYYY-Qn` or `YYYY`.",
            "- SERIES_NAME_HE is BoI's own Hebrew series name (long, hyphen-joined",
            "  facets). Pick series by SERIES_CODE or by dimension codes, never by name.",
            "  Short display labels may live in a dict in compute.py, but an unknown code",
            "  must still render (fall back to SERIES_NAME_HE, then the code) so a new BoI",
            "  series never breaks the refresh.",
            "- UNIT_MEASURE / UNIT_MULT give units (PT = percent; UNIT_MULT 6 = millions).",
            "- The page shell has NO live data explorer for this source: every chart needs",
            "  its own <details><table> (downsample long daily series, e.g. month-end).",
            "  `data-fallback=\"explorer\"` is rejected by verify.",
            "- No GovExplorer / GovMap (they read the CKAN datastore). ECharts only.",
            "- Credit the source in the page intro text as \"בנק ישראל\". The shell adds",
            "  the download link and attribution; do not link to data.gov.il.",
        ])
