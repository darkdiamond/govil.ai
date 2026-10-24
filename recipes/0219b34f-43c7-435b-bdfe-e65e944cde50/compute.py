"""כלי צמ"ה — the register of active heavy engineering equipment.

One row per active machine (~185k). "Now" is the latest registration date
in the register (its data vintage), never the wall clock; the year of that
date is partial unless it reaches late December. Only the columns used here
are kept after load, to stay light on memory.
"""
import pandas as pd

TOP_N = 12
HEAT_TYPES = 10
TREND_FROM = 1990
ELECTRIC = {"סוללות", "רשת חשמל"}
AGE_BUCKETS = [(0, 4), (5, 9), (10, 14), (15, 19), (20, 29), (30, None)]
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def bucket_label(lo, hi):
    return f"{lo}+" if hi is None else f"{lo}–{hi}"


def _prepare(df):
    out = pd.DataFrame({
        "type": df["sug_tzama_nm"].str.strip(),
        "maker": df["shilda_totzar_en_nm"].str.strip(),
        "drive": df["hanaa_nm"].str.strip(),
        "built": pd.to_numeric(df["shnat_yitzur"], errors="coerce"),
        "reg": pd.to_datetime(df["rishum_date"], errors="coerce", format="%Y-%m-%d"),
    })
    out["type"] = out["type"].replace("", "לא ידוע")
    out["maker"] = out["maker"].replace("", "לא ידוע")
    out["drive_grp"] = out["drive"].map(
        lambda d: "חשמלי" if d in ELECTRIC else ("סולר" if d == "סולר" else "אחר / לא ידוע"))
    return out


def _top(counts, k):
    counts = counts.sort_index().sort_values(ascending=False, kind="stable")
    top = counts.head(k)
    other = int(counts.iloc[k:].sum())
    names = list(top.index) + (["אחר"] if other else [])
    vals = [int(v) for v in top.values] + ([other] if other else [])
    return names, vals


def insight_top_type(types, total):
    name, v = types.index[0], types.iloc[0]
    forklifts = types[[t.startswith("מלגזה") for t in types.index]].sum()
    s = f"הסוג הנפוץ ביותר הוא {name} ({n(v)} כלים, {pct(v / total * 100)})."
    if forklifts / total >= 0.2:
        s += f" מלגזות מכל הסוגים מהוות יחד {pct(forklifts / total * 100)} מהמאגר."
    return s


def insight_forklift_electric(df, last_full):
    f = df[df["type"].isin(["מלגזה מנוע חשמל", "מלגזה מנוע שריפה"]) & df["reg"].notna()]
    by = f.groupby([f["reg"].dt.year, "type"]).size().unstack(fill_value=0)
    if last_full not in by.index or (last_full - 10) not in by.index:
        return None

    def share(y):
        row = by.loc[y]
        tot = row.sum()
        return None if tot == 0 else row.get("מלגזה מנוע חשמל", 0) / tot

    s0, s1 = share(last_full - 10), share(last_full)
    if s0 is None or s1 is None:
        return None
    if abs(s1 - s0) < 0.03:
        return (f"שיעור המלגזות החשמליות מבין המלגזות החדשות שנרשמו נותר דומה: "
                f"{pct(s0 * 100)} ב-{last_full - 10} ו-{pct(s1 * 100)} ב-{last_full}.")
    word = "עלה" if s1 > s0 else "ירד"
    lead = (" — רוב המלגזות החדשות כבר חשמליות" if s1 > 0.5 and s0 <= 0.5 else "")
    return (f"שיעור המלגזות החשמליות מבין המלגזות שנרשמו {word} מ-{pct(s0 * 100)} "
            f"ב-{last_full - 10} ל-{pct(s1 * 100)} ב-{last_full}{lead}.")


def insight_registrations(per_year, last_full):
    if last_full not in per_year.index or (last_full - 1) not in per_year.index:
        return None
    v1, v0 = per_year[last_full], per_year[last_full - 1]
    if v0 == 0:
        return None
    chg = v1 / v0 - 1
    window = per_year[(per_year.index >= TREND_FROM) & (per_year.index <= last_full)]
    record = " — שנת השיא ברישום כלים שעדיין פעילים" if window.idxmax() == last_full else ""
    if abs(chg) < 0.03:
        return f"ב-{last_full} נרשמו {n(v1)} כלים שעדיין פעילים, בדומה ל-{last_full - 1}{record}."
    word = "יותר" if chg > 0 else "פחות"
    return (f"ב-{last_full} נרשמו {n(v1)} כלים שעדיין פעילים — {pct(abs(chg) * 100)} {word} "
            f"מאשר ב-{last_full - 1}{record}.")


def insight_age(ages):
    a = ages.dropna()
    if a.empty:
        return None
    old = (a >= 20).mean()
    return (f"הגיל החציוני של כלי צמ\"ה פעיל הוא {int(a.median())} שנים (לפי שנת ייצור); "
            f"{pct(old * 100)} מהכלים בני 20 ומעלה.")


def insight_maker(makers, total):
    name, v = makers.index[0], makers.iloc[0]
    if v / total < 0.05:
        return None
    top5 = makers.head(5).sum() / total
    return (f"היצרן הנפוץ ביותר הוא {name} ({pct(v / total * 100)}); חמשת היצרנים "
            f"הגדולים אחראים יחד ל-{pct(top5 * 100)} מהכלים.")


def compute(frames):
    df = _prepare(frames["equipment"])
    total = len(df)
    ref = df["reg"].max()
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = ref_year - 1 if partial else ref_year

    df["age"] = (ref_year - df["built"]).where(df["built"].between(1900, ref_year))
    types = df["type"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    makers = df["maker"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    per_year = df.dropna(subset=["reg"]).groupby(df["reg"].dt.year).size()
    per_year.index = per_year.index.astype(int)

    reg = df[df["reg"].dt.year >= TREND_FROM]
    by_drive = (reg.groupby([reg["reg"].dt.year, "drive_grp"]).size()
                   .unstack(fill_value=0).sort_index())
    drive_cols = [c for c in ["סולר", "חשמלי", "אחר / לא ידוע"] if c in by_drive.columns]
    years = [int(y) for y in by_drive.index]

    fl = reg[reg["type"].isin(["מלגזה מנוע חשמל", "מלגזה מנוע שריפה"])]
    fl_by = fl.groupby([fl["reg"].dt.year, "type"]).size().unstack(fill_value=0)
    elec_all = by_drive.get("חשמלי", pd.Series(0, index=by_drive.index)) / by_drive.sum(axis=1)

    def fl_share(y):
        if y not in fl_by.index or fl_by.loc[y].sum() == 0:
            return None
        return round(float(fl_by.loc[y].get("מלגזה מנוע חשמל", 0) / fl_by.loc[y].sum() * 100), 1)

    age_rows = []
    for lo, hi in AGE_BUCKETS:
        m = df["age"] >= lo
        if hi is not None:
            m &= df["age"] <= hi
        age_rows.append((bucket_label(lo, hi), int(m.sum())))

    heat_types = list(types.head(HEAT_TYPES).index)
    cells = []
    for yi, t in enumerate(heat_types):
        sub = df.loc[df["type"] == t, "age"]
        for xi, (lo, hi) in enumerate(AGE_BUCKETS):
            m = sub >= lo
            if hi is not None:
                m &= sub <= hi
            cells.append([xi, yi, int(m.sum())])

    t_names, t_vals = _top(types, TOP_N)
    m_names, m_vals = _top(makers, TOP_N)

    charts = {
        "registrations": {"x": [str(y) for y in years],
                          "series": [{"name": c, "data": [int(v) for v in by_drive[c]]}
                                     for c in drive_cols]},
        "electric": {"x": [str(y) for y in years],
                     "all": [round(float(v) * 100, 1) for v in elec_all],
                     "forklifts": [fl_share(y) for y in by_drive.index]},
        "types": {"names": t_names, "values": t_vals},
        "makers": {"names": m_names, "values": m_vals},
        "ages": {"names": [a for a, _ in age_rows], "values": [v for _, v in age_rows]},
        "heat": {"x": [bucket_label(lo, hi) for lo, hi in AGE_BUCKETS], "y": heat_types,
                 "cells": cells, "max": max([c[2] for c in cells] or [1])},
    }

    rules = [
        ("top_type", insight_top_type(types, total)),
        ("forklift_electric", insight_forklift_electric(df, last_full)),
        ("registrations", insight_registrations(per_year, last_full)),
        ("age", insight_age(df["age"])),
        ("maker", insight_maker(makers, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    electric_total = int(df["drive"].isin(ELECTRIC).sum())
    kpis = {
        "total": {"value": total, "display": n(total)},
        "types": {"value": int(types.size), "display": n(types.size)},
        "makers": {"value": int(makers.size), "display": n(makers.size)},
        "electric": {"value": electric_total, "display": pct(electric_total / total * 100)},
    }

    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    labels = {
        "lede": (f"מרשם כלי הצמ\"ה הפעילים של משרד התחבורה: {n(total)} כלים מ-{types.size} "
                 f"סוגים ו-{n(makers.size)} יצרני שלדה. הרישום האחרון במאגר: {d_he(ref)}."),
        "reg_note": (f"כלים פעילים לפי שנת הרישום בישראל, מ-{TREND_FROM}. כלים שהורדו מהכביש "
                     f"אינם במאגר, ולכן שנים מוקדמות מוצגות חסר.{partial_note}"),
        "reg_aria": f"גרף עמודות מוערמות: כלים פעילים לפי שנת רישום וסוג הנעה, {TREND_FROM} עד {ref_year}.",
        "electric_aria": "גרף קווים: שיעור הכלים החשמליים מבין הכלים שנרשמו בכל שנה, בכלל הכלים ובמלגזות.",
        "types_aria": f"תרשים עמודות: {TOP_N} סוגי הצמ\"ה הנפוצים, מספר כלים.",
        "makers_aria": f"תרשים עמודות: {TOP_N} יצרני השלדה הנפוצים, מספר כלים.",
        "ages_aria": "תרשים עמודות: כלים לפי גיל (לפי שנת ייצור).",
        "ages_caption": f"מספר כלים פעילים לפי קבוצת גיל, נכון ל-{ref_year}.",
        "heat_aria": f"מפת חום: מספר כלים לפי סוג ({HEAT_TYPES} הנפוצים) וקבוצת גיל.",
    }
    tables = {"ages": [{"bucket": a, "count": n(v)} for a, v in age_rows]}

    return {
        "agent_data": {
            "summary_he": (f"מרשם כלי הצמ\"ה (ציוד מכני הנדסי) הפעילים בישראל: {n(total)} כלים — "
                           f"סוג, יצרן, שנת ייצור, הנעה ומועד רישום."),
            "dataset_kind": "registry",
            "related_ids": ["273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                            "392abd0a-64f6-4c18-9d56-0111001411e6",
                            "0f16b39a-6016-408d-805d-31f40d5a0990",
                            "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4"],
            "suggested_tags": ["ציוד מכני הנדסי", "צמ\"ה", "משרד התחבורה", "מלגזות", "רישוי"],
            "temporal_coverage": f"{TREND_FROM}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
