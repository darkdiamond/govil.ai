"""Quarterly producer price indices for the services industries (CBS Index API).

One row per (CODE, quarter). Every code is chained by the provider onto its own
newest base (VALUE_CHAINED), and the bases differ between codes (2004, 2005,
2009, 2023, 2024 averages...), so levels are never compared across codes:
cross-industry views use CBS's published changes (PERCENT, PERCENT_YEAR) or
each series rebased to 100 at a shared start quarter.
"""
import math

import pandas as pd
from govlib import fmt

ORD_HE = {1: "הראשון", 2: "השני", 3: "השלישי", 4: "הרביעי"}

# Short display labels for known codes; an unknown code renders with NAME_HE.
LABELS = {
    "194160": "תכנות וייעוץ מחשבים",
    "194165": "תכנות מחשבים",
    "194170": "ייעוץ מחשבים וניהול מתקנים",
    "194190": "שירותים משפטיים",
    "194210": "חשבונאות וייעוץ מס",
    "194250": "ייעוץ ניהולי",
    "194270": "פרסום",
    "194275": "פרסום בטלוויזיה",
    "194280": "פרסום בעיתונות",
    "194285": "פרסום באינטרנט",
    "194290": "פרסום ברדיו",
    "194295": "שילוט חוצות",
    "194310": "שירותי תעסוקה",
    "194350": "שירותי תעסוקה בלי המגזר הציבורי",
    "194370": "השמה",
    "194390": "העסקת כוח אדם",
    "194110": "שמירה ואבטחה",
    "194130": "שירותי ניקיון",
}
# Sub-indices and the main industry they belong to (CBS's catalog levels are
# not a reliable tree, so the hierarchy is spelled out). Codes not listed here
# are main industries.
PARENT = {
    "194165": "194160", "194170": "194160",
    "194275": "194270", "194280": "194270", "194285": "194270",
    "194290": "194270", "194295": "194270",
    "194350": "194310", "194370": "194310", "194390": "194310",
}
GROUP_TITLES = {
    "194160": "מחשוב: תכנות וייעוץ בתחום המחשבים",
    "194270": "פרסום לפי אמצעי מדיה",
    "194310": "שירותי תעסוקה: השמה והעסקת כוח אדם",
}
LONG_MIN_Q = 40          # quarters of history for the long-run comparison
STREAK_MIN = 3           # quarters in a row below last year's level
SPREAD_MOVE = 1.25       # latest spread vs the median spread: wider / narrower
HOT_YOY = 5.0            # y/y above this reads as a fast rise (KPI tone)
HEAT_QUARTERS = 8
STALE_Q = 4              # a code this many quarters behind reads as discontinued
# A sub-index that is an alternative cut of its parent, not a part of it.
VARIANT = {"194350"}


def _f(s):
    s = str(s).strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _pct(v):
    """A published percent change (0-100 scale) as signed text: +2.3%, −4.8%."""
    return fmt.signed_pct(v / 100.0)


def _qlabel(k):
    y, q = divmod(k, 4)
    return f"רבעון {q + 1} {y}"


def _qshort(k):
    y, q = divmod(k, 4)
    return f"ר{q + 1} {y}"


def _qprose(k):
    y, q = divmod(k, 4)
    return f"ברבעון {ORD_HE[q + 1]} של {y}"


def _base_he(b):
    """CBS's "2024 ממוצע" as "ממוצע 2024 = 100"; anything else as published."""
    parts = b.split()
    if len(parts) == 2 and parts[0].isdigit() and parts[1] == "ממוצע":
        return f"ממוצע {parts[0]} = 100"
    return b


def _r1(v):
    return None if v is None else round(v, 1)


def _load(df):
    df = df[df["FREQ"].astype(str).str.strip() == "Q"].copy()
    df["CODE"] = df["CODE"].astype(str).str.strip()
    df["Y"] = pd.to_numeric(df["YEAR"], errors="coerce")
    df["P"] = pd.to_numeric(df["PERIOD"], errors="coerce")
    df = df[df["Y"].notna() & df["P"].between(1, 4)]
    df["K"] = (df["Y"].astype(int) * 4 + df["P"].astype(int) - 1).astype(int)
    df = df.sort_values(["CODE", "K", "VALUE_CHAINED", "PERCENT_YEAR"], kind="mergesort")
    df = df.drop_duplicates(["CODE", "K"], keep="last")
    series = {}
    for code, g in df.groupby("CODE", sort=True):
        obs = {}
        for r in g.itertuples(index=False):
            obs[int(r.K)] = {
                "v": _f(r.VALUE_CHAINED), "raw": _f(r.VALUE), "base": str(r.BASE_DESC).strip(),
                "p": _f(r.PERCENT), "py": _f(r.PERCENT_YEAR),
            }
        obs = {k: o for k, o in obs.items() if o["v"] is not None}
        if not obs:
            continue
        names = sorted({str(n).strip() for n in g["NAME_HE"] if str(n).strip()})
        chain = sorted({str(n).strip() for n in g["CHAIN_BASE"] if str(n).strip()})
        series[code] = {
            "code": code,
            "label": LABELS.get(code) or (names[0] if names else code),
            "name_he": names[0] if names else code,
            "chain_base": chain[-1] if chain else "",
            "obs": obs,
            "first": min(obs), "last": max(obs),
        }
    return series


def _rebased(s, start, end):
    o = s["obs"]
    if start not in o or not o[start]["v"]:
        return None
    b = o[start]["v"]
    return [_r1(o[k]["v"] / b * 100) if k in o else None for k in range(start, end + 1)]


def _parent_of(code, series):
    p = PARENT.get(code)
    return p if p and p in series else None


def compute(frames):
    series = _load(frames["services"])
    if not series:
        raise ValueError("no quarterly rows")
    latest = max(s["last"] for s in series.values())
    codes = sorted(series, key=lambda c: (series[c]["label"], c))
    main = [c for c in codes if PARENT.get(c) is None]
    subs = [c for c in codes if PARENT.get(c) is not None]
    current = [c for c in codes if series[c]["last"] == latest]
    lagging = [c for c in codes if latest - STALE_Q < series[c]["last"] < latest]
    stopped = [c for c in codes if series[c]["last"] <= latest - STALE_Q]

    def py_at(c, k):
        o = series[c]["obs"].get(k)
        return None if o is None else o["py"]

    def p_at(c, k):
        o = series[c]["obs"].get(k)
        return None if o is None else o["p"]

    # ── latest quarter ranking (y/y, as published) ──────────────────────
    ranked = [c for c in current if py_at(c, latest) is not None]
    ranked.sort(key=lambda c: (-py_at(c, latest), series[c]["label"], c))
    main_ranked = [c for c in ranked if c in main]
    rank_chart = {
        "names": [series[c]["label"] for c in ranked],
        "yoy": [py_at(c, latest) for c in ranked],
        "qoq": [p_at(c, latest) for c in ranked],
        "sub": [c in subs for c in ranked],
    }
    rank_rows = []
    for c in ranked:
        o = series[c]["obs"][latest]
        par = _parent_of(c, series)
        rank_rows.append([
            series[c]["label"],
            ("מדד חלופי של " if c in VARIANT else "ענף משנה של ") + series[par]["label"]
            if par else "ענף ראשי",
            _pct(o["py"]),
            _pct(o["p"]) if o["p"] is not None else "–",
            fmt.num_he(o["raw"]) if o["raw"] is not None else "–",
            _base_he(o["base"]) if o["base"] else "–",
        ])

    kpis, labels, insights = {}, {}, []
    qp = _qprose(latest)
    labels["latest_q"] = _qlabel(latest)

    if main_ranked:
        top, bot = main_ranked[0], main_ranked[-1]
        tv, bv = py_at(top, latest), py_at(bot, latest)
        kpis["top"] = {"value": tv, "display": _pct(tv),
                       "tone": "warn" if tv >= HOT_YOY else "info"}
        labels["top_kpi"] = (f"{series[top]['label']}: השינוי השנתי הגבוה בענפים הראשיים "
                             f"({_qlabel(latest)})")
        if bot != top:
            kpis["bottom"] = {"value": bv, "display": _pct(bv),
                              "tone": "info" if bv < 0 else "brand"}
            labels["bottom_kpi"] = (f"{series[bot]['label']}: השינוי השנתי הנמוך בענפים "
                                    f"הראשיים ({_qlabel(latest)})")
        vals = sorted(py_at(c, latest) for c in main_ranked)
        med = float(pd.Series(vals).median())
        kpis["median"] = {"value": med, "display": _pct(med), "tone": "brand"}
        labels["median_kpi"] = (f"חציון השינוי השנתי ב-{len(vals)} הענפים הראשיים "
                                f"שפורסמו ל{_qlabel(latest)}")
        up = [c for c in main_ranked if py_at(c, latest) > 0]
        down = [c for c in main_ranked if py_at(c, latest) < 0]
        kpis["up"] = {"value": len(up), "display": str(len(up)),
                      "tone": "warn" if len(up) == len(main_ranked) else "brand"}
        labels["up_kpi"] = f"ענפים ראשיים (מתוך {len(main_ranked)}) שבהם המחירים גבוהים מאשתקד"

        if bot != top and tv - bv >= 2:
            insights.append({"id": "leader", "text_he": (
                (f"{qp} עלו מחירי {series[top]['label']} ב-{fmt.num_he(tv)}% לעומת הרבעון המקביל "
                 f"אשתקד, הקצב המהיר ביותר בענפים הראשיים. " if tv > 0 else
                 f"{qp} השינוי השנתי הגבוה בענפים הראשיים הוא ב{series[top]['label']}: {_pct(tv)}. ")
                + f"בקצה השני, {series[bot]['label']}: "
                + (f"ירידה של {fmt.num_he(abs(bv))}%." if bv < 0 else
                   (f"עלייה של {fmt.num_he(bv)}% בלבד." if bv > 0 else "ללא שינוי."))
            )})
        if len(main_ranked) >= 3:
            if down:
                tail = (f" המחירים ירדו {fmt.join_he('ב' + series[c]['label'] for c in down)}.")
            else:
                tail = " באף ענף ראשי המחירים לא ירדו."
            insights.append({"id": "breadth", "text_he": (
                f"ב-{len(up)} מתוך {len(main_ranked)} הענפים הראשיים המחירים {qp} "
                f"גבוהים מאשר שנה קודם לכן, והחציון הוא {_pct(med)}.{tail}"
            )})

    # ── largest quarterly move in the latest quarter ────────────────────
    q_moves = [c for c in main if c in current and p_at(c, latest) is not None]
    if q_moves:
        mv = max(q_moves, key=lambda c: (abs(p_at(c, latest)), series[c]["label"], c))
        v = p_at(mv, latest)
        if abs(v) >= 1.5:
            insights.append({"id": "quarter_move", "text_he": (
                f"השינוי הרבעוני החד ביותר {qp}: מחירי {series[mv]['label']} "
                f"{'עלו' if v > 0 else 'ירדו'} ב-{fmt.num_he(abs(v))}% לעומת הרבעון הקודם."
            )})

    # ── long run since a common start ───────────────────────────────────
    long_codes = [c for c in main if len(series[c]["obs"]) >= LONG_MIN_Q and c in current]
    long_flag = len(long_codes) >= 3
    if long_flag:
        start = max(series[c]["first"] for c in long_codes)
        # The shared start must exist in every series (a gap could hit it).
        while start <= latest and any(start not in series[c]["obs"] for c in long_codes):
            start += 1
        long_flag = latest - start >= 8
    if long_flag:
        xs = list(range(start, latest + 1))
        lines = {c: _rebased(series[c], start, latest) for c in long_codes}
        order = sorted(long_codes, key=lambda c: (-(lines[c][-1] or 0), series[c]["label"], c))
        excluded = [c for c in main if len(series[c]["obs"]) < LONG_MIN_Q]
        behind = [c for c in main if c not in long_codes and c not in excluded and c in lagging]
        labels["start_q"] = _qlabel(start)
        labels["longrun_note"] = (
            f"כל מדד חולק ברמתו ב{_qlabel(start)}, כך שכל הקווים מתחילים ב-100 ואפשר להשוות את "
            f"הקצב בין הענפים (לכל ענף בסיס מדד משלו, ולכן אין להשוות את הרמות שמפרסמת הלמ\"ס). "
            f"נכללים ענפים ראשיים עם {LONG_MIN_Q} רבעונים לפחות"
            + (f". ענפים עם היסטוריה קצרה יותר ({fmt.join_he(series[c]['label'] for c in excluded)}) "
               f"אינם בתרשים." if excluded else ".")
            + (f" עוד לא פורסמו ל{_qlabel(latest)} ולכן אינם בתרשים: "
               f"{fmt.join_he(series[c]['label'] for c in behind)}." if behind else "")
        )
        longrun_chart = {
            "x": [_qshort(k) for k in xs],
            "series": [{"name": series[c]["label"], "data": lines[c]} for c in order],
        }
        q_last = latest % 4
        longrun_rows = []
        for k in xs:
            if k % 4 == q_last:
                longrun_rows.append([_qlabel(k)] + [
                    fmt.num_he(lines[c][k - start]) if lines[c][k - start] is not None else "–"
                    for c in order])
        labels["longrun_cols"] = ["רבעון"] + [series[c]["label"] for c in order]
        labels["longrun_caption"] = f"המדדים ב{_qlabel(start)} = 100, ברבעון המקביל בכל שנה"
        labels["longrun_aria"] = (f"מדדי המחירים של {len(order)} ענפי שירותים מאז "
                                  f"{_qlabel(start)}, כש-100 הוא רמת הפתיחה")

        # cumulative change and annualized pace
        years = (latest - start) / 4.0
        cum = []
        for c in order:
            last_v = lines[c][-1]
            ch = last_v / 100.0 - 1
            ann = (last_v / 100.0) ** (1 / years) - 1
            cum.append((c, ch, ann))
        cum_chart = {"names": [series[c]["label"] for c, _, _ in cum],
                     "cum": [round(ch * 100, 1) for _, ch, _ in cum],
                     "ann": [round(a * 100, 1) for _, _, a in cum]}
        cum_rows = [[series[c]["label"], fmt.signed_pct(ch), fmt.signed_pct(a)] for c, ch, a in cum]
        labels["cum_note"] = (
            f"השינוי המצטבר במחירים מ{_qlabel(start)} עד {_qlabel(latest)}, וקצב העלייה הממוצע "
            f"לשנה באותה תקופה (מחושב מהמדד המשורשר של הלמ\"ס)."
        )
        labels["cum_aria"] = f"השינוי המצטבר במחירים בכל ענף מאז {_qlabel(start)}"
        labels["cum_caption"] = f"שינוי מצטבר וקצב שנתי ממוצע מאז {_qlabel(start)}"
        hi, lo = cum[0], cum[-1]
        if hi[1] - lo[1] >= 0.10 and hi[1] > 0:
            insights.append({"id": "longrun", "text_he": (
                f"מאז {_qlabel(start)} עלו מחירי {series[hi[0]]['label']} ב-{fmt.pct(hi[1])} "
                f"(כ-{fmt.pct(hi[2])} בשנה), ואילו מחירי {series[lo[0]]['label']} "
                + (f"ירדו ב-{fmt.pct(abs(lo[1]))}." if lo[1] < 0 else
                   f"עלו ב-{fmt.pct(lo[1])} בלבד.")
            )})

        # annual average change heatmap (full calendar years only)
        ann_years, ann_cells, ann_tab = [], [], {}
        for c in order:
            o = series[c]["obs"]
            means = {}
            for y in range(start // 4, latest // 4 + 1):
                ks = [y * 4 + q for q in range(4)]
                if all(k in o for k in ks):
                    means[y] = sum(o[k]["v"] for k in ks) / 4
            for y in sorted(means):
                if y - 1 in means:
                    ann_tab[(c, y)] = round((means[y] / means[y - 1] - 1) * 100, 1)
        ann_years = sorted({y for _, y in ann_tab})
        ann_flag = len(ann_years) >= 3
        if ann_flag:
            for yi, c in enumerate(order):
                for xi, y in enumerate(ann_years):
                    if (c, y) in ann_tab:
                        ann_cells.append([xi, yi, ann_tab[(c, y)]])
            amax = max(abs(v[2]) for v in ann_cells)
            ann_chart = {"x": [str(y) for y in ann_years],
                         "y": [series[c]["label"] for c in order],
                         "cells": ann_cells, "max": math.ceil(amax)}
            ann_rows = [[str(y)] + [_pct(ann_tab[(c, y)]) if (c, y) in ann_tab else "–"
                                    for c in order] for y in ann_years]
            labels["annual_cols"] = ["שנה"] + [series[c]["label"] for c in order]
            labels["annual_note"] = (
                f"השינוי בממוצע השנתי של כל מדד לעומת השנה הקודמת, {ann_years[0]} עד "
                f"{ann_years[-1]}. נכללות רק שנים שיש בהן ארבעה רבעונים."
            )
            labels["annual_aria"] = "מפת חום של השינוי השנתי הממוצע במחירים לפי ענף ושנה"
            labels["annual_caption"] = "שינוי שנתי בממוצע המדד לפי ענף ושנה"
            # the year with the highest median change
            med_y = {}
            for y in ann_years:
                vs = [ann_tab[(c, y)] for c in order if (c, y) in ann_tab]
                if len(vs) >= 3:
                    med_y[y] = float(pd.Series(vs).median())
            if len(med_y) >= 3:
                hy = max(med_y, key=lambda y: (med_y[y], y))
                ly = min(med_y, key=lambda y: (med_y[y], -y))
                if med_y[hy] - med_y[ly] >= 2 and med_y[hy] > 0:
                    insights.append({"id": "annual", "text_he": (
                        f"בממוצע שנתי, {hy} הייתה השנה שבה התייקרו השירותים הכי מהר "
                        f"(חציון של {_pct(med_y[hy])} בין הענפים), ו-{ly} השנה האיטית ביותר "
                        f"({_pct(med_y[ly])})."
                    )})
    else:
        ann_flag = False

    # ── dispersion of y/y across main industries ───────────────────────
    sp_x, sp_min, sp_med, sp_max, sp_n, sp_rows, spreads = [], [], [], [], [], [], []
    k0 = min(series[c]["first"] for c in main) if main else latest
    for k in range(k0, latest + 1):
        vs = sorted((py_at(c, k), c) for c in main if py_at(c, k) is not None)
        if len(vs) < 3:
            continue
        m = float(pd.Series([v for v, _ in vs]).median())
        sp_x.append(_qshort(k))
        sp_min.append(vs[0][0])
        sp_max.append(vs[-1][0])
        sp_med.append(round(m, 2))
        sp_n.append(len(vs))
        spreads.append((k, vs[-1][0] - vs[0][0]))
        sp_rows.append([_qlabel(k), str(len(vs)), _pct(vs[0][0]) + " (" + series[vs[0][1]]["label"] + ")",
                        _pct(m), _pct(vs[-1][0]) + " (" + series[vs[-1][1]]["label"] + ")"])
    spread_flag = len(sp_x) >= 8
    if spread_flag:
        spread_chart = {"x": sp_x, "min": sp_min, "med": sp_med, "max": sp_max, "n": sp_n}
        labels["spread_note"] = (
            "בכל רבעון: השינוי השנתי הנמוך, החציוני והגבוה בין הענפים הראשיים שפורסמו באותו "
            "רבעון. פס רחב פירושו שהמחירים בענפים השונים נעים בקצב שונה מאוד."
        )
        labels["spread_aria"] = "טווח השינוי השנתי במחירים בין ענפי השירותים בכל רבעון"
        labels["spread_caption"] = "השינוי השנתי הנמוך, החציוני והגבוה בכל רבעון"
        sp_rows.reverse()
        if spreads[-1][0] == latest and len(spreads) >= 8:
            last_sp = spreads[-1][1]
            med_sp = float(pd.Series([s for _, s in spreads]).median())
            if med_sp > 0 and (last_sp >= med_sp * SPREAD_MOVE or last_sp <= med_sp / SPREAD_MOVE):
                wider = last_sp > med_sp
                insights.append({"id": "spread", "text_he": (
                    f"הפער בין השינוי השנתי הגבוה לנמוך בין הענפים הראשיים עומד {qp} על "
                    f"{fmt.num_he(last_sp)} נקודות אחוז, "
                    + ("רחב" if wider else "צר")
                    + f" מהפער החציוני מאז {_qlabel(spreads[0][0])} ({fmt.num_he(med_sp)} נקודות)."
                )})

    # ── ongoing streak of y/y declines (any code) ───────────────────────
    best = None
    for c in current:
        n, k = 0, latest
        while py_at(c, k) is not None and py_at(c, k) < 0:
            n += 1
            k -= 1
        if n >= STREAK_MIN and (best is None or (n, c in main) > (best[1], best[0] in main)):
            best = (c, n)
    if best:
        c, n = best
        insights.append({"id": "streak", "text_he": (
            f"מחירי {series[c]['label']} נמוכים מרמתם שנה קודם לכן זה {n} רבעונים ברציפות, "
            f"מאז {_qlabel(latest - n + 1)}."
        )})

    # ── quarter-on-quarter heatmap (recent quarters, main industries) ──
    hq = list(range(max(latest - HEAT_QUARTERS + 1, k0), latest + 1))
    heat_codes = [c for c in main if any(p_at(c, k) is not None for k in hq)]
    heat_codes.sort(key=lambda c: (series[c]["label"], c))
    qoq_cells = []
    for yi, c in enumerate(heat_codes):
        for xi, k in enumerate(hq):
            v = p_at(c, k)
            if v is not None:
                qoq_cells.append([xi, yi, v])
    qoq_flag = len(heat_codes) >= 3 and len(hq) >= 4
    qoq_chart = {"x": [_qshort(k) for k in hq], "y": [series[c]["label"] for c in heat_codes],
                 "cells": qoq_cells,
                 "max": math.ceil(max([abs(v[2]) for v in qoq_cells] or [1]))}
    qoq_rows = [[series[c]["label"]] + [_pct(p_at(c, k)) if p_at(c, k) is not None else "–"
                                        for k in hq] for c in heat_codes]
    labels["qoq_cols"] = ["ענף"] + [_qlabel(k) for k in hq]
    labels["qoq_note"] = (
        f"השינוי במחירים לעומת הרבעון הקודם, כפי שפרסמה הלמ\"ס, ב-{len(hq)} הרבעונים האחרונים. "
        "התא ריק כשלא פורסם מדד לאותו רבעון."
    )
    labels["qoq_aria"] = "מפת חום של השינוי הרבעוני במחירים לפי ענף ורבעון"
    labels["qoq_caption"] = "שינוי רבעוני במחירים לפי ענף ורבעון"

    # ── groups: a main industry and its sub-indices ────────────────────
    groups, group_ins = [], []
    for par in sorted({PARENT[c] for c in subs if _parent_of(c, series)}):
        members = [par] + sorted([c for c in subs if PARENT[c] == par],
                                 key=lambda c: (series[c]["label"], c))
        members = [c for c in members if series[c]["last"] == latest]
        if len(members) < 2:
            continue
        gstart = max(series[c]["first"] for c in members)
        while gstart <= latest and any(gstart not in series[c]["obs"] for c in members):
            gstart += 1
        if latest - gstart < 2:
            continue
        xs = list(range(gstart, latest + 1))
        lines = {c: _rebased(series[c], gstart, latest) for c in members}
        gid = f"chart-group-{par}"
        rows = []
        for k in reversed(xs):
            rows.append([_qlabel(k)] + [
                fmt.num_he(lines[c][k - gstart]) if lines[c][k - gstart] is not None else "–"
                for c in members])
        yoy = [(c, py_at(c, latest)) for c in members if py_at(c, latest) is not None]
        yoy_txt = "; ".join(f"{series[c]['label']} {_pct(v)}" for c, v in yoy)
        note = (f"כל מדד חולק ברמתו ב{_qlabel(gstart)}, הרבעון הראשון שבו פורסמו כל "
                f"המדדים בקבוצה, כך שכולם מתחילים ב-100.")
        if yoy_txt:
            note += f" השינוי השנתי {qp}: {yoy_txt}."
        groups.append({
            "id": gid, "title": GROUP_TITLES.get(par) or series[par]["label"],
            "note": note,
            "aria": f"מדדי המחירים של {series[par]['label']} וענפי המשנה שלו מאז {_qlabel(gstart)}",
            "caption": f"המדדים ב{_qlabel(gstart)} = 100",
            "cols": ["רבעון"] + [series[c]["label"] for c in members],
            "rows": rows,
            "chart": {"x": [_qshort(k) for k in xs],
                      "series": [{"name": series[c]["label"], "data": lines[c],
                                  "parent": c == par} for c in members]},
        })
        kids = [(c, v) for c, v in yoy if c != par and c in subs and PARENT.get(c) == par
                and c != "194350"]
        if len(kids) >= 2:
            kids.sort(key=lambda t: (-t[1], series[t[0]]["label"]))
            (hc, hv), (lc, lv) = kids[0], kids[-1]
            if hv - lv >= 3:
                group_ins.append((hv - lv, par, {"id": f"group_{par}", "text_he": (
                    f"בתוך {series[par]['label']} הכיוון אינו אחיד: {qp} "
                    f"השינוי השנתי ב{series[hc]['label']} הוא {_pct(hv)}, "
                    f"ואילו ב{series[lc]['label']} {_pct(lv)}."
                )}))

    group_ins.sort(key=lambda t: (-t[0], t[1]))
    insights.extend(g for _, _, g in group_ins[:2])

    # ── text ────────────────────────────────────────────────────────────
    labels["rank_note"] = (
        f"השינוי במחירים {qp} לעומת הרבעון המקביל אשתקד, כפי שפרסמה הלמ\"ס, בכל המדדים "
        f"שפורסמו לרבעון זה. כחול כהה: ענף ראשי; כחול בהיר: ענף משנה."
        + (f" לא פורסמו עדיין ל{_qlabel(latest)}: "
           f"{fmt.join_he(series[c]['label'] for c in lagging)}." if lagging else "")
        + (f" לא עודכנו מאז רבעונים קודמים ולכן אינם בדירוג: "
           f"{fmt.join_he(series[c]['label'] + ' (' + _qlabel(series[c]['last']) + ')' for c in stopped)}."
           if stopped else "")
    )
    labels["rank_aria"] = f"דירוג ענפי השירותים לפי השינוי השנתי במחירים, {_qlabel(latest)}"
    labels["rank_caption"] = f"השינוי השנתי והרבעוני במחירים, {_qlabel(latest)}"

    first_all = min(s["first"] for s in series.values())
    labels["lede"] = (
        f"מדדי מחירי היצרן לענפי השירותים של הלשכה המרכזית לסטטיסטיקה מודדים כמה גובים "
        f"נותני שירותים עסקיים מלקוחותיהם: עורכי דין ורואי חשבון, יועצים, משרדי פרסום, חברות "
        f"השמה וכוח אדם, שמירה וניקיון ותכנות מחשבים. העמוד מציג {len(codes)} מדדים רבעוניים "
        f"({len(main)} ענפים ראשיים ו-{len(subs)} ענפי משנה), מ{_qlabel(first_all)} ועד {_qlabel(latest)}, "
        f"הרבעון האחרון שפורסם."
    )
    bases = sorted({_base_he(series[c]["chain_base"]) for c in codes if series[c]["chain_base"]})
    labels["bases_note"] = (
        f"לכל מדד בסיס משלו ({fmt.join_he(bases)}), ולכן רמות המדדים אינן ברות השוואה בין "
        f"ענפים. ההשוואות בעמוד נעשות לפי אחוזי השינוי שמפרסמת הלמ\"ס, או אחרי חלוקה של כל "
        f"מדד ברמתו ברבעון משותף."
    )

    young = {}
    for c in codes:
        if len(series[c]["obs"]) < 12:
            young.setdefault(series[c]["first"], []).append(series[c]["label"])
    labels["new_note"] = (
        ("חלק מהמדדים חדשים ומתפרסמים רק ברבעונים האחרונים: "
         + "; ".join(f"מ{_qlabel(k)}: {fmt.join_he(v)}" for k, v in sorted(young.items()))
         + ". " if young else "")
        + "מדד שעוד לא פורסם לרבעון האחרון אינו נכלל בהשוואות של אותו רבעון."
    )

    summary = f"מדדי מחירי היצרן הרבעוניים של הלמ\"ס ל-{len(main)} ענפי שירותים עסקיים, עד {_qlabel(latest)}."
    desc = f"מדד מחירי יצרן לענפי השירותים של הלמ\"ס, עד {_qlabel(latest)}."
    if main_ranked:
        summary += (f" השינוי השנתי הגבוה: {series[top]['label']} ({_pct(tv)}), "
                    f"והחציון בין הענפים {_pct(med)}.")
        desc = (f"מדד מחירי יצרן לענפי השירותים של הלמ\"ס, {_qlabel(latest)}: "
                f"{series[top]['label']} {_pct(tv)} בשנה, חציון הענפים {_pct(med)}.")
    if len(desc) < 80:
        desc += " עורכי דין, רואי חשבון, פרסום, כוח אדם ועוד."

    tables = {"rank": rank_rows, "qoq": qoq_rows, "spread": sp_rows if spread_flag else []}
    charts = {"rank": rank_chart, "qoq": qoq_chart}
    if spread_flag:
        charts["spread"] = spread_chart
    if long_flag:
        charts["longrun"] = longrun_chart
        charts["cum"] = cum_chart
        tables["longrun"] = longrun_rows
        tables["cum"] = cum_rows
        if ann_flag:
            charts["annual"] = ann_chart
            tables["annual"] = ann_rows

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_all // 4}/{latest // 4}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד מחירי יצרן לענפי השירותים: עלייה שנתית לפי ענף",
                "description": desc,
                "name": "מדד מחירי יצרן לענפי השירותים",
                "alternate_names": [
                    "מדדי מחירים רבעוניים לענפי השירותים",
                    "מדד מחירי תפוקה בענפי השירותים",
                    "מדד מחירי שירותים עסקיים",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "groups": groups,
        "insights": insights,
        "labels": labels,
        "flags": {"longrun": long_flag, "annual": long_flag and ann_flag,
                  "spread": spread_flag, "qoq": qoq_flag},
    }
