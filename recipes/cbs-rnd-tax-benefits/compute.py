"""הטבות מס לחברות העוסקות במחקר ופיתוח: CBS's yearly R&D tax-benefit release.

The release is a set of chart-data sheets ("תרשים N - ..."), and CBS
renumbers them between editions (the 2022 edition had ten, with three OECD
charts; the 2023 edition has seven). So every table input (t1..t10, the last
three spare, all optional) is read with `cbs.grid`, and each table is found
by its TITLE text, not by its stem:

  series   סך ההטבות במס ... תוצר        yearly benefits by plan, % of GDP, grants
  plans    מספר החברות ... סוג מפעל       shares of firms, benefits, R&D, staff by plan
  size     גודל החברה                     benefits by firm size and plan
  sector   ענפים                          benefits by industry and plan (M NIS)
  startups חברות הזנק                     startups' benefits by field (shares)
  owner    בעלות                          benefits by ownership and plan
  oecd     OECD                           government R&D support as % of GDP

An edition without title rows (the 2022 one) falls back to content for the
tables whose labels say what they are (series, size, sector, startups).
`series` is required; any other table missing from an edition drops its
section. A table found by title whose header labels are gone raises.

Units: the series and sector tables are in millions of NIS; the ownership
detail block says "במיליוני ש'ח" but holds shekels in the 2023 edition (its
three columns add up to the series total only after dividing by 1e6), so any
amount there of 1e6 or more is read as shekels. OECD values are already
percent of GDP. Every other share is a fraction of 1.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*-\s*")
HEB = re.compile("[א-ת]")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
PLANS = ("preferred", "special")
PLAN_NAMES = {"total": "סך הכל", "preferred": "מפעל טכנולוגי מועדף",
              "special": "מפעל טכנולוגי מועדף מיוחד"}
SIZE_ORDER = ("small", "mid", "large", "none")
SIZE_NAMES = {"small": "1-49 מועסקים", "mid": "50-249 מועסקים",
              "large": "250 מועסקים ומעלה", "none": "ללא מועסקים"}
OWN_NAMES = {"foreign": "חברת בת של קבוצה זרה", "israeli": "חברה ישראלית",
             "national": "חברה ישראלית לאומית",
             "multi": "חברה ישראלית רב-לאומית"}
MEASURES = (("companies", "מספר חברות", "החברות"), ("benefits", "סך כל הטבות", "ההטבות"),
            ("rnd", "סך ההוצאות", "ההוצאה למו\"פ"), ("emp", "סך מועסקים", "המועסקים"))
PRIORITY = ("trend", "gdp", "concentration", "driver", "size", "sector", "owner", "oecd",
            "grants", "startups")
MAX_TOP = 7


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind_by_title(t):
    if "OECD" in t:
        return "oecd"
    if "חברות הזנק" in t:
        return "startups"
    if "בעלות" in t:
        return "owner"
    if "גודל החברה" in t:
        return "size"
    if "ענפים" in t:
        return "sector"
    if "מספר החברות" in t:
        return "plans"
    if "סך ההטבות" in t and "תוצר" in t:
        return "series"
    return None


def _cells(rows):
    return {c for r in rows for c in r if c}


def _kind_by_content(rows):
    cells = _cells(rows)
    years = max((sum(1 for c in r if cbs.YEAR.match(c)) for r in rows), default=0)
    if years >= 3 and any(c.startswith("תמריצי מס למחקר ופיתוח") for c in cells):
        return "series"
    if any("1-49" in c for c in cells) and any("אינם מעסיקים" in c for c in cells):
        return "size"
    if "תעשיה עילית" in cells and any("מועדף מיוחד" in c for c in cells):
        return "sector"
    if "סייבר" in cells and "תוכן ומדיה" in cells:
        return "startups"
    return None


def _tables(frames):
    """{kind: (title, rows)} over every non-empty table input; the first
    match by stem number wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        t = _title(rows)
        k = _kind_by_title(t) if t else _kind_by_content(rows)
        if k == "oecd":
            out.setdefault("oecd_all", []).append((t, rows))
        elif k and k not in out:
            out[k] = (t, rows)
    return out


# ── small helpers ────────────────────────────────────────────────────────


def _label(r):
    """(index, text) of the row's first cell with Hebrew or Latin letters."""
    for j, c in enumerate(r):
        if c and cbs.num(c) is None and re.search(r"[א-תA-Za-z]", c):
            return j, c
    return None, ""


def _first_num(r, start):
    for j in range(start, len(r)):
        v = cbs.num(r[j])
        if v is not None:
            return v
    return None


def _plan_of(label):
    if "מיוחד" in label:
        return "special"
    if "מועדף" in label:
        return "preferred"
    return None


def _size_of(label):
    if "1-49" in label:
        return "small"
    if "50-249" in label:
        return "mid"
    if "249+" in label or "250+" in label or "250 ומעלה" in label:
        return "large"
    if "אינם מעסיקים" in label or "ללא מועסקים" in label:
        return "none"
    if label == "סך הכל":
        return "total"
    return None


def _title_year(title):
    years = [int(y) for y in YEAR_IN.findall(title)]
    return max(years) if years else None


def _r1(v):
    return None if v is None else round(v, 1)


def _r3(v):
    return None if v is None else round(v, 3)


def _m(v):
    """Millions of NIS for a sentence: 6790.5 → '6,791'."""
    return fmt.int_he(v)


def _times(a, b):
    r = a / b
    return f"פי {r:.1f}"


# ── table parsers ────────────────────────────────────────────────────────


def _series(rows):
    """{key: {year: value}} for total / preferred / special (M NIS), gdp
    (M NIS), share (fraction) and grant (M NIS)."""
    yr = None
    for i, r in enumerate(rows):
        if sum(1 for c in r if cbs.YEAR.match(c)) >= 3:
            yr = i
            break
    if yr is None:
        raise ValueError("series: year header row not found")
    ycols = {j: int(c) for j, c in enumerate(rows[yr]) if cbs.YEAR.match(c)}
    out = {k: {} for k in ("total", "preferred", "special", "gdp", "share", "grant")}
    for r in rows[yr + 1:]:
        lab = cbs.cell(r, 0)
        if not lab:
            continue
        if lab.startswith("תמריצי מס למחקר ופיתוח"):
            key = _plan_of(lab) or "total"
        elif lab.startswith("תמ") and "מגזר העסקי" in lab:
            key = "gdp"
        elif lab.startswith("כאחוז"):
            key = "share"
        elif "רשות החדשנות" in lab:
            key = "grant"
        else:
            continue
        if out[key]:
            continue
        for j, y in ycols.items():
            v = cbs.val(r, j)
            if v is not None:
                out[key][y] = v
    if not out["total"]:
        raise ValueError("series: total tax-incentive row not found")
    return out


def _plans(rows):
    h = cbs.row_with(rows, "מספר חברות שקיבלו", name="plans", contains=True)
    cols = {k: cbs.col_after(rows[h], lab, 0, contains=True) for k, lab, _ in MEASURES}
    out = {}
    for r in rows[h + 1:]:
        _, lab = _label(r)
        p = _plan_of(lab)
        if p and p not in out:
            vals = {k: cbs.val(r, j) for k, j in cols.items()}
            if any(v is not None for v in vals.values()):
                out[p] = vals
    return out


def _size(rows):
    """{block: {size: M NIS}}, blocks total / preferred / special."""
    out = {"total": {}}
    block = "total"
    for r in rows:
        j, lab = _label(r)
        if j is None or TITLE.match(lab):
            continue
        v = _first_num(r, j + 1)
        if v is None:
            p = _plan_of(lab)
            if p:
                block = p
                out.setdefault(block, {})
            continue
        s = _size_of(lab)
        if s and s not in out[block]:
            out[block][s] = v
    return out


def _sector(title, rows):
    h = None
    for i, r in enumerate(rows):
        if "סך הכל" in r and any("מועדף מיוחד" in c for c in r):
            h = i
            break
    if h is None:
        raise ValueError("sector: header row 'סך הכל' / plan columns not found")
    hdr = rows[h]
    tot = cbs.col_after(hdr, "סך הכל", 0)
    spc = next(j for j, c in enumerate(hdr) if "מועדף מיוחד" in c)
    prf = next((j for j, c in enumerate(hdr) if "מועדף" in c and "מיוחד" not in c), None)
    if prf is None:
        raise ValueError("sector: preferred-plan column not found")
    year = _title_year(title) or (int(hdr[0]) if cbs.YEAR.match(cbs.cell(hdr, 0)) else None)
    total, items = None, []
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        v = cbs.val(r, tot)
        if not lab or v is None:
            continue
        if lab == "סך הכל":
            total = v
            continue
        items.append((lab, v, cbs.val(r, prf) or 0.0, cbs.val(r, spc) or 0.0))
    return year, total, items


def _startups(title, rows):
    items = []
    for r in rows:
        j, lab = _label(r)
        if j is None or TITLE.match(lab) or not HEB.search(lab):
            continue
        v = _first_num(r, j + 1)
        if v is not None:
            items.append((lab, v))
    return _title_year(title), items


def _amount_blocks(rows, h, cols):
    """{plan block: {own: amount}} from the "סך הכל במיליוני" rows after
    header row h; a block starts at a label row naming its plan."""
    amounts, block = {}, "total"
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        if lab.startswith("סך הכל במיליוני"):
            vals = {k: cbs.val(r, j) for k, j in cols.items()}
            if block not in amounts and all(v is not None for v in vals.values()):
                amounts[block] = vals
        elif lab and not lab.startswith("אחוז"):
            block = _plan_of(lab) or "total"
    return amounts


def _owner(rows):
    """(categories [key], shares {plan: {own: 0-1}}, amounts {plan: {own: M NIS}}).

    Three layouts: the 2023 detail block (foreign / Israeli without a
    foreign subsidiary / Israeli multinational, amounts), the 2023 summary
    block (the same three, shares only), and the 2022 two-way block
    (foreign / Israeli, amounts)."""
    def header(*needles):
        return next((i for i, r in enumerate(rows)
                     if all(any(n in c for c in r) for n in needles)), None)

    cols, amounts, shares = None, {}, {}
    h = header("קבוצת חברות זרה", "ללא חברת בת")
    if h is not None:
        hdr = rows[h]
        cols = {"foreign": cbs.col_after(hdr, "קבוצת חברות זרה", 1, contains=True),
                "national": cbs.col_after(hdr, "ללא חברת בת", 1, contains=True),
                "multi": cbs.col_after(hdr, "עם לפחות חברת בת", 1, contains=True)}
        amounts = _amount_blocks(rows, h, cols)
    if not amounts:
        h = header("חברת בת של קבוצת חברות זרה", "רב-לאומית")
        if h is not None:
            hdr = rows[h]
            cols = {"foreign": cbs.col_after(hdr, "קבוצת חברות זרה", 1, contains=True),
                    "national": cbs.col_after(hdr, "לאומית", 1, contains=True),
                    "multi": cbs.col_after(hdr, "רב-לאומית", 1, contains=True)}
            for r in rows[h + 1:]:
                lab = cbs.cell(r, 0)
                b = _plan_of(lab) or ("total" if lab.startswith("סך הכל") else None)
                vals = {k: cbs.val(r, j) for k, j in cols.items()}
                if b and b not in shares and all(v is not None for v in vals.values()) \
                        and sum(vals.values()) > 0:
                    shares[b] = {k: v / sum(vals.values()) for k, v in vals.items()}
    if not amounts and not shares:
        h = next((i for i, r in enumerate(rows) if "זרה" in r and "ישראלית" in r), None)
        if h is None:
            raise ValueError("owner: ownership header labels not found")
        cols = {"foreign": rows[h].index("זרה"), "israeli": rows[h].index("ישראלית")}
        amounts = _amount_blocks(rows, h, cols)
    if amounts:
        if max(v for a in amounts.values() for v in a.values()) >= 1e6:
            amounts = {b: {k: v / 1e6 for k, v in a.items()} for b, a in amounts.items()}
        shares = {b: {k: v / sum(a.values()) for k, v in a.items()}
                  for b, a in amounts.items() if sum(a.values()) > 0}
    return list(cols), shares, amounts


def _oecd(title, rows):
    """(year, [(country, {income, expense, direct, total})]) in percent of
    GDP. A component the table lacks is None; a missing total is the sum."""
    h = next((i for i, r in enumerate(rows)
              if not any(TITLE.match(c) for c in r) and any("ישירה" in c for c in r)), None)
    if h is None:
        raise ValueError("oecd: header with 'ישירה' not found")
    hdr = rows[h]
    lab = next((j for j, c in enumerate(hdr) if "מדינ" in c), None)
    if lab is None:
        lab = cbs.best_col(rows[h + 1:], lambda c: bool(HEB.search(c)))
    if lab is None:
        raise ValueError("oecd: country column not found")
    cols = {}
    for j, c in enumerate(hdr):
        if j == lab or not c:
            continue
        if "ישירה" in c:
            cols.setdefault("direct", j)
        elif "הוצא" in c:
            cols.setdefault("expense", j)
        elif "הכנס" in c:
            cols.setdefault("income", j)
        elif c.startswith(("סך", 'ס"')):
            cols.setdefault("total", j)
    items = []
    for r in rows[h + 1:]:
        name = cbs.cell(r, lab)
        vals = {k: cbs.val(r, cols[k]) if k in cols else None
                for k in ("income", "expense", "direct", "total")}
        if vals["total"] is None:
            parts = [v for k, v in vals.items() if k != "total" and v is not None]
            vals["total"] = sum(parts) if parts else None
        if not name or vals["total"] is None or not re.search(r"[א-תA-Z]", name):
            continue
        items.append((name, vals))
    return _title_year(title), items, len(cols)


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    tabs = _tables(frames)
    if "series" not in tabs:
        raise ValueError("series table (סך ההטבות במס לעידוד המו\"פ) not found in any table input")
    rel = cbs.latest_release(frames["releases"])

    kpis, charts, tables, labels, flags = {}, {}, {}, {}, {}
    insights = []

    def add(key, text):
        if text:
            insights.append({"id": key, "text_he": text})

    # ── yearly series ────────────────────────────────────────────────────
    s = _series(tabs["series"][1])
    tot = s["total"]
    years = sorted(tot)
    ly = years[-1]
    last = tot[ly]
    share = s["share"]
    if not share and s["gdp"]:
        share = {y: tot[y] / s["gdp"][y] for y in years if s["gdp"].get(y)}
    charts["trend"] = {
        "x": [str(y) for y in years],
        "preferred": [_r1(s["preferred"].get(y)) for y in years],
        "special": [_r1(s["special"].get(y)) for y in years],
        "total": [_r1(tot[y]) for y in years],
        "share": [_r3(share[y] * 100) if y in share else None for y in years],
        "has_plans": bool(s["preferred"]) and bool(s["special"]),
        "has_share": bool(share),
    }
    tables["trend"] = [[str(y),
                        _m(s["preferred"][y]) if y in s["preferred"] else "",
                        _m(s["special"][y]) if y in s["special"] else "",
                        _m(tot[y]),
                        fmt.pct(share[y], 2) if y in share else ""] for y in years]
    labels["trend_note"] = (f"סך הטבות המס שניתנו לחברות כדי לעודד מחקר ופיתוח (מו\"פ), בכל שנה "
                            f"מ-{years[0]} עד {ly}, במיליוני ש\"ח, לפי מסלול ההטבה"
                            + (", וכאחוז מהתוצר של המגזר העסקי (הקו)." if share else "."))
    labels["trend_aria"] = f"הטבות מס לעידוד מו\"פ לפי שנה ומסלול, {years[0]} עד {ly}"

    kpis["total"] = {"value": round(last, 1), "display": _m(last), "tone": "brand"}
    labels["total_kpi"] = f"סך הטבות המס לעידוד מו\"פ ב-{ly} (מיליוני ש\"ח)"
    if len(years) >= 2:
        py = years[-2]
        ch = last / tot[py] - 1
        kpis["yoy"] = {"value": round(ch * 100, 1), "display": fmt.signed_pct(ch),
                       "tone": "info" if abs(ch) >= 0.03 else "brand"}
        labels["yoy_kpi"] = f"שינוי בסך ההטבות לעומת {py}"
        if ch >= 0.03:
            word = "עלייה"
        elif ch <= -0.03:
            word = "ירידה"
        else:
            word = None
        txt = f"סך הטבות המס לעידוד מו\"פ הגיע ב-{ly} ל-{_m(last)} מיליון ש\"ח"
        if word:
            txt += f", {word} של {fmt.pct(abs(ch))} לעומת {py} ({_m(tot[py])} מיליון)"
        else:
            txt += f", כמעט ללא שינוי לעומת {py} ({_m(tot[py])} מיליון)"
        if len(years) >= 4 and tot[years[0]] > 0 and last / tot[years[0]] >= 1.5:
            txt += f". זה {_times(last, tot[years[0]])} מהסכום ב-{years[0]}"
        add("trend", txt + ".")
        # Which plan drove the change.
        if s["preferred"].get(py) is not None and s["special"].get(py) is not None \
                and ly in s["special"] and ly in s["preferred"]:
            d_tot = last - tot[py]
            d_spc = s["special"][ly] - s["special"][py]
            d_prf = s["preferred"][ly] - s["preferred"][py]
            spc_from = f"מ-{_m(s['special'][py])} ל-{_m(s['special'][ly])} מיליון ש\"ח"
            if abs(d_tot) >= 100 and d_tot * d_spc > 0 and 0.6 <= d_spc / d_tot <= 1:
                verb = "הגידול" if d_tot > 0 else "הירידה"
                add("driver", f"רוב {verb} בהטבות ב-{ly} בא מהמסלול של מפעל טכנולוגי מועדף מיוחד, "
                              f"שבו ההטבות {'עלו' if d_spc > 0 else 'ירדו'} {spc_from} "
                              f"({_m(abs(d_spc))} מתוך {_m(abs(d_tot))} מיליון של {verb}).")
            elif abs(d_spc) >= 100 and abs(d_prf) >= 50 and d_spc * d_prf < 0:
                add("driver", f"ב-{ly} ההטבות במסלול מפעל טכנולוגי מועדף מיוחד "
                              f"{'עלו' if d_spc > 0 else 'ירדו'} {spc_from}, ובמסלול מפעל טכנולוגי "
                              f"מועדף הן {'עלו' if d_prf > 0 else 'ירדו'} ב-{_m(abs(d_prf))} מיליון.")
    if ly in share:
        sh = share[ly]
        kpis["gdp"] = {"value": round(sh * 100, 2), "display": fmt.pct(sh, 2), "tone": "brand"}
        labels["gdp_kpi"] = f"ההטבות כאחוז מהתוצר של המגזר העסקי, {ly}"
        prev = [share[y] for y in years[:-1] if y in share]
        py = years[-2] if len(years) >= 2 else None
        if py in share:
            txt = f"ב-{ly} הסתכמו ההטבות ב-{fmt.pct(sh, 2)} מהתוצר של המגזר העסקי"
            if len(prev) >= 3 and sh > max(prev):
                first = min(y for y in years if y in share)
                txt += f", השיעור הגבוה ביותר מאז {first} (לעומת {fmt.pct(share[py], 2)} ב-{py})."
                add("gdp", txt)
            elif abs(sh - share[py]) >= 0.0002:
                add("gdp", txt + f", לעומת {fmt.pct(share[py], 2)} ב-{py}.")

    # Innovation Authority grants beside the tax benefits.
    gy = sorted(y for y in s["grant"] if y in tot)
    flags["grants"] = len(gy) >= 1
    if flags["grants"]:
        charts["grants"] = {"x": [str(y) for y in gy], "tax": [_r1(tot[y]) for y in gy],
                            "grant": [_r1(s["grant"][y]) for y in gy]}
        tables["grants"] = [[str(y), _m(tot[y]), _m(s["grant"][y])] for y in gy]
        labels["grants_note"] = ("הטבות המס (תמיכה עקיפה) לצד המענקים של רשות החדשנות (תמיכה "
                                 "ישירה), במיליוני ש\"ח.")
        labels["grants_aria"] = f"הטבות מס לעומת מענקי רשות החדשנות, {gy[0]} עד {gy[-1]}"
        g = gy[-1]
        if s["grant"][g] > 0 and tot[g] / s["grant"][g] >= 1.2:
            add("grants", f"ב-{g} היו הטבות המס {_times(tot[g], s['grant'][g])} ממענקי רשות החדשנות: "
                          f"{_m(tot[g])} מיליון ש\"ח לעומת {_m(s['grant'][g])} מיליון.")

    # ── plans: who gets the special plan ─────────────────────────────────
    plans = _plans(tabs["plans"][1]) if "plans" in tabs else {}
    flags["plans"] = all(p in plans for p in PLANS)
    if flags["plans"]:
        charts["plans"] = {"measures": [lab for _, _, lab in MEASURES],
                           "names": [PLAN_NAMES[p] for p in PLANS],
                           "series": [[_r1(plans[p][k] * 100) if plans[p][k] is not None else None
                                       for k, _, _ in MEASURES] for p in PLANS]}
        tables["plans"] = [[lab] + [fmt.pct(plans[p][k]) if plans[p][k] is not None else ""
                                    for p in PLANS] for k, _, lab in MEASURES]
        labels["plans_note"] = ("איזה חלק מהחברות שקיבלו הטבה, מההטבות, מההוצאה למו\"פ ומהמועסקים "
                                "שייך לכל מסלול, באחוזים.")
        labels["plans_aria"] = "חלוקת החברות, ההטבות, ההוצאה למו\"פ והמועסקים לפי מסלול"
        c, b = plans["special"]["companies"], plans["special"]["benefits"]
        if c is not None and b is not None:
            kpis["special"] = {"value": round(b * 100, 1), "display": fmt.pct(b), "tone": "brand"}
            labels["special_kpi"] = (f"מההטבות הלכו למפעל טכנולוגי מועדף מיוחד, שהם {fmt.pct(c)} "
                                     f"מהחברות")
            if b - c >= 0.2:
                add("concentration", f"החברות במסלול מפעל טכנולוגי מועדף מיוחד הן רק {fmt.pct(c)} "
                                     f"מהחברות שקיבלו הטבת מס לעידוד מו\"פ, אבל קיבלו {fmt.pct(b)} "
                                     f"מסך ההטבות.")

    # ── firm size ────────────────────────────────────────────────────────
    size = _size(tabs["size"][1]) if "size" in tabs else {}
    sz_tot = {k: v for k, v in size.get("total", {}).items() if k != "total"}
    flags["size"] = len(sz_tot) >= 3
    if flags["size"]:
        cats = [k for k in SIZE_ORDER if k in sz_tot]
        grand = size["total"].get("total") or sum(sz_tot.values())
        has_split = all(p in size and size[p] for p in PLANS)
        charts["size"] = {"names": [SIZE_NAMES[k] for k in cats], "split": has_split,
                          "total": [_r1(sz_tot[k]) for k in cats],
                          "preferred": [_r1(size.get("preferred", {}).get(k, 0.0)) for k in cats],
                          "special": [_r1(size.get("special", {}).get(k, 0.0)) for k in cats]}
        tables["size"] = [[SIZE_NAMES[k], _m(sz_tot[k]), fmt.pct(sz_tot[k] / grand) if grand else ""]
                          + ([_m(size["preferred"].get(k, 0.0)), _m(size["special"].get(k, 0.0))]
                             if has_split else []) for k in cats]
        labels["size_cols"] = (["גודל החברה", "מיליוני ש\"ח", "חלק מהסך"]
                               + ([PLAN_NAMES["preferred"], PLAN_NAMES["special"]] if has_split else []))
        labels["size_note"] = "הטבות המס לפי מספר המועסקים בחברה, במיליוני ש\"ח, לפי מסלול."
        labels["size_aria"] = "הטבות מס לעידוד מו\"פ לפי גודל החברה"
        lead = max(cats, key=lambda k: (sz_tot[k], k))
        if grand and sz_tot[lead] / grand >= 0.4 and lead != "none":
            who = {"small": "החברות הקטנות (עד 49 מועסקים)", "mid": "החברות הבינוניות (50-249 מועסקים)",
                   "large": "החברות הגדולות (250 מועסקים ומעלה)"}[lead]
            txt = (f"{who} קיבלו {fmt.pct(sz_tot[lead] / grand)} מהטבות המס "
                   f"({_m(sz_tot[lead])} מיליון ש\"ח)")
            if "small" in sz_tot and lead != "small":
                txt += f", והחברות הקטנות (עד 49 מועסקים) {fmt.pct(sz_tot['small'] / grand)}"
            add("size", txt + ".")

    # ── sectors ──────────────────────────────────────────────────────────
    if "sector" in tabs:
        sec_year, sec_total, sec = _sector(*tabs["sector"])
    else:
        sec_year, sec_total, sec = None, None, []
    flags["sector"] = len(sec) >= 3
    if flags["sector"]:
        sec = sorted(sec, key=lambda t: (t[0].startswith("אחר"), -t[1], t[0]))
        st = sec_total or sum(t[1] for t in sec)
        charts["sector"] = {"names": [t[0] for t in sec], "preferred": [_r1(t[2]) for t in sec],
                            "special": [_r1(t[3]) for t in sec]}
        tables["sector"] = [[t[0], _m(t[1]), fmt.pct(t[1] / st) if st else "", _m(t[2]), _m(t[3])]
                            for t in sec]
        labels["sector_note"] = ("הטבות המס לפי ענף ועוצמה טכנולוגית"
                                 + (f", {sec_year}" if sec_year else "")
                                 + ", במיליוני ש\"ח, לפי מסלול.")
        labels["sector_aria"] = "הטבות מס לעידוד מו\"פ לפי ענף"
        named = [t for t in sec if not t[0].startswith("אחר")]
        if st and len(named) >= 2:
            a, b = named[0], named[1]
            if a[1] / st >= 0.3:
                add("sector", f"הענף שקיבל הכי הרבה הטבות מס הוא \"{a[0]}\": {_m(a[1])} מיליון ש\"ח, "
                              f"{fmt.pct(a[1] / st)} מהסך. אחריו \"{b[0]}\" עם {fmt.pct(b[1] / st)}.")

    # ── startups by field ────────────────────────────────────────────────
    if "startups" in tabs:
        su_year, su = _startups(*tabs["startups"])
    else:
        su_year, su = None, []
    flags["startups"] = len(su) >= 3
    if flags["startups"]:
        ssum = sum(v for _, v in su)
        scale = 100 if ssum <= 1.0001 else 100 / ssum
        su = sorted(su, key=lambda t: (t[0].startswith("אחר"), -t[1], t[0]))
        charts["startups"] = {"names": [n for n, _ in su], "values": [_r1(v * scale) for _, v in su]}
        tables["startups"] = [[n, fmt.pct_of(v * scale)] for n, v in su]
        labels["startups_note"] = ("איך מתחלקות הטבות המס שקיבלו חברות הזנק (סטארט-אפים) לפי תחום "
                                   "הפעילות" + (f", {su_year}" if su_year else "") + ", באחוזים.")
        labels["startups_aria"] = "הטבות מס לחברות הזנק לפי תחום פעילות"
        a = su[0]
        if a[1] * scale >= 20 and not a[0].startswith("אחר"):
            add("startups", f"בקרב חברות ההזנק, תחום {a[0]} קיבל את הנתח הגדול ביותר מהטבות המס: "
                            f"{fmt.pct_of(a[1] * scale)}, ואחריו {su[1][0]} עם "
                            f"{fmt.pct_of(su[1][1] * scale)}.")

    # ── ownership ────────────────────────────────────────────────────────
    own_keys, own_sh, own_amt = _owner(tabs["owner"][1]) if "owner" in tabs else ([], {}, {})
    blocks = [b for b in ("total", "preferred", "special") if b in own_sh]
    flags["owner"] = "total" in own_sh
    if flags["owner"]:
        charts["owner"] = {"names": [PLAN_NAMES[b] for b in blocks],
                           "owners": [OWN_NAMES[k] for k in own_keys],
                           "series": [[_r1(own_sh[b][k] * 100) for b in blocks] for k in own_keys]}
        tables["owner"] = [[PLAN_NAMES[b]] + [
            (f"{fmt.pct(own_sh[b][k])} ({_m(own_amt[b][k])} מיליון)" if b in own_amt
             else fmt.pct(own_sh[b][k])) for k in own_keys] for b in blocks]
        labels["owner_cols"] = ["מסלול"] + [OWN_NAMES[k] for k in own_keys]
        labels["owner_note"] = ("מי מקבל את ההטבות: חברות בנות של קבוצות חברות זרות לעומת חברות "
                                "ישראליות, באחוזים מכל מסלול"
                                + (" (ובטבלה גם במיליוני ש\"ח)." if own_amt else "."))
        labels["owner_aria"] = "הטבות מס לעידוד מו\"פ לפי סוג בעלות ומסלול"
        f = own_sh["total"]["foreign"]
        if f >= 0.4:
            txt = f"{fmt.pct(f)} מהטבות המס הלכו לחברות בנות של קבוצות חברות זרות"
            if "total" in own_amt:
                txt += f" ({_m(own_amt['total']['foreign'])} מיליון ש\"ח)"
            if "special" in own_sh:
                txt += f", ובמסלול מפעל טכנולוגי מועדף מיוחד {fmt.pct(own_sh['special']['foreign'])}"
            add("owner", txt + ".")

    # ── OECD ─────────────────────────────────────────────────────────────
    # Several OECD charts in one edition (2022 had four): the one with the
    # most support components wins; one whose labels are gone is skipped
    # while another parses, and raises when none does.
    oe_year, oe, oe_n, oe_err = None, [], 0, None
    for t, rows in tabs.get("oecd_all", []):
        try:
            y, items, n = _oecd(t, rows)
        except ValueError as e:
            oe_err = oe_err or e
            continue
        if len(items) >= 3 and n > oe_n:
            oe_year, oe, oe_n = y, items, n
    if tabs.get("oecd_all") and not oe and oe_err:
        raise oe_err
    flags["oecd"] = len(oe) >= 3
    if flags["oecd"]:
        oe = sorted(oe, key=lambda t: (-t[1]["total"], t[0]))
        isr = next((n for n, _ in oe if n.startswith("ישראל")), None)
        comps = [k for k in ("income", "expense", "direct")
                 if any(v[k] is not None for _, v in oe)]
        comp_names = {"income": "הטבת מס על בסיס ההכנסות", "expense": "הטבת מס על בסיס ההוצאה למו\"פ",
                      "direct": "מענקים ישירים"}
        charts["oecd"] = {"names": [n for n, _ in oe], "israel": isr,
                          "comps": [comp_names[k] for k in comps],
                          "series": [[_r3(v[k] or 0.0) for _, v in oe] for k in comps]}
        tables["oecd"] = [[n] + [fmt.num_he(v[k] or 0.0, 2) for k in comps] + [fmt.num_he(v["total"], 2)]
                          for n, v in oe]
        labels["oecd_cols"] = ["מדינה"] + [comp_names[k] for k in comps] + ["סך הכל"]
        labels["oecd_note"] = ("התמיכה הממשלתית במו\"פ של המגזר העסקי כאחוז מהתמ\"ג"
                               + (f", {oe_year}" if oe_year else "") + ": "
                               + fmt.join_he(comp_names[k] for k in comps) + ".")
        labels["oecd_aria"] = "תמיכה ממשלתית במו\"פ כאחוז מהתמ\"ג במדינות OECD נבחרות"
        if isr:
            iv = dict(oe)[isr]
            avg = next((v for n, v in oe if n.startswith("OECD")), None)
            countries = [n for n, _ in oe if n[:1] and HEB.match(n)]
            txt = (f"בהשוואה בינלאומית{' (' + str(oe_year) + ')' if oe_year else ''}, "
                   f"התמיכה הממשלתית במו\"פ בישראל הגיעה ל-{fmt.num_he(iv['total'], 2)}% "
                   f"מהתמ\"ג, המקום ה-{countries.index(isr) + 1} מתוך {len(countries)} המדינות בתרשים")
            if avg:
                txt += f" (ממוצע OECD: {fmt.num_he(avg['total'], 2)}%)"
            if iv["income"] and iv["total"] > 0 and iv["income"] / iv["total"] >= 0.6:
                txt += (f". רובה ({fmt.pct(iv['income'] / iv['total'], 0)}) ניתנת כהטבת מס על בסיס "
                        f"ההכנסות")
            add("oecd", txt + ".")

    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "url": rel["PAGE_URL"],
               "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["lede"] = (f"כמה מס חוסכות חברות שעוסקות במחקר ופיתוח בישראל בזכות ההטבות של החוק "
                      f"לעידוד השקעות הון, ומי מקבל אותן: לפי מסלול, גודל חברה, ענף ובעלות. "
                      f"הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים "
                      f"עם כל הודעה חדשה. הנתון האחרון הוא לשנת {ly}: הטבות של {_m(last)} מיליון ש\"ח"
                      + (f", {fmt.pct(share[ly], 2)} מהתוצר של המגזר העסקי." if ly in share else "."))
    summary = (f"הטבות מס לחברות מו\"פ בישראל לפי נתוני הלמ\"ס: {_m(last)} מיליון ש\"ח ב-{ly}"
               + (f", {fmt.pct(share[ly], 2)} מהתוצר העסקי" if ly in share else "")
               + ", לפי מסלול, גודל חברה, ענף ובעלות.")
    desc = (f"כמה הטבות מס מקבלות חברות הייטק ומו\"פ בישראל: {_m(last)} מיליון ש\"ח ב-{ly}"
            + (f" ({fmt.signed_pct(last / tot[years[-2]] - 1)} בשנה)" if len(years) >= 2 else "")
            + ". מפעל טכנולוגי מועדף, ענפים ובעלות.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0]}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "הטבות מס למו\"פ: מפעל טכנולוגי מועדף | הלמ\"ס",
                "description": desc,
                "name": "הטבות מס לחברות העוסקות במחקר ופיתוח",
                "alternate_names": ["הטבות מס למחקר ופיתוח", "מפעל טכנולוגי מועדף",
                                    "מפעל טכנולוגי מועדף מיוחד", "תמריצי מס למו\"פ",
                                    "חוק עידוד השקעות הון הייטק"],
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
