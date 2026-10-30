"""קלפיות מיוחדות בפריסה ארצית, בחירות לרשויות המקומיות — משרד הפנים.

One row per special ballot station: the district (`district`, an English
code), the local authority (`City`; regional councils carry a `מוא"ז`
prefix), a street address (`address`), the venue (`location`, free text),
optional arrival directions (`direction`: floor, room, elevator) and a
physical-accessibility flag (`access`: yes / no).

The file says nothing about who is eligible to vote at a special station,
so the page does not claim it. It is a lookup first (people search "קלפי
מיוחדת <city>"): a directory by district and authority with address, venue,
directions and accessibility, then the honest aggregates 65 rows carry:
stations and accessibility per district, per authority, and per venue type
(classified by keyword from the venue text).

Growth: the file is a per-election snapshot that CKAN replaces in place.
A larger list flows through: authority axes are top-N + "אחר", the
directory renders in full up to DIR_MAX_ROWS rows (above that, per-authority
counts only, pointing to the search under the page), unknown district codes
fall back to their raw value and unknown access values to "לא צוין".
"""
import re

import pandas as pd

TOP_AUTH = 12            # authorities on the bar chart before "אחר"
DIR_MAX_ROWS = 400       # directory rows rendered in full
DISTRICT_LEAD = 0.30     # a "leading district" holds at least this share
CLUSTER_MIN = 3          # an authority needs this many stations for the "none accessible" rule
DISTRICT_MIN = 3         # a district needs this many stations for the best/worst rule
ACCESS_GAP = 0.25        # best vs worst district accessibility gap worth a sentence
VENUE_MIN = 2            # hotels/venue-type insight needs at least this many stations
LRI, PDI = "⁦", "⁩"

DISTRICTS = {
    "north": "מחוז הצפון", "haifa": "מחוז חיפה", "center": "מחוז המרכז",
    "central": "מחוז המרכז", "tel aviv": "מחוז תל אביב", "telaviv": "מחוז תל אביב",
    "jerusalem": "מחוז ירושלים", "south": "מחוז הדרום",
    "judea and samaria": "אזור יהודה והשומרון",
}
DISTRICT_ORDER = ["מחוז הצפון", "מחוז חיפה", "מחוז המרכז", "מחוז תל אביב",
                  "מחוז ירושלים", "מחוז הדרום", "אזור יהודה והשומרון"]
ACCESS = {"yes": "נגישה", "no": "לא נגישה", "כן": "נגישה", "לא": "לא נגישה"}
ACC_YES, ACC_NO, ACC_NA = "נגישה", "לא נגישה", "לא צוין"

HOTEL = "מלון"
# Venue classes, matched in order. Hotels match the venue OR the address
# (a lobby venue at a hotel address); the rest match the venue text, with
# the municipal class as a last address-based fallback.
VENUES = [
    (HOTEL, re.compile(r"מלון|לובי|כפר הנופש")),
    ("מוסד חינוך", re.compile(r"בי''ס|בי\"ס|ביה\"ס|בי״ס|ביה״ס|בית ספר|בית הספר|מכללה|קרי?ית החינוך")),
    ('מתנ"ס או מרכז קהילתי', re.compile(r"מתנ''ס|מתנ\"ס|מתנ״ס|מתנס|מרכז|בית האזרח")),
    ("מועדון או בית העם", re.compile(r"מועדון|בית העם|בית המתנדב|בית ידידות|יד לבנים|מידעטק")),
    ("בניין העירייה או המועצה", re.compile(r"עירי|מועצ|משרדי|מזכירות")),
]
VENUE_OTHER = "מבנה ציבור אחר"
VENUE_ORDER = [v for v, _ in VENUES] + [VENUE_OTHER]
REGIONAL_RX = re.compile(r"^מוא[\"'״]{1,2}ז\s*")
ELEVATOR_RX = re.compile(r"מעלית")


def n(v):
    return f"{int(v):,}"


def stations(v):
    return "קלפי אחת" if v == 1 else f"{n(v)} קלפיות"


def in_stations(v):
    return "בקלפי אחת" if v == 1 else f"ב-{n(v)} קלפיות"


def in_auths(v):
    return "ברשות אחת" if v == 1 else f"ב-{n(v)} רשויות"


def in_dists(v):
    return "במחוז אחד" if v == 1 else f"ב-{n(v)} מחוזות"


def pct(v, digits=0):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def clean(s):
    return " ".join(str(s).replace(" ", " ").split())


def auth_name(s):
    s = clean(s)
    s = re.sub(r"\s*-\s*", "-", s)
    if REGIONAL_RX.match(s):
        s = "מועצה אזורית " + REGIONAL_RX.sub("", s)
    return s


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = " ו-" if last[:1].isdigit() else " ו"
    return ", ".join(items[:-1]) + conj + last


def venue_class(venue, addr):
    if VENUES[0][1].search(venue) or VENUES[0][1].search(addr):
        return HOTEL
    for name, rx in VENUES[1:]:
        if rx.search(venue):
            return name
    # A bare hall/room description at a city-hall address ("עיריית …").
    if VENUES[-1][1].search(addr):
        return VENUES[-1][0]
    return VENUE_OTHER


def _prepare(df):
    out = pd.DataFrame({
        "district_raw": df["district"].map(clean),
        "auth_raw": df["City"].map(clean),
        "address": df["address"].map(clean),
        "venue": df["location"].map(clean),
        "direction": df["direction"].map(clean),
        "access_raw": df["access"].map(clean),
    })
    out = out[out["auth_raw"] != ""].copy()
    out["auth"] = out["auth_raw"].map(auth_name)
    out["district"] = out["district_raw"].map(
        lambda d: DISTRICTS.get(d.lower(), d) if d else "לא צוין")
    out["access"] = out["access_raw"].map(lambda a: ACCESS.get(a.lower(), ACC_NA))
    out["vclass"] = [venue_class(v, a) for v, a in zip(out["venue"], out["address"])]
    out["elevator"] = out["direction"].map(lambda s: bool(ELEVATOR_RX.search(s))) | \
        out["venue"].map(lambda s: bool(ELEVATOR_RX.search(s)))
    out["d_ord"] = out["district"].map(
        lambda d: DISTRICT_ORDER.index(d) if d in DISTRICT_ORDER else len(DISTRICT_ORDER))
    out = out.sort_values(
        ["d_ord", "district", "auth", "address", "venue", "direction", "access"],
        kind="mergesort").reset_index(drop=True)
    return out


def _acc_counts(sub):
    return (int((sub["access"] == ACC_YES).sum()), int((sub["access"] == ACC_NO).sum()),
            int((sub["access"] == ACC_NA).sum()))


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    n_yes, n_no, n_na = _acc_counts(df)
    has_na = n_na > 0

    # ---- per district ----------------------------------------------------
    dist_rows = []
    for d, sub in df.groupby("district", sort=False):
        y, no, na = _acc_counts(sub)
        dist_rows.append({"name": d, "ord": int(sub["d_ord"].iloc[0]), "total": len(sub),
                          "yes": y, "no": no, "na": na,
                          "auth": int(sub["auth"].nunique())})
    dist_rows.sort(key=lambda r: (-r["total"], r["ord"], r["name"]))
    n_dist = len(dist_rows)
    chart_dist = {"names": [r["name"] for r in dist_rows],
                  "yes": [r["yes"] for r in dist_rows],
                  "no": [r["no"] for r in dist_rows],
                  "na": [r["na"] for r in dist_rows]}
    tbl_dist = [{"name": r["name"], "total": n(r["total"]), "auth": n(r["auth"]),
                 "yes": n(r["yes"]), "share": pct(r["yes"] / r["total"])} for r in dist_rows]

    # ---- per authority (top-N + אחר) ---------------------------------------
    auth_rows = []
    for a, sub in df.groupby("auth", sort=True):
        y, no, na = _acc_counts(sub)
        auth_rows.append({"name": a, "total": len(sub), "yes": y, "no": no, "na": na,
                          "district": sub["district"].iloc[0]})
    auth_rows.sort(key=lambda r: (-r["total"], r["name"]))
    n_auth = len(auth_rows)
    top, rest = auth_rows[:TOP_AUTH], auth_rows[TOP_AUTH:]
    a_names = [r["name"] for r in top]
    a_yes = [r["yes"] for r in top]
    a_no = [r["no"] for r in top]
    a_na = [r["na"] for r in top]
    if rest:
        a_names.append("אחר (רשות אחת)" if len(rest) == 1 else f"אחר ({n(len(rest))} רשויות)")
        a_yes.append(sum(r["yes"] for r in rest))
        a_no.append(sum(r["no"] for r in rest))
        a_na.append(sum(r["na"] for r in rest))
    chart_auth = {"names": a_names, "yes": a_yes, "no": a_no, "na": a_na}
    tbl_auth = [{"name": nm, "total": n(y + no + na), "yes": n(y)}
                for nm, y, no, na in zip(a_names, a_yes, a_no, a_na)]
    singles = sum(1 for r in auth_rows if r["total"] == 1)

    # ---- venue type ------------------------------------------------------
    ven_rows = []
    for v, sub in df.groupby("vclass", sort=False):
        y, no, na = _acc_counts(sub)
        ven_rows.append({"name": v, "total": len(sub), "yes": y, "no": no, "na": na})
    ven_rows.sort(key=lambda r: (-r["total"], VENUE_ORDER.index(r["name"])))
    chart_venue = {"names": [r["name"] for r in ven_rows],
                   "yes": [r["yes"] for r in ven_rows],
                   "no": [r["no"] for r in ven_rows],
                   "na": [r["na"] for r in ven_rows]}
    tbl_venue = [{"name": r["name"], "total": n(r["total"]), "share": pct(r["total"] / total),
                  "yes": n(r["yes"])} for r in ven_rows]

    # ---- directory -------------------------------------------------------
    dir_full = total <= DIR_MAX_ROWS
    directory = []
    for r in dist_rows:
        sub = df[df["district"] == r["name"]]
        auths = []
        for a, asub in sub.groupby("auth", sort=True):
            entry = {"name": a, "count": stations(len(asub)), "rows": []}
            if dir_full:
                entry["rows"] = [
                    {"address": x.address, "venue": x.venue, "direction": x.direction,
                     "access": x.access,
                     "tone": "ok" if x.access == ACC_YES else ("danger" if x.access == ACC_NO else "subtle")}
                    for x in asub.itertuples()]
            auths.append(entry)
        directory.append({"name": r["name"],
                          "summary": f"{stations(r['total'])} {in_auths(r['auth'])}",
                          "auths": auths})

    # ---- KPIs ------------------------------------------------------------
    acc_share = n_yes / total if total else 0.0
    acc_tone = "ok" if acc_share >= 0.75 else ("warn" if acc_share >= 0.4 else "danger")
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "auth": {"value": n_auth, "display": n(n_auth), "tone": "brand"},
        "acc": {"value": round(acc_share * 100, 1), "display": f"{acc_share * 100:.0f}%",
                "tone": acc_tone},
        "dist": {"value": n_dist, "display": n(n_dist), "tone": "brand"},
    }

    # ---- insights --------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_district():
        if n_dist < 2:
            return None
        a, b = dist_rows[0], dist_rows[1]
        share = a["total"] / total
        if share < DISTRICT_LEAD or a["total"] == b["total"]:
            return None
        s = (f"{a['name']} מוביל עם {n(a['total'])} מתוך {n(total)} הקלפיות המיוחדות "
             f"({pct(share)}), {in_auths(a['auth'])}; אחריו {b['name']} עם {n(b['total'])}.")
        return s
    add("district", ins_district())

    def ins_access():
        if not total:
            return None
        s = f"{n(n_yes)} מתוך {n(total)} הקלפיות ({pct(acc_share)}) מסומנות כנגישות לבעלי מוגבלות"
        if has_na:
            s += f", {in_stations(n_na)} הנגישות לא צוינה"
        elig = [r for r in dist_rows if r["total"] >= DISTRICT_MIN]
        if len(elig) >= 2:
            best = sorted(elig, key=lambda r: (-r["yes"] / r["total"], -r["total"], r["name"]))[0]
            worst = sorted(elig, key=lambda r: (r["yes"] / r["total"], -r["total"], r["name"]))[0]
            bs, ws = best["yes"] / best["total"], worst["yes"] / worst["total"]
            if bs - ws >= ACCESS_GAP:
                s += (f". הפער בין המחוזות גדול: ב{best['name']} {n(best['yes'])} מתוך "
                      f"{n(best['total'])} נגישות ({pct(bs)}), וב{worst['name']} "
                      f"{n(worst['yes'])} מתוך {n(worst['total'])} ({pct(ws)})")
        return s + "."
    add("access", ins_access())

    def ins_none_accessible():
        hit = [r for r in auth_rows if r["total"] >= CLUSTER_MIN and r["yes"] == 0 and r["na"] == 0]
        if not hit:
            return None
        cnt = sum(r["total"] for r in hit)
        parts = [f"{r['name']} ({n(r['total'])})" for r in hit]
        if len(hit) == 1:
            return (f"ב{hit[0]['name']} אף אחת מ-{n(hit[0]['total'])} הקלפיות המיוחדות "
                    "אינה מסומנת כנגישה. בוחרים עם מוגבלות בניידות יכולים לבדוק את רשימת הקלפיות הנגישות.")
        return (f"ברשויות עם כמה קלפיות מיוחדות, אף אחת אינה מסומנת כנגישה ב{join_he(parts)}: "
                f"{n(cnt)} קלפיות בסך הכול.")
    add("none_acc", ins_none_accessible())

    def ins_hotels():
        h = df[df["vclass"] == HOTEL]
        if len(h) < VENUE_MIN:
            return None
        cities = h.groupby("auth").size().reset_index(name="c").sort_values(
            ["c", "auth"], ascending=[False, True], kind="mergesort")
        parts = [f"{a} ({n(c)})" if c > 1 else a for a, c in zip(cities["auth"], cities["c"])]
        return (f"{n(len(h))} מהקלפיות המיוחדות ממוקמות בבתי מלון או בלובי של מתחם אירוח, "
                f"ב{join_he(parts)}.")
    add("hotels", ins_hotels())

    def ins_venue():
        if not ven_rows:
            return None
        top_v = ven_rows[0]
        if top_v["name"] == VENUE_OTHER or top_v["total"] / total < 0.3:
            return None
        s = (f"סוג המבנה הנפוץ הוא {top_v['name']}: {stations(top_v['total'])} "
             f"({pct(top_v['total'] / total)})")
        if len(ven_rows) > 1:
            s += f", ואחריו {ven_rows[1]['name']} ({n(ven_rows[1]['total'])})"
        return s + "."
    add("venue", ins_venue())

    def ins_spread():
        if n_auth < 3 or singles / n_auth < 0.5:
            return None
        lead = auth_rows[0]
        s = (f"הקלפיות פרוסות על פני {n(n_auth)} רשויות, וב-{n(singles)} מהן יש קלפי מיוחדת אחת בלבד")
        if lead["total"] > 1:
            s += f"; הריכוז הגדול ביותר הוא ב{lead['name']}, עם {n(lead['total'])} קלפיות"
        return s + "."
    add("spread", ins_spread())

    def ins_directions():
        nd = int((df["direction"] != "").sum())
        if nd < 2:
            return None
        ne = int(df["elevator"].sum())
        s = f"ל-{n(nd)} קלפיות מצורפת הנחיית הגעה (קומה, חדר או כניסה)"
        if ne:
            s += (", ובאחת מהן נדרשת עלייה במעלית" if ne == 1
                  else f", וב-{n(ne)} מהן נדרשת עלייה במעלית")
        return s + ". ההנחיות מופיעות ברשימה למטה."
    add("directions", ins_directions())

    # ---- labels ----------------------------------------------------------
    lead_d = dist_rows[0] if dist_rows else None
    lead_a = auth_rows[0] if auth_rows else None
    if n_yes == 0:
        acc_word = "אף אחת מהן אינה מסומנת כנגישה לבעלי מוגבלות"
    elif n_yes == 1:
        acc_word = f"אחת מהן ({pct(acc_share)}) נגישה לבעלי מוגבלות"
    else:
        acc_word = f"{n(n_yes)} מהן ({pct(acc_share)}) נגישות לבעלי מוגבלות"
    labels = {
        "lede": (f"רשימת הקלפיות המיוחדות בפריסה ארצית בבחירות לרשויות המקומיות: {stations(total)} "
                 f"{in_auths(n_auth)} ו{in_dists(n_dist)}. לכל קלפי מופיעים הרשות, הכתובת, "
                 f"המבנה, הנחיות הגעה כשיש, והאם הקלפי נגישה. {acc_word}."),
        "total_kpi": "קלפיות מיוחדות ברשימה",
        "auth_kpi": "רשויות מקומיות",
        "acc_kpi": "מהקלפיות נגישות לבעלי מוגבלות",
        "dist_kpi": "מחוזות",
        "dir_note": ("הקלפיות המיוחדות לפי מחוז ורשות: כתובת, מבנה, הנחיות הגעה ונגישות."
                     if dir_full else
                     f"הרשימה כוללת {n(total)} קלפיות, יותר מדי לרשימה מלאה בעמוד. מוצג מספר הקלפיות בכל רשות; "
                     "לאיתור קלפי לפי עיר או כתובת השתמשו בחיפוש שבתחתית העמוד."),
        "dir_caption": "קלפיות מיוחדות: כתובת, מבנה, הנחיות הגעה ונגישות",
        "dist_note": ((f"{lead_d['name']} מוביל עם {stations(lead_d['total'])}. " if lead_d else "")
                      + "כל עמודה מחולקת לקלפיות נגישות ולקלפיות שאינן נגישות."),
        "dist_aria": ("גרף עמודות מוערמות: קלפיות מיוחדות לפי מחוז, נגישות ולא נגישות."
                      + (f" המוביל: {lead_d['name']} עם {n(lead_d['total'])}." if lead_d else "")),
        "dist_caption": "קלפיות מיוחדות ונגישות לפי מחוז",
        "auth_note": ((f"{lead_a['name']} מובילה עם {stations(lead_a['total'])}. " if lead_a else "")
                      + (f"מוצגות {n(TOP_AUTH)} הרשויות עם הכי הרבה קלפיות; השאר מקובצות תחת \"אחר\"."
                         if rest else "")),
        "auth_aria": ("גרף עמודות מוערמות: קלפיות מיוחדות לפי רשות מקומית, נגישות ולא נגישות."
                      + (f" המובילה: {lead_a['name']} עם {n(lead_a['total'])}." if lead_a else "")),
        "auth_caption": "קלפיות מיוחדות לפי רשות מקומית",
        "venue_note": ((f"סיווג לפי תיאור המקום בנתונים. הנפוץ: {ven_rows[0]['name']} "
                        f"({n(ven_rows[0]['total'])} מתוך {n(total)}).") if ven_rows else ""),
        "venue_aria": ("גרף עמודות מוערמות: קלפיות מיוחדות לפי סוג המבנה, נגישות ולא נגישות."
                       + (f" הנפוץ: {ven_rows[0]['name']} עם {n(ven_rows[0]['total'])}." if ven_rows else "")),
        "venue_caption": "קלפיות מיוחדות לפי סוג המבנה",
    }

    summary = (f"איתור קלפי מיוחדת בבחירות לרשויות המקומיות לפי עיר, עם כתובת, מבנה ונגישות: "
               f"{stations(total)} {in_auths(n_auth)}, {acc_share * 100:.0f}% מהן נגישות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["בחירות", "רשויות מקומיות", "קלפיות", "קלפי מיוחדת", "נגישות"],
            "related_ids": ["b5ee9460-87d7-4eb4-868a-58e35bc507b2",
                            "ebe5ec6f-3e37-4bd9-bbdc-926ad1e0d6b9"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"dist": chart_dist, "auth": chart_auth, "venue": chart_venue},
        "tables": {"dist": tbl_dist, "auth": tbl_auth, "venue": tbl_venue},
        "directory": directory,
        "flags": {"dir_full": dir_full, "has_na": has_na},
        "insights": insights,
        "labels": labels,
        "links": {"accessible": "/datasets/b5ee9460-87d7-4eb4-868a-58e35bc507b2/",
                  "managers": "/datasets/ebe5ec6f-3e37-4bd9-bbdc-926ad1e0d6b9/"},
    }
