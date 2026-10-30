"""הוצאות בכרטיסי אשראי: daily card purchases in Israel, total and by sector.

Input: the BoI `CCP` dataflow (Shva data, BoI research). Every series is a
seasonally adjusted 7-day moving average of daily purchases, in units of
10**UNIT_MULT shekels (millions). `TOT` is the total (from 2016); sectors
start in 2018.

The sector tree comes from the series codes: RSCH_CC_<A>_<B>_<C>_D_SA_MA7,
where a code's parent is the longest other code that prefixes it (OTH_ENR_FUL
under OTH_ENR). Codes with no parent are the sectors; BoI's Hebrew series
name (SERIES_NAME_HE) gives each one its label. Each series is adjusted on
its own, so sectors don't sum exactly to TOT: sector shares are of the
sectors' sum, and say so.
"""
import re

import pandas as pd

TOTAL = "TOT"
# Purchases BoI couldn't classify: a sliver of the total whose swings are
# noise. Kept in the shares, left out of growth rankings (disclosed).
UNCLASSIFIED = "UNCLASS"
WINDOW = 28  # days in the "recent" comparison window
BASE_YEAR = 2019  # the last full year before 2020
DROP_LOOKBACK = 60  # days a fall is measured against (from the prior peak)
TOP_DROPS = 5
GROUP_LABELS = {  # top-level groups by the first code segment
    "FNB": "מזון ומשקאות",
    "MNF": "מוצרי תעשייה",
    "OTH": "מוצרים ושירותים אחרים",
    "SRV": "שירותים",
    "UNCLASS": "לא מסווג",
}
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _key(code):
    return re.sub(r"_D_SA_MA7$", "", re.sub(r"^RSCH_CC_", "", code))


def _label(name, key):
    """The last facet of BoI's Hebrew name ("… - דלק - מנוכה עונתיות …")."""
    n = re.sub(r"\s*-\s*מנוכה עונתיות.*$", "", name or "")
    parts = [p.strip() for p in n.split(" - ") if p.strip()]
    parts = [p for p in parts if p != "רכישות בכרטיסי אשראי"]
    if not parts:
        return key
    last = parts[-1]
    # A third-level facet ("שונות - מוצרים") needs its parent to be read alone.
    if len(parts) >= 3:
        last = f"{parts[-2]}: {last}"
    return last.replace("שרותים", "שירותים").replace(" (כולל שירותי אוכל)", "")


def _date(t):
    return f"{t.day}.{t.month}.{t.year}"


def _m(v):
    return f"{v:,.0f}"


def _pct(v, d=1):
    return f"{v:.{d}f}%"


def _signed(v, d=1):
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.{d}f}"


def _prepare(df):
    df = df.copy()
    for c in ("SERIES_CODE", "SERIES_NAME_HE", "TIME_PERIOD", "OBS_VALUE", "UNIT_MULT"):
        df[c] = df[c].str.strip()
    df["t"] = pd.to_datetime(df["TIME_PERIOD"], errors="coerce", format="%Y-%m-%d")
    df["v"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    mult = pd.to_numeric(df["UNIT_MULT"], errors="coerce").fillna(6)
    df["v"] = df["v"] * 10 ** (mult - 6)  # → millions of shekels a day
    df = df.dropna(subset=["t", "v"])
    df["key"] = df["SERIES_CODE"].map(_key)
    return df.sort_values(["key", "t", "v"], kind="stable")


def _tree(keys):
    def parent(k):
        p = k.split("_")
        for i in range(len(p) - 1, 0, -1):
            q = "_".join(p[:i])
            if q in keys:
                return q
        return None
    return {k: parent(k) for k in keys}


def _window(s, end, days=WINDOW):
    return s[(s.index > end - pd.Timedelta(days=days)) & (s.index <= end)]


def _yoy(s, end):
    """Mean of the last WINDOW days against the same days a year earlier."""
    cur = _window(s, end)
    prev = _window(s, end - pd.DateOffset(years=1))
    if len(cur) < WINDOW * 0.8 or len(prev) < WINDOW * 0.8 or prev.mean() == 0:
        return None
    return (cur.mean() / prev.mean() - 1) * 100


def _drops(s):
    """Deepest falls from the prior DROP_LOOKBACK-day peak, non-overlapping."""
    peak = s.rolling(f"{DROP_LOOKBACK}D").max()
    dd = (s / peak - 1) * 100
    out, used = [], []
    for t, v in dd.sort_values(kind="stable").items():
        if v > -5 or len(out) >= TOP_DROPS:
            break
        if any(abs((t - u).days) < DROP_LOOKBACK * 2 for u in used):
            continue
        win = s[(s.index >= t - pd.Timedelta(days=DROP_LOOKBACK)) & (s.index <= t)]
        pt = win.idxmax()
        out.append({"from": pt, "to": t, "pct": float(v), "peak": float(win.max()), "low": float(s[t])})
        used.append(t)
    return sorted(out, key=lambda d: d["to"])


# ── insights ─────────────────────────────────────────────────────────────


def insight_level(tot, end, yoy):
    if yoy is None:
        return None
    cur = _window(tot, end).mean()
    word = "גבוה" if yoy > 0 else "נמוך"
    return (f"ב-{WINDOW} הימים שעד {_date(end)} הסתכמו הרכישות בכרטיסי אשראי ב-{_m(cur)} מיליון ₪ "
            f"ביום בממוצע (מנוכה עונתיות), {word} ב-{abs(yoy):.1f}% מאותם ימים לפני שנה.")


def insight_base(tot):
    if tot.empty:
        return None
    base = tot[tot.index.year == BASE_YEAR]
    if len(base) < 300:
        return None
    end = tot.index[-1]
    cur = _window(tot, end).mean()
    ch = (cur / base.mean() - 1) * 100
    return (f"לעומת הממוצע היומי ב-{BASE_YEAR} ({_m(base.mean())} מיליון ₪), "
            f"הרכישות כיום {'גבוהות' if ch > 0 else 'נמוכות'} ב-{abs(ch):.1f}% (במחירים שוטפים).")


def insight_leaders(yoys, labels):
    ranked = [(k, v) for k, v in yoys.items() if v is not None]
    if len(ranked) < 3:
        return None
    ranked.sort(key=lambda kv: (-kv[1], kv[0]))
    (top, tv), (low, lv) = ranked[0], ranked[-1]
    if tv - lv < 5:
        return None
    return (f"הענף שצמח הכי מהר בשנה האחרונה: {labels[top]} ({_signed(tv)}%); "
            f"החלש ביותר: {labels[low]} ({_signed(lv)}%), "
            f"בהשוואת {WINDOW} הימים האחרונים לאותם ימים לפני שנה.")


def insight_share(shares, labels):
    if not shares:
        return None
    k, v = sorted(shares.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if v < 15:
        return None
    return (f"הענף הגדול ביותר הוא {labels[k]}: {_pct(v)} מסך הרכישות בענפים "
            f"ב-{WINDOW} הימים האחרונים.")


def insight_drop(drops):
    if not drops:
        return None
    d = sorted(drops, key=lambda x: (x["pct"], x["to"]))[0]
    days = (d["to"] - d["from"]).days
    return (f"הצניחה החדה ביותר בנתונים: {abs(d['pct']):.1f}% בתוך {days:,} ימים, "
            f"מ-{_m(d['peak'])} מיליון ₪ ביום ({_date(d['from'])}) ל-{_m(d['low'])} ({_date(d['to'])}).")


def insight_tourism(series, labels, end):
    """Flights and tourism against BASE_YEAR, if it is still far off."""
    k = "SRV_TOU"
    if k not in series or TOTAL not in series:
        return None
    s = series[k]
    base = s[s.index.year == BASE_YEAR]
    if len(base) < 300:
        return None
    ch = (_window(s, end).mean() / base.mean() - 1) * 100
    tot_base = series[TOTAL][series[TOTAL].index.year == BASE_YEAR]
    if len(tot_base) < 300:
        return None
    tot_ch = (_window(series[TOTAL], end).mean() / tot_base.mean() - 1) * 100
    if abs(ch - tot_ch) < 15:
        return None
    rel = "מאחור" if ch < tot_ch else "לפני"
    return (f"{labels[k]}: {_signed(ch)}% לעומת {BASE_YEAR}, הרחק {rel} לסך הרכישות "
            f"({_signed(tot_ch)}%).")


def insight_growth_leader(growth, labels):
    if len(growth) < 3:
        return None
    k, v = sorted(growth.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    lo, lv = sorted(growth.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return (f"מאז {BASE_YEAR} צמחו הכי הרבה הרכישות בענף {labels[k]} ({_signed(v)}%), "
            f"והכי מעט בענף {labels[lo]} ({_signed(lv)}%).")


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["purchases"])
    series = {}
    for k, g in df.groupby("key", sort=True):
        series[k] = g.drop_duplicates("t", keep="last").set_index("t")["v"].sort_index()
    if not series:
        raise ValueError("no card-purchase series")
    names = df.drop_duplicates("key", keep="last").set_index("key")["SERIES_NAME_HE"]
    labels = {k: _label(names.get(k, ""), k) for k in series}
    labels[TOTAL] = "סך הרכישות"
    tree = _tree(set(series) - {TOTAL})
    sectors = sorted(k for k, p in tree.items() if p is None)
    children = {s: sorted(k for k, p in tree.items() if p == s) for s in sectors}

    # Without the total, its views drop and the sector views stay.
    has_tot = TOTAL in series and not series[TOTAL].empty
    tot = series[TOTAL] if has_tot else pd.Series(dtype=float)
    sec_end = min(series[s].index[-1] for s in sectors) if sectors else None
    end = tot.index[-1] if has_tot else sec_end
    if end is None:
        raise ValueError("neither the total nor any sector series")
    sec_end = sec_end or end
    yoy_total = _yoy(tot, end) if has_tot else None

    ranked = [s for s in sectors if s != UNCLASSIFIED]
    yoys = {s: _yoy(series[s], sec_end) for s in ranked}
    recent = {s: float(_window(series[s], sec_end).mean()) for s in sectors
              if len(_window(series[s], sec_end))}
    sec_sum = sum(recent.values())
    shares = {s: v / sec_sum * 100 for s, v in recent.items()} if sec_sum else {}
    drops = _drops(tot) if has_tot else []

    # Growth since BASE_YEAR by sector.
    growth = {}
    for s in ranked:
        b = series[s][series[s].index.year == BASE_YEAR]
        if len(b) >= 300 and b.mean():
            growth[s] = (recent.get(s, 0) / b.mean() - 1) * 100

    rules = [
        ("level", insight_level(tot, end, yoy_total)),
        ("base", insight_base(tot)),
        ("leaders", insight_leaders(yoys, labels)),
        ("share", insight_share(shares, labels)),
        ("tourism", insight_tourism(series, labels, sec_end)),
        ("drop", insight_drop(drops)),
        ("growth", insight_growth_leader(growth, labels)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    kpis = {}
    cur, m4 = None, None
    if has_tot:
        cur = float(_window(tot, end).mean())
        four = _window(tot, end - pd.Timedelta(days=WINDOW))
        m4 = (cur / four.mean() - 1) * 100 if len(four) and four.mean() else None
        kpis["level"] = {"value": round(float(tot.iloc[-1]), 1), "display": _m(tot.iloc[-1]),
                         "tone": "brand"}
    if yoy_total is not None:
        kpis["yoy"] = {"value": round(yoy_total, 2), "display": _signed(yoy_total) + "%",
                       "tone": "ok" if yoy_total > 0 else "danger" if yoy_total < -3 else "warn"}
    if m4 is not None:
        kpis["m4"] = {"value": round(m4, 2), "display": _signed(m4) + "%",
                      "tone": "ok" if m4 > 1 else "warn" if m4 < -1 else "brand"}
    base = tot[tot.index.year == BASE_YEAR] if has_tot else tot
    if has_tot and len(base) >= 300:
        g = (cur / base.mean() - 1) * 100
        kpis["base"] = {"value": round(g, 2), "display": _signed(g) + "%", "tone": "brand"}

    # 1. the total, one point a week ending on the last day.
    weekly = tot[((end - tot.index).days % 7) == 0] if has_tot else tot
    total_chart = {"x": [t.strftime("%Y-%m-%d") for t in weekly.index],
                   "y": [round(float(v), 1) for v in weekly]}
    year_rows = []
    prev_mean = None
    by_year = tot.groupby(tot.index.year).agg(["mean", "size"]) if has_tot else pd.DataFrame()
    for y, r in by_year.iterrows():
        ch = (r["mean"] / prev_mean - 1) * 100 if prev_mean else None
        year_rows.append({"year": int(y), "mean": _m(r["mean"]), "partial": bool(r["size"] < 360),
                          "change": _signed(ch) + "%" if ch is not None else ""})
        prev_mean = r["mean"]
    year_rows.reverse()

    # 2. sectors: year-on-year change.
    sec_rank = sorted([s for s in ranked if yoys[s] is not None],
                      key=lambda s: (-yoys[s], s))
    yoy_chart = {"names": [labels[s] for s in sec_rank], "y": [round(yoys[s], 2) for s in sec_rank]}
    yoy_rows = [{"name": labels[s], "yoy": _signed(yoys[s]) + "%",
                 "level": _m(recent.get(s, 0))} for s in sec_rank]

    # 3. sector shares, with sub-sectors for the treemap.
    share_rank = sorted(shares, key=lambda s: (-shares[s], s))
    tree_data = []
    for s in share_rank:
        node = {"name": labels[s], "value": round(recent[s], 1)}
        kids = [(c, float(_window(series[c], sec_end).mean())) for c in children[s]
                if len(_window(series[c], sec_end))]
        if kids:
            node["children"] = [{"name": labels[c], "value": round(v, 1)}
                                for c, v in sorted(kids, key=lambda kv: (-kv[1], kv[0]))]
        tree_data.append(node)
    share_rows = [{"name": labels[s], "group": GROUP_LABELS.get(s.split("_")[0], ""),
                   "level": _m(recent[s]), "share": _pct(shares[s])} for s in share_rank]

    # 4. growth since BASE_YEAR by sector (computed above).
    g_rank = sorted(growth, key=lambda s: (-growth[s], s))
    growth_chart = {"names": [labels[s] for s in g_rank], "y": [round(growth[s], 2) for s in g_rank]}
    if "base" in kpis:
        growth_chart["total"] = kpis["base"]["value"]
    growth_rows = [{"name": labels[s], "growth": _signed(growth[s]) + "%"} for s in g_rank]

    # 5. sub-sectors: year-on-year change.
    subs = sorted(k for k, p in tree.items() if p is not None)
    sub_yoy = {k: _yoy(series[k], sec_end) for k in subs}
    sub_rank = sorted([k for k in subs if sub_yoy[k] is not None], key=lambda k: (-sub_yoy[k], k))
    sub_chart = {"names": [labels[k] for k in sub_rank], "y": [round(sub_yoy[k], 2) for k in sub_rank],
                 "group": [labels[tree[k]] for k in sub_rank]}
    sub_rows = [{"name": labels[k], "parent": labels[tree[k]], "yoy": _signed(sub_yoy[k]) + "%"}
                for k in sub_rank]

    drop_rows = [{"from": _date(d["from"]), "to": _date(d["to"]), "pct": _signed(d["pct"]) + "%",
                  "peak": _m(d["peak"]), "low": _m(d["low"])} for d in drops]

    first = min(s.index[0] for s in series.values())
    summary = ("הוצאות בכרטיסי אשראי בישראל, נתון יומי לפי ענף"
               + (f": {_m(cur)} מיליון ₪ ביום בממוצע ב-{WINDOW} הימים שעד {_date(end)}" if has_tot else "")
               + (f", {_signed(yoy_total)}% משנה שעברה" if yoy_total is not None else "") + ".")
    lede = (f"סכום הרכישות היומי בכרטיסי אשראי בישראל מ-{_date(first)} ועד {_date(end)}, "
            f"מנוכה עונתיות וממוצע נע של שבעה ימים, ולפי {len(sectors):,} ענפים. "
            "הנתונים של שב\"א, בעיבוד חטיבת המחקר של בנק ישראל, ומתעדכנים כמה פעמים בשבוע.")
    labels_out = {
        "lede": lede,
        "level_kpi": f"רכישות ביום, מיליון ₪ ({_date(end)})",
        "yoy_kpi": f"שינוי מול אותם {WINDOW} ימים לפני שנה",
        "m4_kpi": f"שינוי מול {WINDOW} הימים שקדמו להם",
        "base_kpi": f"שינוי מול הממוצע של {BASE_YEAR}",
        "total_note": (f"סך הרכישות היומי בכרטיסי אשראי (מיליון ₪, מנוכה עונתיות, ממוצע נע של שבעה ימים), "
                       f"נקודה אחת לשבוע. נתונים מ-{first.year}; אפשר לגרור את פס הזמן."),
        "total_aria": (f"גרף קו: סך הרכישות היומי בכרטיסי אשראי מ-{first.year} עד {_date(end)}"
                       + (f"; כיום {_m(tot.iloc[-1])} מיליון ₪ ביום." if has_tot else ".")),
        "year_caption": "ממוצע הרכישות היומי בכל שנה ושינוי משנה קודמת",
        "yoy_note": (f"שינוי ברכישות בכל ענף: ממוצע {WINDOW} הימים שעד {_date(sec_end)} "
                     "מול אותם ימים לפני שנה (במחירים שוטפים). ללא רכישות שלא סווגו לענף."),
        "yoy_aria": f"תרשים עמודות אופקי: שינוי שנתי ברכישות בכרטיסי אשראי ב-{len(sec_rank):,} ענפים.",
        "yoy_caption": f"שינוי שנתי וממוצע יומי לפי ענף, {WINDOW} ימים עד {_date(sec_end)}",
        "share_note": (f"חלקו של כל ענף מסך הרכישות בענפים ב-{WINDOW} הימים האחרונים. כל סדרה מנוכה "
                       "עונתיות בנפרד, ולכן סכום הענפים קרוב לסך הכול אך אינו זהה לו."),
        "share_aria": f"מפת שטחים: חלוקת הרכישות בכרטיסי אשראי בין {len(share_rank):,} ענפים ותת-ענפים.",
        "share_caption": f"ממוצע יומי וחלק מסך הענפים, {WINDOW} ימים עד {_date(sec_end)}",
        "growth_note": (f"שינוי בממוצע היומי של כל ענף מאז {BASE_YEAR} (השנה המלאה האחרונה לפני "
                        f"{BASE_YEAR + 1}), במחירים שוטפים. ללא רכישות שלא סווגו לענף."),
        "growth_aria": f"תרשים עמודות אופקי: שינוי ברכישות לפי ענף מאז {BASE_YEAR}.",
        "growth_caption": f"שינוי בממוצע היומי לפי ענף מאז {BASE_YEAR}",
        "sub_note": f"השינוי השנתי בתת-הענפים ({WINDOW} ימים מול אותם ימים לפני שנה).",
        "sub_aria": f"תרשים עמודות אופקי: שינוי שנתי ב-{len(sub_rank):,} תת-ענפים.",
        "sub_caption": "שינוי שנתי לפי תת-ענף",
        "drops_note": (f"הירידות החדות ביותר בסך הרכישות: הפער בין שיא ב-{DROP_LOOKBACK} הימים שקדמו "
                       "לבין השפל שאחריו."),
        "drops_caption": "הירידות החדות ביותר בסך הרכישות היומי",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["כרטיסי אשראי", "צריכה פרטית", "כלכלה", "בנק ישראל", "קניות"],
            "temporal_coverage": f"{first.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"total": total_chart, "yoy": yoy_chart, "tree": tree_data,
                   "growth": growth_chart, "sub": sub_chart},
        "tables": {"years": year_rows, "yoy": yoy_rows, "shares": share_rows,
                   "growth": growth_rows, "sub": sub_rows, "drops": drop_rows},
        "flags": {"total": has_tot, "sectors": bool(sec_rank), "yoy": bool(sec_rank), "tree": bool(tree_data), "growth": bool(g_rank),
                  "sub": bool(sub_rank), "drops": bool(drop_rows)},
        "insights": insights,
        "labels": labels_out,
    }
