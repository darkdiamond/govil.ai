"""רישוי עסקים (באר שבע) — register of businesses holding a licence in force.

One row per licence-at-an-address; a licence number that appears at more than
one address is counted once. "Now" is the latest status-change timestamp in the
register (its data vintage), never the wall clock. Phones, e-mails, house
numbers and licence numbers are not used on the page; vehicle licences carry a
plate number inside their description, so descriptions are normalised and
plate-bearing ones are kept out of the licence-type ranking.
"""
import re

import pandas as pd

TOP_N = 12
TOP_BUSINESSES = 10
HEAT_STREETS = 8
HEAT_SECTORS = 6
MONTH_CAP = 36
EXPIRY_HORIZON_YEARS = 14
INDEFINITE_YEAR = 2090          # 2099-12-31 is used as "no expiry date"
LRI, PDI = "⁦", "⁩"
NO_STREET = {"", "0", "באר שבע"}
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
STATUS_ORDER = ["מתחדש", "זמני", "בהיתר"]

# Ordered keyword rules: first match wins. Unknown descriptions fall to "אחר".
SECTOR_RULES = [
    ("רכב, מוסכים ודלק", ["מוסך", "פחחות", "תחנת דלק", "דלק", "צמיג", "שטיפת רכב", "מכונאות", "מלגזות", "חשמלאות רכב", "תדלוק"]),
    ("הובלה והסעות", ["הובל", "מס' רכב", "מס רכב", "מס' ר", "הסעת", "הסעות", "מוניות", "משאית", "רכבים", "מנוף", "מנופ", "עפר", "כספים"]),
    ("פנאי, ספורט ואירוח", ["מקווה", "בריכ", "אולם", "איצטדיון", "אצטדיון", "קניון", "מלון", "אכסניה", "קולנוע", "תיאטרון", "גן חיות", "קייטנה", "שעשועים", "מתנפח", "עינוג", "מופע", "באמפי", "אמפיתיאטרון", "כושר", "משחקי", "חניון"]),
    ("רוכלות מזון ואירועים", ["רוכלות", "אירוע", "יריד", "דוכן"]),
    ("מסעדות ובתי אוכל", ["מסעדה", "בית אוכל", "קפיטריה", "מזנון", "הסעדה", "קייטרינג", "בית קפה", "קפה", "פיצ", "שווארמ", "משקאות משכרים", "גלידה", "פלאפל", "חומוס", "מועדון", "פאב", "בר "]),
    ("מרכולים, קיוסקים ומזון", ["מרכול", "אטליז", "קיוסק", "פירות", "ירקות", "מכולת", "סופר", "מאפ", "דגים", "מעדני", "מזון", "חנות", "אחסנת מזון", "משקאות", "בשר", "עוף", "ממכר"]),
    ("מספרות, יופי ובריאות", ["מספרה", "קוסמטיקה", "יופי", "קעקוע", "קעקע", "ספא", "מניקור", "פדיקור", "בית מרקחת", "מרפאה", "רפואי", "קליניק", "מכון", "בריאות", "טיפול", "שיער", "עיסוי"]),
    ("תעשייה, מלאכה ומחסנים", ["נגר", "מסגר", "מתכת", "ייצור", "הרכב", "פלסטיק", "מחסן", "אחסנ", "אחסון", "בטון", "ברזל", "כימ", "מפעל", "מלאכה", "מוצרי", "עבודות", "יציקה", "ציוד", "חומרי", "ריתוך", "אלומיניום", "זכוכית", "חשמל", "נעליים", "טקסטיל", "הדפסה", "דפוס", "בניין", "נשק", "כלי"]),
]
OTHER = "אחר"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def sector_of(desc):
    for name, words in SECTOR_RULES:
        if any(w in desc for w in words):
            return name
    return OTHER


PLATE = re.compile(r"\d{2,3}-?\d{2,3}-?\d{2,3}|רכב|מס'|מס |\d{5,}")


def norm_desc(s):
    s = re.sub(r"\s+", " ", s).strip().rstrip(",-– ").strip()
    return s


def norm_street(s):
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("ככר "):
        s = "כיכר " + s[4:]
    return s


def _prepare(df):
    out = pd.DataFrame({
        "lic": df["מספר רישיון"].str.strip(),
        "biz": df["שם עסק"].map(lambda s: re.sub(r"\s+", " ", s).strip()),
        "exp": pd.to_datetime(df["תאריך תוקף"], errors="coerce", format="%Y-%m-%d %H:%M:%S"),
        "status": df["תאור סטטוס"].str.strip(),
        "desc": df["תאור רישיון"].map(norm_desc),
        "chg": pd.to_datetime(df["תאריך שינוי מצב"], errors="coerce", format="%Y-%m-%d %H:%M:%S"),
        "street": df["שם רחוב"].map(norm_street),
    })
    # one row per licence number, deterministic regardless of row order
    out["_k"] = out["exp"].astype(str)
    out = out.sort_values(["lic", "street", "biz", "desc", "status", "_k"], kind="mergesort")
    out = out[out["lic"] != ""].drop_duplicates("lic", keep="first").drop(columns="_k")
    out["sector"] = out["desc"].map(sector_of)
    out["has_plate"] = out["desc"].map(lambda s: bool(PLATE.search(s)))
    out["street_ok"] = ~out["street"].isin(NO_STREET)
    return out.reset_index(drop=True)


def _counts(series):
    c = series.value_counts()
    return c.sort_index().sort_values(ascending=False, kind="stable")


def _top(counts, k, other_label="אחר"):
    top = counts.head(k)
    other = int(counts.iloc[k:].sum())
    names = list(top.index) + ([other_label] if other else [])
    vals = [int(v) for v in top.values] + ([other] if other else [])
    return names, vals


def insight_sector(sectors, total):
    named = sectors.drop(OTHER, errors="ignore")
    if named.empty or total == 0:
        return None
    name, v = named.index[0], int(named.iloc[0])
    if v / total < 0.12:
        return None
    s = f"התחום הגדול ביותר הוא {name}: {n(v)} רישיונות, {pct(v / total * 100)} מהמאגר."
    if len(named) > 1:
        v2 = int(named.iloc[1])
        s += f" אחריו {named.index[1]} ({n(v2)} רישיונות, {pct(v2 / total * 100)})."
    return s


def insight_food(sectors, total):
    food = ["מסעדות ובתי אוכל", "מרכולים, קיוסקים ומזון", "רוכלות מזון ואירועים"]
    v = int(sum(sectors.get(f, 0) for f in food))
    if total == 0 or v / total < 0.25:
        return None
    return (f"עסקי מזון ואירוח (מסעדות ובתי אוכל, מרכולים וקיוסקים, רוכלות מזון) מחזיקים יחד "
            f"{n(v)} רישיונות, {pct(v / total * 100)} מכלל הרישיונות בתוקף.")


def insight_status(status_counts, total):
    other = total - int(status_counts.get("מתחדש", 0))
    if total == 0 or other / total < 0.05:
        return None
    parts = []
    for s in ["זמני", "בהיתר"]:
        if status_counts.get(s, 0):
            parts.append(f"{n(status_counts[s])} בסטטוס \"{s}\"")
    return (f"{pct(int(status_counts.get('מתחדש', 0)) / total * 100)} מהרישיונות בסטטוס \"מתחדש\"; "
            f"{n(other)} נוספים ({pct(other / total * 100)}) אינם כאלה: {' ו-'.join(parts)}.")


def insight_expiry(df, ref, total):
    if ref is None or total == 0:
        return None
    ex = df["exp"].dropna()
    ex = ex[ex.dt.year < INDEFINITE_YEAR]
    horizon = ref + pd.DateOffset(years=1)
    soon = int(((ex >= ref) & (ex < horizon)).sum())
    past = int((ex < ref).sum())
    if soon / total < 0.03 and past == 0:
        return None
    s = ""
    if soon / total >= 0.03:
        s = (f"{n(soon)} רישיונות ({pct(soon / total * 100)}) אמורים לפוג בשנה שאחרי "
             f"{d_he(ref)}, מועד העדכון האחרון במאגר.")
    if past:
        s += (f" {n(past)} רישיונות מופיעים עם תאריך תוקף שקדם למועד זה, ועדיין נכללים במאגר."
              if s else
              f"{n(past)} רישיונות מופיעים עם תאריך תוקף שקדם ל-{d_he(ref)} ועדיין נכללים במאגר.")
    return s.strip()


def insight_concentration(df, total):
    c = _counts(df["biz"])
    if total == 0 or len(c) < 20:
        return None
    top = c.head(5)
    share = int(top.sum()) / total
    if share < 0.05:
        return None
    return (f"{n(len(c))} עסקים (לפי שם) מחזיקים ברישיונות, והחמישה המובילים — "
            f"{', '.join(top.index)} — מחזיקים יחד {n(top.sum())} רישיונות ({pct(share * 100)}).")


def insight_streets(df):
    tot = len(df)
    if tot == 0:
        return None
    ok = df[df["street_ok"]]
    if ok.empty:
        return None
    c = _counts(ok["street"])
    name, v = c.index[0], int(c.iloc[0])
    miss = tot - len(ok)
    s = f"הרחוב עם הכי הרבה רישיונות הוא {name}: {n(v)} רישיונות ({pct(v / tot * 100)})."
    if miss / tot >= 0.05:
        s += (f" ב-{n(miss)} רישיונות ({pct(miss / tot * 100)}) לא נרשם רחוב מוגדר "
              f"(הכתובת היא \"באר שבע\" בלבד) והם אינם נכללים בדירוג הרחובות.")
    return s


def insight_temp_sector(df):
    g = df.groupby("sector")["status"].agg(["size", lambda s: (s == "זמני").sum()])
    g.columns = ["n", "t"]
    g = g[(g["n"] >= 40) & (g.index != OTHER)]
    if g.empty:
        return None
    g["r"] = g["t"] / g["n"]
    g = g.sort_values(["r", "n"], ascending=[False, False], kind="stable")
    name = g.index[0]
    overall = (df["status"] == "זמני").mean()
    r = g.iloc[0]["r"]
    if r < overall * 1.5 or r < 0.1:
        return None
    return (f"רישיונות בסטטוס \"זמני\" מרוכזים בתחום {name}: {pct(r * 100)} מרישיונות התחום "
            f"({n(g.iloc[0]['t'])} מתוך {n(g.iloc[0]['n'])}), לעומת {pct(overall * 100)} בכלל המאגר.")


def insight_months(months, partial_last):
    # months: ordered list of (label, count); the partial last month is excluded
    rows = months[:-1] if partial_last else months
    if len(rows) < 6:
        return None
    best = max(rows, key=lambda r: (r[1], r[0]))
    avg = sum(r[1] for r in rows) / len(rows)
    if best[1] < avg * 1.3:
        return None
    return (f"נרשמו שינויי סטטוס ב-{len(rows)} חודשים מלאים, בממוצע {avg:.0f} בחודש. "
            f"החודש הערני ביותר: {best[2]} עם {n(best[1])} שינויים.")


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    ref = df["chg"].max() if df["chg"].notna().any() else None
    ref = None if pd.isna(ref) else ref

    sectors = _counts(df["sector"])
    status_counts = df["status"].value_counts()

    # ---- charts ----
    charts, tables = {}, {}
    named = sectors.drop(OTHER, errors="ignore")
    other_v = int(sectors.get(OTHER, 0))
    s_names = list(named.index) + ([OTHER] if other_v else [])
    s_vals = [int(v) for v in named.values] + ([other_v] if other_v else [])
    charts["sectors"] = {"names": s_names, "values": s_vals}
    tables["sectors"] = [{"name": a, "count": n(b), "share": pct(b / total * 100)} for a, b in zip(s_names, s_vals)]

    st_list = [s for s in STATUS_ORDER if s in status_counts.index] + sorted(
        s for s in status_counts.index if s not in STATUS_ORDER and s)
    charts["status"] = [{"name": s, "value": int(status_counts[s])} for s in st_list]
    tables["status"] = [{"name": s, "count": n(status_counts[s]), "share": pct(status_counts[s] / total * 100)} for s in st_list]

    # expiry timeline: expired-before-ref bucket, years, indefinite bucket
    ex = df.dropna(subset=["exp"]).copy()
    indef = ex["exp"].dt.year >= INDEFINITE_YEAR
    ref_year = ref.year if ref is not None else None
    ex["bucket"] = ex["exp"].dt.year.astype(int).astype(str)
    if ref is not None:
        ex.loc[ex["exp"] < ref, "bucket"] = "פג תוקף"
        far = ex["exp"].dt.year > ref_year + EXPIRY_HORIZON_YEARS
        ex.loc[far & ~indef, "bucket"] = f"אחרי {ref_year + EXPIRY_HORIZON_YEARS}"
    ex.loc[indef, "bucket"] = "ללא תפוגה"
    years = sorted(b for b in ex["bucket"].unique() if b.isdigit())
    x = (["פג תוקף"] if (ex["bucket"] == "פג תוקף").any() else []) + years
    if ref is not None and (ex["bucket"] == f"אחרי {ref_year + EXPIRY_HORIZON_YEARS}").any():
        x.append(f"אחרי {ref_year + EXPIRY_HORIZON_YEARS}")
    if (ex["bucket"] == "ללא תפוגה").any():
        x.append("ללא תפוגה")
    pv = ex.groupby(["bucket", "status"]).size()
    series = []
    for s in st_list:
        series.append({"name": s, "data": [int(pv.get((b, s), 0)) for b in x]})
    charts["expiry"] = {"x": x, "series": series}
    tables["expiry"] = [{"bucket": b, "cells": [n(sr["data"][i]) for sr in series],
                         "total": n(sum(sr["data"][i] for sr in series))} for i, b in enumerate(x)]
    tables["status_cols"] = st_list

    # monthly status changes (latest MONTH_CAP months); last month may be partial
    ch = df.dropna(subset=["chg"]).copy()
    ch["m"] = ch["chg"].dt.strftime("%Y-%m")
    mo_all = sorted(ch["m"].unique())[-MONTH_CAP:]
    ch = ch[ch["m"].isin(mo_all)]
    mp = ch.groupby(["m", "status"]).size()
    month_series = [{"name": s, "data": [int(mp.get((m, s), 0)) for m in mo_all]} for s in st_list]
    mlabels = [f"{MONTHS_HE[int(m[5:]) - 1]} {m[:4]}" for m in mo_all]
    charts["months"] = {"x": mlabels, "series": month_series}
    partial_last = False
    if ref is not None and mo_all and mo_all[-1] == ref.strftime("%Y-%m"):
        partial_last = ref.day < (ref + pd.offsets.MonthEnd(0)).day
    month_rows = [(m, sum(sr["data"][i] for sr in month_series), mlabels[i]) for i, m in enumerate(mo_all)]
    month_rows_ins = [(a, b, c) for a, b, c in month_rows]

    # streets
    ok = df[df["street_ok"]]
    st_counts = _counts(ok["street"])
    t_names = list(st_counts.index[:TOP_N])
    t_vals = [int(v) for v in st_counts.values[:TOP_N]]
    charts["streets"] = {"names": t_names, "values": t_vals}
    tables["streets"] = [{"name": a, "count": n(b)} for a, b in zip(t_names, t_vals)]

    # street x sector heatmap
    hs = list(st_counts.index[:HEAT_STREETS])
    hsec = [s for s in sectors.index if s != OTHER][:HEAT_SECTORS]
    cells, mx = [], 0
    hp = ok.groupby(["street", "sector"]).size()
    for yi, st in enumerate(hs):
        for xi, sec in enumerate(hsec):
            v = int(hp.get((st, sec), 0))
            mx = max(mx, v)
            cells.append([xi, yi, v])
    charts["heat"] = {"x": hsec, "y": hs, "cells": cells, "max": mx}

    # licence types (plate-bearing descriptions kept out)
    clean = df[~df["has_plate"] & (df["desc"].str.len() > 3)]
    d_counts = _counts(clean["desc"])
    d_names, d_vals = d_counts.head(TOP_N).index.tolist(), [int(v) for v in d_counts.head(TOP_N).values]
    charts["types"] = {"names": d_names, "values": d_vals}
    tables["types"] = [{"name": a, "count": n(b)} for a, b in zip(d_names, d_vals)]

    # sector x status share (100% stacked): share of each status inside the top sectors
    sec_list = [s for s in sectors.index if s != OTHER][:TOP_N]
    sp = df.groupby(["sector", "status"]).size()
    share_series, srows = [], []
    for s in st_list:
        share_series.append({"name": s, "data": [round(float(sp.get((sec, s), 0)) / float(sectors[sec]) * 100, 1)
                                                  for sec in sec_list]})
    for i, sec in enumerate(sec_list):
        srows.append({"name": sec, "n": n(sectors[sec]), "cells": [pct(sr["data"][i]) for sr in share_series]})
    charts["sector_status"] = {"names": sec_list, "series": share_series}
    tables["sector_status"] = srows

    # businesses
    b_counts = _counts(df["biz"])
    bt = b_counts.head(TOP_BUSINESSES)
    charts["businesses"] = {"names": bt.index.tolist(), "values": [int(v) for v in bt.values]}
    tables["businesses"] = [{"name": a, "count": n(b)} for a, b in zip(bt.index, bt.values)]
    multi = int((b_counts > 1).sum())

    # ---- insights ----
    rules = [
        ("sector", insight_sector(sectors, total)),
        ("food", insight_food(sectors, total)),
        ("status", insight_status(status_counts, total)),
        ("expiry", insight_expiry(df, ref, total)),
        ("concentration", insight_concentration(df, total)),
        ("streets", insight_streets(df)),
        ("temp_sector", insight_temp_sector(df)),
        ("months", insight_months(month_rows_ins, partial_last)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs ----
    ren = int(status_counts.get("מתחדש", 0))
    ren_share = ren / total * 100 if total else 0
    soon = 0
    if ref is not None:
        e2 = ex[(ex["exp"].dt.year < INDEFINITE_YEAR)]
        soon = int(((e2["exp"] >= ref) & (e2["exp"] < ref + pd.DateOffset(years=1))).sum())
    soon_share = soon / total * 100 if total else 0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "businesses": {"value": int(len(b_counts)), "display": n(len(b_counts)), "tone": "brand"},
        "renewing": {"value": ren, "display": f"{ren_share:.1f}%",
                     "tone": "ok" if ren_share >= 85 else ("warn" if ren_share >= 70 else "danger")},
        "soon": {"value": soon, "display": n(soon), "tone": "warn" if soon_share >= 10 else "info"},
    }

    top_sector = sectors.drop(OTHER, errors="ignore")
    partial_note = (f" החודש האחרון ({mlabels[-1]}) חלקי — עד {d_he(ref)}." if partial_last else "")
    labels = {
        "lede": (f"רישיונות עסק בתוקף בעיריית באר שבע: {n(total)} רישיונות של {n(len(b_counts))} עסקים "
                 f"(לפי שם), ב-{len(ok['street'].unique())} רחובות."
                 + (f" העדכון האחרון במאגר: {d_he(ref)}." if ref is not None else "")
                 + " רישיון שמופיע בכמה כתובות נספר פעם אחת. המאגר כולל רק עסקים טעוני רישוי בעלי רישיון בתוקף."),
        "soon_kpi": (f"רישיונות שפוקעים בשנה שאחרי {d_he(ref)}" if ref is not None else "רישיונות שפוקעים בשנה הקרובה"),
        "sectors_note": ("תחום העיסוק נקבע מתיאור הרישיון לפי מילות מפתח, ולכן הוא קירוב. "
                         f"תיאורים שלא סווגו בשום תחום מוצגים כ\"אחר\" ({pct(other_v / total * 100)} מהרישיונות)."),
        "sectors_aria": "תרשים עמודות אופקי: מספר רישיונות לפי תחום עיסוק.",
        "sectors_caption": "מספר רישיונות ושיעורם לפי תחום עיסוק.",
        "status_aria": "תרשים טבעת: חלוקת הרישיונות לפי סטטוס.",
        "status_caption": "מספר רישיונות ושיעורם לפי סטטוס.",
        "expiry_note": (f"שנת תוקף הרישיון, לפי סטטוס. \"פג תוקף\" — תאריך שקדם ל-{d_he(ref)}; "
                        f"\"ללא תפוגה\" — תאריך רחוק בשנות ה-2090 שמשמש במאגר לרישיונות ללא מועד פקיעה."
                        if ref is not None else "שנת תוקף הרישיון, לפי סטטוס."),
        "expiry_aria": "תרשים עמודות מוערמות: מספר רישיונות לפי שנת תוקף וסטטוס.",
        "expiry_caption": "מספר רישיונות לפי שנת תוקף וסטטוס.",
        "months_note": ("שינויי סטטוס לפי חודש, לרישיונות שיש להם תאריך שינוי מצב רשום "
                        f"({pct(ch.shape[0] / total * 100) if total else '0%'} מהרישיונות)." + partial_note),
        "months_aria": "תרשים עמודות מוערמות: מספר שינויי סטטוס לפי חודש וסטטוס.",
        "streets_note": ("הרחובות עם הכי הרבה רישיונות. רישיונות שכתובתם היא \"באר שבע\" בלבד, בלי רחוב, "
                         "אינם נכללים."),
        "streets_aria": f"תרשים עמודות אופקי: {TOP_N} הרחובות עם הכי הרבה רישיונות.",
        "streets_caption": f"מספר רישיונות לפי רחוב ({TOP_N} המובילים).",
        "heat_note": f"מספר הרישיונות בכל צירוף של רחוב ותחום, ב-{len(hs)} הרחובות המובילים.",
        "heat_aria": "מפת חום: מספר רישיונות לפי רחוב ותחום עיסוק.",
        "types_note": ("תיאורי הרישיון הנפוצים ביותר כפי שנרשמו. רישיונות לרכבים, שתיאורם כולל מספר רכב, "
                       "אינם נכללים כאן."),
        "types_aria": f"תרשים עמודות אופקי: {TOP_N} תיאורי הרישיון הנפוצים.",
        "types_caption": f"מספר רישיונות לפי תיאור הרישיון ({TOP_N} הנפוצים).",
        "ss_note": "חלוקת הרישיונות בכל תחום לפי סטטוס, באחוזים.",
        "ss_aria": "תרשים עמודות מוערמות באחוזים: סטטוס הרישיונות בכל תחום עיסוק.",
        "ss_caption": "שיעור כל סטטוס מרישיונות התחום.",
        "biz_note": (f"העסקים (לפי שם) עם מספר הרישיונות הגדול ביותר. {n(multi)} עסקים מחזיקים "
                     f"ביותר מרישיון אחד."),
        "biz_aria": f"תרשים עמודות אופקי: {TOP_BUSINESSES} העסקים עם הכי הרבה רישיונות.",
        "biz_caption": f"מספר רישיונות לפי עסק ({TOP_BUSINESSES} המובילים).",
    }

    return {
        "agent_data": {
            "summary_he": (f"רישיונות עסק בתוקף בעיריית באר שבע: {n(total)} רישיונות של {n(len(b_counts))} עסקים, "
                           f"לפי תחום עיסוק, סטטוס, תוקף ורחוב."),
            "dataset_kind": "registry",
            "related_ids": ["54b65747-904e-42e1-9316-0575ebbc1216",
                            "fffada0a-b021-4629-9244-bc5e301f23d5",
                            "4491ecd9-5f9c-4299-a79f-43ed979651f9",
                            "82a30a97-01b0-4281-854c-c7931f3445c0",
                            "f4a5cdab-82b2-48ad-9d95-424a035cfed8"],
            "suggested_tags": ["רישוי עסקים", "עסקים", "באר שבע", "כלכלה מקומית", "רגולציה"],
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
