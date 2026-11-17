"""מדדי קיימות (הון) בישראל: CBS's yearly sustainability (capital) release.

The release is a set of chart-data sheets ("תרשים N - ...", one "לוח א"),
and the set CHANGES between editions: 2023 and 2024 carried water,
land-use, Knesset and volunteering charts; 2026 dropped them and added the
improvement/worsening overview, biodiversity by monitoring unit, trust in
institutions and culture. The numbering moves too. So every table input
(t1..t16, the last three spare slots, all optional) is read with
`cbs.grid`, only the newest edition (the `releases` frame names it) is
used, and each chart is found by its TITLE text:

  overview   מגמות שינוי רב-שנתיות במדדי הון   improving/worsening counts by capital
  econ       ... הון כלכלי                     index lines (base year = 100)
  bio        מדד המגוון הביולוגי ... (survey)  weighted index + 3 parts per survey year
  bio_units  רכיבי מדד המגוון הביולוגי          the same parts per monitoring unit
  air        ... מזהמי אוויר                   exposure / target value × 100
  energy     אספקת אנרגיה ראשונית לנפש         one series
  renew      ... אנרגיה מתחדשת                 % of primary energy and of electricity
  health     הון אנושי ... בריאות               index lines
  edu        הון אנושי ... השכלה                index lines
  jobs       ... אוכלוסייה ותעסוקה              unemployment %, long-term %, migration
  trust      אמון כללי / אמון בזולת             % by sex and population group
  inst       מוסדות שלטון                       % trusting each institution
  culture    ... הון תרבותי                    index lines + actual counts

A chart missing from an edition drops its section. A table that is found
but whose header labels are gone raises (the layout changed: a human
should look). A block of years cut short drops only what it held.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*(?:\d+|[א-ת])[א-ת]?\s*[-–:]\s*")
YR = re.compile(r"^((?:19|20)\d\d)(?:/\d\d)?(?:\(\s*\))?$")
PAREN = re.compile(r"\s*[(\[][^)\]]*[)\]]")
NUMLIKE = re.compile(r"^[-−\d.,\s%]+$")
STEM = re.compile(r"t\d+")
KINDS = ("overview", "econ", "bio", "bio_units", "air", "energy", "renew", "health", "edu",
         "jobs", "trust", "inst", "culture")
PRIORITY = ("overview", "overview_lead", "renew", "air", "bio", "inst_gov", "trust_gap",
            "jobs_unemp", "health", "econ", "bio_units", "energy", "migration", "inst_police",
            "edu", "culture")
MAX_TOP = 8


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    if "מגמות שינוי" in t:
        return "overview"
    if "רכיבי מדד המגוון הביולוגי" in t:
        return "bio_units"
    if "מדד המגוון הביולוגי" in t:
        return "bio"
    if "הון כלכלי" in t:
        return "econ"
    if "מזהמי אוויר" in t:
        return "air"
    if "אנרגיה מתחדשת" in t:
        return "renew"
    if "אספקת אנרגיה ראשונית" in t and "לנפש" in t:
        return "energy"
    if "הון אנושי" in t and "בריאות" in t:
        return "health"
    if "הון אנושי" in t and "השכלה" in t:
        return "edu"
    if "אוכלוסייה ותעסוקה" in t:
        return "jobs"
    if "אמון כללי" in t or "אמון בזולת" in t:
        return "trust"
    if "מוסדות שלטון" in t:
        return "inst"
    if "הון תרבותי" in t:
        return "culture"
    return None


def _tables(frames):
    """{kind: rows} over every table input's rows of the newest edition the
    tables carry (one edition only, should a stem ever hold an older one);
    the first match by stem number wins."""
    out = {}
    names = sorted((n for n in frames if STEM.fullmatch(n)), key=lambda n: int(n[1:]))
    eds = [frames[n][["RELEASE_NO", "RELEASE_DATE"]] for n in names if not frames[n].empty]
    if not eds:
        raise ValueError("no table has rows")
    release_no = str(cbs.latest_release(pd.concat(eds).drop_duplicates(), "tables")["RELEASE_NO"]).strip()
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        df = df[df["RELEASE_NO"].astype(str).str.strip() == release_no]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        k = _kind(_title(rows))
        if k and k not in out:
            out[k] = rows
    return out


# ── year blocks ──────────────────────────────────────────────────────────


def _yr(c):
    m = YR.match(c)
    return int(m.group(1)) if m else None


def _is_label(c):
    return bool(c) and not NUMLIKE.match(c) and not TITLE.match(c)


def _blocks(rows, name):
    """Runs of year rows. Each block: {"start", "years": [(row, year)],
    "cols": {j: {"label", "group"}}, "vals": {j: {year: value}}, "tag"}.
    The year column is the one holding the most years; value columns are
    to its left-to-right side (higher index) with at least one number.
    A label is the nearest text above the block in that column (year rows
    skipped); the group is the next text above that, stopping at a year
    row (a later block falls back to the first block's group)."""
    ycol = cbs.best_col(rows, lambda v: _yr(v) is not None)
    if ycol is None:
        raise ValueError(f"{name}: no year column")
    is_year = [_yr(cbs.cell(r, ycol)) is not None for r in rows]
    runs, cur, prev = [], [], None
    for i, r in enumerate(rows):
        y = _yr(cbs.cell(r, ycol)) if is_year[i] else None
        if y is None:
            # A footnote row (long text only) inside a run of years does not
            # end it; anything else (a header, a row of numbers) does.
            if cur and all(len(c) > 25 and not NUMLIKE.match(c) for c in r if c):
                continue
            if cur:
                runs.append(cur)
            cur, prev = [], None
            continue
        if prev is not None and y <= prev:
            runs.append(cur)
            cur = []
        cur.append((i, y))
        prev = y
    if cur:
        runs.append(cur)

    blocks = []
    for run in runs:
        start = run[0][0]
        width = max(len(rows[i]) for i, _ in run)
        vals = {}
        for j in range(ycol + 1, width):
            col = {y: cbs.val(rows[i], j) for i, y in run}
            if any(v is not None for v in col.values()):
                vals[j] = col
        cols = {}
        for j in vals:
            label, group, lrow, grow, k = None, None, None, None, start - 1
            while k >= 0:
                c = cbs.cell(rows[k], j)
                if label is None:
                    if not is_year[k] and _is_label(c):
                        label, lrow = c, k
                else:
                    if is_year[k]:
                        break
                    if _is_label(c):
                        group, grow = c, k
                        break
                k -= 1
            cols[j] = {"label": label, "group": group, "lrow": lrow, "grow": grow}
        # A merged group header sits over its leftmost column only: the
        # columns to its right with an empty cell on that row inherit it.
        prev = None
        for j in sorted(cols):
            c = cols[j]
            if (c["group"] is None and prev is not None and prev["group"] is not None
                    and prev["lrow"] == c["lrow"] and not cbs.cell(rows[prev["grow"]], j)):
                c["group"], c["grow"] = prev["group"], prev["grow"]
            prev = c
        tag = " ".join(c for c in rows[start][:ycol] if c)
        blocks.append({"start": start, "years": run, "cols": cols, "vals": vals, "tag": tag})
    if blocks:
        first = blocks[0]["cols"]
        for b in blocks[1:]:
            for j, c in b["cols"].items():
                if c["group"] is None and j in first:
                    c["group"] = first[j]["group"] or first[j]["label"]
    return blocks


def _is_index(b):
    """Every series starts at 100 (a base-year index)."""
    firsts = []
    for col in b["vals"].values():
        v = next((col[y] for y in sorted(col) if col[y] is not None), None)
        firsts.append(v)
    return bool(firsts) and all(v is not None and abs(v - 100) < 1e-6 for v in firsts)


def _short(label):
    """A legend name: no footnotes or parentheticals, the part before
    ' - ', no trailing colon."""
    s = PAREN.sub("", label).strip()
    s = re.split(r"\s+[-–]\s+", s)[0].strip()
    return s.rstrip(":").strip()


def _series(b, name):
    """[(name, {year: value})] for a block's labelled columns, left to
    right. A column with no label raises."""
    out = []
    for j in sorted(b["vals"]):
        c = b["cols"][j]
        if not c["label"]:
            raise ValueError(f"{name}: column {j + 1} has no header label")
        out.append((c, b["vals"][j]))
    return out


def _last(col):
    ys = [y for y in sorted(col) if col[y] is not None]
    return (ys[-1], col[ys[-1]]) if ys else (None, None)


def _first(col):
    ys = [y for y in sorted(col) if col[y] is not None]
    return (ys[0], col[ys[0]]) if ys else (None, None)


def _r(v, d=1):
    return None if v is None else round(v, d)


def _n(v, d=1):
    return fmt.num_he(v, d)


def _signed(v, d=1):
    s = fmt.num_he(abs(v), d)
    return (fmt.MINUS + s) if v < 0 and float(s.replace(",", "")) != 0 else s


def _line_chart(series, d=1):
    """{x, names, data} for a line chart over the union of years."""
    years = sorted({y for _, col in series for y in col if col[y] is not None})
    return {
        "x": [str(y) for y in years],
        "names": [n for n, _ in series],
        "data": [[_r(col.get(y), d) for y in years] for _, col in series],
    }


def _year_table(series, d=1):
    years = sorted({y for _, col in series for y in col if col[y] is not None})
    rows = []
    for y in years:
        rows.append([str(y)] + [("–" if col.get(y) is None else _n(col[y], d)) for _, col in series])
    return rows


def _index_section(rows, name):
    """An index block (every series 100 in its base year) as named series."""
    blocks = _blocks(rows, name)
    idx = [b for b in blocks if _is_index(b)]
    if not idx:
        return None
    b = idx[0]
    out, bare = [], {}
    for c, col in _series(b, name):
        nm = _short(c["label"])
        full = nm
        g = c["group"]
        if g and g.endswith(":"):
            full = f"{_short(g)}: {nm}"
        out.append((full, col))
        # Prose uses the bare label when it stands on its own (3+ words).
        bare[full] = nm if len(nm.split()) >= 3 else full
    actual = next((x for x in blocks if not _is_index(x)), None)
    return {"index": out, "actual": actual, "bare": bare}


def _idx(nm):
    """'המדד של X', or X itself when X is already named an index."""
    return nm if nm.startswith("מדד") else f"המדד של {nm}"


def _index_extremes(series):
    """(name, last year, last value) of the highest and lowest latest index
    value, or None with fewer than two series."""
    pts = []
    for nm, col in series:
        y, v = _last(col)
        if v is not None:
            pts.append((nm, y, v))
    if len(pts) < 2:
        return None
    hi = max(pts, key=lambda p: (p[2], p[0]))
    lo = min(pts, key=lambda p: (p[2], p[0]))
    return hi, lo


def _base_year(col):
    for y in sorted(col):
        if col[y] is not None and abs(col[y] - 100) < 1e-6:
            return y
    return _first(col)[0]


# ── sections ─────────────────────────────────────────────────────────────


def _overview(rows):
    h = cbs.row_with(rows, "שיפור", name="overview")
    hr = rows[h]
    ci = cbs.col_after(hr, "שיפור")
    cw = cbs.col_after(hr, "הרעה")
    cf = cbs.col_after(hr, "ללא שינוי", contains=True)
    out, total = [], None
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        a, w, f = cbs.val(r, ci), cbs.val(r, cw), cbs.val(r, cf)
        if not lab or a is None or w is None or f is None:
            continue
        rec = {"name": lab, "imp": a, "worse": w, "flat": f, "n": a + w + f}
        if lab.startswith("סך ה"):
            total = rec
        else:
            out.append(rec)
    if not out:
        return None
    if total is None:
        total = {"name": "סך הכל", "imp": sum(o["imp"] for o in out),
                 "worse": sum(o["worse"] for o in out), "flat": sum(o["flat"] for o in out)}
        total["n"] = total["imp"] + total["worse"] + total["flat"]
    return {"total": total, "caps": out}


def _bio(rows):
    h = cbs.row_with(rows, "מצב המינים", name="bio", contains=True)
    hr = rows[h]
    cols = [(j, _short(c)) for j, c in enumerate(hr) if j >= 1 and _is_label(c)]
    if not cols:
        raise ValueError("bio: no component labels")
    years = []
    for r in rows[h + 1:]:
        m = re.fullmatch(r"מדד\s*((?:19|20)\d\d)", cbs.cell(r, 0))
        if m:
            years.append((int(m.group(1)), r))
    years.sort(key=lambda t: t[0])
    if not years:
        return None
    w = next((k for k, (_, nm) in enumerate(cols) if "משוקלל" in nm or "מגוון" in nm), 0)
    names = [nm.replace("- מדד משוקלל", "").strip() if k == w else nm for k, (_, nm) in enumerate(cols)]
    names[w] = "מדד משוקלל"
    data = [[_r(cbs.val(r, j), 3) for j, _ in cols] for _, r in years]
    return {"years": [y for y, _ in years], "names": names, "w": w, "data": data}


def _bio_units(rows):
    h = cbs.row_with(rows, "יחידות ניטור", name="bio_units", contains=True)
    width = max(len(r) for r in rows)
    i, hdr = h, [""] * width
    while i < len(rows) and cbs.val(rows[i], 1) is None:
        for j in range(1, width):
            c = cbs.cell(rows[i], j)
            if c:
                hdr[j] = (hdr[j] + " " + c).strip()
        i += 1
    dir_col = next((j for j in range(width) if "כיוון" in hdr[j]), None)
    num_cols = [j for j in range(1, width) if hdr[j] and j != dir_col]
    if not num_cols:
        raise ValueError("bio_units: no component labels")
    units, last = [], None
    for r in rows[i:]:
        lab = cbs.cell(r, 0)
        # Footnotes ("(1) רמת הייחוס ...") lose their mark in cbs.clean:
        # skip long text rows; a unit name is a few words.
        if not lab or lab.startswith("(") or len(lab) > 30:
            continue
        vals = [cbs.val(r, j) for j in num_cols]
        if all(v is None for v in vals):
            if last is not None and not any(cbs.cell(r, j) for j in range(1, width)):
                last["name"] = f"{last['name']} {lab}"
            continue
        last = {"name": lab, "vals": vals,
                "dir": cbs.cell(r, dir_col) if dir_col is not None else ""}
        units.append(last)
    if not units:
        return None
    nat = next((u for u in units if "ארצי" in u["name"]), None)
    rest = [u for u in units if u is not nat]
    return {"names": [_short(hdr[j]) for j in num_cols], "national": nat, "units": rest,
            "dir_head": hdr[dir_col] if dir_col is not None else ""}


def _single_block(rows, name):
    blocks = _blocks(rows, name)
    if not blocks:
        return None
    return [(_short(c["label"]), col) for c, col in _series(blocks[0], name)]


def _jobs(rows):
    blocks = _blocks(rows, "jobs")
    act = [b for b in blocks if not _is_index(b)]
    if not act:
        return None
    b = act[0]
    unemp, longt, mig, mig_k = [], [], None, False
    for c, col in _series(b, "jobs"):
        g = (c["group"] or "")
        lab = _short(c["label"])
        if "הגירה" in lab or "הגירה" in g:
            mig, mig_k = col, "אלפים" in c["label"]
        elif "ממושכת" in g:
            longt.append((lab, col))
        elif "בלתי מועסקים" in g:
            unemp.append((lab, col))
    if not unemp and not longt and mig is None:
        raise ValueError("jobs: no known column groups")
    return {"unemp": unemp, "long": longt, "mig": mig, "mig_thousands": mig_k}


def _inst(rows):
    blocks = _blocks(rows, "inst")
    out = []
    for b in blocks:
        if not b["tag"]:
            continue
        ser = _series(b, "inst")
        groups = [(_short(c["label"]), col) for c, col in ser]
        tot = next((col for nm, col in groups if nm.startswith("סך ה")), None)
        if tot is None:
            raise ValueError("inst: no total column")
        out.append({"name": _short(b["tag"]), "total": tot, "groups": groups})
    return out or None


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    m = re.search(r"(?:19|20)\d\d\s*$", str(rel["TITLE"]))
    rep_year = m.group(0).strip() if m else ""

    charts, tables, flags, labels, kpis = {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── overview ─────────────────────────────────────────────────────────
    ov = _overview(tabs["overview"]) if "overview" in tabs else None
    if ov:
        t = ov["total"]
        flags["overview"] = True
        charts["overview"] = {
            "names": [c["name"] for c in ov["caps"]],
            "imp": [c["imp"] for c in ov["caps"]],
            "worse": [c["worse"] for c in ov["caps"]],
            "flat": [c["flat"] for c in ov["caps"]],
            "n": [c["n"] for c in ov["caps"]],
        }
        tables["overview"] = [[c["name"], fmt.int_he(c["imp"]), fmt.int_he(c["worse"]),
                               fmt.int_he(c["flat"]), fmt.int_he(c["n"])]
                              for c in ov["caps"] + [t]]
        pi, pw = t["imp"] / t["n"] * 100, t["worse"] / t["n"] * 100
        kpis["indicators"] = {"value": t["n"], "display": fmt.int_he(t["n"]), "tone": "brand"}
        kpis["improved"] = {"value": round(pi, 1), "display": fmt.pct_of(pi, 1),
                            "tone": "ok" if pi > pw else "warn"}
        kpis["worsened"] = {"value": round(pw, 1), "display": fmt.pct_of(pw, 1),
                            "tone": "danger" if pw > pi else "warn"}
        labels["overview_aria"] = "מגמות השינוי במדדי ההון לפי סוג ההון"
        if pi > pw:
            word = "שיפור"
        elif pw > pi:
            word = "הרעה"
        else:
            word = None
        add("overview", (f"מתוך {fmt.int_he(t['n'])} מדדי הקיימות, ב-{fmt.pct_of(pi, 1)} חלה מגמת שיפור "
                         f"רב-שנתית, ב-{fmt.pct_of(pw, 1)} מגמת הרעה, וב-{fmt.pct_of(100 - pi - pw, 1)} "
                         f"לא חל שינוי מובהק"
                         + (f": רוב המגמות המובהקות הן של {word}." if word else ".")))
        caps = [c for c in ov["caps"] if c["n"] >= 4]
        if len(caps) >= 2:
            best = max(caps, key=lambda c: (c["imp"] / c["n"], c["name"]))
            worst = max(caps, key=lambda c: (c["worse"] / c["n"], c["name"]))
            txt = (f"ב{best['name']} שיעור המדדים המשתפרים הגבוה ביותר: {fmt.int_he(best['imp'])} "
                   f"מתוך {fmt.int_he(best['n'])} ({fmt.pct_of(best['imp'] / best['n'] * 100, 0)}).")
            if worst is not best and worst["worse"] > 0:
                txt += (f" ב{worst['name']} שיעור ההרעה הגבוה ביותר: {fmt.int_he(worst['worse'])} "
                        f"מתוך {fmt.int_he(worst['n'])} מדדים "
                        f"({fmt.pct_of(worst['worse'] / worst['n'] * 100, 0)}).")
            add("overview_lead", txt)

    # ── index sections: econ, health, edu, culture ───────────────────────
    idx_titles = {"econ": "הון כלכלי", "health": "בריאות", "edu": "השכלה וכישורים",
                  "culture": "הון תרבותי"}
    idx = {}
    for k in ("econ", "health", "edu", "culture"):
        if k not in tabs:
            continue
        sec = _index_section(tabs[k], k)
        if not sec or len(sec["index"]) < 1:
            continue
        ser = sec["index"]
        idx[k] = sec
        flags[k] = True
        charts[k] = _line_chart(ser, 1)
        tables[k] = _year_table(ser, 1)
        labels[k + "_cols"] = ["שנה"] + [n for n, _ in ser]
        bases = sorted({_base_year(col) for _, col in ser})
        labels[k + "_base"] = fmt.join_he([str(b) for b in bases])
        labels[k + "_aria"] = f"מדדי {idx_titles[k]} לאורך השנים, שנת בסיס = 100"
        ext = _index_extremes(ser)
        if ext:
            (hn, hy, hv), (ln, ly, lv) = ext
            hn, ln = sec["bare"][hn], sec["bare"][ln]
            if k == "culture":
                # Distance below each series' own peak: the hardest-hit
                # culture indicator since its best year.
                gaps = []
                for nm, col in ser:
                    py = max((y for y in col if col[y] is not None), key=lambda y: (col[y], -y))
                    y1, v1 = _last(col)
                    if y1 is not None and y1 > py and col[py] > 0:
                        gaps.append((v1 / col[py] - 1, nm, py, y1))
                if gaps:
                    g, nm, py, y1 = min(gaps)
                    nm = sec["bare"][nm]
                    if g <= -0.05:
                        add("culture", f"ב{nm}, הנתון של {y1} עדיין נמוך ב-{fmt.pct(-g, 0)} "
                                       f"מהשיא של {py}.")
                continue
            if hv > 100 and lv < 100:
                add(k, f"ב{idx_titles[k]}, {_idx(hn)} הגיע ל-{_n(hv)} ב-{hy} (100 בשנת הבסיס), "
                       f"ואילו {_idx(ln)} ירד ל-{_n(lv)} ב-{ly}.")
            elif hv > 100:
                add(k, f"ב{idx_titles[k]}, {_idx(hn)} עלה הכי הרבה: {_n(hv)} ב-{hy} "
                       f"(100 בשנת הבסיס).")

    # culture: the actual counts of the latest year with data, as a table
    if "culture" in idx and idx["culture"]["actual"] is not None:
        b = idx["culture"]["actual"]
        rows_ = []
        for c, col in _series(b, "culture"):
            y, v = _last(col)
            if v is not None:
                rows_.append([_short(c["label"]), str(y), _n(v, 0 if v >= 100 else 1)])
        if rows_:
            tables["culture_actual"] = rows_

    # ── biodiversity ─────────────────────────────────────────────────────
    bio = _bio(tabs["bio"]) if "bio" in tabs else None
    if bio:
        flags["bio"] = True
        charts["bio"] = bio
        tables["bio"] = [[str(y)] + [("–" if v is None else _n(v, 3)) for v in row]
                         for y, row in zip(bio["years"], bio["data"])]
        labels["bio_cols"] = ["שנת מדידה"] + bio["names"]
        labels["bio_aria"] = "מדד המגוון הביולוגי ורכיביו לפי שנת מדידה, ביחס לרמת הייחוס"
        w = bio["w"]
        first, last = bio["data"][0][w], bio["data"][-1][w]
        y0, y1 = bio["years"][0], bio["years"][-1]
        if last is not None:
            kpis["bio"] = {"value": last, "display": _n(last, 3),
                           "tone": "ok" if last >= 1 else ("danger" if last < 0.95 else "warn")}
            labels["bio_kpi"] = f"מדד המגוון הביולוגי, {y1} (רמת הייחוס = 1)"
        if first is not None and last is not None and y1 > y0:
            if last < first:
                trend = f"ירד מ-{_n(first, 3)} ב-{y0} ל-{_n(last, 3)} ב-{y1}"
            elif last > first:
                trend = f"עלה מ-{_n(first, 3)} ב-{y0} ל-{_n(last, 3)} ב-{y1}"
            else:
                trend = f"נותר {_n(last, 3)} בין {y0} ל-{y1}"
            parts = [(bio["names"][k], v) for k, v in enumerate(bio["data"][-1])
                     if k != w and v is not None]
            txt = f"מדד המגוון הביולוגי המשוקלל {trend}"
            if parts:
                lo = min(parts, key=lambda p: (p[1], p[0]))
                if lo[1] < 1:
                    txt += f". הרכיב החלש ביותר הוא {lo[0]} ({_n(lo[1], 3)})"
            add("bio", txt + "; 1 היא רמת הייחוס.")

    bu = _bio_units(tabs["bio_units"]) if "bio_units" in tabs else None
    if bu and bu["units"]:
        flags["bio_units"] = True
        units = sorted(bu["units"], key=lambda u: (u["vals"][0] is None, u["vals"][0] or 0, u["name"]))
        charts["bio_units"] = {
            "names": [u["name"] for u in units],
            "values": [_r(u["vals"][0], 3) for u in units],
            "national": _r(bu["national"]["vals"][0], 3) if bu["national"] else None,
        }
        has_dir = any(u["dir"] for u in bu["units"])
        labels["bio_units_cols"] = ["יחידת ניטור"] + bu["names"] + (["כיוון השינוי"] if has_dir else [])
        all_u = ([bu["national"]] if bu["national"] else []) + units
        tables["bio_units"] = [[u["name"]] + [("–" if v is None else _n(v, 3)) for v in u["vals"]]
                               + ([{"↓": "ירידה", "↑": "עלייה"}.get(u["dir"], u["dir"] or "–")]
                                  if has_dir else [])
                               for u in all_u]
        labels["bio_units_aria"] = "מדד המגוון הביולוגי לפי יחידת ניטור"
        valid = [u for u in units if u["vals"][0] is not None]
        if len(valid) >= 2:
            lo, hi = valid[0], valid[-1]
            down = sum(1 for u in bu["units"] if u["dir"] == "↓")
            txt = (f"בין יחידות הניטור, מדד המגוון הביולוגי הנמוך ביותר נמדד ב{lo['name']} "
                   f"({_n(lo['vals'][0], 3)}) והגבוה ביותר ב{hi['name']} ({_n(hi['vals'][0], 3)})")
            if has_dir and down == len(bu["units"]):
                txt += f"; בכל {fmt.int_he(down)} היחידות המגמה היא ירידה"
            elif has_dir and down:
                txt += f"; ב-{fmt.int_he(down)} מתוך {fmt.int_he(len(bu['units']))} היחידות המגמה היא ירידה"
            add("bio_units", txt + ".")

    # ── air ──────────────────────────────────────────────────────────────
    air = _single_block(tabs["air"], "air") if "air" in tabs else None
    if air:
        flags["air"] = True
        charts["air"] = _line_chart(air, 0)
        tables["air"] = _year_table(air, 0)
        labels["air_cols"] = ["שנה"] + [n for n, _ in air]
        labels["air_aria"] = "חשיפת האוכלוסייה למזהמי אוויר ביחס לערך היעד"
        lasts = [(nm, *_last(col), *_first(col)) for nm, col in air]
        lasts = [x for x in lasts if x[2] is not None]
        if lasts:
            top = max(lasts, key=lambda x: (x[2], x[0]))
            nm, y1, v1, y0, v0 = top
            above = [x for x in lasts if x[2] > 100]
            if v1 > 100 and y1 > y0:
                move = "ירדה" if v1 < v0 else ("עלתה" if v1 > v0 else "נותרה")
                txt = (f"החשיפה ל-{nm} {move} מ-{fmt.int_he(v0)} ב-{y0} ל-{fmt.int_he(v1)} ב-{y1}, "
                       f"עדיין פי {_n(v1 / 100)} מערך היעד (100)")
                if len(above) == len(lasts) and len(lasts) > 1:
                    txt += f"; כל {fmt.int_he(len(lasts))} המזהמים מעל ערך היעד"
                add("air", txt + ".")

    # ── energy ───────────────────────────────────────────────────────────
    en = _single_block(tabs["energy"], "energy") if "energy" in tabs else None
    if en:
        nm, col = en[0]
        flags["energy"] = True
        charts["energy"] = _line_chart([(nm, col)], 2)
        tables["energy"] = _year_table([(nm, col)], 2)
        labels["energy_aria"] = "אספקת אנרגיה ראשונית לנפש לפי שנה"
        (y0, v0), (y1, v1) = _first(col), _last(col)
        if y1 is not None and y1 > y0 and v0:
            ch = v1 / v0 - 1
            if abs(ch) >= 0.02:
                add("energy", f"אספקת האנרגיה הראשונית לנפש {'ירדה' if ch < 0 else 'עלתה'} "
                              f"ב-{fmt.pct(abs(ch), 0)} בין {y0} ל-{y1}, מ-{_n(v0, 2)} ל-{_n(v1, 2)}.")

    # ── renewables ───────────────────────────────────────────────────────
    rn = _single_block(tabs["renew"], "renew") if "renew" in tabs else None
    if rn:
        flags["renew"] = True
        charts["renew"] = _line_chart(rn, 1)
        tables["renew"] = _year_table(rn, 1)
        labels["renew_cols"] = ["שנה"] + [n for n, _ in rn]
        labels["renew_aria"] = "שיעור האנרגיה המתחדשת לפי שנה"
        elec = next(((n, c) for n, c in rn if "חשמל" in n), rn[-1])
        (y0, v0), (y1, v1) = _first(elec[1]), _last(elec[1])
        if y1 is not None:
            kpis["renew"] = {"value": round(v1, 1), "display": fmt.pct_of(v1, 1), "tone": "info"}
            labels["renew_kpi"] = f"ייצור חשמל ממקורות מתחדשים, {y1}"
            if y1 > y0 and v1 > v0:
                txt = (f"חלקה של האנרגיה המתחדשת בייצור החשמל עלה מ-{fmt.pct_of(v0, 1)} ב-{y0} "
                       f"ל-{fmt.pct_of(v1, 1)} ב-{y1}")
                prim = next(((n, c) for n, c in rn if n != elec[0]), None)
                if prim:
                    py, pv = _last(prim[1])
                    if pv is not None:
                        txt += f"; מתוך כלל אספקת האנרגיה הראשונית: {fmt.pct_of(pv, 1)} ב-{py}"
                add("renew", txt + ".")

    # ── jobs ─────────────────────────────────────────────────────────────
    jobs = _jobs(tabs["jobs"]) if "jobs" in tabs else None
    if jobs and jobs["unemp"]:
        ser = jobs["unemp"] + [(f"אבטלה ממושכת: {n}", c) for n, c in jobs["long"]]
        flags["jobs"] = True
        charts["jobs"] = _line_chart(jobs["unemp"], 1)
        tables["jobs"] = _year_table(ser, 1)
        labels["jobs_cols"] = ["שנה"] + [n for n, _ in ser]
        labels["jobs_aria"] = "שיעור הבלתי מועסקים לפי מין ושנה"
        tot = next((c for n, c in jobs["unemp"] if n.startswith("סך ה")), jobs["unemp"][0][1])
        y1, v1 = _last(tot)
        ys = [y for y in tot if tot[y] is not None]
        if y1 is not None and len(ys) >= 3:
            lo = min(ys, key=lambda y: (tot[y], -y))
            txt = f"שיעור הבלתי מועסקים היה {fmt.pct_of(v1, 1)} ב-{y1}"
            if lo == y1:
                txt += f", הנמוך ביותר מאז {min(ys)}"
            lt = next((c for n, c in jobs["long"] if n.startswith("סך ה")), None)
            if lt:
                ly_, lv = _last(lt)
                if lv is not None:
                    txt += f". מתוכם, {fmt.pct_of(lv, 1)} מובטלים לאורך זמן (נתון {ly_})"
            add("jobs_unemp", txt + ".")
    if jobs and jobs["mig"]:
        col = jobs["mig"]
        if not jobs["mig_thousands"]:
            col = {y: (None if v is None else v / 1000) for y, v in col.items()}
        flags["migration"] = True
        ys = sorted(y for y in col if col[y] is not None)
        charts["migration"] = {"x": [str(y) for y in ys], "y": [_r(col[y], 1) for y in ys]}
        tables["migration"] = [[str(y), _signed(col[y], 1)] for y in ys]
        labels["migration_aria"] = "מאזן ההגירה לפי שנה, באלפים"
        if len(ys) >= 3:
            y1, v1 = ys[-1], col[ys[-1]]
            lo = min(ys, key=lambda y: (col[y], -y))
            if v1 < 0:
                txt = f"מאזן ההגירה ב-{y1} היה שלילי: {_n(abs(v1))} אלף"
            elif v1 > 0:
                txt = f"מאזן ההגירה ב-{y1} היה חיובי: {_n(v1)} אלף"
            else:
                txt = None
            if txt:
                if lo == y1 and v1 < 0:
                    txt += f", השלילי ביותר מאז {ys[0]}"
                add("migration", txt + ".")

    # ── trust ────────────────────────────────────────────────────────────
    tr = _single_block(tabs["trust"], "trust") if "trust" in tabs else None
    if tr:
        flags["trust"] = True
        charts["trust"] = _line_chart(tr, 1)
        tables["trust"] = _year_table(tr, 1)
        labels["trust_cols"] = ["שנה"] + [n for n, _ in tr]
        labels["trust_aria"] = "שיעור הנותנים אמון בזולת לפי מין וקבוצת אוכלוסייה"
        d = dict(tr)
        tot = next((c for n, c in tr if n.startswith("סך ה")), None)
        if tot:
            y1, v1 = _last(tot)
            kpis["trust"] = {"value": v1, "display": fmt.pct_of(v1, 1), "tone": "brand"}
            labels["trust_kpi"] = f"נותנים אמון בזולת, בני 20 ומעלה, {y1}"
        if "יהודים" in d and "ערבים" in d:
            yj, vj = _last(d["יהודים"])
            ya, va = _last(d["ערבים"])
            if yj == ya and vj is not None and va is not None and vj != va:
                hi, lo = (("יהודים", vj), ("ערבים", va)) if vj > va else (("ערבים", va), ("יהודים", vj))
                big = "פער גדול" if abs(vj - va) >= 10 else "פער"
                txt = (f"{big} באמון בזולת: ב-{yj} {fmt.pct_of(hi[1], 1)} מה{hi[0]} "
                       f"נותנים אמון באחרים, לעומת {fmt.pct_of(lo[1], 1)} מה{lo[0]}")
                ar = d["ערבים"]
                ys = [y for y in ar if ar[y] is not None]
                if len(ys) >= 3 and min(ys, key=lambda y: (ar[y], -y)) == ya:
                    txt += f"; בקרב הערבים זהו השיעור הנמוך ביותר מאז {min(ys)}"
                add("trust_gap", txt + ".")

    # ── institutions ─────────────────────────────────────────────────────
    inst = _inst(tabs["inst"]) if "inst" in tabs else None
    if inst:
        flags["inst"] = True
        ser = [(i["name"], i["total"]) for i in inst]
        charts["inst"] = _line_chart(ser, 1)
        tables["inst"] = _year_table(ser, 1)
        labels["inst_cols"] = ["שנה"] + [n for n, _ in ser]
        labels["inst_aria"] = "שיעור הנותנים אמון במוסדות השלטון לפי שנה"
        # latest year by group, per institution
        gnames = [g for g, _ in inst[0]["groups"]]
        lat = []
        for i in inst:
            y, _ = _last(i["total"])
            gd = dict(i["groups"])
            lat.append([_r(gd[g].get(y), 1) if g in gd else None for g in gnames])
        charts["inst_groups"] = {"names": [i["name"] for i in inst], "groups": gnames, "data": lat}
        ly_ = max(_last(i["total"])[0] for i in inst)
        labels["inst_groups_year"] = str(ly_)
        tables["inst_groups"] = [[i["name"]] + [("–" if v is None else fmt.pct_of(v, 1)) for v in row]
                                 for i, row in zip(inst, lat)]
        labels["inst_groups_cols"] = ["מוסד"] + gnames
        labels["inst_groups_aria"] = f"אמון במוסדות השלטון לפי קבוצה, {ly_}"
        for i in inst:
            col = i["total"]
            ys = sorted(y for y in col if col[y] is not None)
            if len(ys) < 3:
                continue
            y0, y1 = ys[0], ys[-1]
            v0, v1 = col[y0], col[y1]
            nm = i["name"]
            iid = "inst_gov" if "ממשלה" in nm else ("inst_police" if "משטרה" in nm else "inst_" + str(len(insights)))
            if "ממשלה" in nm:
                kpis["gov"] = {"value": v1, "display": fmt.pct_of(v1, 1),
                               "tone": "danger" if min(ys, key=lambda y: (col[y], -y)) == y1 else "warn"}
                labels["gov_kpi"] = f"נותנים אמון בממשלה, {y1}"
            diff = v1 - v0
            if abs(diff) < 3:
                continue
            move = "ירד" if diff < 0 else "עלה"
            trust = nm if nm.startswith("אמון ב") else "אמון ב" + nm
            txt = f"שיעור הנותנים {trust} {move} מ-{fmt.pct_of(v0, 1)} ב-{y0} ל-{fmt.pct_of(v1, 1)} ב-{y1}"
            if diff < 0 and min(ys, key=lambda y: (col[y], -y)) == y1:
                txt += ", השיעור הנמוך ביותר בסדרה"
            elif diff > 0 and max(ys, key=lambda y: (col[y], -y)) == y1:
                txt += ", השיעור הגבוה ביותר בסדרה"
            add(iid, txt + ".")

    if not flags:
        raise ValueError("no known chart found in the newest edition")

    # ── insights: the card holds the strongest; the rest are callouts ────
    def prio(i):
        try:
            return PRIORITY.index(i["id"])
        except ValueError:
            return len(PRIORITY)

    ordered = sorted(insights, key=lambda i: (prio(i), i["id"]))
    top = ordered[:MAX_TOP]
    sec_of = {"overview_lead": "overview", "inst_gov": "inst", "inst_police": "inst",
              "trust_gap": "trust", "jobs_unemp": "jobs"}
    callouts = {}
    for i in ordered[MAX_TOP:]:
        sec = sec_of.get(i["id"], i["id"] if not i["id"].startswith("inst_") else "inst")
        callouts.setdefault(sec, []).append(i["text_he"])

    # ── text ─────────────────────────────────────────────────────────────
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    all_years = set()
    for c in charts.values():
        if isinstance(c, dict) and "x" in c:
            all_years.update(int(x[:4]) for x in c["x"])
    y_min, y_max = (min(all_years), max(all_years)) if all_years else (None, None)

    lede = ("האם הרווחה של היום נשמרת גם לדורות הבאים? מדדי הקיימות של הלשכה המרכזית לסטטיסטיקה "
            "(הלמ\"ס) עוקבים אחרי מצב ההון של ישראל: הון כלכלי, טבעי, אנושי, חברתי ותרבותי.")
    if ov:
        lede += (f" בהודעה האחרונה{(' (נתוני ' + rep_year + ')') if rep_year else ''} נבחנו "
                 f"{fmt.int_he(ov['total']['n'])} מדדים: "
                 f"ב-{fmt.pct_of(ov['total']['imp'] / ov['total']['n'] * 100, 1)} מהם חלה מגמת שיפור "
                 f"וב-{fmt.pct_of(ov['total']['worse'] / ov['total']['n'] * 100, 1)} מגמת הרעה.")
    elif y_min:
        lede += f" הסדרות בעמוד מכסות את השנים {y_min}-{y_max}."
    labels["lede"] = lede

    if ov:
        t = ov["total"]
        summary = (f"מדדי הקיימות (הון) של הלמ\"ס{(' לשנת ' + rep_year) if rep_year else ''}: "
                   f"מתוך {fmt.int_he(t['n'])} מדדים, ב-{fmt.pct_of(t['imp'] / t['n'] * 100, 1)} "
                   f"מגמת שיפור וב-{fmt.pct_of(t['worse'] / t['n'] * 100, 1)} מגמת הרעה. "
                   f"אנרגיה מתחדשת, זיהום אוויר, מגוון ביולוגי, בריאות, השכלה ואמון.")
        desc = (f"מדדי הקיימות של ישראל: ב-{fmt.pct_of(t['imp'] / t['n'] * 100, 1)} מתוך "
                f"{fmt.int_he(t['n'])} מדדים שיפור, ב-{fmt.pct_of(t['worse'] / t['n'] * 100, 1)} הרעה. "
                f"אנרגיה מתחדשת, אוויר, מגוון ביולוגי, אמון ועוד.")
    else:
        summary = ("מדדי הקיימות (הון) של הלמ\"ס: הון כלכלי, טבעי, אנושי, חברתי ותרבותי לאורך זמן, "
                   "מאנרגיה מתחדשת ואיכות האוויר ועד אמון במוסדות.")
        desc = ("מדדי הקיימות של ישראל לפי הלמ\"ס: הון כלכלי, טבעי, אנושי, חברתי ותרבותי, "
                "מאנרגיה מתחדשת ואיכות אוויר ועד אמון ובריאות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{y_min}/{y_max}" if y_min else None,
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדדי קיימות בישראל: הון טבעי, אנושי וחברתי | הלמ\"ס",
                "description": desc,
                "name": "מדדי קיימות (הון) בישראל",
                "alternate_names": ["מדדי קיימות בישראל", "מדדי הון בישראל",
                                    "מדדי פיתוח בר-קיימא", "קיימות ישראל למ\"ס"],
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
