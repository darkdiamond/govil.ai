"""יצוא סחורות לפי ענף כלכלי וארצות: CBS's yearly goods-exports release.

Each edition has one table per destination ("לוח N. - יצוא, לפי ענף כלכלי -
ענפים ראשיים - <destination>"): total, Europe, EU, America, USA, Asia, China,
the "other countries" group. Each holds the economic divisions (ISIC codes)
as rows and three blocks of four years: percent of the destination's
exports, a value index (2020=100) and million dollars. One more table
(currently t1) is the latest year as a division × continent cross-tab: it
repeats the per-destination tables' latest year, so it is recognised and
skipped.

Tables are matched by their TITLE (the destination after "ענפים ראשיים -"),
never by stem: CBS renumbers tables between editions, so t1..t9 plus three
spare stems are all optional. The total table is required; a missing
destination drops from the charts. A recognised table whose header labels
(the "Million $" block, the year row, the industry label column) are gone
raises: the layout changed and a human should look.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^לוח\s*\d+[א-ת]?\.?\s*-\s*(.+)$")
HEB = re.compile("[א-ת]")
BASE = re.compile(r"^((?:19|20)\d\d)\s*=\s*100$")
CODE = re.compile(r"^(?:\d{1,2}|[A-Z])$")
TOTAL_LABEL = "יצוא ברוטו"
TOTAL_DEST = "סך כולל"
# Continents (they partition the total) and the sub-destination each holds.
CONTINENTS = ("אירופה", "אמריקה", "אסיה", "יתר ארצות")
SUBS = {"האיחוד האירופי": "אירופה", "ארצות הברית": "אמריקה", "סין": "אסיה"}
DEST_ALIAS = {"קבוצת יתר ארצות": "יתר ארצות", "יתר הארצות": "יתר ארצות"}
OTHER = "אחר"
PRIORITY = ("total", "leader", "top_share", "decline", "rise", "conc", "conc2", "sub",
            "index", "agri")
MAX_TOP = 8


# ── locating tables ──────────────────────────────────────────────────────


def _dest(rows):
    """The destination named in a table's Hebrew title, or None."""
    for r in rows[:6]:
        for c in r:
            m = TITLE.match(c)
            if m and "ענף" in c:
                tail = m.group(1)
                if "ענפים ראשיים" not in tail:
                    continue
                d = tail.split("ענפים ראשיים", 1)[1].strip(" -")
                d = re.sub(r"\s*-\s*(?:19|20)\d\d$", "", d).strip()
                return DEST_ALIAS.get(d, d)
    return None


def _is_cross(rows):
    """The latest-year cross-tab: a header row naming several continents."""
    return any(sum(1 for c in r if c in ("אירופה", "אמריקה", "אסיה")) >= 2 for r in rows[:10])


def _tables(frames):
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    out = {}
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        d = _dest(rows)
        if not d or _is_cross(rows) or d in out:
            continue
        out[d] = _series(rows, d)
    return out


# ── parsing one destination table ────────────────────────────────────────


def _block(row, start_label, end_label, name):
    a = cbs.col_after(row, start_label, 0)
    b = cbs.col_after(row, end_label, a)
    return a, b


def _series(rows, name):
    h = cbs.row_with(rows, "מיליוני דולרים", name=name)
    a, b = _block(rows[h], "Million $", "מיליוני דולרים", name)
    yr = next((i for i in range(h, min(h + 4, len(rows)))
               if sum(1 for j in range(a, b + 1) if cbs.YEAR.match(cbs.cell(rows[i], j))) >= 2), None)
    if yr is None:
        raise ValueError(f"{name}: year row of the Million $ block not found")
    ycols = sorted((int(rows[yr][j]), j) for j in range(a, b + 1) if cbs.YEAR.match(rows[yr][j]))
    lab = cbs.col_after(rows[yr], "ענף משנה", 0)
    code = next((j for j, c in enumerate(rows[yr]) if c.startswith("סמל")), None)
    # Value index block (optional): its base year and its newest-year column.
    idx = None
    try:
        ia, ib = _block(rows[h], "Value Index", "מדד ערך", name)
        base = next((int(BASE.match(c).group(1)) for c in rows[h] if BASE.match(c)), None)
        icols = sorted((int(rows[yr][j]), j) for j in range(ia, ib + 1) if cbs.YEAR.match(rows[yr][j]))
        if base and icols:
            idx = (base, icols)
    except ValueError:
        idx = None
    years = [y for y, _ in ycols]
    total = None
    items = []          # (code, label, [values by year], index_latest)
    pending = None      # a coded row whose values sit on the next (wrapped) row
    for r in rows[yr + 1:]:
        label = cbs.cell(r, lab)
        if not label or not HEB.search(label):
            continue
        c = cbs.cell(r, code) if code is not None else ""
        vals = [cbs.val(r, j) for _, j in ycols]
        has = any(v is not None for v in vals)
        ix = cbs.val(r, idx[1][-1][1]) if idx else None
        if label == TOTAL_LABEL:
            if has:
                total = (vals, ix)
            continue
        if label.startswith(("(", "הלשכה")):
            continue
        if not has:
            pending = (c, label) if CODE.match(c) else None
            continue
        if not c and pending:
            c, label = pending
        pending = None
        items.append((c if CODE.match(c) else "", label, vals, ix))
    if total is None:
        raise ValueError(f"{name}: gross-exports row ({TOTAL_LABEL}) not found")
    return {"years": years, "total": total[0], "total_index": total[1], "items": items,
            "base": idx[0] if idx else None, "index_year": idx[1][-1][0] if idx else None}


# ── helpers ──────────────────────────────────────────────────────────────


def _short(label):
    s = label.rstrip(";").strip()
    for p in ("ייצור ועיבוד של ", "ייצור "):
        if s.startswith(p):
            s = s[len(p):]
            break
    s = re.sub(r",\s*פרט ל.*$", "", s)
    s = s.replace("לנמ\"א", "").strip()
    s = re.sub(r"\s+לבני אדם.*$", "", s).strip()
    return s or label


def _partition(items):
    """Sections A/B (agriculture, mining), C's divisions, and the uncoded
    'other exports' row: together they make up the gross total."""
    out = []
    for c, label, vals, ix in items:
        if c in ("A", "B") or c.isdigit() and 10 <= int(c) <= 39 or not c:
            out.append((c, label, vals, ix))
    return out


def _bn(v):
    return fmt.num_he(v / 1000, 1)


def _m(v):
    return fmt.int_he(v)


def _chg_phrase(c):
    """'עלייה של 3.1%' / 'ירידה של …', or 'ללא שינוי' when it rounds to zero."""
    if abs(c) < 0.0005:
        return "ללא שינוי"
    return f"{'עלייה' if c > 0 else 'ירידה'} של {fmt.pct(abs(c))}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _r1(v):
    return None if v is None else round(v, 1)


def _plural(dest):
    return dest.startswith("יתר")


def _she(dest):
    """'היא' / 'הן' for a destination name."""
    return "הן" if _plural(dest) else "היא"


def _in(dest):
    """'לאירופה', 'לארצות הברית', 'לאיחוד האירופי' (the article folds in)."""
    return "ל" + dest.removeprefix("ה")


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if TOTAL_DEST not in tabs:
        raise ValueError("total table (ענפים ראשיים - סך כולל) not found in any table")
    T = tabs[TOTAL_DEST]
    years = T["years"]
    ly, fy = years[-1], years[0]
    n = len(years)
    tot = T["total"]
    if tot[-1] is None:
        raise ValueError("total: no gross exports in the latest year")

    conts = [c for c in CONTINENTS if c in tabs and tabs[c]["years"] == years]
    subs = [s for s in SUBS if s in tabs and tabs[s]["years"] == years]
    others = [d for d in tabs if d not in CONTINENTS and d not in SUBS and d != TOTAL_DEST
              and tabs[d]["years"] == years]
    dests = conts + subs + sorted(others)

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    span = f"{fy} עד {ly}"

    # ── total + continents by year ───────────────────────────────────────
    cont_v = {c: tabs[c]["total"] for c in conts}
    charts["trend"] = {"x": [str(y) for y in years], "total": [_r1(v / 1000) if v else None for v in tot],
                       "names": conts,
                       "series": [[_r1(v / 1000) if v is not None else None for v in cont_v[c]] for c in conts]}
    tables["trend"] = [[str(years[k])] + [_m(cont_v[c][k]) if cont_v[c][k] is not None else "" for c in conts]
                       + [_m(tot[k]) if tot[k] is not None else ""] for k in reversed(range(n))]
    labels["trend_cols"] = ["שנה"] + conts + ["סך הכל"]
    labels["trend_note"] = (f"יצוא הסחורות של ישראל בכל שנה, {span}, במיליארדי דולרים, "
                            f"מחולק לפי יבשת היעד.")
    labels["trend_aria"] = f"יצוא סחורות לפי יבשת יעד, {span}"
    yoy = _chg(tot[-1], tot[-2]) if n >= 2 else None
    kpis["total"] = {"value": round(tot[-1] / 1000, 1), "display": _bn(tot[-1]), "tone": "brand"}
    labels["total_kpi"] = f"יצוא סחורות, מיליארדי דולרים, {ly}"
    if yoy is not None:
        kpis["yoy"] = {"value": round(yoy * 100, 1), "display": fmt.signed_pct(yoy),
                       "tone": "ok" if yoy >= 0.01 else "danger" if yoy <= -0.01 else "brand"}
        labels["yoy_kpi"] = f"שינוי לעומת {years[-2]}"
        peak = max(range(n), key=lambda k: (tot[k] or 0, k))
        txt = (f"יצוא הסחורות הסתכם ב-{_bn(tot[-1])} מיליארד דולר ב-{ly}, "
               f"{_chg_phrase(yoy)} לעומת {years[-2]}")
        if peak != n - 1 and tot[peak] and tot[-1] < tot[peak] * 0.95:
            txt += (f". זו רמה נמוכה ב-{fmt.pct(1 - tot[-1] / tot[peak], 0)} מהשיא של "
                    f"{years[peak]} ({_bn(tot[peak])} מיליארד דולר)")
        add("total", txt + ".")

    if T["base"] and T["total_index"]:
        g = T["total_index"] / 100 - 1
        kpis["since_base"] = {"value": round(g * 100, 1), "display": fmt.signed_pct(g),
                              "tone": "ok" if g >= 0.01 else "danger" if g <= -0.01 else "brand"}
        labels["since_base_kpi"] = f"שינוי לעומת {T['base']} (מדד ערך)"

    # Largest continent, and a change of leader.
    if len(conts) >= 2:
        lead = max(conts, key=lambda c: (cont_v[c][-1] or 0, c))
        share = cont_v[lead][-1] / tot[-1]
        kpis["lead"] = {"value": round(share * 100, 1), "display": fmt.pct(share), "tone": "info"}
        labels["lead_kpi"] = f"חלקה של {lead}, יעד היצוא הגדול, {ly}"
        txt = f"{lead} {_she(lead)} יעד היצוא הגדול ב-{ly}: {_bn(cont_v[lead][-1])} מיליארד דולר, {fmt.pct(share)} מהיצוא"
        if n >= 2:
            prev = max(conts, key=lambda c: (cont_v[c][-2] or 0, c))
            if prev != lead:
                txt += (f". {lead} {'עקפו' if _plural(lead) else 'עקפה'} את {prev}, "
                        f"{'שהובילו' if _plural(prev) else 'שהובילה'} ב-{years[-2]} "
                        f"{'והגיעו' if _plural(prev) else 'והגיעה'} ב-{ly} ל-{_bn(cont_v[prev][-1])} "
                        f"מיליארד דולר")
        add("leader", txt + ".")

    # ── destinations: first year vs latest ───────────────────────────────
    flags["dest"] = len(dests) >= 2
    if flags["dest"]:
        dv = {d: tabs[d]["total"] for d in dests}
        order = sorted(dests, key=lambda d: (-(dv[d][-1] or 0), d))
        charts["dest"] = {"names": order, "years": [str(fy), str(ly)],
                          "first": [_r1(dv[d][0] / 1000) if dv[d][0] is not None else None for d in order],
                          "last": [_r1(dv[d][-1] / 1000) if dv[d][-1] is not None else None for d in order]}
        tables["dest"] = []
        for d in order:
            c = _chg(dv[d][-1], dv[d][0])
            tables["dest"].append([d] + [_m(v) if v is not None else "" for v in dv[d]]
                                  + [fmt.signed_pct(c) if c is not None else ""])
        labels["dest_cols"] = ["יעד"] + [str(y) for y in years] + [f"שינוי {fy}-{ly}"]
        labels["dest_note"] = (f"היצוא לכל יבשת ולשלושה יעדים בתוכן (האיחוד האירופי, ארצות הברית "
                               f"וסין), {fy} מול {ly}, במיליארדי דולרים. בטבלה כל השנים, במיליוני דולרים.")
        labels["dest_aria"] = f"יצוא סחורות לפי יעד, {fy} ו-{ly}"
        moves = [(d, _chg(dv[d][-1], dv[d][0])) for d in subs]
        moves = [(d, c) for d, c in moves if c is not None]
        if moves:
            d, c = max(moves, key=lambda dc: (abs(dc[1]), dc[0]))
            if abs(c) >= 0.15:
                add("sub", f"היצוא {_in(d)} {'עלה' if c > 0 else 'ירד'} ב-{fmt.pct(abs(c), 0)} בין {fy} ל-{ly}, "
                           f"מ-{_bn(dv[d][0])} ל-{_bn(dv[d][-1])} מיליארד דולר.")

    # ── growth since the index base year, by destination ─────────────────
    idx_d = [(d, tabs[d]["total_index"]) for d in [TOTAL_DEST] + dests
             if tabs[d]["total_index"] is not None and tabs[d]["base"] == T["base"]]
    flags["index"] = bool(T["base"]) and len(idx_d) >= 3
    if flags["index"]:
        idx_d.sort(key=lambda dv_: (-dv_[1], dv_[0]))
        b = T["base"]
        charts["index"] = {"names": [d if d != TOTAL_DEST else "סך כל היצוא" for d, _ in idx_d],
                           "values": [_r1(v - 100) for _, v in idx_d],
                           "total": TOTAL_DEST}
        tables["index"] = [[d if d != TOTAL_DEST else "סך כל היצוא", fmt.num_he(v, 1), fmt.signed_pct(v / 100 - 1)]
                           for d, v in idx_d]
        labels["index_cols"] = ["יעד", f"מדד ערך ({b}=100)", f"שינוי מאז {b}"]
        labels["index_note"] = (f"בכמה השתנה ערך היצוא לכל יעד בין {b} ל-{T['index_year']}, "
                                f"לפי מדד הערך של הלמ\"ס ({b}=100). ערך בדולרים, לא כמות.")
        labels["index_aria"] = f"שינוי ערך היצוא לפי יעד, {b} עד {T['index_year']}"
        top_d = [(d, v) for d, v in idx_d if d != TOTAL_DEST]
        if top_d:
            hi, lo = top_d[0], top_d[-1]
            if hi[1] - lo[1] >= 20:
                def moved(v, only=""):
                    """Verb by the index's side of 100 (it can be below 100 for
                    the top destination too, when every destination shrank)."""
                    g = v / 100 - 1
                    if fmt.pct(abs(g), 0) == fmt.pct(0, 0):
                        return "כמעט לא השתנה"
                    return (f"גדל{only} ב-{fmt.pct(g, 0)}" if g > 0
                            else f"ירד ב-{fmt.pct(-g, 0)}")
                add("index", f"מאז {b} היצוא {_in(hi[0])} {moved(hi[1])}"
                             + f", ואילו היצוא {_in(lo[0])} {moved(lo[1], ' רק')}"
                             + f" (ערך בדולרים, {b} עד {T['index_year']}).")

    # ── industries (latest year) ─────────────────────────────────────────
    part = _partition(T["items"])
    ind = {}
    for c, label, vals, ix in part:
        key = c or label
        if key not in ind:
            ind[key] = {"label": _short(label) if c else label, "vals": vals}
    keys = sorted(ind, key=lambda k: (-(ind[k]["vals"][-1] or 0), k))
    keys = [k for k in keys if ind[k]["vals"][-1]]
    if len(keys) < 3:
        raise ValueError("total: fewer than three industries with exports in the latest year")
    # Named industries (a section or division code); the uncoded "other
    # exports" row only counts in the ranking and the totals.
    ckeys = [k for k in keys if CODE.match(k)]
    if len(ckeys) < 3:
        raise ValueError("total: fewer than three coded industries in the latest year")
    TOPN = 12
    top = keys[:TOPN]
    rest = tot[-1] - sum(ind[k]["vals"][-1] for k in top)
    bars = [(ind[k]["label"], ind[k]["vals"][-1]) for k in top] + ([(OTHER, rest)] if rest > 0.05 else [])
    charts["ind"] = {"names": [nm for nm, _ in bars], "values": [round(v) for _, v in bars]}
    tables["ind"] = [[nm, _m(v), fmt.pct(v / tot[-1])] for nm, v in bars]
    labels["ind_note"] = (f"היצוא של {len(top)} הענפים הגדולים ב-{ly}, במיליוני דולרים. "
                          f"ענפי התעשייה לפי הסיווג האחיד של ענפי הכלכלה, וחקלאות וכרייה כענף אחד כל אחת"
                          + (". השאר ב\"אחר\"." if rest > 0.05 else "."))
    labels["ind_aria"] = f"יצוא סחורות לפי ענף כלכלי, {ly}"
    k0 = ckeys[0]
    s1 = ind[k0]["vals"][-1] / tot[-1]
    kpis["top_share"] = {"value": round(s1 * 100, 1), "display": fmt.pct(s1), "tone": "info"}
    labels["top_share_kpi"] = f"חלק ענף {ind[k0]['label']} מהיצוא, {ly}"
    if n >= 2 and ind[k0]["vals"][0] and tot[0]:
        s0 = ind[k0]["vals"][0] / tot[0]
        if abs(s1 - s0) >= 0.02:
            add("top_share", f"ענף {ind[k0]['label']} הוא הענף המייצא הגדול: {_bn(ind[k0]['vals'][-1])} מיליארד "
                             f"דולר ב-{ly}, {fmt.pct(s1)} מהיצוא, לעומת {fmt.pct(s0)} ב-{fy}.")

    # ── change by industry, first year → latest ──────────────────────────
    big = [k for k in ckeys if ind[k]["vals"][0] and (ind[k]["vals"][0] >= tot[0] * 0.01
                                                    or ind[k]["vals"][-1] >= tot[-1] * 0.01)]
    flags["chg"] = n >= 2 and len(big) >= 3
    if flags["chg"]:
        ch = sorted(((k, _chg(ind[k]["vals"][-1], ind[k]["vals"][0])) for k in big), key=lambda kc: (kc[1], kc[0]))
        charts["chg"] = {"names": [ind[k]["label"] for k, _ in ch], "values": [_r1(c * 100) for _, c in ch]}
        tables["chg"] = [[ind[k]["label"], _m(ind[k]["vals"][0]), _m(ind[k]["vals"][-1]), fmt.signed_pct(c)]
                         for k, c in reversed(ch)]
        labels["chg_cols"] = ["ענף", str(fy), str(ly), "שינוי"]
        labels["chg_note"] = (f"בכמה אחוזים השתנה היצוא של כל ענף בין {fy} ל-{ly}. מוצגים הענפים "
                              f"ששיעורם מהיצוא הוא אחוז אחד לפחות.")
        labels["chg_aria"] = f"שינוי היצוא לפי ענף, {fy} עד {ly}"
        dk, dc = ch[0]
        if dc <= -0.25 and ind[dk]["vals"][0] >= 500:
            add("decline", f"הירידה החדה ביותר: יצוא ענף {ind[dk]['label']} צנח ב-{fmt.pct(abs(dc), 0)}, מ-"
                           f"{_bn(ind[dk]['vals'][0])} מיליארד דולר ב-{fy} ל-{_bn(ind[dk]['vals'][-1])} ב-{ly}.")
        rises = [(k, ind[k]["vals"][-1] - ind[k]["vals"][0]) for k in big if k != k0]
        rk, rv = max(rises, key=lambda kv: (kv[1], kv[0]))
        if rv >= 300:
            add("rise", f"הגידול הגדול ביותר בדולרים: יצוא ענף {ind[rk]['label']} עלה ב-{_m(rv)} מיליון דולר "
                        f"בין {fy} ל-{ly}, ל-{_bn(ind[rk]['vals'][-1])} מיליארד דולר.")

    # ── share of the leading industries over time ────────────────────────
    flags["share"] = n >= 3
    if flags["share"]:
        sk = ckeys[:5]
        charts["share"] = {"x": [str(y) for y in years], "names": [ind[k]["label"] for k in sk],
                           "series": [[_r1(ind[k]["vals"][j] / tot[j] * 100) if ind[k]["vals"][j] is not None
                                       and tot[j] else None for j in range(n)] for k in sk]}
        tables["share"] = [[ind[k]["label"]] + [fmt.pct(ind[k]["vals"][j] / tot[j]) if ind[k]["vals"][j] is not None
                                                and tot[j] else "" for j in range(n)] for k in sk]
        labels["share_cols"] = ["ענף"] + [str(y) for y in years]
        labels["share_note"] = f"החלק של חמשת הענפים הגדולים מכלל יצוא הסחורות בכל שנה, {span}, באחוזים."
        labels["share_aria"] = f"חלק הענפים המובילים מהיצוא, {span}"

    # ── industry × continent ─────────────────────────────────────────────
    flags["heat"] = len(conts) >= 2
    if flags["heat"]:
        cmap = {}
        for c in conts:
            m = {}
            for code, label, vals, ix in _partition(tabs[c]["items"]):
                m.setdefault(code or label, vals[-1])
            cmap[c] = m
        hk = ckeys[:10]
        cells, trows = [], []
        for i, k in enumerate(hk):
            tv = ind[k]["vals"][-1]
            row = [ind[k]["label"]]
            for j, c in enumerate(conts):
                v = cmap[c].get(k)
                sh = v / tv * 100 if v is not None and tv else None
                if sh is not None:
                    cells.append([j, i, round(sh, 1), round(v)])
                row.append(f"{_m(v)} ({fmt.pct_of(sh)})" if sh is not None else "")
            trows.append(row)
        charts["heat"] = {"x": conts, "y": [ind[k]["label"] for k in hk], "cells": cells}
        tables["heat"] = trows
        labels["heat_cols"] = ["ענף"] + conts
        labels["heat_note"] = (f"לאן הולך היצוא של כל אחד מעשרת הענפים הגדולים ב-{ly}: החלק של כל יבשת "
                               f"מהיצוא של הענף. בטבלה גם הסכום במיליוני דולרים.")
        labels["heat_aria"] = f"יצוא לפי ענף ויבשת יעד, {ly}"
        # Concentration: an industry whose exports lean on one continent far
        # more than exports overall do.
        overall = {c: (cont_v[c][-1] or 0) / tot[-1] for c in conts}
        cand = []
        for k in hk:
            tv = ind[k]["vals"][-1]
            if not tv or tv < tot[-1] * 0.02:
                continue
            for c in conts:
                v = cmap[c].get(k)
                if v is None:
                    continue
                sh = v / tv
                if sh >= 0.5 and sh - overall[c] >= 0.2:
                    cand.append((sh - overall[c], k, c, sh))
        cand.sort(key=lambda t: (-t[0], t[1], t[2]))
        seen = set()
        for iid in ("conc", "conc2"):
            pick = next((t for t in cand if t[2] not in seen), None)
            if not pick:
                break
            _, k, c, sh = pick
            seen.add(c)
            add(iid, f"{fmt.pct(sh, 0)} מיצוא ענף {ind[k]['label']} ב-{ly} הלך {_in(c)} "
                     f"({_m(cmap[c][k])} מיליון דולר), אף {'שהן קולטות' if _plural(c) else 'שהיא קולטת'} רק {fmt.pct(overall[c], 0)} מכלל היצוא.")
        ag = ind.get("A")
        if ag and ag["vals"][-1] and all(t[1] != "A" for t in cand[:2]):
            c = max(conts, key=lambda c_: (cmap[c_].get("A") or 0, c_))
            sh = (cmap[c].get("A") or 0) / ag["vals"][-1]
            if sh >= 0.5:
                add("agri", f"{fmt.pct(sh, 0)} מהיצוא החקלאי ב-{ly} הלך {_in(c)}: "
                            f"{_m(cmap[c]['A'])} מתוך {_m(ag['vals'][-1])} מיליון דולר.")

    # ── what each destination buys ───────────────────────────────────────
    flags["mix"] = len(dests) >= 2
    if flags["mix"]:
        mk = ckeys[:6]
        rows_ = [(TOTAL_DEST, T)] + [(d, tabs[d]) for d in dests]
        series, trows = [], []
        for k in mk:
            series.append([])
        other_s = []
        for d, tb in rows_:
            m = {}
            for code, label, vals, ix in _partition(tb["items"]):
                m.setdefault(code or label, vals[-1])
            dt = tb["total"][-1]
            shares = [(m.get(k) or 0) / dt * 100 if dt else 0 for k in mk]
            for s, sh in zip(series, shares):
                s.append(round(sh, 1))
            other_s.append(round(max(0.0, 100 - sum(shares)), 1))
            trows.append([d] + [fmt.pct_of(sh) for sh in shares] + [fmt.pct_of(max(0.0, 100 - sum(shares)))])
        charts["mix"] = {"names": [d for d, _ in rows_], "inds": [ind[k]["label"] for k in mk] + [OTHER],
                         "series": series + [other_s]}
        tables["mix"] = trows
        labels["mix_cols"] = ["יעד"] + [ind[k]["label"] for k in mk] + [OTHER]
        labels["mix_note"] = (f"מה קונה כל יעד: החלק של ששת הענפים הגדולים מהיצוא לכל יעד ב-{ly}, "
                              f"באחוזים. כל שורה מסתכמת במאה.")
        labels["mix_aria"] = f"הרכב היצוא לכל יעד לפי ענף, {ly}"

    # ── sub-destinations' share of their continent ───────────────────────
    sp = [s for s in subs if SUBS[s] in conts]
    flags["subs"] = n >= 2 and bool(sp)
    if flags["subs"]:
        charts["subs"] = {"x": [str(y) for y in years],
                          "names": [f"{s} מתוך {SUBS[s]}" for s in sp],
                          "series": [[_r1(tabs[s]["total"][j] / cont_v[SUBS[s]][j] * 100)
                                      if tabs[s]["total"][j] is not None and cont_v[SUBS[s]][j] else None
                                      for j in range(n)] for s in sp]}
        tables["subs"] = [[f"{s} מתוך {SUBS[s]}"] + [fmt.pct(tabs[s]["total"][j] / cont_v[SUBS[s]][j])
                                                    if tabs[s]["total"][j] is not None and cont_v[SUBS[s]][j]
                                                    else "" for j in range(n)] for s in sp]
        labels["subs_cols"] = ["יעד"] + [str(y) for y in years]
        labels["subs_note"] = (f"איזה חלק מהיצוא לכל יבשת הולך ליעד הגדול בה, {span}, באחוזים.")
        labels["subs_aria"] = f"חלק האיחוד האירופי, ארצות הברית וסין מהיצוא ליבשתם, {span}"

    # ── insights card + callouts ─────────────────────────────────────────
    by_id = {i["id"]: i for i in insights}
    top_i = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    lead_txt = ""
    if len(conts) >= 2:
        lead = max(conts, key=lambda c: (cont_v[c][-1] or 0, c))
        lead_txt = f" היעד הגדול: {lead}, והענף המייצא הגדול: {ind[k0]['label']}."
    labels["lede"] = (f"לאן מייצאת ישראל סחורות, ומה כל ענף מוכר לכל יבשת. הנתונים מתוך ההודעה השנתית של "
                      f"הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על יצוא סחורות לפי ענף כלכלי וארצות, ומתעדכנים עם "
                      f"כל הודעה חדשה. ב-{ly} הסתכם יצוא הסחורות ב-{_bn(tot[-1])} מיליארד דולר."
                      + lead_txt)
    summary = (f"יצוא הסחורות של ישראל לפי ענף ויעד, לפי נתוני הלמ\"ס: {_bn(tot[-1])} מיליארד דולר ב-{ly}, "
               f"מהם {fmt.pct(s1)} בענף {ind[k0]['label']}.")
    desc = (f"לאן מייצאת ישראל ומה: יצוא סחורות לפי ענף כלכלי ויבשת יעד. {_bn(tot[-1])} מיליארד דולר ב-{ly}"
            + (f", {_chg_phrase(yoy)}" if yoy is not None else "") + ".")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{fy}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "יצוא סחורות מישראל לפי ענף וארץ יעד | הלמ\"ס",
                "description": desc,
                "name": "יצוא סחורות לפי ענף כלכלי וארצות",
                "alternate_names": ["יצוא ישראל לפי ענף", "יצוא סחורות לפי ארץ יעד",
                                    "ייצוא סחורות מישראל", "יעדי היצוא של ישראל"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top_i,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
