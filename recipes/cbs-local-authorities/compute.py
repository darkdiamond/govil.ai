"""הרשויות המקומיות בישראל: CBS's yearly local-authorities press release.

The release is a set of chart tables ("תרשים N - …") plus, since the 2023
edition, one internal-migration table per big city ("הגירה מיישובים
נבחרים"). Their order and numbering change between editions (the 2022
edition had 14 tables, 2023 34, 2024 36, and a subject moves from t13 to
t12 to t4), so every table resource t1..t36 is read and each table is
recognised by its TITLE text, never by its stem. A subject whose title
is gone just drops its section; a recognised table that is laid out in
a way the parser can't read raises.

Table kinds:
  cluster  rows labelled 1..10 (a socio-economic or periphery cluster)
           plus a national row, one column per series
  cities   one row per city (Hebrew name, one value), plus a national row
  shares   one row per category (Hebrew label, one percent)
  years    one row per year, one column per series; the payments table
           spreads a year over two rows (ordinary, then extraordinary)
  status   population by municipal status, one column per selected year
  flows    one big city's in- and out-migration by locality
"""
import re

from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+\s*[.:\-–]?\s*(.+)$")
PERIOD = re.compile(r"[,\s]*((?:19|20)\d\d(?:\s*[–\-]\s*(?:19|20)\d\d)?)\s*(\(ממוצע\))?\s*$")
NATIONAL = re.compile(r"^כלל[\s\-]?ארצי")
HEB = re.compile(r"[א-ת]")
YEAR = re.compile(r"^(?:19|20)\d\d$")
TOTAL = ("סך הכל", "סה\"כ")
MIN_SECTIONS = 4
MAX_INSIGHTS = 8
# insight id → its section's lede; the top MAX_INSIGHTS by PRIORITY also
# go to the insights card.
LEDE_SECTION = {"life_gap": "cities", "employ": "cities", "bagrut_low": "cities", "mig": "mig",
                "flows": "flows", "status": "status", "pop_se": "pop", "natural": "natural",
                "wage_gap": "wage_se", "edu": "edu", "bagrut_cl": "bagrut_cl", "waste": "waste",
                "receipts": "receipts", "labour": "payments", "gov_share": "sources",
                "edu_pay": "domains"}
PRIORITY = ["life_gap", "flows", "mig", "employ", "gov_share", "bagrut_low", "wage_gap", "natural",
            "receipts", "edu", "bagrut_cl", "waste", "edu_pay", "status", "pop_se", "labour"]

# subject key → (title regex, kind). First match wins; a key is filled once.
SUBJECTS = [
    ("status", r"אוכלוסייה,? לפי מעמד מוניציפלי", "status"),
    ("natural", r"^ריבוי טבעי.*לפי אשכול חברתי", "cluster"),
    ("mig_rate", r"מאזן הגירה פנימית.*בערים", "cities"),
    ("life", r"תוחלת חיים בערים", "cities"),
    ("pop_se", r"^אוכלוסייה,? לפי אשכול חברתי", "cluster"),
    ("pop_peri", r"^אוכלוסייה,? לפי אשכול פריפריאליות", "cluster"),
    ("employ", r"שיעור תעסוקה בערים", "cities"),
    ("commute", r"מועסקים מחוץ ליישוב המגורים בערים", "cities"),
    ("wage_peri", r"^שכר ממוצע.*לפי אשכול פריפריאליות", "cluster"),
    ("wage_se", r"^שכר ממוצע.*לפי אשכול חברתי", "cluster"),
    ("rent_cl", r"^דירות בשכירות.*לפי אשכול", "cluster"),
    ("rent_city", r"^דירות בשכירות בערים", "cities"),
    ("bagrut_cl", r"^זכאים לתעודת בגרות,? לפי אשכול", "cluster"),
    ("bagrut_city", r"^זכאים לתעודת בגרות בערים", "cities"),
    ("dropout", r"שנשרו", "cluster"),
    ("edu", r"^רמת השכלה", "cluster"),
    ("unemp", r"דמי אבטלה", "cluster"),
    ("waste", r"פסולת לנפש", "cluster"),
    ("recycle", r"פסולת ממוחזרת", "cluster"),
    ("rec_years", r"^תקבולי .*בתקציב הרגיל ובתקציב הבלתי רגיל", "years"),
    ("rec_src", r"^תקבולי .*בתקציב הרגיל,? לפי מקור(?! ו)", "shares"),
    ("rec_src_cl", r"^תקבולי .*בתקציב הרגיל,? לפי מקור ואשכול חברתי", "cluster"),
    ("recx_src", r"^תקבולי .*בתקציב הבלתי רגיל,? לפי מקור(?! ו)", "shares"),
    ("recx_src_cl", r"^תקבולי .*בתקציב הבלתי רגיל,? לפי מקור ואשכול חברתי", "cluster"),
    ("pay_years", r"^תשלומי .*בתקציב הרגיל ובתקציב הבלתי רגיל", "years"),
    ("pay_dom", r"^תשלומי .*בתקציב הרגיל,? לפי תחום", "shares"),
    ("payx_dom", r"^תשלומי .*בתקציב הבלתי רגיל,? לפי תחום", "shares"),
]
CITY_METRICS = [  # key, short label, unit, digits
    ("life", "תוחלת חיים", "שנים", 1),
    ("employ", "שיעור תעסוקה", "%", 1),
    ("commute", "עובדים מחוץ ליישוב", "%", 1),
    ("rent_city", "דירות בשכירות", "%", 1),
    ("bagrut_city", "זכאות לבגרות", "%", 1),
]


# ── reading ──────────────────────────────────────────────────────────────


def _city(name):
    """CBS writes "תל אביב -יפו" in one table and "תל אביב-יפו" in another."""
    return re.sub(r"\s*-\s*", "-", " ".join(name.split()))


def _first_num(row, start=1):
    for j in range(start, len(row)):
        v = cbs.val(row, j)
        if v is not None:
            return j, v
    return None, None


def _title(rows):
    """(row index, subject text, period label) of the table's title."""
    for i, r in enumerate(rows[:8]):
        m = TITLE.match(cbs.cell(r, 0))
        if m:
            text = m.group(1).strip()
            p = PERIOD.search(text)
            period = None
            if p:
                period = re.sub(r"\s*[–\-]\s*", "-", p.group(1))
                if p.group(2):
                    period = "ממוצע " + period
                text = text[:p.start()].strip(" ,")
            if period is None:  # a lone year row just under the title
                for r2 in rows[i + 1:i + 4]:
                    cells = [c for c in r2 if c]
                    if len(cells) == 1 and YEAR.match(cells[0]):
                        period = cells[0]
                        break
            return i, text, period
    return None


def _year_range(period):
    """'2020-2024 (ממוצע)' → 2024; '2023' → 2023; None → None."""
    if not period:
        return None
    ys = re.findall(r"(?:19|20)\d\d", period)
    return max(int(y) for y in ys) if ys else None


def _header_names(rows, ti, first_data, cols):
    """Series names: the nearest row above the data (below the title)
    with a label over at least one value column."""
    for i in range(first_data - 1, ti, -1):
        names = {j: cbs.cell(rows[i], j) for j in cols}
        if any(names.values()):
            return names
    return {j: "" for j in cols}


def _cluster(rows, ti):
    data, national = {}, None
    first = None
    for i in range(ti + 1, len(rows)):
        r = rows[i]
        lab = cbs.cell(r, 0)
        if re.fullmatch(r"\d{1,2}", lab) and 1 <= int(lab) <= 10:
            data[int(lab)] = r
            first = i if first is None else first
        elif NATIONAL.match(lab):
            national = r
            first = i if first is None else first
    if not data:
        return None
    cols = sorted({j for r in data.values() for j in range(1, len(r)) if cbs.val(r, j) is not None})
    names = _header_names(rows, ti, first, cols)
    series = []
    for j in cols:
        series.append({"name": names.get(j, ""),
                       "values": {k: cbs.val(r, j) for k, r in data.items()},
                       "national": cbs.val(national, j) if national else None})
    return {"clusters": sorted(data), "series": series}


def _cities(rows, ti):
    items, national = [], None
    for r in rows[ti + 1:]:
        lab = cbs.cell(r, 0)
        _, v = _first_num(r)
        if v is None or not HEB.search(lab):
            continue
        if NATIONAL.match(lab):
            national = v
        else:
            items.append((_city(lab), v))
    if not items:
        return None
    return {"items": items, "national": national}


def _size(titles):
    """The city-size threshold a table title states ("שבהן 50,000 תושבים"), or None."""
    for t in titles:
        m = re.search(r"שבהן\s*(\d{1,3}(?:,\d{3})+)\s*תושבים", t)
        if m:
            return m.group(1)
    return None


def _cities_of(titles, definite=False):
    """"ערים שבהן N תושבים ויותר" from the titles, or a neutral phrase."""
    n = _size(titles)
    h = "ה" if definite else ""
    return f"{h}ערים שבהן {n} תושבים ויותר" if n else f"{h}ערים {h}גדולות"


def _shares(rows, ti):
    items = []
    for r in rows[ti + 1:]:
        j, v = _first_num(r)
        # The label is the first Hebrew cell before the numbers: most tables
        # keep it in C01, some (the extraordinary budget by domain) in C02.
        lab = next((cbs.cell(r, k) for k in range(j if j is not None else 0)
                    if HEB.search(cbs.cell(r, k))), "")
        if v is None or not HEB.search(lab) or NATIONAL.match(lab):
            continue
        items.append((lab, v))
    return {"items": items} if items else None


def _years(rows, ti):
    """{year: {col: value}} plus series names. A row with no year (or the
    same year again) continues the year above; its columns are the
    'continuation' set (the payments table's extraordinary budget)."""
    out, first_cols, cont_cols = {}, set(), set()
    year, first = None, None
    for i in range(ti + 1, len(rows)):
        r = rows[i]
        lab = cbs.cell(r, 0)
        vals = {j: cbs.val(r, j) for j in range(1, len(r)) if cbs.val(r, j) is not None}
        if YEAR.match(lab) and (year is None or int(lab) != year):
            if not vals:
                continue
            year = int(lab)
            first = i if first is None else first
            out[year] = dict(vals)
            first_cols |= vals.keys()
        elif year is not None and vals and (lab == "" or lab == str(year)):
            out[year].update(vals)
            cont_cols |= vals.keys()
    if not out:
        return None
    cols = sorted(first_cols | cont_cols)
    names = _header_names(rows, ti, first, cols)
    return {"years": out, "names": names, "first_cols": sorted(first_cols - cont_cols),
            "cont_cols": sorted(cont_cols - first_cols)}


def _status(rows, ti):
    for i in range(ti + 1, len(rows)):
        ycols = {j: int(c) for j, c in enumerate(rows[i]) if YEAR.match(c)}
        if len(ycols) >= 2:
            break
    else:
        return None
    groups = []
    for r in rows[i + 1:]:
        lab = cbs.cell(r, 0)
        if not HEB.search(lab):
            continue
        vals = {y: cbs.val(r, j) for j, y in ycols.items()}
        if any(v is not None for v in vals.values()):
            groups.append((lab, vals))
    if not groups:
        return None
    years = sorted(ycols.values())
    shares = {}
    for y in years:
        tot = sum(v[y] or 0 for _, v in groups)
        shares[y] = {g: (v[y] / tot * 100 if tot and v[y] is not None else None)
                     for g, v in groups}
    return {"years": years, "groups": [g for g, _ in groups], "shares": shares}


def _flows(rows, mi):
    """One big city's migration table; mi is the 'הגירה מיישובים נבחרים' row."""
    city = _city(cbs.cell(rows[mi - 1], 0)) if mi > 0 else ""
    h = cbs.row_with(rows, "נכנסים", mi, name="flows", contains=True)
    hrow = rows[h]
    cin = cbs.col_after(hrow, "נכנסים", 0, contains=True)
    cout = cbs.col_after(hrow, "יוצאים", 0, contains=True)
    nin = max(j for j in range(cin) if hrow[j] == "שם")
    nout = max(j for j in range(cout) if hrow[j] == "שם")
    year = None
    for r in rows[mi + 1:h]:
        cells = [c for c in r if c]
        if cells and YEAR.match(cells[0]):
            year = int(cells[0])
    tin = tout = None
    pin, pout = [], []
    for r in rows[h + 1:]:
        a, b = cbs.cell(r, nin), cbs.cell(r, nout)
        va, vb = cbs.val(r, cin), cbs.val(r, cout)
        if a in TOTAL:
            tin = va
        elif a and HEB.search(a) and va is not None:
            pin.append((_city(a), va))
        if b in TOTAL:
            tout = vb
        elif b and HEB.search(b) and vb is not None:
            pout.append((_city(b), vb))
    if not city or tin is None or tout is None:
        return None
    def key(kv):
        return (-kv[1], kv[0])
    return {"city": city, "year": year, "in": tin, "out": tout,
            "top_in": sorted(pin, key=key), "top_out": sorted(pout, key=key)}


def _discover(frames):
    found, flows, titles = {}, [], {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        mi = next((i for i, r in enumerate(rows) if "הגירה מיישובים נבחרים" in r), None)
        if mi is not None:
            f = _flows(rows, mi)
            if f:
                flows.append(f)
            continue
        t = _title(rows)
        if not t:
            continue
        ti, text, period = t
        for key, rx, kind in SUBJECTS:
            if key in found or not re.search(rx, text):
                continue
            parsed = {"cluster": _cluster, "cities": _cities, "shares": _shares,
                      "years": _years, "status": _status}[kind](rows, ti)
            if parsed is not None:
                parsed["title"] = text
                parsed["period"] = period
                found[key] = parsed
                titles[key] = n
            break
    flows.sort(key=lambda f: f["city"])
    return found, flows


# ── formatting ───────────────────────────────────────────────────────────


def _r(v, d=1):
    return None if v is None else round(v, d)


def _cl(k):
    return f"אשכול {k}"


def _p(v, d=1):
    return "" if v is None else fmt.pct_of(v, d)


def _n(v, d=1):
    """A number; a negative one with U+2212 minus."""
    return "" if v is None else fmt.num_he(v, d).replace("-", fmt.MINUS)


def _ils(v):
    return "" if v is None else fmt.int_he(v)


def _when(t):
    return f" ({t['period']})" if t.get("period") else ""


def _series_name(s, fallback):
    n = s["name"]
    return n or fallback


# ── sections ─────────────────────────────────────────────────────────────


def _cluster_chart(t, fallbacks, digits=1):
    """Chart + table for a cluster table: x = clusters (+ national)."""
    cl = t["clusters"]
    has_nat = any(s["national"] is not None for s in t["series"])
    x = [_cl(k) for k in cl] + (["כלל ארצי"] if has_nat else [])
    series = []
    for n, s in enumerate(t["series"]):
        vals = [_r(s["values"].get(k), digits) for k in cl]
        if has_nat:
            vals.append(_r(s["national"], digits))
        series.append({"name": _series_name(s, fallbacks[n] if n < len(fallbacks) else ""),
                       "data": vals})
    rows = [[x[i]] + [_n(s["data"][i], digits) if s["data"][i] is not None else "" for s in series]
            for i in range(len(x))]
    return {"x": x, "series": series}, rows, [s["name"] for s in series]


def _ranked(t):
    items = sorted(t["items"], key=lambda kv: (-kv[1], kv[0]))
    return items


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    found, flows = _discover(frames)
    report_year = _year_range(re.search(r"(?:19|20)\d\d\s*$", str(rel["TITLE"])).group(0)
                              if re.search(r"(?:19|20)\d\d\s*$", str(rel["TITLE"])) else None)
    sections = len(found) + (1 if flows else 0)
    if sections < MIN_SECTIONS:
        raise ValueError(f"only {sections} recognised tables (titles changed?): {sorted(found)}")

    kpis, labels, charts, tables, flags, insights = {}, {}, {}, {}, {}, []
    yr = f" {report_year}" if report_year else ""

    # ── cities: metric switcher + lookup table ───────────────────────────
    metrics = [(k, lab, unit, d) for k, lab, unit, d in CITY_METRICS if k in found]
    if metrics:
        city_vals = {}
        for k, *_ in metrics:
            for name, v in found[k]["items"]:
                city_vals.setdefault(name, {})[k] = v
        mig = found.get("mig_rate")
        if mig:
            for name, v in mig["items"]:
                city_vals.setdefault(name, {})["mig_rate"] = v
        cols = [(k, lab, unit, d) for k, lab, unit, d in metrics]
        if mig:
            cols.append(("mig_rate", "מאזן הגירה ל-1,000", "", 1))
        charts["cities"] = {"metrics": []}
        for k, lab, unit, d in metrics:
            t = found[k]
            items = _ranked(t)
            charts["cities"]["metrics"].append({
                "key": k, "label": lab, "unit": unit,
                "title": t["title"] + _when(t),
                "x": [n for n, _ in items], "y": [_r(v, d) for _, v in items],
                "national": _r(t["national"], d)})
        tables["cities"] = [[name] + [_n(city_vals[name].get(k), d) for k, _, _, d in cols]
                            for name in sorted(city_vals)]
        labels["cities_cols"] = ["עיר"] + [lab + (f" ({unit})" if unit else "") for _, lab, unit, _ in cols]
        labels["cities_count"] = fmt.int_he(len(city_vals))
        flags["cities"] = True
        labels["cities_note"] = (
            f"השוואה בין {fmt.int_he(len(city_vals))} "
            f"{_cities_of([found[k]['title'] for k, *_ in metrics])}. בחרו מדד כדי לראות "
            "את דירוג הערים. הקו המקווקו הוא הממוצע הארצי. הטבלה שמתחת מרכזת את כל המדדים לכל עיר.")

        life = found.get("life")
        if life and len(life["items"]) >= 3:
            items = _ranked(life)
            (top, tv), (bot, bv) = items[0], items[-1]
            gap = tv - bv
            if gap >= 1:
                insights.append({"id": "life_gap", "text_he": (
                    f"פער של {fmt.num_he(gap, 1)} שנים בתוחלת החיים בין הערים הגדולות"
                    f"{_when(life)}: {fmt.num_he(tv, 1)} שנים ב{top} לעומת {fmt.num_he(bv, 1)} ב{bot}.")})
            if life["national"] is not None:
                kpis["life"] = {"value": round(life["national"], 1),
                                "display": fmt.num_he(life["national"], 1), "tone": "brand"}
                labels["life_kpi"] = f"תוחלת חיים ארצית{_when(life)}"
            kpis["life_top"] = {"value": round(tv, 1), "display": fmt.num_he(tv, 1), "tone": "ok"}
            labels["life_top_kpi"] = f"תוחלת החיים הגבוהה ביותר בין הערים ({top})"
        emp = found.get("employ")
        if emp and len(emp["items"]) >= 3 and emp["national"] is not None:
            items = _ranked(emp)
            below = [n for n, v in items if v < emp["national"]]
            tail = (f"; ב-{fmt.int_he(len(below))} מתוך {fmt.int_he(len(items))} הערים הוא נמוך "
                    f"מהממוצע הארצי ({fmt.pct_of(emp['national'])})" if below else "")
            insights.append({"id": "employ", "text_he": (
                f"שיעור התעסוקה{_when(emp)} נע בין {fmt.pct_of(items[0][1])} ב{items[0][0]} "
                f"ל-{fmt.pct_of(items[-1][1])} ב{items[-1][0]}{tail}.")})
        bag = found.get("bagrut_city")
        if bag and len(bag["items"]) >= 3:
            low = [(n, v) for n, v in _ranked(bag) if v < 50]
            if low:
                low.sort(key=lambda kv: (kv[1], kv[0]))
                shown = low if len(low) <= 6 else low[:5]
                names = fmt.join_he([f"{n} ({fmt.pct_of(v)})" for n, v in shown])
                if len(shown) < len(low):
                    names += f" ועוד {fmt.int_he(len(low) - len(shown))}"
                insights.append({"id": "bagrut_low", "text_he": (
                    f"ב-{fmt.int_he(len(low))} ערים פחות ממחצית מבני הנוער זכאים לתעודת בגרות"
                    f"{_when(bag)}: {names}.")})

    # ── internal migration rate ──────────────────────────────────────────
    mig = found.get("mig_rate")
    if mig and len(mig["items"]) >= 3:
        items = sorted(mig["items"], key=lambda kv: (kv[1], kv[0]))
        charts["mig"] = {"x": [n for n, _ in items], "y": [_r(v, 1) for _, v in items]}
        tables["mig"] = [[n, _n(v, 1)] for n, v in reversed(items)]
        neg = [n for n, v in items if v < 0]
        labels["mig_note"] = (
            f"{mig['title']}{_when(mig)}. ערך שלילי: יותר תושבים עזבו את העיר לרשויות אחרות "
            "מאשר הגיעו אליה מהן (ההגירה מחוץ לארץ אינה כלולה).")
        flags["mig"] = True
        if neg:
            share = ("כל" if len(neg) == len(items)
                     else f"{fmt.int_he(len(neg))} מתוך")
            pos = (f"; החיובי הגבוה ביותר: {items[-1][0]} ({_n(items[-1][1])})"
                   if items[-1][1] > 0 else "")
            insights.append({"id": "mig", "text_he": (
                f"{share} {fmt.int_he(len(items))} {_cities_of([mig['title']], definite=True)} "
                f"איבדו תושבים בהגירה פנימית{_when(mig)}. המאזן השלילי הגבוה ביותר: {items[0][0]} "
                f"({_n(items[0][1])} לכל 1,000 תושבים){pos}.")})
            labels["mig_rule_n"] = fmt.int_he(len(neg))

    # ── big-city migration flows ─────────────────────────────────────────
    if flows:
        fl = sorted(flows, key=lambda f: (f["in"] - f["out"], f["city"]))
        charts["flows"] = {"x": [f["city"] for f in fl], "in": [f["in"] for f in fl],
                           "out": [-f["out"] for f in fl],
                           "net": [f["in"] - f["out"] for f in fl]}
        tables["flows"] = [[f["city"], fmt.int_he(f["in"]), fmt.int_he(f["out"]),
                            _n(f["in"] - f["out"], 0)] for f in fl]
        tables["partners"] = [[f["city"],
                               fmt.join_he([f"{n} ({fmt.int_he(v)})" for n, v in f["top_in"][:3]]),
                               fmt.join_he([f"{n} ({fmt.int_he(v)})" for n, v in f["top_out"][:3]])]
                              for f in sorted(flows, key=lambda f: f["city"])]
        fy = sorted({f["year"] for f in flows if f["year"]})
        labels["flows_note"] = (
            f"מספר העוברים לכל אחת מ-{fmt.int_he(len(flows))} הערים הגדולות מרשויות אחרות בישראל "
            f"(נכנסים) וממנה אליהן (יוצאים){' בשנת ' + str(fy[-1]) if fy else ''}. "
            "היוצאים מוצגים משמאל לקו האפס, והנקודה היא המאזן.")
        flags["flows"] = True
        losers = [f for f in fl if f["out"] > f["in"]]
        if losers:
            w = losers[0]
            top_dest = w["top_out"][0] if w["top_out"] else None
            dest = f" היעד המוביל של העוזבים: {top_dest[0]} ({fmt.int_he(top_dest[1])})." if top_dest else ""
            insights.append({"id": "flows", "text_he": (
                f"ב-{fmt.int_he(len(losers))} מתוך {fmt.int_he(len(fl))} הערים הגדולות מספר העוזבים לרשויות "
                f"אחרות עלה על מספר המגיעים. הפער הגדול ביותר ב{w['city']}: {fmt.int_he(w['out'])} עזבו "
                f"ו-{fmt.int_he(w['in'])} הגיעו.{dest}")})

    # ── population by municipal status ───────────────────────────────────
    st = found.get("status")
    if st:
        ys = st["years"]
        charts["status"] = {"x": [str(y) for y in ys],
                            "series": [{"name": g, "data": [_r(st["shares"][y][g], 1) for y in ys]}
                                       for g in st["groups"]]}
        tables["status"] = [[str(y)] + [_p(st["shares"][y][g]) for g in st["groups"]] for y in ys]
        labels["status_cols"] = ["שנה"] + st["groups"]
        labels["status_note"] = (f"התפלגות האוכלוסייה ברשויות המקומיות לפי מעמד מוניציפלי (עיריות, "
                                 f"מועצות מקומיות ומועצות אזוריות), באחוזים, בשנים נבחרות {ys[0]} עד {ys[-1]}.")
        flags["status"] = True
        muni = next((g for g in st["groups"] if g.startswith("עיריות")), None)
        if muni:
            last, firsty = ys[-1], ys[0]
            v = st["shares"][last][muni]
            kpis["muni"] = {"value": round(v, 1), "display": fmt.pct_of(v), "tone": "brand"}
            labels["muni_kpi"] = f"מהאוכלוסייה גרים בעיריות ({last})"
            v0 = st["shares"][firsty][muni]
            if v0 is not None and abs(v - v0) >= 1:
                insights.append({"id": "status", "text_he": (
                    f"{fmt.pct_of(v)} מתושבי הרשויות המקומיות גרים בעיריות ({last}), לעומת "
                    f"{fmt.pct_of(v0)} בשנת {firsty}.")})

    # ── population by cluster ────────────────────────────────────────────
    pse, pper = found.get("pop_se"), found.get("pop_peri")
    if pse or pper:
        cl = sorted(set((pse or {}).get("clusters", [])) | set((pper or {}).get("clusters", [])))
        ser = []
        if pse:
            ser.append({"name": "לפי אשכול חברתי-כלכלי",
                        "data": [_r(pse["series"][0]["values"].get(k), 1) for k in cl]})
        if pper:
            ser.append({"name": "לפי אשכול פריפריאליות",
                        "data": [_r(pper["series"][0]["values"].get(k), 1) for k in cl]})
        charts["pop"] = {"x": [_cl(k) for k in cl], "series": ser}
        tables["pop"] = [[_cl(k)] + [_p(s["data"][i]) for s in ser] for i, k in enumerate(cl)]
        labels["pop_cols"] = ["אשכול"] + [s["name"] for s in ser]
        labels["pop_note"] = (
            f"אחוז מהאוכלוסייה שגר ברשויות בכל אשכול{_when(pse or pper)}. אשכול 1 הוא הנמוך ביותר "
            "(חברתית-כלכלית, או המרוחק ביותר ממרכז הארץ) ואשכול 10 הגבוה ביותר.")
        flags["pop"] = True
        if pse:
            v = pse["series"][0]["values"]
            low = sum(v.get(k) or 0 for k in (1, 2, 3))
            high = sum(v.get(k) or 0 for k in (8, 9, 10))
            if low and high:
                insights.append({"id": "pop_se", "text_he": (
                    f"{fmt.pct_of(low)} מהאוכלוסייה גרים ברשויות באשכולות החברתיים-כלכליים 1 עד 3, "
                    f"ו-{fmt.pct_of(high)} באשכולות 8 עד 10{_when(pse)}.")})

    # ── generic cluster charts ───────────────────────────────────────────
    def cluster_section(key, fallbacks, digits=1):
        t = found.get(key)
        if not t:
            return None
        ch, rows, names = _cluster_chart(t, fallbacks, digits)
        charts[key] = ch
        tables[key] = rows
        labels[key + "_cols"] = ["אשכול"] + names
        labels[key + "_note"] = t["title"] + _when(t) + "."
        flags[key] = True
        return t

    nat = cluster_section("natural", ["ריבוי טבעי ל-1,000 תושבים"])
    if nat:
        s = next((s for s in nat["series"] if "ריבוי" in s["name"]), nat["series"][0])
        v1, v10 = s["values"].get(1), s["values"].get(10)
        if v1 is not None and v10 is not None and v1 > v10:
            ten = (f"ריבוי טבעי שלילי ({_n(v10)}) באשכול 10" if v10 < 0
                   else f"{_n(v10)} באשכול 10")
            insights.append({"id": "natural", "text_he": (
                f"הריבוי הטבעי ברשויות באשכול החברתי-כלכלי 1 הוא {_n(v1)} לכל 1,000 תושבים{_when(nat)}, "
                f"לעומת {ten}.")})

    wse = cluster_section("wage_se", ["גברים", "נשים"], 0)
    cluster_section("wage_peri", ["גברים", "נשים"], 0)
    if wse and len(wse["series"]) >= 2:
        men = next((s for s in wse["series"] if "גבר" in s["name"]), None)
        women = next((s for s in wse["series"] if "נש" in s["name"]), None)
        if men and women and men["national"] and women["national"]:
            ratio = women["national"] / men["national"]
            insights.append({"id": "wage_gap", "text_he": (
                f"השכר הממוצע של נשים{_when(wse)} הוא {fmt.pct(ratio, 0)} משכר הגברים: "
                f"{_ils(women['national'])} ₪ לעומת {_ils(men['national'])} ₪ לחודש. "
                + (f"באשכול 10 גברים משתכרים בממוצע {_ils(men['values'][10])} ₪."
                   if men["values"].get(10) else ""))})

    cluster_section("rent_cl", ["לפי אשכול חברתי-כלכלי", "לפי אשכול פריפריאליות"])
    bcl = cluster_section("bagrut_cl", ["זכאים לבגרות", "עומדים בדרישות הסף של האוניברסיטאות"])
    cluster_section("dropout", ["בנים", "בנות"], 2)
    edu = cluster_section("edu", ["פחות מ-12 שנות לימוד", "12 שנות לימוד", "אקדמאים"])
    cluster_section("unemp", ["", ""], 2)
    if edu:
        acad = next((s for s in edu["series"] if s["name"].startswith("אקדמ")), None)
        if acad and acad["values"].get(1) is not None and acad["values"].get(10) is not None:
            insights.append({"id": "edu", "text_he": (
                f"שיעור האקדמאים בקרב בני 25 עד 65 עולה מ-{fmt.pct_of(acad['values'][1])} ברשויות באשכול 1 "
                f"ל-{fmt.pct_of(acad['values'][10])} באשכול 10{_when(edu)}"
                + (f", לעומת ממוצע ארצי של {fmt.pct_of(acad['national'])}." if acad["national"] else "."))})
    if bcl and not any(i["id"] == "edu" for i in insights):
        s = bcl["series"][0]
        if s["values"].get(1) is not None and s["values"].get(9) is not None:
            insights.append({"id": "bagrut_cl", "text_he": (
                f"הזכאות לבגרות ברשויות באשכול 1 היא {fmt.pct_of(s['values'][1])}, לעומת "
                f"{fmt.pct_of(s['values'][9])} באשכול 9{_when(bcl)}.")})

    # waste + recycling: one chart, two axes
    wst, rcy = found.get("waste"), found.get("recycle")
    if wst or rcy:
        cl = sorted(set((wst or {}).get("clusters", [])) | set((rcy or {}).get("clusters", [])))
        nat_w = wst["series"][0]["national"] if wst else None
        nat_r = rcy["series"][0]["national"] if rcy else None
        x = [_cl(k) for k in cl] + ["כלל ארצי"]
        w = [_r(wst["series"][0]["values"].get(k), 2) for k in cl] + [_r(nat_w, 2)] if wst else None
        r_ = [_r(rcy["series"][0]["values"].get(k), 1) for k in cl] + [_r(nat_r, 1)] if rcy else None
        charts["waste"] = {"x": x, "waste": w, "recycle": r_}
        tables["waste"] = [[x[i], _n(w[i], 2) if w else "", _p(r_[i]) if r_ else ""]
                           for i in range(len(x))]
        labels["waste_cols"] = ["אשכול", "פסולת לנפש ליום (ק\"ג)", "פסולת ממוחזרת"]
        labels["waste_note"] = (
            "כמות הפסולת הממוצעת לנפש ליום (ק\"ג, עמודות) ואחוז הפסולת שממוחזרת (קו), לפי האשכול "
            f"החברתי-כלכלי של הרשות{_when(wst or rcy)}.")
        flags["waste"] = True
        if wst and wst["series"][0]["values"].get(10) and nat_w:
            v10 = wst["series"][0]["values"][10]
            if v10 > nat_w * 1.5:
                insights.append({"id": "waste", "text_he": (
                    f"ברשויות באשכול 10 נוצרים {fmt.num_he(v10, 1)} ק\"ג פסולת לנפש ביום, "
                    f"פי {fmt.num_he(v10 / nat_w, 1)} מהממוצע הארצי של {fmt.num_he(nat_w, 1)} ק\"ג{_when(wst)}.")})

    # ── budget: receipts and payments over the years ─────────────────────
    ry = found.get("rec_years")
    if ry:
        ys = sorted(ry["years"])
        cols = sorted({j for y in ys for j in ry["years"][y]})
        ser = [{"name": ry["names"].get(j) or f"סדרה {n + 1}",
                "data": [_r(ry["years"][y].get(j), 1) for y in ys]} for n, j in enumerate(cols)]
        charts["receipts"] = {"x": [str(y) for y in ys], "series": ser}
        tables["receipts"] = [[str(y)] + [_n(ry["years"][y].get(j), 1) for j in cols]
                              + [_n(sum(v for v in ry["years"][y].values()), 1)] for y in reversed(ys)]
        labels["receipts_cols"] = ["שנה"] + [s["name"] for s in ser] + ["סך הכל"]
        labels["receipts_note"] = (f"תקבולי הרשויות המקומיות בכל שנה, במיליארדי ₪ (מחירים שוטפים), "
                                   f"{ys[0]} עד {ys[-1]}.")
        flags["receipts"] = True
        reg = next((j for j in cols if ry["names"].get(j, "").startswith("תקציב רגיל")), cols[0])
        last, prev = ys[-1], ys[-2] if len(ys) > 1 else None
        v = ry["years"][last].get(reg)
        if v is not None:
            kpis["receipts"] = {"value": round(v, 1), "display": fmt.num_he(v, 1), "tone": "brand"}
            labels["receipts_kpi"] = f"תקבולי התקציב הרגיל, {last} (מיליארדי ₪)"
            if prev and ry["years"][prev].get(reg):
                c = v / ry["years"][prev][reg] - 1
                kpis["receipts_chg"] = {"value": round(c, 4), "display": fmt.signed_pct(c),
                                        "tone": "ok" if c > 0 else "warn"}
                labels["receipts_chg_kpi"] = f"שינוי בתקבולי התקציב הרגיל לעומת {prev}"
                v0 = ry["years"][ys[0]].get(reg)
                if v0:
                    insights.append({"id": "receipts", "text_he": (
                        f"תקבולי התקציב הרגיל של הרשויות המקומיות הגיעו ל-{fmt.num_he(v, 1)} מיליארד ₪ "
                        f"בשנת {last}, {'עלייה' if c > 0 else 'ירידה'} של {fmt.pct(abs(c))} לעומת {prev} "
                        f"ופי {fmt.num_he(v / v0, 1)} מבשנת {ys[0]} (במחירים שוטפים).")})

    py = found.get("pay_years")
    if py:
        ys = sorted(py["years"])
        fc, cc = py["first_cols"], py["cont_cols"]
        ser = []
        for j in fc:
            ser.append({"name": py["names"].get(j) or "", "stack": "רגיל",
                        "data": [_r(py["years"][y].get(j), 1) for y in ys]})
        for j in cc:
            ser.append({"name": py["names"].get(j) or "", "stack": "בלתי רגיל",
                        "data": [_r(py["years"][y].get(j), 1) for y in ys]})
        charts["payments"] = {"x": [str(y) for y in ys], "series": ser}
        allc = fc + cc
        tables["payments"] = [[str(y)] + [_n(py["years"][y].get(j), 1) for j in allc] for y in reversed(ys)]
        labels["payments_cols"] = ["שנה"] + [(py["names"].get(j) or "") + (" (רגיל)" if j in fc else " (בלתי רגיל)")
                                             for j in allc]
        labels["payments_note"] = (
            f"תשלומי הרשויות המקומיות לפי סוג, במיליארדי ₪ (מחירים שוטפים), {ys[0]} עד {ys[-1]}. "
            "העמודה השמאלית בכל שנה היא התקציב הבלתי רגיל (פיתוח), והימנית התקציב הרגיל.")
        flags["payments"] = True
        labour = next((j for j in fc if "עבודה" in (py["names"].get(j) or "")), None)
        if labour is not None:
            last = ys[-1]
            tot = sum(py["years"][last].get(j) or 0 for j in fc)
            lv = py["years"][last].get(labour)
            if tot and lv:
                insights.append({"id": "labour", "text_he": (
                    f"עלות העבודה היא {fmt.pct(lv / tot)} מתשלומי התקציב הרגיל ({fmt.num_he(lv, 1)} "
                    f"מתוך {fmt.num_he(tot, 1)} מיליארד ₪ בשנת {last}).")})

    # receipts by source: overall + by cluster, ordinary and extraordinary
    def sources(key_all, key_cl, out):
        ta, tc = found.get(key_all), found.get(key_cl)
        if not ta and not tc:
            return None
        if tc:
            cats = [_series_name(s, f"מקור {n + 1}") for n, s in enumerate(tc["series"])]
        else:
            cats = [lab for lab, _ in ta["items"]]
        cats = [re.sub(r"\s*\(.*?\)\s*$", "", c).strip() for c in cats]
        x, data = [], {c: [] for c in cats}
        if ta:
            amap = {re.sub(r"\s*\(.*?\)\s*$", "", lab).strip(): v for lab, v in ta["items"]}
            x.append("כלל הרשויות")
            for c in cats:
                data[c].append(_r(amap.get(c, _fuzzy(amap, c)), 1))
        if tc:
            for k in tc["clusters"]:
                x.append(_cl(k))
                for n, c in enumerate(cats):
                    data[c].append(_r(tc["series"][n]["values"].get(k), 1))
        charts[out] = {"x": x, "series": [{"name": c, "data": data[c]} for c in cats]}
        tables[out] = [[x[i]] + [_p(data[c][i]) for c in cats] for i in range(len(x))]
        labels[out + "_cols"] = [""] + cats
        flags[out] = True
        return ta, tc, cats, data, x

    src = sources("rec_src", "rec_src_cl", "sources")
    if src:
        ta, tc, cats, data, x = src
        t = ta or tc
        labels["sources_note"] = (f"מקורות התקבולים בתקציב הרגיל, באחוזים, בכלל הרשויות ולפי האשכול "
                                  f"החברתי-כלכלי של הרשות{_when(t)}.")
        gov = next((c for c in cats if "ממשלה" in c), None)
        arn = next((c for c in cats if "ארנונה" in c), None)
        if gov and ta and data[gov][0] is not None:
            kpis["gov_share"] = {"value": data[gov][0], "display": fmt.pct_of(data[gov][0]), "tone": "info"}
            labels["gov_share_kpi"] = f"מתקבולי התקציב הרגיל באים מהממשלה{_when(ta)}"
        if gov and tc and "אשכול 1" in x and "אשכול 10" in x:
            g1, g10 = data[gov][x.index("אשכול 1")], data[gov][x.index("אשכול 10")]
            a1 = data[arn][x.index("אשכול 1")] if arn else None
            a10 = data[arn][x.index("אשכול 10")] if arn else None
            if g1 is not None and g10 is not None and g1 > g10:
                tail = (f" הארנונה מכסה {fmt.pct_of(a1)} מהתקבולים באשכול 1 ו-{fmt.pct_of(a10)} באשכול 10."
                        if a1 is not None and a10 is not None else "")
                insights.append({"id": "gov_share", "text_he": (
                    f"ברשויות באשכול החברתי-כלכלי 1 השתתפות הממשלה היא {fmt.pct_of(g1)} מתקבולי התקציב "
                    f"הרגיל, לעומת {fmt.pct_of(g10)} באשכול 10{_when(tc)}.{tail}")})
    srcx = sources("recx_src", "recx_src_cl", "sourcesx")
    if srcx:
        t = srcx[0] or srcx[1]
        labels["sourcesx_note"] = (f"מקורות התקבולים בתקציב הבלתי רגיל (פיתוח), באחוזים, בכלל הרשויות "
                                   f"ולפי האשכול החברתי-כלכלי של הרשות{_when(t)}.")

    # payments by domain
    pd_, px = found.get("pay_dom"), found.get("payx_dom")
    if pd_ or px:
        doms = []
        for t in (pd_, px):
            for lab, _ in (t or {}).get("items", []):
                c = re.sub(r"\s*\(.*?\)\s*$", "", lab).strip()
                if c not in doms:
                    doms.append(c)
        def dmap(t):
            return {re.sub(r"\s*\(.*?\)\s*$", "", lab).strip(): v for lab, v in t["items"]} if t else {}
        mr, mx = dmap(pd_), dmap(px)
        ser = []
        if pd_:
            ser.append({"name": "תקציב רגיל", "data": [_r(mr.get(c), 1) for c in doms]})
        if px:
            ser.append({"name": "תקציב בלתי רגיל", "data": [_r(mx.get(c), 1) for c in doms]})
        charts["domains"] = {"x": doms, "series": ser}
        tables["domains"] = [[c] + [_p(s["data"][i]) for s in ser] for i, c in enumerate(doms)]
        labels["domains_cols"] = ["תחום"] + [s["name"] for s in ser]
        labels["domains_note"] = (f"חלוקת התשלומים של הרשויות המקומיות לפי תחום, באחוזים מכלל "
                                  f"התשלומים בכל תקציב{_when(pd_ or px)}. \"אחר\" כולל בין השאר מינהל, "
                                  "שירותים מקומיים ופירעון מלוות.")
        flags["domains"] = True
        if pd_ and mr.get("חינוך"):
            v = mr["חינוך"]
            kpis["edu_pay"] = {"value": round(v, 1), "display": fmt.pct_of(v), "tone": "brand"}
            labels["edu_pay_kpi"] = f"מתשלומי התקציב הרגיל מוקדשים לחינוך{_when(pd_)}"
            top = max(((c, v2) for c, v2 in mr.items() if not c.startswith("אחר")),
                      key=lambda kv: (kv[1], kv[0]))
            if top[0] == "חינוך" and mr.get("רווחה"):
                insights.append({"id": "edu_pay", "text_he": (
                    f"החינוך הוא התחום הגדול בתשלומי התקציב הרגיל של הרשויות: {fmt.pct_of(v)}, "
                    f"ואחריו הרווחה עם {fmt.pct_of(mr['רווחה'])}{_when(pd_)}.")})

    # ── release card, lede, SEO ──────────────────────────────────────────
    release = {"title": str(rel["TITLE"]), "date": _date_he(str(rel["RELEASE_DATE"])),
               "headline": str(rel.get("HEADLINE") or ""), "url": str(rel["PAGE_URL"]),
               "pdf": str(rel.get("REPORT_PDF_URL") or "")}
    n_cities = len(tables.get("cities", []))
    bits = []
    if n_cities:
        bits.append(f"השוואה בין {fmt.int_he(n_cities)} הערים הגדולות בתוחלת חיים, תעסוקה, השכלה ודיור")
    if flows:
        bits.append(f"הגירה פנימית אל {fmt.int_he(len(flows))} הערים הגדולות וממנה")
    if pse or nat or wse:
        bits.append("פערים בין אשכולות חברתיים-כלכליים")
    if ry or py:
        bits.append("תקציבי הרשויות")
    labels["lede"] = (
        f"נתוני הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על הרשויות המקומיות בישראל{yr}, מתוך ההודעה השנתית "
        f"לתקשורת: {fmt.join_he(bits)}. העמוד מתעדכן עם כל מהדורה חדשה.")

    if len(insights) < 3:
        raise ValueError(f"only {len(insights)} insights")
    rank = {k: n for n, k in enumerate(PRIORITY)}
    ordered = sorted(insights, key=lambda i: rank[i["id"]])
    insights = ordered[:MAX_INSIGHTS]
    ledes = {}  # the rest become their section's lede (no sentence shown twice)
    for i in ordered[MAX_INSIGHTS:]:
        ledes.setdefault(LEDE_SECTION[i["id"]], []).append(i["text_he"])

    desc_bits = []
    if "life" in found and found["life"]["items"]:
        top = _ranked(found["life"])[0]
        desc_bits.append(f"תוחלת החיים הגבוהה ביותר ב{top[0]} ({fmt.num_he(top[1], 1)})")
    if "receipts" in kpis:
        desc_bits.append(f"תקציב רגיל {kpis['receipts']['display']} מיליארד ₪")
    description = ("נתוני הרשויות המקומיות בישראל: השוואת ערים בתעסוקה, השכלה, תוחלת חיים והגירה, "
                   "ותקציבי הרשויות. " + "; ".join(desc_bits) + ".")
    if len(description) > 150:
        cut = description.rfind(";")
        if cut > 0:
            description = description[:cut] + "."
    summary = (f"הרשויות המקומיות בישראל לפי הלמ\"ס{yr}: " + fmt.join_he(bits) + ".")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "rankings",
        "spatial_coverage": "ישראל, הרשויות המקומיות",
        "seo": {
            "title": "הרשויות המקומיות בישראל: נתוני ערים ותקציבים",
            "description": description,
            "name": "הרשויות המקומיות בישראל",
            "alternate_names": ["נתוני רשויות מקומיות", "השוואת ערים בישראל",
                                "קובץ הרשויות המקומיות", "תקציבי הרשויות המקומיות"],
        },
    }
    if report_year:
        agent_data["temporal_coverage"] = str(report_year)
    if charts.get("receipts"):
        agent_data["temporal_coverage"] = f"{charts['receipts']['x'][0]}/{charts['receipts']['x'][-1]}"

    return {"agent_data": agent_data, "kpis": kpis, "labels": labels, "charts": charts,
            "tables": tables, "flags": flags, "insights": insights, "ledes": ledes,
            "release": release}


def _fuzzy(amap, c):
    """A source label that differs only in wording ("הכנסות עצמיות ואחרות")."""
    words = set(c.split())
    best = max(amap, key=lambda k: (len(words & set(k.split())), k), default=None)
    if best is not None and len(words & set(best.split())) >= 2:
        return amap[best]
    return None


def _date_he(iso):
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", iso)
    if not m:
        return iso
    return f"{int(m.group(3))} ב{fmt.MONTHS_HE[int(m.group(2)) - 1]} {m.group(1)}"
