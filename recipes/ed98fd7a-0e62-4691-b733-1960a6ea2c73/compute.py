"""רשימת האגודות השיתופיות — the registrar of cooperative societies (~7.2k).

One row per cooperative ever registered since 1921: name, registered town and
address, status (active / closed / in liquidation) with the date the status
took effect, registration date, primary type and a comma-separated list of
secondary types (settlement form for agricultural societies: kibbutz, moshav,
community settlement…). Cooperatives are organisations, so they may be named;
the page still never prints their street address or phone — it aggregates
contact completeness only.

"Now" is the latest registration/status date in the data; the current year is
partial and is labelled as such.
"""
import pandas as pd

ACTIVE, LIQ, CLOSED = "פעילה", "בפירוק", "סגורה"
STATUS_ORDER = [ACTIVE, LIQ, CLOSED]
NO_STATUS = "ללא סטטוס"
NO_TYPE = "לא צוין"
UNKNOWN_TOWN = "לא ידוע"
TOP_TYPES = 10
TOP_DECADE_TYPES = 6
TOP_SECONDARY = 12
TOP_TOWNS = 15
MIN_TYPE_N = 50          # survival comparison: types with at least this many societies
MIN_LIFE_N = 30          # lifespan boxplot: types with at least this many closed societies
MIN_DECADE_N = 50        # a decade needs this many registrations to compare its mix
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
             "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
KIBBUTZ_FORMS = ["קיבוץ מתחדש", "קיבוץ שיתופי", "קיבוץ עירוני", "קיבוץ"]


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _date(s):
    """'12/19/1921 12:00:00 AM' → Timestamp (month/day/year; time ignored)."""
    return pd.to_datetime(s.str.strip().str.split(" ").str[0], format="%m/%d/%Y", errors="coerce")


def _vc(s):
    """value_counts with a total order: count desc, then label asc."""
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _top(vc, n, other="אחר"):
    head = [(k, int(v)) for k, v in vc.head(n).items()]
    rest = int(vc.iloc[n:].sum())
    if rest:
        head.append((other, rest))
    return head


def _growth_tone(cur, prev, threshold=0.05):
    if not prev:
        return "brand"
    ch = (cur - prev) / prev
    return "ok" if ch >= threshold else "warn" if ch <= -threshold else "brand"


def _prepare(raw):
    status = raw["StatusDesc"].str.strip().replace("", NO_STATUS)
    town = raw["TownName"].str.strip()
    town = town.where((town != "") & (raw["TownId"].str.strip() != "0"), UNKNOWN_TOWN)
    phone = raw["phone"].str.strip()
    zipc = raw["zip"].str.strip()
    df = pd.DataFrame({
        "status": status,
        "reg": _date(raw["RegistrationDate"]),
        "sdate": _date(raw["StatusDate"]),
        "ptype": raw["PrimaryType"].str.strip().replace("", NO_TYPE),
        "secondary": raw["SecondaryTypes"].str.strip(),
        "town": town,
        "has_town": town != UNKNOWN_TOWN,
        "has_phone": phone.str.contains(r"\d", regex=True) & (phone != "0"),
        "has_zip": zipc.str.fullmatch(r"\d{5,7}") & (zipc != "0"),
        "has_street": raw["StreetName"].str.strip() != "",
        "has_building": raw["Building"].str.contains(r"\d", regex=True),
    })
    df["has_zip"] = df["has_zip"].fillna(False).astype(bool)
    df["has_address"] = df["has_street"] & df["has_building"]
    return df


def _secondary(df):
    """Long frame (row index, secondary type) — a society may carry several."""
    s = df["secondary"].str.split(",").explode().str.strip()
    s = s[s.notna() & (s != "")]
    return s


def _statuses(df):
    present = set(df["status"])
    rest = sorted(present - set(STATUS_ORDER))
    return [s for s in STATUS_ORDER if s in present] + rest


# ---------------------------------------------------------------- insights

def insight_status(df):
    n = len(df)
    a, c, l = (int((df["status"] == s).sum()) for s in (ACTIVE, CLOSED, LIQ))
    tail = f" ו-{_int(l)} נמצאות בהליך פירוק" if l else ""
    return (f"מתוך {_int(n)} האגודות השיתופיות שנרשמו אי-פעם, {_int(a)} ({_pct(a / n)}) פעילות כיום; "
            f"{_int(c)} נסגרו{tail}.")


def insight_dominant(df):
    act = df[df["status"] == ACTIVE]
    if len(act) < 50:
        return None
    vc = _vc(act["ptype"])
    share = vc.iloc[0] / len(act)
    if share < 0.4:
        return None
    second = (f"; הבא אחריו: '{vc.index[1]}' ({_int(vc.iloc[1])})" if len(vc) > 1 else "")
    return (f"הסוג '{vc.index[0]}' שולט במרשם: {_int(vc.iloc[0])} מהאגודות הפעילות ({_pct(share)}) "
            f"רשומות כאגודות מסוג זה{second}.")


def insight_survival(df):
    g = df.groupby("ptype")["status"]
    n = g.size()
    rate = g.apply(lambda s: (s == ACTIVE).mean())
    elig = rate[(n >= MIN_TYPE_N) & (rate.index != NO_TYPE)]
    if len(elig) < 2:
        return None
    order = sorted(elig.items(), key=lambda kv: (-kv[1], kv[0]))
    (hi, hr), (lo, lr) = order[0], order[-1]
    if hr - lr < 0.2:
        return None
    return (f"שיעור ההישרדות שונה מאוד בין הסוגים: {_pct(hr)} מהאגודות מסוג '{hi}' שנרשמו אי-פעם פעילות "
            f"כיום ({_int((df['ptype'].eq(hi) & df['status'].eq(ACTIVE)).sum())} מתוך {_int(n[hi])}), "
            f"לעומת {_pct(lr)} בלבד מהאגודות מסוג '{lo}' ({_int(n[lo])} נרשמו). "
            f"ההשוואה כוללת סוגים עם {_int(MIN_TYPE_N)} אגודות לפחות.")


def insight_kibbutz(df, sec):
    act_idx = df.index[df["status"] == ACTIVE]
    s = sec[sec.index.isin(act_idx) & sec.isin(KIBBUTZ_FORMS)]
    rows = s.index.unique()
    if len(rows) < 20:
        return None
    ren = int(s[s == "קיבוץ מתחדש"].index.nunique())
    coop = int(s[s == "קיבוץ שיתופי"].index.nunique())
    if ren + coop == 0:
        return None
    lead, lead_n, other, other_n = (("מתחדש", ren, "שיתופי", coop) if ren >= coop
                                    else ("שיתופי", coop, "מתחדש", ren))
    return (f"{_int(len(rows))} אגודות פעילות מסווגות כקיבוץ. מתוכן {_int(lead_n)} ({_pct(lead_n / len(rows))}) "
            f"מוגדרות 'קיבוץ {lead}' ו-{_int(other_n)} ({_pct(other_n / len(rows))}) 'קיבוץ {other}'.")


def insight_registrations(df, now):
    y = df["reg"].dt.year
    full, prev = now.year - 1, now.year - 2
    a, b = int((y == full).sum()), int((y == prev).sum())
    if b < 10:
        return None
    ch = (a - b) / b
    if round(ch * 100) == 0:
        trend = f"ללא שינוי לעומת {prev}"
    else:
        trend = f"{'עלייה' if ch > 0 else 'ירידה'} של {abs(ch) * 100:.0f}% לעומת {prev} ({_int(b)})"
    vc = _vc(y.dropna().astype(int))
    peak, peak_n = int(vc.index[0]), int(vc.iloc[0])
    cur = int((y == now.year).sum())
    return (f"ב-{full} נרשמו {_int(a)} אגודות חדשות — {trend}. מתחילת {now.year} ועד "
            f"{now.day}/{now.month} נרשמו {_int(cur)}. שנת השיא במרשם: {peak}, עם {_int(peak_n)} רישומים.")


def insight_december(df):
    m = df["reg"].dt.month.dropna()
    if len(m) < 500:
        return None
    dec = int((m == 12).sum())
    share = dec / len(m)
    if share < 0.12:
        return None
    others = (len(m) - dec) / 11
    return (f"דצמבר בולט ברישום: {_int(dec)} אגודות ({_pct(share)}) נרשמו בחודש זה — פי "
            f"{dec / others:.1f} מהממוצע של שאר החודשים ({_int(round(others))}).")


def _decade_mix(df):
    d = (df["reg"].dt.year // 10 * 10).dropna().astype(int)
    return pd.crosstab(d, df.loc[d.index, "ptype"])


def insight_mix_shift(df, now):
    ct = _decade_mix(df)
    decades = sorted(ct.index)
    totals = ct.sum(axis=1)
    cur = decades[-1]
    if totals[cur] < MIN_DECADE_N and len(decades) >= 3:
        cur = decades[-2]
    i = decades.index(cur)
    if i == 0:
        return None
    prev = decades[i - 1]
    if totals[cur] < MIN_DECADE_N or totals[prev] < MIN_DECADE_N:
        return None
    sc, sp = ct.loc[cur] / totals[cur], ct.loc[prev] / totals[prev]
    gain = (sc - sp).drop(NO_TYPE, errors="ignore")
    best = sorted(gain.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if best[1] < 0.05:
        return None
    t = best[0]
    cur_lbl = f"בשנות ה-{cur} (עד {now.year})" if cur + 9 >= now.year else f"בשנות ה-{cur}"
    return (f"תמהיל הרישום משתנה: {cur_lbl} {_pct(sc[t])} מהאגודות החדשות ({_int(ct.loc[cur, t])}) "
            f"הן מסוג '{t}', לעומת {_pct(sp[t])} בשנות ה-{prev}.")


def insight_liquidation(df, now):
    liq = df[(df["status"] == LIQ) & df["sdate"].notna()]
    if len(liq) < 10:
        return None
    y = liq["sdate"].dt.year
    recent = int((y >= now.year - 1).sum())
    share = recent / len(liq)
    if share < 0.25:
        return None
    cur = int((y == now.year).sum())
    return (f"חלק ניכר מהליכי הפירוק נפתחו לאחרונה: {_int(recent)} מתוך {_int(len(liq))} האגודות שבפירוק כיום ({_pct(share)}) "
            f"נכנסו להליך מאז תחילת {now.year - 1}, {_int(cur)} מהן ב-{now.year} (עד {now.day}/{now.month}).")


def _lifespans(df):
    c = df[(df["status"] == CLOSED) & df["reg"].notna() & df["sdate"].notna()].copy()
    c["life"] = (c["sdate"] - c["reg"]).dt.days / 365.25
    bad = int((c["life"] < 0).sum())
    return c[c["life"] >= 0], bad


def insight_lifespan(df):
    c, _ = _lifespans(df)
    if len(c) < 100:
        return None
    med = c["life"].median()
    g = c.groupby("ptype")["life"]
    m = g.median()[(g.size() >= MIN_LIFE_N) & (g.median().index != NO_TYPE)]
    if len(m) < 2:
        return None
    order = sorted(m.items(), key=lambda kv: (-kv[1], kv[0]))
    (hi, hm), (lo, lm) = order[0], order[-1]
    return (f"אגודה שנסגרה פעלה בחציון {med:.1f} שנים מהרישום ועד הסגירה. הארוכות ביותר: אגודות "
            f"'{hi}' (חציון {hm:.1f} שנים); הקצרות ביותר: '{lo}' ({lm:.1f} שנים).")


# ---------------------------------------------------------------- charts

def _years_chart(df, statuses, now):
    y = df["reg"].dt.year.dropna().astype(int)
    years = list(range(int(y.min()), now.year + 1))
    by = df.loc[y.index].groupby([y, "status"]).size()
    return {"x": [str(v) for v in years],
            "series": [{"name": s, "data": [int(by.get((v, s), 0)) for v in years]} for s in statuses]}


def _decades_chart(df, now):
    ct = _decade_mix(df)
    totals_by_type = ct.sum(axis=0)
    types = [t for t, _ in sorted(totals_by_type.items(), key=lambda kv: (-kv[1], kv[0]))
             if t != NO_TYPE][:TOP_DECADE_TYPES]
    decades = sorted(ct.index)
    labels = [f"שנות ה-{d}" for d in decades]
    rows_tot = ct.sum(axis=1)
    series = []
    for t in types:
        series.append({"name": t, "counts": [int(ct.loc[d, t]) for d in decades]})
    other = [int(rows_tot[d] - sum(int(ct.loc[d, t]) for t in types)) for d in decades]
    if any(other):
        series.append({"name": "אחר", "counts": other})
    for s in series:
        s["data"] = [round(c / int(rows_tot[d]) * 100, 1) if rows_tot[d] else 0
                     for c, d in zip(s["counts"], decades)]
    rows = [{"label": labels[i], "total": int(rows_tot[d]),
             "cells": [s["counts"][i] for s in series]} for i, d in enumerate(decades)]
    return {"x": labels, "series": series, "names": [s["name"] for s in series], "rows": rows}


def _types_chart(df, statuses):
    vc = _vc(df["ptype"])
    top = [k for k in vc.index[:TOP_TYPES]]
    key = df["ptype"].where(df["ptype"].isin(top), "אחר")
    names = top + (["אחר"] if (key == "אחר").any() else [])
    ct = df.groupby([key, "status"]).size()
    series = [{"name": s, "data": [int(ct.get((t, s), 0)) for t in names]} for s in statuses]
    totals = [int((key == t).sum()) for t in names]
    rows = []
    for i, t in enumerate(names):
        act = int(ct.get((t, ACTIVE), 0))
        rows.append({"label": t, "total": totals[i], "active": act,
                     "share": round(act / totals[i] * 100, 1) if totals[i] else 0.0})
    return {"names": names, "series": series, "rows": rows}


def compute(frames):
    df = _prepare(frames.pop("main"))
    sec = _secondary(df)
    now = max(df["reg"].max(), df["sdate"].max())
    statuses = _statuses(df)
    act = df[df["status"] == ACTIVE]
    n, n_act = len(df), len(act)
    full = now.year - 1

    years = _years_chart(df, statuses, now)
    decades = _decades_chart(df, now)
    types = _types_chart(df, statuses)
    status = [(s, int((df["status"] == s).sum())) for s in statuses]

    sec_act = sec[sec.index.isin(act.index)]
    secondary = _top(_vc(sec_act), TOP_SECONDARY)
    n_sec_rows = int(sec_act.index.nunique())

    closed = df[df["status"].isin([CLOSED, LIQ]) & df["sdate"].notna()]
    cy = closed["sdate"].dt.year.astype(int)
    c_years = list(range(int(cy.min()), now.year + 1)) if len(cy) else []
    cby = closed.groupby([cy, "status"]).size()
    c_statuses = [s for s in (CLOSED, LIQ) if (closed["status"] == s).any()]
    closures = {"x": [str(v) for v in c_years],
                "series": [{"name": s, "data": [int(cby.get((v, s), 0)) for v in c_years]}
                           for s in c_statuses]}

    life, life_bad = _lifespans(df)
    lg = life.groupby("ptype")["life"]
    elig = [t for t in lg.size().index if lg.size()[t] >= MIN_LIFE_N and t != NO_TYPE]
    meds = {t: float(lg.get_group(t).median()) for t in elig}
    order = sorted(elig, key=lambda t: (-meds[t], t))
    box, life_rows = [], []
    for t in order:
        v = lg.get_group(t).sort_values().to_numpy()
        q = [float(pd.Series(v).quantile(p)) for p in (0.05, 0.25, 0.5, 0.75, 0.95)]
        box.append([round(x, 1) for x in q])
        life_rows.append({"label": t, "n": len(v), "median": round(q[2], 1),
                          "q1": round(q[1], 1), "q3": round(q[3], 1)})
    lifespan = {"names": order, "box": box, "rows": life_rows}

    m = df["reg"].dt.month.dropna().astype(int).value_counts()
    months = {"names": MONTHS_HE, "values": [int(m.get(i + 1, 0)) for i in range(12)]}

    act_known = act[act["has_town"]]
    towns = [(k, int(v)) for k, v in _vc(act_known["town"]).head(TOP_TOWNS).items()]
    n_towns = int(act_known["town"].nunique())

    contact_fields = [("יישוב ידוע", "has_town"), ("מיקוד", "has_zip"), ("טלפון", "has_phone"),
                      ("רחוב ומספר בית", "has_address")]
    contact = {"names": [lbl for lbl, _ in contact_fields],
               "values": [round(float(act[c].mean()) * 100, 1) if n_act else 0.0
                          for _, c in contact_fields]}

    rules = [
        ("status", insight_status(df)),
        ("dominant", insight_dominant(df)),
        ("survival", insight_survival(df)),
        ("kibbutz", insight_kibbutz(df, sec)),
        ("registrations", insight_registrations(df, now)),
        ("mix_shift", insight_mix_shift(df, now)),
        ("liquidation", insight_liquidation(df, now)),
        ("lifespan", insight_lifespan(df)),
        ("december", insight_december(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    ry = df["reg"].dt.year
    new_full, new_prev = int((ry == full).sum()), int((ry == full - 1).sum())
    sy = df["sdate"].dt.year
    closed_full = int(((df["status"] == CLOSED) & (sy == full)).sum())
    n_liq = int((df["status"] == LIQ).sum())
    liq_recent = int(((df["status"] == LIQ) & (sy >= full)).sum())
    first_year = int(ry.min())
    now_he = f"{now.day}/{now.month}/{now.year}"
    top_type = types["names"][0]
    top_type_act = int((act["ptype"] == top_type).sum())

    def bar(items):
        return {"names": [k for k, _ in items], "values": [v for _, v in items]}

    return {
        "agent_data": {
            "summary_he": (f"מרשם האגודות השיתופיות: {_int(n)} אגודות שנרשמו בישראל מאז {first_year}, "
                           f"מהן {_int(n_act)} פעילות — קיבוצים, מושבים, אגודות חקלאיות, שיכון, "
                           f"אשראי ועוד; סטטוס, סוג, שנת רישום ויישוב. מעודכן עד {now_he}."),
            "dataset_kind": "registry",
            "suggested_tags": ["אגודות שיתופיות", "קואופרטיבים", "קיבוצים", "מושבים", "רשם האגודות"],
            "related_ids": ["246d949c-a253-4811-8a11-41a137d3d613",
                            "c5ac01fb-c7ef-4e5e-ba81-e9e11c6f7bd9",
                            "3fc54b81-25b3-4ac7-87db-248c3e1602de",
                            "4acf8b98-776e-4c36-8f98-73cc73fed623",
                            "bd731d1b-aab6-4a13-a4a3-e3102a320fd4"],
            "temporal_coverage": f"{first_year}/{now.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "active": {"value": n_act, "display": _int(n_act), "tone": "brand"},
            # Liquidations: warn while a meaningful share of them are recent.
            "liquidation": {"value": n_liq, "display": _int(n_liq),
                            "tone": "warn" if n_liq and liq_recent / n_liq >= 0.25 else "info"},
            "new_full": {"value": new_full, "display": _int(new_full),
                         "tone": _growth_tone(new_full, new_prev)},
            "closed_full": {"value": closed_full, "display": _int(closed_full), "tone": "brand"},
        },
        "charts": {
            "years": years,
            "decades": decades,
            "status": bar(status),
            "types": types,
            "secondary": bar(secondary),
            "closures": closures,
            "lifespan": lifespan,
            "months": months,
            "towns": bar(towns),
            "contact": contact,
        },
        "flags": {"closures": bool(c_years), "lifespan": len(order) >= 2},
        "insights": insights,
        "labels": {
            "lede": (f"{_int(n)} אגודות שיתופיות נרשמו בישראל מאז {first_year}; {_int(n_act)} מהן פעילות "
                     f"היום, {_int(n_liq)} בפירוק והשאר נסגרו. הסוג הנפוץ: '{top_type}' "
                     f"({_int(top_type_act)} אגודות פעילות). הרישום האחרון במאגר: {now_he}."),
            "full_year": str(full),
            "years_aria": (f"גרף עמודות מוערמות: אגודות לפי שנת רישום ({first_year}–{now.year}) "
                           f"ומצבן כיום."),
            "years_note": (f"כל עמודה היא שנתון רישום, צבועה לפי מצב האגודות היום. "
                           f"השנה האחרונה חלקית — עד {now_he}."),
            "decades_aria": "גרף עמודות מוערמות לפי אחוזים: תמהיל סוגי האגודות שנרשמו בכל עשור.",
            "decades_note": (f"חלקו של כל סוג מבין האגודות שנרשמו בכל עשור: {TOP_DECADE_TYPES} הסוגים "
                             f"הנפוצים, והשאר תחת 'אחר'. העשור האחרון חלקי — עד {now.year}."),
            "status_aria": f"תרשים עמודות: {_int(n)} האגודות לפי סטטוס במרשם.",
            "types_aria": f"גרף עמודות מוערמות: האגודות לפי סוג ראשי ({TOP_TYPES} הנפוצים) ומצבן.",
            "secondary_aria": f"תרשים עמודות: הסיווגים המשניים הנפוצים בקרב האגודות הפעילות.",
            "secondary_note": (f"לאגודה יכולים להיות כמה סיווגים משניים; ל-{_int(n_sec_rows)} מתוך "
                               f"{_int(n_act)} האגודות הפעילות רשום סיווג משני."),
            "closures_aria": "גרף עמודות מוערמות: אגודות שנסגרו או נכנסו לפירוק, לפי שנת שינוי הסטטוס.",
            "closures_note": (f"לפי תאריך הסטטוס הנוכחי של כל אגודה: סגירה, או כניסה להליך פירוק. "
                              f"השנה האחרונה חלקית — עד {now_he}."),
            "lifespan_aria": "תרשים קופסה: משך החיים בשנים של אגודות שנסגרו, לפי סוג ראשי.",
            "lifespan_note": (f"השנים מהרישום ועד הסגירה, לאגודות סגורות בסוגים עם {_int(MIN_LIFE_N)} "
                              f"סגירות לפחות; הקופסה היא הרבעון האמצעי, השפמים — האחוזון ה-5 וה-95."
                              + (" רשומה אחת שבה תאריך הסגירה קודם לרישום הושמטה." if life_bad == 1
                                 else f" {_int(life_bad)} רשומות שבהן תאריך הסגירה קודם לרישום הושמטו."
                                 if life_bad else "")),
            "months_aria": "תרשים עמודות: אגודות לפי חודש הרישום בשנה, בכל השנים.",
            "towns_aria": f"תרשים עמודות: {TOP_TOWNS} היישובים עם מספר האגודות הפעילות הגבוה ביותר.",
            "towns_note": (f"לפי הכתובת הרשומה; האגודות הפעילות רשומות ב-{_int(n_towns)} יישובים, "
                           f"ול-{_int((~act['has_town']).sum())} מהן אין יישוב ידוע."),
            "contact_aria": "תרשים עמודות: שיעור האגודות הפעילות שיש להן כל אחד מפרטי הכתובת והקשר.",
        },
    }
