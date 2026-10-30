"""ריביות משכנתאות: new housing loans to households, banking system total.

Input: the BoI `BIR_MRTG_99` dataflow, one row per series per month. Series
are picked by their dimension codes (never by series number or name):

  BS_ITEM          A2C housing loans; A2CX2 / A2C2 the same split into
                   "excluding purchase groups" / purchase groups (they sum
                   to A2C); A2C5 investment apartments; A2C1 the reduced-
                   price programme; A2B2 consumer credit secured by a home
  DATA_TYPE        B volume, B_SA seasonally adjusted volume, N number of
                   loans, R average rate, RB / RM anchor rate / margin of
                   variable-rate loans, T years to final maturity, PTI
                   payment-to-income
  INDEXATION_TYPE  NI unindexed, CPI CPI-linked, IFC_DFC foreign currency
  IR_FV_TYPE       F fixed, V variable, A all
  LTV / PTI        loan-to-value / payment-to-income bands (L0 / P01 total;
                   P07 = bullet and balloon loans, outside the PTI bands)
  BIR_COVERAGE     N new, NO new to repay a loan at another bank, RC
                   recycled at the same bank

Volumes are in units of 10**UNIT_MULT shekels (thousands). Breakdowns lag
the headline total by a month at times, so every view uses the latest
month its own series reach, and says which month that is.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

TRACKS = [  # (key, label, dims) — the volume split of new housing loans
    ("ni_v", "לא צמודה, משתנה (פריים ודומיה)", {"BS_ITEM": "A2CX2", "INDEXATION_TYPE": "NI", "IR_FV_TYPE": "V"}),
    ("ni_f", "לא צמודה, קבועה", {"BS_ITEM": "A2CX2", "INDEXATION_TYPE": "NI", "IR_FV_TYPE": "F"}),
    ("cpi_v", "צמודת מדד, משתנה", {"BS_ITEM": "A2CX2", "INDEXATION_TYPE": "CPI", "IR_FV_TYPE": "V"}),
    ("cpi_f", "צמודת מדד, קבועה", {"BS_ITEM": "A2CX2", "INDEXATION_TYPE": "CPI", "IR_FV_TYPE": "F"}),
    # These two are published only as fixed + variable: summed.
    ("fx", "צמודת מט\"ח", {"BS_ITEM": "A2CX2", "INDEXATION_TYPE": "IFC_DFC", "IR_FV_TYPE": ("V", "F")}),
    ("groups", "קבוצות רכישה", {"BS_ITEM": "A2C2", "IR_FV_TYPE": ("V", "F")}),
]
LTV_BANDS = [("L1", "עד 30%"), ("L2", "30% עד 45%"), ("L3", "45% עד 60%"),
             ("L4", "60% עד 75%"), ("L5", "75% עד 90%"), ("L6", "מעל 90%"),
             ("L7", "ללא בטוחה")]
PTI_BANDS = [("P10", "עד 10%"), ("P11", "10% עד 20%"), ("P03", "20% עד 30%"),
             ("P04", "30% עד 40%"), ("P12", "40% עד 50%"), ("P13", "50% עד 60%"),
             ("P14", "60% עד 80%"), ("P15", "מעל 80%"), ("P07", "בולט ובלון")]
BASE = {"BS_ITEM": "A2C", "BIR_COVERAGE": "N", "INDEXATION_TYPE": "_T",
        "IR_FV_TYPE": "A", "LTV": "L0", "PTI": "P01"}
RECENT = 12  # months in the distribution views


def _month(p):
    y, m = p.split("-")
    return f"{MONTHS_HE[int(m) - 1]} {y}"


def _bn(v):
    return f"{v / 1e9:,.2f}"


def _m(v):
    return f"{v / 1e6:,.0f}"


def _pct(v, d=1):
    return f"{v:.{d}f}%"


def _signed(v, d=1):
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.{d}f}"


def _prepare(df):
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].str.strip()
    df["v"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    mult = pd.to_numeric(df["UNIT_MULT"], errors="coerce").fillna(0)
    shekel = df["UNIT_MEASURE"] == "ILS"
    df.loc[shekel, "v"] = df.loc[shekel, "v"] * (10 ** mult[shekel])
    df = df[df["TIME_PERIOD"].str.match(r"^\d{4}-\d{2}$")].dropna(subset=["v"])
    return df.sort_values(["SERIES_CODE", "TIME_PERIOD", "v"], kind="stable")


def _pick(df, **dims):
    """The one monthly series matching `dims` (BASE fills the rest).
    Several matches: the longest, ties to the smallest code."""
    want = {**BASE, **dims}
    sub = df
    for k, v in want.items():
        if k in sub.columns:
            sub = sub[sub[k] == v]
    if sub.empty:
        return pd.Series(dtype=float)
    counts = sub.groupby("SERIES_CODE").size()
    code = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    s = sub[sub["SERIES_CODE"] == code].drop_duplicates("TIME_PERIOD", keep="last")
    return s.set_index("TIME_PERIOD")["v"].sort_index()


def _common_last(series):
    """Latest month every given series reaches."""
    ends = [s.index[-1] for s in series if not s.empty]
    return min(ends) if len(ends) == len(series) else None


def _yoy_month(p):
    y, m = p.split("-")
    return f"{int(y) - 1}-{m}"


# ── insights ─────────────────────────────────────────────────────────────


def insight_volume(vol, n):
    if len(vol) < 13:
        return None
    last = vol.index[-1]
    prev = _yoy_month(last)
    if prev not in vol.index or vol[prev] == 0:
        return None
    ch = (vol[last] / vol[prev] - 1) * 100
    word = "עלייה" if ch > 0 else "ירידה"
    tail = ""
    if last in n.index and n[last] > 0:
        tail = f", {int(n[last]):,} הלוואות בממוצע של {vol[last] / n[last] / 1e6:,.2f} מיליון ₪"
    if abs(ch) < 2:
        return (f"ב{_month(last)} ניתנו משכנתאות חדשות ב-{_bn(vol[last])} מיליארד ₪{tail}, "
                f"כמעט ללא שינוי לעומת {_month(prev)}.")
    return (f"ב{_month(last)} ניתנו משכנתאות חדשות ב-{_bn(vol[last])} מיליארד ₪{tail}: "
            f"{word} של {abs(ch):.1f}% לעומת {_month(prev)}.")


def insight_rolling(vol):
    """12-month sum against the 12 months before (a seasonality-free trend)."""
    if len(vol) < 24:
        return None
    a, b = vol.iloc[-12:].sum(), vol.iloc[-24:-12].sum()
    if b == 0:
        return None
    ch = (a / b - 1) * 100
    word = "גבוה" if ch > 0 else "נמוך"
    return (f"ב-12 החודשים שעד {_month(vol.index[-1])} ניתנו משכנתאות ב-{_bn(a)} מיליארד ₪, "
            f"{word} ב-{abs(ch):.1f}% מ-12 החודשים שקדמו להם ({_bn(b)} מיליארד ₪).")


def insight_prime_share(shares, month):
    if month is None or "ni_v" not in shares or month not in shares["ni_v"].index:
        return None
    s = shares["ni_v"]
    cur = float(s[month])
    prev = _yoy_month(month)
    tail = ""
    if prev in s.index:
        d = cur - float(s[prev])
        if abs(d) >= 1:
            tail = (f", {'עלייה' if d > 0 else 'ירידה'} של {abs(d):.1f} נקודות אחוז "
                    f"לעומת {_month(prev)}")
    return (f"המסלול הלא צמוד בריבית משתנה (פריים ודומיו) היה {_pct(cur)} מהמשכנתאות "
            f"החדשות ב{_month(month)}{tail}.")


def insight_rates(rates):
    """The gap between the unindexed fixed and the CPI-linked fixed rate."""
    a, b = rates.get("ni_f"), rates.get("cpi_f")
    if a is None or b is None or a.empty or b.empty:
        return None
    month = _common_last([a, b])
    if month is None:
        return None
    gap = float(a[month] - b[month])
    if gap <= 0:
        return None
    return (f"ב{_month(month)} הריבית הממוצעת במסלול הקבוע הלא צמוד הייתה {_pct(a[month], 2)}, "
            f"לעומת {_pct(b[month], 2)} במסלול הקבוע הצמוד למדד: פער של {gap:.2f} נקודות אחוז.")


def insight_ltv(ltv_recent):
    if not ltv_recent or ltv_recent["total"] == 0:
        return None
    high = sum(v for k, v in ltv_recent["by_code"].items() if k in ("L5", "L6"))
    share = high / ltv_recent["total"] * 100
    over60 = sum(v for k, v in ltv_recent["by_code"].items() if k in ("L4", "L5", "L6"))
    return (f"ב-{ltv_recent['months']} החודשים שעד {_month(ltv_recent['end'])}, "
            f"{over60 / ltv_recent['total'] * 100:.1f}% מסכום המשכנתאות ניתן בשיעור מימון מעל 60%, "
            f"ורק {share:.1f}% מעל 75%.")


def insight_refi(refi, vol, month):
    if month is None or month not in refi.index or month not in vol.index or vol[month] == 0:
        return None
    share = refi[month] / vol[month] * 100
    if share < 1:
        return None
    return (f"{share:.1f}% מהמשכנתאות החדשות ב{_month(month)} ({_m(refi[month])} מיליון ₪) "
            "ניתנו למחזור משכנתא בבנק אחר.")


def insight_rate_trend(s, label):
    """A track's average rate now against twelve months earlier."""
    if s is None or len(s) < 13:
        return None
    last = s.index[-1]
    prev = _yoy_month(last)
    if prev not in s.index:
        return None
    d = float(s[last] - s[prev])
    if abs(d) < 0.1:
        return (f"הריבית הממוצעת במסלול {label} ({_pct(s[last], 2)} ב{_month(last)}) "
                f"כמעט לא השתנתה לעומת {_month(prev)} ({_pct(s[prev], 2)}).")
    word = "עלתה" if d > 0 else "ירדה"
    return (f"הריבית הממוצעת במסלול {label} {word} מ-{_pct(s[prev], 2)} ב{_month(prev)} "
            f"ל-{_pct(s[last], 2)} ב{_month(last)} ({abs(d):.2f} נקודות אחוז).")


def insight_term(terms):
    got = [(lbl, terms[k]) for k, lbl in (("ni", "במשכנתאות הלא צמודות"), ("cpi", "בצמודות למדד"))
           if not terms[k].empty]
    if not got:
        return None
    month = _common_last([s for _, s in got])
    if month is None:
        return None
    parts = [f"{s[month]:.1f} שנים {lbl}" for lbl, s in got if month in s.index]
    return f"התקופה הממוצעת עד הפירעון הסופי ב{_month(month)}: {' ו-'.join(parts)}."


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["loans"])
    vol = _pick(df, DATA_TYPE="B")
    vol_sa = _pick(df, DATA_TYPE="B_SA")
    n = _pick(df, DATA_TYPE="N")
    pti_avg = _pick(df, DATA_TYPE="PTI")

    # Rates by track. The CPI-linked variable rate is its anchor + margin.
    rates = {
        "cpi_f": _pick(df, DATA_TYPE="R", INDEXATION_TYPE="CPI", IR_FV_TYPE="F"),
        "ni_f": _pick(df, DATA_TYPE="R", INDEXATION_TYPE="NI", IR_FV_TYPE="F"),
        "cpi_all": _pick(df, DATA_TYPE="R", INDEXATION_TYPE="CPI"),
        "fx": _pick(df, DATA_TYPE="R", INDEXATION_TYPE="IFC_DFC"),
    }
    anchor = _pick(df, DATA_TYPE="RB", INDEXATION_TYPE="CPI", IR_FV_TYPE="V")
    margin = _pick(df, DATA_TYPE="RM", INDEXATION_TYPE="CPI", IR_FV_TYPE="V")
    if not anchor.empty and not margin.empty:
        rates["cpi_v"] = (anchor + margin).dropna()
    rate_labels = {"cpi_f": "צמודה קבועה", "ni_f": "לא צמודה קבועה",
                   "cpi_v": "צמודה משתנה (עוגן ועוד הוספה)", "cpi_all": "צמודה, כל המסלולים",
                   "fx": "צמודת מט\"ח"}
    rate_keys = [k for k in ("ni_f", "cpi_f", "cpi_v", "fx") if not rates.get(k, pd.Series(dtype=float)).empty]
    rate_months = sorted(set().union(*[set(rates[k].index) for k in rate_keys])) if rate_keys else []
    rate_month = _common_last([rates[k] for k in rate_keys if k != "fx"]) if rate_keys else None

    # Track mix.
    def _track(dims):
        ir = dims.get("IR_FV_TYPE")
        if isinstance(ir, tuple):
            parts = [_pick(df, DATA_TYPE="B", **{**dims, "IR_FV_TYPE": t}) for t in ir]
            parts = [p for p in parts if not p.empty]
            return pd.concat(parts, axis=1).sum(axis=1, min_count=1).dropna() if parts else pd.Series(dtype=float)
        return _pick(df, DATA_TYPE="B", **dims)

    track = {k: _track(dims) for k, _, dims in TRACKS}
    track = {k: s for k, s in track.items() if not s.empty}
    if vol.empty and len(track) == len(TRACKS):
        # The tracks partition housing loans (they sum to the total to the
        # shekel), so without the headline series their full sum stands in.
        vol = pd.concat(track, axis=1).dropna().sum(axis=1).sort_index()
    has_vol = not vol.empty
    if not has_vol and not rate_keys:
        raise ValueError("neither a new housing-loan volume nor a rate series")
    # Without volumes, the volume views drop and the rest of the page stays.
    last = vol.index[-1] if has_vol else rate_month or rate_months[-1]
    mix_month = _common_last(list(track.values())) if track else None
    shares = {}
    if track:
        tot = pd.concat(track, axis=1).fillna(0)
        tot = tot[tot.sum(axis=1) > 0]
        for k in tot.columns:
            shares[k] = (tot[k] / tot.sum(axis=1) * 100).round(2)

    # LTV and PTI bands over the latest RECENT months they reach.
    def bands(spec, dim):
        got = {code: _pick(df, DATA_TYPE="B", **{dim: code}) for code, _ in spec}
        got = {c: s for c, s in got.items() if not s.empty}
        if not got:
            return None
        end = _common_last(list(got.values()))
        months = sorted({m for s in got.values() for m in s.index if m <= end})[-RECENT:]
        by = {c: float(s.reindex(months).fillna(0).sum()) for c, s in got.items()}
        return {"end": end, "months": len(months), "by_code": by, "total": sum(by.values())}

    ltv = bands(LTV_BANDS, "LTV")
    pti = bands(PTI_BANDS, "PTI")

    # Other slices of new lending.
    refi = _pick(df, DATA_TYPE="B", BIR_COVERAGE="NO")
    inv = _pick(df, DATA_TYPE="B", BS_ITEM="A2C5")
    reduced = _pick(df, DATA_TYPE="B", BS_ITEM="A2C1")
    terms = {k: _pick(df, DATA_TYPE="T", INDEXATION_TYPE=c) for k, c in (("ni", "NI"), ("cpi", "CPI"))}
    side_month = _common_last([s for s in (refi, inv) if not s.empty]) if not refi.empty else None
    consumer = _pick(df, DATA_TYPE="B", BS_ITEM="A2B2", PROPERTY_VALUE="_Z")
    consumer_rate = _pick(df, DATA_TYPE="R", BS_ITEM="A2B2", INDEXATION_TYPE="NI")

    rules = [
        ("rate_trend", insight_rate_trend(rates.get("ni_f"), "הקבוע הלא צמוד")),
        ("volume", insight_volume(vol, n)),
        ("rolling", insight_rolling(vol)),
        ("rates", insight_rates(rates)),
        ("prime_share", insight_prime_share(shares, mix_month)),
        ("ltv", insight_ltv(ltv)),
        ("refi", insight_refi(refi, vol, side_month)),
        ("term", insight_term(terms)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # KPIs.
    prev = _yoy_month(last)
    yoy = (vol[last] / vol[prev] - 1) * 100 if has_vol and prev in vol.index and vol[prev] else None
    kpis = {}
    if has_vol:
        kpis["volume"] = {"value": round(float(vol[last]), 0), "display": _bn(vol[last]),
                          "tone": "brand"}
    if yoy is not None:
        kpis["yoy"] = {"value": round(yoy, 2), "display": _signed(yoy) + "%",
                       "tone": "ok" if yoy > 2 else "warn" if yoy < -2 else "brand"}
    for k in ("ni_f", "cpi_f"):
        s = rates.get(k)
        if s is not None and not s.empty:
            kpis[f"rate_{k}"] = {"value": float(s.iloc[-1]), "display": _pct(s.iloc[-1], 2),
                                 "tone": "brand"}
    if mix_month and "ni_v" in shares:
        kpis["prime_share"] = {"value": float(shares["ni_v"][mix_month]),
                               "display": _pct(shares["ni_v"][mix_month]), "tone": "brand"}
    loan_month = _common_last([vol, n]) if has_vol and not n.empty else None
    if loan_month and n[loan_month]:
        avg = vol[loan_month] / n[loan_month]
        kpis["avg_loan"] = {"value": round(float(avg), 0), "display": f"{avg / 1e6:,.2f}",
                            "tone": "brand"}

    # Charts + tables.
    months = list(vol.index)
    sa = vol_sa.reindex(months) if months else pd.Series(dtype=float)
    volume_chart = {
        "x": months,
        "y": [round(v / 1e9, 3) for v in vol],
        "sa": [None if pd.isna(v) else round(v / 1e9, 3) for v in sa],
    }
    years = sorted({m[:4] for m in months})
    year_table = []
    for y in reversed(years):
        ms = [m for m in months if m.startswith(y)]
        row = {"year": y, "total": _bn(vol[ms].sum()), "months": len(ms),
               "partial": len(ms) < 12}
        if not n.empty:
            nn = n.reindex(ms).dropna()
            row["loans"] = f"{int(nn.sum()):,}" if len(nn) == len(ms) else ""
        year_table.append(row)

    rate_chart = {
        "x": rate_months,
        "series": [{"name": rate_labels[k],
                    "data": [None if pd.isna(v) else round(float(v), 2)
                             for v in rates[k].reindex(rate_months)]} for k in rate_keys],
    }
    rate_table = []
    for m in rate_months[-RECENT:][::-1]:
        rate_table.append({"month": _month(m), "cells": [
            "" if pd.isna(rates[k].get(m)) else _pct(rates[k][m], 2) for k in rate_keys]})

    mix_keys = [k for k, _, _ in TRACKS if k in shares]
    mix_x = list(shares[mix_keys[0]].index) if mix_keys else []
    mix_chart = {
        "x": mix_x,
        "series": [{"name": lbl, "data": [round(float(v), 2) for v in shares[k].reindex(mix_x).fillna(0)]}
                   for k, lbl, _ in TRACKS if k in shares],
    }
    mix_table = []
    if mix_month:
        prev_m = _yoy_month(mix_month)
        for k, lbl, _ in TRACKS:
            if k in shares:
                cur = shares[k].get(mix_month)
                old = shares[k].get(prev_m)
                mix_table.append({"track": lbl,
                                  "amount": _m(track[k].get(mix_month, 0)),
                                  "share": _pct(cur) if cur is not None else "",
                                  "prev": _pct(old) if old is not None else ""})

    def band_view(spec, b):
        if not b:
            return None
        labels = {c: l for c, l in spec}
        rows = [(labels[c], b["by_code"][c]) for c, _ in spec if c in b["by_code"]]
        return {"names": [r[0] for r in rows],
                "share": [round(r[1] / b["total"] * 100, 2) if b["total"] else 0 for r in rows],
                "amount": [round(r[1] / 1e9, 3) for r in rows],
                "table": [{"band": r[0], "amount": _bn(r[1]),
                           "share": _pct(r[1] / b["total"] * 100) if b["total"] else ""} for r in rows]}

    ltv_view, pti_view = band_view(LTV_BANDS, ltv), band_view(PTI_BANDS, pti)

    # Loans: count and average size by year (complete years only).
    loans_chart, loans_table = None, []
    if not n.empty:
        both = pd.concat({"v": vol, "n": n}, axis=1).dropna()
        by_year = both.groupby(both.index.str[:4]).agg(v=("v", "sum"), n=("n", "sum"), k=("n", "size"))
        by_year = by_year[by_year["k"] == 12]
        if len(by_year):
            loans_chart = {"x": list(by_year.index),
                           "n": [int(v) for v in by_year["n"]],
                           "avg": [round(v / c / 1e6, 3) for v, c in zip(by_year["v"], by_year["n"], strict=True)]}
            loans_table = [{"year": y, "n": f"{int(r.n):,}", "avg": f"{r.v / r.n / 1e6:,.2f}"}
                           for y, r in by_year.iloc[::-1].iterrows()]

    # Refinancing, investment flats, reduced-price programme as % of new lending.
    def share_of(s):
        s = s.reindex(months)
        return [None if pd.isna(a) or not vol[m] else round(a / vol[m] * 100, 2)
                for m, a in zip(months, s, strict=True)]

    slices = [(lbl, s) for lbl, s in (("מחזור משכנתא מבנק אחר", refi),
                                      ("דירה להשקעה", inv),
                                      ("דירה בהנחה (מחיר מופחת)", reduced))
              if has_vol and not s.empty]
    slices_chart = {"x": months, "series": [{"name": lbl, "data": share_of(s)} for lbl, s in slices]}
    slice_rows = []
    for y in reversed(years):
        ms = [m for m in months if m.startswith(y)]
        total = vol[ms].sum()
        cells = []
        for _, s in slices:
            got = s.reindex(ms).dropna()
            cells.append(_pct(got.sum() / vol[got.index].sum() * 100) if len(got) else "")
        if total:
            slice_rows.append({"year": y, "cells": cells})

    # FX-linked loans are a sliver of lending; their monthly term average
    # swings with a handful of loans, so it stays out of the chart.
    term_keys = [(k, lbl) for k, lbl in (("ni", "לא צמודה"), ("cpi", "צמודת מדד"))
                 if not terms[k].empty]
    term_x = sorted(set().union(*[set(terms[k].index) for k, _ in term_keys])) if term_keys else []
    terms_chart = {"x": term_x, "series": [
        {"name": lbl, "data": [None if pd.isna(v) else round(float(v), 2) for v in terms[k].reindex(term_x)]}
        for k, lbl in term_keys]}
    if not pti_avg.empty:
        terms_chart["pti"] = [None if pd.isna(v) else round(float(v), 2) for v in pti_avg.reindex(term_x)]
    terms_table = [{"name": lbl, "value": f"{terms[k].iloc[-1]:.1f}", "month": _month(terms[k].index[-1])}
                   for k, lbl in term_keys]

    consumer_view = None
    if not consumer.empty:
        cx = list(consumer.index)
        consumer_view = {"x": cx, "y": [round(v / 1e6, 1) for v in consumer],
                         "rate": [None if pd.isna(v) else round(float(v), 2) for v in consumer_rate.reindex(cx)],
                         "last": _m(consumer.iloc[-1]), "month": _month(cx[-1]),
                         "last_rate": _pct(consumer_rate.iloc[-1], 2) if not consumer_rate.empty else None}

    span = months or rate_months
    first_year = span[0][:4]
    summary = ("ריבית משכנתא ממוצעת לפי מסלול והיקף המשכנתאות החודשי"
               + (f": ב{_month(last)} ניתנו {_bn(vol[last])} מיליארד ₪" if has_vol else "")
               + (f", ריבית קבועה לא צמודה {_pct(rates['ni_f'].iloc[-1], 2)}" if "rate_ni_f" in kpis else "")
               + ".")
    lede = (f"המשכנתאות החדשות שנתנו הבנקים למשקי בית מ{_month(span[0])} ועד {_month(last)}: "
            "היקף חודשי, ריבית ממוצעת בכל מסלול, תמהיל המסלולים, שיעור המימון, שיעור ההחזר "
            "מההכנסה, מחזור משכנתאות ודירות להשקעה. הנתונים מתוך המאגר הסטטיסטי של בנק ישראל "
            "(הפיקוח על הבנקים) ומתעדכנים מדי חודש.")
    labels = {
        "lede": lede,
        "volume_kpi": f"משכנתאות חדשות ב{_month(last)} (מיליארד ₪)",
        "yoy_kpi": f"שינוי לעומת {_month(prev)}",
        "rate_ni_f_kpi": "ריבית ממוצעת, לא צמודה קבועה" + (f" ({_month(rates['ni_f'].index[-1])})" if "rate_ni_f" in kpis else ""),
        "rate_cpi_f_kpi": "ריבית ממוצעת, צמודה קבועה" + (f" ({_month(rates['cpi_f'].index[-1])})" if "rate_cpi_f" in kpis else ""),
        "prime_share_kpi": f"שיעור המסלול הלא צמוד המשתנה ({_month(mix_month)})" if mix_month else "",
        "avg_loan_kpi": f"משכנתא ממוצעת, מיליון ₪ ({_month(loan_month)})" if loan_month else "",
        "volume_note": (f"סכום המשכנתאות החדשות בכל חודש, במיליארדי ₪, וקו מנוכה עונתיות. "
                        f"נתונים מ-{first_year}; אפשר לגרור את פס הזמן."),
        "volume_aria": (f"גרף קו: סכום המשכנתאות החדשות בכל חודש מ-{first_year} עד {_month(last)}"
                        + (f"; בחודש האחרון {_bn(vol[last])} מיליארד ₪." if has_vol else ".")),
        "year_caption": "סכום המשכנתאות החדשות ומספר ההלוואות בכל שנה",
        "rates_note": ("הריבית הממוצעת על משכנתאות חדשות בכל מסלול. במסלול הצמוד המשתנה: ריבית העוגן "
                       "הממוצעת ועוד ההוספה הממוצעת. למסלול הלא צמוד המשתנה (פריים) אין סדרת ריבית במאגר."),
        "rates_aria": ("גרף קו: ריבית ממוצעת על משכנתאות חדשות לפי מסלול"
                       + (f", עד {_month(rate_month)}." if rate_month else ".")),
        "rates_caption": f"ריבית ממוצעת לפי מסלול, {RECENT} החודשים האחרונים",
        "mix_note": ("חלקו של כל מסלול מסכום המשכנתאות החדשות בכל חודש (100% לכל חודש)."
                     + (f" בטבלה: {_month(mix_month)} מול {_month(_yoy_month(mix_month))}." if mix_month else "")),
        "mix_aria": "גרף שטח מוערם: תמהיל מסלולי המשכנתא החדשה לפי חודש, באחוזים מהסכום.",
        "mix_caption": "סכום וחלק של כל מסלול בחודש האחרון, ושנה קודם",
        "loans_note": "מספר המשכנתאות החדשות בכל שנה מלאה, וסכום המשכנתא הממוצע (מיליון ₪).",
        "loans_aria": "תרשים עמודות וקו: מספר המשכנתאות החדשות וסכום המשכנתא הממוצע לפי שנה.",
        "loans_caption": "מספר המשכנתאות החדשות וסכום ממוצע לפי שנה מלאה",
        "slices_note": ("מחזור משכנתא מבנק אחר, משכנתאות לדירה להשקעה ומשכנתאות בתוכנית דירה בהנחה, "
                        "כאחוז מסכום המשכנתאות החדשות בכל חודש."),
        "slices_aria": "גרף קו: מחזור משכנתאות, דירות להשקעה ודירה בהנחה כאחוז מהמשכנתאות החדשות.",
        "slices_caption": "חלקם של מחזור משכנתאות, דירות להשקעה ודירה בהנחה לפי שנה",
        "terms_note": ("תקופה ממוצעת עד הפירעון הסופי (בשנים) לפי מגזר הצמדה"
                       + (", ושיעור ההחזר הממוצע מההכנסה (ציר ימני)." if "pti" in terms_chart else ".")),
        "terms_aria": "גרף קו: תקופה ממוצעת לפירעון של משכנתאות חדשות לפי מגזר הצמדה.",
        "terms_caption": "תקופה ממוצעת לפירעון (שנים), בחודש האחרון",
    }
    if ltv:
        labels.update(
            ltv_note=(f"סכום המשכנתאות החדשות ב-{ltv['months']} החודשים שעד {_month(ltv['end'])} "
                      "לפי שיעור המימון (סכום ההלוואה כאחוז משווי הנכס)."),
            ltv_aria=f"תרשים עמודות: התפלגות סכום המשכנתאות לפי שיעור מימון, {ltv['months']} חודשים עד {_month(ltv['end'])}.",
            ltv_caption=f"סכום וחלק לפי שיעור מימון, {ltv['months']} חודשים עד {_month(ltv['end'])}",
        )
    if pti:
        labels.update(
            pti_note=(f"סכום המשכנתאות החדשות ב-{pti['months']} החודשים שעד {_month(pti['end'])} "
                      "לפי שיעור ההחזר החודשי מההכנסה. הלוואות בולט ובלון מוצגות בנפרד."),
            pti_aria=f"תרשים עמודות: התפלגות סכום המשכנתאות לפי שיעור החזר מהכנסה, {pti['months']} חודשים עד {_month(pti['end'])}.",
            pti_caption=f"סכום וחלק לפי שיעור החזר מהכנסה, {pti['months']} חודשים עד {_month(pti['end'])}",
        )
    if consumer_view:
        labels.update(
            consumer_note=(f"הלוואות לכל מטרה בבטחון דירת מגורים (לא למטרת דיור), במיליוני ₪ בחודש. "
                           f"ב{consumer_view['month']}: {consumer_view['last']} מיליון ₪"
                           + (f", ריבית ממוצעת לא צמודה {consumer_view['last_rate']}." if consumer_view["last_rate"] else ".")),
            consumer_aria=f"גרף עמודות וקו: הלוואות לכל מטרה בבטחון דירה, סכום חודשי וריבית ממוצעת, עד {consumer_view['month']}.",
            consumer_caption="הלוואות לכל מטרה בבטחון דירה, השנים האחרונות",
        )

    consumer_table = []
    if consumer_view:
        cs = consumer.groupby(consumer.index.str[:4]).agg(["sum", "size"])
        consumer_table = [{"year": y, "total": _m(r["sum"]), "partial": r["size"] < 12}
                          for y, r in cs.iloc[::-1].iterrows()]

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["משכנתאות", "ריבית", "דיור", "בנק ישראל", "אשראי"],
            "temporal_coverage": f"{span[0]}/{last}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "volume": volume_chart,
            "rates": rate_chart,
            "mix": mix_chart,
            "ltv": ltv_view and {k: ltv_view[k] for k in ("names", "share", "amount")},
            "pti": pti_view and {k: pti_view[k] for k in ("names", "share", "amount")},
            "loans": loans_chart,
            "slices": slices_chart,
            "terms": terms_chart,
            "consumer": consumer_view and {k: consumer_view[k] for k in ("x", "y", "rate")},
        },
        "tables": {
            "years": year_table,
            "rates_head": [rate_labels[k] for k in rate_keys],
            "rates": rate_table,
            "mix": mix_table,
            "ltv": ltv_view["table"] if ltv_view else [],
            "pti": pti_view["table"] if pti_view else [],
            "loans": loans_table,
            "slices_head": [lbl for lbl, _ in slices],
            "slices": slice_rows,
            "terms": terms_table,
            "consumer": consumer_table,
        },
        "flags": {"volume": has_vol, "ltv": bool(ltv_view), "pti": bool(pti_view), "loans": bool(loans_chart),
                  "slices": bool(slices), "terms": bool(term_keys),
                  "consumer": bool(consumer_view), "mix": bool(mix_keys)},
        "insights": insights,
        "labels": labels,
    }
