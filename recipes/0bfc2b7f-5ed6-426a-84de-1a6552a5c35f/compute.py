"""Urban renewal compounds (מתחמי התחדשות עירונית), Ministry of Construction
and Housing: one row per compound, with its city, planning status, declaration
track and date, the plan's validity year, and existing / proposed / permitted
housing units."""
import pandas as pd
from govlib import fmt, frame

# Planning stages in pipeline order; unknown statuses follow, by count.
STATUS_ORDER = [
    "תכנון ראשוני",
    "תכנון סטטוטורי",
    "תכנית מאושרת לפני מימוש",
    "תכנית מאושרת - אחרי רישוי",
    "תכנית מאושרת במימוש",
]
STATUS_SHORT = {
    "תכנון ראשוני": "תכנון ראשוני",
    "תכנון סטטוטורי": "תכנון סטטוטורי",
    "תכנית מאושרת לפני מימוש": "מאושרת, לפני מימוש",
    "תכנית מאושרת - אחרי רישוי": "מאושרת, אחרי רישוי",
    "תכנית מאושרת במימוש": "מאושרת, במימוש",
}
STATUS_COLOR = {
    "תכנון ראשוני": "#c3cfe7",
    "תכנון סטטוטורי": "#6c9fd8",
    "תכנית מאושרת לפני מימוש": "#0068f5",
    "תכנית מאושרת - אחרי רישוי": "#0b3668",
    "תכנית מאושרת במימוש": "#198754",
}
OTHER_COLORS = ["#ffc107", "#6c757d", "#dc3545", "#0dcaf0"]
APPROVED_PREFIX = "תכנית מאושרת"
TRACK_ORDER = ["מיסוי", "רשויות", "טרם הוכרז"]
NO_TRACK = "לא צוין"
TRACK_SHORT = {"מיסוי": "מסלול מיסוי", "רשויות": "מסלול רשויות"}

TOP_CITIES = 15
YEAR_SPAN = 20  # bars per year chart; earlier years fold into one "עד" bar
SIZE_BINS = [(0, 100), (100, 250), (250, 500), (500, 1000), (1000, 2000), (2000, None)]
MULT_BINS = [(0, 2), (2, 3), (3, 4), (4, 5), (5, 7), (7, None)]


def _bin_label(lo, hi, digits=0):
    f = (lambda v: f"{v:,}") if digits == 0 else (lambda v: f"{v:g}")
    if hi is None:
        return f"{f(lo)} ומעלה"
    if lo == 0:
        return f"עד {f(hi)}" if digits else f"פחות מ-{f(hi)}"
    return f"{f(lo)}-{f(hi)}" if digits else f"{f(lo)}-{f(hi - 1)}"


def _bins(values, bins, digits=0):
    labels, counts = [], []
    for lo, hi in bins:
        sel = values >= lo
        if hi is not None:
            sel &= values < hi
        labels.append(_bin_label(lo, hi, digits))
        counts.append(int(sel.sum()))
    return labels, counts


def _status_label(s):
    return STATUS_SHORT.get(s, s)


def _year_axis(years: pd.Series):
    """Year labels for a count series: the last YEAR_SPAN years one by one,
    everything before folded into "עד <year>"."""
    ys = years.dropna().astype(int)
    if ys.empty:
        return [], {}
    hi = int(ys.max())
    lo_all = int(ys.min())
    start = max(lo_all, hi - YEAR_SPAN + 1)
    keys = {}
    labels = []
    if lo_all < start:
        labels.append(f"עד {start - 1}")
    for y in range(start, hi + 1):
        labels.append(str(y))
    for y in sorted(set(ys.tolist())):
        keys[y] = labels[0] if y < start else str(y)
    return labels, keys


def compute(frames):
    raw = frames["main"].copy()
    n_raw = len(raw)

    df = pd.DataFrame({
        "id": frame.num(raw["MisparMitham"]),
        "city": frame.clean_series(raw["Yeshuv"]),
        "code": frame.clean_series(raw["SemelYeshuv"]),
        "name": frame.clean_series(raw["ShemMitcham"]),
        "kayam_s": frame.clean_series(raw["YachadKayam"]),
        "mutza_s": frame.clean_series(raw["YachadMutza"]),
        "kayam": frame.num(raw["YachadKayam"]),
        "mutza": frame.num(raw["YachadMutza"]),
        "heterim": frame.num(raw["SachHeterim"]),
        "date": pd.to_datetime(frame.clean_series(raw["TaarichHachraza"]),
                               format="%d/%m/%Y", errors="coerce"),
        "valid_year": frame.num(raw["ShnatMatanTokef"]),
        "track": frame.clean_series(raw["Maslul"]),
        "exec": frame.clean_series(raw["Bebitzua"]),
        "status": frame.clean_series(raw["Status"]),
    })

    # A row whose cells slid one column over (a stray delimiter upstream):
    # its unit counts are text and its status is a ';'-joined run of cells.
    bad = (
        ((df["kayam_s"] != "") & df["kayam"].isna())
        | ((df["mutza_s"] != "") & df["mutza"].isna())
        | df["status"].str.contains(";", regex=False)
        | (df["status"].str.len() > 80)
    )
    n_bad = int(bad.sum())
    df = df[~bad].copy()

    # City: grouped by code, named by its most common spelling; a row with a
    # blank name takes its code's name. A row with neither can't be placed.
    df["code"] = df["code"].where(df["code"] != "", df["city"])
    named = df[(df["city"] != "") & (df["code"] != "")]
    names = (named.groupby(["code", "city"]).size().reset_index(name="k")
             .sort_values(["code", "k", "city"], ascending=[True, False, True], kind="stable")
             .drop_duplicates("code"))
    df["city"] = df["code"].map(dict(zip(names["code"], names["city"]))).fillna("")
    no_place = df["city"] == ""
    n_noplace = int(no_place.sum())
    df = df[~no_place].copy()
    n = len(df)
    if n == 0:
        raise ValueError("no usable rows")

    # Negative unit counts are entry errors: treated as missing.
    df.loc[df["kayam"] < 0, "kayam"] = float("nan")
    df.loc[df["mutza"] < 0, "mutza"] = float("nan")
    df.loc[df["heterim"] < 0, "heterim"] = float("nan")
    df.loc[(df["valid_year"] < 1900) | (df["valid_year"] > 2100), "valid_year"] = float("nan")
    df["track"] = df["track"].where(df["track"] != "", NO_TRACK)
    df["status"] = df["status"].where(df["status"] != "", NO_TRACK)
    df["approved"] = df["status"].str.startswith(APPROVED_PREFIX)
    df["id_sort"] = df["id"].fillna(-1)

    mutza_sum = float(df["mutza"].sum())
    kayam_sum = float(df["kayam"].sum())
    both = df[(df["kayam"] > 0) & (df["mutza"] > 0)]
    net_sum = float((both["mutza"] - both["kayam"]).sum())
    het = df[df["heterim"] > 0]
    het_sum = float(het["heterim"].sum())
    n_cities = int(df["city"].nunique())
    n_approved = int(df["approved"].sum())
    n_exec = int((df["exec"] == "כן").sum())
    mult = (both["mutza"] / both["kayam"])
    mult_med = float(mult.median()) if len(mult) else None

    # ---- statuses
    st_counts = frame.ranked(df["status"])
    statuses = [s for s in STATUS_ORDER if s in st_counts.index] + \
        [s for s in st_counts.index if s not in STATUS_ORDER]
    st_units = df.groupby("status")["mutza"].sum()
    status_rows = []
    for s in statuses:
        c = int(st_counts[s])
        u = float(st_units.get(s, 0))
        status_rows.append([_status_label(s), fmt.int_he(c), fmt.pct(c / n),
                            fmt.int_he(u), fmt.pct(u / mutza_sum) if mutza_sum else "–"])
    chart_status = {
        "labels": [_status_label(s) for s in statuses],
        "counts": [int(st_counts[s]) for s in statuses],
        "units": [round(float(st_units.get(s, 0))) for s in statuses],
    }
    extra = [s for s in statuses if s not in STATUS_COLOR]
    status_colors = [STATUS_COLOR.get(s) or OTHER_COLORS[extra.index(s) % len(OTHER_COLORS)]
                     for s in statuses]
    chart_status["colors"] = status_colors

    # ---- tracks
    tr_counts = frame.ranked(df["track"])
    tracks = [t for t in TRACK_ORDER if t in tr_counts.index] + \
        [t for t in tr_counts.index if t not in TRACK_ORDER and t != NO_TRACK] + \
        ([NO_TRACK] if NO_TRACK in tr_counts.index else [])
    tr_units = df.groupby("track")["mutza"].sum()
    track_rows = [[t, fmt.int_he(int(tr_counts[t])), fmt.pct(int(tr_counts[t]) / n),
                   fmt.int_he(float(tr_units.get(t, 0)))] for t in tracks]
    chart_track = {"names": tracks, "values": [int(tr_counts[t]) for t in tracks],
                   "units": [round(float(tr_units.get(t, 0))) for t in tracks]}

    # ---- declarations per year, by track
    decl = df[df["date"].notna()].copy()
    decl["year"] = decl["date"].dt.year
    years_labels, years_key = _year_axis(decl["year"])
    decl["ylab"] = decl["year"].map(years_key)
    decl_tracks = [t for t in tracks if t in set(decl["track"])]
    chart_decl = {"labels": years_labels, "series": []}
    for t in decl_tracks:
        vc = decl[decl["track"] == t]["ylab"].value_counts()
        chart_decl["series"].append({"name": TRACK_SHORT.get(t, t),
                                     "data": [int(vc.get(lab, 0)) for lab in years_labels]})
    decl_tot = decl["ylab"].value_counts()
    last_date = decl["date"].max() if len(decl) else None
    # The data carries no publication date, so the year of the latest
    # declaration may still be open: it is never used in the trend, and its
    # count is quoted "as of" that declaration.
    latest_year = int(last_date.year) if last_date is not None else None
    decl_rows = []
    for lab in years_labels:
        row = [lab, fmt.int_he(int(decl_tot.get(lab, 0)))]
        for s in chart_decl["series"]:
            row.append(fmt.int_he(s["data"][years_labels.index(lab)]))
        row.append(f"עד {fmt.d_he(last_date)}" if latest_year and lab == str(latest_year) else "")
        decl_rows.append(row)
    decl_cols = ["שנה", "מתחמים שהוכרזו"] + [s["name"] for s in chart_decl["series"]] + ["הערה"]

    # ---- plan validity year
    vy = df[df["valid_year"].notna()].copy()
    vy["year"] = vy["valid_year"].astype(int)
    vy_labels, vy_key = _year_axis(vy["year"])
    vy["ylab"] = vy["year"].map(vy_key)
    vy_counts = vy["ylab"].value_counts()
    vy_units = vy.groupby("ylab")["mutza"].sum()
    chart_valid = {"labels": vy_labels,
                   "counts": [int(vy_counts.get(lab, 0)) for lab in vy_labels],
                   "units": [round(float(vy_units.get(lab, 0))) for lab in vy_labels]}
    valid_rows = [[lab, fmt.int_he(int(vy_counts.get(lab, 0))), fmt.int_he(float(vy_units.get(lab, 0)))]
                  for lab in vy_labels]

    # ---- cities
    city_n = df.groupby("city").size()
    city_u = df.groupby("city")["mutza"].sum()
    city_k = df.groupby("city")["kayam"].sum()
    city_appr = df[df["approved"]].groupby("city").size()
    city_tbl = pd.DataFrame({"n": city_n, "u": city_u, "k": city_k}).reset_index()
    by_n = city_tbl.sort_values(["n", "u", "city"], ascending=[False, False, True], kind="stable")
    top_n = by_n["city"].head(TOP_CITIES).tolist()
    chart_cities = {"names": top_n, "series": [], "colors": status_colors}
    for s in statuses:
        vc = df[df["status"] == s].groupby("city").size()
        chart_cities["series"].append({"name": _status_label(s),
                                       "data": [int(vc.get(c, 0)) for c in top_n]})
    cities_rows = []
    for c in top_n:
        cn = int(city_n[c])
        ca = int(city_appr.get(c, 0))
        cities_rows.append([c, fmt.int_he(cn), fmt.pct(cn / n), fmt.int_he(ca), fmt.pct(ca / cn)])
    rest_n = n - int(city_n[top_n].sum())

    by_u = city_tbl.sort_values(["u", "n", "city"], ascending=[False, False, True], kind="stable")
    top_u = by_u["city"].head(TOP_CITIES).tolist()
    chart_units = {"names": top_u,
                   "kayam": [round(float(city_k.get(c, 0))) for c in top_u],
                   "added": [round(float(city_u.get(c, 0) - city_k.get(c, 0))) for c in top_u]}
    chart_units["added"] = [max(v, 0) for v in chart_units["added"]]
    units_rows = []
    for c in top_u:
        # The ratio of the two columns shown beside it.
        kc, mc = float(city_k.get(c, 0)), float(city_u.get(c, 0))
        m = mc / kc if kc > 0 else None
        units_rows.append([c, fmt.int_he(float(city_k.get(c, 0))), fmt.int_he(float(city_u.get(c, 0))),
                           fmt.pct(float(city_u.get(c, 0)) / mutza_sum) if mutza_sum else "–",
                           fmt.num_he(m) if m is not None else "–"])

    # ---- compound size and density multiplier
    sizes = df["mutza"].dropna()
    sizes = sizes[sizes > 0]
    size_labels, size_counts = _bins(sizes, SIZE_BINS)
    size_rows = [[lab, fmt.int_he(c), fmt.pct(c / len(sizes)) if len(sizes) else "–"]
                 for lab, c in zip(size_labels, size_counts)]
    mult_labels, mult_counts = _bins(mult, MULT_BINS, digits=1)
    mult_rows = [[lab, fmt.int_he(c), fmt.pct(c / len(mult)) if len(mult) else "–"]
                 for lab, c in zip(mult_labels, mult_counts)]

    # ---- declaration vs plan validity, per declared track
    order = df[df["date"].notna() & df["valid_year"].notna()].copy()
    order["lag"] = order["date"].dt.year - order["valid_year"].astype(int)
    order_tracks = [t for t in tracks if t in set(order["track"])]
    order_cats = ["התוכנית בתוקף לפני שנת ההכרזה", "באותה שנה", "ההכרזה לפני מתן התוקף"]
    order_stats = {}
    order_rows = []
    for t in order_tracks:
        sub = order[order["track"] == t]
        before = int((sub["lag"] > 0).sum())
        same = int((sub["lag"] == 0).sum())
        after = int((sub["lag"] < 0).sum())
        order_stats[t] = (len(sub), before, same, after)
        order_rows.append([TRACK_SHORT.get(t, t), fmt.int_he(len(sub)), fmt.int_he(before),
                           fmt.int_he(same), fmt.int_he(after)])
    # Shares from the same counts; the last segment closes the bar at 100.
    order_pcts = []
    for t in order_tracks:
        tot, before, same, _after = order_stats[t]
        a = round(before / tot * 100, 1)
        b = round(same / tot * 100, 1)
        order_pcts.append([a, b, round(100 - a - b, 1)])
    chart_order = {"names": [TRACK_SHORT.get(t, t) for t in order_tracks],
                   "series": [{"name": cat, "data": [p[i] for p in order_pcts]}
                              for i, cat in enumerate(order_cats)]}

    # ---- permits by city
    het_city = het.groupby("city")["heterim"].sum()
    het_city_n = het.groupby("city").size()
    het_tbl = pd.DataFrame({"h": het_city, "n": het_city_n}).reset_index() \
        .sort_values(["h", "n", "city"], ascending=[False, False, True], kind="stable").head(10)
    chart_permits = {"names": het_tbl["city"].tolist(),
                     "values": [round(float(v)) for v in het_tbl["h"]]}
    permit_rows = [[r.city, fmt.int_he(r.h), fmt.int_he(r.n)] for r in het_tbl.itertuples()]
    het_mutza = float(het["mutza"].sum())

    # ---- largest compounds
    big = df[df["mutza"].notna()].sort_values(["mutza", "id_sort", "name"],
                                              ascending=[False, True, True], kind="stable").head(10)
    big_rows = [[r.name or "–", r.city, fmt.int_he(r.kayam) if pd.notna(r.kayam) else "–",
                 fmt.int_he(r.mutza), _status_label(r.status), r.track] for r in big.itertuples()]

    # ---------------- KPIs
    appr_share = n_approved / n
    kpis = {
        "total": {"value": n, "display": fmt.int_he(n), "tone": "brand"},
        "cities": {"value": n_cities, "display": fmt.int_he(n_cities), "tone": "brand"},
        "mutza": {"value": int(mutza_sum), "display": fmt.int_he(mutza_sum), "tone": "info"},
        "kayam": {"value": int(kayam_sum), "display": fmt.int_he(kayam_sum), "tone": "brand"},
        "approved": {"value": round(appr_share * 100, 1), "display": fmt.pct(appr_share),
                     "tone": "ok" if appr_share >= 0.5 else "warn"},
        "heterim": {"value": int(het_sum), "display": fmt.int_he(het_sum), "tone": "ok"},
        "exec": {"value": n_exec, "display": fmt.int_he(n_exec), "tone": "brand"},
    }
    if mult_med is not None:
        kpis["mult"] = {"value": round(mult_med, 2), "display": fmt.num_he(mult_med), "tone": "info"}

    # ---------------- insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # 1. leading city
    def ins_leader():
        if len(by_n) < 2:
            return None
        a, b = by_n.iloc[0], by_n.iloc[1]
        if a["n"] < 1.2 * b["n"] or a["n"] / n < 0.08:
            return None
        ua = float(city_u.get(a["city"], 0))
        return (f"{a['city']} מובילה עם {fmt.int_he(a['n'])} מתחמים ({fmt.pct(a['n'] / n)} מכלל המתחמים) "
                f"ו-{fmt.int_he(ua)} יחידות דיור מוצעות, לפני {b['city']} עם {fmt.int_he(b['n'])} מתחמים.")
    add("leader", ins_leader())

    # 2. pipeline: proposed units still in planning
    def ins_pipeline():
        if not mutza_sum:
            return None
        plan_u = float(df[~df["approved"]]["mutza"].sum())
        share = plan_u / mutza_sum
        n_plan = int((~df["approved"]).sum())
        if n_plan == 0:
            return None
        appr_u = mutza_sum - plan_u
        if share >= 0.5:
            return (f"רוב יחידות הדיור המוצעות עדיין בשלבי תכנון: {fmt.int_he(plan_u)} יח״ד ({fmt.pct(share)}) "
                    f"ב-{fmt.int_he(n_plan)} מתחמים שתוכניתם טרם אושרה, לעומת {fmt.int_he(appr_u)} יח״ד "
                    f"בתוכניות מאושרות.")
        return (f"רוב יחידות הדיור המוצעות כבר בתוכניות מאושרות: {fmt.int_he(appr_u)} יח״ד "
                f"({fmt.pct(1 - share)}), לעומת {fmt.int_he(plan_u)} יח״ד ב-{fmt.int_he(n_plan)} מתחמים "
                f"שתוכניתם טרם אושרה.")
    add("pipeline", ins_pipeline())

    # 3. declaration trend over full years
    def ins_trend():
        if last_date is None:
            return None
        yc = decl["year"].value_counts()
        first = int(decl["year"].min())
        last = latest_year - 1
        if last not in yc.index:
            return None
        span = list(range(max(last - 5, first), last))
        if len(span) < 3:
            return None
        avg = sum(int(yc.get(y, 0)) for y in span) / len(span)
        cur = int(yc[last])
        if avg <= 0:
            return None
        ratio = cur / avg
        if ratio >= 1.5:
            word = f"פי {fmt.num_he(ratio)} מהממוצע השנתי"
        elif ratio <= 0.67:
            word = "ירידה לעומת הממוצע השנתי"
        else:
            word = "בדומה לממוצע השנתי"
        txt = (f"בשנת {last} הוכרזו {fmt.int_he(cur)} מתחמים, {word} בשנים {span[0]}-{span[-1]} "
               f"({fmt.num_he(avg)} בשנה).")
        txt += (f" נכון לתאריך ההכרזה האחרון ({fmt.d_he(last_date)}) הוכרזו "
                f"{fmt.int_he(int(yc.get(latest_year, 0)))} מתחמים בשנת {latest_year}.")
        return txt
    add("trend", ins_trend())

    # 4. order of declaration vs validity by track
    def ins_order():
        parts = []
        for t in ("מיסוי", "רשויות"):
            if t not in order_stats:
                continue
            tot, before, same, after = order_stats[t]
            if tot < 20:
                continue
            if (before + same) / tot >= 0.6:
                parts.append(f"ב{TRACK_SHORT[t]} {fmt.pct((before + same) / tot)} מהמתחמים הוכרזו "
                             f"בשנת מתן התוקף לתוכנית או אחריה")
            elif after / tot >= 0.6:
                parts.append(f"ב{TRACK_SHORT[t]} {fmt.pct(after / tot)} מהמתחמים הוכרזו לפני שנת מתן התוקף")
        if not parts:
            return None
        return "סדר השלבים תלוי במסלול: " + ", ואילו ".join(parts) + "."
    add("order", ins_order())

    # 5. density multiplier
    def ins_mult():
        if mult_med is None or len(mult) < 20:
            return None
        hi = int((mult >= 5).sum())
        return (f"המכפיל החציוני הוא {fmt.num_he(mult_med)}: מתחם טיפוסי מציע פי {fmt.num_he(mult_med)} "
                f"יחידות דיור מהקיימות בו. ב-{fmt.int_he(hi)} מתחמים ({fmt.pct(hi / len(mult))}) המכפיל 5 ומעלה, "
                f"ובסך הכול {fmt.int_he(len(mult))} המתחמים עם נתוני יח״ד קיימות ומוצעות מוסיפים "
                f"{fmt.int_he(net_sum)} יח״ד נטו.")
    add("mult", ins_mult())

    # 6. permits
    def ins_permits():
        if len(het) < 5 or not het_mutza:
            return None
        return (f"ב-{fmt.int_he(len(het))} מתחמים כבר ניתנו היתרי בנייה ל-{fmt.int_he(het_sum)} יחידות דיור, "
                f"{fmt.pct(het_sum / het_mutza)} מ-{fmt.int_he(het_mutza)} יח״ד המוצעות בהם. "
                f"{fmt.int_he(n_exec)} מתחמים מסומנים כנמצאים בביצוע.")
    add("permits", ins_permits())

    # 7. undeclared
    def ins_undeclared():
        nd = int(df["date"].isna().sum())
        if nd < 10:
            return None
        nodate = df[df["date"].isna()]
        tbd = int((nodate["track"] == "טרם הוכרז").sum())
        nt = int((nodate["track"] == NO_TRACK).sum())
        bits = []
        if tbd:
            bits.append(f"{fmt.int_he(tbd)} מהם מסומנים במפורש \"טרם הוכרז\"")
        if nt:
            bits.append(f"ב-{fmt.int_he(nt)} גם לא צוין מסלול")
        tail = f": {', '.join(bits)}" if bits else ""
        return (f"תאריך ההכרזה חסר ב-{fmt.int_he(nd)} מתוך {fmt.int_he(n)} המתחמים ברשימה "
                f"({fmt.pct(nd / n)}){tail}.")
    add("undeclared", ins_undeclared())

    # 8. largest compound
    def ins_largest():
        if big.empty:
            return None
        r = big.iloc[0]
        if r["mutza"] < 3 * float(sizes.median()):
            return None
        return (f"המתחם הגדול ביותר הוא \"{r['name']}\" ב{r['city']}, עם {fmt.int_he(r['mutza'])} "
                f"יחידות דיור מוצעות (סטטוס: {_status_label(r['status'])}).")
    add("largest", ins_largest())

    # ---------------- text
    first_y = int(decl["year"].min()) if len(decl) else None
    last_y = int(decl["year"].max()) if len(decl) else None
    notes = []
    if n_bad:
        notes.append("רשומה אחת פגומה (ערכים שהוזזו בין העמודות) הושמטה מהניתוח." if n_bad == 1 else
                     f"{fmt.int_he(n_bad)} רשומות פגומות (ערכים שהוזזו בין העמודות) הושמטו מהניתוח.")
    if n_noplace:
        notes.append("רשומה אחת ללא שם יישוב וללא סמל יישוב הושמטה מהניתוח." if n_noplace == 1 else
                     f"{fmt.int_he(n_noplace)} רשומות ללא שם יישוב וללא סמל יישוב הושמטו מהניתוח.")
    bad_note = " ".join(notes)
    top_city = by_n.iloc[0]["city"]
    lede = (f"רשימת משרד הבינוי והשיכון כוללת {fmt.int_he(n)} מתחמי התחדשות עירונית (פינוי בינוי ועוד) "
            f"ב-{fmt.int_he(n_cities)} יישובים, עם {fmt.int_he(kayam_sum)} יחידות דיור קיימות "
            f"ו-{fmt.int_he(mutza_sum)} יחידות דיור מוצעות. {fmt.pct(appr_share)} מהמתחמים "
            f"נמצאים בתוכנית מאושרת, והיישוב עם הכי הרבה מתחמים הוא {top_city}.")
    summary = (f"{fmt.int_he(n)} מתחמי התחדשות עירונית ב-{fmt.int_he(n_cities)} יישובים, עם "
               f"{fmt.int_he(mutza_sum)} יחידות דיור מוצעות במקום {fmt.int_he(kayam_sum)} קיימות; "
               f"{fmt.pct(appr_share)} מהם בתוכנית מאושרת.")
    seo_desc = (f"איתור מתחם התחדשות עירונית ופינוי בינוי לפי יישוב, שם מתחם או מספר תוכנית: "
                f"{fmt.int_he(n)} מתחמים, {fmt.int_he(mutza_sum)} יח״ד מוצעות.")

    st_top = statuses[int(pd.Series(chart_status["counts"]).idxmax())]
    labels = {
        "lede": lede,
        "bad_note": bad_note,
        "status_lede": (f"השלב הנפוץ ביותר הוא \"{_status_label(st_top)}\" עם {fmt.int_he(int(st_counts[st_top]))} "
                        f"מתחמים. העמודות מציגות את מספר המתחמים ואת יחידות הדיור המוצעות בכל שלב."),
        "status_aria": "מתחמים ויחידות דיור מוצעות לפי סטטוס התכנון",
        "track_lede": (f"{fmt.int_he(int(tr_counts.get('מיסוי', 0)))} מתחמים הוכרזו במסלול מיסוי "
                       f"ו-{fmt.int_he(int(tr_counts.get('רשויות', 0)))} במסלול רשויות."),
        "track_aria": "מתחמים לפי מסלול ההכרזה",
        "decl_lede": (f"{fmt.int_he(len(decl))} מתחמים נושאים תאריך הכרזה, משנת {first_y} ועד "
                      f"{fmt.d_he(last_date)}." if len(decl) else "")
                     + (f" שנת {latest_year} מוצגת עד ההכרזה האחרונה." if latest_year else ""),
        "decl_aria": "מספר המתחמים שהוכרזו בכל שנה לפי מסלול",
        "valid_lede": (f"{fmt.int_he(len(vy))} מתחמים עם שנת מתן תוקף לתוכנית. "
                       f"הקו מציג את יחידות הדיור המוצעות במתחמים שתוכניתם קיבלה תוקף באותה שנה."),
        "valid_aria": "מתחמים ויחידות דיור מוצעות לפי שנת מתן התוקף לתוכנית",
        "cities_lede": (f"{fmt.int_he(len(top_n))} היישובים עם הכי הרבה מתחמים, לפי שלב התכנון. "
                        f"ב-{fmt.int_he(n_cities - len(top_n))} היישובים האחרים יש עוד {fmt.int_he(rest_n)} מתחמים."
                        if n_cities > len(top_n) else "כל היישובים ברשימה, לפי שלב התכנון."),
        "cities_aria": "מתחמים לפי יישוב ושלב תכנון",
        "units_lede": "היישובים עם הכי הרבה יחידות דיור מוצעות: החלק הכהה הוא יחידות הדיור הקיימות והחלק הבהיר התוספת.",
        "units_aria": "יחידות דיור קיימות ותוספת לפי יישוב",
        "size_lede": (f"חציון המתחם: {fmt.int_he(float(sizes.median()))} יחידות דיור מוצעות." if len(sizes) else ""),
        "size_aria": "התפלגות המתחמים לפי מספר יחידות הדיור המוצעות",
        "mult_lede": (f"מכפיל = יח״ד מוצעות חלקי יח״ד קיימות, ב-{fmt.int_he(len(mult))} מתחמים עם שני הנתונים."
                      if len(mult) else ""),
        "mult_aria": "התפלגות המתחמים לפי מכפיל הציפוף",
        "order_lede": (f"השוואת שנת ההכרזה לשנת מתן התוקף לתוכנית, ב-{fmt.int_he(len(order))} מתחמים עם שני הנתונים "
                       f"(שיעור מהמתחמים בכל מסלול)."),
        "order_aria": "סדר ההכרזה ומתן התוקף לפי מסלול",
        "permits_lede": (f"{fmt.int_he(het_sum)} יחידות דיור קיבלו היתר ב-{fmt.int_he(len(het))} מתחמים. "
                         f"עשרת היישובים המובילים:"),
        "permits_aria": "יחידות דיור שקיבלו היתר לפי יישוב",
        "big_caption": "עשרת המתחמים עם הכי הרבה יחידות דיור מוצעות",
    }

    flags = {
        "decl": len(years_labels) >= 2,
        "valid": len(vy_labels) >= 2,
        "mult": len(mult) >= 10,
        "order": len(order_tracks) >= 1 and len(order) >= 10,
        "permits": len(het_tbl) >= 3,
    }

    temporal = f"{first_y}/{last_y}" if first_y else None
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "מתחמי התחדשות עירונית ופינוי בינוי: רשימה וסטטוס",
            "description": seo_desc,
            "name": "מתחמי התחדשות עירונית",
            "alternate_names": ["התחדשות עירונית", "מתחמי פינוי בינוי", "מתחמי התחדשות עירונית מוכרזים",
                                "רשימת מתחמי פינוי בינוי"],
        },
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "status": chart_status, "track": chart_track, "decl": chart_decl,
            "valid": chart_valid, "cities": chart_cities, "units": chart_units,
            "size": {"labels": size_labels, "values": size_counts},
            "mult": {"labels": mult_labels, "values": mult_counts},
            "order": chart_order, "permits": chart_permits,
        },
        "tables": {
            "status": status_rows, "track": track_rows, "decl": decl_rows, "decl_cols": decl_cols,
            "valid": valid_rows, "cities": cities_rows, "units": units_rows, "size": size_rows,
            "mult": mult_rows, "order": order_rows, "permits": permit_rows, "big": big_rows,
        },
        "insights": insights,
        "labels": labels,
        "flags": flags,
        "meta": {"rows_raw": n_raw, "rows_bad": n_bad, "rows_no_place": n_noplace},
    }
