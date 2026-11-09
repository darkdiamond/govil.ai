"""Reading CBS release tables: the grid the `cbs_releases` provider emits.

A table resource arrives as one row per non-empty sheet row: `RELEASE_NO,
RELEASE_DATE, SHEET_NO, SHEET, ROW, C01..Cnn`, cells as printed. A recipe
finds header rows and columns by their label text, and data rows by pattern:

    rows = cbs.grid(frames["t1"], "t1")        # newest edition, cleaned cells
    h = cbs.row_with(rows, "Cruise", name="t1")  # raises when the label is gone
    air = cbs.col_after(rows[h], "By Air", 0)
    for i, year, month, end in cbs.periods(rows, h + 1, len(rows)):
        v = cbs.num(rows[i][air])

Header lookups raise ValueError (the refresh fails as recipe_failed and
keeps the last page); `num` returns None for CBS's missing-value marks.
"""
import re

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
         "IX": 9, "X": 10, "XI": 11, "XII": 12}
# "..": unknown or not for publication; "-": no cases; "x": suppressed.
MISSING = frozenset({"", "..", "-", "—", "–", "x", "X"})
# Footnote marks: "(1)", "(R)" revised, "*" provisional.
_FOOTNOTE = re.compile(r"\((?:\d+|R)\)|\*")
_SPACE = re.compile(r"\s+")
YEAR = re.compile(r"^(19|20)\d\d$")
# A month or a month range: "X", "I-X", "I-XII".
PERIOD = re.compile(r"^([IVX]+)(?:-([IVX]+))?$")
_CELL = re.compile(r"C\d+")


def clean(v) -> str:
    """A cell without footnote marks, whitespace collapsed:
    `" 2026 * "` → `"2026"`, `"Trend(R)"` → `"Trend"`."""
    return _SPACE.sub(" ", _FOOTNOTE.sub(" ", str(v))).strip()


def num(v):
    """A cell as a float, or None for a missing-value mark or text."""
    v = clean(v)
    if v in MISSING:
        return None
    try:
        return float(v.replace(",", ""))
    except ValueError:
        return None


def cell(row, j):
    return row[j] if 0 <= j < len(row) else ""


def val(row, j):
    """`num` of row[j], None past the row's end."""
    return num(cell(row, j))


def _release_key(release_no: str):
    """"345/2026" → (2026, 345): CBS numbers releases within a year."""
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d{4})\s*", str(release_no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def latest_release(df, name="releases") -> dict:
    """The newest edition in a `releases` frame, as a dict of its columns
    (RELEASE_NO, RELEASE_DATE, TITLE, HEADLINE, PAGE_URL, REPORT_PDF_URL).
    Same order as `grid`: the newest date, and of two editions that share
    it, the higher release number ("100/2026" beats "99/2026", which a plain
    string sort gets wrong). Raises when no edition has a date."""
    df = df[df["RELEASE_DATE"].fillna("").astype(str).str.strip() != ""]
    if df.empty:
        raise ValueError(f"{name}: no edition listed")
    best = max(df.to_dict("records"),
               key=lambda r: (str(r["RELEASE_DATE"]), _release_key(r["RELEASE_NO"]),
                              str(r["RELEASE_NO"])))
    return best


def grid(df, name="table") -> list:
    """The newest edition's rows of one table (all sheets, in sheet and row
    order) as lists of cleaned cells; index j is column C(j+1). Exactly one
    edition: the newest date, and of two editions that share it, the higher
    release number."""
    if df.empty:
        raise ValueError(f"{name}: empty grid")
    latest = df["RELEASE_DATE"].max()
    df = df[df["RELEASE_DATE"] == latest]
    newest = max(df["RELEASE_NO"].unique(), key=lambda n: (_release_key(n), n))
    df = df[df["RELEASE_NO"] == newest].sort_values(["SHEET_NO", "ROW"], kind="stable")
    cols = sorted((c for c in df.columns if _CELL.fullmatch(c)), key=lambda c: int(c[1:]))
    return [[clean(v) for v in row] for row in df[cols].itertuples(index=False)]


def row_with(rows, label, start=0, name="table", contains=False) -> int:
    """Index of the first row at or after `start` with a cell equal to
    `label` (or containing it). Raises when there is none."""
    for i in range(max(0, start), len(rows)):
        if any((label in c) if contains else (c == label) for c in rows[i]):
            return i
    raise ValueError(f"{name}: header label {label!r} not found")


def col_after(row, label, start=0, contains=False) -> int:
    """Index of the first cell at or after column `start` equal to `label`
    (or containing it). Raises when there is none."""
    for j in range(max(0, start), len(row)):
        if (label in row[j]) if contains else (row[j] == label):
            return j
    raise ValueError(f"header label {label!r} not found after column {start}")


def best_col(rows, pred, exclude=()):
    """The column whose cells most often satisfy `pred` (ties: leftmost),
    or None. Use it for label columns: a data column can hold a 4-digit
    value that looks like a year, but not as often as the year column."""
    counts: dict[int, int] = {}
    for r in rows:
        for j, v in enumerate(r):
            if j not in exclude and v and pred(v):
                counts[j] = counts.get(j, 0) + 1
    if not counts:
        return None
    return min(counts, key=lambda j: (-counts[j], j))


def periods(rows, start, stop):
    """`[(row index, year, month, end)]` for the data rows in rows[start:stop].

    The year column is the one holding the most 4-digit years, the month
    column the one holding the most roman months; a year carries down to the
    rows below it. `month` is None for a whole-year row (a year and no
    month), `end` is the range end for a range like `I-X` (month 1, end 10),
    else None. Rows with neither are skipped."""
    body = rows[start:stop]
    mcol = best_col(body, lambda v: bool(PERIOD.match(v)) and PERIOD.match(v).group(1) in ROMAN)
    ycol = best_col(body, lambda v: bool(YEAR.match(v)), exclude={mcol})
    if ycol is None:
        raise ValueError("no year column")
    out, year = [], None
    for i in range(start, stop):
        r = rows[i]
        y = cell(r, ycol)
        m = cell(r, mcol) if mcol is not None else ""
        if YEAR.match(y):
            year = int(y)
        if year is None:
            continue
        pm = PERIOD.match(m)
        if pm and pm.group(1) in ROMAN:
            end = ROMAN.get(pm.group(2)) if pm.group(2) else None
            out.append((i, year, ROMAN[pm.group(1)], end))
        elif not m and YEAR.match(y):
            out.append((i, year, None, None))
    return out


def monthly_runs(rows, start, stop, value_col):
    """`[(row index, year, month)]` for a chart-data block where the year
    appears only on a year's first row and the month only now and then
    (I, VI, XII): months are counted from the year row. A month mark that
    disagrees with the count raises. Rows without a value are skipped."""
    body = rows[start:stop]
    mcol = best_col(body, lambda v: v in ROMAN)
    ycol = best_col(body, lambda v: bool(YEAR.match(v)), exclude={mcol})
    if ycol is None:
        raise ValueError("no year column")
    out, year, month = [], None, 0
    for i in range(start, stop):
        r = rows[i]
        if val(r, value_col) is None:
            continue
        if YEAR.match(cell(r, ycol)):
            year, month = int(cell(r, ycol)), 1
        elif year is not None:
            month += 1
        if year is None:
            continue
        mark = cell(r, mcol) if mcol is not None else ""
        if mark in ROMAN and ROMAN[mark] != month:
            raise ValueError(f"month mark {mark} on month {month} of {year}")
        if month > 12:
            raise ValueError(f"more than 12 months in {year}")
        out.append((i, year, month))
    return out
