"""Recipe: קולות קוראים של משרד החדשנות, המדע והטכנולוגיה.

One row per funded proposal / scholarship / prize: call, category, program,
budget year, field, institution, researcher, gender, dates and budget.
Pure function of the data: no clock, no network, no randomness.
"""

import re

import pandas as pd

TOP_INST = 12
TOP_COUNTRY = 12
TOP_SUBFIELD = 12
TOP_CALLS = 10
TOP_FIELDS = 8
TOP_CATS = 5
TOP_PROGRAMS = 6

FEMALE = "נקבה"
MALE = "זכר"
ACTIVE = "מחקר פעיל"
OTHER = "אחר"
ILS = "ILS"

# Grant-size buckets in ILS: (upper bound exclusive, label)
SIZE_BUCKETS = [
    (50_000, "עד 50 אלף"),
    (100_000, "50-100 אלף"),
    (250_000, "100-250 אלף"),
    (500_000, "250-500 אלף"),
    (1_000_000, "500 אלף עד מיליון"),
    (2_000_000, "1-2 מיליון"),
    (float("inf"), "מעל 2 מיליון"),
]


def _clean(s: pd.Series) -> pd.Series:
    return s.astype(str).map(lambda v: re.sub(r"\s+", " ", v).strip())


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def _m(v: float) -> float:
    """ILS → millions, 1 decimal."""
    return round(float(v) / 1e6, 1)


def _pct(part: float, whole: float) -> float:
    return (part / whole) if whole else 0.0


def _top_with_other(counts: pd.Series, n: int) -> list[tuple[str, int]]:
    """counts: index=name, value=int. Sorted desc by value, then name."""
    items = sorted(((str(k), int(v)) for k, v in counts.items()), key=lambda kv: (-kv[1], kv[0]))
    top = items[:n]
    rest = sum(v for _, v in items[n:])
    if rest > 0:
        top.append((OTHER, rest))
    return top


def _sorted_counts(s: pd.Series) -> list[tuple[str, int]]:
    vc = s.value_counts()
    return sorted(((str(k), int(v)) for k, v in vc.items()), key=lambda kv: (-kv[1], kv[0]))


def compute(frames):
    df = frames["grants"].copy()
    for c in df.columns:
        df[c] = _clean(df[c])

    df["year"] = _num(df["budget_year"])
    bad_year = int(df["year"].isna().sum())
    df = df[df["year"].notna()].copy()
    df["year"] = df["year"].astype(int)
    df["amount"] = _num(df["budget"])
    df["is_ils"] = df["currency"].str.upper() == ILS
    df["start"] = pd.to_datetime(df["project_start_date"].str[:10], errors="coerce", format="%Y-%m-%d")
    df["end"] = pd.to_datetime(df["contract_end_date"].str[:10], errors="coerce", format="%Y-%m-%d")

    n = int(len(df))
    ils = df[df["is_ils"] & df["amount"].notna()]
    non_ils = df[~df["is_ils"] & df["amount"].notna()]
    total_ils = float(ils["amount"].sum())
    median_ils = float(ils["amount"].median()) if len(ils) else 0.0

    years = sorted(df["year"].unique().tolist())
    y0, y1 = (years[0], years[-1]) if years else (0, 0)

    # ── by year ─────────────────────────────────────────────────────────
    cnt_y = df.groupby("year").size()
    bud_y = ils.groupby("year")["amount"].sum()
    med_y = ils.groupby("year")["amount"].median()
    yearly = {
        "x": [str(y) for y in years],
        "count": [int(cnt_y.get(y, 0)) for y in years],
        "budget_m": [_m(bud_y.get(y, 0.0)) for y in years],
        "median_k": [round(float(med_y.get(y, 0.0)) / 1000, 1) for y in years],
    }

    # ── category × year ────────────────────────────────────────────────
    cat_counts = _top_with_other(df["category_of_call"].replace("", "לא צוין").value_counts(), TOP_CATS)
    cat_names = [k for k, _ in cat_counts]
    cat_known = set(cat_names) - {OTHER}
    df["cat"] = df["category_of_call"].replace("", "לא צוין")
    df["cat_b"] = df["cat"].where(df["cat"].isin(cat_known), OTHER)
    ct = df.groupby(["cat_b", "year"]).size()
    cat_year = {
        "years": [str(y) for y in years],
        "series": [
            {"name": c, "data": [int(ct.get((c, y), 0)) for y in years]} for c in cat_names
        ],
    }
    cat_year_rows = [
        {"year": str(y), "vals": [int(ct.get((c, y), 0)) for c in cat_names], "total": int(cnt_y.get(y, 0))}
        for y in years
    ]

    # category summary table (count, ILS budget, median)
    ils_cat = ils.assign(cat=ils["category_of_call"].replace("", "לא צוין"))
    cat_rows = []
    for c, k in _sorted_counts(df["cat"]):
        sub = ils_cat[ils_cat["cat"] == c]["amount"]
        cat_rows.append({
            "name": c, "count": k,
            "budget_m": _m(sub.sum()),
            "median_k": round(float(sub.median()) / 1000, 1) if len(sub) else 0.0,
        })

    # ── treemap: category → program (ILS budget) ───────────────────────
    ils_cat["prog"] = ils_cat["call_program"].replace("", "לא צוין")
    tm = []
    prog_rows = []
    for c, _ in sorted(
        ((c, float(v)) for c, v in ils_cat.groupby("cat")["amount"].sum().items()),
        key=lambda kv: (-kv[1], kv[0]),
    ):
        sub = ils_cat[ils_cat["cat"] == c]
        pb = sub.groupby("prog")["amount"].sum()
        pc = sub.groupby("prog").size()
        items = sorted(((p, float(v)) for p, v in pb.items()), key=lambda kv: (-kv[1], kv[0]))
        kids = []
        for p, v in items[:TOP_PROGRAMS]:
            kids.append({"name": p, "value": _m(v)})
            prog_rows.append({"cat": c, "prog": p, "count": int(pc.get(p, 0)), "budget_m": _m(v)})
        rest = items[TOP_PROGRAMS:]
        if rest:
            rv = sum(v for _, v in rest)
            rc = sum(int(pc.get(p, 0)) for p, _ in rest)
            kids.append({"name": OTHER, "value": _m(rv)})
            prog_rows.append({"cat": c, "prog": OTHER, "count": rc, "budget_m": _m(rv)})
        tm.append({"name": c, "value": _m(sub["amount"].sum()), "children": kids})

    # ── field ──────────────────────────────────────────────────────────
    df["fld"] = df["field"].replace("", "לא צוין")
    ils_f = ils.assign(fld=ils["field"].replace("", "לא צוין"))
    fld_counts = _top_with_other(df["fld"].value_counts(), TOP_FIELDS)
    fld_known = {k for k, _ in fld_counts} - {OTHER}
    ils_f["fld_b"] = ils_f["fld"].where(ils_f["fld"].isin(fld_known), OTHER)
    fb = ils_f.groupby("fld_b")["amount"].sum()
    fm = ils_f.groupby("fld_b")["amount"].median()
    field_rows = [
        {"name": f, "count": k, "budget_m": _m(fb.get(f, 0.0)),
         "median_k": round(float(fm.get(f, 0.0)) / 1000, 1) if f in fm.index else 0.0}
        for f, k in fld_counts
    ]
    field_rows.sort(key=lambda r: (-r["budget_m"], -r["count"], r["name"]))
    field_chart = {
        "names": [r["name"] for r in field_rows],
        "budget_m": [r["budget_m"] for r in field_rows],
        "count": [r["count"] for r in field_rows],
        "median_k": [r["median_k"] for r in field_rows],
    }

    # ── sub-field (excluding rows whose sub-field just repeats the field) ─
    sf = df[(df["sub_field"] != "") & (df["sub_field"] != df["field"])]
    sf_excluded = n - int(len(sf))
    sf_items = _sorted_counts(sf["sub_field"])[:TOP_SUBFIELD]
    sf_field = {}
    for name, _ in sf_items:
        top_f = _sorted_counts(sf[sf["sub_field"] == name]["field"])
        sf_field[name] = top_f[0][0] if top_f else ""
    subfield = {
        "names": [k for k, _ in sf_items],
        "count": [v for _, v in sf_items],
        "field": [sf_field[k] for k, _ in sf_items],
    }

    # ── institutions ───────────────────────────────────────────────────
    inst_df = df[df["institution"] != ""]
    inst_missing = n - int(len(inst_df))
    n_inst = int(inst_df["institution"].nunique())
    inst_items = _sorted_counts(inst_df["institution"])
    ib = ils[ils["institution"] != ""].groupby("institution")["amount"].sum()
    ifem = inst_df.groupby("institution")["gender"].apply(lambda g: int((g == FEMALE).sum()))
    inst_rows = []
    for name, k in inst_items[:TOP_INST]:
        inst_rows.append({
            "name": name, "count": k, "budget_m": _m(ib.get(name, 0.0)),
            "female_share": round(_pct(int(ifem.get(name, 0)), k), 3),
        })
    inst_rest = sum(k for _, k in inst_items[TOP_INST:])
    inst_chart = {
        "names": [r["name"] for r in inst_rows],
        "count": [r["count"] for r in inst_rows],
        "budget_m": [r["budget_m"] for r in inst_rows],
    }
    top5_share = _pct(sum(k for _, k in inst_items[:5]), int(len(inst_df)))

    # ── gender ─────────────────────────────────────────────────────────
    g = df[df["gender"].isin([FEMALE, MALE])]
    g_missing = n - int(len(g))
    fem_total = int((g["gender"] == FEMALE).sum())
    fem_share = _pct(fem_total, int(len(g)))
    gy_f = g[g["gender"] == FEMALE].groupby("year").size()
    gy_m = g[g["gender"] == MALE].groupby("year").size()
    gender_year = {
        "x": [str(y) for y in years],
        "female": [int(gy_f.get(y, 0)) for y in years],
        "male": [int(gy_m.get(y, 0)) for y in years],
        "share": [round(_pct(int(gy_f.get(y, 0)), int(gy_f.get(y, 0)) + int(gy_m.get(y, 0))) * 100, 1)
                  for y in years],
    }
    gc = []
    for c, _ in _sorted_counts(g["category_of_call"].replace("", "לא צוין")):
        sub = g[g["category_of_call"].replace("", "לא צוין") == c]
        f = int((sub["gender"] == FEMALE).sum())
        gc.append({"name": c, "female": f, "total": int(len(sub)),
                   "share": round(_pct(f, int(len(sub))) * 100, 1)})
    gc.sort(key=lambda r: (-r["share"], -r["total"], r["name"]))
    gf = []
    for f_name, _ in _sorted_counts(g["field"].replace("", "לא צוין")):
        sub = g[g["field"].replace("", "לא צוין") == f_name]
        f = int((sub["gender"] == FEMALE).sum())
        gf.append({"name": f_name, "female": f, "total": int(len(sub)),
                   "share": round(_pct(f, int(len(sub))) * 100, 1)})
    gf.sort(key=lambda r: (-r["share"], -r["total"], r["name"]))

    # ── partner countries ──────────────────────────────────────────────
    intl = df[df["partner_country"] != ""]
    n_intl = int(len(intl))
    n_countries = int(intl["partner_country"].nunique())
    country_items = _top_with_other(intl["partner_country"].value_counts(), TOP_COUNTRY)
    cb = ils[ils["partner_country"] != ""].groupby("partner_country")["amount"].sum()
    country_rows = [
        {"name": k, "count": v,
         "budget_m": _m(cb.get(k, 0.0)) if k != OTHER else _m(
             sum(float(cb.get(x, 0.0)) for x in cb.index if x not in {c for c, _ in country_items}))}
        for k, v in country_items
    ]
    cy = intl.groupby("year").size()
    intl_year_share = [round(_pct(int(cy.get(y, 0)), int(cnt_y.get(y, 0))) * 100, 1) for y in years]

    # ── grant size distribution (ILS) ──────────────────────────────────
    edges = [b for b, _ in SIZE_BUCKETS]
    size_labels = [lbl for _, lbl in SIZE_BUCKETS]
    size_counts = [0] * len(SIZE_BUCKETS)
    for v in ils["amount"].tolist():
        for i, ub in enumerate(edges):
            if v < ub:
                size_counts[i] += 1
                break
    size_budget = [0.0] * len(SIZE_BUCKETS)
    for v in ils["amount"].tolist():
        for i, ub in enumerate(edges):
            if v < ub:
                size_budget[i] += v
                break
    size = {"labels": size_labels, "count": size_counts, "budget_m": [_m(v) for v in size_budget]}
    max_row = ils.sort_values(["amount", "call_for_proposals", "institution"], ascending=[False, True, True]).head(1)

    # ── duration ───────────────────────────────────────────────────────
    dur = ((df["end"] - df["start"]).dt.days / 365.25).dropna()
    dur = dur[dur >= 0]
    dur_years = dur.round().astype(int).clip(lower=1)
    max_bucket = 5
    dur_labels, dur_counts = [], []
    for k in range(1, max_bucket + 1):
        if k < max_bucket:
            cnt = int((dur_years == k).sum())
            dur_labels.append("שנה אחת" if k == 1 else f"{k} שנים")
        else:
            cnt = int((dur_years >= k).sum())
            dur_labels.append(f"{k} שנים ומעלה")
        dur_counts.append(cnt)
    dur_missing = n - int(len(dur))
    dur_median = float(dur.median()) if len(dur) else 0.0
    duration = {"labels": dur_labels, "count": dur_counts}

    # ── status by year ─────────────────────────────────────────────────
    act = df["proposal_status"] == ACTIVE
    n_active = int(act.sum())
    rest_items = _sorted_counts(df.loc[~act, "proposal_status"].replace("", "סטטוס לא צוין"))
    st_names = [k for k, _ in _sorted_counts(df["proposal_status"].replace("", "לא צוין"))]
    st = df.assign(stt=df["proposal_status"].replace("", "לא צוין")).groupby(["stt", "year"]).size()
    status_year = {
        "years": [str(y) for y in years],
        "series": [{"name": s, "data": [int(st.get((s, y), 0)) for y in years]} for s in st_names],
    }
    status_rows = [
        {"year": str(y), "vals": [int(st.get((s, y), 0)) for s in st_names]} for y in years
    ]

    # ── top calls ──────────────────────────────────────────────────────
    calls = df[df["call_for_proposals"] != ""]
    n_calls = int(calls["call_for_proposals"].nunique())
    call_items = _sorted_counts(calls["call_for_proposals"])[:TOP_CALLS]
    cl_b = ils.groupby("call_for_proposals")["amount"].sum()
    cl_y = calls.groupby("call_for_proposals")["year"].min()
    call_rows = [
        {"name": k, "count": v, "budget_m": _m(cl_b.get(k, 0.0)), "year": int(cl_y.get(k, 0))}
        for k, v in call_items
    ]

    n_researchers = int(df.loc[df["researcher_full_name"] != "", "researcher_full_name"].nunique())

    # ── non-ILS disclosure ─────────────────────────────────────────────
    non_ils_note = ""
    if len(non_ils):
        cur_g = (non_ils.assign(cur=non_ils["currency"].replace("", "מטבע לא צוין"))
                 .groupby("cur")["amount"].agg(["size", "sum"]))
        parts = [
            f"{int(r['size']):,} מענקים ב{c}, סך {float(r['sum']):,.0f} {c}"
            for c, r in sorted(cur_g.iterrows(), key=lambda kv: (-int(kv[1]["size"]), kv[0]))
        ]
        non_ils_note = (
            "מענקים הנקובים במטבע אחר אינם נכללים בסכומים בשקלים: " + "; ".join(parts) + "."
        )

    # ── insights ───────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_trend():
        if len(years) < 2:
            return None
        a, b = years[-2], years[-1]
        ca, cb_ = int(cnt_y.get(a, 0)), int(cnt_y.get(b, 0))
        ba, bb = float(bud_y.get(a, 0.0)), float(bud_y.get(b, 0.0))
        if not ca or not ba:
            return None
        dc = (cb_ - ca) / ca
        db = (bb - ba) / ba
        if abs(dc) < 0.1:
            word = "מספר דומה של מענקים"
        elif dc > 0:
            word = f"עלייה של {dc * 100:.0f}% במספר המענקים"
        else:
            word = f"ירידה של {abs(dc) * 100:.0f}% במספר המענקים"
        bword = "התקציב בשקלים נותר דומה" if abs(db) < 0.1 else (
            f"התקציב בשקלים {'עלה' if db > 0 else 'ירד'} ב-{abs(db) * 100:.0f}%")
        return (f"בשנת התקציב {b} רשומים {cb_:,} מענקים לעומת {ca:,} ב-{a}: {word}; "
                f"{bword} ({_m(bb):,.1f} לעומת {_m(ba):,.1f} מיליון ₪). "
                "נתוני השנה האחרונה עשויים להתעדכן.")

    def ins_peak():
        if len(years) < 3 or bud_y.empty:
            return None
        items = sorted(((int(y), float(v)) for y, v in bud_y.items()), key=lambda kv: (-kv[1], kv[0]))
        py, pv = items[0]
        return (f"שנת התקציב עם ההיקף הגבוה ביותר היא {py}, עם {_m(pv):,.1f} מיליון ₪ "
                f"ב-{int(cnt_y.get(py, 0)):,} מענקים.")

    def ins_field():
        if not field_rows or total_ils <= 0:
            return None
        top = field_rows[0]
        share = top["budget_m"] * 1e6 / total_ils
        if share < 0.2:
            return None
        meds = [r for r in field_rows if r["name"] != OTHER and r["count"] >= 20]
        extra = ""
        if len(meds) >= 2:
            hi = sorted(meds, key=lambda r: (-r["median_k"], r["name"]))[0]
            lo = sorted(meds, key=lambda r: (r["median_k"], r["name"]))[0]
            if hi["median_k"] >= lo["median_k"] * 1.3:
                extra = (f" המענק החציוני הגבוה ביותר הוא ב{hi['name']} ({hi['median_k']:,.0f} אלף ₪), "
                         f"והנמוך ביותר ב{lo['name']} ({lo['median_k']:,.0f} אלף ₪), "
                         "בקרב תחומים עם 20 מענקים לפחות.")
        return f"התחום \"{top['name']}\" מקבל {share * 100:.1f}% מהתקציב בשקלים ({top['budget_m']:,.1f} מיליון ₪).{extra}"

    def ins_inst():
        if len(inst_items) < 6:
            return None
        lead, k = inst_items[0]
        if top5_share >= 0.5:
            return (f"חמשת המוסדות המובילים מחזיקים {top5_share * 100:.1f}% מהמענקים; "
                    f"בראשם {lead} עם {k:,} מענקים, מתוך {n_inst:,} מוסדות במאגר.")
        return f"המענקים מפוזרים בין {n_inst:,} מוסדות; המוביל, {lead}, מחזיק {k:,} מענקים."

    def ins_gender():
        if len(g) < 50 or not gc:
            return None
        base = f"{fem_share * 100:.1f}% מהזוכים שמגדרם צוין הן נשים"
        big = [r for r in gc if r["total"] >= 30]
        if len(big) >= 2:
            hi, lo = big[0], big[-1]
            if hi["share"] - lo["share"] >= 10:
                return (f"{base}. השיעור משתנה מאוד לפי סוג הקול הקורא: {hi['share']:.1f}% ב{hi['name']} "
                        f"לעומת {lo['share']:.1f}% ב{lo['name']} (קטגוריות עם 30 זוכים לפחות).")
        return base + "."

    def ins_gender_trend():
        rows = [(y, f, m) for y, f, m in zip(years, gender_year["female"], gender_year["male"]) if f + m >= 30]
        if len(rows) < 3:
            return None
        first, last = rows[0], rows[-1]
        s0 = _pct(first[1], first[1] + first[2]) * 100
        s1 = _pct(last[1], last[1] + last[2]) * 100
        d = s1 - s0
        if abs(d) < 3:
            return (f"שיעור הנשים בין הזוכים יציב יחסית: {s0:.1f}% ב-{first[0]} ו-{s1:.1f}% ב-{last[0]} "
                    "(שנים עם 30 זוכים לפחות).")
        word = "עלה" if d > 0 else "ירד"
        return (f"שיעור הנשים בין הזוכים {word} מ-{s0:.1f}% ב-{first[0]} ל-{s1:.1f}% ב-{last[0]} "
                "(שנים עם 30 זוכים לפחות).")

    def ins_intl():
        if n_intl < 20 or not country_items:
            return None
        lead, k = country_items[0]
        if lead == OTHER:
            return None
        return (f"{_pct(n_intl, n) * 100:.1f}% מהמענקים ({n_intl:,}) ניתנו בשיתוף פעולה עם {n_countries:,} "
                f"מדינות וגופים שותפים; המובילה היא {lead} עם {k:,} מענקים ({_pct(k, n_intl) * 100:.1f}%).")

    def ins_median():
        rows = [(y, m, c) for y, m, c in zip(years, yearly["median_k"], yearly["count"]) if c >= 30]
        if len(rows) < 3:
            return None
        (fy, fm_, _), (ly, lm, _) = rows[0], rows[-1]
        if not fm_:
            return None
        d = (lm - fm_) / fm_
        if abs(d) < 0.1:
            return None
        word = "עלה" if d > 0 else "ירד"
        return (f"המענק החציוני בשקלים {word} מ-{fm_:,.0f} אלף ₪ ב-{fy} ל-{lm:,.0f} אלף ₪ ב-{ly} "
                f"({'+' if d > 0 else '−'}{abs(d) * 100:.0f}%, שנים עם 30 מענקים לפחות).")

    def ins_size():
        if len(ils) < 50:
            return None
        big = sum(c for c, (ub, _) in zip(size_counts, SIZE_BUCKETS) if ub > 1_000_000)
        big_b = sum(b for b, (ub, _) in zip(size_budget, SIZE_BUCKETS) if ub > 1_000_000)
        if big == 0 or total_ils <= 0:
            return None
        return (f"{big:,} מענקים בלבד ({_pct(big, len(ils)) * 100:.1f}%) הם של מיליון ₪ ומעלה, "
                f"אך הם מרכזים {_pct(big_b, total_ils) * 100:.1f}% מהתקציב בשקלים.")

    add("trend", ins_trend())
    add("peak", ins_peak())
    add("field", ins_field())
    add("institutions", ins_inst())
    add("gender", ins_gender())
    add("gender_trend", ins_gender_trend())
    add("international", ins_intl())
    add("median", ins_median())
    add("size", ins_size())

    # ── KPIs ───────────────────────────────────────────────────────────
    fem_tone = "warn" if fem_share < 0.4 else ("ok" if fem_share >= 0.45 else "info")
    span = f"{y0}–{y1}" if y0 != y1 else str(y0)
    kpis = {
        "total": {"value": n, "display": f"{n:,}", "tone": "brand"},
        "budget": {"value": _m(total_ils), "display": f"{_m(total_ils):,.1f}", "tone": "brand"},
        "median": {"value": round(median_ils / 1000, 1), "display": f"{median_ils / 1000:,.1f}", "tone": "brand"},
        "years": {"value": span, "display": span, "tone": "brand"},
        "institutions": {"value": n_inst, "display": f"{n_inst:,}", "tone": "brand"},
        "researchers": {"value": n_researchers, "display": f"{n_researchers:,}", "tone": "brand"},
        "female": {"value": round(fem_share * 100, 1), "display": f"{fem_share * 100:.1f}%", "tone": fem_tone},
        "active": {"value": n_active, "display": f"{n_active:,}", "tone": "info"},
    }

    # ── labels / ledes ─────────────────────────────────────────────────
    last_y = years[-1] if years else 0
    peak_c_y = max(years, key=lambda y: (int(cnt_y.get(y, 0)), -y)) if years else 0
    lbl = {
        "budget_kpi": "סך התקציב בשקלים (מיליון ₪)",
        "median_kpi": "מענק חציוני (אלפי ₪)",
        "years_kpi": "שנות תקציב",
        "female_kpi": "שיעור נשים בין הזוכים",
        "active_kpi": "מחקרים פעילים",
        "non_ils_note": non_ils_note,
        "bad_year_note": (f"{bad_year:,} רשומות ללא שנת תקציב תקינה אינן נכללות." if bad_year else ""),
        "yearly_lede": (
            f"השנה עם המספר הרב ביותר של מענקים היא {peak_c_y} ({int(cnt_y.get(peak_c_y, 0)):,}). "
            f"בשנת {last_y} רשומים {int(cnt_y.get(last_y, 0)):,} מענקים בהיקף {_m(bud_y.get(last_y, 0.0)):,.1f} מיליון ₪."
        ),
        "yearly_aria": (f"גרף עמודות וקו: מספר המענקים והתקציב בשקלים לפי שנת תקציב, {span}. "
                        f"שיא המענקים ב-{peak_c_y}."),
        "cat_lede": (
            f"המאגר כולל {len(cat_rows):,} סוגי קולות קוראים. הנפוץ ביותר: {cat_rows[0]['name']} "
            f"עם {cat_rows[0]['count']:,} מענקים ({_pct(cat_rows[0]['count'], n) * 100:.1f}%)."
            if cat_rows else ""
        ),
        "cat_aria": "גרף עמודות מוערמות: מספר המענקים לפי סוג קול קורא ושנת תקציב.",
        "prog_lede": (
            f"חלוקת התקציב בשקלים לפי סוג הקול הקורא ולפי המסלול שבתוכו. "
            f"החלק הגדול ביותר: {tm[0]['name']}, {tm[0]['value']:,.1f} מיליון ₪."
            if tm else ""
        ),
        "prog_aria": (f"מפת שטחים: התקציב בשקלים לפי סוג קול קורא ומסלול. הגדול ביותר {tm[0]['name']}."
                      if tm else "מפת שטחים: התקציב לפי סוג קול קורא ומסלול."),
        "field_lede": (
            f"התחום עם התקציב הגדול ביותר: {field_rows[0]['name']} ({field_rows[0]['budget_m']:,.1f} מיליון ₪ "
            f"ב-{field_rows[0]['count']:,} מענקים)."
            if field_rows else ""
        ),
        "field_aria": "גרף עמודות אופקי: התקציב בשקלים ומספר המענקים לפי תחום מדעי.",
        "sub_lede": (
            f"{len(sf):,} מענקים משויכים לתת-תחום ייעודי. "
            + (f"{sf_excluded:,} מענקים שתת-התחום שלהם זהה לתחום הראשי או חסר אינם נכללים בתרשים."
               if sf_excluded else "")
        ),
        "sub_aria": (f"גרף עמודות אופקי: {len(sf_items):,} תתי-התחומים עם מספר המענקים הגבוה ביותר."
                     + (f" המוביל: {sf_items[0][0]}." if sf_items else "")),
        "inst_lede": (
            f"{n_inst:,} מוסדות זכו במענקים. חמשת המובילים מחזיקים {top5_share * 100:.1f}% מהמענקים"
            + (f"; {inst_rest:,} מענקים נוספים מתחלקים בין שאר המוסדות" if inst_rest else "")
            + "."
            + (f" ל-{inst_missing:,} מענקים לא צוין מוסד." if inst_missing else "")
        ),
        "inst_aria": (f"גרף עמודות אופקי: {len(inst_rows):,} המוסדות עם מספר המענקים הגבוה ביותר."
                      + (f" המוביל: {inst_rows[0]['name']} עם {inst_rows[0]['count']:,}." if inst_rows else "")),
        "gender_lede": (
            f"{fem_total:,} זוכות מתוך {len(g):,} זוכים שמגדרם צוין ({fem_share * 100:.1f}%)."
            + (f" ל-{g_missing:,} רשומות לא צוין מגדר." if g_missing else "")
        ),
        "gender_year_aria": f"גרף עמודות מוערמות וקו: זוכים וזוכות לפי שנת תקציב ושיעור הנשים, {span}.",
        "gender_cat_aria": (f"גרף עמודות אופקי: שיעור הנשים בין הזוכים לפי סוג קול קורא. הגבוה ביותר: {gc[0]['name']}."
                            if gc else "גרף עמודות אופקי: שיעור הנשים לפי סוג קול קורא."),
        "gender_field_aria": (f"גרף עמודות אופקי: שיעור הנשים בין הזוכים לפי תחום. הגבוה ביותר: {gf[0]['name']}."
                              if gf else "גרף עמודות אופקי: שיעור הנשים לפי תחום."),
        "country_lede": (
            f"{n_intl:,} מענקים ({_pct(n_intl, n) * 100:.1f}%) הם חלק משיתוף פעולה בינלאומי עם "
            f"{n_countries:,} מדינות וגופים שותפים."
        ),
        "country_aria": (f"גרף עמודות אופקי: מספר המענקים לפי מדינה שותפה."
                         + (f" המובילה: {country_items[0][0]}." if country_items else "")),
        "size_lede": (
            f"המענק החציוני בשקלים הוא {median_ils / 1000:,.1f} אלף ₪"
            + (f"; הגדול ביותר, {_m(float(max_row['amount'].iloc[0])):,.1f} מיליון ₪, "
               f"ניתן ל{max_row['institution'].iloc[0] or 'מוסד שלא צוין'} בשנת {int(max_row['year'].iloc[0])}"
               if len(max_row) else "")
            + "."
        ),
        "size_aria": "גרף עמודות: התפלגות גודל המענקים בשקלים לפי טווחי סכום.",
        "dur_lede": (
            f"משך ההתקשרות החציוני הוא {dur_median:.1f} שנים, מתאריך תחילת הפרויקט ועד סיום החוזה."
            + (f" ל-{dur_missing:,} מענקים אין תאריכים תקינים." if dur_missing else "")
        ),
        "dur_aria": "גרף עמודות: מספר המענקים לפי משך ההתקשרות בשנים (מעוגל).",
        "status_lede": (
            f"{n_active:,} מענקים ({_pct(n_active, n) * 100:.1f}%) מסומנים כמחקר פעיל"
            + (("; השאר: " + ", ".join(f"\"{k}\" ({v:,})" for k, v in rest_items) + ".")
               if rest_items else ".")
        ),
        "status_aria": "גרף עמודות מוערמות: מספר המענקים לפי סטטוס ושנת תקציב.",
        "calls_lede": (
            f"המאגר כולל {n_calls:,} קולות קוראים. הגדול ביותר במספר הזוכים: "
            f"\"{call_rows[0]['name']}\" עם {call_rows[0]['count']:,} מענקים."
            if call_rows else ""
        ),
        "calls_aria": (f"גרף עמודות אופקי: {len(call_rows):,} הקולות הקוראים עם מספר הזוכים הגבוה ביותר."),
    }

    summary = (
        f"איתור מחקרים ומלגות שמומנו בקולות קוראים של משרד המדע לפי חוקר, מוסד או תחום: "
        f"{n:,} מענקים בשנים {y0}-{y1}, {_m(total_ils):,.1f} מיליון ₪."
    )

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["מחקר", "קול קורא", "מענקי מחקר", "מלגות", "שיתוף פעולה בינלאומי", "משרד המדע"],
            "related_ids": [
                "80862c9b-fe75-4950-8bc8-62d9e414dd2e",
                "4a787551-f06c-4eff-891f-61a7b0e6037c",
                "5b8efc55-e12d-434e-8bae-7579a0975e6c",
                "836be8e0-40ae-4e4b-afc3-74b96e9c754a",
                "47acbf53-8ad7-477b-a736-8ff96a3f806e",
            ],
            "temporal_coverage": f"{y0}/{y1}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "yearly": yearly,
            "cat_year": cat_year,
            "treemap": tm,
            "field": field_chart,
            "subfield": subfield,
            "inst": inst_chart,
            "gender_year": gender_year,
            "gender_cat": {"names": [r["name"] for r in gc], "share": [r["share"] for r in gc],
                           "total": [r["total"] for r in gc]},
            "gender_field": {"names": [r["name"] for r in gf], "share": [r["share"] for r in gf],
                             "total": [r["total"] for r in gf]},
            "country": {"names": [r["name"] for r in country_rows], "count": [r["count"] for r in country_rows],
                        "budget_m": [r["budget_m"] for r in country_rows]},
            "size": size,
            "duration": duration,
            "status": status_year,
            "calls": {"names": [r["name"] for r in call_rows], "count": [r["count"] for r in call_rows],
                      "budget_m": [r["budget_m"] for r in call_rows]},
            "intl_share": {"x": [str(y) for y in years], "share": intl_year_share},
        },
        "tables": {
            "cat_names": cat_names,
            "cat_year": cat_year_rows,
            "cats": cat_rows,
            "programs": prog_rows,
            "fields": field_rows,
            "institutions": inst_rows,
            "gender_cat": gc,
            "gender_field": gf,
            "countries": country_rows,
            "status_names": st_names,
            "status": status_rows,
            "calls": call_rows,
        },
        "flags": {
            "has_intl": n_intl > 0,
            "has_subfield": len(sf_items) > 0,
        },
        "labels": lbl,
        "insights": insights,
    }
