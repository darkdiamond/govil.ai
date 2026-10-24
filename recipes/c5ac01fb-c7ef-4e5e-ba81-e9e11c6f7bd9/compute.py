"""מאגר עמותות וחברות לתועלת הציבור — Registrar of Associations, 4 tables:

  npos       every registered association (עמותה): status, sector, town,
             latest financial/staff report
  donations  donations from foreign state entities, as reported by the
             recipient associations
  certs      "proper management" certificates (אישור ניהול תקין) per year
  pbcs       public benefit companies (חל"צ)

All are organizations; no person is named. "Now" is always derived from the
data: the latest status update, donation report or certificate update. The
current year is partial everywhere, so year-over-year rules compare the last
two full years.
"""
import pandas as pd

ACTIVE = {"רשומה", "פעילה", "החייאה"}
IN_PROCESS = {
    "בתהליכי רישום", "בהליכי פירוק מרצון", "בפרוק מרצון", "הוגשה בקשת פירוק לבית משפט",
    "בפרוק ע~י בימ~ש", "פירוק זמני", "כונס נכסים",
}
GROUPS = ["פעילה", "בהליכים", "נמחקה או פורקה"]
REG_FROM = 1980
CERT_YEARS = 15
TOP_STATUS = 10
TOP_TOWNS = 15
TOP_DON = 10
REV_BINS = [0, 1, 50_000, 250_000, 1_000_000, 5_000_000, 25_000_000, float("inf")]
REV_LABELS = ["0", "עד 50 אלף", "50–250 אלף", "250 אלף–1 מיליון", "1–5 מיליון",
              "5–25 מיליון", "25 מיליון ומעלה"]
STAFF_BINS = [-1, 0, 5, 20, 100, float("inf")]
STAFF_LABELS = ["0", "1–5", "6–20", "21–100", "מעל 100"]


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _ils_m(v):
    return f"{v / 1e6:,.1f} מיליון ₪"


def _clean(s):
    # The registrar's export writes '~' for both ',' and '"': a comma when a
    # space follows ("חינוך~ השכלה"), gershayim inside a word ("ע~ר", "ארה~ב").
    return (s.str.replace("~ ", ", ", regex=False)
             .str.replace("~", '"', regex=False).str.strip())


def _group(status):
    if status in ACTIVE:
        return "פעילה"
    if status in IN_PROCESS:
        return "בהליכים"
    return "נמחקה או פורקה"


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _top(vc, n, other="אחר"):
    head = [(k, int(v)) for k, v in vc.head(n).items()]
    rest = int(vc.iloc[n:].sum())
    if rest:
        head.append((other, rest))
    return head


def _prep_npos(df):
    upd = pd.to_datetime(df["תאריך עדכון סטטוס"].str.replace(r"\s+", " ", regex=True),
                         format="%b %d %Y %I:%M%p", errors="coerce")
    out = pd.DataFrame({
        "status": df["סטטוס עמותה"].str.strip(),
        "sector": _clean(df["סיווג פעילות ענפי"]),
        "town": df["כתובת - ישוב"].str.strip(),
        "registered": pd.to_datetime(df["תאריך רישום עמותה"], format="%d/%m/%Y", errors="coerce"),
        "updated": upd,
        "revenue": pd.to_numeric(df["מחזור כספי (הכנסות)"], errors="coerce"),
        "employees": pd.to_numeric(df["כמות עובדים"], errors="coerce"),
        "volunteers": pd.to_numeric(df["כמות מתנדבים"], errors="coerce"),
    })
    out["group"] = out["status"].map(_group)
    return out


def insight_active(n):
    total = len(n)
    act = int((n["group"] == "פעילה").sum())
    gone = int((n["group"] == "נמחקה או פורקה").sum())
    return (f"מתוך {_int(total)} עמותות שנרשמו אי-פעם, {_int(act)} ({_pct(act / total)}) רשומות "
            f"ופעילות כיום ו-{_int(gone)} ({_pct(gone / total)}) נמחקו או פורקו.")


def insight_sector(n):
    a = n[(n["group"] == "פעילה") & (n["sector"] != "")]
    if len(a) < 100:
        return None
    vc = _sorted_counts(a["sector"])
    return (f"התחום הנפוץ ביותר בקרב העמותות הפעילות הוא '{vc.index[0]}' עם {_int(vc.iloc[0])} "
            f"עמותות ({_pct(vc.iloc[0] / len(a))}), ואחריו '{vc.index[1]}' ({_pct(vc.iloc[1] / len(a))}).")


def insight_registrations(n):
    yrs = n["registered"].dropna().dt.year
    if yrs.empty:
        return None
    cur = int(yrs.max())
    full, prev = cur - 1, cur - 2
    a, b = int((yrs == full).sum()), int((yrs == prev).sum())
    if b < 50:
        return None
    ch = (a - b) / b
    if abs(ch) < 0.03:
        trend = f"בדומה ל-{prev} ({_int(b)})"
    else:
        trend = f"{'עלייה' if ch > 0 else 'ירידה'} של {_pct(abs(ch))} לעומת {prev} ({_int(b)})"
    return (f"ב-{full} נרשמו {_int(a)} עמותות חדשות — {trend}. ב-{cur} נרשמו עד כה "
            f"{_int((yrs == cur).sum())}.")


def insight_revenue(n):
    r = n["revenue"].dropna()
    r = r[r > 0]
    if len(r) < 100:
        return None
    big = int((r >= 1_000_000).sum())
    return (f"בקרב {_int(len(r))} העמותות שדיווחו על מחזור הכנסות, המחזור החציוני הוא "
            f"{_int(r.median())} ₪; ל-{_pct(big / len(r))} מהן מחזור של מיליון ₪ ומעלה.")


def insight_town(n):
    a = n[(n["group"] == "פעילה") & (n["town"] != "")]
    if len(a) < 100:
        return None
    vc = _sorted_counts(a["town"])
    return (f"{vc.index[0]} היא מקום מושבן של {_pct(vc.iloc[0] / len(a))} מהעמותות הפעילות "
            f"({_int(vc.iloc[0])}); אחריה {vc.index[1]} ({_int(vc.iloc[1])}) ו{vc.index[2]} "
            f"({_int(vc.iloc[2])}).")


def insight_certs(c, cert_now):
    full, prev = cert_now.year - 1, cert_now.year - 2
    rate = {}
    for y in (full, prev):
        g = c[c["year"] == y]
        if len(g) < 100:
            return None
        rate[y] = (g["status"] == "נחתם אישור").mean()
    diff = rate[full] - rate[prev]
    trend = (f"שיעור דומה ל-{prev}" if abs(diff) < 0.01
             else f"לעומת {_pct(rate[prev])} ב-{prev}")
    n_full = int((c["year"] == full).sum())
    return (f"לשנת {full} נחתם אישור ניהול תקין ל-{_pct(rate[full])} מ-{_int(n_full)} העמותות "
            f"שנבדקו, {trend}.")


def insight_donations(d, don_now):
    full, prev = don_now.year - 1, don_now.year - 2
    a = d.loc[d["year"] == full, "amount"].sum()
    b = d.loc[d["year"] == prev, "amount"].sum()
    if b <= 0:
        return None
    ch = (a - b) / b
    trend = (f"בדומה ל-{prev}" if abs(ch) < 0.03
             else f"{'עלייה' if ch > 0 else 'ירידה'} של {_pct(abs(ch))} לעומת {prev}")
    recipients = int(d.loc[d["year"] == full, "npo"].nunique())
    return (f"ב-{full} דיווחו {_int(recipients)} עמותות על תרומות מישויות מדיניות זרות בסך "
            f"{_ils_m(a)} — {trend}.")


def insight_top_recipient(d):
    tot = d["amount"].sum()
    if tot <= 0:
        return None
    vc = d.groupby("npo_name")["amount"].sum().sort_index().sort_values(ascending=False, kind="stable")
    top5 = vc.head(5).sum() / tot
    if top5 < 0.1:
        return None
    return (f"חמש העמותות שקיבלו את הסכום הגבוה ביותר מישויות מדיניות זרות מרכזות "
            f"{_pct(top5)} מכלל התרומות המדווחות ({_ils_m(tot)}); המובילה היא '{vc.index[0]}'.")


def compute(frames):
    n = _prep_npos(frames["npos"])
    now = n["updated"].max()

    # --- registrations by year and status group
    reg = n.dropna(subset=["registered"])
    reg = reg[reg["registered"].dt.year >= REG_FROM]
    yrs = list(range(REG_FROM, int(reg["registered"].dt.year.max()) + 1))
    by = reg.groupby([reg["registered"].dt.year, "group"]).size()
    registrations = {"x": [str(y) for y in yrs],
                     "series": [{"name": g, "data": [int(by.get((y, g), 0)) for y in yrs]}
                                for g in GROUPS]}

    status = _top(_sorted_counts(n["status"]), TOP_STATUS)
    act = n[n["group"] == "פעילה"]
    sector = [(k, int(v)) for k, v in _sorted_counts(act.loc[act["sector"] != "", "sector"]).items()]
    sec_all = n[n["sector"] != ""].groupby("sector")
    alive = sorted(((k, round(float((g["group"] == "פעילה").mean() * 100), 1), len(g))
                    for k, g in sec_all if len(g) >= 100), key=lambda t: (-t[1], t[0]))
    towns = _top(_sorted_counts(act.loc[act["town"] != "", "town"]), TOP_TOWNS, "שאר היישובים")

    rev = n["revenue"].dropna()
    rev_b = pd.cut(rev, REV_BINS, labels=REV_LABELS, right=False).value_counts()
    revenue = {"names": REV_LABELS, "values": [int(rev_b.get(l, 0)) for l in REV_LABELS]}
    emp_b = pd.cut(n["employees"].dropna(), STAFF_BINS, labels=STAFF_LABELS).value_counts()
    vol_b = pd.cut(n["volunteers"].dropna(), STAFF_BINS, labels=STAFF_LABELS).value_counts()
    staff = {"names": STAFF_LABELS,
             "employees": [int(emp_b.get(l, 0)) for l in STAFF_LABELS],
             "volunteers": [int(vol_b.get(l, 0)) for l in STAFF_LABELS]}

    # --- certificates
    cr = frames["certs"]
    c = pd.DataFrame({
        "npo": cr["מספר עמותה"].str.strip(),
        "year": pd.to_numeric(cr["שנת האישור"], errors="coerce"),
        "status": cr["האם יש אישור"].str.strip(),
        "updated": pd.to_datetime(cr["תאריך עדכון אחרון של רשומה"], format="%d/%m/%Y", errors="coerce"),
    }).dropna(subset=["year"])
    c["year"] = c["year"].astype(int)
    cert_now = c["updated"].max()
    cert_states = [k for k, _ in _sorted_counts(c["status"]).items()]
    cy = sorted(c["year"].unique())[-CERT_YEARS:]
    cby = c.groupby(["year", "status"]).size()
    certs = {"x": [str(y) for y in cy],
             "series": [{"name": s, "data": [int(cby.get((y, s), 0)) for y in cy]} for s in cert_states]}

    # --- foreign-state donations
    dr = frames["donations"]
    d = pd.DataFrame({
        "npo": dr["מספר עמותה"].str.strip(),
        "npo_name": _clean(dr["שם עמותה"]),
        "donor": _clean(dr["ישות מדינית זרה תורמת"]),
        "dtype": _clean(dr["סוג ישות מדינית זרה תורמת (קוד)"]),
        "amount": pd.to_numeric(dr["סכום התרומה בש~ח"], errors="coerce").fillna(0),
        "year": pd.to_numeric(dr["שנת תרומה"], errors="coerce"),
        "reported": pd.to_datetime(dr["תאריך דיווח התרומה"], format="%d/%m/%Y", errors="coerce"),
    }).dropna(subset=["year"])
    d["year"] = d["year"].astype(int)
    don_now = d["reported"].max()
    dy = d.groupby("year")["amount"].sum().sort_index()
    don_year = {"names": [str(y) for y in dy.index], "values": [round(v / 1e6, 1) for v in dy]}
    dt = d.groupby("dtype")["amount"].sum().sort_index().sort_values(ascending=False, kind="stable")
    don_type = {"names": list(dt.index), "values": [round(v / 1e6, 1) for v in dt]}
    rec = d.groupby("npo_name")["amount"].sum().sort_index().sort_values(ascending=False, kind="stable")
    don_top = {"names": list(rec.index[:TOP_DON]), "values": [round(v / 1e6, 1) for v in rec.iloc[:TOP_DON]]}
    dn = d.groupby("donor")["amount"].sum().sort_index().sort_values(ascending=False, kind="stable")
    donors = {"names": list(dn.index[:TOP_DON]), "values": [round(v / 1e6, 1) for v in dn.iloc[:TOP_DON]]}
    main_funded = int(dr.loc[dr["עיקר מימון תרומות מישות מדינית זרה"].str.strip() == "כן",
                             "מספר עמותה"].nunique())

    # --- public benefit companies
    p = frames["pbcs"]
    pbc = [(k, int(v)) for k, v in _sorted_counts(p["סטטוס חלצ"].str.strip()).items()]
    pbc_sector = _top(_sorted_counts(_clean(p.loc[p["סיווג פעילות ענפי"].str.strip() != "",
                                                  "סיווג פעילות ענפי"])), 8)

    rules = [
        ("active", insight_active(n)),
        ("sector", insight_sector(n)),
        ("registrations", insight_registrations(n)),
        ("certs", insight_certs(c, cert_now)),
        ("donations", insight_donations(d, don_now)),
        ("top_recipient", insight_top_recipient(d)),
        ("revenue", insight_revenue(n)),
        ("town", insight_town(n)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]
    total, active = len(n), int((n["group"] == "פעילה").sum())
    now_he = f"{now.day}/{now.month}/{now.year}"

    def bar(items):
        return {"names": [k for k, _ in items], "values": [v for _, v in items]}

    return {
        "agent_data": {
            "summary_he": (f"רשם העמותות: {_int(total)} עמותות שנרשמו אי-פעם, מהן {_int(active)} "
                           f"פעילות; לצדן אישורי ניהול תקין, תרומות מישויות מדיניות זרות "
                           f"וחברות לתועלת הציבור. מעודכן עד {now_he}."),
            "dataset_kind": "registry",
            "related_ids": [],
            "suggested_tags": ["עמותות", "מגזר שלישי", "רשם העמותות", "תרומות"],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": total, "display": _int(total)},
            "active": {"value": active, "display": _int(active)},
            "certs": {"value": int(((c["year"] == cert_now.year) & (c["status"] == "נחתם אישור")).sum()),
                      "display": _int(((c["year"] == cert_now.year) & (c["status"] == "נחתם אישור")).sum())},
            "donations": {"value": float(d["amount"].sum()), "display": _ils_m(d["amount"].sum())},
            "pbcs": {"value": len(p), "display": _int(len(p))},
        },
        "charts": {
            "registrations": registrations,
            "status": bar(status),
            "sector": bar(sector),
            "alive": {"names": [k for k, _, _ in alive], "values": [v for _, v, _ in alive],
                      "n": [m for _, _, m in alive]},
            "towns": bar(towns),
            "revenue": revenue,
            "staff": staff,
            "certs": certs,
            "don_year": don_year,
            "don_type": don_type,
            "don_top": don_top,
            "donors": donors,
            "pbc": bar(pbc),
            "pbc_sector": bar(pbc_sector),
        },
        "insights": insights,
        "labels": {
            "lede": (f"{_int(total)} עמותות שנרשמו אי-פעם ברשם העמותות ({_int(active)} פעילות), "
                     f"אישורי ניהול תקין, {_int(len(d))} דיווחים על תרומות מישויות מדיניות זרות "
                     f"ו-{_int(len(p))} חברות לתועלת הציבור. עדכון הסטטוס האחרון: {now_he}."),
            "cert_year": str(cert_now.year),
            "reg_aria": f"גרף עמודות מוערמות: עמותות לפי שנת רישום ({REG_FROM} ואילך) ומצבן כיום.",
            "reg_note": (f"עמותות לפי שנת הרישום, צבועות לפי מצבן היום. ל-{_int(n['registered'].isna().sum())} "
                         f"עמותות אין תאריך רישום והן אינן מוצגות."),
            "status_aria": "תרשים עמודות: העמותות לפי סטטוס ברשם.",
            "sector_aria": f"תרשים עמודות: {_int(active)} העמותות הפעילות לפי תחום פעילות.",
            "alive_aria": "תרשים עמודות: שיעור העמותות שעדיין פעילות מתוך כל שנרשמו בכל תחום.",
            "alive_note": "שיעור העמותות שעדיין פעילות מתוך כל העמותות שנרשמו בתחום (תחומים עם 100 עמותות לפחות).",
            "towns_aria": f"תרשים עמודות: {TOP_TOWNS} היישובים עם מספר העמותות הפעילות הגבוה ביותר.",
            "revenue_aria": "תרשים עמודות: העמותות לפי מחזור ההכנסות בדוח האחרון.",
            "revenue_note": (f"לפי הדוח הכספי האחרון שהוגש; {_int(rev.size)} עמותות דיווחו על מחזור."),
            "staff_aria": "תרשים עמודות מקובצות: העמותות לפי מספר העובדים ומספר המתנדבים בדוח האחרון.",
            "certs_aria": f"גרף עמודות מוערמות: אישורי ניהול תקין לפי שנה ומצב, {CERT_YEARS} השנים האחרונות.",
            "certs_note": ("אישור ניהול תקין ניתן לכל שנה בנפרד; השנה הנוכחית והבאה עדיין "
                           "בתהליך ולכן מספר הסירובים וההיעדרויות בהן חלקי."),
            "don_year_aria": "תרשים עמודות: סך התרומות מישויות מדיניות זרות לפי שנה, במיליוני ₪.",
            "don_year_note": (f"לפי דיווחי העמותות; השנה האחרונה חלקית. {_int(main_funded)} עמותות "
                              f"דיווחו שעיקר מימונן מתרומות כאלה."),
            "don_type_aria": "תרשים עמודות: סך התרומות לפי סוג הישות התורמת, במיליוני ₪.",
            "don_top_aria": f"תרשים עמודות: {TOP_DON} העמותות שקיבלו את הסכום הגבוה ביותר, במיליוני ₪.",
            "donors_aria": f"תרשים עמודות: {TOP_DON} הישויות התורמות הגדולות, במיליוני ₪.",
            "pbc_aria": f"תרשים עמודות: {_int(len(p))} החברות לתועלת הציבור לפי סטטוס.",
            "pbc_sector_aria": "תרשים עמודות: החברות לתועלת הציבור לפי תחום פעילות.",
        },
    }
