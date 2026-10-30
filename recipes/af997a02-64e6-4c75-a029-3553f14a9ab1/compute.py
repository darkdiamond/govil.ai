"""New vehicles without a model code, delivered per month (Ministry of Transport).

One table: month (YYYYMM) x vehicle group x manufacturer x model name ->
number of vehicles. Every number on the page is computed here. Insight
rules return a sentence or None when their premise does not hold.

Growth: one new month per release. Months are kept monthly (a few hundred
points at most for decades); category axes are capped (top-N + "אחר");
the latest year is usually partial, so year-over-year comparisons use the
same calendar months in both years (disclosed on the page).
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני",
                "יולי", "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]

OTHER = "אחר"
UNKNOWN = "לא ידוע"
NO_MODEL = "ללא שם דגם"
TYPE_CAP = 8          # vehicle groups shown before "אחר"
MAKER_TOP = 15        # manufacturers ranking
MODEL_TOP = 15        # models ranking
TREE_PER_TYPE = 6     # manufacturers per group in the treemap
TREND_THRESHOLD = 0.03

NOTES = ("מאגר זה מכיל פרטים אודות כמות כלי רכב חדשים חסרי קוד דגם שעלו על הכביש "
         "בכל חודש משנת 2018 ועד החודש הקלנדרי הקודם.")


def _int(v):
    return f"{int(round(v)):,}"


def _pct(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def _signed_pct(v, digits=1):
    s = f"{abs(v) * 100:.{digits}f}%"
    if round(abs(v) * 100, digits) == 0:
        return s
    return ("+" if v > 0 else "−") + s


def _month_label(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def _prepare(df):
    df = df.copy()
    month = df["sgira_month"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    df["period"] = pd.to_datetime(month, format="%Y%m", errors="coerce")
    df["n"] = pd.to_numeric(df["car_num"].astype(str).str.replace(",", "").str.strip(),
                            errors="coerce")
    df = df.dropna(subset=["period", "n"])
    df = df[df["n"] > 0]
    df["vtype"] = df["kvutzat_sug_rechev"].astype(str).str.strip().replace("", UNKNOWN)
    df["maker"] = df["tozeret_nm"].astype(str).str.strip().replace("", UNKNOWN)
    df["model"] = df["degem_nm"].astype(str).str.strip().replace("", NO_MODEL)
    df["year"] = df["period"].dt.year.astype(int)
    df["mon"] = df["period"].dt.month.astype(int)
    df["ym"] = df["year"] * 100 + df["mon"]
    return df[["period", "ym", "year", "mon", "vtype", "maker", "model", "n"]]


def _ranked(series):
    """Sum-series sorted by value desc, ties by key asc (total order)."""
    s = series.sort_index()
    return s.sort_values(ascending=False, kind="stable")


# ── insight rules ───────────────────────────────────────────────────────

def insight_ytd(ctx):
    prev, cur = ctx["ytd_prev"], ctx["ytd_cur"]
    if prev <= 0 or ctx["prev_year"] is None:
        return None
    ch = (cur - prev) / prev
    span = ctx["ytd_span"]
    y1, y0 = ctx["last_year"], ctx["prev_year"]
    if abs(ch) < TREND_THRESHOLD:
        return (f"ב{span} {y1} עלו לכביש {_int(cur)} כלי רכב חדשים ללא קוד דגם, "
                f"כמעט ללא שינוי לעומת התקופה המקבילה ב-{y0} ({_int(prev)}).")
    word = "עלייה" if ch > 0 else "ירידה"
    return (f"ב{span} {y1} עלו לכביש {_int(cur)} כלי רכב חדשים ללא קוד דגם, "
            f"{word} של {_pct(abs(ch))} לעומת התקופה המקבילה ב-{y0} ({_int(prev)}).")


def insight_type_mover(ytd_rows, ctx):
    """The vehicle group with the largest same-period change, if material."""
    best = None
    for r in ytd_rows:
        if r["name"] == OTHER or r["prev"] < 200:
            continue
        diff = r["cur"] - r["prev"]
        ch = diff / r["prev"]
        if abs(ch) < 0.15 or abs(diff) < 300:
            continue
        key = (abs(diff), r["name"])
        if best is None or key > best[0]:
            best = (key, r, ch)
    if best is None:
        return None
    _, r, ch = best
    word = "זינק" if ch > 0 else "צנח"
    return (f"מספר כלי הרכב מסוג {r['name']} {word} ב-{_pct(abs(ch))}: "
            f"{_int(r['cur'])} ב{ctx['ytd_span']} {ctx['last_year']} לעומת "
            f"{_int(r['prev'])} בתקופה המקבילה ב-{ctx['prev_year']}.")


def insight_leading_type(by_type, total):
    if by_type.empty or total <= 0:
        return None
    name, v = by_type.index[0], by_type.iloc[0]
    share = v / total
    if share < 0.2:
        return None
    second = ""
    if len(by_type) > 1:
        second = (f", ולאחריו {by_type.index[1]} "
                  f"({_pct(by_type.iloc[1] / total)})")
    return (f"הקבוצה הגדולה ביותר היא {name}: {_int(v)} כלי רכב, "
            f"{_pct(share)} מכלל המסירות במאגר{second}.")


def insight_top_maker(by_maker, total, l12_makers, l12_total):
    if by_maker.empty or total <= 0:
        return None
    name, v = by_maker.index[0], by_maker.iloc[0]
    share = v / total
    if share < 0.05:
        return None
    if len(by_maker) > 1 and by_maker.iloc[1] > 0 and v / by_maker.iloc[1] < 1.1:
        return None
    text = (f"היצרן המוביל לאורך כל התקופה הוא {name} עם {_int(v)} כלי רכב "
            f"({_pct(share)} מהסך).")
    if not l12_makers.empty and l12_total > 0:
        n12, v12 = l12_makers.index[0], l12_makers.iloc[0]
        if n12 == name:
            text += f" הוא מוביל גם ב-12 החודשים האחרונים ({_int(v12)})."
        else:
            text += f" ב-12 החודשים האחרונים מוביל {n12} ({_int(v12)})."
    return text


def insight_season(cal_avg, full_years):
    if len(full_years) < 2 or cal_avg.empty:
        return None
    hi_m, lo_m = int(cal_avg.idxmax()), int(cal_avg.idxmin())
    hi, lo = cal_avg.max(), cal_avg.min()
    if lo <= 0 or hi / lo < 1.2:
        return None
    return (f"עונתיות ברורה: ב{MONTHS_HE[hi_m - 1]} עולים לכביש בממוצע {_int(hi)} כלי רכב, "
            f"פי {hi / lo:.1f} מאשר ב{MONTHS_HE[lo_m - 1]} ({_int(lo)}), "
            f"לפי {len(full_years)} שנים מלאות.")


def insight_shift(yearly_type, full_years):
    """A group whose yearly volume changed sharply between the first and last full year."""
    if len(full_years) < 3:
        return None
    y0, y1 = full_years[0], full_years[-1]
    best = None
    for t in yearly_type.columns:
        if t == OTHER:
            continue
        a, b = yearly_type.loc[y0, t], yearly_type.loc[y1, t]
        if a < 1000:
            continue
        ch = (b - a) / a
        if abs(ch) < 0.4:
            continue
        key = (abs(ch), t)
        if best is None or key > best[0]:
            best = (key, t, a, b, ch)
    if best is None:
        return None
    _, t, a, b, ch = best
    word = "ירד" if ch < 0 else "עלה"
    return (f"מספר כלי הרכב מסוג {t} ללא קוד דגם {word} מ-{_int(a)} ב-{y0} "
            f"ל-{_int(b)} ב-{y1} ({_signed_pct(ch, 0)}).")


def insight_concentration(conc_rows):
    best = None
    for r in conc_rows:
        if r["total"] < 1000 or r["name"] == OTHER:
            continue
        if r["leader_share"] < 0.3:
            continue
        key = (r["leader_share"], r["name"])
        if best is None or key > best[0]:
            best = (key, r)
    if best is None:
        return None
    r = best[1]
    return (f"קבוצת סוג הרכב המרוכזת ביותר היא {r['name']}: {r['leader']} לבדו אחראי ל-"
            f"{_pct(r['leader_share'])} מהמסירות, ושלושת היצרנים הגדולים ל-"
            f"{_pct(r['top3_share'])}.")


def insight_record(monthly):
    if len(monthly) < 24:
        return None
    hi_p, lo_p = monthly.idxmax(), monthly.idxmin()
    return (f"החודש העמוס ביותר במאגר היה {_month_label(hi_p)} עם {_int(monthly.max())} "
            f"כלי רכב, והשקט ביותר {_month_label(lo_p)} עם {_int(monthly.min())}.")


# ── compute ─────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])
    total = int(df["n"].sum())

    # Monthly series, gaps filled with zero.
    first_p, last_p = df["period"].min(), df["period"].max()
    idx = pd.date_range(first_p, last_p, freq="MS")
    monthly = df.groupby("period")["n"].sum().reindex(idx, fill_value=0)
    ma12 = monthly.rolling(12).mean()
    last_year, last_mon = int(last_p.year), int(last_p.month)
    present = df.groupby("year")["mon"].nunique()
    full_years = [int(y) for y, c in present.sort_index().items() if c == 12]
    years = sorted(int(y) for y in df["year"].unique())
    partial_last = last_mon < 12
    prev_year = last_year - 1 if (last_year - 1) in years else None

    # Same-period window (Jan..last_mon) — the whole year when the last is full.
    if last_mon == 12:
        ytd_span = "כל השנה"
        ytd_span_short = "שנה מלאה"
    elif last_mon == 1:
        ytd_span = f"חודש {MONTHS_HE[0]}"
        ytd_span_short = MONTHS_HE[0]
    else:
        ytd_span = f"{MONTHS_HE[0]} עד {MONTHS_HE[last_mon - 1]}"
        ytd_span_short = f"{MONTHS_HE[0]}-{MONTHS_HE[last_mon - 1]}"
    ytd = df[df["mon"] <= last_mon]
    ytd_cur = float(ytd.loc[ytd["year"] == last_year, "n"].sum())
    ytd_prev = float(ytd.loc[ytd["year"] == prev_year, "n"].sum()) if prev_year else 0.0

    # Vehicle groups (capped).
    by_type_all = _ranked(df.groupby("vtype")["n"].sum())
    cap = TYPE_CAP if len(by_type_all) > TYPE_CAP + 1 else TYPE_CAP + 1
    keep_types = list(by_type_all.index[:cap])
    df["vgroup"] = df["vtype"].where(df["vtype"].isin(keep_types), OTHER)
    groups = keep_types + ([OTHER] if (df["vgroup"] == OTHER).any() else [])
    by_type = df.groupby("vgroup")["n"].sum().reindex(groups)

    yearly_type = (df.pivot_table(index="year", columns="vgroup", values="n",
                                  aggfunc="sum", fill_value=0)
                   .reindex(index=years, columns=groups, fill_value=0))
    yearly_tot = yearly_type.sum(axis=1)

    def year_label(y):
        if y == last_year and partial_last:
            return f"{y} ({ytd_span_short})"
        return str(y)

    year_labels = [year_label(y) for y in years]

    # Same-period comparison per group.
    ytd_type = ytd.assign(vgroup=ytd["vtype"].where(ytd["vtype"].isin(keep_types), OTHER))
    ytd_rows = []
    for g in groups:
        sub = ytd_type[ytd_type["vgroup"] == g]
        cur = float(sub.loc[sub["year"] == last_year, "n"].sum())
        prev = float(sub.loc[sub["year"] == prev_year, "n"].sum()) if prev_year else 0.0
        ch = (cur - prev) / prev if prev > 0 else None
        ytd_rows.append({"name": g, "cur": int(cur), "prev": int(prev),
                         "chg": None if ch is None else round(ch * 100, 1)})

    # Rolling 12-month sums per group (small multiples).
    type_month = (df.pivot_table(index="period", columns="vgroup", values="n",
                                 aggfunc="sum", fill_value=0)
                  .reindex(index=idx, columns=groups, fill_value=0))
    roll = type_month.rolling(12).sum()
    roll_x = [p.strftime("%Y-%m") for p in idx[11:]]
    multiples, trend_rows = [], []
    for g in groups:
        series = roll[g].iloc[11:]
        multiples.append({"name": g, "y": [int(v) for v in series]})
        l12 = float(type_month[g].iloc[-12:].sum()) if len(idx) >= 12 else float(type_month[g].sum())
        p12 = float(type_month[g].iloc[-24:-12].sum()) if len(idx) >= 24 else None
        ch = (l12 - p12) / p12 if p12 else None
        trend_rows.append({"name": g, "l12": _int(l12),
                           "p12": "" if p12 is None else _int(p12),
                           "chg": "" if ch is None else _signed_pct(ch),
                           "share": _pct(by_type[g] / total) if total else ""})

    # Seasonality heatmap.
    ym = df.groupby(["year", "mon"])["n"].sum()
    cells = []
    for yi, y in enumerate(years):
        for m in range(1, 13):
            if (y, m) in ym.index:
                cells.append([m - 1, yi, int(ym[(y, m)])])
    cal = df[df["year"].isin(full_years)].groupby("mon")["n"].sum()
    cal_avg = (cal / max(len(full_years), 1)).sort_index()
    heat_max = int(max(c[2] for c in cells)) if cells else 0

    # Manufacturers.
    by_maker = _ranked(df.groupby("maker")["n"].sum())
    last12_start = idx[-12] if len(idx) >= 12 else idx[0]
    l12df = df[df["period"] >= last12_start]
    l12_total = float(l12df["n"].sum())
    l12_makers = _ranked(l12df.groupby("maker")["n"].sum())
    maker_main_type = (df.groupby(["maker", "vtype"])["n"].sum().reset_index()
                       .sort_values(["maker", "n", "vtype"], ascending=[True, False, True], kind="stable")
                       .drop_duplicates("maker").set_index("maker")["vtype"])
    top_makers = list(by_maker.index[:MAKER_TOP])
    makers_chart = {
        "names": top_makers,
        "total": [int(by_maker[m]) for m in top_makers],
        "l12": [int(l12_makers.get(m, 0)) for m in top_makers],
    }
    makers_table = [{"name": m, "total": _int(by_maker[m]), "share": _pct(by_maker[m] / total),
                     "l12": _int(l12_makers.get(m, 0)), "type": maker_main_type.get(m, "")}
                    for m in top_makers]
    top_share = by_maker.iloc[:MAKER_TOP].sum() / total if total else 0

    # Treemap: group -> top manufacturers + other; concentration table.
    tree, conc_rows = [], []
    gm = df.groupby(["vgroup", "maker"])["n"].sum()
    for g in groups:
        s = _ranked(gm[g])
        kids = [{"name": m, "value": int(v)} for m, v in s.iloc[:TREE_PER_TYPE].items()]
        rest = int(s.iloc[TREE_PER_TYPE:].sum())
        if rest > 0:
            kids.append({"name": f"{OTHER} ({_int(len(s) - TREE_PER_TYPE)} יצרנים)", "value": rest})
        tree.append({"name": g, "value": int(s.sum()), "children": kids})
        gt = float(s.sum())
        conc_rows.append({"name": g, "total": gt, "leader": s.index[0],
                          "leader_share": s.iloc[0] / gt if gt else 0,
                          "top3_share": s.iloc[:3].sum() / gt if gt else 0,
                          "makers": int(len(s))})
    conc_table = [{"name": r["name"], "makers": _int(r["makers"]), "leader": r["leader"],
                   "leader_share": _pct(r["leader_share"]), "top3": _pct(r["top3_share"])}
                  for r in conc_rows]

    # Models.
    by_model = _ranked(df.groupby(["maker", "model"])["n"].sum())
    model_type = (df.groupby(["maker", "model", "vtype"])["n"].sum().reset_index()
                  .sort_values(["maker", "model", "n", "vtype"],
                               ascending=[True, True, False, True], kind="stable")
                  .drop_duplicates(["maker", "model"]).set_index(["maker", "model"])["vtype"])
    top_models = list(by_model.index[:MODEL_TOP])
    models_chart = {"names": [f"{mo} ({mk})" for mk, mo in top_models],
                    "values": [int(by_model[k]) for k in top_models]}
    models_table = [{"model": mo, "maker": mk, "type": model_type.get((mk, mo), ""),
                     "total": _int(by_model[(mk, mo)])} for mk, mo in top_models]
    n_models = int(len(by_model))

    # Diversity per year.
    div = (df.assign(mk=df["maker"] + "|" + df["model"])
           .groupby("year").agg(makers=("maker", "nunique"), models=("mk", "nunique"))
           .reindex(years))
    diversity = {"x": year_labels, "makers": [int(v) for v in div["makers"]],
                 "models": [int(v) for v in div["models"]]}
    div_table = [{"year": year_labels[i], "makers": _int(div["makers"].iloc[i]),
                  "models": _int(div["models"].iloc[i]), "total": _int(yearly_tot.iloc[i])}
                 for i in range(len(years))]

    # ── KPIs ──
    last_val = float(monthly.iloc[-1])
    same_prev_p = last_p - pd.DateOffset(years=1)
    prev_month_val = float(monthly.get(same_prev_p, 0)) if same_prev_p >= first_p else 0.0
    kpis = {"total": {"value": total, "display": _int(total), "tone": "brand"},
            "latest": {"value": int(last_val), "display": _int(last_val), "tone": "brand"}}

    def tone(ch):
        if ch is None:
            return "brand"
        if ch >= TREND_THRESHOLD:
            return "ok"
        if ch <= -0.15:
            return "danger"
        if ch <= -TREND_THRESHOLD:
            return "warn"
        return "brand"

    ytd_ch = (ytd_cur - ytd_prev) / ytd_prev if ytd_prev > 0 else None
    kpis["ytd"] = {"value": None if ytd_ch is None else round(ytd_ch * 100, 1),
                   "display": "" if ytd_ch is None else _signed_pct(ytd_ch),
                   "tone": tone(ytd_ch)}
    mo_ch = (last_val - prev_month_val) / prev_month_val if prev_month_val > 0 else None
    kpis["month_yoy"] = {"value": None if mo_ch is None else round(mo_ch * 100, 1),
                         "display": "" if mo_ch is None else _signed_pct(mo_ch),
                         "tone": tone(mo_ch)}
    l12_types = _ranked(l12df.groupby("vtype")["n"].sum())
    lead_t = l12_types.index[0]
    kpis["lead_type"] = {"value": round(l12_types.iloc[0] / l12_total * 100, 1),
                         "display": _pct(l12_types.iloc[0] / l12_total), "tone": "info"}
    kpis["makers"] = {"value": int(l12df["maker"].nunique()),
                      "display": _int(l12df["maker"].nunique()), "tone": "brand"}

    ctx = {"ytd_cur": ytd_cur, "ytd_prev": ytd_prev, "ytd_span": ytd_span,
           "last_year": last_year, "prev_year": prev_year}
    by_type_ranked = _ranked(by_type)
    rules = [
        ("ytd", insight_ytd(ctx)),
        ("type_mover", insight_type_mover(ytd_rows, ctx)),
        ("leading_type", insight_leading_type(by_type_ranked, total)),
        ("top_maker", insight_top_maker(by_maker, total, l12_makers, l12_total)),
        ("shift", insight_shift(yearly_type, full_years)),
        ("concentration", insight_concentration(conc_rows)),
        ("season", insight_season(cal_avg, full_years)),
        ("record", insight_record(monthly)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    y_min, y_max = years[0], years[-1]
    last_label = _month_label(last_p)
    period_range = f"{_month_label(first_p)} עד {last_label}"
    summary = (f"כמה כלי רכב חדשים ללא קוד דגם עלו לכביש בכל חודש, לפי סוג רכב, יצרן ודגם: "
               f"{_int(total)} כלי רכב מ-{y_min} עד {last_label}, "
               f"{_int(last_val)} בחודש האחרון.")
    lede = (f"המאגר של משרד התחבורה מונה {_int(total)} כלי רכב חדשים שנמסרו ועלו לכביש בלי קוד דגם "
            f"במאגר הדגמים, בתקופה {period_range}: גרורים ונגררים, משאיות, טרקטורונים, "
            f"אופנועים, אוטובוסים ועוד, מ-{_int(by_maker.size)} יצרנים ו-{_int(n_models)} שמות דגם. "
            f"בדף: מגמה חודשית, השוואה לתקופה המקבילה אשתקד, עונתיות, ודירוג יצרנים ודגמים.")

    ma_vals = [None if pd.isna(v) else round(float(v), 1) for v in ma12]
    hi_i = int(monthly.values.argmax())

    ytd_x_cur = f"{last_year} ({ytd_span_short})" if partial_last else str(last_year)
    ytd_x_prev = (f"{prev_year} ({ytd_span_short})" if partial_last else str(prev_year)) if prev_year else ""

    labels = {
        "lede": lede,
        "notes": NOTES,
        "kpi_total": f"כלי רכב במאגר ({y_min} עד {last_year})",
        "kpi_latest": f"עלו לכביש ב{last_label}",
        "kpi_ytd": (f"שינוי ב{ytd_span} {last_year} לעומת {prev_year}" if prev_year
                    else "שינוי לעומת השנה הקודמת"),
        "kpi_month_yoy": (f"{last_label} לעומת {_month_label(same_prev_p)}"),
        "kpi_lead_type": f"משקל {lead_t} ב-12 החודשים האחרונים",
        "kpi_makers": "יצרנים פעילים ב-12 החודשים האחרונים",
        "monthly_note": (f"מספר כלי הרכב שעלו לכביש בכל חודש, {period_range}. הקו המקווקו: "
                         f"ממוצע נע של 12 חודשים. השיא: {_month_label(idx[hi_i])} "
                         f"({_int(monthly.iloc[hi_i])})."),
        "monthly_aria": (f"גרף קו: כלי רכב חדשים ללא קוד דגם לפי חודש, {period_range}. "
                         f"השיא ב{_month_label(idx[hi_i])} עם {_int(monthly.iloc[hi_i])}, "
                         f"ובחודש האחרון {_int(last_val)}."),
        "yearly_note": (f"סך כלי הרכב בכל שנה, מפולח לפי קבוצת סוג רכב."
                        + (f" שנת {last_year} חלקית ({ytd_span_short})." if partial_last else "")),
        "yearly_aria": (f"תרשים עמודות מוערמות: כלי רכב לפי שנה וקבוצת סוג רכב, {y_min} עד {y_max}. "
                        f"הקבוצה הגדולה: {by_type_ranked.index[0]}."),
        "yearly_caption": f"כלי רכב לפי שנה וקבוצת סוג רכב, {y_min} עד {y_max}",
        "ytd_note": (f"השוואה הוגנת לשנה חלקית: אותם חודשים ({ytd_span}) ב-{last_year} וב-{prev_year}."
                     if prev_year and partial_last else
                     (f"השוואה בין {last_year} ל-{prev_year} לפי קבוצת סוג רכב." if prev_year else "")),
        "ytd_aria": (f"תרשים עמודות: {ytd_span} {last_year} לעומת {prev_year} לפי קבוצת סוג רכב. "
                     f"סך הכל {_int(ytd_cur)} לעומת {_int(ytd_prev)}." if prev_year else ""),
        "ytd_caption": f"כלי רכב לפי קבוצה, {ytd_span} {last_year} לעומת {prev_year}",
        "ytd_cur": ytd_x_cur,
        "ytd_prev": ytd_x_prev,
        "trend_note": ("סכום מתגלגל של 12 חודשים לכל קבוצת סוג רכב, כל גרף בסולם משלו: "
                       "כך רואים את המגמה בלי רעש עונתי ובלי עיוות של שנה חלקית."),
        "trend_aria": "גרפי קו קטנים: סכום מתגלגל של 12 חודשים לקבוצת סוג הרכב",
        "trend_caption": "כלי רכב ב-12 החודשים האחרונים לעומת 12 החודשים שקדמו להם, לפי קבוצה",
        "season_note": (f"כל משבצת היא חודש אחד; ככל שהצבע כהה יותר עלו לכביש יותר כלי רכב."
                        + (f" בממוצע על פני {len(full_years)} שנים מלאות, "
                           f"{MONTHS_HE[int(cal_avg.idxmax()) - 1]} הוא החודש העמוס ביותר ו"
                           f"{MONTHS_HE[int(cal_avg.idxmin()) - 1]} השקט ביותר."
                           if len(full_years) >= 1 and not cal_avg.empty else "")),
        "season_aria": (f"מפת חום: כלי רכב לפי חודש ושנה, {y_min} עד {y_max}. "
                        f"הערך הגבוה ביותר {_int(heat_max)}."),
        "makers_note": (f"{_int(MAKER_TOP)} היצרנים הגדולים לאורך כל התקופה ({_pct(top_share)} מכלל כלי הרכב), "
                        f"לצד מספר כלי הרכב שלהם ב-12 החודשים האחרונים. שם היצרן כפי שמופיע במאגר "
                        f"(שם ומדינת ייצור, לעיתים מקוצר)."),
        "makers_aria": (f"תרשים עמודות אופקי: {_int(MAKER_TOP)} היצרנים המובילים. "
                        f"במקום הראשון {by_maker.index[0]} עם {_int(by_maker.iloc[0])} כלי רכב."),
        "makers_caption": f"{_int(MAKER_TOP)} היצרנים המובילים לפי מספר כלי רכב",
        "tree_note": (f"כל מלבן הוא קבוצת סוג רכב, ובתוכו {_int(TREE_PER_TYPE)} היצרנים הגדולים בה; "
                      f"השאר מקובצים תחת {OTHER}. גודל המלבן לפי מספר כלי הרכב."),
        "tree_aria": (f"מפת עץ: כלי רכב לפי קבוצת סוג רכב ויצרן. "
                      f"הקבוצה הגדולה {by_type_ranked.index[0]}."),
        "conc_caption": "ריכוזיות היצרנים בכל קבוצת סוג רכב",
        "models_note": (f"{_int(MODEL_TOP)} שמות הדגם הנפוצים ביותר מתוך {_int(n_models)} צירופי יצרן ושם דגם. "
                        f"אלה כלי רכב שאין להם קוד דגם, ולכן שם הדגם נרשם כטקסט חופשי."),
        "models_aria": (f"תרשים עמודות אופקי: {_int(MODEL_TOP)} הדגמים הנפוצים. "
                        f"במקום הראשון {top_models[0][1]} של {top_models[0][0]} "
                        f"עם {_int(by_model.iloc[0])} כלי רכב."),
        "models_caption": f"{_int(MODEL_TOP)} הדגמים הנפוצים ביותר",
        "div_note": ("כמה יצרנים שונים וכמה שמות דגם שונים הופיעו בכל שנה."
                     + (f" שנת {last_year} חלקית." if partial_last else "")),
        "div_aria": (f"גרף קו: יצרנים ושמות דגם פעילים לפי שנה, {y_min} עד {y_max}. "
                     f"ב-{year_labels[-1]}: {_int(div['makers'].iloc[-1])} יצרנים."),
        "div_caption": "יצרנים, שמות דגם וכלי רכב לפי שנה",
    }

    tables = {
        "yearly": {"cols": groups,
                   "rows": [{"year": year_labels[i],
                             "vals": [_int(yearly_type.iloc[i][g]) for g in groups],
                             "total": _int(yearly_tot.iloc[i])} for i in range(len(years))]},
        "ytd": [{"name": r["name"], "prev": _int(r["prev"]), "cur": _int(r["cur"]),
                 "chg": "" if r["chg"] is None else _signed_pct(r["chg"] / 100)} for r in ytd_rows],
        "trend": trend_rows,
        "makers": makers_table,
        "conc": conc_table,
        "models": models_table,
        "diversity": div_table,
    }

    charts = {
        "monthly": {"x": [p.strftime("%Y-%m") for p in idx],
                    "y": [int(v) for v in monthly], "ma": ma_vals},
        "yearly": {"x": year_labels,
                   "series": [{"name": g, "data": [int(v) for v in yearly_type[g]]} for g in groups]},
        "ytd": {"names": [r["name"] for r in ytd_rows],
                "cur": [r["cur"] for r in ytd_rows], "prev": [r["prev"] for r in ytd_rows],
                "chg": [r["chg"] for r in ytd_rows],
                "cur_label": ytd_x_cur, "prev_label": ytd_x_prev},
        "multiples": {"x": roll_x, "series": multiples},
        "season": {"months": MONTHS_SHORT, "years": [str(y) for y in years],
                   "cells": cells, "max": heat_max},
        "makers": makers_chart,
        "tree": tree,
        "models": models_chart,
        "diversity": diversity,
    }

    flags = {"ytd": prev_year is not None and ytd_prev > 0,
             "multiples": len(roll_x) >= 2}

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["כלי רכב", "רכב חדש", "מסירות רכב", "גרורים", "משאיות", "משרד התחבורה"],
            "related_ids": ["e3f2eab4-bcdd-4fca-87db-18cb14ad4e4c",
                            "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                            "0219b34f-43c7-435b-bdfe-e65e944cde50",
                            "0f16b39a-6016-408d-805d-31f40d5a0990",
                            "392abd0a-64f6-4c18-9d56-0111001411e6"],
            "temporal_coverage": f"{y_min}/{y_max}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
