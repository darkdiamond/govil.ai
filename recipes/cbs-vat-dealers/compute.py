"""Openings and closings of VAT dealers' files (CBS half-yearly release).

The release is a set of tables ("לוח 1א" … "לוח 8ב": openings and closings,
total and by branch, original / seasonally adjusted / trend data) and, since
2026, chart-data sheets ("תרשים 1" … "תרשים 5"). CBS RENUMBERS the files
between editions (the 2025 editions put table 1א in t1, the 2026 ones in
t1a and the charts in t9..t13), so every table is identified by its title,
never by its stem. A table whose title is found but whose header labels are
gone raises; a missing table drops its section (only the two total tables
are required).
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\.?\s*-\s*")
HEB = re.compile("[א-ת]")
CODES = re.compile(r"\([^)]*\)")
HALF = re.compile(r"מחצית\s+(הראשונה|השנייה|השניה)\s+של\s+((?:19|20)\d\d)")
STEM = re.compile(r"t(\d+)([a-z]?)")
MONTHS = fmt.MONTHS_HE


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows[:12]:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    if t.startswith("לוח"):
        if "בכלל ענפי הכלכלה" in t:
            return "total_open" if "פתיחות" in t else "total_close" if "סגירות" in t else None
        if "בענף" in t or "בענפי" in t:
            return "branch_open" if "פתיחות" in t else "branch_close" if "סגירות" in t else None
        return None
    if t.startswith("תרשים"):
        if "אחוז השינוי" in t and "מחצית" in t:
            return "half"
        if "מנוכי עונתיות ומגמה" in t:
            return "trend"
    return None


def _ed_key(r):
    """(date, year, number) of an edition: "99/2026" sorts before "100/2026"."""
    m = re.search(r"(\d+)/(\d{4})", str(r[1]))
    return (str(r[0]), int(m.group(2)), int(m.group(1))) if m else (str(r[0]), 0, 0)


def _tables(frames):
    """{kind: [(title, rows), ...]} over every non-empty table input, in stem
    order (t1, t1a, t1b, t2, ...)."""
    out = {}
    names = []
    for n in frames:
        m = STEM.fullmatch(n)
        if m:
            names.append((int(m.group(1)), m.group(2), n))
    # only the newest edition's files: an older edition's file under a stem
    # the newest edition no longer uses must not shadow its renumbered twin
    keyed = {}
    for _, _, n in sorted(names):
        df = frames[n]
        if not df.empty:
            keyed[n] = max(_ed_key(r) for r in df[["RELEASE_DATE", "RELEASE_NO"]].drop_duplicates()
                           .itertuples(index=False))
    newest = max(keyed.values(), default=None)
    for _, _, n in sorted(names):
        if keyed.get(n) != newest:
            continue
        rows = cbs.grid(frames[n], n)
        t = _title(rows)
        k = _kind(t)
        if k:
            out.setdefault(k, []).append((t, rows))
    return out


# ── parsing ──────────────────────────────────────────────────────────────


def _clean_name(s):
    s = CODES.sub(" ", s).replace("סך הכל", " ")
    s = re.sub(r"\s+", " ", s).strip(" ,;-")
    return s


def _series_table(rows, name):
    """Groups of one "לוח" table: [{name, cat, annual{y: v}, monthly{(y, m):
    (orig, sa, trend)}, pct{(y, m): v}}]. The original-data column is found
    by its English label, the seasonally adjusted and trend columns sit just
    before it (checked)."""
    h = None
    for i, r in enumerate(rows):
        if any(c.lower() == "original" for c in r):
            h = i
            break
    if h is None:
        raise ValueError(f"{name}: header label 'Original' not found")
    hdr = rows[h]
    nxt = rows[h + 1] if h + 1 < len(rows) else []
    origs = [j for j, c in enumerate(hdr) if c.lower() == "original"]
    # a "trend percent change" column (the total tables) sits before trend
    pct_col = next((j for j, c in enumerate(hdr) if "percent" in c.lower()), None)
    # category row ("סדר G", "היי-טק") and the Hebrew "מגמה" header row
    cat_row = None
    for i in range(h - 1, -1, -1):
        if any(c.startswith("סדר") or c == "היי-טק" for c in rows[i]):
            cat_row = i
            break
    heb_row = next((i for i in range((cat_row or 0), h) if "מגמה" in rows[i]), h)
    groups = []
    for j in origs:
        if cbs.cell(hdr, j - 1).lower() != "seasonally":
            raise ValueError(f"{name}: no 'Seasonally adjusted' column before column {j}")
        if "trend" not in (cbs.cell(hdr, j - 2).lower(), cbs.cell(nxt, j - 2).lower()):
            raise ValueError(f"{name}: no 'Trend' column before column {j}")
        cat = ""
        pieces = []
        if cat_row is not None:
            cat = next((c for c in rows[cat_row][max(0, j - 2):j + 1]
                        if c.startswith("סדר") or c == "היי-טק"), "")
            for i in range(cat_row + 1, heb_row):
                for c in rows[i][max(0, j - 2):j + 1]:
                    if HEB.search(c):
                        pieces.append(c)
        groups.append({"col": j, "cat": cat, "name": _clean_name(" ".join(pieces)) or "סך הכל",
                       "monthly": {}, "pct": {}})
    for i, year, month, end in cbs.periods(rows, h + 1, len(rows)):
        if end is not None:
            continue
        r = rows[i]
        for g in groups:
            j = g["col"]
            o = cbs.val(r, j)
            # a year row is a total in some editions and a monthly average in
            # others: annual totals are summed from the twelve months instead
            if month is not None and o is not None:
                g["monthly"][(year, month)] = (o, cbs.val(r, j - 1), cbs.val(r, j - 2))
                if pct_col is not None:
                    p = cbs.val(r, pct_col)
                    if p is not None:
                        g["pct"][(year, month)] = p
    for g in groups:
        mo = g["monthly"]
        g["annual"] = {y: sum(mo[(y, m)][0] for m in range(1, 13))
                       for y in sorted({y for y, _ in mo})
                       if all((y, m) in mo for m in range(1, 13))}
    # sub-branches: a group with no category of its own (under a "סך הכל"
    # group), or a "ענף ראשי" whose letter also stands alone in the table
    letters = {c.split()[1] for c in (g["cat"] for g in groups)
               if c.startswith("סדר") and "ענף ראשי" not in c and len(c.split()) > 1}
    for g in groups:
        c = g["cat"]
        g["hitech"] = c == "היי-טק" or "היי-טק" in g["name"]
        main_div = "ענף ראשי" in c and len(c.split()) > 1 and c.split()[1] in letters
        g["sub"] = cat_row is not None and (not c or main_div)
    return groups


def _half(title, rows, name):
    """Chart 1: % change (seasonally adjusted) by branch, half-year vs the
    same half a year earlier. Returns (period text, [(label, open, close)])."""
    h = cbs.row_with(rows, 'פתיחות תיקי עוסקי מע"מ', name=name, contains=True)
    oc = cbs.col_after(rows[h], "פתיחות", contains=True)
    cc = cbs.col_after(rows[h], "סגירות", contains=True)
    body = rows[h + 1:]
    lc = cbs.best_col(body, lambda v: bool(HEB.search(v)), exclude={oc, cc})
    items = []
    for r in body:
        lab = cbs.cell(r, lc)
        o, c = cbs.val(r, oc), cbs.val(r, cc)
        if lab and HEB.search(lab) and o is not None and c is not None:
            items.append((lab, o, c))
    hm = HALF.findall(title)
    return hm, items


def _trend(rows, name):
    """Chart 2-5: monthly seasonally adjusted and trend series since 2011.
    Returns (label, {(y, m): (open_sa, open_tr, close_sa, close_tr)})."""
    h = cbs.row_with(rows, "פתיחות - נתונים מנוכי עונתיות", name=name)
    r = rows[h]
    cols = [cbs.col_after(r, lab) for lab in ("פתיחות - נתונים מנוכי עונתיות", "פתיחות - נתוני מגמה",
                                              "סגירות - נתונים מנוכי עונתיות", "סגירות - נתוני מגמה")]
    label = ""
    for i in range(h - 1, -1, -1):
        cand = [c for c in rows[i] if HEB.search(c) and not TITLE.match(c)]
        if cand:
            label = cand[0]
            break
        if any(TITLE.match(c) for c in rows[i]):
            break
    label = re.sub(r"\s*-\s*סה\"כ\s*$", "", CODES.sub("", label)).strip()
    out = {}
    for i, y, m in cbs.monthly_runs(rows, h + 1, len(rows), cols[0]):
        out[(y, m)] = tuple(cbs.val(rows[i], c) for c in cols)
    return label, out


# ── helpers ──────────────────────────────────────────────────────────────


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _r(v, d=0):
    return None if v is None else (round(v) if d == 0 else round(v, d))


def _sp(v, d=1):
    """A signed percent from a fraction, U+2212 minus."""
    return fmt.signed_pct(v, d)


def _mon(y, m):
    return f"{MONTHS[m - 1]} {y}"


def _word(c, up="עלייה", down="ירידה"):
    return up if c > 0 else down


def _chg_in(c, what):
    """'עלייה של 3.1% ב<what>', or 'ללא שינוי ב<what>' when it rounds to zero."""
    if abs(c) < 0.0005:
        return f"ללא שינוי ב{what}"
    return f"{_word(c)} של {fmt.pct(abs(c))} ב{what}"


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _full_years(monthly):
    years = sorted({y for y, _ in monthly})
    return [y for y in years if all((y, m) in monthly for m in range(1, 13))]


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    for k in ("total_open", "total_close"):
        if k not in tabs:
            raise ValueError(f"{k}: total table (לוח 1א/1ב, בכלל ענפי הכלכלה) not found in any input")
    t_open = _series_table(tabs["total_open"][0][1], "total_open")[0]
    t_close = _series_table(tabs["total_close"][0][1], "total_close")[0]
    years = sorted(set(t_open["annual"]) & set(t_close["annual"]))
    if not years:
        raise ValueError("total tables: no annual rows")
    ly = years[-1]

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── annual totals ────────────────────────────────────────────────────
    o_ly, c_ly = t_open["annual"][ly], t_close["annual"][ly]
    net = o_ly - c_ly
    kpis["open"] = {"value": int(o_ly), "display": fmt.int_he(o_ly), "tone": "brand"}
    kpis["close"] = {"value": int(c_ly), "display": fmt.int_he(c_ly), "tone": "brand"}
    kpis["net"] = {"value": int(net), "display": ("+" if net > 0 else "−" if net < 0 else "") + fmt.int_he(abs(net)),
                   "tone": "ok" if net > 0 else "danger" if net < 0 else "brand"}
    labels["open_kpi"] = f"תיקי עוסקי מע\"מ שנפתחו ב-{ly}"
    labels["close_kpi"] = f"תיקים שנסגרו ב-{ly}"
    labels["net_kpi"] = f"פתיחות פחות סגירות, {ly}"
    charts["annual"] = {"x": [str(y) for y in years],
                        "open": [int(t_open["annual"][y]) for y in years],
                        "close": [int(t_close["annual"][y]) for y in years],
                        "net": [int(t_open["annual"][y] - t_close["annual"][y]) for y in years]}
    tables["annual"] = [[str(y), fmt.int_he(t_open["annual"][y]), fmt.int_he(t_close["annual"][y]),
                         fmt.int_he(t_open["annual"][y] - t_close["annual"][y]),
                         fmt.num_he(t_open["annual"][y] / t_close["annual"][y], 2)]
                        for y in reversed(years)]
    labels["annual_note"] = (f"מספר התיקים שנפתחו ונסגרו בכל שנה, {years[0]} עד {ly} (נתונים מקוריים), "
                             f"וההפרש ביניהם.")
    labels["annual_aria"] = f"פתיחות וסגירות של תיקי עוסקי מע\"מ לפי שנה, {years[0]} עד {ly}"
    if ly - 1 in t_open["annual"] and ly - 1 in t_close["annual"]:
        co = _chg(o_ly, t_open["annual"][ly - 1])
        cc = _chg(c_ly, t_close["annual"][ly - 1])
        kpis["open_chg"] = {"value": round(co * 100, 1), "display": _sp(co),
                            "tone": "ok" if co >= 0.02 else "danger" if co <= -0.02 else "brand"}
        labels["open_chg_kpi"] = f"שינוי בפתיחות לעומת {ly - 1}"
        add("annual", f"ב-{ly} נפתחו {fmt.int_he(o_ly)} תיקי עוסקי מע\"מ ונסגרו {fmt.int_he(c_ly)}: "
                      f"{_chg_in(co, 'פתיחות')} ו{_chg_in(cc, 'סגירות')} "
                      f"לעומת {ly - 1}. על כל תיק שנסגר נפתחו {fmt.num_he(o_ly / c_ly, 2)}.")
    if len(years) >= 3:
        lo = min(years, key=lambda y: (t_open["annual"][y], y))
        if lo != ly and lo != years[0]:
            add("low", f"השפל בפתיחות בשנים המוצגות היה ב-{lo}, עם {fmt.int_he(t_open['annual'][lo])} "
                       f"תיקים בלבד. מאז הפתיחות {'עלו' if o_ly > t_open['annual'][lo] else 'ירדו'} "
                       f"ב-{fmt.pct(abs(_chg(o_ly, t_open['annual'][lo])))}.")

    # ── seasonality (original monthly data) ──────────────────────────────
    fy = [y for y in _full_years(t_open["monthly"]) if y in _full_years(t_close["monthly"])]
    flags["season"] = len(fy) >= 2
    if flags["season"]:
        so = [_avg([t_open["monthly"][(y, m)][0] for y in fy]) for m in range(1, 13)]
        sc = [_avg([t_close["monthly"][(y, m)][0] for y in fy]) for m in range(1, 13)]
        charts["season"] = {"x": list(MONTHS), "open": [_r(v) for v in so], "close": [_r(v) for v in sc]}
        tables["season"] = [[MONTHS[k], fmt.int_he(so[k]), fmt.int_he(sc[k])] for k in range(12)]
        labels["season_note"] = (f"ממוצע הפתיחות והסגירות בכל חודש בשנים {fy[0]} עד {fy[-1]} "
                                 f"(נתונים מקוריים, לפני ניכוי עונתיות).")
        labels["season_aria"] = f"ממוצע חודשי של פתיחות וסגירות תיקי עוסקי מע\"מ, {fy[0]} עד {fy[-1]}"
        mo = max(range(12), key=lambda k: (so[k], -k))
        mc = max(range(12), key=lambda k: (sc[k], -k))
        ao, ac = sum(so) / 12, sum(sc) / 12
        if so[mo] / ao >= 1.3 and sc[mc] / ac >= 1.3:
            add("season", f"החודש העמוס בפתיחות הוא {MONTHS[mo]}: בממוצע {fmt.int_he(so[mo])} פתיחות, "
                          f"פי {fmt.num_he(so[mo] / ao, 1)} מחודש ממוצע. הסגירות מתרכזות ב{MONTHS[mc]} "
                          f"({fmt.int_he(sc[mc])} בממוצע, פי {fmt.num_he(sc[mc] / ac, 1)}). "
                          f"שנים {fy[0]} עד {fy[-1]}, נתונים מקוריים.")

    # ── the first half of a year not yet complete (a January edition) ────
    both_m = set(t_open["monthly"]) & set(t_close["monthly"])
    lm = max(both_m, default=None)
    if lm and lm[1] == 6 and lm[0] > ly:
        cur = [(lm[0], m) for m in range(1, 7)]
        prv = [(lm[0] - 1, m) for m in range(1, 7)]
        if all(k in both_m for k in cur + prv):
            so_c = sum(t_open["monthly"][k][0] for k in cur)
            sc_c = sum(t_close["monthly"][k][0] for k in cur)
            co = _chg(so_c, sum(t_open["monthly"][k][0] for k in prv))
            cc = _chg(sc_c, sum(t_close["monthly"][k][0] for k in prv))
            add("h1", f"במחצית הראשונה של {lm[0]} נפתחו {fmt.int_he(so_c)} תיקים ונסגרו {fmt.int_he(sc_c)} "
                      f"(נתונים מקוריים): {_chg_in(co, 'פתיחות')} ו{_chg_in(cc, 'סגירות')} "
                      f"לעומת המחצית "
                      f"הראשונה של {lm[0] - 1}.")

    # ── trend momentum (latest month of the total tables) ────────────────
    if t_open["pct"] and t_close["pct"]:
        lm = max(set(t_open["pct"]) & set(t_close["pct"]), default=None)
        if lm:
            po, pc = t_open["pct"][lm], t_close["pct"][lm]
            def dirw(p, up, down):
                return up if p >= 0.1 else down if p <= -0.1 else "יציבה"
            add("momentum", f"ב{_mon(*lm)} מגמת הפתיחות {dirw(po, 'עולה', 'יורדת')} "
                            f"({fmt.signed_pct(po / 100, 2)} לעומת החודש הקודם) ומגמת הסגירות "
                            f"{dirw(pc, 'עולה', 'יורדת')} ({fmt.signed_pct(pc / 100, 2)}).")

    # ── long-run trend since 2011 ────────────────────────────────────────
    trends = []
    for t, rows in tabs.get("trend", []):
        lab, ser = _trend(rows, "trend")
        if ser:
            trends.append((t, lab, ser))
    total_tr = next((x for x in trends if "בכלל ענפי הכלכלה" in x[0]), None)
    flags["trend"] = total_tr is not None and len(total_tr[2]) >= 24
    if flags["trend"]:
        ser = total_tr[2]
        keys = sorted(ser)
        charts["trend"] = {"x": [f"{y}-{m:02d}" for y, m in keys],
                           "open_sa": [_r(ser[k][0]) for k in keys], "open_tr": [_r(ser[k][1]) for k in keys],
                           "close_sa": [_r(ser[k][2]) for k in keys], "close_tr": [_r(ser[k][3]) for k in keys]}
        tyears = sorted({y for y, _ in keys})
        tables["trend"] = [[str(y), fmt.int_he(_avg([ser[k][0] for k in keys if k[0] == y])),
                            fmt.int_he(_avg([ser[k][2] for k in keys if k[0] == y]))]
                           for y in reversed(tyears)]
        labels["trend_note"] = (f"פתיחות וסגירות בכל חודש מאז {_mon(*keys[0])}, מנוכות עונתיות (הקו הדק) "
                                f"ונתוני מגמה (הקו העבה). הטבלה מציגה ממוצע חודשי מנוכה עונתיות לכל שנה.")
        labels["trend_aria"] = f"פתיחות וסגירות חודשיות מנוכות עונתיות ומגמה, {_mon(*keys[0])} עד {_mon(*keys[-1])}"
        sa_keys = [k for k in keys if ser[k][0] is not None]
        lo = min(sa_keys, key=lambda k: (ser[k][0], k))
        hi = max(sa_keys, key=lambda k: (ser[k][0], [-x for x in k]))
        add("extremes", f"מאז {keys[0][0]} השפל בפתיחות (מנוכה עונתיות) היה ב{_mon(*lo)}, "
                        f"{fmt.int_he(ser[lo][0])} פתיחות בחודש, והשיא ב{_mon(*hi)}, "
                        f"{fmt.int_he(ser[hi][0])} פתיחות.")
        f0 = [y for y in tyears if sum(1 for k in keys if k[0] == y) == 12]
        if len(f0) >= 5:
            a, b = f0[0], f0[-1]
            ao = _avg([ser[k][0] for k in keys if k[0] == a])
            bo = _avg([ser[k][0] for k in keys if k[0] == b])
            ac = _avg([ser[k][2] for k in keys if k[0] == a])
            bc = _avg([ser[k][2] for k in keys if k[0] == b])
            add("longrun", f"בטווח הארוך: ב-{b} נפתחו בממוצע {fmt.int_he(bo)} תיקים בחודש לעומת "
                           f"{fmt.int_he(ao)} ב-{a} ({_sp(_chg(bo, ao))}), והסגירות "
                           f"{'עלו' if bc > ac else 'ירדו'} מ-{fmt.int_he(ac)} ל-{fmt.int_he(bc)} בחודש "
                           f"(נתונים מנוכי עונתיות).")

    # ── branches (annual original data) ──────────────────────────────────
    bo, bc = {}, {}
    for t, rows in tabs.get("branch_open", []):
        for g in _series_table(rows, "branch_open"):
            bo.setdefault(g["name"], g)
    for t, rows in tabs.get("branch_close", []):
        for g in _series_table(rows, "branch_close"):
            bc.setdefault(g["name"], g)
    both = [n for n in bo if n in bc and ly in bo[n]["annual"] and ly in bc[n]["annual"]]
    top = [n for n in both if not bo[n]["sub"] and not bo[n]["hitech"]]
    subs = [n for n in both if bo[n]["sub"] or bo[n]["hitech"]]
    flags["branches"] = len(top) >= 4
    if flags["branches"]:
        order = sorted(top, key=lambda n: (-bo[n]["annual"][ly], n))
        charts["branches"] = {"names": order, "open": [int(bo[n]["annual"][ly]) for n in order],
                              "close": [int(bc[n]["annual"][ly]) for n in order]}
        tables["branches"] = [[n, fmt.int_he(bo[n]["annual"][ly]), fmt.int_he(bc[n]["annual"][ly]),
                               fmt.int_he(bo[n]["annual"][ly] - bc[n]["annual"][ly])] for n in order]
        labels["branches_note"] = (f"תיקים שנפתחו ונסגרו ב-{ly} בכל ענף ראשי (נתונים מקוריים), מהענף "
                                   f"עם הכי הרבה פתיחות.")
        labels["branches_aria"] = f"פתיחות וסגירות של תיקי עוסקי מע\"מ לפי ענף, {ly}"
        lead = order[0]
        sh = bo[lead]["annual"][ly] / o_ly
        if sh >= 0.1:
            add("lead", f"הענף עם הכי הרבה פתיחות ב-{ly} הוא {lead}: {fmt.int_he(bo[lead]['annual'][ly])} "
                        f"תיקים, {fmt.pct(sh)} מכלל הפתיחות. אחריו {order[1]} "
                        f"({fmt.int_he(bo[order[1]]['annual'][ly])}).")
        # net by branch, with the opening/closing ratio
        nord = sorted(top, key=lambda n: (-(bo[n]["annual"][ly] - bc[n]["annual"][ly]), n))
        charts["net"] = {"names": nord, "net": [int(bo[n]["annual"][ly] - bc[n]["annual"][ly]) for n in nord]}
        tables["net"] = [[n, fmt.int_he(bo[n]["annual"][ly] - bc[n]["annual"][ly]),
                          fmt.num_he(bo[n]["annual"][ly] / bc[n]["annual"][ly], 2)] for n in nord]
        labels["net_note"] = (f"כמה תיקים נוספו בכל ענף ב-{ly}: פתיחות פחות סגירות, ובטבלה גם מספר "
                              f"הפתיחות על כל סגירה.")
        labels["net_aria"] = f"פתיחות פחות סגירות לפי ענף, {ly}"
        neg = [n for n in top if bo[n]["annual"][ly] < bc[n]["annual"][ly]]
        ratio = {n: bo[n]["annual"][ly] / bc[n]["annual"][ly] for n in top}
        best = max(top, key=lambda n: (ratio[n], n))
        if neg:
            add("net", f"ב-{ly} נסגרו יותר תיקים משנפתחו "
                       f"{'בענף אחד' if len(neg) == 1 else f'ב-{len(neg)} ענפים'}: "
                       f"{fmt.join_he(chr(34) + n + chr(34) for n in sorted(neg))}. היחס הגבוה ביותר "
                       f"בין פתיחות לסגירות היה ב{best}: {fmt.num_he(ratio[best], 2)} פתיחות על כל סגירה.")
        else:
            add("net", f"ב-{ly} בכל הענפים הראשיים נפתחו יותר תיקים משנסגרו. היחס הגבוה ביותר היה "
                       f"ב{best}: {fmt.num_he(ratio[best], 2)} פתיחות על כל סגירה.")
        # growth vs the previous year
        if ly - 1 in t_open["annual"]:
            grow = [(n, _chg(bo[n]["annual"][ly], bo[n]["annual"].get(ly - 1))) for n in top]
            grow = [(n, g) for n, g in grow if g is not None and bo[n]["annual"][ly] >= 500]
            if len(grow) >= 3:
                g1 = max(grow, key=lambda x: (x[1], x[0]))
                g0 = min(grow, key=lambda x: (x[1], x[0]))
                if g1[1] >= 0.05:
                    add("growth", f"הזינוק הגדול בפתיחות ב-{ly} היה ב{g1[0]}: {_sp(g1[1])} לעומת {ly - 1}. "
                                  f"בקצה השני {g0[0]}, עם {_sp(g0[1])}.")
    flags["subs"] = len(subs) >= 2
    if flags["subs"]:
        sord = sorted(subs, key=lambda n: (-bo[n]["annual"][ly], n))
        has_prev = all(ly - 1 in bo[n]["annual"] for n in sord)
        charts["subs"] = {"names": sord, "open": [int(bo[n]["annual"][ly]) for n in sord],
                          "close": [int(bc[n]["annual"][ly]) for n in sord]}
        tables["subs"] = [[n, fmt.int_he(bo[n]["annual"][ly]), fmt.int_he(bc[n]["annual"][ly])]
                          + ([_sp(_chg(bo[n]["annual"][ly], bo[n]["annual"][ly - 1]))] if has_prev else [])
                          for n in sord]
        labels["subs_cols"] = ["תת-ענף", "פתיחות", "סגירות"] + ([f"שינוי בפתיחות מ-{ly - 1}"] if has_prev else [])
        labels["subs_note"] = (f"פתיחות וסגירות ב-{ly} בתת-ענפים שהלמ\"ס מפרטת (חלק מהענפים הראשיים), "
                               f"ובענפי ההיי-טק, שחוצים כמה ענפים.")
        labels["subs_aria"] = f"פתיחות וסגירות בתת-ענפים נבחרים ובהיי-טק, {ly}"
        ht = next((n for n in sord if bo[n]["hitech"]), None)
        if ht:
            r = bo[ht]["annual"][ly] / bc[ht]["annual"][ly]
            txt = (f"בהיי-טק נפתחו ב-{ly} {fmt.int_he(bo[ht]['annual'][ly])} תיקים ונסגרו "
                   f"{fmt.int_he(bc[ht]['annual'][ly])}, {fmt.num_he(r, 2)} פתיחות על כל סגירה")
            pv = bo[ht]["annual"].get(ly - 1)
            if pv:
                c = _chg(bo[ht]["annual"][ly], pv)
                txt += f", ו{_chg_in(c, 'פתיחות')} לעומת {ly - 1}"
            add("hitech", txt + ".")

    # ── half-year change by branch (chart 1 of the release) ──────────────
    half = None
    if "half" in tabs:
        t, rows = tabs["half"][0]
        hm, items = _half(t, rows, "half")
        tot = next((x for x in items if x[0] in ('סה"כ', "סך הכל", "סה''כ")), None)
        br = [x for x in items if x is not tot]
        if len(br) >= 4 and len(hm) >= 2:
            half = (hm, br, tot)
    flags["half"] = half is not None
    if half:
        hm, br, tot = half
        h_txt = f"מחצית {hm[0][0].replace('השניה', 'השנייה')} של {hm[0][1]}"
        h_base = f"המחצית {hm[1][0].replace('השניה', 'השנייה')} של {hm[1][1]}"
        hord = sorted(br, key=lambda x: (-x[1], x[0]))
        charts["half"] = {"names": [x[0] for x in hord], "open": [x[1] for x in hord], "close": [x[2] for x in hord]}
        tables["half"] = [[x[0], _sp(x[1] / 100), _sp(x[2] / 100)] for x in hord]
        labels["half_note"] = (f"אחוז השינוי בפתיחות ובסגירות במחצית {hm[0][0].replace('השניה', 'השנייה')} של {hm[0][1]} לעומת {h_base}, לפי ענף "
                               f"(נתונים מנוכי עונתיות, כפי שפרסמה הלמ\"ס; חלק מהשורות הן תת-ענפים).")
        labels["half_aria"] = f"אחוז השינוי בפתיחות ובסגירות לפי ענף, ה{h_txt} לעומת {h_base}"
        labels["half_period"] = h_txt
        if tot:
            kpis["half_open"] = {"value": tot[1], "display": _sp(tot[1] / 100),
                                 "tone": "ok" if tot[1] >= 2 else "danger" if tot[1] <= -2 else "brand"}
            labels["half_open_kpi"] = f"שינוי בפתיחות ב{h_txt} (מנוכה עונתיות)"
            up_o = sum(1 for x in br if x[1] > 0)
            dn_c = sum(1 for x in br if x[2] < 0)
            add("half", f"ב{h_txt} {'עלו' if tot[1] > 0 else 'ירדו'} הפתיחות ב-{fmt.pct_of(abs(tot[1]))} "
                        f"והסגירות {'עלו' if tot[2] > 0 else 'ירדו'} ב-{fmt.pct_of(abs(tot[2]))} לעומת {h_base} "
                        f"(מנוכה עונתיות). הפתיחות עלו ב-{up_o} מתוך {len(br)} הענפים, והסגירות "
                        f"ירדו ב-{dn_c} מהם.")
        mx = hord[0]
        if mx[1] >= 10:
            add("half_lead", f"העלייה החדה ביותר בפתיחות ב{h_txt} הייתה ב{mx[0]}: {_sp(mx[1] / 100)}.")

    # ── selected branches since 2011 (charts 3-5 of the release) ─────────
    multi = [x for x in trends if x is not total_tr and len(x[2]) >= 24]
    flags["multi"] = len(multi) >= 1
    if flags["multi"]:
        charts["multi"] = []
        tables["multi"] = []
        for k, (t, lab, ser) in enumerate(multi[:4]):
            keys = sorted(ser)
            charts["multi"].append({"id": f"chart-multi-{k}", "name": lab,
                                    "x": [f"{y}-{m:02d}" for y, m in keys],
                                    "open": [_r(ser[x][1]) for x in keys],
                                    "close": [_r(ser[x][3]) for x in keys]})
            fyr = [y for y in sorted({y for y, _ in keys}) if sum(1 for x in keys if x[0] == y) == 12]
            if len(fyr) >= 2:
                a, b = fyr[0], fyr[-1]
                tables["multi"].append([lab,
                                        fmt.int_he(_avg([ser[x][1] for x in keys if x[0] == a])),
                                        fmt.int_he(_avg([ser[x][1] for x in keys if x[0] == b])),
                                        fmt.int_he(_avg([ser[x][3] for x in keys if x[0] == a])),
                                        fmt.int_he(_avg([ser[x][3] for x in keys if x[0] == b]))])
                labels["multi_a"], labels["multi_b"] = str(a), str(b)
        flags["multi_table"] = bool(tables["multi"])
        labels["multi_note"] = ("נתוני המגמה של הפתיחות והסגירות בכל חודש בענפים שהלמ\"ס מפרטת לאורך זמן. "
                                "הטבלה מציגה ממוצע חודשי של המגמה בשנה המלאה הראשונה והאחרונה.")

    # ── release card + text ──────────────────────────────────────────────
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["lede"] = (f"כמה עסקים נפתחים וכמה נסגרים בישראל, לפי תיקי עוסקי המע\"מ (עוסקים מורשים ופטורים) "
                      f"שנפתחו ונסגרו ברשות המסים. הנתונים מתוך ההודעה החצי שנתית של הלשכה המרכזית "
                      f"לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. ב-{ly} נפתחו "
                      f"{fmt.int_he(o_ly)} תיקים ונסגרו {fmt.int_he(c_ly)}.")
    summary = (f"פתיחות וסגירות עסקים בישראל לפי תיקי עוסקי מע\"מ (הלמ\"ס): ב-{ly} נפתחו {fmt.int_he(o_ly)} "
               f"תיקים ונסגרו {fmt.int_he(c_ly)}, לפי ענף ולאורך זמן.")
    desc = (f"כמה עסקים נפתחו ונסגרו בישראל: {fmt.int_he(o_ly)} תיקי עוסקי מע\"מ נפתחו ו-{fmt.int_he(c_ly)} "
            f"נסגרו ב-{ly}. נתוני הלמ\"ס לפי ענף ולפי חודש.")
    first = min([years[0]] + ([int(charts["trend"]["x"][0][:4])] if flags["trend"] else []))
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "פתיחת וסגירת עסקים בישראל: תיקי עוסקי מע\"מ | הלמ\"ס",
                "description": desc,
                "name": "פתיחות וסגירות של תיקי עוסקי מע\"מ",
                "alternate_names": ["פתיחת עסקים בישראל", "סגירת עסקים בישראל",
                                    "פתיחת תיק עוסק מורשה", "עסקים שנסגרו בישראל",
                                    "פתיחות וסגירות עסקים"],
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
