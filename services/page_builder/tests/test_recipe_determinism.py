"""Recipe compute output must not depend on the process's string hash seed.

Each case runs a committed recipe's compute() on a small synthetic frame in
fresh interpreters with different PYTHONHASHSEED values and compares the
serialized model.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RESILIENCE = REPO / "recipes" / "b08ed183-2c26-490f-aa13-f1a7529c3aca"

_DRIVER = r"""
import importlib.util, json, sys
import pandas as pd
spec = importlib.util.spec_from_file_location("compute", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
frames = {k: pd.DataFrame(v) for k, v in json.loads(sys.argv[2]).items()}
print(json.dumps(mod.compute(frames), ensure_ascii=False, sort_keys=True, default=str))
"""


def _run(compute_py: Path, frames: dict, seed: int) -> str:
    env = {**os.environ, "PYTHONHASHSEED": str(seed)}
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER, str(compute_py), json.dumps(frames)],
        capture_output=True, text=True, env=env, check=True, timeout=120,
    )
    return proc.stdout


def _center(code, name, phone, phone2):
    return {"institute_code": code, "institute_name": name, "city": "חיפה",
            "streetCode": "", "address": "", "email": "", "phone": phone,
            "phone2": phone2, "other_cities": "חיפה, טירת כרמל", "el_notes": ""}


def test_resilience_centers_shared_phone_is_hash_seed_independent():
    # Center א lists one number twice in two spellings; center ב shares it,
    # so the shared-phone insight prints one of א's two spellings.
    rows = [
        _center("1", "א", "04-8123456", "048123456"),
        _center("2", "ב", "04 8123456", ""),
        _center("3", "ג", "03-5555555", ""),
    ]
    frames = {"centers": {k: [r[k] for r in rows] for k in rows[0]}}
    outputs = {_run(RESILIENCE / "compute.py", frames, seed) for seed in range(1, 11)}
    assert len(outputs) == 1
