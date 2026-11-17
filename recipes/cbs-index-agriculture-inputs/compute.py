"""מדד מחירי תשומה בחקלאות: the CBS agricultural input price index.

Inputs (CBS Index API, provider `cbs_index`; one row per code and month):
  main      the general index (260010, since 1976), the index without hired
            labour (260020), inputs in plant crops (261010) and in livestock
            (261020), full history.
  groups_a  main groups: feed, chicks, seeds, fertilisers, pesticides, water,
  groups_b  fuel and electricity, packaging, building materials, hired labour,
            machinery, equipment, vehicles, hauling, veterinary, insurance,
            taxes, land lease, other (from 2011; machinery, equipment and
            vehicles only from the 2021 basket).
  selected  selected inputs: diesel, petrol, fuel, electricity, feed mixes,
            nitrogen and potash fertilisers, herbicides (from 2011).

Rules (BRIEF.md, Source rules): levels and long-run ratios use VALUE_CHAINED
(every month on the newest base, CHAIN_BASE); month-on-month and
year-on-year changes are CBS's published PERCENT / PERCENT_YEAR, quoted as
published. The general index is required; every other code is optional, so
a code CBS retires drops its views instead of failing the page. An unknown
code renders under CBS's own NAME_HE.

Electricity is billed on seasonal time-of-use tariffs, so its month-on-month
change swings by tens of percent at each season change; rankings use the
year-on-year change, which compares like seasons.
"""
import math

import pandas as pd
from govlib import fmt

GENERAL = 260010
NO_LABOUR = 260020
CROPS = 261010
LIVESTOCK = 261020
LABOUR = 260450
DIESEL = 270130
PETROL = 270140
ELECTRICITY = 260320
MAIN_ORDER = [GENERAL, CROPS, LIVESTOCK, NO_LABOUR, LABOUR]
INPUT_KEYS = ("main", "groups_a", "groups_b", "selected")

SHORT = {
    GENERAL: "המדד הכללי",
    NO_LABOUR: "המדד ללא עבודה שכירה",
    CROPS: "גידולים צמחיים",
    LIVESTOCK: "בעלי חיים",
    LABOUR: "עבודה שכירה",
    260030: "מספוא לבעלי חיים",
    260290: "דלק, שמנים וחשמל",
    260340: "חומרי בנייה וכיסויים פלסטיים",
    260510: "שירותים וטרינריים ותרופות",
    260550: "שונות (הנהלת חשבונות, מחשב, משרד)",
    260060: "תערובות לבקר",
}

# The main groups of subject 55, in CBS's catalog order. Unknown codes in
# groups_a / groups_b follow, by code.
GROUP_ORDER = [
    260030, 260100, 260110, 260150, 260230, 260280, 260290, 260330, 260340,
    260599, 260900, 260950, 260500, 260510, 260520, 260530, 260540, 260550,
    260450,
]
# Selected inputs, in display order.
SELECTED_ORDER = [270130, 270140, 260300, 260320, 270010, 270020, 260060,
                  260170, 260190, 260240]
ENERGY = [DIESEL, PETROL, ELECTRICITY]
FEED_FERT = [270010, 270020, 260060, 260170, 260190]

RECENT_MONTHS = 24
ANNUAL_YEARS = 25
HEAT_YEARS = 15
REBASE_YEARS = 10
TOP_N = 10
SEASON_YEARS = 10


# ── parsing ──────────────────────────────────────────────────────────────


def _load(frames):
    """code → DataFrame indexed by month (Timestamp), sorted, monthly rows
    only; and code → the input it came from. A code in more than one input
    is read from the first (main has the longest history)."""
    out, names, origin = {}, {}, {}
    for key in INPUT_KEYS:
        df = frames.get(key)
        if df is None or df.empty:
            continue
        df = df[df["FREQ"].str.strip() == "M"].copy()
        df["code"] = pd.to_numeric(df["CODE"].str.strip(), errors="coerce")
        df["t"] = pd.to_datetime(df["DATE"].str.strip(), errors="coerce", format="%Y-%m-%d")
        df = df.dropna(subset=["code", "t"])
        df["code"] = df["code"].astype(int)
        for col, src in (("v", "VALUE_CHAINED"), ("value", "VALUE"),
                         ("p", "PERCENT"), ("py", "PERCENT_YEAR")):
            df[col] = pd.to_numeric(df[src].str.strip(), errors="coerce")
        df["base"] = df["BASE_DESC"].str.strip()
        df["chain"] = df["CHAIN_BASE"].str.strip()
        df["name"] = df["NAME_HE"].str.strip()
        df = df.sort_values(["code", "t", "v", "p", "py"], kind="stable")
        for code, s in df.groupby("code", sort=True):
            if code in out:
                continue
            s = s.drop_duplicates("t", keep="last").set_index("t")
            if s["v"].notna().any():
                out[code] = s
                names[code] = s["name"].iloc[-1]
                origin[code] = key
    return out, names, origin


def _label(code, names):
    return SHORT.get(code) or names.get(code) or str(code)


def _base_he(desc):
    """'2020 ממוצע' → 'ממוצע 2020', '1975 1976' stays as is."""
    parts = (desc or "").split()
    if len(parts) == 2 and parts[0].isdigit() and not parts[1].isdigit():
        return f"{parts[1]} {parts[0]}"
    return desc or ""


# ── formatting ───────────────────────────────────────────────────────────


def _sp(v, digits=1):
    """A published change in percent, signed: 0.1 → '+0.1%', -0.4 → '−0.4%'."""
    body = f"{abs(v):.{digits}f}"
    if float(body) == 0:
        return f"{body}%"
    return ("+" if v > 0 else fmt.MINUS) + body + "%"


def _spi(v, digits=1):
    """A signed change inside Hebrew prose, isolated so bidi keeps its sign."""
    return fmt.isolate(_sp(v, digits))


def _pc(v, digits=1):
    """A change in prose without a plus sign; a negative is isolated."""
    if v < 0 and float(f"{abs(v):.{digits}f}") != 0:
        return fmt.isolate(fmt.MINUS + f"{abs(v):.{digits}f}%")
    return f"{abs(v):.{digits}f}%"


def _sig(v, n=4):
    """A chained level to `n` significant digits (1976 levels are ~0.006)."""
    if v == 0 or not math.isfinite(v):
        return 0.0
    return float(f"{v:.{n}g}")


def _lvl(v):
    """A level for tables: one decimal from 10 up, significant digits below."""
    if abs(v) >= 10:
        return fmt.num_he(v, 1)
    if v <= 0:
        return "–"
    digits = max(1, 3 - math.floor(math.log10(v)))
    return f"{v:.{digits}f}"


def _r1(v):
    return round(float(v), 1)


def _months_back(t, n):
    m = t.year * 12 + t.month - 1 - n
    return pd.Timestamp(year=m // 12, month=m % 12 + 1, day=1)


def _at(s, t, col="v"):
    if s is not None and t in s.index:
        x = s.at[t, col]
        if pd.notna(x):
            return float(x)
    return None


def _moved(v, plural=False):
    """'עלה ב-3.6%' / 'ירד ב-0.4%' / 'לא השתנה' (plural: עלו / ירדו / לא השתנו)."""
    if float(f"{abs(v):.1f}") == 0:
        return "לא השתנו" if plural else "לא השתנה"
    if v > 0:
        return ("עלו" if plural else "עלה") + f" ב-{_pc(v)}"
    return ("ירדו" if plural else "ירד") + f" ב-{_pc(-v)}"


# ── insights ─────────────────────────────────────────────────────────────


def insight_latest(gen, last):
    p, py = _at(gen, last, "p"), _at(gen, last, "py")
    if p is None or py is None:
        return None
    return (f"מדד מחירי התשומה בחקלאות לחודש {fmt.month_he(last)} {_moved(p)} לעומת החודש "
            f"הקודם. ב-12 החודשים האחרונים המדד {_moved(py)}.")


def insight_yoy_trend(gen, last):
    now, prev_t = _at(gen, last, "py"), _months_back(last, 12)
    before = _at(gen, prev_t, "py")
    if now is None or before is None:
        return None
    d = now - before
    if abs(d) < 0.3:
        return (f"קצב השינוי השנתי במדד יציב: {_spi(now)} ב{fmt.month_he(last)}, "
                f"לעומת {_spi(before)} ב{fmt.month_he(prev_t)}.")
    if now > 0 and before > 0:
        word = "התגבר" if d > 0 else "התמתן"
        head = f"קצב העלייה השנתי במדד {word}"
    else:
        head = "השינוי השנתי במדד " + ("עלה" if d > 0 else "ירד")
    return (f"{head}: מ-{_spi(before)} ב{fmt.month_he(prev_t)} "
            f"ל-{_spi(now)} ב{fmt.month_he(last)}.")


def insight_crops_livestock(series, last, start):
    cr, lv = series.get(CROPS), series.get(LIVESTOCK)
    cp, lp = _at(cr, last, "py"), _at(lv, last, "py")
    if cp is None or lp is None:
        return None
    s = (f"ב-12 החודשים שעד {fmt.month_he(last)} התשומות בגידולים צמחיים {_moved(cp, plural=True)}, "
         f"והתשומות בבעלי חיים {_moved(lp, plural=True)}.")
    if start is not None:
        c0, c1, l0, l1 = _at(cr, start), _at(cr, last), _at(lv, start), _at(lv, last)
        if None not in (c0, c1, l0, l1) and c0 > 0 and l0 > 0:
            s += (f" מאז {fmt.month_he(start)} התשומות בגידולים צמחיים "
                  f"{_moved((c1 / c0 - 1) * 100, plural=True)} ובבעלי חיים "
                  f"{_moved((l1 / l0 - 1) * 100, plural=True)}.")
    return s


def insight_drivers(movers):
    up = [m for m in movers if m["py"] > 0]
    down = [m for m in movers if m["py"] < 0]
    if not up:
        return None
    names = fmt.join_he([f"{m['name']} ({_pc(m['py'])})" for m in up[:2]])
    s = f"הקבוצות שהתייקרו ביותר בשנה האחרונה: {names}."
    if down:
        low = down[-1]
        s += f" הירידה החדה ביותר: {low['name']} ({_pc(low['py'])})."
    else:
        s += " אף קבוצה ראשית לא הוזלה בשנה זו."
    return s


def insight_diesel(series, last):
    s = series.get(DIESEL)
    py = _at(s, last, "py")
    if py is None or abs(py) < 10:
        return None
    word = "התייקר" if py > 0 else "הוזל"
    s = f"מחיר הסולר לחקלאים {word} ב-{_pc(abs(py))} ב-12 החודשים שעד {fmt.month_he(last)}"
    vals = sorted(((abs(v), c) for c in SELECTED_ORDER
                   if (v := _at(series.get(c), last, "py")) is not None), reverse=True)
    if vals and vals[0][1] == DIESEL:
        s += ", השינוי החד ביותר בין התשומות הנבחרות שבעמוד"
    return s + "."


def insight_electricity(series, last):
    """Electricity's month-on-month swing is the seasonal tariff, not a
    price trend: say so when the swing dwarfs the year-on-year change."""
    s = series.get(ELECTRICITY)
    p, py = _at(s, last, "p"), _at(s, last, "py")
    if p is None or py is None or abs(p) < 10 or abs(py) * 3 > abs(p):
        return None
    return (f"מחיר החשמל לחקלאות {_moved(p)} ב{fmt.month_he(last)} לעומת החודש הקודם, תנודה "
            "שמתאימה למעבר בין תעריפים עונתיים. לעומת החודש המקביל אשתקד הוא "
            f"{_moved(py)}.")


def insight_season(gen, last):
    """The calendar months with the largest average rise and fall over the
    last complete years, when they stand out."""
    p = gen["p"].dropna()
    full_years = [y for y in sorted(set(p.index.year)) if y < last.year or last.month == 12]
    full_years = [y for y in full_years if (p.index.year == y).sum() == 12][-SEASON_YEARS:]
    if len(full_years) < 5:
        return None
    win = p[p.index.year.isin(full_years)]
    by_month = win.groupby(win.index.month).mean().sort_index()
    top = int(by_month.idxmax())
    low = int(by_month.idxmin())
    top_mean, low_mean = float(by_month[top]), float(by_month[low])
    if top_mean < 0.5:
        return None
    s = (f"למדד יש דפוס עונתי: בשנים {full_years[0]} עד {full_years[-1]} עלה המדד בחודש "
         f"{fmt.MONTHS_HE[top - 1]} ב-{_pc(top_mean, 2)} בממוצע")
    if low_mean <= -0.5:
        s += f", וירד בחודש {fmt.MONTHS_HE[low - 1]} ב-{_pc(-low_mean, 2)} בממוצע"
    return s + "."


def insight_decades(gen, last):
    t1, t2 = _months_back(last, 120), _months_back(last, 240)
    v0, v1, v2 = _at(gen, last), _at(gen, t1), _at(gen, t2)
    if None in (v0, v1, v2) or v1 <= 0 or v2 <= 0:
        return None
    a, b = (v0 / v1 - 1) * 100, (v1 / v2 - 1) * 100
    return (f"בעשור האחרון ({fmt.month_he(t1)} עד {fmt.month_he(last)}) המדד {_moved(a)}, "
            f"לעומת {_pc(b)} בעשור שקדם לו ({fmt.month_he(t2)} עד {fmt.month_he(t1)}).")


# ── shared views ─────────────────────────────────────────────────────────


def _rebased(series, names, codes, start, last, gen):
    """Lines rebased to 100 at `start`, for codes that reach `last`; and a
    table of January values plus the latest month."""
    lines, cols = [], []
    for code in codes:
        s = series.get(code)
        if s is None:
            continue
        v0 = _at(s, start)
        win = s.loc[start:last, "v"].dropna()
        if v0 is None or v0 <= 0 or win.empty or win.index[-1] != last:
            continue
        lines.append({"name": _label(code, names),
                      "data": [[t.strftime("%Y-%m"), _r1(v / v0 * 100)] for t, v in win.items()]})
        cols.append((s, v0))
    if len(lines) < 2:
        return None
    ticks = [t for t in gen.loc[start:last].index if t.month == 1]
    if ticks[-1] != last:
        ticks.append(last)
    rows = []
    for t in reversed(ticks):
        row = [fmt.month_he(t)]
        for s, v0 in cols:
            v = _at(s, t)
            row.append(fmt.num_he(v / v0 * 100, 1) if v is not None else "–")
        rows.append(row)
    ends = {line["name"]: line["data"][-1][1] for line in lines}
    return {"lines": lines, "cols": [line["name"] for line in lines], "rows": rows, "ends": ends}


def _ranked(items):
    pick = items if len(items) <= 2 * TOP_N else items[:TOP_N] + items[-TOP_N:]
    return pick, len(pick) < len(items)


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    series, names, origin = _load(frames)
    gen = series.get(GENERAL)
    if gen is None:
        raise ValueError("no rows for the general index (code 260010)")
    gen = gen[gen["v"].notna()]
    series[GENERAL] = gen
    last = gen.index[-1]
    first = gen.index[0]
    chain_base = _base_he(gen["chain"].iloc[-1])
    latest_value = _at(gen, last, "value")
    if latest_value is None:
        latest_value = _at(gen, last)
    latest_base = _base_he(gen.at[last, "base"])
    p_last, py_last = _at(gen, last, "p"), _at(gen, last, "py")
    month = fmt.month_he(last)

    start = pd.Timestamp(year=last.year - REBASE_YEARS, month=1, day=1)
    if start not in gen.index:
        start = None
    # Cumulative changes compare the same calendar month ten years apart:
    # electricity's seasonal tariff (and the index's July / October swings)
    # would otherwise make the start month decide the result.
    cum = _months_back(last, 12 * REBASE_YEARS)
    if cum not in gen.index:
        cum = None

    # ── KPIs ──
    kpis = {"level": {"value": latest_value, "display": fmt.num_he(latest_value, 1),
                      "tone": "brand"}}
    if p_last is not None:
        kpis["mom"] = {"value": p_last, "display": _sp(p_last),
                       "tone": "warn" if p_last >= 1 else "ok" if p_last < 0 else "brand"}
    if py_last is not None:
        kpis["yoy"] = {"value": py_last, "display": _sp(py_last),
                       "tone": "warn" if py_last >= 4 else "ok" if py_last <= 0 else "brand"}
    for key, code in (("crops", CROPS), ("livestock", LIVESTOCK)):
        v = _at(series.get(code), last, "py")
        if v is not None:
            kpis[key] = {"value": v, "display": _sp(v), "tone": "brand"}

    # ── 1. recent months ──
    recent = gen.iloc[-RECENT_MONTHS:]
    v_last = float(gen.at[last, "v"])
    recent_chart = {
        "x": [f"{fmt.MONTHS_SHORT_HE[t.month - 1]} {t.year}" for t in recent.index],
        "mom": [None if pd.isna(x) else _r1(x) for x in recent["p"]],
        "yoy": [None if pd.isna(x) else _r1(x) for x in recent["py"]],
    }
    recent_table = []
    for t, r in recent.iloc[::-1].iterrows():
        recent_table.append([
            fmt.month_he(t),
            fmt.num_he(r["value"], 1) if pd.notna(r["value"]) else "–",
            _base_he(r["base"]),
            _sp(r["p"]) if pd.notna(r["p"]) else "–",
            _sp(r["py"]) if pd.notna(r["py"]) else "–",
        ])

    # ── 2. whole history on the newest base ──
    history = [[t.strftime("%Y-%m"), _sig(float(v))] for t, v in gen["v"].items()]
    dec = gen[gen.index.month == 12]
    annual_rows = [{"year": t.year, "level": float(r["v"]),
                    "py": None if pd.isna(r["py"]) else float(r["py"])}
                   for t, r in dec.iterrows()]
    annual_table = [[str(a["year"]), _lvl(a["level"]), _sp(a["py"]) if a["py"] is not None else "–"]
                    for a in annual_rows]
    if last.month != 12:
        annual_table.append([f"{month} (12 חודשים)", _lvl(v_last),
                             _sp(py_last) if py_last is not None else "–"])
    annual_table.reverse()
    mult = v_last / float(gen["v"].iloc[0])
    mult_txt = fmt.int_he(_sig(mult, 3)) if mult >= 1000 else fmt.num_he(mult, 1)

    # ── 3. annual change (December on December) ──
    ann = [a for a in annual_rows if a["py"] is not None][-ANNUAL_YEARS:]
    annual_chart = {"x": [str(a["year"]) for a in ann], "y": [_r1(a["py"]) for a in ann]}
    annual_small = [[str(a["year"]), _sp(a["py"])] for a in reversed(ann)]
    ann_max = max(ann, key=lambda a: (a["py"], a["year"])) if ann else None
    ann_min = min(ann, key=lambda a: (a["py"], -a["year"])) if ann else None
    ann_avg = sum(a["py"] for a in ann) / len(ann) if ann else None

    # ── 4. crops, livestock, labour rebased ──
    rebased = _rebased(series, names, MAIN_ORDER, start, last, gen) if start is not None else None

    # ── 5. crops vs livestock, published year-on-year ──
    cvl = None
    cr, lv = series.get(CROPS), series.get(LIVESTOCK)
    if cr is not None and lv is not None:
        both = pd.concat({"cr": cr["py"], "lv": lv["py"], "gen": gen["py"]}, axis=1)
        both = both.dropna(subset=["cr", "lv"]).loc[:last]
        if len(both) >= 24:
            cvl = {
                "x": [t.strftime("%Y-%m") for t in both.index],
                "cr": [_r1(v) for v in both["cr"]],
                "lv": [_r1(v) for v in both["lv"]],
                "gen": [None if pd.isna(v) else _r1(v) for v in both["gen"]],
                "since": fmt.month_he(both.index[0]),
                "cr_above": int((both["cr"] > both["lv"]).sum()),
                "n": len(both),
            }
            pts = [t for t in both.index if t.month == 12]
            if both.index[-1] not in pts:
                pts.append(both.index[-1])
            cvl["rows"] = [[fmt.month_he(t), _sp(both.at[t, "cr"]), _sp(both.at[t, "lv"]),
                            _sp(both.at[t, "gen"]) if pd.notna(both.at[t, "gen"]) else "–"]
                           for t in reversed(pts[-ANNUAL_YEARS:])]

    # ── 6/7. main groups: last 12 months and the decade ──
    group_codes = [c for c in GROUP_ORDER if c in series]
    group_codes += sorted(c for c in series if origin[c] in ("groups_a", "groups_b")
                          and c not in GROUP_ORDER)
    stale = _months_back(last, 12)
    leaves = []
    for code in group_codes:
        s = series[code]
        if s.index[-1] <= stale:
            continue  # a group CBS stopped publishing
        v1 = _at(s, last)
        v0 = _at(s, cum) if cum is not None else None
        leaves.append({"code": code, "name": _label(code, names), "p": _at(s, last, "p"),
                       "py": _at(s, last, "py"),
                       "dec": (v1 / v0 - 1) * 100 if v0 and v1 is not None and v0 > 0 else None})
    movers = sorted([g for g in leaves if g["py"] is not None], key=lambda g: (-g["py"], g["code"]))
    drivers = None
    if len(movers) >= 4:
        pick, cut = _ranked(movers)
        drivers = {"names": [g["name"] for g in pick], "y": [_r1(g["py"]) for g in pick],
                   "rows": [[g["name"], _sp(g["py"]), _sp(g["p"]) if g["p"] is not None else "–"]
                            for g in pick], "n": len(movers), "cut": cut}
    dec_movers = sorted([g for g in leaves if g["dec"] is not None],
                        key=lambda g: (-g["dec"], g["code"]))
    decade = None
    if len(dec_movers) >= 4 and cum is not None:
        pick, cut = _ranked(dec_movers)
        decade = {"names": [g["name"] for g in pick], "y": [_r1(g["dec"]) for g in pick],
                  "rows": [[g["name"], _sp(g["dec"])] for g in pick],
                  "n": len(dec_movers), "cut": cut,
                  "gen": _r1((v_last / float(gen.at[cum, "v"]) - 1) * 100),
                  "missing": len([g for g in leaves if g["dec"] is None])}
    all_groups = [{"name": g["name"],
                   "p": _sp(g["p"]) if g["p"] is not None else "–",
                   "py": _sp(g["py"]) if g["py"] is not None else "–",
                   "dec": _sp(g["dec"]) if g["dec"] is not None else "–"}
                  for g in leaves]

    # ── 8. selected inputs: year-on-year, and energy / feed lines ──
    sel_codes = [c for c in SELECTED_ORDER if c in series]
    sel_codes += sorted(c for c in series if origin[c] == "selected" and c not in SELECTED_ORDER)
    sel = []
    for code in sel_codes:
        s = series[code]
        if s.index[-1] <= stale:
            continue
        py = _at(s, last, "py")
        if py is None:
            continue
        v1 = _at(s, last)
        v0 = _at(s, cum) if cum is not None else None
        sel.append({"code": code, "name": _label(code, names), "py": py,
                    "p": _at(s, last, "p"),
                    "dec": (v1 / v0 - 1) * 100 if v0 and v1 is not None and v0 > 0 else None})
    sel.sort(key=lambda g: (-g["py"], g["code"]))
    selected = None
    if len(sel) >= 3:
        selected = {"names": [g["name"] for g in sel], "y": [_r1(g["py"]) for g in sel],
                    "rows": [[g["name"], _sp(g["py"]), _sp(g["p"]) if g["p"] is not None else "–",
                              _sp(g["dec"]) if g["dec"] is not None else "–"] for g in sel]}
    energy = _rebased(series, names, ENERGY, start, last, gen) if start is not None else None
    feed = _rebased(series, names, FEED_FERT, start, last, gen) if start is not None else None

    # ── 9. heatmap of monthly changes, general index ──
    y0 = last.year - HEAT_YEARS + 1
    heat_src = gen[(gen.index.year >= y0) & gen["p"].notna()]
    heat_years = sorted(set(heat_src.index.year))
    cells = [[t.month - 1, heat_years.index(t.year), _r1(r["p"])] for t, r in heat_src.iterrows()]
    if not cells:
        raise ValueError("no published monthly changes for the general index")
    heat_rows = []
    for y in reversed(heat_years):
        row = [str(y)]
        for mth in range(1, 13):
            t = pd.Timestamp(year=y, month=mth, day=1)
            v = _at(gen, t, "p")
            row.append(_sp(v) if v is not None and t in heat_src.index else "–")
        heat_rows.append(row)
    heat = {"x": fmt.MONTHS_SHORT_HE, "y": [str(y) for y in heat_years], "cells": cells,
            "min": min(c[2] for c in cells), "max": max(c[2] for c in cells)}

    # ── insights ──
    rules = [
        ("latest", insight_latest(gen, last)),
        ("yoy_trend", insight_yoy_trend(gen, last)),
        ("crops_livestock", insight_crops_livestock(series, last, cum)),
        ("drivers", insight_drivers(movers)),
        ("diesel", insight_diesel(series, last)),
        ("electricity", insight_electricity(series, last)),
        ("season", insight_season(gen, last)),
        ("decades", insight_decades(gen, last)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── text ──
    lvl_txt = fmt.num_he(latest_value, 1)
    change_txt = ""
    if p_last is not None and py_last is not None:
        change_txt = (f": שינוי של {_spi(p_last)} לעומת החודש הקודם ו-{_spi(py_last)} "
                      "לעומת החודש המקביל אשתקד")
    lede = (f"מדד מחירי התשומה בענף החקלאות של הלשכה המרכזית לסטטיסטיקה עמד ב{month} על "
            f"{lvl_txt} נקודות (בסיס {latest_base} = 100){change_txt}. המדד עוקב אחר המחירים "
            "שמשלמים החקלאים על מספוא, דשנים, חומרי הדברה, מים, דלק וחשמל, מיכון, עבודה שכירה "
            f"ושאר התשומות, ללא מע\"מ. בעמוד: ערכי המדד בכל חודש מאז {first.year}, גידולים צמחיים "
            "מול בעלי חיים, הפירוט לפי קבוצות ותשומות נבחרות כמו סולר, חשמל ותערובות.")
    summary = (f"מדד מחירי התשומה בחקלאות ל{month}: {lvl_txt} נקודות (בסיס {latest_base} = 100)"
               + (f", {_spi(p_last)} בחודש ו-{_spi(py_last)} בשנה" if change_txt else "")
               + f". ערכי המדד מאז {first.year}, גידולים צמחיים ובעלי חיים, ופירוט לפי קבוצות.")
    desc = (f"מדד מחירי התשומה בחקלאות האחרון ל{month}: {lvl_txt} נקודות"
            + (f", שינוי שנתי {_sp(py_last)}" if py_last is not None else "")
            + ". מספוא, דשנים, סולר, חשמל ומים לפי חודש, מאז "
            + f"{first.year}.")

    labels = {
        "lede": lede,
        "level_kpi": f"המדד הכללי, {month} (בסיס {latest_base} = 100)",
        "mom_kpi": f"שינוי חודשי ({month})",
        "yoy_kpi": "שינוי ב-12 החודשים האחרונים",
        "crops_kpi": "גידולים צמחיים, שינוי שנתי",
        "livestock_kpi": "בעלי חיים, שינוי שנתי",
        "recent_note": (f"השינוי החודשי (עמודות) והשינוי לעומת החודש המקביל אשתקד (קו) ב-{len(recent)} "
                        "החודשים האחרונים, כפי שפרסמה הלמ\"ס. בטבלה: ערך המדד שפורסם בכל חודש "
                        "והבסיס שלו."),
        "recent_aria": (f"תרשים עמודות וקו: השינוי החודשי והשנתי במדד מחירי התשומה בחקלאות ב-"
                        f"{len(recent)} החודשים האחרונים."),
        "recent_caption": f"ערכי מדד מחירי התשומה בחקלאות ב-{len(recent)} החודשים האחרונים",
        "history_note": (f"כל ערכי המדד מ{fmt.month_he(first)} ועד {month}, על בסיס אחד ({chain_base} = 100) "
                         "לפי מקדמי הקישור הרשמיים של הלמ\"ס. הציר האנכי לוגריתמי, כי באינפלציה של "
                         f"שנות ה-70 וה-80 המדד גדל פי כמה בשנה; מאז {first.year} הוא גדל פי "
                         f"{mult_txt} בערך. אפשר לגרור את פס הזמן כדי להתמקד בתקופה."),
        "history_aria": (f"גרף קו לוגריתמי: מדד מחירי התשומה בחקלאות מ-{first.year} עד {last.year} "
                         f"על בסיס {chain_base} = 100; כיום {fmt.num_he(v_last, 1)}."),
        "history_caption": f"המדד בדצמבר של כל שנה והשינוי השנתי, {first.year} עד {last.year}",
        "history_level_col": f"המדד בדצמבר (בסיס {chain_base} = 100)",
    }
    if ann:
        labels.update(
            annual_note=(f"השינוי במדד מדצמבר לדצמבר ב-{len(ann)} השנים השלמות האחרונות "
                         f"({ann[0]['year']} עד {ann[-1]['year']}), כפי שפורסם. ממוצע התקופה "
                         f"{_pc(ann_avg)} בשנה; השנה הגבוהה {ann_max['year']} ({_pc(ann_max['py'])})"
                         f" והנמוכה {ann_min['year']} ({_pc(ann_min['py'])})."),
            annual_aria=(f"תרשים עמודות: השינוי השנתי במדד מחירי התשומה בחקלאות, {ann[0]['year']} עד "
                         f"{ann[-1]['year']}."),
            annual_caption=f"השינוי השנתי במדד, {ann[0]['year']} עד {ann[-1]['year']}",
        )
    if rebased:
        top_name = max(rebased["ends"], key=lambda k: (rebased["ends"][k], k))
        low_name = min(rebased["ends"], key=lambda k: (rebased["ends"][k], k))
        labels.update(
            rebased_note=(f"המדד הכללי, התשומות בגידולים צמחיים ובבעלי חיים, המדד ללא עבודה שכירה "
                          f"ועלות העבודה השכירה, כשכל סדרה מתחילה ב-100 ב{fmt.month_he(start)}. "
                          f"מאז עלתה ביותר הסדרה \"{top_name}\" ({fmt.num_he(rebased['ends'][top_name], 1)}) "
                          f"ופחות מכולן \"{low_name}\" ({fmt.num_he(rebased['ends'][low_name], 1)})."),
            rebased_aria=(f"גרף קווים: המדד הכללי, גידולים צמחיים, בעלי חיים ועבודה שכירה מ"
                          f"{fmt.month_he(start)} עד {month}, {fmt.month_he(start)} = 100."),
            rebased_caption=f"המדד ומרכיביו, {fmt.month_he(start)} = 100",
        )
    if cvl:
        labels.update(
            cvl_note=(f"השינוי לעומת החודש המקביל אשתקד בתשומות בגידולים צמחיים ובבעלי חיים, מ{cvl['since']}. "
                      f"התשומות בגידולים צמחיים עלו מהר יותר מאלה של בעלי החיים ב-{cvl['cr_above']:,} "
                      f"מתוך {cvl['n']:,} החודשים."),
            cvl_aria=(f"גרף קווים: השינוי השנתי בתשומות בגידולים צמחיים, בבעלי חיים ובמדד הכללי מ"
                      f"{cvl['since']} עד {month}."),
            cvl_caption=f"השינוי השנתי בגידולים צמחיים ובבעלי חיים, בדצמבר של כל שנה וב{month}",
        )
    if drivers:
        labels.update(
            drivers_note=((f"{TOP_N} הקבוצות שהתייקרו ביותר ו-{TOP_N} שהתייקרו פחות מכולן "
                           f"מתוך {drivers['n']:,}, " if drivers["cut"] else
                           f"{drivers['n']:,} הקבוצות הראשיות של המדד, ")
                          + f"לפי השינוי ב-12 החודשים שעד {month}. הנתונים כאן אינם כוללים את "
                          "משקלות הקבוצות, ולכן מוצג שינוי המחיר בלבד ולא התרומה לשינוי במדד."),
            drivers_aria=(f"תרשים עמודות אופקי: השינוי השנתי בקבוצות הראשיות של מדד מחירי התשומה "
                          f"בחקלאות, {month}; הגבוה {drivers['names'][0]} ({_pc(drivers['y'][0])})."),
            drivers_caption=f"השינוי ב-12 החודשים שעד {month} לפי קבוצה",
        )
    if decade:
        miss = (f" {decade['missing']:,} קבוצות שנוספו לסל המדד מאוחר יותר אינן מופיעות כאן."
                if decade["missing"] else "")
        labels.update(
            decade_note=((f"{TOP_N} הקבוצות שעלו ביותר ו-{TOP_N} שעלו פחות מכולן מתוך {decade['n']:,}"
                          if decade["cut"] else f"{decade['n']:,} הקבוצות הראשיות")
                         + f", לפי השינוי המצטבר מ{fmt.month_he(cum)} עד {month}. "
                         f"המדד הכללי עלה באותה תקופה ב-{_pc(decade['gen'])} (הקו האנכי)." + miss),
            decade_aria=(f"תרשים עמודות אופקי: השינוי המצטבר בקבוצות הראשיות מ{fmt.month_he(cum)} "
                         f"עד {month}; הגבוה {decade['names'][0]} ({_pc(decade['y'][0])})."),
            decade_caption=f"השינוי המצטבר מ{fmt.month_he(cum)} עד {month} לפי קבוצה",
        )
    if selected:
        labels.update(
            selected_note=(f"השינוי ב-12 החודשים שעד {month} במחירי תשומות נבחרות: דלקים, חשמל, "
                           "תערובות מספוא, דשנים וקוטלי עשבים, כפי שפרסמה הלמ\"ס."
                           + (f" בטבלה גם השינוי החודשי והשינוי המצטבר מ{fmt.month_he(cum)}."
                              if cum is not None else "")),
            selected_aria=(f"תרשים עמודות אופקי: השינוי השנתי בתשומות נבחרות בחקלאות, {month}; "
                           f"הגבוה {selected['names'][0]} ({_pc(selected['y'][0])})."),
            selected_caption=f"תשומות נבחרות: השינוי ב-12 החודשים שעד {month}",
            sel_dec_col=f"שינוי מ{fmt.month_he(cum)}" if cum is not None else "שינוי מצטבר",
        )
    if energy:
        labels.update(
            energy_note=(f"מחירי הסולר, הבנזין והחשמל לחקלאות, כשכל סדרה מתחילה ב-100 ב{fmt.month_he(start)}. "
                         "קו החשמל קופץ ויורד כמה פעמים בשנה בגלל התעריף העונתי (תעריף גבוה בקיץ "
                         "ובחורף, נמוך בעונות המעבר)."),
            energy_aria=(f"גרף קווים: סולר, בנזין וחשמל מ{fmt.month_he(start)} עד {month}, "
                         f"{fmt.month_he(start)} = 100."),
            energy_caption=f"סולר, בנזין וחשמל, {fmt.month_he(start)} = 100",
        )
    if feed:
        f_top = max(feed["ends"], key=lambda k: (feed["ends"][k], k))
        labels.update(
            feed_note=(f"תערובות מספוא לעופות ולבקר ודשנים, כשכל סדרה מתחילה ב-100 ב{fmt.month_he(start)}. "
                       f"הגבוהה כיום: \"{f_top}\" ({fmt.num_he(feed['ends'][f_top], 1)})."),
            feed_aria=(f"גרף קווים: תערובות מספוא ודשנים מ{fmt.month_he(start)} עד {month}, "
                       f"{fmt.month_he(start)} = 100."),
            feed_caption=f"תערובות מספוא ודשנים, {fmt.month_he(start)} = 100",
        )
    labels.update(
        heat_note=(f"השינוי החודשי במדד הכללי בכל חודש מ-{heat_years[0]} עד {last.year}, כפי שפורסם. "
                   "כחול כהה הוא עלייה, אדום הוא ירידה."),
        heat_aria=(f"מפת חום: השינוי החודשי במדד מחירי התשומה בחקלאות לפי חודש ושנה, "
                   f"{heat_years[0]} עד {last.year}."),
        heat_caption=f"השינוי החודשי במדד לפי חודש ושנה, {heat_years[0]} עד {last.year}",
        groups_caption=f"כל הקבוצות הראשיות: שינוי חודשי ושנתי ב{month}"
                       + (f" ושינוי מצטבר מ{fmt.month_he(cum)}" if cum is not None else ""),
        groups_note=f"השינויים בכל הקבוצות הראשיות של המדד ב{month}.",
        dec_col=f"שינוי מ{fmt.month_he(cum)}" if cum is not None else "",
        base_note=(f"הלמ\"ס מחליפה את בסיס המדד מעת לעת (הבסיס הנוכחי: {chain_base} = 100). ערך "
                   "שפורסם על בסיס קודם מוצג בטבלה עם הבסיס שלו; הגרפים מציגים את כל הסדרה על הבסיס "
                   "הנוכחי לפי מקדמי הקישור הרשמיים. שינויים מצטברים שחושבו כאן מתוך הסדרה המקושרת "
                   "עשויים להיות שונים במעט מחישוב לפי ערכים מעוגלים."),
    )

    def lines(r):
        return {"lines": r["lines"]} if r else None

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first.strftime('%Y-%m')}/{last.strftime('%Y-%m')}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד מחירי תשומה בחקלאות: ערכי המדד והשינוי החודשי",
                "description": desc,
                "name": "מדד מחירי תשומה בחקלאות",
                "alternate_names": ["מדד תשומות החקלאות", "מדד תשומה בחקלאות",
                                    "מדד מחירי תשומה בענף החקלאות", "מדד תשומות חקלאיות"],
            },
        },
        "kpis": kpis,
        "charts": {
            "recent": recent_chart,
            "history": history,
            "annual": annual_chart,
            "rebased": lines(rebased),
            "cvl": {k: cvl[k] for k in ("x", "cr", "lv", "gen")} if cvl else None,
            "drivers": {"names": drivers["names"], "y": drivers["y"]} if drivers else None,
            "decade": ({"names": decade["names"], "y": decade["y"], "gen": decade["gen"]}
                       if decade else None),
            "selected": {"names": selected["names"], "y": selected["y"]} if selected else None,
            "energy": lines(energy),
            "feed": lines(feed),
            "heat": heat,
        },
        "tables": {
            "recent": recent_table,
            "annual_all": annual_table,
            "annual": annual_small,
            "rebased_cols": rebased["cols"] if rebased else [],
            "rebased": rebased["rows"] if rebased else [],
            "cvl": cvl["rows"] if cvl else [],
            "drivers": drivers["rows"] if drivers else [],
            "decade": decade["rows"] if decade else [],
            "selected": selected["rows"] if selected else [],
            "energy_cols": energy["cols"] if energy else [],
            "energy": energy["rows"] if energy else [],
            "feed_cols": feed["cols"] if feed else [],
            "feed": feed["rows"] if feed else [],
            "heat": heat_rows,
            "groups": all_groups,
        },
        "flags": {
            "annual": bool(ann), "rebased": bool(rebased), "cvl": bool(cvl),
            "drivers": bool(drivers), "decade": bool(decade), "groups": bool(all_groups),
            "selected": bool(selected), "energy": bool(energy), "feed": bool(feed),
        },
        "insights": insights,
        "labels": labels,
    }
