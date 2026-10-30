"""סטארט-אפים מהדרום 2017: a Tech7 community list of Negev startups, published
by the Beer Sheva municipality.

One row per company: name, field (English category), website, foundation date,
free-text location, employee count, description, logo filename and a YouTube
link. The XLSX resource is read (the CSV twin splits multi-line descriptions
into junk rows). A one-off snapshot, but a re-upload may add companies, new
fields or new places: fields map to Hebrew with the raw label as fallback, and
places are matched by pattern to a settlement with an "unidentified" bucket.

Companies are commercial and named freely. Street addresses are not shown,
only the settlement.
"""
import re

import pandas as pd

OTHER = "אחר"
MORE_FIELDS = "תחומים נוספים"
MORE_PLACES = "יישובים נוספים"
UNKNOWN_FIELD = "לא צוין"
UNKNOWN_PLACE = "לא זוהה"
BEER_SHEVA = "באר שבע"
TOP_FIELDS = 10
TOP_PLACES = 10
TOP_EMP = 12
DIR_MAX = 80

FIELD_HE = {
    "other": "אחר",
    "mobile": "מובייל",
    "cyber": "סייבר",
    "web": "אינטרנט",
    "medical device": "מכשור רפואי",
    "software": "תוכנה",
    "adtech": "פרסום דיגיטלי",
    "gaming": "משחקים",
    "enterprise": "פתרונות לארגונים",
    "ecommerce": "מסחר מקוון",
    "virtual reality": "מציאות מדומה",
    "edtech": "טכנולוגיות חינוך",
    "agrotech": "חקלאות טכנולוגית",
    "fintech": "פינטק",
    "iot": "אינטרנט של הדברים",
    "big data": "ביג דאטה",
    "biotech": "ביוטכנולוגיה",
    "cleantech": "טכנולוגיה נקייה",
    "hardware": "חומרה",
}

# (regex on the lowercased location, settlement). First match wins, so the
# Beer Sheva industrial-park streets come before the generic rules.
PLACE_RULES = [
    (r"be'?e?r[\s\-]*she?va|באר[\s\-]*שבע|nergia|gab yam|gav[\s\-]*yam|rager|wework", BEER_SHEVA),
    (r"\bomer\b|עומר", "עומר"),
    (r"lehavim|להבים", "להבים"),
    (r"netivot|נתיבות", "נתיבות"),
    (r"yeruc?ham|ירוחם", "ירוחם"),
    (r"eilat|אילת", "אילת"),
    (r"revivim|רביבים", "רביבים"),
    (r"\berez\b|ארז", "ארז"),
    (r"nevatim|נבטים", "נבטים"),
    (r"shoval|שובל", "שובל"),
    (r"s[ae]?de?h? ?david|שדה דוד", "שדה דוד"),
    (r"dimona|דימונה", "דימונה"),
    (r"ofakim|אופקים", "אופקים"),
    (r"sderot|שדרות", "שדרות"),
    (r"arad|ערד", "ערד"),
    (r"ashkelon|אשקלון", "אשקלון"),
    (r"ashdod|אשדוד", "אשדוד"),
    (r"kiryat gat|קרית גת|קריית גת", "קריית גת"),
    (r"mitzpe ramon|מצפה רמון", "מצפה רמון"),
    (r"jerusalem|ירושלים", "ירושלים"),
    (r"tel[\s\-]*aviv|תל[\s\-]*אביב", "תל אביב"),
]
_PLACE_RX = [(re.compile(rx), name) for rx, name in PLACE_RULES]
# Settlements outside the Negev (the list is "startups from the south").
OUTSIDE_SOUTH = {"ירושלים", "תל אביב"}

EMP_BINS = [(1, 2, "1-2"), (3, 4, "3-4"), (5, 9, "5-9"), (10, None, "10+")]

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
             "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _int(v):
    return f"{int(v):,}"


def _pct(x):
    return f"{x * 100:.0f}%"


def _field_he(raw):
    s = raw.strip()
    if not s:
        return UNKNOWN_FIELD
    return FIELD_HE.get(s.lower(), s)


def _place(raw):
    s = raw.strip().lower()
    if not s:
        return UNKNOWN_PLACE
    for rx, name in _PLACE_RX:
        if rx.search(s):
            return name
    return UNKNOWN_PLACE


def _domain(url):
    s = url.strip()
    if not s:
        return ""
    s = re.sub(r"^[a-z]+://", "", s, flags=re.I)
    s = s.split("/", 1)[0].lower()
    return re.sub(r"^www\.", "", s)


def _top_with_other(counts, n, more):
    """counts: (name, value) pairs, sorted. Keeps n-1 + a `more` bucket when longer."""
    if len(counts) <= n:
        return counts
    head = counts[: n - 1]
    rest = sum(v for _, v in counts[n - 1:])
    return head + [(more, rest)]


def compute(frames):
    df = frames["companies"].copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    df = df[df["company-name"] != ""].copy()
    df = df.sort_values(["company-name", "foundation-date", "company-location"], kind="mergesort")
    df = df.drop_duplicates(subset=["company-name"], keep="first").reset_index(drop=True)

    df["field"] = df["company-field"].map(_field_he)
    df["place"] = df["company-location"].map(_place)
    df["date"] = pd.to_datetime(df["foundation-date"].str[:10], format="%Y-%m-%d", errors="coerce")
    df["year"] = df["date"].dt.year
    df["emp"] = pd.to_numeric(df["company-emp"].str.replace(",", "", regex=False), errors="coerce")
    df.loc[df["emp"] <= 0, "emp"] = float("nan")
    df["has_web"] = df["company-website"] != ""
    df["has_video"] = df["product-video"].str.contains(r"youtu", case=False, regex=True)
    df["has_logo"] = df["compay-logo"] != ""

    n = len(df)
    emp = df["emp"].dropna()
    n_emp = len(emp)
    total_emp = int(emp.sum()) if n_emp else 0
    med_emp = float(emp.median()) if n_emp else 0.0
    years = df["year"].dropna().astype(int)
    y_min = int(years.min()) if len(years) else None
    y_max = int(years.max()) if len(years) else None

    # ── fields
    fc = df.groupby("field").size().reset_index(name="n")
    fc = fc.sort_values(["n", "field"], ascending=[False, True], kind="mergesort")
    field_pairs = list(zip(fc["field"], fc["n"].astype(int)))
    fields_chart = _top_with_other(field_pairs, TOP_FIELDS, MORE_FIELDS)
    fstats = df.groupby("field").agg(n=("field", "size"), emp=("emp", "sum"),
                                     emp_n=("emp", "count"), med=("emp", "median")).reset_index()
    fstats = fstats.sort_values(["n", "field"], ascending=[False, True], kind="mergesort")
    fields_table = [{
        "name": r.field, "count": int(r.n), "share": _pct(r.n / n),
        "emp": _int(r.emp) if r.emp_n else "",
        "avg": f"{r.emp / r.emp_n:.1f}" if r.emp_n else "",
    } for r in fstats.itertuples()]

    # average size by field (fields with ≥2 companies with a headcount)
    fsize = fstats[fstats["emp_n"] >= 2].copy()
    fsize["avg"] = fsize["emp"] / fsize["emp_n"]
    fsize = fsize.sort_values(["avg", "field"], ascending=[False, True], kind="mergesort")
    size_chart = {"names": fsize["field"].tolist(),
                  "values": [round(float(v), 1) for v in fsize["avg"]],
                  "counts": fsize["emp_n"].astype(int).tolist()}

    # ── places
    pc = df.groupby("place").size().reset_index(name="n")
    pc["unk"] = pc["place"] == UNKNOWN_PLACE
    pc = pc.sort_values(["unk", "n", "place"], ascending=[True, False, True], kind="mergesort")
    place_pairs = list(zip(pc["place"], pc["n"].astype(int)))
    places_chart = _top_with_other(place_pairs, TOP_PLACES, MORE_PLACES)
    pstats = df.groupby("place").agg(n=("place", "size"), emp=("emp", "sum"),
                                     emp_n=("emp", "count")).reset_index()
    pstats["unk"] = pstats["place"] == UNKNOWN_PLACE
    pstats = pstats.sort_values(["unk", "n", "place"], ascending=[True, False, True], kind="mergesort")
    places_table = [{"name": r.place, "count": int(r.n), "share": _pct(r.n / n),
                     "emp": _int(r.emp) if r.emp_n else ""} for r in pstats.itertuples()]
    n_bs = int((df["place"] == BEER_SHEVA).sum())
    n_unk_place = int((df["place"] == UNKNOWN_PLACE).sum())
    n_outside = int(df["place"].isin(OUTSIDE_SOUTH).sum())
    n_other_negev = n - n_bs - n_unk_place - n_outside
    n_settlements = int(pc[~pc["unk"]].shape[0])
    n_negev_places = int((~pc["unk"] & (pc["place"] != BEER_SHEVA) & ~pc["place"].isin(OUTSIDE_SOUTH)).sum())

    # ── founding years (+ field mix per year)
    yc = df.dropna(subset=["year"]).copy()
    yc["year"] = yc["year"].astype(int)
    year_list = list(range(y_min, y_max + 1)) if y_min is not None else []
    by_year = yc.groupby("year").size().reindex(year_list, fill_value=0)
    years_table = [{"year": str(y), "count": int(v), "share": _pct(v / n)} for y, v in by_year.items()]
    top_field_names = [f for f, _ in field_pairs[:5]]
    yf = []
    for f in top_field_names + [MORE_FIELDS]:
        if f == MORE_FIELDS:
            sub = yc[~yc["field"].isin(top_field_names)]
        else:
            sub = yc[yc["field"] == f]
        vals = sub.groupby("year").size().reindex(year_list, fill_value=0)
        if int(vals.sum()):
            yf.append({"name": f, "data": [int(v) for v in vals]})
    years_chart = {"x": [str(y) for y in year_list], "y": [int(v) for v in by_year], "stack": yf}

    # founding month (seasonality is weak at this size; show quarter-agnostic months)
    mc = yc.groupby(yc["date"].dt.month).size().reindex(range(1, 13), fill_value=0)
    jan1 = int(((yc["date"].dt.month == 1) & (yc["date"].dt.day == 1)).sum())
    months_chart = {"x": MONTHS_HE, "y": [int(v) for v in mc]}
    months_table = [{"month": MONTHS_HE[i], "count": int(mc.iloc[i])} for i in range(12)]

    # ── employees
    bins = []
    for lo, hi, lab in EMP_BINS:
        m = (emp >= lo) if hi is None else ((emp >= lo) & (emp <= hi))
        bins.append({"label": lab, "count": int(m.sum()), "share": _pct(m.sum() / n_emp) if n_emp else ""})
    ec = df.dropna(subset=["emp"]).sort_values(["emp", "company-name"], ascending=[False, True], kind="mergesort")
    top_emp = ec.head(TOP_EMP)
    emp_chart = {"names": top_emp["company-name"].tolist(),
                 "values": [int(v) for v in top_emp["emp"]],
                 "fields": top_emp["field"].tolist()}
    emp_table = [{"name": r["company-name"], "field": r.field, "place": r.place, "emp": _int(r.emp)}
                 for _, r in top_emp.iterrows()]

    # scatter: foundation date vs headcount
    sc = df.dropna(subset=["emp", "date"]).sort_values(["date", "company-name"], kind="mergesort")
    scatter = [[r["date"].strftime("%Y-%m-%d"), int(r["emp"]), r["company-name"], r["field"]]
               for _, r in sc.iterrows()]

    # ── digital presence
    pres = [("אתר אינטרנט", int(df["has_web"].sum())),
            ("סרטון מוצר ביוטיוב", int(df["has_video"].sum())),
            ("קובץ לוגו", int(df["has_logo"].sum()))]
    pres_chart = {"names": [p for p, _ in pres], "yes": [v for _, v in pres],
                  "no": [n - v for _, v in pres]}
    pres_table = [{"name": p, "yes": v, "share": _pct(v / n)} for p, v in pres]
    n_all3 = int((df["has_web"] & df["has_video"] & df["has_logo"]).sum())

    # ── directory
    dd = df.sort_values(["company-name"], kind="mergesort")
    directory = [{
        "name": r["company-name"], "field": r.field, "place": r.place,
        "year": str(int(r.year)) if pd.notna(r.year) else "",
        "emp": _int(r.emp) if pd.notna(r.emp) else "",
        "site": _domain(r["company-website"]),
    } for _, r in dd.head(DIR_MAX).iterrows()]
    dir_truncated = n > DIR_MAX

    # ── insights
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    named = [(f, v) for f, v in field_pairs if f not in (OTHER, UNKNOWN_FIELD)]
    n_other_field = dict(field_pairs).get(OTHER, 0)

    def ins_field():
        if not named or n < 5:
            return None
        f, v = named[0]
        second = named[1][1] if len(named) > 1 else 0
        if v <= second:
            return None
        t = (f"התחום המוגדר הנפוץ ביותר הוא {f}: {_int(v)} חברות ({_pct(v / n)} מהרשימה)")
        if len(named) > 1:
            t += f", לפני {named[1][0]} עם {_int(named[1][1])}"
        t += "."
        if n_other_field:
            t += f" עוד {_int(n_other_field)} חברות סווגו תחת \"אחר\"."
        return t

    def ins_place():
        if n_bs == 0 or n < 5:
            return None
        share = n_bs / n
        if share >= 0.5:
            lead = f"{_int(n_bs)} מתוך {_int(n)} החברות ({_pct(share)}) ממוקמות בבאר שבע"
        else:
            lead = f"רק {_int(n_bs)} מתוך {_int(n)} החברות ({_pct(share)}) ממוקמות בבאר שבע"
        t = lead
        if n_other_negev > 0:
            t += f"; {_int(n_other_negev)} פועלות ביישובים אחרים בדרום"
        if n_outside:
            t += f" ו-{_int(n_outside)} מחוץ לנגב"
        t += "."
        if n_unk_place:
            t += f" אצל {_int(n_unk_place)} חברות המיקום שנרשם אינו מזהה יישוב."
        return t

    def ins_years():
        if len(years) < 5 or len(year_list) < 2:
            return None
        peak_y = int(by_year.idxmax())
        peak_v = int(by_year.max())
        if (by_year == peak_v).sum() > 1:
            return None
        t = (f"שנת השיא בהקמת חברות היא {peak_y}, עם {_int(peak_v)} חברות "
             f"({_pct(peak_v / len(years))} מבעלות תאריך הקמה).")
        early = int((years <= peak_y - 2).sum())
        if early and early < len(years) * 0.5:
            t += f" רק {_int(early)} מהחברות הוקמו עד {peak_y - 2}: רוב הרשימה צעירה."
        return t

    def ins_size():
        if n_emp < 5:
            return None
        small = int((emp <= 4).sum())
        top = ec.iloc[0]
        lead = "אלה חברות קטנות: החציון" if med_emp <= 10 else "חציון העובדים לחברה"
        t = (f"{lead} הוא {med_emp:g} עובדים, ו-{_int(small)} מתוך {_int(n_emp)} "
             f"({_pct(small / n_emp)}) מעסיקות עד ארבעה עובדים. הגדולה ברשימה היא "
             f"{top['company-name']} עם {_int(top['emp'])} עובדים.")
        return t

    def ins_field_size():
        if len(fsize) < 2 or n_emp < 5:
            return None
        cand = fsize[fsize["field"] != OTHER]
        if cand.empty:
            return None
        r = cand.iloc[0]
        overall = total_emp / n_emp
        if r["avg"] < overall * 1.2:
            return None
        return (f"חברות ה{r['field']} גדולות מהממוצע: {r['avg']:.1f} עובדים בממוצע "
                f"(על פני {_int(r['emp_n'])} חברות), לעומת {overall:.1f} בכלל הרשימה.")

    def ins_presence():
        if n < 5:
            return None
        v = pres[1][1]
        w = pres[0][1]
        return (f"{_int(w)} חברות ({_pct(w / n)}) ציינו אתר אינטרנט, ו-{_int(v)} ({_pct(v / n)}) "
                f"צירפו סרטון מוצר ביוטיוב.")

    def ins_jan1():
        if len(years) < 5 or jan1 < 3:
            return None
        share = jan1 / len(years)
        if share < 0.1:
            return None
        return (f"{_int(jan1)} חברות ({_pct(share)}) רשמו את 1 בינואר כתאריך ההקמה, "
                f"כנראה שנה משוערת בלבד, ולכן התפלגות החודשים אינה מדויקת.")

    add("field", ins_field())
    add("place", ins_place())
    add("years", ins_years())
    add("size", ins_size())
    add("field_size", ins_field_size())
    add("presence", ins_presence())
    add("jan1", ins_jan1())

    # ── KPIs
    bs_share = n_bs / n if n else 0
    kpis = {
        "companies": {"value": n, "display": _int(n), "tone": "brand"},
        "employees": {"value": total_emp, "display": _int(total_emp), "tone": "brand"},
        "median": {"value": med_emp, "display": f"{med_emp:g}", "tone": "info"},
        "fields": {"value": len(field_pairs), "display": _int(len(field_pairs)), "tone": "brand"},
        "bs_share": {"value": round(bs_share, 3), "display": _pct(bs_share),
                     "tone": "ok" if bs_share >= 0.5 else "info"},
        "settlements": {"value": n_settlements, "display": _int(n_settlements), "tone": "brand"},
        "years": {"value": y_max or 0,
                  "display": (f"{y_min}–{y_max}" if y_min is not None and y_min != y_max
                              else str(y_max or "")), "tone": "brand"},
        "video": {"value": pres[1][1], "display": _pct(pres[1][1] / n) if n else "0%", "tone": "brand"},
    }

    top_field_txt = f"{named[0][0]} ({_int(named[0][1])})" if named else ""
    summary = (f"איתור סטארט-אפים מהנגב לפי שם, תחום או יישוב: {_int(n)} חברות מרשימת Tech7, "
               f"{_pct(bs_share)} מהן בבאר שבע, עם {_int(total_emp)} עובדים בסך הכול.")

    span_txt = f"{y_min} עד {y_max}" if y_min is not None else ""
    labels = {
        "lede": (f"רשימת סטארט-אפים מהדרום (סטארטאפים בנגב) שריכזה קהילת היזמות Tech7 ופרסמה עיריית באר שבע: "
                 f"{_int(n)} חברות צעירות, עם תחום פעילות, מיקום, מועד הקמה (בין השנים {span_txt}), "
                 f"מספר עובדים, אתר וסרטון מוצר. בסך הכול הן מעסיקות {_int(total_emp)} עובדים."),
        "lookup_sub": "חיפוש חי בכל רשומות המאגר: שם החברה, תחום, מיקום, אתר אינטרנט ותיאור המוצר",
        "companies_kpi": "חברות ברשימה",
        "employees_kpi": "עובדים בסך הכול",
        "median_kpi": "חציון עובדים לחברה",
        "fields_kpi": "תחומי פעילות",
        "bs_share_kpi": "שיעור החברות בבאר שבע",
        "settlements_kpi": "יישובים מזוהים",
        "years_kpi": "שנות הקמה",
        "video_kpi": "שיעור החברות עם סרטון מוצר",
        "fields_note": (f"{len(field_pairs)} תחומים. המוביל המוגדר: {top_field_txt}. "
                        f"\"אחר\" הוא הסיווג שהחברות בחרו כשלא נמצא להן תחום מתאים."),
        "fields_aria": f"מספר חברות לפי תחום פעילות, {len(field_pairs)} תחומים",
        "size_note": ("ממוצע העובדים לחברה בכל תחום שיש בו לפחות שתי חברות עם נתון עובדים. "
                      f"הממוצע בכלל הרשימה: {(total_emp / n_emp if n_emp else 0):.1f}."),
        "size_aria": "ממוצע עובדים לחברה לפי תחום",
        "places_note": (f"{_int(n_bs)} חברות בבאר שבע ועוד {_int(n_other_negev)} ב-{_int(n_negev_places)} "
                        f"יישובים אחרים בדרום. המיקום נגזר מהכתובת החופשית שהחברות מסרו."),
        "places_aria": f"מספר חברות לפי יישוב, {n_settlements} יישובים מזוהים",
        "years_note": (f"שנת ההקמה של כל חברה, {span_txt}, בפילוח לחמשת התחומים הנפוצים."),
        "years_aria": f"מספר חברות לפי שנת הקמה, {span_txt}",
        "months_note": (f"חודש ההקמה המדווח. {_int(jan1)} חברות רשמו 1 בינואר, לרוב תאריך משוער."),
        "months_aria": "מספר חברות לפי חודש הקמה",
        "bins_note": (f"מספר העובדים שדיווחה כל חברה ({_int(n_emp)} חברות עם נתון). "
                      f"החציון: {med_emp:g} עובדים."),
        "bins_aria": "התפלגות החברות לפי מספר עובדים",
        "emp_note": f"{len(emp_chart['names'])} החברות עם מספר העובדים הגבוה ברשימה.",
        "emp_aria": "החברות הגדולות ברשימה לפי מספר עובדים",
        "scatter_note": "כל נקודה היא חברה: מועד ההקמה מול מספר העובדים. החברות הוותיקות אינן בהכרח הגדולות.",
        "scatter_aria": "מועד הקמה מול מספר עובדים לכל חברה",
        "pres_note": (f"כמה חברות צירפו אתר, סרטון ולוגו. {_int(n_all3)} חברות צירפו את שלושתם."),
        "pres_aria": "נוכחות דיגיטלית: אתר, סרטון ולוגו",
        "dir_note": (f"כל {_int(n)} החברות לפי סדר אלפביתי." if not dir_truncated
                     else f"{_int(DIR_MAX)} החברות הראשונות לפי סדר אלפביתי מתוך {_int(n)}; השאר בטבלת הנתונים המלאה."),
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["סטארט-אפים", "יזמות", "באר שבע", "נגב", "הייטק"],
            "related_ids": ["54b65747-904e-42e1-9316-0575ebbc1216", "fffada0a-b021-4629-9244-bc5e301f23d5"],
            **({"temporal_coverage": f"{y_min}/{y_max}"} if y_min is not None else {}),
            "spatial_coverage": "באר שבע והנגב",
        },
        "kpis": kpis,
        "charts": {
            "fields": {"names": [a for a, _ in fields_chart], "values": [int(b) for _, b in fields_chart]},
            "size": size_chart,
            "places": {"names": [a for a, _ in places_chart], "values": [int(b) for _, b in places_chart]},
            "years": years_chart,
            "months": months_chart,
            "bins": {"names": [b["label"] for b in bins], "values": [b["count"] for b in bins]},
            "emp": emp_chart,
            "scatter": scatter,
            "pres": pres_chart,
        },
        "tables": {
            "fields": fields_table,
            "size": [{"name": a, "avg": f"{b:.1f}", "n": c} for a, b, c in
                     zip(size_chart["names"], size_chart["values"], size_chart["counts"])],
            "places": places_table,
            "years": years_table,
            "months": months_table,
            "bins": bins,
            "emp": emp_table,
            "pres": pres_table,
            "directory": directory,
        },
        "insights": insights,
        "labels": labels,
    }
