"""פערים בין גברים לנשים במדדי איכות חיים: CBS's yearly release comparing
men and women across the quality-of-life indicators.

The release is a set of chart-data sheets ("תרשים N - ..."). One edition
holds everything the page needs: the trend sheets carry each ratio's full
series (2002 onward), so the source reads only the newest edition
(`history_releases: 1`). Chart NUMBERS MOVE between editions (the overall
ratio list was chart 1, then chart 1 of a different layout, then chart 23),
so every table input (t1..t26, the last three spare, all optional) is
identified by its TITLE, never by its stem:

  summary   סיכום הפערים ... לפי תחום          share of indicators per domain:
                                               men better / equal / women better
  snapshot  פערים בין גברים לנשים בתחום X, YYYY ratio per indicator (left block)
                                               + total / men / women values
  trend     מגמות בפערים ... בתחום X / במדד X  ratio series by year
  overall   יחס בין המינים במדדי איכות חיים    every ratio, capped at 2 for
                                               display: not read (the snapshot
                                               sheets hold the same ratios uncapped)

The ratio is CBS's: women's value over men's, inverted for indicators where
lower is better, so a ratio above 1 always means women's situation is better.

A sheet missing from the edition drops its section. A recognised sheet whose
header labels are gone raises (the layout changed: a human should look).
"""
import math
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^תרשים\s*\d+[א-ת]?\s*-\s*")
HEB = re.compile("[א-ת]")
STEM = re.compile(r"t\d+")
YEAR4 = re.compile(r"((?:19|20)\d\d)")
SNAP = re.compile(r"פערים בין (?:גברים לנשים|נשים לגברים) בתחום (.+?),\s*((?:19|20)\d\d)\s*$")
TREND = re.compile(r"מגמות בפערים בין (?:גברים לנשים|נשים לגברים) (?:בתחום|במדד) (.+?),\s*(?:19|20)\d\d")
HEAD_N = re.compile(r"נתוניהם של (\d+) מדדים")
# Ratios within this distance of 1 are drawn as "close to equality" (CBS's
# own classification in the summary sheet puts 0.98-1.02 there and 0.96 out).
NEAR = 0.03
# Bars per side in the "largest gaps" chart.
GAPS_N = 6
# Trend charts: (key, word in the domain name), in page order.
TRENDS = (("work", "תעסוקה"), ("edu", "חינוך"), ("security", "ביטחון אישי"),
          ("welfare", "רווחה אישית"), ("ict", "טכנולוגי"))
# A ratio move smaller than this between the first and last year is "stable".
FLAT_R = 0.02
MAX_INSIGHTS = 8


# ── sheets ──────────────────────────────────────────────────────────────


def _int(v):
    try:
        return int(str(v).strip())
    except ValueError:
        return 0


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return TITLE.sub("", c).strip()
    return ""


def _kind(t):
    if "סיכום" in t and "לפי תחום" in t:
        return "summary"
    if TREND.search(t):
        return "trend"
    if SNAP.search(t):
        return "snapshot"
    if "יחס בין המינים" in t:
        return "overall"
    return None


def _sheets(frames):
    """[(kind, title, rows)] over every non-empty table input, in stem order."""
    out = []
    names = sorted((n for n in frames if STEM.fullmatch(n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        t = _title(rows)
        k = _kind(t)
        if k:
            out.append((k, t, rows))
    return out


def _label(c):
    return bool(c) and bool(HEB.search(c)) and not TITLE.match(c) and not c.startswith(("(", "מקור"))


def _r2(v):
    return None if v is None else round(v, 2)


def _r3(v):
    return None if v is None else round(v, 3)


def _num(v, d=1):
    return "–" if v is None else fmt.num_he(v, d)


def _ratio(v):
    return "–" if v is None else fmt.num_he(v, 2)


def _norm(s):
    s = s.replace('"', "").replace("״", "").replace("-", " ").replace("(", " ").replace(")", " ")
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s):
    return set(_norm(s).split())


# ── parsers ─────────────────────────────────────────────────────────────


def _summary(rows):
    h = cbs.row_with(rows, "תחום", name="summary")
    hr = rows[h]
    men = cbs.col_after(hr, "גברים", contains=True)
    eq = cbs.col_after(hr, "שוויון", contains=True)
    wom = cbs.col_after(hr, "נשים טוב", contains=True)
    lab = cbs.col_after(hr, "תחום")
    out = []
    for r in rows[h + 1:]:
        name = cbs.cell(r, lab)
        if not _label(name):
            continue
        m, e, w = cbs.val(r, men), cbs.val(r, eq), cbs.val(r, wom)
        if m is None and e is None and w is None:
            continue
        out.append({"name": name, "men": m, "eq": e, "women": w})
    return out


def _snapshot(rows, name):
    """(ratios [(label, ratio)], values [(label, total, men, women)])."""
    ratios = []
    for r in rows:
        lab, v = cbs.cell(r, 0), cbs.val(r, 1)
        if _label(lab) and v is not None and v > 0:
            ratios.append((lab, v))
    values = []
    h = None
    for i, r in enumerate(rows):
        if "גברים" in r and "נשים" in r:
            h = i
            break
    if h is not None:
        hr = rows[h]
        men, wom = hr.index("גברים"), hr.index("נשים")
        tot = None
        for j in range(men - 1, -1, -1):
            if hr[j] in ('סה"כ', "סך הכל"):
                tot = j
                break
        lab = (tot if tot is not None else men) - 1
        for r in rows[h + 1:]:
            lb = cbs.cell(r, lab)
            m, w = cbs.val(r, men), cbs.val(r, wom)
            if _label(lb) and (m is not None or w is not None):
                values.append((lb, cbs.val(r, tot) if tot is not None else None, m, w))
    # No men/women header: the values block sits low in the sheet and may be
    # cut off; the ratios alone still describe the domain.
    return ratios, values


def _transposed(rows):
    """The single-indicator block laid out downwards (economic satisfaction):
    a header row "<year> | <indicator>", then rows "גברים | v" / "נשים | v"."""
    pos = {}
    for i, r in enumerate(rows):
        for j, c in enumerate(r):
            if c in ("סך הכל", 'סה"כ', "גברים", "נשים") and cbs.val(r, j + 1) is not None:
                pos.setdefault(c.replace('סה"כ', "סך הכל"), (i, j))
    if "גברים" not in pos or "נשים" not in pos:
        return None
    i0, j0 = pos["גברים"]
    lab = None
    for i in range(i0 - 1, -1, -1):
        if YEAR4.fullmatch(cbs.cell(rows[i], j0)) and _label(cbs.cell(rows[i], j0 + 1)):
            lab = cbs.cell(rows[i], j0 + 1)
            break
    if lab is None:
        return None

    def v(k):
        if k not in pos:
            return None
        i, j = pos[k]
        return cbs.val(rows[i], j + 1)

    return (lab, v("סך הכל"), v("גברים"), v("נשים"))


def _trend(rows, name):
    """(years, [(label, {year: ratio})])."""
    h = None
    for i, r in enumerate(rows):
        if sum(1 for c in r if cbs.YEAR.match(c)) >= 3:
            h = i
            break
    if h is None:
        raise ValueError(f"{name}: year header row not found")
    ycols = {j: int(c) for j, c in enumerate(rows[h]) if cbs.YEAR.match(c)}
    series = []
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        if not _label(lab):
            continue
        pts = {y: cbs.val(r, j) for j, y in ycols.items()}
        pts = {y: v for y, v in pts.items() if v is not None and v > 0}
        if pts:
            series.append((lab, pts))
    years = sorted({y for _, p in series for y in p})
    return years, series


def _match(label, values, used):
    """The value row for a ratio label: same normalized text, one inside the
    other, or the best word overlap (Jaccard >= 0.5)."""
    n = _norm(label)
    best, score = None, 0.0
    for k, row in enumerate(values):
        if k in used:
            continue
        m = _norm(row[0])
        if m == n:
            return k
        if m in n or n in m:
            s = 0.9
        else:
            a, b = _tokens(label), _tokens(row[0])
            s = len(a & b) / len(a | b) if a | b else 0.0
        if s > score:
            best, score = k, s
    return best if score >= 0.5 else None


# ── compute ─────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    sheets = _sheets(frames)
    if not sheets:
        raise ValueError("no gender-gap chart recognised in any table")

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    cands = []

    def add(iid, text):
        if text:
            cands.append({"id": iid, "text_he": text})

    # report year: the summary title, else the newest snapshot year
    year = None
    snaps = []
    summ = None
    trends = []
    for kind, t, rows in sheets:
        if kind == "summary" and summ is None:
            summ = _summary(rows)
            m = YEAR4.findall(t)
            if m:
                year = int(m[-1])
        elif kind == "snapshot":
            m = SNAP.search(t)
            snaps.append((m.group(1).strip(), int(m.group(2)), rows, t))
        elif kind == "trend":
            m = TREND.search(t)
            trends.append((m.group(1).strip(), rows, t))
    if year is None and snaps:
        year = max(s[1] for s in snaps)
    if year is None:
        raise ValueError("report year not found")
    ys = str(year)

    # ── indicators: ratio + men/women values, by domain ──
    domains = []
    for dom, _y, rows, t in snaps:
        ratios, values = _snapshot(rows, t)
        if not ratios and not values:
            continue
        used = set()
        items = []
        for lab, r in ratios:
            k = _match(lab, values, used)
            row = values[k] if k is not None else (lab, None, None, None)
            if k is not None:
                used.add(k)
            # the values block names the unit when it isn't a percent ("(אלפים)")
            shown = row[0] if "(" in row[0] else lab
            items.append({"label": lab, "shown": shown, "ratio": r, "total": row[1], "men": row[2],
                          "women": row[3]})
        for k, row in enumerate(values):
            if k not in used:
                items.append({"label": row[0], "shown": row[0], "ratio": None, "total": row[1],
                              "men": row[2], "women": row[3]})
        domains.append({"name": dom, "items": items})
    # single-indicator trend sheets with a downward values block (economic satisfaction)
    for dom, rows, t in trends:
        if any(dom == d["name"] for d in domains):
            continue
        tv = _transposed(rows)
        if not tv:
            continue
        _yrs, ser = _trend(rows, t)
        last = None
        for lab, pts in ser:
            if _norm(lab) == _norm(tv[0]) and pts:
                last = pts[max(pts)]
        domains.append({"name": dom, "items": [{"label": tv[0], "shown": tv[0], "ratio": last, "total": tv[1],
                                                "men": tv[2], "women": tv[3]}]})
    if not domains:
        raise ValueError("no domain snapshot sheet parsed")
    domains.sort(key=lambda d: d["name"])

    allr = [(it["label"], it["ratio"], d["name"]) for d in domains for it in d["items"] if it["ratio"] is not None]
    n_ind = len(allr)
    if n_ind == 0:
        raise ValueError("no ratio parsed")

    flags["domains"] = True
    tables["domains"] = [{"name": d["name"],
                          "rows": [[it["shown"], _ratio(it["ratio"]), _num(it["men"]), _num(it["women"]),
                                    _num(it["total"])] for it in d["items"]]}
                         for d in domains]

    def find(word, dom_word=None):
        for d in domains:
            if dom_word and dom_word not in d["name"]:
                continue
            for it in d["items"]:
                if word in it["label"] and it["men"] is not None and it["women"] is not None:
                    return it
        return None

    # ── summary by domain ──
    tot = None
    if summ:
        body = [s for s in summ if s["name"] not in ("סך הכל", 'סה"כ')]
        tot = next((s for s in summ if s["name"] in ("סך הכל", 'סה"כ')), None)
        if body:
            body.sort(key=lambda s: (-(s["women"] or 0), (s["men"] or 0), s["name"]))
            flags["summary"] = True

            def p(v):
                return None if v is None else round(v * 100, 1)

            charts["summary"] = {"x": [s["name"] for s in body], "men": [p(s["men"]) for s in body],
                                 "eq": [p(s["eq"]) for s in body], "women": [p(s["women"]) for s in body]}
            tables["summary"] = [[s["name"], _pct(s["men"]), _pct(s["eq"]), _pct(s["women"])] for s in body]
            labels["summary_aria"] = (f"תרשים עמודות נערמות: חלוקת המדדים בכל תחום לפי כיוון הפער בין גברים "
                                      f"לנשים, {ys}")
            wtop = max(body, key=lambda s: ((s["women"] or 0), s["name"]))
            mtop = max(body, key=lambda s: ((s["men"] or 0), s["name"]))
            if (wtop["women"] or 0) >= 0.5 and (mtop["men"] or 0) >= 0.5:
                add("domain", f"התחום שבו מצב הנשים טוב יותר בחלק הגדול ביותר של המדדים הוא {wtop['name']} "
                    f"({_pct(wtop['women'])} מהמדדים), והתחום שבו מצב הגברים טוב יותר בחלק הגדול ביותר "
                    f"הוא {mtop['name']} ({_pct(mtop['men'])}).")
        if tot and None not in (tot["men"], tot["eq"], tot["women"]):
            kpis["men"] = {"value": round(tot["men"] * 100, 1), "display": _pct(tot["men"]), "tone": "info"}
            kpis["eq"] = {"value": round(tot["eq"] * 100, 1), "display": _pct(tot["eq"]), "tone": "brand"}
            kpis["women"] = {"value": round(tot["women"] * 100, 1), "display": _pct(tot["women"]), "tone": "info"}
            add("overall", f"בשנת הדיווח האחרונה ({ys}) מצב הגברים טוב יותר ב-{_pct(tot['men'])} מהמדדים, "
                f"מצב הנשים טוב יותר ב-{_pct(tot['women'])}, וב-{_pct(tot['eq'])} אין פער של ממש בין "
                "המינים, לפי סיווג הלמ\"ס.")

    hm = HEAD_N.search(str(rel.get("HEADLINE") or ""))
    n_head = int(hm.group(1)) if hm else None
    kpis["indicators"] = {"value": n_head or n_ind, "display": f"{n_head or n_ind:,}", "tone": "brand"}
    labels["indicators_kpi"] = ("מדדי איכות חיים עם השוואה בין גברים לנשים" if n_head
                                else "מדדים בעמוד עם יחס בין גברים לנשים")

    # ── largest gaps ──
    def lg(r):
        return abs(math.log2(r))

    menside = sorted([a for a in allr if a[1] < 1 - NEAR], key=lambda a: (-lg(a[1]), a[0]))[:GAPS_N]
    womside = sorted([a for a in allr if a[1] > 1 + NEAR], key=lambda a: (-lg(a[1]), a[0]))[:GAPS_N]
    gaps = sorted(menside + womside, key=lambda a: (a[1], a[0]))
    if len(gaps) >= 2:
        flags["gaps"] = True
        charts["gaps"] = {"x": [a[0] for a in gaps], "y": [_r2(a[1]) for a in gaps],
                          "domain": [a[2] for a in gaps], "near": NEAR}
        tables["gaps"] = [[a[0], a[2], _ratio(a[1])] for a in gaps]
        labels["gaps_aria"] = (f"תרשים עמודות: {len(gaps)} המדדים עם הפער הגדול ביותר בין גברים לנשים, "
                               f"יחס על סולם לוגריתמי, {ys}")
    if menside and womside:
        m0, w0 = menside[0], womside[0]
        add("gaps", f"היחס הנמוך ביותר, כלומר הפער הגדול ביותר לטובת גברים, הוא במדד {m0[0]} "
            f"({_ratio(m0[1])}), והגבוה ביותר, פער לטובת נשים, במדד {w0[0]} ({_ratio(w0[1])}).")

    # ── trends ──
    tlist = []
    for key, word in TRENDS:
        hit = next(((d, rows, t) for d, rows, t in trends if word in d), None)
        if not hit:
            continue
        dom, rows, t = hit
        years, ser = _trend(rows, t)
        ser = [(lab, pts) for lab, pts in ser if len(pts) >= 2]
        if not ser or len(years) < 2:
            continue
        x = [str(y) for y in years]
        tlist.append({
            "key": key, "domain": dom,
            "title": f"מגמות בפערים בתחום {dom}",
            "aria": f"תרשים קווים: היחס בין נשים לגברים במדדי תחום {dom}, {years[0]}-{years[-1]}",
            "chart": {"x": x, "series": [{"name": lab, "data": [_r3(pts.get(y)) for y in years]}
                                         for lab, pts in ser]},
            "cols": ["שנה"] + [lab for lab, _ in ser],
            "rows": [[str(y)] + [_ratio(pts.get(y)) for _, pts in ser] for y in reversed(years)],
            "span": f"{years[0]}-{years[-1]}",
            "series": ser,
        })
    flags["trends"] = bool(tlist)

    # work: employment rate
    tw = next((t for t in tlist if t["key"] == "work"), None)
    emp = find("שיעור התעסוקה")
    if tw:
        s = next(((lab, pts) for lab, pts in tw["series"] if "שיעור התעסוקה" in lab), None)
        if s and emp:
            pts = s[1]
            y0, y1 = min(pts), max(pts)
            r0, r1 = pts[y0], pts[y1]
            if abs(r1 - r0) < FLAT_R:
                move = f"והיחס ביניהם כמעט לא השתנה מאז {y0} ({_ratio(r0)})"
            elif r1 > r0:
                move = f"היחס בין שיעור התעסוקה של נשים לזה של גברים עלה מ-{_ratio(r0)} ב-{y0} ל-{_ratio(r1)} ב-{y1}"
            else:
                move = f"היחס בין שיעור התעסוקה של נשים לזה של גברים ירד מ-{_ratio(r0)} ב-{y0} ל-{_ratio(r1)} ב-{y1}"
            add("work", f"שיעור התעסוקה של נשים עמד ב-{ys} על {_pp(emp['women'])}, לעומת {_pp(emp['men'])} "
                f"בקרב גברים; {move}.")
    inc = find("שביעות רצון מהכנסה")
    if inc and inc["men"] - inc["women"] >= 3:
        add("income", f"{_pp(inc['women'])} מהנשים המועסקות מרוצות מההכנסה מעבודתן, לעומת "
            f"{_pp(inc['men'])} מהגברים המועסקים ({ys}).")

    edu = find("זכאות לבגרות בקרב")
    if edu and abs(edu["women"] - edu["men"]) >= 3:
        hi, lo = ("נשים", "גברים") if edu["women"] > edu["men"] else ("גברים", "נשים")
        add("edu", f"שיעור הזכאות לבגרות בקרב בני 26 הוא {_pp(max(edu['women'], edu['men']))} בקרב {hi}, "
            f"לעומת {_pp(min(edu['women'], edu['men']))} בקרב {lo} ({ys}).")
    math5 = find("חמש יחידות")
    if math5 and math5["men"] - math5["women"] >= 2:
        add("math5", f"בבגרות במתמטיקה ברמת חמש יחידות התמונה הפוכה: {_pp(math5['men'])} מהגברים לעומת "
            f"{_pp(math5['women'])} מהנשים ({ys}).")

    lone = find("בדידות")
    if lone and abs(lone["women"] - lone["men"]) >= 3:
        hi, lo = ("נשים", "גברים") if lone["women"] > lone["men"] else ("גברים", "נשים")
        add("lonely", f"על תחושת בדידות דיווחו {_pp(max(lone['women'], lone['men']))} מה{hi}, "
            f"לעומת {_pp(min(lone['women'], lone['men']))} מה{lo} ({ys}).")

    life = find("תוחלת חיים")
    if life and abs(life["women"] - life["men"]) >= 1:
        add("life", f"תוחלת החיים של נשים היא {fmt.num_he(life['women'], 1)} שנים, לעומת "
            f"{fmt.num_he(life['men'], 1)} שנים אצל גברים ({ys}).")

    ti = next((t for t in tlist if t["key"] == "ict"), None)
    if ti:
        s = next(((lab, pts) for lab, pts in ti["series"] if "ICT" in lab or "טכנולוגיית המידע" in lab), None)
        if s:
            pts = s[1]
            y0, y1 = min(pts), max(pts)
            word = ("כמעט לא השתנה" if abs(pts[y1] - pts[y0]) < FLAT_R
                    else "ירד" if pts[y1] < pts[y0] else "עלה")
            add("ict", f"בענף טכנולוגיות המידע והתקשורת היחס בין נשים לגברים בשיעור המועסקים {word}: "
                f"{_ratio(pts[y0])} ב-{y0} ו-{_ratio(pts[y1])} ב-{y1}.")

    order = ("overall", "domain", "work", "gaps", "edu", "math5", "income", "ict", "lonely", "life")
    insights = sorted(cands, key=lambda i: order.index(i["id"]) if i["id"] in order else len(order))
    insights = insights[:MAX_INSIGHTS]

    # trend ledes
    for t in tlist:
        moves = []
        for lab, pts in t["series"]:
            y0, y1 = min(pts), max(pts)
            moves.append((abs(pts[y1] - pts[y0]), lab, pts[y0], pts[y1], y0, y1))
        moves.sort(key=lambda m: (-m[0], m[1]))
        d, lab, a, b, y0, y1 = moves[0]
        t["lede"] = (f"היחס בין נשים לגברים בכל מדד בתחום, לפי שנה ({t['span']}). "
                     + (f"השינוי הגדול ביותר: {lab}, מ-{_ratio(a)} ב-{y0} ל-{_ratio(b)} ב-{y1}."
                        if d >= FLAT_R else "היחסים כמעט לא השתנו לאורך התקופה."))
        del t["series"]
    charts["trends"] = tlist

    # ── release card, lede, SEO ──
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["year"] = ys
    labels["ratio_note"] = ("בכל מדד הלמ\"ס מחשבת יחס בין מצבן של נשים למצבם של גברים, כך שיחס גבוה מ-1 "
                            "פירושו פער לטובת נשים ויחס נמוך מ-1 פירושו פער לטובת גברים. במדד שבו ערך נמוך "
                            "טוב יותר (למשל היפגעות מאלימות או עישון) היחס הפוך: ערך הגברים חלקי ערך הנשים. "
                            "יחס של 1 הוא שוויון.")
    labels["gaps_note"] = (f"עד {GAPS_N} המדדים בכל כיוון שבהם היחס בין נשים לגברים רחוק ביותר מ-1 (סולם "
                           "לוגריתמי: יחס של 2 ויחס של 0.5 רחוקים מהשוויון באותה מידה). עמודה ימינה: פער "
                           "לטובת נשים; שמאלה: פער לטובת גברים.")
    labels["near_low"] = fmt.num_he(1 - NEAR, 2)
    labels["near_high"] = fmt.num_he(1 + NEAR, 2)
    labels["domains_n"] = str(len(domains))
    labels["lede"] = (f"איפה מצבן של נשים בישראל טוב יותר ואיפה מצבם של גברים, ב-{len(domains)} תחומי איכות "
                      "חיים: תעסוקה, ביטחון אישי, בריאות, חינוך, מעורבות אזרחית, רווחה אישית ועוד. "
                      "הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על פערים בין גברים "
                      f"לנשים במדדי איכות חיים, שנת דיווח {ys}"
                      + (f". מצב הגברים טוב יותר ב-{_pct(tot['men'])} מהמדדים, ומצב הנשים ב-{_pct(tot['women'])}."
                         if tot and tot["men"] is not None and tot["women"] is not None else "."))
    yrs_all = sorted({int(y) for t in tlist for y in t["chart"]["x"]})
    summary = (f"פערים בין גברים לנשים במדדי איכות חיים של הלמ\"ס, {ys}: "
               + (f"מצב הגברים טוב יותר ב-{_pct(tot['men'])} מהמדדים ומצב הנשים ב-{_pct(tot['women'])}. "
                  if tot and tot["men"] is not None and tot["women"] is not None else "")
               + "תעסוקה, השכלה, בריאות, ביטחון אישי ורווחה, ומגמות הפער לאורך השנים.")
    desc = (f"פערים בין גברים לנשים בישראל ב-{len(domains)} תחומי איכות חיים ({ys}): "
            + (f"מצב הגברים טוב יותר ב-{_pct(tot['men'])} מהמדדים, הנשים ב-{_pct(tot['women'])}. "
               if tot and tot["men"] is not None and tot["women"] is not None else "")
            + "תעסוקה, השכלה ובריאות.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "misc",
        "temporal_coverage": f"{yrs_all[0]}/{year}" if yrs_all and yrs_all[0] < year else ys,
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "פערים בין גברים לנשים במדדי איכות חיים בישראל",
            "description": desc,
            "name": "פערים בין גברים לנשים במדדי איכות חיים",
            "alternate_names": ["פערי מגדר בישראל", "שוויון מגדרי במדדי איכות חיים",
                                "פערים בין נשים לגברים", "מדדי איכות חיים לפי מין"],
        },
    }
    return {"agent_data": agent_data, "kpis": kpis, "charts": charts, "insights": insights,
            "labels": labels, "tables": tables, "flags": flags, "release": release}


def _pct(fraction):
    return "–" if fraction is None else fmt.num_he(fraction * 100, 1) + "%"


def _pp(v):
    return "–" if v is None else fmt.num_he(v, 1) + "%"
