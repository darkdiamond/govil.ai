"""מאגר שותפויות — רשם השותפויות: every partnership ever registered in Israel (~29k).

One row per partnership: type (Israeli general / Israeli limited / foreign),
status, registration ("incorporation") date and a registered address. There is
no amount to rank partnerships by, so the page aggregates: registrations over
time and their mix, survival by cohort, status, geography, and a keyword-based
read of what the partnerships do (from their names — disclosed as such).

"Now" is the latest registration date in the data; the current year and month
are partial and are compared only against the same calendar window earlier.
The registrar export writes '~' for '"' inside abbreviations (חו~ל, בימ~ש).
"""
import pandas as pd

GROUPS = ["פעילה", "נמחקה", "פורקה או חוסלה", "בפירוק", "אחר"]
TYPE_GENERAL = "ישראלית כללית"
TYPE_LIMITED = "ישראלית מוגבלת"
FOREIGN = "שותפות זרה"
COHORT_FROM = 1980
HEAT_YEARS = 15
MONTHS = 24
TOP_TOWNS = 12
TOP_STATUS = 14
SURVIVAL_YEARS = 10
SURVIVAL_WINDOW = 5
MIX_GAP = 10
MIN_COHORT = 30
SURGE_UP = 1.5
SURGE_DOWN = 0.5

# Keyword read of a partnership's line of business, from its Hebrew or English
# name. First match wins, in this order; unmatched names stay "לא סווג".
SECTORS = [
    ("משרדי עורכי דין", r'עורכי[ -]*דין|עו"ד|משרד עורכ|ADVOCATES|LAW OFFICE'),
    ("משרדי רואי חשבון", r'רואי[ -]*חשבון|רו"ח|CPA|ACCOUNTANTS'),
    ("אנרגיה", r"אנרגי|סולאר|סולרי|וולטא|ENERGY|SOLAR|POWER"),
    ('נדל"ן ובנייה', r'נדל"ן|נדלן|נכסים|בנייה|בניה|מגורים|פינוי|התחדשות|דיור|REAL ESTATE|PROPERTIES'),
    ("השקעות וקרנות", r"קרן ל|קרנות|השקע|קפיטל|ונצ'רס|ונצרס|פרטנרס|פאנד|FUND|CAPITAL|VENTURE|INVEST"),
    ("חקלאות", r"חקלא|רפת|פרדס|חוות|^משק |מטעי"),
]
UNCLASSIFIED = "לא סווג"


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _clean(s):
    return s.str.replace("~", '"', regex=False).str.strip()


def _group(status):
    if status in ("פעילה", "פעילה זמנית"):
        return "פעילה"
    if "מחוק" in status:
        return "נמחקה"
    if "בפרוק" in status or "בפירוק" in status:
        return "בפירוק"
    if "פורק" in status or "מחוסלת" in status or "חיסול" in status:
        return "פורקה או חוסלה"
    return "אחר"


def _type_group(t):
    return t if t.startswith("ישראלית") else FOREIGN


def _vc(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _top(vc, n, other="אחר"):
    head = [(k, int(v)) for k, v in vc.head(n).items()]
    rest = int(vc.iloc[n:].sum())
    if rest:
        head.append((other, rest))
    return head


def _growth_tone(cur, prev, threshold=0.03):
    if not prev:
        return "brand"
    ch = (cur - prev) / prev
    return "ok" if ch >= threshold else "warn" if ch <= -threshold else "brand"


def _year_ago(ts):
    try:
        return ts.replace(year=ts.year - 1)
    except ValueError:
        return ts.replace(year=ts.year - 1, day=28)


def _prepare(raw):
    eng = raw["שם באנגלית"].str.upper().str.strip()
    df = pd.DataFrame({
        "name": _clean(raw["שם שותפות"]),
        "type": _clean(raw["סוג תאגיד"]),
        "status": _clean(raw["סטטוס תאגיד"]),
        "founded": pd.to_datetime(raw["תאריך התאגדות"].str.strip(), format="%d/%m/%Y", errors="coerce"),
        "town": raw["ישוב"].str.strip(),
        "country": raw["מדינה"].str.strip(),
    })
    df["group"] = df["status"].map(_group)
    df["tgroup"] = df["type"].map(_type_group)
    text = df["name"] + " " + eng
    sector = pd.Series(UNCLASSIFIED, index=df.index)
    left = pd.Series(True, index=df.index)
    for label, rx in SECTORS:
        m = left & text.str.contains(rx, regex=True)
        sector[m] = label
        left &= ~m
    df["sector"] = sector
    return df


def _ytd(df, now):
    start, prev_start, prev_end = pd.Timestamp(now.year, 1, 1), pd.Timestamp(now.year - 1, 1, 1), _year_ago(now)
    a = int(((df["founded"] >= start) & (df["founded"] <= now)).sum())
    b = int(((df["founded"] >= prev_start) & (df["founded"] <= prev_end)).sum())
    return a, b


# ── insights ────────────────────────────────────────────────────────────────

def insight_active(df):
    n = len(df)
    act = int((df["group"] == "פעילה").sum())
    struck = int((df["group"] == "נמחקה").sum())
    gone = int((df["group"] == "פורקה או חוסלה").sum())
    return (f"מתוך {_int(n)} שותפויות שנרשמו אי-פעם, {_int(act)} ({_pct(act / n)}) פעילות היום; "
            f"{_int(struck)} נמחקו מהמרשם ו-{_int(gone)} פורקו או חוסלו.")


def insight_registrations(df, now):
    y = df["founded"].dt.year
    full, prev = now.year - 1, now.year - 2
    a, b = int((y == full).sum()), int((y == prev).sum())
    if b < 50:
        return None
    ch = (a - b) / b
    trend = ("בדומה לשנה שקדמה לה" if abs(ch) < 0.03
             else f"{'עלייה' if ch > 0 else 'ירידה'} של {_pct(abs(ch))} לעומת {prev} ({_int(b)})")
    vc = y[y < now.year].value_counts().sort_index()
    peak = int(vc.idxmax())
    tail = (" זו שנת השיא במאגר." if peak == full
            else f" שנת השיא בשנים המלאות: {peak} ({_int(vc.max())}).")
    return f"ב-{full} נרשמו {_int(a)} שותפויות חדשות — {trend}.{tail}"


def insight_ytd(df, now):
    a, b = _ytd(df, now)
    if b < 50:
        return None
    ch = (a - b) / b
    word = ("כמעט ללא שינוי" if abs(ch) < 0.03
            else f"{'עלייה' if ch > 0 else 'ירידה'} של {_pct(abs(ch))}")
    return (f"מתחילת {now.year} ועד {now.day}/{now.month} נרשמו {_int(a)} שותפויות, לעומת {_int(b)} "
            f"באותה תקופה אשתקד — {word}.")


def insight_month(df, now):
    """Current month-to-date vs the same days of each of the previous 12 months."""
    cur = df[(df["founded"].dt.year == now.year) & (df["founded"].dt.month == now.month)]
    base = []
    p = now.to_period("M")
    for k in range(1, 13):
        q = p - k
        m = df[(df["founded"].dt.to_period("M") == q) & (df["founded"].dt.day <= now.day)]
        base.append(len(m))
    avg = sum(base) / len(base)
    if avg < 10 or now.day < 7:
        return None
    ratio = len(cur) / avg
    if SURGE_DOWN < ratio < SURGE_UP:
        return None
    if ratio >= SURGE_UP:
        lead = _vc(cur["tgroup"])
        share = lead.iloc[0] / len(cur)
        who = "רובן מסוג" if share > 0.5 else "הסוג הנפוץ:"
        return (f"ב-{now.day} הימים הראשונים של {now.month}/{now.year} נרשמו {_int(len(cur))} שותפויות — "
                f"פי {ratio:.1f} מהממוצע לאותם ימים ב-12 החודשים הקודמים ({avg:.0f}), קצב גבוה במיוחד. "
                f"{who} '{lead.index[0]}' ({_int(lead.iloc[0])}).")
    return (f"ב-{now.day} הימים הראשונים של {now.month}/{now.year} נרשמו {_int(len(cur))} שותפויות בלבד — "
            f"{_pct(ratio)} מהממוצע לאותם ימים ב-12 החודשים הקודמים ({avg:.0f}).")


def insight_mix(df, now):
    y = df["founded"].dt.year
    full = now.year - 1
    old = full - MIX_GAP
    isr = df[df["tgroup"].isin([TYPE_GENERAL, TYPE_LIMITED])]
    yi = isr["founded"].dt.year
    a, b = isr[yi == full], isr[yi == old]
    if len(a) < 50 or len(b) < 50:
        return None
    sa = (a["tgroup"] == TYPE_LIMITED).mean()
    sb = (b["tgroup"] == TYPE_LIMITED).mean()
    if abs(sa - sb) < 0.05:
        verb = "נשאר יציב"
    else:
        verb = "עלה" if sa > sb else "ירד"
    return (f"חלקן של השותפויות המוגבלות בין השותפויות הישראליות החדשות {verb}: {_pct(sa)} ב-{full}, "
            f"לעומת {_pct(sb)} ב-{old}.")


def insight_survival(df, now):
    end = now.year - 1 - SURVIVAL_YEARS
    start = end - SURVIVAL_WINDOW + 1
    y = df["founded"].dt.year
    c = df[(y >= start) & (y <= end)]
    g, l = c[c["tgroup"] == TYPE_GENERAL], c[c["tgroup"] == TYPE_LIMITED]
    if len(g) < 100 or len(l) < 100:
        return None
    ag, al = (g["group"] == "פעילה").mean(), (l["group"] == "פעילה").mean()
    if abs(ag - al) < 0.05:
        return (f"מבין השותפויות שנרשמו ב-{start}–{end}, שיעור הפעילות היום דומה בשותפויות "
                f"כלליות ({_pct(ag)}) ובמוגבלות ({_pct(al)}).")
    hi, lo = ("המוגבלות", "הכלליות") if al > ag else ("הכלליות", "המוגבלות")
    return (f"מבין השותפויות שנרשמו ב-{start}–{end}, {_pct(max(al, ag))} מהשותפויות {hi} עדיין פעילות, "
            f"לעומת {_pct(min(al, ag))} מהשותפויות {lo}.")


def insight_town(df):
    act = df[(df["group"] == "פעילה") & (df["town"] != "")]
    if len(act) < 100:
        return None
    vc = _vc(act["town"])
    top = vc.index[0]
    tops = list(vc.head(10).index)
    lim = {t: (act.loc[act["town"] == t, "tgroup"] == TYPE_LIMITED).mean() for t in tops}
    best = sorted(tops, key=lambda t: (-lim[t], t))[0]
    return (f"{top} היא הכתובת הרשומה של {_pct(vc.iloc[0] / len(act))} מהשותפויות הפעילות שיש להן יישוב "
            f"({_int(vc.iloc[0])}). מבין עשרת היישובים המובילים, ב{best} שיעור השותפויות המוגבלות "
            f"הגבוה ביותר — {_pct(lim[best])}.")


def insight_sector(df):
    act = df[df["group"] == "פעילה"]
    cls = act[act["sector"] != UNCLASSIFIED]
    if len(cls) < 100:
        return None
    vc = _vc(cls["sector"])
    lead = vc.index[0]
    lim = (cls.loc[cls["sector"] == lead, "tgroup"] == TYPE_LIMITED).mean()
    second = f"; אחריו {vc.index[1]} ({_int(vc.iloc[1])})" if len(vc) > 1 else ""
    return (f"לפי מילות מפתח בשם, התחום הנפוץ בין השותפויות הפעילות הוא {lead} — {_int(vc.iloc[0])} "
            f"שותפויות, {_pct(lim)} מהן מוגבלות{second}. ל-{_pct(1 - len(cls) / len(act))} מהשותפויות "
            f"הפעילות השם אינו מעיד על התחום.")


def insight_foreign(df):
    f = df[df["tgroup"] == FOREIGN]
    if len(f) < 10:
        return None
    fa = int((f["group"] == "פעילה").sum())
    abroad = df[(df["country"] != "") & (df["country"] != "ישראל")]
    tail = ""
    if len(abroad) >= 5:
        vc = _vc(abroad["country"])
        tail = (f" ל-{_int(len(abroad))} שותפויות רשומה כתובת מחוץ לישראל, בעיקר ב{vc.index[0]} "
                f"({_int(vc.iloc[0])}).")
    return (f"במאגר {_int(len(f))} שותפויות זרות (שנרשמו בחו\"ל), מהן {_int(fa)} פעילות.{tail}")


# ── charts ─────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames.pop("main"))
    df = df[df["founded"].notna()].copy()
    now = df["founded"].max()
    y = df["founded"].dt.year
    full = now.year - 1
    act = df[df["group"] == "פעילה"]

    tgroups = [t for t in [TYPE_GENERAL, TYPE_LIMITED] if (df["tgroup"] == t).any()]
    tgroups += sorted(t for t in df["tgroup"].unique() if t not in (TYPE_GENERAL, TYPE_LIMITED, FOREIGN))
    if (df["tgroup"] == FOREIGN).any():
        tgroups.append(FOREIGN)

    # registrations per year by type, full history
    first = int(y.min())
    years = list(range(first, now.year + 1))
    by = df.groupby([y, "tgroup"]).size()
    yearly = {"x": [str(v) for v in years],
              "series": [{"name": t, "data": [int(by.get((v, t), 0)) for v in years]} for t in tgroups],
              "zoom_start": round(max(0, (COHORT_FROM - first) / max(1, now.year - first)) * 100, 1)}

    # last 24 months by type
    months = pd.period_range(end=now.to_period("M"), periods=MONTHS, freq="M")
    pm = df.groupby([df["founded"].dt.to_period("M"), "tgroup"]).size()
    monthly = {"x": [f"{p.month}/{p.year}" for p in months],
               "series": [{"name": t, "data": [int(pm.get((p, t), 0)) for p in months]} for t in tgroups]}

    # year × month heatmap
    hy = list(range(now.year - HEAT_YEARS + 1, now.year + 1))
    hm = df.groupby([y, df["founded"].dt.month]).size()
    cells = []
    for yi, yy in enumerate(hy):
        for mi in range(12):
            if yy == now.year and mi + 1 > now.month:
                continue
            cells.append([mi, yi, int(hm.get((yy, mi + 1), 0))])
    heat = {"years": [str(v) for v in hy], "months": [str(m) for m in range(1, 13)],
            "cells": cells, "max": max([c[2] for c in cells] + [1])}

    # survival by cohort year, general vs limited
    cyears = list(range(COHORT_FROM, now.year))
    surv_series = []
    for t in [TYPE_GENERAL, TYPE_LIMITED]:
        sub = df[df["tgroup"] == t]
        g = sub.groupby(sub["founded"].dt.year)["group"]
        size, rate = g.size(), g.apply(lambda s: (s == "פעילה").mean())
        surv_series.append({"name": t, "data": [round(float(rate[v]) * 100, 1)
                                                 if size.get(v, 0) >= MIN_COHORT else None
                                                 for v in cyears]})
    survival = {"x": [str(v) for v in cyears], "series": surv_series}

    # status
    status = _top(_vc(df["status"]), TOP_STATUS)

    # type × status group (counts; chart shows shares)
    types = [k for k, _ in _vc(df["type"]).items()]
    groups = [g for g in GROUPS if (df["group"] == g).any()]
    ct = df.groupby(["type", "group"]).size()
    tstat = {"types": types, "groups": groups,
             "counts": [[int(ct.get((t, g), 0)) for g in groups] for t in types],
             "totals": [int((df["type"] == t).sum()) for t in types]}
    tstat["shares"] = [[round(c * 100 / tot, 1) if tot else 0 for c in row]
                       for row, tot in zip(tstat["counts"], tstat["totals"])]

    # towns (active) by type
    at = act[act["town"] != ""]
    tv = _vc(at["town"])
    towns_l = list(tv.head(TOP_TOWNS).index)
    tt = at.groupby(["town", "tgroup"]).size()
    towns = {"names": towns_l,
             "series": [{"name": t, "data": [int(tt.get((n, t), 0)) for n in towns_l]} for t in tgroups],
             "rows": [{"name": n, "total": int(tv[n]),
                       "limited": round(float((at.loc[at["town"] == n, "tgroup"] == TYPE_LIMITED).mean()), 4)}
                      for n in towns_l]}

    # sectors (active) by type
    sc = _vc(act.loc[act["sector"] != UNCLASSIFIED, "sector"])
    sectors = list(sc.index)
    sv = act.groupby(["sector", "tgroup"]).size()
    sector = {"names": sectors,
              "series": [{"name": t, "data": [int(sv.get((s, t), 0)) for s in sectors]} for t in tgroups],
              "rows": [{"name": s, "total": int((act["sector"] == s).sum()),
                        "limited": round(float((act.loc[act["sector"] == s, "tgroup"] == TYPE_LIMITED).mean()), 4)}
                       for s in sectors]}

    rules = [
        ("active", insight_active(df)),
        ("registrations", insight_registrations(df, now)),
        ("ytd", insight_ytd(df, now)),
        ("month", insight_month(df, now)),
        ("mix", insight_mix(df, now)),
        ("survival", insight_survival(df, now)),
        ("town", insight_town(df)),
        ("sector", insight_sector(df)),
        ("foreign", insight_foreign(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    n_full = int((y == full).sum())
    n_prev = int((y == full - 1).sum())
    ytd_a, ytd_b = _ytd(df, now)
    lim_act = int((act["tgroup"] == TYPE_LIMITED).sum())
    now_he = f"{now.day}/{now.month}/{now.year}"
    no_town = int((act["town"] == "").sum())
    unclassified = int((act["sector"] == UNCLASSIFIED).sum())

    def bar(items):
        return {"names": [k for k, _ in items], "values": [v for _, v in items]}

    return {
        "agent_data": {
            "summary_he": (f"איתור שותפות ברשם השותפויות לפי שם, מספר שותפות או יישוב: {_int(len(df))} שותפויות "
                           f"שנרשמו מאז {first}, מהן {_int(len(act))} פעילות, עם סטטוס ותאריך רישום. "
                           f"מעודכן עד {now_he}."),
            "dataset_kind": "registry",
            "related_ids": [
                "246d949c-a253-4811-8a11-41a137d3d613",
                "6397d78e-f00f-4657-a03a-3868f845d3c0",
                "01aeaf5c-59a2-4ddc-a616-31b85621bfe2",
                "3111ae54-790a-4d02-9750-d51e1134b405",
                "713440a1-9963-4548-a7d9-9d9c9da54f62",
            ],
            "suggested_tags": ["שותפויות", "רשם החברות", "תאגידים", "עסקים", "קרנות השקעה"],
            "temporal_coverage": f"{first}/{now.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": len(df), "display": _int(len(df)), "tone": "brand"},
            "active": {"value": len(act), "display": _int(len(act)), "tone": "brand"},
            "last_year": {"value": n_full, "display": _int(n_full), "tone": _growth_tone(n_full, n_prev)},
            "ytd": {"value": ytd_a, "display": _int(ytd_a), "tone": _growth_tone(ytd_a, ytd_b)},
            "limited": {"value": lim_act, "display": _int(lim_act), "tone": "info"},
        },
        "charts": {
            "yearly": yearly,
            "monthly": monthly,
            "heat": heat,
            "survival": survival,
            "status": bar(status),
            "tstat": tstat,
            "towns": towns,
            "sector": sector,
        },
        "insights": insights,
        "labels": {
            "lede": (f"{_int(len(df))} שותפויות נרשמו ברשם השותפויות מאז {first}; {_int(len(act))} מהן "
                     f"פעילות היום — {_int(lim_act)} שותפויות מוגבלות (בהן קרנות השקעה ומיזמי נדל\"ן "
                     f"ואנרגיה) והשאר בעיקר שותפויות כלליות של בעלי מקצוע ועסקים. הרישום האחרון במאגר: {now_he}."),
            "full_year": str(full),
            "this_year": str(now.year),
            "ytd_kpi": f"נרשמו מתחילת {now.year} (עד {now.day}/{now.month})",
            "yearly_aria": f"גרף עמודות מוערמות: שותפויות חדשות בכל שנה לפי סוג, {first}–{now.year}.",
            "yearly_note": (f"מספר השותפויות שנרשמו בכל שנה, לפי סוג. השנה האחרונה חלקית — עד {now_he}. "
                            f"גררו את פס הזמן לצפייה בכל התקופה."),
            "monthly_aria": f"גרף עמודות מוערמות: שותפויות חדשות בכל חודש, {MONTHS} החודשים האחרונים.",
            "monthly_note": f"החודש האחרון חלקי — עד {now_he}.",
            "heat_aria": f"מפת חום: שותפויות חדשות לפי חודש ושנה, {hy[0]}–{now.year}.",
            "heat_note": f"כל תא הוא מספר הרישומים בחודש; {HEAT_YEARS} השנים האחרונות. השנה האחרונה עד {now_he}.",
            "survival_aria": "גרף קו: שיעור השותפויות שעדיין פעילות, לפי שנת הרישום — כלליות מול מוגבלות.",
            "survival_note": (f"שיעור השותפויות מכל שנתון רישום שפעילות היום (שנתונים עם {MIN_COHORT} "
                              f"שותפויות לפחות מכל סוג). שנתונים צעירים טבעי שיהיו גבוהים יותר."),
            "status_aria": f"תרשים עמודות: {_int(len(df))} השותפויות לפי סטטוס ברשם.",
            "tstat_aria": "תרשים עמודות מוערמות: התפלגות הסטטוס בכל סוג שותפות, באחוזים.",
            "towns_aria": f"תרשים עמודות מוערמות: {TOP_TOWNS} היישובים עם מספר השותפויות הפעילות הגבוה ביותר, לפי סוג.",
            "towns_note": f"שותפויות פעילות לפי הכתובת הרשומה; ל-{_int(no_town)} שותפויות פעילות אין יישוב רשום.",
            "sector_aria": "תרשים עמודות מוערמות: שותפויות פעילות לפי תחום משוער מהשם, לפי סוג.",
            "sector_note": (f"סיווג לפי מילות מפתח בשם השותפות (בעברית או באנגלית) — הערכה בלבד. "
                            f"{_int(unclassified)} שותפויות פעילות ששמן אינו מעיד על התחום אינן מוצגות."),
        },
    }
