"""רשימת תחנות הידרומטריות: the Hydrological Service's registry of stream
gauging stations, active and closed, one row per station.

The registry is a slowly changing list: a new station is added now and then and
the status column flips when a station closes or reopens. Every count, share,
leader and year below is computed from the current file.

Conventions found in the data and handled here:
- Founding dates are mostly 01/10/YYYY: the start of the hydrological year,
  so they usually mean "founded in water year YYYY". The share is computed and
  stated, not assumed.
- Catchment area uses 99999 as a placeholder for "unknown" (SENTINEL_AREA and
  above). Those values, blanks and non-numeric entries are excluded from every
  area figure, and the page says how many.
- Coordinates are ITM (EPSG:2039). Values outside the Israel ITM box are
  ignored for the north-south profile; the map (GovMap) reads them directly.
- Status: "פעילה" counts as active; every other non-empty value is shown under
  its own name, blanks under UNKNOWN.
"""
import pandas as pd

ID = "זיהוי תחנה"
NAME = "שם עברית"
FOUNDED = "תאריך הקמה"
AREA = "שטח היקוות (קמ''ר)"
SHARED = "שטח משותף"
X = "נ.צ. X (רוחב)"
Y = "נ.צ. Y (רוחב)"
GROUP = "מספר קבוצה"
BASIN = "תחום התנקזות של נחל ראשי"
STATUS = "סטטוס תחנה נוכחי"

ACTIVE = "פעילה"
INACTIVE = "לא פעילה"
UNKNOWN = "לא ידוע"
NO_BASIN = "ללא תחום התנקזות"
OTHER = "אחר"
YES = "כן"

TOP_BASINS = 15
SHARE_MIN_STATIONS = 10       # basins compared on active share need this many stations
SHARE_GAP_PP = 0.25           # best vs worst basin active share gap worth stating
ERA_OLD_END = 1969            # "founded up to" for the early-network group
ERA_NEW_START = 2000          # "founded from" for the modern group
ERA_MIN = 10                  # stations needed in each era group
ERA_GAP_PP = 0.15
WATER_YEAR_MIN = 0.5          # share of 01/10 dates needed to state the convention
TOP_AREA = 10
NEWEST_N = 8
BAND_KM = 50
SENTINEL_AREA = 99999
ITM_X = (100_000, 300_000)
ITM_Y = (350_000, 820_000)
AREA_BINS = [(0, 10), (10, 50), (50, 100), (100, 500), (500, 1000), (1000, 5000), (5000, None)]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _num(s):
    s = s.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(s, errors="coerce")


def _status_order(values):
    """Active first, inactive second, everything else alphabetically, unknown last."""
    vals = set(values)
    head = [v for v in (ACTIVE, INACTIVE) if v in vals]
    rest = sorted(v for v in vals if v not in (ACTIVE, INACTIVE, UNKNOWN))
    tail = [UNKNOWN] if UNKNOWN in vals else []
    return head + rest + tail


def _area_label(lo, hi):
    if hi is None:
        return f"{lo:,} ומעלה"
    return f"{lo:,}-{hi:,}"


def compute(frames):
    df = frames["main"].copy()
    for c in (ID, NAME, FOUNDED, AREA, SHARED, X, Y, GROUP, BASIN, STATUS):
        df[c] = df[c].astype(str).str.strip()
    df = df[(df[ID] != "") | (df[NAME] != "")].copy()
    # Legacy double-apostrophe gershayim (ע''י) -> proper gershayim for display.
    for c in (NAME, BASIN):
        df[c] = df[c].str.replace("''", "\u05f4", regex=False)
    df = df.sort_values([ID, NAME], kind="mergesort").reset_index(drop=True)

    n = len(df)
    df["status"] = df[STATUS].where(df[STATUS] != "", UNKNOWN)
    df["active"] = df["status"] == ACTIVE
    statuses = _status_order(df["status"].unique())
    n_active = int(df["active"].sum())
    n_inactive = int((df["status"] == INACTIVE).sum())
    active_share = n_active / n if n else 0.0

    df["basin"] = df[BASIN].where(df[BASIN] != "", NO_BASIN)
    df["date"] = pd.to_datetime(df[FOUNDED], format="%d/%m/%Y", errors="coerce")
    df["year"] = df["date"].dt.year
    area_raw = _num(df[AREA])
    df["area"] = area_raw.where((area_raw >= 0) & (area_raw < SENTINEL_AREA))
    n_sentinel = int((area_raw >= SENTINEL_AREA).sum())
    df["x"] = _num(df[X])
    df["y"] = _num(df[Y])
    in_box = df["x"].between(*ITM_X) & df["y"].between(*ITM_Y)

    def by_status(sub):
        vc = sub["status"].value_counts()
        return [int(vc.get(s, 0)) for s in statuses]

    # ---- founding decades ---------------------------------------------------
    dated = df[df["year"].notna()].copy()
    dated["decade"] = (dated["year"] // 10 * 10).astype(int)
    decades = sorted(dated["decade"].unique())
    t_decade, dec_share = [], []
    for d in decades:
        sub = dated[dated["decade"] == d]
        cells = by_status(sub)
        sh = float(sub["active"].mean()) if len(sub) else 0.0
        dec_share.append(round(sh * 100, 1))
        t_decade.append({"name": f"{d}-{d + 9}", "total": _int(len(sub)),
                         "cells": [_int(v) for v in cells], "share": _pct(sh)})
    chart_decade = {
        "x": [f"{d}-{d + 9}" for d in decades],
        "series": [{"name": s, "data": [int((dated[dated["decade"] == d]["status"] == s).sum())
                                        for d in decades]} for s in statuses],
        "share": dec_share,
    }
    first_year = int(dated["year"].min()) if len(dated) else None
    last_year = int(dated["year"].max()) if len(dated) else None
    n_undated = n - len(dated)

    # ---- basins -------------------------------------------------------------
    b_cnt = df["basin"].value_counts()
    b_rank = sorted(b_cnt.index, key=lambda b: (-int(b_cnt[b]), b == NO_BASIN, b))
    top_b = [b for b in b_rank if b != NO_BASIN][:TOP_BASINS]
    rest_mask = ~df["basin"].isin(top_b)
    rows_b = [(b, df[df["basin"] == b]) for b in top_b]
    if rest_mask.any():
        rows_b.append((OTHER, df[rest_mask]))
    n_basins = int((df["basin"] != NO_BASIN).groupby(df["basin"]).any().sum())
    chart_basins = {
        "names": [r[0] for r in rows_b],
        "series": [{"name": s, "data": [int((sub["status"] == s).sum()) for _, sub in rows_b]}
                   for s in statuses],
    }
    t_basins = [{"name": name, "total": _int(len(sub)),
                 "cells": [_int(v) for v in by_status(sub)],
                 "share": _pct(float(sub["active"].mean()) if len(sub) else 0.0)}
                for name, sub in rows_b]
    n_rest_basins = int(df.loc[rest_mask & (df["basin"] != NO_BASIN), "basin"].nunique())

    # Active share among basins with enough stations.
    big = [b for b in b_rank if b != NO_BASIN and int(b_cnt[b]) >= SHARE_MIN_STATIONS]
    sh_rows = []
    for b in big:
        sub = df[df["basin"] == b]
        sh_rows.append((b, float(sub["active"].mean()), int(sub["active"].sum()), len(sub)))
    sh_rows.sort(key=lambda r: (-r[1], -r[3], r[0]))
    chart_bshare = {"names": [r[0] for r in sh_rows],
                    "values": [round(r[1] * 100, 1) for r in sh_rows],
                    "active": [r[2] for r in sh_rows],
                    "total": [r[3] for r in sh_rows]}
    t_bshare = [{"name": r[0], "active": _int(r[2]), "total": _int(r[3]), "share": _pct(r[1])}
                for r in sh_rows]

    # ---- north-south bands ----------------------------------------------------
    geo = df[in_box].copy()
    geo["band"] = (geo["y"] // (BAND_KM * 1000)).astype(int)
    bands = sorted(geo["band"].unique(), reverse=True)
    t_ns, ns_labels = [], []
    for b in bands:
        sub = geo[geo["band"] == b]
        bc = sub.loc[sub["basin"] != NO_BASIN, "basin"].value_counts()
        tops = sorted(bc.index, key=lambda k: (-int(bc[k]), k))[:2]
        lab = f"{b * BAND_KM}-{(b + 1) * BAND_KM}"
        if tops:
            lab += f" ({', '.join(tops)})"
        ns_labels.append(lab)
        t_ns.append({"name": lab, "total": _int(len(sub)),
                     "cells": [_int(v) for v in by_status(sub)],
                     "share": _pct(float(sub["active"].mean()) if len(sub) else 0.0)})
    chart_ns = {"names": ns_labels,
                "series": [{"name": s, "data": [int((geo[geo["band"] == b]["status"] == s).sum())
                                                for b in bands]} for s in statuses]}
    n_nogeo = n - len(geo)

    # ---- catchment area ---------------------------------------------------------
    ar = df[df["area"].notna()].copy()
    t_area, area_names = [], []
    area_series = {s: [] for s in statuses}
    for lo, hi in AREA_BINS:
        m = ar["area"] >= lo
        if hi is not None:
            m &= ar["area"] < hi
        sub = ar[m]
        lab = _area_label(lo, hi)
        area_names.append(lab)
        cells = by_status(sub)
        for s, v in zip(statuses, cells):
            area_series[s].append(v)
        t_area.append({"name": lab, "total": _int(len(sub)), "cells": [_int(v) for v in cells],
                       "share": _pct(float(sub["active"].mean()) if len(sub) else 0.0)})
    chart_area = {"names": area_names,
                  "series": [{"name": s, "data": area_series[s]} for s in statuses]}
    n_area = len(ar)
    n_noarea = n - n_area
    med_area = float(ar["area"].median()) if n_area else None
    med_act = float(ar.loc[ar["active"], "area"].median()) if ar["active"].any() else None
    med_inact = float(ar.loc[~ar["active"], "area"].median()) if (~ar["active"]).any() else None

    top_area = ar.sort_values(["area", ID], ascending=[False, True], kind="mergesort").head(TOP_AREA)
    chart_toparea = {"names": top_area[NAME].tolist(),
                     "values": [int(round(v)) for v in top_area["area"]],
                     "active": top_area["active"].tolist(),
                     "status": top_area["status"].tolist()}
    t_toparea = [{"name": r[NAME], "basin": r["basin"], "area": _int(round(r["area"])),
                  "status": r["status"]} for _, r in top_area.iterrows()]

    # ---- shared catchments, groups, newest ---------------------------------------
    n_shared = int((df[SHARED] == YES).sum())
    shared_active = int(((df[SHARED] == YES) & df["active"]).sum())
    grp = df[df[GROUP] != ""]
    g_sizes = grp.groupby(GROUP).size()
    multi = g_sizes[g_sizes >= 2]
    n_groups = int(len(multi))
    n_in_groups = int(multi.sum())

    newest = dated.sort_values(["date", ID], ascending=[False, True], kind="mergesort").head(NEWEST_N)
    t_newest = [{"name": r[NAME], "basin": r["basin"], "date": r["date"].strftime("%m/%Y"),
                 "status": r["status"]} for _, r in newest.iterrows()]

    water_year = float((dated["date"].dt.strftime("%d/%m") == "01/10").mean()) if len(dated) else 0.0

    # ---- insights ---------------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if n:
        add("active", f"{_int(n_active)} מתוך {_int(n)} התחנות ברשימה ({_pct(active_share)}) פעילות כיום; "
                      f"{_int(n_inactive)} אינן פעילות עוד.")

    if len(dated):
        old = dated[dated["year"] <= ERA_OLD_END]
        new = dated[dated["year"] >= ERA_NEW_START]
        if len(old) >= ERA_MIN and len(new) >= ERA_MIN:
            so, sn = float(old["active"].mean()), float(new["active"].mean())
            if abs(sn - so) >= ERA_GAP_PP:
                more = "גבוה" if sn > so else "נמוך"
                add("era", f"מבין {_int(len(old))} התחנות שהוקמו עד {ERA_OLD_END} רק {_pct(so)} פעילות כיום, "
                           f"לעומת {_pct(sn)} מבין {_int(len(new))} התחנות שהוקמו מ-{ERA_NEW_START} ואילך: "
                           f"שיעור פעילות {more} בהרבה ברשת החדשה.")
        dc = dated["decade"].value_counts()
        peak = sorted(dc.index, key=lambda d: (-int(dc[d]), d))[0]
        add("peak_decade", f"עשור ההקמה העמוס ביותר הוא {peak}-{peak + 9}, עם {_int(dc[peak])} תחנות "
                           f"({_pct(dc[peak] / len(dated))} מהתחנות שתאריך הקמתן ידוע); "
                           f"הוותיקה ביותר הוקמה ב-{first_year}.")

    if len(top_b):
        lead = top_b[0]
        lead_act = df.loc[df["basin"] != NO_BASIN].groupby("basin")["active"].sum()
        act_lead = sorted(lead_act.index, key=lambda b: (-int(lead_act[b]), b))[0]
        txt = (f"אגן {lead} מרכז את מספר התחנות הגדול ביותר: {_int(b_cnt[lead])} "
               f"({_pct(b_cnt[lead] / n)} מהרשימה).")
        if act_lead != lead and int(lead_act[act_lead]) > 0:
            txt += f" במספר התחנות הפעילות מוביל דווקא אגן {act_lead}, עם {_int(lead_act[act_lead])}."
        elif int(lead_act[lead]) > 0:
            txt += f" הוא מוביל גם בתחנות פעילות, עם {_int(lead_act[lead])}."
        add("basin_lead", txt)

    if len(sh_rows) >= 3:
        hi_r, lo_r = sh_rows[0], sh_rows[-1]
        if hi_r[1] - lo_r[1] >= SHARE_GAP_PP:
            add("basin_share", f"בין האגנים שבהם לפחות {SHARE_MIN_STATIONS} תחנות, שיעור הפעילות הגבוה ביותר "
                               f"הוא באגן {hi_r[0]} ({_pct(hi_r[1])}, {hi_r[2]} מתוך {hi_r[3]}) והנמוך ביותר "
                               f"באגן {lo_r[0]} ({_pct(lo_r[1])}, {lo_r[2]} מתוך {lo_r[3]}).")

    if len(top_area):
        r = top_area.iloc[0]
        txt = (f"אגן ההיקוות הגדול ביותר נמדד בתחנה \"{r[NAME]}\": {_int(round(r['area']))} קמ\"ר "
               f"(התחנה {r['status']}).")
        if med_act is not None and med_inact is not None:
            txt += (f" חציון שטח ההיקוות הוא {_int(round(med_act))} קמ\"ר בתחנות הפעילות "
                    f"ו-{_int(round(med_inact))} קמ\"ר בשאר.")
        if n_noarea:
            txt += f" ל-{_int(n_noarea)} תחנות אין שטח היקוות תקין ברשימה"
            txt += f" (מהן {_int(n_sentinel)} עם ערך {SENTINEL_AREA}), והן לא נכללו." if n_sentinel else ", והן לא נכללו."
        add("area", txt)

    if len(t_newest):
        r = newest.iloc[0]
        recent = dated[dated["year"] >= ERA_NEW_START]
        txt = f"התחנה החדשה ביותר ברשימה היא \"{r[NAME]}\" (אגן {r['basin']}), שהוקמה ב-{r['date'].strftime('%m/%Y')}"
        if len(recent):
            txt += f"; מאז {ERA_NEW_START} נוספו {_int(len(recent))} תחנות, {_int(recent['active'].sum())} מהן פעילות כיום."
        else:
            txt += "."
        add("newest", txt)

    if water_year >= WATER_YEAR_MIN:
        add("water_year", f"{_pct(water_year)} מתאריכי ההקמה רשומים כ-1 באוקטובר, תחילת שנת המים ההידרולוגית, "
                          f"כך שברוב המקרים התאריך מציין את שנת ההקמה ולא יום מדויק.")

    if n_groups:
        gb = grp[grp[GROUP].isin(multi.index)].groupby(GROUP)["basin"].nunique()
        same = int((gb == 1).sum())
        tail = ("כל קבוצה נמצאת כולה בתוך תחום התנקזות אחד." if same == n_groups else
                f"{_int(same)} מהקבוצות נמצאות כולן בתוך תחום התנקזות אחד.")
        add("groups", f"{_int(n_in_groups)} תחנות משויכות ל-{_int(n_groups)} קבוצות (מספר קבוצה משותף); {tail}")

    if n_shared:
        add("shared", f"{_int(n_shared)} תחנות מסומנות בעלות שטח היקוות משותף, {_int(shared_active)} מהן פעילות כיום.")

    # ---- KPIs, labels -----------------------------------------------------------
    span = f"{first_year}–{last_year}" if first_year is not None else "–"
    kpis = {
        "total": {"value": n, "display": _int(n), "tone": "brand"},
        "active": {"value": n_active, "display": _int(n_active), "tone": "ok" if n_active else "danger"},
        "share": {"value": round(active_share, 4), "display": _pct(active_share),
                  "tone": "brand"},
        "basins": {"value": n_basins, "display": _int(n_basins), "tone": "brand"},
        "span": {"value": first_year, "display": span, "tone": "info"},
        "median_area": {"value": med_area, "display": _int(round(med_area)) if med_area is not None else "–",
                        "tone": "brand"},
    }

    oldest_txt = f", הוותיקה שבהן מ-{first_year}" if first_year is not None else ""
    summary = (f"איתור תחנות הידרומטריות של השירות ההידרולוגי לפי שם, מספר ואגן ניקוז: "
               f"{_int(n)} תחנות, {_int(n_active)} פעילות כיום{oldest_txt}.")

    labels = {
        "lede": (f"הרשימה כוללת {_int(n)} תחנות מדידה הידרומטריות (תחנות ספיקה ומפלס בנחלים) של השירות ההידרולוגי "
                 f"ברשות המים, ב-{_int(n_basins)} תחומי התנקזות. {_int(n_active)} מהן ({_pct(active_share)}) "
                 f"פעילות כיום; תאריכי ההקמה משתרעים בין {first_year} ל-{last_year}. "
                 f"מתחת לעמוד אפשר לחפש כל תחנה לפי שמה, מספרה או הנחל."
                 if first_year is not None else
                 f"הרשימה כוללת {_int(n)} תחנות מדידה הידרומטריות של השירות ההידרולוגי, "
                 f"{_int(n_active)} מהן פעילות כיום."),
        "share_kpi": "מהתחנות פעילות כיום",
        "median_area_kpi": f"חציון שטח היקוות (קמ\"ר, {_int(n_area)} תחנות)",
        "map_note": (f"כל נקודה היא תחנה; לחיצה מציגה את שמה, מספרה, האגן, הסטטוס ותאריך ההקמה. "
                     f"התחנות נטענות ישירות מהמאגר, ותחנות ללא נקודת ציון אינן מוצגות."),
        "decade_note": (f"תחנות לפי עשור ההקמה, מפוצלות לפי הסטטוס הנוכחי; הקו מציג איזה שיעור מתחנות כל עשור "
                        f"פעיל כיום." + (f" ל-{_int(n_undated)} תחנות אין תאריך הקמה תקין." if n_undated else "")),
        "decade_aria": (f"תרשים עמודות מוערם וקו: תחנות לפי עשור הקמה ושיעור הפעילות בכל עשור, "
                        f"{len(decades)} עשורים, מ-{first_year} עד {last_year}."
                        if first_year is not None else "תרשים עמודות: תחנות לפי עשור הקמה."),
        "decade_caption": "תחנות לפי עשור הקמה וסטטוס נוכחי, ושיעור הפעילות.",
        "basins_note": (f"{len(top_b)} תחומי ההתנקזות עם מספר התחנות הגדול ביותר"
                        + (f"; {_int(n_rest_basins)} תחומים נוספים ותחנות ללא תחום מקובצים תחת \"{OTHER}\"."
                           if rest_mask.any() else ".")),
        "basins_aria": (f"תרשים עמודות אופקי מוערם: תחנות לפי תחום התנקזות וסטטוס. "
                        f"המוביל: {top_b[0]} עם {_int(b_cnt[top_b[0]])} תחנות." if top_b else
                        "תרשים עמודות אופקי מוערם: תחנות לפי תחום התנקזות וסטטוס."),
        "basins_caption": "תחנות לפי תחום התנקזות וסטטוס נוכחי.",
        "bshare_note": (f"איזה חלק מהתחנות שהוקמו בכל אגן עדיין פעיל; רק אגנים שבהם לפחות "
                        f"{SHARE_MIN_STATIONS} תחנות ({len(sh_rows)} אגנים)."),
        "bshare_aria": (f"תרשים עמודות: שיעור התחנות הפעילות לפי אגן, {len(sh_rows)} אגנים. "
                        f"הגבוה: {sh_rows[0][0]} ({_pct(sh_rows[0][1])})." if sh_rows else
                        "תרשים עמודות: שיעור התחנות הפעילות לפי אגן."),
        "bshare_caption": "שיעור התחנות הפעילות לפי אגן.",
        "ns_note": (f"הארץ חולקה לרצועות של {BAND_KM} ק\"מ מצפון לדרום לפי נקודת הציון (רשת ישראל החדשה, ק\"מ צפונה); "
                    f"בסוגריים האגנים הנפוצים ברצועה."
                    + (f" {_int(n_nogeo)} תחנות ללא נקודת ציון תקינה לא נכללו." if n_nogeo else "")),
        "ns_aria": (f"תרשים עמודות אופקי מוערם: תחנות לפי רצועות של {BAND_KM} ק\"מ מצפון לדרום וסטטוס, "
                    f"{len(bands)} רצועות."),
        "ns_caption": f"תחנות לפי רצועה של {BAND_KM} ק\"מ מצפון לדרום וסטטוס נוכחי.",
        "area_note": (f"התפלגות שטח ההיקוות שמעל כל תחנה, בקמ\"ר: מנחלים קטנים ועד הירדן. "
                      f"{_int(n_area)} תחנות עם ערך תקין"
                      + (f"; {_int(n_noarea)} ללא ערך" + (f" או עם ערך {SENTINEL_AREA}" if n_sentinel else "")
                         + " לא נכללו." if n_noarea else ".")),
        "area_aria": (f"תרשים עמודות מוערם: תחנות לפי טווח שטח היקוות וסטטוס, {_int(n_area)} תחנות"
                      + (f", חציון {_int(round(med_area))} קמ\"ר." if med_area is not None else ".")),
        "area_caption": "תחנות לפי טווח שטח היקוות (קמ\"ר) וסטטוס נוכחי.",
        "toparea_note": f"{len(top_area)} התחנות עם שטח ההיקוות הגדול ביותר; עמודה כהה מסמנת תחנה פעילה.",
        "toparea_aria": (f"תרשים עמודות אופקי: {len(top_area)} התחנות עם שטח ההיקוות הגדול ביותר. "
                         f"המובילה: {top_area.iloc[0][NAME]} ({_int(round(top_area.iloc[0]['area']))} קמ\"ר)."
                         if len(top_area) else "תרשים עמודות אופקי: התחנות עם שטח ההיקוות הגדול ביותר."),
        "toparea_caption": "התחנות עם שטח ההיקוות הגדול ביותר.",
        "newest_note": f"{len(t_newest)} התחנות שהוקמו לאחרונה, לפי תאריך ההקמה הרשום.",
        "newest_caption": "התחנות שהוקמו לאחרונה.",
        "shared_kpi": "תחנות עם שטח היקוות משותף",
    }
    n_recent = int((dated["year"] >= ERA_NEW_START).sum()) if len(dated) else 0
    kpis["recent"] = {"value": n_recent, "display": _int(n_recent), "tone": "brand"}
    labels["recent_kpi"] = f"תחנות שהוקמו מ-{ERA_NEW_START} ואילך"
    kpis["shared"] = {"value": n_shared, "display": _int(n_shared), "tone": "info" if n_shared else "brand"}

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["הידרולוגיה", "תחנות מדידה", "נחלים", "רשות המים", "ספיקה"],
            "related_ids": ["e81d14bd-a81d-4de4-b1de-d7a0541ace02",
                            "f72117a6-2b71-43e9-bc81-75c284a4d1e2",
                            "d16214ba-56b3-417d-9342-6a144f215b9b",
                            "15072295-27ab-4939-951b-de462adc0ab0",
                            "87514149-a73c-424d-89b4-80d3c9058f7a"],
            "temporal_coverage": f"{first_year}/{last_year}" if first_year is not None else None,
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "decade": chart_decade,
            "basins": chart_basins,
            "bshare": chart_bshare,
            "ns": chart_ns,
            "area": chart_area,
            "toparea": chart_toparea,
        },
        "tables": {
            "statuses": statuses,
            "decade": t_decade,
            "basins": t_basins,
            "bshare": t_bshare,
            "ns": t_ns,
            "area": t_area,
            "toparea": t_toparea,
            "newest": t_newest,
        },
        "flags": {"bshare": len(sh_rows) >= 2, "toparea": len(top_area) > 0,
                  "ns": len(bands) > 0, "newest": len(t_newest) > 0},
        "fields": {"area": AREA},
        "insights": insights,
        "labels": labels,
    }
