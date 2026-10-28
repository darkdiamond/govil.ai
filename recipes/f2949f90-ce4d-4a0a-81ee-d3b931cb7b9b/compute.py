"""מאגר עזבונות לטובת המדינה — the Administrator General's estates-for-the-state register.

Five related tables, joined on the estate file number (מספר תיק):

* deposits    — money received into the estates and endowments funds. A
  subset of deposits is repeated once per payment method (a cross-join with
  a three-row lookup in the export, the `ארץ` column); rows are de-duplicated
  to one per deposit before anything is summed.
* cases       — one row per estate file: opening date, status, closing reason,
  whether an endowment (הקדש) exists.
* purposes    — the designations (ייעודים) the testator set for each file;
  several rows per file.
* decisions   — committee allocation decisions reported to the Administrator
  General, one row per decision × source file; exact duplicate rows (a
  repeated export artefact) are dropped.
* allocations — the per-account components of committee allocations (no
  dates), with allocated / paid / cancelled amounts.

The people behind the estates are private individuals; nothing on the page is
per-file — every view is an aggregate. "Now" is the latest receipt date in the
deposits table (never the wall clock); decisions carry their own latest date.
"""
import pandas as pd

LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
TOP_COUNTRIES = 10
TOP_CURRENCIES = 8
TOP_MINISTRIES = 10
TOP_INSTITUTIONS = 12
TOP_TOPICS = 12
TOP_SUBJECTS = 12
HEAT_MINISTRIES = 8
MIX_TOPICS = 6
SIZE_BUCKETS = [(0, 1_000), (1_000, 10_000), (10_000, 100_000), (100_000, 1_000_000),
                (1_000_000, 10_000_000), (10_000_000, None)]
SOURCE_BUCKETS = [(1, 1), (2, 10), (11, 100), (101, None)]   # rank ranges of estate files


# ── formatting ─────────────────────────────────────────────────────────────
def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def mil(v, digits=1):
    return f"{v / 1e6:,.{digits}f}"


def money_he(v):
    """Hebrew money phrase for prose: מיליון / מיליארד ₪."""
    if v >= 1e9:
        return f"{v / 1e9:,.2f} מיליארד ₪"
    if v >= 1e6:
        return f"{v / 1e6:,.1f} מיליון ₪"
    return f"{v:,.0f} ₪"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def signed_pct(v):
    s = f"{abs(v):.1f}%"
    return ("+" if v > 0 else "−" if v < 0 else "") + s


def ministry_he(name):
    if name.startswith(("משרד", "לשכת", "המשרד")):
        return name
    if name.startswith("ל"):
        return "המשרד " + name
    return "משרד " + name


def clean(s):
    """Upstream writes the Hebrew quote (״) as '~'; strip trailing ' -'."""
    return (s.str.replace("~", "״", regex=False).str.strip()
             .str.rstrip("-").str.strip())


def money(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce").fillna(0.0)


def dates(s):
    return pd.to_datetime(s.str.strip(), errors="coerce", format="%d/%m/%Y")


def _rank(series):
    """Sort a value-indexed Series by value desc, label asc (total, stable)."""
    return series.sort_index(kind="stable").sort_values(ascending=False, kind="stable")


def _top(series, k, other="אחר"):
    s = _rank(series)
    top = s.head(k)
    rest = float(s.iloc[k:].sum())
    names = list(top.index) + ([other] if rest > 0 else [])
    vals = [float(v) for v in top.values] + ([rest] if rest > 0 else [])
    return names, vals


def _reference_date(ts):
    """Latest date with at least two other dates within the 90 days before it
    (guards against a single mistyped future date)."""
    d = ts.dropna().sort_values().reset_index(drop=True)
    for i in range(len(d) - 1, -1, -1):
        lo = d.iloc[i] - pd.Timedelta(days=90)
        if ((d >= lo) & (d <= d.iloc[i])).sum() >= 3:
            return d.iloc[i]
    return d.iloc[-1] if len(d) else None


# ── preparation ────────────────────────────────────────────────────────────
def _deposits(df):
    out = pd.DataFrame({
        "no": df["מספר הפקדה"].str.strip(),
        "dt": dates(df["תאריך קבלה"]),
        "raw_dt": df["תאריך קבלה"].str.strip(),
        "ils": money(df["סכום לאחר המרה לשקלים"]),
        "cur": clean(df["סוג מטבע מקור"]).str.rstrip('."').str.strip(),
        "country": clean(df["מדינה"]),
    })
    out = out.drop_duplicates(subset=["no", "raw_dt", "ils", "cur", "country"])
    out["cur"] = out["cur"].replace({"שח": "ש״ח", "": "לא צוין"})
    out["country"] = out["country"].replace("", "לא צוין")
    return out


def _decisions(df):
    df = df.drop_duplicates()
    return pd.DataFrame({
        "dec_no": df["מספר החלטה"].str.strip(),
        "dt": dates(df["תאריך ההחלטה של הועד"]),
        "decided": money(df["סה~כ סכום עליו החליטה הוועדה"]),
        "paid": money(df["סה~כ שולם מחושב"]),
        "cancelled": money(df["סה~כ סכום שבוטל ע~י הוועדה"]),
        "ministry": clean(df["שם המשרד אליו יועבר התשלום"]).replace("", "לא צוין"),
        "inst": clean(df["שם המוסד אליו יועבר התשלום"]).replace("", "לא צוין"),
    })


def _cases(df):
    return pd.DataFrame({
        "case": df["מספר תיק"].str.strip(),
        "opened": dates(df["תאריך פתיחת התיק"]),
        "status": df["סטטוס ראשי של התיק"].str.strip().replace("", "לא צוין"),
        "closed": dates(df["תאריך סגירה של התיק"]),
        "reason": df["סיבת סגירה של התיק"].str.strip(),
        "hekdesh": df["האם קיים הקדש"].str.strip().str.startswith("אחרת"),
    })


def _purposes(df):
    return pd.DataFrame({
        "case": df["מספר תיק"].str.strip(),
        "topic": clean(df["נושא"]).replace("", "לא צוין"),
        "subject": clean(df["הנושא העיקרי של הייעוד"]).str.rstrip('"').str.strip(),
        "memorial": df["נדרשת הנצחה"].str.strip() == "נדרשת הנצחה",
        "method": df["אופן ביצוע התשלום"].str.strip().replace("", "לא צוין"),
    })


def _allocations(df):
    return pd.DataFrame({
        "case": df["מספר תיק"].str.strip(),
        "alloc": money(df["סכום שהוקצה ע~י וועדת העזבונות"]),
        "paid": money(df["סה~כ שולם"]),
        "cancelled": money(df["סכום שבוטל ע~י הוועדה"]),
    })


# ── insight rules ──────────────────────────────────────────────────────────
def insight_country(dep):
    m = dep.groupby("country")["ils"].sum()
    c = dep.groupby("country").size()
    total, cnt = m.sum(), c.sum()
    if total <= 0:
        return None
    lead = _rank(m).index[0]
    share = m[lead] / total
    if share < 0.25:
        return None
    s = (f"{lead} היא מקור הכסף הגדול ביותר: {money_he(m[lead])} — {pct(share * 100)} "
         f"מסך ההפקדות בשקלים, מתוך {pct(c[lead] / cnt * 100)} בלבד ממספר ההפקדות.")
    by_count = _rank(c).index[0]
    if by_count != lead:
        s += (f" לפי מספר ההפקדות מובילה {by_count} ({n(c[by_count])} הפקדות), "
              f"אך הן קטנות בממוצע.")
    return s


def insight_concentration(dep):
    x = dep.loc[dep["ils"] > 0, "ils"].sort_values(ascending=False, kind="stable")
    k = len(x) // 100
    if k < 5:
        return None
    share = x.head(k).sum() / x.sum()
    if share < 0.3:
        return None
    big = dep.loc[dep["ils"] > 0].sort_values(["ils", "no"], ascending=[False, True]).iloc[0]
    when = f"ב-{big['dt'].year}" if pd.notna(big["dt"]) else ""
    return (f"הכסף מרוכז בהפקדות מעטות: האחוז העליון ({n(k)} הפקדות) מהווה {pct(share * 100)} "
            f"מסך ההפקדות בשקלים, וההפקדה הגדולה ביותר — {money_he(big['ils'])} {when} "
            f"מ{big['country']} — לבדה {pct(big['ils'] / x.sum() * 100)}. "
            f"החציון הוא {n(x.median())} ₪ להפקדה.")


def insight_ytd(dep, ref):
    if ref is None:
        return None
    y = ref.year
    cur = dep[(dep["dt"] >= pd.Timestamp(y, 1, 1)) & (dep["dt"] <= ref)]
    try:
        prev_end = ref.replace(year=y - 1)
    except ValueError:                       # 29 Feb
        prev_end = pd.Timestamp(y - 1, 2, 28)
    prev = dep[(dep["dt"] >= pd.Timestamp(y - 1, 1, 1)) & (dep["dt"] <= prev_end)]
    if len(cur) < 20 or len(prev) < 20 or prev["ils"].sum() <= 0:
        return None
    c, p = cur["ils"].sum(), prev["ils"].sum()
    chg = c / p - 1
    period = f"מתחילת {y} ועד {d_he(ref)}"
    if abs(chg) < 0.1:
        return (f"{period} התקבלו {n(len(cur))} הפקדות בסך {money_he(c)} — בדומה לתקופה "
                f"המקבילה ב-{y - 1} ({money_he(p)}).")
    word = "יותר" if chg > 0 else "פחות"
    return (f"{period} התקבלו {n(len(cur))} הפקדות בסך {money_he(c)} — {pct(abs(chg) * 100)} "
            f"{word} מאשר בתקופה המקבילה ב-{y - 1} ({money_he(p)}, {n(len(prev))} הפקדות).")


def insight_peak(by_year, last_full):
    s = by_year[by_year.index <= last_full]
    if len(s) < 5 or s.sum() <= 0:
        return None
    s = _rank(s)
    y1, v1 = int(s.index[0]), s.iloc[0]
    y2, v2 = int(s.index[1]), s.iloc[1]
    med = by_year[(by_year.index <= last_full) & (by_year.index > last_full - 10)].median()
    return (f"שנות השיא בהפקדות היו {y1} ({money_he(v1)}) ו-{y2} ({money_he(v2)}); "
            f"בעשור האחרון החציון השנתי עומד על {money_he(med)}.")


def insight_ministry(dec):
    m = dec.groupby("ministry")["decided"].sum()
    c = dec.groupby("ministry").size()
    total = m.sum()
    if total <= 0:
        return None
    lead = _rank(m).index[0]
    s = (f"{ministry_he(lead)} מקבל את נתח הכסף הגדול ביותר מהחלטות הוועדה: "
         f"{money_he(m[lead])} ({pct(m[lead] / total * 100)}).")
    by_count = _rank(c).index[0]
    if by_count != lead:
        s += (f" לפי מספר ההקצאות מוביל {ministry_he(by_count)} "
              f"({n(c[by_count])} הקצאות, {pct(c[by_count] / c.sum() * 100)}) — הרבה סכומים קטנים יותר.")
    return s


def insight_backlog(by_year, last_full):
    """Paid share of the latest full decision year vs. all earlier years."""
    if last_full is None or last_full not in by_year.index:
        return None
    row = by_year.loc[last_full]
    old = by_year[by_year.index <= last_full - 5]
    if row["decided"] <= 0 or old["decided"].sum() <= 0 or len(old) < 3:
        return None
    s1 = row["paid"] / row["decided"]
    s0 = old["paid"].sum() / old["decided"].sum()
    if s0 - s1 < 0.15:
        return None
    return (f"מהכסף שהוועדה הקצתה ב-{last_full} שולמו עד כה {pct(s1 * 100)} בלבד, לעומת "
            f"{pct(s0 * 100)} מהכסף שהוקצה עד {last_full - 5} — תשלום ההקצאות נמשך "
            f"שנים אחרי ההחלטה.")


def insight_cancel(by_year):
    s = by_year[by_year["decided"] > 0]
    if len(s) < 3:
        return None
    share = s["cancelled"] / s["decided"]
    tot = s["cancelled"].sum() / s["decided"].sum()
    top = _rank(share).index[0]
    if share[top] < 0.2:
        return None
    return (f"בסך הכול בוטלו {pct(tot * 100)} מהסכומים שהוקצו; השיעור הגבוה ביותר — "
            f"{pct(share[top] * 100)} — בהחלטות {int(top)} ({money_he(s.loc[top, 'cancelled'])} בוטלו).")


def insight_cases(cases, ref_year):
    tot = len(cases)
    if tot == 0:
        return None
    st = cases["status"].value_counts()
    closed = st.get("סגור", 0)
    opn = cases[cases["status"] == "פתוח"]
    if len(opn) < 10:
        return None
    age = (ref_year - opn["opened"].dt.year).dropna()
    old = (age >= 20).mean()
    return (f"{pct(closed / tot * 100)} מתיקי העזבון סגורים ו-{n(len(opn))} פתוחים. "
            f"התיק הפתוח החציוני נפתח לפני {int(age.median())} שנים, ו-{pct(old * 100)} "
            f"מהתיקים הפתוחים נפתחו לפני 20 שנה ויותר.")


def insight_memorial(pur):
    tot = len(pur)
    if tot == 0:
        return None
    share = pur["memorial"].mean()
    g = pur.groupby("topic").agg(n=("memorial", "size"), m=("memorial", "mean"))
    g = g[(g["n"] >= 100) & (g.index != "לא צוין")]
    if g.empty or share < 0.02:
        return None
    best = _rank(g["m"]).index[0]
    return (f"ב-{pct(share * 100)} מהייעודים ({n(pur['memorial'].sum())}) נדרשת הנצחה; "
            f"השיעור הגבוה ביותר בנושא {best} ({pct(g.loc[best, 'm'] * 100)}).")


def insight_mix(mix_share, labels):
    """Topic whose share of file designations grew most between the two
    latest decades on the chart."""
    if len(mix_share) < 2:
        return None
    a, b = mix_share.iloc[-2], mix_share.iloc[-1]
    diff = (b - a).drop("אחר", errors="ignore")
    if diff.empty:
        return None
    diff = _rank(diff)
    t = diff.index[0]
    if diff.iloc[0] < 15:
        return None
    return (f"מטרות העזבונות השתנו: {t} מהווה {pct(b[t])} מהייעודים בתיקים שנפתחו ב-{labels[-1]}, "
            f"לעומת {pct(a[t])} בתיקים של {labels[-2]}.")


def insight_sources(al):
    a = al[al["case"] != "0"].groupby("case")["alloc"].sum()
    tot = al["alloc"].sum()
    if tot <= 0 or len(a) < 20:
        return None
    a = _rank(a)
    k = 3
    share = a.head(k).sum() / tot
    paid = al["paid"].sum() / tot
    if share < 0.25:
        return None
    return (f"בקובץ רכיבי ההקצאות מקורם של {pct(share * 100)} מ-{money_he(tot)} שהוקצו בשלושה "
            f"תיקי עזבון בלבד (מתוך {n(len(a))}); מהסכום הכולל שולמו {pct(paid * 100)}.")


# ── compute ────────────────────────────────────────────────────────────────
def compute(frames):
    dep = _deposits(frames["deposits"])
    dec = _decisions(frames["decisions"])
    cases = _cases(frames["cases"])
    pur = _purposes(frames["purposes"])
    al = _allocations(frames["allocations"])

    # ── deposits ──
    ref = _reference_date(dep["dt"])
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = ref_year - 1 if partial else ref_year
    dv = dep[dep["dt"].notna() & (dep["dt"] <= ref)]
    yr = dv["dt"].dt.year.astype(int)
    by_year_n = dv.groupby(yr).size()
    by_year_ils = dv.groupby(yr)["ils"].sum()
    zero_share = dv.groupby(yr)["ils"].apply(lambda s: float((s <= 0).mean()))
    busy = by_year_n[by_year_n >= 50]
    dep_from = int(busy.index.min()) if len(busy) else int(by_year_n.index.min())
    ils_from_c = zero_share[(zero_share < 0.5) & (zero_share.index >= dep_from)]
    ils_from = int(ils_from_c.index.min()) if len(ils_from_c) else dep_from
    years = list(range(dep_from, ref_year + 1))
    total_ils = float(dep["ils"].sum())
    n_dep = int(dep["no"].nunique())
    countries = dep.loc[dep["country"] != "לא צוין", "country"].nunique()
    zero_total = float((dep["ils"] <= 0).mean())
    before = dv[dv["dt"].dt.year < dep_from]

    c_names, c_vals = _top(dep.groupby("country")["ils"].sum(), TOP_COUNTRIES)
    c_cnt = dep.groupby("country").size()
    top_c = set(c_names) - {"אחר"}
    c_counts = [int(c_cnt[c]) if c != "אחר" else int(c_cnt[~c_cnt.index.isin(top_c)].sum())
                for c in c_names]

    pos = dep[dep["ils"] > 0]
    cur_names, cur_vals = _top(pos.groupby("cur")["ils"].sum(), TOP_CURRENCIES)
    cur_cnt = dep.groupby("cur").size()
    top_cur = set(cur_names) - {"אחר"}
    cur_counts = [int(cur_cnt[c]) if c != "אחר" else int(cur_cnt[~cur_cnt.index.isin(top_cur)].sum())
                  for c in cur_names]

    size_rows = []
    for lo, hi in SIZE_BUCKETS:
        m = pos["ils"] >= lo
        if hi is not None:
            m &= pos["ils"] < hi
        lab = (f"{lo / 1e6:g} מיליון ₪ ומעלה" if hi is None else
               f"עד {hi:,} ₪" if lo == 0 else
               f"{LRI}{lo:,}–{hi:,}{PDI} ₪")
        size_rows.append({"bucket": lab, "count": int(m.sum()), "sum": float(pos.loc[m, "ils"].sum())})
    pos_n, pos_sum = max(len(pos), 1), max(float(pos["ils"].sum()), 1.0)

    # ── cases ──
    oy = cases["opened"].dt.year
    oy_valid = oy[oy.notna() & (oy <= ref_year)].astype(int)
    oc = oy_valid.value_counts()
    busy_c = oc[oc >= 20]
    case_from = int(busy_c.index.min()) if len(busy_c) else int(oc.index.min())
    case_max = int(oy_valid.max())
    statuses = list(_rank(cases["status"].value_counts()).index)
    cy = cases[oy.notna() & (oy >= case_from) & (oy <= ref_year)]
    cyy = cy["opened"].dt.year.astype(int)
    case_years = list(range(case_from, case_max + 1))
    cs = cy.groupby([cyy, "status"]).size().unstack(fill_value=0).reindex(case_years, fill_value=0)
    n_before_cases = int((oy_valid < case_from).sum())
    st_counts = cases["status"].value_counts()
    closed_cases = cases[cases["status"] == "סגור"]
    reasons = closed_cases["reason"].replace("", "לא צוין").value_counts()
    reasons = _rank(reasons)
    hek = int(cases["hekdesh"].sum())

    # ── purposes ──
    topic_cases = pur.drop_duplicates(subset=["case", "topic"]).groupby("topic").size()
    t_names = list(_rank(topic_cases).head(TOP_TOPICS).index)
    # a file counts as "commemoration required" for a topic if any of its
    # designations under that topic asks for it
    ct = pur.groupby(["topic", "case"])["memorial"].any().reset_index()
    memo_cases = ct.groupby("topic")["memorial"].sum()
    topic_rows = []
    for t in t_names:
        yes = int(memo_cases.get(t, 0))
        topic_rows.append({"topic": t, "cases": int(topic_cases[t]), "memo": yes,
                           "nomemo": int(topic_cases[t]) - yes})
    methods = _rank(pur["method"].value_counts())
    subj = pur.loc[pur["subject"] != ""].drop_duplicates(subset=["case", "subject"])
    subj_rank = _rank(subj.groupby("subject").size()).head(TOP_SUBJECTS)
    files_with_purpose = pur["case"].nunique()

    # topic mix by decade the estate file was opened (purposes ⨝ cases)
    tp = pur.drop_duplicates(subset=["case", "topic"]).merge(
        cases[["case", "opened"]], on="case", how="inner")
    tp = tp[tp["opened"].notna() & (tp["opened"].dt.year <= ref_year)]
    tp["decade"] = (tp["opened"].dt.year // 10 * 10).astype(int)
    dec_counts = tp.groupby("decade").size()
    decades = [int(d) for d in sorted(dec_counts[dec_counts >= 100].index)]
    mix_topics = [t for t in _rank(tp.groupby("topic").size()).index if t != "לא צוין"][:MIX_TOPICS]
    tp["mt"] = tp["topic"].where(tp["topic"].isin(mix_topics), "אחר")
    mix = tp[tp["decade"].isin(decades)].groupby(["decade", "mt"]).size().unstack(fill_value=0)
    mix = mix.reindex(decades, fill_value=0)
    mix_cols = mix_topics + (["אחר"] if "אחר" in mix.columns else [])
    mix_share = mix.reindex(columns=mix_cols, fill_value=0).div(mix.sum(axis=1), axis=0) * 100
    max_open = int(tp["opened"].dt.year.max()) if len(tp) else ref_year

    def dec_label(d):
        return f"{d}–{min(d + 9, max_open)}"

    # ── decisions ──
    dd = dec[dec["dt"].notna()]
    dec_ref = dd["dt"].max()
    dec_partial = not (dec_ref.month == 12 and dec_ref.day >= 15)
    dec_last_full = int(dec_ref.year) - 1 if dec_partial else int(dec_ref.year)
    dy = dd["dt"].dt.year.astype(int)
    by_dec = dd.groupby(dy).agg(decided=("decided", "sum"), paid=("paid", "sum"),
                                cancelled=("cancelled", "sum"), rows=("decided", "size"),
                                decisions=("dec_no", "nunique"))
    by_dec["open"] = (by_dec["decided"] - by_dec["paid"] - by_dec["cancelled"]).clip(lower=0)
    dec_busy = by_dec[by_dec["rows"] >= 50]
    dec_from = int(dec_busy.index.min()) if len(dec_busy) else int(by_dec.index.min())
    dec_years = list(range(dec_from, int(dec_ref.year) + 1))
    byd = by_dec.reindex(dec_years, fill_value=0)
    early = by_dec[by_dec.index < dec_from]
    d_total = float(dec["decided"].sum())
    d_paid = float(dec["paid"].sum())
    d_cancel = float(dec["cancelled"].sum())
    d_open = max(d_total - d_paid - d_cancel, 0.0)
    paid_share = d_paid / d_total * 100 if d_total else 0.0

    min_names, min_vals = _top(dec.groupby("ministry")["decided"].sum(), TOP_MINISTRIES)
    min_cnt = dec.groupby("ministry").size()
    top_m = set(min_names) - {"אחר"}
    min_counts = [int(min_cnt[m]) if m != "אחר" else int(min_cnt[~min_cnt.index.isin(top_m)].sum())
                  for m in min_names]
    inst_sum = _rank(dec.groupby("inst")["decided"].sum()).head(TOP_INSTITUTIONS)
    inst_cnt = dec.groupby("inst").size()
    n_inst = dec["inst"].nunique()

    heat_m = list(_rank(dd.groupby("ministry")["decided"].sum()).head(HEAT_MINISTRIES).index)
    hm = dd[dd["ministry"].isin(heat_m) & (dy >= dec_from)]
    hmg = hm.groupby([hm["dt"].dt.year.astype(int), "ministry"])["decided"].sum()
    cells = []
    for yi, m in enumerate(heat_m):
        for xi, y in enumerate(dec_years):
            v = float(hmg.get((y, m), 0.0))
            cells.append([xi, yi, round(v / 1e6, 2)])

    nz = sorted(c[2] for c in cells if c[2] > 0)
    heat_max = nz[min(len(nz) - 1, int(len(nz) * 0.97))] if nz else 1

    # ── allocations ──
    a_tot = float(al["alloc"].sum())
    a_paid = float(al["paid"].sum())
    a_cancel = float(al["cancelled"].sum())
    a_open = max(a_tot - a_paid - a_cancel, 0.0)
    src = _rank(al[al["case"] != "0"].groupby("case")["alloc"].sum())
    src_rows = []
    no_case = float(al.loc[al["case"] == "0", "alloc"].sum())
    for lo, hi in SOURCE_BUCKETS:
        part = src.iloc[lo - 1:] if hi is None else src.iloc[lo - 1:hi]
        if len(part) == 0:
            continue
        if hi is None:
            lab = f"תיקים {LRI}{lo}+{PDI} בדירוג"
        elif lo == hi:
            lab = "התיק הגדול ביותר"
        else:
            lab = f"תיקים {LRI}{lo}–{min(hi, len(src))}{PDI} בדירוג"
        src_rows.append({"bucket": lab, "files": len(part), "sum": float(part.sum())})
    if no_case > 0:
        src_rows.append({"bucket": "ללא תיק משויך", "files": 0, "sum": no_case})
    n_src = len(src)

    # ── insights ──
    rules = [
        ("country", insight_country(dep)),
        ("concentration", insight_concentration(dep)),
        ("ytd", insight_ytd(dv, ref)),
        ("peak", insight_peak(by_year_ils.reindex(years, fill_value=0), last_full)),
        ("ministry", insight_ministry(dec)),
        ("backlog", insight_backlog(by_dec, dec_last_full)),
        ("cancel", insight_cancel(byd[byd["rows"] > 0])),
        ("cases", insight_cases(cases, ref_year)),
        ("memorial", insight_memorial(pur)),
        ("mix", insight_mix(mix_share, [dec_label(d) for d in decades])),
        ("sources", insight_sources(al)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── KPIs ──
    ytd_cur = dv[(dv["dt"] >= pd.Timestamp(ref_year, 1, 1))]["ils"].sum()
    try:
        prev_end = ref.replace(year=ref_year - 1)
    except ValueError:
        prev_end = pd.Timestamp(ref_year - 1, 2, 28)
    ytd_prev = dv[(dv["dt"] >= pd.Timestamp(ref_year - 1, 1, 1)) & (dv["dt"] <= prev_end)]["ils"].sum()
    if ytd_prev > 0:
        ytd_chg = (ytd_cur / ytd_prev - 1) * 100
        ytd_tone = "info" if abs(ytd_chg) < 10 else ("ok" if ytd_chg > 0 else "warn")
        ytd_disp = signed_pct(ytd_chg)
    else:
        ytd_chg, ytd_tone, ytd_disp = None, "brand", "—"
    paid_tone = "ok" if paid_share >= 85 else ("info" if paid_share >= 65 else "warn")
    open_share = st_counts.get("פתוח", 0) / max(len(cases), 1) * 100
    kpis = {
        "deposits_ils": {"value": round(total_ils / 1e9, 2), "display": f"{total_ils / 1e9:,.2f}",
                         "tone": "brand"},
        "deposits": {"value": n_dep, "display": n(n_dep), "tone": "brand"},
        "countries": {"value": int(countries), "display": n(countries), "tone": "brand"},
        "ytd": {"value": None if ytd_chg is None else round(ytd_chg, 1), "display": ytd_disp,
                "tone": ytd_tone},
        "cases": {"value": len(cases), "display": n(len(cases)), "tone": "brand"},
        "open_cases": {"value": int(st_counts.get("פתוח", 0)), "display": n(st_counts.get("פתוח", 0)),
                       "tone": "info"},
        "decided": {"value": round(d_total / 1e6, 1), "display": mil(d_total, 0), "tone": "brand"},
        "paid_share": {"value": round(paid_share, 1), "display": f"{paid_share:.1f}%",
                       "tone": paid_tone},
    }

    # ── charts ──
    charts = {
        "dep_year": {"x": [str(y) for y in years],
                     "ils": [round(float(by_year_ils.get(y, 0.0)) / 1e6, 2) for y in years],
                     "n": [int(by_year_n.get(y, 0)) for y in years],
                     "partial": str(ref_year) if partial else None},
        "countries": {"names": c_names, "values": [round(v / 1e6, 2) for v in c_vals],
                      "counts": c_counts},
        "currencies": {"names": cur_names, "values": [round(v / 1e6, 2) for v in cur_vals]},
        "sizes": {"names": [r["bucket"] for r in size_rows],
                  "n": [round(r["count"] / pos_n * 100, 1) for r in size_rows],
                  "sum": [round(r["sum"] / pos_sum * 100, 1) for r in size_rows]},
        "case_year": {"x": [str(y) for y in case_years],
                      "series": [{"name": s, "data": [int(v) for v in cs[s]]}
                                 for s in statuses if s in cs.columns]},
        "status": {"names": statuses, "values": [int(st_counts[s]) for s in statuses]},
        "topics": {"names": [r["topic"] for r in topic_rows],
                   "memo": [r["memo"] for r in topic_rows],
                   "nomemo": [r["nomemo"] for r in topic_rows]},
        "methods": {"names": list(methods.index), "values": [int(v) for v in methods.values]},
        "mix": {"x": [f"{LRI}{dec_label(d)}{PDI}" for d in decades],
                "series": [{"name": c, "data": [round(float(v), 1) for v in mix_share[c]]}
                           for c in mix_cols]},
        "dec_year": {"x": [str(y) for y in dec_years],
                     "paid": [round(float(v) / 1e6, 2) for v in byd["paid"]],
                     "cancelled": [round(float(v) / 1e6, 2) for v in byd["cancelled"]],
                     "open": [round(float(v) / 1e6, 2) for v in byd["open"]],
                     "n": [int(v) for v in byd["decisions"]]},
        "ministries": {"names": min_names, "values": [round(v / 1e6, 2) for v in min_vals]},
        "institutions": {"names": list(inst_sum.index),
                         "values": [round(float(v) / 1e6, 2) for v in inst_sum.values]},
        "heat": {"x": [str(y) for y in dec_years], "y": heat_m, "cells": cells,
                 # colour scale tops out at the 97th percentile of non-zero
                 # cells so one record year doesn't wash out the rest
                 "max": heat_max},
        "execution": {"names": ["שולם", "בוטל", "טרם שולם"],
                      "values": [round(a_paid / 1e6, 1), round(a_cancel / 1e6, 1), round(a_open / 1e6, 1)]},
        "sources": {"names": [r["bucket"] for r in src_rows],
                    "values": [round(r["sum"] / 1e6, 1) for r in src_rows]},
    }

    tables = {
        "countries": [{"name": nm, "ils": mil(v), "count": n(c)}
                      for nm, v, c in zip(c_names, c_vals, c_counts)],
        "currencies": [{"name": nm, "ils": mil(v), "count": n(c)}
                       for nm, v, c in zip(cur_names, cur_vals, cur_counts)],
        "sizes": [{"bucket": r["bucket"], "count": n(r["count"]),
                   "count_share": f"{r['count'] / pos_n * 100:.1f}%",
                   "sum_share": f"{r['sum'] / pos_sum * 100:.1f}%"} for r in size_rows],
        "status": [{"name": s, "count": n(st_counts[s]),
                    "share": f"{st_counts[s] / len(cases) * 100:.1f}%"} for s in statuses],
        "reasons": [{"name": k, "count": n(v)} for k, v in reasons.items()],
        "topics": [{"topic": r["topic"], "cases": n(r["cases"]), "memo": n(r["memo"])}
                   for r in topic_rows],
        "methods": [{"name": k, "count": n(v), "share": f"{v / len(pur) * 100:.1f}%"}
                    for k, v in methods.items()],
        "subjects": [{"name": k, "count": n(v)} for k, v in subj_rank.items()],
        "mix": [{"decade": dec_label(d), "cells": [f"{mix_share.loc[d, c]:.1f}%" for c in mix_cols]}
                for d in decades],
        "mix_cols": mix_cols,
        "dec_year": [{"year": str(y), "decided": mil(byd.loc[y, "decided"]), "paid": mil(byd.loc[y, "paid"]),
                      "cancelled": mil(byd.loc[y, "cancelled"]), "decisions": n(byd.loc[y, "decisions"])}
                     for y in dec_years],
        "ministries": [{"name": nm, "ils": mil(v), "count": n(c)}
                       for nm, v, c in zip(min_names, min_vals, min_counts)],
        "institutions": [{"name": k, "ils": mil(v), "count": n(inst_cnt[k])} for k, v in inst_sum.items()],
        "execution": [{"name": nm, "ils": mil(v * 1e6), "share": f"{v * 1e6 / a_tot * 100:.1f}%" if a_tot else "—"}
                      for nm, v in zip(charts["execution"]["names"], [a_paid / 1e6, a_cancel / 1e6, a_open / 1e6])],
        "sources": [{"bucket": r["bucket"], "files": n(r["files"]) if r["files"] else "—",
                     "ils": mil(r["sum"]), "share": f"{r['sum'] / a_tot * 100:.1f}%" if a_tot else "—"}
                    for r in src_rows],
    }

    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    dec_partial_note = (f" {dec_ref.year} — שנה חלקית, עד {d_he(dec_ref)}." if dec_partial else "")
    before_note = (f" {n(len(before))} הפקדות מוקדמות יותר (לפני {dep_from}) אינן מוצגות בגרף."
                   if len(before) else "")
    early_note = (f" {n(early['rows'].sum())} הקצאות מוקדמות יותר (לפני {dec_from}) אינן מוצגות."
                  if len(early) else "")
    labels = {
        "lede": (f"מחלקת העזבונות לטובת המדינה אצל האפוטרופוס הכללי מקבלת עזבונות ותרומות מישראל "
                 f"ומ-{n(countries)} מדינות, וּועדה ציבורית מקצה אותם לגופים ללא כוונת רווח דרך משרדי "
                 f"הממשלה. במאגר {n(n_dep)} הפקדות בסך {money_he(total_ils)} (ההפקדה האחרונה: "
                 f"{d_he(ref)}), {n(len(cases))} תיקי עזבון ו-{n(len(dec))} הקצאות של הוועדה בסך "
                 f"{money_he(d_total)} — ההחלטה האחרונה המדווחת במאגר מ-{d_he(dec_ref)}. "
                 f"כל הנתונים בדף מצרפיים; אין בו פרטים על מורישים."),
        "deposits_ils_kpi": "סך ההפקדות (מיליארד ₪)",
        "ytd_kpi": (f"הפקדות בשקלים מתחילת {ref_year} לעומת התקופה המקבילה ב-{ref_year - 1}"
                    if ytd_chg is not None else "שינוי בהפקדות מתחילת השנה"),
        "decided_kpi": "הוקצו בהחלטות הוועדה (מיליון ₪)",
        "paid_kpi": "מהסכום שהוקצה כבר שולם",
        "open_kpi": f"תיקים פתוחים ({open_share:.1f}% מהתיקים)",
        "dep_year_note": (f"סכום ההפקדות בשקלים (עמודות) ומספר ההפקדות (קו) לפי שנת הקבלה, מ-{dep_from}. "
                          f"עד {ils_from} רוב ההפקדות רשומות ללא סכום מומר לשקלים, ולכן העמודות בשנים "
                          f"אלה נמוכות; בסך הכול {pct(zero_total * 100)} מההפקדות ללא סכום בשקלים."
                          f"{before_note}{partial_note}"),
        "dep_year_aria": (f"גרף משולב: סכום ההפקדות במיליוני ₪ ומספר ההפקדות לפי שנה, {dep_from} עד {ref_year}."),
        "countries_note": "סכום ההפקדות לפי מדינת המקור של התורם או המוריש, במיליוני ₪.",
        "countries_aria": f"תרשים עמודות: {TOP_COUNTRIES} מדינות המקור לפי סכום ההפקדות במיליוני ₪.",
        "countries_caption": f"{TOP_COUNTRIES} מדינות המקור המובילות לפי סכום, ואחר.",
        "currencies_note": ("המטבע שבו התקבלה ההפקדה, לפי הסכום המומר לשקלים. מטבעות שהוחלפו ביורו "
                            "(פרנק צרפתי, מרק גרמני ועוד) מופיעים בהפקדות ישנות ללא סכום מומר."),
        "currencies_aria": f"תרשים עמודות: סכום ההפקדות במיליוני ₪ לפי מטבע המקור ({TOP_CURRENCIES} המובילים).",
        "currencies_caption": "סכום ההפקדות ומספרן לפי מטבע המקור.",
        "sizes_note": (f"התפלגות {n(len(pos))} ההפקדות שיש להן סכום בשקלים: איזה חלק מההפקדות "
                       f"ואיזה חלק מהכסף נופל בכל טווח."),
        "sizes_aria": "תרשים עמודות כפול: שיעור ההפקדות ושיעור הכסף בכל טווח גודל הפקדה.",
        "sizes_caption": "שיעור ההפקדות ושיעור הכסף לפי גודל ההפקדה.",
        "case_year_note": (f"מספר תיקי העזבון לפי שנת הפתיחה ולפי הסטטוס הנוכחי שלהם, מ-{case_from}."
                           + (f" {n(n_before_cases)} תיקים שנפתחו לפני כן אינם מוצגים." if n_before_cases else "")),
        "case_year_aria": f"גרף עמודות מוערמות: תיקי עזבון לפי שנת פתיחה וסטטוס, {case_from} עד {case_max}.",
        "status_note": (f"{n(hek)} תיקים ({pct(hek / max(len(cases), 1) * 100)}) כוללים הקדש. "
                        f"סיבת הסגירה רשומה ב-{pct((closed_cases['reason'] != '').mean() * 100 if len(closed_cases) else 0)} "
                        f"מהתיקים הסגורים."),
        "status_aria": f"תרשים עמודות: {n(len(cases))} תיקי עזבון לפי סטטוס.",
        "status_caption": "תיקי עזבון לפי סטטוס.",
        "reasons_caption": "תיקים סגורים לפי סיבת הסגירה.",
        "topics_note": (f"הנושאים שהמורישים ייעדו להם את כספם, לפי מספר התיקים ({n(files_with_purpose)} "
                        f"תיקים עם ייעוד), ומהם תיקים שבהם נדרשת הנצחה."),
        "topics_aria": f"תרשים עמודות מוערמות: מספר התיקים ב-{TOP_TOPICS} נושאי הייעוד הנפוצים, עם ובלי דרישת הנצחה.",
        "topics_caption": "נושאי הייעוד: מספר תיקים, ומהם תיקים שבהם נדרשת הנצחה.",
        "methods_note": "האם הכסף מחולק דרך הוועדה הציבורית או מועבר ישירות מהמחלקה, לפי הוראות העזבון.",
        "methods_aria": "תרשים עמודות: ייעודים לפי אופן ביצוע התשלום.",
        "methods_caption": "ייעודים לפי אופן ביצוע התשלום.",
        "subjects_caption": f"{TOP_SUBJECTS} הנושאים העיקריים המפורטים של הייעוד, לפי מספר תיקים.",
        "mix_note": ("חלקו של כל נושא מבין ייעודי התיקים, לפי העשור שבו נפתח התיק — כך רואים כיצד "
                     "השתנו מטרות העזבונות לאורך השנים."),
        "mix_aria": f"תרשים עמודות 100%: התפלגות נושאי הייעוד לפי עשור פתיחת התיק, {len(decades)} עשורים.",
        "mix_caption": "שיעור כל נושא מבין ייעודי התיקים, לפי עשור הפתיחה.",
        "dec_year_note": (f"הסכום שהוועדה הקצתה בכל שנה, לפי מה שכבר שולם, מה שבוטל ומה שטרם שולם "
                          f"(מיליוני ₪), ומספר ההחלטות (קו). הקצאות משנים אחרונות עדיין בתשלום."
                          f"{early_note}{dec_partial_note}"),
        "dec_year_aria": f"גרף עמודות מוערמות: הקצאות הוועדה לפי שנה ומצב התשלום, {dec_from} עד {dec_ref.year}.",
        "dec_year_caption": "הקצאות הוועדה לפי שנת ההחלטה (מיליוני ₪) ומספר ההחלטות.",
        "ministries_aria": f"תרשים עמודות: {TOP_MINISTRIES} המשרדים שדרכם הועברו ההקצאות, במיליוני ₪.",
        "ministries_caption": "סכום ההקצאות ומספרן לפי המשרד המעביר.",
        "institutions_note": (f"הגופים שקיבלו את הסכומים הגדולים ביותר מבין {n(n_inst)} מוסדות "
                              f"(כולל משרדי ממשלה שקיבלו ישירות)."),
        "institutions_aria": f"תרשים עמודות: {TOP_INSTITUTIONS} המוסדות המקבלים לפי סכום, במיליוני ₪.",
        "institutions_caption": f"{TOP_INSTITUTIONS} המוסדות שקיבלו את הסכומים הגדולים ביותר.",
        "heat_note": (f"הסכום שהוקצה בכל שנה דרך {HEAT_MINISTRIES} המשרדים הגדולים, במיליוני ₪. "
                      f"שנים בולטות משקפות לרוב הקצאה גדולה אחת; סולם הצבע נעצר ב-{heat_max:,.1f} מיליון ₪, וערכים גבוהים ממנו מוצגים בגוון הכהה ביותר."),
        "heat_aria": f"מפת חום: הקצאות לפי משרד ({HEAT_MINISTRIES} הגדולים) ושנה, במיליוני ₪.",
        "execution_note": (f"קובץ רכיבי ההחלטות מפרט מאילו תיקי עזבון (ברמת החשבון) מומנה כל הקצאה — "
                           f"{money_he(a_tot)} בסך הכול, גם מפרוטוקולים שאינם בקובץ ההחלטות."),
        "execution_aria": "תרשים עוגה: הסכום שהוקצה לפי מצב: שולם, בוטל, טרם שולם.",
        "execution_caption": "סכומי ההקצאות לפי מצב התשלום.",
        "sources_note": (f"כמה מהכסף שהוקצה מקורו בתיקי העזבון הגדולים: {n(n_src)} תיקים מדורגים לפי "
                         f"הסכום שהוקצה מהם."),
        "sources_aria": "תרשים עמודות: סכום ההקצאות לפי דירוג תיק העזבון שממנו מומנו.",
        "sources_caption": "סכום ההקצאות לפי קבוצת דירוג של תיק המקור.",
    }

    t0 = min(dep_from, case_from)
    return {
        "agent_data": {
            "summary_he": (f"עזבונות ותרומות לטובת מדינת ישראל: {n(n_dep)} הפקדות בסך {money_he(total_ils)} "
                           f"מ-{n(countries)} מדינות, {n(len(cases))} תיקי עזבון וייעודיהם, והחלטות ועדת "
                           f"העזבונות על הקצאת {money_he(d_total)} לגופים ציבוריים."),
            "dataset_kind": "misc",
            "suggested_tags": ["עזבונות", "תרומות", "האפוטרופוס הכללי", "ועדת העזבונות",
                               "משרד המשפטים", "הקדשות"],
            "related_ids": ["01aeaf5c-59a2-4ddc-a616-31b85621bfe2",
                            "669b2652-f75b-4de3-8e6b-0dfa17accef5",
                            "3111ae54-790a-4d02-9750-d51e1134b405"],
            "temporal_coverage": f"{t0}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל ותורמים מרחבי העולם",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
