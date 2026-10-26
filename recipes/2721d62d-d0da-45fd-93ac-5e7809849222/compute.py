"""מאגר רישיונות רופאים — the Ministry of Health register of licensed physicians.

One row per (licence, specialty certificate): first/last name, licence number,
licence registration date, and — when the doctor holds one — the specialty
certificate number, its registration date and the specialty name. A doctor
without a specialty has one row with the three specialty fields empty; a doctor
with three specialties has three rows. The whole register is republished on
each update, so the page is a snapshot; "now" is the latest date in the register
(its data vintage), never the wall clock. That year is partial unless the
vintage reaches December.

Dates are DMYYYY / DDMMYYYY digit strings (day not zero-padded). Licence
numbers are NOT unique — the numbering was restarted at some point and a few
hundred numbers belong to two different doctors with different licence dates —
so a doctor is keyed by (licence number, licence date). Licence and
certificate numbers are identifiers and never reach the page; names are not
used (the register's substance is the profession, not the people).

The register carries no country of training, gender or employer; the page
says only what the columns support.
"""
import re

import pandas as pd

LRI, RLI, PDI = "\u2066", "\u2067", "\u2069"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
TOP_SPECS = 20
TOP_GAP = 15
TOP_PATHS = 12
TOP_RISE = 12
MIX_TOP = 8
MIX_FROM = 1980
COHORT_FROM = 1960
HEAT_YEARS = 20
YEAR_MIN_COUNT = 10      # the yearly series starts at the first year with this many licences
WINDOW = 5               # years per window in the rising-specialties comparison
NEW_SPEC_YEARS = 10      # "new specialty" = first certificate within this many years
OTHER = "אחר"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _date(s):
    s = s.str.strip()
    ok = s.str.fullmatch(r"\d{7,8}")
    return pd.to_datetime(s.where(ok, "").str.zfill(8).where(ok), format="%d%m%Y", errors="coerce")


def _ranked(s):
    """Descending by value, ties broken by index (name) — a total order."""
    return s.sort_index(kind="stable").sort_values(ascending=False, kind="stable")


def _signed(ch, digits=0):
    r = round(ch * 100, digits)
    if r == 0:
        return "ללא שינוי"
    return f"{'עלייה' if r > 0 else 'ירידה'} של {pct(abs(r), digits)}"


def _prepare(raw):
    df = pd.DataFrame({
        "lic": raw["מספר רישיון רופא"].str.strip().values,
        "ld": _date(raw["תאריך רישום רישיון"]).values,
        "sd": _date(raw["תאריך רישום התמחות"]).values,
        "spec": raw["שם התמחות"].map(lambda s: re.sub(r"\s+", " ", s.strip())).values,
    })
    bad = int(df["ld"].isna().sum())
    df = df[df["ld"].notna()].copy()
    df["key"] = df["lic"] + "|" + df["ld"].dt.strftime("%Y%m%d")
    docs = (df.sort_values(["key"], kind="stable").drop_duplicates("key")[["key", "ld"]]
            .reset_index(drop=True))
    docs["ly"] = docs["ld"].dt.year
    sp = df[df["spec"] != ""].copy()
    # One doctor listing the same specialty twice (exact or re-issued) counts once — the earliest.
    sp = (sp.sort_values(["key", "spec", "sd"], na_position="last", kind="stable")
          .drop_duplicates(["key", "spec"]).reset_index(drop=True))
    sp["sy"] = sp["sd"].dt.year
    sp["gap"] = (sp["sd"] - sp["ld"]).dt.days / 365.25
    return docs, sp, bad


# ---------------------------------------------------------------- insights

def insight_ytd(docs, asof, partial):
    y = asof.year
    if partial:
        md = (docs["ld"].dt.month * 100 + docs["ld"].dt.day) <= (asof.month * 100 + asof.day)
        cur = int(((docs["ly"] == y) & md).sum())
        prev = int(((docs["ly"] == y - 1) & md).sum())
        full_prev = int((docs["ly"] == y - 1).sum())
        if prev < 100:
            return None
        ch = cur / prev - 1
        s = (f"מתחילת {y} ועד {d_he(asof)} נרשמו {n(cur)} רישיונות רופא חדשים — "
             f"{_signed(ch)} לעומת התקופה המקבילה ב-{y - 1} ({n(prev)})")
        best = docs[docs["ly"] < y].groupby("ly").size()
        if not best.empty and cur > int(best.max()):
            s += f", וכבר יותר מבכל שנה שלמה קודמת (השיא הקודם: {n(best.max())} ב-{int(_ranked(best).index[0])})"
        elif full_prev:
            s += f"; בכל {y - 1} נרשמו {n(full_prev)}"
        return s + "."
    cur = int((docs["ly"] == y).sum())
    prev = int((docs["ly"] == y - 1).sum())
    if prev < 100:
        return None
    return f"ב-{y} נרשמו {n(cur)} רישיונות רופא חדשים — {_signed(cur / prev - 1)} לעומת {y - 1} ({n(prev)})."


def insight_decade(per_year, last_full):
    a = per_year[(per_year.index > last_full - 10) & (per_year.index <= last_full)]
    b = per_year[(per_year.index > last_full - 20) & (per_year.index <= last_full - 10)]
    if b.sum() < 500:
        return None
    va, vb = int(a.sum()), int(b.sum())
    ch = va / vb - 1
    if abs(ch) < 0.05:
        return (f"בעשור {last_full - 9}–{last_full} נרשמו {n(va)} רישיונות רופא, בדומה לעשור "
                f"שקדם לו ({n(vb)}).")
    word = f"פי {va / vb:.1f} מאשר" if ch >= 0.5 else ("יותר מאשר" if ch > 0 else "פחות מאשר")
    return (f"בעשור {last_full - 9}–{last_full} נרשמו {n(va)} רישיונות רופא — {word} בעשור "
            f"{last_full - 19}–{last_full - 10} ({n(vb)}).")


def insight_waves(per_year, last_full):
    """The sharpest single-year jumps over the preceding five-year mean, from separate episodes."""
    rows = []
    for y in per_year.index:
        if y > last_full:
            continue
        prev = [per_year.get(y - k, 0) for k in range(1, 6)]
        m = sum(prev) / 5
        if m < 100:
            continue
        rows.append((y, per_year[y] / m, m))
    rows = [r for r in rows if r[1] >= 1.5]
    if not rows:
        return None
    rows.sort(key=lambda r: (-r[1], r[0]))
    picked = []
    for r in rows:
        if all(abs(r[0] - p[0]) >= 10 for p in picked):
            picked.append(r)
        if len(picked) == 2:
            break
    picked.sort(key=lambda r: r[0])
    parts = [f"ב-{y} נרשמו {n(per_year[y])} רישיונות, פי {ratio:.1f} מממוצע חמש השנים שקדמו ({n(round(m))})"
             for y, ratio, m in picked]
    head = "שתי קפיצות חדות בולטות בקצב הרישוי: " if len(picked) == 2 else "הקפיצה החדה ביותר בקצב הרישוי: "
    return head + "; ".join(parts) + "."


def insight_young(docs, asof):
    tot = len(docs)
    recent = int((docs["ly"] > asof.year - 10).sum())
    if tot < 1000:
        return None
    share = recent / tot
    if share < 0.25:
        return None
    return (f"המרשם צעיר: {n(recent)} מתוך {n(tot)} הרופאים במאגר ({pct(share * 100)}) קיבלו "
            f"רישיון ב-{asof.year - 9}–{asof.year}.")


def insight_leader(doc_spec, n_specialists):
    if doc_spec.empty or n_specialists == 0:
        return None
    top = doc_spec.head(3)
    (a, va), (b, vb), (c, vc) = list(top.items())
    if va < 1.2 * vb:
        return None
    return (f"ההתמחות הנפוצה ביותר היא {a}, עם {n(va)} רופאים ({pct(va / n_specialists * 100)} מבעלי "
            f"ההתמחות), ואחריה {b} ({n(vb)}) ו{c} ({n(vc)}).")


def insight_rising(rise, w_new, w_old, tot_ch):
    if len(rise) < 4:
        return None
    hi = rise[0]
    lo = rise[-1]
    if hi["ch"] - lo["ch"] < 0.3:
        return None
    return (f"תעודות ההתמחות שניתנו ב-{w_new} לעומת {w_old}: {_signed(tot_ch)} בסך הכול. "
            f"הצמיחה המהירה ביותר מבין ההתמחויות הגדולות — {hi['name']} ({n(hi['old'])} ← {n(hi['new'])}, "
            f"{_signed(hi['ch'])}); האיטית ביותר — {lo['name']} ({n(lo['old'])} ← {n(lo['new'])}, "
            f"{_signed(lo['ch'])}).")


def insight_pipeline(docs, first_gap, asof):
    lo, hi = asof.year - 30, asof.year - 11
    m = docs[(docs["ly"] >= lo) & (docs["ly"] <= hi)]
    if len(m) < 1000:
        return None
    share = m["has"].mean()
    g = first_gap[(first_gap["ly"] >= lo) & (first_gap["ly"] <= hi) & (first_gap["gap"] >= 0)]["gap"]
    if len(g) < 200:
        return None
    rec = docs[docs["ly"] > asof.year - 5]
    s = (f"מבין הרופאים שקיבלו רישיון ב-{lo}–{hi}, {pct(share * 100)} רשומים כיום כבעלי התמחות, "
         f"ובחציון עברו {g.median():.1f} שנים מהרישיון ועד תעודת ההתמחות הראשונה")
    if len(rec) >= 200:
        s += (f"; בקרב מי שקיבלו רישיון ב-{asof.year - 4}–{asof.year} השיעור הוא {pct(rec['has'].mean() * 100)} "
              f"בלבד — רובם עדיין בשלבי התמחות")
    return s + "."


def insight_paths(paths, n_specialists, n_multi):
    if paths.empty or n_multi < 100:
        return None
    (a, b), v = paths.index[0], int(paths.iloc[0])
    return (f"ל-{n(n_multi)} רופאים ({pct(n_multi / n_specialists * 100)} מבעלי ההתמחות) רשומה יותר "
            f"מהתמחות אחת. המסלול הנפוץ ביותר הוא מ{a} ל{b} ({n(v)} רופאים).")


def insight_slowest(gap_tbl):
    big = [r for r in gap_tbl if r["count"] >= 100]
    if len(big) < 5:
        return None
    big = sorted(big, key=lambda r: (-r["med"], r["name"]))
    a, b = big[0], big[-1]
    if a["med"] - b["med"] < 2:
        return None
    return (f"הדרך להתמחות ארוכה במיוחד ב{a['name']}: חציון של {a['med']:.1f} שנים מהרישיון ועד התעודה, "
            f"לעומת {b['med']:.1f} שנים ב{b['name']} — המהירה מבין ההתמחויות שיש בהן {n(100)} תעודות ומעלה.")


def insight_newest(first_cert, asof):
    new = first_cert[first_cert.dt.year > asof.year - NEW_SPEC_YEARS]
    if new.empty:
        return None
    new = new.sort_values(kind="stable")
    names = list(new.index[-3:])[::-1]
    head = (f"{n(len(new))} תחומי התמחות קיבלו את תעודתם הראשונה במאגר מאז {asof.year - NEW_SPEC_YEARS + 1}"
            if len(new) > 1 else f"תחום התמחות אחד קיבל את תעודתו הראשונה במאגר מאז {asof.year - NEW_SPEC_YEARS + 1}")
    return head + f"; האחרונים שבהם: " + "; ".join(f"{nm} ({new[nm].year})" for nm in names) + "."


def insight_quality(n_neg, n_certs, bad):
    if n_neg < 20 and bad == 0:
        return None
    s = (f"ב-{n(n_neg)} תעודות התמחות ({pct(n_neg / n_certs * 100, 1)}) תאריך התעודה קודם לתאריך רישום "
         f"הרישיון — ככל הנראה הכרה בהתמחות שנרכשה לפני הרישיון הנוכחי או תיעוד חלקי; הן אינן נכללות "
         f"בחישובי משך הזמן עד להתמחות")
    if bad:
        s += f", ו-{n(bad)} רשומות ללא תאריך רישיון תקין אינן נכללות בעמוד"
    return s + "."


# ---------------------------------------------------------------- compute

def _period(y, start, step=5):
    p = start + ((y - start) // step) * step
    return p


def compute(frames):
    raw = frames["doctors"]
    docs, sp, bad = _prepare(raw)
    asof = max(docs["ld"].max(), sp["sd"].max() if sp["sd"].notna().any() else docs["ld"].max())
    last = asof.year
    partial = asof.month < 12
    last_full = last - 1 if partial else last

    total = len(docs)
    has = set(sp["key"])
    docs["has"] = docs["key"].isin(has)
    n_specialists = int(docs["has"].sum())
    per_doc = sp.groupby("key").size()
    n_multi = int((per_doc >= 2).sum())

    # ---- yearly licences + certificates
    per_year = docs.groupby("ly").size().sort_index()
    certs_year = sp.dropna(subset=["sy"]).groupby("sy").size()
    certs_year.index = certs_year.index.astype(int)
    big_years = per_year[per_year >= YEAR_MIN_COUNT]
    y0 = int(big_years.index.min()) if not big_years.empty else int(per_year.index.min())
    years = list(range(y0, last + 1))
    early = int(per_year[per_year.index < y0].sum())
    charts = {}
    charts["years"] = {
        "x": [str(y) for y in years],
        "lic": [int(per_year.get(y, 0)) for y in years],
        "cert": [int(certs_year.get(y, 0)) for y in years],
        "zoom_from": str(max(y0, last - 49)),
    }

    # ---- month x year heatmap
    hy = list(range(last - HEAT_YEARS + 1, last + 1))
    hm = docs[docs["ly"] >= hy[0]].groupby([docs["ly"], docs["ld"].dt.month]).size()
    cells = []
    for yi, y in enumerate(hy):
        for m in range(1, 13):
            if y == last and m > asof.month:
                continue
            cells.append([m - 1, yi, int(hm.get((y, m), 0))])
    charts["heat"] = {"x": MONTHS_SHORT, "y": [str(y) for y in hy], "cells": cells,
                      "max": max([c[2] for c in cells] + [1])}
    mon = docs[docs["ly"] >= hy[0]]["ld"].dt.month.value_counts()
    mon_r = _ranked(mon)
    peak_m, peak_v = int(mon_r.index[0]), int(mon_r.iloc[0])

    # ---- specialties: doctors per specialty
    doc_spec = _ranked(sp.groupby("spec")["key"].nunique())
    top_specs = doc_spec.head(TOP_SPECS)
    charts["specs"] = {"names": list(top_specs.index)[::-1], "values": [int(v) for v in top_specs.values][::-1]}
    n_fields = int(len(doc_spec))

    # ---- number of specialties per doctor
    cnt = per_doc.reindex(docs["key"]).fillna(0).astype(int)
    nb = cnt.clip(upper=3).value_counts()
    nspec_names = ["ללא התמחות", "התמחות אחת", "שתי התמחויות", "שלוש ומעלה"]
    nspec_vals = [int(nb.get(i, 0)) for i in range(4)]
    charts["nspec"] = {"names": nspec_names, "values": nspec_vals,
                       "colors": ["#c3cfe7", "#0068f5", "#0b3668", "#198754"]}

    # ---- cohort pipeline: share specialised by licence cohort
    first = (sp[sp["gap"].notna()].sort_values(["key", "sd", "spec"], kind="stable")
             .drop_duplicates("key")[["key", "gap"]].merge(docs[["key", "ly"]], on="key"))
    mature_to = last - 11   # cohorts younger than this are still mid-residency (censored)
    cohorts = []
    for p in range(COHORT_FROM, last + 1, 5):
        c = docs[(docs["ly"] >= p) & (docs["ly"] < p + 5)]
        if c.empty:
            continue
        g = first[(first["ly"] >= p) & (first["ly"] < p + 5) & (first["gap"] >= 0)]["gap"]
        hi_y = min(p + 4, last)
        cohorts.append({"name": f"{p}–{hi_y}" if hi_y > p else str(p), "count": len(c),
                        "share": round(c["has"].mean() * 100, 1),
                        "med": round(float(g.median()), 1) if len(g) >= 20 and p + 4 <= mature_to else None})
    charts["cohorts"] = {"x": [c["name"] for c in cohorts], "count": [c["count"] for c in cohorts],
                         "share": [c["share"] for c in cohorts], "med": [c["med"] for c in cohorts]}

    # ---- years from licence to each certificate, per specialty
    ok = sp[sp["gap"] >= 0]
    n_neg = int((sp["gap"] < 0).sum())
    n_certs = int(sp["gap"].notna().sum())
    gq = ok.groupby("spec")["gap"].agg(["size", "median",
                                         lambda x: x.quantile(0.25), lambda x: x.quantile(0.75)])
    gq.columns = ["count", "med", "q1", "q3"]
    gtop = [s for s in doc_spec.index if s in gq.index][:TOP_GAP]
    gap_tbl = [{"name": s, "count": int(gq.loc[s, "count"]), "med": round(float(gq.loc[s, "med"]), 1),
                "q1": round(float(gq.loc[s, "q1"]), 1), "q3": round(float(gq.loc[s, "q3"]), 1)}
               for s in gtop]
    gap_sorted = sorted(gap_tbl, key=lambda r: (r["med"], r["name"]))
    charts["gap"] = {"names": [r["name"] for r in gap_sorted][::-1],
                     "q1": [r["q1"] for r in gap_sorted][::-1],
                     "span": [round(r["q3"] - r["q1"], 1) for r in gap_sorted][::-1],
                     "med": [r["med"] for r in gap_sorted][::-1]}
    gap_all = [{"name": s, "count": int(gq.loc[s, "count"]), "med": float(gq.loc[s, "med"])}
               for s in gq.index]

    # ---- pathways (consecutive specialties per doctor)
    ss = sp.dropna(subset=["sd"]).sort_values(["key", "sd", "spec"], kind="stable").copy()
    ss["prev"] = ss.groupby("key")["spec"].shift()
    pp = ss.dropna(subset=["prev"]).groupby(["prev", "spec"]).size()
    paths = pp.sort_index().sort_values(ascending=False, kind="stable")
    ptop = paths.head(TOP_PATHS)
    # RLI…PDI: ECharts draws canvas labels left-to-right; isolate so the arrow reads first → next.
    charts["paths"] = {"names": [f"{RLI}{a} ← {b}{PDI}" for a, b in ptop.index][::-1],
                       "values": [int(v) for v in ptop.values][::-1]}

    # ---- rising specialties: last WINDOW complete years vs the WINDOW before
    wn = (last_full - WINDOW + 1, last_full)
    wo = (last_full - 2 * WINDOW + 1, last_full - WINDOW)
    rn = sp[(sp["sy"] >= wn[0]) & (sp["sy"] <= wn[1])]["spec"].value_counts()
    ro = sp[(sp["sy"] >= wo[0]) & (sp["sy"] <= wo[1])]["spec"].value_counts()
    tot_ch = (rn.sum() / ro.sum() - 1) if ro.sum() else 0.0
    big = _ranked(rn[rn >= 50]).head(TOP_RISE)
    rise = []
    for s, v in big.items():
        o = int(ro.get(s, 0))
        if o >= 30:
            rise.append({"name": s, "new": int(v), "old": o, "ch": v / o - 1})
    rise.sort(key=lambda r: (-r["ch"], r["name"]))
    w_new = f"{wn[0]}–{wn[1]}"
    w_old = f"{wo[0]}–{wo[1]}"
    charts["rise"] = {"names": [r["name"] for r in rise][::-1], "old": [r["old"] for r in rise][::-1],
                      "new": [r["new"] for r in rise][::-1], "w_old": w_old, "w_new": w_new}

    # ---- specialty mix of new certificates by five-year period (100%)
    mix_specs = list(_ranked(sp[sp["sy"] >= MIX_FROM]["spec"].value_counts()).head(MIX_TOP).index)
    mp = sp[sp["sy"] >= MIX_FROM].copy()
    mp["p"] = mp["sy"].astype(int).map(lambda y: _period(y, MIX_FROM))
    mp["g"] = mp["spec"].where(mp["spec"].isin(mix_specs), OTHER)
    mt = mp.groupby(["p", "g"]).size().unstack(fill_value=0)
    cols = mix_specs + [OTHER]
    mt = mt.reindex(columns=cols, fill_value=0).sort_index()
    plabels = []
    for p in mt.index:
        hi_y = min(p + 4, last)
        lab = f"{p}–{hi_y}" if hi_y > p else str(p)
        if hi_y == last and partial:
            lab += "*"
        plabels.append(lab)
    shares = mt.div(mt.sum(axis=1), axis=0) * 100
    charts["mix"] = {"x": plabels,
                     "series": [{"name": c, "data": [round(float(v), 1) for v in shares[c].values],
                                 "ci": i} for i, c in enumerate(cols)]}
    fm = mt.index[0] if len(mt) else MIX_FROM
    lm = mt.index[-1] if len(mt) else MIX_FROM
    fam_share = ("רפואת המשפחה", float(shares.loc[fm].get("רפואת המשפחה", 0)),
                 float(shares.loc[lm].get("רפואת המשפחה", 0))) if len(mt) else None

    # ---- newest specialties
    first_cert = sp.dropna(subset=["sd"]).groupby("spec")["sd"].min()
    newest = first_cert.sort_index(kind="stable").sort_values(ascending=False, kind="stable").head(10)
    newest_rows = [{"name": s, "date": d_he(d), "count": int(doc_spec.get(s, 0))} for s, d in newest.items()]

    # ---- insights
    rules = [
        ("ytd", insight_ytd(docs, asof, partial)),
        ("decade", insight_decade(per_year, last_full)),
        ("waves", insight_waves(per_year, last_full)),
        ("young", insight_young(docs, asof)),
        ("leader", insight_leader(doc_spec, n_specialists)),
        ("pipeline", insight_pipeline(docs, first, asof)),
        ("rising", insight_rising(rise, w_new, w_old, tot_ch)),
        ("paths", insight_paths(paths, n_specialists, n_multi)),
        ("slowest", insight_slowest(gap_all)),
        ("newest", insight_newest(first_cert, asof)),
        ("quality", insight_quality(n_neg, n_certs, bad)),
    ]
    insights = [{"id": k, "text_he": t} for k, t in rules if t]

    # ---- KPIs
    md = (docs["ld"].dt.month * 100 + docs["ld"].dt.day) <= (asof.month * 100 + asof.day)
    cur_lic = int((docs["ly"] == last).sum())
    prev_same = int(((docs["ly"] == last - 1) & (md if partial else True)).sum())
    lic_tone = "brand"
    if prev_same >= 100:
        ch = cur_lic / prev_same - 1
        lic_tone = "ok" if ch >= 0.05 else ("warn" if ch <= -0.05 else "brand")
    cur_cert = int(certs_year.get(last, 0))
    sd_md = (sp["sd"].dt.month * 100 + sp["sd"].dt.day) <= (asof.month * 100 + asof.day)
    prev_cert = int(((sp["sy"] == last - 1) & (sd_md if partial else True)).sum())
    cert_tone = "brand"
    if prev_cert >= 100:
        ch = cur_cert / prev_cert - 1
        cert_tone = "ok" if ch >= 0.05 else ("warn" if ch <= -0.05 else "brand")
    fg = first[(first["gap"] >= 0) & (first["ly"] <= mature_to)]["gap"]
    med_all = float(fg.median()) if len(fg) else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "new": {"value": cur_lic, "display": n(cur_lic), "tone": lic_tone},
        "certs": {"value": cur_cert, "display": n(cur_cert), "tone": cert_tone},
        "share": {"value": round(n_specialists / total * 100, 1),
                  "display": f"{n_specialists / total * 100:.1f}%", "tone": "info"},
        "fields": {"value": n_fields, "display": n(n_fields), "tone": "brand"},
        "median": {"value": round(med_all, 1), "display": f"{med_all:.1f}", "tone": "info"},
    }

    asof_s = d_he(asof)
    ytd_tail = f" (עד {asof_s})" if partial else ""
    lede = (f"מרשם רישיונות הרופאים של משרד הבריאות מונה {n(total)} רופאים שקיבלו רישיון "
            f"מ-{int(per_year.index.min())} ועד {asof_s}. ל-{n(n_specialists)} מהם ({pct(n_specialists / total * 100)}) "
            f"רשומה לפחות תעודת התמחות אחת, מתוך {n(n_fields)} תחומי התמחות. המרשם אינו כולל ארץ לימודים, "
            f"מגדר או מקום עבודה, ולכן העמוד מתמקד בקצב הרישוי, במסלולי ההתמחות ובזמן שהם אורכים. "
            f"מספרי רישיון ותעודה אינם מוצגים.")
    lw = per_year[per_year.index <= last_full]
    peak_y = int(_ranked(lw).index[0]) if not lw.empty else last
    labels = {
        "lede": lede,
        "total_kpi": "רופאים במרשם",
        "new_kpi": f"רישיונות חדשים ב-{last}{ytd_tail}",
        "certs_kpi": f"תעודות התמחות ב-{last}{ytd_tail}",
        "share_kpi": "שיעור בעלי התמחות",
        "fields_kpi": "תחומי התמחות",
        "median_kpi": f"שנים בחציון מרישיון להתמחות ראשונה (רישיונות עד {mature_to})",
        "years_note": (f"רישיונות רופא חדשים ותעודות התמחות לפי שנת רישום, {y0}–{last}"
                       + (f" ({last} חלקית, עד {asof_s})" if partial else "")
                       + (f". {n(early)} רישיונות מלפני {y0} אינם מוצגים בגרף" if early else "")
                       + f". שנת השיא המלאה ברישוי: {peak_y} ({n(per_year.get(peak_y, 0))})."),
        "years_aria": (f"גרף עמודות וקו: רישיונות רופא ותעודות התמחות לפי שנה, {y0} עד {last}. "
                       f"שיא ברישוי ב-{peak_y}."),
        "heat_note": (f"רישיונות חדשים לפי חודש רישום, {hy[0]}–{last}. החודש העמוס ביותר בתקופה: "
                      f"{MONTHS_HE[peak_m - 1]} ({n(peak_v)} רישיונות, {pct(peak_v / max(int(mon.sum()), 1) * 100)})."),
        "heat_aria": f"מפת חום: רישיונות רופא לפי חודש ושנה, {hy[0]} עד {last}.",
        "specs_note": (f"{TOP_SPECS} תחומי ההתמחות עם מספר הרופאים הגדול ביותר, מתוך {n(n_fields)} תחומים. "
                       f"רופא בעל כמה התמחויות נספר בכל אחת מהן."),
        "specs_aria": (f"תרשים עמודות אופקי: {TOP_SPECS} תחומי ההתמחות הגדולים — {doc_spec.index[0]} בראש "
                       f"עם {n(doc_spec.iloc[0])} רופאים."),
        "specs_caption": "מספר רופאים לפי תחום התמחות.",
        "nspec_note": (f"{n(nspec_vals[0])} רופאים ({pct(nspec_vals[0] / total * 100)}) רשומים ללא התמחות — "
                       f"בהם מתמחים, רופאים כלליים ורופאים שלא השלימו התמחות; {n(n_multi)} רשומים עם שתיים ומעלה."),
        "nspec_aria": f"תרשים טבעת: רופאים לפי מספר ההתמחויות, {n(n_specialists)} עם התמחות.",
        "nspec_caption": "רופאים לפי מספר תעודות ההתמחות.",
        "cohort_note": (f"לכל מחזור רישוי (חמש שנים): שיעור הרופאים שרשומים כיום כבעלי התמחות, וחציון השנים "
                        f"מהרישיון ועד התעודה הראשונה. השיעור במחזורים האחרונים נמוך כי חבריהם עדיין בהתמחות, והחציון מוצג רק למחזורים שהסתיימו עד {mature_to}."),
        "cohort_aria": f"גרף עמודות וקו: שיעור בעלי ההתמחות לפי מחזור רישוי, {cohorts[0]['name']} עד {cohorts[-1]['name']}.",
        "cohort_caption": "רופאים, שיעור בעלי התמחות וחציון שנים עד התמחות לפי מחזור רישוי.",
        "gap_note": (f"השנים מרישום הרישיון ועד רישום תעודת ההתמחות, ב-{TOP_GAP} התחומים הגדולים: הפס מראה את "
                     f"המחצית האמצעית (רבעון ראשון עד שלישי) והנקודה את החציון. תתי-התמחויות מגיעות "
                     f"מאוחר יותר כי הן נבנות על התמחות בסיס."
                     + (f" {n(n_neg)} תעודות שתאריכן קודם לרישיון אינן נכללות." if n_neg else "")),
        "gap_aria": "תרשים טווחים אופקי: שנים מרישיון להתמחות לפי תחום, רבעונים וחציון.",
        "gap_caption": "שנים מרישיון לתעודת התמחות לפי תחום: חציון ורבעונים.",
        "paths_note": (f"{TOP_PATHS} המעברים הנפוצים בין התמחות אחת לבאה אחריה אצל אותו רופא (לפי סדר "
                       f"התעודות) — רובם התמחות בסיס ואחריה תת-התמחות."),
        "paths_aria": f"תרשים עמודות אופקי: {TOP_PATHS} מסלולי ההתמחות הנפוצים.",
        "paths_caption": "מספר רופאים לפי מעבר בין התמחויות.",
        "rise_note": (f"תעודות התמחות שניתנו ב-{w_new} לעומת {w_old}, בתחומים הגדולים; סך כל התעודות: "
                      f"{_signed(tot_ch)}."),
        "rise_aria": f"תרשים עמודות אופקי: תעודות התמחות לפי תחום, {w_old} מול {w_new}.",
        "rise_caption": f"תעודות התמחות לפי תחום, {w_old} מול {w_new}.",
        "mix_note": (f"התפלגות תעודות ההתמחות החדשות לפי תחום, בתקופות של חמש שנים מ-{MIX_FROM}; "
                     f"{MIX_TOP} התחומים הגדולים ו\"אחר\"."
                     + (f" * {last} חלקית." if partial else "")
                     + (f" חלקה של רפואת המשפחה: {pct(fam_share[1])} ב-{plabels[0].rstrip('*')} ו-{pct(fam_share[2])} ב-{plabels[-1].rstrip('*')}."
                        if fam_share and "רפואת המשפחה" in mix_specs else "")),
        "mix_aria": f"עמודות מוערמות 100%: תמהיל תעודות ההתמחות לפי תקופה, {plabels[0]} עד {plabels[-1]}.",
        "mix_caption": "אחוז תעודות ההתמחות לפי תחום ותקופה.",
        "newest_note": "תחומי ההתמחות שתעודתם הראשונה במאגר היא החדשה ביותר — מסלולים שנפתחו או פוצלו לאחרונה.",
        "newest_caption": "תחומי ההתמחות החדשים: תאריך התעודה הראשונה ומספר רופאים.",
    }

    tables = {
        "specs": [{"name": s, "count": n(v), "share": f"{v / n_specialists * 100:.1f}%"} for s, v in top_specs.items()],
        "nspec": [{"name": a, "count": n(b), "share": f"{b / total * 100:.1f}%"} for a, b in zip(nspec_names, nspec_vals)],
        "cohorts": [{"name": c["name"], "count": n(c["count"]), "share": f"{c['share']:.1f}%",
                     "med": "—" if c["med"] is None else f"{c['med']:.1f}"} for c in cohorts],
        "gap": [{"name": r["name"], "med": f"{r['med']:.1f}", "q1": f"{r['q1']:.1f}", "q3": f"{r['q3']:.1f}",
                 "count": n(r["count"])} for r in sorted(gap_tbl, key=lambda r: (r["med"], r["name"]))],
        "paths": [{"name": f"{a} ← {b}", "count": n(v)} for (a, b), v in ptop.items()],
        "rise": [{"name": r["name"], "old": n(r["old"]), "new": n(r["new"]),
                  "ch": "0%" if round(r["ch"] * 100) == 0 else f"{r['ch'] * 100:+.0f}%".replace("-", "−")}
                 for r in rise],
        "mix_cols": cols,
        "mix": [{"name": plabels[i], "vals": [f"{shares.iloc[i][c]:.1f}%" for c in cols]} for i in range(len(plabels))],
        "newest": newest_rows,
    }

    return {
        "agent_data": {
            "summary_he": (f"מרשם רישיונות הרופאים בישראל: {n(total)} רופאים, מהם {n(n_specialists)} בעלי "
                           f"התמחות ב-{n(n_fields)} תחומים — קצב הרישוי מ-{y0}, מסלולי ההתמחות והזמן שהם אורכים."),
            "dataset_kind": "registry",
            "related_ids": ["54601127-7b82-4bd7-ad80-271a802fdeeb",
                            "72662d34-ce69-4990-8504-ee0860529e7d",
                            "9f0ea3dc-2e25-43f0-9b8f-10f53e23c335",
                            "b54ae5a7-1bd5-4e7f-8b9d-f367f8eefd65",
                            "7b840685-b166-46aa-9612-883bc9d2b91e"],
            "suggested_tags": ["רופאים", "רישוי רפואי", "התמחויות רפואיות", "מקצועות הרפואה", "משרד הבריאות"],
            "temporal_coverage": f"{int(per_year.index.min())}/{asof.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"partial": partial, "has_newest": bool(newest_rows)},
    }
