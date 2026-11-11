"""Where the refresh reads recipes from: git `main` (`GithubRecipeRepo`, per
file or one tarball) or a local directory (`LocalRecipeRepo`), chosen by
`recipe_repo_from_env`. Re-exported by `refresh`, which the pipeline and the
tests use; the news job imports it from here."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import weakref
from collections.abc import Callable
from pathlib import Path

from services.providers import SOURCE_CONFIG_FILENAME, SourceConfig
from services.shared import github

from .recipe import (
    MANIFEST_FILENAME,
    RECIPE_FILES,
    Recipe,
    RecipeError,
    RecipeManifest,
)

# The refresh's logger: these lines read as they did inside refresh.py.
log = logging.getLogger("page_builder.refresh")


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


def _is_transient_fetch_error(e: BaseException) -> bool:
    """A recipe file download that failed in transit (timeout, connection,
    GitHub 5xx or rate limit), not a missing or broken recipe: retried next
    run. A 404 and anything the recipe's own bytes caused stay recipe errors."""
    import httpx

    if isinstance(e, httpx.TransportError):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        r = e.response
        return (r.status_code >= 500 or r.status_code == 429
                or (r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0"))
    return False


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
