"""מוסדות חינוך: the Ministry of Education's list of active recognised
education institutions (kindergartens, day-care centres, schools and other
frameworks), one row per institution with its ITM point.

Columns: institution symbol (SEMEL_MOSAD) and name, locality and local
authority, framework type, population sector, supervision stream (ממלכתי /
ממלכתי דתי / חרדי), legal status (רשמי / מוכר שאיננו רשמי / …), regular or
special education, the supervising district/unit, gender composition, the
education stage (code + label), and three geocoding-quality fields.

The file is a full snapshot (no time column), so everything is a count over
the current list. "NULL" and empty cells read as "לא צוין". Institutions are
grouped by the stage code: 8 = kindergarten, 1-7 = a school stage, anything
else is a day-care centre (type name contains "מעון"/"משפחתון") or "other".
Day-care rows carry "בנות" as their gender composition (a registry default),
so gender is analysed for schools only.
"""
import pandas as pd
from govlib import fmt, frame

UNKNOWN = "לא צוין"
G_GAN = "גני ילדים"
G_SCHOOL = "בתי ספר"
G_MAON = "מעונות יום"
G_OTHER = "מסגרות אחרות"
GROUPS = [G_GAN, G_SCHOOL, G_MAON, G_OTHER]

HAREDI = "חרדי"
STATE = "ממלכתי"
SPECIAL = "מיוחד"
ACC_ORDER = ["גבוהה מאוד", "גבוהה", "בינונית", "נמוכה"]
LOW_ACC = {"בינונית", "נמוכה"}
MIXED = "מעורב"

TOP_TYPES = 12        # framework-type bars before "אחר"
TOP_DISTRICTS = 12    # district/unit bars before "אחר"
TOP_LOCALITIES = 15   # locality rows in the stacked chart
TOP_REASONS = 10      # geocoding-reason rows before "אחר"
MIN_GROUP = 50        # a stream/sector/group needs this many rows for a comparison
GAP_PTS = 0.20        # a share gap must be at least this (fraction) to be called out
LEAD_GROUP = 0.40     # largest group "dominates" above this share
CITY_LEAD = 0.05      # top locality worth an insight above this share
HAREDI_MAJORITY = 0.50
LOW_ACC_WARN = 0.10   # KPI tone: warn at or above this share placed at low accuracy
LOW_ACC_OK = 0.05     # ... ok below this
SECTOR_GAP = 1.5      # a sector's low-accuracy share must be ≥ this × the overall
ITM_X = (100_000, 300_000)
ITM_Y = (350_000, 820_000)

COLS = {
    "semel": "SEMEL_MOSAD",
    "name": "SHEM_MOSAD",
    "locality": "ISV_SHEM_ISHUV",
    "authority": "SHEM_RASHUT",
    "type": "TEUR_TAT_SUG_MISGERET",
    "sector": "TEUR_MIGZAR",
    "stream": "TEUR_PIKOH1",
    "legal": "TEUR_MAMAD",
    "edtype": "TEUR_SUG_CHINUCH",
    "district": "SHEM_MAHUZ",
    "gender": "TEUR_HERKEV_UCHLOSIYA",
    "stage_code": "SHLAV_CHINUH",
    "stage": "TEUR_SHLAV_HINUH",
    "geo_method": "TEUR_STATUS_GEOCODE",
    "geo_reason": "TEUR_SIBAT_STATUS",
    "accuracy": "RAMAT_DIYUK_MIKUM",
}


def _group(row_code, type_name):
    if row_code == 8:
        return G_GAN
    if 1 <= row_code <= 7:
        return G_SCHOOL
    if "מעון" in type_name or "משפחתון" in type_name:
        return G_MAON
    return G_OTHER


def _prepare(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({k: frame.clean_series(raw[c]) for k, c in COLS.items()})
    df = df[(df["semel"] != "") | (df["name"] != "")].copy()
    for k in COLS:
        if k in ("semel", "name", "stage_code"):
            continue
        df.loc[df[k].isin(["", "NULL", "null"]), k] = UNKNOWN
    df["code"] = pd.to_numeric(df["stage_code"], errors="coerce").fillna(-1).astype(int)
    df["group"] = [_group(c, t) for c, t in zip(df["code"], df["type"])]
    df["x"] = frame.num(raw.loc[df.index, "X"])
    df["y"] = frame.num(raw.loc[df.index, "Y"])
    df["mapped"] = df["x"].between(*ITM_X) & df["y"].between(*ITM_Y)
    df["semel_num"] = pd.to_numeric(df["semel"], errors="coerce")
    return df.sort_values(["semel_num", "semel", "name"], kind="stable",
                          na_position="last").reset_index(drop=True)


def _kpi(value, display, tone="brand"):
    return {"value": value, "display": display, "tone": tone}


def _order_known(counts, known_order):
    """known_order first (those present), then the rest by count; unknown last."""
    present = [k for k in known_order if k in counts.index]
    rest = [k for k in counts.index if k not in present and k != UNKNOWN]
    tail = [UNKNOWN] if UNKNOWN in counts.index else []
    return present + rest + tail


def _ranked_known_last(series):
    c = frame.ranked(series)
    order = [k for k in c.index if k != UNKNOWN] + ([UNKNOWN] if UNKNOWN in c.index else [])
    return c.reindex(order)


def _rank_rows(counts, total, n):
    labels, values = frame.top_other(counts, n)
    rows = [[lab, fmt.int_he(v), fmt.pct(v / total)] for lab, v in zip(labels, values)]
    return {"names": labels, "values": values}, rows


def _crosstab(df, row, row_order, col, col_order):
    ct = pd.crosstab(df[row], df[col]).reindex(index=row_order, columns=col_order, fill_value=0)
    series = [{"name": c, "data": [int(v) for v in ct[c].tolist()]} for c in col_order]
    rows = [[r] + [fmt.int_he(v) for v in ct.loc[r].tolist()] + [fmt.int_he(ct.loc[r].sum())]
            for r in row_order]
    return ct, {"names": list(row_order), "series": series}, {"cols": list(col_order), "rows": rows}


def _share(num, den):
    return num / den if den else 0.0


# ---------------------------------------------------------------- insights

def _ins_groups(group_counts, total):
    g, v = group_counts.index[0], int(group_counts.iloc[0])
    if v / total < LEAD_GROUP:
        return None
    rest = [f"{fmt.int_he(int(group_counts[k]))} {k}" for k in group_counts.index[1:]
            if int(group_counts[k]) > 0]
    tail = f" לצדם ברשימה {fmt.join_he(rest)}." if rest else ""
    lead = "רוב מוסדות החינוך ברשימה" if v / total > 0.5 else "הקבוצה הגדולה ברשימה"
    return (f"{g} הם {lead}: {fmt.int_he(v)} מתוך {fmt.int_he(total)} "
            f"({fmt.pct(v / total, 0)}).{tail}")


def _ins_legal(df):
    h = df[df["stream"] == HAREDI]
    s = df[df["stream"] == STATE]
    if len(h) < MIN_GROUP or len(s) < MIN_GROUP:
        return None
    official = "רשמי"
    h_off = _share(int((h["legal"] == official).sum()), len(h))
    s_off = _share(int((s["legal"] == official).sum()), len(s))
    if s_off - h_off < GAP_PTS:
        return None
    h_other = _share(int(((h["legal"] != official) & (h["legal"] != UNKNOWN)).sum()), len(h))
    tail = (" רוב המוסדות החרדיים הם מוכרים שאינם רשמיים, פטורים או מוסדות תרבותיים-ייחודיים."
            if h_other > 0.5 else "")
    return (f"רק {fmt.pct(h_off, 0)} מ-{fmt.int_he(len(h))} המוסדות בפיקוח חרדי הם רשמיים, "
            f"לעומת {fmt.pct(s_off, 0)} מהמוסדות הממלכתיים.{tail}")


def _ins_city(loc_counts, total, n_loc):
    top, v = loc_counts.index[0], int(loc_counts.iloc[0])
    if top == UNKNOWN or v / total < CITY_LEAD:
        return None
    top5 = int(loc_counts.iloc[:5].sum())
    return (f"{top} מובילה עם {fmt.int_he(v)} מוסדות חינוך ({fmt.pct(v / total)} מהרשימה). "
            f"חמשת היישובים הגדולים מרכזים {fmt.pct(top5 / total, 0)} מהמוסדות, "
            f"והשאר פזורים ב-{fmt.int_he(max(n_loc - 5, 0))} יישובים נוספים.")


def _ins_haredi_cities(df, top_locs):
    hits = []
    for loc in top_locs:
        g = df[df["locality"] == loc]
        sh = _share(int((g["stream"] == HAREDI).sum()), len(g))
        if sh > HAREDI_MAJORITY:
            hits.append((-sh, loc, sh))
    if not hits:
        return None
    hits.sort()
    parts = [f"{loc} ({fmt.pct(sh, 0)})" for _, loc, sh in hits[:5]]
    lead = ("ביישוב אחד מבין" if len(hits) == 1 else
            f"ב-{fmt.int_he(len(hits))} מתוך")
    return (f"{lead} {fmt.int_he(len(top_locs))} היישובים עם הכי הרבה מוסדות, רוב המוסדות "
            f"בפיקוח חרדי: {fmt.join_he(parts)}.")


def _sep_share(g):
    known = g[g["gender"] != UNKNOWN]
    if len(known) < MIN_GROUP:
        return None, len(known)
    return _share(int((known["gender"] != MIXED).sum()), len(known)), len(known)


def _ins_gender(schools):
    h, nh = _sep_share(schools[schools["stream"] == HAREDI])
    s, ns = _sep_share(schools[schools["stream"] == STATE])
    if h is None or s is None or abs(h - s) < GAP_PTS:
        return None
    hi = ("בפיקוח חרדי", h, nh)
    lo = ("הממלכתיים", s, ns)
    if s > h:
        hi, lo = ("הממלכתיים", s, ns), ("בפיקוח חרדי", h, nh)
    mixed = " שרובם מעורבים" if 1 - lo[1] > 0.5 else ""
    return (f"{fmt.pct(hi[1], 0)} מבתי הספר {hi[0]} מיועדים לבנים בלבד או לבנות בלבד, "
            f"לעומת {fmt.pct(lo[1], 0)} מבתי הספר {lo[0]}{',' if mixed else ''}{mixed} "
            f"(מתוך {fmt.int_he(hi[2])} ו-{fmt.int_he(lo[2])} בתי ספר שהרכבם ידוע).")


def _ins_special(df):
    gans = df[df["group"] == G_GAN]
    schools = df[df["group"] == G_SCHOOL]
    if len(gans) < MIN_GROUP or len(schools) < MIN_GROUP:
        return None
    ng = int((gans["edtype"] == SPECIAL).sum())
    ns = int((schools["edtype"] == SPECIAL).sum())
    if ng + ns == 0:
        return None
    return (f"{fmt.int_he(ng)} גני ילדים ({fmt.pct(ng / len(gans), 0)} מהגנים) "
            f"ו-{fmt.int_he(ns)} בתי ספר ({fmt.pct(ns / len(schools), 0)}) "
            f"הם מסגרות של חינוך מיוחד.")


def _ins_accuracy(df, low_share):
    best = None
    for sec, g in df.groupby("sector", sort=True):
        if sec == UNKNOWN or len(g) < MIN_GROUP:
            continue
        sh = _share(int(g["accuracy"].isin(LOW_ACC).sum()), len(g))
        if best is None or sh > best[0]:
            best = (sh, sec, len(g))
    if best is None or low_share == 0:
        return None
    sh, sec, n = best
    if sh < SECTOR_GAP * low_share or sh < GAP_PTS:
        return None
    return (f"מיקום המוסדות במגזר ה{sec} מדויק פחות: {fmt.pct(sh, 0)} מ-{fmt.int_he(n)} "
            f"המוסדות שלו מוקמו ברמת דיוק בינונית או נמוכה (למשל במרכז היישוב או השכונה), "
            f"לעומת {fmt.pct(low_share, 0)} בכלל הרשימה.")


# ---------------------------------------------------------------- compute

def compute(frames: dict) -> dict:
    df = _prepare(frames["institutions"])
    total = len(df)
    if total == 0:
        raise ValueError("no institutions")

    group_counts = df["group"].value_counts().reindex(GROUPS, fill_value=0)
    group_counts = group_counts.sort_values(ascending=False, kind="stable")
    groups_present = [g for g in GROUPS if int(group_counts[g]) > 0]
    n_gan = int(group_counts[G_GAN])
    n_school = int(group_counts[G_SCHOOL])
    n_maon = int(group_counts[G_MAON])

    type_counts = _ranked_known_last(df["type"])
    loc_counts = _ranked_known_last(df["locality"])
    n_loc = int((loc_counts.index != UNKNOWN).sum())
    n_auth = int(df.loc[df["authority"] != UNKNOWN, "authority"].nunique())
    dist_counts = _ranked_known_last(df["district"])
    stream_counts = _ranked_known_last(df["stream"])
    stream_order = list(stream_counts.index)
    sector_counts = _ranked_known_last(df["sector"])
    sector_order = list(sector_counts.index)
    legal_order = list(_ranked_known_last(df["legal"]).index)
    acc_counts = df["accuracy"].value_counts()
    acc_order = _order_known(acc_counts, ACC_ORDER)

    low_n = int(df["accuracy"].isin(LOW_ACC).sum())
    low_share = low_n / total
    lowest_n = int((df["accuracy"] == "נמוכה").sum())
    lowest_share = lowest_n / total

    # framework types
    type_chart, type_rows = _rank_rows(type_counts, total, TOP_TYPES)
    # groups × stream (100%)
    _, gs_chart, gs_table = _crosstab(df, "group", groups_present, "stream", stream_order)
    # sector × group
    _, sg_chart, sg_table = _crosstab(df, "sector", sector_order, "group", groups_present)
    # stream × legal status (100%)
    _, sl_chart, sl_table = _crosstab(df, "stream", stream_order, "legal", legal_order)

    # special education share per stream, for kindergartens and schools
    sp_names, sp_gan, sp_school, sp_rows = [], [], [], []
    for st in stream_order:
        if st == UNKNOWN:
            continue
        g = df[(df["stream"] == st) & (df["group"] == G_GAN)]
        s = df[(df["stream"] == st) & (df["group"] == G_SCHOOL)]
        if len(g) + len(s) == 0:
            continue
        ng, ns = int((g["edtype"] == SPECIAL).sum()), int((s["edtype"] == SPECIAL).sum())
        pg = round(_share(ng, len(g)) * 100, 1)
        ps = round(_share(ns, len(s)) * 100, 1)
        sp_names.append(st)
        sp_gan.append(pg)
        sp_school.append(ps)
        sp_rows.append([st, fmt.int_he(ng), fmt.pct_of(pg), fmt.int_he(ns), fmt.pct_of(ps)])
    n_special = int((df["edtype"] == SPECIAL).sum())

    # school stages, in stage-code order
    schools = df[df["group"] == G_SCHOOL]
    st_df = (schools.groupby(["code", "stage"]).size().reset_index(name="n")
             .sort_values(["code", "stage"], kind="stable"))
    stage_chart = {"names": st_df["stage"].tolist(), "values": [int(v) for v in st_df["n"]]}
    stage_rows = [[r.stage, fmt.int_he(r.n), fmt.pct(_share(r.n, len(schools)))]
                  for r in st_df.itertuples()]
    stage_top = None
    if len(st_df):
        i = st_df["n"].to_numpy().argmax()
        stage_top = (st_df["stage"].iloc[i], int(st_df["n"].iloc[i]))

    # school gender composition per stream (100%)
    gender_order = _order_known(schools["gender"].value_counts(), ["בנים", "בנות", MIXED])
    sch_streams = [s for s in stream_order if (schools["stream"] == s).any()]
    _, gen_chart, gen_table = _crosstab(schools, "stream", sch_streams, "gender", gender_order)

    # top localities, stacked by group
    top_locs = [x for x in loc_counts.index if x != UNKNOWN][:TOP_LOCALITIES]
    loc_df = df[df["locality"].isin(top_locs)]
    _, loc_chart, loc_table = _crosstab(loc_df, "locality", top_locs, "group", groups_present)
    loc_hshare = []
    for loc in top_locs:
        g = loc_df[loc_df["locality"] == loc]
        loc_hshare.append(fmt.pct(_share(int((g["stream"] == HAREDI).sum()), len(g)), 0))
    for row, hs in zip(loc_table["rows"], loc_hshare):
        row.append(hs)

    # supervising district / unit
    dist_chart, dist_rows = _rank_rows(dist_counts, total, TOP_DISTRICTS)
    n_dist = int((dist_counts.index != UNKNOWN).sum())

    # geocoding accuracy by sector (100%)
    _, acc_chart, acc_table = _crosstab(df, "sector", sector_order, "accuracy", acc_order)
    acc_low = []
    for sec in sector_order:
        g = df[df["sector"] == sec]
        acc_low.append(fmt.pct(_share(int(g["accuracy"].isin(LOW_ACC).sum()), len(g)), 0))
    for row, ls in zip(acc_table["rows"], acc_low):
        row.append(ls)
    method_counts = _ranked_known_last(df["geo_method"])
    method_chart, method_rows = _rank_rows(method_counts, total, 10)
    reason_counts = _ranked_known_last(df["geo_reason"])
    _, reason_rows = _rank_rows(reason_counts, total, TOP_REASONS)
    n_mapped = int(df["mapped"].sum())

    insights = []
    for iid, text in [
        ("groups", _ins_groups(group_counts, total)),
        ("legal", _ins_legal(df)),
        ("city", _ins_city(loc_counts, total, n_loc)),
        ("haredi_cities", _ins_haredi_cities(df, top_locs)),
        ("gender", _ins_gender(schools)),
        ("special", _ins_special(df)),
        ("accuracy", _ins_accuracy(df, low_share)),
    ]:
        if text:
            insights.append({"id": iid, "text_he": text})

    top_loc = top_locs[0] if top_locs else UNKNOWN
    top_type = type_counts.index[0]
    stream_known = stream_counts[stream_counts.index != UNKNOWN]
    stream_parts = [f"{s} {fmt.pct(int(v) / total, 0)}" for s, v in stream_known.items()]

    lede = (f"רשימת מוסדות החינוך הפעילים של משרד החינוך, רשמיים ומוכרים: "
            f"{fmt.int_he(total)} מוסדות ב-{fmt.int_he(n_loc)} יישובים, ובהם "
            f"{fmt.int_he(n_gan)} גני ילדים, {fmt.int_he(n_school)} בתי ספר ומוסדות לימוד "
            f"ו-{fmt.int_he(n_maon)} מעונות יום. לכל מוסד רשומים סמל מוסד, שם, יישוב "
            f"ורשות, סוג המסגרת, הפיקוח, המגזר, שלב החינוך ומיקום על המפה, יחד עם "
            f"רמת הדיוק של המיקום. בחלוקה לפי פיקוח: {', '.join(stream_parts)}.")
    summary = (f"{fmt.int_he(total)} מוסדות חינוך פעילים בישראל: {fmt.int_he(n_gan)} גני ילדים, "
               f"{fmt.int_he(n_school)} בתי ספר ו-{fmt.int_he(n_maon)} מעונות יום ב-"
               f"{fmt.int_he(n_loc)} יישובים, עם סמל מוסד, סוג פיקוח, מגזר ומיקום על המפה.")
    seo_desc = (f"איתור גן ילדים, בית ספר או מעון יום לפי שם, סמל מוסד או יישוב: "
                f"{fmt.int_he(total)} מוסדות חינוך פעילים ב-{fmt.int_he(n_loc)} יישובים, "
                f"על המפה ולפי פיקוח.")

    map_note = ("כל מוסד מסומן לפי המיקום שמשרד החינוך רשם לו. לחיצה על נקודה מציגה את שם "
                "המוסד, סמל המוסד, סוג המסגרת, היישוב, הפיקוח ורמת הדיוק של המיקום.")
    if lowest_n:
        map_note += (f" {fmt.int_he(lowest_n)} מוסדות ({fmt.pct(lowest_share, 0)}) מוקמו ברמת "
                     f"דיוק נמוכה, לרוב במרכז היישוב, ולכן הנקודה שלהם היא קירוב בלבד.")
    if total - n_mapped:
        map_note += f" {fmt.int_he(total - n_mapped)} מוסדות בלי נקודת ציון תקינה אינם במפה."

    h_total = int(stream_counts.get(HAREDI, 0))
    labels = {
        "lede": lede,
        "map_note": map_note,
        "map_aria": f"מפה אינטראקטיבית של {fmt.int_he(n_mapped)} מוסדות החינוך. גרסה נגישה: ראו את טבלת הנתונים למטה.",
        "type_lede": (f"סוג המסגרת כפי שמשרד החינוך רושם אותו ({fmt.int_he(len(type_counts))} סוגים). "
                      f"הנפוץ: {top_type}, עם {fmt.int_he(int(type_counts.iloc[0]))} מוסדות."),
        "type_aria": f"תרשים עמודות: מספר המוסדות לפי סוג המסגרת, הנפוץ {top_type}",
        "gs_lede": ("חלוקת המוסדות בכל קבוצה לפי זרם הפיקוח. גני ילדים ובתי ספר מקובצים לפי "
                    "שלב החינוך הרשום למוסד."),
        "gs_aria": "תרשים עמודות מוערמות באחוזים: זרם הפיקוח בגני הילדים, בבתי הספר ובמעונות היום",
        "sg_lede": (f"מספר המוסדות בכל מגזר, בחלוקה לסוג המוסד. המגזר הגדול: "
                    f"{sector_order[0]}, עם {fmt.int_he(int(sector_counts.iloc[0]))} מוסדות."),
        "sg_aria": "תרשים עמודות מוערמות: מוסדות החינוך לפי מגזר וסוג מוסד",
        "sl_lede": (f"מעמד המוסד לפי זרם הפיקוח. מוסד רשמי מוחזק בידי המדינה והרשות המקומית, "
                    f"ומוסד מוכר שאיננו רשמי מופעל בידי בעלות פרטית או רשת. בפיקוח החרדי "
                    f"{fmt.int_he(h_total)} מוסדות."),
        "sl_aria": "תרשים עמודות מוערמות באחוזים: מעמד המוסד (רשמי, מוכר שאיננו רשמי ועוד) בכל זרם פיקוח",
        "sp_lede": (f"שיעור המסגרות לחינוך מיוחד מתוך גני הילדים ובתי הספר בכל זרם. "
                    f"בסך הכול {fmt.int_he(n_special)} מוסדות חינוך מיוחד ברשימה."),
        "sp_aria": "תרשים עמודות: שיעור החינוך המיוחד בגני הילדים ובבתי הספר לפי זרם פיקוח",
        "stage_lede": (f"שלבי החינוך שבכל אחד מ-{fmt.int_he(len(schools))} בתי הספר ומוסדות הלימוד."
                       + (f" הנפוץ: {stage_top[0]}, ב-{fmt.int_he(stage_top[1])} מוסדות."
                          if stage_top else "")),
        "stage_aria": "תרשים עמודות: בתי הספר לפי שלבי החינוך שהם כוללים",
        "gen_lede": ("הרכב התלמידים בבתי הספר לפי זרם הפיקוח: בנים בלבד, בנות בלבד או מעורב. "
                     "מעונות היום אינם כלולים, כי ההרכב הרשום להם קבוע ואינו משקף את הילדים."),
        "gen_aria": "תרשים עמודות מוערמות באחוזים: הרכב בנים, בנות ומעורב בבתי הספר לפי זרם פיקוח",
        "loc_lede": (f"{fmt.int_he(len(top_locs))} היישובים עם הכי הרבה מוסדות חינוך, בחלוקה לסוג "
                     f"המוסד. בראש: {top_loc}, עם {fmt.int_he(int(loc_counts.iloc[0]))} מוסדות."),
        "loc_aria": f"תרשים עמודות מוערמות: {fmt.int_he(len(top_locs))} היישובים עם הכי הרבה מוסדות חינוך",
        "loc_caption": "היישובים עם הכי הרבה מוסדות חינוך, לפי סוג מוסד ושיעור הפיקוח החרדי",
        "dist_lede": (f"המחוז או היחידה במשרד החינוך שמפקחת על המוסד ({fmt.int_he(n_dist)} יחידות). "
                      f"לצד המחוזות הגאוגרפיים יש יחידות לפי סוג פיקוח, כמו המוכרים והרישוי."),
        "dist_aria": "תרשים עמודות: מספר המוסדות לפי מחוז או יחידה מפקחת במשרד החינוך",
        "acc_lede": (f"משרד החינוך מדרג כמה מדויקת נקודת המיקום של כל מוסד. "
                     f"{fmt.int_he(low_n)} מוסדות ({fmt.pct(low_share, 0)}) מוקמו ברמת דיוק "
                     f"בינונית או נמוכה. כך זה נראה בכל מגזר."),
        "acc_aria": "תרשים עמודות מוערמות באחוזים: רמת הדיוק של מיקום המוסדות בכל מגזר",
        "method_lede": "השיטה שבה נקבע המיקום של המוסד, מכתובת מלאה ועד מרכז היישוב.",
        "method_aria": "תרשים עמודות: מספר המוסדות לפי שיטת קביעת המיקום",
        "reason_caption": "פירוט סיבת המיקום כפי שהיא רשומה לכל מוסד",
    }

    def tone_low(sh):
        if sh >= LOW_ACC_WARN:
            return "warn"
        if sh < LOW_ACC_OK:
            return "ok"
        return "brand"

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "חיפוש סמל מוסד חינוך: גנים, בתי ספר ומעונות יום",
                "description": seo_desc,
                "name": "מוסדות חינוך בישראל: גני ילדים, בתי ספר ומעונות יום",
                "alternate_names": [
                    "מוסדות חינוך",
                    "רשימת מוסדות החינוך של משרד החינוך",
                    "איתור סמל מוסד",
                    "מפת בתי ספר וגני ילדים",
                    "מיקום מוסדות חינוך",
                ],
            },
        },
        "kpis": {
            "total": _kpi(total, fmt.int_he(total)),
            "gan": _kpi(n_gan, fmt.int_he(n_gan)),
            "school": _kpi(n_school, fmt.int_he(n_school)),
            "maon": _kpi(n_maon, fmt.int_he(n_maon)),
            "localities": _kpi(n_loc, fmt.int_he(n_loc), "info"),
            "low_acc": _kpi(round(lowest_share, 4), fmt.pct(lowest_share, 0), tone_low(lowest_share)),
        },
        "kpi_labels": {
            "localities": f"יישובים ({fmt.int_he(n_auth)} רשויות מקומיות)",
        },
        "charts": {
            "types": type_chart,
            "group_stream": gs_chart,
            "sector_group": sg_chart,
            "stream_legal": sl_chart,
            "special": {"names": sp_names, "gan": sp_gan, "school": sp_school},
            "stages": stage_chart,
            "gender": gen_chart,
            "localities": loc_chart,
            "districts": dist_chart,
            "accuracy": acc_chart,
            "methods": method_chart,
        },
        "tables": {
            "types": type_rows,
            "group_stream": gs_table,
            "sector_group": sg_table,
            "stream_legal": sl_table,
            "special": sp_rows,
            "stages": stage_rows,
            "gender": gen_table,
            "localities": loc_table,
            "districts": dist_rows,
            "accuracy": acc_table,
            "methods": method_rows,
            "reasons": reason_rows,
        },
        "insights": insights,
        "labels": labels,
    }
