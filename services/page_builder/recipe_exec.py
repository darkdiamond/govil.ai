"""Run a recipe's compute() — the part of a refresh that executes recipe code.

Self-contained on purpose (stdlib + pandas only, no `services.*` imports):
it is copied into a LocalSandbox workdir and run there with a scrubbed env,
the same isolation agent tool commands get. Layout it expects in its cwd:

    inputs.json        {"<input>": [{"file": "data/x.csv",
                                     "resource_name": "...",
                                     "concat": bool}, ...], ...}
    recipe/compute.py  defines compute(frames: dict[str, DataFrame]) -> dict
    data/*.csv         the fetched resources

and writes `outputs/model.json`. Any exception exits non-zero with the
traceback on stderr; the host turns that into a RecipeError.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

RESOURCE_NAME_COLUMN = "_resource_name"


def load_frames(spec: dict) -> dict:
    frames = {}
    for name, parts in spec.items():
        dfs = []
        for p in parts:
            # str-only, no NA inference — see services/page_builder/recipe.py.
            df = pd.read_csv(p["file"], dtype=str, keep_default_na=False)
            if p.get("concat"):
                df[RESOURCE_NAME_COLUMN] = p.get("resource_name") or ""
            dfs.append(df)
        frames[name] = dfs[0] if len(dfs) == 1 else pd.concat(dfs, ignore_index=True)
    return frames


def _json_default(o):
    # numpy scalars (np.int64 from a groupby count, …) and timestamps are
    # the two types pandas code hands back without trying.
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(f"{type(o).__name__} is not JSON serializable")


def main() -> int:
    spec = json.loads(Path("inputs.json").read_text(encoding="utf-8"))
    mod_spec = importlib.util.spec_from_file_location("recipe_compute", "recipe/compute.py")
    mod = importlib.util.module_from_spec(mod_spec)
    sys.path.insert(0, str(Path("recipe").resolve()))
    mod_spec.loader.exec_module(mod)
    model = mod.compute(load_frames(spec))
    if not isinstance(model, dict):
        raise TypeError(f"compute() returned {type(model).__name__}, expected dict")
    Path("outputs").mkdir(exist_ok=True)
    # allow_nan=False: a NaN/inf in the model is a bug in the recipe (it
    # would serialize as invalid JSON and break the chart), not a value.
    Path("outputs/model.json").write_text(
        json.dumps(model, ensure_ascii=False, allow_nan=False, default=_json_default),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
