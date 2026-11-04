"""Hebrew page text: numbers, percents, dates, lists.

Every function takes plain Python or numpy scalars and returns a str.
Percent helpers say in their name what scale they take: `pct` a fraction
(0.236), `pct_of` a value already on 0–100 (23.6).
"""
import math
import re

# Bidi isolates: wrap a number or Latin run inside Hebrew text so the
# browser doesn't reorder its sign or unit.
LRI, PDI = "\u2066", "\u2069"
MINUS = "−"

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT_HE = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                   "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]


def isolate(s) -> str:
    return f"{LRI}{s}{PDI}"


def _round_half_up(v: float) -> int:
    # Python's round() is half-to-even (round(2.5) == 2); a page reader
    # expects a median of 2.5 to read 3.
    return math.floor(abs(v) + 0.5) * (1 if v >= 0 else -1)


def int_he(v) -> str:
    """Rounded integer with thousands separators: 1234.5 → '1,235'."""
    return f"{_round_half_up(float(v)):,}"


def num_he(v, digits: int = 1) -> str:
    """Fixed decimals with thousands separators: 1234.56 → '1,234.6'."""
    return f"{float(v):,.{digits}f}"


def pct(fraction, digits: int = 1) -> str:
    """A fraction as a percent: 0.236 → '23.6%'."""
    return f"{float(fraction) * 100:.{digits}f}%"


def pct_of(value, digits: int = 1) -> str:
    """A value already on 0–100 as a percent: 23.6 → '23.6%'."""
    return f"{float(value):.{digits}f}%"


def signed_pct(fraction, digits: int = 1) -> str:
    """A change as a signed percent, minus as U+2212: 0.05 → '+5.0%',
    -0.05 → '−5.0%'. A change that rounds to zero has no sign. NaN or inf
    (a change from zero) raises: the insight rule should drop that sentence."""
    f = float(fraction)
    if not math.isfinite(f):
        raise ValueError(f"signed_pct of {f}")
    body = f"{abs(f) * 100:.{digits}f}"
    if float(body) == 0:
        return f"{body}%"
    return ("+" if f > 0 else MINUS) + body + "%"


def d_he(ts) -> str:
    """A date in words: 2024-03-05 → '5 במרץ 2024'."""
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def month_he(ts) -> str:
    """'מרץ 2024'."""
    return f"{MONTHS_HE[ts.month - 1]} {ts.year}"


_HEBREW_START = re.compile(r"[א-ת]")


def vav(word: str) -> str:
    """Attach the conjunction ו: 'ו' before a Hebrew word, 'ו-' before a
    number or Latin text ('ו-2024', 'ו-ABC')."""
    word = str(word)
    return ("ו" if _HEBREW_START.match(word) else "ו-") + word


def join_he(items) -> str:
    """'א', 'ב', 'ג' → 'א, ב וג'."""
    items = [str(i) for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " " + vav(items[-1])
