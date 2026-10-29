"""מאגר סימני המסחר — the Israel Patent Office trademark register (רשם סימני המסחר).

One row per trademark application (~364k, 1920 onward): mark number, whether
it is figurative (דמות), status (מצב), filing route (national / international
designation under the Madrid Protocol / national basis for an international
filing), application / registration / expiry dates, Nice classes
("9; 42"), Vienna figurative codes ("26.4; 27.5"), priority claim, agent
(law firm), owner, licensee, customs-enforcement representative, foreign
registration basis and free-text goods lists / descriptions.

The input is large (≈370MB CSV), so everything here aggregates; no row ever
reaches the page. "Now" is the latest application date in the data — never
the wall clock. When that date falls before 20 December the latest year is
partial: it is labelled as such, excluded from full-year trend rules, and
compared with the same calendar window of the previous year instead.

People: owners and agents are named (applicants on a public filing and
licensed professionals / firms). Customs-representative e-mails and phones
are never read; their names only feed a count.
"""
import re
import unicodedata

import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"

NICE = {
    1: "חומרים כימיים", 2: "צבעים", 3: "תכשירי ניקוי וקוסמטיקה", 4: "שמנים תעשייתיים",
    5: "תכשירי רוקחות", 6: "מתכות פשוטות", 7: "מכונות", 8: "כלי עבודה ידניים",
    9: "מכשירי מדע, חשמל ומחשבים", 10: "מכשירים רפואיים", 11: "התקני תאורה וחימום",
    12: "כלי רכב", 13: "כלי נשק", 14: "מתכות יקרות ותכשיטים", 15: "כלי נגינה",
    16: "נייר וצורכי נייר", 17: "חומרי אטימה ובידוד", 18: "עור וחיקויי עור",
    19: "חומרי בנייה לא מתכתיים", 20: "רהיטים", 21: "כלי מטבח וזכוכית",
    22: "חבלים וחומרי טקסטיל גולמיים", 23: "מטווה וחוטים", 24: "אריגים",
    25: "דברי הלבשה", 26: "תחרה, רקמה וכפתורים", 27: "שטיחים ומרבדים",
    28: "משחקים וצורכי התעמלות", 29: "בשר, דגים, חלב ושימורים", 30: "דברי מאפה ומזון יבש",
    31: "פירות וירקות טריים", 32: "משקאות לא כוהליים", 33: "משקאות כוהליים",
    34: "צורכי מעשנים", 35: "פרסומת ומסחר", 36: "ביטוח ומימון", 37: "בינוי ותיקון",
    38: "תקשורת", 39: "הובלה ואחסנה", 40: "טיפול בחומרים", 41: "חינוך ובידור",
    42: "שירותים מדעיים וטכנולוגיים", 43: "הספקת מזון ומשקה", 44: "שירותים רפואיים",
    45: "שירותים אישיים ומשפטיים",
}
VIENNA = {
    1: "גרמי שמיים ותופעות טבע", 2: "בני אדם", 3: "בעלי חיים", 4: "יצורים ודמויות",
    5: "צמחים", 6: "נופים", 7: "מבנים", 8: "מזון", 9: "טקסטיל וביגוד",
    10: "טבק וטיפוח", 11: "כלי בית", 12: "רהיטים", 13: "תאורה וחימום",
    14: "כלי עבודה", 15: "מכונות", 16: "תקשורת וצילום", 17: "שעונים ותכשיטים",
    18: "כלי תחבורה", 19: "מכלים ואריזות", 20: "כלי כתיבה ומסמכים",
    21: "משחקים וספורט", 22: "כלי נגינה", 23: "כלי נשק", 24: "סמלים ודגלים",
    25: "עיטורים ורקעים", 26: "צורות גאומטריות", 27: "צורות כתב וספרות",
    28: "כיתובים", 29: "צבעים",
}

ROUTE_NAT, ROUTE_INT, ROUTE_BASE = "לאומי", "בינלאומי", "בסיס לבינלאומי"
ROUTE_LABEL = {ROUTE_NAT: "בקשה לאומית", ROUTE_INT: "ייעוד בינלאומי (פרוטוקול מדריד)",
               ROUTE_BASE: "בסיס לבקשה בינלאומית"}
ROUTE_ORDER = [ROUTE_NAT, ROUTE_INT, ROUTE_BASE]

G_REG, G_CLOSED, G_UNPAID, G_ACCEPTED, G_EXAM, G_OTHER = (
    "רשום", "סגור", "לא שולמה אגרה", "קובל (בתקופת התנגדות)", "בבחינה", "אחר")
STATUS_GROUP = {
    "רשום": G_REG, "סגור": G_CLOSED, "אי תשלום": G_UNPAID, "קובל": G_ACCEPTED,
    "בחינה ראשונה": G_EXAM, "בחינה שנייה": G_EXAM, "ממתין לבחינה": G_EXAM,
    "ממתין לקבלת החלטה בתיק אחר": G_EXAM, "במיון": G_EXAM,
}
GROUP_ORDER = [G_REG, G_CLOSED, G_UNPAID, G_ACCEPTED, G_EXAM, G_OTHER]
GROUP_COLOR = {G_REG: "#198754", G_CLOSED: "#6c757d", G_UNPAID: "#dc3545",
               G_ACCEPTED: "#0dcaf0", G_EXAM: "#0068f5", G_OTHER: "#c3cfe7"}
PENDING = {G_ACCEPTED, G_EXAM}

PARTIAL_CUTOFF = (12, 20)       # latest date before 20 Dec → latest year partial
RECENT_YEARS = 30               # window of the per-year cohort charts
AGENT_YEARS = 10                # agents ranked on the last N application years
TOP_CLASSES = 15
HEAT_CLASSES = 12
HEAT_PERIOD = 5                 # years per heatmap column
HEAT_PERIODS = 6
TOP_OWNERS = 15
TOP_AGENTS = 12
TOP_VIENNA = 12
LAG_MIN_N = 50                  # registration years with fewer marks are not plotted
LAG_MAX_DAYS = 20 * 366         # longer gaps are data artefacts, excluded (disclosed)
STABLE = 0.03                   # relative change below this reads as "stable"
SHARE_PP = 3.0                  # share moves below this many points read as "stable"
AGENT_CONC_MIN = 0.30           # top-5 agents' share must reach this to be called concentrated
AGENT_LEAD = 1.5                # leader must have this multiple of the runner-up to be named the leader
OWNER_MIN = 200                 # a leading owner must hold at least this many marks
LAG_CHANGE = 0.10               # median-time change below this reads as "stable"

_BIDI = re.compile("[‎‏‪-‮⁦-⁩]")
_WS = re.compile(r"\s+")


def _int(v):
    return f"{int(round(v)):,}"


def _pct(v, d=1):
    return f"{v * 100:.{d}f}%"


def _kpi_num(v):
    s = f"{v:,}" if isinstance(v, int) else v
    return s.replace("-", MINUS)


def _iso(s):
    return f"{LRI}{s}{PDI}"


def _clean_name(s):
    s = _BIDI.sub("", s or "").replace("~", "״")
    s = s.replace('בעמ"', "בע״מ").replace('בע"מ', "בע״מ")
    s = _WS.sub(" ", s).strip().strip('",').strip()
    return s


def _owner_key(s):
    """Merge spelling variants of one owner: curly apostrophe, case, accents."""
    s = unicodedata.normalize("NFKD", s.replace("\u2019", "'").casefold())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _date(col):
    return pd.to_datetime(col.str.strip(), format="%d/%m/%Y", errors="coerce")


def _ranked(series):
    """value_counts with a total, order-independent tie-break (count desc, key asc)."""
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _display_names(keys, he, en):
    """Most frequent cleaned Hebrew name per key when it names at least half of the
    key's rows (a stray Hebrew value on a few rows is often a placeholder), else the
    most frequent English one."""
    frame = pd.DataFrame({"k": keys, "he": he, "en": en})
    frame = frame[frame["k"] != ""]
    size = frame.groupby("k").size()
    out = {}
    h = frame[frame["he"] != ""].groupby(["k", "he"]).size().reset_index(name="n")
    h = h.sort_values(["k", "n", "he"], ascending=[True, False, True], kind="stable")
    for k, name, n in h.drop_duplicates("k")[["k", "he", "n"]].itertuples(index=False):
        if n * 2 >= size[k]:
            out[k] = name
    e = frame[frame["en"] != ""].groupby(["k", "en"]).size().reset_index(name="n")
    e = e.sort_values(["k", "n", "en"], ascending=[True, False, True], kind="stable")
    for k, name in e.drop_duplicates("k")[["k", "en"]].itertuples(index=False):
        out.setdefault(k, name)
    return out


# ── insight rules ────────────────────────────────────────────────────────


def insight_ytd(t):
    """Latest partial year vs the same calendar window a year earlier (national filings,
    which are recorded at filing; international designations arrive with a lag)."""
    if not t["partial"] or t["ytd_prev"] < 100:
        return None
    cur, prev = t["ytd_cur"], t["ytd_prev"]
    ch = (cur - prev) / prev
    win = t["ytd_window"]
    if abs(ch) < STABLE:
        return (f"בקשות לאומיות ב-{t['last_year']} ({win}): {_int(cur)} — כמעט ללא שינוי "
                f"לעומת אותה תקופה ב-{t['last_year'] - 1} ({_int(prev)}).")
    word = "עלייה" if ch > 0 else "ירידה"
    return (f"בקשות לאומיות ב-{t['last_year']} ({win}): {_int(cur)} — {word} של {_pct(abs(ch))} "
            f"לעומת אותה תקופה ב-{t['last_year'] - 1} ({_int(prev)}). ייעודים בינלאומיים "
            f"נקלטים במאגר באיחור, ולכן אינם נכללים בהשוואה.")


def insight_peak(yearly, full_year):
    s = yearly[yearly.index <= full_year]
    if len(s) < 5:
        return None
    peak_y = int(s.sort_index().idxmax())
    peak = int(s.max())
    last = int(s.loc[full_year])
    if peak_y == full_year:
        return f"{full_year} הייתה שנת שיא בהגשת בקשות לסימני מסחר, עם {_int(last)} בקשות."
    gap = (peak - last) / peak
    return (f"שנת השיא בהגשת בקשות הייתה {peak_y} עם {_int(peak)} בקשות; ב-{full_year}, "
            f"השנה המלאה האחרונה, הוגשו {_int(last)} — {_pct(gap)} מתחת לשיא.")


def insight_intl(route_share, intl_counts, full_year):
    s = route_share
    base = full_year - 10
    if full_year not in s.index or base not in s.index:
        return None
    a, b = s.loc[base] * 100, s.loc[full_year] * 100
    if a < 0.5:
        started = intl_counts[intl_counts > 0]
        if started.empty or b < 0.5:
            return None
        y0 = int(started.index.min())
        return (f"ייעודים בינלאומיים לפי פרוטוקול מדריד מופיעים במאגר מ-{y0}; "
                f"ב-{full_year} הם כבר {b:.1f}% מכלל הבקשות.")
    diff = b - a
    if abs(diff) < SHARE_PP:
        return (f"חלקם של הייעודים הבינלאומיים (פרוטוקול מדריד) יציב: {b:.1f}% מהבקשות "
                f"ב-{full_year}, לעומת {a:.1f}% ב-{base}.")
    word = "עלה" if diff > 0 else "ירד"
    return (f"חלקם של הייעודים הבינלאומיים (פרוטוקול מדריד) {word} מ-{a:.1f}% מהבקשות "
            f"ב-{base} ל-{b:.1f}% ב-{full_year}.")


def insight_class(cls_counts, total, growth):
    if cls_counts.empty or total == 0:
        return None
    c, n = int(cls_counts.index[0]), int(cls_counts.iloc[0])
    text = (f"הסוג הנפוץ ביותר בסיווג ניצה הוא סוג {c} ({NICE.get(c, 'סוג ' + str(c))}), "
            f"המופיע ב-{_pct(n / total)} מהבקשות.")
    if growth:
        g_c, a, b, p0, p1 = growth
        text += (f" הצמיחה החדה ביותר בין הסוגים הגדולים: סוג {g_c} ({NICE.get(g_c, '')}), "
                 f"מ-{a:.1f}% מהבקשות ב-{p0} ל-{b:.1f}% ב-{p1}.")
    return text


def insight_agents(agent_counts, total_window, y0, y1, names):
    """National filings only: international designations arrive through WIPO, usually
    without an Israeli agent."""
    named = agent_counts.drop(labels=["__none__"], errors="ignore")
    if total_window < 100 or len(named) < 5:
        return None
    lead_k, lead = named.index[0], int(named.iloc[0])
    second = int(named.iloc[1])
    top5 = int(named.iloc[:5].sum()) / total_window
    none = int(agent_counts.get("__none__", 0)) / total_window
    if second > 0 and lead >= AGENT_LEAD * second:
        head = (f"{names.get(lead_k, lead_k)} הוא מיופה הכוח הבולט: {_pct(lead / total_window)} "
                f"מהבקשות הלאומיות שהוגשו ב-{y0}-{y1}, פי {lead / second:.1f} ממיופה הכוח השני.")
    else:
        head = f"אין מיופה כוח דומיננטי בבקשות הלאומיות שהוגשו ב-{y0}-{y1}."
    conc = "מרוכז" if top5 >= AGENT_CONC_MIN else "מבוזר יחסית"
    return (f"{head} שוק הייצוג {conc}: חמשת המובילים טיפלו ב-{_pct(top5)} מהבקשות, "
            f"ו-{_pct(none)} הוגשו ללא מיופה כוח.")


def insight_owner(owner_counts, names):
    if owner_counts.empty:
        return None
    k, n = owner_counts.index[0], int(owner_counts.iloc[0])
    if n < OWNER_MIN:
        return None
    second = names[owner_counts.index[1]] if len(owner_counts) > 1 else None
    tail = (f", לפני {_iso(second)} ({_int(owner_counts.iloc[1])})" if second else "")
    return f"בעל הסימנים הגדול במאגר הוא {_iso(names[k])} עם {_int(n)} בקשות{tail}."


def insight_lag(lag_stats):
    if len(lag_stats) < 11:
        return None
    y1 = int(lag_stats.index.max())
    y0 = y1 - 10
    if y0 not in lag_stats.index:
        return None
    a, b = lag_stats.loc[y0, "p50"], lag_stats.loc[y1, "p50"]
    if a <= 0:
        return None
    ch = (b - a) / a
    if abs(ch) < LAG_CHANGE:
        return (f"משך החציוני מהגשה ועד רישום יציב: {b:.1f} חודשים בסימנים שנרשמו ב-{y1}, "
                f"לעומת {a:.1f} ב-{y0}.")
    word = "התארך" if ch > 0 else "התקצר"
    return (f"משך הזמן החציוני מהגשה ועד רישום {word} מ-{a:.1f} חודשים בסימנים שנרשמו "
            f"ב-{y0} ל-{b:.1f} חודשים ב-{y1}.")


def insight_survival(fate, full_year):
    y = full_year - 20
    if y not in fate.index:
        return None
    row = fate.loc[y]
    tot = row.sum()
    if tot < 100:
        return None
    reg = row.get(G_REG, 0) / tot
    closed = row.get(G_CLOSED, 0) / tot
    return (f"מבין {_int(tot)} הבקשות שהוגשו ב-{y}, {_pct(reg)} עדיין רשומות ובתוקף היום, "
            f"ו-{_pct(closed)} נסגרו — נדחו, נזנחו או לא חודשו.")


def insight_expiry(exp_counts, as_of_year, registered):
    if exp_counts.empty or registered == 0:
        return None
    nxt = exp_counts[exp_counts.index <= as_of_year + 1]
    n = int(nxt.sum())
    if n == 0:
        return None
    return (f"{_int(n)} סימנים רשומים ({_pct(n / registered)} מהרשומים) יגיע מועד חידושם "
            f"עד סוף {as_of_year + 1}.")


def insight_special(kind_counts):
    cert = int(kind_counts.get("מאשר", 0))
    coll = int(kind_counts.get("קיבוצי", 0))
    if cert + coll < 20:
        return None
    return (f"לצד סימני המסחר והשירות הרגילים כולל המאגר {_int(cert)} סימני אישור ו-{_int(coll)} "
            f"סימנים קיבוציים — סימנים המעידים על תקן או על חברות בארגון ולא על יצרן מסוים.")


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    df = frames["marks"]
    n_all = len(df)
    app = _date(df["תאריך בקשה"])
    reg = _date(df["תאריך רישום"])
    exp = _date(df["תאריך תום תוקף"])
    status = df["מצב"].str.strip()
    group = status.map(STATUS_GROUP).fillna(G_OTHER)
    route = df["לאומי/בינלאומי"].str.strip()
    yes = lambda c: df[c].str.strip() == "כן"  # noqa: E731

    ok = app.notna()
    as_of = app.max()
    as_of_year = int(as_of.year)
    partial = (as_of.month, as_of.day) < PARTIAL_CUTOFF
    full_year = as_of_year - 1 if partial else as_of_year
    first_year = int(app.min().year)
    year = app.dt.year

    # ── yearly filings by route ──
    years = list(range(first_year, as_of_year + 1))
    ry = pd.crosstab(year[ok], route[ok])
    ry = ry.reindex(years, fill_value=0)
    routes = [r for r in ROUTE_ORDER if r in ry.columns] + sorted(
        c for c in ry.columns if c not in ROUTE_ORDER)
    yearly = ry.sum(axis=1)
    route_share = (ry.get(ROUTE_INT, 0) / yearly.where(yearly > 0)).fillna(0)

    # YTD comparison (national filings), same calendar window
    nat = ok & (route == ROUTE_NAT)
    md = app.dt.month * 100 + app.dt.day
    cut = as_of.month * 100 + as_of.day
    ytd_cur = int((nat & (year == as_of_year) & (md <= cut)).sum())
    ytd_prev = int((nat & (year == as_of_year - 1) & (md <= cut)).sum())
    ytd_window = f"עד {as_of.day}.{as_of.month}"

    # ── status ──
    g_counts = group.value_counts()
    status_rows = [{"name": g, "value": int(g_counts.get(g, 0)), "color": GROUP_COLOR[g]}
                   for g in GROUP_ORDER if int(g_counts.get(g, 0)) > 0]
    registered = int(g_counts.get(G_REG, 0))
    pending = int(sum(g_counts.get(g, 0) for g in PENDING))
    accepted = int(g_counts.get(G_ACCEPTED, 0))

    # ── fate by filing year (last RECENT_YEARS years) ──
    fy0 = as_of_year - RECENT_YEARS + 1
    win = ok & (year >= fy0)
    fate = pd.crosstab(year[win], group[win]).reindex(range(fy0, as_of_year + 1), fill_value=0)
    fate_tot = fate.sum(axis=1)
    fate_chart = {
        "x": [str(y) for y in fate.index],
        "series": [{"name": g, "color": GROUP_COLOR[g],
                    "data": [round(float(v) / t * 100, 1) if t else 0
                             for v, t in zip(fate.get(g, pd.Series(0, index=fate.index)), fate_tot)]}
                   for g in GROUP_ORDER if g in fate.columns and int(fate[g].sum()) > 0],
        "totals": [int(v) for v in fate_tot],
    }

    # ── Nice classes ──
    cls = (df["סוגי ניצה לבקשה"].str.split(r"[;,\s]+", regex=True)
           .explode())
    cls = pd.to_numeric(cls, errors="coerce")
    cls = cls[cls.between(1, 45)].astype(int)
    cls_pairs = pd.DataFrame({"row": cls.index, "c": cls.values}).drop_duplicates()
    n_with_class = int(cls_pairs["row"].nunique())
    cls_counts = _ranked(cls_pairs["c"])
    multi = int((cls_pairs.groupby("row").size() > 1).sum())
    top_cls = cls_counts.iloc[:TOP_CLASSES]
    classes_chart = {
        "names": [f"{c} · {NICE.get(int(c), 'סוג ' + str(c))}" for c in top_cls.index],
        "values": [int(v) for v in top_cls],
        "shares": [round(int(v) / n_with_class * 100, 1) for v in top_cls],
    }

    # heatmap: class share of filings per 5-year period ending at full_year
    periods = []
    for i in range(HEAT_PERIODS - 1, -1, -1):
        p1 = full_year - i * HEAT_PERIOD
        periods.append((p1 - HEAT_PERIOD + 1, p1))
    cls_pairs["year"] = year.reindex(cls_pairs["row"]).values
    py = year[ok]
    heat_classes = [int(c) for c in cls_counts.iloc[:HEAT_CLASSES].index]
    cells, heat_tbl = [], []
    shares_by_period = {}
    for xi, (a, b) in enumerate(periods):
        n_p = int(((py >= a) & (py <= b)).sum())
        sub = cls_pairs[(cls_pairs["year"] >= a) & (cls_pairs["year"] <= b)]
        cc = sub["c"].value_counts()
        shares_by_period[(a, b)] = (cc, n_p)
        for yi, c in enumerate(heat_classes):
            cnt = int(cc.get(c, 0))
            sh = round(cnt / n_p * 100, 1) if n_p else 0.0
            cells.append([xi, yi, sh, cnt])
    heat_chart = {
        "x": [f"{a}-{b}" for a, b in periods],
        "y": [f"{c} · {NICE.get(c, '')}" for c in heat_classes],
        "cells": cells,
        "max": max([c[2] for c in cells] or [1]),
    }
    growth = None
    if len(periods) >= 2:
        (a0, b0), (a1, b1) = periods[-2], periods[-1]
        cc0, n0 = shares_by_period[(a0, b0)]
        cc1, n1 = shares_by_period[(a1, b1)]
        if n0 >= 1000 and n1 >= 1000:
            best = None
            for c in heat_classes:
                s0, s1 = cc0.get(c, 0) / n0 * 100, cc1.get(c, 0) / n1 * 100
                d = s1 - s0
                if d >= 1.0 and (best is None or d > best[0] or (d == best[0] and c < best[1])):
                    best = (d, c, s0, s1)
            if best:
                growth = (best[1], best[2], best[3], f"{a0}-{b0}", f"{a1}-{b1}")

    # ── owners ──
    own_en = df["שם בעל הסימן באנגלית"].map(_clean_name)
    own_he = df["שם בעל הסימן בעברית"].map(_clean_name)
    own_key = own_en.where(own_en != "", own_he).map(_owner_key)
    owner_counts = _ranked(own_key[own_key != ""])
    owner_names = _display_names(own_key, own_he, own_en)
    top_own = owner_counts.iloc[:TOP_OWNERS]
    own_reg = own_key[group == G_REG].value_counts()
    owners_chart = {
        "names": [owner_names[k] for k in top_own.index],
        "total": [int(v) for v in top_own],
        "registered": [int(own_reg.get(k, 0)) for k in top_own.index],
    }
    n_owners = int(owner_counts.size)

    # ── agents (last AGENT_YEARS application years) ──
    ag_he = df["שם מיופה כח"].map(_clean_name)
    ag_en = df["שם מיופה כח אנגלית"].map(_clean_name)
    ag_key = ag_he.where(ag_he != "", ag_en)
    ay0 = as_of_year - AGENT_YEARS + 1
    awin = ok & (year >= ay0) & route.isin([ROUTE_NAT, ROUTE_BASE])
    ak = ag_key[awin].where(ag_key[awin] != "", "__none__")
    agent_counts = _ranked(ak)
    agent_names = _display_names(ag_key, ag_he, ag_en)
    named = agent_counts.drop(labels=["__none__"], errors="ignore")
    top_ag = named.iloc[:TOP_AGENTS]
    total_aw = int(awin.sum())
    rest = int(named.iloc[TOP_AGENTS:].sum())
    none_n = int(agent_counts.get("__none__", 0))
    agents_chart = {
        "names": [agent_names.get(k, k) for k in top_ag.index] + ["מיופי כוח אחרים", "ללא מיופה כוח"],
        "values": [int(v) for v in top_ag] + [rest, none_n],
        "shares": [round(int(v) / total_aw * 100, 1) if total_aw else 0
                   for v in list(top_ag) + [rest, none_n]],
    }
    n_agents_window = int(named.size)

    # ── time to registration ──
    lag = (reg - app).dt.days
    lag_ok = lag.notna() & (lag >= 0) & (lag <= LAG_MAX_DAYS)
    lag_excl = int((lag.notna() & ~lag_ok).sum())
    ly0 = as_of_year - RECENT_YEARS + 1
    lsel = lag_ok & (reg.dt.year >= ly0)
    lg = (lag[lsel] / 30.4375).groupby(reg.dt.year[lsel])
    lag_stats = pd.DataFrame({"n": lg.size(), "p25": lg.quantile(0.25),
                              "p50": lg.quantile(0.5), "p75": lg.quantile(0.75)})
    lag_stats = lag_stats[lag_stats["n"] >= LAG_MIN_N].sort_index()
    lag_stats.index = lag_stats.index.astype(int)
    lag_chart = {
        "x": [str(y) for y in lag_stats.index],
        "p25": [round(float(v), 1) for v in lag_stats["p25"]],
        "p50": [round(float(v), 1) for v in lag_stats["p50"]],
        "p75": [round(float(v), 1) for v in lag_stats["p75"]],
        "n": [int(v) for v in lag_stats["n"]],
    }
    lag_last_year = int(lag_stats.index.max()) if len(lag_stats) else None
    lag_last = float(lag_stats["p50"].iloc[-1]) if len(lag_stats) else None
    lag_tone = "brand"
    if len(lag_stats) > 5 and lag_last is not None:
        ref = float(lag_stats["p50"].iloc[-6:-1].median())
        if ref > 0 and lag_last > ref * (1 + LAG_CHANGE):
            lag_tone = "warn"
        elif ref > 0 and lag_last < ref * (1 - LAG_CHANGE):
            lag_tone = "ok"

    # ── expiry wave of registered marks ──
    esel = (group == G_REG) & exp.notna() & (exp >= as_of)
    exp_counts = exp.dt.year[esel].astype(int).value_counts().sort_index()
    expiry_chart = {"x": [str(y) for y in exp_counts.index],
                    "y": [int(v) for v in exp_counts]}
    reg_no_future_exp = registered - int(esel.sum())

    # ── features by filing year ──
    fig = yes("דמות")
    prio = yes("דין קדימה")
    foreign = yes("רישום חיצוני")
    hebdesc = df["תיאור סימן עברית"].str.strip() != ""
    fsel = ok & (year >= fy0)
    fyear = year[fsel]
    feat = pd.DataFrame({"fig": fig[fsel], "prio": prio[fsel], "heb": hebdesc[fsel],
                         "foreign": foreign[fsel]}).groupby(fyear).mean() * 100
    feat = feat.reindex(range(fy0, as_of_year + 1)).fillna(0)
    features_chart = {"x": [str(y) for y in feat.index],
                      "fig": [round(float(v), 1) for v in feat["fig"]],
                      "prio": [round(float(v), 1) for v in feat["prio"]],
                      "heb": [round(float(v), 1) for v in feat["heb"]],
                      "foreign": [round(float(v), 1) for v in feat["foreign"]]}

    # ── Vienna top-level categories (figurative marks) ──
    vi = df["סוגי וינה לבקשה"].str.split(";").explode().str.strip()
    vi = pd.to_numeric(vi.str.split(".").str[0], errors="coerce")
    vi = vi[vi.between(1, 29)].astype(int)
    vi_pairs = pd.DataFrame({"row": vi.index, "c": vi.values}).drop_duplicates()
    n_vienna = int(vi_pairs["row"].nunique())
    vi_counts = _ranked(vi_pairs["c"]).iloc[:TOP_VIENNA]
    vienna_chart = {
        "names": [VIENNA.get(int(c), f"קטגוריה {c}") for c in vi_counts.index],
        "values": [int(v) for v in vi_counts],
        "shares": [round(int(v) / n_vienna * 100, 1) if n_vienna else 0 for v in vi_counts],
    }

    # ── other counts ──
    kind_counts = df["סוג רישום"].str.strip().value_counts()
    lic_key = df["שם בעל הרשות באנגלית"].map(_clean_name)
    lic_key = lic_key.where(lic_key != "", df["שם בעל הרשות בעברית"].map(_clean_name))
    n_licensed = int((lic_key != "").sum())
    customs = (df["שם מייצג לעניין אכיפת מכס"].str.strip() != "") & (group == G_REG)
    n_customs = int(customs.sum())
    n_fig = int(fig.sum())
    n_prio = int(prio.sum())
    n_foreign = int(foreign.sum())

    full_n = int(yearly.loc[full_year])
    prev_n = int(yearly.loc[full_year - 1]) if (full_year - 1) in yearly.index else 0
    yoy = (full_n - prev_n) / prev_n if prev_n else 0.0
    yoy_tone = "brand" if abs(yoy) < STABLE else ("ok" if yoy > 0 else "danger")
    intl_last = float(route_share.loc[full_year]) if full_year in route_share.index else 0.0

    t = {"partial": partial, "ytd_cur": ytd_cur, "ytd_prev": ytd_prev,
         "ytd_window": ytd_window, "last_year": as_of_year}
    rules = [
        ("peak", insight_peak(yearly, full_year)),
        ("ytd", insight_ytd(t)),
        ("intl", insight_intl(route_share, ry.get(ROUTE_INT, yearly * 0), full_year)),
        ("survival", insight_survival(fate, full_year) if full_year - 20 >= fy0 else None),
        ("classes", insight_class(cls_counts, n_with_class, growth)),
        ("owner", insight_owner(owner_counts, owner_names)),
        ("agents", insight_agents(agent_counts, total_aw, ay0, as_of_year, agent_names)),
        ("lag", insight_lag(lag_stats[lag_stats.index <= full_year])),
        ("expiry", insight_expiry(exp_counts, as_of_year, registered)),
        ("special", insight_special(kind_counts)),
    ]
    insights = [{"id": i, "text_he": s} for i, s in rules if s]

    as_of_s = f"{as_of.day}.{as_of.month}.{as_of.year}"
    partial_note = (f" הנתונים לשנת {as_of_year} חלקיים (עד {as_of_s})." if partial else "")
    peak_y = int(yearly[yearly.index <= full_year].idxmax())

    summary = (f"חיפוש במאגר סימני המסחר לפי שם הסימן, מספר סימן או בעלים: {_int(n_all)} "
               f"בקשות מאז {first_year}, מהן {_int(registered)} רשומות ובתוקף.")
    lede = (f"המאגר של רשם סימני המסחר ברשות הפטנטים כולל {_int(n_all)} בקשות לרישום סימני מסחר "
               f"ושירות שהוגשו בישראל בשנים {first_year}-{as_of_year}, מהן {_int(registered)} "
               f"רשומות ובתוקף ו-{_int(pending)} בבחינה או בתקופת התנגדות. "
               f"ב-{full_year} הוגשו {_int(full_n)} בקשות, {_pct(intl_last)} מהן ייעודים "
               f"בינלאומיים לפי פרוטוקול מדריד.")

    top_owner_name = owner_names[owner_counts.index[0]] if len(owner_counts) else ""
    top_agent_name = agent_names.get(top_ag.index[0], "") if len(top_ag) else ""

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["סימני מסחר", "קניין רוחני", "רשות הפטנטים", "מותגים",
                               "פרוטוקול מדריד", "סיווג ניצה"],
            "related_ids": [],
            "temporal_coverage": f"{first_year}/{as_of_year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": n_all, "display": _kpi_num(n_all), "tone": "brand"},
            "registered": {"value": registered, "display": _kpi_num(registered), "tone": "ok"},
            "pending": {"value": pending, "display": _kpi_num(pending), "tone": "info"},
            "last_year": {"value": full_n, "display": _kpi_num(full_n), "tone": yoy_tone},
            "intl": {"value": round(intl_last * 100, 1), "display": f"{intl_last * 100:.1f}%",
                     "tone": "brand"},
            "lag": {"value": round(lag_last, 1) if lag_last is not None else None,
                    "display": f"{lag_last:.1f}" if lag_last is not None else "—",
                    "tone": lag_tone},
            "owners": {"value": n_owners, "display": _kpi_num(n_owners), "tone": "brand"},
            "customs": {"value": n_customs, "display": _kpi_num(n_customs), "tone": "brand"},
        },
        "charts": {
            "yearly": {"x": [str(y) for y in years],
                       "series": [{"name": ROUTE_LABEL.get(r, r),
                                   "data": [int(v) for v in ry[r]]} for r in routes],
                       "partial_year": str(as_of_year) if partial else None},
            "status": status_rows,
            "fate": fate_chart,
            "classes": classes_chart,
            "heat": heat_chart,
            "owners": owners_chart,
            "agents": agents_chart,
            "lag": lag_chart,
            "expiry": expiry_chart,
            "features": features_chart,
            "vienna": vienna_chart,
        },
        "insights": insights,
        "labels": {
            "lede": lede,
            "as_of": as_of_s,
            "last_year_kpi": (f"בקשות שהוגשו ב-{full_year} "
                              f"({'+' if yoy >= 0 else MINUS}{abs(yoy) * 100:.1f}% לעומת {full_year - 1})"),
            "intl_kpi": f"ייעודים בינלאומיים מתוך בקשות {full_year}",
            "lag_kpi": (f"חודשים מהגשה לרישום (חציון, נרשמו ב-{lag_last_year})"
                        if lag_last_year else "חודשים מהגשה לרישום (חציון)"),
            "yearly_note": (f"מספר הבקשות לפי שנת ההגשה ולפי מסלול ההגשה. שנת השיא: {peak_y} "
                            f"({_int(yearly.loc[peak_y])} בקשות).{partial_note}"),
            "yearly_aria": (f"תרשים עמודות מוערמות: בקשות לסימני מסחר לפי שנת הגשה ומסלול, "
                            f"{first_year}-{as_of_year}. שיא ב-{peak_y} עם {_int(yearly.loc[peak_y])} בקשות."),
            "status_note": (f"{_int(registered)} סימנים ({_pct(registered / n_all)}) רשומים ובתוקף; "
                            f"{_int(int(g_counts.get(G_CLOSED, 0)))} תיקים סגורים — סימנים שפקעו, "
                            f"נדחו או נזנחו. {_int(accepted)} בקשות קובלו ומפורסמות להתנגדות."),
            "status_aria": (f"תרשים טבעת: מצב {_int(n_all)} התיקים במאגר. "
                            f"{_pct(registered / n_all)} רשומים ובתוקף."),
            "fate_note": (f"המצב הנוכחי של הבקשות לפי שנת ההגשה, באחוזים מבקשות אותה שנה "
                          f"({fy0}-{as_of_year}). בקשות מהשנים האחרונות עדיין בבחינה; "
                          f"בקשות ישנות שלא חודשו נסגרו."),
            "fate_aria": (f"תרשים עמודות מוערמות באחוזים: המצב הנוכחי של הבקשות לפי שנת הגשה, "
                          f"{fy0}-{as_of_year}."),
            "classes_note": (f"מספר הבקשות המייעדות כל סוג בסיווג ניצה הבינלאומי. "
                             f"{_int(multi)} בקשות ({_pct(multi / n_with_class)}) מכסות יותר "
                             f"מסוג אחד ונספרות בכל אחד מהם. מוצגים {len(top_cls)} הסוגים "
                             f"הנפוצים מתוך {cls_counts.size}."),
            "classes_aria": (f"תרשים עמודות אופקי: {len(top_cls)} סוגי ניצה הנפוצים בבקשות. "
                             f"המוביל: {classes_chart['names'][0] if top_cls.size else ''}."),
            "heat_note": (f"אחוז הבקשות בכל תקופה בת {HEAT_PERIOD} שנים שמייעדות כל אחד מ-"
                          f"{len(heat_classes)} הסוגים הנפוצים — כך נראה השינוי בתמהיל התחומים."),
            "heat_aria": (f"מפת חום: אחוז הבקשות לפי סוג ניצה ותקופה, {periods[0][0]}-{periods[-1][1]}."),
            "owners_note": (f"{len(top_own)} בעלי הסימנים עם מספר הבקשות הגדול ביותר בכל השנים, "
                            f"ומתוכן כמה רשומות כיום. במאגר {_int(n_owners)} בעלי סימנים שונים "
                            f"(לפי השם, ללא הבחנה בין אותיות גדולות לקטנות)."),
            "owners_aria": (f"תרשים עמודות אופקי: {len(top_own)} בעלי סימני המסחר הגדולים. "
                            f"המוביל: {top_owner_name}."),
            "agents_note": (f"חלקם של מיופי הכוח (משרדי עורכי דין ועורכי פטנטים) בבקשות הלאומיות "
                            f"שהוגשו ב-{ay0}-{as_of_year}, כולל בקשות בסיס לבינלאומי: "
                            f"{_int(total_aw)} בקשות, "
                            f"{_int(n_agents_window)} מיופי כוח שונים. ייעודים בינלאומיים מגיעים "
                            f"דרך הארגון העולמי לקניין רוחני, לרוב ללא מיופה כוח ישראלי, "
                            f"ואינם נכללים."),
            "agents_aria": (f"תרשים עמודות אופקי: מיופי הכוח המובילים בבקשות הלאומיות {ay0}-{as_of_year}. "
                            f"המוביל: {top_agent_name}."),
            "lag_note": (f"חציון ורבעונים של הזמן מהגשת הבקשה ועד רישום הסימן, לפי שנת הרישום "
                         f"(שנים עם {LAG_MIN_N} רישומים לפחות). {_int(lag_excl)} רשומות עם פער "
                         f"שלילי או ארוך מ-{LAG_MAX_DAYS // 366} שנים הוחרגו."),
            "lag_aria": (f"תרשים קו: משך הזמן החציוני מהגשה לרישום לפי שנת רישום. "
                         f"ב-{lag_last_year}: {lag_last:.1f} חודשים." if lag_last_year else
                         "תרשים קו: משך הזמן מהגשה לרישום."),
            "expiry_note": (f"סימנים רשומים לפי שנת תום התוקף הנוכחית — המועד שבו יש לחדש אותם. "
                            f"{_int(reg_no_future_exp)} סימנים רשומים ללא מועד תוקף עתידי במאגר "
                            f"אינם מוצגים."),
            "expiry_aria": (f"תרשים עמודות: סימנים רשומים לפי שנת תום תוקף, "
                            f"{expiry_chart['x'][0] if expiry_chart['x'] else ''}-"
                            f"{expiry_chart['x'][-1] if expiry_chart['x'] else ''}."),
            "features_note": (f"אחוז הבקשות בכל שנת הגשה שהן סימן עם דמות (לוגו), שתובעות דין "
                              f"קדימה מבקשה קודמת בחו״ל, שכוללות כיתוב בעברית, או שמבוססות על "
                              f"רישום חיצוני. בכל המאגר: {_int(n_fig)} סימנים עם דמות, "
                              f"{_int(n_prio)} עם דין קדימה, {_int(n_foreign)} על בסיס רישום חיצוני."),
            "features_aria": (f"תרשים קווים: מאפייני הבקשות לפי שנת הגשה באחוזים, {fy0}-{as_of_year}."),
            "vienna_note": (f"הקטגוריות הראשיות בסיווג וינה של הרכיבים הציוריים, מתוך "
                            f"{_int(n_vienna)} סימנים שסווגו; סימן אחד יכול להשתייך לכמה קטגוריות."),
            "vienna_aria": (f"תרשים עמודות אופקי: {len(vi_counts)} קטגוריות וינה הנפוצות ברכיבים "
                            f"הציוריים של סימנים."),
            "extras": (f"במאגר {_int(n_licensed)} סימנים עם בעל רשות (רישיון שימוש) רשום, "
                       f"ו-{_int(n_customs)} סימנים רשומים שמונה להם מייצג לעניין אכיפה במכס — "
                       f"מנגנון המאפשר לעכב בנמל יבוא של מוצרים מזויפים."),
        },
    }
