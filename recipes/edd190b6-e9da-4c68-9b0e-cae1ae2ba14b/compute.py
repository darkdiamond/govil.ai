"""Recipe compute for שמות צמתים ומחלפים (Ministry of Transport signage names).

One table: every junction / interchange whose name appears on an advance
signage plate on the inter-urban road network, with ITM coordinates, its
current and future form, the roads that meet there, and the signage
committee / gazette references. Pure function of the rows.
"""

import math
import re

import numpy as np
import pandas as pd

UNBUILT = "טרם נבנה"
TYPE_ORDER = ["צומת", "צומת מפוצל", "מחלף", UNBUILT]
STATUS_ORDER = ["קיים", "קיים לשדרוג", "מתוכנן"]
TYPE_LABEL = {
    "צומת": "צומת במפלס",
    "צומת מפוצל": "צומת מפוצל",
    "מחלף": "מחלף",
    UNBUILT: "מתוכנן (טרם נבנה)",
}
# North→south bands on the ITM northing (metres). Approximate regions.
BANDS = [
    (735000, "צפון: חיפה, הגליל והגולן"),
    (680000, "השרון, העמקים וואדי ערה"),
    (610000, "מרכז: גוש דן, ירושלים והשפלה"),
    (540000, "דרום: מישור החוף הדרומי והנגב הצפוני"),
    (-math.inf, "הנגב ההררי והערבה"),
]
ROAD_CLASSES = [
    (1, "כבישים ארציים ראשיים (ספרה אחת)", "ספרה אחת"),
    (2, "כבישים ארציים (שתי ספרות)", "שתי ספרות"),
    (3, "כבישים אזוריים (שלוש ספרות)", "שלוש ספרות"),
    (4, "כבישים מקומיים (ארבע ספרות)", "ארבע ספרות"),
]
TOP_ROADS = 15
TOP_WORDS = 12
NEAR_BINS = [(0, 1000, "עד 1 ק״מ"), (1000, 2000, "1-2 ק״מ"), (2000, 3000, "2-3 ק״מ"),
             (3000, 5000, "3-5 ק״מ"), (5000, 10000, "5-10 ק״מ"), (10000, math.inf, "מעל 10 ק״מ")]
NEAR_PAIR_M = 2000  # same name within this distance = one junction signed in two places


def _fmt(n):
    return f"{int(n):,}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _ordered(values, order):
    known = [v for v in order if v in values]
    extra = sorted(v for v in values if v not in order)
    return known + extra


def _roads(raw):
    """Split the RAODS field into (numbered roads, named streets)."""
    nums, names = [], []
    for tok in str(raw).split("/"):
        t = tok.strip()
        if not t:
            continue
        if re.fullmatch(r"\d+(\s*-\s*\d+)+", t):
            nums.extend(p.strip() for p in t.split("-"))
            continue
        m = re.fullmatch(r"(\d+)\s*(\(.*\))?", t)
        if m:
            nums.append(m.group(1))
        else:
            names.append(t)
    seen, uniq = set(), []
    for n in nums:
        n = str(int(n))
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq, names


def _band(y):
    for lo, name in BANDS:
        if y >= lo:
            return name
    return BANDS[-1][1]


def compute(frames):
    df = frames["names"].copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    df["x"] = pd.to_numeric(df["X"].str.replace(",", ""), errors="coerce")
    df["y"] = pd.to_numeric(df["Y"].str.replace(",", ""), errors="coerce")
    df = df[df["HEBREW"] != ""].copy()
    df = df.sort_values(["HEBREW", "x", "y", "NUM"], kind="mergesort").reset_index(drop=True)
    total = len(df)

    df["type"] = df["CURRENT"].where(df["CURRENT"] != "", UNBUILT)
    df["status"] = df["STATUS"].where(df["STATUS"] != "", "לא צוין")
    parsed = df["RAODS"].apply(_roads)
    df["nums"] = parsed.apply(lambda p: p[0])
    df["streets"] = parsed.apply(lambda p: p[1])

    types = _ordered(set(df["type"]), TYPE_ORDER)
    type_counts = {t: int((df["type"] == t).sum()) for t in types}
    n_inter = type_counts.get("מחלף", 0)
    n_plain = type_counts.get("צומת", 0)
    n_split = type_counts.get("צומת מפוצל", 0)
    n_unbuilt = type_counts.get(UNBUILT, 0)
    statuses = _ordered(set(df["status"]), STATUS_ORDER)
    status_counts = {s: int((df["status"] == s).sum()) for s in statuses}
    n_upgrade = status_counts.get("קיים לשדרוג", 0)
    n_planned = status_counts.get("מתוכנן", 0)

    def tl(t):
        return TYPE_LABEL.get(t, t)

    # ---- type mix
    ch_type = {"names": [tl(t) for t in types], "values": [type_counts[t] for t in types]}
    tbl_type = [{"name": tl(t), "count": _fmt(type_counts[t]), "share": _pct(type_counts[t] / total)} for t in types]

    # ---- current → future flows (only rows with a recorded future form)
    fut = df[df["FUTURE"] != ""]
    flows = (fut.groupby(["type", "FUTURE"]).size().reset_index(name="n")
             .sort_values(["n", "type", "FUTURE"], ascending=[False, True, True], kind="mergesort"))
    links, nodes = [], []
    for r in flows.itertuples():
        src = "טרם נבנה" if r.type == UNBUILT else tl(r.type)
        s, t = f"{src} (היום)", f"{tl(r.FUTURE)} (בעתיד)"
        links.append({"source": s, "target": t, "value": int(r.n)})
        for nm in (s, t):
            if nm not in nodes:
                nodes.append(nm)
    ch_flow = {"nodes": [{"name": n} for n in nodes], "links": links}
    tbl_flow = [{"from": tl(r.type), "to": tl(r.FUTURE), "count": _fmt(r.n)} for r in flows.itertuples()]
    n_future_inter = int((fut["FUTURE"] == "מחלף").sum())

    # ---- roads
    ex = df[["HEBREW", "type", "nums"]].explode("nums").dropna(subset=["nums"])
    road_tot = ex.groupby("nums").size()
    road_inter = ex[ex["type"] == "מחלף"].groupby("nums").size()
    roads_rank = sorted(road_tot.index, key=lambda r: (-int(road_tot[r]), int(r)))
    n_roads = len(roads_rank)
    top_roads = roads_rank[:TOP_ROADS]
    ch_roads = {"names": [f"כביש {r}" for r in top_roads], "series": []}
    for t in types:
        sub = ex[ex["type"] == t].groupby("nums").size()
        ch_roads["series"].append({"name": tl(t), "data": [int(sub.get(r, 0)) for r in top_roads]})
    tbl_roads = [{"name": f"כביש {r}", "count": _fmt(road_tot[r]), "inter": _fmt(road_inter.get(r, 0)),
                  "share": _pct(road_inter.get(r, 0) / road_tot[r], 0)} for r in top_roads]

    # ---- road classes (by number of digits)
    ex["digits"] = ex["nums"].str.len()
    cls_rows = []
    for d, name, short in ROAD_CLASSES:
        sub = ex[ex["digits"] == d] if d < 4 else ex[ex["digits"] >= 4]
        if len(sub) == 0:
            continue
        cls_rows.append({"name": name, "short": short, "roads": int(sub["nums"].nunique()), "points": len(sub),
                         "inter": int((sub["type"] == "מחלף").sum())})
    ch_class = {"names": [c["short"] for c in cls_rows], "long": [c["name"] for c in cls_rows], "points": [c["points"] for c in cls_rows],
                "share": [round(c["inter"] / c["points"] * 100, 1) for c in cls_rows]}
    tbl_class = [{"name": c["name"], "roads": _fmt(c["roads"]), "points": _fmt(c["points"]),
                  "share": _pct(c["inter"] / c["points"])} for c in cls_rows]

    # ---- legs: how many numbered roads / streets meet
    def legs(r):
        n, s = len(r["nums"]), len(r["streets"])
        if s and n:
            return "כביש ורחוב עירוני"
        if s:
            return "רחובות בלבד"
        if n >= 3:
            return "שלושה כבישים או יותר"
        if n == 2:
            return "שני כבישים ממוספרים"
        return "כביש אחד"
    df["legs"] = df.apply(legs, axis=1)
    legs_order = ["שני כבישים ממוספרים", "שלושה כבישים או יותר", "כביש ורחוב עירוני", "כביש אחד", "רחובות בלבד"]
    legs_c = df["legs"].value_counts()
    legs_names = [lname for lname in legs_order if lname in legs_c.index]
    ch_legs = {"names": legs_names, "values": [int(legs_c[lname]) for lname in legs_names]}
    tbl_legs = [{"name": lname, "count": _fmt(legs_c[lname]), "share": _pct(legs_c[lname] / total)} for lname in legs_names]
    n_street = int(df["streets"].apply(len).gt(0).sum())

    # ---- north→south bands
    geo = df.dropna(subset=["x", "y"]).copy()
    geo["band"] = geo["y"].apply(_band)
    band_names = [b[1] for b in BANDS if (geo["band"] == b[1]).any()]
    ch_band = {"names": band_names, "series": []}
    for t in types:
        ch_band["series"].append({"name": tl(t), "data": [int(((geo["band"] == b) & (geo["type"] == t)).sum()) for b in band_names]})
    band_stats = []
    for b in band_names:
        sub = geo[geo["band"] == b]
        built = sub[sub["type"] != UNBUILT]
        band_stats.append({"name": b, "n": len(sub), "inter": int((sub["type"] == "מחלף").sum()),
                           "built": len(built)})
    tbl_band = [{"name": s["name"], "count": _fmt(s["n"]), "inter": _fmt(s["inter"]),
                 "share": _pct(s["inter"] / s["built"], 0) if s["built"] else "—"} for s in band_stats]

    # ---- nearest named neighbour
    xy = geo[["x", "y"]].to_numpy()
    nn = None
    if len(xy) >= 2:
        d = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1))
        np.fill_diagonal(d, np.inf)
        nn = d.min(axis=1)
    near_rows = []
    if nn is not None:
        for lo, hi, name in NEAR_BINS:
            near_rows.append({"name": name, "n": int(((nn >= lo) & (nn < hi)).sum())})
        near_rows = [r for r in near_rows if r["n"] > 0] if sum(r["n"] for r in near_rows) else near_rows
    ch_near = {"names": [r["name"] for r in near_rows], "values": [r["n"] for r in near_rows]}
    tbl_near = [{"name": r["name"], "count": _fmt(r["n"]), "share": _pct(r["n"] / len(xy))} for r in near_rows]

    # ---- committee decisions by year
    vd = pd.to_datetime(df["VAADA"], errors="coerce", format="%d/%m/%Y %H:%M:%S")
    df["vyear"] = vd.dt.year
    dec = df.dropna(subset=["vyear"])
    n_dec = len(dec)
    years = sorted(int(y) for y in dec["vyear"].unique())
    ch_vaada = {"names": [str(y) for y in years], "series": []}
    for s in statuses:
        ch_vaada["series"].append({"name": s, "data": [int(((dec["vyear"] == y) & (dec["status"] == s)).sum()) for y in years]})
    n_sessions = int(vd.dropna().dt.normalize().nunique())
    gaz = df["YALKUTPIR"].str.match(r"^\s*\d+")
    n_gaz = int(gaz.sum())
    tbl_vaada = [{"name": str(y), "count": _fmt((dec["vyear"] == y).sum()),
                  "sessions": _fmt(vd[df["vyear"] == y].dt.normalize().nunique()),
                  "gazette": _fmt(((dec["vyear"] == y) & gaz[dec.index]).sum())} for y in years]

    # ---- name words
    multi = df[df["HEBREW"].str.split().str.len() >= 2]
    fw = multi["HEBREW"].str.split().str[0].value_counts()
    words = sorted([w for w in fw.index if fw[w] >= 2], key=lambda w: (-int(fw[w]), w))[:TOP_WORDS]
    ch_words = {"names": words, "values": [int(fw[w]) for w in words]}
    tbl_words = [{"name": w, "count": _fmt(fw[w]),
                  "examples": ", ".join(sorted(multi[multi["HEBREW"].str.split().str[0] == w]["HEBREW"].unique())[:3])}
                 for w in words]
    n_single = int((df["HEBREW"].str.split().str.len() == 1).sum())

    # ---- trilingual completeness
    tri = (df["ARABIC"] != "") & (df["LATIN"] != "")
    n_tri = int(tri.sum())

    # ---- repeated names
    dup_names = sorted(df["HEBREW"][df["HEBREW"].duplicated(keep=False)].unique())
    dup_close, dup_far = [], []
    for nm in dup_names:
        pts = geo[geo["HEBREW"] == nm][["x", "y"]].to_numpy()
        if len(pts) < 2:
            continue
        dd = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)).max()
        (dup_close if dd <= NEAR_PAIR_M else dup_far).append((nm, dd))
    n_unique = int(df["HEBREW"].nunique())

    # ---------------------------------------------------------- insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_mix():
        built = total - n_unbuilt
        if built <= 0:
            return None
        at_grade = n_plain + n_split
        lead = "רובן המכריע" if at_grade / built >= 0.6 else ("רובן" if at_grade / built > 0.5 else None)
        if lead is None:
            if n_inter / built > 0.5:
                return (f"מחלפים הם הרוב: {_fmt(n_inter)} מתוך {_fmt(built)} הנקודות הבנויות ({_pct(n_inter / built)}), "
                        f"לעומת {_fmt(at_grade)} צמתים במפלס.")
            return None
        return (f"{lead} של הנקודות הבנויות הן צמתים במפלס: {_fmt(at_grade)} מתוך {_fmt(built)} ({_pct(at_grade / built)}), "
                f"מהם {_fmt(n_split)} צמתים מפוצלים. המחלפים מונים {_fmt(n_inter)} ({_pct(n_inter / built)}).")

    def ins_top_road():
        if len(roads_rank) < 2:
            return None
        r1, r2 = roads_rank[0], roads_rank[1]
        c1, c2 = int(road_tot[r1]), int(road_tot[r2])
        if c1 <= c2:
            return None
        i1 = int(road_inter.get(r1, 0))
        return (f"כביש {r1} הוא הכביש עם הכי הרבה צמתים ומחלפים בעלי שם: {_fmt(c1)}, לעומת {_fmt(c2)} בכביש {r2} שבמקום השני; "
                f"{_fmt(i1)} מהם ({_pct(i1 / c1, 0)}) מחלפים.")

    def ins_road_extremes():
        big = [r for r in roads_rank if road_tot[r] >= 10]
        if len(big) < 3:
            return None
        sh = {r: road_inter.get(r, 0) / road_tot[r] for r in big}
        hi = sorted(big, key=lambda r: (-sh[r], -int(road_tot[r]), int(r)))[0]
        lo = sorted(big, key=lambda r: (sh[r], -int(road_tot[r]), int(r)))[0]
        if sh[hi] - sh[lo] < 0.3:
            return None
        return (f"בין הכבישים עם עשרה צמתים בעלי שם או יותר, כביש {hi} מופרד מפלסית ברובו — {_pct(sh[hi], 0)} מהנקודות בו מחלפים "
                f"({_fmt(road_inter.get(hi, 0))} מתוך {_fmt(road_tot[hi])}), "
                + (f"ואילו בכביש {lo} אין אף מחלף בין {_fmt(road_tot[lo])} הנקודות." if sh[lo] == 0 else
                   f"ואילו בכביש {lo} רק {_pct(sh[lo], 0)} ({_fmt(road_inter.get(lo, 0))} מתוך {_fmt(road_tot[lo])})."))

    def ins_upgrades():
        if n_upgrade + n_planned == 0:
            return None
        parts = []
        if n_upgrade:
            parts.append(f"{_fmt(n_upgrade)} צמתים קיימים מסומנים לשדרוג")
        if n_planned:
            parts.append(f"{_fmt(n_planned)} נקודות מתוכננות שטרם נבנו")
        tail = f"; {_fmt(n_future_inter)} מהן צפויות להפוך למחלפים." if n_future_inter else "."
        return "הרשימה כבר כוללת את הרשת העתידית: " + " ועוד ".join(parts) + tail

    def ins_vaada():
        if len(years) < 2 or n_dec == 0:
            return None
        yc = dec["vyear"].value_counts()
        peak = sorted(years, key=lambda y: (-int(yc[y]), -y))[0]
        last = years[-1]
        s = (f"{_fmt(n_dec)} שמות ({_pct(n_dec / total)}) אושרו בוועדת השילוט של משרד התחבורה ב־{_fmt(n_sessions)} ישיבות "
             f"בין {years[0]} ל־{last}; השנה העמוסה ביותר הייתה {peak} עם {_fmt(yc[peak])} שמות")
        s += "." if peak == last else f", ובשנת {last} אושרו {_fmt(yc[last])}."
        return s

    def ins_band():
        ok = [b for b in band_stats if b["built"] >= 15]
        if len(ok) < 2:
            return None
        sh = {b["name"]: b["inter"] / b["built"] for b in ok}
        hi = sorted(ok, key=lambda b: (-sh[b["name"]], b["name"]))[0]
        lo = sorted(ok, key=lambda b: (sh[b["name"]], b["name"]))[0]
        if sh[hi["name"]] - sh[lo["name"]] < 0.1:
            return None
        return (f"שיעור המחלפים משתנה לאורך הארץ: ברצועת \"{hi['name']}\" {_pct(sh[hi['name']], 0)} מהנקודות הבנויות הן מחלפים, "
                f"וברצועת \"{lo['name']}\" רק {_pct(sh[lo['name']], 0)} (רצועות עם חמש עשרה נקודות בנויות לפחות).")

    def ins_near():
        if nn is None:
            return None
        med = float(np.median(nn))
        far_i = int(np.argmax(nn))
        far_name = geo.iloc[far_i]["HEBREW"]
        return (f"המרחק החציוני מצומת בעל שם לצומת הקרוב אליו הוא {med / 1000:.1f} ק״מ; "
                f"הצומת המבודד ביותר הוא \"{far_name}\", {nn[far_i] / 1000:.1f} ק״מ מהשכן הקרוב.")

    def ins_dups():
        if not dup_names:
            return None
        s = f"{_fmt(len(dup_names))} שמות מופיעים ביותר מנקודה אחת"
        if dup_close:
            s += f"; {_fmt(len(dup_close))} מהם הם זוגות במרחק של עד {NEAR_PAIR_M // 1000} ק״מ — צמתים מפוצלים או שתי זרועות של אותו מחלף"
        if dup_far:
            names = ", ".join(n for n, _ in sorted(dup_far, key=lambda t: (-t[1], t[0]))[:3])
            if len(dup_far) == 1:
                s += f", ושם אחד ({names}) חוזר בנקודות רחוקות זו מזו"
            else:
                s += f", ו־{_fmt(len(dup_far))} שמות חוזרים בנקודות רחוקות זו מזו (למשל {names})"
        return s + "."

    def ins_street():
        if n_street == 0 or n_street / total < 0.05:
            return None
        return (f"ב־{_fmt(n_street)} נקודות ({_pct(n_street / total)}) הכביש הבין־עירוני פוגש רחוב עירוני בעל שם ולא כביש ממוספר — "
                f"בדרך כלל כניסה ליישוב.")

    add("mix", ins_mix())
    add("top_road", ins_top_road())
    add("road_extremes", ins_road_extremes())
    add("band", ins_band())
    add("upgrades", ins_upgrades())
    add("vaada", ins_vaada())
    add("near", ins_near())
    add("dups", ins_dups())
    add("street", ins_street())

    # ---------------------------------------------------------- KPIs
    tri_share = n_tri / total if total else 0
    kpis = {
        "total": {"value": total, "display": _fmt(total), "tone": "brand",
                  "label": "צמתים ומחלפים בעלי שם לשילוט"},
        "inter": {"value": n_inter, "display": _fmt(n_inter), "tone": "info",
                  "label": "מחלפים (הפרדה מפלסית)"},
        "future": {"value": n_upgrade + n_planned, "display": _fmt(n_upgrade + n_planned),
                   "tone": "warn" if n_upgrade + n_planned else "brand",
                   "label": "מתוכננים או מסומנים לשדרוג"},
        "roads": {"value": n_roads, "display": _fmt(n_roads), "tone": "brand",
                  "label": "כבישים ממוספרים שונים"},
        "trilingual": {"value": round(tri_share * 100, 1), "display": _pct(tri_share),
                       "tone": "ok" if tri_share >= 0.99 else "warn",
                       "label": "שמות עם תעתיק לערבית ולאותיות לטיניות"},
    }

    ys, ye = (years[0], years[-1]) if years else (None, None)
    top_r = roads_rank[0] if roads_rank else None
    summary = (f"צמתים ומחלפים בישראל: איתור צומת או מחלף לפי שם או מספר כביש, על מפה — "
               f"{_fmt(total)} נקודות בעלות שם, מהן {_fmt(n_inter)} מחלפים, על {_fmt(n_roads)} כבישים.")
    lede = (f"רשימת {_fmt(total)} הצמתים והמחלפים בכבישים הבין־עירוניים בארץ ששמם מופיע על שלט ההכוונה המקדים, "
               f"לפי פרסום \"שמות יעדים בשילוט הדרכה\" של משרד התחבורה: {_fmt(n_plain + n_split)} צמתים במפלס, "
               f"{_fmt(n_inter)} מחלפים ו־{_fmt(n_planned)} נקודות מתוכננות, על פני {_fmt(n_roads)} כבישים ממוספרים. "
               f"לכל נקודה שם בעברית, בערבית ובאותיות לטיניות, מיקום, הכבישים הנפגשים בה וצורתה העתידית.")

    top_band = max(band_stats, key=lambda b: (b["n"], b["name"])) if band_stats else None
    near_med = float(np.median(nn)) if nn is not None else None
    labels = {
        "lede": lede,
        "map_note": f"כל {_fmt(len(geo))} הנקודות על המפה. לחיצה על נקודה מציגה את שמה, צורתה והכבישים הנפגשים בה.",
        "type_note": (f"{_fmt(n_plain)} צמתים במפלס, {_fmt(n_split)} צמתים מפוצלים, {_fmt(n_inter)} מחלפים"
                      + (f" ו־{_fmt(n_unbuilt)} נקודות שטרם נבנו." if n_unbuilt else ".")),
        "type_aria": f"תרשים טבעת: חלוקת {_fmt(total)} הנקודות לפי צורה. מחלפים: {_fmt(n_inter)}, צמתים במפלס: {_fmt(n_plain)}.",
        "type_caption": "חלוקת הצמתים והמחלפים לפי צורתם היום",
        "flow_note": (f"{_fmt(len(fut))} נקודות שצורתן העתידית שונה מצורתן היום (שדרוג או בנייה חדשה); "
                      f"{_fmt(n_future_inter)} מהן יהיו מחלפים."),
        "flow_aria": f"תרשים זרימה: {_fmt(len(fut))} נקודות שצורתן משתנה, מצורה נוכחית לצורה עתידית; {_fmt(n_future_inter)} יהפכו למחלפים.",
        "flow_caption": "מעבר מצורה נוכחית לצורה עתידית",
        "roads_note": (f"{len(top_roads)} הכבישים עם מספר הצמתים בעלי השם הגדול ביותר, מתוך {_fmt(n_roads)} כבישים ממוספרים. "
                       f"נקודה שבה נפגשים שני כבישים נספרת בשניהם."),
        "roads_aria": (f"תרשים עמודות מוערמות: צמתים ומחלפים לפי כביש. מוביל: כביש {top_r} עם {_fmt(road_tot[top_r])} נקודות."
                       if top_r else "תרשים עמודות: צמתים ומחלפים לפי כביש."),
        "roads_caption": "צמתים ומחלפים בעלי שם לפי כביש",
        "classes_note": "כל צומת נספר פעם אחת לכל כביש ממוספר שעובר בו, לפי מספר הספרות במספר הכביש. הקו מציג את שיעור המחלפים.",
        "classes_aria": "תרשים עמודות וקו: מספר הצמתים ושיעור המחלפים לפי דרגת הכביש.",
        "classes_caption": "צמתים ושיעור מחלפים לפי דרגת הכביש",
        "legs_note": f"ב־{_fmt(n_street)} נקודות אחת הזרועות היא רחוב עירוני בעל שם ולא כביש ממוספר.",
        "legs_aria": f"תרשים עמודות: הנקודות לפי סוג הדרכים הנפגשות בהן. {_fmt(n_street)} נקודות כוללות רחוב עירוני.",
        "legs_caption": "הנקודות לפי סוג הדרכים הנפגשות בהן",
        "bands_note": ("רצועות צפון–דרום לפי קואורדינטת הצפון ברשת ישראל; גבולות הרצועות משוערים."
                      + (f" הרצועה הצפופה ביותר: {top_band['name']} ({_fmt(top_band['n'])} נקודות)." if top_band else "")),
        "bands_aria": (f"תרשים עמודות מוערמות: נקודות לפי רצועה גאוגרפית וצורה. הצפופה ביותר: {top_band['name']}."
                      if top_band else "תרשים עמודות לפי רצועה גאוגרפית."),
        "bands_caption": "צמתים ומחלפים לפי רצועה גאוגרפית",
        "near_note": (f"המרחק בקו אווירי מכל נקודה לנקודה בעלת השם הקרובה אליה. חציון: {near_med / 1000:.1f} ק״מ."
                      if near_med is not None else ""),
        "near_aria": (f"תרשים עמודות: התפלגות המרחק לצומת הקרוב. חציון {near_med / 1000:.1f} ק״מ."
                      if near_med is not None else "תרשים עמודות: התפלגות המרחק לצומת הקרוב."),
        "near_caption": "התפלגות המרחק לצומת בעל השם הקרוב",
        "vaada_note": (f"{_fmt(n_dec)} שמות שלהם תאריך החלטה של ועדת השילוט, לפי שנה ומצב; {_fmt(n_gaz)} פורסמו גם בילקוט הפרסומים. "
                       f"ליתר השמות לא רשום תאריך ועדה."),
        "vaada_aria": (f"תרשים עמודות מוערמות: שמות שאושרו בוועדת השילוט לפי שנה, {ys}-{ye}." if years
                       else "תרשים עמודות: שמות שאושרו בוועדת השילוט לפי שנה."),
        "vaada_caption": "החלטות ועדת השילוט לפי שנה",
        "words_note": (f"{_fmt(n_single)} מהשמות הם מילה אחת. בשמות של שתי מילים או יותר, המילים הפותחות הנפוצות "
                       f"(מופיעות לפחות פעמיים)."),
        "words_aria": (f"תרשים עמודות: המילים הפותחות הנפוצות בשמות הצמתים. הנפוצה: {words[0]}." if words
                       else "תרשים עמודות: המילים הפותחות הנפוצות בשמות הצמתים."),
        "words_caption": "המילים הפותחות הנפוצות בשמות הצמתים",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["שילוט", "צמתים", "מחלפים", "דרכים", "כבישים", "תחבורה"],
            "related_ids": ["09cbcff5-64fc-429b-96e5-881cbcab96af", "3bf88891-4cb3-4288-81ef-bad6a9f8d625",
                            "263e3397-aac1-4f8a-b1e3-caff7eabcbff"],
            "spatial_coverage": "ארצי — דרכים בין־עירוניות",
        },
        "kpis": kpis,
        "kpi_order": ["total", "inter", "future", "roads", "trilingual"],
        "charts": {
            "type": ch_type, "flow": ch_flow, "roads": ch_roads, "classes": ch_class, "legs": ch_legs,
            "bands": ch_band, "near": ch_near, "vaada": ch_vaada, "words": ch_words,
        },
        "tables": {
            "type": tbl_type, "flow": tbl_flow, "roads": tbl_roads, "classes": tbl_class, "legs": tbl_legs,
            "bands": tbl_band, "near": tbl_near, "vaada": tbl_vaada, "words": tbl_words,
        },
        "has_flow": bool(links),
        "has_vaada": bool(years),
        "has_words": bool(words),
        "has_near": bool(near_rows),
        "insights": insights,
        "labels": labels,
    }
