"""מרשם העוסקים באסבסט — Ministry of Environmental Protection register of
asbestos licence holders.

One row per licence (~460): licence type (role × material: contractor,
responsible worker, surveyor, supervisor; cement vs friable asbestos), the
holder's name, contact details, settlement and district, licence expiry date,
a free-text disciplinary history, and — for responsible workers — the
contractor that employs them. The whole register is republished on each
update and lists only licences still in force, so the page is a snapshot.
There is no "today" in the data; time views are by expiry date (the
earliest expiry is the nearest one) and by disciplinary-event date.

Licence numbers, phones, faxes, emails and street addresses never reach the
page; contact columns are used only as completeness percentages. Business
names (contractors, incl. sole traders named after their owner) are named in
the employer ranking. Disciplinary records are shown only in aggregate.

Disciplinary text is a "<"-separated list of events like
"התליית רישיון עבור <name> מתאריך dd/mm/yyyy ל- N ימים". A holder with
several licences repeats the same events on each row, so events are
de-duplicated by their exact text before counting. Unparseable fragments
are counted and disclosed.
"""
import re

import pandas as pd

TOP_SETTLEMENTS = 15
TOP_EMPLOYERS = 12
MIN_TYPE_N = 10
LRI, PDI = "⁦", "⁩"
UNKNOWN_DISTRICT = "לא צוין"
ROLE_PLURAL = {"קבלן": "קבלנים", "עובד אחראי": "עובדים אחראים", "סוקר": "סוקרים",
               "מפקח": "מפקחים"}
MATERIAL_DEFAULT = "ללא סיווג חומר"
CREW_BUCKETS = [("ללא עובד אחראי", 0, 0), ("אחד", 1, 1), ("שניים", 2, 2),
                ("שלושה–ארבעה", 3, 4), ("חמישה ומעלה", 5, None)]
SUSP_BUCKETS = [("עד חודש", 0, 31), ("חודש–שלושה", 32, 92), ("שלושה–שישה חודשים", 93, 183),
                ("מעל חצי שנה", 184, None)]
CONTACT_FIELDS = [("Phone", "טלפון"), ("AdditionalTelephone", "טלפון נוסף"), ("Fax", "פקס"),
                  ("Email", "דוא״ל"), ("Address", "כתובת")]
EVENT_RE = re.compile(r"^(.+?) עבור (.+?) מתאריך (\d{1,2}/\d{1,2}/\d{4})(?:\s*ל-\s*(\d+)\s*ימים)?")
QNAMES = ["ינו׳–מרץ", "אפר׳–יוני", "יולי–ספט׳", "אוק׳–דצמ׳"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def norm(s):
    return re.sub(r"\s+", " ", str(s).strip())


def _ranked(s):
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _split_type(t):
    m = re.match(r"^(.*?)\s*אסבסט\s*(.*)$", t)
    if not m:
        return t, MATERIAL_DEFAULT
    role = m.group(1).strip() or t
    mat = m.group(2).strip() or MATERIAL_DEFAULT
    return role, mat


def _plural(role):
    return ROLE_PLURAL.get(role, role)


def _bucket(v, buckets):
    for lab, lo, hi in buckets:
        if v >= lo and (hi is None or v <= hi):
            return lab
    return buckets[-1][0]


def _list_he(items):
    items = list(items)
    if len(items) == 1:
        return items[0]
    last = items[-1]
    joiner = " ו-" if last[:1].isdigit() else " ו"
    return ", ".join(items[:-1]) + joiner + last


# ---------------------------------------------------------------- insights

def insight_types(type_counts, total, mat_by_role):
    if type_counts.empty:
        return None
    lead, lv = type_counts.index[0], int(type_counts.iloc[0])
    s = f"סוג הרישיון הנפוץ ביותר הוא {lead}: {n(lv)} רישיונות ({pct(lv / total * 100)} מהמרשם)"
    c = mat_by_role.get("קבלן", {})
    cem, fri = c.get("צמנט", 0), c.get("פריך", 0)
    if cem and fri and fri * 2 <= cem:
        s += (f". רישיון קבלן לאסבסט פריך — המסוכן יותר לפירוק — מחזיקים רק {n(fri)} קבלנים, "
              f"לעומת {n(cem)} קבלני אסבסט צמנט")
    return s + "."


def insight_friable_geo(fri_by_dist, districts):
    if not districts or fri_by_dist is None:
        return None
    thin = [d for d in districts if fri_by_dist.get(d, 0) <= 1]
    if not thin or len(thin) == len(districts):
        return None
    parts = [f"{d} ({'אין אף אחד' if fri_by_dist.get(d, 0) == 0 else 'אחד בלבד'})" for d in thin]
    return ("קבלני אסבסט פריך מפוזרים בדלילות: במחוזות " if len(thin) > 1 else
            "קבלני אסבסט פריך מפוזרים בדלילות: במחוז ") + _list_he(parts) + " רשום לכל היותר קבלן פריך אחד."


def insight_district(dist_counts, total, n_unknown):
    known = dist_counts.drop(UNKNOWN_DISTRICT, errors="ignore")
    if len(known) < 2:
        return None
    (a, va), (b, vb) = list(known.items())[:2]
    s = (f"מחוז {a} מוביל במספר בעלי הרישיון: {n(va)} רישיונות ({pct(va / total * 100)}), "
         f"ואחריו מחוז {b} עם {n(vb)}")
    if n_unknown:
        s += f"; ל-{n(n_unknown)} רישיונות לא צוין מחוז"
    return s + "."


def insight_settlements(sett_counts, total_known):
    if len(sett_counts) < 10 or total_known == 0:
        return None
    top10 = int(sett_counts.head(10).sum())
    a, va = sett_counts.index[0], int(sett_counts.iloc[0])
    return (f"בעלי הרישיון פזורים ב-{n(len(sett_counts))} יישובים; {a} בראש עם {n(va)}, "
            f"ועשרת היישובים המובילים מרכזים יחד רק {pct(top10 / total_known * 100, 0)} מהרישיונות.")


def insight_expiry(exp, total):
    if exp.empty:
        return None
    years = exp.dt.year.value_counts().sort_index()
    q = exp.dt.to_period("Q").value_counts().sort_index()
    first_q = q.index[0]
    fy = int(years.index[0])
    fv = int(years.iloc[0])
    peak_y = int(_ranked(years).index[0])
    s = (f"הרישיון הקרוב לפקיעה במרשם פג ב-{exp.min().strftime('%d/%m/%Y')}; "
         f"{n(fv)} רישיונות ({pct(fv / total * 100)}) פגים עד סוף {fy}")
    if peak_y != fy:
        s += f", ושנת השיא בפקיעות היא {peak_y} עם {n(years[peak_y])} רישיונות"
    return s + "."


def insight_disc_rate(rate_rows, overall, n_disc):
    if n_disc == 0:
        return None
    s = f"ל-{n(n_disc)} רישיונות ({pct(overall * 100)}) רשום היבט משמעתי כלשהו"
    elig = [r for r in rate_rows if r["n"] >= MIN_TYPE_N]
    if elig:
        top = sorted(elig, key=lambda r: (-r["rate"], r["type"]))[0]
        if top["rate"] >= 1.5 * overall:
            s += (f"; השיעור הגבוה ביותר בקרב בעלי רישיון {top['type']} — {pct(top['rate'] * 100)} "
                  f"({n(top['k'])} מתוך {n(top['n'])})")
    return s + "."


def insight_disc_trend(ev_years, ev_types):
    tot = int(ev_years.sum())
    if tot < 10 or len(ev_years) < 3:
        return None
    peak = int(_ranked(ev_years).index[0])
    lead, lv = ev_types.index[0], int(ev_types.iloc[0])
    return (f"במרשם מתועדים {n(tot)} אירועים משמעתיים בין {int(ev_years.index.min())} ל-"
            f"{int(ev_years.index.max())}; שנת השיא היא {peak} עם {n(ev_years[peak])} אירועים. "
            f"הסנקציה הנפוצה היא {lead} ({n(lv)} אירועים, {pct(lv / tot * 100, 0)}).")


def insight_suspension(days):
    if len(days) < 5:
        return None
    med = float(days.median())
    over = int((days > 183).sum())
    s = (f"חציון משך התליית רישיון הוא {med:.0f} ימים; ההתליה הארוכה ביותר במרשם נמשכה "
         f"{n(days.max())} ימים")
    if over:
        s += f", ו-{n(over)} התליות נמשכו יותר מחצי שנה"
    return s + "."


def insight_sole(n_sole, n_contr):
    if n_contr == 0 or n_sole < 3:
        return None
    return (f"{n(n_sole)} מתוך {n(n_contr)} רישיונות הקבלן ({pct(n_sole / n_contr * 100, 0)}) "
            f"רשומים על שם אדם המחזיק גם ברישיון עובד אחראי — עסק שבעליו משמש גם כעובד האחראי "
            f"בו (לפי התאמת שם מדויקת).")


def insight_employers(emp_counts, n_workers, crew_zero):
    if emp_counts.empty or n_workers == 0:
        return None
    a, va = emp_counts.index[0], int(emp_counts.iloc[0])
    single = int((emp_counts == 1).sum())
    s = (f"{n(n_workers)} רישיונות עובד אחראי מחולקים בין {n(len(emp_counts))} מעסיקים; "
         f"ל-{n(single)} מהם עובד אחראי אחד בלבד. המעסיק הגדול ביותר, {a}, רשום עם {n(va)} עובדים אחראים")
    if crew_zero:
        s += f". ל-{n(crew_zero)} קבלנים מורשים לא רשום אף עובד אחראי"
    return s + "."


def insight_multi(n_holders, n_multi, total):
    if n_multi < 3:
        return None
    return (f"{n(total)} הרישיונות שייכים ל-{n(n_holders)} שמות שונים: {n(n_multi)} מחזיקים "
            f"ביותר מרישיון אחד — למשל קבלן שהוא גם העובד האחראי, או עובד אחראי אצל כמה קבלנים.")


def insight_unparsed(k):
    if k == 0:
        return None
    return (f"{n(k)} קטעים בשדה ההיבטים המשמעתיים לא נקראו כאירוע מתוארך (ככל הנראה טקסט "
            f"שנקטע במקור) ואינם נכללים בספירת האירועים.")


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["main"]
    total = len(raw)
    df = pd.DataFrame({
        "type": raw["LicenseType"].map(norm).replace("", "לא ידוע").values,
        "name": raw["Name"].map(norm).values,
        "settlement": raw["Settlement"].map(norm).values,
        "district": raw["District"].map(norm).replace("", UNKNOWN_DISTRICT).values,
        "exp": pd.to_datetime(raw["LicenseExpirationDate"].str.strip(), errors="coerce",
                              format="%d/%m/%Y").values,
        "disc": raw["DisciplinaryAspects"].map(norm).values,
        "employer": raw["EmployerContractor"].map(norm).values,
    })
    rm = df["type"].map(_split_type)
    df["role"] = [r for r, _ in rm]
    df["material"] = [m for _, m in rm]

    # ---- types
    type_counts = _ranked(df["type"].value_counts())
    role_counts = _ranked(df["role"].value_counts())
    roles = list(role_counts.index)
    mat_counts = _ranked(df["material"].value_counts())
    mats = list(mat_counts.index)
    rm_tab = df.groupby(["role", "material"]).size()
    mat_by_role = {r: {m: int(rm_tab.get((r, m), 0)) for m in mats} for r in roles}

    # ---- geography
    dist_counts = _ranked(df["district"].value_counts())
    n_unknown = int(dist_counts.get(UNKNOWN_DISTRICT, 0))
    districts = [d for d in dist_counts.index if d != UNKNOWN_DISTRICT]
    if n_unknown:
        districts_all = districts + [UNKNOWN_DISTRICT]
    else:
        districts_all = districts
    dr = df.groupby(["district", "role"]).size()
    contr_fri = df[(df["role"] == "קבלן") & (df["material"] == "פריך")]
    fri_by_dist = contr_fri["district"].value_counts().to_dict() if len(contr_fri) else None

    sett = _ranked(df.loc[df["settlement"] != "", "settlement"].value_counts())
    total_known_sett = int(sett.sum())
    top_sett = sett.head(TOP_SETTLEMENTS)
    other_sett = int(sett.iloc[TOP_SETTLEMENTS:].sum())

    # ---- expiry
    exp = df["exp"].dropna()
    n_bad_exp = int(df["exp"].isna().sum())
    qp = df.dropna(subset=["exp"]).copy()
    qp["q"] = qp["exp"].dt.year * 10 + (qp["exp"].dt.quarter)
    qs = sorted(qp["q"].unique().tolist())
    qlab = [f"{QNAMES[q % 10 - 1]} {q // 10}" for q in qs]
    qr = qp.groupby(["q", "role"]).size()
    exp_years = exp.dt.year.value_counts().sort_index()
    first_exp_year = int(exp_years.index[0]) if len(exp_years) else 0
    first_year_n = int(exp_years.iloc[0]) if len(exp_years) else 0

    # ---- disciplinary
    df["has_disc"] = df["disc"] != ""
    n_disc = int(df["has_disc"].sum())
    overall = n_disc / total if total else 0
    rate_rows = []
    for t in type_counts.index:
        sub = df[df["type"] == t]
        k = int(sub["has_disc"].sum())
        rate_rows.append({"type": t, "n": len(sub), "k": k, "rate": k / len(sub) if len(sub) else 0})
    rate_rows.sort(key=lambda r: (-r["rate"], r["type"]))

    events = set()
    unparsed = set()
    for s in df["disc"]:
        if not s:
            continue
        for part in s.split("<"):
            p = norm(part)
            if not p:
                continue
            if EVENT_RE.match(p):
                events.add(p)
            else:
                unparsed.add(p)
    ev_rows = []
    for e in sorted(events):
        m = EVENT_RE.match(e)
        d = pd.to_datetime(m.group(3), format="%d/%m/%Y", errors="coerce")
        if pd.isna(d):
            unparsed.add(e)
            continue
        ev_rows.append({"kind": m.group(1).strip(), "year": int(d.year),
                        "days": int(m.group(4)) if m.group(4) else None})
    ev = pd.DataFrame(ev_rows, columns=["kind", "year", "days"])
    ev_types = _ranked(ev["kind"].value_counts()) if len(ev) else pd.Series(dtype=int)
    kinds = list(ev_types.index)
    ev_years = ev["year"].value_counts().sort_index() if len(ev) else pd.Series(dtype=int)
    if len(ev_years):
        yrs = list(range(int(ev_years.index.min()), int(ev_years.index.max()) + 1))
        ev_years = ev_years.reindex(yrs, fill_value=0)
    else:
        yrs = []
    ky = ev.groupby(["year", "kind"]).size() if len(ev) else pd.Series(dtype=int)
    days = pd.Series([d for d in ev["days"] if d is not None and not pd.isna(d)], dtype=float)
    susp_b = (days.map(lambda v: _bucket(v, SUSP_BUCKETS)).value_counts()
              .reindex([b[0] for b in SUSP_BUCKETS], fill_value=0)) if len(days) else \
        pd.Series([0] * len(SUSP_BUCKETS), index=[b[0] for b in SUSP_BUCKETS])
    n_susp = int(ev_types.get("התליית רישיון", 0)) if len(ev_types) else 0

    # ---- contractors and their responsible workers
    contr = df[df["role"] == "קבלן"]
    n_contr = len(contr)
    workers = df[(df["role"] == "עובד אחראי")]
    worker_names = set(workers.loc[workers["name"] != "", "name"])
    n_sole = int(contr["name"].isin(worker_names).sum())
    emp = workers.loc[workers["employer"] != "", "employer"]
    emp_counts = _ranked(emp.value_counts())
    n_workers = int(len(emp))
    contr_names = sorted(set(contr.loc[contr["name"] != "", "name"]))
    crew = pd.Series([int(emp_counts.get(c, 0)) for c in contr_names], dtype=int)
    crew_b = (crew.map(lambda v: _bucket(v, CREW_BUCKETS)).value_counts()
              .reindex([b[0] for b in CREW_BUCKETS], fill_value=0)) if len(crew) else \
        pd.Series([0] * len(CREW_BUCKETS), index=[b[0] for b in CREW_BUCKETS])
    crew_zero = int((crew == 0).sum())
    top_emp = emp_counts.head(TOP_EMPLOYERS)
    emp_in_reg = [bool(e in set(contr_names)) for e in top_emp.index]

    # ---- holders
    named = df[df["name"] != ""]
    per_name = named.groupby("name").size()
    n_holders = int(len(per_name))
    n_multi = int((per_name > 1).sum())

    # ---- contact completeness (percent of licences with a value, per role)
    contact = []
    for col, lab in CONTACT_FIELDS:
        filled = raw[col].map(norm) != ""
        contact.append({"name": lab, "all": round(float(filled.mean() * 100), 1) if total else 0,
                        "by_role": [round(float(filled[(df["role"] == r).values].mean() * 100), 1)
                                    for r in roles]})

    # ---------------------------------------------------------- charts
    charts = {
        "types": {"roles": [_plural(r) for r in roles],
                  "series": [{"name": m, "data": [mat_by_role[r][m] or "-" for r in roles]} for m in mats]},
        "districts": {"names": districts_all,
                      "series": [{"name": _plural(r), "data": [int(dr.get((d, r), 0)) for d in districts_all]}
                                 for r in roles]},
        "settlements": {"names": list(top_sett.index), "values": [int(v) for v in top_sett.values]},
        "expiry": {"x": qlab,
                   "series": [{"name": _plural(r), "data": [int(qr.get((q, r), 0)) for q in qs]} for r in roles]},
        "disc_rate": {"names": [r["type"] for r in rate_rows],
                      "values": [round(r["rate"] * 100, 1) for r in rate_rows],
                      "overall": round(overall * 100, 1)},
        "disc_years": {"x": [str(y) for y in yrs],
                       "series": [{"name": k, "data": [int(ky.get((y, k), 0)) for y in yrs]} for k in kinds]},
        "susp": {"names": list(susp_b.index), "values": [int(v) for v in susp_b.values]},
        "employers": {"names": list(top_emp.index),
                      "values": [int(v) for v in top_emp.values], "in_reg": emp_in_reg},
        "crew": {"names": list(crew_b.index), "values": [int(v) for v in crew_b.values]},
        "contact": {"names": [c["name"] for c in contact], "roles": [_plural(r) for r in roles],
                    "all": [c["all"] for c in contact],
                    "by_role": [[c["by_role"][i] for c in contact] for i in range(len(roles))]},
    }

    rules = [
        ("types", insight_types(type_counts, total, mat_by_role)),
        ("district", insight_district(dist_counts, total, n_unknown)),
        ("friable_geo", insight_friable_geo(fri_by_dist, districts)),
        ("settlements", insight_settlements(sett, total_known_sett)),
        ("expiry", insight_expiry(exp, total)),
        ("disc_rate", insight_disc_rate(rate_rows, overall, n_disc)),
        ("disc_trend", insight_disc_trend(ev_years, ev_types)),
        ("suspension", insight_suspension(days)),
        ("sole", insight_sole(n_sole, n_contr)),
        ("employers", insight_employers(emp_counts, n_workers, crew_zero)),
        ("multi", insight_multi(n_holders, n_multi, total)),
        ("unparsed", insight_unparsed(len(unparsed))),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    n_fri_contr = int(mat_by_role.get("קבלן", {}).get("פריך", 0))
    exp_share = first_year_n / total if total else 0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "contractors": {"value": n_contr, "display": n(n_contr), "tone": "brand"},
        "disc": {"value": round(overall * 100, 1), "display": f"{overall * 100:.1f}%",
                 "tone": "danger" if overall >= 0.25 else ("warn" if overall >= 0.1 else "info")},
        "expiring": {"value": first_year_n, "display": n(first_year_n),
                     "tone": "warn" if exp_share >= 0.05 else "brand"},
    }

    role_txt = _list_he([f"{n(role_counts[r])} {_plural(r)}" for r in roles])
    peak_q = qlab[int(pd.Series([sum(int(qr.get((q, r), 0)) for r in roles) for q in qs]).idxmax())] if qs else ""
    labels = {
        "lede": (f"מרשם בעלי הרישיונות לעבודה עם אסבסט של המשרד להגנת הסביבה: {n(total)} רישיונות "
                 f"בתוקף — {role_txt}. המרשם כולל רק רישיונות בתוקף, ולכן הוא תמונת מצב: "
                 f"הרישיון הקרוב לפקיעה פג ב-{exp.min().strftime('%d/%m/%Y') if len(exp) else '—'}. "
                 f"מספרי רישיון ופרטי קשר אינם מוצגים בעמוד; היבטים משמעתיים מוצגים במצטבר בלבד."),
        "total_kpi": "רישיונות בתוקף במרשם",
        "contr_kpi": f"רישיונות קבלן אסבסט (מהם {n(n_fri_contr)} לאסבסט פריך)",
        "disc_kpi": f"שיעור הרישיונות עם היבט משמעתי רשום ({n(n_disc)} רישיונות)",
        "exp_kpi": f"רישיונות שתוקפם פג עד סוף {first_exp_year} ({exp_share * 100:.1f}%)",
        "types_note": ("מספר הרישיונות לפי תפקיד ולפי סוג האסבסט: אסבסט צמנט (לוחות וצנרת) "
                       "או אסבסט פריך — המתפורר בקלות ומסוכן יותר, ודורש רישיון נפרד."),
        "types_aria": f"גרף עמודות מוערמות: רישיונות לפי תפקיד וסוג אסבסט; {_plural(roles[0])} בראש עם {n(role_counts.iloc[0])}.",
        "types_caption": "רישיונות לפי סוג רישיון.",
        "districts_note": ("רישיונות לפי מחוז המען הרשום, בחלוקה לתפקידים."
                           + (f" ל-{n(n_unknown)} רישיונות לא צוין מחוז." if n_unknown else "")),
        "districts_aria": f"גרף עמודות מוערמות אופקי: רישיונות לפי מחוז ותפקיד; מחוז {districts[0] if districts else ''} בראש.",
        "districts_caption": "רישיונות לפי מחוז ותפקיד.",
        "sett_note": (f"{TOP_SETTLEMENTS} היישובים עם מספר הרישיונות הגדול ביותר, מתוך {n(len(sett))} יישובים"
                      + ("; בטבלה מופיע גם סך היישובים האחרים." if other_sett else ".")),
        "sett_aria": (f"תרשים עמודות אופקי: יישובים לפי מספר רישיונות; {sett.index[0]} בראש עם {n(sett.iloc[0])}."
                      if len(sett) else "תרשים עמודות אופקי: יישובים לפי מספר רישיונות."),
        "sett_caption": "רישיונות לפי יישוב.",
        "expiry_note": (f"מתי פג תוקפם של הרישיונות שבמרשם, לפי רבעון ותפקיד. הרבעון העמוס ביותר: {peak_q}."
                        + (f" {n(n_bad_exp)} רישיונות ללא תאריך תוקף תקין אינם מוצגים." if n_bad_exp else "")),
        "expiry_aria": f"גרף עמודות מוערמות: רישיונות לפי רבעון פקיעת התוקף, {qlab[0] if qlab else ''} עד {qlab[-1] if qlab else ''}.",
        "expiry_caption": "רישיונות לפי רבעון פקיעת התוקף ותפקיד.",
        "rate_note": (f"שיעור הרישיונות שרשום להם היבט משמעתי כלשהו (התליה, נזיפה, התראה), לפי סוג הרישיון. "
                      f"הקו המקווקו — השיעור בכלל המרשם, {overall * 100:.1f}%."),
        "rate_aria": f"תרשים עמודות אופקי: שיעור רישיונות עם היבט משמעתי לפי סוג רישיון; ממוצע {overall * 100:.1f}%.",
        "rate_caption": "רישיונות עם היבט משמעתי לפי סוג רישיון.",
        "years_note": ("אירועים משמעתיים לפי שנת האירוע וסוג הסנקציה. אירוע של בעל כמה רישיונות "
                       "נספר פעם אחת."),
        "years_aria": (f"גרף עמודות מוערמות: אירועים משמעתיים לפי שנה, {yrs[0]} עד {yrs[-1]}."
                       if yrs else "גרף עמודות מוערמות: אירועים משמעתיים לפי שנה."),
        "years_caption": "אירועים משמעתיים לפי שנה וסוג.",
        "susp_note": f"משך {n(len(days))} התליות הרישיון שמשכן מצוין במרשם.",
        "susp_aria": f"תרשים עמודות: התליות רישיון לפי משך, חציון {float(days.median()) if len(days) else 0:.0f} ימים.",
        "susp_caption": "התליות רישיון לפי משך.",
        "emp_note": (f"{TOP_EMPLOYERS} המעסיקים שרשומים אצלם הכי הרבה רישיונות עובד אחראי. "
                     "עמודה כהה — המעסיק מופיע במרשם גם כקבלן מורשה (לפי שם זהה)."),
        "emp_aria": (f"תרשים עמודות אופקי: מעסיקים לפי מספר עובדים אחראים; {top_emp.index[0]} בראש עם {n(top_emp.iloc[0])}."
                     if len(top_emp) else "תרשים עמודות אופקי: מעסיקים לפי מספר עובדים אחראים."),
        "emp_caption": "מעסיקים לפי מספר רישיונות עובד אחראי.",
        "crew_note": (f"לכמה עובדים אחראים רשומים אצל כל אחד מ-{n(len(contr_names))} הקבלנים המורשים "
                      "(לפי התאמת שם המעסיק לשם הקבלן)."),
        "crew_aria": f"תרשים עמודות: קבלנים לפי מספר העובדים האחראים הרשומים אצלם; {n(crew_zero)} ללא עובד אחראי.",
        "crew_caption": "קבלנים לפי מספר עובדים אחראים.",
        "contact_note": ("איזה חלק מהרישיונות כולל כל סוג של פרט קשר, לפי תפקיד. "
                         "הפרטים עצמם אינם מוצגים בעמוד."),
        "contact_aria": "גרף עמודות: שיעור הרישיונות עם כל סוג פרט קשר, לפי תפקיד.",
        "contact_caption": "שיעור הרישיונות עם פרט קשר, לפי תפקיד.",
    }
    tables = {
        "types": [{"type": t, "count": n(v), "share": f"{v / total * 100:.1f}%"} for t, v in type_counts.items()],
        "districts": [{"name": d, "vals": [n(dr.get((d, r), 0)) for r in roles],
                       "total": n(dist_counts[d])} for d in districts_all],
        "role_cols": [_plural(r) for r in roles],
        "settlements": [{"name": a, "count": n(b)} for a, b in
                        zip(list(top_sett.index) + (["יישובים אחרים"] if other_sett else []),
                            [int(v) for v in top_sett.values] + ([other_sett] if other_sett else []))],
        "expiry": [{"name": lab, "vals": [n(qr.get((q, r), 0)) for r in roles],
                    "total": n(sum(int(qr.get((q, r), 0)) for r in roles))} for q, lab in zip(qs, qlab)],
        "disc_rate": [{"type": r["type"], "k": n(r["k"]), "n": n(r["n"]), "rate": f"{r['rate'] * 100:.1f}%"}
                      for r in rate_rows],
        "kind_cols": kinds,
        "disc_years": [{"year": str(y), "vals": [n(ky.get((y, k), 0)) for k in kinds],
                        "total": n(ev_years[y])} for y in yrs],
        "susp": [{"name": a, "count": n(b)} for a, b in susp_b.items()],
        "employers": [{"name": a, "count": n(b), "reg": "כן" if f else "לא"}
                      for (a, b), f in zip(top_emp.items(), emp_in_reg)],
        "crew": [{"name": a, "count": n(b)} for a, b in crew_b.items()],
        "contact": [{"name": c["name"], "all": f"{c['all']:.1f}%",
                     "vals": [f"{v:.1f}%" for v in c["by_role"]]} for c in contact],
    }

    return {
        "agent_data": {
            "summary_he": (f"מרשם העוסקים באסבסט: {n(total)} רישיונות בתוקף — {role_txt} — "
                           f"בחלוקה לפי סוג אסבסט, מחוז ויישוב, מועד פקיעת התוקף והיבטים משמעתיים."),
            "dataset_kind": "registry",
            "related_ids": ["7f1a7496-c3d9-498f-ade2-2ebb8e602916",
                            "33b03ff6-a58e-49bf-840e-a17a894c9885",
                            "04931a88-336c-4d95-8a13-9dc631c3e2d1"],
            "suggested_tags": ["אסבסט", "רישוי מקצועי", "קבלנים", "בטיחות סביבתית", "פיקוח",
                               "המשרד להגנת הסביבה"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"has_events": bool(yrs), "has_susp": bool(len(days)),
                  "has_workers": bool(n_workers)},
    }
