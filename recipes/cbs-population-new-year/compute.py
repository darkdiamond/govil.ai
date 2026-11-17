"""אוכלוסיית ישראל בפתחה של השנה החדשה: CBS's yearly new-year release.

The release's Excel files are the data behind its two charts; the headline
numbers (total population, births, deaths) are only in its text:
  t1   monthly mortality rate (deaths per 1,000 residents in the month), one
       column per period: the 2017-2019 average, the 2020-2022 average and
       each year since 2023. The newest edition carries every period, so
       only it is read.
  t2   monthly international migration balance, one column per year (the
       release's year and the one before it). Editions are stacked
       (history_releases 3) so the page shows every year the window holds;
       for a month two editions both carry, the newest edition wins.
  releases  the edition list: CBS's one-line headline (which states the
       total population) and links.

Header rows are found by their period labels and raise when missing; month
rows are found by month name, and a month whose label cell holds something
else (the 2025 edition prints a footnote over "ינואר") is placed by its
neighbours.
"""
import re

import pandas as pd
from govlib import cbs, fmt

MONTHS = {m: i for i, m in enumerate(fmt.MONTHS_HE, 1)} | {"מרס": 3}
PERIOD = re.compile(r"^((?:19|20)\d\d)(?:-((?:19|20)\d\d))?$")
POP = re.compile(r"נאמדת\s+ב(?:כ)?-?\s*([\d.,]+)\s*מיליון")
SHORT = fmt.MONTHS_SHORT_HE


# ── tables ───────────────────────────────────────────────────────────────


def _period_key(label):
    m = PERIOD.match(label)
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    return (min(a, b), max(a, b))


def _monthly(rows, name):
    """{period label: [12 values or None]} from a month × period grid.

    The header is the first row with two or more period labels (2024,
    2017-2019); it raises when there is none. Data rows follow it."""
    head = None
    for i, r in enumerate(rows):
        if sum(1 for c in r if PERIOD.match(c)) >= 2 and cbs.cell(r, 0) not in MONTHS:
            head = i
            break
    if head is None:
        raise ValueError(f"{name}: period header row not found")
    cols = {j: c for j, c in enumerate(rows[head]) if PERIOD.match(c)}
    body = rows[head + 1:]
    mcol = cbs.best_col(body, lambda v: v in MONTHS, exclude=set(cols))
    if mcol is None:
        raise ValueError(f"{name}: month label column not found")
    recs = []
    for r in body:
        if not any(cbs.val(r, j) is not None for j in cols):
            continue
        recs.append([MONTHS.get(cbs.cell(r, mcol)), r])
        if len(recs) >= 12:
            break
    # A data row whose label isn't a month sits between months: place it.
    for k, rec in enumerate(recs):
        if rec[0] is None:
            if k + 1 < len(recs) and recs[k + 1][0]:
                rec[0] = recs[k + 1][0] - 1
            elif k > 0 and recs[k - 1][0]:
                rec[0] = recs[k - 1][0] + 1
    out = {c: [None] * 12 for c in cols.values()}
    seen = set()
    for m, r in recs:
        if not m or not 1 <= m <= 12 or m in seen:
            continue
        seen.add(m)
        for j, c in cols.items():
            out[c][m - 1] = cbs.val(r, j)
    return dict(sorted(out.items(), key=lambda kv: _period_key(kv[0])))


def _rel_key(no):
    """"345/2026" → (2026, 345): CBS numbers releases within a year."""
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d{4})\s*", str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _editions(df):
    """The table's editions, oldest first, each as a frame of its own."""
    df = df[df["RELEASE_DATE"].astype(str).str.strip() != ""]
    keys = sorted({(d, n) for d, n in zip(df["RELEASE_DATE"], df["RELEASE_NO"], strict=True)},
                  key=lambda k: (k[0], _rel_key(k[1]), k[1]))
    return [df[(df["RELEASE_DATE"] == d) & (df["RELEASE_NO"] == n)] for d, n in keys]


def _migration(df):
    """{year: [12 values or None]}; the newest edition wins per month."""
    years = {}
    for ed in _editions(df):
        for label, vals in _monthly(cbs.grid(ed, "t2"), "t2").items():
            a, b = _period_key(label)
            if a != b:
                continue
            cur = years.setdefault(a, [None] * 12)
            for k, v in enumerate(vals):
                if v is not None:
                    cur[k] = v
    if not years:
        raise ValueError("t2: no yearly migration columns")
    return dict(sorted(years.items()))


# ── formatting ───────────────────────────────────────────────────────────


def _plabel(label):
    a, b = _period_key(label)
    return str(a) if a == b else f"ממוצע {a}-{b}"


def _signed(v):
    s = fmt.int_he(abs(v))
    return s if round(v) >= 0 else fmt.MINUS + s


def _rate(v):
    return f"{v:.3f}"


def _months_span(vals):
    have = [k for k, v in enumerate(vals) if v is not None]
    return have


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _subject(df, word, name):
    """Raise unless a cell of the table names its subject: CBS renumbers a
    release's charts between editions, and a swapped table would otherwise
    be plotted under the wrong heading."""
    cols = [c for c in df.columns if c.startswith("C")]
    if not df[cols].apply(lambda col: col.astype(str).str.contains(word, regex=False)).any().any():
        raise ValueError(f"{name}: no cell mentions {word!r}; the table's subject changed")


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames: dict[str, pd.DataFrame]) -> dict:
    _subject(frames["t1"], "תמותה", "t1")
    _subject(frames["t2"], "הגירה", "t2")
    mort = _monthly(cbs.grid(frames["t1"], "t1"), "t1")
    mig = _migration(frames["t2"])
    rel = cbs.latest_release(frames["releases"])

    kpis, insights, labels, charts, tables = {}, [], {}, {}, {}

    def add(i, text):
        if text:
            insights.append({"id": i, "text_he": text})

    # ── mortality ────────────────────────────────────────────────────────
    periods = list(mort)
    singles = [p for p in periods if _period_key(p)[0] == _period_key(p)[1]
               and any(v is not None for v in mort[p])]
    if not singles:
        raise ValueError("t1: no single-year mortality column with data")
    latest_p = singles[-1]
    latest_y = _period_key(latest_p)[0]
    base_p = periods[0]
    lvals = mort[latest_p]
    have = _months_span(lvals)
    full_latest = len(have) == 12
    # Common months: those every period with data carries (the latest year
    # is usually missing December at release time).
    live = [p for p in periods if any(v is not None for v in mort[p])]
    common = [k for k in range(12) if all(mort[p][k] is not None for p in live)]
    avg = {p: _mean([mort[p][k] for k in common]) for p in live} if common else {}
    common_note = ("" if len(common) == 12 else
                   f" (החודשים {fmt.MONTHS_HE[common[0]]} עד {fmt.MONTHS_HE[common[-1]]}, שיש בכל התקופות)"
                   if common == list(range(common[0], common[-1] + 1)) and common else
                   f" ({len(common)} החודשים שיש בכל התקופות)")

    charts["mort"] = {
        "x": SHORT[:],
        "series": [{"name": _plabel(p),
                    "data": [None if v is None else round(v, 4) for v in mort[p]]}
                   for p in live],
    }
    tables["mort"] = [[fmt.MONTHS_HE[k]] + ["–" if mort[p][k] is None else _rate(mort[p][k])
                                            for p in live] for k in range(12)]
    labels["mort_cols"] = ["חודש"] + [_plabel(p) for p in live]

    # Deviation from the baseline period, month by month.
    dev_ps = [p for p in singles if p != base_p][-3:]
    base = mort[base_p]
    charts["dev"] = {
        "x": SHORT[:],
        "series": [{"name": str(_period_key(p)[0]),
                    "data": [None if (mort[p][k] is None or not base[k]) else
                             round((mort[p][k] / base[k] - 1) * 100, 1) for k in range(12)]}
                   for p in dev_ps],
    }
    tables["dev"] = [[fmt.MONTHS_HE[k]] + [
        "–" if v is None else fmt.signed_pct(v / 100) for v in
        [s["data"][k] for s in charts["dev"]["series"]]] for k in range(12)]
    labels["dev_cols"] = ["חודש"] + [s["name"] for s in charts["dev"]["series"]]

    if avg:
        charts["avg"] = {"x": [_plabel(p) for p in live],
                         "y": [round(avg[p], 4) for p in live]}
        tables["avg"] = [[_plabel(p), _rate(avg[p]),
                          "–" if p == base_p else fmt.signed_pct(avg[p] / avg[base_p] - 1)]
                         for p in live]

    # KPI + insights: the latest year against the baseline.
    lvl = None
    if avg and latest_p in avg and avg[base_p]:
        lvl = avg[latest_p] / avg[base_p] - 1
        tone = "danger" if lvl >= 0.05 else "warn" if lvl >= 0.02 else "ok" if lvl <= -0.02 else "brand"
        kpis["mort"] = {"value": round(lvl * 100, 1), "display": fmt.signed_pct(lvl), "tone": tone}
        labels["mort_kpi"] = f"שיעור התמותה ב-{latest_y} לעומת {_plabel(base_p)}"
        pre = " שלפני הקורונה" if _period_key(base_p)[1] < 2020 else ""
        if abs(lvl) < 0.02:
            add("mort_level", f"שיעור התמותה החודשי ב-{latest_y} דומה לממוצע של השנים "
                              f"{_plabel(base_p).replace('ממוצע ', '')}{pre}: "
                              f"{_rate(avg[latest_p])} לעומת {_rate(avg[base_p])} פטירות לאלף "
                              f"תושבים בחודש בממוצע{common_note}.")
        else:
            add("mort_level", f"שיעור התמותה החודשי ב-{latest_y} "
                              f"{'גבוה' if lvl > 0 else 'נמוך'} ב-{fmt.pct(abs(lvl))} מהממוצע של "
                              f"השנים {_plabel(base_p).replace('ממוצע ', '')}: "
                              f"{_rate(avg[latest_p])} לעומת {_rate(avg[base_p])} פטירות לאלף "
                              f"תושבים בחודש בממוצע{common_note}.")
    for p in live:
        a, b = _period_key(p)
        if p == base_p or a == b or p not in avg or not avg[base_p]:
            continue
        c = avg[p] / avg[base_p] - 1
        if abs(c) >= 0.02:
            add("mort_range", f"בשנים {a}-{b} היה שיעור התמותה הממוצע "
                              f"{'גבוה' if c > 0 else 'נמוך'} ב-{fmt.pct(abs(c))} מזה של "
                              f"{_plabel(base_p).replace('ממוצע ', '')}.")
            break
    # Seasonality of the latest full-enough year.
    if len(have) >= 6:
        hi = max(have, key=lambda k: (lvals[k], -k))
        lo = min(have, key=lambda k: (lvals[k], k))
        if lvals[lo] and lvals[hi] / lvals[lo] - 1 >= 0.1:
            shown = "" if full_latest else " (מבין החודשים שפורסמו)"
            add("mort_season", f"החודש עם שיעור התמותה הגבוה ביותר ב-{latest_y}{shown} הוא "
                               f"{fmt.MONTHS_HE[hi]} ({_rate(lvals[hi])} לאלף), גבוה ב-"
                               f"{fmt.pct(lvals[hi] / lvals[lo] - 1)} מ{fmt.MONTHS_HE[lo]}, "
                               f"החודש הנמוך ביותר ({_rate(lvals[lo])}).")
    # The sharpest single month against the baseline's same month.
    spikes = [(mort[p][k] / base[k] - 1, _period_key(p)[0], k) for p in singles if p != base_p
              for k in range(12) if mort[p][k] is not None and base[k]]
    if spikes:
        r, y, k = max(spikes, key=lambda t: (t[0], t[1], -t[2]))
        if r >= 0.15:
            add("mort_spike", f"החריגה החדה ביותר בנתונים: ב{fmt.MONTHS_HE[k]} {y} היה שיעור "
                              f"התמותה גבוה ב-{fmt.pct(r)} מהממוצע לאותו חודש ב"
                              f"{_plabel(base_p).replace('ממוצע ', 'שנים ')}.")

    # ── migration ────────────────────────────────────────────────────────
    years = list(mig)
    my = years[-1]
    mv = mig[my]
    mhave = _months_span(mv)
    if not mhave:
        raise ValueError("t2: latest year has no months")
    total = sum(mv[k] for k in mhave)
    partial = len(mhave) < 12
    span = (f"{fmt.MONTHS_HE[mhave[0]]} עד {fmt.MONTHS_HE[mhave[-1]]} {my}" if partial
            else str(my))
    kpis["mig"] = {"value": round(total), "display": _signed(total),
                   "tone": "danger" if total < 0 else "ok" if total > 0 else "brand"}
    labels["mig_kpi"] = f"מאזן ההגירה הבין-לאומי, {span}"
    neg = sum(1 for k in mhave if mv[k] < 0)
    kpis["neg"] = {"value": neg, "display": f"{neg:,}",
                   "tone": "warn" if neg * 2 > len(mhave) else "brand"}
    labels["neg_kpi"] = f"חודשים עם מאזן הגירה שלילי ב-{my} (מתוך {len(mhave)})"

    prev = years[-2] if len(years) >= 2 else None
    ptot = None
    if prev is not None:
        pv = [mig[prev][k] for k in mhave]
        if all(v is not None for v in pv):
            ptot = sum(pv)
    word = "שלילי" if total < 0 else "חיובי" if total > 0 else "מאוזן"
    cmp_txt = ""
    if ptot is not None and ptot != 0:
        cmp_txt = (f", לעומת מאזן {'שלילי' if ptot < 0 else 'חיובי'} של "
                   f"{fmt.int_he(abs(ptot))} ב{'אותם חודשים ב-' if partial else '-'}{prev}")
    add("mig_total", f"מאזן ההגירה הבין-לאומי של ישראל ב{'חודשים ' if partial else '-'}{span} "
                     f"היה {word}"
                     + (f": {fmt.int_he(abs(total))} נפש" if total else "")
                     + cmp_txt + ".")
    if len(mhave) >= 6 and neg * 4 >= len(mhave) * 3:
        add("mig_months", (f"בכל {len(mhave)} החודשים בנתוני {my} " if neg == len(mhave) else
                           f"ב-{neg} מתוך {len(mhave)} החודשים בנתוני {my} ")
            + "היה מאזן ההגירה שלילי: יותר אנשים עזבו את ישראל מאשר הגיעו לגור בה.")
    elif len(mhave) >= 6 and neg * 4 <= len(mhave):
        pos = len(mhave) - neg
        add("mig_months", (f"בכל {pos} החודשים בנתוני {my} " if pos == len(mhave) else
                           f"ב-{pos} מתוך {len(mhave)} החודשים בנתוני {my} ")
            + "היה מאזן ההגירה חיובי.")
    cells = [(mig[y][k], y, k) for y in years for k in range(12) if mig[y][k] is not None]
    v, y, k = min(cells, key=lambda t: (t[0], -t[1], t[2]))
    if v < 0:
        ys = [mig[y][j] for j in range(12) if mig[y][j] is not None]
        ysum = sum(ys)
        share = v / ysum if ysum < 0 and len(ys) == 12 else None
        add("mig_extreme", f"החודש עם המאזן השלילי ביותר בנתונים הוא {fmt.MONTHS_HE[k]} {y}: "
                           f"{fmt.int_he(abs(v))} נפש"
                           + (f", {fmt.pct(share)} מהמאזן השלילי של השנה כולה" if share
                              and share >= 0.3 else "") + ".")

    charts["mig"] = {"x": SHORT[:],
                     "series": [{"name": str(y), "data": [None if v is None else round(v)
                                                          for v in mig[y]]} for y in years]}
    tables["mig"] = [[fmt.MONTHS_HE[k]] + ["–" if mig[y][k] is None else _signed(mig[y][k])
                                          for y in years] for k in range(12)]
    labels["mig_cols"] = ["חודש"] + [str(y) for y in years]
    cum = []
    for y in years:
        run, acc = 0, []
        for v in mig[y]:
            if v is None:
                acc.append(None)
                continue
            run += v
            acc.append(round(run))
        cum.append({"name": str(y), "data": acc})
    charts["cum"] = {"x": SHORT[:], "series": cum}
    tables["cum"] = [[str(y), _signed(sum(v for v in mig[y] if v is not None)),
                      f"{sum(1 for v in mig[y] if v is not None):,}",
                      f"{sum(1 for v in mig[y] if v is not None and v < 0):,}"] for y in years]

    # ── population (from CBS's headline) ─────────────────────────────────
    headline = str(rel.get("HEADLINE") or "").strip()
    pop = None
    m = POP.search(headline)
    if m:
        try:
            pop = float(m.group(1).replace(",", ""))
        except ValueError:
            pop = None
    rdate = pd.Timestamp(rel["RELEASE_DATE"])
    if pop:
        digits = len(m.group(1).split(".")[1]) if "." in m.group(1) else 0
        kpis["pop"] = {"value": pop, "display": f"{pop:,.{digits}f}", "tone": "brand"}
        labels["pop_kpi"] = f"תושבי ישראל, במיליונים (אומדן הלמ\"ס, {fmt.d_he(rdate)})"
    kpi_order = [k for k in ("pop", "mig", "neg", "mort") if k in kpis]

    # ── text ─────────────────────────────────────────────────────────────
    pop_txt = f" אוכלוסיית ישראל נאמדת בכ-{kpis['pop']['display']} מיליון תושבים." if pop else ""
    labels.update({
        "lede": ("כמה תושבים יש בישראל בפתח השנה החדשה, כמה עזבו וכמה הגיעו, ואיך השתנה שיעור "
                 "התמותה. הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) "
                 f"לקראת השנה האזרחית החדשה, שפורסמה ב-{fmt.d_he(rdate)}.{pop_txt} "
                 "הלמ\"ס מפרסמת קבצי נתונים לשני מרכיבים: מאזן ההגירה הבין-לאומי ושיעור "
                 "התמותה, לפי חודש. שאר המספרים בהודעה המלאה."),
        "mig_note": (f"מאזן ההגירה הבין-לאומי בכל חודש, {years[0]} עד {my}: כל מי שנכנס לישראל "
                     "כדי לגור בה (עולים, תושבים חוזרים ואחרים) פחות תושבים שיצאו לתקופה "
                     "ממושכת. ערך שלילי: יותר עזבו מאשר הגיעו."),
        "mig_aria": f"מאזן הגירה בין-לאומי לפי חודש, {years[0]} עד {my}",
        "mig_caption": "מאזן הגירה בין-לאומי לפי חודש ושנה (נפש)",
        "cum_note": ("המאזן המצטבר מתחילת כל שנה: הנקודה האחרונה של כל קו היא מאזן השנה "
                     "כולה (או עד החודש האחרון שפורסם)."),
        "cum_aria": f"מאזן הגירה מצטבר מתחילת השנה, {years[0]} עד {my}",
        "cum_caption": "מאזן הגירה שנתי",
        "mort_note": ("שיעור התמותה בכל חודש: פטירות לאלף תושבים באותו חודש. הקווים משווים את "
                      f"{latest_y} לשנים הקודמות ולממוצעים רב-שנתיים."
                      + ("" if full_latest else
                         f" ל-{latest_y} יש נתונים עד {fmt.MONTHS_HE[have[-1]]}.")),
        "mort_aria": f"שיעור תמותה לפי חודש, {_plabel(periods[0])} עד {latest_y}",
        "mort_caption": "שיעור תמותה לפי חודש (פטירות לאלף תושבים)",
        "dev_note": (f"בכמה אחוזים היה שיעור התמותה בכל חודש גבוה או נמוך מהממוצע של אותו "
                     f"חודש ב{_plabel(base_p).replace('ממוצע ', 'שנים ')}."),
        "dev_head": f"שיעור התמותה לעומת {_plabel(base_p)}",
        "dev_aria": f"שינוי בשיעור התמותה לעומת {_plabel(base_p)}, לפי חודש",
        "dev_caption": f"שינוי בשיעור התמותה לעומת {_plabel(base_p)}",
        "avg_note": ("שיעור התמותה החודשי הממוצע בכל תקופה" + common_note
                     + ", כדי להשוות תקופות על אותם חודשים."),
        "avg_aria": "שיעור תמותה חודשי ממוצע לפי תקופה",
        "avg_caption": "שיעור תמותה חודשי ממוצע לפי תקופה",
        "avg_cols": ["תקופה", "פטירות לאלף תושבים בחודש", f"לעומת {_plabel(base_p)}"],
    })

    release = {"title": rel["TITLE"], "headline": headline, "url": rel["PAGE_URL"],
               "pdf": rel["REPORT_PDF_URL"], "date": fmt.d_he(rdate)}
    mig_txt = (f"מאזן ההגירה ב{'חודשים ' if partial else '-'}{span}: {word}"
               + (f", {fmt.int_he(abs(total))} נפש" if total else ""))
    summary = ("אוכלוסיית ישראל בפתחה של השנה החדשה לפי הלמ\"ס"
               + (f": כ-{kpis['pop']['display']} מיליון תושבים" if pop else "")
               + f". {mig_txt}, ושיעור התמותה לפי חודש.")
    desc = ("כמה תושבים יש בישראל"
            + (f": כ-{kpis['pop']['display']} מיליון לפי הלמ\"ס" if pop else " לפי הלמ\"ס")
            + f". {mig_txt}. שיעור התמותה לפי חודש.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{min(_period_key(periods[0])[0], years[0])}/{max(latest_y, my)}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "כמה תושבים יש בישראל? האוכלוסייה בפתח השנה | הלמ\"ס",
                "description": desc,
                "name": "אוכלוסיית ישראל בפתחה של השנה החדשה",
                "alternate_names": ["כמה תושבים יש בישראל", "מספר התושבים בישראל",
                                    "אוכלוסיית ישראל בסוף השנה", "מאזן הגירה בין-לאומי",
                                    "שיעור התמותה בישראל"],
            },
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"avg": bool(avg), "dev": bool(dev_ps)},
    }
