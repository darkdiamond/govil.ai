"""סחר החוץ לפי ארצות: CBS's monthly release on goods trade by country.

Inputs are CBS grid tables from the newest edition of the release:
  t1  imports and exports by country and region, $ million: the latest
      month and the same month a year earlier, the year to date and the
      same period a year earlier, and the two last full years
  t2  the same table in NIS million
  t3  t1 without diamonds ($ million)
  t4  t2 without diamonds (NIS million)
  t5  imports and exports by country group ($ million, excl. aircraft,
      ships and diamonds), 13 months: original, seasonally adjusted, trend,
      and the trend's monthly change
  t6  t5 in NIS (not read: the page uses dollars)
  t7  OECD member countries ($ million), with the OECD total
  t8  t7 in NIS (not read)
  releases  the edition list (number, date, headline, link)

Header rows and columns are found by their labels (govlib.cbs) and raise
when missing; country and region rows are found by pattern (a 3-digit CBS
code and an ISO code), so a missing one only shortens a ranking.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TOP_PARTNERS = 15
TOP_SIDE = 12
TOP_BALANCE = 8
TOP_MOVERS = 6
TOP_DIAMONDS = 8
TOP_ANNUAL = 10

# English region label (letters only, lower case) → (key, Hebrew name).
CONTINENTS = {"europe": "אירופה", "asia": "אסיה", "africa": "אפריקה",
              "america": "אמריקה", "oceania": "אוקיאניה"}
UNCLASSIFIED = "ארצות בלתי מסווגות"
_PERIOD = re.compile(r"^([IVX]+)(?:\s*-\s*([IVX]+))?$")
_ISO = re.compile(r"^[A-Z]{2}$")
_CODE = re.compile(r"^\d{1,3}$")
_HE = re.compile("[א-ת]")


# ── tables ───────────────────────────────────────────────────────────────


def _key(label):
    return re.sub(r"[^a-z]", "", label.lower())


def _block_cols(per, years, start, stop):
    """Columns of one Imports/Exports block: month, year to date, full years.
    The month column is the first with a roman-month label, the year-to-date
    column the next labelled one; each is followed by the year before, and
    the two full years follow the year-to-date pair."""
    lab = [j for j in range(start, stop) if _PERIOD.match(cbs.cell(per, j))]
    if len(lab) == 1 and cbs.cell(per, lab[0]) == "I":
        # A January edition: the month is the year to date, one pair of
        # columns, then the full years.
        lab = [lab[0], lab[0]]
    if len(lab) < 2:
        raise ValueError(f"period labels not found in columns {start}-{stop}")
    m, y = lab[0], lab[1]
    cols = {"m": m, "m0": m + 1, "y": y, "y0": y + 1, "f1": y + 2, "f0": y + 3}
    yr = {k: cbs.cell(years, j) for k, j in cols.items()}
    if not all(cbs.YEAR.match(v) for v in yr.values()):
        raise ValueError(f"year header row incomplete: {yr}")
    yr = {k: int(v) for k, v in yr.items()}
    if not (yr["m"] - yr["m0"] == 1 and yr["y"] - yr["y0"] == 1 and yr["f1"] - yr["f0"] == 1):
        raise ValueError(f"unexpected year columns: {yr}")
    pm = _PERIOD.match(cbs.cell(per, m))
    py = _PERIOD.match(cbs.cell(per, y))
    month = cbs.ROMAN.get(pm.group(1))
    ytd_end = cbs.ROMAN.get(py.group(2) or py.group(1))
    if month is None or ytd_end is None:
        raise ValueError("period labels are not roman months")
    return cols, yr, month, ytd_end


def _by_country(rows, name):
    """A "Trade Countries" table (t1-t4, t7): {"countries": [...],
    "aggs": {key: values}, "years", "month", "ytd_end"}. Values are
    {"imp": {m, m0, y, y0, f1, f0}, "exp": {...}} in the table's unit."""
    h = cbs.row_with(rows, "Imports", name=name)
    imp = cbs.col_after(rows[h], "Imports", 0)
    exp = cbs.col_after(rows[h], "Exports", imp + 1)
    pr = cbs.row_with(rows, "ISO", h, name=name)
    yr_row = cbs.row_with(rows, "Code", pr, name=name)
    en = cbs.col_after(rows[pr], "Countries", 0)
    iso = cbs.col_after(rows[pr], "ISO", 0)
    he = next((j for j, c in enumerate(rows[pr]) if c.replace(" ", "") == "ארצות"), None)
    if he is None:
        raise ValueError(f"{name}: Hebrew country-name column not found")
    icols, yrs, month, ytd_end = _block_cols(rows[pr], rows[yr_row], imp, exp)
    ecols, eyrs, emonth, eytd = _block_cols(rows[pr], rows[yr_row], exp, len(rows[pr]))
    if (eyrs, emonth, eytd) != (yrs, month, ytd_end):
        raise ValueError(f"{name}: imports and exports cover different periods")

    def values(r):
        return {"imp": {k: cbs.val(r, j) for k, j in icols.items()},
                "exp": {k: cbs.val(r, j) for k, j in ecols.items()}}

    countries, aggs, cont, pending = [], {}, None, ""
    for r in rows[yr_row + 1:]:
        code, iso_c, en_c = cbs.cell(r, 0), cbs.cell(r, iso), cbs.cell(r, en)
        v = values(r)
        has = v["imp"]["y"] is not None or v["exp"]["y"] is not None
        if has or _CODE.match(code):
            label, pending = (pending + " " + en_c).strip(), ""
        else:
            label = ""
        if _CODE.match(code) and _ISO.match(iso_c):
            he_c = cbs.cell(r, he) or en_c
            countries.append({"code": code, "iso": iso_c, "he": he_c, "cont": cont, "v": v})
        elif _CODE.match(code) and code == "900":
            aggs["unclassified"] = v
        elif _CODE.match(code):
            if has and cont:  # "Other Countries" of a continent
                aggs.setdefault("other:" + cont, v)
        elif en_c and not has:
            pending = (pending + " " + en_c).strip()  # a label that wraps onto the next row
        elif label and has:
            k = _key(label)
            aggs[k] = v
            if k in CONTINENTS:
                cont = k
    if "grandtotal" not in aggs:
        raise ValueError(f"{name}: Grand Total row not found")
    return {"countries": countries, "aggs": aggs, "years": yrs, "month": month,
            "ytd_end": ytd_end}


def _regions(rows, name="t5"):
    """The country-group table (t5): {section: [(year, month, {block: {group: v}})]}
    for sections orig / sa / trend / pct. Original data is required; the
    others sit lower in the sheet and are optional."""
    h = cbs.row_with(rows, "Imports", name=name)
    imp = cbs.col_after(rows[h], "Imports", 0)
    exp = cbs.col_after(rows[h], "Exports", imp + 1)
    rh = cbs.row_with(rows, "סך כולל", h, name=name)
    rs = cbs.row_with(rows, "מזה: סין", h, name=name)
    cols = {}
    for b, (s, e) in {"imp": (imp, exp), "exp": (exp, len(rows[rh]))}.items():
        c = {"total": cbs.col_after(rows[rh], "סך כולל", s),
             "europe": cbs.col_after(rows[rh], "אירופה", s),
             "asia": cbs.col_after(rows[rh], "אסיה", s),
             "america": cbs.col_after(rows[rh], "אמריקה", s),
             "other": cbs.col_after(rows[rh], "יתר ארצות", s),
             "china": cbs.col_after(rows[rs], "מזה: סין", s),
             "usa": cbs.col_after(rows[rs], "מזה: ארצות", s),
             "eu": cbs.col_after(rows[rs], "מזה: האיחוד", s)}
        if any(not s <= j < e for j in c.values()):
            raise ValueError(f"{name}: {b} columns out of their block")
        cols[b] = c
    marks = {"orig": ("Original data", False), "sa": ("Seasonally adjusted data", False),
             "trend": ("Trend data - Million", True), "pct": ("Trend data - Percentage", True)}
    starts = {"orig": cbs.row_with(rows, marks["orig"][0], rs, name=name)}
    for k in ("sa", "trend", "pct"):
        try:
            starts[k] = cbs.row_with(rows, marks[k][0], rs, name=name, contains=marks[k][1])
        except ValueError:
            pass
    order = sorted(starts.items(), key=lambda kv: kv[1])
    out = {}
    for n, (sec, s) in enumerate(order):
        stop = order[n + 1][1] if n + 1 < len(order) else len(rows)
        recs = []
        for i, y, m, end in cbs.periods(rows, s + 1, stop):
            if m is None or end:
                continue
            recs.append((y, m, {b: {g: cbs.val(rows[i], j) for g, j in c.items()}
                                for b, c in cols.items()}))
        recs.sort(key=lambda r: (r[0], r[1]))
        out[sec] = recs
    return out


# ── formatting ───────────────────────────────────────────────────────────


def _mname(y, m):
    return f"{fmt.MONTHS_HE[m - 1]} {y}"


def _mshort(y, m):
    return f"{fmt.MONTHS_SHORT_HE[m - 1]} {str(y)[2:]}"


def _bn(v):
    """$ million → billions, one decimal."""
    return fmt.num_he(v / 1000, 1)


def _mn(v):
    return fmt.int_he(v) if v is not None else "–"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _spct(c, digits=1):
    return fmt.signed_pct(c, digits) if c is not None else "–"


def _word(c, up="עלייה", down="ירידה"):
    return up if c > 0 else down


def _tone(c, band=0.01, good_up=True):
    if c is None:
        return "brand"
    if abs(c) <= band:
        return "warn"
    return "ok" if (c > 0) == good_up else "danger"


def _r1(v):
    return round(v, 1) if v is not None else None


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    t1 = _by_country(cbs.grid(frames["t1"], "t1"), "t1")
    t2 = _by_country(cbs.grid(frames["t2"], "t2"), "t2")
    t3 = _by_country(cbs.grid(frames["t3"], "t3"), "t3")
    t4 = _by_country(cbs.grid(frames["t4"], "t4"), "t4")
    t7 = _by_country(cbs.grid(frames["t7"], "t7"), "t7")
    reg = _regions(cbs.grid(frames["t5"], "t5"))

    yrs, month, ytd_end = t1["years"], t1["month"], t1["ytd_end"]
    Y, Y0, F1, F0 = yrs["y"], yrs["y0"], yrs["f1"], yrs["f0"]
    gt = t1["aggs"]["grandtotal"]
    imp, exp = gt["imp"], gt["exp"]
    if imp["m"] is None or exp["m"] is None or imp["y"] is None or exp["y"] is None:
        raise ValueError("t1: Grand Total has no latest-month values")
    ytd_label = (f"{fmt.MONTHS_HE[0]}-{fmt.MONTHS_HE[ytd_end - 1]}" if ytd_end > 1
                 else fmt.MONTHS_HE[0])
    ytd_cur = f"{ytd_label} {Y}"
    ytd_prev = f"{ytd_label} {Y0}"
    mlabel = _mname(yrs["m"], month)

    imp_y_chg = _chg(imp["y"], imp["y0"])
    exp_y_chg = _chg(exp["y"], exp["y0"])
    exp_m_chg = _chg(exp["m"], exp["m0"])
    bal_y = exp["y"] - imp["y"]
    bal_y0 = (exp["y0"] - imp["y0"]) if exp["y0"] is not None and imp["y0"] is not None else None

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["exp_m"] = {"value": round(exp["m"], 1), "display": _bn(exp["m"]),
                     "tone": _tone(exp_m_chg)}
    labels["exp_m_kpi"] = f"יצוא סחורות, {mlabel} (מיליארד $)"
    kpis["imp_m"] = {"value": round(imp["m"], 1), "display": _bn(imp["m"]), "tone": "brand"}
    labels["imp_m_kpi"] = f"יבוא סחורות, {mlabel} (מיליארד $)"
    if exp_y_chg is not None:
        kpis["exp_y"] = {"value": round(exp_y_chg, 4), "display": fmt.signed_pct(exp_y_chg),
                         "tone": _tone(exp_y_chg)}
        labels["exp_y_kpi"] = f"שינוי ביצוא, {ytd_cur} לעומת {ytd_prev}"
    if imp_y_chg is not None:
        kpis["imp_y"] = {"value": round(imp_y_chg, 4), "display": fmt.signed_pct(imp_y_chg),
                         "tone": "info"}
        labels["imp_y_kpi"] = f"שינוי ביבוא, {ytd_cur} לעומת {ytd_prev}"
    kpis["bal_y"] = {"value": round(bal_y, 1), "display": ("−" if bal_y < 0 else "") + _bn(abs(bal_y)),
                     "tone": ("danger" if bal_y0 is not None and bal_y < bal_y0 else
                              "ok" if bal_y0 is not None and bal_y > bal_y0 else "brand")}
    labels["bal_y_kpi"] = (f"המאזן המסחרי בסחורות, {ytd_cur} (מיליארד $)")
    g4 = t4["aggs"]["grandtotal"]
    if g4["imp"]["m"] is not None and g4["exp"]["m"] is not None:
        nd = g4["exp"]["m"] - g4["imp"]["m"]
        kpis["bal_nis"] = {"value": round(nd, 1),
                           "display": ("−" if nd < 0 else "") + fmt.num_he(abs(nd) / 1000, 1),
                           "tone": "info"}
        labels["bal_nis_kpi"] = f"המאזן המסחרי ללא יהלומים, {mlabel} (מיליארד ₪)"

    # ── countries ────────────────────────────────────────────────────────
    cs = t1["countries"]
    for c in cs:
        v = c["v"]
        c["imp"] = v["imp"]["y"] or 0.0
        c["exp"] = v["exp"]["y"] or 0.0
        c["imp0"] = v["imp"]["y0"]
        c["exp0"] = v["exp"]["y0"]
        c["tot"] = c["imp"] + c["exp"]
        c["tot0"] = ((c["imp0"] or 0) + (c["exp0"] or 0)
                     if c["imp0"] is not None or c["exp0"] is not None else None)
        c["bal"] = c["exp"] - c["imp"]
        c["f1"] = (v["imp"]["f1"] or 0) + (v["exp"]["f1"] or 0)
        c["f0"] = (v["imp"]["f0"] or 0) + (v["exp"]["f0"] or 0)
    total_trade = imp["y"] + exp["y"]
    if not cs:
        raise ValueError("t1: no country rows")

    charts, tables, flags = {}, {}, {}
    part = sorted(cs, key=lambda c: (-c["tot"], c["iso"]))[:TOP_PARTNERS]
    charts["partners"] = {"names": [c["he"] for c in part],
                          "imp": [_r1(c["imp"]) for c in part],
                          "exp": [_r1(c["exp"]) for c in part]}
    tables["partners"] = [[c["he"], _mn(c["imp"]), _mn(c["exp"]), _mn(c["tot"]),
                           fmt.pct(c["tot"] / total_trade)] for c in part]

    def side(key, key0):
        top = sorted(cs, key=lambda c: (-c[key], c["iso"]))[:TOP_SIDE]
        return top, {"names": [c["he"] for c in top],
                     "cur": [_r1(c[key]) for c in top],
                     "prev": [_r1(c[key0]) for c in top]}, [
            [c["he"], _mn(c[key]), _mn(c[key0]), _spct(_chg(c[key], c[key0])),
             fmt.pct(c[key] / (exp["y"] if key == "exp" else imp["y"]))] for c in top]

    top_exp, charts["exports"], tables["exports"] = side("exp", "exp0")
    top_imp, charts["imports"], tables["imports"] = side("imp", "imp0")

    # trade balance by country
    surplus = sorted([c for c in cs if c["bal"] > 0], key=lambda c: (-c["bal"], c["iso"]))
    deficit = sorted([c for c in cs if c["bal"] < 0], key=lambda c: (c["bal"], c["iso"]))
    bal_sel = surplus[:TOP_BALANCE] + list(reversed(deficit[:TOP_BALANCE]))
    charts["balance"] = {"names": [c["he"] for c in bal_sel],
                         "bal": [_r1(c["bal"]) for c in bal_sel]}
    tables["balance"] = [[c["he"], _mn(c["exp"]), _mn(c["imp"]),
                          ("−" if c["bal"] < 0 else "") + _mn(abs(c["bal"]))]
                         for c in bal_sel]
    flags["balance"] = bool(surplus) and bool(deficit)

    # biggest movers in total trade (year to date vs the same period last year)
    movers = [c for c in cs if c["tot0"] is not None and c["tot0"] > 0]
    for c in movers:
        c["d"] = c["tot"] - c["tot0"]
    ups = sorted([c for c in movers if c["d"] > 0], key=lambda c: (-c["d"], c["iso"]))[:TOP_MOVERS]
    downs = sorted([c for c in movers if c["d"] < 0], key=lambda c: (c["d"], c["iso"]))[:TOP_MOVERS]
    mv = ups + list(reversed(downs))
    charts["movers"] = {"names": [c["he"] for c in mv], "d": [_r1(c["d"]) for c in mv]}
    tables["movers"] = [[c["he"], _mn(c["tot0"]), _mn(c["tot"]),
                         ("−" if c["d"] < 0 else "+") + _mn(abs(c["d"])),
                         _spct(_chg(c["tot"], c["tot0"]))] for c in mv]
    flags["movers"] = len(mv) >= 4

    # full years: the top partners of the last full year, against the year before
    ann = sorted([c for c in cs if c["f1"] > 0], key=lambda c: (-c["f1"], c["iso"]))[:TOP_ANNUAL]
    charts["annual"] = {"names": [c["he"] for c in ann], "f1": [_r1(c["f1"]) for c in ann],
                        "f0": [_r1(c["f0"]) for c in ann], "y1": str(F1), "y0": str(F0)}
    tables["annual"] = [[c["he"], _mn(c["f0"]), _mn(c["f1"]), _spct(_chg(c["f1"], c["f0"]))]
                        for c in ann]
    flags["annual"] = len(ann) >= 3

    # ── continents ───────────────────────────────────────────────────────
    aggs = t1["aggs"]
    conts = [k for k in CONTINENTS if k in aggs]
    cont_rows = [(CONTINENTS[k], aggs[k]) for k in conts]
    if "unclassified" in aggs:
        cont_rows.append((UNCLASSIFIED, aggs["unclassified"]))
    cont_rows = [(n, v) for n, v in cont_rows if v["imp"]["y"] is not None]
    cont_rows.sort(key=lambda r: (-(r[1]["imp"]["y"] + (r[1]["exp"]["y"] or 0)), r[0]))
    charts["continents"] = {"names": [n for n, _ in cont_rows],
                            "imp": [_r1(v["imp"]["y"]) for _, v in cont_rows],
                            "exp": [_r1(v["exp"]["y"]) for _, v in cont_rows]}
    tables["continents"] = [[n, _mn(v["imp"]["y"]), fmt.pct(v["imp"]["y"] / imp["y"]),
                             _mn(v["exp"]["y"]), fmt.pct((v["exp"]["y"] or 0) / exp["y"]),
                             _spct(_chg(v["exp"]["y"], v["exp"]["y0"]))]
                            for n, v in cont_rows]
    flags["continents"] = len(cont_rows) >= 2

    # ── diamonds: t1 (all goods) minus t3 (without diamonds) ─────────────
    nod = {c["iso"]: c for c in t3["countries"]}
    dia = []
    for c in cs:
        o = nod.get(c["iso"])
        if not o or o["v"]["exp"]["y"] is None:
            continue
        de = c["exp"] - o["v"]["exp"]["y"]
        di = c["imp"] - (o["v"]["imp"]["y"] or 0)
        if de > 0.5 or di > 0.5:
            dia.append({"he": c["he"], "iso": c["iso"], "exp": de, "imp": di,
                        "share": de / c["exp"] if c["exp"] else None})
    dia.sort(key=lambda d: (-(d["exp"] + d["imp"]), d["iso"]))
    dia = dia[:TOP_DIAMONDS]
    g3 = t3["aggs"]["grandtotal"]
    dia_exp = exp["y"] - (g3["exp"]["y"] or 0)
    charts["diamonds"] = {"names": [d["he"] for d in dia], "exp": [_r1(d["exp"]) for d in dia],
                          "imp": [_r1(d["imp"]) for d in dia]}
    tables["diamonds"] = [[d["he"], _mn(d["exp"]), _mn(d["imp"]),
                           fmt.pct(d["share"]) if d["share"] is not None else "–"] for d in dia]
    flags["diamonds"] = len(dia) >= 3 and dia_exp > 0

    # ── monthly series by region (t5) ────────────────────────────────────
    sec = "sa" if reg.get("sa") else "orig"
    ser = reg[sec]
    flags["monthly"] = len(ser) >= 3
    groups = [("europe", "אירופה"), ("asia", "אסיה"), ("america", "אמריקה"),
              ("other", "יתר הארצות"), ("eu", "מזה: האיחוד האירופי"),
              ("usa", "מזה: ארצות הברית"), ("china", "מזה: סין")]
    charts["group_names"] = [n for _, n in groups]
    for b in ("exp", "imp"):
        charts["monthly_" + b] = {"x": [_mshort(y, m) for y, m, _ in ser],
                                  "series": [[_r1(v[b][g]) for _, _, v in ser] for g, _ in groups]}
        tables["monthly_" + b] = [[_mname(y, m)] + [_mn(v[b][g]) for g, _ in groups]
                                  for y, m, v in reversed(ser)]

    # ── OECD (t7) and NIS (t2) ──────────────────────────────────────────
    oecd = t7["aggs"].get("totaloecd")
    oecd_exp = (oecd["exp"]["y"] / exp["y"]) if oecd and oecd["exp"]["y"] is not None else None
    oecd_imp = (oecd["imp"]["y"] / imp["y"]) if oecd and oecd["imp"]["y"] is not None else None
    g2 = t2["aggs"]["grandtotal"]
    imp_nis = _chg(g2["imp"]["y"], g2["imp"]["y0"])
    exp_nis = _chg(g2["exp"]["y"], g2["exp"]["y0"])
    tables["currency"] = [
        ["יבוא", _mn(imp["y0"]), _mn(imp["y"]), _spct(imp_y_chg),
         _mn(g2["imp"]["y0"]), _mn(g2["imp"]["y"]), _spct(imp_nis)],
        ["יצוא", _mn(exp["y0"]), _mn(exp["y"]), _spct(exp_y_chg),
         _mn(g2["exp"]["y0"]), _mn(g2["exp"]["y"]), _spct(exp_nis)]]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if exp_y_chg is not None and imp_y_chg is not None:
        if bal_y < 0 and bal_y0 is not None and bal_y0 < 0:
            bal_txt = (f"הגירעון המסחרי בסחורות {'התרחב' if bal_y < bal_y0 else 'הצטמצם'} "
                       f"ל-{_bn(abs(bal_y))} מיליארד $, לעומת {_bn(abs(bal_y0))} מיליארד $.")
        elif bal_y < 0:
            bal_txt = f"הגירעון המסחרי בסחורות: {_bn(abs(bal_y))} מיליארד $."
        else:
            bal_txt = f"העודף המסחרי בסחורות: {_bn(bal_y)} מיליארד $."
        add("ytd", f"ב{ytd_cur} ייצאה ישראל סחורות ב-{_bn(exp['y'])} מיליארד $ "
                   f"({_word(exp_y_chg)} של {fmt.pct(abs(exp_y_chg))} לעומת {ytd_prev}) "
                   f"וייבאה ב-{_bn(imp['y'])} מיליארד $ ({_word(imp_y_chg)} של "
                   f"{fmt.pct(abs(imp_y_chg))}). {bal_txt}")
    if part:
        lead = part[0]
        top3 = part[:3]
        share3 = sum(c["tot"] for c in top3) / total_trade
        add("leader", f"{lead['he']} היא שותפת הסחר הגדולה של ישראל ב{ytd_cur}: "
                      f"{_bn(lead['tot'])} מיליארד $ ביבוא וביצוא יחד, "
                      f"{fmt.pct(lead['tot'] / total_trade)} מכלל הסחר. שלוש הגדולות "
                      f"({fmt.join_he([c['he'] for c in top3])}) מרכזות "
                      f"{fmt.pct(share3)} ממנו." if len(top3) == 3 else None)
    if top_exp and top_imp and top_exp[0]["iso"] != top_imp[0]["iso"]:
        e0, i0 = top_exp[0], top_imp[0]
        add("sides", f"היעד הגדול של היצוא הוא {e0['he']} ({fmt.pct(e0['exp'] / exp['y'])} "
                     f"מהיצוא), אבל מקור היבוא הגדול הוא {i0['he']} "
                     f"({fmt.pct(i0['imp'] / imp['y'])} מהיבוא).")
    if surplus and deficit:
        s0, d0 = surplus[0], deficit[0]
        add("balance", f"העודף המסחרי הגדול ביותר הוא מול {s0['he']} "
                       f"({_bn(s0['bal'])} מיליארד $ יותר יצוא מיבוא), והגירעון הגדול "
                       f"ביותר מול {d0['he']} ({_bn(abs(d0['bal']))} מיליארד $ יותר יבוא "
                       f"מיצוא).")
    if ups and downs:
        u, d = ups[0], downs[0]
        add("movers", f"לעומת {ytd_prev}, הסחר עם {u['he']} גדל הכי הרבה: ב-{_mn(u['d'])} "
                      f"מיליון $ ({fmt.pct(abs(_chg(u['tot'], u['tot0'])))}). הירידה הגדולה היא "
                      f"בסחר עם {d['he']}: ב-{_mn(abs(d['d']))} מיליון $ "
                      f"({fmt.pct(abs(_chg(d['tot'], d['tot0'])))}).")
    if cont_rows:
        ce = max(cont_rows, key=lambda r: ((r[1]["exp"]["y"] or 0), r[0]))
        ci = max(cont_rows, key=lambda r: (r[1]["imp"]["y"], r[0]))
        add("continents", f"{ce[0]} קולטת {fmt.pct((ce[1]['exp']['y'] or 0) / exp['y'])} "
                          f"מהיצוא, ו{ci[0]} מספקת {fmt.pct(ci[1]['imp']['y'] / imp['y'])} "
                          f"מהיבוא." if ce[0] != ci[0] else
            f"{ce[0]} היא היבשת הגדולה בסחר: {fmt.pct((ce[1]['exp']['y'] or 0) / exp['y'])} "
            f"מהיצוא ו-{fmt.pct(ce[1]['imp']['y'] / imp['y'])} מהיבוא.")
    if exp_nis is not None and imp_y_chg is not None and abs(imp_y_chg - imp_nis) >= 0.03:
        dollars = (f"לעומת {_word(imp_y_chg)} של {fmt.pct(abs(imp_y_chg))} ביבוא ו{_word(exp_y_chg)} "
                   f"של {fmt.pct(abs(exp_y_chg))} ביצוא בדולרים. הפער נובע משינוי שער החליפין.")
        add("currency", f"{'בשקלים התמונה שונה: ' if imp_nis < imp_y_chg else 'בשקלים '}"
                        f"היבוא {_word(imp_nis, 'עלה', 'ירד')} ב-{fmt.pct(abs(imp_nis))} "
                        f"והיצוא {_word(exp_nis, 'עלה', 'ירד')} ב-{fmt.pct(abs(exp_nis))}, {dollars}")
    if flags["diamonds"] and exp["y"]:
        d0 = max(dia, key=lambda d: (d["exp"], d["iso"]))
        add("diamonds", f"יהלומים הם {fmt.pct(dia_exp / exp['y'])} מהיצוא ב{ytd_cur} "
                        f"({_bn(dia_exp)} מיליארד $). היעד הגדול שלהם הוא {d0['he']}"
                        + (f", שם הם {fmt.pct(d0['share'])} מהיצוא לשם" if d0["share"] else "")
                        + ".")
    if oecd_exp is not None and oecd_imp is not None:
        add("oecd", f"מדינות ה-OECD קולטות {fmt.pct(oecd_exp)} מהיצוא ומספקות "
                    f"{fmt.pct(oecd_imp)} מהיבוא.")
    pct = reg.get("pct") or []
    if pct:
        y, m, v = pct[-1]
        moves = [(n, v["exp"][g]) for g, n in groups[:3] if v["exp"][g] is not None]
        up = [(n, x) for n, x in moves if x >= 0.5]
        dn = [(n, x) for n, x in moves if x <= -0.5]
        if up or dn:
            parts = [f"ל{n} {'עלה' if x > 0 else 'ירד'} ב-{fmt.num_he(abs(x), 1)}%"
                     for n, x in sorted(up + dn, key=lambda t: (-t[1], t[0]))]
            add("trend", f"לפי נתוני המגמה של {_mname(y, m)} (ללא יהלומים, אוניות ומטוסים), "
                         f"היצוא {fmt.join_he(parts)} לעומת החודש הקודם.")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"עם אילו ארצות ישראל סוחרת: לאן היא מייצאת סחורות, מאין היא מייבאת, "
                 f"ואיך הסחר עם כל ארץ ויבשת משתנה. הנתונים מתוך ההודעה החודשית של הלשכה "
                 f"המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. הנתון האחרון הוא "
                 f"ל{mlabel}: יצוא של {_bn(exp['m'])} מיליארד $ ויבוא של {_bn(imp['m'])} "
                 f"מיליארד $."),
        "partners_note": (f"{len(part)} הארצות עם היקף הסחר הגדול ביותר ב{ytd_cur}, יבוא ויצוא "
                          f"יחד, במיליוני דולרים. כולל יהלומים."),
        "partners_aria": f"שותפות הסחר הגדולות של ישראל, {ytd_cur}",
        "partners_caption": f"שותפות הסחר הגדולות, {ytd_cur} (מיליוני $)",
        "exports_note": (f"{len(top_exp)} יעדי היצוא הגדולים ב{ytd_cur}, לעומת אותה תקופה "
                         f"ב-{Y0}, במיליוני דולרים."),
        "exports_aria": f"יעדי היצוא הגדולים, {ytd_cur} מול {ytd_prev}",
        "exports_caption": "יעדי היצוא הגדולים (מיליוני $)",
        "imports_note": (f"{len(top_imp)} מקורות היבוא הגדולים ב{ytd_cur}, לעומת אותה תקופה "
                         f"ב-{Y0}, במיליוני דולרים."),
        "imports_aria": f"מקורות היבוא הגדולים, {ytd_cur} מול {ytd_prev}",
        "imports_caption": "מקורות היבוא הגדולים (מיליוני $)",
        "continents_note": (f"היבוא והיצוא לפי יבשת ב{ytd_cur}, במיליוני דולרים. "
                            f"\"ארצות בלתי מסווגות\" הן סחר שהלמ\"ס לא שייכה לארץ מסוימת."),
        "continents_aria": f"יבוא ויצוא לפי יבשת, {ytd_cur}",
        "continents_caption": f"יבוא ויצוא לפי יבשת, {ytd_cur} (מיליוני $)",
        "balance_note": (f"היצוא פחות היבוא מול כל ארץ ב{ytd_cur}: הארצות עם העודף הגדול "
                         f"(ישראל מוכרת להן יותר משהיא קונה) והגירעון הגדול, במיליוני דולרים."),
        "balance_aria": f"המאזן המסחרי מול כל ארץ, {ytd_cur}",
        "balance_caption": f"המאזן המסחרי לפי ארץ, {ytd_cur} (מיליוני $)",
        "movers_note": (f"השינוי בהיקף הסחר (יבוא ויצוא יחד) ב{ytd_cur} לעומת {ytd_prev}: "
                        f"הארצות שהסחר איתן גדל וירד הכי הרבה, במיליוני דולרים."),
        "movers_aria": f"השינוי בסחר לפי ארץ, {ytd_cur} לעומת {ytd_prev}",
        "movers_caption": "השינוי בסחר לפי ארץ (מיליוני $)",
        "annual_note": (f"עשר שותפות הסחר הגדולות בשנת {F1} כולה, לעומת שנת {F0}: יבוא ויצוא "
                        f"יחד, במיליוני דולרים."),
        "annual_aria": f"שותפות הסחר הגדולות, {F0} מול {F1}",
        "annual_caption": f"היקף הסחר, {F0} ו-{F1} (מיליוני $)",
        "diamonds_note": (f"הסחר ביהלומים מול כל ארץ ב{ytd_cur}: ההפרש בין הסחר הכולל לסחר "
                          f"ללא יהלומים, במיליוני דולרים. בטבלה גם החלק של היהלומים מהיצוא "
                          f"לכל ארץ."),
        "diamonds_aria": f"סחר ביהלומים לפי ארץ, {ytd_cur}",
        "diamonds_caption": f"סחר ביהלומים לפי ארץ, {ytd_cur} (מיליוני $)",
        "currency_caption": f"יבוא ויצוא בדולרים ובשקלים, {ytd_prev} ו-{ytd_cur}",
        "currency_note": (f"סך היבוא והיצוא ב{ytd_cur} ובאותה תקופה ב-{Y0}, במיליוני דולרים "
                          f"ובמיליוני שקלים."),
        "col_ytd": ytd_cur, "col_ytd0": ytd_prev,
        "col_y0": str(Y0), "col_y": str(Y),
        "col_f0": str(F0), "col_f1": str(F1),
        "y_cur": str(Y), "y_prev": str(Y0),
    })
    if flags["monthly"]:
        first, last_ = ser[0], ser[-1]
        kind = "מנוכה עונתיות" if sec == "sa" else "מקורי"
        labels.update({
            "monthly_note": (f"היצוא והיבוא בכל חודש מאז {_mname(first[0], first[1])}, לפי אזור, "
                             f"במיליוני דולרים (נתון {kind}, ללא יהלומים, אוניות ומטוסים). "
                             f"\"מזה\" הם חלק מהיבשת שלהם. אפשר להסתיר קו בלחיצה על המקרא."),
            "monthly_exp_aria": (f"יצוא חודשי לפי אזור, {_mname(first[0], first[1])} עד "
                                 f"{_mname(last_[0], last_[1])}"),
            "monthly_imp_aria": (f"יבוא חודשי לפי אזור, {_mname(first[0], first[1])} עד "
                                 f"{_mname(last_[0], last_[1])}"),
            "monthly_exp_caption": "יצוא חודשי לפי אזור (מיליוני $)",
            "monthly_imp_caption": "יבוא חודשי לפי אזור (מיליוני $)",
        })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    lead_names = fmt.join_he([c["he"] for c in part[:3]])
    summary = (f"היבוא והיצוא של ישראל לפי ארץ ויבשת, מנתוני הלמ\"ס. ב{ytd_cur}: יצוא של "
               f"{_bn(exp['y'])} מיליארד $ ויבוא של {_bn(imp['y'])} מיליארד $. שותפות הסחר "
               f"הגדולות: {lead_names}.")
    desc = (f"עם מי ישראל סוחרת: יבוא ויצוא לפי ארץ. ב{ytd_cur} יצוא {_bn(exp['y'])} "
            f"ויבוא {_bn(imp['y'])} מיליארד $. השותפות הגדולות: {lead_names}.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            "temporal_coverage": f"{F0}/{Y}",
            "spatial_coverage": "ישראל וארצות הסחר שלה",
            "seo": {
                "title": "יבוא ויצוא לפי ארצות: שותפות הסחר של ישראל | הלמ\"ס",
                "description": desc,
                "name": "סחר החוץ של ישראל לפי ארצות",
                "alternate_names": ["סחר חוץ לפי ארצות - סחורות", "יצוא לפי מדינות",
                                    "יבוא לפי מדינות", "שותפות הסחר של ישראל",
                                    "מאזן מסחרי לפי ארץ"],
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
