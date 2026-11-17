"""יצואנים ויבואנים בישראל: CBS's yearly release on trade in goods by the
characteristics of the exporting and importing enterprises.

Each edition carries four tables, all split by employment size class
(0-9, 10-49, 50-249, 250+) and by imports / exports:

  n_ind  מספר עסקים, לפי ענף כלכלי     enterprises by industry section
  v_ind  הסחר בסחורות, לפי ענף כלכלי   trade value ($M) by industry section
  n_cty  מספר עסקים, לפי ארצות הסחר    enterprises trading with each country
  v_cty  הסחר בסחורות, לפי ארצות הסחר  trade value ($M) by country

CBS renumbers tables between editions, so every stem (t1..t7, three of them
spare, all optional) is classified by its TITLE, never by its stem. The
source keeps several editions (history_releases), and each edition is one
year, read from its "Imports and Exports, <year>" line: that gives the
year-over-year series. A recognised table whose header labels are gone
raises; a table missing from an edition drops what needs it.

The country table's Grand Total counts enterprise-country pairs (one
importer of two countries counts twice), so the number of enterprises comes
only from the industry table.
"""
import itertools
import re

import pandas as pd
from govlib import cbs, fmt

HEB = re.compile("[א-ת]")
YEAR_LINE = re.compile(r"(?:Imports and Exports|יבוא ויצוא),?\s*((?:19|20)\d\d)")
SECTION = re.compile(r"^[A-Z]$")
CODE = re.compile(r"^\d{3}$")
ISO = re.compile(r"^[A-Z]{2}$")
RELEASE = re.compile(r"(\d+)\s*/\s*(\d{4})")

SIZES = ("0-9", "10-49", "50-249", "250 +")
SIZE_HE = ("0-9 מועסקים", "10-49 מועסקים", "50-249 מועסקים", "250 מועסקים ומעלה")
SIDES = ("imp", "exp")

# ISIC sections: short Hebrew names for charts. An unknown letter falls back
# to the table's own Hebrew label.
SECTION_HE = {
    "A": "חקלאות, ייעור ודיג", "B": "כרייה וחציבה", "C": "תעשייה", "D": "חשמל וגז",
    "E": "מים, ביוב ופסולת", "F": "בינוי", "G": "מסחר סיטוני וקמעוני", "H": "תחבורה ואחסנה",
    "I": "אירוח ואוכל", "J": "מידע ותקשורת", "K": "פיננסים וביטוח", "L": "נדל\"ן",
    "M": "שירותים מקצועיים ומדעיים", "N": "שירותי ניהול ותמיכה", "O": "מינהל ציבורי",
    "P": "חינוך", "Q": "בריאות ורווחה", "R": "אמנות, בידור ופנאי", "S": "שירותים אחרים",
}
CONTINENT_HE = {"europe": "אירופה", "asia": "אסיה", "america": "אמריקה", "africa": "אפריקה",
                "oceania": "אוקיאניה"}
CONTINENT_ORDER = ("europe", "asia", "america", "africa", "oceania", "unclassified")
UNCLASSIFIED_HE = "ארצות לא מסווגות"
PRIORITY = ("conc_exp", "exporters_trend", "cty_exp", "ind_exp", "ind_imp", "cty_importers",
            "value_trend", "conc_imp", "big_trend", "importers_trend", "cty_imp", "ind_avg", "cty_move")
MAX_TOP = 8
TOP_IND = 10
TOP_CTY = 12
TOP_TREND = 6


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows[:4]:
        for c in r:
            if c.startswith("לוח"):
                return c
    return ""


def _kind(t):
    by_ind = "ענף כלכלי" in t
    by_cty = "ארצות" in t
    if "מספר עסקים" in t:
        return "n_ind" if by_ind else ("n_cty" if by_cty else None)
    if "הסחר בסחורות" in t:
        return "v_ind" if by_ind else ("v_cty" if by_cty else None)
    return None


def _release_key(no):
    m = RELEASE.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _year_of(rows, name):
    for r in rows[:6]:
        for c in r:
            m = YEAR_LINE.search(c)
            if m:
                return int(m.group(1))
    raise ValueError(f"{name}: no 'Imports and Exports, <year>' line")


def _tables(frames):
    """{year: {kind: rows}}. Of two editions for the same year, the newer
    release wins; within an edition, the first stem with a kind wins."""
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    found = {}  # (release key, kind) -> (year, rows)
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        for rn in sorted(df["RELEASE_NO"].unique(), key=lambda v: (_release_key(v), str(v))):
            rows = cbs.grid(df[df["RELEASE_NO"] == rn], n)
            k = _kind(_title(rows))
            if not k:
                continue
            key = (_release_key(rn), k)
            if key not in found:
                found[key] = (_year_of(rows, n), rows)
    out = {}
    for (rk, k), (year, rows) in sorted(found.items(), key=lambda kv: kv[0]):
        out.setdefault(year, {})[k] = rows  # later releases overwrite earlier
    return out


# ── reading one table ────────────────────────────────────────────────────


def _layout(rows, name):
    """(first body row, {side: [5 column indexes: four sizes + total]})."""
    hi = cbs.row_with(rows, "Exports", name=name)
    ci = cbs.col_after(rows[hi], "Imports")
    ce = cbs.col_after(rows[hi], "Exports")
    hs = cbs.row_with(rows, "0-9", hi, name=name)
    cols = {}
    for side, s, stop in (("imp", ci, ce), ("exp", ce, 10 ** 6)):
        c = [cbs.col_after(rows[hs], lab, s) for lab in SIZES] + [cbs.col_after(rows[hs], "סך הכל", s)]
        if c != sorted(c) or c[-1] >= stop:
            raise ValueError(f"{name}: size-class header out of order")
        cols[side] = c
    return hs + 1, cols


def _vals(r, cols):
    return {side: [cbs.val(r, j) for j in cols[side]] for side in SIDES}


def _has_data(r, cols):
    return any(cbs.cell(r, j) for side in SIDES for j in cols[side])


def _heb_label(rs, numeric):
    parts = []
    for r in rs:
        for j, c in enumerate(r):
            if j not in numeric and HEB.search(c):
                parts.append(c)
    return " ".join(parts).strip()


def _parse(rows, kind, name):
    start, cols = _layout(rows, name)
    numeric = set(cols["imp"]) | set(cols["exp"])
    gt = cbs.row_with(rows, "Grand Total", start - 1, name=name)
    out = {"total": _vals(rows[gt], cols), "items": []}
    if out["total"]["imp"][4] is None or out["total"]["exp"][4] is None:
        raise ValueError(f"{name}: Grand Total has no total")
    if kind.endswith("ind"):
        pend, block = None, []
        for i in range(gt + 1, len(rows)):
            r = rows[i]
            letter = next((c for j, c in enumerate(r) if j not in numeric and SECTION.match(c)), None)
            if pend is None and letter:
                pend, block = letter, []
            if pend is None:
                continue
            block.append(r)
            if _has_data(r, cols):
                full = _heb_label(block, numeric)
                out["items"].append({"key": pend, "name": SECTION_HE.get(pend) or full,
                                     **_vals(r, cols)})
                pend = None
    else:
        conts = {}
        for i in range(gt + 1, len(rows)):
            r = rows[i]
            if not _has_data(r, cols):
                continue
            labels = [c for j, c in enumerate(r) if j not in numeric and c]
            code = next((c for c in labels if CODE.match(c)), None)
            iso = next((c for c in labels if ISO.match(c)), None)
            eng = "".join(c for c in labels if not HEB.search(c) and not CODE.match(c)).replace(" ", "").lower()
            if code == "900":
                conts.setdefault("unclassified", _vals(r, cols))
            elif code and iso:
                heb = _heb_label([r], numeric)
                if heb:
                    out["items"].append({"key": iso, "name": heb, **_vals(r, cols)})
            elif not code and eng in CONTINENT_HE:
                conts.setdefault(eng, _vals(r, cols))
        out["continents"] = conts
    return out


# ── helpers ──────────────────────────────────────────────────────────────


def _bn(v):
    """$M → $B, 2 decimals for charts."""
    return None if v is None else round(v / 1000, 2)


def _b1(v):
    return fmt.num_he(v / 1000, 1)


def _r1(v):
    return None if v is None else round(v, 1)


def _share(part, whole):
    return part / whole if part is not None and whole else None


JUMP = 0.5  # a one-year change in a count above this is a series change


def _chg(new, old):
    return (new - old) / old if new is not None and old else None


def _z(v):
    return v or 0.0


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    tabs = _tables(frames)
    if not tabs:
        raise ValueError("no recognised table in any edition")
    data = {}
    for y, ks in tabs.items():
        data[y] = {k: _parse(rows, k, f"{k} {y}") for k, rows in ks.items()}
    years = sorted(data)
    ly = years[-1]
    cur = data[ly]

    def val_total(y):
        d = data[y]
        t = d.get("v_ind") or d.get("v_cty")
        return t["total"] if t else None

    def cnt_total(y):
        t = data[y].get("n_ind")
        return t["total"] if t else None

    vt = val_total(ly)
    nt = cnt_total(ly)
    if vt is None and nt is None:
        raise ValueError(f"{ly}: neither a trade-value nor an enterprise-count table")

    kpis, charts, tables, labels, flags = {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    vyears = [y for y in years if val_total(y)]
    nyears = [y for y in years if cnt_total(y)]
    py = years[-2] if len(years) > 1 else None

    # ── KPIs ──
    if nt:
        kpis["exporters"] = {"value": nt["exp"][4], "display": fmt.int_he(nt["exp"][4]), "tone": "brand"}
        kpis["importers"] = {"value": nt["imp"][4], "display": fmt.int_he(nt["imp"][4]), "tone": "brand"}
        labels["exporters_kpi"] = f"עסקים מייצאים ({ly})"
        labels["importers_kpi"] = f"עסקים מייבאים ({ly})"
    if vt:
        kpis["exp_value"] = {"value": round(vt["exp"][4], 1), "display": _b1(vt["exp"][4]), "tone": "brand"}
        kpis["imp_value"] = {"value": round(vt["imp"][4], 1), "display": _b1(vt["imp"][4]), "tone": "brand"}
        labels["exp_value_kpi"] = f"יצוא סחורות, מיליארד דולר ({ly})"
        labels["imp_value_kpi"] = f"יבוא סחורות, מיליארד דולר ({ly})"
        big = _share(vt["exp"][3], vt["exp"][4])
        if big is not None:
            kpis["big_share"] = {"value": round(big * 100, 1), "display": fmt.pct(big),
                                 "tone": "warn" if big >= 0.5 else "info"}
            labels["big_share_kpi"] = "חלק העסקים הגדולים (250+ מועסקים) ביצוא"

    # ── trend: enterprise counts ──
    if len(nyears) >= 2:
        flags["count"] = True
        charts["count"] = {"x": [str(y) for y in nyears],
                           "exp": [cnt_total(y)["exp"][4] for y in nyears],
                           "imp": [cnt_total(y)["imp"][4] for y in nyears]}
        tables["count"] = [[str(y), fmt.int_he(cnt_total(y)["exp"][4]), fmt.int_he(cnt_total(y)["imp"][4])]
                           for y in nyears]
        labels["count_aria"] = f"מספר העסקים המייצאים והמייבאים, {nyears[0]} עד {nyears[-1]}"
        labels["count_note"] = (f"כמה עסקים ייצאו וכמה ייבאו סחורות בכל שנה, {nyears[0]} עד {nyears[-1]}. "
                                f"עסק נספר פעם אחת גם אם סחר עם כמה ארצות.")
        # A one-year jump of more than JUMP in a count is a coverage or
        # registration change, not growth (2024: CBS ties the doubling of
        # exporters to a change in how customs records personal exports).
        jumps = {}
        for k in ("exp", "imp"):
            for y0, y1 in itertools.pairwise(nyears):
                c = _chg(cnt_total(y1)[k][4], cnt_total(y0)[k][4])
                if c is not None and abs(c) > JUMP:
                    jumps.setdefault(y1, []).append(k)
        if jumps:
            parts = []
            for y in sorted(jumps):
                who = fmt.join_he([{"exp": "המייצאים", "imp": "המייבאים"}[k] for k in jumps[y]])
                parts.append(f"מספר העסקים {who} ב-{y}")
            verb = "השתנה" if len(parts) == 1 else "השתנו"
            labels["count_note"] += (f" שימו לב: {fmt.join_he(parts)} {verb} ביותר מחצי בתוך שנה אחת. "
                                     "שינוי כזה משקף ככל הנראה שינוי ברישום או בכיסוי הנתונים, "
                                     "ולא שינוי באותו היקף במספר העסקים הסוחרים.")
        a, b = nyears[-2], nyears[-1]
        e0, e1 = cnt_total(a)["exp"], cnt_total(b)["exp"]
        c = _chg(e1[4], e0[4])
        if c is not None and abs(c) > JUMP:
            txt = (f"מספר העסקים המייצאים השתנה מ-{fmt.int_he(e0[4])} ב-{a} ל-{fmt.int_he(e1[4])} ב-{b} "
                   f"({fmt.signed_pct(c)})")
            v0, v1 = val_total(a), val_total(b)
            vc = _chg(v1["exp"][4], v0["exp"][4]) if v0 and v1 else None
            if vc is not None and abs(vc) < abs(c) / 3:
                txt += f", בעוד שערך היצוא השתנה רק במעט ({fmt.signed_pct(vc)})"
            add("exporters_trend", txt + ". קפיצה כזו בשנה אחת מעידה ככל הנראה על שינוי ברישום או בכיסוי "
                "הנתונים, ולכן אין להשוות את שתי השנים כגידול או כירידה.")
        elif c is not None and abs(c) >= 0.03:
            word = "עלה" if c > 0 else "ירד"
            txt = (f"מספר העסקים המייצאים {word} מ-{fmt.int_he(e0[4])} ב-{a} "
                   f"ל-{fmt.int_he(e1[4])} ב-{b} ({fmt.signed_pct(c)})")
            d_small = _z(e1[0]) - _z(e0[0])
            d_all = e1[4] - e0[4]
            if d_all and d_small / d_all >= 0.6 and (d_small > 0) == (d_all > 0):
                txt += f", בעיקר בעסקים הזעירים (0-9 מועסקים), שמספרם {word} ב-{fmt.int_he(abs(d_small))}"
            add("exporters_trend", txt + ".")
        i0, i1 = cnt_total(a)["imp"][4], cnt_total(b)["imp"][4]
        c = _chg(i1, i0)
        if c is not None and abs(c) > JUMP:
            add("importers_trend", f"מספר העסקים המייבאים השתנה מ-{fmt.int_he(i0)} ב-{a} ל-{fmt.int_he(i1)} "
                f"ב-{b} ({fmt.signed_pct(c)}), קפיצה שמעידה ככל הנראה על שינוי ברישום או בכיסוי הנתונים.")
        elif c is not None and abs(c) >= 0.03:
            word = "עלה" if c > 0 else "ירד"
            add("importers_trend", f"מספר העסקים המייבאים {word} מ-{fmt.int_he(i0)} ב-{a} "
                f"ל-{fmt.int_he(i1)} ב-{b} ({fmt.signed_pct(c)}).")

    # ── trend: values + big-firm share ──
    if len(vyears) >= 2:
        flags["value"] = True
        charts["value"] = {"x": [str(y) for y in vyears],
                           "exp": [_bn(val_total(y)["exp"][4]) for y in vyears],
                           "imp": [_bn(val_total(y)["imp"][4]) for y in vyears],
                           "big_exp": [_r1(100 * _z(_share(val_total(y)["exp"][3], val_total(y)["exp"][4])))
                                       for y in vyears],
                           "big_imp": [_r1(100 * _z(_share(val_total(y)["imp"][3], val_total(y)["imp"][4])))
                                       for y in vyears]}
        tables["value"] = [[str(y), _b1(val_total(y)["exp"][4]), _b1(val_total(y)["imp"][4]),
                            fmt.pct(_z(_share(val_total(y)["exp"][3], val_total(y)["exp"][4]))),
                            fmt.pct(_z(_share(val_total(y)["imp"][3], val_total(y)["imp"][4])))]
                           for y in vyears]
        labels["value_aria"] = f"ערך היצוא והיבוא של סחורות, {vyears[0]} עד {vyears[-1]}"
        labels["value_note"] = ("ערך היצוא והיבוא של סחורות בכל שנה (מיליארד דולר), והקו: כמה מהערך "
                                "עבר דרך העסקים הגדולים (250 מועסקים ומעלה).")
        a, b = vyears[-2], vyears[-1]
        x0, x1 = val_total(a)["exp"][4], val_total(b)["exp"][4]
        c = _chg(x1, x0)
        if c is not None:
            if abs(c) < 0.02:
                add("value_trend", f"ערך יצוא הסחורות כמעט לא השתנה: {_b1(x1)} מיליארד דולר ב-{b} "
                    f"לעומת {_b1(x0)} מיליארד ב-{a}.")
            else:
                word = "עלה" if c > 0 else "ירד"
                add("value_trend", f"ערך יצוא הסחורות {word} מ-{_b1(x0)} מיליארד דולר ב-{a} "
                    f"ל-{_b1(x1)} מיליארד ב-{b} ({fmt.signed_pct(c)}).")
        s0 = _share(val_total(vyears[0])["exp"][3], val_total(vyears[0])["exp"][4])
        s1 = _share(val_total(b)["exp"][3], val_total(b)["exp"][4])
        if s0 is not None and s1 is not None and abs(s1 - s0) >= 0.02:
            word = "גדל" if s1 > s0 else "קטן"
            add("big_trend", f"חלקם של העסקים הגדולים ביצוא {word} מ-{fmt.pct(s0)} ב-{vyears[0]} "
                f"ל-{fmt.pct(s1)} ב-{b}.")

    # ── concentration by size (latest year) ──
    ni, vi = cur.get("n_ind"), cur.get("v_ind")
    if ni and vi:
        flags["conc"] = True
        cats = ["יצואנים: מספר עסקים", "יצוא: ערך", "יבואנים: מספר עסקים", "יבוא: ערך"]
        srcs = [ni["total"]["exp"], vi["total"]["exp"], ni["total"]["imp"], vi["total"]["imp"]]
        series = [[_r1(100 * _z(_share(s[k], s[4]))) for s in srcs] for k in range(4)]
        charts["conc"] = {"cats": cats, "sizes": list(SIZE_HE), "series": series}
        tables["conc"] = [[SIZE_HE[k]] + [fmt.pct(_z(_share(s[k], s[4]))) for s in srcs] for k in range(4)]
        labels["conc_aria"] = f"התפלגות העסקים וערך הסחר לפי גודל העסק, {ly}"
        labels["conc_note"] = (f"כל עמודה היא 100%: חלקה של כל קבוצת גודל במספר העסקים ובערך הסחר, {ly}. "
                               f"גודל העסק נמדד במספר המועסקים בו.")
        labels["conc_cols"] = ["גודל העסק"] + cats
        for side, who, what in (("exp", "יצואנים", "היצוא"), ("imp", "יבואנים", "היבוא")):
            n, v = ni["total"][side], vi["total"][side]
            sn, sv = _share(n[3], n[4]), _share(v[3], v[4])
            if sn is not None and sv is not None and sv >= 2 * sn and sv >= 0.2:
                add(f"conc_{side}", f"{fmt.int_he(n[3])} {who} גדולים (250 מועסקים ומעלה), "
                    f"{fmt.pct(sn)} מכלל ה{who}, אחראים ל-{fmt.pct(sv)} מערך {what} ב-{ly}.")

    # ── industries ──
    if vi and vi["items"]:
        flags["ind"] = True
        items = sorted(vi["items"], key=lambda it: (-(_z(it["exp"][4]) + _z(it["imp"][4])), it["key"]))
        top = items[:TOP_IND]
        rest = items[TOP_IND:]
        names = [it["name"] for it in top]
        exp = [_bn(it["exp"][4]) for it in top]
        imp = [_bn(it["imp"][4]) for it in top]
        if rest:
            names.append("אחר")
            exp.append(_bn(sum(_z(it["exp"][4]) for it in rest)))
            imp.append(_bn(sum(_z(it["imp"][4]) for it in rest)))
        charts["ind"] = {"names": names, "exp": exp, "imp": imp}
        tables["ind"] = [[n, "–" if e is None else fmt.num_he(e, 2), "–" if m is None else fmt.num_he(m, 2)]
                         for n, e, m in zip(names, exp, imp)]
        labels["ind_aria"] = f"ערך היצוא והיבוא לפי ענף כלכלי, {ly}"
        labels["ind_note"] = (f"ערך היצוא והיבוא של סחורות לפי הענף הכלכלי של העסק, {ly} (מיליארד דולר). "
                              f"ענף העסק הוא פעילותו העיקרית, ולא סוג הסחורה.")
        tot_exp = vi["total"]["exp"][4]
        tot_imp = vi["total"]["imp"][4]
        lead_e = max(vi["items"], key=lambda it: (_z(it["exp"][4]), it["key"]))
        se = _share(lead_e["exp"][4], tot_exp)
        if se is not None and se >= 0.3:
            add("ind_exp", f"ענף {lead_e['name']} מוביל את היצוא: {_b1(lead_e['exp'][4])} מיליארד דולר, "
                f"{fmt.pct(se)} מערך היצוא ב-{ly}.")
        lead_i = max(vi["items"], key=lambda it: (_z(it["imp"][4]), it["key"]))
        si = _share(lead_i["imp"][4], tot_imp)
        if si is not None and si >= 0.3:
            small = _share(_z(lead_i["imp"][0]) + _z(lead_i["imp"][1]), lead_i["imp"][4])
            txt = (f"עסקי {lead_i['name']} מייבאים {fmt.pct(si)} מערך היבוא "
                   f"({_b1(lead_i['imp'][4])} מיליארד דולר ב-{ly})")
            if small is not None and small >= 0.3:
                txt += f", ו-{fmt.pct(small)} מזה עובר דרך עסקים קטנים של עד 49 מועסקים"
            add("ind_imp", txt + ".")

        # size mix within the biggest industries (100% bars)
        for side, key in (("exp", "indsize_exp"), ("imp", "indsize_imp")):
            its = sorted((it for it in vi["items"] if it[side][4]),
                         key=lambda it: (-it[side][4], it["key"]))[:6]
            if len(its) < 2:
                continue
            flags[key] = True
            ser = [[_r1(100 * _z(_share(it[side][k], it[side][4]))) for it in its] for k in range(4)]
            charts[key] = {"names": [it["name"] for it in its], "sizes": list(SIZE_HE), "series": ser}
            tables[key] = [[it["name"]] + [fmt.pct(_z(_share(it[side][k], it[side][4]))) for k in range(4)]
                           for it in its]
    labels["indsize_cols"] = ["ענף"] + list(SIZE_HE)
    labels["indsize_exp_aria"] = f"ערך היצוא בענפים הגדולים לפי גודל העסק, {ly}"
    labels["indsize_imp_aria"] = f"ערך היבוא בענפים הגדולים לפי גודל העסק, {ly}"
    labels["indsize_exp_note"] = (f"בששת הענפים עם היצוא הגדול ביותר: איזה חלק מהיצוא בא מעסקים בכל גודל, {ly}. "
                                  f"חלקים שהלמ\"ס לא פרסמה מטעמי סודיות חסרים, ולכן סכום השורה יכול להיות קטן מ-100%.")
    labels["indsize_imp_note"] = (f"בששת הענפים עם היבוא הגדול ביותר: איזה חלק מהיבוא בא מעסקים בכל גודל, {ly}. "
                                  f"חלקים שהלמ\"ס לא פרסמה מטעמי סודיות חסרים, ולכן סכום השורה יכול להיות קטן מ-100%.")

    if ni and ni["items"]:
        flags["indn"] = True
        items = sorted(ni["items"], key=lambda it: (-_z(it["exp"][4]), it["key"]))[:TOP_IND]
        vmap = {it["key"]: it for it in (vi["items"] if vi else [])}
        rows = []
        for it in items:
            v = vmap.get(it["key"])
            avg = (v["exp"][4] / it["exp"][4]) if v and v["exp"][4] and it["exp"][4] else None
            rows.append([it["name"], fmt.int_he(_z(it["exp"][4])), fmt.int_he(_z(it["imp"][4])),
                         "–" if avg is None else fmt.num_he(avg, 2)])
        charts["indn"] = {"names": [it["name"] for it in items],
                          "exp": [it["exp"][4] for it in items],
                          "imp": [it["imp"][4] for it in items]}
        tables["indn"] = rows
        labels["indn_aria"] = f"מספר העסקים המייצאים והמייבאים לפי ענף, {ly}"
        labels["indn_note"] = (f"כמה עסקים בכל ענף ייצאו וכמה ייבאו סחורות ב-{ly}: עשרת הענפים עם הכי הרבה "
                               f"יצואנים. בטבלה גם היצוא הממוצע לעסק מייצא (מיליון דולר).")
        if vi:
            avgs = []
            for it in ni["items"]:
                v = vmap.get(it["key"])
                if v and v["exp"][4] and it["exp"][4] and it["exp"][4] >= 100:
                    avgs.append((v["exp"][4] / it["exp"][4], it))
            if len(avgs) >= 3:
                avgs.sort(key=lambda p: (-p[0], p[1]["key"]))
                hi_avg, hi_it = avgs[0]
                tot_avg = vi["total"]["exp"][4] / ni["total"]["exp"][4] if ni["total"]["exp"][4] else None
                if tot_avg and hi_avg >= 2 * tot_avg:
                    add("ind_avg", f"עסק מייצא בענף {hi_it['name']} ייצא בממוצע סחורות ב-"
                        f"{fmt.num_he(hi_avg, 1)} מיליון דולר ב-{ly}, פי {fmt.num_he(hi_avg / tot_avg, 1)} "
                        f"מהממוצע לכלל היצואנים ({fmt.num_he(tot_avg, 2)} מיליון דולר).")

    # ── regions + countries ──
    vc, nc = cur.get("v_cty"), cur.get("n_cty")
    if vc and vc.get("continents"):
        keys = [k for k in CONTINENT_ORDER if k in vc["continents"]]
        flags["region"] = True
        names = [CONTINENT_HE.get(k, UNCLASSIFIED_HE) for k in keys]
        charts["region"] = {"names": names,
                            "exp": [_bn(vc["continents"][k]["exp"][4]) for k in keys],
                            "imp": [_bn(vc["continents"][k]["imp"][4]) for k in keys]}
        tables["region"] = [[n, "–" if e is None else fmt.num_he(e, 2), "–" if m is None else fmt.num_he(m, 2)]
                            for n, e, m in zip(names, charts["region"]["exp"], charts["region"]["imp"])]
        labels["region_aria"] = f"ערך היצוא והיבוא לפי יבשת, {ly}"
        labels["region_note"] = (f"ערך היצוא והיבוא של סחורות לפי יבשת, {ly} (מיליארד דולר). "
                                 f"\"ארצות לא מסווגות\" הן עסקאות שהארץ שלהן לא נקבעה או לא פורסמה.")
    if vc and vc["items"]:
        flags["cty"] = True
        items = sorted(vc["items"], key=lambda it: (-(_z(it["exp"][4]) + _z(it["imp"][4])), it["key"]))[:TOP_CTY]
        charts["cty"] = {"names": [it["name"] for it in items],
                         "exp": [_bn(it["exp"][4]) for it in items],
                         "imp": [_bn(it["imp"][4]) for it in items]}
        tables["cty"] = [[it["name"], "–" if it["exp"][4] is None else fmt.num_he(it["exp"][4] / 1000, 2),
                          "–" if it["imp"][4] is None else fmt.num_he(it["imp"][4] / 1000, 2)] for it in items]
        labels["cty_aria"] = f"שותפות הסחר הגדולות של ישראל, {ly}"
        labels["cty_note"] = (f"{len(items)} הארצות עם היקף הסחר (יצוא ועוד יבוא) הגדול ביותר, {ly} (מיליארד דולר).")
        tot_exp = vc["total"]["exp"][4]
        lead = max(vc["items"], key=lambda it: (_z(it["exp"][4]), it["key"]))
        sh = _share(lead["exp"][4], tot_exp)
        if sh is not None and sh >= 0.1:
            add("cty_exp", f"{lead['name']} היא יעד היצוא הגדול: {_b1(lead['exp'][4])} מיליארד דולר, "
                f"{fmt.pct(sh)} מערך יצוא הסחורות ב-{ly}.")
        lead_i = max(vc["items"], key=lambda it: (_z(it["imp"][4]), it["key"]))
        shi = _share(lead_i["imp"][4], vc["total"]["imp"][4])
        if shi is not None and shi >= 0.1 and lead_i["key"] != lead["key"]:
            add("cty_imp", f"מקור היבוא הגדול הוא {lead_i['name']}: {_b1(lead_i['imp'][4])} מיליארד דולר, "
                f"{fmt.pct(shi)} מערך היבוא ב-{ly}.")

        # exports to the top destinations over the years
        cyears = [y for y in years if data[y].get("v_cty") and data[y]["v_cty"]["items"]]
        if len(cyears) >= 2:
            dest = sorted(vc["items"], key=lambda it: (-_z(it["exp"][4]), it["key"]))[:TOP_TREND]
            ser = []
            for it in dest:
                row = []
                for y in cyears:
                    m = {x["key"]: x for x in data[y]["v_cty"]["items"]}
                    row.append(_bn(m[it["key"]]["exp"][4]) if it["key"] in m else None)
                ser.append(row)
            flags["ctytrend"] = True
            charts["ctytrend"] = {"x": [str(y) for y in cyears], "names": [it["name"] for it in dest],
                                  "series": ser}
            tables["ctytrend"] = [[str(y)] + ["–" if s[j] is None else fmt.num_he(s[j], 2) for s in ser]
                                  for j, y in enumerate(cyears)]
            labels["ctytrend_cols"] = ["שנה"] + [it["name"] for it in dest]
            labels["ctytrend_aria"] = f"היצוא ליעדים הגדולים, {cyears[0]} עד {cyears[-1]}"
            labels["ctytrend_note"] = (f"ערך היצוא לכל אחד מ-{len(dest)} יעדי היצוא הגדולים של {ly}, "
                                       f"בכל שנה מ-{cyears[0]} (מיליארד דולר).")
            best = None
            for it, s in zip(dest, ser):
                if s[0] and s[-1] is not None:
                    c = _chg(s[-1], s[0])
                    if best is None or (abs(c), it["key"]) > (abs(best[0]), best[1]["key"]):
                        best = (c, it, s)
            if best and abs(best[0]) >= 0.15:
                c, it, s = best
                word = "עלה" if c > 0 else "ירד"
                add("cty_move", f"מבין יעדי היצוא הגדולים, השינוי החד ביותר הוא ב{it['name']}: היצוא אליה "
                    f"{word} מ-{fmt.num_he(s[0], 1)} מיליארד דולר ב-{cyears[0]} ל-{fmt.num_he(s[-1], 1)} "
                    f"מיליארד ב-{cyears[-1]} ({fmt.signed_pct(c)}).")

    if nc and nc["items"]:
        flags["ctyn"] = True
        items = sorted(nc["items"], key=lambda it: (-_z(it["exp"][4]), it["key"]))[:TOP_CTY]
        charts["ctyn"] = {"names": [it["name"] for it in items], "exp": [it["exp"][4] for it in items]}
        tables["ctyn"] = [[it["name"], "–" if it["exp"][4] is None else fmt.int_he(it["exp"][4]),
                           "–" if it["imp"][4] is None else fmt.int_he(it["imp"][4])] for it in items]
        labels["ctyn_aria"] = f"מספר העסקים המייצאים לכל ארץ, {ly}"
        labels["ctyn_note"] = (f"לאן מייצאים הכי הרבה עסקים: {len(items)} הארצות עם מספר היצואנים הגדול ביותר, "
                               f"{ly}. עסק שמייצא לכמה ארצות נספר בכל אחת מהן. בטבלה גם מספר היבואנים מכל ארץ.")
        lead_i = max(nc["items"], key=lambda it: (_z(it["imp"][4]), it["key"]))
        if nt and lead_i["imp"][4]:
            sh = _share(lead_i["imp"][4], nt["imp"][4])
            small = _share(lead_i["imp"][0], lead_i["imp"][4])
            if sh is not None and sh >= 0.25:
                txt = (f"{fmt.int_he(lead_i['imp'][4])} עסקים ייבאו סחורות מ{lead_i['name']} ב-{ly}, "
                       f"{fmt.pct(sh)} מכלל היבואנים")
                if small is not None and small >= 0.8:
                    txt += f". {fmt.pct(small)} מהם עסקים זעירים של עד 9 מועסקים"
                add("cty_importers", txt + ".")

    # The insight card holds the strongest findings; the rest show as a
    # callout in their own chart section.
    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    # ── release card + text ──
    rel = cbs.latest_release(frames["releases"])
    release = {"title": rel["TITLE"], "headline": rel["HEADLINE"], "url": rel["PAGE_URL"],
               "pdf": rel["REPORT_PDF_URL"], "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}

    parts = []
    if nt:
        parts.append(f"ייצאו סחורות {fmt.int_he(nt['exp'][4])} עסקים וייבאו {fmt.int_he(nt['imp'][4])}")
    if vt:
        parts.append(f"ערך היצוא היה {_b1(vt['exp'][4])} מיליארד דולר וערך היבוא {_b1(vt['imp'][4])} מיליארד")
    labels["lede"] = ("מי הם היצואנים והיבואנים של ישראל: כמה עסקים סוחרים בסחורות, באיזה גודל, מאיזה ענף "
                      "ועם אילו ארצות. הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), "
                      "שמצליבה את נתוני המכס עם מרשם העסקים, ומתעדכנים עם כל הודעה חדשה. "
                      f"בשנת {ly} " + "; ".join(parts) + ".")
    summary = (f"הסחר בסחורות של ישראל לפי מאפייני היצואנים והיבואנים (הלמ\"ס): ב-{ly} "
               + "; ".join(parts) + ".")
    if nt:
        desc = (f"כמה יצואנים ויבואנים יש בישראל: {fmt.int_he(nt['exp'][4])} עסקים מייצאים "
                f"ו-{fmt.int_he(nt['imp'][4])} מייבאים ב-{ly}, לפי גודל העסק, ענף וארץ.")
    else:
        desc = (f"יצוא ויבוא סחורות לפי מאפייני העסקים: {_b1(vt['exp'][4])} מיליארד דולר יצוא ב-{ly}, "
                f"לפי גודל העסק, ענף וארץ.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "misc",
            "temporal_coverage": f"{years[0]}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "יצואנים ויבואנים בישראל: מספר, גודל וענף | הלמ\"ס",
                "description": desc,
                "name": "יצואנים ויבואנים בישראל לפי מאפיינים",
                "alternate_names": ["הסחר בסחורות לפי מאפיינים של יצואנים ויבואנים",
                                    "מספר היצואנים בישראל", "מספר היבואנים בישראל",
                                    "יצוא לפי גודל עסק"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top,
        "callouts": callouts,
        "labels": labels,
        "flags": flags,
        "release": release,
        "year": ly,
        "prev_year": py,
    }
