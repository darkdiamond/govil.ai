"""סטטיסטיקת הנפקת רישיונות לזרים (Population and Immigration Authority).

Two resources:
- "monthly" (מתעדכן): one row per year × month × visa type × sub-type × work
  permit sector × sex × age group × passport country, with counts of new
  licences, extensions and corrections. Starts 2019, appended monthly.
- "historic": the same breakdown per year only, 2013 onward, frozen. Counts
  under six are published as the text "קטן מ6"; they are counted as zero
  and the number of such cells is disclosed. Its years that the monthly file
  also covers (a partial 2019) are dropped, so each year comes from exactly
  one file.

Visitor licences (ב/2) are the bulk of the data (every tourist gets one at the
border), so most views split tourism from everything else, and the non-tourism
mix, work permits (ב/1, by sector and country) and the ס' 2(א)(5) status get
their own charts.

Text fields store parentheses mirrored (")צילון(") - they are swapped back.
"Latest" is the latest month in the data; a final year with fewer than twelve
months is partial and compared year-to-date with the same months a year
earlier, never extrapolated.
"""
import pandas as pd

MINUS = "−"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

TOUR = "tour"
GROUPS = [  # key, label, visa codes (after paren fix)
    (TOUR, "ביקור ותיירות (ב/2)", {"ב/2", "ב/2 קבוצתי"}),
    ("work", "עבודה (ב/1)", {"ב/1", "ב/1 כללי", "ב/1 חוץ"}),
    ("study", "לימודים (א/2)", {"א/2", "א/2 כללי"}),
    ("s25", "רישיון לפי ס' 2(א)(5)", {"ס' 2(א)5", "ס' 2(א)(5)"}),
    ("family", "בני משפחה (א/4)", {"א/4"}),
    ("diplo", "דיפלומטים ושירות חוץ", {"דיפלומט", "דיפלומט חוץ", "שירות חוץ"}),
    ("other", "אחר", None),
]
GROUP_LABEL = {k: lbl for k, lbl, _ in GROUPS}
NONTOUR_KEYS = [k for k, _, _ in GROUPS if k != TOUR]

AGE_MAP = {"קטן מ25": "מתחת ל-25", "<25": "מתחת ל-25", "25-34": "25-34",
           "35-44": "35-44", "45-54": "45-54", "גדול מ55": "55+", "55+": "55+"}
AGE_ORDER = ["מתחת ל-25", "25-34", "35-44", "45-54", "55+"]

TOP_SECTORS = 7
TOP_COUNTRIES = 10
STABLE_PCT = 0.05          # YTD / yearly change within ±5% reads as "יציב"
SHARP_DROP = 0.15          # YTD fall beyond this turns the KPI red (warn above it)
GROWTH_RATIO = 1.3         # work-licence change vs base year counts as growth/decline
MIN_WOMEN_N = 1000         # licences a group needs for the women-share insight
MIN_SEASON_YEARS = 2       # full years needed for the seasonality insight


def _fix(s):
    """Swap mirrored parentheses: 'סרי לנקה )צילון(' -> 'סרי לנקה (צילון)'."""
    i, j = s.find(")"), s.find("(")
    if i != -1 and (j == -1 or i < j):
        return s.translate(str.maketrans("()", ")("))
    return s


def _group_of(visa):
    for k, _, codes in GROUPS:
        if codes is not None and visa in codes:
            return k
    return "other"


def _fmt(v):
    v = int(round(v))
    return f"{MINUS}{abs(v):,}" if v < 0 else f"{v:,}"


def _pct(frac, digits=1, signed=False):
    s = f"{abs(frac) * 100:.{digits}f}%"
    if signed:
        return (MINUS if frac < 0 else "+") + s
    return s


def _num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce")


def _prep_monthly(df):
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    out = pd.DataFrame({
        "year": _num(df["שנת_רישום"]),
        "month": _num(df["חודש_רישום"]),
        "visa": df["אשרה"].map(_fix),
        "permit": df["היתר"].map(_fix),
        "sex": df["מין"],
        "age": df["קבוצת_גיל"].map(lambda a: AGE_MAP.get(a, "")),
        "country": df["ארץ_דרכון"].map(_fix),
        "new": _num(df["חדשים"]),
        "ext": _num(df["הארכות"]),
        "fix": _num(df["תיקונים"]),
    })
    out = out[out["year"].notna() & out["month"].between(1, 12)].copy()
    out["year"] = out["year"].astype(int)
    out["month"] = out["month"].astype(int)
    for c in ("new", "ext", "fix"):
        out[c] = out[c].fillna(0)
    out["group"] = out["visa"].map(_group_of)
    return out


def _prep_historic(df):
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    out = pd.DataFrame({
        "year": _num(df["שנה"]),
        "visa": df["אשרה"].map(_fix),
    })
    suppressed = 0
    for src, dst in (("חדשים", "new"), ("הארכות", "ext"), ("תיקונים", "fix")):
        v = _num(df[src])
        suppressed += int(((v.isna()) & (df[src] != "")).sum()) if src == "חדשים" else 0
        out[dst] = v.fillna(0)
    out = out[out["year"].notna()].copy()
    out["year"] = out["year"].astype(int)
    out["group"] = out["visa"].map(_group_of)
    return out, suppressed


def compute(frames):
    m = _prep_monthly(frames["monthly"])
    h, suppressed = _prep_historic(frames["historic"])

    m_years = sorted(m["year"].unique().tolist())
    first_m = m_years[0]
    last_year = m_years[-1]
    h = h[h["year"] < first_m]
    h_years = sorted(h["year"].unique().tolist())
    all_years = h_years + m_years

    months_per_year = m.groupby("year")["month"].nunique()
    last_month = int(m.loc[m["year"] == last_year, "month"].max())
    partial = int(months_per_year.get(last_year, 0)) < 12
    full_years = [y for y in m_years if int(months_per_year.get(y, 0)) == 12]
    ref = full_years[-1] if full_years else last_year
    base = first_m  # first monthly year
    hist_full_years = h_years + full_years

    # ── yearly totals per group (both files) ────────────────────────────
    yg = pd.concat([
        h.groupby(["year", "group"])[["new", "ext", "fix"]].sum(),
        m.groupby(["year", "group"])[["new", "ext", "fix"]].sum(),
    ]).groupby(level=[0, 1]).sum()

    def ysum(year, col="new", groups=None):
        if year not in all_years:
            return 0.0
        sub = yg.xs(year, level=0)
        if groups is not None:
            sub = sub[sub.index.isin(groups)]
        return float(sub[col].sum())

    def ylabel(y):
        return f"{y}*" if (partial and y == last_year) else str(y)

    x_years = [ylabel(y) for y in all_years]
    tour_y = [int(ysum(y, groups=[TOUR])) for y in all_years]
    non_y = [int(ysum(y, groups=NONTOUR_KEYS)) for y in all_years]
    tot_y = [a + b for a, b in zip(tour_y, non_y)]

    # ── monthly series (monthly file) ───────────────────────────────────
    mm = m.assign(t=m["group"].eq(TOUR)).groupby(["year", "month", "t"])["new"].sum()
    ym_pairs = sorted({(int(y), int(mo)) for y, mo, _ in mm.index})
    monthly = {"x": [], "tour": [], "other": []}
    for y, mo in ym_pairs:
        monthly["x"].append(f"{y}-{mo:02d}")
        monthly["tour"].append(int(mm.get((y, mo, True), 0)))
        monthly["other"].append(int(mm.get((y, mo, False), 0)))

    # ── seasonality heatmap: tourism, month × year ──────────────────────
    heat_cells = []
    for yi, y in enumerate(m_years):
        for mo in range(1, 13):
            if (y, mo) in set(ym_pairs):
                heat_cells.append([mo - 1, yi, int(mm.get((y, mo, True), 0))])
    heat = {"months": MONTHS_HE, "years": [str(y) for y in m_years], "cells": heat_cells,
            "max": max([c[2] for c in heat_cells] + [1])}

    # ── non-tourism mix per year ────────────────────────────────────────
    mix = {"x": x_years, "series": []}
    for k in NONTOUR_KEYS:
        mix["series"].append({"name": GROUP_LABEL[k],
                              "data": [int(ysum(y, groups=[k])) for y in all_years]})
    mix_rows = [{"year": x_years[i], "vals": [s["data"][i] for s in mix["series"]]}
                for i in range(len(all_years))]

    # ── work licences by sector (monthly years) ─────────────────────────
    w = m[m["group"] == "work"].copy()
    w["permit"] = w["permit"].where(w["permit"] != "", "לא צוין ענף")
    sec_tot = w[w["year"] == ref].groupby("permit")["new"].sum()
    sec_tot = sec_tot[sec_tot > 0].reset_index().sort_values(["new", "permit"], ascending=[False, True])
    top_secs = [s for s in sec_tot["permit"].tolist() if s != "לא צוין ענף"][:TOP_SECTORS]
    w["sec"] = w["permit"].where(w["permit"].isin(top_secs), "אחר")
    ws = w.groupby(["year", "sec"])["new"].sum()
    sec_names = top_secs + (["אחר"] if (w["sec"] == "אחר").any() else [])
    sectors = {"x": [ylabel(y) for y in m_years], "series": [
        {"name": s, "data": [int(ws.get((y, s), 0)) for y in m_years]} for s in sec_names]}
    sector_rows = [{"year": sectors["x"][i], "vals": [s["data"][i] for s in sectors["series"]]}
                   for i in range(len(m_years))]

    # ── top countries: tourism and work, ref year vs base year ─────────
    def countries(group):
        g = m[m["group"] == group]
        cur = g[g["year"] == ref].groupby("country")["new"].sum()
        old = g[g["year"] == base].groupby("country")["new"].sum()
        cur = cur[(cur > 0) & (cur.index != "")].reset_index().sort_values(
            ["new", "country"], ascending=[False, True]).head(TOP_COUNTRIES)
        names = cur["country"].tolist()
        total = float(g[g["year"] == ref]["new"].sum())
        return {"names": names, "cur": [int(v) for v in cur["new"]],
                "old": [int(old.get(n, 0)) for n in names],
                "share": [float(v) / total if total else 0.0 for v in cur["new"]],
                "total": total}

    tour_c = countries(TOUR)
    work_c = countries("work")

    # ── ס' 2(א)(5): new + extensions per year ───────────────────────────
    s25 = {"x": x_years, "new": [int(ysum(y, groups=["s25"])) for y in all_years],
           "ext": [int(ysum(y, "ext", groups=["s25"])) for y in all_years]}
    s25_c = m[(m["group"] == "s25") & (m["year"] == ref)].groupby("country")["new"].sum()
    s25_c = s25_c[s25_c > 0].reset_index().sort_values(["new", "country"], ascending=[False, True])
    s25_top = s25_c.head(3)["country"].tolist()

    # ── age × sex pyramid, ref year ─────────────────────────────────────
    r = m[m["year"] == ref]
    known = r[r["sex"].isin(["זכר", "נקבה"]) & r["age"].isin(AGE_ORDER)]
    pyr = known.groupby(["age", "sex"])["new"].sum()
    pyramid = {"ages": AGE_ORDER,
               "men": [int(pyr.get((a, "זכר"), 0)) for a in AGE_ORDER],
               "women": [int(pyr.get((a, "נקבה"), 0)) for a in AGE_ORDER]}
    unknown_pyr = int(r["new"].sum() - known["new"].sum())

    # ── women share by group, ref year ──────────────────────────────────
    rs = r[r["sex"].isin(["זכר", "נקבה"])]
    ws_g = rs.groupby(["group", "sex"])["new"].sum()
    women = {"names": [], "share": [], "n": []}
    rows_w = []
    for k, lbl, _ in GROUPS:
        f = float(ws_g.get((k, "נקבה"), 0))
        t = f + float(ws_g.get((k, "זכר"), 0))
        if t > 0:
            rows_w.append((f / t, lbl, int(t)))
    rows_w.sort(key=lambda x: (-x[0], x[1]))
    for sh, lbl, t in rows_w:
        women["names"].append(lbl)
        women["share"].append(round(sh * 100, 1))
        women["n"].append(t)

    # ── flows: extensions and corrections per year ──────────────────────
    flows = {"x": x_years,
             "ext": [int(ysum(y, "ext")) for y in all_years],
             "fix": [int(ysum(y, "fix")) for y in all_years]}

    # ── YTD comparison ──────────────────────────────────────────────────
    ytd = None
    if partial and (last_year - 1) in m_years:
        months = set(m.loc[m["year"] == last_year, "month"].unique().tolist())
        cur = float(m[(m["year"] == last_year)]["new"].sum())
        prev = float(m[(m["year"] == last_year - 1) & m["month"].isin(months)]["new"].sum())
        cur_t = float(m[(m["year"] == last_year) & (m["group"] == TOUR)]["new"].sum())
        prev_t = float(m[(m["year"] == last_year - 1) & m["month"].isin(months)
                         & (m["group"] == TOUR)]["new"].sum())
        if prev > 0:
            ytd = {"cur": cur, "prev": prev, "chg": cur / prev - 1,
                   "cur_t": cur_t, "prev_t": prev_t,
                   "chg_t": (cur_t / prev_t - 1) if prev_t else None}

    # ── KPIs ────────────────────────────────────────────────────────────
    ref_total = ysum(ref)
    kpis = {
        "ref_total": {"value": int(ref_total), "display": _fmt(ref_total), "tone": "brand"},
        "span": {"value": len(all_years), "display": f"{all_years[0]}–{all_years[-1]}",
                 "tone": "brand"},
    }
    labels = {}
    if ytd:
        c = ytd["chg"]
        tone = ("ok" if c >= STABLE_PCT else "brand" if c > -STABLE_PCT
                else "warn" if c > -SHARP_DROP else "danger")
        kpis["ytd"] = {"value": round(ytd["chg"], 4), "display": _pct(ytd["chg"], signed=True), "tone": tone}
        labels["ytd_kpi"] = (f"שינוי ברישיונות החדשים {MONTHS_HE[0]}-{MONTHS_HE[last_month - 1]} {last_year} "
                             f"({_fmt(ytd['cur'])}) לעומת אותם חודשים ב-{last_year - 1}")
    tour_by_full = {y: ysum(y, groups=[TOUR]) for y in hist_full_years} or {ref: ysum(ref, groups=[TOUR])}
    peak_y = sorted(tour_by_full.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    peak_v = tour_by_full[peak_y]
    ref_t = ysum(ref, groups=[TOUR])
    vs_peak = ref_t / peak_v if peak_v else 0.0
    kpis["vs_peak"] = {"value": round(vs_peak, 4), "display": _pct(vs_peak, 0),
                       "tone": "ok" if vs_peak >= 0.95 else ("warn" if vs_peak < 0.7 else "info")}
    labels["vs_peak_kpi"] = f"רישיונות ביקור ב-{ref} מתוך שנת השיא {peak_y}"
    work_ref = ysum(ref, groups=["work"])
    work_base = ysum(base, groups=["work"])
    kpis["work"] = {"value": int(work_ref), "display": _fmt(work_ref),
                    "tone": "info" if work_base and work_ref / work_base >= GROWTH_RATIO else "brand"}
    labels["work_kpi"] = f"רישיונות עבודה (ב/1) חדשים ב-{ref}"
    ext_ref = ysum(ref, "ext")
    kpis["ext"] = {"value": int(ext_ref), "display": _fmt(ext_ref), "tone": "brand"}
    labels["ext_kpi"] = f"הארכות רישיון ב-{ref}"
    labels["ref_total_kpi"] = f"רישיונות שהייה חדשים ב-{ref}"
    labels["span_kpi"] = "שנות נתונים במאגר"

    # ── insights ────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_peak():
        if len(tour_by_full) < 2 or peak_y == ref:
            return None
        low_y = sorted(tour_by_full.items(), key=lambda kv: (kv[1], kv[0]))[0][0]
        s = (f"רישיונות הביקור (ב/2) הגיעו לשיא של {_fmt(peak_v)} ב-{peak_y}. "
             f"ב-{ref} ניתנו {_fmt(ref_t)}, {_pct(vs_peak, 0)} מרמת השיא")
        if low_y not in (peak_y, ref):
            s += f", אחרי שפל של {_fmt(tour_by_full[low_y])} ב-{low_y}"
        return s + "."

    def ins_ytd():
        if not ytd:
            return None
        c = ytd["chg"]
        if abs(c) < STABLE_PCT:
            d = f"יציב ({_pct(c, signed=True)})"
        else:
            d = f"{'עלייה' if c > 0 else 'ירידה'} של {_pct(abs(c))}"
        return (f"ב-{last_year} עד {MONTHS_HE[last_month - 1]} ניתנו {_fmt(ytd['cur'])} רישיונות חדשים, "
                f"{d} לעומת אותם חודשים ב-{last_year - 1} ({_fmt(ytd['prev'])}).")

    def ins_work():
        if ref == base or not work_base:
            return None
        ratio = work_ref / work_base
        if ratio >= GROWTH_RATIO:
            word = f"פי {ratio:.1f}" if ratio >= 2 else f"עלייה של {_pct(ratio - 1, 0)}"
        elif ratio <= 1 / GROWTH_RATIO:
            word = f"ירידה של {_pct(1 - ratio, 0)}"
        else:
            return None
        s = f"רישיונות העבודה החדשים (ב/1): {_fmt(work_ref)} ב-{ref} לעומת {_fmt(work_base)} ב-{base}, {word}"
        if top_secs:
            lead = top_secs[0]
            lv, lb = ws.get((ref, lead), 0), ws.get((base, lead), 0)
            s += f". הענף המוביל ב-{ref}: {lead} עם {_fmt(lv)} רישיונות"
            if lb:
                s += f" (לעומת {_fmt(lb)} ב-{base})"
        return s + "."

    def ins_work_country():
        if not work_c["names"] or ref == base:
            return None
        n, v, o = work_c["names"][0], work_c["cur"][0], work_c["old"][0]
        s = f"{n} היא ארץ המוצא המובילה של עובדים זרים חדשים ב-{ref}: {_fmt(v)} רישיונות, {_pct(work_c['share'][0])} מכלל רישיונות העבודה"
        return s + (f" (לעומת {_fmt(o)} ב-{base})." if o else ".")

    def ins_tour_country():
        if not tour_c["names"]:
            return None
        n, sh = tour_c["names"][0], tour_c["share"][0]
        if sh < 0.1:
            return None
        return f"בעלי דרכון של {n} קיבלו {_pct(sh)} מרישיונות הביקור ב-{ref} ({_fmt(tour_c['cur'][0])})."

    def ins_s25():
        vals = {y: ysum(y, groups=["s25"]) for y in hist_full_years}
        if len(vals) < 3:
            return None
        py = sorted(vals.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        if py == ref or not vals[py] or vals[ref] / vals[py] > 0.5:
            return None
        s = (f"רישיונות חדשים לפי ס' 2(א)(5) ירדו משיא של {_fmt(vals[py])} ב-{py} "
             f"ל-{_fmt(vals[ref])} ב-{ref}")
        if s25_top:
            s += f"; ב-{ref} הובילו {', '.join(s25_top)}"
        return s + "."

    def ins_season():
        if len(full_years) < MIN_SEASON_YEARS:
            return None
        g = m[(m["group"] == TOUR) & m["year"].isin(full_years)]
        by = g.groupby(["year", "month"])["new"].sum()
        tot = g.groupby("year")["new"].sum()
        share = {mo: sum(float(by.get((y, mo), 0)) / float(tot[y]) for y in full_years if tot[y]) / len(full_years)
                 for mo in range(1, 13)}
        order = sorted(share.items(), key=lambda kv: (-kv[1], kv[0]))
        hi, lo = order[0], order[-1]
        if hi[1] < 1.3 * (1 / 12):
            return None
        return (f"עונתיות: בממוצע השנים המלאות {full_years[0]}-{full_years[-1]}, "
                f"{MONTHS_HE[hi[0] - 1]} הוא החודש העמוס ברישיונות ביקור ({_pct(hi[1])} מהשנה) "
                f"ו{MONTHS_HE[lo[0] - 1]} השקט ביותר ({_pct(lo[1])}).")

    def ins_women():
        cand = [(s, nm, n) for s, nm, n in zip(women["share"], women["names"], women["n"]) if n >= MIN_WOMEN_N]
        if len(cand) < 2:
            return None
        top, bot = cand[0], cand[-1]
        if top[0] - bot[0] < 15:
            return None
        return (f"הרכב מגדרי ב-{ref}: נשים הן {top[0]:.1f}% ממקבלי רישיון בקטגוריה {top[1]}, "
                f"לעומת {bot[0]:.1f}% בקטגוריה {bot[1]}.")

    add("peak", ins_peak())
    add("ytd", ins_ytd())
    add("work", ins_work())
    add("work_country", ins_work_country())
    add("tour_country", ins_tour_country())
    add("s25", ins_s25())
    add("season", ins_season())
    add("women", ins_women())

    # ── ledes / aria ────────────────────────────────────────────────────
    partial_note = (f" * {last_year}: נתונים חלקיים עד {MONTHS_HE[last_month - 1]}." if partial else "")
    hist_note = ""
    if h_years:
        hist_note = (f" השנים {h_years[0]}-{h_years[-1]} מהקובץ השנתי ההיסטורי, ומ-{first_m} מהקובץ החודשי"
                     f" המתעדכן.")
        if suppressed:
            hist_note += f" בקובץ ההיסטורי {suppressed:,} תאים מסומנים \"קטן מ6\" ונספרו כאפס."
    ti = max(range(len(tot_y)), key=lambda i: (tot_y[i], -i))
    labels["yearly_lede"] = (f"השנה עם המספר הגבוה ביותר של רישיונות חדשים: {all_years[ti]} ({_fmt(tot_y[ti])})."
                             + hist_note + partial_note)
    labels["yearly_aria"] = (f"גרף עמודות מוערמות: רישיונות שהייה חדשים לזרים לפי שנה, {all_years[0]} עד "
                             f"{all_years[-1]}, ביקור ותיירות לעומת שאר הסוגים. שיא ב-{all_years[ti]}.")
    mi = max(range(len(monthly["tour"])), key=lambda i: (monthly["tour"][i] + monthly["other"][i], -i))
    mi_y, mi_m = ym_pairs[mi]
    labels["monthly_lede"] = (f"החודש העמוס ביותר מאז {first_m}: {MONTHS_HE[mi_m - 1]} {mi_y} עם "
                              f"{_fmt(monthly['tour'][mi] + monthly['other'][mi])} רישיונות חדשים. "
                              f"אפשר להגדיל קטע זמן בעזרת המחוון שמתחת לגרף.")
    labels["monthly_aria"] = f"גרף קווים: רישיונות חדשים לפי חודש מאז {first_m}, ביקור ותיירות לעומת שאר הסוגים."
    labels["heat_lede"] = (f"רישיונות ביקור (ב/2) חדשים בכל חודש, {m_years[0]} עד {m_years[-1]}. "
                           f"צבע כהה יותר = יותר רישיונות.")
    labels["heat_aria"] = f"מפת חום: רישיונות ביקור חדשים לפי חודש ושנה, {m_years[0]} עד {m_years[-1]}."
    nt_ref = {k: ysum(ref, groups=[k]) for k in NONTOUR_KEYS}
    nt_lead = sorted(nt_ref.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    nt_total = sum(nt_ref.values())
    labels["mix_lede"] = (f"ללא רישיונות ביקור. ב-{ref} ניתנו {_fmt(nt_total)} רישיונות חדשים מסוגים אחרים; "
                          f"הקטגוריה הגדולה: {GROUP_LABEL[nt_lead[0]]} ({_pct(nt_lead[1] / nt_total if nt_total else 0)})."
                          + partial_note)
    labels["mix_aria"] = f"גרף עמודות מוערמות: רישיונות חדשים שאינם רישיונות ביקור, לפי סוג ושנה, {all_years[0]} עד {all_years[-1]}."
    sec_ref_total = float(w[w["year"] == ref]["new"].sum())
    labels["sectors_lede"] = (
        (f"רישיונות עבודה (ב/1) חדשים לפי ענף ההיתר. ב-{ref}: {_fmt(sec_ref_total)} רישיונות, "
         f"בראש: {top_secs[0]} ({_pct(float(ws.get((ref, top_secs[0]), 0)) / sec_ref_total if sec_ref_total else 0)}). "
         f"מוצגים {len(top_secs)} הענפים הגדולים ב-{ref}, השאר תחת \"אחר\".") if top_secs else
        "רישיונות עבודה (ב/1) חדשים לפי ענף ההיתר.") + partial_note
    labels["sectors_aria"] = f"גרף עמודות מוערמות: רישיונות עבודה חדשים לפי ענף ושנה מאז {first_m}."
    labels["tour_c_lede"] = (f"{len(tour_c['names'])} ארצות הדרכון המובילות ברישיונות ביקור ב-{ref}, "
                             f"לצד מספרן ב-{base}.")
    labels["tour_c_aria"] = (f"גרף עמודות: ארצות הדרכון המובילות ברישיונות ביקור ב-{ref} לעומת {base}"
                             + (f", בראש {tour_c['names'][0]}." if tour_c["names"] else "."))
    labels["work_c_lede"] = (f"{len(work_c['names'])} ארצות הדרכון המובילות ברישיונות עבודה (ב/1) ב-{ref}, "
                             f"לצד מספרן ב-{base}.")
    labels["work_c_aria"] = (f"גרף עמודות: ארצות הדרכון המובילות ברישיונות עבודה ב-{ref} לעומת {base}"
                             + (f", בראש {work_c['names'][0]}." if work_c["names"] else "."))
    s25_peak_i = max(range(len(s25["new"])), key=lambda i: (s25["new"][i], -i))
    labels["s25_lede"] = (f"רישיון ישיבה זמני לפי סעיף 2(א)(5) לחוק הכניסה לישראל. שיא הרישיונות החדשים: "
                          f"{all_years[s25_peak_i]} ({_fmt(s25['new'][s25_peak_i])})"
                          + (f"; ארצות הדרכון המובילות ב-{ref}: {', '.join(s25_top)}." if s25_top else ".")
                          + partial_note)
    labels["s25_title"] = "רישיונות לפי סעיף 2(א)(5)"
    labels["s25_aria"] = f"גרף עמודות וקו: רישיונות חדשים והארכות לפי ס' 2(א)(5), {all_years[0]} עד {all_years[-1]}."
    py_tot = sum(pyramid["men"]) + sum(pyramid["women"])
    big_i = max(range(len(AGE_ORDER)), key=lambda i: (pyramid["men"][i] + pyramid["women"][i], -i))
    labels["pyr_lede"] = (f"כל הרישיונות החדשים ב-{ref} לפי מין וקבוצת גיל. קבוצת הגיל הגדולה: "
                          f"{AGE_ORDER[big_i]} ({_pct((pyramid['men'][big_i] + pyramid['women'][big_i]) / py_tot if py_tot else 0)})."
                          + (f" לא נכללו {_fmt(unknown_pyr)} רישיונות ללא מין או גיל רשומים." if unknown_pyr else ""))
    labels["pyr_aria"] = f"פירמידת גילים: רישיונות חדשים ב-{ref} לפי מין וקבוצת גיל."
    labels["women_lede"] = (f"שיעור הנשים מבין מקבלי רישיונות חדשים ב-{ref}, לפי סוג הרישיון "
                            f"(רק רישיונות עם מין רשום).")
    labels["women_aria"] = f"גרף עמודות אופקי: שיעור הנשים לפי סוג רישיון ב-{ref}."
    fi = max(range(len(flows["ext"])), key=lambda i: (flows["ext"][i], -i))
    labels["flows_lede"] = (f"מלבד רישיונות חדשים, הרשות מאריכה ומתקנת רישיונות קיימים. שיא ההארכות: "
                            f"{all_years[fi]} ({_fmt(flows['ext'][fi])})"
                            + (f"; ב-{ref}: {_fmt(ext_ref)} הארכות." if all_years[fi] != ref else ".")
                            + partial_note)
    labels["flows_aria"] = f"גרף עמודות: הארכות ותיקוני רישיונות לפי שנה, {all_years[0]} עד {all_years[-1]}."
    labels["ref_year"] = str(ref)
    labels["base_year"] = str(base)

    summary = (f"רישיונות שהייה לזרים לפי סוג אשרה, ארץ דרכון, ענף, מין וגיל, {all_years[0]}-{all_years[-1]}: "
               f"{_fmt(ref_total)} רישיונות חדשים ב-{ref}, מהם {_fmt(work_ref)} רישיונות עבודה.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["רישיונות שהייה", "זרים", "עובדים זרים", "תיירות", "הגירה", "אשרות"],
            "related_ids": ["7c27e23b-86f1-44ee-9d9b-4f8880ca0973"],
            "temporal_coverage": f"{all_years[0]}/{all_years[-1]}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "yearly": {"x": x_years, "tour": tour_y, "other": non_y, "total": tot_y},
            "monthly": monthly,
            "heat": heat,
            "mix": mix,
            "sectors": sectors,
            "tour_c": tour_c,
            "work_c": work_c,
            "s25": s25,
            "pyramid": pyramid,
            "women": women,
            "flows": flows,
        },
        "tables": {"mix": mix_rows, "sectors": sector_rows},
        "insights": insights,
        "labels": labels,
        "flags": {"ytd": bool(ytd), "sectors": bool(top_secs), "work_c": bool(work_c["names"])},
    }
