"""כלי רכב המחויבים בהתקנת נקודות עיגון לאבטחת מטענים.

One row per commercial vehicle or trailer above 3.5 t whose licence renewal
depends on installed cargo-anchoring points. Three columns only: the licence
plate, the EU category (N2/N3 trucks, O3/O4 trailers) and the gross vehicle
weight in kg. There is no date, so the page is a structural portrait of the
list: category mix, weight distribution, the registered-weight "spikes"
(round tons, a few kg under a threshold, US pound ratings), and the plate
FORMAT (digit count) as a coarse proxy for registration series.

- The plate itself is never shown — only how many digits it has.
- A gross weight of 99,999 kg (or anything non-positive / unparsable) is a
  placeholder for "not recorded": those rows count in the category totals
  and are disclosed, but stay out of every weight view.
- No hardcoded category list: known EU codes get a Hebrew description and an
  order; unknown codes flow through after them.
"""
import math

import pandas as pd

PLACEHOLDER_MIN = 99999       # 99,999 kg is the register's "unknown weight"
HEAVY_KG = 12000              # the N2/N3 line; "heavy" = above it
TOP_WEIGHTS = 15
FINE_LO, FINE_HI, FINE_STEP = 3500, 16000, 100   # spike histogram range (kg)
NEAR_BELOW = 20               # "just under a round ton" = 1–20 kg below a multiple of 1,000
LB_KG = 0.45359237
LB_LO, LB_HI = 4530, 4537     # ≈ 10,000 lb (4,536 kg) and its rounding variants
LEADER_SHARE = 0.4
ROUND_SHARE = 0.03
NEAR_SHARE = 0.05
LB_SHARE = 0.02
WEIGHT_RATIO = 1.5            # weight share ≥ 1.5× count share is worth a sentence
PLATE_GAP = 0.15              # 8-digit share differing ≥15 points between two categories
PLATE_MIN_DIGITS = 5          # 3–5 digit plates (a few thousand, mostly older trailers) share one bucket

CAT_ORDER = ["N2", "N3", "O3", "O4"]
CAT_DESC = {
    "N1": "רכב משא עד 3.5 טון",
    "N2": "משאית 3.5 עד 12 טון",
    "N3": "משאית מעל 12 טון",
    "O2": "גרור עד 3.5 טון",
    "O3": "גרור 3.5 עד 10 טון",
    "O4": "גרור מעל 10 טון",
}
MOTOR = "N"
TRAILER = "O"
BANDS = [(3501, 5000, "3.5 עד 5"), (5001, 7500, "5 עד 7.5"), (7501, 10000, "7.5 עד 10"),
         (10001, 12000, "10 עד 12"), (12001, 15000, "12 עד 15"), (15001, 20000, "15 עד 20"),
         (20001, 26000, "20 עד 26"), (26001, 32000, "26 עד 32"), (32001, 40000, "32 עד 40"),
         (40001, 50000, "40 עד 50"), (50001, 60000, "50 עד 60"), (60001, 10 ** 9, "מעל 60")]
UNKNOWN = "לא צוין"


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _t(kg):
    return f"{kg / 1000:,.1f}".rstrip("0").rstrip(".")


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _cat_label(c):
    d = CAT_DESC.get(c)
    return f"{c} — {d}" if d else c


def _digits_label(d):
    return f"עד {d} ספרות" if d == PLATE_MIN_DIGITS else f"{d} ספרות"


def _band(w):
    for lo, hi, label in BANDS:
        if lo <= w <= hi:
            return label
    return None


def _prepare(df):
    cat = df["sug_rechev_EU_cd"].str.strip().str.upper().replace("", UNKNOWN)
    w = pd.to_numeric(df["mishkal_kolel"].str.replace(",", "").str.strip(), errors="coerce")
    w = w.where((w > 0) & (w < PLACEHOLDER_MIN))
    digits = df["mispar_rechev"].str.strip().str.replace(r"\D", "", regex=True).str.len()
    digits = digits.where(digits == 0, digits.clip(lower=PLATE_MIN_DIGITS))
    return pd.DataFrame({"cat": cat, "w": w, "digits": digits})


def _cats(df):
    present = set(df["cat"].unique())
    return [c for c in CAT_ORDER if c in present] + sorted(present - set(CAT_ORDER))


# ── insight rules ────────────────────────────────────────────────────────────

def insight_leader(cat_counts, n):
    if len(cat_counts) < 2:
        return None
    (c1, n1), (c2, n2) = list(cat_counts.items())[:2]
    if n1 / n < LEADER_SHARE:
        return None
    lead = "רוב הרשימה היא" if n1 / n > 0.5 else "הקטגוריה הגדולה ברשימה היא"
    return (f"{lead} קטגוריה {_cat_label(c1)}: {_int(n1)} כלים ({_pct(n1 / n)}), "
            f"פי {n1 / n2:.1f} מהקטגוריה הבאה, {c2} ({_int(n2)}).")


def insight_heavy(wv):
    if len(wv) < 100:
        return None
    heavy = wv[wv["w"] > HEAVY_KG]
    if len(heavy) == 0:
        return None
    vc = _ranked(heavy["cat"])
    top2 = list(vc.items())[:2]
    parts = " ו-".join(f"{c} ({_int(v)})" for c, v in top2)
    word = "בעיקר" if sum(v for _, v in top2) / len(heavy) >= 0.5 else "המובילות"
    return (f"{_pct(len(heavy) / len(wv))} מהכלים שמשקלם רשום ({_int(len(heavy))}) שוקלים מעל "
            f"{_t(HEAVY_KG)} טון — {word} בקטגוריות {parts}.")


def insight_round(wv):
    vc = _ranked(wv["w"].astype(int))
    if len(vc) == 0:
        return None
    top_w, top_n = int(vc.index[0]), int(vc.iloc[0])
    if top_n / len(wv) < ROUND_SHARE:
        return None
    cats = _ranked(wv.loc[wv["w"] == top_w, "cat"])
    whole = (wv["w"] % 1000 == 0).mean()
    return (f"המשקל הכולל הנפוץ ביותר הוא {_int(top_w)} ק״ג — {_int(top_n)} כלים "
            f"({_pct(top_n / len(wv))}), {_pct(cats.iloc[0] / top_n, 0)} מהם בקטגוריה {cats.index[0]}; "
            f"{_pct(whole)} מכלל הכלים רשומים בטון עגול.")


def insight_near(wv):
    r = wv["w"] % 1000
    near = wv[(r >= 1000 - NEAR_BELOW) & (wv["w"] >= 5000)]
    if len(near) / max(len(wv), 1) < NEAR_SHARE:
        return None
    vc = _ranked(near["w"].astype(int))
    parts = ", ".join(f"{_int(k)} ק״ג ({_int(v)})" for k, v in list(vc.items())[:3])
    return (f"{_int(len(near))} כלים ({_pct(len(near) / len(wv))}) רשומים במשקל של עד "
            f"{NEAR_BELOW} ק״ג מתחת לטון עגול — הנפוצים: {parts}.")


def insight_pounds(wv):
    lb = wv[(wv["w"] >= LB_LO) & (wv["w"] <= LB_HI)]
    if len(lb) / max(len(wv), 1) < LB_SHARE:
        return None
    vc = _ranked(lb["cat"])
    lb_round = int(round(float(lb["w"].median()) / LB_KG, -2))
    who = ("כולם" if int(vc.iloc[0]) == len(lb) else f"{_pct(vc.iloc[0] / len(lb), 0)} מהם")
    return (f"{_int(len(lb))} כלים ({_pct(len(lb) / len(wv))}) רשומים במשקל "
            f"{_int(lb['w'].min())} עד {_int(lb['w'].max())} ק״ג, כלומר כ-{_int(lb_round)} פאונד — "
            f"ככל הנראה דירוג שנקבע ביחידות אמריקאיות ותורגם לקילוגרמים; {who} בקטגוריה {vc.index[0]}.")


def insight_weight_share(rows):
    best = None
    for r in rows:
        if r["n_share"] > 0 and r["w_share"] / r["n_share"] >= WEIGHT_RATIO:
            if best is None or r["w_share"] / r["n_share"] > best["w_share"] / best["n_share"]:
                best = r
    if best is None:
        return None
    return (f"כלי קטגוריה {best['cat']} הם {_pct(best['n_share'])} מהכלים אך {_pct(best['w_share'])} "
            f"מסך המשקל הכולל הרשום — משקל חציוני של {_t(best['med'])} טון לכלי.")


def insight_plate(plate_share, counts):
    big = [c for c in plate_share if counts.get(c, 0) >= 500]
    if len(big) < 2:
        return None
    hi = max(big, key=lambda c: (plate_share[c], c))
    lo = min(big, key=lambda c: (plate_share[c], c))
    if plate_share[hi] - plate_share[lo] < PLATE_GAP:
        return None
    return (f"ל-{_pct(plate_share[hi])} מכלי קטגוריה {hi} מספר רישוי בן שמונה ספרות (הסדרה החדשה), "
            f"לעומת {_pct(plate_share[lo])} בלבד בקטגוריה {lo}.")


# ── compute ──────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])
    n = len(df)
    cats = _cats(df)
    cat_counts = _ranked(df["cat"])
    counts = {c: int(cat_counts.get(c, 0)) for c in cats}
    wv = df.dropna(subset=["w"]).copy()
    wv["w"] = wv["w"].astype(int)
    n_w = len(wv)
    n_nw = n - n_w
    n_motor = int(sum(v for c, v in counts.items() if c.startswith(MOTOR)))
    n_trailer = int(sum(v for c, v in counts.items() if c.startswith(TRAILER)))

    # ── Categories ────────────────────────────────────────────────────────
    cat_chart = {"names": [_cat_label(c) for c in cats], "values": [counts[c] for c in cats]}
    t_cats = [{"name": _cat_label(c), "count": _int(counts[c]), "share": f"{counts[c] / n * 100:.1f}"}
              for c in cats]

    # ── Count share vs gross-weight share ─────────────────────────────────
    total_w = math.fsum(float(v) for v in wv["w"].sort_values())
    grp = {c: g["w"] for c, g in wv.groupby("cat")}
    share_rows = []
    for c in cats:
        s = grp.get(c, pd.Series(dtype=int))
        sw = math.fsum(float(v) for v in s.sort_values())
        share_rows.append({"cat": c, "n_share": len(s) / n_w if n_w else 0.0,
                           "w_share": sw / total_w if total_w else 0.0,
                           "med": float(s.median()) if len(s) else 0.0})
    share_chart = {"names": cats,
                   "count": [round(r["n_share"] * 100, 1) for r in share_rows],
                   "weight": [round(r["w_share"] * 100, 1) for r in share_rows]}
    t_share = [{"name": _cat_label(r["cat"]), "cols": [f"{r['n_share'] * 100:.1f}", f"{r['w_share'] * 100:.1f}"]}
               for r in share_rows]

    # ── Weight bands × category ───────────────────────────────────────────
    wv["band"] = wv["w"].map(_band)
    bands = [b[2] for b in BANDS]
    bt = wv.groupby(["band", "cat"]).size().unstack(fill_value=0).reindex(index=bands, columns=cats, fill_value=0)
    bands_chart = {"x": bands, "series": [{"name": c, "data": [int(v) for v in bt[c]]} for c in cats]}
    t_bands = [{"name": b, "total": _int(bt.loc[b].sum()), "cols": [_int(bt.loc[b, c]) for c in cats]}
               for b in bands]
    band_tot = bt.sum(axis=1)
    top_band = band_tot.sort_index().sort_values(ascending=False, kind="stable").index[0] if n_w else bands[0]

    # ── Fine histogram (spikes) ───────────────────────────────────────────
    fine = wv[(wv["w"] > FINE_LO) & (wv["w"] <= FINE_HI)]
    edges = list(range(FINE_LO, FINE_HI, FINE_STEP))
    fbin = ((fine["w"] - FINE_LO - 1) // FINE_STEP).astype(int)
    ft = fine.groupby([fbin, fine["cat"]]).size().unstack(fill_value=0)
    ft = ft.reindex(index=range(len(edges)), columns=cats, fill_value=0)
    keep = [c for c in cats if int(ft[c].sum()) > 0]
    fine_chart = {"x": [_int(e + 1) for e in edges],
                  "ranges": [f"{_int(e + 1)} עד {_int(e + FINE_STEP)} ק״ג" for e in edges],
                  "series": [{"name": c, "data": [int(v) for v in ft[c]]} for c in keep]}
    fine_tot = ft.sum(axis=1)
    peak_i = int(fine_tot.sort_index().sort_values(ascending=False, kind="stable").index[0]) if len(fine) else 0
    peak_lbl = fine_chart["ranges"][peak_i]
    peak_n = int(fine_tot.iloc[peak_i]) if len(fine) else 0

    # ── Most common exact weights ─────────────────────────────────────────
    wc = _ranked(wv["w"])
    top = wc.head(TOP_WEIGHTS)
    cat_by_w = wv[wv["w"].isin(top.index)].groupby("w")["cat"].agg(lambda s: _ranked(s).index[0])
    common_chart = {"names": [f"{_int(k)} ק״ג" for k in top.index], "values": [int(v) for v in top]}
    t_common = [{"name": f"{_int(k)}", "cat": cat_by_w[k], "count": _int(v),
                 "share": f"{v / n_w * 100:.1f}"} for k, v in top.items()]
    top_cover = int(top.sum()) / n_w if n_w else 0.0
    n_distinct = int(wv["w"].nunique())

    # ── Boxplot per category ──────────────────────────────────────────────
    box_cats = [c for c in cats if c in grp and len(grp[c])]
    box, t_box = [], []
    for c in box_cats:
        s = grp[c]
        qs = [float(s.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
        box.append([round(v) for v in qs])
        t_box.append({"name": _cat_label(c), "min": _int(s.min()), "q1": _int(qs[1]), "med": _int(qs[2]),
                      "q3": _int(qs[3]), "max": _int(s.max())})
    box_chart = {"names": box_cats, "data": box}

    # ── Plate format (digit count only) ───────────────────────────────────
    dg = df[df["digits"] > 0]
    dlev = sorted(int(v) for v in dg["digits"].unique())
    dt = dg.groupby(["cat", "digits"]).size().unstack(fill_value=0).reindex(index=cats, columns=dlev, fill_value=0)
    plate_series = []
    for d_ in dlev:
        plate_series.append({"name": _digits_label(d_),
                             "data": [round(dt.loc[c, d_] / dt.loc[c].sum() * 100, 1) if dt.loc[c].sum() else 0.0
                                      for c in cats]})
    plate_chart = {"names": cats, "series": plate_series}
    t_plate = [{"name": _cat_label(c), "cols": [_int(dt.loc[c, d_]) for d_ in dlev]} for c in cats]
    plate_share = {c: (dt.loc[c, 8] / dt.loc[c].sum() if 8 in dlev and dt.loc[c].sum() else 0.0) for c in cats}
    eight_all = (dg["digits"] == 8).mean() if len(dg) else 0.0

    # ── KPIs ──────────────────────────────────────────────────────────────
    med_w = float(wv["w"].median()) if n_w else 0.0
    heavy_share = (wv["w"] > HEAVY_KG).mean() if n_w else 0.0
    trailer_share = n_trailer / n if n else 0.0

    rules = [
        ("leader", insight_leader(cat_counts, n)),
        ("heavy", insight_heavy(wv)),
        ("weight_share", insight_weight_share(share_rows)),
        ("round", insight_round(wv)),
        ("near", insight_near(wv)),
        ("pounds", insight_pounds(wv)),
        ("plate", insight_plate(plate_share, counts)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    nw_note = (f" {_int(n_nw)} כלים שמשקלם רשום כ-{_int(PLACEHOLDER_MIN)} ק״ג (ערך שמסמן משקל לא ידוע) "
               f"אינם בתרשים." if n_nw else "")
    w_min, w_max = (int(wv["w"].min()), int(wv["w"].max())) if n_w else (0, 0)

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} כלי רכב מסחריים וגרורים מעל 3.5 טון החייבים בהתקנת נקודות עיגון "
                           f"לאבטחת מטענים: {_int(n_motor)} משאיות ו-{_int(n_trailer)} גרורים. "
                           f"המשקל הכולל החציוני {_int(med_w)} ק״ג, ו-{_pct(heavy_share)} מהכלים שוקלים "
                           f"מעל {_t(HEAVY_KG)} טון."),
            "dataset_kind": "registry",
            "related_ids": [
                "0219b34f-43c7-435b-bdfe-e65e944cde50",
                "35c791ca-8db2-4657-8c6f-eb092147a6bb",
                "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                "392abd0a-64f6-4c18-9d56-0111001411e6",
                "0f16b39a-6016-408d-805d-31f40d5a0990",
            ],
            "suggested_tags": ["רכב מסחרי", "משאיות", "גרורים", "עיגון מטען", "בטיחות בדרכים", "רישוי רכב"],
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "median": {"value": round(med_w), "display": _int(med_w), "tone": "brand"},
            "heavy": {"value": round(heavy_share, 4), "display": _pct(heavy_share),
                      "tone": "info" if heavy_share >= 0.25 else "brand"},
            "trailers": {"value": round(trailer_share, 4), "display": _pct(trailer_share), "tone": "brand"},
        },
        "charts": {
            "cats": cat_chart,
            "share": share_chart,
            "bands": bands_chart,
            "fine": fine_chart,
            "common": common_chart,
            "box": box_chart,
            "plate": plate_chart,
        },
        "tables": {
            "cats": t_cats,
            "share": t_share,
            "cat_cols": cats,
            "bands": t_bands,
            "common": t_common,
            "box": t_box,
            "plate_cols": [_digits_label(d_) for d_ in dlev],
            "plate": t_plate,
        },
        "insights": insights,
        "labels": {
            "lede": (f"הרשימה מונה {_int(n)} כלי רכב מסחריים וגרורים שמשקלם הכולל מעל 3.5 טון, "
                     f"שחידוש רישיונם מותנה בהתקנת נקודות עיגון לאבטחת מטענים: {_int(n_motor)} משאיות "
                     f"(קטגוריות N) ו-{_int(n_trailer)} גרורים ונתמכים (קטגוריות O). לכל כלי רשומים רק "
                     f"קטגוריית האיחוד האירופי והמשקל הכולל המותר, ולכן העמוד מתאר את הרכב הרשימה — "
                     f"לפי קטגוריה ומשקל. מספרי הרישוי עצמם אינם מוצגים."),
            "total_kpi": "כלי רכב ברשימה",
            "median_kpi": "משקל כולל חציוני (ק״ג)",
            "heavy_kpi": f"שיעור הכלים מעל {_t(HEAVY_KG)} טון",
            "trailers_kpi": "שיעור הגרורים והנתמכים",
            "cats_note": (f"קטגוריית האיחוד האירופי קובעת את סוג הכלי ואת טווח המשקל: N2 ו-N3 הן משאיות, "
                          f"O3 ו-O4 גרורים ונתמכים. הקטגוריה הגדולה — {_cat_label(cats[0]) if cats else ''}."
                          if cats else ""),
            "cats_aria": "תרשים עמודות: כלי רכב לפי קטגוריית האיחוד האירופי.",
            "share_note": ("כל קטגוריה פעמיים: חלקה ממספר הכלים שמשקלם רשום, וחלקה מסך המשקל הכולל הרשום "
                           "של כל הכלים."),
            "share_aria": "תרשים עמודות: חלק כל קטגוריה ממספר הכלים ומסך המשקל הכולל.",
            "share_caption": "חלק מהכלים ומסך המשקל הכולל, באחוזים.",
            "bands_note": (f"כלים לפי טווח משקל כולל בטונות, מחולקים לפי קטגוריה. הטווח הנפוץ — {top_band} טון "
                           f"({_int(band_tot.get(top_band, 0))} כלים).{nw_note}"),
            "bands_aria": "תרשים עמודות מוערם: כלים לפי טווח משקל כולל וקטגוריה.",
            "bands_caption": "כלים לפי טווח משקל (טון) וקטגוריה.",
            "fine_note": (f"התפלגות המשקל הכולל בדרגות של {FINE_STEP} ק״ג, מ-{_t(FINE_LO)} עד {_t(FINE_HI)} טון "
                          f"({_int(len(fine))} כלים). המשקל אינו מתפזר בצורה חלקה: היצרנים רושמים ערכים "
                          f"עגולים או ערכים שמתחת לסף, ולכן התרשים בנוי מקפיצות. הדרגה הגבוהה — "
                          f"{peak_lbl} ({_int(peak_n)} כלים)."),
            "fine_aria": f"תרשים עמודות: כלים לפי משקל כולל בדרגות של {FINE_STEP} ק״ג.",
            "common_note": (f"{_int(n_distinct)} ערכי משקל שונים רשומים, אבל {TOP_WEIGHTS} הנפוצים מכסים "
                            f"{_pct(top_cover)} מהכלים."),
            "common_aria": f"תרשים עמודות: {TOP_WEIGHTS} ערכי המשקל הכולל הנפוצים.",
            "box_note": ("התיבה — הרבעון התחתון עד העליון, הקו — החציון, השפמים — אחוזון 5 עד 95. "
                         f"המשקל הרשום נע בין {_int(w_min)} ל-{_int(w_max)} ק״ג."),
            "box_aria": "תרשים תיבה: משקל כולל בקילוגרם לפי קטגוריה.",
            "plate_note": (f"מספר הספרות במספר הרישוי בלבד — המספרים עצמם אינם מוצגים. מספרים בני שמונה "
                           f"ספרות הם הסדרה החדשה ביותר, ולכן חלקם בכל קטגוריה מרמז בקירוב כמה מהכלים "
                           f"נרשמו בשנים האחרונות; לגרורים סדרת מספור משלהם. בכלל הרשימה — "
                           f"{_pct(eight_all)} בני שמונה ספרות."),
            "plate_aria": "תרשים עמודות מוערם: חלוקת מספרי הרישוי לפי מספר הספרות, בכל קטגוריה.",
            "plate_caption": "כלים לפי מספר הספרות במספר הרישוי ולפי קטגוריה.",
        },
    }
