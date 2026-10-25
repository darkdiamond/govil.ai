"""מינהל יהלומים — the Diamond Administration register of diamond dealers.

One row per licence (~7.5k): the holder's name, the licence status (active /
inactive / in registration) and the licence type (trade / manufacturer /
jeweller). There are no dates, places or ids, so the page is about the
register's composition: status by licence type, and what the holder's NAME
says — its legal form (Ltd company, partnership, or no legal form, which is
mostly individuals) and its trade vocabulary.

Holders that are individuals are never named on the page (a few names carry
passport numbers in the source). The only names rendered are businesses
(companies/partnerships) that are currently in registration. Name-derived
dimensions are text heuristics and the page says so.
"""
import re

import pandas as pd

ACTIVE = "פעיל"
INACTIVE = "לא פעיל"
PENDING = "בהליך רישום"
STATUS_ORDER = [ACTIVE, INACTIVE, PENDING]
STATUS_COLOR = {ACTIVE: "#198754", INACTIVE: "#6c757d", PENDING: "#0068f5"}
STATUS_PLURAL = {INACTIVE: "לא פעילים"}
TYPE_ORDER = ["סחר", "יצרן", "צורף"]
TYPE_PLURAL = {"סחר": "סוחרים", "יצרן": "יצרנים", "צורף": "צורפים"}

F_CO, F_PA, F_BIZ, F_PER = "חברה בע״מ", "שותפות", "שם מסחרי ללא צורה משפטית", "שם אישי"
FORMS = [F_CO, F_PA, F_BIZ, F_PER]
CO_RE = r'בע["\'״׳]?\s?מ|\bבעמ\b'
PA_RE = r"ש\.ר|שותפות|ושות"

# Trade vocabulary in names: label -> regex (mapping only; counts come from the data).
WORDS = [
    ("יהלום / יהלומי", r"יהלומ"),
    ("דיאמונד (תעתיק לועזי)", r"דיא?י?מונד|דיימונד|דיאם|דימונד"),
    ("תכשיט / תכשיטי", r"תכשיט"),
    ("ישראל", r"ישראל"),
    ("ובניו / אחים", r"ובניו|ובנו|ובנותיו|אחים"),
    ("זהב / גולד", r"זהב|גולד"),
    ("ג׳ם / ג׳מס", r"ג['׳]ם|ג['׳]מס"),
    ("אינטרנשיונל / בינלאומי", r"אינטרנש|אינטרנצ|בינלאומי"),
    ("גרופ / קבוצת", r"גרופ|קבוצת"),
    ("ג׳ולרי", r"ג['׳]ו?ולר"),
]
BIZ_RE = "|".join(p for _, p in WORDS) + r"|השקעות|אחזקות|ייצור|יצור|סחר|טריידינג|מפעל|תעשי|חב['׳]|חברת|צורפות"
YEAR_RE = r"(?<!\d)(19[4-9]\d|20\d\d)(?!\d)"
YEAR_SPLIT = 2000
EARLY_DEC = 1980
RATE_MIN_N = 10
PENDING_MAX = 25
# Names carrying an ID-like token are never printed (counted as unnamed instead).
ID_RE = r'\d{5,}|[A-Za-z]{1,2}\d{4,}|דרכון|ת\.\s?ז|ת["״]ז|תעודת זהות'
YEAR_MIN_GROUP = 30
GAP_PP = 5
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def _order(present, known):
    order = [s for s in known if s in present]
    return order + sorted(set(present) - set(order))


def _form(name):
    if re.search(CO_RE, name):
        return F_CO
    if re.search(PA_RE, name):
        return F_PA
    if re.search(BIZ_RE, name):
        return F_BIZ
    return F_PER


def _prepare(df):
    name = df["diamond_dealer_name"].str.strip().str.replace(r"\s+", " ", regex=True)
    out = pd.DataFrame({
        "name": name,
        "status": df["status"].str.strip().replace("", "לא ידוע"),
        "type": df["license_type"].str.strip().replace("", "לא ידוע"),
    })
    out["form"] = out["name"].map(_form)
    yr = pd.to_numeric(out["name"].str.extract(YEAR_RE)[0], errors="coerce")
    out["year"] = yr.where(out["form"].isin([F_CO, F_PA]))
    return out


def _rate(sub):
    return (sub["status"] == ACTIVE).mean() * 100 if len(sub) else 0.0


def _join(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " ו-" + parts[-1]


# ---------------------------------------------------------------- insights

def insight_status(st, total):
    a = int(st.get(ACTIVE, 0))
    if not total or not a:
        return None
    rest = [f"{n(v)} {STATUS_PLURAL.get(s, s)}" for s, v in st.items() if s != ACTIVE and v > 0]
    s = f"{n(a)} מתוך {n(total)} הרישיונות במאגר פעילים ({pct(a / total * 100)})"
    return s + (f"; {_join(rest)}." if rest else ".")


def insight_type_lead(tc, total):
    if len(tc) < 2:
        return None
    (a, va), (b, vb) = list(tc.items())[:2]
    if va < 1.2 * vb:
        return None
    return (f"רישיון {a} הוא הנפוץ ביותר — {n(va)} רישיונות, {pct(va / total * 100, 0)} מהמאגר; "
            f"אחריו {b} עם {n(vb)}.")


def insight_rate_gap(rates, counts):
    r = {t: v for t, v in rates.items() if counts.get(t, 0) >= 100}
    if len(r) < 2:
        return None
    lo = min(r, key=lambda t: (r[t], t))
    hi = max(r, key=lambda t: (r[t], t))
    if r[hi] - r[lo] < GAP_PP:
        return None
    return (f"שיעור הפעילים נמוך במיוחד ברישיונות {lo}: {pct(r[lo], 0)} בלבד, "
            f"לעומת {pct(r[hi], 0)} ברישיונות {hi}.")


def insight_mix(types, share_all, share_act):
    diffs = [(share_act[t] - share_all[t], t) for t in types]
    if not diffs:
        return None
    d, t = min(diffs)
    if -d < GAP_PP:
        return None
    pl = TYPE_PLURAL.get(t, f"בעלי רישיון {t}")
    return (f"{pl} הם {pct(share_all[t], 0)} מכלל הרישיונות במאגר, אך רק {pct(share_act[t], 0)} "
            f"מהרישיונות הפעילים — חלקם בענף הפעיל קטן מחלקם במרשם ההיסטורי.")


def insight_form(form_rates, form_counts, act_total, act_co):
    if form_counts.get(F_CO, 0) < 100 or form_counts.get(F_PER, 0) < 100 or not act_total:
        return None
    rc, rp = form_rates[F_CO], form_rates[F_PER]
    if abs(rc - rp) < GAP_PP:
        return None
    word = "גבוה" if rc > rp else "נמוך"
    return (f"שיעור הפעילים בקרב חברות בע״מ ({pct(rc, 0)}) {word} משיעורם בקרב רישיונות "
            f"הרשומים על שם אישי ({pct(rp, 0)}); חברות מחזיקות {pct(act_co / act_total * 100, 0)} "
            f"מהרישיונות הפעילים.")


def insight_words(word_rows, total):
    if not word_rows:
        return None
    top = word_rows[0]
    if top["count"] / total < 0.05:
        return None
    s = (f"המילה „{top['short']}” מופיעה בשמם של {n(top['count'])} בעלי רישיון "
         f"({pct(top['count'] / total * 100, 0)} מהמאגר)")
    lat = next((w for w in word_rows if w["label"].startswith("דיאמונד")), None)
    if lat and lat["count"] >= 50 and lat is not top:
        s += f", והתעתיק הלועזי „דיאמונד” על גלגוליו — בשמם של {n(lat['count'])}"
    return s + "."


def insight_years(df):
    y = df.dropna(subset=["year"])
    old, new = y[y["year"] < YEAR_SPLIT], y[y["year"] >= YEAR_SPLIT]
    if len(old) < YEAR_MIN_GROUP or len(new) < YEAR_MIN_GROUP:
        return None
    ro, rn = _rate(old), _rate(new)
    if abs(rn - ro) < 10:
        return None
    word = "גבוה" if rn > ro else "נמוך"
    return (f"בשמותיהן של {n(len(y))} חברות ושותפויות מופיעה שנה (למשל „(1990) בע״מ”). בקרב אלה "
            f"שבשמן שנה מ-{YEAR_SPLIT} ואילך שיעור הפעילים {word} יותר: {pct(rn, 0)}, לעומת "
            f"{pct(ro, 0)} בקרב אלה שבשמן שנה מוקדמת יותר.")


def insight_pending(df):
    p = df[df["status"] == PENDING]
    if p.empty:
        return None
    tc = p["type"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    parts = [f"{n(v)} ברישיון {t}" for t, v in tc.items()]
    return f"{n(len(p))} רישיונות נמצאים כעת בהליך רישום: {_join(parts)}."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["dealers"])
    total = len(df)
    statuses = _order(set(df["status"]), STATUS_ORDER)
    types = _order(set(df["type"]), TYPE_ORDER)
    forms = [f for f in FORMS if (df["form"] == f).any()]

    st = df["status"].value_counts().reindex(statuses).fillna(0).astype(int)
    act_total = int(st.get(ACTIVE, 0))
    pend = int(st.get(PENDING, 0))
    act = df[df["status"] == ACTIVE]

    ts = df.groupby(["type", "status"]).size().unstack(fill_value=0).reindex(
        index=types, columns=statuses, fill_value=0)
    tcount = ts.sum(axis=1)
    tc_sorted = tcount.sort_index().sort_values(ascending=False, kind="stable")
    rates = {t: (ts.loc[t, ACTIVE] / tcount[t] * 100 if ACTIVE in ts.columns and tcount[t] else 0.0)
             for t in types}
    overall_rate = act_total / total * 100 if total else 0.0
    share_all = {t: tcount[t] / total * 100 for t in types}
    share_act = {t: ((act["type"] == t).sum() / act_total * 100 if act_total else 0.0) for t in types}
    inact = df[df["status"] == INACTIVE]
    share_inact = {t: ((inact["type"] == t).sum() / len(inact) * 100 if len(inact) else 0.0)
                   for t in types}

    fs = df.groupby(["form", "status"]).size().unstack(fill_value=0).reindex(
        index=forms, columns=statuses, fill_value=0)
    fcount = fs.sum(axis=1)
    form_rates = {f: _rate(df[df["form"] == f]) for f in forms}
    act_co = int((act["form"] == F_CO).sum())
    ft = df.groupby(["type", "form"]).size().unstack(fill_value=0).reindex(
        index=types, columns=forms, fill_value=0)

    # Trade vocabulary.
    word_rows = []
    for label, rx in WORDS:
        m = df["name"].str.contains(rx, regex=True)
        c = int(m.sum())
        if c == 0:
            continue
        sub = df[m]
        word_rows.append({"label": label, "short": label.split(" ")[0], "count": c,
                          "active": int((sub["status"] == ACTIVE).sum()),
                          "rate": _rate(sub),
                          "lead_type": sub["type"].value_counts().sort_index()
                                       .sort_values(ascending=False, kind="stable").index[0]})
    word_rows.sort(key=lambda w: (-w["count"], w["label"]))

    # Year embedded in business names, by decade.
    y = df.dropna(subset=["year"]).copy()
    y["dec"] = (y["year"] // 10 * 10).astype(int)
    decs = sorted(y["dec"].unique())
    dec_rows = []
    if any(d < EARLY_DEC for d in decs):
        dec_rows.append((f"לפני {EARLY_DEC}", y[y["dec"] < EARLY_DEC]))
    for d in decs:
        if d >= EARLY_DEC:
            dec_rows.append((f"שנות ה-{d}", y[y["dec"] == d]))
    years_chart = {"x": [k for k, _ in dec_rows],
                   "series": [{"name": s, "color": STATUS_COLOR.get(s),
                               "data": [int((sub["status"] == s).sum()) for _, sub in dec_rows]}
                              for s in statuses if (y["status"] == s).any()],
                   "rate": [round(_rate(sub), 1) if len(sub) >= RATE_MIN_N else None
                            for _, sub in dec_rows]}

    # Businesses in registration (named); individuals counted only.
    pend_df = df[df["status"] == PENDING]
    id_like = pend_df["name"].str.contains(ID_RE, regex=True)
    pend_biz = pend_df[pend_df["form"].isin([F_CO, F_PA]) & ~id_like].sort_values(["name", "type"])
    pend_people = len(pend_df) - len(pend_biz)

    charts = {
        "status": {"names": statuses, "values": [int(st[s]) for s in statuses],
                   "colors": [STATUS_COLOR.get(s) for s in statuses]},
        "type": {"names": types,
                 "series": [{"name": s, "color": STATUS_COLOR.get(s),
                             "data": [int(ts.loc[t, s]) for t in types]} for s in statuses]},
        "rate": {"names": types, "values": [round(rates[t], 1) for t in types],
                 "overall": round(overall_rate, 1)},
        "mix": {"names": types,
                "series": [{"name": "כלל המאגר", "data": [round(share_all[t], 1) for t in types]},
                           {"name": "פעילים", "data": [round(share_act[t], 1) for t in types]},
                           {"name": "לא פעילים", "data": [round(share_inact[t], 1) for t in types]}]},
        "form": {"names": forms,
                 "series": [{"name": s, "color": STATUS_COLOR.get(s),
                             "data": [round(fs.loc[f, s] / fcount[f] * 100, 1) if fcount[f] else 0
                                      for f in forms]} for s in statuses]},
        "formtype": {"names": types,
                     "series": [{"name": f, "data": [round(ft.loc[t, f] / tcount[t] * 100, 1)
                                                      if tcount[t] else 0 for t in types]}
                                for f in forms]},
        "words": {"names": [w["label"] for w in word_rows],
                  "series": [{"name": ACTIVE, "color": STATUS_COLOR[ACTIVE],
                              "data": [w["active"] for w in word_rows]},
                             {"name": "אחר", "color": STATUS_COLOR[INACTIVE],
                              "data": [w["count"] - w["active"] for w in word_rows]}]},
        "years": years_chart,
    }

    rules = [
        ("status", insight_status(st, total)),
        ("type_lead", insight_type_lead(tc_sorted, total)),
        ("rate_gap", insight_rate_gap(rates, tcount.to_dict())),
        ("mix", insight_mix(types, share_all, share_act)),
        ("form", insight_form(form_rates, fcount.to_dict(), act_total, act_co)),
        ("words", insight_words(word_rows, total)),
        ("years", insight_years(df)),
        ("pending", insight_pending(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    share_tone = "ok" if overall_rate >= 50 else ("warn" if overall_rate < 30 else "brand")
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "active": {"value": act_total, "display": n(act_total), "tone": "ok"},
        "share": {"value": round(overall_rate, 1), "display": f"{overall_rate:.1f}%",
                  "tone": share_tone},
        "pending": {"value": pend, "display": n(pend), "tone": "info" if pend else "brand"},
    }

    low = min(types, key=lambda t: (rates[t], t)) if types else ""
    y_total = len(y)
    labels = {
        "lede": (f"מרשם בעלי רישיון היהלומנים של מינהל היהלומים במשרד הכלכלה והתעשייה: "
                 f"{n(total)} רישיונות, מהם {n(act_total)} פעילים ו-{n(pend)} בהליך רישום. לכל רישיון "
                 f"רשומים רק שם בעליו, סוג הרישיון ({_join(types)}) והסטטוס — אין במאגר תאריכים או "
                 f"כתובות, ולכן העמוד מתאר את הרכב המרשם: פעילות לפי סוג רישיון, והמידע שעולה משמות "
                 f"בעלי הרישיון."),
        "status_note": "הסטטוס הנוכחי של כל הרישיונות במאגר.",
        "status_aria": f"תרשים טבעת: רישיונות לפי סטטוס — {n(act_total)} פעילים מתוך {n(total)}.",
        "status_caption": "מספר רישיונות ושיעורם לפי סטטוס.",
        "type_note": "מספר הרישיונות מכל סוג, לפי הסטטוס הנוכחי.",
        "type_aria": (f"תרשים עמודות מוערמות: רישיונות לפי סוג וסטטוס — {tc_sorted.index[0]} "
                      f"הנפוץ עם {n(tc_sorted.iloc[0])}."),
        "type_caption": "מספר רישיונות לפי סוג רישיון וסטטוס.",
        "rate_note": (f"איזה חלק מהרישיונות מכל סוג פעיל כיום. הקו המקווקו — שיעור הפעילים בכלל "
                      f"המאגר ({overall_rate:.1f}%)."),
        "rate_aria": (f"תרשים עמודות: שיעור הרישיונות הפעילים לפי סוג רישיון; הנמוך ביותר — {low} "
                      f"עם {rates.get(low, 0):.0f}%."),
        "rate_caption": "שיעור הרישיונות הפעילים לפי סוג רישיון.",
        "mix_note": ("חלקו של כל סוג רישיון בכלל המאגר, בקרב הרישיונות הפעילים ובקרב הלא פעילים. "
                     "פער בין העמודות מראה אילו סוגים נשארו פעילים ואילו מאפיינים בעיקר את המרשם ההיסטורי."),
        "mix_aria": "תרשים עמודות מקובצות: חלקו של כל סוג רישיון בכלל המאגר, בקרב הפעילים ובקרב הלא פעילים.",
        "mix_caption": "חלקו של כל סוג רישיון (באחוזים) בכלל המאגר, בקרב הפעילים ובקרב הלא פעילים.",
        "form_note": ("הצורה המשפטית כפי שהיא עולה משם בעל הרישיון: „בע״מ” — חברה; „ש.ר”, „שותפות” "
                      "או „ושות׳” — שותפות; שם הכולל מילה מסחרית (יהלומים, תכשיטים, אחזקות…) בלי צורה "
                      "משפטית — שם מסחרי; וכל השאר — שם אישי, ברובם עוסקים יחידים. הסיווג נגזר מטקסט "
                      "השם ואינו רשמי."),
        "form_aria": (f"תרשים עמודות מוערמות באחוזים: סטטוס לפי צורה משפטית — שיעור הפעילים "
                      f"{form_rates.get(F_CO, 0):.0f}% בחברות."),
        "form_caption": "מספר רישיונות ושיעור כל סטטוס לפי הצורה המשפטית העולה מהשם.",
        "formtype_note": "איך מתחלקים בעלי כל סוג רישיון בין חברות, שותפויות, שמות מסחריים ושמות אישיים.",
        "formtype_aria": "תרשים עמודות מוערמות באחוזים: צורה משפטית לפי סוג רישיון.",
        "formtype_caption": "חלקה של כל צורה משפטית (באחוזים) בכל סוג רישיון.",
        "words_note": ("כמה בעלי רישיון כוללים בשמם מילה מכל משפחה — בכתיב עברי או בתעתיק — ומהם כמה "
                       "פעילים. שם יכול להופיע ביותר ממשפחה אחת."),
        "words_aria": (f"תרשים עמודות אופקי מוערם: מילים נפוצות בשמות בעלי הרישיון — "
                       f"{word_rows[0]['label'] if word_rows else ''} בראש."),
        "words_caption": "מספר בעלי רישיון שבשמם מופיעה כל משפחת מילים, מהם פעילים, ושיעור הפעילים.",
        "years_note": (f"{n(y_total)} חברות ושותפויות כוללות שנה בשמן, כמו „(1990) בע״מ” — בדרך "
                       f"כלל שנת ההתאגדות. התרשים מקבץ אותן לפי עשור השנה שבשם ומראה כמה מהן פעילות כיום; "
                       f"שיעור הפעילים מוצג לעשורים עם {RATE_MIN_N} חברות לפחות."),
        "years_aria": "תרשים עמודות מוערמות: חברות ושותפויות שבשמן שנה, לפי עשור וסטטוס.",
        "years_caption": "חברות ושותפויות שבשמן שנה, לפי עשור, סטטוס ושיעור הפעילים.",
        "pending_note": ("חברות ושותפויות שרישיונן נמצא כעת בהליך רישום"
                         + (f" (מוצגות {PENDING_MAX} הראשונות לפי סדר האלף-בית מתוך {n(len(pend_biz))})."
                            if len(pend_biz) > PENDING_MAX else ".")
                         + (f" עוד {n(pend_people)} בקשות אינן מפורטות כאן (בעלי רישיון על שם אישי או "
                            f"שם מסחרי, או שמות הכוללים מספר מזהה)." if pend_people else "")),
        "pending_caption": "חברות ושותפויות בהליך רישום, לפי סוג רישיון.",
    }

    tables = {
        "status": [{"name": s, "count": n(st[s]), "share": f"{st[s] / total * 100:.1f}%"}
                   for s in statuses],
        "status_cols": statuses,
        "type": [{"name": t, "total": n(tcount[t]), "vals": [n(ts.loc[t, s]) for s in statuses]}
                 for t in types],
        "rate": [{"name": t, "count": n(tcount[t]), "rate": f"{rates[t]:.1f}%"} for t in types],
        "mix": [{"name": t, "all": f"{share_all[t]:.1f}%", "act": f"{share_act[t]:.1f}%",
                 "inact": f"{share_inact[t]:.1f}%"} for t in types],
        "form": [{"name": f, "total": n(fcount[f]),
                  "shares": [f"{fs.loc[f, s] / fcount[f] * 100:.1f}%" for s in statuses]}
                 for f in forms],
        "form_cols": forms,
        "formtype": [{"name": t, "shares": [f"{ft.loc[t, f] / tcount[t] * 100:.1f}%" for f in forms]}
                     for t in types],
        "words": [{"name": w["label"], "count": n(w["count"]), "active": n(w["active"]),
                   "rate": f"{w['rate']:.1f}%", "lead": w["lead_type"]} for w in word_rows],
        "years": [{"name": k, "total": n(len(sub)), "active": n((sub["status"] == ACTIVE).sum()),
                   "rate": f"{_rate(sub):.1f}%" if len(sub) >= RATE_MIN_N else "—"}
                  for k, sub in dec_rows],
        "pending": [{"name": r["name"], "type": r["type"], "form": r["form"]}
                    for _, r in pend_biz.head(PENDING_MAX).iterrows()],
    }

    return {
        "agent_data": {
            "summary_he": (f"מרשם היהלומנים של מינהל היהלומים: {n(total)} רישיונות סחר, ייצור וצורפות, "
                           f"מהם {n(act_total)} פעילים ({overall_rate:.0f}%) ו-{n(pend)} בהליך רישום — "
                           f"פילוח לפי סוג רישיון, צורה משפטית ומילים בשמות העסקים."),
            "dataset_kind": "registry",
            "related_ids": ["246d949c-a253-4811-8a11-41a137d3d613",
                            "ed8ce28e-ae7f-4588-b3f9-59485960d521",
                            "4acf8b98-776e-4c36-8f98-73cc73fed623",
                            "ed98fd7a-0e62-4691-b733-1960a6ea2c73"],
            "suggested_tags": ["יהלומים", "רישוי", "סחר", "תכשיטים", "תעשייה"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "flags": {"years": len(dec_rows) >= 3, "pending": bool(len(pend_biz)),
                  "words": bool(word_rows)},
        "insights": insights,
        "labels": labels,
    }
