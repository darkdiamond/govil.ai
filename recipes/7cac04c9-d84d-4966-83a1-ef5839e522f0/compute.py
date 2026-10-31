"""Light-rail depots (maintenance and operation yards), existing and planned.

One row per depot polygon: name, status, area in dunams, perimeter and the
year-month the record was last updated. Every number on the page is
computed here; insight rules return None when their premise doesn't hold.
"""
import math
import re

import pandas as pd

# Known statuses, ordered along the delivery pipeline. Unknown statuses
# flow through after these, alphabetically.
STATUS_ORDER = ["קיים", "בביצוע", "מתוכנן"]
STATUS_COLOR = {"קיים": "#0b3668", "בביצוע": "#0068f5", "מתוכנן": "#9fc3f8"}
OTHER_COLOR = "#6c757d"
NO_LINE = "ללא קו בשם"
LINE_RE = re.compile(r"קו\s+([^\s\-–]+)")
# Size bands in dunams (lower bound inclusive).
BANDS = [(0, 25), (25, 50), (50, 100), (100, None)]
MAX_ROWS = 40  # chart/table cap; the registry holds a dozen today


def _f1(v):
    return f"{v:,.1f}"


def _pct(v):
    return f"{v * 100:.0f}%"


def _ym(v):
    v = int(v)
    return f"{v % 100:02d}/{v // 100}"


STATUS_PLURAL = {"קיים": "קיימים", "מתוכנן": "מתוכננים"}


def _in_depots(k):
    return "במתחם אחד" if k == 1 else f"ב-{k:,} מתחמים"


def _n_depots(k):
    return "מתחם אחד" if k == 1 else f"{k:,} מתחמים"


def _status_key(s):
    return (STATUS_ORDER.index(s), "") if s in STATUS_ORDER else (len(STATUS_ORDER), s)


def _line_of(name):
    m = LINE_RE.search(name)
    return f"קו {m.group(1)}" if m else NO_LINE


def _prepare(df):
    df = df.copy()
    df["name"] = df["NAME"].str.strip()
    df["status"] = df["STATUS"].str.strip().replace("", "לא צוין")
    df["dunam"] = pd.to_numeric(df["DUNAM"].str.replace(",", ""), errors="coerce")
    area_m2 = pd.to_numeric(df["Shape_Area"].str.replace(",", ""), errors="coerce")
    # Fall back to the polygon area when DUNAM is blank.
    df["dunam"] = df["dunam"].fillna(area_m2 / 1000)
    per = pd.to_numeric(df["Shape_Length"].str.replace(",", ""), errors="coerce")
    per2 = pd.to_numeric(df["SHAPE_Leng"].str.replace(",", ""), errors="coerce")
    df["perim"] = per.fillna(per2)
    df["ym"] = pd.to_numeric(df["YEARMONTH"], errors="coerce")
    df = df[(df["name"] != "") & df["dunam"].notna() & (df["dunam"] > 0)].copy()
    df["line"] = df["name"].map(_line_of)
    df["compact"] = [
        (4 * math.pi * a * 1000 / p ** 2) if (p == p and p > 0) else None
        for a, p in zip(df["dunam"], df["perim"])
    ]
    df = df.sort_values(["dunam", "name", "status", "perim"],
                        ascending=[False, True, True, True], kind="stable")
    return df.reset_index(drop=True)


def _depot_label(r, dup_names):
    return f"{r['name']} ({r['status']})" if r["name"] in dup_names else r["name"]


# ---------------------------------------------------------------- insights

def insight_pipeline(by_status, total):
    planned = by_status.get("מתוכנן")
    if planned is None or total <= 0:
        return None
    share = planned["area"] / total
    if share >= 0.5:
        return (f"רוב שטח הדיפו עדיין על הנייר: {planned['count']:,} מתחמים מתוכננים "
                f"משתרעים על {_f1(planned['area'])} דונם, {_pct(share)} מכלל השטח במאגר.")
    if share >= 0.2:
        return (f"{planned['count']:,} מתחמים מתוכננים משתרעים על {_f1(planned['area'])} דונם, "
                f"{_pct(share)} מכלל השטח במאגר.")
    return None


def insight_operational(by_status, total, n):
    ex = by_status.get("קיים")
    if ex is None or total <= 0:
        return None
    share = ex["area"] / total
    word = "רק" if share < 0.34 else ""
    head = f"{word} {ex['count']:,}".strip()
    return (f"{head} מתוך {n:,} המתחמים פעילים כיום, בשטח של {_f1(ex['area'])} דונם "
            f"({_pct(share)} מהשטח).")


def insight_largest(df):
    if len(df) < 3:
        return None
    top = df.iloc[0]
    med = float(df["dunam"].median())
    if med <= 0:
        return None
    ratio = top["dunam"] / med
    if ratio < 1.5:
        return None
    return (f"המתחם הגדול ביותר הוא {top['name']} ({top['status']}), {_f1(top['dunam'])} דונם: "
            f"פי {ratio:.1f} מהחציון ({_f1(med)} דונם).")


def insight_line_lead(by_line, total):
    named = by_line[by_line["line"] != NO_LINE]
    if len(named) < 2 or total <= 0:
        return None
    top, second = named.iloc[0], named.iloc[1]
    if top["area"] <= second["area"] * 1.05:
        return None
    return (f"ל{top['line']} מוקצה השטח הגדול ביותר: {_f1(top['area'])} דונם {_in_depots(int(top['count']))} "
            f"({_pct(top['area'] / total)} מהשטח), לפני {second['line']} עם "
            f"{_f1(second['area'])} דונם. השיוך לקו נגזר משם המתחם.")


def insight_expansion(df):
    """A line with an existing depot and more depot area still to come."""
    best = None
    for line, g in df[df["line"] != NO_LINE].groupby("line", sort=True):
        ex = g.loc[g["status"] == "קיים", "dunam"].sum()
        more = g.loc[g["status"] != "קיים", "dunam"].sum()
        if ex > 0 and more > 0:
            cand = (more / ex, line, ex, more)
            if best is None or cand[0] > best[0]:
                best = cand
    if best is None:
        return None
    ratio, line, ex, more = best
    return (f"ב{line} פועלים היום {_f1(ex)} דונם של דיפו, ובתכנון או בביצוע עוד "
            f"{_f1(more)} דונם: תוספת של {_pct(ratio)} לשטח הקיים.")


def insight_vintage(df):
    ym = df["ym"].dropna()
    if ym.empty:
        return None
    latest = int(ym.max())
    n_latest = int((ym == latest).sum())
    if ym.nunique() < 2:
        return f"כל {len(ym):,} הרשומות עודכנו לאחרונה ב-{_ym(latest)}."
    mode = int(ym.value_counts().sort_index().sort_values(ascending=False, kind="stable").index[0])
    n_mode = int((ym == mode).sum())
    if mode == latest:
        return (f"העדכון האחרון במאגר הוא מ-{_ym(latest)} ({n_latest:,} רשומות); "
                f"שאר הרשומות ותיקות יותר.")
    newest = df[df["ym"] == latest].sort_values("name")["name"].tolist()
    who = newest[0] if len(newest) == 1 else f"{n_latest:,} מתחמים"
    return (f"{n_mode:,} מתוך {len(ym):,} הרשומות עודכנו לאחרונה ב-{_ym(mode)}; "
            f"הרשומה העדכנית ביותר ({who}) היא מ-{_ym(latest)}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    n = len(df)
    total = float(df["dunam"].sum())

    # status
    statuses = sorted(df["status"].unique(), key=_status_key)
    by_status = {}
    for s in statuses:
        g = df[df["status"] == s]
        by_status[s] = {"count": len(g), "area": float(g["dunam"].sum())}
    status_colors = [STATUS_COLOR.get(s, OTHER_COLOR) for s in statuses]

    # line (parsed from the name)
    rows = []
    for line, g in df.groupby("line", sort=True):
        rows.append({"line": line, "count": len(g), "area": float(g["dunam"].sum()),
                     **{s: float(g.loc[g["status"] == s, "dunam"].sum()) for s in statuses}})
    by_line = pd.DataFrame(rows)
    by_line["_last"] = by_line["line"] == NO_LINE
    by_line = by_line.sort_values(["_last", "area", "line"], ascending=[True, False, True],
                                  kind="stable").reset_index(drop=True)

    # depots
    dup_names = set(df["name"][df["name"].duplicated(keep=False)])
    shown = df.head(MAX_ROWS)
    capped = n > MAX_ROWS
    depot_labels = [_depot_label(r, dup_names) for _, r in shown.iterrows()]
    # Same name and status twice: number the repeats so chart labels stay distinct.
    seen = {}
    for i, lab in enumerate(depot_labels):
        seen[lab] = seen.get(lab, 0) + 1
        if seen[lab] > 1:
            depot_labels[i] = f"{lab} {seen[lab]}"

    # size bands
    band_names, band_counts = [], {s: [] for s in statuses}
    for lo, hi in BANDS:
        name = f"{lo}-{hi} דונם" if hi else f"{lo}+ דונם"
        band_names.append(name)
        m = (df["dunam"] >= lo) & ((df["dunam"] < hi) if hi else True)
        for s in statuses:
            band_counts[s].append(int((m & (df["status"] == s)).sum()))
    band_totals = [sum(band_counts[s][i] for s in statuses) for i in range(len(BANDS))]

    # shape
    shp = shown[shown["compact"].notna()]
    shape_pts = [[round(float(r["perim"])), round(float(r["dunam"]), 1),
                  round(float(r["compact"]), 2), lab, r["status"]]
                 for (_, r), lab in zip(shown.iterrows(), depot_labels) if r["compact"] == r["compact"]]
    compact_sorted = shp.sort_values(["compact", "name", "status"], kind="stable")
    elong = compact_sorted.iloc[0] if len(compact_sorted) else None
    compact = compact_sorted.iloc[-1] if len(compact_sorted) else None

    # vintage
    ym = df["ym"].dropna().astype(int)
    vint = ym.value_counts().sort_index()
    latest_ym = int(ym.max()) if len(ym) else None

    largest = df.iloc[0]
    median = float(df["dunam"].median())
    ex_area = by_status.get("קיים", {"area": 0.0})["area"]
    ex_share = ex_area / total if total else 0.0

    rules = [
        ("pipeline", insight_pipeline(by_status, total)),
        ("operational", insight_operational(by_status, total, n)),
        ("largest", insight_largest(df)),
        ("line_lead", insight_line_lead(by_line, total)),
        ("expansion", insight_expansion(df)),
        ("vintage", insight_vintage(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    status_phrase = ", ".join(
        f"{by_status[s]['count']:,} {STATUS_PLURAL.get(s, s) if by_status[s]['count'] > 1 else s}"
        for s in statuses)

    status_table = [{"name": s, "count": f"{by_status[s]['count']:,}",
                     "area": _f1(by_status[s]["area"]),
                     "share": _pct(by_status[s]["area"] / total) if total else "0%",
                     "avg": _f1(by_status[s]["area"] / by_status[s]["count"])}
                    for s in statuses]

    line_table = [{"name": r["line"], "count": f"{int(r['count']):,}", "area": _f1(r["area"]),
                   "share": _pct(r["area"] / total) if total else "0%",
                   "parts": "; ".join(f"{s} {_f1(r[s])}" for s in statuses if r[s] > 0)}
                  for _, r in by_line.iterrows()]

    depot_table = [{"name": lab, "status": r["status"], "area": _f1(r["dunam"]),
                    "share": _pct(r["dunam"] / total) if total else "0%",
                    "perim": f"{round(float(r['perim'])):,}" if r["perim"] == r["perim"] else "",
                    "compact": f"{r['compact']:.2f}" if r["compact"] == r["compact"] else "",
                    "ym": _ym(r["ym"]) if r["ym"] == r["ym"] else ""}
                   for (_, r), lab in zip(shown.iterrows(), depot_labels)]

    cap_note = (f" מוצגים {MAX_ROWS:,} המתחמים הגדולים מתוך {n:,}." if capped else "")
    lines_named = int((by_line["line"] != NO_LINE).sum())
    no_line_n = int(by_line.loc[by_line["line"] == NO_LINE, "count"].sum())

    summary = (f"איתור מתחמי הדיפו של הרכבת הקלה לפי שם וסטטוס: {n:,} מתחמים ({status_phrase}) "
               f"בשטח כולל של {_f1(total)} דונם.")
    if len(summary) > 155:
        summary = (f"מתחמי דיפו של הרכבת הקלה: {n:,} מתחמים בשטח כולל של {_f1(total)} דונם, "
                   f"לפי שם, סטטוס ושטח.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "count": {"value": n, "display": f"{n:,}", "tone": "brand"},
            "area": {"value": round(total, 1), "display": _f1(total), "tone": "brand"},
            "ex_share": {"value": round(ex_share, 3), "display": _pct(ex_share),
                         "tone": "warn" if ex_share < 0.5 else "ok"},
            "largest": {"value": round(float(largest["dunam"]), 1),
                        "display": _f1(largest["dunam"]), "tone": "info"},
        },
        "charts": {
            "depots": {"names": depot_labels,
                       "area": [round(float(v), 1) for v in shown["dunam"]],
                       "status": list(shown["status"]),
                       "colors": [STATUS_COLOR.get(s, OTHER_COLOR) for s in shown["status"]],
                       "median": round(median, 1)},
            "status": {"names": statuses, "colors": status_colors,
                       "count": [by_status[s]["count"] for s in statuses],
                       "area": [round(by_status[s]["area"], 1) for s in statuses],
                       "count_share": [round(by_status[s]["count"] / n * 100, 1) for s in statuses],
                       "area_share": [round(by_status[s]["area"] / total * 100, 1) if total else 0
                                      for s in statuses]},
            "lines": {"names": list(by_line["line"]), "statuses": statuses, "colors": status_colors,
                      "series": [[round(float(v), 1) for v in by_line[s]] for s in statuses]},
            "bands": {"names": band_names, "statuses": statuses, "colors": status_colors,
                      "series": [band_counts[s] for s in statuses]},
            "shape": {"points": shape_pts, "statuses": statuses, "colors": status_colors},
            "vintage": {"x": [_ym(v) for v in vint.index], "y": [int(c) for c in vint.values]},
        },
        "tables": {
            "status": status_table,
            "lines": line_table,
            "depots": depot_table,
            "bands": [{"name": band_names[i], "total": f"{band_totals[i]:,}",
                       "parts": "; ".join(f"{s} {band_counts[s][i]:,}" for s in statuses
                                          if band_counts[s][i])}
                      for i in range(len(BANDS))],
            "vintage": [{"ym": _ym(v), "count": f"{int(c):,}"} for v, c in vint.items()],
        },
        "insights": insights,
        "labels": {
            "lede": (f"המאגר של משרד התחבורה ממפה {n:,} מתחמי תחזוקה ותפעול (דיפו וחניוני קרונות) "
                     f"של הרכבת הקלה, קיימים ומתוכננים, בשטח כולל של {_f1(total)} דונם. "
                     f"לכל מתחם מופיעים שמו, סטטוס התכנון ({status_phrase}), שטחו בדונמים, "
                     f"היקף הפוליגון ומועד העדכון האחרון."),
            "count_kpi": "מתחמי דיפו במאגר",
            "area_kpi": "שטח כולל (דונם)",
            "ex_share_kpi": "שיעור השטח במתחמים פעילים",
            "largest_kpi": f"המתחם הגדול (דונם): {largest['name']}",
            "depots_lede": (f"המתחמים מדורגים לפי שטח וצבועים לפי סטטוס. החציון עומד על "
                            f"{_f1(median)} דונם, והגדול ביותר, {largest['name']}, משתרע על "
                            f"{_f1(largest['dunam'])} דונם.{cap_note}"),
            "depots_aria": (f"תרשים עמודות: שטח {len(shown):,} מתחמי דיפו בדונמים, מהגדול "
                            f"({largest['name']}, {_f1(largest['dunam'])}) לקטן."),
            "status_lede": (f"השוואה בין חלקו של כל סטטוס במספר המתחמים ובשטח. " +
                            " ".join(f"{s}: {_n_depots(by_status[s]['count'])}, "
                                     f"{_pct(by_status[s]['area'] / total) if total else '0%'} מהשטח."
                                     for s in statuses)),
            "status_aria": (f"תרשים עמודות: שיעור המתחמים ושיעור השטח לפי סטטוס, "
                            f"{len(statuses):,} סטטוסים."),
            "lines_lede": (f"השיוך לקו נגזר מהמילה \"קו\" בשם המתחם: {lines_named:,} קווים מזוהים"
                           + (f", ו-{no_line_n:,} מתחמים ששמם אינו מציין קו מופיעים בנפרד."
                              if no_line_n else ".")),
            "lines_aria": f"תרשים עמודות נערמות: שטח הדיפו בדונמים לפי קו וסטטוס, {len(by_line):,} קבוצות.",
            "bands_lede": (f"התפלגות המתחמים לפי גודל: " +
                           ", ".join(f"{band_names[i]}: {band_totals[i]:,}" for i in range(len(BANDS)))
                           + "."),
            "bands_aria": f"תרשים עמודות נערמות: מספר המתחמים בכל טווח גודל לפי סטטוס, {len(BANDS):,} טווחים.",
            "shape_lede": (
                (f"מדד הקומפקטיות (בין אפס לאחת, אחת היא עיגול מושלם) משווה שטח להיקף. "
                 f"המתחם המוארך ביותר הוא {elong['name']} ({elong['status']}, {elong['compact']:.2f}), "
                 f"והקומפקטי ביותר {compact['name']} ({compact['status']}, {compact['compact']:.2f}). "
                 f"ככל שהנקודה נמוכה יותר ביחס להיקפה, המתחם צר וארוך יותר.")
                if elong is not None else ""),
            "shape_aria": f"תרשים פיזור: שטח בדונמים מול היקף במטרים, {len(shape_pts):,} מתחמים.",
            "vintage_lede": (f"מועד העדכון האחרון של כל רשומה. הרשומה העדכנית ביותר היא מ-{_ym(latest_ym)}."
                             if latest_ym else ""),
            "vintage_aria": f"תרשים עמודות: מספר הרשומות לפי חודש העדכון האחרון, {len(vint):,} חודשים.",
        },
        "flags": {
            "shape": len(shape_pts) >= 3,
            "vintage": len(vint) >= 1,
            "lines": lines_named >= 1,
        },
    }
