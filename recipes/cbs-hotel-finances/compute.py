"""הכנסות, הוצאות ורווח מלונות התיירות: CBS's yearly release on tourist
hotels' profit and loss (from the hotels' tax filings, a ~2.5-year lag).

Every edition carries whole series in the prices of its latest year, so only
the newest edition is read (history_releases 1). CBS renumbers and reshapes
the sheets between editions (the 2024 chart sheet sat 10 columns to the
right; the locality-share chart flipped between fractions and percent), so
every table input (t1..t7, three spare, all optional) is recognised by its
title text, never by its stem:

  loc     לוח ... לפי ישובים נבחרים       NIS million in basic prices of the
                                          latest year, by locality, ~7 years:
                                          revenue, expenses, wages, profit,
                                          gross value added (+ a %-change block,
                                          recomputed here instead)
  trend   תרשים ... הכנסות, הוצאות ורווח  revenue / expenses since 1991, in the
                                          prices of the latest year
  struct  תרשים ... כאחוז מההכנסות        expenses and profit as % of revenue,
                                          latest year (detailed items when the
                                          sheet carries its "נתונים מעזר" block)

The locality-share chart sheet is the loc table's last year divided out, so
it is not read. Profit in the trend is revenue minus expenses: CBS's own
profit column there was not re-priced for the early years (1991's profit is
the same figure in every edition while its revenue moves), and in the loc
table "רווח ותמורה להון" equals revenue minus expenses to rounding.

A table found by title whose labels are gone raises (the layout changed);
a table missing from an edition drops its sections. At least one of loc and
trend must be present.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*[.\-]")
HEB = re.compile("[א-ת]")
BASE = re.compile(r"במחירי(?:\s*בסיס)?\s*((?:19|20)\d\d)")
UNIT = ("מיליוני", "אחוז")
MAX_INSIGHTS = 8
PRIORITY = ("rev", "margin", "low", "struct", "leader", "loc_margin", "recovery", "va")


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows[:12]:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(title):
    if title.startswith("לוח") and "הכנסות" in title and "ישוב" in title:
        return "loc"
    if title.startswith("תרשים") and "כאחוז מההכנסות" in title:
        return "struct"
    if title.startswith("תרשים") and "הכנסות, הוצאות ורווח" in title:
        return "trend"
    return None


def _tables(frames):
    """{kind: (title, rows)}; of two tables of one kind, the lower stem wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        t = _title(rows)
        k = _kind(t)
        if k and k not in out:
            out[k] = (t, rows)
    return out


def _he(r):
    """The row's Hebrew label: its last cell with Hebrew letters."""
    for c in reversed(r):
        if c and HEB.search(c):
            return c
    return ""


# ── parsers ──────────────────────────────────────────────────────────────


def _loc(rows):
    """{measure: {year: {"total": v, locality: v, ...}}}, the locality names
    in table order, and the price base year."""
    h = cbs.row_with(rows, "סך הכל", name="loc")
    ycol = cbs.best_col(rows[h:], lambda v: bool(cbs.YEAR.match(v)))
    if ycol is None:
        raise ValueError("loc: no year column")
    d0 = next((i for i in range(h, len(rows)) if cbs.YEAR.match(cbs.cell(rows[i], ycol))), None)
    if d0 is None:
        raise ValueError("loc: no data row")
    base_m = None
    for r in rows[:d0]:
        for c in r:
            base_m = base_m or BASE.search(c)
    if not base_m:
        raise ValueError("loc: price base year not found")
    heads = {}
    for j in range(ycol):
        parts = [cbs.cell(r, j) for r in rows[h:d0]
                 if cbs.cell(r, j) and not any(u in cbs.cell(r, j) for u in UNIT)]
        txt = " ".join(parts).replace("- ", "-").strip()
        if txt:
            heads[j] = txt
    total = next((j for j, t in heads.items() if t == "סך הכל"), None)
    if total is None:
        raise ValueError("loc: total column not found")
    locs = [(j, t) for j, t in heads.items() if j != total]
    if len(locs) < 3:
        raise ValueError("loc: locality columns not found")
    data, cur = {}, None
    for r in rows[d0:]:
        lab = " ".join(c for c in r[ycol + 1:] if c and HEB.search(c))
        if "אחוז שינוי" in " ".join(r):
            break
        if lab:
            if "תמורה למשרות" in lab:
                cur = "wages"
            elif "ערך מוסף" in lab:
                cur = "va"
            elif "רווח" in lab:
                cur = "profit"
            elif "הכנסות" in lab:
                cur = "rev"
            elif "הוצאות" in lab:
                cur = "exp"
            else:
                cur = None
        y = cbs.cell(r, ycol)
        if cur is None or not cbs.YEAR.match(y) or cbs.val(r, total) is None:
            continue
        row = {"total": cbs.val(r, total)}
        for j, t in locs:
            row[t] = cbs.val(r, j)
        data.setdefault(cur, {})[int(y)] = row
    for need in ("rev", "exp"):
        if need not in data:
            raise ValueError(f"loc: block {need!r} not found")
    return data, [t for _, t in locs], int(base_m.group(1))


def _trend(title, rows):
    """{year: (revenue, expenses)} in NIS million, and the price base year."""
    h = cbs.row_with(rows, "הכנסות", name="trend")
    rc = cbs.col_after(rows[h], "הכנסות")
    ec = cbs.col_after(rows[h], "הוצאות")
    ycol = cbs.best_col(rows[h + 1:], lambda v: bool(cbs.YEAR.match(v)))
    if ycol is None:
        raise ValueError("trend: no year column")
    m = BASE.search(title)
    out = {}
    for r in rows[h + 1:]:
        y = cbs.cell(r, ycol)
        rv, ev = cbs.val(r, rc), cbs.val(r, ec)
        if cbs.YEAR.match(y) and rv is not None and ev is not None:
            out[int(y)] = (rv, ev)
    return out, (int(m.group(1)) if m else None)


def _struct(title, rows):
    """[(label, % of revenue)] (the detailed items when present), the year."""
    def items(a, b):
        out = []
        for r in rows[a:b]:
            lab = _he(r)
            v = next((cbs.num(c) for c in r if cbs.num(c) is not None), None)
            if lab and v is not None and not TITLE.match(lab):
                out.append((lab, v))
        return out

    h = next((i for i, r in enumerate(rows) if any("נתונים מעזר" in c for c in r)), None)
    start = next((i for i, r in enumerate(rows) if any(TITLE.match(c) for c in r)), 0) + 1
    main = items(start, h if h is not None else len(rows))
    detail = items(h + 1, len(rows)) if h is not None else []
    got = detail if len(detail) >= 5 else main
    if not any("רווח" in lab for lab, _ in got) or len(got) < 3:
        raise ValueError("struct: profit / expense items not found")
    years = [int(y) for y in re.findall(r"(?:19|20)\d\d", title)]
    return got, (max(years) if years else None)


# ── formatting ───────────────────────────────────────────────────────────


def _bn(v):
    """NIS million → billions, one decimal."""
    return fmt.num_he(v / 1000, 1)


def _r1(v):
    return None if v is None else round(v, 1)


def _chg(a, b):
    return (b - a) / a if a else None


def _spct(f):
    return fmt.signed_pct(f, 1)


def _short(name):
    return name.replace(" (מערב)", "").replace("קיבוצים ומושבים שיתופיים", "קיבוצים ומושבים")


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    T = _tables(frames)
    if "loc" not in T and "trend" not in T:
        raise ValueError("neither the locality table nor the trend chart was found")
    rel = cbs.latest_release(frames["releases"])
    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(i, text):
        if text:
            insights.append({"id": i, "text_he": text})

    # ── long trend ───────────────────────────────────────────────────────
    tr, tr_base = (_trend(*T["trend"]) if "trend" in T else ({}, None))
    ty = sorted(tr)
    flags["trend"] = len(ty) >= 5
    if flags["trend"]:
        rev = {y: tr[y][0] for y in ty}
        exp = {y: tr[y][1] for y in ty}
        prof = {y: rev[y] - exp[y] for y in ty}
        marg = {y: prof[y] / rev[y] * 100 for y in ty if rev[y]}
        charts["trend"] = {"x": [str(y) for y in ty], "rev": [round(rev[y] / 1000, 2) for y in ty],
                           "exp": [round(exp[y] / 1000, 2) for y in ty],
                           "profit": [round(prof[y] / 1000, 2) for y in ty]}
        charts["margin"] = {"x": [str(y) for y in ty], "y": [_r1(marg.get(y)) for y in ty]}
        tables["trend"] = [[str(y), _bn(rev[y]), _bn(exp[y]), _bn(prof[y]),
                            fmt.pct_of(marg[y], 1) if y in marg else ""] for y in reversed(ty)]
        tables["margin"] = [[str(y), fmt.pct_of(marg[y], 1)] for y in reversed(ty) if y in marg]
        pb = f"במחירי {tr_base}" if tr_base else "במחירים קבועים"
        labels["trend_pb"] = pb
        labels["trend_note"] = (f"הכנסות, הוצאות ורווח מלונות התיירות בכל שנה מאז {ty[0]}, במיליארדי ש\"ח {pb} "
                                f"(בניכוי עליית המחירים, כך שאפשר להשוות בין השנים). הרווח הוא ההכנסות פחות "
                                f"ההוצאות.")
        labels["trend_aria"] = f"הכנסות, הוצאות ורווח מלונות התיירות, {ty[0]} עד {ty[-1]}"
        labels["margin_note"] = (f"איזה חלק מההכנסות נשאר כרווח בכל שנה מאז {ty[0]}, באחוזים. "
                                 f"שיעור הרווח אינו תלוי ברמת המחירים.")
        labels["margin_aria"] = f"שיעור הרווח של מלונות התיירות, {ty[0]} עד {ty[-1]}"

    # ── localities ───────────────────────────────────────────────────────
    loc = None
    if "loc" in T:
        loc, names, base = _loc(T["loc"][1])
    flags["loc"] = loc is not None
    if flags["loc"]:
        ly_all = sorted(loc["rev"])
        ly = ly_all[-1]
        lrev, lexp = loc["rev"][ly], loc["exp"].get(ly)
        if lexp is None:
            raise ValueError(f"loc: no expenses for {ly}")
        good = [n for n in names if lrev.get(n) is not None and lexp.get(n) is not None and lrev[n] > 0]
        rest = lrev["total"] - sum(lrev[n] for n in good)
        order = sorted(good, key=lambda n: (-lrev[n], n))
        charts["loc"] = {"names": [_short(n) for n in order] + (["שאר הארץ"] if rest > 0 else []),
                         "values": [round(lrev[n], 1) for n in order] + ([round(rest, 1)] if rest > 0 else [])}
        tables["loc"] = [[_short(n), fmt.int_he(lrev[n]), fmt.pct(lrev[n] / lrev["total"])] for n in order]
        if rest > 0:
            tables["loc"].append(["שאר הארץ", fmt.int_he(rest), fmt.pct(rest / lrev["total"])])
        labels["loc_cols"] = ["יישוב", f"הכנסות {ly} (מיליוני ש\"ח)", "חלק מסך ההכנסות"]
        labels["loc_note"] = (f"הכנסות מלונות התיירות ב-{ly} לפי יישוב, במיליוני ש\"ח. \"שאר הארץ\" הם המלונות "
                              f"מחוץ ליישובים שהלמ\"ס מפרטת. סך הכל {_bn(lrev['total'])} מיליארד ש\"ח.")
        labels["loc_aria"] = f"הכנסות מלונות התיירות לפי יישוב, {ly}"
        top = order[0]
        sh = lrev[top] / lrev["total"]
        if sh >= 0.15:
            top3 = order[:3]
            s3 = sum(lrev[n] for n in top3) / lrev["total"]
            add("leader", f"המלונות ב{_short(top)} הכניסו {_bn(lrev[top])} מיליארד ש\"ח ב-{ly}, "
                          f"{fmt.pct(sh)} מהכנסות כל מלונות התיירות. יחד עם {fmt.join_he([_short(n) for n in top3[1:]])} "
                          f"מדובר ב-{fmt.pct(s3)} מההכנסות.")

        # margin + wages by locality
        lw = loc.get("wages", {}).get(ly, {})
        mg = {n: (lrev[n] - lexp[n]) / lrev[n] * 100 for n in good}
        morder = sorted(good, key=lambda n: (-mg[n], n))
        tot_m = (lrev["total"] - lexp["total"]) / lrev["total"] * 100
        charts["loc_margin"] = {"names": [_short(n) for n in morder] + ["סך הכל"],
                                "margin": [_r1(mg[n]) for n in morder] + [_r1(tot_m)],
                                "wages": [_r1(lw[n] / lrev[n] * 100) if lw.get(n) is not None else None
                                          for n in morder]
                                + [_r1(lw["total"] / lrev["total"] * 100) if lw.get("total") is not None else None]}
        flags["loc_wages"] = any(v is not None for v in charts["loc_margin"]["wages"])
        tables["loc_margin"] = [[nm, fmt.pct_of(m, 1) if m is not None else "",
                                 fmt.pct_of(w, 1) if w is not None else ""]
                                for nm, m, w in zip(charts["loc_margin"]["names"], charts["loc_margin"]["margin"],
                                                    charts["loc_margin"]["wages"])]
        labels["loc_margin_note"] = (f"איזה חלק מההכנסות נשאר כרווח בכל יישוב ב-{ly}"
                                     + (", ואיזה חלק הלך לשכר העובדים (תמורה למשרות)" if flags["loc_wages"] else "")
                                     + ", באחוזים.")
        labels["loc_margin_aria"] = f"שיעור הרווח של מלונות התיירות לפי יישוב, {ly}"
        hi, lo = morder[0], morder[-1]
        if mg[hi] - mg[lo] >= 8:
            add("loc_margin", f"שיעור הרווח הגבוה ביותר ב-{ly} נרשם ב{_short(hi)}: {fmt.pct_of(mg[hi], 1)} "
                              f"מההכנסות, לעומת {fmt.pct_of(mg[lo], 1)} ב{_short(lo)} ו-{fmt.pct_of(tot_m, 1)} "
                              f"בכלל המלונות.")

        # real change from the first year of the window
        fy = ly_all[0]
        f_rev = loc["rev"][fy]
        ch = {n: _chg(f_rev.get(n), lrev[n]) for n in good if f_rev.get(n)}
        flags["recovery"] = ly > fy and len(ch) >= 3
        if flags["recovery"]:
            corder = sorted(ch, key=lambda n: (-ch[n], n))
            tch = _chg(f_rev["total"], lrev["total"])
            charts["recovery"] = {"names": [_short(n) for n in corder] + ["סך הכל"],
                                  "values": [_r1(ch[n] * 100) for n in corder] + [_r1(tch * 100)]}
            tables["recovery"] = [[_short(n), fmt.int_he(f_rev[n]), fmt.int_he(lrev[n]), _spct(ch[n])]
                                  for n in corder]
            tables["recovery"].append(["סך הכל", fmt.int_he(f_rev["total"]), fmt.int_he(lrev["total"]), _spct(tch)])
            labels["recovery_cols"] = ["יישוב", f"{fy} (מיליוני ש\"ח)", f"{ly} (מיליוני ש\"ח)", "שינוי"]
            labels["recovery_note"] = (f"השינוי בהכנסות המלונות בכל יישוב בין {fy} ל-{ly}, במחירים קבועים "
                                       f"(במחירי {base}), באחוזים.")
            labels["recovery_aria"] = f"שינוי ריאלי בהכנסות המלונות לפי יישוב, {fy} עד {ly}"
            # The pre-crisis year: the last year before the window's deepest single-year fall.
            falls = [(loc["rev"][y]["total"] / loc["rev"][y - 1]["total"], y) for y in ly_all[1:]
                     if y - 1 in loc["rev"] and loc["rev"][y - 1]["total"]]
            if falls:
                ratio, fall_y = min(falls)
                ref = fall_y - 1
                if ratio <= 0.7 and ref < ly - 1:
                    r_rev = loc["rev"][ref]
                    up = sorted(n for n in good if r_rev.get(n) and lrev[n] >= r_rev[n])
                    down = sorted(n for n in good if r_rev.get(n) and lrev[n] < r_rev[n])
                    rt = _chg(r_rev["total"], lrev["total"])
                    txt = (f"הכנסות המלונות ב-{ly} היו {'גבוהות' if rt >= 0 else 'נמוכות'} ב-{fmt.pct(abs(rt))} "
                           f"מאשר ב-{ref}, השנה שלפני הצניחה של {fall_y} (במחירים קבועים). ")
                    if down and up:
                        worst = min(down, key=lambda n: (_chg(r_rev[n], lrev[n]), n))
                        n_up = (f"יישוב אחד מתוך {len(up) + len(down)} עבר" if len(up) == 1
                                else f"{len(up)} מתוך {len(up) + len(down)} היישובים עברו")
                        txt += (f"{n_up} את רמת {ref}, "
                                f"וב{_short(worst)} ההכנסות עדיין נמוכות ממנה ב-{fmt.pct(-_chg(r_rev[worst], lrev[worst]))}.")
                    elif up:
                        txt += f"בכל היישובים המפורטים ההכנסות עברו את רמת {ref}."
                    else:
                        txt += f"באף אחד מהיישובים המפורטים ההכנסות עדיין לא חזרו לרמת {ref}."
                    add("recovery", txt)

        # value added
        va = loc.get("va", {}).get(ly)
        if va and va.get("total") and lw.get("total") is not None:
            add("va", f"הערך המוסף הגולמי של מלונות התיירות היה {_bn(va['total'])} מיליארד ש\"ח ב-{ly}, "
                      f"{fmt.pct(va['total'] / lrev['total'])} מההכנסות. מתוכו {_bn(lw['total'])} מיליארד ש\"ח "
                      f"שולמו כשכר לעובדים.")

        # locality trend lines
        sel = order[:6]
        charts["loc_trend"] = {"x": [str(y) for y in ly_all], "names": [_short(n) for n in sel],
                               "series": [[_r1(loc["rev"][y].get(n)) for y in ly_all] for n in sel]}
        tables["loc_trend"] = [[str(y)] + [fmt.int_he(loc["rev"][y][n]) if loc["rev"][y].get(n) is not None else ""
                                           for n in sel] for y in ly_all]
        labels["loc_trend_cols"] = ["שנה"] + [_short(n) for n in sel]
        labels["loc_trend_note"] = (f"הכנסות המלונות ב{len(sel)} היישובים המובילים בכל שנה בין {fy} ל-{ly}, "
                                    f"במיליוני ש\"ח במחירי {base}.")
        labels["loc_trend_aria"] = f"הכנסות המלונות לפי יישוב, {fy} עד {ly}"

    # ── expense structure ────────────────────────────────────────────────
    st, sy = (_struct(*T["struct"]) if "struct" in T else ([], None))
    flags["struct"] = len(st) >= 3
    if flags["struct"]:
        so = sorted(st, key=lambda t: (-t[1], t[0]))
        charts["struct"] = {"names": [n for n, _ in so], "values": [_r1(v) for _, v in so],
                            "profit": ["רווח" in n for n, _ in so]}
        tables["struct"] = [[n, fmt.pct_of(v, 1)] for n, v in so]
        sy_txt = f" ב-{sy}" if sy else ""
        labels["struct_note"] = (f"לאן הולך כל שקל שהמלונות מכניסים{sy_txt}: כל סוג הוצאה, והרווח שנשאר, "
                                 f"כאחוז מסך ההכנסות.")
        labels["struct_aria"] = f"הוצאות ורווח מלונות התיירות כאחוז מההכנסות{sy_txt}"
        exps = [t for t in so if "רווח" not in t[0]]
        big = exps[0]
        if big[1] >= 20:
            add("struct", f"ההוצאה הגדולה של המלונות היא {big[0]}: {fmt.pct_of(big[1], 1)} מההכנסות{sy_txt}, "
                          f"יותר מ{exps[1][0]} ({fmt.pct_of(exps[1][1], 1)})"
                          + (f" ומ{exps[2][0]} ({fmt.pct_of(exps[2][1], 1)})" if len(exps) >= 3 else "") + ".")
            kpis["wages"] = {"value": round(big[1], 1), "display": fmt.pct_of(big[1], 1), "tone": "brand"}
            labels["wages_kpi"] = f"{big[0]} כאחוז מההכנסות{sy_txt}"

    # ── headline numbers (trend first, else the loc table) ──────────────
    if flags["trend"]:
        src = {y: (rev[y], exp[y]) for y in ty}
        pb_txt = labels["trend_pb"]
    else:
        src = {y: (loc["rev"][y]["total"], loc["exp"][y]["total"]) for y in sorted(loc["rev"]) if y in loc["exp"]}
        pb_txt = f"במחירי {base}"
    sy_all = sorted(src)
    y1 = sy_all[-1]
    r1, e1 = src[y1]
    p1 = r1 - e1
    m1 = p1 / r1 * 100
    kpis["rev"] = {"value": round(r1 / 1000, 1), "display": _bn(r1), "tone": "brand"}
    kpis["profit"] = {"value": round(p1 / 1000, 1), "display": _bn(p1), "tone": "ok" if p1 > 0 else "danger"}
    labels["rev_kpi"] = f"הכנסות המלונות ב-{y1} (מיליארדי ש\"ח)"
    labels["profit_kpi"] = f"רווח המלונות ב-{y1} (מיליארדי ש\"ח)"
    prev = y1 - 1 if y1 - 1 in src else None
    m0 = None
    if prev:
        r0, e0 = src[prev]
        rc = _chg(r0, r1)
        m0 = (r0 - e0) / r0 * 100
        kpis["revchg"] = {"value": round(rc * 100, 1), "display": _spct(rc),
                          "tone": "ok" if rc > 0.02 else ("danger" if rc < -0.1 else "warn")}
        labels["revchg_kpi"] = f"שינוי ריאלי בהכנסות לעומת {prev}"
        add("rev", f"הכנסות מלונות התיירות הסתכמו ב-{_bn(r1)} מיליארד ש\"ח ב-{y1} ({pb_txt}), "
                   f"{'עלייה' if rc > 0 else 'ירידה'} ריאלית של {fmt.pct(abs(rc))} לעומת {prev}. "
                   f"ההוצאות {'עלו' if e1 > e0 else 'ירדו'} ב-{fmt.pct(abs(_chg(e0, e1)))}, והרווח הגיע ל-{_bn(p1)} "
                   f"מיליארד ש\"ח.")
    kpis["margin"] = {"value": round(m1, 1), "display": fmt.pct_of(m1, 1),
                      "tone": ("ok" if m0 is None or m1 >= m0 else "warn") if m1 > 0 else "danger"}
    labels["margin_kpi"] = f"שיעור הרווח מההכנסות, {y1}"

    if flags["trend"] and len(ty) >= 10:
        best = max(ty, key=lambda y: (marg[y], y))
        prior = [marg[y] for y in ty if y < y1]
        if best == y1 and prior:
            add("margin", f"שיעור הרווח של {fmt.pct_of(m1, 1)} מההכנסות ב-{y1} הוא הגבוה ביותר מאז {ty[0]}. "
                          f"הממוצע בכל התקופה: {fmt.pct_of(sum(marg.values()) / len(marg), 1)}.")
        else:
            add("margin", f"ב-{y1} נשארו {fmt.pct_of(m1, 1)} מההכנסות כרווח. השיא בתקופה נרשם ב-{best} "
                          f"({fmt.pct_of(marg[best], 1)}), והממוצע מאז {ty[0]} הוא "
                          f"{fmt.pct_of(sum(marg.values()) / len(marg), 1)}.")
        falls = [(rev[y] / rev[y - 1], y) for y in ty[1:] if y - 1 in rev and rev[y - 1]]
        worst = sorted(falls)[:2]
        if worst and worst[0][0] <= 0.85:
            (a, ya) = worst[0]
            txt = f"השנה הקשה ביותר בתקופה הייתה {ya}: ההכנסות ירדו ב-{fmt.pct(1 - a)} לעומת השנה הקודמת"
            if ya - 1 in marg and marg[ya] < marg[ya - 1]:
                txt += f", ושיעור הרווח ירד ל-{fmt.pct_of(marg[ya], 1)}"
            else:
                txt += f", ושיעור הרווח היה {fmt.pct_of(marg[ya], 1)}"
            if len(worst) > 1 and worst[1][0] <= 0.85:
                txt += f". הירידה השנייה בגודלה הייתה ב-{worst[1][1]} ({fmt.pct(1 - worst[1][0])})"
            add("low", txt + ".")

    if len(insights) < 3:
        raise ValueError("too few insights")

    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_INSIGHTS]

    release = {"title": rel["TITLE"], "headline": rel["HEADLINE"], "url": rel["PAGE_URL"],
               "pdf": rel["REPORT_PDF_URL"], "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    head = f"{_bn(r1)} מיליארד ש\"ח הכנסות ו-{_bn(p1)} מיליארד ש\"ח רווח ב-{y1}"
    labels["lede"] = (f"כמה מרוויחים מלונות התיירות בישראל, על מה הם מוציאים ואיפה הרווח גבוה יותר. "
                      f"הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על הכנסות, הוצאות "
                      f"ורווח המלונות, שמבוססת על הדוחות הכספיים של המלונות ומתפרסמת באיחור של כשנתיים וחצי. "
                      f"בשורה התחתונה: {head}, שיעור רווח של {fmt.pct_of(m1, 1)}.")
    summary = (f"הכנסות, הוצאות ורווח מלונות התיירות בישראל לפי הלמ\"ס: {head} "
               f"({fmt.pct_of(m1, 1)} מההכנסות), לפי יישוב ולפי סוג הוצאה.")
    desc = (f"כמה מרוויחים מלונות התיירות בישראל: {head}. "
            f"מבנה ההוצאות, שכר ורווח לפי יישוב.")
    first = min(sy_all[0], ty[0] if flags["trend"] else sy_all[0])
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first}/{y1}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "הכנסות, הוצאות ורווח מלונות התיירות | נתוני הלמ\"ס",
                "description": desc,
                "name": "הכנסות, הוצאות ורווח מלונות התיירות",
                "alternate_names": ["רווחיות בתי המלון בישראל", "רווח מלונות התיירות",
                                    "הכנסות בתי המלון", "שיעור הרווח של המלונות"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
