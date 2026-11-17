"""יבוא סחורות לפי ארץ מקור: CBS's yearly release on imports by country of origin.

The release has six country tables, each with the same rows (continents,
sub-regions, countries) and six years of columns, in million dollars:

  origin      לפי ארץ מקור                    where the goods were made
  purchase    לפי ארץ קנייה                   where Israel bought them
  gap         שלא יוצרו בארץ הקנייה           purchase minus origin, per country
  origin_nd   לפי ארץ מקור, ללא יהלומים
  purchase_nd לפי ארץ קנייה, ללא יהלומים
  gap_nd      שלא יוצרו ... ללא יהלומים       (not shown: the gap above minus diamonds)

CBS may renumber the tables, so every stem t1..t9 (three spares) is optional
and each table is recognised by its TITLE. The origin table is required; a
missing other table drops its section. A recognised table whose header
labels (the year row, the country column, "סך כולל") are gone raises.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE_HE = re.compile(r"^לוח\s*\d+[א-ת]?\s*-")
CONTINENTS = ("אירופה", "אסיה", "אפריקה", "אמריקה", "אוקיאניה")
NO_DIAMONDS = "ללא יהלומים"
TOP_N = 15
LINE_N = 6
GAP_N = 7
MOVER_N = 6
MOVER_MIN = 300.0  # million $: a country must reach this in one of the two years
PRIORITY = ("trend", "top", "indirect", "hubs", "continents", "movers", "diamonds",
            "concentration", "unclassified")
MAX_TOP = 8


# ── locating and parsing tables ──────────────────────────────────────────


def _despace(s):
    """CBS spaces out region names ("א ס י ה"): join single letters."""
    parts = s.split(" ")
    if len(parts) > 2 and all(len(p) == 1 for p in parts):
        return "".join(parts)
    return s


def _title(rows):
    for r in rows[:6]:
        for c in r:
            if TITLE_HE.match(c):
                return c
    return ""


def _kind(t):
    nd = NO_DIAMONDS in t
    if "שלא יוצרו בארץ הקנייה" in t:
        return "gap_nd" if nd else "gap"
    if "לפי ארץ מקור" in t:
        return "origin_nd" if nd else "origin"
    if "לפי ארץ קנייה" in t:
        return "purchase_nd" if nd else "purchase"
    return None


def _tables(frames):
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        k = _kind(_title(rows))
        if k and k not in out:
            out[k] = rows
    return out


def _parse(rows, name):
    """{"years": [..asc], "items": [{name, code, kind, v: {year: value}}]}."""
    yr = next((i for i, r in enumerate(rows) if sum(1 for c in r if cbs.YEAR.match(c)) >= 2), None)
    if yr is None:
        raise ValueError(f"{name}: year header row not found")
    ycols = [(j, int(c)) for j, c in enumerate(rows[yr]) if cbs.YEAR.match(c)]
    lcol = ccol = None
    for r in rows[:yr + 1]:
        for j, c in enumerate(r):
            if lcol is None and _despace(c) == "ארצות":
                lcol = j
            if ccol is None and c == "סמל":
                ccol = j
    if lcol is None:
        raise ValueError(f"{name}: country column (ארצות) not found")
    if ccol is None:
        raise ValueError(f"{name}: code column (סמל) not found")
    items, prefix, total = [], "", None
    for r in rows[yr + 1:]:
        label = _despace(cbs.cell(r, lcol))
        code = cbs.cell(r, ccol)
        vals = {y: cbs.val(r, j) for j, y in ycols}
        if not label:
            prefix = ""
            continue
        if all(v is None for v in vals.values()):
            prefix = (prefix + " " + label).strip()  # a label split over two rows
            continue
        label = (prefix + " " + label).strip()
        prefix = ""
        if label == "סך כולל":
            total = vals
            continue
        if "מסווגות" in label:
            kind = "unclassified"
        elif label in CONTINENTS and not code:
            kind = "continent"
        elif not code:
            kind = "region"
        elif label.startswith("יתר"):
            kind = "residual"
        else:
            kind = "country"
        items.append({"name": label, "code": code, "kind": kind, "v": vals})
    if total is None:
        raise ValueError(f"{name}: grand total row (סך כולל) not found")
    return {"years": sorted(y for _, y in ycols), "items": items, "total": total}


# ── small helpers ────────────────────────────────────────────────────────


def _r1(v):
    return None if v is None else round(float(v), 1)


def _bn(v):
    return fmt.num_he(v / 1000, 1)


def _m(v):
    return fmt.int_he(v)


def _chg(new, old):
    if new is None or old is None or old == 0:
        return None
    return new / old - 1


def _countries(t):
    return [i for i in t["items"] if i["kind"] == "country"]


def _by_code(t):
    return {i["code"]: i for i in _countries(t)}


def _get(item, y):
    return item["v"].get(y) if item else None


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "origin" not in tabs:
        raise ValueError("origin table (יבוא סחורות, לפי ארץ מקור) not found in any table")
    o = _parse(tabs["origin"], "origin")
    years = o["years"]
    ly = years[-1]
    py = ly - 1 if (ly - 1) in years else None
    tot = o["total"]
    t_last = tot.get(ly)
    if t_last is None:
        raise ValueError("origin: no grand total for the latest year")
    t_prev = tot.get(py) if py else None

    p = _parse(tabs["purchase"], "purchase") if "purchase" in tabs else None
    g = _parse(tabs["gap"], "gap") if "gap" in tabs else None
    ond = _parse(tabs["origin_nd"], "origin_nd") if "origin_nd" in tabs else None
    pnd = _parse(tabs["purchase_nd"], "purchase_nd") if "purchase_nd" in tabs else None

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    countries = _countries(o)
    ranked = sorted((c for c in countries if _get(c, ly) is not None),
                    key=lambda c: (-_get(c, ly), c["code"]))
    if not ranked:
        raise ValueError("origin: no country rows")

    # ── KPIs + trend ─────────────────────────────────────────────────────
    chg = _chg(t_last, t_prev)
    kpis["total"] = {"value": _r1(t_last), "display": _bn(t_last), "tone": "brand"}
    labels["total_kpi"] = f"יבוא סחורות ב-{ly} (מיליארדי דולרים)"
    if chg is not None:
        kpis["chg"] = {"value": round(chg * 100, 1), "display": fmt.signed_pct(chg),
                       "tone": "info"}
        labels["chg_kpi"] = f"שינוי ביבוא לעומת {py}"

    nd_tot = ond["total"] if ond else {}
    diam = {y: (tot[y] - nd_tot[y]) if tot.get(y) is not None and nd_tot.get(y) is not None
            else None for y in years}
    flags["diamonds"] = ond is not None and diam.get(ly) is not None
    charts["trend"] = {"x": [str(y) for y in years],
                       "total": [_r1(tot.get(y)) for y in years],
                       "nd": [_r1(nd_tot.get(y)) for y in years] if flags["diamonds"] else None,
                       "diam": [_r1(diam.get(y)) for y in years] if flags["diamonds"] else None}
    tables["trend"] = [[str(y), _bn(tot[y]) if tot.get(y) is not None else "–"]
                       + ([_bn(nd_tot[y]) if nd_tot.get(y) is not None else "–",
                           _bn(diam[y]) if diam.get(y) is not None else "–"]
                          if flags["diamonds"] else [])
                       for y in reversed(years)]
    labels["trend_cols"] = (["שנה", "סך היבוא"]
                            + (["ללא יהלומים", "יהלומים"] if flags["diamonds"] else []))
    valid = [y for y in years if tot.get(y) is not None]
    peak = max(valid, key=lambda y: (tot[y], y))
    labels["trend_note"] = (f"יבוא הסחורות לישראל בכל שנה, {years[0]} עד {ly}, במיליארדי דולרים"
                            + (", בפיצול ליהלומים ולשאר הסחורות." if flags["diamonds"] else "."))
    labels["trend_aria"] = f"יבוא סחורות לישראל לפי שנה, {years[0]} עד {ly}"
    if chg is not None:
        txt = (f"ב-{ly} הסתכם יבוא הסחורות לישראל ב-{_bn(t_last)} מיליארד דולר, "
               f"{'עלייה' if chg > 0 else 'ירידה'} של {fmt.pct(abs(chg))} לעומת {py}")
        if peak != ly and tot[peak] > t_last * 1.03:
            txt += f". השיא בתקופה היה ב-{peak}: {_bn(tot[peak])} מיליארד דולר"
        elif peak == ly and len(valid) >= 3:
            txt += f", הרמה הגבוהה ביותר מאז {valid[0]}"
        add("trend", txt + ".")

    # ── top origin countries ─────────────────────────────────────────────
    top = ranked[:TOP_N]
    top_disp = list(reversed(top))
    charts["top"] = {"names": [c["name"] for c in top_disp],
                     "values": [_r1(_get(c, ly)) for c in top_disp],
                     "share": [round(_get(c, ly) / t_last * 100, 1) for c in top_disp]}
    tables["top"] = []
    for c in top:
        v, pv = _get(c, ly), _get(c, py) if py else None
        cc = _chg(v, pv)
        tables["top"].append([c["name"], _m(v), fmt.pct(v / t_last),
                              fmt.signed_pct(cc) if cc is not None else "–"])
    labels["top_cols"] = ["ארץ מקור", f"{ly} (מיליוני דולרים)", "חלק מהיבוא",
                          f"שינוי לעומת {py}" if py else "שינוי"]
    labels["top_note"] = (f"{len(top)} הארצות שבהן יוצרו הכי הרבה סחורות שיובאו לישראל ב-{ly}, "
                          f"במיליוני דולרים.")
    labels["top_aria"] = f"{len(top)} ארצות המקור המובילות ביבוא לישראל, {ly}"
    lead = ranked[0]
    lv = _get(lead, ly)
    kpis["lead"] = {"value": round(lv / t_last * 100, 1), "display": fmt.pct(lv / t_last),
                    "tone": "brand"}
    labels["lead_kpi"] = f"חלקה של {lead['name']} ביבוא לפי ארץ מקור, {ly}"
    first_y = next((y for y in years if _get(lead, y) is not None and tot.get(y)), None)
    txt = (f"{lead['name']} היא ארץ המקור הגדולה של היבוא לישראל: ב-{ly} יוצרו בה סחורות "
           f"ב-{_bn(lv)} מיליארד דולר, {fmt.pct(lv / t_last)} מכלל היבוא")
    if first_y is not None and first_y != ly:
        s0 = _get(lead, first_y) / tot[first_y]
        s1 = lv / t_last
        if abs(s1 - s0) >= 0.01:
            txt += f", לעומת {fmt.pct(s0)} ב-{first_y}"
    if len(ranked) >= 2:
        second = ranked[1]
        txt += (f". השנייה היא {second['name']}, עם {_bn(_get(second, ly))} מיליארד דולר")
    add("top", txt + ".")
    if len(ranked) >= 5:
        s5 = sum(_get(c, ly) for c in ranked[:5]) / t_last
        add("concentration", f"חמש ארצות המקור הגדולות ({fmt.join_he(c['name'] for c in ranked[:5])}) "
                             f"מספקות {fmt.pct(s5)} מיבוא הסחורות לישראל ב-{ly}.")

    # ── lines: top countries over time ───────────────────────────────────
    line = ranked[:LINE_N]
    charts["lines"] = {"x": [str(y) for y in years],
                       "series": [{"name": c["name"], "data": [_r1(_get(c, y)) for y in years]}
                                  for c in line]}
    tables["lines"] = [[c["name"]] + [_bn(_get(c, y)) if _get(c, y) is not None else "–"
                                      for y in years] for c in line]
    labels["lines_cols"] = ["ארץ מקור"] + [str(y) for y in years]
    labels["lines_note"] = (f"היבוא מ-{len(line)} ארצות המקור הגדולות בכל שנה, {years[0]} עד {ly}, "
                            f"במיליוני דולרים.")
    labels["lines_aria"] = f"יבוא מארצות המקור הגדולות לפי שנה, {years[0]} עד {ly}"

    # ── movers ───────────────────────────────────────────────────────────
    flags["movers"] = False
    if py:
        mv = []
        for c in countries:
            v, pv = _get(c, ly), _get(c, py)
            if v is None or pv is None or max(v, pv) < MOVER_MIN:
                continue
            mv.append((v - pv, c, v, pv))
        ups = sorted((m for m in mv if m[0] > 0), key=lambda m: (-m[0], m[1]["code"]))[:MOVER_N]
        downs = sorted((m for m in mv if m[0] < 0), key=lambda m: (m[0], m[1]["code"]))[:MOVER_N]
        sel = sorted(ups + downs, key=lambda m: (m[0], m[1]["code"]))
        flags["movers"] = len(sel) >= 3
        if flags["movers"]:
            charts["movers"] = {"names": [m[1]["name"] for m in sel],
                                "values": [_r1(m[0]) for m in sel]}
            tables["movers"] = [[m[1]["name"], _m(m[3]), _m(m[2]),
                                 ("+" if m[0] > 0 else fmt.MINUS) + _m(abs(m[0])),
                                 fmt.signed_pct(_chg(m[2], m[3]))]
                                for m in reversed(sel)]
            labels["movers_cols"] = ["ארץ מקור", str(py), str(ly), "שינוי (מיליוני דולרים)",
                                     "שינוי באחוזים"]
            labels["movers_note"] = (f"הארצות שהיבוא מהן עלה או ירד הכי הרבה בין {py} ל-{ly}, "
                                     f"במיליוני דולרים. רק ארצות שהיבוא מהן הגיע ל-"
                                     f"{_m(MOVER_MIN)} מיליון דולר לפחות באחת השנתיים.")
            labels["movers_aria"] = f"השינוי ביבוא לפי ארץ מקור בין {py} ל-{ly}"
            parts = []
            if ups:
                u = ups[0]
                parts.append(f"העלייה הגדולה ביותר ב-{ly} הייתה ביבוא מ{u[1]['name']}: "
                             f"מ-{_m(u[3])} ל-{_m(u[2])} מיליון דולר "
                             f"({fmt.signed_pct(_chg(u[2], u[3]))})")
            if downs:
                d = downs[0]
                parts.append(f"הירידה הגדולה ביותר הייתה ביבוא מ{d[1]['name']}: "
                             f"מ-{_m(d[3])} ל-{_m(d[2])} מיליון דולר "
                             f"({fmt.signed_pct(_chg(d[2], d[3]))})")
            add("movers", ". ".join(parts) + ".")

    # ── continents (origin) ──────────────────────────────────────────────
    conts = [i for i in o["items"] if i["kind"] in ("continent", "unclassified")]
    flags["continents"] = sum(1 for c in conts if c["kind"] == "continent") >= 2
    if flags["continents"]:
        charts["continents"] = {"x": [str(y) for y in years],
                                "series": [{"name": c["name"],
                                            "data": [_r1(_get(c, y)) for y in years]}
                                           for c in conts]}
        tables["continents"] = [[c["name"]] + [_bn(_get(c, y)) if _get(c, y) is not None else "–"
                                               for y in years] for c in conts]
        labels["continents_cols"] = ["יבשת"] + [str(y) for y in years]
        labels["continents_note"] = ("יבוא הסחורות לפי יבשת המקור בכל שנה, במיליארדי דולרים. "
                                     "\"ארצות בלתי מסווגות\" הוא יבוא שהלמ\"ס אינה "
                                     "מייחסת לארץ מסוימת.")
        labels["continents_aria"] = f"יבוא סחורות לפי יבשת מקור, {years[0]} עד {ly}"
        unc = next((c for c in conts if c["kind"] == "unclassified"), None)
        if unc and _get(unc, ly):
            s = _get(unc, ly) / t_last
            if s >= 0.03:
                add("unclassified", f"{fmt.pct(s)} מהיבוא ב-{ly} ({_bn(_get(unc, ly))} מיליארד "
                                    f"דולר) רשום כ\"ארצות בלתי מסווגות\", בלי ארץ מקור מפורטת.")

    # ── origin vs purchase: continents ───────────────────────────────────
    flags["compare"] = False
    if p is not None:
        pc = {i["name"]: i for i in p["items"] if i["kind"] in ("continent", "unclassified")}
        pairs = [(c, pc[c["name"]]) for c in conts
                 if c["name"] in pc and _get(c, ly) is not None and _get(pc[c["name"]], ly) is not None]
        flags["compare"] = sum(1 for c, _ in pairs if c["kind"] == "continent") >= 2
        if flags["compare"]:
            charts["compare"] = {"names": [c["name"] for c, _ in pairs],
                                 "origin": [_r1(_get(c, ly)) for c, _ in pairs],
                                 "purchase": [_r1(_get(q, ly)) for _, q in pairs]}
            tables["compare"] = [[c["name"], _bn(_get(c, ly)), _bn(_get(q, ly)),
                                  ("+" if _get(q, ly) >= _get(c, ly) else fmt.MINUS)
                                  + _bn(abs(_get(q, ly) - _get(c, ly)))] for c, q in pairs]
            labels["compare_cols"] = ["יבשת", "לפי ארץ מקור", "לפי ארץ קנייה", "הפרש"]
            labels["compare_note"] = (f"היבוא ב-{ly} לפי יבשת, פעם לפי הארץ שבה יוצרה הסחורה "
                                      f"ופעם לפי הארץ שממנה נקנתה, במיליארדי דולרים.")
            labels["compare_aria"] = f"יבוא לפי יבשת מקור ולפי יבשת קנייה, {ly}"
            eu = next(((c, q) for c, q in pairs if c["name"] == "אירופה"), None)
            asia = next(((c, q) for c, q in pairs if c["name"] == "אסיה"), None)
            if eu and asia:
                eo, ep = _get(eu[0], ly), _get(eu[1], ly)
                ao, ap = _get(asia[0], ly), _get(asia[1], ly)
                if (ao > eo) != (ap > ep):
                    lo, lp = ("אסיה", "אירופה") if ao > eo else ("אירופה", "אסיה")
                    add("continents", f"לפי ארץ המקור {lo} מובילה ב-{ly} "
                                      f"(אסיה {_bn(ao)} מיליארד דולר, אירופה {_bn(eo)}), "
                                      f"אבל לפי ארץ הקנייה {lp} מובילה (אירופה {_bn(ep)}, "
                                      f"אסיה {_bn(ap)}): חלק מהסחורות שיוצרו באסיה נקנות "
                                      f"דרך ארצות באירופה.")
                elif ep - eo >= 1000:
                    add("continents", f"ב-{ly} נקנו באירופה סחורות ב-{_bn(ep)} מיליארד דולר, "
                                      f"אבל רק {_bn(eo)} מיליארד מהן יוצרו באירופה.")

    # ── origin vs purchase: countries (gap) ──────────────────────────────
    gap = []
    pcode = _by_code(p) if p is not None else {}
    if g is not None:
        for c in _countries(g):
            v = _get(c, ly)
            if v is not None:
                gap.append((v, c))
    elif p is not None:
        for c in countries:
            q = pcode.get(c["code"])
            if _get(c, ly) is not None and _get(q, ly) is not None:
                gap.append((_get(q, ly) - _get(c, ly), c))
    ocode = _by_code(o)
    pos = sorted((x for x in gap if x[0] > 0), key=lambda x: (-x[0], x[1]["code"]))[:GAP_N]
    neg = sorted((x for x in gap if x[0] < 0), key=lambda x: (x[0], x[1]["code"]))[:GAP_N]
    sel = sorted(pos + neg, key=lambda x: (x[0], x[1]["code"]))
    flags["gap"] = len(pos) >= 2 and len(neg) >= 2
    if flags["gap"]:
        charts["gap"] = {"names": [c["name"] for _, c in sel], "values": [_r1(v) for v, _ in sel]}
        rows_ = []
        for v, c in reversed(sel):
            ov = _get(ocode.get(c["code"]), ly)
            pv = _get(pcode.get(c["code"]), ly)
            rows_.append([c["name"], _m(ov) if ov is not None else "–",
                          _m(pv) if pv is not None else "–",
                          ("+" if v > 0 else fmt.MINUS) + _m(abs(v))])
        tables["gap"] = rows_
        labels["gap_cols"] = ["ארץ", "לפי ארץ מקור", "לפי ארץ קנייה", "הפרש"]
        labels["gap_note"] = (f"ההפרש בין היבוא לפי ארץ קנייה ליבוא לפי ארץ מקור ב-{ly}, במיליוני "
                              f"דולרים. ערך חיובי: ישראל קנתה בארץ הזאת יותר ממה שיוצר בה (ארץ "
                              f"מתווכת). ערך שלילי: סחורות שיוצרו בה נקנו דרך ארצות אחרות.")
        labels["gap_aria"] = f"הפרש בין יבוא לפי ארץ קנייה ולפי ארץ מקור, {ly}"
        nv, nc = neg[0]
        ov = _get(ocode.get(nc["code"]), ly)
        if ov:
            kpis["indirect"] = {"value": _r1(-nv), "display": _bn(-nv), "tone": "info"}
            labels["indirect_kpi"] = (f"סחורות מתוצרת {nc['name']} שנקנו בארצות אחרות, {ly} "
                                      f"(מיליארדי דולרים)")
            add("indirect", f"מתוך סחורות בשווי {_bn(ov)} מיליארד דולר שיוצרו ב{nc['name']} "
                            f"ויובאו לישראל ב-{ly}, סחורות בשווי {_bn(-nv)} מיליארד "
                            f"({fmt.pct(-nv / ov, 0)}) לא נקנו בה ישירות אלא דרך ארצות אחרות.")
        hubs = pos[:3]
        hub_txt = []
        for v, c in hubs:
            ov = _get(ocode.get(c["code"]), ly)
            pv = _get(pcode.get(c["code"]), ly)
            if ov is not None and pv is not None:
                hub_txt.append(f"{c['name']} ({_bn(pv)} מול {_bn(ov)})")
        if len(hub_txt) >= 2:
            add("hubs", f"יש ארצות שישראל קונה בהן הרבה יותר ממה שמיוצר בהן, תחנות ביניים בסחר: "
                        f"ב-{ly} {fmt.join_he(hub_txt)}, במיליארדי דולרים לפי ארץ קנייה מול "
                        f"ארץ מקור.")

    # ── diamonds ─────────────────────────────────────────────────────────
    if flags["diamonds"]:
        d_last = diam[ly]
        kpis["diam"] = {"value": _r1(d_last), "display": _bn(d_last), "tone": "brand"}
        labels["diam_kpi"] = f"יבוא יהלומים ב-{ly} (מיליארדי דולרים)"
        dvalid = [y for y in years if diam.get(y) is not None]
        dpeak = max(dvalid, key=lambda y: (diam[y], y))
        if dpeak != ly and diam[dpeak] >= d_last * 1.2:
            kpis["diam"]["tone"] = "warn"
            add("diamonds", f"יבוא היהלומים הסתכם ב-{ly} ב-{_bn(d_last)} מיליארד דולר "
                            f"({fmt.pct(d_last / t_last)} מהיבוא), {fmt.pct(1 - d_last / diam[dpeak], 0)} "
                            f"פחות מהשיא של {dpeak} ({_bn(diam[dpeak])} מיליארד).")
        else:
            add("diamonds", f"יבוא היהלומים הסתכם ב-{ly} ב-{_bn(d_last)} מיליארד דולר, "
                            f"{fmt.pct(d_last / t_last)} מכלל היבוא.")
        ndc = _by_code(ond)
        dl = []
        pndc = _by_code(pnd) if pnd is not None else {}
        for c in countries:
            v, w = _get(c, ly), _get(ndc.get(c["code"]), ly)
            if v is None or w is None:
                continue
            dv = v - w
            if dv >= 1:
                dp = None
                q, qn = pcode.get(c["code"]), pndc.get(c["code"])
                if _get(q, ly) is not None and _get(qn, ly) is not None:
                    dp = _get(q, ly) - _get(qn, ly)
                dl.append((dv, c, dp))
        dl = sorted(dl, key=lambda x: (-x[0], x[1]["code"]))[:8]
        flags["dcountries"] = len(dl) >= 3
        if flags["dcountries"]:
            has_p = all(x[2] is not None for x in dl)
            dd = list(reversed(dl))
            charts["dcountries"] = {"names": [c["name"] for _, c, _ in dd],
                                    "origin": [_r1(v) for v, _, _ in dd],
                                    "purchase": [_r1(x) for _, _, x in dd] if has_p else None}
            tables["dcountries"] = [[c["name"], _m(v)] + ([_m(x)] if has_p else [])
                                    for v, c, x in dl]
            labels["dcountries_cols"] = ["ארץ", "לפי ארץ מקור"] + (["לפי ארץ קנייה"] if has_p else [])
            labels["dcountries_note"] = (f"יבוא היהלומים ב-{ly} מהארצות הגדולות, במיליוני דולרים "
                                         f"(ההפרש בין היבוא הכולל ליבוא ללא יהלומים).")
            labels["dcountries_aria"] = f"יבוא יהלומים לפי ארץ, {ly}"
    else:
        flags["dcountries"] = False

    by_id = {i["id"]: i for i in insights}
    top_ins = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["lede"] = (f"מאיפה מגיעות הסחורות שישראל מייבאת: היבוא לפי ארץ המקור, הארץ שבה יוצרה "
                      f"הסחורה, לעומת ארץ הקנייה שממנה היא נקנתה. הנתונים מתוך ההודעה השנתית של "
                      f"הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. ב-{ly} "
                      f"הסתכם היבוא ב-{_bn(t_last)} מיליארד דולר, ו-{lead['name']} הייתה ארץ "
                      f"המקור הגדולה ({fmt.pct(lv / t_last)}).")
    summary = (f"יבוא הסחורות לישראל לפי ארץ מקור, לפי נתוני הלמ\"ס: {_bn(t_last)} מיליארד דולר "
               f"ב-{ly}, {lead['name']} ראשונה עם {fmt.pct(lv / t_last)}. השוואה לארץ הקנייה, "
               f"יבשות ויהלומים, {years[0]} עד {ly}.")
    desc = (f"מאיפה ישראל מייבאת: יבוא סחורות לפי ארץ מקור וארץ קנייה. ב-{ly} יובאו סחורות "
            f"ב-{_bn(t_last)} מיליארד דולר, {lead['name']} ראשונה עם {fmt.pct(lv / t_last)}.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0]}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "יבוא סחורות לישראל לפי ארץ מקור | הלמ\"ס",
                "description": desc,
                "name": "יבוא סחורות לפי ארץ מקור",
                "alternate_names": ["יבוא לפי ארץ ייצור", "מאיפה ישראל מייבאת",
                                    "יבוא לישראל לפי ארץ קנייה", "יבוא מסין לישראל",
                                    "ארצות המקור של היבוא"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top_ins,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
