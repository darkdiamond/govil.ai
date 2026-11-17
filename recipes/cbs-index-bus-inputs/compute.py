"""מדד מחירי תשומה באוטובוסים: the CBS bus input price indices.

Inputs (CBS Index API, provider `cbs_index`; one row per code and month):
  buses    buses for the whole population (chapter f, subject 58): the
           general index (440010, monthly since 2005), the index without
           wages, and the main and secondary groups.
  lines    scheduled-line buses (subject 171, since 2020): general index and
           main groups.
  minibus  public minibuses / shared taxis (chapter fa): the general index
           with wages (432005, since mid-2020), CBS's main code without wages
           (432010, since 2008) and the groups.

Rules (BRIEF.md, Source rules): levels and long-run ratios use VALUE_CHAINED;
month-on-month and year-on-year changes are CBS's published PERCENT /
PERCENT_YEAR, quoted as published.

Chain repair: at two base switches the chained series jumps against the
published monthly change (buses, Feb 2007: the old-base rows lack the
1993->2007 link; minibuses, May 2020: one row carries the old-base value under
the new base label). `_relink` walks each series from the newest month back and,
wherever the chained step disagrees with the published PERCENT by more than
RELINK_PP points, rescales the older rows so that step equals PERCENT, the
same method the provider uses where CBS publishes no coefficient. A clean
series is left untouched.

The bus general index is required; every other code is optional, so a code
CBS retires drops its views instead of failing the page. An unknown code
renders under CBS's own NAME_HE.
"""
import pandas as pd
from govlib import fmt

BUS = 440010
BUS_NO_WAGES = 440070
LINES = 451010
MINI = 432005          # minibuses incl. wages (since mid-2020)
MINI_NO_WAGES = 432010  # CBS's main code for the chapter (since 2008)
FUEL = 440150
DRIVERS = 440090

HEADS = [(BUS, "אוטובוסים, כלל האוכלוסייה"), (LINES, "אוטובוסים בקווים קבועים"),
         (MINI, "אוטובוסים זעירים ציבוריים")]

SHORT = {
    BUS: "המדד הכללי",
    BUS_NO_WAGES: "המדד ללא שכר",
    440080: "שכר (תמורה למשרות שכיר)",
    440140: "אנרגיה, שמנים ונוזלי קירור",
    440150: "דלק",
    440170: "רכב",
    440180: "אחזקת אוטובוסים",
    440260: "אחזקת מבנים והוצאות משרד",
    440330: "מסים, אגרות, רישיונות וביטוח",
    440370: "שונות",
    LINES: "קווים קבועים: המדד הכללי",
    451020: "המדד ללא שכר",
    451030: "שכר (תמורה למשרות שכיר)",
    451280: "שונות",
    MINI: "זעירים: המדד הכללי",
    MINI_NO_WAGES: "זעירים: המדד ללא שכר",
    432030: "זעירים: המדד ללא דלקים",
    432100: "שכר (תמורה למשרות שכיר)",
    432370: "שונות",
}

# The full table: (code, depth) per index, in CBS's catalog order.
ROWS = {
    "buses": [(440010, 0), (440070, 1), (440080, 1), (440090, 2), (440100, 2), (440110, 2),
              (440140, 1), (440150, 2), (440170, 1), (440180, 1), (440200, 2), (440210, 2),
              (440220, 2), (440260, 1), (440330, 1), (440360, 2), (440370, 1)],
    "lines": [(451010, 0), (451020, 1), (451030, 1), (451040, 2), (451070, 1), (451090, 2),
              (451120, 1), (451130, 1), (451170, 1), (451230, 1), (451270, 2), (451280, 1)],
    "minibus": [(432005, 0), (432010, 0), (432030, 0), (432100, 1), (432110, 2), (432140, 1),
                (432150, 2), (432170, 1), (432180, 1), (432200, 2), (432210, 2), (432350, 1),
                (432360, 1), (432370, 1)],
}
INDEX_NAMES = {"buses": "אוטובוסים, כלל האוכלוסייה", "lines": "אוטובוסים בקווים קבועים",
               "minibus": "אוטובוסים זעירים ציבוריים (מוניות שירות)"}

# Main groups of the bus index for the rebased chart.
BUS_MAIN = [440010, 440080, 440140, 440170, 440180, 440260, 440330, 440370]
# Bus leaf groups ranked in the "which inputs moved" insight.
BUS_LEAVES = [440090, 440100, 440110, 440150, 440170, 440200, 440210, 440220,
              440260, 440360, 440370]
# The same input across the three indices: (label, bus, lines, minibus).
COMPARE = [
    ("נהגים", 440090, 451040, 432110),
    ("דלק", 440150, 451090, 432150),
    ("רכב", 440170, 451120, 432170),
    ("אחזקת אוטובוסים", 440180, 451130, 432180),
    ("חלפים", 440200, None, 432200),
    ("צמיגים", 440210, None, 432210),
    ("ביטוח", 440360, 451270, 432360),
    ("שונות", 440370, 451280, 432370),
]

RELINK_PP = 1.0
RECENT_MONTHS = 24
REBASE_YEARS = 10


# ── parsing ──────────────────────────────────────────────────────────────


def _relink(s):
    """Re-link chained levels where a step contradicts the published PERCENT.
    Returns (series, number of links repaired)."""
    v = s["v"].tolist()
    p = s["p"].tolist()
    t = list(s.index)
    fixed = 0
    factor = 1.0
    out = [None] * len(v)
    out[-1] = v[-1]
    for i in range(len(v) - 1, 0, -1):
        cur, prev = out[i], v[i - 1]
        if pd.isna(prev) or cur is None or pd.isna(cur):
            out[i - 1] = None if pd.isna(prev) else prev * factor
            continue
        # PERCENT is a one-month change: compare only consecutive months.
        if (t[i].year - t[i - 1].year) * 12 + t[i].month - t[i - 1].month != 1:
            out[i - 1] = prev * factor
            continue
        pub = p[i]
        step = (cur / (prev * factor) - 1) * 100 if prev else None
        if pd.notna(pub) and step is not None and abs(step - pub) > RELINK_PP:
            factor = cur / (1 + pub / 100) / prev
            fixed += 1
        out[i - 1] = prev * factor
    s = s.copy()
    s["v"] = out
    return s, fixed


def _load(frames):
    """code → DataFrame indexed by month (Timestamp), monthly rows only;
    plus names, the resource each code came from, and repaired-link count."""
    out, names, origin = {}, {}, {}
    relinked = 0
    for key in ("buses", "lines", "minibus"):
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
            s = s[s["v"].notna()]
            if s.empty:
                continue
            s, n = _relink(s)
            relinked += n
            out[code] = s
            names[code] = s["name"].iloc[-1]
            origin[code] = key
    return out, names, origin, relinked


def _label(code, names):
    return SHORT.get(code) or names.get(code) or str(code)


def _base_he(desc):
    """'2020 ינואר' → 'ינואר 2020'."""
    parts = (desc or "").split()
    if len(parts) == 2 and parts[0].isdigit():
        return f"{parts[1]} {parts[0]}"
    return desc or ""


# ── formatting ───────────────────────────────────────────────────────────


def _sp(v, digits=1):
    """A change in percent, signed: 0.1 → '+0.1%', -0.4 → '−0.4%'."""
    body = f"{abs(v):.{digits}f}"
    if float(body) == 0:
        return f"{body}%"
    return ("+" if v > 0 else fmt.MINUS) + body + "%"


def _spi(v, digits=1):
    return fmt.isolate(_sp(v, digits))


def _pc(v, digits=1):
    """A change in prose without a plus sign; a negative is isolated."""
    if v < 0 and float(f"{abs(v):.{digits}f}") != 0:
        return fmt.isolate(fmt.MINUS + f"{abs(v):.{digits}f}%")
    return f"{abs(v):.{digits}f}%"


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


def insight_latest(bus, last):
    p, py = _at(bus, last, "p"), _at(bus, last, "py")
    if p is None or py is None:
        return None
    return (f"מדד מחירי התשומה באוטובוסים לחודש {fmt.month_he(last)} {_moved(p)} לעומת החודש "
            f"הקודם. ב-12 החודשים האחרונים המדד {_moved(py)}.")


def insight_three_way(series, last):
    vals = []
    for code, name in HEADS:
        v = _at(series.get(code), last, "py")
        if v is not None:
            vals.append((name, v))
    if len(vals) < 2:
        return None
    parts = fmt.join_he([f"{n} {_spi(v)}" for n, v in vals])
    s = f"השינוי ב-12 החודשים שעד {fmt.month_he(last)}: {parts}."
    hi = max(vals, key=lambda x: (x[1], x[0]))
    lo = min(vals, key=lambda x: (x[1], x[0]))
    if hi[1] - lo[1] >= 1.0:
        verb = "עלה מהר יותר" if lo[1] >= 0 else ("ירד פחות" if hi[1] < 0 else "עלה")
        s += (f" המדד של {hi[0]} {verb}, בפער של {fmt.num_he(hi[1] - lo[1], 1)} "
              "נקודות אחוז.")
    return s


def insight_fuel_wages(series, last):
    fuel, drv = series.get(FUEL), series.get(DRIVERS)
    fp, dp = _at(fuel, last, "py"), _at(drv, last, "py")
    if fp is None or dp is None:
        return None
    s = (f"באוטובוסים מחיר הדלק {_moved(fp)} ב-12 החודשים שעד {fmt.month_he(last)}, "
         f"ושכר הנהגים {_moved(dp)}.")
    if fp - dp >= 3:
        s += " הדלק התייקר מהר יותר משכר הנהגים."
    elif dp - fp >= 3:
        s += " השכר עלה מהר יותר מהדלק."
    return s


def insight_since(start, ends):
    if start is None or len(ends) < 2:
        return None
    hi = max(ends, key=lambda x: (x[1], x[0]))
    lo = min(ends, key=lambda x: (x[1], x[0]))
    parts = fmt.join_he([f"{n} {_spi(v - 100)}" for n, v in ends])
    s = f"השינוי המצטבר מאז {fmt.month_he(start)}: {parts}."
    if hi[1] - lo[1] >= 2:
        s += f" הפער הגדול ביותר הוא בין {hi[0]} ל{lo[0]}."
    return s


def insight_drivers(movers):
    up = [m for m in movers if m["py"] > 0]
    down = [m for m in movers if m["py"] < 0]
    if not up:
        return None
    names = fmt.join_he([f"{m['name']} ({_pc(m['py'])})" for m in up[:2]])
    s = f"מלבד הדלק ושכר הנהגים, בתשומות של אוטובוסים התייקרו ביותר בשנה האחרונה: {names}."
    if down:
        low = down[-1]
        s += f" הירידה החדה ביותר: {low['name']} ({_pc(low['py'])})."
    return s


def insight_divergence(cmp_rows):
    best = None
    for r in cmp_rows:
        b, m = r["bus"], r["mini"]
        if b is None or m is None:
            continue
        gap = b - m
        if best is None or abs(gap) > abs(best[1]):
            best = (r["label"], gap, b, m)
    if best is None or abs(best[1]) < 3:
        return None
    name, gap, b, m = best
    return (f"הפער הגדול ביותר בין אוטובוסים לאוטובוסים זעירים הוא בסעיף {name}: "
            f"{_spi(b)} באוטובוסים לעומת {_spi(m)} באוטובוסים הזעירים בשנה האחרונה, "
            f"הפרש של {fmt.num_he(abs(gap), 1)} נקודות אחוז.")


def insight_biggest_month(bus, last):
    p = bus["p"].dropna()
    win = p[p.index > _months_back(last, 120)]
    if len(win) < 24:
        return None
    mx = float(win.max())
    if mx < 1:
        return None
    t = win[win == mx].index[-1]
    med = float(win.median())
    return (f"העלייה החודשית החדה ביותר במדד ב-10 השנים האחרונות: {_pc(mx)} ב{fmt.month_he(t)}, "
            f"לעומת שינוי חודשי חציוני של {_pc(med)}.")


def insight_yoy_trend(bus, last):
    now, prev_t = _at(bus, last, "py"), _months_back(last, 12)
    before = _at(bus, prev_t, "py")
    if now is None or before is None:
        return None
    d = now - before
    if abs(d) < 0.3:
        return (f"קצב השינוי השנתי במדד יציב: {_spi(now)} ב{fmt.month_he(last)}, "
                f"לעומת {_spi(before)} ב{fmt.month_he(prev_t)}.")
    if now > 0 and before > 0:
        head = "קצב העלייה השנתי במדד " + ("התגבר" if d > 0 else "התמתן")
    else:
        head = "השינוי השנתי במדד " + ("עלה" if d > 0 else "ירד")
    return f"{head}: מ-{_spi(before)} ב{fmt.month_he(prev_t)} ל-{_spi(now)} ב{fmt.month_he(last)}."


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    series, names, origin, relinked = _load(frames)
    bus = series.get(BUS)
    if bus is None:
        raise ValueError("no rows for the bus general index (code 440010)")
    last = bus.index[-1]
    first = bus.index[0]
    chain_base = _base_he(bus["chain"].iloc[-1])
    latest_value = _at(bus, last, "value")
    latest_base = _base_he(bus.at[last, "base"])
    p_last, py_last = _at(bus, last, "p"), _at(bus, last, "py")
    month = fmt.month_he(last)
    v_last = float(bus.at[last, "v"])

    heads = [(code, name, series[code]) for code, name in HEADS
             if code in series and series[code].index[-1] == last]
    if MINI not in series and MINI_NO_WAGES in series and series[MINI_NO_WAGES].index[-1] == last:
        heads.append((MINI_NO_WAGES, "אוטובוסים זעירים (ללא שכר)", series[MINI_NO_WAGES]))

    # ── KPIs ──
    lvl = latest_value if latest_value is not None else v_last
    kpis = {"level": {"value": lvl, "display": fmt.num_he(lvl, 1), "tone": "brand"}}
    if p_last is not None:
        kpis["mom"] = {"value": p_last, "display": _sp(p_last),
                       "tone": "warn" if p_last >= 1 else "ok" if p_last < 0 else "brand"}
    if py_last is not None:
        kpis["yoy"] = {"value": py_last, "display": _sp(py_last),
                       "tone": "warn" if py_last >= 5 else "ok" if py_last <= 0 else "brand"}
    for key, code in (("lines", LINES), ("mini", MINI), ("fuel", FUEL)):
        v = _at(series.get(code), last, "py")
        if v is not None:
            kpis[key] = {"value": v, "display": _sp(v), "tone": "brand"}

    # ── 1. recent months: bus m/m bars + y/y lines of the three indices ──
    recent = bus.iloc[-RECENT_MONTHS:]
    recent_chart = {
        "x": [f"{fmt.MONTHS_SHORT_HE[t.month - 1]} {t.year}" for t in recent.index],
        "mom": [None if pd.isna(x) else _r1(x) for x in recent["p"]],
        "lines": [{"name": name, "data": [_at(s, t, "py") for t in recent.index]}
                  for _code, name, s in heads],
    }
    recent_table = []
    for t, r in recent.iloc[::-1].iterrows():
        row = [fmt.month_he(t),
               fmt.num_he(r["value"], 1) if pd.notna(r["value"]) else "–",
               _sp(r["p"]) if pd.notna(r["p"]) else "–"]
        for _code, _name, s in heads:
            v = _at(s, t, "py")
            row.append(_sp(v) if v is not None else "–")
        recent_table.append(row)
    recent_cols = ["חודש", "המדד שפורסם (אוטובוסים)", "שינוי חודשי"] + [
        f"שינוי שנתי: {name}" for _c, name, _s in heads]

    # ── 2. the three headline indices from their common start ──
    common = None
    if len(heads) >= 2:
        common = max(s.index[0] for _c, _n, s in heads)
    compare = None
    ends = []
    if common is not None:
        lines = []
        for _code, name, s in heads:
            v0 = _at(s, common)
            win = s.loc[common:last, "v"].dropna()
            if v0 is None or v0 <= 0:
                continue
            lines.append({"name": name,
                          "data": [[t.strftime("%Y-%m"), _r1(v / v0 * 100)] for t, v in win.items()]})
            ends.append((name, float(win.iloc[-1]) / v0 * 100))
        if len(lines) >= 2:
            ticks = [t for t in bus.loc[common:last].index if t.month in (1, 7)]
            if not ticks or ticks[-1] != last:
                ticks.append(last)
            rows = []
            for t in reversed(ticks):
                row = [fmt.month_he(t)]
                for _code, _name, s in heads:
                    v, v0 = _at(s, t), _at(s, common)
                    row.append(fmt.num_he(v / v0 * 100, 1) if v is not None and v0 else "–")
                rows.append(row)
            compare = {"lines": lines, "cols": [n for _c, n, _s in heads], "rows": rows}
        else:
            ends = []

    # ── 3. bus index history on the newest base ──
    history = [[t.strftime("%Y-%m"), round(float(v), 2)] for t, v in bus["v"].items()]
    dec = bus[bus.index.month == 12]
    annual_table = [[str(t.year), fmt.num_he(r["v"], 1),
                     _sp(r["py"]) if pd.notna(r["py"]) else "–"] for t, r in dec.iterrows()]
    if last.month != 12:
        annual_table.append([f"{month} (12 חודשים)", fmt.num_he(v_last, 1),
                             _sp(py_last) if py_last is not None else "–"])
    annual_table.reverse()
    ann = [(t.year, float(r["py"])) for t, r in dec.iterrows() if pd.notna(r["py"])]

    # ── 4. bus main groups rebased ──
    start = pd.Timestamp(year=last.year - REBASE_YEARS, month=1, day=1)
    if start not in bus.index:
        start = None
    rebased = None
    if start is not None:
        lines, cols = [], []
        for code in BUS_MAIN:
            s = series.get(code)
            if s is None:
                continue
            v0 = _at(s, start)
            win = s.loc[start:last, "v"].dropna()
            if v0 is None or v0 <= 0 or win.empty or win.index[-1] != last:
                continue
            lines.append({"name": _label(code, names),
                          "data": [[t.strftime("%Y-%m"), _r1(v / v0 * 100)] for t, v in win.items()]})
            cols.append((code, s, v0))
        if len(lines) >= 3:
            ticks = [t for t in bus.loc[start:last].index if t.month == 1]
            if ticks[-1] != last:
                ticks.append(last)
            rows = []
            for t in reversed(ticks):
                row = [fmt.month_he(t)]
                for _code, s, v0 in cols:
                    v = _at(s, t)
                    row.append(fmt.num_he(v / v0 * 100, 1) if v is not None else "–")
                rows.append(row)
            rb_ends = {line["name"]: line["data"][-1][1] for line in lines[1:]}
            rebased = {"lines": lines, "cols": [line["name"] for line in lines], "rows": rows,
                       "ends": rb_ends, "gen": lines[0]["data"][-1][1]}

    # ── 5. fuel vs drivers' wages, published year-on-year ──
    fvw = None
    fuel, drv = series.get(FUEL), series.get(DRIVERS)
    if fuel is not None and drv is not None:
        both = pd.concat({"fuel": fuel["py"], "drv": drv["py"], "gen": bus["py"]}, axis=1)
        both = both.dropna(subset=["fuel", "drv"]).loc[:last]
        if len(both) >= 24:
            fvw = {
                "x": [t.strftime("%Y-%m") for t in both.index],
                "fuel": [_r1(v) for v in both["fuel"]],
                "drv": [_r1(v) for v in both["drv"]],
                "gen": [None if pd.isna(v) else _r1(v) for v in both["gen"]],
                "since": fmt.month_he(both.index[0]),
                "fuel_max": float(both["fuel"].max()),
                "fuel_max_t": fmt.month_he(both["fuel"].idxmax()),
                "fuel_min": float(both["fuel"].min()),
                "fuel_min_t": fmt.month_he(both["fuel"].idxmin()),
                "drv_min": float(both["drv"].min()),
                "drv_max": float(both["drv"].max()),
            }
            pts = [t for t in both.index if t.month == 12]
            if both.index[-1] not in pts:
                pts.append(both.index[-1])
            fvw["rows"] = [[fmt.month_he(t), _sp(both.at[t, "fuel"]), _sp(both.at[t, "drv"]),
                            _sp(both.at[t, "gen"]) if pd.notna(both.at[t, "gen"]) else "–"]
                           for t in reversed(pts)]

    # ── 6. the same input across the three indices ──
    cmp_rows = []
    for label, b, ln, m in COMPARE:
        bv = _at(series.get(b), last, "py")
        if bv is None:
            continue
        cmp_rows.append({"label": label, "bus": bv,
                         "lines": _at(series.get(ln), last, "py") if ln else None,
                         "mini": _at(series.get(m), last, "py") if m else None})
    cmp = None
    if len(cmp_rows) >= 4:
        cmp = {"names": [r["label"] for r in cmp_rows],
               "bus": [_r1(r["bus"]) for r in cmp_rows],
               "lines": [None if r["lines"] is None else _r1(r["lines"]) for r in cmp_rows],
               "mini": [None if r["mini"] is None else _r1(r["mini"]) for r in cmp_rows],
               "rows": [[r["label"], _sp(r["bus"]),
                         _sp(r["lines"]) if r["lines"] is not None else "–",
                         _sp(r["mini"]) if r["mini"] is not None else "–"] for r in cmp_rows]}

    # ── 7. all codes ──
    stale = _months_back(last, 12)
    groups = []
    for key in ("buses", "lines", "minibus"):
        known = [c for c, _d in ROWS[key]]
        extra = sorted(c for c, o in origin.items() if o == key and c not in known)
        rows = []
        for code, depth in ROWS[key] + [(c, 1) for c in extra]:
            s = series.get(code)
            if s is None or s.index[-1] <= stale:
                continue
            p, py = _at(s, s.index[-1], "p"), _at(s, s.index[-1], "py")
            v1, v0 = _at(s, s.index[-1]), _at(s, common) if common is not None else None
            cum = (v1 / v0 - 1) * 100 if v0 and v1 is not None else None
            rows.append({"name": names.get(code, str(code)) if depth == 0 else _label(code, names),
                         "depth": depth,
                         "p": _sp(p) if p is not None else "–",
                         "py": _sp(py) if py is not None else "–",
                         "cum": _sp(cum) if cum is not None else "–"})
        if rows:
            groups.append({"title": INDEX_NAMES[key], "rows": rows})

    movers = []
    for code in [c for c in BUS_LEAVES if c not in (FUEL, DRIVERS)]:
        v = _at(series.get(code), last, "py")
        if v is not None:
            movers.append({"code": code, "name": names.get(code, str(code)), "py": v})
    movers.sort(key=lambda g: (-g["py"], g["code"]))

    # ── insights ──
    rules = [
        ("latest", insight_latest(bus, last)),
        ("three_way", insight_three_way(series, last)),
        ("fuel_wages", insight_fuel_wages(series, last)),
        ("divergence", insight_divergence(cmp_rows)),
        ("since", insight_since(common, ends)),
        ("drivers", insight_drivers(movers)),
        ("biggest_month", insight_biggest_month(bus, last)),
        ("yoy_trend", insight_yoy_trend(bus, last)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── text ──
    lvl_txt = fmt.num_he(lvl, 1)
    change_txt = ""
    if p_last is not None and py_last is not None:
        change_txt = (f": שינוי של {_spi(p_last)} לעומת החודש הקודם ו-{_spi(py_last)} "
                      "לעומת החודש המקביל אשתקד")
    lede = (f"מדד מחירי התשומה באוטובוסים של הלשכה המרכזית לסטטיסטיקה עמד ב{month} על {lvl_txt} "
            f"נקודות (בסיס {latest_base} = 100){change_txt}. המדד עוקב אחר מחירי מה שמפעיל "
            "אוטובוסים משלם עליו: שכר נהגים ועובדים, דלק, רכישת אוטובוסים, חלפים וצמיגים, תיקונים, "
            "ביטוח, מסים ואגרות. בעמוד גם המדד לאוטובוסים בקווים קבועים והמדד לאוטובוסים זעירים "
            "ציבוריים (מוניות שירות), וההשוואה ביניהם.")
    summary = (f"מדד מחירי התשומה באוטובוסים ל{month}: {lvl_txt} נקודות (בסיס {latest_base} = 100)"
               + (f", {_spi(p_last)} בחודש ו-{_spi(py_last)} בשנה" if change_txt else "")
               + ". השוואה לקווים קבועים ולאוטובוסים זעירים, דלק מול שכר ופירוט לפי קבוצות.")
    desc = (f"מדד מחירי התשומה באוטובוסים ל{month}: {lvl_txt} נקודות"
            + (f", שינוי חודשי {_sp(p_last)} ושנתי {_sp(py_last)}" if change_txt else "")
            + f". ערכי המדד מאז {first.year}, מוניות שירות ופירוט לפי קבוצות.")

    labels = {
        "lede": lede,
        "level_kpi": f"מדד האוטובוסים, {month} (בסיס {latest_base} = 100)",
        "mom_kpi": f"שינוי חודשי ({month})",
        "yoy_kpi": "שינוי ב-12 החודשים האחרונים",
        "lines_kpi": "קווים קבועים, שינוי שנתי",
        "mini_kpi": "אוטובוסים זעירים, שינוי שנתי",
        "fuel_kpi": "דלק לאוטובוסים, שינוי שנתי",
        "recent_note": (f"השינוי החודשי במדד האוטובוסים (עמודות) והשינוי לעומת החודש המקביל אשתקד "
                        f"בשלושת המדדים (קווים) ב-{len(recent)} החודשים האחרונים, כפי שפרסמה הלמ\"ס."),
        "recent_aria": (f"תרשים עמודות וקווים: השינוי החודשי והשנתי במדדי התשומה באוטובוסים ב-"
                        f"{len(recent)} החודשים האחרונים."),
        "recent_caption": f"מדדי התשומה באוטובוסים ב-{len(recent)} החודשים האחרונים",
        "history_note": (f"מדד האוטובוסים בכל חודש מ{fmt.month_he(first)} ועד {month}, על בסיס אחד "
                         f"({chain_base} = 100). מאז {fmt.month_he(first)} המדד {_moved((v_last / float(bus["v"].iloc[0]) - 1) * 100)}. "
                         "אפשר לגרור את פס הזמן כדי להתמקד בתקופה."),
        "history_aria": (f"גרף קו: מדד מחירי התשומה באוטובוסים מ-{first.year} עד {last.year} על בסיס "
                         f"{chain_base} = 100; כיום {fmt.num_he(v_last, 1)}."),
        "history_caption": f"מדד האוטובוסים בדצמבר של כל שנה והשינוי השנתי, {first.year} עד {last.year}",
        "history_level_col": f"המדד בדצמבר (בסיס {chain_base} = 100)",
    }
    if ann:
        hi = max(ann, key=lambda a: (a[1], a[0]))
        lo = min(ann, key=lambda a: (a[1], -a[0]))
        labels["history_note"] += (f" השינוי השנתי הגבוה ביותר מדצמבר לדצמבר: {_pc(hi[1])} ב-{hi[0]}; "
                                   f"הנמוך ביותר: {_pc(lo[1])} ב-{lo[0]}.")
    if compare:
        hi = max(ends, key=lambda x: (x[1], x[0]))
        labels.update(
            compare_note=(f"שלושת המדדים הכלליים, כשכל אחד מתחיל ב-100 ב{fmt.month_he(common)}, החודש "
                          f"הראשון שבו מתפרסמים שלושתם. עד {month} עלה ביותר המדד של {hi[0]} "
                          f"({fmt.num_he(hi[1], 1)}). כל מדד בנוי מסל תשומות ומשקלות משלו."),
            compare_aria=(f"גרף קווים: מדד האוטובוסים, מדד הקווים הקבועים ומדד האוטובוסים הזעירים מ"
                          f"{fmt.month_he(common)} עד {month}, {fmt.month_he(common)} = 100."),
            compare_caption=f"שלושת המדדים, {fmt.month_he(common)} = 100",
        )
    if rebased:
        top_name = max(rebased["ends"], key=lambda k: (rebased["ends"][k], k))
        low_name = min(rebased["ends"], key=lambda k: (rebased["ends"][k], k))
        labels.update(
            rebased_note=(f"המדד הכללי לאוטובוסים והקבוצות הראשיות, כשכל סדרה מתחילה ב-100 ב"
                          f"{fmt.month_he(start)}. המדד הכללי הגיע ל-{fmt.num_he(rebased['gen'], 1)}; "
                          f"עלתה ביותר הקבוצה \"{top_name}\" ({fmt.num_he(rebased['ends'][top_name], 1)}) "
                          f"ופחות מכולן \"{low_name}\" ({fmt.num_he(rebased['ends'][low_name], 1)})."),
            rebased_aria=(f"גרף קווים: המדד הכללי לאוטובוסים והקבוצות הראשיות מ{fmt.month_he(start)} "
                          f"עד {month}, {fmt.month_he(start)} = 100."),
            rebased_caption=f"המדד והקבוצות הראשיות, {fmt.month_he(start)} = 100",
        )
    if fvw:
        labels.update(
            fvw_note=(f"השינוי לעומת החודש המקביל אשתקד בדלק ובשכר הנהגים באוטובוסים, מ{fvw['since']}. "
                      f"הדלק תנודתי: בין {_pc(fvw['fuel_min'])} ({fvw['fuel_min_t']}) ל-"
                      f"{_pc(fvw['fuel_max'])} ({fvw['fuel_max_t']}), ושכר הנהגים נע בין "
                      f"{_pc(fvw['drv_min'])} ל-{_pc(fvw['drv_max'])}."),
            fvw_aria=(f"גרף קווים: השינוי השנתי בדלק, בשכר הנהגים ובמדד האוטובוסים מ{fvw['since']} "
                      f"עד {month}."),
            fvw_caption=f"השינוי השנתי בדלק ובשכר הנהגים, בדצמבר של כל שנה ו{month}",
        )
    if cmp:
        labels.update(
            cmp_note=(f"השינוי ב-12 החודשים שעד {month} באותו סעיף בשלושת המדדים. אותו סעיף יכול "
                      "לנוע אחרת בכל מדד, כי הסוגים והמחירים של כלי הרכב, הדלק והביטוח שונים. "
                      "הנתונים אינם כוללים את משקלות הסעיפים, ולכן מוצג שינוי המחיר בלבד ולא "
                      "התרומה לשינוי במדד. מקף: הסעיף אינו מתפרסם במדד זה."),
            cmp_aria=(f"תרשים עמודות אופקי: השינוי השנתי לפי סעיף באוטובוסים, בקווים קבועים "
                      f"ובאוטובוסים זעירים, {month}."),
            cmp_caption=f"השינוי ב-12 החודשים שעד {month} לפי סעיף ומדד",
        )
    labels.update(
        groups_note=("השינוי החודשי והשנתי האחרון שפורסם בכל סדרה"
                     + (f", והשינוי המצטבר מ{fmt.month_he(common)}" if common is not None else "")
                     + ". קבוצה מוזחת היא חלק מהקבוצה שמעליה."),
        cum_col=f"שינוי מ{fmt.month_he(common)}" if common is not None else "",
        base_note=(f"הלמ\"ס מחליפה את בסיס המדד מעת לעת (הבסיס הנוכחי של מדד האוטובוסים: {chain_base} "
                   "= 100). הגרפים מציגים כל סדרה על הבסיס העדכני שלה לפי מקדמי הקישור הרשמיים. "
                   + ("במעבר בסיס שבו הסדרה המקושרת לא התיישבה עם השינוי החודשי שפורסם, היא קושרה "
                      "לפי השינוי החודשי שפורסם (דיוק של כעשירית האחוז). " if relinked else "")
                   + "שינויים מצטברים שחושבו כאן עשויים להיות שונים במעט מחישוב לפי ערכים מעוגלים."),
    )

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first.strftime('%Y-%m')}/{last.strftime('%Y-%m')}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד מחירי תשומה באוטובוסים: ערכי המדד והשינוי החודשי",
                "description": desc,
                "name": "מדד מחירי תשומה באוטובוסים",
                "alternate_names": ["מדד תשומות האוטובוסים", "מדד תשומה באוטובוסים",
                                    "מדד מחירי תשומה באוטובוסים זעירים ציבוריים",
                                    "מדד תשומות מוניות שירות"],
            },
        },
        "kpis": kpis,
        "charts": {
            "recent": recent_chart,
            "compare": {"lines": compare["lines"]} if compare else None,
            "history": history,
            "rebased": {"lines": rebased["lines"]} if rebased else None,
            "fvw": {k: fvw[k] for k in ("x", "fuel", "drv", "gen")} if fvw else None,
            "cmp": ({k: cmp[k] for k in ("names", "bus", "lines", "mini")} if cmp else None),
        },
        "tables": {
            "recent_cols": recent_cols,
            "recent": recent_table,
            "compare_cols": compare["cols"] if compare else [],
            "compare": compare["rows"] if compare else [],
            "annual_all": annual_table,
            "rebased_cols": rebased["cols"] if rebased else [],
            "rebased": rebased["rows"] if rebased else [],
            "fvw": fvw["rows"] if fvw else [],
            "cmp": cmp["rows"] if cmp else [],
            "groups": groups,
        },
        "flags": {
            "compare": bool(compare), "rebased": bool(rebased), "fvw": bool(fvw),
            "cmp": bool(cmp), "groups": bool(groups),
        },
        "insights": insights,
        "labels": labels,
    }
