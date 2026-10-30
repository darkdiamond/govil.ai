"""הכנסות וגבייה משרד המשפטים (Ministry of Justice charges and collection) — recipe compute.

One CSV per year ("... לשנת 2020"), one row per charge (תנועה): the unit that
issued it, the fee type, the amount, its status and the balance still open.
The files are concatenated (`_resource_name` names the file, and the file's
year is the year of the charge on this page).

Semantics, checked against the data (2026-10):
- "פעילה" is a valid charge. Its "יתרה להתאמה" is the part not yet matched to
  a payment: 0 when paid, the full amount when unpaid. So for active charges
  collected = amount - balance, and the collection rate is collected / billed.
- "פטור" (exempt), "מבוטלת" (cancelled) and "מוקפאת" (frozen) are charges that
  were not collected by design; "סיבת פטור וביטול" says why (free text with
  case numbers, normalised here).
- Balances are as of the file's last update, so recent years can still show
  debts that will be paid later.

The table is ~14M rows over all years, so everything is vectorised: each
string column is factorised once and popped off the frame straight away;
numbers are parsed per distinct value. All aggregates come from one small
cube (year x unit x status x fee type) plus two side tables.

Every number and sentence on the page comes from here. Insight rules return
a sentence or None when their premise does not hold.
"""
import re

import numpy as np
import pandas as pd

C_UNIT = "שם היחידה"
C_STATUS = "סטטוס תנועה"
C_TYPE = "סוג האגרה"
C_AMOUNT = "סכום בשקלים"
C_BAL = "יתרה להתאמה"
C_REASON = "סיבת פטור וביטול"
C_FILE = "_resource_name"

ACTIVE = "פעילה"
EXEMPT = "פטור"
CANCELLED = "מבוטלת"
FROZEN = "מוקפאת"
STATUS_ORDER = [ACTIVE, EXEMPT, CANCELLED, FROZEN]
STATUS_LABEL = {ACTIVE: "פעיל (חיוב תקף)", EXEMPT: "פטור", CANCELLED: "בוטל", FROZEN: "הוקפא"}
PERIODIC = "תקופתית"
SERVICE = "שירות"

TOP_UNITS = 10            # units shown by name in rankings; the rest fold into "אחר"
HEAT_UNITS = 12           # units in the unit x year table
MIN_RATE_BILLED = 1_000_000  # a unit enters the collection-rate chart from this billed sum
MIN_RATE_CHARGES = 500       # ... and this many active charges
TOP_REASONS = 10
MIN_REASON_COUNT = 100    # a reason is named only when this many charges carry it
RATE_OK = 0.9
RATE_WARN = 0.75
TREND_FLAT = 0.03
LOW_MAX = 200      # "small charge" ceiling in the amounts lede (a bucket bound)
HIGH_MIN = 5000    # "large charge" floor in the amounts lede (a bucket bound)

AMOUNT_BUCKETS = [  # (upper bound inclusive, label)
    (0, "0"),
    (50, "1 עד 50"),
    (200, "51 עד 200"),
    (500, "201 עד 500"),
    (1000, "501 עד 1,000"),
    (2000, "1,001 עד 2,000"),
    (5000, "2,001 עד 5,000"),
    (20000, "5,001 עד 20,000"),
    (None, "מעל 20,000"),
]

# Known non-Hebrew reason texts; any other reason without Hebrew folds into "אחר".
REASON_HE = {"Cancel debit due to reject request": "ביטול חיוב עקב דחיית הבקשה"}
_HEB_RE = re.compile(r"[א-ת]")
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _m(x, digits=1):
    """Shekels -> millions, formatted."""
    return f"{x / 1e6:,.{digits}f}"


def _b(name):
    """The Hebrew prefix ב attached to a name (with a hyphen before a non-Hebrew name)."""
    return ("ב" if _HEB_RE.match(str(name)) else "ב-") + str(name)


def _signed_pct(x):
    s = f"{abs(x) * 100:.1f}%"
    return ("+" if x > 0 else "−") + s if abs(x) >= 0.0005 else s


# ── vectorised conversions ──────────────────────────────────────────────


def _labels(s):
    """Strings -> (int codes, stripped labels); codes are value-sorted, so they
    do not depend on row order. Distinct raw values that strip to the same
    label are merged."""
    codes, uniq = pd.factorize(s, sort=True)
    raw = [str(u).strip() for u in uniq]
    labels = sorted(set(raw))
    pos = {l: i for i, l in enumerate(labels)}
    remap = np.array([pos[r] for r in raw] + [-1], dtype="int64")
    return remap[codes], labels


def _numbers(s):
    """Numeric strings (thousands separators allowed) -> float array, NaN when garbage."""
    codes, uniq = pd.factorize(s, sort=True)
    vals = pd.to_numeric(pd.Index(uniq).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")
    arr = np.append(np.asarray(vals, dtype="float64"), np.nan)
    return arr[codes]


def _norm_reason(text):
    t = str(text).strip()
    if not t:
        return ""
    if t in REASON_HE:
        return REASON_HE[t]
    if not _HEB_RE.search(t):
        return "אחר"
    # Case / request numbers make every row unique: drop long digit runs.
    t = re.sub(r"(?:מספר\s*)?\d{3,}", "", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.-:")
    if len(t) > 60:
        t = t[:58].rstrip() + "…"
    return t or "אחר"


def _file_year(name):
    m = _YEAR_RE.findall(str(name))
    return int(m[-1]) if m else None


def _prepare(df):
    n_raw = len(df)
    f_codes, f_names = _labels(df.pop(C_FILE)) if C_FILE in df.columns else (
        np.zeros(n_raw, dtype="int64"), [""])
    f_year = np.array([_file_year(n) or -1 for n in f_names] + [-1], dtype="int64")
    year = f_year[f_codes]

    unit, unit_labels = _labels(df.pop(C_UNIT))
    status, status_labels = _labels(df.pop(C_STATUS))
    ftype, type_labels = _labels(df.pop(C_TYPE))
    amount = _numbers(df.pop(C_AMOUNT))
    bal = _numbers(df.pop(C_BAL))

    r_codes, r_uniq = pd.factorize(df.pop(C_REASON), sort=True)
    r_norm = [_norm_reason(u) for u in r_uniq]
    r_labels = sorted(set(r_norm))
    r_pos = {l: i for i, l in enumerate(r_labels)}
    reason = np.array([r_pos[r] for r in r_norm] + [-1], dtype="int64")[r_codes]
    del r_codes

    bal = np.where(np.isnan(bal), 0.0, np.clip(bal, 0, None))
    keep = (year > 0) & ~np.isnan(amount) & (amount >= 0) & (unit >= 0) & (status >= 0)
    no_year = int(((year <= 0)).sum())
    bad_amount = int((np.isnan(amount) | (amount < 0)).sum())
    bal = np.minimum(bal, np.where(np.isnan(amount), 0.0, amount))
    if ftype.min(initial=0) < 0:
        type_labels = type_labels + ["לא צוין"]
        ftype = np.where(ftype < 0, len(type_labels) - 1, ftype)

    years_present = sorted(set(int(y) for y in np.unique(year[keep])))
    y_pos = {y: i for i, y in enumerate(years_present)}
    y_idx = np.full(int(year.max(initial=0)) + 2, -1, dtype="int64")
    for y, i in y_pos.items():
        y_idx[y] = i

    year, unit, status, ftype, amount, bal, reason = (
        a[keep] for a in (year, unit, status, ftype, amount, bal, reason))
    yi = y_idx[year]

    ny, nu, ns, nt = len(years_present), len(unit_labels), len(status_labels), len(type_labels)
    key = ((yi * nu + unit) * ns + status) * nt + ftype
    size = ny * nu * ns * nt
    cnt = np.bincount(key, minlength=size).reshape(ny, nu, ns, nt)
    amt = np.bincount(key, weights=amount, minlength=size).reshape(ny, nu, ns, nt)
    opn = np.bincount(key, weights=bal, minlength=size).reshape(ny, nu, ns, nt)
    del key

    # Amount distribution of active charges.
    act_code = status_labels.index(ACTIVE) if ACTIVE in status_labels else -1
    bounds = [b for b, _ in AMOUNT_BUCKETS if b is not None]
    act = status == act_code
    bucket = np.searchsorted(np.array(bounds, dtype="float64"), amount[act], side="left")
    buckets = np.bincount(bucket, minlength=len(AMOUNT_BUCKETS))
    bucket_amt = np.bincount(bucket, weights=amount[act], minlength=len(AMOUNT_BUCKETS))

    # Reasons for non-active charges.
    nonact = (status != act_code) & (reason >= 0)
    rk = reason[nonact]
    r_cnt = np.bincount(rk, minlength=len(r_labels))
    r_amt = np.bincount(rk, weights=amount[nonact], minlength=len(r_labels))

    return {
        "years": years_present, "units": unit_labels, "statuses": status_labels,
        "types": type_labels, "cnt": cnt, "amt": amt, "opn": opn,
        "buckets": buckets, "bucket_amt": bucket_amt,
        "r_labels": r_labels, "r_cnt": r_cnt, "r_amt": r_amt,
        "n_raw": n_raw, "n": int(keep.sum()), "no_year": no_year, "bad_amount": bad_amount,
    }


# ── insight rules ───────────────────────────────────────────────────────


def insight_trend(yrs):
    """Billed amount: latest year vs the one before, and vs the first year."""
    if len(yrs) < 2:
        return None
    a, b = yrs[-2], yrs[-1]
    if a["billed"] <= 0:
        return None
    ch = (b["billed"] - a["billed"]) / a["billed"]
    if abs(ch) < TREND_FLAT:
        s = (f"בשנת {b['year']} הסתכמו החיובים התקפים ב-{_m(b['billed'])} מיליון ₪, "
             f"כמעט ללא שינוי לעומת {a['year']} ({_m(a['billed'])} מיליון ₪).")
    else:
        word = "עלייה" if ch > 0 else "ירידה"
        s = (f"בשנת {b['year']} הסתכמו החיובים התקפים ב-{_m(b['billed'])} מיליון ₪, "
             f"{word} של {_pct(abs(ch))} לעומת {a['year']} ({_m(a['billed'])} מיליון ₪).")
    f = yrs[0]
    if len(yrs) >= 4 and f["billed"] > 0:
        mult = b["billed"] / f["billed"]
        if mult >= 1.5:
            s += f" זה פי {mult:.1f} מהסכום בשנת {f['year']}."
    return s


def insight_leader(units, total_billed):
    """The unit that bills the most, when it holds a large share."""
    if not units or total_billed <= 0:
        return None
    u = units[0]
    share = u["billed"] / total_billed
    if share < 0.3:
        return None
    s = (f"{u['name']} לבדו אחראי ל-{_pct(share)} מכל החיובים התקפים במאגר "
         f"({_m(u['billed'])} מיליון ₪ מתוך {_m(total_billed)} מיליון ₪).")
    if len(units) > 1:
        v = units[1]
        s += f" במקום השני: {v['name']} ({_pct(v['billed'] / total_billed)})."
    return s


def insight_volume_value(units, total_count, total_billed):
    """A unit with a big share of the charges but a small share of the money."""
    if len(units) < 2 or total_count <= 0 or total_billed <= 0:
        return None
    by_cnt = sorted(units, key=lambda u: (-u["count"], u["name"]))[:3]
    cands = [(u["count"] / total_count - u["billed"] / total_billed, u) for u in by_cnt]
    cands.sort(key=lambda c: (-c[0], c[1]["name"]))
    u = cands[0][1]
    cs, as_ = u["count"] / total_count, u["billed"] / total_billed
    if cs < 0.1 or cs < 2 * as_:
        return None
    avg = u["billed"] / u["count"] if u["count"] else 0
    return (f"{u['name']} הנפיק {_pct(cs)} מכל החיובים התקפים ({_int(u['count'])}), "
            f"אבל רק {_pct(as_)} מהכסף: החיוב הממוצע שם הוא {_int(avg)} ₪ בלבד.")


def insight_collection(total, weakest):
    """Overall collection rate, and the unit that collects the least."""
    if total["billed"] <= 0:
        return None
    s = (f"מתוך {_m(total['billed'])} מיליון ₪ בחיובים תקפים נגבו {_m(total['collected'])} מיליון ₪ "
         f"({_pct(total['rate'])}); {_m(total['open'])} מיליון ₪ עדיין פתוחים.")
    if weakest and weakest["rate"] < total["rate"] - 0.1:
        s += (f" שיעור הגבייה הנמוך ביותר: {weakest['name']}, {_pct(weakest['rate'])} "
              f"({_m(weakest['open'])} מיליון ₪ פתוחים).")
    return s


def insight_type_gap(types):
    """Periodic (annual) fees vs one-off service fees: collection gap."""
    per = next((t for t in types if t["raw"] == PERIODIC), None)
    ser = next((t for t in types if t["raw"] == SERVICE), None)
    if not per or not ser or per["billed"] <= 0 or ser["billed"] <= 0:
        return None
    gap = ser["rate"] - per["rate"]
    if abs(gap) < 0.1:
        return None
    lo, hi = (per, ser) if gap > 0 else (ser, per)
    return (f"אגרות {lo['name']} נגבות פחות: {_pct(lo['rate'])} מהן שולמו, לעומת "
            f"{_pct(hi['rate'])} באגרות {hi['name']}. אגרות {per['name']} הן "
            f"{_pct(per['billed_share'])} מהחיובים התקפים, ובהן {_pct(per['open_share'])} מהיתרה הפתוחה.")


def insight_exempt(total, reasons):
    """Exemptions and cancellations: their size and the leading reason."""
    waived = total["nonactive"]
    all_amt = total["billed"] + waived
    if all_amt <= 0 or waived <= 0:
        return None
    share = waived / all_amt
    if share < 0.02:
        return None
    s = (f"{_m(waived)} מיליון ₪ בחיובים ({_pct(share)} מסך החיובים) לא נגבו מלכתחילה: "
         f"{_m(total['exempt'])} מיליון ₪ בפטור, {_m(total['cancelled'])} מיליון ₪ בביטול"
         + (f" ו-{_m(total['frozen'])} מיליון ₪ בהקפאה." if total["frozen"] >= 50_000 else "."))
    named = [r for r in reasons if r["named"]]
    if named:
        r = sorted(named, key=lambda r: (-r["amount"], r["name"]))[0]
        s += f" הסיבה שמאחורי הסכום הגדול ביותר: \"{r['name']}\" ({_m(r['amount'])} מיליון ₪)."
    return s


def insight_rate_trend(yrs):
    """Collection rate of the first charge year vs the latest one."""
    if len(yrs) < 3:
        return None
    first, last = yrs[0], yrs[-1]
    if first["billed"] <= 0 or last["billed"] <= 0:
        return None
    diff = last["rate"] - first["rate"]
    if abs(diff) < 0.05:
        return None
    if diff > 0:
        return (f"חיובי {first['year']} נגבו רק ב-{_pct(first['rate'])}, ו-{_m(first['open'])} מיליון ₪ מהם "
                f"עדיין רשומים כיתרה פתוחה, לעומת שיעור גבייה של {_pct(last['rate'])} בחיובי {last['year']}: "
                f"החובות הישנים לא נסגרו עם השנים.")
    return (f"שיעור הגבייה של חיובי {last['year']} עומד על {_pct(last['rate'])}, לעומת "
            f"{_pct(first['rate'])} בחיובי {first['year']}. היתרות נכונות למועד עדכון הקבצים, "
            f"כך שחלק מהחובות הפתוחים בשנים האחרונות עשוי עוד להיגבות.")


def insight_waived_units(units, a_i):
    """Units where most of the charged amount was never collectable."""
    rows = []
    for u in units[:TOP_UNITS]:
        tot = sum(u["status_amt"])
        if tot > 0:
            sh = 1 - u["status_amt"][a_i] / tot
            if sh >= 0.5:
                rows.append((sh, u["name"]))
    if not rows:
        return None
    rows.sort(key=lambda r: (-r[0], r[1]))
    rows = rows[:2]
    if len(rows) == 1:
        return (f"{_b(rows[0][1])} רוב סכום החיובים לא נגבה כלל: {_pct(rows[0][0])} ממנו "
                f"בוטל, נפטר או הוקפא.")
    return (f"{_b(rows[0][1])} ו{_b(rows[1][1])} רוב סכום החיובים לא נגבה כלל: {_pct(rows[0][0])} "
            f"ו-{_pct(rows[1][0])} ממנו (בהתאמה) בוטל, נפטר או הוקפא.")


# ── compute ─────────────────────────────────────────────────────────────


def compute(frames):
    d = _prepare(frames["main"])
    frames.clear()
    years, units, statuses, types = d["years"], d["units"], d["statuses"], d["types"]
    cnt, amt, opn = d["cnt"], d["amt"], d["opn"]
    si = {s: i for i, s in enumerate(statuses)}
    a_i = si.get(ACTIVE)
    if a_i is None or not years:
        raise ValueError("no active charges or no year in the file names")

    def st(arr, name):
        i = si.get(name)
        return arr[..., i, :] if i is not None else np.zeros_like(arr[..., 0, :])

    # Per year.
    yrs = []
    for y_i, y in enumerate(years):
        billed = float(amt[y_i, :, a_i, :].sum())
        open_ = float(opn[y_i, :, a_i, :].sum())
        yrs.append({
            "year": y, "count": int(cnt[y_i].sum()), "active": int(cnt[y_i, :, a_i, :].sum()),
            "billed": billed, "open": open_, "collected": billed - open_,
            "rate": (billed - open_) / billed if billed > 0 else 0.0,
            "exempt": float(st(amt, EXEMPT)[y_i].sum()),
            "cancelled": float(st(amt, CANCELLED)[y_i].sum()),
        })

    tot_billed = float(amt[:, :, a_i, :].sum())
    tot_open = float(opn[:, :, a_i, :].sum())
    total = {
        "count": int(cnt.sum()), "active": int(cnt[:, :, a_i, :].sum()),
        "billed": tot_billed, "open": tot_open, "collected": tot_billed - tot_open,
        "rate": (tot_billed - tot_open) / tot_billed if tot_billed > 0 else 0.0,
        "exempt": float(st(amt, EXEMPT).sum()), "cancelled": float(st(amt, CANCELLED).sum()),
        "frozen": float(st(amt, FROZEN).sum()),
        "nonactive": float(amt.sum()) - tot_billed,
        "exempt_n": int(st(cnt, EXEMPT).sum()), "cancelled_n": int(st(cnt, CANCELLED).sum()),
    }

    # Per unit (all years).
    ulist = []
    for u_i, name in enumerate(units):
        billed = float(amt[:, u_i, a_i, :].sum())
        open_ = float(opn[:, u_i, a_i, :].sum())
        n_all = int(cnt[:, u_i].sum())
        if n_all == 0:
            continue
        ulist.append({
            "i": u_i, "name": name, "count": int(cnt[:, u_i, a_i, :].sum()), "all": n_all,
            "billed": billed, "open": open_, "collected": billed - open_,
            "rate": (billed - open_) / billed if billed > 0 else 0.0,
            "status_amt": [float(amt[:, u_i, s_i, :].sum()) for s_i in range(len(statuses))],
            "status_cnt": [int(cnt[:, u_i, s_i, :].sum()) for s_i in range(len(statuses))],
            "first": next((years[y] for y in range(len(years)) if cnt[y, u_i].sum() > 0), None),
        })
    ulist.sort(key=lambda u: (-u["billed"], -u["all"], u["name"]))

    # Status order: known first, then any new status alphabetically.
    s_order = [s for s in STATUS_ORDER if s in si] + sorted(s for s in statuses if s not in STATUS_ORDER)
    s_name = [STATUS_LABEL.get(s, s) for s in s_order]

    # ── charts ──
    charts, tables, labels, flags = {}, {}, {}, {}

    charts["years"] = {
        "x": [str(y["year"]) for y in yrs],
        "collected": [round(y["collected"] / 1e6, 2) for y in yrs],
        "open": [round(y["open"] / 1e6, 2) for y in yrs],
        "count": [round(y["count"] / 1000, 1) for y in yrs],
        "rate": [round(y["rate"] * 100, 1) for y in yrs],
    }
    tables["years"] = [{
        "year": y["year"], "count": _int(y["count"]), "billed": _m(y["billed"]),
        "collected": _m(y["collected"]), "open": _m(y["open"]), "rate": _pct(y["rate"]),
    } for y in yrs]
    peak = sorted(yrs, key=lambda y: (-y["billed"], y["year"]))[0]
    labels["years_aria"] = (
        f"גרף עמודות מוערמות: חיובים תקפים לפי שנה, {years[0]} עד {years[-1]}, בחלוקה לנגבה ולפתוח. "
        f"השנה עם הסכום הגבוה ביותר: {peak['year']} ({_m(peak['billed'])} מיליון ₪).")
    labels["years_note"] = (
        f"סכום החיובים התקפים בכל שנה (מיליוני ₪), מפוצל לחלק שנגבה ולחלק שעדיין פתוח, "
        f"והקו מציג את מספר החיובים בכל הסטטוסים (באלפים). השנה היא שנת הקובץ.")

    # Units ranking (top N + other), stacked collected / open.
    top = ulist[:TOP_UNITS]
    rest = ulist[TOP_UNITS:]
    rank_rows = [{"name": u["name"], "collected": u["collected"], "open": u["open"],
                  "billed": u["billed"], "count": u["count"], "rate": u["rate"]} for u in top]
    if rest:
        rb = sum(u["billed"] for u in rest)
        ro = sum(u["open"] for u in rest)
        rank_rows.append({"name": f"אחר ({len(rest)} יחידות)", "collected": rb - ro, "open": ro,
                          "billed": rb, "count": sum(u["count"] for u in rest),
                          "rate": (rb - ro) / rb if rb > 0 else 0.0})
    charts["units"] = {
        "x": [r["name"] for r in rank_rows],
        "collected": [round(r["collected"] / 1e6, 2) for r in rank_rows],
        "open": [round(r["open"] / 1e6, 2) for r in rank_rows],
    }
    tables["units"] = [{"name": r["name"], "billed": _m(r["billed"]), "share": _pct(r["billed"] / tot_billed) if tot_billed else "0%",
                        "count": _int(r["count"]), "rate": _pct(r["rate"])} for r in rank_rows]
    labels["units_aria"] = (
        f"גרף עמודות אופקי: חיובים תקפים לפי יחידה, {years[0]} עד {years[-1]}. "
        f"בראש: {ulist[0]['name']} עם {_m(ulist[0]['billed'])} מיליון ₪.")
    labels["units_note"] = (
        f"סך החיובים התקפים של כל יחידה בכל השנים (מיליוני ₪), {len(top)} היחידות הגדולות"
        + (f" ושאר {len(rest)} היחידות מקובצות יחד תחת אחר." if rest else "."))

    # Unit x year table/heatmap (billed, ₪M).
    heat_units = ulist[:HEAT_UNITS]
    cells, hmax = [], 0.0
    for r, u in enumerate(heat_units):
        for c_, y in enumerate(years):
            v = round(float(amt[c_, u["i"], a_i, :].sum()) / 1e6, 2)
            cells.append([c_, r, v])
            hmax = max(hmax, v)
    charts["heat"] = {"x": [str(y) for y in years], "y": [u["name"] for u in heat_units],
                      "cells": cells, "max": hmax}
    tables["heat"] = [{"name": u["name"], "vals": [_m(float(amt[c_, u["i"], a_i, :].sum()), 2) for c_ in range(len(years))]}
                      for u in heat_units]
    # Fastest growing unit, latest year vs first year it appears with real money.
    growth = []
    for u in heat_units:
        series = [float(amt[c_, u["i"], a_i, :].sum()) for c_ in range(len(years))]
        if series[0] >= 1e6 and series[-1] > 0:
            growth.append((series[-1] / series[0], u["name"], series[0], series[-1]))
    growth.sort(key=lambda g: (-g[0], g[1]))
    labels["heat_aria"] = (
        f"מפת חום: חיובים תקפים במיליוני ₪ לפי יחידה ושנה, {len(heat_units)} היחידות הגדולות, "
        f"{years[0]} עד {years[-1]}.")
    if growth and growth[0][0] >= 1.5:
        g = growth[0]
        labels["heat_note"] = (
            f"כל משבצת היא סכום החיובים התקפים של יחידה בשנה (מיליוני ₪). הצמיחה המהירה ביותר: "
            f"{g[1]}, מ-{_m(g[2])} מיליון ₪ ב-{years[0]} ל-{_m(g[3])} מיליון ₪ ב-{years[-1]}.")
    else:
        labels["heat_note"] = "כל משבצת היא סכום החיובים התקפים של יחידה בשנה (מיליוני ₪)."

    # Collection rate by unit.
    rated = [u for u in ulist if u["billed"] >= MIN_RATE_BILLED and u["count"] >= MIN_RATE_CHARGES]
    rated.sort(key=lambda u: (u["rate"], u["name"]))
    charts["rate"] = {
        "x": [u["name"] for u in rated],
        "y": [round(u["rate"] * 100, 1) for u in rated],
        "tone": ["ok" if u["rate"] >= RATE_OK else "warn" if u["rate"] >= RATE_WARN else "danger" for u in rated],
        "ok": round(RATE_OK * 100), "warn": round(RATE_WARN * 100),
    }
    tables["rate"] = [{"name": u["name"], "rate": _pct(u["rate"]), "billed": _m(u["billed"]),
                       "open": _m(u["open"])} for u in rated]
    weakest = rated[0] if rated else None
    labels["rate_aria"] = (
        f"גרף עמודות: שיעור הגבייה של חיובים תקפים לפי יחידה. הנמוך ביותר: "
        f"{weakest['name']} ({_pct(weakest['rate'])})." if weakest else "גרף עמודות: שיעור הגבייה לפי יחידה.")
    labels["rate_note"] = (
        f"החלק מסכום החיובים התקפים שכבר הותאם לתשלום, בכל השנים יחד. מוצגות {len(rated)} יחידות "
        f"עם חיובים של {_m(MIN_RATE_BILLED, 0)} מיליון ₪ לפחות ו-{_int(MIN_RATE_CHARGES)} חיובים תקפים לפחות. "
        f"ירוק: {_pct(RATE_OK, 0)} ומעלה, צהוב: {_pct(RATE_WARN, 0)} עד {_pct(RATE_OK, 0)}, אדום: מתחת ל-{_pct(RATE_WARN, 0)}.")
    flags["rate"] = len(rated) >= 2

    # Status mix per year (share of charges by count).
    st_series = []
    for s in s_order:
        s_i = si[s]
        st_series.append({"name": STATUS_LABEL.get(s, s), "data": [
            round(100 * int(cnt[y_i, :, s_i, :].sum()) / yrs[y_i]["count"], 2) if yrs[y_i]["count"] else 0
            for y_i in range(len(years))]})
    charts["status"] = {"x": [str(y) for y in years], "series": st_series}
    tables["status"] = [{"year": y, "count": _int(yrs[y_i]["count"]),
                         "shares": [_pct(int(cnt[y_i, :, si[s], :].sum()) / yrs[y_i]["count"]) if yrs[y_i]["count"] else "0%"
                                    for s in s_order]} for y_i, y in enumerate(years)]
    tables["status_names"] = s_name
    ex_i = si.get(EXEMPT)
    ex_share = [int(cnt[y_i, :, ex_i, :].sum()) / yrs[y_i]["count"] if ex_i is not None and yrs[y_i]["count"] else 0.0
                for y_i in range(len(years))]
    labels["status_aria"] = (
        f"גרף עמודות מוערמות: התפלגות החיובים לפי סטטוס בכל שנה. שיעור הפטורים בשנת {years[-1]}: "
        f"{_pct(ex_share[-1])}.")
    labels["status_note"] = (
        "שיעור החיובים בכל שנה לפי הסטטוס שלהם: חיוב תקף, פטור, בוטל או הוקפא (לפי מספר החיובים).")

    # Status by unit (share of amount), top units.
    su_units = ulist[:TOP_UNITS]
    charts["status_units"] = {
        "x": [u["name"] for u in su_units],
        "series": [{"name": STATUS_LABEL.get(s, s), "data": [
            round(100 * u["status_amt"][si[s]] / sum(u["status_amt"]), 2) if sum(u["status_amt"]) > 0 else 0
            for u in su_units]} for s in s_order],
    }
    tables["status_units"] = [{"name": u["name"], "shares": [
        _pct(u["status_amt"][si[s]] / sum(u["status_amt"])) if sum(u["status_amt"]) > 0 else "0%" for s in s_order]}
        for u in su_units]
    waived_units = sorted(
        [u for u in su_units if sum(u["status_amt"]) > 0],
        key=lambda u: (-(1 - u["status_amt"][a_i] / sum(u["status_amt"])), u["name"]))
    wu = waived_units[0] if waived_units else None
    labels["status_units_aria"] = (
        f"גרף עמודות מוערמות אופקי: חלוקת סכום החיובים של כל יחידה לפי סטטוס. השיעור הגבוה ביותר של "
        f"פטור וביטול: {wu['name']} ({_pct(1 - wu['status_amt'][a_i] / sum(wu['status_amt']))})."
        if wu else "גרף עמודות מוערמות: סטטוס החיובים לפי יחידה.")
    labels["status_units_note"] = (
        f"איזה חלק מסכום החיובים של כל יחידה תקף, ואיזה חלק נפטר, בוטל או הוקפא ({len(su_units)} היחידות "
        f"עם החיובים התקפים הגבוהים ביותר, כל השנים).")

    # Fee type: billed per year by type + collection rate by type.
    t_tot = {}
    for t_i, t in enumerate(types):
        b = float(amt[:, :, a_i, t_i].sum())
        o = float(opn[:, :, a_i, t_i].sum())
        t_tot[t] = (b, o)
    t_order = sorted(types, key=lambda t: (-t_tot[t][0], t))
    t_name = {t: ("תקופתיות" if t == PERIODIC else "שירות" if t == SERVICE else t) for t in types}
    tlist = [{"raw": t, "name": t_name[t], "billed": t_tot[t][0], "open": t_tot[t][1],
              "rate": (t_tot[t][0] - t_tot[t][1]) / t_tot[t][0] if t_tot[t][0] > 0 else 0.0,
              "billed_share": t_tot[t][0] / tot_billed if tot_billed else 0.0,
              "open_share": t_tot[t][1] / tot_open if tot_open else 0.0} for t in t_order]
    charts["types"] = {
        "x": [str(y) for y in years],
        "series": [{"name": t_name[t], "data": [round(float(amt[y_i, :, a_i, types.index(t)].sum()) / 1e6, 2)
                                                for y_i in range(len(years))]} for t in t_order],
        "rate": [{"name": t_name[t], "data": [
            round(100 * (1 - float(opn[y_i, :, a_i, types.index(t)].sum()) / b), 1) if (b := float(amt[y_i, :, a_i, types.index(t)].sum())) > 0 else None
            for y_i in range(len(years))]} for t in t_order],
    }
    tables["types"] = [{"name": t["name"], "billed": _m(t["billed"]), "share": _pct(t["billed_share"]),
                        "rate": _pct(t["rate"]), "open": _m(t["open"])} for t in tlist]
    labels["types_aria"] = (
        f"גרף עמודות מוערמות: חיובים תקפים לפי סוג אגרה ושנה. הסוג הגדול ביותר: "
        f"{tlist[0]['name']} ({_pct(tlist[0]['billed_share'])} מהסכום).")
    labels["types_note"] = (
        "אגרות תקופתיות (כמו האגרה השנתית של חברות ועמותות) לעומת אגרות שירות חד-פעמיות, "
        "במיליוני ₪. הטבלה מציגה גם את שיעור הגבייה של כל סוג.")

    # Reasons for exemption / cancellation.
    r_rows = []
    for i, name in enumerate(d["r_labels"]):
        if d["r_cnt"][i] <= 0:
            continue
        r_rows.append({"name": name if name else "ללא סיבה מצוינת", "count": int(d["r_cnt"][i]),
                       "amount": float(d["r_amt"][i]), "named": bool(name) and name != "אחר"})
    named = [r for r in r_rows if r["named"] and r["count"] >= MIN_REASON_COUNT]
    named.sort(key=lambda r: (-r["count"], r["name"]))
    shown = named[:TOP_REASONS]
    shown_names = {r["name"] for r in shown}
    other = [r for r in r_rows if r["name"] not in shown_names]
    reason_rows = list(shown)
    if other:
        reason_rows.append({"name": "סיבות אחרות או ללא סיבה", "count": sum(r["count"] for r in other),
                            "amount": sum(r["amount"] for r in other), "named": False})
    n_nonact = sum(r["count"] for r in r_rows)
    charts["reasons"] = {"x": [r["name"] for r in reason_rows], "y": [r["count"] for r in reason_rows],
                         "amount": [round(r["amount"] / 1e6, 2) for r in reason_rows]}
    tables["reasons"] = [{"name": r["name"], "count": _int(r["count"]),
                          "share": _pct(r["count"] / n_nonact) if n_nonact else "0%",
                          "amount": _m(r["amount"], 2)} for r in reason_rows]
    flags["reasons"] = bool(shown)
    labels["reasons_aria"] = (
        f"גרף עמודות אופקי: סיבות לפטור או לביטול חיובים. הסיבה השכיחה ביותר: "
        f"{shown[0]['name']} ({_int(shown[0]['count'])} חיובים)." if shown else "גרף עמודות: סיבות לפטור ולביטול.")
    labels["reasons_note"] = (
        f"{_int(n_nonact)} חיובים שלא נגבו מלכתחילה (פטור, ביטול או הקפאה), לפי הסיבה הרשומה. "
        f"מספרי פניות הוסרו מהטקסט כדי לקבץ סיבות זהות; סיבה מוצגת בשמה כשהיא מופיעה ב-{_int(MIN_REASON_COUNT)} "
        f"חיובים לפחות.")

    # Amount distribution of active charges.
    bk = d["buckets"]
    n_act = int(bk.sum())
    charts["amounts"] = {"x": [l for _, l in AMOUNT_BUCKETS], "y": [int(v) for v in bk],
                         "amount": [round(float(v) / 1e6, 2) for v in d["bucket_amt"]]}
    tables["amounts"] = [{"name": l, "count": _int(bk[i]), "share": _pct(bk[i] / n_act) if n_act else "0%",
                          "amount": _m(d["bucket_amt"][i], 2),
                          "amount_share": _pct(d["bucket_amt"][i] / tot_billed) if tot_billed else "0%"}
                         for i, (_, l) in enumerate(AMOUNT_BUCKETS)]
    low = sum(int(bk[i]) for i, (b, _) in enumerate(AMOUNT_BUCKETS) if b is not None and b <= LOW_MAX)
    hi_i = [i for i, (b, _) in enumerate(AMOUNT_BUCKETS) if b is None or b > HIGH_MIN]
    hi_amt = sum(float(d["bucket_amt"][i]) for i in hi_i)
    hi_cnt = sum(int(bk[i]) for i in hi_i)
    labels["amounts_aria"] = (
        f"גרף עמודות: התפלגות סכומי החיובים התקפים. {_pct(low / n_act if n_act else 0)} מהחיובים הם עד {_int(LOW_MAX)} ₪.")
    labels["amounts_note"] = (
        f"מספר החיובים התקפים בכל טווח סכום (₪). {_pct(low / n_act if n_act else 0)} מהחיובים הם של {_int(LOW_MAX)} ₪ ומטה, "
        f"ואילו {_int(hi_cnt)} חיובים של יותר מ-{_int(HIGH_MIN)} ₪ מרכזים {_pct(hi_amt / tot_billed if tot_billed else 0)} מהכסף.")

    # Volume vs value scatter (all units).
    charts["scatter"] = {"points": [[u["count"], round(u["billed"] / u["count"], 1) if u["count"] else 0, u["name"]]
                                    for u in ulist if u["count"] > 0 and u["billed"] > 0]}
    tables["scatter"] = [{"name": u["name"], "count": _int(u["count"]),
                          "avg": _int(u["billed"] / u["count"]) if u["count"] else "0"}
                         for u in sorted([u for u in ulist if u["count"] > 0],
                                         key=lambda u: (-u["count"], u["name"]))]
    big = sorted([u for u in ulist if u["count"] > 0], key=lambda u: (-u["billed"] / u["count"], u["name"]))
    labels["scatter_aria"] = (
        f"תרשים פיזור: לכל יחידה, מספר החיובים התקפים מול החיוב הממוצע. החיוב הממוצע הגבוה ביותר: "
        f"{big[0]['name']} ({_int(big[0]['billed'] / big[0]['count'])} ₪)." if big else "תרשים פיזור.")
    labels["scatter_note"] = (
        "כל נקודה היא יחידה: הציר האופקי הוא מספר החיובים התקפים בכל השנים, והאנכי הוא החיוב הממוצע ב-₪ "
        "(שני הצירים לוגריתמיים).")

    # ── KPIs ──
    last, prev = yrs[-1], (yrs[-2] if len(yrs) > 1 else None)
    rate_tone = "ok" if total["rate"] >= RATE_OK else "warn" if total["rate"] >= RATE_WARN else "danger"
    open_share = tot_open / tot_billed if tot_billed else 0.0
    kpis = {
        "count": {"value": total["count"], "display": _int(total["count"]), "tone": "brand"},
        "billed": {"value": round(tot_billed / 1e6, 1), "display": _m(tot_billed), "tone": "brand"},
        "rate": {"value": round(total["rate"] * 100, 1), "display": _pct(total["rate"]), "tone": rate_tone},
        "open": {"value": round(tot_open / 1e6, 1), "display": _m(tot_open),
                 "tone": "danger" if open_share >= 0.25 else "warn" if open_share >= 0.1 else "brand"},
        "last": {"value": round(last["billed"] / 1e6, 1), "display": _m(last["billed"]), "tone": "brand"},
        "waived": {"value": round(total["nonactive"] / 1e6, 1),
                   "display": _m(total["nonactive"]), "tone": "info"},
        "units": {"value": len(ulist), "display": _int(len(ulist)), "tone": "brand"},
        "span": {"value": len(years), "display": f"{years[0]}–{years[-1]}", "tone": "brand"},
    }
    if prev and prev["billed"] > 0:
        ch = (last["billed"] - prev["billed"]) / prev["billed"]
        kpis["change"] = {"value": round(ch * 100, 1), "display": _signed_pct(ch),
                          "tone": "ok" if ch >= TREND_FLAT else "danger" if ch <= -TREND_FLAT else "brand"}
        labels["change_kpi"] = f"שינוי בחיובים התקפים, {last['year']} לעומת {prev['year']}"
    labels["count_kpi"] = "חיובים במאגר (כל הסטטוסים)"
    labels["billed_kpi"] = "חיובים תקפים, מיליוני ₪"
    labels["rate_kpi"] = "שיעור גבייה של חיובים תקפים"
    labels["open_kpi"] = "יתרה פתוחה, מיליוני ₪"
    labels["last_kpi"] = f"חיובים תקפים ב-{last['year']}, מיליוני ₪"
    labels["waived_kpi"] = "פטורים, ביטולים והקפאות, מיליוני ₪"
    labels["units_kpi"] = "יחידות גובות"
    labels["span_kpi"] = "שנות חיוב במאגר"
    kpi_order = ["count", "billed", "rate", "open", "last"] + (["change"] if "change" in kpis else []) + ["waived", "span"]
    labels["kpi_order"] = kpi_order

    # ── insights ──
    insights = []
    for iid, text in (
        ("trend", insight_trend(yrs)),
        ("collection", insight_collection(total, weakest)),
        ("leader", insight_leader(ulist, tot_billed)),
        ("type_gap", insight_type_gap(tlist)),
        ("volume", insight_volume_value(ulist, total["active"], tot_billed)),
        ("exempt", insight_exempt(total, reason_rows)),
        ("rate_trend", insight_rate_trend(yrs)),
        ("waived_units", insight_waived_units(ulist, a_i)),
    ):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── lede / summary ──
    labels["lede"] = (
        f"כל החיובים שהנפיקו {len(ulist)} יחידות של משרד המשפטים בשנים {years[0]} עד {years[-1]}, "
        f"ובראשן {', '.join(u['name'] for u in ulist[:4])}. "
        f"בסך הכול {_int(total['count'])} חיובים; מתוכם {_int(total['active'])} תקפים בסך "
        f"{_m(tot_billed)} מיליון ₪, ש-{_pct(total['rate'])} מהם כבר נגבו.")
    excluded = d["n_raw"] - d["n"]
    flags["excluded"] = excluded > 0
    labels["excluded_note"] = (
        f"{_int(excluded)} שורות ללא שנה בשם הקובץ או ללא סכום תקין אינן נכללות בחישובים."
        if excluded > 0 else "")

    summary = (f"הכנסות וגבייה של משרד המשפטים {years[0]}-{years[-1]}: {_m(tot_billed, 0)} מיליון ₪ "
               f"בחיובים תקפים, {_pct(total['rate'])} נגבו. פירוט לפי יחידה, סוג אגרה ופטורים.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["גבייה", "אגרות", "הכנסות המדינה", "משרד המשפטים", "רשם החברות", "תקבולים"],
            "related_ids": [
                "246d949c-a253-4811-8a11-41a137d3d613",
                "3111ae54-790a-4d02-9750-d51e1134b405",
                "656f6e4c-ec04-40a5-b3bc-c556b2b127e0",
                "382c098b-a687-478a-9965-06977d7c9501",
                "669b2652-f75b-4de3-8e6b-0dfa17accef5",
            ],
            "temporal_coverage": f"{years[0]}/{years[-1]}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
