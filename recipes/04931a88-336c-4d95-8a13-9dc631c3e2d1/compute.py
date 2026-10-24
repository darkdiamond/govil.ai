"""מפעלים — Ministry of Environmental Protection register of factories and
environmental sites (one row per site).

Activity ("מהות האתר") is "<code> <description>"; the code's first two digits
are the industry division. Division labels come from the data itself (the
description of the 2-digit-coded rows), so a renamed or new division labels
itself. Rows with no code (e.g. "קרקעות מזוהמות") are their own group.
Coordinates are ITM; about half the sites have "(חסר)" instead. Rows in the
ministry's test district are excluded and disclosed.

Site names may be sole proprietors' business names, so the page never lists
individual sites — only aggregates (the shell's data table and the map
popups show the source rows as published).
"""
import pandas as pd

TEST_DISTRICT_MARK = "בדיקות"
MISSING = "(חסר)"
TOP_DIVISIONS = 25
TOP_ACTIVITIES = 20
TOP_AUTHORITIES = 15
HEAT_DIVISIONS = 10
PROFILE_AUTHORITIES = 12   # rows of the authority × activity profile
PROFILE_GROUPS = 6         # stacked groups in the profile (rest = "other")
COVERAGE_GROUPS = 12       # groups on the map-coverage chart
UNCODED_MIN = 50          # an uncoded description this common gets its own group
CONCENTRATION_SHARE = 0.4  # "X% of division D is in one settlement" threshold
ITM_X = (100_000, 300_000)
ITM_Y = (350_000, 800_000)


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    out = df.copy()
    for c in ["Machoz", "Yeshuv", "Rashut_Mekomit", "mehute_Atar", "Nekudat_Tsiun_X"]:
        out[c] = out[c].str.strip()
    test = out["Machoz"].str.contains(TEST_DISTRICT_MARK, regex=False)
    n_test = int(test.sum())
    out = out[~test].copy()
    m = out["mehute_Atar"].str.extract(r"^(\d+)\s*(.*)$")
    out["code"], out["desc"] = m[0], m[1].str.strip()
    out["desc"] = out["desc"].where(out["code"].notna(), out["mehute_Atar"])
    out["div"] = out["code"].str[:2]
    out["district"] = out["Machoz"].replace("", "לא צוין")
    out["settlement"] = out["Yeshuv"].replace("", "לא צוין")
    out["authority"] = out["Rashut_Mekomit"].replace("", "לא צוין")
    x = pd.to_numeric(out["Nekudat_Tsiun_X"], errors="coerce")
    y = pd.to_numeric(out["Nekudat_Tsiun_Y"], errors="coerce")
    out["has_xy"] = x.notna() & y.notna()
    # ITM (EPSG:2039) extent of Israel; numeric points outside it are typos
    # that GovMap still plots (it maps every row) — disclosed on the map.
    out["bad_xy"] = out["has_xy"] & ~(x.between(*ITM_X) & y.between(*ITM_Y))
    return out.reset_index(drop=True), n_test


def _division_labels(df):
    """Division code → name, from rows coded at exactly two digits."""
    two = df[df["code"].str.len() == 2]
    labels = {}
    for code, g in two.groupby("div"):
        labels[code] = _ranked(g["desc"]).index[0]
    return labels


def _group(df, labels):
    """Display group per row: division name, a common uncoded description,
    or 'לא מסווג'."""
    uncoded = _ranked(df.loc[df["code"].isna(), "desc"])
    own = {d for d, n in uncoded.items() if n >= UNCODED_MIN and d != MISSING}
    def g(row_div, row_desc, coded):
        if coded:
            return labels.get(row_div, f"ענף {row_div}")
        return row_desc if row_desc in own else "לא מסווג"
    return [g(dv, ds, c) for dv, ds, c in zip(df["div"], df["desc"], df["code"].notna())]


def insight_top_group(df):
    groups = _ranked(df["group"])
    name, v = groups.index[0], int(groups.iloc[0])
    return (f"הקבוצה הגדולה ביותר במאגר היא {name} — {_int(v)} אתרים "
            f"({_pct(v / len(df), 1)}), ואחריה {groups.index[1]} ({_int(groups.iloc[1])}).")


def insight_contaminated(df):
    g = df[df["desc"].str.contains("קרקעות מזוהמות", regex=False)]
    if len(g) < UNCODED_MIN:
        return None
    d = _ranked(g["district"])
    return (f"במאגר {_int(len(g))} אתרים של קרקעות מזוהמות; המספר הגדול ביותר במחוז "
            f"{d.index[0]} ({_int(d.iloc[0])}).")


def insight_concentration(df):
    """The most concentrated of the 5 largest coded divisions."""
    best = None
    for name in _ranked(df.loc[df["code"].notna(), "group"]).index[:5]:
        g = df[df["group"] == name]
        s = _ranked(g["settlement"])
        share = s.iloc[0] / len(g)
        if share >= CONCENTRATION_SHARE and (best is None or share > best[2]):
            best = (name, s.index[0], share, len(g))
    if best is None:
        return None
    name, place, share, n = best
    return (f"{_pct(share)} מ-{_int(n)} האתרים בתחום {name} נמצאים ביישוב אחד — {place}.")


def insight_districts(df):
    d = _ranked(df["district"])
    if len(d) < 2:
        return None
    gap = (d.iloc[0] - d.iloc[1]) / len(df)
    if gap < 0.02:
        return (f"מחוזות {d.index[0]} ו{d.index[1]} מובילים כמעט בשוויון — "
                f"{_int(d.iloc[0])} ו-{_int(d.iloc[1])} אתרים.")
    return f"מחוז {d.index[0]} מוביל עם {_int(d.iloc[0])} אתרים ({_pct(d.iloc[0] / len(df))})."


def insight_coords(df):
    missing = 1 - df["has_xy"].mean()
    if missing < 0.05:
        return None
    by = df.groupby("district")["has_xy"].mean().sort_index().sort_values(kind="stable")
    return (f"ל-{_pct(missing)} מהאתרים אין נקודת ציון במאגר, ולכן הם אינם מופיעים במפה; "
            f"הכיסוי הנמוך ביותר במחוז {by.index[0]} ({_pct(by.iloc[0])} עם מיקום).")


def insight_authority(df):
    a = _ranked(df["authority"])
    share = a.iloc[0] / len(df)
    return (f"{a.index[0]} היא הרשות המקומית עם הכי הרבה אתרים — {_int(a.iloc[0])} "
            f"({_pct(share, 1)}), מתוך {_int(a.size)} רשויות.")


def insight_mapped_gap(df):
    """Largest gap in map coverage between activity groups (top groups,
    ≥30 points apart)."""
    top = list(_ranked(df["group"]).index[:COVERAGE_GROUPS])
    share = df.groupby("group")["has_xy"].mean()
    s = sorted(top, key=lambda g: (share[g], g))
    lo, hi = s[0], s[-1]
    if share[hi] - share[lo] < 0.3:
        return None
    return (f"הכיסוי במפה תלוי בסוג האתר: ל-{_pct(share[hi])} מאתרי {hi} יש נקודת ציון, "
            f"לעומת {_pct(share[lo])} בלבד מאתרי {lo}.")


def compute(frames):
    df, n_test = _prepare(frames["sites"])
    labels = _division_labels(df)
    df["group"] = _group(df, labels)
    total = len(df)

    districts = _ranked(df["district"])
    by_d_xy = df.groupby(["district", "has_xy"]).size()
    districts_chart = {
        "names": list(districts.index),
        "with_xy": [int(by_d_xy.get((d, True), 0)) for d in districts.index],
        "without_xy": [int(by_d_xy.get((d, False), 0)) for d in districts.index],
    }

    groups = _ranked(df["group"])
    g_top = groups.head(TOP_DIVISIONS)
    g_rest = int(groups.iloc[TOP_DIVISIONS:].sum())
    treemap = [{"name": n, "value": int(v)} for n, v in g_top.items()]
    if g_rest:
        treemap.append({"name": "תחומים אחרים", "value": g_rest})

    acts = _ranked(df["desc"].where(df["desc"] != MISSING, "לא צוין"))
    acts_chart = {"names": list(acts.index[:TOP_ACTIVITIES]),
                  "values": [int(v) for v in acts.iloc[:TOP_ACTIVITIES]]}

    auth = _ranked(df["authority"])
    auth_chart = {"names": list(auth.index[:TOP_AUTHORITIES]),
                  "values": [int(v) for v in auth.iloc[:TOP_AUTHORITIES]]}

    heat_groups = list(groups.index[:HEAT_DIVISIONS])
    by_dg = df.groupby(["district", "group"]).size()
    cells = []
    for xi, d in enumerate(districts.index):
        dt = int(districts[d])
        for yi, g in enumerate(heat_groups):
            v = int(by_dg.get((d, g), 0))
            cells.append([xi, yi, round(v / dt * 100, 1) if dt else 0, v])
    heat = {"districts": list(districts.index), "groups": heat_groups, "cells": cells,
            "max": max((c[2] for c in cells), default=0)}

    t_groups = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
                for n, v in groups.head(TOP_DIVISIONS).items()]

    def rows(series, limit):
        return [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
                for n, v in series.head(limit).items()]

    t_acts = rows(acts, TOP_ACTIVITIES)
    t_auth = rows(auth, TOP_AUTHORITIES)
    t_districts = [{"name": d, "total": _int(districts[d]),
                    "with_xy": _int(by_d_xy.get((d, True), 0)),
                    "without_xy": _int(by_d_xy.get((d, False), 0))} for d in districts.index]

    # What kind of activity sits in each of the largest authorities.
    prof_auth = list(auth.index[:PROFILE_AUTHORITIES])
    prof_groups = list(groups.index[:PROFILE_GROUPS])
    by_ag = df.groupby(["authority", "group"]).size()
    profile = {
        "names": prof_auth,
        "series": [{"name": g, "data": [int(by_ag.get((a, g), 0)) for a in prof_auth]}
                   for g in prof_groups]
                  + [{"name": "תחומים אחרים",
                      "data": [int(auth[a]) - sum(int(by_ag.get((a, g), 0)) for g in prof_groups)
                               for a in prof_auth]}],
    }
    t_profile = {"cols": [s["name"] for s in profile["series"]],
                 "rows": [{"name": a, "vals": [_int(s["data"][i]) for s in profile["series"]]}
                          for i, a in enumerate(prof_auth)]}

    # Map coverage by activity group: which kinds of sites lack a location.
    cov_groups = list(groups.index[:COVERAGE_GROUPS])
    cov_share = df.groupby("group")["has_xy"].mean()
    mapped_chart = {"names": cov_groups,
                    "values": [round(float(cov_share[g]) * 100, 1) for g in cov_groups]}
    t_mapped = [{"name": g, "count": _int(groups[g]), "share": f"{cov_share[g] * 100:.1f}"}
                for g in cov_groups]

    rules = [
        ("top_group", insight_top_group(df)),
        ("districts", insight_districts(df)),
        ("contaminated", insight_contaminated(df)),
        ("concentration", insight_concentration(df)),
        ("authority", insight_authority(df)),
        ("coords", insight_coords(df)),
        ("mapped_gap", insight_mapped_gap(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    with_xy = int(df["has_xy"].sum())
    n_bad = int(df["bad_xy"].sum())
    kpis = {
        "total": {"value": total, "display": _int(total)},
        "settlements": {"value": int(df["settlement"].nunique()), "display": _int(df["settlement"].nunique())},
        "groups": {"value": int(groups.size), "display": _int(groups.size)},
        "mapped": {"value": with_xy / total if total else 0, "display": _pct(with_xy / total if total else 0)},
    }

    test_note = f" לא נכללו {_int(n_test)} רשומות של מחוז הבדיקות." if n_test else ""
    labels_out = {
        "lede": (f"מרשם המפעלים והאתרים הסביבתיים של המשרד להגנת הסביבה: {_int(total)} אתרים "
                 f"ב-{_int(df['settlement'].nunique())} יישובים ו-{_int(auth.size)} רשויות מקומיות, "
                 f"לפי מהות הפעילות, מחוז ומיקום.{test_note}"),
        "map_note": (f"{_int(with_xy)} אתרים ({_pct(with_xy / total if total else 0)}) מופיעים במפה; "
                     f"לשאר אין נקודת ציון במאגר. לחצו על אשכול להתקרבות."
                     + ("" if not n_bad else
                        " לאתר אחד רשומה נקודת ציון שגויה מחוץ לישראל, והוא מופיע במפה במקום הרשום."
                        if n_bad == 1 else
                        f" ל-{_int(n_bad)} אתרים רשומה נקודת ציון שגויה מחוץ לישראל, והם מופיעים "
                        f"במפה במקום הרשום.")),
        "districts_aria": "תרשים עמודות מוערמות: מספר האתרים לפי מחוז, עם מיקום ובלי מיקום.",
        "treemap_aria": f"מפת שטחים: מספר האתרים לפי תחום פעילות, {len(treemap)} תחומים.",
        "treemap_note": (f"תחומי פעילות לפי שתי הספרות הראשונות של קוד הפעילות; {TOP_DIVISIONS} "
                         f"התחומים הגדולים, והשאר מקובצים."),
        "acts_aria": f"תרשים עמודות אופקי: {len(acts_chart['names'])} סוגי הפעילות הנפוצים ביותר.",
        "auth_aria": f"תרשים עמודות אופקי: {len(auth_chart['names'])} הרשויות המקומיות עם הכי הרבה אתרים.",
        "heat_aria": f"מפת חום: שיעור כל אחד מ-{len(heat_groups)} התחומים הגדולים מתוך האתרים בכל מחוז.",
        "groups_caption": f"{TOP_DIVISIONS} תחומי הפעילות הגדולים לפי מספר אתרים.",
        "acts_caption": f"{len(t_acts)} סוגי הפעילות הנפוצים ביותר.",
        "auth_caption": f"{len(t_auth)} הרשויות המקומיות עם הכי הרבה אתרים.",
        "districts_caption": "מספר האתרים בכל מחוז, עם נקודת ציון ובלי.",
        "profile_aria": (f"תרשים עמודות אופקי מוערם: תמהיל הפעילות ב-{len(prof_auth)} הרשויות "
                         f"המקומיות עם הכי הרבה אתרים, לפי {len(prof_groups)} התחומים הגדולים."),
        "profile_caption": (f"מספר האתרים בכל אחת מ-{len(prof_auth)} הרשויות הגדולות לפי "
                            f"תחום פעילות."),
        "mapped_aria": (f"תרשים עמודות אופקי: שיעור האתרים עם נקודת ציון בכל אחד מ-"
                        f"{len(cov_groups)} התחומים הגדולים."),
        "mapped_caption": "שיעור האתרים עם נקודת ציון לפי תחום פעילות (באחוזים).",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} מפעלים ואתרים סביבתיים בישראל לפי תחום פעילות, מחוז, "
                           f"יישוב ורשות מקומית, כולל מפה של האתרים עם נקודת ציון."),
            "dataset_kind": "map",
            "suggested_tags": ["מפעלים", "הגנת הסביבה", "תעשייה", "קרקעות מזוהמות"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "districts": districts_chart,
            "treemap": treemap,
            "acts": acts_chart,
            "auth": auth_chart,
            "heat": heat,
            "profile": profile,
            "mapped": mapped_chart,
        },
        "tables": {"groups": t_groups, "acts": t_acts, "auth": t_auth,
                   "districts": t_districts, "profile": t_profile, "mapped": t_mapped},
        "insights": insights,
        "labels": labels_out,
    }
