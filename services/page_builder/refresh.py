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
import csv
import functools
import hashlib
import http.client
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
from urllib import error as urllib_error

from .agent_contract import (
    DownloadBlocked,
    ResourceRestrictedError,
    fetch_resource_file,
    fetch_resource_preview,
    FetchLimitExceeded,
    fetch_resource_records_to_file,
    run_host_check,
    sanitize_content_html,
)
from . import geo_snapshot
from services.providers import SOURCE_CONFIG_FILENAME, SourceConfig, provider_for_key

from .local_sandbox import LocalSandbox
from .recipe import (
    MANIFEST_FILENAME,
    RECIPE_FILES,
    Recipe,
    RecipeError,
    RecipeManifest,
    feature_table,
    snapshot_table,
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
# A wall-budget overrun is transient (slow CKAN); this many in a row since
# the last full fetch means the dataset outgrew its budget → `too_large`.
_DEFAULT_WALL_BUDGET_STRIKES = 3
# Same idea for every `StrikeError` (a map-file download the WAF blocked):
# this many runs in a row → its `escalate_to` reason, which opens an issue.
_DEFAULT_TRANSIENT_STRIKES = 3
# A `map` input's file download cap (REFRESH_MAP_MAX_BYTES): it is parsed
# in the builder process, not the compute sandbox.
_DEFAULT_MAP_MAX_BYTES = 50_000_000
_DEFAULT_PAGE_SIZE = 25_000
_PAGE_TIMEOUT_S = 60.0
_COMPUTE_TIMEOUT_S = 300
# Heap cap for compute (see `_memory_guard`). The job has 4Gi; the rest is
# the builder, the page cache and the exported CSVs on the tmpfs.
_DEFAULT_COMPUTE_MEMORY_MB = 3072
# Sandbox-spawn flake (gRPC atfork handlers abort the forked child, SIGABRT
# + an `ev_epoll1_linux` line on stderr): not the recipe's fault, so retry
# in a fresh sandbox instead of opening an authoring issue. If every attempt
# flakes, the failure is `sandbox_failed`: transient, retried next run.
_COMPUTE_SPAWN_ATTEMPTS = 2
_COMPUTE_SPAWN_BACKOFF_S = 1.0

# Failure reasons a human must act on → open an authoring issue. Anything
# else (`fetch_failed`, `sandbox_failed`) is transient and simply retried
# next run.
# Staging (GCS upload / Firestore mark) failed after a good render. After
# this many in a row the batch stops: the store is down, and every further
# source would only spend a full export to fail the same way.
STAGE_FAILED = "stage_failed"
MAX_CONSECUTIVE_STAGE_FAILURES = 3
AUTHORING_REASONS = (
    "recipe_failed", "schema_changed", "too_large", "geometry_stale", "download_blocked",
)


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
#      datastore-only edits (A still sees those that move the total or the
#      first rows).
#   B′ unordered inputs hash — B over the rows as a multiset (same pass as B).
#      Observe only: tells a reordered re-upload from an edited one, and is
#      the gate for ever skipping on it (a compute may depend on row order).
# And one after the recipe, exact by definition:
#   C  content hash — the rendered body + agent_data. A data bump whose page
#      came out identical (the bytes moved where the page doesn't look: an
#      unused column, a reorder, an edit no number shows) is `unchanged`:
#      nothing is staged or published. It stores the new A/A′/B, so the same
#      data re-uploaded again is caught before the export (A ∧ A′) or before
#      compute (B), not after it.
# off      today's behaviour
# observe  compute A/A′/B/B′/C and report agreement with the rendered output; never skip
# inputs   skip on B, then C (A/A′ observed)
# full     skip on A ∧ A′ without fetching, else fetch and skip on B, then C. A
#          alone false-skipped ~5/night in observe, so it never skips by itself;
#          an input with no CKAN hash makes A′ None and forces the fetch.
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

    def provider_source_ids(self) -> list[str]:
        return [i for i in self.list_ids() if (self.root / i / SOURCE_CONFIG_FILENAME).is_file()]

    def source_config(self, dataset_id: str) -> Optional[SourceConfig]:
        path = self.root / dataset_id / SOURCE_CONFIG_FILENAME
        if not path.is_file():
            return None
        return SourceConfig.model_validate_json(path.read_text(encoding="utf-8"))


class GcsRecipeRepo:
    """Recipes uploaded to gs://<bucket>/<prefix><id>/ — the preview lane
    (`infra/refresh-preview.deploy.sh sync-recipes`)."""

    def __init__(self, bucket: str, prefix: str = "recipes/"):
        from google.cloud import storage

        self._bucket = storage.Client().bucket(bucket)
        self.prefix = prefix if prefix.endswith("/") else prefix + "/"

    def list_ids(self) -> list[str]:
        ids, with_source = set(), set()
        for blob in self._bucket.client.list_blobs(self._bucket, prefix=self.prefix):
            rel = blob.name[len(self.prefix):]
            parts = rel.split("/")
            if len(parts) == 2 and parts[1] == MANIFEST_FILENAME:
                ids.add(parts[0])
            elif len(parts) == 2 and parts[1] == SOURCE_CONFIG_FILENAME:
                with_source.add(parts[0])
        self._with_source = with_source & ids
        return sorted(ids)

    def provider_source_ids(self) -> list[str]:
        ids = self.list_ids()
        return [i for i in ids if i in self._with_source]

    def source_config(self, dataset_id: str) -> Optional[SourceConfig]:
        blob = self._bucket.blob(f"{self.prefix}{dataset_id}/{SOURCE_CONFIG_FILENAME}")
        if not blob.exists():
            return None
        return SourceConfig.model_validate_json(blob.download_as_bytes())

    def load(self, dataset_id: str, scratch: Path) -> Recipe:
        def fetch(name: str, dest: Path) -> None:
            blob = self._bucket.blob(f"{self.prefix}{dataset_id}/{name}")
            if not blob.exists():
                raise RecipeError(f"recipe {dataset_id} missing {name} in GCS")
            blob.download_to_filename(str(dest))

        return _load_remote(scratch / dataset_id, fetch)


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
        self._with_source: set[str] = set()

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
            ids, with_source = set(), set()
            for node in tree.get("tree") or []:
                parts = node.get("path", "").split("/")
                if len(parts) == 3 and parts[0] == "recipes" and parts[2] == MANIFEST_FILENAME:
                    ids.add(parts[1])
                elif len(parts) == 3 and parts[0] == "recipes" and parts[2] == SOURCE_CONFIG_FILENAME:
                    with_source.add(parts[1])
            self._sha, self._ids = sha, sorted(ids)
            self._with_source = with_source & ids
        return list(self._ids)

    def provider_source_ids(self) -> list[str]:
        return [i for i in self.list_ids() if i in self._with_source]

    def source_config(self, dataset_id: str) -> Optional[SourceConfig]:
        if dataset_id not in set(self.provider_source_ids()):
            return None
        r = self._get(
            f"https://raw.githubusercontent.com/{self.repo}/{self._sha}/"
            f"recipes/{dataset_id}/{SOURCE_CONFIG_FILENAME}"
        )
        return SourceConfig.model_validate_json(r.content)

    def load(self, dataset_id: str, scratch: Path) -> Recipe:
        if self._sha is None:
            self.list_ids()
        def fetch(name: str, dest: Path) -> None:
            r = self._get(
                f"https://raw.githubusercontent.com/{self.repo}/{self._sha}/"
                f"recipes/{dataset_id}/{name}"
            )
            dest.write_bytes(r.content)

        return _load_remote(scratch / dataset_id, fetch)


def _load_remote(dest: Path, fetch: Callable[[str, Path], None]) -> Recipe:
    """Download a recipe with `fetch(name, path)`: the fixed files, then the
    snapshot files its recipe.json declares. The names are validated (plain
    `<name>.geojson`) before they become paths."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in RECIPE_FILES:
        fetch(name, dest / name)
    manifest = RecipeManifest.model_validate_json(
        (dest / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    for name in manifest.snapshot_files:
        fetch(name, dest / name)
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
            try:
                self._previews[rid] = self._preview_fn(rid)
            except FetchLimitExceeded as e:
                # A provider reads the whole series to preview it.
                raise _limit_error(e, f"preview of {rid[:8]}") from None
        return self._previews[rid]


class WallBudgetExceeded(RecipeError):
    """A fetch ran out of wall budget. Transient (`fetch_failed`) on its
    own; `refresh_one` counts them and escalates a run of them."""

    def __init__(self, message: str):
        super().__init__(message, reason="fetch_failed")


class StrikeError(RecipeError):
    """A transient failure that a human must see once it keeps happening.
    `refresh_one` counts consecutive runs per `strike` in the refresh state's
    `transient_strikes` map and, at REFRESH_TRANSIENT_STRIKES, records it as
    `escalate_to` instead (an AUTHORING_REASON: issue opened, count reset)."""

    def __init__(self, message: str, *, reason: str, strike: str, escalate_to: str):
        super().__init__(message, reason=reason)
        self.strike = strike
        self.escalate_to = escalate_to


def _limit_error(e: FetchLimitExceeded, what: str) -> RecipeError:
    """A byte overrun is the dataset outgrowing its cap: a retry fetches the
    same bytes again, so a human must act (`too_large`). A wall-budget
    overrun is slow CKAN or a dataset that outgrew the budget; one run can't
    tell which, so it is retried (`fetch_failed`) until it repeats
    (`_DEFAULT_WALL_BUDGET_STRIKES`)."""
    if e.limit == "bytes":
        return RecipeError(
            f"{what}: {e} (REFRESH_MAX_BYTES / REFRESH_TOTAL_BYTES / recipe limits)",
            reason="too_large",
        )
    if e.limit == "wall_budget":
        return WallBudgetExceeded(f"{what}: ran out of wall budget ({e})")
    raise AssertionError(f"unhandled fetch limit {e.limit!r}")


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
# Builds a `map` input's table; folded only into recipes that have one, so
# a change here doesn't re-render every other page.
_GEO_CODE_FILE = Path(__file__).resolve().parent / "geo_snapshot.py"


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
    for name in recipe.files:
        h.update(name.encode())
        h.update(b"\0")
        h.update((recipe.root / name).read_bytes())
        h.update(b"\0")
    h.update(_render_code_hash().encode())
    if any(i.map for i in recipe.manifest.inputs):
        h.update(_geo_code_hash().encode())
    return h.hexdigest()


@functools.lru_cache(maxsize=1)
def _geo_code_hash() -> str:
    return hashlib.sha256(_GEO_CODE_FILE.read_bytes()).hexdigest()


# Everything the image ships that a refresh runs (Dockerfile COPYs) plus the
# installed library versions (requirements.txt holds ranges, so a rebuild can
# move pandas without touching it), for the failure lock only. Broader than
# _RENDER_CODE_FILES on purpose: a deploy that changes any of it retries
# locked sources once, but must not re-render every page through the prechecks.
_SERVICES_DIR = Path(__file__).resolve().parent.parent
_CHECK_SCRIPT = _SERVICES_DIR.parent / "agent" / "skills" / "check.py"


@functools.lru_cache(maxsize=1)
def _builder_code_hash() -> str:
    from importlib import metadata

    files = sorted(
        p for p in _SERVICES_DIR.rglob("*.py")
        if "tests" not in p.relative_to(_SERVICES_DIR).parts
    )
    h = hashlib.sha256()
    for path in [*files, _CHECK_SCRIPT]:
        if not path.is_file():
            continue
        h.update(str(path.relative_to(_SERVICES_DIR.parent)).encode())
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    dists = sorted(
        f"{d.metadata['Name']}=={d.version}".lower() for d in metadata.distributions()
    )
    h.update("\n".join(dists).encode())
    return h.hexdigest()


def _preview_shape(p: dict) -> list:
    return [p.get("total"), [[f.get("id"), f.get("type")] for f in p.get("fields") or []]]


def _digest(parts: list, identity: str) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode())
    h.update(identity.encode())
    return h.hexdigest()


def input_fingerprint(recipe: Recipe, probe: InputProbe, identity: str) -> str:
    """Check A: what the datastore preview says about every input — row total,
    columns, first rows (`_id` dropped) — plus `recipe_identity`. A snapshot
    input has no datastore; its bytes are already in the identity. A map
    input contributes CKAN's size/md5 of its file."""
    parts = []
    for inp in recipe.manifest.inputs:
        if inp.snapshot:
            parts.append([inp.name, inp.by_id, "snapshot"])
            continue
        if inp.map:
            res = probe.resolved[inp.name][0]
            parts.append([inp.name, inp.by_id, "map", res.get("size"), res.get("hash")])
            continue
        for res in probe.resolved[inp.name]:
            p = probe.preview(res["id"]) or {}
            parts.append(
                [
                    inp.name,
                    res["id"],
                    *_preview_shape(p),
                    [
                        {k: v for k, v in row.items() if k != "_id"}
                        for row in p.get("sample_rows") or []
                    ],
                ]
            )
    return _digest(parts, identity)


def file_fingerprint(recipe: Recipe, probe: InputProbe, identity: str) -> Optional[str]:
    """Check A′: CKAN's md5 + size of every input's uploaded file, the
    preview's row total and columns, plus `recipe_identity`. None when any
    input has no CKAN hash (API-pushed resource, or a source doc scanned before
    the scanner kept it) — it never vouches for an input it can't see. A
    snapshot input is exact by construction (its bytes are in the identity).
    A map input with no md5 makes it None too (size alone misses a same-size
    edit), so its file is downloaded and check B decides."""
    parts = []
    for inp in recipe.manifest.inputs:
        if inp.snapshot:
            parts.append([inp.name, inp.by_id, "snapshot"])
            continue
        if inp.map:
            res = probe.resolved[inp.name][0]
            if not res.get("hash"):
                return None
            parts.append([inp.name, inp.by_id, "map", res["hash"], res.get("size")])
            continue
        for res in probe.resolved[inp.name]:
            if not res.get("hash"):
                return None
            p = probe.preview(res["id"]) or {}
            parts.append(
                [inp.name, res["id"], res["hash"], res.get("size"), *_preview_shape(p)]
            )
    return _digest(parts, identity)


_MULTISET_MOD = 1 << 256


def inputs_hashes(
    recipe: Recipe, inputs: dict[str, list["FetchedInput"]], identity: str
) -> tuple[str, str]:
    """Check B and B′ in one pass over the exported CSVs, + `recipe_identity`.

    B (exact): the bytes as exported (deterministic: datastore order, `_id`
    dropped, schema field order). B′ (observe only): the same rows as a
    multiset — the sum of each line's sha256 — so it holds when a re-upload
    only reordered the rows. A quoted newline splits a record into fragments
    that move together, so the multiset is still order-blind."""
    ordered = hashlib.sha256()
    unordered = hashlib.sha256()
    for inp in recipe.manifest.inputs:
        for part in inputs.get(inp.name, []):
            tag = f"{inp.name}|{part.resource_id}|".encode()
            ordered.update(tag)
            acc = 0
            with open(part.file, "rb") as f:
                header = f.readline()
                ordered.update(header)
                for line in f:
                    ordered.update(line)
                    digest = hashlib.sha256(line.rstrip(b"\r\n")).digest()
                    acc += int.from_bytes(digest, "big")
            ordered.update(b"\0")
            acc %= _MULTISET_MOD  # once per part: Python ints don't overflow
            unordered.update(tag + header.rstrip(b"\r\n") + b"\0" + acc.to_bytes(32, "big"))
    ordered.update(identity.encode())
    unordered.update(identity.encode())
    return ordered.hexdigest(), unordered.hexdigest()


def inputs_hash(
    recipe: Recipe, inputs: dict[str, list["FetchedInput"]], identity: str
) -> str:
    """Check B alone (see `inputs_hashes`)."""
    return inputs_hashes(recipe, inputs, identity)[0]


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
    snapshot_rows: Callable[[list], list] = lambda rows: rows,
    fetch_file_fn: Callable = fetch_resource_file,
) -> dict[str, list[FetchedInput]]:
    """Full export of every resource the recipe reads, as CSV in `dest_dir`.

    Raises RecipeError: `schema_changed` (inputs no longer resolve),
    `too_large` (over REFRESH_MAX_RECORDS, or the export crossed its byte
    cap — sampling is never an option here), `fetch_failed` (CKAN/network,
    or the wall budget ran out; transient).

    `probe` (from `probe_inputs`) skips the resolve + preview calls already made.
    A snapshot input is written from its committed GeoJSON, never fetched; a
    map input downloads its file (`fetch_file_fn`) and converts it the same
    way. `snapshot_rows` lets author verify truncate/shuffle either's features.
    """
    probe = probe or probe_inputs(recipe, resources, preview_fn)
    _preview = probe.preview
    resolved = probe.resolved

    limits = recipe.manifest.limits
    max_records = limits.max_records or _env_int("REFRESH_MAX_RECORDS", _DEFAULT_MAX_RECORDS)
    max_bytes = limits.max_bytes or _env_int("REFRESH_MAX_BYTES", _DEFAULT_MAX_BYTES)
    # A per-resource cap above the dataset total would be clipped by it.
    remaining = limits.total_bytes or max(
        _env_int("REFRESH_TOTAL_BYTES", _DEFAULT_TOTAL_BYTES), limits.max_bytes or 0
    )
    page_size = _env_int("REFRESH_PAGE_SIZE", _DEFAULT_PAGE_SIZE)
    deadline = time.monotonic() + float(
        limits.wall_budget_s
        or _env_int("REFRESH_WALL_BUDGET_S", int(_DEFAULT_WALL_BUDGET_S))
    )

    dest_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[FetchedInput]] = {}
    for inp in recipe.manifest.inputs:
        if inp.snapshot:
            out[inp.name] = [_write_snapshot(recipe, inp, resolved[inp.name][0],
                                             dest_dir, snapshot_rows)]
            continue
        if inp.map:
            cap = min(_env_int("REFRESH_MAP_MAX_BYTES", _DEFAULT_MAP_MAX_BYTES), remaining)
            fetched, nbytes = _fetch_map(inp, resolved[inp.name][0], dest_dir, fetch_file_fn,
                                         max_bytes=cap, deadline=deadline,
                                         transform=snapshot_rows)
            remaining -= nbytes
            out[inp.name] = [fetched]
            continue
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
            cap = min(max_bytes, remaining)
            if cap <= 0:
                raise RecipeError(
                    f"input {inp.name!r}: earlier inputs used the whole "
                    "REFRESH_TOTAL_BYTES budget",
                    reason="too_large",
                )
            try:
                outcome = fetch_fn(
                    rid,
                    total,
                    dest,
                    max_bytes=cap,
                    page_size=page_size,
                    page_timeout_s=_PAGE_TIMEOUT_S,
                    deadline=deadline,
                    sample_target_rows=0,
                    prefer_sample=False,
                    fields=inp.columns,
                )
            except FetchLimitExceeded as e:
                raise _limit_error(e, f"input {inp.name!r}: export of {rid[:8]}") from None
            if outcome is None or outcome.mode != "full":
                raise RecipeError(
                    f"input {inp.name!r}: full fetch of {rid[:8]} failed (fetch error)",
                    reason="fetch_failed",
                )
            if inp.columns:
                _project_csv(dest, inp.columns)
            remaining -= outcome.bytes
            parts.append(
                FetchedInput(dest, rid, res.get("name") or "", outcome.rows)
            )
        out[inp.name] = parts
    return out


def _write_snapshot(recipe: Recipe, inp, res: dict, dest_dir: Path,
                    transform: Callable[[list], list]) -> FetchedInput:
    header, rows = snapshot_table(recipe.root / inp.snapshot)
    lost = [c for c in inp.required_columns if c not in header]
    if lost:
        raise RecipeError(f"input {inp.name!r}: snapshot {inp.snapshot} lacks column(s) {lost}")
    rows = transform(rows)
    if not rows:
        raise RecipeError(f"input {inp.name!r}: snapshot {inp.snapshot} has no features")
    return _write_table(inp, res, header, rows, dest_dir)


def _map_file_name(res: dict) -> str:
    """The downloaded file's name, from its URL (it hints the format)."""
    from urllib.parse import unquote, urlsplit

    tail = unquote(urlsplit(res.get("url") or "").path.rsplit("/", 1)[-1])
    return tail or f"{res.get('id', 'map')}.{(res.get('format') or 'bin').lower()}"


def _fetch_map(inp, res: dict, dest_dir: Path, fetch_file_fn: Callable, *,
               max_bytes: int, deadline: float,
               transform: Callable[[list], list]) -> tuple[FetchedInput, int]:
    """Download a `map` input's file and write it as the snapshot table.

    The bytes are the data's, so a bad file is `schema_changed` (the upload
    changed shape), not `recipe_failed`. A WAF block, or a file CKAN lists
    but data.gov.il no longer serves (404/410), is transient until it
    repeats (`StrikeError` → `download_blocked` / `schema_changed`)."""
    rid = inp.by_id
    what = f"input {inp.name!r}: map file {rid[:8]}"
    raw = dest_dir / f"{inp.name}__map.download"
    if max_bytes <= 0:
        raise RecipeError(f"{what}: earlier inputs used the whole REFRESH_TOTAL_BYTES budget",
                          reason="too_large")
    try:
        got = fetch_file_fn(res.get("url") or "", raw, max_bytes=max_bytes,
                            timeout_s=_PAGE_TIMEOUT_S, deadline=deadline)
        data = raw.read_bytes()
    except FetchLimitExceeded as e:
        raise _limit_error(e, f"{what}: download") from None
    except DownloadBlocked as e:
        raise StrikeError(f"{what}: download blocked ({e})", reason="fetch_failed",
                          strike="download_blocked", escalate_to="download_blocked") from None
    except ValueError as e:  # not a data.gov.il URL: the resource moved off-site
        raise RecipeError(f"{what}: {e}", reason="schema_changed") from None
    except urllib_error.HTTPError as e:
        if e.code in (404, 410):
            raise StrikeError(f"{what}: the file is gone (HTTP {e.code})", reason="fetch_failed",
                              strike="download_missing", escalate_to="schema_changed") from None
        raise RecipeError(f"{what}: download failed ({e})", reason="fetch_failed") from None
    except (urllib_error.URLError, OSError, http.client.HTTPException) as e:  # timeouts too
        raise RecipeError(f"{what}: download failed ({e!r})", reason="fetch_failed") from None
    finally:
        raw.unlink(missing_ok=True)
    try:
        feats, crs = geo_snapshot.load_map(data, _map_file_name(res))
        body, tol = geo_snapshot.build_snapshot(
            feats, crs=crs,
            max_bytes=(inp.map_max_kb * 1000) if inp.map_max_kb else geo_snapshot.DEFAULT_MAX_BYTES,
        )
    except geo_snapshot.SnapshotTooLarge as e:
        raise RecipeError(f"{what}: {e} (map_max_kb)", reason="too_large") from None
    except geo_snapshot.SnapshotError as e:
        raise RecipeError(f"{what}: {e}", reason="schema_changed") from None
    header, rows = feature_table(json.loads(body), what, reason="schema_changed")
    lost = [c for c in inp.required_columns if c not in header]
    if lost:
        raise RecipeError(f"{what}: lacks column(s) {lost}", reason="schema_changed")
    rows = transform(rows)
    if not rows:
        raise RecipeError(f"{what}: has no features", reason="schema_changed")
    log.info("map %s: %s bytes → %d features (%s, tolerance %s)",
             rid[:8], f"{got.bytes:,}", len(rows), crs, tol)
    return _write_table(inp, res, header, rows, dest_dir), got.bytes


def _write_table(inp, res: dict, header: list[str], rows: list[list[str]],
                 dest_dir: Path) -> FetchedInput:
    dest = dest_dir / f"{inp.name}__1.csv"
    with open(dest, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return FetchedInput(dest, inp.by_id, res.get("name") or "", len(rows))


def _project_csv(path: Path, columns: list[str]) -> None:
    """Rewrite `path` to exactly `columns`, in that order. A no-op for a
    CKAN export (already projected by `fields=`); fetchers that ignore
    `fields` (providers, author verify's cache) get projected here, so
    compute sees the same frame whichever fetcher ran."""
    with open(path, encoding="utf-8", newline="") as f:
        header = next(csv.reader(f), [])
    if header == columns:
        return
    lost = [c for c in columns if c not in header]
    if lost:
        raise RecipeError(
            f"{path.name}: export lacks column(s) {lost}", reason="schema_changed"
        )
    idx = [header.index(c) for c in columns]
    tmp = path.with_suffix(".projected")
    with open(path, encoding="utf-8", newline="") as src, open(
        tmp, "w", encoding="utf-8", newline=""
    ) as out:
        w = csv.writer(out)
        for row in csv.reader(src):
            w.writerow([row[i] if i < len(row) else "" for i in idx])
    tmp.replace(path)


# ── compute + render ─────────────────────────────────────────────────────


def _memory_guard(recipe: Recipe) -> str:
    """Python prologue for the compute process. It caps its own heap
    (RLIMIT_DATA: allocations past it raise MemoryError, a clean recipe
    failure) and volunteers as the OOM killer's first victim, so a recipe
    that outgrows the container takes down itself, not the builder and the
    rest of the night's refresh. Cap: the recipe's
    `limits.compute_memory_mb`, else REFRESH_COMPUTE_MEMORY_MB; 0 = no cap."""
    limits = recipe.manifest.limits
    mb = limits.compute_memory_mb or _env_int(
        "REFRESH_COMPUTE_MEMORY_MB", _DEFAULT_COMPUTE_MEMORY_MB
    )
    code = (
        "try:\n"
        "    open('/proc/self/oom_score_adj', 'w').write('1000')\n"
        "except OSError:\n"
        "    pass\n"
    )
    if mb > 0:
        n = mb * 1024 * 1024
        code += f"import resource; resource.setrlimit(resource.RLIMIT_DATA, ({n}, {n}))\n"
    return code


class _SpawnFlake(RecipeError):
    """compute() died to the known fork/gRPC abort, not to recipe code.

    Not an authoring reason: as `recipe_failed` it would open an issue and
    lock the source out (`needs_refresh` skips a failed version) until the
    data moved, though the same recipe renders fine on the next spawn.
    """

    def __init__(self, message: str):
        super().__init__(message, reason="sandbox_failed")


def _is_spawn_flake(error_value: str, stderr: str) -> bool:
    return error_value == "exit code -6" and "ev_epoll1_linux" in stderr


def run_compute(
    recipe: Recipe,
    inputs: dict[str, list[FetchedInput]],
    work_root: Path,
    *,
    timeout: Optional[int] = None,
) -> dict:
    """`_run_compute_once`, retried on the known sandbox-spawn flake only.

    Every other failure (recipe exceptions, timeouts, a bare SIGABRT
    without the gRPC signature) surfaces immediately. `timeout` defaults to
    the recipe's `limits.compute_timeout_s`, else `_COMPUTE_TIMEOUT_S`.
    """
    limits = recipe.manifest.limits
    timeout = timeout or limits.compute_timeout_s or _COMPUTE_TIMEOUT_S
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
    timeout: int,
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
            _memory_guard(recipe)
            + "import runpy; runpy.run_path('recipe_exec.py', run_name='__main__')",
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


def failed_version_key(src, recipe: Recipe) -> str:
    """What a failure is pinned to: the data version, the recipe version, and
    a hash of the recipe files + the builder code. The same failure is not
    retried until one of them moves, so a builder fix (or a recipe edit that
    kept its `recipe_version`) gets one fresh try at a locked source.

    Called from the failure handlers, so it never raises: without the hash
    the key is the bare version, which a later readable run never matches
    (one extra retry, not a crashed batch)."""
    base = version_key(src.metadata_modified, recipe.manifest.recipe_version)
    try:
        code = hashlib.sha256(
            (recipe_identity(recipe) + _builder_code_hash()).encode()
        ).hexdigest()
    except Exception:
        log.warning("refresh %s: hashing the recipe/builder code failed", src.id[:8],
                    exc_info=True)
        return base
    return f"{base}|{code[:16]}"


def needs_refresh(src, state: dict, recipe: Recipe) -> Optional[str]:
    """Why this source should be refreshed now, or None to skip it."""
    if src is None:
        return None
    if src.analysis_status in ("unavailable", "restricted"):
        return None  # data gone upstream; keep the frozen page
    rv = recipe.manifest.recipe_version
    if state.get("refresh_reason") in AUTHORING_REASONS and state.get(
        "refresh_failed_version"
    ) == failed_version_key(src, recipe):
        return None  # same data + recipe + builder would fail the same way
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


def _read_gcs(bucket: str, relpath: str) -> Optional[bytes]:
    """The staged object's current bytes, or None if there is none."""
    from google.api_core.exceptions import NotFound
    from google.cloud import storage

    try:
        return storage.Client().bucket(bucket).blob(relpath).download_as_bytes()
    except NotFound:
        return None


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
    # REFRESH_PRECHECK report: {mode, fp_same, fp2_same, inputs_same,
    # inputs_same_unordered, content_same, skipped}
    # (True/False; None = no stored hash to compare against yet).
    precheck: dict = field(default_factory=dict)


class _Unchanged(Exception):
    """Precheck proved the inputs identical to the last render — stop before
    the expensive steps. `reason` is `fingerprint` or `inputs_hash`
    (`content_hash`, the post-render check, doesn't raise)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _precheck_may_skip(trigger: str, state: dict) -> bool:
    """Skipping is only safe for a plain data bump on a recently re-rendered
    page: a forced run, a recipe_version change, or a page older than
    REFRESH_PRECHECK_MAX_AGE_DAYS (bounds check A's blind spot and picks up
    shell-code changes that alter output without any data change) always
    re-render. The age runs from the last full render, including one that
    came out identical (`last_verified_at`): it proved the live page right."""
    if trigger != "data_updated":
        return False
    stamps = [state.get("last_refreshed_at"), state.get("last_verified_at")]
    stamps = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in stamps if t]
    if not stamps:
        return False
    last = max(stamps)
    max_age = _env_int("REFRESH_PRECHECK_MAX_AGE_DAYS", _DEFAULT_PRECHECK_MAX_AGE_DAYS)
    return datetime.now(timezone.utc) - last <= timedelta(days=max_age)


def _same(new: str, old: Optional[str]) -> Optional[bool]:
    return None if old is None else new == old


def fetchable_resources(resources: list[dict]) -> list[dict]:
    """A provider doc's resources as input resolution sees them. They are
    stored `datastore_active: false` (data.json must not send the browser
    explorer to data.gov.il), but every one is fetchable by its provider."""
    return [{**r, "datastore_active": True} for r in resources or []]


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
    read_gcs: Callable[[str, str], Optional[bytes]] = _read_gcs,
    providers=None,
    **fetch_kwargs,
) -> RefreshOutcome:
    started = time.monotonic()
    rv = recipe.manifest.recipe_version
    resources = src.resources
    provider_key = getattr(src, "provider", None)
    if provider_key:
        # A non-CKAN source: its provider fetches (services/providers), CKAN
        # is never called. Disabled provider → leave the last-good page.
        p = provider_for_key(provider_key, providers)
        if p is None:
            log.info("refresh %s: provider %s is disabled — skipped", src.id, provider_key)
            return RefreshOutcome(src.id, "skipped", trigger, f"provider_disabled:{provider_key}")
        resources = fetchable_resources(src.resources)
        preview_fn, fetch_fn = p.fetch_fns(resources)
        fetch_kwargs.setdefault("preview_fn", preview_fn)
        fetch_kwargs.setdefault("fetch_fn", fetch_fn)
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
                recipe, resources, fetch_kwargs.get("preview_fn", fetch_resource_preview)
            )
            fp = hashes["input_fingerprint"] = input_fingerprint(recipe, probe, identity)
            pc["fp_same"] = _same(fp, state.get("input_fingerprint"))
            ff = hashes["file_fingerprint"] = file_fingerprint(recipe, probe, identity)
            pc["fp2_same"] = _same(ff, state.get("file_fingerprint")) if ff else None
            if may_skip and mode == "full" and pc["fp_same"] and pc["fp2_same"]:
                raise _Unchanged("fingerprint")

            def after_fetch(inputs):
                ih, iu = inputs_hashes(recipe, inputs, identity)
                hashes["inputs_hash"], hashes["inputs_hash_unordered"] = ih, iu
                pc["inputs_same"] = _same(ih, state.get("inputs_hash"))
                pc["inputs_same_unordered"] = _same(iu, state.get("inputs_hash_unordered"))
                if may_skip and mode in ("inputs", "full") and pc["inputs_same"]:
                    raise _Unchanged("inputs_hash")

        page, inputs = build_page(
            recipe, resources, work_root,
            probe=probe, after_fetch=after_fetch, **fetch_kwargs,
        )
    except _Unchanged as u:
        # Same inputs + same recipe ⇒ same page: keep the live one and report
        # `unchanged` (never triggers a publish). Only the exact check (B)
        # advances the version marker. After a fingerprint skip the bump stays
        # pending, so it is re-probed each run (one cheap preview call) until
        # the max age forces a real render. That is what bounds A's blind spot
        # even when CKAN never bumps the dataset again.
        return _mark_unchanged(
            store, src, trigger, u.reason, pc, hashes,
            advance_version=u.reason == "inputs_hash", preview=preview, started=started,
        )
    except ResourceRestrictedError as e:
        # Data went private upstream. Not the recipe's fault, not
        # actionable by re-authoring; the reconcile sweep owns this state.
        log.warning("refresh %s: restricted upstream: %s", src.id[:8], e)
        return RefreshOutcome(src.id, "failed", trigger, "restricted", str(e))
    except RecipeError as e:
        strikes = None
        if isinstance(e, WallBudgetExceeded):
            strikes = int(state.get("wall_budget_strikes") or 0) + 1
            limit = _env_int("REFRESH_WALL_BUDGET_STRIKES", _DEFAULT_WALL_BUDGET_STRIKES)
            if strikes >= limit:
                # Reset, so a re-authored recipe gets a fresh run of tries.
                e = RecipeError(
                    f"{e} — {strikes} runs in a row since the last full fetch",
                    reason="too_large",
                )
                strikes = 0
        transient = None
        if isinstance(e, StrikeError):
            transient = dict(state.get("transient_strikes") or {})
            n = int(transient.get(e.strike) or 0) + 1
            if n >= _env_int("REFRESH_TRANSIENT_STRIKES", _DEFAULT_TRANSIENT_STRIKES):
                transient.pop(e.strike, None)  # a fresh run of tries after the fix
                e = RecipeError(f"{e} — {n} runs in a row", reason=e.escalate_to)
            else:
                transient[e.strike] = n
        log.warning("refresh %s failed (%s): %s", src.id[:8], e.reason, e)
        store.mark_refresh_failed(
            src.id,
            error=str(e),
            reason=e.reason,
            failed_version=failed_version_key(src, recipe),
            wall_budget_strikes=strikes,
            transient_strikes=transient,
            preview=preview,
        )
        outcome = RefreshOutcome(
            src.id, "failed", trigger, e.reason, _clip(str(e)),
            round(time.monotonic() - started, 2),
        )
        if notify and e.reason in AUTHORING_REASONS:
            outcome.issue = _queue_authoring_safely(
                store, src, e.reason, detail=str(e), preview=preview
            )
        return outcome
    except Exception as e:  # infra bug, not a data/recipe verdict
        log.exception("refresh %s crashed", src.id[:8])
        store.mark_refresh_failed(
            src.id,
            error=f"{type(e).__name__}: {e}",
            reason="error",
            failed_version=failed_version_key(src, recipe),
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
        # C: a data bump that rendered the live page byte for byte. Exact, so
        # no max-age gate; a forced run or a recipe_version change still
        # stages (the latter must record its version through mark_refreshed).
        # After a staging failure the staged body may not be the one the
        # stored hash describes (a failed rollback), so that render stages.
        staging_suspect = (state.get("refresh_status") == "failed"
                           and state.get("refresh_reason") == STAGE_FAILED)
        if (mode in ("inputs", "full") and trigger == "data_updated"
                and pc["content_same"] and not staging_suspect):
            return _mark_unchanged(
                store, src, trigger, "content_hash", pc, hashes,
                advance_version=True, preview=preview, started=started,
                rows=snapshot["rows"],
            )
    prefix = "preview/datasets" if preview else "datasets"
    rel = f"{prefix}/{src.id}/{CONTENT_FILENAME}"
    previous_html: Optional[bytes] = None
    staged = False
    try:
        # Kept so a failed Firestore mark can put it back: the staged body
        # and the doc's agent_data must describe the same render, or the
        # next publish pairs a new page with the old summary.
        try:
            previous_html = read_gcs(staging_bucket, rel)
        except Exception:
            # Only the rollback below needs it; never fail a render over it.
            log.warning("refresh %s: reading the staged body failed — no rollback copy",
                        src.id[:8], exc_info=True)
        write_gcs(page.content_html.encode("utf-8"), staging_bucket, rel)
        staged = True
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
    except Exception as e:
        # Staging/state infra, not the recipe: this source only. It is not
        # an AUTHORING_REASON, so the next run retries it; run_refresh stops
        # the batch if staging keeps failing. If the upload landed but the
        # mark didn't, the last-good body goes back first. (A first render
        # has none; its doc isn't publishable yet, so the orphan is inert.)
        log.exception("refresh %s: staging failed", src.id[:8])
        if staged and previous_html is not None:
            try:
                write_gcs(previous_html, staging_bucket, rel)
            except Exception:
                log.exception(
                    "refresh %s: restoring the last-good body failed — staged "
                    "page and Firestore disagree until the next refresh", src.id[:8],
                )
        try:
            store.mark_refresh_failed(
                src.id,
                error=f"{type(e).__name__}: {e}",
                reason=STAGE_FAILED,
                failed_version=failed_version_key(src, recipe),
                preview=preview,
            )
        except Exception:
            log.exception("refresh %s: recording the staging failure failed", src.id[:8])
        return RefreshOutcome(
            src.id, "failed", trigger, STAGE_FAILED, _clip(str(e)),
            round(time.monotonic() - started, 2),
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


def _mark_unchanged(
    store, src, trigger: str, reason: str, pc: dict, hashes: dict, *,
    advance_version: bool, preview: bool, started: float, rows: Optional[dict] = None,
) -> RefreshOutcome:
    """Record a precheck skip (the live page stands). A failed state write is
    a staging failure like a failed `mark_refreshed`: this source only,
    retried next run, counted toward `staging_down`."""
    pc["skipped"] = reason
    try:
        store.mark_refresh_unchanged(
            src.id,
            metadata_modified=src.metadata_modified,
            input_fingerprint=hashes["input_fingerprint"],
            inputs_hash=hashes.get("inputs_hash"),
            inputs_hash_unordered=hashes.get("inputs_hash_unordered"),
            file_fingerprint=hashes.get("file_fingerprint"),
            reason=reason,
            advance_version=advance_version,
            preview=preview,
        )
    except Exception as e:
        log.exception("refresh %s: recording the unchanged state failed", src.id[:8])
        return RefreshOutcome(
            src.id, "failed", trigger, STAGE_FAILED, _clip(str(e)),
            round(time.monotonic() - started, 2), precheck=pc,
        )
    log.info("refresh precheck %s: unchanged (%s) — skipped", src.id[:8], reason)
    return RefreshOutcome(
        src.id, "unchanged", trigger, reason,
        elapsed_s=round(time.monotonic() - started, 2), rows=rows or {}, precheck=pc,
    )


def _log_precheck(dataset_id: str, pc: dict) -> None:
    """One line per refreshed source: did the cheap checks agree with the
    rendered output? A skip predicate that held with changed content is a
    false skip (`inputs`/`full` would have kept a stale page) — the rollout
    gate. Only the predicates a mode skips on (or might, once promoted) are
    flagged: A or A′ alone never skips. `inputs_same_unordered` with
    `inputs_same=False` means the re-upload only reordered rows."""
    log.info(
        "refresh precheck %s: mode=%s fp_same=%s inputs_same=%s content_same=%s"
        " fp2_same=%s inputs_same_unordered=%s",
        dataset_id[:8], pc.get("mode"), pc.get("fp_same"),
        pc.get("inputs_same"), pc.get("content_same"), pc.get("fp2_same"),
        pc.get("inputs_same_unordered"),
    )
    if pc.get("content_same") is False:
        would_skip = {
            "inputs_same": pc.get("inputs_same"),               # inputs, full
            "fp_same ∧ fp2_same": pc.get("fp_same") and pc.get("fp2_same"),  # full
            # none yet; only news when B differed (else `inputs_same` warns)
            "inputs_same_unordered": pc.get("inputs_same_unordered")
            and pc.get("inputs_same") is not True,
        }
        for check, held in would_skip.items():
            if held:
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
    """Flag a dataset for local authoring and open its issue (once).

    A recorded issue is reused while it is open or was closed as not
    planned. One closed as completed means a recipe PR landed and this is a
    new need (e.g. the recipe later failed), so a fresh issue is opened."""
    from . import notify as _notify

    state = store.get_refresh_state(src.id, preview=preview)
    store.mark_authoring_needed(src.id, reason, preview=preview)
    recorded = state.get("authoring_issue")
    if recorded and _notify.issue_state(int(recorded)) != "completed":
        # Back to `notified`, which mark_authoring_needed just overwrote:
        # the daily queue skips notified sources.
        store.set_authoring_issue(src.id, int(recorded), preview=preview)
        return int(recorded)
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


def _queue_authoring_safely(store, src, reason: str, **kw) -> Optional[int]:
    """queue_authoring for use mid-batch: a Firestore/GitHub error costs this
    source its issue (retried next run), never the rest of the refresh."""
    try:
        return queue_authoring(store, src, reason, **kw)
    except Exception:
        log.exception("queueing %s for authoring failed", src.id[:8])
        return None


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
    stage_failures = 0  # consecutive
    staging_down = False
    # Heavy recipes (`limits` set) run after all the others: if one still
    # outgrows the container, every other page is already staged.
    heavy: list[tuple[str, Recipe]] = []

    def _queue():
        for dataset_id in ids:
            yield dataset_id, None
        yield from heavy

    try:
        for dataset_id, recipe in _queue():
            if staging_down:
                outcomes.append(RefreshOutcome(dataset_id, "skipped", reason="staging_down"))
                continue
            # A fingerprint skip made no export, so it doesn't spend the cap.
            if len([o for o in outcomes if _spends_cap(o)]) >= cap:
                outcomes.append(RefreshOutcome(dataset_id, "skipped", reason="cap"))
                continue
            src = store.get_source(dataset_id)
            if src is None:
                outcomes.append(RefreshOutcome(dataset_id, "skipped", reason="no_source_doc"))
                continue
            if recipe is None:
                try:
                    recipe = repo.load(dataset_id, scratch)
                except Exception as e:
                    log.exception("recipe %s failed to load", dataset_id[:8])
                    outcome = RefreshOutcome(
                        dataset_id, "failed", reason="recipe_invalid", error=_clip(str(e))
                    )
                    # The page can't refresh until the recipe is fixed, so it
                    # needs authoring like any other broken recipe. Idempotent:
                    # the open issue is reused every night until then.
                    if notify:
                        outcome.issue = _queue_authoring_safely(
                            store, src, "recipe_failed", detail=str(e), preview=preview
                        )
                    outcomes.append(outcome)
                    continue
                if recipe.manifest.heavy:
                    heavy.append((dataset_id, recipe))
                    continue
            state = store.get_refresh_state(dataset_id, preview=preview)
            trigger = "forced" if force else needs_refresh(src, state, recipe)
            if trigger is None:
                outcomes.append(RefreshOutcome(dataset_id, "skipped", reason="up_to_date"))
                continue
            log.info("refreshing %s (%s) — %s", dataset_id[:8], trigger, (src.title or "")[:60])
            outcome = refresh_one(
                src, recipe, store=store, preview=preview,
                staging_bucket=staging_bucket, work_root=work_root,
                trigger=trigger, previous_state=state, notify=notify, **kwargs,
            )
            outcomes.append(outcome)
            if outcome.reason == STAGE_FAILED:
                stage_failures += 1
                if stage_failures >= MAX_CONSECUTIVE_STAGE_FAILURES:
                    log.error(
                        "refresh: %d staging failures in a row — stopping the batch",
                        stage_failures,
                    )
                    staging_down = True
            elif outcome.status == "refreshed":
                stage_failures = 0
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
        "staging_down": staging_down,
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
    repo = recipe_repo_from_env()
    # Provider sources (BoI, …) get their doc + version from the sync step,
    # as the daily job does. Prod only: it writes `sources/<id>`, and the
    # preview lane reads unmerged recipes, so it must never touch prod docs.
    # A preview of a provider recipe therefore needs its prod doc to exist.
    providers_summary = None
    if not preview:
        from services.providers.sync import sync_provider_sources

        providers_summary = sync_provider_sources(store, repo, only_ids=args.source)
    summary = run_refresh(
        store,
        repo,
        preview=preview,
        staging_bucket=bucket,
        only_ids=args.source,
        force=args.force,
        notify=not args.no_notify,
    )
    summary["providers"] = providers_summary
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
