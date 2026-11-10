"""מדד מחירי יצרן: the CBS producer price index of industrial output sold
domestically (מדד המחירים הסיטוניים של תפוקת התעשייה ליעדים מקומיים).

Inputs (CBS Index API, one row per code and month):
  long         170010 industry + mining & quarrying (B,C) and 170020 the same
               without fuels, from 1995: the only series with a long history.
  branches     170030 industry (C, the chapter's main code, the headline),
               170050 industry without fuels, mining 180010 and its two parts,
               and every main industry group of the 2011 classification, 2013→.
  subbranches  a chosen set of sub-industries, 2013→.

Levels are VALUE_CHAINED (every month on the newest base, CHAIN_BASE); monthly
and yearly changes are CBS's published PERCENT / PERCENT_YEAR. "Latest" is the
newest month of the headline code. A code whose newest month is older than
that (discontinued) is left out of every comparison, and the page says how
many were left out.
"""
import math
import re

import pandas as pd
from govlib import fmt

HEAD = 170030      # industry (C): the headline
HEAD_XF = 170050   # industry without fuels
LONG = 170010      # industry + mining & quarrying, since 1995
LONG_XF = 170020   # the same without fuels
REFINED = 180610   # refined petroleum products
OIL_GAS = 180015   # crude oil and natural gas extraction
AGGREGATES = {HEAD, HEAD_XF, LONG, LONG_XF}
MINING_PARTS = {180015, 180025}  # parts of 180010, which the ranking shows

RECENT_MONTHS = 24     # monthly-change bars
HEAT_MONTHS = 13       # heatmap columns
VOL_MONTHS = 60        # volatility window
SUB_SIDE = 10          # sub-industries per side (rises / falls)
LATE_START_MONTHS = 12  # a code starting this much after the rest skips the rebased views
SMALL_STEP = 3         # small multiples plot every 3rd month (sparklines; ~29 of them)
STALE_MONTHS = 4       # a code this many months behind the headline reads as discontinued
FUEL_GAP_PP = 1.0      # headline vs ex-fuels gap worth a sentence
STREAK_MIN = 3

SHORT = {
    170030: "תפוקת התעשייה",
    170050: "התעשייה ללא דלקים",
    170010: "התעשייה וכרייה וחציבה",
    170020: "התעשייה וכרייה וחציבה, ללא דלקים",
    180010: "כרייה וחציבה",
    180015: "הפקת נפט וגז טבעי",
    180025: "כרייה וחציבה אחרת",
    180070: "מוצרי מזון",
    180235: "משקאות",
    180260: "מוצרי טבק",
    180280: "טקסטיל",
    180370: "מוצרי הלבשה",
    180420: "מוצרי עור",
    180475: "מוצרי עץ",
    180510: "נייר ומוצריו",
    180575: "הדפסה",
    180610: "מוצרי נפט מזוקק",
    180625: "כימיקלים ומוצריהם",
    180680: "תרופות",
    180720: "גומי ופלסטיק",
    180810: "מוצרים ממינרלים אל-מתכתיים",
    180880: "מתכות בסיסיות",
    180940: "מוצרי מתכת",
    181153: "מחשבים, אלקטרוניקה ואופטיקה",
    181090: "ציוד חשמלי",
    181030: "מכונות וציוד",
    181460: "כלי רכב מנועיים",
    181500: "כלי תחבורה אחרים",
    181530: "רהיטים",
    181550: "ענפי ייצור אחרים",
    181630: "תיקון והתקנת מכונות",
    180030: "חציבת אבן, חול וחומר",
    180045: "הפקת מלחים",
    180050: "כריית מינרלים לכימיקלים ודשנים",
    180073: "עיבוד ושימור בשר",
    180077: "משחטות",
    180090: "שימורי פירות וירקות",
    180110: "שמנים מן הצומח",
    180120: "מוצרי חלב",
    180130: "טחינת תבואה",
    180165: "דברי מאפה",
    180170: "פסטה, איטריות וקוסקוס",
    180180: "קקאו, שוקולד וממתקים",
    180190: "מזון מוכן",
    180195: "מזון לבעלי חיים",
    190310: "יינות",
    180240: "בירה ולתת",
    180250: "משקאות קלים ומים מינרליים",
    180520: "עיסת עץ, נייר וקרטון",
    180523: "קרטון גלי ומכלי נייר",
    180630: "כימיקלים בסיסיים",
    180640: "דשנים",
    180650: "חומרי גלם פלסטיים ופטרוכימיה",
    180670: "צבעים ולכות",
    180690: "סבון, חומרי ניקוי ותמרוקים",
    180730: "לוחות וצינורות מפלסטיק",
    180740: "שרוולים ויריעות מפלסטיק",
    180750: "מכלים ובקבוקים מפלסטיק",
    180820: "זכוכית ומוצריה",
    180845: "צמנט, סיד וטיח",
    180855: "מוצרי בטון",
    180860: "עיבוד אבן",
    180865: "בטון מוכן ובלוקים",
    180890: "ברזל ופלדה",
    180900: "מתכות אל-ברזליות",
    180950: "שלדי מתכת",
    181157: "רכיבים ולוחות אלקטרוניים",
    181160: "ציוד תקשורת",
    181225: "מכשירי מדידה וניווט",
    181230: "מכשור רפואי",
    181120: "כבלים וחיווט",
    181133: "ציוד תאורה",
    181137: "מכשירי חשמל ביתיים",
    181050: "מכונות לחקלאות",
    181470: "כלי רכב ונגררים",
    181480: "חלקי חילוף לרכב",
    181540: "רהיטים",
    181560: "תכשיטים",
}

_CLASS_PREFIX = re.compile(r"^[A-Z](?:,[A-Z])*\s+")


def _label(code, name):
    if code in SHORT:
        return SHORT[code]
    s = _CLASS_PREFIX.sub("", " ".join(str(name).split()))
    return s.removeprefix("ייצור ")


def _base_label(desc):
    m = re.fullmatch(r"\s*(\d{4})\s*ממוצע\s*", str(desc))
    return f"ממוצע {m.group(1)} = 100" if m else f"{str(desc).strip()} = 100"


def _sp(v, digits=1):
    """A published percent (0-100 scale) with its sign: 0.8 → '+0.8%'."""
    return fmt.signed_pct(float(v) / 100, digits)


def _isp(v, digits=1):
    """_sp isolated for a Hebrew sentence, so bidi keeps the sign before the number."""
    return fmt.isolate(_sp(v, digits))


def _iss(fraction):
    """fmt.signed_pct isolated for a Hebrew sentence."""
    return fmt.isolate(fmt.signed_pct(fraction))


def _p(v, digits=1):
    """Unsigned percent with U+2212 for negatives (for chart tables)."""
    s = f"{float(v):.{digits}f}"
    if float(s) == 0:
        s = f"{0:.{digits}f}"
    return s.replace("-", fmt.MINUS) + "%"


def _ym(t):
    return t.strftime("%Y-%m")


def _short_month(t):
    return f"{fmt.MONTHS_SHORT_HE[t.month - 1]} {t.year}"


def _r(v, digits=2):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), digits)


def _months_between(a, b):
    return (b.year - a.year) * 12 + b.month - a.month


# ── data ──────────────────────────────────────────────────────────────────


def _prepare(df):
    df = df[df["FREQ"].str.strip() == "M"].copy()
    df["code"] = pd.to_numeric(df["CODE"].str.strip(), errors="coerce")
    df["t"] = pd.to_datetime(df["DATE"].str.strip(), errors="coerce", format="%Y-%m-%d")
    df["v"] = pd.to_numeric(df["VALUE_CHAINED"].str.strip(), errors="coerce")
    df["p"] = pd.to_numeric(df["PERCENT"].str.strip(), errors="coerce")
    df["py"] = pd.to_numeric(df["PERCENT_YEAR"].str.strip(), errors="coerce")
    df = df.dropna(subset=["code", "t", "v"])
    df["code"] = df["code"].astype(int)
    df = df.sort_values(["code", "t", "v", "p", "py", "NAME_HE", "CHAIN_BASE"], kind="stable")
    return df.drop_duplicates(["code", "t"], keep="last")


def _series(frames):
    """code → {"name", "label", "base", "s": DataFrame(v, p, py) by month, "src"}."""
    out = {}
    for src in ("long", "branches", "subbranches"):
        df = _prepare(frames[src])
        for code, g in df.groupby("code", sort=True):
            if code in out:
                continue
            g = g.set_index("t").sort_index()
            name = g["NAME_HE"].iloc[-1]
            out[int(code)] = {"name": name, "label": _label(int(code), name),
                              "base": str(g["CHAIN_BASE"].iloc[-1]).strip(),
                              "s": g[["v", "p", "py"]], "src": src}
    return out


def _at(entry, t, col):
    s = entry["s"]
    if t not in s.index:
        return None
    v = s.at[t, col]
    return None if pd.isna(v) else float(v)


# ── insights ──────────────────────────────────────────────────────────────


def insight_latest(head, xf, latest):
    p, py = _at(head, latest, "p"), _at(head, latest, "py")
    if p is None or py is None:
        return None
    if abs(p) < 0.05:
        move = "לא השתנה לעומת החודש הקודם"
    else:
        move = f"{'עלה' if p > 0 else 'ירד'} ב-{fmt.pct_of(abs(p))} לעומת החודש הקודם"
    tail = ""
    xpy = _at(xf, latest, "py") if xf else None
    if xpy is not None:
        tail = f" ללא דלקים: {_isp(xpy)} בשנה."
    return (f"ב{fmt.month_he(latest)} מדד מחירי תפוקת התעשייה {move}, "
            f"ושיעור השינוי ב-12 החודשים האחרונים הוא {_isp(py)}.{tail}")


def insight_fuel(head, xf, refined, latest):
    if not xf:
        return None
    a, b = _at(head, latest, "py"), _at(xf, latest, "py")
    if a is None or b is None or abs(a - b) < FUEL_GAP_PP:
        return None
    way = "דוחפים את המדד הכללי כלפי מעלה" if a > b else "מושכים את המדד הכללי כלפי מטה"
    ref = _at(refined, latest, "py") if refined else None
    tail = (f" שיעור השינוי במחירי מוצרי הנפט המזוקק: {_isp(ref)} בשנה."
            if ref is not None else "")
    return (f"הדלקים {way}: שיעור השינוי ב-12 החודשים האחרונים הוא {_isp(a)} במדד הכללי, "
            f"לעומת {_isp(b)} ללא דלקים, פער של {abs(a - b):.1f} נקודות אחוז.{tail}")


def insight_branches(rank):
    if len(rank) < 5:
        return None
    up = sum(1 for r in rank if r["py"] > 0)
    down = sum(1 for r in rank if r["py"] < 0)
    top, low = rank[0], rank[-1]
    if top["py"] <= 0 or low["py"] >= 0:
        return None
    return (f"ב-12 החודשים האחרונים עלו המחירים ב-{up:,} מתוך {len(rank):,} ענפי התעשייה "
            f"וירדו ב-{down:,}. העלייה החדה ביותר: {top['label']} ({_isp(top['py'])}); "
            f"הירידה החדה ביותר: {low['label']} ({_isp(low['py'])}).")


def insight_subs(subs, min_abs=5.0):
    if len(subs) < 6:
        return None
    top, low = subs[0], subs[-1]
    parts = []
    if top["py"] >= min_abs:
        parts.append(f"{top['label']} התייקרו ב-{fmt.pct_of(top['py'])}")
    if low["py"] <= -min_abs:
        parts.append(f"{low['label']} הוזלו ב-{fmt.pct_of(abs(low['py']))}")
    if not parts:
        return None
    return f"בין ענפי המשנה, ב-12 החודשים האחרונים: {fmt.join_he(parts)}."


def insight_long(long_e, latest_long):
    s = long_e["s"]["v"].dropna()
    if len(s) < 60:
        return None
    t0, t1 = s.index[0], s.index[-1]
    years = _months_between(t0, t1) / 12
    ratio = float(s.iloc[-1]) / float(s.iloc[0])
    if years < 5 or ratio <= 0:
        return None
    cagr = ratio ** (1 / years) - 1
    py = long_e["s"]["py"].dropna()
    peak = ""
    if not py.empty:
        pt = py.idxmax()
        peak = (f" שיעור השינוי השנתי הגבוה ביותר: {_isp(py.max())} ב{fmt.month_he(pt)}.")
    return (f"מ{fmt.month_he(t0)} עד {fmt.month_he(t1)} עלו מחירי היצרן בתעשייה ובכרייה "
            f"פי {ratio:.2f}, כ-{fmt.pct(cagr)} בממוצע לשנה.{peak}")


def insight_streak(head, latest):
    p = head["s"]["p"].dropna()
    p = p[p.index <= latest]
    if p.empty or abs(p.iloc[-1]) < 0.05:
        return None
    sign = 1 if p.iloc[-1] > 0 else -1
    n = 0
    for v in reversed(p.tolist()):
        if v * sign > 0:
            n += 1
        else:
            break
    if n < STREAK_MIN:
        return None
    word = "עליות" if sign > 0 else "ירידות"
    start = p.index[-n]
    v = head["s"]["v"]
    t_before = p.index[-n - 1] if len(p) > n else None
    if t_before is None or pd.isna(v.get(t_before)) or pd.isna(v.get(latest)):
        return None
    total = float(v[latest]) / float(v[t_before]) - 1
    return (f"{n:,} חודשים רצופים של {word} במדד מחירי תפוקת התעשייה, "
            f"מאז {fmt.month_he(start)}: {_iss(total)} במצטבר.")


def insight_cumulative(mult, start):
    if len(mult) < 5:
        return None
    top, low = mult[0], mult[-1]
    if top["chg"] <= 0:
        return None
    return (f"מאז {fmt.month_he(start)} התייקרו בעיקר {top['label']} "
            f"({_iss(top['chg'])}), ואילו {low['label']} "
            + ("הוזלו" if low["chg"] < 0 else "עלו הכי מעט")
            + f" ({_iss(low['chg'])}).")


def insight_volatility(vol, head_std, months):
    if len(vol) < 5 or head_std is None:
        return None
    top, low = vol[0], vol[-1]
    if top["std"] < 2 * head_std:
        return None
    return (f"הענף התנודתי ביותר ב-{months:,} החודשים האחרונים: {top['label']}, "
            f"עם סטיית תקן של {top['std']:.1f} נקודות אחוז בשינוי החודשי, לעומת "
            f"{head_std:.1f} במדד הכללי ו-{low['std']:.1f} בלבד ב{low['label']}.")


def insight_peak(head, latest):
    s = head["s"]["v"].dropna()
    s = s[s.index <= latest]
    if len(s) < 24:
        return None
    cur, mx = float(s.iloc[-1]), float(s.max())
    mt = s.idxmax()
    if mt == s.index[-1]:
        return (f"מדד מחירי תפוקת התעשייה ב{fmt.month_he(latest)} הוא הגבוה ביותר "
                f"מאז תחילת הסדרה ב-{s.index[0].year}.")
    gap = cur / mx - 1
    if gap > -0.01:
        return None
    return (f"המדד נמצא {fmt.pct(abs(gap))} מתחת לשיא שלו מ{fmt.month_he(mt)}.")


# ── compute ───────────────────────────────────────────────────────────────


def compute(frames):
    S = _series(frames)
    if HEAD not in S:
        raise ValueError("no rows for the headline code 170030")
    head = S[HEAD]
    latest = head["s"].index.max()
    base = head["base"]
    base_txt = _base_label(base)
    xf = S.get(HEAD_XF)
    if xf is not None and xf["s"].index.max() != latest:
        xf = None
    refined = S.get(REFINED) if S.get(REFINED) and S[REFINED]["s"].index.max() == latest else None
    long_e = S.get(LONG)
    long_xf = S.get(LONG_XF)
    m_txt = fmt.month_he(latest)

    def current(code):
        return code in S and S[code]["s"].index.max() == latest

    branch_codes = sorted(c for c, e in S.items() if e["src"] == "branches"
                          and c not in AGGREGATES and c not in MINING_PARTS)
    sub_codes = sorted(c for c, e in S.items() if e["src"] == "subbranches")
    behind = [c for c in branch_codes + sub_codes + sorted(MINING_PARTS & set(S))
              if not current(c)]
    stale = [c for c in behind if _months_between(S[c]["s"].index.max(), latest) >= STALE_MONTHS]
    lagging = [c for c in behind if c not in stale]
    branch_codes = [c for c in branch_codes if current(c)]
    sub_codes = [c for c in sub_codes if current(c)]

    # ranking by the published 12-month change at the latest month
    def rank_rows(codes):
        rows = []
        for c in codes:
            py = _at(S[c], latest, "py")
            if py is None:
                continue
            rows.append({"code": c, "label": S[c]["label"], "py": py,
                         "p": _at(S[c], latest, "p"), "v": _at(S[c], latest, "v")})
        return sorted(rows, key=lambda r: (-r["py"], r["code"]))

    rank = rank_rows(branch_codes)
    subs = rank_rows(sub_codes)

    # KPIs
    h_v, h_p, h_py = _at(head, latest, "v"), _at(head, latest, "p"), _at(head, latest, "py")
    kpis = {"level": {"value": _r(h_v, 1), "display": fmt.num_he(h_v, 1), "tone": "brand"}}
    if h_p is not None:
        kpis["mm"] = {"value": h_p, "display": _sp(h_p),
                      "tone": "warn" if h_p >= 0.5 else "info" if h_p <= -0.5 else "brand"}
    if h_py is not None:
        kpis["yy"] = {"value": h_py, "display": _sp(h_py),
                      "tone": "warn" if h_py > 3 else "info" if h_py < 0 else "brand"}
    x_py = _at(xf, latest, "py") if xf else None
    if x_py is not None:
        kpis["xf"] = {"value": x_py, "display": _sp(x_py),
                      "tone": "warn" if x_py > 3 else "info" if x_py < 0 else "brand"}
    if rank:
        up = sum(1 for r in rank if r["py"] > 0)
        kpis["up"] = {"value": up, "display": f"{up:,}", "tone": "brand"}

    charts, tables, flags, labels = {}, {}, {}, {}

    # 1. the long run (chained levels) since 1995
    if long_e is not None:
        lv = long_e["s"]["v"]
        idx = lv.index
        if long_xf is not None:
            idx = idx.union(long_xf["s"].index)
        idx = idx.union(head["s"].index).sort_values()

        def on(entry):
            if entry is None:
                return [None] * len(idx)
            s = entry["s"]["v"].reindex(idx)
            return [_r(v, 2) for v in s.tolist()]

        charts["long"] = {"x": [_ym(t) for t in idx], "all": on(long_e), "xf": on(long_xf),
                          "head": on(head),
                          "names": [long_e["label"], long_xf["label"] if long_xf else "",
                                    head["label"]]}
        yearly = lv.groupby(lv.index.year).agg(["mean", "count"])
        xfy = long_xf["s"]["v"].groupby(long_xf["s"]["v"].index.year).mean() if long_xf else None
        rows, prev = [], None
        for y, r in yearly.iterrows():
            full = int(r["count"]) == 12
            chg = (r["mean"] / prev - 1) if prev is not None and full else None
            rows.append([f"{y}" + ("" if full else f" (עד {fmt.MONTHS_HE[lv[lv.index.year == y].index.max().month - 1]})"),
                         fmt.num_he(r["mean"], 1),
                         fmt.signed_pct(chg) if chg is not None else "–",
                         fmt.num_he(xfy[y], 1) if xfy is not None and y in xfy.index else "–"])
            prev = r["mean"] if full else prev
        tables["long"] = rows[::-1]
        y0, y1 = idx[0].year, idx[-1].year
        labels["long_note"] = (
            f"רמת המדד בכל חודש מ-{y0}, משורשרת לבסיס אחד ({_base_label(long_e['base'])}) לפי מקדמי "
            f"השרשור של הלמ\"ס. הסדרה הארוכה כוללת גם כרייה וחציבה; מדד {head['label']} (סיווג 2011) "
            f"מתפרסם מ-{head['s'].index.min().year}. אפשר לגרור את פס הזמן כדי להתמקד בתקופה.")
        labels["long_aria"] = (
            f"גרף קווי: מדד מחירי יצרן מ-{y0} עד {y1}, {base_txt}. "
            f"ב{m_txt}: {fmt.num_he(h_v, 1)} בתעשייה.")
        labels["long_caption"] = f"ממוצע שנתי של מדד מחירי היצרן ושינוי שנתי, {y0} עד {y1}"
        flags["long"] = True

    # 2. 12-month change, general vs without fuels, since the series start
    yy_src = [(long_e, "all"), (long_xf, "xf")]
    if long_e is not None:
        py = long_e["s"]["py"].dropna()
        idx = py.index
        if long_xf is not None:
            idx = idx.union(long_xf["s"]["py"].dropna().index)
        idx = idx.sort_values()
        charts["yy"] = {"x": [_ym(t) for t in idx]}
        for e, k in yy_src:
            charts["yy"][k] = ([_r(v, 1) for v in e["s"]["py"].reindex(idx).tolist()]
                               if e is not None else [None] * len(idx))
        charts["yy"]["names"] = [long_e["label"], long_xf["label"] if long_xf else ""]
        rows = []
        for t in idx:
            if t.month == 12 or t == idx[-1]:
                a = _at(long_e, t, "py")
                b = _at(long_xf, t, "py") if long_xf else None
                rows.append([f"{fmt.MONTHS_HE[t.month - 1]} {t.year}",
                             _p(a) if a is not None else "–", _p(b) if b is not None else "–"])
        tables["yy"] = rows[::-1]
        hi = py.idxmax()
        lo = py.idxmin()
        labels["yy_note"] = (
            f"שיעור השינוי של המדד לעומת אותו חודש בשנה הקודמת, כפי שפרסמה הלמ\"ס. "
            f"הפער בין שני הקווים הוא השפעת מחירי הדלקים. הגבוה ביותר: {_isp(py.max())} "
            f"({fmt.month_he(hi)}); הנמוך ביותר: {_isp(py.min())} ({fmt.month_he(lo)}).")
        labels["yy_aria"] = (
            f"גרף קווי: שיעור השינוי השנתי במדד מחירי יצרן, כולל דלקים וללא דלקים, "
            f"מ-{idx[0].year} עד {idx[-1].year}. שיא {_sp(py.max())} ב{fmt.month_he(hi)}.")
        labels["yy_caption"] = "שיעור השינוי ב-12 חודשים, בדצמבר של כל שנה ובחודש האחרון"
        flags["yy"] = True

    # 3. monthly changes, last 24 months, headline vs without fuels
    hp = head["s"]["p"].dropna()
    recent = hp.index[-RECENT_MONTHS:]
    charts["mm"] = {"x": [_short_month(t) for t in recent],
                    "head": [_r(_at(head, t, "p"), 1) for t in recent],
                    "xf": [_r(_at(xf, t, "p"), 1) if xf else None for t in recent],
                    "names": [head["label"], xf["label"] if xf else ""]}
    tables["mm"] = [[fmt.month_he(t),
                     _p(_at(head, t, "p")),
                     _p(_at(xf, t, "p")) if xf and _at(xf, t, "p") is not None else "–",
                     _p(_at(head, t, "py")) if _at(head, t, "py") is not None else "–"]
                    for t in reversed(recent)]
    rp = hp.loc[recent]
    n_up = int((rp > 0).sum())
    labels["mm_note"] = (
        f"השינוי מחודש לחודש ב-{len(recent):,} החודשים האחרונים, כפי שפורסם. "
        f"המדד עלה ב-{n_up:,} מהם וירד או לא השתנה ב-{len(recent) - n_up:,}.")
    labels["mm_aria"] = (
        f"תרשים עמודות: השינוי החודשי במדד מחירי תפוקת התעשייה, {fmt.month_he(recent[0])} "
        f"עד {m_txt}. בחודש האחרון {_sp(h_p) if h_p is not None else '–'}.")
    labels["mm_caption"] = f"שינוי חודשי ושנתי במדד, {len(recent):,} החודשים האחרונים"

    # 4. branches ranked by 12-month change
    if rank:
        charts["rank"] = {"series_name": "שינוי ב-12 חודשים", "names": [r["label"] for r in rank], "y": [_r(r["py"], 1) for r in rank],
                          "head": _r(h_py, 1), "head_name": head["label"]}
        tables["rank"] = [[r["label"], _p(r["py"]),
                           _p(r["p"]) if r["p"] is not None else "–",
                           fmt.num_he(r["v"], 1) if r["v"] is not None else "–"] for r in rank]
        labels["rank_note"] = (
            f"השינוי במחירי כל ענף ראשי ב-12 החודשים עד {m_txt}, כפי שפורסם. "
            f"הקו המקווקו: {head['label']} ({_isp(h_py) if h_py is not None else '–'}).")
        labels["rank_aria"] = (
            f"תרשים עמודות אופקי: {len(rank):,} ענפי התעשייה לפי שינוי המחירים ב-12 חודשים. "
            f"בראש {rank[0]['label']} ({_sp(rank[0]['py'])}), בתחתית {rank[-1]['label']} "
            f"({_sp(rank[-1]['py'])}).")
        labels["rank_caption"] = f"ענפי התעשייה לפי שינוי המחירים ב-12 החודשים עד {m_txt}"
        labels["rank_level_col"] = f"רמת המדד ({base_txt})"
        flags["rank"] = True

    # 5./6. rebased views from a common start
    firsts = {c: S[c]["s"]["v"].dropna().index.min() for c in branch_codes}
    mult, start = [], None
    if firsts:
        t_min = min(firsts.values())
        in_view = [c for c in branch_codes if _months_between(t_min, firsts[c]) <= LATE_START_MONTHS]
        late = len(branch_codes) - len(in_view)
        start = max(firsts[c] for c in in_view)
        months = head["s"].index[(head["s"].index >= start) & (head["s"].index <= latest)]
        keep = list(months)
        keep_small = list(months[::-1][::SMALL_STEP][::-1])
        if keep_small and keep_small[0] != start:
            keep_small.insert(0, start)
        for c in in_view:
            s = S[c]["s"]["v"]
            if start not in s.index or pd.isna(s.at[start]):
                continue
            reb = s.reindex(keep_small) / float(s.at[start]) * 100
            chg = float(s.at[latest]) / float(s.at[start]) - 1
            mult.append({"code": c, "label": S[c]["label"], "chg": chg,
                         "data": [_r(v, 1) for v in reb.tolist()]})
        mult.sort(key=lambda m: (-m["chg"], m["code"]))
        if mult:
            py_of = {r["code"]: r["py"] for r in rank}
            charts["small"] = {"x": [_ym(t) for t in keep_small],
                               "items": [{"name": m["label"], "chg": fmt.signed_pct(m["chg"]),
                                          "data": m["data"]} for m in mult]}
            tables["small"] = [[m["label"], fmt.num_he(100 + m["chg"] * 100, 1),
                                fmt.signed_pct(m["chg"]),
                                _sp(py_of[m["code"]]) if m["code"] in py_of else "–"]
                               for m in mult]
            labels["small_note"] = (
                f"כל ענף מוצג ביחס לרמתו ב{fmt.month_he(start)} (= 100), כך שאפשר להשוות ענפים "
                f"מאותה נקודת פתיחה. הענפים ממוינים לפי השינוי המצטבר, מהגבוה לנמוך; "
                f"הקו המקווקו הוא נקודת הפתיחה."
                + (f" {late:,} ענפים שהחלו להתפרסם מאוחר יותר אינם מוצגים." if late else ""))
            labels["small_caption"] = (f"השינוי המצטבר במחירי כל ענף מאז {fmt.month_he(start)} "
                                       f"ועד {m_txt}")
            labels["small_start_col"] = f"רמה ב{_short_month(latest)} ({_short_month(start)} = 100)"
            labels["small_aria"] = [
                f"גרף קווי קטן: {m['label']}, שינוי מצטבר {fmt.signed_pct(m['chg'])} "
                f"מאז {fmt.month_he(start)}." for m in mult]
            flags["small"] = True

        # fuels vs the rest
        if start is not None and xf is not None and refined is not None:
            series = [(head, "head"), (xf, "xf"), (refined, "ref")]
            og = S.get(OIL_GAS) if current(OIL_GAS) else None
            if og is not None:
                series.append((og, "og"))
            fuel = {"x": [_ym(t) for t in keep], "names": {}}
            for e, k in series:
                s = e["s"]["v"]
                if start in s.index:
                    fuel[k] = [_r(v, 1) for v in
                               (s.reindex(keep) / float(s.at[start]) * 100).tolist()]
                    fuel["names"][k] = e["label"]
            if all(k in fuel for k in ("head", "xf", "ref")):
                charts["fuel"] = fuel
                rows = []
                for y in sorted({t.year for t in months}, reverse=True):
                    t = max(t for t in months if t.year == y)
                    rows.append([f"{fmt.MONTHS_HE[t.month - 1]} {y}"]
                                + [(_p(_at(e, t, "py")) if _at(e, t, "py") is not None else "–")
                                   for e, _ in series[:3]])
                tables["fuel"] = rows
                rstd = refined["s"]["p"][refined["s"].index >= start].std()
                xstd = xf["s"]["p"][xf["s"].index >= start].std()
                ratio = rstd / xstd if xstd and xstd > 0 else None
                labels["fuel_note"] = (
                    f"המדד הכללי, המדד ללא דלקים ומחירי מוצרי הנפט המזוקק, ביחס לרמתם "
                    f"ב{fmt.month_he(start)} (= 100)."
                    + (f" השינוי החודשי במחירי מוצרי הנפט המזוקק תנודתי פי {ratio:.0f} מזה של "
                       f"המדד ללא דלקים (לפי סטיית התקן), ולכן הדלקים מסבירים חלק גדול "
                       f"מהתנודות במדד הכללי." if ratio is not None and ratio >= 2 else ""))
                labels["fuel_aria"] = (
                    f"גרף קווי: מדד מחירי יצרן כולל דלקים, ללא דלקים ומוצרי נפט מזוקק מאז "
                    f"{fmt.month_he(start)}. ב{m_txt}: {refined['label']} "
                    f"{fmt.num_he(fuel['ref'][-1], 1)}, ללא דלקים {fmt.num_he(fuel['xf'][-1], 1)}.")
                labels["fuel_caption"] = "שיעור השינוי ב-12 חודשים: כללי, ללא דלקים ומוצרי נפט מזוקק"
                labels["fuel_cols"] = ["חודש", head["label"], xf["label"], refined["label"]]
                flags["fuel"] = True

    # 7. heatmap of monthly changes, last 13 months × branches
    if rank:
        hm = head["s"].index[head["s"].index <= latest][-HEAT_MONTHS:]
        names = [r["label"] for r in rank]
        cells, vals = [], []
        for yi, r in enumerate(rank):
            for xi, t in enumerate(hm):
                v = _at(S[r["code"]], t, "p")
                if v is not None:
                    cells.append([xi, yi, _r(v, 1)])
                    vals.append(abs(v))
        if cells:
            cap = float(pd.Series(vals).quantile(0.95))
            cap = max(1.0, math.ceil(cap))
            charts["heat"] = {"x": [_short_month(t) for t in hm], "y": names, "cells": cells,
                              "cap": cap}
            grid = {(c[1], c[0]): c[2] for c in cells}
            tables["heat"] = [[names[yi]] + [_p(grid[(yi, xi)]) if (yi, xi) in grid else "–"
                                             for xi in range(len(hm))]
                              for yi in range(len(names))]
            labels["heat_cols"] = ["ענף"] + [_short_month(t) for t in hm]
            n_over = sum(1 for v in vals if v > cap)
            labels["heat_note"] = (
                f"השינוי החודשי במחירי כל ענף ב-{len(hm):,} החודשים האחרונים. כחול: ירידה, "
                f"אדום: עלייה. סולם הצבעים נעצר ב-{cap:.0f}% לכל כיוון"
                + (f" ({n_over:,} תאים חורגים ממנו וצבועים בגוון הקיצוני)." if n_over else ".")
                + " המספר בכל תא הוא השינוי שפורסם.")
            labels["heat_aria"] = (
                f"מפת חום: השינוי החודשי במחירי {len(names):,} ענפי התעשייה, "
                f"{fmt.month_he(hm[0])} עד {m_txt}.")
            labels["heat_caption"] = f"השינוי החודשי לפי ענף, {fmt.month_he(hm[0])} עד {m_txt}"
            flags["heat"] = True

    # 8. volatility: std of the monthly change over the last 60 months
    vol = []
    w0 = latest - pd.DateOffset(months=VOL_MONTHS - 1)
    for c in branch_codes:
        p = S[c]["s"]["p"]
        p = p[(p.index >= w0) & (p.index <= latest)].dropna()
        if len(p) >= 12:
            vol.append({"code": c, "label": S[c]["label"], "std": float(p.std()),
                        "max": float(p.max()), "tmax": p.idxmax(),
                        "min": float(p.min()), "tmin": p.idxmin()})
    vol.sort(key=lambda r: (-r["std"], r["code"]))
    hpw = hp[(hp.index >= w0) & (hp.index <= latest)]
    head_std = float(hpw.std()) if len(hpw) >= 12 else None
    vol_months = len(hpw)
    if vol:
        charts["vol"] = {"names": [v["label"] for v in vol], "y": [_r(v["std"], 2) for v in vol],
                         "head": _r(head_std, 2)}
        tables["vol"] = [[v["label"], f"{v['std']:.2f}",
                          f"{_sp(v['max'])} ({_short_month(v['tmax'])})",
                          f"{_sp(v['min'])} ({_short_month(v['tmin'])})"] for v in vol]
        labels["vol_note"] = (
            f"סטיית התקן של השינוי החודשי בכל ענף, ב-{vol_months:,} החודשים האחרונים "
            f"(מ{fmt.month_he(w0)}). ככל שהעמודה ארוכה יותר, המחירים בענף קופצים יותר מחודש לחודש."
            + (f" הקו המקווקו: {head['label']} ({head_std:.2f})." if head_std is not None else ""))
        labels["vol_aria"] = (
            f"תרשים עמודות אופקי: תנודתיות המחירים לפי ענף. התנודתי ביותר {vol[0]['label']} "
            f"({vol[0]['std']:.1f}), היציב ביותר {vol[-1]['label']} ({vol[-1]['std']:.1f}).")
        labels["vol_caption"] = "סטיית התקן של השינוי החודשי לפי ענף, והשינוי החודשי הקיצוני"
        labels["head_name"] = head["label"]
        flags["vol"] = True

    # 9. sub-industries: the largest rises and falls
    if len(subs) >= 4:
        side = min(SUB_SIDE, len(subs) // 2)
        pick = subs[:side] + subs[-side:]
        charts["subs"] = {"series_name": "שינוי ב-12 חודשים", "names": [r["label"] for r in pick], "y": [_r(r["py"], 1) for r in pick]}
        tables["subs"] = [[r["label"], _p(r["py"]),
                           _p(r["p"]) if r["p"] is not None else "–"] for r in pick]
        labels["subs_note"] = (
            f"{side:,} ענפי המשנה עם השינוי הגבוה ביותר ו-{side:,} עם השינוי הנמוך ביותר ב-12 "
            f"החודשים עד {m_txt}, מתוך {len(subs):,} ענפי משנה נבחרים.")
        labels["subs_aria"] = (
            f"תרשים עמודות אופקי: ענפי המשנה עם השינוי הגדול ביותר במחירים ב-12 חודשים. "
            f"בראש {pick[0]['label']} ({_sp(pick[0]['py'])}), בתחתית {pick[-1]['label']} "
            f"({_sp(pick[-1]['py'])}).")
        labels["subs_caption"] = f"ענפי המשנה עם השינוי הגדול ביותר במחירים ב-12 החודשים עד {m_txt}"
        flags["subs"] = True

    rules = [
        ("latest", insight_latest(head, xf, latest)),
        ("fuel", insight_fuel(head, xf, refined, latest)),
        ("branches", insight_branches(rank)),
        ("subs", insight_subs(subs)),
        ("streak", insight_streak(head, latest)),
        ("peak", insight_peak(head, latest)),
        ("cumulative", insight_cumulative(mult, start) if start is not None else None),
        ("volatility", insight_volatility(vol, head_std, vol_months)),
        ("long", insight_long(long_e, latest) if long_e is not None else None),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    t_first = long_e["s"].index.min() if long_e is not None else head["s"].index.min()
    lede = (
        f"מדד מחירי יצרן (מדד המחירים הסיטוניים של תפוקת התעשייה ליעדים מקומיים) מודד את "
        f"המחירים שמקבלים היצרנים בישראל על מה שהם מוכרים בשוק המקומי. "
        f"הנתון האחרון הוא ל{m_txt}: המדד "
        + (f"השתנה בשיעור של {_isp(h_p)} בחודש ושל {_isp(h_py)} ב-12 חודשים" if h_p is not None and h_py is not None
           else f"עומד על {fmt.num_he(h_v, 1)}")
        + f". בעמוד: {len(rank):,} ענפים ראשיים ו-{len(subs):,} ענפי משנה, ונתונים מ-{t_first.year}. "
        f"מקור הנתונים: הלשכה המרכזית לסטטיסטיקה, מאגר המדדים.")
    summary = (
        f"מדד מחירי יצרן (המחירים הסיטוניים בתעשייה) ל{m_txt}"
        + (f": {_sp(h_p)} בחודש, {_sp(h_py)} בשנה" if h_p is not None and h_py is not None else "")
        + (f", ללא דלקים {_sp(x_py)}" if x_py is not None else "")
        + f". שינוי המחירים בכל ענף, דלקים מול שאר התעשייה ונתונים מ-{t_first.year}.")
    desc = (
        f"מדד מחירי יצרן (מדד המחירים הסיטוניים) לתפוקת התעשייה ב{m_txt}"
        + (f": {_sp(h_p)} בחודש, {_sp(h_py)} ב-12 חודשים" if h_p is not None and h_py is not None else "")
        + ". השינוי בכל ענף ומשקל הדלקים.")

    labels.update({
        "lede": lede,
        "level_kpi": f"מדד מחירי תפוקת התעשייה, {m_txt} ({base_txt})",
        "mm_kpi": f"שינוי לעומת החודש הקודם ({m_txt})",
        "yy_kpi": f"שינוי ב-12 חודשים ({m_txt})",
        "xf_kpi": "שינוי ב-12 חודשים, התעשייה ללא דלקים",
        "up_kpi": f"ענפים שהתייקרו ב-12 חודשים, מתוך {len(rank):,}",
        "base_txt": base_txt,
        "col_12m": "שינוי ב-12 חודשים",
        "rank_title": "שינוי המחירים לפי ענף ב-12 החודשים האחרונים",
        "about": [
            ("המדד משקף את המחירים שמקבל היצרן על תפוקה שנמכרת בשוק המקומי, ולא את המחיר לצרכן. "
             "מחירי יצרן נחשבים אינדיקציה מוקדמת ללחצי מחירים שעשויים לעבור בהמשך לצרכנים."),
            (f"רמות המדד בעמוד משורשרות לבסיס אחד ({base_txt}) לפי מקדמי השרשור הרשמיים של הלמ\"ס, "
             "כי הלמ\"ס מחליפה את בסיס המדד מדי כמה שנים. שיעורי השינוי החודשיים והשנתיים הם "
             "כפי שפורסמו (מעוגלים לעשירית האחוז), ולכן חישוב מחדש מהרמות עשוי להיות שונה בעשירית."),
            (f"הנתון הראשי הוא מדד מחירי תפוקת התעשייה (ללא כרייה וחציבה), במתכונת הסיווג האחיד "
             f"של ענפי הכלכלה 2011, שמתפרסם מ-{head['s'].index.min().year}. לתקופה הארוכה העמוד "
             f"משתמש במדד התעשייה וכרייה וחציבה, שמתפרסם מ-{t_first.year}."),
            ("המדדים לפי סיווג הענפים הישן (1993) לא נכללו: הסיווג הוחלף בסיווג 2011, "
             "והעמוד משווה ענפים רק לפי הסיווג החדש."),
            ("המדד מתפרסם בדרך כלל באמצע החודש שאחרי חודש הנתונים. נתוני החודשים האחרונים עשויים "
             "להתעדכן, והעמוד מציג תמיד את הגרסה האחרונה."),
        ] + ([("ענף נבחר אחד הפסיק להתפרסם ואינו מוצג בהשוואות." if len(stale) == 1 else
               f"{len(stale):,} מהענפים הנבחרים הפסיקו להתפרסם ואינם מוצגים בהשוואות.")]
             if stale else [])
          + ([(f"עוד לא פורסמו נתונים ל{m_txt} עבור "
              f"{fmt.join_he(S[c]['label'] for c in lagging)}, ולכן הם אינם בהשוואות של החודש.")]
             if lagging else []),
    })

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{_ym(t_first)}/{_ym(latest)}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד מחירי יצרן | מדד המחירים הסיטוניים בתעשייה",
                "description": desc,
                "name": "מדד מחירי יצרן",
                "alternate_names": [
                    "מדד המחירים הסיטוניים",
                    "מדד המחירים הסיטוניים של תפוקת התעשייה ליעדים מקומיים",
                    "מדד מחירי תפוקת התעשייה",
                    "מדד מחירי יצרנים",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "flags": flags,
        "insights": insights,
        "labels": labels,
    }
