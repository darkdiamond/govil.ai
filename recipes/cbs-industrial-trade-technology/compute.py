"""מאזן היצוא והיבוא התעשייתי לפי עוצמה טכנולוגית: CBS's yearly release.

Three tables, each industry rows × five year columns, in million dollars,
diamonds excluded: imports, exports, and the balance (exports minus imports).
Industries sit under four OECD technology-intensity groups (high, medium-high,
medium-low, low), with a grand total on top.

Tables are found by their TITLE ("לוח N. - יבוא תעשייתי ...", "יצוא
תעשייתי", "מאזן יצוא ויבוא"), never by stem: t4..t6 are spare optional slots.
`history_releases` is 3, so each grid stacks up to three editions; each
edition is parsed on its own (header row with "ענף" / "סמל", year columns
by content) and for a year several editions carry, the newest edition wins
(CBS revises earlier years). Rows are keyed by the industry code ("סמל"),
groups and the total by their label.

imports and exports are required; the balance table is read when present
and otherwise computed as exports minus imports. A recognised table whose
header labels are gone raises. A missing group or industry drops its row.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^לוח\s*\d+")
HEB = re.compile("[א-ת]")
REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
# Group labels, in the published order (high → low). Unknown groups still
# flow through, after these.
GROUP_ORDER = ("תעשיות טכנולוגיה עילית", "תעשיות טכנולוגיה מעורבת עילית",
               "תעשיות טכנולוגיה מעורבת מסורתית", "תעשיות טכנולוגיה מסורתית")
GROUP_SHORT = {"תעשיות טכנולוגיה עילית": "טכנולוגיה עילית",
               "תעשיות טכנולוגיה מעורבת עילית": "מעורבת עילית",
               "תעשיות טכנולוגיה מעורבת מסורתית": "מעורבת מסורתית",
               "תעשיות טכנולוגיה מסורתית": "מסורתית"}
# "in the X industries": the definite form for sentences.
GROUP_PHRASE = {"תעשיות טכנולוגיה עילית": "תעשיות הטכנולוגיה העילית",
                "תעשיות טכנולוגיה מעורבת עילית": "תעשיות הטכנולוגיה המעורבת העילית",
                "תעשיות טכנולוגיה מעורבת מסורתית": "תעשיות הטכנולוגיה המעורבת המסורתית",
                "תעשיות טכנולוגיה מסורתית": "תעשיות הטכנולוגיה המסורתית"}
HIGH = "תעשיות טכנולוגיה עילית"
TOTAL = "__total__"
N_INDBAL = 16
N_MOVERS = 12
N_TREE_TABLE = 20
PREFIX = re.compile(r"^(?:ייצור|יצור)\s+(?!ו)")


def _short(label):
    """Axis label: the industry name without its leading 'ייצור'."""
    return PREFIX.sub("", label) or label


# ── reading ──────────────────────────────────────────────────────────────


def _rel_key(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _editions(df, name):
    """[(sort_key, release_no, rows)] newest first, each edition's grid on its own."""
    if df.empty:
        return []
    out = []
    for no in df["RELEASE_NO"].unique():
        sub = df[df["RELEASE_NO"] == no]
        out.append(((str(sub["RELEASE_DATE"].max()), _rel_key(no), str(no)), str(no),
                    cbs.grid(sub, name)))
    out.sort(key=lambda e: e[0], reverse=True)
    return out


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    if "מאזן" in t:
        return "bal"
    if "יצוא תעשייתי" in t:
        return "exp"
    if "יבוא תעשייתי" in t:
        return "imp"
    return None


def _parse(rows, name):
    """{key: {"label", "group", "code", "years": {year: value}}} plus the
    key order, from one edition's grid."""
    h = cbs.row_with(rows, "סמל", name=name)
    lcol = cbs.col_after(rows[h], "ענף", 0)
    ccol = cbs.col_after(rows[h], "סמל", 0)
    ycols = [(int(c), j) for j, c in enumerate(rows[h]) if cbs.YEAR.match(c)]
    if len(ycols) < 2:
        raise ValueError(f"{name}: year columns not found")
    out, order, group = {}, [], None
    for r in rows[h + 1:]:
        label = cbs.cell(r, lcol)
        if not label or not HEB.search(label):
            continue
        years = {y: cbs.val(r, j) for y, j in ycols}
        years = {y: v for y, v in years.items() if v is not None}
        if not years:
            continue
        code = cbs.cell(r, ccol)
        if label.startswith("סך הכל"):
            key, grp = TOTAL, None
        elif not code and label.startswith("תעשיות"):
            key, grp, group = label, None, label
        elif code:
            key, grp = "c:" + code, group
        else:
            continue
        if key in out:
            continue
        out[key] = {"label": label, "group": grp, "code": code, "years": years}
        order.append(key)
    return out, order


def _series(tabs, kind):
    """Merge a table's editions: newest edition wins per (key, year); labels,
    groups and order from the newest edition that has the key."""
    merged, order = {}, []
    for rel_no, rows in tabs.get(kind, []):
        parsed, keys = _parse(rows, f"{kind} {rel_no}")
        for k in keys:
            p = parsed[k]
            if k not in merged:
                merged[k] = {"label": p["label"], "group": p["group"], "code": p["code"],
                             "years": {}}
                order.append(k)
            for y, v in p["years"].items():
                merged[k]["years"].setdefault(y, v)
    return merged, order


def _tables(frames):
    """{kind: [(release_no, rows)]} newest first. Every edition is classified
    by its own title, so a stem CBS renumbered between editions never feeds
    another table's series; for one release, the first stem (by number) that
    carries the kind wins."""
    found = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        for key, no, rows in _editions(frames[n], n):
            k = _kind(_title(rows))
            if k is None:
                continue
            found.setdefault(k, {}).setdefault(no, (key, rows))
    out = {}
    for k, eds in found.items():
        ordered = sorted(eds.items(), key=lambda e: e[1][0], reverse=True)
        out[k] = [(no, rows) for no, (_key, rows) in ordered]
    return out


# ── small helpers ────────────────────────────────────────────────────────


def _bn(v):
    """Million $ → billion $, one decimal, as text."""
    return fmt.num_he(abs(v) / 1000, 1)


def _r1(v):
    return None if v is None else round(v, 1)


def _signed_bn(v):
    s = fmt.num_he(abs(v) / 1000, 1)
    if float(s.replace(",", "")) == 0:
        return s
    return (fmt.MINUS if v < 0 else "") + s


def _val(series, key, year):
    s = series.get(key)
    return None if s is None else s["years"].get(year)


def _change_word(ch, up, down, flat="ללא שינוי של ממש"):
    if abs(ch) < 0.01:
        return flat
    return up if ch > 0 else down


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    for k, t in (("imp", "יבוא תעשייתי"), ("exp", "יצוא תעשייתי")):
        if k not in tabs:
            raise ValueError(f"table '{t}' not found in any input")

    imp, imp_order = _series(tabs, "imp")
    exp, exp_order = _series(tabs, "exp")
    if TOTAL not in imp or TOTAL not in exp:
        raise ValueError("grand total row (סך הכל) missing")
    bal_pub, _ = _series(tabs, "bal") if "bal" in tabs else ({}, [])

    years = sorted(set(imp[TOTAL]["years"]) & set(exp[TOTAL]["years"]))
    if len(years) < 2:
        raise ValueError("fewer than two years with both exports and imports")
    ly, py = years[-1], years[-2]

    # Keys in the exports table's order, then any imports-only keys.
    keys = list(exp_order) + [k for k in imp_order if k not in exp]
    meta = {k: (exp.get(k) or imp.get(k)) for k in keys}

    def bal(k, y):
        b = _val(bal_pub, k, y)
        if b is not None:
            return b
        e, i = _val(exp, k, y), _val(imp, k, y)
        return None if e is None or i is None else e - i

    groups = [k for k in keys if k != TOTAL and meta[k]["group"] is None]
    groups.sort(key=lambda g: (GROUP_ORDER.index(g) if g in GROUP_ORDER else len(GROUP_ORDER), g))
    gshort = {g: GROUP_SHORT.get(g, g.replace("תעשיות ", "")) for g in groups}
    inds = [k for k in keys if meta[k]["group"] is not None]

    E = {y: _val(exp, TOTAL, y) for y in years}
    I_ = {y: _val(imp, TOTAL, y) for y in years}
    B = {y: bal(TOTAL, y) for y in years}

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── KPIs ──────────────────────────────────────────────────────────────
    e_ch = E[ly] / E[py] - 1 if E[py] else None
    i_ch = I_[ly] / I_[py] - 1 if I_[py] else None
    kpis["exports"] = {"value": round(E[ly], 1), "display": _bn(E[ly]),
                       "tone": "brand" if e_ch is None or abs(e_ch) < 0.03
                       else ("ok" if e_ch > 0 else "warn")}
    kpis["imports"] = {"value": round(I_[ly], 1), "display": _bn(I_[ly]), "tone": "brand"}
    worse = B[ly] < B[py]
    kpis["balance"] = {"value": round(B[ly], 1), "display": _signed_bn(B[ly]),
                       "tone": "ok" if B[ly] >= 0 else ("danger" if worse else "warn")}
    labels["exports_kpi"] = f"יצוא תעשייתי ב-{ly} (מיליארד $)"
    labels["imports_kpi"] = f"יבוא תעשייתי ב-{ly} (מיליארד $)"
    labels["balance_kpi"] = f"מאזן הסחר התעשייתי ב-{ly} (מיליארד $)"
    if e_ch is not None:
        kpis["exp_change"] = {"value": round(e_ch * 100, 1), "display": fmt.signed_pct(e_ch),
                              "tone": "brand" if abs(e_ch) < 0.03 else ("ok" if e_ch > 0 else "danger")}
        labels["exp_change_kpi"] = f"שינוי ביצוא לעומת {py}"
    if HIGH in exp and E[ly]:
        he = _val(exp, HIGH, ly)
        if he is not None:
            kpis["high_share"] = {"value": round(he / E[ly] * 100, 1),
                                  "display": fmt.pct(he / E[ly]), "tone": "info"}
            labels["high_share_kpi"] = f"חלק הטכנולוגיה העילית ביצוא ({ly})"
        hb = bal(HIGH, ly)
        if hb is not None:
            kpis["high_bal"] = {"value": round(hb, 1), "display": _signed_bn(hb),
                                "tone": "ok" if hb > 0 else "danger"}
            labels["high_bal_kpi"] = f"מאזן הטכנולוגיה העילית ב-{ly} (מיליארד $)"

    # ── chart: totals over time ───────────────────────────────────────────
    charts["trend"] = {"x": [str(y) for y in years],
                       "exp": [_r1(E[y]) for y in years], "imp": [_r1(I_[y]) for y in years],
                       "bal": [_r1(B[y]) for y in years]}
    tables["trend"] = [[str(y), fmt.int_he(E[y]), fmt.int_he(I_[y]),
                        (fmt.MINUS if B[y] < 0 else "") + fmt.int_he(abs(B[y]))] for y in years]
    labels["trend_note"] = (f"היצוא והיבוא של סחורות תעשייתיות (ללא יהלומים) בכל שנה מאז {years[0]}, "
                            f"במיליוני דולרים, והפער ביניהם: מאזן הסחר התעשייתי.")
    labels["trend_aria"] = f"יצוא, יבוא ומאזן תעשייתי, {years[0]} עד {ly}"

    # Deficit insight.
    if B[ly] < 0 and B[py] < 0:
        ch = abs(B[ly]) / abs(B[py]) - 1
        word = _change_word(ch, "התרחב", "הצטמצם")
        txt = (f"הגירעון בסחר התעשייתי (ללא יהלומים) הסתכם ב-{_bn(B[ly])} מיליארד דולר ב-{ly}, "
               f"לעומת {_bn(B[py])} מיליארד ב-{py}")
        txt += f": {word} ב-{fmt.pct(abs(ch))}." if abs(ch) >= 0.01 else f": {word}."
        add("deficit", txt)
    elif B[ly] < 0 <= B[py]:
        add("deficit", f"מאזן הסחר התעשייתי עבר לגירעון של {_bn(B[ly])} מיליארד דולר ב-{ly}, "
                       f"אחרי עודף של {_bn(B[py])} מיליארד ב-{py}.")
    elif B[ly] >= 0:
        add("deficit", f"מאזן הסחר התעשייתי (ללא יהלומים) הראה עודף של {_bn(B[ly])} מיליארד דולר ב-{ly}.")
    # Record deficit over the window.
    if len(years) >= 4 and B[ly] < 0 and all(B[ly] < B[y] for y in years[:-1]):
        labels_rec = f"זה הגירעון הגדול ביותר בכל השנים המוצגות ({years[0]}-{ly})."
        for i in insights:
            if i["id"] == "deficit":
                i["text_he"] += " " + labels_rec

    # Exports vs imports trend.
    if e_ch is not None and i_ch is not None:
        def move(ch, v):
            if abs(ch) < 0.01:
                return f"נותר כמעט ללא שינוי ועמד על {_bn(v)} מיליארד"
            return f"{'עלה' if ch > 0 else 'ירד'} ב-{fmt.pct(abs(ch))} ל-{_bn(v)} מיליארד"
        txt = f"ב-{ly} היצוא התעשייתי {move(e_ch, E[ly])} דולר, והיבוא {move(i_ch, I_[ly])}."
        peak = max(years, key=lambda y: (E[y], y))
        if peak != ly and E[ly] < E[peak] * 0.97:
            txt += (f" היצוא עדיין נמוך ב-{fmt.pct(1 - E[ly] / E[peak])} מהשיא של {peak} "
                    f"({_bn(E[peak])} מיליארד).")
        add("flows", txt)

    # ── by technology group ───────────────────────────────────────────────
    if groups:
        flags["groups"] = True
        charts["groupbal"] = {"x": [str(y) for y in years],
                              "series": [{"name": gshort[g], "data": [_r1(bal(g, y)) for y in years]}
                                         for g in groups]}
        tables["groupbal"] = [[str(y)] + [("–" if bal(g, y) is None else
                                           (fmt.MINUS if bal(g, y) < 0 else "") + fmt.int_he(abs(bal(g, y))))
                                          for g in groups] for y in years]
        labels["group_cols"] = ["שנה"] + [gshort[g] for g in groups]
        labels["groupbal_note"] = ("המאזן (יצוא פחות יבוא) בכל אחת מארבע קבוצות העוצמה הטכנולוגית, "
                                   "במיליוני דולרים. ערך חיובי הוא עודף, שלילי הוא גירעון.")
        labels["groupbal_aria"] = f"מאזן הסחר התעשייתי לפי עוצמה טכנולוגית, {years[0]} עד {ly}"

        for kind, src, tot in (("expmix", exp, E), ("impmix", imp, I_)):
            charts[kind] = {"x": [str(y) for y in years],
                            "series": [{"name": gshort[g], "data": [_r1(_val(src, g, y)) for y in years]}
                                       for g in groups]}
            tables[kind] = [[str(y)] + [("–" if _val(src, g, y) is None else
                                         f"{fmt.int_he(_val(src, g, y))} ({fmt.pct(_val(src, g, y) / tot[y])})")
                                        for g in groups] for y in years]
        labels["expmix_note"] = ("היצוא התעשייתי לפי עוצמה טכנולוגית, במיליוני דולרים. "
                                 "בטבלה: הסכום וחלקו מכלל היצוא התעשייתי באותה שנה.")
        labels["impmix_note"] = ("היבוא התעשייתי לפי עוצמה טכנולוגית, במיליוני דולרים. "
                                 "בטבלה: הסכום וחלקו מכלל היבוא התעשייתי באותה שנה.")
        labels["expmix_aria"] = f"יצוא תעשייתי לפי עוצמה טכנולוגית, {years[0]} עד {ly}"
        labels["impmix_aria"] = f"יבוא תעשייתי לפי עוצמה טכנולוגית, {years[0]} עד {ly}"

        # Coverage ratio: exports per dollar of imports.
        def ratio(g, y):
            e, i = _val(exp, g, y), _val(imp, g, y)
            return None if e is None or not i else e / i
        charts["ratio"] = {"x": [str(y) for y in years],
                           "series": [{"name": gshort[g], "data": [None if ratio(g, y) is None
                                                                   else round(ratio(g, y) * 100, 1)
                                                                   for y in years]}
                                      for g in groups] + [{"name": "כל התעשייה",
                                                           "data": [round(E[y] / I_[y] * 100, 1)
                                                                    for y in years]}]}
        tables["ratio"] = [[str(y)] + [("–" if ratio(g, y) is None else fmt.pct(ratio(g, y), 0))
                                       for g in groups] + [fmt.pct(E[y] / I_[y], 0)] for y in years]
        labels["ratio_cols"] = labels["group_cols"] + ["כל התעשייה"]
        labels["ratio_note"] = ("שיעור הכיסוי: היצוא כאחוז מהיבוא בכל קבוצה. מעל 100% הקבוצה מייצאת "
                                "יותר משהיא מייבאת.")
        labels["ratio_aria"] = f"היצוא כאחוז מהיבוא לפי עוצמה טכנולוגית, {years[0]} עד {ly}"

        gb = {g: bal(g, ly) for g in groups if bal(g, ly) is not None}
        surplus = [g for g in groups if gb.get(g) is not None and gb[g] > 0]
        if len(surplus) == 1:
            g = surplus[0]
            gp = bal(g, py)
            txt = (f"רק {GROUP_PHRASE.get(g, g)} מייצאות יותר משהן מייבאות: עודף של {_bn(gb[g])} מיליארד דולר "
                   f"ב-{ly}")
            if gp is not None and gp > 0 and abs(gb[g] / gp - 1) >= 0.05:
                txt += (f", {'גבוה' if gb[g] > gp else 'נמוך'} ב-{fmt.pct(abs(gb[g] / gp - 1))} "
                        f"מ-{py} ({_bn(gp)} מיליארד)")
            others = [x for x in groups if x != g and gb.get(x) is not None and gb[x] < 0]
            if len(others) == len(groups) - 1 and others:
                txt += ". כל שאר הקבוצות בגירעון"
            add("surplus", txt + ".")
        elif len(surplus) > 1:
            add("surplus", f"ב-{ly} {len(surplus)} קבוצות עוצמה טכנולוגית הראו עודף בסחר: "
                           f"{fmt.join_he(gshort[g] for g in surplus)}.")
        deficits = [g for g in groups if gb.get(g) is not None and gb[g] < 0]
        if deficits:
            g = min(deficits, key=lambda g: (gb[g], g))
            share = gb[g] / B[ly] if B[ly] < 0 else None
            if share is not None and share > 0.3:
                add("worst_group", f"הגירעון הגדול ביותר הוא ב{GROUP_PHRASE.get(g, g)}: {_bn(gb[g])} מיליארד "
                                   f"דולר ב-{ly}, {fmt.pct(share)} מהגירעון התעשייתי כולו.")

        he, hi = _val(exp, HIGH, ly), _val(imp, HIGH, ly)
        if he is not None and hi is not None and E[ly] and I_[ly]:
            se, si = he / E[ly], hi / I_[ly]
            if se - si >= 0.05:
                add("mix", f"הטכנולוגיה העילית היא {fmt.pct(se)} מהיצוא התעשייתי ב-{ly}, "
                           f"אבל רק {fmt.pct(si)} מהיבוא.")

    # ── industries, latest year ───────────────────────────────────────────
    best_key = None
    ib = [(k, bal(k, ly)) for k in inds if bal(k, ly) is not None]
    if len(ib) >= 4:
        flags["indbal"] = True
        top = sorted(ib, key=lambda kv: (-abs(kv[1]), meta[kv[0]]["label"]))[:N_INDBAL]
        top.sort(key=lambda kv: (kv[1], meta[kv[0]]["label"]))
        charts["indbal"] = {"names": [_short(meta[k]["label"]) for k, _ in top],
                            "full": [meta[k]["label"] for k, _ in top],
                            "groups": [gshort.get(meta[k]["group"], "") for k, _ in top],
                            "values": [_r1(v) for _, v in top]}
        tables["indbal"] = [[meta[k]["label"], gshort.get(meta[k]["group"], ""),
                             fmt.int_he(_val(exp, k, ly) or 0), fmt.int_he(_val(imp, k, ly) or 0),
                             (fmt.MINUS if v < 0 else "") + fmt.int_he(abs(v))]
                            for k, v in sorted(top, key=lambda kv: (-kv[1], meta[kv[0]]["label"]))]
        labels["indbal_note"] = (f"{len(top)} הענפים עם המאזן הגדול ביותר (בערך מוחלט) ב-{ly}, "
                                 f"מתוך {len(ib)} ענפי תעשייה, במיליוני דולרים.")
        labels["indbal_aria"] = f"מאזן הסחר לפי ענף תעשייה, {ly}"
        best = max(ib, key=lambda kv: (kv[1], meta[kv[0]]["label"]))
        worst = min(ib, key=lambda kv: (kv[1], meta[kv[0]]["label"]))
        if best[1] > 0:
            best_key = best[0]
            add("best_ind", f"הענף עם העודף הגדול ביותר הוא {meta[best[0]]['label']}: "
                            f"יצוא של {_bn(_val(exp, best[0], ly))} מיליארד דולר מול יבוא של "
                            f"{_bn(_val(imp, best[0], ly))} מיליארד ב-{ly}.")
        if worst[1] < 0:
            add("worst_ind", f"בין הענפים, הגירעון הגדול ביותר הוא ב{meta[worst[0]]['label']}: "
                             f"{_bn(worst[1])} מיליארד דולר ב-{ly} (יבוא של "
                             f"{_bn(_val(imp, worst[0], ly))} מיליארד, יצוא של "
                             f"{_bn(_val(exp, worst[0], ly))} מיליארד).")

    # Exports treemap: group → industry, latest year.
    ie = [(k, _val(exp, k, ly)) for k in inds if (_val(exp, k, ly) or 0) > 0]
    if len(ie) >= 4:
        flags["exptree"] = True
        tree = []
        for g in groups:
            kids = sorted(((_short(meta[k]["label"]), round(v, 1)) for k, v in ie if meta[k]["group"] == g),
                          key=lambda t: (-t[1], t[0]))
            if kids:
                tree.append({"name": gshort[g], "children": [{"name": n, "value": v} for n, v in kids]})
        charts["exptree"] = tree
        ranked = sorted(ie, key=lambda kv: (-kv[1], meta[kv[0]]["label"]))
        tables["exptree"] = [[meta[k]["label"], gshort.get(meta[k]["group"], ""), fmt.int_he(v),
                              fmt.pct(v / E[ly])] for k, v in ranked[:N_TREE_TABLE]]
        labels["exptree_note"] = (f"כל ענפי היצוא התעשייתי ב-{ly} לפי קבוצת עוצמה טכנולוגית; "
                                  f"גודל המלבן הוא היקף היצוא. בטבלה {min(len(ranked), N_TREE_TABLE)} "
                                  f"הענפים הגדולים.")
        labels["exptree_aria"] = f"יצוא תעשייתי לפי ענף, {ly}"
        k0, v0 = ranked[0]
        if k0 == best_key:
            for i in insights:
                if i["id"] == "best_ind":
                    i["text_he"] = (i["text_he"][:-1] + f". זה גם ענף היצוא הגדול: "
                                    f"{fmt.pct(v0 / E[ly])} מהיצוא התעשייתי.")
        else:
            add("top_exp", f"{meta[k0]['label']} הוא ענף היצוא הגדול: {_bn(v0)} מיליארד דולר "
                           f"ב-{ly}, {fmt.pct(v0 / E[ly])} מהיצוא התעשייתי.")

    # Movers: change in exports vs the previous year.
    mv = []
    for k in inds:
        a, b = _val(exp, k, ly), _val(exp, k, py)
        if a is not None and b is not None and a != b:
            mv.append((k, a - b, a, b))
    if len(mv) >= 4:
        flags["movers"] = True
        top = sorted(mv, key=lambda t: (-abs(t[1]), meta[t[0]]["label"]))[:N_MOVERS]
        top.sort(key=lambda t: (t[1], meta[t[0]]["label"]))
        charts["movers"] = {"names": [_short(meta[k]["label"]) for k, *_ in top],
                            "full": [meta[k]["label"] for k, *_ in top],
                            "values": [_r1(d) for _, d, *_ in top]}
        tables["movers"] = [[meta[k]["label"], fmt.int_he(b), fmt.int_he(a),
                             ("+" if d > 0 else fmt.MINUS) + fmt.int_he(abs(d)),
                             fmt.signed_pct(a / b - 1) if b else "–"]
                            for k, d, a, b in sorted(top, key=lambda t: (-t[1], meta[t[0]]["label"]))]
        labels["movers_cols"] = ["ענף", str(py), str(ly), "שינוי", "שינוי באחוזים"]
        labels["movers_note"] = (f"{len(top)} הענפים שהיצוא שלהם השתנה הכי הרבה (במיליוני דולרים) "
                                 f"בין {py} ל-{ly}.")
        labels["movers_aria"] = f"שינוי ביצוא לפי ענף, {py} עד {ly}"
        up = max(mv, key=lambda t: (t[1], meta[t[0]]["label"]))
        dn = min(mv, key=lambda t: (t[1], meta[t[0]]["label"]))
        parts = []
        if up[1] >= 100:
            parts.append(f"ב{meta[up[0]]['label']} עלה ב-{fmt.int_he(up[1])} מיליון דולר")
        if dn[1] <= -100:
            parts.append(f"ב{meta[dn[0]]['label']} ירד ב-{fmt.int_he(abs(dn[1]))} מיליון")
        if parts:
            add("movers", f"בין {py} ל-{ly} היצוא " + " והיצוא ".join(parts) + ".")

    if len(insights) < 1:
        raise ValueError("no insight survived")

    # ── text ──────────────────────────────────────────────────────────────
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    bal_word = "גירעון" if B[ly] < 0 else "עודף"
    labels["lede"] = (f"כמה ישראל מייצאת ומייבאת בכל ענף תעשייה, ומה המאזן בין טכנולוגיה עילית "
                      f"לתעשייה מסורתית. הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה "
                      f"(הלמ\"ס), במיליוני דולרים וללא יהלומים, ומתעדכנים עם כל הודעה חדשה. "
                      f"ב-{ly}: יצוא של {_bn(E[ly])} מיליארד דולר, יבוא של {_bn(I_[ly])} מיליארד, "
                      f"ו{bal_word} של {_bn(B[ly])} מיליארד.")
    summary = (f"יצוא ויבוא תעשייתי לפי עוצמה טכנולוגית (הלמ\"ס): ב-{ly} יצוא של {_bn(E[ly])} "
               f"מיליארד דולר, יבוא של {_bn(I_[ly])} מיליארד ו{bal_word} של {_bn(B[ly])} מיליארד.")
    desc = (f"היצוא והיבוא התעשייתי של ישראל לפי ענף ועוצמה טכנולוגית: {bal_word} של {_bn(B[ly])} "
            f"מיליארד דולר ב-{ly}, יצוא {_bn(E[ly])} מיליארד.")

    order = ("deficit", "surplus", "flows", "mix", "worst_group", "worst_ind", "best_ind",
             "top_exp", "movers")
    rank = {k: i for i, k in enumerate(order)}
    insights.sort(key=lambda i: rank.get(i["id"], len(order)))

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0]}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "יצוא ויבוא תעשייתי לפי עוצמה טכנולוגית | הלמ\"ס",
                "description": desc,
                "name": "מאזן היצוא והיבוא התעשייתי לפי עוצמה טכנולוגית",
                "alternate_names": ["יצוא הייטק מישראל", "מאזן הסחר התעשייתי",
                                    "יצוא תעשייתי לפי ענף", "יצוא טכנולוגיה עילית",
                                    "מאזן יצוא ויבוא תעשייתי לפי עצמה טכנולוגית"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": flags,
        "years": {"first": str(years[0]), "last": str(ly)},
    }
