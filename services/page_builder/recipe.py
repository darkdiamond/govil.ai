"""Recipe contract — the deterministic replacement for per-update agent runs.

A recipe is authored ONCE per dataset (locally, with Claude Code — see
`.claude/skills/author-dataset/SKILL.md`) and then re-run, with no LLM, every
time CKAN publishes a new version of the dataset. It lives in
`recipes/<dataset_id>/`:

    recipe.json        RecipeManifest — inputs, version, insight floor
    compute.py         compute(frames) -> page model (pure: no network,
                       no clock, no randomness)
    template.html.j2   Jinja2 body template rendered from the page model
    <name>.geojson     optional map snapshot, read by an input with `snapshot`

The page model is the ONLY place numbers come from. The template carries
layout and fixed copy; every KPI, chart series and insight sentence is
computed from the data on each run, so claims re-word (or drop out) as the
data changes instead of going stale. `lint_template` enforces the
"no numbers in the template" half of that.

Data contract for `compute`: one pandas DataFrame per declared input, every
column read as `str` with no NA inference (empty cells are ""). Type
coercion is the recipe's job, explicitly — pandas' dtype inference flips
between versions of the same dataset (one stray text cell turns an int
column into object), and a recipe that silently depended on it would
break on the very update it exists to absorb. `concat` inputs carry an
extra `_resource_name` column naming the file each row came from.

Map snapshots: data.gov.il's CDN refuses scripted downloads of uploaded
files (SHP/KMZ/GeoJSON), so geometry that exists only in such a file can't
be fetched at refresh time. The author downloads it once in a browser,
`author snapshot` converts it to a committed WGS84 GeoJSON, and an input
with `snapshot` reads that file as a table: one row per feature, its
properties as strings plus `__geometry` (the feature's geometry as compact
JSON). The CKAN resource it was taken from is still checked on every run:
when its size/hash moves past `snapshot_of`, the refresh fails
`geometry_stale` and a human re-downloads it.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import AgentData

CONTRACT_VERSION = 1

log = logging.getLogger("page_builder.recipe")
MANIFEST_FILENAME = "recipe.json"
COMPUTE_FILENAME = "compute.py"
TEMPLATE_FILENAME = "template.html.j2"
RECIPE_FILES = (MANIFEST_FILENAME, COMPUTE_FILENAME, TEMPLATE_FILENAME)

# Column added to every row of a `concat` input.
RESOURCE_NAME_COLUMN = "_resource_name"
# Column holding each feature's geometry in a `snapshot` input.
GEOMETRY_COLUMN = "__geometry"
_SNAPSHOT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\.geojson$")


class RecipeError(RuntimeError):
    """A recipe could not produce a valid page from the current data.

    `reason` is the authoring-queue reason the failure maps to
    (`recipe_failed` / `schema_changed`) — what the human re-authoring the
    dataset needs to know first.
    """

    def __init__(self, message: str, *, reason: str = "recipe_failed"):
        super().__init__(message)
        self.reason = reason


class SnapshotOf(BaseModel):
    """The CKAN resource facts a snapshot was taken from. `hash` is CKAN's
    md5 of the upload (often empty); `size` is the fallback. `last_modified`
    is a note only: CKAN bumps it on byte-identical re-uploads."""
    model_config = ConfigDict(extra="forbid")

    size: Optional[int] = Field(default=None, ge=0)
    hash: Optional[str] = None
    last_modified: Optional[str] = None
    taken_at: Optional[str] = None

    @model_validator(mode="after")
    def _comparable(self) -> "SnapshotOf":
        if self.size is None and not self.hash:
            raise ValueError("snapshot_of needs `size` or `hash`")
        return self


class RecipeInput(BaseModel):
    """One logical table the recipe consumes.

    Exactly one selector:
      - `by_id`: a single CKAN resource id. Use when the dataset has one
        stable data file.
      - `by_schema`: every datastore-active resource whose columns include
        all of these. Use for datasets that add a file per period (a new
        yearly CSV) — the new file is picked up automatically. Pair with
        `concat: true`, or with `pick: "latest"` for datasets that publish
        each full snapshot as a new resource: only the matching resource
        with the newest CKAN `last_modified` is read.

    `columns` (optional) fetches only these columns from the datastore,
    which shrinks the export of a wide table. It must include every
    `required_columns` entry; compute sees no other column.

    `snapshot` reads a committed GeoJSON in the recipe dir instead of the
    datastore (see the module doc). `by_id` then names the CKAN map-file
    resource it was taken from, and `snapshot_of` that resource's facts then.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    by_id: Optional[str] = None
    by_schema: Optional[list[str]] = None
    concat: bool = False
    pick: Literal["all", "latest"] = "all"
    required_columns: list[str] = Field(default_factory=list)
    columns: Optional[list[str]] = Field(default=None, min_length=1)
    snapshot: Optional[str] = None
    snapshot_of: Optional[SnapshotOf] = None

    @model_validator(mode="after")
    def _one_selector(self) -> "RecipeInput":
        if bool(self.by_id) == bool(self.by_schema):
            raise ValueError(f"input {self.name!r}: set exactly one of by_id / by_schema")
        if self.snapshot is not None or self.snapshot_of is not None:
            if self.snapshot is None or self.snapshot_of is None:
                raise ValueError(f"input {self.name!r}: snapshot and snapshot_of go together")
            if not _SNAPSHOT_NAME_RE.match(self.snapshot):
                raise ValueError(
                    f"input {self.name!r}: snapshot must be a plain lowercase "
                    "`<name>.geojson` file in the recipe dir"
                )
            if not self.by_id:
                raise ValueError(f"input {self.name!r}: snapshot needs by_id (its CKAN resource)")
            if self.columns is not None or self.concat or self.pick != "all":
                raise ValueError(f"input {self.name!r}: snapshot takes no columns / concat / pick")
        if self.pick == "latest":
            if not self.by_schema:
                raise ValueError(f"input {self.name!r}: pick 'latest' requires by_schema")
            if self.concat:
                raise ValueError(f"input {self.name!r}: pick 'latest' reads one resource; drop concat")
        elif self.by_schema and not self.concat:
            raise ValueError(
                f"input {self.name!r}: by_schema requires concat: true or pick: 'latest'"
            )
        if self.columns is not None:
            missing = [c for c in self.required_columns if c not in self.columns]
            if missing:
                raise ValueError(
                    f"input {self.name!r}: required_columns {missing} not in columns"
                )
            if len(set(self.columns)) != len(self.columns):
                raise ValueError(f"input {self.name!r}: duplicate entries in columns")
            if "_id" in self.columns:
                raise ValueError(f"input {self.name!r}: `_id` is never exported; drop it from columns")
        return self

    @property
    def columns_needed(self) -> list[str]:
        return list(dict.fromkeys(
            [*(self.by_schema or []), *self.required_columns, *(self.columns or [])]
        ))


class RecipeLimits(BaseModel):
    """Per-recipe overrides of the refresh's fetch/compute caps, for the few
    datasets too big for the defaults (env `REFRESH_*`). A recipe that sets
    any of them is "heavy": the refresh runs it after every other recipe, so
    if it still blows up, the rest of the night is already done. The upper
    bounds are a sanity ceiling, not a budget.
    """
    model_config = ConfigDict(extra="forbid")

    max_records: Optional[int] = Field(default=None, ge=1, le=20_000_000)
    max_bytes: Optional[int] = Field(default=None, ge=1, le=2_000_000_000)
    total_bytes: Optional[int] = Field(default=None, ge=1, le=4_000_000_000)
    wall_budget_s: Optional[int] = Field(default=None, ge=1, le=3600)
    compute_timeout_s: Optional[int] = Field(default=None, ge=1, le=1800)
    compute_memory_mb: Optional[int] = Field(default=None, ge=256, le=30_000)


class RecipeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = CONTRACT_VERSION
    dataset_id: str
    # Bump on every change to compute.py / template.html.j2: a new version
    # re-renders the page even when the data hasn't moved.
    recipe_version: int = Field(ge=1)
    authored_at: datetime
    # The CKAN version + row counts the recipe was written against — the
    # baseline a reviewer compares a broken refresh to.
    authored_against: dict[str, Any] = Field(default_factory=dict)
    inputs: list[RecipeInput] = Field(min_length=1)
    # Fewer surviving insights than this fails the refresh: the data has
    # drifted far enough from what the rules were written for that the page
    # needs a human look.
    min_insights: int = Field(default=2, ge=0)
    # Literal strings allowed to contain digits in template prose (e.g.
    # "24/7", "ISO 9001"). Everything else numeric must come from the model.
    lint_allow_numbers: list[str] = Field(default_factory=list)
    limits: RecipeLimits = Field(default_factory=RecipeLimits)

    @property
    def heavy(self) -> bool:
        return bool(self.limits.model_fields_set)

    @model_validator(mode="after")
    def _unique_names(self) -> "RecipeManifest":
        names = [i.name for i in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("input names must be unique")
        snaps = self.snapshot_files
        if len(snaps) != len(set(snaps)):
            raise ValueError("snapshot files must be unique")
        return self

    @property
    def snapshot_files(self) -> list[str]:
        return [i.snapshot for i in self.inputs if i.snapshot]


KpiTone = Literal["brand", "ok", "warn", "info", "danger"]


class Kpi(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: Any = None
    display: str
    # Validated here, not only in author verify: a tone branch that only
    # fires on some future data state must fail the refresh (page kept,
    # issue opened), not ship an uncoloured `text-<typo>` KPI.
    tone: Optional[KpiTone] = None


class Insight(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    text_he: str = Field(min_length=1)


class PageModel(BaseModel):
    """What `compute()` returns. `agent_data` is validated as `AgentData`
    and written to Firestore exactly like an agent session's output was."""
    model_config = ConfigDict(extra="allow")

    agent_data: AgentData
    kpis: dict[str, Kpi] = Field(default_factory=dict)
    charts: dict[str, Any] = Field(default_factory=dict)
    insights: list[Insight] = Field(default_factory=list)
    tables: dict[str, Any] = Field(default_factory=dict)


class Recipe:
    """A loaded recipe directory."""

    def __init__(self, root: Path, manifest: RecipeManifest):
        self.root = root
        self.manifest = manifest

    @property
    def dataset_id(self) -> str:
        return self.manifest.dataset_id

    @property
    def compute_path(self) -> Path:
        return self.root / COMPUTE_FILENAME

    @property
    def template_path(self) -> Path:
        return self.root / TEMPLATE_FILENAME

    @property
    def files(self) -> list[str]:
        """Every file the recipe is made of: the fixed three + its snapshots."""
        return [*RECIPE_FILES, *self.manifest.snapshot_files]

    @classmethod
    def load(cls, root: Path) -> "Recipe":
        root = Path(root)
        missing = [f for f in RECIPE_FILES if not (root / f).is_file()]
        if missing:
            raise RecipeError(f"recipe {root} is missing {', '.join(missing)}")
        manifest = RecipeManifest.model_validate_json(
            (root / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        if manifest.dataset_id != root.name:
            raise RecipeError(
                f"recipe dir {root.name} declares dataset_id {manifest.dataset_id}"
            )
        missing = [f for f in manifest.snapshot_files if not (root / f).is_file()]
        if missing:
            raise RecipeError(f"recipe {root} is missing snapshot {', '.join(missing)}")
        return cls(root, manifest)


# ── map snapshots ────────────────────────────────────────────────────────


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, int):
        return str(v)
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def snapshot_table(path: Path) -> tuple[list[str], list[list[str]]]:
    """A committed GeoJSON FeatureCollection as (header, rows): one row per
    feature in file order (`author snapshot` sorts them), every property as
    a string ("" for null), plus GEOMETRY_COLUMN. A malformed file is the
    recipe's fault (`recipe_failed`), never the data's."""
    name = Path(path).name
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RecipeError(f"snapshot {name}: unreadable ({e})") from None
    feats = doc.get("features") if isinstance(doc, dict) else None
    if not isinstance(feats, list) or doc.get("type") != "FeatureCollection":
        raise RecipeError(f"snapshot {name}: not a GeoJSON FeatureCollection")
    keys: dict[str, None] = {}
    for f in feats:
        props = (f or {}).get("properties") or {}
        if not isinstance(props, dict) or GEOMETRY_COLUMN in props:
            raise RecipeError(f"snapshot {name}: bad feature properties")
        keys.update(dict.fromkeys(props))
    rows = []
    for f in feats:
        props = f.get("properties") or {}
        rows.append([*(_cell(props.get(k)) for k in keys), _cell(f.get("geometry"))])
    return [*keys, GEOMETRY_COLUMN], rows


def snapshot_stale(inp: RecipeInput, res: Optional[dict]) -> Optional[str]:
    """Why the CKAN resource has moved past its snapshot, or None. Compares
    CKAN's md5 when both sides have one, else the size. A resource with
    neither can't be judged: logged, not failed."""
    snap = inp.snapshot_of
    if res is None:
        return f"resource {inp.by_id} is gone from the dataset"
    if snap.hash and res.get("hash"):
        return None if res["hash"] == snap.hash else f"hash {snap.hash[:12]} → {res['hash'][:12]}"
    if snap.size is not None and res.get("size") is not None:
        size = int(res["size"])
        return None if size == snap.size else f"size {snap.size:,} → {size:,} bytes"
    log.warning("input %r: resource %s has no size/hash to compare with its snapshot",
                inp.name, inp.by_id)
    return None


# ── input resolution ─────────────────────────────────────────────────────


def _modified_key(resource: dict) -> datetime:
    """Sort key for `pick: "latest"`: the resource's CKAN `last_modified`
    (a datetime from Firestore, an ISO string from JSON), oldest when missing.
    Naive timestamps are UTC, as CKAN writes them."""
    from services.scanner.models import _parse_datetime

    v = resource.get("last_modified")
    if isinstance(v, str):
        v = _parse_datetime(v)
    if not isinstance(v, datetime):
        return datetime.min.replace(tzinfo=timezone.utc)
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def resolve_inputs(
    manifest: RecipeManifest,
    resources: list[dict],
    fields_of,
) -> dict[str, list[dict]]:
    """Map each declared input to the CKAN resources that feed it.

    `resources` is the scanner's `sources/<id>.resources` list;
    `fields_of(resource_id) -> list[str] | None` returns a resource's
    datastore column names (CKAN preview in prod, a stub in tests). Raises
    RecipeError(reason="schema_changed") when the data no longer has the
    shape the recipe was written for — a missing resource, a vanished
    column — so the page is kept and a human re-authors it.
    """
    from services.shared.resources import select_prefetch_resources

    active = select_prefetch_resources(resources or [])
    by_id = {r["id"]: r for r in resources or []}
    out: dict[str, list[dict]] = {}
    for inp in manifest.inputs:
        if inp.snapshot:
            res = by_id.get(inp.by_id)
            why = snapshot_stale(inp, res)
            if why:
                raise RecipeError(
                    f"input {inp.name!r}: map file {inp.by_id} changed since its "
                    f"snapshot ({why}); download it again in a browser and run "
                    "`author snapshot`",
                    reason="geometry_stale",
                )
            out[inp.name] = [res]
            continue
        if inp.by_id:
            res = by_id.get(inp.by_id)
            if res is None or not res.get("datastore_active"):
                raise RecipeError(
                    f"input {inp.name!r}: resource {inp.by_id} is no longer a "
                    "datastore-active resource of this dataset",
                    reason="schema_changed",
                )
            matched = [res]
        else:
            matched = []
            for res in active:
                cols = fields_of(res["id"]) or []
                if set(inp.by_schema or []) <= set(cols):
                    matched.append(res)
            if not matched:
                raise RecipeError(
                    f"input {inp.name!r}: no resource has columns {inp.by_schema}",
                    reason="schema_changed",
                )
            if inp.pick == "latest":
                undated = [r["id"][:8] for r in matched
                           if not by_id.get(r["id"], {}).get("last_modified")]
                if undated:
                    log.warning(
                        "input %r: resource(s) %s have no last_modified; pick 'latest' "
                        "ranks them oldest", inp.name, undated,
                    )
                # max() keeps the first of equal keys, i.e. CKAN order.
                matched = [max(
                    matched, key=lambda r: _modified_key(by_id.get(r["id"], {}))
                )]
        needed = inp.columns_needed
        if needed:
            for res in matched:
                cols = set(fields_of(res["id"]) or [])
                lost = [c for c in needed if c not in cols]
                if lost:
                    raise RecipeError(
                        f"input {inp.name!r}: resource {res['id'][:8]} lost "
                        f"column(s) {lost}",
                        reason="schema_changed",
                    )
        out[inp.name] = matched
    return out


# ── rendering ────────────────────────────────────────────────────────────


def _fmt_int(v: Any) -> str:
    return f"{int(round(float(v))):,}"


def _fmt_num(v: Any, digits: int = 1) -> str:
    return f"{float(v):,.{digits}f}"


def _fmt_pct(v: Any, digits: int = 1) -> str:
    """`v` is a fraction (0.236 → '23.6%')."""
    return f"{float(v) * 100:.{digits}f}%"


def _environment():
    from jinja2 import StrictUndefined
    from jinja2.sandbox import SandboxedEnvironment

    env = SandboxedEnvironment(
        autoescape=True,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    # Jinja's default sorts keys — that would silently reorder any
    # name→series map a chart iterates. Keep compute()'s order; emit
    # Hebrew as-is (htmlsafe still escapes < > & ').
    env.policies["json.dumps_kwargs"] = {"sort_keys": False, "ensure_ascii": False}
    env.filters["fmt_int"] = _fmt_int
    env.filters["fmt_num"] = _fmt_num
    env.filters["fmt_pct"] = _fmt_pct
    return env


def render_template(template_src: str, model: dict, inputs: Optional[dict] = None) -> str:
    """Render a body template against a page model.

    Sandboxed + StrictUndefined: a template that references a key the model
    no longer produces fails loudly instead of rendering an empty chart.
    `| tojson` (jinja builtin) is the only sanctioned way to put data in a
    <script>; it escapes `<`, `>`, `&`, `'` so data can't close the tag.
    `inputs` maps each input name to the resources it resolved to
    (`[{"id", "name", "rows"}]`) — e.g. `inputs.points[0].id` for a
    GovMap resourceId, which compute() never sees.
    """
    try:
        return _environment().from_string(template_src).render(
            model=model, inputs=inputs or {}
        )
    except Exception as e:
        raise RecipeError(f"template render failed: {type(e).__name__}: {e}") from e


def validate_model(raw: dict, manifest: RecipeManifest) -> PageModel:
    try:
        model = PageModel.model_validate(raw)
    except Exception as e:
        raise RecipeError(f"compute() output is not a valid page model: {e}") from e
    if len(model.insights) < manifest.min_insights:
        raise RecipeError(
            f"only {len(model.insights)} insight(s) survived (min_insights="
            f"{manifest.min_insights}) — the data no longer fits the rules",
        )
    ids = [i.id for i in model.insights]
    if len(ids) != len(set(ids)):
        raise RecipeError(f"duplicate insight ids: {ids}")
    return model


# ── template lint ────────────────────────────────────────────────────────

_JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>(.*?)</\1\s*>", re.DOTALL | re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")
_ARIA_RE = re.compile(r'aria-label\s*=\s*"([^"]*)"', re.IGNORECASE)
_DIGIT_RUN_RE = re.compile(r"\d[\d,.:/%-]*")
# Five+ numeric literals in one JS array is a pasted data series, not
# config (grid sizes, font sizes and the like are scalars).
_JS_NUMERIC_ARRAY_RE = re.compile(
    r"\[\s*-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?){4,}\s*\]"
)


def lint_template(template_src: str, allow: list[str] = ()) -> list[str]:
    """Findings that would freeze a number into the page.

    Checks prose text, aria-labels and <script> data. Jinja expressions are
    blanked first, so `{{ model.kpis.total.display }}` is fine and a literal
    `1,695` is not. `allow` lists literal strings that may contain digits.
    """
    findings: list[str] = []
    src = _JINJA_RE.sub(" ", template_src)
    for literal in allow:
        src = src.replace(literal, " ")

    for m in _SCRIPT_STYLE_RE.finditer(src):
        if m.group(1).lower() == "script":
            arr = _JS_NUMERIC_ARRAY_RE.search(m.group(2))
            if arr:
                findings.append(
                    f"TEMPLATE-NUMERIC-LITERAL: <script> holds a literal data "
                    f"array {arr.group(0)[:60]!r} — emit it from compute() via "
                    "`{{ model.charts.<name> | tojson }}`"
                )
    for m in _ARIA_RE.finditer(src):
        d = _DIGIT_RUN_RE.search(m.group(1))
        if d:
            findings.append(
                f"TEMPLATE-NUMERIC-LITERAL: aria-label contains {d.group(0)!r} "
                f"({m.group(1)[:60]!r}) — compute the label in the model"
            )
    text = _TAG_RE.sub(" ", _SCRIPT_STYLE_RE.sub(" ", src))
    for d in _DIGIT_RUN_RE.finditer(text):
        ctx = text[max(0, d.start() - 30): d.end() + 30].strip()
        findings.append(
            f"TEMPLATE-NUMERIC-LITERAL: prose contains {d.group(0)!r} "
            f"(…{ctx}…) — every number must come from the model, or be "
            "listed in recipe.json lint_allow_numbers"
        )
    return findings


# ── KPI card format ──────────────────────────────────────────────────────
# Published look: a bare number in a dir="ltr" box (real minus U+2212, no
# bidi-isolate characters), units in the label below, colour from a
# data-driven tone. Hebrew in the value is limited to a short magnitude
# suffix (מ׳, אלף). Shared by `author verify` (fails) and the nightly
# refresh (reported), since a display can drift with the data.
_KPI_VALUE_RE = re.compile(
    r'<div\b([^>]*\bclass="(?=[^"]*\btext-(?:xl|[2-5]xl)\b)(?=[^"]*\bfont-bold\b)'
    r'[^"]*"[^>]*)>(.*?)</div>',
    re.DOTALL,
)
_KPI_TONE_RE = re.compile(r"\btext-(?:brand|ok|warn|info|danger)\b")
_HEB_WORD_RE = re.compile(r"[א-ת][א-ת׳״\"']*")


def kpi_format_findings(html: str) -> list[str]:
    out = []
    for m in _KPI_VALUE_RE.finditer(html):
        attrs, value = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        where = f"KPI {value[:30]!r}"
        # A bare count reads fine either way; a sign, range, ratio or time
        # does not ("2014–2026" displays reversed in an RTL paragraph).
        if re.search(r"[−\-–+/:]", value) and 'dir="ltr"' not in attrs:
            out.append(f'KPI-FORMAT: {where} needs dir="ltr" on the value box')
        if not _KPI_TONE_RE.search(attrs):
            out.append(f"KPI-FORMAT: {where} colour must be one of text-brand, "
                       "text-ok, text-warn, text-info, text-danger")
        if re.search("[⁦-⁩‎‏]", value):
            out.append(f'KPI-FORMAT: {where} contains bidi marks — dir="ltr" handles direction')
        if re.search(r"(?<![\w.])-\d", value):
            out.append(f"KPI-FORMAT: {where} uses '-' — use the minus sign '−' (U+2212)")
        words = _HEB_WORD_RE.findall(value)
        if len(words) > 1 or any(len(w.strip("׳״\"'")) > 3 for w in words) or "₪" in value:
            out.append(f"KPI-FORMAT: {where} carries a unit/word — keep the number bare "
                       "(a short suffix like מ׳ is fine) and put units in the label")
    return out


def dump_model(model: dict) -> str:
    """Canonical JSON for determinism comparisons."""
    return json.dumps(model, ensure_ascii=False, sort_keys=True, allow_nan=False)
