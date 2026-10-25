"""אזורי עדיפות לאומית ואזורי פיתוח — Ministry of Economy.

Three CKAN files, two of which carry information:
  * dev — every development-area classification ever decreed (דרגה א / ב /
    מרכז הארץ), one row per locality × program type (הקמה / הרחבה / both) ×
    validity period; is_history marks rows no longer in force.
  * nap — the national-priority map (עדיפות לאומית), one row per locality.
  * the third file ("אזורי פיתוח א") is exactly the current class-A slice of
    dev, so it is not read.

A locality can hold two current dev rows — e.g. class א for expanding a plant
but "מרכז הארץ" for establishing a new one — so the page reasons both in rows
("classifications") and in localities, where a locality's "best" class is the
most favourable one it holds (א > ב > מרכז הארץ). Snapshots of the map in past
years are rebuilt from the validity intervals. "Now" is the data: the rows
flagged current, never the wall clock.
"""
import pandas as pd

LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
DATE_FMT = "%d/%m/%Y"

# Known class codes, in order of benefit; unknown codes flow through after them.
CLASS_ORDER = ["א", "ב", "מרכז הארץ"]
CLASS_LABEL = {"א": "דרגה א", "ב": "דרגה ב", "מרכז הארץ": "מרכז הארץ"}
STATUS_ORDER = ["הקמה/הרחבה", "הרחבה", "הקמה"]
STATUS_LABEL = {"הקמה/הרחבה": "הקמה והרחבה", "הרחבה": "הרחבה בלבד", "הקמה": "הקמה בלבד",
                "": "לא צוין"}
NOT_LISTED = "לא במפה"
NO_SUB = "לא צוינה נפה"
OTHER_SUB = "נפות אחרות"
TOP_SUB = 16           # dev subdistricts shown separately
TOP_NAP_SUB = 12
TOP_PROFILES = 6
WAVE_MIN = 50          # a start date carrying ≥ this many rows is a "decree wave"
SNAP_MONTH, SNAP_DAY = 7, 1


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def cls_label(c):
    return CLASS_LABEL.get(c, c or "לא צוין")


def _rank_map(values):
    known = {c: i for i, c in enumerate(CLASS_ORDER)}
    extra = sorted(v for v in set(values) if v not in known)
    for i, v in enumerate(extra):
        known[v] = len(CLASS_ORDER) + i
    return known


def _prep(df):
    out = pd.DataFrame({
        "name": df["datasource_city_name"].str.strip(),
        "cls": df["priority_class"].str.strip(),
        "status": df["program_status"].str.strip(),
        "sub": df["SubDistrict"].str.strip(),
        "hist": df["is_history"].str.strip() == "כן",
        "gaza": df["is_surrounding_Gaza"].str.strip() == "כן",
        "ind": df["is_industrial_area"].str.strip() == "כן",
        "fd": pd.to_datetime(df["from_date"].str.strip(), format=DATE_FMT, errors="coerce"),
        "td": pd.to_datetime(df["to_date"].str.strip(), format=DATE_FMT, errors="coerce"),
    })
    out = out[out["name"] != ""]
    out = out.drop_duplicates()
    return out.sort_values(["name", "cls", "status", "fd", "td", "sub"],
                           kind="stable").reset_index(drop=True)


def _sub_of(df):
    """One subdistrict per locality: the most frequent non-empty value."""
    s = df[df["sub"] != ""]
    if s.empty:
        return pd.Series(dtype=str)
    c = s.groupby(["name", "sub"]).size().reset_index(name="k")
    c = c.sort_values(["name", "k", "sub"], ascending=[True, False, True], kind="stable")
    return c.drop_duplicates("name").set_index("name")["sub"]


def _best(df, rank):
    r = df.assign(r=df["cls"].map(rank))
    return r.groupby("name")["r"].min()


def _localities(cur, rank):
    """Per-locality view of the current dev map."""
    best = _best(cur, rank)
    inv = {v: k for k, v in rank.items()}
    loc = pd.DataFrame({"best": best.map(inv)})
    loc["sub"] = _sub_of(cur).reindex(loc.index).fillna("").replace("", NO_SUB)
    loc["ind"] = cur.groupby("name")["ind"].any().reindex(loc.index)
    loc["gaza"] = cur.groupby("name")["gaza"].any().reindex(loc.index)

    def profile(g):
        pairs = sorted({(rank[c], c, s) for c, s in zip(g["cls"], g["status"])})
        return " · ".join(f"{cls_label(c)} — {STATUS_LABEL.get(s, s)}" for _, c, s in pairs)

    loc["profile"] = cur.groupby("name")[["cls", "status"]].apply(profile).reindex(loc.index)
    loc["split"] = cur.groupby("name")["cls"].nunique().reindex(loc.index) > 1
    return loc.sort_index()


def _snapshots(dev, rank, classes):
    valid = dev[dev["fd"].notna() & dev["td"].notna() & (dev["td"] >= dev["fd"])]
    if valid.empty:
        return [], {c: [] for c in classes}, None
    y0 = int(valid["fd"].min().year)
    y1 = int(valid["fd"].max().year)
    years, series = [], {c: [] for c in classes}
    inv = {v: k for k, v in rank.items()}
    for y in range(y0, y1 + 1):
        t = pd.Timestamp(year=y, month=SNAP_MONTH, day=SNAP_DAY)
        a = valid[(valid["fd"] <= t) & (valid["td"] >= t)]
        if a.empty:
            continue
        b = _best(a, rank).map(inv).value_counts()
        years.append(y)
        for c in classes:
            series[c].append(int(b.get(c, 0)))
    return years, series, len(dev) - len(valid)


def _decree(dev, cur, rank, classes):
    """Best class just before the latest decree's start vs. now."""
    fd = cur["fd"].dropna()
    if fd.empty:
        return None
    counts = fd.value_counts()
    counts = counts.sort_index().sort_values(ascending=False, kind="stable")
    start = counts.index[0]
    prev_t = start - pd.Timedelta(days=1)
    valid = dev[dev["fd"].notna() & dev["td"].notna()]
    prev = valid[(valid["fd"] <= prev_t) & (valid["td"] >= prev_t)]
    if prev.empty:
        return None
    inv = {v: k for k, v in rank.items()}
    a = _best(prev, rank).map(inv).rename("prev")
    b = _best(cur, rank).map(inv).rename("now")
    t = pd.concat([a, b], axis=1).fillna(NOT_LISTED)
    cats = classes + [NOT_LISTED]
    matrix = [[int(((t["prev"] == p) & (t["now"] == q)).sum()) for q in cats] for p in cats]
    rk = {c: i for i, c in enumerate(cats)}
    both = t[(t["prev"] != NOT_LISTED) & (t["now"] != NOT_LISTED)]
    up = int((both["now"].map(rk) < both["prev"].map(rk)).sum())
    down = int((both["now"].map(rk) > both["prev"].map(rk)).sum())
    added = int(((t["prev"] == NOT_LISTED) & (t["now"] != NOT_LISTED)).sum())
    removed = int(((t["prev"] != NOT_LISTED) & (t["now"] == NOT_LISTED)).sum())
    moves = {}
    for p in classes:
        for q in classes:
            if p != q:
                moves[(p, q)] = int(((t["prev"] == p) & (t["now"] == q)).sum())
    return {"start": start, "prev": prev_t, "cats": cats, "matrix": matrix, "up": up,
            "down": down, "added": added, "removed": removed, "moves": moves}


# ── insights ─────────────────────────────────────────────────────────────

def insight_classes(loc, classes):
    total = len(loc)
    if total == 0:
        return None
    vc = loc["best"].value_counts()
    parts = [f"{n(vc.get(c, 0))} ב{cls_label(c)}" for c in classes if vc.get(c, 0)]
    lead = classes[0]
    share = vc.get(lead, 0) / total
    return (f"במפת אזורי הפיתוח הנוכחית {n(total)} יישובים ואזורי תעשייה: "
            + ", ".join(parts)
            + f" (לפי הדרגה המועדפת של כל אחד). {pct(share * 100)} מהם נהנים מ{cls_label(lead)}, "
              f"הדרגה המטיבה ביותר.")


def insight_split(loc, cur):
    total = len(loc)
    sp = loc[loc["split"]]
    if total == 0 or len(sp) / total < 0.05:
        return None
    by = sp["best"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    lead = by.index[0]
    return (f"הסיווג תלוי בסוג התוכנית: ל-{n(len(sp))} יישובים ואזורים ({pct(len(sp) / total * 100)}) "
            f"יש יותר מדרגה אחת — לרוב {cls_label(lead)} להרחבת מפעל קיים ומרכז הארץ להקמת מפעל "
            f"חדש ({n(by.iloc[0])} מקרים).")


def insight_decree(dc):
    if dc is None:
        return None
    changed = dc["up"] + dc["down"]
    if changed + dc["added"] + dc["removed"] == 0:
        return (f"המפה שנכנסה לתוקף ב-{d_he(dc['start'])} לא שינתה את הדרגה המועדפת של אף "
                f"יישוב לעומת המפה הקודמת.")
    moves = sorted(((v, p, q) for (p, q), v in dc["moves"].items() if v),
                   key=lambda x: (-x[0], x[1], x[2]))
    top = ""
    if moves:
        v, p, q = moves[0]
        top = f" המעבר הנפוץ: מ{cls_label(p)} ל{cls_label(q)} ({n(v)})."
    return (f"במפה שנכנסה לתוקף ב-{d_he(dc['start'])} שופרה דרגתם של {n(dc['up'])} יישובים "
            f"ואזורים והורדה דרגתם של {n(dc['down'])}, לעומת המפה שבתוקף ערב כניסתה; "
            f"{n(dc['added'])} נוספו למפה ו-{n(dc['removed'])} אינם מופיעים בה עוד.{top}")


def insight_trend(years, series, classes):
    if len(years) < 5:
        return None
    best = None
    for c in classes:
        s = series[c]
        peak = max(s)
        if peak < 20:
            continue
        drop = 1 - s[-1] / peak
        if best is None or drop > best[0]:
            best = (drop, c, peak, years[s.index(peak)], s[-1])
    if best is None:
        return None
    drop, c, peak, py, last = best
    s = series[c]
    steps = [(s[i - 1] - s[i], years[i], years[i - 1]) for i in range(1, len(s))]
    big, by, bp = max(steps, key=lambda x: (x[0], -x[1]))
    if drop < 0.2:
        return (f"היקף המפה יציב יחסית לאורך השנים: אף דרגה לא ירדה ביותר מ-{pct(20, 0)} משיאה "
                f"(תמונת מצב ב-{SNAP_DAY} ב{MONTHS_HE[SNAP_MONTH - 1]} בכל שנה, {years[0]}–{years[-1]}).")
    return (f"{cls_label(c)} הצטמצמה במידה הניכרת ביותר: {n(peak)} יישובים ואזורים בשיאה ({py}) "
            f"לעומת {n(last)} ב-{years[-1]} — ירידה של {pct(drop * 100)}"
            + (f"; הצניחה החדה ביותר בין {bp} ל-{by} ({n(big)} פחות)." if big > 0 else ".")
            )


def insight_sub(loc, classes):
    lead = classes[0]
    a = loc[(loc["best"] == lead) & (loc["sub"] != NO_SUB)]
    if len(a) < 20:
        return None
    vc = a["sub"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    allA = int((loc["best"] == lead).sum())
    share = vc.iloc[0] / allA
    if share < 0.15:
        return None
    return (f"{vc.index[0]} מרכזת את המספר הגדול ביותר של יישובים ואזורים ב{cls_label(lead)}: "
            f"{n(vc.iloc[0])} מתוך {n(allA)} ({pct(share * 100)}), "
            f"ואחריה {vc.index[1]} ({n(vc.iloc[1])}).")


def insight_overlap(nap_names, loc, classes):
    if not len(nap_names):
        return None
    m = pd.Series(nap_names).map(loc["best"]).fillna(NOT_LISTED)
    center = "מרכז הארץ"
    if center not in classes:
        return None
    c = int((m == center).sum())
    share = c / len(m)
    if share < 0.1:
        return None
    lead = classes[0]
    a_all = loc.index[loc["best"] == lead]
    a_out = int((~pd.Series(a_all).isin(set(nap_names))).sum())
    tail = (f" מנגד, {n(a_out)} מהיישובים והאזורים ב{cls_label(lead)} אינם במפת העדיפות הלאומית."
            if a_out else "")
    return (f"שתי המפות אינן חופפות: {n(c)} מתוך {n(len(m))} היישובים והאזורים במפת העדיפות "
            f"הלאומית ({pct(share * 100)}) מסווגים במפת אזורי הפיתוח כמרכז הארץ.{tail}")


def insight_gaza(loc, nap, nap_gaza):
    g = loc[loc["gaza"]]
    if g.empty:
        return None
    ng = int(nap_gaza.sum())
    lead = CLASS_ORDER[0]
    a = int((g["best"] == lead).sum())
    in_nap = int(g.index.isin(set(nap["name"])).sum())
    word = "כולם" if a == len(g) else f"{n(a)} מהם"
    word2 = "וכולם נכללים" if in_nap == len(g) else f"ו-{n(in_nap)} מהם נכללים"
    return (f"{n(len(g))} יישובים ואזורי תעשייה במפת אזורי הפיתוח מסומנים כעוטף עזה; {word} "
            f"ב{cls_label(lead)}, {word2} גם במפת העדיפות הלאומית (שבה מסומנים {n(ng)} "
            f"כעוטף עזה).")


def insight_industrial(loc, classes):
    ind = loc[loc["ind"]]
    if len(ind) < 10:
        return None
    lead = classes[0]
    a = int((ind["best"] == lead).sum())
    share = a / len(ind)
    return (f"במפה {n(len(ind))} אזורי תעשייה ופארקי תעסוקה; {pct(share * 100)} מהם "
            f"({n(a)}) ב{cls_label(lead)} — לעומת {pct((loc['best'] == lead).mean() * 100)} "
            f"מכלל היישובים והאזורים.")


def insight_nap_new(nap):
    fd = nap["fd"].dropna()
    if fd.empty:
        return None
    counts = fd.value_counts().sort_index().sort_values(ascending=False, kind="stable")
    base = counts.index[0]
    later = nap[nap["fd"] > base]
    if later.empty:
        return None
    last = later["fd"].max()
    return (f"רוב מפת העדיפות הלאומית ({n(counts.iloc[0])} מתוך {n(len(nap))} רשומות) בתוקף "
            f"מ-{d_he(base)}; {n(len(later))} רשומות צורפו אליה מאז, האחרונה ב-{d_he(last)}.")


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    dev = _prep(frames["dev"])
    nap = _prep(frames["nap"])
    rank = _rank_map(dev["cls"])
    classes = sorted({c for c in dev["cls"] if c}, key=lambda c: rank[c])
    cur = dev[~dev["hist"]]
    loc = _localities(cur, rank)
    total = len(loc)
    vc_best = loc["best"].value_counts()
    nap_names = sorted(set(nap["name"]))
    nap_sub = _sub_of(nap).reindex(nap_names).fillna("").replace("", NO_SUB)
    nap_ind = nap.groupby("name")["ind"].any().reindex(nap_names)
    nap_gaza = nap.groupby("name")["gaza"].any().reindex(nap_names)

    # validity of the current map: most common end date among current rows
    td = cur["td"].dropna()
    td = td[td.dt.year > 1900]
    valid_to = (td.value_counts().sort_index().sort_values(ascending=False, kind="stable").index[0]
                if not td.empty else None)
    nap_td = nap["td"].dropna()
    nap_td = nap_td[nap_td.dt.year > 1900]
    nap_to = (nap_td.value_counts().sort_index().sort_values(ascending=False, kind="stable").index[0]
              if not nap_td.empty else None)

    # 1. profiles
    pc = loc["profile"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    p_top = pc.head(TOP_PROFILES)
    p_other = int(pc.iloc[TOP_PROFILES:].sum())
    p_names = list(p_top.index) + (["שילובים אחרים"] if p_other else [])
    p_vals = [int(v) for v in p_top.values] + ([p_other] if p_other else [])

    # 2. class × status (rows)
    statuses = [s for s in STATUS_ORDER if s in set(cur["status"])] + sorted(
        set(cur["status"]) - set(STATUS_ORDER))
    cs = cur.groupby(["cls", "status"]).size()
    status_series = [{"name": STATUS_LABEL.get(s, s),
                      "data": [int(cs.get((c, s), 0)) for c in classes]} for s in statuses]

    # 3. subdistricts (localities by best class)
    real = loc[loc["sub"] != NO_SUB]
    sc = real["sub"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    top_subs = list(sc.index[:TOP_SUB])
    def sub_bucket(s):
        if s == NO_SUB:
            return NO_SUB
        return s if s in top_subs else OTHER_SUB
    loc["subb"] = loc["sub"].map(sub_bucket)
    sub_names = top_subs + ([OTHER_SUB] if len(sc) > TOP_SUB else []) + (
        [NO_SUB] if (loc["sub"] == NO_SUB).any() else [])
    sb = loc.groupby(["subb", "best"]).size()
    sub_series = [{"name": cls_label(c), "data": [int(sb.get((s, c), 0)) for s in sub_names]}
                  for c in classes]
    sub_rows = [{"name": s, "cells": [n(sb.get((s, c), 0)) for c in classes],
                 "total": n(sum(int(sb.get((s, c), 0)) for c in classes))} for s in sub_names]

    # 4. national priority by subdistrict
    nsc = nap_sub[nap_sub != NO_SUB].value_counts().sort_index().sort_values(
        ascending=False, kind="stable")
    n_top = list(nsc.index[:TOP_NAP_SUB])
    n_other = int(nsc.iloc[TOP_NAP_SUB:].sum())
    n_none = int((nap_sub == NO_SUB).sum())
    nap_sub_names = n_top + ([OTHER_SUB] if n_other else []) + ([NO_SUB] if n_none else [])
    nap_sub_vals = [int(nsc[s]) for s in n_top] + ([n_other] if n_other else []) + (
        [n_none] if n_none else [])

    # 5. history snapshots
    years, snap, invalid = _snapshots(dev, rank, classes)

    # 6. decree waves (rows by start date)
    w = dev[dev["fd"].notna()]
    wc = w["fd"].value_counts()
    waves = sorted(d for d, k in wc.items() if k >= WAVE_MIN)
    wcl = w.groupby(["fd", "cls"]).size()
    wave_x = [d.strftime("%m/%Y") for d in waves]
    wave_series = [{"name": cls_label(c), "data": [int(wcl.get((d, c), 0)) for d in waves]}
                   for c in classes]
    wave_rows = [{"date": d_he(d), "cells": [n(wcl.get((d, c), 0)) for c in classes],
                  "total": n(wc[d])} for d in waves]
    wave_rest = int(len(w) - sum(int(wc[d]) for d in waves))

    # 7. transitions
    dc = _decree(dev, cur, rank, classes)
    trans = None
    if dc is not None:
        labels_t = [cls_label(c) for c in classes] + [NOT_LISTED]
        cells = [[j, i, dc["matrix"][i][j]] for i in range(len(labels_t))
                 for j in range(len(labels_t))]
        trans = {"labels": labels_t, "cells": cells,
                 "max": max(max(r) for r in dc["matrix"]) or 1}

    # 8. national priority × dev best class
    ov = pd.Series(nap_names, dtype=str).map(loc["best"]).fillna(NOT_LISTED)
    ov_cats = classes + [NOT_LISTED]
    ov_names = [cls_label(c) if c != NOT_LISTED else "לא במפת אזורי הפיתוח" for c in ov_cats]
    ov_vals = [int((ov == c).sum()) for c in ov_cats]
    nap_set = set(nap_names)
    in_nap = loc.index.isin(nap_set)
    rev_vals_in = [int(((loc["best"] == c) & in_nap).sum()) for c in classes]
    rev_vals_out = [int(((loc["best"] == c) & ~in_nap).sum()) for c in classes]

    # 9. kinds (localities vs industrial areas) per framework
    kind_names = [cls_label(c) for c in classes] + ["עדיפות לאומית"]
    kind_loc = [int(((loc["best"] == c) & ~loc["ind"]).sum()) for c in classes] + [
        int((~nap_ind).sum())]
    kind_ind = [int(((loc["best"] == c) & loc["ind"]).sum()) for c in classes] + [
        int(nap_ind.sum())]

    # 10. national-priority entry dates
    nfd = nap["fd"].dropna()
    ndc = nfd.value_counts().sort_index()
    by_year = len(ndc) > 10
    if by_year:
        ndc = nfd.dt.year.value_counts().sort_index()
        nd_names = [str(int(y)) for y in ndc.index]
        nd_rows = [{"date": str(int(y)), "count": n(v)} for y, v in ndc.items()]
    else:
        nd_names = [d.strftime("%m/%Y") for d in ndc.index]
        nd_rows = [{"date": d_he(d), "count": n(v)} for d, v in ndc.items()]
    nd_vals = [int(v) for v in ndc.values]

    # insights
    rules = [
        ("classes", insight_classes(loc, classes)),
        ("split", insight_split(loc, cur)),
        ("decree", insight_decree(dc)),
        ("trend", insight_trend(years, snap, classes)),
        ("sub", insight_sub(loc, classes)),
        ("overlap", insight_overlap(nap_names, loc, classes)),
        ("gaza", insight_gaza(loc, nap, nap_gaza)),
        ("industrial", insight_industrial(loc, classes)),
        ("nap_new", insight_nap_new(nap)),
    ]
    insights = [{"id": k, "text_he": v} for k, v in rules if v]

    # KPIs
    lead = classes[0] if classes else ""
    a_cnt = int(vc_best.get(lead, 0))
    gaza_cnt = int(loc["gaza"].sum())
    split_cnt = int(loc["split"].sum())
    kpis = {
        "localities": {"value": total, "display": n(total), "tone": "brand"},
        "class_a": {"value": a_cnt, "display": n(a_cnt), "tone": "ok" if a_cnt else "brand"},
        "nap": {"value": len(nap_names), "display": n(len(nap_names)), "tone": "brand"},
        "gaza": {"value": gaza_cnt, "display": n(gaza_cnt), "tone": "info"},
    }
    if dc is not None:
        kpis["upgraded"] = {"value": dc["up"], "display": n(dc["up"]),
                            "tone": "ok" if dc["up"] > dc["down"] else "info"}
        kpis["downgraded"] = {"value": dc["down"], "display": n(dc["down"]),
                              "tone": "danger" if dc["down"] > dc["up"] else "warn" if dc["down"] else "brand"}
    kpis["split"] = {"value": split_cnt, "display": n(split_cnt), "tone": "info"}
    kpis["history"] = {"value": int(dev["hist"].sum()), "display": n(dev["hist"].sum()),
                       "tone": "brand"}

    first_year = int(dev["fd"].min().year) if dev["fd"].notna().any() else None
    to_txt = f", בתוקף עד {d_he(valid_to)}" if valid_to is not None else ""
    nap_to_txt = f" (בתוקף עד {d_he(nap_to)})" if nap_to is not None else ""
    split_word = cls_label(lead)
    since = f" מאז {first_year}" if first_year else ""
    decree_txt = (f"המפה הנוכחית בתוקף מ-{d_he(dc['start'])}." if dc is not None else "")
    snap_label = f"{SNAP_DAY} ב{MONTHS_HE[SNAP_MONTH - 1]}"

    labels = {
        "lede": (f"מפת אזורי הפיתוח של משרד הכלכלה והתעשייה קובעת את דרגת ההטבה לפי מיקום "
                 f"המפעל: {n(total)} יישובים ואזורי תעשייה בה כיום{to_txt}. לצדה מפת העדיפות "
                 f"הלאומית — {n(len(nap_names))} יישובים ואזורים{nap_to_txt}. המאגר שומר גם "
                 f"{n(dev['hist'].sum())} סיווגים היסטוריים{since}."),
        "k_localities": "יישובים ואזורי תעשייה במפת אזורי הפיתוח",
        "k_class_a": f"מהם ב{split_word} (הדרגה המטיבה ביותר)",
        "k_nap": "יישובים ואזורים במפת העדיפות הלאומית",
        "k_gaza": "יישובים ואזורים בעוטף עזה",
        "k_upgraded": (f"שדרגתם שופרה במפה מ-{d_he(dc['start'])}" if dc is not None else ""),
        "k_downgraded": (f"שדרגתם הורדה במפה מ-{d_he(dc['start'])}" if dc is not None else ""),
        "k_split": "עם דרגה שונה להקמה ולהרחבה",
        "k_history": "סיווגים היסטוריים שאינם בתוקף",
        "profile_note": (f"הצירוף של דרגה וסוג תוכנית שכל יישוב או אזור מקבל במפה הנוכחית. "
                         f"{n(split_cnt)} מהם מקבלים דרגה שונה להקמת מפעל חדש ולהרחבת מפעל קיים."),
        "profile_aria": f"תרשים עמודות: יישובים ואזורים לפי צירוף הדרגות שלהם, {len(p_names)} צירופים.",
        "profile_caption": "מספר היישובים והאזורים לפי צירוף דרגה וסוג תוכנית במפה הנוכחית.",
        "status_note": (f"{n(len(cur))} סיווגים בתוקף — כל יישוב מופיע פעם אחת לכל סוג תוכנית "
                        f"שמסווג אצלו בנפרד."),
        "status_aria": "תרשים עמודות מוערמות: סיווגים בתוקף לפי דרגה וסוג תוכנית.",
        "status_caption": "מספר הסיווגים בתוקף לפי דרגה וסוג תוכנית.",
        "sub_note": (f"יישובים ואזורים לפי הנפה ולפי הדרגה המועדפת שלהם. {len(top_subs)} הנפות הגדולות "
                     f"מוצגות בנפרד; {n((loc['sub'] == NO_SUB).sum())} רשומים ללא נפה."),
        "sub_aria": f"תרשים עמודות מוערמות: יישובים ואזורים לפי נפה ודרגה, {len(sub_names)} קבוצות.",
        "sub_caption": "מספר היישובים והאזורים לפי נפה ודרגה מועדפת.",
        "nap_sub_note": (f"{n(len(nap_names))} היישובים והאזורים במפת העדיפות הלאומית לפי נפה; "
                         f"{n(n_none)} רשומים ללא נפה."),
        "nap_sub_aria": f"תרשים עמודות: יישובים ואזורים בעדיפות לאומית לפי נפה, {len(nap_sub_names)} קבוצות.",
        "nap_sub_caption": "מספר היישובים והאזורים במפת העדיפות הלאומית לפי נפה.",
        "history_note": (f"כמה יישובים ואזורים היו בכל דרגה, לפי תקופות התוקף שבמאגר — תמונת "
                         f"מצב ב-{snap_label} בכל שנה, {years[0]}–{years[-1]}." if years else "")
                        + (f" {n(invalid)} רשומות עם תאריכי תוקף חסרים או הפוכים אינן נכללות."
                           if invalid else ""),
        "history_aria": (f"גרף שטח מוערם: יישובים ואזורים לפי דרגה, {years[0]} עד {years[-1]}."
                         if years else "גרף שטח מוערם: יישובים ואזורים לפי דרגה לאורך השנים."),
        "history_caption": f"מספר היישובים והאזורים בכל דרגה, נכון ל-{snap_label} בכל שנה.",
        "waves_note": (f"מספר הסיווגים שנכנסו לתוקף בכל מועד שבו נכנסו לתוקף לפחות {WAVE_MIN} "
                       f"סיווגים — גלי ההחלטות על מפת אזורי הפיתוח. {n(wave_rest)} סיווגים "
                       f"נוספים נכנסו לתוקף בעדכונים נקודתיים ואינם מוצגים."),
        "waves_aria": f"תרשים עמודות מוערמות: סיווגים לפי מועד כניסה לתוקף ודרגה, {len(waves)} מועדים.",
        "waves_caption": "מספר הסיווגים שנכנסו לתוקף בכל גל החלטות, לפי דרגה.",
        "trans_note": (f"הדרגה המועדפת של כל יישוב ואזור ערב כניסת המפה הנוכחית לתוקף "
                       f"({d_he(dc['prev'])}) לעומת היום. {n(dc['up'])} שופרו, {n(dc['down'])} "
                       f"הורדו. שורות: הדרגה במפה הקודמת; עמודות: הדרגה היום." if dc is not None else ""),
        "trans_aria": "מפת חום: מעברי דרגה בין המפה הקודמת למפה הנוכחית.",
        "trans_caption": "מספר היישובים והאזורים לפי דרגה במפה הקודמת (שורות) ובמפה הנוכחית (עמודות).",
        "overlap_note": (f"היישובים והאזורים במפת העדיפות הלאומית לפי הדרגה שלהם במפת אזורי "
                         f"הפיתוח (התאמה לפי שם). {n(ov_vals[-1])} מהם אינם במפת אזורי הפיתוח."),
        "overlap_aria": "תרשים עמודות: יישובי עדיפות לאומית לפי דרגת אזור הפיתוח.",
        "overlap_caption": "מספר היישובים והאזורים בעדיפות לאומית לפי דרגתם במפת אזורי הפיתוח.",
        "rev_note": "כמה מהיישובים והאזורים בכל דרגה נכללים גם במפת העדיפות הלאומית.",
        "rev_aria": "תרשים עמודות מוערמות: יישובים ואזורים בכל דרגה, בעדיפות לאומית ומחוצה לה.",
        "rev_caption": "מספר היישובים והאזורים בכל דרגה, בעדיפות לאומית ומחוצה לה.",
        "kinds_note": (f"{n(loc['ind'].sum())} אזורי תעשייה במפת אזורי הפיתוח ו-{n(nap_ind.sum())} "
                       f"במפת העדיפות הלאומית."),
        "kinds_aria": "תרשים עמודות מוערמות: יישובים ואזורי תעשייה בכל מסגרת.",
        "kinds_caption": "מספר היישובים ואזורי התעשייה בכל מסגרת (דרגה מועדפת).",
        "nap_dates_note": (f"מועד הכניסה לתוקף של כל רשומה במפת העדיפות הלאומית"
                           + (", לפי שנה." if by_year else ".")
                           + (f" המפה בתוקף עד {d_he(nap_to)}." if nap_to is not None else "")),
        "nap_dates_aria": f"תרשים עמודות: רשומות עדיפות לאומית לפי מועד כניסה לתוקף, {len(nd_names)} מועדים.",
        "nap_dates_caption": "מספר הרשומות במפת העדיפות הלאומית לפי מועד כניסה לתוקף.",
        "class_cols": [cls_label(c) for c in classes],
        "decree": decree_txt,
    }

    charts = {
        "profile": {"names": p_names, "values": p_vals},
        "status": {"x": [cls_label(c) for c in classes], "series": status_series},
        "sub": {"names": sub_names, "series": sub_series},
        "nap_sub": {"names": nap_sub_names, "values": nap_sub_vals},
        "history": {"x": [str(y) for y in years],
                    "series": [{"name": cls_label(c), "data": snap[c]} for c in classes]},
        "waves": {"x": wave_x, "series": wave_series},
        "trans": trans,
        "overlap": {"names": ov_names, "values": ov_vals},
        "rev": {"names": [cls_label(c) for c in classes],
                "series": [{"name": "גם בעדיפות לאומית", "data": rev_vals_in},
                           {"name": "לא בעדיפות לאומית", "data": rev_vals_out}]},
        "kinds": {"names": kind_names,
                  "series": [{"name": "יישובים", "data": kind_loc},
                             {"name": "אזורי תעשייה", "data": kind_ind}]},
        "nap_dates": {"names": nd_names, "values": nd_vals},
    }

    tables = {
        "profile": [{"name": k, "count": n(v)} for k, v in zip(p_names, p_vals)],
        "status": [{"name": cls_label(c),
                    "cells": [n(cs.get((c, s), 0)) for s in statuses]} for c in classes],
        "status_cols": [STATUS_LABEL.get(s, s) for s in statuses],
        "sub": sub_rows,
        "nap_sub": [{"name": k, "count": n(v)} for k, v in zip(nap_sub_names, nap_sub_vals)],
        "history": [{"year": str(y), "cells": [n(snap[c][i]) for c in classes],
                     "total": n(sum(snap[c][i] for c in classes))} for i, y in enumerate(years)],
        "waves": wave_rows,
        "trans": ([{"name": lab, "cells": [n(v) for v in row]}
                   for lab, row in zip(trans["labels"], dc["matrix"])] if trans else []),
        "trans_cols": trans["labels"] if trans else [],
        "overlap": [{"name": k, "count": n(v)} for k, v in zip(ov_names, ov_vals)],
        "rev": [{"name": cls_label(c), "inn": n(a), "out": n(b)}
                for c, a, b in zip(classes, rev_vals_in, rev_vals_out)],
        "kinds": [{"name": k, "loc": n(a), "ind": n(b)}
                  for k, a, b in zip(kind_names, kind_loc, kind_ind)],
        "nap_dates": nd_rows,
    }

    last_year = max([d.year for d in [valid_to, nap_to] if d is not None], default=None)
    summary = (f"מפת אזורי הפיתוח הנוכחית של משרד הכלכלה והתעשייה כוללת {n(total)} יישובים ואזורי "
               f"תעשייה — {n(a_cnt)} ב{cls_label(lead)} — ומפת העדיפות הלאומית כוללת "
               f"{n(len(nap_names))}. המאגר כולל גם את היסטוריית הסיווגים{since}, לפי דרגה, "
               f"סוג תוכנית ונפה.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["אזורי פיתוח", "עדיפות לאומית", "עידוד השקעות הון", "פריפריה",
                           "אזורי תעשייה", "עוטף עזה"],
        "related_ids": ["4acf8b98-776e-4c36-8f98-73cc73fed623"],
        "spatial_coverage": "ישראל",
    }
    if first_year and last_year:
        agent_data["temporal_coverage"] = f"{first_year}/{last_year}"

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"decree": dc is not None, "history": bool(years), "waves": bool(waves),
                  "nap": bool(nap_names)},
    }
