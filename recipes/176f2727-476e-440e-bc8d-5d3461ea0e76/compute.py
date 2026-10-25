"""פנקס הסניגורים הציבוריים — appointments of public defenders, one row per
appointment (attorney name, appointment date, court file number, public-
defence file number, district). One CSV per district office, all with the
same shape except the date column, which the southern file names
"תאריך המינוי" and the others "תאריך מינוי"; the input matches every file
by the columns they share and compute() coalesces the two date names.

Privacy: attorneys are licensed professionals acting in a public role and
may be named and ranked. The court/defence file numbers point at specific
criminal cases (i.e. at defendants) — they are only aggregated (file-type
code from the court number; appointments per defence file), never shown.

"Now" is the latest appointment date that is actually populated (a day with
several rows), never the wall clock: a handful of typo dates lie decades in
the future or before the office existed and are excluded, disclosed.
"""
import pandas as pd

FIRST = "שם פרטי"
LAST = "שם משפחה"
DATE_COLS = ["תאריך מינוי", "תאריך המינוי"]
COURT = "מספר תיק בית המשפט שבו מונה"
PD_FILE = "מספר תיק הסנגוריה הציבורית"
DISTRICT = "מחוז"

FLOOR = pd.Timestamp("1996-01-01")       # the office began appointing in 1996
REF_MIN_ROWS = 5                          # a "real" day has at least this many rows
START_SHARE = 0.02                        # charts start at the first year ≥ 2% of the peak year
TOP_CODES = 10
MIX_CODES = 6
TOP_ATTORNEYS = 15
WINDOW_YEARS = 5
HEAT_YEARS = 15
LOAD_BUCKETS = [(1, 9), (10, 49), (50, 99), (100, 199), (200, 499), (500, None)]
DETENTION = ["מ״י", "מ״ת", "עמ״י", "עמ״ת"]
CODE_LABELS = {
    "ת״פ": "תיק פלילי",
    "מ״י": "מעצר ימים",
    "מ״ת": "מעצר עד תום ההליכים",
    "עמ״י": "ערר על מעצר ימים",
    "עמ״ת": "ערר על מעצר עד תום ההליכים",
    "ע״פ": "ערעור פלילי",
    "רע״פ": "רשות ערעור פלילי",
    "תפ״ח": "תיק פלילי חמור",
    "עת״א": "עתירת אסיר",
    "ב״ש": "בקשות שונות",
    "בש״פ": "בקשות שונות פליליות",
}
NO_NUMBER = "ללא מספר תיק"
NO_CODE = "מספר ללא קוד"
OTHER = "אחר"
WEEKDAYS = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]   # Sun..Sat
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def signed_pct(v):
    s = "+" if v > 0 else ("−" if v < 0 else "")
    return f"{s}{abs(v):.1f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def district_name(d):
    return d if d.startswith("ה") else f"מחוז {d}"


def in_district(d):
    return f"ב{d[1:]}" if d.startswith("ה") else f"במחוז {d}"


def code_name(c):
    lab = CODE_LABELS.get(c)
    return f"{c} — {lab}" if lab else c


def _sorted_counts(s):
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _same_day(ts, year):
    try:
        return ts.replace(year=year)
    except ValueError:            # 29 Feb → 28 Feb
        return ts.replace(year=year, day=28)


def _prepare(raw):
    cols = [c for c in DATE_COLS if c in raw.columns]
    if not cols:
        raise ValueError(f"no appointment-date column (expected one of {DATE_COLS})")
    date = raw[cols[0]]
    for c in cols[1:]:
        date = date.where(date.notna() & (date != ""), raw[c])
    date = date.fillna("")
    court = raw[COURT].fillna("").str.strip()
    code = court.str.extract(r"^(\S+)\s+\S")[0]
    code = code.str.replace("~", "״", regex=False).str.replace('"', "״", regex=False)
    code = code.where(code.notna(), NO_CODE).where(court != "", NO_NUMBER)
    name = (raw[FIRST].fillna("").str.strip() + " " + raw[LAST].fillna("").str.strip())
    name = name.str.replace(r"\s+", " ", regex=True).str.strip()
    df = pd.DataFrame({
        "d": pd.to_datetime(date.str.strip(), errors="coerce", format="%d/%m/%Y"),
        "district": raw[DISTRICT].fillna("").str.strip().replace("", "לא צוין"),
        "code": code,
        "name": name.replace("", "לא צוין"),
        "file": raw[PD_FILE].fillna("").str.strip(),
    })
    return df


def _reference_date(d):
    per_day = d.dropna().value_counts()
    real = per_day[per_day >= REF_MIN_ROWS]
    return (real.index.max() if len(real) else d.max())


# ── insight rules ────────────────────────────────────────────────────────

def insight_ytd(ytd_now, ytd_prev, ref_year, end):
    if ytd_prev < 1000:
        return None
    chg = ytd_now / ytd_prev - 1
    span = f"מתחילת {ref_year} ועד {d_he(end)}"
    if abs(chg) < 0.03:
        return (f"{span} נרשמו {n(ytd_now)} מינויים — בדומה לתקופה המקבילה ב-{ref_year - 1} "
                f"({n(ytd_prev)}).")
    word = "יותר" if chg > 0 else "פחות"
    return (f"{span} נרשמו {n(ytd_now)} מינויים — {pct(abs(chg) * 100)} {word} מאשר "
            f"בתקופה המקבילה ב-{ref_year - 1} ({n(ytd_prev)}).")


def insight_districts(cur, base, last_full, base_year):
    tot = cur.sum()
    if tot == 0:
        return None
    lead = cur.index[0]
    s = (f"ב-{last_full} המחוז עם מספר המינויים הגדול ביותר היה {district_name(lead)} "
         f"({n(cur.iloc[0])}, {pct(cur.iloc[0] / tot * 100)} מהמינויים).")
    ok = base[base >= 1000]
    if len(ok):
        chg = (cur.reindex(ok.index).fillna(0) / ok - 1).sort_index()
        chg = chg.sort_values(ascending=False, kind="stable")
        top = chg.index[0]
        if chg.iloc[0] >= 0.1:
            s += (f" הגידול החד ביותר מאז {base_year} נרשם {in_district(top)}: "
                  f"{pct(chg.iloc[0] * 100)} יותר מינויים.")
    return s


def insight_weekend(wk, y0, y1):
    sat = wk[wk["dow"] == 6]
    week = wk[wk["dow"] <= 4]
    if len(sat) < 500 or len(week) == 0:
        return None
    sat_codes = _sorted_counts(sat["code"].value_counts())
    c = sat_codes.index[0]
    if c in (NO_NUMBER, NO_CODE):
        return None
    s_sh = sat_codes.iloc[0] / len(sat)
    w_sh = (week["code"] == c).mean()
    if s_sh - w_sh < 0.1:
        return None
    lab = CODE_LABELS.get(c)
    what = f"{c} ({lab})" if lab else c
    return (f"בשבתות נרשמו {n(len(sat))} מינויים ב-{y0}–{y1}; "
            f"{pct(s_sh * 100)} מהם בתיקי {what}, לעומת {pct(w_sh * 100)} בימים ראשון–חמישי.")


def insight_concentration(loads, last_full):
    if len(loads) < 50:
        return None
    k = max(1, int(round(len(loads) * 0.1)))
    share = loads.iloc[:k].sum() / loads.sum()
    return (f"המינויים מרוכזים: ב-{last_full} עשירית הסניגורים העמוסים ביותר ({k} מתוך "
            f"{n(len(loads))}) קיבלו {pct(share * 100)} מהמינויים; החציון היה "
            f"{n(loads.median())} מינויים לסניגור.")


def insight_leader(top, last_full):
    if len(top) < 2:
        return None
    a, b = top[0], top[1]
    if a["count"] < 1.1 * b["count"]:
        return None
    return (f"הסניגור שקיבל את מספר המינויים הגבוה ביותר ב-{last_full} הוא {a['name']} "
            f"({n(a['count'])} מינויים, רובם {in_district(a['district'])}), ואחריו {b['name']} "
            f"({n(b['count'])}).")


def insight_attorneys(active, med, last_full, base_year):
    if last_full not in active.index or base_year not in active.index:
        return None
    a1, a0 = active[last_full], active[base_year]
    m1, m0 = med.get(last_full), med.get(base_year)
    if not a0 or m0 is None or m1 is None:
        return None
    chg = a1 / a0 - 1
    if abs(chg) < 0.05:
        head = f"מספר הסניגורים שקיבלו מינוי נותר יציב: {n(a0)} ב-{base_year} ו-{n(a1)} ב-{last_full}"
    else:
        word = "עלה" if chg > 0 else "ירד"
        head = f"מספר הסניגורים שקיבלו מינוי {word} מ-{n(a0)} ב-{base_year} ל-{n(a1)} ב-{last_full}"
    return f"{head}; החציון למינויים לסניגור בשנה עבר מ-{n(m0)} ל-{n(m1)}."


def insight_detention(by_year_code, totals, last_full, base_year):
    if last_full not in totals.index or base_year not in totals.index:
        return None
    if totals[last_full] < 1000 or totals[base_year] < 1000:
        return None

    def share(y):
        row = by_year_code.loc[y] if y in by_year_code.index else pd.Series(dtype=float)
        return sum(row.get(c, 0) for c in DETENTION) / totals[y]

    s1, s0 = share(last_full), share(base_year)
    if s0 < 0.2:
        return None
    codes = ", ".join(DETENTION)
    if abs(s1 - s0) < 0.02:
        tail = f"בדומה ל-{base_year} ({pct(s0 * 100)})"
    else:
        tail = f"לעומת {pct(s0 * 100)} ב-{base_year}"
    return (f"ב-{last_full} {pct(s1 * 100)} מהמינויים היו בהליכי מעצר ({codes}), {tail}.")


def insight_season(month_share, years):
    if len(years) < 5:
        return None
    avg = month_share.mean(axis=0)
    lo, hi = int(avg.idxmin()), int(avg.idxmax())
    if avg[lo] > 0.9 / 12:
        return None
    s = (f"החודש החלש ביותר הוא {MONTHS_HE[lo - 1]}: בממוצע {pct(avg[lo] * 100)} מהמינויים "
         f"השנתיים ב-{years[0]}–{years[-1]}, לעומת {pct(100 / 12)} בחודש ממוצע")
    if lo in (9, 10):
        s += " — החודש שבו חלים לרוב חגי תשרי"
    elif lo == 4:
        s += " — החודש שבו חל לרוב חג הפסח"
    return s + f"; החזק ביותר הוא {MONTHS_HE[hi - 1]} ({pct(avg[hi] * 100)})."


def insight_files(df):
    f = df[df["file"] != ""]
    g = f.groupby(["district", "file"]).size()
    if len(g) < 1000:
        return None
    multi = (g > 1).mean()
    return (f"{pct(multi * 100)} מתיקי הסניגוריה ({n(len(g))} תיקים עם מספר) כוללים יותר "
            f"ממינוי אחד — בממוצע {len(f) / len(g):.1f} מינויים לתיק.")


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["appointments"])
    total = len(df)
    ref = _reference_date(df["d"])
    valid = df["d"].notna() & (df["d"] >= FLOOR) & (df["d"] <= ref)
    excluded = int(total - valid.sum())
    df = df[valid].copy()
    df["y"] = df["d"].dt.year.astype(int)
    df["m"] = df["d"].dt.month.astype(int)
    df["dow"] = (df["d"].dt.dayofweek.astype(int) + 1) % 7      # Sun=0 .. Sat=6

    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = ref_year - 1 if partial else ref_year

    per_year = df.groupby("y").size().sort_index()
    start = int(per_year[per_year >= per_year.max() * START_SHARE].index.min())
    pre_start = int(per_year[per_year.index < start].sum())
    years = list(range(start, ref_year + 1))
    first_year = int(per_year.index.min())
    yr = df[df["y"] >= start]

    # 1. yearly by district (stacked)
    dist_order = list(_sorted_counts(df["district"].value_counts()).index)
    by_yd = yr.groupby(["y", "district"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    ch_yearly = {"x": [str(y) for y in years],
                 "series": [{"name": d, "data": [int(v) for v in by_yd.get(d, pd.Series(0, index=years))]}
                            for d in dist_order],
                 "partial": str(ref_year) if partial else None}

    # 2. month × year heatmap (the reference month is partial → omitted)
    by_ym = yr.groupby(["y", "m"]).size()
    cells = []
    heat_years = years[-HEAT_YEARS:]
    for yi, y in enumerate(heat_years):
        for m in range(1, 13):
            if partial and (y, m) >= (ref_year, ref.month):
                continue
            cells.append([m - 1, yi, int(by_ym.get((y, m), 0))])
    ch_heat = {"x": MONTHS_HE, "y": [str(y) for y in heat_years], "cells": cells,
               "max": max([c[2] for c in cells] or [1]),
               "min": min([c[2] for c in cells] or [0])}

    full_years = [y for y in range(max(start, last_full - 9), last_full + 1) if y in per_year.index]
    ms = (df[df["y"].isin(full_years)].groupby(["y", "m"]).size().unstack(fill_value=0)
          .reindex(columns=range(1, 13), fill_value=0))
    month_share = ms.div(ms.sum(axis=1), axis=0)

    # 3. districts: last full year vs WINDOW_YEARS earlier
    base_year = last_full - WINDOW_YEARS
    cur = _sorted_counts(df[df["y"] == last_full]["district"].value_counts())
    base = df[df["y"] == base_year]["district"].value_counts()
    d_names = list(cur.index) + sorted(d for d in base.index if d not in cur.index)
    ch_dist = {"names": d_names, "base_year": str(base_year), "cur_year": str(last_full),
               "base": [int(base.get(d, 0)) for d in d_names],
               "cur": [int(cur.get(d, 0)) for d in d_names]}

    # 4. file-type codes (all years)
    codes = _sorted_counts(df["code"].value_counts())
    real = codes[~codes.index.isin([NO_NUMBER, NO_CODE])]
    top_codes = list(real.head(TOP_CODES).index)
    rest = int(codes.sum() - real.head(TOP_CODES).sum() - codes.get(NO_NUMBER, 0))
    code_names = top_codes + [OTHER, NO_NUMBER]
    code_vals = [int(codes[c]) for c in top_codes] + [rest, int(codes.get(NO_NUMBER, 0))]
    ch_codes = {"names": code_names, "labels": [code_name(c) for c in top_codes] + [OTHER, NO_NUMBER],
                "values": code_vals}

    # 5. code mix over time (share %, top MIX_CODES by the last full year)
    lf = df[df["y"] == last_full]
    lf_codes = _sorted_counts(lf["code"].value_counts())
    mix = [c for c in lf_codes.index if c not in (NO_NUMBER, NO_CODE)][:MIX_CODES]
    by_yc = yr.groupby(["y", "code"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    ytot = by_yc.sum(axis=1).replace(0, 1)
    mix_series = []
    for c in mix:
        mix_series.append({"name": code_name(c),
                           "data": [round(float(v) * 100, 1) for v in by_yc.get(c, 0) / ytot]})
    other_share = 1 - sum(by_yc.get(c, 0) for c in mix) / ytot
    mix_series.append({"name": "אחר / ללא קוד", "data": [round(float(v) * 100, 1) for v in other_share]})
    ch_mix = {"x": [str(y) for y in years], "series": mix_series}

    # 6. code mix by district, last full year (100% bars)
    dm = lf.assign(c=lf["code"].where(lf["code"].isin(mix), OTHER))
    dct = dm.groupby(["district", "c"]).size().unstack(fill_value=0)
    dct = dct.reindex(index=list(cur.index), columns=mix + [OTHER], fill_value=0)
    dshare = dct.div(dct.sum(axis=1).replace(0, 1), axis=0)
    ch_dmix = {"names": list(dct.index),
               "series": [{"name": c, "label": (c if c == OTHER else code_name(c)),
                           "data": [round(float(v) * 100, 1) for v in dshare[c]]} for c in dct.columns]}

    # 7. weekday × code, last WINDOW_YEARS full years
    wk = df[(df["y"] > last_full - WINDOW_YEARS) & (df["y"] <= last_full)]
    wk_codes = mix[:4]
    wct = (wk.assign(c=wk["code"].where(wk["code"].isin(wk_codes), OTHER))
             .groupby(["dow", "c"]).size().unstack(fill_value=0)
             .reindex(index=range(7), columns=wk_codes + [OTHER], fill_value=0))
    ch_week = {"names": WEEKDAYS,
               "series": [{"name": c, "label": (c if c == OTHER else code_name(c)),
                           "data": [int(v) for v in wct[c]]} for c in wct.columns]}

    # 8. attorneys per year + median load
    att = yr.groupby(["y", "name"]).size()
    active = att.groupby(level=0).size().reindex(years, fill_value=0)
    med = att.groupby(level=0).median()
    ch_att = {"x": [str(y) for y in years],
              "active": [int(v) for v in active],
              "median": [(None if (partial and y == ref_year) or y not in med.index
                          else round(float(med[y]), 1)) for y in years]}

    # 9. top attorneys, last full year
    lf_att = _sorted_counts(lf.groupby("name").size())
    lf_att = lf_att[lf_att.index != "לא צוין"]
    dist_mode = (lf.groupby(["name", "district"]).size().reset_index(name="k")
                   .sort_values(["name", "k", "district"], ascending=[True, False, True])
                   .drop_duplicates("name").set_index("name")["district"])
    ndist = lf.groupby("name")["district"].nunique()
    top = [{"name": a, "count": int(v), "district": dist_mode[a], "ndist": int(ndist[a])}
           for a, v in lf_att.head(TOP_ATTORNEYS).items()]
    ch_top = {"names": [t["name"] for t in top], "values": [t["count"] for t in top]}

    # 10. workload distribution, last full year
    load_rows = []
    for lo, hi in LOAD_BUCKETS:
        m = lf_att >= lo
        if hi is not None:
            m &= lf_att <= hi
        load_rows.append({"bucket": f"{lo} ומעלה" if hi is None else f"{lo} עד {hi}",
                          "att": int(m.sum()), "appts": int(lf_att[m].sum())})
    ch_load = {"names": [r["bucket"] for r in load_rows], "att": [r["att"] for r in load_rows],
               "appts": [r["appts"] for r in load_rows]}

    # YTD vs same period a year earlier (through the day before the
    # reference date — the latest day of an export is usually incomplete).
    end = ref - pd.Timedelta(days=1)
    ytd_now = int(((df["d"] >= pd.Timestamp(ref_year, 1, 1)) & (df["d"] <= end)).sum()) \
        if end.year == ref_year else 0
    prev_end = _same_day(end, ref_year - 1)
    ytd_prev = int(((df["d"] >= pd.Timestamp(ref_year - 1, 1, 1)) & (df["d"] <= prev_end)).sum()) \
        if end.year == ref_year else 0

    rules = [
        ("ytd", insight_ytd(ytd_now, ytd_prev, ref_year, end) if partial and ytd_now else None),
        ("districts", insight_districts(cur, base, last_full, base_year)),
        ("detention", insight_detention(by_yc, per_year, last_full, last_full - 10)),
        ("weekend", insight_weekend(wk, last_full - WINDOW_YEARS + 1, last_full)),
        ("concentration", insight_concentration(lf_att, last_full)),
        ("leader", insight_leader(top, last_full)),
        ("attorneys", insight_attorneys(active, med, last_full, last_full - 10)),
        ("season", insight_season(month_share, full_years)),
        ("files", insight_files(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    names_total = int(df.loc[df["name"] != "לא צוין", "name"].nunique())
    lf_total = int(len(lf))
    if ytd_prev:
        ytd_chg = (ytd_now / ytd_prev - 1) * 100
        ytd_kpi = {"value": round(ytd_chg, 1), "display": signed_pct(ytd_chg), "tone": "info"}
    else:
        ytd_kpi = {"value": None, "display": "—", "tone": "brand"}
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "last_full": {"value": lf_total, "display": n(lf_total), "tone": "brand"},
        "ytd": ytd_kpi,
        "attorneys": {"value": int(len(lf_att)), "display": n(len(lf_att)), "tone": "brand"},
    }

    excl_note = ""
    if excluded:
        excl_note = (f" {n(excluded)} רשומות עם תאריך מינוי חסר, לפני {FLOOR.year} או אחרי "
                     f"{d_he(ref)} אינן נכללות בתרשימים.")
    pre_note = (f" {n(pre_start)} המינויים שלפני {start} אינם מוצגים בתרשימי השנים." if pre_start else "")
    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    k_top = max(1, int(round(len(lf_att) * 0.1)))

    labels = {
        "lede": (f"פנקס המינויים של הסניגוריה הציבורית: {n(total)} מינויים של {n(names_total)} "
                 f"סניגורים ב-{len(dist_order)} מחוזות, מ-{first_year} ועד {d_he(ref)}. כל רשומה היא "
                 f"מינוי של סניגור לתיק — שם הסניגור, מועד המינוי, מספר התיק בבית המשפט ומספר "
                 f"תיק הסניגוריה."),
        "ytd_kpi": (f"מינויים מתחילת {ref_year} לעומת התקופה המקבילה ב-{ref_year - 1}"
                    if ytd_prev else "שינוי מתחילת השנה"),
        "last_full_kpi": f"מינויים ב-{last_full}",
        "attorneys_kpi": f"סניגורים שקיבלו מינוי ב-{last_full}",
        "yearly_note": f"מספר המינויים בכל שנה, לפי מחוז הסניגוריה.{partial_note}{pre_note}{excl_note}",
        "yearly_aria": (f"גרף עמודות מוערמות: מינויים לפי שנה ומחוז, {start} עד {ref_year}; "
                        f"ב-{last_full} נרשמו {n(lf_total)} מינויים."),
        "heat_note": (f"מספר המינויים בכל חודש, {heat_years[0]}–{ref_year}. החודש האחרון ({MONTHS_HE[ref.month - 1]} {ref_year}) "
                      f"חלקי ואינו מוצג." if partial else f"מספר המינויים בכל חודש, {heat_years[0]}–{ref_year}."),
        "heat_aria": f"מפת חום: מינויים לפי חודש ושנה, {heat_years[0]} עד {ref_year}.",
        "dist_note": f"מינויים בכל מחוז ב-{last_full} לעומת {base_year}.",
        "dist_aria": f"תרשים עמודות: מינויים לפי מחוז, {base_year} מול {last_full}.",
        "dist_caption": f"מינויים לפי מחוז ב-{base_year} וב-{last_full}.",
        "codes_note": (f"סוג התיק לפי הקידומת של מספר התיק בבית המשפט, בכל שנות המאגר; "
                       f"{TOP_CODES} הקודים הנפוצים, השאר תחת ״אחר״. "
                       f"{pct(codes.get(NO_NUMBER, 0) / max(len(df), 1) * 100)} מהמינויים נרשמו ללא "
                       f"מספר תיק. קודים ללא פירוש מוצגים כפי שנרשמו; ציר המינויים באלפים."),
        "codes_aria": f"תרשים עמודות: מינויים לפי סוג תיק, {TOP_CODES} הקודים הנפוצים.",
        "codes_caption": "מינויים לפי סוג תיק בבית המשפט.",
        "mix_note": (f"שיעור כל סוג תיק מהמינויים בכל שנה — {len(mix)} הקודים הנפוצים ב-{last_full}. "
                     f"קודי התיקים במערכת בתי המשפט השתנו לאורך השנים, ולכן קודים ישנים נכללים ב״אחר״."),
        "mix_aria": f"גרף שטח מוערם: שיעור סוגי התיקים מהמינויים בכל שנה, {start} עד {ref_year}.",
        "dmix_note": f"התפלגות סוגי התיקים בכל מחוז ב-{last_full} (אחוז ממינויי המחוז).",
        "dmix_aria": f"תרשים עמודות מוערמות: התפלגות סוגי התיקים לפי מחוז ב-{last_full}.",
        "dmix_caption": f"שיעור סוגי התיקים (באחוזים) לפי מחוז ב-{last_full}.",
        "week_note": (f"מינויים לפי יום בשבוע ב-{last_full - WINDOW_YEARS + 1}–{last_full}, "
                      f"לפי סוג התיק."),
        "week_aria": f"תרשים עמודות מוערמות: מינויים לפי יום בשבוע וסוג תיק, {last_full - WINDOW_YEARS + 1}–{last_full}.",
        "week_caption": f"מינויים לפי יום בשבוע וסוג תיק, {last_full - WINDOW_YEARS + 1}–{last_full}.",
        "att_note": ("מספר הסניגורים שקיבלו לפחות מינוי אחד בכל שנה, והחציון של מספר המינויים "
                     "לסניגור. סניגורים מזוהים לפי שמם כפי שנרשם, כך ששני סניגורים בעלי שם זהה "
                     "נספרים כאחד." + (f" החציון אינו מוצג ל-{ref_year} החלקית." if partial else "")),
        "att_aria": f"גרף קווים: סניגורים פעילים וחציון מינויים לסניגור, {start} עד {ref_year}.",
        "top_note": (f"{TOP_ATTORNEYS} הסניגורים שקיבלו את מספר המינויים הגבוה ביותר ב-{last_full}, "
                     f"לפי שם, עם המחוז שבו קיבלו את רוב המינויים."),
        "top_aria": (f"תרשים עמודות: {TOP_ATTORNEYS} הסניגורים עם מספר המינויים הגבוה ביותר ב-{last_full}"
                     + (f"; בראש: {top[0]['name']}, {n(top[0]['count'])} מינויים." if top else ".")),
        "top_caption": f"הסניגורים עם מספר המינויים הגבוה ביותר ב-{last_full}.",
        "load_note": (f"כמה סניגורים קיבלו כמה מינויים ב-{last_full}, וכמה מינויים מכלל המינויים "
                      f"נפלו בכל קבוצה. עשירית הסניגורים העמוסים ביותר: {k_top} סניגורים."),
        "load_aria": f"תרשים עמודות: סניגורים ומינויים לפי מספר המינויים לסניגור ב-{last_full}.",
        "load_caption": f"התפלגות העומס — סניגורים ומינויים לפי מספר מינויים לסניגור ב-{last_full}.",
    }
    tables = {
        "dist": [{"name": d, "base": n(b), "cur": n(c)}
                 for d, b, c in zip(d_names, ch_dist["base"], ch_dist["cur"])],
        "codes": [{"name": l, "count": n(v)} for l, v in zip(ch_codes["labels"], code_vals)],
        "dmix_cols": [s["label"] for s in ch_dmix["series"]],
        "dmix": [{"name": d, "cells": [f"{s['data'][i]:.1f}%" for s in ch_dmix["series"]]}
                 for i, d in enumerate(ch_dmix["names"])],
        "week_cols": [s["label"] for s in ch_week["series"]],
        "week": [{"name": w, "cells": [n(s["data"][i]) for s in ch_week["series"]]}
                 for i, w in enumerate(WEEKDAYS)],
        "top": [{"name": t["name"], "count": n(t["count"]), "district": t["district"],
                 "ndist": n(t["ndist"])} for t in top],
        "load": [{"bucket": r["bucket"], "att": n(r["att"]), "appts": n(r["appts"])} for r in load_rows],
    }
    summary = (f"פנקס הסניגורים הציבוריים: {n(total)} מינויים של סניגורים לתיקים פליליים מאז "
               f"{first_year}, ב-{len(dist_order)} מחוזות הסניגוריה; ב-{last_full} נרשמו {n(lf_total)} "
               f"מינויים של {n(len(lf_att))} סניגורים.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["סניגוריה ציבורית", "משפט פלילי", "מינויי סניגורים", "בתי משפט",
                               "מעצרים", "משרד המשפטים"],
            "related_ids": ["13449cdd-9d02-44cf-b298-82f598369cd7",
                            "713440a1-9963-4548-a7d9-9d9c9da54f62",
                            "669b2652-f75b-4de3-8e6b-0dfa17accef5"],
            "temporal_coverage": f"{start}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"yearly": ch_yearly, "heat": ch_heat, "dist": ch_dist, "codes": ch_codes,
                   "mix": ch_mix, "dmix": ch_dmix, "week": ch_week, "att": ch_att,
                   "top": ch_top, "load": ch_load},
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
