"""סקר מגמות בעסקים: CBS's monthly Business Tendency Survey release.

Managers are asked about the previous month's activity, their current state
and the next month. The release's chart tables carry the "net balance"
(share reporting an increase minus share reporting a decrease, as a
fraction) per month since mid-2019, next to the official index it tracks:

  t1  total balance vs the change in the revenue index, all industries
  t2  manufacturing sales balance vs the change in industrial production
  t3  construction: balance of current activity and of new works
  t4  retail sales balance vs the change in the VAT revenue index
  t5  hotels revenue balance vs the hotel-survey revenue index (y/y)
  t6  services local-sales balance vs the change in the VAT revenue index
  t7  % of firms naming the security situation a severe constraint, by
      industry: before the war and in the latest survey
  t8  the same for a shortage of workers
  releases  the edition list (number, date, headline, link)

Header rows and columns are found by their labels (govlib.cbs) and raise
when missing; period rows are found by pattern, so a missing one only
shortens a series. A month here is the month the activity happened (the
survey that asks about it is published a month later).
"""
import re

import pandas as pd
from govlib import cbs, fmt

HEAT_MONTHS = 24
DATE = re.compile(r"((?:19|20)\d\d)-(\d\d)")

# The six monthly chart tables: (key, input, sector name, balance label,
# comparator label, comparator is a balance too, short comparator name).
SERIES = [
    ("total", "t1", "כלל המשק", "מאזן כולל", "השינוי במדד", False,
     "השינוי במדד הפדיון"),
    ("manuf", "t2", "תעשייה", "מאזן נטו", "השינוי במדד", False,
     "השינוי במדד הייצור התעשייתי"),
    ("constr", "t3", "בינוי", "מאזן נטו של פעילות שוטפת", "מאזן נטו של עבודות חדשות", True,
     "מאזן עבודות חדשות"),
    ("retail", "t4", "מסחר קמעוני", "מאזן נטו", "השינוי במדד", False,
     "השינוי במדד הפדיון"),
    ("hotels", "t5", "מלונאות", "מאזן נטו", "השינוי במדד", False,
     "השינוי במדד הפדיון"),
    ("services", "t6", "שירותים", "מאזן נטו", "השינוי במדד", False,
     "השינוי במדד הפדיון"),
]
# "בענף ה…" forms of the sector names.
DEFINITE = {"total": "כלל המשק", "manuf": "התעשייה", "constr": "הבינוי",
            "retail": "המסחר הקמעוני", "hotels": "המלונאות", "services": "השירותים"}
SECTORS = ["manuf", "constr", "retail", "hotels", "services"]
SECTION_TITLE = {
    "manuf": "תעשייה: מכירות מול מדד הייצור",
    "constr": "בינוי: פעילות שוטפת ועבודות חדשות",
    "retail": "מסחר קמעוני: מכירות מול מדד הפדיון",
    "hotels": "מלונאות: פדיון מול מדד הפדיון",
    "services": "שירותים: מכירות לשוק המקומי מול מדד הפדיון",
}


# ── tables ───────────────────────────────────────────────────────────────


def _monthly(rows, name, a_label, b_label):
    """[((year, month), a, b)] for the monthly chart table, plus the two
    header texts. a = balance, b = the comparator; month rows only."""
    h = cbs.row_with(rows, "חודש", name=name)
    a = cbs.col_after(rows[h], a_label, 0, contains=True)
    b = cbs.col_after(rows[h], b_label, 0, contains=True)
    out = []
    for i, y, m, end in cbs.periods(rows, h + 1, len(rows)):
        if m is None or end:
            continue
        va, vb = cbs.val(rows[i], a), cbs.val(rows[i], b)
        if va is None and vb is None:
            continue
        out.append(((y, m), va, vb))
    out.sort(key=lambda r: r[0])
    # A period listed twice (a revised row) keeps its last value.
    dedup = {}
    for t, va, vb in out:
        dedup[t] = (va, vb)
    return [(t, *dedup[t]) for t in sorted(dedup)], rows[h][a], rows[h][b]


def _constraint(rows, name):
    """{"before": {sector: pct}, "now": {sector: pct}, "now_t": (y, m)} from a
    'before the war vs latest' chart table."""
    h = cbs.row_with(rows, "טרום", name=name, contains=True)
    before = cbs.col_after(rows[h], "טרום", 0, contains=True)
    now = next((j for j, c in enumerate(rows[h]) if DATE.match(c)), None)
    if now is None:
        raise ValueError(f"{name}: latest-survey date header not found")
    m = DATE.match(rows[h][now])
    out = {"before": {}, "now": {}, "now_t": (int(m.group(1)), int(m.group(2)))}
    for r in rows[h + 1:]:
        label = cbs.cell(r, 0)
        if not label or not re.search("[א-ת]", label):
            continue
        b, n = cbs.val(r, before), cbs.val(r, now)
        if n is None:
            continue
        out["now"][label] = n
        if b is not None:
            out["before"][label] = b
    if not out["now"]:
        raise ValueError(f"{name}: no industry rows")
    return out


# ── formatting ───────────────────────────────────────────────────────────


def _pp(v):
    """A balance fraction in percentage points, signed: 0.088 → '+8.8'."""
    x = round(v * 100, 1)
    if x == 0:
        return "0.0"
    return ("+" if x > 0 else fmt.MINUS) + fmt.num_he(abs(x), 1)


def _p(v):
    return None if v is None else round(v * 100, 1)


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {str(t[0])[2:]}"


def _prev(t, k=1):
    y, m = t
    n = y * 12 + (m - 1) - k
    return (n // 12, n % 12 + 1)


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _tone(v, band=0.02):
    if v is None:
        return "brand"
    return "ok" if v >= band else "danger" if v <= -band else "warn"


def _corr(pairs):
    if len(pairs) < 3:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if not sxx or not syy:
        return None
    return sxy / (sxx * syy) ** 0.5


def _yearly(series):
    """[[year, mean a, mean b, months]] rows for a monthly series."""
    out = []
    for y in sorted({t[0] for t, _, _ in series}):
        a = [va for t, va, _ in series if t[0] == y and va is not None]
        b = [vb for t, _, vb in series if t[0] == y and vb is not None]
        out.append([str(y), _pp(_mean(a)) if a else "",
                    _pp(_mean(b)) if b else "", str(len(a))])
    return out


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    data, heads = {}, {}
    for key, inp, _sector, a_label, b_label, _bal, _short in SERIES:
        data[key], ha, hb = _monthly(cbs.grid(frames[inp], inp), inp, a_label, b_label)
        heads[key] = (ha, hb)
    names = {s[0]: s[2] for s in SERIES}
    bal = {k: {t: a for t, a, _ in v if a is not None} for k, v in data.items()}
    if not bal["total"]:
        raise ValueError("t1: no total-balance months")

    tot = sorted(bal["total"])
    lt = tot[-1]
    last = bal["total"][lt]
    pm = bal["total"].get(_prev(lt))
    yago = bal["total"].get(_prev(lt, 12))
    last12 = [bal["total"][t] for t in tot[-12:]]
    avg12 = _mean(last12)

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["balance"] = {"value": round(last * 100, 1), "display": _pp(last), "tone": _tone(last)}
    labels["balance_kpi"] = f"מאזן כולל, פעילות ב{_mname(lt)} (נקודות אחוז)"
    if pm is not None:
        d = last - pm
        kpis["mom"] = {"value": round(d * 100, 1), "display": _pp(d), "tone": _tone(d)}
        labels["mom_kpi"] = f"שינוי לעומת {_mname(_prev(lt))} (נקודות אחוז)"
    if len(last12) >= 6:
        kpis["avg12"] = {"value": round(avg12 * 100, 1), "display": _pp(avg12),
                         "tone": "brand"}
        labels["avg12_kpi"] = f"ממוצע המאזן הכולל ב-{len(last12)} החודשים האחרונים"
    sec_last = {k: bal[k][lt] for k in SECTORS if lt in bal[k]}
    if sec_last:
        pos = sum(1 for v in sec_last.values() if v > 0)
        kpis["positive"] = {"value": pos, "display": str(pos),
                            "tone": "ok" if pos * 2 > len(sec_last) else
                            "danger" if pos * 2 < len(sec_last) else "warn"}
        labels["positive_kpi"] = (f"ענפים עם מאזן חיובי ב{_mname(lt)}, "
                                  f"מתוך {len(sec_last)}")

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables, sections = {}, {}, []
    s = data["total"]
    charts["total"] = {"x": [f"{t[0]}-{t[1]:02d}" for t, _, _ in s],
                       "a": [_p(a) for _, a, _ in s], "b": [_p(b) for _, _, b in s]}
    tables["total"] = _yearly(s)

    # Sector snapshot: latest month and the same month a year earlier.
    snap = [k for k in SECTORS if lt in bal[k]]
    snap.sort(key=lambda k: (-bal[k][lt], k))
    charts["sectors"] = {"names": [names[k] for k in snap],
                         "now": [_p(bal[k][lt]) for k in snap],
                         "yago": [_p(bal[k].get(_prev(lt, 12))) for k in snap],
                         "now_label": _mname(lt), "yago_label": _mname(_prev(lt, 12))}
    tables["sectors"] = [[names[k], _pp(bal[k][lt]),
                          _pp(bal[k][_prev(lt, 12)]) if _prev(lt, 12) in bal[k] else ""]
                         for k in snap]

    # Heatmap: sectors × the last months.
    hm = tot[-HEAT_MONTHS:]
    heat_rows = ["total"] + SECTORS
    cells = []
    for yi, k in enumerate(heat_rows):
        for xi, t in enumerate(hm):
            if t in bal[k]:
                cells.append([xi, yi, _p(bal[k][t])])
    vmax = max([abs(c[2]) for c in cells] + [1])
    charts["heat"] = {"x": [_mshort(t) for t in hm], "y": [names[k] for k in heat_rows],
                      "cells": cells, "max": round(vmax)}
    tables["heat"] = [[_mname(t)] + [_pp(bal[k][t]) if t in bal[k] else "" for k in heat_rows]
                      for t in reversed(hm)]
    labels["heat_cols"] = ["חודש"] + [names[k] for k in heat_rows]

    # Per-sector sections: the balance against its comparator.
    for key in SECTORS:
        sr = data[key]
        if not [a for _, a, _ in sr if a is not None]:
            continue
        spec = next(x for x in SERIES if x[0] == key)
        charts[key] = {"x": [f"{t[0]}-{t[1]:02d}" for t, _, _ in sr],
                       "a": [_p(a) for _, a, _ in sr], "b": [_p(b) for _, _, b in sr],
                       "a_name": "מאזן נטו" if not spec[5] else "מאזן פעילות שוטפת",
                       "b_name": spec[6], "b_balance": spec[5]}
        b_months = [t for t, _, b in sr if b is not None]
        a_months = [t for t, a, _ in sr if a is not None]
        note = (f"{heads[key][0]}, לפי חודש הפעילות מאז {_mname(a_months[0])}"
                + (f", לצד {heads[key][1]}." if b_months else "."))
        if b_months and b_months[-1] < _prev(a_months[-1], 6):
            note += f" נתוני המדד מוצגים עד {_mname(b_months[-1])}, החודש האחרון שבלוח."
        sections.append({
            "id": key, "title": SECTION_TITLE[key], "note": note,
            "aria": f"{SECTION_TITLE[key]}, {_mname(a_months[0])} עד {_mname(a_months[-1])}",
            "caption": f"{names[key]}: ממוצע שנתי (נקודות אחוז / אחוזים)",
            "cols": ["שנה", charts[key]["a_name"], spec[6], "חודשים"],
            "rows": _yearly(sr),
        })

    # Constraints: security situation and worker shortage.
    cons = {}
    for key, inp in (("security", "t7"), ("labor", "t8")):
        c = _constraint(cbs.grid(frames[inp], inp), inp)
        order = sorted(c["now"], key=lambda n: (-c["now"][n], n))
        charts[key] = {"names": order, "before": [c["before"].get(n) for n in order],
                       "now": [c["now"][n] for n in order], "now_label": _mname(c["now_t"])}
        tables[key] = [[n, fmt.pct_of(c["before"][n]) if n in c["before"] else "",
                        fmt.pct_of(c["now"][n])] for n in order]
        cons[key] = (c, order)

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if pm is not None:
        d = last - pm
        trend = ("עלה" if d >= 0.02 else "ירד" if d <= -0.02 else "כמעט לא השתנה")
        add("latest", f"המאזן הכולל של הפעילות בעסקים ב{_mname(lt)} עמד על {_pp(last)} נקודות "
                      f"אחוז: {'יותר' if last > 0 else 'פחות'} חברות דיווחו על עלייה בפעילות "
                      f"מאשר על ירידה. לעומת {_mname(_prev(lt))} המאזן {trend}"
                      + (f" ({_pp(d)} נקודות)." if trend != "כמעט לא השתנה" else "."))
    # Streak of same-sign months.
    sign = last > 0
    run, t = 0, lt
    while t in bal["total"] and (bal["total"][t] > 0) == sign:
        run += 1
        t = _prev(t)
    if run >= 3:
        add("streak", f"זה החודש ה-{run} ברציפות שבו המאזן הכולל "
                      f"{'חיובי' if sign else 'שלילי'}.")
    if len(tot) >= 24:
        lo = min(tot, key=lambda t: (bal["total"][t], t))
        lo12 = min(tot[-12:], key=lambda t: (bal["total"][t], t))
        if lo12 != lt and bal["total"][lo12] <= -0.1:
            add("dip", f"השפל של השנה האחרונה היה ב{_mname(lo12)}, עם מאזן של "
                       f"{_pp(bal['total'][lo12])} נקודות. השפל העמוק ביותר בסדרה, מאז "
                       f"{_mname(tot[0])}, נרשם ב{_mname(lo)}: {_pp(bal['total'][lo])} נקודות.")
    if yago is not None and abs(last - yago) >= 0.03:
        add("yoy", f"לעומת {_mname(_prev(lt, 12))}, אז עמד המאזן הכולל על {_pp(yago)} נקודות, "
                   f"התמונה {'טובה' if last > yago else 'חלשה'} יותר ב-"
                   f"{fmt.num_he(abs(last - yago) * 100, 1)} נקודות.")
    if len(snap) >= 3:
        hi, lo_s = snap[0], snap[-1]
        if bal[hi][lt] - bal[lo_s][lt] >= 0.05:
            add("sectors", f"ב{_mname(lt)} המאזן הגבוה ביותר היה בענף {DEFINITE[hi]} "
                           f"({_pp(bal[hi][lt])} נקודות) והנמוך ביותר בענף {DEFINITE[lo_s]} "
                           f"({_pp(bal[lo_s][lt])} נקודות).")
    pairs = [(a, b) for _, a, b in data["total"] if a is not None and b is not None]
    if len(pairs) >= 24:
        agree = sum(1 for a, b in pairs if (a > 0) == (b > 0)) / len(pairs)
        r = _corr(pairs)
        if agree >= 0.6 and r is not None and r > 0.3:
            add("match", f"הסקר משקף את הנתונים הקשים: ב-{fmt.pct(agree, 0)} מתוך {len(pairs)} "
                         f"החודשים שבהם יש לשניהם נתון, כיוון המאזן הכולל (חיובי או שלילי) "
                         f"תאם את כיוון השינוי במדד הפדיון לכלל ענפי המשק.")
    c, order = cons["security"]
    top = order[0]
    if c["now"][top] >= 10:
        b = c["before"].get(top)
        add("security", f"{fmt.pct_of(c['now'][top])} מהחברות בענף {top} דיווחו ב"
                        f"{_mname(c['now_t'])} שהמצב הביטחוני הוא מגבלה חמורה על פעילותן"
                        + (f", לעומת {fmt.pct_of(b)} לפני המלחמה." if b is not None else "."))
    c, order = cons["labor"]
    up = [n for n in order if n in c["before"] and c["now"][n] > c["before"][n]]
    top = order[0]
    if c["now"][top] >= 10:
        add("labor", f"מחסור בעובדים מגביל במיוחד את הפעילות בענף {top}: "
                     f"{fmt.pct_of(c['now'][top])} מהחברות דיווחו עליו כמגבלה חמורה ב{_mname(c['now_t'])}"
                     + (f". השיעור גבוה מזה שלפני המלחמה ב-{len(up)} מתוך {len(order)} הענפים."
                        if len(up) * 2 > len(order) else "."))
    cs = data["constr"]
    gap = [(t, a, b) for t, a, b in cs if a is not None and b is not None]
    if gap:
        t, a, b = gap[-1]
        if abs(a - b) >= 0.03:
            add("constr", f"בבינוי, מאזן העבודות החדשות ב{_mname(t)} ({_pp(b)} נקודות) "
                          f"{'נמוך' if b < a else 'גבוה'} ממאזן הפעילות השוטפת ({_pp(a)}): "
                          f"{'פחות' if b < a else 'יותר'} עבודות חדשות נכנסות לעומת היקף "
                          f"הפעילות הקיימת.")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": ("סקר הערכת המגמות בעסקים של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) שואל בכל חודש "
                 "מנהלי חברות בתעשייה, בבינוי, במסחר, במלונאות ובשירותים אם הפעילות שלהם "
                 "עלתה או ירדה. המאזן הוא שיעור המדווחים על עלייה פחות שיעור המדווחים על "
                 "ירידה, כך שמאזן חיובי מצביע על התרחבות. העמוד מציג את המאזנים לפי חודש "
                 f"הפעילות, לצד המדדים הרשמיים שהם צופים. הנתון האחרון: {_mname(lt)}, "
                 f"מאזן כולל של {_pp(last)} נקודות."),
        "total_note": (f"{heads['total'][0]} בכל חודש מאז {_mname(tot[0])} (עמודות), לצד "
                       f"{heads['total'][1]} (קו). אפשר לגרור כדי להתמקד בתקופה."),
        "total_aria": f"מאזן כולל ומדד הפדיון, {_mname(tot[0])} עד {_mname(lt)}",
        "total_caption": "מאזן כולל ושינוי במדד הפדיון, ממוצע שנתי",
        "sectors_note": (f"המאזן בכל ענף ב{_mname(lt)}, לעומת אותו חודש שנה קודם. בבינוי: "
                         "מאזן הפעילות השוטפת."),
        "sectors_aria": f"מאזן לפי ענף, {_mname(lt)} לעומת {_mname(_prev(lt, 12))}",
        "sectors_caption": "מאזן לפי ענף (נקודות אחוז)",
        "heat_note": (f"המאזן בכל ענף בכל חודש מאז {_mname(hm[0])}: כחול לעלייה, אדום "
                      "לירידה. כך רואים אם תנודה פגעה בכל המשק או בענף אחד."),
        "heat_aria": f"מאזן לפי ענף וחודש, {_mname(hm[0])} עד {_mname(hm[-1])}",
        "heat_caption": "מאזן לפי ענף וחודש (נקודות אחוז)",
        "security_note": ("שיעור החברות בכל ענף שדיווחו שהמצב הביטחוני הוא מגבלה חמורה על "
                          f"פעילותן: לפני המלחמה ובסקר {charts['security']['now_label']}."),
        "security_aria": "מגבלה ביטחונית חמורה לפי ענף, לפני המלחמה ובסקר האחרון",
        "security_caption": "המצב הביטחוני כמגבלה חמורה (אחוז מהחברות)",
        "labor_note": ("שיעור החברות בכל ענף שדיווחו שמחסור בעובדים הוא מגבלה חמורה על "
                       f"פעילותן: לפני המלחמה ובסקר {charts['labor']['now_label']}."),
        "labor_aria": "מחסור בעובדים כמגבלה חמורה לפי ענף, לפני המלחמה ובסקר האחרון",
        "labor_caption": "מחסור בעובדים כמגבלה חמורה (אחוז מהחברות)",
    })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"סקר מגמות בעסקים של הלמ\"ס: מאזן הפעילות בכלל המשק ובכל ענף, לפי חודש. "
               f"ב{_mname(lt)} המאזן הכולל עמד על {_pp(last)} נקודות אחוז.")
    desc = (f"סקר מגמות בעסקים: המאזן הכולל ב{_mname(lt)} {_pp(last)} נקודות. "
            f"מאזן לפי ענף, מגבלות ביטחון ומחסור בעובדים, מנתוני הלמ\"ס.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{tot[0][0]}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "סקר מגמות בעסקים: מאזן הפעילות לפי ענף | הלמ\"ס",
                "description": desc,
                "name": "סקר מגמות בעסקים",
                "alternate_names": ["סקר הערכת המגמות בעסקים", "סקר מגמות בעסקים הלמ\"ס",
                                    "מאזן נטו סקר מגמות"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "sections": sections,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"sectors": len(snap) >= 2},
    }
