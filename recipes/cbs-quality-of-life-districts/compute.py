"""מדדי איכות חיים במחוזות: CBS's yearly release comparing Israel's seven
districts on its quality-of-life indicators.

Each edition is a cross-section of ONE year (`history_releases: 1`). Two
kinds of chart-data sheets, both found by content, never by stem (CBS
renumbers and reorders them between editions):

  profile    one sheet per district: a header row with the year, the
             district's name and "ממוצע ארצי", then one row per indicator
             with the district's value as a ratio to the national average
             (the average column is 1). CBS orients every ratio so that
             above 1 is better than average: for "negative" indicators
             (long-term unemployment, murders, housing cost) the ratio is
             average / district. Checked against the headline sheets: murders
             in Tel Aviv 0.7 vs 1.9 nationally → profile ratio 2.71.
  headline   a few sheets of absolute values by district (topics change
             every year: employment, murders, trust, volunteering, ...),
             one or more value columns, the national figure as a
             "ממוצע ארצי" column or a "סה"כ" row.

The 2025 edition's profile sheets mostly repeated 2022 data under the 2023
titles, so profiles whose year is older than the newest profile year are
dropped as stale (and editions are not chained).
"""
import re

import pandas as pd
from govlib import cbs, fmt

STEM = re.compile(r"t\d+")
YEAR = re.compile(r"^(?:19|20)\d\d$")
HEB = re.compile("[א-ת]")
TITLE_PREFIX = re.compile(r"^תרשים\s*\d+[א-ת]?\s*-\s*")
TITLE_YEAR = re.compile(r",?\s*((?:19|20)\d\d)\s*$")
BY_DISTRICT = re.compile(r",?\s*לפי\s+מחוז(?:ות)?\s*,?")
GENERIC_SHEET = re.compile(r"^(?:תרשים|גיליון|גליון|sheet|לוח)\s*\d*$", re.IGNORECASE)
BANNER = ("הלשכה המרכזית", "פורסם", "Central Bureau", "Published")
NATIONAL_ROW = ('סה"כ', "סך הכל", "כלל הארץ", "ממוצע ארצי", "ישראל")
AVG = "ממוצע ארצי"
# Known district spellings → the short name the page uses. A row label that
# starts with "מחוז" but is not listed still counts (new names flow through).
DISTRICTS = {
    "ירושלים": "ירושלים", "הצפון": "הצפון", "צפון": "הצפון", "חיפה": "חיפה",
    "המרכז": "המרכז", "מרכז": "המרכז", "תל אביב": "תל אביב", "תל אביב-יפו": "תל אביב",
    "הדרום": "הדרום", "דרום": "הדרום", "יהודה והשומרון": "יהודה ושומרון",
    "יהודה ושומרון": "יהודה ושומרון", 'יו"ש': "יהודה ושומרון",
}
JS = "יהודה ושומרון"
# Two spellings of one indicator across the district sheets.
ALIASES = {"יכולת השפעה על מדיניות": "יכולת להשפיע על מדיניות הממשלה"}
# A ratio within this distance of 1 counts as "close to the average".
TOL = 0.05
GAP_TOP = 12
PROFILE_TOP = 3


# ── labels ──────────────────────────────────────────────────────────────


def _district(label):
    s = cbs.clean(label)
    if not s:
        return None
    core = re.sub(r"^(?:מחוז|אזור)\s+", "", s).strip()
    if core in DISTRICTS:
        return DISTRICTS[core]
    if s.startswith("מחוז ") and HEB.search(core) and len(core) <= 20:
        return core
    return None


def in_d(d):
    """"במחוז ירושלים" / "באזור יהודה והשומרון"."""
    return "באזור יהודה והשומרון" if d == JS else f"במחוז {d}"


def full_d(d):
    return "אזור יהודה והשומרון" if d == JS else f"מחוז {d}"


def _label(s):
    s = cbs.clean(s)
    s = ALIASES.get(s, s)
    # CBS abbreviates "שביעות רצון" in the district sheets.
    return re.sub(r'^ש"ר\s+', "שביעות רצון ", s)


def _i(r):
    """A ratio as an index (national average = 100), rounded half up."""
    return None if r is None else int(r * 100 + 0.5)


# ── sheets ──────────────────────────────────────────────────────────────


def _grids(frames):
    names = sorted((n for n in frames if STEM.fullmatch(n)), key=lambda n: int(n[1:]))
    out = []
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        out.append((n, cbs.grid(df, n), str(df["SHEET"].iloc[0]) if "SHEET" in df else ""))
    return out


def _profile(rows, name):
    """(year, district, [(label, ratio)]) or None when the sheet is not a
    district profile."""
    for h, r in enumerate(rows):
        if AVG not in r:
            continue
        ac = r.index(AVG)
        yc = next((j for j, c in enumerate(r) if YEAR.match(c)), None)
        dc = next((j for j, c in enumerate(r) if j != ac and _district(c)), None)
        if yc is None or dc is None:
            continue
        items = []
        for row in rows[h + 1:]:
            if cbs.val(row, ac) != 1:
                continue
            lab = _label(cbs.cell(row, yc))
            if not lab or not HEB.search(lab) or cbs.num(lab) is not None:
                continue
            items.append((lab, cbs.val(row, dc)))
        if not items:
            raise ValueError(f"{name}: district profile header without indicator rows")
        return int(r[yc]), _district(r[dc]), items
    return None


def _clean_title(t):
    t = TITLE_PREFIX.sub("", cbs.clean(t))
    t = re.sub(r"\s*,\s*", ", ", t)
    t = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", t))
    year = None
    m = TITLE_YEAR.search(t)
    if m:
        year = int(m.group(1))
        t = t[:m.start()]
    t = BY_DISTRICT.sub(",", t)
    t = re.sub(r"\s*,\s*,\s*", ", ", t).strip(" ,")
    return t, year


def _headline(rows, sheet, name):
    """A table of absolute values by district, or None."""
    data = []  # (row index, label col, district or None for the national row)
    for i, r in enumerate(rows):
        for j, c in enumerate(r):
            d = _district(c)
            nat = cbs.clean(c) in NATIONAL_ROW and c != AVG
            if (d or nat) and any(cbs.num(x) is not None for x in r[j + 1:]):
                data.append((i, j, d))
                break
    dist = [x for x in data if x[2]]
    if len({x[2] for x in dist}) < 3:
        return None
    lc = max({x[1] for x in dist}, key=lambda j: (sum(1 for x in dist if x[1] == j), -j))
    data = [x for x in data if x[1] == lc]
    first = min(x[0] for x in data)
    width = max(len(rows[x[0]]) for x in data)
    vcols = [j for j in range(lc + 1, width)
             if sum(1 for x in dist if cbs.val(rows[x[0]], j) is not None) * 2 >= len(dist)]
    if not vcols:
        return None
    head = {}
    for i in range(first - 1, -1, -1):
        cells = {j: cbs.cell(rows[i], j) for j in vcols}
        if any(v and cbs.num(v) is None for v in cells.values()):
            head = cells
            break
    avg = None
    series = []
    for j in vcols:
        lab = cbs.clean(head.get(j, ""))
        if lab == AVG:
            avg = next((cbs.val(rows[x[0]], j) for x in dist if cbs.val(rows[x[0]], j) is not None), None)
            continue
        series.append((j, lab))
    if not series:
        return None
    title = ""
    used = {lc, *vcols}
    for r in rows:
        for j, c in enumerate(r):
            c = cbs.clean(c)
            if (j not in used and len(c) >= 12 and HEB.search(c) and cbs.num(c) is None
                    and not any(b in c for b in BANNER) and c not in head.values()):
                title = c
                break
        if title:
            break
    if not title:
        for r in rows[:first]:
            c = next((cbs.clean(x) for x in r if TITLE_PREFIX.match(cbs.clean(x))), "")
            if c:
                title = c
                break
    if not title and sheet and not GENERIC_SHEET.match(cbs.clean(sheet)):
        title = cbs.clean(sheet)
    title, year = _clean_title(title) if title else ("", None)
    if len(series) == 1:
        if not title:
            title = series[0][1]
        series = [(series[0][0], title)]
    else:
        if any(not lab for _, lab in series):
            raise ValueError(f"{name}: a value column of a district table lost its header label")
        if not title:
            title = fmt.join_he([lab for _, lab in series])
    if not title:
        raise ValueError(f"{name}: district table without a title or header label")
    nat_row = next((x for x in data if x[2] is None), None)
    districts = []
    seen = set()
    for i, _, d in dist:
        if d in seen:
            continue
        seen.add(d)
        districts.append((d, [cbs.val(rows[i], j) for j, _ in series]))
    national = [cbs.val(rows[nat_row[0]], j) for j, _ in series] if nat_row else None
    if national is None and avg is not None and len(series) == 1:
        national = [avg]
    return {"title": title, "year": year, "names": [lab for _, lab in series],
            "districts": districts, "national": national}


# ── formatting ──────────────────────────────────────────────────────────


def _dec(values):
    """One decimal, as CBS prints most of these; two for small values that
    carry more (fatalities per 100 injured: 1.09)."""
    vs = [abs(v) for v in values if v is not None]
    if not vs or all(abs(v * 10 - round(v * 10)) < 1e-6 for v in vs):
        return 1
    return 2 if max(vs) < 5 else 1


def _n(v, d):
    return "–" if v is None else fmt.num_he(v, d)


def _r(v, d):
    return None if v is None else round(v, d)


# ── compute ─────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    grids = _grids(frames)
    profiles, heads = [], []
    for name, rows, sheet in grids:
        p = _profile(rows, name)
        if p:
            profiles.append(p)
            continue
        h = _headline(rows, sheet, name)
        if h:
            heads.append(h)
    if not profiles and not heads:
        raise ValueError("no district table recognised in any table input")

    kpis, charts, tables, labels, flags = {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # Profiles: the newest year only, one per district.
    year = None
    prof = {}
    if profiles:
        year = max(p[0] for p in profiles)
        for y, d, items in profiles:
            if y == year and d not in prof:
                prof[d] = dict(items)
    order_labels = []
    for y, d, items in profiles:
        if y == year:
            for lab, _ in items:
                if lab not in order_labels:
                    order_labels.append(lab)
    if year is None:
        year = max((h["year"] for h in heads if h["year"]), default=None)
    rel_year = None
    m = TITLE_YEAR.search(str(rel.get("TITLE") or ""))
    if m:
        rel_year = int(m.group(1))
    year = year or rel_year
    ystr = str(year) if year else ""
    labels["year"] = ystr

    dists = list(prof)
    n_ind = 0
    if len(dists) >= 2:
        flags["profiles"] = True
        score = {}
        for d in dists:
            vals = [v for v in prof[d].values() if v is not None]
            above = sum(1 for v in vals if v >= 1 + TOL)
            below = sum(1 for v in vals if v <= 1 - TOL)
            score[d] = (above, len(vals) - above - below, below, len(vals))
        dists.sort(key=lambda d: (-(score[d][0] / max(score[d][3], 1)), score[d][2] / max(score[d][3], 1), d))
        labs = [lab for lab in order_labels if sum(1 for d in dists if prof[d].get(lab) is not None) >= 2]
        n_ind = len(labs)
        charts["score"] = {"x": dists,
                           "above": [score[d][0] for d in dists],
                           "near": [score[d][1] for d in dists],
                           "below": [score[d][2] for d in dists]}
        tables["score"] = [[full_d(d), str(score[d][0]), str(score[d][1]), str(score[d][2]),
                            fmt.pct(score[d][0] / score[d][3], 0) if score[d][3] else "–"] for d in dists]
        heat = []
        for yi, lab in enumerate(labs):
            for xi, d in enumerate(dists):
                v = prof[d].get(lab)
                if v is not None:
                    heat.append([xi, yi, _i(v)])
        charts["heat"] = {"x": dists, "y": labs, "data": heat, "height": 120 + 22 * len(labs)}
        tables["heat"] = [[lab] + [str(_i(prof[d].get(lab))) if prof[d].get(lab) is not None else "–"
                                   for d in dists] for lab in labs]
        # Widest spread between districts (max / min ratio).
        gaps = []
        for lab in labs:
            vs = sorted(((prof[d][lab], d) for d in dists if prof[d].get(lab) is not None),
                        key=lambda t: (t[0], t[1]))
            lo_v, hi_v = vs[0][0], vs[-1][0]
            if lo_v > 0:
                # Districts that tie on the printed index are named together.
                lo = (lo_v, [d for v, d in vs if _i(v) == _i(lo_v)])
                hi = (hi_v, [d for v, d in vs if _i(v) == _i(hi_v)])
                gaps.append((hi_v / lo_v, lab, lo, hi))
        gaps.sort(key=lambda g: (-g[0], g[1]))
        top = gaps[:GAP_TOP]
        charts["gaps"] = {"y": [g[1] for g in top],
                          "lo": [_i(g[2][0]) for g in top], "hi": [_i(g[3][0]) for g in top],
                          "lo_d": [", ".join(g[2][1]) for g in top], "hi_d": [", ".join(g[3][1]) for g in top]}
        tables["gaps"] = [[g[1], f"{fmt.join_he(g[3][1])} ({_i(g[3][0])})",
                           f"{fmt.join_he(g[2][1])} ({_i(g[2][0])})",
                           fmt.num_he(g[0], 1)] for g in top]
        # District profile cards: strongest and weakest indicators.
        cards = []
        for d in dists:
            items = sorted(((v, lab) for lab, v in prof[d].items() if v is not None and lab in labs),
                           key=lambda t: (-t[0], t[1]))
            best = [{"label": lab, "v": _i(v)} for v, lab in items[:PROFILE_TOP] if v >= 1 + TOL]
            worst = [{"label": lab, "v": _i(v)} for v, lab in reversed(items[-PROFILE_TOP:]) if v <= 1 - TOL]
            cards.append({"name": full_d(d), "above": score[d][0], "below": score[d][2],
                          "n": score[d][3], "best": best, "worst": worst})
        charts["cards"] = cards

        lead, last = dists[0], dists[-1]
        la, _, lb, ln = score[lead]
        kpis["indicators"] = {"value": n_ind, "display": fmt.int_he(n_ind), "tone": "brand"}
        kpis["districts"] = {"value": len(dists), "display": fmt.int_he(len(dists)), "tone": "brand"}
        kpis["lead_share"] = {"value": round(la / ln, 3), "display": fmt.pct(la / ln, 0), "tone": "ok"}
        _, _, sb, sn = score[last]
        kpis["last_below"] = {"value": round(sb / sn, 3), "display": fmt.pct(sb / sn, 0),
                              "tone": "warn" if sb / sn >= 0.4 else "brand"}
        labels["lead"] = full_d(lead)
        labels["last"] = full_d(last)
        add("lead", f"{full_d(lead)} מוביל בהשוואה: ב-{la} מתוך {ln} מדדים ({fmt.pct(la / ln, 0)}) "
            f"מצבו טוב מהממוצע הארצי ביותר מ-{fmt.pct(TOL, 0)}, ורק ב-{lb} מדדים מצבו פחות טוב ממנו"
            f" ({ystr})." if la > score[dists[1]][0] or len(dists) == 2 else None)
        if sb > 0 and last != lead:
            add("last", f"מצבו של {full_d(last)} פחות טוב מהממוצע הארצי ביותר מ-{fmt.pct(TOL, 0)} ב-{sb} מתוך {sn} "
                f"מדדים ({fmt.pct(sb / sn, 0)}), השיעור הגבוה ביותר מבין המחוזות.")
        if top:
            _, lab, lo, hi = top[0]
            add("gap", f"הפער הגדול ביותר בין המחוזות הוא במדד \"{lab}\": מדד יחסי {_i(hi[0])} "
                f"{fmt.join_he([in_d(d) for d in hi[1]])} לעומת {_i(lo[0])} {fmt.join_he([in_d(d) for d in lo[1]])} (ממוצע ארצי = 100, וערך גבוה יותר "
                f"מציין מצב טוב יותר).")
        flat = [lab for lab in labs
                if all(abs(prof[d][lab] - 1) < TOL for d in dists if prof[d].get(lab) is not None)
                and sum(1 for d in dists if prof[d].get(lab) is not None) == len(dists)]
        if len(flat) >= 2:
            quoted = fmt.join_he(flat[:3])
            add("flat", f"ב-{len(flat)} מדדים כל המחוזות קרובים לממוצע הארצי (בטווח של {fmt.pct(TOL, 0)}), "
                f"ביניהם {quoted}.")
        # The lowest-ranked district's strongest point.
        lc = next((c for c in cards if c["name"] == full_d(last)), None)
        if lc and lc["best"] and last != lead:
            b = lc["best"][0]
            add("bright", f"גם {in_d(last)} יש מדדים שבהם המצב טוב מהממוצע, בראשם \"{b['label']}\" "
                f"(מדד יחסי {b['v']}).")
        labels["heat_aria"] = (f"מפת חום: {n_ind} מדדי איכות חיים ב-{len(dists)} מחוזות ביחס לממוצע הארצי, {ystr}")
        labels["score_aria"] = f"תרשים עמודות נערמות: מספר המדדים שבהם כל מחוז טוב, קרוב או פחות טוב מהממוצע, {ystr}"
        labels["gaps_aria"] = f"תרשים טווחים: {len(top)} המדדים עם הפער הגדול ביותר בין המחוזות, {ystr}"
        labels["tol"] = fmt.pct(TOL, 0)
        labels["n_ind"] = fmt.int_he(n_ind)
        labels["n_dist"] = fmt.int_he(len(dists))
        labels["gap_top"] = fmt.int_he(len(top))
        labels["heat_cols"] = ["מדד"] + dists
        labels["score_note"] = (f"לכל מחוז: בכמה מדדים מצבו טוב מהממוצע הארצי ביותר מ-{fmt.pct(TOL, 0)}, "
                                f"בכמה הוא קרוב לממוצע ובכמה מצבו פחות טוב ממנו ביותר מ-{fmt.pct(TOL, 0)} (סף של העמוד, לא של הלמ\"ס). "
                                f"המחוזות מסודרים לפי שיעור המדדים הטובים מהממוצע ({ystr}).")

    # Headline tables: absolute values.
    hs = []
    for k, h in enumerate(heads):
        names = h["names"]
        dd = sorted(h["districts"], key=lambda t: (-(t[1][0] if t[1][0] is not None else float("-inf")), t[0]))
        allv = [v for _, vs in dd for v in vs] + (h["national"] or [])
        dec = _dec(allv)
        hy = h["year"] or year
        single = len(names) == 1
        nat = h["national"]
        rows_c = ([("ממוצע ארצי", nat)] if nat and not single else []) + dd
        x = [d for d, _ in rows_c]
        series = [{"name": nm, "data": [_r(vs[s], dec) for _, vs in rows_c]} for s, nm in enumerate(names)]
        entry = {"id": f"chart-h{k + 1}", "title": h["title"], "single": single, "x": x,
                 "series": series, "dec": dec,
                 "avg": _r(nat[0], dec) if single and nat and nat[0] is not None else None,
                 "nat": [_r(v, dec) for v in nat] if nat and not single else None,
                 "aria": f"תרשים עמודות: {h['title']} לפי מחוז" + (f", {hy}" if hy else ""),
                 "cols": ["מחוז"] + names,
                 "rows": ([["ממוצע ארצי"] + [_n(v, dec) for v in nat]] if nat else [])
                 + [[full_d(d)] + [_n(v, dec) for v in vs] for d, vs in dd],
                 "h": "h-80 md:h-96" if not single else "h-72 md:h-80",
                 "year": str(hy) if hy else ""}
        known = [(vs[0], d) for d, vs in dd if vs[0] is not None]
        if len(known) >= 3:
            hi, lo = known[0], known[-1]
            hi_ds = fmt.join_he([in_d(d) for v, d in known if _n(v, dec) == _n(hi[0], dec)])
            lo_ds = fmt.join_he([in_d(d) for v, d in known if _n(v, dec) == _n(lo[0], dec)])
            note = (f"הערך הגבוה ביותר {hi_ds} ({_n(hi[0], dec)}) והנמוך ביותר {lo_ds} "
                    f"({_n(lo[0], dec)})")
            if nat and nat[0] is not None:
                note += f"; ממוצע ארצי {_n(nat[0], dec)}"
            entry["note"] = (f"{names[0] if not single else h['title']}: " + note + ".")
        else:
            entry["note"] = ""
        hs.append(entry)
    charts["heads"] = hs
    for e in hs[:2]:
        if e["note"]:
            add(f"head_{e['id']}", e["note"][:-1] + (f" ({e['year']})." if e["year"] else "."))
    if hs:
        flags["heads"] = True

    if not kpis and hs:
        kpis["tables"] = {"value": len(hs), "display": fmt.int_he(len(hs)), "tone": "brand"}

    release = {"no": str(rel.get("RELEASE_NO") or ""), "title": str(rel.get("TITLE") or ""),
               "date": fmt.d_he(pd.Timestamp(rel.get("RELEASE_DATE"))) if rel.get("RELEASE_DATE") else "",
               "url": str(rel.get("PAGE_URL") or ""), "pdf": str(rel.get("REPORT_PDF_URL") or ""),
               "headline": str(rel.get("HEADLINE") or "").strip()}

    nd = len(dists)
    if flags.get("profiles"):
        lede = (f"השוואה בין {nd} מחוזות ישראל ב-{n_ind} מדדי איכות חיים של הלשכה המרכזית לסטטיסטיקה "
                f"(הלמ\"ס) לשנת {ystr}: תעסוקה, ביטחון אישי, בריאות, דיור, השכלה, מעורבות אזרחית, סביבה "
                f"ורווחה אישית. כל מדד מוצג ביחס לממוצע הארצי (100), כך שערך מעל 100 מציין מצב טוב "
                f"מהממוצע. {full_d(dists[0])} מוביל במספר המדדים הטובים מהממוצע.")
        summary = (f"מדדי איכות חיים במחוזות לפי הלמ\"ס ({ystr}): {n_ind} מדדים ב-{nd} מחוזות ביחס לממוצע "
                   f"הארצי. {full_d(dists[0])} טוב מהממוצע ב-{fmt.pct(score[dists[0]][0] / score[dists[0]][3], 0)} "
                   f"מהמדדים.")
        desc = (f"השוואת {nd} מחוזות ישראל ב-{n_ind} מדדי איכות חיים של הלמ\"ס לשנת {ystr}: תעסוקה, "
                f"בריאות, דיור, ביטחון וסביבה. המוביל: {full_d(dists[0])}.")
    else:
        lede = ("מדדי איכות חיים לפי מחוז מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס)"
                + (f" לשנת {ystr}" if ystr else "") + ".")
        summary = lede
        desc = ("מדדי איכות חיים לפי מחוז מתוך ההודעה השנתית של הלמ\"ס" + (f" לשנת {ystr}" if ystr else "")
                + ": השוואה בין מחוזות ישראל בתעסוקה, בריאות, דיור וביטחון.")
    labels["lede"] = lede

    seo = {"title": "מדדי איכות חיים במחוזות: השוואה בין מחוזות ישראל",
           "description": desc,
           "name": "מדדי איכות חיים במחוזות",
           "alternate_names": ["מדדי איכות חיים לפי מחוז", "איכות חיים במחוזות ישראל",
                               "השוואת מחוזות בישראל", "מדדי איכות חיים בישראל לפי מחוזות"]}
    agent_data = {"summary_he": summary, "dataset_kind": "rankings", "spatial_coverage": "ישראל, לפי מחוז",
                  "seo": seo}
    if year:
        agent_data["temporal_coverage"] = str(year)

    return {"agent_data": agent_data, "kpis": kpis, "charts": charts, "tables": tables,
            "insights": insights, "labels": labels, "flags": flags, "release": release}
