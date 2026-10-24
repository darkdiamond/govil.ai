"""מאגר מתווכים פעילים — licensed real-estate brokers + broker exam sittings.

Two unrelated tables. Brokers are private individuals: only the city
column is read, and only city-level counts leave this function — the name
column is never touched. Exams: one row per examinee per sitting; sittings
dated after the last graded one are scheduled (registrants, no scores yet).
The pass mark is not in the data, so the page reports "score of 60+" and
never calls it a pass rate.
"""
import pandas as pd

TOP_CITIES = 15
RECENT_SITTINGS_MONTHS = 24
SCORE_LINE = 60
DIST_YEARS = 3
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


TOP_INST = 10
MIN_INST_GRADED = 100     # graded examinees with an institution, for the comparison insight
HEAT_YEARS = 15


def _exams(df):
    out = pd.DataFrame({
        "d": pd.to_datetime(df["תאריך הבחינה"], format="%d/%m/%Y", errors="coerce"),
        "s": pd.to_numeric(df["ציון"], errors="coerce"),
        "inst": df["מוסד לימודי"].str.strip(),
    }).dropna(subset=["d"])
    out.loc[(out["s"] < 0) | (out["s"] > 100), "s"] = float("nan")
    return out


def insight_brokers(cities, total):
    top, v = cities.index[0], cities.iloc[0]
    top5 = cities.head(5).sum() / total
    return (f"{n(total)} מתווכים מורשים רשומים ב-{n(cities.size)} יישובים; {top} מובילה "
            f"עם {n(v)} ({pct(v / total * 100)}), וחמשת היישובים הגדולים מרכזים "
            f"{pct(top5 * 100)} מהמתווכים.")


def insight_volume(per_year, last_full):
    if last_full not in per_year.index or (last_full - 1) not in per_year.index:
        return None
    v1, v0 = per_year[last_full], per_year[last_full - 1]
    peak_y = int(per_year[per_year.index <= last_full].idxmax())
    peak = f" השיא נרשם ב-{peak_y} ({n(per_year[peak_y])})." if peak_y != last_full else \
        " זו שנת השיא במאגר."
    if v0 == 0:
        return None
    chg = v1 / v0 - 1
    if abs(chg) < 0.03:
        return f"ב-{last_full} נבחנו {n(v1)} נבחנים, בדומה ל-{last_full - 1}.{peak}"
    word = "יותר" if chg > 0 else "פחות"
    return (f"ב-{last_full} נבחנו {n(v1)} נבחנים — {pct(abs(chg) * 100)} {word} מאשר "
            f"ב-{last_full - 1}.{peak}")


def insight_scores(stats, last_full):
    if last_full not in stats.index:
        return None
    prev = stats[(stats.index < last_full) & (stats.index >= last_full - 5)]
    if len(prev) < 3:
        return None
    m1, base = stats.loc[last_full, "mean"], prev["mean"].mean()
    s1 = stats.loc[last_full, "ge"]
    rel = "גבוה" if m1 > base + 1 else ("נמוך" if m1 < base - 1 else "דומה")
    tail = "מהממוצע" if rel != "דומה" else "לממוצע"
    return (f"הציון הממוצע ב-{last_full} היה {m1:.1f} — {rel} {tail} של {len(prev)} השנים "
            f"שלפניה ({base:.1f}); {pct(s1 * 100)} מהנבחנים קיבלו {SCORE_LINE} ומעלה.")


def insight_long_trend(stats, last_full):
    early = stats[(stats.index >= 2005) & (stats.index <= 2009)]
    late = stats[(stats.index > last_full - 5) & (stats.index <= last_full)]
    if len(early) < 3 or len(late) < 3:
        return None
    e, l = early["ge"].mean(), late["ge"].mean()
    if abs(e - l) < 0.03:
        return None
    word = "ירד" if l < e else "עלה"
    return (f"שיעור הנבחנים עם ציון {SCORE_LINE} ומעלה {word} לאורך השנים: ממוצע של "
            f"{pct(e * 100)} ב-{int(early.index.min())}–{int(early.index.max())} לעומת "
            f"{pct(l * 100)} ב-{int(late.index.min())}–{int(late.index.max())}.")


def insight_institution(g):
    w = g[g["inst"] != ""]
    if len(w) < MIN_INST_GRADED:
        return None
    wo = g[g["inst"] == ""]
    a, b = w["s"].mean(), wo["s"].mean()
    share = len(w) / len(g)
    if abs(a - b) < 2:
        return (f"רק {pct(share * 100)} מהנבחנים רשומים עם מוסד לימודי, וציוניהם דומים לשאר "
                f"({a:.1f} מול {b:.1f}).")
    rel = "גבוה" if a > b else "נמוך"
    return (f"רק {pct(share * 100)} מהנבחנים רשומים עם מוסד לימודי, אך הציון הממוצע שלהם "
            f"({a:.1f}) {rel} מזה של שאר הנבחנים ({b:.1f}).")


def insight_upcoming(upcoming):
    """Next regular sitting: the first future date with a real cohort (a few
    stray rows on other dates are make-up or special sittings)."""
    major = upcoming[upcoming >= 50]
    if major.empty:
        return None
    d, cnt = major.index[0], major.iloc[0]
    return f"במועד הבחינה הקרוב הרשום במאגר, {d_he(d)}, רשומים {n(cnt)} נבחנים."


def compute(frames):
    b = frames["brokers"]
    city = b["עיר מגורים"].str.strip().replace("", "לא ידוע")
    total = len(b)
    cities = city.value_counts().sort_index().sort_values(ascending=False, kind="stable")

    ex = _exams(frames["exams"])
    graded = ex.dropna(subset=["s"])
    ref = graded["d"].max()
    last_full = int(ref.year) - 1
    done = ex[ex["d"] <= ref]
    upcoming = ex[ex["d"] > ref].groupby("d").size().sort_index()

    per_year = done.groupby(done["d"].dt.year).size()
    per_year.index = per_year.index.astype(int)
    g_year = graded[graded["d"] <= ref]
    stats = g_year.groupby(g_year["d"].dt.year)["s"].agg(
        mean="mean", ge=lambda s: (s >= SCORE_LINE).mean(), graded="size")
    stats.index = stats.index.astype(int)
    years = sorted(per_year.index)
    ungraded = done[done["s"].isna()].groupby(done["d"].dt.year).size()

    dist_src = g_year[g_year["d"].dt.year.between(last_full - DIST_YEARS + 1, last_full)]
    bins = list(range(0, 100, 10))
    dist = [(f"{lo}–{lo + 9}" if lo < 90 else "90–100",
             int(((dist_src["s"] >= lo) & ((dist_src["s"] < lo + 10) if lo < 90 else (dist_src["s"] <= 100))).sum()))
            for lo in bins]

    since = ref - pd.DateOffset(months=RECENT_SITTINGS_MONTHS)
    sit = ex[ex["d"] > since].groupby("d").size().sort_index()

    top_c = cities.head(TOP_CITIES)
    other = int(cities.iloc[TOP_CITIES:].sum())

    # Institutions: sparse (most examinees have none) — counted over all years.
    wi = done[done["inst"] != ""]
    inst_n = wi["inst"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    inst_top = list(inst_n.head(TOP_INST).index)
    inst_mean = wi.dropna(subset=["s"]).groupby("inst")["s"].mean()
    inst_rows = [{"name": i, "count": n(inst_n[i]),
                  "mean": "—" if i not in inst_mean.index else f"{inst_mean[i]:.1f}"}
                 for i in inst_top]

    # Examinees by calendar month (all completed sittings): the exam calendar.
    by_month = done.groupby(done["d"].dt.month).size().reindex(range(1, 13), fill_value=0)

    # Score-band share per year, last HEAT_YEARS full years.
    hy = [y for y in stats.index if last_full - HEAT_YEARS < y <= last_full]
    band_lo = list(range(0, 100, 10))
    heat_cells = []
    for xi, y in enumerate(hy):
        s = g_year.loc[g_year["d"].dt.year == y, "s"]
        for yi, lo in enumerate(band_lo):
            hi_ok = (s < lo + 10) if lo < 90 else (s <= 100)
            share = float(((s >= lo) & hi_ok).mean() * 100) if len(s) else 0.0
            heat_cells.append([xi, yi, round(share, 1)])

    charts = {
        "volume": {"x": [str(y) for y in years],
                   "graded": [int(per_year[y] - ungraded.get(y, 0)) for y in years],
                   "ungraded": [int(ungraded.get(y, 0)) for y in years]},
        "scores": {"x": [str(y) for y in stats.index],
                   "mean": [round(float(v), 1) for v in stats["mean"]],
                   "ge": [round(float(v) * 100, 1) for v in stats["ge"]]},
        "dist": {"names": [a for a, _ in dist], "values": [v for _, v in dist]},
        "sittings": {"x": [d.strftime("%Y-%m-%d") for d in sit.index],
                     "y": [int(v) for v in sit.values],
                     "upcoming": [bool(d > ref) for d in sit.index]},
        "cities": {"names": [*top_c.index, *(["שאר היישובים"] if other else [])],
                   "values": [int(v) for v in top_c.values] + ([other] if other else [])},
        "institutions": {"names": inst_top, "values": [int(inst_n[i]) for i in inst_top]},
        "months": {"names": MONTHS_HE, "values": [int(v) for v in by_month.values]},
        "bands": {"years": [str(y) for y in hy],
                  "bands": [f"{lo}–{lo + 9}" if lo < 90 else "90–100" for lo in band_lo],
                  "cells": heat_cells,
                  "max": max([c[2] for c in heat_cells] or [1])},
    }

    rules = [
        ("brokers", insight_brokers(cities, total)),
        ("volume", insight_volume(per_year, last_full)),
        ("scores", insight_scores(stats, last_full)),
        ("long_trend", insight_long_trend(stats, last_full)),
        ("upcoming", insight_upcoming(upcoming)),
        ("institution", insight_institution(g_year)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    lf = stats.loc[last_full] if last_full in stats.index else None
    kpis = {
        "brokers": {"value": total, "display": n(total)},
        "cities": {"value": int(cities.size), "display": n(cities.size)},
        "examinees": {"value": int(len(done)), "display": n(len(done))},
        "ge_last": {"value": None if lf is None else float(lf["ge"]),
                    "display": "—" if lf is None else pct(lf["ge"] * 100)},
    }
    y0 = int(done["d"].dt.year.min())
    labels = {
        "last_full": str(last_full),
        "ge_label": f"ציון {SCORE_LINE} ומעלה",
        "lede": (f"שני קבצים: רשימת {n(total)} המתווכים המורשים לפי יישוב מגורים, ו-{n(len(done))} "
                 f"רישומים של נבחנים בבחינת דיני מתווכים במקרקעין מ-{y0} ועד {d_he(ref)}."),
        "volume_aria": f"תרשים עמודות: נבחנים בכל שנה, {y0} עד {ref.year}, עם ציון ובלי ציון.",
        "volume_note": (f"נבחנים ללא ציון בקובץ (למשל מי שלא ניגש) מוצגים בנפרד. "
                        f"{ref.year} — שנה חלקית, עד {d_he(ref)}."),
        "scores_aria": f"גרף קווים: ציון ממוצע ושיעור הנבחנים עם ציון {SCORE_LINE} ומעלה, לפי שנה.",
        "scores_note": (f"מחושב על נבחנים שיש להם ציון. ציון הסף לעבירת הבחינה אינו מופיע "
                        f"במאגר; הקו מציג ציון {SCORE_LINE} ומעלה."),
        "dist_aria": (f"תרשים עמודות: התפלגות הציונים ב-{last_full - DIST_YEARS + 1}–{last_full}."),
        "dist_title": f"התפלגות הציונים, {last_full - DIST_YEARS + 1}–{last_full}",
        "dist_caption": f"מספר נבחנים לפי טווח ציון, {last_full - DIST_YEARS + 1}–{last_full}.",
        "sittings_aria": "תרשים עמודות: נבחנים בכל מועד בחינה בשנתיים האחרונות, כולל מועדים עתידיים.",
        "cities_aria": f"תרשים עמודות: מתווכים מורשים לפי יישוב מגורים, {TOP_CITIES} היישובים המובילים.",
        "cities_caption": f"מתווכים מורשים לפי יישוב מגורים ({TOP_CITIES} המובילים ושאר היישובים).",
        "inst_aria": f"תרשים עמודות: {len(inst_top)} המוסדות הלימודיים עם מספר הנבחנים הגדול ביותר.",
        "inst_note": (f"מוסד לימודי רשום רק אצל {pct(len(wi) / len(done) * 100)} מהנבחנים "
                      f"({n(len(wi))}); הנתון מוצג לכל השנים יחד."),
        "inst_caption": "נבחנים וציון ממוצע לפי מוסד לימודי.",
        "months_aria": "תרשים עמודות: נבחנים לפי חודש הבחינה, בכל השנים.",
        "months_caption": "מספר הנבחנים לפי חודש הבחינה, בכל השנים.",
        "bands_aria": (f"מפת חום: שיעור הנבחנים בכל טווח ציון לפי שנה, "
                       f"{hy[0] if hy else ''}–{hy[-1] if hy else ''}."),
        "bands_note": "שיעור מהנבחנים בעלי ציון באותה שנה. גוון כהה = שיעור גבוה יותר.",
    }

    return {
        "agent_data": {
            "summary_he": (f"רשם המתווכים: {n(total)} מתווכים מורשים ב-{n(cities.size)} יישובים, "
                           f"ו-{n(len(done))} רישומי נבחנים בבחינות המתווכים מאז {y0}."),
            "dataset_kind": "timeseries",
            "related_ids": ["669b2652-f75b-4de3-8e6b-0dfa17accef5",
                            "713440a1-9963-4548-a7d9-9d9c9da54f62",
                            "3111ae54-790a-4d02-9750-d51e1134b405"],
            "suggested_tags": ["מתווכים", "נדל״ן", "רשם המתווכים", "בחינות", "שוק הדיור"],
            "temporal_coverage": f"{y0}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": {
            "dist": [{"range": a, "count": n(v)} for a, v in dist],
            "cities": [{"name": k, "count": n(v)} for k, v in
                       zip(charts["cities"]["names"], charts["cities"]["values"])],
            "institutions": inst_rows,
            "months": [{"name": k, "count": n(v)} for k, v in zip(MONTHS_HE, by_month.values)],
        },
        "insights": insights,
        "labels": labels,
    }
