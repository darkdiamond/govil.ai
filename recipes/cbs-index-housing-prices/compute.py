"""מדד מחירי הדירות: CBS dwelling price index, national, by district, new dwellings.

Inputs (CBS Index API rows, one per CODE x FREQ x TIME_PERIOD):

  national   code 40010. Quarterly (Q) rows to 1993, monthly (M) from 1994.
             VALUE_CHAINED puts both eras on one base (CHAIN_BASE); the
             provider chains across every base change, including the 1985
             scale break, so the long-run view starts at the first quarter.
  districts  codes 60000-60500, monthly from Oct 2017. Each district index
             is linked to the national index at its start (it opens at the
             national level, not at 100), so every comparison rebases to
             the first month all districts share. CBS publishes no
             PERCENT_YEAR for them: their 12-month change is computed from
             the levels and labelled as such.
  new        code 70000, new dwellings, monthly from Dec 2018 (the API
             fails for earlier start dates). Also linked to the national
             level; compared after rebasing to the first common month.

The index is computed from transactions of two adjacent months, so each
monthly figure overlaps the one before it. Months are named as CBS's API
labels them (TIME_PERIOD).
"""
import re

import pandas as pd
from govlib import fmt

NATIONAL_CODE = "40010"
NEW_CODE = "70000"
DISTRICT_LABELS = {  # short display names; an unknown code falls back to NAME_HE
    "60000": "ירושלים", "60100": "צפון", "60200": "חיפה",
    "60300": "מרכז", "60400": "תל אביב", "60500": "דרום",
}
DD_MIN = 0.02         # a decline episode counts from a 2% fall below the peak
FAST_RISE = 5.0       # y/y percent at which a rise is flagged (KPI tone)
STREAK_MIN = 3        # months in a row before a streak is worth a sentence
RECENT = 24           # months in the recent monthly-change view
FLAT = 0.05           # |percent| at or below this reads as "no change"


# ── small helpers ───────────────────────────────────────────────────────

def _num(s):
    s = str(s).strip().replace(",", "").replace("−", "-")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _ym(tp):
    y, m = tp.split("-")
    return int(y), int(m)


def _shift(tp, k):
    y, m = _ym(tp)
    t = y * 12 + (m - 1) + k
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def _mdiff(a, b):
    (ya, ma), (yb, mb) = _ym(a), _ym(b)
    return (ya - yb) * 12 + ma - mb


def _mon(tp):
    y, m = _ym(tp)
    return f"{fmt.MONTHS_HE[m - 1]} {y}"


def _mon_short(tp):
    y, m = _ym(tp)
    return f"{fmt.MONTHS_SHORT_HE[m - 1]} {y}"


def _q_label(tp):
    y, q = tp.split("-Q")
    return f"רבעון {q} {y}"


def _q_month(tp):
    y, q = tp.split("-Q")
    return f"{y}-{(int(q) - 1) * 3 + 1:02d}"


def _signed(p, digits=1):
    """A percent already on 0-100, signed, U+2212 minus; zero unsigned."""
    body = f"{abs(p):.{digits}f}"
    if float(body) == 0:
        return body + "%"
    return ("+" if p > 0 else fmt.MINUS) + body + "%"


def _ss(p, digits=1):
    """_signed, isolated for a Hebrew sentence."""
    return fmt.isolate(_signed(p, digits))


def _sign(p):
    """+1 / -1 / 0 for a percent, with |p| <= FLAT as no change."""
    p = float(p)
    return 1 if p > FLAT else (-1 if p < -FLAT else 0)


def _abs(p, digits=1):
    return f"{abs(p):.{digits}f}%"


def _verb(p, up="עלה", down="ירד"):
    return up if p > 0 else down


def _from(word):
    """'מ' glued to a Hebrew word, 'מ-' before a digit: 'מינואר 2020', 'מ-2020'."""
    return ("מ" if re.match(r"[א-ת]", word) else "מ-") + word


def _base_he(cb):
    m = re.fullmatch(r"\s*(\d{4})\s*ממוצע\s*", cb or "")
    if m:
        return f"ממוצע {m.group(1)} = 100"
    return f"{(cb or '').strip()} = 100"


def _monthly(df, code):
    d = df[(df["CODE"].astype(str).str.strip() == code) & (df["FREQ"].str.strip() == "M")].copy()
    d["TIME_PERIOD"] = d["TIME_PERIOD"].str.strip()
    d = d[d["TIME_PERIOD"].str.fullmatch(r"\d{4}-\d{2}")]
    d = d.sort_values(["TIME_PERIOD", "VALUE_CHAINED"], kind="mergesort")
    d = d.drop_duplicates("TIME_PERIOD", keep="last").set_index("TIME_PERIOD")
    d["v"] = d["VALUE_CHAINED"].map(_num)
    d = d[d["v"].notna()]
    return d


# ── national ────────────────────────────────────────────────────────────

def _quarters_before(nat, first_month, chain_base):
    """Quarterly rows before the monthly era, on the same chain base."""
    q = nat[(nat["CODE"].astype(str).str.strip() == NATIONAL_CODE) & (nat["FREQ"].str.strip() == "Q")].copy()
    q["TIME_PERIOD"] = q["TIME_PERIOD"].str.strip()
    q = q[q["TIME_PERIOD"].str.fullmatch(r"\d{4}-Q[1-4]")]
    q = q.sort_values(["TIME_PERIOD", "VALUE_CHAINED"], kind="mergesort").drop_duplicates("TIME_PERIOD", keep="last")
    q = q[q["TIME_PERIOD"].map(_q_month) < first_month]
    q = q[q["CHAIN_BASE"].str.strip() == chain_base]
    q["v"] = q["VALUE_CHAINED"].map(_num)
    q = q[q["v"].notna() & (q["v"] > 0)]
    return q.reset_index(drop=True)


def _episodes(v):
    """Declines of DD_MIN or more below a running peak, oldest first."""
    out, peak_v, peak_p, cur = [], None, None, None
    for p, x in v.items():
        if peak_v is None or x >= peak_v:
            if cur is not None:
                cur["recovered"] = p
                if cur["depth"] <= -DD_MIN:
                    out.append(cur)
                cur = None
            peak_v, peak_p = x, p
            continue
        dd = x / peak_v - 1
        if cur is None:
            cur = {"peak": peak_p, "trough": p, "depth": dd, "recovered": None}
        elif dd < cur["depth"]:
            cur["trough"], cur["depth"] = p, dd
    if cur is not None and cur["depth"] <= -DD_MIN:
        out.append(cur)
    return out


# ── compute ─────────────────────────────────────────────────────────────

def compute(frames):
    nat = frames["national"]
    m = _monthly(nat, NATIONAL_CODE)
    if len(m) < 13:
        raise ValueError("national housing index: fewer than 13 monthly rows")
    v = m["v"]
    pct = m["PERCENT"].map(_num)
    pyy = m["PERCENT_YEAR"].map(_num)
    last = v.index[-1]
    first_m = v.index[0]
    chain_base = m["CHAIN_BASE"].iloc[-1].strip()
    base_he = _base_he(chain_base)

    q = _quarters_before(nat, first_m, chain_base)
    has_q = not q.empty
    long_first = q["TIME_PERIOD"].iloc[0][:4] if has_q else first_m[:4]

    # Long-run series on a time axis: [date, value, label].
    long_pts = []
    for _, r in q.iterrows():
        long_pts.append([_q_month(r["TIME_PERIOD"]) + "-01", round(r["v"], 2), _q_label(r["TIME_PERIOD"])])
    for p, x in v.items():
        long_pts.append([p + "-01", round(x, 2), _mon(p)])

    # Year-end levels table.
    year_end = {}
    for _, r in q.iterrows():
        year_end[r["TIME_PERIOD"][:4]] = (r["v"], "Q", r["TIME_PERIOD"])
    for p, x in v.items():
        year_end[p[:4]] = (x, "M", p)
    long_rows = []
    years = sorted(year_end)
    for i, y in enumerate(years):
        val, kind, p = year_end[y]
        chg = "–"
        if i > 0:
            pv, pkind, pp = year_end[years[i - 1]]
            prev_full = (pkind == "M" and pp.endswith("-12")) or (pkind == "Q" and pp.endswith("Q4"))
            if pkind == kind and prev_full and int(years[i - 1]) == int(y) - 1:
                chg = _signed((val / pv - 1) * 100)
        partial = kind == "M" and not p.endswith("-12")
        long_rows.append([y + (f" (עד {fmt.MONTHS_HE[_ym(p)[1] - 1]})" if partial else ""),
                          fmt.num_he(val, 1), chg])
    long_rows.reverse()

    # Year-over-year change, as published.
    yy = pyy.dropna()
    yoy_chart = {"x": [_mon_short(p) for p in yy.index], "y": [round(x, 1) for x in yy.values]}
    yoy_rows = []
    for y, grp in yy.groupby(yy.index.str[:4], sort=True):
        lastp = grp.index[-1]
        mx, mn = grp.idxmax(), grp.idxmin()
        label = y + ("" if lastp.endswith("-12") else f" (עד {fmt.MONTHS_HE[_ym(lastp)[1] - 1]})")
        yoy_rows.append([label, _signed(grp.iloc[-1]),
                         f"{fmt.isolate(_signed(grp[mx]))} ({fmt.MONTHS_HE[_ym(mx)[1] - 1]})",
                         f"{fmt.isolate(_signed(grp[mn]))} ({fmt.MONTHS_HE[_ym(mn)[1] - 1]})"])
    yoy_rows.reverse()

    # Drawdown from the running peak (monthly era).
    dd = v / v.cummax() - 1
    episodes = _episodes(v)
    dd_chart = {"x": [_mon_short(p) for p in dd.index], "y": [round(x * 100, 2) for x in dd.values]}
    ep_rows = []
    for e in reversed(episodes):
        ep_rows.append([_mon(e["peak"]), _mon(e["trough"]), _signed(e["depth"] * 100),
                        _mon(e["recovered"]) if e["recovered"] else "טרם חזר לשיא"])
    peak_p = v[v == v.max()].index[-1]
    dd_now = v.iloc[-1] / v.max() - 1

    # Recent monthly changes.
    newm = _monthly(frames["new"], NEW_CODE)
    new_pct = newm["PERCENT"].map(_num) if not newm.empty else pd.Series(dtype=float)
    rec = pct.dropna().iloc[-RECENT:]
    recent_chart = {
        "x": [_mon_short(p) for p in rec.index],
        "all": [round(x, 1) for x in rec.values],
        "new": [None if pd.isna(new_pct.get(p)) else round(new_pct.get(p), 1) for p in rec.index],
    }
    has_new_recent = any(x is not None for x in recent_chart["new"])
    recent_rows = [[_mon(p), _signed(rec[p]),
                    "–" if pd.isna(new_pct.get(p)) else _signed(new_pct.get(p))] for p in reversed(rec.index)]

    # ── districts ──
    dist = frames["districts"]
    dist = dist[dist["FREQ"].str.strip() == "M"].copy()
    dist["CODE"] = dist["CODE"].astype(str).str.strip()
    dist["TIME_PERIOD"] = dist["TIME_PERIOD"].str.strip()
    dist["v"] = dist["VALUE_CHAINED"].map(_num)
    dist = dist[dist["v"].notna() & dist["TIME_PERIOD"].str.fullmatch(r"\d{4}-\d{2}")]
    dist = dist.sort_values(["CODE", "TIME_PERIOD", "VALUE_CHAINED"], kind="mergesort")
    dist = dist.drop_duplicates(["CODE", "TIME_PERIOD"], keep="last")
    names = {}
    for code, grp in dist.groupby("CODE", sort=True):
        names[code] = DISTRICT_LABELS.get(code) or grp["NAME_HE"].iloc[-1].strip() or code
    wide = dist.pivot(index="TIME_PERIOD", columns="CODE", values="v").sort_index()
    wide = wide[sorted(wide.columns)]
    common = wide.dropna()
    has_dist = len(common) >= 2 and len(wide.columns) >= 2
    dist_view = None
    if has_dist:
        b, e = common.index[0], common.index[-1]
        nat_al = v.reindex(common.index)
        nat_ok = pd.notna(nat_al.get(b)) and pd.notna(nat_al.get(e))
        e12 = _shift(e, -12)
        has_yoy = e12 in common.index
        stats = []
        for code in common.columns:
            s = common[code]
            stats.append({
                "name": names[code], "nat": False,
                "since": s[e] / s[b] - 1,
                "yoy": (s[e] / s[e12] - 1) if has_yoy else None,
                "peak": s[s == s.max()].index[-1], "dd": s[e] / s.max() - 1,
            })
        nat_stat = None
        if nat_ok:
            ns = nat_al.loc[b:e]
            nat_stat = {"name": "כל הארץ", "nat": True, "since": ns[e] / ns[b] - 1,
                        "yoy": (ns[e] / ns[e12] - 1) if has_yoy and pd.notna(ns.get(e12)) else None,
                        "peak": ns[ns == ns.max()].index[-1], "dd": ns[e] / ns.max() - 1}
        lines = [{"name": names[c], "data": [round(x / common[c][b] * 100, 2) for x in common[c].values]}
                 for c in common.columns]
        nat_line = None
        if pd.notna(nat_al.get(b)):
            nat_line = [None if pd.isna(x) else round(x / nat_al[b] * 100, 2) for x in nat_al.values]
        allst = stats + ([nat_stat] if nat_stat else [])
        dist_rows = [[s["name"], fmt.num_he((1 + s["since"]) * 100, 1), _signed(s["since"] * 100),
                      "–" if s["yoy"] is None else _signed(s["yoy"] * 100),
                      f"{fmt.isolate(_signed(s['dd'] * 100))} ({_mon_short(s['peak'])})"]
                     for s in sorted(allst, key=lambda s: (-s["since"], s["name"]))]
        rank = None
        if has_yoy:
            rk = sorted([s for s in allst if s["yoy"] is not None], key=lambda s: (s["yoy"], s["name"]))
            rank = {"names": [s["name"] for s in rk], "y": [round(s["yoy"] * 100, 1) for s in rk],
                    "nat": [s["nat"] for s in rk]}
        # Year x district heatmap: December to December (or to the latest month).
        hm_years, hm_cells, hm_rows = [], [], []
        series_list = [(names[c], common[c]) for c in common.columns]
        if nat_ok:
            series_list.append(("כל הארץ", nat_al))
        hm_names = [n for n, _ in series_list]
        for y in sorted({p[:4] for p in common.index}):
            start = f"{int(y) - 1}-12"
            end = f"{y}-12" if f"{y}-12" in common.index else (e if e[:4] == y else None)
            if start not in common.index or end is None:
                continue
            xi = len(hm_years)
            hm_years.append(y)
            row = [y + ("" if end.endswith("-12") else f" (עד {fmt.MONTHS_HE[_ym(end)[1] - 1]})")]
            for yi, (_, s) in enumerate(series_list):
                if pd.isna(s.get(start)) or pd.isna(s.get(end)):
                    row.append("–")
                    continue
                c = (s[end] / s[start] - 1) * 100
                hm_cells.append([xi, yi, round(c, 1)])
                row.append(_signed(c))
            hm_rows.append(row)
        hm_rows.reverse()
        partial_year = None if e.endswith("-12") else e[:4]
        dist_view = {
            "b": b, "e": e, "e12": e12, "has_yoy": has_yoy, "stats": stats, "nat": nat_stat,
            "chart": {"x": [_mon_short(p) for p in common.index], "series": lines, "nat": nat_line},
            "rows": dist_rows, "rank": rank,
            "heat": {"years": hm_years, "names": hm_names, "cells": hm_cells} if hm_cells else None,
            "heat_rows": hm_rows, "partial_year": partial_year,
        }

    # ── new dwellings vs all ──
    new_view = None
    if not newm.empty:
        nv = newm["v"]
        cm = [p for p in nv.index if p in v.index]
        if len(cm) >= 2:
            b, e = cm[0], cm[-1]
            nyy = newm["PERCENT_YEAR"].map(_num)
            rows = []
            for y in sorted({p[:4] for p in cm}):
                ps = [p for p in cm if p[:4] == y]
                pe = ps[-1]
                a, n = pyy.get(pe), nyy.get(pe)
                if pd.isna(a) and pd.isna(n):
                    continue
                rows.append([y + ("" if pe.endswith("-12") else f" (עד {fmt.MONTHS_HE[_ym(pe)[1] - 1]})"),
                             "–" if pd.isna(n) else _signed(n), "–" if pd.isna(a) else _signed(a)])
            rows.reverse()
            new_view = {
                "b": b, "e": e,
                "new_since": nv[e] / nv[b] - 1, "all_since": v[e] / v[b] - 1,
                "new_yy": None if pd.isna(nyy.get(nv.index[-1])) else nyy.get(nv.index[-1]),
                "new_last": nv.index[-1],
                "all_yy_at": None if pd.isna(pyy.get(nv.index[-1])) else pyy.get(nv.index[-1]),
                "chart": {"x": [_mon_short(p) for p in cm],
                          "new": [round(nv[p] / nv[b] * 100, 2) for p in cm],
                          "all": [round(v[p] / v[b] * 100, 2) for p in cm]},
                "rows": rows,
            }

    # ── KPIs ──
    lv = v.iloc[-1]
    yy_last = pyy.iloc[-1] if pd.notna(pyy.iloc[-1]) else None
    mm_last = pct.iloc[-1] if pd.notna(pct.iloc[-1]) else None

    def tone(p):
        if p is None:
            return "brand"
        if p >= FAST_RISE:
            return "warn"
        return "info" if p < 0 else "brand"

    kpis = {"level": {"value": round(lv, 1), "display": fmt.num_he(lv, 1), "tone": "brand"}}
    labels = {"level_kpi": f"מדד מחירי הדירות, {_mon(last)} (בסיס: {base_he})"}
    if yy_last is not None:
        kpis["yoy"] = {"value": yy_last, "display": _signed(yy_last), "tone": tone(yy_last)}
        labels["yoy_kpi"] = f"שינוי ב-12 חודשים, לעומת {_mon(_shift(last, -12))}"
    if mm_last is not None:
        kpis["mom"] = {"value": mm_last, "display": _signed(mm_last), "tone": tone(mm_last)}
        labels["mom_kpi"] = f"שינוי לעומת החודש הקודם ({_mon(_shift(last, -1))})"
    kpis["peak"] = {"value": round(dd_now * 100, 1), "display": _signed(dd_now * 100),
                    "tone": "info" if dd_now < 0 else "brand"}
    labels["peak_kpi"] = (f"מרחק מהשיא של {_mon(peak_p)}" if dd_now < 0
                          else "המדד בשיא של כל התקופה")
    if dist_view and dist_view["has_yoy"]:
        n_down = sum(1 for s in dist_view["stats"] if s["yoy"] < 0)
        kpis["dist_down"] = {"value": n_down, "display": f"{n_down}",
                             "tone": "info" if n_down > len(dist_view["stats"]) / 2 else "brand"}
        labels["dist_down_kpi"] = (f"מחוזות (מתוך {len(dist_view['stats'])}) שבהם המדד ירד ב-12 החודשים "
                                   f"שעד {_mon(dist_view['e'])}")
    if new_view and new_view["new_yy"] is not None:
        kpis["new_yoy"] = {"value": new_view["new_yy"], "display": _signed(new_view["new_yy"]),
                           "tone": tone(new_view["new_yy"])}
        labels["new_yoy_kpi"] = f"דירות חדשות: שינוי ב-12 חודשים ({_mon(new_view['new_last'])})"

    # ── insights ──
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if yy_last is not None:
        sign = _sign(yy_last)
        streak = 0
        for x in reversed(yy.values):
            if sign != 0 and _sign(x) == sign:
                streak += 1
            else:
                break
        if sign == 0:
            t = f"מדד מחירי הדירות ב{_mon(last)} כמעט זהה לרמתו ב{_mon(_shift(last, -12))} (שינוי של {_abs(yy_last)})."
        else:
            t = (f"מדד מחירי הדירות ב{_mon(last)} {'גבוה' if sign > 0 else 'נמוך'} ב-{_abs(yy_last)} "
                 f"מרמתו ב{_mon(_shift(last, -12))}, לפי השינוי השנתי שפרסמה הלשכה המרכזית לסטטיסטיקה.")
            if streak >= STREAK_MIN and streak < len(yy):
                t += (f" זה החודש ה-{streak} ברציפות שבו המדד "
                      f"{'גבוה' if sign > 0 else 'נמוך'} מרמתו שנה קודם.")
        add("yoy", t)

    if dd_now <= -DD_MIN:
        months = _mdiff(last, peak_p)
        t = (f"המדד ירד ב-{_abs(dd_now * 100)} מאז השיא של {_mon(peak_p)}, "
             f"{months} חודשים קודם לכן.")
        past = [ep for ep in episodes if ep["recovered"] is not None]
        deeper = [ep for ep in past if ep["depth"] <= dd_now]
        if deeper:
            ep = deeper[-1]
            later = [x for x in past if x["peak"] > ep["peak"]]
            if later:
                t += (f" זו הירידה העמוקה ביותר מאז הירידה שהחלה ב{_mon(ep['peak'])} "
                      f"(עד {_abs(ep['depth'] * 100)} מתחת לשיא).")
        elif past:
            t += f" זו הירידה העמוקה ביותר בנתונים החודשיים, שמתחילים ב{_mon(first_m)}."
        add("peak", t)
    elif dd_now == 0:
        add("peak", f"המדד ב{_mon(last)} הוא הגבוה ביותר בכל הנתונים החודשיים, מאז {_mon(first_m)}.")

    years_span = _mdiff(last, first_m) / 12
    if years_span >= 5:
        mult = lv / v.iloc[0]
        cagr = mult ** (1 / years_span) - 1
        dch = pd.Series({p: v[p] / v[_shift(p, -12)] - 1 for p in v.index
                         if p.endswith("-12") and _shift(p, -12) in v.index}, dtype=float)
        t =(f"מאז {_mon(first_m)} עלה המדד פי {mult:.1f}, קצב ממוצע של {_abs(cagr * 100)} בשנה "
             "(במחירים שוטפים, לפני השפעת האינפלציה).")
        if len(dch) >= 3:
            top = dch.sort_values(kind="mergesort").index[-1]
            low = dch.sort_values(kind="mergesort").index[0]
            t += (f" השנה החזקה ביותר הייתה {top[:4]} ({_ss(dch[top] * 100)} מדצמבר לדצמבר), "
                  f"והחלשה ביותר {low[:4]} ({_ss(dch[low] * 100)}).")
        add("long", t)

    if dist_view:
        st = sorted(dist_view["stats"], key=lambda s: (s["since"], s["name"]))
        lo, hi = st[0], st[-1]
        if hi["since"] - lo["since"] >= 0.05:
            t = (f"בין {_mon(dist_view['b'])} ל{_mon(dist_view['e'])} השינוי הגדול ביותר במחירים היה במחוז {hi['name']} "
                 f"({_ss(hi['since'] * 100)}) והקטן ביותר במחוז {lo['name']} ({_ss(lo['since'] * 100)})")
            if dist_view["nat"]:
                t += f" (בכל הארץ: {_ss(dist_view['nat']['since'] * 100)})"
            add("districts_since", t + ".")
        if dist_view["has_yoy"]:
            ys = sorted(dist_view["stats"], key=lambda s: (s["yoy"], s["name"]))
            down = [s for s in ys if s["yoy"] < 0]
            n = len(ys)
            if len(down) == n:
                t = (f"ב-12 החודשים שעד {_mon(dist_view['e'])} ירד המדד בכל {n} המחוזות. "
                     f"הירידה החדה ביותר במחוז {ys[0]['name']} ({_ss(ys[0]['yoy'] * 100)}), "
                     f"והמתונה ביותר במחוז {ys[-1]['name']} ({_ss(ys[-1]['yoy'] * 100)}).")
            elif not down:
                t = (f"ב-12 החודשים שעד {_mon(dist_view['e'])} עלה המדד בכל {n} המחוזות. "
                     f"העלייה החדה ביותר במחוז {ys[-1]['name']} ({_ss(ys[-1]['yoy'] * 100)}).")
            else:
                t = (f"ב-12 החודשים שעד {_mon(dist_view['e'])} ירד המדד ב-{len(down)} מתוך {n} המחוזות, "
                     f"בחדות הרבה ביותר במחוז {ys[0]['name']} ({_ss(ys[0]['yoy'] * 100)}), "
                     f"והשינוי הגבוה ביותר במחוז {ys[-1]['name']} ({_ss(ys[-1]['yoy'] * 100)}).")
            add("districts_yoy", t + " השינוי במחוזות מחושב מרמות המדד.")

    if new_view:
        ns, als = new_view["new_since"], new_view["all_since"]
        gap = (ns - als) * 100
        if abs(gap) >= 1:
            t = (f"בין {_mon(new_view['b'])} ל{_mon(new_view['e'])} {_verb(ns, 'עלו', 'ירדו')} מחירי הדירות החדשות ב-{_abs(ns * 100)}, "
                 f"לעומת {_ss(als * 100)} בכלל הדירות.")
        else:
            t = (f"בין {_mon(new_view['b'])} ל{_mon(new_view['e'])} השתנו מחירי הדירות החדשות ({_ss(ns * 100)}) "
                 f"בקצב דומה לכלל הדירות ({_ss(als * 100)}).")
        if new_view["new_yy"] is not None:
            t += f" ב-12 החודשים שעד {_mon(new_view['new_last'])}: {_ss(new_view['new_yy'])} בדירות החדשות"
            t += f" לעומת {_ss(new_view['all_yy_at'])} בכלל הדירות." if new_view["all_yy_at"] is not None else "."
        add("new_vs_all", t)

    last6 = pct.dropna().iloc[-6:]
    if len(last6) == 6 and len(v) >= 7:
        downs = int((last6 < 0).sum())
        ups = int((last6 > 0).sum())
        c6 = v.iloc[-1] / v.iloc[-7] - 1
        moves = [f"ירד ב-{downs} חודשים" if downs else "",
                 (f"עלה ב-{ups}" if downs else f"עלה ב-{ups} חודשים") if ups else ""]
        moves = " ו".join(x for x in moves if x) or "לא השתנה באף חודש"
        t = (f"בששת החודשים האחרונים (עד {_mon(last)}) המדד {moves}; "
             f"בסך הכול {_verb(c6) if abs(c6) * 100 > FLAT else 'כמעט לא השתנה'}"
             + (f" ב-{_abs(c6 * 100)}." if abs(c6) * 100 > FLAT else "."))
        add("momentum", t)

    # ── labels / text ──
    yoy_phrase = ""
    if yy_last is not None:
        yoy_phrase = (f", שינוי של {_ss(yy_last)} לעומת {_mon(_shift(last, -12))}")
    lede = (f"מדד מחירי הדירות של הלשכה המרכזית לסטטיסטיקה עמד ב{_mon(last)} על {fmt.num_he(lv, 1)} נקודות "
            f"(בסיס: {base_he}){yoy_phrase}. הדף מציג את המדד הארצי מאז {long_first}"
            + (f", את מדדי המחירים לפי מחוז מאז {_mon(dist_view['b'])}" if dist_view else "")
            + (f" ואת מדד מחירי הדירות החדשות מאז {_mon(new_view['b'])}" if new_view else "")
            + ". המדד מחושב מעסקאות של חודשיים סמוכים, ולכן כל נתון חודשי חופף בחלקו לנתון שלפניו.")
    summary = (f"מדד מחירי הדירות בישראל לפי הלשכה המרכזית לסטטיסטיקה: {fmt.num_he(lv, 1)} נקודות ב{_mon(last)}"
               + (f" ({_signed(yy_last)} בשנה)" if yy_last is not None else "")
               + ", מגמה ארוכת טווח, מדדים לפי מחוז ומדד הדירות החדשות.")
    seo_desc = (f"מדד מחירי הדירות של הלמ\"ס עד {_mon(last)}"
                + (f": {_signed(yy_last)} בשנה האחרונה" if yy_last is not None else "")
                + f". מגמה מאז {long_first}, מחירי הדירות לפי מחוז ומחירי דירות חדשות.")

    labels.update({
        "lede": lede,
        "long_note": (f"רמת המדד בכל תקופה, על בסיס אחד ({base_he})."
                      + (f" עד {q['TIME_PERIOD'].iloc[-1][:4]} המדד רבעוני, ומ-{first_m[:4]} חודשי."
                         if has_q else "")
                      + " המחירים שוטפים (לא מנוכי אינפלציה). אפשר לגרור את פס הזמן."),
        "long_aria": (f"גרף קו: מדד מחירי הדירות מ-{long_first} עד {_mon(last)}, "
                      f"בסיס {base_he}; ברמה האחרונה {fmt.num_he(lv, 1)}."),
        "long_caption": "רמת המדד בסוף כל שנה והשינוי לעומת סוף השנה הקודמת",
        "yoy_note": ("השינוי באחוזים לעומת אותו חודש בשנה הקודמת, כפי שפרסמה הלשכה המרכזית לסטטיסטיקה. "
                     "עמודה מעל הקו: עלייה; מתחת לקו: ירידה."),
        "yoy_aria": (f"גרף עמודות: שינוי שנתי במדד מחירי הדירות {_from(_mon(yy.index[0]))} עד {_mon(yy.index[-1])}"
                     + (f"; בחודש האחרון {_signed(yy_last)}." if yy_last is not None else ".")),
        "yoy_caption": "השינוי השנתי בסוף כל שנה, והגבוה והנמוך בה",
        "dd_note": (f"בכמה אחוזים המדד נמוך מהשיא הגבוה ביותר שהיה עד אותו חודש (0 = שיא חדש). "
                    f"בטבלה: כל ירידה של {int(DD_MIN * 100)}% ויותר מתחת לשיא מאז {_mon(first_m)}."),
        "dd_aria": (f"גרף שטח: המרחק של מדד מחירי הדירות מהשיא הקודם, {_from(_mon(first_m))} עד {_mon(last)}; "
                    f"כעת {_signed(dd_now * 100)}."),
        "dd_caption": "תקופות ירידה במדד מחירי הדירות: שיא, שפל, עומק וחזרה לשיא",
        "recent_note": (f"השינוי באחוזים לעומת החודש הקודם, כפי שפורסם, ב-{len(rec)} החודשים האחרונים"
                        + (", בכלל הדירות ובדירות החדשות." if has_new_recent else ".")),
        "recent_aria": (f"גרף עמודות: שינוי חודשי במדד מחירי הדירות, {_mon(rec.index[0])} עד {_mon(rec.index[-1])}."),
        "recent_caption": "שינוי חודשי במדד, כלל הדירות ודירות חדשות",
    })
    if dist_view:
        db = _mon(dist_view["b"])
        labels.update({
            "dist_note": (f"מדד המחירים בכל מחוז ({db} = 100), כדי שאפשר יהיה להשוות את השינוי מאז. "
                          f"הקו המקווקו: כל הארץ."),
            "dist_aria": (f"גרף קו: מדד מחירי הדירות לפי מחוז {_from(db)} עד {_mon(dist_view['e'])}, "
                          f"{db} = 100."),
            "dist_caption": (f"מדד לפי מחוז ({db} = 100), השינוי מאז, ב-12 החודשים האחרונים ומהשיא"),
            "dist_col_level": f"מדד ({db} = 100)",
            "dist_col_since": f"שינוי מאז {db}",
            "dist_col_yoy": "שינוי ב-12 חודשים",
            "rank_head": "מחירי הדירות ב-12 החודשים האחרונים, לפי מחוז",
            "rank_note": (f"השינוי במדד ב-12 החודשים שעד {_mon(dist_view['e'])} בכל מחוז ובכל הארץ, מחושב מרמות המדד "
                          "(הלשכה לא מפרסמת שינוי שנתי למדדי המחוזות)."),
            "rank_aria": (f"תרשים עמודות: שינוי שנתי במדד מחירי הדירות לפי מחוז, עד {_mon(dist_view['e'])}."),
            "rank_caption": f"שינוי ב-12 חודשים לפי מחוז, עד {_mon(dist_view['e'])}",
            "heat_note": ("השינוי במדד מדצמבר לדצמבר בכל מחוז ובכל הארץ (כחול: ירידה, אדום: עלייה)."
                          + (f" {dist_view['partial_year']}: מדצמבר הקודם עד {_mon(dist_view['e'])}."
                             if dist_view["partial_year"] and dist_view["heat"]
                             and dist_view["partial_year"] in dist_view["heat"]["years"] else "")),
            "heat_aria": "מפת חום: השינוי השנתי במדד מחירי הדירות לפי מחוז ושנה.",
            "heat_caption": "שינוי שנתי במדד לפי מחוז ושנה (מדצמבר לדצמבר)",
        })
    if new_view:
        nb = _mon(new_view["b"])
        labels.update({
            "new_note": (f"מדד מחירי הדירות החדשות מול מדד כלל הדירות ({nb} = 100). "
                         "בטבלה: השינוי השנתי בסוף כל שנה, כפי שפורסם."),
            "new_aria": (f"גרף קו: מחירי דירות חדשות מול כלל הדירות {_from(nb)} עד {_mon(new_view['e'])}, "
                         f"{nb} = 100."),
            "new_caption": "שינוי שנתי בסוף כל שנה: דירות חדשות וכלל הדירות",
        })

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{long_first}/{last[:4]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד מחירי הדירות: מגמה, שינוי שנתי ומחירים לפי מחוז",
                "description": seo_desc,
                "name": "מדד מחירי הדירות",
                "alternate_names": ["מדד מחירי דירות", "מחירי הדירות בישראל",
                                    "מדד מחירי דירות לפי אזור", "מדד מחירי דירות חדשות"],
            },
        },
        "kpis": kpis,
        "charts": {
            "long": long_pts,
            "yoy": yoy_chart,
            "dd": dd_chart,
            "recent": recent_chart,
            "dist": dist_view["chart"] if dist_view else None,
            "rank": dist_view["rank"] if dist_view else None,
            "heat": dist_view["heat"] if dist_view else None,
            "new": new_view["chart"] if new_view else None,
        },
        "tables": {
            "long": long_rows,
            "yoy": yoy_rows,
            "episodes": ep_rows,
            "recent": recent_rows,
            "dist": dist_view["rows"] if dist_view else [],
            "rank": ([[n, _signed(y)] for n, y in zip(reversed(dist_view["rank"]["names"]),
                                                      reversed(dist_view["rank"]["y"]))]
                     if dist_view and dist_view["rank"] else []),
            "heat_cols": dist_view["heat"]["names"] if dist_view and dist_view["heat"] else [],
            "heat": dist_view["heat_rows"] if dist_view and dist_view["heat"] else [],
            "new": new_view["rows"] if new_view else [],
        },
        "flags": {
            "dist": bool(dist_view),
            "rank": bool(dist_view and dist_view["rank"]),
            "heat": bool(dist_view and dist_view["heat"]),
            "new": bool(new_view),
            "new_recent": has_new_recent,
            "episodes": bool(ep_rows),
        },
        "insights": insights,
        "labels": labels,
    }
