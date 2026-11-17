"""השמות הפרטיים שניתנו לתינוקות: CBS's yearly baby-names release.

The release's Excel tables are laid out differently from one edition to the
next (2023: one table per sex and religion group; 2025: the same lists
gathered in one table, plus a 1949-onward history table and a by-locality
table for Jewish girls and boys), so every table resource (t1..t9) is read by
CONTENT, not by number. Each sheet of each edition is classified by its
header row:

  list     "שם" / "שם פרטי" | count | "אחוז": the names given to 5+ babies
           of one sex and religion group born in one year, with the share of
           all the group's babies (shares don't sum to 100: unnamed babies
           and names under 5 are left out)
  history  "סך הכל" followed by birth years: how many people registered
           today carry each name, per birth year (one sheet per group)
  city     "שם פרטי" | "יישוב…" | count | share: names given to 5+ babies of
           a group in each locality

The page reads the newest edition (max RELEASE_DATE over every table, then
the higher release number). The previous year's lists come from whichever
edition carries that year (newest first), for rank changes. A group, the
history or the locality table that an edition lacks drops its section.
"""
import re

from govlib import cbs, fmt

# Ordering/labels for the groups CBS publishes; an unknown group keeps its
# sheet label and sorts last.
RELIGIONS = [("jewish", "יהוד"), ("muslim", "מוסלמ"), ("christian", "נוצר"), ("druze", "דרוז")]
LABELS = {
    ("girls", "jewish"): "בנות יהודיות", ("boys", "jewish"): "בנים יהודים",
    ("girls", "muslim"): "בנות מוסלמיות", ("boys", "muslim"): "בנים מוסלמים",
    ("girls", "christian"): "בנות נוצריות", ("boys", "christian"): "בנים נוצרים",
    ("girls", "druze"): "בנות דרוזיות", ("boys", "druze"): "בנים דרוזים",
}
DEFINITE = {
    ("girls", "jewish"): "הבנות היהודיות", ("boys", "jewish"): "הבנים היהודים",
    ("girls", "muslim"): "הבנות המוסלמיות", ("boys", "muslim"): "הבנים המוסלמים",
    ("girls", "christian"): "הבנות הנוצריות", ("boys", "christian"): "הבנים הנוצרים",
    ("girls", "druze"): "הבנות הדרוזיות", ("boys", "druze"): "הבנים הדרוזים",
}
SEX_HE = {"girls": "בנות", "boys": "בנים"}
TABLES = [f"t{i}" for i in range(1, 13)]  # t10..t12: spare slots for a bigger edition
BIRTH_YEAR = re.compile(r"(?:ילידי|ילידות)\s+((?:19|20)\d\d)(?!\s*-\s*\d)")
HEB = re.compile("[א-ת]")

TOP_N = 10           # top-names chart / table
TREND_N = 5          # names per group on the history chart
MOVERS_N = 5         # risers and fallers each
MOVERS_POOL = 100    # movers are picked among the top 100 of either year
BIG_GROUP = 100      # rank changes only for groups listing 100+ names (small
                     # groups count tens of babies a name: noise)
SLOPE_CAP = 20       # a previous rank past this plots at the bottom
UNISEX_MIN = 0.15    # the smaller sex's share for a "shared" name
UNISEX_N = 10
RISER_MIN = 100      # the riser insight names a name given to 100+ babies
CITY_MIN = 100       # localities with at least this many listed babies
CITY_ROWS = 20


# ── reading the grids ────────────────────────────────────────────────────


def _rel_key(no):
    """"345/2026" → (2026, 345): CBS numbers releases within a year."""
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d{4})\s*", str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _sheets(frames):
    """Every sheet of every edition of every table: dicts with release,
    date, name and rows (cleaned cells, in row order)."""
    out = []
    for t in TABLES:
        df = frames.get(t)
        if df is None or df.empty:
            continue
        cols = sorted((c for c in df.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))
        df = df.sort_values(["RELEASE_DATE", "RELEASE_NO", "SHEET_NO", "ROW"], kind="stable")
        for (date, no, sno), g in df.groupby(["RELEASE_DATE", "RELEASE_NO", "SHEET_NO"], sort=True):
            rows = [[cbs.clean(v) for v in r] for r in g[cols].itertuples(index=False)]
            while rows and rows[-1] and all(not c for c in rows[-1]):
                rows.pop()
            out.append({"table": t, "date": str(date), "no": str(no), "sheet_no": str(sno),
                        "sheet": cbs.clean(g["SHEET"].iloc[0]), "rows": rows})
    return out


def _group(texts):
    """(sex, religion) from label texts, first text that names a sex."""
    for s in texts:
        sex = "girls" if "בנות" in s else "boys" if "בנים" in s else None
        if sex is None:
            continue
        for key, stem in RELIGIONS:
            if stem in s:
                return sex, key
        return sex, s.replace("בנות", "").replace("בנים", "").strip() or "?"
    return None


def _header(rows):
    """(kind, row index, columns) of the first header row, or None."""
    for i, r in enumerate(rows[:15]):
        cells = [c for c in r]
        years = [j for j, c in enumerate(cells) if cbs.YEAR.match(c)]
        if "סך הכל" in cells and len(years) >= 10:
            return "history", i, {"name": 0 if cells[0] else None, "total": cells.index("סך הכל"),
                                  "years": {j: int(cells[j]) for j in years}}
        # "שם", "שם פרטי" (and a typo'd "שם שם" in one edition)
        name = next((j for j, c in enumerate(cells)
                     if c.startswith("שם") and set(c.split()) <= {"שם", "פרטי"}), None)
        if name is None:
            continue
        cnt = next((j for j, c in enumerate(cells) if j != name and c
                    and any(k in c for k in ("מספר", "מוחלט", "סה\"כ", "כמות"))), None)
        share = next((j for j, c in enumerate(cells) if "אחוז" in c), None)
        city = next((j for j, c in enumerate(cells) if j != name and "יישוב" in c and c != cells[cnt or 0]), None)
        if cnt is None or share is None:
            continue
        if city is not None:
            return "city", i, {"name": name, "city": city, "count": cnt, "share": share}
        return "list", i, {"name": name, "count": cnt, "share": share}
    return None


def _year(texts):
    for s in texts:
        m = BIRTH_YEAR.search(s)
        if m:
            return int(m.group(1))
    return None


def _parse(sheets):
    lists, history, cities = {}, {}, {}
    for sh in sheets:
        rows = sh["rows"]
        h = _header(rows)
        if h is None:
            continue
        kind, hi, cols = h
        above = [" ".join(c for c in r if c) for r in rows[:hi]]
        grp = _group([sh["sheet"]] + above)
        if grp is None:
            continue
        ed = (sh["date"], _rel_key(sh["no"]), sh["no"])
        if kind == "history":
            if cols["name"] is None:
                cols["name"] = 0
            names = {}
            for r in rows[hi + 1:]:
                nm = cbs.cell(r, cols["name"])
                if not HEB.search(nm):
                    continue
                names[nm] = {y: (cbs.val(r, j) or 0) for j, y in cols["years"].items()}
            if names:
                history.setdefault(ed, {})[grp] = names
            continue
        year = _year(above + [sh["sheet"]])
        if year is None:
            continue
        if kind == "list":
            items = {}
            for r in rows[hi + 1:]:
                nm, n, p = cbs.cell(r, cols["name"]), cbs.val(r, cols["count"]), cbs.val(r, cols["share"])
                if not HEB.search(nm) or n is None or nm.startswith("סה"):
                    continue
                items[nm] = (items.get(nm, (0, 0))[0] + n, items.get(nm, (0, 0))[1] + (p or 0))
            if items:
                lists.setdefault(ed, {})[(year, grp)] = items
        else:
            per = {}
            for r in rows[hi + 1:]:
                nm, loc, n = cbs.cell(r, cols["name"]), cbs.cell(r, cols["city"]), cbs.val(r, cols["count"])
                if not HEB.search(nm) or not HEB.search(loc) or n is None:
                    continue
                p = cbs.val(r, cols["share"]) or 0
                per.setdefault(loc, {})
                old = per[loc].get(nm, (0, 0))
                per[loc][nm] = (old[0] + n, old[1] + p)
            if per:
                cities.setdefault(ed, {})[(year, grp)] = per
    return lists, history, cities


# ── helpers ──────────────────────────────────────────────────────────────


def _gorder(g):
    sex, rel = g
    ri = next((i for i, (k, _) in enumerate(RELIGIONS) if k == rel), len(RELIGIONS))
    return (ri, 0 if sex == "girls" else 1, str(rel))


def _glabel(g):
    return LABELS.get(g) or f"{SEX_HE[g[0]]} {g[1]}"


def _gdef(g):
    return DEFINITE.get(g) or _glabel(g)


def _ranked(items):
    """[(name, count, share)] by count desc, then name."""
    return sorted(((k, v[0], v[1]) for k, v in items.items()), key=lambda r: (-r[1], r[0]))


def _ranks(items):
    """{name: competition rank} (1 + names with a strictly larger count)."""
    counts = sorted((v[0] for v in items.values()), reverse=True)
    out = {}
    for k, v in items.items():
        lo, hi = 0, len(counts)
        while lo < hi:  # first index whose count is <= v
            mid = (lo + hi) // 2
            if counts[mid] > v[0]:
                lo = mid + 1
            else:
                hi = mid
        out[k] = lo + 1
    return out


def _n(v):
    return fmt.int_he(v)


def _p(v):
    return fmt.pct_of(v, 1)


def _pp(v):
    s = f"{abs(v):.2f}"
    if float(s) == 0:
        return "0.00"
    return ("+" if v > 0 else fmt.MINUS) + s


def _ord(rank):
    return "המקום הראשון" if rank == 1 else f"המקום ה-{rank}"


def _decade_label(d, years):
    ys = [y for y in years if d <= y < d + 10]
    if ys and (min(ys) != d or max(ys) != d + 9):
        return f"{min(ys)}-{max(ys)}"
    return f"שנות ה-{str(d)[2:]}" if d < 2000 else f"{d}-{d + 9}"


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    sheets = _sheets(frames)
    lists, history, cities = _parse(sheets)
    if not lists:
        raise ValueError("no name list found in any table")

    # Newest edition overall (tables first; the releases list may lag).
    newest = max(lists)
    cur_lists = lists[newest]
    year = max(y for y, _ in cur_lists)
    cur = {g: items for (y, g), items in cur_lists.items() if y == year}
    groups = sorted(cur, key=_gorder)

    # Previous year: the newest edition that lists year - 1.
    prev = {}
    for ed in sorted(lists, reverse=True):
        for (y, g), items in lists[ed].items():
            if y == year - 1 and g not in prev:
                prev[g] = items
    hist = history.get(newest, {})
    city = {g: per for (y, g), per in cities.get(newest, {}).items() if y == year}

    rel_df = frames.get("releases")
    release = None
    if rel_df is not None and not rel_df.empty:
        match = rel_df[rel_df["RELEASE_NO"].astype(str).str.strip() == newest[2]]
        release = match.to_dict("records")[0] if not match.empty else cbs.latest_release(rel_df)

    ranked = {g: _ranked(cur[g]) for g in groups}
    ranks_now = {g: _ranks(cur[g]) for g in groups}
    ranks_prev = {g: _ranks(prev[g]) for g in groups if g in prev}

    # ── combined per sex (sum over groups) ──
    combined = {}
    for g in groups:
        acc = combined.setdefault(g[0], {})
        for nm, (n, _) in cur[g].items():
            acc[nm] = acc.get(nm, 0) + n
    comb_rank = {s: sorted(acc.items(), key=lambda kv: (-kv[1], kv[0])) for s, acc in combined.items()}
    sexes = [s for s in ("girls", "boys") if s in comb_rank]

    distinct = sum(len(cur[g]) for g in groups)

    # ── top names per group ──
    top_chart = {"groups": [], "labels": []}
    for key in sexes:
        top = comb_rank[key][:TOP_N]
        top_chart["groups"].append({"label": f"כל ה{SEX_HE[key]}", "names": [k for k, _ in top],
                                    "counts": [int(v) for _, v in top], "shares": None})
    for g in groups:
        top = ranked[g][:TOP_N]
        top_chart["groups"].append({"label": _glabel(g), "names": [r[0] for r in top],
                                    "counts": [int(r[1]) for r in top],
                                    "shares": [round(r[2], 2) for r in top]})
    top_table = []
    for i in range(TOP_N):
        row = [str(i + 1)]
        for g in groups:
            r = ranked[g][i] if i < len(ranked[g]) else None
            row.append(f"{r[0]} ({_n(r[1])})" if r else "–")
        top_table.append(row)
    comb_table = []
    for i in range(TOP_N):
        row = [str(i + 1)]
        for key in sexes:
            r = comb_rank[key][i] if i < len(comb_rank[key]) else None
            row.append(f"{r[0]} ({_n(r[1])})" if r else "–")
        comb_table.append(row)

    # ── leaders cards ──
    leaders = []
    for g in groups:
        nm, n, p = ranked[g][0]
        tied = [r[0] for r in ranked[g][1:] if r[1] == n]
        if g in ranks_prev:
            pr = ranks_prev[g].get(nm)
            if pr == 1:
                change = f"גם ב-{year - 1} במקום הראשון"
            elif pr:
                change = f"ב-{year - 1}: {_ord(pr)}"
            else:
                change = f"לא ברשימת {year - 1}"
        else:
            change = ""
        leaders.append({"group": _glabel(g), "name": nm, "count": _n(n), "share": _p(p),
                        "tied": fmt.join_he(tied) if tied else "", "change": change})

    # ── movers (share change, percentage points) ──
    movers_chart, movers_tables, entries = {"groups": []}, [], {}
    big = [g for g in groups if g in prev and len(cur[g]) >= BIG_GROUP]
    for g in big:
        now_top = {r[0] for r in ranked[g][:MOVERS_POOL]}
        prev_top = {r[0] for r in _ranked(prev[g])[:MOVERS_POOL]}
        pool = sorted(now_top | prev_top)
        deltas = []
        for nm in pool:
            a = prev[g].get(nm, (0, 0))[1]
            b = cur[g].get(nm, (0, 0))[1]
            deltas.append((nm, b - a, a, b))
        ups = sorted((d for d in deltas if d[1] > 0), key=lambda d: (-d[1], d[0]))[:MOVERS_N]
        downs = sorted((d for d in deltas if d[1] < 0), key=lambda d: (d[1], d[0]))[:MOVERS_N]
        if not ups and not downs:
            continue
        sel = ups + list(reversed(downs))
        movers_chart["groups"].append({
            "label": _glabel(g),
            "names": [d[0] for d in sel],
            "delta": [round(d[1], 2) for d in sel],
            "prev": [round(d[2], 2) for d in sel],
            "now": [round(d[3], 2) for d in sel],
        })
        for d in sel:
            movers_tables.append([d[0], _glabel(g), fmt.pct_of(d[2], 2) if d[2] else "–",
                                  fmt.pct_of(d[3], 2) if d[3] else "–", _pp(d[1])])
        top_now = [r[0] for r in ranked[g][:TOP_N]]
        top_prev = {r[0] for r in _ranked(prev[g])[:TOP_N]}
        entries[g] = [nm for nm in top_now if nm not in top_prev]

    # ── rank slope (top 10 now vs a year earlier) ──
    slope = {"groups": []}
    slope_table = []
    for g in big:
        rows = []
        for nm, n, p in ranked[g][:TOP_N]:
            pr = ranks_prev[g].get(nm)
            rows.append({"name": nm, "now": ranks_now[g][nm],
                         "prev": min(pr, SLOPE_CAP + 1) if pr else SLOPE_CAP + 1})
            slope_table.append([nm, _glabel(g), str(pr) if pr else "–", str(ranks_now[g][nm])])
        ymax = max(max(r["prev"], r["now"]) for r in rows)
        slope["groups"].append({"label": _glabel(g), "rows": rows, "ymax": ymax})
    slope["cap"] = SLOPE_CAP + 1

    # ── concentration ──
    conc = {"labels": [], "defs": [], "top5": [], "next5": [], "rest": []}
    conc_table = []
    for g in groups:
        sh = [r[2] for r in ranked[g]]
        t5, t10, listed = sum(sh[:5]), sum(sh[:10]), sum(sh)
        conc["labels"].append(_glabel(g))
        conc["defs"].append(_gdef(g))
        conc["top5"].append(round(t5, 1))
        conc["next5"].append(round(t10 - t5, 1))
        conc["rest"].append(round(max(listed - t10, 0), 1))
        conc_table.append([_glabel(g), _p(t5), _p(t10), _n(len(sh)), _p(listed)])
    # sort bars by top-10 share, most concentrated first
    order = sorted(range(len(conc["labels"])), key=lambda i: (-(conc["top5"][i] + conc["next5"][i]), conc["labels"][i]))
    conc = {k: [v[i] for i in order] for k, v in conc.items()}
    conc_table = [conc_table[i] for i in order]

    # ── shared (unisex) names ──
    uni = []
    if "girls" in combined and "boys" in combined:
        for nm in set(combined["girls"]) & set(combined["boys"]):
            a, b = combined["girls"][nm], combined["boys"][nm]
            if min(a, b) / (a + b) >= UNISEX_MIN:
                uni.append((nm, a, b))
        uni.sort(key=lambda r: (-(r[1] + r[2]), r[0]))
        uni = uni[:UNISEX_N]
    uni_chart = {"names": [r[0] for r in uni], "girls": [int(r[1]) for r in uni], "boys": [int(r[2]) for r in uni]}
    uni_table = [[r[0], _n(r[1]), _n(r[2]), fmt.pct(r[1] / (r[1] + r[2]), 0)] for r in uni]

    # ── history ──
    trend = {"groups": []}
    trend_table = []
    gens, gen_cols, years_all = [], [], []
    hgroups = [g for g in sorted(hist, key=_gorder)]
    for g in hgroups:
        names = hist[g]
        years = sorted({y for v in names.values() for y in v})
        years_all = sorted(set(years_all) | set(years))
        pick = [r[0] for r in ranked[g][:TREND_N]] if g in ranked else []
        pick = [nm for nm in pick if nm in names]
        if pick:
            trend["groups"].append({"label": _glabel(g), "years": years,
                                    "series": [{"name": nm, "data": [int(names[nm].get(y, 0)) for y in years]}
                                               for nm in pick]})
        gen_cols.append(g)
    decades = sorted({y // 10 * 10 for y in years_all})
    # a decade needs at least 5 birth years in the table
    decades = [d for d in decades if sum(1 for y in years_all if d <= y < d + 10) >= 5]
    gen_leaders = {}
    for g in gen_cols:
        names = hist[g]
        for d in decades:
            tot = {nm: sum(v.get(y, 0) for y in range(d, d + 10)) for nm, v in names.items()}
            best = min(tot.items(), key=lambda kv: (-kv[1], kv[0]))
            if best[1] > 0:
                gen_leaders[(g, d)] = (best[0], best[1])
    for d in decades:
        row = [_decade_label(d, years_all)]
        for g in gen_cols:
            b = gen_leaders.get((g, d))
            row.append(b[0] if b else "–")
        gens.append(row)
    # trend table: per group, count in each decade for its picked names
    for grp in trend["groups"]:
        for s in grp["series"]:
            by_dec = []
            for d in decades:
                by_dec.append(_n(sum(v for y, v in zip(grp["years"], s["data"]) if d <= y < d + 10)))
            trend_table.append([s["name"], grp["label"]] + by_dec)
    decade_labels = [_decade_label(d, years_all) for d in decades]

    # ── localities ──
    city_rows, city_lead, city_leads_chart = [], {}, {"groups": []}
    city_groups = sorted(city, key=_gorder)
    for g in city_groups:
        lead = {}
        for loc, names in city[g].items():
            tot = sum(v[0] for v in names.values())
            if tot < CITY_MIN:
                continue
            best = sorted(names.items(), key=lambda kv: (-kv[1][0], kv[0]))
            top = [kv for kv in best if kv[1][0] == best[0][1][0]]
            if len(top) > 1:  # a tie at the top: no single leader
                lead[loc] = (" / ".join(kv[0] for kv in top[:3]), best[0][1][0], best[0][1][1], tot, True)
            else:
                lead[loc] = (best[0][0], best[0][1][0], best[0][1][1], tot, False)
        city_lead[g] = lead
        counts = {}
        for v in lead.values():
            if not v[4]:
                counts[v[0]] = counts.get(v[0], 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_N]
        if top:
            city_leads_chart["groups"].append({
                "label": _glabel(g), "names": [k for k, _ in top], "counts": [v for _, v in top],
                "n_loc": sum(1 for v in lead.values() if not v[4]), "ties": sum(1 for v in lead.values() if v[4])})
    if city_groups:
        size = {}
        for g in city_groups:
            for loc, names in city[g].items():
                size[loc] = size.get(loc, 0) + sum(v[0] for v in names.values())
        locs = sorted(size, key=lambda k: (-size[k], k))[:CITY_ROWS]
        for loc in locs:
            row = [loc]
            for g in city_groups:
                v = city_lead.get(g, {}).get(loc)
                row.append(f"{v[0]} ({_p(v[2])})" if v else "–")
            city_rows.append(row)

    # ── KPIs ──
    kpis = {}
    if "girls" in comb_rank:
        kpis["girl"] = {"value": int(comb_rank["girls"][0][1]), "display": _n(comb_rank["girls"][0][1]), "tone": "brand"}
    if "boys" in comb_rank:
        kpis["boy"] = {"value": int(comb_rank["boys"][0][1]), "display": _n(comb_rank["boys"][0][1]), "tone": "brand"}
    kpis["distinct"] = {"value": distinct, "display": _n(distinct), "tone": "brand"}
    t10 = [(conc["top5"][i] + conc["next5"][i], conc["labels"][i]) for i in range(len(conc["labels"]))]
    if t10:
        mx = max(t10)
        kpis["conc"] = {"value": round(mx[0], 1), "display": _p(mx[0]), "tone": "info"}

    # ── insights ──
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    add("combined", _ins_combined(comb_rank, year))
    for g in [x for x in groups if x[1] == "jewish"]:
        add(f"leader-{g[0]}", _ins_leader(g, ranked, ranks_prev, year))
    add("dominant", _ins_dominant(groups, ranked, year))
    add("riser", _ins_riser(movers_chart, groups, prev, cur, ranks_now, ranks_prev, year))
    add("entries", _ins_entries(entries, year))
    add("concentration", _ins_conc(conc))
    add("generations", _ins_generations(gen_cols, gen_leaders, decades, ranks_now, years_all, year))
    add("cities", _ins_cities(city_leads_chart, year))
    add("unisex", _ins_unisex(uni))

    # ── text ──
    g_names = fmt.join_he([f"{_glabel(g)}: {ranked[g][0][0]}" for g in groups if g[1] in ("jewish", "muslim")])
    lede = (f"אילו שמות קיבלו התינוקות שנולדו בישראל ב-{year}? לפי הלשכה המרכזית לסטטיסטיקה, "
            f"השמות המובילים הם {g_names}. בעמוד: עשרת השמות הנפוצים בכל קבוצת מין ודת, "
            f"השמות שעלו וירדו לעומת {year - 1}")
    if gens and years_all:
        lede += f", השם הנפוץ בכל עשור מאז {years_all[0]}"
    lede += " והשם המוביל בכל יישוב." if city_rows else "."
    summary_bits = []
    if "girls" in comb_rank and "boys" in comb_rank:
        summary_bits.append(f"השמות הנפוצים ביותר לילידי {year}: {comb_rank['boys'][0][0]} לבנים "
                            f"({_n(comb_rank['boys'][0][1])}) ו{comb_rank['girls'][0][0]} לבנות "
                            f"({_n(comb_rank['girls'][0][1])}), בכל הקבוצות יחד.")
    summary = ("השמות הפרטיים שניתנו לתינוקות בישראל לפי מין ודת, מנתוני הלמ\"ס. "
               + " ".join(summary_bits))
    jg = ranked.get(("girls", "jewish"))
    jb = ranked.get(("boys", "jewish"))
    if jg and jb:
        desc = (f"השמות הפופולריים לתינוקות שנולדו ב-{year}: {jg[0][0]}, {jg[1][0]} ו{jg[2][0]} לבנות, "
                f"{jb[0][0]}, {jb[1][0]} ו{jb[2][0]} לבנים. טבלאות לפי מין, דת ויישוב, מגמות מאז {years_all[0] if years_all else year - 1}.")
    else:
        desc = summary
    if len(desc) > 150:
        desc = (f"השמות הפופולריים לתינוקות שנולדו ב-{year} בישראל, לפי מין ודת: עשרת הראשונים, "
                f"העולים והיורדים והשם המוביל בכל יישוב.")

    labels = {
        "lede": lede,
        "year": str(year),
        "prev_year": str(year - 1),
        "girl_kpi": (f"ילידות {year} שנקראו {comb_rank['girls'][0][0]}, השם המוביל לבנות" if "girls" in comb_rank else ""),
        "boy_kpi": (f"ילידי {year} שנקראו {comb_rank['boys'][0][0]}, השם המוביל לבנים" if "boys" in comb_rank else ""),
        "distinct_kpi": f"שמות שונים ברשימות של {year} (סכום על פני הקבוצות)",
        "conc_kpi": (f"מהתינוקות קיבלו את עשרת השמות הנפוצים ({max(t10)[1]}, הקבוצה המרוכזת ביותר)" if t10 else ""),
        "leaders_title": f"השמות המובילים של ילידי {year}",
        "top_note": ("עשרת השמות הנפוצים בכל קבוצה. \"כל הבנות\" ו\"כל הבנים\" מחברים את הקבוצות "
                     "(השמות שניתנו ל-5 תינוקות לפחות בקבוצה). המספר הוא מספר התינוקות שקיבלו את השם."),
        "top_aria": f"עשרת השמות הנפוצים לילידי {year} לפי קבוצת מין ודת",
        "top_caption": f"עשרת השמות הנפוצים לילידי {year} בכל קבוצה (מספר התינוקות בסוגריים)",
        "comb_caption": f"עשרת השמות הנפוצים לילידי {year}, כל הקבוצות יחד",
        "slope_note": (f"דירוג עשרת השמות של {year} לעומת מקומם ב-{year - 1}. "
                       f"קו עולה: השם התקדם בדירוג. שם שלא היה ב-{SLOPE_CAP} הראשונים מוצג בתחתית. "
                       f"בקבוצות עם {BIG_GROUP} שמות לפחות ברשימה; בקבוצות הקטנות כל שם ניתן לעשרות תינוקות "
                       "והדירוג משתנה הרבה בגלל מקרים בודדים."),
        "slope_aria": f"שינוי בדירוג עשרת השמות המובילים בין {year - 1} ל-{year}",
        "slope_caption": f"דירוג עשרת השמות המובילים ב-{year} וב-{year - 1}",
        "movers_note": (f"השינוי בחלק השם מכלל התינוקות בקבוצה, בנקודות אחוז, בין {year - 1} ל-{year}, "
                        f"מבין {MOVERS_POOL} השמות הנפוצים בכל אחת מהשנים. "
                        f"החלק מנטרל את השינוי במספר הלידות. בקבוצות עם {BIG_GROUP} שמות לפחות ברשימה."),
        "movers_aria": f"השמות שחלקם עלה וירד הכי הרבה בין {year - 1} ל-{year}",
        "movers_caption": f"השמות שעלו וירדו בין {year - 1} ל-{year} (חלק מהתינוקות בקבוצה)",
        "conc_note": ("איזה חלק מהתינוקות בכל קבוצה קיבל את חמשת השמות הנפוצים, את חמשת הבאים, "
                      "ואת שאר השמות שברשימה (שמות שניתנו ל-5 תינוקות לפחות). החלק שחסר עד 100% "
                      "הוא שמות נדירים יותר ותינוקות שעדיין לא נרשם להם שם."),
        "conc_aria": f"ריכוז השמות לפי קבוצה, ילידי {year}",
        "conc_caption": f"חלק חמשת ועשרת השמות הנפוצים ומספר השמות ברשימה, ילידי {year}",
        "uni_note": (f"שמות שניתנו גם לבנות וגם לבנים ב-{year}, כשהמין הפחות נפוץ מקבל לפחות "
                     f"{round(UNISEX_MIN * 100)}% מהם. כל הקבוצות יחד."),
        "uni_aria": f"השמות המשותפים לבנות ולבנים, ילידי {year}",
        "uni_caption": f"שמות משותפים לבנות ולבנים, ילידי {year}",
        "trend_note": (f"כמה אנשים הרשומים היום במרשם האוכלוסין נושאים כל אחד מחמשת השמות המובילים של {year}, "
                       "לפי שנת הלידה. בשנים מוקדמות נספרים רק מי שרשומים היום, כך שהמספרים שם נמוכים מאלה שניתנו בפועל."),
        "trend_aria": f"מספר נושאי השמות המובילים של {year} לפי שנת לידה",
        "trend_caption": "מספר נושאי השם לפי עשור לידה",
        "gens_note": ("השם הנפוץ ביותר בכל עשור לידה, לפי מי שרשומים היום במרשם האוכלוסין. "
                      "עשור חלקי מסומן בשנותיו."),
        "gens_caption": "השם המוביל בכל עשור לידה, לפי קבוצה",
        "city_note": (f"השם הנפוץ ביותר בקרב ילידי {year} ב-{len(city_rows)} היישובים עם הכי הרבה תינוקות ברשימות, "
                      "והחלק שלו מהשמות שברשימת היישוב (שמות שניתנו ל-5 תינוקות לפחות ביישוב)."),
        "city_caption": f"השם המוביל לפי יישוב, ילידי {year}",
        "cityc_note": (f"בכמה יישובים כל שם הוא הנפוץ ביותר, ביישובים עם {CITY_MIN} תינוקות לפחות ברשימה. "
                       "יישוב שבו שני שמות שווים בראש לא נספר."),
        "cityc_aria": f"מספר היישובים שבהם כל שם הוא הנפוץ ביותר, ילידי {year}",
        "cityc_caption": f"מספר היישובים שבהם השם מוביל, ילידי {year}",
        "about_lists": ("הרשימות כוללות את השם הפרטי הראשון של כל תינוק, לפי מין ודת, ורק שמות שניתנו "
                        "ל-5 תינוקות לפחות באותה קבוצה. האחוזים הם מתוך כל התינוקות בקבוצה, ולכן אינם "
                        "מסתכמים ל-100%."),
    }
    if release is not None:
        labels["headline"] = cbs.clean(release.get("HEADLINE", ""))

    model = {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            "temporal_coverage": f"{years_all[0]}/{year}" if years_all else f"{min(y for e in lists.values() for y, _ in e)}/{year}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "שמות פופולריים לתינוקות: השמות הנפוצים בישראל",
                "description": desc,
                "name": "השמות הפופולריים לתינוקות בישראל",
                "alternate_names": [
                    "השמות הפרטיים שניתנו לתינוקות",
                    "השמות הנפוצים בישראל",
                    "שמות תינוקות פופולריים",
                    "שמות פופולריים לבנות ולבנים",
                ],
            },
        },
        "kpis": kpis,
        "charts": {
            "top": top_chart,
            "slope": slope,
            "movers": movers_chart,
            "conc": conc,
            "uni": uni_chart,
            "trend": trend,
            "cityc": city_leads_chart,
        },
        "insights": insights,
        "leaders": leaders,
        "labels": labels,
        "tables": {
            "top": top_table,
            "top_cols": ["מקום"] + [_glabel(g) for g in groups],
            "comb": comb_table,
            "comb_cols": ["מקום"] + [f"כל ה{SEX_HE[s]}" for s in sexes],
            "slope": slope_table,
            "movers": movers_tables,
            "conc": conc_table,
            "uni": uni_table,
            "trend": trend_table,
            "trend_cols": ["שם", "קבוצה"] + decade_labels,
            "gens": gens,
            "gens_cols": ["עשור לידה"] + [_glabel(g) for g in gen_cols],
            "city": city_rows,
            "city_cols": ["יישוב"] + [_glabel(g) for g in city_groups],
            "cityc": [[n, grp["label"], str(c)] for grp in city_leads_chart["groups"]
                      for n, c in zip(grp["names"], grp["counts"])],
        },
        "flags": {
            "slope": bool(slope["groups"]),
            "movers": bool(movers_chart["groups"]),
            "uni": len(uni) >= 3,
            "trend": bool(trend["groups"]),
            "gens": bool(gens) and bool(gen_cols),
            "city": bool(city_rows),
            "cityc": bool(city_leads_chart["groups"]),
        },
        "release": None if release is None else {
            "title": cbs.clean(release.get("TITLE", "")),
            "no": str(release.get("RELEASE_NO", "")),
            "date": _date_he(release.get("RELEASE_DATE", "")),
            "url": str(release.get("PAGE_URL", "") or ""),
            "pdf": str(release.get("REPORT_PDF_URL", "") or ""),
        },
    }
    return model


def _date_he(s):
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", str(s).strip())
    if not m:
        return str(s)
    return f"{int(m.group(3))} ב{fmt.MONTHS_HE[int(m.group(2)) - 1]} {m.group(1)}"


# ── insight rules ────────────────────────────────────────────────────────


def _ins_combined(comb_rank, year):
    if "girls" not in comb_rank or "boys" not in comb_rank:
        return None
    b, g = comb_rank["boys"], comb_rank["girls"]
    if len(b) < 2 or len(g) < 2:
        return None
    return (f"בכל הקבוצות יחד, השם הנפוץ ביותר לבנים שנולדו ב-{year} הוא {b[0][0]} "
            f"({_n(b[0][1])} תינוקות, לפני {b[1][0]} עם {_n(b[1][1])}), ולבנות {g[0][0]} "
            f"({_n(g[0][1])}, לפני {g[1][0]} עם {_n(g[1][1])}).")


def _ins_leader(g, ranked, ranks_prev, year):
    r = ranked[g]
    if len(r) < 3:
        return None
    nm, n, p = r[0]
    if r[1][1] == n:
        return None
    tail = ""
    if g in ranks_prev:
        pr = ranks_prev[g].get(nm)
        if pr == 1:
            tail = f", כמו ב-{year - 1}"
        elif pr:
            tail = f", לעומת {_ord(pr)} ב-{year - 1}"
    born = "ילידות" if g[0] == "girls" else "ילידי"
    return (f"השם הנפוץ ביותר בקרב {_glabel(g)} {born} {year} הוא {nm}: {_n(n)} תינוקות, "
            f"{_p(p)} מהקבוצה{tail}. אחריו {r[1][0]} ו{r[2][0]}.")


def _ins_dominant(groups, ranked, year):
    tops = [(ranked[g][0][2], g) for g in groups if ranked[g]]
    if len(tops) < 3:
        return None
    tops.sort(key=lambda t: (-t[0], _gorder(t[1])))
    best, g = tops[0]
    rest = sorted(t[0] for t in tops[1:])
    med = rest[len(rest) // 2]
    if best < 2 * med:
        return None
    nm = ranked[g][0][0]
    return (f"{nm} ניתן ל-{_p(best)} מ{_gdef(g)} שנולדו ב-{year}, החלק הגבוה ביותר של שם אחד "
            f"בכל הקבוצות. בשאר הקבוצות השם המוביל ניתן ל-{_p(rest[0])} עד {_p(rest[-1])} מהתינוקות.")


def _ins_riser(movers, groups, prev, cur, ranks_now, ranks_prev, year):
    def cur_count(label, nm):
        g = next(x for x in groups if _glabel(x) == label)
        return cur[g].get(nm, (0, 0))[0]

    best = None
    for grp in movers["groups"]:
        for nm, d, a, b in zip(grp["names"], grp["delta"], grp["prev"], grp["now"]):
            if d > 0 and cur_count(grp["label"], nm) >= RISER_MIN and (best is None or d > best[1] or (d == best[1] and nm < best[0])):
                best = (nm, d, a, b, grp["label"])
    if best is None or best[1] < 0.1:
        return None
    g = next(x for x in groups if _glabel(x) == best[4])
    rn, rp = ranks_now[g].get(best[0]), ranks_prev.get(g, {}).get(best[0])
    if rp == rn:
        move = "ונשאר במקום הראשון" if rn == 1 else f"ונשאר במקום ה-{rn}"
    elif rp:
        move = f"ממקום {rp} למקום {rn}"
    else:
        move = f"ועלה למקום {rn}"
    frm = f"מ-{_p(best[2])}" if best[2] else "משם שלא היה ברשימה"
    return (f"השם שהתחזק הכי הרבה הוא {best[0]} בקרב {best[4]}: {frm} "
            f"ב-{year - 1} ל-{_p(best[3])} מהתינוקות ב-{year}, {move}.")


def _ins_entries(entries, year):
    parts = []
    for g in sorted(entries, key=_gorder):
        if g[1] in ("jewish", "muslim") and entries[g]:
            parts.append(f"{fmt.join_he(entries[g])} ({_glabel(g)})")
    if not parts:
        return None
    return f"נכנסו לעשרת השמות הנפוצים ב-{year}, לעומת {year - 1}: {fmt.join_he(parts)}."


def _ins_conc(conc):
    if len(conc["labels"]) < 3:
        return None
    t10 = [a + b for a, b in zip(conc["top5"], conc["next5"])]
    hi, lo = 0, len(t10) - 1  # sorted most concentrated first
    if t10[hi] < 1.5 * t10[lo]:
        return None
    return (f"עשרת השמות הנפוצים ניתנו ל-{_p(t10[hi])} מ{conc['defs'][hi]}, לעומת "
            f"{_p(t10[lo])} בלבד מ{conc['defs'][lo]}, הקבוצה עם מגוון השמות הרחב ביותר.")


def _ins_generations(gen_cols, gen_leaders, decades, ranks_now, years_all, year):
    g = ("boys", "jewish")
    if g not in gen_cols or len(decades) < 3:
        return None
    first = gen_leaders.get((g, decades[0]))
    last = gen_leaders.get((g, decades[-1]))
    if not first or not last:
        return None
    seq = []
    for d in decades:
        b = gen_leaders.get((g, d))
        if b and (not seq or seq[-1] != b[0]):
            seq.append(b[0])
    if len(seq) < 2:
        return None
    if seq[-1] in seq[:-1]:
        seq_txt = f"{', '.join(seq[:-1])} ושוב {seq[-1]}"
    else:
        seq_txt = fmt.join_he(seq)
    rank = ranks_now.get(g, {}).get(first[0])
    where = "במקום הראשון" if rank == 1 else f"במקום ה-{rank}"
    tail = f"; ב-{year} {first[0]} {where}" if rank and first[0] != last[0] else ""
    return (f"השמות שהובילו בקרב בנים יהודים לאורך עשורי הלידה מאז {years_all[0]}, לפי הסדר: "
            f"{seq_txt}{tail}.")


def _ins_cities(cc, year):
    for grp in cc["groups"]:
        if not grp["counts"] or grp["n_loc"] < 5:
            continue
        nm, c = grp["names"][0], grp["counts"][0]
        if len(grp["counts"]) > 1 and grp["counts"][1] == c:
            continue
        born = "ילידות" if grp["label"].startswith("בנות") else "ילידי"
        return (f"{nm} הוא השם הנפוץ ביותר בקרב {grp['label']} {born} {year} ב-{c} מתוך "
                f"{grp['n_loc']} יישובים (יישובים עם {CITY_MIN} תינוקות לפחות ברשימה ושם מוביל אחד).")
    return None


def _ins_unisex(uni):
    if len(uni) < 3:
        return None
    nm, a, b = uni[0]
    near = min(uni, key=lambda r: (abs(r[1] - r[2]) / (r[1] + r[2]), r[0]))
    s = (f"השם המשותף הנפוץ ביותר לבנות ולבנים הוא {nm}: {_n(a)} בנות ו-{_n(b)} בנים.")
    if near[0] != nm:
        s += (f" המאוזן ביותר הוא {near[0]}, עם {_n(near[1])} בנות ו-{_n(near[2])} בנים.")
    return s
