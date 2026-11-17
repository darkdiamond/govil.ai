"""מקבלי תארים אקדמיים: CBS's yearly release on academic degree recipients.

The release is a set of chart-data sheets ("תרשים N - ..."), each holding two
academic years side by side. `history_releases: 4` stacks the last editions,
so the page stitches a short trend (each edition adds one year; the newest
edition wins where two overlap). CBS renumbers and adds sheets between
editions (the Bedouin sheets first appeared in 2026), so every stem t1..t21
is optional and each sheet is recognised by its title, never by its stem:

  "מקבלי תארים ... לפי <dim>, מספרים מוחלטים"        counts
  "אחוז <group> בקרב כלל מקבלי התארים ... לפי <dim>"  shares (%)

with <dim> one of סוג מוסד / תואר / תחום לימוד and <group> הנשים or any
population group (הערבים, החרדים, יוצאי אתיופיה, הבדווים, and new ones flow
through). Counts by institution type are required: they are the totals.

A sheet that repeats the previous edition's numbers exactly (CBS shipped the
2026 Haredi-by-field sheet as a copy of 2025's, relabelled one year on) is a
stale copy: it is ignored and the older edition's years stand.
"""
import re

import pandas as pd
from govlib import cbs, fmt

STEM = re.compile(r"t\d+")
TITLE = re.compile(r"^תרשים\s*\d+[א-ת]?\s*[-.]")
ACAD = re.compile(r"((?:19|20)\d\d)\s*/\s*(\d\d)")
GROUP = re.compile(r"אחוז\s+(.+?)\s+בקרב")
DIMS = (("inst", "סוג מוסד"), ("degree", "לפי תואר"), ("field", "תחום לימוד"))
FLAT_PCT = 1.5      # total change below this (%) reads as stability
MOVE_PCT = 5.0      # a category's change worth an insight (%)
INST_PCT = 3.0      # the same for an institution type (bigger, steadier groups)
MIN_FIELD = 1000    # fields smaller than this are not ranked by change
GAP_PP = 20.0       # women-share gap between fields worth an insight
SHIFT_PP = 0.1      # a group's overall share moving less than this is flat
MAX_INSIGHTS = 8


def _rel_key(no):
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d{4})\s*", str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _int(v):
    try:
        return int(str(v).strip())
    except ValueError:
        return 0


def _cells(df):
    return sorted((c for c in df.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    """(subject, dim) for a sheet title, or None. subject is "count",
    "women" or a population group's name as printed (e.g. "הערבים")."""
    dim = next((k for k, w in DIMS if w in t), None)
    if not dim:
        return None
    if "מספרים מוחלטים" in t and "מקבלי תארים" in t:
        return ("count", dim)
    m = GROUP.search(t)
    if m and "מקבלי התארים" in t:
        g = m.group(1).strip()
        return ("women" if g == "הנשים" else g, dim)
    return None


def _parse(rows, name):
    """{"years": {end year: label}, "cats": [label], "vals": {year: {cat: v}},
    "matrix": tuple} for one chart sheet, or None for a sheet with no
    numbers at all (title or header rows only). Raises when it has numbers but no
    year header, or a year header but no data rows (the layout changed)."""
    if not any(cbs.num(c) is not None for r in rows for c in r[1:]):
        return None  # a cut-off sheet: title or header only
    head = None
    for i, r in enumerate(rows):
        cols = {j: ACAD.search(c) for j, c in enumerate(r) if ACAD.search(c)}
        if cols and not any(TITLE.match(c) for c in r):
            head = (i, cols)
            break
    if head is None:
        raise ValueError(f"{name}: data rows but no academic-year header")
    i0, cols = head
    years = {}
    for j, m in cols.items():
        end = int(m.group(1)) + 1
        heb = ACAD.sub("", rows[i0][j]).strip()
        years[j] = (end, f"{m.group(1)}/{m.group(2)}", heb)
    cats, vals, matrix = [], {}, []
    for r in rows[i0 + 1:]:
        lab = cbs.cell(r, 0)
        if not lab or lab.startswith(("מקור", "(", "*")):
            continue
        nums = {j: cbs.val(r, j) for j in years}
        if all(v is None for v in nums.values()):
            continue
        cats.append(lab)
        for j, v in nums.items():
            if v is not None:
                vals.setdefault(years[j][0], {})[lab] = v
        matrix.append((lab,) + tuple(nums[j] for j in sorted(years)))
    if not cats:
        raise ValueError(f"{name}: year header but no data rows")
    return {"years": {e: (a, h) for e, a, h in years.values()}, "cats": cats, "vals": vals,
            "matrix": tuple(matrix)}


def _tables(frames):
    """{(subject, dim): {"cats", "vals", "years", "stale"}} merged over the
    editions, oldest first; a newer edition's year replaces an older one's."""
    eds = {}
    names = sorted((n for n in frames if STEM.fullmatch(n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        cols = _cells(df)
        for no in df["RELEASE_NO"].unique():
            g = df[df["RELEASE_NO"] == no]
            g = g.assign(_s=g["SHEET_NO"].map(_int), _r=g["ROW"].map(_int))
            g = g.sort_values(["_s", "_r"], kind="stable")
            rows = [[cbs.clean(v) for v in r] for r in g[cols].itertuples(index=False)]
            k = _kind(_title(rows))
            if not k:
                continue
            ed = eds.setdefault(_rel_key(no), {})
            if k not in ed:
                p = _parse(rows, f"{n} {no}")
                if p:
                    ed[k] = p
    out = {}
    last = {}
    for ek in sorted(eds):
        for k, p in eds[ek].items():
            t = out.setdefault(k, {"cats": [], "vals": {}, "years": {}, "stale": False})
            if last.get(k) == p["matrix"]:
                t["stale"] = True
                continue
            last[k] = p["matrix"]
            t["stale"] = False  # only the newest edition's copy is worth a note
            t["cats"] = p["cats"] + [c for c in t["cats"] if c not in p["cats"]]
            for y, d in p["vals"].items():
                t["vals"][y] = dict(d)
            t["years"].update(p["years"])
    return out


# ── formatting ──────────────────────────────────────────────────────────


def _p(v, d=1):
    return f"{v:.{d}f}%"


def _r(v, d=1):
    return None if v is None else round(v, d)


def _n(v):
    return fmt.int_he(v)


def _chg(new, old):
    return (new - old) / old * 100 if old else None


def _signed(v):
    s = f"{abs(v):.1f}%"
    return s if v >= 0 else "−" + s


def _short(g):
    """"הערבים" → "ערבים"; "יוצאי אתיופיה" stays."""
    return g[1:] if " " not in g and g.startswith("ה") and len(g) > 2 else g


def _weighted(share, count, y):
    """Overall share in year y from a share-by-institution table weighted by
    the counts by institution; None unless every institution has both."""
    if not share or y not in share["vals"] or y not in count["vals"]:
        return None
    s, c = share["vals"][y], count["vals"][y]
    if not c or set(c) - set(s):
        return None
    tot = sum(c.values())
    return sum(s[k] * c[k] for k in c) / tot if tot else None


# ── compute ─────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    T = _tables(frames)
    cinst = T.get(("count", "inst"))
    if not cinst or not cinst["vals"]:
        raise ValueError("no counts-by-institution sheet in any edition")
    years = sorted(cinst["vals"])
    ly = years[-1]
    py = years[-2] if len(years) > 1 else None
    ylab = {}
    for t in T.values():
        ylab.update(t["years"])
    ylab.update(cinst["years"])

    def acad(y):
        return ylab[y][0]

    def heb(y):
        a, h = ylab[y]
        return f"{h} ({a})" if h else a

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    labels_dim = {"inst": "סוג מוסד", "degree": "תואר", "field": "תחום לימוד"}
    cands = []

    def add(iid, text):
        if text:
            cands.append({"id": iid, "text_he": text})

    totals = {y: sum(cinst["vals"][y].values()) for y in years}
    total = totals[ly]
    kpis["total"] = {"value": round(total), "display": _n(total), "tone": "brand"}
    labels["total_kpi"] = f"מקבלי תארים ותעודות אקדמיות, {acad(ly)}"
    tchg = _chg(total, totals[py]) if py else None
    if tchg is not None:
        tone = "info" if abs(tchg) < FLAT_PCT else ("ok" if tchg > 0 else "warn")
        kpis["change"] = {"value": round(tchg, 1), "display": _signed(tchg), "tone": tone}
        labels["change_kpi"] = f"שינוי לעומת {acad(py)}"

    # ── trend by institution type ──
    icats = [c for c in cinst["cats"] if any(c in cinst["vals"][y] for y in years)]
    charts["trend"] = {"x": [acad(y) for y in years],
                       "series": [{"name": c, "data": [_r(cinst["vals"][y].get(c), 0) for y in years]}
                                  for c in icats],
                       "total": [round(totals[y]) for y in years]}
    tables["trend"] = [[acad(y)] + [_n(cinst["vals"][y][c]) if c in cinst["vals"][y] else "–"
                                    for c in icats] + [_n(totals[y])] for y in years]
    labels["trend_cols"] = ["שנת לימודים"] + icats + ["סך הכול"]
    labels["trend_aria"] = (f"תרשים עמודות מוערמות: מקבלי תארים לפי סוג מוסד, {acad(years[0])} עד {acad(ly)}"
                            if len(years) > 1 else f"תרשים עמודות: מקבלי תארים לפי סוג מוסד, {acad(ly)}")
    lv = cinst["vals"][ly]
    top_i = max(lv, key=lambda c: (lv[c], c))
    labels["trend_note"] = (f"בשנת {heb(ly)} קיבלו {_n(total)} סטודנטים תואר או תעודה אקדמית. "
                            f"{_p(lv[top_i] / total * 100)} מהם סיימו ב{top_i}."
                            + (" כל הודעה שנתית מציגה שתי שנות לימודים, והעמוד מחבר את ההודעות האחרונות לרצף אחד."
                               if len(years) > 2 else ""))

    if tchg is not None:
        word = ("כמעט ללא שינוי" if abs(tchg) < FLAT_PCT else
                f"עלייה של {_p(tchg)}" if tchg > 0 else f"ירידה של {_p(-tchg)}")
        add("total", f"בשנת {heb(ly)} קיבלו {_n(total)} סטודנטים תואר או תעודה אקדמית, "
                     f"{word} לעומת {_n(totals[py])} בשנת {heb(py)}.")
        moves = [(c, _chg(lv[c], cinst["vals"][py][c])) for c in lv if c in cinst["vals"][py]]
        moves = [(c, v) for c, v in moves if v is not None and abs(v) >= INST_PCT]
        if moves:
            c, v = max(moves, key=lambda m: (abs(m[1]), m[0]))
            add("inst", f"מספר מקבלי התארים ב{c} {'עלה' if v > 0 else 'ירד'} ב-{_p(abs(v))}, "
                        f"מ-{_n(cinst['vals'][py][c])} ל-{_n(lv[c])}.")
    if len(years) > 2:
        f0, fl = totals[years[0]], total
        ch = _chg(fl, f0)
        add("span", f"לאורך {len(years)} שנות הלימודים שבעמוד ({acad(years[0])} עד {acad(ly)}) "
                    + ("מספר מקבלי התארים נשאר כמעט יציב" if abs(ch) < FLAT_PCT else
                       f"מספר מקבלי התארים {'עלה' if ch > 0 else 'ירד'} ב-{_p(abs(ch))}")
                    + f", מ-{_n(f0)} ל-{_n(fl)}.")

    # ── counts by degree / field: latest vs previous ──
    def compare(key, sect):
        t = T.get(("count", key))
        if not t or not t["vals"]:
            return None
        ys = sorted(t["vals"])
        y1 = ys[-1]
        y0 = ys[-2] if len(ys) > 1 else None
        cats = [c for c in t["cats"] if c in t["vals"][y1]]
        flags[sect] = True
        series = ([{"name": acad(y0), "data": [_r(t["vals"][y0].get(c), 0) for c in cats]}] if y0 else [])
        series.append({"name": acad(y1), "data": [_r(t["vals"][y1][c], 0) for c in cats]})
        charts[sect] = {"x": cats, "series": series}
        rows = []
        for c in cats:
            v1 = t["vals"][y1][c]
            if y0 is None:
                rows.append([c, _n(v1)])
                continue
            v0 = t["vals"][y0].get(c)
            ch = _chg(v1, v0) if v0 else None
            rows.append([c, _n(v0) if v0 is not None else "–", _n(v1),
                         _signed(ch) if ch is not None else "–"])
        tables[sect] = rows
        labels[f"{sect}_cols"] = ([labels_dim[key], acad(y0), acad(y1), "שינוי"] if y0
                                  else [labels_dim[key], acad(y1)])
        return t, y0, y1, cats

    deg = compare("degree", "degree")
    if deg:
        t, y0, y1, cats = deg
        v = t["vals"][y1]
        tot = sum(v.values())
        top = max(cats, key=lambda c: (v[c], c))
        labels["degree_note"] = (f"בשנת {heb(y1)}: {_n(v[top])} מקבלי {top} ({_p(v[top] / tot * 100)} מהמסיימים)"
                                 + (f", {_n(v['תואר שלישי'])} מקבלי תואר שלישי" if "תואר שלישי" in v else "")
                                 + ". \"תעודה אקדמית\" כוללת תעודת הוראה ותעודות אקדמיות אחרות.")
        labels["degree_aria"] = f"תרשים עמודות: מקבלי תארים לפי תואר, {acad(y1)}"
        if y0:
            mv = [(c, _chg(v[c], t["vals"][y0][c])) for c in cats if t["vals"][y0].get(c)]
            mv = [(c, x) for c, x in mv if abs(x) >= MOVE_PCT]
            if mv:
                c, x = max(mv, key=lambda m: (abs(m[1]), m[0]))
                add("degree", f"מספר מקבלי {c} {'עלה' if x > 0 else 'ירד'} ב-{_p(abs(x))} בשנת {heb(y1)}, "
                              f"מ-{_n(t['vals'][y0][c])} ל-{_n(v[c])}.")
    fld = compare("field", "field")
    if fld:
        t, y0, y1, cats = fld
        v = t["vals"][y1]
        tot = sum(v.values())
        top = max(cats, key=lambda c: (v[c], c))
        labels["field_note"] = (f"בשנת {heb(y1)} התחום הגדול ביותר הוא {top}, עם {_n(v[top])} מקבלי תארים "
                                f"({_p(v[top] / tot * 100)}).")
        labels["field_aria"] = f"תרשים עמודות אופקי: מקבלי תארים לפי תחום לימוד, {acad(y1)}"
        if y0:
            mv = [(c, _chg(v[c], t["vals"][y0][c])) for c in cats
                  if t["vals"][y0].get(c) and v[c] >= MIN_FIELD]
            mv = [(c, x) for c, x in mv if abs(x) >= MOVE_PCT]
            if mv:
                c, x = max(mv, key=lambda m: (abs(m[1]), m[0]))
                add("field", f"התחום שהשתנה יותר מכול הוא {c}: {'עלייה' if x > 0 else 'ירידה'} של {_p(abs(x))} "
                             f"במספר מקבלי התארים, מ-{_n(t['vals'][y0][c])} ל-{_n(v[c])}.")

    # ── women ──
    wov = {y: _weighted(T.get(("women", "inst")), cinst, y) for y in years}
    if wov[ly] is not None:
        kpis["women"] = {"value": round(wov[ly], 1), "display": _p(wov[ly]), "tone": "brand"}
        labels["women_kpi"] = f"נשים מקרב מקבלי התארים, {acad(ly)}"
    for key in ("field", "degree", "inst"):
        t = T.get(("women", key))
        if not t or not t["vals"]:
            continue
        ys = sorted(t["vals"])
        y1 = ys[-1]
        y0 = ys[-2] if len(ys) > 1 else None
        cats = [c for c in t["cats"] if c in t["vals"][y1]]
        sect = f"women_{key}"
        flags[sect] = True
        series = ([{"name": acad(y0), "data": [_r(t["vals"][y0].get(c)) for c in cats]}] if y0 else [])
        series.append({"name": acad(y1), "data": [_r(t["vals"][y1][c]) for c in cats]})
        charts[sect] = {"x": cats, "series": series}
        tables[sect] = [[c] + ([_p(t["vals"][y0][c]) if c in t["vals"][y0] else "–"] if y0 else [])
                        + [_p(t["vals"][y1][c])] for c in cats]
        labels[f"{sect}_cols"] = [labels_dim[key]] + ([acad(y0)] if y0 else []) + [acad(y1)]
        labels[f"{sect}_aria"] = f"תרשים עמודות: אחוז הנשים בקרב מקבלי התארים לפי {labels_dim[key]}, {acad(y1)}"
        v = t["vals"][y1]
        hi = max(cats, key=lambda c: (v[c], c))
        lo = min(cats, key=lambda c: (v[c], c))
        labels[f"{sect}_note"] = (f"אחוז הנשים בקרב מקבלי התארים, {acad(y1)}: הגבוה ביותר ב{hi} ({_p(v[hi])}), "
                                  f"הנמוך ביותר ב{lo} ({_p(v[lo])}).")
        if key == "field" and v[hi] - v[lo] >= GAP_PP:
            add("women_field", f"בשנת {heb(y1)} נשים הן {_p(v[hi])} ממקבלי התארים ב{hi}, "
                               f"לעומת {_p(v[lo])} בלבד ב{lo}.")
        if key == "degree" and y0 and "תואר שלישי" in v and "תואר שלישי" in t["vals"][y0]:
            a, b = t["vals"][y0]["תואר שלישי"], v["תואר שלישי"]
            if abs(b - a) >= 1:
                add("women_phd", f"אחוז הנשים בקרב מקבלי התואר השלישי {'עלה' if b > a else 'ירד'} "
                                 f"מ-{_p(a)} בשנת {heb(y0)} ל-{_p(b)} בשנת {heb(y1)}.")
    if wov[ly] is not None:
        add("women", f"נשים הן {_p(wov[ly])} מכלל מקבלי התארים בשנת {heb(ly)}.")

    # ── population groups ──
    groups = []
    for (s, d) in T:
        if s not in ("count", "women") and s not in groups:
            groups.append(s)
    order = {g: min(i for i, k in enumerate(T) if k[0] == g) for g in groups}
    groups.sort(key=lambda g: (order[g], g))
    gov_series = []
    for g in groups:
        ser = [_weighted(T.get((g, "inst")), cinst, y) for y in years]
        if any(v is not None for v in ser):
            gov_series.append((g, ser))
    if gov_series:
        flags["groups_trend"] = True
        charts["groups_trend"] = {"x": [acad(y) for y in years],
                                  "series": [{"name": _short(g), "data": [_r(v, 2) for v in ser]}
                                             for g, ser in gov_series]}
        tables["groups_trend"] = [[acad(y)] + [_p(ser[i], 2) if ser[i] is not None else "–"
                                               for _, ser in gov_series] for i, y in enumerate(years)]
        labels["groups_trend_cols"] = ["שנת לימודים"] + [_short(g) for g, _ in gov_series]
        labels["groups_trend_aria"] = "תרשים קווים: חלקן של קבוצות אוכלוסייה בקרב כלל מקבלי התארים לפי שנה"
        parts = []
        for g, ser in gov_series:
            if py is None or ser[-1] is None or ser[-2] is None:
                continue
            a, b = ser[-2], ser[-1]
            verb = "נותר יציב" if abs(b - a) < SHIFT_PP else ("עלה" if b > a else "ירד")
            d = 1 if _p(a) != _p(b) else 2
            parts.append(f"חלקם של {g} {verb} (מ-{_p(a, d)} ל-{_p(b, d)})")
        if parts:
            add("groups", f"בשנת {heb(ly)} לעומת השנה הקודמת, בקרב כלל מקבלי התארים: {fmt.join_he(parts)}.")
        g0, s0 = gov_series[0]
        if s0[-1] is not None:
            kpis["group0"] = {"value": round(s0[-1], 1), "display": _p(s0[-1]), "tone": "brand"}
            labels["group0_kpi"] = f"{_short(g0)} מקרב מקבלי התארים, {acad(ly)}"
        labels["groups_trend_note"] = ("חלקה של כל קבוצה בקרב כלל מקבלי התארים, מחושב מאחוז הקבוצה בכל סוג מוסד "
                                       "ומספר מקבלי התארים בו. בחרו קבוצה במקרא כדי להציג אותה בקנה מידה משלה.")

    conc = []
    for key in ("inst", "degree", "field"):
        present = [g for g in groups if T.get((g, key)) and T[(g, key)]["vals"]]
        if not present:
            continue
        cats = []
        for g in present:
            t = T[(g, key)]
            y1 = max(t["vals"])
            cats += [c for c in t["cats"] if c in t["vals"][y1] and c not in cats]
        series, notes = [], []
        for g in present:
            t = T[(g, key)]
            y1 = max(t["vals"])
            name = _short(g) + ("" if y1 == ly else f" ({acad(y1)})")
            if y1 != ly:
                notes.append(f"ל{_short(g)} הנתון האחרון בהודעות הוא משנת {acad(y1)}"
                             + (" (בהודעה האחרונה הופיע לוח זהה לזה של השנה הקודמת)" if t["stale"] else ""))
            series.append({"name": name, "data": [_r(t["vals"][y1].get(c), 2) for c in cats]})
            v = t["vals"][y1]
            if key == "inst" and len(v) > 1:
                hi = max(v, key=lambda c: (v[c], c))
                lo = min(v, key=lambda c: (v[c], c))
                if v[lo] >= 0.3 and v[hi] / v[lo] >= 2:
                    conc.append((v[hi] / v[lo], g, hi, lo, v[hi], v[lo], y1))
        sect = f"groups_{key}"
        flags[sect] = True
        charts[sect] = {"x": cats, "series": series}
        tables[sect] = [[c] + [_p(s["data"][i], 2) if s["data"][i] is not None else "–" for s in series]
                        for i, c in enumerate(cats)]
        labels[f"{sect}_cols"] = [labels_dim[key]] + [s["name"] for s in series]
        labels[f"{sect}_aria"] = f"תרשים עמודות: אחוז קבוצות אוכלוסייה בקרב מקבלי התארים לפי {labels_dim[key]}"
        miss = sum(1 for s in series for v in s["data"] if v is None)
        labels[f"{sect}_note"] = ("אחוז כל קבוצה בקרב מקבלי התארים"
                                  + (f", {acad(ly)}" if not notes else "")
                                  + ". בחרו קבוצה במקרא."
                                  + (f" {'; '.join(notes)}." if notes else "")
                                  + (" תא ריק: הלמ\"ס לא פרסמה את הנתון." if miss else ""))
    if conc:
        r, g, hi, lo, a, b, y1 = max(conc, key=lambda c: (c[0], c[1]))
        add("concentration", f"אחוז {g} בקרב מקבלי התארים ב{hi} ({_p(a, 2 if a < 1 else 1)}) גבוה פי {r:.1f} מאחוזם ב{lo} "
                             f"({_p(b, 2 if b < 1 else 1)}), בשנת {heb(y1)}.")

    # ── insights order ──
    order_ids = ("total", "groups", "inst", "degree", "field", "women_field", "women_phd",
                 "concentration", "span", "women")
    insights = sorted(cands, key=lambda i: order_ids.index(i["id"]))[:MAX_INSIGHTS]

    # ── release card, lede, SEO ──
    headline = str(rel.get("HEADLINE") or "").strip()
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": headline,
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["lede"] = (f"כמה סטודנטים מסיימים תואר אקדמי בישראל בכל שנה, באיזה תואר, באילו מוסדות ובאילו "
                      f"תחומים, ומי הם: נשים וגברים וקבוצות אוכלוסייה. בשנת {heb(ly)} קיבלו {_n(total)} "
                      f"סטודנטים תואר או תעודה אקדמית"
                      + (f", ונשים היו {_p(wov[ly])} מהם" if wov[ly] is not None else "")
                      + ". הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על מקבלי תארים "
                        "אקדמיים.")
    labels["latest_year"] = acad(ly)
    labels["years"] = fmt.join_he([acad(y) for y in years])

    summary = (f"מקבלי תארים אקדמיים בישראל לפי נתוני הלמ\"ס: {_n(total)} מקבלי תארים ותעודות בשנת {heb(ly)}"
               + (f", מהם {_p(wov[ly])} נשים" if wov[ly] is not None else "")
               + ". פילוח לפי תואר, סוג מוסד, תחום לימוד וקבוצת אוכלוסייה.")
    desc = (f"כמה מקבלי תארים אקדמיים יש בישראל: {_n(total)} בשנת {acad(ly)}, לפי תואר, סוג מוסד ותחום לימוד"
            + (f", עם אחוז הנשים ({_p(wov[ly])})" if wov[ly] is not None else "")
            + " וקבוצות אוכלוסייה.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "misc",
        "temporal_coverage": f"{years[0] - 1}/{ly}",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "מקבלי תארים אקדמיים בישראל: נתוני הלמ\"ס",
            "description": desc,
            "name": "מקבלי תארים אקדמיים",
            "alternate_names": ["בוגרי אוניברסיטאות ומכללות", "מספר מקבלי תואר ראשון",
                                "מקבלי תואר שני ושלישי", "בוגרי השכלה גבוהה בישראל",
                                "מסיימי תואר אקדמי"],
        },
    }
    return {"agent_data": agent_data, "kpis": kpis, "charts": charts, "insights": insights,
            "labels": labels, "tables": tables, "flags": flags, "release": release}
