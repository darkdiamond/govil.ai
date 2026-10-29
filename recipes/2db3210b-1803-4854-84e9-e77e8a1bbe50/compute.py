"""ריביות החשב הכללי — a small snapshot table of the Accountant General's
current published rates (one row per rate: name, effective-from date, annual %).

Searchers want the CURRENT base rate ("ריבית חשכ"ל היום"), so the page leads
with it. Every number and sentence is computed from the rows; rules whose
premise doesn't hold (a named rate missing, no clear match) return None.

Growth: the publisher overwrites rows in place today. If history is ever
appended (same name, several effective dates), the latest date per name is
the current rate and the base rate's previous value feeds a change insight.
"""
import re

import pandas as pd

LATE_WORDS = ("פיגורים", "איחורים", "איחור")
INACTIVE_MARK = "לא בתוקף"
# Weights tested by the shekel-rate composition rule; the sentence is emitted
# only when the data matches them.
W_A, W_B = 0.25, 0.75
MATCH_TOL = 0.005
INFL_TOL = 0.05


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _rate(v):
    """4.75 -> '4.75', 5.3574 -> '5.3574', 4.0 -> '4.00'."""
    s = f"{v:.4f}".rstrip("0")
    whole, _, frac = s.partition(".")
    frac = frac.ljust(2, "0")
    out = f"{whole}.{frac}"
    return out.replace("-", "−")


def _pp(v):
    """Signed percentage-point gap with U+2212 minus."""
    if abs(v) < 0.00005:
        return "0.00"
    sign = "+" if v > 0 else "−"
    return sign + _rate(abs(v))


SHORT_MAX = 26
SUMMARY_MAX = 155


def _short(name):
    """Chart-axis label: drop a ' - ' qualifier, then cut at a word boundary."""
    s = name.split(" - ")[0].strip() or name
    if len(s) <= SHORT_MAX:
        return s
    out = ""
    for w in s.split(" "):
        if len(out) + len(w) + (1 if out else 0) > SHORT_MAX:
            break
        out = f"{out} {w}" if out else w
    return (out or s[:SHORT_MAX]) + "…"


def _date(d):
    return f"{d.day}.{d.month}.{d.year}"


def _prepare(df):
    df = df.copy()
    df["name"] = df["interestname"].map(_clean)
    df["date"] = pd.to_datetime(df["ineffecfrom"].str.strip(),
                                format="%m/%d/%Y %I:%M:%S %p", errors="coerce")
    df["value"] = pd.to_numeric(df["annual"].str.replace(",", "").str.strip(),
                                errors="coerce")
    df = df[df["name"] != ""]
    return df[["name", "date", "value"]]


def _latest_per_name(df):
    """Current row per rate name + the rows it superseded (history)."""
    d = df.sort_values(["name", "date", "value"], kind="stable",
                       na_position="first")
    cur = d.groupby("name", sort=True).tail(1)
    return cur.reset_index(drop=True), d


def _find(cur, pred):
    rows = cur[cur["name"].map(pred) & cur["value"].notna()]
    if rows.empty:
        return None
    rows = rows.sort_values(["date", "name"], ascending=[False, True], kind="stable")
    return rows.iloc[0]


def _is_late(n):
    return any(w in n for w in LATE_WORDS)


def _is_base(n):
    return "חשב כללי" in n and not _is_late(n)


def _is_shekel(n):
    return "שקלית" in n and not _is_late(n)


def _is_linked(n):
    return "צמודה" in n and not _is_late(n)


def _is_infl(n):
    return "ציפיות האינפלציה" in n


def _is_a(n):
    return n.startswith("ערך A")


def _is_b(n):
    return n.startswith("ערך B")


# ---------------------------------------------------------------- insights

def insight_base(base, prev):
    if base is None:
        return None
    s = (f"ריבית החשב הכללי עומדת על {_rate(base['value'])}% בשנה, "
         f"בתוקף מ-{_date(base['date'])}" if pd.notna(base["date"]) else
         f"ריבית החשב הכללי עומדת על {_rate(base['value'])}% בשנה")
    if prev is not None and pd.notna(prev["value"]):
        diff = base["value"] - prev["value"]
        when = f" ({_date(prev['date'])})" if pd.notna(prev["date"]) else ""
        if abs(diff) < 0.00005:
            s += f", ללא שינוי לעומת השיעור הקודם{when}"
        else:
            word = "עלייה" if diff > 0 else "ירידה"
            s += (f", {word} של {_rate(abs(diff))} נקודות אחוז לעומת "
                  f"{_rate(prev['value'])}%{when}")
    return s + "."


def insight_late(base, cur):
    if base is None:
        return None
    late = cur[cur["name"].map(_is_late) & cur["value"].notna()].copy()
    if late.empty:
        return None
    late["gap"] = late["value"] - base["value"]
    late = late[late["gap"] > 0].sort_values(["gap", "name"], ascending=[False, True],
                                             kind="stable")
    if late.empty:
        return None
    parts = [f"{r['name']} ({_rate(r['value'])}%), גבוהה ב-{_rate(r['gap'])} נקודות אחוז"
             for _, r in late.head(3).iterrows()]
    return ("ריביות הפיגורים והאיחורים גבוהות בהרבה מריבית החשב הכללי "
            f"({_rate(base['value'])}%): " + "; ".join(parts) + ".")


def insight_real_nominal(shekel, linked, infl):
    if shekel is None or linked is None:
        return None
    gap = shekel["value"] - linked["value"]
    s = (f"הריבית השקלית ({_rate(shekel['value'])}%) גבוהה מהריבית הצמודה "
         f"({_rate(linked['value'])}%) ב-{_rate(abs(gap))} נקודות אחוז")
    if gap <= 0:
        s = (f"הריבית השקלית ({_rate(shekel['value'])}%) אינה גבוהה מהריבית הצמודה "
             f"({_rate(linked['value'])}%)")
        return s + "."
    if infl is not None:
        if abs(gap - infl["value"]) <= INFL_TOL:
            s += (f", כמעט בדיוק ממוצע ציפיות האינפלציה ({_rate(infl['value'])}%)")
        else:
            s += f"; ממוצע ציפיות האינפלציה עומד על {_rate(infl['value'])}%"
    return s + "."


def insight_composition(shekel, a, b):
    if shekel is None or a is None or b is None:
        return None
    mix = W_A * a["value"] + W_B * b["value"]
    if abs(mix - shekel["value"]) > MATCH_TOL:
        return None
    return (f"הריבית השקלית ({_rate(shekel['value'])}%) מתקבלת בנתונים הנוכחיים "
            f"משקלול של {int(W_A * 100)}% מערך A, ריבית שוק ההון ({_rate(a['value'])}%), "
            f"ו-{int(W_B * 100)}% מערך B, ריבית המערכת הבנקאית ({_rate(b['value'])}%).")


def insight_dates(pub):
    dated = pub[pub["date"].notna()]
    if dated.empty:
        return None
    g = (dated.groupby("date")["name"].apply(lambda s: sorted(s))
         .sort_index(ascending=False))
    if len(g) == 1:
        d = g.index[0]
        return f"כל {len(g.iloc[0]):,} הערכים המפורסמים בתוקף מאותו מועד, {_date(d)}."
    latest_d, latest_names = g.index[0], g.iloc[0]
    others = g.iloc[1:]
    parts = []
    for d, names in others.items():
        p = f"{len(names):,} מ-{_date(d)}"
        if len(names) <= 3:
            p += " (" + ", ".join(names) + ")"
        parts.append(p)
    return (f"{len(latest_names):,} מהערכים המפורסמים בתוקף מהמועד העדכני ביותר, "
            f"{_date(latest_d)}; " + "; ".join(parts) + ".")


def insight_inactive(cur):
    empty = cur[cur["value"].isna()].sort_values("name", kind="stable")
    if empty.empty:
        return None
    parts = []
    for _, r in empty.iterrows():
        parts.append(f"{r['name']}" + (f", תאריך תחולה {_date(r['date'])}"
                                      if pd.notna(r["date"]) else ""))
    n = len(empty)
    head = "ערך אחד במאגר מופיע" if n == 1 else f"{n:,} ערכים במאגר מופיעים"
    return f"{head} ללא שיעור מפורסם: " + "; ".join(parts) + "."


def _labels(names):
    short = [_short(n) for n in names]
    # A collision would merge two bars' labels — fall back to the full name.
    return [s if short.count(s) == 1 else n for s, n in zip(short, names)]


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["rates"])
    cur, hist = _latest_per_name(df)
    pub = cur[cur["value"].notna()]
    pub = pub.sort_values(["value", "name"], ascending=[False, True], kind="stable")
    n_all, n_pub = int(len(cur)), int(len(pub))

    base = _find(cur, _is_base)
    prev = None
    if base is not None:
        older = hist[(hist["name"] == base["name"]) & hist["value"].notna()]
        older = older[older["date"] < base["date"]] if pd.notna(base["date"]) else older.iloc[0:0]
        if not older.empty:
            prev = older.sort_values("date", kind="stable").iloc[-1]
    shekel = _find(cur, _is_shekel)
    linked = _find(cur, _is_linked)
    infl = _find(cur, _is_infl)
    a, b = _find(cur, _is_a), _find(cur, _is_b)

    rules = [
        ("base_rate", insight_base(base, prev)),
        ("late_gap", insight_late(base, cur)),
        ("real_nominal", insight_real_nominal(shekel, linked, infl)),
        ("shekel_mix", insight_composition(shekel, a, b)),
        ("effective_dates", insight_dates(pub)),
        ("unpublished", insight_inactive(cur)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs (ordered; template loops kpi_order)
    kpis, kpi_labels, order = {}, {}, []

    def add(key, value, display, label, tone="brand"):
        kpis[key] = {"value": value, "display": display, "tone": tone}
        kpi_labels[key] = label
        order.append(key)

    if base is not None:
        when = f", בתוקף מ-{_date(base['date'])}" if pd.notna(base["date"]) else ""
        tone = "brand"
        if prev is not None and base["value"] != prev["value"]:
            tone = "info"
        add("base", float(base["value"]), f"{_rate(base['value'])}%",
            f"ריבית החשב הכללי, שנתית{when}", tone)
    if shekel is not None:
        when = f", מ-{_date(shekel['date'])}" if pd.notna(shekel["date"]) else ""
        add("shekel", float(shekel["value"]), f"{_rate(shekel['value'])}%",
            f"ריבית שקלית, שנתית{when}")
    if linked is not None:
        when = f", מ-{_date(linked['date'])}" if pd.notna(linked["date"]) else ""
        add("linked", float(linked["value"]), f"{_rate(linked['value'])}%",
            f"ריבית צמודה, שנתית{when}")
    if n_pub:
        top = pub.iloc[0]
        add("highest", float(top["value"]), f"{_rate(top['value'])}%",
            f"הגבוהה במאגר: {top['name']}")
    add("published", n_pub, f"{n_pub:,}",
        f"ערכים עם שיעור מפורסם, מתוך {n_all:,} במאגר")

    # ---- table: every current rate (published first, by rate desc; then unpublished)
    rows = []
    base_v = float(base["value"]) if base is not None else None
    for _, r in pub.iterrows():
        rows.append({
            "name": r["name"],
            "rate": f"{_rate(r['value'])}%",
            "date": _date(r["date"]) if pd.notna(r["date"]) else "–",
            "gap": (_pp(r["value"] - base_v) if base_v is not None
                    and r["name"] != base["name"] else "–"),
            "is_base": bool(base is not None and r["name"] == base["name"]),
        })
    for _, r in cur[cur["value"].isna()].sort_values("name", kind="stable").iterrows():
        rows.append({"name": r["name"], "rate": "לא פורסם",
                     "date": _date(r["date"]) if pd.notna(r["date"]) else "–",
                     "gap": "–", "is_base": False})

    # ---- chart: published rates, ascending so the highest sits on top (horizontal bars)
    asc = pub.iloc[::-1]
    chart = {
        "names": list(asc["name"]),
        "labels": _labels(list(asc["name"])),
        "values": [round(float(v), 4) for v in asc["value"]],
        "base_name": base["name"] if base is not None else None,
        "base_value": base_v,
    }

    # ---- effective-date groups
    dated = pub[pub["date"].notna()]
    date_rows = []
    for d, grp in sorted(dated.groupby("date"), key=lambda x: x[0], reverse=True):
        date_rows.append({"date": _date(d), "n": f"{len(grp):,}",
                          "names": ", ".join(sorted(grp["name"]))})

    lo, hi = (pub["value"].min(), pub["value"].max()) if n_pub else (None, None)
    # summary_he is the meta description: <=155 chars, the searcher's answer first.
    parts = []
    if base is not None:
        lead = f"ריבית חשכ״ל היום: {_rate(base['value'])}%"
        if pd.notna(base["date"]):
            lead += f" (בתוקף מ-{_date(base['date'])})"
        parts.append(lead + ".")
    rates = []
    if shekel is not None:
        rates.append(f"ריבית שקלית {_rate(shekel['value'])}%")
    if linked is not None:
        rates.append(f"צמודה {_rate(linked['value'])}%")
    if rates:
        parts.append(", ".join(rates) + ".")
    parts.append(f"כל {n_pub:,} ריביות החשב הכללי בטבלה אחת.")
    summary = " ".join(parts)
    while len(summary) > SUMMARY_MAX and len(parts) > 1:
        parts.pop(-2 if len(parts) > 2 else -1)
        summary = " ".join(parts)

    dmin = dated["date"].min() if not dated.empty else None
    dmax = dated["date"].max() if not dated.empty else None

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "misc",
        "suggested_tags": ["ריבית", "ריבית חשכ״ל", "החשב הכללי", "חובות למדינה",
                           "ריבית פיגורים", "מימון ציבורי"],
        "related_ids": [],
        "spatial_coverage": "ישראל",
    }
    if dmin is not None:
        agent_data["temporal_coverage"] = f"{dmin.date().isoformat()}/{dmax.date().isoformat()}"

    chart_aria = (f"תרשים עמודות אופקי: {n_pub:,} הריביות המפורסמות, מהגבוהה לנמוכה. "
                  + (f"הגבוהה: {pub.iloc[0]['name']} ({_rate(hi)}%); " if n_pub else "")
                  + (f"ריבית החשב הכללי מסומנת ({_rate(base_v)}%)." if base_v is not None else ""))

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": order,
        "charts": {"rates": chart},
        "insights": insights,
        "tables": {"rates": rows, "dates": date_rows},
        "flags": {"has_chart": n_pub >= 2, "has_dates": len(date_rows) >= 1},
        "labels": {
            **{f"kpi_{k}": v for k, v in kpi_labels.items()},
            "rates_aria": chart_aria,
            "rates_caption": f"{n_all:,} הערכים במאגר: שיעור שנתי, תאריך תחולה ופער מריבית החשב הכללי.",
            "rates_lede": (f"השיעורים השנתיים כפי שפורסמו, מהגבוה לנמוך. העמודה האחרונה מציגה את הפער "
                           f"בנקודות אחוז מריבית החשב הכללי ({_rate(base_v)}%)."
                           if base_v is not None else
                           "השיעורים השנתיים כפי שפורסמו, מהגבוה לנמוך."),
            "dates_caption": f"הערכים המפורסמים לפי תאריך תחולה ({len(date_rows):,} מועדים).",
        },
    }
