"""גמל-נט — monthly reports of every provident-fund (גמל / השתלמות / להשקעה)
investment track.

One CSV per period (1999–2022, 2023, 2024–now); a new period file is picked
up via `by_schema` + concat. Amounts are ₪ millions, yields nominal gross
(the dataset's field dictionary). Aggregates start at FROM_PERIOD: before
2017 the set of reporting funds shifts in steps (e.g. April 2008 and April
2009 move total assets by ±15% in a month with no market cause), so long
sums would mix scope changes into the trend. The page says so.

SPECIALIZATION was re-coded in 2024 (e.g. "מניות" → "עוקבי מדדים" /
"מתמחים בניהול אקטיבי"), so specialization is shown as a current snapshot
only, never as a time series.
"""
import pandas as pd

FROM_PERIOD = 201701
TOP_MANAGERS = 10
TOP_TRACKS = 10
TOP_SPECS = 9
RECENT_MONTHS = 36
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
LRI, PDI = "⁦", "⁩"
AGE_TRACKS = [("עד 50", "עד גיל 50"), ("50-60", "גיל 50–60"), ("60 ומעלה", "גיל 60 ומעלה")]
EXPOSURES = [("STOCK_MARKET_EXPOSURE", "חשיפה למניות"),
             ("FOREIGN_EXPOSURE", "חשיפה לחו״ל"),
             ("FOREIGN_CURRENCY_EXPOSURE", "חשיפה למט״ח")]
BIG_TRACK_M = 1000          # ₪ millions: "large track" for the Sharpe insight
MIN_RISK_TRACKS = 10


def p_he(rp):
    return f"{MONTHS_HE[rp % 100 - 1]} {rp // 100}"


def p_iso(rp):
    return f"{rp // 100}-{rp % 100:02d}"


def bn(millions):
    return f"{millions / 1000:,.1f} מיליארד ₪"


def pct(v, digits=1, signed=False):
    s = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return f"{LRI}{s}%{PDI}"


def num(v, digits=1, signed=False):
    """A percentage for a table cell — the unit lives in the column header."""
    s = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return f"{LRI}{s}{PDI}"


def short(name):
    return name.replace(' בע"מ', "").replace(" בע״מ", "").strip()


def _num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce")


def _prepare(df):
    out = pd.DataFrame({
        "fund": df["FUND_ID"].str.strip(),
        "name": df["FUND_NAME"].str.strip(),
        "manager": df["MANAGING_CORPORATION"].str.strip().map(short),
        "cls": df["FUND_CLASSIFICATION"].str.strip(),
        "target": df["TARGET_POPULATION"].str.strip(),
        "spec": df["SPECIALIZATION"].str.strip().replace("", "ללא סיווג"),
        "sub": df["SUB_SPECIALIZATION"].str.strip(),
        "rp": _num(df["REPORT_PERIOD"]),
        "assets": _num(df["TOTAL_ASSETS"]),
        "y": _num(df["MONTHLY_YIELD"]),
        "ytd": _num(df["YEAR_TO_DATE_YIELD"]),
        "mfee": _num(df["AVG_ANNUAL_MANAGEMENT_FEE"]),
        "dfee": _num(df["AVG_DEPOSIT_FEE"]),
        "net": _num(df["NET_MONTHLY_DEPOSITS"]),
        "dep": _num(df["DEPOSITS"]),
        "wd": _num(df["WITHDRAWLS"]),
        "tr": _num(df["INTERNAL_TRANSFERS"]),
        "liq": _num(df["LIQUID_ASSETS_PERCENT"]),
        "y3": _num(df["AVG_ANNUAL_YIELD_TRAILING_3YRS"]),
        "y5": _num(df["AVG_ANNUAL_YIELD_TRAILING_5YRS"]),
        "sd": _num(df["STANDARD_DEVIATION"]),
        "sharpe": _num(df["SHARPE_RATIO"]),
        **{c: _num(df[c]) for c, _ in EXPOSURES},
        "src": df["_resource_name"],
    })
    out = out.dropna(subset=["rp"])
    out["rp"] = out["rp"].astype(int)
    out = out[(out["rp"] >= FROM_PERIOD) & (out["fund"] != "")]
    out = (out.sort_values(["fund", "rp", "src"], kind="stable")
              .drop_duplicates(["fund", "rp"], keep="last")
              .reset_index(drop=True))
    return out


def _weighted(df, col):
    g = df.dropna(subset=[col, "assets"])
    g = g[g["assets"] > 0]
    w = (g[col] * g["assets"]).groupby(g["rp"]).sum()
    a = g.groupby("rp")["assets"].sum()
    return (w / a).sort_index()


def _wavg(df, col, by):
    g = df.dropna(subset=[col, "assets"])
    g = g[g["assets"] > 0]
    return (g[col] * g["assets"]).groupby(g[by]).sum() / g.groupby(by)["assets"].sum()


def _exposure_ok(df, col):
    """Rows whose exposure value reads as ₪ millions (≤105% of assets and not
    a percentage-sized number on a much larger track)."""
    e, a = df[col], df["assets"]
    ok = e.notna() & (a > 0)
    pct_like = ok & (e <= 100) & (a > 100) & (e < 0.05 * a)
    return ok, ok & (e <= 1.05 * a) & ~pct_like


def _exposure_shares(df):
    out, cover = {}, []
    for col, label in EXPOSURES:
        ok, good = _exposure_ok(df, col)
        g = df[good].groupby("rp")
        out[label] = (g[col].sum() / g["assets"].sum() * 100).sort_index()
        cover.append(float(df[good]["assets"].sum() / df[ok]["assets"].sum()))
    return out, min(cover) if cover else 0.0


def _months_back(rp, n):
    y, m = divmod(rp, 100)
    total = y * 12 + (m - 1) - n
    return (total // 12) * 100 + total % 12 + 1


# ── insights ─────────────────────────────────────────────────────────────


def insight_growth(assets, last):
    prev = last - 100
    if prev not in assets.index or assets[prev] <= 0:
        return None
    chg = assets[last] / assets[prev] - 1
    if abs(chg) < 0.01:
        return f"סך הנכסים ({bn(assets[last])}) כמעט לא השתנה לעומת {p_he(prev)}."
    word = "גדל" if chg > 0 else "קטן"
    return (f"סך הנכסים בקופות הגמל וקרנות ההשתלמות {word} ב-{pct(abs(chg) * 100)} בשנה — "
            f"מ-{bn(assets[prev])} ב{p_he(prev)} ל-{bn(assets[last])} ב{p_he(last)}.")


def insight_leader(shares):
    if shares.empty:
        return None
    top, share = shares.index[0], shares.iloc[0]
    top3 = shares.head(3).sum()
    if share < 0.15:
        return (f"אין גוף מנהל דומיננטי: הגדול שבהם, {top}, מנהל {pct(share * 100)} מהנכסים, "
                f"ושלושת הגדולים יחד — {pct(top3 * 100)}.")
    return (f"{top} מנהל {pct(share * 100)} מהנכסים, ושלושת הגופים הגדולים "
            f"יחד — {pct(top3 * 100)}.")


def insight_return(wy, last):
    want = [_months_back(last, i) for i in range(12)]
    if not all(r in wy.index for r in want):
        return None
    comp = 1.0
    for r in want:
        comp *= 1 + wy[r] / 100
    neg = sum(wy[r] < 0 for r in want)
    word = "חיובית" if comp > 1 else "שלילית"
    tail = (f"{neg} מתוך 12 החודשים היו שליליים." if neg
            else "כל 12 החודשים היו חיוביים.")
    return (f"התשואה הנומינלית המשוקללת (לפי גודל נכסים) ב-12 החודשים שהסתיימו "
            f"ב{p_he(last)} הייתה {word}: {pct((comp - 1) * 100, signed=True)}. {tail}")


def insight_fees(fee_year, partial_year):
    full = fee_year[[y != partial_year for y in fee_year.index]]
    if len(full) < 4:
        return None
    y1, v1 = int(full.index[-1]), full.iloc[-1]
    y0, v0 = int(full.index[0]), full.iloc[0]
    if abs(v1 - v0) < 0.005:
        return (f"דמי הניהול הממוצעים מהצבירה נותרו יציבים ({pct(v1, 2)}) בין "
                f"{y0} ל-{y1}.")
    word = "ירדו" if v1 < v0 else "עלו"
    return (f"דמי הניהול הממוצעים מהצבירה (משוקללים לפי נכסים) {word} מ-{pct(v0, 2)} "
            f"ב-{y0} ל-{pct(v1, 2)} ב-{y1}.")


def insight_flows_by_type(net12):
    if net12.empty or len(net12) < 2:
        return None
    s = net12.sort_values(ascending=False, kind="stable")
    top, bottom = s.index[0], s.index[-1]
    text = f"ב-12 החודשים האחרונים הכסף זרם בעיקר אל {top} ({bn(s.iloc[0])} נטו)"
    if s.iloc[-1] < 0:
        text += f", בעוד מ{bottom} יצאו {bn(-s.iloc[-1])} נטו"
    return text + "."


def insight_age(age):
    """Equity exposure of the default age tracks should fall with age."""
    if len(age) < 2:
        return None
    first, last = age[0], age[-1]
    if first["equity"] is None or last["equity"] is None:
        return None
    gap = first["equity"] - last["equity"]
    if abs(gap) < 5:
        return (f"במסלולי ברירת המחדל לפי גיל, שיעור החשיפה למניות דומה בין {first['label']} "
                f"({pct(first['equity'])}) ל{last['label']} ({pct(last['equity'])}).")
    word = "יורד" if gap > 0 else "עולה"
    return (f"במסלולי ברירת המחדל לפי גיל שיעור החשיפה למניות {word} עם הגיל: "
            f"{pct(first['equity'])} במסלול {first['label']} לעומת {pct(last['equity'])} "
            f"במסלול {last['label']}.")


def insight_spec(spec_assets):
    tot = spec_assets.sum()
    if tot <= 0 or "עוקבי מדדים" not in spec_assets.index:
        return None
    share = spec_assets["עוקבי מדדים"] / tot
    if share < 0.03:
        return None
    return (f"מסלולים עוקבי מדדים (פסיביים) מחזיקים כבר {pct(share * 100)} מהנכסים "
            f"({bn(spec_assets['עוקבי מדדים'])}).")


def insight_target(target_assets):
    tot = target_assets.sum()
    if tot <= 0:
        return None
    general = target_assets.get("כלל האוכלוסיה", 0)
    sector = tot - general
    if sector / tot < 0.02:
        return None
    return (f"{pct(sector / tot * 100)} מהנכסים ({bn(sector)}) נמצאים בקופות ענפיות "
            f"המיועדות לעובדי סקטור, מפעל או גוף מסוים; היתר פתוח לכלל האוכלוסייה.")


def insight_sharpe(cur):
    big = cur.dropna(subset=["sharpe", "y5"])
    big = big[big["assets"] >= BIG_TRACK_M]
    if len(big) < MIN_RISK_TRACKS:
        return None
    best = big.sort_values(["sharpe", "fund"], ascending=[False, True]).iloc[0]
    med = big["sharpe"].median()
    return (f"מבין {len(big)} המסלולים הגדולים (נכסים מעל מיליארד ₪) עם נתוני 5 שנים, יחס "
            f"שארפ הגבוה ביותר — {best['sharpe']:.2f} — שייך ל{best['name']} "
            f"(תשואה שנתית ממוצעת {pct(best['y5'], 2)}); החציון: {med:.2f}.")


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["reports"])
    last = int(df["rp"].max())
    cur = df[df["rp"] == last]
    partial_year = last // 100 if last % 100 != 12 else None

    assets = df.groupby("rp")["assets"].sum().sort_index()
    cls_tot = cur.groupby("cls")["assets"].sum().sort_index().sort_values(ascending=False, kind="stable")
    cls_order = list(cls_tot.index)
    by_cls = (df.pivot_table(index="rp", columns="cls", values="assets", aggfunc="sum")
                .sort_index().fillna(0))
    by_cls = by_cls[[c for c in cls_order if c in by_cls.columns]
                    + sorted(c for c in by_cls.columns if c not in cls_order)]
    wy = _weighted(df, "y")
    mfee = _weighted(df, "mfee")
    dfee = _weighted(df, "dfee")
    net_m = df.dropna(subset=["net"]).groupby("rp")["net"].sum().sort_index()

    mgr = (cur.groupby("manager")["assets"].sum().sort_index()
              .sort_values(ascending=False, kind="stable"))
    shares = mgr / mgr.sum()
    top_m = mgr.head(TOP_MANAGERS)
    other_m = mgr.iloc[TOP_MANAGERS:].sum()

    mfee_y = mfee.groupby(mfee.index // 100).mean()
    dfee_y = dfee.groupby(dfee.index // 100).mean()

    roll = []
    periods = list(wy.index)
    for i in range(11, len(periods)):
        win = periods[i - 11:i + 1]
        if _months_back(win[-1], 11) != win[0]:
            continue
        comp = 1.0
        for r in win:
            comp *= 1 + wy[r] / 100
        roll.append((win[-1], round((comp - 1) * 100, 2)))

    tracks = (cur.dropna(subset=["ytd"]).sort_values(["assets", "fund"], ascending=[False, True])
                 .head(TOP_TRACKS))
    recent_y = wy.tail(RECENT_MONTHS)

    # Net deposits over the last 12 reported months, by fund type.
    win12 = [_months_back(last, i) for i in range(12)]
    n12 = df[df["rp"].isin(win12)].dropna(subset=["net"])
    net12 = n12.groupby("cls")["net"].sum().reindex(cls_order).dropna()

    # Specialization snapshot (current taxonomy only).
    spec_assets = (cur.groupby("spec")["assets"].sum().sort_index()
                      .sort_values(ascending=False, kind="stable"))
    spec_top = spec_assets.head(TOP_SPECS)
    spec_other = spec_assets.iloc[TOP_SPECS:].sum()
    spec_ytd = _wavg(cur, "ytd", "spec")
    spec_y5 = _wavg(cur, "y5", "spec")

    # Default age tracks (SPECIALIZATION "מדרגות").
    stairs = cur[cur["spec"] == "מדרגות"]
    age = []
    for sub, label in AGE_TRACKS:
        g = stairs[stairs["sub"] == sub]
        if g.empty or g["assets"].sum() <= 0:
            continue
        ok, good = _exposure_ok(g, "STOCK_MARKET_EXPOSURE")
        eg = g[good]
        equity = (float(eg["STOCK_MARKET_EXPOSURE"].sum() / eg["assets"].sum() * 100)
                  if len(eg) and eg["assets"].sum() > 0 else None)
        ytd = _wavg(g, "ytd", "spec")
        age.append({"label": label, "assets": float(g["assets"].sum()), "tracks": int(len(g)),
                    "equity": equity,
                    "ytd": float(ytd.iloc[0]) if len(ytd) else None})

    target_assets = cur.groupby("target")["assets"].sum().sort_index()

    exp, exp_cover = _exposure_shares(df)
    exp_x = sorted(set().union(*[set(s.index) for s in exp.values()])) if exp else []
    exp_rows = []
    for y in sorted({r // 100 for r in exp_x}):
        rp = max(r for r in exp_x if r // 100 == y)
        exp_rows.append({"period": p_he(rp),
                         **{lbl: (num(s[rp]) if rp in s.index else "—") for lbl, s in exp.items()}})

    flows = (df.dropna(subset=["dep", "wd", "tr"]).groupby(df["rp"] // 100)[["dep", "wd", "tr"]]
               .sum().sort_index())

    risk = cur.dropna(subset=["sd", "y5"])
    risk = risk[risk["assets"] > 0].sort_values(["assets", "fund"], ascending=[False, True])

    w5 = _wavg(cur, "y5", "manager")
    w3 = _wavg(cur, "y3", "manager")
    mgr_order = [n for n in top_m.index if n in w5.index or n in w3.index]

    liq_c = cur.dropna(subset=["liq"])
    liq_c = liq_c[liq_c["assets"] > 0]
    liq = float((liq_c["liq"] * liq_c["assets"]).sum() / liq_c["assets"].sum()) if len(liq_c) else None

    charts = {
        "assets": {
            "x": [p_iso(r) for r in by_cls.index],
            "series": [{"name": c, "data": [round(v / 1000, 1) for v in by_cls[c]]}
                       for c in by_cls.columns],
        },
        "managers": {
            "names": [*top_m.index, *(["אחר"] if other_m > 0 else [])],
            "values": [round(v / 1000, 1) for v in [*top_m.values, *([other_m] if other_m > 0 else [])]],
        },
        "net12": {"names": list(net12.index), "values": [round(v / 1000, 2) for v in net12.values]},
        "spec": {
            "names": [*spec_top.index, *(["אחר"] if spec_other > 0 else [])],
            "values": [round(v / 1000, 1) for v in [*spec_top.values, *([spec_other] if spec_other > 0 else [])]],
        },
        "spec_yield": {
            "names": list(spec_top.index),
            "ytd": [round(float(spec_ytd[s]), 2) if s in spec_ytd.index else None for s in spec_top.index],
            "y5": [round(float(spec_y5[s]), 2) if s in spec_y5.index else None for s in spec_top.index],
        },
        "age": {
            "names": [a["label"] for a in age],
            "equity": [None if a["equity"] is None else round(a["equity"], 1) for a in age],
            "ytd": [None if a["ytd"] is None else round(a["ytd"], 2) for a in age],
        },
        "yields": {"x": [p_iso(r) for r in recent_y.index],
                   "y": [round(v, 2) for v in recent_y.values]},
        "rolling": {"x": [p_iso(r) for r, _ in roll], "y": [v for _, v in roll]},
        "fees": {"x": [str(int(y)) for y in mfee_y.index],
                 "mgmt": [round(v, 3) for v in mfee_y.values],
                 "deposit": [round(dfee_y.get(y), 3) if y in dfee_y.index else None
                             for y in mfee_y.index]},
        "tracks": {"names": list(tracks["name"]), "values": [round(v, 2) for v in tracks["ytd"]]},
        "exposure": {
            "x": [p_iso(r) for r in exp_x],
            "series": [{"name": lbl, "data": [round(float(s[r]), 1) if r in s.index else None
                                              for r in exp_x]}
                       for lbl, s in exp.items()],
        },
        "flows": {
            "x": [str(int(y)) for y in flows.index],
            "dep": [round(v / 1000, 1) for v in flows["dep"]],
            "wd": [round(-v / 1000, 1) for v in flows["wd"]],
            "tr": [round(v / 1000, 1) for v in flows["tr"]],
        },
        "risk": {
            "points": [[round(float(r["sd"]), 2), round(float(r["y5"]), 2),
                        round(float(r["assets"]) / 1000, 2), r["name"], r["cls"]]
                       for _, r in risk.iterrows()],
            "classes": [c for c in cls_order if c in set(risk["cls"])],
        },
        "mgr_yield": {
            "names": mgr_order,
            "y3": [round(float(w3[n]), 2) if n in w3.index else None for n in mgr_order],
            "y5": [round(float(w5[n]), 2) if n in w5.index else None for n in mgr_order],
        },
    }

    rules = [
        ("growth", insight_growth(assets, last)),
        ("leader", insight_leader(shares)),
        ("return", insight_return(wy, last)),
        ("flows_by_type", insight_flows_by_type(net12)),
        ("age", insight_age(age)),
        ("spec", insight_spec(spec_assets)),
        ("fees", insight_fees(mfee_y, partial_year)),
        ("target", insight_target(target_assets)),
        ("sharpe", insight_sharpe(cur)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    last_y = wy.get(last)
    kpis = {
        "assets": {"value": float(assets[last]), "display": bn(assets[last])},
        "tracks": {"value": int(cur["fund"].nunique()), "display": f"{cur['fund'].nunique():,}"},
        "managers": {"value": int(mgr.size), "display": f"{mgr.size:,}"},
        "month_yield": {"value": None if last_y is None else float(last_y),
                        "display": "—" if last_y is None else pct(last_y, 2, signed=True)},
        "liquid": {"value": liq, "display": "—" if liq is None else pct(liq)},
    }

    ytd_label = f"ינואר–{MONTHS_HE[last % 100 - 1]} {last // 100}"
    tables = {
        "managers": [{"name": n, "assets": bn(v), "share": num(v / mgr.sum() * 100)}
                     for n, v in mgr.items()],
        "net12": [{"name": n, "net": bn(v)} for n, v in net12.items()],
        "spec": [{"name": n, "assets": bn(v), "share": num(v / spec_assets.sum() * 100),
                  "ytd": num(spec_ytd[n], 2, signed=True) if n in spec_ytd.index else "—",
                  "y5": num(spec_y5[n], 2) if n in spec_y5.index else "—"}
                 for n, v in spec_assets.items()],
        "age": [{"label": a["label"], "tracks": f"{a['tracks']:,}", "assets": bn(a["assets"]),
                 "equity": "—" if a["equity"] is None else num(a["equity"]),
                 "ytd": "—" if a["ytd"] is None else num(a["ytd"], 2, signed=True)} for a in age],
        "fees": [{"year": f"{int(y)}{' (חלקית)' if int(y) == partial_year else ''}",
                  "mgmt": num(v, 3),
                  "dep": num(dfee_y[y], 3) if y in dfee_y.index else "—"}
                 for y, v in mfee_y.items()],
        "tracks": [{"name": n, "ytd": num(v, 2, signed=True), "assets": bn(a)}
                   for n, v, a in zip(tracks["name"], tracks["ytd"], tracks["assets"])],
        "flows": [{"year": f"{int(y)}{' (חלקית)' if int(y) == partial_year else ''}",
                   "dep": bn(r["dep"]), "wd": bn(r["wd"]), "tr": bn(r["tr"]),
                   "net": bn(r["dep"] - r["wd"] + r["tr"])}
                  for y, r in flows.iterrows()],
        "exposure": exp_rows,
        "exposure_labels": [lbl for _, lbl in EXPOSURES],
        "mgr_yield": [{"name": n,
                       "y3": num(w3[n], 2) if n in w3.index else "—",
                       "y5": num(w5[n], 2) if n in w5.index else "—"} for n in mgr_order],
        "target": [{"name": n, "assets": bn(v), "share": num(v / target_assets.sum() * 100)}
                   for n, v in target_assets.sort_values(ascending=False, kind="stable").items()],
    }

    n_tracks = cur["fund"].nunique()
    labels = {
        "period": p_he(last),
        "ytd_label": ytd_label,
        "lede": (f"דיווחים חודשיים של {n_tracks:,} מסלולי השקעה בקופות גמל, קרנות השתלמות "
                 f"וקופות גמל להשקעה, ב-{mgr.size} גופים מנהלים, נכון ל{p_he(last)}. "
                 f"סך הנכסים: {bn(assets[last])}."),
        "scope_note": (f"הנתונים מ{p_he(FROM_PERIOD)} ואילך: בשנים קודמות היקף הקופות המדווחות "
                       f"השתנה בקפיצות (למשל באפריל 2008 ובאפריל 2009), כך שסכומים ארוכי טווח "
                       f"היו מערבבים שינויי דיווח עם מגמה. סכומים במיליארדי ₪, תשואות נומינליות ברוטו."),
        "assets_aria": (f"גרף שטח: סך הנכסים לפי סוג קופה, {p_he(FROM_PERIOD)} עד {p_he(last)}, "
                        f"במיליארדי ₪."),
        "managers_aria": f"תרשים עמודות: נכסים לפי גוף מנהל ב{p_he(last)}, במיליארדי ₪.",
        "net12_aria": f"תרשים עמודות: הפקדות נטו ב-12 החודשים שהסתיימו ב{p_he(last)}, לפי סוג קופה.",
        "spec_aria": f"תרשים עמודות: נכסים לפי סוג התמחות המסלול ב{p_he(last)}, במיליארדי ₪.",
        "spec_yield_aria": (f"תרשים עמודות: תשואה מתחילת השנה ותשואה שנתית ממוצעת ל-5 שנים לפי "
                            f"סוג התמחות, משוקללות לפי נכסים, {p_he(last)}."),
        "age_aria": (f"תרשים עמודות: שיעור החשיפה למניות והתשואה מתחילת השנה במסלולי ברירת "
                     f"המחדל לפי גיל, {p_he(last)}."),
        "yields_aria": (f"תרשים עמודות: תשואה חודשית משוקללת ב-{len(recent_y)} החודשים "
                        f"האחרונים; חודשים שליליים באדום."),
        "rolling_aria": "גרף קו: תשואה מצטברת ל-12 חודשים מתגלגלים, משוקללת לפי נכסים.",
        "fees_aria": "גרף קווים: דמי ניהול ממוצעים מצבירה ומהפקדה לפי שנה, משוקללים לפי נכסים.",
        "fees_note": ("ממוצע שנתי של הממוצע החודשי המשוקלל לפי נכסים. דמי ניהול מהפקדה מדווחים "
                      "רק בחלק מהמסלולים." + (f" {partial_year} — שנה חלקית." if partial_year else "")),
        "tracks_aria": (f"תרשים עמודות: תשואה מתחילת השנה של {len(tracks)} המסלולים "
                        f"הגדולים ב{p_he(last)}."),
        "exposure_aria": (f"גרף קווים: חשיפה למניות, לחו״ל ולמט״ח כאחוז מהנכסים, משוקללת לפי "
                          f"נכסים, {p_he(FROM_PERIOD)} עד {p_he(last)}."),
        "exposure_note": (f"שיעור החשיפה מסך הנכסים, משוקלל לפי נכסים. מסלולים שמדווחים ערך שנראה "
                          f"כאחוז ולא כמיליוני ₪ הוצאו; המסלולים שנכללו מחזיקים לפחות "
                          f"{pct(exp_cover * 100)} מהנכסים בכל אחד מהמדדים."),
        "flows_aria": "תרשים עמודות: הפקדות, משיכות והעברות בין קופות לפי שנה, במיליארדי ₪.",
        "risk_aria": (f"תרשים פיזור: {len(risk)} מסלולים עם נתוני 5 שנים — סטיית תקן מול "
                      f"תשואה שנתית ממוצעת, גודל הנקודה לפי נכסים."),
        "risk_note": (f"כל נקודה היא מסלול השקעה ({len(risk)} מסלולים עם היסטוריה של 5 שנים "
                      f"לפחות, נכון ל{p_he(last)}), בצבע לפי סוג הקופה."),
        "mgr_yield_aria": ("תרשים עמודות: תשואה שנתית ממוצעת ל-3 ול-5 שנים לפי גוף מנהל, "
                           "משוקללת לפי נכסי המסלולים."),
        "managers_caption": f"נכסים ונתח שוק לפי גוף מנהל, {p_he(last)}.",
        "net12_caption": f"הפקדות נטו ב-12 החודשים שהסתיימו ב{p_he(last)}, לפי סוג קופה.",
        "spec_caption": f"נכסים, תשואה מתחילת השנה ותשואה ל-5 שנים לפי סוג התמחות, {p_he(last)}.",
        "age_caption": f"מסלולי ברירת המחדל לפי גיל, {p_he(last)}.",
        "fees_caption": "דמי ניהול ממוצעים מצבירה ומהפקדה לפי שנה.",
        "tracks_caption": f"תשואה מתחילת השנה ונכסים של המסלולים הגדולים, {p_he(last)}.",
        "flows_caption": "הפקדות, משיכות, העברות בין קופות והפקדות נטו לפי שנה.",
        "exposure_caption": "שיעור החשיפה בסוף כל שנה (או בחודש האחרון של שנה חלקית).",
        "mgr_yield_caption": "תשואה שנתית ממוצעת לפי גוף מנהל, משוקללת לפי נכסים.",
        "target_caption": f"נכסים לפי אוכלוסיית היעד של הקופה, {p_he(last)}.",
    }

    return {
        "agent_data": {
            "summary_he": (f"נתוני גמל-נט: דיווח חודשי על {n_tracks:,} מסלולי קופות גמל, קרנות "
                           f"השתלמות וקופות גמל להשקעה — נכסים, תשואות, דמי ניהול והפקדות. סך "
                           f"הנכסים ב{p_he(last)}: {bn(assets[last])}."),
            "dataset_kind": "timeseries",
            "related_ids": ["3a1ca8fa-738b-4890-b52f-e8f7ce1e6145",
                            "b5dd1f5e-0566-42fd-8db9-ae12e10c445b"],
            "suggested_tags": ["קופות גמל", "קרנות השתלמות", "חיסכון", "דמי ניהול", "תשואות", "שוק ההון"],
            "temporal_coverage": f"{p_iso(FROM_PERIOD)}/{p_iso(last)}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
