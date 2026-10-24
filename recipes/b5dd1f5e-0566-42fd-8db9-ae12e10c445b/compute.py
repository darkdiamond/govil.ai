"""ביטוח-נט — monthly reports of the profit-sharing investment tracks behind
Israeli life-insurance savings policies.

One CSV per period (1999–2022, 2023, 2024–now), picked up via `by_schema` +
concat. Amounts are ₪ millions, yields nominal gross. Aggregates start at
FROM_PERIOD: the "policies issued from 2004" class begins then and the number
of reporting tracks doubles, so earlier totals are not comparable. Track type
is not a column — it is read from the track name with ordered keyword rules;
names that match none fall into "אחר", so a new naming style only grows that
bucket.
"""
import pandas as pd

FROM_PERIOD = 200401
TOP_TRACKS = 10
RECENT_MONTHS = 36
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
LRI, PDI = "⁦", "⁩"
EXPOSURES = [("STOCK_MARKET_EXPOSURE", "חשיפה למניות"),
             ("FOREIGN_EXPOSURE", "חשיפה לחו״ל"),
             ("FOREIGN_CURRENCY_EXPOSURE", "חשיפה למט״ח")]
BIG_TRACK_M = 1000
MIN_RISK_TRACKS = 10
# Ordered: the first rule whose keywords all appear in the name wins.
TYPE_RULES = [
    ("עוקבי מדדים", [["עוקב"], ["S&P"], ["מדד"]]),
    ("הלכתי", [["הלכה"]]),
    # The legacy general profit-sharing funds of the 1990–2003 policies
    # ("קרן י'" / "קרן ט'", and their post-2004 "קרן י' חדשה").
    ("קרנות י׳ / ט׳", [["קרן י'"], ["קרן י׳"], ["קרן ט'"], ["קרן ט׳"]]),
    ("מקבלי קצבה", [["קצבה"]]),
    ("תלוי גיל", [["גיל"], ["ומעלה"], ["ומטה"], ["לבני"]]),
    ("ניהול אישי", [["ניהול אישי"]]),
    ("משולב סחיר", [["משולב"]]),
    ("אג״ח עם מניות", [["עד", "מניות"]]),
    ("מניות", [["מניות"]]),
    ("אג״ח ממשלות", [["ממשלות"]]),
    ("אשראי ואג״ח", [["אשראי"], ['אג"ח'], ["אג״ח"]]),
    ("שקלי / כספי", [["שקלי"], ["כספי"]]),
    ("כללי", [["כללי"], ["משתתף ברווחים"]]),
]


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
    return (name.replace(' בע"מ', "").replace(" בע״מ", "")
                .replace(" חברה לביטוח", "").replace(" ביטוח", "").strip())


def track_type(name):
    for label, alternatives in TYPE_RULES:
        if any(all(k in name for k in keys) for keys in alternatives):
            return label
    return "אחר"


def vintage(cls):
    return cls.replace("פוליסות שהונפקו ", "").strip()


def _num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce")


def _months_back(rp, n):
    y, m = divmod(rp, 100)
    total = y * 12 + (m - 1) - n
    return (total // 12) * 100 + total % 12 + 1


def _prepare(df):
    out = pd.DataFrame({
        "fund": df["FUND_ID"].str.strip(),
        "name": df["FUND_NAME"].str.strip(),
        "insurer": df["PARENT_COMPANY_NAME"].str.strip().map(short),
        "cls": df["FUND_CLASSIFICATION"].str.strip().map(vintage),
        "rp": _num(df["REPORT_PERIOD"]),
        "assets": _num(df["TOTAL_ASSETS"]),
        "y": _num(df["MONTHLY_YIELD"]),
        "ytd": _num(df["YEAR_TO_DATE_YIELD"]),
        "mfee": _num(df["AVG_ANNUAL_MANAGEMENT_FEE"]),
        "dfee": _num(df["AVG_DEPOSIT_FEE"]),
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
    out["type"] = out["name"].map(track_type)
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


def _exposure_shares(df):
    out, cover = {}, []
    a = df["assets"]
    for col, label in EXPOSURES:
        e = df[col]
        ok = e.notna() & (a > 0)
        pct_like = ok & (e <= 100) & (a > 100) & (e < 0.05 * a)
        good = ok & (e <= 1.05 * a) & ~pct_like
        g = df[good].groupby("rp")
        out[label] = (g[col].sum() / g["assets"].sum() * 100).sort_index()
        cover.append(float(df[good]["assets"].sum() / df[ok]["assets"].sum()) if ok.any() else 0.0)
    return out, min(cover) if cover else 0.0


def _annual_returns(wy):
    """Compounded asset-weighted return per calendar year with all 12 months."""
    out = {}
    for y, g in wy.groupby(wy.index // 100):
        if len(g) == 12:
            comp = 1.0
            for v in g.values:
                comp *= 1 + v / 100
            out[int(y)] = (comp - 1) * 100
    return pd.Series(out).sort_index()


# ── insights ─────────────────────────────────────────────────────────────


def insight_growth(assets, last):
    prev = last - 100
    if prev not in assets.index or assets[prev] <= 0:
        return None
    chg = assets[last] / assets[prev] - 1
    if abs(chg) < 0.01:
        return f"סך הנכסים ({bn(assets[last])}) כמעט לא השתנה לעומת {p_he(prev)}."
    word = "גדל" if chg > 0 else "קטן"
    return (f"סך הנכסים במסלולי ביטוח החיים המשתתפים ברווחים {word} ב-{pct(abs(chg) * 100)} "
            f"בשנה — מ-{bn(assets[prev])} ב{p_he(prev)} ל-{bn(assets[last])} ב{p_he(last)}.")


def insight_leader(shares):
    if shares.empty:
        return None
    top, share = shares.index[0], shares.iloc[0]
    top3 = shares.head(3).sum()
    if share < 0.15:
        return (f"אין חברת ביטוח דומיננטית: שלוש הגדולות מנהלות יחד {pct(top3 * 100)} "
                f"מהנכסים.")
    return (f"{top} מנהלת {pct(share * 100)} מהנכסים, ושלוש חברות הביטוח הגדולות יחד — "
            f"{pct(top3 * 100)}.")


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
    return (f"התשואה הנומינלית המשוקללת ב-12 החודשים שהסתיימו ב{p_he(last)} הייתה {word}: "
            f"{pct((comp - 1) * 100, signed=True)}. {tail}")


def insight_annual(annual):
    if len(annual) < 5:
        return None
    best_y = int(annual.idxmax())
    worst_y = int(annual.idxmin())
    neg = int((annual < 0).sum())
    return (f"מאז {int(annual.index[0])} השנה הטובה ביותר הייתה {best_y} "
            f"({pct(annual[best_y], signed=True)}) והגרועה ביותר {worst_y} "
            f"({pct(annual[worst_y], signed=True)}); {neg} מתוך {len(annual)} השנים המלאות "
            f"הסתיימו בתשואה שלילית.")


def insight_vintage(vin_ytd, ytd_label):
    v = vin_ytd.dropna()
    if len(v) < 2:
        return None
    hi, lo = v.idxmax(), v.idxmin()
    if v[hi] - v[lo] < 0.5:
        return (f"התשואה מתחילת השנה ({ytd_label}) דומה בין דורות הפוליסות: בין "
                f"{pct(v[lo], 2, signed=True)} ל-{pct(v[hi], 2, signed=True)}.")
    return (f"בין דורות הפוליסות התשואה מתחילת השנה ({ytd_label}) הגבוהה ביותר — "
            f"{pct(v[hi], 2, signed=True)} — בפוליסות שהונפקו {hi}, והנמוכה ביותר — "
            f"{pct(v[lo], 2, signed=True)} — בפוליסות שהונפקו {lo}.")


def insight_fees(fee_year, partial_year):
    full = fee_year[[y != partial_year for y in fee_year.index]].dropna()
    if len(full) < 4:
        return None
    y1, v1 = int(full.index[-1]), full.iloc[-1]
    y0, v0 = int(full.index[0]), full.iloc[0]
    if abs(v1 - v0) < 0.005:
        return f"דמי הניהול הממוצעים מהצבירה נותרו יציבים ({pct(v1, 2)}) בין {y0} ל-{y1}."
    word = "ירדו" if v1 < v0 else "עלו"
    return (f"דמי הניהול הממוצעים מהצבירה (משוקללים לפי נכסים) {word} מ-{pct(v0, 2)} "
            f"ב-{y0} ל-{pct(v1, 2)} ב-{y1}.")


def insight_exposure(shares, last):
    s = shares.get("חשיפה למניות")
    then = last - 300
    if s is None or last not in s.index or then not in s.index:
        return None
    d = s[last] - s[then]
    if abs(d) < 2:
        return (f"החשיפה למניות נותרה כמעט ללא שינוי בשלוש השנים האחרונות: "
                f"{pct(s[last])} מהנכסים ב{p_he(last)}.")
    word = "עלתה" if d > 0 else "ירדה"
    return (f"החשיפה למניות {word} מ-{pct(s[then])} מהנכסים ב{p_he(then)} ל-{pct(s[last])} "
            f"ב{p_he(last)}.")


def insight_types(type_assets):
    tot = type_assets.sum()
    if tot <= 0 or len(type_assets) < 2:
        return None
    top = type_assets.index[0]
    share = type_assets.iloc[0] / tot
    eq = type_assets.get("מניות", 0) / tot
    lead = "רוב הכסף מנוהל" if share > 0.5 else "הנתח הגדול ביותר של הכסף מנוהל"
    text = f"{lead} במסלולים מסוג {top} ({pct(share * 100)} מהנכסים)"
    if top != "מניות" and eq >= 0.02:
        text += f"; מסלולי המניות מחזיקים {pct(eq * 100)}"
    return text + "."


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
    ytd_label = f"ינואר–{MONTHS_HE[last % 100 - 1]} {last // 100}"

    assets = df.groupby("rp")["assets"].sum().sort_index()
    vin_order = sorted(df["cls"].unique())
    by_cls = (df.pivot_table(index="rp", columns="cls", values="assets", aggfunc="sum")
                .sort_index().fillna(0))[vin_order]
    wy = _weighted(df, "y")
    mfee = _weighted(df, "mfee")
    dfee = _weighted(df, "dfee")
    mfee_y = mfee.groupby(mfee.index // 100).mean()
    dfee_y = dfee.groupby(dfee.index // 100).mean()
    annual = _annual_returns(wy)

    ins = (cur.groupby("insurer")["assets"].sum().sort_index()
              .sort_values(ascending=False, kind="stable"))
    shares = ins / ins.sum()

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
    recent_y = wy.tail(RECENT_MONTHS)

    vin_ytd = _wavg(cur, "ytd", "cls").reindex(vin_order)
    vin_y5 = _wavg(cur, "y5", "cls").reindex(vin_order)
    vin_assets = cur.groupby("cls")["assets"].sum().reindex(vin_order)

    type_assets = (cur.groupby("type")["assets"].sum().sort_index()
                      .sort_values(ascending=False, kind="stable"))
    type_ytd = _wavg(cur, "ytd", "type")
    type_y5 = _wavg(cur, "y5", "type")
    type_n = cur.groupby("type")["fund"].nunique()

    tracks = (cur.dropna(subset=["ytd"]).sort_values(["assets", "fund"], ascending=[False, True])
                 .head(TOP_TRACKS))

    exp, exp_cover = _exposure_shares(df)
    exp_x = sorted(set().union(*[set(s.index) for s in exp.values()])) if exp else []
    exp_rows = []
    for y in sorted({r // 100 for r in exp_x}):
        rp = max(r for r in exp_x if r // 100 == y)
        exp_rows.append({"period": p_he(rp),
                         **{lbl: (num(s[rp]) if rp in s.index else "—") for lbl, s in exp.items()}})

    risk = cur.dropna(subset=["sd", "y5"])
    risk = risk[risk["assets"] > 0].sort_values(["assets", "fund"], ascending=[False, True])

    w5 = _wavg(cur, "y5", "insurer")
    w3 = _wavg(cur, "y3", "insurer")
    ins_order = [n for n in ins.index if n in w5.index or n in w3.index]

    liq_c = cur.dropna(subset=["liq"])
    liq_c = liq_c[liq_c["assets"] > 0]
    liq = float((liq_c["liq"] * liq_c["assets"]).sum() / liq_c["assets"].sum()) if len(liq_c) else None

    charts = {
        "assets": {"x": [p_iso(r) for r in by_cls.index],
                   "series": [{"name": f"פוליסות {c}", "data": [round(v / 1000, 1) for v in by_cls[c]]}
                              for c in by_cls.columns]},
        "insurers": {"names": list(ins.index), "values": [round(v / 1000, 1) for v in ins.values]},
        "annual": {"x": [str(y) for y in annual.index], "y": [round(v, 2) for v in annual.values]},
        "vintage": {"names": [f"פוליסות {c}" for c in vin_order],
                    "ytd": [None if pd.isna(v) else round(float(v), 2) for v in vin_ytd.values],
                    "y5": [None if pd.isna(v) else round(float(v), 2) for v in vin_y5.values]},
        "types": {"names": list(type_assets.index),
                  "values": [round(v / 1000, 1) for v in type_assets.values]},
        "type_yield": {"names": list(type_assets.index),
                       "ytd": [round(float(type_ytd[t]), 2) if t in type_ytd.index else None
                               for t in type_assets.index],
                       "y5": [round(float(type_y5[t]), 2) if t in type_y5.index else None
                              for t in type_assets.index]},
        "yields": {"x": [p_iso(r) for r in recent_y.index], "y": [round(v, 2) for v in recent_y.values]},
        "rolling": {"x": [p_iso(r) for r, _ in roll], "y": [v for _, v in roll]},
        "fees": {"x": [str(int(y)) for y in mfee_y.index],
                 "mgmt": [round(v, 3) for v in mfee_y.values],
                 "deposit": [round(dfee_y[y], 3) if y in dfee_y.index else None for y in mfee_y.index]},
        "tracks": {"names": list(tracks["name"]), "values": [round(v, 2) for v in tracks["ytd"]]},
        "exposure": {"x": [p_iso(r) for r in exp_x],
                     "series": [{"name": lbl, "data": [round(float(s[r]), 1) if r in s.index else None
                                                       for r in exp_x]}
                                for lbl, s in exp.items()]},
        "risk": {"points": [[round(float(r["sd"]), 2), round(float(r["y5"]), 2),
                             round(float(r["assets"]) / 1000, 2), r["name"], r["type"]]
                            for _, r in risk.iterrows()],
                 "classes": [t for t in type_assets.index if t in set(risk["type"])]},
        "ins_yield": {"names": ins_order,
                      "y3": [round(float(w3[n]), 2) if n in w3.index else None for n in ins_order],
                      "y5": [round(float(w5[n]), 2) if n in w5.index else None for n in ins_order]},
    }

    rules = [
        ("growth", insight_growth(assets, last)),
        ("leader", insight_leader(shares)),
        ("return", insight_return(wy, last)),
        ("annual", insight_annual(annual)),
        ("vintage", insight_vintage(vin_ytd, ytd_label)),
        ("types", insight_types(type_assets)),
        ("fees", insight_fees(mfee_y, partial_year)),
        ("exposure", insight_exposure(exp, last)),
        ("sharpe", insight_sharpe(cur)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    last_y = wy.get(last)
    kpis = {
        "assets": {"value": float(assets[last]), "display": bn(assets[last])},
        "tracks": {"value": int(cur["fund"].nunique()), "display": f"{cur['fund'].nunique():,}"},
        "insurers": {"value": int(ins.size), "display": f"{ins.size:,}"},
        "month_yield": {"value": None if last_y is None else float(last_y),
                        "display": "—" if last_y is None else pct(last_y, 2, signed=True)},
        "liquid": {"value": liq, "display": "—" if liq is None else pct(liq)},
    }

    tables = {
        "insurers": [{"name": n, "assets": bn(v), "share": num(v / ins.sum() * 100)} for n, v in ins.items()],
        "annual": [{"year": str(y), "ret": num(v, 2, signed=True)} for y, v in annual.items()],
        "vintage": [{"name": f"פוליסות {c}", "assets": bn(vin_assets[c]),
                     "ytd": "—" if pd.isna(vin_ytd[c]) else num(vin_ytd[c], 2, signed=True),
                     "y5": "—" if pd.isna(vin_y5[c]) else num(vin_y5[c], 2)} for c in vin_order],
        "types": [{"name": t, "tracks": f"{int(type_n[t]):,}", "assets": bn(v),
                   "ytd": num(type_ytd[t], 2, signed=True) if t in type_ytd.index else "—",
                   "y5": num(type_y5[t], 2) if t in type_y5.index else "—"}
                  for t, v in type_assets.items()],
        "fees": [{"year": f"{int(y)}{' (חלקית)' if int(y) == partial_year else ''}",
                  "mgmt": num(v, 3), "dep": num(dfee_y[y], 3) if y in dfee_y.index else "—"}
                 for y, v in mfee_y.items()],
        "tracks": [{"name": n, "ytd": num(v, 2, signed=True), "assets": bn(a)}
                   for n, v, a in zip(tracks["name"], tracks["ytd"], tracks["assets"])],
        "exposure": exp_rows,
        "exposure_labels": [lbl for _, lbl in EXPOSURES],
        "ins_yield": [{"name": n, "y3": num(w3[n], 2) if n in w3.index else "—",
                       "y5": num(w5[n], 2) if n in w5.index else "—"} for n in ins_order],
    }

    n_tracks = cur["fund"].nunique()
    first = int(df["rp"].min())
    labels = {
        "period": p_he(last),
        "ytd_label": ytd_label,
        "lede": (f"דיווחים חודשיים של {n_tracks:,} מסלולי השקעה שעליהם נשענות פוליסות ביטוח חיים "
                 f"משתתפות ברווחים, ב-{ins.size} חברות ביטוח, נכון ל{p_he(last)}. סך הנכסים: "
                 f"{bn(assets[last])}."),
        "scope_note": (f"הנתונים מ{p_he(first)} ואילך: אז נוסף סיווג הפוליסות שהונפקו מ-2004 "
                       f"ומספר המסלולים המדווחים הוכפל, כך שסכומים מוקדמים יותר אינם ברי השוואה. "
                       f"סכומים במיליארדי ₪, תשואות נומינליות ברוטו. סוג המסלול נגזר משם המסלול."),
        "assets_aria": f"גרף שטח: סך הנכסים לפי דור הפוליסות, {p_he(first)} עד {p_he(last)}.",
        "insurers_aria": f"תרשים עמודות: נכסים לפי חברת ביטוח ב{p_he(last)}, במיליארדי ₪.",
        "annual_aria": f"תרשים עמודות: תשואה שנתית משוקללת לכל שנה קלנדרית מלאה מאז {first // 100}.",
        "vintage_aria": f"תרשים עמודות: תשואה מתחילת השנה ול-5 שנים לפי דור הפוליסות, {p_he(last)}.",
        "types_aria": f"תרשים עמודות: נכסים לפי סוג מסלול, {p_he(last)}, במיליארדי ₪.",
        "type_yield_aria": f"תרשים עמודות: תשואה מתחילת השנה ול-5 שנים לפי סוג מסלול, {p_he(last)}.",
        "yields_aria": f"תרשים עמודות: תשואה חודשית משוקללת ב-{len(recent_y)} החודשים האחרונים.",
        "rolling_aria": "גרף קו: תשואה מצטברת ל-12 חודשים מתגלגלים, משוקללת לפי נכסים.",
        "fees_aria": "גרף קווים: דמי ניהול ממוצעים מצבירה ומהפקדה לפי שנה, משוקללים לפי נכסים.",
        "fees_note": ("ממוצע שנתי של הממוצע החודשי המשוקלל לפי נכסים. דמי ניהול מהפקדה מדווחים "
                      "רק בחלק מהמסלולים." + (f" {partial_year} — שנה חלקית." if partial_year else "")),
        "tracks_aria": f"תרשים עמודות: תשואה מתחילת השנה של {len(tracks)} המסלולים הגדולים.",
        "exposure_aria": f"גרף קווים: חשיפה למניות, לחו״ל ולמט״ח כאחוז מהנכסים, עד {p_he(last)}.",
        "exposure_note": (f"שיעור החשיפה מסך הנכסים, משוקלל לפי נכסים, מאז שהחל הדיווח עליה. "
                          f"המסלולים שנכללו מחזיקים לפחות {pct(exp_cover * 100)} מהנכסים בכל מדד."),
        "risk_aria": (f"תרשים פיזור: {len(risk)} מסלולים עם נתוני 5 שנים — סטיית תקן מול תשואה "
                      f"שנתית ממוצעת, לפי סוג מסלול."),
        "risk_note": (f"כל נקודה היא מסלול ({len(risk)} מסלולים עם היסטוריה של 5 שנים, נכון "
                      f"ל{p_he(last)}), בצבע לפי סוג המסלול; גודל הנקודה לפי נכסים."),
        "ins_yield_aria": "תרשים עמודות: תשואה שנתית ממוצעת ל-3 ול-5 שנים לפי חברת ביטוח.",
        "insurers_caption": f"נכסים ונתח שוק לפי חברת ביטוח, {p_he(last)}.",
        "annual_caption": "תשואה שנתית משוקללת לפי שנה קלנדרית מלאה.",
        "vintage_caption": f"נכסים ותשואות לפי דור הפוליסות, {p_he(last)}.",
        "types_caption": f"מסלולים, נכסים ותשואות לפי סוג מסלול, {p_he(last)}.",
        "fees_caption": "דמי ניהול ממוצעים מצבירה ומהפקדה לפי שנה.",
        "tracks_caption": f"תשואה מתחילת השנה ונכסים של המסלולים הגדולים, {p_he(last)}.",
        "exposure_caption": "שיעור החשיפה בסוף כל שנה (או בחודש האחרון של שנה חלקית).",
        "ins_yield_caption": "תשואה שנתית ממוצעת לפי חברת ביטוח, משוקללת לפי נכסים.",
    }

    return {
        "agent_data": {
            "summary_he": (f"נתוני ביטוח-נט: דיווח חודשי על {n_tracks:,} מסלולי השקעה של פוליסות "
                           f"ביטוח חיים משתתפות ברווחים — נכסים, תשואות, דמי ניהול וחשיפות. סך "
                           f"הנכסים ב{p_he(last)}: {bn(assets[last])}."),
            "dataset_kind": "timeseries",
            "related_ids": ["3a1ca8fa-738b-4890-b52f-e8f7ce1e6145",
                            "5265b154-c2e2-4f3d-a22e-fba593240d9a"],
            "suggested_tags": ["ביטוח חיים", "חיסכון", "חברות ביטוח", "תשואות", "דמי ניהול"],
            "temporal_coverage": f"{p_iso(first)}/{p_iso(last)}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
