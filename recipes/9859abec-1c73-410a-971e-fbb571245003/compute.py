"""כינויי מקור — Israel's register of appellations of origin (Patent Office).

One row = one application for Israeli protection of an appellation of origin
(a geographic name that designates a product: CHIANTI CLASSICO, ROQUEFORT,
יינות הרי יהודה). Almost all rows are international registrations received
under the Lisbon system ("בינלאומי"); a handful are Israeli national filings
("לאומי"). Columns: mark number, current status, national/international,
Hebrew and English description, application date, registration date and the
Nice goods classes (";"-separated when an application covers several).

The data carries no country column and no people — only product/place names.
Units on the page: "בקשות" = rows. Class charts count an application once in
every class it lists (disclosed).
"""
import re

import pandas as pd

TOP_CLASSES = 12            # classes in the class bar chart (+ "שאר הסוגים")
HEAT_CLASSES = 8            # classes in the class x decade heatmap (+ "אחר")
TOP_WAVES = 10              # busiest application dates
LATEST_N = 10               # newest applications table
NATIONAL_MAX = 20           # national applications table cap
ERA_SPLIT = 2000            # "early" vs "modern" era for closure / lag rules
RECENT_YEARS = 10           # window for the recent-filings rule
MIN_ERA_ROWS = 30           # min applications per era for a rate comparison
LRI, PDI = "⁦", "⁩"

REG, CLOSED = "רשום", "סגור"
NATIONAL, INTL = "לאומי", "בינלאומי"
STATUS_ORDER = [REG, "בחינה שנייה", CLOSED]

# Hebrew short names of the Nice goods classes (as worded in the Patent
# Office's own Nice term list); unknown classes fall back to "סוג N".
NICE_HE = {
    1: "חומרים כימיים", 2: "צבעים", 3: "תכשירי ניקוי וקוסמטיקה",
    4: "שמנים תעשייתיים", 5: "תכשירי רוקחות", 6: "מתכות פשוטות", 7: "מכונות",
    8: "כלי עבודה ידניים", 9: "מכשירי מדע, חשמל ומחשבים", 10: "מכשירים רפואיים",
    11: "התקני תאורה", 12: "כלי רכב", 13: "כלי נשק", 14: "מתכות יקרות ותכשיטים",
    15: "כלי נגינה", 16: "נייר וצורכי נייר", 17: "חומרי אטימה ובידוד",
    18: "עור וחיקויי עור", 19: "חומרי בנייה לא מתכתיים", 20: "רהיטים",
    21: "כלי מטבח וזכוכית", 22: "חבלים וחומרי טקסטיל גולמיים", 23: "מטווה וחוטים",
    24: "אריגים", 25: "דברי הלבשה", 26: "תחרה, רקמה וכפתורים",
    27: "שטיחים ומרבדים", 28: "משחקים וצורכי התעמלות",
    29: "בשר, דגים, חלב ושימורים", 30: "קפה, קמח ודברי מאפה",
    31: "פירות, ירקות ותוצרת חקלאית", 32: "משקאות לא כוהליים ובירה",
    33: "משקאות כוהליים", 34: "צורכי מעשנים",
}

# script of the description, in check order (first match wins)
SCRIPTS = [
    ("עברית", re.compile(r"[֐-׿]")),
    ("כתב ערבי", re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")),
    ("קירילית", re.compile(r"[Ѐ-ӿ]")),
    ("גאורגית", re.compile(r"[Ⴀ-ჿ]")),
    ("לטינית", re.compile(r"[A-Za-zÀ-ɏ]")),
]
SCRIPT_OTHER, SCRIPT_NONE = "כתב אחר", "ללא תיאור"
SCRIPT_ORDER = ["לטינית", "כתב ערבי", "עברית", "קירילית", "גאורגית", SCRIPT_OTHER, SCRIPT_NONE]
IRAN_TOKENS = ("ایران", "IRAN")     # the country's name inside a description

LAG_BUCKETS = [  # (label, lo_days, hi_days) — hi inclusive, None = open
    ("באותו יום", 0, 0),
    ("עד חודש", 1, 31),
    ("חודש עד חצי שנה", 32, 183),
    ("חצי שנה עד שנה", 184, 366),
    ("שנה עד שלוש", 367, 1096),
    ("מעל שלוש שנים", 1097, None),
]
LAG_ERROR = "רישום לפני ההגשה"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def pct_bare(v, digits=1):
    return f"{v:.{digits}f}%"


def dmy(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def cls_label(c):
    return f"{c} {NICE_HE.get(c, '')}".strip() if c in NICE_HE else f"סוג {c}"


def _script(s):
    if not s:
        return None
    for name, rx in SCRIPTS:
        if rx.search(s):
            return name
    return SCRIPT_OTHER


def _classes(s):
    out = []
    for p in re.split(r"[;,]", s):
        p = p.strip()
        if p.isdigit():
            c = int(p)
            if c not in out:
                out.append(c)
    return sorted(out)


def _prepare(df):
    out = pd.DataFrame({
        "num_s": df["מספר הסימן"].str.strip(),
        "num": pd.to_numeric(df["מספר הסימן"].str.strip(), errors="coerce"),
        "status": df["מצב"].str.strip(),
        "scope": df["לאומי/בינלאומי"].str.strip(),
        "he": df["תיאור סימן עברית"].str.strip(),
        "en": df["תיאור סימן אנגלית"].str.strip(),
        "app": pd.to_datetime(df["תאריך בקשה"].str.strip(), format="%d/%m/%Y", errors="coerce"),
        "reg": pd.to_datetime(df["תאריך רישום"].str.strip(), format="%d/%m/%Y", errors="coerce"),
        "cls": df["סוגי ניצה לבקשה"].map(_classes),
    })
    out = out[out["num_s"] != ""].copy()
    out["status"] = out["status"].where(out["status"] != "", "לא צוין")
    out["name"] = out["en"].where(out["en"] != "", out["he"])
    out["script"] = out["he"].map(_script)
    out["script"] = out["script"].where(out["script"].notna(), out["en"].map(_script))
    out["script"] = out["script"].fillna(SCRIPT_NONE)
    out["year"] = out["app"].dt.year
    out["lag"] = (out["reg"] - out["app"]).dt.days
    # stable order for everything downstream
    return out.sort_values(["app", "num", "num_s"], na_position="last", kind="stable")


def _status_list(df):
    seen = set(df["status"])
    return [s for s in STATUS_ORDER if s in seen] + sorted(seen - set(STATUS_ORDER))


def _decade_label(d):
    return f"שנות ה-{d % 100:02d}" if d < 2000 else f"שנות ה-{d}"


# ---------------------------------------------------------------- insights

def insight_first_batch(df):
    d = df.dropna(subset=["app"])
    if len(d) < 50:
        return None
    y0 = int(d["year"].min())
    first = d[d["year"] == y0]
    share = len(first) / len(d)
    if share < 0.15:
        return None
    days = first.groupby("app").size().sort_index().sort_values(ascending=False, kind="stable")
    day, k = days.index[0], int(days.iloc[0])
    reg = (first["status"] == REG).mean() * 100
    s = (f"{n(len(first))} בקשות ({pct(share * 100)} מכלל המאגר) הוגשו כבר ב-{y0}, השנה "
         f"הראשונה במאגר")
    if k >= 0.5 * len(first):
        s += f" — {n(k)} מהן ביום אחד, {dmy(day)}"
    s += f". {pct(reg)} מהן רשומות עד היום."
    return s


def insight_closure_era(df):
    d = df.dropna(subset=["app"])
    early, modern = d[d["year"] < ERA_SPLIT], d[d["year"] >= ERA_SPLIT]
    if len(early) < MIN_ERA_ROWS or len(modern) < MIN_ERA_ROWS:
        return None
    ce = (early["status"] == CLOSED).mean() * 100
    cm = (modern["status"] == CLOSED).mean() * 100
    if abs(ce - cm) < 10:
        return None
    early_txt = f"שהוגשו לפני {ERA_SPLIT}"
    modern_txt = f"שהוגשו מ-{ERA_SPLIT} ואילך"
    if ce > cm:
        (a, ta), (b, tb) = (ce, early_txt), (cm, modern_txt)
    else:
        (a, ta), (b, tb) = (cm, modern_txt), (ce, early_txt)
    return (f"{pct(a)} מהבקשות {ta} כבר סגורות, לעומת {pct(b)} מאלה {tb} — "
            f"{n((d['status'] == CLOSED).sum())} בקשות סגורות בסך הכול.")


def insight_top_class(occ, total):
    s = occ.sort_index().sort_values(ascending=False, kind="stable")
    if len(s) < 2 or total == 0:
        return None
    c0, v0 = int(s.index[0]), int(s.iloc[0])
    if v0 / total < 0.3:
        return None
    c1, v1 = int(s.index[1]), int(s.iloc[1])
    return (f"{pct(v0 / total * 100)} מהבקשות ({n(v0)}) הן לסוג {cls_label(c0)} — יינות, "
            f"משקאות חריפים וכדומה. במקום השני, הרחק מאחור, סוג {cls_label(c1)} "
            f"עם {n(v1)} בקשות.")


def insight_national(df):
    nat = df[df["scope"] == NATIONAL]
    if nat.empty:
        return None
    classes = sorted({c for cl in nat["cls"] for c in cl})
    st = nat["status"].value_counts()
    st = st.sort_index().sort_values(ascending=False, kind="stable")
    parts = ", ".join(f"{k}: {n(v)}" for k, v in st.items())
    yrs = sorted(nat["year"].dropna().astype(int).unique())
    when = (f"ב-{yrs[0]}" if len(yrs) == 1 else
            f"בשנים {', '.join(str(y) for y in yrs[:-1])} ו-{yrs[-1]}") if yrs else ""
    where = (f"כולן בסוג {cls_label(classes[0])}" if len(classes) == 1
             else f"ב-{len(classes)} סוגים")
    return (f"רק {n(len(nat))} בקשות ({pct(len(nat) / len(df) * 100)}) הן בקשות לאומיות "
            f"ישראליות, {where}, שהוגשו {when} ({parts}); כל השאר רישומים בינלאומיים.")


def insight_recent(df):
    d = df.dropna(subset=["app"])
    if d.empty:
        return None
    y1 = int(d["year"].max())
    y0 = y1 - RECENT_YEARS + 1
    r = d[d["year"] >= y0]
    if len(r) < 10:
        return None
    reg = (r["status"] == REG).mean() * 100
    by = r.groupby("year").size().sort_index().sort_values(ascending=False, kind="stable")
    return (f"בעשר שנות ההגשה האחרונות במאגר ({y0}–{y1}) הוגשו {n(len(r))} בקשות, "
            f"{pct(reg)} מהן כבר רשומות. השנה העמוסה בתקופה: {int(by.index[0])} "
            f"עם {n(by.iloc[0])} בקשות.")


def insight_lag(df):
    d = df.dropna(subset=["lag"])
    d = d[d["lag"] >= 0]
    early, modern = d[d["year"] < ERA_SPLIT], d[d["year"] >= ERA_SPLIT]
    if len(early) < MIN_ERA_ROWS or len(modern) < MIN_ERA_ROWS:
        return None
    same_e = (early["lag"] == 0).mean() * 100
    med_m = float(modern["lag"].median())
    if same_e < 50 or med_m < 7:
        return None
    return (f"מהבקשות שהוגשו לפני {ERA_SPLIT} נרשמו {pct(same_e)} ביום הגשתן; מ-{ERA_SPLIT} ואילך "
            f"עוברים בחציון {n(round(med_m))} ימים מהבקשה ועד הרישום.")


def insight_script(df):
    a = df[(df["script"] == "כתב ערבי")].dropna(subset=["app"])
    if len(a) < 10:
        return None
    y0 = int(a["year"].min())
    since = df[df["year"] >= y0]
    share = len(a) / len(since) * 100
    if share < 10:
        return None
    txt = (a["he"] + " " + a["en"]).str.upper()
    iran = int(txt.map(lambda s: any(t.upper() in s for t in IRAN_TOKENS)).sum())
    s = (f"{n(len(a))} בקשות מתוארות בכתב ערבי (פרסית או ערבית), כולן מ-{y0} ואילך — "
         f"{pct(share)} מהבקשות שהוגשו מאז")
    if iran >= 0.5 * len(a):
        s += f"; ב-{n(iran)} מהן מופיע בתיאור שם המדינה ایران (איראן)."
    else:
        s += "."
    return s


def insight_waves(waves, total):
    if len(waves) < 3 or total == 0:
        return None
    top3 = waves[:3]
    k = sum(w["count"] for w in top3)
    if k / total < 0.25:
        return None
    dates = ", ".join(w["date"] for w in top3)
    return (f"הבקשות מגיעות בגלים: בשלושת ימי ההגשה העמוסים ({dates}) הוגשו {n(k)} בקשות — "
            f"{pct(k / total * 100)} מכל המאגר.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    dated = df.dropna(subset=["app"])
    statuses = _status_list(df)
    y_min, y_max = int(dated["year"].min()), int(dated["year"].max())

    # ---- per year x status (continuous years)
    years = list(range(y_min, y_max + 1))
    ys = dated.groupby(["year", "status"]).size()
    year_series = [{"name": s, "data": [int(ys.get((y, s), 0)) for y in years]}
                   for s in statuses]

    # ---- status
    st_counts = df["status"].value_counts()
    status_rows = [{"name": s, "value": int(st_counts.get(s, 0))} for s in statuses]
    status_table = [{"name": r["name"], "count": n(r["value"]),
                     "share": pct_bare(r["value"] / total * 100)} for r in status_rows]

    # ---- decade x status
    dated = dated.assign(dec=(dated["year"] // 10 * 10).astype(int))
    decs = sorted(dated["dec"].unique())
    dec_labels = [_decade_label(int(d)) for d in decs]
    ds = dated.groupby(["dec", "status"]).size()
    dec_tot = dated.groupby("dec").size()
    dec_series = []
    for s in statuses:
        vals = [int(ds.get((d, s), 0)) for d in decs]
        dec_series.append({"name": s, "data": vals,
                           "share": [round(v / int(dec_tot[d]) * 100, 1) for v, d in zip(vals, decs)]})
    dec_table = [{"dec": lab, "total": n(dec_tot[d]),
                  "v": [n(ds.get((d, s), 0)) for s in statuses],
                  "closed": pct_bare(ds.get((d, CLOSED), 0) / int(dec_tot[d]) * 100)}
                 for lab, d in zip(dec_labels, decs)]

    # ---- classes (an application counts in each class it lists)
    ex = df[["status", "cls", "year"]].explode("cls")
    ex = ex.dropna(subset=["cls"])
    ex["cls"] = ex["cls"].astype(int)
    occ = ex.groupby("cls").size()
    occ_sorted = occ.sort_index().sort_values(ascending=False, kind="stable")
    top_cls = list(occ_sorted.index[:TOP_CLASSES])
    rest_cls = list(occ_sorted.index[TOP_CLASSES:])
    cs = ex.groupby(["cls", "status"]).size()
    cls_x = [cls_label(int(c)) for c in top_cls]
    if rest_cls:
        cls_x.append("שאר הסוגים")
    cls_series = []
    for s in statuses:
        vals = [int(cs.get((c, s), 0)) for c in top_cls]
        if rest_cls:
            vals.append(int(sum(cs.get((c, s), 0) for c in rest_cls)))
        cls_series.append({"name": s, "data": vals})
    cls_tot = [sum(x["data"][i] for x in cls_series) for i in range(len(cls_x))]
    cls_table = []
    for i, lab in enumerate(cls_x):
        cl = next((x["data"][i] for x in cls_series if x["name"] == CLOSED), 0)
        cls_table.append({"cls": lab, "total": n(cls_tot[i]),
                          "v": [n(x["data"][i]) for x in cls_series],
                          "closed": pct_bare(cl / cls_tot[i] * 100) if cls_tot[i] else "—"})
    multi = int((df["cls"].map(len) > 1).sum())
    no_cls = int((df["cls"].map(len) == 0).sum())

    # ---- class x decade heatmap
    exd = ex.dropna(subset=["year"]).copy()
    exd["dec"] = (exd["year"] // 10 * 10).astype(int)
    heat_cls = list(occ_sorted.index[:HEAT_CLASSES])
    heat_rest = len(occ_sorted) > HEAT_CLASSES
    heat_y = [cls_label(int(c)) for c in heat_cls] + (["שאר הסוגים"] if heat_rest else [])
    exd["hc"] = exd["cls"].where(exd["cls"].isin(heat_cls), -1)
    hd = exd.groupby(["hc", "dec"]).size()
    keys = list(heat_cls) + ([-1] if heat_rest else [])
    cells, heat_table = [], []
    for yi, c in enumerate(keys):
        row = []
        for xi, d in enumerate(decs):
            v = int(hd.get((c, d), 0))
            cells.append([xi, yi, v])
            row.append(n(v))
        heat_table.append({"cls": heat_y[yi], "v": row})
    heat_max = max((c[2] for c in cells), default=0)

    # ---- busiest application dates
    by_day = dated.groupby("app")
    day_n = by_day.size().sort_index().sort_values(ascending=False, kind="stable")
    exa = df[["app", "cls"]].dropna(subset=["app"]).explode("cls").dropna(subset=["cls"])
    exa["cls"] = exa["cls"].astype(int)
    day_cls = (exa.groupby(["app", "cls"]).size().reset_index(name="k")
                  .sort_values(["app", "k", "cls"], ascending=[True, False, True])
                  .drop_duplicates("app").set_index("app")["cls"])
    day_reg = dated.assign(r=dated["status"] == REG).groupby("app")["r"].sum()
    waves = []
    for day, k in day_n.head(TOP_WAVES).items():
        if k < 2:
            break
        c = day_cls.get(day)
        waves.append({"date": dmy(day), "count": int(k),
                      "reg": int(day_reg.get(day, 0)),
                      "cls": cls_label(int(c)) if c is not None and not pd.isna(c) else "—"})
    waves_table = [{"date": w["date"], "count": n(w["count"]), "reg": n(w["reg"]),
                    "cls": w["cls"]} for w in waves]

    # ---- application -> registration lag, by era
    lg = df.dropna(subset=["lag", "app"])
    eras = [("לפני " + str(ERA_SPLIT), lg[lg["year"] < ERA_SPLIT]),
            (f"{ERA_SPLIT} ואילך", lg[lg["year"] >= ERA_SPLIT])]
    eras = [(lab, e) for lab, e in eras if len(e)]
    lag_x = [b[0] for b in LAG_BUCKETS]
    n_err = int((lg["lag"] < 0).sum())
    if n_err:
        lag_x.append(LAG_ERROR)
    lag_series = []
    for lab, e in eras:
        vals = []
        for _, lo, hi in LAG_BUCKETS:
            m = e["lag"] >= lo
            if hi is not None:
                m &= e["lag"] <= hi
            vals.append(int(m.sum()))
        if n_err:
            vals.append(int((e["lag"] < 0).sum()))
        lag_series.append({"name": lab, "data": vals})
    lag_table = [{"b": b, "v": [n(s["data"][i]) for s in lag_series]} for i, b in enumerate(lag_x)]

    # ---- description script by decade
    sd = dated.groupby(["dec", "script"]).size()
    scripts_present = [s for s in SCRIPT_ORDER if s in set(df["script"])]
    script_series = [{"name": s, "data": [int(sd.get((d, s), 0)) for d in decs]}
                     for s in scripts_present]
    script_table = [{"dec": lab, "v": [n(x["data"][i]) for x in script_series]}
                    for i, lab in enumerate(dec_labels)]

    # ---- tables: newest applications, national applications
    def row(r):
        main, alt = (r.he, r.en) if r.he else (r.en, "")
        return {"num": r.num_s, "name": main or "—", "alt": alt,
                "cls": ", ".join(cls_label(c) for c in r.cls) or "—",
                "status": r.status,
                "app": dmy(r.app) if not pd.isna(r.app) else "—",
                "reg": dmy(r.reg) if not pd.isna(r.reg) else "—"}

    newest = dated.sort_values(["app", "num", "num_s"], ascending=[False, False, False],
                               kind="stable").head(LATEST_N)
    latest_table = [row(r) for r in newest.itertuples()]
    nat = df[df["scope"] == NATIONAL].sort_values(["app", "num", "num_s"], kind="stable")
    national_table = [row(r) for r in nat.head(NATIONAL_MAX).itertuples()]

    rules = [
        ("first_batch", insight_first_batch(df)),
        ("top_class", insight_top_class(occ, total)),
        ("closure_era", insight_closure_era(df)),
        ("lag", insight_lag(df)),
        ("waves", insight_waves(waves, total)),
        ("script", insight_script(df)),
        ("national", insight_national(df)),
        ("recent", insight_recent(df)),
    ]
    insights = [{"id": i, "text_he": s} for i, s in rules if s]

    # ---- KPIs
    n_reg = int(st_counts.get(REG, 0))
    reg_share = n_reg / total * 100 if total else 0
    n_nat = int((df["scope"] == NATIONAL).sum())
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "reg_share": {"value": round(reg_share, 1), "display": pct_bare(reg_share),
                      "tone": "ok" if reg_share >= 60 else "warn"},
        "span": {"value": y_max - y_min + 1, "display": f"{y_min}–{y_max}", "tone": "brand"},
        "national": {"value": n_nat, "display": n(n_nat), "tone": "info" if n_nat else "brand"},
    }

    n_intl = int((df["scope"] == INTL).sum())
    top_c = int(occ_sorted.index[0]) if len(occ_sorted) else None
    peak_y = years[max(range(len(years)), key=lambda i: (sum(s["data"][i] for s in year_series), -i))]
    first_wave = waves[0] if waves else None
    first_ar = dated.loc[dated["script"] == "כתב ערבי", "year"]
    labels = {
        "lede": (f"מרשם כינויי המקור של רשם סימני המסחר: {n(total)} בקשות להגנה בישראל על שמות "
                 f"גאוגרפיים שמזהים מוצר — יין, גבינה, משקה חריף, שטיח או אבן — מ-{y_min} ועד "
                 f"{y_max}. {n(n_intl)} מהן רישומים בינלאומיים ו-{n(n_nat)} בקשות לאומיות "
                 f"ישראליות. לכל בקשה מצוינים מצבה ({n(n_reg)} רשומות), תאריכי ההגשה והרישום "
                 f"וסוגי הסחורות לפי סיווג ניצה."),
        "reg_kpi": f"מהבקשות רשומות ({n(n_reg)})",
        "years_note": (f"מספר הבקשות לפי שנת ההגשה, לפי מצבן היום. השנה העמוסה: {peak_y}. "
                       f"אפשר להתמקד בטווח שנים בגרירה."),
        "years_aria": (f"תרשים עמודות: בקשות לפי שנת הגשה, {y_min}–{y_max}, מחולקות לפי מצב. "
                       f"השיא ב-{peak_y}."),
        "status_note": (f"מצב הבקשות היום: {n(n_reg)} רשומות ו-{n(st_counts.get(CLOSED, 0))} סגורות."),
        "status_aria": f"תרשים טבעת: מצב הבקשות. {pct_bare(reg_share)} רשומות.",
        "status_caption": "בקשות לפי מצב ושיעורן.",
        "dec_note": (f"שיעור הבקשות הרשומות והסגורות לפי עשור ההגשה. העשור האחרון ({dec_labels[-1]}) "
                     f"כולל את השנים {decs[-1]}–{y_max} בלבד."),
        "dec_aria": "תרשים עמודות מוערמות: מצב הבקשות באחוזים לפי עשור ההגשה.",
        "dec_caption": "בקשות לפי עשור הגשה ומצב, ושיעור הסגורות.",
        "cls_note": (f"{len(top_cls)} סוגי הסחורות המובילים לפי סיווג ניצה, לפי מצב הבקשה"
                     + (", ושאר הסוגים יחד" if rest_cls else "")
                     + (f". {n(multi)} בקשות מכסות כמה סוגים ונספרות בכל אחד מהם." if multi else ".")),
        "cls_aria": (f"תרשים עמודות מוערמות: בקשות לפי סוג ניצה. המוביל: סוג "
                     f"{cls_label(top_c) if top_c is not None else ''}."),
        "cls_caption": "בקשות לפי סוג ניצה ומצב, ושיעור הסגורות.",
        "heat_note": (f"באילו סוגי סחורות הוגשו בקשות בכל עשור — {len(heat_cls)} הסוגים הגדולים"
                      + (" ושאר הסוגים יחד." if heat_rest else ".")),
        "heat_aria": "מפת חום: בקשות לפי סוג ניצה ועשור ההגשה.",
        "heat_caption": "בקשות לפי סוג ניצה ועשור הגשה.",
        "waves_note": (f"{len(waves)} ימי ההגשה שבהם התקבלו הכי הרבה בקשות"
                       + (f"; בראש — {first_wave['date']} עם {n(first_wave['count'])} בקשות." if first_wave else ".")),
        "waves_aria": "תרשים עמודות: ימי ההגשה העמוסים ביותר ומספר הבקשות בכל אחד.",
        "waves_caption": "ימי ההגשה העמוסים, מספר הבקשות, הרשומות שבהן וסוג הניצה העיקרי.",
        "lag_note": (f"הזמן מתאריך הבקשה ועד תאריך הרישום, בבקשות שהוגשו לפני {ERA_SPLIT} ומ-{ERA_SPLIT} ואילך"
                     + (f". ב-{n(n_err)} בקשות תאריך הרישום מוקדם מתאריך הבקשה — כנראה טעות הקלדה; הן מוצגות בנפרד." if n_err else ".")),
        "lag_aria": f"תרשים עמודות: הזמן מהבקשה לרישום, לפני {ERA_SPLIT} ומ-{ERA_SPLIT} ואילך.",
        "lag_caption": "בקשות לפי הזמן מהבקשה לרישום ותקופת ההגשה.",
        "script_note": ("באיזה כתב רשום תיאור הסימן, לפי עשור ההגשה"
                        + (f". תיאורים בכתב ערבי מופיעים החל מ-{int(first_ar.min())}." if len(first_ar) else ".")),
        "script_aria": "תרשים עמודות מוערמות: בקשות לפי כתב התיאור ועשור ההגשה.",
        "script_caption": "בקשות לפי עשור ההגשה וכתב התיאור.",
        "latest_note": f"{len(latest_table)} הבקשות האחרונות לפי תאריך ההגשה.",
        "latest_caption": "הבקשות האחרונות: מספר, תיאור, סוג ניצה, מצב ותאריכים.",
        "national_note": (f"כל {n(len(nat))} הבקשות הלאומיות — כינויי מקור ישראליים שהוגשו ישירות לרשם"
                          + (f"; מוצגות {NATIONAL_MAX} הראשונות." if len(nat) > NATIONAL_MAX else ".")),
        "national_caption": "הבקשות הלאומיות: מספר, תיאור, סוג ניצה, מצב ותאריכים.",
    }

    charts = {
        "years": {"x": [str(y) for y in years], "series": year_series},
        "status": status_rows,
        "dec": {"x": dec_labels, "series": dec_series},
        "cls": {"x": cls_x, "series": cls_series},
        "heat": {"x": dec_labels, "y": heat_y, "cells": cells, "max": heat_max},
        "waves": {"x": [w["date"] for w in waves], "y": [w["count"] for w in waves],
                  "cls": [w["cls"] for w in waves]},
        "lag": {"x": lag_x, "series": lag_series},
        "script": {"x": dec_labels, "series": script_series},
    }
    tables = {
        "status": status_table, "statuses": statuses, "dec": dec_table, "cls": cls_table,
        "heat_x": dec_labels, "heat": heat_table, "waves": waves_table,
        "lag_heads": [s["name"] for s in lag_series], "lag": lag_table,
        "script_heads": scripts_present, "script": script_table, "latest": latest_table, "national": national_table,
    }

    return {
        "agent_data": {
            "summary_he": (f"מרשם כינויי המקור בישראל: {n(total)} בקשות להגנה על שמות גאוגרפיים "
                           f"של מוצרים מ-{y_min} ועד {y_max}, {pct_bare(reg_share)} מהן רשומות; "
                           f"רובן המכריע רישומים בינלאומיים, ובראשן משקאות כוהליים."),
            "dataset_kind": "registry",
            "suggested_tags": ["כינויי מקור", "קניין רוחני", "סימני מסחר", "סיווג ניצה",
                               "יין", "משרד המשפטים"],
            "related_ids": ["025c3e07-358d-4892-ac2d-1e28f66ba188",
                            "656f6e4c-ec04-40a5-b3bc-c556b2b127e0",
                            "556634fd-fcec-4bbd-8bd5-ba1390bc1c14",
                            "029b6747-551b-47ad-9a05-ef7f7868fcd0"],
            "temporal_coverage": f"{y_min}/{y_max}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"lag": bool(lag_series), "national": bool(national_table),
                  "waves": bool(waves), "multi": multi > 0, "no_cls": no_cls},
    }
