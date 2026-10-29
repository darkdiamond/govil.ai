"""קלפיות נגישות להצבעת בוחרים המוגבלים בניידות — משרד הפנים.

One row per accessible ballot station: the local authority (`city`), the
ballot number (`num`), the locality (`yishuv` — empty when the authority is
itself a town, e.g. a municipality), a free-text address (`adress`; for
villages it just repeats the locality name), the venue (`location`), the
district code (`district`) and an authority-type code (`type`: 1 = urban
authority, 2 = regional council in the current file).

The page is primarily a lookup: people search "קלפי נגישה <city>". So the
recipe renders a per-authority directory (capped for growth), says plainly
which authorities the list covers — and, computed against a short list of
large cities people search for, which ones it does NOT cover — then adds the
honest aggregates the data carries (stations per authority, venue type,
venue mix per authority).

Growth: the file is a per-election snapshot that CKAN replaces in place.
A larger (e.g. nationwide) list flows through: authority axes are top-N +
"אחר", the directory is capped at DIR_MAX_ROWS rows (above that it lists
authorities with counts and points to the search under the page), and unknown
district/type codes fall back to their raw value.
"""
import re

import pandas as pd

TOP_AUTH = 12           # authorities on the bar chart before "אחר"
TOP_AUTH_MIX = 8        # authorities in the venue-mix cross-tab
DIR_MAX_ROWS = 400      # directory rows rendered in full
LEADER_SHARE = 0.25     # a "leading authority" holds at least this share
VENUE_LEADER_SHARE = 0.30
SINGLE_SHARE = 0.5      # "most localities have a single station" threshold
LRI, PDI = "⁦", "⁩"

DISTRICTS = {
    "north": "מחוז הצפון", "haifa": "מחוז חיפה", "center": "מחוז המרכז",
    "central": "מחוז המרכז", "tel aviv": "מחוז תל אביב", "telaviv": "מחוז תל אביב",
    "jerusalem": "מחוז ירושלים", "south": "מחוז הדרום",
    "judea and samaria": "אזור יהודה והשומרון",
}
TYPES = {"1": "רשות עירונית", "2": "מועצה אזורית"}
TYPES_PL = {"1": "רשויות עירוניות", "2": "מועצות אזוריות"}

# Venue classes, matched in order against the free-text venue field.
VENUES = [
    ("בית ספר", re.compile(r'בי"ס|ביה"ס|בית ספר|בית הספר|בי״ס|ביה״ס')),
    ('מתנ"ס', re.compile(r'מתנ"ס|מתנ״ס|מרכז קהילתי')),
    ("בית העם", re.compile(r"בית העם|בית עם")),
    ("מועדון", re.compile(r"מועדון")),
    ("מזכירות / משרדים", re.compile(r"מזכירות|משרד")),
]
VENUE_OTHER = "מבנה ציבור אחר"

# Large cities people search for ("קלפי נגישה חיפה"). Used only to say which
# of them this list does not cover — never as a filter.
SEARCHED_CITIES = ["חיפה", "תל אביב-יפו", "ירושלים", "באר שבע"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def clean(s):
    return " ".join(str(s).replace(" ", " ").split())


def norm_key(s):
    s = clean(s).replace("קריית", "קרית").replace("״", '"')
    return re.sub(r"[\s\-–־]", "", s)


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = " ו-" if last[:1].isdigit() else " ו"
    return ", ".join(items[:-1]) + conj + last


def venue_class(s):
    for name, rx in VENUES:
        if rx.search(s):
            return name
    return VENUE_OTHER


def fmt_address(addr, locality):
    a = clean(addr).strip(" ,")
    a = re.sub(r"\s*,\s*", " ", a)
    if not a or norm_key(a) == norm_key(locality):
        return ""
    return a


def _prepare(df):
    out = pd.DataFrame({
        "auth": df["city"].map(clean),
        "ballot_raw": df["num"].map(clean),
        "yishuv": df["yishuv"].map(clean),
        "addr": df["adress"].map(clean),
        "venue": df["location"].map(clean),
        "district": df["district"].map(clean),
        "type": df["type"].map(clean),
    })
    out = out[out["auth"] != ""].copy()
    out["locality"] = out["yishuv"].where(out["yishuv"] != "", out["auth"])
    num = pd.to_numeric(out["ballot_raw"], errors="coerce")
    out["ballot_n"] = num
    out["ballot"] = [
        (str(int(v)) if float(v).is_integer() else str(v)) if pd.notna(v) else r
        for v, r in zip(num, out["ballot_raw"])
    ]
    out["vclass"] = out["venue"].map(venue_class)
    out["address"] = [fmt_address(a, l) for a, l in zip(out["addr"], out["locality"])]
    out["type_he"] = out["type"].map(lambda t: TYPES.get(t, f"סוג {t}" if t else "לא צוין"))
    out["district_he"] = out["district"].map(
        lambda d: DISTRICTS.get(d.lower(), d) if d else "לא צוין")
    # Total order for every downstream sort.
    out = out.sort_values(
        ["auth", "locality", "ballot_n", "ballot", "venue", "addr"],
        kind="mergesort", na_position="last").reset_index(drop=True)
    return out


def _auth_table(df):
    g = (df.groupby("auth")
         .agg(stations=("locality", "size"), localities=("locality", "nunique"),
              type_he=("type_he", lambda s: s.value_counts().sort_index().idxmax()))
         .reset_index())
    g = g.sort_values(["stations", "auth"], ascending=[False, True], kind="mergesort")
    return g.reset_index(drop=True)


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    auth = _auth_table(df)
    n_auth = len(auth)
    loc_keys = df[["auth", "locality"]].drop_duplicates()
    n_loc = len(loc_keys)
    districts = sorted(df["district_he"].unique())
    types = df.groupby("type").size().sort_index()

    # ---- chart: stations + localities per authority (top-N + אחר) -------
    top = auth.head(TOP_AUTH)
    rest = auth.iloc[TOP_AUTH:]
    a_names = list(top["auth"])
    a_st = [int(v) for v in top["stations"]]
    a_loc = [int(v) for v in top["localities"]]
    if len(rest):
        a_names.append(f"אחר ({n(len(rest))} רשויות)")
        a_st.append(int(rest["stations"].sum()))
        a_loc.append(int(rest["localities"].sum()))
    chart_auth = {"names": a_names, "stations": a_st, "localities": a_loc}
    tbl_auth = [{"name": nm, "stations": n(s), "localities": n(l)}
                for nm, s, l in zip(a_names, a_st, a_loc)]

    # ---- chart: venue type ----------------------------------------------
    order = [v for v, _ in VENUES] + [VENUE_OTHER]
    vc = df["vclass"].value_counts()
    venues = sorted([(k, int(vc[k])) for k in order if k in vc.index],
                    key=lambda kv: (-kv[1], order.index(kv[0])))
    chart_venue = {"names": [k for k, _ in venues], "values": [v for _, v in venues]}
    tbl_venue = [{"name": k, "count": n(v), "share": pct(v / total)} for k, v in venues]

    # ---- chart: venue mix per authority (100% stacked) -----------------
    mix_auth = list(auth.head(TOP_AUTH_MIX)["auth"])
    mix_df = df[df["auth"].isin(mix_auth)]
    ct = pd.crosstab(mix_df["auth"], mix_df["vclass"]).reindex(
        index=mix_auth, columns=chart_venue["names"], fill_value=0)
    mix_series = []
    for v in chart_venue["names"]:
        counts = [int(c) for c in ct[v]]
        shares = [round(c / max(int(ct.loc[a].sum()), 1) * 100, 1) for a, c in zip(mix_auth, counts)]
        mix_series.append({"name": v, "share": shares, "count": counts})
    chart_mix = {"names": mix_auth, "series": mix_series}
    tbl_mix = [{"name": a, "cells": [n(ct.loc[a, v]) for v in chart_venue["names"]],
                "total": n(ct.loc[a].sum())} for a in mix_auth]
    mix_capped = n_auth > TOP_AUTH_MIX

    # ---- directory ------------------------------------------------------
    directory = []
    dir_full = total <= DIR_MAX_ROWS
    for _, a in auth.iterrows():
        rows = df[df["auth"] == a["auth"]]
        locs = sorted(rows["locality"].unique())
        entry = {
            "name": a["auth"], "kind": a["type_he"],
            "count": n(a["stations"]), "loc_count": n(a["localities"]),
            "localities": ", ".join(locs),
            "rows": [],
        }
        if dir_full:
            entry["rows"] = [
                {"locality": r.locality, "address": r.address, "venue": r.venue,
                 "ballot": r.ballot, "kind": r.vclass}
                for r in rows.itertuples()
            ]
        directory.append(entry)

    # ---- coverage note (searched cities not in the list) -----------------
    present = set(df["auth"].map(norm_key)) | set(df["locality"].map(norm_key))
    missing = [c for c in SEARCHED_CITIES if norm_key(c) not in present]

    # ---- KPIs -----------------------------------------------------------
    reg = int(types.get("2", 0))
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "auth": {"value": n_auth, "display": n(n_auth), "tone": "brand"},
        "loc": {"value": n_loc, "display": n(n_loc), "tone": "brand"},
    }
    if reg:
        kpis["reg"] = {"value": round(reg / total * 100, 1),
                       "display": f"{reg / total * 100:.0f}%", "tone": "info"}
    else:
        top_share = int(auth["stations"].iloc[0]) / total
        kpis["reg"] = {"value": round(top_share * 100, 1),
                       "display": f"{top_share * 100:.0f}%", "tone": "info"}
    reg_label = ("מהקלפיות נמצאות במועצות אזוריות" if reg
                 else f"מהקלפיות ב{auth['auth'].iloc[0]}, הרשות המובילה")

    # ---- insights -------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_coverage():
        if len(districts) != 1:
            return None
        s = (f"הרשימה מכסה {n(n_auth)} רשויות בלבד, כולן ב{districts[0]}: "
             f"{join_he(list(auth['auth']))}.")
        if missing:
            s += f" ערים כמו {join_he(missing)} אינן כלולות בה."
        return s
    add("coverage", ins_coverage())

    def ins_leader():
        if n_auth < 2:
            return None
        s1, s2 = int(auth["stations"].iloc[0]), int(auth["stations"].iloc[1])
        share = s1 / total
        if share < LEADER_SHARE or s1 == s2:
            return None
        lead = auth.iloc[0]
        verb = "מרכזת יותר ממחצית הרשימה" if share > 0.5 else "מובילה"
        return (f"{lead['auth']} {verb}: {n(s1)} מתוך {n(total)} הקלפיות הנגישות "
                f"({pct(share)}), ב-{n(lead['localities'])} יישובים; אחריה {auth['auth'].iloc[1]} "
                f"עם {n(s2)}.")
    add("leader", ins_leader())

    def ins_single():
        per = df.groupby(["auth", "locality"]).size()
        singles = int((per == 1).sum())
        if n_loc < 3 or singles / n_loc < SINGLE_SHARE:
            return None
        s = (f"ב-{n(singles)} מתוך {n(n_loc)} היישובים ({pct(singles / n_loc)}) יש קלפי נגישה אחת בלבד")
        mx = per.sort_index().sort_values(ascending=False, kind="mergesort")
        if int(mx.iloc[0]) > 1:
            (a_, l_), c_ = mx.index[0], int(mx.iloc[0])
            s += f"; הריכוז הגדול ביותר הוא ב{l_}, עם {n(c_)} קלפיות נגישות"
        return s + "."
    add("single", ins_single())

    def ins_venue():
        if not venues:
            return None
        k, v = venues[0]
        if v / total < VENUE_LEADER_SHARE:
            return None
        s = f"הקלפיות הנגישות ממוקמות בעיקר ב{'מועדוני יישוב' if k == 'מועדון' else k}: {n(v)} מתוך {n(total)} ({pct(v / total)})"
        if len(venues) > 1:
            k2, v2 = venues[1]
            s += f", ואחריהם {k2} ({n(v2)})"
        return s + "."
    add("venue", ins_venue())

    def ins_types():
        if len(types) < 2 or not set(types.index) <= set(TYPES):
            return None
        parts = []
        for t, c in types.items():
            n_a = int(df.loc[df["type"] == t, "auth"].nunique())
            label = TYPES[t] if n_a == 1 else TYPES_PL[t]
            parts.append(f"{n(c)} קלפיות ב-{n(n_a)} {label}" if n_a > 1
                         else f"{n(c)} קלפיות ב{label} אחת")
        urban = df[df["type"] == "1"]
        s = "בפילוח לפי סוג רשות: " + join_he(parts) + "."
        if len(urban) and urban["auth"].nunique() == 1:
            nm = urban["auth"].iloc[0]
            cls = sorted(urban["vclass"].unique())
            s += (f" ב{nm} הקלפיות ממוקמות בכתובות רחוב, במבנים מסוג {join_he(cls)}.")
        return s
    add("types", ins_types())

    # ---- labels ---------------------------------------------------------
    lead = auth.iloc[0]
    labels = {
        "lede": (f"רשימה של {n(total)} קלפיות נגישות לבוחרים המוגבלים בניידות, "
                 f"ב-{n(n_loc)} יישובים ב-{n(n_auth)} רשויות מקומיות"
                 + (f" ב{districts[0]}" if len(districts) == 1 else "")
                 + f". לכל קלפי מופיעים היישוב, הכתובת, המבנה שבו היא ממוקמת ומספר הקלפי. "
                 f"הרשות עם מספר הקלפיות הנגישות הגדול ביותר היא {lead['auth']} ({n(lead['stations'])})."),
        "total_kpi": "קלפיות נגישות ברשימה",
        "auth_kpi": "רשויות מקומיות",
        "loc_kpi": "יישובים עם קלפי נגישה",
        "reg_kpi": reg_label,
        "cover_title": "אילו ערים כלולות ברשימה?",
        "cover_text": (f"הרשימה כוללת {n(n_auth)} רשויות"
                       + (f" ב{districts[0]}" if len(districts) == 1 else f" ב-{n(len(districts))} מחוזות")
                       + f": {join_he(list(auth['auth']))}."),
        "cover_missing": (f"ערים כמו {join_he(missing)} אינן מופיעות ברשימה זו. "
                          "בוחרים מרשויות שאינן ברשימה יכולים לברר את מיקום הקלפי הנגישה הקרובה "
                          "אצל מנהל הבחירות ברשות המקומית שלהם." if missing else ""),
        "dir_note": ("לחצו על שם הרשות כדי לראות את רשימת הקלפיות הנגישות בה, לפי יישוב."
                     if dir_full else
                     f"הרשימה כוללת {n(total)} קלפיות — יותר מדי לרשימה מלאה בעמוד. "
                     "מוצגים כאן מספרי הקלפיות לכל רשות; לחיפוש קלפי לפי יישוב או כתובת השתמשו בחיפוש שבתחתית העמוד."),
        "dir_caption": "קלפיות נגישות לפי יישוב: כתובת, מבנה ומספר קלפי",
        "auth_note": (f"{lead['auth']} מובילה עם {n(lead['stations'])} קלפיות נגישות ב-{n(lead['localities'])} יישובים. "
                      "העמודה הבהירה מציגה כמה יישובים שונים מכוסים בכל רשות."
                      + (f" מוצגות {n(TOP_AUTH)} הרשויות הגדולות; השאר מקובצות תחת \"אחר\"." if len(rest) else "")),
        "auth_aria": (f"גרף עמודות אופקי: מספר הקלפיות הנגישות והיישובים בכל רשות מקומית. "
                      f"המובילה: {lead['auth']} עם {n(lead['stations'])} קלפיות."),
        "auth_caption": "קלפיות נגישות ויישובים לפי רשות מקומית",
        "venue_note": (f"סיווג המבנים לפי תיאור המקום בנתונים. הסוג הנפוץ: {venues[0][0]} "
                       f"({n(venues[0][1])} מתוך {n(total)})." if venues else ""),
        "venue_aria": (f"גרף עמודות: קלפיות נגישות לפי סוג המבנה. הנפוץ: {venues[0][0]} עם {n(venues[0][1])} קלפיות."
                       if venues else "גרף עמודות: קלפיות נגישות לפי סוג המבנה."),
        "venue_caption": "קלפיות נגישות לפי סוג המבנה",
        "mix_note": ("שיעור כל סוג מבנה מתוך הקלפיות הנגישות בכל רשות. מעבר עם העכבר מציג גם את המספר."
                     + (f" מוצגות {n(TOP_AUTH_MIX)} הרשויות הגדולות." if mix_capped else "")),
        "mix_aria": f"גרף עמודות מוערמות: התפלגות סוגי המבנים של הקלפיות הנגישות ב-{n(len(mix_auth))} רשויות.",
        "mix_caption": "קלפיות נגישות לפי רשות וסוג מבנה",
    }

    summary = (f"רשימת קלפיות נגישות לבוחרים המוגבלים בניידות לפי יישוב, עם כתובת ומבנה: "
               f"{n(total)} קלפיות ב-{n(n_loc)} יישובים ב-{n(n_auth)} רשויות"
               + (f" ב{districts[0]}" if len(districts) == 1 else "") + ".")

    tags = ["בחירות", "נגישות", "קלפיות", "מוגבלות בניידות"]
    if len(districts) == 1:
        tags.append(districts[0])

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": tags[:8],
            "related_ids": ["f8bc8173-367b-4d14-930e-3c8a1d53099f",
                            "ebe5ec6f-3e37-4bd9-bbdc-926ad1e0d6b9"],
            "spatial_coverage": districts[0] if len(districts) == 1 else "ישראל",
        },
        "kpis": kpis,
        "charts": {"auth": chart_auth, "venue": chart_venue, "mix": chart_mix},
        "tables": {"auth": tbl_auth, "venue": tbl_venue, "mix": tbl_mix},
        "directory": directory,
        "flags": {"dir_full": dir_full, "missing": bool(missing),
                  "mix": len(mix_auth) >= 2 and len(chart_venue["names"]) >= 2},
        "insights": insights,
        "labels": labels,
        "links": {"special": "/datasets/f8bc8173-367b-4d14-930e-3c8a1d53099f/",
                  "managers": "/datasets/ebe5ec6f-3e37-4bd9-bbdc-926ad1e0d6b9/"},
    }
