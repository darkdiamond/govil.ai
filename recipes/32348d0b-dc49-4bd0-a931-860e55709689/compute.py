"""סניפי בנקים פיזיים — Bank of Israel registry of physical bank branches.

One row per branch (Hebrew resource; an English twin carries the same rows).
A branch with a Close_Date is closed; the registry keeps it. Counts below are
of ACTIVE branches unless a sentence says otherwise. Coordinates: despite the
names, X_Coordinate is latitude and Y_Coordinate is longitude (the map
config in the template follows that).
"""
import re

import pandas as pd

TOP_BANKS = 10
TOP_CITIES = 15
OPEN_SINCE = 2000
CLOSE_RECENT_YEARS = 3
ISRAEL_LAT = (29.4, 33.4)
ISRAEL_LNG = (34.2, 35.95)
DAY_LABELS ={"יום ו": "שישי", "יום א": "ראשון", "יום ש": "שבת", "": "לא צוין"}
PRESENCE_CITIES = 10       # rows of the bank × city matrix
PRESENCE_BANKS = 8         # columns of the bank × city matrix
PRESENCE_MIN_BRANCHES = 10
PRESENCE_MIN_SHARE = 0.4
TABLE_YEARS = 20


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def short_bank(name):
    """'בנק הפועלים בע"מ' → 'בנק הפועלים' (labels only; counts use full names)."""
    return re.sub(r'\s*בע["״]?מ\s*$', "", name.strip()) or name


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    out = df.copy()
    for c in ["Bank_Name", "City", "Branch_Type", "day_closed", "Handicap_Access", "Close_Date", "Open_Date"]:
        out[c] = out[c].str.strip()
    out["bank"] = out["Bank_Name"].map(short_bank)
    out["city"] = out["City"].replace("", "לא צוין")
    out["opened"] = pd.to_datetime(out["Open_Date"], format="%d/%m/%Y", errors="coerce")
    out["closed"] = pd.to_datetime(out["Close_Date"], format="%d/%m/%Y", errors="coerce")
    out["active"] = out["Close_Date"] == ""
    return out


def insight_top_banks(act):
    banks = _ranked(act["bank"])
    if len(banks) < 2:
        return None
    a, b = banks.index[0], banks.index[1]
    two = int(banks.iloc[0] + banks.iloc[1])
    return (f"{a} ({_int(banks.iloc[0])}) ו{b} ({_int(banks.iloc[1])}) מחזיקים יחד "
            f"{_pct(two / len(act))} מהסניפים הפעילים.")


def insight_cities(act):
    cities = _ranked(act["city"])
    top = cities.head(2)
    share = top.sum() / len(act)
    if share < 0.1:
        return None
    return (f"{top.index[0]} ו{top.index[1]} לבדן מרכזות {_int(top.sum())} סניפים — "
            f"{_pct(share)} מכלל הסניפים הפעילים, ב-{_int(cities.size)} יישובים בסך הכול.")


def insight_closures(df):
    cl = df.loc[~df["active"] & df["closed"].notna()]
    if cl.empty:
        return None
    last = cl["closed"].max()
    since = last.year - CLOSE_RECENT_YEARS + 1
    recent = cl[cl["closed"].dt.year >= since]
    banks = _ranked(recent["bank"])
    if recent.empty:
        return None
    top_n = int(banks.iloc[0])
    leaders = list(banks[banks == top_n].index)
    if top_n < 3 or len(leaders) > 2:
        lead = ""
    elif len(leaders) == 2:
        lead = f", בעיקר ב{leaders[0]} וב{leaders[1]} ({_int(top_n)} בכל אחד)"
    else:
        lead = f", בעיקר ב{leaders[0]} ({_int(top_n)})"
    return (f"מאז {since} נסגרו {_int(len(recent))} סניפים{lead}. הסגירה האחרונה במאגר "
            f"נרשמה ב-{last.strftime('%m/%Y')}.")


def insight_sunday(act):
    sun = int((act["day_closed"] == "יום א").sum())
    if sun == 0:
        return None
    banks = _ranked(act.loc[act["day_closed"] == "יום א", "bank"])
    names = ", ".join(banks.index[:3])
    return (f"{_int(sun)} סניפים ({_pct(sun / len(act))}) סגורים ביום ראשון ולא בשישי — "
            f"בעיקר אצל {names}.")


def insight_access(act):
    no = act[act["Handicap_Access"] == "לא"]
    if no.empty:
        return f"כל {_int(len(act))} הסניפים הפעילים מסומנים כנגישים לאנשים עם מוגבלות."
    banks = _ranked(no["bank"])
    lead = "הרוב" if banks.iloc[0] > len(no) / 2 else "המספר הגדול ביותר"
    return (f"{_int(len(no))} סניפים פעילים ({_pct(len(no) / len(act), 1)}) אינם מסומנים "
            f"כנגישים לאנשים עם מוגבלות; {lead} ב{banks.index[0]} ({_int(banks.iloc[0])}).")


def insight_digital(act):
    dig = act[act["Branch_Type"].str.contains("דיגיטלי")]
    if dig.empty:
        return None
    banks = _ranked(dig["bank"])
    return (f"{_int(len(dig))} מהסניפים הפעילים מוגדרים כסניפים דיגיטליים; "
            f"{banks.index[0]} מפעיל {_int(banks.iloc[0])} מהם.")


def insight_merges(df):
    """Closures that were mergers into another branch (Merge_Branch set)."""
    cl = df[~df["active"]]
    if len(cl) < 5:
        return None
    merged = int((cl["Merge_Branch"].str.strip() != "").sum())
    if merged == 0:
        return (f"אף אחד מ-{_int(len(cl))} הסניפים שנסגרו אינו רשום כמאוחד לסניף אחר — "
                f"כולם נסגרו ללא סניף ממשיך במרשם.")
    return (f"מתוך {_int(len(cl))} הסניפים שנסגרו, {_int(merged)} ({_pct(merged / len(cl))}) "
            f"רשומים כמאוחדים לסניף אחר, והשאר נסגרו ללא סניף ממשיך במרשם.")


def insight_presence(act, top_cities):
    """The city where a single bank holds the largest share of branches
    (among the top cities, ≥10 branches, ≥40% share)."""
    best = None
    for city in top_cities:
        sub = act[act["city"] == city]
        if len(sub) < PRESENCE_MIN_BRANCHES:
            continue
        banks = _ranked(sub["bank"])
        share = banks.iloc[0] / len(sub)
        key = (share, -top_cities.index(city))
        if share >= PRESENCE_MIN_SHARE and (best is None or key > best[0]):
            best = (key, city, banks.index[0], int(banks.iloc[0]), len(sub))
    if best is None:
        return None
    _, city, bank, n, tot = best
    return (f"ב{city} {bank} מחזיק {_int(n)} מתוך {_int(tot)} הסניפים הפעילים "
            f"({_pct(n / tot)}) — הריכוזיות הגבוהה ביותר של בנק אחד בין היישובים הגדולים.")


def compute(frames):
    df = _prepare(frames["branches"])
    act = df[df["active"]]
    n_act, n_closed = len(act), int((~df["active"]).sum())

    banks = _ranked(act["bank"])
    top_banks = list(banks.index[:TOP_BANKS])
    other_banks = int(banks.iloc[TOP_BANKS:].sum())
    types = _ranked(act["Branch_Type"]).index.tolist()
    by_bank_type = act.groupby(["bank", "Branch_Type"]).size()
    banks_chart = {
        "names": top_banks + (["בנקים אחרים"] if other_banks else []),
        "series": [
            {"name": t,
             "data": [int(by_bank_type.get((b, t), 0)) for b in top_banks] +
                     ([int(act.loc[~act["bank"].isin(top_banks) & (act["Branch_Type"] == t)].shape[0])]
                      if other_banks else [])}
            for t in types
        ],
    }

    cities = _ranked(act["city"])
    cities_chart = {"names": list(cities.index[:TOP_CITIES]),
                    "values": [int(v) for v in cities.iloc[:TOP_CITIES]]}

    days = _ranked(act["day_closed"])
    by_bank_day = act.groupby(["bank", "day_closed"]).size()
    day_chart = {
        "names": top_banks,
        "series": [{"name": DAY_LABELS.get(d, d),
                    "data": [int(by_bank_day.get((b, d), 0)) for b in top_banks]}
                   for d in days.index],
    }

    opened = df.loc[df["opened"].notna() & (df["opened"].dt.year >= OPEN_SINCE)]
    closed = df.loc[df["closed"].notna()]
    years = sorted(set(opened["opened"].dt.year) | set(closed["closed"].dt.year))
    o_y, c_y = opened["opened"].dt.year.value_counts(), closed["closed"].dt.year.value_counts()
    flow_chart = {"x": [str(y) for y in years],
                  "opened": [int(o_y.get(y, 0)) for y in years],
                  "closed": [int(c_y.get(y, 0)) for y in years]}

    access = act.groupby("bank")["Handicap_Access"].apply(lambda s: (s == "כן").mean())
    access = access[access.index.isin(top_banks)].reindex(top_banks)
    access_chart = {"names": top_banks, "values": [round(float(v) * 100, 1) for v in access]}

    closed_rows = df.loc[~df["active"]].sort_values(
        ["closed", "bank", "Branch_Name", "Branch_Code"], na_position="first", kind="stable")
    t_closed = [{"date": (r["closed"].strftime("%d/%m/%Y") if pd.notna(r["closed"]) else r["Close_Date"]),
                 "bank": r["bank"], "branch": r["Branch_Name"], "city": r["city"]}
                for _, r in closed_rows.tail(15).iloc[::-1].iterrows()]
    t_banks = [{"name": b, "count": _int(v), "share": _pct(v / n_act, 1)} for b, v in banks.items()]
    t_cities = [{"name": c, "count": _int(v), "share": _pct(v / n_act, 1)}
                for c, v in cities.iloc[:TOP_CITIES].items()]
    t_days = {"cols": [s["name"] for s in day_chart["series"]],
              "rows": [{"name": b, "vals": [_int(s["data"][i]) for s in day_chart["series"]]}
                       for i, b in enumerate(top_banks)]}
    t_flow = [{"year": x, "opened": _int(o), "closed": _int(c)}
              for x, o, c in list(zip(flow_chart["x"], flow_chart["opened"],
                                      flow_chart["closed"]))[-TABLE_YEARS:]]
    t_access = [{"name": n, "share": f"{v:.1f}"} for n, v in zip(access_chart["names"], access_chart["values"])]

    # Closures by bank, split by whether the branch was merged into another.
    cl = df[~df["active"]]
    merged = cl["Merge_Branch"].str.strip() != ""
    cl_banks = _ranked(cl["bank"])
    status_chart = {
        "names": list(cl_banks.index),
        "series": [
            {"name": "אוחד לסניף אחר",
             "data": [int((merged & (cl["bank"] == b)).sum()) for b in cl_banks.index]},
            {"name": "נסגר ללא סניף ממשיך",
             "data": [int((~merged & (cl["bank"] == b)).sum()) for b in cl_banks.index]},
        ],
    }
    t_status = [{"name": b, "closed": _int(cl_banks[b]),
                 "merged": _int(status_chart["series"][0]["data"][i]),
                 "active": _int(banks.get(b, 0))}
                for i, b in enumerate(cl_banks.index)]

    # Bank × city presence: the largest cities against the largest banks.
    p_cities = list(cities.index[:PRESENCE_CITIES])
    p_banks = list(banks.index[:PRESENCE_BANKS])
    by_city_bank = act.groupby(["city", "bank"]).size()
    presence = {
        "cities": p_cities, "banks": p_banks,
        "cells": [[bi, ci, int(by_city_bank.get((c, b), 0))]
                  for ci, c in enumerate(p_cities) for bi, b in enumerate(p_banks)],
    }
    presence["max"] = max((c[2] for c in presence["cells"]), default=0)
    t_presence = {"cols": p_banks,
                  "rows": [{"name": c, "vals": [_int(by_city_bank.get((c, b), 0)) for b in p_banks]}
                           for c in p_cities]}

    rules = [
        ("top_banks", insight_top_banks(act)),
        ("cities", insight_cities(act)),
        ("closures", insight_closures(df)),
        ("sunday", insight_sunday(act)),
        ("access", insight_access(act)),
        ("digital", insight_digital(act)),
        ("merges", insight_merges(df)),
        ("presence", insight_presence(act, list(cities.index[:PRESENCE_CITIES]))),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # Rows whose point would land outside Israel (swapped or garbage coords) —
    # GovMap plots every row, so the map note discloses them.
    lat = pd.to_numeric(df["X_Coordinate"], errors="coerce")
    lng = pd.to_numeric(df["Y_Coordinate"], errors="coerce")
    in_box = lat.between(*ISRAEL_LAT) & lng.between(*ISRAEL_LNG)
    n_bad_xy = int((lat.notna() & lng.notna() & ~in_box).sum())
    n_no_xy = int((lat.isna() | lng.isna()).sum())

    accessible = float((act["Handicap_Access"] == "כן").mean()) if n_act else 0.0
    kpis = {
        "active": {"value": n_act, "display": _int(n_act)},
        "banks": {"value": int(banks.size), "display": _int(banks.size)},
        "cities": {"value": int(cities.size), "display": _int(cities.size)},
        "accessible": {"value": accessible, "display": _pct(accessible)},
    }

    labels = {
        "lede": (f"מרשם הסניפים הפיזיים של הבנקים בישראל: {_int(n_act)} סניפים פעילים של "
                 f"{_int(banks.size)} בנקים ב-{_int(cities.size)} יישובים, ועוד {_int(n_closed)} "
                 f"סניפים שנסגרו ונשמרו במרשם. לכל סניף: כתובת, טלפון, יום סגירה, נגישות ומיקום."),
        "map_note": (f"כל {_int(len(df))} הסניפים במרשם, כולל {_int(n_closed)} שנסגרו (מצוין בחלונית). "
                     f"לחצו על אשכול להתקרבות."
                     + ("" if not n_no_xy else
                        " לסניף אחד אין מיקום במרשם." if n_no_xy == 1 else
                        f" ל-{_int(n_no_xy)} סניפים אין מיקום במרשם.")
                     + ("" if not n_bad_xy else
                        " לסניף אחד רשום מיקום שגוי מחוץ לישראל, והוא מופיע במפה במקום הרשום."
                        if n_bad_xy == 1 else
                        f" ל-{_int(n_bad_xy)} סניפים רשום מיקום שגוי מחוץ לישראל, והם מופיעים "
                        f"במפה במקום הרשום.")),
        "banks_aria": f"תרשים עמודות אופקי מוערם: סניפים פעילים לפי בנק וסוג סניף, {len(top_banks)} הבנקים הגדולים.",
        "banks_note": (f"{len(top_banks)} הבנקים עם מספר הסניפים הגבוה ביותר; השאר מקובצים."
                       if other_banks else "סניפים פעילים לפי בנק וסוג סניף."),
        "cities_aria": f"תרשים עמודות אופקי: {len(cities_chart['names'])} היישובים עם מספר הסניפים הגבוה ביותר.",
        "day_aria": "תרשים עמודות אופקי מוערם: סניפים פעילים לפי בנק ויום הסגירה השבועי.",
        "flow_aria": (f"תרשים עמודות: סניפים שנפתחו ונסגרו בכל שנה, "
                      f"{years[0] if years else OPEN_SINCE} עד {years[-1] if years else OPEN_SINCE}."),
        "flow_note": (f"תאריכי פתיחה כפי שנרשמו במרשם, משנת {OPEN_SINCE}. ייתכן שתאריך פתיחה "
                      f"משקף רישום מחדש (למשל במיזוג) ולא פתיחה פיזית. סגירות — לפי תאריך הסגירה."),
        "access_aria": "תרשים עמודות אופקי: שיעור הסניפים המסומנים כנגישים, לפי בנק.",
        "closed_caption": "הסניפים שנסגרו לאחרונה לפי תאריך הסגירה.",
        "banks_caption": "מספר הסניפים הפעילים לפי בנק.",
        "cities_caption": f"{len(t_cities)} היישובים עם מספר הסניפים הפעילים הגבוה ביותר.",
        "days_caption": "סניפים פעילים לפי בנק ויום הסגירה השבועי.",
        "flow_caption": f"סניפים שנפתחו ונסגרו בכל שנה, {len(t_flow)} השנים האחרונות.",
        "access_caption": "שיעור הסניפים הפעילים המסומנים כנגישים, לפי בנק (באחוזים).",
        "status_aria": (f"תרשים עמודות אופקי מוערם: {_int(len(cl))} הסניפים שנסגרו, לפי בנק "
                        f"ולפי האם אוחדו לסניף אחר."),
        "status_note": (f"כל הסניפים שנסגרו ונשמרו במרשם ({_int(len(cl))}), לפי בנק. סניף "
                        f"\"אוחד\" — רשום במרשם סניף ממשיך שאליו הועבר."),
        "status_caption": "סניפים שנסגרו לפי בנק: סך הכול, מתוכם אוחדו, ומספר הסניפים הפעילים.",
        "presence_aria": (f"מפת חום: מספר הסניפים הפעילים של {len(p_banks)} הבנקים הגדולים "
                          f"ב-{len(p_cities)} היישובים עם הכי הרבה סניפים."),
        "presence_caption": (f"סניפים פעילים לפי יישוב ובנק — {len(p_cities)} היישובים ו-"
                             f"{len(p_banks)} הבנקים הגדולים."),
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(n_act)} סניפי בנקים פעילים ב-{_int(cities.size)} יישובים, לפי בנק, "
                           f"סוג סניף, יום סגירה ונגישות — כולל מפה וסניפים שנסגרו."),
            "dataset_kind": "map",
            "suggested_tags": ["בנקים", "סניפי בנק", "נגישות", "שירותים פיננסיים"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "banks": banks_chart,
            "cities": cities_chart,
            "days": day_chart,
            "flow": flow_chart,
            "access": access_chart,
            "status": status_chart,
            "presence": presence,
        },
        "tables": {"closed": t_closed, "banks": t_banks, "cities": t_cities, "days": t_days,
                   "flow": t_flow, "access": t_access, "status": t_status,
                   "presence": t_presence},
        "insights": insights,
        "labels": labels,
    }
