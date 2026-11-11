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

Results land in `sources/<id>` (refresh state + agent_data) and
gs://<staging>/datasets/<id>/content.html. The daily job
(`services.page_builder.pipeline`) drives `run_refresh`; for one dataset run
`python -m services.page_builder.pipeline --source <id> --no-trigger-publish`.
"""
from __future__ import annotations

import csv
import functools
import hashlib
import http.client
import json
import logging
import os
import re
import shutil
import tempfile
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib import error as urllib_error

from services.providers import SOURCE_CONFIG_FILENAME, SourceConfig, provider_for_key
from services.shared import github, model_history
from services.shared.fetch_types import (
    DownloadBlocked,
    FetchLimitExceeded,
    ResourceRestrictedError,
)
from services.shared.states import (
    NO_DATA_STATUSES,
    AuthoringReason,
    FailReason,
    OutcomeStatus,
    RefreshState,
    RefreshStatus,
)

from . import geo_snapshot
from .ckan_export import (
    fetch_resource_export,
    fetch_resource_file,
    fetch_resource_preview,
)
from .local_sandbox import LocalSandbox, OutputTooLarge
from .page_gate import run_host_check
from .recipe import (
    MANIFEST_FILENAME,
    RECIPE_FILES,
    PreviewUnavailable,
    Recipe,
    RecipeError,
    RecipeManifest,
    feature_table,
    kpi_format_findings,
    render_template,
    resolve_inputs,
    snapshot_table,
    validate_model,
)
from .sanitize import sanitize_content_html

log = logging.getLogger("page_builder.refresh")

CONTENT_FILENAME = "content.html"
RECIPE_EXEC_PATH = Path(__file__).resolve().parent / "recipe_exec.py"
# Shared helpers recipes import (`from govlib import fmt`) and the shared
# Jinja macros (`{% import "gov.j2" as gov %}`); see recipe_lib/govlib.
RECIPE_LIB_DIR = Path(__file__).resolve().parent / "recipe_lib"
GOVLIB_DIR = RECIPE_LIB_DIR / "govlib"

# Refresh fetches FULL data — a sampled frame would silently change what
# every number means. No LLM context to protect, so the caps are about
# container memory and CKAN politeness only.
_DEFAULT_MAX_RECORDS = 2_000_000
_DEFAULT_MAX_BYTES = 300_000_000
_DEFAULT_TOTAL_BYTES = 600_000_000
# Ceiling on an input's uploaded-file DOWNLOAD (all columns), separate from
# the export caps above, which bound the normalized output (only the
# recipe's `columns`). Over it the input pages the datastore instead. The
# job's /tmp is in memory: this + the exports already fetched must fit in
# the container next to the builder (largest recipe file 879MB, 2026-11-04).
_DEFAULT_FILE_MAX_BYTES = 1_500_000_000
_DEFAULT_WALL_BUDGET_S = 900.0
# A wall-budget overrun is transient (slow CKAN); this many in a row since
# the last full fetch means the dataset outgrew its budget → `too_large`.
# Counted in RUNS: the job runs twice a day (06:00 + 14:00), so 6 ≈ 3 days.
_DEFAULT_WALL_BUDGET_STRIKES = 6
# Same idea for every `StrikeError` (a map-file download the WAF blocked):
# this many runs in a row → its `escalate_to` reason, which opens an issue.
# Also 6 runs ≈ 3 days at two runs a day.
_DEFAULT_TRANSIENT_STRIKES = 6
# In-run second pass: a source whose CKAN fetch/preview failed transiently is
# retried once at the end of the run instead of waiting for the next run (CKAN slowness
# comes in bursts — 2026-11-02 lost 16 previews in a 40-minute window while
# other sources fetched fine). At most this many sources are deferred per run
# (REFRESH_RETRY_CAP; later ones fail as before), so an outage can't double
# the run, and the pass starts at least REFRESH_RETRY_DELAY_S after the last
# deferral.
_DEFAULT_RETRY_CAP = 20
_DEFAULT_RETRY_DELAY_S = 120.0
# A `map` input's file download cap (REFRESH_MAP_MAX_BYTES): it is parsed
# in the builder process, not the compute sandbox. 100MB admits the parcel
# blocks (65MB), survey-boundary (84MB) and aquifer (85MB) layers; parsing an
# 84MB shapefile peaks at ~1.8GB RSS, see the TODO.md map-memory item.
_DEFAULT_MAP_MAX_BYTES = 100_000_000
_DEFAULT_PAGE_SIZE = 100_000
_PAGE_TIMEOUT_S = 60.0
_COMPUTE_TIMEOUT_S = 300
# Heap cap for compute (see `_memory_guard`). The job has 4Gi; the rest is
# the builder, the page cache and the exported CSVs on the tmpfs.
_DEFAULT_COMPUTE_MEMORY_MB = 3072
# What the root builder reads back from compute, which runs outside the
# compute heap cap. model.json over REFRESH_MODEL_MAX_BYTES fails as
# `too_large` before it is read (largest model seen while authoring: 109KB,
# 2026-11-11; 0 = no cap). Of stdout / stderr only the last
# REFRESH_COMPUTE_OUTPUT_TAIL_BYTES are kept (errors quote 1,500 chars).
# REFRESH_COMPUTE_FILE_MAX_BYTES is compute's RLIMIT_FSIZE, so its scratch
# files can't fill the in-memory /tmp; never below the largest input the
# recipe may fetch (the host writes the inputs, but a recipe may copy one).
_DEFAULT_MODEL_MAX_BYTES = 64 * 1024 * 1024
_DEFAULT_COMPUTE_OUTPUT_TAIL_BYTES = 64 * 1024
_DEFAULT_COMPUTE_FILE_MAX_BYTES = 1_000_000_000
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
STAGE_FAILED = FailReason.STAGE_FAILED
MAX_CONSECUTIVE_STAGE_FAILURES = 3
AUTHORING_REASONS = frozenset({
    FailReason.RECIPE_FAILED, FailReason.SCHEMA_CHANGED, FailReason.TOO_LARGE,
    FailReason.GEOMETRY_STALE, FailReason.DOWNLOAD_BLOCKED,
})


def _clip(msg: str, head: int = 150, tail: int = 450) -> str:
    """Keep what a traceback is about (head) AND where it ended (tail)."""
    return msg if len(msg) <= head + tail else f"{msg[:head]} … {msg[-tail:]}"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
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

    def source_config(self, dataset_id: str) -> SourceConfig | None:
        path = self.root / dataset_id / SOURCE_CONFIG_FILENAME
        if not path.is_file():
            return None
        return SourceConfig.model_validate_json(path.read_text(encoding="utf-8"))


class GithubRecipeRepo:
    """Recipes read straight from git — `recipes/` at a branch of the
    (public) repo. Production's source of truth: merging a recipe PR is what
    puts a dataset on the recipe list, with no sync step or write grant.

    The branch is resolved to one commit per run (git trees API), and every
    file is fetched at that commit, so a merge landing mid-run can't mix
    two versions of a recipe.

    `fetch` (env RECIPES_FETCH): `files` downloads each recipe file on its own
    from raw.githubusercontent.com — 3+ sequential requests per recipe, ~0.6s
    each from me-west1, so ~9.5 min/run at 317 recipes, growing with every
    recipe. `tarball` downloads the commit's archive once (~5MB) and extracts
    `recipes/` locally; a recipe loaded either way is byte-identical.
    """

    FETCH_MODES = ("files", "tarball")
    # The whole repo's archive (~5MB compressed on 2026-11-04). A fuse, not a
    # budget: far above any plausible repo, far below the container's disk.
    TARBALL_MAX_BYTES = 200_000_000

    def __init__(self, repo: str, ref: str = "main", token: str | None = None,
                 fetch: str = "files"):
        if fetch not in self.FETCH_MODES:
            raise ValueError(f"RECIPES_FETCH must be one of {self.FETCH_MODES}, got {fetch!r}")
        self.repo, self.ref, self.fetch = repo, ref, fetch
        self._headers = github.api_headers(token)
        self._sha: str | None = None
        self._ids: list[str] | None = None
        self._with_source: set[str] = set()
        self._tree: Path | None = None  # extracted `recipes/` (tarball mode)

    def _get(self, url: str, **kw):
        import httpx

        r = httpx.get(url, headers=self._headers, timeout=30.0,
                      follow_redirects=True, **kw)
        r.raise_for_status()
        return r

    def list_ids(self) -> list[str]:
        if self._ids is None:
            sha = self._get(
                f"{github.API}/repos/{self.repo}/commits/{self.ref}"
            ).json()["sha"]
            self._sha = sha
            ids, with_source = set(), set()
            if self.fetch == "tarball":
                # The list comes from the archive itself, eagerly, here: the
                # pipeline's recipe-list step turns a failure into
                # `refresh_unavailable`. Lazily (first load) it would fail
                # every recipe as `recipe_invalid` and open an authoring
                # issue for each.
                tree = self._extracted()
                for d in tree.iterdir():
                    if (d / MANIFEST_FILENAME).is_file():
                        ids.add(d.name)
                    if (d / SOURCE_CONFIG_FILENAME).is_file():
                        with_source.add(d.name)
            else:
                listing = self._get(
                    f"{github.API}/repos/{self.repo}/git/trees/{sha}",
                    params={"recursive": "1"},
                ).json()
                if listing.get("truncated"):
                    raise RuntimeError("git tree listing truncated — recipe list incomplete")
                for node in listing.get("tree") or []:
                    parts = node.get("path", "").split("/")
                    if len(parts) == 3 and parts[0] == "recipes" and parts[2] == MANIFEST_FILENAME:
                        ids.add(parts[1])
                    elif (len(parts) == 3 and parts[0] == "recipes"
                          and parts[2] == SOURCE_CONFIG_FILENAME):
                        with_source.add(parts[1])
            self._ids = sorted(ids)
            self._with_source = with_source & ids
        return list(self._ids)

    def provider_source_ids(self) -> list[str]:
        return [i for i in self.list_ids() if i in self._with_source]

    def source_config(self, dataset_id: str) -> SourceConfig | None:
        if dataset_id not in set(self.provider_source_ids()):
            return None
        return SourceConfig.model_validate_json(
            self._read(dataset_id, SOURCE_CONFIG_FILENAME)
        )

    def load(self, dataset_id: str, scratch: Path) -> Recipe:
        def fetch(name: str, dest: Path) -> None:
            dest.write_bytes(self._read(dataset_id, name))

        return _load_remote(scratch / dataset_id, fetch)

    def _read(self, dataset_id: str, name: str) -> bytes:
        """One recipe file at the run's commit."""
        if self._sha is None:
            self.list_ids()
        if self.fetch == "tarball":
            path = self._extracted() / dataset_id / name
            if not path.is_file():
                raise RecipeError(f"recipe {dataset_id} missing {name} at {self._sha[:12]}")
            return path.read_bytes()
        return self._get(
            f"https://raw.githubusercontent.com/{self.repo}/{self._sha}/"
            f"recipes/{dataset_id}/{name}"
        ).content

    def _extracted(self) -> Path:
        """`recipes/` at the run's commit, from one archive download. Lives
        for the process (the job's container); a failure raises, and the
        caller treats it like a failed recipe list."""
        if self._tree is not None:
            return self._tree
        started = time.monotonic()
        root = Path(tempfile.mkdtemp(prefix="recipes-tar-"))
        try:
            size, n = self._download_and_extract(root)
        except BaseException:
            shutil.rmtree(root, ignore_errors=True)
            raise
        # Removed with this repo object, or at interpreter exit: local runs
        # would otherwise leave a copy of every recipe in /tmp each time.
        weakref.finalize(self, shutil.rmtree, root, True)
        log.info("recipes: %d files from the %s archive (%d bytes) in %.1fs",
                 n, self._sha[:12], size, time.monotonic() - started)
        self._tree = root / "tree"
        return self._tree

    def _download_and_extract(self, root: Path) -> tuple[int, int]:
        import tarfile

        import httpx

        archive = root / "repo.tar.gz"
        # The API answers with a redirect to codeload.github.com (httpx drops
        # the Authorization header on the cross-host hop; a private repo's
        # redirect URL carries its own token).
        with httpx.stream(
            "GET", f"{github.API}/repos/{self.repo}/tarball/{self._sha}",
            headers=self._headers, timeout=60.0, follow_redirects=True,
        ) as r:
            r.raise_for_status()
            size = 0
            with archive.open("wb") as f:
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > self.TARBALL_MAX_BYTES:
                        raise RuntimeError(
                            f"repo archive exceeds {self.TARBALL_MAX_BYTES:,} bytes"
                        )
                    f.write(chunk)
        out = root / "tree"
        out.mkdir()
        with tarfile.open(archive, "r:gz") as tar:
            # Every member sits under one top dir (`<owner>-<repo>-<sha>/`);
            # keep only regular files at recipes/<id>/<name>. The `data`
            # filter also refuses absolute paths, `..` and links.
            members, tops = [], set()
            for m in tar.getmembers():
                parts = m.name.split("/")
                if len(parts) > 1:
                    tops.add(parts[0])
                if (m.isfile() and len(parts) == 4 and parts[1] == "recipes"
                        and parts[2] and parts[3]):
                    m.name = f"{parts[2]}/{parts[3]}"
                    members.append(m)
            if len(tops) != 1:
                raise RuntimeError(f"repo archive has {len(tops)} top-level dirs, expected 1")
            tar.extractall(out, members=members, filter="data")
        archive.unlink()
        return size, len(members)


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


def recipe_repo_from_env() -> LocalRecipeRepo | GithubRecipeRepo:
    """RECIPES_SOURCE:
      github:<owner/repo>@<ref>   (default: PUBLISH_GITHUB_REPO @ main)
      a local directory           (tests, local runs)
    RECIPES_FETCH (github only): `files` (default) | `tarball` — see
    `GithubRecipeRepo`.
    """
    src = os.environ.get("RECIPES_SOURCE", "").strip()
    if not src:
        src = f"github:{github.default_repo()}@main"
    if src.startswith("github:"):
        repo, _, ref = src[len("github:"):].partition("@")
        return GithubRecipeRepo(
            repo, ref or "main",
            token=github.token() or None,
            fetch=os.environ.get("RECIPES_FETCH", "files").strip().lower() or "files",
        )
    return LocalRecipeRepo(Path(src))


# ── fetch ────────────────────────────────────────────────────────────────


@dataclass
class FetchedInput:
    file: Path
    resource_id: str
    resource_name: str
    rows: int
    via: str | None = None        # CKAN export: "file" | "datastore"


@dataclass
class InputProbe:
    """Inputs resolved against CKAN + the datastore previews that resolution
    needed. `fetch_inputs` reuses it, so probing for the precheck adds no
    CKAN calls."""

    resolved: dict[str, list[dict]]
    _previews: dict[str, dict | None]
    _preview_fn: Callable[[str], dict | None]

    def preview(self, rid: str) -> dict | None:
        if rid not in self._previews:
            try:
                self._previews[rid] = self._preview_fn(rid)
            except FetchLimitExceeded as e:
                # A provider reads the whole series to preview it.
                raise _limit_error(e, f"preview of {rid[:8]}") from None
        return self._previews[rid]

    def answered(self) -> bool:
        """Every datastore preview asked so far this run came back (and at
        least one was asked)."""
        return bool(self._previews) and all(
            p is not None for p in self._previews.values()
        )


class WallBudgetExceeded(RecipeError):
    """A fetch ran out of wall budget. Transient (`fetch_failed`) on its
    own; `refresh_one` counts them and escalates a run of them."""

    def __init__(self, message: str):
        super().__init__(message, reason=FailReason.FETCH_FAILED)


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
            reason=FailReason.TOO_LARGE,
        )
    if e.limit == "wall_budget":
        return WallBudgetExceeded(f"{what}: ran out of wall budget ({e})")
    raise AssertionError(f"unhandled fetch limit {e.limit!r}")


def probe_inputs(
    recipe: Recipe,
    resources: list[dict],
    preview_fn: Callable[[str], dict | None] = fetch_resource_preview,
) -> InputProbe:
    """Resolve the recipe's inputs. Raises RecipeError `schema_changed` when
    they no longer resolve, StrikeError `preview_unavailable` when a preview
    they needed didn't answer; ResourceRestrictedError passes through."""
    previews: dict[str, dict | None] = {}
    probe = InputProbe({}, previews, preview_fn)

    def _fields(rid: str) -> list[str] | None:
        p = probe.preview(rid)
        return [f["id"] for f in (p or {}).get("fields") or []] if p else None

    try:
        probe.resolved = resolve_inputs(recipe.manifest, resources, _fields)
    except PreviewUnavailable as e:
        raise _preview_strike(str(e)) from None
    return probe


_PREVIEW_STRIKE = "preview_unavailable"


def _preview_strike(message: str) -> StrikeError:
    """A datastore preview that didn't answer. Slow CKAN, not a schema change:
    retried next run; an issue opens only once it repeats (e.g. a resource
    dropped from the datastore)."""
    return StrikeError(message, reason=FailReason.FETCH_FAILED, strike=_PREVIEW_STRIKE,
                       escalate_to=FailReason.SCHEMA_CHANGED)


def _strikes_after_probe(state: RefreshState, probe: InputProbe | None) -> dict | None:
    """The `transient_strikes` to write once this run's previews answered:
    a run of preview failures is broken, so that count restarts. None = leave
    the stored map alone (also when no preview was asked yet, e.g. a `by_id`
    input with no column check, whose preview comes only in `fetch_inputs`)."""
    strikes = state.transient_strikes or {}
    if probe is None or _PREVIEW_STRIKE not in strikes or not probe.answered():
        return None
    return {k: v for k, v in strikes.items() if k != _PREVIEW_STRIKE}


# Shared code between the data and the page: the compute runner, template
# rendering/validation, the sanitizer, and the CKAN export with its shared
# helpers (CSV normalization, the file URL, `pick: "latest"`'s date parsing
# shape the inputs compute sees, and fingerprint A can't see that). A deploy that changes any of them can change the output with
# identical data, so it invalidates both prechecks. The check.py gate
# (page_gate.py) doesn't shape output, so it isn't here.
_RENDER_CODE_FILES = (
    RECIPE_EXEC_PATH,
    Path(__file__).resolve().parent / "recipe.py",
    Path(__file__).resolve().parent / "sanitize.py",
    Path(__file__).resolve().parent / "ckan_export.py",
    Path(__file__).resolve().parents[1] / "shared" / "ckan.py",
    Path(__file__).resolve().parent / "schema.py",  # validators rewrite agent_data
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
    # Only recipes that import the shared lib: a lib change re-renders them,
    # not every page.
    if _uses_recipe_lib(recipe):
        h.update(_recipe_lib_hash().encode())
    return h.hexdigest()


@functools.lru_cache(maxsize=1)
def _geo_code_hash() -> str:
    return hashlib.sha256(_GEO_CODE_FILE.read_bytes()).hexdigest()


# Any mention counts (`import os, govlib`, `{%+ import "gov.j2" %}`, ...): a
# false positive only folds one more hash, a miss would let the precheck
# skip a page whose lib output changed.
_USES_GOVLIB = re.compile(r"\bgovlib\b")
_USES_MACROS = re.compile(r"\bgov\.j2\b")


def _uses_recipe_lib(recipe: Recipe) -> bool:
    def text(name: str) -> str:
        return (recipe.root / name).read_text(encoding="utf-8", errors="replace")

    return bool(_USES_GOVLIB.search(text("compute.py"))
                or _USES_MACROS.search(text("template.html.j2")))


@functools.lru_cache(maxsize=1)
def _recipe_lib_hash() -> str:
    # The .j2 macros aren't .py, so _builder_code_hash's rglob misses them;
    # it adds this hash too.
    h = hashlib.sha256()
    for path in sorted(p for p in RECIPE_LIB_DIR.rglob("*") if p.is_file()
                       and "__pycache__" not in p.parts):
        h.update(str(path.relative_to(RECIPE_LIB_DIR)).encode())
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


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
    h.update(_recipe_lib_hash().encode())
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
    columns, first rows (`_id` dropped) — plus each resource's name and
    `recipe_identity`. A snapshot
    input has no datastore; its bytes are already in the identity. A map
    input contributes CKAN's size/md5 of its file."""
    parts = []
    for inp in recipe.manifest.inputs:
        if inp.snapshot:
            parts.append([inp.name, inp.by_id, "snapshot"])
            continue
        if inp.map:
            res = probe.resolved[inp.name][0]
            parts.append([inp.name, inp.by_id, "map", res.get("size"), res.get("hash"),
                          res.get("name") or ""])
            continue
        for res in probe.resolved[inp.name]:
            p = probe.preview(res["id"]) or {}
            parts.append(
                [
                    inp.name,
                    res["id"],
                    res.get("name") or "",
                    *_preview_shape(p),
                    [
                        {k: v for k, v in row.items() if k != "_id"}
                        for row in p.get("sample_rows") or []
                    ],
                ]
            )
    return _digest(parts, identity)


def file_fingerprint(recipe: Recipe, probe: InputProbe, identity: str) -> str | None:
    """Check A′: CKAN's md5 + size of every input's uploaded file, its
    resource name, the preview's row total and columns, plus `recipe_identity`. None when any
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
            parts.append([inp.name, inp.by_id, "map", res["hash"], res.get("size"),
                          res.get("name") or ""])
            continue
        for res in probe.resolved[inp.name]:
            if not res.get("hash"):
                return None
            p = probe.preview(res["id"]) or {}
            parts.append(
                [inp.name, res["id"], res.get("name") or "", res["hash"], res.get("size"),
                 *_preview_shape(p)]
            )
    return _digest(parts, identity)


_MULTISET_MOD = 1 << 256


def inputs_hashes(
    recipe: Recipe, inputs: dict[str, list[FetchedInput]], identity: str
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
            # The resource name reaches compute and the template; length-prefixed
            # since it can hold any character.
            rname = part.resource_name.encode()
            tag = f"{inp.name}|{part.resource_id}|{len(rname)}|".encode() + rname
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
    recipe: Recipe, inputs: dict[str, list[FetchedInput]], identity: str
) -> str:
    """Check B alone (see `inputs_hashes`)."""
    return inputs_hashes(recipe, inputs, identity)[0]


def content_hash(page: RenderedPage) -> str:
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
    preview_fn: Callable[[str], dict | None] = fetch_resource_preview,
    fetch_fn: Callable = fetch_resource_export,
    probe: InputProbe | None = None,
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
    file_max_bytes = _env_int("REFRESH_FILE_MAX_BYTES", _DEFAULT_FILE_MAX_BYTES)
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
            p = _preview(rid)
            if p is None:
                # A by_id input with no column check meets its preview here.
                raise _preview_strike(f"input {inp.name!r}: no preview for resource {rid[:8]}")
            total = int(p.get("total") or 0)
            # A provider resource marked optional (a CBS table some editions
            # lack) may be empty by design: compute gets a header-only frame.
            if total <= 0 and not (res.get("params") or {}).get("optional"):
                raise RecipeError(
                    f"input {inp.name!r}: resource {rid[:8]} has no rows",
                    reason=FailReason.FETCH_FAILED,
                )
            if total > max_records:
                raise RecipeError(
                    f"input {inp.name!r}: {total:,} rows > REFRESH_MAX_RECORDS "
                    f"{max_records:,}",
                    reason=FailReason.TOO_LARGE,
                )
            dest = dest_dir / f"{inp.name}__{i + 1}.csv"
            cap = min(max_bytes, remaining)
            if cap <= 0:
                raise RecipeError(
                    f"input {inp.name!r}: earlier inputs used the whole "
                    "REFRESH_TOTAL_BYTES budget",
                    reason=FailReason.TOO_LARGE,
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
                    fields=inp.columns,
                    # The uploaded file is tried first; the datastore preview
                    # is what it must match (ckan_export.fetch_resource_csv).
                    resource=res,
                    preview=_preview(rid),
                    file_max_bytes=file_max_bytes,
                )
            except FetchLimitExceeded as e:
                raise _limit_error(e, f"input {inp.name!r}: export of {rid[:8]}") from None
            if outcome is None:
                raise RecipeError(
                    f"input {inp.name!r}: full fetch of {rid[:8]} failed (fetch error)",
                    reason=FailReason.FETCH_FAILED,
                )
            if inp.columns:
                _project_csv(dest, inp.columns)
            remaining -= outcome.bytes
            parts.append(
                FetchedInput(dest, rid, res.get("name") or "", outcome.rows,
                             getattr(outcome, "via", None))
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
                          reason=FailReason.TOO_LARGE)
    try:
        try:
            got = fetch_file_fn(res.get("url") or "", raw, max_bytes=max_bytes,
                                timeout_s=_PAGE_TIMEOUT_S, deadline=deadline)
        except FetchLimitExceeded as e:
            raise _limit_error(e, f"{what}: download") from None
        except DownloadBlocked as e:
            raise StrikeError(f"{what}: download blocked ({e})", reason=FailReason.FETCH_FAILED,
                              strike="download_blocked", escalate_to=FailReason.DOWNLOAD_BLOCKED) from None
        except ValueError as e:  # not a data.gov.il URL: the resource moved off-site
            raise RecipeError(f"{what}: {e}", reason=FailReason.SCHEMA_CHANGED) from None
        except urllib_error.HTTPError as e:
            if e.code in (404, 410):
                raise StrikeError(f"{what}: the file is gone (HTTP {e.code})", reason=FailReason.FETCH_FAILED,
                                  strike="download_missing", escalate_to=FailReason.SCHEMA_CHANGED) from None
            raise RecipeError(f"{what}: download failed ({e})", reason=FailReason.FETCH_FAILED) from None
        except (urllib_error.URLError, OSError, http.client.HTTPException) as e:  # timeouts too
            raise RecipeError(f"{what}: download failed ({e!r})", reason=FailReason.FETCH_FAILED) from None
    except BaseException:  # any failed download: no partial file left behind
        raw.unlink(missing_ok=True)
        raise
    # Converted as it streams off the file (see `geo_snapshot.iter_map`): the
    # raw layer never sits in memory whole, beside the converted one, and the
    # converted features go straight to rows, never through a GeoJSON body.
    try:
        feats, crs = geo_snapshot.iter_map(raw, _map_file_name(res))
        layer = geo_snapshot.simplify_features(
            feats, crs=crs,
            max_bytes=(inp.map_max_kb * 1000) if inp.map_max_kb else geo_snapshot.DEFAULT_MAX_BYTES,
        )
    except geo_snapshot.SnapshotTooLarge as e:
        raise RecipeError(f"{what}: {e} (map_max_kb)", reason=FailReason.TOO_LARGE) from None
    except geo_snapshot.SnapshotError as e:
        raise RecipeError(f"{what}: {e}", reason=FailReason.SCHEMA_CHANGED) from None
    finally:
        feats = None
        raw.unlink(missing_ok=True)
    tol = layer.tol
    doc = {"type": "FeatureCollection",
           "features": [{"properties": p, "geometry": None if g == "null" else g}
                        for p, g in layer.features]}
    del layer
    header, rows = feature_table(doc, what, reason=FailReason.SCHEMA_CHANGED)
    del doc
    lost = [c for c in inp.required_columns if c not in header]
    if lost:
        raise RecipeError(f"{what}: lacks column(s) {lost}", reason=FailReason.SCHEMA_CHANGED)
    rows = transform(rows)
    if not rows:
        raise RecipeError(f"{what}: has no features", reason=FailReason.SCHEMA_CHANGED)
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
            f"{path.name}: export lacks column(s) {lost}", reason=FailReason.SCHEMA_CHANGED
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
    `limits.compute_memory_mb`, else REFRESH_COMPUTE_MEMORY_MB; 0 = no cap.
    It also caps each file it writes (RLIMIT_FSIZE, REFRESH_COMPUTE_FILE_MAX_BYTES)."""
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
    fsize = _env_int("REFRESH_COMPUTE_FILE_MAX_BYTES", _DEFAULT_COMPUTE_FILE_MAX_BYTES)
    if fsize > 0:
        largest_input = max(
            limits.max_bytes or _env_int("REFRESH_MAX_BYTES", _DEFAULT_MAX_BYTES),
            limits.total_bytes or max(
                _env_int("REFRESH_TOTAL_BYTES", _DEFAULT_TOTAL_BYTES), limits.max_bytes or 0
            ),
        )
        n = max(fsize, largest_input)
        # Python ignores SIGXFSZ, so a write past it raises OSError (EFBIG).
        code += (
            f"import resource; _fsize = {n}\n"
            "_h = resource.getrlimit(resource.RLIMIT_FSIZE)[1]\n"
            "if _h != resource.RLIM_INFINITY:\n"
            "    _fsize = min(_fsize, _h)\n"
            "resource.setrlimit(resource.RLIMIT_FSIZE, (_fsize, _fsize))\n"
        )
    return code


class _SpawnFlake(RecipeError):
    """compute() died to the known fork/gRPC abort, not to recipe code.

    Not an authoring reason: as `recipe_failed` it would open an issue and
    lock the source out (`needs_refresh` skips a failed version) until the
    data moved, though the same recipe renders fine on the next spawn.
    """

    def __init__(self, message: str):
        super().__init__(message, reason=FailReason.SANDBOX_FAILED)


def _is_spawn_flake(error_value: str, stderr: str) -> bool:
    return error_value == "exit code -6" and "ev_epoll1_linux" in stderr


def run_compute(
    recipe: Recipe,
    inputs: dict[str, list[FetchedInput]],
    work_root: Path,
    *,
    timeout: int | None = None,
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
    model_max = _env_int("REFRESH_MODEL_MAX_BYTES", _DEFAULT_MODEL_MAX_BYTES)
    tail = _env_int("REFRESH_COMPUTE_OUTPUT_TAIL_BYTES", _DEFAULT_COMPUTE_OUTPUT_TAIL_BYTES)
    sandbox = LocalSandbox.create(workdir, max_read_bytes=model_max if model_max > 0 else None)
    try:
        (workdir / "recipe").mkdir()
        for name in RECIPE_FILES:
            shutil.copyfile(recipe.root / name, workdir / "recipe" / name)
        shutil.copyfile(RECIPE_EXEC_PATH, workdir / "recipe_exec.py")
        # On sys.path as the cwd ('' under `python -c`), so compute.py can
        # `from govlib import ...`.
        shutil.copytree(GOVLIB_DIR, workdir / "govlib",
                        ignore=shutil.ignore_patterns("__pycache__"))
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
            max_output_bytes=tail if tail > 0 else _DEFAULT_COMPUTE_OUTPUT_TAIL_BYTES,
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
        except OutputTooLarge as e:
            raise RecipeError(
                f"compute() model.json too large: {e} (REFRESH_MODEL_MAX_BYTES)",
                reason=FailReason.TOO_LARGE,
            ) from None
        try:
            model = json.loads(raw.decode("utf-8"))
        except ValueError as e:  # bad JSON or bad UTF-8: what compute() returned
            raise RecipeError(f"compute() wrote an unreadable model.json: {e}") from e
        if not isinstance(model, dict):
            raise RecipeError(
                f"compute() model.json is a {type(model).__name__}, not an object"
            )
        return model
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
    inputs: dict[str, list[FetchedInput]] | None = None,
) -> RenderedPage:
    """Model → validated body. Same gates an agent page passed: sanitizer,
    then the image's check.py on the sanitized output."""
    model = validate_model(raw_model, recipe.manifest)
    agent_data = model.agent_data.model_dump(mode="json", exclude_none=True)
    template_src = recipe.template_path.read_text(encoding="utf-8")
    # The template sees exactly what compute() returned (extras included).
    html = render_template(template_src, raw_model, inputs_context(inputs or {}))
    try:
        html = sanitize_content_html(html, dataset_id=recipe.dataset_id)
    except ValueError as e:  # e.g. unbalanced <style>/<script>: the template's output
        raise RecipeError(str(e)) from e
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
    probe: InputProbe | None = None,
    after_fetch: Callable[[dict[str, list[FetchedInput]]], None] | None = None,
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


def version_key(metadata_modified: datetime | None, recipe_version: int) -> str:
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


def needs_refresh(src, state: RefreshState, recipe: Recipe) -> str | None:
    """Why this source should be refreshed now, or None to skip it."""
    if src is None:
        return None
    if src.analysis_status in NO_DATA_STATUSES:
        return None  # data gone upstream; keep the frozen page
    rv = recipe.manifest.recipe_version
    if (state.refresh_reason in AUTHORING_REASONS
            and state.refresh_failed_version == failed_version_key(src, recipe)):
        return None  # same data + recipe + builder would fail the same way
    if state.recipe_version != rv:
        return "recipe_version"
    done = state.refreshed_metadata_modified
    if done is None:
        return "never_refreshed"
    if src.metadata_modified and src.metadata_modified > done:
        return "data_updated"
    return None


def _write_gcs(data: bytes, bucket: str, relpath: str) -> str:
    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(relpath)
    ctype = ("application/gzip" if relpath.endswith(".gz")
             else "text/html; charset=utf-8")
    blob.upload_from_string(data, content_type=ctype)
    return f"gs://{bucket}/{relpath}"


def _stage_model_history(src_id: str, model: dict, *, bucket: str,
                         write_gcs: Callable[[bytes, str, str], str],
                         recipe_version: int | None = None,
                         metadata_modified: datetime | None = None,
                         now: datetime | None = None) -> bool:
    """Write the render's model to models/<id>/<UTC ts>.json.gz and
    models/<id>/latest.json.gz (read by the news job). Best effort: a failure
    is logged, never fails the refresh (the page is already staged and marked).
    `recipe_version` + `metadata_modified` let a reader tell a recipe change
    (model shape moved) from a data change."""
    ts = model_history.stamp(now or datetime.now(UTC))
    try:
        body = model_history.encode(src_id, model, ts=ts, recipe_version=recipe_version,
                                    metadata_modified=metadata_modified)
        for name in model_history.object_names(src_id, ts):
            write_gcs(body, bucket, name)
        return True
    except Exception:
        log.warning("refresh %s: writing model history failed", src_id[:8], exc_info=True)
        return False


def _read_gcs(bucket: str, relpath: str) -> bytes | None:
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
    status: OutcomeStatus
    trigger: str | None = None
    reason: str | None = None
    error: str | None = None
    elapsed_s: float = 0.0
    rows: dict = field(default_factory=dict)
    kpis: dict = field(default_factory=dict)
    insights: list = field(default_factory=list)
    changes: dict = field(default_factory=dict)
    issue: int | None = None
    # REFRESH_PRECHECK report: {mode, fp_same, fp2_same, inputs_same,
    # inputs_same_unordered, content_same, skipped}
    # (True/False; None = no stored hash to compare against yet).
    precheck: dict = field(default_factory=dict)
    # Which path served each CKAN input export: {resource id8: "file" | "datastore"}.
    fetch_via: dict = field(default_factory=dict)
    # True on the outcome of the end-of-run second pass (see _DEFAULT_RETRY_CAP).
    retried: bool | None = None


class _Unchanged(Exception):
    """Precheck proved the inputs identical to the last render — stop before
    the expensive steps. `reason` is `fingerprint` or `inputs_hash`
    (`content_hash`, the post-render check, doesn't raise)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _precheck_may_skip(trigger: str, state: RefreshState) -> bool:
    """Skipping is only safe for a plain data bump on a recently re-rendered
    page: a forced run, a recipe_version change, or a page older than
    REFRESH_PRECHECK_MAX_AGE_DAYS (bounds check A's blind spot and picks up
    shell-code changes that alter output without any data change) always
    re-render. The age runs from the last full render, including one that
    came out identical (`last_verified_at`): it proved the live page right."""
    if trigger != "data_updated":
        return False
    stamps = [state.last_refreshed_at, state.last_verified_at]
    stamps = [t if t.tzinfo else t.replace(tzinfo=UTC) for t in stamps if t]
    if not stamps:
        return False
    last = max(stamps)
    max_age = _env_int("REFRESH_PRECHECK_MAX_AGE_DAYS", _DEFAULT_PRECHECK_MAX_AGE_DAYS)
    return datetime.now(UTC) - last <= timedelta(days=max_age)


def _same(new: str, old: str | None) -> bool | None:
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
    staging_bucket: str,
    work_root: Path,
    trigger: str,
    previous_state: RefreshState | None = None,
    notify: bool = True,
    write_gcs: Callable[[bytes, str, str], str] = _write_gcs,
    read_gcs: Callable[[str, str], bytes | None] = _read_gcs,
    providers=None,
    defer_transient: bool = False,
    **fetch_kwargs,
) -> RefreshOutcome:
    """Refresh one recipe'd source. With `defer_transient`, a failure worth
    retrying later in the run (`_retry_later`) writes nothing — no state, no
    strike, no issue — and returns status `retry_later`; `run_refresh` calls
    again without the flag, which records the outcome as usual."""
    started = time.monotonic()
    rv = recipe.manifest.recipe_version
    resources = src.resources
    provider_key = src.provider
    if provider_key:
        # A non-CKAN source: its provider fetches (services/providers), CKAN
        # is never called. Disabled provider → leave the last-good page.
        p = provider_for_key(provider_key, providers)
        if p is None:
            log.info("refresh %s: provider %s is disabled — skipped", src.id, provider_key)
            return RefreshOutcome(src.id, OutcomeStatus.SKIPPED, trigger, f"provider_disabled:{provider_key}")
        resources = fetchable_resources(src.resources)
        preview_fn, fetch_fn = p.fetch_fns(resources)
        fetch_kwargs.setdefault("preview_fn", preview_fn)
        fetch_kwargs.setdefault("fetch_fn", fetch_fn)
    mode = precheck_mode()
    state = previous_state if previous_state is not None else RefreshState()
    may_skip = mode != "off" and _precheck_may_skip(trigger, state)
    pc: dict = {"mode": mode} if mode != "off" else {}
    hashes: dict[str, str | None] = {}  # stored on success; names match mark_refreshed kwargs
    try:
        probe = None
        after_fetch = None
        # Up front in every mode (fetch_inputs reuses it): a probe that
        # answered breaks a run of `preview_unavailable` strikes.
        probe = probe_inputs(
            recipe, resources, fetch_kwargs.get("preview_fn", fetch_resource_preview)
        )
        if mode != "off":
            identity = recipe_identity(recipe)
            fp = hashes["input_fingerprint"] = input_fingerprint(recipe, probe, identity)
            pc["fp_same"] = _same(fp, state.input_fingerprint)
            ff = hashes["file_fingerprint"] = file_fingerprint(recipe, probe, identity)
            pc["fp2_same"] = _same(ff, state.file_fingerprint) if ff else None
            if may_skip and mode == "full" and pc["fp_same"] and pc["fp2_same"]:
                raise _Unchanged("fingerprint")

            def after_fetch(inputs):
                ih, iu = inputs_hashes(recipe, inputs, identity)
                hashes["inputs_hash"], hashes["inputs_hash_unordered"] = ih, iu
                pc["inputs_same"] = _same(ih, state.inputs_hash)
                pc["inputs_same_unordered"] = _same(iu, state.inputs_hash_unordered)
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
            advance_version=u.reason == "inputs_hash", started=started,
            transient_strikes=_strikes_after_probe(state, probe),
        )
    except ResourceRestrictedError as e:
        # Data went private upstream. Not the recipe's fault, not
        # actionable by re-authoring; the reconcile sweep owns this state.
        log.warning("refresh %s: restricted upstream: %s", src.id[:8], e)
        return RefreshOutcome(src.id, OutcomeStatus.FAILED, trigger, FailReason.RESTRICTED, str(e))
    except RecipeError as e:
        if defer_transient and _retry_later(e):
            log.warning("refresh %s: %s — retrying at the end of the run", src.id[:8], e)
            return RefreshOutcome(
                src.id, OutcomeStatus.RETRY_LATER, trigger, e.reason, _clip(str(e)),
                round(time.monotonic() - started, 2),
            )
        strikes = None
        if isinstance(e, WallBudgetExceeded):
            strikes = int(state.wall_budget_strikes or 0) + 1
            limit = _env_int("REFRESH_WALL_BUDGET_STRIKES", _DEFAULT_WALL_BUDGET_STRIKES)
            if strikes >= limit:
                # Reset, so a re-authored recipe gets a fresh run of tries.
                e = RecipeError(
                    f"{e} — {strikes} runs in a row since the last full fetch",
                    reason=FailReason.TOO_LARGE,
                )
                strikes = 0
        transient = _strikes_after_probe(state, probe)
        if isinstance(e, StrikeError):
            # A preview strike (even one in fetch_inputs) continues the run.
            if transient is None or e.strike == _PREVIEW_STRIKE:
                transient = dict(state.transient_strikes or {})
            n = int(transient.get(e.strike) or 0) + 1
            if n >= _env_int("REFRESH_TRANSIENT_STRIKES", _DEFAULT_TRANSIENT_STRIKES):
                transient.pop(e.strike, None)  # a fresh run of tries after the fix
                e = RecipeError(f"{e} — {n} runs in a row", reason=e.escalate_to)
            else:
                transient[e.strike] = n
        log.warning("refresh %s failed (%s): %s", src.id[:8], e.reason, e)
        try:
            store.mark_refresh_failed(
                src.id,
                error=str(e),
                reason=e.reason,
                failed_version=failed_version_key(src, recipe),
                wall_budget_strikes=strikes,
                transient_strikes=transient,
            )
        except Exception as me:
            # Nothing recorded, so the next run retries it (and files the
            # issue then). A failed state write counts as a staging failure.
            log.exception("refresh %s: recording the failure failed", src.id[:8])
            return RefreshOutcome(
                src.id, OutcomeStatus.FAILED, trigger, STAGE_FAILED,
                _clip(f"{e.reason}: {e}; {type(me).__name__}: {me}"),
                round(time.monotonic() - started, 2),
            )
        outcome = RefreshOutcome(
            src.id, OutcomeStatus.FAILED, trigger, e.reason, _clip(str(e)),
            round(time.monotonic() - started, 2),
        )
        if notify and e.reason in AUTHORING_REASONS:
            outcome.issue = _queue_authoring_safely(
                store, src, e.reason, detail=str(e)
            )
        return outcome
    except Exception as e:  # infra bug, not a data/recipe verdict
        log.exception("refresh %s crashed", src.id[:8])
        try:
            store.mark_refresh_failed(
                src.id,
                error=f"{type(e).__name__}: {e}",
                reason=FailReason.ERROR,
                failed_version=failed_version_key(src, recipe),
            )
        except Exception as me:
            log.exception("refresh %s: recording the crash failed", src.id[:8])
            return RefreshOutcome(
                src.id, OutcomeStatus.FAILED, trigger, STAGE_FAILED,
                _clip(f"{type(e).__name__}: {e}; {type(me).__name__}: {me}"),
            )
        return RefreshOutcome(src.id, OutcomeStatus.FAILED, trigger, FailReason.ERROR, _clip(str(e)))

    snapshot = {
        "rows": {k: sum(p.rows for p in v) for k, v in inputs.items()},
        "kpis": {
            k: (v or {}).get("display") for k, v in (page.model.get("kpis") or {}).items()
        },
        "insights": [i.get("text_he") for i in page.model.get("insights") or []],
        "warnings": page.warnings,
    }
    fetch_via = {p.resource_id[:8]: p.via for v in inputs.values() for p in v if p.via}
    if page.warnings:
        log.warning("refresh %s: %d format warning(s): %s", src.id[:8],
                    len(page.warnings), "; ".join(page.warnings)[:500])
    previous = state.last_snapshot
    if mode != "off":
        ch = hashes["content_hash"] = content_hash(page)
        pc["content_same"] = _same(ch, state.content_hash)
        _log_precheck(src.id, pc)
        # C: a data bump that rendered the live page byte for byte. Exact, so
        # no max-age gate; a forced run or a recipe_version change still
        # stages (the latter must record its version through mark_refreshed).
        # After a staging failure the staged body may not be the one the
        # stored hash describes (a failed rollback), so that render stages.
        staging_suspect = (state.refresh_status == RefreshStatus.FAILED
                           and state.refresh_reason == STAGE_FAILED)
        if (mode in ("inputs", "full") and trigger == "data_updated"
                and pc["content_same"] and not staging_suspect):
            out = _mark_unchanged(
                store, src, trigger, "content_hash", pc, hashes,
                advance_version=True, started=started,
                rows=snapshot["rows"],
            )
            out.fetch_via = fetch_via
            return out
    rel = f"datasets/{src.id}/{CONTENT_FILENAME}"
    previous_html: bytes | None = None
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
            )
        except Exception:
            log.exception("refresh %s: recording the staging failure failed", src.id[:8])
        return RefreshOutcome(
            src.id, OutcomeStatus.FAILED, trigger, STAGE_FAILED, _clip(str(e)),
            round(time.monotonic() - started, 2),
        )
    _stage_model_history(src.id, page.model, bucket=staging_bucket,
                         write_gcs=write_gcs, recipe_version=rv,
                         metadata_modified=src.metadata_modified)
    return RefreshOutcome(
        src.id,
        OutcomeStatus.REFRESHED,
        trigger,
        elapsed_s=round(time.monotonic() - started, 2),
        rows=snapshot["rows"],
        kpis=snapshot["kpis"],
        insights=snapshot["insights"],
        changes=snapshot_diff(previous, snapshot),
        precheck=pc,
        fetch_via=fetch_via,
    )


def _mark_unchanged(
    store, src, trigger: str, reason: str, pc: dict, hashes: dict, *,
    advance_version: bool, started: float, rows: dict | None = None,
    transient_strikes: dict | None = None,
) -> RefreshOutcome:
    """Record a precheck skip (the live page stands). A failed state write is
    a staging failure like a failed `mark_refreshed`: this source only,
    retried next run, counted toward `staging_down`. `transient_strikes`
    (from `_strikes_after_probe`) matters only after a fingerprint skip: an
    input-hash skip fetched everything, so the store clears them all."""
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
            transient_strikes=transient_strikes,
        )
    except Exception as e:
        log.exception("refresh %s: recording the unchanged state failed", src.id[:8])
        return RefreshOutcome(
            src.id, OutcomeStatus.FAILED, trigger, STAGE_FAILED, _clip(str(e)),
            round(time.monotonic() - started, 2), precheck=pc,
        )
    log.info("refresh precheck %s: unchanged (%s) — skipped", src.id[:8], reason)
    return RefreshOutcome(
        src.id, OutcomeStatus.UNCHANGED, trigger, reason,
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


def snapshot_diff(before: dict | None, after: dict) -> dict:
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


def queue_authoring(store, src, reason: str, *, detail: str = "") -> int | None:
    """Flag a dataset for local authoring and open its issue (once).

    A recorded issue is reused while it is open or was closed as not
    planned. One closed as completed means a recipe PR landed and this is a
    new need (e.g. the recipe later failed), so a fresh issue is opened, as
    when the recorded issue was deleted."""
    from . import notify as _notify

    state = RefreshState.from_dict(store.get_refresh_state(src.id))  # fresh: guards duplicate issues
    store.mark_authoring_needed(src.id, reason)
    recorded = state.authoring_issue
    if recorded and _notify.issue_state(int(recorded)) not in ("completed", "gone"):
        # Back to `notified`, which mark_authoring_needed just overwrote:
        # the daily queue skips notified sources.
        store.set_authoring_issue(src.id, int(recorded))
        return int(recorded)
    number = _notify.open_authoring_issue(
        dataset_id=src.id,
        title=src.title or src.id,
        org=(src.organization or {}).get("title", "") or "",
        reason=reason,
        detail=detail,
        source_url=getattr(src, "source_url", None),
    )
    if number is not None:
        store.set_authoring_issue(src.id, number)
    return number


def _queue_authoring_safely(store, src, reason: str, **kw) -> int | None:
    """queue_authoring for use mid-batch: a Firestore/GitHub error costs this
    source its issue (retried next run), never the rest of the refresh."""
    try:
        return queue_authoring(store, src, reason, **kw)
    except Exception:
        log.exception("queueing %s for authoring failed", src.id[:8])
        return None


def _retry_later(e: RecipeError) -> bool:
    """A failure a second try minutes later may not hit: CKAN/network
    trouble. Not a wall-budget overrun (the dataset is slow; a retry doubles
    the time) nor a map download strike (a WAF block or a 404 won't clear
    within the run)."""
    if e.reason != FailReason.FETCH_FAILED or isinstance(e, WallBudgetExceeded):
        return False
    return not isinstance(e, StrikeError) or e.strike == _PREVIEW_STRIKE


def _spends_cap(o: RefreshOutcome) -> bool:
    # A `retry_later` slot keeps its place: the retry pass refreshes it.
    return o.status != OutcomeStatus.SKIPPED and not (
        o.status == OutcomeStatus.UNCHANGED and o.reason == "fingerprint"
    )


def run_refresh(
    store,
    repo,
    *,
    staging_bucket: str,
    only_ids: list[str] | None = None,
    cap: int | None = None,
    force: bool = False,
    notify: bool = True,
    work_root: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> dict:
    """Refresh every eligible recipe'd source (sequentially — a refresh is
    CKAN-bound and cheap; there is no model latency to hide), then retry the
    transient fetch failures once (see `_DEFAULT_RETRY_CAP`)."""
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
    retry_cap = max(0, _env_int("REFRESH_RETRY_CAP", _DEFAULT_RETRY_CAP))
    # outcome index, src, recipe, trigger, refresh state (the deferral wrote nothing)
    deferred: list[tuple[int, object, Recipe, str, RefreshState]] = []
    last_deferred_at = 0.0

    # Failed outcomes recorded without a successful state write.
    _NO_WRITE = (FailReason.ERROR, FailReason.RESTRICTED, FailReason.RECIPE_INVALID)

    def _count_staging(outcome: RefreshOutcome) -> None:
        nonlocal stage_failures, staging_down
        if outcome.reason == STAGE_FAILED:
            stage_failures += 1
            if stage_failures >= MAX_CONSECUTIVE_STAGE_FAILURES:
                log.error(
                    "refresh: %d staging failures in a row — stopping the batch",
                    stage_failures,
                )
                staging_down = True
        elif outcome.status in (OutcomeStatus.REFRESHED, OutcomeStatus.UNCHANGED) or (
            outcome.status == OutcomeStatus.FAILED and outcome.reason not in _NO_WRITE
        ):
            # Its state write went through, so the store is up.
            stage_failures = 0

    def _queue():
        for dataset_id in ids:
            yield dataset_id, None
        yield from heavy

    try:
        for dataset_id, recipe in _queue():
            if staging_down:
                outcomes.append(RefreshOutcome(dataset_id, OutcomeStatus.SKIPPED, reason="staging_down"))
                continue
            # A fingerprint skip made no export, so it doesn't spend the cap.
            if len([o for o in outcomes if _spends_cap(o)]) >= cap:
                outcomes.append(RefreshOutcome(dataset_id, OutcomeStatus.SKIPPED, reason="cap"))
                continue
            try:
                src = store.get_source(dataset_id)
            except Exception as e:
                # A store error, like a failed state write: this source only,
                # counted toward `staging_down`.
                log.exception("refresh %s: reading the source doc failed", dataset_id[:8])
                outcome = RefreshOutcome(dataset_id, OutcomeStatus.FAILED, reason=STAGE_FAILED,
                                         error=_clip(f"{type(e).__name__}: {e}"))
                outcomes.append(outcome)
                _count_staging(outcome)
                continue
            if src is None:
                outcomes.append(RefreshOutcome(dataset_id, OutcomeStatus.SKIPPED, reason="no_source_doc"))
                continue
            if recipe is None:
                try:
                    recipe = repo.load(dataset_id, scratch)
                except Exception as e:
                    log.exception("recipe %s failed to load", dataset_id[:8])
                    outcome = RefreshOutcome(
                        dataset_id, OutcomeStatus.FAILED, reason=FailReason.RECIPE_INVALID, error=_clip(str(e))
                    )
                    # The page can't refresh until the recipe is fixed, so it
                    # needs authoring like any other broken recipe. Idempotent:
                    # the open issue is reused every night until then.
                    if notify:
                        outcome.issue = _queue_authoring_safely(
                            store, src, AuthoringReason.RECIPE_FAILED, detail=str(e)
                        )
                    outcomes.append(outcome)
                    continue
                if recipe.manifest.heavy:
                    heavy.append((dataset_id, recipe))
                    continue
            trigger = None
            try:
                state = src.refresh  # read with the source doc: one read per source
                trigger = "forced" if force else needs_refresh(src, state, recipe)
                if trigger is None:
                    outcomes.append(RefreshOutcome(dataset_id, OutcomeStatus.SKIPPED, reason="up_to_date"))
                    continue
                log.info("refreshing %s (%s) — %s", dataset_id[:8], trigger, (src.title or "")[:60])
                outcome = refresh_one(
                    src, recipe, store=store,
                    staging_bucket=staging_bucket, work_root=work_root,
                    trigger=trigger, previous_state=state, notify=notify,
                    defer_transient=len(deferred) < retry_cap, **kwargs,
                )
            except Exception as e:
                # One source's crash must not cost the outcomes already made.
                log.exception("refresh %s crashed", dataset_id[:8])
                outcome = RefreshOutcome(dataset_id, OutcomeStatus.FAILED, trigger,
                                         FailReason.ERROR, _clip(f"{type(e).__name__}: {e}"))
            if outcome.status == OutcomeStatus.RETRY_LATER:
                deferred.append((len(outcomes), src, recipe, trigger, state))
                last_deferred_at = time.monotonic()
            outcomes.append(outcome)
            _count_staging(outcome)
        if deferred and not staging_down:
            wait = _env_float("REFRESH_RETRY_DELAY_S", _DEFAULT_RETRY_DELAY_S) - (
                time.monotonic() - last_deferred_at
            )
            log.info("refresh: retrying %d transient failure(s)%s", len(deferred),
                     f" in {wait:.0f}s" if wait > 0 else "")
            if wait > 0:
                sleep(wait)
        # Each deferred slot already counted toward the cap, so no cap check.
        for i, src, recipe, trigger, state in deferred:
            if staging_down:
                outcomes[i] = RefreshOutcome(src.id, OutcomeStatus.SKIPPED, reason="staging_down")
                continue
            try:
                outcome = refresh_one(
                    src, recipe, store=store,
                    staging_bucket=staging_bucket, work_root=work_root,
                    trigger=trigger, previous_state=state, notify=notify, **kwargs,
                )
            except Exception as e:
                log.exception("refresh %s crashed", src.id[:8])
                outcome = RefreshOutcome(src.id, OutcomeStatus.FAILED, trigger,
                                         FailReason.ERROR, _clip(f"{type(e).__name__}: {e}"))
            outcome.retried = True
            outcomes[i] = outcome
            _count_staging(outcome)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    refreshed = [o.id for o in outcomes if o.status == OutcomeStatus.REFRESHED]
    unchanged = [o.id for o in outcomes if o.status == OutcomeStatus.UNCHANGED]
    failed = [o.id for o in outcomes if o.status == OutcomeStatus.FAILED]
    return {
        "recipes": len(ids),
        "refreshed": refreshed,
        "unchanged": unchanged,
        "failed": failed,
        "staging_down": staging_down,
        "outcomes": [o.__dict__ for o in outcomes],
    }
