"""מדדי מחירים בסחר חוץ: CBS's quarterly foreign-trade price indices release.

Inputs are CBS grid tables (one row per sheet row, cells C01..Cnn) from the
newest edition of the release (the Q4 edition is titled "לשנת YYYY" and has
the same tables):
  t1   price indices of exports and imports, and the terms of trade
  t2   import prices by category (fuels, investment goods, inputs, consumer)
  t4   volume indices of exports and imports
  t14  manufacturing export prices by industry (ISIC codes, 2025 weights)
  t17  manufacturing export prices by technological intensity
  t22  import prices by SITC section
  t23  export prices by SITC section
  releases  the edition list (number, date, headline, link)

Every table has the same shape: a "YYYY=100" base row, multi-row Hebrew and
English column headers, a "Price indices" / "Volume indices" row, then rows
of years, quarters (IV-VI) and months (VII), then "Percentage of change".
Columns are found by their English header words (or the SITC / ISIC code
row) and raise when missing; period rows are found by pattern. All indices
are in US dollars. Changes are computed here from the index levels.
"""
import re

import pandas as pd
from govlib import cbs, fmt

QN = ("הראשון", "השני", "השלישי", "הרביעי")
SITC_HE = {
    "0": "מזון ובעלי חיים", "1": "משקאות וטבק", "2": "חומרי גלם (ללא דלק)",
    "3": "דלקים ושמני סיכה", "4": "שמנים ושומנים", "5": "כימיקלים",
    "6": "סחורות מעובדות לפי חומר", "7": "מכונות וציוד הובלה", "8": "מוצרים מעובדים שונים",
}
ISIC_HE = {
    "322-324,329": "כלי נגינה, ציוד ספורט וצעצועים",
    "26,3250": "מחשבים, אלקטרוניקה וציוד רפואי",
    "2100": "תרופות",
    "29-30": "כלי תחבורה",
    "271-274,279": "ציוד חשמלי",
    "20": "כימיקלים",
    "25,275,28": "מוצרי מתכת, מכונות וציוד",
    "24": "מתכות בסיסיות",
    "23": "מוצרים מינרליים אל-מתכתיים",
    "22": "גומי ופלסטיק",
    "19": "מוצרי נפט מזוקק",
    "321": "תכשיטים",
    "16,170,18,310": "עץ, רהיטים, נייר ודפוס",
    "13-15": "טקסטיל, הלבשה ועור",
    "10,110,120": "מזון, משקאות וטבק",
    "05-08": "כרייה וחציבה",
    "34": "עיבוד יהלומים",
}
TECH = (("High-technology", "טכנולוגיה עילית"), ("Medium-high", "טכנולוגיה מעורבת עילית"),
        ("Medium-low", "טכנולוגיה מעורבת מסורתית"), ("Low-technology", "טכנולוגיה מסורתית"))
CATS = (("Fuels", "חומרי אנרגיה"), ("Investment", "נכסי השקעה"),
        ("Production inputs", "תשומות לייצור"), ("Consumer", "מוצרי צריכה"))
_BASE = re.compile(r"^(\d{4})=100$")
_SITC = re.compile(r"^\d$")
_ISIC = re.compile(r"^\d{2,4}(-\d{2,4})?(, ?\d{2,4}(-\d{2,4})?)*$")
_LATIN = re.compile(r"[A-Za-z]")
MOVE = 0.01      # a change under 1% reads as "almost unchanged"
SHOCK = 0.10     # an energy-price move this large gets its own insight


# ── table reading ────────────────────────────────────────────────────────


class Table:
    """One CBS index table: header labels per column and the period rows."""

    def __init__(self, frame, name):
        self.name = name
        self.rows = rows = cbs.grid(frame, name)
        top = next((i for i, r in enumerate(rows) if any(_BASE.match(c) for c in r)), None)
        if top is None:
            raise ValueError(f"{name}: base row (YYYY=100) not found")
        self.base = next(_BASE.match(c).group(1) for c in rows[top] if _BASE.match(c))
        idx = next((i for i in range(top, len(rows)) if any(
            c.startswith(("Price indices", "Volume indices")) for c in rows[i])), None)
        if idx is None:
            raise ValueError(f"{name}: 'Price indices' row not found")
        self.top, self.idx = top, idx
        stop = next((i for i in range(idx + 1, len(rows)) if any(
            c.startswith("Percentage of change") for c in rows[i])), len(rows))
        self.periods = cbs.periods(rows, idx + 1, stop)
        width = max(len(r) for r in rows[top:idx + 1])
        self.labels = {j: " ".join(cbs.cell(rows[i], j) for i in range(top + 1, idx)
                                   if cbs.cell(rows[i], j)) for j in range(width)}

    def header_row(self, *labels):
        """Index of the header row (between base and index rows) holding
        every label; raises when there is none."""
        for i in range(self.top, self.idx):
            if all(lb in self.rows[i] for lb in labels):
                return i
        raise ValueError(f"{self.name}: header row with {labels} not found")

    def col(self, pred, what, cols=None):
        hits = [j for j in (cols if cols is not None else sorted(self.labels))
                if pred(self.labels.get(j, ""))]
        if not hits:
            raise ValueError(f"{self.name}: column {what!r} not found")
        return hits[0]

    def series(self, j):
        """{"years": {y: v}, "quarters": {(y, q): v}, "months": {(y, m): v}}."""
        out = {"years": {}, "quarters": {}, "months": {}}
        for i, y, m, end in self.periods:
            v = cbs.val(self.rows[i], j)
            if v is None:
                continue
            if m is None:
                out["years"][y] = v
            elif end is not None:
                if m in (1, 4, 7, 10) and end == m + 2:
                    out["quarters"][(y, (m - 1) // 3 + 1)] = v
            else:
                out["months"][(y, m)] = v
        return out

    def weights(self):
        """{col: weight} from the "Weight YYYY" row, and the year; ({}, None)
        when the table has none."""
        for i in range(self.top, self.idx):
            r = self.rows[i]
            if any(c.startswith("Weight") for c in r):
                year = next((m.group(1) for c in r
                             for m in [re.fullmatch(r"(?:Weight )?((?:19|20)\d\d)", c)] if m), None)
                return {j: cbs.val(r, j) for j in range(len(r))
                        if cbs.val(r, j) is not None and not cbs.YEAR.match(r[j])}, year
        return {}, None


def _main(label):
    """The headline series: excl. ships, aircraft and diamonds (with fuels)."""
    return "diamonds" in label and "fuels" not in label


def _no_fuel(label):
    return "diamonds" in label and "fuels" in label


def _blocks(t, groups):
    """Column ranges under each group header (Terms of trade / Exports /
    Imports), left to right."""
    h = t.header_row(*groups)
    starts = sorted((cbs.col_after(t.rows[h], g, 0), g) for g in groups)
    width = max(t.labels) + 1
    return {g: range(s, starts[k + 1][0] if k + 1 < len(starts) else width)
            for k, (s, g) in enumerate(starts)}


def _code_cols(t, pattern, min_hits):
    """{col: code} from the header row with the most cells matching pattern."""
    best = None
    for i in range(t.top, t.idx):
        hits = {j: c.replace(" ", "") for j, c in enumerate(t.rows[i]) if pattern.match(c)}
        if len(hits) >= min_hits and (best is None or len(hits) > len(best)):
            best = hits
    if best is None:
        raise ValueError(f"{t.name}: code row not found")
    return best


def _hebrew_label(t, j):
    parts = [cbs.cell(t.rows[i], j) for i in range(t.top + 1, t.idx)]
    parts = [p for p in parts if p and not _LATIN.search(p) and not _ISIC.match(p)
             and cbs.num(p) is None and p != "משקל"]
    return " ".join(parts).replace(" ,", ",").strip()


# ── formatting ───────────────────────────────────────────────────────────


def _qlong(k):
    return f"הרבעון {QN[k[1] - 1]} של {k[0]}"


def _qin(k):
    return f"ברבעון {QN[k[1] - 1]} של {k[0]}"


def _qshort(k):
    return f"ר׳{k[1]} {k[0]}"


def _mname(k):
    return f"{fmt.MONTHS_HE[k[1] - 1]} {k[0]}"


def _mshort(k):
    return f"{fmt.MONTHS_SHORT_HE[k[1] - 1]} {k[0]}"


def _ix(v):
    return "" if v is None else fmt.num_he(v, 1)


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _sp(c):
    return "" if c is None else fmt.signed_pct(c)


def _r1(v):
    return None if v is None else round(v, 1)


def _r2(c):
    return None if c is None else round(c * 100, 2)


def _verb(c, up="עלו", down="ירדו", same="לא השתנו"):
    if abs(c) < 0.0005:
        return same
    return f"{up if c > 0 else down} ב-{fmt.pct(abs(c))}"


def _prev_q(k):
    return (k[0], k[1] - 1) if k[1] > 1 else (k[0] - 1, 4)


def _yago(k):
    return (k[0] - 1, k[1])


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"].copy()
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    # t1: exports, imports (with / without fuels), terms of trade
    t1 = Table(frames["t1"], "t1")
    b1 = _blocks(t1, ("Terms of trade index", "Exports", "Imports"))
    exp = t1.series(t1.col(_main, "exports", b1["Exports"]))
    imp = t1.series(t1.col(_main, "imports", b1["Imports"]))
    imp_nf = t1.series(t1.col(_no_fuel, "imports excl. fuels", b1["Imports"]))
    tot = t1.series(t1.col(_main, "terms of trade", b1["Terms of trade index"]))
    tot_nf = t1.series(t1.col(_no_fuel, "terms of trade excl. fuels",
                              b1["Terms of trade index"]))
    quarters = sorted(set(exp["quarters"]) & set(imp["quarters"]))
    if len(quarters) < 2:
        raise ValueError("t1: fewer than two quarters")
    L = quarters[-1]
    P, Y = _prev_q(L), _yago(L)
    base = t1.base
    # Footnote "(1) Since 2026, the calculations do not contain diamonds."
    since = next((m.group(1) for r in t1.rows for c in r
                  for m in [re.match(r"^Since ((?:19|20)\d\d), the calculations do not contain "
                                     r"diamonds", c)] if m), None)

    def q(s, k):
        return s["quarters"].get(k)

    exp_q, imp_q = _chg(q(exp, L), q(exp, P)), _chg(q(imp, L), q(imp, P))
    imp_nf_q = _chg(q(imp_nf, L), q(imp_nf, P))
    tot_nf_q = _chg(q(tot_nf, L), q(tot_nf, P))
    exp_y, imp_y = _chg(q(exp, L), q(exp, Y)), _chg(q(imp, L), q(imp, Y))

    # t2: import prices by category
    t2 = Table(frames["t2"], "t2")
    w2, w2_year = t2.weights()
    cats = []
    for key, he in CATS:
        j = t2.col(lambda lb, key=key: key in lb and "Total" not in lb, key)
        cats.append({"name": he, "s": t2.series(j), "w": w2.get(j)})
    fuel = cats[0]["s"]
    fuel_q = _chg(q(fuel, L), q(fuel, P))

    # t4: volume indices
    t4 = Table(frames["t4"], "t4")
    b4 = _blocks(t4, ("Exports", "Imports"))
    vexp = t4.series(t4.col(_main, "export volume", b4["Exports"]))
    vimp = t4.series(t4.col(_main, "import volume", b4["Imports"]))

    # t17: manufacturing exports by technological intensity
    t17 = Table(frames["t17"], "t17")
    tech = [{"name": he, "s": t17.series(t17.col(lambda lb, key=key: key in lb, key))}
            for key, he in TECH]

    # t22 / t23: imports and exports by SITC section
    sitc = {}
    for nm, side in (("t22", "imp"), ("t23", "exp")):
        t = Table(frames[nm], nm)
        for j, code in _code_cols(t, _SITC, 5).items():
            sitc.setdefault(code, {})[side] = t.series(j)

    # t14: manufacturing exports by industry
    t14 = Table(frames["t14"], "t14")
    w14, w14_year = t14.weights()
    inds = []
    for j, code in sorted(_code_cols(t14, _ISIC, 5).items()):
        if "Thereof" in t14.labels.get(j, ""):
            continue
        name = ISIC_HE.get(code) or _hebrew_label(t14, j) or f"ענף {code}"
        s = t14.series(j)
        inds.append({"name": name, "code": code, "w": w14.get(j), "s": s,
                     "now": q(s, L), "ago": q(s, Y), "y": _chg(q(s, L), q(s, Y))})
    inds = [d for d in inds if d["y"] is not None]
    inds.sort(key=lambda d: (-d["y"], d["name"]))

    # ── KPIs ─────────────────────────────────────────────────────────────
    def tone(c, good_up):
        if c is None or abs(c) < MOVE:
            return "brand"
        return "ok" if (c > 0) == good_up else ("danger" if good_up else "warn")

    kpis, labels = {}, {}
    if tot_nf_q is not None:
        kpis["tot"] = {"value": round(tot_nf_q, 4), "display": fmt.signed_pct(tot_nf_q),
                       "tone": tone(tot_nf_q, True)}
        labels["tot_kpi"] = f"מדד תנאי הסחר ללא אנרגיה, {_qshort(L)} לעומת {_qshort(P)}"
    if exp_q is not None:
        kpis["exp"] = {"value": round(exp_q, 4), "display": fmt.signed_pct(exp_q),
                       "tone": tone(exp_q, True)}
        labels["exp_kpi"] = f"מחירי היצוא, {_qshort(L)} לעומת {_qshort(P)}"
    if imp_q is not None:
        kpis["imp"] = {"value": round(imp_q, 4), "display": fmt.signed_pct(imp_q),
                       "tone": tone(imp_q, False)}
        labels["imp_kpi"] = f"מחירי היבוא, {_qshort(L)} לעומת {_qshort(P)}"
    if fuel_q is not None:
        kpis["fuel"] = {"value": round(fuel_q, 4), "display": fmt.signed_pct(fuel_q),
                        "tone": tone(fuel_q, False)}
        labels["fuel_kpi"] = f"מחירי יבוא חומרי אנרגיה, {_qshort(L)} לעומת {_qshort(P)}"

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables, flags = {}, {}, {}
    charts["prices"] = {"x": [_qshort(k) for k in quarters],
                        "exp": [_r1(q(exp, k)) for k in quarters],
                        "imp": [_r1(q(imp, k)) for k in quarters],
                        "imp_nf": [_r1(q(imp_nf, k)) for k in quarters]}
    tables["prices"] = [[_qshort(k), _ix(q(exp, k)), _sp(_chg(q(exp, k), q(exp, _prev_q(k)))),
                         _ix(q(imp, k)), _sp(_chg(q(imp, k), q(imp, _prev_q(k)))),
                         _ix(q(imp_nf, k))] for k in reversed(quarters)]

    charts["tot"] = {"x": [_qshort(k) for k in quarters],
                     "nf": [_r1(q(tot_nf, k)) for k in quarters],
                     "all": [_r1(q(tot, k)) for k in quarters]}
    tables["tot"] = [[_qshort(k), _ix(q(tot_nf, k)),
                      _sp(_chg(q(tot_nf, k), q(tot_nf, _prev_q(k)))), _ix(q(tot, k)),
                      _sp(_chg(q(tot, k), q(tot, _prev_q(k))))] for k in reversed(quarters)]

    months = sorted(set(exp["months"]) & set(imp["months"]))
    flags["months"] = len(months) >= 3
    if flags["months"]:
        charts["months"] = {"x": [_mshort(k) for k in months],
                            "exp": [_r1(exp["months"].get(k)) for k in months],
                            "imp": [_r1(imp["months"].get(k)) for k in months],
                            "tot": [_r1(tot_nf["months"].get(k)) for k in months]}
        tables["months"] = [[_mname(k), _ix(exp["months"].get(k)), _ix(imp["months"].get(k)),
                             _ix(tot_nf["months"].get(k))] for k in reversed(months)]

    cq = sorted(set().union(*(set(c["s"]["quarters"]) for c in cats)))
    charts["cats"] = {"x": [_qshort(k) for k in cq],
                      "series": [{"name": c["name"], "data": [_r1(q(c["s"], k)) for k in cq]}
                                 for c in cats]}
    tables["cats"] = [[c["name"], _ix(q(c["s"], L)), _sp(_chg(q(c["s"], L), q(c["s"], P))),
                       _sp(_chg(q(c["s"], L), q(c["s"], Y))),
                       fmt.pct_of(c["w"]) if c["w"] is not None else ""] for c in cats]

    sitc_rows = []
    for code in sorted(sitc):
        d = sitc[code]
        si, se = d.get("imp"), d.get("exp")
        sitc_rows.append({"code": code, "name": SITC_HE.get(code, f"סוג {code}"),
                          "imp": _chg(q(si, L), q(si, Y)) if si else None,
                          "exp": _chg(q(se, L), q(se, Y)) if se else None,
                          "imp_ix": q(si, L) if si else None, "exp_ix": q(se, L) if se else None})
    flags["sitc"] = any(r["imp"] is not None or r["exp"] is not None for r in sitc_rows)
    if flags["sitc"]:
        charts["sitc"] = {"names": [r["name"] for r in sitc_rows],
                          "imp": [_r2(r["imp"]) for r in sitc_rows],
                          "exp": [_r2(r["exp"]) for r in sitc_rows]}
        tables["sitc"] = [[r["name"], _ix(r["imp_ix"]), _sp(r["imp"]), _ix(r["exp_ix"]),
                           _sp(r["exp"])] for r in sitc_rows]

    tq = sorted(set().union(*(set(t["s"]["quarters"]) for t in tech)))
    flags["tech"] = len(tq) >= 2
    if flags["tech"]:
        charts["tech"] = {"x": [_qshort(k) for k in tq],
                          "series": [{"name": t["name"], "data": [_r1(q(t["s"], k)) for k in tq]}
                                     for t in tech]}
        tables["tech"] = [[t["name"], _ix(q(t["s"], L)), _sp(_chg(q(t["s"], L), q(t["s"], P))),
                           _sp(_chg(q(t["s"], L), q(t["s"], Y)))] for t in tech]

    flags["inds"] = len(inds) >= 3
    if flags["inds"]:
        charts["inds"] = {"names": [d["name"] for d in inds], "y": [_r2(d["y"]) for d in inds]}
        tables["inds"] = [[d["name"], _ix(d["ago"]), _ix(d["now"]), _sp(d["y"]),
                           fmt.pct_of(d["w"]) if d["w"] is not None else ""] for d in inds]

    vq = sorted(set(vexp["quarters"]) & set(vimp["quarters"]))
    flags["volume"] = len(vq) >= 2
    if flags["volume"]:
        charts["volume"] = {"x": [_qshort(k) for k in vq],
                            "exp": [_r1(q(vexp, k)) for k in vq],
                            "imp": [_r1(q(vimp, k)) for k in vq]}
        tables["volume"] = [[_qshort(k), _ix(q(vexp, k)), _sp(_chg(q(vexp, k), q(vexp, _yago(k)))),
                             _ix(q(vimp, k)), _sp(_chg(q(vimp, k), q(vimp, _yago(k))))]
                            for k in reversed(vq)]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if tot_nf_q is not None and exp_q is not None and imp_nf_q is not None:
        word = ("השתפר" if tot_nf_q > 0 else "הורע") if abs(tot_nf_q) >= 0.0005 else "לא השתנה"
        add("tot", f"{_qin(L)} מדד תנאי הסחר (ללא אוניות, מטוסים, יהלומים וחומרי אנרגיה) "
                   f"{word}" + (f" ב-{fmt.pct(abs(tot_nf_q))}" if word != "לא השתנה" else "")
                   + f": מחירי היצוא {_verb(exp_q)} ומחירי היבוא ללא אנרגיה "
                   f"{_verb(imp_nf_q)}, לעומת {_qlong(P)}.")
    if fuel_q is not None and abs(fuel_q) >= SHOCK and imp_q is not None and imp_nf_q is not None:
        add("energy", f"מחירי יבוא חומרי האנרגיה {_verb(fuel_q, 'זינקו', 'צנחו')} {_qin(L)}. "
                      f"מחירי כלל היבוא {_verb(imp_q)}, ובלי חומרי אנרגיה {_verb(imp_nf_q)}.")
    if exp_y is not None and imp_y is not None:
        add("year", f"לעומת {_qlong(Y)}, מחירי היצוא {_verb(exp_y)} ומחירי היבוא {_verb(imp_y)} "
                    f"(במונחי דולר).")
    yrs = sorted(set(exp["years"]) & set(imp["years"]))
    if len(yrs) >= 2:
        a, b = yrs[-1], yrs[-2]
        ce, ci = _chg(exp["years"][a], exp["years"][b]), _chg(imp["years"][a], imp["years"][b])
        ct = _chg(tot_nf["years"].get(a), tot_nf["years"].get(b))
        if ce is not None and ci is not None:
            add("annual", f"בממוצע שנתי, מחירי היצוא ב-{a} {_verb(ce)} לעומת {b} ומחירי היבוא "
                          f"{_verb(ci)}" + (f". מדד תנאי הסחר ללא אנרגיה {_verb(ct, 'עלה', 'ירד', 'לא השתנה')}"
                                            if ct is not None else "") + ".")
    if flags["sitc"]:
        movers = [(abs(r["imp"]), r["name"], r["imp"]) for r in sitc_rows if r["imp"] is not None]
        movers.sort(key=lambda m: (-m[0], m[1]))
        if movers and movers[0][0] >= 0.05:
            _, nm, c = movers[0]
            add("sitc", f"בין סוגי הסחורות ביבוא, השינוי החד ביותר לעומת {_qlong(Y)} היה "
                        f"ב{nm}: {_sp(c)}.")
    if flags["tech"]:
        ty = [(_chg(q(t["s"], L), q(t["s"], Y)), t["name"]) for t in tech]
        ty = [x for x in ty if x[0] is not None]
        if len(ty) >= 2:
            ty.sort(key=lambda x: (-x[0], x[1]))
            hi, lo = ty[0], ty[-1]
            if hi[0] - lo[0] >= 0.03:
                add("tech", f"ביצוא התעשייתי, המחירים בתעשיות {hi[1]} {_verb(hi[0])} בשנה, "
                            f"ובתעשיות {lo[1]} {_verb(lo[0])}.")
    if flags["inds"]:
        weighted = [d for d in inds if d["w"]]
        if weighted:
            big = max(weighted, key=lambda d: (d["w"], d["name"]))
            add("industry", f"הענף הגדול ביצוא התעשייתי הוא {big['name']} ("
                            f"{fmt.pct_of(big['w'])} מהמשקל ב-{w14_year}). מחירי היצוא שלו "
                            f"{_verb(big['y'])} לעומת {_qlong(Y)}." if w14_year else None)
    if flags["volume"]:
        ve, vi = _chg(q(vexp, L), q(vexp, Y)), _chg(q(vimp, L), q(vimp, Y))
        if ve is not None and vi is not None:
            add("volume", f"בכמויות (מדדי הנפח), היצוא {_verb(ve, 'עלה', 'ירד', 'לא השתנה')} לעומת "
                          f"{_qlong(Y)} והיבוא {_verb(vi, 'עלה', 'ירד', 'לא השתנה')}.")

    # ── text ─────────────────────────────────────────────────────────────
    rel_date = pd.Timestamp(latest_rel["RELEASE_DATE"])
    release = {"no": latest_rel["RELEASE_NO"], "date": fmt.d_he(rel_date),
               "title": latest_rel["TITLE"], "headline": latest_rel["HEADLINE"],
               "url": latest_rel["PAGE_URL"], "pdf": latest_rel["REPORT_PDF_URL"]}
    big_cat = max((c for c in cats if c["w"] is not None), key=lambda c: (c["w"], c["name"]),
                  default=None)
    labels.update({
        "lede": (f"בכמה התייקרו או הוזלו הסחורות שישראל מייבאת ומייצאת, ומה זה עושה למדד "
                 f"תנאי הסחר: היחס בין מחירי היצוא למחירי היבוא. מדד מעל הרמה הקודמת אומר "
                 f"שתמורת אותה כמות יצוא אפשר לייבא יותר. הנתונים מתוך ההודעה הרבעונית של "
                 f"הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), במונחי דולר, כשממוצע {base} שווה 100. "
                 f"הנתון האחרון הוא ל{_qlong(L)[1:]}."),
        "prices_note": (f"מדדי המחירים של היצוא והיבוא בכל רבעון, ללא אוניות, מטוסים ויהלומים. "
                        f"הקו המקווקו הוא היבוא בלי חומרי אנרגיה. ממוצע {base} שווה 100."),
        "prices_aria": f"מדדי מחירי היצוא והיבוא לפי רבעון, {_qshort(quarters[0])} עד {_qshort(L)}",
        "prices_caption": "מדדי מחירים של היצוא והיבוא לפי רבעון",
        "tot_note": ("מדד תנאי הסחר הוא מדד מחירי היצוא חלקי מדד מחירי היבוא, כפול מאה. "
                     "עלייה פירושה שיפור: היצוא מתייקר יותר מהיבוא. הקו הראשי לא כולל חומרי "
                     "אנרגיה, שמחיריהם תנודתיים מאוד."),
        "tot_aria": f"מדד תנאי הסחר לפי רבעון, {_qshort(quarters[0])} עד {_qshort(L)}",
        "tot_caption": "מדד תנאי הסחר לפי רבעון",
        "cats_note": ("מדדי מחירי היבוא לפי קבוצת סחורות. "
                      + (f"הקבוצה הגדולה ביבוא היא {big_cat['name']} "
                         f"({fmt.pct_of(big_cat['w'])} מהמשקל ב-{w2_year}). " if big_cat and w2_year
                         else "")
                      + "חומרי האנרגיה תנודתיים בהרבה מכל השאר."),
        "cats_aria": f"מדדי מחירי היבוא לפי קבוצה, {_qshort(cq[0])} עד {_qshort(cq[-1])}" if cq else "",
        "cats_caption": f"מחירי היבוא לפי קבוצה, {_qshort(L)}",
        "cats_w_col": f"משקל {w2_year}" if w2_year else "משקל",
        "q_col": _qshort(L), "p_col": f"לעומת {_qshort(P)}", "y_col": f"לעומת {_qshort(Y)}",
        "base_txt": f"שבו ממוצע {base} שווה 100",
        "y_short": _qshort(Y),
        "diamonds_note": (f"החל משנת {since} החישובים אינם כוללים יהלומים כלל." if since else ""),
    })
    if flags["months"]:
        labels.update({
            "months_note": (f"המדדים בכל חודש מאז {_mname(months[0])}. מדד תנאי הסחר בחודש "
                            f"מוצג ללא חומרי אנרגיה."),
            "months_aria": f"מדדי מחירי היצוא, היבוא ותנאי הסחר לפי חודש, {_mname(months[0])} עד "
                           f"{_mname(months[-1])}",
            "months_caption": "מדדי מחירים בסחר חוץ לפי חודש",
        })
    if flags["sitc"]:
        labels.update({
            "sitc_note": (f"השינוי במחירים {_qin(L)} לעומת {_qlong(Y)}, לפי סוג סחורה "
                          f"בסיווג הבין-לאומי (סיט\"ק), ביבוא וביצוא."),
            "sitc_aria": f"שינוי שנתי במחירי היבוא והיצוא לפי סוג סחורה, {_qshort(L)}",
            "sitc_caption": f"מחירי היבוא והיצוא לפי סוג סחורה, {_qshort(L)}",
        })
    if flags["tech"]:
        labels.update({
            "tech_note": ("מחירי היצוא התעשייתי לפי העוצמה הטכנולוגית של הענף: מתעשיות "
                          "טכנולוגיה עילית (תרופות, אלקטרוניקה) ועד תעשיות מסורתיות."),
            "tech_aria": f"מחירי היצוא התעשייתי לפי עוצמה טכנולוגית, {_qshort(tq[0])} עד "
                         f"{_qshort(tq[-1])}",
            "tech_caption": f"מחירי היצוא התעשייתי לפי עוצמה טכנולוגית, {_qshort(L)}",
        })
    if flags["inds"]:
        labels.update({
            "inds_note": (f"השינוי במחירי היצוא של כל ענף תעשייה {_qin(L)} לעומת "
                          f"{_qlong(Y)}. המשקל בטבלה הוא חלק הענף ביצוא התעשייתי."),
            "inds_aria": f"שינוי שנתי במחירי היצוא לפי ענף תעשייה, {_qshort(L)}",
            "inds_caption": f"מחירי היצוא לפי ענף תעשייה, {_qshort(L)}",
            "inds_w_col": f"משקל {w14_year}" if w14_year else "משקל",
        })
    if flags["volume"]:
        labels.update({
            "volume_note": ("מדדי הנפח מודדים את הכמות שיובאה ויוצאה, בניכוי השינוי במחירים. "
                            "הם אינם מנוכי עונתיות, ולכן כדאי להשוות רבעון לאותו רבעון בשנה "
                            "הקודמת."),
            "volume_aria": f"מדדי הנפח של היצוא והיבוא לפי רבעון, {_qshort(vq[0])} עד {_qshort(vq[-1])}",
            "volume_caption": "מדדי הנפח של היצוא והיבוא לפי רבעון",
        })

    summary = (f"מדדי המחירים של היבוא והיצוא של ישראל ומדד תנאי הסחר, לפי רבעון וקבוצת סחורות, "
               f"מנתוני הלמ\"ס. {_qin(L)}: יצוא {_sp(exp_q)}, יבוא {_sp(imp_q)} לעומת "
               f"הרבעון הקודם.")
    desc = (f"מדד מחירי היבוא והיצוא ומדד תנאי הסחר, לפי רבעון וסוג סחורה. {_qin(L)}: "
            f"מחירי היצוא {_sp(exp_q)}, מחירי היבוא {_sp(imp_q)}.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{min(yrs or [quarters[0][0]])}/{L[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד מחירי היבוא והיצוא ותנאי הסחר | הלמ\"ס",
                "description": desc,
                "name": "מדדי מחירים בסחר חוץ: יבוא, יצוא ותנאי הסחר",
                "alternate_names": ["מדדי מחירים בסחר חוץ", "מדד תנאי הסחר", "מדד מחירי היבוא",
                                    "מדד מחירי היצוא"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
