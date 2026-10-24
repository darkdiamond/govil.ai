"""בקשות לפטנטים — Israeli patent applications and their status.

One row per application, except where the register lists an application
twice with two statuses (its history). Each application keeps its most
advanced status (STATUS_RANK). Timing uses the Israeli filing date
("תאריך הגשה"); for a PCT national-phase entry that is ~18 months after the
international date ("תאריך הבקשה"). "Now" = the latest filing or grant date in
the data — the current calendar year is partial and only ever compared to
the same period of the previous year.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

# Lifecycle order: a later stage wins when an application appears twice.
STATUS_RANK = {
    "בקשה חדשה": 1, "פרסום שני": 2, "בקשה הוזנחה": 3, "בקשה סורבה": 3,
    "פטנט": 4, "צו ארכה": 5, "פקיעת תוקף": 6, "פג תוקף": 6,
    "צו ארכה פג תוקף": 6, "פטנט בוטל": 6,
}
PENDING = {"בקשה חדשה", "פרסום שני"}
IN_FORCE = {"פטנט", "צו ארכה"}
GRANTED_FAMILY = {"פטנט", "צו ארכה", "פקיעת תוקף", "פג תוקף", "צו ארכה פג תוקף", "פטנט בוטל"}
STATUS_LABEL = {
    "בקשה חדשה": "בבחינה", "פרסום שני": "פורסמה לאחר קבלה", "בקשה הוזנחה": "הוזנחה",
    "בקשה סורבה": "סורבה", "פטנט": "פטנט בתוקף", "צו ארכה": "בתוקף בצו הארכה",
    "פקיעת תוקף": "פקע (אי-חידוש)", "פג תוקף": "תם תוקף (סוף התקופה)",
    "צו ארכה פג תוקף": "צו הארכה פג", "פטנט בוטל": "בוטל",
}
OFFICE_HE = {
    "US": "ארה״ב", "EP": "משרד הפטנטים האירופי", "IB": "הלשכה הבינלאומית (WIPO)",
    "IL": "ישראל", "GB": "בריטניה", "JP": "יפן", "CN": "סין", "FR": "צרפת",
    "CA": "קנדה", "AU": "אוסטרליה", "SE": "שוודיה", "KR": "דרום קוריאה",
    "NL": "הולנד", "DK": "דנמרק", "DE": "גרמניה", "CH": "שווייץ", "IT": "איטליה",
    "ES": "ספרד", "FI": "פינלנד", "BE": "בלגיה", "AT": "אוסטריה", "IN": "הודו",
    "IE": "אירלנד", "NO": "נורווגיה", "SG": "סינגפור", "RU": "רוסיה",
    "BR": "ברזיל", "NZ": "ניו זילנד", "HU": "הונגריה", "PL": "פולין",
}
TOP_OFFICES = 12
FIRST_YEAR = 1990
COHORT_YEARS = 20
HEAT_YEARS = 15
LAG_BUCKETS = [(0, 2, "עד שנתיים"), (2, 3, "2–3 שנים"), (3, 4, "3–4 שנים"),
               (4, 5, "4–5 שנים"), (5, 6, "5–6 שנים"), (6, 8, "6–8 שנים"),
               (8, 200, "8 שנים ומעלה")]


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _prepare(df):
    df = df[~df["שם האמצאה בעברית"].str.contains("טסט", regex=False)]
    out = pd.DataFrame({
        "app": df["מספר בקשה"].str.strip(),
        "filed": pd.to_datetime(df["תאריך הגשה"], format="%d/%m/%Y", errors="coerce"),
        "granted": pd.to_datetime(df["תאריך מתן פטנט"], format="%d/%m/%Y", errors="coerce"),
        "status": df["סטטוס בקשה/פטנט"].str.strip(),
        "office": df["מספר בקשה בינלאומי"].str.extract(r"^([A-Z]{2})/\d{4}/", expand=False),
    })
    out = out[out["app"] != ""]
    out["rank"] = out["status"].map(STATUS_RANK).fillna(0)
    # Most advanced status per application; ties broken by every column so
    # row order never matters.
    out = out.sort_values(["app", "rank", "status", "filed", "granted", "office"],
                          na_position="first", kind="stable")
    out = out.drop_duplicates("app", keep="last").reset_index(drop=True)
    out["pct"] = out["office"].notna()
    return out


def _office_name(code):
    return OFFICE_HE.get(code, code)


def compute(frames):
    raw_rows = len(frames["applications"])
    df = _prepare(frames["applications"])
    n_apps = len(df)
    anchor = max(df["filed"].max(), df["granted"].max())
    cur = int(anchor.year)
    last_full = cur - 1
    test_rows = int(frames["applications"]["שם האמצאה בעברית"].str.contains("טסט", regex=False).sum())

    fy = df["filed"].dt.year
    gy = df["granted"].dt.year

    # 1. Filings per year by route
    years = list(range(FIRST_YEAR, cur + 1))
    direct = df[~df["pct"]].groupby(fy[~df["pct"]]).size()
    pct_c = df[df["pct"]].groupby(fy[df["pct"]]).size()
    filings = {
        "x": [str(y) for y in years],
        "direct": [int(direct.get(y, 0)) for y in years],
        "pct": [int(pct_c.get(y, 0)) for y in years],
    }
    tot_f = {y: filings["direct"][i] + filings["pct"][i] for i, y in enumerate(years)}

    # 2. Grants per year
    g_counts = df.groupby(gy).size()
    grants = {"x": [str(y) for y in years], "y": [int(g_counts.get(y, 0)) for y in years]}

    # 3. Status mix
    st = df["status"].value_counts()
    st = st.sort_index().sort_values(ascending=False, kind="stable")
    status = {"names": [STATUS_LABEL.get(s, s) for s in st.index], "values": [int(v) for v in st]}
    status_rows = [{"name": STATUS_LABEL.get(s, s), "n": _int(v), "share": f"{v / n_apps * 100:.1f}"}
                   for s, v in st.items()]

    # 4. PCT receiving office, last 5 full years
    win = df[(fy >= last_full - 4) & (fy <= last_full)]
    w_pct = win[win["pct"]]
    off = w_pct["office"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    top = off.head(TOP_OFFICES)
    rest = int(off.iloc[TOP_OFFICES:].sum())
    origin_names = [_office_name(c) for c in top.index] + (["משרדים אחרים"] if rest else [])
    origin_vals = [int(v) for v in top] + ([rest] if rest else [])
    origin = {"names": origin_names, "values": origin_vals}
    origin_rows = [{"name": n, "n": _int(v), "share": f"{v / max(len(w_pct), 1) * 100:.1f}"}
                   for n, v in zip(origin_names, origin_vals)]
    direct_win = int((~win["pct"]).sum())

    # 5/6. Grant lag (filing → grant), years
    g = df[df["granted"].notna() & df["filed"].notna() & (df["granted"] >= df["filed"])].copy()
    g["lag"] = (g["granted"] - g["filed"]).dt.days / 365.25
    g["gy"] = g["granted"].dt.year
    recent = g[(g["gy"] >= last_full - 4) & (g["gy"] <= last_full)]
    lag_counts = [int(((recent["lag"] >= lo) & (recent["lag"] < hi)).sum()) for lo, hi, _ in LAG_BUCKETS]
    lag = {"names": [b[2] for b in LAG_BUCKETS], "values": lag_counts}
    lag_rows = [{"name": b[2], "n": _int(v), "share": f"{v / max(len(recent), 1) * 100:.1f}"}
                for b, v in zip(LAG_BUCKETS, lag_counts)]
    med = g[g["gy"] >= 2000].groupby("gy")["lag"].median()
    lag_trend = {"x": [str(int(y)) for y in med.index], "y": [round(float(v), 2) for v in med]}

    # 7. Cohort fate by filing year
    cohort_years = list(range(last_full - COHORT_YEARS + 1, last_full + 1))

    def fate(s):
        if s in GRANTED_FAMILY:
            return "granted"
        if s == "בקשה הוזנחה":
            return "abandoned"
        if s == "בקשה סורבה":
            return "refused"
        return "pending"

    df["fate"] = df["status"].map(fate)
    fates = {}
    for k in ("granted", "pending", "abandoned", "refused"):
        sub = df[df["fate"] == k].groupby(fy[df["fate"] == k]).size()
        fates[k] = [int(sub.get(y, 0)) for y in cohort_years]
    cohort_tot = [sum(fates[k][i] for k in fates) for i in range(len(cohort_years))]
    fate_chart = {
        "x": [str(y) for y in cohort_years],
        "series": [
            {"name": lbl, "data": [round(fates[k][i] / cohort_tot[i] * 100, 1) if cohort_tot[i] else 0
                                   for i in range(len(cohort_years))]}
            for k, lbl in (("granted", "ניתן פטנט"), ("pending", "עדיין בטיפול"),
                           ("abandoned", "הוזנחה"), ("refused", "סורבה"))
        ],
    }

    # 8. Still in force, by grant year
    gf = df[df["granted"].notna() & df["status"].isin(GRANTED_FAMILY)]
    gf_y = gf["granted"].dt.year
    inforce = gf.groupby(gf_y)["status"].apply(lambda s: s.isin(IN_FORCE).mean())
    inforce = inforce[(inforce.index >= 2000) & (inforce.index <= last_full)]
    inforce_chart = {"x": [str(int(y)) for y in inforce.index],
                     "y": [round(float(v) * 100, 1) for v in inforce]}

    # 9. Month × year filings heatmap
    hy = list(range(cur - HEAT_YEARS, cur + 1))
    hm = df[fy.isin(hy)].groupby([fy[fy.isin(hy)], df["filed"].dt.month]).size()
    cells = [[hy.index(int(y)), int(mo) - 1, int(v)] for (y, mo), v in hm.items()]
    heat = {"years": [str(y) for y in hy], "months": MONTHS_HE, "cells": cells,
            "max": int(max((c[2] for c in cells), default=1))}

    # Insights --------------------------------------------------------------
    def ins_grants():
        a, b = grants["y"][years.index(last_full)], grants["y"][years.index(last_full - 1)]
        if not b:
            return None
        ch = (a - b) / b
        full = [grants["y"][years.index(y)] for y in years if y <= last_full]
        rec = " — שיא כל הזמנים במאגר" if a == max(full) else ""
        if abs(ch) < 0.03:
            return f"ב-{last_full} ניתנו {_int(a)} פטנטים, בדומה ל-{last_full - 1} ({_int(b)}){rec}."
        word = "עלייה" if ch > 0 else "ירידה"
        return f"ב-{last_full} ניתנו {_int(a)} פטנטים — {word} של {abs(ch) * 100:.1f}% לעומת {last_full - 1} ({_int(b)}){rec}."

    def ins_ytd():
        if anchor.month < 3:
            return None
        cut_prev = anchor - pd.DateOffset(years=1)
        a = int(((df["granted"] >= pd.Timestamp(cur, 1, 1)) & (df["granted"] <= anchor)).sum())
        b = int(((df["granted"] >= pd.Timestamp(cur - 1, 1, 1)) & (df["granted"] <= cut_prev)).sum())
        if not b:
            return None
        ch = (a - b) / b
        word = "יותר" if ch > 0 else "פחות"
        if abs(ch) < 0.03:
            return f"מתחילת {cur} ועד {d_he(anchor)} ניתנו {_int(a)} פטנטים — קצב דומה לתקופה המקבילה ב-{cur - 1}."
        return (f"מתחילת {cur} ועד {d_he(anchor)} ניתנו {_int(a)} פטנטים — {abs(ch) * 100:.0f}% {word} "
                f"מבתקופה המקבילה ב-{cur - 1} ({_int(b)}).")

    def ins_filings():
        a, b = tot_f[last_full], tot_f[last_full - 1]
        if not b:
            return None
        ch = (a - b) / b
        share = filings["pct"][years.index(last_full)] / a if a else 0
        trend = ("בדומה לשנה הקודמת" if abs(ch) < 0.03 else
                 f"{'עלייה' if ch > 0 else 'ירידה'} של {abs(ch) * 100:.1f}% לעומת {last_full - 1}")
        return (f"ב-{last_full} הוגשו {_int(a)} בקשות לפטנט ({trend}); {_pct(share, 0)} מהן "
                "הגיעו במסלול הבינלאומי (PCT).")

    def ins_origin():
        if len(w_pct) < 100 or top.empty:
            return None
        c, v = top.index[0], int(top.iloc[0])
        share = v / len(w_pct)
        if share < 0.2:
            return None
        return (f"בחמש השנים {last_full - 4}–{last_full}, {_pct(share, 0)} מהבקשות שהגיעו במסלול PCT "
                f"הוגשו במקור דרך {_office_name(c)}; {_pct(int(off.get('IL', 0)) / len(w_pct), 1)} דרך ישראל.")

    def ins_lag():
        if last_full not in med.index or (last_full - 10) not in med.index:
            return None
        a, b = float(med[last_full]), float(med[last_full - 10])
        if abs(a - b) < 0.25:
            return f"חציון הזמן מהגשה ועד מתן פטנט עמד ב-{last_full} על {a:.1f} שנים — בדומה ל-{last_full - 10}."
        word = "התקצר" if a < b else "התארך"
        return f"חציון הזמן מהגשה ועד מתן פטנט {word} מ-{b:.1f} שנים ב-{last_full - 10} ל-{a:.1f} שנים ב-{last_full}."

    def ins_fate():
        y = last_full - 10
        if y not in cohort_years:
            return None
        i = cohort_years.index(y)
        if cohort_tot[i] < 500:
            return None
        gr = fates["granted"][i] / cohort_tot[i]
        ab = fates["abandoned"][i] / cohort_tot[i]
        return (f"מבין {_int(cohort_tot[i])} הבקשות שהוגשו ב-{y}, {_pct(gr, 0)} הבשילו לפטנט "
                f"ו-{_pct(ab, 0)} הוזנחו.")

    def ins_inforce():
        y = last_full - 10
        if y not in inforce.index:
            return None
        cohort = gf[gf_y == y]
        gone = cohort[~cohort["status"].isin(IN_FORCE)]
        base = f"מבין הפטנטים שניתנו ב-{y}, {_pct(float(inforce[y]), 0)} עדיין בתוקף"
        if len(gone) >= 50:
            lapsed = (gone["status"] == "פקיעת תוקף").mean()
            if lapsed >= 0.5:
                return base + f"; {_pct(lapsed, 0)} מהשאר פקעו משום שלא חודשו."
        return base + "."

    rules = [("grants", ins_grants()), ("ytd", ins_ytd()), ("filings", ins_filings()),
             ("origin", ins_origin()), ("lag", ins_lag()), ("fate", ins_fate()),
             ("inforce", ins_inforce())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    in_force_now = int(df["status"].isin(IN_FORCE).sum())
    lag_last = float(med[last_full]) if last_full in med.index else None
    y0 = int(fy.min())

    def tbl(years_list, values):
        return [{"year": str(y), "n": _int(v)} for y, v in zip(years_list, values)]

    return {
        "agent_data": {
            "summary_he": (f"{_int(n_apps)} בקשות לפטנט שהוגשו בישראל מ-{y0} ועד {d_he(anchor)}, "
                           f"מצבן העדכני ומועדי מתן הפטנט. {_int(in_force_now)} פטנטים בתוקף כיום."),
            "dataset_kind": "timeseries",
            "suggested_tags": ["פטנטים", "קניין רוחני", "חדשנות", "רשות הפטנטים"],
            "related_ids": ["ebf84395-4784-4438-b9ca-08caf263beaf", "247efc75-31f2-4b19-bd4e-e670b1bf2783",
                            "a5b7e889-de77-4062-85e1-cf427bfbf9d1"],
            "temporal_coverage": f"{y0}/{anchor.strftime('%Y-%m-%d')}",
        },
        "kpis": {
            "applications": {"value": n_apps, "display": _int(n_apps)},
            "in_force": {"value": in_force_now, "display": _int(in_force_now)},
            "grants_last": {"value": grants["y"][years.index(last_full)],
                            "display": _int(grants["y"][years.index(last_full)])},
            "lag_last": {"value": lag_last, "display": "—" if lag_last is None else f"{lag_last:.1f} שנים"},
        },
        "charts": {"filings": filings, "grants": grants, "status": status, "origin": origin,
                   "lag": lag, "lag_trend": lag_trend, "fate": fate_chart,
                   "inforce": inforce_chart, "heat": heat},
        "tables": {"status": status_rows, "origin": origin_rows, "lag": lag_rows,
                   "filings_recent": tbl(years[-10:], [tot_f[y] for y in years[-10:]]),
                   "grants_recent": tbl(years[-10:], grants["y"][-10:])},
        "insights": insights,
        "labels": {
            "last_full": str(last_full),
            "grants_last_label": f"פטנטים שניתנו ב-{last_full}",
            "lag_last_label": f"חציון הזמן עד מתן פטנט ({last_full})",
            "lede": (f"{_int(n_apps)} בקשות לפטנט, מ-{y0} ועד {d_he(anchor)}. כל בקשה מוצגת פעם אחת, "
                     f"בסטטוס המתקדם ביותר שלה; {_int(test_rows)} רשומות בדיקה ({_int(raw_rows)} שורות במאגר) הוסרו."),
            "filings_note": (f"לפי שנת ההגשה בישראל. {cur} חלקית — עד {d_he(anchor)}. בקשה במסלול PCT "
                             "מוגשת בישראל כשנה וחצי אחרי הבקשה הבינלאומית."),
            "grants_note": f"לפי תאריך מתן הפטנט. {cur} חלקית — עד {d_he(anchor)}.",
            "origin_note": (f"בקשות PCT שהוגשו בישראל ב-{last_full - 4}–{last_full}, לפי המשרד שקיבל את "
                            f"הבקשה הבינלאומית. באותן שנים הוגשו עוד {_int(direct_win)} בקשות ישירות בישראל."),
            "lag_note": f"פטנטים שניתנו ב-{last_full - 4}–{last_full} ({_int(len(recent))}), לפי משך הזמן מההגשה בישראל.",
            "fate_note": f"שיעור הבקשות לפי מצבן היום, לפי שנת ההגשה ({cohort_years[0]}–{last_full}).",
            "inforce_note": "שיעור הפטנטים שעדיין בתוקף, לפי שנת מתן הפטנט. פטנט פוקע כשלא משלמים את אגרת החידוש, ותוקפו המרבי עשרים שנה.",
            "filings_aria": f"עמודות מוערמות: בקשות לפטנט לפי שנה ומסלול, {FIRST_YEAR} עד {cur}.",
            "grants_aria": f"עמודות: פטנטים שניתנו בכל שנה, {FIRST_YEAR} עד {cur}.",
            "status_aria": f"עמודות אופקיות: {_int(n_apps)} בקשות לפי מצבן היום.",
            "origin_aria": f"עמודות אופקיות: בקשות PCT לפי משרד הקבלה הבינלאומי, {last_full - 4} עד {last_full}.",
            "lag_aria": "עמודות: פטנטים לפי משך הזמן מהגשה ועד מתן.",
            "lag_trend_aria": "קו: חציון הזמן מהגשה ועד מתן פטנט, לפי שנת המתן.",
            "fate_aria": f"עמודות מוערמות באחוזים: מצב הבקשות לפי שנת הגשה, {cohort_years[0]} עד {last_full}.",
            "inforce_aria": "קו: שיעור הפטנטים שעדיין בתוקף, לפי שנת מתן.",
            "heat_aria": f"מפת חום: בקשות לפטנט לפי חודש ושנת הגשה, {hy[0]} עד {cur}.",
        },
    }
