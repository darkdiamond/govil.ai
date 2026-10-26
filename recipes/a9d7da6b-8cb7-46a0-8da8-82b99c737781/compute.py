"""רישיונות עסק והיתרים למפעלים — Ministry of Environmental Protection.

One row per approval/permit. Four kinds (SugHeter): the ministry's answer to
a business-licensing authority ("אישור המשרד לרישיון עסק", ~96% of rows,
sub-typed in Heter_Name as a licence, a temporary permit or "(חסר)"), and
three permits the ministry issues itself — X-ray, radioactive radiation and
toxins.

Dates: most business-licence rows have none; the permits almost always do.
The file mixes date orders — permit dates are DD/MM/YYYY while business-
licence end dates are MM/DD/YYYY — so the order is detected per (column,
kind) from the values themselves (a first field above 12 means DD/MM, a
second field above 12 means MM/DD), with the other order as fallback.

No "valid today" claims: compute has no clock, start dates run ahead of the
publication date, and the dataset itself warns the licence data does not
prove a valid licence. Rows of the ministry's test district are excluded and
disclosed. Factories (companies, institutions, businesses) are named.
"""
import math

import pandas as pd

BL = "אישור המשרד לרישיון עסק"
TEST_MARK = "לבדיקות"
MISSING_SUB = "(חסר)"
UNSET = "לא צוין"
TOP_SETTLE = 15
TOP_ENV_SETTLE = 12
TOP_FACTORIES = 15
TOP_KINDS = 14
RECENT_MONTHS = 24
NEAR_TIE = 0.02

# Business kind from words in the factory name — first match wins; names
# with none of these stay unclassified (disclosed on the page).
KINDS = [
    ("תחנות דלק ותדלוק", ["תחנת דלק", "תחנות דלק", "תדלוק", "דלק"]),
    ("מגרסות", ["מגרסה", "מגרסת"]),
    ("רפתות", ["רפת"]),
    ("לולים", ["לול"]),
    ("מתקני טיהור שפכים", ["מט\"ש", "טיהור", "שפכים"]),
    ("מחזור ופסולת", ["מחזור", "מיחזור", "תחנת מעבר", "פסולת"]),
    ("מוסכים", ["מוסך"]),
    ("מתכת ומסגריות", ["מתכת", "מתכות", "מסגרי"]),
    ("בטון ואספלט", ["בטון", "אספלט"]),
    ("מחצבות", ["מחצבה", "מחצבת"]),
    ("נגריות", ["נגרי"]),
    ("שיש ואבן", ["שיש"]),
    ("בתי דפוס", ["דפוס"]),
    ("מכבסות", ["מכבסה", "מכבסת", "ניקוי יבש"]),
    ("מחלבות", ["מחלבה", "מחלבת"]),
    ("בתי קירור", ["בית קירור", "בתי קירור"]),
    ("דירים", ["דיר "]),
    ("משחטות", ["משחטה", "משחטת"]),
    ("בתי בד", ["בית בד", "בית הבד"]),
]

# Duration bins in days (upper bound inclusive).
DUR_BINS = [
    (182, "עד חצי שנה"),
    (349, "חצי שנה עד שנה"),
    (380, "כשנה"),
    (1100, "שנה עד שלוש שנים"),
    (1830, "שלוש עד חמש שנים"),
    (3660, "חמש עד עשר שנים"),
    (math.inf, "מעל עשר שנים"),
]
ONE_YEAR = (350, 380)
# Palette index per licence kind (business licence first, then permits by
# size) so a kind keeps its colour on every chart.
KIND_COLORS = [0, 1, 2, 6, 5, 3, 7, 4, 8, 9]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _parse_dates(s):
    s = s.str.strip()
    parts = s.str.extract(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
    a = pd.to_numeric(parts[0], errors="coerce")
    b = pd.to_numeric(parts[1], errors="coerce")
    mmdd = int((b > 12).sum()) > int((a > 12).sum())
    f1, f2 = ("%m/%d/%Y", "%d/%m/%Y") if mmdd else ("%d/%m/%Y", "%m/%d/%Y")
    d1 = pd.to_datetime(s, format=f1, errors="coerce")
    d2 = pd.to_datetime(s, format=f2, errors="coerce")
    return d1.fillna(d2)


def _kind(name):
    for label, words in KINDS:
        if any(w in name for w in words):
            return label
    return None


def _prepare(df):
    out = df.copy()
    for c in ["Yishuv_Name", "Machoz_Name", "MifalName", "SugHeter", "Heter_Name"]:
        out[c] = out[c].str.strip().str.replace(r"\s+", " ", regex=True)
    test = out["Machoz_Name"].str.contains(TEST_MARK, regex=False) | \
        out["Yishuv_Name"].str.contains(TEST_MARK, regex=False)
    n_test = int(test.sum())
    out = out[~test].copy()
    out["district"] = out["Machoz_Name"].replace("", UNSET)
    out["settle"] = out["Yishuv_Name"].replace("", UNSET)
    out["factory"] = out["MifalName"].replace("", UNSET)
    out["kind_type"] = out["SugHeter"].replace("", UNSET)
    out["is_bl"] = out["kind_type"] == BL
    # Sub-type: the licence sub-type for business-licence rows, the permit kind otherwise.
    out["sub"] = out["Heter_Name"].where(out["is_bl"], out["kind_type"])
    out["sub"] = out["sub"].replace({"": UNSET, MISSING_SUB: "ללא תת-סוג"})
    out["start"] = pd.NaT
    out["end"] = pd.NaT
    for k, idx in out.groupby("kind_type").groups.items():
        out.loc[idx, "start"] = _parse_dates(out.loc[idx, "Start_Date"])
        out.loc[idx, "end"] = _parse_dates(out.loc[idx, "End_Date"])
    out["start"] = pd.to_datetime(out["start"])
    out["end"] = pd.to_datetime(out["end"])
    out["dur"] = (out["end"] - out["start"]).dt.days
    out["kind"] = [None if not bl else _kind(n) for n, bl in zip(out["factory"], out["is_bl"])]
    return out.reset_index(drop=True), n_test


def _env_order(df):
    return list(_ranked(df.loc[~df["is_bl"], "kind_type"]).index)


def _sub_order(df):
    """Business-licence sub-types first (by size), then the permit kinds."""
    bl = list(_ranked(df.loc[df["is_bl"], "sub"]).index)
    return bl + [k for k in _env_order(df) if k not in bl]


def _dur_bin(d):
    for hi, label in DUR_BINS:
        if d <= hi:
            return label
    return DUR_BINS[-1][1]


# ---------------------------------------------------------------- insights

def insight_dominance(df):
    n_bl = int(df["is_bl"].sum())
    share = n_bl / len(df)
    if share < 0.5:
        return None
    env = _ranked(df.loc[~df["is_bl"], "kind_type"])
    if env.empty:
        return (f"כל {_int(n_bl)} הרשומות במאגר הן אישורי המשרד לרישיון עסק.")
    parts = ", ".join(f"{_int(v)} היתרי {k}" for k, v in env.items())
    return (f"{_pct(share)} מהרשומות ({_int(n_bl)}) הן אישורי המשרד לבקשות רישיון עסק; "
            f"ההיתרים שהמשרד מנפיק בעצמו מעטים בהרבה — {parts}.")


def insight_districts(df):
    d = _ranked(df.loc[df["district"] != UNSET, "district"])
    if len(d) < 3:
        return None
    total = len(df)
    if (d.iloc[0] - d.iloc[2]) / total < NEAR_TIE * 2:
        return (f"שלושה מחוזות מובילים כמעט בשוויון — {d.index[0]} ({_int(d.iloc[0])} רשומות), "
                f"{d.index[1]} ({_int(d.iloc[1])}) ו{d.index[2]} ({_int(d.iloc[2])}) — "
                f"ויחד הם {_pct(d.iloc[:3].sum() / total)} מהמאגר.")
    if (d.iloc[0] - d.iloc[1]) / total < NEAR_TIE:
        return (f"מחוזות {d.index[0]} ו{d.index[1]} מובילים כמעט בשוויון — "
                f"{_int(d.iloc[0])} ו-{_int(d.iloc[1])} רשומות.")
    return f"מחוז {d.index[0]} מוביל עם {_int(d.iloc[0])} רשומות ({_pct(d.iloc[0] / total)})."


def _sub_share_by_district(df, label, min_rows=500):
    bl = df[df["is_bl"] & (df["district"] != UNSET)]
    g = bl.groupby("district")["sub"].agg(lambda s: (s == label).mean())
    n = bl.groupby("district").size()
    g = g[n >= min_rows]
    return g.sort_index().sort_values(ascending=False, kind="stable")


def insight_temporary(df):
    bl = df[df["is_bl"]]
    label = "היתר זמני"
    share = (bl["sub"] == label).mean() if len(bl) else 0
    if share < 0.05:
        return None
    by = _sub_share_by_district(df, label)
    tail = ""
    if len(by) >= 2 and by.iloc[0] - by.iloc[-1] >= 0.05:
        tail = (f" השיעור הגבוה ביותר במחוז {by.index[0]} ({_pct(by.iloc[0])}) "
                f"והנמוך ביותר במחוז {by.index[-1]} ({_pct(by.iloc[-1])}).")
    return (f"{_int((bl['sub'] == label).sum())} מאישורי רישיון העסק ({_pct(share)}) "
            f"הם היתרים זמניים.{tail}")


def insight_missing(df):
    bl = df[df["is_bl"]]
    label = "ללא תת-סוג"
    share = (bl["sub"] == label).mean() if len(bl) else 0
    if share < 0.05:
        return None
    by = _sub_share_by_district(df, label)
    tail = f" הכי הרבה במחוז {by.index[0]} ({_pct(by.iloc[0])} מאישורי המחוז)." if len(by) else ""
    return (f"ב-{_pct(share)} מאישורי רישיון העסק ({_int((bl['sub'] == label).sum())}) "
            f"לא צוין תת-הסוג — רישיון או היתר זמני.{tail}")


def insight_duration(df):
    env = df[~df["is_bl"] & (df["dur"] > 0)]
    parts = []
    for k in _env_order(df):
        g = env[env["kind_type"] == k]
        if len(g) < 20:
            continue
        one = g["dur"].between(*ONE_YEAR).mean()
        if one >= 0.4:
            parts.append(f"{_pct(one)} מהיתרי {k} ניתנים לשנה")
        else:
            years = float(g["dur"].median()) / 365.25
            parts.append(f"היתר {k} טיפוסי ניתן לכ-{years:.0f} שנים (חציון)"
                         if years >= 1.5 else f"משך חציוני של היתר {k} הוא {g['dur'].median():.0f} ימים")
    if not parts:
        return None
    return "משך ההיתרים שונה לפי סוג: " + "; ".join(parts) + "."


def insight_recent(df):
    env = df[~df["is_bl"] & df["start"].notna()]
    if len(env) < 50:
        return None
    years = env["start"].dt.year
    # The very latest year can hold a handful of early renewals; use the
    # latest year that carries at least 5% of the dated permits.
    counts = years.value_counts().sort_index()
    ok = counts[counts >= 0.05 * len(env)]
    if ok.empty:
        return None
    y = int(ok.index.max())
    n = int(counts[y])
    share = n / len(env)
    if share < 0.3:
        return None
    return (f"{_pct(share)} מהיתרי הקרינה, הרנטגן והרעלים עם תאריך תחילה ({_int(n)} מתוך "
            f"{_int(len(env))}) מתחילים ב-{y}, ושאר ההיתרים פזורים על פני "
            f"{_int(years.nunique() - 1)} שנים נוספות.")


def insight_top_factory(df):
    f = _ranked(df.loc[df["factory"] != UNSET, "factory"])
    if f.empty or f.iloc[0] < 10:
        return None
    name, n = f.index[0], int(f.iloc[0])
    places = int(df.loc[df["factory"] == name, "settle"].nunique())
    where = f" ב-{_int(places)} יישובים שונים" if places > 1 else ""
    return (f"למפעל {name} יש הכי הרבה רשומות במאגר — {_int(n)}{where}.")


def insight_kind(df):
    bl = df[df["is_bl"]]
    k = _ranked(bl["kind"].dropna())
    if k.empty:
        return None
    covered = bl["kind"].notna().mean()
    return (f"לפי מילים בשם המפעל, הקבוצה הגדולה בין אישורי רישיון העסק היא {k.index[0]} — "
            f"{_int(k.iloc[0])} אישורים ({_pct(k.iloc[0] / len(bl), 1)}); "
            f"שם המפעל מאפשר לסווג {_pct(covered)} מהאישורים.")


def insight_multi(df):
    named = df[df["factory"] != UNSET]
    combos = named.groupby("factory")["kind_type"].agg(
        lambda s: tuple(sorted(set(s), key=lambda k: (k != BL, k))))
    multi = combos[combos.map(len) > 1]
    n = int(multi.size)
    if n < 10:
        return None
    top = _ranked(multi.map(lambda t: " + ".join(t)))
    parts = [("אישור לרישיון עסק" if k == BL else f"היתר {k}") for k in top.index[0].split(" + ")]
    return (f"{_int(n)} מפעלים מופיעים ביותר מסוג רישוי אחד; השילוב הנפוץ ביותר — "
            f"{' וגם '.join(parts)} — אצל {_int(top.iloc[0])} מפעלים.")


def insight_dated(df):
    bl = df[df["is_bl"]]
    if len(bl) < 100:
        return None
    share = bl["start"].notna().mean()
    env = df[~df["is_bl"]]
    env_share = env["start"].notna().mean() if len(env) else 0
    if share >= 0.2:
        return None
    return (f"רק ל-{_pct(share, 1)} מאישורי רישיון העסק יש תאריך תחילה, לעומת "
            f"{_pct(env_share, 1)} מההיתרים שהמשרד מנפיק בעצמו — ולכן הניתוח לאורך זמן מבוסס "
            f"בעיקר על ההיתרים.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df, n_test = _prepare(frames["permits"])
    total = len(df)
    bl = df[df["is_bl"]]
    env = df[~df["is_bl"]]
    n_bl, n_env = len(bl), len(env)
    env_kinds = _env_order(df)
    subs = _sub_order(df)
    ci = {k: KIND_COLORS[i % len(KIND_COLORS)] for i, k in enumerate([BL] + env_kinds)}

    # 1. composition by sub-type
    sub_counts = df["sub"].value_counts()
    types_chart = {"names": subs, "values": [int(sub_counts.get(s, 0)) for s in subs]}
    t_types = [{"name": s, "group": "אישור לרישיון עסק" if s in set(bl["sub"]) else "היתר",
                "count": _int(sub_counts.get(s, 0)),
                "share": _pct(sub_counts.get(s, 0) / total, 1)} for s in subs]

    # 2. districts × business-licence sub-type
    districts = list(_ranked(df["district"]).index)
    bl_subs = [s for s in subs if s in set(bl["sub"])]
    by_ds = bl.groupby(["district", "sub"]).size()
    dist_chart = {"names": districts,
                  "series": [{"name": s, "data": [int(by_ds.get((d, s), 0)) for d in districts]}
                             for s in bl_subs]}
    t_dist = {"cols": bl_subs,
              "rows": [{"name": d, "vals": [_int(by_ds.get((d, s), 0)) for s in bl_subs]}
                       for d in districts]}

    # 3. districts × environmental permit kind
    env_districts = list(_ranked(env["district"]).index)
    by_de = env.groupby(["district", "kind_type"]).size()
    env_dist_chart = {"names": env_districts,
                      "series": [{"name": k, "ci": ci[k], "data": [int(by_de.get((d, k), 0)) for d in env_districts]}
                                 for k in env_kinds]}
    t_env_dist = {"cols": env_kinds,
                  "rows": [{"name": d, "vals": [_int(by_de.get((d, k), 0)) for k in env_kinds]}
                           for d in env_districts]}

    # 4. top settlements: business licences vs permits
    settles = _ranked(df.loc[df["settle"] != UNSET, "settle"])
    top_s = list(settles.index[:TOP_SETTLE])
    by_sb = df.groupby(["settle", "is_bl"]).size()
    settle_chart = {"names": top_s,
                    "bl": [int(by_sb.get((s, True), 0)) for s in top_s],
                    "env": [int(by_sb.get((s, False), 0)) for s in top_s]}
    t_settle = [{"name": s, "bl": _int(by_sb.get((s, True), 0)),
                 "env": _int(by_sb.get((s, False), 0)), "total": _int(settles[s])} for s in top_s]

    # 5. top settlements for environmental permits
    env_settles = _ranked(env.loc[env["settle"] != UNSET, "settle"])
    top_es = list(env_settles.index[:TOP_ENV_SETTLE])
    by_se = env.groupby(["settle", "kind_type"]).size()
    env_settle_chart = {"names": top_es,
                        "series": [{"name": k, "ci": ci[k], "data": [int(by_se.get((s, k), 0)) for s in top_es]}
                                   for k in env_kinds]}
    t_env_settle = {"cols": env_kinds,
                    "rows": [{"name": s, "vals": [_int(by_se.get((s, k), 0)) for k in env_kinds]}
                             for s in top_es]}
    env_top_share = env_settles.iloc[:3].sum() / n_env if n_env else 0

    # 6. business kinds by name keywords
    kinds = _ranked(bl["kind"].dropna())
    kinds_top = kinds.head(TOP_KINDS)
    kinds_chart = {"names": list(kinds_top.index), "values": [int(v) for v in kinds_top]}
    t_kinds = [{"name": k, "count": _int(v), "share": _pct(v / n_bl, 1) if n_bl else "0%"}
               for k, v in kinds_top.items()]
    covered = bl["kind"].notna().mean() if n_bl else 0

    # 7. top factories
    fac = _ranked(df.loc[df["factory"] != UNSET, "factory"])
    top_f = fac.head(TOP_FACTORIES)
    fac_places = df[df["factory"].isin(top_f.index)].groupby("factory")["settle"].nunique()
    fac_chart = {"names": list(top_f.index), "values": [int(v) for v in top_f]}
    t_fac = [{"name": f, "count": _int(v), "places": _int(fac_places.get(f, 0))}
             for f, v in top_f.items()]

    # 8. records per factory
    rep_bins = [(1, "רשומה אחת"), (2, "שתיים"), (3, "שלוש"), (5, "ארבע עד חמש"),
                (10, "שש עד עשר"), (math.inf, "יותר מעשר")]
    lo = 0
    rep_names, rep_vals = [], []
    for hi, label in rep_bins:
        rep_names.append(label)
        rep_vals.append(int(((fac > lo) & (fac <= hi)).sum()))
        lo = hi
    rep_chart = {"names": rep_names, "values": rep_vals}
    n_fac = int(fac.size)
    t_rep = [{"name": n, "count": _int(v), "share": _pct(v / n_fac, 1) if n_fac else "0%"}
             for n, v in zip(rep_names, rep_vals)]
    repeat_share = (fac > 1).mean() if n_fac else 0

    # 9. start year × kind
    dated = df[df["start"].notna()]
    years_chart = None
    if len(dated):
        y0, y1 = int(dated["start"].dt.year.min()), int(dated["start"].dt.year.max())
        yrs = list(range(y0, y1 + 1))
        by_yk = dated.groupby([dated["start"].dt.year, "kind_type"]).size()
        kinds_order = ([BL] if BL in set(dated["kind_type"]) else []) + \
            [k for k in env_kinds if k in set(dated["kind_type"])]
        years_chart = {"years": [str(y) for y in yrs],
                       "series": [{"name": "אישור לרישיון עסק" if k == BL else k, "ci": ci[k],
                                   "data": [int(by_yk.get((y, k), 0)) for y in yrs]}
                                  for k in kinds_order],
                       "zoom_start": max(0, round((1 - min(1, 25 / len(yrs))) * 100))}

    # 10. environmental permits by start month, last RECENT_MONTHS months of data
    env_dated = env[env["start"].notna()]
    months_chart = None
    if len(env_dated):
        per = env_dated["start"].dt.to_period("M")
        last = per.max()
        rng = pd.period_range(last - (RECENT_MONTHS - 1), last, freq="M")
        by_mk = env_dated.groupby([per, "kind_type"]).size()
        months_chart = {"months": [f"{p.month:02d}/{p.year}" for p in rng],
                        "series": [{"name": k, "ci": ci[k], "data": [int(by_mk.get((p, k), 0)) for p in rng]}
                                   for k in env_kinds]}
        months_first, months_last = rng[0], rng[-1]
        n_in_window = int(sum(sum(s["data"]) for s in months_chart["series"]))

    # 11. duration bins × kind
    durd = df[df["dur"].notna()]
    nonpos = int((durd["dur"] <= 0).sum())
    durd = durd[durd["dur"] > 0].copy()
    durd["bin"] = [_dur_bin(d) for d in durd["dur"]]
    bins = [b for _, b in DUR_BINS]
    dur_kinds = [k for k in env_kinds if k in set(durd["kind_type"])] + \
        ([BL] if BL in set(durd["kind_type"]) else [])
    by_bk = durd.groupby(["bin", "kind_type"]).size()
    dur_chart = {"bins": bins,
                 "series": [{"name": "אישור לרישיון עסק" if k == BL else k, "ci": ci[k],
                             "data": [int(by_bk.get((b, k), 0)) for b in bins]} for k in dur_kinds]}
    t_dur = {"cols": [s["name"] for s in dur_chart["series"]],
             "rows": [{"name": b, "vals": [_int(by_bk.get((b, k), 0)) for k in dur_kinds]}
                      for b in bins]}
    open_ended = int((bl["end"].dt.year >= 2099).sum()) if n_bl else 0

    # ------------------------------------------------------------ insights
    rules = [
        ("dominance", insight_dominance(df)),
        ("districts", insight_districts(df)),
        ("temporary", insight_temporary(df)),
        ("missing", insight_missing(df)),
        ("duration", insight_duration(df)),
        ("recent", insight_recent(df)),
        ("top_factory", insight_top_factory(df)),
        ("kind", insight_kind(df)),
        ("multi", insight_multi(df)),
        ("dated", insight_dated(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ------------------------------------------------------------ KPIs
    n_settle = int(df.loc[df["settle"] != UNSET, "settle"].nunique())
    temp_share = (bl["sub"] == "היתר זמני").mean() if n_bl else 0
    miss_share = (bl["sub"] == "ללא תת-סוג").mean() if n_bl else 0
    bl_dated = bl["start"].notna().mean() if n_bl else 0
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand",
                  "label": "רשומות במאגר"},
        "factories": {"value": n_fac, "display": _int(n_fac), "tone": "brand",
                      "label": "מפעלים (שמות ייחודיים)"},
        "settlements": {"value": n_settle, "display": _int(n_settle), "tone": "brand",
                        "label": "יישובים"},
        "env": {"value": n_env, "display": _int(n_env), "tone": "info",
                "label": "היתרי קרינה, רנטגן ורעלים"},
        "temp": {"value": temp_share, "display": _pct(temp_share, 1),
                 "tone": "info" if temp_share >= 0.05 else "brand",
                 "label": "מאישורי רישיון העסק הם היתרים זמניים"},
        "missing": {"value": miss_share, "display": _pct(miss_share, 1),
                    "tone": "warn" if miss_share >= 0.1 else "ok" if miss_share < 0.02 else "brand",
                    "label": "מאישורי רישיון העסק בלי תת-סוג"},
        "dated": {"value": bl_dated, "display": _pct(bl_dated, 1),
                  "tone": "warn" if bl_dated < 0.5 else "ok",
                  "label": "מאישורי רישיון העסק עם תאריך תחילה"},
        "repeat": {"value": repeat_share, "display": _pct(repeat_share), "tone": "brand",
                   "label": "מהמפעלים מופיעים ביותר מרשומה אחת"},
    }

    # ------------------------------------------------------------ labels
    test_note = f" לא נכללו {_int(n_test)} רשומות של מחוז הבדיקות." if n_test else ""
    span = ""
    if len(env_dated):
        span = (f" תאריכי התחילה של ההיתרים משתרעים בין {int(env_dated['start'].dt.year.min())} "
                f"ל-{int(env_dated['start'].dt.year.max())}.")
    labels = {
        "lede": (f"{_int(total)} רשומות של המשרד להגנת הסביבה על {_int(n_fac)} מפעלים "
                 f"ב-{_int(n_settle)} יישובים: {_int(n_bl)} אישורים שנתן המשרד לבקשות רישיון עסק, "
                 f"ו-{_int(n_env)} היתרי קרינה רדיואקטיבית, רנטגן ורעלים שהמשרד מנפיק בעצמו.{span}"
                 f"{test_note}"),
        "types_aria": f"תרשים עמודות אופקי: מספר הרשומות לפי סוג ותת-סוג, {len(subs)} קטגוריות.",
        "types_caption": "מספר הרשומות ושיעורן לפי סוג ותת-סוג.",
        "dist_aria": (f"תרשים עמודות מוערמות: אישורי רישיון עסק בכל אחד מ-{len(districts)} "
                      f"המחוזות לפי תת-סוג."),
        "dist_caption": "אישורי רישיון עסק לפי מחוז ותת-סוג.",
        "env_dist_aria": (f"תרשים עמודות מוערמות: היתרי קרינה, רנטגן ורעלים לפי מחוז, "
                          f"{len(env_districts)} מחוזות."),
        "env_dist_caption": "היתרי קרינה, רנטגן ורעלים לפי מחוז וסוג.",
        "settle_aria": (f"תרשים עמודות אופקי מוערם: {len(top_s)} היישובים עם הכי הרבה רשומות, "
                        f"אישורי רישיון עסק והיתרים."),
        "settle_caption": f"{len(top_s)} היישובים עם הכי הרבה רשומות.",
        "env_settle_aria": (f"תרשים עמודות אופקי מוערם: {len(top_es)} היישובים עם הכי הרבה "
                            f"היתרי קרינה, רנטגן ורעלים."),
        "env_settle_caption": f"{len(top_es)} היישובים עם הכי הרבה היתרים, לפי סוג.",
        "env_settle_note": (f"שלושת היישובים המובילים מחזיקים {_pct(env_top_share)} מההיתרים."
                            if n_env else ""),
        "kinds_note": (f"סיווג לפי מילים בשם המפעל (למשל ״תחנת דלק״, ״רפת״, ״מגרסה״). "
                       f"השם מאפשר לסווג {_pct(covered)} מאישורי רישיון העסק; השאר — לרוב חברות "
                       f"ששמן אינו מעיד על הפעילות — אינם מוצגים."),
        "kinds_aria": f"תרשים עמודות אופקי: אישורי רישיון עסק לפי סוג העסק, {len(kinds_top)} סוגים.",
        "kinds_caption": f"{len(kinds_top)} סוגי העסקים הנפוצים לפי שם המפעל.",
        "fac_aria": f"תרשים עמודות אופקי: {len(top_f)} המפעלים עם הכי הרבה רשומות.",
        "fac_caption": f"{len(top_f)} המפעלים עם הכי הרבה רשומות ומספר היישובים שבהם הם רשומים.",
        "rep_aria": "תרשים עמודות: מספר המפעלים לפי מספר הרשומות של כל מפעל.",
        "rep_caption": "התפלגות המפעלים לפי מספר הרשומות.",
        "rep_note": (f"{_pct(repeat_share)} מ-{_int(n_fac)} המפעלים מופיעים במאגר יותר מפעם אחת, "
                     f"ו-{_int(rep_vals[-1])} מפעלים מופיעים יותר מעשר פעמים."),
        "years_note": (f"רשומות עם תאריך תחילה בלבד ({_int(len(dated))} מתוך {_int(total)}). "
                       f"גררו את פס הזמן להתמקדות בתקופה." if years_chart else ""),
        "years_aria": "תרשים עמודות מוערמות: רשומות לפי שנת התחילה וסוג.",
        "months_note": (f"היתרי קרינה, רנטגן ורעלים לפי חודש התחילה, {RECENT_MONTHS} החודשים "
                        f"האחרונים במאגר (\u2066{months_first.month:02d}/{months_first.year}–"
                        f"{months_last.month:02d}/{months_last.year}\u2069, {_int(n_in_window)} היתרים)."
                        if months_chart else ""),
        "months_aria": f"תרשים עמודות מוערמות: היתרים לפי חודש תחילה, {RECENT_MONTHS} חודשים.",
        "dur_note": (f"משך ההיתר מתאריך התחילה עד תאריך הסיום, ב-{_int(len(durd))} רשומות עם "
                     f"שני התאריכים."
                     + (f" לא נכללו {_int(nonpos)} רשומות שבהן תאריך הסיום קודם לתחילה או זהה לו."
                        if nonpos else "")
                     + (f" {_int(open_ended)} אישורי רישיון עסק רשומים עד {2099} ואילך, כלומר ללא "
                        f"הגבלת זמן." if open_ended else "")),
        "dur_aria": "תרשים עמודות מקובצות: משך ההיתרים לפי סוג.",
        "dur_caption": "מספר הרשומות בכל טווח משך, לפי סוג.",
    }

    temporal = None
    if len(dated):
        temporal = f"{int(dated['start'].dt.year.min())}/{int(dated['start'].dt.year.max())}"

    agent_data = {
        "summary_he": (f"{_int(total)} אישורים והיתרים של המשרד להגנת הסביבה ל-{_int(n_fac)} מפעלים: "
                       f"אישורים לרישיון עסק לפי מחוז, יישוב וסוג עסק, והיתרי קרינה, רנטגן ורעלים "
                       f"לפי סוג, מיקום, מועד ומשך."),
        "dataset_kind": "registry",
        "suggested_tags": ["רישוי עסקים", "מפעלים", "הגנת הסביבה", "קרינה", "רנטגן", "רעלים"],
        "related_ids": [
            "04931a88-336c-4d95-8a13-9dc631c3e2d1",
            "5fc5c912-4fa5-4474-93c1-326e505e22cf",
            "4e9111d8-e842-40ec-b587-629e684e85ac",
            "422ff747-a1ee-4e8d-b515-43417f0d80d8",
        ],
        "spatial_coverage": "ישראל",
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "types": types_chart,
            "dist": dist_chart,
            "env_dist": env_dist_chart,
            "settle": settle_chart,
            "env_settle": env_settle_chart,
            "kinds": kinds_chart,
            "fac": fac_chart,
            "rep": rep_chart,
            "years": years_chart,
            "months": months_chart,
            "dur": dur_chart,
        },
        "tables": {
            "types": t_types, "dist": t_dist, "env_dist": t_env_dist, "settle": t_settle,
            "env_settle": t_env_settle, "kinds": t_kinds, "fac": t_fac, "rep": t_rep,
            "dur": t_dur,
        },
        "insights": insights,
        "labels": labels,
    }
