"""מסגרות הרווחה שבפיקוח משרד הרווחה והביטחון החברתי.

One row per active welfare framework (day-care centre, club, residential
home, hostel, sheltered workshop, treatment centre, ...) supervised by the
ministry: its type, the ministry department responsible for it, ownership,
operating network, welfare authority, district, actual occupancy, start date
and ITM coordinates.

The file is a snapshot replaced wholesale on each update (every row is
"פעילה"), so the only time axis is the start date of the frameworks that are
active today — a survivor view, disclosed as such. Growth means new
frameworks, types, departments and authorities; they all flow through, and
top-N + "אחר" caps keep every chart mobile-sized.

Sensitivity. Some frameworks serve protected populations (women and girls in
distress, at-risk and detained youth, people in addiction treatment,
probation clients, residential homes). The page never shows a framework's
address or individual location for those: they appear only inside counts.
The map shows a positive allow-list of community / day services under
departments that do not serve protected populations — an unknown new type or
department is NOT mapped until a human adds it here.
"""
import pandas as pd

TOP_TYPES = 15
TOP_AUTH = 15
TOP_DEPTS = 12
TOP_YEAR_DEPTS = 5
TOP_NETWORKS = 10
BOX_TYPES = 10
YEAR_WINDOW = 30         # yearly bars for the latest N years; earlier years in one bucket
RECENT_YEARS = 5         # "opened in the last N full years" insight
MIN_DEPT_REGION = 50     # department size for the regional over-representation rule
OVERREP_RATIO = 1.3      # region share at least this many times the overall share
MIN_BOX_N = 20           # frameworks with a reported occupancy needed for a box

# Map allow-lists (raw source values). Unknown values are not mapped.
MAP_DEPTS = [
    "ילד ונוער", "אזרחים ותיקים", 'אגף מש"ה', "רווחת הפרט ומש`", "נוער וצעירים",
    "שיקום ונכים", "אוטיסטים", "השרות לעיוור", "מנהל מוגבלויות", "מנהלת קליטה",
]
MAP_TYPES = [
    "מעון יום", "מועדונית", "מועדון/מרכז קהילתי", "טיפול יום", 'תעסוקה מוגנת )מע"ש(',
    "שילוב בתעסוקה", "תחנה לטיפול המשפחה", "קייטנה", "מועדונית שיקומית",
    "תעסוקה ניתמכת", "שילוב במעון יום", "מרכז שיקום", "מוקד תעסוקה", "תגבור צהרון",
    "ארוחות חמות", "מרכז רב שרותים",
]
MAP_EXCLUDE_SECOND = {"פגיעות מיניות", "חלופת מעצר", "בעיות התנהגות", "הכלה בתנאי שטח"}

DEPT_DISPLAY = {"רווחת הפרט ומש`": "רווחת הפרט והמשפחה", 'אגף מש"ה': 'מוגבלות שכלית (מש"ה)'}
UNASSIGNED = {"לא משויך", "לא ידוע", "אחר", ""}
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר",
             "אוקטובר", "נובמבר", "דצמבר"]
OWNER_ORDER = ["רשות מקומית", "ציבורי", "ארגון מפעיל", "פרטי", "ממשלתי"]


def clean_label(s):
    s = s.strip()
    # the source stores some parentheses mirrored: 'תעסוקה מוגנת )מע"ש('
    if ")" in s and "(" in s and s.index(")") < s.rindex("("):
        s = s.replace(")", "\0").replace("(", ")").replace("\0", "(")
    return s.replace('"', "״")


def dept_label(s):
    return DEPT_DISPLAY.get(s, s).replace('"', "״")


def network_label(s):
    s = s.strip()
    head, _, rest = s.partition(" ")
    if head.isdigit() and rest:
        s = rest.strip()
    s = s.strip('"').strip()
    return s.replace('"', "״")


def n(v):
    return f"{int(v):,}"


def pct(a, b, digits=1):
    return f"{a / b * 100:.{digits}f}%" if b else "—"


def _sorted_counts(s):
    """value_counts with a total, deterministic order (count desc, label asc)."""
    vc = s.value_counts()
    df = pd.DataFrame({"name": vc.index, "n": vc.values})
    return df.sort_values(["n", "name"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def _prepare(raw):
    df = pd.DataFrame({
        "type_raw": raw["Type_Descr"].str.strip(),
        "dept_raw": raw["Head_Department"].str.strip(),
        "second_raw": raw["Second_Classific"].str.strip(),
        "owner": raw["Owner_Code_Descr"].str.strip().replace("", "לא ידוע"),
        "org": raw["Organization"].str.strip(),
        "op": raw["Registered_Business_Id"].str.strip(),
        "auth": raw["Authoritys"].str.strip().replace("", "לא ידוע"),
        "region": raw["Region_Descr"].str.strip().replace("", "לא ידוע"),
        "gender": raw["Gender_Descr"].str.strip(),
        "gx": pd.to_numeric(raw["GisX"].str.strip(), errors="coerce"),
        "gy": pd.to_numeric(raw["GisY"].str.strip(), errors="coerce"),
    })
    df["type_raw"] = df["type_raw"].replace("", "לא ידוע")
    df["dept_raw"] = df["dept_raw"].replace("", "לא ידוע")
    df["type"] = df["type_raw"].map(clean_label)
    df["dept"] = df["dept_raw"].map(dept_label)
    cap = pd.to_numeric(raw["Actual_Capacity"].str.replace(",", "", regex=False).str.strip(),
                        errors="coerce")
    df["cap"] = cap.where(cap > 0)          # 0 = not reported
    d = pd.to_datetime(raw["STARTD"].str.strip(), format="%d/%m/%Y", errors="coerce")
    df["year"] = d.dt.year
    df["month"] = d.dt.month
    df["has_xy"] = df["gx"].between(100000, 300000) & df["gy"].between(350000, 800000)
    return df


# ── insight rules ────────────────────────────────────────────────────────────

def insight_dept(depts, total):
    if len(depts) < 2:
        return None
    a, b = depts.iloc[0], depts.iloc[1]
    share = a["n"] / total
    if share < 0.2:
        return None
    return (f"אגף {a['name']} מפקח על {n(a['n'])} מסגרות — {pct(a['n'], total)} מכלל "
            f"המסגרות, יותר מפי {a['n'] / b['n']:.1f} מהאגף השני בגודלו ({b['name']}, "
            f"{n(b['n'])}).")


def insight_type(types, total, df):
    if types.empty:
        return None
    t = types.iloc[0]
    share = t["n"] / total
    if share < 0.1:
        return None
    sub = df[df["type"] == t["name"]]
    own = _sorted_counts(sub["owner"]).iloc[0]
    return (f"{t['name']} הוא סוג המסגרת הנפוץ ביותר: {n(t['n'])} מסגרות ({pct(t['n'], total)}); "
            f"הבעלות הנפוצה בהן — {own['name']} ({pct(own['n'], len(sub))}).")


def insight_owner(owners, total):
    if owners.empty:
        return None
    a = owners.iloc[0]
    if a["n"] / total < 0.3:
        return None
    rest = [f"{r['name']} {pct(r['n'], total)}" for _, r in owners.iloc[1:4].iterrows()]
    return (f"{pct(a['n'], total)} מהמסגרות בבעלות {a['name']}"
            + (f"; אחריהן {', '.join(rest)}." if rest else "."))


def insight_region_overrep(df, total):
    reg_share = df["region"].value_counts() / total
    best = None
    for (dept, region), cnt in df.groupby(["dept", "region"]).size().items():
        dn = int((df["dept"] == dept).sum())
        if dn < MIN_DEPT_REGION:
            continue
        ratio = (cnt / dn) / reg_share[region]
        key = (ratio, cnt, dept, region)
        if ratio >= OVERREP_RATIO and (best is None or key > best[0]):
            best = (key, dept, region, int(cnt), dn)
    if best is None:
        return None
    _, dept, region, cnt, dn = best
    return (f"מחוז {region} מרכז {pct(cnt, dn)} ממסגרות אגף {dept} ({n(cnt)} מתוך {n(dn)}), "
            f"לעומת {pct(reg_share[region] * total, total)} מכלל המסגרות — הייצוג היחסי הגבוה "
            f"ביותר של אגף במחוז (מבין אגפים עם {MIN_DEPT_REGION} מסגרות לפחות).")


def insight_auth(auths, total, n_auth):
    if len(auths) < 5:
        return None
    a = auths.iloc[0]
    top5 = int(auths.head(5)["n"].sum())
    return (f"ב{a['name']} פועלות {n(a['n'])} מסגרות ({pct(a['n'], total)}), הרבה ביותר מבין "
            f"{n(n_auth)} רשויות הרווחה; חמש הרשויות המובילות מרכזות {pct(top5, total)} "
            f"מהמסגרות.")


def insight_recent(df, full_years, latest_year, partial):
    if len(full_years) < RECENT_YEARS + 3:
        return None
    yrs = full_years[-RECENT_YEARS:]
    valid = df["year"].notna()
    cnt = int(df["year"].isin(yrs).sum())
    tot = int(valid.sum())
    y_counts = df.loc[df["year"].isin(full_years), "year"].value_counts()
    peak = y_counts.sort_index().idxmax()
    tail = ""
    if partial is not None:
        tail = (f" בשנת {latest_year} (עד {MONTHS_HE[partial - 1]}) נוספו עד כה "
                f"{n((df['year'] == latest_year).sum())}.")
    return (f"מבין המסגרות הפעילות כיום, {n(cnt)} ({pct(cnt, tot)}) החלו לפעול בחמש השנים "
            f"המלאות האחרונות ({yrs[0]} עד {yrs[-1]}); שנת השיא היא {int(peak)} עם "
            f"{n(y_counts[peak])} מסגרות.{tail}")


def insight_capacity(df):
    rep = df[df["cap"].notna()]
    if len(rep) < 50:
        return None
    by = rep.groupby("dept")["cap"].agg(["sum", "median", "size"]).reset_index()
    by = by[by["size"] >= MIN_BOX_N]
    if by.empty:
        return None
    s = by.sort_values(["sum", "dept"], ascending=[False, True], kind="mergesort").iloc[0]
    total = rep["cap"].sum()
    return (f"התפוסה בפועל המדווחת מסתכמת ב-{n(total)} מקבלי שירות; הגדולה ביותר באגף "
            f"{s['dept']} ({n(s['sum'])}, {pct(s['sum'], total)}), שבו חציון התפוסה למסגרת "
            f"הוא {n(s['median'])}, לעומת {n(rep['cap'].median())} בכלל המסגרות.")


def insight_unreported(df, total):
    k = int(df["cap"].isna().sum())
    if k / total < 0.05:
        return None
    by = _sorted_counts(df.loc[df["cap"].isna(), "dept"])
    lead = by.iloc[0]
    return (f"ב-{n(k)} מסגרות ({pct(k, total)}) לא דווחה תפוסה (ערך אפס) — הרבות ביותר "
            f"באגף {lead['name']} ({n(lead['n'])}); הן נספרות במספר המסגרות אך לא בסכומי התפוסה.")


def insight_networks(nets, total):
    if nets.empty:
        return None
    k = int(nets["n"].sum())
    a = nets.iloc[0]
    if k / total < 0.03:
        return None
    return (f"{n(k)} מסגרות ({pct(k, total)}) מופעלות בידי {n(len(nets))} רשתות וארגונים "
            f"ארציים; הגדולה שבהן — {a['name']}, עם {n(a['n'])} מסגרות.")


# ── compute ──────────────────────────────────────────────────────────────────

def _top_other(counts, k):
    top = counts.head(k)
    rest = counts.iloc[k:]
    names = list(top["name"])
    vals = [int(v) for v in top["n"]]
    if len(rest):
        names.append("אחר")
        vals.append(int(rest["n"].sum()))
    return names, vals


def _cap_sum(df, key, names):
    s = df.groupby(key)["cap"].sum()
    out = []
    for nm in names:
        out.append(int(s.get(nm, 0)))
    return out


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)

    depts = _sorted_counts(df["dept"])
    types = _sorted_counts(df["type"])
    owners = _sorted_counts(df["owner"])
    regions = _sorted_counts(df["region"])
    auths = _sorted_counts(df["auth"])
    n_auth = len(auths)
    cap_known = df["cap"].notna()
    cap_total = int(df["cap"].sum())

    # ── departments: count + reported occupancy
    d_names, d_vals = _top_other(depts, TOP_DEPTS)
    d_top = set(d_names) - {"אחר"}
    df["dept_g"] = df["dept"].where(df["dept"].isin(d_top), "אחר")
    d_cap = _cap_sum(df, "dept_g", d_names)
    ch_dept = {"names": d_names, "n": d_vals, "cap": d_cap}

    # ── types
    t_names, t_vals = _top_other(types, TOP_TYPES)
    t_top = set(t_names) - {"אחר"}
    df["type_g"] = df["type"].where(df["type"].isin(t_top), "אחר")
    t_cap = _cap_sum(df, "type_g", t_names)
    t_named = [i for i, nm in enumerate(t_names) if nm != "אחר"]
    ch_types = {"names": [t_names[i] for i in t_named], "n": [t_vals[i] for i in t_named]}

    # ── treemap: department → type
    tree = []
    dt = df.groupby(["dept", "type"]).size()
    for _, r in depts.iterrows():
        kids = dt.loc[r["name"]]
        kd = pd.DataFrame({"name": kids.index, "n": kids.values}).sort_values(
            ["n", "name"], ascending=[False, True], kind="mergesort")
        tree.append({"name": r["name"], "value": int(r["n"]),
                     "children": [{"name": t, "value": int(v)} for t, v in zip(kd["name"], kd["n"])]})

    # ── ownership by department (100% stacked)
    own_names = [o for o in OWNER_ORDER if o in set(owners["name"])] + \
        [o for o in owners["name"] if o not in OWNER_ORDER]
    od = df.groupby(["dept_g", "owner"]).size()
    dept_rows = [nm for nm in d_names]
    own_series = []
    for o in own_names:
        data = []
        for dn in dept_rows:
            tot_d = int((df["dept_g"] == dn).sum())
            v = int(od.get((dn, o), 0))
            data.append(round(v / tot_d * 100, 1) if tot_d else 0)
        own_series.append({"name": o, "data": data})
    ch_owner = {"names": dept_rows, "series": own_series,
                "all": [round(int(r["n"]) / total * 100, 1) for _, r in
                        owners.set_index("name").loc[own_names].reset_index().iterrows()],
                "owners": own_names}

    # ── region × department heatmap (% of the department's frameworks in each region)
    r_names = list(regions["name"])
    rd = df.groupby(["dept_g", "region"]).size()
    cells, heat_table = [], []
    for yi, dn in enumerate(dept_rows):
        tot_d = int((df["dept_g"] == dn).sum())
        row = []
        for xi, rn in enumerate(r_names):
            v = int(rd.get((dn, rn), 0))
            share = round(v / tot_d * 100, 1) if tot_d else 0
            cells.append([xi, yi, share, v])
            row.append(f"{share:.1f}% ({v:,})")
        heat_table.append({"name": dn, "cells": row})
    reg_all = [round(int(v) / total * 100, 1) for v in regions["n"]]
    heat_table.append({"name": "כלל המסגרות",
                       "cells": [f"{s:.1f}% ({int(v):,})" for s, v in zip(reg_all, regions["n"])]})
    hv = [c[2] for c in cells] or [0, 100]
    ch_heat = {"x": r_names, "y": dept_rows, "cells": cells, "min": 0, "max": float(max(hv))}

    # ── regions: count + occupancy
    ch_region = {"names": r_names, "n": [int(v) for v in regions["n"]],
                 "cap": _cap_sum(df, "region", r_names)}

    # ── authorities
    at = auths.head(TOP_AUTH)
    a_cap = _cap_sum(df, "auth", list(at["name"]))
    a_reg = df.groupby("auth")["region"].agg(lambda s: _sorted_counts(s).iloc[0]["name"])
    ch_auth = {"names": list(at["name"]), "n": [int(v) for v in at["n"]], "cap": a_cap}

    # ── start year (active frameworks only)
    yr = df[df["year"].notna()].copy()
    yr["year"] = yr["year"].astype(int)
    latest_year = int(yr["year"].max()) if len(yr) else None
    latest_month = int(yr.loc[yr["year"] == latest_year, "month"].max()) if len(yr) else None
    partial = latest_month if latest_month is not None and latest_month < 12 else None
    years_all = sorted(yr["year"].unique().tolist())
    full_years = [y for y in years_all if partial is None or y != latest_year]
    start = latest_year - YEAR_WINDOW + 1 if latest_year else 0
    early = yr["year"] < start
    x_years = [f"עד {start - 1}"] if early.any() else []
    x_years += [str(y) for y in range(start, latest_year + 1)] if latest_year else []
    if partial is not None and x_years:
        x_years[-1] = f"{latest_year} (חלקית)"
    ydepts = list(depts["name"].head(TOP_YEAR_DEPTS))
    yr["dg"] = yr["dept"].where(yr["dept"].isin(ydepts), "אחר")
    yc = yr.groupby(["dg", "year"]).size()
    year_series = []
    for dn in ydepts + (["אחר"] if (yr["dg"] == "אחר").any() else []):
        sub = yc.loc[dn] if dn in yc.index.get_level_values(0) else pd.Series(dtype=int)
        data = [int(sub[sub.index < start].sum())] if early.any() else []
        data += [int(sub.get(y, 0)) for y in range(start, latest_year + 1)]
        year_series.append({"name": dn, "data": data})
    ch_years = {"x": x_years, "series": year_series}

    # ── occupancy distribution per type (boxplot, reported occupancy only)
    rep = df[cap_known]
    bx = _sorted_counts(rep["type"])
    bx = bx[bx["n"] >= MIN_BOX_N].head(BOX_TYPES)
    boxes, box_table = [], []
    for nm in bx["name"]:
        s = rep.loc[rep["type"] == nm, "cap"].sort_values().reset_index(drop=True)
        q = [float(s.quantile(p)) for p in (0.05, 0.25, 0.5, 0.75, 0.95)]
        q = [round(v, 1) for v in q]
        boxes.append(q)
        box_table.append({"name": nm, "n": n(len(s)), "p25": f"{q[1]:,.0f}", "med": f"{q[2]:,.0f}",
                          "p75": f"{q[3]:,.0f}", "p95": f"{q[4]:,.0f}"})
    ch_box = {"names": list(bx["name"]), "boxes": boxes}

    # ── operating networks
    org_code = df["org"].str.partition(" ")[0]
    has_net = (org_code != "0") & (df["org"] != "")
    nets = _sorted_counts(df.loc[has_net, "org"].map(network_label))
    nt = nets.head(TOP_NETWORKS)
    nd = df.loc[has_net].assign(net=df.loc[has_net, "org"].map(network_label))
    net_main_type = nd.groupby("net")["type"].agg(lambda s: _sorted_counts(s).iloc[0]["name"])
    ch_net = {"names": list(nt["name"]), "n": [int(v) for v in nt["n"]]}

    # ── gender-specific frameworks by department
    g = df[df["gender"].isin(["זכר", "נקבה"])]
    gd = _sorted_counts(g["dept"])
    gdn = list(gd["name"].head(8))
    gc = g.groupby(["dept", "gender"]).size()
    ch_gender = {"names": gdn,
                 "boys": [int(gc.get((d, "זכר"), 0)) for d in gdn],
                 "girls": [int(gc.get((d, "נקבה"), 0)) for d in gdn]}
    n_gender = len(g)

    # ── map: positive allow-lists, intersected with values present
    present_dept = set(df["dept_raw"])
    present_type = set(df["type_raw"])
    present_second = sorted(set(df["second_raw"]) - MAP_EXCLUDE_SECOND - {""})
    m_depts = [d for d in MAP_DEPTS if d in present_dept]
    m_types = [t for t in MAP_TYPES if t in present_type]
    mapped = df["dept_raw"].isin(m_depts) & df["type_raw"].isin(m_types) & \
        df["second_raw"].isin(present_second)
    n_mapped = int(mapped.sum())
    n_mapped_xy = int((mapped & df["has_xy"]).sum())
    show_map = bool(m_depts and m_types and present_second and n_mapped_xy > 0)
    map_cfg = {"filters": {"Head_Department": m_depts, "Type_Descr": m_types,
                           "Second_Classific": present_second},
               "cap": n_mapped + 100}

    n_ops = int(df.loc[df["op"] != "", "op"].nunique())

    rules = [
        ("dept", insight_dept(depts, total)),
        ("type", insight_type(types, total, df)),
        ("owner", insight_owner(owners, total)),
        ("auth", insight_auth(auths, total, n_auth)),
        ("region", insight_region_overrep(df, total)),
        ("recent", insight_recent(df, full_years, latest_year, partial)),
        ("capacity", insight_capacity(df)),
        ("networks", insight_networks(nets, total)),
        ("unreported", insight_unreported(df, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    local_share = int((df["owner"] == "רשות מקומית").sum()) / total if total else 0
    med_cap = rep["cap"].median() if len(rep) else 0
    unrep = int((~cap_known).sum())
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "capacity": {"value": cap_total, "display": n(cap_total), "tone": "brand"},
        "authorities": {"value": n_auth, "display": n(n_auth), "tone": "brand"},
        "types": {"value": len(types), "display": n(len(types)), "tone": "brand"},
        "local": {"value": round(local_share * 100, 1), "display": pct(local_share, 1),
                  "tone": "info"},
        "median_cap": {"value": float(med_cap), "display": f"{med_cap:,.0f}", "tone": "brand"},
        "operators": {"value": n_ops, "display": n(n_ops), "tone": "brand"},
        "unreported": {"value": unrep, "display": pct(unrep, total),
                       "tone": "warn" if unrep / total >= 0.1 else "brand"},
    }

    top_t = types.iloc[0] if len(types) else None
    top_r = regions.iloc[0] if len(regions) else None
    first_year = years_all[0] if years_all else None
    y_note = ""
    if x_years:
        y_note = (f"שנה לשנה מ-{start} (המוקדמות יותר בעמודה אחת)"
                  + (f"; שנת {latest_year} חלקית — עד {MONTHS_HE[partial - 1]}." if partial else "."))
    labels = {
        "lede": (f"{n(total)} מסגרות רווחה פעילות בפיקוח משרד הרווחה והביטחון החברתי — מעונות "
                 f"יום, מועדוניות, מרכזים קהילתיים, פנימיות, הוסטלים, מסגרות תעסוקה ומרכזי "
                 f"טיפול — ב-{n(n_auth)} רשויות רווחה וב-{n(len(regions))} מחוזות, בפיקוח "
                 f"{n(len(depts))} אגפים. לכל מסגרת מצוינים סוגה, האגף המפקח, הבעלות, הרשות, "
                 f"התפוסה בפועל ומועד תחילת הפעילות. כל המסגרות במאגר פעילות, ולכן ציר הזמן מראה "
                 f"מתי החלו לפעול המסגרות הקיימות היום, לא כמה נפתחו או נסגרו בכל שנה."),
        "total_kpi": "מסגרות רווחה פעילות",
        "capacity_kpi": "מקבלי שירות (תפוסה בפועל מדווחת)",
        "auth_kpi": "רשויות רווחה",
        "types_kpi": "סוגי מסגרות",
        "local_kpi": "מהמסגרות בבעלות רשות מקומית",
        "median_cap_kpi": "חציון התפוסה למסגרת (מבין המדווחות)",
        "operators_kpi": "גופים מפעילים",
        "unreported_kpi": "מהמסגרות ללא תפוסה מדווחת",
        "dept_note": (f"מספר המסגרות שבפיקוח כל אגף במשרד, והתפוסה בפועל המדווחת (ציר עליון). "
                      + (f"{TOP_DEPTS} האגפים הגדולים מוצגים בנפרד; השאר בעמודת \"אחר\"."
                         if "אחר" in d_names else "")),
        "dept_aria": (f"גרף עמודות אופקי: מסגרות ותפוסה לפי אגף. המוביל: {depts.iloc[0]['name']} "
                      f"עם {n(depts.iloc[0]['n'])} מסגרות." if len(depts) else "גרף עמודות לפי אגף."),
        "dept_caption": "מספר מסגרות ותפוסה בפועל לפי אגף.",
        "types_note": (f"{len(ch_types['names'])} סוגי המסגרות הנפוצים. "
                       + (f"הנפוץ ביותר: {top_t['name']}, עם {n(top_t['n'])} מסגרות. " if top_t is not None else "")
                       + (f"שאר {n(len(types) - len(ch_types['names']))} הסוגים מסוכמים בשורת \"אחר\" בטבלה."
                          if "אחר" in t_names else "")),
        "types_aria": (f"גרף עמודות אופקי: {len(ch_types['names'])} סוגי המסגרות הנפוצים. "
                       + (f"הנפוץ: {top_t['name']}." if top_t is not None else "")),
        "types_caption": "מספר מסגרות ותפוסה בפועל לפי סוג מסגרת.",
        "tree_note": ("כל מלבן הוא אגף, ובתוכו סוגי המסגרות שבפיקוחו — שטח המלבן לפי מספר "
                      "המסגרות. לחיצה על אגף מתמקדת בו."),
        "tree_aria": "מפת עץ: מסגרות לפי אגף ולפי סוג מסגרת בתוך כל אגף.",
        "owner_note": ("חלוקת הבעלות בכל אגף, באחוזים מהמסגרות שבו: רשות מקומית, גוף ציבורי, "
                       "ארגון מפעיל, בעלות פרטית או ממשלתית."),
        "owner_aria": (f"גרף עמודות מוערמות 100%: הבעלות על המסגרות לפי אגף. בכלל המסגרות "
                       f"{owners.iloc[0]['name']} מובילה." if len(owners) else "גרף בעלות לפי אגף."),
        "owner_caption": "התפלגות הבעלות על המסגרות לפי אגף, באחוזים.",
        "heat_note": (f"איזה חלק ממסגרות כל אגף נמצא בכל מחוז. השורה התחתונה בטבלה — חלוקת "
                      f"כלל המסגרות"
                      + (f" (המחוז הגדול: {top_r['name']}, {pct(top_r['n'], total)})." if top_r is not None else ".")
                      + " גוון כהה = ריכוז גבוה."),
        "heat_aria": "מפת חום: אחוז ממסגרות כל אגף בכל מחוז.",
        "heat_caption": "אחוז ומספר מסגרות כל אגף לפי מחוז.",
        "region_note": "מספר המסגרות והתפוסה בפועל המדווחת בכל מחוז של המשרד.",
        "region_aria": (f"גרף עמודות: מסגרות ותפוסה לפי מחוז. הגדול: {top_r['name']}."
                        if top_r is not None else "גרף עמודות לפי מחוז."),
        "region_caption": "מספר מסגרות ותפוסה בפועל לפי מחוז.",
        "auth_note": (f"{len(ch_auth['names'])} רשויות הרווחה עם מספר המסגרות הגדול ביותר "
                      f"(לפי הרשות שאליה משויכת המסגרת)."),
        "auth_aria": (f"גרף עמודות אופקי: {len(ch_auth['names'])} הרשויות עם הכי הרבה מסגרות. "
                      f"המובילה: {auths.iloc[0]['name']}." if len(auths) else "גרף רשויות."),
        "auth_caption": "מספר מסגרות, מחוז ותפוסה ברשויות המובילות.",
        "years_note": (f"שנת תחילת הפעילות של המסגרות הפעילות כיום, לפי {TOP_YEAR_DEPTS} האגפים "
                       f"הגדולים. {y_note} מסגרות שנסגרו אינן במאגר, ולכן שנים מוקדמות "
                       f"מיוצגות בחסר."),
        "years_aria": (f"גרף עמודות מוערמות: מסגרות פעילות לפי שנת תחילת פעילות ואגף, "
                       f"{first_year} עד {latest_year}." if first_year else "גרף לפי שנה."),
        "box_note": (f"פיזור התפוסה בפועל למסגרת ב-{len(ch_box['names'])} סוגי המסגרות הנפוצים "
                     f"(מבין מסגרות עם תפוסה מדווחת). הקופסה — הרבעון התחתון עד העליון, הקו — "
                     f"החציון, השפמים — האחוזון החמישי עד האחוזון התשעים וחמישה."),
        "box_aria": "תרשים קופסה: התפוסה בפועל למסגרת לפי סוג מסגרת.",
        "box_caption": "חציון ורבעוני התפוסה בפועל למסגרת לפי סוג.",
        "net_note": (f"רשתות וארגונים ארציים המפעילים מסגרות (ב-{pct(int(has_net.sum()), total)} "
                     f"מהמסגרות מצוין ארגון; בשאר — ללא ארגון)."),
        "net_aria": (f"גרף עמודות אופקי: הרשתות המפעילות הגדולות. הגדולה: {nt.iloc[0]['name']}."
                     if len(nt) else "גרף רשתות מפעילות."),
        "net_caption": "מספר מסגרות וסוג המסגרת העיקרי לפי רשת מפעילה.",
        "gender_note": (f"{n(n_gender)} מסגרות ({pct(n_gender, total)}) מיועדות לזכרים בלבד או לנקבות "
                        f"בלבד; בשאר המגדר אינו מצוין. לפי אגף."),
        "gender_aria": "גרף עמודות אופקי מוערם: מסגרות לזכרים בלבד ולנקבות בלבד לפי אגף.",
        "gender_caption": "מסגרות לזכרים בלבד ולנקבות בלבד לפי אגף.",
        "map_note": (f"המפה מציגה {n(n_mapped_xy)} מסגרות יום וקהילה שיש להן מיקום (מתוך "
                     f"{n(total)}): מעונות יום, מועדוניות, מרכזים קהילתיים, טיפול יום, תעסוקה "
                     f"ותחנות לטיפול במשפחה. מסגרות מגורים (פנימיות, הוסטלים, בתים חמים, דיור) "
                     f"ומסגרות לאוכלוסיות מוגנות — נשים ונערות, נוער בסיכון ובחסות, נפגעי "
                     f"התמכרויות ושירותי מבחן — מוצגות רק בסיכומים שבעמוד, ללא מיקום."),
        "map_aria": "מפה אינטראקטיבית של מסגרות היום והקהילה. גרסה נגישה: ראו את הטבלאות בעמוד ואת קובץ הנתונים.",
    }

    tables = {
        "dept": [{"name": nm, "n": n(v), "cap": n(c)} for nm, v, c in zip(d_names, d_vals, d_cap)],
        "types": [{"name": nm, "n": n(v), "cap": n(c)} for nm, v, c in zip(t_names, t_vals, t_cap)],
        "owner": [{"name": dn, "cells": [f"{s['data'][i]:.1f}%" for s in own_series]}
                  for i, dn in enumerate(dept_rows)]
                 + [{"name": "כלל המסגרות", "cells": [f"{v:.1f}%" for v in ch_owner["all"]]}],
        "heat": heat_table,
        "region": [{"name": nm, "n": n(v), "cap": n(c)}
                   for nm, v, c in zip(ch_region["names"], ch_region["n"], ch_region["cap"])],
        "auth": [{"name": nm, "region": a_reg.get(nm, ""), "n": n(v), "cap": n(c)}
                 for nm, v, c in zip(ch_auth["names"], ch_auth["n"], ch_auth["cap"])],
        "box": box_table,
        "net": [{"name": nm, "n": n(v), "type": net_main_type.get(nm, "")}
                for nm, v in zip(ch_net["names"], ch_net["n"])],
        "gender": [{"name": nm, "boys": n(b), "girls": n(gl)}
                   for nm, b, gl in zip(gdn, ch_gender["boys"], ch_gender["girls"])],
    }

    temporal = f"{first_year}/{latest_year}" if first_year else None
    agent = {
        "summary_he": (f"{n(total)} מסגרות רווחה פעילות בפיקוח משרד הרווחה ב-{n(n_auth)} רשויות — "
                       f"פילוח לפי אגף, סוג מסגרת, בעלות, מחוז ורשות, תפוסה בפועל של "
                       f"{n(cap_total)} מקבלי שירות ומפת מסגרות היום והקהילה."),
        "dataset_kind": "map",
        "suggested_tags": ["מסגרות רווחה", "מעונות יום", "שירותים חברתיים", "רשויות מקומיות",
                           "אזרחים ותיקים", "מוגבלויות", "ילדים ונוער"],
        "related_ids": ["fa11b2f3-0796-48f8-ab84-e5540ea2b014",
                        "4f361ce6-f30f-4629-b4ba-1ad19039e745",
                        "edb5f516-28b1-439e-828a-43ec3a3cc82f",
                        "ce12ebb6-fbec-4134-80b1-79d068bd96ee",
                        "e941665c-53df-48b0-8a1f-e5ae719cf695"],
        "spatial_coverage": "ישראל",
    }
    if temporal:
        agent["temporal_coverage"] = temporal

    return {
        "agent_data": agent,
        "kpis": kpis,
        "charts": {"dept": ch_dept, "types": ch_types, "tree": tree, "owner": ch_owner,
                   "heat": ch_heat, "region": ch_region, "auth": ch_auth, "years": ch_years,
                   "box": ch_box, "net": ch_net, "gender": ch_gender},
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "regions": r_names,
        "owners": own_names,
        "show": {"map": show_map, "net": len(nt) > 0, "gender": len(gdn) > 0,
                 "box": len(boxes) > 0, "years": len(x_years) > 0},
        "map": map_cfg,
    }
