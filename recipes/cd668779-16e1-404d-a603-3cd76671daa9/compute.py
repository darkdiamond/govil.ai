"""מאגרי המים העיליים בישראל: a registry of surface reservoirs (Water Authority).

One row per reservoir. Volume is in thousands of m³ (אלמ"ק). Every number,
chart series and sentence on the page is computed here. Implausible values
are excluded by disclosed, data-driven rules:

* volume: a top value more than OUTLIER_RATIO times the next largest one is
  treated as a typo and left out of every volume total (2026-01: one kibbutz
  reservoir listed at 300,000 = 300 million m³, 24x the next);
* construction year before YEAR_MIN;
* depth above DEPTH_MAX metres.
"""
import re

import pandas as pd
from govlib import fmt, frame

ID = "זיהוי מאגר"
NAME = "שם המאגר"
TYPE = "סוג המאגר"
PLANTS = "מכוני מים משוייכים"
QUALITY = "איכות מים"
DEPTH = "עומק (מ')"
VOL = "נפח (אלמק)"
YEAR = "שנת הקמה"
AREA = "שטח המאגר (דונם)"
SURF = "שטח פני המים (דונם)"
CELL = "שם התא"
OWNER = "בעלות"
SOURCE = "מקור המאגר"
NATNO = "מספר ארצי"
LINING = "חיפוי המאגר"
ELEV = "רום (מ')"

NONE = "לא צוין"
OUTLIER_RATIO = 10
YEAR_MIN = 1900
DEPTH_MAX = 100
TOP_N = 12
SCATTER_MAX = 700  # keeps the scatter's script block well under 50KB as the list grows

# Keyword classes for the free-text source field, first match wins.
SOURCE_RULES = [
    ("קולחין וביוב", r"קולח|ביוב|שפכ|שפד|טיהור|טיפול|מט\"?ש|סניטר|רפת|ביתי|תשלובת|קישון"),
    ("נחלים, שטפונות וניקוז", r"שטפ|נחל|ניקוז|נקוז|נקז|תעל|ירדן|כנרת|כינרת"),
    ("מעיינות", r"מעיינ|מעין|נביע|עיינות|(?:^|[\s\-])עין\s"),
    ("קידוחים ומים מליחים", r"קידוח|מליח|באר"),
    ("מערכת ארצית ואגודות מים", r"מקורות|מוביל|מפעל|(?:^|\s)קו\s|אגוד|מי-|מי\s"),
]
SOURCE_ORDER = [n for n, _ in SOURCE_RULES] + ["אחר"]

SIZE_BINS = [0, 50, 100, 250, 500, 1000, 2500, 5000, float("inf")]
SIZE_LABELS = ["עד 50", "50-100", "100-250", "250-500", "500-1,000",
               "1,000-2,500", "2,500-5,000", "מעל 5,000"]
DEPTH_BINS = [0, 3, 5, 7, 10, 15, float("inf")]
DEPTH_LABELS = ["עד 3", "3-5", "5-7", "7-10", "10-15", "מעל 15"]


def _classify_source(s):
    if not s:
        return NONE
    for name, pat in SOURCE_RULES:
        if re.search(pat, s):
            return name
    return "אחר"


def _owner(s):
    if not s:
        return ""
    if "מקורות" in s:
        return "מקורות"
    return s


def _excluded_note(k, what):
    if k == 0:
        return ""
    if k == 1:
        return f" רשומה אחת {what} הושמטה כשגויה."
    return f" {fmt.int_he(k)} רשומות {what} הושמטו כשגויות."


def _boom_prefix(share, adjacent):
    """Claim "most" only above 50%, and "one wave" only for adjacent decades."""
    if share > 0.5 and adjacent:
        return "רוב המאגרים נבנו בגל אחד: "
    if share > 0.5:
        return "רוב המאגרים נבנו בשני עשורים: "
    if adjacent:
        return "גל הבנייה העיקרי: "
    return ""


def _since_2000(k):
    if k == 0:
        return ", ומאז שנת 2000 לא נוסף אף מאגר."
    if k == 1:
        return ", ומאז שנת 2000 נוסף מאגר אחד בלבד."
    return f", ומאז שנת 2000 נוספו רק {fmt.int_he(k)}."


def _decade_label(d):
    d = int(d)
    if 1900 <= d < 2000:
        return f"שנות ה-{d - 1900}"
    return f"שנות ה-{d}"


def _prepare(df):
    df = df.copy()
    for c in df.columns:
        df[c] = frame.clean_series(df[c])
    df["id"] = pd.to_numeric(df[ID], errors="coerce").fillna(-1)
    df["name"] = df[NAME]
    df["type"] = df[TYPE].where(df[TYPE] != "", NONE)
    df["owner"] = df[OWNER].map(_owner)
    df["src"] = df[SOURCE].map(_classify_source)
    vol = frame.num(df[VOL])
    vol = vol.where(vol > 0)
    df["vol_raw"] = vol
    yr = frame.num(df[YEAR])
    df["year_bad"] = yr.notna() & (yr < YEAR_MIN)
    df["year"] = yr.where(yr >= YEAR_MIN)
    dp = frame.num(df[DEPTH])
    df["depth_bad"] = dp.notna() & (dp > DEPTH_MAX)
    df["depth"] = dp.where((dp > 0) & (dp <= DEPTH_MAX))
    ar = frame.num(df[AREA])
    df["area"] = ar.where(ar > 0)
    df["elev"] = frame.num(df[ELEV])
    df = df.sort_values(["id", "name"], kind="stable").reset_index(drop=True)

    # Isolated top volumes: drop while the largest is OUTLIER_RATIO x the next.
    df["vol_out"] = False
    ranked = df[df["vol_raw"].notna()].sort_values(["vol_raw", "id"], ascending=[False, True], kind="stable")
    idx = list(ranked.index)
    vals = list(ranked["vol_raw"])
    i = 0
    while i + 1 < len(vals) and vals[i] > OUTLIER_RATIO * vals[i + 1]:
        df.loc[idx[i], "vol_out"] = True
        i += 1
    df["vol"] = df["vol_raw"].where(~df["vol_out"])
    return df


def _mcm(v):
    """Thousands of m³ → million m³, display string."""
    m = v / 1000
    return fmt.num_he(m, 1) if m < 100 else fmt.int_he(m)


def compute(frames):
    df = _prepare(frames["main"])
    n = len(df)
    has_vol = df[df["vol"].notna()]
    total_vol = float(has_vol["vol"].sum())
    n_vol = len(has_vol)
    outliers = df[df["vol_out"]]

    insights = []
    labels = {}
    tables = {}
    charts = {}
    flags = {}

    # ---- by type ---------------------------------------------------------
    t_counts = frame.ranked(df["type"])
    t_vol = df.groupby("type")["vol"].sum()
    t_lab, t_cnt = frame.top_other(t_counts, 6)
    keep = set(t_lab) - {frame.OTHER}
    t_vols = []
    for lab in t_lab:
        if lab == frame.OTHER:
            t_vols.append(float(t_vol[[k for k in t_vol.index if k not in keep]].sum()))
        else:
            t_vols.append(float(t_vol.get(lab, 0.0)))
    charts["types"] = {
        "names": t_lab,
        "count": t_cnt,
        "vol": [round(v / 1000, 2) for v in t_vols],
        "count_share": [round(c / n * 100, 1) for c in t_cnt],
        "vol_share": [round(v / total_vol * 100, 1) if total_vol else 0 for v in t_vols],
    }
    tables["types"] = [
        [lab, fmt.int_he(c), fmt.pct(c / n), _mcm(v), fmt.pct(v / total_vol) if total_vol else "–"]
        for lab, c, v in zip(t_lab, t_cnt, t_vols)
    ]
    top_type = t_counts.index[0]
    top_type_n = int(t_counts.iloc[0])
    top_type_vol = float(t_vol.get(top_type, 0.0))
    labels["types_lede"] = (
        f"{top_type} הוא הסוג הנפוץ: {fmt.int_he(top_type_n)} מתוך {fmt.int_he(n)} המאגרים"
        f" ({fmt.pct(top_type_n / n)})"
        + (f", עם {fmt.pct(top_type_vol / total_vol)} מהקיבולת המדווחת." if total_vol else ".")
    )
    if top_type != NONE and top_type_n / n >= 0.3 and total_vol:
        insights.append({
            "id": "type_leader",
            "text_he": (
                f"{fmt.int_he(top_type_n)} מתוך {fmt.int_he(n)} המאגרים ({fmt.pct(top_type_n / n)}) הם"
                f" מסוג \"{top_type}\", והם מחזיקים {fmt.pct(top_type_vol / total_vol)} מהקיבולת המדווחת."
            ),
        })

    # Median size by type (types with ≥10 volumes)
    med = has_vol.groupby("type")["vol"].agg(["median", "count"])
    med = med[(med["count"] >= 10) & (med.index != NONE)].sort_values(["median"], ascending=False, kind="stable")
    if len(med) >= 2:
        hi, lo = med.index[0], med.index[-1]
        ratio = med.loc[hi, "median"] / med.loc[lo, "median"]
        if ratio >= 1.5:
            insights.append({
                "id": "type_size",
                "text_he": (
                    f"המאגר החציוני מסוג \"{hi}\" מחזיק {fmt.int_he(med.loc[hi, 'median'])} אלף מ\"ק,"
                    f" פי {fmt.num_he(ratio, 1)} מהמאגר החציוני מסוג \"{lo}\""
                    f" ({fmt.int_he(med.loc[lo, 'median'])} אלף מ\"ק)."
                ),
            })

    # ---- size distribution ----------------------------------------------
    bins = pd.cut(has_vol["vol"], SIZE_BINS, labels=SIZE_LABELS, right=True)
    s_cnt = bins.value_counts().reindex(SIZE_LABELS, fill_value=0)
    s_vol = has_vol.groupby(bins, observed=False)["vol"].sum().reindex(SIZE_LABELS, fill_value=0)
    charts["size"] = {
        "names": SIZE_LABELS,
        "count": [int(v) for v in s_cnt],
        "share": [round(float(v) / total_vol * 100, 1) if total_vol else 0 for v in s_vol],
    }
    tables["size"] = [
        [lab, fmt.int_he(c), _mcm(v), fmt.pct(v / total_vol) if total_vol else "–"]
        for lab, c, v in zip(SIZE_LABELS, s_cnt, s_vol)
    ]
    median_vol = float(has_vol["vol"].median()) if n_vol else 0.0
    big = has_vol[has_vol["vol"] > 1000]
    labels["size_lede"] = (
        f"המאגר החציוני מחזיק {fmt.int_he(median_vol)} אלף מ\"ק. {fmt.int_he(len(big))} המאגרים שמעל מיליון מ\"ק"
        f" ({fmt.pct(len(big) / n_vol) if n_vol else '–'} מהמאגרים עם נפח מדווח) מחזיקים"
        f" {fmt.pct(big['vol'].sum() / total_vol) if total_vol else '–'} מהקיבולת."
        " העמודות סופרות מאגרים בכל קבוצת נפח (באלפי מ\"ק), והקו מראה את נתח הקבוצה מהקיבולת."
    )

    # ---- top reservoirs ---------------------------------------------------
    top = has_vol.sort_values(["vol", "id"], ascending=[False, True], kind="stable").head(TOP_N)
    charts["top"] = {
        "names": top["name"].tolist(),
        "vol": [round(float(v) / 1000, 2) for v in top["vol"]],
        "type": top["type"].tolist(),
        "owner": [o or NONE for o in top["owner"]],
    }
    tables["top"] = [
        [str(i + 1), r["name"], r["type"], r["owner"] or NONE,
         fmt.int_he(r["year"]) if pd.notna(r["year"]) else "–", fmt.int_he(r["vol"])]
        for i, (_, r) in enumerate(top.iterrows())
    ]
    labels["top_n"] = fmt.int_he(len(top))
    if len(top):
        r0 = top.iloc[0]
        labels["top_lede"] = (
            f"הגדול ברשימה הוא {r0['name']} עם {_mcm(r0['vol'])} מיליון מ\"ק."
            + (f" {fmt.int_he(len(top))} המאגרים הגדולים מחזיקים {fmt.pct(top['vol'].sum() / total_vol)}"
               f" מהקיבולת המדווחת." if total_vol else "")
        )
    if n_vol >= 30 and total_vol:
        k = 10
        share10 = has_vol["vol"].nlargest(k).sum() / total_vol
        insights.append({
            "id": "concentration",
            "text_he": (
                f"עשרת המאגרים הגדולים מחזיקים {fmt.pct(share10)} מהקיבולת המדווחת"
                f" ({_mcm(has_vol['vol'].nlargest(k).sum())} מתוך {_mcm(total_vol)} מיליון מ\"ק),"
                f" אף שהם {fmt.pct(k / n_vol)} בלבד מהמאגרים עם נפח ידוע."
            ),
        })
    if len(outliers):
        o = outliers.sort_values(["vol_raw", "id"], ascending=[False, True], kind="stable").iloc[0]
        nxt = float(has_vol["vol"].max()) if n_vol else 0
        names = fmt.join_he(outliers["name"].tolist())
        labels["outlier_note"] = (
            f"נפח של {names} ({fmt.int_he(o['vol_raw'])} אלף מ\"ק) גדול פי"
            f" {fmt.int_he(o['vol_raw'] / nxt) if nxt else '–'} מהמאגר הבא ברשימה, כנראה טעות הקלדה,"
            " ולכן אינו נכלל בסיכומי הנפח בעמוד."
        )
        insights.append({"id": "outlier", "text_he": labels["outlier_note"]})
    else:
        labels["outlier_note"] = ""

    # ---- construction by decade -----------------------------------------
    has_year = df[df["year"].notna()].copy()
    has_year["decade"] = (has_year["year"] // 10 * 10).astype(int)
    flags["decades"] = has_year["decade"].nunique() >= 3
    if flags["decades"]:
        d0, d1 = int(has_year["decade"].min()), int(has_year["decade"].max())
        decades = list(range(d0, d1 + 10, 10))
        d_cnt = has_year["decade"].value_counts().reindex(decades, fill_value=0)
        d_vol = has_year.groupby("decade")["vol"].sum().reindex(decades, fill_value=0)
        cum = d_vol.cumsum()
        charts["decades"] = {
            "names": [_decade_label(d) for d in decades],
            "short": [str(d) for d in decades],
            "count": [int(v) for v in d_cnt],
            "cum": [round(float(v) / 1000, 1) for v in cum],
        }
        tables["decades"] = [
            [_decade_label(d), fmt.int_he(c), _mcm(v), _mcm(cv)]
            for d, c, v, cv in zip(decades, d_cnt, d_vol, cum)
        ]
        peak = d_cnt.sort_values(ascending=False, kind="stable")
        pd_, pn = int(peak.index[0]), int(peak.iloc[0])
        two = peak.iloc[:2]
        labels["decades_lede"] = (
            f"שנת הקמה ידועה ל-{fmt.int_he(len(has_year))} מאגרים. השיא היה ב{_decade_label(pd_)},"
            f" עם {fmt.int_he(pn)} מאגרים חדשים. הקו מראה את הקיבולת המצטברת (מיליון מ\"ק) של המאגרים שנבנו עד כל עשור"
            " (רק מאגרים עם שנת הקמה ונפח ידועים)."
            + _excluded_note(int(df["year_bad"].sum()), f"עם שנת הקמה לפני {YEAR_MIN}")
        )
        share2 = two.sum() / len(has_year)
        recent = int((has_year["year"] >= 2000).sum())
        if share2 >= 0.4:
            dl = sorted(int(x) for x in two.index)
            insights.append({
                "id": "boom",
                "text_he": (
                    _boom_prefix(share2, dl[1] - dl[0] == 10)
                    + f"{fmt.pct(share2)} מהמאגרים ששנת הקמתם ידועה הוקמו ב"
                    f"{_decade_label(dl[0])} וב{_decade_label(dl[1])}"
                    + (_since_2000(recent) if d1 >= 2000 else ".")
                ),
            })

    # ---- water quality ---------------------------------------------------
    q = df[df[QUALITY] != ""]
    q_counts = frame.ranked(q[QUALITY])
    q_lab, q_cnt = frame.top_other(q_counts, 4)
    flags["quality"] = len(q) >= 10
    charts["quality"] = {"names": q_lab, "count": q_cnt}
    tables["quality"] = [[lab, fmt.int_he(c), fmt.pct(c / len(q)) if len(q) else "–"] for lab, c in zip(q_lab, q_cnt)]
    ww = int(q[QUALITY].str.contains("קולח").sum())
    labels["quality_lede"] = (
        f"איכות המים מצוינת ל-{fmt.int_he(len(q))} מאגרים בלבד ({fmt.pct(len(q) / n)})."
        f" מתוכם {fmt.int_he(ww)} ({fmt.pct(ww / len(q)) if len(q) else '–'}) מוגדרים כמאגרי קולחין."
    )

    # ---- source (keyword classes) ---------------------------------------
    order = SOURCE_ORDER + [NONE]
    src_cnt = df["src"].value_counts().reindex(order, fill_value=0)
    src_vol = df.groupby("src")["vol"].sum().reindex(order, fill_value=0)
    charts["source"] = {
        "names": order,
        "count": [int(v) for v in src_cnt],
        "vol": [round(float(v) / 1000, 1) for v in src_vol],
        "count_share": [round(int(c) / n * 100, 1) for c in src_cnt],
        "vol_share": [round(float(v) / total_vol * 100, 1) if total_vol else 0 for v in src_vol],
    }
    tables["source"] = [[lab, fmt.int_he(c), _mcm(v)] for lab, c, v in zip(order, src_cnt, src_vol)]
    n_src = int((df["src"] != NONE).sum())
    ww_src = int(src_cnt["קולחין וביוב"])
    labels["source_lede"] = (
        f"מקור המים מתואר בטקסט חופשי ל-{fmt.int_he(n_src)} מאגרים, וסווג כאן לפי מילות מפתח"
        " (מאגר עם כמה מקורות משויך למקור הראשון ברשימת הקבוצות)."
        f" {fmt.int_he(ww_src)} מאגרים ({fmt.pct(ww_src / n_src) if n_src else '–'}) נשענים על קולחין או ביוב."
    )
    if n_src >= 50 and ww_src / n_src >= 0.3:
        insights.append({
            "id": "wastewater",
            "text_he": (
                f"מקור המים של {fmt.int_he(ww_src)} מאגרים ({fmt.pct(ww_src / n_src)} מאלו שמקורם מתואר)"
                " הוא קולחין, ביוב או שפכים: יותר ממחצית המאגרים שמקורם ידוע אוגרים מי קולחין."
                if ww_src / n_src >= 0.5 else
                f"מקור המים של {fmt.int_he(ww_src)} מאגרים ({fmt.pct(ww_src / n_src)} מאלו שמקורם מתואר)"
                " הוא קולחין, ביוב או שפכים, הקבוצה הגדולה ביותר."
            ),
        })

    # ---- owners -----------------------------------------------------------
    own = df[df["owner"] != ""]
    o_counts = frame.ranked(own["owner"])
    o_top = o_counts.head(12)
    o_vol = own.groupby("owner")["vol"].sum()
    charts["owners"] = {
        "names": [str(k) for k in o_top.index],
        "count": [int(v) for v in o_top],
        "vol": [round(float(o_vol.get(k, 0)) / 1000, 2) for k in o_top.index],
    }
    tables["owners"] = [[str(k), fmt.int_he(v), _mcm(o_vol.get(k, 0))] for k, v in o_top.items()]
    flags["owners"] = len(o_top) >= 3
    labels["owners_lede"] = (
        f"הבעלות מצוינת ל-{fmt.int_he(len(own))} מאגרים, בידי {fmt.int_he(len(o_counts))} גופים שונים:"
        " קיבוצים, מושבים, אגודות מים, רשויות ניקוז וחברת מקורות (כל שלוחות מקורות אוחדו)."
    )
    if len(o_counts) >= 2 and total_vol:
        lead, ln = o_counts.index[0], int(o_counts.iloc[0])
        if ln >= 5 and ln >= 2 * int(o_counts.iloc[1]):
            insights.append({
                "id": "owner",
                "text_he": (
                    f"{lead} היא הבעלים של {fmt.int_he(ln)} מאגרים, פי {fmt.num_he(ln / int(o_counts.iloc[1]), 1)}"
                    f" מהבעלים הבא ({o_counts.index[1]}), ושל {fmt.pct(float(o_vol.get(lead, 0)) / total_vol)}"
                    f" מהקיבולת המדווחת. שאר המאגרים מפוזרים בין {fmt.int_he(len(o_counts) - 1)} בעלים אחרים."
                ),
            })

    # ---- lining + depth -------------------------------------------------
    lin = df[df[LINING] != ""]
    l_counts = frame.ranked(lin[LINING])
    l_lab, l_cnt = frame.top_other(l_counts, 5)
    flags["lining"] = len(lin) >= 10
    charts["lining"] = {"names": l_lab, "count": l_cnt}
    tables["lining"] = [[lab, fmt.int_he(c)] for lab, c in zip(l_lab, l_cnt)]
    labels["lining_lede"] = (
        f"סוג החיפוי מצוין ל-{fmt.int_he(len(lin))} מאגרים בלבד ({fmt.pct(len(lin) / n)})."
        + (f" הנפוץ: {l_counts.index[0]} ({fmt.int_he(int(l_counts.iloc[0]))})." if len(l_counts) else "")
    )

    hd = df[df["depth"].notna()]
    dbins = pd.cut(hd["depth"], DEPTH_BINS, labels=DEPTH_LABELS, right=True)
    dc = dbins.value_counts().reindex(DEPTH_LABELS, fill_value=0)
    flags["depth"] = len(hd) >= 10
    charts["depth"] = {"names": DEPTH_LABELS, "count": [int(v) for v in dc]}
    tables["depth"] = [[lab, fmt.int_he(c)] for lab, c in zip(DEPTH_LABELS, dc)]
    labels["depth_lede"] = (
        f"עומק ידוע ל-{fmt.int_he(len(hd))} מאגרים; העומק החציוני {fmt.num_he(hd['depth'].median(), 1)} מ'."
        + _excluded_note(int(df["depth_bad"].sum()), f"עם עומק מעל {DEPTH_MAX} מ'")
    )

    # ---- scatter area vs volume ----------------------------------------
    sc = df[df["vol"].notna() & df["area"].notna()]
    capped = len(sc) > SCATTER_MAX
    sc = sc.sort_values(["vol", "id"], ascending=[False, True], kind="stable").head(SCATTER_MAX)
    sc = sc.sort_values("id", kind="stable")
    flags["scatter"] = len(sc) >= 20
    stypes = [lab for lab in t_lab if lab not in (frame.OTHER, NONE)][:4]
    series = []
    for st in stypes + ["אחר"]:
        sub = sc[sc["type"] == st] if st != "אחר" else sc[~sc["type"].isin(stypes)]
        series.append({
            "name": st,
            "data": [[float(a), float(v), nm, (float(d) if pd.notna(d) else None)]
                     for a, v, nm, d in zip(sub["area"], sub["vol"], sub["name"], sub["depth"])],
        })
    charts["scatter"] = series
    if len(sc) >= 20:
        dens = (sc["vol"] / sc["area"]).median()
        labels["scatter_lede"] = (
            f"{fmt.int_he(len(sc))} מאגרים עם נפח ושטח ידועים"
            + (" (הגדולים שבהם)" if capped else "")
            + f". בחציון כל דונם של שטח מאגר מחזיק"
            f" {fmt.num_he(dens, 1)} אלף מ\"ק. הציר האופקי הוא שטח המאגר בדונם והאנכי נפחו באלפי מ\"ק, שניהם בסקאלה לוגריתמית;"
            " נקודות מעל הענן הן מאגרים עמוקים במיוחד ביחס לשטחם."
        )

    # ---- completeness ---------------------------------------------------
    fields = [(NAME, "שם"), (TYPE, "סוג"), (VOL, "נפח"), (SOURCE, "מקור המים"), (OWNER, "בעלות"),
              (DEPTH, "עומק"), (YEAR, "שנת הקמה"), (PLANTS, "מכוני מים משויכים"), (AREA, "שטח המאגר"),
              (QUALITY, "איכות מים"), (SURF, "שטח פני המים"), (LINING, "חיפוי"), (NATNO, "מספר ארצי"),
              (ELEV, "רום"), (CELL, "שם התא")]
    comp = sorted(((lab, float((df[c] != "").mean() * 100)) for c, lab in fields),
                  key=lambda t: (-t[1], t[0]))
    charts["complete"] = {"names": [c[0] for c in comp], "pct": [round(c[1], 1) for c in comp]}
    tables["complete"] = [[c[0], fmt.pct_of(c[1])] for c in comp]
    low = [c[0] for c in comp if c[1] < 20]
    labels["complete_lede"] = (
        "לא לכל מאגר מולאו כל השדות. "
        + (f"השדות {fmt.join_he(low)} מולאו בפחות מחמישית מהמאגרים."
           if low else "כל השדות מולאו ליותר מחמישית מהמאגרים.")
    )

    # ---- elevation extremes ----------------------------------------------
    ev = df[df["elev"].notna()].sort_values(["elev", "id"], kind="stable")
    if len(ev) >= 5:
        lo, hi = ev.iloc[0], ev.iloc[-1]
        if lo["elev"] < 0:
            insights.append({
                "id": "elevation",
                "text_he": (
                    f"לפי {fmt.int_he(len(ev))} המאגרים שגובהם מדווח, הנמוך הוא {lo['name']}"
                    f" ({fmt.int_he(abs(lo['elev']))} מ' מתחת לפני הים) והגבוה {hi['name']}"
                    f" ({fmt.int_he(hi['elev'])} מ' מעל פני הים)."
                ),
            })

    # ---- KPIs -------------------------------------------------------------
    ww_share = ww / len(q) if len(q) else 0
    kpis = {
        "count": {"value": n, "display": fmt.int_he(n), "tone": "brand"},
        "capacity": {"value": round(total_vol / 1000, 1), "display": _mcm(total_vol), "tone": "brand"},
        "median": {"value": round(median_vol, 1), "display": fmt.int_he(median_vol), "tone": "brand"},
        "types": {"value": int((t_counts.index != NONE).sum()), "display": fmt.int_he(int((t_counts.index != NONE).sum())),
                  "tone": "brand"},
        "wastewater": {"value": round(ww_share * 100, 1), "display": fmt.pct(ww_share),
                       "tone": "info"},
        "vol_cov": {"value": round(n_vol / n * 100, 1), "display": fmt.pct(n_vol / n),
                    "tone": "ok" if n_vol / n >= 0.9 else "warn" if n_vol / n < 0.7 else "brand"},
    }
    labels["vol_cov_kpi"] = "מאגרים עם נפח מדווח"
    labels["count_kpi"] = "מאגרים ברשימה"

    # ---- agent data + SEO ----------------------------------------------
    yrs = has_year["year"] if len(has_year) else pd.Series(dtype=float)
    summary = (
        f"רשימה של {fmt.int_he(n)} מאגרי מים עיליים בישראל עם קיבולת מדווחת כוללת של"
        f" {_mcm(total_vol)} מיליון מ\"ק. {fmt.pct(top_type_n / n)} מהם מסוג \"{top_type}\","
        f" ו-{fmt.int_he(ww_src)} ניזונים מקולחין או ביוב. לכל מאגר: סוג, נפח, עומק, שטח, שנת הקמה, בעלות ומקור המים."
    )
    description = (
        f"איתור מאגר מים לפי שם, בעלים או מקור המים: {fmt.int_he(n)} מאגרים עיליים בישראל,"
        f" {_mcm(total_vol)} מיליון מ\"ק קיבולת, {fmt.int_he(ww_src)} מהם ניזונים מקולחין."
    )
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "מאגרי מים בישראל: רשימת המאגרים, נפח ושנת הקמה",
            "description": description,
            "name": "מאגרי המים העיליים בישראל",
            "alternate_names": ["רשימת מאגרי המים בישראל", "מאגרי קולחין בישראל",
                                "מאגרי שאיבה", "מאגרי מים עיליים", "מאגרי מים לחקלאות"],
        },
    }
    if len(yrs):
        agent_data["temporal_coverage"] = f"{int(yrs.min())}/{int(yrs.max())}"

    labels["lookup_note"] = ("חיפוש חי בכל רשומות המאגר: שם המאגר, סוג, בעלות, מקור המים,"
                             " מכוני מים משויכים וחיפוי.")
    labels["types_aria"] = "מספר המאגרים והקיבולת לפי סוג מאגר"
    labels["size_aria"] = "התפלגות המאגרים לפי נפח ונתח הקיבולת בכל קבוצת גודל"
    labels["top_aria"] = f"{fmt.int_he(len(top))} המאגרים הגדולים לפי נפח, במיליוני מ\"ק"
    labels["decades_aria"] = "מאגרים שהוקמו בכל עשור וקיבולת מצטברת"
    labels["quality_aria"] = "איכות המים במאגרים שעבורם היא מצוינת"
    labels["source_aria"] = "מספר המאגרים והקיבולת לפי מקור המים"
    labels["owners_aria"] = "הבעלים עם הכי הרבה מאגרים"
    labels["lining_aria"] = "סוג חיפוי המאגר"
    labels["depth_aria"] = "התפלגות עומק המאגרים במטרים"
    labels["scatter_aria"] = "שטח המאגר בדונם מול נפחו באלפי מ\"ק, בסקאלה לוגריתמית"
    labels["complete_aria"] = "שיעור המאגרים שבהם מולא כל שדה"
    labels.setdefault("top_lede", "")
    labels.setdefault("scatter_lede", "")

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
    }
