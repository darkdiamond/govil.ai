"""רשם ההקדשות — the public-endowments register of the Corporations Authority.

Three tables keyed by the endowment file number (מספר תיק):

* general   — the register itself: one row per registered public endowment
              (name, registration date, purposes free text, funding method,
              status — currently always "פעיל").
* balances  — reported asset balances: one or more lines per file (a line per
              currency / holding), all lines of a file sharing one "as of"
              date. It also carries files that are no longer in the general
              register (mostly old, near-zero reports).
* realestate — one row per property held by an endowment (type, block/parcel,
              whether an endowment caveat is noted in the land registry). It
              too has a few files that are not in the general register.

Endowments are registered entities and are named (top balances, most
properties). Block/parcel numbers are never printed. Exact duplicate rows are
dropped in every table, and a file listed twice in the register is counted
once (earliest registration date).

"Now" is the latest registration date in the register; balance dates after
it are treated as invalid. The current year is partial and labelled as such.
"""
import math
import re

import pandas as pd

UNKNOWN = "לא צוין"
ILS = "ש~ח"
TOP_BAL = 15
TOP_RE_TYPES = 12
TOP_RE_ENDOW = 10
REPORT_YEARS = 12
CURRENT_YEARS = 2          # a report is "current" if dated in the last 2 full years or later
STALE_YEARS = 5            # older than this many years before "now" = stale
MIN_YEAR_N = 10

THEMES = [
    ("מלגות ופרסים", r"מלג|מילג|פרס|סטיפנד|הענקת"),
    ("השכלה גבוהה", r"אוניברסיט|טכניון|מכלל|פקולט|סטודנט|ויצמן"),
    ("חינוך ותלמידים", r"חינוך|בית ספר|בתי ספר|בית הספר|תלמיד|ילד|נוער|\bגן\b"),
    ("רווחה וסיוע לנזקקים",
     r"נזקק|נצרכ|\bעני|לעני|סיוע|עזרה|צדקה|הלווא|גמ~ח|קשיש|זקן|זקנ|יתומ|רווח|חסד|ניצולי"),
    ("דת ופולחן", r"כנסת|תורה|ישיב|מסגד|וקף|כנסי|מקווה|\bדת|קבר|תפיל"),
    ("רפואה ובריאות", r"רפוא|חולי|סרטן|בריאות|נכים|נכות|עיוור"),
    ("תרבות, אמנות וספרים", r"תרבות|אמנו|אומנו|מוזיק|ספרי|ספרות|תיאטרון|מוזיאון|מחול"),
    ("מחקר", r"מחקר|חקר"),
    ("צבא, ביטחון והנצחה", r"צה~ל|חייל|נופל|לוחמ|צבא|שכול|ביטחון"),
]
INSTITUTIONS = [
    ("האוניברסיטה העברית", r"העברית"),
    ("אוניברסיטת בר-אילן", r"בר[- ]?אילן"),
    ("אוניברסיטת תל אביב", r"אוניברסיט\S*\s+ת(?:ל[- ]אביב|~א)"),
    ("הטכניון", r"טכניון"),
    ("אוניברסיטת בן-גוריון", r"אוניברסיט\S*\s+בן[- ]גוריון|בן[- ]גוריון בנגב"),
    ("מכון ויצמן", r"ויצמן"),
    ("אוניברסיטת חיפה", r"אוניברסיט\S*\s+חיפה"),
    ("האוניברסיטה הפתוחה", r"האוניברסיטה הפתוחה"),
    ("אוניברסיטת אריאל", r"אריאל"),
]
MEMORIAL = r"ז~ל|ע~ש|ע\"ש|לזכר|לזיכר|הנצח|על שם|על-שם|ע~ש"
BAL_BUCKETS = [
    (None, 0, "ללא יתרה"),
    (0, 1e4, "עד 10 אלף"),
    (1e4, 1e5, "10 אלף עד 100 אלף"),
    (1e5, 1e6, "100 אלף עד מיליון"),
    (1e6, 1e7, "מיליון עד 10 מיליון"),
    (1e7, 1e8, "10 עד 100 מיליון"),
    (1e8, None, "מעל 100 מיליון"),
]


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _ils(v):
    """Human ILS amount: '2.0 מיליארד ₪', '881.7 מיליון ₪', '236,332 ₪'."""
    if abs(v) >= 1e9:
        return f"{v / 1e9:.1f} מיליארד ₪"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f} מיליון ₪"
    return f"{_int(v)} ₪"


def _clean(s):
    """CKAN export writes gershayim as '~' (ז~ל, ש~ח) — restore them."""
    s = re.sub(r"(?<=[א-ת])~(?=[א-ת])", "״", str(s))
    s = s.replace("~", "\"")
    s = re.sub(r"\s+", " ", s).strip().rstrip(".").strip()
    return s


def _vc(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _date(s):
    return pd.to_datetime(s.str.strip(), format="%d/%m/%Y", errors="coerce")


def _fsum(vals):
    return math.fsum(sorted(float(v) for v in vals))


# ---------------------------------------------------------------- prepare

def _prepare(frames):
    g = frames["general"].drop_duplicates().copy()
    g["tik"] = g["מספר תיק"].str.strip()
    g["reg"] = _date(g["תאריך רישום"])
    g["name"] = g["שם הקדש"].map(_clean)
    g["fund"] = g["שיטת מימון"].str.strip().replace("", UNKNOWN)
    g["status"] = g["סטטווס תיק"].str.strip().replace("", UNKNOWN)
    g["purpose"] = g["מטרות"].str.strip()
    g = g[g["tik"] != ""]
    g = g.sort_values(["tik", "reg", "name"], na_position="last", kind="stable")
    g = g.drop_duplicates("tik", keep="first").set_index("tik")
    now = g["reg"].max()

    b = frames["balances"].drop_duplicates().copy()
    b["tik"] = b["מספר תיק"].str.strip()
    b["amt"] = pd.to_numeric(b["סכום"].str.replace(",", "").str.strip(), errors="coerce").fillna(0.0)
    b["cur"] = b["תאור מטבע"].str.strip()
    d = _date(b["נכון לתאריך"])
    b["bad_date"] = d.notna() & (d > now)
    b["dt"] = d.where(~b["bad_date"])
    b = b[b["tik"] != ""]

    r = frames["realestate"].drop_duplicates().copy()
    r["tik"] = r["מספר תיק"].str.strip()
    r["type"] = r["תאור הנכס"].str.strip().replace("", UNKNOWN)
    r["note"] = r["הערה במרשם המקרקעין"].str.strip() == "יש"
    gush = pd.to_numeric(r["גוש"].str.strip(), errors="coerce").fillna(0)
    helka = pd.to_numeric(r["חלקה"].str.strip(), errors="coerce").fillna(0)
    sub = pd.to_numeric(r["תת חלקה"].str.strip(), errors="coerce").fillna(0)
    r["has_parcel"] = (gush > 0) & (helka > 0)
    r["has_sub"] = sub > 0
    r["name"] = r["שם הקדש"].map(_clean)
    r = r[r["tik"] != ""]

    # per-file balance summary
    ils = b[b["cur"] == ILS].groupby("tik")["amt"].apply(_fsum)
    rep = b.groupby("tik")["dt"].max()
    per = pd.DataFrame({"rep": rep})
    per["ils"] = ils
    per["has_ils"] = per["ils"].notna()
    per["in_reg"] = per.index.isin(g.index)
    return g, b, r, per, now


# ---------------------------------------------------------------- pieces

def _themes(g):
    text = (g["purpose"] + " " + g["שם הקדש"]).fillna("")
    out = {}
    for label, pat in THEMES:
        out[label] = text.str.contains(pat, regex=True)
    return pd.DataFrame(out, index=g.index)


def _institutions(g):
    return {label: int(g["purpose"].str.contains(pat, regex=True).sum()) for label, pat in INSTITUTIONS}


def _bucket(v):
    for lo, hi, label in BAL_BUCKETS:
        if lo is None and v <= hi:
            return label
        if hi is None and v > lo:
            return label
        if lo is not None and hi is not None and lo < v <= hi:
            return label
    return BAL_BUCKETS[-1][2]


# ---------------------------------------------------------------- insights

def insight_funding(g):
    vc = _vc(g["fund"])
    n = len(g)
    top, top_n = vc.index[0], int(vc.iloc[0])
    share = top_n / n
    if share < 0.4:
        return None
    tail = ""
    if len(vc) > 1:
        tail = f", ועוד {_int(vc.iloc[1])} ({_pct(vc.iloc[1] / n)}) בשיטת '{vc.index[1]}'"
    note = (" — כלומר מחלקים רק את התשואה ושומרים על הקרן עצמה" if top == "פירות בלבד" else "")
    return (f"{_int(top_n)} מתוך {_int(n)} ההקדשות הרשומים ({_pct(share)}) ממומנים בשיטת "
            f"'{top}'{note}{tail}.")


def insight_concentration(reg_bal):
    s = reg_bal["ils"].sort_values(ascending=False, kind="stable")
    tot = _fsum(s)
    if len(s) < 50 or tot <= 0:
        return None
    top10 = _fsum(s.head(10)) / tot
    if top10 < 0.3:
        return None
    lead = reg_bal.sort_values(["ils", "name"], ascending=[False, True], kind="stable").iloc[0]
    half = _fsum(s.tail(len(s) // 2)) / tot
    return (f"היתרות מרוכזות מאוד: 10 ההקדשות הגדולים מחזיקים {_pct(top10)} מסך {_ils(tot)} "
            f"שדווחו בשקלים, והגדול שבהם, '{lead['name']}', לבדו {_ils(lead['ils'])} "
            f"({_pct(lead['ils'] / tot)}). מחצית ההקדשות הקטנים יותר מחזיקים יחד {_pct(half)} בלבד.")


def insight_median(reg_bal, n_reg):
    s = reg_bal["ils"]
    if len(s) < 50:
        return None
    zero = int((s <= 0).sum())
    med = float(s.median())
    zs = zero / len(s)
    z_txt = (f"; {_int(zero)} ({_pct(zs)}) דיווחו על יתרה אפסית" if zs >= 0.05 else "")
    missing = n_reg - len(s)
    m_txt = (f". ל-{_int(missing)} הקדשות רשומים אין דיווח יתרה בשקלים כלל" if missing > 0 else "")
    return (f"היתרה החציונית של הקדש רשום היא {_ils(med)} — מחצית ההקדשות מחזיקים פחות מכך{z_txt}{m_txt}.")


def insight_re_link(g, re_tiks):
    has = g.index.isin(re_tiks)
    rate = pd.Series(has, index=g.index).groupby(g["fund"]).agg(["size", "mean"])
    rate = rate[(rate["size"] >= 50) & (rate.index != UNKNOWN)]
    if len(rate) < 2:
        return None
    order = sorted(rate.itertuples(), key=lambda t: (-t.mean, t.Index))
    hi, lo = order[0], order[-1]
    if hi.mean - lo.mean < 0.3:
        return None
    return (f"שיטת המימון מתאימה למה שההקדש מחזיק: {_pct(hi.mean)} מההקדשות בשיטת '{hi.Index}' "
            f"מחזיקים נכסי מקרקעין, לעומת {_pct(lo.mean)} בלבד מאלה שבשיטת '{lo.Index}'. "
            f"ההשוואה כוללת שיטות עם 50 הקדשות לפחות.")


def insight_note(r):
    n = len(r)
    if n < 50:
        return None
    no = int((~r["note"]).sum())
    if no / n < 0.1:
        return None
    t = r.groupby("type")["note"].agg(["size", "mean"])
    t = t[(t["size"] >= 50) & (t.index != UNKNOWN)]
    tail = ""
    if len(t) >= 2:
        o = sorted(t.itertuples(), key=lambda x: (x.mean, x.Index))
        tail = (f" הפער לפי סוג הנכס: '{o[0].Index}' — {_pct(o[0].mean)} עם הערה, "
                f"'{o[-1].Index}' — {_pct(o[-1].mean)}.")
    return (f"ל-{_int(no)} מתוך {_int(n)} נכסי המקרקעין ({_pct(no / n)}) לא רשומה "
            f"במרשם המקרקעין הערה על היותו נכס של הקדש.{tail}")


def insight_stale(g, per, now):
    rep = per.loc[per.index.isin(g.index), "rep"]
    rep = rep.reindex(g.index)
    n = len(g)
    cut = now.year - STALE_YEARS
    stale = int((rep.dt.year < cut).sum())
    none = int(rep.isna().sum())
    if (stale + none) / n < 0.1:
        return None
    cur = int((rep.dt.year >= now.year - CURRENT_YEARS).sum())
    return (f"עדכניות הדיווח: ל-{_int(cur)} מההקדשות הרשומים ({_pct(cur / n)}) יש דיווח יתרה מ-"
            f"{now.year - CURRENT_YEARS} ואילך, אבל אצל {_int(stale)} ({_pct(stale / n)}) הדיווח האחרון "
            f"קודם ל-{cut}, ול-{_int(none)} אין דיווח יתרה מתוארך כלל.")


def insight_orphans(g, per, r, now):
    orph = per[~per["in_reg"]]
    re_orph = set(r["tik"]) - set(g.index)
    if len(orph) < 20:
        return None
    med = float(orph["ils"].dropna().median()) if orph["has_ils"].any() else 0.0
    old = int((orph["rep"].dt.year < now.year - STALE_YEARS).sum() + orph["rep"].isna().sum())
    re_txt = (f" גם בקובץ המקרקעין יש {_int(len(re_orph))} תיקים שאינם במרשם." if len(re_orph) else "")
    return (f"קובץ היתרות כולל {_int(len(orph))} תיקים שאינם מופיעים במרשם הכללי — כנראה הקדשות שכבר "
            f"אינם רשומים כפעילים: היתרה החציונית שלהם {_ils(med)}, ול-{_int(old)} מהם ({_pct(old / len(orph))}) "
            f"הדיווח האחרון ישן מ-{STALE_YEARS} שנים או חסר תאריך.{re_txt}")


def insight_peaks(g, now):
    y = g["reg"].dt.year.dropna().astype(int)
    full = now.year - 1
    span = y[(y <= full) & (y > full - 30)]
    if len(span) < 200:
        return None
    counts = span.value_counts().reindex(range(full - 29, full + 1), fill_value=0)
    med = float(counts.median())
    peaks = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    if med <= 0 or peaks[0][1] < 2 * med:
        return None
    days = _vc(g["reg"].dropna())
    day, day_n = days.index[0], int(days.iloc[0])
    p_txt = ", ".join(f"{yr} ({_int(c)})" for yr, c in peaks)
    d_txt = (f" ביום אחד, {day.day}/{day.month}/{day.year}, נרשמו {_int(day_n)} הקדשות." if day_n >= 10 else "")
    return (f"הרישום מגיע בגלים. שנות השיא: {p_txt} — בשנת השיא נרשמו פי {peaks[0][1] / med:.1f} מהחציון השנתי "
            f"של 30 השנים האחרונות ({_int(med)}).{d_txt}")


def insight_trend(g, now):
    y = g["reg"].dt.year
    full, prev = now.year - 1, now.year - 2
    a, b = int((y == full).sum()), int((y == prev).sum())
    if b < MIN_YEAR_N:
        return None
    ch = (a - b) / b
    if round(ch * 100) == 0:
        trend = f"ללא שינוי לעומת {prev}"
    else:
        trend = f"{'עלייה' if ch > 0 else 'ירידה'} של {abs(ch) * 100:.0f}% לעומת {prev} ({_int(b)})"
    cur = int((y == now.year).sum())
    return (f"ב-{full} נרשמו {_int(a)} הקדשות חדשות — {trend}. מתחילת {now.year} ועד "
            f"{now.day}/{now.month} נרשמו {_int(cur)}.")


def insight_themes(th, inst, n):
    s = th.sum().sort_values(ascending=False, kind="stable")
    lead, lead_n = s.index[0], int(s.iloc[0])
    if lead_n / n < 0.25:
        return None
    best = sorted(inst.items(), key=lambda kv: (-kv[1], kv[0]))
    tail = ""
    if best and best[0][1] >= 20:
        tail = (f" המוסד האקדמי הנזכר בהכי הרבה מטרות: {best[0][0]} ({_int(best[0][1])} הקדשות)"
                + (f", ואחריו {best[1][0]} ({_int(best[1][1])})" if len(best) > 1 and best[1][1] else "")
                + ".")
    return (f"הייעוד הנפוץ ביותר הוא '{lead}': {_int(lead_n)} הקדשות ({_pct(lead_n / n)}) מזכירים אותו "
            f"במטרותיהם (לפי מילות מפתח).{tail}")


def insight_memorial(g):
    m = g["שם הקדש"].str.contains(MEMORIAL, regex=True)
    share = m.mean()
    if share < 0.3:
        return None
    return (f"רוב ההקדשות הם קרנות הנצחה: ב-{_int(m.sum())} משמות ההקדשות ({_pct(share)}) מופיע "
            f"'ז״ל', 'על שם' או 'לזכר'.")


# ---------------------------------------------------------------- compute

def compute(frames):
    g, b, r, per, now = _prepare(frames)
    n = len(g)
    full = now.year - 1
    now_he = f"{now.day}/{now.month}/{now.year}"
    G, A, R = set(g.index), set(per.index), set(r["tik"])

    # -- coverage of the three files
    combos = [
        ("במרשם, עם יתרה ומקרקעין", G & A & R),
        ("במרשם, עם יתרה בלבד", (G & A) - R),
        ("במרשם, עם מקרקעין בלבד", (G & R) - A),
        ("במרשם, ללא יתרה ומקרקעין", G - A - R),
        ("רק בקובץ היתרות", A - G - R),
        ("בקובצי היתרות והמקרקעין בלבד", (A & R) - G),
        ("רק בקובץ המקרקעין", R - G - A),
    ]
    coverage = {"names": [k for k, v in combos if v], "values": [len(v) for k, v in combos if v]}

    # -- registrations per year
    y = g["reg"].dt.year.dropna().astype(int)
    first_year = int(y.min())
    yc = y.value_counts()
    years = list(range(first_year, now.year + 1))
    years_chart = {"x": [str(v) for v in years], "y": [int(yc.get(v, 0)) for v in years]}
    no_reg = int(g["reg"].isna().sum())

    # -- funding
    reg_bal = per[per["in_reg"] & per["has_ils"]].copy()
    reg_bal["name"] = g["name"].reindex(reg_bal.index)
    has_re = pd.Series(g.index.isin(R), index=g.index)
    fvc = _vc(g["fund"])
    f_rows = []
    for f, c in fvc.items():
        idx = g.index[g["fund"] == f]
        bal = reg_bal["ils"].reindex(idx).dropna()
        f_rows.append({"label": f, "n": int(c), "share": round(c / n * 100, 1),
                       "re": round(float(has_re[idx].mean()) * 100, 1),
                       "median": round(float(bal.median())) if len(bal) else 0})
    funding = {"names": [x["label"] for x in f_rows], "values": [x["n"] for x in f_rows],
               "re": [x["re"] for x in f_rows], "rows": f_rows}

    # -- purposes
    th = _themes(g)
    ts = th.sum().sort_values(ascending=False, kind="stable")
    themes = {"names": list(ts.index), "values": [int(v) for v in ts.values],
              "share": [round(v / n * 100, 1) for v in ts.values]}
    no_theme = int((~th.any(axis=1)).sum())
    inst = _institutions(g)
    io = [kv for kv in sorted(inst.items(), key=lambda kv: (-kv[1], kv[0])) if kv[1] > 0]
    institutions = {"names": [k for k, _ in io], "values": [v for _, v in io]}

    # -- balances
    bk = reg_bal["ils"].map(_bucket)
    labels = [lbl for _, _, lbl in BAL_BUCKETS]
    bvc = bk.value_counts()
    bal_dist = {"names": labels, "values": [int(bvc.get(lbl, 0)) for lbl in labels]}
    tot = _fsum(reg_bal["ils"])
    top = reg_bal.sort_values(["ils", "name"], ascending=[False, True], kind="stable").head(TOP_BAL)
    top_chart = {"names": list(top["name"]), "values": [round(float(v)) for v in top["ils"]],
                 "mil": [round(float(v) / 1e6, 1) for v in top["ils"]],
                 "share": [round(float(v) / tot * 100, 1) if tot else 0.0 for v in top["ils"]],
                 "year": [str(int(d.year)) if pd.notna(d) else "—" for d in top["rep"]]}
    s = reg_bal["ils"].sort_values(ascending=False, kind="stable")
    k1 = max(1, len(s) // 100)
    k10 = max(1, len(s) // 10)
    conc = [("10 ההקדשות הגדולים", _fsum(s.head(10))),
            (f"האחוז העליון ({_int(k1)} הקדשות)", _fsum(s.head(k1))),
            (f"העשירון העליון ({_int(k10)} הקדשות)", _fsum(s.head(k10))),
            (f"המחצית התחתונה ({_int(len(s) // 2)} הקדשות)", _fsum(s.tail(len(s) // 2)))]
    concentration = {"names": [k for k, _ in conc],
                     "values": [round(v / tot * 100, 1) if tot else 0.0 for _, v in conc]}

    # -- report recency
    y0 = now.year - REPORT_YEARS + 1
    older = f"{y0 - 1} ומטה"
    nodate = "ללא תאריך"

    def rep_bucket(d):
        if pd.isna(d):
            return nodate
        return str(int(d.year)) if d.year >= y0 else older

    rb = per["rep"].map(rep_bucket)
    r_names = [nodate, older] + [str(v) for v in range(y0, now.year + 1)]
    ct = pd.crosstab(rb, per["in_reg"])
    reg_counts = [int(ct.loc[k, True]) if (k in ct.index and True in ct.columns) else 0 for k in r_names]
    oth_counts = [int(ct.loc[k, False]) if (k in ct.index and False in ct.columns) else 0 for k in r_names]
    keep = [i for i in range(len(r_names)) if reg_counts[i] + oth_counts[i] > 0]
    reports = {"names": [r_names[i] for i in keep], "reg": [reg_counts[i] for i in keep],
               "other": [oth_counts[i] for i in keep]}
    bad_dates = int(b.loc[b["bad_date"], "tik"].nunique())

    # -- currencies (non-ILS)
    nb = b[b["cur"] != ILS].copy()
    nb["curl"] = nb["cur"].map(lambda c: _clean(c) if c else UNKNOWN)
    cvc = _vc(nb["curl"])
    cur_rows = [{"label": k, "lines": int(v), "tiks": int(nb.loc[nb["curl"] == k, "tik"].nunique())}
                for k, v in cvc.items()]
    currencies = {"names": [x["label"] for x in cur_rows], "values": [x["lines"] for x in cur_rows],
                  "rows": cur_rows}
    n_ils_lines = int((b["cur"] == ILS).sum())

    # -- real estate
    tvc = _vc(r["type"])
    ttop = list(tvc.index[:TOP_RE_TYPES])
    rkey = r["type"].where(r["type"].isin(ttop), "אחר")
    tnames = ttop + (["אחר"] if (rkey == "אחר").any() else [])
    tg = r.groupby(rkey)["note"]
    t_rows = [{"label": t, "n": int(tg.size()[t]), "note": int(tg.sum()[t]),
               "share": round(float(tg.mean()[t]) * 100, 1)} for t in tnames]
    re_types = {"names": tnames, "note": [x["note"] for x in t_rows],
                "nonote": [x["n"] - x["note"] for x in t_rows], "rows": t_rows}
    pc = r.groupby("tik").agg(n=("type", "size"), note=("note", "sum"))
    rname = r.sort_values(["tik", "name"], kind="stable").groupby("tik")["name"].first()
    pc["name"] = g["name"].reindex(pc.index).fillna(rname)
    pc = pc.sort_values(["n", "name"], ascending=[False, True], kind="stable")
    topre = pc.head(TOP_RE_ENDOW)
    re_top = {"names": list(topre["name"]), "values": [int(v) for v in topre["n"]],
              "rows": [{"label": nm, "n": int(c), "note": int(nt)}
                       for nm, c, nt in zip(topre["name"], topre["n"], topre["note"])]}
    n_re = len(r)
    n_re_endow = int(r["tik"].nunique())
    single = int((pc["n"] == 1).sum())
    parcel_share = float(r["has_parcel"].mean()) if n_re else 0.0
    n_sub = int(r["has_sub"].sum())

    # -- KPIs
    note_share = float(r["note"].mean()) if n_re else 0.0
    rep_reg = per["rep"].reindex(g.index)
    cur_share = float((rep_reg.dt.year >= now.year - CURRENT_YEARS).mean())
    med = float(reg_bal["ils"].median()) if len(reg_bal) else 0.0
    new_full = int((y == full).sum())
    new_prev = int((y == full - 1).sum())

    def tone_share(v, ok, warn):
        return "ok" if v >= ok else "warn" if v >= warn else "danger"

    rules = [
        ("funding", insight_funding(g)),
        ("concentration", insight_concentration(reg_bal)),
        ("median", insight_median(reg_bal, n)),
        ("re_link", insight_re_link(g, R)),
        ("registry_note", insight_note(r)),
        ("stale", insight_stale(g, per, now)),
        ("orphans", insight_orphans(g, per, r, now)),
        ("themes", insight_themes(th, inst, n)),
        ("peaks", insight_peaks(g, now)),
        ("trend", insight_trend(g, now)),
        ("memorial", insight_memorial(g)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    statuses = _vc(g["status"])
    status_txt = (f"כל {_int(n)} התיקים במרשם מסומנים '{statuses.index[0]}'"
                  if len(statuses) == 1 else
                  "; ".join(f"{k}: {_int(v)}" for k, v in statuses.items()))
    lead_fund = funding["names"][0]

    return {
        "agent_data": {
            "summary_he": (f"פנקס ההקדשות הציבוריים של רשות התאגידים: {_int(n)} הקדשות רשומים מאז "
                           f"{first_year}, יתרות נכסים מדווחות של {_ils(tot)} בשקלים ו-{_int(n_re)} נכסי "
                           f"מקרקעין — שיטות מימון, מטרות, ריכוזיות היתרות ועדכניות הדיווח. "
                           f"מעודכן עד {now_he}."),
            "dataset_kind": "registry",
            "suggested_tags": ["הקדשות ציבוריים", "רשם ההקדשות", "קרנות", "מלגות", "מקרקעין",
                               "רשות התאגידים"],
            "related_ids": ["ed98fd7a-0e62-4691-b733-1960a6ea2c73",
                            "246d949c-a253-4811-8a11-41a137d3d613",
                            "382c098b-a687-478a-9965-06977d7c9501",
                            "3111ae54-790a-4d02-9750-d51e1134b405",
                            "669b2652-f75b-4de3-8e6b-0dfa17accef5"],
            "temporal_coverage": f"{first_year}/{now.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "balance": {"value": round(tot), "display": f"{tot / 1e9:.2f}", "tone": "brand"},
            "median": {"value": round(med), "display": _int(med), "tone": "brand"},
            "properties": {"value": n_re, "display": _int(n_re), "tone": "brand"},
            "note_share": {"value": round(note_share, 4), "display": _pct(note_share),
                           "tone": tone_share(note_share, 0.8, 0.5)},
            "current": {"value": round(cur_share, 4), "display": _pct(cur_share),
                        "tone": tone_share(cur_share, 0.75, 0.5)},
            "new_full": {"value": new_full, "display": _int(new_full),
                         "tone": ("ok" if new_prev and new_full >= new_prev * 1.1 else
                                  "warn" if new_prev and new_full <= new_prev * 0.9 else "brand")},
        },
        "charts": {
            "coverage": coverage,
            "years": years_chart,
            "funding": funding,
            "themes": themes,
            "institutions": institutions,
            "bal_dist": bal_dist,
            "top": top_chart,
            "concentration": concentration,
            "reports": reports,
            "currencies": currencies,
            "re_types": re_types,
            "re_top": re_top,
        },
        "flags": {"currencies": bool(cur_rows), "institutions": len(io) >= 2,
                  "realestate": n_re > 0},
        "insights": insights,
        "labels": {
            "lede": (f"{_int(n)} הקדשות ציבוריים רשומים כיום בפנקס של רשם ההקדשות, הוותיק שבהם משנת "
                     f"{first_year}. שיטת המימון הנפוצה: '{lead_fund}'. "
                     f"היתרות שדווחו בשקלים מסתכמות ב-{_ils(tot)}, ו-{_int(n_re_endow)} הקדשות מחזיקים "
                     f"יחד {_int(n_re)} נכסי מקרקעין. הרישום האחרון במרשם: {now_he}."),
            "full_year": str(full),
            "current_from": str(now.year - CURRENT_YEARS),
            "coverage_note": (f"שלושת הקבצים מקושרים במספר התיק. המרשם הכללי מונה {_int(n)} תיקים "
                              f"({status_txt}); קובץ היתרות מכסה {_int(len(A))} תיקים וקובץ המקרקעין "
                              f"{_int(len(R))}. תיקים שמופיעים רק בקבצים המשניים אינם במרשם הכללי."),
            "coverage_aria": "תרשים עמודות: מספר התיקים לפי הקבצים שבהם הם מופיעים.",
            "years_note": (f"מספר ההקדשות הרשומים כיום לפי שנת הרישום. השנה האחרונה חלקית — עד {now_he}."
                           + (f" ל-{_int(no_reg)} תיקים אין תאריך רישום." if no_reg else "")),
            "years_aria": f"גרף עמודות: הקדשות רשומים לפי שנת רישום, {first_year} עד {now.year}.",
            "funding_note": ("שיטת המימון שנקבעה להקדש: 'פירות בלבד' — רק התשואה מחולקת והקרן נשמרת; "
                             "'קרן ופירות' — מותר לממש גם את הקרן; 'שימוש בנכס' — ההקדש מממש את מטרתו "
                             "באמצעות נכס. מימין: מספר ההקדשות; משמאל: שיעור המחזיקים נכסי מקרקעין."),
            "funding_aria": "תרשים עמודות: הקדשות לפי שיטת מימון.",
            "funding_re_aria": "תרשים עמודות: שיעור ההקדשות שמחזיקים נכסי מקרקעין, לפי שיטת מימון.",
            "themes_note": (f"סיווג לפי מילות מפתח בשם ההקדש ובמטרותיו; הקדש יכול להשתייך לכמה ייעודים. "
                            f"{_int(no_theme)} הקדשות לא סווגו לאף ייעוד."),
            "themes_aria": "תרשים עמודות: מספר ההקדשות לפי ייעוד, על פי מילות מפתח במטרות.",
            "institutions_note": "מוסדות להשכלה גבוהה שמוזכרים בשמם בטקסט המטרות של ההקדש.",
            "institutions_aria": "תרשים עמודות: מספר ההקדשות שמטרותיהם מזכירות כל מוסד אקדמי.",
            "bal_note": (f"היתרה בשקלים בדיווח האחרון של כל הקדש רשום (סכום כל שורות השקלים בתיק), "
                         f"ל-{_int(len(reg_bal))} הקדשות שדיווחו יתרה בשקלים."),
            "bal_aria": "תרשים עמודות: הקדשות לפי גודל היתרה בשקלים.",
            "top_note": (f"{TOP_BAL} ההקדשות הרשומים עם היתרה בשקלים הגדולה ביותר, לפי הדיווח האחרון של כל "
                         f"אחד; בטבלה גם שנת הדיווח. יתרות במטבע חוץ אינן נכללות."),
            "top_aria": f"תרשים עמודות: {TOP_BAL} ההקדשות עם היתרה הגדולה ביותר, במיליוני שקלים.",
            "conc_note": f"איזה חלק מסך {_ils(tot)} מוחזק בידי כל קבוצה של הקדשות.",
            "conc_aria": "תרשים עמודות: חלקן של קבוצות הקדשות בסך היתרות בשקלים.",
            "reports_note": (f"התאריך שאליו מתייחסת היתרה האחרונה של כל תיק בקובץ היתרות, בהפרדה בין תיקים "
                             f"שבמרשם לתיקים שאינם בו."
                             + (f" {_int(bad_dates)} תאריכים שחלים אחרי {now_he} נחשבו שגויים." if bad_dates
                                else "")),
            "reports_aria": "גרף עמודות מוערמות: תיקים לפי שנת הדיווח האחרון על היתרה.",
            "cur_note": (f"{_int(n_ils_lines)} שורות יתרה רשומות בשקלים. השורות שלהלן במטבעות אחרים — "
                         f"חלקן במטבעות שכבר אינם בשימוש — ואינן נכללות בסכומים בעמוד."),
            "cur_aria": "תרשים עמודות: שורות יתרה במטבעות שאינם שקל.",
            "re_types_note": (f"{_int(n_re)} נכסים של {_int(n_re_endow)} הקדשות ({_int(single)} מהם מחזיקים "
                              f"נכס אחד). 'הערה במרשם' — האם רשומה בטאבו הערה שהנכס שייך להקדש. "
                              f"ל-{_pct(parcel_share)} מהנכסים מצוינים גוש וחלקה, ול-{_int(n_sub)} גם תת-חלקה."),
            "re_types_aria": "גרף עמודות מוערמות: נכסי מקרקעין לפי סוג, עם הערה במרשם וללא.",
            "re_top_note": f"{TOP_RE_ENDOW} ההקדשות שמחזיקים את מספר נכסי המקרקעין הגדול ביותר.",
            "re_top_aria": f"תרשים עמודות: {TOP_RE_ENDOW} ההקדשות עם מספר הנכסים הגדול ביותר.",
        },
    }
