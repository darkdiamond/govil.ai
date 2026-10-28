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
WEIGHT_BUCKETS = [(0, 1), (1, 3.5), (3.5, 10), (10, 30), (30, None)]      # tonnes
LIFT_BUCKETS = [(0, 1.5), (1.5, 2.5), (2.5, 3.5), (3.5, 5), (5, None)]   # tonnes
FORKLIFTS = ["מלגזה מנוע חשמל", "מלגזה מנוע שריפה"]
HP_TYPES = 10
TOP_MODELS = 12
RESTRICTION_COLS = ["hagbala_nm_1", "hagbala_nm_2", "hagbala_nm_3", "hagbala_nm_4"]
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
        "hp": pd.to_numeric(df["koah_sus"], errors="coerce"),
        "w": pd.to_numeric(df["mishkal_ton"], errors="coerce"),
        "lift": pd.to_numeric(df["kosher_harama_ton"], errors="coerce"),
        "model": df["degem_nm"].str.strip(),
    })
    # Restriction labels, multi-valued across 4 columns; unmapped codes
    # ("לא ידוע קוד X") are grouped and disclosed.
    r = pd.DataFrame({c: df[c].str.strip() for c in RESTRICTION_COLS})
    r = r.where(~r.apply(lambda col: col.str.startswith("לא ידוע")), "קוד הגבלה לא מזוהה")
    out["restr"] = r.apply(lambda row: sorted({v for v in row if v}), axis=1)
    out["type"] = out["type"].replace("", "לא ידוע")
    out["maker"] = out["maker"].replace("", "לא ידוע")
    out["drive_grp"] = out["drive"].map(
        lambda d: "חשמלי" if d in ELECTRIC else ("סולר" if d == "סולר" else "אחר / לא ידוע"))
    return out


def bucket_t(lo, hi):
    def f(x):
        return f"{x:g}"
    return f"{f(lo)}+ טון" if hi is None else f"{f(lo)}–{f(hi)} טון"


def _bucketize(series, buckets):
    rows = []
    for lo, hi in buckets:
        m = series >= lo
        if hi is not None:
            m &= series < hi
        rows.append((bucket_t(lo, hi), int(m.sum())))
    return rows


def insight_speed(restr_counts, total):
    slow = restr_counts.get("עד 30 קמש", 0)
    if total == 0 or slow / total < 0.5:
        return None
    fast = restr_counts.get("מעל 30 קמש", 0)
    return (f"{pct(slow / total * 100)} מהכלים רשומים בהגבלת מהירות של עד 30 קמ״ש, "
            f"ו-{pct(fast / total * 100)} מורשים לנסוע מעל 30 קמ״ש.")


def insight_lift(df):
    f = df[df["type"].isin(FORKLIFTS) & (df["lift"] > 0)]
    med = f.groupby("type")["lift"].median()
    if not set(FORKLIFTS) <= set(med.index) or f["type"].value_counts().min() < 100:
        return None
    e, c = med["מלגזה מנוע חשמל"], med["מלגזה מנוע שריפה"]
    if abs(e - c) < 0.2:
        return (f"כושר ההרמה החציוני של מלגזות חשמליות ושל מלגזות בעלות מנוע שריפה דומה "
                f"(כ-{e:.1f} טון).")
    word = "נמוך" if e < c else "גבוה"
    return (f"כושר ההרמה החציוני של מלגזה חשמלית ({e:.1f} טון) {word} מזה של מלגזה בעלת מנוע "
            f"שריפה ({c:.1f} טון) — החשמליות נפוצות יותר במשימות קלות.")


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

    restr_counts = pd.Series([v for lst in df["restr"] for v in lst]).value_counts()
    restr_counts = restr_counts.sort_index().sort_values(ascending=False, kind="stable")
    restr_rows = [(k, int(v)) for k, v in restr_counts.items()]

    weight_known = df["w"] > 0
    weight_rows = _bucketize(df.loc[weight_known, "w"], WEIGHT_BUCKETS)

    hp_types = [t for t in types.index if t != "לא ידוע"][:HP_TYPES]
    hp = df[df["type"].isin(hp_types) & (df["hp"] > 0)]
    hp_med = hp.groupby("type")["hp"].median()
    hp_n = hp.groupby("type").size()
    hp_list = [t for t in hp_types if t in hp_med.index]

    lift_rows = []
    for lo, hi in LIFT_BUCKETS:
        row = {"bucket": bucket_t(lo, hi)}
        for t in FORKLIFTS:
            sub = df.loc[(df["type"] == t) & (df["lift"] > 0), "lift"]
            m = sub >= lo
            if hi is not None:
                m &= sub < hi
            row[t] = int(m.sum())
        lift_rows.append(row)

    models = (df[df["model"] != ""].groupby(["model", "maker", "type"]).size()
                .reset_index(name="n")
                .sort_values(["n", "model", "maker", "type"], ascending=[False, True, True, True])
                .head(TOP_MODELS))

    charts["restrictions"] = {"names": [k for k, _ in restr_rows], "values": [v for _, v in restr_rows]}
    charts["weights"] = {"names": [k for k, _ in weight_rows], "values": [v for _, v in weight_rows]}
    charts["hp"] = {"names": hp_list, "values": [round(float(hp_med[t])) for t in hp_list]}
    charts["lift"] = {"names": [r["bucket"] for r in lift_rows],
                      "series": [{"name": t, "data": [r[t] for r in lift_rows]} for t in FORKLIFTS]}

    rules = [
        ("top_type", insight_top_type(types, total)),
        ("forklift_electric", insight_forklift_electric(df, last_full)),
        ("registrations", insight_registrations(per_year, last_full)),
        ("age", insight_age(df["age"])),
        ("maker", insight_maker(makers, total)),
        ("speed", insight_speed(restr_counts, total)),
        ("lift", insight_lift(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    electric_total = int(df["drive"].isin(ELECTRIC).sum())
    fleet_share = electric_total / total * 100
    new_reg = df[df["reg"].dt.year == last_full]
    new_share = (new_reg["drive"].isin(ELECTRIC).mean() * 100) if len(new_reg) else None
    # Direction of electrification: the last full year's registrations vs
    # the whole active fleet — green while new machines are more electric
    # than the fleet, amber if they are less, neutral info when similar.
    if new_share is None or abs(new_share - fleet_share) < 3:
        electric_tone = "info"
    else:
        electric_tone = "ok" if new_share > fleet_share else "warn"
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "types": {"value": int(types.size), "display": n(types.size), "tone": "brand"},
        "makers": {"value": int(makers.size), "display": n(makers.size), "tone": "brand"},
        "electric": {"value": electric_total, "display": f"{fleet_share:.1f}%",
                     "tone": electric_tone},
    }
    electric_kpi_label = (
        "מהכלים בהנעה חשמלית"
        + (f" ({new_share:.1f}% מהרישומים ב-{last_full})" if new_share is not None else "")
    )

    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    labels = {
        "electric_kpi": electric_kpi_label,
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
        "heat_caption": f"מספר כלים לפי סוג ({HEAT_TYPES} הנפוצים) וקבוצת גיל בשנים.",
        "types_caption": f"מספר כלים לפי סוג ({TOP_N} הנפוצים ואחר).",
        "makers_caption": f"מספר כלים לפי יצרן שלדה ({TOP_N} הנפוצים ואחר).",
        "restr_aria": "תרשים עמודות: מספר כלים לפי הגבלת רישוי (כלי יכול לשאת יותר מהגבלה אחת).",
        "restr_note": (f"הגבלות הרישום של כל כלי (עד ארבע לכלי). קודי הגבלה שאין להם תיאור במאגר "
                       f"מקובצים יחד. {pct((df['restr'].str.len() > 0).mean() * 100)} מהכלים "
                       f"רשומים עם הגבלה אחת לפחות."),
        "restr_caption": "מספר כלים לפי הגבלת רישוי.",
        "weights_aria": "תרשים עמודות: כלים לפי משקל עצמי, בטונות.",
        "weights_note": (f"משקל עצמי לפי רישום הכלי; {pct((~weight_known).mean() * 100)} מהכלים "
                         f"רשומים ללא משקל (0) ואינם נכללים."),
        "weights_caption": "מספר כלים לפי קבוצת משקל עצמי.",
        "hp_aria": f"תרשים עמודות: כוח סוס חציוני ב-{len(hp_list)} סוגי הכלים הנפוצים.",
        "hp_note": ("חציון כוח הסוס של כלים שיש להם ערך רשום; רשומות ללא ערך (0) — בעיקר כלים "
                    "חשמליים — אינן נכללות."),
        "hp_caption": "כוח סוס חציוני ומספר הכלים שנכללו, לפי סוג.",
        "lift_aria": "תרשים עמודות: מלגזות חשמליות ובעלות מנוע שריפה לפי כושר הרמה.",
        "lift_caption": "מספר מלגזות לפי כושר הרמה וסוג מנוע.",
        "models_caption": f"{TOP_MODELS} הדגמים הנפוצים במאגר, עם יצרן וסוג.",
    }
    tables = {
        "ages": [{"bucket": a, "count": n(v)} for a, v in age_rows],
        "types": [{"name": k, "count": n(v)} for k, v in zip(t_names, t_vals)],
        "makers": [{"name": k, "count": n(v)} for k, v in zip(m_names, m_vals)],
        "heat": [{"type": t, "cells": [n(c[2]) for c in cells if c[1] == yi]}
                 for yi, t in enumerate(heat_types)],
        "restrictions": [{"name": k, "count": n(v)} for k, v in restr_rows],
        "weights": [{"bucket": k, "count": n(v)} for k, v in weight_rows],
        "hp": [{"type": t, "hp": n(hp_med[t]), "count": n(hp_n[t])} for t in hp_list],
        "lift": [{"bucket": r["bucket"], "e": n(r[FORKLIFTS[0]]), "c": n(r[FORKLIFTS[1]])} for r in lift_rows],
        "models": [{"model": r["model"], "maker": r["maker"], "type": r["type"], "count": n(r["n"])}
                   for _, r in models.iterrows()],
        "heat_x": [bucket_label(lo, hi) for lo, hi in AGE_BUCKETS],
    }

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
