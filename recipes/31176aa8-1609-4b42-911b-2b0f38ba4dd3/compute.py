"""דירה בהנחה / מחיר למשתכן: מעקב אחר הגרלות (משרד הבינוי והשיכון).

One row per lottery. A project's first lottery ("ראשונה") offers its flats;
a continuation lottery ("המשך") re-offers the flats left over, to a wider
pool of registrants. So flats and demand ratios come from first lotteries
only (continuations would count the same flats twice), while lottery
counts, registrations and winners cover both kinds.
"""
import pandas as pd
from govlib import fmt, frame

FIRST = "ראשונה"
CONT = "המשך"
TOP_N = 15
MIN_CITY_UNITS = 300      # cities in the demand ranking / scatter
MAX_ROUNDS = 16           # centralized rounds shown (latest ones)
DEMAND_MOVE = 0.15        # relative change that counts as a rise/fall
PRICE_MOVE = 0.05

NUMERIC = [
    "Winners", "WinnersSeriesA", "WinnersSeriesB", "WinnersSeriesC",
    "WinnersMeshapryDiur", "WinnersBneyMakom",
    "Subscribers", "SubscribersBenyMakom",
    "LotteryHousingUnits", "LotteryNativeHousingUnits", "PriceForMeter",
]

# Known eligibility codes in a readable order; unknown values follow by name.
ELIG_ORDER = ["א", "א+ב", "א+ב+ג", "חסרי ומשפרי דיור", "לא מוגדר"]
ELIG_LABEL = {
    "א": "קבוצה א",
    "א+ב": "קבוצות א+ב",
    "א+ב+ג": "קבוצות א+ב+ג",
    "חסרי ומשפרי דיור": "חסרי ומשפרי דיור",
    "לא מוגדר": "לא מוגדר",
}
STATUS_ORDER = ["בתהליכי הגרלה", "בחירת דירות", "בקרת חוזים", "בקרה לאחר אכלוס"]


def _i(v):
    return round(float(v)) if pd.notna(v) else 0


def _ordered(values, known):
    """Known values first in their order, then the rest by name."""
    vals = sorted(set(values))
    return [k for k in known if k in vals] + [v for v in vals if v not in known]


def _ratio(a, b):
    return float(a) / float(b) if b else None


def _round1(v):
    return None if v is None else round(float(v), 1)


def compute(frames):
    df = frames["main"].copy()
    for c in NUMERIC:
        df[c] = frame.num(df[c])
    for c in ["LotteryType", "LamasName", "ProviderName", "Eligibility", "MarketingRep",
              "ProjectStatus", "ConstructionPermitName",
              "CentralizationType", "ProjectId", "LotteryId"]:
        df[c] = frame.clean_series(df[c])
    df["dt"] = pd.to_datetime(df["LotteryExecutionDate"].str.strip(), errors="coerce",
                              format="%Y-%m-%d %H:%M:%S")
    df["year"] = df["dt"].dt.year
    # Total order for every later groupby / first().
    df = df.sort_values(["LotteryId", "dt"], kind="stable").reset_index(drop=True)

    first = df[df["LotteryType"] == FIRST]
    cont = df[df["LotteryType"] == CONT]
    dated = df[df["dt"].notna()]
    undated = int(len(df) - len(dated))

    n_lot = len(df)
    n_first, n_cont = len(first), len(cont)
    units_first = _i(first["LotteryHousingUnits"].sum())
    units_cont = _i(cont["LotteryHousingUnits"].sum())
    subs_all = _i(df["Subscribers"].sum())
    winners = _i(df["Winners"].sum())
    n_cities = int(df.loc[df["LamasName"] != "", "LamasName"].nunique())
    n_projects = int(df.loc[df["ProjectId"] != "", "ProjectId"].nunique())
    n_providers = int(df.loc[df["ProviderName"] != "", "ProviderName"].nunique())

    last_dt = dated["dt"].max() if len(dated) else None
    first_dt = dated["dt"].min() if len(dated) else None
    years = sorted(int(y) for y in dated["year"].unique())
    # The last year is partial when the data stops before December AND it
    # covers fewer distinct months than a typical earlier year (a full year
    # whose final round fell in November is not partial).
    months = dated.groupby("year")["dt"].apply(lambda s: s.dt.month.nunique())
    partial_last = bool(
        last_dt is not None and last_dt.month < 12 and len(years) > 1
        and months[years[-1]] < months[years[:-1]].median()
    )
    full_years = years[:-1] if partial_last else years
    year_lbl = [str(y) for y in years]

    def year_note():
        parts = []
        if partial_last:
            parts.append(f"שנת {years[-1]} חלקית: הנתונים מסתיימים ב-{fmt.d_he(last_dt)}.")
        if undated:
            parts.append("הגרלה אחת ללא תאריך עריכה אינה נכללת בפילוח השנתי." if undated == 1 else
                         f"{fmt.int_he(undated)} הגרלות ללא תאריך עריכה אינן נכללות בפילוח השנתי.")
        return " ".join(parts)

    # ---- by year: lotteries, units, winners ---------------------------------
    fy = first[first["dt"].notna()].groupby("year")
    cy = cont[cont["dt"].notna()].groupby("year")
    ay = dated.groupby("year")
    f_n = fy.size().reindex(years, fill_value=0)
    c_n = cy.size().reindex(years, fill_value=0)
    f_units = fy["LotteryHousingUnits"].sum().reindex(years, fill_value=0)
    c_units = cy["LotteryHousingUnits"].sum().reindex(years, fill_value=0)
    f_subs = fy["Subscribers"].sum().reindex(years, fill_value=0)
    a_win = ay["Winners"].sum().reindex(years, fill_value=0)
    ratio_y = {y: _ratio(f_subs[y], f_units[y]) for y in years}

    charts = {}
    tables = {}
    labels = {}
    flags = {}

    charts["years"] = {
        "x": year_lbl,
        "first": [int(f_n[y]) for y in years],
        "cont": [int(c_n[y]) for y in years],
        "units": [_i(f_units[y]) for y in years],
    }
    tables["years"] = [[str(y), fmt.int_he(f_n[y]), fmt.int_he(c_n[y]), fmt.int_he(f_units[y]),
                        fmt.int_he(c_units[y]), fmt.int_he(a_win[y])] for y in years]
    peak_units_y = max(years, key=lambda y: (f_units[y], -y)) if years else None

    # Peak demand among full years only: a partial year's single round is not a "year".
    peak_ys = [y for y in full_years if ratio_y.get(y) is not None]
    peak_ratio_y = max(peak_ys, key=lambda y: (ratio_y[y], -y)) if peak_ys else None
    charts["demand"] = {
        "x": year_lbl,
        "subs": [_i(f_subs[y]) for y in years],
        "ratio": [_round1(ratio_y[y]) for y in years],
        "peak": years.index(peak_ratio_y) if peak_ratio_y is not None else None,
    }
    tables["demand"] = [[str(y), fmt.int_he(f_subs[y]), fmt.int_he(f_units[y]),
                         fmt.num_he(ratio_y[y]) if ratio_y[y] is not None else "-"] for y in years]

    # ---- price per m² (first lotteries, one value per lottery) --------------
    fp = first[first["dt"].notna() & (first["PriceForMeter"] > 0)]
    no_price = int(len(first) - len(first[first["PriceForMeter"] > 0]))
    price_rows, box = [], []
    med_price = {}
    for y in years:
        s = fp.loc[fp["year"] == y, "PriceForMeter"]
        if len(s) == 0:
            box.append(None)
            continue
        q = [float(s.quantile(p)) for p in (0.1, 0.25, 0.5, 0.75, 0.9)]
        med_price[y] = q[2]
        box.append([round(v) for v in q])
        price_rows.append([str(y), fmt.int_he(q[1]), fmt.int_he(q[2]), fmt.int_he(q[3]), fmt.int_he(len(s))])
    charts["price"] = {"x": year_lbl, "box": box}
    tables["price"] = price_rows
    flags["price"] = len(price_rows) >= 2

    # ---- centralized rounds ---------------------------------------------------
    rd = dated[~dated["CentralizationType"].isin(["", "-", "הגרלה רגילה"])]
    rounds = []
    if len(rd):
        g = rd.groupby("CentralizationType").agg(
            start=("dt", "min"), n=("LotteryId", "size"),
            units=("LotteryHousingUnits", "sum"), subs=("Subscribers", "sum"))
        rf = rd[rd["LotteryType"] == FIRST].groupby("CentralizationType").agg(
            f_units=("LotteryHousingUnits", "sum"), f_subs=("Subscribers", "sum"))
        g = g.join(rf)
        g = g.reset_index().sort_values(["start", "CentralizationType"], kind="stable")
        n_rounds_all = len(g)
        g = g.tail(MAX_ROUNDS)
        for r in g.itertuples():
            short = r.CentralizationType
            for prefix in ("הגרלה גדולה - ", "הגרלה גדולה ", "הגרלת "):
                if short.startswith(prefix) and len(short) > len(prefix):
                    short = short[len(prefix):]
                    break
            rounds.append({"name": r.CentralizationType, "short": short, "n": int(r.n),
                           "units": _i(r.units), "subs": _i(r.subs), "start": fmt.month_he(r.start),
                           "ratio": (_round1(_ratio(r.f_subs, r.f_units))
                                     if pd.notna(r.f_units) and r.f_units > 0 else None)})
    else:
        n_rounds_all = 0
    flags["rounds"] = len(rounds) >= 2
    charts["rounds"] = {"names": [r["short"] for r in rounds], "values": [r["ratio"] for r in rounds]}
    tables["rounds"] = [[r["name"], r["start"], fmt.int_he(r["n"]), fmt.int_he(r["units"]),
                         fmt.int_he(r["subs"]), fmt.num_he(r["ratio"]) if r["ratio"] is not None else "-"]
                        for r in rounds]

    # ---- cities -----------------------------------------------------------------
    fc = first[first["LamasName"] != ""]
    cg = fc.groupby("LamasName").agg(units=("LotteryHousingUnits", "sum"), subs=("Subscribers", "sum"),
                                     n=("LotteryId", "size"))
    cp = fc[fc["PriceForMeter"] > 0].groupby("LamasName")["PriceForMeter"].median()
    cg["price"] = cp
    cg = cg.reset_index()
    by_units = cg.sort_values(["units", "LamasName"], ascending=[False, True], kind="stable")
    c_series = pd.Series(by_units["units"].values, index=by_units["LamasName"].values)
    c_names, c_vals = frame.top_other(c_series, TOP_N)
    charts["cities"] = {"names": c_names, "values": [_i(v) for v in c_vals]}
    tables["cities"] = [[n, fmt.int_he(v), fmt.pct(v / units_first) if units_first else "-"]
                        for n, v in zip(c_names, c_vals)]

    big = cg[cg["units"] >= MIN_CITY_UNITS].copy()
    big["ratio"] = big["subs"] / big["units"]
    hot = big.sort_values(["ratio", "LamasName"], ascending=[False, True], kind="stable").head(TOP_N)
    charts["city_demand"] = {"names": hot["LamasName"].tolist(), "values": [round(float(v), 1) for v in hot["ratio"]]}
    tables["city_demand"] = [[r.LamasName, fmt.num_he(r.ratio), fmt.int_he(r.units),
                              fmt.int_he(r.price) if pd.notna(r.price) else "-"] for r in hot.itertuples()]
    flags["city_demand"] = len(hot) >= 3
    sc = big[big["price"].notna()].sort_values("LamasName", kind="stable")
    charts["scatter"] = [[round(float(r.price)), round(float(r.ratio), 1), _i(r.units), r.LamasName]
                         for r in sc.itertuples()]
    flags["scatter"] = len(sc) >= 5
    corr = None
    if len(sc) >= 5:
        # Spearman = Pearson over ranks (no scipy in the builder image).
        corr = float(sc["price"].rank().corr(sc["ratio"].rank()))

    # ---- winners by group ------------------------------------------------------
    grp_cols = [("WinnersSeriesA", "סדרה א"), ("WinnersSeriesB", "סדרה ב"),
                ("WinnersSeriesC", "סדרה ג"), ("WinnersMeshapryDiur", "משפרי דיור")]
    gw = {col: ay[col].sum().reindex(years, fill_value=0) for col, _ in grp_cols}
    charts["groups"] = {"x": year_lbl, "series": [
        {"name": lbl, "data": [_i(gw[col][y]) for y in years]} for col, lbl in grp_cols]}
    tables["groups"] = [[str(y)] + [fmt.int_he(gw[col][y]) for col, _ in grp_cols] for y in years]
    tables["groups_cols"] = ["שנה"] + [lbl for _, lbl in grp_cols]

    # ---- locals (בני מקום) ----------------------------------------------------
    # First lotteries only, like every other flat count on the page.
    nat_u = fy["LotteryNativeHousingUnits"].sum().reindex(years, fill_value=0)
    all_u = f_units
    bm = dated[dated["WinnersBneyMakom"].notna()]
    bmy = bm.groupby("year")
    bm_w = bmy["WinnersBneyMakom"].sum().reindex(years)
    bm_all = bmy["Winners"].sum().reindex(years)
    nat_share = {y: _ratio(nat_u[y], all_u[y]) for y in years}
    win_share = {y: (_ratio(bm_w[y], bm_all[y]) if pd.notna(bm_w[y]) else None) for y in years}
    # Locals among registrants: first lotteries only (continuations reopen to all).
    fs = first[first["dt"].notna() & first["SubscribersBenyMakom"].notna()].groupby("year")
    bs = fs["SubscribersBenyMakom"].sum().reindex(years)
    bs_all = fs["Subscribers"].sum().reindex(years)
    sub_share = {y: (_ratio(bs[y], bs_all[y]) if pd.notna(bs[y]) else None) for y in years}

    def p100(v):
        return _round1(v * 100) if v is not None else None

    charts["native"] = {"x": year_lbl,
                        "units": [p100(nat_share[y]) for y in years],
                        "winners": [p100(win_share[y]) for y in years],
                        "subs": [p100(sub_share[y]) for y in years]}
    tables["native"] = [[str(y), fmt.int_he(nat_u[y]),
                         fmt.pct(nat_share[y]) if nat_share[y] is not None else "-",
                         fmt.pct(sub_share[y]) if sub_share[y] is not None else "-",
                         fmt.pct(win_share[y]) if win_share[y] is not None else "-"] for y in years]

    # ---- eligibility mix by year ------------------------------------------------
    el = dated[dated["Eligibility"] != ""]
    el_vals = _ordered(el["Eligibility"].tolist(), ELIG_ORDER)
    ect = pd.crosstab(el["year"], el["Eligibility"]).reindex(index=years, columns=el_vals, fill_value=0)
    charts["elig"] = {"x": year_lbl, "series": [
        {"name": ELIG_LABEL.get(v, v), "data": [int(ect.at[y, v]) for y in years]} for v in el_vals]}
    tables["elig_cols"] = ["שנה"] + [ELIG_LABEL.get(v, v) for v in el_vals]
    tables["elig"] = [[str(y)] + [fmt.int_he(ect.at[y, v]) for v in el_vals] for y in years]

    # ---- marketing body by year (units, first lotteries) ----------------------
    fr = first[first["dt"].notna() & (first["MarketingRep"] != "")]
    rep_vals = sorted(fr["MarketingRep"].unique())
    rct = fr.pivot_table(index="year", columns="MarketingRep", values="LotteryHousingUnits",
                         aggfunc="sum", fill_value=0).reindex(index=years, columns=rep_vals, fill_value=0)
    charts["rep"] = {"x": year_lbl, "series": [
        {"name": v, "data": [_i(rct.at[y, v]) for y in years]} for v in rep_vals]}
    tables["rep_cols"] = ["שנה"] + rep_vals
    tables["rep"] = [[str(y)] + [fmt.int_he(rct.at[y, v]) for v in rep_vals] for y in years]

    # ---- contractors ---------------------------------------------------------
    fpv = first[first["ProviderName"] != ""]
    pv = fpv.groupby("ProviderName").agg(units=("LotteryHousingUnits", "sum"), n=("LotteryId", "size"))
    pv = pv.reset_index().sort_values(["units", "ProviderName"], ascending=[False, True], kind="stable")
    top_pv = pv.head(TOP_N)
    charts["providers"] = {"names": top_pv["ProviderName"].tolist(), "values": [_i(v) for v in top_pv["units"]]}
    tables["providers"] = [[r.ProviderName, fmt.int_he(r.units), fmt.int_he(r.n)] for r in top_pv.itertuples()]
    top10_share = _ratio(pv.head(10)["units"].sum(), pv["units"].sum())

    # ---- project / permit status (latest row per project) ---------------------
    # Undated rows sort first, so a dated lottery wins as the project's latest.
    lp = df[df["ProjectId"] != ""].sort_values(["ProjectId", "dt", "LotteryId"], kind="stable",
                                               na_position="first")
    lp = lp.groupby("ProjectId").tail(1)
    st = frame.ranked(lp.loc[lp["ProjectStatus"] != "", "ProjectStatus"])
    st_names = _ordered(st.index.tolist(), STATUS_ORDER)
    charts["status"] = [{"name": n, "value": int(st[n])} for n in st_names]
    tables["status"] = [[n, fmt.int_he(st[n]), fmt.pct(st[n] / st.sum())] for n in st_names]
    pm = frame.ranked(lp.loc[lp["ConstructionPermitName"] != "", "ConstructionPermitName"])
    charts["permit"] = {"names": [str(k) for k in pm.index], "values": [int(v) for v in pm]}
    tables["permit"] = [[str(k), fmt.int_he(v), fmt.pct(v / pm.sum())] for k, v in pm.items()]

    # ---- insights ----------------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_demand():
        ys = [y for y in full_years if ratio_y.get(y) is not None and f_units[y] > 0]
        if len(ys) < 3:
            return None
        last = ys[-1]
        low = min(ys[:-1], key=lambda y: (ratio_y[y], y))
        r_last, r_low = ratio_y[last], ratio_y[low]
        if r_low <= 0:
            return None
        mult = r_last / r_low
        if mult >= 1 + DEMAND_MOVE:
            return (f"הביקוש זינק: בשנת {last} נרשמו בממוצע {fmt.num_he(r_last)} הרשמות לכל דירה בהגרלות הראשונות, "
                    f"פי {fmt.num_he(mult)} מהשפל של {low} ({fmt.num_he(r_low)} הרשמות לדירה).")
        peak = max(ys, key=lambda y: (ratio_y[y], -y))
        if peak != last:
            return (f"בשנת {last} נרשמו בממוצע {fmt.num_he(r_last)} הרשמות לכל דירה בהגרלות הראשונות, "
                    f"לעומת שיא של {fmt.num_he(ratio_y[peak])} בשנת {peak}.")
        return None

    def ins_partial():
        if not partial_last or not years:
            return None
        y = years[-1]
        if f_units[y] <= 0 or ratio_y[y] is None:
            return None
        return (f"ההגרלה האחרונה במאגר נערכה ב-{fmt.d_he(last_dt)}. בשנת {y} (עד אותו מועד) הוצעו "
                f"{fmt.int_he(f_units[y])} דירות בהגרלות ראשונות, עם {fmt.num_he(ratio_y[y])} הרשמות לדירה בממוצע.")

    def ins_city():
        if len(by_units) < 2 or not units_first:
            return None
        top = by_units.iloc[0]
        share = top["units"] / units_first
        if share < 0.03:
            return None
        second = by_units.iloc[1]
        return (f"{top['LamasName']} מובילה במספר הדירות שהוצעו: {fmt.int_he(top['units'])} דירות "
                f"({fmt.pct(share)} מהדירות בהגרלות הראשונות), ואחריה {second['LamasName']} "
                f"עם {fmt.int_he(second['units'])}.")

    def ins_hot():
        if len(hot) < 3:
            return None
        h = hot.iloc[0]
        lo = big.sort_values(["ratio", "LamasName"], kind="stable").iloc[0]
        if h["ratio"] < 2 * lo["ratio"]:
            return None
        return (f"התחרות החריפה ביותר נרשמה ב{h['LamasName']}: {fmt.num_he(h['ratio'])} הרשמות לכל דירה. "
                f"בקצה השני, ב{lo['LamasName']} נרשמו {fmt.num_he(lo['ratio'])} הרשמות לדירה "
                f"(יישובים עם {fmt.int_he(MIN_CITY_UNITS)} דירות לפחות בהגרלות ראשונות).")

    def ins_price():
        ys = [y for y in full_years if y in med_price]
        if len(ys) < 3:
            return None
        a, b = ys[0], ys[-1]
        ch = med_price[b] / med_price[a] - 1
        if abs(ch) < PRICE_MOVE:
            return (f"המחיר החציוני למ\"ר נותר יציב יחסית: {fmt.int_he(med_price[a])} ₪ בשנת {a} "
                    f"ו-{fmt.int_he(med_price[b])} ₪ בשנת {b}.")
        word = "עלה" if ch > 0 else "ירד"
        return (f"המחיר החציוני למ\"ר בהגרלות הראשונות {word} מ-{fmt.int_he(med_price[a])} ₪ בשנת {a} "
                f"ל-{fmt.int_he(med_price[b])} ₪ בשנת {b} ({fmt.signed_pct(ch)}).")

    def ins_corr():
        if corr is None or pd.isna(corr) or abs(corr) < 0.3:
            return None
        word = "גבוה יותר" if corr > 0 else "נמוך יותר"
        return (f"ככל שהמחיר למ\"ר ביישוב {word}, כך התחרות על כל דירה גבוהה יותר "
                f"(מתאם דירוגים של {fmt.num_he(corr, 2)} בין המחיר החציוני למספר ההרשמות לדירה, "
                f"ב-{fmt.int_he(len(sc))} יישובים).")

    def ins_cont():
        if not n_projects or not n_cont:
            return None
        pj = (df["LotteryType"] == CONT)[df["ProjectId"] != ""].groupby(df["ProjectId"]).any()
        share = float(pj.mean())
        if share < 0.05:
            return None
        return (f"ב-{fmt.pct(share)} מהפרויקטים ({fmt.int_he(pj.sum())} מתוך {fmt.int_he(len(pj))}) נדרשה "
                f"הגרלת המשך לדירות שנותרו: {fmt.int_he(n_cont)} הגרלות המשך הציעו שוב {fmt.int_he(units_cont)} דירות.")

    def ins_native():
        ys = [y for y in full_years if nat_share.get(y) is not None and all_u[y] > 0]
        if len(ys) < 3:
            return None
        a, b = ys[0], ys[-1]
        if abs(nat_share[b] - nat_share[a]) < 0.03:
            return None
        word = "עלה" if nat_share[b] > nat_share[a] else "ירד"
        return (f"שיעור הדירות שהוקצו לבני המקום (תושבי היישוב) {word} מ-{fmt.pct(nat_share[a])} בשנת {a} "
                f"ל-{fmt.pct(nat_share[b])} בשנת {b}.")

    def ins_groups():
        ys = [y for y in years if sum(gw[c][y] for c, _ in grp_cols) > 0]
        if len(ys) < 3:
            return None
        only_a = [y for y in ys if gw["WinnersSeriesB"][y] + gw["WinnersSeriesC"][y] == 0]
        # a trailing run of years where every winner came from series A / upgraders only
        run = []
        for y in reversed(ys):
            if y in only_a:
                run.append(y)
            else:
                break
        if len(run) >= 2 and len(run) < len(ys):
            start = min(run)
            return (f"מאז {start} כל הזוכים נמנים על סדרה א או על משפרי הדיור, בעוד שבשנים שקדמו "
                    f"חולקו הזכיות גם בין סדרות ב ו-ג.")
        return None

    def ins_providers():
        if len(pv) < 10 or top10_share is None:
            return None
        t = pv.iloc[0]
        return (f"{fmt.int_he(len(pv))} קבלנים זכו בפרויקטים. המוביל, {t['ProviderName']}, הציע "
                f"{fmt.int_he(t['units'])} דירות, ועשרת הגדולים יחד {fmt.pct(top10_share)} מהדירות.")

    def ins_native_odds():
        # Winning odds of a local registrant vs everyone, first lotteries
        # that report locals among winners.
        f2 = first[first["WinnersBneyMakom"].notna() & first["SubscribersBenyMakom"].notna()]
        sl, sa = f2["SubscribersBenyMakom"].sum(), f2["Subscribers"].sum()
        wl, wa = f2["WinnersBneyMakom"].sum(), f2["Winners"].sum()
        if sl <= 0 or sa <= sl or wa <= 0:
            return None
        p_local = wl / sl
        p_other = (wa - wl) / (sa - sl)
        if p_other <= 0 or p_local / p_other < 1.5:
            return None
        return (f"לבני המקום סיכוי גבוה בהרבה לזכות: בהגרלות הראשונות שמדווחות על כך זכו "
                f"{fmt.pct(p_local)} מהרשמות בני המקום, לעומת {fmt.pct(p_other, 2)} מיתר ההרשמות "
                f"(פי {fmt.num_he(p_local / p_other)}).")

    for iid, fn in [("demand", ins_demand), ("partial", ins_partial), ("price", ins_price),
                    ("city", ins_city), ("hot", ins_hot), ("corr", ins_corr), ("cont", ins_cont),
                    ("native", ins_native), ("native_odds", ins_native_odds),
                    ("groups", ins_groups), ("providers", ins_providers)]:
        add(iid, fn())

    # ---- KPIs ------------------------------------------------------------------
    kpis = {
        "lotteries": {"value": n_lot, "display": fmt.int_he(n_lot), "tone": "brand"},
        "units": {"value": units_first, "display": fmt.int_he(units_first), "tone": "brand"},
        "subs": {"value": subs_all, "display": fmt.int_he(subs_all), "tone": "brand"},
        "winners": {"value": winners, "display": fmt.int_he(winners), "tone": "ok"},
    }
    ry = [y for y in full_years if ratio_y.get(y) is not None and f_units[y] > 0]
    if ry:
        ly = ry[-1]
        rising = len(ry) >= 2 and ratio_y[ly] > ratio_y[ry[-2]] * (1 + DEMAND_MOVE)
        kpis["ratio"] = {"value": round(ratio_y[ly], 1), "display": fmt.num_he(ratio_y[ly]),
                         "tone": "danger" if rising else "info"}
        labels["ratio_kpi"] = f"הרשמות לכל דירה בהגרלות ראשונות ({ly})"
    py = [y for y in full_years if y in med_price]
    if py:
        kpis["price"] = {"value": round(med_price[py[-1]]), "display": fmt.int_he(med_price[py[-1]]), "tone": "brand"}
        labels["price_kpi"] = f"מחיר חציוני למ\"ר בש\"ח ({py[-1]})"
    kpis["cities"] = {"value": n_cities, "display": fmt.int_he(n_cities), "tone": "brand"}
    kpis["years"] = {"value": len(years),
                     "display": f"{years[0]}–{years[-1]}" if years else "-", "tone": "brand"}
    flags["ratio_kpi"] = "ratio" in kpis
    flags["price_kpi"] = "price" in kpis

    span = f"{years[0]} עד {years[-1]}" if years else ""
    labels.update({
        "lotteries_kpi": "הגרלות (ראשונות והמשך)",
        "units_kpi": "דירות שהוצעו בהגרלות ראשונות",
        "subs_kpi": "הרשמות להגרלות (כולל כפילויות)",
        "winners_kpi": "זוכים",
        "cities_kpi": "יישובים",
        "years_kpi": "שנות הגרלה",
        "year_note": year_note(),
        "years_note": (f"{fmt.int_he(n_first)} הגרלות ראשונות ו-{fmt.int_he(n_cont)} הגרלות המשך, לפי שנת עריכת ההגרלה. "
                       f"הקו מציג את הדירות שהוצעו בהגרלות הראשונות"
                       + (f"; השיא בשנת {peak_units_y} עם {fmt.int_he(f_units[peak_units_y])} דירות." if peak_units_y else ".")),
        "years_aria": (f"גרף עמודות מוערמות: מספר ההגרלות לפי שנה ולפי סוג, {span}, וקו של הדירות שהוצעו. "
                       + (f"שיא הדירות בשנת {peak_units_y}." if peak_units_y else "")),
        "demand_note": ("הרשמות להגרלות הראשונות בכל שנה, ומספר ההרשמות הממוצע לכל דירה שהוצעה בהן. "
                        "אדם אחד יכול להירשם לכמה הגרלות, ולכן ההרשמות אינן מספר נרשמים ייחודיים."),
        "demand_aria": (f"גרף עמודות וקו: הרשמות להגרלות ראשונות והרשמות לכל דירה לפי שנה, {span}."
                        + (f" בשנת {ry[-1]}: {fmt.num_he(ratio_y[ry[-1]])} הרשמות לדירה." if ry else "")),
        "price_note": ("התפלגות המחיר למ\"ר (ש\"ח) בהגרלות הראשונות לפי שנה: הקופסה בין הרבעון התחתון לעליון, "
                       "הקו בחציון והשפמים באחוזון העשירי והתשעים. כל הגרלה נספרת פעם אחת, ללא שקלול לפי מספר הדירות"
                       + (f"; {fmt.int_he(no_price)} הגרלות ללא מחיר אינן נכללות." if no_price else ".")),
        "price_aria": (f"תרשים קופסאות: מחיר למ\"ר בהגרלות ראשונות לפי שנה, {span}."
                       + (f" חציון {fmt.int_he(med_price[py[-1]])} ש\"ח בשנת {py[-1]}." if py else "")),
        "rounds_note": ("הגרלות מרוכזות (\"הגרלה גדולה\") לפי סדר כרונולוגי: הרשמות לכל דירה בהגרלות הראשונות שבהן. "
                        "הטבלה מציגה גם את מספרי ההגרלות, הדירות וההרשמות, כולל הגרלות המשך"
                        + (f". מוצגות {fmt.int_he(len(rounds))} ההגרלות המרוכזות האחרונות מתוך {fmt.int_he(n_rounds_all)}." if n_rounds_all > len(rounds) else ".")),
        "rounds_aria": (f"גרף עמודות אופקי: הרשמות לכל דירה בכל אחת מ-{fmt.int_he(len(rounds))} ההגרלות המרוכזות."
                        + (f" הגבוה ביותר: {max(rounds, key=lambda r: (r['ratio'] or 0, r['name']))['name']}." if rounds else "")),
        "cities_note": (f"דירות שהוצעו בהגרלות ראשונות לפי יישוב: {fmt.int_he(TOP_N)} היישובים המובילים, "
                        f"והשאר מקובצים תחת \"אחר\". {fmt.int_he(n_cities)} יישובים בסך הכול."),
        "cities_aria": ("גרף עמודות אופקי: דירות בהגרלות ראשונות לפי יישוב. "
                        + (f"מוביל: {c_names[0]} עם {fmt.int_he(c_vals[0])} דירות." if c_names else "")),
        "city_demand_note": (f"הרשמות לכל דירה בהגרלות הראשונות, ביישובים עם {fmt.int_he(MIN_CITY_UNITS)} דירות לפחות "
                             f"({fmt.int_he(len(big))} יישובים). מוצגים {fmt.int_he(len(hot))} המבוקשים ביותר."),
        "city_demand_aria": ("גרף עמודות אופקי: הרשמות לכל דירה לפי יישוב. "
                             + (f"המבוקש ביותר: {hot.iloc[0]['LamasName']} עם {fmt.num_he(hot.iloc[0]['ratio'])} הרשמות לדירה." if len(hot) else "")),
        "scatter_note": (f"כל נקודה היא יישוב עם {fmt.int_he(MIN_CITY_UNITS)} דירות לפחות בהגרלות ראשונות: "
                         f"מחיר חציוני למ\"ר מול הרשמות לכל דירה. גודל הנקודה לפי מספר הדירות."),
        "scatter_aria": f"תרשים פיזור: מחיר חציוני למ\"ר מול הרשמות לדירה ב-{fmt.int_he(len(sc))} יישובים.",
        "groups_note": ("זוכים לפי סדרת הזכאות בכל שנה: סדרות א, ב ו-ג של חסרי הדיור, ומשפרי דיור, "
                        "כפי שהם מסווגים במאגר."),
        "groups_aria": f"גרף עמודות מוערמות: זוכים לפי סדרה ולפי שנה, {span}.",
        "native_note": ("שיעור הדירות שהוקצו לבני המקום (תושבי היישוב) מהדירות בהגרלות הראשונות, שיעור בני המקום מבין "
                        "ההרשמות להגרלות הראשונות, ושיעורם מבין הזוכים בהגרלות שמדווחות על כך."),
        "native_aria": f"גרף קווים: שיעור בני המקום מהדירות, מההרשמות ומהזוכים לפי שנה, {span}.",
        "elig_note": "מספר ההגרלות בכל שנה לפי קבוצות הזכאות שהורשו להשתתף בהן.",
        "elig_aria": f"גרף עמודות מוערמות: הגרלות לפי קבוצת זכאות ולפי שנה, {span}.",
        "rep_note": "דירות שהוצעו בהגרלות ראשונות לפי הגוף המשווק (משרד הבינוי והשיכון או רשות מקרקעי ישראל).",
        "rep_aria": f"גרף עמודות מוערמות: דירות בהגרלות ראשונות לפי גוף משווק ולפי שנה, {span}.",
        "providers_note": (f"{fmt.int_he(TOP_N)} הקבלנים שהציעו את מספר הדירות הגבוה ביותר בהגרלות הראשונות, "
                           f"מתוך {fmt.int_he(n_providers)} קבלנים."),
        "providers_aria": ("גרף עמודות אופקי: דירות לפי קבלן. "
                           + (f"מוביל: {top_pv.iloc[0]['ProviderName']} עם {fmt.int_he(top_pv.iloc[0]['units'])} דירות." if len(top_pv) else "")),
        "status_note": f"שלב הפרויקט לפי ההגרלה האחרונה של כל אחד מ-{fmt.int_he(len(lp))} הפרויקטים.",
        "status_aria": "גרף טבעת: פרויקטים לפי שלב.",
        "permit_note": "מצב היתר הבנייה לפי ההגרלה האחרונה של כל פרויקט.",
        "permit_aria": ("גרף עמודות אופקי: פרויקטים לפי מצב היתר הבנייה. "
                        + (f"הנפוץ: {pm.index[0]} ({fmt.int_he(pm.iloc[0])} פרויקטים)." if len(pm) else "")),
    })
    lede = (f"המאגר עוקב אחר {fmt.int_he(n_lot)} הגרלות של תכנית דירה בהנחה (מחיר למשתכן) "
            f"שנערכו בין {fmt.d_he(first_dt)} ל-{fmt.d_he(last_dt)}, ב-{fmt.int_he(n_cities)} יישובים. "
            f"בהגרלות הראשונות הוצעו {fmt.int_he(units_first)} דירות, ובכל ההגרלות נרשמו "
            f"{fmt.int_he(subs_all)} הרשמות ו-{fmt.int_he(winners)} זוכים."
            if first_dt is not None else
            f"המאגר עוקב אחר {fmt.int_he(n_lot)} הגרלות של תכנית דירה בהנחה (מחיר למשתכן).")
    labels["lede"] = lede
    labels["lookup_sub"] = ("חיפוש חי בכל רשומות המאגר: יישוב, שכונה, שם הפרויקט, קבלן, מספר הגרלה, "
                            "מחיר למ\"ר ומספרי נרשמים וזוכים.")

    summary = (f"תוצאות הגרלות דירה בהנחה ומחיר למשתכן לפי יישוב, פרויקט וקבלן: {fmt.int_he(n_lot)} הגרלות, "
               f"{fmt.int_he(units_first)} דירות ו-{fmt.int_he(winners)} זוכים"
               + (f", {span}." if span else "."))
    if len(summary) > 155:
        summary = (f"תוצאות הגרלות דירה בהנחה ומחיר למשתכן לפי יישוב ופרויקט: {fmt.int_he(n_lot)} הגרלות "
                   f"ו-{fmt.int_he(winners)} זוכים.")
    description = summary if len(summary) >= 70 else None

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "הגרלות דירה בהנחה: תוצאות, נרשמים וזוכים לפי יישוב",
            "name": "הגרלות דירה בהנחה ומחיר למשתכן: נרשמים, זוכים ומחירים",
            "alternate_names": [
                "נתונים תקופתיים - תכנית דירה בהנחה",
                "מעקב אחר הגרלות דירה בהנחה",
                "תוצאות הגרלות מחיר למשתכן",
                "הגרלות מחיר מטרה",
            ],
        },
    }
    if description:
        agent_data["seo"]["description"] = description
    if years:
        agent_data["temporal_coverage"] = f"{years[0]}/{years[-1]}"

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
    }
