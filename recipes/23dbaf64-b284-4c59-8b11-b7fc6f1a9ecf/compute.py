"""פנקס מאגרי המידע — the Privacy Protection Authority's public register of
personal-data databases (one row per registered database, ~32k).

"Now" is the latest registration date in the register (its data vintage),
never the wall clock. Rows that repeat a database number (the same database
listed under several addresses) are collapsed to one database; the city
chart counts each database once, at its first address after a total sort.

Owners are organisations and are named. Rows whose owner name and id are
both blank are owners whose details the register withholds (the CKAN notes:
only the parts allowed for publication given owners' privacy) — they are
counted, never named. Owner ids are used only for their legal-entity prefix
(an aggregate classification); no id ever reaches the page.
"""
import re

import pandas as pd

COLS = {
    "num": "מספר מאגר",
    "oid": "מזהה בעל המאגר",
    "owner": "שם מלא",
    "name": "שם המאגר",
    "city": "ישוב",
    "abroad": "העברת מידע לחול",
    "status": "סטטוס מאגר",
    "date": "תאריך רישום המאגר",
    "types": "סוגי מידע",
    "purposes": "מטרות",
    "public_src": "קבלת מידע דרך קבע מגוף ציבורי",
    "holders": "מחזיקים במאגר",
}
LAW_YEAR = 1981            # the Privacy Protection Law; earlier dates are placeholders (1900)
TOP_OWNERS = 12
TOP_TYPES = 15
TOP_PURPOSES = 12
TOP_HOLDERS = 12
TOP_CITIES = 15
TOP_NAMES = 15
HEAT_TYPES = 10
MIN_CATEGORY = 50          # a purpose/type value below this is free text, grouped
ABROAD_MIN = 50            # min databases for an owner type's abroad rate
RECENT_MONTHS = 36
NTYPES_CAP = 8
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
STATUS_ORDER = ["מאושר", "בוער", "מבוטל", "מותלה רישוי"]
WITHHELD = "פרטי הבעלים לא פורסמו"
OWNER_TYPES = [  # (label, predicate on the id string)
    ("חברה פרטית", lambda s: len(s) == 9 and s.startswith("51")),
    ("גוף ציבורי (ממשלה ורשויות)", lambda s: len(s) == 9 and s.startswith("50")),
    ("חברה ציבורית (כולל חל״צ)", lambda s: len(s) == 9 and s.startswith("52")),
    ("עמותה", lambda s: len(s) == 9 and s.startswith("58")),
    ("אגודה שיתופית", lambda s: len(s) == 9 and s.startswith("57")),
    ("שותפות", lambda s: len(s) == 9 and s[:2] in ("53", "54", "55")),
    ("חברה זרה", lambda s: len(s) == 9 and s.startswith("56")),
    ("קוד מוסד (קופות חולים, בתי ספר)", lambda s: 5 <= len(s) <= 6),
]
OTHER_OWNER = "אחר"
OTHER = "אחר"
FREE_OTHER = "אחר (פירוט חופשי)"
FREE_SENS = "אחר רגיש (פירוט חופשי)"
FREE_NONSENS = "אחר לא רגיש (פירוט חופשי)"

HEB = "֐-׿"


def clean(s):
    """The register writes quote marks as '~' (בע~מ) and commas as '~ '."""
    s = s.replace("#x0D", " ").strip()
    s = re.sub(r"(^|\s)~([^~]+?)~", r'\1"\2"', s)           # ~quoted~ phrase
    s = re.sub(rf"(?<=[{HEB}])~(?=[{HEB}])", "״", s)          # בע~מ -> בע״מ
    s = re.sub(r"\)([^()]+)\(", r"(\1)", s)                  # reversed parens
    s = s.replace("~ ", ", ").replace("~", '"')
    return re.sub(r"\s+", " ", s).strip()


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def pnum(v, digits=1):
    return f"{v:.{digits}f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def m_he(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def owner_type(oid, owner):
    if not oid and not owner:
        return WITHHELD
    for label, f in OWNER_TYPES:
        if f(oid):
            return label
    return OTHER_OWNER


def split_list(s):
    return [v for v in (x.strip() for x in s.replace("#x0D", " ").split(";")) if v]


def _sorted_counts(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _top(counts, k, other_label=OTHER):
    top = counts.head(k)
    rest = int(counts.iloc[k:].sum())
    names = list(top.index) + ([other_label] if rest else [])
    vals = [int(v) for v in top.values] + ([rest] if rest else [])
    return names, vals


def _prepare(raw):
    df = pd.DataFrame({k: raw[c].astype(str).str.strip() for k, c in COLS.items()})
    rows_in = len(df)
    df = df.sort_values(list(df.columns), kind="stable")
    df = df.drop_duplicates(subset=["num"], keep="first").reset_index(drop=True)
    dup_rows = rows_in - len(df)
    df["owner"] = df["owner"].map(clean)
    df["name"] = df["name"].map(clean)
    df["city"] = df["city"].map(clean)
    df["otype"] = [owner_type(o, w) for o, w in zip(df["oid"], df["owner"])]
    dt = pd.to_datetime(df["date"].str.split().str.join(" "),
                        format="%b %d %Y %I:%M%p", errors="coerce")
    df["dt"] = dt.where(dt.dt.year >= LAW_YEAR)
    df["status"] = df["status"].replace("", "לא צוין")
    df["abroad_yes"] = df["abroad"] == "כן"
    df["type_list"] = df["types"].map(split_list)
    df["purp_list"] = df["purposes"].map(split_list)
    df["hold_list"] = df["holders"].map(lambda s: [clean(x) for x in split_list(s)])
    df["src_list"] = df["public_src"].map(lambda s: [clean(x) for x in split_list(s)])
    return df, dup_rows


def _expand_sensitive(v):
    """'אחר רגיש-אישיות~מצב כלכלי' -> ['מצב כלכלי (רגיש)', 'אישיות (רגיש)']."""
    if not v.startswith("אחר רגיש"):
        return [v]
    rest = v[len("אחר רגיש"):].lstrip("-").strip()
    parts = [p.strip(" .-") for p in rest.split("~")]
    parts = [p for p in parts if p]
    return [f"{p} (רגיש)" for p in parts] or [FREE_SENS]


def _canon_types(lists):
    lists = [[x for v in lst for x in _expand_sensitive(v)] for lst in lists]
    flat = pd.Series([v for lst in lists for v in lst], dtype=object)
    vc = flat.value_counts()
    keep = set(vc[vc >= MIN_CATEGORY].index)

    def canon(v):
        if v.startswith("אחר לא רגיש"):
            return [FREE_NONSENS]
        if v.endswith(" (רגיש)") and v not in keep:
            return [FREE_SENS]
        return [clean(v) if v in keep else OTHER]
    return [sorted({c for v in lst for c in canon(v)}) for lst in lists]


def _canon_purposes(lists):
    flat = pd.Series([v for lst in lists for v in lst], dtype=object)
    vc = flat.value_counts()
    keep = set(vc[vc >= MIN_CATEGORY].index)

    def canon(v):
        if v.startswith("אחר"):
            return FREE_OTHER
        return clean(v) if v in keep else OTHER
    return [sorted({canon(v) for v in lst}) for lst in lists]


def _count_lists(lists):
    return _sorted_counts(pd.Series([v for lst in lists for v in lst], dtype=object))


# ---------------------------------------------------------------- insights

def insight_status(status, total):
    ok = int(status.get("מאושר", 0))
    if total == 0 or ok == 0:
        return None
    parts = [f"{n(v)} {k}" for k, v in status.items() if k != "מאושר" and v]
    rest = f"; יתר המאגרים: {', '.join(parts)}" if parts else ""
    return (f"{n(ok)} מתוך {n(total)} המאגרים בפנקס ({pct(ok / total * 100)}) "
            f"רשומים בסטטוס ״מאושר״{rest}.")


def insight_recent(df, ref):
    d = df["dt"].dropna()
    last = int(((d > ref - pd.Timedelta(days=365)) & (d <= ref)).sum())
    prev = int(((d > ref - pd.Timedelta(days=730)) & (d <= ref - pd.Timedelta(days=365))).sum())
    if prev < 50:
        return None
    chg = last / prev - 1
    span = f"בשנה שהסתיימה ב-{d_he(ref)}"
    if abs(chg) < 0.1:
        return f"{span} נרשמו {n(last)} מאגרים חדשים — בדומה לשנה שקדמה לה ({n(prev)})."
    word = "עלייה" if chg > 0 else "ירידה"
    return (f"{span} נרשמו {n(last)} מאגרים חדשים, לעומת {n(prev)} בשנה שקדמה לה — "
            f"{word} של {pct(abs(chg) * 100, 0)}.")


def insight_gap(months, counts, partial):
    """Longest run of months with no registration inside the recent window."""
    best, cur, start, best_start = 0, 0, None, None
    usable = len(months) - (1 if partial else 0)
    for i in range(usable):
        if counts[i] == 0:
            if cur == 0:
                start = i
            cur += 1
            if cur > best:
                best, best_start = cur, start
        else:
            cur = 0
    if best < 2:
        return None
    a, b = months[best_start], months[best_start + best - 1]
    return (f"בחלון של {len(months)} החודשים האחרונים בולט רצף של {best} חודשים ללא אף רישום "
            f"חדש בפנקס: {m_he(a)}–{m_he(b)}.")


def insight_peak(per_year, total_dated):
    if per_year.empty or total_dated == 0:
        return None
    y = int(per_year.sort_index().idxmax())
    v = int(per_year[y])
    share = v / total_dated
    if share < 0.08:
        return None
    return (f"שנת השיא ברישום היא {y}, עם {n(v)} מאגרים ({pct(share * 100)} מהמאגרים "
            f"שתאריך רישומם ידוע).")


def insight_owner(owners, total):
    if owners.empty:
        return None
    name, v = owners.index[0], int(owners.iloc[0])
    if v / total < 0.03:
        return None
    second = (f"; אחריו {owners.index[1]} ({n(owners.iloc[1])})"
              if len(owners) > 1 else "")
    return (f"בעל המאגרים הגדול בפנקס הוא {name}, עם {n(v)} מאגרים רשומים "
            f"({pct(v / total * 100)} מכלל הפנקס){second}.")


def insight_otype(otypes, total):
    if otypes.empty:
        return None
    lead = [k for k in otypes.index if k != WITHHELD][0]
    v = int(otypes[lead])
    w = int(otypes.get(WITHHELD, 0))
    s = f"סוג הבעלים הנפוץ בפנקס: {lead} — {n(v)} מאגרים ({pct(v / total * 100)})"
    if w / total >= 0.02:
        s += f"; ב-{n(w)} מאגרים ({pct(w / total * 100)}) פרטי הבעלים אינם מפורסמים"
    return s + "."


def insight_types(types, total, medical):
    if types.empty:
        return None
    name, v = types.index[0], int(types.iloc[0])
    s = f"סוג המידע הנפוץ ביותר במאגרים הוא {name} ({pct(v / total * 100)} מהמאגרים)"
    if medical / total >= 0.1:
        s += f"; {n(medical)} מאגרים ({pct(medical / total * 100)}) מחזיקים מידע רפואי"
    return s + "."


def insight_abroad(df, purposes_rate):
    total = len(df)
    yes = int(df["abroad_yes"].sum())
    if total == 0 or yes == 0:
        return None
    s = f"{n(yes)} מאגרים ({pct(yes / total * 100)}) מדווחים על העברת מידע לחו״ל"
    if purposes_rate:
        name, r, cnt = purposes_rate[0]
        if r >= 2 * yes / total:
            s += (f"; השיעור הגבוה ביותר — {pct(r * 100)} — במאגרים שבעליהם {name} "
                  f"({n(cnt)} מאגרים)")
    return s + "."


def insight_holders(df, holders):
    total = len(df)
    out = int((df["hold_list"].str.len() > 0).sum())
    if out / total < 0.05 or holders.empty:
        return None
    return (f"ב-{n(out)} מאגרים ({pct(out / total * 100)}) המידע מוחזק גם אצל גורם חיצוני; "
            f"המחזיק הנפוץ ביותר הוא {holders.index[0]} ({n(holders.iloc[0])} מאגרים).")


def insight_public_src(df, srcs):
    k = int((df["src_list"].str.len() > 0).sum())
    if k < 20 or srcs.empty:
        return None
    return (f"רק {n(k)} מאגרים ({pct(k / len(df) * 100, 2)}) מקבלים מידע דרך קבע מגוף ציבורי; "
            f"המקור השכיח הוא {srcs.index[0]} ({n(srcs.iloc[0])} מאגרים).")


# ---------------------------------------------------------------- compute

def compute(frames):
    df, dup_rows = _prepare(frames["registry"])
    total = len(df)
    ref = df["dt"].max()
    ref_p = ref.to_period("M")
    month_end = (ref_p + 1).to_timestamp() - pd.Timedelta(days=1)
    partial = ref.day < month_end.day - 3

    status = df["status"].value_counts()
    status_names = ([s for s in STATUS_ORDER if s in status.index]
                    + sorted(s for s in status.index if s not in STATUS_ORDER))
    status = status.reindex(status_names)

    # Yearly registrations by status.
    dated = df[df["dt"].notna()]
    undated = total - len(dated)
    yr = dated.groupby([dated["dt"].dt.year, "status"]).size().unstack(fill_value=0)
    yr = yr.reindex(range(int(yr.index.min()), int(yr.index.max()) + 1), fill_value=0)
    years = [int(y) for y in yr.index]
    per_year = yr.sum(axis=1)

    # Monthly registrations, last RECENT_MONTHS months ending at ref's month.
    months = list(pd.period_range(ref_p - (RECENT_MONTHS - 1), ref_p, freq="M"))
    mc = dated["dt"].dt.to_period("M").value_counts()
    m_counts = [int(mc.get(p, 0)) for p in months]

    # Owners.
    named = df[df["owner"] != ""]
    owners = _sorted_counts(named["owner"])
    otypes = _sorted_counts(df["otype"])
    ot_names = list(otypes.index)
    distinct_owners = int(named["owner"].nunique())

    # Data types.
    df["tcanon"] = _canon_types(df["type_list"])
    types = _count_lists(df["tcanon"])
    # Top-N named types; the tail bar counts DATABASES holding any other type
    # (not summed mentions), so it reads on the same scale as the others.
    t_names = [t for t in types.index if t != OTHER][:TOP_TYPES]
    t_vals = [int(types[t]) for t in t_names]
    top_set = set(t_names)
    tail = int(df["tcanon"].map(lambda l: any(x not in top_set for x in l)).sum())
    if tail:
        t_names, t_vals = t_names + [OTHER], t_vals + [tail]
    medical = int(df["type_list"].map(lambda l: any("רפואי" in x for x in l)).sum())
    ntypes = df["tcanon"].str.len().clip(upper=NTYPES_CAP)
    nt_rows = [(f"{k}+" if k == NTYPES_CAP else str(k), int((ntypes == k).sum()))
               for k in range(0, NTYPES_CAP + 1)]
    no_types = int((ntypes == 0).sum())
    med_ntypes = float(df["tcanon"].str.len()[df["tcanon"].str.len() > 0].median())

    # Heatmap: owner type × top data types, % of that owner type's databases.
    heat_types = [t for t in types.index if t not in (OTHER, FREE_SENS, FREE_NONSENS)][:HEAT_TYPES]
    heat_rows = [o for o in ot_names if int(otypes[o]) >= 100]
    cells, heat_table = [], []
    for yi, o in enumerate(heat_rows):
        sub = df.loc[df["otype"] == o, "tcanon"]
        row = []
        for xi, t in enumerate(heat_types):
            share = round(float(sub.map(lambda l, t=t: t in l).mean() * 100), 1)
            cells.append([xi, yi, share])
            row.append(pnum(share))
        heat_table.append({"otype": o, "count": n(len(sub)), "cells": row})

    # Purposes.
    df["pcanon"] = _canon_purposes(df["purp_list"])
    purposes = _count_lists(df["pcanon"])
    std_purposes = purposes[[p not in (OTHER, FREE_OTHER) for p in purposes.index]]
    p_top = std_purposes.head(TOP_PURPOSES)
    free_other = int(df["pcanon"].map(lambda l: FREE_OTHER in l).sum())
    p_names = list(p_top.index)
    p_vals = [int(v) for v in p_top.values]

    # Transfer-abroad rate by owner type.
    abroad_by_ot = []
    for o in ot_names:
        m = df["otype"] == o
        abroad_by_ot.append((o, round(float(df.loc[m, "abroad_yes"].mean() * 100), 1), int(m.sum())))
    rates = sorted(((o, r / 100, c) for o, r, c in abroad_by_ot if c >= ABROAD_MIN),
                   key=lambda r: (-r[1], r[0]))

    # Holders.
    holders = _count_lists(df["hold_list"])
    h_names, h_vals = list(holders.head(TOP_HOLDERS).index), [int(v) for v in holders.head(TOP_HOLDERS)]
    outsourced = int((df["hold_list"].str.len() > 0).sum())
    distinct_holders = int(holders.size)

    # Public-body sources.
    srcs = _count_lists(df["src_list"])

    # Cities.
    cities = _sorted_counts(df.loc[df["city"] != "", "city"])
    c_names, c_vals = list(cities.head(TOP_CITIES).index), [int(v) for v in cities.head(TOP_CITIES)]
    no_city = int((df["city"] == "").sum())

    # Database names (normalised: leading "מאגר" dropped).
    nm = df["name"].str.replace(r"^מאגר\s+", "", regex=True).str.strip()
    nm = nm[(nm != "") & (nm != "ללא שם")]
    names = _sorted_counts(nm)
    nm_names, nm_vals = list(names.head(TOP_NAMES).index), [int(v) for v in names.head(TOP_NAMES)]
    unnamed = int((df["name"].isin(["", "ללא שם"])).sum())

    # ------------------------------------------------------------ KPIs
    approved = int(status.get("מאושר", 0))
    appr_share = approved / total * 100
    d = df["dt"].dropna()
    last12 = int(((d > ref - pd.Timedelta(days=365)) & (d <= ref)).sum())
    prev12 = int(((d > ref - pd.Timedelta(days=730)) & (d <= ref - pd.Timedelta(days=365))).sum())
    chg = (last12 / prev12 - 1) if prev12 else 0.0
    recent_tone = ("ok" if chg >= 0.1 else "danger" if chg <= -0.25
                   else "warn" if chg <= -0.1 else "brand")
    abroad = int(df["abroad_yes"].sum())
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "approved": {"value": round(appr_share, 1), "display": pnum(appr_share),
                     "tone": "ok" if appr_share >= 75 else "warn" if appr_share < 50 else "brand"},
        "recent": {"value": last12, "display": n(last12), "tone": recent_tone},
        "owners": {"value": distinct_owners, "display": n(distinct_owners), "tone": "brand"},
        "abroad": {"value": round(abroad / total * 100, 1),
                   "display": pnum(abroad / total * 100), "tone": "info"},
        "outsourced": {"value": round(outsourced / total * 100, 1),
                       "display": pnum(outsourced / total * 100), "tone": "info"},
    }

    # ------------------------------------------------------------ charts
    st_cols = [s for s in status_names if s in yr.columns]
    charts = {
        "years": {"x": [str(y) for y in years],
                  "series": [{"name": s, "data": [int(v) for v in yr[s]]} for s in st_cols]},
        "recent": {"x": [m_he(p) for p in months], "y": m_counts},
        "status": {"names": status_names, "values": [int(v) for v in status.values]},
        "otypes": {"names": ot_names, "values": [int(otypes[o]) for o in ot_names]},
        "owners": {"names": list(owners.head(TOP_OWNERS).index),
                   "values": [int(v) for v in owners.head(TOP_OWNERS)]},
        "types": {"names": t_names, "values": t_vals},
        "heat": {"x": heat_types, "y": heat_rows, "cells": cells,
                 "max": max([c[2] for c in cells] or [1])},
        "ntypes": {"names": [k for k, _ in nt_rows], "values": [v for _, v in nt_rows]},
        "purposes": {"names": p_names, "values": p_vals},
        "abroad": {"names": [r[0] for r in rates], "values": [round(r[1] * 100, 1) for r in rates],
                   "avg": round(abroad / total * 100, 1)},
        "holders": {"names": h_names, "values": h_vals},
        "cities": {"names": c_names, "values": c_vals},
        "names": {"names": nm_names, "values": nm_vals},
    }

    rules = [
        ("status", insight_status(status, total)),
        ("recent", insight_recent(df, ref)),
        ("gap", insight_gap(months, m_counts, partial)),
        ("peak", insight_peak(per_year, len(dated))),
        ("owner", insight_owner(owners, total)),
        ("otype", insight_otype(otypes, total)),
        ("types", insight_types(types, total, medical)),
        ("abroad", insight_abroad(df, rates)),
        ("holders", insight_holders(df, holders)),
        ("public_src", insight_public_src(df, srcs)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    first_year = years[0]
    partial_note = f" {m_he(ref_p)} — חודש חלקי, עד {d_he(ref)}." if partial else ""
    top_heat = max(cells, key=lambda c: (c[2], -c[1], -c[0])) if cells else None
    labels = {
        "lede": (f"פנקס מאגרי המידע של הרשות להגנת הפרטיות במשרד המשפטים: {n(total)} מאגרי מידע "
                 f"אישי רשומים, של {n(distinct_owners)} בעלי מאגרים מזוהים — מטרת המאגר, סוגי "
                 f"המידע שבו, מי מחזיק בו והאם הוא מועבר לחו״ל. הרישום האחרון בפנקס: {d_he(ref)}."),
        "approved_kpi": "מהמאגרים בסטטוס ״מאושר״",
        "recent_kpi": ("מאגרים שנרשמו בשנה האחרונה (ללא שינוי משנה קודמת)"
                       if prev12 and round(abs(chg) * 100) == 0 else
                       f"מאגרים שנרשמו בשנה האחרונה (שינוי של {'+' if chg > 0 else '−'}"
                       f"{abs(chg) * 100:.0f}% משנה קודמת)" if prev12 else
                       "מאגרים שנרשמו בשנה האחרונה"),
        "years_note": (f"מאגרים לפי שנת רישום בפנקס ולפי הסטטוס הנוכחי שלהם, מ-{first_year}. "
                       f"{n(undated)} מאגרים ({pct(undated / total * 100)}) רשומים ללא תאריך "
                       f"רישום תקין ואינם נכללים."),
        "years_aria": (f"גרף עמודות מוערמות: מאגרים לפי שנת רישום וסטטוס, {first_year} עד "
                       f"{ref.year}. שנת השיא: {int(per_year.idxmax())}."),
        "recent_note": (f"מאגרים חדשים שנרשמו בכל חודש, {len(months)} החודשים האחרונים."
                        f"{partial_note}"),
        "recent_aria": f"גרף עמודות: מאגרים חדשים לפי חודש רישום, {len(months)} החודשים האחרונים.",
        "status_aria": f"תרשים עמודות: מאגרים לפי סטטוס. {pct(appr_share)} בסטטוס מאושר.",
        "status_caption": "מספר מאגרים לפי סטטוס בפנקס.",
        "otypes_note": (f"סוג בעל המאגר לפי מבנה מספר הזיהוי שלו (מספר תאגיד: חברה, עמותה, "
                        f"אגודה וכו׳). ״{WITHHELD}״ — שם הבעלים ומספרו אינם בקובץ, בהתאם להחרגת "
                        f"פרטים מטעמי פרטיות."),
        "otypes_aria": f"תרשים עמודות: מאגרים לפי סוג בעל המאגר. המוביל: {ot_names[0]}.",
        "otypes_caption": "מספר מאגרים לפי סוג בעל המאגר.",
        "owners_note": (f"בעלי המאגרים עם המספר הגדול ביותר של מאגרים רשומים (בעלים שפרטיהם לא "
                        f"פורסמו אינם נכללים). ארגון גדול רושם לעתים מאגר נפרד לכל סניף או יחידה."),
        "owners_aria": f"תרשים עמודות: {TOP_OWNERS} בעלי המאגרים הגדולים לפי מספר מאגרים.",
        "owners_caption": f"{TOP_OWNERS} בעלי המאגרים עם מספר המאגרים הגדול ביותר.",
        "types_note": (f"מספר המאגרים המחזיקים כל סוג מידע (מאגר יכול להחזיק כמה סוגים). "
                       f"״אחר״ — מאגרים המחזיקים סוג מידע אחר כלשהו (כולל סוגים שמופיעים "
                       f"בפחות מ-{n(MIN_CATEGORY)} מאגרים); "
                       f"{n(no_types)} מאגרים רשומים ללא סוג מידע."),
        "types_aria": f"תרשים עמודות: {TOP_TYPES} סוגי המידע הנפוצים במאגרים.",
        "types_caption": "מספר מאגרים לפי סוג מידע.",
        "heat_note": (f"באיזה שיעור מהמאגרים של כל סוג בעלים מופיע כל סוג מידע ({HEAT_TYPES} "
                      f"הסוגים הנפוצים; סוגי בעלים עם {n(100)} מאגרים לפחות)."),
        "heat_aria": ("מפת חום: שיעור המאגרים המחזיקים כל סוג מידע, לפי סוג בעל המאגר."
                      + (f" השיעור הגבוה: {top_heat[2]}% — {heat_types[top_heat[0]]} אצל "
                         f"{heat_rows[top_heat[1]]}." if top_heat else "")),
        "heat_caption": "שיעור המאגרים המחזיקים כל סוג מידע, לפי סוג בעל המאגר.",
        "ntypes_note": (f"כמה סוגי מידע שונים מוחזקים בכל מאגר. החציון: {med_ntypes:g} סוגים "
                        f"(במאגרים שצוין להם סוג)."),
        "ntypes_aria": "תרשים עמודות: מאגרים לפי מספר סוגי המידע שבהם.",
        "ntypes_caption": "מספר מאגרים לפי מספר סוגי המידע.",
        "purposes_note": (f"מטרות המאגר מתוך רשימת המטרות הקבועה (מאגר יכול לציין כמה מטרות). "
                          f"{n(free_other)} מאגרים ({pct(free_other / total * 100)}) ציינו "
                          f"גם או רק מטרה ״אחר״ בתיאור חופשי, שאינה מוצגת."),
        "purposes_aria": f"תרשים עמודות: {len(p_names)} מטרות המאגר הנפוצות.",
        "purposes_caption": "מספר מאגרים לפי מטרה.",
        "abroad_note": (f"שיעור המאגרים המדווחים על העברת מידע לחו״ל, לפי סוג בעל המאגר (סוגים עם "
                        f"{n(ABROAD_MIN)} מאגרים לפחות). הקו המקווקו — השיעור בכלל הפנקס "
                        f"({pct(abroad / total * 100)})."),
        "abroad_aria": ("תרשים עמודות: שיעור המאגרים המעבירים מידע לחו״ל לפי סוג בעל המאגר."
                        + (f" הגבוה: {rates[0][0]}, {rates[0][1] * 100:.1f}%." if rates else "")),
        "abroad_caption": "שיעור המאגרים המעבירים מידע לחו״ל, לפי סוג בעל המאגר.",
        "holders_note": (f"גורמים חיצוניים המחזיקים במידע עבור בעל המאגר, כפי שדווחו בפנקס. "
                         f"{n(outsourced)} מאגרים ({pct(outsourced / total * 100)}) "
                         f"מציינים מחזיק אחד לפחות, מתוך {n(distinct_holders)} מחזיקים שונים."),
        "holders_aria": f"תרשים עמודות: {TOP_HOLDERS} המחזיקים החיצוניים הנפוצים.",
        "holders_caption": f"{TOP_HOLDERS} המחזיקים החיצוניים הנפוצים, לפי מספר מאגרים.",
        "cities_note": (f"יישוב הכתובת הרשומה של בעל המאגר. {n(no_city)} מאגרים ללא יישוב "
                        f"אינם נכללים."),
        "cities_aria": f"תרשים עמודות: {TOP_CITIES} היישובים עם המספר הגדול ביותר של מאגרים. המוביל: {c_names[0] if c_names else ''}.",
        "cities_caption": f"{TOP_CITIES} היישובים המובילים לפי מספר מאגרים.",
        "names_note": (f"שמות המאגרים החוזרים ביותר (המילה ״מאגר״ בתחילת השם הושמטה). "
                       f"{n(unnamed)} מאגרים רשומים ללא שם."),
        "names_aria": f"תרשים עמודות: {TOP_NAMES} שמות המאגרים הנפוצים.",
        "names_caption": f"{TOP_NAMES} שמות המאגרים הנפוצים.",
        "dedup_note": (f"{n(dup_rows)} שורות החוזרות על מספר מאגר קיים (זהות, או שונות רק "
                       f"בכתובת) אוחדו, כך שכל מאגר נספר פעם אחת." if dup_rows else ""),
    }

    tables = {
        "status": [{"name": k, "count": n(v), "share": pnum(v / total * 100)}
                   for k, v in zip(status_names, status.values)],
        "otypes": [{"name": o, "count": n(otypes[o]), "share": pnum(otypes[o] / total * 100)}
                   for o in ot_names],
        "owners": [{"name": k, "count": n(v)} for k, v in owners.head(TOP_OWNERS).items()],
        "types": [{"name": k, "count": n(v), "share": pnum(v / total * 100)}
                  for k, v in zip(t_names, t_vals)],
        "heat": heat_table,
        "heat_x": heat_types,
        "ntypes": [{"k": k, "count": n(v)} for k, v in nt_rows],
        "purposes": [{"name": k, "count": n(v)} for k, v in zip(p_names, p_vals)],
        "abroad": [{"name": p, "rate": pnum(r * 100), "count": n(c)} for p, r, c in rates],
        "holders": [{"name": k, "count": n(v)} for k, v in zip(h_names, h_vals)],
        "cities": [{"name": k, "count": n(v)} for k, v in zip(c_names, c_vals)],
        "names": [{"name": k, "count": n(v)} for k, v in zip(nm_names, nm_vals)],
    }

    return {
        "agent_data": {
            "summary_he": (f"פנקס מאגרי המידע של הרשות להגנת הפרטיות: {n(total)} מאגרי מידע אישי "
                           f"רשומים — בעל המאגר, מטרתו, סוגי המידע, מחזיקים חיצוניים והעברה "
                           f"לחו״ל; {pnum(appr_share)} בסטטוס מאושר."),
            "dataset_kind": "registry",
            "related_ids": ["669b2652-f75b-4de3-8e6b-0dfa17accef5",
                            "713440a1-9963-4548-a7d9-9d9c9da54f62",
                            "3111ae54-790a-4d02-9750-d51e1134b405",
                            "01aeaf5c-59a2-4ddc-a616-31b85621bfe2",
                            "1806c96c-9cc4-47bf-98b3-80a18f061f98"],
            "suggested_tags": ["הגנת הפרטיות", "מאגרי מידע", "מידע אישי", "רישום", "משרד המשפטים"],
            "temporal_coverage": f"{first_year}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
