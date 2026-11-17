"""מדד מחירי יצרן ליצוא: CBS's quarterly producer price index of industrial,
mining and quarrying output for export (chapter ba of the CBS Index API).

Inputs (one row per code and period):
  branches     195010 the headline (industry + mining & quarrying, for export)
               and the 15 main grouped branches of the 2011 classification
               (subject 163), quarterly.
  subbranches  16 chosen grouped sub-branches (subject 120), quarterly.
  domestic     CBS's producer price index for domestic destinations (chapter b)
               for the headline (170010) and the matching branches, monthly.
               Turned into quarterly averages of complete quarters here, so the
               page can set export prices against domestic ones.

Levels are VALUE_CHAINED (one base per code, CHAIN_BASE). The export index's
quarterly and yearly changes are CBS's published PERCENT / PERCENT_YEAR. The
domestic side's quarterly changes are computed here from the quarterly
averages (CBS publishes monthly changes only), and the page says so.
"Latest" is the newest quarter of the headline code; a code that stops before
it is left out of the comparisons, and the page says how many were.
"""
import re

import pandas as pd
from govlib import fmt

HEAD = 195010
DOM_HEAD = 170010
QN = ("הראשון", "השני", "השלישי", "הרביעי")
HEAT_Q = 12            # heatmap columns (quarters)
YY_TABLE_Q = 20        # rows of the yearly-change table
QQ_Q = 16              # quarterly-change bars
GAP_PP = 1.0           # export vs domestic gap worth a sentence
# The domestic index includes VAT, which rose from 17% to 18% in January 2025:
# every domestic year-on-year change of a 2025 quarter is partly the tax.
VAT_YEAR = 2025
VAT_NOTE = ("מדד מחירי היצרן לשוק המקומי כולל מע\"מ, ושיעור המע\"מ עלה מ-17% ל-18% בינואר 2025. "
            "לכן השינוי השנתי במדד המקומי ברבעונים של 2025 משקף בחלקו את העלאת המס, והפער מול "
            "מחירי היצוא באותם רבעונים גדול בחלקו בשל כך.")
VAT_CAVEAT = (" בשנת 2025 השינוי בשוק המקומי כולל בחלקו את העלאת המע\"מ מ-17% ל-18%, "
              "שאינה חלה על מחירי היצוא.")
STREAK_MIN = 3
SUB_MIN_ABS = 5.0

SHORT = {
    195010: "מדד מחירי היצוא הכללי",
    195020: "נפט מזוקק, כרייה וחציבה",
    195030: "מזון ומשקאות",
    195040: "טקסטיל",
    195080: "הלבשה",
    195090: "כימיקלים ומוצריהם",
    193270: "תרופות",
    195120: "גומי ופלסטיק",
    195200: "מוצרים ממינרלים אל-מתכתיים",
    195210: "מוצרי מתכת",
    195220: "מחשבים, אלקטרוניקה ואופטיקה",
    193470: "ציוד חשמלי",
    195290: "מכונות וציוד",
    195340: "כלי רכב מנועיים",
    195350: "כלי תחבורה אחרים",
    195360: "ענפי ייצור אחרים",
    195250: "מחשבים וציוד היקפי",
    193570: "ציוד תקשורת",
    195230: "מכשירי מדידה, ניווט ובקרה",
    195240: "מכשור אלקטרוני רפואי",
    193690: "מכשור אופטי וציוד צילום",
    193190: "כימיקלים בסיסיים",
    193210: "דשנים ותרכובות חנקן",
    193230: "חומרי גלם פלסטיים ופטרוכימיה",
    193290: "סבון, חומרי ניקוי ותמרוקים",
    193430: "צמיגים ומוצרי גומי",
    195280: "סוללות ומצברים",
    195320: "תנורים, מבערים ואנרגיה סולרית",
    195330: "מכונות ייעודיות",
    193770: "כלי טיס וציוד נלווה",
    195370: "תכשיטים ויהלומים מעובדים",
    195380: "ציוד רפואי ודנטלי",
    170010: "מחירי יצרן לשוק המקומי",
}
# export branch → the domestic branch with the same scope
PAIRS = {
    HEAD: DOM_HEAD,
    195090: 180625, 193270: 180680, 195120: 180720, 195200: 180810,
    195210: 180940, 195220: 181153, 193470: 181090, 195290: 181030,
    195340: 181460, 195350: 181500, 195360: 181550, 195370: 181560,
}

_CLASS_PREFIX = re.compile(r"^[A-Z](?:,[A-Z])*\s+")


def _label(code, name):
    if code in SHORT:
        return SHORT[code]
    s = _CLASS_PREFIX.sub("", " ".join(str(name).split()))
    return s.removeprefix("ייצור ")


def _qlong(k):
    return f"הרבעון {QN[k[1] - 1]} של {k[0]}"


def _qin(k):
    return f"ברבעון {QN[k[1] - 1]} של {k[0]}"


def _qshort(k):
    return f"ר׳{k[1]} {k[0]}"


def _qprev(k, n=1):
    i = k[0] * 4 + k[1] - 1 - n
    return (i // 4, i % 4 + 1)


def _qdiff(a, b):
    return (b[0] * 4 + b[1]) - (a[0] * 4 + a[1])


def _sp(v, digits=1):
    return fmt.signed_pct(float(v) / 100, digits)


def _isp(v, digits=1):
    return fmt.isolate(_sp(v, digits))


def _iss(fraction):
    return fmt.isolate(fmt.signed_pct(fraction))


def _p(v, digits=1):
    if v is None:
        return "–"
    s = f"{float(v):.{digits}f}"
    if float(s) == 0:
        s = f"{0:.{digits}f}"
    return s.replace("-", fmt.MINUS) + "%"


def _lv(v):
    return "–" if v is None else f"{float(v):,.1f}"


def _r(v, digits=2):
    return None if v is None or pd.isna(v) else round(float(v), digits)


def _base_year(desc):
    m = re.search(r"(\d{4})", str(desc))
    return int(m.group(1)) if m else None


# ── data ──────────────────────────────────────────────────────────────────


def _num(df, col):
    return pd.to_numeric(df[col].str.strip(), errors="coerce")


def _prepare(df, freq):
    df = df[df["FREQ"].str.strip() == freq].copy()
    df["code"] = pd.to_numeric(df["CODE"].str.strip(), errors="coerce")
    t = pd.to_datetime(df["DATE"].str.strip(), errors="coerce", format="%Y-%m-%d")
    df["y"] = t.dt.year
    df["m"] = t.dt.month
    df["v"] = _num(df, "VALUE_CHAINED")
    df["p"] = _num(df, "PERCENT")
    df["py"] = _num(df, "PERCENT_YEAR")
    df = df.dropna(subset=["code", "y", "v"])
    df["code"] = df["code"].astype(int)
    df["y"] = df["y"].astype(int)
    df["m"] = df["m"].astype(int)
    df = df.sort_values(["code", "y", "m", "v", "p", "py", "NAME_HE", "CHAIN_BASE"], kind="stable")
    return df.drop_duplicates(["code", "y", "m"], keep="last")


def _export_series(frames):
    """code → {"label", "base", "s": {(y, q): (v, p, py)}, "src"}."""
    out = {}
    for src in ("branches", "subbranches"):
        df = _prepare(frames[src], "Q")
        for code, g in df.groupby("code", sort=True):
            if code in out:
                continue
            s = {}
            for r in g.itertuples(index=False):
                s[(r.y, (r.m - 1) // 3 + 1)] = (float(r.v),
                                                None if pd.isna(r.p) else float(r.p),
                                                None if pd.isna(r.py) else float(r.py))
            out[int(code)] = {"label": _label(int(code), g["NAME_HE"].iloc[-1]),
                              "base": str(g["CHAIN_BASE"].iloc[-1]).strip(),
                              "s": dict(sorted(s.items())), "src": src}
    return out


def _domestic_series(frame):
    """code → {(y, q): mean VALUE_CHAINED} over complete quarters only."""
    df = _prepare(frame, "M")
    df["q"] = (df["m"] - 1) // 3 + 1
    out = {}
    for code, g in df.groupby("code", sort=True):
        agg = g.groupby(["y", "q"], sort=True)["v"].agg(["mean", "count"])
        out[int(code)] = {(int(y), int(q)): float(r["mean"])
                          for (y, q), r in agg.iterrows() if r["count"] == 3}
    return out


def _yy(s, k):
    a, b = s.get(k), s.get(_qprev(k, 4))
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1) * 100


def _base_mean(s, year):
    vals = [s[(year, q)] for q in range(1, 5) if (year, q) in s]
    return sum(vals) / 4 if len(vals) == 4 else None


# ── insights ──────────────────────────────────────────────────────────────


def insight_latest(head, latest):
    _, p, py = head["s"][latest]
    if p is None or py is None:
        return None
    move = ("לא השתנה לעומת הרבעון הקודם" if abs(p) < 0.05
            else f"{'עלה' if p > 0 else 'ירד'} ב-{fmt.pct_of(abs(p))} לעומת הרבעון הקודם")
    return (f"{_qin(latest)} מדד מחירי היצרן ליצוא {move}, ושיעור השינוי לעומת "
            f"הרבעון המקביל אשתקד הוא {_isp(py)}.")


def insight_streak(head, latest):
    keys = [k for k in head["s"] if k <= latest]
    vals = [head["s"][k][2] for k in keys]
    if not vals or vals[-1] is None or abs(vals[-1]) < 0.05:
        return None
    sign = 1 if vals[-1] > 0 else -1
    n = 0
    for v in reversed(vals):
        if v is not None and v * sign > 0:
            n += 1
        else:
            break
    if n < STREAK_MIN:
        return None
    start = keys[-n]
    word = "גבוה" if sign > 0 else "נמוך"
    return (f"זה הרבעון ה-{n:,} ברציפות שבו מדד מחירי היצוא {word} מזה של הרבעון המקביל "
            f"אשתקד, מאז {_qlong(start)}.")


def insight_peak(head, latest):
    s = {k: v[0] for k, v in head["s"].items() if k <= latest}
    if len(s) < 8:
        return None
    pk = max(s, key=lambda k: (s[k], k))
    if pk == latest:
        return f"{_qin(latest)} מדד מחירי היצוא ברמתו הגבוהה ביותר מאז {_qlong(min(s))}."
    drop = s[latest] / s[pk] - 1
    if drop > -0.02:
        return None
    return (f"השיא של מדד מחירי היצוא היה {_qin(pk)}. מאז ירד המדד ב-"
            f"{fmt.pct(abs(drop))} עד {_qlong(latest)}.")


def insight_domestic(e_py, d_yy, latest):
    if e_py is None or d_yy is None or abs(e_py - d_yy) < GAP_PP:
        return None
    rel = "נמוך" if e_py < d_yy else "גבוה"
    return (f"{_qin(latest)} שיעור השינוי השנתי במחירי היצוא היה {_isp(e_py)}, לעומת {_isp(d_yy)} "
            f"במחירי היצרן לשוק המקומי (ממוצע רבעוני). השינוי ביצוא {rel} ב-"
            f"{abs(e_py - d_yy):.1f} נקודות אחוז."
            + (VAT_CAVEAT if latest[0] == VAT_YEAR else ""))


def insight_pairs(pairs, latest):
    if len(pairs) < 5:
        return None
    lower = [r for r in pairs if r["e"] < r["d"]]
    higher = [r for r in pairs if r["e"] > r["d"]]
    word, group = ("נמוך", lower) if len(lower) >= len(higher) else ("גבוה", higher)
    if len(group) * 2 <= len(pairs):
        return None
    wide = max(group, key=lambda r: (abs(r["e"] - r["d"]), r["label"]))
    who = (f"בכל {len(pairs):,} הענפים" if len(group) == len(pairs) else f"ב-{len(group):,} מתוך {len(pairs):,} הענפים")
    return (f"{who} שיש להם מדד מקביל לשוק המקומי, "
            f"שינוי מחירי היצוא בשנה האחרונה {word} משינוי המחירים בשוק המקומי (ממוצע רבעוני). הפער הגדול "
            f"ביותר: {wide['label']} ({_isp(wide['e'])} ביצוא, {_isp(wide['d'])} בשוק המקומי)."
            + (VAT_CAVEAT if latest[0] == VAT_YEAR else ""))


def insight_branches(rank):
    if len(rank) < 5:
        return None
    up = sum(1 for r in rank if r["py"] > 0)
    down = sum(1 for r in rank if r["py"] < 0)
    top, low = rank[0], rank[-1]
    if top["py"] == low["py"]:
        return None
    return (f"לעומת הרבעון המקביל אשתקד עלו מחירי היצוא ב-{up:,} מתוך {len(rank):,} הענפים "
            f"הראשיים וירדו ב-{down:,}. השינוי הגבוה ביותר: {top['label']} ({_isp(top['py'])}); "
            f"הנמוך ביותר: {low['label']} ({_isp(low['py'])}).")


def insight_cum(cum, base_year):
    if len(cum) < 5:
        return None
    top, low = cum[0], cum[-1]
    if top["chg"] <= 0:
        return None
    tail = ("הוזלו" if low["chg"] < 0 else "עלו הכי מעט")
    return (f"לעומת הממוצע של {base_year} התייקר היצוא בעיקר בענף {top['label']} "
            f"({_iss(top['chg'])}), ואילו מחירי היצוא בענף {low['label']} {tail} "
            f"({_iss(low['chg'])}).")


def insight_subs(subs):
    if len(subs) < 6:
        return None
    top, low = subs[0], subs[-1]
    parts = []
    if top["py"] >= SUB_MIN_ABS:
        parts.append(f"{top['label']} ({_isp(top['py'])})")
    if low["py"] <= -SUB_MIN_ABS:
        parts.append(f"{low['label']} ({_isp(low['py'])})")
    if not parts:
        return None
    return (f"בין ענפי המשנה, השינויים הבולטים במחירי היצוא לעומת הרבעון המקביל אשתקד: "
            f"{fmt.join_he(parts)}.")


# ── compute ───────────────────────────────────────────────────────────────


def compute(frames):
    ex = _export_series(frames)
    dom = _domestic_series(frames["domestic"])
    if HEAD not in ex:
        raise ValueError("headline code 195010 missing from branches")
    head = ex[HEAD]
    latest = max(head["s"])
    lv, lp, lpy = head["s"][latest]
    base_year = _base_year(head["base"])
    base_txt = f"ממוצע {base_year} = 100" if base_year else f"{head['base']} = 100"
    first = min(head["s"])

    def current(code):
        e = ex[code]
        return latest in e["s"] and e["s"][latest][2] is not None

    branch_codes = [c for c, e in ex.items() if e["src"] == "branches" and c != HEAD]
    sub_codes = [c for c, e in ex.items() if e["src"] == "subbranches"]
    stale = sum(1 for c in branch_codes + sub_codes if latest not in ex[c]["s"])

    # ── long: export vs domestic, rebased to the export base year ──
    dhead = dom.get(DOM_HEAD, {})
    dbase = _base_mean(dhead, base_year) if base_year else None
    qkeys = [k for k in head["s"] if k <= latest]
    cmp_ok = dbase is not None and sum(1 for k in qkeys if k in dhead) >= 8
    long_chart = {"x": [_qshort(k) for k in qkeys],
                  "exp": [_r(head["s"][k][0]) for k in qkeys],
                  "dom": [_r(dhead[k] / dbase * 100) if cmp_ok and k in dhead else None
                          for k in qkeys],
                  "names": ["יצוא", "שוק מקומי"]}
    years = sorted({k[0] for k in qkeys})
    long_rows = []
    for y in years:
        ev = [head["s"][(y, q)][0] for q in range(1, 5) if (y, q) in head["s"]]
        dv = [dhead[(y, q)] for q in range(1, 5) if (y, q) in head["s"] and (y, q) in dhead]
        note = "" if len(ev) == 4 else f" ({len(ev):,} רבעונים)"
        long_rows.append([f"{y}{note}", _lv(sum(ev) / len(ev)),
                          _lv(sum(dv) / len(dv) / dbase * 100) if cmp_ok and len(dv) == len(ev) else "–"])

    # ── yearly change: export published vs domestic computed ──
    yy_keys = [k for k in qkeys if head["s"][k][2] is not None]
    yy_chart = {"x": [_qshort(k) for k in yy_keys],
                "exp": [head["s"][k][2] for k in yy_keys],
                "dom": [_r(_yy(dhead, k), 1) if cmp_ok else None for k in yy_keys],
                "names": ["יצוא", "שוק מקומי"]}
    yy_rows = [[_qshort(k), _p(head["s"][k][2]), _p(_yy(dhead, k)) if cmp_ok else "–"]
               for k in reversed(yy_keys[-YY_TABLE_Q:])]
    d_yy_latest = _yy(dhead, latest) if cmp_ok else None

    # ── quarterly change ──
    qq_keys = [k for k in qkeys if head["s"][k][1] is not None][-QQ_Q:]
    qq_chart = {"x": [_qshort(k) for k in qq_keys], "y": [head["s"][k][1] for k in qq_keys]}
    qq_rows = [[_qshort(k), _p(head["s"][k][1]), _p(head["s"][k][2])] for k in reversed(qq_keys)]

    # ── branch ranking (yearly change, latest quarter) ──
    rank = [{"code": c, "label": ex[c]["label"], "py": ex[c]["s"][latest][2],
             "p": ex[c]["s"][latest][1], "v": ex[c]["s"][latest][0]}
            for c in branch_codes if current(c)]
    rank.sort(key=lambda r: (-r["py"], r["label"]))
    rank_chart = {"names": [r["label"] for r in rank], "y": [r["py"] for r in rank],
                  "head": lpy, "series_name": "שינוי שנתי"}
    rank_rows = [[r["label"], _p(r["py"]), _p(r["p"]), _lv(r["v"])] for r in rank]

    # ── export vs domestic by branch ──
    pairs = []
    for c in sorted(PAIRS, key=lambda c: (c != HEAD, c)):
        if c not in ex or not current(c):
            continue
        d = _yy(dom.get(PAIRS[c], {}), latest)
        if d is None:
            continue
        pairs.append({"code": c, "label": ex[c]["label"], "e": ex[c]["s"][latest][2], "d": round(d, 1)})
    pair_branches = [r for r in pairs if r["code"] != HEAD]
    pairs_sorted = sorted(pairs, key=lambda r: (r["code"] != HEAD, -(r["e"] - r["d"]), r["label"]))
    pair_chart = {"names": [r["label"] for r in pairs_sorted], "e": [r["e"] for r in pairs_sorted],
                  "d": [r["d"] for r in pairs_sorted], "series": ["יצוא", "שוק מקומי"]}
    pair_rows = [[r["label"], _p(r["e"]), _p(r["d"]), f"{r['e'] - r['d']:.1f}".replace("-", fmt.MINUS)]
                 for r in pairs_sorted]

    # ── cumulative change since the base year ──
    cum = []
    if base_year:
        for c in branch_codes:
            if not current(c):
                continue
            bm = _base_mean({k: v[0] for k, v in ex[c]["s"].items()}, base_year)
            if bm:
                cum.append({"label": ex[c]["label"], "chg": ex[c]["s"][latest][0] / bm - 1,
                            "v": ex[c]["s"][latest][0]})
    cum.sort(key=lambda r: (-r["chg"], r["label"]))
    head_bm = _base_mean({k: v[0] for k, v in head["s"].items()}, base_year) if base_year else None
    head_cum = lv / head_bm - 1 if head_bm else None
    cum_chart = {"names": [r["label"] for r in cum], "y": [round(r["chg"] * 100, 1) for r in cum],
                 "head": round(head_cum * 100, 1) if head_cum is not None else None}
    cum_rows = [[r["label"], _p(r["chg"] * 100), _lv(r["v"])] for r in cum]

    # ── heatmap: yearly change per branch, last quarters ──
    hq = [k for k in yy_keys][-HEAT_Q:]
    heat_codes = [HEAD] + [r["code"] for r in rank]
    cells = []
    for yi, c in enumerate(heat_codes):
        for xi, k in enumerate(hq):
            v = ex[c]["s"].get(k, (None, None, None))[2]
            if v is not None:
                cells.append([xi, yi, v])
    heat_chart = {"x": [_qshort(k) for k in hq], "y": [ex[c]["label"] for c in heat_codes],
                  "cells": cells,
                  "max": min(30.0, max([abs(c[2]) for c in cells] + [1.0]))}
    heat_cols = ["ענף"] + [_qshort(k) for k in hq]
    heat_rows = [[ex[c]["label"]] + [_p(ex[c]["s"].get(k, (None, None, None))[2]) for k in hq]
                 for c in heat_codes]

    # ── sub-branches ──
    subs = [{"label": ex[c]["label"], "py": ex[c]["s"][latest][2], "p": ex[c]["s"][latest][1]}
            for c in sub_codes if current(c)]
    subs.sort(key=lambda r: (-r["py"], r["label"]))
    subs_chart = {"names": [r["label"] for r in subs], "y": [r["py"] for r in subs],
                  "series_name": "שינוי שנתי"}
    subs_rows = [[r["label"], _p(r["py"]), _p(r["p"])] for r in subs]

    # ── insights ──
    cands = [
        ("latest", insight_latest(head, latest)),
        ("domestic", insight_domestic(lpy, d_yy_latest, latest)),
        ("branches", insight_branches(rank)),
        ("peak", insight_peak(head, latest)),
        ("streak", insight_streak(head, latest)),
        ("pairs", insight_pairs(pair_branches, latest)),
        ("cum", insight_cum(cum, base_year) if base_year else None),
        ("subs", insight_subs(subs)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in cands if t]

    up = sum(1 for r in rank if r["py"] > 0)
    tone_yy = "ok" if lpy is not None and lpy > 0 else ("warn" if lpy is not None and lpy < 0 else "brand")
    kpis = {
        "level": {"value": lv, "display": f"{lv:,.1f}", "tone": "brand"},
        "qq": {"value": lp, "display": _sp(lp), "tone": "brand"} if lp is not None else None,
        "yy": {"value": lpy, "display": _sp(lpy), "tone": tone_yy} if lpy is not None else None,
        "dom": ({"value": round(d_yy_latest, 1), "display": _sp(d_yy_latest), "tone": "info"}
                if d_yy_latest is not None else None),
        "up": {"value": up, "display": f"{up:,} / {len(rank):,}", "tone": "brand"} if rank else None,
    }
    kpis = {k: v for k, v in kpis.items() if v is not None}

    span = f"{_qshort(first)} עד {_qshort(latest)}"
    stale_line = (f"{stale:,} ענפים שהנתונים שלהם מסתיימים לפני {_qlong(latest)} אינם נכללים בהשוואות."
                  if stale else None)
    lede = (f"מדד מחירי היצרן ליצוא של הלשכה המרכזית לסטטיסטיקה מודד את המחירים שמקבלים יצרני "
            f"התעשייה, הכרייה והחציבה בישראל על סחורות שהם מוכרים לחו\"ל. {_qin(latest)} עמד "
            f"המדד על {lv:,.1f} נקודות ({base_txt})"
            + (f", שינוי של {_isp(lpy)} לעומת הרבעון המקביל אשתקד" if lpy is not None else "")
            + f". בעמוד: המדד הכללי מאז {first[0]}, {len(rank):,} ענפים ראשיים, "
              f"{len(subs):,} ענפי משנה, והשוואה למחירי היצרן לשוק המקומי.")
    summary = (f"מדד מחירי היצרן ליצוא בתעשייה, כרייה וחציבה, נתונים רבעוניים של הלמ\"ס "
               f"{span}: {_qin(latest)} {lv:,.1f} נקודות"
               + (f", {_isp(lpy)} בשנה" if lpy is not None else "")
               + f". כולל {len(rank):,} ענפים ראשיים וענפי משנה, והשוואה לשוק המקומי.")
    desc = (f"מדד מחירי יצרן ליצוא לפי ענף תעשייה, נתוני הלמ\"ס: {_qin(latest)} "
            + (f"{_sp(lpy)} בשנה" if lpy is not None else f"{lv:,.1f} נקודות")
            + ". תרופות, אלקטרוניקה, כימיקלים, יהלומים והשוואה לשוק המקומי.")

    labels = {
        "lede": lede,
        "level_kpi": f"מדד מחירי היצוא, {_qshort(latest)} ({base_txt})",
        "qq_kpi": "שינוי לעומת הרבעון הקודם",
        "yy_kpi": "שינוי לעומת הרבעון המקביל אשתקד",
        "dom_kpi": ("שינוי שנתי במחירי היצרן לשוק המקומי, אותו רבעון"
                    + (" (כולל העלאת המע\"מ)" if latest[0] == VAT_YEAR else "")),
        "up_kpi": "ענפים ראשיים שמחירי היצוא בהם עלו בשנה",
        "long_note": (f"המדד הכללי של מחירי היצוא, לצד מדד מחירי היצרן לשוק המקומי (תעשייה וכרייה "
                      f"וחציבה), שניהם ב{base_txt}. המדד המקומי חודשי, ומוצג כאן כממוצע של כל רבעון."
                      if cmp_ok else f"המדד הכללי של מחירי היצוא, {base_txt}."),
        "long_aria": f"מדד מחירי היצוא והשוק המקומי, {span}",
        "long_caption": f"ממוצע שנתי של המדדים ({base_txt})",
        "yy_note": ("שיעור השינוי לעומת הרבעון המקביל אשתקד. ביצוא: השינוי שפרסמה הלמ\"ס. בשוק "
                    "המקומי: מחושב מהממוצע הרבעוני של המדד החודשי. " + VAT_NOTE),
        "yy_aria": f"שיעור השינוי השנתי במחירי היצוא ובשוק המקומי, {_qshort(yy_keys[0]) if yy_keys else ''} עד {_qshort(latest)}",
        "yy_caption": "שיעור השינוי השנתי, הרבעונים האחרונים",
        "qq_note": "השינוי במדד הכללי של מחירי היצוא לעומת הרבעון הקודם, כפי שפרסמה הלמ\"ס.",
        "qq_aria": f"שינוי רבעוני במדד מחירי היצוא, {_qshort(qq_keys[0]) if qq_keys else ''} עד {_qshort(latest)}",
        "qq_caption": "השינוי הרבעוני והשנתי במדד מחירי היצוא",
        "rank_title": f"מחירי היצוא לפי ענף, {_qshort(latest)}",
        "rank_note": (f"שיעור השינוי במחירי היצוא של כל ענף ראשי {_qin(latest)} לעומת הרבעון "
                      f"המקביל אשתקד. הקו המקווקו: המדד הכללי ({_sp(lpy) if lpy is not None else ''})."),
        "rank_aria": f"שינוי שנתי במחירי היצוא לפי ענף, {_qshort(latest)}",
        "rank_caption": f"מחירי היצוא לפי ענף ראשי, {_qshort(latest)}",
        "rank_level_col": f"רמת המדד ({base_txt})",
        "pair_note": ("שיעור השינוי השנתי במחירים של אותו ענף ביצוא ובשוק המקומי. השינוי במדד "
                      "המקומי מחושב מהממוצע הרבעוני של המדד החודשי, ולכן עשוי להיות שונה מעט מהמספרים "
                      "החודשיים שמפרסמת הלמ\"ס. " + VAT_NOTE),
        "pair_aria": f"שינוי שנתי במחירים ביצוא ובשוק המקומי לפי ענף, {_qshort(latest)}",
        "pair_caption": f"יצוא מול שוק מקומי לפי ענף, {_qshort(latest)}",
        "cum_note": (f"השינוי ברמת מחירי היצוא של כל ענף מהממוצע של {base_year} עד {_qlong(latest)}. "
                     f"הקו המקווקו: המדד הכללי." if base_year else ""),
        "cum_aria": f"שינוי מצטבר במחירי היצוא לפי ענף מאז {base_year}",
        "cum_caption": f"שינוי מצטבר במחירי היצוא לפי ענף מאז ממוצע {base_year}",
        "cum_title": f"השינוי המצטבר לפי ענף מאז {base_year}",
        "cum_col": f"שינוי מאז ממוצע {base_year}",
        "heat_note": (f"שיעור השינוי השנתי במחירי היצוא של כל ענף ב-{len(hq):,} הרבעונים האחרונים: "
                      f"כחול לעלייה, אדום לירידה."),
        "heat_aria": f"מפת חום של השינוי השנתי במחירי היצוא לפי ענף, {_qshort(hq[0]) if hq else ''} עד {_qshort(latest)}",
        "heat_caption": "שינוי שנתי במחירי היצוא לפי ענף ורבעון",
        "heat_cols": heat_cols,
        "subs_note": (f"שיעור השינוי במחירי היצוא של ענפי משנה נבחרים {_qin(latest)} לעומת הרבעון "
                      f"המקביל אשתקד."),
        "subs_aria": f"שינוי שנתי במחירי היצוא בענפי משנה, {_qshort(latest)}",
        "subs_caption": f"מחירי היצוא בענפי משנה נבחרים, {_qshort(latest)}",
        "about": [x for x in [
            (f"מקור: הלשכה המרכזית לסטטיסטיקה, מאגר המדדים, פרק מדד מחירי יצרן - יצוא בענפי "
             f"התעשייה, במתכונת הסיווג האחיד של ענפי הכלכלה 2011. נתונים רבעוניים, {span}."),
            (f"רמות המדד משורשרות לבסיס אחד ({base_txt}) באמצעות מקדמי הקישור של הלמ\"ס. שיעורי "
             f"השינוי של מדד היצוא הם המספרים שפרסמה הלמ\"ס, מעוגלים לעשירית האחוז."),
            ("מדד מחירי היצרן לשוק המקומי (תפוקת התעשייה ליעדים מקומיים) מתפרסם מדי חודש. "
             "לצורך ההשוואה חושב כאן ממוצע של שלושת החודשים בכל רבעון, ורק רבעונים שלמים נכללים."),
            VAT_NOTE,
            stale_line,
        ] if x],
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first[0]}/{latest[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד מחירי יצרן ליצוא לפי ענף | מחירי היצוא בתעשייה",
                "description": desc,
                "name": "מדד מחירי יצרן ליצוא",
                "alternate_names": ["מדד מחירי היצוא בתעשייה", "מדד מחירי תפוקת התעשייה ליצוא",
                                    "מדד מחירי יצרן - יצוא בענפי התעשייה"],
            },
        },
        "kpis": kpis,
        "charts": {"long": long_chart, "yy": yy_chart, "qq": qq_chart, "rank": rank_chart,
                   "pair": pair_chart, "cum": cum_chart, "heat": heat_chart, "subs": subs_chart},
        "tables": {"long": long_rows, "yy": yy_rows, "qq": qq_rows, "rank": rank_rows,
                   "pair": pair_rows, "cum": cum_rows, "heat": heat_rows, "subs": subs_rows},
        "flags": {"cmp": cmp_ok, "rank": len(rank) >= 3, "pair": len(pairs) >= 3,
                  "cum": len(cum) >= 3, "heat": len(cells) > 0, "subs": len(subs) >= 3},
        "insights": insights,
        "labels": labels,
    }
