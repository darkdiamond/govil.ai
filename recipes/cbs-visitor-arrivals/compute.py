"""כניסות מבקרים לישראל: CBS's monthly visitor-arrivals release.

Inputs are CBS grid tables (one row per sheet row, cells C01..Cnn) from the
newest edition of the release:
  t1  visitor arrivals by mode (day visitors / tourists, land / air), yearly
      since 2016, year to date, and monthly
  t2  tourist arrivals: original, seasonally adjusted and trend, monthly
  t3  tourists and day visits by country of citizenship (month, year to date)
  t4  arrivals by border crossing (month and year to date, three years)
  t5  tourist arrivals by air, monthly since 2019 (chart data)
  releases  the edition list (number, date, headline, link)

Header rows are found by their (English) labels and raise when missing, so a
redesigned table fails the refresh as recipe_failed and keeps the last
page. Data rows (years, months, countries, crossings) are found by pattern:
a missing one only shortens a series. All values are thousands.
"""
import re

import pandas as pd
from govlib import cbs, fmt

CONTINENTS = ("אסיה", "אפריקה", "אירופה", "אמריקה", "אוקיאניה")
TOP_COUNTRIES = 15
RECOVERY_MONTHS = 12
DOMINANT_SHARE = 0.8
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")
_EN_RANGE = re.compile(rf"^({'|'.join(MONTHS_EN)})-({'|'.join(MONTHS_EN)})$")


# ── tables ───────────────────────────────────────────────────────────────


def _t1(rows):
    """Yearly arrivals by mode, and the year-to-date pair."""
    h = cbs.row_with(rows, "Cruise", name="t1")
    sub = rows[h]
    cruise = cbs.col_after(sub, "Cruise", 0)
    d_land, d_air = cbs.col_after(sub, "By Land", cruise), cbs.col_after(sub, "By Air", cruise)
    d_tot = cbs.col_after(sub, "Total", cruise)
    t_land, t_air = cbs.col_after(sub, "By Land", d_tot), cbs.col_after(sub, "By Air", d_tot)
    g = cbs.row_with(rows, "Grand Total", max(0, h - 4), name="t1")
    grand = cbs.col_after(rows[g], "Grand Total", 0)
    t_tot = cbs.col_after(rows[g], "Total", 0)
    stop = next((i for i in range(h, len(rows)) if any(
        "Percentage of change" in c for c in rows[i])), len(rows))
    years, ytd = [], []
    for i, y, m, end in cbs.periods(rows, h + 1, stop):
        r = rows[i]
        rec = {"year": y, "grand": cbs.val(r, grand), "tourists": cbs.val(r, t_tot),
               "air": cbs.val(r, t_air), "land": cbs.val(r, t_land), "day": cbs.val(r, d_tot),
               "day_air": cbs.val(r, d_air), "day_land": cbs.val(r, d_land), "cruise": cbs.val(r, cruise)}
        if rec["grand"] is None:
            continue
        if m is None:
            years.append(rec)
        elif m == 1 and end:
            ytd.append({**rec, "end": end})
    years.sort(key=lambda r: r["year"])
    ytd.sort(key=lambda r: r["year"])
    return years, ytd


def _t2(rows):
    """Monthly tourist arrivals (total): original, SA, trend, trend % change."""
    e = cbs.row_with(rows, "change in trend", name="t2")
    head = cbs.row_with(rows, "Total", max(0, e - 6), name="t2")
    total = cbs.col_after(rows[head], "Total", 0)
    sub = rows[e]
    pct = cbs.col_after(sub, "change in trend", total)
    trend, sa, orig = (cbs.col_after(sub, "Trend", pct), cbs.col_after(sub, "adjusted", pct),
                       cbs.col_after(sub, "data", pct))
    stop = next((i for i in range(e, len(rows)) if any(
        "Percentage of change" in c for c in rows[i])), len(rows))
    out = []
    for i, y, m, end in cbs.periods(rows, e + 1, stop):
        r = rows[i]
        if m is None or end:
            continue
        o = cbs.val(r, orig)
        if o is None:
            continue
        out.append({"t": (y, m), "orig": o, "sa": cbs.val(r, sa), "trend": cbs.val(r, trend),
                    "trend_pct": cbs.val(r, pct)})
    out.sort(key=lambda r: r["t"])
    return out


def _t3(rows):
    """Tourists by country of citizenship: the month block and the
    year-to-date block. Returns (countries, continents, grand, labels)."""
    p = next((i for i, r in enumerate(rows)
              if sum(bool(re.match(r"^[IVX]+(-[IVX]+)? \d{4}$", c)) for c in r) >= 1
              and any("Absolute numbers" in c for c in rows[max(0, i - 1)])), None)
    if p is None:
        raise ValueError("t3: period header row not found")
    blocks = [j for j, c in enumerate(rows[p]) if re.match(r"^[IVX]+(-[IVX]+)? \d{4}$", c)]
    tok = cbs.row_with(rows, "Cruise", p, name="t3")
    grand_row = tok - 1 if "Grand" in rows[tok - 1] else cbs.row_with(rows, "Grand", p, name="t3")
    name_col = cbs.col_after(rows[cbs.row_with(rows, "ארץ אזרחות", name="t3")], "ארץ אזרחות", 0)

    def cols(b):
        air = cbs.col_after(rows[tok], "Air", b)
        return {"air": air, "tourists": cbs.col_after(rows[tok], "Total", air),
                "grand": cbs.col_after(rows[grand_row], "Grand", b)}

    month, ytd = cols(blocks[0]), cols(blocks[-1])
    countries, continents, grand = [], [], None
    for r in rows[tok + 1:]:
        name = r[name_col] if name_col < len(r) else ""
        g = cbs.val(r, ytd["grand"])
        if not name or g is None:
            continue
        rec = {"name": name, "ytd": cbs.val(r, ytd["tourists"]) or 0.0, "ytd_grand": g,
               "month": cbs.val(r, month["tourists"]) or 0.0, "ytd_air": cbs.val(r, ytd["air"])}
        if name == "סך כולל":
            grand = rec
        elif name.endswith("- סך הכל"):
            base = name.replace("- סך הכל", "").strip()
            if base in CONTINENTS:
                continents.append({**rec, "name": base})
        elif "ארצות אחרות" in name or "בלתי מסווגות" in name or name.startswith("מזה"):
            continue
        else:
            countries.append(rec)
    if grand is None:
        raise ValueError("t3: grand total row (סך כולל) not found")
    return countries, continents, grand, (rows[p][blocks[0]], rows[p][blocks[-1]])


def _t4(rows):
    """Tourist arrivals by border crossing, year to date, for three years."""
    yrow = next((i for i, r in enumerate(rows) if sum(bool(cbs.YEAR.match(c)) for c in r) >= 4),
                None)
    if yrow is None:
        raise ValueError("t4: year header row not found")
    ycols = [j for j, c in enumerate(rows[yrow]) if cbs.YEAR.match(c)]
    half = len(ycols) // 2
    if half < 2 or len(ycols) != 2 * half:
        raise ValueError(f"t4: expected two blocks of years, got {ycols}")
    # The English block labels ("January-October", "October") say which
    # block is which; the range must be the left one. In January both read
    # "January" (year to date = the month), so there is no range to check.
    lrow = next((rows[i] for i in range(yrow - 1, -1, -1)
                 if any(c in MONTHS_EN or _EN_RANGE.match(c) for c in rows[i])), None)
    if lrow is None:
        raise ValueError("t4: block label row (January-…) not found")
    ranges = [j for j, c in enumerate(lrow) if _EN_RANGE.match(c)]
    singles = [j for j, c in enumerate(lrow) if c in MONTHS_EN]
    if ranges and singles and min(ranges) > min(singles):
        raise ValueError("t4: the year-to-date block (January-…) must come first")
    name_col = cbs.col_after(rows[cbs.row_with(rows, "דרך מעבר", name="t4")], "דרך מעבר", 0)
    years = [int(rows[yrow][j]) for j in ycols[:half]]
    section, out = None, []
    for r in rows[yrow + 1:]:
        name = r[name_col] if name_col < len(r) else ""
        vals = [cbs.val(r, j) for j in ycols]
        if not name or all(v is None for v in vals):
            continue
        if name.startswith("מבקרים - סך"):
            section = "visitors"
        elif name.startswith("תיירים"):
            section = "tourists"
        elif name.startswith("מבקרי יום"):
            section = "day"
        out.append({"name": name, "section": section, "ytd": vals[:half], "month": vals[half:]})
    return years, out


def _t5(rows):
    """Tourist arrivals by air, monthly: [{t: (year, month), orig, trend}]."""
    h = cbs.row_with(rows, "Original Data נתונים מקוריים", name="t5")
    orig = cbs.col_after(rows[h], "Original Data נתונים מקוריים", 0)
    trend = cbs.col_after(rows[h], "Trend מגמה", orig)
    return [{"t": (y, m), "orig": cbs.val(rows[i], orig), "trend": cbs.val(rows[i], trend)}
            for i, y, m in cbs.monthly_runs(rows, h + 1, len(rows), orig)]


# ── formatting ───────────────────────────────────────────────────────────


def _k(v):
    """Thousands, one decimal: 152.4."""
    return fmt.num_he(v, 1)


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _range(end, year):
    if end == 1:
        return f"ינואר {year}"
    return f"ינואר עד {fmt.MONTHS_HE[end - 1]} {year}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _word(c, up="עלייה", down="ירידה"):
    return up if c > 0 else down


def _tone(c, band=0.02):
    if c is None:
        return "brand"
    return "ok" if c > band else "danger" if c < -band else "warn"


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"].copy()
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    years, ytd = _t1(cbs.grid(frames["t1"], "t1"))
    monthly = _t2(cbs.grid(frames["t2"], "t2"))
    countries, continents, grand3, (month_lbl, _) = _t3(cbs.grid(frames["t3"], "t3"))
    t4_years, crossings = _t4(cbs.grid(frames["t4"], "t4"))
    air = _t5(cbs.grid(frames["t5"], "t5"))
    if not monthly:
        raise ValueError("t2: no monthly rows")
    if not years:
        raise ValueError("t1: no yearly rows")

    last = monthly[-1]
    # The release's own month (t3's period header, e.g. "X 2026"): t4's
    # month block is for it. t2's last row is normally the same month.
    pm = re.match(r"^([IVX]+) (\d{4})$", month_lbl)
    if not pm or pm.group(1) not in cbs.ROMAN:
        raise ValueError(f"t3: month block label {month_lbl!r} is not 'MM YYYY'")
    lt = (int(pm.group(2)), cbs.ROMAN[pm.group(1)])

    vis = next((c for c in crossings if c["section"] == "visitors"), None)
    if vis is None or vis["month"][-1] is None:
        raise ValueError("t4: visitors grand-total row (מבקרים - סך כולל) not found")
    vis_month, vis_month_prev = vis["month"][-1], vis["month"][-2]
    vis_month_chg = _chg(vis_month, vis_month_prev)

    ytd_now = ytd[-1] if ytd else None
    ytd_prev = ytd[-2] if len(ytd) >= 2 and ytd[-2]["end"] == ytd[-1]["end"] else None
    ytd_chg = _chg(ytd_now["grand"], ytd_prev["grand"]) if ytd_now and ytd_prev else None

    full_years = [y for y in years if y["year"] < (ytd_now["year"] if ytd_now else 10 ** 4)]
    peak = max(full_years or years, key=lambda y: (y["grand"], y["year"]))

    air_by_t = {a["t"]: a for a in air}
    air_last = air[-1] if air else None
    base_year = peak["year"]
    base_air = air_by_t.get((base_year, air_last["t"][1])) if air_last else None
    recovery = (air_last["orig"] / base_air["orig"]) if air_last and base_air and base_air["orig"] else None

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    month_value = vis_month
    kpis["month"] = {"value": month_value, "display": _k(month_value),
                     "tone": _tone(vis_month_chg)}
    labels["month_kpi"] = f"כניסות מבקרים ב{_mname(lt)} (אלפים)"
    if vis_month_chg is not None:
        kpis["month_chg"] = {"value": round(vis_month_chg, 4),
                             "display": fmt.signed_pct(vis_month_chg),
                             "tone": _tone(vis_month_chg)}
        labels["month_chg_kpi"] = f"שינוי לעומת {_mname((lt[0] - 1, lt[1]))}"
    if ytd_now:
        kpis["ytd"] = {"value": ytd_now["grand"], "display": _k(ytd_now["grand"]),
                       "tone": _tone(ytd_chg)}
        labels["ytd_kpi"] = f"מבקרים מתחילת השנה, {_range(ytd_now['end'], ytd_now['year'])} (אלפים)"
    if ytd_chg is not None:
        kpis["ytd_chg"] = {"value": round(ytd_chg, 4), "display": fmt.signed_pct(ytd_chg),
                           "tone": _tone(ytd_chg)}
        labels["ytd_chg_kpi"] = f"שינוי לעומת התקופה המקבילה ב-{ytd_prev['year']}"
    if recovery is not None:
        kpis["recovery"] = {"value": round(recovery, 4), "display": fmt.pct(recovery, 0),
                            "tone": "ok" if recovery >= 0.9 else "warn" if recovery >= 0.5
                            else "danger"}
        labels["recovery_kpi"] = (f"תיירים בדרך האוויר ב{_mname(air_last['t'])} "
                                  f"לעומת {_mname((base_year, air_last['t'][1]))}")

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables = {}, {}
    charts["years"] = {
        "x": [str(y["year"]) for y in years],
        "air": [y["air"] for y in years], "land": [y["land"] for y in years],
        "day": [y["day"] for y in years], "grand": [y["grand"] for y in years],
    }
    tables["years"] = [[str(y["year"]), _k(y["grand"]), _k(y["tourists"]) if y["tourists"]
                        is not None else "", _k(y["air"]) if y["air"] is not None else "",
                        _k(y["land"]) if y["land"] is not None else "",
                        _k(y["day"]) if y["day"] is not None else ""] for y in years]

    if air:
        charts["air"] = {"x": [f"{t[0]}-{t[1]:02d}" for t in (a["t"] for a in air)],
                         "orig": [a["orig"] for a in air], "trend": [a["trend"] for a in air]}
        air_years = sorted({a["t"][0] for a in air})
        tables["air"] = [[str(y)] + [_k(air_by_t[(y, m)]["orig"]) if (y, m) in air_by_t else ""
                                     for m in range(1, 13)] for y in air_years]

    rec_rows = []
    for a in air[-RECOVERY_MONTHS:]:
        b = air_by_t.get((base_year, a["t"][1]))
        if b and b["orig"]:
            rec_rows.append((a["t"], a["orig"], b["orig"], a["orig"] / b["orig"]))
    if rec_rows:
        charts["recovery"] = {"x": [_mshort(r[0]) for r in rec_rows],
                              "y": [round(r[3] * 100, 1) for r in rec_rows]}
        tables["recovery"] = [[_mname(r[0]), _k(r[1]), _k(r[2]), fmt.pct(r[3], 0)]
                              for r in rec_rows]

    charts["recent"] = {"x": [_mshort(m["t"]) for m in monthly],
                        "orig": [m["orig"] for m in monthly], "sa": [m["sa"] for m in monthly],
                        "trend": [m["trend"] for m in monthly]}
    tables["recent"] = [[_mname(m["t"]), _k(m["orig"]),
                         _k(m["sa"]) if m["sa"] is not None else "",
                         _k(m["trend"]) if m["trend"] is not None else "",
                         fmt.signed_pct(m["trend_pct"] / 100) if m["trend_pct"] is not None
                         else ""]
                        for m in reversed(monthly)]

    groups = {"דרך האוויר", "דרך היבשה"}
    leaves = [c for c in crossings if c["section"] == "tourists" and "סך" not in c["name"]
              and c["name"] not in groups and any(v for v in c["ytd"] if v)]
    leaves.sort(key=lambda c: (-(c["ytd"][-1] or 0), c["name"]))
    # One crossing (Ben Gurion) carries most tourists; drawn on the same
    # axis it flattens the rest, so a dominant leader leaves the chart (it
    # stays in the table and the note says so).
    tour_row = next((c for c in crossings if c["section"] == "tourists"), None)
    tour_ytd = tour_row["ytd"][-1] if tour_row else None
    drawn = leaves
    dominant = None
    if len(leaves) > 2 and tour_ytd and (leaves[0]["ytd"][-1] or 0) / tour_ytd > DOMINANT_SHARE:
        dominant, drawn = leaves[0], leaves[1:]
    if leaves:
        charts["crossings"] = {"names": [c["name"] for c in drawn],
                               "years": [str(y) for y in t4_years],
                               "series": [[c["ytd"][k] for c in drawn]
                                          for k in range(len(t4_years))]}
        tables["crossings"] = [[c["name"]] + [_k(v) if v is not None else "" for v in c["ytd"]]
                               for c in leaves]

    countries.sort(key=lambda c: (-c["ytd"], c["name"]))
    top = countries[:TOP_COUNTRIES]
    tourists_total = grand3["ytd"]
    charts["countries"] = {"names": [c["name"] for c in top], "ytd": [c["ytd"] for c in top]}
    tables["countries"] = [[c["name"], _k(c["ytd"]), _k(c["month"]),
                            fmt.pct(c["ytd"] / tourists_total) if tourists_total else ""]
                           for c in top]

    continents.sort(key=lambda c: (-c["ytd"], c["name"]))
    charts["continents"] = [{"name": c["name"], "value": c["ytd"]} for c in continents]
    tables["continents"] = [[c["name"], _k(c["ytd"]),
                             fmt.pct(c["ytd"] / tourists_total) if tourists_total else ""]
                            for c in continents]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if vis_month_chg is not None:
        add("month", f"ב{_mname(lt)} נכנסו לישראל {_k(vis_month)} אלף מבקרים, "
                     f"{_word(vis_month_chg)} של {fmt.pct(abs(vis_month_chg))} לעומת "
                     f"{_mname((lt[0] - 1, lt[1]))} ({_k(vis_month_prev)} אלף).")
    if ytd_chg is not None:
        add("ytd", f"מתחילת השנה ({_range(ytd_now['end'], ytd_now['year'])}) "
                   f"נכנסו {_k(ytd_now['grand'])} אלף מבקרים, {_word(ytd_chg)} של "
                   f"{fmt.pct(abs(ytd_chg))} לעומת התקופה המקבילה ב-{ytd_prev['year']} "
                   f"({_k(ytd_prev['grand'])} אלף).")
    if recovery is not None and base_air:
        add("recovery", f"שנת השיא בנתונים היא {base_year}, עם {_k(peak['grand'])} אלף "
                        f"מבקרים. ב{_mname(air_last['t'])} נכנסו בדרך האוויר "
                        f"{_k(air_last['orig'])} אלף תיירים, {fmt.pct(recovery, 0)} מהמספר "
                        f"ב{_mname((base_year, air_last['t'][1]))} ({_k(base_air['orig'])} אלף).")
    window = monthly[-24:]
    if len(window) >= 12:
        low = min(window, key=lambda m: (m["orig"], m["t"]))
        if low["t"] != last["t"]:
            add("low", f"החודש החלש ביותר מאז {_mname(window[0]['t'])} היה {_mname(low['t'])}: "
                       f"{_k(low['orig'])} אלף תיירים בלבד. מאז עלה המספר פי "
                       f"{fmt.num_he(last['orig'] / low['orig'], 1)}."
                if low["orig"] else None)
    run = 0
    for m in reversed(monthly):
        if m["trend_pct"] is None:
            break
        if run and (m["trend_pct"] > 0) != (monthly[-1]["trend_pct"] > 0):
            break
        if m["trend_pct"] == 0:
            break
        run += 1
    if run >= 3 and last["trend_pct"] is not None:
        add("trend", f"מגמת כניסות התיירים {'עולה' if last['trend_pct'] > 0 else 'יורדת'} "
                     f"זה {run} חודשים ברציפות ({fmt.pct_of(abs(last['trend_pct']))} "
                     f"ב{_mname(last['t'])}, בנתוני המגמה של הלמ\"ס).")
    if top and tourists_total:
        lead = top[0]
        share = lead["ytd"] / tourists_total
        if share >= 0.15:
            add("country", f"{lead['name']} היא מקור התיירים הגדול: {_k(lead['ytd'])} אלף "
                           f"תיירים מתחילת השנה, {fmt.pct(share)} מכלל התיירים.")
    if leaves and leaves[0]["ytd"][-1]:
        tot = tour_ytd
        if tot:
            share = leaves[0]["ytd"][-1] / tot
            add("crossing", f"{fmt.pct(share)} מהתיירים מתחילת השנה נכנסו {leaves[0]['name']}"
                            f" ({_k(leaves[0]['ytd'][-1])} אלף מתוך {_k(tot)} אלף).")

    # ── text ─────────────────────────────────────────────────────────────
    rel_date = pd.Timestamp(latest_rel["RELEASE_DATE"])
    release = {"no": latest_rel["RELEASE_NO"], "date": fmt.d_he(rel_date),
               "title": latest_rel["TITLE"], "headline": latest_rel["HEADLINE"],
               "url": latest_rel["PAGE_URL"], "pdf": latest_rel["REPORT_PDF_URL"]}
    span = f"{years[0]['year']}-{lt[0]}"
    labels.update({
        "lede": (f"כמה מבקרים נכנסים לישראל בכל חודש, מאילו ארצות ודרך אילו מעברי גבול. "
                 f"הנתונים מתוך ההודעה החודשית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), "
                 f"ומתעדכנים עם כל הודעה חדשה. הנתון האחרון הוא ל{_mname(lt)}: "
                 f"{_k(month_value)} אלף מבקרים."),
        "years_note": (f"כניסות מבקרים בכל שנה מאז {years[0]['year']}, לפי תיירים בדרך האוויר, "
                       f"תיירים בדרך היבשה ומבקרי יום. השיא: {peak['year']}, "
                       f"{_k(peak['grand'])} אלף."),
        "years_aria": f"כניסות מבקרים לפי שנה, {years[0]['year']} עד {years[-1]['year']}",
        "years_caption": "כניסות מבקרים לפי שנה ודרך כניסה (אלפים)",
        "recent_note": (f"כניסות תיירים בכל חודש מאז {_mname(monthly[0]['t'])}: הנתון המקורי, "
                        f"הנתון המנוכה עונתיות וקו המגמה של הלמ\"ס."),
        "recent_aria": (f"כניסות תיירים חודשיות, {_mname(monthly[0]['t'])} עד "
                        f"{_mname(last['t'])}"),
        "recent_caption": "כניסות תיירים לפי חודש (אלפים)",
        "countries_note": (f"{len(top)} ארצות האזרחות שמהן הגיעו הכי הרבה תיירים מתחילת "
                           f"{ytd_now['year'] if ytd_now else lt[0]}."),
        "countries_aria": "תיירים לפי ארץ אזרחות מתחילת השנה",
        "countries_caption": "תיירים לפי ארץ אזרחות (אלפים)",
        "countries_month_col": f"{_mname(lt)}",
        "continents_aria": "תיירים לפי יבשת מתחילת השנה",
        "continents_caption": "תיירים לפי יבשת (אלפים)",
        "crossings_aria": "תיירים לפי מעבר גבול, מתחילת השנה, שלוש שנים",
        "crossings_caption": "תיירים לפי מעבר גבול מתחילת השנה (אלפים)",
        "crossings_note": (f"כניסות תיירים מתחילת השנה לפי מעבר הגבול, "
                           f"{fmt.join_he(str(y) for y in t4_years)}, באותם חודשים בכל שנה. "
                           + (f"{dominant['name']} ({_k(dominant['ytd'][-1])} אלף ב-"
                              f"{t4_years[-1]}, {fmt.pct(dominant['ytd'][-1] / tour_ytd)} "
                              f"מהתיירים) מופיע רק בטבלה, כדי שהשאר ייראו בתרשים."
                              if dominant else "")),
        "span": span,
        "month_label": month_lbl,
    })
    if air:
        labels.update({
            "air_note": (f"כניסות תיירים בדרך האוויר בכל חודש מאז {_mname(air[0]['t'])}, "
                         f"עם קו המגמה של הלמ\"ס. אפשר לגרור כדי להתמקד בתקופה."),
            "air_aria": f"תיירים בדרך האוויר לפי חודש, {_mname(air[0]['t'])} עד {_mname(air[-1]['t'])}",
            "air_caption": "תיירים בדרך האוויר לפי שנה וחודש (אלפים)",
        })
    if rec_rows:
        labels.update({
            "recovery_note": (f"כניסות התיירים בדרך האוויר ב-{len(rec_rows)} החודשים האחרונים, "
                              f"באחוזים מאותו חודש ב-{base_year}, שנת השיא בנתונים."),
            "recovery_aria": f"תיירים בדרך האוויר באחוזים מרמת {base_year}",
            "recovery_caption": f"תיירים בדרך האוויר לעומת {base_year} (אלפים)",
            "base_year": str(base_year),
        })

    summary = (f"כניסות מבקרים לישראל לפי חודש, ארץ אזרחות ומעבר גבול, מנתוני הלמ\"ס. "
               f"ב{_mname(lt)} נכנסו {_k(month_value)} אלף מבקרים"
               + (f" ({fmt.signed_pct(vis_month_chg)} בשנה)" if vis_month_chg is not None else "")
               + ".")
    desc = (f"כמה תיירים נכנסים לישראל: {_k(month_value)} אלף מבקרים ב{_mname(lt)}"
            + (f", {_k(ytd_now['grand'])} אלף מתחילת השנה" if ytd_now else "")
            + ". נתונים חודשיים לפי ארץ ומעבר גבול.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0]['year']}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "כניסות תיירים לישראל: נתונים חודשיים | הלמ\"ס",
                "description": desc,
                "name": "כניסות תיירים ומבקרים לישראל",
                "alternate_names": ["כניסות מבקרים לישראל", "מספר התיירים בישראל",
                                    "תיירות נכנסת לישראל"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"air": bool(air), "recovery": bool(rec_rows), "crossings": bool(leaves),
                  "continents": bool(continents)},
    }
