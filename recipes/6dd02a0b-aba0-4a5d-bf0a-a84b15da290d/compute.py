"""שיוך ישובים לתחנות המשטרה: which police station, area (מרחב) and district
(מחוז) is responsible for each locality (Israel Police).

One row per locality, keyed by the CBS locality code (סמל). A city split
between several stations appears once as a parent row with no station and
once per station ("ירושלים (תחנת שלם)"), all sharing the city's code. So:

* a locality = a distinct code (name when the code is blank);
* an assignment = a row, minus the parent row of a split city (a row with no
  station whose code also has rows with a station);
* a locality with no station at all (the Bedouin tribes of מרחב רותם, as of
  2026-10) is "without a listed station" and reported as such.

Every number and sentence on the page is computed here.
"""
import re

import pandas as pd
from govlib import fmt, frame

NAME = "שם יישוב"
CODE = "סמל"
STATION = "שם תחנה"
AREA = "שם מרחב"
DISTRICT = "שם מחוז"

TOP_STATIONS = 15
TOP_AREAS = 20
BIG = 30
NO_STATION = "ללא תחנה משויכת"
SIZE_BINS = [(1, 1, "יישוב אחד"), (2, 5, "2-5"), (6, 10, "6-10"),
             (11, 20, "11-20"), (21, 40, "21-40"), (41, None, "41 ומעלה")]
SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")


def _load(df):
    d = pd.DataFrame({
        "name": frame.clean_series(df[NAME]),
        "code": frame.clean_series(df[CODE]),
        "station": frame.clean_series(df[STATION]),
        "area": frame.clean_series(df[AREA]),
        "district": frame.clean_series(df[DISTRICT]),
    })
    d = d[d["name"] != ""].copy()
    d["key"] = d["code"].where(d["code"] != "", "#" + d["name"])
    d = d.drop_duplicates().sort_values(
        ["key", "station", "area", "district", "name"], kind="stable").reset_index(drop=True)
    has_station = d[d["station"] != ""].groupby("key").size()
    d["split_parent"] = (d["station"] == "") & d["key"].isin(has_station.index)
    return d


def _ranked_counts(df, col, key="key"):
    s = df.groupby(col)[key].nunique()
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _size_bin(n):
    for lo, hi, label in SIZE_BINS:
        if n >= lo and (hi is None or n <= hi):
            return label
    return SIZE_BINS[-1][2]


def _dec(v):
    """One decimal, without a trailing '.0'."""
    return fmt.num_he(v, 1).removesuffix(".0")


def _city_name(rows):
    parents = rows[rows["station"] == ""]["name"]
    if len(parents):
        return min(parents)
    return min(SUFFIX.sub("", n) for n in rows["name"])


def compute(frames):
    d = _load(frames["main"])
    n_loc = int(d["key"].nunique())
    a = d[~d["split_parent"]]                       # assignments
    st = a[a["station"] != ""]
    n_assign = len(a)

    # ---- stations -------------------------------------------------------
    st_counts = _ranked_counts(st, "station")
    n_stations = len(st_counts)
    st_area = (st.groupby("station")["area"]
               .agg(lambda s: fmt.join_he(sorted({v for v in s if v}))))
    st_district = (st.groupby("station")["district"]
                   .agg(lambda s: fmt.join_he(sorted({v for v in s if v}))))
    st_areas_n = st[st["area"] != ""].groupby("station")["area"].nunique()
    multi_area = sorted(st_areas_n[st_areas_n > 1].index)
    median_st = float(st_counts.median()) if n_stations else 0.0

    # ---- unassigned -----------------------------------------------------
    with_station = set(st["key"])
    unassigned = a[(a["station"] == "") & ~a["key"].isin(with_station)].drop_duplicates("key")
    n_unassigned = len(unassigned)
    un_by_area = _ranked_counts(unassigned.assign(area=unassigned["area"].replace("", "לא צוין")), "area")

    # ---- districts / areas ----------------------------------------------
    dist_loc = _ranked_counts(d[d["district"] != ""], "district")
    dist_st = st[st["district"] != ""].groupby("district")["station"].nunique()
    dist_area = a[(a["district"] != "") & (a["area"] != "")].groupby("district")["area"].nunique()
    dist_assign = st[st["district"] != ""].groupby("district").size()
    districts = list(dist_loc.index)
    n_districts = len(districts)
    ratio = {k: float(dist_assign.get(k, 0)) / int(dist_st[k])
             for k in districts if int(dist_st.get(k, 0)) > 0}

    area_counts = _ranked_counts(a[a["area"] != ""], "area")
    n_areas = len(area_counts)
    area_district = (a[a["area"] != ""].groupby("area")["district"]
                     .agg(lambda s: fmt.join_he(sorted({v for v in s if v}))))
    area_st = st[st["area"] != ""].groupby("area")["station"].nunique()

    # ---- split cities ---------------------------------------------------
    st_per_key = st.groupby("key")["station"].nunique()
    split_keys = sorted(st_per_key[st_per_key > 1].index)
    split = []
    for k in split_keys:
        rows = d[d["key"] == k]
        srows = rows[rows["station"] != ""].sort_values(["station", "area"], kind="stable")
        parts = [f"{r.station} ({r.area})" if r.area else r.station
                 for r in srows.drop_duplicates("station").itertuples()]
        split.append({"name": _city_name(rows), "n": int(st_per_key[k]), "parts": parts,
                      "areas": int(srows.loc[srows["area"] != "", "area"].nunique())})
    split.sort(key=lambda x: (-x["n"], x["name"]))

    # ---- size distribution ----------------------------------------------
    bins = {label: 0 for _, _, label in SIZE_BINS}
    for v in st_counts:
        bins[_size_bin(int(v))] += 1
    single = int(bins[SIZE_BINS[0][2]])

    # ---- treemap: district > area > station ------------------------------
    tree = []
    for dist in districts:
        sub = a[a["district"] == dist]
        children = []
        areas = _ranked_counts(sub.assign(area=sub["area"].replace("", "לא צוין")), "area")
        for ar in areas.index:
            sa = sub[sub["area"].replace("", "לא צוין") == ar]
            leaves = []
            sc = _ranked_counts(sa.assign(station=sa["station"].replace("", NO_STATION)), "station")
            for s_name, v in sc.items():
                leaves.append({"name": s_name, "value": int(v)})
            children.append({"name": ar, "children": leaves})
        tree.append({"name": dist, "children": children})

    # ---- directory: per district, station -> localities -----------------
    directory = []
    for dist in districts:
        sub = st[st["district"] == dist]
        rows = []
        sc = _ranked_counts(sub, "station")
        for s_name in sorted(sc.index, key=lambda s: (-int(sc[s]), s)):
            ss = sub[sub["station"] == s_name]
            names = sorted(set(ss["name"]))
            rows.append([s_name, fmt.join_he(sorted({v for v in ss["area"] if v})) or "–",
                         fmt.int_he(len(names)), ", ".join(names)])
        directory.append({"district": dist, "stations": len(sc),
                          "localities": fmt.int_he(dist_loc[dist]), "rows": rows})

    # ---- charts -----------------------------------------------------------
    top_st = st_counts.iloc[:TOP_STATIONS]
    charts = {
        "district": {
            "names": districts,
            "loc": [int(dist_loc[k]) for k in districts],
            "stations": [int(dist_st.get(k, 0)) for k in districts],
        },
        "ratio": {
            "names": sorted(ratio, key=lambda k: (-ratio[k], k)),
        },
        "areas": {},
        "stations": {
            "names": [str(k) for k in top_st.index],
            "values": [int(v) for v in top_st],
            "area": [st_area.get(k, "") for k in top_st.index],
            "district": [st_district.get(k, "") for k in top_st.index],
        },
        "sizes": {"names": [b[2] for b in SIZE_BINS], "values": [int(bins[b[2]]) for b in SIZE_BINS]},
        "tree": tree,
    }
    charts["ratio"]["values"] = [round(ratio[k], 1) for k in charts["ratio"]["names"]]
    ar_labels, ar_values = frame.top_other(area_counts, TOP_AREAS)
    charts["areas"] = {"names": ar_labels, "values": ar_values,
                       "district": [area_district.get(k, "") for k in ar_labels]}

    # ---- KPIs -----------------------------------------------------------
    kpis = {
        "localities": {"value": n_loc, "display": fmt.int_he(n_loc), "tone": "brand"},
        "stations": {"value": n_stations, "display": fmt.int_he(n_stations), "tone": "brand"},
        "areas": {"value": n_areas, "display": fmt.int_he(n_areas), "tone": "brand"},
        "districts": {"value": n_districts, "display": fmt.int_he(n_districts), "tone": "brand"},
        "split": {"value": len(split), "display": fmt.int_he(len(split)), "tone": "info"},
        "unassigned": {"value": n_unassigned, "display": fmt.int_he(n_unassigned),
                       "tone": "warn" if n_unassigned else "ok"},
    }

    # ---- insights -------------------------------------------------------
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    def ins_district():
        if n_districts < 2:
            return None
        k = districts[0]
        share = dist_loc[k] / n_loc
        if share < 0.2:
            return None
        return (f"מחוז {k} אחראי על המספר הגדול ביותר של יישובים: {fmt.int_he(dist_loc[k])} "
                f"מתוך {fmt.int_he(n_loc)} ({fmt.pct(share)}), באמצעות {fmt.int_he(dist_st.get(k, 0))} תחנות. "
                f"מחוז {districts[-1]} אחראי על {fmt.int_he(dist_loc[districts[-1]])} יישובים בלבד.")

    def ins_station():
        if n_stations < 3:
            return None
        k = st_counts.index[0]
        v = int(st_counts.iloc[0])
        if v < 2 * median_st:
            return None
        return (f"{k} אחראית על {fmt.int_he(v)} יישובים, יותר מכל תחנה אחרת, "
                f"לעומת חציון של {_dec(median_st)} יישובים לתחנה.")

    def ins_ratio():
        if len(ratio) < 2:
            return None
        names = charts["ratio"]["names"]
        hi, lo = names[0], names[-1]
        if ratio[lo] <= 0 or ratio[hi] / ratio[lo] < 2:
            return None
        return (f"בממוצע כל תחנה במחוז {hi} אחראית על {_dec(ratio[hi])} יישובים, "
                f"פי {_dec(ratio[hi] / ratio[lo])} ממחוז {lo} ({_dec(ratio[lo])} יישובים לתחנה).")

    def ins_split():
        if not split:
            return None
        top = split[0]
        if len(split) == 1:
            return f"{top['name']} היא היישוב היחיד המחולק בין כמה תחנות: {fmt.int_he(top['n'])} תחנות."
        return (f"{fmt.int_he(len(split))} יישובים מחולקים בין כמה תחנות משטרה. "
                f"{top['name']} מחולקת בין המספר הגדול ביותר: {fmt.int_he(top['n'])} תחנות"
                + (f" ב-{fmt.int_he(top['areas'])} מרחבים" if top["areas"] > 1 else "") + ".")

    def ins_unassigned():
        if not n_unassigned:
            return None
        k = un_by_area.index[0]
        v = int(un_by_area.iloc[0])
        tribes = int(unassigned["name"].str.contains("(שבט)", regex=False).sum())
        txt = f"{fmt.int_he(n_unassigned)} יישובים מופיעים בטבלה ללא תחנה משויכת"
        if len(un_by_area) == 1:
            txt += f", כולם ב{k}"
        else:
            txt += f", {fmt.int_he(v)} מהם ב{k}"
        if tribes == n_unassigned:
            txt += ", וכולם שבטים בדואיים"
        elif tribes >= n_unassigned / 2:
            txt += f", ו-{fmt.int_he(tribes)} מהם שבטים בדואיים"
        return txt + "."

    def ins_single():
        big = int((st_counts >= BIG).sum())
        if n_stations < 5 or single < 2 or big < 2:
            return None
        return (f"{fmt.int_he(single)} תחנות אחראיות על יישוב אחד בלבד (או על חלק מעיר), "
                f"ו-{fmt.int_he(big)} תחנות אחראיות על {fmt.int_he(BIG)} יישובים ויותר כל אחת.")

    def ins_multi_area():
        if not multi_area:
            return None
        k = multi_area[0]
        return (f"{k} רשומה תחת יותר ממרחב אחד ({st_area[k]})"
                + (f", וכך עוד {fmt.int_he(len(multi_area) - 1)} תחנות" if len(multi_area) > 1 else "")
                + ".")

    add("district", ins_district())
    add("station", ins_station())
    add("ratio", ins_ratio())
    add("split", ins_split())
    add("unassigned", ins_unassigned())
    add("single", ins_single())
    add("multi_area", ins_multi_area())

    # ---- tables ---------------------------------------------------------
    tables = {
        "district": [[k, fmt.int_he(dist_loc[k]), fmt.int_he(dist_area.get(k, 0)),
                      fmt.int_he(dist_st.get(k, 0)),
                      fmt.num_he(ratio[k]) if k in ratio else "–"] for k in districts],
        "areas": [[k, area_district.get(k, ""), fmt.int_he(area_st.get(k, 0)),
                   fmt.int_he(area_counts[k])] for k in area_counts.index],
        "stations": [[str(i + 1), charts["stations"]["names"][i], charts["stations"]["area"][i] or "–",
                      fmt.int_he(charts["stations"]["values"][i])] for i in range(len(top_st))],
        "sizes": [[n, fmt.int_he(v)] for n, v in zip(charts["sizes"]["names"], charts["sizes"]["values"])],
        "split": [[x["name"], fmt.int_he(x["n"]), ", ".join(x["parts"])] for x in split],
        "unassigned": [[k, fmt.int_he(v)] for k, v in un_by_area.items()],
    }
    unassigned_names = ", ".join(sorted(unassigned["name"]))

    # ---- labels ---------------------------------------------------------
    top_d = districts[0] if districts else ""
    top_s = st_counts.index[0] if n_stations else ""
    top_a = area_counts.index[0] if n_areas else ""
    labels = {
        "localities_kpi": "יישובים בטבלה (לפי סמל יישוב)",
        "unassigned_kpi": "יישובים ללא תחנה משויכת",
        "district_lede": (f"מספר היישובים ומספר התחנות בכל אחד מ-{fmt.int_he(n_districts)} מחוזות המשטרה. "
                          f"מחוז {top_d} מוביל עם {fmt.int_he(dist_loc.get(top_d, 0))} יישובים."),
        "district_aria": (f"גרף עמודות אופקי: יישובים ותחנות לפי מחוז משטרה. "
                          f"מחוז {top_d} מוביל עם {fmt.int_he(dist_loc.get(top_d, 0))} יישובים."),
        "ratio_lede": ("ממוצע השיוכים לתחנה בכל מחוז: כמה יישובים (או חלקי ערים) נמצאים בגזרת "
                       "האחריות של תחנה אחת. מחוזות כפריים מכסים יישובים רבים בכל תחנה."),
        "ratio_aria": ("גרף עמודות: ממוצע יישובים לתחנה לפי מחוז. "
                       + (f"הגבוה ביותר במחוז {charts['ratio']['names'][0]}: "
                          f"{fmt.num_he(charts['ratio']['values'][0])} יישובים לתחנה." if ratio else "")),
        "tree_lede": (f"מבנה הפיקוד של משטרת ישראל כפי שהוא משתקף בטבלה: {fmt.int_he(n_districts)} מחוזות, "
                      f"{fmt.int_he(n_areas)} מרחבים ו-{fmt.int_he(n_stations)} תחנות. גודל כל ריבוע הוא מספר "
                      "היישובים בגזרה. לחיצה על מרחב מציגה את התחנות שבו."),
        "tree_aria": (f"מפת עץ: מחוזות, מרחבים ותחנות המשטרה לפי מספר היישובים. "
                      f"המחוז הגדול ביותר: {top_d}."),
        "areas_lede": (f"מספר היישובים בגזרת כל מרחב. {top_a} הוא המרחב הגדול ביותר, "
                       f"עם {fmt.int_he(area_counts.get(top_a, 0))} יישובים. "
                       "עיר המחולקת בין מרחבים נספרת בכל אחד מהם."),
        "areas_aria": (f"גרף עמודות אופקי: יישובים לפי מרחב משטרה. "
                       f"{top_a} מוביל עם {fmt.int_he(area_counts.get(top_a, 0))} יישובים."),
        "stations_lede": (f"{fmt.int_he(len(top_st))} התחנות שבגזרתן הכי הרבה יישובים. "
                          f"{top_s} מובילה עם {fmt.int_he(st_counts.iloc[0]) if n_stations else ''} יישובים."),
        "stations_aria": (f"גרף עמודות אופקי: תחנות המשטרה עם הכי הרבה יישובים בגזרתן. "
                          f"{top_s} מובילה עם {fmt.int_he(st_counts.iloc[0]) if n_stations else ''} יישובים."),
        "stations_title": f"{fmt.int_he(len(top_st))} התחנות האחראיות על הכי הרבה יישובים",
        "sizes_lede": (f"כמה יישובים יש בגזרה של כל אחת מ-{fmt.int_he(n_stations)} התחנות. "
                       f"החציון: {_dec(median_st)} יישובים לתחנה."),
        "sizes_aria": (f"היסטוגרמה: תחנות לפי מספר היישובים בגזרתן. "
                       f"{fmt.int_he(single)} תחנות אחראיות על יישוב אחד."),
        "split_lede": (f"{fmt.int_he(len(split))} יישובים מחולקים בין כמה תחנות. כל חלק מופיע בטבלת המקור "
                       "כשורה נפרדת, עם שם התחנה בסוגריים."),
        "unassigned_lede": (f"{fmt.int_he(n_unassigned)} יישובים מופיעים בטבלה עם מרחב ומחוז אך ללא שם תחנה."),
        "directory_lede": (f"כל {fmt.int_he(n_stations)} התחנות לפי מחוז, עם היישובים שבגזרת כל תחנה. "
                           "עיר המחולקת בין תחנות מופיעה תחת כל אחת מהן."),
        "lookup_note": "חיפוש חי בכל רשומות המאגר: שם יישוב, סמל יישוב, שם תחנה, מרחב ומחוז",
    }

    summary = (f"שיוך {fmt.int_he(n_loc)} יישובים לתחנות משטרת ישראל: לכל יישוב, התחנה האחראית עליו, "
               f"המרחב והמחוז. {fmt.int_he(n_stations)} תחנות ב-{fmt.int_he(n_areas)} מרחבים "
               f"ו-{fmt.int_he(n_districts)} מחוזות"
               + (f"; {fmt.int_he(len(split))} יישובים מחולקים בין כמה תחנות." if split else "."))
    desc = (f"איזו תחנת משטרה אחראית על היישוב שלך? חיפוש לפי שם יישוב בין {fmt.int_he(n_loc)} יישובים, "
            f"{fmt.int_he(n_stations)} תחנות ו-{fmt.int_he(n_areas)} מרחבים של משטרת ישראל.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל ויהודה ושומרון",
            "seo": {
                "title": "איזו תחנת משטרה אחראית על היישוב? שיוך יישובים",
                "description": desc,
                "name": "שיוך יישובים לתחנות המשטרה",
                "alternate_names": ["שיוך ישובים לתחנות המשטרה", "תחנת משטרה לפי יישוב",
                                    "גזרות האחריות של תחנות המשטרה", "תחנות משטרה לפי יישוב ומרחב"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "tables": tables,
        "directory": directory,
        "unassigned_names": unassigned_names,
        "flags": {"split": bool(split), "unassigned": bool(n_unassigned), "ratio": len(ratio) >= 2},
        "labels": labels,
        "counts": {"assignments": n_assign},
    }
