"""מאגר רואי החשבון — the Ministry of Justice register of CPA licences.

One row per licence (~43k): licence date, first/last name, settlement and
current status (active / declared not practising / cancelled / suspended).
"Now" is the latest licence date in the register (its data vintage), never
the wall clock; that year is partial unless the date reaches late December.

Licence numbers are individual identifiers and never reach the page. Names
are used only in aggregate (most common surnames / first names) — no
individual is singled out. Settlement spellings vary in the source
("קרית"/"קריית", "פתח-תקוה"/"פתח תקווה", spacing around hyphens); they are
folded on a normalized key and shown under their most common spelling.
"""
import re

import pandas as pd

ACTIVE = "פעיל"
NOT_PRACTISING = "הצהיר על אי עיסוק במקצוע"
CANCELLED = "בוטל"
SUSPENDED = "מושעה"
STATUS_ORDER = [ACTIVE, NOT_PRACTISING, CANCELLED, SUSPENDED]
STATUS_COLOR = {ACTIVE: "#198754", NOT_PRACTISING: "#6c757d",
                CANCELLED: "#dc3545", SUSPENDED: "#9a6700"}
STATUS_SHORT = {NOT_PRACTISING: "אי עיסוק במקצוע"}
UNKNOWN_CITY = {"", "ללא ישוב"}
CITY_ALIAS = {"מודיעין": "מודיעין-מכבים-רעות"}   # same city, official name
TOP_CITIES = 15
TOP_NAMES = 15
HEAT_YEARS = 12
COHORT_MIN = 500
SENIOR = 30
DECADE_FROM = 1950
SENIORITY = [(0, 4), (5, 9), (10, 14), (15, 19), (20, 24), (25, 29), (30, 39), (40, None)]
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def short(status):
    return STATUS_SHORT.get(status, status)


def _city_display(s):
    s = re.sub(r"\s+", " ", s.strip())
    s = re.sub(r"\s*-\s*", "-", s)
    return CITY_ALIAS.get(s, s)


def _city_key(s):
    k = re.sub(r"[\s\-–\"'״׳]", "", s)
    return k.replace("וו", "ו").replace("יי", "י")


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    out = pd.DataFrame({
        "date": pd.to_datetime(df["תאריך קבלת רישיון"].str.strip(), errors="coerce",
                               format="%d/%m/%Y"),
        "first": df["שם פרטי"].str.strip(),
        "last": df["שם משפחה"].str.strip(),
        "status": df["סטטוס"].str.strip().replace("", "לא ידוע"),
    })
    city = df["ישוב"].map(_city_display)
    known = ~city.isin(UNKNOWN_CITY)
    key = city.map(_city_key)
    # Canonical spelling per key: the most frequent variant, ties by name.
    variants = (pd.DataFrame({"key": key[known], "city": city[known]})
                .groupby(["key", "city"]).size().reset_index(name="n")
                .sort_values(["key", "n", "city"], ascending=[True, False, True]))
    canon = variants.drop_duplicates("key").set_index("key")["city"]
    out["city"] = key.map(canon).where(known, "")
    out["year"] = out["date"].dt.year
    return out


def _statuses(df):
    present = set(df["status"])
    order = [s for s in STATUS_ORDER if s in present]
    return order + sorted(present - set(order))


def _status_color(s, i):
    return STATUS_COLOR.get(s)


def insight_status(st_counts, total):
    act = st_counts.get(ACTIVE, 0)
    if total == 0 or act == 0:
        return None
    rest = [f"{n(v)} {('הצהירו על אי עיסוק במקצוע' if s == NOT_PRACTISING else ('רישיונם בוטל' if s == CANCELLED else ('מושעים' if s == SUSPENDED else 'בסטטוס ' + s)))}"
            for s, v in st_counts.items() if s != ACTIVE and v > 0]
    tail = (", ".join(rest[:-1]) + " ו-" + rest[-1]) if len(rest) > 1 else "".join(rest)
    s = f"{pct(act / total * 100)} מהרשומים במאגר פעילים — {n(act)} רואי חשבון"
    return s + (f"; {tail}." if tail else ".")


def insight_peak(per_year, last_full):
    full = per_year[per_year.index <= last_full]
    if len(full) < 10 or last_full not in full.index:
        return None
    peak = int(full.idxmax())
    pv, lv = int(full[peak]), int(full[last_full])
    if peak == last_full:
        return f"{last_full} היא שנת השיא במתן רישיונות: {n(lv)} רישיונות חדשים."
    drop = 1 - lv / pv
    if abs(drop) < 0.1:
        return (f"שנת השיא במתן רישיונות הייתה {peak} ({n(pv)}); ב-{last_full} ניתנו "
                f"{n(lv)} — קרוב לשיא.")
    return (f"שנת השיא במתן רישיונות הייתה {peak}, עם {n(pv)} רישיונות חדשים; ב-{last_full} "
            f"ניתנו {n(lv)} — {pct(drop * 100, 0)} פחות מהשיא.")


def insight_ytd(df, ref, partial):
    if not partial:
        return None
    y = ref.year
    cur = df[(df["year"] == y) & (df["date"] <= ref)]
    md = (df["date"].dt.month * 100 + df["date"].dt.day) <= (ref.month * 100 + ref.day)
    prev = df[(df["year"] == y - 1) & md]
    if len(prev) < 50:
        return None
    c, p = len(cur), len(prev)
    chg = c / p - 1
    if abs(chg) < 0.05:
        trend = f"בדומה לתקופה המקבילה ב-{y - 1} ({n(p)})"
    else:
        trend = (f"{pct(abs(chg) * 100, 0)} {'יותר' if chg > 0 else 'פחות'} מבתקופה המקבילה "
                 f"ב-{y - 1} ({n(p)})")
    return f"מתחילת {y} ועד {d_he(ref)} ניתנו {n(c)} רישיונות חדשים — {trend}."


def insight_cohort(cohort, last_full):
    decs = [d for d in cohort.index if isinstance(d, int) and d + 9 <= last_full
            and cohort.loc[d].sum() >= COHORT_MIN]
    if not decs:
        return None
    recent = max(decs)
    old = recent - 30
    if old not in decs:
        return None

    def sh(d, s):
        row = cohort.loc[d]
        return row.get(s, 0) / row.sum() * 100

    a1, a0 = sh(recent, ACTIVE), sh(old, ACTIVE)
    if a1 - a0 < 5:
        return None
    return (f"ככל שהרישיון ותיק יותר, כך קטן הסיכוי שבעליו עדיין פעיל: מבין מי שקיבלו רישיון "
            f"בשנות ה-{recent}, {pct(a1, 0)} פעילים, לעומת {pct(a0, 0)} מבין מקבלי הרישיון "
            f"בשנות ה-{old} — שבהם {pct(sh(old, NOT_PRACTISING), 0)} הצהירו על אי עיסוק "
            f"ו-{pct(sh(old, CANCELLED), 0)} שרישיונם בוטל.")


def insight_seniority(sen):
    s = sen.dropna()
    if len(s) < 100:
        return None
    return (f"הוותק החציוני של רואה חשבון פעיל הוא {int(s.median())} שנים מאז קבלת הרישיון; "
            f"{pct((s < 10).mean() * 100, 0)} קיבלו רישיון בעשור האחרון, ו-{pct((s >= SENIOR).mean() * 100, 0)} "
            f"מחזיקים בו {SENIOR} שנה ומעלה.")


def insight_cities(cities, known_total):
    if known_total == 0 or len(cities) < 5:
        return None
    top, v = cities.index[0], int(cities.iloc[0])
    if v / known_total < 0.05:
        return None
    top5 = cities.head(5)
    names = ", ".join(top5.index[1:4]) + " ו" + top5.index[4]
    return (f"{top} מובילה עם {n(v)} רואי חשבון רשומים ({pct(v / known_total * 100)}); "
            f"יחד עם {names} מרכזים חמשת הישובים הגדולים "
            f"{pct(top5.sum() / known_total * 100)} מהרשומים שישובם ידוע.")


def insight_missing(df):
    miss = df[df["date"].isna()]
    if len(miss) == 0:
        return None
    canc = (miss["status"] == CANCELLED).mean()
    s = f"ל-{n(len(miss))} רשומות ({pct(len(miss) / len(df) * 100)}) אין תאריך קבלת רישיון"
    if canc == 1:
        s += " — כולן רישיונות שבוטלו"
    elif canc >= 0.8:
        s += f" — {pct(canc * 100)} מהן רישיונות שבוטלו"
    return s + "; הן אינן נכללות בגרפים לפי שנה."


def insight_surname(surnames, total):
    if len(surnames) < 2:
        return None
    (a, va), (b, vb) = list(surnames.items())[:2]
    if va < 1.3 * vb:
        return None
    return (f"שם המשפחה הנפוץ ביותר בקרב רואי החשבון הוא {a} ({n(va)} רשומות, "
            f"{pct(va / total * 100)}), ואחריו {b} ({n(vb)}).")


def _decade_label(d):
    return f"לפני {DECADE_FROM}" if d == "pre" else f"שנות ה-{d}"


def compute(frames):
    df = _prepare(frames["cpa"])
    total = len(df)
    statuses = _statuses(df)
    st_counts = df["status"].value_counts().reindex(statuses).fillna(0).astype(int)
    act_total = int(st_counts.get(ACTIVE, 0))

    dated = df.dropna(subset=["date"])
    ref = dated["date"].max()
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = ref_year - 1 if partial else ref_year
    first_year = int(dated["year"].min())

    years = list(range(first_year, ref_year + 1))
    by_year = (dated.groupby(["year", "status"]).size().unstack(fill_value=0)
               .reindex(years, fill_value=0))
    per_year = by_year.sum(axis=1)
    per_year.index = per_year.index.astype(int)

    # Cohort (licence decade) × current status.
    dec = dated["year"].astype(int) // 10 * 10
    dec_key = dec.where(dec >= DECADE_FROM, -1)
    cohort = dated.groupby([dec_key, "status"]).size().unstack(fill_value=0)
    cohort = cohort.reindex(columns=statuses, fill_value=0).sort_index()
    cohort.index = [("pre" if d == -1 else int(d)) for d in cohort.index]
    cohort_labels = [_decade_label(d) for d in cohort.index]

    # Seniority of active CPAs.
    act = df[df["status"] == ACTIVE]
    sen = (ref_year - act["year"]).where(act["year"].notna())
    sen_rows = []
    for lo, hi in SENIORITY:
        m = sen >= lo
        if hi is not None:
            m &= sen <= hi
        sen_rows.append((f"{lo} ומעלה" if hi is None else (f"עד {hi}" if lo == 0 else f"{lo} עד {hi}"), int(m.sum())))

    # Monthly heatmap, last HEAT_YEARS years.
    hy = list(range(ref_year - HEAT_YEARS + 1, ref_year + 1))
    hd = dated[dated["year"].isin(hy)]
    hm = hd.groupby([hd["year"].astype(int), hd["date"].dt.month]).size()
    cells = []
    for yi, y in enumerate(hy):
        for m in range(1, 13):
            if y == ref_year and m > ref.month:
                continue
            cells.append([m - 1, yi, int(hm.get((y, m), 0))])

    # Cumulative licences by month: reference year vs the two before it.
    cum_series = []
    for y in [ref_year, ref_year - 1, ref_year - 2]:
        sub = dated[dated["year"] == y]
        if sub.empty and y != ref_year:
            continue
        mc = sub.groupby(sub["date"].dt.month).size().reindex(range(1, 13), fill_value=0).cumsum()
        data = [int(v) for v in mc.values]
        if y == ref_year:
            data = [v if i + 1 <= ref.month else None for i, v in enumerate(data)]
        cum_series.append({"name": str(y), "data": data})

    # Settlements.
    known = df[df["city"] != ""]
    cities = _sorted_counts(known["city"])
    top_c = list(cities.head(TOP_CITIES).index)
    city_st = (known[known["city"].isin(top_c)].groupby(["city", "status"]).size()
               .unstack(fill_value=0).reindex(index=top_c, columns=statuses, fill_value=0))
    unknown_city = total - len(known)

    surnames = _sorted_counts(df.loc[df["last"] != "", "last"])
    firsts = _sorted_counts(df.loc[df["first"] != "", "first"])
    recent_first = df[(df["first"] != "") & (df["year"] >= ref_year - 9)]
    firsts_recent = _sorted_counts(recent_first["first"])

    charts = {
        "status": {"names": [short(s) for s in statuses],
                   "values": [int(st_counts[s]) for s in statuses],
                   "colors": [_status_color(s, i) for i, s in enumerate(statuses)]},
        "years": {"x": [str(y) for y in years],
                  "series": [{"name": short(s), "color": _status_color(s, i),
                              "data": [int(v) for v in by_year.get(s, pd.Series(0, index=years))]}
                             for i, s in enumerate(statuses)],
                  "zoom_from": years.index(1970) if 1970 in years else 0},
        "cohort": {"x": cohort_labels,
                   "series": [{"name": short(s), "color": _status_color(s, i),
                               "data": [round(float(cohort.loc[d, s] / cohort.loc[d].sum() * 100), 1)
                                        for d in cohort.index]}
                              for i, s in enumerate(statuses)]},
        "seniority": {"names": [k for k, _ in sen_rows], "values": [v for _, v in sen_rows]},
        "heat": {"x": MONTHS_SHORT, "y": [str(y) for y in hy], "cells": cells,
                 "max": max([c[2] for c in cells] or [1])},
        "cumulative": {"x": MONTHS_SHORT, "series": cum_series},
        "cities": {"names": top_c,
                   "series": [{"name": short(s), "color": _status_color(s, i),
                               "data": [int(city_st.loc[c, s]) for c in top_c]}
                              for i, s in enumerate(statuses)]},
        "surnames": {"names": list(surnames.head(TOP_NAMES).index),
                     "values": [int(v) for v in surnames.head(TOP_NAMES).values]},
        "firsts": {"names": list(firsts_recent.head(TOP_NAMES).index),
                   "values": [int(v) for v in firsts_recent.head(TOP_NAMES).values]},
    }

    rules = [
        ("status", insight_status(st_counts, total)),
        ("peak", insight_peak(per_year, last_full)),
        ("ytd", insight_ytd(dated, ref, partial)),
        ("cohort", insight_cohort(cohort, last_full)),
        ("seniority", insight_seniority(sen)),
        ("cities", insight_cities(cities, len(known))),
        ("surname", insight_surname(surnames, total)),
        ("missing", insight_missing(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    lf = int(per_year.get(last_full, 0))
    lp = int(per_year.get(last_full - 1, 0))
    chg = (lf / lp - 1) if lp else 0
    new_tone = "ok" if chg >= 0.05 else ("warn" if chg <= -0.05 else "brand")
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "active": {"value": act_total, "display": n(act_total), "tone": "ok"},
        "new": {"value": lf, "display": n(lf), "tone": new_tone},
        "cities": {"value": int(cities.size), "display": n(cities.size), "tone": "brand"},
    }
    chg_txt = ("" if not lp else
               f", {'עלייה' if chg >= 0 else 'ירידה'} של {abs(chg) * 100:.0f}% לעומת {last_full - 1}")

    partial_note = (f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else "")
    pre_n = int(cohort.loc["pre"].sum()) if "pre" in cohort.index else 0
    labels = {
        "lede": (f"מרשם רישיונות ראיית החשבון של משרד המשפטים: {n(total)} רשומות, מהן "
                 f"{n(act_total)} רואי חשבון פעילים, מ-{n(cities.size)} ישובים. הרישיון "
                 f"המוקדם במאגר ניתן ב-{first_year}, והאחרון ב-{d_he(ref)}."),
        "active_kpi": f"רואי חשבון פעילים ({act_total / total * 100:.1f}% מהרשומים)",
        "new_kpi": f"רישיונות חדשים ב-{last_full}{chg_txt}",
        "status_note": "הסטטוס הנוכחי של כל רישיון במאגר.",
        "status_aria": (f"תרשים טבעת: רישיונות לפי סטטוס — {n(act_total)} פעילים מתוך {n(total)}."),
        "status_caption": "מספר רישיונות לפי סטטוס.",
        "years_note": (f"רישיונות שניתנו בכל שנה, לפי הסטטוס הנוכחי של בעליהם. ניתן לגלול "
                       f"ולהגדיל את טווח השנים.{partial_note}"),
        "years_aria": (f"גרף עמודות מוערמות: רישיונות שניתנו בכל שנה מ-{first_year} עד {ref_year}, "
                       f"לפי סטטוס נוכחי; שיא ב-{int(per_year[per_year.index <= last_full].idxmax())}."),
        "cohort_note": ("התפלגות הסטטוס הנוכחי לפי עשור קבלת הרישיון."
                        + (f" {n(pre_n)} רישיונות מלפני {DECADE_FROM} מקובצים יחד." if pre_n else "")),
        "cohort_aria": "תרשים עמודות מוערמות באחוזים: סטטוס נוכחי לפי עשור קבלת הרישיון.",
        "cohort_caption": "שיעור כל סטטוס (באחוזים) ומספר הרישיונות, לפי עשור קבלת הרישיון.",
        "seniority_note": f"שנים מאז קבלת הרישיון, נכון ל-{ref_year}, בקרב רואי החשבון הפעילים.",
        "seniority_aria": (f"תרשים עמודות: רואי חשבון פעילים לפי ותק, חציון "
                           f"{int(sen.dropna().median())} שנים."),
        "seniority_caption": "מספר רואי חשבון פעילים לפי קבוצת ותק בשנים.",
        "heat_note": (f"מספר הרישיונות שניתנו בכל חודש, {hy[0]}–{ref_year}. חלק גדול מהרישיונות "
                      f"ניתן במועדים מרוכזים, ולכן חודשים בודדים בולטים."),
        "heat_aria": f"מפת חום: רישיונות חדשים לפי חודש ושנה, {hy[0]} עד {ref_year}.",
        "cum_note": (f"מספר הרישיונות המצטבר מתחילת השנה, {ref_year} לעומת השנתיים שקדמו לה."
                     + (f" נתוני {ref_year} עד {d_he(ref)}." if partial else "")),
        "cum_aria": f"גרף קווים: רישיונות מצטברים לפי חודש, {cum_series[-1]['name']} עד {ref_year}.",
        "cum_caption": "רישיונות מצטברים מתחילת השנה, לפי חודש.",
        "cities_note": (f"{TOP_CITIES} הישובים עם מספר רואי החשבון הרשומים הגדול ביותר, לפי סטטוס. "
                        f"איות שמות הישובים במקור אוחד (למשל קרית/קריית)"
                        + (f"; {n(unknown_city)} רשומות ללא ישוב אינן נכללות." if unknown_city else ".")),
        "cities_aria": (f"תרשים עמודות אופקי מוערם: {TOP_CITIES} הישובים המובילים — "
                        f"{top_c[0]} בראש עם {n(cities.iloc[0])} רשומים."),
        "cities_caption": f"רשומים לפי ישוב ({TOP_CITIES} המובילים) וסטטוס.",
        "surnames_note": f"{TOP_NAMES} שמות המשפחה הנפוצים בכלל הרשומים במאגר.",
        "surnames_aria": (f"תרשים עמודות אופקי: {TOP_NAMES} שמות המשפחה הנפוצים — "
                          f"{surnames.index[0]} בראש."),
        "surnames_caption": "מספר רשומים לפי שם משפחה.",
        "firsts_note": (f"{TOP_NAMES} השמות הפרטיים הנפוצים בקרב מי שקיבלו רישיון "
                        f"ב-{ref_year - 9}–{ref_year}."),
        "firsts_aria": (f"תרשים עמודות אופקי: {TOP_NAMES} השמות הפרטיים הנפוצים בקרב בעלי "
                        f"רישיון מ-{ref_year - 9} ואילך."),
        "firsts_caption": "מספר בעלי רישיון לפי שם פרטי.",
    }
    tables = {
        "status": [{"name": short(s), "count": n(st_counts[s]),
                    "share": f"{st_counts[s] / total * 100:.1f}%"} for s in statuses],
        "status_cols": [short(s) for s in statuses],
        "cohort": [{"name": lab, "total": n(cohort.loc[d].sum()),
                    "shares": [f"{cohort.loc[d, s] / cohort.loc[d].sum() * 100:.1f}%" for s in statuses]}
                   for d, lab in zip(cohort.index, cohort_labels)],
        "seniority": [{"bucket": k, "count": n(v)} for k, v in sen_rows],
        "cumulative": [{"month": MONTHS_SHORT[i],
                        "vals": [("—" if s["data"][i] is None else n(s["data"][i])) for s in cum_series]}
                       for i in range(12)],
        "cum_cols": [s["name"] for s in cum_series],
        "cities": [{"name": c, "total": n(cities[c]),
                    "vals": [n(city_st.loc[c, s]) for s in statuses]} for c in top_c],
        "surnames": [{"name": k, "count": n(v)} for k, v in surnames.head(TOP_NAMES).items()],
        "firsts": [{"name": k, "count": n(v)} for k, v in firsts_recent.head(TOP_NAMES).items()],
    }

    return {
        "agent_data": {
            "summary_he": (f"מרשם רואי החשבון — איתור רואה חשבון לפי שם או מספר רישיון: {n(total)} רישיונות, מהם "
                           f"{n(act_total)} פעילים, עם יישוב וסטטוס, מ-{first_year} ועד {ref_year}."),
            "dataset_kind": "registry",
            "related_ids": ["669b2652-f75b-4de3-8e6b-0dfa17accef5",
                            "1806c96c-9cc4-47bf-98b3-80a18f061f98",
                            "176f2727-476e-440e-bc8d-5d3461ea0e76",
                            "01aeaf5c-59a2-4ddc-a616-31b85621bfe2"],
            "suggested_tags": ["רואי חשבון", "רישוי מקצועי", "משרד המשפטים",
                               "מקצועות חופשיים", "מרשמים מקצועיים"],
            "temporal_coverage": f"{first_year}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
