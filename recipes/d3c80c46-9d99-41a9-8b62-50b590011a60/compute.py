"""נתוני החוב הממשלתי המקומי — Israel's domestic government debt, from the
Accountant General: tradable bond auctions, non-tradable (pension) issues,
redemptions (actual and forecast) by bond and by linkage, switch auctions,
buybacks, and daily secondary-market trading.

Units differ by table and are not documented on CKAN; they are inferred from
magnitudes and stated on the page: auctions, redemptions and buybacks are
₪ millions; switch auctions, non-tradable issues and trading are ₪.

"Now" is the latest date in each table, never the wall clock. Bond types
are mapped from both current names (ממשלתית / צמודה / משתנה / קצרה) and the
legacy series names (שחר, גליל, גילון, גלבוע) the trading history carries.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
LRI, PDI = "⁦", "⁩"
TYPE_ORDER = ["שקליות בריבית קבועה", "צמודות מדד", "ריבית משתנה", "קצרות", "צמודות דולר", "אחר"]
# Ordered prefix rules (longest first) for issuance BONDS and trading BONDNAME.
TYPE_PREFIXES = [
    ("ממשלתית בריבית משתנה", "ריבית משתנה"),
    ("ממשלתית צמודה", "צמודות מדד"),
    ("ממשלתית קצרה", "קצרות"),
    ("גילון", "ריבית משתנה"),
    ("גליל", "צמודות מדד"),
    ("גלבוע", "צמודות דולר"),
    ("שחר", "שקליות בריבית קבועה"),
    ("ממשלתית", "שקליות בריבית קבועה"),
]
TERM_BUCKETS = [(0, 1, "עד שנה"), (1, 5, "1–4 שנים"), (5, 10, "5–9 שנים"),
                (10, 20, "10–19 שנים"), (20, 999, "20 שנה ומעלה")]
RECENT_YEARS = 10


def bond_type(name):
    n = (name or "").strip()
    for prefix, label in TYPE_PREFIXES:
        if n.startswith(prefix):
            return label
    return "אחר"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def m_he(ts):
    return f"{MONTHS_HE[ts.month - 1]} {ts.year}"


def bn_m(millions):
    """₪ millions → '186.2 מיליארד ₪'."""
    return f"{millions / 1000:,.1f} מיליארד ₪"


def bn(shekels):
    return f"{shekels / 1e9:,.1f} מיליארד ₪"


def pct(v, digits=1, signed=False):
    s = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return f"{LRI}{s}%{PDI}"


def num(v, digits=1):
    return f"{LRI}{v:,.{digits}f}{PDI}"


def _num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce")


def _date(s, dayfirst):
    if dayfirst:
        return pd.to_datetime(s.str.strip(), format="%d/%m/%Y", errors="coerce")
    return pd.to_datetime(s.str.strip().str[:10], format="%Y-%m-%d", errors="coerce")


def _term_bucket(years):
    for lo, hi, label in TERM_BUCKETS:
        if lo <= years < hi:
            return label
    return None


def _ordered(cols):
    return [t for t in TYPE_ORDER if t in cols]


# ── insights ─────────────────────────────────────────────────────────────


def insight_issuance_ytd(iss, last):
    y = last.year
    cut = (last.month, last.day)
    md = list(zip(iss["d"].dt.month, iss["d"].dt.day))
    same = pd.Series([m <= cut for m in md], index=iss.index)
    cur = iss[(iss["d"].dt.year == y) & same]["f"].sum()
    prev = iss[(iss["d"].dt.year == y - 1) & same]["f"].sum()
    if prev <= 0 or cur <= 0:
        return None
    chg = cur / prev - 1
    if abs(chg) < 0.05:
        return (f"מתחילת {y} ועד {d_he(last)} גייסה הממשלה {bn_m(cur)} במכרזי אג״ח סחירות — "
                f"היקף דומה לתקופה המקבילה ב-{y - 1} ({bn_m(prev)}).")
    word = "יותר" if chg > 0 else "פחות"
    return (f"מתחילת {y} ועד {d_he(last)} גייסה הממשלה {bn_m(cur)} במכרזי אג״ח סחירות — "
            f"{pct(abs(chg) * 100)} {word} מבתקופה המקבילה ב-{y - 1} ({bn_m(prev)}).")


def insight_linked(by_type_year):
    if by_type_year.empty or "צמודות מדד" not in by_type_year.columns:
        return None
    share = by_type_year["צמודות מדד"] / by_type_year.sum(axis=1)
    share = share.dropna()
    if len(share) < 2:
        return None
    y0, y1 = int(share.index[0]), int(share.index[-1])
    d = (share.iloc[-1] - share.iloc[0]) * 100
    if abs(d) < 3:
        return (f"האג״ח הצמודות למדד היוו {pct(share.iloc[-1] * 100)} מהגיוס ב-{y1}, בדומה "
                f"ל-{y0}.")
    word = "עלה" if d > 0 else "ירד"
    return (f"משקל האג״ח הצמודות למדד בגיוס {word} מ-{pct(share.iloc[0] * 100)} ב-{y0} "
            f"ל-{pct(share.iloc[-1] * 100)} ב-{y1}.")


def insight_yield(iss_y, last):
    s = iss_y.get("שקליות בריבית קבועה")
    if s is None or len(s) < 13:
        return None
    lastm = s.index[-1]
    prev = [p for p in s.index if p <= lastm - pd.DateOffset(months=12)]
    if not prev:
        return None
    p = prev[-1]
    v1, v0 = s[lastm], s[p]
    d = v1 - v0
    if abs(d) < 0.1:
        return (f"התשואה הממוצעת במכרזי האג״ח השקליות בריבית קבועה עמדה על {pct(v1, 2)} "
                f"ב{lastm.strftime('%m/%Y')}, כמעט ללא שינוי משנה קודם.")
    word = "עלתה" if d > 0 else "ירדה"
    return (f"התשואה הממוצעת במכרזי האג״ח השקליות בריבית קבועה {word} מ-{pct(v0, 2)} "
            f"ב-{p.strftime('%m/%Y')} ל-{pct(v1, 2)} ב-{lastm.strftime('%m/%Y')}.")


def insight_cover(cover_y):
    s = cover_y.dropna()
    if len(s) < 2:
        return None
    y1, v1 = int(s.index[-1]), s.iloc[-1]
    hi_y = int(s.idxmax())
    if hi_y == y1:
        return (f"הביקוש במכרזים ב-{y1} הוא הגבוה בתקופה: בממוצע הוגשו הצעות בהיקף "
                f"{v1:.1f} מהכמות שהוצעה.")
    return (f"יחס הכיסוי הממוצע במכרזים (הביקוש ביחס לכמות המוצעת) עומד ב-{y1} על {v1:.1f}, "
            f"לעומת שיא של {s.max():.1f} ב-{hi_y}.")


def insight_term(term_year):
    if term_year.empty or "20 שנה ומעלה" not in term_year.columns:
        return None
    share = (term_year["20 שנה ומעלה"] / term_year.sum(axis=1)).dropna()
    y = int(share.index[-1])
    return (f"{pct(share.iloc[-1] * 100)} מהגיוס ב-{y} היה באג״ח ארוכות במיוחד, לתקופה מקורית "
            f"של 20 שנה ומעלה.")


def insight_wall(red_year, last_actual_year):
    fut = red_year[red_year.index > last_actual_year]
    if fut.empty:
        return None
    y = int(fut.idxmax())
    return (f"לפי התחזית, היקף הפדיונות יגיע ל-{bn_m(fut.max())} ב-{y} — לעומת "
            f"{bn_m(red_year.get(last_actual_year, 0))} ב-{last_actual_year}.")


def insight_switch(sw_year):
    s = sw_year.dropna()
    if len(s) < 5:
        return None
    full = s.iloc[:-1] if len(s) > 1 else s
    y = int(full.idxmax())
    return (f"מכרזי ההחלף, שבהם הממשלה מחליפה אג״ח קצרות בארוכות, הגיעו לשיא של {bn(full.max())} "
            f"ב-{y}.")


def insight_venue(tr_year):
    if tr_year.empty:
        return None
    y = int(tr_year.index[-1])
    row = tr_year.loc[y]
    tot = row.sum()
    if tot <= 0:
        return None
    return (f"{pct(row.get('TASE', 0) / tot * 100)} מהמסחר באג״ח הממשלתיות ב-{y} התבצע בבורסה "
            f"לניירות ערך; {pct(row.get('OTC', 0) / tot * 100)} מחוץ לבורסה ו-"
            f"{pct(row.get('MTS', 0) / tot * 100)} במערכת MTS.")


# ── compute ──────────────────────────────────────────────────────────────


def _canon(df):
    """Canonical row order: floating-point sums (a year of trading is ~₪1e12)
    depend on summation order, so every frame is sorted by all its columns
    before anything is added up — the model can't depend on CKAN row order."""
    return df.sort_values(list(df.columns), kind="stable").reset_index(drop=True)


def compute(frames):
    frames = {k: _canon(v) for k, v in frames.items()}
    # Tradable auctions (₪ millions)
    i = frames["issuance"]
    iss = pd.DataFrame({
        "d": _date(i["ISSUANCEDATE"], dayfirst=False),
        "type": i["BONDS"].map(bond_type),
        "f": _num(i["TOTALFUNDING"]),
        "q": _num(i["PURCHASEDQUANTITY"]),
        "offered": _num(i["OFFEREDQUANTITY"]),
        "demand": _num(i["DEMANDEDAMOUNT"]),
        "cover": _num(i["COVERRATIO"]),
        "yld": _num(i["GROSSAVGYIELD"]),
        "term": _num(i["ORIGINALTERMTOMATURITY"]),
    }).dropna(subset=["d", "f"])
    iss = iss.sort_values(["d", "type", "f"], kind="stable")
    last_iss = iss["d"].max()
    iss["y"] = iss["d"].dt.year
    by_type_year = (iss.pivot_table(index="y", columns="type", values="f", aggfunc="sum")
                       .fillna(0).sort_index())
    by_type_year = by_type_year[_ordered(by_type_year.columns)]
    iss["bucket"] = iss["term"].map(lambda v: _term_bucket(v) if pd.notna(v) else None)
    term_year = (iss.dropna(subset=["bucket"])
                    .pivot_table(index="y", columns="bucket", values="f", aggfunc="sum")
                    .fillna(0).sort_index())
    term_year = term_year[[b for _, _, b in TERM_BUCKETS if b in term_year.columns]]

    iy = iss.dropna(subset=["yld", "q"])
    iy = iy[iy["q"] > 0]
    iy = iy.assign(m=iy["d"].dt.to_period("M").dt.to_timestamp())
    yld_m = {t: ((g["yld"] * g["q"]).groupby(g["m"]).sum() / g.groupby("m")["q"].sum()).sort_index()
             for t, g in iy.groupby("type")}
    yld_types = [t for t in TYPE_ORDER if t in yld_m and len(yld_m[t]) >= 6]
    months = sorted(set().union(*[set(yld_m[t].index) for t in yld_types])) if yld_types else []

    cv = iss.dropna(subset=["demand", "offered"])
    cv = cv[cv["offered"] > 0]
    cover_y = (cv.groupby("y")["demand"].sum() / cv.groupby("y")["offered"].sum()).sort_index()
    cvm = cv.assign(m=cv["d"].dt.to_period("M").dt.to_timestamp())
    cover_m = (cvm.groupby("m")["demand"].sum() / cvm.groupby("m")["offered"].sum()).sort_index()

    # Redemptions (₪ millions): actual indication + forecast, by bond.
    r = frames["redemptions"]
    red = pd.DataFrame({
        "d": _date(r["REDEMPTIONDATE"], dayfirst=True),
        "p": _num(r["PRNCIPAL"]),
        "tradable": r["TRADABLEORNONTRADABLE"].str.strip(),
        "bond": r["BONDS"].str.strip(),
        "kind": r["DATATYPE"].str.strip(),
    }).dropna(subset=["d", "p"])
    red["y"] = red["d"].dt.year
    is_fc = red["kind"].str.contains("תחזית")
    actual_last = red[~is_fc]["d"].max()
    red_year = red.groupby("y")["p"].sum().sort_index()
    red_split = (red.pivot_table(index="y", columns="tradable", values="p", aggfunc="sum")
                    .fillna(0).sort_index())
    fc_year = red[is_fc].groupby("y")["p"].sum()
    upcoming = red[red["d"] > actual_last] if pd.notna(actual_last) else red.iloc[0:0]
    up_bond = (upcoming.groupby("bond")["p"].sum().sort_index()
                       .sort_values(ascending=False, kind="stable"))

    # Redemptions by linkage (₪ millions), last RECENT_YEARS full + forecast.
    lk = frames["linkage"]
    link = pd.DataFrame({
        "d": _date(lk["REDEMPTIONDATE"], dayfirst=True),
        "p": _num(lk["PRNCIPAL"]),
        "linkage": lk["LINKAGETYPES"].str.strip(),
    }).dropna(subset=["d", "p"])
    link["y"] = link["d"].dt.year
    link_year = (link.pivot_table(index="y", columns="linkage", values="p", aggfunc="sum")
                    .fillna(0).sort_index())
    link_cols = list(link.groupby("linkage")["p"].sum().sort_index()
                         .sort_values(ascending=False, kind="stable").index)
    link_year = link_year[link_cols].tail(RECENT_YEARS + 4)

    # Switch auctions (₪)
    s = frames["switch"]
    sw = pd.DataFrame({
        "d": _date(s["AUCTIONSDATE"], dayfirst=False),
        "bought": _num(s["PURCHASEDAMOUNT"]),
        "issued": _num(s["ISSUEDAMOUNT"]),
    }).dropna(subset=["d"])
    sw["y"] = sw["d"].dt.year
    sw_year = sw.groupby("y")[["bought", "issued"]].sum().sort_index()

    # Buybacks (₪ millions)
    b = frames["buyback"]
    bb = pd.DataFrame({
        "d": _date(b["BUYBACKDATE"], dayfirst=True),
        "q": _num(b["PURCHASEDQUANTITY"]),
    }).dropna(subset=["d", "q"])
    bb_year = bb.groupby(bb["d"].dt.year)["q"].sum().sort_index()

    # Non-tradable pension bonds ("ערד" etc., ₪)
    nt = frames["nontradable"]
    ntd = pd.DataFrame({
        "d": _date(nt["ISSUANCEDATE"], dayfirst=True),
        "bond": nt["BONDS"].str.strip(),
        "q": _num(nt["PURCHASEDQUANTITY"]),
        "coupon": _num(nt["COUPON"]),
    }).dropna(subset=["d", "q"])
    nt_year = ntd.groupby(ntd["d"].dt.year)["q"].sum().sort_index()

    # Daily trading (₪), two period files concatenated.
    t = frames["trading"]
    tr = pd.DataFrame({
        "d": _date(t["TRADINGDATE"], dayfirst=True),
        "type": t["BONDNAME"].map(bond_type),
        "TASE": _num(t["TASE"]), "MTS": _num(t["MTS"]), "OTC": _num(t["OTC"]),
        "total": _num(t["TOTAL"]),
    }).dropna(subset=["d", "total"])
    last_tr = tr["d"].max()
    tr["y"] = tr["d"].dt.year
    days_y = tr.groupby("y")["d"].nunique()
    tr_year = tr.groupby("y")[["TASE", "MTS", "OTC"]].sum().sort_index()
    full_years = [y for y in tr_year.index if days_y.get(y, 0) >= 200 and y != last_tr.year]
    tr_type = (tr.pivot_table(index="y", columns="type", values="total", aggfunc="sum")
                 .fillna(0).sort_index())
    tr_type = tr_type[_ordered(tr_type.columns)]
    tr_type_share = tr_type.div(tr_type.sum(axis=1), axis=0) * 100
    tr_daily_avg = (tr.groupby("y")["total"].sum() / days_y).sort_index()
    last12 = tr[tr["d"] > last_tr - pd.Timedelta(days=365)]

    # ── insights
    rules = [
        ("issuance_ytd", insight_issuance_ytd(iss, last_iss)),
        ("linked", insight_linked(by_type_year)),
        ("yield", insight_yield(yld_m, last_iss)),
        ("cover", insight_cover(cover_y)),
        ("term", insight_term(term_year)),
        ("wall", insight_wall(red_year, int(actual_last.year) if pd.notna(actual_last) else 0)),
        ("switch", insight_switch(sw_year["bought"] if len(sw_year) else pd.Series(dtype=float))),
        ("venue", insight_venue(tr_year.loc[full_years] if full_years else tr_year.iloc[0:0])),
    ]
    insights = [{"id": k, "text_he": v} for k, v in rules if v]

    ytd_cur = iss[iss["y"] == last_iss.year]["f"].sum()
    next12 = red[(red["d"] > last_iss) & (red["d"] <= last_iss + pd.Timedelta(days=365))]["p"].sum()
    kpis = {
        "issuance_ytd": {"value": float(ytd_cur), "display": bn_m(ytd_cur)},
        "last_auction": {"value": last_iss.strftime("%Y-%m-%d"), "display": d_he(last_iss)},
        "next12": {"value": float(next12), "display": bn_m(next12)},
        "trading12": {"value": float(last12["total"].sum()), "display": bn(last12["total"].sum())},
    }

    yr = lambda idx: [str(int(v)) for v in idx]
    charts = {
        "issuance": {"x": yr(by_type_year.index),
                     "series": [{"name": c, "data": [round(v / 1000, 1) for v in by_type_year[c]]}
                                for c in by_type_year.columns]},
        "term": {"x": yr(term_year.index),
                 "series": [{"name": c, "data": [round(v / 1000, 1) for v in term_year[c]]}
                            for c in term_year.columns]},
        "yields": {"x": [m.strftime("%Y-%m") for m in months],
                   "series": [{"name": t, "data": [round(float(yld_m[t][m]), 2) if m in yld_m[t].index
                                                   else None for m in months]}
                              for t in yld_types]},
        "cover": {"x": [m.strftime("%Y-%m") for m in cover_m.index],
                  "y": [round(float(v), 2) for v in cover_m.values]},
        "redemptions": {"x": yr(red_split.index),
                        "series": [{"name": c, "data": [round(v / 1000, 1) for v in red_split[c]]}
                                   for c in sorted(red_split.columns)],
                        "forecast_from": int(actual_last.year) if pd.notna(actual_last) else None},
        "upcoming": {"names": list(up_bond.index), "values": [round(v / 1000, 1) for v in up_bond.values]},
        "linkage": {"x": yr(link_year.index),
                    "series": [{"name": c, "data": [round(v / 1000, 1) for v in link_year[c]]}
                               for c in link_year.columns]},
        "switch": {"x": yr(sw_year.index),
                   "bought": [round(v / 1e9, 1) for v in sw_year["bought"]],
                   "issued": [round(v / 1e9, 1) for v in sw_year["issued"]]},
        "buyback": {"x": yr(bb_year.index), "y": [round(v / 1000, 2) for v in bb_year.values]},
        "nontradable": {"x": yr(nt_year.index), "y": [round(v / 1e9, 2) for v in nt_year.values]},
        "venue": {"x": yr(tr_year.index),
                  "series": [{"name": n, "data": [round(v / 1e9, 1) for v in tr_year[c]]}
                             for c, n in (("TASE", "בורסה"), ("OTC", "מחוץ לבורסה"), ("MTS", "MTS"))]},
        "trade_type": {"x": yr(tr_type_share.index),
                       "series": [{"name": c, "data": [round(float(v), 1) for v in tr_type_share[c]]}
                                  for c in tr_type_share.columns]},
    }

    def year_label(y, partial_year):
        return f"{int(y)}{' (חלקית)' if int(y) == partial_year else ''}"

    tables = {
        "issuance": [{"year": year_label(y, last_iss.year),
                      "cells": [bn_m(by_type_year.loc[y, c]) for c in by_type_year.columns],
                      "total": bn_m(by_type_year.loc[y].sum())} for y in by_type_year.index],
        "issuance_cols": list(by_type_year.columns),
        "term": [{"year": year_label(y, last_iss.year),
                  "cells": [bn_m(term_year.loc[y, c]) for c in term_year.columns]} for y in term_year.index],
        "term_cols": list(term_year.columns),
        "cover": [{"year": year_label(y, last_iss.year), "ratio": num(v, 2)} for y, v in cover_y.items()],
        "upcoming": [{"bond": n, "amount": bn_m(v)} for n, v in up_bond.items()],
        "linkage": [{"year": str(int(y)), "cells": [bn_m(link_year.loc[y, c]) for c in link_year.columns]}
                    for y in link_year.index],
        "linkage_cols": list(link_year.columns),
        "switch": [{"year": year_label(y, int(sw["d"].max().year)), "bought": bn(r_["bought"]),
                    "issued": bn(r_["issued"])} for y, r_ in sw_year.iterrows()],
        "buyback": [{"year": str(int(y)), "amount": bn_m(v)} for y, v in bb_year.items()],
        "nontradable": [{"year": str(int(y)), "amount": bn(v)} for y, v in nt_year.items()],
        "venue": [{"year": year_label(y, last_tr.year), "tase": bn(r_["TASE"]), "otc": bn(r_["OTC"]),
                   "mts": bn(r_["MTS"]), "avg": bn(tr_daily_avg[y])} for y, r_ in tr_year.iterrows()],
        "trade_type": [{"year": year_label(y, last_tr.year),
                        "cells": [num(tr_type_share.loc[y, c]) for c in tr_type_share.columns]}
                       for y in tr_type_share.index],
        "trade_type_cols": list(tr_type_share.columns),
    }

    last_nt = ntd["d"].max()
    labels = {
        "lede": (f"נתוני החוב הממשלתי המקומי של החשב הכללי: {len(iss):,} הנפקות במכרזי אג״ח סחירות "
                 f"מאז {m_he(iss['d'].min())} (האחרונה ב-{d_he(last_iss)}), פדיונות בפועל ובתחזית, "
                 f"מכרזי החלף ורכישה חוזרת, ונתוני מסחר יומיים עד {d_he(last_tr)}."),
        "units_note": ("יחידות לפי הקבצים: מכרזי הנפקה, פדיונות ורכישות חוזרות במיליוני ₪; מכרזי "
                       "החלף, הנפקות לא סחירות ומסחר ב-₪. בתרשימים — מיליארדי ₪."),
        "issuance_aria": f"תרשים עמודות: גיוס במכרזי אג״ח סחירות לפי סוג אג״ח ושנה, עד {d_he(last_iss)}.",
        "term_aria": "תרשים עמודות: גיוס לפי התקופה המקורית לפדיון ולפי שנה.",
        "yields_aria": "גרף קווים: תשואה ממוצעת משוקללת במכרזים לפי חודש וסוג אג״ח.",
        "cover_aria": "גרף קו: יחס כיסוי חודשי במכרזי ההנפקה (ביקוש ביחס לכמות המוצעת).",
        "redemptions_aria": "תרשים עמודות: פדיונות קרן לפי שנה, סחיר ולא סחיר, כולל שנות תחזית.",
        "upcoming_aria": f"תרשים עמודות: פדיונות צפויים אחרי {d_he(actual_last)} לפי סדרת אג״ח.",
        "linkage_aria": "תרשים עמודות: פדיונות לפי סוג הצמדה ושנה.",
        "switch_aria": "תרשים עמודות: היקף מכרזי ההחלף לפי שנה — אג״ח שנרכשו ואג״ח שהונפקו.",
        "buyback_aria": "תרשים עמודות: רכישות חוזרות של אג״ח לפי שנה.",
        "nontradable_aria": "תרשים עמודות: הנפקות אג״ח לא סחירות לפי שנה.",
        "venue_aria": "תרשים עמודות: מחזור המסחר באג״ח ממשלתיות לפי זירה ושנה.",
        "trade_type_aria": "תרשים עמודות: חלוקת המסחר לפי סוג אג״ח בכל שנה, באחוזים.",
        "forecast_note": (f"פדיונות עד {d_he(actual_last)} — אינדיקציה לביצוע בפועל; לאחר מכן — תחזית "
                          f"החשב הכללי." if pd.notna(actual_last) else ""),
        "nontradable_note": (f"אג״ח לא סחירות מונפקות לקרנות הפנסיה. ההנפקה האחרונה במאגר: "
                             f"{d_he(last_nt)}." if pd.notna(last_nt) else ""),
        "venue_note": ("ממוצע יומי = מחזור שנתי חלקי מספר ימי המסחר במאגר. בשנה הראשונה והאחרונה "
                       "הנתונים חלקיים."),
    }

    return {
        "agent_data": {
            "summary_he": (f"נתוני החוב הממשלתי המקומי: הנפקות אג״ח, פדיונות ותחזית פדיונות, מכרזי "
                           f"החלף ומסחר. מתחילת {last_iss.year} גויסו {bn_m(ytd_cur)} במכרזים."),
            "dataset_kind": "timeseries",
            "related_ids": [],
            "suggested_tags": ["חוב ממשלתי", "אג״ח", "החשב הכללי", "שוק ההון", "מימון ממשלתי"],
            "temporal_coverage": f"{red['d'].min().strftime('%Y-%m-%d')}/{red['d'].max().strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
