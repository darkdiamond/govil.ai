"""יצוא שירותים: CBS's monthly services-exports release (chapter 09).

Inputs are CBS grid tables from the newest edition of the release:
  t1  exports of services by kind, monthly since 2016: total, total excl.
      start-ups, business services, of which hi-tech, travel, passenger
      fares, other transport, insurance and government, start-ups and
      exceptional intangible deals. Original data, seasonally adjusted (SA)
      and, for the totals, trend. $ million.
  t2  the same months, original data only, one column per month: the kinds
      above plus the other-transport breakdown (freight, charter, port
      services) and business services by the exporter's industry.
  releases  the edition list (number, date, headline, link)

The release's t3-t8 are chart data that repeat t1's columns, so they are
not read. Header rows and columns are found by their labels (govlib.cbs, or
the English block names of t1) and raise when missing, so a redesigned table
fails the refresh as recipe_failed and keeps the last page. Months are found
by pattern: a missing one only shortens a series.
"""
import re

import pandas as pd
from govlib import cbs, fmt

# t1's English block labels → keys. Checked in this order (the first
# matching rule wins), so the specific labels come before "total".
T1_BLOCKS = (
    ("startups", ("start-up companies and exceptional",)),
    ("hitech", ("hi-tech",)),
    ("business", ("business services",)),
    ("travel", ("travel services",)),
    ("fares", ("passenger fares",)),
    ("other_tr", ("other transportation",)),
    ("ins", ("insurance",)),
    ("excl", ("total", "excl")),
    ("total", ("total",)),
)
# The kinds a year is split into (t1, original data); "biz_other" is
# business services minus hi-tech.
KINDS = (
    ("hitech", "שירותי היי-טק"),
    ("biz_other", "שירותים עסקיים אחרים"),
    ("travel", "תיירות"),
    ("fares", "תחבורה: דמי נסיעה"),
    ("other_tr", "תחבורה: מטענים ושירותים אחרים"),
    ("ins", "ביטוח וממשלה"),
    ("startups", "חברות הזנק ועסקאות חריגות"),
)
# Short names for t2's industry rows, by industry code; others keep the
# CBS name, cut at its first comma.
INDUSTRY_SHORT = {
    "05-33": "תעשייה, כרייה וחציבה",
    "46": "מסחר סיטוני",
    "61": "שירותי תקשורת",
    "62": "תכנות וייעוץ מחשבים",
    "64,66": "שירותים פיננסיים",
    "72": "מחקר מדעי ופיתוח",
    "70,71,73,74,82": "שירותים מקצועיים וניהול",
    "6201": "תכנות מחשבים",
    "6202,6209": "ייעוץ מחשוב וניהול מתקנים",
    "6203": "מרכזי מחקר ופיתוח תוכנה",
}
INDUSTRY_SHORT_NAME = {
    "ענפים אחרים לנמ\"א": "ענפים אחרים",
    "שירותים עסקיים אחרים לא מסווגים": "שירותים עסקיים לא מסווגים",
}
_SUBCODE = re.compile(r"^\d{4}(,\d{4})*$")
RECENT = 12
TRAVEL_GAP = 0.1
FREIGHT_DROP = 0.3


# ── tables ───────────────────────────────────────────────────────────────


def _t1_cols(rows):
    """{key: {"orig": j, "sa": j|None, "trend": j|None}} and the sub-header
    row index. Raises when a block or its original-data column is missing."""
    rb = cbs.row_with(rows, "Exports of travel services", name="t1", contains=True)
    starts = {}
    for j, c in enumerate(rows[rb]):
        low = c.lower()
        if not low:
            continue
        for key, needles in T1_BLOCKS:
            if all(n in low for n in needles):
                starts.setdefault(key, j)
                break
    missing = [k for k, _ in T1_BLOCKS if k not in starts]
    if missing:
        raise ValueError(f"t1: block labels not found: {missing}")
    sub = cbs.row_with(rows, "Seasonally Adjusted", rb, name="t1")
    order = sorted(starts.values())
    out = {}
    for key, b in starts.items():
        nxt = next((s for s in order if s > b), len(rows[sub]))
        span = range(b, nxt)

        def find(label, span=span):
            return next((j for j in span if cbs.cell(rows[sub], j) == label), None)

        orig = find("Original")
        if orig is None:
            raise ValueError(f"t1: no Original column in block {key}")
        out[key] = {"orig": orig, "sa": find("Seasonally Adjusted"), "trend": find("Trend")}
    for key in ("excl", "hitech", "travel", "fares"):
        if out[key]["sa"] is None:
            raise ValueError(f"t1: no Seasonally Adjusted column in block {key}")
    if out["excl"]["trend"] is None:
        raise ValueError("t1: no Trend column for the total excl. start-ups")
    return out, sub


def _t1(rows):
    """[{t: (year, month), <key>: orig, <key>_sa, <key>_trend}] by month."""
    cols, sub = _t1_cols(rows)
    out = []
    for i, y, m, end in cbs.periods(rows, sub + 1, len(rows)):
        if m is None or end:
            continue
        r = rows[i]
        rec = {"t": (y, m)}
        for key, c in cols.items():
            rec[key] = cbs.val(r, c["orig"])
            if c["sa"] is not None:
                rec[key + "_sa"] = cbs.val(r, c["sa"])
            if c["trend"] is not None:
                rec[key + "_trend"] = cbs.val(r, c["trend"])
        if rec["excl"] is None:
            continue
        out.append(rec)
    out.sort(key=lambda r: r["t"])
    # Keep one row per month (a duplicated month would double a year's sum).
    dedup = {}
    for r in out:
        dedup[r["t"]] = r
    return [dedup[t] for t in sorted(dedup)]


def _t2_months(rows):
    """(month row index, {column: (year, month)}). The month row is the row
    with the most roman months; a year label sits somewhere over each run
    of months that starts at I."""
    counts = [sum(c in cbs.ROMAN for c in r) for r in rows]
    mrow = max(range(len(rows)), key=lambda i: (counts[i], -i)) if rows else 0
    if not rows or counts[mrow] < 1:
        raise ValueError("t2: month header row not found")
    yrow = next((i for i in range(mrow - 1, -1, -1)
                 if sum(bool(cbs.YEAR.match(c)) for c in rows[i]) >= 1), None)
    if yrow is None:
        raise ValueError("t2: year header row not found")
    mcols = [j for j, c in enumerate(rows[mrow]) if c in cbs.ROMAN]
    runs, cur, prev = [], [], 0
    for j in mcols:
        m = cbs.ROMAN[rows[mrow][j]]
        if cur and m <= prev:
            runs.append(cur)
            cur = []
        cur.append(j)
        prev = m
    if cur:
        runs.append(cur)
    out, last_year = {}, None
    for k, run in enumerate(runs):
        hi = runs[k + 1][0] if k + 1 < len(runs) else len(rows[yrow])
        years = [int(cbs.cell(rows[yrow], j)) for j in range(run[0], hi)
                 if cbs.YEAR.match(cbs.cell(rows[yrow], j))]
        year = years[0] if years else (last_year + 1 if last_year else None)
        if year is None:
            raise ValueError("t2: a run of months has no year label")
        for j in run:
            out[j] = (year, cbs.ROMAN[rows[mrow][j]])
        last_year = year
    return mrow, out


def _series(row, mcols):
    return {t: cbs.val(row, j) for j, t in mcols.items() if cbs.val(row, j) is not None}


def _t2(rows):
    """Other-transport breakdown and business services by industry, each
    as [{name, short, code, parent, sub, s: {(y, m): value}}]."""
    mrow, mcols = _t2_months(rows)
    tot = cbs.row_with(rows, "יצוא שירותים - סך הכל", name="t2", contains=True)
    name_col = cbs.col_after(rows[tot], "יצוא שירותים - סך הכל", 0, contains=True)

    def name(r):
        return cbs.cell(r, name_col)

    ot = cbs.row_with(rows, "שירותי תחבורה אחרים - סך הכל", tot, name="t2", contains=True)
    freight = []
    for r in rows[ot + 1:]:
        n = name(r)
        if "ביטוח" in n or "עסקיים" in n:
            break
        s = _series(r, mcols)
        if n and s:
            freight.append({"name": n, "short": n, "s": s})

    bt = cbs.row_with(rows, "שירותים עסקיים", ot, name="t2", contains=True)
    business = _series(rows[bt], mcols)
    hi = cbs.row_with(rows, "שם ענף", mrow, name="t2")
    code_col = name_col - 1 if name_col > 0 else None
    industries, parent = [], None
    for r in rows[hi + 1:]:
        n = name(r)
        s = _series(r, mcols)
        if not s:
            continue
        code = re.sub(r"\s+", "", cbs.cell(r, code_col)) if code_col is not None else ""
        is_sub = n.startswith("מזה") or bool(_SUBCODE.match(code))
        if is_sub and n.startswith("מזה"):
            continue  # start-ups within R&D: shown with t1's start-up series
        short = (INDUSTRY_SHORT.get(code) or INDUSTRY_SHORT_NAME.get(n)
                 or n.split(",")[0].split(";")[0].strip())
        rec = {"name": n, "short": short, "code": code, "sub": is_sub,
               "parent": parent["short"] if is_sub and parent else None, "s": s}
        if not is_sub:
            parent = rec
        industries.append(rec)
    return freight, industries, business


# ── formatting ───────────────────────────────────────────────────────────


def _m(v):
    """$ million, no decimals: 8,537."""
    return fmt.int_he(v)


def _b(v):
    """$ million as $ billion, one decimal: 8.5."""
    return fmt.num_he(v / 1000, 1)


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _range(end, year):
    if end == 1:
        return f"ינואר {year}"
    return f"ינואר עד {fmt.MONTHS_HE[end - 1]} {year}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _word(c, up="עלייה", down="ירידה"):
    return up if c > 0 else down


def _tone(c, band=0.02):
    if c is None:
        return "brand"
    return "ok" if c > band else "danger" if c < -band else "warn"


def _sum(recs, key):
    vals = [r.get(key) for r in recs]
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def _sumd(s, ts):
    vals = [s[t] for t in ts if t in s]
    return sum(vals) if len(vals) == len(ts) and ts else None


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"].copy()
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    months = _t1(cbs.grid(frames["t1"], "t1"))
    if len(months) < 2:
        raise ValueError("t1: fewer than two monthly rows")
    freight, industries, business = _t2(cbs.grid(frames["t2"], "t2"))

    for r in months:
        r["biz_other"] = (r["business"] - r["hitech"]
                          if r["business"] is not None and r["hitech"] is not None else None)
    by_t = {r["t"]: r for r in months}
    last, prev = months[-1], months[-2]
    lt = last["t"]
    cur_year, end_m = lt

    # Years: full calendar years (12 months), and the current year to date.
    years_all = sorted({t[0] for t in by_t})
    full_years = [y for y in years_all if all((y, m) in by_t for m in range(1, 13))]
    ytd_ts = [(cur_year, m) for m in range(1, end_m + 1)]
    ytd_prev_ts = [(cur_year - 1, m) for m in range(1, end_m + 1)]
    has_ytd = all(t in by_t for t in ytd_ts)
    has_ytd_prev = all(t in by_t for t in ytd_prev_ts)
    partial = end_m < 12 and has_ytd

    def total_of(ts, key):
        recs = [by_t[t] for t in ts if t in by_t]
        return _sum(recs, key) if len(recs) == len(ts) else None

    l12 = [r["t"] for r in months[-RECENT:]]
    p12 = [r["t"] for r in months[-2 * RECENT:-RECENT]] if len(months) >= 2 * RECENT else []

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    sa_chg = _chg(last["excl_sa"], prev["excl_sa"])
    kpis["sa"] = {"value": round(last["excl_sa"], 1), "display": _m(last["excl_sa"]),
                  "tone": _tone(sa_chg)}
    labels["sa_kpi"] = f"יצוא שירותים ב{_mname(lt)}, מנוכה עונתיות (מיליוני דולרים)"
    if sa_chg is not None:
        kpis["sa_chg"] = {"value": round(sa_chg, 4), "display": fmt.signed_pct(sa_chg),
                          "tone": _tone(sa_chg)}
        labels["sa_chg_kpi"] = f"שינוי לעומת {_mname(prev['t'])}, מנוכה עונתיות"
    ytd_now = total_of(ytd_ts, "total") if has_ytd else None
    ytd_prev = total_of(ytd_prev_ts, "total") if has_ytd_prev else None
    ytd_chg = _chg(ytd_now, ytd_prev)
    if ytd_now is not None:
        kpis["ytd"] = {"value": round(ytd_now, 1), "display": _b(ytd_now), "tone": _tone(ytd_chg)}
        labels["ytd_kpi"] = (f"יצוא שירותים, {_range(end_m, cur_year)} "
                             f"(מיליארדי דולרים, כולל חברות הזנק)")
    if ytd_chg is not None:
        kpis["ytd_chg"] = {"value": round(ytd_chg, 4), "display": fmt.signed_pct(ytd_chg),
                           "tone": _tone(ytd_chg)}
        labels["ytd_chg_kpi"] = f"שינוי לעומת התקופה המקבילה ב-{cur_year - 1}"
    hit12, ex12 = total_of(l12, "hitech"), total_of(l12, "excl")
    hshare = hit12 / ex12 if hit12 is not None and ex12 else None
    if hshare is not None:
        kpis["hitech"] = {"value": round(hshare, 4), "display": fmt.pct(hshare, 0), "tone": "info"}
        labels["hitech_kpi"] = (f"חלק שירותי ההיי-טק ביצוא, {_mshort(l12[0])} עד "
                                f"{_mshort(l12[-1])} (לא כולל חברות הזנק)")

    charts, tables = {}, {}

    # ── monthly series (excl. start-ups) ─────────────────────────────────
    charts["monthly"] = {
        "x": [f"{t[0]}-{t[1]:02d}" for t in (r["t"] for r in months)],
        "orig": [round(r["excl"], 1) for r in months],
        "sa": [round(r["excl_sa"], 1) if r.get("excl_sa") is not None else None for r in months],
        "trend": [round(r["excl_trend"], 1) if r.get("excl_trend") is not None else None
                  for r in months],
    }
    tables["monthly"] = [[str(y)] + [_m(by_t[(y, m)]["excl_sa"])
                                     if (y, m) in by_t and by_t[(y, m)].get("excl_sa") is not None
                                     else "" for m in range(1, 13)]
                         for y in reversed(years_all)]

    # ── years by kind ────────────────────────────────────────────────────
    year_cols = [(str(y), [(y, m) for m in range(1, 13)]) for y in full_years]
    if partial and cur_year not in full_years:
        span = (fmt.MONTHS_SHORT_HE[0] if end_m == 1
                else f"{fmt.MONTHS_SHORT_HE[0]}-{fmt.MONTHS_SHORT_HE[end_m - 1]}")
        year_cols.append((f"{cur_year} ({span})", ytd_ts))
    year_kinds = {k: [total_of(ts, k) for _, ts in year_cols] for k, _ in KINDS}
    year_total = [total_of(ts, "total") for _, ts in year_cols]
    charts["years"] = {
        "x": [lbl for lbl, _ in year_cols],
        "series": [{"name": nm, "data": [round(v / 1000, 2) if v is not None else None
                                         for v in year_kinds[k]]} for k, nm in KINDS],
    }
    tables["years"] = [[lbl] + [_b(year_kinds[k][i]) if year_kinds[k][i] is not None else ""
                                for k, _ in KINDS]
                       + [_b(year_total[i]) if year_total[i] is not None else ""]
                       for i, (lbl, _) in enumerate(year_cols)]
    labels["years_cols"] = ["שנה"] + [nm for _, nm in KINDS] + ["סך הכול"]

    # ── mix: shares of the total excl. start-ups ─────────────────────────
    mix_kinds = [(k, nm) for k, nm in KINDS if k != "startups"]
    mix_rows = []
    for i, (lbl, ts) in enumerate(year_cols):
        ex = total_of(ts, "excl")
        if not ex:
            continue
        mix_rows.append((lbl, [(year_kinds[k][i] or 0) / ex for k, _ in mix_kinds]))
    charts["mix"] = {"x": [r[0] for r in mix_rows],
                     "series": [{"name": nm, "data": [round(r[1][j] * 100, 1) for r in mix_rows]}
                                for j, (_, nm) in enumerate(mix_kinds)]}
    tables["mix"] = [[r[0]] + [fmt.pct(v) for v in r[1]] for r in mix_rows]
    labels["mix_cols"] = ["שנה"] + [nm for _, nm in mix_kinds]

    # ── year to date by kind ─────────────────────────────────────────────
    ytd_rows = []
    if has_ytd and has_ytd_prev:
        for k, nm in KINDS:
            a, b = total_of(ytd_prev_ts, k), total_of(ytd_ts, k)
            if a is None or b is None:
                continue
            ytd_rows.append((nm, a, b, _chg(b, a)))
    if ytd_rows:
        charts["ytd"] = {"names": [r[0] for r in ytd_rows],
                         "prev": [round(r[1], 1) for r in ytd_rows],
                         "now": [round(r[2], 1) for r in ytd_rows],
                         "chg": [round(r[3] * 100, 1) if r[3] is not None else None
                                 for r in ytd_rows],
                         "years": [str(cur_year - 1), str(cur_year)]}
        tables["ytd"] = [[r[0], _m(r[1]), _m(r[2]),
                          fmt.signed_pct(r[3]) if r[3] is not None else ""] for r in ytd_rows]

    # ── seasonality: original over SA, by calendar month ─────────────────
    season = []
    for m in range(1, 13):
        ratios = [by_t[(y, m)]["excl"] / by_t[(y, m)]["excl_sa"] for y in full_years
                  if by_t[(y, m)].get("excl_sa")]
        if ratios:
            season.append((m, sum(ratios) / len(ratios) - 1, len(ratios)))
    if len(season) == 12:
        charts["season"] = {"x": [fmt.MONTHS_SHORT_HE[m - 1] for m, _, _ in season],
                            "y": [round(v * 100, 1) for _, v, _ in season]}
        tables["season"] = [[fmt.MONTHS_HE[m - 1], fmt.signed_pct(v)] for m, v, _ in season]

    # ── recent months: SA change ─────────────────────────────────────────
    rec = []
    for r in months[-RECENT:]:
        p = by_t.get((r["t"][0] - 1, 12) if r["t"][1] == 1 else (r["t"][0], r["t"][1] - 1))
        c = _chg(r.get("excl_sa"), p.get("excl_sa")) if p else None
        tc = _chg(r.get("excl_trend"), p.get("excl_trend")) if p else None
        rec.append((r["t"], r.get("excl_sa"), c, tc))
    charts["recent"] = {"x": [_mshort(t) for t, *_ in rec],
                        "chg": [round(c * 100, 1) if c is not None else None for _, _, c, _ in rec],
                        "trend": [round(c * 100, 2) if c is not None else None
                                  for _, _, _, c in rec]}
    tables["recent"] = [[_mname(t), _m(sa) if sa is not None else "",
                         fmt.signed_pct(c) if c is not None else "",
                         fmt.signed_pct(tc, 2) if tc is not None else ""]
                        for t, sa, c, tc in reversed(rec)]

    # ── travel and passenger fares, monthly SA ───────────────────────────
    charts["travel"] = {"x": charts["monthly"]["x"],
                        "travel": [round(r["travel_sa"], 1) if r.get("travel_sa") is not None
                                   else None for r in months],
                        "fares": [round(r["fares_sa"], 1) if r.get("fares_sa") is not None
                                  else None for r in months]}
    tables["travel"] = [[lbl, _m(total_of(ts, "travel")) if total_of(ts, "travel") is not None
                         else "", _m(total_of(ts, "fares")) if total_of(ts, "fares") is not None
                         else ""] for lbl, ts in year_cols]

    # ── other transport: freight breakdown by year (t2) ──────────────────
    def t2_years(s):
        out = []
        for lbl, ts in year_cols:
            out.append(_sumd(s, ts))
        return out

    if freight:
        fr = [(f["short"], t2_years(f["s"])) for f in freight]
        fr = [f for f in fr if any(v for v in f[1] if v)]
    else:
        fr = []
    if fr:
        charts["freight"] = {"x": [lbl for lbl, _ in year_cols],
                             "series": [{"name": n, "data": [round(v / 1000, 2) if v is not None
                                                             else None for v in vals]}
                                        for n, vals in fr]}
        tables["freight"] = [[lbl] + [_m(vals[i]) if vals[i] is not None else "" for _, vals in fr]
                             for i, (lbl, _) in enumerate(year_cols)]
        labels["freight_cols"] = ["שנה"] + [n for n, _ in fr]

    # ── business services by industry (t2) ───────────────────────────────
    ind_rows = []
    for ind in industries:
        a = _sumd(ind["s"], l12)
        b = _sumd(ind["s"], p12) if p12 else None
        if a is None:
            continue
        ind_rows.append({**ind, "l12": a, "p12": b, "chg": _chg(a, b)})
    tops = [r for r in ind_rows if not r["sub"]]
    tops.sort(key=lambda r: (-r["l12"], r["short"]))
    biz12 = _sumd(business, l12)
    if tops:
        charts["industries"] = {"names": [r["short"] for r in tops],
                                "now": [round(r["l12"], 1) for r in tops],
                                "prev": [round(r["p12"], 1) if r["p12"] is not None else None
                                         for r in tops]}
        tbl = []
        for r in tops:
            tbl.append([r["short"], _m(r["l12"]), _m(r["p12"]) if r["p12"] is not None else "",
                        fmt.signed_pct(r["chg"]) if r["chg"] is not None else "",
                        fmt.pct(r["l12"] / biz12) if biz12 else ""])
            for s in sorted((x for x in ind_rows if x["sub"] and x["parent"] == r["short"]),
                            key=lambda x: (-x["l12"], x["short"])):
                tbl.append([f"מזה: {s['short']}", _m(s["l12"]),
                            _m(s["p12"]) if s["p12"] is not None else "",
                            fmt.signed_pct(s["chg"]) if s["chg"] is not None else "",
                            fmt.pct(s["l12"] / biz12) if biz12 else ""])
        tables["industries"] = tbl

    # Industries by full calendar year (lines).
    ind_years = [y for y in full_years
                 if all(_sumd(r["s"], [(y, m) for m in range(1, 13)]) is not None for r in tops)]
    if tops and len(ind_years) >= 2:
        charts["ind_years"] = {
            "x": [str(y) for y in ind_years],
            "series": [{"name": r["short"],
                        "data": [round(_sumd(r["s"], [(y, m) for m in range(1, 13)]) / 1000, 2)
                                 for y in ind_years]} for r in tops],
        }
        tables["ind_years"] = [[str(y)] + [_b(_sumd(r["s"], [(y, m) for m in range(1, 13)]))
                                           for r in tops] for y in ind_years]
        labels["ind_years_cols"] = ["שנה"] + [r["short"] for r in tops]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if sa_chg is not None:
        add("month", f"ב{_mname(lt)} הסתכם יצוא השירותים (לא כולל חברות הזנק, מנוכה עונתיות) "
                     f"ב-{_b(last['excl_sa'])} מיליארד דולר, {_word(sa_chg)} של "
                     f"{fmt.pct(abs(sa_chg))} לעומת {_mname(prev['t'])}.")
    if ytd_chg is not None:
        add("ytd", f"מתחילת השנה ({_range(end_m, cur_year)}) יוצאו שירותים (כולל חברות הזנק) בהיקף "
                   f"{_b(ytd_now)} מיליארד דולר, {_word(ytd_chg)} של {fmt.pct(abs(ytd_chg))} "
                   f"לעומת התקופה המקבילה ב-{cur_year - 1} ({_b(ytd_prev)} מיליארד).")
    if hshare is not None and full_years:
        y0 = full_years[0]
        ts0 = [(y0, m) for m in range(1, 13)]
        h0, e0 = total_of(ts0, "hitech"), total_of(ts0, "excl")
        if h0 is not None and e0 and abs(hshare - h0 / e0) >= 0.03:
            add("hitech", f"שירותי ההיי-טק הם {fmt.pct(hshare)} מיצוא השירותים ב-{RECENT} "
                          f"החודשים האחרונים (לא כולל חברות הזנק), לעומת {fmt.pct(h0 / e0)} "
                          f"ב-{y0}.")
    if tops and biz12:
        lead = tops[0]
        share = lead["l12"] / biz12
        if share >= 0.25:
            subs = sorted((x for x in ind_rows if x["sub"] and x["parent"] == lead["short"]),
                          key=lambda x: (-x["l12"], x["short"]))
            tail = ""
            if subs:
                tail = (f" מזה {subs[0]['short']}: {_b(subs[0]['l12'])} מיליארד "
                        f"({fmt.pct(subs[0]['l12'] / lead['l12'])} מהענף).")
            add("industry", f"ענף {lead['short']} מוביל את יצוא השירותים העסקיים: "
                            f"{_b(lead['l12'])} מיליארד דולר ב-{RECENT} החודשים האחרונים, "
                            f"{fmt.pct(share)} מהשירותים העסקיים." + tail)
    trav12 = total_of(l12, "travel")
    tyears = [(y, total_of([(y, m) for m in range(1, 13)], "travel")) for y in full_years]
    tyears = [t for t in tyears if t[1]]
    if trav12 is not None and tyears:
        peak_y, peak_v = max(tyears, key=lambda t: (t[1], t[0]))
        ratio = trav12 / peak_v
        if ratio < 1 - TRAVEL_GAP:
            add("travel", f"יצוא שירותי התיירות (הוצאות מבקרים מחו\"ל בישראל) ב-{RECENT} החודשים "
                          f"האחרונים: {_b(trav12)} מיליארד דולר, {fmt.pct(ratio, 0)} בלבד "
                          f"מהשיא של {peak_y} ({_b(peak_v)} מיליארד).")
        elif ratio > 1 + TRAVEL_GAP:
            add("travel", f"יצוא שירותי התיירות ב-{RECENT} החודשים האחרונים ({_b(trav12)} מיליארד "
                          f"דולר) גבוה ב-{fmt.pct(ratio - 1)} משנת השיא הקודמת, {peak_y}.")
    if fr and freight:
        big = max(freight, key=lambda f: (sum(v for v in t2_years(f["s"]) if v), f["short"]))
        fy = [(y, _sumd(big["s"], [(y, m) for m in range(1, 13)])) for y in full_years]
        fy = [t for t in fy if t[1]]
        if len(fy) >= 3:
            py, pv = max(fy, key=lambda t: (t[1], t[0]))
            ly, lv = fy[-1]
            drop = 1 - lv / pv
            if py != ly and drop >= FREIGHT_DROP:
                add("freight", f"הסעיף הגדול ביצוא שירותי התחבורה, {big['short']}, הגיע לשיא של "
                               f"{_b(pv)} מיליארד דולר ב-{py}. ב-{ly} הוא הסתכם ב-{_b(lv)} "
                               f"מיליארד, ירידה של {fmt.pct(drop)}.")
    run = 0
    tr = [r.get("excl_trend") for r in months]
    for k in range(len(tr) - 1, 0, -1):
        a, b = tr[k], tr[k - 1]
        if a is None or b is None or a == b:
            break
        if run and (a > b) != (tr[-1] > tr[-2]):
            break
        run += 1
    if run >= 4 and tr[-1] is not None and tr[-2] is not None:
        add("trend", f"קו המגמה של יצוא השירותים (לא כולל חברות הזנק) "
                     f"{'עולה' if tr[-1] > tr[-2] else 'יורד'} זה {run} חודשים ברציפות, "
                     f"עד {_b(tr[-1])} מיליארד דולר ב{_mname(lt)}.")
    if len(season) == 12:
        hi_m = max(season, key=lambda s: (s[1], -s[0]))
        if hi_m[1] >= 0.1:
            add("season", f"{fmt.MONTHS_HE[hi_m[0] - 1]} הוא החודש החזק בשנה: בממוצע של "
                          f"{len(full_years)} שנים מלאות, היצוא בו גבוה ב-{fmt.pct(hi_m[1])} "
                          f"מהנתון המנוכה עונתיות.")
    st12 = total_of(l12, "startups")
    tot12 = total_of(l12, "total")
    if st12 is not None and tot12 and st12 / tot12 >= 0.02:
        add("startups", f"יצוא השירותים של חברות הזנק ועסקאות חריגות בנכסים בלתי מוחשיים הוסיף "
                        f"{_b(st12)} מיליארד דולר ב-{RECENT} החודשים האחרונים "
                        f"({fmt.pct(st12 / tot12)} מסך היצוא). הסכום תנודתי מאוד מחודש לחודש.")

    # ── text ─────────────────────────────────────────────────────────────
    rel_date = pd.Timestamp(latest_rel["RELEASE_DATE"])
    release = {"no": latest_rel["RELEASE_NO"], "date": fmt.d_he(rel_date),
               "title": latest_rel["TITLE"],
               "headline": re.sub(r"^[\s•·*-]+", "", str(latest_rel["HEADLINE"])).strip(),
               "url": latest_rel["PAGE_URL"], "pdf": latest_rel["REPORT_PDF_URL"]}
    first = months[0]["t"]
    labels.update({
        "lede": (f"כמה שירותים ישראל מוכרת לחו\"ל בכל חודש: שירותי היי-טק ותוכנה, מחקר ופיתוח, "
                 f"תיירות, תחבורה ושירותים עסקיים אחרים. הנתונים במיליוני דולרים, מתוך ההודעה "
                 f"החודשית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), ומתעדכנים עם כל הודעה חדשה. "
                 f"הנתון האחרון הוא ל{_mname(lt)}: {_b(last['excl_sa'])} מיליארד דולר "
                 f"(מנוכה עונתיות, לא כולל חברות הזנק)."),
        "monthly_note": (f"יצוא השירותים בכל חודש מאז {_mname(first)}, לא כולל חברות הזנק: "
                         f"הנתון המקורי, הנתון המנוכה עונתיות וקו המגמה של הלמ\"ס. "
                         f"אפשר לגרור כדי להתמקד בתקופה."),
        "monthly_aria": f"יצוא שירותים חודשי, {_mname(first)} עד {_mname(lt)}",
        "monthly_caption": "יצוא שירותים מנוכה עונתיות לפי שנה וחודש (מיליוני דולרים)",
        "years_note": ("יצוא השירותים בכל שנה לפי סוג השירות, במיליארדי דולרים"
                       + (f". {cur_year} מוצגת עד {fmt.MONTHS_HE[end_m - 1]}." if partial else ".")),
        "years_aria": f"יצוא שירותים לפי שנה וסוג שירות, {year_cols[0][0]} עד {cur_year}",
        "years_caption": "יצוא שירותים לפי שנה וסוג שירות (מיליארדי דולרים)",
        "mix_note": "חלקו של כל סוג שירות בסך יצוא השירותים בכל שנה, לא כולל חברות הזנק.",
        "mix_aria": "הרכב יצוא השירותים לפי סוג שירות, באחוזים",
        "mix_caption": "הרכב יצוא השירותים לפי שנה (אחוזים)",
        "recent_note": (f"השינוי מחודש לחודש ביצוא השירותים המנוכה עונתיות (לא כולל חברות הזנק) "
                        f"ב-{len(rec)} החודשים האחרונים, ולצדו השינוי בקו המגמה."),
        "recent_aria": f"שינוי חודשי ביצוא השירותים, {_mname(rec[0][0])} עד {_mname(lt)}",
        "recent_caption": "יצוא שירותים מנוכה עונתיות ושינוי חודשי",
        "travel_note": ("יצוא שירותי תיירות (הוצאות של מבקרים מחו\"ל בישראל) ודמי נסיעה (כרטיסי טיסה "
                        "שחברות ישראליות מכרו לתושבי חוץ) בכל חודש, מנוכה עונתיות."),
        "travel_aria": f"יצוא שירותי תיירות ודמי נסיעה לפי חודש, {_mname(first)} עד {_mname(lt)}",
        "travel_caption": "יצוא שירותי תיירות ודמי נסיעה לפי שנה (מיליוני דולרים)",
        "span": f"{first[0]}-{cur_year}",
    })
    if ytd_rows:
        labels.update({
            "ytd_note": (f"השינוי ביצוא כל סוג שירות, {_range(end_m, cur_year)}, לעומת אותם "
                         f"חודשים ב-{cur_year - 1}. הסכומים עצמם בטבלה (מיליוני דולרים)."),
            "ytd_aria": f"יצוא שירותים לפי סוג מתחילת השנה, {cur_year - 1} מול {cur_year}",
            "ytd_caption": "יצוא שירותים לפי סוג מתחילת השנה (מיליוני דולרים)",
            "ytd_cols": ["סוג שירות", str(cur_year - 1), str(cur_year), "שינוי"],
        })
    if len(season) == 12:
        labels.update({
            "season_note": (f"בכמה גבוה או נמוך הנתון המקורי מהנתון המנוכה עונתיות בכל חודש, "
                            f"בממוצע על {len(full_years)} שנים מלאות ({full_years[0]} עד "
                            f"{full_years[-1]}). כך נראית העונתיות של יצוא השירותים."),
            "season_aria": "השפעת העונה על יצוא השירותים לפי חודש",
            "season_caption": "סטייה ממוצעת של הנתון המקורי מהנתון המנוכה עונתיות",
        })
    if fr:
        labels.update({
            "freight_note": ("יצוא שירותי תחבורה מלבד דמי נסיעה, לפי סוג, בכל שנה (מיליארדי דולרים)"
                             + (f". {cur_year} מוצגת עד {fmt.MONTHS_HE[end_m - 1]}." if partial
                                else ".")),
            "freight_aria": "יצוא שירותי תחבורה אחרים לפי סוג ושנה",
            "freight_caption": "יצוא שירותי תחבורה אחרים לפי שנה (מיליוני דולרים)",
        })
    if tops:
        labels.update({
            "industries_note": (f"יצוא השירותים העסקיים לפי הענף של החברה המייצאת, "
                                f"{_mshort(l12[0])} עד {_mshort(l12[-1])}, לעומת 12 החודשים "
                                f"שלפניהם. כולל חברות הזנק (בענף המחקר והפיתוח)."
                                if p12 else
                                f"יצוא השירותים העסקיים לפי הענף של החברה המייצאת, "
                                f"{_mshort(l12[0])} עד {_mshort(l12[-1])}."),
            "industries_aria": "יצוא שירותים עסקיים לפי ענף ב-12 החודשים האחרונים",
            "industries_caption": "יצוא שירותים עסקיים לפי ענף (מיליוני דולרים)",
            "industries_cols": ["ענף", f"{_mshort(l12[0])} עד {_mshort(l12[-1])}",
                                f"{_mshort(p12[0])} עד {_mshort(p12[-1])}" if p12 else "",
                                "שינוי", "אחוז מהשירותים העסקיים"],
            "industries_now": f"{_mshort(l12[0])} עד {_mshort(l12[-1])}",
            "industries_prev": f"{_mshort(p12[0])} עד {_mshort(p12[-1])}" if p12 else "",
        })
    if "ind_years" in charts:
        labels.update({
            "ind_years_note": (f"יצוא השירותים העסקיים של כל ענף בכל שנה מלאה, "
                               f"{ind_years[0]} עד {ind_years[-1]} (מיליארדי דולרים, בציר לוגריתמי כדי "
                               f"שגם הענפים הקטנים ייראו). "
                               f"אפשר להסתיר ענף בלחיצה על שמו במקרא."),
            "ind_years_aria": f"יצוא שירותים עסקיים לפי ענף ושנה, {ind_years[0]} עד {ind_years[-1]}",
            "ind_years_caption": "יצוא שירותים עסקיים לפי ענף ושנה (מיליארדי דולרים)",
        })

    summary = (f"יצוא השירותים של ישראל לפי חודש, סוג שירות וענף, מנתוני הלמ\"ס. "
               f"ב{_mname(lt)}: {_b(last['excl_sa'])} מיליארד דולר (מנוכה עונתיות, "
               f"לא כולל חברות הזנק)"
               + (f", {fmt.signed_pct(sa_chg)} לעומת החודש הקודם" if sa_chg is not None else "")
               + ".")
    desc = (f"כמה שירותים ישראל מייצאת: {_b(last['excl_sa'])} מיליארד דולר ב{_mname(lt)}"
            + (f", {_b(ytd_now)} מיליארד מתחילת השנה" if ytd_now is not None else "")
            + ". היי-טק, תיירות ותחבורה, לפי חודש וענף.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first[0]}/{cur_year}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "יצוא שירותים מישראל: נתונים חודשיים | הלמ\"ס",
                "description": desc,
                "name": "יצוא השירותים של ישראל",
                "alternate_names": ["יצוא שירותים", "יצוא שירותי היי-טק",
                                    "יצוא שירותים לפי ענף", "יצוא שרותים"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"ytd": bool(ytd_rows), "season": len(season) == 12, "freight": bool(fr),
                  "industries": bool(tops), "ind_years": "ind_years" in charts},
    }
