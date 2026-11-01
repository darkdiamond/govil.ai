"""pandas idioms recipes repeat: deterministic counts, top-N, cleaning, parsing.

Columns arrive as str (recipe_exec reads every CSV with dtype=str), so the
helpers here take str Series unless they say otherwise.
"""
import re

import pandas as pd

OTHER = "אחר"


def ranked(series: pd.Series) -> pd.Series:
    """value_counts with a deterministic order: count descending, ties by
    value ascending. Plain value_counts leaves tie order to the hash table."""
    return series.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _py(v):
    return v.item() if hasattr(v, "item") else v


def top_other(counts: pd.Series, n: int, other: str = OTHER):
    """The first `n` entries of an already-ordered Series (e.g. `ranked`)
    plus one `other` entry summing the rest. Returns (labels, values) as
    plain Python lists. No `other` entry when nothing is left over; if
    exactly one entry would be folded, it is shown by name instead."""
    if len(counts) <= n + 1:
        return [str(k) for k in counts.index], [_py(v) for v in counts]
    head = counts.iloc[:n]
    labels = [str(k) for k in head.index] + [other]
    return labels, [_py(v) for v in head] + [_py(counts.iloc[n:].sum())]


_SPACE = re.compile(r"\s+")


def clean(s) -> str:
    """Collapse whitespace and strip; None and NaN give ''."""
    if s is None or (isinstance(s, float) and s != s):
        return ""
    return _SPACE.sub(" ", str(s)).strip()


def clean_series(series: pd.Series) -> pd.Series:
    """`clean` over a str Series, vectorized."""
    return series.fillna("").astype(str).str.replace(_SPACE, " ", regex=True).str.strip()


_NUM_JUNK = re.compile(r"[,\s₪%‎‏⁦-⁩]")


def num(series: pd.Series) -> pd.Series:
    """Parse a str Series of numbers to float: drops thousands commas, ₪, %,
    whitespace and bidi marks; reads U+2212 as minus. Unparseable → NaN."""
    s = series.astype(str).str.replace(_NUM_JUNK, "", regex=True).str.replace("−", "-", regex=False)
    return pd.to_numeric(s, errors="coerce")
