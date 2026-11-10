"""מדד המחירים לצרכן: Israel's CPI from the CBS Index API.

Inputs (provider `cbs_index`, one row per code and month):
  headline   120010, the general CPI, monthly since September 1951
  groups     the "excluding" indices and the main consumption groups, since 2000
  secondary  the secondary consumption groups, since 2023

Columns: CODE, NAME_HE, FREQ, TIME_PERIOD, DATE, YEAR, PERIOD, VALUE (on the
base in force at the time, BASE_DESC), PERCENT (m/m), PERCENT_YEAR (y/y),
VALUE_CHAINED (every row on the newest base, CHAIN_BASE).

Rules:
- The page's "latest month" is the headline's newest month. Group figures are
  read at that same month; a code without a row there drops out of the view.
- PERCENT / PERCENT_YEAR are quoted as CBS published them (rounded to 0.1).
  Levels and multi-month changes come from VALUE_CHAINED.
- VALUE_CHAINED is chained by the provider across every base change
  (including the 1985 scale break), so the long series is read as is.
- The 1%-3% band is the government's price-stability target that the Bank of
  Israel is charged with: a fixed policy fact, not CBS data.
"""
import math
import re

import pandas as pd
from govlib import fmt

HEADLINE = 120010
EX_FV = 120020
EX_HOUSING = 110040
EX_FV_HOUSING = 120030
EX_ENERGY = 110045
EXCLUDING = [EX_FV, EX_HOUSING, EX_FV_HOUSING, EX_ENERGY]
FOOD_ALL = 110050  # food incl. fruit and vegetables: the sum of two main groups
HOUSING = 120450

TARGET_LOW, TARGET_HIGH = 1.0, 3.0
BAND_FROM = 2003       # band-years insight counts complete years from here
WINDOW_FROM = 2000     # the monthly views (y/y, heatmap, groups) start here
RECENT_MONTHS = 24
SECONDARY_SIDE = 10    # risers and fallers shown in the secondary chart
MIN_SEASON_YEARS = 5

SHORT = {
    HEADLINE: "המדד הכללי",
    EX_FV: "ללא ירקות ופירות",
    EX_HOUSING: "ללא דיור",
    EX_FV_HOUSING: "ללא ירקות ופירות וללא דיור",
    EX_ENERGY: "ללא אנרגיה",
    FOOD_ALL: "מזון כולל ירקות ופירות",
    120050: "מזון (ללא ירקות ופירות)",
    120130: "בשר, עופות ודגים",
    120046: "ירקות קפואים ומשומרים",
    120047: "פירות יבשים ומשומרים",
    120460: "שכר דירה",
    120490: "דיור בבעלות הדיירים",
    120510: "תיווך, חוזים וביטוח דירה",
    120580: "חשמל, גז ומים",
    120630: "מוצרים לתחזוקת משק הבית",
    121450: "טיפוח אישי וקוסמטיקה",
    121484: "שירותים משפטיים, אגרות ושירותי בנק",
    121487: "תכשיטים, שעונים ותיקים",
}

MINUS = fmt.MINUS
MONTHS = fmt.MONTHS_HE
MONTHS_SHORT = fmt.MONTHS_SHORT_HE


# ── parsing ─────────────────────────────────────────────────────────────

def _load(df):
    d = pd.DataFrame({
        "code": pd.to_numeric(df["CODE"].astype(str).str.strip(), errors="coerce"),
        "name": df["NAME_HE"].astype(str).str.strip(),
        "freq": df["FREQ"].astype(str).str.strip(),
        "date": pd.to_datetime(df["DATE"].astype(str).str.strip(), format="%Y-%m-%d",
                               errors="coerce"),
        "value": pd.to_numeric(df["VALUE"].astype(str).str.strip(), errors="coerce"),
        "base": df["BASE_DESC"].astype(str).str.strip(),
        "pct": pd.to_numeric(df["PERCENT"].astype(str).str.strip(), errors="coerce"),
        "pct_y": pd.to_numeric(df["PERCENT_YEAR"].astype(str).str.strip(), errors="coerce"),
        "vc": pd.to_numeric(df["VALUE_CHAINED"].astype(str).str.strip(), errors="coerce"),
        "chain_base": df["CHAIN_BASE"].astype(str).str.strip(),
    })
    d = d[(d["freq"] == "M") & d["code"].notna() & d["date"].notna()].copy()
    d["code"] = d["code"].astype(int)
    d = d.sort_values(["code", "date", "value", "pct"], kind="mergesort")
    d = d.drop_duplicates(["code", "date"], keep="last")
    return d.reset_index(drop=True)


def _next_month(t):
    return pd.Timestamp(year=t.year + (t.month == 12), month=t.month % 12 + 1, day=1)


def _series(d, code):
    g = d[d["code"] == code].sort_values("date", kind="mergesort").reset_index(drop=True).copy()
    g["lvl"] = g["vc"]
    return g


# ── formatting ──────────────────────────────────────────────────────────

def _p(v, d=1):
    """-0.5 → '−0.5%' (bare, for KPI values and tables)."""
    s = f"{abs(v):.{d}f}"
    return (MINUS if v < 0 and float(s) != 0 else "") + s + "%"


def _sp(v, d=1):
    """Signed: '+1.6%', '−0.5%', '0.0%'."""
    s = f"{abs(v):.{d}f}"
    if float(s) == 0:
        return s + "%"
    return ("+" if v > 0 else MINUS) + s + "%"


def _ip(v, d=1):
    """A percent inside a Hebrew sentence (isolated so the sign stays put)."""
    return fmt.isolate(_p(v, d))


def _isp(v, d=1):
    return fmt.isolate(_sp(v, d))


def _num(v, d=1):
    s = f"{abs(v):,.{d}f}"
    return (MINUS if v < 0 and float(s.replace(",", "")) != 0 else "") + s


def _month(t):
    return f"{MONTHS[t.month - 1]} {t.year}"


def _mshort(t):
    return f"{MONTHS_SHORT[t.month - 1]} {t.year}"


def _ym(t):
    return f"{t.year}-{t.month:02d}"


def _base_label(desc):
    m = re.fullmatch(r"(\d{4})\s*ממוצע", desc or "")
    if m:
        return f"ממוצע {m.group(1)} = 100"
    return f"{desc} = 100" if desc else ""


def _label(code, name):
    return SHORT.get(code) or name or str(code)


def _sig(v, n=4):
    if not math.isfinite(v) or v == 0:
        return None
    return float(f"{v:.{n}g}")


def _band_state(v):
    if v < TARGET_LOW:
        return "below"
    if v > TARGET_HIGH:
        return "above"
    return "in"


def _band_tone(v):
    if TARGET_LOW <= v <= TARGET_HIGH:
        return "ok"
    if TARGET_LOW - 1 <= v <= TARGET_HIGH + 1:
        return "warn"
    return "danger"


def _change_phrase(v, iso=True):
    """'עלייה של 0.7%', 'ירידה של 0.5%', 'יציבות'."""
    s = f"{abs(v):.1f}"
    if float(s) == 0:
        return "יציבות"
    num = fmt.isolate(s + "%") if iso else s + "%"
    return ("עלייה" if v > 0 else "ירידה") + f" של {num}"


def _rise_word(v, plural=False):
    if plural:
        return "עלו" if v > 0 else "ירדו"
    return "עלה" if v > 0 else "ירד"


def _at(g, t, col):
    r = g[g["date"] == t]
    if r.empty:
        return None
    v = float(r[col].iloc[0])
    return v if math.isfinite(v) else None


# ── compute ─────────────────────────────────────────────────────────────

def compute(frames):
    hd = _load(frames["headline"])
    gd = _load(frames["groups"])
    sd = _load(frames["secondary"])

    head = _series(hd, HEADLINE)
    head = head[head["lvl"].notna() & (head["lvl"] > 0)].reset_index(drop=True)
    if len(head) < 26:
        raise ValueError("headline CPI has too few months")
    last = head.iloc[-1]
    t_last = last["date"]
    month_txt = _month(t_last)
    name_by_code = {}
    for d in (gd, sd):
        for code, nm in d.drop_duplicates("code")[["code", "name"]].itertuples(index=False):
            name_by_code[int(code)] = nm

    mm = float(last["pct"]) if math.isfinite(last["pct"]) else None
    yy = float(last["pct_y"]) if math.isfinite(last["pct_y"]) else None
    base_label = _base_label(str(last["base"]))
    chain_label = _base_label(str(last["chain_base"]))

    labels, kpis, charts, tables, flags = {}, {}, {}, {}, {}
    insights = []
    labels["col_y12"] = "שינוי ב-12 חודשים"

    # ── KPIs ──
    if mm is not None:
        kpis["mm"] = {"value": mm, "display": _p(mm), "tone": "brand"}
        labels["mm_kpi"] = f"שינוי חודשי, {month_txt}"
    if yy is not None:
        kpis["yy"] = {"value": yy, "display": _p(yy), "tone": _band_tone(yy)}
        labels["yy_kpi"] = f"אינפלציה ב-12 החודשים האחרונים (עד {month_txt})"
    kpis["level"] = {"value": float(last["value"]), "display": _num(float(last["value"])),
                     "tone": "brand"}
    labels["level_kpi"] = f"רמת המדד ב{month_txt} (בסיס: {base_label})"

    dec_prev = pd.Timestamp(year=t_last.year - 1, month=12, day=1)
    lvl_dec = _at(head, dec_prev, "lvl")
    ytd = None
    if lvl_dec and t_last.month != 12:
        ytd = (float(last["lvl"]) / lvl_dec - 1) * 100
        kpis["ytd"] = {"value": round(ytd, 1), "display": _p(ytd), "tone": "brand"}
        labels["ytd_kpi"] = f"שינוי מתחילת {t_last.year} (מדצמבר {t_last.year - 1})"

    groups = {}
    for code in sorted(gd["code"].unique()):
        g = _series(gd, int(code))
        g = g[g["date"] <= t_last].reset_index(drop=True)
        if not g.empty:
            groups[int(code)] = g
    core = groups.get(EX_FV_HOUSING)
    core_y = _at(core, t_last, "pct_y") if core is not None else None
    if core_y is not None:
        kpis["core"] = {"value": core_y, "display": _p(core_y), "tone": _band_tone(core_y)}
        labels["core_kpi"] = "אינפלציה שנתית ללא ירקות ופירות וללא דיור"
    flags["kpi_order"] = [k for k in ("yy", "mm", "level", "ytd", "core") if k in kpis]

    # ── lede ──
    parts = [(f"מדד המחירים לצרכן של הלשכה המרכזית לסטטיסטיקה ל{month_txt} עמד על "
              f"{_num(float(last['value']))} נקודות (בסיס: {base_label}).")]
    if mm is not None and yy is not None:
        parts.append(f"זו {_change_phrase(mm)} לעומת החודש הקודם, והאינפלציה ב-12 החודשים "
                     f"האחרונים היא {_ip(yy)}.")
    nxt = _next_month(t_last)
    parts.append(f"המדד מתפרסם פעם בחודש: מדד {_month(nxt)} צפוי להתפרסם באמצע "
                 f"{_month(_next_month(nxt))}. העמוד מציג את המדד הכללי מאז "
                 f"{_month(head['date'].iloc[0])}, את המדדים ללא רכיבים ואת קבוצות הצריכה.")
    labels["lede"] = " ".join(parts)

    # ── y/y against the target band ──
    win_from = min(WINDOW_FROM, t_last.year - 10)
    hy = head[(head["date"].dt.year >= win_from) & head["pct_y"].notna()]
    charts["yy"] = {"x": [_ym(t) for t in hy["date"]],
                    "y": [round(float(v), 1) for v in hy["pct_y"]],
                    "lo": TARGET_LOW, "hi": TARGET_HIGH}
    band_txt = f"{fmt.isolate(_p(TARGET_LOW, 0))} עד {fmt.isolate(_p(TARGET_HIGH, 0))}"
    labels["band"] = band_txt
    labels["band_lo"] = _p(TARGET_LOW, 0)
    labels["band_hi"] = _p(TARGET_HIGH, 0)
    yrows = []
    for year, g in hy.groupby(hy["date"].dt.year, sort=True):
        decv = g[g["date"].dt.month == 12]["pct_y"]
        inside = int(((g["pct_y"] >= TARGET_LOW) & (g["pct_y"] <= TARGET_HIGH)).sum())
        yrows.append([str(int(year)),
                      _p(float(decv.iloc[0])) if len(decv) else "–",
                      _p(float(g["pct_y"].max())), _p(float(g["pct_y"].min())),
                      f"{inside} מתוך {len(g)}"])
    tables["yy"] = yrows
    if len(hy):
        imax = int(hy["pct_y"].to_numpy().argmax())
        labels["yy_aria"] = (f"גרף קו: האינפלציה השנתית בכל חודש מאז {_month(hy['date'].iloc[0])}, "
                             f"מול טווח היעד של {band_txt}. בחודש האחרון {_p(yy) if yy is not None else ''}; "
                             f"השיא בתקופה {_p(float(hy['pct_y'].iloc[imax]))} ב{_month(hy['date'].iloc[imax])}.")
        recent = hy[hy["date"].dt.year >= t_last.year - 4]
        in_n = int(((recent["pct_y"] >= TARGET_LOW) & (recent["pct_y"] <= TARGET_HIGH)).sum())
        labels["yy_note"] = (f"השינוי במדד לעומת אותו חודש בשנה הקודמת, כפי שפרסמה הלמ\"ס. הרצועה "
                             f"הירוקה היא טווח היעד ({band_txt}). ב-{len(recent)} החודשים מאז "
                             f"ינואר {t_last.year - 4} האינפלציה הייתה בתוך הטווח ב-{in_n} חודשים.")

    # insight: target band + streak
    if yy is not None:
        states = [_band_state(float(v)) for v in head["pct_y"] if math.isfinite(v)]
        cur = states[-1]
        streak = 0
        for s in reversed(states):
            if s != cur:
                break
            streak += 1
        prev_streak, prev_state = 0, None
        for s in reversed(states[:len(states) - streak]):
            if prev_state is None:
                prev_state = s
            if s != prev_state:
                break
            prev_streak += 1
        where = {"in": "בתוך טווח היעד", "above": "מעל טווח היעד",
                 "below": "מתחת לטווח היעד"}
        text = (f"האינפלציה השנתית ב{month_txt} הייתה {_ip(yy)}, {where[cur]} של הממשלה ובנק "
                f"ישראל ({band_txt}).")
        if streak > 1:
            text += f" זה החודש ה-{streak} ברציפות {where[cur]}."
        elif prev_state is not None:
            text += f" זה החודש הראשון כך, אחרי {prev_streak} חודשים {where[prev_state]}."
        insights.append({"id": "target", "text_he": text})

    # ── recent months m/m ──
    rec = head[head["pct"].notna()].tail(RECENT_MONTHS)
    charts["recent"] = {"x": [_mshort(t) for t in rec["date"]],
                        "y": [round(float(v), 1) for v in rec["pct"]]}
    tables["recent"] = [[_month(t), _p(float(p)), _p(float(y)) if math.isfinite(y) else "–"]
                        for t, p, y in zip(rec["date"], rec["pct"], rec["pct_y"])][::-1]
    up = int((rec["pct"] > 0).sum())
    down = int((rec["pct"] < 0).sum())
    labels["recent_aria"] = (f"גרף עמודות: השינוי החודשי במדד ב-{len(rec)} החודשים האחרונים. "
                             f"{up} חודשי עלייה ו-{down} חודשי ירידה.")
    flat = len(rec) - up - down
    labels["recent_note"] = (f"השינוי במדד לעומת החודש הקודם, ב-{len(rec)} החודשים האחרונים: "
                             f"{up} חודשי עלייה, {down} חודשי ירידה"
                             + (f" ו-{flat} ללא שינוי." if flat else "."))

    # ── seasonality heatmap ──
    hm = head[(head["date"].dt.year >= win_from) & head["pct"].notna()]
    years = sorted({int(t.year) for t in hm["date"]})
    yidx = {y: i for i, y in enumerate(years)}
    cells = [[int(t.month) - 1, yidx[int(t.year)], round(float(v), 1)]
             for t, v in zip(hm["date"], hm["pct"])]
    absv = sorted(abs(c[2]) for c in cells)
    vmax = absv[int(0.95 * (len(absv) - 1))] if absv else 1.0
    vmax = max(0.5, math.ceil(vmax * 2) / 2)
    charts["heat"] = {"years": [str(y) for y in years], "months": MONTHS_SHORT,
                      "cells": cells, "vmax": vmax}
    grid = {(int(t.year), int(t.month)): float(v) for t, v in zip(hm["date"], hm["pct"])}
    tables["heat"] = [[str(y)] + [_num(grid[(y, m)]) if (y, m) in grid else "–"
                                  for m in range(1, 13)] for y in reversed(years)]
    labels["heat_months"] = MONTHS_SHORT
    full_years = hm[hm["date"].dt.year < t_last.year]
    season = full_years.groupby(full_years["date"].dt.month)["pct"].agg(["mean", "count"])
    if len(season) == 12:
        hi_m = int(season["mean"].idxmax())
        lo_m = int(season["mean"].idxmin())
        labels["heat_note"] = (f"כל משבצת היא השינוי החודשי באחוזים (כחול: ירידה, אדום: עלייה; "
                               f"הצבע מגיע לשיאו ב-{_p(vmax)}). בממוצע השנים {years[0]}-"
                               f"{t_last.year - 1} המדד עולה הכי הרבה ב{MONTHS[hi_m - 1]} "
                               f"({_ip(float(season.loc[hi_m, 'mean']), 2)}) "
                               + ("ויורד הכי הרבה" if season.loc[lo_m, "mean"] < 0 else "ועולה הכי מעט")
                               + f" ב{MONTHS[lo_m - 1]} ({_ip(float(season.loc[lo_m, 'mean']), 2)}).")
    else:
        labels["heat_note"] = "כל משבצת היא השינוי החודשי באחוזים (כחול: ירידה, אדום: עלייה)."
    labels["heat_aria"] = (f"מפת חום: השינוי החודשי במדד לפי חודש ושנה, {years[0]}-{years[-1]}."
                           if years else "מפת חום: השינוי החודשי במדד לפי חודש ושנה.")

    # insight: this month vs its usual seasonal move
    if mm is not None and t_last.month in season.index:
        n_years = int(season.loc[t_last.month, "count"])
        avg = float(season.loc[t_last.month, "mean"])
        if n_years >= MIN_SEASON_YEARS:
            mname = MONTHS[t_last.month - 1]
            if avg <= -0.15:
                usual = f"ב{mname} המדד נוטה לרדת"
            elif avg >= 0.15:
                usual = f"ב{mname} המדד נוטה לעלות"
            else:
                usual = f"ב{mname} המדד כמעט אינו משתנה בדרך כלל"
            insights.append({"id": "season", "text_he": (
                f"במדד {month_txt} נרשמה {_change_phrase(mm)} לעומת החודש הקודם. {usual}: "
                f"השינוי הממוצע בחודש זה בשנים {years[0]}-{t_last.year - 1} הוא "
                f"{_ip(avg, 2)}.")})

    # insight: year to date
    if ytd is not None:
        word = "עלה" if ytd > 0.05 else ("ירד" if ytd < -0.05 else "כמעט לא השתנה")
        tail = f" ב-{_ip(abs(ytd))}" if word != "כמעט לא השתנה" else ""
        insights.append({"id": "ytd", "text_he": (
            f"מתחילת {t_last.year} (מדצמבר {t_last.year - 1} עד {month_txt}) {word} "
            f"המדד{tail}.")})

    # ── main groups, latest y/y ──
    main = [c for c in groups if c not in EXCLUDING and c != FOOD_ALL]
    grows = []
    for c in main:
        y = _at(groups[c], t_last, "pct_y")
        if y is None:
            continue
        grows.append((c, _label(c, name_by_code.get(c, "")), y,
                      _at(groups[c], t_last, "pct"), _at(groups[c], t_last, "value")))
    grows.sort(key=lambda r: (-r[2], r[0]))
    flags["groups"] = len(grows) >= 3
    if flags["groups"]:
        charts["groups"] = {"names": [r[1] for r in grows], "y": [r[2] for r in grows],
                            "headline": yy}
        trows = [[r[1], _p(r[3]) if r[3] is not None else "–", _p(r[2]),
                  _num(r[4]) if r[4] is not None else "–"] for r in grows]
        fa = groups.get(FOOD_ALL)
        fa_y = _at(fa, t_last, "pct_y") if fa is not None else None
        if fa_y is not None:
            fa_m = _at(fa, t_last, "pct")
            fa_v = _at(fa, t_last, "value")
            trows.append([_label(FOOD_ALL, name_by_code.get(FOOD_ALL, "")) + " (סיכום שתי קבוצות המזון)",
                          _p(fa_m) if fa_m is not None else "–", _p(fa_y),
                          _num(fa_v) if fa_v is not None else "–"])
        tables["groups"] = trows
        top, bot = grows[0], grows[-1]
        labels["groups_aria"] = (f"גרף עמודות: השינוי ב-12 החודשים האחרונים ב-{len(grows)} קבוצות "
                                 f"הצריכה הראשיות, עד {month_txt}. הגבוה: {top[1]} ({_p(top[2])}); "
                                 f"הנמוך: {bot[1]} ({_p(bot[2])}).")
        above = sum(1 for r in grows if yy is not None and r[2] > yy)
        labels["groups_note"] = (f"השינוי במחירי כל קבוצת צריכה לעומת {_month(pd.Timestamp(year=t_last.year - 1, month=t_last.month, day=1))}. "
                                 + (f"הקו המקווקו הוא המדד הכללי ({_p(yy)}); {above} מתוך "
                                    f"{len(grows)} הקבוצות התייקרו יותר ממנו. " if yy is not None else "")
                                 + "המאגר אינו כולל את משקל כל קבוצה בסל, ולכן אין כאן חישוב "
                                   "של תרומת כל קבוצה למדד הכללי.")
        bot_txt = (f"ובקבוצת {bot[1]} המחירים ירדו הכי הרבה ({_isp(bot[2])})" if bot[2] < 0
                   else f"ובקבוצת {bot[1]} הם עלו הכי מעט ({_isp(bot[2])})")
        top_txt = (f"בקבוצת {top[1]} המחירים עלו הכי הרבה" if top[2] > 0
                   else f"בקבוצת {top[1]} המחירים ירדו הכי מעט")
        insights.append({"id": "groups", "text_he": (
            f"מבין {len(grows)} קבוצות הצריכה הראשיות, {top_txt} "
            f"ב-12 החודשים האחרונים ({_isp(top[2])}), {bot_txt}.")})

    # insight: housing effect
    exh = groups.get(EX_HOUSING)
    exh_y = _at(exh, t_last, "pct_y") if exh is not None else None
    hous = groups.get(HOUSING)
    hous_y = _at(hous, t_last, "pct_y") if hous is not None else None
    if yy is not None and exh_y is not None and hous_y is not None:
        diff = yy - exh_y
        if diff >= 0.3:
            insights.append({"id": "housing", "text_he": (
                f"הדיור מושך את המדד למעלה: מחירי סעיף הדיור (בעיקר שכר דירה ושירותי דיור בבעלות "
                f"הדיירים) {_rise_word(hous_y, plural=True)} ב-{_ip(abs(hous_y))} ב-12 החודשים "
                f"האחרונים, וללא הדיור האינפלציה "
                f"השנתית הייתה {_ip(exh_y)} בלבד, לעומת {_ip(yy)} במדד הכללי.")})
        elif diff <= -0.3:
            insights.append({"id": "housing", "text_he": (
                "הדיור מושך את המדד למטה: מחירי סעיף הדיור "
                + (f"{_rise_word(hous_y, plural=True)} ב-{_ip(abs(hous_y))}" if round(hous_y, 1) != 0
                   else "לא השתנו")
                + " ב-12 "
                f"החודשים האחרונים, וללא הדיור האינפלציה השנתית הייתה {_ip(exh_y)}, "
                f"לעומת {_ip(yy)} במדד הכללי.")})

    # ── groups rebased to a common start ──
    reb_codes = [c for c in main if c in groups]
    if flags["groups"] and reb_codes:
        starts = [groups[c]["date"].iloc[0] for c in reb_codes]
        t0 = max(max(starts), pd.Timestamp(year=win_from, month=1, day=1))
        h0 = _at(head, t0, "lvl")
        series = []
        rrows = []
        span_years = (t_last.year - t0.year) + (t_last.month - t0.month) / 12
        for c in [HEADLINE] + reb_codes:
            g = head if c == HEADLINE else groups[c]
            g = g[(g["date"] >= t0) & g["lvl"].notna()]
            base = h0 if c == HEADLINE else _at(groups[c], t0, "lvl")
            if not base or g.empty or g["date"].iloc[-1] != t_last:
                continue
            m = {t: round(float(v) / base * 100, 1) for t, v in zip(g["date"], g["lvl"])}
            nm = _label(c, name_by_code.get(c, ""))
            series.append({"name": nm, "m": m, "headline": c == HEADLINE})
            end = float(g["lvl"].iloc[-1]) / base
            ann = (end ** (1 / span_years) - 1) * 100 if span_years >= 1 else None
            rrows.append((c, nm, (end - 1) * 100, ann, round(end * 100, 1)))
        flags["rebased"] = len(series) >= 3 and span_years >= 1
        if flags["rebased"]:
            months = sorted({t for s in series for t in s["m"]})
            charts["rebased"] = {
                "x": [_ym(t) for t in months],
                "series": [{"name": s["name"], "headline": s["headline"],
                            "y": [s["m"].get(t) for t in months]} for s in series],
            }
            hrow = [r for r in rrows if r[0] == HEADLINE]
            others = sorted([r for r in rrows if r[0] != HEADLINE], key=lambda r: (-r[2], r[0]))
            tables["rebased"] = [[r[1], _num(r[4]), _p(r[2]), _p(r[3]) if r[3] is not None else "–"]
                                 for r in hrow + others]
            labels["rebased_start"] = _month(t0)
            labels["rebased_col"] = f"רמה היום ({_month(t0)} = 100)"
            top, bot = others[0], others[-1]
            labels["rebased_aria"] = (f"גרף קווים: קבוצות הצריכה הראשיות מאז {_month(t0)} "
                                      f"({_month(t0)} = 100). השינוי הגדול ביותר: {top[1]} "
                                      f"({_p(top[2])}); הקטן ביותר: {bot[1]} ({_p(bot[2])}).")
            labels["rebased_note"] = (f"כל קבוצה מוצגת יחסית לרמתה ב{_month(t0)} (= 100), כך שאפשר "
                                      f"להשוות בין הקבוצות. לחיצה על שם קבוצה במקרא מסתירה אותה או "
                                      f"מציגה אותה.")
            if hrow:
                bot_txt = (f"ואילו מחירי {bot[1]} ירדו ב-{_ip(abs(bot[2]))}" if bot[2] < 0
                           else f"ואילו מחירי {bot[1]} עלו ב-{_ip(bot[2])} בלבד")
                insights.append({"id": "since_start", "text_he": (
                    f"מאז {_month(t0)} {_rise_word(hrow[0][2])} המדד הכללי ב-{_ip(abs(hrow[0][2]))}. "
                    f"מחירי {top[1]} {_rise_word(top[2], plural=True)} ב-{_ip(abs(top[2]))}, "
                    f"{bot_txt}.")})
    else:
        flags["rebased"] = False

    # ── excluding indices vs headline ──
    ex_series = []
    exh_from = pd.Timestamp(year=win_from, month=1, day=1)
    xs = [t for t in head["date"] if t >= exh_from]
    xkeys = [_ym(t) for t in xs]
    hmap = dict(zip(head["date"], head["pct_y"]))
    ex_series.append({"name": SHORT[HEADLINE],
                      "y": [round(float(hmap[t]), 1) if math.isfinite(hmap[t]) else None for t in xs]})
    ex_rows = []
    t_prev = pd.Timestamp(year=t_last.year - 1, month=t_last.month, day=1)
    if yy is not None:
        ex_rows.append([SHORT[HEADLINE], _p(yy),
                        _p(hmap[t_prev]) if t_prev in hmap and math.isfinite(hmap[t_prev]) else "–"])
    for c in EXCLUDING:
        g = groups.get(c)
        if g is None:
            continue
        m = dict(zip(g["date"], g["pct_y"]))
        ys = [round(float(m[t]), 1) if t in m and math.isfinite(m[t]) else None for t in xs]
        cur = _at(g, t_last, "pct_y")
        if cur is None or sum(v is not None for v in ys) < 12:
            continue
        ex_series.append({"name": _label(c, name_by_code.get(c, "")), "y": ys})
        prev = _at(g, t_prev, "pct_y")
        ex_rows.append([_label(c, name_by_code.get(c, "")), _p(cur),
                        _p(prev) if prev is not None else "–"])
    flags["excluding"] = len(ex_series) >= 2
    if flags["excluding"]:
        charts["excluding"] = {"x": xkeys, "series": ex_series, "lo": TARGET_LOW,
                               "hi": TARGET_HIGH}
        tables["excluding"] = ex_rows
        labels["ex_now"] = f"שינוי שנתי, {month_txt}"
        labels["ex_prev"] = f"שינוי שנתי, {_month(t_prev)}"
        cur_vals = [(r[0], r[1]) for r in ex_rows]
        labels["excluding_aria"] = ("גרף קווים: האינפלציה השנתית במדד הכללי ובמדדים ללא רכיבים. "
                                    f"ב{month_txt}: " + ", ".join(f"{n} {v}" for n, v in cur_vals) + ".")
        labels["excluding_note"] = ("המדדים ללא רכיבים מוציאים מהסל את הסעיפים התנודתיים או "
                                    "המיוחדים (ירקות ופירות, דיור, אנרגיה), ומראים את קצב עליית "
                                    "המחירים של שאר הסל. הם מתפרסמים על ידי הלמ\"ס יחד עם המדד הכללי.")
        if core_y is not None and yy is not None:
            gap = core_y - yy
            if abs(gap) >= 0.3:
                side = "נמוכה" if gap < 0 else "גבוהה"
                insights.append({"id": "core", "text_he": (
                    f"בלי ירקות ופירות ובלי דיור, האינפלציה השנתית ב{month_txt} הייתה "
                    f"{_ip(core_y)}, {side} מזו של המדד הכללי ({_ip(yy)}): הסעיפים שהוצאו "
                    f"{'דוחפים את המדד למעלה' if gap < 0 else 'מושכים את המדד למטה'}.")})

    # ── secondary groups ──
    srows = []
    for code in sorted(sd["code"].unique()):
        g = sd[(sd["code"] == code) & (sd["date"] == t_last)]
        if g.empty or not math.isfinite(g["pct_y"].iloc[0]):
            continue
        srows.append((int(code), _label(int(code), g["name"].iloc[0]),
                      float(g["pct_y"].iloc[0]),
                      float(g["pct"].iloc[0]) if math.isfinite(g["pct"].iloc[0]) else None))
    srows.sort(key=lambda r: (-r[2], r[0]))
    flags["secondary"] = len(srows) >= 6
    if flags["secondary"]:
        side = min(SECONDARY_SIDE, len(srows) // 2)
        pick = srows[:side] + srows[-side:]
        charts["secondary"] = {"names": [r[1] for r in pick], "y": [r[2] for r in pick],
                               "headline": yy}
        tables["secondary"] = [[r[1], _p(r[3]) if r[3] is not None else "–", _p(r[2])]
                               for r in srows]
        labels["secondary_aria"] = (f"גרף עמודות אופקי: {side} הקבוצות המשניות שהתייקרו הכי הרבה "
                                    f"ו-{side} שהתייקרו הכי מעט ב-12 החודשים עד {month_txt}, "
                                    f"מתוך {len(srows)}. בראש: {srows[0][1]} ({_p(srows[0][2])}).")
        labels["secondary_note"] = (f"השינוי ב-12 החודשים עד {month_txt} ב-{side} הקבוצות המשניות "
                                    f"שהתייקרו הכי הרבה וב-{side} שהתייקרו הכי מעט (או הוזלו), מתוך "
                                    f"{len(srows)} קבוצות. הקו המקווקו הוא המדד הכללי. "
                                    "הרשימה המלאה בטבלה.")
        t3 = [r for r in srows[:3] if r[2] > 0]
        if t3:
            txt = (f"בפירוט ל-{len(srows)} קבוצות צריכה משניות, ההתייקרות החדה ביותר ב-12 "
                   f"החודשים האחרונים: " + fmt.join_he([f"{r[1]} ({_isp(r[2])})" for r in t3]) + ".")
        else:
            txt = (f"באף אחת מ-{len(srows)} קבוצות הצריכה המשניות המחירים לא עלו ב-12 החודשים "
                   "האחרונים.")
        lo = srows[-1]
        if lo[2] < 0:
            txt += f" הירידה החדה ביותר: {lo[1]} ({_isp(lo[2])})."
        insights.append({"id": "secondary", "text_he": txt})

    # ── annual inflation since 1951 (December on December, as published) ──
    decs = head[(head["date"].dt.month == 12)].reset_index(drop=True)
    ann = []
    for _, r in decs.iterrows():
        v = r["pct_y"]
        if not math.isfinite(v):
            prev = decs[decs["date"] == pd.Timestamp(year=r["date"].year - 1, month=12, day=1)]
            if prev.empty:
                continue
            v = (float(r["lvl"]) / float(prev["lvl"].iloc[0]) - 1) * 100
        ann.append((int(r["date"].year), round(float(v), 1)))
    flags["annual"] = len(ann) >= 5
    if flags["annual"]:
        charts["annual"] = {"x": [str(y) for y, _ in ann], "y": [v for _, v in ann],
                            "lo": TARGET_LOW, "hi": TARGET_HIGH}
        tables["annual"] = [[str(y), _p(v)] for y, v in reversed(ann)]
        ymax = max(ann, key=lambda a: (a[1], -a[0]))
        ymin = min(ann, key=lambda a: (a[1], a[0]))
        labels["annual_aria"] = (f"גרף עמודות: האינפלציה השנתית בישראל, {ann[0][0]}-{ann[-1][0]}. "
                                 f"השיא {_p(ymax[1])} ב-{ymax[0]}, השפל {_p(ymin[1])} ב-{ymin[0]}.")
        labels["annual_note"] = (f"השינוי במדד מדצמבר לדצמבר בכל שנה שלמה, {ann[0][0]}-{ann[-1][0]}. "
                                 f"שנות האינפלציה הגבוהה מגיעות עד {_p(ymax[1])} (ב-{ymax[0]}), "
                                 f"ולכן הגרף נפתח על השנים מ-{ann[max(0, len(ann) - 30)][0]}: "
                                 "אפשר לגרור את הסרגל שמתחתיו כדי לראות את כל התקופה.")
        charts["annual"]["zoom_from"] = str(ann[max(0, len(ann) - 30)][0])
        band = [(y, v) for y, v in ann if y >= BAND_FROM]
        if len(band) >= 5:
            k = sum(1 for _, v in band if TARGET_LOW <= v <= TARGET_HIGH)
            a = sum(1 for _, v in band if v > TARGET_HIGH)
            b = sum(1 for _, v in band if v < TARGET_LOW)
            insights.append({"id": "band_years", "text_he": (
                f"בשנים {band[0][0]}-{band[-1][0]} האינפלציה השנתית (דצמבר מול דצמבר) הייתה "
                f"בתוך טווח היעד ב-{k} מתוך {len(band)} השנים, מעליו ב-{a} ומתחתיו ב-{b}. "
                f"בשנת {band[-1][0]} היא עמדה על {_ip(band[-1][1])}.")})

    # ── the level over the long run (log scale) ──
    lv = head[head["lvl"].notna()]
    charts["level"] = {"x": [_ym(t) for t in lv["date"]],
                       "y": [_sig(float(v)) for v in lv["lvl"]]}
    first = lv.iloc[0]
    mult = float(last["lvl"]) / float(first["lvl"])
    mult_txt = f"{fmt.int_he(mult / 1000)} אלף" if mult >= 10000 else fmt.int_he(mult)
    labels["level_aria"] = (f"גרף קו בסולם לוגריתמי: רמת המדד מאז {_month(first['date'])} "
                            f"(בסיס: {chain_label}). המחירים עלו מאז פי {mult_txt}.")
    labels["level_note"] = (f"כל החודשים מוצגים על בסיס אחד ({chain_label}), לפי מקדמי הקישור "
                            "הרשמיים של הלמ\"ס. הציר האנכי לוגריתמי: כל קו רשת גבוה פי עשרה מזה "
                            "שמתחתיו, כך ששיפוע תלול פירושו קצב עליית מחירים מהיר.")
    lrows = []
    for y in range(int(first["date"].year), t_last.year + 1):
        if y % 10 != 0 and y != t_last.year:
            continue
        t = pd.Timestamp(year=y, month=1, day=1) if y != t_last.year else t_last
        v = _at(lv, t, "lvl")
        if v is None:
            continue
        lrows.append([_month(t), f"{_sig(v):,g}" if v < 1 else _num(v)])
    if not lrows or lrows[0][0] != _month(first["date"]):
        lrows.insert(0, [_month(first["date"]), f"{_sig(float(first['lvl'])):,g}"])
    tables["level"] = lrows
    if flags["annual"]:
        ymax = max(ann, key=lambda a: (a[1], -a[0]))
        insights.append({"id": "longrun", "text_he": (
            f"מאז {_month(first['date'])} עלו המחירים לצרכן בישראל פי {mult_txt}. שיא "
            f"האינפלציה נרשם ב-{ymax[0]}, אז עלה המדד ב-{_ip(ymax[1])} בשנה אחת.")})

    # ── notes ──
    labels["target_note"] = (f"טווח היעד ({band_txt} בשנה) הוא יעד יציבות המחירים שקבעה הממשלה ושבנק "
                             "ישראל אחראי לעמוד בו. הוא נתון קבוע שמוצג לצורך השוואה, ואינו חלק "
                             "מנתוני הלמ\"ס.")
    labels["base_note"] = (f"רמת המדד בעמוד היא על הבסיס הנוכחי ({base_label}). השינויים החודשיים "
                           "והשנתיים מוצגים כפי שפרסמה הלמ\"ס, מעוגלים לעשירית האחוז; שינוי "
                           "שמחושב מרמות המדד עשוי להיות שונה מהם בעשירית.")

    # ── agent_data ──
    first_year = int(head["date"].iloc[0].year)
    summary = (f"מדד המחירים לצרכן של הלמ\"ס: ב{month_txt} "
               + (f"{_change_phrase(mm, iso=False)} בחודש, " if mm is not None else "")
               + (f"אינפלציה שנתית של {_p(yy)}. " if yy is not None else "")
               + f"המדד הכללי מאז {first_year}, המדדים ללא רכיבים וקבוצות הצריכה.")
    desc = (f"מדד המחירים לצרכן האחרון: ב{month_txt} "
            + (f"{_change_phrase(mm, iso=False)} בחודש" if mm is not None else "")
            + (f" ואינפלציה של {_p(yy)} ב-12 חודשים" if yy is not None else "")
            + ". האינפלציה מול היעד, קבוצות הצריכה והמדד מאז "
            + f"{first_year}.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "temporal_coverage": f"{first_year}/{t_last.year}",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "מדד המחירים לצרכן: המדד האחרון והאינפלציה בישראל",
            "description": desc,
            "name": "מדד המחירים לצרכן",
            "alternate_names": ["מדד המחירים לצרכן האחרון", "אינפלציה בישראל",
                                "מדד יוקר המחיה", "מדד המחירים לצרכן - כללי"],
        },
    }

    labels["latest_month"] = month_txt
    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
    }
