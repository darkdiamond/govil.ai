"""מדד מחירי מוצרים ושירותים נבחרים: CBS consumer price indices of everyday items.

Inputs (all from the CBS Index API, one row per code and month):
  staples, food   food items (subject 40): bread, flour, rice, oil, sugar,
                  cheese, coffee, meat, chicken, fish, sweets, drinks.
  home            cooking gas, repair services, cleaning products, appliances.
  transport       bus, train, taxi, flights abroad, fuel, cars, car insurance.
  services        dental care, medicines, gym, cinema, hotels, TV, internet,
                  haircuts, bank fees.
  basics          the general CPI (120010) plus CPI components people look up
                  that subject 40 lacks: milk, household electricity, water and
                  sewage, pre-school education, restaurant meals (subject 38).

Charts use VALUE_CHAINED (every row of a code on its newest base, CHAIN_BASE);
quoted 12-month and monthly changes are CBS's published PERCENT_YEAR and
PERCENT. Cumulative changes (5 years, since the first month of the data) are
ratios of VALUE_CHAINED. Item indices are separate CBS series: they are not
added up or compared as prices, only as index movements.
"""
import math
import re

import pandas as pd
from govlib import fmt, frame

CPI = 120010
THEME_HE = {
    "food": "מזון",
    "home": "בית ודיור",
    "transport": "תחבורה",
    "services": "שירותים",
    "other": "אחר",
}
THEME_ORDER = ("food", "home", "transport", "services", "other")
INPUT_THEME = {"staples": "food", "food": "food", "home": "home", "transport": "transport",
               "services": "services"}
CODE_THEME = {120240: "food", 120430: "food", 120590: "home", 120620: "home",
              121070: "services"}
SHORT = {
    120240: "חלב",
    120430: "ארוחות במסעדות ובבתי קפה",
    120590: "חשמל לבית",
    120620: "מים וביוב",
    121070: "גני ילדים (חינוך קדם יסודי)",
    140148: "חמאה",
    140621: "מנוי לחדר כושר וסטודיו",
    140635: "טלוויזיה רב-ערוצית",
    140690: "דלק והטענה לרכב",
}
# The items a reader checks first, in this order (absent ones skipped).
ESSENTIALS = (140025, 120240, 140150, 120590, 120620, 140690, 140665, 121070)
DEFAULT_PICK = (140025, 120240, 140690)
FIVE_Y = 60
HEAT_YEARS = 6
FLAT = 0.5  # |change| below this many percent reads as "almost unchanged"
MOM_N = 8
FOOTNOTE = re.compile(r"\s*\(\d+\)\s*$")


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


def _catalog(df):
    """code → {name, theme}, the name from the code's newest row."""
    out = {}
    for code, g in df.groupby("code", sort=True):
        code = int(code)
        last = g.iloc[-1]
        name = SHORT.get(code) or FOOTNOTE.sub("", last["name"]) or str(code)
        theme = CODE_THEME.get(code) or INPUT_THEME.get(last["_input"], "other")
        out[code] = {"name": name, "theme": theme}
    return out


def _chained_run(df, code):
    """The newest contiguous run of VALUE_CHAINED (a break CBS can't link
    leaves earlier rows blank)."""
    g = df[df["code"] == code][["t", "v"]].set_index("t")["v"]
    if g.empty:
        return g
    blank = g.isna()
    if blank.any():
        g = g[g.index > blank[blank].index.max()]
    return g.dropna()


# ── text helpers ─────────────────────────────────────────────────────────

def _sp(v, digits=1):
    """A change on 0-100 as signed text: +3.4%, −3.4%, 0.0%."""
    body = f"{abs(v):.{digits}f}"
    if float(body) == 0:
        return f"{body}%"
    return ("+" if v > 0 else fmt.MINUS) + body + "%"


def _iso(s):
    return fmt.isolate(s)


def _ym(t):
    return f"{t.year}-{t.month:02d}"


def _r(v, digits=1):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), digits)


def _move(v):
    if abs(v) < FLAT:
        return f"כמעט ללא שינוי ({_iso(_sp(v))})"
    return f"{'עלייה' if v > 0 else 'ירידה'} של {abs(v):.1f}%"


def _tone_change(v):
    if v >= 5:
        return "danger"
    if v > FLAT:
        return "warn"
    if v <= -FLAT:
        return "ok"
    return "brand"


def _full_years(s):
    """Calendar years with all 12 months → {year: mean}."""
    if s.empty:
        return {}
    g = s.groupby(s.index.year)
    counts, means = g.size(), g.mean()
    return {int(y): float(means[y]) for y in counts.index if counts[y] == 12}


def _cum(s, base_t, end_t):
    if base_t in s.index and end_t in s.index and s[base_t] > 0:
        return (s[end_t] / s[base_t] - 1) * 100
    return None


def _order(items, key):
    """Sort descending by key, ties by name then code."""
    return sorted(items, key=lambda i: (-i[key], i["name"], i["code"]))


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    df = _load(frames)
    if df.empty:
        raise ValueError("no monthly rows")
    cat = _catalog(df)
    item_codes = sorted(c for c in cat if c != CPI)
    if not item_codes:
        raise ValueError("no item indices")
    items_df = df[df["code"] != CPI]
    L = items_df["t"].max()
    runs = {c: _chained_run(df, c) for c in cat}
    chain_base = ""
    # Each code's newest CHAIN_BASE (df is sorted by code, then month). The
    # picker draws raw chained levels against the CPI, so they must share it.
    bases = df.groupby("code", sort=True)["base"].last()
    bases = sorted(set(bases[bases != ""]))
    if len(bases) > 1:
        raise ValueError(f"item indices on different chain bases: {bases}")
    if bases:
        chain_base = bases[0]

    cpi_row = df[(df["code"] == CPI) & (df["t"] == L)]
    cpi_yoy = cpi_pct = None
    if not cpi_row.empty:
        r = cpi_row.iloc[0]
        cpi_yoy = None if pd.isna(r["yoy"]) else float(r["yoy"])
        cpi_pct = None if pd.isna(r["pct"]) else float(r["pct"])
    cpi_run = runs.get(CPI, pd.Series(dtype=float))

    # ── latest month per item ──
    latest = []
    for _, r in items_df[items_df["t"] == L].iterrows():
        c = int(r["code"])
        latest.append({"code": c, "name": cat[c]["name"], "theme": cat[c]["theme"],
                       "yoy": None if pd.isna(r["yoy"]) else float(r["yoy"]),
                       "pct": None if pd.isna(r["pct"]) else float(r["pct"])})
    latest_codes = {i["code"] for i in latest}
    lagging = [cat[c]["name"] for c in item_codes if c not in latest_codes]
    rank = _order([i for i in latest if i["yoy"] is not None], "yoy")
    mom_all = _order([i for i in latest if i["pct"] is not None], "pct")

    # ── cumulative: 5 years, and since the first month of the general CPI ──
    B5 = L - pd.DateOffset(months=FIVE_Y)
    B0 = cpi_run.index.min() if not cpi_run.empty else df["t"].min()
    five, since0 = [], []
    for c in item_codes:
        s = runs[c]
        v5 = _cum(s, B5, L)
        if v5 is not None:
            five.append({"code": c, "name": cat[c]["name"], "theme": cat[c]["theme"], "cum": v5})
        v0 = _cum(s, B0, L)
        if v0 is not None:
            since0.append({"code": c, "name": cat[c]["name"], "theme": cat[c]["theme"],
                           "cum": v0})
    five = _order(five, "cum")
    since0 = _order(since0, "cum")
    cpi5 = _cum(cpi_run, B5, L)
    cpi0 = _cum(cpi_run, B0, L)

    # ── yearly change heatmap: last HEAT_YEARS full calendar years ──
    fy = {c: _full_years(runs[c]) for c in cat}
    cpi_fy = fy.get(CPI, {})
    years_pool = cpi_fy if cpi_fy else _full_years(runs[item_codes[0]])
    heat_years = [y for y in sorted(years_pool) if (y - 1) in years_pool][-HEAT_YEARS:]
    heat_rows = []
    for c in item_codes + ([CPI] if CPI in cat else []):
        cells = []
        for y in heat_years:
            if y in fy[c] and (y - 1) in fy[c]:
                cells.append(round((fy[c][y] / fy[c][y - 1] - 1) * 100, 1))
            else:
                cells.append(None)
        if any(v is not None for v in cells):
            heat_rows.append({"code": c, "name": "המדד הכללי" if c == CPI else cat[c]["name"],
                              "theme": "cpi" if c == CPI else cat[c]["theme"], "cells": cells})
    # Items grouped by theme, CPI first.
    heat_rows.sort(key=lambda h: (-1 if h["theme"] == "cpi" else THEME_ORDER.index(h["theme"]),
                                  h["name"], h["code"]))

    # ── picker: every item's chained series on one monthly axis ──
    start = min(runs[c].index.min() for c in cat if not runs[c].empty)
    months = pd.date_range(start, L, freq="MS")
    picker_groups = []
    five_by = {i["code"]: i["cum"] for i in five}
    yoy_by = {i["code"]: i["yoy"] for i in rank}
    for th in THEME_ORDER:
        codes = [c for c in item_codes if cat[c]["theme"] == th and not runs[c].empty]
        codes.sort(key=lambda c: (cat[c]["name"], c))
        if not codes:
            continue
        picker_groups.append({
            "theme": THEME_HE[th],
            "codes": codes,
            "names": [cat[c]["name"] for c in codes],
            "facts": [[_r(yoy_by.get(c)), _r(five_by.get(c)), _ym(runs[c].index.min())]
                      for c in codes],
        })
    default_code = next((c for c in DEFAULT_PICK if c in cat and not runs[c].empty),
                        picker_groups[0]["codes"][0] if picker_groups else None)
    picker_items = [{"code": c, "y": [_r(runs[c].get(t)) for t in months]}
                    for g in picker_groups for c in g["codes"]]
    picker = {
        "groups": picker_groups,
        "start": _ym(start), "n": len(months),
        "cpi": [_r(cpi_run.get(t)) for t in months] if not cpi_run.empty else [],
        "default": default_code,
        "cpi_yoy": _r(cpi_yoy), "cpi5": _r(cpi5),
    }

    # ── KPIs ──
    kpis, labels = {}, {}
    month_txt = fmt.month_he(L)
    if cpi_yoy is not None:
        kpis["cpi"] = {"value": cpi_yoy, "display": _sp(cpi_yoy), "tone": "brand"}
        labels["cpi_kpi"] = f"המדד הכללי: שינוי ב-12 חודשים ({month_txt})"
    if rank and cpi_yoy is not None:
        above = [i for i in rank if i["yoy"] > cpi_yoy]
        kpis["above"] = {"value": len(above), "display": f"{len(above):,}",
                         "tone": "warn" if len(above) * 2 > len(rank) else "brand"}
        labels["above_kpi"] = f"פריטים שהתייקרו יותר מהמדד הכללי, מתוך {len(rank):,}"
    if len(rank) >= 2:
        top, bot = rank[0], rank[-1]
        kpis["top"] = {"value": top["yoy"], "display": _sp(top["yoy"]),
                       "tone": _tone_change(top["yoy"])}
        labels["top_kpi"] = f"ההתייקרות השנתית הגדולה ביותר: {top['name']}"
        kpis["bottom"] = {"value": bot["yoy"], "display": _sp(bot["yoy"]),
                          "tone": _tone_change(bot["yoy"])}
        labels["bottom_kpi"] = f"השינוי השנתי הנמוך ביותר: {bot['name']}"

    # ── insights ──
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_extremes():
        if len(rank) < 5:
            return None
        top, bot = rank[0], rank[-1]
        if top["yoy"] <= 0 or bot["yoy"] >= 0:
            return None
        cpi_txt = f", לעומת {_iso(_sp(cpi_yoy))} במדד הכללי" if cpi_yoy is not None else ""
        return (f"ההתייקרות הגדולה ביותר בשנה שעד {month_txt}: {top['name']} "
                f"({_iso(_sp(top['yoy']))}){cpi_txt}. בקצה השני: {bot['name']}, עם "
                f"{_move(bot['yoy'])}.")

    def ins_breadth():
        if len(rank) < 5 or cpi_yoy is None:
            return None
        above = sum(1 for i in rank if i["yoy"] > cpi_yoy)
        down = sum(1 for i in rank if i["yoy"] < 0)
        return (f"{above:,} מתוך {len(rank):,} הפריטים בעמוד התייקרו בשנה האחרונה יותר מהמדד "
                f"הכללי ({_iso(_sp(cpi_yoy))}), ו-{down:,} פריטים הוזלו.")

    def ins_essentials():
        parts = []
        for c in ESSENTIALS:
            if c in yoy_by and yoy_by[c] is not None:
                parts.append(f"{cat[c]['name']} {_iso(_sp(yoy_by[c]))}")
        if len(parts) < 3:
            return None
        return f"השינוי ב-12 החודשים שעד {month_txt} במוצרים הבסיסיים: {'; '.join(parts)}."

    def ins_five():
        if len(five) < 5 or cpi5 is None:
            return None
        top = five[0]
        above = sum(1 for i in five if i["cum"] > cpi5)
        return (f"בחמש השנים שמאז {fmt.month_he(B5)} עלה המדד הכללי ב-{_iso(fmt.pct_of(cpi5))}"
                f" במצטבר. הפריט שהתייקר הכי הרבה הוא {top['name']} "
                f"({_iso(_sp(top['cum']))}), ו-{above:,} מתוך {len(five):,} הפריטים "
                f"התייקרו יותר מהמדד הכללי.") if cpi5 > 0 else None

    def ins_longrun():
        if len(since0) < 5 or cpi0 is None:
            return None
        top, bot = since0[0], since0[-1]
        return (f"מאז {fmt.month_he(B0)} עלה המדד הכללי ב-{_iso(fmt.pct_of(cpi0))}. "
                f"באותה תקופה עלה המדד של {top['name']} ב-{_iso(fmt.pct_of(top['cum']))}, "
                f"ואילו במדד של {bot['name']} נרשמה {_move(bot['cum'])}.")

    def ins_mom():
        if not mom_all:
            return None
        big = max(mom_all, key=lambda i: (abs(i["pct"]), i["name"], i["code"]))
        if abs(big["pct"]) < 2:
            return None
        cpi_txt = (f" המדד הכללי באותו חודש: {_move(cpi_pct)}." if cpi_pct is not None else "")
        return (f"התנועה החודשית הבולטת ב{month_txt}: {big['name']}, "
                f"{_move(big['pct'])} לעומת החודש הקודם.{cpi_txt}")

    add("extremes", ins_extremes())
    add("breadth", ins_breadth())
    add("essentials", ins_essentials())
    add("five", ins_five())
    add("longrun", ins_longrun())
    add("mom", ins_mom())

    # ── charts + tables ──
    charts, tables, flags = {}, {}, {}
    flags["rank"] = len(rank) >= 3
    charts["rank"] = {"names": [i["name"] for i in rank], "y": [_r(i["yoy"]) for i in rank],
                      "theme": [THEME_HE[i["theme"]] for i in rank], "cpi": _r(cpi_yoy)}
    tables["rank"] = [[i["name"], THEME_HE[i["theme"]], _sp(i["yoy"]),
                       _sp(i["pct"]) if i["pct"] is not None else "–"] for i in rank]
    if lagging:
        labels["rank_note"] = (f"לפי השינוי לעומת {month_txt} בשנה הקודמת, כפי שפרסמה הלמ\"ס. "
                               f"לא פורסם עדיין נתון לחודש זה עבור: {fmt.join_he(lagging)}.")
    else:
        labels["rank_note"] = (f"לפי השינוי ב-{month_txt} לעומת אותו חודש בשנה הקודמת, כפי "
                               f"שפרסמה הלמ\"ס. הקו המקווקו: המדד הכללי.")
    labels["rank_aria"] = f"השינוי ב-12 חודשים לפי פריט, {month_txt}"

    flags["mom"] = len(mom_all) >= 2 * MOM_N
    if flags["mom"]:
        up = mom_all[:MOM_N]
        down = mom_all[-MOM_N:]
        sel = up + down
        charts["mom"] = {"names": [i["name"] for i in sel], "y": [_r(i["pct"]) for i in sel]}
        tables["mom"] = [[i["name"], _sp(i["pct"])] for i in sel]
        labels["mom_note"] = (f"{MOM_N:,} הפריטים שעלו הכי הרבה ו-{MOM_N:,} שירדו הכי הרבה ב"
                              f"{month_txt} לעומת החודש הקודם. "
                              + (f"המדד הכללי: {_sp(cpi_pct)}." if cpi_pct is not None else ""))
        labels["mom_aria"] = f"השינוי החודשי לפי פריט, {month_txt}"

    flags["five"] = len(five) >= 3
    charts["five"] = {"names": [i["name"] for i in five], "y": [_r(i["cum"]) for i in five],
                      "theme": [THEME_HE[i["theme"]] for i in five], "cpi": _r(cpi5)}
    tables["five"] = [[i["name"], THEME_HE[i["theme"]], _sp(i["cum"])] for i in five]
    missing5 = [cat[c]["name"] for c in item_codes if c not in {i["code"] for i in five}]
    labels["five_note"] = (f"השינוי המצטבר במדד של כל פריט מ{fmt.month_he(B5)} עד {month_txt}"
                           + (f". המדד הכללי עלה באותה תקופה ב-{fmt.pct_of(cpi5)}" if cpi5 is not None
                              else "")
                           + (f". חסרים פריטים שהלמ\"ס מודדת רק מתקופה מאוחרת יותר: "
                              f"{fmt.join_he(missing5)}" if missing5 else "") + ".")
    labels["five_aria"] = f"השינוי המצטבר לפי פריט מ{fmt.month_he(B5)} עד {month_txt}"
    labels["five_head"] = f"מה התייקר הכי הרבה מאז {fmt.month_he(B5)}"

    flags["since0"] = len(since0) >= 3
    charts["since0"] = {"names": [i["name"] for i in since0],
                        "y": [_r(i["cum"]) for i in since0],
                        "theme": [THEME_HE[i["theme"]] for i in since0], "cpi": _r(cpi0)}
    tables["since0"] = [[i["name"], THEME_HE[i["theme"]], _sp(i["cum"])] for i in since0]
    labels["since0_note"] = (f"השינוי המצטבר מ{fmt.month_he(B0)} עד {month_txt}, רק לפריטים "
                             f"שנמדדו כבר אז ({len(since0):,} מתוך {len(item_codes):,})"
                             + (f". המדד הכללי עלה ב-{fmt.pct_of(cpi0)}" if cpi0 is not None
                                else "") + ".")
    labels["since0_aria"] = f"השינוי המצטבר לפי פריט מ{fmt.month_he(B0)} עד {month_txt}"
    labels["since0_head"] = f"התמונה הארוכה: השינוי מאז {fmt.month_he(B0)}"

    flags["heat"] = len(heat_years) >= 2 and len(heat_rows) >= 3
    flat_cells = [abs(v) for h in heat_rows for v in h["cells"] if v is not None]
    charts["heat"] = {
        "years": [str(y) for y in heat_years],
        "items": [h["name"] for h in heat_rows],
        "cells": [[j, i, v] for i, h in enumerate(heat_rows) for j, v in enumerate(h["cells"])
                  if v is not None],
        "max": min(max(flat_cells), 15) if flat_cells else 1,
    }
    tables["heat_cols"] = ["פריט"] + [str(y) for y in heat_years]
    tables["heat"] = [[h["name"]] + [_sp(v) if v is not None else "–" for v in h["cells"]]
                      for h in heat_rows]
    if heat_years:
        labels["heat_note"] = (f"השינוי במדד הממוצע של כל שנה לעומת השנה הקודמת, בשנים "
                               f"{heat_years[0]}-{heat_years[-1]} (שנים מלאות בלבד). אדום: "
                               f"התייקרות, כחול: הוזלה. תא ריק: הפריט לא נמדד בשתי השנים.")
        labels["heat_aria"] = f"השינוי השנתי לפי פריט, {heat_years[0]}-{heat_years[-1]}"

    flags["picker"] = bool(picker_groups) and bool(picker["cpi"])
    charts["picker"] = picker
    charts["picker_items"] = picker_items
    tables["picker"] = [[n, g["theme"], _sp(f[0]) if f[0] is not None else "–",
                         _sp(f[1]) if f[1] is not None else "–",
                         fmt.num_he(runs[c].iloc[-1])]
                        for g in picker_groups
                        for c, n, f in zip(g["codes"], g["names"], g["facts"])]
    labels["picker_note"] = (f"בחרו מוצר או שירות כדי לראות את המדד שלו לאורך זמן מול המדד "
                             f"הכללי. שתי הסדרות על אותו בסיס ({chain_base} = 100), כך שקו "
                             f"שמעל המדד הכללי פירושו מוצר שהתייקר מאז יותר ממנו.")
    labels["picker_aria"] = "מדד המחירים של המוצר שנבחר מול המדד הכללי"
    labels["chain_base"] = chain_base
    labels["month"] = month_txt
    labels["n_items"] = f"{len(item_codes):,}"

    # ── lede, summary, seo ──
    lede = (f"מדדי המחירים לצרכן של {len(item_codes):,} מוצרים ושירותים נבחרים, מכיכר לחם וחלב "
            f"ועד דלק, חשמל וטיפולי שיניים, מתוך מאגר המדדים של הלשכה המרכזית לסטטיסטיקה. "
            f"הנתון האחרון הוא ל{month_txt}.")
    if cpi_yoy is not None:
        lede += f" המדד הכללי עלה ב-12 החודשים האחרונים ב-{_iso(_sp(cpi_yoy))}"
        if rank:
            lede += (f", ובין הפריטים הטווח נע מ-{_iso(_sp(rank[0]['yoy']))} "
                     f"({rank[0]['name']}) ועד {_iso(_sp(rank[-1]['yoy']))} ({rank[-1]['name']})")
        lede += "."
    labels["lede"] = lede

    summary = (f"מדדי מחירים חודשיים של {len(item_codes):,} מוצרים ושירותים: לחם, חלב, קפה, "
               f"דלק, חשמל, מים, תחבורה ציבורית, טיפולי שיניים ועוד, לצד המדד הכללי.")
    if rank:
        summary += (f" ההתייקרות הגדולה ביותר בשנה שעד {month_txt}: {rank[0]['name']} "
                    f"({_sp(rank[0]['yoy'])}).")
    desc = "כמה התייקרו לחם, חלב, דלק, חשמל ועוד מוצרים ושירותים?"
    if rank and cpi_yoy is not None:
        desc += (f" בשנה שעד {month_txt}: {rank[0]['name']} {_sp(rank[0]['yoy'])}, "
                 f"המדד הכללי {_sp(cpi_yoy)}.")
    if len(desc) > 150:
        desc = (f"כמה התייקרו לחם, חלב, דלק, חשמל ועוד? מדד המחירים של {len(item_codes):,} "
                f"מוצרים ושירותים, נכון ל{month_txt}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{start.year}/{L.year}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "כמה התייקרו לחם, חלב ודלק? מדד מחירים לפי מוצר",
                "description": desc,
                "name": "מדד מחירי מוצרים ושירותים נבחרים",
                "alternate_names": [
                    "מדד מחירים לפי מוצר",
                    "התייקרות מוצרי יסוד",
                    "מחירי לחם, חלב ודלק",
                    "מדד המחירים לצרכן של מוצרים ושירותים נבחרים",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
