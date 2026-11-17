"""חברות הזנק (סטארט-אפ) בישראל: CBS's yearly start-up release.

The release is a set of tables ("לוח N - ...") and chart-data sheets
("תרשים N - ..."), and their NUMBERS MOVE between editions (capital raising
by round was תרשים 6 in two editions and 7 in the next; the mature-company
series moved from t12 to t14). So every table input (t1..t17, the last three
spare slots, all optional) is read with `cbs.grid`, and each table is found
by its TITLE text, not by its stem:

  main      פתיחות, סגירות, חברות פעילות, משרות שכיר ושכר (yearly, 2011-)
  sector    the same five measures by field of activity, latest year
  grants    companies and grant total from the Innovation Authority, by field
  rounds    number and $ amount of capital raised, by round type, 3 years
  rsector   the same by round type and field, 3 years summed
  size      average monthly wage by company size, + economy / high-tech
  district  active companies and average wage by district
  swage     average wage and jobs by field
  rates     opening and closing rates by field, two years
  funding   average government vs private funding per company, by field
  mature    mature (graduated) companies and their jobs, by size, yearly

Two chart sheets repeat `main` (active companies + jobs; openings,
closings and their rates) and one repeats `rounds` in dollars; they are
recognised and not read. A title that is found but whose header labels are
gone raises (the layout changed: a human should look). A table missing from
an edition drops its section; `main` is required.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*-\s*")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
# Round types are printed in English; the page is Hebrew.
ROUND_HE = {"Pre-Seed & Seed": "סבבי Pre-Seed ו-Seed", "A & B Rounds": "סבבי A ו-B",
            "Late Rounds": "סבבים מאוחרים", "Other": "אחר",
            "Late Rounds & Other": "סבבים מאוחרים ואחר"}
TOTAL = "סך הכל"
# Insight-card order; at most MAX_TOP there, the others go to their section.
PRIORITY = ("active", "flows", "jobs", "wage", "raised", "district", "sector", "rsector",
            "funding", "mature", "rates", "grants", "swage", "size")
MAX_TOP = 8
ORDINAL = {2: "שנייה", 3: "שלישית", 4: "רביעית", 5: "חמישית", 6: "שישית", 7: "שביעית",
           8: "שמינית", 9: "תשיעית", 10: "עשירית"}


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return TITLE.sub("", c)
    return ""


def _kind(t):
    if "מאזן" in t or "מספר חברות הזנק פעילות ומשרות שכיר" in t or "גיוסי הון" in t:
        return None  # chart sheets that repeat `main` / `rounds`
    if "בשלות" in t and "משרות שכיר" in t and "גיוס" not in t and "מימון" not in t:
        return "mature"
    if "מימון ממשלתי" in t:
        return "funding"
    if "מענק" in t:
        return "grants"
    if "גיוס" in t:
        return "rsector" if "תחום" in t else "rounds"
    if "אחוז הפתיחות" in t and "תחום" in t:
        return "rates"
    if "פתיחות" in t and "סגירות" in t and "חברות פעילות" in t and "מחוז" not in t:
        return "sector" if "תחום" in t else "main"
    if "מחוז" in t:
        return "district"
    if "גודל חברה" in t and "שכר" in t:
        return "size"
    if "שכר" in t and "תחום" in t:
        return "swage"
    return None


def _tables(frames):
    """{kind: (title, rows)} over every non-empty table input, first match
    by stem number wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        t = _title(rows)
        k = _kind(t)
        if k and k not in out:
            out[k] = (t, rows)
    return out


# ── small helpers ────────────────────────────────────────────────────────


def _year(c):
    return int(c) if cbs.YEAR.match(c) else None


def _title_year(t):
    ys = [int(y) for y in YEAR_IN.findall(t)]
    return max(ys) if ys else None


def _col(row, pred, name, label):
    for j, c in enumerate(row):
        if j > 0 and c and pred(c):
            return j
    raise ValueError(f"{name}: header label {label!r} not found")


def _data(rows, start, cols):
    """[(label, [values])] for rows after `start`: a label in column 0 and
    at least one number in `cols`. Footnotes and helper rows (no label, or
    no numbers) are skipped; the grand total row is kept, named TOTAL."""
    out = []
    for r in rows[start:]:
        label = cbs.cell(r, 0)
        if not label or label.startswith(("הערה", "קו ")):
            continue
        vals = [cbs.val(r, j) for j in cols]
        if all(v is None for v in vals):
            continue
        out.append((label, vals))
    return out


def _split_total(items):
    total = next((v for n, v in items if n == TOTAL), None)
    return total, [(n, v) for n, v in items if n != TOTAL]


def _ffill_years(row):
    """{column: year} for a header row printing each year once over its
    column group."""
    out, cur = {}, None
    for j, c in enumerate(row):
        y = _year(c)
        if y:
            cur = y
        if j > 0 and cur:
            out[j] = cur
    return out


def _r1(v):
    return None if v is None else round(v, 1)


def _r2(v):
    return None if v is None else round(v, 2)


def _p(v, d=1):
    return fmt.pct_of(v, d)


def _round(name):
    return ROUND_HE.get(name, name)


def _musd(v):
    """$ millions as a Hebrew amount: 1,234 million → '1.2 מיליארד דולר'."""
    if v >= 1000:
        return f"{fmt.num_he(v / 1000)} מיליארד דולר"
    return f"{fmt.int_he(v)} מיליון דולר"


# ── table parsers ────────────────────────────────────────────────────────


def _main(rows):
    h = cbs.row_with(rows, "פתיחות", name="main")
    hr = rows[h]
    c_open = cbs.col_after(hr, "פתיחות", 1)
    c_close = cbs.col_after(hr, "סגירות", 1)
    c_act = cbs.col_after(hr, "חברות פעילות", 1)
    c_jobs = _col(hr, lambda c: c.startswith("משרות שכיר"), "main", "משרות שכיר")
    c_wage = _col(hr, lambda c: c.startswith("שכר"), "main", "שכר")
    jobs_k = "אלפים" in hr[c_jobs]
    out = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, 0))
        if y is None or y in out:
            continue
        act = cbs.val(r, c_act)
        if act is None:
            continue
        jobs = cbs.val(r, c_jobs)
        if jobs is not None and jobs_k:
            jobs *= 1000
        out[y] = {"open": cbs.val(r, c_open), "close": cbs.val(r, c_close), "active": act,
                  "jobs": jobs, "wage": cbs.val(r, c_wage)}
    if len(out) < 2:
        raise ValueError("main: fewer than two years")
    return out


def _sector(rows):
    h = cbs.row_with(rows, "פתיחות", name="sector")
    hr = rows[h]
    cols = [cbs.col_after(hr, "פתיחות", 1), cbs.col_after(hr, "סגירות", 1),
            cbs.col_after(hr, "חברות פעילות", 1),
            _col(hr, lambda c: c.startswith("משרות שכיר"), "sector", "משרות שכיר"),
            _col(hr, lambda c: c.startswith("שכר"), "sector", "שכר")]
    jobs_k = "אלפים" in hr[cols[3]]
    items = []
    for n, v in _data(rows, h + 1, cols):
        if v[3] is not None and jobs_k:
            v[3] *= 1000
        items.append((n, v))
    return _split_total(items)


def _year_groups(rows, measure, name):
    """For a table with a year row over measure columns (grants, rounds,
    rates): (measure row index, {year: {measure label: column}})."""
    m = cbs.row_with(rows, measure, name=name)
    yr = next((i for i in range(m - 1, -1, -1) if _ffill_years(rows[i])), None)
    if yr is None:
        raise ValueError(f"{name}: year header row not found")
    ymap = _ffill_years(rows[yr])
    out = {}
    for j, c in enumerate(rows[m]):
        if j in ymap and c:
            out.setdefault(ymap[j], {})[c] = j
    if not out:
        raise ValueError(f"{name}: no year columns")
    return m, dict(sorted(out.items()))


def _grants(rows):
    m, groups = _year_groups(rows, "מספר חברות", "grants")
    years = list(groups)
    cols = []
    for y in years:
        g = groups[y]
        cols.append(g["מספר חברות"])
        cols.append(next((j for c, j in g.items() if c.startswith("סך מענק")), -1))
    items = _data(rows, m + 1, cols)
    return years, _split_total(items)


def _rounds(rows):
    m, groups = _year_groups(rows, "שכיחות גיוסים", "rounds")
    years = list(groups)
    cols = []
    for y in years:
        g = groups[y]
        cols.append(g["שכיחות גיוסים"])
        cols.append(next((j for c, j in g.items() if c.startswith("סכום הגיוס")), -1))
    items = _data(rows, m + 1, cols)
    return years, _split_total(items)


def _rsector(rows):
    m = cbs.row_with(rows, "שכיחות גיוסים", name="rsector")
    head = rows[m - 1]
    types, cur = {}, None
    for j, c in enumerate(head):
        if j > 0 and c:
            cur = c
        if j > 0 and cur:
            types[j] = cur
    groups = []
    for j, c in enumerate(rows[m]):
        if c.startswith("סכום הגיוס") and j in types:
            groups.append((types[j], j))
    if not groups:
        raise ValueError("rsector: amount columns not found")
    items = _data(rows, m + 1, [j for _, j in groups])
    return [t for t, _ in groups], _split_total(items)


def _size_label(c):
    """CBS prints size bands right to left ("20-11", "50+"): as read in
    Hebrew text, "11-20" and "מעל 50"."""
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", c)
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        return f"{a}-{b}"
    m = re.fullmatch(r"(\d+)\s*\+|\+\s*(\d+)", c)
    if m:
        return f"מעל {m.group(1) or m.group(2)}"
    return c


def _size(rows):
    h = cbs.row_with(rows, "גודל חברה", name="size")
    hr = rows[h]
    c_w = cbs.col_after(hr, "שכר חודשי ממוצע למשרת שכיר", 1)
    bench = {}
    for key, txt in (("all", "בכלל חברות ההזנק"), ("economy", "במשק"), ("hitech", "בהייטק")):
        j = next((j for j, c in enumerate(hr) if j > 0 and c.endswith(txt)), None)
        if j is not None:
            bench[key] = j
    items = _data(rows, h + 1, [c_w] + list(bench.values()))
    bvals = {}
    for _, v in items:
        for k, x in zip(bench, v[1:]):
            if x is not None and k not in bvals:
                bvals[k] = x
    return [(_size_label(n), v[0]) for n, v in items if v[0] is not None], bvals


def _district(rows):
    h = cbs.row_with(rows, "מחוז", name="district")
    hr = rows[h]
    c_a = next((j for j, c in enumerate(hr) if j > 0 and c == "חברות פעילות"), None)
    c_w = next((j for j, c in enumerate(hr) if j > 0 and c == "שכר חודשי ממוצע למשרת שכיר"), None)
    if c_a is None and c_w is None:
        raise ValueError("district: neither 'חברות פעילות' nor wage column found")
    cols = [c_a if c_a is not None else -1, c_w if c_w is not None else -1]
    return _split_total(_data(rows, h + 1, cols))[1]


def _swage(rows):
    h = cbs.row_with(rows, "תחום פעילות", name="swage")
    hr = rows[h]
    c_w = cbs.col_after(hr, "שכר חודשי ממוצע למשרת שכיר", 1)
    c_j = next((j for j, c in enumerate(hr) if j > 0 and c.startswith("משרות שכיר")), -1)
    return _split_total(_data(rows, h + 1, [c_w, c_j]))


def _rates(rows):
    m, groups = _year_groups(rows, "אחוז הפתיחות", "rates")
    years = list(groups)
    cols = []
    for y in years:
        cols += [groups[y]["אחוז הפתיחות"], groups[y].get("אחוז הסגירות", -1)]
    items = _split_total(_data(rows, m + 1, cols))[1]
    scale = 100 if all(x is None or x <= 1.0001 for _, v in items for x in v) else 1
    return years, [(n, [None if x is None else x * scale for x in v]) for n, v in items]


def _funding(rows):
    h = cbs.row_with(rows, "תחום פעילות", name="funding")
    hr = rows[h]
    c_g = cbs.col_after(hr, "מימון ממשלתי", 1, contains=True)
    c_p = cbs.col_after(hr, "מימון פרטי", 1, contains=True)
    c_r = next((j for j, c in enumerate(hr) if j > 0 and "מינוף" in c), -1)
    return _split_total(_data(rows, h + 1, [c_g, c_p, c_r]))[1]


def _mature(rows):
    m = cbs.row_with(rows, "עד 25", name="mature", contains=True)
    # the measure row: the first row holding a 'משרות שכיר' column cell
    mr = next((i for i in range(m, len(rows)) if any(c.startswith("משרות שכיר") for c in rows[i])),
              None)
    if mr is None:
        raise ValueError("mature: measure header row not found")
    cols = {}
    for j, c in enumerate(rows[mr]):
        if j == 0 or not c:
            continue
        small = "עד 25" in c
        big = "יותר מ-25" in c or "מעל 25" in c
        if not (small or big):
            continue
        kind = "jobs" if c.startswith("משרות") else "active"
        cols[("small" if small else "big", kind)] = j
    need = [("small", "active"), ("big", "active"), ("small", "jobs"), ("big", "jobs")]
    if any(k not in cols for k in need):
        raise ValueError("mature: size columns not found")
    out = {}
    for r in rows[mr + 1:]:
        y = _year(cbs.cell(r, 0))
        if y is None or y in out:
            continue
        v = {k: cbs.val(r, cols[k]) for k in need}
        if v[("big", "active")] is not None:
            out[y] = v
    return out


# ── insight helpers ──────────────────────────────────────────────────────


def _chg(new, old):
    return None if not old else (new - old) / old


def _first(items):
    """The (name, value) with the largest value, ties by name."""
    return min(items, key=lambda kv: (-kv[1], kv[0]))


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "main" not in tabs:
        raise ValueError("main table (פתיחות, סגירות, חברות פעילות) not found in any input")

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── main: the yearly series ─────────────────────────────────────────
    main = _main(tabs["main"][1])
    ys = sorted(main)
    ly = ys[-1]
    last = main[ly]
    charts["trend"] = {"x": [str(y) for y in ys],
                       "active": [main[y]["active"] for y in ys],
                       "jobs": [None if main[y]["jobs"] is None else round(main[y]["jobs"])
                                for y in ys]}
    tables["trend"] = [[str(y), fmt.int_he(main[y]["active"]),
                        fmt.int_he(main[y]["jobs"]) if main[y]["jobs"] is not None else "–"]
                       for y in ys]
    kpis["active"] = {"value": last["active"], "display": fmt.int_he(last["active"]),
                      "tone": "brand"}
    labels["active_kpi"] = f"חברות הזנק פעילות, {ly}"
    if last["jobs"] is not None:
        kpis["jobs"] = {"value": round(last["jobs"]), "display": fmt.int_he(last["jobs"]),
                        "tone": "brand"}
        labels["jobs_kpi"] = f"משרות שכיר בחברות ההזנק, {ly}"

    peak_y = min(ys, key=lambda y: (-main[y]["active"], y))
    peak = main[peak_y]["active"]
    if peak_y == ly:
        add("active", f"מספר חברות ההזנק הפעילות הגיע ב-{ly} לשיא של {fmt.int_he(peak)} חברות, "
                      f"לעומת {fmt.int_he(main[ys[0]]['active'])} ב-{ys[0]}.")
    else:
        d = _chg(last["active"], peak)
        if d is not None and d <= -0.03:
            add("active", f"ב-{ly} פעלו {fmt.int_he(last['active'])} חברות הזנק, "
                          f"{fmt.pct(-d)} פחות מהשיא של {fmt.int_he(peak)} חברות ב-{peak_y}.")
        else:
            add("active", f"ב-{ly} פעלו {fmt.int_he(last['active'])} חברות הזנק, קרוב לשיא של "
                          f"{fmt.int_he(peak)} חברות ב-{peak_y}.")

    jy = [y for y in ys if main[y]["jobs"] is not None]
    if len(jy) >= 2 and main[jy[-1]]["jobs"] is not None:
        jl = main[jy[-1]]["jobs"]
        jpeak_y = min(jy, key=lambda y: (-main[y]["jobs"], y))
        jp = main[jpeak_y]["jobs"]
        if jpeak_y == jy[-1]:
            add("jobs", f"חברות ההזנק העסיקו ב-{jy[-1]} שיא של {fmt.int_he(jl)} משרות שכיר.")
        else:
            d = _chg(jl, jp)
            if d is not None and d <= -0.03:
                add("jobs", f"מספר משרות השכיר בחברות ההזנק ירד ל-{fmt.int_he(jl)} ב-{jy[-1]}, "
                            f"{fmt.pct(-d)} פחות מהשיא של {fmt.int_he(jp)} משרות ב-{jpeak_y}.")

    # openings and closings
    fy = [y for y in ys if main[y]["open"] is not None and main[y]["close"] is not None]
    if len(fy) >= 2:
        charts["flows"] = {"x": [str(y) for y in fy],
                           "open": [main[y]["open"] for y in fy],
                           "close": [main[y]["close"] for y in fy],
                           "net": [main[y]["open"] - main[y]["close"] for y in fy],
                           "open_rate": [_r1(main[y]["open"] / main[y]["active"] * 100) for y in fy],
                           "close_rate": [_r1(main[y]["close"] / main[y]["active"] * 100)
                                          for y in fy]}
        tables["flows"] = [[str(y), fmt.int_he(main[y]["open"]), fmt.int_he(main[y]["close"]),
                            fmt.int_he(main[y]["open"] - main[y]["close"]).replace("-", fmt.MINUS),
                            _p(main[y]["close"] / main[y]["active"] * 100)] for y in fy]
        flags["flows"] = True
        fl = main[fy[-1]]
        kpis["open"] = {"value": fl["open"], "display": fmt.int_he(fl["open"]), "tone": "brand"}
        labels["open_kpi"] = f"חברות הזנק שנפתחו, {fy[-1]}"
        kpis["close"] = {"value": fl["close"], "display": fmt.int_he(fl["close"]),
                         "tone": "danger" if fl["close"] > fl["open"] else "brand"}
        labels["close_kpi"] = f"חברות הזנק שנסגרו, {fy[-1]}"
        run = 0
        for y in reversed(fy):
            if main[y]["close"] > main[y]["open"]:
                run += 1
            else:
                break
        if run >= 1:
            # Years before the current run in which closings also beat openings:
            # "the first year since ..." is true only when there are none.
            earlier = [y for y in fy[:len(fy) - run] if main[y]["close"] > main[y]["open"]]
            head = (f"ב-{fy[-1]} נסגרו {fmt.int_he(fl['close'])} חברות הזנק ונפתחו "
                    f"{fmt.int_he(fl['open'])} בלבד. ")
            if run == 1 and not earlier:
                tail = f"זו השנה הראשונה מאז {fy[0]} שבה הסגירות עולות על הפתיחות."
            elif run == 1:
                tail = (f"הפעם הקודמת שבה הסגירות עלו על הפתיחות הייתה ב-{earlier[-1]}.")
            else:
                yrs = (f"השנה ה{ORDINAL[run]} ברציפות" if run in ORDINAL
                       else f"השנה ה-{run} ברציפות")
                tail = f"זו {yrs} שבה הסגירות עולות על הפתיחות."
            add("flows", head + tail)
        else:
            op_y = min(fy, key=lambda y: (-main[y]["open"], y))
            if op_y != fy[-1]:
                add("flows", f"ב-{fy[-1]} נפתחו {fmt.int_he(fl['open'])} חברות הזנק ונסגרו "
                             f"{fmt.int_he(fl['close'])}. שיא הפתיחות היה ב-{op_y}, "
                             f"{fmt.int_he(main[op_y]['open'])} חברות.")
        labels["flows_note"] = (f"כמה חברות הזנק נפתחו ונסגרו בכל שנה מאז {fy[0]}, והמאזן "
                                f"ביניהן. הלמ\"ס מציינת שבשנים האחרונות יש חוסר במידע, ולכן "
                                f"נתוני השנים האלה עשויים לעלות כשהמידע ייחשף.")
        labels["flows_aria"] = f"פתיחות וסגירות של חברות הזנק, {fy[0]} עד {fy[-1]}"

    # wage bill
    wy = [y for y in ys if main[y]["wage"] is not None]
    if len(wy) >= 2:
        flags["wagebill"] = True
        charts["wagebill"] = {"x": [str(y) for y in wy],
                              "wage": [_r2(main[y]["wage"] / 1000) for y in wy]}
        tables["wagebill"] = [[str(y), fmt.num_he(main[y]["wage"] / 1000, 2)] for y in wy]
        labels["wagebill_note"] = (f"סך השכר ששילמו חברות ההזנק לעובדיהן בכל שנה, במיליארדי "
                                   f"שקלים במחירים שוטפים, {wy[0]} עד {wy[-1]}.")
        labels["wagebill_aria"] = f"סך השכר בחברות ההזנק, {wy[0]} עד {wy[-1]}"

    labels["trend_note"] = (f"מספר חברות ההזנק הפעילות ומספר משרות השכיר בהן בכל שנה, "
                            f"{ys[0]} עד {ly}.")
    labels["trend_aria"] = f"חברות הזנק פעילות ומשרות שכיר, {ys[0]} עד {ly}"

    # ── wages by company size, with the benchmarks ──────────────────────
    bench = {}
    if "size" in tabs:
        st, srows = tabs["size"]
        sizes, bench = _size(srows)
        sy = _title_year(st)
        yr = f", {sy}" if sy else ""
        yb = f" ב-{sy}" if sy else ""
        if sizes:
            flags["size"] = True
            charts["size"] = {"names": [n for n, _ in sizes], "values": [round(v) for _, v in sizes],
                              "all": round(bench["all"]) if "all" in bench else None,
                              "economy": round(bench["economy"]) if "economy" in bench else None,
                              "hitech": round(bench["hitech"]) if "hitech" in bench else None}
            tables["size"] = [[n, fmt.int_he(v)] for n, v in sizes]
            for k, nm in (("all", "כלל חברות ההזנק"), ("hitech", "ממוצע ענף ההייטק"),
                          ("economy", "ממוצע המשק")):
                if k in bench:
                    tables["size"].append([nm, fmt.int_he(bench[k])])
            labels["size_note"] = (f"השכר החודשי הממוצע למשרת שכיר בחברות ההזנק לפי מספר המועסקים "
                                   f"בחברה{yr}, בשקלים, לצד הממוצע בכל המשק ובענף ההייטק.")
            labels["size_aria"] = f"שכר חודשי ממוצע בחברות הזנק לפי גודל חברה{yr}"
            lo, hi = sizes[0], sizes[-1]
            if hi[1] > lo[1] * 1.05:
                add("size", f"השכר עולה עם גודל החברה: {fmt.int_he(lo[1])} ש\"ח בחודש בחברות של "
                            f"{lo[0]} משרות שכיר, לעומת {fmt.int_he(hi[1])} ש\"ח בחברות של "
                            f"{hi[0]} משרות{yb}.")
        if "all" in bench:
            kpis["wage"] = {"value": round(bench["all"]), "display": fmt.int_he(bench["all"]),
                            "tone": "brand"}
            labels["wage_kpi"] = f"שכר חודשי ממוצע למשרה (ש\"ח){yr}"
            if bench.get("economy"):
                ratio = bench["all"] / bench["economy"]
                txt = (f"השכר החודשי הממוצע בחברות ההזנק{yb} היה {fmt.int_he(bench['all'])} ש\"ח, "
                       f"פי {fmt.num_he(ratio)} מהממוצע במשק ({fmt.int_he(bench['economy'])} ש\"ח)")
                if bench.get("hitech"):
                    rel_h = bench["all"] / bench["hitech"] - 1
                    if rel_h < -0.02:
                        txt += (f", אבל {fmt.pct(-rel_h)} פחות מהממוצע בענף ההייטק "
                                f"({fmt.int_he(bench['hitech'])} ש\"ח)")
                    elif rel_h > 0.02:
                        txt += (f", ו-{fmt.pct(rel_h)} יותר מהממוצע בענף ההייטק "
                                f"({fmt.int_he(bench['hitech'])} ש\"ח)")
                add("wage", txt + ".")

    # ── by field of activity ────────────────────────────────────────────
    if "sector" in tabs:
        st, srows = tabs["sector"]
        stot, sitems = _sector(srows)
        sitems = [(n, v) for n, v in sitems if v[2] is not None]
        sy = _title_year(st)
        yr = f", {sy}" if sy else ""
        yb = f" ב-{sy}" if sy else ""
        if len(sitems) >= 2:
            flags["sector"] = True
            order = sorted(sitems, key=lambda kv: (-kv[1][2], kv[0]))
            charts["sector"] = {"names": [n for n, _ in order],
                                "active": [v[2] for _, v in order],
                                "jobs": [None if v[3] is None else round(v[3]) for _, v in order]}
            tables["sector"] = [[n, fmt.int_he(v[2]),
                                 fmt.int_he(v[0]) if v[0] is not None else "–",
                                 fmt.int_he(v[1]) if v[1] is not None else "–",
                                 fmt.int_he(v[3]) if v[3] is not None else "–"] for n, v in order]
            labels["sector_note"] = (f"חברות ההזנק הפעילות לפי תחום פעילות{yr}, ומספר משרות השכיר "
                                     f"בכל תחום.")
            labels["sector_aria"] = f"חברות הזנק פעילות לפי תחום פעילות{yr}"
            tot_a = stot[2] if stot and stot[2] else sum(v[2] for _, v in sitems)
            n0, v0 = order[0]
            n1, v1 = order[1]
            if tot_a and v0[2] > v1[2]:
                add("sector", f"התחום הגדול ביותר{yb} היה {n0}, עם {fmt.int_he(v0[2])} חברות "
                              f"פעילות ({fmt.pct(v0[2] / tot_a)} מכלל חברות ההזנק), ואחריו "
                              f"{n1} עם {fmt.int_he(v1[2])}.")

    if "swage" in tabs:
        st, srows = tabs["swage"]
        _, witems = _swage(srows)
        witems = [(n, v) for n, v in witems if v[0] is not None]
        sy = _title_year(st)
        yr = f", {sy}" if sy else ""
        yb = f" ב-{sy}" if sy else ""
        if len(witems) >= 2:
            flags["swage"] = True
            order = sorted(witems, key=lambda kv: (-kv[1][0], kv[0]))
            charts["swage"] = {"names": [n for n, _ in order],
                               "values": [round(v[0]) for _, v in order],
                               "all": round(bench["all"]) if "all" in bench else None}
            tables["swage"] = [[n, fmt.int_he(v[0]),
                                fmt.int_he(v[1]) if v[1] is not None else "–"] for n, v in order]
            labels["swage_note"] = (f"השכר החודשי הממוצע למשרת שכיר בכל תחום פעילות{yr}, "
                                    f"בשקלים.")
            labels["swage_aria"] = f"שכר חודשי ממוצע בחברות הזנק לפי תחום פעילות{yr}"
            named = [(n, v) for n, v in order if n != "אחר"]
            if len(named) >= 2 and named[0][1][0] > named[-1][1][0] * 1.1:
                add("swage", f"השכר הגבוה ביותר{yb} היה בתחום {named[0][0]}, "
                             f"{fmt.int_he(named[0][1][0])} ש\"ח בחודש, והנמוך ביותר בתחום "
                             f"{named[-1][0]}, {fmt.int_he(named[-1][1][0])} ש\"ח.")

    if "rates" in tabs:
        st, srows = tabs["rates"]
        r_years, ritems = _rates(srows)
        ritems = [(n, v) for n, v in ritems if v[-2] is not None and v[-1] is not None]
        if ritems and r_years:
            flags["rates"] = True
            ry = r_years[-1]
            order = sorted(ritems, key=lambda kv: (-kv[1][-1], kv[0]))
            charts["rates"] = {"names": [n for n, _ in order],
                               "open": [_r1(v[-2]) for _, v in order],
                               "close": [_r1(v[-1]) for _, v in order]}
            cols = ["תחום פעילות"]
            for y in r_years:
                cols += [f"פתיחות {y}", f"סגירות {y}"]
            labels["rates_cols"] = cols
            tables["rates"] = [[n] + [_p(x) if x is not None else "–" for x in v] for n, v in order]
            note = (f"כמה חברות נפתחו וכמה נסגרו ב-{ry} בכל תחום, באחוזים מסך החברות "
                    f"הפעילות בו.")
            if len(r_years) > 1:
                note += f" בטבלה גם {fmt.join_he([str(y) for y in r_years[:-1]])} להשוואה."
            labels["rates_note"] = note
            labels["rates_aria"] = f"אחוז הפתיחות והסגירות לפי תחום פעילות, {ry}"
            neg = [n for n, v in ritems if v[-1] > v[-2]]
            hi_n, hi_v = next(((n, v) for n, v in order if n != "אחר"), order[0])
            if len(neg) >= 2:
                add("rates", f"ב-{ry} אחוז הסגירות עלה על אחוז הפתיחות ב-{len(neg)} מתוך "
                             f"{len(ritems)} תחומי הפעילות. אחוז הסגירות הגבוה ביותר היה בתחום {hi_n}: "
                             f"{_p(hi_v[-1])} מהחברות.")

    # ── by district ─────────────────────────────────────────────────────
    if "district" in tabs:
        st, drows = tabs["district"]
        ditems = _district(drows)
        sy = _title_year(st)
        yr = f", {sy}" if sy else ""
        yb = f" ב-{sy}" if sy else ""
        act = [(n, v) for n, v in ditems if v[0] is not None]
        if len(act) >= 2:
            flags["district"] = True
            order = sorted(ditems, key=lambda kv: (-(kv[1][0] or 0), kv[0]))
            charts["district"] = {"names": [n for n, _ in order],
                                  "active": [v[0] for _, v in order],
                                  "wage": [None if v[1] is None else round(v[1]) for _, v in order]}
            tables["district"] = [[n, fmt.int_he(v[0]) if v[0] is not None else "–",
                                   fmt.int_he(v[1]) if v[1] is not None else "–"]
                                  for n, v in order]
            labels["district_note"] = (f"חברות ההזנק הפעילות לפי מחוז{yr}, והשכר החודשי הממוצע "
                                       f"למשרת שכיר בכל מחוז (בשקלים, בטבלה ובחלון המידע).")
            labels["district_aria"] = f"חברות הזנק פעילות לפי מחוז{yr}"
            tot = sum(v[0] for _, v in act)
            n0, v0 = _first([(n, v[0]) for n, v in act])
            txt = (f"{fmt.pct(v0 / tot)} מחברות ההזנק הפעילות{yb} היו במחוז {n0} "
                   f"({fmt.int_he(v0)} חברות)")
            wd = [(n, v[1]) for n, v in ditems if v[1] is not None]
            if len(wd) >= 2:
                wn, wv = _first(wd)
                lo_n, lo_v = min(wd, key=lambda kv: (kv[1], kv[0]))
                if wv > lo_v * 1.1:
                    txt += (f". השכר הממוצע הגבוה ביותר היה במחוז {wn}, {fmt.int_he(wv)} ש\"ח, "
                            f"והנמוך ביותר במחוז {lo_n}, {fmt.int_he(lo_v)} ש\"ח")
            add("district", txt + ".")

    # ── capital raising ────────────────────────────────────────────────
    if "rounds" in tabs:
        st, rrows = tabs["rounds"]
        r_years, (rtot, ritems) = _rounds(rrows)
        ritems = [(n, v) for n, v in ritems if any(x is not None for x in v)]
        if ritems and r_years:
            flags["rounds"] = True
            k = len(r_years)
            names = [_round(n) for n, _ in ritems]
            charts["rounds"] = {"x": [str(y) for y in r_years], "names": names,
                                "amount": [[_r1(v[2 * i + 1]) for i in range(k)] for _, v in ritems]}
            labels["rounds_cols"] = (["סוג הגיוס"]
                                     + [f"{y}: גיוסים" for y in r_years]
                                     + [f"{y}: מיליון דולר" for y in r_years])
            tables["rounds"] = [[nm] + [fmt.int_he(v[2 * i]) if v[2 * i] is not None else "–"
                                        for i in range(k)]
                                + [fmt.int_he(v[2 * i + 1]) if v[2 * i + 1] is not None else "–"
                                   for i in range(k)]
                                for nm, (_, v) in zip(names, ritems)]
            if rtot:
                tables["rounds"].append(
                    ["סך הכל"] + [fmt.int_he(rtot[2 * i]) if rtot[2 * i] is not None else "–"
                                  for i in range(k)]
                    + [fmt.int_he(rtot[2 * i + 1]) if rtot[2 * i + 1] is not None else "–"
                       for i in range(k)])
            labels["rounds_note"] = (f"סכום ההון שגייסו חברות ההזנק והחברות הבשלות בכל שנה לפי "
                                     f"שלב הגיוס, במיליוני דולרים, {r_years[0]} עד {r_years[-1]}. "
                                     f"סבבים מאוחרים: סבב C ואילך, PIPE, הלוואות והנפקות לציבור "
                                     f"הרחב. מספר הגיוסים בטבלה.")
            labels["rounds_aria"] = f"גיוסי הון לפי סוג הגיוס, {r_years[0]} עד {r_years[-1]}"
            amt = [rtot[2 * i + 1] if rtot and rtot[2 * i + 1] is not None
                   else sum(v[2 * i + 1] or 0 for _, v in ritems) for i in range(k)]
            cnt = [rtot[2 * i] if rtot and rtot[2 * i] is not None
                   else sum(v[2 * i] or 0 for _, v in ritems) for i in range(k)]
            kpis["raised"] = {"value": round(amt[-1]), "display": fmt.num_he(amt[-1] / 1000),
                              "tone": "brand"}
            labels["raised_kpi"] = f"הון שגויס (מיליארד דולר), {r_years[-1]}"
            if k >= 2 and amt[-2]:
                d = _chg(amt[-1], amt[-2])
                word = ("עלה" if d > 0.03 else "ירד" if d < -0.03 else None)
                if word:
                    kpis["raised"]["tone"] = "ok" if d > 0 else "warn"
                    txt = (f"ב-{r_years[-1]} גייסו חברות ההזנק והחברות הבשלות {_musd(amt[-1])} "
                           f"ב-{fmt.int_he(cnt[-1])} גיוסים. הסכום {word} ב-{fmt.pct(abs(d))} "
                           f"לעומת {r_years[-2]}")
                    if k >= 3 and amt[0] > amt[-1] * 1.1:
                        txt += f", ועדיין נמוך מ-{_musd(amt[0])} ב-{r_years[0]}"
                    add("raised", txt + ".")

    if "rsector" in tabs:
        st, rrows = tabs["rsector"]
        types, (_, items) = _rsector(rrows)
        items = [(n, v) for n, v in items if any(x is not None for x in v)]
        span = re.findall(r"(?:19|20)\d\d", st)
        span_txt = f"{min(span)}-{max(span)}" if len(span) >= 2 else ""
        if len(items) >= 2:
            flags["rsector"] = True
            order = sorted(items, key=lambda kv: (-sum(x or 0 for x in kv[1]), kv[0]))
            tnames = [_round(t) for t in types]
            charts["rsector"] = {"names": [n for n, _ in order], "types": tnames,
                                 "values": [[_r1(v[i]) for _, v in order] for i in range(len(types))]}
            labels["rsector_cols"] = ["תחום פעילות"] + tnames + ["סך הכל"]
            tables["rsector"] = [[n] + [fmt.int_he(x) if x is not None else "–" for x in v]
                                 + [fmt.int_he(sum(x or 0 for x in v))] for n, v in order]
            per = f" בשנים {span_txt}" if span_txt else ""
            labels["rsector_note"] = (f"סכום ההון שגויס{per} (במצטבר) בכל תחום פעילות לפי שלב "
                                      f"הגיוס, במיליוני דולרים.")
            labels["rsector_aria"] = f"גיוסי הון לפי תחום פעילות וסוג הגיוס{per}"
            tot = sum(sum(x or 0 for x in v) for _, v in items)
            n0, v0 = order[0]
            s0 = sum(x or 0 for x in v0)
            if tot and s0 / tot >= 0.15:
                add("rsector", f"תחום {n0} גייס{per} {_musd(s0)}, {fmt.pct(s0 / tot)} מכל ההון "
                               f"שגייסו חברות ההזנק והחברות הבשלות.")

    if "funding" in tabs:
        st, frows = tabs["funding"]
        fitems = [(n, v) for n, v in _funding(frows) if v[1] is not None and v[1] > 0]
        sy = _title_year(st)
        yr = f", {sy}" if sy else ""
        yb = f" ב-{sy}" if sy else ""
        if len(fitems) >= 2:
            flags["funding"] = True
            order = sorted(fitems, key=lambda kv: (-kv[1][1], kv[0]))
            charts["funding"] = {"names": [n for n, _ in order],
                                 "private": [_r2(v[1] / 1e6) for _, v in order],
                                 "gov": [_r2(v[0] / 1e6) if v[0] is not None else None
                                         for _, v in order]}
            tables["funding"] = [[n, fmt.num_he(v[1] / 1e6, 2),
                                  fmt.num_he(v[0] / 1e6, 2) if v[0] is not None else "–",
                                  fmt.int_he(v[1] / v[0]) if v[0] else "–"] for n, v in order]
            labels["funding_note"] = (f"המימון הממוצע לחברה בכל תחום{yr}, במיליוני דולרים: מימון "
                                      f"פרטי (גיוסי הון) לעומת מימון ממשלתי. היחס ביניהם הוא "
                                      f"כמה דולרים פרטיים גויסו על כל דולר ממשלתי.")
            labels["funding_aria"] = f"מימון פרטי וממשלתי ממוצע לחברה לפי תחום{yr}"
            n0, v0 = order[0]
            if v0[0]:
                add("funding", f"חברה בתחום {n0} גייסה{yb} בממוצע {fmt.num_he(v0[1] / 1e6)} מיליון "
                               f"דולר ממקורות פרטיים, פי {fmt.int_he(v0[1] / v0[0])} מהמימון "
                               f"הממשלתי הממוצע לחברה בתחום.")

    if "grants" in tabs:
        st, grows = tabs["grants"]
        g_years, (gtot, gitems) = _grants(grows)
        k = len(g_years)
        gitems = [(n, v) for n, v in gitems if v[2 * k - 1] is not None]
        if len(gitems) >= 2:
            flags["grants"] = True
            gy = g_years[-1]
            order = sorted(gitems, key=lambda kv: (-kv[1][2 * k - 1], kv[0]))
            charts["grants"] = {"names": [n for n, _ in order],
                                "values": [_r1(v[2 * k - 1]) for _, v in order]}
            labels["grants_cols"] = (["תחום פעילות"] + [f"{y}: חברות" for y in g_years]
                                     + [f"{y}: מיליון ש\"ח" for y in g_years])
            tables["grants"] = [[n] + [fmt.int_he(v[2 * i]) if v[2 * i] is not None else "–"
                                       for i in range(k)]
                                + [fmt.num_he(v[2 * i + 1]) if v[2 * i + 1] is not None else "–"
                                   for i in range(k)] for n, v in order]
            labels["grants_note"] = (f"סך המענקים שקיבלו חברות הזנק מרשות החדשנות ב-{gy} לפי "
                                     f"תחום, במיליוני שקלים. בטבלה גם מספר החברות שקיבלו מענק"
                                     + (f" והשנים {g_years[0]} עד {g_years[-2]}." if k > 1 else "."))
            labels["grants_aria"] = f"מענקי רשות החדשנות לחברות הזנק לפי תחום, {gy}"
            tot = (gtot[2 * k - 1] if gtot and gtot[2 * k - 1] is not None
                   else sum(v[2 * k - 1] for _, v in gitems))
            tot_n = gtot[2 * k - 2] if gtot and gtot[2 * k - 2] is not None else None
            n0, v0 = order[0]
            if tot and v0[2 * k - 1] / tot >= 0.2:
                txt = (f"רשות החדשנות העניקה ב-{gy} מענקים בסך {fmt.int_he(tot)} מיליון ש\"ח "
                       + (f"ל-{fmt.int_he(tot_n)} חברות הזנק" if tot_n else "לחברות הזנק")
                       + f". {fmt.pct(v0[2 * k - 1] / tot)} מהסכום הלכו לתחום {n0}.")
                add("grants", txt)

    # ── mature companies ────────────────────────────────────────────────
    if "mature" in tabs:
        mat = _mature(tabs["mature"][1])
        my = sorted(mat)
        if len(my) >= 2:
            flags["mature"] = True
            charts["mature"] = {"x": [str(y) for y in my],
                                "small": [mat[y][("small", "active")] for y in my],
                                "big": [mat[y][("big", "active")] for y in my],
                                "jobs_big": [None if mat[y][("big", "jobs")] is None
                                             else round(mat[y][("big", "jobs")]) for y in my]}
            tables["mature"] = [[str(y)] + [fmt.int_he(mat[y][kk]) if mat[y][kk] is not None else "–"
                                            for kk in (("small", "active"), ("big", "active"),
                                                       ("small", "jobs"), ("big", "jobs"))]
                                for y in my]
            labels["mature_note"] = (f"חברות הזנק שבשלו (חברות בשלות) בכל שנה, {my[0]} עד {my[-1]}: "
                                     f"חברות עם עד 25 משרות שכיר ועם יותר מ-25, ומשרות השכיר "
                                     f"בחברות הגדולות.")
            labels["mature_aria"] = f"חברות בשלות לפי גודל, {my[0]} עד {my[-1]}"
            m0, m1 = mat[my[0]], mat[my[-1]]
            b0, b1 = m0[("big", "active")], m1[("big", "active")]
            jb = m1[("big", "jobs")]
            if b0 and b1 > b0 * 1.1:
                txt = (f"מספר החברות הבשלות עם יותר מ-25 משרות שכיר גדל מ-{fmt.int_he(b0)} ב-{my[0]} "
                       f"ל-{fmt.int_he(b1)} ב-{my[-1]}")
                if jb and my[-1] in main and main[my[-1]]["jobs"]:
                    txt += (f", והן מעסיקות {fmt.int_he(jb)} משרות שכיר, פי "
                            f"{fmt.num_he(jb / main[my[-1]]['jobs'])} מכל המשרות בחברות ההזנק")
                add("mature", txt + ".")

    # The page's insight card holds the strongest findings; the rest show as
    # a callout in their own chart section.
    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    # ── text ─────────────────────────────────────────────────────────────
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    lede = (f"כמה חברות הזנק (סטארט-אפ) פועלות בישראל, כמה נפתחות וכמה נסגרות, כמה הן מעסיקות "
            f"ומשלמות, באילו תחומים ומחוזות הן פועלות וכמה הון הן מגייסות. הנתונים מתוך ההודעה "
            f"השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. "
            f"הנתון האחרון הוא לשנת {ly}: {fmt.int_he(last['active'])} חברות הזנק פעילות")
    if last["jobs"] is not None:
        lede += f" ו-{fmt.int_he(last['jobs'])} משרות שכיר"
    labels["lede"] = lede + "."

    summary = (f"חברות ההזנק בישראל לפי נתוני הלמ\"ס: ב-{ly} פעלו {fmt.int_he(last['active'])} "
               f"חברות הזנק")
    if last["open"] is not None and last["close"] is not None:
        summary += f", {fmt.int_he(last['open'])} נפתחו ו-{fmt.int_he(last['close'])} נסגרו"
    summary += "."
    desc = (f"כמה חברות הזנק (סטארט-אפ) פועלות בישראל: {fmt.int_he(last['active'])} ב-{ly}")
    if last["jobs"] is not None:
        desc += f", עם {fmt.int_he(last['jobs'])} משרות שכיר"
    desc += ". פתיחות וסגירות, שכר, תחומים, מחוזות וגיוסי הון."
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{ys[0]}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "חברות הזנק (סטארט-אפ) בישראל: נתונים ומגמות | הלמ\"ס",
                "description": desc,
                "name": "חברות הזנק (סטארט-אפ) בישראל",
                "alternate_names": ["סטארטאפים בישראל", "מספר הסטארט-אפים בישראל",
                                    "חברות סטארט-אפ בישראל", "הייטק וחברות הזנק",
                                    "גיוסי הון של חברות הזנק"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top,
        "callouts": callouts,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
