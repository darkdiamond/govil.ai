"""Public-transport operator clusters (אשכולות תח"צ): weekly riders and trips.

One row per cluster: the cluster's name, the operator that runs it, weekly
riders (Rav-Kav validations in a representative week), weekly trips and the
area of the cluster's schematic polygon. Every number on the page is computed
here; each insight rule returns None when its premise doesn't hold.
"""
import pandas as pd

TOP_CLUSTERS = 15   # bars in the cluster ranking (rest -> "אחר")
TOP_OPERATORS = 10  # operators shown by name in share charts
TOP_RATIO = 10      # rows in the busiest / emptiest riders-per-trip lists
TOP_DENSITY = 15
OTHER = "אחר"
# Weekly-riders size buckets (lower bound, label). Upper bound = next lower.
SIZE_BUCKETS = [
    (0, "עד 50 אלף"),
    (50_000, "50 עד 100 אלף"),
    (100_000, "100 עד 250 אלף"),
    (250_000, "250 עד 500 אלף"),
    (500_000, "500 אלף עד מיליון"),
    (1_000_000, "מיליון ומעלה"),
]
CUM_STEPS = [1, 3, 5, 10, 20]


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _num(x, digits=1):
    return f"{x:,.{digits}f}"


def _millions(n):
    return f"{n / 1_000_000:.2f}"


def _big(n):
    """Hebrew-friendly short form: 14.1 מיליון / 605 אלף / 2,162."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} מיליון"
    if n >= 10_000:
        return f"{n / 1_000:,.0f} אלף"
    return _int(n)


def _clean(s):
    s = " ".join(str(s).replace(",", ", ").split()).replace(" ,", ",")
    return s.strip(" ,;-")


def _prepare(df):
    df = df.copy()
    df["name"] = df["CLUSTER_"].map(_clean)
    df["operator"] = df["OPERATOR"].map(_clean)
    df["cid"] = df["CLUSTERID"].map(_clean)
    df["riders"] = pd.to_numeric(df["WEEKRIDERS"].str.replace(",", ""), errors="coerce")
    df["trips"] = pd.to_numeric(df["WEEKTRIPS"].str.replace(",", ""), errors="coerce")
    df["area"] = pd.to_numeric(df["AREA_KMR"].str.replace(",", ""), errors="coerce")
    df.loc[df["name"] == "", "name"] = "ללא שם"
    df.loc[df["operator"] == "", "operator"] = "מפעיל לא ידוע"
    df = df[df["riders"].notna() & (df["riders"] >= 0)].copy()
    df["trips"] = df["trips"].fillna(0)
    df = df.sort_values(["riders", "name", "operator", "cid", "trips", "area"],
                        ascending=[False, True, True, True, False, False], kind="stable")
    df = df.reset_index(drop=True)
    # Display label: a name used by several clusters gets its operator.
    dup = df["name"].duplicated(keep=False)
    df["label"] = df["name"]
    df.loc[dup, "label"] = df.loc[dup, "name"] + " (" + df.loc[dup, "operator"] + ")"
    dup2 = df["label"].duplicated(keep=False)
    df.loc[dup2, "label"] = df.loc[dup2, "label"] + " #" + df.loc[dup2, "cid"]
    df["rpt"] = df["riders"] / df["trips"].where(df["trips"] > 0)
    df["dens"] = df["riders"] / df["area"].where(df["area"] > 0)
    return df


def _table(headers, rows):
    return {"headers": headers, "rows": rows}


def compute(frames):
    df = _prepare(frames["clusters"])
    n = len(df)
    tot_r = float(df["riders"].sum())
    tot_t = float(df["trips"].sum())
    area_ok = df[df["area"].notna() & (df["area"] > 0)]
    tot_a = float(area_ok["area"].sum())
    n_ops = int(df["operator"].nunique())
    avg_rpt = tot_r / tot_t if tot_t > 0 else None

    # ---- operators -------------------------------------------------------
    ops = (df.groupby("operator", sort=False)
             .agg(riders=("riders", "sum"), trips=("trips", "sum"),
                  area=("area", lambda s: float(s[s > 0].sum())), clusters=("name", "size"))
             .reset_index())
    ops = ops.sort_values(["riders", "trips", "operator"], ascending=[False, False, True],
                          kind="stable").reset_index(drop=True)
    ops["r_share"] = ops["riders"] / tot_r if tot_r else 0.0
    ops["t_share"] = ops["trips"] / tot_t if tot_t else 0.0

    # ---- chart: clusters ranking -----------------------------------------
    top = df.head(TOP_CLUSTERS)
    rest = df.iloc[TOP_CLUSTERS:]
    cl_names = list(top["label"])
    cl_vals = [int(v) for v in top["riders"]]
    cl_ops = list(top["operator"])
    if len(rest):
        cl_names.append(f"{OTHER} ({len(rest)} אשכולות)")
        cl_vals.append(int(rest["riders"].sum()))
        cl_ops.append("")
    chart_clusters = {"names": cl_names, "values": cl_vals, "ops": cl_ops}
    tbl_clusters = _table(["אשכול", "מפעיל", "נוסעים בשבוע", "שיעור מהנוסעים"],
                          [[cl_names[i], cl_ops[i] or "שונים", _int(v), _pct(v / tot_r if tot_r else 0)]
                           for i, v in enumerate(cl_vals)])

    # ---- chart: operator treemap (operator -> clusters) -------------------
    tree = []
    for _, o in ops.iterrows():
        kids = df[df["operator"] == o["operator"]]
        tree.append({"name": o["operator"], "value": int(o["riders"]),
                     "children": [{"name": r["name"], "value": int(r["riders"])}
                                  for _, r in kids.iterrows()]})

    # ---- chart: share of riders vs share of trips per operator ------------
    otop = ops.head(TOP_OPERATORS)
    orest = ops.iloc[TOP_OPERATORS:]
    sh_names = list(otop["operator"])
    sh_r = [round(float(v) * 100, 1) for v in otop["r_share"]]
    sh_t = [round(float(v) * 100, 1) for v in otop["t_share"]]
    sh_rows = [[o["operator"], str(int(o["clusters"])), _int(o["riders"]), _pct(o["r_share"]),
                _int(o["trips"]), _pct(o["t_share"])] for _, o in otop.iterrows()]
    if len(orest):
        lbl = f"{OTHER} ({len(orest)} מפעילים)"
        sh_names.append(lbl)
        sh_r.append(round(float(orest["r_share"].sum()) * 100, 1))
        sh_t.append(round(float(orest["t_share"].sum()) * 100, 1))
        sh_rows.append([lbl, str(int(orest["clusters"].sum())), _int(orest["riders"].sum()),
                        _pct(orest["r_share"].sum()), _int(orest["trips"].sum()),
                        _pct(orest["t_share"].sum())])
    chart_shares = {"names": sh_names, "riders": sh_r, "trips": sh_t}
    tbl_shares = _table(["מפעיל", "אשכולות", "נוסעים בשבוע", "שיעור מהנוסעים",
                         "נסיעות בשבוע", "שיעור מהנסיעות"], sh_rows)

    # ---- chart: riders per trip ------------------------------------------
    rt = df[df["rpt"].notna()].sort_values(["rpt", "label"], ascending=[False, True], kind="stable")
    n_no_trips = n - len(rt)
    med_rpt = float(rt["rpt"].median()) if len(rt) else None
    k = min(TOP_RATIO, len(rt) // 2)
    busy = rt.head(k)
    empty = rt.tail(k).iloc[::-1]
    def _rpt_chart(part):
        return {"names": list(part["label"]), "values": [round(float(v), 1) for v in part["rpt"]],
                "riders": [int(v) for v in part["riders"]], "trips": [int(v) for v in part["trips"]]}
    def _rpt_table(part):
        return _table(["אשכול", "נוסעים לנסיעה", "נוסעים בשבוע", "נסיעות בשבוע"],
                      [[r["label"], _num(r["rpt"]), _int(r["riders"]), _int(r["trips"])]
                       for _, r in part.iterrows()])

    # ---- chart: scatter area vs riders -----------------------------------
    sc = df[df["area"].notna() & (df["area"] > 0) & (df["riders"] > 0)]
    scatter = [[round(float(r["area"]), 2), int(r["riders"]), int(r["trips"]), r["label"], r["operator"]]
               for _, r in sc.iterrows()]

    # ---- chart: density ---------------------------------------------------
    de = df[df["dens"].notna()].sort_values(["dens", "label"], ascending=[False, True], kind="stable")
    dtop = de.head(TOP_DENSITY)
    chart_density = {"names": list(dtop["label"]), "values": [int(round(v)) for v in dtop["dens"]],
                     "area": [round(float(v), 1) for v in dtop["area"]]}
    tbl_density = _table(["אשכול", "נוסעים לקמ״ר", "שטח (קמ״ר)", "נוסעים בשבוע"],
                         [[r["label"], _int(r["dens"]), _num(r["area"]), _int(r["riders"])]
                          for _, r in dtop.iterrows()])

    # ---- chart: concentration curve ---------------------------------------
    cum_r = (df["riders"].cumsum() / tot_r) if tot_r else df["riders"] * 0
    area_rank = df["area"].where(df["area"] > 0, 0).fillna(0)
    cum_a = (area_rank.cumsum() / tot_a) if tot_a else area_rank * 0
    chart_cum = {"x": list(range(1, n + 1)), "riders": [round(float(v) * 100, 1) for v in cum_r],
                 "area": [round(float(v) * 100, 1) for v in cum_a], "names": list(df["label"])}
    cum_rows = []
    for s in CUM_STEPS:
        if s < n:
            cum_rows.append([f"{s} האשכולות הגדולים" if s > 1 else "האשכול הגדול ביותר",
                             _pct(cum_r.iloc[s - 1]), _pct(cum_a.iloc[s - 1])])
    cum_rows.append([f"כל {n} האשכולות", _pct(1.0 if tot_r else 0), _pct(1.0 if tot_a else 0)])
    tbl_cum = _table(["אשכולות (מהגדול לקטן)", "שיעור מצטבר מהנוסעים", "שיעור מצטבר מהשטח"], cum_rows)

    # ---- chart: size distribution -----------------------------------------
    bounds = [b for b, _ in SIZE_BUCKETS] + [float("inf")]
    sz_names, sz_counts, sz_riders = [], [], []
    for i, (lo, lbl) in enumerate(SIZE_BUCKETS):
        m = (df["riders"] >= lo) & (df["riders"] < bounds[i + 1])
        sz_names.append(lbl)
        sz_counts.append(int(m.sum()))
        sz_riders.append(int(df.loc[m, "riders"].sum()))
    chart_sizes = {"names": sz_names, "counts": sz_counts, "riders": sz_riders}
    tbl_sizes = _table(["נוסעים בשבוע", "אשכולות", "סך נוסעים", "שיעור מהנוסעים"],
                       [[sz_names[i], str(sz_counts[i]), _int(sz_riders[i]),
                         _pct(sz_riders[i] / tot_r if tot_r else 0)] for i in range(len(sz_names))])

    # ---- chart: a name shared by several clusters/operators ---------------
    name_counts = df.groupby("name").size().reset_index(name="cnt")
    name_counts = name_counts.sort_values(["cnt", "name"], ascending=[False, True], kind="stable")
    shared = None
    if len(name_counts) and int(name_counts.iloc[0]["cnt"]) >= 3:
        sname = name_counts.iloc[0]["name"]
        part = df[df["name"] == sname]
        shared = {"name": sname, "count": len(part), "ops": int(part["operator"].nunique()),
                  "riders": int(part["riders"].sum()), "trips": int(part["trips"].sum()),
                  "chart": {"names": list(part["operator"]),
                            "riders": [int(v) for v in part["riders"]],
                            "trips": [int(v) for v in part["trips"]]},
                  "table": _table(["מפעיל", "נוסעים בשבוע", "נסיעות בשבוע", "נוסעים לנסיעה"],
                                  [[r["operator"], _int(r["riders"]), _int(r["trips"]),
                                    _num(r["rpt"]) if pd.notna(r["rpt"]) else "לא ידוע"]
                                   for _, r in part.iterrows()])}

    # ---- insights -----------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def i_top():
        if n < 2 or tot_r <= 0:
            return None
        a, b = df.iloc[0], df.iloc[1]
        if a["riders"] <= b["riders"]:
            return None
        return (f"האשכול העמוס ביותר הוא {a['label']} שמפעילה {a['operator']}: {_int(a['riders'])} נוסעים "
                f"בשבוע, {_pct(a['riders'] / tot_r)} מכלל הנוסעים במאגר ופי {a['riders'] / b['riders']:.1f} "
                f"מהאשכול השני, {b['label']}.")

    def i_conc():
        k5 = 5
        if n < 2 * k5 or tot_r <= 0 or tot_a <= 0:
            return None
        rs, as_ = float(cum_r.iloc[k5 - 1]), float(cum_a.iloc[k5 - 1])
        if rs < 0.25 or as_ >= rs:
            return None
        return (f"ריכוזיות גבוהה: {k5} האשכולות הגדולים מובילים {_pct(rs)} מהנוסעים, "
                f"על {_pct(as_)} בלבד מהשטח הכולל של האשכולות.")

    def i_op():
        if len(ops) < 2 or tot_r <= 0:
            return None
        a, b = ops.iloc[0], ops.iloc[1]
        if a["riders"] <= b["riders"]:
            return None
        clusters = int(a["clusters"])
        cl_txt = "באשכול אחד" if clusters == 1 else f"ב-{clusters} אשכולות"
        return (f"{a['operator']} היא המפעילה הגדולה במאגר: {_int(a['riders'])} נוסעים בשבוע "
                f"({_pct(a['r_share'])}) {cl_txt}, לפני {b['operator']} עם {_pct(b['r_share'])}.")

    def i_gap():
        if len(ops) < 3 or tot_t <= 0:
            return None
        g = ops.assign(gap=ops["r_share"] - ops["t_share"])
        hi = g.sort_values(["gap", "operator"], ascending=[False, True], kind="stable").iloc[0]
        lo = g.sort_values(["gap", "operator"], ascending=[True, True], kind="stable").iloc[0]
        parts = []
        if hi["gap"] >= 0.02:
            parts.append(f"ל{hi['operator']} {_pct(hi['r_share'])} מהנוסעים אך רק {_pct(hi['t_share'])} מהנסיעות, "
                         f"כלומר אוטובוסים מלאים יותר מהממוצע")
        if lo["gap"] <= -0.02:
            parts.append(f"אצל {lo['operator']} ההפך: {_pct(lo['t_share'])} מהנסיעות ו-{_pct(lo['r_share'])} "
                         f"בלבד מהנוסעים")
        if not parts:
            return None
        return "פער בין נוסעים לנסיעות: " + "; ".join(parts) + "."

    def i_load():
        if len(rt) < 5 or not med_rpt:
            return None
        a = rt.iloc[0]
        z = rt.iloc[-1]
        if a["rpt"] < 1.5 * med_rpt:
            return None
        return (f"בממוצע {_num(a['rpt'])} נוסעים לכל נסיעה ב{a['label']}, פי {a['rpt'] / med_rpt:.1f} מהחציון "
                f"({_num(med_rpt)}); בקצה השני {z['label']} עם {_num(z['rpt'])} נוסעים לנסיעה.")

    def i_dens():
        if len(de) < 5:
            return None
        a, z = de.iloc[0], de.iloc[-1]
        if z["dens"] <= 0 or a["dens"] / z["dens"] < 10:
            return None
        return (f"צפיפות הנוסעים נעה בין {_int(a['dens'])} נוסעים לקמ״ר בשבוע ב{a['label']} "
                f"(שטח של {_num(a['area'])} קמ״ר) ל-{_int(z['dens'])} בלבד ב{z['label']} "
                f"({_int(z['area'])} קמ״ר).")

    def i_shared():
        if not shared or tot_r <= 0:
            return None
        return (f"האזור {shared['name']} מחולק ל-{shared['count']} אשכולות של {shared['ops']} מפעילים שונים, "
                f"ויחד הם מובילים {_int(shared['riders'])} נוסעים בשבוע ({_pct(shared['riders'] / tot_r)}).")

    def i_small():
        lim = 50_000
        m = df["riders"] < lim
        c = int(m.sum())
        if c < 3 or tot_r <= 0:
            return None
        return (f"{c} מתוך {n} האשכולות מובילים פחות מ-{_int(lim)} נוסעים בשבוע כל אחד, "
                f"ויחד רק {_pct(df.loc[m, 'riders'].sum() / tot_r)} מכלל הנוסעים.")

    add("top_cluster", i_top())
    add("concentration", i_conc())
    add("top_operator", i_op())
    add("share_gap", i_gap())
    add("load", i_load())
    add("density", i_dens())
    add("shared_name", i_shared())
    add("small", i_small())

    # ---- KPIs ---------------------------------------------------------------
    top5 = float(cum_r.iloc[min(5, n) - 1]) if n and tot_r else 0.0
    kpis = {
        "riders": {"value": int(tot_r), "display": _millions(tot_r), "tone": "brand"},
        "trips": {"value": int(tot_t), "display": _int(tot_t), "tone": "brand"},
        "rpt": {"value": round(avg_rpt, 1) if avg_rpt else 0,
                "display": _num(avg_rpt) if avg_rpt else "0", "tone": "info"},
        "clusters": {"value": n, "display": _int(n), "tone": "brand"},
        "operators": {"value": n_ops, "display": _int(n_ops), "tone": "brand"},
        "top5": {"value": round(top5, 3), "display": _pct(top5),
                 "tone": "warn" if top5 >= 0.4 else "brand"},
    }

    lead_op = ops.iloc[0]["operator"] if len(ops) else ""
    lede = (f"המאגר מחלק את רשת האוטובוסים בישראל ל-{n} אשכולות תחבורה ציבורית ומצמיד לכל אחד את המפעיל "
            f"שמפעיל אותו. בשבוע מייצג נרשמו {_big(tot_r)} נוסעים ו-{_big(tot_t)} נסיעות, בממוצע "
            f"{_num(avg_rpt) if avg_rpt else '0'} נוסעים לנסיעה, אצל {n_ops} מפעילים"
            + (f", כשהגדולה שבהם היא {lead_op}." if lead_op else "."))
    summary = (f"אשכולות התחבורה הציבורית: איזה מפעיל אוטובוסים אחראי על כל אזור. {n} אשכולות, "
               f"{_big(tot_r)} נוסעים ו-{_big(tot_t)} נסיעות בשבוע.")

    labels = {
        "lede": lede,
        "kpi_riders": "נוסעים בשבוע (מיליונים)",
        "kpi_trips": "נסיעות בשבוע",
        "kpi_rpt": "נוסעים בממוצע לנסיעה",
        "kpi_clusters": "אשכולות",
        "kpi_operators": "מפעילים",
        "kpi_top5": "שיעור הנוסעים בחמשת האשכולות הגדולים",
        "clusters_note": (f"{min(TOP_CLUSTERS, n)} האשכולות העמוסים ביותר לפי נוסעים בשבוע"
                          + (f"; {len(rest)} האשכולות הנותרים מקובצים תחת אחר." if len(rest) else ".")),
        "clusters_aria": (f"תרשים עמודות אופקי של האשכולות לפי נוסעים בשבוע; המוביל {cl_names[0]} "
                          f"עם {_int(cl_vals[0])} נוסעים." if n else "אין נתונים"),
        "tree_note": (f"כל מלבן הוא מפעיל, וגודלו לפי מספר הנוסעים בשבוע; בתוכו האשכולות שהוא מפעיל. "
                      f"{n_ops} מפעילים ב-{n} אשכולות."),
        "tree_aria": (f"מפת עץ של {n_ops} מפעילים ואשכולותיהם לפי נוסעים בשבוע; הגדול {lead_op}."),
        "shares_note": (f"שיעור כל מפעיל מסך הנוסעים לעומת שיעורו מסך הנסיעות. כשעמודת הנוסעים גבוהה "
                        f"מעמודת הנסיעות, כל נסיעה של המפעיל מובילה יותר נוסעים מהממוצע. "
                        f"{min(TOP_OPERATORS, len(ops))} המפעילים הגדולים מוצגים בשמם."),
        "shares_aria": (f"תרשים עמודות מקובצות של שיעור הנוסעים ושיעור הנסיעות לפי מפעיל; "
                        f"{lead_op} מובילה עם {_pct(ops.iloc[0]['r_share']) if len(ops) else ''} מהנוסעים."),
        "rpt_note": ("נוסעים בשבוע חלקי נסיעות בשבוע, מדד גס לעומס הממוצע בכל נסיעה. "
                     + (f"החציון בין האשכולות: {_num(med_rpt)} נוסעים לנסיעה. " if med_rpt else "")
                     + (f"{n_no_trips} אשכולות ללא נסיעות מדווחות אינם נכללים." if n_no_trips else "")),
        "busy_aria": (f"עמודות של {k} האשכולות עם הכי הרבה נוסעים לנסיעה; בראש {busy.iloc[0]['label']} "
                      f"עם {_num(busy.iloc[0]['rpt'])}." if k else "אין נתונים"),
        "empty_aria": (f"עמודות של {k} האשכולות עם הכי מעט נוסעים לנסיעה; בתחתית {empty.iloc[0]['label']} "
                       f"עם {_num(empty.iloc[0]['rpt'])}." if k else "אין נתונים"),
        "scatter_note": ("כל נקודה היא אשכול: שטח האשכול (ציר אופקי) מול מספר הנוסעים בשבוע (ציר אנכי), "
                         "שני הצירים בסקאלה לוגריתמית; גודל הנקודה לפי מספר הנסיעות. "
                         "אשכולות עירוניים קטנים ועמוסים בצד אחד, אשכולות כפריים רחבים ודלילים בצד השני."
                         + (f" {n - len(sc)} אשכולות ללא שטח או נוסעים אינם מוצגים." if n - len(sc) else "")),
        "scatter_aria": f"תרשים פיזור של {len(sc)} אשכולות: שטח מול נוסעים בשבוע.",
        "density_note": (f"{min(TOP_DENSITY, len(de))} האשכולות עם הכי הרבה נוסעים בשבוע לכל קמ״ר. "
                         "השטח הוא של גבול סכמתי, ולכן אשכול שהוא מסדרון צר (כמו קו מהיר) נראה צפוף מאוד."),
        "density_aria": (f"תרשים עמודות אופקי של צפיפות הנוסעים לקמ״ר; בראש {dtop.iloc[0]['label']} "
                         f"עם {_int(dtop.iloc[0]['dens'])}." if len(dtop) else "אין נתונים"),
        "cum_note": ("האשכולות מסודרים מהגדול לקטן לפי נוסעים. הקו הכחול מראה את השיעור המצטבר מכלל הנוסעים, "
                     "והקו האפור את השיעור המצטבר מהשטח: פער גדול בין הקווים פירושו שמעט שטח עירוני נושא "
                     "את רוב התנועה."),
        "cum_aria": (f"עקומה מצטברת של נוסעים ושטח לפי דירוג האשכולות; חמשת הגדולים מובילים {_pct(top5)} "
                     f"מהנוסעים."),
        "sizes_note": "כמה אשכולות יש בכל טווח גודל (נוסעים בשבוע), וכמה נוסעים הם מובילים יחד.",
        "sizes_aria": (f"תרשים עמודות של מספר האשכולות לפי טווח נוסעים בשבוע; הטווח הנפוץ "
                       f"{sz_names[max(range(len(sz_counts)), key=lambda i: (sz_counts[i], -i))]}."),
    }
    if shared:
        labels["shared_title"] = f"{shared['name']}: אשכול אחד, כמה מפעילים"
        labels["shared_note"] = (f"השם {shared['name']} מופיע ב-{shared['count']} אשכולות נפרדים, כל אחד בהפעלת "
                                 f"מפעיל אחר. יחד: {_int(shared['riders'])} נוסעים ו-{_int(shared['trips'])} "
                                 f"נסיעות בשבוע.")
        labels["shared_aria"] = (f"תרשים עמודות של נוסעים בשבוע לפי מפעיל באשכולות {shared['name']}; "
                                 f"הגדול {shared['chart']['names'][0]}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "clusters": chart_clusters,
            "tree": tree,
            "shares": chart_shares,
            "busy": _rpt_chart(busy),
            "empty": _rpt_chart(empty),
            "scatter": scatter,
            "density": chart_density,
            "cum": chart_cum,
            "sizes": chart_sizes,
        },
        "tables": {
            "clusters": tbl_clusters,
            "shares": tbl_shares,
            "busy": _rpt_table(busy),
            "empty": _rpt_table(empty),
            "density": tbl_density,
            "cum": tbl_cum,
            "sizes": tbl_sizes,
        },
        "shared": shared,
        "has_ratio": k > 0,
        "insights": insights,
        "labels": labels,
    }
