"""Numeric env knobs: a missing, empty or malformed value is the default.

Stdlib only, so every layer (builder, news, scanner, providers) can use it.
"""
from __future__ import annotations

import os


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default
