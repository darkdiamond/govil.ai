"""נתוני פשיעה (Israel Police): investigation files and offences by year,
quarter, police territory, locality and offence classification.

Inputs
- crimes: one yearly CSV per year (the publisher keeps the latest five years
  plus the current year's quarters), concatenated. One row = one offence in
  an investigation file; FictiveIDNumber identifies the file (a case can
  hold several offences, so files are counted as distinct ids).
- catalog: the offence dictionary (every offence name, its group/type and a
  sensitivity flag).

Every number on the page comes from here. Each insight rule returns a
sentence or None when its premise does not hold in the data.

Series break: the yearly files are not all comparable. At authoring time
(2026-10) the 2021 and 2022 datastore tables hold about half the rows of the
later years in every offence group: a stray quote in StatisticArea made
CKAN's import swallow ~190-220k rows per year into a few hundred oversized
StatisticArea values. The recipe does not fetch that column, so it cannot
see the cause; it detects the effect instead. A full year whose case count
jumps or falls by more than BREAK_RATIO against the previous full year
starts a new comparable segment; year-over-year comparisons only use years
inside the latest segment, and the page says so. If CKAN repairs the files
the break disappears and the comparisons extend back on their own.
"""
import re

import pandas as pd

NOTE_STRUCTURE_YEAR = 2023  # CKAN notes: the dataset's structure changed in 2023
BREAK_RATIO = 1.5          # year-over-year jump treated as a series break
STABLE_PCT = 2.0           # |change| below this reads as "stable"
MOVER_MIN = 500            # offences in both years for a type to be a mover
MOVER_PCT = 10.0           # |change| a mover needs to be named
TOP_TYPES = 15
TOP_STATIONS = 15
TOP_CITIES = 15
TOP_COUNCILS = 10
MIX_GROUPS = 7             # groups shown in mix charts, the rest -> "אחר"
DISTRICT_MIN_SHARE = 0.01  # districts below this share are not drawn
NO_DISTRICT = "ללא שיוך מחוזי"
NO_STATION = "ללא שיוך לתחנה"
NO_PLACE = "מקום לא צוין"
OTHER = "אחר"
COUNCIL_PREFIX = "מועצה אזורית"


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, digits=1):
    return f"{x:.{digits}f}%"


def _signed_pct(x, digits=1):
    s = f"{abs(x):.{digits}f}%"
    if round(x, digits) > 0:
        return "+" + s
    if round(x, digits) < 0:
        return "−" + s
    return s


def _chg(a, b):
    """Percent change from a to b, or None."""
    if not a:
        return None
    return (b - a) / a * 100.0


def _fix_parens(s):
    # A few names arrive with their parentheses flipped by an RTL export:
    # "(תקיפה (למעט עובדי ציבור" -> "תקיפה (למעט עובדי ציבור)".
    s = re.sub(r"\s+", " ", s.strip())
    if s.startswith("(") and not s.endswith(")"):
        s = s[1:].strip() + ")"
    return s


def _type_key(s):
    return re.sub(r"[\"'׳״\s()]+", "", s)


def _sorted_counts(series):
    """value_counts with a total order: count desc, then label asc."""
    vc = series.value_counts()
    df = pd.DataFrame({"k": vc.index.astype(str), "n": vc.to_numpy()})
    df = df.sort_values(["n", "k"], ascending=[False, True], kind="stable")
    return pd.Series(df["n"].to_numpy(), index=df["k"].to_numpy())


def _q_label(y, q):
    return f"ר{q} {y}"


def _q_label_long(y, q):
    return f"רבעון {q} {y}"


# ── preparation ─────────────────────────────────────────────────────────


def _prepare(raw):
    n_raw = len(raw)
    df = pd.DataFrame({
        "year": pd.to_numeric(raw["Year"].str.strip(), errors="coerce"),
        "q": pd.to_numeric(raw["Quarter"].str.strip().str.upper()
                           .str.extract(r"([1-4])", expand=False), errors="coerce"),
    })
    df["case"] = raw["FictiveIDNumber"].str.strip()
    ok = df["year"].notna() & df["q"].notna() & (df["case"] != "")
    df = df[ok].copy()
    df["year"] = df["year"].astype(int)
    df["q"] = df["q"].astype(int)
    for src, dst, empty in [
        ("PoliceDistrict", "district", NO_DISTRICT),
        ("PoliceMerhav", "merhav", NO_DISTRICT),
        ("PoliceStation", "station", NO_STATION),
    ]:
        v = raw.loc[ok, src].str.strip()
        df[dst] = v.where(v != "", empty)
    df["yeshuv"] = raw.loc[ok, "Yeshuv"].str.strip()
    df["muni"] = raw.loc[ok, "municipalName"].str.strip()
    df["group"] = raw.loc[ok, "StatisticGroup"].str.strip().map(_fix_parens)
    df["group"] = df["group"].where(df["group"] != "", "לא סווג")
    t = raw.loc[ok, "StatisticType"].str.strip().map(_fix_parens)
    df["type_raw"] = t.where(t != "", "לא סווג")
    # Merge spelling variants of one type (אמל"ח / אמלח): the display name is
    # the most frequent variant, ties broken alphabetically.
    df["tkey"] = df["type_raw"].map(_type_key)
    var = (df.groupby(["tkey", "type_raw"]).size().reset_index(name="n")
           .sort_values(["tkey", "n", "type_raw"], ascending=[True, False, True], kind="stable")
           .drop_duplicates("tkey"))
    df["type"] = df["tkey"].map(dict(zip(var["tkey"], var["type_raw"])))
    df = df.drop(columns=["type_raw"])
    return df, n_raw - int(ok.sum())


def _place(df):
    kind = pd.Series("", index=df.index, dtype=object)
    has_y = df["yeshuv"] != ""
    kind[has_y] = "ערים ויישובים עירוניים"
    council = (~has_y) & df["muni"].str.startswith(COUNCIL_PREFIX)
    kind[council] = "יישובים במועצות אזוריות"
    rest = (~has_y) & (~council)
    kind[rest] = df.loc[rest, "muni"].where(df.loc[rest, "muni"] != "", NO_PLACE)
    return kind


# ── insight rules ───────────────────────────────────────────────────────


def ins_trend(cases_y, L, P):
    if L is None or P is None:
        return None
    a, b = cases_y[P], cases_y[L]
    c = _chg(a, b)
    if c is None:
        return None
    if abs(c) < STABLE_PCT:
        return (f"מספר תיקי החקירה ב-{L} ({_int(b)}) כמעט זהה ל-{P} ({_int(a)}), "
                f"שינוי של {_signed_pct(c)} בלבד.")
    word = "עלייה" if c > 0 else "ירידה"
    return (f"ב-{L} נפתחו {_int(b)} תיקי חקירה פליליים, {word} של {abs(c):.1f}% "
            f"לעומת {P} ({_int(a)} תיקים).")


def ins_break(brk, group_ratio):
    if not brk:
        return None
    y0, y1, r = brk
    word = "זינק" if r > 1 else "צנח"
    pct = abs(r - 1) * 100
    s = f"בין {y0} ל-{y1} {word} מספר התיקים ב-{pct:.0f}%, שינוי חריג לסדרה שנתית. "
    if group_ratio:
        n_in, n_all, lo, hi = group_ratio
        s += (f"השינוי דומה ב-{n_in} מתוך {n_all} קבוצות העבירה הגדולות (פי {lo:.1f} עד פי {hi:.1f}). "
              "שינוי אחיד כזה מתאים יותר לשינוי באופן בניית הנתונים מאשר לשינוי בפשיעה")
        if y1 == NOTE_STRUCTURE_YEAR:
            s += f" (משטרת ישראל מציינת שמבנה המאגר השתנה ב-{NOTE_STRUCTURE_YEAR})"
        s += ". "
    s += f"לכן ההשוואות בין שנים בעמוד מתחילות ב-{y1}."
    return s


def ins_partial(partial):
    if not partial:
        return None
    y, qs, cur, prev, py = partial
    if len(qs) == 1:
        qtxt = f"רבעון {qs[0]}"
    elif qs == list(range(qs[0], qs[-1] + 1)):
        qtxt = f"רבעונים {qs[0]}-{qs[-1]}"
    else:
        qtxt = "רבעונים " + ", ".join(str(q) for q in qs[:-1]) + f" ו-{qs[-1]}"
    c = _chg(prev, cur)
    if c is None:
        return (f"נתוני {y} חלקיים ({qtxt}): {_int(cur)} תיקים עד כה.")
    if abs(c) < STABLE_PCT:
        tail = "כמעט ללא שינוי"
    else:
        tail = f"{'עלייה' if c > 0 else 'ירידה'} של {abs(c):.1f}%"
    return (f"נתוני {y} חלקיים ({qtxt}): {_int(cur)} תיקים, {tail} לעומת אותה תקופה "
            f"ב-{py} ({_int(prev)}).")


def ins_leader(groups_L, L):
    if groups_L.empty or groups_L.sum() == 0:
        return None
    tot = groups_L.sum()
    n1, v1 = groups_L.index[0], groups_L.iloc[0]
    s1 = v1 / tot * 100
    if len(groups_L) < 2:
        return f"כל העבירות ב-{L} סווגו כ{n1}."
    n2, v2 = groups_L.index[1], groups_L.iloc[1]
    s2 = v2 / tot * 100
    if s1 < 15:
        return None
    if s1 - s2 < 1.0:
        return (f"שתי קבוצות מובילות כמעט שוות ב-{L}: {n1} ({_pct(s1)} מהעבירות) "
                f"ו{n2} ({_pct(s2)}), ויחד הן {_pct(s1 + s2)} מכלל העבירות.")
    return (f"{n1} הן הקבוצה הגדולה ב-{L}, {_int(v1)} עבירות ({_pct(s1)}), "
            f"ואחריהן {n2} ({_pct(s2)}). יחד הן {_pct(s1 + s2)} מכלל העבירות.")


def ins_group_peak(grp_year, comp_years, L):
    """A sizeable group that is well below its peak inside the segment."""
    if L is None or len(comp_years) < 2:
        return None
    sub = grp_year.reindex(columns=comp_years, fill_value=0)
    tot_L = sub[L].sum()
    best = None
    for g in sorted(sub.index):
        row = sub.loc[g]
        if tot_L == 0 or row[L] / tot_L < 0.02:
            continue
        peak_y = max(comp_years, key=lambda y: (row[y], -y))
        if peak_y == L or row[peak_y] == 0:
            continue
        drop = (row[peak_y] - row[L]) / row[peak_y] * 100
        if drop >= 20 and (best is None or drop > best[3]):
            best = (g, peak_y, int(row[peak_y]), drop, int(row[L]))
    if not best:
        return None
    g, py, pv, drop, lv = best
    return (f"{g} הגיעו לשיא של {_int(pv)} עבירות ב-{py} וירדו ל-{_int(lv)} ב-{L}, "
            f"ירידה של {drop:.0f}% מהשיא.")


def ins_mover(movers, up, L, P):
    if movers is None or movers.empty:
        return None
    m = movers[movers["chg"] >= MOVER_PCT] if up else movers[movers["chg"] <= -MOVER_PCT]
    if m.empty:
        return None
    r = m.iloc[0] if up else m.iloc[-1]
    word = "העלייה" if up else "הירידה"
    return (f"{word} החדה ביותר בין סוגי העבירה עם {_int(MOVER_MIN)} עבירות לפחות: "
            f"{r['type']}, מ-{_int(r['prev'])} ב-{P} ל-{_int(r['cur'])} ב-{L} "
            f"({_signed_pct(r['chg'])}).")


def ins_district(dist_L, dist_P, L, P):
    if dist_L.empty:
        return None
    tot = dist_L.sum()
    n1, v1 = dist_L.index[0], dist_L.iloc[0]
    s = f"{n1} מוביל ב-{L} עם {_int(v1)} תיקים ({_pct(v1 / tot * 100)} מהתיקים)"
    if P is not None and not dist_P.empty:
        best = None
        for d in sorted(dist_L.index):
            if d == NO_DISTRICT or dist_L[d] / tot < 0.05:
                continue
            c = _chg(dist_P.get(d, 0), dist_L[d])
            if c is not None and (best is None or abs(c) > abs(best[1])):
                best = (d, c)
        if best and abs(best[1]) >= 3:
            word = "עלייה" if best[1] > 0 else "ירידה"
            s += f". השינוי החד ביותר לעומת {P}: {word} של {abs(best[1]):.1f}% ב{best[0]}"
    return s + "."


def ins_city(city_L, cases_L, L):
    if city_L.empty or cases_L == 0 or len(city_L) < 2:
        return None
    (n1, v1), (n2, v2) = list(city_L.items())[:2]
    top5 = city_L.iloc[:5].sum()
    return (f"{n1} ({_int(v1)} תיקים) ו{n2} ({_int(v2)}) הן הערים עם מספר התיקים הגבוה ב-{L}. "
            f"חמש הערים המובילות מרכזות {_pct(top5 / cases_L * 100)} מכלל התיקים.")


def ins_multi(multi_share, max_off, L):
    if multi_share is None or multi_share < 0.05:
        return None
    return (f"ב-{_pct(multi_share * 100)} מתיקי {L} נרשמו שתי עבירות או יותר, "
            f"והתיק העמוס ביותר כולל {_int(max_off)} עבירות. לכן מספר העבירות גבוה ממספר התיקים.")


def ins_catalog(cat):
    if not cat or cat["total"] == 0 or cat["sensitive"] == 0:
        return None
    g, gn, gt = cat["top_sensitive"]
    return (f"מילון העבירות מונה {_int(cat['total'])} עבירות, מהן {_int(cat['sensitive'])} "
            f"({_pct(cat['sensitive'] / cat['total'] * 100)}) מסומנות כרגישות, ומיקומן מוצג רק ברמת יישוב או מועצה אזורית. "
            f"הכי הרבה עבירות רגישות יש ב{g} ({_int(gn)} מתוך {_int(gt)}).")


# ── main ────────────────────────────────────────────────────────────────


def _catalog(raw):
    if raw is None or raw.empty:
        return None
    g = raw["StatisticCrimeGroupName"].str.strip().map(_fix_parens)
    g = g.where(g != "", "לא סווג")
    sens = raw["SensitivityFlag"].str.strip().isin(["1", "1.0", "true", "True", "כן"])
    name = raw["CrimeName"].str.strip()
    keep = name != ""
    df = pd.DataFrame({"g": g[keep], "s": sens[keep], "n": name[keep],
                       "t": raw.loc[keep, "StatisticCrimeTypeName"].str.strip()})
    agg = df.groupby("g").agg(total=("n", "size"), sens=("s", "sum")).reset_index()
    agg = agg.sort_values(["total", "g"], ascending=[False, True], kind="stable")
    by_sens = agg.sort_values(["sens", "g"], ascending=[False, True], kind="stable").iloc[0]
    return {
        "total": int(len(df)),
        "sensitive": int(df["s"].sum()),
        "types": int(df["t"].nunique()),
        "groups": int(len(agg)),
        "top_sensitive": (by_sens["g"], int(by_sens["sens"]), int(by_sens["total"])),
        "names": agg["g"].tolist(),
        "plain": [int(t - s) for t, s in zip(agg["total"], agg["sens"])],
        "sens": [int(s) for s in agg["sens"]],
    }


def compute(frames):
    df, dropped = _prepare(frames["crimes"])
    if df.empty:
        raise ValueError("no rows with year/quarter/case id")
    cat = _catalog(frames.get("catalog"))

    # cases: one row per (year, case) with its location fields
    cases = (df.sort_values(["year", "case", "q", "station", "yeshuv", "muni"], kind="stable")
             .drop_duplicates(["year", "case"]))
    cases = cases.assign(place=_place(cases))

    years = sorted(df["year"].unique().tolist())
    qcount = df.groupby("year")["q"].nunique()
    full_years = [y for y in years if qcount[y] == 4]
    cases_y = cases.groupby("year").size()
    off_y = df.groupby("year").size()

    # comparable segment (see module docstring)
    brk = None
    seg_start = full_years[0] if full_years else None
    for a, b in zip(full_years, full_years[1:]):
        r = cases_y[b] / cases_y[a] if cases_y[a] else 0
        if r > BREAK_RATIO or (r and r < 1 / BREAK_RATIO):
            brk = (a, b, r)
            seg_start = b
    comp_years = [y for y in full_years if seg_start is not None and y >= seg_start]
    L = comp_years[-1] if comp_years else (full_years[-1] if full_years else years[-1])
    P = comp_years[-2] if len(comp_years) >= 2 else None

    # partial latest year
    partial = None
    last = years[-1]
    if last not in full_years and last > L:
        qs = sorted(df.loc[df["year"] == last, "q"].unique().tolist())
        cur = int(cases_y[last])
        prev_cases = cases[(cases["year"] == L) & (cases["q"].isin(qs))]
        prev = int(len(prev_cases))
        partial = (last, qs, cur, prev, L)

    # ── quarterly timeline
    qser = cases.groupby(["year", "q"]).size()
    qoff = df.groupby(["year", "q"]).size()
    q_x, q_cases, q_off, q_pre, q_rows = [], [], [], [], []
    for (y, q) in sorted(qser.index.tolist()):
        q_x.append(_q_label(y, q))
        q_cases.append(int(qser[(y, q)]))
        q_off.append(int(qoff[(y, q)]))
        q_pre.append(bool(brk and y < seg_start))
        q_rows.append({"label": _q_label_long(y, q), "cases": _int(qser[(y, q)]),
                       "off": _int(qoff[(y, q)]),
                       "note": "לפני שבר בסדרה" if (brk and y < seg_start) else
                               ("שנה חלקית" if y not in full_years else "")})
    peak_i = max(range(len(q_cases)), key=lambda i: (q_cases[i] if not q_pre[i] else -1, -i))

    # ── groups
    grp_year = df.groupby(["group", "year"]).size().unstack(fill_value=0)
    groups_L = _sorted_counts(df.loc[df["year"] == L, "group"])
    groups_P = _sorted_counts(df.loc[df["year"] == P, "group"]) if P else pd.Series(dtype=int)
    mix_order = groups_L.index[:MIX_GROUPS].tolist()
    mix_years = full_years + ([last] if partial else [])
    mix_series = []
    for g in mix_order + [OTHER]:
        vals = []
        for y in mix_years:
            col = grp_year[y] if y in grp_year.columns else pd.Series(dtype=int)
            tot = col.sum()
            v = col.get(g, 0) if g != OTHER else col[~col.index.isin(mix_order)].sum()
            vals.append(round(v / tot * 100, 1) if tot else 0.0)
        mix_series.append({"name": g, "data": vals})
    mix_years_lbl = [str(y) if y in full_years else f"{y} (חלקית)" for y in mix_years]

    grp_names = groups_L.index.tolist()
    grp_rows = []
    for g in grp_names:
        c = _chg(groups_P.get(g, 0), groups_L[g]) if P else None
        grp_rows.append({"name": g, "cur": _int(groups_L[g]),
                         "prev": _int(groups_P.get(g, 0)) if P else "",
                         "chg": _signed_pct(c) if c is not None else ""})

    # ── types
    tL = df[df["year"] == L]
    types_L = _sorted_counts(tL["type"])
    types_P = _sorted_counts(df.loc[df["year"] == P, "type"]) if P else pd.Series(dtype=int)
    type_group = (tL.groupby(["type", "group"]).size().reset_index(name="n")
                  .sort_values(["type", "n", "group"], ascending=[True, False, True], kind="stable")
                  .drop_duplicates("type").set_index("type")["group"])
    top_types = types_L.index[:TOP_TYPES].tolist()
    type_rows = []
    for t in top_types:
        c = _chg(types_P.get(t, 0), types_L[t]) if P else None
        type_rows.append({"name": t, "group": type_group.get(t, ""), "cur": _int(types_L[t]),
                          "prev": _int(types_P.get(t, 0)) if P else "",
                          "chg": _signed_pct(c) if c is not None else ""})

    movers = None
    mover_rows = []
    mov_chart = {"names": [], "values": [], "cur": [], "prev": []}
    if P:
        m = pd.DataFrame({"cur": types_L, "prev": types_P}).fillna(0)
        m = m[(m["cur"] >= MOVER_MIN) & (m["prev"] >= MOVER_MIN)].copy()
        m["chg"] = (m["cur"] - m["prev"]) / m["prev"] * 100
        m["type"] = m.index.astype(str)
        m = m.sort_values(["chg", "type"], ascending=[False, True], kind="stable")
        movers = m
        sel = pd.concat([m[m["chg"] > 0].head(6), m[m["chg"] < 0].tail(6)])
        sel = sel[~sel.index.duplicated()]
        for _, r in sel.iterrows():
            mov_chart["names"].append(r["type"])
            mov_chart["values"].append(round(float(r["chg"]), 1))
            mov_chart["cur"].append(int(r["cur"]))
            mov_chart["prev"].append(int(r["prev"]))
            mover_rows.append({"name": r["type"], "prev": _int(r["prev"]), "cur": _int(r["cur"]),
                               "chg": _signed_pct(r["chg"])})

    # ── districts
    dist_all = _sorted_counts(cases.loc[cases["year"].isin(full_years), "district"])
    dist_tot = dist_all.sum()
    shown_d = [d for d in dist_all.index if d != NO_DISTRICT and dist_all[d] / dist_tot >= DISTRICT_MIN_SHARE]
    hidden_d = int(dist_tot - dist_all[shown_d].sum())
    dist_year = cases.groupby(["district", "year"]).size().unstack(fill_value=0)
    dist_L = _sorted_counts(cases.loc[cases["year"] == L, "district"])
    dist_P = _sorted_counts(cases.loc[cases["year"] == P, "district"]) if P else pd.Series(dtype=int)
    shown_d = sorted(shown_d, key=lambda d: (-int(dist_L.get(d, 0)), d))
    dist_series = [{"name": d, "data": [int(dist_year.loc[d].get(y, 0)) for y in full_years]}
                   for d in shown_d]
    dist_rows = [{"name": d, "vals": [_int(dist_year.loc[d].get(y, 0)) for y in full_years]}
                 for d in shown_d]

    # district × group heatmap (offences in L, share of the district's offences)
    hm_d = shown_d
    hm_g = mix_order + [OTHER]
    dg = tL.groupby(["district", "group"]).size()
    cells = []
    hm_max = 0.0
    for yi, d in enumerate(hm_d):
        row = dg[d] if d in dg.index.get_level_values(0) else pd.Series(dtype=int)
        tot = row.sum()
        for xi, g in enumerate(hm_g):
            v = row.get(g, 0) if g != OTHER else row[~row.index.isin(mix_order)].sum()
            s = round(v / tot * 100, 1) if tot else 0.0
            hm_max = max(hm_max, s)
            cells.append([xi, yi, s, int(v)])

    # ── stations
    cL = cases[cases["year"] == L]
    cP = cases[cases["year"] == P] if P else cases.iloc[0:0]
    st_L = _sorted_counts(cL["station"])
    st_P = _sorted_counts(cP["station"]) if P else pd.Series(dtype=int)
    top_st = [s for s in st_L.index if s != NO_STATION][:TOP_STATIONS]
    st_dist = (cL.groupby(["station", "district"]).size().reset_index(name="n")
               .sort_values(["station", "n", "district"], ascending=[True, False, True], kind="stable")
               .drop_duplicates("station").set_index("station")["district"])
    st_rows = []
    for s in top_st:
        c = _chg(st_P.get(s, 0), st_L[s]) if P else None
        st_rows.append({"name": s, "district": st_dist.get(s, ""), "cur": _int(st_L[s]),
                        "prev": _int(st_P.get(s, 0)) if P else "",
                        "chg": _signed_pct(c) if c is not None else ""})

    # treemap district > merhav > station
    tm = cL.groupby(["district", "merhav", "station"]).size().reset_index(name="n")
    tree = []
    for d in sorted(tm["district"].unique(), key=lambda d: (-int(tm.loc[tm["district"] == d, "n"].sum()), d)):
        sd = tm[tm["district"] == d]
        kids = []
        for mh in sorted(sd["merhav"].unique(), key=lambda m: (-int(sd.loc[sd["merhav"] == m, "n"].sum()), m)):
            sm = sd[sd["merhav"] == mh].sort_values(["n", "station"], ascending=[False, True], kind="stable")
            kids.append({"name": mh, "value": int(sm["n"].sum()),
                         "children": [{"name": r.station, "value": int(r.n)} for r in sm.itertuples()]})
        tree.append({"name": d, "value": int(sd["n"].sum()), "children": kids})

    # ── localities
    city_L = _sorted_counts(cL.loc[cL["yeshuv"] != "", "yeshuv"])
    city_P = _sorted_counts(cP.loc[cP["yeshuv"] != "", "yeshuv"]) if P else pd.Series(dtype=int)
    top_city = city_L.index[:TOP_CITIES].tolist()
    city_rows = []
    for cty in top_city:
        c = _chg(city_P.get(cty, 0), city_L[cty]) if P else None
        city_rows.append({"name": cty, "cur": _int(city_L[cty]),
                          "prev": _int(city_P.get(cty, 0)) if P else "",
                          "chg": _signed_pct(c) if c is not None else ""})

    place_L = _sorted_counts(cL["place"])
    place_rows = [{"name": k, "n": _int(v), "share": _pct(v / len(cL) * 100)} for k, v in place_L.items()]
    councils = _sorted_counts(cL.loc[cL["muni"].str.startswith(COUNCIL_PREFIX), "muni"])
    top_councils = councils.index[:TOP_COUNCILS].tolist()
    council_rows = [{"name": k, "n": _int(councils[k])} for k in top_councils]

    # ── offences per case
    per_case = tL.groupby("case").size()
    bins = ["1", "2", "3", "4", "5 ומעלה"]
    bc = [int((per_case == 1).sum()), int((per_case == 2).sum()), int((per_case == 3).sum()),
          int((per_case == 4).sum()), int((per_case >= 5).sum())]
    n_cases_L = int(len(per_case))
    multi_share = (n_cases_L - bc[0]) / n_cases_L if n_cases_L else None
    max_off = int(per_case.max()) if n_cases_L else 0
    multi_rows = [{"name": b, "n": _int(v), "share": _pct(v / n_cases_L * 100 if n_cases_L else 0)}
                  for b, v in zip(bins, bc)]

    # ── seasonality: quarter share of each comparable full year
    season_years = comp_years if len(comp_years) >= 2 else full_years
    season_series = []
    season_rows = []
    for y in season_years:
        vals = [round(int(qser.get((y, q), 0)) / int(cases_y[y]) * 100, 1) for q in (1, 2, 3, 4)]
        season_series.append({"name": str(y), "data": vals})
    for qi, q in enumerate((1, 2, 3, 4)):
        season_rows.append({"name": f"רבעון {q}", "vals": [_pct(s["data"][qi]) for s in season_series]})
    top_q = None
    if len(season_series) >= 2:
        tops = {max(range(4), key=lambda i: (s["data"][i], -i)) for s in season_series}
        if len(tops) == 1:
            top_q = tops.pop() + 1

    # ── group ratio across the break
    group_ratio = None
    if brk:
        a, b, r = brk
        big = [g for g in grp_year.index if grp_year.loc[g, b] / grp_year[b].sum() >= 0.01
               and grp_year.loc[g, a] > 0]
        rs = sorted(grp_year.loc[g, b] / grp_year.loc[g, a] for g in big)
        close = [x for x in rs if 0.8 * r <= x <= 1.2 * r]
        if big and len(close) / len(big) >= 0.5:
            group_ratio = (len(close), len(big), min(close), max(close))

    # ── KPIs
    cases_L = int(cases_y[L])
    off_L = int(off_y[L])
    change = _chg(cases_y[P], cases_y[L]) if P else None
    ch_display, ch_tone = "", "brand"
    if change is not None:
        ch_display = _signed_pct(change)
        ch_tone = ("danger" if change >= 5 else "warn" if change >= STABLE_PCT
                   else "ok" if change <= -STABLE_PCT else "brand")
    top_share = groups_L.iloc[0] / groups_L.sum() * 100 if len(groups_L) else 0
    span = f"{years[0]}–{years[-1]}" if years[0] != years[-1] else str(years[0])
    kpis = {}
    if change is not None:
        kpis["change"] = {"value": round(change, 1), "display": ch_display, "tone": ch_tone}
    kpis.update({
        "cases": {"value": cases_L, "display": _int(cases_L), "tone": "brand"},
        "offences": {"value": off_L, "display": _int(off_L), "tone": "brand"},
        "ratio": {"value": round(off_L / cases_L, 2) if cases_L else 0,
                  "display": f"{off_L / cases_L:.2f}" if cases_L else "0", "tone": "brand"},
        "top_group": {"value": round(top_share, 1), "display": _pct(top_share), "tone": "info"},
        "multi": {"value": round((multi_share or 0) * 100, 1),
                  "display": _pct((multi_share or 0) * 100), "tone": "info"},
        "span": {"value": len(years), "display": span, "tone": "brand"},
    })
    kpi_order = (["cases", "offences", "change", "top_group", "multi", "span"] if "change" in kpis
                 else ["cases", "offences", "ratio", "top_group", "multi", "span"])

    # ── insights
    rules = [
        ("trend", ins_trend(cases_y, L, P)),
        ("partial", ins_partial(partial)),
        ("break", ins_break(brk, group_ratio)),
        ("leader_group", ins_leader(groups_L, L)),
        ("mover_up", ins_mover(movers, True, L, P)),
        ("mover_down", ins_mover(movers, False, L, P)),
        ("group_peak", ins_group_peak(grp_year, comp_years, L)),
        ("district", ins_district(dist_L, dist_P, L, P)),
        ("city", ins_city(city_L, cases_L, L)),
        ("multi", ins_multi(multi_share, max_off, L)),
        ("catalog", ins_catalog(cat)),
    ]
    if top_q:
        rules.append(("season", f"רבעון {top_q} היה הרבעון העמוס בכל אחת מהשנים "
                                f"{season_years[0]} עד {season_years[-1]}."))
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── labels / ledes
    top_g = groups_L.index[0] if len(groups_L) else ""
    pk = peak_i
    lab = {}
    lab["kpi_cases"] = f"תיקי חקירה פליליים ב-{L}"
    lab["kpi_offences"] = f"עבירות בתיקים ב-{L}"
    lab["kpi_change"] = (f"שינוי במספר התיקים, {L} לעומת {P}" if P
                         else "שינוי שנתי (אין שנה קודמת להשוואה)")
    lab["kpi_top_group"] = f"נתח {top_g} מהעבירות ב-{L}"
    lab["kpi_multi"] = f"תיקים עם יותר מעבירה אחת ב-{L}"
    lab["kpi_ratio"] = f"עבירות בממוצע לתיק ב-{L}"
    lab["kpi_span"] = "טווח השנים במאגר"
    lab["lede"] = (
        f"סטטיסטיקת הפשיעה של משטרת ישראל: כל עבירה בתיק חקירה פלילי, לפי שנה ורבעון, מחוז, מרחב ותחנה, "
        f"יישוב או מועצה אזורית, וקבוצת וסוג העבירה. ב-{L} נפתחו {_int(cases_L)} תיקים "
        f"שכללו {_int(off_L)} עבירות. המאגר מכסה את השנים {years[0]} עד {years[-1]}."
    )
    pre_txt = (f" העמודות הבהירות ({brk[0]} ומטה) שייכות לקבצים שאינם ברי השוואה לשנים שאחריהם."
               if brk else "")
    lab["quarterly_lede"] = (
        f"מספר התיקים בכל רבעון, והקו מראה את מספר העבירות בהם. הרבעון העמוס ביותר "
        f"{'מאז ' + str(seg_start) + ' ' if brk else ''}היה {q_rows[pk]['label']} עם {q_rows[pk]['cases']} תיקים.{pre_txt}"
    )
    lab["quarterly_aria"] = (f"גרף עמודות: תיקי חקירה פליליים בכל רבעון, {q_rows[0]['label']} עד "
                             f"{q_rows[-1]['label']}. שיא ב{q_rows[pk]['label']} עם {q_rows[pk]['cases']} תיקים.")
    mix_note = ""
    if brk:
        mix_note = " שיעורים פחות רגישים לשינוי בהיקף הקבצים מאשר מספרים מוחלטים"
        if group_ratio:
            n_in, n_all, lo, hi = group_ratio
            mix_note += (f": בין {brk[0]} ל-{brk[1]} השתנו {n_in} מתוך {n_all} הקבוצות הגדולות "
                         f"בקצב דומה (פי {lo:.1f} עד פי {hi:.1f}){', אבל לא כולן' if n_in < n_all else ''}, ולכן השוואה לשנים "
                         f"שלפני {brk[1]} עדיין דורשת זהירות.")
        else:
            mix_note += (f", אך השינוי בין {brk[0]} ל-{brk[1]} לא היה אחיד בין הקבוצות, ולכן השוואה "
                         f"לשנים שלפני {brk[1]} דורשת זהירות.")
    lab["mix_lede"] = (f"חלקה של כל קבוצת עבירות מכלל העבירות בכל שנה.{mix_note} "
                       f"ב-{L} {top_g} היו {_pct(top_share)} מהעבירות.")
    lab["mix_aria"] = f"גרף עמודות מוערמות: התפלגות העבירות לפי קבוצה בכל שנה. {top_g} מובילות עם {_pct(top_share)} ב-{L}."
    lab["groups_lede"] = (f"מספר העבירות בכל קבוצה ב-{L}" + (f" לעומת {P}." if P else "."))
    lab["groups_aria"] = f"גרף עמודות אופקי: עבירות לפי קבוצת עבירה ב-{L}. {top_g} מובילות עם {_int(groups_L.iloc[0]) if len(groups_L) else 0}."
    t1 = top_types[0] if top_types else ""
    lab["types_lede"] = (f"{len(top_types)} סוגי העבירה הנפוצים ב-{L}, מתוך {_int(types_L.size)} סוגים. "
                         f"בראש: {t1} עם {_int(types_L.iloc[0]) if len(types_L) else 0} עבירות.")
    lab["types_aria"] = f"גרף עמודות אופקי: סוגי העבירה הנפוצים ב-{L}. בראש {t1}."
    if mov_chart["names"]:
        lab["movers_lede"] = (f"השינוי באחוזים בין {P} ל-{L} בסוגי העבירה שנרשמו בהם {_int(MOVER_MIN)} עבירות "
                              f"לפחות בכל אחת משתי השנים ({_int(len(movers))} סוגים). מוצגים העולים והיורדים ביותר.")
        lab["movers_aria"] = (f"גרף עמודות דו-כיווני: סוגי העבירה שהשתנו הכי הרבה בין {P} ל-{L}. "
                              f"העלייה הגדולה ב{mov_chart['names'][0]} ({_signed_pct(mov_chart['values'][0])}).")
    d1 = dist_L.index[0] if len(dist_L) else ""
    lab["districts_lede"] = (
        f"תיקי חקירה בכל מחוז משטרתי לפי שנה{f' (שנת {last} החלקית אינה מוצגת)' if partial else ''}. ב-{L} {d1} מוביל עם {_int(dist_L.iloc[0]) if len(dist_L) else 0} תיקים."
        + (f" לא מוצגים {_int(hidden_d)} תיקים ללא שיוך מחוזי או במחוזות קטנים מ-{DISTRICT_MIN_SHARE * 100:.0f}% מהתיקים."
           if hidden_d else "")
        + (f" את הקפיצה בין {brk[0]} ל-{brk[1]} יש לקרוא בזהירות, ראו בתובנות." if brk else "")
    )
    lab["districts_aria"] = f"גרף קווים: תיקי חקירה לפי מחוז ושנה. {d1} מוביל ב-{L}."
    lab["heat_lede"] = (f"איזה חלק מהעבירות בכל מחוז שייך לכל קבוצת עבירות ({L}). "
                        "התא הכהה מראה את הקבוצה הדומיננטית, והשוואה לאורך העמודה מגלה מחוזות חריגים.")
    lab["heat_aria"] = f"מפת חום: שיעור כל קבוצת עבירות מתוך העבירות בכל מחוז ב-{L}."
    s1 = top_st[0] if top_st else ""
    lab["stations_lede"] = (f"{len(top_st)} התחנות עם מספר תיקי החקירה הגבוה ב-{L}. "
                            f"בראש {s1} עם {_int(st_L[s1]) if s1 else 0} תיקים.")
    lab["stations_aria"] = f"גרף עמודות אופקי: התחנות המובילות במספר התיקים ב-{L}. בראש {s1}."
    lab["tree_lede"] = (f"כל {_int(st_L.size)} התחנות והמרחבים ב-{L}, מקובצים לפי מחוז. גודל המלבן הוא מספר התיקים. "
                        "לחיצה על מחוז מתמקדת בו, ולחיצה על \"כל המחוזות\" בשורת הניווט שמתחת לגרף מחזירה לתצוגה המלאה.")
    lab["tree_aria"] = f"מפת עץ: תיקי חקירה לפי מחוז, מרחב ותחנה ב-{L}."
    c1 = top_city[0] if top_city else ""
    lab["cities_lede"] = (f"{len(top_city)} היישובים עם מספר התיקים הגבוה ב-{L}. "
                          f"בראש {c1} עם {_int(city_L[c1]) if c1 else 0} תיקים. מספר מוחלט, לא מנורמל לגודל האוכלוסייה.")
    lab["cities_aria"] = f"גרף עמודות אופקי: היישובים המובילים במספר התיקים ב-{L}. בראש {c1}."
    p1 = place_L.index[0] if len(place_L) else ""
    lab["place_lede"] = (f"היכן התרחשו העבירות ב-{L}: {p1} מרכזים {_pct(place_L.iloc[0] / len(cL) * 100) if len(cL) else '0%'} מהתיקים. "
                         "ביישובים כפריים המיקום מוצג רק ברמת המועצה האזורית.")
    lab["place_aria"] = f"גרף טבעת: תיקי חקירה לפי סוג המקום ב-{L}. בראש: {p1}."
    k1 = top_councils[0] if top_councils else ""
    lab["councils_lede"] = (f"המועצות האזוריות עם מספר התיקים הגבוה ב-{L}. בראש {k1}"
                            + (f" עם {_int(councils[k1])} תיקים." if k1 else "."))
    lab["councils_aria"] = f"גרף עמודות אופקי: המועצות האזוריות המובילות במספר התיקים ב-{L}."
    lab["multi_lede"] = (f"כמה עבירות נרשמו בכל תיק ב-{L}. {_pct(bc[0] / n_cases_L * 100 if n_cases_L else 0)} מהתיקים "
                         f"כוללים עבירה אחת בלבד, והתיק העמוס ביותר כולל {_int(max_off)}.")
    lab["multi_aria"] = f"גרף עמודות: התפלגות מספר העבירות בתיק ב-{L}."
    lab["season_lede"] = (f"חלקו של כל רבעון מהתיקים השנתיים, בשנים {season_years[0]} עד {season_years[-1]}. "
                          + (f"רבעון {top_q} היה העמוס בכל השנים." if top_q else "אין רבעון שעמוס באופן עקבי בכל השנים."))
    lab["season_aria"] = f"גרף קווים: חלק כל רבעון מהתיקים השנתיים, {season_years[0]} עד {season_years[-1]}."
    if cat:
        lab["catalog_lede"] = (f"מילון העבירות מונה {_int(cat['total'])} עבירות ב-{_int(cat['groups'])} קבוצות "
                               f"ו-{_int(cat['types'])} סוגים. {_int(cat['sensitive'])} מהן מסומנות כרגישות: "
                               "מיקומן מוצג רק ברמת יישוב או מועצה אזורית, ולא ברמת אזור סטטיסטי.")
        lab["catalog_aria"] = f"גרף עמודות מוערמות: מספר העבירות במילון בכל קבוצה, רגישות ושאינן רגישות."
    lab["dropped"] = (f"{_int(dropped)} רשומות ללא שנה, רבעון או מזהה תיק אינן נספרות." if dropped else "")

    temporal = f"{years[0]}/{years[-1]}" if years[0] != years[-1] else str(years[0])
    summary = (f"סטטיסטיקת פשיעה של משטרת ישראל לפי יישוב, תחנה וסוג עבירה: "
               f"{_int(cases_L)} תיקי חקירה ו-{_int(off_L)} עבירות ב-{L}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": temporal,
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "insights": insights,
        "labels": lab,
        "flags": {
            "movers": bool(mov_chart["names"]),
            "has_prev": P is not None,
            "catalog": cat is not None,
            "councils": bool(top_councils),
            "break": brk is not None,
        },
        "meta": {"L": L, "P": P if P else "", "full_years": full_years},
        "charts": {
            "quarterly": {"x": q_x, "cases": q_cases, "off": q_off, "pre": q_pre},
            "mix": {"years": mix_years_lbl, "series": mix_series},
            "groups": {"names": grp_names, "cur": [int(groups_L[g]) for g in grp_names],
                       "prev": [int(groups_P.get(g, 0)) for g in grp_names] if P else []},
            "types": {"names": top_types, "cur": [int(types_L[t]) for t in top_types],
                      "prev": [int(types_P.get(t, 0)) for t in top_types] if P else []},
            "movers": mov_chart,
            "districts": {"years": [str(y) for y in full_years], "series": dist_series},
            "heat": {"x": hm_g, "y": hm_d, "cells": cells, "max": hm_max},
            "stations": {"names": top_st, "cur": [int(st_L[s]) for s in top_st],
                         "prev": [int(st_P.get(s, 0)) for s in top_st] if P else []},
            "tree": tree,
            "cities": {"names": top_city, "cur": [int(city_L[c]) for c in top_city],
                       "prev": [int(city_P.get(c, 0)) for c in top_city] if P else []},
            "place": {"names": place_L.index.tolist(), "values": [int(v) for v in place_L]},
            "councils": {"names": top_councils, "values": [int(councils[k]) for k in top_councils]},
            "multi": {"bins": bins, "values": bc},
            "season": {"q": [f"רבעון {q}" for q in (1, 2, 3, 4)], "series": season_series},
            "catalog": ({"names": cat["names"], "plain": cat["plain"], "sens": cat["sens"]}
                        if cat else {"names": [], "plain": [], "sens": []}),
        },
        "tables": {
            "quarterly": q_rows,
            "groups": grp_rows,
            "types": type_rows,
            "movers": mover_rows,
            "districts": dist_rows,
            "stations": st_rows,
            "cities": city_rows,
            "place": place_rows,
            "councils": council_rows,
            "multi": multi_rows,
            "season": season_rows,
            "mix": [{"name": s["name"], "vals": [_pct(v) for v in s["data"]]} for s in mix_series],
            "catalog": ([{"name": n, "total": _int(p + s), "sens": _int(s)}
                         for n, p, s in zip(cat["names"], cat["plain"], cat["sens"])] if cat else []),
        },
    }
