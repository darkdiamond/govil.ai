"""החשבונות הלאומיים לשנת YYYY: CBS's yearly national-accounts release.

Two editions a year: the first annual estimate (February, "החשבונות
הלאומיים לשנת 2025") and the second (March, "...: אומדן שני"). The newest
wins. They number their tables differently (the main GDP table is t6 in the
first estimate and t1 in the second; productivity t10 vs t5), and the first
estimate also carries quarterly versions of some tables. So every stem is an
optional input and each table is found by its TITLE text:

  main      הוצאה על התוצר המקומי הגולמי, במחירי שוק   GDP and uses, yearly
  prod      תוצר מקומי גולמי, במחירי שוק לשעת עבודה    GDP, work-hours, 1995-
  industry  תוצר ... לפי ענף כלכלי                    GDP by industry, 2006-
  labour    חלק התמורות למועסקים ולהון                 income shares, 1995-
  public    הוצאה לצריכה ציבורית                       defence vs civilian
  intl      תוצר מקומי גולמי לנפש ... מדינה            per-capita growth, OECD

A quarterly version of a table (rows by quarter) is skipped in favour of the
yearly one. `main` is required; every other table drops its section when
missing, and raises when found with its header labels gone.

Growth rates are computed from the chained (constant-price) levels, which is
exactly how CBS defines the published quantity change (chained ratio), so a
truncated table still yields a consistent rate.
"""
import re

import pandas as pd
from govlib import cbs, fmt

HEB = re.compile("[א-ת]")
LATIN = re.compile(r"[A-Za-z][A-Za-z.\-' ]*")
QUARTER = re.compile(r"^[IVX]+-[IVX]+$")
NOTE = re.compile(r"\([A-Z]\)")
YEAR_IN = re.compile(r"(?:19|20)\d\d")

# Industry short names by CBS category code; an unknown code keeps the
# sheet's label up to its first ";".
INDUSTRY_SHORT = {
    "A": "חקלאות",
    "B - C": "תעשייה וכרייה",
    "F": "בינוי",
    "D - E": "חשמל, מים וביוב",
    "G, I": "מסחר, אירוח ואוכל",
    "H": "תחבורה ואחסנה",
    "J": "מידע ותקשורת",
    "K - N": "פיננסים, נדל\"ן ושירותים עסקיים",
    "P - T": "חינוך, בריאות ושירותים אחרים",
}

USES = (  # key, label
    ("priv", "צריכה פרטית"),
    ("pub", "צריכה ציבורית"),
    ("fixed", "השקעה בנכסים קבועים"),
    ("exp", "יצוא"),
    ("imp", "יבוא"),
)
# verb forms per use: (grew, fell); יצוא/יבוא are masculine
USE_VERBS = {"priv": ("צמחה", "ירדה"), "pub": ("צמחה", "ירדה"), "fixed": ("צמחה", "ירדה"),
             "exp": ("צמח", "ירד"), "imp": ("צמח", "ירד")}


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    """Text of the title rows: every Hebrew cell of the first 10 rows."""
    return " ".join(c for r in rows[:10] for c in r if HEB.search(c))


def _quarterly(rows):
    return any(QUARTER.match(c) for r in rows for c in r[:6])


def _kind(t, rows):
    # Table titles proper ("לוח 5.- ..."): a chart sheet's column headers
    # can repeat a table's subject ("הוצאה לצריכה ציבורית").
    lt = " ".join(c for r in rows[:10] for c in r if c.startswith("לוח"))
    if "הוצאה על התוצר המקומי הגולמי, במחירי שוק" in lt:
        return "main"
    if "תוצר מקומי גולמי, במחירי שוק לשעת עבודה" in lt:
        return "prod"
    if "לפי ענף כלכלי" in t and "תוצר מקומי גולמי" in lt:
        return "industry"
    if "חלק התמורות למועסקים" in lt:
        return "labour"
    if "הוצאה לצריכה ציבורית" in lt:
        return "public"
    if "לנפש" in t and any(c == "מדינה" for r in rows[:12] for c in r):
        return "intl"
    return None


def _tables(frames):
    """{kind: rows}: the first yearly match by stem number. source.json
    stacks one edition (history_releases 1), so every table is the newest
    edition's."""
    out = {}

    def order(n):
        m = re.fullmatch(r"t(\d+)([a-z]?)", n)
        return (int(m.group(1)), m.group(2))

    names = sorted((n for n in frames if re.fullmatch(r"t\d+[a-z]?", n)), key=order)
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        k = _kind(_title(rows), rows)
        if k and k not in out and not _quarterly(rows):
            out[k] = rows
    return out


# ── small helpers ────────────────────────────────────────────────────────


def _r(v, d=1):
    return None if v is None else round(v, d)


def _chg(a, b):
    """Percent change from b to a, or None."""
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1) * 100


def _header_cols(rows, start, stop):
    """{column: Hebrew header text}, the Hebrew cells of rows[start:stop]
    joined top to bottom, footnote letters removed."""
    out = {}
    for r in rows[start:stop]:
        for j, c in enumerate(r):
            if HEB.search(c):
                out.setdefault(j, []).append(NOTE.sub("", c).strip())
    return {j: " ".join(v) for j, v in out.items()}


def _find_col(cols, pred, label, name):
    for j in sorted(cols):
        if pred(cols[j]):
            return j
    raise ValueError(f"{name}: column {label!r} not found")


def _sections(rows, start, markers):
    """{section: {year: row}} for whole-year rows after `start`. A row
    whose text holds a marker opens that section (first marker that
    matches); a year row before any marker is ignored."""
    ycol = cbs.best_col(rows[start:], lambda v: bool(cbs.YEAR.match(v)))
    out, sec = {}, None
    for r in rows[start:]:
        txt = " ".join(r)
        y = cbs.cell(r, ycol) if ycol is not None else ""
        if not cbs.YEAR.match(y):
            for key, words in markers:
                if any(w in txt for w in words):
                    sec = key
                    break
            continue
        if sec is not None and not any(QUARTER.match(c) for c in r[:6]):
            out.setdefault(sec, {})[int(y)] = r
    return out


def _sign_word(v, up="עלייה", down="ירידה"):
    return up if v >= 0 else down


def _p(v):
    return fmt.pct_of(abs(v))


# ── parsers ──────────────────────────────────────────────────────────────


def _parse_main(rows):
    h = cbs.row_with(rows, "הוצאה על התוצר המקומי הגולמי, במחירי שוק", name="main", contains=True)
    s = cbs.row_with(rows, "במחירים שוטפים", h + 1, name="main", contains=True)
    cols = _header_cols(rows, h + 1, s)
    c = {
        "gdp": _find_col(cols, lambda t: t == "תוצר מקומי גולמי", "תוצר מקומי גולמי", "main"),
        "pc": _find_col(cols, lambda t: "לנפש" in t and "תוצר" in t, "לנפש", "main"),
        "imp": _find_col(cols, lambda t: "יבוא סחורות" in t, "יבוא סחורות", "main"),
        "exp": _find_col(cols, lambda t: "יצוא סחורות" in t, "יצוא סחורות", "main"),
        "fixed": _find_col(cols, lambda t: "נכסים קבועים" in t, "נכסים קבועים", "main"),
        "pub": _find_col(cols, lambda t: "לצריכה ציבורית" in t, "לצריכה ציבורית", "main"),
        "priv": _find_col(cols, lambda t: "הוצאה לצריכה פרטית" in t, "הוצאה לצריכה פרטית", "main"),
    }
    secs = _sections(rows, s, [("cur", ("במחירים שוטפים",)), ("chn", ("משורשרים",)),
                              ("other", ("שינוי",))])
    cur, chn = secs.get("cur", {}), secs.get("chn", {})
    if not cur:
        raise ValueError("main: no current-price rows")

    def series(sec, key):
        return {y: cbs.val(r, c[key]) for y, r in sec.items()}

    return {k: {"cur": series(cur, k), "chn": series(chn, k)} for k in c}


def _parse_prod(rows):
    h = cbs.row_with(rows, "תוצר מקומי גולמי לשעת עבודה", name="prod", contains=True)
    hr = rows[h]
    per_hour = [j for j, v in enumerate(hr) if "לשעת עבודה" in v]
    gdp = [j for j, v in enumerate(hr) if v == "תוצר מקומי גולמי"]
    hours = [j for j, v in enumerate(hr) if "שעות עבודה" in v]
    if len(per_hour) < 2 or not gdp or not hours:
        raise ValueError("prod: header labels changed")
    secs = _sections(rows, h + 1, [("cur", ("במחירים שוטפים",)), ("chn", ("משורשרים",)),
                                   ("other", ("השינוי", "ממוצע"))])
    chn = secs.get("chn", {})
    years = sorted(chn)
    return {
        "years": years,
        "gdp": [cbs.val(chn[y], gdp[0]) for y in years],
        "hours": [cbs.val(chn[y], hours[0]) for y in years],
        "ph_total": [cbs.val(chn[y], per_hour[0]) for y in years],
        "ph_bus": [cbs.val(chn[y], per_hour[1]) for y in years],
    }


def _parse_industry(rows):
    h = cbs.row_with(rows, "סך הכל", name="industry")
    k = cbs.row_with(rows, "סדר", h, name="industry")
    names = {j: NOTE.sub("", v).strip() for j, v in enumerate(rows[h]) if HEB.search(v)}
    codes = {j: v for j, v in enumerate(rows[k]) if re.search(r"[A-Z]", v) and v != "Category"}
    total = cbs.col_after(rows[h], "סך הכל")
    cols, labels = [], []
    for j in sorted(names):
        n = names[j]
        if n.startswith(("שירותי דיור", "שירותים ציבוריים")):
            cols.append(j)
            labels.append(n.split("(")[0].strip() if n.startswith("שירותי דיור")
                          else "שירותים ציבוריים ומלכ\"רים")
        elif j in codes and n != "עסקים":
            cols.append(j)
            labels.append(INDUSTRY_SHORT.get(codes[j], n.split(";")[0].strip()))
    if len(cols) < 5:
        raise ValueError("industry: industry columns not found")
    secs = _sections(rows, k + 1, [("cur", ("במחירים שוטפים",)), ("pct", ("אחוזים",)),
                                   ("real", ("במחירי 20",)), ("other", ("שינוי",))])
    cur, real = secs.get("cur", {}), secs.get("real", {})
    if not cur:
        raise ValueError("industry: no current-price rows")
    return {"cols": cols, "labels": labels, "total": total, "cur": cur, "real": real}


def _parse_labour(rows):
    yr = None
    for i, r in enumerate(rows):
        if sum(1 for c in r if cbs.YEAR.match(c)) >= 5:
            yr = i
            break
    if yr is None:
        raise ValueError("labour: year header row not found")
    ycols = {j: int(c) for j, c in enumerate(rows[yr]) if cbs.YEAR.match(c)}

    def line(label):
        # Data rows (low in a short sheet): a missing one empties its series.
        for r in rows[yr + 1:]:
            if any(label in c for c in r):
                return {y: cbs.val(r, j) for j, y in ycols.items()}
        return {}

    comp = line("תמורה למועסקים")
    surplus = line("עודף תפעולי")
    taxes = line("מסים נטו על ייצור ועל יבוא")
    years = sorted(y for y in ycols.values() if comp.get(y) is not None)
    return {"years": years, "comp": [comp[y] for y in years],
            "surplus": [surplus.get(y) for y in years], "taxes": [taxes.get(y) for y in years]}


def _parse_public(rows):
    h = cbs.row_with(rows, "צריכה ביטחונית", name="public")
    s = cbs.row_with(rows, "במחירים שוטפים", h, name="public", contains=True)
    hdr = _header_cols(rows, h, s)
    tot = [j for j in sorted(hdr) if hdr[j].endswith("סך הכל")]
    grand = _find_col(hdr, lambda t: "סך כולל" in t, "סך כולל", "public")
    dcol = cbs.col_after(rows[h], "צריכה ביטחונית")
    ccol = cbs.col_after(rows[h], "צריכה אזרחית")
    if len(tot) < 2:
        raise ValueError("public: total columns not found")
    # The defence total is the "סך הכל" column on the defence side of the
    # header: the group label sits at one edge of its columns, so take the
    # total nearer to it.
    d_tot, c_tot = (tot[0], tot[1]) if abs(tot[0] - dcol) < abs(tot[0] - ccol) else (tot[1], tot[0])
    secs = _sections(rows, s, [("cur", ("במחירים שוטפים",)), ("chn", ("משורשרים",)),
                               ("other", ("שינוי",))])
    cur = secs.get("cur", {})
    years = sorted(cur)
    return {"years": years,
            "def": [cbs.val(cur[y], d_tot) for y in years],
            "civ": [cbs.val(cur[y], c_tot) for y in years],
            "all": [cbs.val(cur[y], grand) for y in years]}


def _parse_intl(rows):
    t = " ".join(c for r in rows[:10] for c in r if "לנפש" in c)
    m = YEAR_IN.search(t)
    year = int(m.group(0)) if m else None
    h = cbs.row_with(rows, "מדינה", name="intl")
    out = {}
    for r in rows[h + 1:]:
        nums = [cbs.num(c) for c in r if cbs.num(c) is not None]
        texts = [c for c in r if c and cbs.num(c) is None]
        if len(nums) != 1 or not texts:
            continue
        txt = texts[0]
        if txt.startswith(("שינוי", "Quantity")):
            continue
        name = LATIN.sub("", txt).strip() if HEB.search(txt) else txt.strip()
        if name and name not in out:
            out[name] = nums[0]
    return {"year": year, "items": sorted(out.items(), key=lambda kv: (kv[1], kv[0]))}


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "main" not in tabs:
        raise ValueError("main GDP table (הוצאה על התוצר המקומי הגולמי, במחירי שוק) not found")
    main = _parse_main(tabs["main"])
    edition = "אומדן שני" if "אומדן שני" in str(rel["TITLE"]) else "אומדן ראשון"

    gdp_cur, gdp_chn = main["gdp"]["cur"], main["gdp"]["chn"]
    years = sorted(y for y in gdp_cur if gdp_cur[y] is not None)
    ly = years[-1]
    fy = years[0]
    real_years = sorted(y for y in gdp_chn if gdp_chn[y] is not None)

    def growth(key, y):
        s = main[key]["chn"]
        return _chg(s.get(y), s.get(y - 1))

    g_years = [y for y in real_years if y - 1 in gdp_chn and gdp_chn.get(y - 1) is not None]
    gl = g_years[-1] if g_years else None  # latest year with a real growth rate

    insights, labels, charts, tables, kpis = [], {}, {}, {}, {}
    flags = dict.fromkeys(("uses", "mix", "long", "prod", "industry", "ind_growth", "defence",
                           "labour", "intl"), False)

    def add(i, text):
        if text:
            insights.append({"id": i, "text_he": text})

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis["gdp"] = {"value": round(gdp_cur[ly] / 1000, 1), "display": fmt.int_he(gdp_cur[ly] / 1000),
                   "tone": "brand"}
    labels["gdp_kpi"] = f"התוצר המקומי הגולמי ב-{ly} (מיליארדי ₪, מחירים שוטפים)"
    pc_cur = main["pc"]["cur"].get(ly)
    if pc_cur is not None:
        kpis["pc"] = {"value": round(pc_cur), "display": fmt.int_he(pc_cur), "tone": "brand"}
        labels["pc_kpi"] = f"תוצר לנפש ב-{ly} (₪, מחירים שוטפים)"
    g = growth("gdp", gl) if gl else None
    if g is not None:
        tone = "ok" if g >= 2 else ("warn" if g >= 0 else "danger")
        kpis["growth"] = {"value": round(g, 1), "display": fmt.signed_pct(g / 100), "tone": tone}
        labels["growth_kpi"] = f"צמיחת התוצר ב-{gl} (שינוי כמותי)"
    gpc = growth("pc", gl) if gl else None
    if gpc is not None:
        tone = "ok" if gpc >= 1 else ("warn" if gpc >= 0 else "danger")
        kpis["pc_growth"] = {"value": round(gpc, 1), "display": fmt.signed_pct(gpc / 100), "tone": tone}
        labels["pc_growth_kpi"] = f"שינוי בתוצר לנפש ב-{gl} (שינוי כמותי)"

    # ── insight: growth ──────────────────────────────────────────────────
    if g is not None:
        prev = growth("gdp", gl - 1)
        if g >= 0:
            txt = f"התוצר המקומי הגולמי צמח ב-{gl} ב-{_p(g)} במונחים ריאליים"
        else:
            txt = f"התוצר המקומי הגולמי התכווץ ב-{gl} ב-{_p(g)} במונחים ריאליים"
        if prev is not None:
            if abs(g - prev) < 0.3:
                txt += f", קצב דומה לזה של {gl - 1} ({'צמיחה' if prev >= 0 else 'ירידה'} של {_p(prev)})"
            elif g > prev:
                txt += (f", האצה לעומת {gl - 1} ({'צמיחה' if prev >= 0 else 'ירידה'} של {_p(prev)})")
            else:
                txt += (f", האטה לעומת {gl - 1} ({'צמיחה' if prev >= 0 else 'ירידה'} של {_p(prev)})")
        add("growth", txt + ".")
    if g is not None and gpc is not None and g - gpc >= 0.3:
        if gpc >= 0:
            txt = (f"התוצר לנפש גדל פחות מהתוצר כולו: עלייה של {_p(gpc)} ב-{gl} "
                   f"לעומת צמיחה של {_p(g)}")
        elif g >= 0:
            txt = f"התוצר לנפש ירד ב-{gl} ב-{_p(gpc)}, אף שהתוצר כולו צמח ב-{_p(g)}"
        else:
            txt = (f"התוצר לנפש ירד ב-{gl} יותר מהתוצר כולו: ירידה של {_p(gpc)} "
                   f"לעומת ירידה של {_p(g)}")
        add("per_capita", txt + ". הפער משקף את גידול האוכלוסייה.")

    # ── uses: growth by component and share of GDP ───────────────────────
    use_years = [y for y in g_years if all(growth(k, y) is not None for k, _ in USES)]
    if use_years:
        flags["uses"] = True
        keys = ["gdp"] + [k for k, _ in USES]
        names = ["תוצר מקומי גולמי"] + [n for _, n in USES]
        charts["uses"] = {"years": [str(y) for y in use_years], "names": names,
                          "series": [[_r(growth(k, y)) for y in use_years] for k in keys]}
        tables["uses"] = [[str(y)] + [fmt.pct_of(growth(k, y)) if growth(k, y) is not None else "–"
                                      for k in keys] for y in use_years]
        labels["uses_cols"] = ["שנה"] + names
        y = use_years[-1]
        rates = sorted(((growth(k, y), n, k) for k, n in USES if k != "imp"), key=lambda t: (-t[0], t[1]))
        top, low = rates[0], rates[-1]

        def _verb(r):
            up, down = USE_VERBS[r[2]]
            return up if r[0] >= 0 else down
        txt = (f"מבין השימושים בתוצר, {top[1]} {_verb(top)} ב-{y} "
               f"ב-{_p(top[0])}, הקצב {'הגבוה' if top[0] >= 0 else 'המתון'} ביותר")
        if low[1] != top[1]:
            txt += (f", ו{low[1]} {_verb(low)} ב-{_p(low[0])}")
        add("uses", txt + ".")
        labels["uses_note"] = (f"השינוי הכמותי (במחירים קבועים) בתוצר ובכל אחד מהשימושים בו, "
                               f"{use_years[0]} עד {y}, באחוזים לעומת השנה הקודמת.")
        labels["uses_aria"] = f"צמיחת התוצר ומרכיביו, {use_years[0]} עד {y}"

    share_years = [y for y in years if all(main[k]["cur"].get(y) is not None for k, _ in USES)]
    if share_years:
        flags["mix"] = True
        charts["mix"] = {"years": [str(y) for y in share_years], "names": [n for _, n in USES],
                         "series": [[_r(main[k]["cur"][y] / gdp_cur[y] * 100) for y in share_years]
                                    for k, _ in USES]}
        tables["mix"] = [[str(y)] + [fmt.pct_of(main[k]["cur"][y] / gdp_cur[y] * 100) for k, _ in USES]
                         for y in share_years]
        labels["mix_cols"] = ["שנה"] + [n for _, n in USES]
        labels["mix_note"] = (f"כל שימוש כאחוז מהתוצר המקומי הגולמי, במחירים שוטפים, "
                              f"{share_years[0]} עד {share_years[-1]}. היבוא מקוזז מהתוצר, ולכן סכום "
                              f"השימושים עולה על מאה אחוז.")
        labels["mix_aria"] = f"השימושים בתוצר כאחוז מהתוצר, {share_years[0]} עד {share_years[-1]}"

    # ── long run: real GDP and productivity ──────────────────────────────
    if "prod" in tabs:
        p = _parse_prod(tabs["prod"])
        yrs = [y for y, v in zip(p["years"], p["gdp"], strict=True) if v is not None]
        if len(yrs) >= 5:
            flags["long"] = True
            gdp_by = dict(zip(p["years"], p["gdp"], strict=True))
            gr = [(y, _chg(gdp_by[y], gdp_by.get(y - 1))) for y in yrs[1:]]
            gr = [(y, v) for y, v in gr if v is not None]
            charts["long"] = {"years": [str(y) for y, _ in gr], "growth": [_r(v) for _, v in gr],
                              "level": [_r(gdp_by[y] / 1000) for y, _ in gr]}
            tables["long"] = [[str(y), fmt.num_he(gdp_by[y] / 1000), fmt.pct_of(v)] for y, v in gr]
            labels["long_note"] = (f"התוצר המקומי הגולמי במחירים קבועים (משורשרים, מיליארדי ₪) "
                                   f"והצמיחה הריאלית בכל שנה, {gr[0][0]} עד {gr[-1][0]}.")
            labels["long_aria"] = f"צמיחת התוצר הריאלית, {gr[0][0]} עד {gr[-1][0]}"
            neg = [y for y, v in gr if v < 0]
            first, last = yrs[0], yrs[-1]
            mult = gdp_by[last] / gdp_by[first]
            span = last - first
            avg = (mult ** (1 / span) - 1) * 100
            txt = (f"מאז {first} גדל התוצר הריאלי פי {fmt.num_he(mult)}, צמיחה ממוצעת של "
                   f"{_p(avg)} בשנה")
            if len(neg) == 1:
                txt += f". רק בשנה אחת הוא התכווץ: {neg[0]}"
            elif neg:
                txt += f". הוא התכווץ ב-{len(neg)} שנים: {fmt.join_he(neg)}"
            else:
                txt += ", בלי שנה אחת של התכווצות"
            add("long", txt + ".")

        ph = [(y, t, b) for y, t, b in zip(p["years"], p["ph_total"], p["ph_bus"], strict=True)
              if t is not None]
        if len(ph) >= 5:
            flags["prod"] = True
            charts["prod"] = {"years": [str(y) for y, _, _ in ph], "total": [_r(t) for _, t, _ in ph],
                              "bus": [_r(b) for _, _, b in ph]}
            step = max(1, len(ph) // 15)
            sel = ph[::-1][::step][::-1]
            tables["prod"] = [[str(y), fmt.num_he(t), fmt.num_he(b) if b is not None else "–"]
                              for y, t, b in sel]
            labels["prod_note"] = (f"התוצר לשעת עבודה, בש\"ח במחירים קבועים (משורשרים), בכלל המשק "
                                   f"ובמגזר העסקי, {ph[0][0]} עד {ph[-1][0]}.")
            labels["prod_aria"] = f"פריון העבודה: תוצר לשעת עבודה, {ph[0][0]} עד {ph[-1][0]}"
            labels["prod_table_note"] = ("" if step == 1 else
                                         f"בטבלה מוצגת כל שנה {step} מתוך הסדרה.")
            by = {y: t for y, t, _ in ph}
            ly2 = ph[-1][0]
            if ly2 - 10 in by:
                r10 = ((by[ly2] / by[ly2 - 10]) ** 0.1 - 1) * 100
                hours = dict(zip(p["years"], p["hours"], strict=True))
                txt = (f"התוצר לשעת עבודה בכלל המשק {_sign_word(r10, 'גדל', 'ירד')} בעשור "
                       f"{ly2 - 10}-{ly2} בקצב ממוצע של {_p(r10)} בשנה")
                if hours.get(ly2) and hours.get(ly2 - 10):
                    rh = ((hours[ly2] / hours[ly2 - 10]) ** 0.1 - 1) * 100
                    txt += f", ושעות העבודה {_sign_word(rh, 'גדלו', 'ירדו')} ב-{_p(rh)} בשנה"
                add("prod", txt + ".")

    # ── industries ───────────────────────────────────────────────────────
    if "industry" in tabs:
        ind = _parse_industry(tabs["industry"])
        cur = ind["cur"]
        iyears = sorted(y for y in cur if cbs.val(cur[y], ind["total"]))
        if iyears:
            flags["industry"] = True
            iy, i0 = iyears[-1], iyears[0]

            def share(y, j):
                v, t = cbs.val(cur[y], j), cbs.val(cur[y], ind["total"])
                return None if v is None or not t else v / t * 100

            rows_ = [(ind["labels"][k], share(iy, j), share(i0, j))
                     for k, j in enumerate(ind["cols"])]
            rows_ = [r for r in rows_ if r[1] is not None]
            rows_.sort(key=lambda r: (-r[1], r[0]))
            charts["industry"] = {"names": [r[0] for r in rows_], "last": [_r(r[1]) for r in rows_],
                                  "first": [_r(r[2]) for r in rows_],
                                  "last_year": str(iy), "first_year": str(i0)}
            tables["industry"] = [[n, fmt.pct_of(a), fmt.pct_of(b) if b is not None else "–"]
                                  for n, a, b in rows_]
            labels["industry_cols"] = ["ענף", f"{iy}", f"{i0}"]
            labels["industry_note"] = (f"חלקו של כל ענף בתוצר המקומי הגולמי, במחירים שוטפים: {iy} "
                                       f"לעומת {i0}. את השאר משלימים המסים נטו על מוצרים.")
            labels["industry_aria"] = f"התוצר לפי ענף כלכלי, {iy} לעומת {i0}"
            moves = [(a - b, n, a, b) for n, a, b in rows_ if b is not None]
            if moves:
                up = max(moves, key=lambda m: (m[0], m[1]))
                if up[0] >= 1:
                    add("industry", f"ענף {up[1]} הגדיל את חלקו בתוצר יותר מכל ענף אחר: "
                                    f"{_p(up[3])} ב-{i0} ו-{_p(up[2])} ב-{iy}.")
            real = ind["real"]
            if iy in real and iy - 1 in real:
                rg = []
                for k, j in enumerate(ind["cols"]):
                    v = _chg(cbs.val(real[iy], j), cbs.val(real[iy - 1], j))
                    if v is not None:
                        rg.append((ind["labels"][k], v))
                rg.sort(key=lambda r: (-r[1], r[0]))
                if len(rg) >= 3:
                    flags["ind_growth"] = True
                    charts["ind_growth"] = {"names": [n for n, _ in rg], "values": [_r(v) for _, v in rg]}
                    tables["ind_growth"] = [[n, fmt.pct_of(v)] for n, v in rg]
                    labels["ind_growth_note"] = (f"השינוי הריאלי (במחירי 2020) בתוצר של כל ענף ב-{iy} "
                                                 f"לעומת {iy - 1}, באחוזים.")
                    labels["ind_growth_aria"] = f"צמיחה ריאלית לפי ענף, {iy}"
                    labels["ind_growth_head"] = f"מי צמח ב-{iy}: שינוי ריאלי לפי ענף"
                    hi, lo = rg[0], rg[-1]
                    txt = (f"ב-{iy} {'צמח' if hi[1] >= 0 else 'ירד'} התוצר של ענף {hi[0]} ב-{_p(hi[1])}, "
                           f"יותר מכל ענף אחר")
                    if lo[1] < 0:
                        txt += f", ותוצר ענף {lo[0]} ירד ב-{_p(lo[1])}"
                    add("ind_growth", txt + ".")

    # ── public consumption: defence vs civilian ──────────────────────────
    if "public" in tabs:
        pb = _parse_public(tabs["public"])
        pts = [(y, d, c) for y, d, c in zip(pb["years"], pb["def"], pb["civ"], strict=True)
               if d is not None and c is not None and gdp_cur.get(y)]
        if pts:
            flags["defence"] = True
            charts["defence"] = {"years": [str(y) for y, _, _ in pts],
                                 "def": [_r(d / 1000) for _, d, _ in pts],
                                 "civ": [_r(c / 1000) for _, _, c in pts],
                                 "share": [_r(d / gdp_cur[y] * 100) for y, d, _ in pts]}
            tables["defence"] = [[str(y), fmt.num_he(d / 1000), fmt.num_he(c / 1000),
                                  fmt.pct_of(d / gdp_cur[y] * 100)] for y, d, c in pts]
            labels["defence_note"] = (f"ההוצאה לצריכה ציבורית מתחלקת לצריכה ביטחונית ולצריכה אזרחית "
                                      f"(מיליארדי ₪, מחירים שוטפים), והצריכה הביטחונית כאחוז מהתוצר, "
                                      f"{pts[0][0]} עד {pts[-1][0]}.")
            labels["defence_aria"] = f"צריכה ביטחונית ואזרחית, {pts[0][0]} עד {pts[-1][0]}"
            y1, d1, _ = pts[-1]
            s1 = d1 / gdp_cur[y1] * 100
            kpis["defence"] = {"value": round(s1, 1), "display": fmt.pct_of(s1),
                               "tone": "warn" if len(pts) > 1 and s1 - pts[0][1] / gdp_cur[pts[0][0]] * 100 >= 1
                               else "info"}
            labels["defence_kpi"] = f"הצריכה הביטחונית כאחוז מהתוצר ב-{y1}"
            if len(pts) > 1:
                y0, d0, _ = pts[0]
                s0 = d0 / gdp_cur[y0] * 100
                if abs(s1 - s0) >= 0.5:
                    add("defence", f"הצריכה הביטחונית {'עלתה' if s1 > s0 else 'ירדה'} מ-{_p(s0)} מהתוצר "
                                   f"ב-{y0} ל-{_p(s1)} ב-{y1}: {fmt.num_he(d1 / 1000)} מיליארד ₪ לעומת "
                                   f"{fmt.num_he(d0 / 1000)} מיליארד ₪.")

    # ── labour share ─────────────────────────────────────────────────────
    if "labour" in tabs:
        lb = _parse_labour(tabs["labour"])
        if len(lb["years"]) >= 3:
            flags["labour"] = True
            charts["labour"] = {"years": [str(y) for y in lb["years"]], "comp": [_r(v) for v in lb["comp"]],
                                "surplus": [_r(v) for v in lb["surplus"]],
                                "taxes": [_r(v) for v in lb["taxes"]]}
            step = max(1, len(lb["years"]) // 15)
            idx = list(range(len(lb["years"])))[::-1][::step][::-1]
            tables["labour"] = [[str(lb["years"][i]), fmt.pct_of(lb["comp"][i]),
                                 fmt.pct_of(lb["surplus"][i]) if lb["surplus"][i] is not None else "–",
                                 fmt.pct_of(lb["taxes"][i]) if lb["taxes"][i] is not None else "–"]
                                for i in idx]
            labels["labour_note"] = (f"חלוקת התוצר של המגזר העסקי בין התמורה למועסקים (שכר ושווי עבודת "
                                     f"עצמאים), העודף התפעולי (תשואה להון) והמסים נטו, באחוזים, "
                                     f"{lb['years'][0]} עד {lb['years'][-1]}.")
            labels["labour_aria"] = f"חלק העבודה וההון בתוצר העסקי, {lb['years'][0]} עד {lb['years'][-1]}"
            labels["labour_table_note"] = ("" if step == 1 else f"בטבלה מוצגת כל שנה {step} מתוך הסדרה.")
            last = lb["comp"][-1]
            hi_i = max(range(len(lb["comp"])), key=lambda i: (lb["comp"][i], lb["years"][i]))
            mean = sum(lb["comp"]) / len(lb["comp"])
            if hi_i != len(lb["comp"]) - 1 and lb["comp"][hi_i] - last >= 1:
                add("labour", f"חלקם של המועסקים בתוצר העסקי עמד ב-{lb['years'][-1]} על {_p(last)}, "
                              f"לעומת {_p(lb['comp'][hi_i])} בשיא של {lb['years'][hi_i]} וממוצע של "
                              f"{_p(mean)} מאז {lb['years'][0]}.")

    # ── international comparison ─────────────────────────────────────────
    if "intl" in tabs:
        it = _parse_intl(tabs["intl"])
        items = it["items"]
        if len(items) >= 3:
            flags["intl"] = True
            charts["intl"] = {"names": [n for n, _ in items], "values": [_r(v, 2) for _, v in items]}
            tables["intl"] = [[n, fmt.pct_of(v)] for n, v in sorted(items, key=lambda kv: (-kv[1], kv[0]))]
            yr = it["year"]
            labels["intl_note"] = ("השינוי הכמותי בתוצר לנפש" + (f" ב-{yr}" if yr else "")
                                   + " לעומת השנה הקודמת, באחוזים: ישראל, ממוצע OECD ומדינות נבחרות.")
            labels["intl_aria"] = "צמיחת התוצר לנפש: ישראל מול מדינות OECD"
            d = dict(items)
            isr = d.get("ישראל")
            oecd = d.get("OECD")
            countries = [(n, v) for n, v in items if n != "OECD"]
            if isr is not None:
                above = sum(1 for n, v in countries if v > isr)
                txt = (f"בהשוואה בין-לאומית, התוצר לנפש בישראל {_sign_word(isr, 'עלה', 'ירד')}"
                       + (f" ב-{yr}" if yr else "") + f" ב-{_p(isr)}")
                if oecd is not None:
                    if abs(isr - oecd) < 0.05:
                        txt += f", כמו ממוצע OECD ({_p(oecd)})"
                    else:
                        txt += (f", {'יותר' if isr > oecd else 'פחות'} מממוצע OECD ({_p(oecd)})")
                txt += f". {above} מתוך {len(countries) - 1} המדינות האחרות בתרשים צמחו מהר יותר."
                add("intl", txt)

    # ── table + labels for the headline year table ───────────────────────
    tables["annual"] = []
    for y in years:
        tables["annual"].append([
            str(y), fmt.num_he(gdp_cur[y] / 1000),
            fmt.int_he(main["pc"]["cur"][y]) if main["pc"]["cur"].get(y) is not None else "–",
            fmt.pct_of(growth("gdp", y)) if growth("gdp", y) is not None else "–",
            fmt.pct_of(growth("pc", y)) if growth("pc", y) is not None else "–",
        ])
    charts["annual"] = {"years": [str(y) for y in years],
                        "gdp": [_r(gdp_cur[y] / 1000) for y in years],
                        "pc": [_r(main["pc"]["cur"].get(y), 0) for y in years],
                        "growth": [_r(growth("gdp", y)) for y in years],
                        "pc_growth": [_r(growth("pc", y)) for y in years]}
    labels["annual_note"] = (f"התוצר המקומי הגולמי (מיליארדי ₪) והתוצר לנפש (₪) במחירים שוטפים, "
                             f"והשינוי הכמותי בהם, {fy} עד {ly}.")
    labels["annual_aria"] = f"התוצר והתוצר לנפש, {fy} עד {ly}"

    release = {"title": str(rel["TITLE"]), "url": str(rel["PAGE_URL"]),
               "pdf": str(rel["REPORT_PDF_URL"] or ""), "headline": str(rel["HEADLINE"] or ""),
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["edition"] = (f"העמוד מבוסס על {edition} של החשבונות הלאומיים לשנת {ly}. האומדן השני, "
                         f"שמתפרסם כחודש אחרי הראשון, מעדכן את הנתונים, ושנים קודמות מתעדכנות גם הן.")

    growth_txt = (f"צמיחה ריאלית של {_p(g)}" if g is not None and g >= 0
                  else (f"התכווצות ריאלית של {_p(g)}" if g is not None else ""))
    labels["lede"] = (f"התוצר המקומי הגולמי של ישראל, הצמיחה, התוצר לנפש והשימושים בתוצר בכל שנה, "
                      f"מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על החשבונות הלאומיים. "
                      f"ב-{ly} הסתכם התוצר ב-{fmt.int_he(gdp_cur[ly] / 1000)} מיליארד ₪"
                      + (f", {growth_txt}" if growth_txt else "")
                      + (f", והתוצר לנפש ב-{fmt.int_he(pc_cur)} ₪" if pc_cur is not None else "") + ".")

    # The page's other sections, named only when this edition has them.
    topics = [t for k, t in (("long", "צמיחה לאורך השנים"), ("industry", "ענפים"),
                             ("prod", "פריון"), ("defence", "צריכה ביטחונית"))
              if k in charts]
    topics_txt = fmt.join_he(topics) if topics else ""
    summary = (f"החשבונות הלאומיים של ישראל לפי הלמ\"ס: תוצר של {fmt.int_he(gdp_cur[ly] / 1000)} מיליארד ₪ "
               f"ב-{ly}" + (f", {growth_txt}" if growth_txt else "")
               + (f", תוצר לנפש {fmt.int_he(pc_cur)} ₪" if pc_cur is not None else "")
               + "." + (f" {topics_txt}." if topics_txt else ""))
    desc = (f"התמ\"ג של ישראל ב-{ly}: {fmt.int_he(gdp_cur[ly] / 1000)} מיליארד ₪"
            + (f", צמיחה של {_p(g)}" if g is not None and g >= 0 else
               (f", ירידה של {_p(g)}" if g is not None else ""))
            + (f", תוצר לנפש {fmt.int_he(pc_cur)} ₪" if pc_cur is not None else "")
            + ". צמיחה, ענפים ופריון לפי הלמ\"ס.")
    long_years = charts.get("long", {}).get("years") or [str(fy)]
    t0 = min(int(long_years[0]) - 1 if flags.get("long") else fy, fy)
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{t0}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "התמ\"ג של ישראל: צמיחה ותוצר לנפש שנתי | הלמ\"ס",
                "description": desc,
                "name": "התוצר המקומי הגולמי של ישראל: החשבונות הלאומיים השנתיים",
                "alternate_names": ["החשבונות הלאומיים לשנה", "תמ\"ג ישראל", "צמיחה כלכלית בישראל",
                                    "תוצר לנפש בישראל", "החשבונות הלאומיים של ישראל"],
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
