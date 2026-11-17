"""מדד מחירי תשומה בסלילה וגישור: the CBS road and bridge construction input price index.

Inputs (CBS Index API, provider `cbs_index`; one row per code and month):
  main       the general index (240010, from 1967: CBS's API answers HTTP 500
             for an earlier start), the index without bridging (240015), and
             the main groups: materials (240020), equipment hire (240320),
             labour (240800).
  materials  the material groups (quarry materials, asphalt mixes, cement and
             concrete, steel, pipes, marking, guardrails, …), from 2014.
  chapters   the index by work chapter (earthworks, asphalt layers, drainage,
             bridging, concrete, …), from 2014.
  selected   selected inputs (road bitumen, basalt asphalt concrete, cement,
             ready-mix concrete, aggregates, explosives), from 2014.

Rules (BRIEF.md, Source rules): levels and long-run ratios use VALUE_CHAINED
(every month on the newest base, CHAIN_BASE); month-on-month and
year-on-year changes are CBS's published PERCENT / PERCENT_YEAR, quoted as
published. The general index is required; every other code is optional, so
a code CBS retires (or a shorter input) drops its views instead of failing
the page. An unknown code renders under CBS's own NAME_HE.
"""
import math

import pandas as pd
from govlib import fmt

GENERAL = 240010
NO_BRIDGE = 240015
MATERIALS = 240020
EQUIPMENT = 240320
LABOUR = 240800
MAIN_ORDER = [GENERAL, MATERIALS, LABOUR, EQUIPMENT, NO_BRIDGE]

SHORT = {
    GENERAL: "המדד הכללי",
    NO_BRIDGE: "המדד ללא גישור",
    MATERIALS: "חומרים",
    EQUIPMENT: "שכירת ציוד",
    LABOUR: "שכר עבודה",
    240700: "פלדה ואביזרי מתכת",
    240740: "תאורת כביש ותשתית חשמל",
    240246: "בטון אספלט בזלתי (תא\"מ 19)",
    240140: "אגו\"מ (אגרגטים)",
}

# CBS's catalog order per family (subjects 53, 127, 128). A code CBS adds to
# an input follows its family by code.
FAMILIES = {
    "materials": [240030, 240220, 240255, 240280, 240283, 240284,
                  240285, 240291, 240700, 240710, 240730, 240740],
    "chapters": [242110, 242210, 242310, 242410, 242510, 242710,
                 242810, 242910, 243010, 243110, 243410, 243610],
    "selected": [240230, 240246, 240260, 240270, 240140, 240160, 240170, 240240],
}
INPUT_OF = {"main": None, "materials": "materials", "chapters": "chapters",
            "selected": "selected"}

RECENT_MONTHS = 24
ANNUAL_YEARS = 25
HEAT_YEARS = 15
REBASE_YEARS = 10
SEASON_YEARS = 10


# ── parsing ──────────────────────────────────────────────────────────────


def _load(frames):
    """code → DataFrame indexed by month (Timestamp), sorted, monthly rows
    only; plus code → family (the input it came from). A code in two inputs
    is read from the first (main comes first: the longer history)."""
    out, names, family = {}, {}, {}
    for key, fam in INPUT_OF.items():
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
                family[code] = fam
    return out, names, family


def _label(code, names):
    return SHORT.get(code) or names.get(code) or str(code)


def _base_he(desc):
    """'2010 ינואר' → 'ינואר 2010', '1972 ממוצע' → 'ממוצע 1972'."""
    parts = (desc or "").split()
    if len(parts) == 2 and parts[0].isdigit():
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
    """A chained level to `n` significant digits (1967 levels are ~0.00075)."""
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


# ── insights ─────────────────────────────────────────────────────────────


def _moved(v, plural=False):
    """'עלה ב-3.6%' / 'ירד ב-0.4%' / 'לא השתנה' (plural: עלו / ירדו / לא השתנו)."""
    if float(f"{abs(v):.1f}") == 0:
        return "לא השתנו" if plural else "לא השתנה"
    if v > 0:
        return ("עלו" if plural else "עלה") + f" ב-{_pc(v)}"
    return ("ירדו" if plural else "ירד") + f" ב-{_pc(-v)}"


def insight_latest(gen, last):
    p, py = _at(gen, last, "p"), _at(gen, last, "py")
    if p is None or py is None:
        return None
    return (f"מדד מחירי התשומה בסלילה וגישור לחודש {fmt.month_he(last)} {_moved(p)} לעומת "
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
    head = (f"ב-12 החודשים שעד {fmt.month_he(last)} שכר העבודה {_moved(lp)}, "
            f"והחומרים {_moved(mp, plural=True)}.")
    tail = ""
    if start is not None:
        l0, l1, m0, m1 = _at(lab, start), _at(lab, last), _at(mat, start), _at(mat, last)
        if None not in (l0, l1, m0, m1) and l0 > 0 and m0 > 0:
            tail = (f" מאז {fmt.month_he(start)} שכר העבודה {_moved((l1 / l0 - 1) * 100)} "
                    f"והחומרים {_moved((m1 / m0 - 1) * 100, plural=True)}.")
    return head + tail


def insight_materials(movers):
    up = [m for m in movers if m["py"] > 0]
    down = [m for m in movers if m["py"] < 0]
    if not up:
        return None
    names = fmt.join_he([f"{m['name']} ({_pc(m['py'])})" for m in up[:2]])
    s = f"קבוצות החומרים שהתייקרו ביותר בשנה האחרונה: {names}."
    if down:
        low = down[-1]
        s += f" הירידה החדה ביותר: {low['name']} ({_pc(low['py'])})."
    else:
        s += " אף קבוצת חומרים לא הוזלה בשנה זו."
    return s


def insight_chapters(chapters, gen_py):
    rows = [c for c in chapters if c["py"] is not None]
    if len(rows) < 4 or gen_py is None:
        return None
    hi, lo = rows[0], rows[-1]
    above = sum(1 for c in rows if c["py"] > gen_py)
    return (f"לפי פרקי העבודה, בשנה האחרונה התייקרו ביותר {hi['name']} ({_spi(hi['py'])}), "
            f"ופחות מכולם {lo['name']} ({_spi(lo['py'])}). {above} מתוך {len(rows)} הפרקים "
            f"שבעמוד התייקרו יותר מהמדד הכללי ({_spi(gen_py)}).")


def insight_swing(selected, series, last):
    """The selected input that moved most last month, when the move is large."""
    rows = [g for g in selected if g["p"] is not None]
    if not rows:
        return None
    top = max(rows, key=lambda g: (abs(g["p"]), -g["code"]))
    if abs(top["p"]) < 3:
        return None
    s = series[top["code"]]
    win = s["p"][s.index > _months_back(last, 24)].dropna()
    big = int((win.abs() >= 5).sum())
    verb = "עלה" if top["p"] > 0 else "ירד"
    out = f"מחיר {top['name']} {verb} ב-{_pc(abs(top['p']))} ב{fmt.month_he(last)}"
    if top["py"] is not None:
        out += f", ו-{_spi(top['py'])} לעומת החודש המקביל אשתקד"
    out += "."
    if big >= 3:
        out += (f" זו תשומה תנודתית: ב-{big} מתוך {len(win)} החודשים האחרונים השתנה מחירה "
                "ב-5% או יותר בחודש אחד.")
    return out


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
    return (f"העלייה החודשית החדה ביותר במדד ב-10 השנים האחרונות: {_pc(mx)} ב{fmt.month_he(t)}, "
            f"לעומת שינוי חודשי חציוני של {_pc(med)}.")


def insight_decades(gen, last):
    t1, t2 = _months_back(last, 120), _months_back(last, 240)
    v0, v1, v2 = _at(gen, last), _at(gen, t1), _at(gen, t2)
    if None in (v0, v1, v2) or v1 <= 0 or v2 <= 0:
        return None
    a, b = (v0 / v1 - 1) * 100, (v1 / v2 - 1) * 100
    return (f"בעשור האחרון ({fmt.month_he(t1)} עד {fmt.month_he(last)}) המדד {_moved(a)}, "
            f"לעומת {_pc(b)} בעשור שקדם לו ({fmt.month_he(t2)} עד {fmt.month_he(t1)}).")


# ── groups ───────────────────────────────────────────────────────────────


def _family_rows(fam, series, names, family, last, start):
    """The codes of one family that are still published, with their
    published changes and the cumulative change since `start`."""
    order = FAMILIES[fam]
    codes = [c for c in order if c in series and family.get(c) == fam]
    codes += sorted(c for c in series if family.get(c) == fam and c not in order)
    stale = _months_back(last, 12)
    rows = []
    for code in codes:
        s = series[code]
        if s.index[-1] <= stale:
            continue  # a code CBS stopped publishing
        v1 = _at(s, last)
        v0 = _at(s, start) if start is not None else None
        dec = (v1 / v0 - 1) * 100 if v0 and v1 is not None and v0 > 0 else None
        rows.append({"code": code, "name": _label(code, names), "p": _at(s, last, "p"),
                     "py": _at(s, last, "py"), "dec": dec})
    return rows


def _bars(rows, key):
    pick = sorted([g for g in rows if g[key] is not None], key=lambda g: (-g[key], g["code"]))
    return pick


def _fmt_row(g, with_dec):
    row = [g["name"], _sp(g["p"]) if g["p"] is not None else "–",
           _sp(g["py"]) if g["py"] is not None else "–"]
    if with_dec:
        row.append(_sp(g["dec"]) if g["dec"] is not None else "–")
    return row


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    series, names, family = _load(frames)
    gen = series.get(GENERAL)
    if gen is None:
        raise ValueError("no rows for the general index (code 240010)")
    gen = gen[gen["v"].notna()]
    last = gen.index[-1]
    first = gen.index[0]
    chain_base = _base_he(gen["chain"].iloc[-1])
    latest_value = _at(gen, last, "value")
    latest_base = _base_he(gen.at[last, "base"])
    p_last, py_last = _at(gen, last, "p"), _at(gen, last, "py")
    month = fmt.month_he(last)
    v_last = float(gen.at[last, "v"])

    # Rebase window start: January ten years before the latest year.
    start = pd.Timestamp(year=last.year - REBASE_YEARS, month=1, day=1)
    if start not in gen.index:
        start = None

    # ── KPIs ──
    lvl = latest_value if latest_value is not None else v_last
    kpis = {"level": {"value": lvl, "display": fmt.num_he(lvl, 1), "tone": "brand"}}
    if p_last is not None:
        kpis["mom"] = {"value": p_last, "display": _sp(p_last),
                       "tone": "warn" if p_last >= 0.5 else "ok" if p_last < 0 else "brand"}
    if py_last is not None:
        kpis["yoy"] = {"value": py_last, "display": _sp(py_last),
                       "tone": "warn" if py_last >= 4 else "ok" if py_last <= 0 else "brand"}
    for key, code in (("materials", MATERIALS), ("labour", LABOUR), ("equipment", EQUIPMENT)):
        v = _at(series.get(code), last, "py")
        if v is not None:
            kpis[key] = {"value": v, "display": _sp(v), "tone": "brand"}

    # ── 1. recent months: m/m bars + y/y line, and the contract table ──
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

    # ── 2. the whole history on the newest base ──
    history = [[t.strftime("%Y-%m"), _sig(float(v))] for t, v in gen["v"].items()]
    dec_rows = gen[gen.index.month == 12]
    annual_rows = [{"year": t.year, "level": float(r["v"]),
                    "py": None if pd.isna(r["py"]) else float(r["py"])}
                   for t, r in dec_rows.iterrows()]
    annual_table = [[str(a["year"]), _lvl(a["level"]), _sp(a["py"]) if a["py"] is not None else "–"]
                    for a in annual_rows]
    if last.month != 12:
        annual_table.append([f"{month} (12 חודשים)", _lvl(v_last),
                             _sp(py_last) if py_last is not None else "–"])
    annual_table.reverse()
    mult = v_last / float(gen["v"].iloc[0])
    mult_txt = fmt.int_he(_sig(mult, 3)) if mult >= 1000 else fmt.num_he(mult, 1)

    # ── 3. annual change, last complete years (December on December) ──
    ann = [a for a in annual_rows if a["py"] is not None][-ANNUAL_YEARS:]
    annual_chart = {"x": [str(a["year"]) for a in ann], "y": [_r1(a["py"]) for a in ann]}
    annual_small = [[str(a["year"]), _sp(a["py"])] for a in reversed(ann)]
    ann_max = max(ann, key=lambda a: (a["py"], a["year"])) if ann else None
    ann_avg = sum(a["py"] for a in ann) / len(ann) if ann else None

    # ── 4. main groups rebased to the window start ──
    def rebase(codes):
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
        return {"lines": lines, "cols": [line["name"] for line in lines], "rows": rows,
                "ends": ends}

    rebased = None
    if start is not None:
        main_codes = MAIN_ORDER + sorted(c for c in series
                                         if family.get(c) is None and c not in MAIN_ORDER)
        rebased = rebase(main_codes)

    # ── 5. labour vs materials, published year-on-year ──
    lvm = None
    lab, mat = series.get(LABOUR), series.get(MATERIALS)
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

    # ── 6/7. material groups: last 12 months and the decade ──
    mat_rows = _family_rows("materials", series, names, family, last, start)
    movers = _bars(mat_rows, "py")
    drivers = None
    if len(movers) >= 4:
        drivers = {"names": [g["name"] for g in movers], "y": [_r1(g["py"]) for g in movers],
                   "n": len(movers)}
    dec_movers = _bars(mat_rows, "dec")
    gen_dec = (v_last / float(gen.at[start, "v"]) - 1) * 100 if start is not None else None
    decade = None
    if len(dec_movers) >= 4 and start is not None:
        decade = {"names": [g["name"] for g in dec_movers], "y": [_r1(g["dec"]) for g in dec_movers],
                  "n": len(dec_movers), "gen": _r1(gen_dec)}

    # ── 8. work chapters: last 12 months and since the window start ──
    ch_rows = _family_rows("chapters", series, names, family, last, start)
    ch_sorted = _bars(ch_rows, "py")
    chapters = None
    if len(ch_sorted) >= 4:
        chapters = {"names": [g["name"] for g in ch_sorted],
                    "py": [_r1(g["py"]) for g in ch_sorted],
                    "dec": [None if g["dec"] is None else _r1(g["dec"]) for g in ch_sorted],
                    "n": len(ch_sorted), "has_dec": any(g["dec"] is not None for g in ch_sorted)}

    # ── 9. selected inputs rebased to the window start ──
    sel_rows = _family_rows("selected", series, names, family, last, start)
    selected = None
    if start is not None:
        selected = rebase([g["code"] for g in sel_rows])

    # ── 10. heatmap of monthly changes, general index ──
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
        ("labour_materials", insight_labour_materials(series, last, start)),
        ("materials", insight_materials(movers)),
        ("chapters", insight_chapters(ch_sorted, py_last)),
        ("swing", insight_swing(sel_rows, series, last)),
        ("biggest_month", insight_biggest_month(gen, last)),
        ("decades", insight_decades(gen, last)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── text ──
    lvl_txt = fmt.num_he(lvl, 1)
    change_txt = ""
    if p_last is not None and py_last is not None:
        change_txt = (f": שינוי של {_spi(p_last)} לעומת החודש הקודם ו-{_spi(py_last)} "
                      "לעומת החודש המקביל אשתקד")
    lede = (f"מדד מחירי התשומה בסלילה וגישור (מדד הסלילה) של הלשכה המרכזית לסטטיסטיקה "
            f"עמד ב{month} על {lvl_txt} נקודות (בסיס {latest_base} = 100){change_txt}. "
            "המדד עוקב אחר מחירי החומרים, שכירת הציוד ושכר העבודה של קבלן שסולל כבישים "
            f"ובונה גשרים, ללא מע\"מ. בעמוד: ערכי המדד בכל חודש מאז {first.year}, "
            "השינוי השנתי, ופירוט לפי קבוצות חומרים, פרקי עבודה ותשומות נבחרות.")
    summary = (f"מדד מחירי התשומה בסלילה וגישור ל{month}: {lvl_txt} נקודות (בסיס {latest_base} = 100)"
               + (f", {_spi(p_last)} בחודש ו-{_spi(py_last)} בשנה" if change_txt else "")
               + f". ערכי המדד מאז {first.year}, שכר עבודה מול חומרים, פרקי עבודה ותשומות נבחרות.")
    desc = (f"מדד הסלילה והגישור האחרון ל{month}: {lvl_txt} נקודות"
            + (f", שינוי חודשי {_sp(p_last)} ושנתי {_sp(py_last)}" if change_txt else "")
            + f". ערכי המדד בכל חודש מאז {first.year}, ביטומן, אספלט ופרקי עבודה.")

    labels = {
        "lede": lede,
        "level_kpi": f"המדד הכללי, {month} (בסיס {latest_base} = 100)",
        "mom_kpi": f"שינוי חודשי ({month})",
        "yoy_kpi": "שינוי ב-12 החודשים האחרונים",
        "materials_kpi": "חומרים, שינוי שנתי",
        "labour_kpi": "שכר עבודה, שינוי שנתי",
        "equipment_kpi": "שכירת ציוד, שינוי שנתי",
        "recent_note": (f"השינוי החודשי (עמודות) והשינוי לעומת החודש המקביל אשתקד (קו) ב-{len(recent)} "
                        "החודשים האחרונים, כפי שפרסמה הלמ\"ס. בטבלה: ערך המדד שפורסם בכל חודש, "
                        f"הבסיס שלו, והשינוי המצטבר מאותו חודש ועד {month}."),
        "recent_aria": (f"תרשים עמודות וקו: השינוי החודשי והשנתי במדד הסלילה והגישור ב-{len(recent)} "
                        f"החודשים האחרונים; ב{month} {_sp(p_last) if p_last is not None else ''} בחודש."),
        "recent_caption": f"ערכי מדד הסלילה והגישור ב-{len(recent)} החודשים האחרונים",
        "cum_col": f"שינוי מצטבר עד {month}",
        "history_note": (f"כל ערכי המדד מ{fmt.month_he(first)} ועד {month}, על בסיס אחד ({chain_base} = 100) "
                         "לפי מקדמי הקישור הרשמיים של הלמ\"ס. הציר האנכי לוגריתמי, כי באינפלציה של "
                         f"שנות ה-70 וה-80 המדד גדל פי כמה בשנה; מאז {first.year} הוא גדל פי "
                         f"{mult_txt} בערך. אפשר לגרור את פס הזמן כדי להתמקד בתקופה."),
        "history_aria": (f"גרף קו לוגריתמי: מדד הסלילה והגישור מ-{first.year} עד {last.year} "
                         f"על בסיס {chain_base} = 100; כיום {fmt.num_he(v_last, 1)}."),
        "history_caption": f"מדד הסלילה והגישור בדצמבר של כל שנה והשינוי השנתי, {first.year} עד {last.year}",
        "history_level_col": f"המדד בדצמבר (בסיס {chain_base} = 100)",
    }
    if ann:
        labels.update(
            annual_note=(f"השינוי במדד מדצמבר לדצמבר ב-{len(ann)} השנים השלמות האחרונות "
                         f"({ann[0]['year']} עד {ann[-1]['year']}), כפי שפורסם. ממוצע התקופה "
                         f"{_pc(ann_avg)} בשנה; השנה הגבוהה {ann_max['year']} ({_pc(ann_max['py'])})."),
            annual_aria=(f"תרשים עמודות: השינוי השנתי במדד הסלילה והגישור, {ann[0]['year']} עד "
                         f"{ann[-1]['year']}; השיא {_pc(ann_max['py'])} ב-{ann_max['year']}."),
            annual_caption=f"השינוי השנתי במדד הסלילה והגישור, {ann[0]['year']} עד {ann[-1]['year']}",
        )
    if rebased:
        top_name = max(rebased["ends"], key=lambda k: (rebased["ends"][k], k))
        low_name = min(rebased["ends"], key=lambda k: (rebased["ends"][k], k))
        labels.update(
            rebased_note=(f"המדד הכללי והקבוצות הראשיות, כשכל סדרה מתחילה ב-100 ב{fmt.month_he(start)}. "
                          f"מאז עלתה ביותר הסדרה \"{top_name}\" ({fmt.num_he(rebased['ends'][top_name], 1)}) "
                          f"ופחות מכולן \"{low_name}\" ({fmt.num_he(rebased['ends'][low_name], 1)}). "
                          "המדד ללא גישור משמיט את עבודות הגשרים."),
            rebased_aria=(f"גרף קווים: המדד הכללי והקבוצות הראשיות מ{fmt.month_he(start)} עד {month}, "
                          f"{fmt.month_he(start)} = 100."),
            rebased_caption=f"המדד והקבוצות הראשיות, {fmt.month_he(start)} = 100",
        )
    if lvm:
        labels.update(
            lvm_note=(f"השינוי לעומת החודש המקביל אשתקד בשכר העבודה ובחומרים, מ{lvm['since']} "
                      "(מאז שהלמ\"ס מפרסמת אותו לשתי הקבוצות). שכר העבודה עלה מהר יותר מהחומרים "
                      f"ב-{lvm['lab_above']:,} מתוך {lvm['n']:,} החודשים."),
            lvm_aria=f"גרף קווים: השינוי השנתי בשכר העבודה, בחומרים ובמדד הכללי מ{lvm['since']} עד {month}.",
            lvm_caption=f"השינוי השנתי בשכר העבודה ובחומרים, בדצמבר של כל שנה ו{month}",
        )
    if drivers:
        labels.update(
            drivers_note=(f"{drivers['n']:,} קבוצות החומרים שבעמוד, לפי השינוי ב-12 החודשים שעד {month}, "
                          "כפי שפורסם. הנתונים כאן אינם כוללים את משקלות הקבוצות, ולכן מוצג שינוי "
                          "המחיר בלבד ולא התרומה לשינוי במדד."),
            drivers_aria=(f"תרשים עמודות אופקי: השינוי השנתי בקבוצות החומרים של מדד הסלילה והגישור, "
                          f"{month}; הגבוה {drivers['names'][0]} ({_pc(drivers['y'][0])})."),
        )
    if decade:
        labels.update(
            decade_note=(f"השינוי המצטבר בכל קבוצת חומרים מ{fmt.month_he(start)} עד {month}, מחושב "
                         f"מהסדרה המקושרת. המדד הכללי עלה באותה תקופה ב-{_pc(decade['gen'])} (הקו האנכי)."),
            decade_aria=(f"תרשים עמודות אופקי: השינוי המצטבר בקבוצות החומרים מ{fmt.month_he(start)} "
                         f"עד {month}; הגבוה {decade['names'][0]} ({_pc(decade['y'][0])})."),
            decade_caption=f"השינוי המצטבר מ{fmt.month_he(start)} עד {month} לפי קבוצת חומרים",
        )
    if mat_rows:
        labels.update(
            materials_caption=f"קבוצות החומרים: שינוי חודשי ושנתי ב{month}"
                              + (f" ושינוי מצטבר מ{fmt.month_he(start)}" if start is not None else ""),
        )
    if chapters:
        labels.update(
            chapters_note=(f"{chapters['n']:,} פרקי עבודה עיקריים, לפי השינוי ב-12 החודשים שעד {month} "
                           "(עמודה כהה), לצד השינוי המצטבר"
                           + (f" מ{fmt.month_he(start)}" if start is not None else "")
                           + " (עמודה בהירה). כל פרק מתמחר עבודה שלמה בשטח, כולל החומרים, הציוד "
                           "וכוח האדם שהיא דורשת."),
            chapters_aria=(f"תרשים עמודות אופקי: השינוי השנתי והמצטבר בפרקי העבודה של מדד הסלילה "
                           f"והגישור, {month}; הגבוה {chapters['names'][0]} ({_pc(chapters['py'][0])})."),
            chapters_caption=f"פרקי העבודה: שינוי חודשי ושנתי ב{month}"
                             + (f" ושינוי מצטבר מ{fmt.month_he(start)}" if start is not None else ""),
        )
    if selected:
        top_name = max(selected["ends"], key=lambda k: (selected["ends"][k], k))
        low_name = min(selected["ends"], key=lambda k: (selected["ends"][k], k))
        labels.update(
            selected_note=(f"תשומות נבחרות שהלמ\"ס מפרסמת בנפרד, כשכל סדרה מתחילה ב-100 ב{fmt.month_he(start)}. "
                           f"מאז עלה ביותר \"{top_name}\" ({fmt.num_he(selected['ends'][top_name], 1)}) "
                           f"ופחות מכולם \"{low_name}\" ({fmt.num_he(selected['ends'][low_name], 1)}). "
                           "אפשר להסתיר ולהציג סדרות בלחיצה על המקרא."),
            selected_aria=(f"גרף קווים: תשומות נבחרות בסלילה וגישור מ{fmt.month_he(start)} עד {month}, "
                           f"{fmt.month_he(start)} = 100."),
            selected_caption=f"תשומות נבחרות: שינוי חודשי ושנתי ב{month} ושינוי מצטבר מ{fmt.month_he(start)}",
        )
    labels.update(
        heat_note=(f"השינוי החודשי במדד הכללי בכל חודש מ-{heat_years[0]} עד {last.year}, כפי שפורסם. "
                   "צבע כהה יותר הוא עלייה גדולה יותר."),
        heat_aria=(f"מפת חום: השינוי החודשי במדד הסלילה והגישור לפי חודש ושנה, {heat_years[0]} עד "
                   f"{last.year}; הגבוה {_pc(heat['max'])}."),
        heat_caption=f"השינוי החודשי במדד לפי חודש ושנה, {heat_years[0]} עד {last.year}",
        dec_col=f"שינוי מ{fmt.month_he(start)}" if start is not None else "",
        base_note=(f"הבסיס הנוכחי של המדד הוא {chain_base} = 100. ערך שפורסם על בסיס קודם מוצג "
                   "בטבלה עם הבסיס שלו; הגרפים מציגים את כל הסדרה על הבסיס הנוכחי לפי מקדמי הקישור "
                   "הרשמיים של הלמ\"ס. שינויים מצטברים שחושבו כאן מתוך הסדרה המקושרת עשויים להיות "
                   "שונים במעט מחישוב לפי ערכים מעוגלים."),
    )

    with_dec = start is not None
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first.strftime('%Y-%m')}/{last.strftime('%Y-%m')}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד הסלילה והגישור האחרון: ערכי המדד והשינוי החודשי",
                "description": desc,
                "name": "מדד מחירי תשומה בסלילה וגישור",
                "alternate_names": ["מדד סלילה וגישור", "מדד הסלילה", "מדד תשומות סלילה",
                                    "מדד סלילה", "מדד תשומות סלילה וגישור"],
            },
        },
        "kpis": kpis,
        "charts": {
            "recent": recent_chart,
            "history": history,
            "annual": annual_chart,
            "rebased": {"lines": rebased["lines"]} if rebased else None,
            "lvm": {k: lvm[k] for k in ("x", "lab", "mat", "gen")} if lvm else None,
            "drivers": {"names": drivers["names"], "y": drivers["y"]} if drivers else None,
            "decade": ({"names": decade["names"], "y": decade["y"], "gen": decade["gen"]}
                       if decade else None),
            "chapters": ({k: chapters[k] for k in ("names", "py", "dec", "has_dec")}
                         if chapters else None),
            "selected": {"lines": selected["lines"]} if selected else None,
            "heat": heat,
        },
        "tables": {
            "recent": recent_table,
            "annual_all": annual_table,
            "annual": annual_small,
            "rebased_cols": rebased["cols"] if rebased else [],
            "rebased": rebased["rows"] if rebased else [],
            "lvm": lvm["rows"] if lvm else [],
            "decade": [[g["name"], _sp(g["dec"])] for g in dec_movers] if decade else [],
            "materials": [_fmt_row(g, with_dec) for g in movers]
                         + [_fmt_row(g, with_dec) for g in mat_rows if g["py"] is None],
            "chapters": [_fmt_row(g, with_dec) for g in ch_sorted]
                        + [_fmt_row(g, with_dec) for g in ch_rows if g["py"] is None],
            "selected": [_fmt_row(g, with_dec) for g in sel_rows],
            "heat": heat_rows,
        },
        "flags": {
            "annual": bool(ann), "rebased": bool(rebased), "lvm": bool(lvm),
            "drivers": bool(drivers), "decade": bool(decade), "materials": bool(mat_rows),
            "chapters": bool(chapters), "selected": bool(selected),
            "selected_table": bool(sel_rows), "heat": True,
        },
        "insights": insights,
        "labels": labels,
    }
