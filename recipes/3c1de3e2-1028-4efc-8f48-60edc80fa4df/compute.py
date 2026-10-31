"""Pre-hospital (ambulance) quality indicators, Ministry of Health national program.

Every resource is one indicator. Each row is a cell of
(indicator, year, month, provider, gender, shift, day range, age range) with
`number_of_cases` (eligible cases, the denominator) and
`number_of_cases_approved` (cases that met the indicator, the numerator; an
empty value means none did). A rate is always sum(approved) / sum(cases).

Cross-sectional views (providers, shifts, gender, age, day range) use each
indicator's own latest year, since indicators are published for different
years. Trend views use every year.
"""

import pandas as pd

MIN_N = 30            # min eligible cases for a provider / group rate to be shown
TREND_PP = 1.0        # change (percentage points) that counts as a rise/fall
SPREAD_PP = 3.0       # provider spread worth an insight
GAP_GENDER_PP = 1.5
GAP_AGE_PP = 2.0
GAP_SHIFT_PP = 1.5
MAX_PROVIDERS = 16
UNKNOWN = "לא ידוע"

# Short display names for known indicator codes; unknown codes fall back to
# the dataset's own measure_description.
SHORT_NAMES = {
    "06-15-1-06-001": "מתן אספירין בכאב חזה",
    "06-15-1-03-001": 'מסירת אק"ג בחשד ל-STEMI',
    "06-15-1-02-001": "הערכת שבץ סטנדרטית",
    "06-15-1-05-001": "הודעה מוקדמת על שבץ",
    "06-16-1-01-001": "הערכת כאב למפונים",
    "06-16-1-01-002": "מדידת CO2 באינטובציה",
    "06-17-1-06-002": "דופק עצמוני לאחר דום לב",
}
SHIFT_ORDER = {"בוקר": 0, "ערב": 1, "לילה": 2}
# Day ranges: the gap is (second − first) in this order; unknown labels sort
# after the known ones, alphabetically.
DAY_ORDER = {"א - ד כולל ש": 0, "ה - ו": 1}
DAY_DISPLAY = {"א - ד כולל ש": "א-ד ושבת", "ה - ו": "ה-ו"}
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _pp(x):
    return round(x * 100, 1)


def _signed_pp(x):
    v = x * 100
    s = f"{abs(v):.1f}"
    return ("+" if v >= 0 else "−") + s


def _r1(x):
    return round(x, 1) + 0.0


def _rate(sub):
    n = float(sub["n"].sum())
    a = float(sub["a"].sum())
    return (a / n if n > 0 else None), n, a


def _clean(s):
    return " ".join(str(s).split())


def _age_key(label):
    t = label.replace("עד", "").replace("+", "").strip()
    first = t.split("-")[0].strip()
    try:
        v = float(first)
    except ValueError:
        return None
    if label.strip().startswith("עד"):
        return -1.0  # "up to X" is the youngest band
    return v


def _provider_label(p):
    for pre in ("מד'א - ", "מד\"א - "):
        if p.startswith(pre):
            return p[len(pre):]
    return p


def _year_txt(m):
    if m["ref_partial"]:
        return f"{m['ly']}, חלקית: {m['ref_months']} חודשים"
    return f"{m['ly']}"


def _join(items):
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = " ו-" if last[:1].isdigit() or last[:1].isascii() else " ו"
    return ", ".join(items[:-1]) + conj + last


def compute(frames):
    df = frames["main"].copy()
    for c in ["measure_code", "measure_description", "measure_long_description",
              "subject_desc", "provider", "provider_ownership", "gender", "shift",
              "day_range", "age_range"]:
        df[c] = df[c].map(_clean)
    df["age_range"] = df["age_range"].str.replace(" +", "+", regex=False).str.replace(
        " - ", "-", regex=False)
    df["n"] = pd.to_numeric(df["number_of_cases"].str.replace(",", ""), errors="coerce")
    df["a"] = pd.to_numeric(df["number_of_cases_approved"].str.replace(",", ""),
                            errors="coerce").fillna(0)
    df["year"] = pd.to_numeric(df["measurement_year"], errors="coerce")
    df["mon"] = pd.to_numeric(df["month"], errors="coerce")
    df["tgt"] = pd.to_numeric(df["target"], errors="coerce").fillna(0)
    df["start"] = pd.to_numeric(df["measurement_start_year"], errors="coerce")
    df = df[df["n"].notna() & (df["n"] > 0) & df["year"].notna()
            & (df["measure_code"] != "")].copy()
    df["year"] = df["year"].astype(int)
    df["a"] = df[["a", "n"]].min(axis=1)

    # ── indicators ────────────────────────────────────────────────────
    measures = []
    for code, sub in df.groupby("measure_code", sort=True):
        desc = sub["measure_description"].value_counts().sort_index().idxmax()
        name = SHORT_NAMES.get(code, desc)
        subject = sub["subject_desc"].value_counts().sort_index().idxmax()
        long_desc = sub["measure_long_description"].value_counts().sort_index().idxmax()
        years = sorted(sub["year"].unique().tolist())
        by_year = []
        for y in years:
            ys = sub[sub["year"] == y]
            r, n, a = _rate(ys)
            months = int(ys["mon"].dropna().nunique())
            tg = float(ys["tgt"].max())
            by_year.append({"year": y, "rate": r, "n": n, "a": a,
                            "months": months, "target": tg})
        # Reference year for the cross-sectional views and the target check:
        # the latest year, unless it is partial (< 12 months) and an earlier
        # full year exists; then the latest full year (annual targets apply
        # to full years). A partial reference year is flagged and disclosed.
        full = [b for b in by_year if b["months"] >= 12]
        skipped = None
        if by_year[-1]["months"] < 12 and full:
            ref = full[-1]
            skipped = {"year": by_year[-1]["year"], "months": by_year[-1]["months"]}
        else:
            ref = by_year[-1]
        ly = ref["year"]
        lsub = sub[sub["year"] == ly]
        lr, ln, la = _rate(lsub)
        tgt = float(lsub["tgt"].max())
        start = sub["start"].dropna()
        measures.append({
            "code": code, "name": name, "subject": subject, "long": long_desc,
            "years": years, "ly": ly, "rate": lr, "n": ln, "a": la,
            "target": tgt, "start": int(start.min()) if len(start) else None,
            "by_year": by_year, "ref_partial": ref["months"] < 12,
            "ref_months": ref["months"], "skipped": skipped,
            "total_n": float(sub["n"].sum()),
        })
    # order: latest-year rate, highest first (ties by code)
    measures.sort(key=lambda m: (-m["rate"], m["code"]))
    names = [m["name"] for m in measures]
    latest = pd.concat([df[(df["measure_code"] == m["code"]) & (df["year"] == m["ly"])]
                        for m in measures]) if measures else df.iloc[0:0]

    # ── KPIs ──────────────────────────────────────────────────────────
    total_n = float(df["n"].sum())
    y0, y1 = int(df["year"].min()), int(df["year"].max())
    providers_all = sorted(df["provider"].unique().tolist())
    with_target = [m for m in measures if m["target"] > 0]
    met = [m for m in with_target if m["rate"] is not None and m["rate"] >= m["target"]]
    priv = float(df.loc[df["provider_ownership"] == "פרטית", "n"].sum())
    priv_share = priv / total_n if total_n else 0.0
    kpis = {
        "measures": {"value": len(measures), "display": f"{len(measures):,}", "tone": "brand"},
        "cases": {"value": int(total_n), "display": f"{int(total_n):,}", "tone": "brand"},
        "years": {"value": y1 - y0 + 1,
                  "display": f"{y0}–{y1}" if y1 > y0 else f"{y0}", "tone": "brand"},
        "providers": {"value": len(providers_all), "display": f"{len(providers_all):,}",
                      "tone": "brand"},
        "private": {"value": round(priv_share, 4), "display": _pct(priv_share), "tone": "info"},
    }
    if with_target:
        tone = "ok" if len(met) == len(with_target) else ("warn" if met else "danger")
        kpis["met"] = {"value": len(met), "display": f"{len(met)}/{len(with_target)}",
                       "tone": tone}

    # ── chart: scorecard (latest year per indicator) ─────────────────
    score_items = []
    for m in measures:
        status = "none"
        if m["target"] > 0:
            status = "ok" if m["rate"] >= m["target"] else "below"
        score_items.append({
            "name": m["name"], "rate": _pp(m["rate"]), "year": _year_txt(m),
            "target": _pp(m["target"]) if m["target"] > 0 else None,
            "status": status, "n": int(m["n"]),
        })
    score_rows = [{
        "name": m["name"], "subject": m["subject"], "long": m["long"],
        "year": _year_txt(m), "start": str(m["start"]) if m["start"] else "",
        "rate": _pct(m["rate"]),
        "target": _pct(m["target"], 0) if m["target"] > 0 else "ללא יעד",
        "n": f"{int(m['n']):,}",
        "status": ("עומד ביעד" if m["rate"] >= m["target"] else "מתחת ליעד")
        if m["target"] > 0 else "",
    } for m in measures]

    # ── chart: yearly trend + volume ─────────────────────────────────
    all_years = sorted(df["year"].unique().tolist())
    trend_series, vol_series, trend_rows = [], [], []
    for m in measures:
        by = {b["year"]: b for b in m["by_year"]}
        trend_series.append({"name": m["name"],
                             "data": [_pp(by[y]["rate"]) if y in by else None for y in all_years]})
        vol_series.append({"name": m["name"],
                           "data": [int(by[y]["n"]) if y in by else None for y in all_years]})
        trend_rows.append({"name": m["name"],
                           "cells": [(_pct(by[y]["rate"]) + " (" + f"{int(by[y]['n']):,}" + ")")
                                     if y in by else "" for y in all_years]})

    # ── chart: monthly rate per indicator ────────────────────────────
    dm = df[df["mon"].between(1, 12)].copy()
    dm["ym"] = dm["year"].astype(str) + "-" + dm["mon"].astype(int).map(lambda v: f"{v:02d}")
    yms = sorted(dm["ym"].unique().tolist())
    gm = dm.groupby(["measure_code", "ym"])[["n", "a"]].sum()
    monthly_series = []
    for m in measures:
        vals = []
        for ym in yms:
            if (m["code"], ym) in gm.index:
                row = gm.loc[(m["code"], ym)]
                vals.append(_pp(row["a"] / row["n"]) if row["n"] > 0 else None)
            else:
                vals.append(None)
        monthly_series.append({"name": m["name"], "data": vals})

    # ── chart: seasonality of case volume (full years only) ─────────
    season_cells, season_max = [], 100.0
    season_min = 100.0
    season_rows = []
    for mi, m in enumerate(measures):
        full_years = [b["year"] for b in m["by_year"] if b["months"] == 12]
        s = dm[(dm["measure_code"] == m["code"]) & (dm["year"].isin(full_years))]
        if s.empty:
            continue
        per = s.groupby("mon")["n"].sum().reindex(range(1, 13), fill_value=0)
        avg = per.mean()
        if avg <= 0:
            continue
        row = []
        for k in range(12):
            idx = round(float(per.iloc[k] / avg * 100), 0)
            season_cells.append([k, mi, idx])
            row.append(idx)
            season_max = max(season_max, idx)
            season_min = min(season_min, idx)
        season_rows.append({"mi": mi, "peak": MONTHS_HE[int(per.values.argmax())],
                            "peak_idx": max(row), "low": MONTHS_HE[int(per.values.argmin())],
                            "low_idx": min(row), "years": len(full_years)})

    # ── chart: providers heatmap (latest year per indicator) ────────
    lp = latest.groupby(["measure_code", "provider"])[["n", "a"]].sum()
    prov_n = latest.groupby("provider")["n"].sum()
    prov_owner = latest.groupby("provider")["provider_ownership"].agg(
        lambda s: s.value_counts().sort_index().idxmax())
    eligible = sorted({p for (c, p), r in lp.iterrows() if r["n"] >= MIN_N},
                      key=lambda p: (-prov_n[p], p))[:MAX_PROVIDERS]
    heat_cells, prov_rows = [], []
    lowest_count = {}
    spread = []
    for mi, m in enumerate(measures):
        rates = []
        for p in eligible:
            if (m["code"], p) in lp.index:
                r = lp.loc[(m["code"], p)]
                if r["n"] >= MIN_N:
                    rates.append((p, r["a"] / r["n"], r["n"]))
        for p, r, n in rates:
            pi = eligible.index(p)
            heat_cells.append([mi, pi, _r1((r - m["rate"]) * 100), _pp(r), int(n)])
        if len(rates) >= 3:
            lo = min(rates, key=lambda t: (t[1], t[0]))
            hi = max(rates, key=lambda t: (t[1], t[0]))
            lowest_count.setdefault(lo[0], []).append(m["name"])
            spread.append((hi[1] - lo[1], m, hi, lo))
    excluded = sorted(set(providers_all) - set(eligible))
    # Colour scale clamp: the 90th percentile of |deviation| (at least 3 pp),
    # so one or two outlying small providers don't wash out the regions.
    devs = sorted(abs(c[2]) for c in heat_cells)
    heat_limit = 3.0
    if devs:
        p90 = devs[int(0.9 * (len(devs) - 1))]
        heat_limit = max(3.0, float(int(p90 * 2 + 0.999)) / 2)
    heat_max = devs[-1] if devs else 0.0
    for p in eligible:
        cells = []
        for m in measures:
            if (m["code"], p) in lp.index and lp.loc[(m["code"], p)]["n"] >= MIN_N:
                r = lp.loc[(m["code"], p)]
                cells.append(_pct(r["a"] / r["n"]))
            else:
                cells.append("")
        prov_rows.append({"name": _provider_label(p), "owner": prov_owner[p],
                          "n": f"{int(prov_n[p]):,}", "cells": cells})

    # ── group dimensions (latest year per indicator) ────────────────
    def group_rates(sub, col):
        g = sub.groupby(col)[["n", "a"]].sum()
        return {k: (r["a"] / r["n"], r["n"]) for k, r in g.iterrows()
                if k != UNKNOWN and k != "" and r["n"] >= MIN_N}

    shift_names = sorted({s for s in latest["shift"].unique() if s not in (UNKNOWN, "")},
                         key=lambda s: (SHIFT_ORDER.get(s, 9), s))
    shift_series = {s: [] for s in shift_names}
    shift_rows, gap_rows = [], []
    gender_gap, age_gap, day_gap, shift_gap = [], [], [], []
    day_labels = sorted({d for d in latest["day_range"].unique() if d not in (UNKNOWN, "")},
                        key=lambda d: (DAY_ORDER.get(d, 9), d))
    day_gap_label = (f"{DAY_DISPLAY.get(day_labels[1], day_labels[1])} מול "
                     f"{DAY_DISPLAY.get(day_labels[0], day_labels[0])}") if len(day_labels) == 2 else ""
    g_vals, a_vals, d_vals = [], [], []
    for m in measures:
        sub = latest[latest["measure_code"] == m["code"]]
        sr = group_rates(sub, "shift")
        for s in shift_names:
            shift_series[s].append(_r1((sr[s][0] - m["rate"]) * 100) if s in sr else None)
        shift_rows.append({"name": m["name"],
                           "cells": [_pct(sr[s][0]) if s in sr else "" for s in shift_names]})
        if len(sr) >= 2:
            hi = max(sr.items(), key=lambda t: (t[1][0], t[0]))
            lo = min(sr.items(), key=lambda t: (t[1][0], t[0]))
            shift_gap.append((hi[1][0] - lo[1][0], m, hi, lo))

        gr = group_rates(sub, "gender")
        g_val = None
        if "נקבה" in gr and "זכר" in gr:
            g_val = gr["נקבה"][0] - gr["זכר"][0]
            gender_gap.append((abs(g_val), m, gr["נקבה"][0], gr["זכר"][0]))
        ar = group_rates(sub, "age_range")
        keyed = sorted([(k, _age_key(k), v) for k, v in ar.items() if _age_key(k) is not None],
                       key=lambda t: (t[1], t[0]))
        a_val, a_lbl = None, ""
        if len(keyed) >= 2:
            young, old = keyed[0], keyed[-1]
            a_val = old[2][0] - young[2][0]
            a_lbl = f"{old[0]} מול {young[0]}"
            age_gap.append((abs(a_val), m, old, young))
        dr = group_rates(sub, "day_range")
        d_val = None
        if len(day_labels) == 2 and all(d in dr for d in day_labels):
            d_val = dr[day_labels[1]][0] - dr[day_labels[0]][0]
            day_gap.append((abs(d_val), m))
        g_vals.append(_r1(g_val * 100) if g_val is not None else None)
        a_vals.append(_r1(a_val * 100) if a_val is not None else None)
        d_vals.append(_r1(d_val * 100) if d_val is not None else None)
        gap_rows.append({
            "name": m["name"], "year": str(m["ly"]),
            "female": _pct(gr["נקבה"][0]) if "נקבה" in gr else "",
            "male": _pct(gr["זכר"][0]) if "זכר" in gr else "",
            "gender_gap": _signed_pp(g_val) if g_val is not None else "",
            "age": a_lbl, "age_gap": _signed_pp(a_val) if a_val is not None else "",
            "day_gap": _signed_pp(d_val) if d_val is not None else "",
        })
    gaps_chart = {
        "names": names,
        "gender": g_vals,
        "age": a_vals,
        "day": d_vals,
        "age_labels": [r["age"] for r in gap_rows],
        "day_label": day_gap_label,
    }

    # ── insights ─────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_target():
        if not with_target:
            return None
        below = [m for m in with_target if m not in met]
        if not below:
            parts = [f"{m['name']} {_pct(m['rate'])} ({_year_txt(m)})" for m in with_target]
            return (f"כל {len(with_target)} המדדים שנקבע להם יעד עומדים בו בשנת המדידה המלאה "
                    f"האחרונה שלהם: {_join(parts)}.") if len(with_target) > 1 else (
                f"המדד היחיד שנקבע לו יעד, {with_target[0]['name']}, עומד בו: "
                f"{_pct(with_target[0]['rate'])} מול יעד של {_pct(with_target[0]['target'], 0)} "
                f"({_year_txt(with_target[0])}).")
        parts = [f"{m['name']} {_pct(m['rate'])} מול יעד {_pct(m['target'], 0)} ({_year_txt(m)})"
                 for m in below]
        return (f"{len(below)} מתוך {len(with_target)} המדדים שנקבע להם יעד נמצאים מתחתיו "
                f"בשנת המדידה המלאה האחרונה: {_join(parts)}.")

    def ins_range():
        rated = [m for m in measures if m["rate"] is not None]
        if len(rated) < 2:
            return None
        hi = max(rated, key=lambda m: (m["rate"], m["code"]))
        lo = min(rated, key=lambda m: (m["rate"], m["code"]))
        if hi is lo:
            return None
        return (f"שיעור העמידה הגבוה ביותר הוא ב{hi['name']} ({_pct(hi['rate'])}, {_year_txt(hi)}) "
                f"והנמוך ביותר ב{lo['name']} ({_pct(lo['rate'])}, {_year_txt(lo)}).")

    def ins_trend():
        ups, downs, flat = [], [], []
        dropped_partial = False
        for m in measures:
            full = [b for b in m["by_year"] if b["months"] == 12]
            if len(full) < len(m["by_year"]):
                dropped_partial = True
            if len(full) < 2:
                continue
            f, l = full[0], full[-1]
            d = l["rate"] - f["rate"]
            txt = f"{m['name']} מ-{_pct(f['rate'])} ב-{f['year']} ל-{_pct(l['rate'])} ב-{l['year']}"
            if d * 100 >= TREND_PP:
                ups.append(txt)
            elif d * 100 <= -TREND_PP:
                downs.append(txt)
            else:
                flat.append(m["name"])
        if not (ups or downs or flat):
            return None
        parts = []
        if ups:
            parts.append("עלייה ב" + _join(ups))
        if downs:
            parts.append("ירידה ב" + _join(downs))
        s = "במדדים שנמדדו בכמה שנים: " + "; ".join(parts) if parts else ""
        if flat:
            s += ("; " if s else "במדדים שנמדדו בכמה שנים, ") + \
                f"יציבות (שינוי של פחות מ-{TREND_PP:.0f} נקודת אחוז) ב{_join(flat)}"
        if dropped_partial:
            s += " (שנים חלקיות לא נכללו)"
        return s + "."

    def ins_spread():
        cand = [t for t in spread if t[0] * 100 >= SPREAD_PP]
        if not cand:
            return None
        gap, m, hi, lo = max(cand, key=lambda t: (t[0], t[1]["code"]))
        return (f"הפער הגדול ביותר בין ספקי השירות הוא ב{m['name']} ({m['ly']}): "
                f"{_provider_label(hi[0])} {_pct(hi[1])} לעומת {_provider_label(lo[0])} "
                f"{_pct(lo[1])}, פער של {gap * 100:.1f} נקודות אחוז "
                f"(ספקים עם {MIN_N} מקרים לפחות).")

    def ins_lowest_repeat():
        if not lowest_count:
            return None
        p, ms = max(lowest_count.items(), key=lambda t: (len(t[1]), t[0]))
        tie = [q for q, v in lowest_count.items() if len(v) == len(ms)]
        if len(ms) < 2 or len(tie) > 1:
            return None
        return (f"{_provider_label(p)} מדורג אחרון בין ספקי השירות ב-{len(ms)} מתוך "
                f"{len(spread)} המדדים שהושוו: {_join(ms)}.")

    def ins_gender():
        cand = [t for t in gender_gap if t[0] * 100 >= GAP_GENDER_PP]
        if not cand:
            return None
        _, m, f, ml = max(cand, key=lambda t: (t[0], t[1]["code"]))
        who = "נשים" if f < ml else "גברים"
        return (f"ב{m['name']} ({m['ly']}) שיעור העמידה בקרב {who} נמוך יותר: "
                f"נשים {_pct(f)} לעומת גברים {_pct(ml)}.")

    def ins_age():
        cand = [t for t in age_gap if t[0] * 100 >= GAP_AGE_PP]
        if not cand:
            return None
        _, m, old, young = max(cand, key=lambda t: (t[0], t[1]["code"]))
        lower = old if old[2][0] < young[2][0] else young
        higher = young if lower is old else old
        return (f"ב{m['name']} ({m['ly']}) שיעור העמידה בקבוצת הגיל {lower[0]} נמוך יותר: "
                f"{_pct(lower[2][0])} לעומת {_pct(higher[2][0])} בגילי {higher[0]}.")

    def ins_shift():
        cand = [t for t in shift_gap if t[0] * 100 >= GAP_SHIFT_PP]
        if not cand:
            return None
        gap, m, hi, lo = max(cand, key=lambda t: (t[0], t[1]["code"]))
        return (f"ב{m['name']} ({m['ly']}) משמרת ה{lo[0]} חלשה מכולן ({_pct(lo[1][0])}) לעומת "
                f"משמרת ה{hi[0]} ({_pct(hi[1][0])}).")

    def ins_volume():
        if not measures:
            return None
        m = max(measures, key=lambda m: (m["n"], m["code"]))
        txt = (f"{m['name']} הוא המדד בהיקף הגדול ביותר: {int(m['n']):,} מקרים נמדדו "
               f"ב-{m['ly']}")
        if m["ref_partial"]:
            txt += f" (שנה חלקית: {m['ref_months']} חודשים)"
        idx = m["years"].index(m["ly"])
        if idx >= 1 and not m["ref_partial"]:
            prev = m["by_year"][idx - 1]
            ch = m["n"] / prev["n"] - 1 if prev["n"] else 0
            if prev["months"] >= 12 and abs(ch) >= 0.02:
                txt += (f", {'עלייה' if ch > 0 else 'ירידה'} של {abs(ch) * 100:.1f}% "
                        f"לעומת {prev['year']}")
        return txt + "."

    add("target", ins_target())
    add("range", ins_range())
    add("trend", ins_trend())
    add("spread", ins_spread())
    add("lowest_provider", ins_lowest_repeat())
    add("gender", ins_gender())
    add("age", ins_age())
    add("shift", ins_shift())
    add("volume", ins_volume())

    # ── labels / ledes ───────────────────────────────────────────────
    labels = {}
    if measures:
        top = max(measures, key=lambda m: (m["rate"], m["code"]))
        low = min(measures, key=lambda m: (m["rate"], m["code"]))
        labels["score_aria"] = (f"תרשים עמודות אופקי: שיעור העמידה בכל אחד מ-{len(measures)} "
                                f"המדדים בשנת המדידה האחרונה שלו. הגבוה: {top['name']} "
                                f"{_pct(top['rate'])}; הנמוך: {low['name']} {_pct(low['rate'])}.")
        labels["score_lede"] = (
            f"כל מדד מוצג לשנה האחרונה שנמדדה במלואה ({_join(sorted({str(m['ly']) for m in measures}))}). "
            + (f"{len(met)} מתוך {len(with_target)} המדדים שנקבע להם יעד עומדים בו; "
               "הסימון האנכי הוא היעד." if with_target else "לאף מדד לא נקבע יעד בנתונים."))
        sk = [m for m in measures if m["skipped"]]
        if sk:
            labels["score_lede"] += " " + " ".join(
                f"ב{m['name']} נתוני {m['skipped']['year']} חלקיים ({m['skipped']['months']} "
                f"חודשים), ולכן מוצגת שנת {m['ly']}, השנה המלאה האחרונה." for m in sk)
        pp = [m for m in measures if m["ref_partial"]]
        if pp:
            labels["score_lede"] += " " + " ".join(
                f"ב{m['name']} שנת {m['ly']} חלקית ({m['ref_months']} חודשים) ואין שנה מלאה "
                "קודמת." for m in pp)
    multi = [m for m in measures if len(m["years"]) >= 2]
    labels["trend_aria"] = (f"תרשים קווים: שיעור העמידה השנתי לפי מדד, {all_years[0]}-"
                            f"{all_years[-1]}. {len(multi)} מדדים נמדדו ביותר משנה אחת.")
    labels["trend_lede"] = (f"שיעור העמידה בכל שנה לכל מדד בשנים {all_years[0]}-{all_years[-1]}. "
                            f"{len(multi)} מתוך {len(measures)} המדדים נמדדו ביותר משנה אחת; "
                            "השאר מופיעים כנקודה בודדת.")
    labels["vol_aria"] = (f"תרשים עמודות בציר לוגריתמי: מספר המקרים שנמדדו בכל שנה לכל מדד. "
                          f"סך הכול {int(total_n):,} מקרים.")
    big = max(measures, key=lambda m: (m["total_n"], m["code"]))
    small = min(measures, key=lambda m: (m["total_n"], m["code"]))
    labels["vol_lede"] = (f"היקפי המדידה שונים מאוד: {big['name']} כולל {int(big['total_n']):,} "
                          f"מקרים לאורך כל השנים, ו{small['name']} {int(small['total_n']):,} בלבד. "
                          "הציר לוגריתמי כדי שכל המדדים ייראו.")
    labels["monthly_aria"] = (f"תרשים קווים: שיעור העמידה החודשי לפי מדד, {len(yms)} חודשים "
                              f"מ-{yms[0]} עד {yms[-1]}.") if yms else ""
    labels["monthly_lede"] = ("התנודות החודשיות בכל מדד. במדדים קטנים כל חודש מבוסס על מעט "
                              "מקרים, ולכן התנודה גדולה יותר. אפשר להסתיר מדדים במקרא.")
    if season_rows:
        top_season = max(season_rows, key=lambda r: (r["peak_idx"], -r["mi"]))
        labels["season_aria"] = (f"מפת חום: היקף המקרים בכל חודש ביחס לממוצע החודשי (100) לכל "
                                 f"מדד. השיא הבולט: {measures[top_season['mi']]['name']} "
                                 f"ב{top_season['peak']} ({top_season['peak_idx']:.0f}).")
        labels["season_lede"] = (f"כמה מקרים נמדדו בכל חודש לעומת חודש ממוצע באותו מדד (100 = "
                                 f"ממוצע; שנים מלאות בלבד). השיא הבולט: "
                                 f"{measures[top_season['mi']]['name']} ב{top_season['peak']} "
                                 f"(מדד {top_season['peak_idx']:.0f}).")
    labels["prov_aria"] = (f"מפת חום: שיעור העמידה של {len(eligible)} ספקי שירות בכל מדד, "
                           "כסטייה בנקודות אחוז מהשיעור הארצי של המדד.")
    labels["prov_lede"] = (f"כל תא מראה את שיעור העמידה של ספק השירות במדד, בשנה שמוצגת בכרטיס הציון "
                           f"של המדד. הצבע הוא הסטייה מהשיעור הארצי: כחול מעליו, אדום "
                           f"מתחתיו. מוצגים רק תאים עם {MIN_N} מקרים לפחות"
                           + ("; ספק קטן אחד לא מוצג." if len(excluded) == 1 else
                              f"; {len(excluded)} ספקים קטנים לא מוצגים." if excluded else ".")
                           + (f" סקאלת הצבע נחתכת ב-{heat_limit:.1f} נקודות אחוז לכל כיוון; "
                              f"סטיות גדולות יותר (עד {heat_max:.1f}) צבועות בגוון הקיצוני."
                              if heat_max > heat_limit else ""))
    labels["shift_aria"] = ("תרשים עמודות: סטיית שיעור העמידה של כל משמרת מהשיעור הכולל של "
                            "המדד, בנקודות אחוז.")
    labels["shift_lede"] = (f"עמודה מעל האפס פירושה שהמשמרת טובה מהממוצע של אותו מדד. קבוצות "
                            f"עם פחות מ-{MIN_N} מקרים ומשמרת לא ידועה לא נכללו.")
    day_txt = f" ובין ימים {day_gap_label}" if day_gap_label else ""
    day_first = (", ימי " + DAY_DISPLAY.get(day_labels[1], day_labels[1])) if day_gap_label else ""
    labels["day_gap"] = day_gap_label
    labels["gaps_aria"] = ("תרשים עמודות: פערי שיעור העמידה בנקודות אחוז בין נשים לגברים, בין "
                           f"קבוצת הגיל המבוגרת לצעירה{day_txt}, לפי מדד.")
    labels["gaps_lede"] = (f"ערך שלילי פירושו שהקבוצה הראשונה (נשים, הגיל המבוגר{day_first}) עומדת "
                           "במדד בשיעור נמוך יותר. כל מדד בשנת המדידה המלאה האחרונה שלו; קבוצות "
                           f"עם פחות מ-{MIN_N} מקרים ולא ידוע לא נכללו.")
    labels["cases_kpi"] = f"מקרים שנמדדו, {y0}-{y1}" if y1 > y0 else f"מקרים שנמדדו ב-{y0}"
    labels["min_n"] = str(MIN_N)
    labels["intro_measures"] = _join(sorted(names))

    summary = (f"מדדי איכות בשירותי האמבולנס (פרה-הוספיטל) לפי מדד, מרחב מד\"א, משמרת, מין "
               f"וגיל: {len(measures)} מדדים, {int(total_n):,} מקרים, {y0}-{y1}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{y0}/{y1}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "score": score_items,
            "trend": {"years": [str(y) for y in all_years], "series": trend_series},
            "volume": {"years": [str(y) for y in all_years], "series": vol_series},
            "monthly": {"x": yms, "series": monthly_series},
            "season": {"months": MONTHS_HE, "names": names, "cells": season_cells,
                       "min": season_min, "max": season_max},
            "providers": {"providers": [_provider_label(p) for p in eligible],
                          "limit": heat_limit,
                          "names": names, "cells": heat_cells},
            "shift": {"names": names, "shifts": shift_names,
                      "series": [shift_series[s] for s in shift_names]},
            "gaps": gaps_chart,
        },
        "tables": {
            "score": score_rows,
            "trend": {"years": [str(y) for y in all_years], "rows": trend_rows},
            "providers": {"names": names, "rows": prov_rows},
            "shift": {"shifts": shift_names, "rows": shift_rows},
            "gaps": gap_rows,
            "day_labels": day_labels,
        },
        "flags": {"season": bool(season_cells), "targets": bool(with_target),
                  "has_met": "met" in kpis},
        "insights": insights,
        "labels": labels,
    }
