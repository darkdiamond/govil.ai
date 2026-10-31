"""Audited financial reports of Israel's local authorities, one file per report year.

Each yearly resource is a long (EAV) table: one row per cell of every sheet of
every authority's audited report (~1M rows per year). The page reads only the
"דוח לתושב" (report to the resident) cells and two cells of "נתונים כלליים",
identified by their mapping code, which has been stable across all report
years. Each code exists twice: the report year ("current") and the previous
year as restated in that report ("prior"). A year's value comes from its own
report when there is one, else from the next year's report (prior column), so
a year with no file of its own (e.g. 2021) still appears.

Amounts in the source are thousands of NIS; ratios are fractions.
"""
import math

import pandas as pd

# metric -> (current-year code, prior-year code). Codes are the publisher's
# stable mapping codes ("קוד" / "קוד_מיפוי"); a code missing from a year's
# file just leaves that metric empty for that year.
METRICS = {
    "inc_own": ("2988", "2990"),
    "inc_edu": ("2993", "2995"),
    "inc_welf": ("2998", "3000"),
    "inc_other_old": ("3003", "3005"),   # until 2019
    "inc_other": ("38063", "38065"),     # from 2022, incl. arnona compensation
    "inc_grants": ("3008", "3010"),
    "inc_total": ("3013", "3015"),
    "exp_sal": ("3018", "3020"),
    "exp_ops": ("3023", "3025"),
    "exp_edu_sal": ("3028", "3030"),
    "exp_edu_ops": ("3033", "3035"),
    "exp_welf_sal": ("3038", "3040"),
    "exp_welf_ops": ("3043", "3045"),
    "exp_fin": ("3048", "3050"),
    "exp_loan": ("3053", "3055"),
    "exp_total": ("3058", "3060"),
    "result": ("3063", "3064"),
    "pct_acc_def": ("3067", "3068"),
    "pct_loan": ("3069", "3070"),
    "per_capita": ("3073", "3074"),
    "positions": ("3075", "3076"),
    "acc_def": ("3091", "3092"),
    "pct_collect": ("3125", "3126"),
    "pct_arrears": ("6542", "6543"),
    "arn_m2": ("3129", "3130"),
    "population": ("43192", "43191"),
    "socio": ("43195", None),
}
CODE_MAP = {}
for _m, (_c, _p) in METRICS.items():
    CODE_MAP[_c] = (_m, 1)
    if _p:
        CODE_MAP[_p] = (_m, 0)

INCOME_PARTS = [
    ("inc_own", "הכנסות עצמיות"),
    ("inc_edu", "משרד החינוך"),
    ("inc_welf", "משרד הרווחה"),
    ("inc_grants", "מענקים"),
    ("inc_other", "משרדי ממשלה אחרים"),
]
EXPENSE_PARTS = [
    ("x_edu", "חינוך (שכר ופעולות)"),
    ("exp_ops", "פעולות כלליות"),
    ("exp_sal", "משכורות ושכר כללי"),
    ("x_welf", "רווחה (שכר ופעולות)"),
    ("x_debt", "מימון ופירעון מלוות"),
]
MINUS = "−"
TOP_N = 15
CHUNK = 90  # authorities per JSON island (keeps each <script> well under 50KB)


# ---------------------------------------------------------------- helpers
def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _int(v):
    return f"{int(round(v)):,}"


def _signed(v, digits=1):
    s = f"{abs(v):,.{digits}f}"
    return (MINUS + s) if v < 0 and round(abs(v), digits) != 0 else s


def _pct(frac, digits=1):
    return f"{frac * 100:.{digits}f}%"


def _bn(thousands):
    return thousands / 1e6


def _mn(thousands):
    return thousands / 1e3


def _r(v, d):
    v = _num(v)
    return None if v is None else round(v, d)


def _load(frames):
    parts = []
    for name in ("recent", "y2019"):
        df = frames.get(name)
        if df is None or df.empty:
            continue
        code_col = next(c for c in ("קוד", "קוד_מיפוי") if c in df.columns)
        code = df[code_col].str.strip().str.replace(r"\.0+$", "", regex=True)
        keep = code.isin(CODE_MAP.keys())
        sub = pd.DataFrame({
            "name": df.loc[keep, "שם_רשות"].str.strip(),
            "year": pd.to_numeric(df.loc[keep, "שנת_נתונים"].str.strip(), errors="coerce"),
            "code": code[keep],
            "value": pd.to_numeric(df.loc[keep, "ערך"].str.strip().str.replace(",", "", regex=False),
                                   errors="coerce"),
        })
        parts.append(sub)
    long = pd.concat(parts, ignore_index=True)
    long = long.dropna(subset=["year", "value"])
    long = long[long["name"] != ""]
    long["year"] = long["year"].astype(int)
    long["metric"] = long["code"].map(lambda c: CODE_MAP[c][0])
    long["cur"] = long["code"].map(lambda c: CODE_MAP[c][1])
    # Own report first; ties (a year published twice) break on value.
    long = long.sort_values(["name", "year", "metric", "cur", "value"],
                            ascending=[True, True, True, False, True], kind="stable")
    long = long.drop_duplicates(["name", "year", "metric"], keep="first")
    wide = long.pivot(index=["name", "year"], columns="metric", values="value")
    for m in METRICS:
        if m not in wide.columns:
            wide[m] = float("nan")
    wide["inc_other"] = wide["inc_other"].fillna(wide["inc_other_old"])
    wide["x_edu"] = wide["exp_edu_sal"].add(wide["exp_edu_ops"], fill_value=0)
    wide["x_welf"] = wide["exp_welf_sal"].add(wide["exp_welf_ops"], fill_value=0)
    wide["x_debt"] = wide["exp_fin"].add(wide["exp_loan"], fill_value=0)
    wide = wide.reset_index().sort_values(["year", "name"], kind="stable").reset_index(drop=True)
    # A row without both totals is not a usable report.
    wide = wide.dropna(subset=["inc_total", "exp_total"])
    return wide


def _pos(s):
    """Ratios reported as 0 mean "not reported" for collection/per-capita."""
    return s[s > 0]


def _median(s):
    s = s.dropna()
    return float(s.median()) if len(s) else None


# ---------------------------------------------------------------- insights
def ins_balance(nat, latest, prev):
    r = nat[latest]
    inc, exp, res = r["inc"], r["exp"], r["res"]
    word = "גירעון מצרפי" if res < 0 else "עודף מצרפי"
    s = (f"ב-{latest} דיווחו {r['n']:,} רשויות על הכנסות של {_bn(inc):,.1f} מיליארד ₪ "
         f"והוצאות של {_bn(exp):,.1f} מיליארד ₪, {word} של {abs(_mn(res)):,.1f} מיליון ₪ בתקציב הרגיל. "
         f"{r['deficit']:,} רשויות סיימו את השנה בגירעון ו-{r['surplus']:,} בעודף")
    if prev is not None:
        p = nat[prev]
        if p["deficit"] != r["deficit"]:
            more = "יותר" if r["deficit"] > p["deficit"] else "פחות"
            s += f" ({more} מאשר ב-{prev}, אז {p['deficit']:,})"
    return s + "."


def ins_acc_def(nat, years, top_acc):
    first, last = years[0], years[-1]
    a0, a1 = nat[first]["acc"], nat[last]["acc"]
    if a0 <= 0 or a1 <= 0:
        return None
    ch = a1 / a0 - 1
    if abs(ch) < 0.05:
        trend = f"כמעט ללא שינוי לעומת {first} ({_bn(a0):,.2f} מיליארד ₪)"
    else:
        trend = f"{'עלייה' if ch > 0 else 'ירידה'} של {abs(ch) * 100:.0f}% לעומת {first} ({_bn(a0):,.2f} מיליארד ₪)"
    s = f"הגירעון המצטבר בתקציב הרגיל של כלל הרשויות הגיע ב-{last} ל-{_bn(a1):,.2f} מיליארד ₪, {trend}"
    if len(top_acc) >= 2 and top_acc[0]["v"] >= 0.3:
        s += (f". השיעור הגבוה ביותר מן ההכנסה: {top_acc[0]['name']} ({_pct(top_acc[0]['v'])}) "
              f"ו{top_acc[1]['name']} ({_pct(top_acc[1]['v'])})")
    return s + "."


def ins_collect(cur, latest):
    s = _pos(cur.set_index("name")["pct_collect"].dropna())
    if len(s) < 10:
        return None
    s = s.sort_index().sort_values(kind="stable")
    med = float(s.median())
    lo, hi = s.index[0], s.index[-1]
    zeros = int((cur["pct_collect"] == 0).sum())
    note = ""
    if zeros == 1:
        note = " (רשות אחת שדיווחה שיעור אפס אינה נכללת)"
    elif zeros > 1:
        note = f" ({zeros:,} רשויות שדיווחו שיעור אפס אינן נכללות)"
    return (f"חציון שיעור גביית הארנונה מהחיוב השוטף ב-{latest} הוא {_pct(med)}, אך הפער בין הרשויות גדול: "
            f"מ-{_pct(s.iloc[0])} ב{lo} ועד {_pct(s.iloc[-1])} ב{hi}{note}.")


def ins_loan(med_loan, years):
    pts = [(y, med_loan[y]) for y in years if med_loan.get(y) is not None]
    if len(pts) < 2:
        return None
    (y0, v0), (y1, v1) = pts[0], pts[-1]
    d = (v1 - v0) * 100
    if abs(d) < 1:
        return (f"עומס המלוות החציוני נותר יציב: {_pct(v0)} מההכנסה ב-{y0} לעומת {_pct(v1)} ב-{y1}.")
    word = "ירד" if d < 0 else "עלה"
    return (f"עומס המלוות החציוני {word} מ-{_pct(v0)} מההכנסה ב-{y0} ל-{_pct(v1)} ב-{y1} "
            f"({abs(d):.1f} נקודות אחוז).")


def ins_per_capita(med_pc, years):
    pts = [(y, med_pc[y]) for y in years if med_pc.get(y)]
    if len(pts) < 2:
        return None
    (y0, v0), (y1, v1) = pts[0], pts[-1]
    ch = v1 / v0 - 1
    if abs(ch) < 0.02:
        return None
    word = "עלתה" if ch > 0 else "ירדה"
    return (f"ההוצאה החציונית לתושב {word} מ-{_int(v0)} ₪ ב-{y0} ל-{_int(v1)} ₪ ב-{y1} "
            f"({'עלייה' if ch > 0 else 'ירידה'} של {abs(ch) * 100:.0f}%, במחירים שוטפים).")


def ins_edu(exp_mix, years):
    y0, y1 = years[0], years[-1]
    e0, e1 = exp_mix[y0].get("x_edu"), exp_mix[y1].get("x_edu")
    t0, t1 = exp_mix[y0]["total"], exp_mix[y1]["total"]
    if not e0 or not e1 or not t0 or not t1:
        return None
    ch = e1 / e0 - 1
    return (f"חינוך הוא סעיף ההוצאה הגדול: {_bn(e1):,.1f} מיליארד ₪ ב-{y1} ({_pct(e1 / t1)} מההוצאות), "
            f"לעומת {_bn(e0):,.1f} מיליארד ₪ ב-{y0} ({'עלייה' if ch >= 0 else 'ירידה'} של {abs(ch) * 100:.0f}%).")


def ins_own(inc_mix, years):
    y0, y1 = years[0], years[-1]
    o0, o1 = inc_mix[y0].get("inc_own"), inc_mix[y1].get("inc_own")
    t0, t1 = inc_mix[y0]["total"], inc_mix[y1]["total"]
    if not o0 or not o1 or not t0 or not t1:
        return None
    s0, s1 = o0 / t0, o1 / t1
    d = (s1 - s0) * 100
    if abs(d) < 1:
        tail = f"כמעט ללא שינוי לעומת {y0} ({_pct(s0)})"
    else:
        tail = f"{'עלייה' if d > 0 else 'ירידה'} של {abs(d):.1f} נקודות אחוז לעומת {y0} ({_pct(s0)})"
    return (f"הכנסות עצמיות (ארנונה, אגרות ושירותים) מימנו ב-{y1} {_pct(s1)} מתקציב הרשויות, {tail}. "
            f"השאר הגיע ממשרדי הממשלה וממענקים.")


def ins_socio(socio_rows):
    lo = [r for r in socio_rows if r["rank"] <= 4]
    hi = [r for r in socio_rows if r["rank"] >= 7]
    nl, nh = sum(r["n"] for r in lo), sum(r["n"] for r in hi)
    if nl < 10 or nh < 10:
        return None
    dl = sum(r["deficit"] for r in lo) / nl
    dh = sum(r["deficit"] for r in hi) / nh
    if abs(dl - dh) < 0.10:
        return None
    more = "נמוך" if dl > dh else "גבוה"
    return (f"רשויות בדירוג חברתי-כלכלי {more} נוטות יותר לגירעון שוטף: {_pct(dl, 0)} מהרשויות בדירוג 1-4 "
            f"({nl:,}) סיימו בגירעון, לעומת {_pct(dh, 0)} מהרשויות בדירוג 7-10 ({nh:,}).")


def ins_switch(wide, latest, prev):
    if prev is None:
        return None
    a = wide[wide["year"] == prev].set_index("name")["result"]
    b = wide[wide["year"] == latest].set_index("name")["result"]
    both = pd.concat([a, b], axis=1, keys=["a", "b"], join="inner").dropna()
    if len(both) < 20:
        return None
    to_def = int(((both["a"] >= 0) & (both["b"] < 0)).sum())
    to_sur = int(((both["a"] < 0) & (both["b"] >= 0)).sum())
    if to_def + to_sur == 0:
        return None
    return (f"בין {prev} ל-{latest} עברו {to_def:,} רשויות מאיזון או עודף לגירעון שוטף, "
            f"ו-{to_sur:,} רשויות יצאו מגירעון (מתוך {len(both):,} שדיווחו בשתי השנים).")


# ---------------------------------------------------------------- compute
def compute(frames):
    wide = _load(frames)
    counts = wide.groupby("year")["name"].nunique().sort_index()
    # A year counts once at least half the usual number of authorities reported.
    full = counts[counts >= counts.max() * 0.5]
    years = [int(y) for y in full.index]
    wide = wide[wide["year"].isin(years)]
    latest = years[-1]
    prev = years[-2] if len(years) >= 2 else None
    gaps = [y for y in range(years[0], latest + 1) if y not in years]

    nat, inc_mix, exp_mix = {}, {}, {}
    med_collect, med_loan, med_pc, pc_band = {}, {}, {}, {}
    for y in years:
        g = wide[wide["year"] == y]
        nat[y] = {
            "n": int(g["name"].nunique()),
            "inc": float(g["inc_total"].sum()),
            "exp": float(g["exp_total"].sum()),
            "res": float(g["result"].sum()),
            "acc": float(g["acc_def"].sum()),
            "deficit": int((g["result"] < 0).sum()),
            "surplus": int((g["result"] > 0).sum()),
            "balanced": int((g["result"] == 0).sum()),
        }
        inc_mix[y] = {k: float(g[k].sum()) for k, _ in INCOME_PARTS}
        inc_mix[y]["total"] = nat[y]["inc"]
        exp_mix[y] = {k: float(g[k].sum()) for k, _ in EXPENSE_PARTS}
        exp_mix[y]["total"] = nat[y]["exp"]
        med_collect[y] = _median(_pos(g["pct_collect"]))
        med_loan[y] = _median(g["pct_loan"])
        pc = _pos(g["per_capita"]).dropna()
        med_pc[y] = float(pc.median()) if len(pc) else None
        pc_band[y] = ([float(pc.quantile(0.25)), float(pc.median()), float(pc.quantile(0.75))]
                      if len(pc) >= 10 else None)

    cur = wide[wide["year"] == latest].sort_values("name", kind="stable").reset_index(drop=True)
    ylab = [str(y) for y in years]

    # --- top lists (latest year)
    def top(col, n=TOP_N, positive=True):
        s = cur.set_index("name")[col].dropna()
        if positive:
            s = s[s > 0]
        s = s.sort_index().sort_values(ascending=False, kind="stable").head(n)
        return [{"name": k, "v": float(v)} for k, v in s.items()]

    top_acc = top("pct_acc_def")
    acc_amt = cur.set_index("name")["acc_def"]
    top_inc = top("inc_total")
    exp_by = cur.set_index("name")["exp_total"]

    # --- collection histogram
    bins = [(0.0, 0.5, "מתחת ל-50%"), (0.5, 0.7, "50%-70%"), (0.7, 0.8, "70%-80%"),
            (0.8, 0.85, "80%-85%"), (0.85, 0.9, "85%-90%"), (0.9, 0.95, "90%-95%"),
            (0.95, 1.0001, "95% ומעלה")]
    col = _pos(cur["pct_collect"]).dropna()
    hist = [{"label": lab, "n": int(((col >= a) & (col < b)).sum())} for a, b, lab in bins]
    cs = cur.set_index("name")["pct_collect"].dropna()
    cs = cs[cs > 0].sort_index()
    low10 = [{"name": k, "v": _pct(v)} for k, v in cs.sort_values(kind="stable").head(10).items()]
    high10 = [{"name": k, "v": _pct(v)} for k, v in cs.sort_values(ascending=False, kind="stable").head(10).items()]
    zero_collect = int((cur["pct_collect"] == 0).sum())

    # --- socio-economic rank (only years whose report carries it)
    socio_rows = []
    so = cur.dropna(subset=["socio"])
    so = so[(so["socio"] >= 1) & (so["socio"] <= 10)]
    unranked = int(len(cur) - len(so))
    if len(so) >= len(cur) * 0.5:
        for rank, g in so.groupby(so["socio"].round().astype(int)):
            socio_rows.append({
                "rank": int(rank), "n": int(len(g)),
                "deficit": int((g["result"] < 0).sum()),
                "deficit_share": round(float((g["result"] < 0).mean()) * 100, 1),
                "collect": _r((_median(_pos(g["pct_collect"])) or 0) * 100, 1),
                "pc": _r(_median(_pos(g["per_capita"])) or 0, 0),
            })
        socio_rows.sort(key=lambda r: r["rank"])

    # --- authority profiles (lookup)
    profiles = []
    for name, g in wide.groupby("name", sort=True):
        g = g.set_index("year")
        last = g.loc[g.index.max()]
        def ser(colname):
            return [_r(_mn(g.loc[y, colname]), 1) if y in g.index and pd.notna(g.loc[y, colname]) else None
                    for y in years]
        inc_own_share = (last["inc_own"] / last["inc_total"]) if last["inc_total"] else None
        profiles.append({
            "n": name, "y": int(g.index.max()),
            "inc": ser("inc_total"), "exp": ser("exp_total"), "res": ser("result"),
            "pc": _r(last["per_capita"], 0), "col": _r(last["pct_collect"], 4),
            "loan": _r(last["pct_loan"], 4), "acc": _r(last["pct_acc_def"], 4),
            "accm": _r(_mn(last["acc_def"]), 1) if pd.notna(last["acc_def"]) else None,
            "own": _r(inc_own_share, 4), "pop": _r(last["population"], 0),
            "soc": _r(last["socio"], 0), "pos": _r(last["positions"], 0),
        })
    chunks = [profiles[i:i + CHUNK] for i in range(0, len(profiles), CHUNK)]

    # --- all-authorities table (latest year)
    all_rows = []
    for _, r in cur.iterrows():
        res = r["result"]
        all_rows.append({
            "name": r["name"],
            "inc": f"{_mn(r['inc_total']):,.1f}",
            "exp": f"{_mn(r['exp_total']):,.1f}",
            "res": _signed(_mn(res)) if pd.notna(res) else "-",
            "pc": _int(r["per_capita"]) if pd.notna(r["per_capita"]) and r["per_capita"] > 0 else "-",
            "col": _pct(r["pct_collect"]) if pd.notna(r["pct_collect"]) and r["pct_collect"] > 0 else "-",
            "acc": _pct(r["pct_acc_def"]) if pd.notna(r["pct_acc_def"]) else "-",
            "loan": _pct(r["pct_loan"]) if pd.notna(r["pct_loan"]) else "-",
        })

    # --- charts
    charts = {
        "years": ylab,
        "national": {
            "inc": [round(_bn(nat[y]["inc"]), 2) for y in years],
            "exp": [round(_bn(nat[y]["exp"]), 2) for y in years],
            "res": [round(_mn(nat[y]["res"]), 1) for y in years],
        },
        "balance": {
            "surplus": [nat[y]["surplus"] for y in years],
            "deficit": [nat[y]["deficit"] for y in years],
            "balanced": [nat[y]["balanced"] for y in years],
        },
        "income": [{"name": lab, "data": [round(_bn(inc_mix[y][k]), 2) for y in years]} for k, lab in INCOME_PARTS],
        "expense": [{"name": lab, "data": [round(_bn(exp_mix[y][k]), 2) for y in years]} for k, lab in EXPENSE_PARTS],
        "health": {
            "collect": [_r(med_collect[y] * 100, 1) if med_collect[y] is not None else None for y in years],
            "loan": [_r(med_loan[y] * 100, 1) if med_loan[y] is not None else None for y in years],
            "acc": [round(nat[y]["acc"] / nat[y]["inc"] * 100, 1) if nat[y]["inc"] else None for y in years],
        },
        "pc": {
            "p25": [_r(pc_band[y][0], 0) if pc_band[y] else None for y in years],
            "med": [_r(pc_band[y][1], 0) if pc_band[y] else None for y in years],
            "p75": [_r(pc_band[y][2], 0) if pc_band[y] else None for y in years],
        },
        "top_acc": {"names": [t["name"] for t in top_acc], "v": [round(t["v"] * 100, 1) for t in top_acc]},
        "top_inc": {"names": [t["name"] for t in top_inc], "v": [round(_mn(t["v"]), 1) for t in top_inc]},
        "hist": {"labels": [h["label"] for h in hist], "n": [h["n"] for h in hist]},
        "socio": socio_rows,
    }

    tables = {
        "national": [{
            "y": str(y), "n": f"{nat[y]['n']:,}",
            "inc": f"{_bn(nat[y]['inc']):,.2f}", "exp": f"{_bn(nat[y]['exp']):,.2f}",
            "res": _signed(_mn(nat[y]["res"])),
            "surplus": f"{nat[y]['surplus']:,}", "deficit": f"{nat[y]['deficit']:,}",
            "balanced": f"{nat[y]['balanced']:,}",
        } for y in years],
        "income": [{"y": str(y), "v": [f"{_bn(inc_mix[y][k]):,.2f}" for k, _ in INCOME_PARTS],
                    "own_share": _pct(inc_mix[y]["inc_own"] / inc_mix[y]["total"]) if inc_mix[y]["total"] else "-"}
                   for y in years],
        "expense": [{"y": str(y), "v": [f"{_bn(exp_mix[y][k]):,.2f}" for k, _ in EXPENSE_PARTS]} for y in years],
        "income_cols": [lab for _, lab in INCOME_PARTS],
        "expense_cols": [lab for _, lab in EXPENSE_PARTS],
        "health": [{
            "y": str(y),
            "collect": _pct(med_collect[y]) if med_collect[y] is not None else "-",
            "loan": _pct(med_loan[y]) if med_loan[y] is not None else "-",
            "acc": f"{nat[y]['acc'] / nat[y]['inc'] * 100:.1f}%" if nat[y]["inc"] else "-",
            "acc_bn": f"{_bn(nat[y]['acc']):,.2f}",
        } for y in years],
        "pc": [{"y": str(y), "p25": _int(pc_band[y][0]), "med": _int(pc_band[y][1]), "p75": _int(pc_band[y][2])}
               for y in years if pc_band[y]],
        "top_acc": [{"name": t["name"], "pct": _pct(t["v"]),
                     "amt": f"{_mn(acc_amt.get(t['name'], 0)):,.1f}"} for t in top_acc],
        "top_inc": [{"name": t["name"], "inc": f"{_mn(t['v']):,.1f}",
                     "exp": f"{_mn(exp_by.get(t['name'], 0)):,.1f}"} for t in top_inc],
        "hist": hist,
        "low10": low10, "high10": high10,
        "socio": [{"rank": str(r["rank"]), "n": f"{r['n']:,}", "deficit": f"{r['deficit_share']:.1f}%",
                   "collect": f"{r['collect']:.1f}%", "pc": _int(r["pc"])} for r in socio_rows],
        "all": all_rows,
    }

    # --- insights
    rules = [
        ("balance", ins_balance(nat, latest, prev)),
        ("acc_def", ins_acc_def(nat, years, top_acc)),
        ("collect", ins_collect(cur, latest)),
        ("switch", ins_switch(wide, latest, prev)),
        ("loan", ins_loan(med_loan, years)),
        ("per_capita", ins_per_capita(med_pc, years)),
        ("own_income", ins_own(inc_mix, years)),
        ("education", ins_edu(exp_mix, years)),
        ("socio", ins_socio(socio_rows) if socio_rows else None),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # --- KPIs
    L = nat[latest]
    dshare = L["deficit"] / L["n"] if L["n"] else 0
    d_tone = "danger" if dshare >= 0.5 else "warn" if dshare >= 1 / 3 else "ok" if dshare < 0.2 else "brand"
    mc = med_collect[latest]
    c_tone = "brand" if mc is None else "ok" if mc >= 0.9 else "warn" if mc >= 0.8 else "danger"
    acc_tone = "info"
    if prev is not None and nat[prev]["acc"] > 0:
        acc_tone = "danger" if L["acc"] > nat[prev]["acc"] * 1.05 else "ok" if L["acc"] < nat[prev]["acc"] * 0.95 else "info"
    kpis = {
        "authorities": {"value": L["n"], "display": f"{L['n']:,}", "tone": "brand"},
        "income": {"value": round(_bn(L["inc"]), 1), "display": f"{_bn(L['inc']):,.1f}", "tone": "brand"},
        "result": {"value": round(_mn(L["res"]), 1), "display": _signed(_mn(L["res"])),
                   "tone": "danger" if L["res"] < 0 else "ok"},
        "deficit": {"value": L["deficit"], "display": f"{L['deficit']:,}", "tone": d_tone},
        "collect": {"value": _r(mc, 4), "display": _pct(mc) if mc is not None else "-", "tone": c_tone},
        "acc": {"value": round(_bn(L["acc"]), 2), "display": f"{_bn(L['acc']):,.2f}", "tone": acc_tone},
    }

    span = f"{years[0]}-{latest}"
    gap_note = ""
    if gaps:
        gap_note = "אין במאגר נתונים לשנים " + ", ".join(str(g) for g in gaps) + "."
    res_word = "גירעון" if L["res"] < 0 else "עודף"
    labels = {
        "latest": str(latest),
        "span": span,
        "gap_note": gap_note,
        "lede": (f"הדוחות הכספיים המבוקרים של {L['n']:,} רשויות מקומיות (עיריות, מועצות מקומיות ומועצות אזוריות) "
                 f"לשנים {span}, כפי שמפרסם האגף לביקורת ברשויות המקומיות במשרד הפנים. "
                 f"ב-{latest} הסתכמו הכנסות הרשויות בתקציב הרגיל ב-{_bn(L['inc']):,.1f} מיליארד ₪, "
                 f"ו-{L['deficit']:,} מהן סיימו את השנה בגירעון."),
        "authorities_kpi": f"רשויות שדיווחו ב-{latest}",
        "income_kpi": f"הכנסות בתקציב הרגיל ב-{latest} (מיליארד ₪)",
        "result_kpi": f"{res_word} מצרפי בתקציב הרגיל ב-{latest} (מיליון ₪)",
        "deficit_kpi": f"רשויות שסיימו את {latest} בגירעון שוטף (מתוך {L['n']:,})",
        "collect_kpi": f"חציון גביית ארנונה מהחיוב השוטף ({latest})",
        "acc_kpi": f"גירעון מצטבר של כלל הרשויות בסוף {latest} (מיליארד ₪)",
        "national_lede": (f"סך ההכנסות וההוצאות בתקציב הרגיל של כל הרשויות שדיווחו בכל שנה (מיליארדי ₪). "
                          f"ב-{latest}: הכנסות {_bn(L['inc']):,.1f}, הוצאות {_bn(L['exp']):,.1f}. "
                          f"מספר הרשויות המדווחות משתנה בין השנים (ראו בטבלה)."),
        "national_aria": (f"גרף עמודות: הכנסות והוצאות של הרשויות המקומיות לפי שנה, {span}. "
                          f"ב-{latest} הכנסות {_bn(L['inc']):,.1f} והוצאות {_bn(L['exp']):,.1f} מיליארד ₪."),
        "balance_lede": (f"כמה רשויות סיימו כל שנה בעודף, בגירעון או באיזון מלא בתקציב הרגיל. "
                         f"ב-{latest}: {L['surplus']:,} בעודף, {L['deficit']:,} בגירעון, {L['balanced']:,} מאוזנות."),
        "balance_aria": (f"גרף עמודות מוערמות: מספר הרשויות בעודף, בגירעון ובאיזון לפי שנה. "
                         f"ב-{latest} {L['deficit']:,} רשויות בגירעון."),
        "income_lede": (f"מקורות ההכנסה של כלל הרשויות (מיליארדי ₪). "
                        + (f"ב-{latest} הכנסות עצמיות היו {_pct(inc_mix[latest]['inc_own'] / inc_mix[latest]['total'])} מסך ההכנסות."
                           if inc_mix[latest]["total"] else "")),
        "income_aria": f"גרף עמודות מוערמות: מקורות ההכנסה של הרשויות המקומיות לפי שנה, {span}.",
        "expense_lede": (f"הוצאות כלל הרשויות לפי סעיף (מיליארדי ₪). "
                         + (f"ב-{latest} חינוך היה {_pct(exp_mix[latest]['x_edu'] / exp_mix[latest]['total'])} מסך ההוצאות."
                            if exp_mix[latest]["total"] else "")),
        "expense_aria": f"גרף עמודות מוערמות: הוצאות הרשויות המקומיות לפי סעיף ושנה, {span}.",
        "health_lede": ("שלושה מדדי איתנות: חציון שיעור גביית הארנונה מהחיוב השוטף, חציון עומס המלוות מההכנסה, "
                        "והגירעון המצטבר של כל הרשויות כאחוז מסך הכנסותיהן. חציון הגבייה אינו כולל רשויות שדיווחו שיעור אפס."),
        "health_aria": (f"גרף קווים: מדדי איתנות פיננסית של הרשויות לפי שנה. ב-{latest} חציון הגבייה "
                        f"{_pct(mc) if mc is not None else '-'}."),
        "pc_lede": (f"הוצאה ממוצעת לתושב בכל רשות, במחירים שוטפים: החציון, ותחום הרבעונים (רבע מהרשויות מתחת לקו התחתון ורבע מעל העליון). "
                    + (f"ב-{latest} החציון היה {_int(med_pc[latest])} ₪." if med_pc.get(latest) else "")
                    + " רשויות שדיווחו אפס אינן נכללות."),
        "pc_aria": (f"גרף קווים: הוצאה לתושב ברשויות המקומיות לפי שנה, חציון ורבעונים."
                    + (f" ב-{latest} החציון {_int(med_pc[latest])} ₪." if med_pc.get(latest) else "")),
        "acc_lede": (f"{len(top_acc):,} הרשויות עם הגירעון המצטבר הגבוה ביותר ביחס להכנסה השנתית שלהן, סוף {latest}."
                     + (f" בראש: {top_acc[0]['name']}, {_pct(top_acc[0]['v'])}." if top_acc else "")),
        "acc_aria": (f"גרף עמודות אופקי: הרשויות עם שיעור הגירעון המצטבר הגבוה ביותר מן ההכנסה ב-{latest}."
                     + (f" בראש {top_acc[0]['name']} עם {_pct(top_acc[0]['v'])}." if top_acc else "")),
        "inc_lede": (f"{len(top_inc):,} הרשויות עם התקציב הרגיל הגדול ביותר ב-{latest} (הכנסות, מיליוני ₪)."
                     + (f" {top_inc[0]['name']} מובילה עם {_mn(top_inc[0]['v']):,.0f} מיליון ₪." if top_inc else "")),
        "inc_aria": (f"גרף עמודות אופקי: הרשויות עם ההכנסות הגבוהות ביותר ב-{latest}."
                     + (f" בראש {top_inc[0]['name']}." if top_inc else "")),
        "hist_lede": (f"התפלגות הרשויות לפי שיעור גביית הארנונה מהחיוב השוטף ב-{latest} "
                      f"({len(col):,} רשויות"
                      + ("; רשות אחת שדיווחה שיעור אפס אינה נכללת" if zero_collect == 1
                         else f"; {zero_collect:,} שדיווחו שיעור אפס אינן נכללות" if zero_collect else "") + ")."),
        "hist_aria": (f"גרף עמודות: מספר הרשויות לפי טווח שיעור גביית הארנונה ב-{latest}. "
                      f"{hist[-1]['n'] + hist[-2]['n']:,} רשויות גבו 90% ומעלה."),
        "socio_lede": (f"לפי הדירוג החברתי-כלכלי של הרשות (1 הנמוך, 10 הגבוה), {latest}: שיעור הרשויות שסיימו בגירעון "
                       f"שוטף וחציון גביית הארנונה."
                       + (f" {unranked:,} רשויות ללא דירוג אינן נכללות." if unranked else "")),
        "socio_aria": f"גרף עמודות וקו: שיעור הרשויות בגירעון וחציון הגבייה לפי דירוג חברתי-כלכלי, {latest}.",
        "profile_aria": "גרף עמודות: הכנסות והוצאות של הרשות שנבחרה לפי שנה, במיליוני ₪.",
        "all_caption": f"כל הרשויות שדיווחו ב-{latest}: הכנסות, הוצאות ותוצאה (מיליוני ₪) ומדדים עיקריים.",
    }

    summary = (f"איתור הדוח הכספי המבוקר של כל רשות מקומית: הכנסות, הוצאות, גירעון וגביית ארנונה. "
               f"ב-{latest}: {L['n']:,} רשויות, {L['deficit']:,} בגירעון.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0]}/{latest}",
            "spatial_coverage": "כל הרשויות המקומיות בישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "insights": insights,
        "profiles": chunks,
        "profile_years": ylab,
        "default_profile": top_inc[0]["name"] if top_inc else profiles[0]["n"],
        "flags": {"socio": bool(socio_rows), "gaps": bool(gaps)},
    }
