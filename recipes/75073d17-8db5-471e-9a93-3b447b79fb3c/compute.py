"""מרכזי בריאות בבאר שבע — a point layer of clinics (the health funds) and
Ministry of Health sites (milk stations) with an operator, a neighbourhood
code and a street.  The source file lists every point twice and cuts text at
eight characters, so the recipe de-duplicates exact repeats, drops empty
placeholder rows (disclosed) and treats names / streets as display text only.

Order-independent: counts, medians and sorted aggregates only.
"""
import math
import re

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
NO_OPERATOR = "לא צוין"
NO_NEIGH = "לא צוין"
MINISTRY = "משרד הבריאות"
MILK_RE = re.compile(r"טי[פם]ת|חלב")
TOP_OPS = 6                # operators with their own colour (rest = "אחר")
TOP_NEIGH = 10             # neighbourhood bars (rest = "אחר")
MAP_CAP = 1500
BIN_M = 100
BIN_COUNT = 8
CLUSTER_M = 100
CLUSTER_SHARE = 0.2
LEAD_SHARE = 0.4
LEAD_MARGIN = 0.1
NEIGH_MIN = 3
NEIGH_SHARE = 0.1
R_KM = 6371.0088


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    out = df.copy()
    for c in ["Name", "address", "neighborho", "HMOname"]:
        out[c] = out[c].str.strip()
    out["neighborho"] = out["neighborho"].str.replace(r"\.\s+", ".", regex=True)
    out["lonf"] = pd.to_numeric(out["X"].str.strip(), errors="coerce")
    out["latf"] = pd.to_numeric(out["Y"].str.strip(), errors="coerce")
    n_rows = len(out)
    key = ["lonf", "latf", "Name", "address", "neighborho", "HMOname"]
    ok = out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    out = out[ok].copy()
    n_unique = len(out.drop_duplicates(subset=key))
    out = out.drop_duplicates(subset=key)
    empty = (out["Name"] == "") & (out["address"] == "") & (out["HMOname"] == "")
    n_empty = int(empty.sum())
    out = out[~empty].copy()
    out["op"] = out["HMOname"].where(out["HMOname"] != "", NO_OPERATOR)
    out["neigh"] = out["neighborho"].where(out["neighborho"] != "", NO_NEIGH)
    out["milk"] = out["Name"].str.contains(MILK_RE)
    out = out.sort_values(["op", "neigh", "lonf", "latf", "Name", "address"], kind="stable")
    return out.reset_index(drop=True), n_rows, n_unique, n_empty


def compute(frames):
    df, n_rows, n_unique, n_empty = _prepare(frames["clinics"])
    total = len(df)
    ops = _ranked(df["op"])
    named_ops = [o for o in ops.index if o not in (NO_OPERATOR,)]
    top_ops = list(ops.index[:TOP_OPS])
    rest_ops = len(ops) > TOP_OPS
    op_group = df["op"].where(df["op"].isin(top_ops), "אחר")

    # operator chart
    onames = top_ops + (["אחר"] if rest_ops else [])
    ovals = [int(ops[o]) for o in top_ops]
    if rest_ops:
        ovals.append(int(ops.iloc[TOP_OPS:].sum()))
    t_op = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
            for n, v in zip(onames, ovals)]

    # neighbourhood x operator
    neigh = _ranked(df["neigh"])
    top_n = list(neigh.index[:TOP_NEIGH])
    rest_n = len(neigh) > TOP_NEIGH
    ngroup = df["neigh"].where(df["neigh"].isin(top_n), "אחר")
    nnames = top_n + (["אחר"] if rest_n else [])
    ct = pd.crosstab(ngroup, op_group)
    series = []
    for o in onames:
        vals = [int(ct.loc[n, o]) if (n in ct.index and o in ct.columns) else 0 for n in nnames]
        series.append({"name": o, "values": vals})
    t_neigh = [{"name": n, "count": _int(sum(s["values"][i] for s in series)),
                "by_op": "، ".join(f"{s['name']} {_int(s['values'][i])}"
                                    for s in series if s["values"][i])}
               for i, n in enumerate(nnames)]

    # nearest neighbour (local equirectangular projection)
    lat0 = (df["latf"].min() + df["latf"].max()) / 2
    x = np.radians(df["lonf"].to_numpy()) * R_KM * math.cos(math.radians(lat0)) * 1000
    y = np.radians(df["latf"].to_numpy()) * R_KM * 1000
    if total > 1:
        dx = x[:, None] - x[None, :]
        dy = y[:, None] - y[None, :]
        dist = np.hypot(dx, dy)
        np.fill_diagonal(dist, np.inf)
        nn = dist.min(axis=1)
    else:
        nn = np.array([])
    has_nn = len(nn) > 0
    if has_nn:
        b = np.minimum((nn // BIN_M).astype(int), BIN_COUNT - 1)
        counts = [int((b == i).sum()) for i in range(BIN_COUNT)]
        edges = [f"{i * BIN_M}-{(i + 1) * BIN_M}" for i in range(BIN_COUNT - 1)]
        edges.append(f"מעל {(BIN_COUNT - 1) * BIN_M}")
        median_nn = float(np.median(nn))
        close_n = int((nn <= CLUSTER_M).sum())
    else:
        counts, edges, median_nn, close_n = [], [], 0.0, 0
    nearest = {"names": edges, "values": counts}
    t_nearest = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
                 for n, v in zip(edges, counts)] if has_nn else []

    # map points: [lat, lon, operator index, name, address, neighbourhood, operator]
    oidx = {o: i for i, o in enumerate(onames)}
    pts = []
    for r in df.head(MAP_CAP).itertuples():
        g = r.op if r.op in oidx else "אחר"
        pts.append([round(float(r.latf), 5), round(float(r.lonf), 5), oidx[g],
                    r.Name, r.address, r.neigh if r.neigh != NO_NEIGH else "", r.op])
    bounds = [[round(float(df["latf"].min()), 5), round(float(df["lonf"].min()), 5)],
              [round(float(df["latf"].max()), 5), round(float(df["lonf"].max()), 5)]]

    # ---- insights
    insights = []
    lead = ops.index[0]
    lead_share = ops.iloc[0] / total
    second = ops.iloc[1] / total if len(ops) > 1 else 0
    if lead != NO_OPERATOR and lead_share >= LEAD_SHARE and lead_share - second >= LEAD_MARGIN:
        insights.append({"id": "leader", "text_he": (
            f"{lead} מפעילה {_int(ops.iloc[0])} מתוך {_int(total)} הנקודות "
            f"({_pct(lead_share)}), לפני המפעיל השני בגודלו, {ops.index[1]} "
            f"עם {_int(ops.iloc[1])} ({_pct(second)}).")})
    n_milk = int(df["milk"].sum())
    if n_milk:
        insights.append({"id": "milk", "text_he": (
            f"{_int(n_milk)} מהנקודות מסומנות בשמן כטיפות חלב "
            f"({_pct(n_milk / total)} מהמאגר); שם הנקודה נחתך במקור, ולכן הספירה מבוססת על "
            f"התחילית של השם.")})
    lab = neigh.drop(labels=[NO_NEIGH], errors="ignore")
    if len(lab) and lab.iloc[0] >= NEIGH_MIN and lab.iloc[0] / total >= NEIGH_SHARE:
        insights.append({"id": "neigh", "text_he": (
            f"הקוד \"{lab.index[0]}\" בעמודת השכונה הוא הנפוץ ביותר: {_int(lab.iloc[0])} נקודות "
            f"({_pct(lab.iloc[0] / total)}). הקודים מקוצרים כפי שנכתבו בקובץ.")})
    labelled = df[(df["neigh"] != NO_NEIGH) & (df["op"] != NO_OPERATOR) & (df["op"] != MINISTRY)]
    per_n = labelled.groupby("neigh")["op"].nunique()
    multi = int((per_n >= 2).sum())
    if multi >= 1 and len(per_n):
        insights.append({"id": "mix", "text_he": (
            f"ב-{_int(multi)} מתוך {_int(len(per_n))} קודי השכונה שיש בהם מרפאות קופות חולים "
            f"פועלות מרפאות של שתי קופות או יותר.")})
    if has_nn and close_n / total >= CLUSTER_SHARE:
        insights.append({"id": "cluster", "text_he": (
            f"{_int(close_n)} נקודות ({_pct(close_n / total)}) נמצאות במרחק של עד "
            f"{_int(CLUSTER_M)} מטרים מנקודה אחרת; המרחק החציוני לנקודה הקרובה ביותר הוא "
            f"{_int(round(median_nn))} מטרים.")})
    elif has_nn:
        insights.append({"id": "nearest", "text_he": (
            f"המרחק החציוני בין נקודה לנקודה הקרובה אליה הוא {_int(round(median_nn))} מטרים.")})
    if n_rows > n_unique + n_empty and n_unique:
        insights.append({"id": "dups", "text_he": (
            f"הקובץ כולל {_int(n_rows)} שורות, אבל רק {_int(total)} נקודות ייחודיות עם פרטים: "
            f"שורות כפולות אוחדו"
            + (f" ו-{_int(n_empty)} שורות ריקות לא נספרו." if n_empty else "."))})

    clalit = int(ops.get("כללית", 0))
    clalit_share = clalit / total if total else 0
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand",
                  "label": "נקודות ייחודיות במאגר"},
        "milk": {"value": n_milk, "display": _int(n_milk), "tone": "brand",
                 "label": "נקודות שנקראות טיפת חלב"},
        "clalit": {"value": clalit_share, "display": _pct(clalit_share), "tone": "brand",
                   "label": "מהנקודות הן של כללית"},
        "nearest": {"value": median_nn, "display": _int(round(median_nn)), "tone": "brand",
                    "label": "מרחק חציוני לנקודה הקרובה ביותר (מטרים)"},
    }

    note = []
    if n_rows > n_unique + n_empty:
        note.append(f"הקובץ מכיל {_int(n_rows)} שורות, ורובן כפילויות מדויקות; הספירה כאן היא לפי נקודות ייחודיות")
    if n_empty:
        note.append(f"{_int(n_empty)} שורות ריקות הושמטו")
    note_txt = (" (" + "; ".join(note) + ")") if note else ""
    labels = {
        "lede": (f"{_int(total)} מרכזי בריאות בבאר שבע: מרפאות קופות החולים וטיפות חלב של משרד הבריאות, "
                 f"עם מפעיל, קוד שכונה ונקודת מיקום{note_txt}. שמות ורחובות נחתכו במקור לשמונה "
                 f"תווים, ולכן הם מוצגים כפי שהם."),
        "map_note": (f"{_int(total)} הנקודות על המפה, בצבע לפי המפעיל. לחצו על סמן כדי לראות את הפרטים "
                     f"כפי שנכתבו בקובץ."),
        "op_note": "מספר הנקודות לפי המפעיל; נקודה בלי מפעיל מסומנת \"לא צוין\".",
        "op_aria": f"תרשים עמודות אופקי: מספר הנקודות לפי מפעיל, {len(onames)} קבוצות.",
        "op_caption": "מספר הנקודות והשיעור שלהן לפי מפעיל.",
        "neigh_note": ("מספר הנקודות בכל קוד שכונה, בפילוח לפי מפעיל"
                       + (f"; {_int(TOP_NEIGH)} הקודים הנפוצים, והשאר מקובצים." if rest_n else ".")
                       + " הקודים מקוצרים כפי שנכתבו בקובץ."),
        "neigh_aria": f"תרשים עמודות אופקי מוערם: נקודות לפי קוד שכונה ומפעיל, {len(nnames)} קודים.",
        "neigh_caption": "מספר הנקודות לפי קוד שכונה, ופירוט לפי מפעיל.",
        "nearest_note": (f"מרחק קו אווירי מכל נקודה לנקודה הקרובה אליה, בקבוצות של {_int(BIN_M)} מטרים."),
        "nearest_aria": f"תרשים עמודות: התפלגות המרחק לנקודה הקרובה ביותר, {len(edges)} קבוצות.",
        "nearest_caption": "מספר הנקודות לפי המרחק לנקודה הקרובה ביותר (מטרים).",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} מרכזי בריאות בבאר שבע — מרפאות קופות חולים וטיפות חלב — "
                           f"לפי מפעיל ושכונה, עם מפה של כל הנקודות."),
            "dataset_kind": "map",
            "suggested_tags": ["בריאות", "מרפאות", "קופות חולים", "טיפות חלב", "באר שבע", "מפה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["d25f8679-13bc-4082-bf6e-6156e1d2df60",
                            "947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe",
                            "7edbd028-9704-440c-a1b6-a0ed566081bc",
                            "54b65747-904e-42e1-9316-0575ebbc1216",
                            "dae759e1-aa71-421a-8649-b8974a82bf2d"],
        },
        "kpis": kpis,
        "charts": {
            "op": {"names": onames, "values": ovals},
            "neigh": {"names": nnames, "series": series},
            "nearest": nearest,
            "map": {"points": pts, "ops": onames, "bounds": bounds},
        },
        "tables": {"op": t_op, "neigh": t_neigh, "nearest": t_nearest},
        "insights": insights,
        "has_nearest": has_nn,
        "labels": labels,
    }
