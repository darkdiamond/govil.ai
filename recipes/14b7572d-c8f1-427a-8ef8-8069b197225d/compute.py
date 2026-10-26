"""ניטור נמלת האש הקטנה במשתלות — Ministry of Environmental Protection
monitoring of the little fire ant (Wasmannia auropunctata) in plant nurseries.

One row per nursery (~370): location (ITM X/Y), local authority, and up to
three recorded inspections (date + result: "נגיעות" / "ללא נגיעות"), filled
in order (first → second → third). `results_ma` is the ministry's own current
status: the latest result when the nursery was inspected in the last year,
else "לא נבדק בשנה האחרונה". That status is used as published — the page never
re-derives "the last year" (no wall clock).

"Latest" means the latest inspection date in the data. Its calendar year is
partial unless it reaches December; partial years are labelled and kept out
of the trend rule (disclosed). Nurseries are businesses and may be named,
but the page only aggregates (the shell's explorer and the map popups carry
the rows as published).
"""
import pandas as pd

INF = "נגיעות"
CLEAN = "ללא נגיעות"
STALE = "לא נבדק בשנה האחרונה"
VISITS = [("first_visi", "first_resu"), ("second_vis", "second_res"), ("third_visi", "third_resu")]
STAGE_NAMES = ["בדיקה ראשונה", "בדיקה שנייה", "בדיקה שלישית"]
TOP_AUTH = 15
MIN_YEAR_INSPECTIONS = 30     # a complete year needs this many inspections for the trend rule
TREND_PP = 0.05               # ±5 percentage points = a direction, else stable
MIN_BASE = 20                 # minimum group size for comparative insights
ATYPE_MIN = 40               # authority-type group size for the type comparison
STALE_SHARE = 0.25            # "many nurseries not inspected lately" threshold
EXCEL_MIN, EXCEL_MAX = 36526, 73051   # Excel serials for 2000-01-01 … 2099-12-31
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
COLORS = {INF: "#dc3545", CLEAN: "#198754", STALE: "#c3cfe7"}
NONE_COLOR = "#c3cfe7"
OTHER_COLOR = "#0068f5"
GAP_BINS = [(0, 6, "עד חצי שנה"), (6, 12, "חצי שנה עד שנה"), (12, 18, "שנה עד שנה וחצי"),
            (18, 24, "שנה וחצי עד שנתיים"), (24, 36, "שנתיים עד שלוש"),
            (36, None, "יותר משלוש שנים")]
OUTCOMES = [
    ("single_inf", "בדיקה אחת — נגיעות", "#dc3545"),
    ("single_clean", "בדיקה אחת — ללא נגיעות", "#198754"),
    ("all_inf", "נגיעות בכל הבדיקות", "#dc3545"),
    ("cleared", "נגיעות בעבר, נקייה בבדיקה האחרונה", "#0068f5"),
    ("new_inf", "נקייה בעבר, נגיעות בבדיקה האחרונה", "#9a6700"),
    ("all_clean", "ללא נגיעות בכל הבדיקות", "#198754"),
]


def n(v):
    return f"{int(v):,}"


def pct(x, digits=0):
    return f"{LRI}{x * 100:.{digits}f}%{PDI}"


def pct_bare(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _date(s):
    """ISO date-times, plus the odd Excel serial day number the XLSX export
    leaves behind (e.g. "45953" = 2025-10-23)."""
    s = s.str.strip()
    d = pd.to_datetime(s.str.slice(0, 10), errors="coerce", format="%Y-%m-%d")
    serial = pd.to_numeric(s.where(s.str.fullmatch(r"\d{5}(\.0+)?")), errors="coerce")
    serial = serial.where(serial.between(EXCEL_MIN, EXCEL_MAX))
    from_serial = pd.Timestamp("1899-12-30") + pd.to_timedelta(serial.round(), unit="D")
    return d.fillna(from_serial)


def _short_authority(a):
    """Axis label: the customary abbreviations for regional / local councils."""
    for full, short in (("מועצה אזורית ", "מ״א "), ("מועצה מקומית ", "מ״מ ")):
        if a.startswith(full):
            return short + a[len(full):]
    return a


def _prepare(df):
    out = pd.DataFrame({
        "authority": df["municipal"].str.strip().replace("", "לא צוין"),
        "status": df["results_ma"].str.strip().replace("", "לא צוין"),
    })
    dates, results = [], []
    n_bad = 0
    for dc, rc in VISITS:
        d = _date(df[dc])
        r = df[rc].str.strip()
        ok = d.notna() & r.isin([INF, CLEAN])
        n_bad += int(((df[dc].str.strip() != "") & ~ok).sum())
        dates.append(d.where(ok))
        results.append(r.where(ok, ""))
    for i in range(3):
        out[f"d{i}"] = dates[i]
        out[f"r{i}"] = results[i]
    out["nvis"] = sum(out[f"r{i}"].ne("").astype(int) for i in range(3))
    seq = out[["r0", "r1", "r2"]].apply(lambda row: [v for v in row if v], axis=1)
    out["seq"] = seq
    out["first_r"] = seq.map(lambda s: s[0] if s else "")
    out["last_r"] = seq.map(lambda s: s[-1] if s else "")
    out["ever_inf"] = seq.map(lambda s: INF in s)
    last_d = out["d2"].fillna(out["d1"]).fillna(out["d0"])
    first_d = out["d0"].fillna(out["d1"]).fillna(out["d2"])
    out["last_d"], out["first_d"] = last_d, first_d
    a = out["authority"]
    out["atype"] = a.map(lambda s: "מועצות אזוריות" if s.startswith("מועצה אזורית")
                         else "מועצות מקומיות" if s.startswith("מועצה מקומית")
                         else "ערים ורשויות אחרות")
    return out.reset_index(drop=True), n_bad


def _visits(df):
    parts = [pd.DataFrame({"d": df[f"d{i}"], "r": df[f"r{i}"]}) for i in range(3)]
    v = pd.concat(parts, ignore_index=True)
    v = v[v["r"] != ""].copy()
    v["y"] = v["d"].dt.year.astype(int)
    return v


def _outcome(seq):
    if not seq:
        return None
    if len(seq) == 1:
        return "single_inf" if seq[0] == INF else "single_clean"
    if all(x == INF for x in seq):
        return "all_inf"
    if all(x == CLEAN for x in seq):
        return "all_clean"
    return "new_inf" if seq[-1] == INF else "cleared"


def _period(visits):
    last = visits["d"].max()
    partial = last.month < 12
    return last, partial


def _year_label(y, last, partial):
    return f"{y} (עד {MONTHS_HE[last.month - 1]})" if partial and y == last.year else str(y)


# ── insight rules ────────────────────────────────────────────────────────────

def insight_now(df):
    st = df["status"]
    inf, clean = int((st == INF).sum()), int((st == CLEAN).sum())
    recent = inf + clean
    if recent < 10:
        return None
    share = inf / recent
    lead = "יותר ממחצית" if share > 0.5 else "פחות ממחצית" if share < 0.5 else "מחצית"
    return (f"מבין {n(recent)} המשתלות שנבדקו בשנה האחרונה לפי הסטטוס במאגר, ב-{n(inf)} "
            f"({pct(share)}) נמצאה נגיעות בנמלת האש הקטנה — {lead} מהמשתלות שנבדקו לאחרונה.")


def insight_stale(df, last):
    st = df["status"]
    k = int((st == STALE).sum())
    share = k / len(df)
    if share < STALE_SHARE:
        return None
    cutoff = last.year - 3
    old = int(((st == STALE) & (df["last_d"].dt.year <= cutoff)).sum())
    tail = (f"; אצל {n(old)} מהן הבדיקה האחרונה במאגר נערכה ב-{cutoff} או לפני כן"
            if old else "")
    return (f"{n(k)} משתלות ({pct(share)}) לא נבדקו בשנה האחרונה, ולכן אין להן סטטוס עדכני{tail}.")


def insight_ever(df):
    m = df["nvis"] > 0
    base = int(m.sum())
    if base < MIN_BASE:
        return None
    k = int(df.loc[m, "ever_inf"].sum())
    first = int((df.loc[m, "first_r"] == INF).sum())
    return (f"ב-{n(k)} מתוך {n(base)} המשתלות ({pct(k / base)}) נמצאה נגיעות לפחות באחת "
            f"הבדיקות הרשומות; ב-{n(first)} מהן כבר בבדיקה הראשונה.")


def insight_persist(df):
    f = df[df["nvis"] >= 2]
    a = f[f["first_r"] == INF]
    b = f[f["first_r"] == CLEAN]
    if len(a) < MIN_BASE:
        return None
    still = int((a["last_r"] == INF).sum())
    s = (f"הנגיעות עיקשת: מתוך {n(len(a))} משתלות שנמצאו נגועות בבדיקה הראשונה ונבדקו שוב, "
         f"{n(still)} ({pct(still / len(a))}) עדיין נגועות בבדיקה האחרונה")
    if still / len(a) < 0.5:
        s = (f"מתוך {n(len(a))} משתלות שנמצאו נגועות בבדיקה הראשונה ונבדקו שוב, רק "
             f"{n(still)} ({pct(still / len(a))}) עדיין נגועות בבדיקה האחרונה")
    if len(b) >= MIN_BASE:
        turned = int((b["last_r"] == INF).sum())
        s += (f", ומתוך {n(len(b))} שהיו נקיות בבדיקה הראשונה, {n(turned)} "
              f"({pct(turned / len(b))}) נמצאו נגועות בבדיקה האחרונה")
    return s + "."


def insight_trend(yearly, last, partial):
    full = [r for r in yearly if not (partial and r["y"] == last.year) and r["total"] >= MIN_YEAR_INSPECTIONS]
    if len(full) < 3:
        return None
    peak = sorted(full, key=lambda r: (-r["share"], r["y"]))[0]
    cur = full[-1]
    note = (f"; לא כולל {last.year}, שהנתונים עליה חלקיים" if partial else "")
    if peak["y"] == cur["y"]:
        return (f"שיעור הבדיקות שבהן נמצאה נגיעות הגיע לשיא ב-{cur['y']} — {pct(cur['share'])} "
                f"מ-{n(cur['total'])} בדיקות{note.replace('; ', ' — ')}.")
    diff = cur["share"] - peak["share"]
    if diff <= -TREND_PP:
        tail = f"ובשנת {cur['y']} ירד ל-{pct(cur['share'])}"
    else:
        tail = f"ובשנת {cur['y']} נותר קרוב לשיא — {pct(cur['share'])}"
    return (f"שיעור הבדיקות שבהן נמצאה נגיעות הגיע לשיא ב-{peak['y']} ({pct(peak['share'])}), "
            f"{tail} (מתוך {n(cur['total'])} בדיקות{note}).")


def insight_authority(df):
    g = df.groupby("authority").agg(n=("ever_inf", "size"), k=("ever_inf", "sum")).reset_index()
    g = g.sort_values(["k", "n", "authority"], ascending=[False, False, True], kind="stable")
    if len(g) < 2:
        return None
    top, second = g.iloc[0], g.iloc[1]
    if int(top["k"]) < 5 or int(top["k"]) == int(second["k"]):
        return None
    return (f"{top['authority']} מובילה במספר המשתלות שנמצאה בהן נגיעות אי-פעם — "
            f"{n(top['k'])} מתוך {n(top['n'])} המשתלות שבתחומה, ואחריה {second['authority']} "
            f"({n(second['k'])} מתוך {n(second['n'])}).")


def insight_gap(gaps):
    if len(gaps) < MIN_BASE:
        return None
    med = float(gaps.median())
    over2 = float((gaps > 24).mean())
    return (f"הזמן החציוני בין שתי בדיקות עוקבות באותה משתלה הוא כ-{med:.0f} חודשים, "
            f"וב-{pct(over2)} מהמקרים עברו יותר משנתיים עד הבדיקה הבאה.")


def insight_atype(df):
    g = df.groupby("atype")["ever_inf"].agg(["size", "mean"])
    g = g[g["size"] >= ATYPE_MIN]
    if len(g) < 2:
        return None
    g = g.reset_index().sort_values(["mean", "atype"], ascending=[False, True], kind="stable")
    hi, lo = g.iloc[0], g.iloc[-1]
    if hi["mean"] - lo["mean"] < 0.10:
        return None
    return (f"שיעור המשתלות שנמצאה בהן נגיעות אי-פעם גבוה יותר ב{hi['atype']} "
            f"({pct(hi['mean'])} מ-{n(hi['size'])}) מאשר ב{lo['atype']} "
            f"({pct(lo['mean'])} מ-{n(lo['size'])}).")


# ── compute ──────────────────────────────────────────────────────────────────

def compute(frames):
    df, n_bad = _prepare(frames["nurseries"])
    total = len(df)
    visits = _visits(df)
    last, partial = _period(visits)
    first_year = int(visits["y"].min())

    # Current status (ministry's field)
    status = _ranked(df["status"])
    order = [s for s in [INF, CLEAN, STALE] if s in status.index] + \
            [s for s in status.index if s not in (INF, CLEAN, STALE)]
    status_chart = [{"name": s, "value": int(status[s]),
                     "itemStyle": {"color": COLORS.get(s, OTHER_COLOR)}} for s in order]
    t_status = [{"name": s, "count": n(status[s]), "share": pct_bare(status[s] / total)} for s in order]

    # Journey: stage-to-stage transitions (sankey)
    nodes, links, t_journey = [], [], []
    def node(stage, res):
        return f"{STAGE_NAMES[stage]}: {res}"
    for st in range(3):
        for res in (INF, CLEAN):
            nodes.append({"name": node(st, res), "itemStyle": {"color": COLORS[res]}})
    for st in (1, 2):
        nodes.append({"name": f"ללא {STAGE_NAMES[st]}", "itemStyle": {"color": NONE_COLOR}})
    for st in (0, 1):
        prev = df[df[f"r{st}"] != ""]
        for a in (INF, CLEAN):
            src = prev[prev[f"r{st}"] == a]
            for b in (INF, CLEAN, ""):
                k = int((src[f"r{st + 1}"] == b).sum())
                tgt = node(st + 1, b) if b else f"ללא {STAGE_NAMES[st + 1]}"
                if k:
                    links.append({"source": node(st, a), "target": tgt, "value": k})
                t_journey.append({"from": node(st, a), "to": tgt, "count": n(k)})
    used = {l["source"] for l in links} | {l["target"] for l in links}
    journey = {"nodes": [x for x in nodes if x["name"] in used], "links": links}

    # Outcome per nursery
    df["outcome"] = df["seq"].map(_outcome)
    oc = df["outcome"].value_counts()
    outcome_chart = {"names": [lbl for _, lbl, _ in OUTCOMES],
                     "values": [{"value": int(oc.get(k, 0)), "itemStyle": {"color": c}}
                                for k, _, c in OUTCOMES]}
    with_vis = int((df["nvis"] > 0).sum())
    t_outcome = [{"name": lbl, "count": n(oc.get(k, 0)),
                  "share": pct_bare(oc.get(k, 0) / with_vis if with_vis else 0)}
                 for k, lbl, _ in OUTCOMES]

    # Inspections per year
    yt = visits.groupby(["y", "r"]).size()
    years = list(range(first_year, last.year + 1))
    yearly = []
    for y in years:
        i, c = int(yt.get((y, INF), 0)), int(yt.get((y, CLEAN), 0))
        yearly.append({"y": y, "inf": i, "clean": c, "total": i + c,
                       "share": (i / (i + c)) if i + c else 0.0})
    year_labels = [_year_label(y, last, partial) for y in years]
    axis_years = [str(y) for y in years]   # short labels for chart axes; tables carry the partial mark
    yearly_chart = {"years": axis_years, "inf": [r["inf"] for r in yearly],
                    "clean": [r["clean"] for r in yearly],
                    "share": [round(r["share"] * 100, 1) if r["total"] else None for r in yearly]}
    t_yearly = [{"name": year_labels[i], "inf": n(r["inf"]), "clean": n(r["clean"]),
                 "share": pct_bare(r["share"]) if r["total"] else "—"} for i, r in enumerate(yearly)]

    # Cohort: first inspection year
    fv = df[df["nvis"] > 0]
    ct = fv.groupby([fv["first_d"].dt.year.astype(int), "first_r"]).size()
    cohort_chart = {"years": axis_years,
                    "inf": [int(ct.get((y, INF), 0)) for y in years],
                    "clean": [int(ct.get((y, CLEAN), 0)) for y in years]}
    t_cohort = []
    for i, y in enumerate(years):
        a, b = cohort_chart["inf"][i], cohort_chart["clean"][i]
        t_cohort.append({"name": year_labels[i], "total": n(a + b), "inf": n(a),
                         "share": pct_bare(a / (a + b)) if a + b else "—"})
    busiest = max(range(len(years)), key=lambda i: (cohort_chart["inf"][i] + cohort_chart["clean"][i], -i))

    # Recency: year of the last recorded inspection, by its result
    rt = fv.groupby([fv["last_d"].dt.year.astype(int), "last_r"]).size()
    recency_chart = {"years": axis_years,
                     "inf": [int(rt.get((y, INF), 0)) for y in years],
                     "clean": [int(rt.get((y, CLEAN), 0)) for y in years]}
    t_recency = [{"name": year_labels[i], "inf": n(recency_chart["inf"][i]),
                  "clean": n(recency_chart["clean"][i])} for i in range(len(years))]
    last_year_n = recency_chart["inf"][-1] + recency_chart["clean"][-1]

    # Gaps between consecutive inspections (months)
    gaps = []
    for i in (0, 1):
        g = (df[f"d{i + 1}"] - df[f"d{i}"]).dt.days.dropna() / 30.4375
        gaps.append(g)
    gaps = pd.concat(gaps, ignore_index=True).sort_values(kind="stable").reset_index(drop=True)
    gap_vals = []
    for lo, hi, _ in GAP_BINS:
        m = gaps >= lo
        if hi is not None:
            m &= gaps < hi
        gap_vals.append(int(m.sum()))
    gap_chart = {"names": [lbl for _, _, lbl in GAP_BINS], "values": gap_vals}
    t_gap = [{"name": lbl, "count": n(v), "share": pct_bare(v / len(gaps) if len(gaps) else 0)}
             for (_, _, lbl), v in zip(GAP_BINS, gap_vals)]

    # Authorities: top by nurseries, stacked by current status
    auth = df.groupby("authority").size().reset_index(name="n")
    auth = auth.sort_values(["n", "authority"], ascending=[False, True], kind="stable")
    top_auth = list(auth["authority"].head(TOP_AUTH))
    by_as = df.groupby(["authority", "status"]).size()
    ever_by_a = df.groupby("authority")["ever_inf"].sum()
    auth_chart = {"names": top_auth, "short": [_short_authority(a) for a in top_auth],
                  "series": [{"name": s, "color": COLORS.get(s, OTHER_COLOR),
                              "data": [int(by_as.get((a, s), 0)) for a in top_auth]} for s in order]}
    n_by_a = dict(zip(auth["authority"], auth["n"]))
    t_auth = [{"name": a, "total": n(n_by_a[a]),
               "vals": [n(by_as.get((a, s), 0)) for s in order],
               "ever": n(ever_by_a[a])} for a in top_auth]

    # Authority type: current-status mix (100%) + ever-infested share
    types = df.groupby("atype").size().reset_index(name="n")
    types = types.sort_values(["n", "atype"], ascending=[False, True], kind="stable")
    tnames = list(types["atype"])
    by_ts = df.groupby(["atype", "status"]).size()
    ever_by_t = df.groupby("atype")["ever_inf"].mean()
    n_by_t = dict(zip(types["atype"], types["n"]))
    atype_chart = {"names": tnames,
                   "series": [{"name": s, "color": COLORS.get(s, OTHER_COLOR),
                               "data": [round(by_ts.get((t, s), 0) / n_by_t[t] * 100, 1) for t in tnames]}
                              for s in order],
                   "ever": [round(float(ever_by_t[t]) * 100, 1) for t in tnames]}
    t_atype = [{"name": t, "total": n(n_by_t[t]),
                "vals": [pct_bare(by_ts.get((t, s), 0) / n_by_t[t]) for s in order],
                "ever": pct_bare(float(ever_by_t[t]))} for t in tnames]

    # ── insights ──
    rules = [
        ("now", insight_now(df)),
        ("stale", insight_stale(df, last)),
        ("ever", insight_ever(df)),
        ("persist", insight_persist(df)),
        ("trend", insight_trend(yearly, last, partial)),
        ("authority", insight_authority(df)),
        ("gap", insight_gap(gaps)),
        ("atype", insight_atype(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── KPIs ──
    n_inf = int(status.get(INF, 0))
    n_clean = int(status.get(CLEAN, 0))
    n_stale = int(status.get(STALE, 0))
    recent = n_inf + n_clean
    inf_share = n_inf / recent if recent else 0
    stale_share = n_stale / total if total else 0
    ever = int(df["ever_inf"].sum())
    ever_share = ever / with_vis if with_vis else 0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand",
                  "label": "משתלות במעקב"},
        "infested": {"value": n_inf, "display": n(n_inf),
                     "tone": "ok" if n_inf == 0 else "danger" if inf_share >= 0.3 else "warn",
                     "label": f"משתלות נגועות כיום (מתוך {n(recent)} שנבדקו בשנה האחרונה)"},
        "stale": {"value": n_stale, "display": n(n_stale),
                  "tone": "warn" if stale_share >= 0.5 else "brand",
                  "label": f"משתלות שלא נבדקו בשנה האחרונה ({pct_bare(stale_share, 0)} מהמשתלות)"},
        "ever": {"value": round(ever_share, 4), "display": pct_bare(ever_share, 0), "tone": "info",
                 "label": f"מהמשתלות נמצאו נגועות לפחות פעם אחת ({n(ever)} משתלות)"},
    }

    period = f"{first_year}–{last.year}"
    last_he = f"{last.day} ב{MONTHS_HE[last.month - 1]} {last.year}"
    bad_note = ("" if not n_bad else " בדיקה אחת עם תאריך או תוצאה לא תקינים לא נכללה בניתוח."
                if n_bad == 1 else f" {n(n_bad)} בדיקות עם תאריך או תוצאה לא תקינים לא נכללו בניתוח.")
    gap_med = float(gaps.median()) if len(gaps) else 0.0
    oc_all_inf = int(oc.get("all_inf", 0))
    oc_cleared = int(oc.get("cleared", 0))
    oc_new = int(oc.get("new_inf", 0))
    top_n = int(auth["n"].iloc[0]) if len(auth) else 0
    leaders = list(auth.loc[auth["n"] == top_n, "authority"])
    if len(leaders) == 1:
        lead_txt = f"המובילה: {leaders[0]} ({n(top_n)} משתלות)."
    elif len(leaders) == 2:
        lead_txt = f"בראש: {leaders[0]} ו{leaders[1]}, {n(top_n)} משתלות כל אחת."
    else:
        lead_txt = f"{n(len(leaders))} רשויות חולקות את המקום הראשון עם {n(top_n)} משתלות כל אחת."
    big_outcome = max(OUTCOMES, key=lambda o: int(oc.get(o[0], 0)))[1]
    peak_y = max(yearly, key=lambda r: (r["total"], -r["y"]))
    partial_note = (f" הנתונים לשנת {last.year} חלקיים (עד {last_he})." if partial else "")
    labels = {
        "lede": (f"המשרד להגנת הסביבה עוקב אחר {n(total)} משתלות ברחבי הארץ ובודק בהן נוכחות של "
                 f"נמלת האש הקטנה, מין פולש שמתפשט בין היתר עם עציצים ושתילים. במאגר רשומות "
                 f"{n(len(visits))} בדיקות בשנים {period} (עד שלוש לכל משתלה), והבדיקה האחרונה "
                 f"נערכה ב-{last_he}.{bad_note}"),
        "map_note": (f"מיקום {n(total)} המשתלות. לחיצה על נקודה מציגה את שם המשתלה, הרשות "
                     f"והסטטוס העדכני; לחיצה על אשכול מקרבת את התצוגה."),
        "map_aria": f"מפה אינטראקטיבית של {n(total)} המשתלות במעקב. גרסה נגישה: טבלת הנתונים בתחתית העמוד.",
        "status_note": (f"הסטטוס שפרסם המשרד: תוצאת הבדיקה האחרונה למשתלות שנבדקו בשנה האחרונה, "
                        f"ו\"לא נבדק בשנה האחרונה\" לכל השאר — {n(n_stale)} משתלות."),
        "status_aria": (f"תרשים טבעת: סטטוס עדכני של {n(total)} משתלות — {n(n_inf)} נגועות, "
                        f"{n(n_clean)} ללא נגיעות ו-{n(n_stale)} שלא נבדקו בשנה האחרונה."),
        "status_caption": "סטטוס עדכני של המשתלות לפי המאגר.",
        "journey_note": (f"כל משתלה עוברת מבדיקה לבדיקה: הרוחב של כל זרם הוא מספר המשתלות. "
                         f"זרמים אפורים הם משתלות שטרם נבדקו שוב."),
        "journey_aria": (f"תרשים זרימה: תוצאות הבדיקה הראשונה, השנייה והשלישית של המשתלות ומעברים "
                         f"ביניהן; {n(oc_all_inf)} משתלות נמצאו נגועות בכל הבדיקות."),
        "journey_caption": "מעברים בין תוצאות בדיקות עוקבות (מספר משתלות).",
        "outcome_note": (f"סיכום ההיסטוריה של כל משתלה: {n(oc_all_inf)} נגועות בכל הבדיקות, "
                         f"{n(oc_cleared)} נמצאו נקיות בבדיקה האחרונה אחרי נגיעות קודמת, ו-{n(oc_new)} "
                         f"נמצאו נגועות בבדיקה האחרונה אחרי בדיקה נקייה."),
        "outcome_aria": (f"תרשים עמודות אופקי: {n(with_vis)} משתלות לפי מסלול תוצאות הבדיקות — "
                         f"הקבוצה הגדולה היא {big_outcome}."),
        "outcome_caption": "משתלות לפי מסלול תוצאות הבדיקות.",
        "yearly_note": (f"מספר הבדיקות בכל שנה לפי תוצאה, והקו — שיעור הבדיקות שבהן נמצאה נגיעות. "
                        f"השנה עם הכי הרבה בדיקות: {peak_y['y']} ({n(peak_y['total'])}).{partial_note}"),
        "yearly_aria": (f"תרשים עמודות מוערמות וקו: בדיקות לפי שנה ותוצאה בשנים {period}, "
                        f"ושיעור הבדיקות הנגועות."),
        "yearly_caption": "בדיקות לפי שנה ותוצאה.",
        "cohort_note": (f"באיזו שנה נכנסה כל משתלה למעקב, ומה נמצא בבדיקה הראשונה שלה. "
                        f"השנה שבה נכנסו הכי הרבה משתלות: {year_labels[busiest]} "
                        f"({n(cohort_chart['inf'][busiest] + cohort_chart['clean'][busiest])}).{partial_note}"),
        "cohort_aria": f"תרשים עמודות מוערמות: משתלות לפי שנת הבדיקה הראשונה ותוצאתה, {period}.",
        "cohort_caption": "משתלות לפי שנת הבדיקה הראשונה ותוצאתה.",
        "recency_note": (f"השנה של הבדיקה האחרונה הרשומה לכל משתלה ותוצאתה — כמה עדכני המידע. "
                         f"ב-{last.year} נבדקו לאחרונה {n(last_year_n)} משתלות.{partial_note}"),
        "recency_aria": f"תרשים עמודות מוערמות: משתלות לפי שנת הבדיקה האחרונה ותוצאתה, {period}.",
        "recency_caption": "משתלות לפי שנת הבדיקה האחרונה ותוצאתה.",
        "gap_note": (f"הזמן שעבר בין בדיקה לבדיקה הבאה באותה משתלה, על פני {n(len(gaps))} זוגות "
                     f"בדיקות עוקבות. החציון: כ-{gap_med:.0f} חודשים."),
        "gap_aria": f"תרשים עמודות: התפלגות הזמן בין בדיקות עוקבות; חציון של כ-{gap_med:.0f} חודשים.",
        "gap_caption": "התפלגות הזמן בין בדיקות עוקבות באותה משתלה.",
        "auth_note": (f"{len(top_auth)} הרשויות המקומיות עם הכי הרבה משתלות במעקב, לפי הסטטוס "
                      f"העדכני. {lead_txt}"),
        "auth_aria": (f"תרשים עמודות אופקי מוערם: {len(top_auth)} הרשויות עם הכי הרבה משתלות "
                      f"לפי סטטוס עדכני. {lead_txt}"),
        "auth_caption": f"{len(top_auth)} הרשויות המקומיות עם הכי הרבה משתלות.",
        "atype_note": ("התפלגות הסטטוס העדכני לפי סוג הרשות (באחוזים), והסימון — שיעור המשתלות "
                       "שנמצאה בהן נגיעות אי-פעם. סוג הרשות נגזר משם הרשות במאגר."),
        "atype_aria": f"תרשים עמודות אופקי מוערם: סטטוס עדכני לפי סוג הרשות, {len(tnames)} סוגים.",
        "atype_caption": "סטטוס עדכני ושיעור נגיעות אי-פעם לפי סוג הרשות.",
    }

    return {
        "agent_data": {
            "summary_he": (f"ניטור נמלת האש הקטנה ב-{n(total)} משתלות: {n(len(visits))} בדיקות "
                           f"בשנים {period}. {n(n_inf)} משתלות נגועות כיום, ו-{pct_bare(ever_share, 0)} "
                           f"מהמשתלות נמצאו נגועות לפחות פעם אחת."),
            "dataset_kind": "map",
            "suggested_tags": ["נמלת האש הקטנה", "משתלות", "מזיקים", "מינים פולשים", "הגנת הסביבה"],
            "related_ids": [
                "4faf5604-c98f-45eb-bb9e-e0c4fe1c9c69",
                "7a6cbf55-8178-4d40-8613-a38909c7e96f",
                "a37765ea-d407-42e8-b757-9b70a8cf574f",
                "04931a88-336c-4d95-8a13-9dc631c3e2d1",
            ],
            "temporal_coverage": f"{first_year}/{last.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "status": status_chart,
            "journey": journey,
            "outcome": outcome_chart,
            "yearly": yearly_chart,
            "cohort": cohort_chart,
            "recency": recency_chart,
            "gap": gap_chart,
            "auth": auth_chart,
            "atype": atype_chart,
        },
        "tables": {
            "status": t_status, "journey": t_journey, "outcome": t_outcome,
            "yearly": t_yearly, "cohort": t_cohort, "recency": t_recency,
            "gap": t_gap, "auth": t_auth, "atype": t_atype, "status_cols": order,
        },
        "insights": insights,
        "labels": labels,
    }
