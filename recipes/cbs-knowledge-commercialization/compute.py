"""סקר חברות למסחור ידע בישראל: CBS's (roughly yearly) knowledge-commercialization release.

The release carries four chart-data sheets ("תרשים N - ..."), each a short
yearly series, plus English twins of the same sheets ("Diagram N", read but
not used: the Hebrew sheet is the revised one, e.g. 2020 licences 492 vs 550).
CBS renumbers tables between editions, so every table input (t1..t11, three
spare, all optional) is scanned and each sheet is recognised by its TITLE:

  apps      בקשות מקוריות לרישום פטנטים ... שליד האוניברסיטאות   university companies
  income    הכנסות מקניין רוחני ... שליד האוניברסיטאות          million NIS, university companies
  staff     עובדים מקצועיים ...                                   university companies
  activity  מדדי פעילות חברות מסחור ידע                           all companies: licences,
                                                                  approved patents, new startups

`history_releases` is 3: every edition in the window is parsed and merged by
year, the newest edition winning for a year two editions both print (CBS
revises: 2022 licences went 1,120 → 668). A recognised sheet with no year
header row, or an activity sheet whose rows carry none of its three labels,
raises (the layout moved: a human should look). Data rows may come and go.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*-\s*\S")
HEB = re.compile("[א-ת]")
STEM = re.compile(r"t\d+")
REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
CELL = re.compile(r"C\d+")

ACTIVITY = (("licences", "הסכמי רישיון"), ("granted", "פטנטים מאושרים"), ("startups", "חברות הזנק"))
SERIES_NAMES = {
    "apps": "בקשות לפטנטים (אוניברסיטאות)",
    "staff": "עובדים מקצועיים (אוניברסיטאות)",
    "income": "הכנסות מקניין רוחני (אוניברסיטאות)",
    "licences": "הסכמי רישיון חדשים",
    "granted": "פטנטים מאושרים",
    "startups": "חברות הזנק חדשות",
}
# A year-on-year move smaller than this reads as "stable".
STABLE = 0.02
TONE_MOVE = 0.05


# ── reading the grids ────────────────────────────────────────────────────


def _rel_key(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _editions(df):
    """{(date, (year, no)): [cleaned rows]} for every edition in one grid."""
    if df.empty:
        return {}
    cols = sorted((c for c in df.columns if CELL.fullmatch(c)), key=lambda c: int(c[1:]))
    out = {}
    for (date, no), g in df.groupby(["RELEASE_DATE", "RELEASE_NO"], sort=False):
        if not str(date).strip():
            continue
        g = g.sort_values(["SHEET_NO", "ROW"], kind="stable")
        rows = [[cbs.clean(v) for v in r] for r in g[cols].itertuples(index=False)]
        out[(str(date), _rel_key(no))] = rows
    return out


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c) and HEB.search(c):
                return c
    return ""


def _kind(t):
    if "מדדי פעילות" in t:
        return "activity"
    if "אוניברסיט" not in t:
        return None
    if "בקשות" in t and "פטנט" in t:
        return "apps"
    if "הכנסות מקניין רוחני" in t:
        return "income"
    if "עובדים מקצועיים" in t:
        return "staff"
    return None


def _blocks(rows, kind):
    """[(label, {year: value})] for the labelled data rows under each year
    header row (a row with 3+ bare years). Raises without any header."""
    out = []
    years = None
    seen_header = False
    for r in rows:
        ycols = {j: int(c) for j, c in enumerate(r) if cbs.YEAR.match(c)}
        if len(ycols) >= 3:
            years = ycols
            seen_header = True
            continue
        if years is None:
            continue
        vals = {y: cbs.val(r, j) for j, y in years.items()}
        vals = {y: v for y, v in vals.items() if v is not None}
        if len(vals) < 2:
            continue
        label = next((c for c in r if HEB.search(c)), "")
        out.append((label, vals))
    if not seen_header:
        raise ValueError(f"{kind}: year header row not found")
    return out


def _parse(kind, rows):
    """{series: {year: value}} of one sheet."""
    blocks = _blocks(rows, kind)
    if kind != "activity":
        return {kind: dict(blocks[0][1])} if blocks else {}
    out = {}
    for label, vals in blocks:
        for key, needle in ACTIVITY:
            if needle in label and key not in out:
                out[key] = dict(vals)
    if blocks and not out:
        raise ValueError("activity: none of its row labels found")
    return out


def _series(frames):
    """Every series merged over editions (oldest first, newest wins per
    year), plus the newest edition that printed any of them."""
    per_ed = {}
    names = sorted((n for n in frames if STEM.fullmatch(n)), key=lambda n: int(n[1:]))
    for n in names:
        for ed, rows in _editions(frames[n]).items():
            k = _kind(_title(rows))
            if k is None:
                continue
            got = per_ed.setdefault(ed, {})
            if k in got:
                continue
            got[k] = _parse(k, rows)
    merged = {}
    for ed in sorted(per_ed):
        for parsed in per_ed[ed].values():
            for key, vals in parsed.items():
                merged.setdefault(key, {}).update(vals)
    merged = {k: dict(sorted(v.items())) for k, v in merged.items() if len(v) >= 2}
    return merged


# ── wording helpers ──────────────────────────────────────────────────────


def _n(v):
    return fmt.int_he(v)


def _chg(a, b):
    return None if not a else (b - a) / a


def _tone(s):
    ys = list(s)
    if len(ys) < 2:
        return "brand"
    c = _chg(s[ys[-2]], s[ys[-1]])
    if c is None:
        return "brand"
    return "ok" if c >= TONE_MOVE else ("warn" if c <= -TONE_MOVE else "brand")


def _yoy_phrase(s):
    """'עלייה של 5.8% לעומת 2023' / 'ירידה של ...' / 'כמעט ללא שינוי לעומת 2023'."""
    ys = list(s)
    if len(ys) < 2:
        return None
    a, b = s[ys[-2]], s[ys[-1]]
    c = _chg(a, b)
    if c is None:
        return None
    if abs(c) < STABLE:
        return f"כמעט ללא שינוי לעומת {ys[-2]}"
    word = "עלייה" if c > 0 else "ירידה"
    return f"{word} של {fmt.pct(abs(c))} לעומת {ys[-2]}"


def _peak(s):
    return max(s, key=lambda y: (s[y], -y))


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    series = _series(frames)
    if not series:
        raise ValueError("no recognisable table in any edition")
    rel = cbs.latest_release(frames["releases"])

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(i, text):
        if text:
            insights.append({"id": i, "text_he": text})

    def yr_table(keys, digits=0):
        years = sorted({y for k in keys for y in series[k]})
        rows = []
        for y in years:
            row = [str(y)]
            for k in keys:
                v = series[k].get(y)
                row.append("" if v is None else (_n(v) if digits == 0 else fmt.num_he(v, digits)))
            rows.append(row)
        return years, rows

    last = {k: max(s) for k, s in series.items()}

    # ── patent applications (university companies) ───────────────────────
    flags["apps"] = "apps" in series
    if flags["apps"]:
        s = series["apps"]
        ys = list(s)
        ly = ys[-1]
        charts["apps"] = {"x": [str(y) for y in ys], "y": [round(v) for v in s.values()]}
        tables["apps"] = yr_table(["apps"])[1]
        kpis["apps"] = {"value": s[ly], "display": _n(s[ly]), "tone": _tone(s)}
        labels["apps_kpi"] = f"בקשות מקוריות לפטנטים, חברות שליד האוניברסיטאות ({ly})"
        labels["apps_note"] = (f"בקשות מקוריות לרישום פטנטים בארץ ובחו\"ל שהגישו חברות מסחור הידע "
                               f"שליד האוניברסיטאות, {ys[0]} עד {ly}.")
        labels["apps_aria"] = f"בקשות מקוריות לפטנטים בחברות שליד האוניברסיטאות, {ys[0]} עד {ly}"
        yo = _yoy_phrase(s)
        pk = _peak(s)
        if yo:
            txt = (f"ב-{ly} הגישו החברות שליד האוניברסיטאות {_n(s[ly])} בקשות מקוריות לפטנטים, {yo}")
            if pk != ly and s[ly] < s[pk] * 0.95:
                txt += f". השיא היה ב-{pk}, עם {_n(s[pk])} בקשות"
            add("apps", txt + ".")

    # ── IP income (university companies) ─────────────────────────────────
    flags["income"] = "income" in series
    if flags["income"]:
        s = series["income"]
        ys = list(s)
        ly = ys[-1]
        charts["income"] = {"x": [str(y) for y in ys], "y": [round(v, 1) for v in s.values()]}
        tables["income"] = yr_table(["income"])[1]
        kpis["income"] = {"value": round(s[ly], 1), "display": _n(s[ly]), "tone": _tone(s)}
        labels["income_kpi"] = f"הכנסות מקניין רוחני, מיליוני ש\"ח, חברות שליד האוניברסיטאות ({ly})"
        labels["income_note"] = (f"הכנסות החברות שליד האוניברסיטאות ממכירת קניין רוחני: תמלוגים, "
                                 f"דמי רישיון, מכירת פטנטים ואופציות, במיליוני ש\"ח, {ys[0]} עד {ly}. "
                                 f"לפי הלמ\"ס זו סדרה תנודתית, שעשויה להיות מושפעת ממגמות של חברות בודדות.")
        labels["income_aria"] = f"הכנסות מקניין רוחני בחברות שליד האוניברסיטאות, {ys[0]} עד {ly}"
        pk = _peak(s)
        if pk != ly and s[ly] <= s[pk] * 0.5:
            drop = 1 - s[ly] / s[pk]
            add("income", f"הכנסות החברות שליד האוניברסיטאות מקניין רוחני ירדו מ-{_n(s[pk])} מיליון ש\"ח "
                          f"בשיא של {pk} ל-{_n(s[ly])} מיליון ש\"ח ב-{ly}, ירידה של {fmt.pct(drop, 0)}.")
        else:
            yo = _yoy_phrase(s)
            if yo:
                add("income", f"ב-{ly} הסתכמו הכנסות החברות שליד האוניברסיטאות מקניין רוחני "
                              f"ב-{_n(s[ly])} מיליון ש\"ח, {yo}.")

    # ── professional staff (university companies) ────────────────────────
    flags["staff"] = "staff" in series
    if flags["staff"]:
        s = series["staff"]
        ys = list(s)
        ly = ys[-1]
        charts["staff"] = {"x": [str(y) for y in ys], "y": [round(v) for v in s.values()]}
        tables["staff"] = yr_table(["staff"])[1]
        kpis["staff"] = {"value": s[ly], "display": _n(s[ly]), "tone": _tone(s)}
        labels["staff_kpi"] = f"עובדים מקצועיים, חברות שליד האוניברסיטאות ({ly})"
        labels["staff_note"] = (f"מספר העובדים המקצועיים בחברות מסחור הידע שליד האוניברסיטאות, "
                                f"{ys[0]} עד {ly}.")
        labels["staff_aria"] = f"עובדים מקצועיים בחברות שליד האוניברסיטאות, {ys[0]} עד {ly}"
        c = _chg(s[ys[0]], s[ly])
        if c is not None and abs(c) >= 0.1:
            word = "גדל" if c > 0 else "קטן"
            add("staff", f"מספר העובדים המקצועיים בחברות שליד האוניברסיטאות {word} מ-{_n(s[ys[0]])} "
                         f"ב-{ys[0]} ל-{_n(s[ly])} ב-{ly} ({fmt.signed_pct(c, 0)}).")

    # income per professional employee: same years in both series
    if flags["income"] and flags["staff"]:
        common = sorted(set(series["income"]) & set(series["staff"]))
        if len(common) >= 2:
            a, b = common[0], common[-1]
            pa = series["income"][a] / series["staff"][a] if series["staff"][a] else None
            pb = series["income"][b] / series["staff"][b] if series["staff"][b] else None
            if pa and pb and abs(pb / pa - 1) >= 0.25:
                word = "ירדה" if pb < pa else "עלתה"
                add("per_staff", f"ההכנסה מקניין רוחני לכל עובד מקצועי בחברות שליד האוניברסיטאות {word} "
                                 f"מכ-{fmt.num_he(pa)} מיליון ש\"ח ב-{a} לכ-{fmt.num_he(pb)} מיליון ש\"ח ב-{b}.")

    # ── licences and granted patents (all companies) ─────────────────────
    act = [k for k in ("licences", "granted") if k in series]
    flags["activity"] = bool(act)
    if flags["activity"]:
        years, rows = yr_table(act)
        charts["activity"] = {"x": [str(y) for y in years],
                              "names": [SERIES_NAMES[k] for k in act],
                              "series": [[None if series[k].get(y) is None else round(series[k][y])
                                          for y in years] for k in act]}
        tables["activity"] = rows
        labels["activity_cols"] = ["שנה"] + [SERIES_NAMES[k] for k in act]
        labels["activity_note"] = (f"הסכמי רישיון חדשים עם חברות חיצוניות ופטנטים שאושרו, בכל חברות "
                                   f"מסחור הידע (אוניברסיטאות, בתי חולים ומכוני מחקר), {years[0]} עד {years[-1]}.")
        labels["activity_aria"] = f"הסכמי רישיון ופטנטים מאושרים, {years[0]} עד {years[-1]}"
        for k in act:
            s = series[k]
            ly = list(s)[-1]
            kpis[k] = {"value": s[ly], "display": _n(s[ly]), "tone": _tone(s)}
        if "licences" in series:
            s = series["licences"]
            ly = list(s)[-1]
            labels["licences_kpi"] = f"הסכמי רישיון חדשים, כל החברות ({ly})"
            yo = _yoy_phrase(s)
            pk = _peak(s)
            if yo:
                txt = f"ב-{ly} נחתמו {_n(s[ly])} הסכמי רישיון חדשים עם חברות חיצוניות, {yo}"
                if pk != ly and s[ly] < s[pk] * 0.9:
                    txt += f". השיא: {_n(s[pk])} הסכמים ב-{pk}"
                add("licences", txt + ".")
        if "granted" in series:
            s = series["granted"]
            ly = list(s)[-1]
            labels["granted_kpi"] = f"פטנטים מאושרים, כל החברות ({ly})"
            yo = _yoy_phrase(s)
            if yo:
                add("granted", f"ב-{ly} אושרו לחברות מסחור הידע {_n(s[ly])} פטנטים, {yo}.")

    # ── startups (all companies) ─────────────────────────────────────────
    flags["startups"] = "startups" in series
    if flags["startups"]:
        s = series["startups"]
        ys = list(s)
        ly = ys[-1]
        charts["startups"] = {"x": [str(y) for y in ys], "y": [round(v) for v in s.values()]}
        tables["startups"] = yr_table(["startups"])[1]
        kpis["startups"] = {"value": s[ly], "display": _n(s[ly]), "tone": _tone(s)}
        labels["startups_kpi"] = f"חברות הזנק חדשות, כל החברות ({ly})"
        labels["startups_note"] = (f"חברות הזנק שהוקמו על בסיס טכנולוגיה מהמוסדות, בכל חברות מסחור הידע, "
                                   f"{ys[0]} עד {ly}.")
        labels["startups_aria"] = f"חברות הזנק חדשות, {ys[0]} עד {ly}"
        pk = _peak(s)
        tot = sum(s.values())
        if pk == ly:
            add("startups", f"{ly} הייתה שנת שיא בהקמת חברות הזנק: {_n(s[ly])} חברות חדשות. "
                            f"בסך הכל הוקמו {_n(tot)} חברות הזנק בשנים {ys[0]}-{ly}.")
        else:
            yo = _yoy_phrase(s)
            if yo:
                add("startups", f"ב-{ly} היו חברות מסחור הידע מעורבות בהקמת {_n(s[ly])} חברות הזנק, {yo}. "
                                f"השיא: {_n(s[pk])} ב-{pk}, ובסך הכל {_n(tot)} חברות בשנים {ys[0]}-{ly}.")

    # ── all indicators on one index (first common year = 100) ────────────
    idx_keys = [k for k in ("apps", "staff", "income", "licences", "granted", "startups") if k in series]
    common = sorted(set.intersection(*(set(series[k]) for k in idx_keys))) if idx_keys else []
    flags["index"] = len(idx_keys) >= 3 and len(common) >= 3
    if flags["index"]:
        base = common[0]
        idx = {k: [round(series[k][y] / series[k][base] * 100, 1) for y in common] for k in idx_keys}
        charts["index"] = {"x": [str(y) for y in common], "names": [SERIES_NAMES[k] for k in idx_keys],
                           "series": [idx[k] for k in idx_keys]}
        tables["index"] = [[SERIES_NAMES[k], fmt.num_he(idx[k][-1], 0)] for k in idx_keys]
        labels["index_cols"] = ["מדד", f"{common[-1]} (בסיס: {base} = 100)"]
        labels["index_note"] = (f"כל המדדים על אותו קנה מידה: הערך של {base} שווה 100, וכל שנה מוצגת "
                                f"ביחס אליו, עד {common[-1]}. כך רואים מה צמח ומה נחלש.")
        labels["index_aria"] = f"מדדי מסחור ידע ביחס ל-{base}, עד {common[-1]}"
        ranked = sorted(idx_keys, key=lambda k: (-idx[k][-1], k))
        hi, lo = ranked[0], ranked[-1]
        if idx[hi][-1] - idx[lo][-1] >= 50:
            add("index", f"בין {base} ל-{common[-1]}: {SERIES_NAMES[hi]} הגיעו ל-{fmt.num_he(idx[hi][-1], 0)} "
                         f"נקודות (בסיס 100), ו{SERIES_NAMES[lo]} רק ל-{fmt.num_he(idx[lo][-1], 0)}.")

    if not kpis:
        raise ValueError("no KPI could be computed")

    # ── text ─────────────────────────────────────────────────────────────
    span_lo = min(min(s) for s in series.values())
    span_hi = max(last.values())
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    bits = []
    if "licences" in series:
        bits.append(f"{_n(series['licences'][last['licences']])} הסכמי רישיון חדשים")
    if "startups" in series:
        bits.append(f"{_n(series['startups'][last['startups']])} חברות הזנק חדשות")
    if "apps" in series:
        bits.append(f"{_n(series['apps'][last['apps']])} בקשות לפטנטים מהאוניברסיטאות")
    lede_tail = f" בשנה האחרונה בנתונים: {fmt.join_he(bits)}." if bits else ""
    labels["lede"] = ("איך הופך מחקר אקדמי למוצר: חברות מסחור הידע שליד האוניברסיטאות, בתי החולים "
                      "ומכוני המחקר רושמות פטנטים, חותמות על הסכמי רישיון ומקימות חברות הזנק. "
                      "הנתונים מתוך סקר חברות למסחור ידע של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), "
                      f"{span_lo} עד {span_hi}, ומתעדכנים עם כל הודעה חדשה." + lede_tail)
    summary = ("מסחור ידע בישראל לפי סקר הלמ\"ס: פטנטים, הסכמי רישיון, הכנסות מקניין רוחני וחברות הזנק "
               f"של חברות המסחור שליד האוניברסיטאות ומוסדות המחקר, {span_lo}-{span_hi}." + lede_tail)
    # each count with its own series' latest year (the series end in different years)
    desc_keys = [(k, w) for k, w in (("startups", "חברות הזנק"), ("licences", "הסכמי רישיון"))
                 if k in series]
    desc_years = {last[k] for k, _ in desc_keys}
    if len(desc_years) == 1:
        desc_tail = (f". ב-{desc_years.pop()}: "
                     + fmt.join_he([f"{_n(series[k][last[k]])} {w}" for k, w in desc_keys]) + ".")
    elif desc_keys:
        desc_tail = (": " + fmt.join_he([f"{_n(series[k][last[k]])} {w} ב-{last[k]}"
                                         for k, w in desc_keys]) + ".")
    else:
        desc_tail = "."
    desc = "מסחור ידע מהאוניברסיטאות: פטנטים, הכנסות מתמלוגים וחברות הזנק לפי הלמ\"ס" + desc_tail

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{span_lo}/{span_hi}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מסחור ידע באוניברסיטאות: פטנטים והזנק | הלמ\"ס",
                "description": desc,
                "name": "מסחור ידע באוניברסיטאות ובמוסדות מחקר בישראל",
                "alternate_names": ["סקר חברות למסחור ידע בישראל", "חברות מסחור ידע",
                                    "פטנטים של אוניברסיטאות בישראל", "העברת טכנולוגיה מהאקדמיה"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
