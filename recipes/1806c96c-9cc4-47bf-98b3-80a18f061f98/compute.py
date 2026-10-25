"""מאגר עורכי פטנטים — the Patent Office register of licensed patent attorneys.

One row per attorney on the register (~580): licence number, title
(מר / גב / עו"ד — the gendered titles are unreliable in the source, so only
the advocate title is read), Hebrew + English names, year entered on the
register, the last year for which the annual fee was paid, e-mail, postal
address and settlement (Hebrew, with an English twin).

The register lists current members only, so registration-year counts
describe who is on the register today, not historic intake. "Now" is the
latest registration year in the data — never the wall clock. The current
fee cycle is the most common last-paid year (ties to the later year), so
the page follows the data as a new cycle starts filling.

Licence numbers, names, e-mail addresses and postal addresses never reach
the page. E-mail is read only for its domain: a domain shared by at least
ORG_MIN attorneys that is not a public webmail/ISP provider is shown as an
organisation (patent firms, in-house IP departments, the ministry itself).
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
TOP_CITIES = 12
TOP_ORGS = 15
ORG_MIN = 3
SENIORITY = [(0, 4), (5, 9), (10, 14), (15, 19), (20, 24), (25, 29), (30, None)]
RECENT_YEARS = 5
PRIOR_YEARS = 10
UNKNOWN_CITY = {"", "ללא ישוב"}
CITY_ALIAS = {"תל אביב": "תל אביב-יפו", "תל אביב יפו": "תל אביב-יפו",
              "מודיעין": "מודיעין-מכבים-רעות", "מכבים רעות": "מודיעין-מכבים-רעות"}
WEBMAIL = re.compile(
    r"^(g(oogle)?mail|yahoo|hotmail|outlook|live|msn|aol|icloud|me|mac|walla|"
    r"netvision|bezeqint|zahav|012|013|013net|barak|smile|inter|actcom|"
    r"proton(mail)?|gmx|mail|ymail|nana|nana10|internet-zahav)\.")
ST_CUR, ST_ONE, ST_OLD, ST_UNK = "שולם למחזור הנוכחי", "פיגור של שנה", "פיגור של שנתיים ומעלה", "לא צוין"
ST_COLOR = {ST_CUR: "#198754", ST_ONE: "#ffc107", ST_OLD: "#dc3545", ST_UNK: "#6c757d"}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _city_display(s):
    s = re.sub(r"\s+", " ", s.strip())
    s = re.sub(r"\s*-\s*", "-", s)
    return CITY_ALIAS.get(s, s)


def _city_key(s):
    k = re.sub(r"[\s\-–\"'״׳~]", "", s)
    return k.replace("וו", "ו").replace("יי", "י")


def _cities(df):
    he = df["יישוב"].map(_city_display)
    en = df["ישוב באנגלית"].str.strip().str.upper().map(lambda s: re.sub(r"\s+", " ", s))
    known = ~he.isin(UNKNOWN_CITY)
    key = he.map(_city_key)
    variants = (pd.DataFrame({"key": key[known], "city": he[known]})
                .groupby(["key", "city"]).size().reset_index(name="n")
                .sort_values(["key", "n", "city"], ascending=[True, False, True]))
    canon = variants.drop_duplicates("key").set_index("key")["city"]
    city = key.map(canon).where(known, "")
    # Hebrew settlement missing: borrow it from rows that carry the same
    # English name with a Hebrew one (most common pairing, ties by name).
    pairs = (pd.DataFrame({"en": en[known & (en != "")], "city": city[known & (en != "")]})
             .groupby(["en", "city"]).size().reset_index(name="n")
             .sort_values(["en", "n", "city"], ascending=[True, False, True])
             .drop_duplicates("en").set_index("en")["city"])
    fill = (~known) & (en != "")
    city = city.where(~fill, en.map(pairs).fillna(""))
    return city, int((fill & (city != "")).sum())


def _prepare(df):
    out = pd.DataFrame({
        "year": pd.to_numeric(df["שנת רישום בפנקס"].str.strip(), errors="coerce"),
        "fee": pd.to_numeric(df["תשלום לשנה"].str.strip(), errors="coerce"),
        "lawyer": df["תואר"].str.strip().str.startswith("עו"),
        "title_known": df["תואר"].str.strip() != "",
    })
    out.loc[(out["year"] < 1900) | (out["year"] > 2100), "year"] = float("nan")
    out.loc[(out["fee"] < 1900) | (out["fee"] > 2100), "fee"] = float("nan")
    dom = df["כתובת מייל"].str.strip().str.lower().str.extract(r"@([a-z0-9.\-]+\.[a-z]{2,})$")[0]
    out["domain"] = dom.fillna("")
    out["webmail"] = out["domain"].map(lambda d: bool(d) and bool(WEBMAIL.match(d)))
    out["city"], filled = _cities(df)
    return out, filled


def _fee_status(fee, cycle):
    if pd.isna(fee):
        return ST_UNK
    if fee >= cycle:
        return ST_CUR
    return ST_ONE if fee == cycle - 1 else ST_OLD


def insight_fees(st, total, cycle):
    cur = st.get(ST_CUR, 0)
    if total == 0 or cur == 0:
        return None
    s = (f"{pct(cur / total * 100)} מעורכי הפטנטים במאגר ({n(cur)}) שילמו את האגרה השנתית "
         f"לשנת {cycle} או לשנה מאוחרת יותר")
    tail = []
    if st.get(ST_ONE, 0):
        tail.append(f"{n(st[ST_ONE])} שילמו לאחרונה לשנת {cycle - 1}")
    if st.get(ST_OLD, 0):
        tail.append(f"{n(st[ST_OLD])} שילמו לאחרונה לשנת {cycle - 2} או לפניה")
    if st.get(ST_UNK, 0):
        tail.append(f"ל-{n(st[ST_UNK])} לא רשומה שנת תשלום")
    if tail:
        last = tail[-1]
        last = ("ו-" if last[0].isdigit() else "ו") + last
        s += "; " + ", ".join(tail[:-1] + [last]) if len(tail) > 1 else "; " + tail[0]
    return s + "."


def insight_pace(per_year, ref):
    recent = per_year[(per_year.index > ref - RECENT_YEARS) & (per_year.index <= ref)]
    prior = per_year[(per_year.index > ref - RECENT_YEARS - PRIOR_YEARS)
                     & (per_year.index <= ref - RECENT_YEARS)]
    if prior.sum() < 30:
        return None
    r, p = recent.sum() / RECENT_YEARS, prior.sum() / PRIOR_YEARS
    chg = r / p - 1
    a0, a1 = ref - RECENT_YEARS - PRIOR_YEARS + 1, ref - RECENT_YEARS
    head = (f"בקרב הרשומים כיום, {n(recent.sum())} נכנסו לפנקס ב-{ref - RECENT_YEARS + 1}–{ref} — "
            f"ממוצע של {r:.1f} בשנה")
    if abs(chg) < 0.15:
        return head + f", בדומה לממוצע של {p:.1f} בשנה ב-{a0}–{a1}."
    word = "ירידה" if chg < 0 else "עלייה"
    return head + f", {word} של {pct(abs(chg) * 100, 0)} לעומת {p:.1f} בשנה ב-{a0}–{a1}."


def insight_peak(per_year):
    if len(per_year) < 10:
        return None
    peak = int(per_year.idxmax())
    pv = int(per_year[peak])
    med = per_year[per_year > 0].median()
    if pv < 1.5 * med:
        return None
    return (f"{peak} היא שנת הרישום הבולטת בקרב הרשומים כיום: {n(pv)} עורכי פטנטים, "
            f"פי {pv / med:.1f} מהחציון השנתי ({med:.0f}).")


def insight_seniority(sen):
    s = sen.dropna()
    if len(s) < 50:
        return None
    return (f"הוותק החציוני בפנקס הוא {int(s.median())} שנים; {pct((s < 10).mean() * 100, 0)} "
            f"נרשמו בעשור האחרון, ו-{pct((s >= 20).mean() * 100, 0)} רשומים 20 שנה ומעלה.")


def insight_cohort(df, cycle):
    d = df.dropna(subset=["year"])
    if d.empty:
        return None
    ref = int(d["year"].max())
    new = d[d["year"] > ref - 10]
    old = d[d["year"] <= ref - 20]
    if len(new) < 30 or len(old) < 30:
        return None
    a1 = (new["status"] == ST_CUR).mean() * 100
    a0 = (old["status"] == ST_CUR).mean() * 100
    if abs(a1 - a0) < 8:
        return None
    lead, lag = ("שנרשמו בעשור האחרון", f"שנרשמו עד {ref - 20}") if a1 > a0 else \
                (f"שנרשמו עד {ref - 20}", "שנרשמו בעשור האחרון")
    hi, lo = max(a1, a0), min(a1, a0)
    return (f"מבין עורכי הפטנטים {lead}, {pct(hi, 0)} שילמו את אגרת {cycle}, לעומת "
            f"{pct(lo, 0)} מבין אלה {lag}.")


def insight_cities(cities, known_total):
    if known_total == 0 or len(cities) < 5:
        return None
    top, v = cities.index[0], int(cities.iloc[0])
    if v / known_total < 0.1:
        return None
    top3 = cities.head(3)
    return (f"{top} מובילה עם {n(v)} עורכי פטנטים ({pct(v / known_total * 100)}); "
            f"יחד עם {top3.index[1]} ו{top3.index[2]} מרכזות שלוש הערים "
            f"{pct(top3.sum() / known_total * 100)} מהרשומים שישובם ידוע.")


def insight_orgs(orgs, with_email, total):
    if len(orgs) < 3 or with_email == 0:
        return None
    a, va = orgs.index[0], int(orgs.iloc[0])
    in_orgs = int(orgs.sum())
    return (f"{n(in_orgs)} עורכי פטנטים ({pct(in_orgs / total * 100)}) משתמשים בדומיין דוא״ל "
            f"ארגוני המשותף ל-{ORG_MIN} רשומים לפחות — {n(len(orgs))} ארגונים; "
            f"הגדול שבהם הוא {LRI}{a}{PDI} עם {n(va)} עורכי פטנטים.")


def insight_lawyers(df):
    t = df[df["title_known"]]
    if len(t) < 50:
        return None
    k = int(t["lawyer"].sum())
    if k == 0:
        return None
    return (f"{pct(k / len(t) * 100)} מעורכי הפטנטים שתוארם מצוין ({n(k)} מתוך {n(len(t))}) "
            f"רשומים בתואר עורך דין.")


def compute(frames):
    df, filled = _prepare(frames["attorneys"])
    total = len(df)

    fees = df["fee"].dropna().astype(int)
    fee_counts = fees.value_counts()
    cycle = int(fee_counts.sort_index(ascending=False).idxmax()) if len(fee_counts) else 0
    df["status"] = [_fee_status(f, cycle) for f in df["fee"]]
    statuses = [s for s in (ST_CUR, ST_ONE, ST_OLD, ST_UNK) if (df["status"] == s).any()]
    st = df["status"].value_counts().reindex(statuses).fillna(0).astype(int)
    cur = int(st.get(ST_CUR, 0))

    dated = df.dropna(subset=["year"]).copy()
    dated["year"] = dated["year"].astype(int)
    ref = int(dated["year"].max())
    first = int(dated["year"].min())
    years = list(range(first, ref + 1))
    by_year = (dated.groupby(["year", "status"]).size().unstack(fill_value=0)
               .reindex(index=years, columns=statuses, fill_value=0))
    per_year = by_year.sum(axis=1)
    no_year = total - len(dated)

    sen = ref - dated["year"]
    sen_rows = []
    for lo, hi in SENIORITY:
        m = sen >= lo
        if hi is not None:
            m &= sen <= hi
        lab = f"{lo} ומעלה" if hi is None else (f"עד {hi}" if lo == 0 else f"{lo}–{hi}")
        sen_rows.append((lab, int(m.sum())))
    median_sen = int(sen.median()) if len(sen) else 0

    # Decade cohorts × fee status (share).
    dec = (dated["year"] // 10 * 10)
    coh = dated.groupby([dec, "status"]).size().unstack(fill_value=0).reindex(columns=statuses, fill_value=0)
    coh = coh.sort_index()
    coh_labels = [f"שנות ה-{int(d)}" for d in coh.index]
    coh_law = dated.groupby(dec)["lawyer"].sum().reindex(coh.index).fillna(0).astype(int)

    # Last fee year paid.
    fy = sorted(fee_counts.index)
    fee_x = [str(y) for y in fy] + ([ST_UNK] if df["fee"].isna().any() else [])
    fee_v = [int(fee_counts[y]) for y in fy] + ([int(df["fee"].isna().sum())] if df["fee"].isna().any() else [])
    fee_c = [ST_COLOR[_fee_status(y, cycle)] for y in fy] + ([ST_COLOR[ST_UNK]] if df["fee"].isna().any() else [])

    # Settlements.
    known = df[df["city"] != ""]
    cities = _sorted_counts(known["city"])
    top_c = list(cities.head(TOP_CITIES).index)
    rest_c = int(cities.iloc[TOP_CITIES:].sum())
    unknown_city = total - len(known)

    # Organisations by e-mail domain.
    with_email = int((df["domain"] != "").sum())
    org_rows = df[(df["domain"] != "") & ~df["webmail"]]
    dcounts = _sorted_counts(org_rows["domain"])
    orgs = dcounts[dcounts >= ORG_MIN]
    top_o = orgs.head(TOP_ORGS)
    webmail_n = int(df["webmail"].sum())
    org_email_n = int(len(org_rows))
    no_email = total - with_email

    # Titles.
    law_n = int(df["lawyer"].sum())
    title_known = int(df["title_known"].sum())
    titles = [("עורך דין", law_n), ("תואר אחר", title_known - law_n), ("לא צוין", total - title_known)]
    titles = [(k, v, c) for (k, v), c in zip(titles, ("#0068f5", "#6c9be8", "#6c757d")) if v > 0]
    contact = [("דומיין ארגוני", org_email_n), ("דוא״ל פרטי (ספק ציבורי)", webmail_n),
               ("ללא דוא״ל", no_email)]
    contact = [(k, v, c) for (k, v), c in zip(contact, ("#0068f5", "#0dcaf0", "#6c757d")) if v > 0]

    charts = {
        "years": {"x": [str(y) for y in years],
                  "series": [{"name": s, "color": ST_COLOR[s],
                              "data": [int(v) for v in by_year[s]]} for s in statuses]},
        "seniority": {"names": [k for k, _ in sen_rows], "values": [v for _, v in sen_rows]},
        "cohort": {"x": coh_labels,
                   "series": [{"name": s, "color": ST_COLOR[s],
                               "data": [round(float(coh.loc[d, s] / coh.loc[d].sum() * 100), 1)
                                        for d in coh.index]} for s in statuses]},
        "fees": {"x": fee_x, "values": fee_v, "colors": fee_c},
        "cities": {"names": top_c, "values": [int(cities[c]) for c in top_c]},
        "orgs": {"names": list(top_o.index), "values": [int(v) for v in top_o.values]},
        "titles": {"names": [t[0] for t in titles], "values": [t[1] for t in titles],
                   "colors": [t[2] for t in titles]},
        "contact": {"names": [t[0] for t in contact], "values": [t[1] for t in contact],
                    "colors": [t[2] for t in contact]},
    }

    rules = [
        ("fees", insight_fees(st, total, cycle)),
        ("pace", insight_pace(per_year, ref)),
        ("peak", insight_peak(per_year)),
        ("seniority", insight_seniority(sen)),
        ("cohort", insight_cohort(df, cycle)),
        ("cities", insight_cities(cities, len(known))),
        ("orgs", insight_orgs(orgs, with_email, total)),
        ("lawyers", insight_lawyers(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    cur_share = cur / total * 100 if total else 0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "current": {"value": round(cur_share, 1), "display": f"{cur_share:.1f}%",
                    "tone": "ok" if cur_share >= 85 else ("warn" if cur_share >= 60 else "danger")},
        "seniority": {"value": median_sen, "display": n(median_sen), "tone": "brand"},
        "cities": {"value": int(cities.size), "display": n(cities.size), "tone": "brand"},
    }

    peak_year = int(per_year.idxmax())
    labels = {
        "lede": (f"פנקס עורכי הפטנטים של רשות הפטנטים במשרד המשפטים: {n(total)} עורכי פטנטים "
                 f"רשומים מ-{n(cities.size)} ישובים. הוותיקים שבהם נרשמו ב-{first}, האחרונים "
                 f"ב-{ref}; {n(cur)} שילמו את האגרה השנתית לשנת {cycle}."),
        "current_kpi": f"שילמו אגרה שנתית לשנת {cycle} ואילך",
        "seniority_kpi": f"ותק חציוני בפנקס (שנים, נכון ל-{ref})",
        "years_note": (f"מספר עורכי הפטנטים הרשומים כיום לפי שנת הרישום בפנקס, לפי מצב תשלום "
                       f"האגרה. המאגר כולל רק את הרשומים היום — מי שנגרע מהפנקס אינו מופיע, ולכן "
                       f"השנים המוקדמות דלילות."
                       + (f" ל-{n(no_year)} רשומים אין שנת רישום." if no_year else "")),
        "years_aria": (f"גרף עמודות מוערמות: עורכי פטנטים לפי שנת רישום, {first} עד {ref}, "
                       f"לפי מצב תשלום האגרה; שיא ב-{peak_year}."),
        "seniority_note": f"שנים מאז הרישום בפנקס, נכון לשנת הרישום האחרונה במאגר ({ref}).",
        "seniority_aria": f"תרשים עמודות: עורכי פטנטים לפי ותק בפנקס, חציון {median_sen} שנים.",
        "seniority_caption": "מספר עורכי פטנטים לפי קבוצת ותק בשנים.",
        "cohort_note": (f"שיעור מצבי התשלום של האגרה השנתית בכל עשור רישום. המחזור הנוכחי — "
                        f"{cycle} — הוא השנה האחרונה ששולמה בידי מרבית הרשומים."),
        "cohort_aria": "תרשים עמודות מוערמות באחוזים: מצב תשלום האגרה לפי עשור הרישום בפנקס.",
        "cohort_caption": "מספר הרשומים, הרשומים בתואר עורך דין ושיעור כל מצב תשלום, לפי עשור הרישום.",
        "fees_note": (f"השנה האחרונה שעבורה שולמה האגרה השנתית. ירוק — המחזור הנוכחי ({cycle}) "
                      f"ואילך; צהוב — פיגור של שנה; אדום — פיגור של שנתיים ומעלה."),
        "fees_aria": (f"תרשים עמודות: עורכי פטנטים לפי השנה האחרונה ששולמה, {n(cur)} שילמו "
                      f"לשנת {cycle} ואילך."),
        "fees_caption": "מספר עורכי פטנטים לפי השנה האחרונה שעבורה שולמה האגרה.",
        "cities_note": (f"{TOP_CITIES} הישובים עם מספר עורכי הפטנטים הגדול ביותר, לפי כתובת "
                        f"ההתקשרות הרשומה. איות שמות הישובים אוחד (למשל תל אביב / תל אביב יפו)"
                        + (f"; לרשומים ללא ישוב בעברית הושלם הישוב משמו באנגלית ({n(filled)})" if filled else "")
                        + (f"; {n(unknown_city)} רשומים ללא ישוב אינם נכללים." if unknown_city else ".")
                        + (f" עוד {n(rest_c)} עורכי פטנטים בישובים אחרים." if rest_c else "")),
        "cities_aria": (f"תרשים עמודות אופקי: {TOP_CITIES} הישובים המובילים — {top_c[0]} בראש "
                        f"עם {n(cities.iloc[0])} עורכי פטנטים." if top_c else "תרשים ישובים."),
        "cities_caption": f"עורכי פטנטים לפי ישוב ({TOP_CITIES} המובילים).",
        "orgs_note": (f"ארגונים לפי דומיין כתובת הדוא״ל הרשומה — משרדי פטנטים, מחלקות קניין "
                      f"רוחני בחברות וגופים ציבוריים. מוצגים דומיינים המשותפים ל-{ORG_MIN} עורכי "
                      f"פטנטים לפחות ({TOP_ORGS} הגדולים); ספקי דוא״ל ציבוריים אינם נכללים."),
        "orgs_aria": (f"תרשים עמודות אופקי: ארגונים לפי דומיין דוא״ל, {orgs.index[0]} בראש עם "
                      f"{n(orgs.iloc[0])} עורכי פטנטים." if len(orgs) else "תרשים ארגונים."),
        "orgs_caption": "מספר עורכי פטנטים לפי דומיין הדוא״ל הארגוני.",
        "titles_note": "התואר הרשום לצד השם. התארים מר/גב׳ אינם עקביים במקור ולכן מקובצים יחד.",
        "titles_aria": (f"תרשים טבעת: {n(law_n)} עורכי פטנטים בתואר עורך דין מתוך {n(total)}."),
        "titles_caption": "מספר עורכי פטנטים לפי תואר.",
        "contact_note": "סוג כתובת הדוא״ל הרשומה: דומיין של ארגון, ספק דוא״ל ציבורי, או ללא כתובת.",
        "contact_aria": (f"תרשים טבעת: {n(org_email_n)} עם דוא״ל ארגוני, {n(webmail_n)} עם ספק "
                         f"ציבורי, {n(no_email)} ללא דוא״ל."),
        "contact_caption": "מספר עורכי פטנטים לפי סוג כתובת הדוא״ל.",
    }
    tables = {
        "status_cols": statuses,
        "seniority": [{"bucket": k, "count": n(v)} for k, v in sen_rows],
        "cohort": [{"name": lab, "total": n(coh.loc[d].sum()), "law": n(coh_law[d]),
                    "shares": [f"{coh.loc[d, s] / coh.loc[d].sum() * 100:.1f}%" for s in statuses]}
                   for d, lab in zip(coh.index, coh_labels)],
        "fees": [{"name": x, "count": n(v)} for x, v in zip(fee_x, fee_v)],
        "cities": [{"name": c, "count": n(cities[c])} for c in top_c],
        "orgs": [{"name": k, "count": n(v)} for k, v in top_o.items()],
        "titles": [{"name": k, "count": n(v), "share": f"{v / total * 100:.1f}%"} for k, v, _ in titles],
        "contact": [{"name": k, "count": n(v), "share": f"{v / total * 100:.1f}%"} for k, v, _ in contact],
    }

    return {
        "agent_data": {
            "summary_he": (f"פנקס עורכי הפטנטים המורשים בישראל: {n(total)} רשומים מ-{n(cities.size)} "
                           f"ישובים — שנת רישום, תשלום אגרה שנתית, ישוב וארגון, {first}–{ref}."),
            "dataset_kind": "registry",
            "related_ids": ["029b6747-551b-47ad-9a05-ef7f7868fcd0",
                            "247efc75-31f2-4b19-bd4e-e670b1bf2783",
                            "ebf84395-4784-4438-b9ca-08caf263beaf",
                            "6e207fff-abef-4f4d-aac7-61e669ba9ad5",
                            "713440a1-9963-4548-a7d9-9d9c9da54f62"],
            "suggested_tags": ["עורכי פטנטים", "פטנטים", "קניין רוחני", "רישוי מקצועי",
                               "משרד המשפטים"],
            "temporal_coverage": f"{first}/{ref}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
