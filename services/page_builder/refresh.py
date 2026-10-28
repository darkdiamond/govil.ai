"""Deterministic page refresh — re-run a dataset's recipe on fresh data.

No LLM anywhere in this module. Per source with a recipe whose CKAN version
(or recipe version) moved past what was last rendered:

    resolve inputs → full CKAN fetch → compute() in a LocalSandbox
    → validate page model → render template → sanitize → check.py
    → stage content.html to GCS → write agent_data + refresh state

A failure keeps the last-good page live (nothing is staged), records why,
and — when a human has to act (recipe broke, schema moved, data outgrew
the fetch cap) — opens a `needs-authoring` GitHub issue. A transient fetch
failure just retries on the next run.

Two targets share every step and differ only in where results land:
    prod     `sources/<id>` + gs://<staging>/datasets/<id>/content.html
    preview  `preview_sources/<id>` + gs://<staging>/preview/datasets/…
             (`sources/*` is read, never written — the demo lane)

CLI (what the preview Cloud Run job runs; also handy locally):
    python -m services.page_builder.refresh run --target preview
    python -m services.page_builder.refresh run --source <id> --no-publish
    python -m services.page_builder.refresh overlay --out frontend/public/
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from .agent_contract import (
    ResourceRestrictedError,
    fetch_resource_preview,
    fetch_resource_records_to_file,
    run_host_check,
    sanitize_content_html,
)
from .local_sandbox import LocalSandbox
from .recipe import (
    MANIFEST_FILENAME,
    RECIPE_FILES,
    Recipe,
    RecipeError,
    kpi_format_findings,
    render_template,
    resolve_inputs,
    validate_model,
)

log = logging.getLogger("page_builder.refresh")

CONTENT_FILENAME = "content.html"
RECIPE_EXEC_PATH = Path(__file__).resolve().parent / "recipe_exec.py"

# Refresh fetches FULL data — a sampled frame would silently change what
# every number means. No LLM context to protect, so the caps are about
# container memory and CKAN politeness only.
_DEFAULT_MAX_RECORDS = 2_000_000
_DEFAULT_MAX_BYTES = 300_000_000
_DEFAULT_TOTAL_BYTES = 600_000_000
_DEFAULT_WALL_BUDGET_S = 900.0
_DEFAULT_PAGE_SIZE = 25_000
_PAGE_TIMEOUT_S = 60.0
_COMPUTE_TIMEOUT_S = 300
# Sandbox-spawn flake (gRPC atfork handlers abort the forked child, SIGABRT
# + an `ev_epoll1_linux` line on stderr): not the recipe's fault, so retry
# in a fresh sandbox instead of opening an authoring issue.
_COMPUTE_SPAWN_ATTEMPTS = 2
_COMPUTE_SPAWN_BACKOFF_S = 1.0

# Failure reasons a human must act on → open an authoring issue. Anything
# else (`fetch_failed`) is transient and simply retried next run.
AUTHORING_REASONS = ("recipe_failed", "schema_changed", "too_large")


def _clip(msg: str, head: int = 150, tail: int = 450) -> str:
    """Keep what a traceback is about (head) AND where it ended (tail)."""
    return msg if len(msg) <= head + tail else f"{msg[:head]} … {msg[-tail:]}"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# No-op precheck (REFRESH_PRECHECK): CKAN bumps `metadata_modified` on every
# re-upload, including byte-identical ones. Two checks run before the recipe:
#   A  fingerprint — the datastore preview already fetched to resolve inputs
#      (row total, columns, first rows) + the recipe's own files. Costs no
#      extra CKAN call; blind to same-count edits deeper in the table.
#   B  inputs hash — sha256 of the exported CSVs + recipe files. Exact.
#   A′ file fingerprint — CKAN's md5 of each input's uploaded file (`hash`
#      from package_show, already on the source doc) + the preview's total and
#      columns. No extra call; catches same-count edits A can't. Blind to
#      datastore-only edits. Observed only, never skips: it's on trial against
#      B as A's replacement.
# off      today's behaviour
# observe  compute A/A′/B and report agreement with the rendered output; never skip
# inputs   skip on B (A observed)
# full     skip on A, else fetch and skip on B
PRECHECK_MODES = ("off", "observe", "inputs", "full")
_DEFAULT_PRECHECK_MAX_AGE_DAYS = 14


def precheck_mode() -> str:
    mode = os.environ.get("REFRESH_PRECHECK", "off").strip().lower()
    return mode if mode in PRECHECK_MODES else "off"


# ── recipe repositories ──────────────────────────────────────────────────


class LocalRecipeRepo:
    """Recipes from a directory (the repo's `recipes/`, or a test fixture)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def list_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            p.name for p in self.root.iterdir() if (p / MANIFEST_FILENAME).is_file()
        )

    def load(self, dataset_id: str, scratch: Path) -> Recipe:
        return Recipe.load(self.root / dataset_id)


class GcsRecipeRepo:
    """Recipes uploaded to gs://<bucket>/<prefix><id>/ — the preview lane
    (`infra/refresh-preview.deploy.sh sync-recipes`)."""

    def __init__(self, bucket: str, prefix: str = "recipes/"):
        from google.cloud import storage

        self._bucket = storage.Client().bucket(bucket)
        self.prefix = prefix if prefix.endswith("/") else prefix + "/"

    def list_ids(self) -> list[str]:
        ids = set()
        for blob in self._bucket.client.list_blobs(self._bucket, prefix=self.prefix):
            rel = blob.name[len(self.prefix):]
            parts = rel.split("/")
            if len(parts) == 2 and parts[1] == MANIFEST_FILENAME:
                ids.add(parts[0])
        return sorted(ids)

    def load(self, dataset_id: str, scratch: Path) -> Recipe:
        dest = scratch / dataset_id
        dest.mkdir(parents=True, exist_ok=True)
        for name in RECIPE_FILES:
            blob = self._bucket.blob(f"{self.prefix}{dataset_id}/{name}")
            if not blob.exists():
                raise RecipeError(f"recipe {dataset_id} missing {name} in GCS")
            blob.download_to_filename(str(dest / name))
        return Recipe.load(dest)


class GithubRecipeRepo:
    """Recipes read straight from git — `recipes/` at a branch of the
    (public) repo. Production's source of truth: merging a recipe PR is what
    puts a dataset on the recipe list, with no sync step or write grant.

    The branch is resolved to one commit per run (git trees API), and every
    file is fetched at that commit, so a merge landing mid-run can't mix
    two versions of a recipe.
    """

    def __init__(self, repo: str, ref: str = "main", token: Optional[str] = None):
        self.repo, self.ref = repo, ref
        self._headers = {"Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._sha: Optional[str] = None
        self._ids: Optional[list[str]] = None

    def _get(self, url: str, **kw):
        import httpx

        r = httpx.get(url, headers=self._headers, timeout=30.0,
                      follow_redirects=True, **kw)
        r.raise_for_status()
        return r

    def list_ids(self) -> list[str]:
        if self._ids is None:
            sha = self._get(
                f"https://api.github.com/repos/{self.repo}/commits/{self.ref}"
            ).json()["sha"]
            tree = self._get(
                f"https://api.github.com/repos/{self.repo}/git/trees/{sha}",
                params={"recursive": "1"},
            ).json()
            if tree.get("truncated"):
                raise RuntimeError("git tree listing truncated — recipe list incomplete")
            ids = set()
            for node in tree.get("tree") or []:
                parts = node.get("path", "").split("/")
                if len(parts) == 3 and parts[0] == "recipes" and parts[2] == MANIFEST_FILENAME:
                    ids.add(parts[1])
            self._sha, self._ids = sha, sorted(ids)
        return list(self._ids)

    def load(self, dataset_id: str, scratch: Path) -> Recipe:
        if self._sha is None:
            self.list_ids()
        dest = scratch / dataset_id
        dest.mkdir(parents=True, exist_ok=True)
        for name in RECIPE_FILES:
            r = self._get(
                f"https://raw.githubusercontent.com/{self.repo}/{self._sha}/"
                f"recipes/{dataset_id}/{name}"
            )
            (dest / name).write_bytes(r.content)
        return Recipe.load(dest)


def recipe_repo_from_env() -> LocalRecipeRepo | GcsRecipeRepo | GithubRecipeRepo:
    """RECIPES_SOURCE:
      github:<owner/repo>@<ref>   (default: PUBLISH_GITHUB_REPO @ main)
      gs://bucket/prefix/         (the preview lane's uploaded demo recipes)
      a local directory           (tests, local runs)
    """
    src = os.environ.get("RECIPES_SOURCE", "").strip()
    if not src:
        src = "github:{}@main".format(
            os.environ.get("PUBLISH_GITHUB_REPO", "darkdiamond/govil.ai")
        )
    if src.startswith("github:"):
        repo, _, ref = src[len("github:"):].partition("@")
        return GithubRecipeRepo(
            repo, ref or "main",
            token=os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip() or None,
        )
    if src.startswith("gs://"):
        bucket, _, prefix = src[len("gs://"):].partition("/")
        return GcsRecipeRepo(bucket, prefix or "recipes/")
    return LocalRecipeRepo(Path(src))


# ── fetch ────────────────────────────────────────────────────────────────


@dataclass
class FetchedInput:
    file: Path
    resource_id: str
    resource_name: str
    rows: int


@dataclass
class InputProbe:
    """Inputs resolved against CKAN + the datastore previews that resolution
    needed. `fetch_inputs` reuses it, so probing for the precheck adds no
    CKAN calls."""

    resolved: dict[str, list[dict]]
    _previews: dict[str, Optional[dict]]
    _preview_fn: Callable[[str], Optional[dict]]

    def preview(self, rid: str) -> Optional[dict]:
        if rid not in self._previews:
            self._previews[rid] = self._preview_fn(rid)
        return self._previews[rid]


def probe_inputs(
    recipe: Recipe,
    resources: list[dict],
    preview_fn: Callable[[str], Optional[dict]] = fetch_resource_preview,
) -> InputProbe:
    """Resolve the recipe's inputs. Raises RecipeError `schema_changed` when
    they no longer resolve; ResourceRestrictedError passes through."""
    previews: dict[str, Optional[dict]] = {}
    probe = InputProbe({}, previews, preview_fn)

    def _fields(rid: str) -> Optional[list[str]]:
        p = probe.preview(rid)
        return [f["id"] for f in (p or {}).get("fields") or []] if p else None

    probe.resolved = resolve_inputs(recipe.manifest, resources, _fields)
    return probe


# Shared code between the data and the page: the compute runner, template
# rendering/validation, the sanitizer. A deploy that changes any of them can
# change the output with identical data, so it invalidates both prechecks.
_RENDER_CODE_FILES = (
    RECIPE_EXEC_PATH,
    Path(__file__).resolve().parent / "recipe.py",
    Path(__file__).resolve().parent / "agent_contract.py",
)


@functools.lru_cache(maxsize=1)
def _render_code_hash() -> str:
    h = hashlib.sha256()
    for path in _RENDER_CODE_FILES:
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def recipe_identity(recipe: Recipe) -> str:
    """The recipe's code + template + the shared render code. Folded into both
    prechecks so an edited recipe that kept its `recipe_version`, or a deploy
    that changed rendering, still re-renders."""
    h = hashlib.sha256()
    for name in RECIPE_FILES:
        h.update(name.encode())
        h.update(b"\0")
        h.update((recipe.root / name).read_bytes())
        h.update(b"\0")
    h.update(_render_code_hash().encode())
    return h.hexdigest()


def input_fingerprint(recipe: Recipe, probe: InputProbe, identity: str) -> str:
    """Check A: what the datastore preview says about every input — row total,
    columns, first rows (`_id` dropped) — plus `recipe_identity`."""
    parts = []
    for inp in recipe.manifest.inputs:
        for res in probe.resolved[inp.name]:
            p = probe.preview(res["id"]) or {}
            parts.append(
                [
                    inp.name,
                    res["id"],
                    p.get("total"),
                    [[f.get("id"), f.get("type")] for f in p.get("fields") or []],
                    [
                        {k: v for k, v in row.items() if k != "_id"}
                        for row in p.get("sample_rows") or []
                    ],
                ]
            )
    h = hashlib.sha256()
    h.update(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode())
    h.update(identity.encode())
    return h.hexdigest()


def file_fingerprint(recipe: Recipe, probe: InputProbe, identity: str) -> Optional[str]:
    """Check A′: CKAN's md5 + size of every input's uploaded file, the
    preview's row total and columns, plus `recipe_identity`. None when any
    input has no CKAN hash (API-pushed resource, or a source doc scanned before
    the scanner kept it) — it never vouches for an input it can't see."""
    parts = []
    for inp in recipe.manifest.inputs:
        for res in probe.resolved[inp.name]:
            if not res.get("hash"):
                return None
            p = probe.preview(res["id"]) or {}
            parts.append(
                [
                    inp.name,
                    res["id"],
                    res["hash"],
                    res.get("size"),
                    p.get("total"),
                    [[f.get("id"), f.get("type")] for f in p.get("fields") or []],
                ]
            )
    h = hashlib.sha256()
    h.update(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode())
    h.update(identity.encode())
    return h.hexdigest()


def inputs_hash(
    recipe: Recipe, inputs: dict[str, list["FetchedInput"]], identity: str
) -> str:
    """Check B: exact — the exported CSVs (deterministic: datastore order,
    `_id` dropped, schema field order) + `recipe_identity`."""
    h = hashlib.sha256()
    for inp in recipe.manifest.inputs:
        for part in inputs.get(inp.name, []):
            h.update(f"{inp.name}|{part.resource_id}|".encode())
            with open(part.file, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            h.update(b"\0")
    h.update(identity.encode())
    return h.hexdigest()


def content_hash(page: "RenderedPage") -> str:
    h = hashlib.sha256()
    h.update(page.content_html.encode("utf-8"))
    h.update(b"\0")
    h.update(
        json.dumps(page.agent_data, ensure_ascii=False, sort_keys=True, default=str).encode()
    )
    return h.hexdigest()


def fetch_inputs(
    recipe: Recipe,
    resources: list[dict],
    dest_dir: Path,
    *,
    preview_fn: Callable[[str], Optional[dict]] = fetch_resource_preview,
    fetch_fn: Callable = fetch_resource_records_to_file,
    probe: Optional[InputProbe] = None,
) -> dict[str, list[FetchedInput]]:
    """Full export of every resource the recipe reads, as CSV in `dest_dir`.

    Raises RecipeError: `schema_changed` (inputs no longer resolve),
    `too_large` (over REFRESH_MAX_RECORDS — sampling is never an option
    here), `fetch_failed` (CKAN/network; transient).

    `probe` (from `probe_inputs`) skips the resolve + preview calls already made.
    """
    probe = probe or probe_inputs(recipe, resources, preview_fn)
    _preview = probe.preview
    resolved = probe.resolved

    max_records = _env_int("REFRESH_MAX_RECORDS", _DEFAULT_MAX_RECORDS)
    max_bytes = _env_int("REFRESH_MAX_BYTES", _DEFAULT_MAX_BYTES)
    remaining = _env_int("REFRESH_TOTAL_BYTES", _DEFAULT_TOTAL_BYTES)
    page_size = _env_int("REFRESH_PAGE_SIZE", _DEFAULT_PAGE_SIZE)
    deadline = time.monotonic() + float(
        _env_int("REFRESH_WALL_BUDGET_S", int(_DEFAULT_WALL_BUDGET_S))
    )

    dest_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[FetchedInput]] = {}
    for inp in recipe.manifest.inputs:
        parts: list[FetchedInput] = []
        for i, res in enumerate(resolved[inp.name]):
            rid = res["id"]
            total = int((_preview(rid) or {}).get("total") or 0)
            if total <= 0:
                raise RecipeError(
                    f"input {inp.name!r}: resource {rid[:8]} has no rows",
                    reason="fetch_failed",
                )
            if total > max_records:
                raise RecipeError(
                    f"input {inp.name!r}: {total:,} rows > REFRESH_MAX_RECORDS "
                    f"{max_records:,}",
                    reason="too_large",
                )
            dest = dest_dir / f"{inp.name}__{i + 1}.csv"
            outcome = fetch_fn(
                rid,
                total,
                dest,
                max_bytes=min(max_bytes, remaining),
                page_size=page_size,
                page_timeout_s=_PAGE_TIMEOUT_S,
                deadline=deadline,
                sample_target_rows=0,
                prefer_sample=False,
            )
            if outcome is None or outcome.mode != "full":
                raise RecipeError(
                    f"input {inp.name!r}: full fetch of {rid[:8]} failed "
                    "(network, wall budget or byte cap)",
                    reason="fetch_failed",
                )
            remaining -= outcome.bytes
            parts.append(
                FetchedInput(dest, rid, res.get("name") or "", outcome.rows)
            )
        out[inp.name] = parts
    return out


# ── compute + render ─────────────────────────────────────────────────────


class _SpawnFlake(RecipeError):
    """compute() died to the known fork/gRPC abort, not to recipe code."""


def _is_spawn_flake(error_value: str, stderr: str) -> bool:
    return error_value == "exit code -6" and "ev_epoll1_linux" in stderr


def run_compute(
    recipe: Recipe,
    inputs: dict[str, list[FetchedInput]],
    work_root: Path,
    *,
    timeout: int = _COMPUTE_TIMEOUT_S,
) -> dict:
    """`_run_compute_once`, retried on the known sandbox-spawn flake only.

    Every other failure (recipe exceptions, timeouts, a bare SIGABRT
    without the gRPC signature) surfaces immediately.
    """
    for attempt in range(1, _COMPUTE_SPAWN_ATTEMPTS):
        try:
            return _run_compute_once(recipe, inputs, work_root, timeout=timeout)
        except _SpawnFlake as e:
            log.warning(
                "compute() spawn flake for %s (attempt %d/%d), retrying: %s",
                recipe.dataset_id,
                attempt,
                _COMPUTE_SPAWN_ATTEMPTS,
                str(e)[:200],
            )
            time.sleep(_COMPUTE_SPAWN_BACKOFF_S)
    return _run_compute_once(recipe, inputs, work_root, timeout=timeout)


def _run_compute_once(
    recipe: Recipe,
    inputs: dict[str, list[FetchedInput]],
    work_root: Path,
    *,
    timeout: int = _COMPUTE_TIMEOUT_S,
) -> dict:
    """Execute compute.py in a fresh LocalSandbox; return the raw model.

    Recipe code is reviewed (it arrives by PR) but still runs with agent-
    tool isolation: scrubbed env, unprivileged uid in the container,
    wall-clock timeout, output read back through the untrusted-read path.
    """
    work_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=f"{recipe.dataset_id[:8]}-recipe-", dir=work_root))
    sandbox = LocalSandbox.create(workdir)
    try:
        (workdir / "recipe").mkdir()
        for name in RECIPE_FILES:
            shutil.copyfile(recipe.root / name, workdir / "recipe" / name)
        shutil.copyfile(RECIPE_EXEC_PATH, workdir / "recipe_exec.py")
        (workdir / "data").mkdir()
        spec: dict[str, list[dict]] = {}
        input_concat = {i.name: i.concat for i in recipe.manifest.inputs}
        for name, parts in inputs.items():
            spec[name] = []
            for p in parts:
                target = workdir / "data" / p.file.name
                try:
                    os.link(p.file, target)
                except OSError:
                    shutil.copyfile(p.file, target)
                spec[name].append(
                    {
                        "file": f"data/{p.file.name}",
                        "resource_name": p.resource_name,
                        "concat": input_concat.get(name, False),
                    }
                )
        (workdir / "inputs.json").write_text(
            json.dumps(spec, ensure_ascii=False), encoding="utf-8"
        )
        execution = sandbox.run_code(
            "import runpy; runpy.run_path('recipe_exec.py', run_name='__main__')",
            language="python",
            timeout=timeout,
        )
        if execution.error is not None:
            stderr = (execution.logs.stderr or "").strip()
            exc = (
                _SpawnFlake
                if _is_spawn_flake(execution.error.value, stderr)
                else RecipeError
            )
            raise exc(
                f"compute() failed ({execution.error.name}: {execution.error.value}): "
                f"{stderr[-1500:]}"
            )
        try:
            raw = sandbox.files.read("outputs/model.json")
        except FileNotFoundError as e:
            raise RecipeError(f"compute() wrote no model: {e}") from e
        return json.loads(raw.decode("utf-8"))
    finally:
        sandbox.kill()


@dataclass
class RenderedPage:
    content_html: str
    agent_data: dict
    model: dict
    # Cosmetic drift (KPI format) reported, not fatal: the page is correct,
    # just not in house style, and failing the refresh would freeze data.
    warnings: list = field(default_factory=list)


def inputs_context(inputs: dict[str, list[FetchedInput]]) -> dict:
    return {
        name: [{"id": p.resource_id, "name": p.resource_name, "rows": p.rows} for p in parts]
        for name, parts in inputs.items()
    }


def render_page(
    recipe: Recipe,
    raw_model: dict,
    check_root: Path,
    inputs: Optional[dict[str, list[FetchedInput]]] = None,
) -> RenderedPage:
    """Model → validated body. Same gates an agent page passed: sanitizer,
    then the image's check.py on the sanitized output."""
    model = validate_model(raw_model, recipe.manifest)
    agent_data = model.agent_data.model_dump(mode="json", exclude_none=True)
    template_src = recipe.template_path.read_text(encoding="utf-8")
    # The template sees exactly what compute() returned (extras included).
    html = render_template(template_src, raw_model, inputs_context(inputs or {}))
    html = sanitize_content_html(html, dataset_id=recipe.dataset_id)
    check_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="check-", dir=check_root) as d:
        try:
            run_host_check(
                html, json.dumps(agent_data, ensure_ascii=False), Path(d), recipe=True
            )
        except RuntimeError as e:
            raise RecipeError(str(e)) from e
    return RenderedPage(
        content_html=html, agent_data=agent_data, model=raw_model,
        warnings=kpi_format_findings(html),
    )


def build_page(
    recipe: Recipe,
    resources: list[dict],
    work_root: Path,
    *,
    probe: Optional[InputProbe] = None,
    after_fetch: Optional[Callable[[dict[str, list[FetchedInput]]], None]] = None,
    **fetch_kwargs,
) -> tuple[RenderedPage, dict[str, list[FetchedInput]]]:
    """fetch → compute → render, in a scratch dir under `work_root`.

    `after_fetch(inputs)` runs between fetch and compute — the precheck's
    exact input-hash gate raises `_Unchanged` from it to stop before compute."""
    data_dir = Path(tempfile.mkdtemp(prefix=f"{recipe.dataset_id[:8]}-data-", dir=work_root))
    try:
        inputs = fetch_inputs(recipe, resources, data_dir, probe=probe, **fetch_kwargs)
        if after_fetch is not None:
            after_fetch(inputs)
        raw = run_compute(recipe, inputs, work_root)
        return render_page(recipe, raw, work_root, inputs), inputs
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


# ── selection + orchestration ────────────────────────────────────────────


def version_key(metadata_modified: Optional[datetime], recipe_version: int) -> str:
    mm = metadata_modified.isoformat() if metadata_modified else "none"
    return f"{mm}|v{recipe_version}"


def needs_refresh(src, state: dict, recipe: Recipe) -> Optional[str]:
    """Why this source should be refreshed now, or None to skip it."""
    if src is None:
        return None
    if src.analysis_status in ("unavailable", "restricted"):
        return None  # data gone upstream; keep the frozen page
    rv = recipe.manifest.recipe_version
    key = version_key(src.metadata_modified, rv)
    if state.get("refresh_failed_version") == key and state.get(
        "refresh_reason"
    ) in AUTHORING_REASONS:
        return None  # same data + same recipe would fail the same way
    if state.get("recipe_version") != rv:
        return "recipe_version"
    done = state.get("refreshed_metadata_modified")
    if done is None:
        return "never_refreshed"
    if src.metadata_modified and src.metadata_modified > done:
        return "data_updated"
    return None


def _write_gcs(data: bytes, bucket: str, relpath: str) -> str:
    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(relpath)
    blob.upload_from_string(data, content_type="text/html; charset=utf-8")
    return f"gs://{bucket}/{relpath}"


@dataclass
class RefreshOutcome:
    id: str
    status: str                      # refreshed | unchanged | failed | skipped
    trigger: Optional[str] = None
    reason: Optional[str] = None
    error: Optional[str] = None
    elapsed_s: float = 0.0
    rows: dict = field(default_factory=dict)
    kpis: dict = field(default_factory=dict)
    insights: list = field(default_factory=list)
    changes: dict = field(default_factory=dict)
    issue: Optional[int] = None
    # REFRESH_PRECHECK report: {mode, fp_same, inputs_same, content_same, skipped}
    # (True/False; None = no stored hash to compare against yet).
    precheck: dict = field(default_factory=dict)


class _Unchanged(Exception):
    """Precheck proved the inputs identical to the last render — stop before
    the expensive steps. `reason` is `fingerprint` or `inputs_hash`."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _precheck_may_skip(trigger: str, state: dict) -> bool:
    """Skipping is only safe for a plain data bump on a recently re-rendered
    page: a forced run, a recipe_version change, or a page older than
    REFRESH_PRECHECK_MAX_AGE_DAYS (bounds check A's blind spot and picks up
    shell-code changes that alter output without any data change) always
    re-render."""
    if trigger != "data_updated":
        return False
    last = state.get("last_refreshed_at")
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    max_age = _env_int("REFRESH_PRECHECK_MAX_AGE_DAYS", _DEFAULT_PRECHECK_MAX_AGE_DAYS)
    return datetime.now(timezone.utc) - last <= timedelta(days=max_age)


def _same(new: str, old: Optional[str]) -> Optional[bool]:
    return None if old is None else new == old


def refresh_one(
    src,
    recipe: Recipe,
    *,
    store,
    preview: bool,
    staging_bucket: str,
    work_root: Path,
    trigger: str,
    previous_state: Optional[dict] = None,
    notify: bool = True,
    write_gcs: Callable[[bytes, str, str], str] = _write_gcs,
    **fetch_kwargs,
) -> RefreshOutcome:
    started = time.monotonic()
    rv = recipe.manifest.recipe_version
    mode = precheck_mode()
    state = previous_state or {}
    may_skip = mode != "off" and _precheck_may_skip(trigger, state)
    pc: dict = {"mode": mode} if mode != "off" else {}
    hashes: dict[str, Optional[str]] = {}  # stored on success; names match mark_refreshed kwargs
    try:
        probe = None
        after_fetch = None
        if mode != "off":
            identity = recipe_identity(recipe)
            probe = probe_inputs(
                recipe, src.resources, fetch_kwargs.get("preview_fn", fetch_resource_preview)
            )
            fp = hashes["input_fingerprint"] = input_fingerprint(recipe, probe, identity)
            pc["fp_same"] = _same(fp, state.get("input_fingerprint"))
            ff = hashes["file_fingerprint"] = file_fingerprint(recipe, probe, identity)
            pc["fp2_same"] = _same(ff, state.get("file_fingerprint")) if ff else None
            if may_skip and mode == "full" and pc["fp_same"]:
                raise _Unchanged("fingerprint")

            def after_fetch(inputs):
                ih = hashes["inputs_hash"] = inputs_hash(recipe, inputs, identity)
                pc["inputs_same"] = _same(ih, state.get("inputs_hash"))
                if may_skip and mode in ("inputs", "full") and pc["inputs_same"]:
                    raise _Unchanged("inputs_hash")

        page, inputs = build_page(
            recipe, src.resources, work_root,
            probe=probe, after_fetch=after_fetch, **fetch_kwargs,
        )
    except _Unchanged as u:
        # Same inputs + same recipe ⇒ same page: keep the live one and report
        # `unchanged` (never triggers a publish). Only the exact check (B)
        # advances the version marker. After a fingerprint skip the bump stays
        # pending, so it is re-probed each run (one cheap preview call) until
        # the max age forces a real render. That is what bounds A's blind spot
        # even when CKAN never bumps the dataset again.
        pc["skipped"] = u.reason
        store.mark_refresh_unchanged(
            src.id,
            metadata_modified=src.metadata_modified,
            input_fingerprint=hashes["input_fingerprint"],
            inputs_hash=hashes.get("inputs_hash"),
            file_fingerprint=hashes.get("file_fingerprint"),
            reason=u.reason,
            advance_version=u.reason == "inputs_hash",
            preview=preview,
        )
        log.info("refresh precheck %s: unchanged (%s) — skipped", src.id[:8], u.reason)
        return RefreshOutcome(
            src.id, "unchanged", trigger, u.reason,
            elapsed_s=round(time.monotonic() - started, 2), precheck=pc,
        )
    except ResourceRestrictedError as e:
        # Data went private upstream. Not the recipe's fault, not
        # actionable by re-authoring; the reconcile sweep owns this state.
        log.warning("refresh %s: restricted upstream: %s", src.id[:8], e)
        return RefreshOutcome(src.id, "failed", trigger, "restricted", str(e))
    except RecipeError as e:
        log.warning("refresh %s failed (%s): %s", src.id[:8], e.reason, e)
        store.mark_refresh_failed(
            src.id,
            error=str(e),
            reason=e.reason,
            failed_version=version_key(src.metadata_modified, rv),
            preview=preview,
        )
        outcome = RefreshOutcome(
            src.id, "failed", trigger, e.reason, _clip(str(e)),
            round(time.monotonic() - started, 2),
        )
        if notify and e.reason in AUTHORING_REASONS:
            outcome.issue = queue_authoring(
                store, src, e.reason, detail=str(e), preview=preview
            )
        return outcome
    except Exception as e:  # infra bug, not a data/recipe verdict
        log.exception("refresh %s crashed", src.id[:8])
        store.mark_refresh_failed(
            src.id,
            error=f"{type(e).__name__}: {e}",
            reason="error",
            failed_version=version_key(src.metadata_modified, rv),
            preview=preview,
        )
        return RefreshOutcome(src.id, "failed", trigger, "error", _clip(str(e)))

    snapshot = {
        "rows": {k: sum(p.rows for p in v) for k, v in inputs.items()},
        "kpis": {
            k: (v or {}).get("display") for k, v in (page.model.get("kpis") or {}).items()
        },
        "insights": [i.get("text_he") for i in page.model.get("insights") or []],
        "warnings": page.warnings,
    }
    if page.warnings:
        log.warning("refresh %s: %d format warning(s): %s", src.id[:8],
                    len(page.warnings), "; ".join(page.warnings)[:500])
    previous = state.get("last_snapshot")
    if mode != "off":
        ch = hashes["content_hash"] = content_hash(page)
        pc["content_same"] = _same(ch, state.get("content_hash"))
        _log_precheck(src.id, pc)
    prefix = "preview/datasets" if preview else "datasets"
    write_gcs(
        page.content_html.encode("utf-8"),
        staging_bucket,
        f"{prefix}/{src.id}/{CONTENT_FILENAME}",
    )
    store.mark_refreshed(
        src.id,
        metadata_modified=src.metadata_modified,
        recipe_version=rv,
        agent_data=page.agent_data,
        page_path=f"datasets/{src.id}/",
        snapshot=snapshot,
        preview=preview,
        **hashes,
    )
    return RefreshOutcome(
        src.id,
        "refreshed",
        trigger,
        elapsed_s=round(time.monotonic() - started, 2),
        rows=snapshot["rows"],
        kpis=snapshot["kpis"],
        insights=snapshot["insights"],
        changes=snapshot_diff(previous, snapshot),
        precheck=pc,
    )


def _log_precheck(dataset_id: str, pc: dict) -> None:
    """One line per refreshed source: did the cheap checks agree with the
    rendered output? A "same" check with changed content is a false skip
    (`full`/`inputs` would have kept a stale page) — the rollout gate."""
    log.info(
        "refresh precheck %s: mode=%s fp_same=%s inputs_same=%s content_same=%s"
        " fp2_same=%s",
        dataset_id[:8], pc.get("mode"), pc.get("fp_same"),
        pc.get("inputs_same"), pc.get("content_same"), pc.get("fp2_same"),
    )
    if pc.get("content_same") is False:
        for check in ("fp_same", "inputs_same", "fp2_same"):
            if pc.get(check):
                log.warning(
                    "refresh precheck %s: FALSE-SKIP candidate — %s but the page changed",
                    dataset_id[:8], check,
                )


def snapshot_diff(before: Optional[dict], after: dict) -> dict:
    """What moved since the last successful render — the daily "did the
    numbers change, and did the wording follow" view of the demo soak."""
    if not before:
        return {"first_refresh": True}
    old_k, new_k = before.get("kpis") or {}, after.get("kpis") or {}
    old_i, new_i = before.get("insights") or [], after.get("insights") or []
    return {
        "rows": [before.get("rows"), after.get("rows")],
        "kpis_changed": {k: [old_k.get(k), v] for k, v in new_k.items() if old_k.get(k) != v},
        "insights_added": [t for t in new_i if t not in old_i],
        "insights_removed": [t for t in old_i if t not in new_i],
    }


def queue_authoring(store, src, reason: str, *, detail: str = "", preview: bool = False) -> Optional[int]:
    """Flag a dataset for local authoring and open its issue (once)."""
    from . import notify as _notify

    state = store.get_refresh_state(src.id, preview=preview)
    store.mark_authoring_needed(src.id, reason, preview=preview)
    if state.get("authoring_issue"):
        return int(state["authoring_issue"])
    number = _notify.open_authoring_issue(
        dataset_id=src.id,
        title=src.title or src.id,
        org=(src.organization or {}).get("title", "") or "",
        reason=reason,
        detail=detail,
        preview=preview,
    )
    if number is not None:
        store.set_authoring_issue(src.id, number, preview=preview)
    return number


def _spends_cap(o: RefreshOutcome) -> bool:
    return o.status != "skipped" and not (
        o.status == "unchanged" and o.reason == "fingerprint"
    )


def run_refresh(
    store,
    repo,
    *,
    preview: bool,
    staging_bucket: str,
    only_ids: Optional[list[str]] = None,
    cap: Optional[int] = None,
    force: bool = False,
    notify: bool = True,
    work_root: Optional[Path] = None,
    **kwargs,
) -> dict:
    """Refresh every eligible recipe'd source (sequentially — a refresh is
    CKAN-bound and cheap; there is no model latency to hide)."""
    cap = cap if cap is not None else _env_int("REFRESH_CAP", 200)
    work_root = work_root or Path(os.environ.get("SESSIONS_ROOT", "/tmp/sessions"))
    work_root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="recipes-", dir=work_root))
    ids = repo.list_ids()
    if only_ids is not None:
        ids = [i for i in ids if i in set(only_ids)]
    outcomes: list[RefreshOutcome] = []
    try:
        for dataset_id in ids:
            # A fingerprint skip made no export, so it doesn't spend the cap.
            if len([o for o in outcomes if _spends_cap(o)]) >= cap:
                outcomes.append(RefreshOutcome(dataset_id, "skipped", reason="cap"))
                continue
            src = store.get_source(dataset_id)
            if src is None:
                outcomes.append(RefreshOutcome(dataset_id, "skipped", reason="no_source_doc"))
                continue
            try:
                recipe = repo.load(dataset_id, scratch)
            except Exception as e:
                log.exception("recipe %s failed to load", dataset_id[:8])
                outcomes.append(
                    RefreshOutcome(dataset_id, "failed", reason="recipe_invalid", error=_clip(str(e)))
                )
                continue
            state = store.get_refresh_state(dataset_id, preview=preview)
            trigger = "forced" if force else needs_refresh(src, state, recipe)
            if trigger is None:
                outcomes.append(RefreshOutcome(dataset_id, "skipped", reason="up_to_date"))
                continue
            log.info("refreshing %s (%s) — %s", dataset_id[:8], trigger, (src.title or "")[:60])
            outcomes.append(
                refresh_one(
                    src, recipe, store=store, preview=preview,
                    staging_bucket=staging_bucket, work_root=work_root,
                    trigger=trigger, previous_state=state, notify=notify, **kwargs,
                )
            )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    refreshed = [o.id for o in outcomes if o.status == "refreshed"]
    unchanged = [o.id for o in outcomes if o.status == "unchanged"]
    failed = [o.id for o in outcomes if o.status == "failed"]
    return {
        "target": "preview" if preview else "prod",
        "recipes": len(ids),
        "refreshed": refreshed,
        "unchanged": unchanged,
        "failed": failed,
        "outcomes": [o.__dict__ for o in outcomes],
    }


# ── preview overlay (publish.yml, target=preview) ────────────────────────


def overlay_preview(store, out_dir: Path) -> list[str]:
    """Lay the preview lane over a freshly published prod tree.

    publish.py has already written prod `datasets/<id>/agent_data.json` and
    `data/manifest.json`; content.html for preview ids was rsynced from
    gs://…/preview/datasets/ by the workflow. Here: replace agent_data.json
    for every preview-refreshed id and patch its manifest summary so cards
    and the page agree.
    """
    from .schema import AgentData

    done: dict[str, dict] = {}
    for dataset_id, state in store.iter_preview_states():
        # agent_data is only ever written by a successful refresh, so its
        # presence (not refresh_status, which a later failure overwrites)
        # is what says "this id has a preview page to show".
        ad = state.get("agent_data")
        if not ad:
            continue
        AgentData.model_validate(ad)
        d = out_dir / "datasets" / dataset_id
        if not d.is_dir():
            log.warning("overlay: %s has no published dir — skipped", dataset_id[:8])
            continue
        (d / "agent_data.json").write_text(
            json.dumps(ad, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        done[dataset_id] = ad
    manifest_path = out_dir / "data" / "manifest.json"
    if done and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest.get("datasets") or []:
            ad = done.get(entry.get("id"))
            if ad:
                for k in ("summary_he", "temporal_coverage", "spatial_coverage"):
                    if ad.get(k):
                        entry[k] = ad[k]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
    return sorted(done)


# ── CLI ──────────────────────────────────────────────────────────────────


def _cli() -> None:
    p = argparse.ArgumentParser(description="Deterministic recipe refresh (no LLM).")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="refresh eligible recipe'd sources")
    r.add_argument("--target", choices=("prod", "preview"),
                   default=os.environ.get("REFRESH_TARGET", "preview"))
    r.add_argument("--source", action="append", help="limit to dataset id(s)")
    r.add_argument("--force", action="store_true", help="refresh even if up to date")
    r.add_argument("--no-publish", action="store_true")
    r.add_argument("--no-notify", action="store_true")
    o = sub.add_parser("overlay", help="apply the preview lane to a published tree")
    o.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    from services.shared.firestore import FirestoreStateStore

    store = FirestoreStateStore()
    if args.cmd == "overlay":
        ids = overlay_preview(store, args.out)
        print(json.dumps({"overlaid": ids}, indent=2))
        return

    preview = args.target == "preview"
    bucket = os.environ.get("GCS_STAGING_BUCKET", "")
    if not bucket:
        raise SystemExit("GCS_STAGING_BUCKET must be set")
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    started = datetime.now(timezone.utc)
    summary = run_refresh(
        store,
        recipe_repo_from_env(),
        preview=preview,
        staging_bucket=bucket,
        only_ids=args.source,
        force=args.force,
        notify=not args.no_notify,
    )
    summary["run_id"] = run_id
    summary["started_at"] = started
    summary["completed_at"] = datetime.now(timezone.utc)

    publish = None
    if summary["refreshed"] and not args.no_publish:
        import asyncio
        from .pipeline import _trigger_publish_github

        publish = asyncio.run(
            _trigger_publish_github(
                os.environ.get("PUBLISH_GITHUB_REPO", "darkdiamond/govil.ai"),
                os.environ.get("PUBLISH_GITHUB_WORKFLOW", "publish.yml"),
                os.environ.get("PUBLISH_BRANCH", "main"),
                inputs={"target": "preview"} if preview else None,
            )
        )
    summary["publish"] = publish
    if preview:
        try:
            store.record_preview_run(run_id, summary)
        except Exception:
            log.exception("failed to record preview run report")
    print(json.dumps(summary, indent=2, default=str, ensure_ascii=False))
    if summary["failed"] and not (summary["refreshed"] or summary["unchanged"]):
        raise SystemExit(1)


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    _cli()
