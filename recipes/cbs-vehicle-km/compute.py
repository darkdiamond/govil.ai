"""נסועה של כלי רכב בישראל: CBS's yearly vehicle-kilometres release.

The release is a set of chart-data sheets ("תרשים N - ..."). Their subjects
and NUMBERS change between editions (the 2024 edition had total km by
vehicle type as t3, the 2026 one has the distribution of private cars by
annual km there), so every table input (t1..t11, three of them spare slots,
all optional) is read with `cbs.grid` and each chart is found by its TITLE:

  shares    סך נסועה שנתית לפי סוג רכב (אחוזים)       % of all km by type
  totaltype סך הנסועה השנתית (מיליון ק"מ) לפי סוג רכב  million km by type
  avgtype   נסועה ממוצעת לרכב ... לפי סוג רכב           thousand km per vehicle
  age       נסועה ממוצעת ... לפי גיל הרכב               private cars by age
  dist      כלי רכב פרטיים ... לפי סך הנסועה השנתית     cars per km band
  distfuel  ... לפי סך הנסועה השנתית וסוג הנעה          % per km band, by fuel
  agefuel   ... לפי קבוצות גיל ... לפי סוג הנעה         avg km, age group x fuel
  owners    ... חדשים ... לפי סוג בעלות                 avg km of new cars, yearly
  oecd      נסועה שנתית לנפש ... OECD                   km per person by country
  index     נסועה שנתית, מצבת כלי הרכב, שטח הכבישים     index series since a base year

Total km, its yearly change and the private-car average are printed only in
CBS's headline (the `releases` resource); they are parsed from it and their
KPIs drop when the wording changes. A title that is found but whose header
labels are gone raises (the layout changed: a human should look). A chart
missing from an edition drops its section. `shares` is required: every
edition so far has it.
"""
import itertools
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile("^(?:תרשים|לוח)\\s*\\d+[א-ת]?\\s*[-\\u2013\\u2014]\\s*")
HEB = re.compile("[א-ת]")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
BAND = re.compile(r"^(\d+)\s*-\s*(\d+)$")
OPEN_BAND = re.compile(r"^(\d+)\s*\+$")
TOTALS = ("סך הכל", "סה\"כ", "סך כלי הרכב", "נסועה - סך הכל")

# Headline: "... הסתכמה בשנת 2025 ב-69.3 מיליארד ק"מ, עלייה של 2.6% לעומת שנת 2024.
# הנסועה השנתית הממוצעת של כלי הרכב הפרטיים עומדת על 14.7 אלף ק"מ"
H_TOTAL = re.compile(r"בשנת\s+((?:19|20)\d\d)\s+ב-?\s*([\d.,]+)\s+מיליארד")
H_CHANGE = re.compile(r"(עלייה|ירידה)\s+של\s+([\d.,]+)%\s+לעומת\s+שנת\s+((?:19|20)\d\d)")
H_PRIVATE = re.compile(r"הממוצעת\s+של\s+כלי\s+הרכב\s+הפרטיים\s+עומדת\s+על\s+([\d.,]+)\s+אלף")

PRIORITY = ("index_growth", "per_vehicle", "shares", "age", "dist", "distfuel", "agefuel",
            "owners", "oecd", "avgtype", "totaltype", "covid")
MAX_TOP = 8


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    if "OECD" in t and "לנפש" in t:
        return "oecd"
    if "שטח הכבישים" in t or ("מצבת" in t and "אורכם" in t):
        return "index"
    if "סוג רכב" in t:
        if "אחוזים" in t:
            return "shares"
        if "מיליון" in t:
            return "totaltype"
        if "ממוצעת" in t:
            return "avgtype"
        return None
    if "סך הנסועה השנתית" in t and "כלי רכב פרטיים" in t:
        return "distfuel" if "הנעה" in t else "dist"
    if "קבוצות גיל" in t and "הנעה" in t:
        return "agefuel"
    if "גיל הרכב" in t and "ממוצעת" in t:
        return "age"
    if "סוג בעלות" in t and "חדשים" in t and "חשמלי" not in t:
        return "owners"
    return None


def _tables(frames):
    """{kind: (title, rows)} over every non-empty table input; of two
    tables of one kind, the lower stem wins."""
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
            out[k] = (TITLE.sub("", t).strip(), rows)
    return out


# ── small helpers ────────────────────────────────────────────────────────


def _year(c):
    return int(c) if cbs.YEAR.match(c) else None


def _title_year(t):
    ys = [int(y) for y in YEAR_IN.findall(t)]
    return max(ys) if ys else None


def _is_total(label):
    return label in TOTALS or label.startswith(("סך ", "סה"))


def _band(label):
    """'0-5' → '0-5', '25+' → '25 ומעלה' (a '+' after digits flips in RTL)."""
    m = OPEN_BAND.match(label)
    if m:
        return f"{m.group(1)} ומעלה"
    m = BAND.match(label)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return label


def _band_lo(label):
    m = OPEN_BAND.match(label) or BAND.match(label)
    return int(m.group(1)) if m else None


def _labelled(rows, start, col=0):
    out = []
    for r in rows[start:]:
        label = cbs.cell(r, col)
        if label and HEB.search(label) and not label.startswith("["):
            out.append((label, r))
    return out


def _vname(label):
    """'כלי רכב פרטי' → 'רכב פרטי', for prose."""
    return "רכב " + label[len("כלי רכב "):] if label.startswith("כלי רכב ") else label


def _owner(label):
    """Ownership label in 'בבעלות …' prose: 'פרטי' → 'פרטית'."""
    return "פרטית" if label == "פרטי" else label


def _band_prose(label):
    m = OPEN_BAND.match(label)
    return f"{m.group(1)} אלף ק\"מ ומעלה" if m else f"{_band(label)} אלף ק\"מ"


def _r1(v):
    return None if v is None else round(v, 1)


def _r2(v):
    return None if v is None else round(v, 2)


def _k(v):
    """Thousand km with one decimal, as text."""
    return fmt.num_he(v, 1)


def _pct100(values):
    vals = [v for v in values if v is not None]
    if vals and max(vals) <= 1.0001 and sum(vals) <= 1.0001 + 1e-9:
        return [None if v is None else v * 100 for v in values]
    return list(values)


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _num(s):
    try:
        return float(s.replace(",", ""))
    except (AttributeError, ValueError):
        return None


# ── table parsers ────────────────────────────────────────────────────────


def _shares(rows):
    """[(type, % of all km)], the total row left out."""
    out = []
    for label, r in _labelled(rows, 0):
        if TITLE.match(label) or _is_total(label) or "סך הכל" in label:
            continue
        v = cbs.val(r, 1)
        if v is not None:
            out.append((label, v))
    return out


def _by_type(rows, name):
    """Rows of vehicle types x year columns (avgtype, totaltype): {year:
    [(type, value)]} and the total row per year, labels found in any column."""
    h = cbs.row_with(rows, "סוג רכב", name=name)
    lcol = rows[h].index("סוג רכב")
    ycols = sorted((_year(c), j) for j, c in enumerate(rows[h]) if _year(c))
    if not ycols:
        raise ValueError(f"{name}: year columns not found")
    out, totals = {}, {}
    for label, r in _labelled(rows, h + 1, lcol):
        for y, j in ycols:
            v = cbs.val(r, j)
            if v is None:
                continue
            if _is_total(label):
                totals[y] = v
            else:
                out.setdefault(y, []).append((label, v))
    return out, totals


def _age(rows):
    h = cbs.row_with(rows, "גיל הרכב", name="age")
    out = []
    for r in rows[h + 1:]:
        label = cbs.cell(r, 0)
        v = cbs.val(r, 1)
        if _band_lo(label) is not None and v is not None:
            out.append((label, v))
    return out


def _dist(rows):
    h = cbs.row_with(rows, "מספר כלי רכב", name="dist")
    ccol = cbs.col_after(rows[h], "מספר כלי רכב", 0)
    out, total = [], None
    for r in rows[h + 1:]:
        label = cbs.cell(r, 0)
        v = cbs.val(r, ccol)
        if v is None:
            continue
        if _band_lo(label) is not None:
            out.append((label, v))
        elif _is_total(label):
            total = v
    return out, total


def _distfuel(rows):
    h = cbs.row_with(rows, "בנזין", name="distfuel")
    fuels = [(j, c) for j, c in enumerate(rows[h]) if j > 0 and c and HEB.search(c)]
    if len(fuels) < 2:
        raise ValueError("distfuel: fuel header columns not found")
    bands = []
    for r in rows[h + 1:]:
        label = cbs.cell(r, 0)
        if _band_lo(label) is None:
            continue
        vals = [cbs.val(r, j) for j, _ in fuels]
        if any(v is not None for v in vals):
            bands.append((label, vals))
    # shares per fuel column (0-100), whatever scale the sheet used
    cols = list(zip(*[v for _, v in bands])) if bands else []
    cols = [_pct100(list(c)) for c in cols]
    return [c for _, c in fuels], [b for b, _ in bands], cols


def _agefuel(rows):
    h = cbs.row_with(rows, "קבוצת גיל", name="agefuel", contains=True)
    fuels = [(j, c) for j, c in enumerate(rows[h]) if j > 0 and c and HEB.search(c)]
    if len(fuels) < 2:
        raise ValueError("agefuel: fuel header columns not found")
    groups = []
    for label, r in _labelled(rows, h + 1):
        vals = [cbs.val(r, j) for j, _ in fuels]
        if any(v is not None for v in vals):
            groups.append((label, vals))
    return [c for _, c in fuels], groups


def _owners(rows):
    h = cbs.row_with(rows, "פרטי", name="owners")
    ycol = cbs.best_col(rows[h + 1:], lambda c: bool(cbs.YEAR.match(c)))
    if ycol is None:
        return [], {}
    cats = [(j, c) for j, c in enumerate(rows[h]) if j != ycol and c and HEB.search(c)]
    out = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, ycol))
        if y is None or y in out:
            continue
        vals = {c: cbs.val(r, j) for j, c in cats}
        if any(v is not None for v in vals.values()):
            out[y] = vals
    return [c for _, c in cats], out


def _oecd(rows):
    h = cbs.row_with(rows, "מדינה", name="oecd")
    vcol = cbs.col_after(rows[h], "לנפש", 0, contains=True)
    out = []
    for label, r in _labelled(rows, h + 1):
        v = cbs.val(r, vcol)
        if v is not None:
            out.append((label, v))
    return out


def _index(rows):
    h = next((i for i, r in enumerate(rows) if "שנה" in r and "נסועה" in r), None)
    if h is None:
        raise ValueError("index: header row (שנה, נסועה) not found")
    cols = {"km": cbs.col_after(rows[h], "נסועה", 0),
            "length": cbs.col_after(rows[h], "אורך כבישים", 0),
            "area": cbs.col_after(rows[h], "שטח כבישים", 0),
            "fleet": cbs.col_after(rows[h], "מצבת כלי רכב", 0)}
    out = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, 0))
        if y is None:
            if out:
                break  # end of the first block (the sheet repeats it below)
            continue
        v = {k: cbs.val(r, j) for k, j in cols.items()}
        if v["km"] is not None:
            out[y] = v
    return out


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "shares" not in tabs:
        raise ValueError("km share by vehicle type chart (סך נסועה שנתית לפי סוג רכב) not found")

    kpis, labels, charts, tables, titles = {}, {}, {}, {}, {}
    flags = dict.fromkeys(("index", "avgtype", "totaltype", "age", "dist", "distfuel", "agefuel",
                           "owners", "oecd"), False)
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    for k, (t, _) in tabs.items():
        titles[k] = t

    # ── headline facts ───────────────────────────────────────────────────
    head = str(rel.get("HEADLINE") or "")
    m_tot = H_TOTAL.search(head)
    m_chg = H_CHANGE.search(head)
    m_prv = H_PRIVATE.search(head)
    total_bn = _num(m_tot.group(2)) if m_tot else None
    data_year = int(m_tot.group(1)) if m_tot else None
    if total_bn is not None:
        kpis["total"] = {"value": total_bn, "display": fmt.num_he(total_bn, 1), "tone": "brand"}
        labels["total_kpi"] = f"מיליארד ק\"מ נסעו כלי הרכב בשנת {data_year}"
    if m_chg and _num(m_chg.group(2)) is not None:
        c = _num(m_chg.group(2)) / 100 * (1 if m_chg.group(1) == "עלייה" else -1)
        kpis["change"] = {"value": round(c * 100, 1), "display": fmt.signed_pct(c),
                          "tone": "info"}
        labels["change_kpi"] = f"שינוי בנסועה הכוללת לעומת {m_chg.group(3)}"
    if m_prv and _num(m_prv.group(1)) is not None:
        pv = _num(m_prv.group(1))
        kpis["private_avg"] = {"value": pv, "display": fmt.num_he(pv, 1), "tone": "brand"}
        labels["private_avg_kpi"] = "אלף ק\"מ בשנה, נסועה ממוצעת לרכב פרטי"

    # ── shares by vehicle type ───────────────────────────────────────────
    s_title, s_rows = tabs["shares"]
    shares = sorted(_shares(s_rows), key=lambda x: (-x[1], x[0]))
    if not shares:
        raise ValueError("shares: no vehicle-type rows")
    s_year = _title_year(s_title)
    data_year = data_year or s_year
    top_name, top_v = shares[0]
    charts["shares"] = {"names": [n for n, _ in shares], "values": [_r2(v) for _, v in shares]}
    tables["shares"] = [[n, fmt.pct_of(v, 1)] for n, v in shares]
    kpis["top_share"] = {"value": round(top_v, 1), "display": fmt.pct_of(top_v, 1), "tone": "brand"}
    top_lbl = _vname(top_name)
    labels["top_share_kpi"] = f"חלקו של {top_lbl} בנסועה הכוללת" + (f", {s_year}" if s_year else "")
    labels["shares_aria"] = "חלוקת הנסועה השנתית לפי סוג רכב, באחוזים"
    trucks = [(n, v) for n, v in shares if n.startswith("משאית")]
    txt = f"חלקו של {top_lbl} בכל הקילומטרים שנסעו בכבישי ישראל"
    if s_year:
        txt += f" בשנת {s_year}"
    txt += f" היה {fmt.pct_of(top_v, 1)}"
    if total_bn is not None and s_year == data_year:
        txt += f" (כ-{fmt.num_he(total_bn * top_v / 100, 1)} מיליארד ק\"מ)"
    if trucks and top_name != trucks[0][0]:
        txt += f", וחלקן של המשאיות {fmt.pct_of(sum(v for _, v in trucks), 1)}"
    add("shares", txt + ".")

    # ── index: km vs fleet vs roads ──────────────────────────────────────
    if "index" in tabs:
        idx = _index(tabs["index"][1])
        iy = sorted(idx)
        if len(iy) >= 2:
            flags["index"] = True
            base = next((y for y in iy if idx[y]["km"] is not None and abs(idx[y]["km"] - 100) < 1e-6), iy[0])
            keys = ("km", "fleet", "length", "area")
            # rebased so the base year is exactly 100 in every series
            reb = {y: {k: (idx[y][k] / idx[base][k] * 100) if idx[y][k] is not None and idx[base][k] else None
                       for k in keys} for y in iy}
            charts["index"] = {"x": [str(y) for y in iy],
                               **{k: [_r1(reb[y][k]) for y in iy] for k in keys}}
            tables["index"] = [[str(y)] + [fmt.num_he(reb[y][k], 1) if reb[y][k] is not None else "–"
                                           for k in keys]
                               for y in reversed(iy)]
            ly = iy[-1]
            labels["index_note"] = (f"ארבעה מדדים באותו בסיס ({base} = 100): הנסועה הכוללת, מספר כלי "
                                    f"הרכב, אורך הכבישים ושטחם. כשקו הנסועה מתחת לקו המצבת, כל רכב נוסע "
                                    f"בממוצע פחות מבשנת הבסיס.")
            labels["index_aria"] = f"נסועה, מצבת כלי רכב ושטח הכבישים, מדד {base} = 100, {base} עד {ly}"
            km_g = reb[ly]["km"] / 100 - 1
            fl_g = reb[ly]["fleet"] / 100 - 1 if reb[ly]["fleet"] else None
            ln_g = reb[ly]["length"] / 100 - 1 if reb[ly]["length"] else None
            if fl_g is not None:
                t = (f"בין {base} ל-{ly} גדלה הנסועה הכוללת ב-{fmt.pct(km_g, 0)}, "
                     f"ומספר כלי הרכב ב-{fmt.pct(fl_g, 0)}")
                if ln_g is not None:
                    t += f". אורך הכבישים גדל באותה תקופה ב-{fmt.pct(ln_g, 0)}"
                add("index_growth", t + ".")
                pv = (1 + km_g) / (1 + fl_g) - 1
                if abs(pv) >= 0.03:
                    add("per_vehicle", (f"כל רכב נוסע היום בממוצע {'פחות' if pv < 0 else 'יותר'} "
                                        f"מבעבר: מאז {base} {'ירדה' if pv < 0 else 'עלתה'} הנסועה "
                                        f"לרכב בכ-{fmt.pct(abs(pv), 0)}, כי מספר כלי הרכב גדל "
                                        f"{'מהר' if pv < 0 else 'לאט'} יותר מהקילומטרים שנסעו."))
            # the sharpest one-year fall, and whether the next year recovered
            drops = [(idx[y]["km"] / idx[p]["km"] - 1, y) for p, y in itertools.pairwise(iy)
                     if idx[p]["km"] and idx[y]["km"]]
            if drops:
                d, dy = min(drops)
                if d <= -0.08 and dy != ly:
                    nxt = idx.get(dy + 1)
                    prev = idx.get(dy - 1)
                    t = f"השנה החריגה בסדרה היא {dy}: הנסועה הכוללת ירדה ב-{fmt.pct(-d, 1)} לעומת השנה הקודמת"
                    if nxt and prev and nxt["km"] >= prev["km"]:
                        t += f", וב-{dy + 1} היא חזרה לרמה של {dy - 1}"
                    add("covid", t + ".")

    # ── average km by vehicle type (older editions) ──────────────────────
    if "avgtype" in tabs:
        by, _ = _by_type(tabs["avgtype"][1], "avgtype")
        if by:
            y = max(by)
            items = sorted(by[y], key=lambda x: (-x[1], x[0]))
            flags["avgtype"] = True
            charts["avgtype"] = {"names": [n for n, _ in items], "values": [_r1(v) for _, v in items]}
            prev = by.get(y - 1, [])
            pmap = dict(prev)
            tables["avgtype"] = [[n, _k(v), _k(pmap[n]) if n in pmap else "–"] for n, v in items]
            labels["avgtype_cols"] = ["סוג רכב", str(y), str(y - 1)]
            labels["avgtype_aria"] = f"נסועה ממוצעת לרכב לפי סוג רכב, {y}"
            if "private_avg" not in kpis:
                pv = next((v for n, v in items if "פרטי" in n), None)
                if pv is not None:
                    kpis["private_avg"] = {"value": round(pv, 1), "display": _k(pv), "tone": "brand"}
                    labels["private_avg_kpi"] = "אלף ק\"מ בשנה, נסועה ממוצעת לרכב פרטי"
            hi, lo = items[0], items[-1]
            if hi[1] > lo[1] * 2:
                add("avgtype", (f"ב-{y} נסע כל רכב מסוג {hi[0]} בממוצע {_k(hi[1])} אלף ק\"מ, "
                                f"פי {fmt.num_he(hi[1] / lo[1], 1)} מרכב מסוג {lo[0]} ({_k(lo[1])} אלף ק\"מ)."))

    # ── total km by vehicle type (older editions) ────────────────────────
    if "totaltype" in tabs:
        by, tot = _by_type(tabs["totaltype"][1], "totaltype")
        if by:
            y = max(by)
            items = sorted(by[y], key=lambda x: (-x[1], x[0]))
            flags["totaltype"] = True
            charts["totaltype"] = {"names": [n for n, _ in items], "values": [round(v) for _, v in items]}
            pmap = dict(by.get(y - 1, []))
            tables["totaltype"] = [[n, fmt.int_he(v), fmt.int_he(pmap[n]) if n in pmap else "–"]
                                   for n, v in items]
            labels["totaltype_cols"] = ["סוג רכב", str(y), str(y - 1)]
            labels["totaltype_aria"] = f"סך הנסועה השנתית במיליוני ק\"מ לפי סוג רכב, {y}"
            if y in tot and (y - 1) in tot:
                c = _chg(tot[y], tot[y - 1])
                add("totaltype", (f"סך הנסועה בשנת {y} היה {fmt.int_he(tot[y])} מיליון ק\"מ, "
                                  f"{'עלייה' if c >= 0 else 'ירידה'} של {fmt.pct(abs(c), 1)} לעומת {y - 1}."))

    # ── average km by vehicle age ────────────────────────────────────────
    if "age" in tabs:
        age = _age(tabs["age"][1])
        age.sort(key=lambda x: (_band_lo(x[0]), x[0]))
        if age:
            flags["age"] = True
            charts["age"] = {"names": [_band(n) for n, _ in age], "values": [_r1(v) for _, v in age]}
            tables["age"] = [[_band(n), _k(v)] for n, v in age]
            labels["age_aria"] = "נסועה שנתית ממוצעת לרכב פרטי לפי גיל הרכב, באלפי ק\"מ"
            if len(age) >= 3:
                y0, yo = age[0], age[-1]
                if yo[1] and y0[1] > yo[1]:
                    add("age", (f"ככל שהרכב מבוגר יותר הוא נוסע פחות: רכב פרטי בגיל {_band(y0[0])} נוסע "
                                f"בממוצע {_k(y0[1])} אלף ק\"מ בשנה, ורכב בגיל {_band(yo[0])} רק "
                                f"{_k(yo[1])} אלף ק\"מ."))

    # ── distribution of private cars by annual km ────────────────────────
    if "dist" in tabs:
        dist, dtotal = _dist(tabs["dist"][1])
        dist.sort(key=lambda x: (_band_lo(x[0]), x[0]))
        if len(dist) >= 2:
            flags["dist"] = True
            s = sum(v for _, v in dist)
            denom = dtotal if dtotal and dtotal >= s * 0.999 else s
            charts["dist"] = {"names": [_band(n) for n, _ in dist],
                              "values": [round(v) for _, v in dist],
                              "shares": [round(v / denom * 100, 1) for _, v in dist]}
            tables["dist"] = [[_band(n), fmt.int_he(v), fmt.pct(v / denom, 1)] for n, v in dist]
            labels["dist_aria"] = "כלי רכב פרטיים לפי הנסועה השנתית שלהם, באלפי ק\"מ"
            if dtotal:
                kpis["cars"] = {"value": round(dtotal), "display": fmt.int_he(dtotal), "tone": "brand"}
                labels["cars_kpi"] = ("כלי רכב פרטיים בבעלות פרטית" if "בבעלות פרטית" in titles["dist"]
                                     else "כלי רכב פרטיים")
            mode = max(dist, key=lambda x: (x[1], -_band_lo(x[0])))
            under10 = sum(v for n, v in dist if (_band_lo(n) or 0) < 10 and BAND.match(n)
                          and int(BAND.match(n).group(2)) <= 10)
            t = (f"הקבוצה הגדולה ביותר נוסעת {_band(mode[0])} אלף ק\"מ בשנה: "
                 f"{fmt.pct(mode[1] / denom, 1)} מכלי הרכב הפרטיים")
            if under10:
                t += f". {fmt.pct(under10 / denom, 0)} נוסעים פחות מ-10 אלף ק\"מ בשנה"
            high = [(n, v) for n, v in dist if OPEN_BAND.match(n)]
            if high:
                t += f", ו-{fmt.pct(high[0][1] / denom, 1)} נוסעים {_band_prose(high[0][0])}"
            add("dist", t + ".")

    # ── distribution by fuel ─────────────────────────────────────────────
    if "distfuel" in tabs:
        fuels, bands, cols = _distfuel(tabs["distfuel"][1])
        if fuels and len(bands) >= 2:
            flags["distfuel"] = True
            charts["distfuel"] = {"fuels": fuels, "bands": [_band(b) for b in bands],
                                  "series": [[_r1(cols[f][k]) for f in range(len(fuels))]
                                             for k in range(len(bands))]}
            tables["distfuel"] = [[f] + [fmt.pct_of(cols[i][k], 1) if cols[i][k] is not None else "–"
                                         for k in range(len(bands))]
                                  for i, f in enumerate(fuels)]
            labels["distfuel_cols"] = ["סוג הנעה"] + [_band(b) for b in bands]
            labels["distfuel_aria"] = "התפלגות כלי הרכב הפרטיים לפי נסועה שנתית, בכל סוג הנעה"
            # share driving 20+ thousand km a year, per fuel
            hi_idx = [k for k, b in enumerate(bands) if (_band_lo(b) or 0) >= 20]
            if hi_idx:
                hi = [(f, sum(cols[i][k] or 0 for k in hi_idx)) for i, f in enumerate(fuels)]
                hi.sort(key=lambda x: (-x[1], x[0]))
                top, bot = hi[0], hi[-1]
                if top[1] >= bot[1] + 10:
                    add("distfuel", (f"{fmt.pct_of(top[1], 0)} מכלי הרכב הפרטיים בהנעת {top[0]} נוסעים "
                                     f"20 אלף ק\"מ בשנה ויותר, לעומת {fmt.pct_of(bot[1], 0)} "
                                     f"מכלי הרכב בהנעת {bot[0]}."))

    # ── avg km by age group x fuel ───────────────────────────────────────
    if "agefuel" in tabs:
        fuels, groups = _agefuel(tabs["agefuel"][1])
        if groups:
            flags["agefuel"] = True
            charts["agefuel"] = {"fuels": fuels, "groups": [g for g, _ in groups],
                                 "series": [[_r1(v) for v in vals] for _, vals in groups]}
            tables["agefuel"] = [[f] + [_k(vals[i]) if vals[i] is not None else "–" for _, vals in groups]
                                 for i, f in enumerate(fuels)]
            labels["agefuel_cols"] = ["סוג הנעה"] + [g for g, _ in groups]
            labels["agefuel_aria"] = "נסועה שנתית ממוצעת לרכב פרטי לפי סוג הנעה וקבוצת גיל, באלפי ק\"מ"
            g_label, g_vals = groups[-1]
            pairs = [(f, v) for f, v in zip(fuels, g_vals) if v is not None and not _is_total(f)]
            if len(pairs) >= 2:
                pairs.sort(key=lambda x: (-x[1], x[0]))
                hi, lo = pairs[0], pairs[-1]
                if hi[1] >= lo[1] * 1.2:
                    add("agefuel", (f"בקבוצת הגיל \"{g_label}\" נוסע רכב בהנעת {hi[0]} בממוצע "
                                    f"{_k(hi[1])} אלף ק\"מ בשנה, ורכב בהנעת {lo[0]} {_k(lo[1])} אלף ק\"מ."))

    # ── new cars by ownership ────────────────────────────────────────────
    if "owners" in tabs:
        cats, own = _owners(tabs["owners"][1])
        oy = sorted(own)
        if cats and oy:
            flags["owners"] = True
            charts["owners"] = {"x": [str(y) for y in oy], "cats": cats,
                                "series": [[_r1(own[y][c]) for y in oy] for c in cats]}
            tables["owners"] = [[str(y)] + [_k(own[y][c]) if own[y][c] is not None else "–" for c in cats]
                                for y in reversed(oy)]
            labels["owners_cols"] = ["שנה"] + cats
            labels["owners_aria"] = f"נסועה ממוצעת של כלי רכב פרטיים חדשים לפי סוג בעלות, {oy[0]} עד {oy[-1]}"
            ly = oy[-1]
            vals = sorted(((c, v) for c, v in own[ly].items() if v is not None), key=lambda x: (-x[1], x[0]))
            if len(vals) >= 2 and vals[0][1] >= vals[-1][1] * 1.2:
                add("owners", (f"רכב חדש בבעלות {_owner(vals[0][0])} נסע ב-{ly} בממוצע {_k(vals[0][1])} אלף ק\"מ, "
                               f"פי {fmt.num_he(vals[0][1] / vals[-1][1], 1)} מרכב חדש בבעלות "
                               f"{_owner(vals[-1][0])} ({_k(vals[-1][1])} אלף ק\"מ)."))

    # ── OECD per-capita ──────────────────────────────────────────────────
    if "oecd" in tabs:
        rows = sorted(_oecd(tabs["oecd"][1]), key=lambda x: (x[1], x[0]))
        if len(rows) >= 2:
            flags["oecd"] = True
            o_year = _title_year(titles["oecd"])
            charts["oecd"] = {"names": [n for n, _ in rows], "values": [_r2(v) for _, v in rows]}
            tables["oecd"] = [[n, fmt.num_he(v, 1)] for n, v in rows]
            labels["oecd_aria"] = "נסועה שנתית לנפש בישראל ובמדינות OECD נבחרות, באלפי ק\"מ"
            isr = next(((i, v) for i, (n, v) in enumerate(rows) if n == "ישראל"), None)
            if isr:
                i, v = isr
                kpis["per_capita"] = {"value": round(v, 1), "display": fmt.num_he(v, 1), "tone": "brand"}
                labels["per_capita_kpi"] = "אלף ק\"מ לנפש בשנה בישראל" + (f", {o_year}" if o_year else "")
                rank = i + 1
                n = len(rows)
                pos = (f"במקום ה-{rank} מהנמוך מבין {n} המדינות שבתרשים" if rank <= n / 2
                       else f"במקום ה-{n - rank + 1} מהגבוה מבין {n} המדינות שבתרשים")
                add("oecd", (f"נסועה לנפש: {fmt.num_he(v, 1)} אלף ק\"מ לכל תושב בישראל"
                             + (f" בשנת {o_year}" if o_year else "") + f", {pos}. "
                             f"הגבוהה ביותר בתרשים היא ב{rows[-1][0]} ({fmt.num_he(rows[-1][1], 1)} אלף ק\"מ) "
                             f"והנמוכה ביותר ב{rows[0][0]} ({fmt.num_he(rows[0][1], 1)} אלף ק\"מ)."))

    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    # ── text ─────────────────────────────────────────────────────────────
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    yr = f"בשנת {data_year}" if data_year else "בשנה האחרונה"
    if total_bn is not None:
        fact = f"{yr} נסעו כלי הרכב בישראל {fmt.num_he(total_bn, 1)} מיליארד ק\"מ"
        if "private_avg" in kpis:
            fact += f", ורכב פרטי נסע בממוצע {kpis['private_avg']['display']} אלף ק\"מ"
    else:
        fact = f"{yr} היה חלקו של {top_lbl} {fmt.pct_of(top_v, 1)} מכל הקילומטרים"
    labels["lede"] = (f"כמה קילומטרים נוסעים כלי הרכב בישראל (הנסועה), איך זה מתחלק בין סוגי הרכב, "
                      f"ובמה תלוי הקילומטראז' של רכב פרטי: גיל הרכב, סוג ההנעה וסוג הבעלות. "
                      f"הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם "
                      f"כל הודעה חדשה. {fact}.")
    summary = f"נסועה של כלי רכב בישראל לפי נתוני הלמ\"ס: {fact}."
    if total_bn is not None:
        desc = (f"כמה קילומטרים נוסעים בישראל: {fmt.num_he(total_bn, 1)} מיליארד ק\"מ {yr}"
                + (f", {kpis['private_avg']['display']} אלף ק\"מ בממוצע לרכב פרטי" if "private_avg" in kpis else "")
                + ". נסועה לפי סוג רכב, גיל והנעה.")
    else:
        desc = (f"כמה קילומטרים נוסעים בישראל: {top_lbl} נסע {fmt.pct_of(top_v, 1)} מהקילומטרים "
                f"{yr}. נסועה ממוצעת לפי סוג רכב, גיל הרכב וסוג הנעה.")
    years = [y for y in [data_year, s_year] if y]
    if flags.get("index"):
        years.append(int(charts["index"]["x"][0]))
    if flags.get("owners"):
        years.append(int(charts["owners"]["x"][0]))
    cov = f"{min(years)}/{max(years)}" if years else None
    agent = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "נסועה של כלי רכב: כמה קילומטרים נוסעים בישראל | הלמ\"ס",
            "description": desc,
            "name": "נסועה של כלי רכב בישראל",
            "alternate_names": ["קילומטראז' ממוצע לרכב בישראל", "נסועה שנתית ממוצעת לרכב פרטי",
                                "כמה קילומטרים נוסע רכב בשנה", "נסועה בישראל"],
        },
    }
    if cov:
        agent["temporal_coverage"] = cov
    return {
        "agent_data": agent,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top,
        "callouts": callouts,
        "labels": labels,
        "titles": titles,
        "release": release,
        "flags": flags,
    }
