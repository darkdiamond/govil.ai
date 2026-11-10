"""מדד תשומות הבנייה למגורים: the CBS residential construction input price index.

Inputs (CBS Index API, provider `cbs_index`; one row per code and month):
  main    the general index (200010, since 1956), the index without labour
          (200020) and the four main groups: materials (201010), labour
          (205010), equipment hire (203020), general expenses (204010).
  groups  the secondary groups (concrete, iron, electricity, sanitation,
          carpentry, …) from a fixed start, monthly.

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

GENERAL = 200010
NO_LABOUR = 200020
MATERIALS = 201010
EQUIPMENT = 203020
OVERHEAD = 204010
LABOUR = 205010
MAIN_ORDER = [GENERAL, MATERIALS, LABOUR, EQUIPMENT, OVERHEAD, NO_LABOUR]

SHORT = {
    GENERAL: "המדד הכללי",
    NO_LABOUR: "המדד ללא שכר עבודה",
    MATERIALS: "חומרים ומוצרים",
    EQUIPMENT: "שכירת ציוד",
    OVERHEAD: "הוצאות כלליות",
    LABOUR: "שכר עבודה",
    204030: "אחזקת אתר, משרדים ובטיחות",
}

# Secondary groups that are the sum of other codes on the page: left out of
# the "which inputs moved" rankings so a parent and its child don't both
# appear. Their rows stay in the full table.
PARENTS = {201020, 201080, 201130, 201320, 201380, 205020}

# CBS's own catalog order (subject 49), used for the full table. Unknown
# codes follow, by code.
GROUP_ORDER = [
    201020, 201030, 201060, 201080, 201090, 201100,
    201130, 201140, 201160, 201180, 201190, 201200,
    201210, 201230, 201260,
    201320, 201330, 201360, 201370, 201470,
    201380, 201420, 201430, 201440, 201460,
    201480, 201510, 201500, 201560, 201305,
    201520, 201530, 201540, 201550, 201570,
    204020, 204030,
    205020, 205030, 205040, 205050, 205070,
]

RECENT_MONTHS = 24
ANNUAL_YEARS = 25
HEAT_YEARS = 15
REBASE_YEARS = 10
TOP_N = 8
SEASON_YEARS = 10


# ── parsing ──────────────────────────────────────────────────────────────


def _load(frames):
    """code → DataFrame indexed by month (Timestamp), sorted, monthly rows
    only. A code in both inputs is read from `main` (the longer history)."""
    out, names = {}, {}
    for key in ("main", "groups"):
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
    return out, names


def _label(code, names):
    return SHORT.get(code) or names.get(code) or str(code)


def _base_he(desc):
    """'2025 יולי' → 'יולי 2025', '1968 ממוצע' → 'ממוצע 1968'."""
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
    """A chained level to `n` significant digits (1956 levels are ~0.0005)."""
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
    if t in s.index:
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
    return (f"מדד תשומות הבנייה למגורים לחודש {fmt.month_he(last)} {_moved(p)} לעומת החודש "
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
    # "Strengthened / eased" only describes a rise; when either end is a
    # fall (2009), say which way the 12-month change moved instead.
    if now > 0 and before > 0:
        word = "התגבר" if d > 0 else "התמתן"
        head = f"קצב העלייה השנתי במדד {word}"
    else:
        head = "השינוי השנתי במדד " + ("עלה" if d > 0 else "ירד")
    return (f"{head}: מ-{_spi(before)} ב{fmt.month_he(prev_t)} "
            f"ל-{_spi(now)} ב{fmt.month_he(last)}.")


def insight_labour_materials(series, last, start):
    lab, mat = series.get(LABOUR), series.get(MATERIALS)
    if lab is None or mat is None:
        return None
    lp, mp = _at(lab, last, "py"), _at(mat, last, "py")
    if lp is None or mp is None:
        return None
    head = (f"ב-12 החודשים שעד {fmt.month_he(last)} שכר העבודה {_moved(lp)}, "
            f"והחומרים והמוצרים {_moved(mp, plural=True)}.")
    if lp - mp >= 0.3 and lp > 0:
        head += " שכר העבודה התייקר מהר יותר מהחומרים."
    elif mp - lp >= 0.3 and mp > 0:
        head += " החומרים התייקרו מהר יותר משכר העבודה."
    tail = ""
    if start is not None:
        l0, l1, m0, m1 = _at(lab, start), _at(lab, last), _at(mat, start), _at(mat, last)
        if None not in (l0, l1, m0, m1) and l0 > 0 and m0 > 0:
            tail = (f" מאז {fmt.month_he(start)} שכר העבודה {_moved((l1 / l0 - 1) * 100)} "
                    f"והחומרים {_moved((m1 / m0 - 1) * 100, plural=True)}.")
    return head + tail


def insight_drivers(movers):
    up = [m for m in movers if m["py"] > 0]
    down = [m for m in movers if m["py"] < 0]
    if not up:
        return None
    top = up[:2]
    names = fmt.join_he([f"{m['name']} ({_pc(m['py'])})" for m in top])
    s = f"הקבוצות שהתייקרו ביותר בשנה האחרונה: {names}."
    if down:
        low = down[-1]
        s += f" הירידה החדה ביותר: {low['name']} ({_pc(low['py'])})."
    else:
        s += " אף קבוצה משנית לא הוזלה בשנה זו."
    return s


def insight_season(gen, last):
    """The calendar month with the largest average change over the last
    complete years, when it stands out from the rest."""
    p = gen["p"].dropna()
    full_years = [y for y in sorted(set(p.index.year)) if y < last.year or last.month == 12]
    full_years = [y for y in full_years if (p.index.year == y).sum() == 12][-SEASON_YEARS:]
    if len(full_years) < 5:
        return None
    win = p[p.index.year.isin(full_years)]
    by_month = win.groupby(win.index.month).mean()
    top = int(by_month.sort_index().idxmax())
    top_mean = float(by_month[top])
    rest = float(win[win.index.month != top].mean())
    if top_mean < 2 * max(rest, 0.01) or top_mean - rest < 0.2:
        return None
    return (f"בשנים {full_years[0]} עד {full_years[-1]} עלה המדד בחודש {fmt.MONTHS_HE[top - 1]} "
            f"ב-{_pc(top_mean, 2)} בממוצע, לעומת {_pc(rest, 2)} בממוצע בשאר החודשים.")


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


def insight_decades(gen, last):
    t1, t2 = _months_back(last, 120), _months_back(last, 240)
    v0, v1, v2 = _at(gen, last), _at(gen, t1), _at(gen, t2)
    if None in (v0, v1, v2) or v1 <= 0 or v2 <= 0:
        return None
    a, b = (v0 / v1 - 1) * 100, (v1 / v2 - 1) * 100
    return (f"בעשור האחרון ({fmt.month_he(t1)} עד {fmt.month_he(last)}) המדד {_moved(a)}, "
            f"לעומת {_pc(b)} בעשור שקדם לו ({fmt.month_he(t2)} עד {fmt.month_he(t1)}).")


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    series, names = _load(frames)
    gen = series.get(GENERAL)
    if gen is None:
        raise ValueError("no rows for the general index (code 200010)")
    gen = gen[gen["v"].notna()]
    last = gen.index[-1]
    first = gen.index[0]
    chain_base = _base_he(gen["chain"].iloc[-1])
    latest_value = _at(gen, last, "value")
    latest_base = _base_he(gen.at[last, "base"])
    p_last, py_last = _at(gen, last, "p"), _at(gen, last, "py")
    month = fmt.month_he(last)

    # Rebase window start: January ten years before the latest year.
    start = pd.Timestamp(year=last.year - REBASE_YEARS, month=1, day=1)
    if start not in gen.index:
        start = None

    # ── KPIs ──
    kpis = {"level": {"value": latest_value if latest_value is not None else _at(gen, last),
                      "display": fmt.num_he(latest_value if latest_value is not None
                                            else _at(gen, last), 1),
                      "tone": "brand"}}
    if p_last is not None:
        kpis["mom"] = {"value": p_last, "display": _sp(p_last),
                       "tone": "warn" if p_last >= 0.5 else "ok" if p_last < 0 else "brand"}
    if py_last is not None:
        kpis["yoy"] = {"value": py_last, "display": _sp(py_last),
                       "tone": "warn" if py_last >= 4 else "ok" if py_last <= 0 else "brand"}
    for key, code in (("labour", LABOUR), ("materials", MATERIALS)):
        s = series.get(code)
        v = _at(s, last, "py") if s is not None else None
        if v is not None:
            kpis[key] = {"value": v, "display": _sp(v), "tone": "brand"}

    # ── 1. recent months: m/m bars + y/y line, and the buyer's table ──
    recent = gen.iloc[-RECENT_MONTHS:]
    v_last = float(gen.at[last, "v"])
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
    dec = gen[gen.index.month == 12]
    annual_rows = []
    for t, r in dec.iterrows():
        annual_rows.append({"year": t.year, "level": float(r["v"]),
                            "py": None if pd.isna(r["py"]) else float(r["py"])})
    annual_table = [[str(a["year"]), _lvl(a["level"]), _sp(a["py"]) if a["py"] is not None else "–"]
                    for a in annual_rows]
    if last.month != 12:
        annual_table.append([f"{fmt.month_he(last)} (12 חודשים)", _lvl(v_last),
                             _sp(py_last) if py_last is not None else "–"])
    annual_table.reverse()
    # The 1956 chained level carries ~3 significant digits (0.000454), so
    # the multiple is shown to 3 significant digits, as an approximation.
    mult = v_last / float(gen["v"].iloc[0])
    mult_txt = fmt.int_he(_sig(mult, 3)) if mult >= 1000 else fmt.num_he(mult, 1)

    # ── 3. annual change, last complete years (December on December) ──
    ann = [a for a in annual_rows if a["py"] is not None][-ANNUAL_YEARS:]
    annual_chart = {"x": [str(a["year"]) for a in ann], "y": [_r1(a["py"]) for a in ann]}
    annual_small = [[str(a["year"]), _sp(a["py"])] for a in reversed(ann)]
    ann_max = max(ann, key=lambda a: (a["py"], a["year"])) if ann else None
    ann_avg = sum(a["py"] for a in ann) / len(ann) if ann else None

    # ── 4. main groups rebased to the window start ──
    rebased = None
    if start is not None:
        lines, cols = [], []
        for code in MAIN_ORDER + sorted(c for c in series if c < 201020 and c not in MAIN_ORDER):
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
        if len(lines) >= 2:
            ticks = [t for t in gen.loc[start:last].index if t.month == 1]
            if ticks[-1] != last:
                ticks.append(last)
            rows = []
            for t in reversed(ticks):
                row = [fmt.month_he(t)]
                for _code, s, v0 in cols:
                    v = _at(s, t)
                    row.append(fmt.num_he(v / v0 * 100, 1) if v is not None else "–")
                rows.append(row)
            ends = {line["name"]: line["data"][-1][1] for line in lines}
            rebased = {"lines": lines, "cols": [line["name"] for line in lines], "rows": rows,
                       "ends": ends}

    # ── 5. labour vs materials, published year-on-year ──
    lvm = None
    lab, mat = series.get(LABOUR), series.get(MATERIALS)
    if lab is not None and mat is not None:
        both = pd.concat({"lab": lab["py"], "mat": mat["py"], "gen": gen["py"]}, axis=1)
        both = both.dropna(subset=["lab", "mat"])
        both = both.loc[:last]
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

    # ── 6/7. secondary groups: last 12 months and the decade ──
    group_codes = [c for c in GROUP_ORDER if c in series]
    group_codes += sorted(c for c in series if c not in GROUP_ORDER and c not in MAIN_ORDER
                          and c >= 201020)
    leaves = []
    stale = _months_back(last, 12)
    for code in group_codes:
        s = series[code]
        if s.index[-1] <= stale:
            continue  # a group CBS stopped publishing (a rebase retires some)
        py, p = _at(s, last, "py"), _at(s, last, "p")
        v1 = _at(s, last)
        v0 = _at(s, start) if start is not None else None
        dec_ch = (v1 / v0 - 1) * 100 if v0 and v1 is not None and v0 > 0 else None
        leaves.append({"code": code, "name": _label(code, names), "p": p, "py": py,
                       "dec": dec_ch, "parent": code in PARENTS})
    movers = sorted([g for g in leaves if not g["parent"] and g["py"] is not None],
                    key=lambda g: (-g["py"], g["code"]))
    drivers = None
    if len(movers) >= 4:
        pick = movers if len(movers) <= 2 * TOP_N else movers[:TOP_N] + movers[-TOP_N:]
        drivers = {"names": [g["name"] for g in pick], "y": [_r1(g["py"]) for g in pick],
                   "rows": [[g["name"], _sp(g["py"]), _sp(g["p"]) if g["p"] is not None else "–"]
                            for g in pick],
                   "n": len(movers), "cut": len(pick) < len(movers)}
    dec_movers = sorted([g for g in leaves if not g["parent"] and g["dec"] is not None],
                        key=lambda g: (-g["dec"], g["code"]))
    decade = None
    if len(dec_movers) >= 4 and start is not None:
        pick = (dec_movers if len(dec_movers) <= 2 * TOP_N
                else dec_movers[:TOP_N] + dec_movers[-TOP_N:])
        gen_dec = (v_last / float(gen.at[start, "v"]) - 1) * 100
        decade = {"names": [g["name"] for g in pick], "y": [_r1(g["dec"]) for g in pick],
                  "rows": [[g["name"], _sp(g["dec"])] for g in pick],
                  "n": len(dec_movers), "cut": len(pick) < len(dec_movers),
                  "gen": _r1(gen_dec)}
    all_groups = [{"name": g["name"], "parent": g["parent"],
                   "p": _sp(g["p"]) if g["p"] is not None else "–",
                   "py": _sp(g["py"]) if g["py"] is not None else "–",
                   "dec": _sp(g["dec"]) if g["dec"] is not None else "–"}
                  for g in leaves]

    # ── 8. heatmap of monthly changes, general index ──
    y0 = last.year - HEAT_YEARS + 1
    heat_src = gen[(gen.index.year >= y0) & gen["p"].notna()]
    heat_years = sorted(set(heat_src.index.year))
    cells = [[t.month - 1, heat_years.index(t.year), _r1(r["p"])] for t, r in heat_src.iterrows()]
    heat_rows = []
    for y in reversed(heat_years):
        row = [str(y)]
        for mth in range(1, 13):
            t = pd.Timestamp(year=y, month=mth, day=1)
            v = _at(gen, t, "p")
            row.append(_sp(v) if v is not None and t in heat_src.index else "–")
        heat_rows.append(row)
    heat = {"x": fmt.MONTHS_SHORT_HE, "y": [str(y) for y in heat_years], "cells": cells,
            "min": min(c[2] for c in cells) if cells else 0,
            "max": max(c[2] for c in cells) if cells else 1}

    # ── insights ──
    rules = [
        ("latest", insight_latest(gen, last)),
        ("yoy_trend", insight_yoy_trend(gen, last)),
        ("labour_materials", insight_labour_materials(series, last, start)),
        ("drivers", insight_drivers(movers)),
        ("biggest_month", insight_biggest_month(gen, last)),
        ("season", insight_season(gen, last)),
        ("decades", insight_decades(gen, last)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── text ──
    lvl_txt = fmt.num_he(kpis["level"]["value"], 1)
    change_txt = ""
    if p_last is not None and py_last is not None:
        change_txt = (f": שינוי של {_spi(p_last)} לעומת החודש הקודם ו-{_spi(py_last)} "
                      "לעומת החודש המקביל אשתקד")
    lede = (f"מדד מחירי התשומה בבנייה למגורים (מדד תשומות הבנייה) של הלשכה המרכזית לסטטיסטיקה "
            f"עמד ב{month} על {lvl_txt} נקודות (בסיס {latest_base} = 100){change_txt}. "
            "המדד עוקב אחר מחירי החומרים, שכר העבודה, שכירת הציוד וההוצאות הכלליות של קבלן "
            f"שבונה דירות למגורים, ללא מע\"מ. בעמוד: ערכי המדד בכל חודש מאז {first.year}, "
            "השינוי השנתי והפירוט לפי קבוצות.")
    summary = (f"מדד תשומות הבנייה למגורים ל{month}: {lvl_txt} נקודות (בסיס {latest_base} = 100)"
               + (f", {_spi(p_last)} בחודש ו-{_spi(py_last)} בשנה" if change_txt else "")
               + f". ערכי המדד מאז {first.year}, שכר עבודה מול חומרים ופירוט לפי קבוצות.")
    desc = (f"מדד תשומות הבנייה האחרון ל{month}: {lvl_txt} נקודות"
            + (f", שינוי חודשי {_sp(p_last)} ושנתי {_sp(py_last)}" if change_txt else "")
            + f". ערכי המדד בכל חודש מאז {first.year} ופירוט לפי קבוצות.")

    labels = {
        "lede": lede,
        "level_kpi": f"המדד הכללי, {month} (בסיס {latest_base} = 100)",
        "mom_kpi": f"שינוי חודשי ({month})",
        "yoy_kpi": "שינוי ב-12 החודשים האחרונים",
        "labour_kpi": "שכר עבודה, שינוי שנתי",
        "materials_kpi": "חומרים ומוצרים, שינוי שנתי",
        "recent_note": (f"השינוי החודשי (עמודות) והשינוי לעומת החודש המקביל אשתקד (קו) ב-{len(recent)} "
                        f"החודשים האחרונים, כפי שפרסמה הלמ\"ס. בטבלה: ערך המדד שפורסם בכל חודש, "
                        f"הבסיס שלו, והשינוי המצטבר מאותו חודש ועד {month}."),
        "recent_aria": (f"תרשים עמודות וקו: השינוי החודשי והשנתי במדד תשומות הבנייה ב-{len(recent)} "
                        f"החודשים האחרונים; ב{month} {_sp(p_last) if p_last is not None else ''} בחודש."),
        "recent_caption": f"ערכי מדד תשומות הבנייה למגורים ב-{len(recent)} החודשים האחרונים",
        "cum_col": f"שינוי מצטבר עד {month}",
        "history_note": (f"כל ערכי המדד מ{fmt.month_he(first)} ועד {month}, על בסיס אחד ({chain_base} = 100) "
                         "לפי מקדמי הקישור הרשמיים של הלמ\"ס. הציר האנכי לוגריתמי, כי באינפלציה של "
                         f"שנות ה-70 וה-80 המדד גדל פי כמה בשנה; מאז {first.year} הוא גדל פי "
                         f"{mult_txt} בערך. אפשר לגרור את פס הזמן כדי להתמקד בתקופה."),
        "history_aria": (f"גרף קו לוגריתמי: מדד תשומות הבנייה למגורים מ-{first.year} עד {last.year} "
                         f"על בסיס {chain_base} = 100; כיום {fmt.num_he(v_last, 1)}."),
        "history_caption": f"מדד תשומות הבנייה בדצמבר של כל שנה והשינוי השנתי, {first.year} עד {last.year}",
        "history_level_col": f"המדד בדצמבר (בסיס {chain_base} = 100)",
    }
    if ann:
        labels.update(
            annual_note=(f"השינוי במדד מדצמבר לדצמבר ב-{len(ann)} השנים השלמות האחרונות "
                         f"({ann[0]['year']} עד {ann[-1]['year']}), כפי שפורסם. ממוצע התקופה "
                         f"{_pc(ann_avg)} בשנה; השנה הגבוהה {ann_max['year']} ({_pc(ann_max['py'])})."),
            annual_aria=(f"תרשים עמודות: השינוי השנתי במדד תשומות הבנייה, {ann[0]['year']} עד "
                         f"{ann[-1]['year']}; השיא {_pc(ann_max['py'])} ב-{ann_max['year']}."),
            annual_caption=f"השינוי השנתי במדד תשומות הבנייה, {ann[0]['year']} עד {ann[-1]['year']}",
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
            lvm_note=(f"השינוי לעומת החודש המקביל אשתקד בשכר העבודה ובחומרים ובמוצרים, מ{lvm['since']} "
                      f"(מאז שהלמ\"ס מפרסמת אותו לשתי הקבוצות). שכר העבודה עלה מהר יותר מהחומרים "
                      f"ב-{lvm['lab_above']:,} מתוך {lvm['n']:,} החודשים."),
            lvm_aria=(f"גרף קווים: השינוי השנתי בשכר העבודה, בחומרים ובמדד הכללי מ{lvm['since']} עד {month}."),
            lvm_caption=f"השינוי השנתי בשכר העבודה ובחומרים, בדצמבר של כל שנה ו{month}",
        )
    if drivers:
        labels.update(
            drivers_note=((f"{TOP_N} הקבוצות המשניות שהתייקרו ביותר ו-{TOP_N} שהתייקרו פחות מכולן "
                           f"מתוך {drivers['n']:,}, " if drivers["cut"] else
                           f"{drivers['n']:,} הקבוצות המשניות, ")
                          + f"לפי השינוי ב-12 החודשים שעד {month}. קבוצות שהן סיכום של קבוצות אחרות "
                          "(למשל חשמל או תברואה) מופיעות רק בטבלה המלאה בהמשך. הנתונים כאן אינם "
                          "כוללים את משקלות הקבוצות, ולכן מוצג שינוי המחיר בלבד ולא התרומה לשינוי "
                          "במדד."),
            drivers_aria=(f"תרשים עמודות אופקי: השינוי השנתי בקבוצות המשניות של מדד תשומות הבנייה, "
                          f"{month}; הגבוה {drivers['names'][0]} ({_pc(drivers['y'][0])})."),
            drivers_caption=f"השינוי ב-12 החודשים שעד {month} לפי קבוצה משנית",
        )
    if decade:
        labels.update(
            decade_note=((f"{TOP_N} הקבוצות שעלו ביותר ו-{TOP_N} שעלו פחות מכולן מתוך {decade['n']:,}"
                          if decade["cut"] else f"{decade['n']:,} הקבוצות המשניות")
                         + f", לפי השינוי המצטבר מ{fmt.month_he(start)} עד {month}. "
                         f"המדד הכללי עלה באותה תקופה ב-{_pc(decade['gen'])} (הקו האנכי)."),
            decade_aria=(f"תרשים עמודות אופקי: השינוי המצטבר בקבוצות המשניות מ{fmt.month_he(start)} "
                         f"עד {month}; הגבוה {decade['names'][0]} ({_pc(decade['y'][0])})."),
            decade_caption=f"השינוי המצטבר מ{fmt.month_he(start)} עד {month} לפי קבוצה משנית",
        )
    if not cells:
        raise ValueError("no published monthly changes for the general index")
    labels.update(
        heat_note=(f"השינוי החודשי במדד הכללי בכל חודש מ-{heat_years[0]} עד {last.year}, כפי שפורסם. "
                   "צבע כהה יותר הוא עלייה גדולה יותר."),
        heat_aria=(f"מפת חום: השינוי החודשי במדד תשומות הבנייה לפי חודש ושנה, {heat_years[0]} עד "
                   f"{last.year}; הגבוה {_pc(heat['max'])}."),
        heat_caption=f"השינוי החודשי במדד לפי חודש ושנה, {heat_years[0]} עד {last.year}",
        groups_caption=f"כל הקבוצות המשניות: שינוי חודשי ושנתי ב{month}"
                       + (f" ושינוי מצטבר מ{fmt.month_he(start)}" if start is not None else ""),
        groups_note=(f"השינויים בכל הקבוצות המשניות ב{month}. קבוצה מודגשת היא סיכום של "
                     "הקבוצות שאחריה."),
        dec_col=f"שינוי מ{fmt.month_he(start)}" if start is not None else "",
        base_note=(f"הלמ\"ס מחליפה את בסיס המדד מעת לעת (הבסיס הנוכחי: {chain_base} = 100). ערך "
                   "שפורסם על בסיס קודם מוצג בטבלה עם הבסיס שלו; הגרפים מציגים את כל הסדרה על הבסיס "
                   "הנוכחי לפי מקדמי הקישור הרשמיים. שינויים מצטברים שחושבו כאן מתוך הסדרה המקושרת "
                   "עשויים להיות שונים במעט מחישוב לפי ערכים מעוגלים."),
    )

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first.strftime('%Y-%m')}/{last.strftime('%Y-%m')}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד תשומות הבנייה האחרון: ערכי המדד והשינוי החודשי",
                "description": desc,
                "name": "מדד תשומות הבנייה למגורים",
                "alternate_names": ["מדד מחירי תשומה בבנייה למגורים", "מדד תשומות הבניה",
                                    "מדד תשומות בנייה", "מדד הבנייה"],
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
            "heat": heat,
        },
        "tables": {
            "recent": recent_table,
            "annual_all": annual_table,
            "annual": annual_small,
            "rebased_cols": rebased["cols"] if rebased else [],
            "rebased": rebased["rows"] if rebased else [],
            "lvm": lvm["rows"] if lvm else [],
            "drivers": drivers["rows"] if drivers else [],
            "decade": decade["rows"] if decade else [],
            "heat": heat_rows,
            "groups": all_groups,
        },
        "flags": {
            "annual": bool(ann), "rebased": bool(rebased), "lvm": bool(lvm),
            "drivers": bool(drivers), "decade": bool(decade), "groups": bool(all_groups),
            "heat": bool(cells),
        },
        "insights": insights,
        "labels": labels,
    }
