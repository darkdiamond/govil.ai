"""Signalized junctions (צמתים מרומזרים), Ministry of Transport GIS layer.

One row per junction with a traffic light: ITM point (X/Y), district, city,
the street/road names that meet there ("40 / 3611", "הרצל / בן גוריון"), an
optional junction name, the national road body responsible (blank for the
municipal majority), a placement domain (DOMAIN) and a "new" flag (NEW).

The map is drawn live by GovMap from the datastore (ITM), so compute only
aggregates: districts, cities, long tail, national bodies, numbered roads,
junction-name kinds, and new junctions.
"""

import re

import pandas as pd

TOP_CITIES = 15
TOP_ROADS = 12
TOP_BODIES = 8
TREEMAP_CITIES = 6
NO_BODY = "ללא גורם ארצי"
NOT_STATED = "לא צוין"
CITY_BUCKETS = [(1, 1), (2, 5), (6, 10), (11, 25), (26, 50), (51, 100), (101, None)]
ROAD_RE = re.compile(r"^\d{1,4}$")
KIND_ORDER = ["צומת", "מחלף", "כניסה", "מספר צומת בלבד", "שם אחר"]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _ranked(series):
    """value_counts with a total, deterministic order (count desc, name asc)."""
    vc = series.value_counts()
    df = pd.DataFrame({"name": vc.index.astype(str), "count": vc.values.astype(int)})
    return df.sort_values(["count", "name"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def _clean(df):
    out = pd.DataFrame()
    for c in ["district", "CITY", "STREETROAD", "JUNCTION", "AUTHORITY", "DOMAIN", "NEW"]:
        out[c] = df[c].astype(str).str.strip()
    # CSV export doubles the gershayim: 'יו""ש' -> 'יו"ש'
    out["district"] = out["district"].str.replace('""', '"', regex=False)
    out.loc[out["district"] == "", "district"] = NOT_STATED
    out.loc[out["CITY"] == "", "CITY"] = NOT_STATED
    out.loc[out["DOMAIN"] == "", "DOMAIN"] = NOT_STATED
    out["body"] = out["AUTHORITY"].where(out["AUTHORITY"] != "", NO_BODY)
    out["new"] = out["NEW"].map(lambda v: v if v in ("כן", "לא") else NOT_STATED)
    return out


def _kind(name):
    if not name:
        return None
    if name.startswith("מספר צומת"):
        return "מספר צומת בלבד"
    first = name.split()[0].rstrip("-")
    if first == "צומת":
        return "צומת"
    if first in ("מחלף", "מחלפון"):
        return "מחלף"
    if first == "כניסה":
        return "כניסה"
    return "שם אחר"


def _roads(streetroad):
    toks = [t.strip() for t in streetroad.split("/")]
    return sorted({t for t in toks if ROAD_RE.match(t)}, key=lambda t: (int(t), t))


def compute(frames):
    raw = frames["junctions"]
    d = _clean(raw)
    n = len(d)

    # ---- districts x domain ------------------------------------------------
    dist = _ranked(d["district"])
    domains = _ranked(d["DOMAIN"])
    dom_names = domains["name"].tolist()
    ct = pd.crosstab(d["district"], d["DOMAIN"])
    district_series = [
        {"name": dn, "data": [int(ct.at[x, dn]) if dn in ct.columns else 0 for x in dist["name"]]}
        for dn in dom_names
    ]
    city_per_dist = d.groupby("district")["CITY"].nunique()
    dist_rows = []
    for _, r in dist.iterrows():
        cities = int(city_per_dist[r["name"]])
        dist_rows.append({
            "name": r["name"],
            "count": _int(r["count"]),
            "share": _pct(r["count"] / n),
            "cities": _int(cities),
            "per_city": f"{r['count'] / cities:.1f}",
            "by_domain": [_int(s["data"][len(dist_rows)]) for s in district_series],
        })

    # ---- cities -----------------------------------------------------------
    cities = _ranked(d["CITY"])
    n_cities = len(cities)
    top_c = cities.head(TOP_CITIES)
    top5_share = cities["count"].head(5).sum() / n if n else 0
    city_dist = d.drop_duplicates("CITY").set_index("CITY")["district"]
    cities_chart = {
        "names": top_c["name"].tolist(),
        "values": top_c["count"].astype(int).tolist(),
    }
    cities_rows = [
        {"rank": i + 1, "name": r["name"], "district": str(city_dist.get(r["name"], "")),
         "count": _int(r["count"]), "share": _pct(r["count"] / n)}
        for i, r in top_c.iterrows()
    ]

    # ---- long tail: cities by junction count -------------------------------
    bucket_labels, bucket_cities, bucket_junctions = [], [], []
    for lo, hi in CITY_BUCKETS:
        if hi is None:
            m = cities["count"] >= lo
            label = f"{lo}+"
        else:
            m = cities["count"].between(lo, hi)
            label = str(lo) if lo == hi else f"{lo}-{hi}"
        bucket_labels.append(label)
        bucket_cities.append(int(m.sum()))
        bucket_junctions.append(int(cities.loc[m, "count"].sum()))
    tail_rows = [
        {"label": bucket_labels[i], "cities": _int(bucket_cities[i]), "junctions": _int(bucket_junctions[i])}
        for i in range(len(bucket_labels))
    ]
    single = bucket_cities[0]

    # ---- treemap district -> top cities -----------------------------------
    treemap = []
    for dn in dist["name"]:
        sub = _ranked(d.loc[d["district"] == dn, "CITY"])
        kids = [{"name": r["name"], "value": int(r["count"])} for _, r in sub.head(TREEMAP_CITIES).iterrows()]
        rest = sub.iloc[TREEMAP_CITIES:]
        if len(rest):
            kids.append({"name": f"{len(rest)} יישובים נוספים", "value": int(rest["count"].sum())})
        treemap.append({"name": dn, "value": int(sub["count"].sum()), "children": kids})

    # ---- national road bodies ----------------------------------------------
    with_body = d[d["body"] != NO_BODY]
    n_body = len(with_body)
    bodies = _ranked(with_body["body"])
    top_b = bodies.head(TOP_BODIES)
    rest_b = int(bodies["count"].iloc[TOP_BODIES:].sum())
    bodies_names = top_b["name"].tolist() + (["אחר"] if rest_b else [])
    bodies_vals = top_b["count"].astype(int).tolist() + ([rest_b] if rest_b else [])
    bodies_rows = [
        {"name": bodies_names[i], "count": _int(bodies_vals[i]),
         "share": _pct(bodies_vals[i] / n_body) if n_body else "0.0%"}
        for i in range(len(bodies_names))
    ]

    # ---- numbered roads ----------------------------------------------------
    road_lists = d["STREETROAD"].map(_roads)
    on_road = int((road_lists.map(len) > 0).sum())
    exploded = road_lists.explode().dropna()
    roads = _ranked(exploded) if len(exploded) else pd.DataFrame({"name": [], "count": []})
    top_r = roads.head(TOP_ROADS)
    roads_chart = {
        "names": [f"כביש {x}" for x in top_r["name"]],
        "values": top_r["count"].astype(int).tolist(),
    }
    roads_rows = [{"name": f"כביש {r['name']}", "count": _int(r["count"])} for _, r in top_r.iterrows()]

    # ---- junction-name kinds -----------------------------------------------
    kinds = d["JUNCTION"].map(_kind)
    n_named = int(kinds.notna().sum())
    kc = kinds.dropna().value_counts()
    kind_names = [k for k in KIND_ORDER if k in kc.index] + sorted(k for k in kc.index if k not in KIND_ORDER)
    kind_vals = [int(kc[k]) for k in kind_names]
    kinds_rows = [
        {"name": kind_names[i], "count": _int(kind_vals[i]),
         "share": _pct(kind_vals[i] / n_named) if n_named else "0.0%"}
        for i in range(len(kind_names))
    ]

    # ---- new junctions ------------------------------------------------------
    n_new = int((d["new"] == "כן").sum())
    n_new_unknown = int((d["new"] == NOT_STATED).sum())
    new_by = d.groupby("district")["new"].apply(lambda s: int((s == "כן").sum()))
    unk_by = d.groupby("district")["new"].apply(lambda s: int((s == NOT_STATED).sum()))
    new_names = dist["name"].tolist()
    new_vals = [int(new_by[x]) for x in new_names]
    new_rows = []
    for i, x in enumerate(new_names):
        tot = int(dist.loc[dist["name"] == x, "count"].iloc[0])
        known = tot - int(unk_by[x])
        new_rows.append({
            "name": x, "count": _int(new_vals[i]),
            "share": _pct(new_vals[i] / known) if known else NOT_STATED,
        })
    new_order = sorted(range(len(new_names)), key=lambda i: (-new_vals[i], new_names[i]))
    new_chart = {"names": [new_names[i] for i in new_order], "values": [new_vals[i] for i in new_order]}
    new_rows = [new_rows[i] for i in new_order]

    # ---- KPIs ---------------------------------------------------------------
    kpis = {
        "total": {"value": n, "display": _int(n), "tone": "brand"},
        "cities": {"value": n_cities, "display": _int(n_cities), "tone": "brand"},
        "top5": {"value": round(top5_share, 4), "display": _pct(top5_share), "tone": "info"},
        "new": {"value": n_new, "display": _int(n_new), "tone": "ok" if n_new else "brand"},
    }

    # ---- insights -------------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_district():
        if len(dist) < 2:
            return None
        a, b = dist.iloc[0], dist.iloc[1]
        sa, sb = a["count"] / n, b["count"] / n
        if sa - sb < 0.01:
            return (f"מחוזות {a['name']} ו{b['name']} כמעט שקולים בראש הרשימה: {_int(a['count'])} ו-{_int(b['count'])} "
                    f"צמתים מרומזרים, יחד {_pct(sa + sb)} מכלל הצמתים במאגר.")
        return (f"מחוז {a['name']} מוביל עם {_int(a['count'])} צמתים מרומזרים ({_pct(sa)}), "
                f"ואחריו מחוז {b['name']} עם {_int(b['count'])} ({_pct(sb)}).")

    def ins_city():
        if n_cities < 5:
            return None
        c = cities.iloc[0]
        return (f"{c['name']} היא היישוב עם הכי הרבה צמתים מרומזרים: {_int(c['count'])} ({_pct(c['count'] / n)}). "
                f"חמשת היישובים המובילים מרכזים יחד {_pct(top5_share)} מהצמתים.")

    def ins_tail():
        if n_cities < 10 or single / n_cities < 0.1:
            return None
        return (f"ב-{_int(single)} מתוך {_int(n_cities)} היישובים ({_pct(single / n_cities, 0)}) יש צומת מרומזר אחד בלבד, "
                f"וב-{_int(bucket_cities[-1] + bucket_cities[-2])} יישובים יש יותר מחמישים.")

    def ins_density():
        rows = [(x, int(dist.loc[dist["name"] == x, "count"].iloc[0]) / int(city_per_dist[x]), int(city_per_dist[x]))
                for x in dist["name"] if x != NOT_STATED and int(dist.loc[dist["name"] == x, "count"].iloc[0]) >= 30]
        if len(rows) < 3:
            return None
        rows.sort(key=lambda r: (-r[1], r[0]))
        hi, lo = rows[0], rows[-1]
        if hi[1] < 2 * lo[1]:
            return None
        return (f"במחוז {hi[0]} הצמתים צפופים במיוחד: {hi[1]:.1f} צמתים בממוצע ליישוב ({_int(hi[2])} יישובים), "
                f"לעומת {lo[1]:.1f} במחוז {lo[0]} ({_int(lo[2])} יישובים).")

    def ins_body():
        if n_body < 20 or not len(bodies):
            return None
        b = bodies.iloc[0]
        share = b["count"] / n_body
        if share < 0.4:
            return None
        return (f"ל-{_int(n_body)} צמתים ({_pct(n_body / n)}) רשום גורם ארצי אחראי. {b['name']} אחראית על "
                f"{_int(b['count'])} מהם ({_pct(share)}). לשאר הצמתים לא רשום גורם ארצי.")

    def ins_domain():
        if n_body < 20 or len(domains) < 2:
            return None
        b = bodies.iloc[0]["name"]
        sub = d.loc[d["body"] == b, "DOMAIN"]
        top_dom = _ranked(sub).iloc[0]
        overall = domains.iloc[0]["name"]
        if top_dom["name"] == overall or top_dom["count"] / len(sub) < 0.6:
            return None
        return (f"תחום ההצבה הרשום שונה בין הגורמים: {_pct(top_dom['count'] / len(sub))} מהצמתים שבאחריות {b} "
                f"רשומים כ\"{top_dom['name']}\", אף שברוב המאגר ({_pct(domains.iloc[0]['count'] / n)}) התחום הוא \"{overall}\".")

    def ins_road():
        if len(roads) < 2 or on_road < 20:
            return None
        a, b = roads.iloc[0], roads.iloc[1]
        lead = f"כביש {a['name']} מוביל עם {_int(a['count'])} צמתים מרומזרים"
        if a["count"] == b["count"]:
            lead = f"כבישים {a['name']} ו-{b['name']} מובילים עם {_int(a['count'])} צמתים מרומזרים כל אחד"
        elif a["count"] - b["count"] <= 2:
            lead += f", כמעט כמו כביש {b['name']} ({_int(b['count'])})"
        return (f"ב-{_int(on_road)} צמתים ({_pct(on_road / n)}) נפגש לפחות כביש ממוספר אחד. {lead}.")

    def ins_new():
        if not n_new:
            return None
        i = new_order[0]
        txt = (f"{_int(n_new)} צמתים מסומנים במאגר כחדשים ({_pct(n_new / (n - n_new_unknown))} מהצמתים שהשדה מולא בהם); "
               f"הכי הרבה במחוז {new_names[i]} ({_int(new_vals[i])}).")
        if n_new_unknown:
            unk = [x for x in new_names if int(unk_by[x]) > 0]
            where = f" (מחוז {unk[0]})" if len(unk) == 1 else ""
            txt += f" ב-{_int(n_new_unknown)} צמתים{where} השדה ריק."
        return txt

    for iid, fn in [("district", ins_district), ("city", ins_city), ("tail", ins_tail), ("density", ins_density),
                    ("road", ins_road), ("body", ins_body), ("new", ins_new), ("domain", ins_domain)]:
        add(iid, fn())

    # ---- ledes / labels -------------------------------------------------------
    top_d = dist.iloc[0]
    top_city = cities.iloc[0] if n_cities else None
    labels = {
        "total_kpi": "צמתים מרומזרים במאגר",
        "cities_kpi": "יישובים ומועצות עם רמזור",
        "top5_kpi": "מהצמתים בחמשת היישובים המובילים",
        "new_kpi": "צמתים המסומנים כחדשים",
        "map_aria": (f"מפה אינטראקטיבית של {_int(n)} הצמתים המרומזרים בישראל. "
                     "גרסה נגישה: טבלאות ההתפלגות בעמוד ועיון בנתונים למטה."),
        "map_lede": (f"כל אחד מ-{_int(n)} הצמתים מסומן במפה לפי נקודת הציון שלו. "
                     "לחיצה על נקודה מציגה את שם הצומת, הרחובות או הכבישים הנפגשים, היישוב והגורם האחראי."),
        "districts_lede": (f"מחוז {top_d['name']} מוביל עם {_int(top_d['count'])} צמתים ({_pct(top_d['count'] / n)}). "
                           f"הצבעים מפרידים לפי תחום ההצבה כפי שנרשם במאגר."),
        "districts_aria": (f"גרף עמודות מוערמות: צמתים מרומזרים לפי מחוז ותחום הצבה. "
                           f"מחוז {top_d['name']} מוביל עם {_int(top_d['count'])} צמתים."),
        "cities_lede": (f"{_int(TOP_CITIES)} היישובים עם הכי הרבה צמתים מרומזרים מתוך {_int(n_cities)}. "
                        + (f"{top_city['name']} בראש עם {_int(top_city['count'])}." if top_city is not None else "")),
        "cities_aria": (f"גרף עמודות אופקי: {_int(TOP_CITIES)} היישובים המובילים במספר צמתים מרומזרים. "
                        + (f"{top_city['name']} בראש עם {_int(top_city['count'])}." if top_city is not None else "")),
        "cities_title": f"{_int(TOP_CITIES)} היישובים עם הכי הרבה רמזורים",
        "tail_lede": (f"כמה יישובים יש בכל קבוצת גודל. {_int(single)} יישובים מסתפקים בצומת מרומזר אחד, "
                      f"ו-{_int(bucket_cities[-1])} יישובים מחזיקים יותר ממאה צמתים כל אחד."),
        "tail_aria": (f"גרף עמודות: מספר היישובים לפי מספר הצמתים המרומזרים בהם. "
                      f"{_int(single)} יישובים עם צומת אחד בלבד."),
        "treemap_lede": (f"כל מחוז מחולק ל-{_int(TREEMAP_CITIES)} היישובים הגדולים בו, והשאר מקובצים יחד. "
                         "גודל המלבן הוא מספר הצמתים."),
        "treemap_aria": (f"מפת שטח: צמתים מרומזרים לפי מחוז ויישוב. "
                         f"מחוז {top_d['name']} הגדול ביותר עם {_int(top_d['count'])} צמתים."),
        "bodies_lede": (f"ל-{_int(n_body)} צמתים ({_pct(n_body / n) if n else '0.0%'}) רשום גורם ארצי אחראי. "
                        f"ל-{_int(n - n_body)} הצמתים האחרים לא רשום גורם כזה."),
        "bodies_aria": (f"גרף עמודות אופקי: צמתים מרומזרים לפי גורם ארצי אחראי. "
                        + (f"{bodies.iloc[0]['name']} מובילה עם {_int(bodies.iloc[0]['count'])}." if len(bodies) else "")),
        "roads_lede": (f"צמתים שבהם נפגש כביש ממוספר ({_int(on_road)} מתוך {_int(n)}). צומת של שני כבישים ממוספרים נספר בשניהם."
                       + (f" כביש {roads.iloc[0]['name']} בראש עם {_int(roads.iloc[0]['count'])}." if len(roads) else "")),
        "roads_aria": (f"גרף עמודות אופקי: {_int(len(top_r))} הכבישים הממוספרים עם הכי הרבה צמתים מרומזרים."
                       + (f" כביש {roads.iloc[0]['name']} בראש עם {_int(roads.iloc[0]['count'])}." if len(roads) else "")),
        "roads_title": f"{_int(len(top_r))} הכבישים עם הכי הרבה צמתים מרומזרים",
        "kinds_lede": (f"רק ל-{_int(n_named)} צמתים ({_pct(n_named / n) if n else '0.0%'}) רשום שם, בעיקר צמתים בכבישים ארציים. "
                       "המילה הראשונה בשם מסווגת אותו: צומת, מחלף, כניסה ליישוב או מספר צומת בלבד."),
        "kinds_aria": (f"גרף טבעת: סוגי הצמתים לפי שמם, מתוך {_int(n_named)} צמתים עם שם."
                       + (f" הסוג הנפוץ: {kind_names[kind_vals.index(max(kind_vals))]}." if kind_vals else "")),
        "new_lede": (f"{_int(n_new)} צמתים מסומנים במאגר כחדשים. האחוז בטבלה מחושב מתוך הצמתים שהשדה מולא בהם במחוז."
                     + (f" ב-{_int(n_new_unknown)} צמתים השדה ריק." if n_new_unknown else "")),
        "new_aria": (f"גרף עמודות: צמתים המסומנים כחדשים לפי מחוז, {_int(n_new)} בסך הכול."),
    }

    summary = (f"מפת הצמתים המרומזרים (רמזורים) בישראל: {_int(n)} צמתים ב-{_int(n_cities)} יישובים, "
               f"לפי מחוז, יישוב, כביש וגורם אחראי.")
    if top_city is not None:
        cand = summary + f" {top_city['name']} מובילה עם {_int(top_city['count'])}."
        if len(cand) <= 155:
            summary = cand

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "districts": {"names": dist["name"].tolist(), "series": district_series},
            "cities": cities_chart,
            "tail": {"labels": bucket_labels, "values": bucket_cities},
            "treemap": treemap,
            "bodies": {"names": bodies_names, "values": bodies_vals},
            "roads": roads_chart,
            "kinds": {"names": kind_names, "values": kind_vals},
            "new": new_chart,
        },
        "tables": {
            "domains": dom_names,
            "districts": dist_rows,
            "cities": cities_rows,
            "tail": tail_rows,
            "bodies": bodies_rows,
            "roads": roads_rows,
            "kinds": kinds_rows,
            "new": new_rows,
        },
        "flags": {
            "roads": bool(len(top_r)),
            "bodies": bool(n_body),
            "kinds": bool(n_named),
            "new": bool(n_new),
        },
        "labels": labels,
        "insights": insights,
    }
