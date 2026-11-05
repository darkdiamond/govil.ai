"""תאונות דרכים עם נפגעים: CBS's monthly road-accidents release.

Inputs:
  t1        table 1 of the newest edition: road accidents with casualties and
            casualties, by severity. Two column blocks (Casualties, Accidents),
            each with original data, seasonally adjusted, trend and two
            "thereof" columns (killed / seriously injured; fatal / serious
            accidents). Rows: whole years (the last full years), then
            months (about three years back to the latest month).
  releases  the recent editions: number, date, title (names the month) and
            CBS's one-line headline (the first-reported counts for that month).

Header rows and columns are found by label (govlib.cbs) and raise when
missing; period rows are found by pattern, so a missing one only shortens a
series. "Latest month" is the newest monthly row with original data.
"""
import re

import pandas as pd
from govlib import cbs, fmt

MONTH_NAMES = {m: i for i, m in enumerate(fmt.MONTHS_HE, 1)} | {"מרס": 3}
MEASURES = ("cas", "killed", "serious_inj", "acc", "fatal", "serious_acc")
# Revisions: a month counts as settled once this many later editions exist.
SETTLED_AFTER = 3


# ── table 1 ──────────────────────────────────────────────────────────────


def _block_col(row, label, lo, hi, name="t1"):
    for j in range(lo, hi):
        if cbs.cell(row, j) == label:
            return j
    raise ValueError(f"{name}: header label {label!r} not found in columns {lo}-{hi}")


def _t1(rows):
    """(years, months): {year: {measure: value}}, {(year, month): {...}} with
    measures cas/killed/serious_inj/acc/fatal/serious_acc (original data) and
    cas_sa/cas_trend/acc_sa/acc_trend."""
    g = cbs.row_with(rows, "Accidents", name="t1")
    cas0 = cbs.col_after(rows[g], "Casualties", 0)
    acc0 = cbs.col_after(rows[g], "Accidents", 0)
    width = max(len(r) for r in rows)
    span = {"cas": (cas0, acc0 if acc0 > cas0 else width),
            "acc": (acc0, cas0 if cas0 > acc0 else width)}
    h = cbs.row_with(rows, "Killed", g, name="t1")
    hr = rows[h]
    lo, hi = span["cas"]
    cols = {"cas": _block_col(hr, "Original", lo, hi),
            "cas_sa": _block_col(hr, "Seasonally", lo, hi),
            "cas_trend": _block_col(hr, "Trend", lo, hi),
            "killed": _block_col(hr, "Killed", lo, hi),
            "serious_inj": _block_col(hr, "Seriously", lo, hi)}
    lo, hi = span["acc"]
    cols.update({"acc": _block_col(hr, "Original", lo, hi),
                 "acc_sa": _block_col(hr, "Seasonally", lo, hi),
                 "acc_trend": _block_col(hr, "Trend", lo, hi),
                 "fatal": _block_col(hr, "Fatal", lo, hi),
                 "serious_acc": _block_col(hr, "Serious", lo, hi)})
    years, months = {}, {}
    for i, y, m, end in cbs.periods(rows, h + 1, len(rows)):
        v = {k: cbs.val(rows[i], j) for k, j in cols.items()}
        if v["cas"] is None:
            continue
        if m is None:
            years[y] = v
        elif end is None:
            months[(y, m)] = v
    return years, months


def _provisional_year(df):
    """The first year CBS marks provisional ("*2026"), or None."""
    if df.empty:
        return None
    latest = df[df["RELEASE_DATE"] == df["RELEASE_DATE"].max()]
    found = []
    for c in (c for c in latest.columns if re.fullmatch(r"C\d+", c)):
        for v in latest[c]:
            m = re.fullmatch(r"\s*\*\s*((?:19|20)\d\d)\s*", str(v))
            if m:
                found.append(int(m.group(1)))
    return min(found) if found else None


# ── releases ─────────────────────────────────────────────────────────────


def _int(s):
    return int(s.replace(",", ""))


def _first_reports(rel):
    """{(year, month): {"cas", "acc", "killed", "fatal", "order"}} parsed from
    each edition's title (the month) and CBS's headline (first-reported
    counts). An edition whose text doesn't parse is left out."""
    out = {}
    for order, r in enumerate(rel.itertuples(index=False)):
        mt = re.search(r"(" + "|".join(MONTH_NAMES) + r")\s+((?:19|20)\d\d)", r.TITLE)
        a = re.search(r"([\d,]+)\s*נפגעים\s*ב-?\s*([\d,]+)\s*תאונות", r.HEADLINE)
        k = re.search(r"([\d,]+)\s*הרוגים\s*ב-?\s*([\d,]+)\s*תאונות", r.HEADLINE)
        if not (mt and a and k):
            continue
        t = (int(mt.group(2)), MONTH_NAMES[mt.group(1)])
        out[t] = {"cas": _int(a.group(1)), "acc": _int(a.group(2)),
                  "killed": _int(k.group(1)), "fatal": _int(k.group(2)), "order": order}
    return out


# ── formatting ───────────────────────────────────────────────────────────


def _n(v):
    return fmt.int_he(v) if v is not None else ""


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _span(m):
    """'ינואר עד ספטמבר' (or just 'ינואר' for one month)."""
    return fmt.MONTHS_HE[0] if m == 1 else f"{fmt.MONTHS_HE[0]} עד {fmt.MONTHS_HE[m - 1]}"


def _median(vals):
    vals = sorted(vals)
    n = len(vals)
    if not n:
        return None
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _per_k(killed, cas):
    return killed / cas * 1000 if killed is not None and cas else None


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    years, months = _t1(cbs.grid(frames["t1"], "t1"))
    if not months:
        raise ValueError("t1: no monthly rows")
    mts = sorted(months)
    lt = mts[-1]
    last = months[lt]
    cy, cm = lt
    prov_year = _provisional_year(frames["t1"])
    full_years = sorted(years)

    # Year to date: Jan..cm of every year whose months are all in the table.
    # A measure with a missing month ("..") is None, not a short sum.
    ytd = {}
    for y in sorted({t[0] for t in mts}):
        if all((y, m) in months for m in range(1, cm + 1)):
            vals = {k: [months[(y, m)][k] for m in range(1, cm + 1)] for k in MEASURES}
            ytd[y] = {k: sum(v) if all(x is not None for x in v) else None
                      for k, v in vals.items()}
    cur = ytd.get(cy)
    if cur and cur["killed"] is None:
        cur = None  # the headline YTD figure needs every month's killed count
    prev = ytd.get(cy - 1)

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    span_txt = _span(cm)
    k_chg = _chg(cur["killed"], prev["killed"]) if cur and prev else None
    if cur:
        tone = "brand" if k_chg is None else "danger" if k_chg > 0.02 else \
            "ok" if k_chg < -0.02 else "warn"
        kpis["ytd_killed"] = {"value": cur["killed"], "display": fmt.int_he(cur["killed"]),
                              "tone": tone}
        labels["ytd_killed_kpi"] = f"הרוגים בתאונות דרכים, {span_txt} {cy}"
    if k_chg is not None:
        kpis["ytd_chg"] = {"value": round(k_chg, 4), "display": fmt.signed_pct(k_chg),
                           "tone": "danger" if k_chg > 0.02 else "ok" if k_chg < -0.02
                           else "warn"}
        labels["ytd_chg_kpi"] = f"שינוי בהרוגים לעומת {span_txt} {cy - 1}"
    if cur and cur["serious_inj"] is not None:
        kpis["ytd_serious"] = {"value": cur["serious_inj"],
                               "display": fmt.int_he(cur["serious_inj"]), "tone": "brand"}
        labels["ytd_serious_kpi"] = f"פצועים קשה, {span_txt} {cy} (ארעי)"
    kpis["month_killed"] = {"value": last["killed"], "display": _n(last["killed"]),
                            "tone": "brand"}
    labels["month_killed_kpi"] = f"הרוגים ב{_mname(lt)}"
    if full_years:
        fy = full_years[-1]
        kpis["year_killed"] = {"value": years[fy]["killed"], "display": _n(years[fy]["killed"]),
                               "tone": "info"}
        labels["year_killed_kpi"] = f"הרוגים בשנת {fy} כולה"

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables = {}, {}
    charts["trend"] = {"x": [_mshort(t) for t in mts],
                       "orig": [months[t]["cas"] for t in mts],
                       "sa": [months[t]["cas_sa"] for t in mts],
                       "trend": [months[t]["cas_trend"] for t in mts]}
    tables["trend"] = [[_mname(t), _n(months[t]["cas"]), _n(months[t]["cas_sa"]),
                        _n(months[t]["cas_trend"])] for t in reversed(mts)]
    charts["accidents"] = {"x": charts["trend"]["x"],
                           "orig": [months[t]["acc"] for t in mts],
                           "sa": [months[t]["acc_sa"] for t in mts],
                           "trend": [months[t]["acc_trend"] for t in mts]}
    tables["accidents"] = [[_mname(t), _n(months[t]["acc"]), _n(months[t]["acc_sa"]),
                            _n(months[t]["acc_trend"]), _n(months[t]["fatal"]),
                            _n(months[t]["serious_acc"])] for t in reversed(mts)]

    # Killed by month, one line per year.
    ys = sorted({t[0] for t in mts})
    charts["season"] = {"x": fmt.MONTHS_SHORT_HE, "years": [str(y) for y in ys],
                        "series": [[months[(y, m)]["killed"] if (y, m) in months else None
                                    for m in range(1, 13)] for y in ys]}
    tables["season"] = [[fmt.MONTHS_HE[m - 1]] + [_n(months[(y, m)]["killed"])
                                                  if (y, m) in months else "" for y in ys]
                        for m in range(1, 13)]
    labels["season_years"] = [str(y) for y in ys]

    ytd_years = sorted(ytd)
    charts["ytd"] = {"x": [str(y) for y in ytd_years],
                     "killed": [ytd[y]["killed"] for y in ytd_years],
                     "serious": [ytd[y]["serious_inj"] for y in ytd_years],
                     "fatal": [ytd[y]["fatal"] for y in ytd_years]}
    tables["ytd"] = [[str(y), _n(ytd[y]["killed"]), _n(ytd[y]["serious_inj"]),
                      _n(ytd[y]["cas"]), _n(ytd[y]["fatal"]), _n(ytd[y]["acc"])]
                     for y in ytd_years]

    if full_years:
        charts["annual"] = {"x": [str(y) for y in full_years],
                            "killed": [years[y]["killed"] for y in full_years],
                            "serious": [years[y]["serious_inj"] for y in full_years],
                            "cas": [years[y]["cas"] for y in full_years]}
        tables["annual"] = [[str(y), _n(years[y]["killed"]), _n(years[y]["serious_inj"]),
                             _n(years[y]["cas"]), _n(years[y]["fatal"]),
                             _n(years[y]["serious_acc"]), _n(years[y]["acc"])]
                            for y in full_years]

    # Severity: killed per 1,000 casualties, share of fatal+serious accidents.
    # Full years only: a part year's casualties are still being reported, so
    # its ratio runs high.
    sev_rows = [(str(y), years[y]) for y in full_years]
    sev = []
    for lab, v in sev_rows:
        pk = _per_k(v["killed"], v["cas"])
        sh = ((v["fatal"] or 0) + (v["serious_acc"] or 0)) / v["acc"] if v["acc"] else None
        if pk is not None and sh is not None:
            sev.append((lab, pk, sh))
    if len(sev) >= 2:
        charts["severity"] = {"x": [s[0] for s in sev],
                              "per_k": [round(s[1], 1) for s in sev],
                              "share": [round(s[2] * 100, 1) for s in sev]}
        tables["severity"] = [[s[0], fmt.num_he(s[1], 1), fmt.pct(s[2])] for s in sev]

    # Revisions: first-reported counts (CBS headline) vs this edition's table.
    first = _first_reports(rel)
    n_rel = len(rel)
    rev = []
    for t in sorted(first):
        if t not in months or months[t]["cas"] is None or months[t]["killed"] is None:
            continue
        f = first[t]
        rev.append({"t": t, "first_cas": f["cas"], "cas": months[t]["cas"],
                    "first_killed": f["killed"], "killed": months[t]["killed"],
                    "later": n_rel - 1 - f["order"]})
    if len(rev) >= 3:
        charts["revision"] = {"x": [_mshort(r["t"]) for r in rev],
                              "first": [r["first_cas"] for r in rev],
                              "now": [r["cas"] for r in rev]}
        tables["revision"] = [[_mname(r["t"]), _n(r["first_cas"]), _n(r["cas"]),
                               fmt.signed_pct(_chg(r["cas"], r["first_cas"]))
                               if r["first_cas"] else "",
                               _n(r["first_killed"]), _n(r["killed"])]
                              for r in reversed(rev)]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if cur and prev and k_chg is not None:
        d = cur["killed"] - prev["killed"]
        if abs(k_chg) < 0.02:
            add("ytd", f"מתחילת {cy} ועד סוף {fmt.MONTHS_HE[cm - 1]} נהרגו בתאונות דרכים "
                       f"{fmt.int_he(cur['killed'])} בני אדם, כמעט כמו באותה תקופה ב-{cy - 1} "
                       f"({fmt.int_he(prev['killed'])}).")
        else:
            add("ytd", f"מתחילת {cy} ועד סוף {fmt.MONTHS_HE[cm - 1]} נהרגו בתאונות דרכים "
                       f"{fmt.int_he(cur['killed'])} בני אדם, {fmt.int_he(abs(d))} "
                       f"{'יותר' if d > 0 else 'פחות'} מאשר באותה תקופה ב-{cy - 1} "
                       f"({fmt.signed_pct(k_chg)}).")
        s_chg = _chg(cur["serious_inj"], prev["serious_inj"])
        if s_chg is not None and abs(s_chg) >= 0.03:
            add("ytd_serious", f"מספר הפצועים קשה באותה תקופה: {fmt.int_he(cur['serious_inj'])}, "
                               f"{'עלייה' if s_chg > 0 else 'ירידה'} של {fmt.pct(abs(s_chg))} "
                               f"לעומת {cy - 1} (נתוני החודשים האחרונים עוד יעודכנו).")

    if len(full_years) >= 2:
        y0, y1 = full_years[0], full_years[-1]
        a, b = years[y0], years[y1]
        cc, kc = _chg(b["cas"], a["cas"]), _chg(b["killed"], a["killed"])
        pa, pb = _per_k(a["killed"], a["cas"]), _per_k(b["killed"], b["cas"])
        if cc is not None and kc is not None and pa and pb and abs(pb / pa - 1) >= 0.1:
            if cc < 0 < kc:
                lead = (f"מספר הנפגעים ירד מ-{fmt.int_he(a['cas'])} ב-{y0} ל-"
                        f"{fmt.int_he(b['cas'])} ב-{y1} ({fmt.signed_pct(cc)}), אבל מספר "
                        f"ההרוגים עלה מ-{fmt.int_he(a['killed'])} ל-{fmt.int_he(b['killed'])} "
                        f"({fmt.signed_pct(kc)}). ")
            else:
                lead = ""
            add("severity", f"{lead}התאונות נעשו {'קטלניות יותר' if pb > pa else 'קטלניות פחות'}: "
                            f"ב-{y1} היו {fmt.num_he(pb, 1)} הרוגים לכל 1,000 נפגעים, לעומת "
                            f"{fmt.num_he(pa, 1)} ב-{y0}.")
        prevy = full_years[-2]
        c = _chg(years[y1]["killed"], years[prevy]["killed"])
        top = max(full_years, key=lambda y: (years[y]["killed"], y))
        if c is not None:
            rec = (f", המספר הגבוה ביותר בשנים {full_years[0]}-{y1}"
                   if top == y1 and len(full_years) >= 3 else "")
            add("annual", f"בשנת {y1} כולה נהרגו בתאונות דרכים {fmt.int_he(years[y1]['killed'])} "
                          f"בני אדם, {'עלייה' if c > 0 else 'ירידה'} של {fmt.pct(abs(c))} לעומת "
                          f"{prevy}{rec}." if abs(c) >= 0.01 else None)

    killed_m = [(months[t]["killed"], t) for t in mts if months[t]["killed"] is not None]
    if len(killed_m) >= 12:
        top_v, top_t = max(killed_m, key=lambda kt: (kt[0], kt[1]))
        avg = sum(v for v, _ in killed_m) / len(killed_m)
        if top_v >= avg * 1.25:
            add("peak", f"החודש הקטלני ביותר מאז {_mname(mts[0])} היה {_mname(top_t)}, עם "
                        f"{fmt.int_he(top_v)} הרוגים, לעומת ממוצע של {fmt.num_he(avg, 1)} "
                        f"הרוגים בחודש.")

    # The trend's last months move with late reports: compare a settled month.
    tr = [t for t in mts if months[t]["cas_trend"] is not None]
    if len(tr) > SETTLED_AFTER:
        tl = tr[-1 - SETTLED_AFTER]
        base = (tl[0] - 1, tl[1])
        if base in months and months[base]["cas_trend"]:
            c = _chg(months[tl]["cas_trend"], months[base]["cas_trend"])
            if abs(c) >= 0.03:
                add("trend", f"לפי קו המגמה של הלמ\"ס, מספר הנפגעים בחודש {'עולה' if c > 0 else 'יורד'}: "
                             f"{fmt.int_he(months[tl]['cas_trend'])} ב{_mname(tl)} לעומת "
                             f"{fmt.int_he(months[base]['cas_trend'])} שנה קודם "
                             f"({fmt.signed_pct(c)}).")

    settled = [r for r in rev if r["later"] >= SETTLED_AFTER and r["first_cas"]]
    if len(settled) >= 3:
        rc = _median([r["cas"] / r["first_cas"] - 1 for r in settled])
        rk = _median([abs(r["killed"] - r["first_killed"]) for r in settled])
        if rc is not None and rc >= 0.05:
            kt = ("לא השתנה כמעט" if rk <= 2 else
                  f"השתנה בחציון ב-{fmt.int_he(rk)}")
            add("revision", f"הנתון הראשון שמתפרסם לכל חודש נמוך מהסופי: בחודשים שכבר עודכנו "
                            f"לפחות {SETTLED_AFTER} פעמים, מספר הנפגעים גדל בחציון ב-"
                            f"{fmt.pct(rc)} מאז הפרסום הראשון, ואילו מספר ההרוגים {kt}. "
                            f"לכן הנפגעים בחודשים האחרונים בגרף צפויים לעלות בהודעות הבאות.")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"כמה תאונות דרכים עם נפגעים היו בישראל בכל חודש, כמה בני אדם נהרגו "
                 f"ונפצעו קשה, ואיך זה משתנה משנה לשנה. הנתונים מתוך ההודעה החודשית של "
                 f"הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), כולל תאונות באזור יהודה והשומרון, "
                 f"ומתעדכנים עם כל הודעה חדשה. הנתון האחרון הוא ל{_mname(lt)}: "
                 f"{_n(last['killed'])} הרוגים ו-{_n(last['cas'])} נפגעים ב-{_n(last['acc'])} "
                 f"תאונות."),
        "trend_note": (f"מספר הנפגעים (הרוגים, פצועים קשה ופצועים קל) בכל חודש מאז "
                       f"{_mname(mts[0])}: הנתון המקורי, המנוכה עונתיות וקו המגמה. נתוני "
                       f"החודשים האחרונים חלקיים ועוד יעודכנו כלפי מעלה."),
        "trend_aria": f"נפגעים בתאונות דרכים לפי חודש, {_mname(mts[0])} עד {_mname(lt)}",
        "trend_caption": "נפגעים בתאונות דרכים לפי חודש",
        "acc_note": (f"מספר התאונות עם נפגעים בכל חודש מאז {_mname(mts[0])}. בטבלה גם מספר "
                     f"התאונות הקטלניות והקשות."),
        "acc_aria": f"תאונות דרכים עם נפגעים לפי חודש, {_mname(mts[0])} עד {_mname(lt)}",
        "acc_caption": "תאונות דרכים עם נפגעים לפי חודש",
        "season_note": "מספר ההרוגים בתאונות דרכים בכל חודש, שנה מול שנה.",
        "season_aria": "הרוגים בתאונות דרכים לפי חודש, שנה מול שנה",
        "season_caption": "הרוגים בתאונות דרכים לפי חודש ושנה",
        "ytd_note": (f"סך ההרוגים, הפצועים קשה והתאונות הקטלניות בחודשים {span_txt} בכל "
                     f"שנה, כדי להשוות את {cy} לתקופה המקבילה בשנים קודמות."),
        "ytd_aria": f"הרוגים ופצועים קשה, {span_txt}, לפי שנה",
        "ytd_caption": f"נפגעים ותאונות בחודשים {span_txt}, לפי שנה",
    })
    if full_years:
        labels.update({
            "annual_note": (f"סך ההרוגים והפצועים קשה בכל שנה מלאה ({full_years[0]}-"
                            f"{full_years[-1]}), ומספר הנפגעים הכולל (הקו, בציר הימני)."),
            "annual_aria": f"הרוגים, פצועים קשה ונפגעים לפי שנה, {full_years[0]}-{full_years[-1]}",
            "annual_caption": "נפגעים ותאונות לפי שנה",
        })
    if "severity" in charts:
        labels.update({
            "severity_note": ("כמה מהנפגעים נהרגו (לכל 1,000 נפגעים), ואיזה חלק מהתאונות "
                              "היו קטלניות או קשות. עלייה בשני הקווים פירושה שהתאונות "
                              "חמורות יותר בממוצע."),
            "severity_aria": "הרוגים לכל אלף נפגעים ושיעור התאונות הקטלניות והקשות לפי שנה",
            "severity_caption": "חומרת התאונות לפי שנה",
        })
    if "revision" in charts:
        labels.update({
            "revision_note": ("מספר הנפגעים בכל חודש כפי שפורסם לראשונה בהודעה של אותו "
                              "חודש, מול המספר בנתונים העדכניים. דיווחים על נפגעים מגיעים "
                              "באיחור, ולכן הנתון הראשון נמוך מהסופי."),
            "revision_aria": "נפגעים לפי חודש: פרסום ראשון מול נתון עדכני",
            "revision_caption": "נפגעים: פרסום ראשון מול נתון עדכני",
        })
    labels["provisional"] = (f"הנתונים מאז {prov_year} ארעיים, והלמ\"ס מעדכנת אותם בהודעות "
                             f"הבאות. העמוד מציג תמיד את הגרסה האחרונה."
                             if prov_year else
                             "נתוני החודשים האחרונים ארעיים, והלמ\"ס מעדכנת אותם בהודעות "
                             "הבאות. העמוד מציג תמיד את הגרסה האחרונה.")

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = ("תאונות דרכים עם נפגעים בישראל לפי חודש, מנתוני הלמ\"ס: הרוגים, פצועים "
               "קשה ומספר התאונות. "
               + (f"ב{span_txt} {cy} נהרגו {fmt.int_he(cur['killed'])} בני אדם"
                  + (f" ({fmt.signed_pct(k_chg)} לעומת {cy - 1})" if k_chg is not None else "")
                  + "." if cur else f"ב{_mname(lt)} נהרגו {_n(last['killed'])} בני אדם."))
    if cur:
        when = f"{fmt.int_he(cur['killed'])} הרוגים ב{span_txt} {cy}" + (
            f" ({fmt.signed_pct(k_chg)} בשנה)" if k_chg is not None else "")
    else:
        when = f"{_n(last['killed'])} הרוגים ב{_mname(lt)}"
    desc = (f"כמה נהרגו בתאונות דרכים בישראל: {when}. נתונים חודשיים של הלמ\"ס על "
            f"הרוגים, פצועים קשה ותאונות.")
    first_year = min(full_years + [mts[0][0]])
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_year}/{cy}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "תאונות דרכים: הרוגים ונפגעים לפי חודש | הלמ\"ס",
                "description": desc,
                "name": "תאונות דרכים עם נפגעים",
                "alternate_names": ["הרוגים בתאונות דרכים", "נפגעים בתאונות דרכים",
                                    "מספר ההרוגים בכבישים", "תאונות דרכים בישראל"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"annual": bool(full_years), "severity": "severity" in charts,
                  "revision": "revision" in charts, "ytd": len(ytd_years) >= 2},
    }
