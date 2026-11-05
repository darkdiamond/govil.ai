"""התוצר המקומי הגולמי: CBS's quarterly national-accounts release.

CBS publishes three estimates of each quarter (first, second, third; the
fourth quarter's first two come inside the annual report, which the title
regex leaves out). Every edition carries the same four tables:
  t2  expenditure on GDP and uses of resources: annual, half-year and
      quarterly rows in blocks (original current prices, chained 2020
      prices, seasonally adjusted chained, % change at annual rate)
  t3  private consumption by type (same blocks)
  t4  gross domestic capital formation by type (same blocks)
  t5  public consumption: defence and civilian (same blocks)
The chart-data files after them differ between editions: the third
estimate inserts an industry table as t6, which moves every diagram one
stem up. The GDP-per-capita diagram (seasonally adjusted, quarterly since
2015) is t6 in the first and second estimates and t7 in the third, so it
is looked for by its title in both.
  releases  the edition list (number, date, title, headline, links)

Header rows and columns are found by their labels (govlib.cbs plus the
column-header joins below) and raise when missing. Data rows are found by
pattern. The seasonally adjusted and %-change blocks sit at the bottom of
each sheet: a missing one leaves its sections out.
"""
import re

import pandas as pd
from govlib import cbs, fmt

ORDINALS = {1: "הראשון", 2: "השני", 3: "השלישי", 4: "הרביעי"}
ESTIMATES = {"ראשון": 1, "שני": 2, "שלישי": 3}
FLAT_BAND = 1.0          # % at annual rate: within ±1% a quarter is "flat"
RECENT_QUARTERS = 4      # quarters in the component tables
DEFENCE_UP = 0.02        # defence share must move by 2 points to be a finding
_SHORT_Q = re.compile(r"^(\d)(?:/(\d{4}))?$")


# ── grid helpers ─────────────────────────────────────────────────────────


def _heads(rows, start, stop):
    """Joined header text per column over rows[start:stop]."""
    width = max((len(r) for r in rows[start:stop]), default=0)
    return [" ".join(c for c in (cbs.cell(r, j) for r in rows[start:stop]) if c)
            for j in range(width)]


def _col(heads, *needles, after=-1, exclude=(), name="table"):
    """First column after `after` whose header text contains every needle
    and none of `exclude`. Raises when there is none."""
    for j in range(after + 1, len(heads)):
        h = heads[j]
        if all(n in h for n in needles) and not any(x in h for x in exclude):
            return j
    raise ValueError(f"{name}: column {needles!r} not found after {after}")


def _kind(row):
    """The block a section-marker row opens, from its Hebrew label."""
    text = " ".join(row)
    if "שינוי כמותי" in text:
        return "pct"
    if "מנוכי עונתיות" in text:
        return "sa" if "משורשרים" in text else "pct"
    if "נתונים משורשרים" in text:
        return "chain"
    if "נתונים מקוריים" in text:
        return "cur"
    return None


def _blocks(rows, cols, name):
    """{(kind, freq): {(year, period): {measure: value}}}. freq is A (a
    year), H (a half: period 1/2) or Q (a quarter: period 1..4). The first
    block of a kind and freq wins (t2 repeats its header mid-sheet)."""
    marks = [(i, _kind(r)) for i, r in enumerate(rows)
             if any(c.startswith(("נתונים", "שינוי כמותי")) for c in r)]
    marks = [(i, k) for i, k in marks if k]
    if not marks:
        raise ValueError(f"{name}: no data section marker (נתונים מקוריים ...)")
    out = {}
    for n, (s, kind) in enumerate(marks):
        stop = marks[n + 1][0] if n + 1 < len(marks) else len(rows)
        try:
            pers = cbs.periods(rows, s + 1, stop)
        except ValueError:
            continue
        found = {}
        for i, y, m, end in pers:
            if m is None:
                key, freq = (y, 0), "A"
            elif end and end - m == 5:
                key, freq = (y, 1 + (m - 1) // 6), "H"
            elif end and end - m == 2:
                key, freq = (y, 1 + (m - 1) // 3), "Q"
            else:
                continue
            vals = {k: cbs.val(rows[i], j) for k, j in cols.items()}
            if all(v is None for v in vals.values()):
                continue
            found.setdefault(freq, {})[key] = vals
        for freq, recs in found.items():
            out.setdefault((kind, freq), recs)
    return out


def _series(blocks, kind, freq):
    recs = blocks.get((kind, freq)) or {}
    return [(k, recs[k]) for k in sorted(recs)]


# ── tables ───────────────────────────────────────────────────────────────


def _t2(rows):
    t = cbs.row_with(rows, "לוח 2", name="t2", contains=True)
    first = next(i for i in range(t, len(rows)) if _kind(rows[i]))
    h = _heads(rows, t + 1, first)
    n = "t2"
    startup = _col(h, "Start-up", name=n)
    fixed = _col(h, "Fixed capital formation", name=n)
    cols = {
        "gdp_pc": _col(h, "לנפש", "תוצר", name=n),
        "business": _col(h, "business", name=n),
        "gdp": _col(h, "Total", after=startup, name=n),
        "imports": _col(h, "Import", name=n),
        "exports": _col(h, "Export", name=n),
        "fixed": fixed,
        "gcf": _col(h, "Total", after=fixed, name=n),
        "public": _col(h, "General government consumption", name=n),
        "private": _col(h, "Private consumption expenditure", exclude=("per capita",), name=n),
        "uses": _col(h, "Uses of resources", name=n),
    }
    return _blocks(rows, cols, n)


T3_CATS = [  # key, header needles, Hebrew label
    ("cars", ("Personal transport",), "כלי תחבורה אישיים"),
    ("furniture", ("Furniture",), "ריהוט, תכשיטים ושעונים"),
    ("electric", ("Electric",), "ציוד חשמלי"),
    ("clothing", ("Clothing",), "הלבשה והנעלה"),
    ("semi_other", ("Other Semi-Durable",), "מוצרים בני קיימה למחצה אחרים"),
    ("services", ("Services",), "שירותים"),
    ("housing", ("Housing",), "דיור"),
    ("fuel", ("Fuel,",), "דלק, חשמל ומים"),
    ("nondurable", ("Non-Durable",), "מוצרי תעשייה לצריכה שוטפת"),
    ("food", ("Food,",), "מזון, משקאות וטבק"),
    ("abroad", ("of Israelis abroad",), "צריכה של ישראלים בחו\"ל"),
]


def _t3(rows):
    t = cbs.row_with(rows, "לוח 3", name="t3", contains=True)
    first = next(i for i in range(t, len(rows)) if _kind(rows[i]))
    h = _heads(rows, t + 1, first)
    cols = {k: _col(h, *needles, name="t3") for k, needles, _ in T3_CATS}
    return _blocks(rows, cols, "t3")


T4_CATS = [
    ("residential", ("Residential buildings",), (), "בניינים למגורים"),
    ("nonres", ("Non- residential",), (), "בנייה שלא למגורים ועבודות בנייה"),
    ("machinery", ("Machinery and other equipment", "Total"), (), "מכונות וציוד"),
    ("ict", ("ICT",), (), "ציוד תקשוב"),
    ("land", ("Land transport", "Total"), (), "כלי תחבורה יבשתיים"),
    ("ships", ("Ships",), (), "אניות ומטוסים"),
    ("ip", ("Intellectual property",), (), "קניין רוחני (כולל מחקר ופיתוח)"),
    ("bio", ("Cultivated",), (), "משק חי ומטעים"),
]


def _t4(rows):
    t = cbs.row_with(rows, "לוח 4", name="t4", contains=True)
    first = next(i for i in range(t, len(rows)) if _kind(rows[i]))
    h = _heads(rows, t + 1, first)
    cols = {}
    for k, needles, excl, _ in T4_CATS:
        if k == "machinery":
            cols[k] = _col(h, "Total", after=_col(h, "Imports", name="t4"), name="t4")
        elif k == "land":
            cols[k] = _col(h, "Total", after=_col(h, "Passenger", name="t4"), name="t4")
        else:
            cols[k] = _col(h, *needles, exclude=excl, name="t4")
    return _blocks(rows, cols, "t4")


def _t5(rows):
    t = cbs.row_with(rows, "לוח 5", name="t5", contains=True)
    first = next(i for i in range(t, len(rows)) if _kind(rows[i]))
    h = _heads(rows, t + 1, first)
    civ = _col(h, "Civilian consumption", name="t5")
    cols = {
        "defence": _col(h, "Total", after=_col(h, "Defence consumption", name="t5"), name="t5"),
        "civilian": _col(h, "Total", after=civ, name="t5"),
    }
    return _blocks(rows, cols, "t5")


def _per_capita(frames):
    """The GDP-per-capita diagram (SA, 2020 prices): [((year, q), value)].
    It is t6 or t7 depending on the estimate; the one titled so wins."""
    for name in ("t6", "t7"):
        rows = cbs.grid(frames[name], name)
        try:
            cbs.row_with(rows, "Gross Domestic Product per Capita", name=name, contains=True)
        except ValueError:
            continue
        h = cbs.row_with(rows, "GDP", name=name, contains=True)
        vcol = cbs.col_after(rows[h], "GDP", 0, contains=True)
        pcol = cbs.best_col(rows[h + 1:], lambda v: bool(_SHORT_Q.match(v)))
        if pcol is None:
            raise ValueError(f"{name}: no quarter column in the per-capita diagram")
        out, year = [], None
        for r in rows[h + 1:]:
            m = _SHORT_Q.match(cbs.cell(r, pcol))
            v = cbs.val(r, vcol)
            if not m or v is None:
                continue
            if m.group(2):
                year = int(m.group(2))
            if year is None:
                continue
            out.append(((year, int(m.group(1))), v))
        return out
    raise ValueError("t6/t7: GDP per capita diagram (Gross Domestic Product per Capita) not found")


# ── formatting ───────────────────────────────────────────────────────────


def _q(t):
    """(2026, 2) → '2/2026' (CBS's own short form)."""
    return f"{t[1]}/{t[0]}"


def _qname(t):
    return f"הרבעון {ORDINALS[t[1]]} של {t[0]}"


def _in_q(t):
    """'ברבעון השני של 2026'."""
    return f"ברבעון {ORDINALS[t[1]]} של {t[0]}"


def _bn(v):
    """NIS million → NIS billion, one decimal."""
    return fmt.num_he(v / 1000, 1)


def _p(v):
    """A % value (0-100 scale) with a U+2212 minus: −4.2%."""
    return fmt.signed_pct(v / 100)


def _r1(v):
    return None if v is None else round(v, 1)


def _tone(v, band=0.0):
    if v is None:
        return "brand"
    return "ok" if v > band else "danger" if v < -band else "warn"


def _dir(v):
    return "עלה" if v > 0 else "ירד"


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"].copy()
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]
    tm = re.search(r"אומדן (\S+) לרבעון (\S+) של שנת (\d{4})", latest_rel["TITLE"])
    estimate = ESTIMATES.get(tm.group(1)) if tm else None

    g2 = cbs.grid(frames["t2"], "t2")
    b2 = _t2(g2)
    bm = re.search(r"במחירי (\d{4})", " ".join(g2[cbs.row_with(g2, "נתונים משורשרים", name="t2",
                                                              contains=True)]))
    if not bm:
        raise ValueError("t2: base year of the chained data (במחירי YYYY) not found")
    base_y = bm.group(1)
    b3 = _t3(cbs.grid(frames["t3"], "t3"))
    b4 = _t4(cbs.grid(frames["t4"], "t4"))
    b5 = _t5(cbs.grid(frames["t5"], "t5"))
    percap = _per_capita(frames)

    cur_a = _series(b2, "cur", "A")
    cur_q = _series(b2, "cur", "Q")
    chain_a = _series(b2, "chain", "A")
    chain_q = _series(b2, "chain", "Q")
    sa_q = _series(b2, "sa", "Q")
    pct_q = _series(b2, "pct", "Q")
    if not cur_q or not chain_q or not cur_a:
        raise ValueError("t2: no quarterly or annual rows in the original-data blocks")
    last_t = chain_q[-1][0]
    chain_by = dict(chain_q)

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    gq = pct_q[-1][1]["gdp"] if pct_q and pct_q[-1][0] == last_t else None
    if gq is not None:
        kpis["growth"] = {"value": gq, "display": _p(gq), "tone": _tone(gq, FLAT_BAND)}
        labels["growth_kpi"] = f"שינוי בתוצר ב-{_q(last_t)}, בחישוב שנתי (מנוכה עונתיות)"
    prev_y = (last_t[0] - 1, last_t[1])
    yoy = None
    if prev_y in chain_by and chain_by[prev_y]["gdp"] and chain_by[last_t]["gdp"]:
        yoy = chain_by[last_t]["gdp"] / chain_by[prev_y]["gdp"] - 1
        kpis["yoy"] = {"value": round(yoy, 4), "display": fmt.signed_pct(yoy),
                       "tone": _tone(yoy)}
        labels["yoy_kpi"] = f"תוצר ב-{_q(last_t)} לעומת {_q(prev_y)} (מחירים קבועים)"
    if percap:
        pt, pv = percap[-1]
        kpis["percap"] = {"value": pv, "display": fmt.int_he(pv), "tone": "brand"}
        labels["percap_kpi"] = f"תוצר לנפש ב-{_q(pt)}, ש\"ח במחירי {base_y} (מנוכה עונתיות)"
    ann = [(k[0], v) for k, v in chain_a if v["gdp"]]
    ann_growth = [(y, v["gdp"] / pv_["gdp"] - 1, v, pv_)
                  for (y, v), (py, pv_) in zip(ann[1:], ann[:-1]) if y == py + 1]
    if ann_growth:
        y, g, _, _ = ann_growth[-1]
        kpis["annual"] = {"value": round(g, 4), "display": fmt.signed_pct(g), "tone": _tone(g)}
        labels["annual_kpi"] = f"צמיחת התוצר בשנת {y} (מחירים קבועים)"
    ly, lv = cur_a[-1][0][0], cur_a[-1][1]
    if lv["gdp"]:
        kpis["gdp"] = {"value": lv["gdp"], "display": fmt.int_he(lv["gdp"] / 1000),
                       "tone": "brand"}
        labels["gdp_kpi"] = f"התוצר המקומי הגולמי בשנת {ly}, מיליארדי ש\"ח (מחירים שוטפים)"

    charts, tables, flags = {}, {}, {}
    comps = [("gdp", "תוצר מקומי גולמי"), ("private", "צריכה פרטית"),
             ("public", "צריכה ציבורית"), ("fixed", "השקעה בנכסים קבועים"),
             ("exports", "יצוא"), ("imports", "יבוא")]

    # ── growth by quarter (SA, annual rate) ──────────────────────────────
    if pct_q:
        charts["growth"] = {"x": [_q(k) for k, _ in pct_q],
                            "gdp": [_r1(v["gdp"]) for _, v in pct_q],
                            "business": [_r1(v["business"]) for _, v in pct_q],
                            "gdp_pc": [_r1(v["gdp_pc"]) for _, v in pct_q]}
        tables["growth"] = [[_q(k)] + [_p(v[c]) if v[c] is not None else "–"
                                       for c in ("gdp", "business", "gdp_pc")]
                            for k, v in reversed(pct_q)]
        recent = pct_q[-RECENT_QUARTERS:]
        charts["uses"] = {"names": [lbl for _, lbl in comps],
                          "y": [_r1(pct_q[-1][1][c]) for c, _ in comps]}
        tables["uses"] = [[lbl] + [_p(v[c]) if v[c] is not None else "–" for _, v in recent]
                          for c, lbl in comps]
        labels["uses_cols"] = [_q(k) for k, _ in recent]
    flags["growth"] = bool(pct_q)

    # ── index of SA chained levels ───────────────────────────────────────
    sa_ok = [(k, v) for k, v in sa_q if all(v[c] for c, _ in comps)]
    if len(sa_ok) >= 4:
        base_t, base = sa_ok[0]
        idx = {c: [round(v[c] / base[c] * 100, 1) for _, v in sa_ok] for c, _ in comps}
        charts["index"] = {"x": [_q(k) for k, _ in sa_ok], "names": [lbl for _, lbl in comps],
                           "series": [idx[c] for c, _ in comps]}
        tables["index"] = [[_q(k)] + [fmt.num_he(idx[c][n], 1) for c, _ in comps]
                           for n, (k, _) in reversed(list(enumerate(sa_ok)))]
        labels["index_base"] = _q(base_t)
    flags["index"] = len(sa_ok) >= 4

    # ── GDP per capita since 2015 ────────────────────────────────────────
    if percap:
        charts["percap"] = {"x": [_q(k) for k, _ in percap], "y": [v for _, v in percap]}
        pyears = sorted({k[0] for k, _ in percap})
        pby = dict(percap)
        tables["percap"] = [[str(y)] + [fmt.int_he(pby[(y, q)]) if (y, q) in pby else "–"
                                        for q in range(1, 5)] for y in reversed(pyears)]
    flags["percap"] = bool(percap)

    # ── composition of uses at current prices ────────────────────────────
    share_cols = [("private", "צריכה פרטית"), ("public", "צריכה ציבורית"),
                  ("gcf", "השקעה גולמית"), ("exports", "יצוא")]
    periods = [(str(k[0]), v) for k, v in cur_a if v["uses"]]
    full_years = {k[0] for k, _ in cur_a}
    part = [(k, v) for k, v in cur_q if k[0] > max(full_years)]
    if part:
        sums = {c: sum(v[c] or 0 for _, v in part) for c, _ in share_cols + [("uses", ""),
                                                                              ("gdp", "")]}
        qn = len(part)
        periods.append((f"{part[0][0][0]} (" + ("רבעון 1" if qn == 1 else f"רבעונים 1-{qn}")
                        + ")", sums))
    charts["shares"] = {"x": [p if p.isdigit() else p.split(" ")[0] + "*" for p, _ in periods], "names": [lbl for _, lbl in share_cols],
                        "series": [[round(v[c] / v["uses"] * 100, 1) for _, v in periods]
                                   for c, _ in share_cols]}
    tables["shares"] = [[p] + [fmt.pct(v[c] / v["uses"]) for c, _ in share_cols]
                        + [_bn(v["gdp"]), _bn(v["uses"])] for p, v in periods]

    # ── annual growth by component ───────────────────────────────────────
    if ann_growth:
        charts["annual"] = {"names": [lbl for _, lbl in comps] + ["תוצר לנפש"],
                            "years": [str(y) for y, *_ in ann_growth],
                            "series": [[round((v[c] / pv_[c] - 1) * 100, 1)
                                        if v[c] and pv_[c] else None
                                        for c in [c for c, _ in comps] + ["gdp_pc"]]
                                       for _, _, v, pv_ in ann_growth]}
        tables["annual"] = [[lbl] + [_p(s[n]) if s[n] is not None else "–"
                                     for s in charts["annual"]["series"]]
                            for n, lbl in enumerate(charts["annual"]["names"])]
    flags["annual"] = bool(ann_growth)

    # ── private consumption by type ──────────────────────────────────────
    p3 = _series(b3, "pct", "Q")
    c3 = _series(b3, "cur", "Q")
    if p3:
        last3 = p3[-1][1]
        cats = [(k, lbl) for k, _, lbl in T3_CATS if last3.get(k) is not None]
        cats.sort(key=lambda c: (-last3[c[0]], c[1]))
        charts["cons"] = {"names": [lbl for _, lbl in cats], "y": [_r1(last3[k]) for k, _ in cats]}
        recent3 = p3[-RECENT_QUARTERS:]
        tables["cons"] = [[lbl] + [_p(v[k]) if v[k] is not None else "–" for _, v in recent3]
                          for k, lbl in cats]
        labels["cons_cols"] = [_q(k) for k, _ in recent3]
        labels["cons_q"] = _q(p3[-1][0])
    flags["cons"] = bool(p3)
    mix3 = c3[-4:]
    dom = [k for k, _, _ in T3_CATS if k != "abroad"]
    mix_tot = sum(sum(v[k] or 0 for k in dom) for _, v in mix3)
    mix_items = sorted(((lbl, sum(v[k] or 0 for _, v in mix3)) for k, _, lbl in T3_CATS
                        if k != "abroad"), key=lambda x: (-x[1], x[0]))
    charts["cons_mix"] = [{"name": n, "value": round(v / 1000, 1)} for n, v in mix_items]
    tables["cons_mix"] = [[n, _bn(v), fmt.pct(v / mix_tot) if mix_tot else "–"]
                          for n, v in mix_items]
    labels["cons_mix_span"] = (f"{_q(mix3[0][0])} עד {_q(mix3[-1][0])}" if len(mix3) > 1
                               else _q(mix3[0][0]))

    # ── investment by type ───────────────────────────────────────────────
    c4 = _series(b4, "cur", "Q")
    p4 = _series(b4, "pct", "Q")
    mix4 = c4[-4:]
    inv_items = sorted(((lbl, sum(v[k] or 0 for _, v in mix4)) for k, *_, lbl in T4_CATS),
                       key=lambda x: (-x[1], x[0]))
    inv_tot = sum(v for _, v in inv_items)
    charts["inv"] = {"names": [n for n, _ in inv_items],
                     "y": [round(v / 1000, 1) for _, v in inv_items]}
    p4_last = p4[-1][1] if p4 else {}
    lbl_key = {lbl: k for k, *_, lbl in T4_CATS}
    tables["inv"] = [[n, _bn(v), fmt.pct(v / inv_tot) if inv_tot else "–",
                      _p(p4_last[lbl_key[n]]) if p4_last.get(lbl_key[n]) is not None else "–"]
                     for n, v in inv_items]
    labels["inv_span"] = (f"{_q(mix4[0][0])} עד {_q(mix4[-1][0])}" if len(mix4) > 1
                          else _q(mix4[0][0]))
    labels["inv_pct_col"] = (f"שינוי ב-{_q(p4[-1][0])} (בחישוב שנתי)" if p4
                             else "שינוי ברבעון האחרון")

    # ── public consumption: defence and civilian ─────────────────────────
    ch5 = [(k, v) for k, v in _series(b5, "chain", "Q") if v["defence"] and v["civilian"]]
    charts["public"] = {"x": [_q(k) for k, _ in ch5],
                        "defence": [round(v["defence"] / 1000, 1) for _, v in ch5],
                        "civilian": [round(v["civilian"] / 1000, 1) for _, v in ch5],
                        "share": [round(v["defence"] / (v["defence"] + v["civilian"]) * 100, 1)
                                  for _, v in ch5]}
    tables["public"] = [[_q(k), _bn(v["defence"]), _bn(v["civilian"]),
                         fmt.pct(v["defence"] / (v["defence"] + v["civilian"]))]
                        for k, v in reversed(ch5)]
    flags["public"] = len(ch5) >= 2

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if gq is not None:
        if abs(gq) < FLAT_BAND:
            txt = f"{_in_q(last_t)} התוצר כמעט לא השתנה ({_p(gq)} בחישוב שנתי, מנוכה עונתיות)."
        else:
            txt = (f"{_in_q(last_t)} התוצר {_dir(gq)} ב-{fmt.pct_of(abs(gq))} בחישוב שנתי "
                   f"(נתונים מנוכי עונתיות)")
            if len(pct_q) >= 2 and pct_q[-2][1]["gdp"] is not None:
                txt += f", אחרי {_p(pct_q[-2][1]['gdp'])} ברבעון הקודם"
            txt += "."
        add("growth", txt)
    if pct_q:
        lastv = pct_q[-1][1]
        parts = [(lbl, lastv[c]) for c, lbl in comps[1:5] if lastv[c] is not None]
        if len(parts) >= 2:
            hi = max(parts, key=lambda p: (p[1], p[0]))
            lo = min(parts, key=lambda p: (p[1], p[0]))
            if hi[1] - lo[1] >= 5:
                add("drivers", f"מבין רכיבי השימושים ב-{_q(last_t)}, הקצב הגבוה ביותר היה "
                               f"ב{hi[0]} ({_p(hi[1])} בחישוב שנתי) והנמוך ביותר ב{lo[0]} "
                               f"({_p(lo[1])}).")
    if yoy is not None:
        add("yoy", f"התוצר ב-{_q(last_t)} {'גבוה' if yoy > 0 else 'נמוך'} ב-"
                   f"{fmt.pct(abs(yoy))} מהתוצר ב-{_q(prev_y)}, במחירים קבועים "
                   f"(לפני ניכוי עונתיות).")
    if ann_growth:
        y, g, v, pv_ = ann_growth[-1]
        pc = (v["gdp_pc"] / pv_["gdp_pc"] - 1) if v["gdp_pc"] and pv_["gdp_pc"] else None
        add("annual", f"בשנת {y} צמח התוצר ב-{fmt.pct(g)} במחירים קבועים"
                      + (f", והתוצר לנפש {'עלה' if pc > 0 else 'ירד'} ב-{fmt.pct(abs(pc))}"
                         if pc is not None else "") + "."
            if g > 0 else
            f"בשנת {y} התוצר ירד ב-{fmt.pct(abs(g))} במחירים קבועים.")
    if len(percap) >= 8:
        pt, pv = percap[-1]
        top_t, top_v = max(percap, key=lambda p: (p[1], p[0]))
        if top_t == pt:
            add("percap", f"התוצר לנפש ב-{_q(pt)}, {fmt.int_he(pv)} ש\"ח (במחירי {base_y}, מנוכה "
                          f"עונתיות), הוא הגבוה ביותר בנתונים, שמתחילים ב-{_q(percap[0][0])}.")
        else:
            add("percap", f"התוצר לנפש ב-{_q(pt)} הוא {fmt.int_he(pv)} ש\"ח (במחירי {base_y}), "
                          f"{fmt.pct(abs(pv / top_v - 1))} מתחת לשיא של {_q(top_t)} "
                          f"({fmt.int_he(top_v)} ש\"ח).")
    if len(ch5) >= 2:
        s0 = ch5[0][1]["defence"] / (ch5[0][1]["defence"] + ch5[0][1]["civilian"])
        s1 = ch5[-1][1]["defence"] / (ch5[-1][1]["defence"] + ch5[-1][1]["civilian"])
        peak_t, _ = max(ch5, key=lambda p: (p[1]["defence"], p[0]))
        if abs(s1 - s0) >= DEFENCE_UP:
            add("defence", f"הצריכה הביטחונית היא {fmt.pct(s1)} מהצריכה הציבורית ב-"
                           f"{_q(ch5[-1][0])}, לעומת {fmt.pct(s0)} ב-{_q(ch5[0][0])} "
                           f"(במחירים קבועים). שיא הצריכה הביטחונית בנתונים: {_q(peak_t)}.")
    if periods:
        p, v = periods[-1]
        add("shares", f"הצריכה הפרטית היא {fmt.pct(v['private'] / v['uses'])} מכלל השימושים "
                      f"במקורות ב-{p}, והיצוא {fmt.pct(v['exports'] / v['uses'])} (מחירים "
                      f"שוטפים).")
    if inv_items and inv_tot:
        n0, v0 = inv_items[0]
        add("inv", f"הרכיב הגדול בהשקעה בנכסים קבועים הוא {n0}: {_bn(v0)} מיליארד ש\"ח ב-"
                   f"{labels['inv_span']}, {fmt.pct(v0 / inv_tot)} מכלל ההשקעה.")

    # ── text ─────────────────────────────────────────────────────────────
    rel_date = pd.Timestamp(latest_rel["RELEASE_DATE"])
    release = {"no": latest_rel["RELEASE_NO"], "date": fmt.d_he(rel_date),
               "title": latest_rel["TITLE"], "headline": latest_rel["HEADLINE"],
               "url": latest_rel["PAGE_URL"], "pdf": latest_rel["REPORT_PDF_URL"]}
    est = (f"האומדן ה{ORDINALS[estimate][1:]} " if estimate in ORDINALS else "האומדן האחרון ")
    labels.update({
        "lede": (f"כמה צומח המשק הישראלי, כמה תוצר יש לכל נפש, ולאן הולכים המקורות: צריכה "
                 f"פרטית, צריכה ציבורית, השקעה ויצוא. הנתונים מתוך ההודעות של הלשכה המרכזית "
                 f"לסטטיסטיקה (הלמ\"ס) על החשבונות הלאומיים, שמתפרסמות שלוש פעמים לכל רבעון "
                 f"(אומדן ראשון, שני ושלישי). העמוד מציג את {est}"
                 f"לרבעון {ORDINALS[last_t[1]]} של {last_t[0]}, שפורסם ב-{fmt.d_he(rel_date)}."),
        "growth_note": ("שינוי התוצר בכל רבעון לעומת הרבעון הקודם, בחישוב שנתי (כאילו הקצב "
                        "נמשך שנה שלמה), בנתונים מנוכי עונתיות. זה הנתון שמצוטט בכותרות."),
        "growth_aria": "שינוי התוצר הרבעוני בחישוב שנתי",
        "growth_caption": "שינוי כמותי לעומת הרבעון הקודם, בחישוב שנתי",
        "uses_note": (f"קצב השינוי של כל רכיב ב-{_q(last_t)}, בחישוב שנתי. הטבלה מציגה את "
                      f"{RECENT_QUARTERS} הרבעונים האחרונים."),
        "uses_aria": f"שינוי רכיבי השימושים במקורות ב-{_q(last_t)}",
        "uses_caption": "שינוי רכיבי השימושים במקורות לפי רבעון, בחישוב שנתי",
        "index_note": ("רמת כל רכיב לעומת הרבעון הראשון בנתונים (=100), במחירים קבועים "
                       "ומנוכה עונתיות. כך רואים איזה רכיב התאושש ואיזה עוד מתחת לנקודת "
                       "הפתיחה."),
        "index_aria": "מדד רכיבי השימושים במקורות, מנוכה עונתיות",
        "index_caption": "מדד רכיבי השימושים במקורות (הרבעון הראשון = 100)",
        "percap_note": (f"התוצר המקומי הגולמי לנפש בכל רבעון מאז {_q(percap[0][0])}, בשקלים "
                        f"במחירי {base_y} ומנוכה עונתיות. אפשר לגרור כדי להתמקד בתקופה."
                        if percap else ""),
        "percap_aria": "תוצר לנפש לפי רבעון, מנוכה עונתיות",
        "percap_caption": f"תוצר לנפש לפי שנה ורבעון (ש\"ח, מחירי {base_y})",
        "shares_note": ("חלקו של כל רכיב בסך השימושים במקורות (התוצר ועוד היבוא), במחירים "
                        "שוטפים. שנה שמסומנת בכוכבית היא שנה חלקית: סכום הרבעונים שפורסמו עד כה."),
        "shares_aria": "הרכב השימושים במקורות לפי שנה",
        "shares_caption": "הרכב השימושים במקורות (אחוזים, מחירים שוטפים)",
        "annual_note": "שיעור השינוי השנתי של כל רכיב במחירים קבועים (נתונים משורשרים).",
        "annual_aria": "שינוי שנתי ברכיבי התוצר",
        "annual_caption": "שינוי שנתי ברכיבי התוצר, מחירים קבועים",
        "cons_note": (f"שינוי ההוצאה לצריכה פרטית לפי סוג ב-{labels.get('cons_q', '')}, "
                      f"בחישוב שנתי ומנוכה עונתיות. מוצרים בני קיימה (רכב, ריהוט, חשמל) "
                      f"תנודתיים הרבה יותר משירותים ומזון."),
        "cons_aria": "שינוי ההוצאה לצריכה פרטית לפי סוג",
        "cons_caption": "שינוי ההוצאה לצריכה פרטית לפי סוג, בחישוב שנתי",
        "cons_mix_note": (f"על מה מוציאים משקי הבית בשוק המקומי: סכום {len(mix3)} הרבעונים "
                          f"האחרונים ({labels['cons_mix_span']}), במיליארדי ש\"ח במחירים "
                          f"שוטפים."),
        "cons_mix_aria": "הרכב ההוצאה לצריכה פרטית בשוק המקומי",
        "cons_mix_caption": "הוצאה לצריכה פרטית לפי סוג (מיליארדי ש\"ח)",
        "inv_note": (f"ההשקעה בנכסים קבועים לפי סוג נכס: סכום {len(mix4)} הרבעונים האחרונים "
                     f"({labels['inv_span']}), במיליארדי ש\"ח במחירים שוטפים."),
        "inv_aria": "השקעה בנכסים קבועים לפי סוג",
        "inv_caption": "השקעה בנכסים קבועים לפי סוג (מיליארדי ש\"ח)",
        "public_note": (f"הצריכה הציבורית בכל רבעון, ביטחונית ואזרחית, במיליארדי ש\"ח במחירי "
                        f"{base_y} (לא מנוכה עונתיות). הקו מציג את חלק הצריכה הביטחונית."),
        "public_aria": "צריכה ציבורית ביטחונית ואזרחית לפי רבעון",
        "public_caption": f"צריכה ציבורית לפי רבעון (מיליארדי ש\"ח, מחירי {base_y})",
        "base_year": base_y,
        "comp_names": [lbl for _, lbl in comps],
    })

    first_y = min(percap[0][0][0] if percap else cur_a[0][0][0], cur_a[0][0][0])
    summary = ("התוצר המקומי הגולמי של ישראל לפי רבעון, התוצר לנפש והשימושים במקורות, מנתוני "
               "הלמ\"ס. "
               + (f"ב-{_q(last_t)} התוצר {_dir(gq)} ב-{fmt.pct_of(abs(gq))} בחישוב שנתי."
                  if gq is not None else f"הנתון האחרון: {_q(last_t)}."))
    desc = ("צמיחת התוצר של ישראל לפי רבעון"
            + (f": {_p(gq)} בחישוב שנתי ב-{_q(last_t)}" if gq is not None else "")
            + (f". תוצר לנפש {fmt.int_he(percap[-1][1])} ש\"ח" if percap else "")
            + ". צריכה, השקעה ויצוא.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_y}/{last_t[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "צמיחת התוצר בישראל: תמ\"ג רבעוני ותוצר לנפש | הלמ\"ס",
                "description": desc,
                "name": "התוצר המקומי הגולמי (תמ\"ג) של ישראל",
                "alternate_names": ["חשבונות לאומיים", "צמיחת המשק הישראלי",
                                    "תוצר לנפש בישראל", "אומדן התוצר הרבעוני",
                                    "התוצר המקומי הגולמי של ישראל: אומדנים רבעוניים"],
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
