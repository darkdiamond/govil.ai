"""יצוא ויבוא סחורות לפי סוג הובלה: CBS's yearly release on goods trade by
mode of transport (sea, air, land, self-propelled).

Every edition so far (2023-2026) carries five tables, each with five years
of imports and exports in million $:

  mode     ערך היבוא והיצוא סחורות לפי סוג הובלה     totals per mode
  air_c    ארצות הסחר לפי הובלת סחורות אווירית       countries, air
  sea_c    ארצות הסחר לפי הובלת סחורות ימית          countries, sea
  air_ch   ... לפי סוג הובלה ופרקים, Air Transport   HS chapters, air
  sea_ch   ... לפי סוג הובלה ופרקים, Sea Transport   HS chapters, sea

CBS renumbers tables between editions in other releases, so every stem
(t1..t8, three spare) is optional and each table is recognised by its title,
never by its stem. The mode table is required (it holds the grand totals);
any other table missing drops its sections. A recognised table whose header
labels ("Imports", "Exports", the year row, "Grand Total"/"Total", "ISO")
are gone raises: the layout changed and a human should look. Data rows
(countries, chapters, modes) are found by pattern and may come and go.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^לוח\s*\d+[א-ת]?\s*\.?\s*-")
ISO = re.compile(r"^[A-Z]{2}$")
CODE2 = re.compile(r"^\d{2}$")
CODE = re.compile(r"^\d{1,3}$")
CONTINENTS = {"Europe": "אירופה", "Asia": "אסיה", "Africa": "אפריקה",
              "America": "אמריקה", "Oceania": "אוקיאניה"}
MODES = (("sea", "ימית"), ("air", "אווירית"), ("land", "יבשתית"), ("other", "הנעה עצמית ואחרת"))
MODE_EN = {"Sea": "sea", "Air": "air", "Land": "land", "Self-propelled": "other"}
TOP_C = 12
TOP_CH = 10
TOP_P = 10
MOVERS = 5
TREND_CH = 5
SHORT = 28
# Insight-card order; at most MAX_TOP there, the others show in their section.
PRIORITY = ("air_exports", "sea_imports", "change", "air_dest", "sea_origin", "chapter_shift",
            "movers", "air_chapter", "partners", "peak", "sea_chapter")
MAX_TOP = 8
FLAT = 0.005  # a change under 0.5% reads as "stable"


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows[:6]:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _mode_of(rows):
    """"air" / "sea" from a chapter table's subtitle (English, then Hebrew)."""
    head = " ".join(" ".join(r) for r in rows[:6])
    if "Air Transport" in head or "אוויר" in head:
        return "air"
    if "Sea Transport" in head or "ימית" in head:
        return "sea"
    return None


def _kind(title, rows):
    if "ארצות הסחר" in title:
        if "אווירית" in title:
            return "air_c"
        if "ימית" in title:
            return "sea_c"
        return None
    if "סוג הובלה" in title and "פרקים" in title:
        m = _mode_of(rows)
        return f"{m}_ch" if m else None
    if "סוג הובלה" in title and "ערך" in title:
        return "mode"
    return None


def _tables(frames):
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        k = _kind(_title(rows), rows)
        if k and k not in out:
            out[k] = (n, rows)
    return out


# ── reading one table ────────────────────────────────────────────────────


def _layout(rows, name, total_en, total_he):
    """Header columns of an imports/exports × years table."""
    h = cbs.row_with(rows, "Imports", name=name)
    imp_c = cbs.col_after(rows[h], "Imports")
    exp_c = cbs.col_after(rows[h], "Exports", imp_c + 1)
    yr = None
    for i in range(h, min(h + 4, len(rows))):
        if sum(1 for c in rows[i] if cbs.YEAR.match(c)) >= 2:
            yr = i
            break
    if yr is None:
        raise ValueError(f"{name}: year header row not found")
    imp = [(j, int(c)) for j, c in enumerate(rows[yr]) if cbs.YEAR.match(c) and imp_c <= j < exp_c]
    exp = [(j, int(c)) for j, c in enumerate(rows[yr]) if cbs.YEAR.match(c) and j >= exp_c]
    if not imp or not exp:
        raise ValueError(f"{name}: imports/exports year columns not found")
    t = None
    for i in range(yr + 1, len(rows)):
        if total_en in rows[i]:
            t = i
            break
    if t is None:
        raise ValueError(f"{name}: header label {total_en!r} not found")
    en = cbs.col_after(rows[t], total_en)
    he = cbs.col_after(rows[t], total_he)
    vcols = {j for j, _ in imp + exp}
    return {"yr": yr, "imp": imp, "exp": exp, "total": t, "en": en, "he": he, "vcols": vcols}


def _vals(row, lay):
    imp = {y: cbs.val(row, j) for j, y in lay["imp"]}
    exp = {y: cbs.val(row, j) for j, y in lay["exp"]}
    return imp, exp


def _has_vals(row, lay):
    return any(cbs.val(row, j) is not None for j in lay["vcols"])


def _he_label(s):
    """Collapse CBS's letter-spaced headings: "א ס י ה" → "אסיה"."""
    parts = s.split(" ")
    if len(parts) > 1 and all(len(p) == 1 for p in parts):
        return "".join(parts)
    return s


def _modes(rows, name):
    lay = _layout(rows, name, "Grand Total", "סך כולל")
    total = _vals(rows[lay["total"]], lay)
    modes = {}
    for r in rows[lay["total"] + 1:]:
        if not _has_vals(r, lay):
            continue
        en = cbs.cell(r, lay["en"])
        key = next((k for p, k in MODE_EN.items() if en.startswith(p)), None)
        if key and key not in modes:
            modes[key] = _vals(r, lay)
    return lay, total, modes


def _countries(rows, name):
    lay = _layout(rows, name, "Grand Total", "סך כולל")
    iso_c = cbs.col_after(rows[lay["yr"]], "ISO")
    total = _vals(rows[lay["total"]], lay)
    countries, conts = {}, {}
    for r in rows[lay["total"] + 1:]:
        if not _has_vals(r, lay):
            continue
        iso = cbs.cell(r, iso_c)
        if ISO.match(iso):
            if iso not in countries:
                imp, exp = _vals(r, lay)
                countries[iso] = {"he": cbs.cell(r, lay["he"]) or iso, "imp": imp, "exp": exp}
            continue
        en = cbs.cell(r, lay["en"]).replace(" ", "")
        if en in CONTINENTS and en not in conts:
            imp, exp = _vals(r, lay)
            conts[en] = {"he": _he_label(cbs.cell(r, lay["he"])) or CONTINENTS[en],
                         "imp": imp, "exp": exp}
    return lay, total, countries, conts


def _short(s):
    """A chapter's axis label: its first clause, cut at a comma under SHORT."""
    s = s.split(";")[0].strip()
    if len(s) <= SHORT:
        return s.rstrip(",")
    out = ""
    for part in s.split(","):
        cand = (out + "," + part) if out else part
        if len(cand.strip()) > SHORT and out:
            break
        out = cand
    out = out.strip().rstrip(",")
    return out if len(out) <= SHORT + 12 else out[:SHORT].rstrip() + "…"


def _chapters(rows, name):
    """HS chapters: a block starts at a 2-digit code; its label can span
    rows, and the numbers sit on the block's first row that has any."""
    lay = _layout(rows, name, "Total", "סך הכל")
    total = _vals(rows[lay["total"]], lay)
    code_c = cbs.best_col(rows[lay["total"] + 1:], lambda v: bool(CODE2.match(v)),
                          exclude=lay["vcols"])
    chapters = {}
    if code_c is None:
        return lay, total, chapters
    cur = None
    for r in rows[lay["total"] + 1:]:
        code = cbs.cell(r, code_c)
        if CODE2.match(code):
            cur = {"code": code, "he": [], "imp": None, "exp": None}
            if code not in chapters:
                chapters[code] = cur
        if cur is None or cur["imp"] is not None:
            continue
        he = cbs.cell(r, lay["he"])
        if he:
            cur["he"].append(he)
        if _has_vals(r, lay):
            cur["imp"], cur["exp"] = _vals(r, lay)
    out = {}
    for code, c in chapters.items():
        if c["imp"] is None:
            continue
        label = " ".join(c["he"]).strip() or f"פרק {code}"
        out[code] = {"he": label, "short": _short(label), "imp": c["imp"], "exp": c["exp"]}
    return lay, total, out


# ── small helpers ────────────────────────────────────────────────────────


def _g(d, y):
    v = d.get(y) if d else None
    return v if v is not None else None


def _bn(v):
    return round(v / 1000, 2) if v is not None else None


def _m(v):
    return round(v, 1) if v is not None else None


def _bn_he(v):
    return f"{v / 1000:,.1f}"


def _m_he(v):
    return "–" if v is None else fmt.num_he(v, 1)


def _money(v):
    """A million-$ amount in words: billions from 1,000 up."""
    if abs(v) >= 1000:
        return f"{v / 1000:,.1f} מיליארד דולר"
    return f"{fmt.int_he(v)} מיליון דולר"


def _share(part, whole):
    if part is None or not whole:
        return None
    return part / whole


def _chg(a, b):
    """Relative change from b to a, or None."""
    if a is None or b is None or b == 0:
        return None
    return a / b - 1


def _dir_word(c, up="עלה", down="ירד", flat="נותר יציב"):
    if c is None:
        return None
    if abs(c) < FLAT:
        return flat
    return up if c > 0 else down


def _top(items, key, n):
    """Top n of {k: item} by key (desc), ties by k."""
    ranked = sorted(((key(v), k) for k, v in items.items() if key(v) is not None),
                    key=lambda t: (-t[0], t[1]))
    return [k for v, k in ranked if v > 0][:n]


def _sum(*vs):
    vs = [v for v in vs if v is not None]
    return sum(vs) if vs else None


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "mode" not in tabs:
        raise ValueError("table by mode of transport (לוח ערך היבוא והיצוא לפי סוג הובלה) not found")
    mname, mrows = tabs["mode"]
    lay, total, modes = _modes(mrows, mname)
    years = sorted({y for _, y in lay["imp"]} & {y for _, y in lay["exp"]})
    if not years:
        raise ValueError(f"{mname}: no year has both imports and exports")
    ly = years[-1]
    py = years[-2] if len(years) > 1 else None
    t_imp, t_exp = total[0].get(ly), total[1].get(ly)
    if t_imp is None or t_exp is None:
        raise ValueError(f"{mname}: grand total for {ly} missing")

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── KPIs ─────────────────────────────────────────────────────────────
    exp_chg = _chg(t_exp, total[1].get(py)) if py else None
    imp_chg = _chg(t_imp, total[0].get(py)) if py else None
    kpis["exports"] = {"value": round(t_exp, 1), "display": _bn_he(t_exp),
                       "tone": "brand" if exp_chg is None or abs(exp_chg) < FLAT
                       else ("ok" if exp_chg > 0 else "warn")}
    kpis["imports"] = {"value": round(t_imp, 1), "display": _bn_he(t_imp), "tone": "brand"}
    labels["exports_kpi"] = f"יצוא סחורות ב-{ly} (מיליארדי דולרים)"
    labels["imports_kpi"] = f"יבוא סחורות ב-{ly} (מיליארדי דולרים)"
    air, sea = modes.get("air"), modes.get("sea")
    air_exp_sh = _share(_g(air[1], ly), t_exp) if air else None
    sea_imp_sh = _share(_g(sea[0], ly), t_imp) if sea else None
    if air_exp_sh is not None:
        kpis["air_exp"] = {"value": round(air_exp_sh * 100, 1), "display": fmt.pct(air_exp_sh),
                           "tone": "info"}
        labels["air_exp_kpi"] = f"מהיצוא נשלח בדרך האוויר ({ly})"
    if sea_imp_sh is not None:
        kpis["sea_imp"] = {"value": round(sea_imp_sh * 100, 1), "display": fmt.pct(sea_imp_sh),
                           "tone": "info"}
        labels["sea_imp_kpi"] = f"מהיבוא הגיע בדרך הים ({ly})"

    # ── mode over time ───────────────────────────────────────────────────
    present = [(k, he) for k, he in MODES if k in modes]
    flags["mode_trend"] = bool(air or sea)
    if flags["mode_trend"]:
        series = []
        for k, he in (("sea", "ימית"), ("air", "אווירית")):
            if k in modes:
                series.append({"name": f"יבוא, {he}", "data": [_bn(_g(modes[k][0], y)) for y in years]})
                series.append({"name": f"יצוא, {he}", "data": [_bn(_g(modes[k][1], y)) for y in years]})
        charts["mode_trend"] = {"x": [str(y) for y in years], "series": series}
        tables["mode_trend_cols"] = ["שנה"] + [s["name"] for s in series]
        tables["mode_trend"] = [[str(y)] + [("–" if s["data"][i] is None else f"{s['data'][i]:,.1f}")
                                            for s in series] for i, y in enumerate(years)]
        labels["mode_trend_note"] = (f"ערך היבוא והיצוא של סחורות בהובלה ימית ובהובלה אווירית, "
                                     f"במיליארדי דולרים, {years[0]} עד {ly}.")
        labels["mode_trend_aria"] = f"יבוא ויצוא לפי סוג הובלה, {years[0]} עד {ly}"

    # ── mode mix in the latest year ──────────────────────────────────────
    flags["mode_mix"] = len(present) >= 2
    if flags["mode_mix"]:
        mix = []
        rows_t = []
        for k, he in present:
            vi, ve = _g(modes[k][0], ly), _g(modes[k][1], ly)
            si, se = _share(vi, t_imp), _share(ve, t_exp)
            mix.append({"name": he, "data": [None if si is None else round(si * 100, 1),
                                             None if se is None else round(se * 100, 1)]})
            rows_t.append([he, _m_he(vi), "–" if si is None else fmt.pct(si),
                           _m_he(ve), "–" if se is None else fmt.pct(se)])
        rows_t.append(["סך הכל", _m_he(t_imp), fmt.pct(1), _m_he(t_exp), fmt.pct(1)])
        charts["mode_mix"] = {"cats": ["יבוא", "יצוא"], "series": mix}
        tables["mode_mix"] = rows_t
        labels["mode_mix_note"] = (f"איזה חלק מהיבוא ומהיצוא עבר בכל סוג הובלה ב-{ly}, "
                                   f"באחוזים מערך הסחר.")
        labels["mode_mix_aria"] = f"התפלגות היבוא והיצוא לפי סוג הובלה, {ly}"

    # mode insights
    sea_exp_sh = None
    if air_exp_sh is not None and sea:
        sea_exp_sh = _share(_g(sea[1], ly), t_exp)
        if sea_exp_sh is not None:
            if air_exp_sh > sea_exp_sh:
                add("air_exports", f"יותר מהיצוא נשלח בדרך האוויר מאשר בדרך הים: ב-{ly} עברו בהובלה "
                    f"אווירית {fmt.pct(air_exp_sh)} מערך יצוא הסחורות ({_bn_he(_g(air[1], ly))} מיליארד "
                    f"דולר), ובהובלה ימית {fmt.pct(sea_exp_sh)}.")
            else:
                add("air_exports", f"ב-{ly} נשלחו בדרך הים {fmt.pct(sea_exp_sh)} מערך יצוא הסחורות, "
                    f"ובדרך האוויר {fmt.pct(air_exp_sh)}.")
    if sea_imp_sh is not None and air:
        air_imp_sh = _share(_g(air[0], ly), t_imp)
        if air_imp_sh is not None and sea_imp_sh > air_imp_sh:
            # "the reverse" only when exports actually lean to air.
            flip = sea_exp_sh is not None and air_exp_sh > sea_exp_sh
            lead = "ביבוא התמונה הפוכה: " if flip else "ביבוא: "
            add("sea_imports", f"{lead}{fmt.pct(sea_imp_sh)} מערך יבוא הסחורות ב-{ly} "
                f"הגיע בדרך הים ({_bn_he(_g(sea[0], ly))} מיליארד דולר), ורק {fmt.pct(air_imp_sh)} "
                f"בדרך האוויר.")
    if exp_chg is not None and imp_chg is not None:
        def part(word, c, v):
            if abs(c) < FLAT:
                return f"{word} נותר יציב, {_bn_he(v)} מיליארד דולר"
            return f"{word} {_dir_word(c)} ב-{fmt.pct(abs(c))} ל-{_bn_he(v)} מיליארד דולר"
        add("change", f"לעומת {py}, ב-{ly} {part('יצוא הסחורות', exp_chg, t_exp)}, "
            f"ו{part('יבוא הסחורות', imp_chg, t_imp)}.")
    peak_y = max(years, key=lambda y: (total[1].get(y) or 0, -y))
    if (len(years) >= 3 and peak_y != ly and total[1].get(peak_y) and air
            and _g(air[1], peak_y) is not None):
        add("peak", f"שיא היצוא בשנים {years[0]}-{ly} נרשם ב-{peak_y}: "
            f"{_bn_he(total[1][peak_y])} מיליארד דולר, מהם {_bn_he(_g(air[1], peak_y))} מיליארד "
            f"בדרך האוויר.")

    # ── countries ────────────────────────────────────────────────────────
    ctry = {}
    for k in ("air", "sea"):
        if f"{k}_c" in tabs:
            n, rows = tabs[f"{k}_c"]
            _, ctot, cs, conts = _countries(rows, n)
            ctry[k] = {"tot": ctot, "cs": cs, "conts": conts}

    def cy(d, flow, y=ly):
        return _g(d[flow], y)

    # continents
    if ctry:
        cont_keys = [c for c in CONTINENTS if any(c in ctry[k]["conts"] for k in ctry)]
        flags["regions"] = len(cont_keys) >= 2
        if flags["regions"]:
            names = []
            for c in cont_keys:
                names.append(next(ctry[k]["conts"][c]["he"] for k in ctry if c in ctry[k]["conts"]))
            series, cols = [], ["יבשת"]
            for k, he in (("sea", "ימית"), ("air", "אווירית")):
                if k not in ctry:
                    continue
                for flow, fhe in (("imp", "יבוא"), ("exp", "יצוא")):
                    data = [_m(cy(ctry[k]["conts"][c], flow)) if c in ctry[k]["conts"] else None
                            for c in cont_keys]
                    series.append({"name": f"{fhe}, {he}", "data": data})
                    cols.append(f"{fhe}, {he}")
            charts["regions"] = {"names": names, "series": series}
            tables["regions_cols"] = cols
            tables["regions"] = [[names[i]] + [_m_he(s["data"][i]) for s in series]
                                 for i in range(len(names))]
            labels["regions_note"] = (f"ערך הסחר לפי יבשת ולפי סוג הובלה ב-{ly}, במיליוני דולרים. "
                                      f"הסחר עם ארצות שלא סווגו אינו כלול.")
            labels["regions_aria"] = f"יבוא ויצוא לפי יבשת וסוג הובלה, {ly}"
    else:
        flags["regions"] = False

    for k, he in (("air", "אווירית"), ("sea", "ימית")):
        key = f"{k}_countries"
        flags[key] = k in ctry and bool(ctry[k]["cs"])
        if not flags[key]:
            continue
        cs = ctry[k]["cs"]
        top = _top(cs, lambda d: _sum(cy(d, "imp"), cy(d, "exp")), TOP_C)
        flags[key] = len(top) >= 3
        if not flags[key]:
            continue
        charts[key] = {"names": [cs[i]["he"] for i in top],
                       "imp": [_m(cy(cs[i], "imp")) for i in top],
                       "exp": [_m(cy(cs[i], "exp")) for i in top]}
        tables[key] = [[cs[i]["he"], _m_he(cy(cs[i], "imp")), _m_he(cy(cs[i], "exp"))] for i in top]
        labels[f"{key}_note"] = (f"{len(top)} ארצות הסחר הגדולות בהובלה {he} ב-{ly}, לפי סך היבוא "
                                 f"והיצוא, במיליוני דולרים.")
        labels[f"{key}_aria"] = f"ארצות הסחר הגדולות בהובלה {he}, {ly}"

    # top destination / origin insights
    if "air" in ctry and ctry["air"]["cs"]:
        cs = ctry["air"]["cs"]
        at = ctry["air"]["tot"][1].get(ly)
        t1 = _top(cs, lambda d: cy(d, "exp"), 1)
        if t1 and at:
            d = cs[t1[0]]
            add("air_dest", f"{d['he']} היא יעד היצוא הגדול בדרך האוויר: {_money(cy(d, 'exp'))} "
                f"ב-{ly}, {fmt.pct(cy(d, 'exp') / at)} מהיצוא בהובלה אווירית.")
    if "sea" in ctry and ctry["sea"]["cs"]:
        cs = ctry["sea"]["cs"]
        st = ctry["sea"]["tot"][0].get(ly)
        t1 = _top(cs, lambda d: cy(d, "imp"), 1)
        if t1 and st:
            d = cs[t1[0]]
            add("sea_origin", f"{d['he']} היא מקור היבוא הגדול בדרך הים: {_money(cy(d, 'imp'))} "
                f"ב-{ly}, {fmt.pct(cy(d, 'imp') / st)} מהיבוא בהובלה ימית.")

    # partners: air vs sea per country
    flags["partners"] = "air" in ctry and "sea" in ctry
    if flags["partners"]:
        a, s = ctry["air"]["cs"], ctry["sea"]["cs"]
        isos = sorted(set(a) | set(s))
        tot = {}
        for i in isos:
            av = _sum(cy(a[i], "imp"), cy(a[i], "exp")) if i in a else None
            sv = _sum(cy(s[i], "imp"), cy(s[i], "exp")) if i in s else None
            tot[i] = (av or 0.0, sv or 0.0, (a.get(i) or s.get(i))["he"])
        top = _top(tot, lambda t: t[0] + t[1], TOP_P)
        flags["partners"] = len(top) >= 3
        if flags["partners"]:
            charts["partners"] = {"names": [tot[i][2] for i in top],
                                  "air": [round(tot[i][0], 1) for i in top],
                                  "sea": [round(tot[i][1], 1) for i in top]}
            tables["partners"] = [[tot[i][2], fmt.num_he(tot[i][0]), fmt.num_he(tot[i][1]),
                                   fmt.pct(tot[i][0] / (tot[i][0] + tot[i][1]))] for i in top]
            labels["partners_note"] = (f"סך הסחר (יבוא ויצוא) עם {len(top)} שותפות הסחר הגדולות "
                                       f"ב-{ly}, בחלוקה להובלה אווירית וימית, במיליוני דולרים.")
            labels["partners_aria"] = f"שותפות הסחר הגדולות לפי סוג הובלה, {ly}"
            shares = {i: tot[i][0] / (tot[i][0] + tot[i][1]) for i in top}
            hi = max(top, key=lambda i: (shares[i], i))
            lo = min(top, key=lambda i: (shares[i], i))
            if shares[hi] - shares[lo] >= 0.3:
                add("partners", f"בין {len(top)} שותפות הסחר הגדולות, עם {tot[hi][2]} עובר "
                    f"{fmt.pct(shares[hi])} מהסחר בדרך האוויר, ועם {tot[lo][2]} רק "
                    f"{fmt.pct(shares[lo])}.")

        # movers: total exports (air + sea) by country, ly vs py
        flags["movers"] = False
        if py:
            ch = {}
            for i in isos:
                cur = _sum(cy(a[i], "exp") if i in a else None, cy(s[i], "exp") if i in s else None)
                prev = _sum(cy(a[i], "exp", py) if i in a else None,
                            cy(s[i], "exp", py) if i in s else None)
                if cur is not None and prev is not None:
                    ch[i] = (cur - prev, cur, prev, (a.get(i) or s.get(i))["he"])
            up = [i for i in sorted(ch, key=lambda i: (-ch[i][0], i)) if ch[i][0] > 0][:MOVERS]
            down = [i for i in sorted(ch, key=lambda i: (ch[i][0], i)) if ch[i][0] < 0][:MOVERS]
            sel = up + list(reversed(down))
            flags["movers"] = len(up) >= 2 and len(down) >= 2
            if flags["movers"]:
                charts["movers"] = {"names": [ch[i][3] for i in sel],
                                    "delta": [round(ch[i][0], 1) for i in sel]}
                tables["movers"] = [[ch[i][3], fmt.num_he(ch[i][2]), fmt.num_he(ch[i][1]),
                                     (fmt.num_he(ch[i][0]) if ch[i][0] >= 0
                                      else fmt.MINUS + fmt.num_he(-ch[i][0]))] for i in sel]
                labels["movers_note"] = (f"הארצות שהיצוא אליהן (בים ובאוויר יחד) עלה או ירד הכי הרבה "
                                         f"ב-{ly} לעומת {py}, במיליוני דולרים.")
                labels["movers_aria"] = f"שינוי ביצוא לפי ארץ יעד, {py} לעומת {ly}"
                labels["movers_cols"] = ["ארץ", str(py), str(ly), "שינוי"]
                u0, d0 = up[0], down[0]
                add("movers", f"ב-{ly} גדל היצוא ל{ch[u0][3]} יותר מלכל ארץ אחרת: תוספת של "
                    f"{_money(ch[u0][0])} לעומת {py}. היצוא ל{ch[d0][3]} ירד יותר מכולן: "
                    f"{_money(-ch[d0][0])} פחות.")
    else:
        flags["movers"] = False

    # ── chapters ─────────────────────────────────────────────────────────
    chap = {}
    for k in ("air", "sea"):
        if f"{k}_ch" in tabs:
            n, rows = tabs[f"{k}_ch"]
            hlay, htot, hs = _chapters(rows, n)
            chap[k] = {"tot": htot, "hs": hs, "years": sorted({y for _, y in hlay["exp"]})}
    for k, he in (("air", "אווירית"), ("sea", "ימית")):
        key = f"{k}_chapters"
        flags[key] = False
        if k not in chap:
            continue
        hs = chap[k]["hs"]
        top = _top(hs, lambda d: _sum(cy(d, "imp"), cy(d, "exp")), TOP_CH)
        flags[key] = len(top) >= 3
        if not flags[key]:
            continue
        charts[key] = {"names": [hs[c]["short"] for c in top], "full": [hs[c]["he"] for c in top],
                       "imp": [_m(cy(hs[c], "imp")) for c in top],
                       "exp": [_m(cy(hs[c], "exp")) for c in top]}
        tables[key] = [[f"{c} {hs[c]['he']}", _m_he(cy(hs[c], "imp")), _m_he(cy(hs[c], "exp"))]
                       for c in top]
        labels[f"{key}_note"] = (f"{len(top)} פרקי הסחורות (לפי סיווג המכס) הגדולים בהובלה {he} "
                                 f"ב-{ly}, לפי סך היבוא והיצוא, במיליוני דולרים.")
        labels[f"{key}_aria"] = f"פרקי הסחורות הגדולים בהובלה {he}, {ly}"
        tot_e = chap[k]["tot"][1].get(ly)
        t1 = _top(hs, lambda d: cy(d, "exp"), 1)
        if t1 and tot_e:
            c = hs[t1[0]]
            add(f"{k}_chapter", f"פרק הסחורות הגדול ביצוא בהובלה {he} הוא {c['short']}: "
                f"{_money(cy(c, 'exp'))} ב-{ly}, {fmt.pct(cy(c, 'exp') / tot_e)} מהיצוא בהובלה {he}.")

    # air export chapters over time
    flags["chapter_trend"] = False
    if "air" in chap:
        hs = chap["air"]["hs"]
        cyrs = chap["air"]["years"]
        top = _top(hs, lambda d: cy(d, "exp"), TREND_CH)
        flags["chapter_trend"] = len(top) >= 2 and len(cyrs) >= 3
        if flags["chapter_trend"]:
            charts["chapter_trend"] = {"x": [str(y) for y in cyrs],
                                       "series": [{"name": hs[c]["short"],
                                                   "data": [_m(_g(hs[c]["exp"], y)) for y in cyrs]}
                                                  for c in top]}
            tables["chapter_trend_cols"] = ["שנה"] + [hs[c]["short"] for c in top]
            tables["chapter_trend"] = [[str(y)] + [_m_he(_g(hs[c]["exp"], y)) for c in top]
                                       for y in cyrs]
            labels["chapter_trend_note"] = (f"היצוא בהובלה אווירית של {len(top)} פרקי הסחורות "
                                            f"הגדולים, {cyrs[0]} עד {cyrs[-1]}, במיליוני דולרים.")
            labels["chapter_trend_aria"] = f"יצוא אווירי לפי פרק סחורות, {cyrs[0]} עד {cyrs[-1]}"
            y0, y1 = cyrs[0], cyrs[-1]
            moves = {c: _chg(_g(hs[c]["exp"], y1), _g(hs[c]["exp"], y0)) for c in top}
            moves = {c: v for c, v in moves.items() if v is not None}
            if moves:
                c = max(moves, key=lambda c: (abs(moves[c]), c))
                if abs(moves[c]) >= 0.25:
                    a0, a1 = _g(hs[c]["exp"], y0), _g(hs[c]["exp"], y1)
                    add("chapter_shift", f"היצוא בדרך האוויר של {hs[c]['short']} "
                        f"{'ירד' if moves[c] < 0 else 'עלה'} מ-{_money(a0)} ב-{y0} ל-{_money(a1)} "
                        f"ב-{y1}, {'ירידה' if moves[c] < 0 else 'עלייה'} של {fmt.pct(abs(moves[c]))}.")

    by_id = {i["id"]: i for i in insights}
    top_ins = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top_ins}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    # ── text ─────────────────────────────────────────────────────────────
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    lede = (f"איך סחורות נכנסות לישראל ויוצאות ממנה: בדרך הים, בדרך האוויר או בדרך היבשה, "
            f"לאן ומאילו ארצות, ואילו סחורות. הנתונים מתוך ההודעה השנתית של הלשכה המרכזית "
            f"לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. ב-{ly} הסתכם יצוא הסחורות "
            f"ב-{_bn_he(t_exp)} מיליארד דולר והיבוא ב-{_bn_he(t_imp)} מיליארד דולר")
    if air_exp_sh is not None and sea_imp_sh is not None:
        lede += (f"; {fmt.pct(air_exp_sh)} מהיצוא נשלח באוויר, ו-{fmt.pct(sea_imp_sh)} מהיבוא "
                 f"הגיע בים")
    labels["lede"] = lede + "."
    summary = (f"יבוא ויצוא סחורות לפי סוג הובלה, לפי נתוני הלמ\"ס: ב-{ly} יצוא של {_bn_he(t_exp)} "
               f"ויבוא של {_bn_he(t_imp)} מיליארד דולר, לפי הובלה ימית, אווירית ויבשתית, ארצות ופרקי "
               f"סחורות.")
    desc = f"איך סחורות מגיעות לישראל ויוצאות ממנה: ב-{ly} יצוא של {_bn_he(t_exp)} מיליארד דולר"
    if air_exp_sh is not None:
        desc += f", {fmt.pct(air_exp_sh)} ממנו באוויר"
    desc += f", ויבוא של {_bn_he(t_imp)} מיליארד. לפי ארץ ופרק."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0]}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "יבוא ויצוא סחורות לפי סוג הובלה: ים ואוויר | הלמ\"ס",
                "description": desc,
                "name": "יצוא ויבוא סחורות לפי סוג הובלה",
                "alternate_names": ["יבוא ויצוא בהובלה ימית ואווירית", "סחר החוץ לפי סוג הובלה",
                                    "יצוא בדרך האוויר", "יבוא בדרך הים"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top_ins,
        "callouts": callouts,
        "labels": labels,
        "release": release,
        "flags": flags,
        "year": str(ly),
    }
