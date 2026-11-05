"""מאזן התשלומים של ישראל: CBS's quarterly balance-of-payments release.

Inputs are CBS grid tables ($ million) from the newest edition. The fourth
quarter comes out as the yearly summary ("…לשנת 2025"), with the same tables.
  t1   summary: a seasonally adjusted block (current account) and an original
       block (current, capital and financial accounts) with quarterly columns
       for about 4.5 years and annual columns for the last full years
  t2   current account: goods and services separately (SA and original side
       by side, then annual columns)
  t3   trade in goods by type: excl. diamonds/ships, diamonds, ships and
       aircraft, the Palestinian Authority; merchanting (original block)
  t4   trade in services by type (travel, transport, business services, …)
  t5   primary income by investment type (direct, portfolio, other, reserves)
  t8   international investment position and external debt (quarter ends)
  releases  the edition list (number, date, link)

Quarter columns sit newest first under a period row (`IV-VI`, `I-III`,
`X-XII`, …) and a year row that names the year on its first quarter and on
each `X-XII`; the other cells of that row hold stray filler years, so years
are counted from the first column and checked against every `X-XII` label.
Header rows are found by their English label and raise when missing; a
section whose rows sit low in a sheet is optional (its flag turns off).
"""
import pandas as pd
from govlib import cbs, fmt

QUARTERS = {"I-III": 1, "IV-VI": 2, "VII-IX": 3, "X-XII": 4}
Q_ORD = {1: "הראשון", 2: "השני", 3: "השלישי", 4: "הרביעי"}


# ── grid layout ──────────────────────────────────────────────────────────


def _prev(t):
    y, q = t
    return (y - 1, 4) if q == 1 else (y, q - 1)


def _layout(rows, start, name):
    """The first period row at or after `start`: (row index, runs, annual).
    runs = [[(col, (year, quarter)), …], …], each run newest first;
    annual = [(col, year)] for the year columns right of the last run."""
    for i in range(max(0, start), len(rows)):
        if sum(c in QUARTERS for c in rows[i]) >= 4:
            break
    else:
        raise ValueError(f"{name}: quarter header row not found")
    r = rows[i]
    runs, cur = [], []
    for j, c in enumerate(r):
        if c not in QUARTERS:
            if cur:
                runs.append(cur)
                cur = []
            continue
        q = QUARTERS[c]
        if cur and q != (cur[-1][1] - 2) % 4 + 1:
            runs.append(cur)
            cur = []
        cur.append((j, q))
    if cur:
        runs.append(cur)
    out = []
    for run in runs:
        j0 = run[0][0]
        yrow = next((rows[k] for k in (i - 1, i - 2)
                     if k >= 0 and cbs.YEAR.match(cbs.cell(rows[k], j0))), None)
        if yrow is None:
            raise ValueError(f"{name}: no year above the first quarter column")
        t = (int(cbs.cell(yrow, j0)), run[0][1])
        cols = []
        for j, q in run:
            if cols:
                t = _prev(t)
            if t[1] != q:
                raise ValueError(f"{name}: quarter order broken at column {j}")
            lab = cbs.cell(yrow, j)
            if q == 4 and cbs.YEAR.match(lab) and int(lab) != t[0]:
                if not cols or int(lab) < t[0]:
                    raise ValueError(f"{name}: year {lab} over X-XII, expected {t[0]}")
                # A newer year after an I-III: the next block (original data
                # after seasonally adjusted) starts here, also on X-XII.
                out.append(cols)
                cols, t = [], (int(lab), 4)
            cols.append((j, t))
        out.append(cols)
    last = out[-1][-1][0]
    annual = [(j, int(c)) for j, c in enumerate(r) if j > last and cbs.YEAR.match(c)]
    return i, out, annual


def _row(rows, label, start, name, stop=None):
    """Index of the row whose cell equals `label`, at or after `start`
    (and before `stop`). Raises when it is missing."""
    i = cbs.row_with(rows, label, start, name=name)
    if stop is not None and i >= stop:
        raise ValueError(f"{name}: {label!r} not found before row {stop}")
    return i


def _find(rows, label, start):
    try:
        return cbs.row_with(rows, label, start)
    except ValueError:
        return None


def _series(rows, i, cols):
    """{(year, quarter): value} of row i over the quarter columns."""
    return {t: v for j, t in cols if (v := cbs.val(rows[i], j)) is not None}


def _annual(rows, i, annual):
    return {y: v for j, y in annual if (v := cbs.val(rows[i], j)) is not None}


def _pick(rows, start, labels, cols, name, stop=None):
    return {k: _series(rows, _row(rows, lab, start, name, stop), cols)
            for k, lab in labels.items()}


# ── formatting ───────────────────────────────────────────────────────────


def _qshort(t):
    return f"ר{t[1]} {t[0]}"


def _qlong(t):
    return f"הרבעון {Q_ORD[t[1]]} של {t[0]}"


def _qb(t):
    """"ברבעון השני של 2026"."""
    return f"ברבעון {Q_ORD[t[1]]} של {t[0]}"


def _musd(v):
    """$ million, signed with U+2212."""
    return ("−" if v < 0 else "") + fmt.int_he(abs(v))


def _busd(v, d=1):
    """$ million as $ billion."""
    return ("−" if v < 0 else "") + fmt.num_he(abs(v) / 1000, d)


def _bal(v):
    """Surplus or deficit in words, $ million."""
    return (f"עודף של {fmt.int_he(v)} מיליון דולר" if v >= 0
            else f"גירעון של {fmt.int_he(-v)} מיליון דולר")


def _sum(d, ts):
    vals = [d.get(t) for t in ts]
    return sum(vals) if all(v is not None for v in vals) else None


def _r(v):
    return None if v is None else round(v)


# ── tables ───────────────────────────────────────────────────────────────


def _t1(rows):
    sa0 = _row(rows, "Seasonally adjusted data", 0, "t1")
    i, runs, _ = _layout(rows, sa0, "t1")
    sa_cols = runs[0]
    nsa0 = _row(rows, "Not seasonally adjusted data", i + 1, "t1")
    bal = _row(rows, "Balances", i, "t1", nsa0)
    sa = _pick(rows, bal, {"trade": "Trade in goods and services", "primary": "Primary income",
                           "secondary": "Secondary income (current transfers)",
                           "current": "Current balance", "capital": "Capital balance"},
               sa_cols, "t1", nsa0)
    k, nruns, annual = _layout(rows, nsa0, "t1")
    ncols = nruns[0]
    out = {"sa": sa, "sa_cols": sa_cols, "annual": {}, "fin": None}
    # The annual columns and the financial account sit lower in the sheet:
    # both are optional.
    try:
        rec = _row(rows, "Receipts", k, "t1")
        pay = _row(rows, "Payments", rec, "t1")
        b2 = _row(rows, "Balances", pay, "t1")
        out["annual"] = {
            "exports": _annual(rows, _row(rows, "Exports of goods and services", rec, "t1"), annual),
            "imports": _annual(rows, _row(rows, "Imports of goods and services", pay, "t1"), annual),
            "trade": _annual(rows, _row(rows, "Trade in goods and services", b2, "t1"), annual),
            "primary": _annual(rows, _row(rows, "Primary income", b2, "t1"), annual),
            "current": _annual(rows, _row(rows, "Current balance", b2, "t1"), annual),
        }
    except ValueError:
        pass
    try:
        ab = _row(rows, "Investments abroad", k, "t1")
        il = _row(rows, "Investments in Israel", ab, "t1")
        out["fin"] = {
            "di_abroad": _series(rows, _row(rows, "Direct investment", ab, "t1", il), ncols),
            "pf_abroad": _series(rows, _row(rows, "Portfolio investment", ab, "t1", il), ncols),
            "di_israel": _series(rows, _row(rows, "Direct investment", il, "t1"), ncols),
            "pf_israel": _series(rows, _row(rows, "Portfolio investment", il, "t1"), ncols),
        }
        di = _row(rows, "Direct investment", il, "t1")
        out["fin"]["di_israel_y"] = _annual(rows, di, annual)
        out["fin"]["di_abroad_y"] = _annual(
            rows, _row(rows, "Direct investment", ab, "t1", il), annual)
    except ValueError:
        out["fin"] = None
    return out


def _t2(rows):
    i, runs, _ = _layout(rows, 0, "t2")
    if len(runs) < 2:
        raise ValueError("t2: expected seasonally adjusted and original quarter blocks")
    cols = runs[0]
    rec = _row(rows, "A. Receipts", i, "t2")
    pay = _row(rows, "B. Payments", rec, "t2")
    out = _pick(rows, rec, {"x_goods": "Exports of goods", "x_serv": "Exports of services"},
                cols, "t2", pay)
    out.update(_pick(rows, pay, {"m_goods": "Imports of goods", "m_serv": "Imports of services"},
                     cols, "t2"))
    out["cols"], out["nsa_cols"] = cols, runs[1]
    out["x_goods_nsa"] = _series(rows, _row(rows, "Exports of goods", rec, "t2", pay), runs[1])
    try:
        bal = _row(rows, "C. Balances", pay, "t2")
        out.update(_pick(rows, bal, {"b_goods": "Trade in goods", "b_serv": "Trade in services"},
                         cols, "t2"))
    except ValueError:
        out["b_goods"] = out["b_serv"] = None
    return out


def _match(a, b, name):
    """Raise unless two {quarter: value} series agree (to rounding) on every
    quarter they share, and share at least four."""
    both = [t for t in a if t in b]
    if len(both) < 4 or any(abs(a[t] - b[t]) > 2 for t in both):
        raise ValueError(f"{name}: columns don't line up with t2")


def _t3(rows, t2):
    """Goods by type. t3's period labels can't be trusted (the yearly
    edition's header repeats VII-IX over X-XII and drops a cell), so its
    columns take t2's quarter order, column 1 onward, and the total row must
    then match t2's goods exports. A mismatch drops the section."""
    cols = [(k + 1, t) for k, (_, t) in enumerate(t2["cols"])]
    x0 = _row(rows, "1. Exports of goods", 0, "t3")
    m0 = _row(rows, "2. Imports of goods", x0, "t3")
    out = _pick(rows, x0, {"main": "Exports of goods (excl. ships, aircraft and diamonds)",
                           "ships": "Exports of ships and aircraft",
                           "diamonds": "Exports of diamonds",
                           "pa": "Exports to the Palestinian Authority",
                           "total": "Total exports of goods"}, cols, "t3", m0)
    _match(out["total"], t2["x_goods"], "t3")
    out["merch"] = None
    try:
        ncols = [(k + 1, t) for k, (_, t) in enumerate(t2["nsa_cols"])]
        n0 = _row(rows, "Not seasonally adjusted data", m0, "t3")
        nx = _row(rows, "1. Exports of goods", n0, "t3")
        m = _row(rows, "Thereof: Net exports of goods under merchanting", nx, "t3")
        tot = _row(rows, "Total exports of goods", m, "t3")
        merch = {"q": _series(rows, m, ncols), "tot_q": _series(rows, tot, ncols)}
        _match(merch["tot_q"], t2["x_goods_nsa"], "t3 original")
        out["merch"] = merch
    except ValueError:
        out["merch"] = None
    return out


SERVICE_TYPES = [("business", "Business Services", "שירותים עסקיים"),
                 ("transport", "Total transportation services", "תחבורה"),
                 ("travel", "Total travel services", "תיירות"),
                 ("insurance", "Insurance services", "ביטוח"),
                 ("gov", "Government services, n.e.c.", "שירותי ממשלה")]


def _t4(rows):
    i, runs, _ = _layout(rows, 0, "t4")
    if len(runs) < 2:
        raise ValueError("t4: expected seasonally adjusted and original quarter blocks")
    cols = runs[0]
    x0 = _row(rows, "1. Exports of services", i, "t4")
    tot = _row(rows, "Total exports of services", x0, "t4")
    out = {k: _series(rows, _row(rows, lab, x0, "t4", tot), cols) for k, lab, _ in SERVICE_TYPES}
    out["total"] = _series(rows, tot, cols)
    out["cols"] = cols
    try:
        out["startups"] = _series(rows, cbs.row_with(
            rows, "Of which: Exports of services from start-up companies", x0, name="t4",
            contains=True), cols)
    except ValueError:
        out["startups"] = {}
    return out


INCOME_TYPES = [("direct", "2.1 Income on direct investment", "השקעות ישירות"),
                ("portfolio", "2.2 Income on portfolio investment", "השקעות בניירות ערך"),
                ("other", "2.3 Income on other investments", "השקעות אחרות"),
                ("reserve", "2.4 Income on reserve assets", "נכסי רזרבה"),
                ("wages", "1. Compensation of employees", "שכר עבודה")]


def _t5(rows):
    """Net primary income by type (SA). The balances sit at the bottom of the
    sheet, so the whole section is optional."""
    i, runs, _ = _layout(rows, 0, "t5")
    cols = runs[0]
    out = {"cols": cols}
    try:
        pay = _row(rows, "B. Payments", i, "t5")
        di_eq = _row(rows, "2.1.1 Income on equity", pay, "t5")
        out["di_paid"] = _series(rows, di_eq, cols)
        bal = _row(rows, "C. Balances", pay, "t5")
        out["net"] = {k: _series(rows, _row(rows, lab, bal, "t5"), cols)
                      for k, lab, _ in INCOME_TYPES}
        # Labelled "Total net primary income" or "Total primary income".
        tot = min(i for i in (_find(rows, lab, bal) for lab in ("Total net primary income",
                                                                "Total primary income"))
                  if i is not None)
        out["net_total"] = _series(rows, tot, cols)
    except ValueError:
        return None
    return out


def _t8(rows):
    """Quarter-end positions; liabilities and debt sit low: optional parts."""
    i, runs, _ = _layout(rows, 0, "t8")
    cols = runs[0]
    a = _row(rows, "A. Assets", i, "t8")
    out = {"cols": cols, "assets": _series(rows, _row(rows, "Assets - total", a, "t8"), cols)}
    try:
        lb = _row(rows, "B. Liabilities", a, "t8")
        out["liab"] = _series(rows, _row(rows, "Liabilities - total", lb, "t8"), cols)
        nl = _row(rows, "C. Net liabilities", lb, "t8")
        out["net"] = _series(rows, _row(rows, "Net liabilities - total", nl, "t8"), cols)
    except ValueError:
        return None
    try:
        d = _row(rows, "D. External debt", nl, "t8")
        out["gross_debt"] = _series(rows, _row(rows, "Gross external debt", d, "t8"), cols)
        out["net_debt"] = _series(rows, _row(rows, "Net external debt", d, "t8"), cols)
    except ValueError:
        out["gross_debt"] = out["net_debt"] = {}
    return out


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    t1 = _t1(cbs.grid(frames["t1"], "t1"))
    t2 = _t2(cbs.grid(frames["t2"], "t2"))
    try:
        t3 = _t3(cbs.grid(frames["t3"], "t3"), t2)
    except ValueError:
        t3 = None
    t4 = _t4(cbs.grid(frames["t4"], "t4"))
    t5 = _t5(cbs.grid(frames["t5"], "t5"))
    t8 = _t8(cbs.grid(frames["t8"], "t8"))

    sa = t1["sa"]
    qs = sorted(sa["current"])
    if not qs:
        raise ValueError("t1: no seasonally adjusted current balance")
    lt = qs[-1]
    ya = (lt[0] - 1, lt[1])
    cur = sa["current"][lt]
    last4 = [t for t in qs if t > (lt[0] - 1, lt[1])]
    prev4 = [t for t in qs if (lt[0] - 2, lt[1]) < t <= ya]

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis["current"] = {"value": round(cur), "display": _musd(cur),
                       "tone": "ok" if cur > 0 else "danger" if cur < 0 else "warn"}
    labels["current_kpi"] = f"החשבון השוטף, {_qshort(lt)} (מיליוני דולרים, מנוכה עונתיות)"
    if lt in sa["trade"]:
        v = sa["trade"][lt]
        kpis["trade"] = {"value": round(v), "display": _musd(v), "tone": "ok" if v > 0 else "danger"}
        labels["trade_kpi"] = "עודף (גירעון) בסחר סחורות ושירותים (מיליוני דולרים)"
    if lt in sa["primary"]:
        v = sa["primary"][lt]
        kpis["primary"] = {"value": round(v), "display": _musd(v),
                           "tone": "ok" if v > 0 else "warn"}
        labels["primary_kpi"] = "הכנסות ראשוניות נטו: ריבית, דיבידנדים ורווחים (מיליוני דולרים)"
    fin = t1["fin"]
    if fin and lt in fin["di_israel"]:
        v = fin["di_israel"][lt]
        kpis["fdi"] = {"value": round(v), "display": _musd(v), "tone": "info"}
        labels["fdi_kpi"] = f"השקעות ישירות של תושבי חו\"ל בישראל, {_qshort(lt)} (מיליוני דולרים)"
    if t8 and lt in t8["net"]:
        v = -t8["net"][lt]
        kpis["iip"] = {"value": round(v), "display": _busd(v),
                       "tone": "ok" if v > 0 else "danger"}
        labels["iip_kpi"] = ("עודף הנכסים של המשק על התחייבויותיו לחו\"ל (מיליארדי דולרים)"
                             if v > 0 else "עודף ההתחייבויות של המשק לחו\"ל על נכסיו (מיליארדי דולרים)")

    # ── chart: current account by component ──────────────────────────────
    charts["current"] = {"x": [_qshort(t) for t in qs],
                         "trade": [_r(sa["trade"].get(t)) for t in qs],
                         "primary": [_r(sa["primary"].get(t)) for t in qs],
                         "secondary": [_r(sa["secondary"].get(t)) for t in qs],
                         "current": [_r(sa["current"].get(t)) for t in qs]}
    tables["current"] = [[_qshort(t)] + [_musd(sa[k][t]) if t in sa[k] else "–"
                                         for k in ("trade", "primary", "secondary", "current")]
                         for t in reversed(qs)]

    # ── chart: goods and services, exports and imports ────────────────────
    tq = sorted(t2["x_goods"])
    charts["trade"] = {"x": [_qshort(t) for t in tq],
                       **{k: [_r(t2[k].get(t)) for t in tq]
                          for k in ("x_goods", "x_serv", "m_goods", "m_serv")}}
    tables["trade"] = [[_qshort(t)] + [_musd(t2[k][t]) if t in t2[k] else "–"
                                       for k in ("x_goods", "x_serv", "m_goods", "m_serv")]
                       for t in reversed(tq)]

    # ── chart: exports of goods by type ───────────────────────────────────
    flags["goods"] = bool(t3 and t3["total"])
    gq = sorted(t3["total"]) if flags["goods"] else []
    if flags["goods"]:
        charts["goods"] = {"x": [_qshort(t) for t in gq],
                           **{k: [_r(t3[k].get(t)) for t in gq]
                              for k in ("main", "diamonds", "ships", "pa")}}
        tables["goods"] = [[_qshort(t)] + [_musd(t3[k][t]) if t in t3[k] else "–"
                                           for k in ("main", "diamonds", "ships", "pa", "total")]
                           for t in reversed(gq)]

    # ── chart: exports of services by type ────────────────────────────────
    sq = sorted(t4["total"])
    charts["services"] = {"x": [_qshort(t) for t in sq],
                          "names": [h for _, _, h in SERVICE_TYPES],
                          "series": [[_r(t4[k].get(t)) for t in sq] for k, _, _ in SERVICE_TYPES]}
    tables["services"] = [[_qshort(t)] + [_musd(t4[k][t]) if t in t4[k] else "–"
                                          for k, _, _ in SERVICE_TYPES]
                          + [_musd(t4["total"][t])] for t in reversed(sq)]
    labels["services_cols"] = ["רבעון"] + [h for _, _, h in SERVICE_TYPES] + ["סך הכל"]

    # ── chart: primary income by type ─────────────────────────────────────
    flags["income"] = bool(t5 and t5["net_total"])
    if flags["income"]:
        iq = sorted(t5["net_total"])
        charts["income"] = {"x": [_qshort(t) for t in iq],
                            "names": [h for _, _, h in INCOME_TYPES],
                            "series": [[_r(t5["net"][k].get(t)) for t in iq]
                                       for k, _, _ in INCOME_TYPES],
                            "total": [_r(t5["net_total"].get(t)) for t in iq]}
        tables["income"] = [[_qshort(t)] + [_musd(t5["net"][k][t]) if t in t5["net"][k] else "–"
                                            for k, _, _ in INCOME_TYPES]
                            + [_musd(t5["net_total"][t]) if t in t5["net_total"] else "–"]
                            for t in reversed(iq)]
        labels["income_cols"] = ["רבעון"] + [h for _, _, h in INCOME_TYPES] + ["סך הכל"]

    # ── chart: direct investment ──────────────────────────────────────────
    flags["fdi"] = bool(fin and fin["di_israel"] and fin["di_abroad"])
    if flags["fdi"]:
        fq = sorted(set(fin["di_israel"]) | set(fin["di_abroad"]))
        charts["fdi"] = {"x": [_qshort(t) for t in fq],
                         "israel": [_r(fin["di_israel"].get(t)) for t in fq],
                         "abroad": [_r(fin["di_abroad"].get(t)) for t in fq],
                         "pf_israel": [_r(fin["pf_israel"].get(t)) for t in fq],
                         "pf_abroad": [_r(fin["pf_abroad"].get(t)) for t in fq]}
        tables["fdi"] = [[_qshort(t)] + [_musd(fin[k][t]) if t in fin[k] else "–"
                                         for k in ("di_israel", "di_abroad", "pf_israel",
                                                   "pf_abroad")]
                         for t in reversed(fq)]

    # ── chart: annual ─────────────────────────────────────────────────────
    an = t1["annual"]
    years = sorted(an.get("current", {}))
    flags["annual"] = len(years) >= 2
    if flags["annual"]:
        charts["annual"] = {"x": [str(y) for y in years],
                            **{k: [_r(an[k].get(y)) for y in years]
                               for k in ("exports", "imports", "current")}}
        tables["annual"] = [[str(y)] + [_musd(an[k][y]) if y in an[k] else "–"
                                        for k in ("exports", "imports", "trade", "primary",
                                                  "current")]
                            for y in reversed(years)]
        ly = years[-1]
        v = an["current"][ly]
        kpis["annual"] = {"value": round(v), "display": _busd(v),
                          "tone": "ok" if v > 0 else "danger"}
        labels["annual_kpi"] = f"החשבון השוטף בשנת {ly} כולה (מיליארדי דולרים)"

    # ── chart: investment position ────────────────────────────────────────
    flags["iip"] = bool(t8 and t8["net"])
    if flags["iip"]:
        pq = sorted(t8["assets"])
        charts["iip"] = {"x": [_qshort(t) for t in pq],
                         "assets": [round(t8["assets"][t] / 1000, 1) for t in pq],
                         "liab": [round(t8["liab"][t] / 1000, 1) if t in t8["liab"] else None
                                  for t in pq],
                         "net": [round(-t8["net"][t] / 1000, 1) if t in t8["net"] else None
                                 for t in pq],
                         "debt": [round(t8["gross_debt"][t] / 1000, 1)
                                  if t in t8["gross_debt"] else None for t in pq]}
        tables["iip"] = [[_qshort(t), _busd(t8["assets"][t]),
                          _busd(t8["liab"][t]) if t in t8["liab"] else "–",
                          _busd(-t8["net"][t]) if t in t8["net"] else "–",
                          _busd(t8["gross_debt"][t]) if t in t8["gross_debt"] else "–"]
                         for t in reversed(pq)]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    prev = sa["current"].get(_prev(lt))
    deficits = 0
    for t in reversed(qs):
        if sa["current"][t] < 0:
            deficits += 1
        else:
            break
    if prev is not None:
        streak = (f" זה הרבעון ה-{deficits} ברציפות עם גירעון." if deficits >= 2
                  else f" לפני כן נרשם עודף בכל רבעון מאז {_qlong(qs[0])}."
                  if deficits == 1 and all(sa["current"][t] >= 0 for t in qs[:-1])
                  and len(qs) >= 5 else "")
        add("current", f"{_qb(lt)} נרשם בחשבון השוטף {_bal(cur)} (נתונים מנוכי "
                       f"עונתיות), לעומת {_bal(prev)} {_qb(_prev(lt))}.{streak}")

    p_now, p_then = _sum(sa["primary"], last4), _sum(sa["primary"], prev4)
    tr_now = _sum(sa["trade"], last4)
    if len(last4) == 4 and len(prev4) == 4 and p_now is not None and p_then is not None:
        if p_now < 0 and p_then < 0 and p_now / p_then >= 1.5:
            add("primary", f"הגירעון בהכנסות הראשוניות (תשלומי ריבית, דיבידנדים ורווחים "
                           f"למשקיעים זרים, פחות ההכנסות מהשקעות בחו\"ל) הגיע ל-"
                           f"{fmt.int_he(-p_now)} מיליון דולר בארבעת הרבעונים האחרונים, פי "
                           f"{fmt.num_he(p_now / p_then, 1)} מבארבעת הרבעונים שלפניהם."
                           + (f" הוא קיזז {fmt.pct(-p_now / tr_now)} מהעודף בסחר בסחורות "
                              f"ובשירותים באותה תקופה." if tr_now and tr_now > 0
                              and -p_now >= 0.5 * tr_now else ""))
        elif p_now < 0 and p_then < 0 and p_then / p_now >= 1.5:
            add("primary", f"הגירעון בהכנסות הראשוניות ירד ל-{fmt.int_he(-p_now)} מיליון "
                           f"דולר בארבעת הרבעונים האחרונים, לעומת {fmt.int_he(-p_then)} "
                           f"מיליון בארבעת הרבעונים שלפניהם.")

    if t2["b_goods"] and t2["b_serv"]:
        g, s = _sum(t2["b_goods"], last4), _sum(t2["b_serv"], last4)
        if g is not None and s is not None and g < 0 < s:
            add("mix", f"מבנה הסחר של ישראל: בארבעת הרבעונים האחרונים נרשם גירעון של "
                       f"{fmt.int_he(-g)} מיליון דולר בסחר בסחורות, ועודף גדול יותר, "
                       f"{fmt.int_he(s)} מיליון, בסחר בשירותים."
                if s > -g else
                f"בארבעת הרבעונים האחרונים נרשם גירעון של {fmt.int_he(-g)} מיליון דולר "
                f"בסחר בסחורות ועודף של {fmt.int_he(s)} מיליון בסחר בשירותים.")

    if lt in t4["business"] and t4["total"].get(lt):
        share = t4["business"][lt] / t4["total"][lt]
        if share >= 0.5:
            add("services", f"השירותים העסקיים (בעיקר שירותי מחשוב, מחקר ופיתוח, הייטק) הם "
                            f"{fmt.pct(share)} מיצוא השירותים {_qb(lt)}: "
                            f"{fmt.int_he(t4['business'][lt])} מיליון דולר.")

    if flags["fdi"] and len(fin["di_israel"]) >= 8:
        fi = fin["di_israel"]
        top = max(fi, key=lambda t: (fi[t], t))
        recent = [t for t in fi if t >= (lt[0] - 1, lt[1])]
        if top in recent:
            add("fdi", f"ההשקעות הישירות של תושבי חו\"ל בישראל הגיעו לשיא של התקופה "
                       f"{_qb(top)}: {fmt.int_he(fi[top])} מיליון דולר (נתונים מקוריים, "
                       f"מאז {_qlong(min(fi))}).")
        fa = fin["di_abroad"]
        neg = [t for t in sorted(fa) if t in recent and fa[t] < 0]
        if neg:
            t = neg[-1]
            add("fdi_out", f"{_qb(t)} ההשקעות הישירות של ישראלים בחו\"ל היו שליליות "
                           f"({_musd(fa[t])} מיליון דולר): משקיעים ישראלים מימשו יותר "
                           f"השקעות בחו\"ל משביצעו.")

    if flags["annual"] and len(years) >= 2:
        y1, y0 = years[-1], years[-2]
        c1, c0 = an["current"][y1], an["current"].get(y0)
        if c0:
            ch = c1 / c0 - 1
            if abs(ch) >= 0.05 and c0 > 0 and c1 > 0:
                add("annual", f"בשנת {y1} כולה נרשם בחשבון השוטף עודף של "
                              f"{fmt.num_he(c1 / 1000, 1)} מיליארד דולר, "
                              f"{'עלייה' if ch > 0 else 'ירידה'} של {fmt.pct(abs(ch))} "
                              f"לעומת {y0}.")
            elif c1 * c0 < 0 or abs(ch) >= 0.05:
                add("annual", f"בשנת {y1} כולה נרשם בחשבון השוטף {_bal(c1)}, לעומת "
                              f"{_bal(c0)} ב-{y0}.")

    d = t3["diamonds"] if t3 else {}
    dq = sorted(d)
    if len(dq) >= 8 and d[dq[0]] and d[dq[-1]] / d[dq[0]] <= 0.5:
        add("diamonds", f"יצוא היהלומים ירד מ-"
                        f"{fmt.int_he(d[dq[0]])} מיליון דולר {_qb(dq[0])} ל-"
                        f"{fmt.int_he(d[dq[-1]])} מיליון {_qb(dq[-1])} (נתונים "
                        f"מנוכי עונתיות).")

    mr = t3["merch"] if t3 else None
    if mr and lt in mr["q"] and mr["tot_q"].get(lt):
        share = mr["q"][lt] / mr["tot_q"][lt]
        if share >= 0.2:
            add("merch", f"{fmt.pct(share)} מיצוא הסחורות {_qb(lt)} "
                         f"({fmt.int_he(mr['q'][lt])} מיליון דולר) הם סחר מעבר: "
                         f"סחורות שחברות ישראליות קנו ומכרו בחו\"ל בלי "
                         f"שעברו בישראל.")

    if flags["iip"] and lt in t8["net"]:
        nv = -t8["net"][lt]
        old = t8["net"].get(ya)
        if nv > 0 and old is not None:
            add("iip", f"בסוף {_qlong(lt)} עלו נכסי המשק בחו\"ל על התחייבויותיו לחו\"ל ב-"
                       f"{fmt.num_he(nv / 1000, 1)} מיליארד דולר, לעומת "
                       f"{fmt.num_he(-old / 1000, 1)} מיליארד שנה קודם.")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"כמה כסף נכנס לישראל מחו\"ל וכמה יוצא ממנה: יצוא ויבוא של סחורות "
                 f"ושירותים, ריבית ודיבידנדים, העברות, והשקעות. הנתונים מתוך ההודעה "
                 f"הרבעונית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על מאזן התשלומים, "
                 f"ומתעדכנים עם כל הודעה חדשה. הרבעון האחרון בנתונים הוא {_qlong(lt)}: "
                 f"{_bal(cur)} בחשבון השוטף."),
        "current_note": (f"החשבון השוטף הוא סכום ארבעה רכיבים: הסחר בסחורות ובשירותים, "
                         f"ההכנסות הראשוניות (ריבית, דיבידנדים ושכר), וההכנסות המשניות "
                         f"(העברות). הקו הוא העודף או הגירעון הכולל בכל רבעון, מנוכה "
                         f"עונתיות, מאז {_qlong(qs[0])}."),
        "current_aria": f"החשבון השוטף לפי רכיבים, {_qshort(qs[0])} עד {_qshort(qs[-1])}",
        "current_caption": "החשבון השוטף לפי רכיבים (מיליוני דולרים, מנוכה עונתיות)",
        "trade_note": ("היצוא והיבוא של סחורות ושל שירותים בכל רבעון, מנוכה עונתיות. "
                       "ביצוא השירותים ישראל מוכרת לעולם יותר משהיא קונה, ובסחורות "
                       "להפך."),
        "trade_aria": f"יצוא ויבוא של סחורות ושירותים, {_qshort(tq[0])} עד {_qshort(tq[-1])}",
        "trade_caption": "יצוא ויבוא לפי רבעון (מיליוני דולרים, מנוכה עונתיות)",
    })
    if flags["goods"]:
        labels.update({
            "goods_note": ("יצוא הסחורות לפי סוג, מנוכה עונתיות: הסחורות הרגילות, יהלומים, "
                           "אניות ומטוסים, ויצוא לרשות הפלסטינית."),
            "goods_aria": f"יצוא סחורות לפי סוג, {_qshort(gq[0])} עד {_qshort(gq[-1])}",
            "goods_caption": "יצוא סחורות לפי סוג (מיליוני דולרים, מנוכה עונתיות)",
        })
    labels.update({
        "services_note": ("יצוא השירותים לפי סוג, מנוכה עונתיות. השירותים העסקיים כוללים "
                          "את שירותי המחשוב והמחקר והפיתוח של ענף ההייטק."),
        "services_aria": f"יצוא שירותים לפי סוג, {_qshort(sq[0])} עד {_qshort(sq[-1])}",
        "services_caption": "יצוא שירותים לפי סוג (מיליוני דולרים, מנוכה עונתיות)",
    })
    if flags["income"]:
        labels.update({
            "income_note": ("ההכנסות הראשוניות נטו לפי סוג: מה שתושבי ישראל קיבלו מהשקעות "
                            "ומעבודה בחו\"ל, פחות מה ששולם לתושבי חו\"ל. ערך שלילי פירושו "
                            "שיותר כסף יצא. בהשקעות ישירות נכללים גם רווחים שחברות בבעלות "
                            "זרה צברו ולא חילקו."),
            "income_aria": "הכנסות ראשוניות נטו לפי סוג השקעה",
            "income_caption": "הכנסות ראשוניות נטו לפי סוג (מיליוני דולרים, מנוכה עונתיות)",
        })
    if flags["fdi"]:
        labels.update({
            "fdi_note": ("השקעות ישירות (רכישת חברות, הקמת חברות בנות ורווחים שנשארו בהן) "
                         "של תושבי חו\"ל בישראל ושל תושבי ישראל בחו\"ל, בכל רבעון, נתונים "
                         "מקוריים. ערך שלילי פירושו שהמשקיעים מימשו יותר משהשקיעו."),
            "fdi_aria": "השקעות ישירות בישראל ובחו\"ל לפי רבעון",
            "fdi_caption": "השקעות ישירות ובניירות ערך (מיליוני דולרים)",
        })
    if flags["annual"]:
        labels.update({
            "annual_note": ("היצוא והיבוא של סחורות ושירותים והעודף בחשבון השוטף בכל שנה "
                            "מלאה, נתונים מקוריים."),
            "annual_aria": f"מאזן התשלומים השנתי, {years[0]} עד {years[-1]}",
            "annual_caption": "נתונים שנתיים (מיליוני דולרים)",
        })
    if flags["iip"]:
        labels.update({
            "iip_note": ("הנכסים של המשק הישראלי בחו\"ל (השקעות, ניירות ערך, יתרות מטבע "
                         "החוץ של בנק ישראל) וההתחייבויות שלו לתושבי חו\"ל, בסוף כל רבעון. "
                         "העמודות הן ההפרש. החוב החיצוני ברוטו הוא החלק מההתחייבויות "
                         "שהוא חוב."),
            "iip_aria": "נכסים והתחייבויות של המשק מול חו\"ל לפי רבעון",
            "iip_caption": "נכסים, התחייבויות וחוב חיצוני (מיליארדי דולרים)",
        })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"מאזן התשלומים של ישראל לפי רבעון, מנתוני הלמ\"ס: החשבון השוטף, יצוא "
               f"ויבוא, הכנסות מהשקעות והשקעות ישירות. {_qb(lt)}: {_bal(cur)} "
               f"בחשבון השוטף.")
    desc = (f"מאזן התשלומים של ישראל: {_bal(cur)} בחשבון השוטף {_qb(lt)}. "
            f"יצוא, יבוא, השקעות ישירות וחוב חיצוני.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{min(years + [qs[0][0]])}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מאזן התשלומים של ישראל: נתון רבעוני עדכני | הלמ\"ס",
                "description": desc,
                "name": "מאזן התשלומים של ישראל",
                "alternate_names": ["סיכום מאזן התשלומים", "החשבון השוטף של ישראל",
                                    "עודף בחשבון השוטף", "השקעות ישירות בישראל",
                                    "החוב החיצוני של ישראל"],
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
