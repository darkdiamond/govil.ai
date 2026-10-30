"""Bus-network licensing (רישוי מערך האוטובוסים), Ministry of Transport.

Each row is one licensed route variant of one line (origin -> destination) on
one calendar day, with the number of trips licensed for it. The dataset adds a
file per year; the recipe reads the newest one (`pick: "latest"`), so the page
always describes the current year of the licensed network.

Reference period: "a regular weekday" = Sunday-Thursday dates within the last
28 days of data whose network total is at least 85% of that window's median
weekday (drops holidays and one-off disruptions). Per-line, per-operator,
per-cluster and per-city figures are averages over those days.
"""

from __future__ import annotations

import pandas as pd

MONTHS_HE = {
    1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל", 5: "מאי", 6: "יוני",
    7: "יולי", 8: "אוגוסט", 9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר", 12: "דצמבר",
}
# pandas dayofweek: Monday=0 ... Sunday=6. Israeli week order Sunday..Saturday.
DOW_ORDER = [6, 0, 1, 2, 3, 4, 5]
DOW_HE = {6: "ראשון", 0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי", 4: "שישי", 5: "שבת"}
WEEKDAYS = {6, 0, 1, 2, 3}
FRI, SAT = 4, 5

WINDOW_DAYS = 28
REGULAR_SHARE = 0.85      # weekday counts as "regular" at >= 85% of the window median
PARTIAL_LAST_SHARE = 0.5  # last date below 50% of its weekday's recent median = partial upload
DISRUPT_SHARE = 0.75      # weekday below 75% of the year's weekday median = disrupted
TOP_OPERATORS = 12
MIX_OPERATORS = 8
TOP_CLUSTERS = 15
TOP_CITIES = 15
TOP_SAT_CITIES = 10
TOP_LINES = 15
OTHER = "אחר"
BUCKETS = [(1, 4), (5, 9), (10, 19), (20, 49), (50, 99), (100, None)]


def _int(v) -> str:
    return f"{int(round(v)):,}"


def _pct(v: float, digits: int = 1) -> str:
    return f"{v * 100:.{digits}f}%"


def _signed_pct(v: float) -> str:
    s = f"{abs(v) * 100:.1f}%"
    if round(abs(v) * 100, 1) == 0:
        return s
    return ("+" if v > 0 else "−") + s


def _date(d: pd.Timestamp) -> str:
    return f"{d.day}.{d.month}.{d.year}"


def _kpi(value, display, tone="brand"):
    return {"value": value, "display": display, "tone": tone}


def _ref_days(daily: pd.Series, end: pd.Timestamp, start: pd.Timestamp | None = None):
    """Regular weekdays in a 28-day window. Returns (days, kind) where kind is
    'regular' (filtered weekdays), 'weekday' (all weekdays) or 'all'."""
    if start is None:
        lo, hi = end - pd.Timedelta(days=WINDOW_DAYS - 1), end
    else:
        lo, hi = start, start + pd.Timedelta(days=WINDOW_DAYS - 1)
    win = daily[(daily.index >= lo) & (daily.index <= hi)]
    wk = win[[d.dayofweek in WEEKDAYS for d in win.index]]
    if len(wk) == 0:
        return list(win.index), "all"
    med = float(wk.median())
    reg = wk[wk >= REGULAR_SHARE * med]
    if len(reg) == 0:
        return list(wk.index), "weekday"
    return list(reg.index), "regular"


def compute(frames):
    raw = frames["main"]
    df = pd.DataFrame({
        "op": raw["operator_nm"].astype(str).str.strip(),
        "cluster": raw["cluster_nm"].astype(str).str.strip(),
        "num": raw["operator_line_id"].astype(str).str.strip(),
        "line": raw["office_line_id"].astype(str).str.strip(),
        "kind": raw["line_type_nm"].astype(str).str.strip(),
        "vtype": raw["VehicleType_nm"].astype(str).str.strip(),
        "vsize": raw["VehicleSize_nm"].astype(str).str.strip(),
        "o_city": raw["origin_yishuv_nm"].astype(str).str.strip(),
        "d_city": raw["destination_yishuv_nm"].astype(str).str.strip(),
        "t": pd.to_numeric(raw["trips_count"].astype(str).str.replace(",", "", regex=False),
                           errors="coerce"),
        "d": pd.to_datetime(raw["rishui_date"].astype(str).str.slice(0, 10),
                            format="%Y-%m-%d", errors="coerce"),
    })
    df = df[df["t"].notna() & (df["t"] > 0) & df["d"].notna() & (df["line"] != "")]
    if df.empty:
        raise ValueError("no usable rows")
    df["t"] = df["t"].astype("int64")
    for c in ("op", "cluster", "kind", "vtype", "vsize", "o_city", "d_city"):
        df.loc[df[c] == "", c] = "לא צוין"

    year = int(df["d"].max().year)
    dropped_other_years = int((df["d"].dt.year != year).sum())
    df = df[df["d"].dt.year == year]

    daily = df.groupby("d")["t"].sum().sort_index()

    # Partial last date: the file is uploaded mid-day, so its newest date can
    # hold a fraction of a day's licensing. Compare with the same weekday.
    partial_last = None
    last = daily.index[-1]
    prev_same = daily[[(d.dayofweek == last.dayofweek) and d < last for d in daily.index]].tail(4)
    if len(prev_same) >= 2 and daily.iloc[-1] < PARTIAL_LAST_SHARE * float(prev_same.median()):
        partial_last = last
        df = df[df["d"] != last]
        daily = daily.iloc[:-1]
    if daily.empty:
        raise ValueError("no complete dates")

    first_d, last_d = daily.index[0], daily.index[-1]
    dow = pd.Series([d.dayofweek for d in daily.index], index=daily.index)
    df["dow"] = df["d"].dt.dayofweek
    df["m"] = df["d"].dt.month

    ref, ref_kind = _ref_days(daily, last_d)
    n_ref = len(ref)
    ref_set = set(ref)
    rdf = df[df["d"].isin(ref_set)]
    ref_total = float(daily.loc[ref].sum()) / n_ref
    ref_lo, ref_hi = min(ref), max(ref)
    ref_phrase = {
        "regular": "ביום חול רגיל",
        "weekday": "ביום חול",
        "all": "ביום",
    }[ref_kind]
    ref_note = {
        "regular": f"ממוצע לימי חול רגילים (ראשון עד חמישי, ללא חגים וימים חריגים) בין {_date(ref_lo)} ל-{_date(ref_hi)}, {n_ref} ימים",
        "weekday": f"ממוצע לימי ראשון עד חמישי בין {_date(ref_lo)} ל-{_date(ref_hi)}, {n_ref} ימים",
        "all": f"ממוצע יומי בין {_date(ref_lo)} ל-{_date(ref_hi)}, {n_ref} ימים",
    }[ref_kind]

    # ── per-entity averages over the reference days ─────────────────────
    def per_ref(keys):
        return (rdf.groupby(keys)["t"].sum() / n_ref)

    line_ref = per_ref("line")
    n_lines = int(line_ref.size)
    n_ops = int(rdf["op"].nunique())
    n_clusters = int(rdf["cluster"].nunique())

    # operators
    op_ref = per_ref("op").reset_index().rename(columns={"t": "v"})
    op_lines = rdf.groupby("op")["line"].nunique()
    op_ref["lines"] = op_ref["op"].map(op_lines).astype(int)
    op_ref = op_ref.sort_values(["v", "op"], ascending=[False, True]).reset_index(drop=True)
    tot_ref = float(op_ref["v"].sum())
    top_ops = op_ref.head(TOP_OPERATORS)
    rest_ops = op_ref.iloc[TOP_OPERATORS:]
    ops_names = top_ops["op"].tolist()
    ops_vals = [round(v) for v in top_ops["v"]]
    ops_lines = top_ops["lines"].tolist()
    if len(rest_ops):
        ops_names.append(f"{OTHER} ({len(rest_ops)} מפעילים)")
        ops_vals.append(round(float(rest_ops["v"].sum())))
        ops_lines.append(int(rdf[rdf["op"].isin(set(rest_ops["op"]))]["line"].nunique()))
    ops_share = [round(v / tot_ref * 100, 1) for v in ops_vals]

    # operator mix by month (share of the month's trips)
    op_year = df.groupby("op")["t"].sum().reset_index()
    op_year = op_year.sort_values(["t", "op"], ascending=[False, True])
    mix_ops = op_year["op"].head(MIX_OPERATORS).tolist()
    months = sorted(df["m"].unique().tolist())
    days_per_month = daily.groupby(daily.index.month).size()
    month_partial = {}
    for m in months:
        dim = pd.Period(f"{year}-{m:02d}").days_in_month
        has = int(days_per_month.get(m, 0))
        # the first/last month of the file may be cut by the data range
        month_partial[m] = has < dim
    month_labels = [MONTHS_HE[m] + (" (חלקי)" if month_partial[m] else "") for m in months]
    om = df.groupby(["m", "op"])["t"].sum()
    m_tot = df.groupby("m")["t"].sum()
    mix_series = []
    for op in mix_ops:
        mix_series.append({
            "name": op,
            "data": [round(float(om.get((m, op), 0)) / float(m_tot[m]) * 100, 1) for m in months],
        })
    other_mix = [round(100 - sum(s["data"][i] for s in mix_series), 1) for i in range(len(months))]
    if len(op_year) > MIX_OPERATORS:
        mix_series.append({"name": OTHER, "data": [max(0.0, v) for v in other_mix]})

    # clusters
    cl_ref = per_ref("cluster").reset_index().rename(columns={"t": "v"})
    cl_op = rdf.groupby(["cluster", "op"])["t"].sum().reset_index()
    cl_op = cl_op.sort_values(["cluster", "t", "op"], ascending=[True, False, True])
    cl_dom = cl_op.groupby("cluster").head(1).set_index("cluster")["op"]
    cl_lines = rdf.groupby("cluster")["line"].nunique()
    cl_ref = cl_ref.sort_values(["v", "cluster"], ascending=[False, True]).head(TOP_CLUSTERS)
    clusters = {
        "names": cl_ref["cluster"].tolist(),
        "values": [round(v) for v in cl_ref["v"]],
        "ops": [cl_dom[c] for c in cl_ref["cluster"]],
        "lines": [int(cl_lines[c]) for c in cl_ref["cluster"]],
    }

    # line types
    ty = per_ref("kind").reset_index().rename(columns={"t": "v"})
    ty_lines = rdf.groupby("kind")["line"].nunique()
    ty = ty.sort_values(["v", "kind"], ascending=[False, True])
    types = {
        "names": ty["kind"].tolist(),
        "values": [round(v) for v in ty["v"]],
        "lines": [int(ty_lines[k]) for k in ty["kind"]],
        "share": [round(v / tot_ref * 100, 1) for v in ty["v"]],
    }

    # vehicles: size and type (armoured intercity buses)
    def split(col):
        v = per_ref(col).reset_index().rename(columns={"t": "v"})
        vl = rdf.groupby(col)["line"].nunique()
        v = v.sort_values(["v", col], ascending=[False, True])
        return {
            "names": v[col].tolist(),
            "values": [round(x) for x in v["v"]],
            "lines": [int(vl[k]) for k in v[col]],
            "share": [round(x / tot_ref * 100, 1) for x in v["v"]],
        }

    vsizes = split("vsize")
    vtypes = split("vtype")

    # origin cities
    ct = per_ref("o_city").reset_index().rename(columns={"t": "v"})
    ct_lines = rdf.groupby("o_city")["line"].nunique()
    ct = ct.sort_values(["v", "o_city"], ascending=[False, True])
    n_cities = int(ct.shape[0])
    ct_top = ct.head(TOP_CITIES)
    cities = {
        "names": ct_top["o_city"].tolist(),
        "values": [round(v) for v in ct_top["v"]],
        "lines": [int(ct_lines[c]) for c in ct_top["o_city"]],
    }

    # Saturday departures by origin city (all Saturdays of the year)
    sat_days = [d for d in daily.index if d.dayofweek == SAT]
    sat_cities = None
    if sat_days:
        sdf = df[df["dow"] == SAT]
        sc = (sdf.groupby("o_city")["t"].sum() / len(sat_days)).reset_index()
        sc = sc.sort_values(["t", "o_city"], ascending=[False, True])
        sat_total = float(sc["t"].sum())
        if sat_total > 0:
            sct = sc.head(TOP_SAT_CITIES)
            sat_cities = {
                "names": sct["o_city"].tolist(),
                "values": [round(v) for v in sct["t"]],
                "share": [round(v / sat_total * 100, 1) for v in sct["t"]],
                "n_days": len(sat_days),
                "n_cities": int((sc["t"] > 0).sum()),
                "of_cities": int(df["o_city"].nunique()),
                "total": round(sat_total),
            }

    # busiest lines
    lr = line_ref.reset_index().rename(columns={"t": "v"})
    lr = lr.sort_values(["v", "line"], ascending=[False, True]).head(TOP_LINES)
    top_set = set(lr["line"])
    sub = rdf[rdf["line"].isin(top_set)]
    var = sub.groupby(["line", "num", "op", "o_city", "d_city", "kind"])["t"].sum().reset_index()
    var = var.sort_values(["line", "t", "num", "op", "o_city", "d_city", "kind"],
                          ascending=[True, False, True, True, True, True, True])
    main_var = var.groupby("line").head(1).set_index("line")
    top_lines = []
    for _, r in lr.iterrows():
        mv = main_var.loc[r["line"]]
        route = mv["o_city"] if mv["o_city"] == mv["d_city"] else f"{mv['o_city']} - {mv['d_city']}"
        top_lines.append({
            "label": f"קו {mv['num']} ({mv['op']})",
            "num": mv["num"], "op": mv["op"], "route": route, "kind": mv["kind"],
            "makat": r["line"], "value": round(float(r["v"])),
        })

    # distribution of lines by trips per reference day
    dist_labels, dist_vals = [], []
    for lo, hi in BUCKETS:
        if hi is None:
            mask = line_ref >= lo
            dist_labels.append(f"{lo}+")
        else:
            mask = (line_ref >= lo) & (line_ref < hi + 1)
            dist_labels.append(f"{lo}-{hi}")
        dist_vals.append(int(mask.sum()))
    below1 = int((line_ref < 1).sum())
    if below1:
        dist_labels.insert(0, "פחות מ-1")
        dist_vals.insert(0, below1)
    median_line = float(line_ref.median())

    # day of week (median over the whole year)
    dow_med = {k: float(daily[dow == k].median()) for k in DOW_ORDER if (dow == k).any()}
    dow_chart = {
        "names": [DOW_HE[k] for k in DOW_ORDER if k in dow_med],
        "values": [round(dow_med[k]) for k in DOW_ORDER if k in dow_med],
        "days": [int((dow == k).sum()) for k in DOW_ORDER if k in dow_med],
    }

    # monthly: median weekday / Friday / Saturday, active lines
    monthly = {"labels": month_labels, "weekday": [], "fri": [], "sat": [], "lines": []}
    m_lines = df.groupby("m")["line"].nunique()
    for m in months:
        md = daily[daily.index.month == m]
        mdw = dow[md.index]
        def med(sel):
            s = md[sel.values]
            return round(float(s.median())) if len(s) else None
        monthly["weekday"].append(med(mdw.isin(WEEKDAYS)))
        monthly["fri"].append(med(mdw == FRI))
        monthly["sat"].append(med(mdw == SAT))
        monthly["lines"].append(int(m_lines[m]))

    # daily chart
    daily_chart = {
        "x": [d.strftime("%Y-%m-%d") for d in daily.index],
        "y": [int(v) for v in daily.values],
    }

    # ── KPIs ────────────────────────────────────────────────────────────
    kpis = {
        "trips": _kpi(round(ref_total), _int(ref_total)),
        "lines": _kpi(n_lines, f"{n_lines:,}"),
        "operators": _kpi(n_ops, f"{n_ops:,}"),
        "clusters": _kpi(n_clusters, f"{n_clusters:,}"),
        "year_total": _kpi(int(daily.sum()), _int(daily.sum())),
    }

    # change since the start of the year (needs two non-overlapping windows)
    change = None
    if (last_d - first_d).days >= 2 * WINDOW_DAYS:
        base, base_kind = _ref_days(daily, last_d, start=first_d)
        if base_kind == ref_kind:
            base_total = float(daily.loc[base].sum()) / len(base)
            if base_total > 0:
                ch = ref_total / base_total - 1
                tone = "ok" if ch >= 0.02 else ("danger" if ch <= -0.05 else ("warn" if ch <= -0.02 else "brand"))
                kpis["change"] = _kpi(round(ch * 100, 1), _signed_pct(ch), tone)
                change = {"ch": ch, "base_total": base_total, "base_lo": min(base), "base_hi": max(base)}

    sat_ratio = None
    if SAT in dow_med and dow_med.get(6) is not None:
        wk_meds = [dow_med[k] for k in WEEKDAYS if k in dow_med]
        wk_med = sorted(wk_meds)[len(wk_meds) // 2]
        if wk_med > 0:
            sat_ratio = dow_med[SAT] / wk_med
            kpis["sat_ratio"] = _kpi(round(sat_ratio * 100, 1), _pct(sat_ratio), "info")

    # ── insights ────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_leader():
        if op_ref.empty:
            return None
        lead, share = op_ref.iloc[0], float(op_ref.iloc[0]["v"]) / tot_ref
        if share < 0.1 or (len(op_ref) > 1 and float(op_ref.iloc[1]["v"]) == float(lead["v"])):
            return None
        txt = (f"{lead['op']} הוא המפעיל הגדול ברישוי: {_int(lead['v'])} נסיעות {ref_phrase}, "
               f"{_pct(share)} מכלל הנסיעות, ב-{int(lead['lines']):,} קווים.")
        if len(op_ref) >= 4:
            top3 = op_ref.head(3)
            s3 = float(top3["v"].sum()) / tot_ref
            txt += (f" שלושת המפעילים הגדולים ({top3.iloc[0]['op']}, {top3.iloc[1]['op']} ו{_vav(top3.iloc[2]['op'])}) "
                    f"מחזיקים יחד {_pct(s3)} מהנסיעות, מתוך {len(op_ref)} מפעילים.")
        return txt

    def ins_weekend():
        if FRI not in dow_med or SAT not in dow_med or sat_ratio is None:
            return None
        wk_meds = [dow_med[k] for k in WEEKDAYS if k in dow_med]
        wk_med = sorted(wk_meds)[len(wk_meds) // 2]
        fr = dow_med[FRI] / wk_med
        return (f"ביום שישי מורשות בחציון {_int(dow_med[FRI])} נסיעות ({_pct(fr, 0)} מיום חול), "
                f"ובשבת {_int(dow_med[SAT])} נסיעות בלבד ({_pct(sat_ratio, 0)} מיום חול).")

    def ins_disruption():
        wk = daily[dow.isin(WEEKDAYS).values]
        if len(wk) < 20:
            return None
        med = float(wk.median())
        low = (wk < DISRUPT_SHARE * med).tolist()
        best, cur_start, cur_len = None, None, 0
        for i, flag in enumerate(low):
            if flag:
                if cur_len == 0:
                    cur_start = i
                cur_len += 1
                if best is None or cur_len > best[1]:
                    best = (cur_start, cur_len)
            else:
                cur_len = 0
        if best is None or best[1] < 3:
            return None
        run = wk.iloc[best[0]: best[0] + best[1]]
        avg = float(run.mean())
        return (f"בין {_date(run.index[0])} ל-{_date(run.index[-1])} נרשמה ירידה חדה ברישוי: "
                f"{best[1]} ימי חול רצופים מתחת ל-{_pct(DISRUPT_SHARE, 0)} מהחציון השנתי, "
                f"בממוצע {_int(avg)} נסיעות ביום לעומת חציון של {_int(med)} ({_pct(avg / med, 0)}).")

    def ins_lines_month():
        full = [i for i, m in enumerate(months) if not month_partial[m]]
        if len(full) < 3:
            return None
        vals = [monthly["lines"][i] for i in full]
        hi_i = full[max(range(len(full)), key=lambda j: (vals[j], -j))]
        lo_i = full[min(range(len(full)), key=lambda j: (vals[j], j))]
        hi_v, lo_v = monthly["lines"][hi_i], monthly["lines"][lo_i]
        if hi_v == 0 or (hi_v - lo_v) / hi_v < 0.05:
            return None
        return (f"מספר הקווים הפעילים משתנה במהלך השנה: {hi_v:,} קווים ב{MONTHS_HE[months[hi_i]]} "
                f"לעומת {lo_v:,} ב{MONTHS_HE[months[lo_i]]}, {hi_v - lo_v:,} קווים פחות "
                f"({_pct((hi_v - lo_v) / hi_v)}).")

    def ins_change():
        if change is None:
            return None
        ch = change["ch"]
        if abs(ch) < 0.02:
            word = "נותר כמעט ללא שינוי"
        elif ch > 0:
            word = f"עלה ב-{_pct(abs(ch))}"
        else:
            word = f"ירד ב-{_pct(abs(ch))}"
        return (f"היקף הרישוי {ref_phrase} {word}: מ-{_int(change['base_total'])} נסיעות "
                f"בתחילת השנה ({_date(change['base_lo'])} עד {_date(change['base_hi'])}) "
                f"ל-{_int(ref_total)} בתקופה האחרונה.")

    def ins_sat_city():
        if not sat_cities:
            return None
        s0 = sat_cities["share"][0] / 100
        if s0 < 0.2:
            return None
        return (f"{_pct(s0, 0)} מהנסיעות בשבת יוצאות מ{sat_cities['names'][0]} "
                f"({_int(sat_cities['values'][0])} נסיעות בשבת ממוצעת), "
                f"בסך הכול יוצאות נסיעות בשבת מ-{sat_cities['n_cities']:,} מתוך {sat_cities['of_cities']:,} יישובי המוצא במאגר.")

    def ins_busiest():
        if not top_lines:
            return None
        b = top_lines[0]
        if len(top_lines) > 1 and top_lines[1]["value"] == b["value"]:
            return None
        return (f"הקו העמוס ביותר ברישוי הוא {b['label']}, {b['route']}, עם {b['value']:,} נסיעות {ref_phrase}. "
                f"קו חציוני מורשה ל-{median_line:.1f} נסיעות {ref_phrase}.")

    add("leader", ins_leader())
    add("change", ins_change())
    add("disruption", ins_disruption())
    add("weekend", ins_weekend())
    add("lines_month", ins_lines_month())
    def ins_vehicles():
        named = [(n, v, sh) for n, v, sh in zip(vsizes["names"], vsizes["values"], vsizes["share"])
                 if n != "לא מוגדר"]
        if len(named) < 2 or vsizes["share"][0] <= 50 or vsizes["names"][0] == "לא מוגדר":
            return None
        lead = vsizes["names"][0]
        rest = [x for x in named if x[0] != lead][:2]
        parts = [f"{n} ({sh:.1f}%)" for n, _, sh in rest]
        return (f"רוב הנסיעות {ref_phrase} מורשות ל{lead} ({vsizes['share'][0]:.1f}%). "
                f"אחריו: " + " ו".join(parts[:1] + [_vav(x) for x in parts[1:]]) + ".")

    def ins_armoured():
        arm = [(n, v, sh) for n, v, sh in zip(vtypes["names"], vtypes["values"], vtypes["share"])
               if "ממוגן" in n]
        if not arm:
            return None
        tot_v = sum(v for _, v, _ in arm)
        tot_s = sum(sh for _, _, sh in arm)
        lines_n = int(rdf[rdf["vtype"].str.contains("ממוגן", regex=False)]["line"].nunique())
        if tot_v <= 0:
            return None
        detail = ", ".join(f"{n}: {v:,}" for n, v, _ in arm)
        return (f"{tot_v:,} נסיעות {ref_phrase} ({tot_s:.1f}%) מורשות לאוטובוס ממוגן, "
                f"ב-{lines_n:,} קווים ({detail}).")

    add("vehicles", ins_vehicles())
    add("armoured", ins_armoured())
    add("sat_city", ins_sat_city())
    add("busiest", ins_busiest())

    # ── labels ──────────────────────────────────────────────────────────
    peak_i = max(range(len(daily_chart["y"])), key=lambda i: (daily_chart["y"][i], -i))
    labels = {
        "year": str(year),
        "ref_note": ref_note,
        "trips_kpi": f"נסיעות מורשות {ref_phrase} ({year})",
        "lines_kpi": "קווים פעילים בתקופה האחרונה",
        "ops_kpi": "מפעילים",
        "clusters_kpi": "אשכולות",
        "year_total_kpi": f"סך נסיעות מורשות ב-{year}, עד {_date(last_d)}",
        "change_kpi": f"שינוי {ref_phrase} מתחילת השנה",
        "sat_kpi": "נסיעות בשבת כאחוז מיום חול (חציון)",
        "lede": (f"המאגר מפרט, לכל קו אוטובוס ולכל יום, כמה נסיעות אישר משרד התחבורה ברישוי הקו. "
                 f"הדף מציג את קובץ {year}, מ-{_date(first_d)} עד {_date(last_d)}: "
                 f"{n_lines:,} קווים של {n_ops} מפעילים, {_int(ref_total)} נסיעות {ref_phrase}."),
        "partial_note": (f"התאריך האחרון בקובץ ({_date(partial_last)}) נרשם חלקית ואינו נכלל בדף."
                         if partial_last is not None else ""),
        "other_years_note": (f"{dropped_other_years:,} שורות מתאריכים שמחוץ לשנת {year} אינן נכללות."
                             if dropped_other_years else ""),
        "daily_lede": (f"סך הנסיעות המורשות בכל יום מ-{_date(first_d)} עד {_date(last_d)}. "
                       f"השיא: {daily_chart['y'][peak_i]:,} נסיעות ב-{_date(daily.index[peak_i])}. "
                       + ("הפער השבועי בין ימי חול, שישי ושבת בולט לאורך כל התקופה."
                          if sat_ratio is not None and sat_ratio < 0.5 and len(daily) >= 28 else "")),
        "daily_aria": (f"גרף קו: נסיעות מורשות לפי יום ב-{year}, {len(daily_chart['x'])} ימים. "
                       f"שיא של {daily_chart['y'][peak_i]:,} נסיעות ב-{_date(daily.index[peak_i])}."),
        "monthly_aria": (f"גרף קווים: חציון הנסיעות היומיות לפי חודש ב-{year}, ביום חול, שישי ושבת."),
        "lines_month_aria": (f"גרף קו: מספר הקווים הפעילים בכל חודש ב-{year}, בין "
                             f"{min(monthly['lines']):,} ל-{max(monthly['lines']):,} קווים."),
        "dow_aria": ("גרף עמודות: חציון הנסיעות המורשות לפי יום בשבוע. "
                     f"יום {dow_chart['names'][max(range(len(dow_chart['values'])), key=lambda i: (dow_chart['values'][i], -i))]} מוביל."),
        "ops_aria": (f"גרף עמודות אופקי: נסיעות {ref_phrase} לפי מפעיל. "
                     f"{ops_names[0]} מוביל עם {ops_vals[0]:,} נסיעות ({ops_share[0]:.1f}%)."),
        "mix_aria": (f"גרף עמודות מוערמות: חלק כל מפעיל מהנסיעות המורשות בכל חודש ב-{year}, "
                     f"{len(mix_ops)} המפעילים הגדולים ו{OTHER}."),
        "clusters_aria": (f"גרף עמודות אופקי: {len(clusters['names'])} האשכולות עם הכי הרבה נסיעות {ref_phrase}. "
                          f"{clusters['names'][0]} מוביל עם {clusters['values'][0]:,} נסיעות."),
        "types_aria": (f"גרף טבעת: חלוקת הנסיעות {ref_phrase} לפי סוג קו. "
                       f"{types['names'][0]}: {types['share'][0]:.1f}%."),
        "vsizes_aria": (f"גרף טבעת: חלוקת הנסיעות {ref_phrase} לפי גודל רכב. "
                        f"{vsizes['names'][0]}: {vsizes['share'][0]:.1f}%."),
        "vtypes_aria": (f"גרף עמודות: נסיעות {ref_phrase} לפי סוג רכב. "
                        f"{vtypes['names'][0]}: {vtypes['values'][0]:,} נסיעות ({vtypes['share'][0]:.1f}%)."),
        "cities_aria": (f"גרף עמודות אופקי: {len(cities['names'])} יישובי המוצא עם הכי הרבה נסיעות יוצאות {ref_phrase}. "
                        f"{cities['names'][0]} מוביל עם {cities['values'][0]:,} נסיעות."),
        "sat_aria": ((f"גרף עמודות אופקי: {len(sat_cities['names'])} יישובי המוצא עם הכי הרבה נסיעות בשבת. "
                      f"{sat_cities['names'][0]} מוביל עם {sat_cities['values'][0]:,} נסיעות ({sat_cities['share'][0]:.1f}%).")
                     if sat_cities else ""),
        "sat_note": ((f"ממוצע לשבת על פני {sat_cities['n_days']} שבתות בשנת {year}. "
                      f"בסך הכול {sat_cities['total']:,} נסיעות בשבת ממוצעת, מ-{sat_cities['n_cities']:,} יישובים.")
                     if sat_cities else ""),
        "lines_aria": (f"גרף עמודות אופקי: {len(top_lines)} הקווים עם הכי הרבה נסיעות {ref_phrase}. "
                       f"{top_lines[0]['label']} מוביל עם {top_lines[0]['value']:,} נסיעות."),
        "dist_aria": (f"גרף עמודות: התפלגות {n_lines:,} הקווים לפי מספר נסיעות {ref_phrase}. "
                      f"קו חציוני: {median_line:.1f} נסיעות."),
        "dist_note": (f"כל קו נספר פעם אחת, עם כל הכיוונים והחלופות שלו. קו חציוני מורשה ל-{median_line:.1f} נסיעות {ref_phrase}."),
        "ref_phrase": ref_phrase,
        "ops_note": f"{TOP_OPERATORS} המפעילים הגדולים מוצגים בנפרד, והשאר מקובצים תחת {OTHER}.",
        "mix_note": (f"{MIX_OPERATORS} המפעילים הגדולים בשנה מוצגים בנפרד. "
                     "שינוי בחלקו של מפעיל לאורך השנה משקף העברת קווים, קווים חדשים או צמצום שירות."),
        "clusters_note": f"{TOP_CLUSTERS} האשכולות (אזורי מכרז) הגדולים, עם המפעיל העיקרי בכל אשכול.",
        "cities_note": f"{TOP_CITIES} היישובים שמהם יוצאות הכי הרבה נסיעות, לפי יישוב תחנת המוצא, מתוך {n_cities:,} יישובים.",
    }

    tables = {
        "monthly": [
            {"label": month_labels[i], "weekday": monthly["weekday"][i], "fri": monthly["fri"][i],
             "sat": monthly["sat"][i], "lines": monthly["lines"][i]}
            for i in range(len(months))
        ],
        "mix_months": month_labels,
    }

    summary = (f"איתור קווי אוטובוס ברישוי משרד התחבורה לפי מספר קו, מפעיל ויישוב: "
               f"{n_lines:,} קווים ו-{_int(ref_total)} נסיעות {ref_phrase} ב-{year}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["תחבורה ציבורית", "אוטובוסים", "רישוי קווים", "מפעילי תחבורה", "נסיעות"],
            "related_ids": ["27047419-e1fc-4f1d-bb15-7f5f0805d226", "1e9d4542-97af-47ac-a780-f2a6b291b1f5", "30cc4889-9bd7-4888-a66d-51ab39eb579a", "068ff53c-ad54-4848-8a29-bd9b178d9174"],
            "temporal_coverage": f"{first_d.strftime('%Y-%m-%d')}/{last_d.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "daily": daily_chart,
            "monthly": monthly,
            "dow": dow_chart,
            "operators": {"names": ops_names, "values": ops_vals, "lines": ops_lines, "share": ops_share},
            "mix": {"months": month_labels, "series": mix_series},
            "clusters": clusters,
            "types": types,
            "vsizes": vsizes,
            "vtypes": vtypes,
            "cities": cities,
            "sat_cities": sat_cities,
            "lines": {"labels": [l["label"] for l in top_lines], "values": [l["value"] for l in top_lines],
                      "routes": [l["route"] for l in top_lines]},
            "dist": {"labels": dist_labels, "values": dist_vals},
        },
        "top_lines": top_lines,
        "insights": insights,
        "labels": labels,
        "tables": tables,
    }


def _vav(word: str) -> str:
    """Hebrew 'and' prefix: 'ו-' before a non-Hebrew first character."""
    if word and "א" <= word[0] <= "ת":
        return word
    return "-" + word
