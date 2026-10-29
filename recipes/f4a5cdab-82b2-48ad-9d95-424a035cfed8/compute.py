"""Be'er Sheva municipality tenders (מכרזים בעיר באר שבע).

One table: a row per published procedure (tender, call for proposals,
single-supplier notice, ...), with a submission deadline, a last-update
date, an optional winner and an optional online-payment link.

"Now" is never the wall clock: the reference date is the LATEST
"תאריך עדכון" in the data (the municipality's last update to the list).
A procedure is "open" when its deadline falls on/after that date.
"""
import html
import re

import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
# pandas dayofweek: Monday=0 … Sunday=6 → displayed Sunday-first.
WEEKDAYS_HE = {6: "ראשון", 0: "שני", 1: "שלישי", 2: "רביעי",
               3: "חמישי", 4: "שישי", 5: "שבת"}
WEEKDAY_ORDER = [6, 0, 1, 2, 3, 4, 5]

# Procedure type — first matching rule wins (name + number text).
TYPE_RULES = [
    ("ספק יחיד / הודעת כוונה", r"ספק יחיד|כוונה להתקשר|כוונת העירייה|כוונה להכריז|הודעת כוונה"),
    ("מיזם משותף", r"מיזם משותף"),
    ("קול קורא / מאגר", r"קול קורא|מאגר|להיכלל"),
    ("משא ומתן", r"מו\"מ|מו״מ|משא ומתן"),
    ("הצעות מחיר", r"הצעות? מחיר|הצעת מחיר"),
]
TYPE_OTHER = "מכרז / הליך רגיל"
TYPE_ORDER = [t for t, _ in TYPE_RULES] + [TYPE_OTHER]

# Topic — keyword classification of the procedure name; first match wins.
TOPIC_RULES = [
    ("נכסים: השכרה ומכירה", r"השכרת|השכרה|מכירת|למכירת|מגרש|נכס|נכסים|מזנון|מסעדה|שטחים מסחריים|מקלט"),
    ("תברואה וסביבה", r"פסולת|ניקיון|נקיון|גזם|חתול|הדברה|כלבים|סביבה|מחזור|גינון"),
    ("הסעות, חניה ותחבורה", r"הסעות|הסעת|חניה|חנייה|רכב|מוניות|תחבורה|אוטובוס"),
    ("חינוך", r"חינוך|בית ספר|בית הספר|בתי ספר|בתי הספר|תלמיד|גני ילדים|גן ילדים|מעונות|לימוד"),
    ("רווחה וקהילה", r"רווחה|קשיש|ותיקים|נכים|מוגבלות|קהיל|נוער|נערות|משפחות|צעירים|עמותת|טיפול|התמכר|מועדונית|עיוור|לקויי|שיקום|ילדי"),
    ("ביטחון וחירום", r"מיגונית|מיגוניות|שמירה|אבטחה|חירום|ביטחון|בטחון|מצלמות"),
    ("פרסום ומדיה", r"מקומון|רדיו|עיתונ|מודעות|שילוט|קמפיין|צילום|הקלטה|תמלול"),
    ("ייעוץ ושירותים מקצועיים", r"ייעוץ|יועצים|יועץ|ליווי|חשבונא|משפטי|ביקורת|תכנון|פיקוח|מידע|תוכנה|דיגיטל|סקר|מיון|דואר|חקירות|מדידות|שכר|קורס|הדרכ"),
    ("תשתיות, בינוי ואחזקה", r"עבודות|אחזקה|תחזוקה|חשמל|מעליות|כביש|פיתוח|תאורה|ביוב|שיפוץ|הקמה|הקמת|התקנה|התקנת|מערכות|מבנה"),
    ("תרבות, ספורט ופנאי", r"תרבות|ספורט|אירוע|מופע|פסטיבל|ספרי|מוזיאון|פנאי|קייטנ"),
    ("אספקה וציוד", r"אספקה|אספקת|ריהוט|ציוד|רכישת|מזון|הדפסה|דפוס|ביגוד"),
]
TOPIC_OTHER = "אחר"
TOPIC_ORDER = [t for t, _ in TOPIC_RULES] + [TOPIC_OTHER]

PAY_PROVIDERS = [("citypay", "סיטיפיי"), ("paykal", "פייקל")]
PAY_OTHER = "מערכת אחרת"
PAY_NONE = "ללא קישור לתשלום"

LEAD_BUCKETS = [(0, 7, "עד שבוע"), (8, 14, "8-14 ימים"), (15, 21, "15-21 ימים"),
                (22, 30, "22-30 ימים"), (31, 45, "31-45 ימים"), (46, 60, "46-60 ימים"),
                (61, 10 ** 6, "מעל 60 ימים")]

MAX_OPEN_ROWS = 25
RECENT_CLOSED_ROWS = 10
TOP_WINNERS = 10
MUNI_URL_RE = re.compile(r"^https?://(www\.)?beer-sheva\.muni\.il/[\w/.\-]+\?ID=\d+$")


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _date(ts):
    return f"{ts.day}.{ts.month}.{ts.year}"


def _clean(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_dt(series):
    s = series.str.strip()
    out = pd.to_datetime(s, format="%d/%m/%Y %H:%M:%S", errors="coerce")
    alt = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    return out.fillna(alt)


def _classify(text, rules, other):
    for label, rx in rules:
        if re.search(rx, text):
            return label
    return other


def _pay_provider(url):
    u = url.strip().lower()
    if not u:
        return PAY_NONE
    for key, label in PAY_PROVIDERS:
        if key in u:
            return label
    return PAY_OTHER


def _muni_link(url):
    u = url.strip()
    if not MUNI_URL_RE.match(u):
        return None
    return re.sub(r"^http://", "https://", u)


def _prepare(df):
    df = df.copy()
    df["name"] = df["שם מכרז"].map(_clean)
    df["number"] = df["מספר מכרז"].map(_clean)
    df["deadline"] = _parse_dt(df["תאריך אחרון להגשה"])
    df["updated"] = _parse_dt(df["תאריך עדכון"])
    df["winner"] = df["זוכה במכרז"].map(_clean)
    df["has_winner"] = df["winner"] != ""
    df["files"] = df["קבצים"].str.count(r"<a\s")
    df["pay"] = df["תשלום מקוון"].map(_pay_provider)
    df["link"] = df["URL"].map(_muni_link)
    df["rid"] = pd.to_numeric(df["URL"].str.extract(r"ID=(\d+)")[0], errors="coerce").fillna(-1).astype(int)
    text = df["name"] + " " + df["number"]
    df["ptype"] = text.map(lambda t: _classify(t, TYPE_RULES, TYPE_OTHER))
    df["topic"] = df["name"].map(lambda t: _classify(t, TOPIC_RULES, TOPIC_OTHER))
    seq = df["number"].str.extract(r"(\d{1,4})\s*[/\-]\s*(\d{4}|\d{2})(?!\d)")
    df["num_seq"] = pd.to_numeric(seq[0], errors="coerce")
    ny = pd.to_numeric(seq[1], errors="coerce")
    df["num_year"] = ny.where(ny >= 1000, ny + 2000)
    df = df[df["name"] != ""]
    # Total order for every downstream sort: deadline, then list item id, then name.
    df = df.sort_values(["deadline", "rid", "name", "number"], kind="stable", na_position="first")
    return df.reset_index(drop=True)


def _row(r):
    return {
        "name": r["name"],
        "number": r["number"] or "–",
        "deadline": _date(r["deadline"]),
        "time": f"{r['deadline'].hour:02d}:{r['deadline'].minute:02d}",
        "ptype": r["ptype"],
        "pay": r["pay"] != PAY_NONE,
        "link": r["link"],
        "winner": r["winner"],
    }


# ── insight rules ────────────────────────────────────────────────────────

def insight_open(open_df, ref):
    n = len(open_df)
    if n == 0:
        return (f"נכון לעדכון האחרון במאגר ({_date(ref)}) אין הליכים שמועד ההגשה שלהם טרם חלף.")
    nxt = open_df["deadline"].min()
    last = open_df["deadline"].max()
    same = int((open_df["deadline"].dt.normalize() == nxt.normalize()).sum())
    s = (f"נכון לעדכון האחרון במאגר ({_date(ref)}) פתוחים להגשה {_int(n)} הליכים; "
         f"המועד הקרוב ביותר הוא {_date(nxt)}")
    if same > 1:
        s += f" ({_int(same)} הליכים נסגרים בו)"
    if last.normalize() != nxt.normalize():
        s += f", והאחרון נסגר ב-{_date(last)}"
    return s + "."


def insight_ytd(df, ref):
    y = ref.year
    cur = df[(df["deadline"] >= pd.Timestamp(y, 1, 1)) & (df["deadline"] <= ref)]
    try:
        prev_ref = ref.replace(year=y - 1)
    except ValueError:  # 29 Feb
        prev_ref = ref.replace(year=y - 1, day=28)
    prev = df[(df["deadline"] >= pd.Timestamp(y - 1, 1, 1)) & (df["deadline"] <= prev_ref)]
    a, b = len(cur), len(prev)
    if b < 10:
        return None
    ch = (a - b) / b
    period = f"מתחילת {y} ועד {_date(ref)}"
    if abs(ch) < 0.05:
        return (f"{period} חלף מועד ההגשה של {_int(a)} הליכים, "
                f"כמעט כמו בתקופה המקבילה ב-{y - 1} ({_int(b)}).")
    word = "יותר" if ch > 0 else "פחות"
    return (f"{period} חלף מועד ההגשה של {_int(a)} הליכים, {_pct(abs(ch), 0)} {word} "
            f"מאשר בתקופה המקבילה ב-{y - 1} ({_int(b)}).")


def insight_peak_year(yearly, partial_year):
    # The current (reference) year is in progress and the first year is the
    # list's start-up year — both excluded, and the sentence says so.
    full = yearly.drop(index=[partial_year, int(yearly.index.min())], errors="ignore")
    if len(full) < 3:
        return None
    top_y = int(full.sort_index().idxmax())
    low_y = int(full.sort_index().idxmin())
    return (f"השנה העמוסה ביותר הייתה {top_y} עם {_int(full[top_y])} הליכים; "
            f"השקטה ביותר הייתה {low_y}, עם {_int(full[low_y])} (ללא השנה הראשונה במאגר והשנה הנוכחית).")


def insight_types(type_counts, total):
    if total == 0:
        return None
    reg = int(type_counts.get(TYPE_OTHER, 0))
    others = type_counts.drop(index=[TYPE_OTHER], errors="ignore")
    others = others[others > 0]
    if others.empty:
        return None
    name, v = others.index[0], int(others.iloc[0])
    if v / total < 0.05:
        return None
    return (f"לא כל רשומה היא מכרז פומבי רגיל: {_pct(reg / total, 0)} הם מכרזים והליכים רגילים, "
            f"והסוג החריג הנפוץ ביותר הוא „{name}”: {_int(v)} רשומות ({_pct(v / total)}). "
            f"(סיווג לפי מילות מפתח בשם ובמספר ההליך)")


def insight_topic(topic_counts, total):
    t = topic_counts.drop(index=[TOPIC_OTHER], errors="ignore")
    t = t[t > 0]
    if t.empty or total == 0:
        return None
    name, v = t.index[0], int(t.iloc[0])
    if v / total < 0.12:
        return None
    s = f"התחום הנפוץ ביותר הוא „{name}” עם {_int(v)} הליכים ({_pct(v / total)} מהמאגר)"
    if len(t) > 1:
        s += f", ואחריו „{t.index[1]}” ({_int(t.iloc[1])})"
    return s + ". (סיווג לפי מילות מפתח בשם ההליך)"


def insight_weekday(df):
    d = df.dropna(subset=["deadline"])
    if len(d) < 20:
        return None
    wd = d["deadline"].dt.dayofweek.value_counts()
    top = int(sorted(wd.index, key=lambda k: (-wd[k], WEEKDAY_ORDER.index(k)))[0])
    share = wd[top] / len(d)
    if share < 0.35:
        return None
    noon = (d["deadline"].dt.hour == 12) & (d["deadline"].dt.minute == 0)
    s = f"{_pct(share, 0)} ממועדי ההגשה נקבעו ליום {WEEKDAYS_HE[top]}"
    if noon.mean() >= 0.5:
        s += f", ו-{_pct(noon.mean(), 0)} מהם בשעה 12:00 בצהריים"
    return s + "."


def insight_winner(closed, ref):
    old = closed[closed["deadline"] <= ref - pd.Timedelta(days=180)]
    if len(old) < 30:
        return None
    share = old["has_winner"].mean()
    return (f"זוכה מפורסם רק ב-{_pct(share, 0)} מההליכים שמועד ההגשה שלהם חלף לפני יותר מחצי שנה "
            f"({_int(old['has_winner'].sum())} מתוך {_int(len(old))}). בשאר ההליכים שדה הזוכה ריק.")


def insight_top_winner(winners):
    if winners.empty or int(winners.iloc[0]) < 3:
        return None
    top = winners[winners == winners.iloc[0]]
    names = list(top.index[:3])
    if len(names) == 1:
        return f"הזוכה התכוף ביותר הוא {names[0]}, עם {_int(winners.iloc[0])} הליכים."
    return (f"אין זוכה דומיננטי: הזוכים התכופים ביותר ({', '.join(names)}"
            f"{' ועוד' if len(top) > 3 else ''}) זכו כל אחד ב-{_int(winners.iloc[0])} הליכים בלבד.")


def insight_payment(pay_year):
    """Which payment system leads now vs. the earliest year with real volume."""
    named = [lab for _, lab in PAY_PROVIDERS] + [PAY_OTHER]
    rows = []
    for y in sorted(pay_year.index):
        c = {k: int(pay_year.loc[y].get(k, 0)) for k in named}
        if sum(c.values()) >= 10:  # ignore years with only a handful of links
            rows.append((int(y), max(named, key=lambda k: (c[k], -named.index(k)))))
    if len(rows) < 3:
        return None
    first_p, last_p = rows[0][1], rows[-1][1]
    if first_p == last_p or PAY_OTHER in (first_p, last_p):
        return None
    i = len(rows) - 1
    while i > 0 and rows[i - 1][1] == last_p:
        i -= 1
    switch = rows[i][0]
    return (f"התשלום המקוון עבר בין מערכות: עד {switch - 1} הובילה „{first_p}”, "
            f"ומאז {switch} רוב הקישורים לתשלום מפנים ל„{last_p}”. "
            f"(שנים עם עשרה קישורים לפחות)")


def insight_numbering(df, ref):
    y = ref.year - 1
    d = df[df["num_year"] == y]
    if len(d) < 15:
        return None
    mx = int(d["num_seq"].max())
    n = int(d["num_seq"].nunique())
    if mx < n * 1.25:
        return None
    return (f"מספרי ההליכים של {y} מגיעים עד {_int(mx)}, אך במאגר מופיעים רק {_int(n)} מספרים שונים "
            f"מאותה שנה, כלומר לא כל ההליכים הממוספרים מפורסמים ברשימה זו.")


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["tenders"])
    total = len(df)
    dated = df.dropna(subset=["deadline"])
    ref = df["updated"].max()
    if pd.isna(ref):
        ref = dated["deadline"].max()
    ref = ref.normalize()

    open_df = dated[dated["deadline"].dt.normalize() >= ref].sort_values(
        ["deadline", "rid", "name"], kind="stable")
    closed = dated[dated["deadline"].dt.normalize() < ref]
    recent_closed = closed.sort_values(["deadline", "rid", "name"], ascending=[False, False, True],
                                       kind="stable").head(RECENT_CLOSED_ROWS)

    years = dated["deadline"].dt.year.astype(int)
    y_min, y_max = int(years.min()), int(years.max())
    year_list = list(range(y_min, y_max + 1))
    yearly = years.value_counts().reindex(year_list, fill_value=0).sort_index()
    partial_year = ref.year  # the reference year is in progress

    # Yearly stacked by procedure type
    yt = pd.crosstab(years, dated["ptype"]).reindex(index=year_list, fill_value=0)
    type_counts = df["ptype"].value_counts().reindex(TYPE_ORDER, fill_value=0)
    type_counts = type_counts.sort_values(ascending=False, kind="stable")
    types_present = [t for t in TYPE_ORDER if type_counts.get(t, 0) > 0]
    year_labels = [f"{y} (חלקית)" if y == partial_year else str(y) for y in year_list]
    chart_yearly = {
        "x": year_labels,
        "series": [{"name": t, "data": [int(yt.loc[y].get(t, 0)) if t in yt.columns else 0
                                         for y in year_list]} for t in types_present],
        "totals": [int(v) for v in yearly],
    }

    # Topics
    topic_counts = df["topic"].value_counts().reindex(TOPIC_ORDER, fill_value=0)
    topic_sorted = topic_counts.drop(index=[TOPIC_OTHER]).sort_values(ascending=False, kind="stable")
    topic_sorted = topic_sorted[topic_sorted > 0]
    topic_names = list(topic_sorted.index) + ([TOPIC_OTHER] if topic_counts[TOPIC_OTHER] > 0 else [])
    topic_vals = [int(topic_counts[t]) for t in topic_names]
    open_topics = open_df["topic"].value_counts()
    chart_topics = {"names": topic_names, "values": topic_vals,
                    "open": [int(open_topics.get(t, 0)) for t in topic_names]}

    # Month × year heatmap of deadlines
    mm = dated.assign(y=years, m=dated["deadline"].dt.month)
    mt = mm.groupby(["y", "m"]).size()
    cells = [[m - 1, i, int(mt.get((y, m), 0))] for i, y in enumerate(year_list) for m in range(1, 13)]
    by_month = mm["m"].value_counts().reindex(range(1, 13), fill_value=0)
    chart_heat = {"months": MONTHS_HE, "years": [str(y) for y in year_list], "cells": cells,
                  "max": int(max(c[2] for c in cells)) if cells else 0}

    # Weekday of deadline
    wd = dated["deadline"].dt.dayofweek.value_counts()
    chart_weekday = {"names": [WEEKDAYS_HE[k] for k in WEEKDAY_ORDER],
                     "values": [int(wd.get(k, 0)) for k in WEEKDAY_ORDER]}

    # Lead time: update date → deadline (only rows updated before the deadline)
    lead = (dated["deadline"].dt.normalize() - dated["updated"].dt.normalize()).dt.days
    lead = lead[lead >= 0]
    chart_lead = {"names": [b[2] for b in LEAD_BUCKETS],
                  "values": [int(((lead >= lo) & (lead <= hi)).sum()) for lo, hi, _ in LEAD_BUCKETS]}
    lead_median = int(lead.median()) if len(lead) else 0

    # Winner published share per deadline year (closed procedures only)
    cy = closed["deadline"].dt.year.astype(int)
    wy = closed.groupby(cy)["has_winner"].agg(["sum", "count"]).reindex(year_list, fill_value=0)
    chart_winner = {"x": [str(y) for y in year_list],
                    "with": [int(v) for v in wy["sum"]],
                    "without": [int(c - s) for s, c in zip(wy["sum"], wy["count"])],
                    "share": [round(float(s / c) * 100, 1) if c else 0.0
                              for s, c in zip(wy["sum"], wy["count"])]}

    # Top winners
    wcount = df.loc[df["has_winner"], "winner"].value_counts()
    wcount = wcount.sort_index().sort_values(ascending=False, kind="stable")
    top_w = wcount[wcount >= 2].head(TOP_WINNERS)
    chart_winners = {"names": list(top_w.index), "values": [int(v) for v in top_w]}

    # Online payment per year
    pay_order = [lab for _, lab in PAY_PROVIDERS] + [PAY_OTHER, PAY_NONE]
    py = pd.crosstab(years, dated["pay"]).reindex(index=year_list, fill_value=0)
    for p in pay_order:
        if p not in py.columns:
            py[p] = 0
    pays_present = [p for p in pay_order if int(py[p].sum()) > 0]
    chart_pay = {"x": [str(y) for y in year_list],
                 "series": [{"name": p, "data": [int(v) for v in py[p]]} for p in pays_present]}

    # KPIs
    n_open = len(open_df)
    has_pay = df["pay"] != PAY_NONE
    old_closed = closed[closed["deadline"] <= ref - pd.Timedelta(days=180)]
    win_share = float(old_closed["has_winner"].mean()) if len(old_closed) else 0.0
    ytd_cur = int(((dated["deadline"] >= pd.Timestamp(ref.year, 1, 1)) & (dated["deadline"] <= ref)).sum())
    next_dl = open_df["deadline"].min() if n_open else None
    kpis = {
        "open": {"value": n_open, "display": _int(n_open), "tone": "ok" if n_open else "warn"},
        "next": {"value": _date(next_dl) if n_open else None,
                 "display": f"{next_dl.day}.{next_dl.month}" if n_open else "–",
                 "tone": "info"},
        "total": {"value": total, "display": _int(total), "tone": "brand"},
        "ytd": {"value": ytd_cur, "display": _int(ytd_cur), "tone": "brand"},
        "years": {"value": [y_min, y_max], "display": f"{y_min}–{y_max}", "tone": "brand"},
        "winner": {"value": round(win_share, 4), "display": _pct(win_share, 0),
                   "tone": "warn" if win_share < 0.5 else "brand"},
        "pay": {"value": int(has_pay.sum()), "display": _pct(has_pay.mean(), 0), "tone": "brand"},
    }

    rules = [
        ("open", insight_open(open_df, ref)),
        ("ytd", insight_ytd(dated, ref)),
        ("peak_year", insight_peak_year(yearly, partial_year)),
        ("types", insight_types(type_counts, total)),
        ("topic", insight_topic(topic_counts, total)),
        ("weekday", insight_weekday(dated)),
        ("winner", insight_winner(closed, ref)),
        ("top_winner", insight_top_winner(wcount)),
        ("payment", insight_payment(py)),
        ("numbering", insight_numbering(df, ref)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    open_rows = [_row(r) for _, r in open_df.head(MAX_OPEN_ROWS).iterrows()]
    closed_rows = [_row(r) for _, r in recent_closed.iterrows()]
    peak_m = int(by_month.sort_index().idxmax())
    top_year = int(yearly.sort_index().idxmax())
    files_mean = float(df["files"].mean()) if total else 0.0
    no_files = int((df["files"] == 0).sum())

    if n_open:
        open_lede = (f"{_int(n_open)} הליכים שמועד ההגשה שלהם הוא {_date(ref)} או מאוחר יותר "
                     f"(תאריך העדכון האחרון במאגר), לפי סדר מועד ההגשה.")
        if n_open > MAX_OPEN_ROWS:
            open_lede += f" מוצגים {_int(MAX_OPEN_ROWS)} הקרובים; השאר בטבלת הנתונים המלאה שבתחתית העמוד."
    else:
        open_lede = (f"אין הליכים שמועד ההגשה שלהם הוא {_date(ref)} (תאריך העדכון האחרון במאגר) "
                     f"או מאוחר יותר. להלן ההליכים שנסגרו לאחרונה.")

    labels = {
        "ref": _date(ref),
        "lede": (f"מכרזים בעיר באר שבע: רשימת המכרזים, הקולות הקוראים, הודעות ההתקשרות עם ספק יחיד "
                 f"וההליכים האחרים שמפרסמת עיריית באר שבע: {_int(total)} הליכים עם מועדי הגשה "
                 f"בשנים {y_min}-{y_max}. נכון לעדכון האחרון במאגר ({_date(ref)}) "
                 + (f"פתוחים להגשה {_int(n_open)} הליכים, והמועד הקרוב ביותר הוא {_date(next_dl)}."
                    if n_open else "אין הליכים פתוחים להגשה.")),
        "next_kpi": (f"מועד ההגשה הקרוב ביותר ({next_dl.year})" if n_open else "מועד ההגשה הקרוב ביותר"),
        "ytd_kpi": f"הליכים שנסגרו ב-{ref.year} עד {_date(ref)}",
        "open_kpi": f"הליכים פתוחים להגשה ({_date(ref)})",
        "open_lede": open_lede,
        "closed_lede": (f"{_int(len(closed_rows))} ההליכים האחרונים שמועד ההגשה שלהם חלף "
                        f"לפני {_date(ref)}, מהחדש לישן."),
        "yearly_lede": (f"מספר ההליכים לפי שנת מועד ההגשה, {y_min}-{y_max}, מפולח לפי סוג ההליך. "
                        f"השיא ב-{top_year} עם {_int(yearly[top_year])} הליכים; "
                        f"{partial_year} חלקית (עד {_date(ref)} ובתוספת הליכים שמועדם עתידי)."),
        "yearly_aria": (f"גרף עמודות מוערמות: הליכים לפי שנת מועד ההגשה וסוג ההליך, {y_min}-{y_max}. "
                        f"השיא ב-{top_year} עם {_int(yearly[top_year])} הליכים."),
        "topics_lede": (f"סיווג ההליכים לתחומים לפי מילות מפתח בשם ההליך (הליך משויך לתחום הראשון שמתאים). "
                        f"„{topic_names[0]}” מוביל עם {_int(topic_vals[0])} הליכים."
                        if topic_names else "סיווג ההליכים לתחומים לפי מילות מפתח בשם ההליך."),
        "topics_aria": (f"גרף עמודות אופקי: הליכים לפי תחום, {len(topic_names)} תחומים. "
                        f"המוביל: {topic_names[0]} עם {_int(topic_vals[0])}." if topic_names else
                        "גרף עמודות אופקי: הליכים לפי תחום."),
        "heat_lede": (f"כמה הליכים נסגרו בכל חודש בכל שנה. לאורך כל השנים, החודש העמוס ביותר הוא "
                      f"{MONTHS_HE[peak_m - 1]} עם {_int(by_month[peak_m])} מועדי הגשה."),
        "heat_aria": (f"מפת חום: מספר מועדי ההגשה לפי חודש ושנה, {y_min}-{y_max}. "
                      f"החודש העמוס ביותר: {MONTHS_HE[peak_m - 1]}."),
        "weekday_lede": "באיזה יום בשבוע נקבע מועד ההגשה האחרון.",
        "weekday_aria": ("גרף עמודות: מועדי הגשה לפי יום בשבוע. המוביל: "
                         f"{chart_weekday['names'][max(range(len(WEEKDAY_ORDER)), key=lambda i: (chart_weekday['values'][i], -i))]}."),
        "lead_lede": (f"מספר הימים מתאריך העדכון של ההליך ועד מועד ההגשה, ב-{_int(len(lead))} רשומות שעודכנו "
                      f"לפני מועד ההגשה (תאריך העדכון אינו בהכרח תאריך הפרסום). החציון: {_int(lead_median)} ימים."),
        "lead_aria": f"גרף עמודות: התפלגות הזמן מעדכון ההליך ועד מועד ההגשה. החציון {_int(lead_median)} ימים.",
        "winner_lede": (f"בכמה מההליכים שנסגרו מופיע שם זוכה, לפי שנת מועד ההגשה. "
                        f"בהליכים שנסגרו לפני יותר מחצי שנה: {_pct(win_share, 0)}."),
        "winner_aria": (f"גרף עמודות מוערמות: הליכים שנסגרו עם זוכה מפורסם ובלעדיו לפי שנה, {y_min}-{y_max}."),
        "winners_lede": (f"הזוכים שמופיעים ביותר מהליך אחד (שם הזוכה כפי שנרשם, ללא איחוד כתיב). "
                         f"במאגר {_int(len(wcount))} שמות זוכים שונים."),
        "winners_aria": (f"גרף עמודות אופקי: הזוכים התכופים ביותר. המוביל: {chart_winners['names'][0]} "
                         f"עם {_int(chart_winners['values'][0])} הליכים." if chart_winners["names"] else
                         "גרף עמודות אופקי: הזוכים התכופים ביותר."),
        "pay_lede": (f"ל-{_int(int(has_pay.sum()))} הליכים ({_pct(has_pay.mean(), 0)}) צורף קישור לתשלום מקוון; "
                     f"הגרף מראה באיזו מערכת תשלום, לפי שנת מועד ההגשה."),
        "pay_aria": f"גרף עמודות מוערמות: הליכים לפי מערכת התשלום המקוון ושנה, {y_min}-{y_max}.",
        "files_note": (f"לכל הליך מצורפים בממוצע {files_mean:.1f} קבצים; ל-{_int(no_files)} רשומות אין קבצים מצורפים."),
    }

    return {
        "agent_data": {
            "summary_he": (f"מכרזי עיריית באר שבע: {_int(n_open)} מכרזים פתוחים להגשה (נכון ל-{_date(ref)}), "
                           f"מועדי הגשה, זוכים ותשלום מקוון. {_int(total)} הליכים מאז {y_min}."),
            "dataset_kind": "registry",
            "suggested_tags": ["מכרזים", "באר שבע", "רכש ציבורי", "רשויות מקומיות", "שקיפות"],
            "related_ids": ["54b65747-904e-42e1-9316-0575ebbc1216",
                            "fffada0a-b021-4629-9244-bc5e301f23d5"],
            "temporal_coverage": f"{y_min}/{y_max}",
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": {
            "yearly": chart_yearly,
            "topics": chart_topics,
            "heat": chart_heat,
            "weekday": chart_weekday,
            "lead": chart_lead,
            "winner": chart_winner,
            "winners": chart_winners,
            "pay": chart_pay,
        },
        "tables": {"open": open_rows, "closed": closed_rows},
        "flags": {"has_open": n_open > 0, "has_winners": bool(chart_winners["names"])},
        "insights": insights,
        "labels": labels,
    }
