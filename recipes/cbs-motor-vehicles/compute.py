"""כלי רכב מנועיים בישראל: CBS's yearly motor-vehicle release.

The release is a set of chart-data sheets ("תרשים N - ..."), and their
NUMBERS MOVE between editions (the hybrid/EV chart was t2 in 2024 and t3 in
2025-2026; motorization t8, t9, t11). So every table input (t1..t13, all
optional) is read with `cbs.grid`, and each chart is found by its TITLE
text, not by its stem:

  motor   רמת המינוע בישראל (no OECD)       vehicles per 1,000 people, 2000-
  oecd    רמת המינוע ... OECD               per 1,000 people, Israel vs OECD
  hybrid  מספר כלי רכב היברידיים וחשמליים    counts by year since 2015
  fleet   מצבת ... לפי סוג רכב וסוג הנעה     fuel mix % per vehicle type
  newfuel פרטיים חדשים ... לפי סוג הנעה      fuel mix % of new private cars
  buses   אוטובוסים לפי סוג הנעה             buses by fuel, counts by year
  owners  פרטיים חדשים ... לפי סוג בעלות     new private cars by ownership
  evown   חשמליים פרטיים חדשים ... בעלות     new private EVs by ownership
  origin  כלי רכב מנועיים, לפי ארץ ייצור     % by country of manufacture
  evorig  פרטיים חשמליים לפי ארץ ייצור       EV fleet vs new EVs by country
  evmake  פרטיים חשמליים, לפי יצרן           EV fleet by make
  safety  מערכות בטיחות                      % of new cars with each system
  colors  צבע כלי הרכב                       % by colour, new vs fleet

A title that is found but whose header labels are gone raises (the layout
changed: a human should look). A chart missing from an edition drops its
section. motor and hybrid are required: every edition so far has them.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*-\s*")
HEB = re.compile("[א-ת]")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
OTHER_NAMES = ("אחר", "אחר ולא ידוע")
# Insight-card order; at most MAX_TOP there, the others go to their section.
PRIORITY = ("ev", "evnew", "motor", "oecd", "evorig", "lease", "buses", "fleet", "ev_long",
            "petrol", "evown", "origin", "evmake", "safety", "colors")
MAX_TOP = 8


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    if "מערכות בטיחות" in t:
        return "safety"
    if "צבע" in t:
        return "colors"
    if "רמת המינוע" in t:
        return "oecd" if "OECD" in t else "motor"
    if "היברידיים וחשמליים" in t:
        return "hybrid"
    if "אוטובוסים" in t and "הנעה" in t:
        return "buses"
    if "מצבת" in t and "סוג רכב" in t and "הנעה" in t:
        return "fleet"
    if "ארץ ייצור" in t:
        return "evorig" if "חשמלי" in t else "origin"
    if "חשמלי" in t and "יצרן" in t:
        return "evmake"
    if "חדשים" in t and "בעלות" in t:
        if "הנעה" in t:
            return None  # the 2024 combined fuel × ownership chart
        return "evown" if "חשמלי" in t else "owners"
    if "חדשים" in t and "הנעה" in t:
        return "newfuel"
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


def _year_row(rows, start=0, need=2, name="table"):
    """First row with `need`+ cells that are bare years."""
    for i in range(start, len(rows)):
        if sum(1 for c in rows[i] if cbs.YEAR.match(c)) >= need:
            return i
    raise ValueError(f"{name}: year header row not found")


def _labelled(rows, start, ncol_from=1):
    """Data rows after `start`: a Hebrew label in column 0. Stops at
    nothing; rows without a label or numbers are skipped."""
    out = []
    for r in rows[start:]:
        label = cbs.cell(r, 0)
        if not label or not HEB.search(label) or label.startswith("["):
            continue
        out.append((label, r))
    return out


def _pct100(values):
    """Percent values on 0-100, whatever scale the sheet used (fractions
    summing to 1 or percents summing to 100)."""
    vals = [v for v in values if v is not None]
    if vals and max(vals) <= 1.0001 and sum(vals) <= 1.0001 + 1e-9:
        return [None if v is None else v * 100 for v in values]
    return list(values)


def _r1(v):
    return None if v is None else round(v, 1)


def _r2(v):
    return None if v is None else round(v, 2)


def _is_other(name):
    return name in OTHER_NAMES or name.startswith("אחר")


# ── table parsers ────────────────────────────────────────────────────────


def _motor(rows):
    h = cbs.row_with(rows, "סך כל סוגי כלי הרכב", name="motor", contains=True)
    tot = cbs.col_after(rows[h], "סך כל סוגי כלי הרכב", 0, contains=True)
    priv = cbs.col_after(rows[h], "פרטיים", 0, contains=True)
    out = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, 0))
        if y and cbs.val(r, tot) is not None:
            out[y] = {"total": cbs.val(r, tot), "private": cbs.val(r, priv)}
    return out


def _oecd(title, rows):
    h = cbs.row_with(rows, "1,000", name="oecd", contains=True)
    vcol = cbs.col_after(rows[h], "1,000", 1, contains=True)
    out = []
    for label, r in _labelled(rows, h + 1):
        v = cbs.val(r, vcol)
        if v is not None:
            out.append((label, v))
    years = [int(y) for y in YEAR_IN.findall(title)]
    return out, (years[-1] if years else None)


def _hybrid(rows):
    h = cbs.row_with(rows, "חשמלי", name="hybrid")
    cols = {"reg": cbs.col_after(rows[h], "היברידי רגיל", 0),
            "plug": cbs.col_after(rows[h], "היברידי נטען", 0),
            "hyb": cbs.col_after(rows[h], "סך היברידי", 0, contains=True),
            "ev": cbs.col_after(rows[h], "חשמלי", 0)}
    out = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, 0))
        if y is None:
            continue
        v = {k: cbs.val(r, j) for k, j in cols.items()}
        if v["ev"] is not None or v["hyb"] is not None:
            out[y] = v
    return out


def _fleet(title, rows):
    h = cbs.row_with(rows, "בנזין", name="fleet")
    fuels = [(j, c) for j, c in enumerate(rows[h]) if j > 0 and c and HEB.search(c)]
    if len(fuels) < 2:
        raise ValueError("fleet: fuel header columns not found")
    out = []
    for label, r in _labelled(rows, h + 1):
        vals = _pct100([cbs.val(r, j) for j, _ in fuels])
        if any(v is not None for v in vals):
            out.append((label, [v or 0.0 for v in vals]))
    years = [int(y) for y in YEAR_IN.findall(title)]
    return [c for _, c in fuels], out, (years[0] if years else None)


def _by_year_cols(rows, name):
    """Rows of labels × year columns (newfuel, buses)."""
    h = _year_row(rows, 0, 2, name)
    ycols = sorted(((_year(c), j) for j, c in enumerate(rows[h]) if _year(c)))
    out = []
    for label, r in _labelled(rows, h + 1):
        vals = [cbs.val(r, j) for _, j in ycols]
        if any(v is not None for v in vals):
            out.append((label, vals))
    return [y for y, _ in ycols], out


def _owners(rows, name):
    """{year: {ownership: count}} plus the ownership order, from the count
    block (a second block below repeats the years as shares)."""
    h = cbs.row_with(rows, "פרטית", name=name)
    tcol = next((j for j, c in enumerate(rows[h]) if c.startswith("סה")), None)
    if tcol is None:
        raise ValueError(f"{name}: total column not found")
    cats = [(j, c) for j, c in enumerate(rows[h]) if 0 < j < tcol and c and HEB.search(c)]
    out = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, 0))
        total = cbs.val(r, tcol)
        if y is None or total is None or total <= 1.0001 or y in out:
            continue
        out[y] = {"total": total, "cats": {c: (cbs.val(r, j) or 0.0) for j, c in cats}}
    return [c for _, c in cats], out


def _origin(rows):
    h = _year_row(rows, 0, 1, "origin")
    ycols = sorted(((_year(c), j) for j, c in enumerate(rows[h]) if _year(c)))
    if len(ycols) < 1:
        raise ValueError("origin: year columns not found")
    out = []
    for label, r in _labelled(rows, h + 1):
        vals = [cbs.val(r, j) for _, j in ycols]
        if vals[-1] is not None:
            out.append((label, vals))
    return [y for y, _ in ycols], out


def _evorig(rows):
    """{'fleet': [(country, count)], 'new': [...]}: blocks headed by a
    'סך כלי רכב' cell, the block named by its first cell."""
    heads = [i for i, r in enumerate(rows) if any(c == "סך כלי רכב" for c in r)]
    if not heads:
        raise ValueError("evorig: 'סך כלי רכב' header not found")
    out = {}
    for n, h in enumerate(heads):
        kind = "fleet" if "מצבת" in cbs.cell(rows[h], 0) else "new" if "חדש" in cbs.cell(rows[h], 0) else None
        if kind is None or kind in out:
            continue
        vcol = rows[h].index("סך כלי רכב")
        stop = heads[n + 1] if n + 1 < len(heads) else len(rows)
        items = []
        for r in rows[h + 1:stop]:
            label = next((c for c in r[:vcol] if c and HEB.search(c)), "")
            v = cbs.val(r, vcol)
            if not label:
                if v is not None and items:
                    break  # the block's total row
                continue
            if v is not None:
                items.append((label, v))
        if items:
            out[kind] = items
    return out


def _evmake(rows):
    h = cbs.row_with(rows, "סך כלי רכב", name="evmake")
    vcol = cbs.col_after(rows[h], "סך כלי רכב", 0)
    out = []
    for label, r in _labelled(rows, h + 1):
        v = cbs.val(r, vcol)
        if v is not None:
            out.append((label, v))
    return out


def _safety(rows):
    h = next((i for i, r in enumerate(rows)
              if sum(1 for c in r if "עלו לכביש" in c and YEAR_IN.search(c)) >= 2), None)
    if h is None:
        raise ValueError("safety: year header row not found")
    ycols = sorted((int(YEAR_IN.search(c).group()), j) for j, c in enumerate(rows[h])
                   if "עלו לכביש" in c and YEAR_IN.search(c))
    out = []
    for label, r in _labelled(rows, h + 1):
        vals = [cbs.val(r, j) for _, j in ycols]
        if all(v is not None for v in vals):
            out.append((label, vals))
    return [y for y, _ in ycols], out


def _colors(rows):
    h = cbs.row_with(rows, "צבעים", name="colors", contains=True)
    tcol = next(j for j, c in enumerate(rows[h]) if "צבעים" in c)
    cols = [(j, c) for j, c in enumerate(rows[h]) if 0 < j < tcol and c]
    out = {}
    for label, r in _labelled(rows, h + 1):
        kind = "new" if "לכביש" in label else "fleet" if "מצבת" in label else None
        if kind and kind not in out:
            vals = _pct100([cbs.val(r, j) for j, _ in cols])
            if any(v is not None for v in vals):
                out[kind] = (label, [v or 0.0 for v in vals])
    new_year = None
    if "new" in out:
        m = YEAR_IN.search(out["new"][0])
        new_year = int(m.group()) if m else None
    return [c for _, c in cols], out, new_year


# ── formatting ───────────────────────────────────────────────────────────


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _word(c, up="עלייה", down="ירידה"):
    return up if c > 0 else down


def _p(v, d=1):
    return fmt.pct_of(v, d)


def _pp(a, b):
    """'נקודות אחוז' difference text."""
    return f"{fmt.num_he(abs(a - b), 1)} נקודות אחוז"


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "motor" not in tabs:
        raise ValueError("motorization chart (רמת המינוע בישראל) not found in any table")
    if "hybrid" not in tabs:
        raise ValueError("hybrid/electric chart (היברידיים וחשמליים) not found in any table")

    motor = _motor(tabs["motor"][1])
    if not motor:
        raise ValueError("motor: no year rows")
    hybrid = _hybrid(tabs["hybrid"][1])
    if not hybrid:
        raise ValueError("hybrid: no year rows")
    my = sorted(motor)
    ly = my[-1]
    hy = sorted(hybrid)
    hly = hy[-1]

    oecd = _oecd(*tabs["oecd"]) if "oecd" in tabs else ([], None)
    fleet = _fleet(*tabs["fleet"]) if "fleet" in tabs else ([], [], None)
    newfuel = _by_year_cols(tabs["newfuel"][1], "newfuel") if "newfuel" in tabs else ([], [])
    buses = _by_year_cols(tabs["buses"][1], "buses") if "buses" in tabs else ([], [])
    owners = _owners(tabs["owners"][1], "owners") if "owners" in tabs else ([], {})
    evown = _owners(tabs["evown"][1], "evown") if "evown" in tabs else ([], {})
    origin = _origin(tabs["origin"][1]) if "origin" in tabs else ([], [])
    evorig = _evorig(tabs["evorig"][1]) if "evorig" in tabs else {}
    evmake = _evmake(tabs["evmake"][1]) if "evmake" in tabs else []
    safety = _safety(tabs["safety"][1]) if "safety" in tabs else ([], [])
    colors = _colors(tabs["colors"][1]) if "colors" in tabs else ([], {}, None)

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── motorization ─────────────────────────────────────────────────────
    m_last = motor[ly]
    charts["motor"] = {"x": [str(y) for y in my],
                       "total": [_r1(motor[y]["total"]) for y in my],
                       "private": [_r1(motor[y]["private"]) for y in my]}
    tables["motor"] = [[str(y), fmt.int_he(motor[y]["total"]),
                        fmt.int_he(motor[y]["private"]) if motor[y]["private"] is not None else ""]
                       for y in reversed(my)]
    prev_m = motor.get(ly - 1)
    m_chg = _chg(m_last["total"], prev_m["total"] if prev_m else None)
    kpis["motor"] = {"value": round(m_last["total"]), "display": fmt.int_he(m_last["total"]),
                     "tone": "brand"}
    labels["motor_kpi"] = f"כלי רכב לכל 1,000 תושבים, {ly}"
    if m_last["private"] is not None:
        kpis["private"] = {"value": round(m_last["private"]),
                           "display": fmt.int_he(m_last["private"]), "tone": "brand"}
        labels["private_kpi"] = f"כלי רכב פרטיים לכל 1,000 תושבים, {ly}"
    if len(my) >= 2:
        fy = my[0]
        c = _chg(m_last["total"], motor[fy]["total"])
        if c is not None:
            add("motor", f"ב-{ly} היו בישראל {fmt.int_he(m_last['total'])} כלי רכב לכל 1,000 "
                         f"תושבים, לעומת {fmt.int_he(motor[fy]['total'])} ב-{fy}: "
                         f"{_word(c)} של {fmt.pct(abs(c), 0)}"
                         + (f". בשנה האחרונה השיעור {'עלה' if m_chg > 0 else 'ירד'} ב-"
                            f"{fmt.pct(abs(m_chg))}" if m_chg else "") + ".")

    # ── OECD ─────────────────────────────────────────────────────────────
    o_items, o_year = oecd
    isr = next((v for n, v in o_items if n == "ישראל"), None)
    flags["oecd"] = isr is not None and len(o_items) >= 3
    if flags["oecd"]:
        o_sorted = sorted(o_items, key=lambda kv: (kv[1], kv[0]))
        charts["oecd"] = {"names": [n for n, _ in o_sorted], "values": [_r1(v) for _, v in o_sorted]}
        tables["oecd"] = [[n, fmt.int_he(v)] for n, v in sorted(o_items, key=lambda kv: (-kv[1], kv[0]))]
        others = [v for n, v in o_items if n != "ישראל"]
        yr = f" ({o_year})" if o_year else ""
        labels["oecd_note"] = (f"כלי רכב לכל 1,000 תושבים בישראל ובמדינות OECD שהלמ\"ס בחרה "
                               f"להשוואה{yr}. ישראל מודגשת.")
        labels["oecd_aria"] = f"רמת המינוע בישראל ובמדינות OECD נבחרות{yr}"
        if others and isr < min(others):
            top_n, top_v = max(((n, v) for n, v in o_items), key=lambda kv: (kv[1], kv[0]))
            add("oecd", f"רמת המינוע בישראל נמוכה מזו של כל {len(others)} מדינות OECD "
                        f"בהשוואה{yr}: {fmt.int_he(isr)} כלי רכב לכל 1,000 תושבים, לעומת "
                        f"{fmt.int_he(min(others))} עד {fmt.int_he(top_v)} בהן (הגבוהה: {top_n}).")

    # ── hybrid + EV ──────────────────────────────────────────────────────
    h_last = hybrid[hly]
    charts["hybrid"] = {"x": [str(y) for y in hy],
                        "reg": [hybrid[y]["reg"] for y in hy],
                        "plug": [hybrid[y]["plug"] for y in hy],
                        "ev": [hybrid[y]["ev"] for y in hy]}
    tables["hybrid"] = [[str(y), fmt.int_he(hybrid[y]["reg"] or 0), fmt.int_he(hybrid[y]["plug"] or 0),
                         fmt.int_he(hybrid[y]["ev"] or 0)] for y in reversed(hy)]
    h_prev = hybrid.get(hly - 1)
    ev_chg = _chg(h_last["ev"], h_prev["ev"] if h_prev else None)
    if h_last["ev"] is not None:
        kpis["ev"] = {"value": int(h_last["ev"]), "display": fmt.int_he(h_last["ev"]),
                      "tone": "ok" if ev_chg and ev_chg > 0 else "warn" if ev_chg is not None else "info"}
        labels["ev_kpi"] = f"כלי רכב חשמליים, {hly}"
    hyb_total = h_last["hyb"] if h_last["hyb"] is not None else (h_last["reg"] or 0) + (h_last["plug"] or 0)
    kpis["hybrid"] = {"value": int(hyb_total), "display": fmt.int_he(hyb_total), "tone": "brand"}
    labels["hybrid_kpi"] = f"כלי רכב היברידיים (רגיל ונטען), {hly}"
    if ev_chg is not None and h_last["ev"]:
        h_prev2 = hybrid.get(hly - 2)
        prev_chg = _chg(h_prev["ev"], h_prev2["ev"] if h_prev2 else None)
        tail = ""
        if prev_chg is not None and prev_chg - ev_chg >= 0.10 and ev_chg > 0:
            tail = f". קצב הגידול האט: ב-{hly - 1} הגידול היה {fmt.pct(prev_chg, 0)}"
        add("ev", f"מספר כלי הרכב החשמליים {'עלה' if ev_chg > 0 else 'ירד'} ל-"
                  f"{fmt.int_he(h_last['ev'])} ב-{hly}, {_word(ev_chg, 'גידול', 'ירידה')} של "
                  f"{fmt.pct(abs(ev_chg), 0)} בשנה" + tail + ".")
    first_ev = next((y for y in hy if hybrid[y]["ev"]), None)
    if first_ev is not None and first_ev != hly and h_last["ev"] and hybrid[first_ev]["ev"]:
        mult = h_last["ev"] / hybrid[first_ev]["ev"]
        if mult >= 3 and h_last["plug"] and hybrid[first_ev]["plug"]:
            add("ev_long", f"מאז {first_ev} גדל מספר כלי הרכב החשמליים פי {fmt.int_he(mult)} "
                           f"(מ-{fmt.int_he(hybrid[first_ev]['ev'])} ל-{fmt.int_he(h_last['ev'])}), "
                           f"ומספר ההיברידיים הנטענים פי "
                           f"{fmt.int_he(h_last['plug'] / hybrid[first_ev]['plug'])}.")
    labels["hybrid_note"] = (f"מספר כלי הרכב ההיברידיים (רגיל ונטען) והחשמליים בכל שנה מאז {hy[0]}, "
                             f"כל סוגי הרכב.")
    labels["hybrid_aria"] = f"כלי רכב היברידיים וחשמליים, {hy[0]} עד {hly}"

    # ── fleet mix by vehicle type ────────────────────────────────────────
    f_fuels, f_rows, f_year = fleet
    flags["fleet"] = len(f_rows) >= 2
    if flags["fleet"]:
        charts["fleet"] = {"fuels": f_fuels, "types": [n for n, _ in f_rows],
                           "series": [[_r2(vals[k]) for _, vals in f_rows] for k in range(len(f_fuels))]}
        tables["fleet"] = [[n] + [_p(v) for v in vals] for n, vals in f_rows]
        yr = f" ({f_year})" if f_year else ""
        labels["fleet_note"] = (f"איך מתחלקת מצבת כלי הרכב{yr} בכל סוג רכב לפי סוג ההנעה, באחוזים.")
        labels["fleet_aria"] = f"מצבת כלי הרכב לפי סוג רכב וסוג הנעה{yr}"
        labels["fleet_cols"] = ["סוג רכב"] + f_fuels
        idx = {f: k for k, f in enumerate(f_fuels)}
        priv = next(((n, v) for n, v in f_rows if "פרטי" in n), None)
        hk, ek = idx.get("היברידי"), idx.get("חשמל")
        if priv and hk is not None and ek is not None:
            hyb_top = max(f_rows, key=lambda nv: (nv[1][hk], nv[0]))
            txt = (f"בכלי הרכב הפרטיים{yr} {_p(priv[1][ek])} חשמליים ו-{_p(priv[1][hk])} "
                   f"היברידיים")
            if hyb_top[0] != priv[0] and hyb_top[1][hk] >= 30:
                txt += (f", ואילו מבין כלי הרכב מסוג {hyb_top[0]} ההיברידיים הם כבר "
                        f"{_p(hyb_top[1][hk])}")
            add("fleet", txt + ".")

    # ── new private cars by fuel ─────────────────────────────────────────
    nf_years, nf_rows = newfuel
    flags["newfuel"] = bool(nf_years) and len(nf_rows) >= 2
    if flags["newfuel"]:
        n = len(nf_years)
        cols = [_pct100([vals[k] for _, vals in nf_rows]) for k in range(n)]
        share = {name: [cols[k][i] for k in range(n)] for i, (name, _) in enumerate(nf_rows)}
        order = sorted(share, key=lambda f: (-(share[f][-1] or 0), f))
        charts["newfuel"] = {"x": [str(y) for y in nf_years], "fuels": order,
                             "series": [[_r2(v) for v in share[f]] for f in order]}
        tables["newfuel"] = [[f] + [_p(v) if v is not None else "" for v in share[f]] for f in order]
        labels["newfuel_cols"] = ["סוג הנעה"] + [str(y) for y in nf_years]
        labels["newfuel_note"] = (f"החלק של כל סוג הנעה מכלי הרכב הפרטיים החדשים שעלו לכביש בכל שנה, "
                                  f"{nf_years[0]} עד {nf_years[-1]}, באחוזים.")
        labels["newfuel_aria"] = f"כלי רכב פרטיים חדשים לפי סוג הנעה, {nf_years[0]} עד {nf_years[-1]}"
        evname = next((f for f in share if f.startswith("חשמל")), None)
        if evname and n >= 2 and share[evname][-1] is not None and share[evname][-2] is not None:
            a, b = share[evname][-1], share[evname][-2]
            peak_i = max(range(n), key=lambda k: (share[evname][k] or 0, k))
            kpis["evnew"] = {"value": round(a, 1), "display": _p(a),
                             "tone": "ok" if a - b >= 1 else "warn" if a - b <= -1 else "brand"}
            labels["evnew_kpi"] = f"חלק החשמליים מהרכב הפרטי החדש, {nf_years[-1]}"
            if abs(a - b) >= 1:
                txt = (f"חלקם של החשמליים מכלי הרכב הפרטיים החדשים {'עלה' if a > b else 'ירד'} "
                       f"מ-{_p(b)} ב-{nf_years[-2]} ל-{_p(a)} ב-{nf_years[-1]}")
                lead = order[0]
                if lead != evname:
                    txt += f". הנפוץ ביותר ברכב חדש: {lead}, {_p(share[lead][-1])}"
                if peak_i not in (n - 1, n - 2) and a < b:
                    txt += f" (השיא היה ב-{nf_years[peak_i]}: {_p(share[evname][peak_i])})"
                add("evnew", txt + ".")
        petrol = next((f for f in share if f.startswith("בנזין")), None)
        if petrol and n >= 3 and share[petrol][0] and share[petrol][-1] is not None:
            d = share[petrol][-1] - share[petrol][0]
            if d <= -5:
                add("petrol", f"חלקו של הבנזין ברכב הפרטי החדש ירד מ-{_p(share[petrol][0])} ב-"
                              f"{nf_years[0]} ל-{_p(share[petrol][-1])} ב-{nf_years[-1]}.")

    # ── buses ────────────────────────────────────────────────────────────
    b_years, b_rows = buses
    flags["buses"] = bool(b_years) and len(b_rows) >= 2
    if flags["buses"]:
        b_order = sorted(b_rows, key=lambda nv: (-(nv[1][-1] or 0), nv[0]))
        charts["buses"] = {"x": [str(y) for y in b_years], "fuels": [nm for nm, _ in b_order],
                           "series": [vals for _, vals in b_order]}
        tables["buses"] = [[str(y)] + [fmt.int_he(vals[k]) if vals[k] is not None else ""
                                       for _, vals in b_order] for k, y in reversed(list(enumerate(b_years)))]
        labels["buses_cols"] = ["שנה"] + [nm for nm, _ in b_order]
        labels["buses_note"] = f"מספר האוטובוסים לפי סוג הנעה, {b_years[0]} עד {b_years[-1]}."
        labels["buses_aria"] = f"אוטובוסים לפי סוג הנעה, {b_years[0]} עד {b_years[-1]}"
        el = next(((nm, v) for nm, v in b_rows if nm.startswith("חשמל")), None)
        tot_last = sum(v[-1] or 0 for _, v in b_rows)
        tot_first = sum(v[0] or 0 for _, v in b_rows)
        if el and tot_last and tot_first and el[1][-1] is not None and el[1][0] is not None \
                and len(b_years) >= 2:
            s1, s0 = el[1][-1] / tot_last, el[1][0] / tot_first
            if s1 - s0 >= 0.01:
                add("buses", f"האוטובוסים החשמליים: {fmt.int_he(el[1][-1])} ב-{b_years[-1]}, "
                             f"{fmt.pct(s1)} מהאוטובוסים, לעומת {fmt.int_he(el[1][0])} "
                             f"({fmt.pct(s0)}) ב-{b_years[0]}.")

    # ── new private cars by ownership (+ EVs) ────────────────────────────
    o_cats, o_by = owners
    flags["owners"] = bool(o_by) and len(o_cats) >= 2
    if flags["owners"]:
        oy = sorted(o_by)
        charts["owners"] = {"x": [str(y) for y in oy], "cats": o_cats,
                            "series": [[round(o_by[y]["cats"][c]) for y in oy] for c in o_cats]}
        tables["owners"] = [[str(y)] + [fmt.int_he(o_by[y]["cats"][c]) for c in o_cats]
                            + [fmt.int_he(o_by[y]["total"])] for y in reversed(oy)]
        labels["owners_cols"] = ["שנה"] + o_cats + ["סה\"כ"]
        labels["owners_note"] = ("כמה כלי רכב פרטיים חדשים עלו לכביש בכל שנה, לפי מי שרשום כבעלים: "
                                 "אדם פרטי, חברת ליסינג, חברה או השכרה.")
        labels["owners_aria"] = f"כלי רכב פרטיים חדשים לפי סוג בעלות, {oy[0]} עד {oy[-1]}"
        last = o_by[oy[-1]]
        kpis["newcars"] = {"value": round(last["total"]), "display": fmt.int_he(last["total"]),
                           "tone": "brand"}
        labels["newcars_kpi"] = f"כלי רכב פרטיים חדשים שעלו לכביש, {oy[-1]}"
        lease = next((c for c in o_cats if "ליסינג" in c or "החכר" in c), None)
        if lease and len(oy) >= 2:
            s1 = last["cats"][lease] / last["total"]
            s0 = o_by[oy[0]]["cats"][lease] / o_by[oy[0]]["total"]
            if abs(s1 - s0) >= 0.02:
                add("lease", f"חברות הליסינג רשמו {fmt.pct(s1)} מכלי הרכב הפרטיים החדשים ב-{oy[-1]} "
                             f"({fmt.int_he(last['cats'][lease])} כלי רכב), לעומת {fmt.pct(s0)} "
                             f"ב-{oy[0]}.")
    e_cats, e_by = evown
    common = sorted(set(e_by) & set(o_by))
    flags["evown"] = flags["owners"] and bool(common) and bool(e_cats)
    if flags["evown"]:
        cats = [c for c in o_cats if c in e_cats]
        charts["evown"] = {"cats": cats, "years": [str(y) for y in common],
                           "series": [[_r1(e_by[y]["cats"][c] / o_by[y]["cats"][c] * 100)
                                       if o_by[y]["cats"][c] else None for c in cats] for y in common]}
        tables["evown"] = [[c] + [f"{fmt.int_he(e_by[y]['cats'][c])} ({_p(e_by[y]['cats'][c] / o_by[y]['cats'][c] * 100)})"
                                  if o_by[y]["cats"][c] else "" for y in common] for c in cats]
        labels["evown_cols"] = ["סוג בעלות"] + [str(y) for y in common]
        labels["evown_note"] = ("איזה חלק מכלי הרכב הפרטיים החדשים בכל סוג בעלות היה חשמלי. "
                                "בטבלה גם מספר החשמליים.")
        labels["evown_aria"] = "חלק החשמליים מהרכב הפרטי החדש לפי סוג בעלות"
        y = common[-1]
        sh = {c: e_by[y]["cats"][c] / o_by[y]["cats"][c] for c in cats if o_by[y]["cats"][c] >= 1000}
        if len(sh) >= 2:
            hi = max(sh, key=lambda c: (sh[c], c))
            lo = min(sh, key=lambda c: (sh[c], c))
            if sh[hi] - sh[lo] >= 0.05:
                add("evown", f"ב-{y} {fmt.pct(sh[hi])} מכלי הרכב הפרטיים החדשים בסוג הבעלות "
                             f"\"{hi}\" היו חשמליים, לעומת {fmt.pct(sh[lo])} בסוג \"{lo}\".")

    # ── country of manufacture ───────────────────────────────────────────
    og_years, og_rows = origin
    flags["origin"] = bool(og_years) and len(og_rows) >= 3
    if flags["origin"]:
        cols = [_pct100([vals[k] for _, vals in og_rows]) for k in range(len(og_years))]
        rows_ = [(nm, [cols[k][i] for k in range(len(og_years))]) for i, (nm, _) in enumerate(og_rows)]
        rows_.sort(key=lambda nv: (_is_other(nv[0]), -(nv[1][-1] or 0), nv[0]))
        charts["origin"] = {"names": [nm for nm, _ in rows_], "years": [str(y) for y in og_years],
                            "series": [[_r2(v[k]) for _, v in rows_] for k in range(len(og_years))]}
        tables["origin"] = [[nm] + [_p(x) if x is not None else "" for x in v] for nm, v in rows_]
        labels["origin_cols"] = ["ארץ ייצור"] + [str(y) for y in og_years]
        span = f"{og_years[0]} ו-{og_years[-1]}" if len(og_years) > 1 else str(og_years[0])
        labels["origin_note"] = f"החלק של כל ארץ ייצור מכלי הרכב המנועיים, {span}, באחוזים."
        labels["origin_aria"] = f"כלי רכב מנועיים לפי ארץ ייצור, {span}"
        named = [(nm, v) for nm, v in rows_ if not _is_other(nm) and v[0] is not None and v[-1] is not None]
        if len(og_years) >= 2 and named:
            lead = named[0]
            riser = max(named, key=lambda nv: (nv[1][-1] - nv[1][0], nv[0]))
            txt = f"{lead[0]} היא ארץ הייצור המובילה: {_p(lead[1][-1])} מכלי הרכב ב-{og_years[-1]}"
            if riser[1][-1] - riser[1][0] >= 2 and riser[0] != lead[0]:
                txt += (f". הזינוק הגדול ביותר: {riser[0]}, מ-{_p(riser[1][0])} ב-{og_years[0]} "
                        f"ל-{_p(riser[1][-1])}")
            add("origin", txt + ".")

    # ── EVs by country: fleet vs new ─────────────────────────────────────
    flags["evorig"] = "fleet" in evorig
    if flags["evorig"]:
        names = [nm for nm, _ in evorig["fleet"]]
        for nm, _ in evorig.get("new", []):
            if nm not in names:
                names.append(nm)
        fl = dict(evorig["fleet"])
        nw = dict(evorig.get("new", []))
        fs, ns = sum(fl.values()), sum(nw.values())
        names.sort(key=lambda nm: (_is_other(nm), -fl.get(nm, 0), nm))
        charts["evorig"] = {"names": names, "has_new": bool(nw),
                            "fleet": [_r1(fl.get(nm, 0) / fs * 100) if fs else None for nm in names],
                            "new": [_r1(nw.get(nm, 0) / ns * 100) if ns else None for nm in names]}
        tables["evorig"] = [[nm, fmt.int_he(fl.get(nm, 0)), _p(fl.get(nm, 0) / fs * 100) if fs else ""]
                            + ([fmt.int_he(nw.get(nm, 0)), _p(nw.get(nm, 0) / ns * 100)] if ns else [])
                            for nm in names]
        labels["evorig_cols"] = (["ארץ ייצור", "במצבת", "% מהמצבת"]
                                 + (["חדשים", "% מהחדשים"] if ns else []))
        labels["evorig_note"] = ("מאיפה מגיעים כלי הרכב הפרטיים החשמליים: כל המצבת לעומת אלה שעלו "
                                 "לכביש בשנה האחרונה, באחוזים.")
        labels["evorig_aria"] = "כלי רכב פרטיים חשמליים לפי ארץ ייצור"
        top = names[0]
        if fs and fl.get(top, 0) / fs >= 0.4:
            txt = f"{fmt.pct(fl[top] / fs, 0)} מכלי הרכב הפרטיים החשמליים בישראל יוצרו ב{top}"
            if ns and top in nw:
                txt += f", ומבין החשמליים החדשים של השנה האחרונה {fmt.pct(nw[top] / ns, 0)}"
            add("evorig", txt + ".")

    # ── EVs by make ──────────────────────────────────────────────────────
    named = sorted([(nm, v) for nm, v in evmake if not _is_other(nm)], key=lambda kv: (-kv[1], kv[0]))
    rest = sum(v for nm, v in evmake if _is_other(nm))
    flags["evmake"] = len(named) >= 3
    if flags["evmake"]:
        top = named[:15]
        rest += sum(v for _, v in named[15:])
        total = sum(v for _, v in evmake)
        bars = top + ([("אחר", rest)] if rest else [])
        charts["evmake"] = {"names": [nm for nm, _ in bars], "values": [int(v) for _, v in bars]}
        tables["evmake"] = [[nm, fmt.int_he(v), fmt.pct(v / total) if total else ""] for nm, v in bars]
        labels["evmake_note"] = (f"כלי הרכב הפרטיים החשמליים במצבת לפי יצרן: {len(top)} היצרנים "
                                 f"הגדולים, והשאר ב\"אחר\".")
        labels["evmake_aria"] = "כלי רכב פרטיים חשמליים לפי יצרן"
        if total:
            a, b = named[0], named[1]
            add("evmake", f"{a[0]} מובילה את מצבת הרכב הפרטי החשמלי עם {fmt.int_he(a[1])} כלי רכב "
                          f"({fmt.pct(a[1] / total)}), ואחריה {b[0]} עם {fmt.int_he(b[1])} "
                          f"({fmt.pct(b[1] / total)}).")

    # ── safety systems ───────────────────────────────────────────────────
    s_years, s_rows = safety
    flags["safety"] = len(s_years) >= 2 and len(s_rows) >= 3
    if flags["safety"]:
        s_sorted = sorted(s_rows, key=lambda nv: (-nv[1][-1], nv[0]))
        charts["safety"] = {"names": [nm for nm, _ in s_sorted], "years": [str(y) for y in s_years],
                            "series": [[_r1(v[k]) for _, v in s_sorted] for k in range(len(s_years))]}
        tables["safety"] = [[nm] + [_p(x) for x in v] for nm, v in s_sorted]
        labels["safety_cols"] = ["מערכת"] + [f"עלו לכביש ב-{y}" for y in s_years]
        labels["safety_note"] = (f"באיזה אחוז מכלי הרכב הפרטיים שעלו לכביש ב-{s_years[0]} וב-"
                                 f"{s_years[-1]} הותקנה כל מערכת בטיחות.")
        labels["safety_aria"] = f"מערכות בטיחות בכלי רכב פרטיים חדשים, {s_years[0]} ו-{s_years[-1]}"
        riser = max(s_rows, key=lambda nv: (nv[1][-1] - nv[1][0], nv[0]))
        if riser[1][-1] - riser[1][0] >= 10:
            add("safety", f"המערכת שהתפשטה הכי מהר ברכב החדש: {riser[0]}, מ-{_p(riser[1][0])} מהרכבים "
                          f"שעלו לכביש ב-{s_years[0]} ל-{_p(riser[1][-1])} ב-{s_years[-1]}.")

    # ── colours ──────────────────────────────────────────────────────────
    c_names, c_rows, c_year = colors
    flags["colors"] = bool(c_names) and "fleet" in c_rows
    if flags["colors"]:
        fl = c_rows["fleet"][1]
        nw = c_rows["new"][1] if "new" in c_rows else None
        order = sorted(range(len(c_names)), key=lambda k: (-fl[k], c_names[k]))
        charts["colors"] = {"names": [c_names[k] for k in order],
                            "fleet": [_r1(fl[k]) for k in order],
                            "new": [_r1(nw[k]) for k in order] if nw else None}
        new_lbl = f"עלו לכביש ב-{c_year}" if c_year else "חדשים"
        labels["colors_new"] = new_lbl
        tables["colors"] = [[c_names[k], _p(fl[k])] + ([_p(nw[k])] if nw else []) for k in order]
        labels["colors_cols"] = ["צבע", "כל המצבת"] + ([new_lbl] if nw else [])
        labels["colors_note"] = "צבעי כלי הרכב הפרטיים, באחוזים: כל המצבת לעומת הרכבים החדשים."
        labels["colors_aria"] = "צבע כלי הרכב הפרטיים"
        k0 = order[0]
        txt = f"הצבע הנפוץ ברכב הפרטי הוא {c_names[k0]}: {_p(fl[k0])} מהמצבת"
        if nw:
            txt += (f" ו-{_p(nw[k0])} מהרכבים ש{new_lbl}" if c_year
                    else f" ו-{_p(nw[k0])} מהרכבים החדשים")
        add("colors", txt + ".")

    # The page's insight card holds the strongest findings; the rest show as
    # a callout in their own chart section.
    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    # ── text ─────────────────────────────────────────────────────────────
    labels["motor_note"] = (f"כמה כלי רכב יש בישראל לכל 1,000 תושבים, בכל שנה מאז {my[0]}: "
                            f"כל סוגי כלי הרכב, וכלי הרכב הפרטיים לבדם.")
    labels["motor_aria"] = f"רמת המינוע בישראל, {my[0]} עד {ly}"
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["lede"] = (f"כמה כלי רכב יש בישראל, כמה מהם חשמליים והיברידיים, מה קונים היום ומי קונה. "
                      f"הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים "
                      f"עם כל הודעה חדשה. הנתון האחרון הוא לשנת {ly}: "
                      f"{fmt.int_he(m_last['total'])} כלי רכב לכל 1,000 תושבים"
                      + (f", ו-{fmt.int_he(h_last['ev'])} כלי רכב חשמליים" if h_last["ev"] else "") + ".")

    summary = (f"מצבת כלי הרכב בישראל לפי נתוני הלמ\"ס: ב-{ly} {fmt.int_he(m_last['total'])} כלי רכב "
               f"לכל 1,000 תושבים, {fmt.int_he(h_last['ev'] or 0)} חשמליים ו-{fmt.int_he(hyb_total)} "
               f"היברידיים.")
    desc = (f"כמה כלי רכב חשמליים והיברידיים יש בישראל: {fmt.int_he(h_last['ev'] or 0)} חשמליים ב-{hly}, "
            f"{fmt.int_he(m_last['total'])} כלי רכב לכל 1,000 תושבים. רכב חדש, יצרנים ומינוע.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{min(my[0], hy[0])}/{max(ly, hly)}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "כלי רכב בישראל: חשמליים, היברידיים ומינוע | הלמ\"ס",
                "description": desc,
                "name": "כלי רכב מנועיים בישראל",
                "alternate_names": ["מצבת כלי הרכב בישראל", "רכבים חשמליים בישראל",
                                    "רמת המינוע בישראל", "מספר כלי הרכב בישראל"],
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
