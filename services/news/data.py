"""A dataset's full tables, exactly as its recipe reads them — for the SQL tool.

Same path as the refresh: the recipe from git main (`recipe_repo.recipe_repo_from_env`),
the source's resources from Firestore, `refresh.fetch_inputs` (CKAN export,
or the provider's fetchers for non-CKAN sources), then `recipe_exec.load_frames`
(all-text columns). Loaded lazily, once per dataset per run, into a DuckDB
table (`query.TableQuery`): the pandas frames and the downloaded files are
dropped as soon as the table exists, so the run keeps one copy per dataset.

A news load is capped below the refresh's limits (the job has 4GiB and holds
the run's other datasets too): NEWS_TABLE_MAX_ROWS (default 1,000,000 rows over
all of the recipe's inputs, checked from the datastore previews before any
download, then from the export) and NEWS_TABLE_MAX_BYTES (default 150 MB of
exported CSV, checked before pandas reads it). A dataset over either cap is
`DataUnavailable`: the writer works from the page's series and KPIs instead.
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path

from services.shared.env import env_int

from .query import TableQuery

log = logging.getLogger(__name__)


_DATASET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
DEFAULT_MAX_ROWS = 1_000_000
DEFAULT_MAX_BYTES = 150_000_000


class DataUnavailable(Exception):
    pass


class DatasetTables:
    def __init__(self, store=None, recipe_repo=None, *, work_root: Path | None = None,
                 max_rows: int | None = None, max_bytes: int | None = None):
        self._store, self._repo = store, recipe_repo
        self._root = Path(tempfile.mkdtemp(prefix="news-data-", dir=work_root))
        self._cache: dict[str, TableQuery] = {}
        self._failed: dict[str, str] = {}
        self.max_rows = max_rows if max_rows is not None else env_int("NEWS_TABLE_MAX_ROWS", DEFAULT_MAX_ROWS)
        self.max_bytes = (max_bytes if max_bytes is not None
                          else env_int("NEWS_TABLE_MAX_BYTES", DEFAULT_MAX_BYTES))

    def __call__(self, dataset_id: str) -> TableQuery:
        """The dataset's tables in DuckDB, shared by every story of the run
        (closed by `close`, not by the Toolbox)."""
        if dataset_id in self._failed:   # an over-cap dataset is not fetched again for the next story
            raise DataUnavailable(self._failed[dataset_id])
        if dataset_id not in self._cache:
            # The id names the scratch dir (removed below): a plain id, never a path.
            if not _DATASET_ID.fullmatch(dataset_id or ""):
                raise DataUnavailable(f"not a dataset id: {str(dataset_id)[:60]!r}")
            work = self._root / dataset_id
            try:
                frames = self._load(dataset_id, work)
            except DataUnavailable as e:
                self._failed[dataset_id] = str(e)
                raise
            finally:
                shutil.rmtree(work, ignore_errors=True)   # the files: the frames are in memory now
            # TableQuery pops each frame once its table exists: no second copy stays.
            self._cache[dataset_id] = TableQuery(frames, consume=True)
        return self._cache[dataset_id]

    def _check_rows(self, dataset_id: str, rows: int, when: str) -> None:
        if rows > self.max_rows:
            raise DataUnavailable(f"{dataset_id} has {rows:,} rows {when}, over the news load cap "
                                  f"of {self.max_rows:,} (NEWS_TABLE_MAX_ROWS)")

    def _load(self, dataset_id: str, work: Path) -> dict:
        from services.page_builder.recipe_exec import load_frames
        from services.page_builder.refresh import (
            fetch_inputs,
            fetchable_resources,
            probe_inputs,
        )
        from services.providers import provider_for_key

        if self._store is None or self._repo is None:
            raise DataUnavailable("no data access configured for this run")
        src = self._store.get_source(dataset_id)
        if src is None:
            raise DataUnavailable(f"unknown dataset {dataset_id}")
        recipe = self._repo.load(dataset_id, work / "recipe")
        resources, kw = src.resources, {}
        if src.provider:
            p = provider_for_key(src.provider)
            if p is None:
                raise DataUnavailable(f"provider {src.provider} is disabled")
            resources = fetchable_resources(src.resources)
            kw["preview_fn"], kw["fetch_fn"] = p.fetch_fns(resources)
        try:
            probe = (probe_inputs(recipe, resources, kw["preview_fn"]) if "preview_fn" in kw
                     else probe_inputs(recipe, resources))
            # Before any download: the datastore previews' row totals (map and
            # snapshot inputs have none and are bounded by the bytes check).
            expected = sum(int((probe.preview(r["id"]) or {}).get("total") or 0)
                           for i in recipe.manifest.inputs if not (i.snapshot or i.map)
                           for r in probe.resolved.get(i.name, []))
            self._check_rows(dataset_id, expected, "in the datastore")
            inputs = fetch_inputs(recipe, resources, work / "data", probe=probe, **kw)
        except DataUnavailable:
            raise
        except Exception as e:  # RecipeError (too_large, schema_changed, fetch_failed) included
            raise DataUnavailable(f"fetch failed: {e}") from e
        parts = [p for ps in inputs.values() for p in ps]
        self._check_rows(dataset_id, sum(p.rows for p in parts), "exported")
        nbytes = sum(p.file.stat().st_size for p in parts if p.file.exists())
        if nbytes > self.max_bytes:
            raise DataUnavailable(f"{dataset_id} exported {nbytes:,} bytes, over the news load cap "
                                  f"of {self.max_bytes:,} (NEWS_TABLE_MAX_BYTES)")
        concat = {i.name: bool(getattr(i, "concat", False)) for i in recipe.manifest.inputs}
        spec = {name: [{"file": str(p.file), "resource_name": p.resource_name,
                        "concat": concat.get(name, False)} for p in parts]
                for name, parts in inputs.items()}
        frames = load_frames(spec)
        return {_table_name(n): df for n, df in frames.items()}

    def close(self):
        for q in self._cache.values():
            q.close()
        self._cache.clear()
        shutil.rmtree(self._root, ignore_errors=True)


def _table_name(n: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_]", "_", n)
    return t if re.match(r"[A-Za-z_]", t) else f"t_{t}"
