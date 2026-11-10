"""מדד מחירי ירקות ופירות: CBS consumer price indices of selected fresh produce.

Inputs (all from the CBS Index API, one row per code and month):
  groups      CPI components: general CPI (120010), fruit and vegetables
              (120040), fresh vegetables (120042), fresh fruit (120043),
              preserved vegetables (120046), dried/preserved fruit (120047).
  vegetables, fruit, seasonal, late, potatoes
              item indices of fresh vegetables and fruit (subject 41,
              excluding VAT).
  preserved   pickles, tomato paste, olives, nuts, seeds, dried fruit
              (subject 41, including VAT).

Charts use VALUE_CHAINED (every row of a code on its newest base); quoted
changes are CBS's published PERCENT (m/m) and PERCENT_YEAR (y/y). An item
can start late (potatoes from 2025), lag a month or skip months (seasonal
fruit): the latest-month views take only items published for the latest
month and say how many there are; long-run views take each item's own
contiguous chained run.
"""
import math

import pandas as pd
from govlib import fmt, frame

CPI, FV, VEG, FRUIT, VEG_PRES, FRUIT_PRES = 120010, 120040, 120042, 120043, 120046, 120047
GROUP_CODES = (CPI, FV, VEG, FRUIT, VEG_PRES, FRUIT_PRES)
GROUP_LABELS = {
    CPI: "המדד הכללי",
    FV: "ירקות ופירות",
    VEG: "ירקות טריים",
    FRUIT: "פירות טריים",
    VEG_PRES: "ירקות קפואים, כבושים ומשומרים",
    FRUIT_PRES: "פירות יבשים, משומרים וקפואים",
}
VEG_ITEMS = {150050, 150060, 150040, 150110, 150020, 150070, 150100, 150080, 150090,
             150010, 150035, 150119}
FRUIT_ITEMS = {150210, 150170, 150130, 150150, 150160, 150220, 150260, 150265, 150250,
               150200, 150190, 150230, 150240, 150145}
OTHER_ITEMS = {150270, 150280, 150310, 150320, 150330, 150340, 150350, 150370}
# An unknown code takes its kind from the input it came in.
INPUT_KIND = {"vegetables": "veg", "potatoes": "veg", "fruit": "fruit", "seasonal": "fruit",
              "late": "veg", "preserved": "other", "groups": "group"}
KIND_HE = {"veg": "ירקות טריים", "fruit": "פירות טריים", "other": "שימורים, אגוזים ופירות יבשים"}
SHORT = {150265: "משמש, אפרסמון ומנגו"}
TOMATO = 150050
# Small multiples: the items people look up most, in this order (absent ones skipped).
KEY_ITEMS = (150050, 150060, 150040, 150119, 150035, 150020, 150210, 150170, 150260)
MULTI_MONTHS = 61
HEAT_YEARS = 15
SEASON_YEARS = 10
SEASON_MIN_YEARS = 3
SEASON_MIN_MONTHS = 4
VOL_MONTHS = 120
VOL_MIN_OBS = 60
FLAT = 0.5  # |change| below this many percent reads as "almost unchanged"


# ── parsing ──────────────────────────────────────────────────────────────

def _load(frames):
    parts = []
    for name in sorted(frames):
        d = frames[name].copy()
        d["_input"] = name
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df = df[df["FREQ"].str.strip() == "M"].copy()
    df["code"] = pd.to_numeric(df["CODE"].str.strip(), errors="coerce")
    df["t"] = pd.to_datetime(df["DATE"].str.strip(), format="%Y-%m-%d", errors="coerce")
    df["pct"] = frame.num(df["PERCENT"])
    df["yoy"] = frame.num(df["PERCENT_YEAR"])
    df["v"] = frame.num(df["VALUE_CHAINED"])
    df["name"] = frame.clean_series(df["NAME_HE"])
    df["base"] = frame.clean_series(df["CHAIN_BASE"])
    df = df.dropna(subset=["code", "t"])
    df["code"] = df["code"].astype(int)
    df = df.sort_values(["code", "t", "_input", "name", "v", "pct", "yoy"], kind="stable",
                        na_position="last")
    return df.drop_duplicates(["code", "t"], keep="first").reset_index(drop=True)


def _kind(code, inp):
    if code in GROUP_CODES:
        return "group"
    if code in VEG_ITEMS:
        return "veg"
    if code in FRUIT_ITEMS:
        return "fruit"
    if code in OTHER_ITEMS:
        return "other"
    return INPUT_KIND.get(inp, "other")


def _catalog(df):
    """code → {name, kind}, the name from the code's newest row."""
    out = {}
    for code, g in df.groupby("code", sort=True):
        last = g.iloc[-1]
        name = SHORT.get(code) or last["name"] or str(code)
        if code in GROUP_LABELS:
            name = GROUP_LABELS[code]
        out[int(code)] = {"name": name, "kind": _kind(int(code), last["_input"])}
    return out


def _series(df, code, col):
    g = df[df["code"] == code][["t", col]].dropna()
    return g.set_index("t")[col]


def _chained_run(df, code):
    """The newest contiguous run of VALUE_CHAINED (a break CBS can't link
    leaves earlier rows blank)."""
    g = df[df["code"] == code][["t", "v"]].set_index("t")["v"]
    if g.empty:
        return g
    blank = g.isna()
    if blank.any():
        last_blank = blank[blank].index.max()
        g = g[g.index > last_blank]
    return g.dropna()


# ── text helpers ─────────────────────────────────────────────────────────

def _sp(v, digits=1):
    """A published change on 0-100 as signed text: +3.4%, −3.4%, 0.0%."""
    body = f"{abs(v):.{digits}f}"
    if float(body) == 0:
        return f"{body}%"
    return ("+" if v > 0 else fmt.MINUS) + body + "%"


def _iso(t):
    return fmt.isolate(t)


def _month(t):
    return fmt.month_he(t)


def _ym(t):
    return f"{t.year}-{t.month:02d}"


def _r(v, digits=1):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), digits)


def _move(v):
    """'עלייה של +3.4%' / 'ירידה של −3.4%' / 'כמעט ללא שינוי (+0.2%)'."""
    if abs(v) < FLAT:
        return f"כמעט ללא שינוי ({_iso(_sp(v))})"
    return f"{'עלייה' if v > 0 else 'ירידה'} של {_iso(_sp(v))}"


def _tone_change(v):
    if v >= 5:
        return "danger"
    if v > FLAT:
        return "warn"
    if v <= -FLAT:
        return "ok"
    return "brand"


# ── views ────────────────────────────────────────────────────────────────

def _full_years(s):
    """Calendar years with all 12 months in a series → {year: mean}."""
    if s.empty:
        return {}
    g = s.groupby(s.index.year)
    counts, means = g.size(), g.mean()
    return {int(y): float(means[y]) for y in counts.index if counts[y] == 12}


def _latest_items(df, cat, L, kinds):
    rows = df[(df["t"] == L) & df["code"].map(lambda c: cat.get(c, {}).get("kind") in kinds)]
    out = []
    for _, r in rows.iterrows():
        c = int(r["code"])
        out.append({"code": c, "name": cat[c]["name"], "kind": cat[c]["kind"],
                    "yoy": None if pd.isna(r["yoy"]) else float(r["yoy"]),
                    "pct": None if pd.isna(r["pct"]) else float(r["pct"])})
    return out


def _seasonal(df, code, L):
    """Average published monthly change (PERCENT) per calendar month over the
    last SEASON_YEARS years up to L. PERCENT is base-free, so this spans
    CBS's rebases (item indices are re-defined at each one)."""
    s = _series(df, code, "pct")
    s = s[(s.index <= L) & (s.index > L - pd.DateOffset(years=SEASON_YEARS))]
    if s.empty:
        return None
    by_m = s.groupby(s.index.month)
    means, counts = by_m.mean(), by_m.size()
    prof = [None] * 12
    for m in means.index:
        if counts[m] >= SEASON_MIN_YEARS:
            prof[int(m) - 1] = float(means[m])
    vals = [(v, i) for i, v in enumerate(prof) if v is not None]
    if len(vals) < SEASON_MIN_MONTHS:
        return None
    hi = max(vals, key=lambda x: (x[0], -x[1]))
    lo = min(vals, key=lambda x: (x[0], x[1]))
    return {"profile": prof, "peak": hi[1], "peak_v": hi[0], "trough": lo[1], "trough_v": lo[0],
            "amp": hi[0] - lo[0]}


def compute(frames):
    df = _load(frames)
    cat = _catalog(df)
    if df.empty:
        raise ValueError("no monthly rows")
    fresh_kinds = {"veg", "fruit"}
    # The latest month of the item indices (not of the CPI groups), so the
    # per-item views never land on a month the items aren't out for yet.
    fresh_t = df[df["code"].map(lambda c: cat[c]["kind"] in fresh_kinds)]["t"]
    L = fresh_t.max() if not fresh_t.empty else df["t"].max()

    # ── groups ──
    g_last = {}
    for code in GROUP_CODES:
        yy = _series(df, code, "yoy")
        if not yy.empty:
            row = df[(df["code"] == code) & (df["t"] == yy.index.max())].iloc[0]
            g_last[code] = {"t": yy.index.max(), "yoy": float(row["yoy"]),
                            "pct": None if pd.isna(row["pct"]) else float(row["pct"])}

    groups_yoy = []
    for code in (VEG, FRUIT, CPI):
        s = _series(df, code, "yoy")
        if len(s) >= 13:
            groups_yoy.append({"name": GROUP_LABELS[code],
                               "data": [[_ym(t), _r(v)] for t, v in s.items()]})

    # Long run: chained levels rebased to the first year all compared groups cover.
    lr_codes = [c for c in (VEG, FRUIT, FV, CPI) if not _chained_run(df, c).empty]
    fy = {c: _full_years(_chained_run(df, c)) for c in lr_codes}
    common = sorted(set.intersection(*[set(v) for v in fy.values()])) if fy else []
    longrun, lr_table, base_year, real = [], [], None, {}
    if len(common) >= 3 and VEG in fy:
        base_year = common[0]
        for c in lr_codes:
            s = _chained_run(df, c)
            s = s[s.index.year >= base_year] / fy[c][base_year] * 100
            longrun.append({"name": GROUP_LABELS[c], "data": [[_ym(t), _r(v)] for t, v in s.items()]})
        for y in common:
            lr_table.append([str(y)] + [fmt.num_he(fy[c][y] / fy[c][base_year] * 100)
                                        for c in lr_codes])
        last_full = common[-1]
        for c in lr_codes:
            real[c] = (fy[c][last_full] / fy[c][base_year] - 1) * 100

    # Yearly average change per group (full years).
    gy_codes = [c for c in (VEG, FRUIT, CPI) if c in fy or not _chained_run(df, c).empty]
    gy = {c: fy.get(c) or _full_years(_chained_run(df, c)) for c in gy_codes}
    years_tbl = []
    all_years = sorted(set().union(*[set(v) for v in gy.values()])) if gy else []
    for y in all_years:
        cells, ok = [], False
        for c in gy_codes:
            if y in gy[c] and (y - 1) in gy[c]:
                cells.append(_sp((gy[c][y] / gy[c][y - 1] - 1) * 100))
                ok = True
            else:
                cells.append("–")
        if ok:
            years_tbl.append([str(y)] + cells)

    # ── items, latest month ──
    latest = _latest_items(df, cat, L, fresh_kinds)
    fresh_codes = sorted(c for c, v in cat.items() if v["kind"] in fresh_kinds)
    n_fresh = len(fresh_codes)
    rank = sorted([i for i in latest if i["yoy"] is not None],
                  key=lambda i: (-i["yoy"], i["name"], i["code"]))
    mom = sorted([i for i in latest if i["pct"] is not None],
                 key=lambda i: (-i["pct"], i["name"], i["code"]))
    lagging = [cat[c]["name"] for c in fresh_codes if c not in {i["code"] for i in rank}]

    # ── small multiples ──
    window_start = L - pd.DateOffset(months=MULTI_MONTHS - 1)
    months = pd.date_range(window_start, L, freq="MS")
    multi, multi_tbl = [], []
    for code in KEY_ITEMS:
        if code not in cat:
            continue
        s = _chained_run(df, code)
        s = s[(s.index >= window_start) & (s.index <= L)]
        if len(s) < 6:
            continue
        multi.append({"name": cat[code]["name"], "y": [_r(s.get(t)) for t in months]})
        hi_t = s.sort_index().idxmax()
        lo_t = s.sort_index().idxmin()
        multi_tbl.append([cat[code]["name"], _ym(s.index.max()), fmt.num_he(s.iloc[-1]),
                          f"{fmt.num_he(s[lo_t])} ({_ym(lo_t)})",
                          f"{fmt.num_he(s[hi_t])} ({_ym(hi_t)})"])
    multi_x = [_ym(t) for t in months]
    chain_base = ""
    bases = df[df["code"].isin(fresh_codes)]["base"]
    if not bases.empty:
        chain_base = frame.ranked(bases[bases != ""]).index[0] if (bases != "").any() else ""
    # CBS writes the base year first ("2024 ממוצע"); Hebrew prose reads "ממוצע 2024".
    parts = chain_base.split()
    if len(parts) == 2 and parts[0].isdigit():
        chain_base = f"{parts[1]} {parts[0]}"

    # ── seasonality profile ──
    seasons = []
    for code in fresh_codes:
        p = _seasonal(df, code, L)
        if p:
            seasons.append({"code": code, "name": cat[code]["name"], **p})
    seasons.sort(key=lambda s: (-s["amp"], s["name"], s["code"]))
    season_cells = []
    for yi, s in enumerate(seasons):
        for m, v in enumerate(s["profile"]):
            if v is not None:
                season_cells.append([m, yi, _r(v)])
    season_tbl = [[s["name"], fmt.MONTHS_HE[s["peak"]], _sp(s["peak_v"]),
                   fmt.MONTHS_HE[s["trough"]], _sp(s["trough_v"]), fmt.num_he(s["amp"])]
                  for s in seasons]
    season_max = max((abs(c[2]) for c in season_cells), default=1.0)

    # ── vegetables month × year heatmap (m/m) ──
    heat, heat_years, month_avg = [], [], []
    vp = _series(df, VEG, "pct")
    fp = _series(df, FRUIT, "pct")
    if not vp.empty:
        y_last = vp.index.max().year
        heat_years = [y for y in range(y_last - HEAT_YEARS + 1, y_last + 1)
                      if (vp.index.year == y).any()]
        for yi, y in enumerate(heat_years):
            for t, v in vp[vp.index.year == y].items():
                heat.append([t.month - 1, yi, _r(v)])
        win_v = vp[vp.index.year >= heat_years[0]]
        win_f = fp[fp.index.year >= heat_years[0]] if not fp.empty else fp
        for m in range(1, 13):
            a = win_v[win_v.index.month == m]
            b = win_f[win_f.index.month == m] if not win_f.empty else win_f
            month_avg.append({"m": m - 1, "veg": _r(a.mean()) if len(a) else None,
                              "fruit": _r(b.mean()) if len(b) else None})
    heat_max = max((abs(c[2]) for c in heat if c[2] is not None), default=1.0)

    # ── volatility ──
    vol = []
    vol_start = L - pd.DateOffset(months=VOL_MONTHS - 1)
    for code in fresh_codes:
        s = _series(df, code, "pct")
        s = s[s.index >= vol_start]
        if len(s) >= VOL_MIN_OBS:
            vol.append({"name": cat[code]["name"], "sd": float(s.std(ddof=1)),
                        "max": float(s.max()), "min": float(s.min()), "n": len(s)})
    vol.sort(key=lambda v: (-v["sd"], v["name"]))

    # ── long-run change per item (common start year) ──
    item_lr = []
    if base_year is not None:
        last_full = common[-1]
        for code in fresh_codes:
            f = _full_years(_chained_run(df, code))
            if base_year in f and last_full in f:
                item_lr.append({"name": cat[code]["name"], "kind": cat[code]["kind"],
                                "chg": (f[last_full] / f[base_year] - 1) * 100})
        item_lr.sort(key=lambda i: (-i["chg"], i["name"]))

    # ── preserved, nuts ──
    other = sorted([i for i in _latest_items(df, cat, L, {"other"}) if i["yoy"] is not None],
                   key=lambda i: (-i["yoy"], i["name"], i["code"]))
    other_lr = {}
    if base_year is not None:
        for i in other:
            f = _full_years(_chained_run(df, i["code"]))
            if base_year in f and common[-1] in f:
                other_lr[i["code"]] = (f[common[-1]] / f[base_year] - 1) * 100

    # ── KPIs ──
    kpis, labels = {}, {}
    for key, code in (("veg", VEG), ("fruit", FRUIT), ("cpi", CPI)):
        if code in g_last:
            v = g_last[code]["yoy"]
            kpis[key] = {"value": v, "display": _sp(v),
                         "tone": "brand" if code == CPI else _tone_change(v)}
            labels[f"{key}_kpi"] = (f"{GROUP_LABELS[code]}: שינוי ב-12 חודשים "
                                    f"({_month(g_last[code]['t'])})")
    rising = [i for i in rank if i["yoy"] > 0]
    if rank:
        kpis["rising"] = {"value": len(rising), "display": f"{len(rising):,}",
                          "tone": "warn" if len(rising) * 2 > len(rank) else "brand"}
        labels["rising_kpi"] = f"פריטים טריים שהתייקרו בשנה האחרונה, מתוך {len(rank):,}"
        top = rank[0]
        kpis["top"] = {"value": top["yoy"], "display": _sp(top["yoy"]),
                       "tone": _tone_change(top["yoy"])}
        labels["top_kpi"] = f"ההתייקרות השנתית הגדולה ביותר: {top['name']}"

    # ── insights ──
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if VEG in g_last and FRUIT in g_last:
        v, f = g_last[VEG], g_last[FRUIT]
        cpi_txt = ""
        if CPI in g_last and g_last[CPI]["t"] == v["t"]:
            cpi_txt = f", לעומת {_iso(_sp(g_last[CPI]['yoy']))} במדד המחירים לצרכן הכללי"
        add("groups", f"ב-12 החודשים שעד {_month(v['t'])} רשם מדד הירקות הטריים "
            f"{_move(v['yoy'])}, ומדד הפירות הטריים {_move(f['yoy'])}{cpi_txt}."
            if v["t"] == f["t"] else None)
    if len(rank) >= 5:
        hi, lo = rank[0], rank[-1]
        head = (f"מבין {len(rank):,} הירקות והפירות הטריים שמדדם פורסם ל{_month(L)}, "
                f"ההתייקרות השנתית הגדולה ביותר הייתה ב{hi['name']} ({_iso(_sp(hi['yoy']))})")
        if hi["yoy"] > FLAT and lo["yoy"] < -FLAT:
            add("extremes", head + f", והירידה הגדולה ביותר ב{lo['name']} "
                f"({_iso(_sp(lo['yoy']))}).")
        elif hi["yoy"] > FLAT:
            add("extremes", head + ".")
    if len(rank) >= 5:
        share = len(rising) / len(rank)
        if share >= 0.6:
            add("breadth", f"ההתייקרות רחבה: {len(rising):,} מתוך {len(rank):,} הפריטים "
                f"הטריים ({_iso(fmt.pct(share, 0))}) יקרים יותר משהיו לפני שנה.")
        elif share <= 0.4:
            add("breadth", f"רק {len(rising):,} מתוך {len(rank):,} הפריטים הטריים "
                f"({_iso(fmt.pct(share, 0))}) יקרים יותר משהיו לפני שנה; השאר הוזלו או "
                f"לא השתנו.")
    tom = next((i for i in latest if i["code"] == TOMATO), None)
    if tom and tom["yoy"] is not None and tom["pct"] is not None:
        add("tomato", f"מחיר העגבניות ב{_month(L)}: {_move(tom['pct'])} לעומת החודש הקודם, "
            f"ו{_move(tom['yoy'])} לעומת {_month(L - pd.DateOffset(years=1))}.")
    if base_year is not None and VEG in real and CPI in real:
        gap = real[VEG] - real[CPI]
        if abs(gap) >= 5:
            add("longrun", f"בטווח הארוך: הממוצע השנתי של מדד הירקות הטריים עלה בין {base_year} "
                f"ל-{common[-1]} ב-{_iso(fmt.pct_of(real[VEG], 0))}, "
                f"{'יותר' if gap > 0 else 'פחות'} מהמדד הכללי, שעלה "
                f"ב-{_iso(fmt.pct_of(real[CPI], 0))}.")
    if len(vol) >= 5:
        a, z = vol[0], vol[-1]
        add("volatility", f"הפריט התנודתי ביותר: {a['name']}. ב-{VOL_MONTHS:,} החודשים "
            f"האחרונים סטיית התקן של השינוי החודשי במחיר הייתה "
            f"{_iso(fmt.num_he(a['sd']))} נקודות אחוז, לעומת {_iso(fmt.num_he(z['sd']))} "
            f"בלבד ב{z['name']}, הפריט היציב ביותר.")
    if seasons and seasons[0]["peak_v"] >= 3 and seasons[0]["trough_v"] <= -3:
        s = seasons[0]
        add("season", f"העונתיות החזקה ביותר: {s['name']}. ב-{SEASON_YEARS:,} השנים האחרונות "
            f"המחיר עלה בממוצע ב-{_iso(fmt.pct_of(s['peak_v']))} ב{fmt.MONTHS_HE[s['peak']]} "
            f"וירד ב-{_iso(fmt.pct_of(abs(s['trough_v'])))} ב{fmt.MONTHS_HE[s['trough']]}.")
    vals = [(m["veg"], m["m"]) for m in month_avg if m["veg"] is not None]
    if len(vals) == 12:
        hi_m = max(vals, key=lambda x: (x[0], -x[1]))
        lo_m = min(vals, key=lambda x: (x[0], x[1]))
        if hi_m[0] >= 2 and lo_m[0] <= -2:
            add("calendar", f"לירקות הטריים יש לוח שנה קבוע: ב-{len(heat_years):,} השנים האחרונות "
                f"מדד הירקות עלה בממוצע ב-{_iso(fmt.pct_of(hi_m[0]))} ב{fmt.MONTHS_HE[hi_m[1]]} "
                f"וירד ב-{_iso(fmt.pct_of(abs(lo_m[0])))} ב{fmt.MONTHS_HE[lo_m[1]]}.")

    # ── labels, ledes ──
    Lm = _month(L)
    labels["lede"] = (
        f"מדדי המחירים לצרכן של ירקות ופירות מהלשכה המרכזית לסטטיסטיקה: מדדי הקבוצות "
        f"(ירקות טריים, פירות טריים) ומדד נפרד לכל אחד מ-{n_fresh:,} ירקות ופירות טריים, "
        f"לצד שימורים, אגוזים ופירות יבשים. הנתון האחרון הוא של {Lm}. "
        f"מדדי הפריטים אינם כוללים מע\"מ, מלבד מדדי השימורים, האגוזים והפירות היבשים.")
    labels["period"] = Lm
    labels["chain_base"] = chain_base
    labels["chain_note"] = (
        "מדד הוא מחיר יחסי, לא מחיר בשקלים: הוא מראה בכמה השתנה המחיר, לא כמה עולה קילו. "
        "הלמ\"ס מחליפה את בסיס המדד כל שנתיים בערך, ומגדירה מחדש את מדדי הפריטים בכל החלפה. "
        f"הגרפים משתמשים במדד המשורשר לבסיס האחרון ({chain_base} = 100), ולפריט שהשרשור שלו "
        f"נקטע מוצג רק הרצף האחרון. השינויים באחוזים מצוטטים כפי שפורסמו.")
    labels["base_year"] = str(base_year) if base_year else ""
    if groups_yoy:
        labels["groups_yoy_aria"] = (
            "גרף קווים: השינוי ב-12 חודשים במדדי הירקות הטריים, הפירות הטריים והמדד הכללי, "
            f"לכל חודש עד {Lm}.")
    if longrun:
        labels["longrun_note"] = (
            f"רמת המדד, ממוצע {base_year} = 100 (חושב כאן מהמדד המשורשר של הלמ\"ס). "
            f"קו מעל המדד הכללי פירושו שהקבוצה התייקרה יותר מסל הצריכה כולו.")
        labels["longrun_aria"] = (f"גרף קווים: מדדי הירקות הטריים, הפירות הטריים והמדד הכללי "
                                  f"מאז {base_year}, ממוצע {base_year} = 100.")
    if rank:
        labels["rank_note"] = (f"השינוי ב-12 החודשים שעד {Lm}, כפי שפרסמה הלמ\"ס, "
                               f"לכל אחד מ-{len(rank):,} הפריטים הטריים שנמדדו בחודש זה."
                               + (f" ללא שינוי שנתי מפורסם לחודש זה (מחוץ לעונה או בשנה הראשונה על בסיס חדש): {fmt.join_he(lagging)}." if lagging else ""))
        labels["rank_aria"] = (f"גרף עמודות: השינוי השנתי במחיר {len(rank):,} ירקות ופירות "
                               f"טריים, {Lm}. בראש: {rank[0]['name']}, {_sp(rank[0]['yoy'])}.")
    if mom:
        labels["mom_note"] = (f"השינוי לעומת החודש הקודם ב{Lm}. בירקות ובפירות טריים זה בעיקר "
                              f"עונתיות: אותו פריט יכול לעלות בחודש אחד ולרדת בבא.")
        labels["mom_aria"] = (f"גרף עמודות: השינוי החודשי במחיר ירקות ופירות טריים, {Lm}. "
                              f"העלייה הגדולה: {mom[0]['name']}, {_sp(mom[0]['pct'])}.")
    if multi:
        labels["multi_note"] = (f"מדד משורשר ({chain_base} = 100) ב-{MULTI_MONTHS:,} החודשים "
                                f"האחרונים, לפריטים המבוקשים. כל גרף בסולם משלו.")
    if seasons:
        labels["season_note"] = (
            f"השינוי החודשי הממוצע במחיר כל פריט בכל חודש בשנה, לפי השינויים שפרסמה הלמ\"ס "
            f"ב-{SEASON_YEARS:,} השנים שעד {Lm}. אדום: חודש שבו הפריט מתייקר בדרך כלל, כחול: "
            f"חודש שבו הוא מוזל. תא ריק: חודש שבו הפריט כמעט לא נמדד (מחוץ לעונה).")
        labels["season_aria"] = (f"מפת חום: השינוי החודשי הממוצע במחירי {len(seasons):,} ירקות "
                                 f"ופירות טריים לפי חודש. העונתיות החזקה ביותר: "
                                 f"{seasons[0]['name']}, שמתייקרים בעיקר "
                                 f"ב{fmt.MONTHS_HE[seasons[0]['peak']]}.")
    if heat:
        labels["heat_note"] = (f"השינוי החודשי במדד הירקות הטריים, לכל חודש ב-{len(heat_years):,} "
                               f"השנים האחרונות. אדום: התייקרות, כחול: הוזלה.")
        labels["heat_aria"] = (f"מפת חום: השינוי החודשי במדד הירקות הטריים לפי חודש ושנה, "
                               f"{heat_years[0]} עד {heat_years[-1]}.")
    if vol:
        labels["vol_note"] = (f"סטיית התקן של השינוי החודשי ב-{VOL_MONTHS:,} החודשים האחרונים: "
                              f"כמה המחיר קופץ בדרך כלל מחודש לחודש. פריט שנמדד פחות מ-"
                              f"{VOL_MIN_OBS:,} חודשים בתקופה לא נכלל.")
        labels["vol_aria"] = (f"גרף עמודות: התנודתיות החודשית של {len(vol):,} ירקות ופירות. "
                              f"התנודתי ביותר: {vol[0]['name']}.")
    if item_lr:
        labels["item_lr_note"] = (
            f"השינוי בממוצע השנתי של המדד, {base_year} לעומת {common[-1]}, לכל פריט שנמדד "
            f"ברציפות בשתי השנים. הקו האנכי: המדד הכללי"
            + (f" ({_sp(real[CPI], 0)})." if CPI in real else "."))
        labels["item_lr_aria"] = (f"גרף עמודות: ההתייקרות המצטברת של ירקות ופירות טריים "
                                  f"מ-{base_year} עד {common[-1]}. בראש: {item_lr[0]['name']}.")
    if other:
        labels["other_note"] = (f"השינוי ב-12 החודשים שעד {Lm} במדדי שימורי הירקות, "
                                f"האגוזים והפירות היבשים (מדדים אלה כוללים מע\"מ).")
        labels["other_aria"] = (f"גרף עמודות: השינוי השנתי במחירי שימורים, אגוזים ופירות יבשים, "
                                f"{Lm}.")

    # ── summary + SEO ──
    first_year = int(df["t"].min().year)
    summary = labels["lede"]
    if VEG in g_last:
        summary = (f"מדדי המחירים של ירקות ופירות טריים מהלמ\"ס, חודשי מאז {first_year}. "
                   f"ב-12 החודשים שעד {_month(g_last[VEG]['t'])}: ירקות טריים "
                   f"{_sp(g_last[VEG]['yoy'])}"
                   + (f", פירות טריים {_sp(g_last[FRUIT]['yoy'])}" if FRUIT in g_last else "")
                   + (f". ההתייקרות הגדולה: {rank[0]['name']} ({_sp(rank[0]['yoy'])})." if rank
                      else "."))
    desc = f"מחירי ירקות ופירות לפי הלמ\"ס, {Lm}"
    if VEG in g_last:
        desc += f": ירקות טריים {_sp(g_last[VEG]['yoy'])}"
        if FRUIT in g_last:
            desc += f", פירות טריים {_sp(g_last[FRUIT]['yoy'])}"
        desc += " בשנה"
    if rank:
        desc += f". הכי התייקרו: {rank[0]['name']} ({_sp(rank[0]['yoy'])})"
    desc += ". מדד לכל ירק ופרי."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_year}/{L.year}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד מחירי ירקות ופירות: עגבניות, מלפפונים ועוד",
                "description": desc,
                "name": "מדד מחירי ירקות ופירות",
                "alternate_names": ["מחירי ירקות", "מחירי ירקות ופירות", "מחיר עגבניות",
                                    "מדד המחירים לצרכן של ירקות ופירות נבחרים",
                                    "מדד מחירי פירות"],
            },
        },
        "kpis": kpis,
        "labels": labels,
        "insights": insights,
        "flags": {
            "groups_yoy": bool(groups_yoy), "longrun": bool(longrun), "rank": bool(rank),
            "mom": bool(mom), "multi": bool(multi), "season": bool(seasons), "heat": bool(heat),
            "vol": bool(vol), "item_lr": bool(item_lr), "other": bool(other),
        },
        "charts": {
            "groups_yoy": groups_yoy,
            "longrun": longrun,
            "rank": {"names": [i["name"] for i in rank], "y": [_r(i["yoy"]) for i in rank],
                     "kind": [i["kind"] for i in rank]},
            "mom": {"names": [i["name"] for i in mom], "y": [_r(i["pct"]) for i in mom]},
            "multi": {"x": multi_x, "items": multi},
            "season": {"items": [s["name"] for s in seasons], "months": fmt.MONTHS_SHORT_HE,
                       "cells": season_cells, "max": _r(season_max)},
            "heat": {"years": [str(y) for y in heat_years], "months": fmt.MONTHS_SHORT_HE,
                     "cells": heat, "max": _r(heat_max)},
            "vol": {"names": [v["name"] for v in vol], "y": [_r(v["sd"], 2) for v in vol]},
            "item_lr": {"names": [i["name"] for i in item_lr], "y": [_r(i["chg"]) for i in item_lr],
                        "kind": [i["kind"] for i in item_lr],
                        "cpi": _r(real.get(CPI)) if CPI in real else None},
            "other": {"names": [i["name"] for i in other], "y": [_r(i["yoy"]) for i in other]},
        },
        "tables": {
            "lr_cols": ["שנה"] + [GROUP_LABELS[c] for c in lr_codes],
            "longrun": lr_table,
            "years_cols": ["שנה"] + [GROUP_LABELS[c] for c in gy_codes],
            "years": years_tbl,
            "rank": [[i["name"], KIND_HE[i["kind"]], _sp(i["yoy"]),
                      _sp(i["pct"]) if i["pct"] is not None else "–"] for i in rank],
            "mom": [[i["name"], _sp(i["pct"])] for i in mom],
            "multi": multi_tbl,
            "season": season_tbl,
            "month_avg": [[fmt.MONTHS_HE[m["m"]],
                           _sp(m["veg"]) if m["veg"] is not None else "–",
                           _sp(m["fruit"]) if m["fruit"] is not None else "–"] for m in month_avg],
            "vol": [[v["name"], fmt.num_he(v["sd"], 2), _sp(v["max"]), _sp(v["min"]), f"{v['n']:,}"]
                    for v in vol],
            "item_lr": [[i["name"], KIND_HE[i["kind"]], _sp(i["chg"])] for i in item_lr],
            "other": [[i["name"], _sp(i["yoy"]),
                       _sp(other_lr[i["code"]]) if i["code"] in other_lr else "–"] for i in other],
        },
    }
