"""דוח ביצוע תוכניות העבודה הממשלתיות: the Prime Minister's Office annual
report on how ministries met the indicators of their yearly work plans.

Two tables:
- `key`  (מדדים מרכזיים): one row per key indicator of a ministry or
  government unit. `rate_scale` is the achievement rate capped to 0..1,
  `achievement_rate` is the uncapped one (can exceed 1 or go negative).
- `plan` (עיקרי תוכנית העבודה): one row per work-plan indicator, nested
  under goal → target → task. `rate_range` is the capped achievement rate
  (0..1), `rate_scale` the uncapped one.

Every indicator is classified by its capped rate:
  full (>= 100%), partial (60%..100%), low (above 0, under 60%), zero, or
  not reported (no rate: no planned value, or no actual value). The 60% line
  is the PMO's own threshold: below it a ministry must explain the shortfall.

The barrier columns are free-ish text mixed with PMO reviewer notes (strings
starting with "*"); they are normalised and the notes dropped.
"""
import re

import pandas as pd

FULL = 0.9999
LOW_LINE = 0.6
STATUS = ["עמידה מלאה", "עמידה חלקית", "עמידה נמוכה", "לא בוצע", "לא דווח"]
STATUS_KEYS = ["full", "partial", "low", "zero", "none"]
MIN_UNIT = 20          # min work-plan indicators for a ministry leader/laggard rule
MIN_KEY_UNIT = 3       # min key indicators for a unit-level key rule
MAX_MINISTRIES = 36    # cap on ministry rows in the stacked chart
KEY_LOW_N = 15         # lowest units shown in the key-indicator chart
TOP_BARRIERS = 10
GAP_PP = 5.0           # percentage-point gap that counts as a real difference
OVER = 1.5             # uncapped rate that counts as clear overachievement
TYPE_ORDER = ["הצלחה", "תוצאה", "תפוקה"]
DIR_NAMES = {"+": "כיוון רצוי: עלייה", "-": "כיוון רצוי: ירידה", "=": "כיוון רצוי: שמירה"}
BARRIER_MAP = {"Force Major": "כוח עליון", "Force_Major": "כוח עליון"}
JUNK_BARRIER = {"", "---", "-", "אחר"}
HIST = [  # uncapped achievement buckets for key indicators: (label, lower, upper)
    ("שלילי", None, 0.0),
    ("אפס", 0.0, 0.0),
    ("מתחת ל-60%", 0.0, 0.6),
    ("60% עד 99%", 0.6, FULL),
    ("100% בדיוק", FULL, 1.0001),
    ("100% עד 150%", 1.0001, 1.5),
    ("150% עד 200%", 1.5, 2.0),
    ("מעל 200%", 2.0, None),
]


def _bucket(raw, lo, hi):
    """lo == hi is an exact value; a 0 lower bound is exclusive (0 has its own
    bucket); every other lower bound is inclusive, upper bounds exclusive."""
    if lo is not None and lo == hi:
        return raw == lo
    m = pd.Series(True, index=raw.index)
    if lo is not None:
        m &= (raw > lo) if lo == 0.0 else (raw >= lo)
    if hi is not None:
        m &= raw < hi
    return m


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def _clean(s):
    return s.astype(str).str.replace(r"\s+", " ", regex=True).str.strip()


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def _status(r):
    if pd.isna(r):
        return "none"
    if r >= FULL:
        return "full"
    if r >= LOW_LINE:
        return "partial"
    if r > 0:
        return "low"
    return "zero"


def _deadline(v):
    v = str(v).strip()
    if not v:
        return pd.NaT
    if re.fullmatch(r"\d{5}(\.0+)?", v):
        return pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(float(v)))
    d = pd.to_datetime(v[:10], errors="coerce", format="%d/%m/%Y")
    if pd.isna(d):
        d = pd.to_datetime(v[:10], errors="coerce", format="%Y-%m-%d")
    return d


def _barrier(v):
    v = re.sub(r"\s+", " ", str(v)).strip()
    if v.startswith("*") or v in JUNK_BARRIER:
        return ""
    v = BARRIER_MAP.get(v, v).replace("_", " ").strip()
    return v


def _year(series):
    y = _num(series).dropna()
    if y.empty:
        return ""
    vc = y.astype(int).value_counts().sort_index()
    return str(int(vc.sort_values(ascending=False, kind="stable").index[0]))


def _prep_key(df):
    out = pd.DataFrame({
        "unit": _clean(df["unit"]),
        "ind": _clean(df["indicator"]),
        "rate": _num(df["rate_scale"]).clip(lower=0, upper=1),
        "raw": _num(df["achievement_rate"]),
        "dir": df["direction"].str.strip(),
        "stable": df["stable_existing"].str.strip(),
        "binary": df["binary"].str.strip(),
        "rec": df["recurring"].str.strip(),
        "src": df["data_source"].str.strip(),
        "expl": df["public_explanation"].str.strip(),
        "has_actual": _num(df["actual_value_2025"]).notna(),
        "has_target": _num(df["target_value"]).notna(),
        "has_base": _num(df["baseline_value"]).notna(),
    })
    out = out[out["unit"] != ""]
    out = out.sort_values(["unit", "ind", "rate", "raw", "dir", "src", "expl"],
                          kind="stable", na_position="last").reset_index(drop=True)
    out["st"] = out["rate"].map(_status)
    return out


def _prep_plan(df):
    out = pd.DataFrame({
        "unit": _clean(df["unit"]),
        "goal": _clean(df["goal"]),
        "target": _clean(df["target"]),
        "task": _clean(df["task"]),
        "ind": _clean(df["indicator"]),
        "type": _clean(df["indicator_type"]),
        "binary": df["binary"].str.strip(),
        "rec": df["recurring_indicator"].str.strip(),
        "rate": _num(df["rate_range"]).clip(lower=0, upper=1),
        "raw": _num(df["rate_scale"]),
        "due": df["end_date"].map(_deadline),
        "barrier": df["primary_barrier"].map(_barrier),
        "barrier_raw": _clean(df["primary_barrier"]),
        "src": df["data_source"].str.strip(),
        "expl": df["public_explanation"].str.strip(),
        "has_actual": _num(df["actual_value_2025"]).notna(),
        "has_target": _num(df["target_value"]).notna(),
        "has_base": _num(df["baseline_value"]).notna(),
        "has_end": _num(df["value_at_end_date"]).notna(),
    })
    out = out[out["unit"] != ""]
    out = out.sort_values(["unit", "goal", "target", "task", "ind", "rate", "raw", "type", "barrier"],
                          kind="stable", na_position="last").reset_index(drop=True)
    out["st"] = out["rate"].map(_status)
    return out


def _mix(st):
    n = len(st)
    c = st.value_counts()
    counts = [int(c.get(k, 0)) for k in STATUS_KEYS]
    shares = [round(v / n * 100, 1) if n else 0.0 for v in counts]
    rep = n - counts[-1]
    full_rep = counts[0] / rep if rep else None
    return {"n": n, "counts": counts, "shares": shares, "reported": rep, "full_rep": full_rep}


def _mix_rows(groups):
    """groups: list of (label, status series) → chart + table rows."""
    names, rows = [], []
    series = [[] for _ in STATUS_KEYS]
    for label, st in groups:
        m = _mix(st)
        if m["n"] == 0:
            continue
        names.append(label)
        for i in range(len(STATUS_KEYS)):
            series[i].append(m["shares"][i])
        rows.append({"name": label, "n": _int(m["n"]),
                     "cells": [f"{_int(m['counts'][i])} ({m['shares'][i]:.0f}%)" for i in range(len(STATUS_KEYS))],
                     "full": m["full_rep"], "nn": m["n"]})
    return {"names": names, "series": series, "status": STATUS}, rows


def compute(frames):
    key = _prep_key(frames["key"])
    plan = _prep_plan(frames["plan"])
    year = _year(frames["plan"]["year"]) or _year(frames["key"]["year"])

    mk = _mix(key["st"])
    mp = _mix(plan["st"])
    n_units_plan = plan["unit"].nunique()
    n_units_key = key["unit"].nunique()
    goals = plan[plan["goal"] != ""][["unit", "goal"]].drop_duplicates()
    targets = plan[plan["target"] != ""][["unit", "goal", "target"]].drop_duplicates()
    tasks = plan[plan["task"] != ""][["unit", "goal", "target", "task"]].drop_duplicates()

    insights = []
    charts = {}
    tables = {}
    labels = {"year": year, "low_line": _pct(LOW_LINE), "min_unit": _int(MIN_UNIT),
              "min_key_unit": _int(MIN_KEY_UNIT)}

    # ---- 1. overall status mix (both tables) -------------------------------
    charts["status"], tables["status"] = _mix_rows([
        ("מדדים מרכזיים", key["st"]),
        ("מדדי תוכניות העבודה", plan["st"]),
    ])
    full_p = mp["full_rep"]
    below_p = (mp["counts"][2] + mp["counts"][3]) / mp["reported"] if mp["reported"] else None
    if full_p is not None:
        insights.append({"id": "overall", "text_he": (
            f"מתוך {_int(mp['reported'])} מדדי תוכניות העבודה שדווח עליהם ערך ביצוע, "
            f"{_pct(full_p)} עמדו ביעד במלואו ו-{_pct(below_p)} נעצרו מתחת ל-{_pct(LOW_LINE)} "
            f"מהיעד (מהם {_int(mp['counts'][3])} ללא ביצוע כלל). "
            f"עוד {_int(mp['counts'][4])} מדדים לא דווחו או שלא נקבע להם ערך מתוכנן.")})
    if mk["full_rep"] is not None and full_p is not None:
        gap = (mk["full_rep"] - full_p) * 100
        if abs(gap) >= GAP_PP:
            word = "גבוה" if gap > 0 else "נמוך"
            insights.append({"id": "key_vs_plan", "text_he": (
                f"שיעור העמידה המלאה במדדים המרכזיים ({_pct(mk['full_rep'])} מ-{_int(mk['reported'])} שדווחו) "
                f"{word} בכ-{abs(gap):.0f} נקודות האחוז מזה של כלל מדדי תוכניות העבודה ({_pct(full_p)}).")})
        else:
            insights.append({"id": "key_vs_plan", "text_he": (
                f"המדדים המרכזיים עמדו ביעד בשיעור דומה לכלל מדדי תוכניות העבודה: "
                f"{_pct(mk['full_rep'])} לעומת {_pct(full_p)}.")})

    # ---- 2. work-plan status by ministry ----------------------------------
    by_unit = plan.groupby("unit", sort=True)
    sizes = by_unit.size().sort_index().sort_values(ascending=False, kind="stable")
    shown = list(sizes.head(MAX_MINISTRIES).index)
    grp = []
    for u in shown:
        st = plan.loc[plan["unit"] == u, "st"]
        grp.append((u, st))
    _, rows = _mix_rows(grp)
    rows.sort(key=lambda r: (-(r["full"] if r["full"] is not None else -1), -r["nn"], r["name"]))
    order = [r["name"] for r in rows]
    charts["ministry"], tables["ministry"] = _mix_rows([(u, plan.loc[plan["unit"] == u, "st"]) for u in order])
    charts["ministry"]["names"] = list(reversed(charts["ministry"]["names"]))
    charts["ministry"]["series"] = [list(reversed(s)) for s in charts["ministry"]["series"]]
    charts["ministry"]["n"] = [r["nn"] for r in reversed(tables["ministry"])]
    for r in tables["ministry"]:
        r["full_txt"] = _pct(r["full"]) if r["full"] is not None else "אין דיווח"
    labels["ministry_cap"] = (f"מוצגים {_int(MAX_MINISTRIES)} המשרדים עם מספר המדדים הגדול ביותר מתוך {_int(n_units_plan)}."
                              if n_units_plan > MAX_MINISTRIES else "")
    elig = [r for r in tables["ministry"] if r["nn"] >= MIN_UNIT and r["full"] is not None]
    if len(elig) >= 3:
        best = max(elig, key=lambda r: (r["full"], r["nn"], r["name"]))
        worst = min(elig, key=lambda r: (r["full"], -r["nn"], r["name"]))
        if (best["full"] - worst["full"]) * 100 >= GAP_PP * 2:
            insights.append({"id": "ministry_gap", "text_he": (
                f"הפער בין המשרדים גדול. שיעור העמידה המלאה הגבוה ביותר: {best['name']}, {_pct(best['full'])} "
                f"מהמדדים שדווחו; הנמוך ביותר: {worst['name']}, {_pct(worst['full'])} "
                f"(בקרב משרדים עם {_int(MIN_UNIT)} מדדים לפחות).")})
        labels["ministry_aria"] = (
            f"תרשים עמודות מוערמות: התפלגות העמידה ביעדי תוכניות העבודה לפי משרד. "
            f"השיעור הגבוה ביותר של עמידה מלאה: {best['name']}, {_pct(best['full'])}.")
    else:
        labels["ministry_aria"] = "תרשים עמודות מוערמות: התפלגות העמידה ביעדי תוכניות העבודה לפי משרד."
    labels["ministry_lede"] = (
        f"{_int(len(plan))} מדדים של {_int(n_units_plan)} משרדים. המשרדים ממוינים לפי שיעור העמידה המלאה "
        f"מתוך המדדים שדווחו; אורך כל עמודה הוא מאה אחוז ממדדי המשרד.")

    # ---- 3. indicator character (work plan) -------------------------------
    types = [t for t in TYPE_ORDER if (plan["type"] == t).any()] + sorted(
        t for t in plan["type"].unique() if t and t not in TYPE_ORDER)
    grp = [(f"מדד {t}", plan.loc[plan["type"] == t, "st"]) for t in types]
    grp += [("אבן דרך (כן/לא)", plan.loc[plan["binary"] == "1", "st"]),
            ("מדד כמותי", plan.loc[plan["binary"] == "0", "st"]),
            ("מדד חוזר משנה קודמת", plan.loc[plan["rec"] == "1", "st"]),
            ("מדד חדש", plan.loc[plan["rec"] == "0", "st"])]
    charts["character"], tables["character"] = _mix_rows(grp)
    charts["character"]["names"] = list(reversed(charts["character"]["names"]))
    charts["character"]["series"] = [list(reversed(s)) for s in charts["character"]["series"]]
    mb = _mix(plan.loc[plan["binary"] == "1", "st"])
    mq = _mix(plan.loc[plan["binary"] == "0", "st"])
    if mb["full_rep"] is not None and mq["full_rep"] is not None and mb["reported"] >= 30 and mq["reported"] >= 30:
        gap = (mb["full_rep"] - mq["full_rep"]) * 100
        zb = mb["counts"][3] / mb["reported"]
        if abs(gap) >= GAP_PP:
            hi, lo = ("אבני הדרך", "המדדים הכמותיים") if gap > 0 else ("המדדים הכמותיים", "אבני הדרך")
            insights.append({"id": "binary", "text_he": (
                f"{hi} הושלמו במלואם בשיעור גבוה יותר מ{lo}: "
                f"{_pct(max(mb['full_rep'], mq['full_rep']))} לעומת {_pct(min(mb['full_rep'], mq['full_rep']))}. "
                f"אבן דרך היא הכול או כלום, ולכן {_pct(zb)} מאבני הדרך שדווחו לא בוצעו כלל.")})
    labels["character_aria"] = "תרשים עמודות מוערמות: עמידה ביעדים לפי סוג המדד, מדד בינארי או כמותי, ומדד חוזר או חדש."

    # ---- 4. deadlines --------------------------------------------------------
    y0 = int(year) if year.isdigit() else None
    dl_names, dl_n, dl_full = [], [], []
    tables["deadline"] = []
    if y0 is not None:
        d = plan["due"]
        buckets = [
            (f"{y0} מחצית ראשונה", (d.dt.year == y0) & (d.dt.month <= 6)),
            (f"{y0} מחצית שנייה", (d.dt.year == y0) & (d.dt.month > 6)),
            (f"{y0 + 1}", d.dt.year == y0 + 1),
            (f"{y0 + 2}", d.dt.year == y0 + 2),
            (f"{y0 + 3} ואילך", d.dt.year >= y0 + 3),
            (f"לפני {y0}", d.dt.year < y0),
        ]
        for name, mask in buckets:
            sub = plan.loc[mask.fillna(False), "st"]
            if len(sub) == 0:
                continue
            m = _mix(sub)
            dl_names.append(name)
            dl_n.append(m["n"])
            dl_full.append(round(m["full_rep"] * 100, 1) if m["full_rep"] is not None else None)
            tables["deadline"].append({"name": name, "n": _int(m["n"]),
                                       "full": _pct(m["full_rep"]) if m["full_rep"] is not None else "אין דיווח"})
        in_year = plan["due"].dt.year == y0
        later = plan["due"].dt.year > y0
        mi, ml = _mix(plan.loc[in_year.fillna(False), "st"]), _mix(plan.loc[later.fillna(False), "st"])
        if mi["n"] and ml["n"] >= 30 and mi["full_rep"] is not None and ml["full_rep"] is not None:
            share_in = mi["n"] / len(plan)
            gap = (ml["full_rep"] - mi["full_rep"]) * 100
            cmp = ("גבוה יותר" if gap >= GAP_PP else "נמוך יותר" if gap <= -GAP_PP else "דומה")
            insights.append({"id": "deadline", "text_he": (
                f"{_pct(share_in)} מהמדדים נקבעו לסיום במהלך {y0}. ב-{_int(ml['n'])} מדדים שמועד הסיום שלהם "
                f"מאוחר יותר, שיעור העמידה המלאה ביעד השנתי {cmp} ({_pct(ml['full_rep'])} לעומת {_pct(mi['full_rep'])}).")})
    charts["deadline"] = {"names": dl_names, "n": dl_n, "full": dl_full}
    labels["deadline_aria"] = "תרשים עמודות וקו: מספר מדדי תוכניות העבודה לפי מועד הסיום שנקבע להם, ושיעור העמידה המלאה בכל קבוצה."
    labels["deadline_note"] = (f"{_int(int(plan['due'].isna().sum()))} מדדים ללא מועד סיום אינם מוצגים."
                               if plan["due"].isna().any() else "")

    # ---- 5. barriers --------------------------------------------------------
    under = plan[plan["st"].isin(["partial", "low", "zero"])]
    bar = under.loc[under["barrier"] != "", "barrier"]
    vc = bar.value_counts().sort_index().sort_values(ascending=False, kind="stable")
    top = vc.head(TOP_BARRIERS)
    rest = int(vc.iloc[TOP_BARRIERS:].sum()) if len(vc) > TOP_BARRIERS else 0
    b_names = list(top.index) + (["חסמים אחרים"] if rest else [])
    b_vals = [int(v) for v in top.values] + ([rest] if rest else [])
    charts["barriers"] = {"names": list(reversed(b_names)), "values": list(reversed(b_vals))}
    tables["barriers"] = [{"name": n, "v": _int(v)} for n, v in zip(b_names, b_vals)]
    other_stated = int(((under["barrier"] == "") & (under["barrier_raw"] != "")).sum())
    labels["barriers_lede"] = (
        f"{_int(len(under))} מדדים לא עמדו ביעד במלואו, ול-{_int(len(bar))} מהם ציין המשרד חסם מוגדר. "
        f"עוד {_int(other_stated)} סומנו כחסם אחר או בלי פירוט ואינם מוצגים.")
    if len(top) and len(under):
        insights.append({"id": "barrier", "text_he": (
            f"רק ל-{_pct(len(bar) / len(under))} מ-{_int(len(under))} המדדים שלא הושלמו במלואם ציין המשרד חסם מוגדר. "
            f"החסם השכיח ביותר: {top.index[0]} ({_int(top.iloc[0])} מדדים).")})
    labels["barriers_aria"] = (f"תרשים עמודות אופקי: החסמים שציינו המשרדים למדדים שלא הושלמו. "
                               f"השכיח ביותר: {top.index[0]}." if len(top) else "תרשים עמודות אופקי: חסמים לאי ביצוע.")
    charts["has_barriers"] = bool(len(top))

    # ---- 6. key indicators: lowest units -----------------------------------
    ku = key.groupby("unit", sort=True).agg(n=("rate", "size"), rep=("rate", "count"),
                                              avg=("rate", "mean"),
                                              full=("st", lambda s: int((s == "full").sum())))
    ku = ku.reset_index()
    ku_e = ku[ku["rep"] >= MIN_KEY_UNIT].copy()
    ku_e = ku_e.sort_values(["avg", "rep", "unit"], ascending=[True, False, True], kind="stable")
    low = ku_e.head(KEY_LOW_N)
    charts["key_units"] = {"names": list(reversed(low["unit"].tolist())),
                           "values": [round(float(v) * 100, 1) for v in reversed(low["avg"].tolist())]}
    tables["key_units"] = [{"name": r.unit, "avg": _pct(r.avg), "full": f"{_int(r.full)} מתוך {_int(r.rep)}"}
                           for r in low.itertuples()]
    all_full = ku_e[ku_e["full"] == ku_e["rep"]]
    labels["key_units_lede"] = (
        f"ממוצע שיעור הביצוע (עד מאה אחוז למדד) של המדדים המרכזיים, ב-{_int(len(low))} היחידות עם הממוצע הנמוך "
        f"ביותר מתוך {_int(len(ku_e))} יחידות שדיווחו על {_int(MIN_KEY_UNIT)} מדדים מרכזיים לפחות.")
    labels["key_units_aria"] = (
        f"תרשים עמודות אופקי: היחידות עם ממוצע הביצוע הנמוך ביותר במדדים המרכזיים. "
        f"הנמוכה ביותר: {low.iloc[0]['unit']}, {_pct(low.iloc[0]['avg'])}." if len(low) else
        "תרשים עמודות אופקי: ממוצע ביצוע המדדים המרכזיים לפי יחידה.")
    if len(ku_e) >= 5:
        names = all_full.sort_values("unit", kind="stable")["unit"].tolist()
        listed = ", ".join(names[:4]) + (" ועוד" if len(names) > 4 else "")
        if len(names):
            insights.append({"id": "key_units", "text_he": (
                f"{_int(len(names))} מתוך {_int(len(ku_e))} היחידות עמדו במלואם בכל המדדים המרכזיים שדיווחו עליהם"
                f" ({listed}). הממוצע הנמוך ביותר: {low.iloc[0]['unit']}, {_pct(low.iloc[0]['avg'])}.")})

    # ---- 7. key indicators: uncapped distribution ---------------------------
    raw = key["raw"].dropna()
    h_names, h_vals = [], []
    for name, lo, hi in HIST:
        h_names.append(name)
        h_vals.append(int(_bucket(raw, lo, hi).sum()))
    charts["overshoot"] = {"names": h_names, "values": h_vals}
    tables["overshoot"] = [{"name": n, "v": _int(v)} for n, v in zip(h_names, h_vals)]
    over = int((raw >= OVER).sum())
    labels["overshoot_aria"] = (f"תרשים עמודות: התפלגות שיעור הביצוע של המדדים המרכזיים בלי תקרה. "
                                f"{_int(over)} מדדים עברו את היעד ביותר ממחציתו.")
    labels["overshoot_lede"] = (
        f"שיעור הביצוע ביחס ליעד, בלי תקרת מאה האחוז, ל-{_int(len(raw))} מדדים מרכזיים שחושב להם שיעור. "
        f"ערך שלילי פירושו שהמדד זז בכיוון ההפוך מהרצוי.")
    if len(raw) >= 30:
        neg = int((raw < 0).sum())
        insights.append({"id": "overshoot", "text_he": (
            f"{_int(over)} מדדים מרכזיים ({_pct(over / len(raw))}) עברו את היעד ביותר ממחציתו, "
            f"סימן שחלק מהיעדים נקבעו בזהירות; מנגד {_int(neg)} מדדים זזו בכיוון ההפוך מהרצוי.")})

    # ---- 8. key indicators character ---------------------------------------
    grp = [(DIR_NAMES[k], key.loc[key["dir"] == k, "st"]) for k in ["+", "-", "="]]
    grp += [("מדד קיים", key.loc[key["stable"] == "1", "st"]),
            ("מדד חדש", key.loc[key["stable"] == "0", "st"]),
            ("אבן דרך (כן/לא)", key.loc[key["binary"] == "1", "st"]),
            ("מדד כמותי", key.loc[key["binary"] == "0", "st"]),
            ("מדד חוזר", key.loc[key["rec"] == "1", "st"]),
            ("מדד חד-פעמי", key.loc[key["rec"] == "0", "st"])]
    charts["key_character"], tables["key_character"] = _mix_rows(grp)
    charts["key_character"]["names"] = list(reversed(charts["key_character"]["names"]))
    charts["key_character"]["series"] = [list(reversed(s)) for s in charts["key_character"]["series"]]
    labels["key_character_aria"] = "תרשים עמודות מוערמות: עמידה ביעד במדדים המרכזיים לפי הכיוון הרצוי, מדד קיים או חדש, בינארי או כמותי, וחוזר או חד-פעמי."
    me, mn = _mix(key.loc[key["stable"] == "1", "st"]), _mix(key.loc[key["stable"] == "0", "st"])
    if me["full_rep"] is not None and mn["full_rep"] is not None and me["reported"] >= 20 and mn["reported"] >= 20:
        gap = (me["full_rep"] - mn["full_rep"]) * 100
        if abs(gap) >= GAP_PP:
            hi = "הקיימים" if gap > 0 else "החדשים"
            insights.append({"id": "new_key", "text_he": (
                f"במדדים המרכזיים, המדדים {hi} הושגו במלואם לעיתים קרובות יותר: "
                f"{_pct(me['full_rep'])} במדדים קיימים לעומת {_pct(mn['full_rep'])} במדדים חדשים.")})

    # ---- 9. ministry: key vs work plan --------------------------------------
    both = []
    for u in sorted(set(key["unit"]) & set(plan["unit"])):
        a = _mix(key.loc[key["unit"] == u, "st"])
        b = _mix(plan.loc[plan["unit"] == u, "st"])
        if a["full_rep"] is None or b["full_rep"] is None:
            continue
        both.append({"name": u, "plan": round(b["full_rep"] * 100, 1), "key": round(a["full_rep"] * 100, 1),
                     "np": b["reported"], "nk": a["reported"]})
    charts["scatter"] = {"points": [[r["plan"], r["key"], r["name"], r["np"], r["nk"]] for r in both]}
    tables["scatter"] = [{"name": r["name"], "plan": f"{r['plan']:.0f}%", "key": f"{r['key']:.0f}%"} for r in both]
    charts["has_scatter"] = len(both) >= 5
    labels["scatter_aria"] = (f"תרשים פיזור: לכל אחד מ-{_int(len(both))} המשרדים, שיעור העמידה המלאה במדדי תוכנית העבודה "
                              f"(ציר אופקי) לעומת המדדים המרכזיים (ציר אנכי).")
    if len(both) >= 5:
        hi_key = sum(1 for r in both if r["key"] - r["plan"] >= GAP_PP)
        lo_key = sum(1 for r in both if r["plan"] - r["key"] >= GAP_PP)
        insights.append({"id": "scatter", "text_he": (
            f"מבין {_int(len(both))} משרדים שמופיעים בשני הקבצים, ב-{_int(hi_key)} שיעור העמידה המלאה במדדים המרכזיים "
            f"גבוה ביותר מ-{GAP_PP:.0f} נקודות האחוז מזה של תוכנית העבודה, וב-{_int(lo_key)} הוא נמוך ממנו ביותר מ-{GAP_PP:.0f} נקודות.")})

    # ---- 10. transparency ----------------------------------------------------
    no_src = int((key["src"] == "").sum())
    no_expl = int((key["expl"] == "").sum())
    if len(key):
        insights.append({"id": "transparency", "text_he": (
            f"ל-{_int(no_src)} מתוך {_int(len(key))} המדדים המרכזיים ({_pct(no_src / len(key))}) לא צוין מקור נתונים, "
            f"ול-{_int(no_expl)} לא צורף ביאור ציבורי לשיעור הביצוע.")})

    # ---- KPIs ----------------------------------------------------------------
    def tone_full(x):
        if x is None:
            return "brand"
        return "ok" if x >= 0.75 else ("warn" if x >= LOW_LINE else "danger")

    kpis = {
        "plan_n": {"value": len(plan), "display": _int(len(plan)), "tone": "brand",
                   "label": "מדדים בתוכניות העבודה"},
        "key_n": {"value": len(key), "display": _int(len(key)), "tone": "brand",
                  "label": "מדדים מרכזיים"},
        "units": {"value": n_units_plan, "display": _int(n_units_plan), "tone": "brand",
                  "label": "משרדים בתוכניות העבודה"},
        "goals": {"value": len(goals), "display": _int(len(goals)), "tone": "info",
                  "label": f"מטרות, {_int(len(targets))} יעדים ו-{_int(len(tasks))} משימות"},
        "plan_full": {"value": round(full_p, 4) if full_p is not None else None,
                      "display": _pct(full_p) if full_p is not None else "אין",
                      "tone": tone_full(full_p),
                      "label": "עמידה מלאה במדדי תוכניות העבודה (מתוך המדדים שדווחו)"},
        "key_full": {"value": round(mk["full_rep"], 4) if mk["full_rep"] is not None else None,
                     "display": _pct(mk["full_rep"]) if mk["full_rep"] is not None else "אין",
                     "tone": tone_full(mk["full_rep"]),
                     "label": "עמידה מלאה במדדים המרכזיים (מתוך המדדים שדווחו)"},
        "zero": {"value": mp["counts"][3], "display": _int(mp["counts"][3]),
                 "tone": "danger" if mp["reported"] and mp["counts"][3] / mp["reported"] >= 0.1 else "warn",
                 "label": "מדדי תוכניות עבודה שלא בוצעו כלל"},
        "none": {"value": mp["counts"][4] + mk["counts"][4], "display": _int(mp["counts"][4] + mk["counts"][4]),
                 "tone": "warn", "label": "מדדים ללא ערך ביצוע מדווח (בשני הקבצים)"},
    }

    labels["status_aria"] = (
        f"תרשים עמודות מוערמות: התפלגות העמידה ביעדים. עמידה מלאה: {mk['shares'][0]:.0f}% מהמדדים המרכזיים "
        f"ו-{mp['shares'][0]:.0f}% ממדדי תוכניות העבודה.")
    labels["status_lede"] = (
        f"עמידה מלאה היא ביצוע של מאה אחוז מהיעד ומעלה; חלקית היא {_pct(LOW_LINE)} עד מאה אחוז; נמוכה היא מתחת "
        f"ל-{_pct(LOW_LINE)}, הסף שמתחתיו המשרד נדרש להסביר את הפער. "
        f"לא דווח: לא נקבע ערך מתוכנן לשנה או שלא הוזן ערך בפועל.")
    labels["lede"] = (
        f"דוח משרד ראש הממשלה על ביצוע תוכניות העבודה של משרדי הממשלה לשנת {year}: "
        f"{_int(len(plan))} מדדים של {_int(n_units_plan)} משרדים, ועוד {_int(len(key))} מדדים מרכזיים של "
        f"{_int(n_units_key)} משרדים ויחידות סמך. לכל מדד נקבע יעד שנתי, ודווח הערך שהושג בפועל.")

    summary = (f"ביצוע תוכניות העבודה הממשלתיות {year} לפי משרד: {_int(len(plan))} מדדים של "
               f"{_int(n_units_plan)} משרדים"
               + (f", {_pct(full_p)} מהמדדים שדווחו הושגו במלואם" if full_p is not None else "")
               + ". עמידה ביעדים, מדדים מרכזיים וחסמים.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "rankings",
        "suggested_tags": ["תוכניות עבודה", "ביצוע ממשלתי", "מדדי ביצוע", "חשיבה תוצאתית", "בקרה"],
        "related_ids": ["43530ae8-95e5-48d3-8cc9-291055287151", "be345cc9-60a8-4bbc-a8f7-3cc5d16f5e69",
                        "6135c7a7-d4f2-4588-9ace-d4409a9d60fe", "6e25cd24-1b68-4298-90ae-8ae447d9016b"],
    }
    if year:
        agent_data["temporal_coverage"] = year

    return {"agent_data": agent_data, "kpis": kpis, "charts": charts, "insights": insights,
            "labels": labels, "tables": tables}
