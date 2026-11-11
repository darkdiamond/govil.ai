"""A dataset's full tables, exactly as its recipe reads them — for the SQL tool.

Same path as the refresh: the recipe from git main (`recipe_repo.recipe_repo_from_env`),
the source's resources from Firestore, `refresh.fetch_inputs` (CKAN export,
or the provider's fetchers for non-CKAN sources), then `recipe_exec.load_frames`
(all-text columns). Loaded lazily, once per dataset per run, in a scratch dir
removed on close.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


class DataUnavailable(Exception):
    pass


class DatasetTables:
    def __init__(self, store=None, recipe_repo=None, *, work_root: Path | None = None):
        self._store, self._repo = store, recipe_repo
        self._root = Path(tempfile.mkdtemp(prefix="news-data-", dir=work_root))
        self._cache: dict[str, dict[str, pd.DataFrame]] = {}

    def __call__(self, dataset_id: str) -> dict[str, pd.DataFrame]:
        if dataset_id not in self._cache:
            self._cache[dataset_id] = self._load(dataset_id)
        return self._cache[dataset_id]

    def _load(self, dataset_id: str) -> dict[str, pd.DataFrame]:
        from services.page_builder.recipe_exec import load_frames
        from services.page_builder.refresh import fetch_inputs, fetchable_resources
        from services.providers import provider_for_key

        if self._store is None or self._repo is None:
            raise DataUnavailable("no data access configured for this run")
        src = self._store.get_source(dataset_id)
        if src is None:
            raise DataUnavailable(f"unknown dataset {dataset_id}")
        work = self._root / dataset_id[:8]
        recipe = self._repo.load(dataset_id, work / "recipe")
        resources, kw = src.resources, {}
        if src.provider:
            p = provider_for_key(src.provider)
            if p is None:
                raise DataUnavailable(f"provider {src.provider} is disabled")
            resources = fetchable_resources(src.resources)
            kw["preview_fn"], kw["fetch_fn"] = p.fetch_fns(resources)
        try:
            inputs = fetch_inputs(recipe, resources, work / "data", **kw)
        except Exception as e:  # RecipeError (too_large, schema_changed, fetch_failed) included
            raise DataUnavailable(f"fetch failed: {e}") from e
        concat = {i.name: bool(getattr(i, "concat", False)) for i in recipe.manifest.inputs}
        spec = {name: [{"file": str(p.file), "resource_name": p.resource_name,
                        "concat": concat.get(name, False)} for p in parts]
                for name, parts in inputs.items()}
        frames = load_frames(spec)
        return {_table_name(n): df for n, df in frames.items()}

    def close(self):
        shutil.rmtree(self._root, ignore_errors=True)


def _table_name(n: str) -> str:
    import re

    t = re.sub(r"[^A-Za-z0-9_]", "_", n)
    return t if re.match(r"[A-Za-z_]", t) else f"t_{t}"
