"""פנסיה-נט — monthly reports of every Israeli pension-fund investment track.

The table is published as one CSV per period (1999–2022, 2023, 2024–now);
a new period file is picked up automatically via `by_schema` + concat.
Per the dataset's field dictionary: amounts are in ₪ millions, yields are
nominal gross, and until 12/2016 rows were reported at BOTH fund and track
level — summing assets across that era double-counts, so every aggregate
here starts at FROM_PERIOD (track-level only), and the page says so.
"""
import pandas as pd

FROM_PERIOD = 201701
TOP_MANAGERS = 8
TOP_TRACKS = 10
RECENT_MONTHS = 36
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
LRI, PDI = "⁦", "⁩"


def p_he(rp):
    return f"{MONTHS_HE[rp % 100 - 1]} {rp // 100}"


def p_iso(rp):
    return f"{rp // 100}-{rp % 100:02d}"


def bn(millions):
    """₪ millions → '1,307.7 מיליארד ₪'."""
    return f"{millions / 1000:,.1f} מיליארד ₪"


def pct(v, digits=1, signed=False):
    s = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return f"{LRI}{s}%{PDI}"


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
        "rp": _num(df["REPORT_PERIOD"]),
        "assets": _num(df["TOTAL_ASSETS"]),
        "y": _num(df["MONTHLY_YIELD"]),
        "ytd": _num(df["YEAR_TO_DATE_YIELD"]),
        "mfee": _num(df["AVG_ANNUAL_MANAGEMENT_FEE"]),
        "dfee": _num(df["AVG_DEPOSIT_FEE"]),
        "net": _num(df["NET_MONTHLY_DEPOSITS"]),
        "src": df["_resource_name"],
    })
    out = out.dropna(subset=["rp"])
    out["rp"] = out["rp"].astype(int)
    out = out[(out["rp"] >= FROM_PERIOD) & (out["fund"] != "")]
    # A track-month appearing in two period files: keep one, deterministically.
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


def _prev_year(rp):
    return rp - 100


def insight_growth(assets, last):
    prev = _prev_year(last)
    if prev not in assets.index or assets[prev] <= 0:
        return None
    chg = assets[last] / assets[prev] - 1
    if abs(chg) < 0.01:
        return f"סך הנכסים ({bn(assets[last])}) כמעט לא השתנה לעומת {p_he(prev)}."
    word = "גדל" if chg > 0 else "קטן"
    return (f"סך הנכסים בקרנות הפנסיה {word} ב-{pct(abs(chg) * 100)} בשנה — "
            f"מ-{bn(assets[prev])} ב{p_he(prev)} ל-{bn(assets[last])} ב{p_he(last)}.")


def insight_leader(shares):
    if shares.empty:
        return None
    top, share = shares.index[0], shares.iloc[0]
    top3 = shares.head(3).sum()
    if share < 0.15:
        return (f"אין מנהל דומיננטי: שלושת הגדולים מנהלים יחד {pct(top3 * 100)} "
                f"מהנכסים.")
    return (f"{top} מנהלת {pct(share * 100)} מנכסי הפנסיה, ושלושת הגופים הגדולים "
            f"יחד — {pct(top3 * 100)}.")


def insight_return(wy, last):
    want = []
    rp = last
    for _ in range(12):
        want.append(rp)
        rp = rp - 1 if rp % 100 != 1 else rp - 89  # 202601 → 202512
    if not all(r in wy.index for r in want):
        return None
    vals = [wy[r] for r in want]
    comp = 1.0
    for v in vals:
        comp *= 1 + v / 100
    neg = sum(v < 0 for v in vals)
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


def insight_net(net_m, last):
    tail = net_m[net_m.index <= last].tail(12)
    if len(tail) < 12:
        return None
    s = tail.sum()
    if s >= 0:
        return (f"ב-12 החודשים האחרונים נכנסו לקרנות {bn(s)} נטו "
                f"(הפקדות פחות משיכות והעברות).")
    return (f"ב-12 החודשים האחרונים יצאו מהקרנות {bn(-s)} נטו "
            f"(משיכות והעברות עלו על ההפקדות).")


def insight_classes(cls_last):
    tot = cls_last.sum()
    if tot <= 0 or "קרנות חדשות" not in cls_last.index:
        return None
    share = cls_last["קרנות חדשות"] / tot
    return (f"הקרנות החדשות (המקיפות) מחזיקות {pct(share * 100)} מסך הנכסים; "
            f"היתר בקרנות הכלליות (המשלימות).")


def compute(frames):
    df = _prepare(frames["reports"])
    last = int(df["rp"].max())
    cur = df[df["rp"] == last]

    assets = df.groupby("rp")["assets"].sum().sort_index()
    by_cls = df.pivot_table(index="rp", columns="cls", values="assets",
                            aggfunc="sum").sort_index().fillna(0)
    by_cls = by_cls[sorted(by_cls.columns)]
    wy = _weighted(df, "y")
    mfee = _weighted(df, "mfee")
    dfee = _weighted(df, "dfee")
    net_m = df.dropna(subset=["net"]).groupby("rp")["net"].sum().sort_index()

    mgr = (cur.groupby("manager")["assets"].sum().sort_index()
              .sort_values(ascending=False, kind="stable"))
    shares = mgr / mgr.sum()
    top_m = mgr.head(TOP_MANAGERS)
    other = mgr.iloc[TOP_MANAGERS:].sum()

    partial_year = last // 100 if last % 100 != 12 else None
    mfee_y = mfee.groupby(mfee.index // 100).mean()
    dfee_y = dfee.groupby(dfee.index // 100).mean()

    # rolling 12-month compounded return
    roll = []
    periods = list(wy.index)
    for i in range(11, len(periods)):
        win = periods[i - 11:i + 1]
        if (win[-1] // 100 - win[0] // 100) * 12 + (win[-1] % 100 - win[0] % 100) != 11:
            continue
        comp = 1.0
        for r in win:
            comp *= 1 + wy[r] / 100
        roll.append((win[-1], round((comp - 1) * 100, 2)))

    tracks = (cur.dropna(subset=["ytd"]).sort_values(["assets", "fund"], ascending=[False, True])
                 .head(TOP_TRACKS))

    recent_y = wy.tail(RECENT_MONTHS)
    recent_n = net_m.tail(RECENT_MONTHS)

    charts = {
        "assets": {
            "x": [p_iso(r) for r in by_cls.index],
            "series": [{"name": c, "data": [round(v / 1000, 1) for v in by_cls[c]]}
                       for c in by_cls.columns],
        },
        "managers": {
            "names": [*top_m.index, *(["אחר"] if other > 0 else [])],
            "values": [round(v / 1000, 1) for v in [*top_m.values, *([other] if other > 0 else [])]],
        },
        "yields": {"x": [p_iso(r) for r in recent_y.index],
                   "y": [round(v, 2) for v in recent_y.values]},
        "rolling": {"x": [p_iso(r) for r, _ in roll], "y": [v for _, v in roll]},
        "fees": {"x": [str(int(y)) for y in mfee_y.index],
                 "mgmt": [round(v, 3) for v in mfee_y.values],
                 "deposit": [round(dfee_y.get(y), 3) if y in dfee_y.index else None
                             for y in mfee_y.index]},
        "net": {"x": [p_iso(r) for r in recent_n.index],
                "y": [round(v / 1000, 2) for v in recent_n.values]},
        "tracks": {"names": list(tracks["name"]),
                   "values": [round(v, 2) for v in tracks["ytd"]]},
    }

    rules = [
        ("growth", insight_growth(assets, last)),
        ("leader", insight_leader(shares)),
        ("return", insight_return(wy, last)),
        ("fees", insight_fees(mfee_y, partial_year)),
        ("net", insight_net(net_m, last)),
        ("classes", insight_classes(cur.groupby("cls")["assets"].sum())),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    last_y = wy.get(last)
    kpis = {
        "assets": {"value": float(assets[last]), "display": bn(assets[last])},
        "tracks": {"value": int(cur["fund"].nunique()), "display": f"{cur['fund'].nunique():,}"},
        "managers": {"value": int(mgr.size), "display": f"{mgr.size:,}"},
        "month_yield": {"value": None if last_y is None else float(last_y),
                        "display": "—" if last_y is None else pct(last_y, 2, signed=True)},
    }

    table = [{"name": n, "assets": bn(v), "share": pct(v / mgr.sum() * 100)}
             for n, v in mgr.items()]

    labels = {
        "period": p_he(last),
        "lede": (f"דיווחים חודשיים של {cur['fund'].nunique():,} מסלולי השקעה ב-{mgr.size} "
                 f"גופים מנהלים, נכון ל{p_he(last)}. סך הנכסים: {bn(assets[last])}."),
        "scope_note": (f"הנתונים מ{p_he(FROM_PERIOD)} ואילך — עד סוף 2016 דווחו נכסים גם "
                       f"ברמת קרן וגם ברמת מסלול, וסכימה שלהם הייתה כופלת. סכומים במיליארדי ₪, "
                       f"תשואות נומינליות ברוטו."),
        "assets_aria": (f"גרף שטח: סך נכסי קרנות הפנסיה לפי סוג קרן, {p_he(FROM_PERIOD)} "
                        f"עד {p_he(last)}, במיליארדי ₪."),
        "managers_aria": f"תרשים עמודות: נכסים לפי גוף מנהל ב{p_he(last)}, במיליארדי ₪.",
        "yields_aria": (f"תרשים עמודות: תשואה חודשית משוקללת ב-{len(recent_y)} החודשים "
                        f"האחרונים; חודשים שליליים באדום."),
        "rolling_aria": "גרף קו: תשואה מצטברת ל-12 חודשים מתגלגלים, משוקללת לפי נכסים.",
        "fees_aria": "גרף קווים: דמי ניהול ממוצעים מצבירה ומהפקדה לפי שנה, משוקללים לפי נכסים.",
        "fees_note": ("ממוצע שנתי של הממוצע החודשי המשוקלל."
                      + (f" {partial_year} — שנה חלקית." if partial_year else "")),
        "net_aria": (f"תרשים עמודות: הפקדות נטו חודשיות ב-{len(recent_n)} החודשים "
                     f"האחרונים, במיליארדי ₪."),
        "tracks_aria": (f"תרשים עמודות: תשואה מתחילת השנה של {len(tracks)} המסלולים "
                        f"הגדולים ב{p_he(last)}."),
        "table_caption": f"נכסים ונתח שוק לפי גוף מנהל, {p_he(last)}.",
    }

    return {
        "agent_data": {
            "summary_he": (f"נתוני פנסיה-נט: דיווח חודשי על {cur['fund'].nunique():,} מסלולי "
                           f"קרנות פנסיה — נכסים, תשואות, דמי ניהול והפקדות. סך הנכסים "
                           f"ב{p_he(last)}: {bn(assets[last])}."),
            "dataset_kind": "timeseries",
            "related_ids": ["5265b154-c2e2-4f3d-a22e-fba593240d9a",
                            "b5dd1f5e-0566-42fd-8db9-ae12e10c445b",
                            "f15932ed-a034-40ee-b713-b0847ecf5559"],
            "suggested_tags": ["פנסיה", "חיסכון פנסיוני", "דמי ניהול", "תשואות", "שוק ההון"],
            "temporal_coverage": f"{p_iso(FROM_PERIOD)}/{p_iso(last)}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": {"managers": table},
        "insights": insights,
        "labels": labels,
    }
