"""Recipe contract — the deterministic replacement for per-update agent runs.

A recipe is authored ONCE per dataset (locally, with Claude Code — see
`.claude/skills/author-dataset/SKILL.md`) and then re-run, with no LLM, every
time CKAN publishes a new version of the dataset. It lives in
`recipes/<dataset_id>/`:

    recipe.json        RecipeManifest — inputs, version, insight floor
    compute.py         compute(frames) -> page model (pure: no network,
                       no clock, no randomness)
    template.html.j2   Jinja2 body template rendered from the page model

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
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import AgentData

CONTRACT_VERSION = 1
MANIFEST_FILENAME = "recipe.json"
COMPUTE_FILENAME = "compute.py"
TEMPLATE_FILENAME = "template.html.j2"
RECIPE_FILES = (MANIFEST_FILENAME, COMPUTE_FILENAME, TEMPLATE_FILENAME)

# Column added to every row of a `concat` input.
RESOURCE_NAME_COLUMN = "_resource_name"


class RecipeError(RuntimeError):
    """A recipe could not produce a valid page from the current data.

    `reason` is the authoring-queue reason the failure maps to
    (`recipe_failed` / `schema_changed`) — what the human re-authoring the
    dataset needs to know first.
    """

    def __init__(self, message: str, *, reason: str = "recipe_failed"):
        super().__init__(message)
        self.reason = reason


class RecipeInput(BaseModel):
    """One logical table the recipe consumes.

    Exactly one selector:
      - `by_id`: a single CKAN resource id. Use when the dataset has one
        stable data file.
      - `by_schema`: every datastore-active resource whose columns include
        all of these. Use for datasets that add a file per period (a new
        yearly CSV) — the new file is picked up automatically. Pair with
        `concat: true`.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    by_id: Optional[str] = None
    by_schema: Optional[list[str]] = None
    concat: bool = False
    required_columns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_selector(self) -> "RecipeInput":
        if bool(self.by_id) == bool(self.by_schema):
            raise ValueError(f"input {self.name!r}: set exactly one of by_id / by_schema")
        if self.by_schema and not self.concat:
            raise ValueError(f"input {self.name!r}: by_schema requires concat: true")
        return self

    @property
    def columns_needed(self) -> list[str]:
        return list(dict.fromkeys([*(self.by_schema or []), *self.required_columns]))


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

    @model_validator(mode="after")
    def _unique_names(self) -> "RecipeManifest":
        names = [i.name for i in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("input names must be unique")
        return self


class Kpi(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: Any = None
    display: str


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
        return cls(root, manifest)


# ── input resolution ─────────────────────────────────────────────────────


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


def dump_model(model: dict) -> str:
    """Canonical JSON for determinism comparisons."""
    return json.dumps(model, ensure_ascii=False, sort_keys=True, allow_nan=False)
