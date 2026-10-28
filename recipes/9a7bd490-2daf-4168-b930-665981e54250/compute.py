"""כלי רכב שלא ביצעו ריקול — vehicles that, more than six months after the
importer's recall letter, still have not had the repair done. One row per
(vehicle, open recall) pair.

Licence plates are never shown: vehicles appear only in counts. Recall
campaigns (manufacturer notices) are public and are named by their id,
fault category and opening date. The list by definition holds recalls at
least half a year old, so "now" is the latest opening date in the data and
age statements are relative to it.
"""
import pandas as pd

TOP_CAMPAIGNS = 15
HEAT_YEARS = 10
OLD_YEARS = 5                # "open for 5+ years" relative to the latest opening
PARETO_POINTS = [1, 5, 10, 20, 50, 100]
TAKATA = "TAKATA"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
OTHER = "אחר"


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    out = pd.DataFrame({
        "vehicle": df["MISPAR_RECHEV"].str.strip(),
        "recall": df["RECALL_ID"].str.strip(),
        "kind": df["SUG_RECALL"].str.strip().replace("", "לא צוין"),
        "fault": df["SUG_TAKALA"].str.strip().replace("", OTHER),
        "desc": df["TEUR_TAKALA"].str.strip(),
        "opened": pd.to_datetime(df["TAARICH_PTICHA"].str.strip(), errors="coerce", format="%Y-%m-%d"),
    })
    out = out.dropna(subset=["opened"])
    out["takata"] = out["desc"].str.upper().str.contains(TAKATA, regex=False)
    return out.reset_index(drop=True)


def insight_scale(df, vehicles, campaigns):
    return (f"{_int(vehicles)} כלי רכב טרם תוקנו לפי {_int(campaigns)} קריאות שירות "
            f"שונות — {_int(len(df))} זוגות רכב–קריאה פתוחים.")


def insight_airbags(df):
    share = (df["fault"] == "כריות אוויר").mean()
    if share < 0.1:
        return None
    return f"כריות אוויר הן התקלה הנפוצה ביותר: {_pct(share)} מהתיקונים הפתוחים."


def insight_takata(df):
    t = df[df["takata"]]
    if len(t) < 100:
        return None
    return (f"ב-{_int(len(t))} תיקונים פתוחים ({_pct(len(t) / len(df))}, "
            f"{_int(t['recall'].nunique())} קריאות) תיאור התקלה מזכיר את יצרנית כריות האוויר TAKATA.")


def insight_concentration(per_campaign, total):
    if len(per_campaign) < 20:
        return None
    top10 = per_campaign.head(10).sum() / total
    return (f"10 הקריאות הגדולות מרכזות {_pct(top10)} מהתיקונים הפתוחים, "
            f"מתוך {_int(len(per_campaign))} קריאות במאגר.")


def insight_old(df, ref):
    cutoff = ref - pd.DateOffset(years=OLD_YEARS)
    old = df[df["opened"] < cutoff]
    if len(old) == 0:
        return None
    return (f"{_int(len(old))} תיקונים ({_pct(len(old) / len(df))}) שייכים לקריאות שנפתחו יותר "
            f"מ-{OLD_YEARS} שנים לפני הקריאה האחרונה במאגר ({_d_he(ref)}), ועדיין לא בוצעו.")


def insight_multi(df):
    per_vehicle = df["vehicle"].value_counts()
    multi = int((per_vehicle > 1).sum())
    if multi == 0:
        return None
    return (f"{_int(multi)} כלי רכב ({_pct(multi / len(per_vehicle))}) ממתינים ליותר מתיקון אחד; "
            f"המקסימום הוא {int(per_vehicle.max())} קריאות פתוחות לרכב.")


def insight_kind(df):
    tech = df[df["kind"] != "תקלה סידרתית בטיחותית"]
    share = 1 - len(tech) / len(df)
    return (f"{_pct(share)} מהתיקונים הפתוחים הם תקלות סדרתיות בטיחותיות; "
            f"{_int(len(tech))} הם קמפייני שירות טכני.")


def compute(frames):
    df = _prepare(frames["open"])
    ref = df["opened"].max()
    vehicles = int(df["vehicle"].nunique())
    per_campaign = _ranked(df["recall"])
    campaigns = len(per_campaign)

    # Fault categories.
    faults = _ranked(df["fault"])
    f_chart = {"names": list(faults.index), "values": [int(v) for v in faults]}
    t_faults = [{"name": n, "count": _int(v), "share": f"{v / len(df) * 100:.1f}"}
                for n, v in faults.items()]

    # Opening year × kind.
    yr = pd.crosstab(df["opened"].dt.year, df["kind"]).sort_index()
    kinds = list(yr.columns)
    y_chart = {"x": [str(y) for y in yr.index],
               "series": [{"name": k, "data": [int(v) for v in yr[k]]} for k in kinds]}
    t_years = [{"year": str(y), "total": _int(r.sum()), "cells": [_int(r[k]) for k in kinds]}
               for y, r in yr.iterrows()]

    # Top campaigns.
    meta = (df.sort_values(["recall", "opened", "fault", "desc"])
            .drop_duplicates("recall").set_index("recall"))
    top = per_campaign.head(TOP_CAMPAIGNS)
    c_names = [f"{rid} · {meta.loc[rid, 'fault']}" for rid in top.index]
    c_chart = {"names": c_names, "values": [int(v) for v in top]}
    t_campaigns = [{
        "id": rid, "count": _int(v), "fault": meta.loc[rid, "fault"],
        "opened": meta.loc[rid, "opened"].strftime("%Y-%m-%d"),
        "desc": meta.loc[rid, "desc"],
    } for rid, v in top.items()]

    # Pareto: share of open pairs covered by the top-N campaigns.
    cum = per_campaign.cumsum() / len(df) * 100
    p_x = [n for n in PARETO_POINTS if n <= campaigns]
    p_chart = {"x": [str(n) for n in p_x], "y": [round(float(cum.iloc[n - 1]), 1) for n in p_x]}
    t_pareto = [{"name": str(n), "share": f"{cum.iloc[n - 1]:.1f}"} for n in p_x]

    # Open recalls per vehicle.
    pv = df["vehicle"].value_counts().value_counts().sort_index()
    pv_b = {"1": int(pv.get(1, 0)), "2": int(pv.get(2, 0)), "3": int(pv.get(3, 0)),
            "4+": int(pv[pv.index >= 4].sum())}
    v_chart = {"names": list(pv_b.keys()), "values": list(pv_b.values())}
    t_vehicles = [{"name": k, "count": _int(v), "share": f"{v / vehicles * 100:.1f}"}
                  for k, v in pv_b.items()]

    # Fault mix by opening year (last HEAT_YEARS years), % of each year.
    years = sorted(df["opened"].dt.year.unique().tolist())[-HEAT_YEARS:]
    hd = df[df["opened"].dt.year.isin(years)]
    cats = list(faults.index)
    hx = pd.crosstab(hd["fault"], hd["opened"].dt.year).reindex(index=cats, columns=years, fill_value=0)
    hp = hx.div(hx.sum(axis=0).replace(0, 1), axis=1) * 100
    cells = [[j, i, round(float(hp.iat[i, j]), 1), int(hx.iat[i, j])]
             for i in range(len(cats)) for j in range(len(years))]
    heat = {"years": [str(y) for y in years], "cats": cats, "cells": cells,
            "max": round(float(hp.values.max()), 1) if len(cells) else 0}

    takata_n = int(df["takata"].sum())
    rules = [
        ("scale", insight_scale(df, vehicles, campaigns)),
        ("airbags", insight_airbags(df)),
        ("takata", insight_takata(df)),
        ("concentration", insight_concentration(per_campaign, len(df))),
        ("old", insight_old(df, ref)),
        ("multi", insight_multi(df)),
        ("kind", insight_kind(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]
    y0 = int(df["opened"].dt.year.min())

    return {
        "agent_data": {
            "summary_he": (f"{_int(vehicles)} כלי רכב שלא ביצעו תיקון ריקול חצי שנה ויותר אחרי "
                           f"קבלת המכתב מהיבואן — {_int(len(df))} תיקונים פתוחים ב-{_int(campaigns)} "
                           f"קריאות שירות, לפי סוג התקלה ושנת הקריאה."),
            "dataset_kind": "rankings",
            "related_ids": [
                "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "35c791ca-8db2-4657-8c6f-eb092147a6bb",
            ],
            "suggested_tags": ["ריקול", "כריות אוויר", "בטיחות בדרכים", "כלי רכב", "תחבורה"],
            "temporal_coverage": f"{df['opened'].min().strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}",
        },
        "kpis": {
            "vehicles": {"value": vehicles, "display": _int(vehicles), "tone": "brand"},
            "pairs": {"value": len(df), "display": _int(len(df)), "tone": "brand"},
            "campaigns": {"value": campaigns, "display": _int(campaigns), "tone": "brand"},
            # Any open TAKATA-airbag repair is a safety risk on the road.
            "takata": {"value": takata_n, "display": _int(takata_n),
                       "tone": "danger" if takata_n else "ok"},
        },
        "charts": {
            "faults": f_chart,
            "years": y_chart,
            "campaigns": c_chart,
            "pareto": p_chart,
            "vehicles": v_chart,
            "heat": heat,
        },
        "tables": {
            "faults": t_faults,
            "kinds": kinds,
            "years": t_years,
            "campaigns": t_campaigns,
            "pareto": t_pareto,
            "vehicles": t_vehicles,
        },
        "insights": insights,
        "labels": {
            "lede": (f"רשימת כלי הרכב שעברה יותר מחצי שנה מאז שבעליהם קיבלו מכתב מהיבואן על "
                     f"קריאה חוזרת (ריקול), והתיקון לא בוצע: {_int(vehicles)} כלי רכב, "
                     f"{_int(len(df))} תיקונים פתוחים, בקריאות שנפתחו מ-{y0} ועד {_d_he(ref)}. "
                     "מספרי הרישוי אינם מוצגים בעמוד."),
            "faults_aria": "תרשים עמודות: תיקונים פתוחים לפי סוג התקלה.",
            "years_aria": "תרשים עמודות: תיקונים פתוחים לפי שנת פתיחת הקריאה וסוג הקריאה.",
            "years_note": ("כל הקריאות במאגר פתוחות חצי שנה לפחות, ולכן השנה האחרונה כוללת רק "
                           "קריאות מחציתה הראשונה."),
            "campaigns_aria": f"תרשים עמודות: {TOP_CAMPAIGNS} הקריאות עם הכי הרבה כלי רכב שלא תוקנו.",
            "pareto_aria": "גרף קו: השיעור המצטבר של התיקונים הפתוחים שמרוכזים בקריאות הגדולות.",
            "vehicles_aria": "תרשים עמודות: כלי רכב לפי מספר הקריאות הפתוחות לכל רכב.",
            "heat_aria": f"מפת חום: תמהיל סוגי התקלות בכל שנת פתיחה, {HEAT_YEARS} השנים האחרונות.",
        },
    }
