"""מאגר מעונות יום: משרד העבודה (האגף למעונות יום ומשפחתונים).

One row per supervised childcare facility (`סמל מעון` is unique) for one
school year (`שנת לימוד`, e.g. 2024 = תשפ"ה). Each row carries the facility
type (מעון / משפחתון / צהרון), the ministry district, the locality, the
operating organisation, the opening date and, for daycare centres only, the
registered capacity per age group (תינוקות / פעוטות / בוגרים).

The page is a lookup + composition view: type mix, district x type,
localities, seats per locality and per district by age group, centre size,
opening year of the facilities active today, and the operating networks.

Growth: the file is replaced per school year. If several years ever appear
in one file, only the latest is shown (disclosed in the lede). Category axes
are top-N + "אחר"; facility types, districts and organisations flow through
from the data (no hardcoded lists). The opening-year axis keeps the last
OPEN_YEARS calendar years and buckets everything earlier, and the latest
calendar year is flagged partial when the data's last opening date is
before December.
"""
import re

import pandas as pd

TOP_CITIES = 15
TOP_SEAT_CITIES = 12
TOP_ORGS = 12
OPEN_YEARS = 20
SEAT_CITY_MIN = 20       # min centres for the "largest average size" rule
MIX_CITY_MIN = 100       # min facilities for a city to enter the mix contrast
MIX_SHARE_MIN = 0.6      # a type must hold this share of a city to be stated
SEPT_SHARE_MIN = 0.4     # September openings share worth stating
NO_DISTRICT = "ללא מחוז"
OTHER = "אחר"
LRI, PDI = "⁦", "⁩"

AGE_COLS = [("תפוסת תינוקות", "תינוקות"),
            ("תפוסת פעוטות", "פעוטות"),
            ("תפוסת בוגרים", "בוגרים")]

SIZE_BANDS = [(0, 0, "ללא מקומות"), (1, 40, "עד 40"), (41, 60, "41 עד 60"),
              (61, 80, "61 עד 80"), (81, 100, "81 עד 100"),
              (101, 150, "101 עד 150"), (151, None, "מעל 150")]

HEB_LETTERS = re.compile(r"[֐-׿]")


FINALS = str.maketrans("ךםןףץ", "כמנפצ")


def unfinal(s):
    return s.translate(FINALS)


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def pct_plain(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def clean(s):
    return " ".join(str(s).replace(" ", " ").split())


def num(s):
    return pd.to_numeric(s.map(lambda v: clean(v).replace(",", "")), errors="coerce")


def order_counts(series):
    vc = series.value_counts()
    return sorted(((k, int(v)) for k, v in vc.items()), key=lambda kv: (-kv[1], kv[0]))


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = " ו-" if last[:1].isdigit() else " ו"
    return ", ".join(items[:-1]) + conj + last


def _prepare(raw):
    types = raw["תיאור סוג מעון"].map(clean)
    df = pd.DataFrame({
        "id": raw["סמל מעון"].map(clean),
        "year": num(raw["שנת לימוד"]),
        "year_he": raw["שנת לימוד עברי"].map(clean),
        "type": types.where(types != "", "לא צוין"),
        "district_raw": raw["תיאור מחוז"].map(clean),
        "city": raw["שם עיר"].map(clean),
        "org": raw["שם ארגון"].map(clean),
        "opened": pd.to_datetime(raw["תאריך פתיחה"].map(clean), errors="coerce", format="%Y-%m-%d"),
    })
    for col, key in AGE_COLS:
        df[key] = num(raw[col])
    df = df[df["id"] != ""].copy()
    years = sorted(int(y) for y in df["year"].dropna().unique())
    latest = years[-1] if years else None
    dropped = 0
    if latest is not None:
        keep = df["year"] == latest
        dropped = int((~keep).sum())
        df = df[keep].copy()
    # A facility type in the district column (e.g. "צהרונים") is not a
    # district; compare with final letters folded so plurals match.
    type_stems = {unfinal(t) for t in set(df["type"])}

    def district(v):
        if not v or not HEB_LETTERS.search(v) or any(unfinal(v).startswith(t) for t in type_stems):
            return NO_DISTRICT
        return v

    df["district"] = df["district_raw"].map(district)
    df["city"] = df["city"].where(df["city"] != "", "לא צוין")
    df["org"] = df["org"].where(df["org"] != "", "לא צוין")
    df = df.sort_values(["id", "city", "org"], kind="mergesort").reset_index(drop=True)
    year_he = ""
    if len(df):
        vals = order_counts(df["year_he"][df["year_he"] != ""])
        year_he = vals[0][0] if vals else ""
    return df, latest, year_he, dropped


def _stack_by_type(df, col, cats, types):
    ct = pd.crosstab(df[col], df["type"])
    series = []
    for t in types:
        data = [int(ct.at[c, t]) if (c in ct.index and t in ct.columns) else 0 for c in cats]
        series.append({"name": t, "data": data})
    totals = [sum(s["data"][i] for s in series) for i in range(len(cats))]
    table = [{"name": c, "total": n(totals[i]), "cells": [n(s["data"][i]) for s in series]}
             for i, c in enumerate(cats)]
    return {"names": cats, "series": series, "totals": totals}, table


def _top_with_other(df, col, top):
    order = order_counts(df[col])
    names = [k for k, _ in order[:top]]
    rest = len(order) - len(names)
    bucket = df[col].where(df[col].isin(names), OTHER)
    cats = names + ([OTHER] if rest > 0 else [])
    return bucket, cats, rest


def compute(frames):
    df, year, year_he, dropped = _prepare(frames["main"])
    total = len(df)
    type_order = order_counts(df["type"])
    types = [t for t, _ in type_order]
    tcount = dict(type_order)
    year_label = year_he if year_he else (str(year) if year is not None else "")

    # ---- type mix
    type_chart = {"names": types, "values": [tcount[t] for t in types]}
    type_table = [{"name": t, "count": n(tcount[t]), "share": pct_plain(tcount[t] / total)}
                  for t in types]

    # ---- districts x type (unknown district last)
    d_order = [d for d, _ in order_counts(df["district"]) if d != NO_DISTRICT]
    if (df["district"] == NO_DISTRICT).any():
        d_order.append(NO_DISTRICT)
    dist_chart, dist_table = _stack_by_type(df, "district", d_order, types)
    n_no_district = int((df["district"] == NO_DISTRICT).sum())

    # ---- cities
    n_cities = int(df.loc[df["city"] != "לא צוין", "city"].nunique())
    cb, c_cats, c_rest = _top_with_other(df, "city", TOP_CITIES)
    tmp = df.assign(cityb=cb)
    city_chart, city_table = _stack_by_type(tmp, "cityb", c_cats, types)
    top_city_share = sum(city_chart["totals"][:len(c_cats) - (1 if c_rest else 0)]) / total if total else 0

    # ---- capacity (rows that report any seat figure)
    ages = [k for _, k in AGE_COLS]
    # Seat figures are reported for one facility type (daycare centres); the
    # type is picked from the data and stray figures on other types ignored.
    has_cap = df[ages].notna().any(axis=1)
    cap_type = order_counts(df.loc[has_cap, "type"])[0][0] if has_cap.any() else ""
    cap = df[has_cap & (df["type"] == cap_type)].copy()
    cap[ages] = cap[ages].fillna(0)
    cap["seats"] = cap[ages].sum(axis=1)
    n_cap = len(cap)
    seats_total = int(cap["seats"].sum())
    age_totals = [int(cap[a].sum()) for a in ages]

    s_order = sorted(cap.groupby("city")["seats"].sum().items(), key=lambda kv: (-kv[1], kv[0]))
    s_names = [k for k, _ in s_order[:TOP_SEAT_CITIES]]
    sc = cap[cap["city"].isin(s_names)]
    seat_city_chart = {
        "names": s_names,
        "series": [{"name": a, "data": [int(sc.loc[sc["city"] == c, a].sum()) for c in s_names]} for a in ages],
        "centres": [int((sc["city"] == c).sum()) for c in s_names],
    }
    seat_city_table = [{
        "name": c,
        "centres": n(seat_city_chart["centres"][i]),
        "cells": [n(s["data"][i]) for s in seat_city_chart["series"]],
        "total": n(sum(s["data"][i] for s in seat_city_chart["series"])),
    } for i, c in enumerate(s_names)]

    sd_names = [d for d in d_order if (cap["district"] == d).any()]
    seat_dist_chart = {
        "names": sd_names,
        "series": [{"name": a, "data": [int(cap.loc[cap["district"] == d, a].sum()) for d in sd_names]} for a in ages],
    }
    seat_dist_table = [{
        "name": d,
        "cells": [n(s["data"][i]) for s in seat_dist_chart["series"]],
        "total": n(sum(s["data"][i] for s in seat_dist_chart["series"])),
    } for i, d in enumerate(sd_names)]

    # ---- centre size bands
    size_names, size_values = [], []
    for lo, hi, lab in SIZE_BANDS:
        m = cap["seats"] >= lo
        if hi is not None:
            m &= cap["seats"] <= hi
        k = int(m.sum())
        if lab == "ללא מקומות" and k == 0:
            continue
        size_names.append(lab)
        size_values.append(k)
    size_chart = {"names": size_names, "values": size_values}
    size_table = [{"name": a, "count": n(b), "share": pct_plain(b / n_cap) if n_cap else "0%"}
                  for a, b in zip(size_names, size_values)]
    median_seats = float(cap["seats"].median()) if n_cap else 0.0
    mean_seats = float(cap["seats"].mean()) if n_cap else 0.0

    # ---- opening year of active facilities
    op = df[df["opened"].notna()].copy()
    op["y"] = op["opened"].dt.year.astype(int)
    open_chart = None
    open_table = []
    partial = False
    last_full = None
    y_counts = {}
    if len(op):
        y_max = int(op["y"].max())
        max_date = op["opened"].max()
        partial = int(max_date.month) < 12
        y_min_shown = y_max - OPEN_YEARS + 1
        cats, keys = [], []
        if int(op["y"].min()) < y_min_shown:
            cats.append(f"עד {y_min_shown - 1}")
            keys.append(None)
        for y in range(max(y_min_shown, int(op["y"].min())), y_max + 1):
            cats.append(f"{y} (חלקית)" if (partial and y == y_max) else str(y))
            keys.append(y)
        ct = pd.crosstab(op["y"], op["type"])
        series = []
        for t in types:
            data = []
            for k in keys:
                col = ct[t] if t in ct.columns else pd.Series(dtype=int)
                if k is None:
                    data.append(int(col[col.index < y_min_shown].sum()))
                else:
                    data.append(int(col.get(k, 0)))
            series.append({"name": t, "data": data})
        totals = [sum(s["data"][i] for s in series) for i in range(len(cats))]
        open_chart = {"names": cats, "series": series, "totals": totals}
        open_table = [{"name": c, "total": n(totals[i]), "cells": [n(s["data"][i]) for s in series]}
                      for i, c in enumerate(cats)]
        y_counts = {int(k): int(v) for k, v in op["y"].value_counts().items()}
        last_full = y_max - 1 if partial else y_max

    # ---- organisations
    n_orgs = int(df.loc[df["org"] != "לא צוין", "org"].nunique())
    ob, o_cats, o_rest = _top_with_other(df, "org", TOP_ORGS)
    org_names_only = [c for c in o_cats if c != OTHER]
    tmp = df[df["org"].isin(org_names_only)]
    org_chart, org_table = _stack_by_type(tmp, "org", org_names_only, types)
    org_counts = order_counts(df["org"][df["org"] != "לא צוין"])
    single_orgs = sum(1 for _, v in org_counts if v == 1)
    top10_share = sum(v for _, v in org_counts[:10]) / total if total else 0

    # ================= insights =================
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    # type mix
    if len(types) >= 2:
        parts = [f"{t} {n(tcount[t])} ({pct(tcount[t] / total)})" for t in types]
        add("types", f"המאגר מונה {n(total)} מסגרות לגיל הרך: " + join_he(parts) + ".")

    # leading district and its dominant type
    real_d = [d for d in d_order if d != NO_DISTRICT]
    if len(real_d) >= 2:
        d0 = real_d[0]
        d0n = dist_chart["totals"][0]
        if d0n / total >= 0.3:
            sub = df[df["district"] == d0]["type"]
            tt, tn = order_counts(sub)[0]
            txt = f"מחוז {d0} מרכז {n(d0n)} מסגרות ({pct(d0n / total)} מהמאגר)"
            if tn / d0n >= 0.5:
                txt += f", ו-{n(tn)} מהן ({pct(tn / d0n)}) הן מסוג {tt}"
            add("district", txt + ".")

    # city mix contrast
    big = [c for c, k in order_counts(df["city"]) if k >= MIX_CITY_MIN and c != "לא צוין"]
    if big and len(types) >= 2:
        picks = []
        for t in types:
            best = None
            for c in big:
                sub = df[df["city"] == c]
                share = float((sub["type"] == t).mean())
                key = (-share, c)
                if best is None or key < best[0]:
                    best = (key, c, int((sub["type"] == t).sum()), len(sub), share)
            if best and best[4] >= MIX_SHARE_MIN:
                picks.append((best[4], t, best[1], best[2], best[3]))
        picks.sort(key=lambda p: (-p[0], p[1]))
        cities_used = set()
        sents = []
        for share, t, c, k, tot in picks:
            if c in cities_used:
                continue
            cities_used.add(c)
            sents.append(f"ב{c} {n(k)} מתוך {n(tot)} מסגרות ({pct(share)}) הן מסוג {t}")
            if len(sents) == 2:
                break
        if len(sents) == 2:
            add("city_mix", "התמהיל משתנה מאוד בין הערים: " + sents[0] + ", ואילו " + sents[1] + ".")

    # largest average centre size
    if n_cap:
        g = cap.groupby("city")["seats"].agg(["count", "sum"])
        g = g[g["count"] >= SEAT_CITY_MIN]
        if len(g):
            g = g.assign(avg=g["sum"] / g["count"])
            rows = sorted(g.iterrows(), key=lambda kv: (-kv[1]["avg"], kv[0]))
            c, r = rows[0]
            if r["avg"] >= 1.25 * mean_seats:
                add("big_centres",
                    f"ב{c} {n(r['count'])} מסגרות מסוג {cap_type} ובהן {n(r['sum'])} מקומות, "
                    f"ממוצע של {r['avg']:.0f} מקומות למסגרת לעומת {mean_seats:.0f} בכלל המאגר.")

    # age mix of seats
    if seats_total > 0:
        parts = [f"{a} {n(v)} ({pct(v / seats_total)})" for a, v in zip(ages, age_totals)]
        add("ages", f"{n(n_cap)} מסגרות מסוג {cap_type} מדווחות על תפוסה של {n(seats_total)} מקומות: "
            + join_he(parts) + f". החציון הוא {median_seats:.0f} מקומות למסגרת.")

    # recent openings
    if last_full is not None and (last_full - 1) in y_counts and last_full in y_counts:
        a, b = y_counts[last_full - 1], y_counts[last_full]
        ch = (b - a) / a if a else 0
        since = last_full - 4
        recent = sum(v for y, v in y_counts.items() if y >= since)
        share = recent / len(op)
        if share >= 0.25:
            if abs(ch) < 0.05:
                trend = f"דומה ל-{n(a)} ב-{last_full - 1}"
            elif ch > 0:
                trend = f"עלייה של {pct(ch, 0)} לעומת {n(a)} ב-{last_full - 1}"
            else:
                trend = f"ירידה של {pct(-ch, 0)} לעומת {n(a)} ב-{last_full - 1}"
            add("recent",
                f"{pct(share)} מהמסגרות הפעילות היום נפתחו מ-{since} ואילך. "
                f"ב-{last_full} נפתחו {n(b)} מסגרות שעדיין פעילות, {trend} "
                "(הספירה כוללת רק מסגרות שפעילות כיום).")

    # September openings
    if len(op):
        sept = float((op["opened"].dt.month == 9).mean())
        if sept >= SEPT_SHARE_MIN:
            add("september", f"{pct(sept)} מהמסגרות נפתחו בחודש ספטמבר, עם תחילת שנת הלימודים.")

    # concentration of operators
    if org_counts and total:
        o0, v0 = org_counts[0]
        if top10_share >= 0.25:
            add("orgs",
                f"{n(n_orgs)} ארגונים מפעילים את המסגרות. עשרת הגדולים מפעילים {pct(top10_share)} מהן, "
                f"והגדול שבהם, {o0}, מפעיל {n(v0)}; {n(single_orgs)} ארגונים מפעילים מסגרת אחת בלבד.")

    # unknown district disclosure
    if n_no_district:
        add("no_district",
            f"ל-{n(n_no_district)} מסגרות ({pct(n_no_district / total)}) אין מחוז תקין במאגר; "
            f"הן מוצגות בתרשים המחוזות בנפרד, תחת \"{NO_DISTRICT}\".")

    # ================= KPIs + labels =================
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "seats": {"value": seats_total, "display": n(seats_total), "tone": "brand"},
        "cities": {"value": n_cities, "display": n(n_cities), "tone": "brand"},
    }
    if last_full is not None and last_full in y_counts:
        b = y_counts[last_full]
        a = y_counts.get(last_full - 1, 0)
        tone = "ok" if a and b > a * 1.05 else ("warn" if a and b < a * 0.95 else "brand")
        kpis["opened"] = {"value": b, "display": n(b), "tone": tone}
    else:
        kpis["opened"] = {"value": n_orgs, "display": n(n_orgs), "tone": "brand"}

    multi_year = (f" המאגר כולל כמה שנות לימוד, ומוצגת האחרונה בלבד ({n(dropped)} רשומות משנים קודמות לא נכללו)."
                  if dropped else "")
    top_type = types[0] if types else ""
    lede = (f"מאגר המסגרות לגיל הרך בפיקוח משרד העבודה לשנת הלימודים {year_label}: {n(total)} "
            f"מסגרות ({join_he(types)}) ב-{n(n_cities)} יישובים, בהפעלת {n(n_orgs)} ארגונים. "
            f"לכל מסגרת מופיעים סמל המעון, סוג המסגרת, היישוב והכתובת, הארגון המפעיל ותאריך הפתיחה, "
            f"ולמעונות גם התפוסה לפי קבוצת גיל.{multi_year}")

    summary = (f"איתור מעון יום, משפחתון או צהרון מוכר לפי שם, יישוב או סמל מעון: "
               f"{n(total)} מסגרות ב-{n(n_cities)} יישובים, שנת {year_label}.")
    if len(summary) > 155:
        summary = f"איתור מעון יום מוכר לפי שם, יישוב או סמל מעון: {n(total)} מסגרות ב-{n(n_cities)} יישובים."

    labels = {
        "lede": lede,
        "total_kpi": f"מסגרות במאגר ({year_label})",
        "seats_kpi": f"מקומות לפי התפוסה הרשומה, מסגרות מסוג {cap_type}" if cap_type else "מקומות לפי התפוסה הרשומה",
        "cities_kpi": "יישובים",
        "opened_kpi": (f"מסגרות פעילות שנפתחו ב-{last_full}" if "opened" in kpis and last_full in y_counts
                       else "ארגונים מפעילים"),
        "type_note": (f"{top_type} הוא הסוג הנפוץ במאגר, עם {n(tcount[top_type])} מסגרות "
                      f"({pct(tcount[top_type] / total)})." if top_type else ""),
        "type_aria": "תרשים טבעת: מסגרות לפי סוג. " + "; ".join(f"{t}: {n(tcount[t])}" for t in types) + ".",
        "dist_note": (f"מספר המסגרות בכל מחוז של משרד העבודה, לפי סוג המסגרת. "
                      f"מחוז {real_d[0]} מוביל עם {n(dist_chart['totals'][0])}." if real_d else ""),
        "dist_aria": "תרשים עמודות מוערמות: מסגרות לפי מחוז וסוג. " + "; ".join(
            f"{d}: {n(t)}" for d, t in zip(dist_chart["names"], dist_chart["totals"])) + ".",
        "city_note": (f"{TOP_CITIES if c_rest else len(c_cats)} היישובים עם הכי הרבה מסגרות מרכזים "
                      f"{pct(top_city_share)} מהמאגר. הצבעים מראים את התמהיל השונה בין הערים."),
        "city_aria": "תרשים עמודות מוערמות: היישובים עם מספר המסגרות הגבוה ביותר, לפי סוג. " + "; ".join(
            f"{c}: {n(t)}" for c, t in list(zip(city_chart["names"], city_chart["totals"]))[:5]) + ".",
        "seat_city_note": (f"המקומות לפי התפוסה הרשומה במסגרות מסוג {cap_type}, לפי קבוצת גיל, ב-{len(s_names)} "
                           f"היישובים עם הכי הרבה מקומות. {s_names[0]} מובילה עם "
                           f"{seat_city_table[0]['total']} מקומות ב-{seat_city_table[0]['centres']} מסגרות."
                           if s_names else ""),
        "seat_city_aria": "תרשים עמודות מוערמות: מקומות לפי יישוב וקבוצת גיל. " + "; ".join(
            f"{r['name']}: {r['total']}" for r in seat_city_table[:5]) + ".",
        "seat_dist_note": (f"סך המקומות לפי מחוז וקבוצת גיל: {join_he(f'{a} {n(v)}' for a, v in zip(ages, age_totals))}."
                           if n_cap else ""),
        "seat_dist_aria": "תרשים עמודות מוערמות: מקומות לפי מחוז וקבוצת גיל. " + "; ".join(
            f"{r['name']}: {r['total']}" for r in seat_dist_table) + ".",
        "size_note": (f"התפלגות {n(n_cap)} המסגרות מסוג {cap_type} לפי סך המקומות. "
                      f"החציון הוא {median_seats:.0f} מקומות, הממוצע {mean_seats:.0f}." if n_cap else ""),
        "size_aria": "תרשים עמודות: מסגרות לפי גודל (סך המקומות). " + "; ".join(
            f"{a}: {n(b)}" for a, b in zip(size_names, size_values)) + ".",
        "open_note": ("המסגרות הפעילות היום לפי שנת הפתיחה שלהן. מסגרות שנסגרו אינן במאגר, ולכן השנים "
                      "המוקדמות נראות דלילות יותר מכפי שהיו."
                      + (f" שנת {open_chart['names'][-1].split(' ')[0]} חלקית: הנתונים מגיעים עד "
                         f"{op['opened'].max().strftime('%m/%Y')}." if partial and open_chart else "")),
        "open_aria": ("תרשים עמודות מוערמות: מסגרות פעילות לפי שנת פתיחה וסוג. "
                      + (f"שנת {last_full}: {n(y_counts.get(last_full, 0))} מסגרות." if last_full else "")),
        "org_note": (f"{len(org_names_only)} הארגונים המפעילים הכי הרבה מסגרות, לפי סוג. "
                     f"עשרת הגדולים מפעילים {pct(top10_share)} מהמאגר."),
        "org_aria": "תרשים עמודות מוערמות: הארגונים המפעילים הכי הרבה מסגרות. " + "; ".join(
            f"{c}: {n(t)}" for c, t in list(zip(org_chart["names"], org_chart["totals"]))[:5]) + ".",
    }

    temporal = f"{year}/{year + 1}" if year is not None else None

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "spatial_coverage": "ישראל",
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "types": type_chart,
            "districts": dist_chart,
            "cities": city_chart,
            "seat_cities": seat_city_chart,
            "seat_districts": seat_dist_chart,
            "sizes": size_chart,
            "opened": open_chart,
            "orgs": org_chart,
        },
        "tables": {
            "types": type_table,
            "districts": dist_table,
            "cities": city_table,
            "seat_cities": seat_city_table,
            "seat_districts": seat_dist_table,
            "sizes": size_table,
            "opened": open_table,
            "orgs": org_table,
            "type_names": types,
            "ages": ages,
        },
        "flags": {"has_cap": n_cap > 0, "has_open": open_chart is not None},
        "insights": insights,
        "labels": labels,
    }
