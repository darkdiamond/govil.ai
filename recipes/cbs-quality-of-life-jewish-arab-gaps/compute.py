"""פערים בין יהודים לערבים במדדי איכות חיים: CBS's yearly release comparing
the quality-of-life indicators of Jews (and others) and Arabs.

Every value in the release is a RATIO between the two groups, oriented so
that 1 means equality, below 1 means the situation of Jews and others is
better and above 1 means the situation of Arabs is better (for an indicator
where lower is better, such as infant mortality, CBS inverts the ratio).

The release is a set of chart-data sheets ("תרשים N - ..."). One edition
holds both the newest year and the full trend of every gap (2002 onward),
so the source reads one edition (`history_releases: 1`). CBS RENUMBERS the
charts between editions (the summary was chart 1, then chart א, then chart
1 again, with every other chart shifting by one), so every table input
(t1..t27, the last three spare, all optional) is classified by its TITLE:

  summary   סיכום (ה)פערים ... לפי תחום                 share of indicators
                                                          favouring each group
  trend     מגמות בפערים בין יהודים לערבים בתחום X, Y-Y  ratio per year
  snapshot  פערים בין יהודים לערבים בתחום X, YYYY       ratio, newest year
  (all)     יחס בין ... במדדי איכות חיים                  every indicator in
                                                          one chart: skipped,
                                                          the snapshots hold
                                                          the same values
                                                          (capped at 2 there)

A snapshot sheet may also carry the underlying percentages for Jews and
Arabs (the welfare chart did in 2024): that table is shown when present.

A missing kind drops its section. A recognised summary whose header labels
are gone raises (the layout changed: a human should look).
"""
import math
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^תרשים\s*[\dא-ת]+\s*-\s*(.+)$")
DOMAIN_TAIL = re.compile(r",?\s*(?:19|20)\d\d(?:\s*-\s*(?:19|20)\d\d)?\s*$")
YEAR_IN = re.compile(r"((?:19|20)\d\d)")
STEMS = [f"t{i}" for i in range(1, 28)]
# A gap counts as narrowed / widened when its distance from equality,
# |ln(ratio)|, moved by more than this between the first and last year.
MOVE = 0.05
LN2 = 0.6931471805599453
# Trends shorter than this many years are left out of the change view.
MIN_SPAN = 5
# The change chart shows the indicators whose gap moved most.
CHANGE_TOP = 16
MAX_INSIGHTS = 8
# The percentages behind the ratios are shown for this domain only: its
# items are all survey shares (other domains mix shekels, years and rates).
RAW_DOMAIN = "רווחה אישית"
GROUPS = frozenset({"יהודים", "ערבים", "סה\"כ", "סך הכל", "יהודים ואחרים"})


# ── table parsing ───────────────────────────────────────────────────────


def _blocks(rows):
    """[(title, rows under it)] for every titled chart in a grid."""
    out = []
    for r in rows:
        t = next((m.group(1).strip() for c in r if (m := TITLE.match(c))), None)
        if t is not None:
            out.append((t, []))
        elif out:
            out[-1][1].append(r)
    return out


def _domain(title):
    m = re.search(r"בתחום\s+(.+)$", title)
    if not m:
        return None
    d = DOMAIN_TAIL.sub("", m.group(1)).strip(" ,")
    # "הבריאות" in the chart titles, "בריאות" in the summary.
    return re.sub(r"^ה(?=בריאות)", "", d)


def _kind(title):
    if "סיכום" in title and "פערים" in title:
        return "summary"
    if "בין יהודים לערבים" not in title or "בתחום" not in title:
        return None
    return "trend" if title.startswith("מגמות") else "snapshot"


def _label(s):
    s = re.sub(r"\s+", " ", s.replace("ש\"ר", "שביעות רצון")).strip(" -")
    return re.sub(r"\s*-\s*", " - ", s)


def _summary(rows):
    hdr = None
    for i, r in enumerate(rows):
        if any("שוויון" in c for c in r):
            hdr = i
            break
    if hdr is None:
        raise ValueError("summary: header label 'שוויון בין הקבוצות' not found")
    h = rows[hdr]
    eq = cbs.col_after(h, "שוויון", contains=True)
    jw = next((j for j, c in enumerate(h) if "יהודים" in c and "טוב" in c), None)
    ar = next((j for j, c in enumerate(h) if "ערבים" in c and "טוב" in c), None)
    if jw is None or ar is None:
        raise ValueError("summary: header labels 'מצב יהודים/ערבים טוב יותר' not found")
    out = []
    for r in rows[hdr + 1:]:
        lab = cbs.cell(r, 0)
        vals = [cbs.val(r, j) for j in (jw, eq, ar)]
        if not lab or all(v is None for v in vals):
            continue
        if lab.startswith("("):
            continue
        out.append((lab, *[(v or 0.0) for v in vals]))
    return out


def _snapshot(rows):
    """[(label, ratio)] from the label / value pairs, plus the optional
    Jews / Arabs percentage table [(label, total, jews, arabs)]."""
    pairs, raw = [], []
    start = len(rows)
    # Groups as columns: a header row holding both "יהודים" and "ערבים".
    cols_hdr = next((i for i, r in enumerate(rows) if "יהודים" in r and "ערבים" in r), None)
    # Groups as rows: a row starting "יהודים", another "ערבים" in that column.
    rows_grp = None
    if cols_hdr is None:
        for i, r in enumerate(rows):
            if "יהודים" in r:
                g = r.index("יהודים")
                ia = next((k for k in range(len(rows)) if cbs.cell(rows[k], g) == "ערבים"), None)
                if ia is not None:
                    rows_grp = (g, i, ia)
                    break
    if cols_hdr is not None:
        start = cols_hdr
        h = rows[cols_hdr]
        jj, aj = h.index("יהודים"), h.index("ערבים")
        tj = next((j for j, c in enumerate(h) if c.startswith("סה")), None)
        lj = min(j for j in (jj, aj, tj) if j is not None) - 1
        for r in rows[cols_hdr + 1:]:
            lab = cbs.cell(r, lj)
            j, a = cbs.val(r, jj), cbs.val(r, aj)
            if lab and j is not None and a is not None:
                raw.append((_label(lab), cbs.val(r, tj) if tj is not None else None, j, a))
    elif rows_grp is not None:
        g, ij, ia = rows_grp
        it = next((k for k in range(len(rows)) if cbs.cell(rows[k], g).startswith("סה")), None)
        first = min(k for k in (ij, ia, it) if k is not None)
        hi = next((k for k in range(first - 1, -1, -1)
                   if sum(1 for c in rows[k][g + 1:] if re.search("[א-ת]", c)) >= 2), None)
        start = hi if hi is not None else first
        if hi is not None:
            for j in range(g + 1, len(rows[hi])):
                lab = rows[hi][j]
                jv, av = cbs.val(rows[ij], j), cbs.val(rows[ia], j)
                if lab and jv is not None and av is not None:
                    raw.append((_label(lab), cbs.val(rows[it], j) if it is not None else None, jv, av))
    for r in rows[:start]:
        lab, v = cbs.cell(r, 0), cbs.val(r, 1)
        if lab and v is not None and re.search("[א-ת]", lab) and lab not in GROUPS:
            pairs.append((_label(lab), v))
    return pairs, raw


def _trend(rows):
    """(years, [(label, {year: ratio})])."""
    yr = None
    for i, r in enumerate(rows):
        cols = {j: int(c) for j, c in enumerate(r) if cbs.YEAR.match(c)}
        if len(cols) >= 3:
            yr = (i, cols)
            break
    if yr is None:
        return [], []
    i0, cols = yr
    series = []
    for r in rows[i0 + 1:]:
        lab = cbs.cell(r, 0)
        if not lab or not re.search("[א-ת]", lab) or lab.startswith("("):
            continue
        s = {y: v for j, y in cols.items() if (v := cbs.val(r, j)) is not None}
        if s:
            series.append((_label(lab), s))
    return sorted(set(cols.values())), series


def _tables(frames):
    out = {"summary": None, "trend": [], "snapshot": []}
    for stem in STEMS:
        df = frames.get(stem)
        if df is None or df.empty:
            continue
        for title, rows in _blocks(cbs.grid(df, stem)):
            k = _kind(title)
            if k == "summary" and out["summary"] is None:
                s = _summary(rows)
                if s:
                    out["summary"] = s
            elif k == "trend":
                years, series = _trend(rows)
                if series:
                    out["trend"].append({"domain": _domain(title), "years": years, "series": series})
            elif k == "snapshot":
                pairs, raw = _snapshot(rows)
                m = YEAR_IN.findall(title)
                if pairs:
                    out["snapshot"].append({"domain": _domain(title), "year": int(m[-1]) if m else None,
                                            "pairs": pairs, "raw": raw})
    return out


# ── formatting ──────────────────────────────────────────────────────────


def _r(v):
    """A ratio as printed: two decimals (three below 0.1, when the third
    is not a zero)."""
    if v >= 0.095:
        return f"{v:.2f}"
    s = f"{v:.3f}"
    return s.removesuffix("0")


def _side(v):
    if v < 1:
        return "jews"
    if v > 1:
        return "arabs"
    return "equal"


def _dist(v):
    # |ln v|, via log2 (the function merged recipes already use).
    return abs(math.log2(v)) * LN2 if v > 0 else None


def _pct(f):
    return fmt.pct(f)


# ── compute ─────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    T = _tables(frames)
    snaps, trends, summary = T["snapshot"], T["trend"], T["summary"]
    if not snaps and not trends:
        raise ValueError("no snapshot or trend chart recognised in any table")

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    cands = []

    def add(iid, text):
        if text:
            cands.append({"id": iid, "text_he": text})

    rel_title = str(rel.get("TITLE") or "")
    ym = YEAR_IN.findall(rel_title)
    snap_years = sorted({s["year"] for s in snaps if s["year"]})
    ly = int(ym[-1]) if ym else (snap_years[-1] if snap_years else None)
    labels["latest_year"] = str(ly) if ly else ""
    labels["move_pct"] = fmt.pct(MOVE, 0)

    # ── every indicator, newest year ──
    inds = []
    for s in snaps:
        for lab, v in s["pairs"]:
            if v > 0:
                inds.append({"domain": s["domain"], "label": lab, "v": v})
    domains = []
    for s in snaps:
        if s["domain"] not in domains and any(i["domain"] == s["domain"] for i in inds):
            domains.append(s["domain"])
    n = len(inds)
    n_j = sum(1 for i in inds if i["v"] < 1)
    n_a = sum(1 for i in inds if i["v"] > 1)

    # ── 1. CBS summary by domain ──
    total = None
    if summary:
        rows = [r for r in summary if r[0] != "סך הכל"]
        total = next((r for r in summary if r[0] == "סך הכל"), None)
        if rows:
            flags["summary"] = True
            charts["summary"] = {
                "x": [r[0] for r in rows],
                "jews": [round(r[1] * 100, 1) for r in rows],
                "equal": [round(r[2] * 100, 1) for r in rows],
                "arabs": [round(r[3] * 100, 1) for r in rows],
            }
            tables["summary"] = [[r[0], _pct(r[1]), _pct(r[2]), _pct(r[3])] for r in summary]
            labels["summary_aria"] = (f"שיעור המדדים שבהם מצב היהודים ואחרים טוב יותר, שוויון, ומצב הערבים "
                                      f"טוב יותר, בכל אחד מ-{len(rows)} תחומי איכות החיים")
            all_j = [r[0] for r in rows if r[1] >= 0.999]
            top_a = max(rows, key=lambda r: (r[3], r[0]))
            labels["summary_note"] = (
                "החלוקה של הלמ\"ס: בכל תחום, איזה חלק מהמדדים מראה מצב טוב יותר ליהודים ואחרים, "
                "איזה חלק מראה שוויון ואיזה חלק מראה מצב טוב יותר לערבים, בשנת הדיווח האחרונה של כל מדד.")
            if all_j:
                add("summary_all", f"בתחומים {fmt.join_he(all_j)} מצב היהודים ואחרים טוב יותר בכל המדדים "
                                   f"שהלמ\"ס בודקת." if len(all_j) > 1 else
                    f"בתחום {all_j[0]} מצב היהודים ואחרים טוב יותר בכל המדדים שהלמ\"ס בודקת.")
            if top_a[3] > 0:
                add("summary_arabs", f"התחום שבו חלק המדדים המראים מצב טוב יותר לערבים הוא הגדול ביותר: "
                                     f"{top_a[0]}, {_pct(top_a[3])} מהמדדים בתחום.")
    if total:
        kpis["jews_better"] = {"value": round(total[1] * 100, 1), "display": _pct(total[1]), "tone": "brand"}
        kpis["arabs_better"] = {"value": round(total[3] * 100, 1), "display": _pct(total[3]), "tone": "brand"}
        kpis["equal"] = {"value": round(total[2] * 100, 1), "display": _pct(total[2]), "tone": "brand"}
        labels["kpi_basis"] = "מסיכום הלמ\"ס"
        add("total", f"לפי סיכום הלמ\"ס, ב-{_pct(total[1])} מהמדדים מצב היהודים ואחרים טוב יותר, "
                     f"ב-{_pct(total[3])} מצב הערבים טוב יותר וב-{_pct(total[2])} יש שוויון בין הקבוצות.")
    elif n:
        kpis["jews_better"] = {"value": round(n_j / n * 100, 1), "display": _pct(n_j / n), "tone": "brand"}
        kpis["arabs_better"] = {"value": round(n_a / n * 100, 1), "display": _pct(n_a / n), "tone": "brand"}
        labels["kpi_basis"] = "יחס מתחת ל-1 או מעליו"
        add("total", f"מתוך {n} מדדים, ב-{n_j} היחס נמוך מ-1 (מצב היהודים ואחרים טוב יותר) "
                     f"וב-{n_a} הוא גבוה מ-1 (מצב הערבים טוב יותר).")
    if n:
        kpis["indicators"] = {"value": n, "display": fmt.int_he(n), "tone": "brand"}

    # ── 2. newest-year ratios by domain ──
    if inds:
        flags["latest"] = True
        by_dom = {}
        for d in domains:
            items = sorted((i for i in inds if i["domain"] == d), key=lambda i: (i["v"], i["label"]))
            by_dom[d] = {"y": [i["label"] for i in items], "v": [round(i["v"], 3) for i in items]}
        charts["latest"] = {"domains": domains, "by": by_dom}
        tables["latest"] = [[i["domain"], i["label"], _r(i["v"])]
                            for d in domains for i in sorted((i for i in inds if i["domain"] == d),
                                                              key=lambda i: (i["v"], i["label"]))]
        labels["latest_aria"] = (f"היחס בין מצב הערבים למצב היהודים בכל מדד, לפי תחום, {labels['latest_year']}; "
                                 f"קו מקווקו ב-1 מסמן שוויון")
        low = sorted(inds, key=lambda i: (i["v"], i["label"]))[:3]
        add("lowest", "הפערים הגדולים ביותר לטובת היהודים ואחרים: "
            + fmt.join_he([f"{i['label']} (יחס {_r(i['v'])})" for i in low]) + ".")
        hi = sorted((i for i in inds if i["v"] > 1), key=lambda i: (-i["v"], i["label"]))[:3]
        if hi:
            add("highest", "המדדים שבהם מצב הערבים טוב יותר בפער הגדול ביותר: "
                + fmt.join_he([f"{i['label']} (יחס {_r(i['v'])})" for i in hi]) + ".")
        mn = min(inds, key=lambda i: (i["v"], i["label"]))
        kpis["lowest"] = {"value": round(mn["v"], 3), "display": _r(mn["v"]), "tone": "danger" if mn["v"] < 0.5 else "warn"}
        labels["lowest_kpi"] = f"היחס הנמוך ביותר: {mn['label']}"

        # median ratio per domain
        meds = []
        for d in domains:
            vs = sorted(i["v"] for i in inds if i["domain"] == d)
            k = len(vs)
            med = vs[k // 2] if k % 2 else (vs[k // 2 - 1] + vs[k // 2]) / 2
            meds.append((d, med, k, sum(1 for v in vs if v < 1)))
        meds.sort(key=lambda m: (m[1], m[0]))
        flags["domains"] = len(meds) >= 2
        charts["domains"] = {"x": [m[0] for m in meds], "y": [round(m[1], 3) for m in meds]}
        tables["domains"] = [[m[0], _r(m[1]), fmt.int_he(m[2]), fmt.int_he(m[3])] for m in meds]
        labels["domains_aria"] = f"היחס החציוני בין מצב הערבים למצב היהודים בכל אחד מ-{len(meds)} התחומים"
        if len(meds) >= 2:
            add("domains", f"היחס החציוני הנמוך ביותר הוא בתחום {meds[0][0]} ({_r(meds[0][1])}), והגבוה ביותר "
                           f"בתחום {meds[-1][0]} ({_r(meds[-1][1])}).")

    # ── 3. trends by domain ──
    if trends:
        flags["trend"] = True
        tdoms, tby = [], {}
        all_years = set()
        for t in trends:
            d = t["domain"]
            if d in tby:
                continue
            tdoms.append(d)
            years = t["years"]
            all_years.update(years)
            tby[d] = {"x": [str(y) for y in years],
                      "series": [{"name": lab, "data": [round(s[y], 3) if y in s else None for y in years]}
                                 for lab, s in t["series"]]}
        charts["trend"] = {"domains": tdoms, "by": tby}
        labels["trend_aria"] = "מגמת היחס בין מצב הערבים למצב היהודים בכל מדד לאורך השנים, לפי תחום"
        ys = sorted(all_years)
        labels["trend_span"] = f"{ys[0]}-{ys[-1]}" if ys else ""

        # change between first and last year of each series
        moves = []
        for t in trends:
            for lab, s in t["series"]:
                yy = sorted(s)
                y0, y1 = yy[0], yy[-1]
                if y1 - y0 < MIN_SPAN or s[y0] <= 0 or s[y1] <= 0:
                    continue
                d0, d1 = _dist(s[y0]), _dist(s[y1])
                state = "narrow" if d1 < d0 - MOVE else "widen" if d1 > d0 + MOVE else "flat"
                moves.append({"domain": t["domain"], "label": lab, "y0": y0, "y1": y1,
                              "v0": s[y0], "v1": s[y1], "delta": d0 - d1, "state": state})
        tables["trend"] = [[m["domain"], m["label"], f"{_r(m['v0'])} ({m['y0']})", f"{_r(m['v1'])} ({m['y1']})",
                            {"narrow": "הצטמצם", "widen": "התרחב", "flat": "ללא שינוי ניכר"}[m["state"]]]
                           for m in moves]
        if moves:
            nn = sum(1 for m in moves if m["state"] == "narrow")
            nw = sum(1 for m in moves if m["state"] == "widen")
            nf = len(moves) - nn - nw
            kpis["narrowed"] = {"value": nn, "display": fmt.int_he(nn), "tone": "ok" if nn > nw else "warn"}
            kpis["widened"] = {"value": nw, "display": fmt.int_he(nw), "tone": "warn" if nw > nn else "brand"}
            labels["moves_n"] = fmt.int_he(len(moves))
            add("moves", f"מתוך {len(moves)} מדדים עם מגמה של {MIN_SPAN} שנים לפחות, הפער הצטמצם ב-{nn}, "
                         f"התרחב ב-{nw} ונותר דומה ב-{nf} (בין השנה הראשונה לאחרונה של כל מדד, לפי כלל העמוד: "
                         f"שינוי של יותר מכ-{fmt.pct(MOVE, 0)} במרחק מקו השוויון).")
            top = sorted(moves, key=lambda m: (-abs(m["delta"]), m["label"]))[:CHANGE_TOP]
            top.sort(key=lambda m: (m["delta"], m["label"]))
            flags["change"] = True
            charts["change"] = {
                "y": [f"{m['label']} ({m['y0']}-{m['y1']})" for m in top],
                "v0": [round(m["v0"], 3) for m in top],
                "v1": [round(m["v1"], 3) for m in top],
            }
            labels["change_aria"] = (f"היחס בשנה הראשונה ובשנה האחרונה של {len(top)} המדדים שבהם הפער השתנה "
                                     f"הכי הרבה")
            labels["change_n"] = fmt.int_he(len(top))
            tables["change"] = [[y, _r(a), _r(b)] for y, a, b in
                                zip(charts["change"]["y"], charts["change"]["v0"], charts["change"]["v1"])]
            best = max(moves, key=lambda m: (m["delta"], m["label"]))
            if best["state"] == "narrow":
                add("best", f"הצטמצמות בולטת: {best['label']}, היחס עלה מ-{_r(best['v0'])} ב-{best['y0']} "
                            f"ל-{_r(best['v1'])} ב-{best['y1']}." if best["v1"] > best["v0"] else
                    f"הצטמצמות בולטת: {best['label']}, היחס ירד מ-{_r(best['v0'])} ב-{best['y0']} "
                    f"ל-{_r(best['v1'])} ב-{best['y1']}, קרוב יותר לשוויון.")
            worst = min(moves, key=lambda m: (m["delta"], m["label"]))
            if worst["state"] == "widen":
                add("worst", f"התרחבות בולטת: {worst['label']}, היחס {'ירד' if worst['v1'] < worst['v0'] else 'עלה'} "
                             f"מ-{_r(worst['v0'])} ב-{worst['y0']} ל-{_r(worst['v1'])} ב-{worst['y1']}.")

    # ── 4. underlying percentages (when a snapshot carries them) ──
    raw_s = next((s for s in snaps if s["raw"] and RAW_DOMAIN in (s["domain"] or "")
                  and all(0 <= v <= 100 for r in s["raw"] for v in r[2:])), None)
    if raw_s:
        raw = raw_s["raw"]
        flags["raw"] = True
        labels["raw_domain"] = raw_s["domain"] or ""
        charts["raw"] = {"x": [r[0] for r in raw], "jews": [r[2] for r in raw], "arabs": [r[3] for r in raw]}
        tables["raw"] = [[r[0], fmt.pct_of(r[1]) if r[1] is not None else "–", fmt.pct_of(r[2]), fmt.pct_of(r[3])]
                         for r in raw]
        labels["raw_aria"] = f"אחוז היהודים ואחוז הערבים בכל מדד בתחום {labels['raw_domain']}"
        big = max(raw, key=lambda r: (abs(r[2] - r[3]), r[0]))
        add("raw", f"בתחום {labels['raw_domain']}, ההפרש הגדול ביותר באחוזים הוא ב{big[0]}: "
                   f"{fmt.pct_of(big[2])} בקרב יהודים לעומת {fmt.pct_of(big[3])} בקרב ערבים.")

    # ── insights, lede, seo ──
    order = ["total", "lowest", "highest", "moves", "best", "worst", "summary_all", "raw", "domains",
             "summary_arabs"]
    insights = sorted(cands, key=lambda c: order.index(c["id"]))[:MAX_INSIGHTS]

    lede = ("הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) משווה בכל שנה בין יהודים לערבים במדדי איכות החיים. "
            "כל מדד מוצג כיחס בין מצב הערבים למצב היהודים: 1 הוא שוויון, ערך נמוך מ-1 פירושו שמצב היהודים "
            "ואחרים טוב יותר, וערך גבוה מ-1 פירושו שמצב הערבים טוב יותר.")
    if n:
        lede += f" בהודעה האחרונה {n} מדדים ב-{len(domains)} תחומים, רובם לשנת {labels['latest_year']}."
    labels["lede"] = lede

    if total:
        summ = (f"פערים בין יהודים לערבים ב-{n} מדדי איכות חיים של הלמ\"ס ({labels['latest_year']}): ב-{_pct(total[1])} "
                f"מהמדדים מצב היהודים ואחרים טוב יותר, ב-{_pct(total[3])} מצב הערבים טוב יותר. מגמות לכל תחום.")
    else:
        summ = (f"פערים בין יהודים לערבים ב-{n} מדדי איכות חיים של הלמ\"ס ({labels['latest_year']}), "
                f"לפי תחום, ומגמת כל פער לאורך השנים.")
    desc = (f"היחס בין יהודים לערבים ב-{n} מדדי איכות חיים: תעסוקה, בריאות, חינוך, דיור, ביטחון אישי "
            f"ועוד, נתוני הלמ\"ס {labels['latest_year']} ומגמות.")
    years_all = sorted({int(y) for t in trends for y in t["years"]} | set(snap_years))
    agent = {
        "summary_he": summ,
        "dataset_kind": "timeseries",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "פערים בין יהודים לערבים במדדי איכות חיים | הלמ\"ס",
            "description": desc,
            "name": "פערים בין יהודים לערבים במדדי איכות חיים",
            "alternate_names": [
                "פערים בין יהודים לערבים במדדי איכות חיים בישראל",
                "אי-שוויון בין יהודים לערבים",
                "מדדי איכות חיים יהודים וערבים",
                "פערים בין יהודים לערבים בישראל",
            ],
        },
    }
    if years_all:
        agent["temporal_coverage"] = f"{years_all[0]}/{years_all[-1]}"

    release = {
        "title": rel_title,
        "date": fmt.d_he(pd.Timestamp(str(rel["RELEASE_DATE"]))) if rel.get("RELEASE_DATE") else "",
        "headline": str(rel.get("HEADLINE") or ""),
        "url": str(rel.get("PAGE_URL") or ""),
        "pdf": str(rel.get("REPORT_PDF_URL") or ""),
    }
    return {
        "agent_data": agent,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "flags": flags,
        "labels": labels,
        "insights": insights,
        "release": release,
    }
