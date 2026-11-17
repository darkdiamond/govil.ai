"""מדד תשומות הבנייה למסחר ולמשרדים: the CBS input price index for building
commercial and office buildings.

Inputs (CBS Index API, provider `cbs_index`; one row per code and month):
  main              the general index (800010, since 2012), the index without
                    labour (802010) and the four main groups: materials
                    (802020), equipment hire (802030), labour (802040), other
                    (802050); plus the residential general index (200010) for
                    the comparison.
  chapters_shell    work chapters: earthworks, concrete, precast, masonry,
                    insulation, carpentry, plaster, stone, heavy metalwork.
  chapters_systems  work chapters: sanitation, electricity, flooring, paint,
                    aluminium, air conditioning, lifts, industrialised
                    components, overhead.
  items             a selection of secondary groups (concrete, building iron,
                    cables, glass, curtain walls, diesel, …).

Rules (BRIEF.md, Source rules): levels and cumulative changes use
VALUE_CHAINED (every month on the newest base, CHAIN_BASE); month-on-month
and year-on-year changes are CBS's published PERCENT / PERCENT_YEAR, quoted
as published. The general index is required; every other code is optional,
so a code CBS retires (or a shorter input) drops its views instead of
failing the page. An unknown code renders under CBS's own NAME_HE.
"""
import pandas as pd
from govlib import fmt

GENERAL = 800010
NO_LABOUR = 802010
MATERIALS = 802020
EQUIPMENT = 802030
LABOUR = 802040
OTHER = 802050
RESIDENTIAL = 200010
MAIN_ORDER = [GENERAL, MATERIALS, LABOUR, EQUIPMENT, OTHER, NO_LABOUR]

SHORT = {
    GENERAL: "המדד הכללי",
    NO_LABOUR: "המדד ללא שכר עבודה",
    MATERIALS: "חומרים ומוצרים",
    EQUIPMENT: "שכירת ציוד",
    LABOUR: "שכר עבודה",
    OTHER: "שונות",
    RESIDENTIAL: "תשומות הבנייה למגורים",
    800080: "בטון (חומר)",
    800900: "מיזוג אוויר",
    800920: "מערכות מיזוג אוויר",
}

CHAPTER_INPUTS = ("chapters_shell", "chapters_systems")
# CBS's own catalog order (subject 150), used for the full table. Unknown
# chapter codes follow, by code.
CHAPTER_ORDER = [
    800020, 800060, 800190, 800220, 800270, 800340, 800390, 800490, 800630,
    800670, 800740, 800770, 800840, 800900, 801040, 801070, 801090, 801140,
]

RECENT_MONTHS = 24
TOP_N = 10


# ── parsing ──────────────────────────────────────────────────────────────


def _parse(df):
    """code → DataFrame indexed by month (Timestamp), sorted, monthly rows only."""
    out, names = {}, {}
    if df is None or df.empty:
        return out, names
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
        s = s.drop_duplicates("t", keep="last").set_index("t")
        if s["v"].notna().any():
            out[code] = s
            names[code] = s["name"].iloc[-1]
    return out, names


def _load(frames):
    """(series by input key, all names). A code already read from an earlier
    input is skipped in later ones."""
    by_key, names, seen = {}, {}, set()
    for key in ("main", "chapters_shell", "chapters_systems", "items"):
        s, n = _parse(frames.get(key))
        s = {c: v for c, v in s.items() if c not in seen}
        seen.update(s)
        by_key[key] = s
        names.update(n)
    return by_key, names


def _label(code, names):
    return SHORT.get(code) or names.get(code) or str(code)


def _base_he(desc):
    """'2012 ינואר' → 'ינואר 2012', '1968 ממוצע' → 'ממוצע 1968'."""
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
    """A signed change inside Hebrew prose, isolated so bidi keeps its sign."""
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


def _cum(s, start, last):
    """Cumulative change (%) from `start` to `last` on the chained series."""
    v0, v1 = _at(s, start), _at(s, last)
    if v0 is None or v1 is None or v0 <= 0:
        return None
    return (v1 / v0 - 1) * 100


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
    return (f"מדד תשומות הבנייה למסחר ולמשרדים לחודש {fmt.month_he(last)} {_moved(p)} לעומת "
            f"החודש הקודם. ב-12 החודשים האחרונים המדד {_moved(py)}.")


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


def insight_labour_materials(series, last, start):
    lab, mat = series.get(LABOUR), series.get(MATERIALS)
    lp, mp = _at(lab, last, "py"), _at(mat, last, "py")
    if lp is None or mp is None:
        return None
    head = (f"ב-12 החודשים שעד {fmt.month_he(last)} שכר העבודה בבנייה למסחר ולמשרדים "
            f"{_moved(lp)}, והחומרים והמוצרים {_moved(mp, plural=True)}.")
    lc, mc = _cum(lab, start, last), _cum(mat, start, last)
    if lc is not None and mc is not None:
        head += (f" מאז {fmt.month_he(start)} שכר העבודה {_moved(lc)} "
                 f"והחומרים {_moved(mc, plural=True)}.")
    return head


def insight_residential(gen, res, start, last):
    """Commercial vs residential: cumulative since the common start and the
    published 12-month change."""
    if res is None:
        return None
    c, r = _cum(gen, start, last), _cum(res, start, last)
    cp, rp = _at(gen, last, "py"), _at(res, last, "py")
    if c is None or r is None:
        return None
    s = (f"מאז {fmt.month_he(start)} מדד התשומות בבנייה למסחר ולמשרדים {_moved(c)}, "
         f"ומדד התשומות בבנייה למגורים {_moved(r)}.")
    if cp is not None and rp is not None:
        s += (f" ב-12 החודשים האחרונים: {_spi(cp)} במסחר ובמשרדים "
              f"ו-{_spi(rp)} במגורים.")
    return s


def _drivers_text(movers, what):
    up = [m for m in movers if m["py"] > 0]
    down = [m for m in movers if m["py"] < 0]
    if not up:
        return None
    names = fmt.join_he([f"{m['name']} ({_pc(m['py'])})" for m in up[:2]])
    s = f"{what} שהתייקרו ביותר בשנה האחרונה: {names}."
    if down:
        low = down[-1]
        s += f" הירידה החדה ביותר: {low['name']} ({_pc(low['py'])})."
    return s


def insight_chapters(movers):
    if len(movers) < 4:
        return None
    return _drivers_text(movers, "פרקי העבודה")


def insight_items(movers):
    if len(movers) < 4:
        return None
    return _drivers_text(movers, "מבין התשומות שבמבחר, אלה")


def insight_peak_year(ann):
    if len(ann) < 5:
        return None
    top = max(ann, key=lambda a: (a["py"], a["year"]))
    rest = [a["py"] for a in ann if a is not top]
    avg = sum(rest) / len(rest)
    if top["py"] < 2 * max(avg, 0.1):
        return None
    return (f"השנה שבה המדד עלה ביותר היא {top['year']}: {_pc(top['py'])} מדצמבר לדצמבר, "
            f"לעומת {_pc(avg)} בממוצע בשאר השנים מאז {ann[0]['year']}.")


def insight_biggest_month(gen, last):
    p = gen["p"].dropna()
    win = p[p.index > _months_back(last, 120)]
    if len(win) < 24:
        return None
    mx = float(win.max())
    if mx < 0.5:
        return None
    t = win[win == mx].index[-1]
    med = float(win.median())
    return (f"העלייה החודשית החדה ביותר ב-10 השנים האחרונות: {_pc(mx)} ב{fmt.month_he(t)}, "
            f"לעומת שינוי חודשי חציוני של {_pc(med)}.")


# ── sections ─────────────────────────────────────────────────────────────


def _rank(series, names, codes, start, last, order):
    """One row per code still published: published p / py, cumulative since start."""
    rows = []
    stale = _months_back(last, 12)
    for code in codes:
        s = series[code]
        if s.index[-1] <= stale:
            continue  # a code CBS stopped publishing
        rows.append({"code": code, "name": _label(code, names),
                     "p": _at(s, last, "p"), "py": _at(s, last, "py"),
                     "cum": _cum(s, start, last), "ord": order.get(code, 10**7 + code)})
    return rows


def _bars(rows, key):
    pick = sorted([g for g in rows if g[key] is not None], key=lambda g: (-g[key], g["code"]))
    if len(pick) < 4:
        return None, pick
    shown = pick if len(pick) <= 2 * TOP_N else pick[:TOP_N] + pick[-TOP_N:]
    return {"names": [g["name"] for g in shown], "y": [_r1(g[key]) for g in shown],
            "rows": [[g["name"], _sp(g["py"]) if g["py"] is not None else "–",
                      _sp(g["p"]) if g["p"] is not None else "–",
                      _sp(g["cum"]) if g["cum"] is not None else "–"] for g in shown],
            "n": len(pick), "cut": len(shown) < len(pick)}, pick


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    by_key, names = _load(frames)
    main = by_key["main"]
    gen = main.get(GENERAL)
    if gen is None:
        raise ValueError("no rows for the general index (code 800010)")
    gen = gen[gen["v"].notna()]
    last = gen.index[-1]
    first = gen.index[0]
    start = first
    chain_base = _base_he(gen["chain"].iloc[-1])
    latest_value = _at(gen, last, "value")
    latest_base = _base_he(gen.at[last, "base"])
    level = latest_value if latest_value is not None else _at(gen, last)
    p_last, py_last = _at(gen, last, "p"), _at(gen, last, "py")
    month = fmt.month_he(last)
    v_last = float(gen.at[last, "v"])
    res = main.get(RESIDENTIAL)
    if res is not None and (res.index[-1] < last or _at(res, start) is None):
        res = None  # the comparison needs the residential series over the same span

    # ── KPIs ──
    kpis = {"level": {"value": level, "display": fmt.num_he(level, 1), "tone": "brand"}}
    if p_last is not None:
        kpis["mom"] = {"value": p_last, "display": _sp(p_last),
                       "tone": "warn" if p_last >= 0.5 else "ok" if p_last < 0 else "brand"}
    if py_last is not None:
        kpis["yoy"] = {"value": py_last, "display": _sp(py_last),
                       "tone": "warn" if py_last >= 4 else "ok" if py_last <= 0 else "brand"}
    for key, code in (("labour", LABOUR), ("materials", MATERIALS)):
        v = _at(main.get(code), last, "py")
        if v is not None:
            kpis[key] = {"value": v, "display": _sp(v), "tone": "brand"}
    gen_cum = _cum(gen, start, last)

    # ── 1. recent months ──
    recent = gen.iloc[-RECENT_MONTHS:]
    recent_chart = {
        "x": [f"{fmt.MONTHS_SHORT_HE[t.month - 1]} {t.year}" for t in recent.index],
        "mom": [None if pd.isna(x) else _r1(x) for x in recent["p"]],
        "yoy": [None if pd.isna(x) else _r1(x) for x in recent["py"]],
    }
    recent_table = []
    for t, r in recent.iloc[::-1].iterrows():
        cum = "–" if t == last else _sp((v_last / float(r["v"]) - 1) * 100)
        recent_table.append([
            fmt.month_he(t),
            fmt.num_he(r["value"], 1) if pd.notna(r["value"]) else "–",
            _base_he(r["base"]),
            _sp(r["p"]) if pd.notna(r["p"]) else "–",
            _sp(r["py"]) if pd.notna(r["py"]) else "–",
            cum,
        ])

    # ── 2. history vs residential, both rebased to the start month ──
    v0 = float(gen.at[start, "v"])
    lines = [{"name": "בנייה למסחר ולמשרדים",
              "data": [[t.strftime("%Y-%m"), _r1(v / v0 * 100)] for t, v in gen["v"].items()]}]
    if res is not None:
        r0 = _at(res, start)
        rw = res.loc[start:last, "v"].dropna()
        lines.append({"name": "בנייה למגורים",
                      "data": [[t.strftime("%Y-%m"), _r1(v / r0 * 100)] for t, v in rw.items()]})
    res_cum = _cum(res, start, last) if res is not None else None

    # ── 3. annual change, December on December, both indices ──
    dec = gen[(gen.index.month == 12) & gen["py"].notna()]
    ann = [{"year": t.year, "py": float(r["py"]), "level": float(r["v"]),
            "res": _at(res, t, "py") if res is not None else None} for t, r in dec.iterrows()]
    annual_chart = {"x": [str(a["year"]) for a in ann], "y": [_r1(a["py"]) for a in ann],
                    "res": [None if a["res"] is None else _r1(a["res"]) for a in ann]}
    annual_rows = [[str(a["year"]), fmt.num_he(a["level"], 1), _sp(a["py"]),
                    _sp(a["res"]) if a["res"] is not None else "–"] for a in ann]
    if last.month != 12:
        rp = _at(res, last, "py") if res is not None else None
        annual_rows.append([f"{month} (12 חודשים)", fmt.num_he(v_last, 1),
                            _sp(py_last) if py_last is not None else "–",
                            _sp(rp) if rp is not None else "–"])
    annual_rows.reverse()
    ann_avg = sum(a["py"] for a in ann) / len(ann) if ann else None

    # ── 4. main groups rebased to the start month ──
    rebased = None
    glines, cols = [], []
    for code in MAIN_ORDER + sorted(c for c in main if c not in MAIN_ORDER and c != RESIDENTIAL):
        s = main.get(code)
        if s is None:
            continue
        b0 = _at(s, start)
        win = s.loc[start:last, "v"].dropna()
        if b0 is None or b0 <= 0 or win.empty or win.index[-1] != last:
            continue
        glines.append({"name": _label(code, names),
                       "data": [[t.strftime("%Y-%m"), _r1(v / b0 * 100)] for t, v in win.items()]})
        cols.append((s, b0))
    if len(glines) >= 2:
        ticks = [t for t in gen.index if t.month == 1 or t == start]
        if ticks[-1] != last:
            ticks.append(last)
        rows = []
        for t in reversed(ticks):
            row = [fmt.month_he(t)]
            for s, b0 in cols:
                v = _at(s, t)
                row.append(fmt.num_he(v / b0 * 100, 1) if v is not None else "–")
            rows.append(row)
        ends = {ln["name"]: ln["data"][-1][1] for ln in glines}
        rebased = {"lines": glines, "cols": [ln["name"] for ln in glines], "rows": rows,
                   "ends": ends}

    # ── 5. labour vs materials, published year-on-year ──
    lvm = None
    lab, mat = main.get(LABOUR), main.get(MATERIALS)
    if lab is not None and mat is not None:
        both = pd.concat({"lab": lab["py"], "mat": mat["py"], "gen": gen["py"]}, axis=1)
        both = both.dropna(subset=["lab", "mat"]).loc[:last]
        if len(both) >= 24:
            lvm = {
                "x": [t.strftime("%Y-%m") for t in both.index],
                "lab": [_r1(v) for v in both["lab"]],
                "mat": [_r1(v) for v in both["mat"]],
                "gen": [None if pd.isna(v) else _r1(v) for v in both["gen"]],
                "since": fmt.month_he(both.index[0]),
                "lab_above": int((both["lab"] > both["mat"]).sum()),
                "n": len(both),
            }
            pts = [t for t in both.index if t.month == 12]
            if both.index[-1] not in pts:
                pts.append(both.index[-1])
            lvm["rows"] = [[fmt.month_he(t), _sp(both.at[t, "lab"]), _sp(both.at[t, "mat"]),
                            _sp(both.at[t, "gen"]) if pd.notna(both.at[t, "gen"]) else "–"]
                           for t in reversed(pts)]

    # ── 6/7. work chapters: last 12 months and since the start ──
    chap_series = {}
    for key in CHAPTER_INPUTS:
        chap_series.update(by_key[key])
    order = {c: i for i, c in enumerate(CHAPTER_ORDER)}
    chap_rows = _rank(chap_series, names, sorted(chap_series, key=lambda c: order.get(c, 10**7 + c)),
                      start, last, order)
    chapters, chap_movers = _bars(chap_rows, "py")
    chapters_cum, _ = _bars(chap_rows, "cum")

    # ── 8. selected inputs ──
    item_series = by_key["items"]
    item_rows = _rank(item_series, names, sorted(item_series), start, last, {})
    items, item_movers = _bars(item_rows, "py")

    # ── 9. heatmap of monthly changes, general index ──
    heat_src = gen[gen["p"].notna()]
    heat_years = sorted(set(heat_src.index.year))
    cells = [[t.month - 1, heat_years.index(t.year), _r1(r["p"])] for t, r in heat_src.iterrows()]
    if not cells:
        raise ValueError("no published monthly changes for the general index")
    heat_rows = []
    for y in reversed(heat_years):
        row = [str(y)]
        for mth in range(1, 13):
            t = pd.Timestamp(year=y, month=mth, day=1)
            v = _at(heat_src, t, "p")
            row.append(_sp(v) if v is not None else "–")
        heat_rows.append(row)
    heat = {"x": fmt.MONTHS_SHORT_HE, "y": [str(y) for y in heat_years], "cells": cells,
            "min": min(c[2] for c in cells), "max": max(c[2] for c in cells)}

    def _full(rows):
        return [{"name": g["name"],
                 "p": _sp(g["p"]) if g["p"] is not None else "–",
                 "py": _sp(g["py"]) if g["py"] is not None else "–",
                 "cum": _sp(g["cum"]) if g["cum"] is not None else "–"} for g in rows]

    # ── insights ──
    rules = [
        ("latest", insight_latest(gen, last)),
        ("yoy_trend", insight_yoy_trend(gen, last)),
        ("residential", insight_residential(gen, res, start, last)),
        ("labour_materials", insight_labour_materials(main, last, start)),
        ("chapters", insight_chapters(chap_movers)),
        ("items", insight_items(item_movers)),
        ("peak_year", insight_peak_year(ann)),
        ("biggest_month", insight_biggest_month(gen, last)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── text ──
    lvl_txt = fmt.num_he(level, 1)
    change_txt = ""
    if p_last is not None and py_last is not None:
        change_txt = (f": שינוי של {_spi(p_last)} לעומת החודש הקודם ו-{_spi(py_last)} "
                      "לעומת החודש המקביל אשתקד")
    lede = (f"מדד מחירי התשומה בבנייה למסחר ולמשרדים של הלשכה המרכזית לסטטיסטיקה עמד ב{month} "
            f"על {lvl_txt} נקודות (בסיס {latest_base} = 100){change_txt}. המדד עוקב אחר מחירי "
            "החומרים, שכר העבודה, שכירת הציוד וההוצאות האחרות של קבלן שבונה מבני מסחר ומשרדים, "
            f"ללא מע\"מ. בעמוד: ערכי המדד בכל חודש מאז {fmt.month_he(first)}, השוואה למדד "
            "התשומות בבנייה למגורים, ופירוט לפי קבוצות ראשיות, פרקי עבודה ותשומות.")
    summary = (f"מדד תשומות הבנייה למסחר ולמשרדים ל{month}: {lvl_txt} נקודות (בסיס {latest_base} = 100)"
               + (f", {_spi(p_last)} בחודש ו-{_spi(py_last)} בשנה" if change_txt else "")
               + f". ערכי המדד מאז {first.year}, השוואה לבנייה למגורים ופירוט לפי פרקי עבודה.")
    desc = (f"מדד תשומות הבנייה למסחר ולמשרדים ל{month}: {lvl_txt} נקודות"
            + (f", שינוי חודשי {_sp(p_last)} ושנתי {_sp(py_last)}" if change_txt else "")
            + f". ערכי המדד בכל חודש מאז {first.year} ופירוט לפי פרקי עבודה.")

    labels = {
        "lede": lede,
        "level_kpi": f"המדד הכללי, {month} (בסיס {latest_base} = 100)",
        "mom_kpi": f"שינוי חודשי ({month})",
        "yoy_kpi": "שינוי ב-12 החודשים האחרונים",
        "labour_kpi": "שכר עבודה, שינוי שנתי",
        "materials_kpi": "חומרים ומוצרים, שינוי שנתי",
        "recent_note": (f"השינוי החודשי (עמודות) והשינוי לעומת החודש המקביל אשתקד (קו) ב-{len(recent)} "
                        "החודשים האחרונים, כפי שפרסמה הלמ\"ס. בטבלה: ערך המדד שפורסם בכל חודש, "
                        f"הבסיס שלו, והשינוי המצטבר מאותו חודש ועד {month}."),
        "recent_aria": (f"תרשים עמודות וקו: השינוי החודשי והשנתי במדד תשומות הבנייה למסחר ולמשרדים "
                        f"ב-{len(recent)} החודשים האחרונים."),
        "recent_caption": f"ערכי המדד ב-{len(recent)} החודשים האחרונים",
        "cum_col": f"שינוי מצטבר עד {month}",
        "history_note": (
            f"המדד הכללי מ{fmt.month_he(start)} עד {month}, כשהסדרה מתחילה ב-100 ב{fmt.month_he(start)}. "
            f"בתקופה זו הוא {_moved(gen_cum)}"
            + (f", ומדד התשומות בבנייה למגורים {_moved(res_cum)} (הקו השני)" if res_cum is not None
               else "")
            + ". אפשר לגרור את פס הזמן כדי להתמקד בתקופה."),
        "history_aria": ("גרף קווים: מדד תשומות הבנייה למסחר ולמשרדים"
                         + (" ומדד תשומות הבנייה למגורים" if res is not None else "")
                         + f" מ{fmt.month_he(start)} עד {month}, {fmt.month_he(start)} = 100."),
        "history_caption": f"המדד בדצמבר של כל שנה והשינוי השנתי, {first.year} עד {last.year}",
        "history_level_col": f"המדד בדצמבר (בסיס {chain_base} = 100)",
        "res_col": "שינוי שנתי, בנייה למגורים",
    }
    if ann:
        top = max(ann, key=lambda a: (a["py"], a["year"]))
        labels.update(
            annual_note=(f"השינוי במדד מדצמבר לדצמבר בכל שנה מאז {ann[0]['year']}, כפי שפורסם"
                         + (", לצד מדד התשומות בבנייה למגורים" if res is not None else "")
                         + f". ממוצע התקופה במסחר ובמשרדים {_pc(ann_avg)} בשנה; השנה הגבוהה "
                         f"{top['year']} ({_pc(top['py'])})."),
            annual_aria=(f"תרשים עמודות: השינוי השנתי במדד תשומות הבנייה למסחר ולמשרדים, "
                         f"{ann[0]['year']} עד {ann[-1]['year']}; השיא {_pc(top['py'])} ב-{top['year']}."),
        )
    if rebased:
        top_name = max(rebased["ends"], key=lambda k: (rebased["ends"][k], k))
        low_name = min(rebased["ends"], key=lambda k: (rebased["ends"][k], k))
        labels.update(
            rebased_note=(f"המדד הכללי והקבוצות הראשיות, כשכל סדרה מתחילה ב-100 ב{fmt.month_he(start)}. "
                          f"מאז עלתה ביותר הסדרה \"{top_name}\" ({fmt.num_he(rebased['ends'][top_name], 1)}) "
                          f"ופחות מכולן \"{low_name}\" ({fmt.num_he(rebased['ends'][low_name], 1)})."),
            rebased_aria=(f"גרף קווים: המדד הכללי והקבוצות הראשיות מ{fmt.month_he(start)} עד {month}, "
                          f"{fmt.month_he(start)} = 100."),
            rebased_caption=f"המדד והקבוצות הראשיות, {fmt.month_he(start)} = 100",
        )
    if lvm:
        labels.update(
            lvm_note=(f"השינוי לעומת החודש המקביל אשתקד בשכר העבודה ובחומרים ובמוצרים, מ{lvm['since']}. "
                      f"שכר העבודה עלה מהר יותר מהחומרים ב-{lvm['lab_above']:,} מתוך {lvm['n']:,} "
                      "החודשים."),
            lvm_aria=f"גרף קווים: השינוי השנתי בשכר העבודה, בחומרים ובמדד הכללי מ{lvm['since']} עד {month}.",
            lvm_caption=f"השינוי השנתי בשכר העבודה ובחומרים, בדצמבר של כל שנה ו{month}",
        )
    weights = ("הנתונים כאן אינם כוללים את משקלות הפרקים, ולכן מוצג שינוי המחיר בלבד ולא התרומה "
               "לשינוי במדד.")
    if chapters:
        labels.update(
            chapters_note=((f"{TOP_N} הפרקים שהתייקרו ביותר ו-{TOP_N} שהתייקרו פחות מכולם מתוך "
                            f"{chapters['n']:,}" if chapters["cut"] else
                            f"{chapters['n']:,} פרקי העבודה של המדד")
                           + f", לפי השינוי ב-12 החודשים שעד {month}, כפי שפורסם. " + weights),
            chapters_aria=(f"תרשים עמודות אופקי: השינוי השנתי בפרקי העבודה, {month}; "
                           f"הגבוה {chapters['names'][0]} ({_pc(chapters['y'][0])})."),
            chapters_caption=f"השינוי לפי פרק עבודה, {month}",
        )
    if chapters_cum:
        labels.update(
            chapters_cum_note=(f"השינוי המצטבר בכל פרק עבודה מ{fmt.month_he(start)} עד {month}. "
                               f"המדד הכללי עלה באותה תקופה ב-{_pc(gen_cum)} (הקו האנכי)."),
            chapters_cum_aria=(f"תרשים עמודות אופקי: השינוי המצטבר בפרקי העבודה מ{fmt.month_he(start)} "
                               f"עד {month}; הגבוה {chapters_cum['names'][0]} "
                               f"({_pc(chapters_cum['y'][0])})."),
            chapters_cum_caption=f"השינוי המצטבר מ{fmt.month_he(start)} עד {month} לפי פרק עבודה",
        )
    if items:
        labels.update(
            items_note=(f"מבחר של {items['n']:,} תשומות בולטות מתוך הקבוצות המשניות של המדד, לפי "
                        f"השינוי ב-12 החודשים שעד {month}. בטבלה גם השינוי החודשי והשינוי המצטבר "
                        f"מ{fmt.month_he(start)}. הפירוט המלא של כל הקבוצות המשניות מופיע בקובץ "
                        "הנתונים של הלמ\"ס."),
            items_aria=(f"תרשים עמודות אופקי: השינוי השנתי בתשומות נבחרות, {month}; "
                        f"הגבוה {items['names'][0]} ({_pc(items['y'][0])})."),
            items_caption=f"תשומות נבחרות: השינוי ב-12 החודשים שעד {month}",
        )
    labels.update(
        heat_note=(f"השינוי החודשי במדד הכללי בכל חודש מ-{heat_years[0]} עד {last.year}, כפי שפורסם. "
                   "צבע כהה יותר הוא עלייה גדולה יותר."),
        heat_aria=(f"מפת חום: השינוי החודשי במדד לפי חודש ושנה, {heat_years[0]} עד {last.year}; "
                   f"הגבוה {_pc(heat['max'])}."),
        heat_caption=f"השינוי החודשי במדד לפי חודש ושנה, {heat_years[0]} עד {last.year}",
        groups_caption=f"כל פרקי העבודה: שינוי חודשי ושנתי ב{month} ושינוי מצטבר מ{fmt.month_he(start)}",
        cum_since_col=f"שינוי מ{fmt.month_he(start)}",
        base_note=(f"המדד מתפרסם על בסיס {chain_base} = 100. אם הלמ\"ס תחליף את הבסיס, ערך שפורסם על "
                   "בסיס קודם יוצג בטבלה עם הבסיס שלו, והגרפים יציגו את כל הסדרה על הבסיס החדש לפי "
                   "מקדמי הקישור הרשמיים. מדד התשומות בבנייה למגורים מוצג באותו אופן, כשגם הוא מתחיל "
                   f"ב-100 ב{fmt.month_he(start)}."),
    )

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first.strftime('%Y-%m')}/{last.strftime('%Y-%m')}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד תשומות הבנייה למסחר ולמשרדים: ערכי המדד והשינוי החודשי",
                "description": desc,
                "name": "מדד תשומות הבנייה למסחר ולמשרדים",
                "alternate_names": ["מדד מחירי תשומה בבנייה למסחר ולמשרדים",
                                    "מדד תשומות הבנייה למבני מסחר ומשרדים",
                                    "מדד תשומות בנייה מסחרית", "מדד תשומות הבניה למשרדים"],
            },
        },
        "kpis": kpis,
        "charts": {
            "recent": recent_chart,
            "history": {"lines": lines},
            "annual": annual_chart,
            "rebased": {"lines": rebased["lines"]} if rebased else None,
            "lvm": {k: lvm[k] for k in ("x", "lab", "mat", "gen")} if lvm else None,
            "chapters": {"names": chapters["names"], "y": chapters["y"]} if chapters else None,
            "chapters_cum": ({"names": chapters_cum["names"], "y": chapters_cum["y"],
                              "gen": _r1(gen_cum)} if chapters_cum else None),
            "picks": {"names": items["names"], "y": items["y"]} if items else None,
            "heat": heat,
        },
        "tables": {
            "recent": recent_table,
            "annual": annual_rows if res is not None else [r[:3] for r in annual_rows],
            "rebased_cols": rebased["cols"] if rebased else [],
            "rebased": rebased["rows"] if rebased else [],
            "lvm": lvm["rows"] if lvm else [],
            "chapters": [r[:3] for r in chapters["rows"]] if chapters else [],
            "chapters_cum": chapters_cum["rows"] if chapters_cum else [],
            "picks": items["rows"] if items else [],
            "heat": heat_rows,
            "groups": _full(sorted(chap_rows, key=lambda g: g["ord"])),
        },
        "flags": {
            "annual": bool(ann), "res": res is not None, "rebased": bool(rebased),
            "lvm": bool(lvm), "chapters": bool(chapters), "chapters_cum": bool(chapters_cum),
            "picks": bool(items), "groups": bool(chap_rows), "heat": True,
        },
        "insights": insights,
        "labels": labels,
    }
