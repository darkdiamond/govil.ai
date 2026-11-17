"""השקעות ישירות של ישראל בחו"ל ושל חו"ל בישראל: CBS's yearly release.

Each edition has 14 tables (plus chart excerpts) over two directions:
  in   תושבי חו"ל בישראל   (foreign direct investment in Israel)
  out  תושבי ישראל בחו"ל   (Israeli direct investment abroad)
two measures:
  pos  יתרות   (positions, end of year)
  flow תנועות  (transactions during the year)
and four breakdowns: by industry (ענפי כלכלה), by country (מדינה), by
technological intensity (עוצמה טכנולוגית) and, for positions in the last
year, country x industry group. Values are US$ millions, three years per
edition.

Table NUMBERS can move between editions, so every table input (t1..t23,
all optional) is read edition by edition and recognised by its TITLE and
header labels, never by its stem. Chart-excerpt sheets ("תרשים ...")
repeat the tables and are ignored.

`history_releases` is 4: the current edition (the newest in `releases`)
drives every section; the older editions add earlier years to the yearly
totals and the hi-tech share (for a year two editions share, the newer
edition wins, since later editions revise earlier figures).

A recognised table whose header labels are gone raises (layout change).
A table missing from the current edition drops its section. The inward
positions-by-industry table is required: the KPIs rest on its total.
"""
import re

from govlib import cbs, fmt

YEAR_H = re.compile(r"^((?:19|20)\d\d)\s*R?$")
REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
TITLE = re.compile(r"^לוח\s*\d+")
TOT_POS = 'סה"כ יתרות'
TOT_FLOW = 'סה"כ תנועות'
DIRS = ("in", "out")
DIR_HE = {"in": 'השקעות של חו"ל בישראל', "out": 'השקעות של ישראל בחו"ל'}
TOP_N = 10
FLOW_N = 8
CROSS_N = 8


# ── editions and table recognition ───────────────────────────────────────


def _rel_key(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _kind(rows):
    """(direction, measure, breakdown) of a CBS table grid, or None."""
    title = ""
    for r in rows[:6]:
        for c in r:
            if TITLE.match(c):
                title = c
                break
        if title:
            break
    if not title:
        return None
    if "תושבי ישראל" in title:
        d = "out"
    elif "תושבי חו" in title:
        d = "in"
    else:
        return None
    if "יתרות" in title:
        m = "pos"
    elif "תנועות" in title:
        m = "flow"
    else:
        return None
    cells = {c for r in rows[:8] for c in r}
    if "עוצמה טכנולוגית" in cells:
        b = "tech"
    elif any("ענף כלכלי מדינה" in c for c in cells) or ("מדינ" in title and "ענף" in title):
        b = "cross"
    elif "מדינה" in title or "מדינה" in cells:
        b = "country"
    elif "שם ענף" in cells or "ענף" in title or "ענפי" in title:
        b = "industry"
    else:
        return None
    return (d, m, b)


def _editions(frames):
    """{release_no: {(dir, measure, breakdown): rows}} over every table
    input; of two stems with the same kind in one edition, the lower stem
    wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        for rel in sorted(df["RELEASE_NO"].unique(), key=lambda r: (_rel_key(r), r)):
            rows = cbs.grid(df[df["RELEASE_NO"] == rel], f"{n} {rel}")
            k = _kind(rows)
            if k:
                out.setdefault(rel, {}).setdefault(k, rows)
    return out


# ── parsers ──────────────────────────────────────────────────────────────


def _years(rows, name):
    """(header row index, [(col, year, revised)])."""
    for i, r in enumerate(rows):
        ys = [(j, int(YEAR_H.match(c).group(1)), c.endswith("R")) for j, c in enumerate(r)
              if YEAR_H.match(c)]
        if len(ys) >= 2:
            return i, ys
    raise ValueError(f"{name}: year header row not found")


def _vals(r, ys):
    return {y: cbs.val(r, j) for j, y, _ in ys}


def _total_row(rows, start, label, name):
    for r in rows[start:]:
        if any(c == label for c in r):
            return r
    raise ValueError(f"{name}: total row {label!r} not found")


def _industry(rows, measure, name):
    h, ys = _years(rows, name)
    ncol = cbs.col_after(rows[h], "שם ענף", 0)
    ccol = cbs.col_after(rows[h], "קוד ענף", 0)
    total = _vals(_total_row(rows, h + 1, TOT_POS if measure == "pos" else TOT_FLOW, name), ys)
    items, groups = [], {}
    for r in rows[h + 1:]:
        label, code = cbs.cell(r, ncol), cbs.cell(r, ccol)
        if not label:
            continue
        if code and code != ".." and re.search(r"\d", code):
            items.append({"code": code, "name": label, "v": _vals(r, ys)})
        elif label.startswith('סה"כ תעשייה'):
            groups["manuf"] = _vals(r, ys)
        elif label.startswith('סה"כ מסחר ושירותים'):
            groups["serv"] = _vals(r, ys)
        elif label == "ענפים אחרים":
            groups["other"] = _vals(r, ys)
        elif label == "לא מחולק":
            groups["undiv"] = _vals(r, ys)
    return {"years": [y for _, y, _ in ys], "revised": [y for _, y, rv in ys if rv],
            "total": total, "items": items, "groups": groups}


CONTINENTS = ("אירופה", "אמריקה", "אסיה ואוקיאניה", "אפריקה")


def _continent(label):
    for c in CONTINENTS:
        if label.startswith('סה"כ ' + c) or (c == "אסיה ואוקיאניה" and label.startswith('סה"כ אסיה')):
            return c
    return None


def _country(rows, measure, name):
    h, ys = _years(rows, name)
    ncol = cbs.col_after(rows[h], "מדינה", 0)
    total = _vals(_total_row(rows, h + 1, TOT_POS if measure == "pos" else TOT_FLOW, name), ys)
    items, conts, undiv, oecd = [], {}, None, None
    for r in rows[h + 1:]:
        label = cbs.cell(r, ncol)
        if not label:
            continue
        code = next((c for c in r[:ncol] if re.fullmatch(r"\d{1,3}", c)), "")
        cont = _continent(label)
        if cont:
            conts[cont] = _vals(r, ys)
        elif label == "לא מחולק":
            undiv = _vals(r, ys)
        elif "OECD" in label:
            oecd = _vals(r, ys)
        elif code and "אחר" not in label:
            items.append({"code": code, "name": label, "v": _vals(r, ys)})
    return {"years": [y for _, y, _ in ys], "total": total, "items": items,
            "conts": conts, "undiv": undiv, "oecd": oecd}


TECH_ROWS = (
    ("hi_m", "תעשיות טכנולוגיה עילית"),
    ("mhi_m", "תעשיות טכנולוגיה מעורבת עילית"),
    ("mlo_m", "תעשיות טכנולוגיה מעורבת מסורתית"),
    ("lo_m", "תעשיות טכנולוגיה מסורתית"),
    ("hi_s", "ענפי היי טק בשירותים"),
    ("oth_s", "מסחר ושירותים אחרים"),
    ("other", "ענפים אחרים"),
    ("undiv", "לא מחולק"),
)


def _tech(rows, measure, name):
    h, ys = _years(rows, name)
    lcol = cbs.col_after(rows[h], "עוצמה טכנולוגית", 0)
    total = _vals(_total_row(rows, h + 1, TOT_POS if measure == "pos" else TOT_FLOW, name), ys)
    out = {"years": [y for _, y, _ in ys], "total": total, "parts": {}, "hitech": None}
    for r in rows[h + 1:]:
        label = cbs.cell(r, lcol)
        if label.startswith("מזה:") and "הייטק" in label.replace(" ", "").replace("-", ""):
            out["hitech"] = _vals(r, ys)
            continue
        for key, lab in TECH_ROWS:
            if label == lab:
                out["parts"][key] = _vals(r, ys)
    if out["hitech"] is None:
        raise ValueError(f"{name}: hi-tech row not found")
    return out


CROSS_COLS = (("manuf", "תעשייה"), ("serv", "שירותים"), ("other", "ענפים אחרים"),
              ("undiv", "לא מחולק"))


def _cross(rows, name):
    h = cbs.row_with(rows, "סה\"כ יתרות", name=name, contains=True)
    ncol = cbs.col_after(rows[h], "מדינה", 0, contains=True)
    cols = {k: cbs.col_after(rows[h], lab, 0, contains=True) for k, lab in CROSS_COLS}
    tcol = cbs.col_after(rows[h], 'סה"כ יתרות', 0, contains=True)
    title = next((c for r in rows[:6] for c in r if TITLE.match(c)), "")
    yrs = re.findall(r"(?:19|20)\d\d", title)
    items = []
    for r in rows[h + 1:]:
        label = cbs.cell(r, ncol)
        code = next((c for c in r[:ncol] if re.fullmatch(r"\d{1,3}", c)), "")
        if not label or not code or "אחר" in label:
            continue
        t = cbs.val(r, tcol)
        if t is None:
            continue
        items.append({"name": label, "total": t,
                      **{k: cbs.val(r, j) for k, j in cols.items()}})
    return {"year": int(yrs[-1]) if yrs else None, "items": items}


# ── formatting helpers ───────────────────────────────────────────────────


def _bn(v):
    return fmt.num_he(v / 1000, 1)


def _m(v):
    return "–" if v is None else (fmt.MINUS + fmt.int_he(-v) if v < 0 else fmt.int_he(v))


def _r0(v):
    return None if v is None else round(v)


def _short(name):
    s = name.split(",")[0].strip()
    return s if len(s) <= 30 else s[:28].rstrip() + "…"


def _change(a, b):
    """Relative change a → b, None when a is missing or not positive."""
    if a is None or b is None or a <= 0:
        return None
    return (b - a) / a


# ── model ────────────────────────────────────────────────────────────────


SHARE_TOL = 0.01  # 1 percentage point


def _history(eds, current, kind, total_key="total"):
    """{year: value} over every edition up to the current one, newest
    edition winning per year.

    For the hi-tech share an older edition is chained only while it agrees
    with the newer ones on every overlapping year (within SHARE_TOL): CBS
    reclassified the hi-tech industries between editions, and chaining an
    old-classification year onto the new series would show a jump that is
    only a definition change. The series starts at the first break."""
    out = {}
    ck = _rel_key(current)
    share = total_key == "hitech_share"
    for rel in sorted(eds, key=lambda r: (_rel_key(r), r), reverse=True):
        if _rel_key(rel) > ck or kind not in eds[rel]:
            continue
        rows = eds[rel][kind]
        try:
            parsed = _tech(rows, kind[1], f"{kind} {rel}") if kind[2] == "tech" else \
                _industry(rows, kind[1], f"{kind} {rel}")
        except ValueError:
            if rel == current:
                raise
            continue  # an older, incomplete edition adds nothing
        vals = {}
        for y in parsed["years"]:
            if share:
                t, hi = parsed["total"][y], parsed["hitech"][y]
                v = hi / t if t and hi is not None else None
            else:
                v = parsed[total_key][y]
            if v is not None:
                vals[y] = v
        if share and out:
            overlap = [y for y in vals if y in out]
            if not overlap or any(abs(vals[y] - out[y]) > SHARE_TOL for y in overlap):
                break  # classification break: older editions are not comparable
        for y, v in vals.items():
            out.setdefault(y, v)
    return out


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    current = str(rel["RELEASE_NO"]).strip()
    eds = _editions(frames)
    cur = eds.get(current, {})
    if ("in", "pos", "industry") not in cur:
        raise ValueError(f"{current}: inward positions by industry table not found")

    P = {}
    for (d, m, b), rows in cur.items():
        name = f"{d}-{m}-{b}"
        if b == "industry":
            P[(d, m, b)] = _industry(rows, m, name)
        elif b == "country":
            P[(d, m, b)] = _country(rows, m, name)
        elif b == "tech" and m == "pos":
            P[(d, m, b)] = _tech(rows, m, name)
        elif b == "cross" and m == "pos":
            P[(d, m, b)] = _cross(rows, name)

    base = P[("in", "pos", "industry")]
    Y = base["years"][-1]
    Y0 = base["years"][0]

    # yearly totals across editions
    hist = {}
    for d in DIRS:
        for m in ("pos", "flow"):
            if (d, m, "industry") in cur:
                hist[(d, m)] = _history(eds, current, (d, m, "industry"))
    hyears = sorted({y for h in hist.values() for y in h})
    hitech = {d: _history(eds, current, (d, "pos", "tech"), "hitech_share")
              for d in DIRS if (d, "pos", "tech") in cur}

    kpis, labels, charts, tables, flags, ins = {}, {}, {}, {}, {}, {}

    def tot(d, m, y=Y):
        p = P.get((d, m, "industry"))
        return p["total"].get(y) if p else None

    # ── KPIs
    in_pos, out_pos = tot("in", "pos"), tot("out", "pos")
    in_flow, out_flow = tot("in", "flow"), tot("out", "flow")
    if in_pos is None:
        raise ValueError(f"inward positions total for {Y} missing")
    kpis["in_pos"] = {"value": round(in_pos), "display": _bn(in_pos), "tone": "brand"}
    labels["in_pos_kpi"] = f'יתרת ההשקעות הישירות של חו"ל בישראל, סוף {Y} (מיליארדי דולרים)'
    if out_pos is not None:
        kpis["out_pos"] = {"value": round(out_pos), "display": _bn(out_pos), "tone": "brand"}
        labels["out_pos_kpi"] = f'יתרת ההשקעות הישירות של ישראל בחו"ל, סוף {Y} (מיליארדי דולרים)'
    for key, v, d in (("in_flow", in_flow, "in"), ("out_flow", out_flow, "out")):
        if v is None:
            continue
        prev = tot(d, "flow", Y - 1)
        ch = _change(prev, v)
        tone = "brand" if d == "out" or ch is None or abs(ch) < 0.1 else ("ok" if ch > 0 else "warn")
        kpis[key] = {"value": round(v), "display": _bn(v), "tone": tone}
        who = 'של חו"ל בישראל' if d == "in" else 'של ישראל בחו"ל'
        labels[key + "_kpi"] = f"השקעות ישירות חדשות {who} ב-{Y} (תנועות, מיליארדי דולרים)"
    if "in" in hitech and Y in hitech["in"]:
        s = hitech["in"][Y]
        kpis["hitech"] = {"value": round(s * 100, 1), "display": fmt.pct(s), "tone": "info"}
        labels["hitech_kpi"] = f'חלק ענפי ההיי-טק ביתרת ההשקעות של חו"ל בישראל, {Y}'

    # ── history charts
    if hyears:
        charts["hist"] = {
            "x": [str(y) for y in hyears],
            "in_pos": [_r0(hist.get(("in", "pos"), {}).get(y)) for y in hyears],
            "out_pos": [_r0(hist.get(("out", "pos"), {}).get(y)) for y in hyears],
            "in_flow": [_r0(hist.get(("in", "flow"), {}).get(y)) for y in hyears],
            "out_flow": [_r0(hist.get(("out", "flow"), {}).get(y)) for y in hyears],
        }
        tables["hist"] = [[str(y)] + [_m(hist.get(k, {}).get(y)) for k in
                                      (("in", "pos"), ("out", "pos"), ("in", "flow"), ("out", "flow"))]
                          for y in hyears]
        tables["flows"] = [[str(y)] + [_m(hist.get(k, {}).get(y)) for k in (("in", "flow"), ("out", "flow"))]
                           for y in hyears]
        flags["flows"] = any(v is not None for v in charts["hist"]["in_flow"] + charts["hist"]["out_flow"])
        labels["hist_note"] = (
            f"יתרות ההשקעה בסוף כל שנה, {hyears[0]}-{hyears[-1]}, במיליוני דולרים. "
            "השנים המוקדמות נלקחו מהודעות קודמות של הלמ\"ס, ולכל שנה מוצג הנתון מההודעה העדכנית ביותר שכוללת אותה."
        )
        hp = hist.get(("in", "pos"), {})
        labels["hist_aria"] = (f"גרף עמודות: יתרות ההשקעות הישירות הנכנסות והיוצאות לפי שנה, {hyears[0]}-{hyears[-1]}. "
                               f"ב-{Y} יתרת ההשקעות של חו\"ל בישראל הגיעה ל-{fmt.int_he(hp.get(Y, in_pos))} מיליון דולר.")
        labels["flow_aria"] = (f"גרף עמודות: תנועות ההשקעה הישירה הנכנסות והיוצאות לפי שנה, {hyears[0]}-{hyears[-1]}.")

    # ── rankings by industry / country
    def ranking(d, m, b, n=TOP_N):
        p = P.get((d, m, b))
        if not p:
            return None
        ys = p["years"]
        y0, y1 = ys[0], ys[-1]
        items = [it for it in p["items"] if it["v"].get(y1) is not None]
        if m == "pos":
            items.sort(key=lambda it: (-it["v"][y1], it["name"]))
        else:
            items.sort(key=lambda it: (-abs(it["v"][y1]), -it["v"][y1], it["name"]))
        top = items[:n]
        return {
            "y0": str(y0), "y1": str(y1),
            "names": [_short(it["name"]) for it in top],
            "full": [it["name"] for it in top],
            "v0": [_r0(it["v"].get(y0)) for it in top],
            "v1": [_r0(it["v"][y1]) for it in top],
            "rows": [[it["name"]] + [_m(it["v"].get(y)) for y in ys] for it in top],
            "cols": [str(y) for y in ys],
            "items": items, "p": p,
        }

    R = {}
    for d in DIRS:
        for m in ("pos", "flow"):
            for b in ("industry", "country"):
                r = ranking(d, m, b, TOP_N if m == "pos" else FLOW_N)
                if r:
                    R[(d, m, b)] = r
                    key = f"{d}_{m}_{b}"
                    charts[key] = {k: r[k] for k in ("y0", "y1", "names", "full", "v0", "v1")}
                    tables[key] = r["rows"]
                    labels[key + "_cols"] = (["ענף" if b == "industry" else "מדינה"] + r["cols"])
                    flags[key] = True

    def share_of(r, i, denom):
        return r["items"][i]["v"][int(r["y1"])] / denom if denom else None

    # notes + aria per ranking
    for (d, m, b), r in R.items():
        key = f"{d}_{m}_{b}"
        y1 = int(r["y1"])
        lead = r["items"][0]
        tot_y = r["p"]["total"].get(y1)
        what = "יתרות" if m == "pos" else "תנועות"
        by = "ענף" if b == "industry" else "מדינה"
        if m == "pos":
            n = len(r["names"])
            labels[key + "_note"] = (f"{n} ה{'ענפים' if b == 'industry' else 'מדינות'} עם היתרה הגדולה ביותר בסוף {y1}, "
                                     f"לעומת {r['y0']}, במיליוני דולרים.")
            if b == "country":
                undiv = r["p"]["undiv"] and r["p"]["undiv"].get(y1)
                if undiv is not None and tot_y:
                    labels[key + "_note"] += (f" {fmt.pct(undiv / tot_y)} מהיתרות ({fmt.int_he(undiv)} מיליון דולר) "
                                              "לא חולקו לפי מדינה, בעיקר מטעמי חיסיון.")
        else:
            labels[key + "_note"] = (f"{len(r['names'])} ה{'ענפים' if b == 'industry' else 'מדינות'} עם התנועה הגדולה ביותר "
                                     f"(בערך מוחלט) ב-{y1}, במיליוני דולרים. ערך שלילי הוא משיכת השקעות או החזר הלוואות לבעלים.")
        labels[key + "_aria"] = (f"גרף עמודות אופקי: {what} ההשקעה הישירה ({DIR_HE[d]}) לפי {by}, {y1}. "
                                 f"המוביל: {lead['name']}, {fmt.int_he(lead['v'][y1])} מיליון דולר.")

    # ── continents
    conts = []
    for d in DIRS:
        p = P.get((d, "pos", "country"))
        if not p:
            continue
        y1 = p["years"][-1]
        t = p["total"].get(y1)
        if not t:
            continue
        parts = [(c, p["conts"].get(c, {}).get(y1)) for c in CONTINENTS]
        parts.append(("לא מחולק לפי מדינה", p["undiv"].get(y1) if p["undiv"] else None))
        conts.append((d, y1, t, parts))
    if conts:
        names = [c for c, _ in conts[0][3]]
        charts["cont"] = {
            "dirs": [DIR_HE[d] for d, *_ in conts],
            "names": names,
            "series": [[None if dict(c[3]).get(nm) is None else round(dict(c[3])[nm] / c[2] * 100, 1)
                        for c in conts] for nm in names],
            "abs": [[_r0(dict(c[3]).get(nm)) for c in conts] for nm in names],
        }
        tables["cont"] = [[nm] + [_m(dict(c[3]).get(nm)) for c in conts] for nm in names]
        labels["cont_cols"] = ["יבשת"] + [f"{DIR_HE[d]} ({y1})" for d, y1, *_ in conts]
        labels["cont_aria"] = ("גרף עמודות מוערמות: התפלגות יתרות ההשקעה הישירה לפי יבשת, "
                               + ", ".join(f"{DIR_HE[d]}: {fmt.pct(max((v or 0) for _, v in parts[:-1]) / t)} ביבשת המובילה"
                                           for d, _, t, parts in conts) + ".")
        labels["cont_note"] = f"חלק כל יבשת מסך יתרות ההשקעה הישירה בסוף {conts[0][1]}, כולל היתרות שלא חולקו לפי מדינה."
        neg = sorted({nm for nm, row in zip(names, charts["cont"]["series"]) if any(v is not None and v < 0 for v in row)})
        if neg:
            labels["cont_note"] += f" יתרה שלילית ({fmt.join_he(neg)}) אינה מוצגת בתרשים ומופיעה בטבלה."
        flags["cont"] = True

    # ── technological intensity
    techs = []
    for d in DIRS:
        p = P.get((d, "pos", "tech"))
        if p:
            techs.append((d, p))
    if techs:
        tnames = [("hi_m", "תעשייה: טכנולוגיה עילית"), ("mhi_m", "תעשייה: מעורבת עילית"),
                  ("mlo_m", "תעשייה: מעורבת מסורתית"), ("lo_m", "תעשייה: מסורתית"),
                  ("hi_s", "שירותי היי-טק"), ("oth_s", "מסחר ושירותים אחרים"),
                  ("other", "ענפים אחרים"), ("undiv", "לא מחולק")]
        tnames = [(k, n) for k, n in tnames if any(k in p["parts"] for _, p in techs)]
        ty = techs[0][1]["years"][-1]
        charts["tech"] = {
            "dirs": [DIR_HE[d] for d, _ in techs],
            "names": [n for _, n in tnames],
            "series": [[_r0(p["parts"].get(k, {}).get(p["years"][-1])) for _, p in techs] for k, _ in tnames],
        }
        tables["tech"] = [[n] + [_m(p["parts"].get(k, {}).get(p["years"][-1])) for _, p in techs] for k, n in tnames]
        tables["tech"].append(["מזה: כל ענפי ההיי-טק"] + [_m(p["hitech"].get(p["years"][-1])) for _, p in techs])
        labels["tech_cols"] = ["עוצמה טכנולוגית"] + [f"{DIR_HE[d]} ({p['years'][-1]})" for d, p in techs]
        hs = [(d, p["hitech"][p["years"][-1]] / p["total"][p["years"][-1]]) for d, p in techs
              if p["total"].get(p["years"][-1]) and p["hitech"].get(p["years"][-1]) is not None]
        labels["tech_aria"] = (f"גרף עמודות מוערמות: יתרות ההשקעה הישירה לפי עוצמה טכנולוגית, {ty}. "
                               + ", ".join(f"ענפי ההיי-טק: {fmt.pct(s)} מה{DIR_HE[d]}" for d, s in hs) + ".")
        labels["tech_note"] = (f"יתרות בסוף {ty} לפי העוצמה הטכנולוגית של ענף החברה, במיליוני דולרים. "
                               "ענפי ההיי-טק הם תעשיות הטכנולוגיה העילית ושירותי ההיי-טק (תקשורת, תכנות, שירותי מידע ומחקר ופיתוח).")
        if hitech:
            hy = sorted({y for h in hitech.values() for y in h})
            tables["hitech"] = [[str(y)] + [fmt.pct(hitech[d][y]) if y in hitech.get(d, {}) else "–"
                                            for d, _ in techs] for y in hy]
            labels["hitech_cols"] = ["שנה"] + [f"חלק ההיי-טק, {DIR_HE[d]}" for d, _ in techs]
        flags["tech"] = True

    # ── country x industry group (positions, last year)
    for d in DIRS:
        p = P.get((d, "pos", "cross"))
        if not p or not p["items"]:
            continue
        items = sorted(p["items"], key=lambda it: (-it["total"], it["name"]))[:CROSS_N]
        key = f"cross_{d}"
        charts[key] = {"names": [it["name"] for it in items],
                       "series": [[_r0(it[k]) for it in items] for k, _ in CROSS_COLS],
                       "labels": [lab for _, lab in CROSS_COLS]}
        tables[key] = [[it["name"]] + [_m(it[k]) for k, _ in CROSS_COLS] + [_m(it["total"])] for it in items]
        lead = items[0]
        main = max((k for k, _ in CROSS_COLS[:2]), key=lambda k: lead[k] or 0)
        labels[key + "_aria"] = (f"גרף עמודות אופקי מוערם: יתרות ההשקעה הישירה ({DIR_HE[d]}) לפי מדינה וענף, {p['year']}. "
                                 f"{lead['name']} מובילה עם {fmt.int_he(lead['total'])} מיליון דולר.")
        labels[key + "_year"] = str(p["year"]) if p["year"] else str(Y)
        flags[key] = True
        ins[f"cross_{d}"] = _ins_cross(d, lead, main, p["year"] or Y)
    flags["cross"] = flags.get("cross_in") or flags.get("cross_out")
    labels["cross_cols"] = ["מדינה"] + [lab for _, lab in CROSS_COLS] + ['סה"כ']

    # ── insights
    ins["growth"] = _ins_growth(hist.get(("in", "pos"), {}), hist.get(("out", "pos"), {}))
    ins["flows"] = _ins_flows(hist.get(("in", "flow"), {}), Y)
    ins["ratio"] = _ins_ratio(in_pos, out_pos, Y)
    ins["hitech"] = _ins_hitech(hitech.get("in", {}), hitech.get("out", {}))
    if ("in", "pos", "industry") in R:
        ins["top_in_ind"] = _ins_top_ind(R[("in", "pos", "industry")], "in")
    if ("out", "pos", "industry") in R:
        ins["top_out_ind"] = _ins_top_ind(R[("out", "pos", "industry")], "out")
    if ("out", "pos", "country") in R:
        ins["out_cty"] = _ins_country(R[("out", "pos", "country")], "out")
    if ("in", "pos", "country") in R:
        ins["in_cty"] = _ins_country(R[("in", "pos", "country")], "in")
    order = ("growth", "flows", "top_in_ind", "hitech", "out_cty", "top_out_ind", "in_cty",
             "ratio", "cross_out", "cross_in")
    insights = [{"id": k, "text_he": ins[k]} for k in order if ins.get(k)]
    callouts = {k: ins[k] for k in ins if ins.get(k)}

    # ── text
    yrs_txt = f"{hyears[0]}-{hyears[-1]}" if hyears else f"{Y0}-{Y}"
    lede = (f"השקעות ישירות הן השקעות שבהן משקיע מחזיק לפחות 10% מהון חברה במדינה אחרת. "
            f"בסוף {Y} החזיקו משקיעים זרים בחברות ישראליות השקעות ישירות בהיקף של {_bn(in_pos)} מיליארד דולר")
    if out_pos is not None:
        lede += f", ומשקיעים ישראלים החזיקו בחו\"ל {_bn(out_pos)} מיליארד דולר"
    lede += (f". הנתונים מההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), לפי ענפי כלכלה, מדינות ועוצמה טכנולוגית, "
             f"עם סדרה שנתית ל-{yrs_txt}.")
    labels["lede"] = lede
    labels["tenpct"] = "10%"

    summary = (f"השקעות ישירות של חו\"ל בישראל ושל ישראל בחו\"ל לפי ענף ומדינה: יתרה נכנסת של {_bn(in_pos)} מיליארד דולר בסוף {Y}"
               + (f" ויתרה יוצאת של {_bn(out_pos)} מיליארד דולר." if out_pos is not None else "."))
    desc = (f"השקעות ישירות של חו\"ל בישראל ושל ישראל בחו\"ל לפי ענף ומדינה: {_bn(in_pos)} מיליארד דולר נכנסות"
            + (f" ו-{_bn(out_pos)} מיליארד יוצאות" if out_pos is not None else "")
            + f" בסוף {Y}, נתוני הלמ\"ס.")

    release = {
        "title": str(rel.get("TITLE") or "").strip(),
        "date": _date_he(str(rel.get("RELEASE_DATE") or "")),
        "url": str(rel.get("PAGE_URL") or "").strip(),
        "pdf": str(rel.get("REPORT_PDF_URL") or "").strip(),
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            "temporal_coverage": f"{hyears[0]}/{hyears[-1]}" if hyears else f"{Y0}/{Y}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": 'השקעות ישירות זרות בישראל ושל ישראל בחו"ל | הלמ"ס',
                "description": desc,
                "name": 'השקעות ישירות של ישראל בחו"ל ושל חו"ל בישראל',
                "alternate_names": [
                    "השקעות זרות בישראל",
                    "השקעות ישירות זרות",
                    'השקעות ישראליות בחו"ל',
                    "FDI ישראל",
                ],
            },
        },
        "kpis": kpis,
        "labels": labels,
        "charts": charts,
        "tables": tables,
        "flags": flags,
        "insights": insights,
        "callouts": callouts,
        "release": release,
        "year": str(Y),
    }


def _date_he(s):
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s.strip()[:10])
    if not m:
        return s
    return f"{int(m.group(3))} ב{fmt.MONTHS_HE[int(m.group(2)) - 1]} {m.group(1)}"


# ── insight rules ────────────────────────────────────────────────────────


def _chg(ch):
    """'עלייה של 5.0%' / 'ירידה של 11.2%' / 'ללא שינוי'."""
    if abs(ch) < 0.0005:
        return "ללא שינוי"
    return f"{'עלייה' if ch > 0 else 'ירידה'} של {fmt.pct(abs(ch))}"


def _move(ch, g="f"):
    """'גדלה ב-5%' / 'קטנה ב-5%' / 'נותרה כמעט ללא שינוי' (feminine)."""
    if abs(ch) < 0.01:
        return "נותרה כמעט ללא שינוי"
    return f"{'גדלה' if ch > 0 else 'קטנה'} ב-{fmt.pct(abs(ch), 0)}"


def _ins_growth(hin, hout):
    ys = sorted(hin)
    if len(ys) < 3:
        return None
    a, b = hin[ys[0]], hin[ys[-1]]
    ch = _change(a, b)
    if ch is None:
        return None
    word = "גדלה" if ch > 0.05 else ("קטנה" if ch < -0.05 else "נותרה כמעט ללא שינוי")
    s = (f"יתרת ההשקעות הישירות של חו\"ל בישראל {word} "
         f"{'ב-' + fmt.pct(abs(ch), 0) + ' ' if abs(ch) > 0.05 else ''}"
         f"בין {ys[0]} ל-{ys[-1]}, מ-{_bn(a)} ל-{_bn(b)} מיליארד דולר")
    yo = sorted(hout)
    if len(yo) >= 3 and yo[0] == ys[0] and yo[-1] == ys[-1]:
        co = _change(hout[yo[0]], hout[yo[-1]])
        if co is not None:
            s += f". היתרה הישראלית בחו\"ל {_move(co, 'f')} באותן שנים ({_bn(hout[yo[-1]])} מיליארד דולר ב-{yo[-1]})"
    return s + "."


def _ins_flows(h, Y):
    ys = sorted(h)
    if len(ys) < 3 or Y not in h:
        return None
    v = h[Y]
    peak_y = max(ys, key=lambda y: (h[y], -y))
    prev = h.get(Y - 1)
    ch = _change(prev, v)
    if ch is None:
        return None
    if peak_y == Y:
        return (f"תנועות ההשקעה הישירה של חו\"ל בישראל ב-{Y} הגיעו ל-{_bn(v)} מיליארד דולר, "
                f"השיא בשנים {ys[0]}-{ys[-1]} ({_chg(ch)} לעומת {Y - 1}).")
    gap = (h[peak_y] - v) / h[peak_y] if h[peak_y] > 0 else None
    if gap is None or gap < 0.15 or peak_y == Y - 1:
        return (f"תנועות ההשקעה הישירה של חו\"ל בישראל ב-{Y}: {_bn(v)} מיליארד דולר, "
                f"{_chg(ch)} לעומת {Y - 1}.")
    return (f"ההשקעות הישירות החדשות של חו\"ל בישראל ב-{Y} הסתכמו ב-{_bn(v)} מיליארד דולר, "
            f"{_chg(ch)} לעומת {Y - 1} ו-{fmt.pct(gap, 0)} פחות מהשיא של {peak_y} ({_bn(h[peak_y])} מיליארד).")


def _ins_ratio(a, b, Y):
    if a is None or b is None or b <= 0:
        return None
    r = a / b
    if r < 1.2 and r > 1 / 1.2:
        return (f"בסוף {Y} היו יתרות ההשקעה הנכנסות ({_bn(a)} מיליארד דולר) והיוצאות ({_bn(b)} מיליארד) קרובות בהיקפן.")
    if r >= 1.2:
        return (f"יתרת ההשקעות של חו\"ל בישראל גדולה פי {fmt.num_he(r, 1)} מיתרת ההשקעות של ישראל בחו\"ל "
                f"({_bn(a)} לעומת {_bn(b)} מיליארד דולר בסוף {Y}).")
    return (f"יתרת ההשקעות של ישראל בחו\"ל גדולה פי {fmt.num_he(1 / r, 1)} מיתרת ההשקעות של חו\"ל בישראל "
            f"({_bn(b)} לעומת {_bn(a)} מיליארד דולר בסוף {Y}).")


def _ins_hitech(hin, hout):
    ys = sorted(hin)
    if len(ys) < 2:
        return None
    a, b = hin[ys[0]], hin[ys[-1]]
    diff = (b - a) * 100
    trend = (f"עלייה מ-{fmt.pct(a)} ב-{ys[0]}" if diff >= 2 else
             f"ירידה מ-{fmt.pct(a)} ב-{ys[0]}" if diff <= -2 else f"בדומה ל-{fmt.pct(a)} ב-{ys[0]}")
    s = (f"ענפי ההיי-טק (תעשיות טכנולוגיה עילית ושירותי היי-טק) מחזיקים {fmt.pct(b)} מיתרת ההשקעות של חו\"ל בישראל "
         f"בסוף {ys[-1]}, {trend}")
    if ys[-1] in hout:
        s += f". בהשקעות הישראליות בחו\"ל חלקם {fmt.pct(hout[ys[-1]])}"
    return s + "."


def _ins_top_ind(r, d):
    y1 = int(r["y1"])
    tot = r["p"]["total"].get(y1)
    items = r["items"]
    if not tot or len(items) < 2:
        return None
    a, b = items[0], items[1]
    sa, sb = a["v"][y1] / tot, b["v"][y1] / tot
    if d == "in":
        if sa + sb < 0.2:
            return None
        return (f"שני הענפים הגדולים בהשקעות של חו\"ל בישראל, {_short(a['name'])} ({fmt.pct(sa)}) ו{_short(b['name'])} ({fmt.pct(sb)}), "
                f"מחזיקים יחד {fmt.pct(sa + sb)} מהיתרה בסוף {y1}.")
    if sa < 0.2:
        return None
    return (f"ענף {_short(a['name'])} מחזיק {fmt.pct(sa)} מיתרת ההשקעות של ישראל בחו\"ל בסוף {y1} "
            f"({fmt.int_he(a['v'][y1])} מיליון דולר), פי {fmt.num_he(a['v'][y1] / b['v'][y1], 1)} מהענף השני, {_short(b['name'])}."
            if b["v"][y1] > 0 else None)


def _ins_country(r, d):
    y1 = int(r["y1"])
    p = r["p"]
    tot = p["total"].get(y1)
    undiv = p["undiv"].get(y1) if p["undiv"] else None
    if not tot or undiv is None or not r["items"]:
        return None
    divided = tot - undiv
    if divided <= 0:
        return None
    a = r["items"][0]
    sa = a["v"][y1] / divided
    if sa < 0.25:
        return None
    who = 'של ישראל בחו"ל' if d == "out" else 'של חו"ל בישראל'
    verb = "מושקעים ב" if d == "out" else "מגיעים מ"
    return (f"{fmt.pct(sa)} מיתרת ההשקעות {who} שחולקה לפי מדינה {verb}{a['name']} "
            f"({fmt.int_he(a['v'][y1])} מיליון דולר בסוף {y1}). "
            f"{fmt.pct(undiv / tot)} מהיתרה לא חולקו לפי מדינה.")


def _ins_cross(d, lead, main, year):
    t = lead["total"]
    v = lead.get(main)
    if not t or t <= 0 or v is None or v / t < 0.6:
        return None
    what = "בחברות תעשייה" if main == "manuf" else "בחברות שירותים"
    who = 'מההשקעות הישראליות ב' if d == "out" else "מההשקעות מ"
    return f"{fmt.pct(v / t)} {who}{lead['name']} ({year}) הן {what}."
