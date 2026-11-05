"""היצע וביקוש בשוק העבודה: CBS's quarterly labour supply-and-demand release.

The release joins the Labour Force Survey (who looks for work) with the Job
Vacancy Survey (how many jobs employers can't fill). Its key measure is the
supply-to-demand ratio: job seekers per vacancy. Below 1 there are more open
jobs than people looking for them.

Inputs, all grids of the newest edition:
  t2   vacancies and ratio by occupation (major groups and selected detailed
       occupations), one column pair per quarter for the last 5-8 quarters,
       plus the relative sampling error of the latest ratio
  t3   vacancies, employed and the three supply components (employed looking
       for another job, unemployed, out of the labour force but looked for
       work this year) by major group, one block per quarter of this year
  t4   chart data: total ratio, ratio in known occupations, vacancies by
       quarter (about ten quarters)
  t6, t8, ..., t18  chart data: ratio and vacancies by quarter for each of
       the seven major occupation groups
  releases  the edition list (number, date, headline, link)

The yearly edition (October-December plus the whole year) has a different
table layout; source.json's title_regex leaves it out.

Header rows and columns are found by label (govlib.cbs) and raise when
missing; data rows are found by pattern, so a missing one shortens a series.
"""
import re

import pandas as pd
from govlib import cbs, fmt

GROUP_TABLES = ("t6", "t8", "t10", "t12", "t14", "t16", "t18")
# Short names for the seven major occupation groups (2011 classification).
# An unknown name falls through unchanged.
SHORT = {
    "מנהלים": "מנהלים",
    "בעלי משלח יד אקדמי": "אקדמאים",
    "הנדסאים, טכנאים, סוכנים ובעלי משלח יד נלווה": "הנדסאים וטכנאים",
    "פקידים כלליים ועובדי משרד": "פקידים ועובדי משרד",
    "עובדי מכירות ושירותים": "מכירות ושירותים",
    "עובדים מקצועיים בתעשייה ובבינוי ועובדים מקצועיים אחרים": "עובדים מקצועיים",
    "עובדים בלתי מקצועיים": "עובדים בלתי מקצועיים",
}
CODE = re.compile(r"^(\d+)(?:-(\d+))?$")
QUARTER_HE = re.compile(r"^([IV]+) רבע$")
QUARTER_EN = re.compile(r"Quarter\s+([IV]+)\b")
TOP_OCC = 15
TOP_TIGHT = 12


def _norm(name):
    return re.sub(r"\s+", " ", name.replace("-", " ")).strip()


SHORT_N = {_norm(k): v for k, v in SHORT.items()}


def short(name):
    return SHORT_N.get(_norm(name), name)


def _q(t):
    """(2026, 2) → "2/2026"."""
    return f"{t[1]}/{t[0]}"


def _qname(t):
    return f"הרבעון ה{('ראשון', 'שני', 'שלישי', 'רביעי')[t[1] - 1]} של {t[0]}"


def _qin(t):
    """(2026, 2) → "ברבעון השני של 2026"."""
    return "ב" + _qname(t)[1:]


def _qlong(t):
    return f"רבעון {t[1]} {t[0]}"


def _r1(v):
    return fmt.num_he(v, 1) if v is not None else "–"


def _r2(v):
    return round(v, 2) if v is not None else None


def _signed(v):
    """A ratio change with one decimal, minus as U+2212: −0.1, +0.2, 0.0."""
    r = round(v, 1)
    if r == 0:
        return "0.0"
    return ("+" if r > 0 else "\u2212") + fmt.num_he(abs(v), 1)


# ── tables ───────────────────────────────────────────────────────────────


def _series(rows, name, known=False):
    """Chart-data table: [(period, ratio, vacancies[, known ratio])] and the
    table's title (the group name)."""
    h = cbs.row_with(rows, "יחס בין היצע לביקוש", name=name)
    ratio = cbs.col_after(rows[h], "יחס בין היצע לביקוש", 0)
    vac = cbs.col_after(rows[h], "משרות פנויות", 0)
    kcol = cbs.col_after(rows[h], "במשלחי יד ידועים", 0, contains=True) if known else None
    title = next((c for c in rows[h - 1] if c), "") if h > 0 else ""
    if not title or title.startswith(("פורסם", "הלשכה")):
        raise ValueError(f"{name}: group title row not found")
    out = []
    for i, y, q, end in cbs.periods(rows, h + 1, len(rows)):
        if q is None or end or q > 4:
            continue
        r, v = cbs.val(rows[i], ratio), cbs.val(rows[i], vac)
        if r is None and v is None:
            continue
        rec = {"t": (y, q), "ratio": r, "vac": v}
        if known:
            rec["known"] = cbs.val(rows[i], kcol)
        out.append(rec)
    out.sort(key=lambda r: r["t"])
    return out, title


def _t2(rows):
    """Occupations × quarters: [{code, name, level, q: {(y, q): (vac, ratio)}}],
    the quarter list, and the latest ratio's relative sampling error by code."""
    h = cbs.row_with(rows, "מספר משרות פנויות", name="t2")
    qrow = next((i for i in range(h - 1, -1, -1)
                 if sum(bool(QUARTER_HE.match(c)) for c in rows[i]) >= 2), None)
    if qrow is None:
        raise ValueError("t2: quarter header row not found")
    yrow = next((i for i in range(qrow - 1, -1, -1)
                 if any(cbs.YEAR.match(c) for c in rows[i])), None)
    if yrow is None:
        raise ValueError("t2: year header row not found")
    years = [(j, int(c)) for j, c in enumerate(rows[yrow]) if cbs.YEAR.match(c)]
    cols = []
    for j, c in enumerate(rows[h]):
        if c != "מספר משרות פנויות":
            continue
        rj = cbs.col_after(rows[h], "היחס בין היצע לביקוש", j)
        qm = QUARTER_HE.match(cbs.cell(rows[qrow], j))
        yr = [y for yj, y in years if yj <= j]
        if not qm or qm.group(1) not in cbs.ROMAN or not yr:
            raise ValueError(f"t2: no quarter/year above column {j}")
        cols.append(((yr[-1], cbs.ROMAN[qm.group(1)]), j, rj))
    if not cols:
        raise ValueError("t2: no quarter columns")
    try:
        err = cbs.col_after(rows[h], "טעות דגימה", 0, contains=True)
    except ValueError:
        err = None
    occ, seen = [], set()
    for r in rows[h + 1:]:
        if cbs.cell(r, 0).startswith("מקורות"):
            break
        code, name = cbs.cell(r, 0), cbs.cell(r, 1)
        m = CODE.match(code)
        if name.startswith("סך הכל") and not code:
            code, level = "total" if "ידוע" not in name else "known", 0
        elif m:
            level = 1 if m.group(2) and len(m.group(1)) == 1 else len(m.group(1))
        else:
            continue
        if code in seen or not name:
            continue
        q = {}
        for t, vj, rj in cols:
            v, ra = cbs.val(r, vj), cbs.val(r, rj)
            if v is not None or ra is not None:
                q[t] = (v, ra)
        if not q:
            continue
        seen.add(code)
        occ.append({"code": code, "name": name, "level": level, "q": q,
                    "err": cbs.val(r, err) if err is not None else None})
    quarters = sorted({t for t, _, _ in cols})
    return occ, quarters


def _t3(rows):
    """The newest quarter block: (period, {code: {...}}, total incl. unknown)."""
    h = cbs.row_with(rows, "Number of job vacancies", name="t3", contains=True)
    col = {"vac": cbs.col_after(rows[h], "Number of job vacancies", 0, contains=True),
           "emp": cbs.col_after(rows[h], "Employed persons", 0),
           "supply": cbs.col_after(rows[h], "Total supply", 0, contains=True),
           "looking": cbs.col_after(rows[h], "looking for another job", 0, contains=True),
           "unemp": cbs.col_after(rows[h], "Unemployed", 0, contains=True),
           "outside": cbs.col_after(rows[h], "Not in the weekly labour force", 0,
                                    contains=True),
           "ratio": cbs.col_after(rows[h], "Supply - to - demand", 0, contains=True)}
    blocks, year = [], None
    for i in range(len(rows)):
        ys = [c for c in rows[i] if cbs.YEAR.match(c)]
        if ys and len([c for c in rows[i] if c]) == 1:
            year = int(ys[0])
        qm = next((QUARTER_EN.search(c) for c in rows[i] if QUARTER_EN.search(c)), None)
        if qm and qm.group(1) in cbs.ROMAN and i > h:
            if year is None:
                raise ValueError("t3: quarter block without a year")
            blocks.append((i, (year, cbs.ROMAN[qm.group(1)])))
    if not blocks:
        raise ValueError("t3: no quarter block")
    for n in range(len(blocks) - 1, -1, -1):
        start, t = blocks[n]
        stop = blocks[n + 1][0] if n + 1 < len(blocks) else len(rows)
        groups, total = {}, None
        for r in rows[start + 1:stop]:
            if cbs.cell(r, 0).startswith("מקורות"):
                break
            rec = {k: cbs.val(r, j) for k, j in col.items()}
            if rec["vac"] is None or rec["supply"] is None:
                continue
            code, name = cbs.cell(r, 0), cbs.cell(r, 1)
            if CODE.match(code):
                groups[code] = rec | {"name": name}
            elif name.startswith("סך כולל"):
                total = rec
        if groups and total:
            return t, groups, total
    raise ValueError("t3: no complete quarter block")


# ── helpers ──────────────────────────────────────────────────────────────


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _code_key(code):
    m = CODE.match(code)
    return (int(m.group(1)[0]), code) if m else (99, code)


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    total, _ = _series(cbs.grid(frames["t4"], "t4"), "t4", known=True)
    total = [r for r in total if r["ratio"] is not None]
    if not total:
        raise ValueError("t4: no quarterly rows")
    groups = []
    for t in GROUP_TABLES:
        s, title = _series(cbs.grid(frames[t], t), t)
        if s:
            groups.append({"name": title, "short": short(title), "s": s})
    occ, quarters = _t2(cbs.grid(frames["t2"], "t2"))
    t3_t, t3_groups, t3_total = _t3(cbs.grid(frames["t3"], "t3"))

    lt = total[-1]["t"]
    last = total[-1]
    by_t = {r["t"]: r for r in total}
    prev = by_t.get((lt[0] - 1, lt[1]))
    ratio_chg = (last["ratio"] - prev["ratio"]) if prev else None
    vac_chg = _chg(last["vac"], prev["vac"] if prev else None)

    # t2: the newest quarter it covers, and the same quarter a year before.
    q2 = quarters[-1]
    q2_prev = (q2[0] - 1, q2[1]) if (q2[0] - 1, q2[1]) in quarters else None
    majors = [o for o in occ if o["level"] == 1 and q2 in o["q"]
              and o["q"][q2][1] is not None]
    majors.sort(key=lambda o: (o["q"][q2][1], o["code"]))
    detail = [o for o in occ if o["level"] >= 2 and q2 in o["q"]]
    subs = [o for o in detail if o["level"] == 2 and o["q"][q2][0] is not None]

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    rt = last["ratio"]
    kpis["ratio"] = {"value": round(rt, 2), "display": fmt.num_he(rt, 1),
                     "tone": "danger" if rt < 1 else "warn" if rt < 1.5 else "brand"}
    labels["ratio_kpi"] = f"מחפשי עבודה לכל משרה פנויה, {_qlong(lt)}"
    if last["vac"] is not None:
        kpis["vac"] = {"value": round(last["vac"]), "display": fmt.int_he(last["vac"]),
                       "tone": "brand"}
        labels["vac_kpi"] = f"משרות פנויות, {_qlong(lt)}"
    if ratio_chg is not None:
        kpis["chg"] = {"value": round(ratio_chg, 2),
                       "display": _signed(ratio_chg),
                       "tone": "warn" if ratio_chg <= -0.05 else "info" if ratio_chg >= 0.05
                       else "brand"}
        labels["chg_kpi"] = f"שינוי ביחס לעומת {_qlong(prev['t'])}"
    kpis["supply"] = {"value": round(t3_total["supply"], 1),
                      "display": fmt.num_he(t3_total["supply"], 1), "tone": "brand"}
    labels["supply_kpi"] = f"מחפשי עבודה, {_qlong(t3_t)} (אלפים)"
    kpis["unemp"] = {"value": round(t3_total["unemp"], 1),
                     "display": fmt.num_he(t3_total["unemp"], 1), "tone": "brand"}
    labels["unemp_kpi"] = f"מתוכם בלתי מועסקים, {_qlong(t3_t)} (אלפים)"

    charts, tables, flags = {}, {}, {}

    # ── total over time ──────────────────────────────────────────────────
    charts["trend"] = {"x": [_q(r["t"]) for r in total],
                       "ratio": [_r2(r["ratio"]) for r in total],
                       "known": [_r2(r.get("known")) for r in total],
                       "vac": [round(r["vac"]) if r["vac"] is not None else None
                               for r in total]}
    tables["trend"] = [[_qlong(r["t"]), _r1(r["ratio"]), _r1(r.get("known")),
                        fmt.int_he(r["vac"]) if r["vac"] is not None else "–"]
                       for r in reversed(total)]

    # ── groups, latest quarter ───────────────────────────────────────────
    flags["groups"] = len(majors) >= 3
    if flags["groups"]:
        known = next((o for o in occ if o["code"] == "known"), None)
        charts["groups"] = {"names": [short(o["name"]) for o in majors],
                            "ratio": [_r2(o["q"][q2][1]) for o in majors],
                            "known": _r2(known["q"][q2][1]) if known and q2 in known["q"]
                            and known["q"][q2][1] is not None else None}
        tables["groups"] = [[o["name"], fmt.int_he(o["q"][q2][0])
                             if o["q"][q2][0] is not None else "–",
                             _r1(o["q"][q2][1]),
                             _r1(o["q"].get(q2_prev, (None, None))[1]) if q2_prev else "–"]
                            for o in majors]

    # ── groups over time ─────────────────────────────────────────────────
    flags["gtrend"] = len(groups) >= 3
    if flags["gtrend"]:
        gx = sorted({r["t"] for g in groups for r in g["s"]})
        charts["gtrend"] = {"x": [_q(t) for t in gx],
                            "names": [g["short"] for g in groups],
                            "ratio": [[_r2({r["t"]: r["ratio"] for r in g["s"]}.get(t))
                                       for t in gx] for g in groups],
                            "vac": [[round(v) if (v := {r["t"]: r["vac"]
                                                        for r in g["s"]}.get(t)) is not None
                                     else None for t in gx] for g in groups]}
        tables["gtrend"] = []
        tables["gvac"] = []
        for g in groups:
            s = g["s"]
            tables["gtrend"].append([g["name"], _q(s[0]["t"]), _r1(s[0]["ratio"]),
                                     _r1(s[-1]["ratio"]),
                                     fmt.num_he(min(r["ratio"] for r in s
                                                    if r["ratio"] is not None), 1)])
            tables["gvac"].append([g["name"]] + [
                fmt.int_he(v) if (v := {r["t"]: r["vac"] for r in s}.get(t)) is not None
                else "–" for t in gx[-4:]])
        labels["gvac_cols"] = ["משלח יד"] + [_q(t) for t in gx[-4:]]

    # ── supply components ────────────────────────────────────────────────
    sg = sorted(t3_groups.items(), key=lambda kv: _code_key(kv[0]))
    sg = [(c, g) for c, g in sg if g["supply"]]
    flags["supply"] = len(sg) >= 3
    if flags["supply"]:
        parts = ("looking", "unemp", "outside")
        charts["supply"] = {"names": [short(g["name"]) for _, g in sg]}
        for p in parts:
            charts["supply"][p] = [round((g[p] or 0) / g["supply"] * 100, 1) for _, g in sg]
            charts["supply"][p + "_k"] = [round(g[p] or 0, 1) for _, g in sg]
        tables["supply"] = [[g["name"], fmt.num_he(g["supply"], 1)]
                            + [fmt.pct((g[p] or 0) / g["supply"]) for p in parts]
                            for _, g in sg]
        tables["supply"].append(["סך הכל (כולל משלח יד לא ידוע)",
                                 fmt.num_he(t3_total["supply"], 1)]
                                + [fmt.pct((t3_total[p] or 0) / t3_total["supply"])
                                   for p in parts])

    # ── occupations by vacancies ─────────────────────────────────────────
    flags["occ"] = len(subs) >= 3
    if flags["occ"]:
        top = sorted(subs, key=lambda o: (-o["q"][q2][0], o["code"]))[:TOP_OCC]
        charts["occ"] = {"names": [o["name"] for o in top],
                         "vac": [round(o["q"][q2][0]) for o in top],
                         "ratio": [_r2(o["q"][q2][1]) for o in top]}
        tables["occ"] = [[o["name"], fmt.int_he(o["q"][q2][0]), _r1(o["q"][q2][1])]
                         for o in top]

    # ── tightest occupations ─────────────────────────────────────────────
    rated = [o for o in detail if o["q"][q2][1] is not None]
    flags["tight"] = len(rated) >= 5
    if flags["tight"]:
        tight = sorted(rated, key=lambda o: (o["q"][q2][1], o["code"]))[:TOP_TIGHT]
        charts["tight"] = {"names": [o["name"] for o in tight],
                           "ratio": [_r2(o["q"][q2][1]) for o in tight]}
        tables["tight"] = [[o["name"], _r1(o["q"][q2][1]),
                            fmt.int_he(o["q"][q2][0]) if o["q"][q2][0] is not None else "–",
                            fmt.pct(o["err"], 0) if o["err"] is not None else "–"]
                           for o in tight]

    # ── year-on-year change by occupation (dumbbell) ─────────────────────
    moved = []
    if q2_prev:
        moved = [o for o in subs if o["q"][q2][1] is not None
                 and o["q"].get(q2_prev, (None, None))[1] is not None]
    flags["change"] = len(moved) >= 4
    if flags["change"]:
        moved.sort(key=lambda o: (o["q"][q2][1] - o["q"][q2_prev][1], o["code"]))
        charts["change"] = {"names": [o["name"] for o in moved],
                            "before": [_r2(o["q"][q2_prev][1]) for o in moved],
                            "after": [_r2(o["q"][q2][1]) for o in moved],
                            "before_label": _q(q2_prev), "after_label": _q(q2)}
        tables["change"] = [[o["name"], _r1(o["q"][q2_prev][1]), _r1(o["q"][q2][1])]
                            for o in moved]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if t3_total["vac"]:
        r = t3_total["supply"] / t3_total["vac"]
        add("level", f"{_qin(t3_t)} היו {fmt.num_he(t3_total['supply'], 1)} אלף מחפשי "
                     f"עבודה מול {fmt.num_he(t3_total['vac'], 1)} אלף משרות פנויות: "
                     f"{fmt.num_he(r, 1)} מחפשי עבודה לכל משרה פנויה.")
    if ratio_chg is not None:
        if ratio_chg <= -0.05:
            add("yoy", f"שוק העבודה התהדק בשנה האחרונה: היחס בין היצע לביקוש ירד מ-"
                       f"{_r1(prev['ratio'])} {_qin(prev['t'])} ל-{_r1(rt)} {_qin(lt)}, "
                       f"כלומר פחות מחפשי עבודה על כל משרה.")
        elif ratio_chg >= 0.05:
            add("yoy", f"שוק העבודה התרופף בשנה האחרונה: היחס בין היצע לביקוש עלה מ-"
                       f"{_r1(prev['ratio'])} {_qin(prev['t'])} ל-{_r1(rt)} {_qin(lt)}, "
                       f"כלומר יותר מחפשי עבודה על כל משרה.")
        else:
            add("yoy", f"היחס בין היצע לביקוש כמעט לא השתנה בשנה האחרונה: {_r1(rt)} "
                       f"{_qin(lt)}, לעומת {_r1(prev['ratio'])} {_qin(prev['t'])}.")
    if vac_chg is not None and abs(vac_chg) >= 0.02:
        add("vac", f"מספר המשרות הפנויות {_qin(lt)}: {fmt.int_he(last['vac'])}, "
                   f"{'עלייה' if vac_chg > 0 else 'ירידה'} של {fmt.pct(abs(vac_chg))} "
                   f"לעומת הרבעון המקביל אשתקד.")
    if len(majors) >= 3:
        lo, hi = majors[0], majors[-1]
        lo_r, hi_r = lo["q"][q2][1], hi["q"][q2][1]
        if hi_r >= 2 * lo_r:
            add("gap", f"הפער בין משלחי היד גדול: בקרב {short(lo['name'])} יש "
                       f"{_r1(lo_r)} מחפשי עבודה לכל משרה פנויה"
                       + (", כלומר יותר משרות ממחפשים" if lo_r < 1 else "")
                       + f", ובקרב {short(hi['name'])} {_r1(hi_r)}.")
    if len(rated) >= 5:
        under = [o for o in rated if o["q"][q2][1] < 1]
        worst = min(rated, key=lambda o: (o["q"][q2][1], o["code"]))
        if under:
            add("under", f"ב-{len(under)} מתוך {len(rated)} משלחי היד המפורטים שהלמ\"ס מפרסם "
                         f"להם יחס, יש יותר משרות פנויות ממחפשי עבודה (יחס נמוך מ-1). "
                         f"המחסור החריף ביותר: {worst['name']} ({_r1(worst['q'][q2][1])}).")
    if t3_total["supply"]:
        u = (t3_total["unemp"] or 0) / t3_total["supply"]
        lk = (t3_total["looking"] or 0) / t3_total["supply"]
        add("supply", f"{'רק ' if u < 0.5 else ''}{fmt.pct(u)} ממחפשי העבודה הם בלתי מועסקים. "
                      f"{fmt.pct(lk)} כבר מועסקים ומחפשים עבודה אחרת או שעות נוספות, והשאר "
                      f"אינם בכוח העבודה אך חיפשו עבודה בשנה האחרונה.")
    if flags["occ"]:
        o = charts["occ"]
        add("occ", f"הכי הרבה משרות פנויות {_qin(q2)} היו בקרב {o['names'][0]}: "
                   f"{fmt.int_he(o['vac'][0])} משרות.")
    if flags["change"]:
        a, b = moved[0], moved[-1]
        da = a["q"][q2][1] - a["q"][q2_prev][1]
        if da <= -0.3:
            add("tighter", f"ההתהדקות החדה ביותר בשנה: {a['name']}, מ-{_r1(a['q'][q2_prev][1])} "
                           f"ל-{_r1(a['q'][q2][1])} מחפשי עבודה למשרה.")
        db = b["q"][q2][1] - b["q"][q2_prev][1]
        if db >= 0.3:
            add("looser", f"ההתרופפות החדה ביותר בשנה: {b['name']}, מ-{_r1(b['q'][q2_prev][1])} "
                          f"ל-{_r1(b['q'][q2][1])} מחפשי עבודה למשרה.")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"כמה מחפשי עבודה יש בישראל על כל משרה פנויה, ובאילו מקצועות המעסיקים "
                 f"מתקשים למצוא עובדים. הלמ\"ס משלבת את סקר כוח אדם (מי מחפש עבודה) עם סקר "
                 f"המשרות הפנויות (כמה משרות מחכות לעובדים), והנתונים מתעדכנים בכל רבעון. "
                 f"{_qin(lt)}: {_r1(rt)} מחפשי עבודה לכל משרה פנויה."),
        "trend_note": (f"היחס בין היצע העבודה לביקוש (מחפשי עבודה לכל משרה פנויה) ומספר "
                       f"המשרות הפנויות בכל רבעון מאז {_qlong(total[0]['t'])}. יחס נמוך פירושו "
                       f"שוק עבודה הדוק: מעט מחפשים על כל משרה."),
        "trend_aria": f"יחס היצע לביקוש ומשרות פנויות, {_qlong(total[0]['t'])} עד {_qlong(lt)}",
        "trend_caption": "יחס היצע לביקוש ומשרות פנויות לפי רבעון",
    })
    if flags["groups"]:
        labels.update({
            "groups_note": (f"מחפשי עבודה לכל משרה פנויה בכל קבוצת משלח יד, {_qin(q2)}. "
                            f"הקו האדום מסמן יחס של 1: משמאלו יש יותר משרות ממחפשים."),
            "groups_aria": f"יחס היצע לביקוש לפי משלח יד, {_qlong(q2)}",
            "groups_caption": f"משרות פנויות ויחס היצע לביקוש לפי משלח יד, {_qlong(q2)}",
            "groups_prev_col": f"יחס ב{_qlong(q2_prev)}" if q2_prev else "יחס לפני שנה",
        })
    if flags["gtrend"]:
        gtop = max(groups, key=lambda g: (g["s"][-1]["vac"] or 0, g["name"]))
        labels.update({
            "gtrend_note": ("היחס בין היצע לביקוש בכל קבוצת משלח יד, רבעון אחר רבעון. "
                            "אפשר ללחוץ על שם בקבוצה כדי להסתיר או להציג אותה."),
            "gtrend_aria": "יחס היצע לביקוש לפי קבוצת משלח יד ורבעון",
            "gtrend_caption": "יחס היצע לביקוש לפי משלח יד: ראשון, אחרון ושפל",
            "gvac_note": (f"מספר המשרות הפנויות בכל רבעון, לפי קבוצת משלח יד. ברבעון האחרון "
                          f"הכי הרבה משרות פנויות היו בקבוצת {gtop['short']}: "
                          f"{fmt.int_he(gtop['s'][-1]['vac'])}."),
            "gvac_aria": "משרות פנויות לפי קבוצת משלח יד ורבעון",
            "gvac_caption": "משרות פנויות לפי משלח יד, ארבעת הרבעונים האחרונים",
        })
    if flags["supply"]:
        labels.update({
            "supply_note": (f"מי הם מחפשי העבודה בכל קבוצת משלח יד, {_qin(t3_t)}: "
                            f"מועסקים שמחפשים עבודה אחרת או יותר שעות, בלתי מועסקים, ומי שאינם "
                            f"בכוח העבודה אך חיפשו עבודה בשנה האחרונה."),
            "supply_aria": f"רכיבי היצע העבודה לפי משלח יד, {_qlong(t3_t)}",
            "supply_caption": f"רכיבי היצע העבודה לפי משלח יד, {_qlong(t3_t)}",
        })
    if flags["occ"]:
        labels.update({
            "occ_note": (f"משלחי היד (ברמת תת-סדר) עם הכי הרבה משרות פנויות {_qin(q2)}, "
                         f"מתוך המשלחים שהלמ\"ס מפרסם בפירוט."),
            "occ_aria": f"משלחי יד עם הכי הרבה משרות פנויות, {_qlong(q2)}",
            "occ_caption": f"משרות פנויות לפי משלח יד, {_qlong(q2)}",
        })
    if flags["tight"]:
        labels.update({
            "tight_note": (f"משלחי היד המפורטים עם הכי מעט מחפשי עבודה לכל משרה פנויה "
                           f"{_qin(q2)}: כאן המעסיקים מתקשים ביותר למצוא עובדים. "
                           f"בטבלה גם טעות הדגימה היחסית של היחס."),
            "tight_aria": f"משלחי היד עם המחסור הגדול ביותר בעובדים, {_qlong(q2)}",
            "tight_caption": f"משלחי היד עם היחס הנמוך ביותר, {_qlong(q2)}",
        })
    if flags["change"]:
        labels.update({
            "change_note": (f"היחס בין היצע לביקוש בכל משלח יד {_qin(q2_prev)} (נקודה "
                            f"אפורה) ו{_qin(q2)} (נקודה כחולה). למעלה: משלחי היד שבהם "
                            f"השוק התהדק הכי הרבה."),
            "change_aria": f"שינוי ביחס היצע לביקוש לפי משלח יד, {_qlong(q2_prev)} מול {_qlong(q2)}",
            "change_caption": f"יחס היצע לביקוש לפי משלח יד, {_qlong(q2_prev)} מול {_qlong(q2)}",
        })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"משרות פנויות ומחפשי עבודה בישראל לפי משלח יד ורבעון, מנתוני הלמ\"ס. "
               f"{_qin(lt)}: {_r1(rt)} מחפשי עבודה לכל משרה פנויה"
               + (f" ו-{fmt.int_he(last['vac'])} משרות פנויות" if last["vac"] else "") + ".")
    desc = (f"כמה מחפשי עבודה יש על כל משרה פנויה ובאילו מקצועות חסרים עובדים: "
            f"{_r1(rt)} {_qin(lt)}, "
            + (f"{fmt.int_he(last['vac'])} משרות פנויות." if last["vac"] else "לפי משלח יד."))
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{total[0]['t'][0]}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "משרות פנויות ומחפשי עבודה לפי מקצוע | הלמ\"ס",
                "description": desc,
                "name": "היצע וביקוש בשוק העבודה",
                "alternate_names": ["היחס בין היצע לביקוש בשוק העבודה",
                                    "מחפשי עבודה לכל משרה פנויה",
                                    "מחסור בעובדים לפי מקצוע",
                                    "היצע וביקוש בשוק העבודה בישראל"],
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
