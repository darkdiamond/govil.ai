"""שערי מטבעות החוץ בסוף השנה: CBS's yearly exchange-rate release.

Each edition (early January) carries three tables of Bank of Israel
representative rates, each with an "average" block (two annual rows, then
December of the previous year and every month of the year) and an "end of
period" block of the same shape, then a percent-change block:

  fx_nis   לוח 1  שערי חליפין יציגים של מטבעות חוץ נבחרים בש"ח (NIS per unit)
  nis_fx   לוח 2  שערי חליפין של ש"ח במטבעות נבחרים (the reciprocal of 1)
  usd_fx   לוח 3  שערי חליפין של דולר ארה"ב ביחס למטבעות נבחרים

Tables are recognised by TITLE text (CBS renumbers tables between editions),
never by stem. The recipe reads the last four editions (`history_releases`)
and stitches them: for a period two editions both print, the newer wins.
Percent changes are computed from the rates, not read from the percent
block, so a truncated newest edition still yields consistent numbers.
Currencies come from the header rows (Hebrew name, English name, unit), so
a currency CBS adds flows through. fx_nis and its US dollar column are
required; usd_fx is optional; nis_fx is not read (it is 1 / fx_nis).
"""
import re

import pandas as pd
from govlib import cbs, fmt

HEB = re.compile("[א-ת]")
LAT = re.compile("[A-Za-z]")
REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
AVG_LABEL = 'שערי מט"ח, ממוצעים'
END_LABEL = 'שערי מט"ח, סוף תקופה'
PCT_LABEL = "אחוז שינוי"
# Insight thresholds: a change below FLAT counts as "almost unchanged".
FLAT = 0.005


# ── locating tables ──────────────────────────────────────────────────────


def _edition_key(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _editions(df):
    """[(key, rows)] oldest first: each edition's grid, cleaned."""
    out = []
    for no in sorted(set(df["RELEASE_NO"]), key=lambda n: (_edition_key(n), n)):
        out.append((_edition_key(no), cbs.grid(df[df["RELEASE_NO"] == no])))
    return out


def _title(rows):
    for r in rows[:6]:
        for c in r:
            if c.startswith("לוח") and "שערי חליפין" in c:
                return c
    return ""


def _kind(title, rows):
    head = " ".join(" ".join(r) for r in rows[:4])
    if 'דולר ארה"ב' in title:
        return "usd_fx"
    if 'של ש"ח' in title:
        return "nis_fx"
    if "יציגים" in title and "מטבעות חוץ" in head:
        return "fx_nis"
    return None


def _tables(frames):
    """{kind: [(edition key, rows)]} over every non-empty table input; the
    first stem (by number) holding a kind wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        eds = _editions(df)
        newest = eds[-1][1]
        k = _kind(_title(newest), newest)
        if k and k not in out:
            out[k] = eds
    return out


# ── parsing one edition ──────────────────────────────────────────────────


def _currencies(rows, name):
    """[(col, key, hebrew name, unit)] from the header rows between the
    title and the average block."""
    top = next((i for i, r in enumerate(rows) if any("סוף תקופה וממוצע" in c for c in r)), None)
    if top is None:
        raise ValueError(f"{name}: subtitle '(סוף תקופה וממוצע לתקופה)' not found")
    avg = cbs.row_with(rows, AVG_LABEL, top + 1, name=name)
    head = rows[top + 1:avg]
    eng_row = next((r for r in reversed(head) if any(LAT.search(c) for c in r)), None)
    if eng_row is None:
        raise ValueError(f"{name}: English currency header row not found")
    out = []
    for j, e in enumerate(eng_row):
        if not LAT.search(e):
            continue
        heb = " ".join(cbs.cell(r, j) for r in head
                       if HEB.search(cbs.cell(r, j)) and not LAT.search(cbs.cell(r, j)))
        eng = " ".join(cbs.cell(r, j) for r in head if LAT.search(cbs.cell(r, j)))
        unit = next((int(cbs.num(cbs.cell(r, j))) for r in head
                     if cbs.num(cbs.cell(r, j)) is not None), 1)
        if heb:
            out.append((j, eng, heb, unit))
    if not out:
        raise ValueError(f"{name}: no currency columns")
    return out, avg


def _block(rows, start, cur):
    """{"year": {y: {key: v}}, "month": {(y, m): {key: v}}} for one block."""
    stop = next((i for i in range(start + 1, len(rows))
                 if any(c in (AVG_LABEL, END_LABEL) or c.startswith(PCT_LABEL) for c in rows[i])),
                len(rows))
    out = {"year": {}, "month": {}}
    if stop - start < 2:
        return out
    for i, y, m, end in cbs.periods(rows, start + 1, stop):
        if end is not None:
            continue
        vals = {k: cbs.val(rows[i], j) for j, k, _h, _u in cur}
        vals = {k: v for k, v in vals.items() if v is not None and v > 0}
        if not vals:
            continue
        slot = out["year"].setdefault(y, {}) if m is None else out["month"].setdefault((y, m), {})
        slot.update(vals)
    return out


def _parse(eds, name, need_end=False):
    """Stitched series over editions: newer editions overwrite older ones.
    Returns (currencies {key: (heb, unit)} in the newest edition's column
    order, avg, end)."""
    avg = {"year": {}, "month": {}}
    end = {"year": {}, "month": {}}
    names = {}
    order = []
    for _key, rows in eds:
        cur, a = _currencies(rows, name)
        for _j, k, h, u in cur:
            names[k] = (h, u)
        order = [k for _j, k, _h, _u in cur]
        for kind, part in _block(rows, a, cur).items():
            for p, vals in part.items():
                avg[kind].setdefault(p, {}).update(vals)
        e = next((i for i in range(a + 1, len(rows)) if END_LABEL in rows[i]), None)
        if e is not None:
            for kind, part in _block(rows, e, cur).items():
                for p, vals in part.items():
                    end[kind].setdefault(p, {}).update(vals)
    order += sorted(k for k in names if k not in order)
    return {k: names[k] for k in order}, avg, end


# ── helpers ──────────────────────────────────────────────────────────────


def _r4(v):
    return None if v is None else round(v, 4)


def _rate(v):
    return f"{v:.3f}"


def _chg(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    return cur / prev - 1


def _pc(f, d=1):
    return None if f is None else round(f * 100, d)


def _mlabel(y, m):
    return f"{fmt.MONTHS_SHORT_HE[m - 1]} {y}"


def _label(cur, k):
    h, u = cur[k]
    return f"{h} ({u:,})" if u != 1 else h


def _dname(cur, k):
    return "שקל חדש" if _is_nis(k) else cur[k][0]


def _is_usd(k):
    return "Dollar" in k and ("USA" in k or "U.S" in k)


def _is_eur(k):
    return "Euro" in k


def _is_nis(k):
    return "Sheqel" in k or "Shekel" in k


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "fx_nis" not in tabs:
        raise ValueError("table 'שערי חליפין יציגים של מטבעות חוץ נבחרים בש\"ח' not found")
    cur, avg, end = _parse(tabs["fx_nis"], "fx_nis")
    usd = next((k for k in cur if _is_usd(k)), None)
    if usd is None:
        raise ValueError("fx_nis: US dollar column not found")
    eur = next((k for k in cur if _is_eur(k)), None)

    years = sorted(y for y, v in avg["year"].items() if usd in v)
    if len(years) < 2:
        raise ValueError("fx_nis: fewer than two annual averages")
    ly, py = years[-1], years[-2]
    a_last, a_prev = avg["year"][ly], avg["year"][py]

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── year-end rates ───────────────────────────────────────────────────
    eyears = sorted(y for y, v in end["year"].items() if usd in v)
    ey = eyears[-1] if eyears else None
    if ey is not None:
        e_last = end["year"][ey]
        kpis["usd_end"] = {"value": round(e_last[usd], 4), "display": _rate(e_last[usd]),
                           "tone": "brand"}
        labels["usd_end_kpi"] = f"שער הדולר בסוף {ey} (ש\"ח)"
        if eur and eur in e_last:
            kpis["eur_end"] = {"value": round(e_last[eur], 4), "display": _rate(e_last[eur]),
                               "tone": "brand"}
            labels["eur_end_kpi"] = f"שער האירו בסוף {ey} (ש\"ח)"
    kpis["usd_avg"] = {"value": round(a_last[usd], 4), "display": _rate(a_last[usd]),
                       "tone": "brand"}
    labels["usd_avg_kpi"] = f"שער הדולר הממוצע ב-{ly} (ש\"ח)"
    s_usd = _chg(a_prev.get(usd), a_last[usd])  # shekel's strength vs the dollar
    if s_usd is not None:
        kpis["nis_usd"] = {"value": _pc(s_usd), "display": fmt.signed_pct(s_usd),
                           "tone": "ok" if s_usd >= FLAT else ("warn" if s_usd <= -FLAT else "brand")}
        labels["nis_usd_kpi"] = f"שינוי בערך השקל מול הדולר ב-{ly} (שער ממוצע)"

    # ── changes by currency, latest year ─────────────────────────────────
    ch = []
    for k in cur:
        c = _chg(a_last.get(k), a_prev.get(k))
        if c is not None:
            ch.append((k, c))
    ch.sort(key=lambda kc: (kc[1], kc[0]))
    flags["change"] = len(ch) >= 2
    if flags["change"]:
        charts["change"] = {"names": [_label(cur, k) for k, _ in ch], "values": [_pc(c, 2) for _, c in ch]}
        tables["change"] = [[_label(cur, k), _rate(a_prev[k]), _rate(a_last[k]), fmt.signed_pct(c),
                             fmt.signed_pct(1 / (1 + c) - 1)] for k, c in ch]
        labels["change_cols"] = ["מטבע", f"ממוצע {py}", f"ממוצע {ly}", "שינוי בשער המטבע",
                                 "שינוי בערך השקל"]
        labels["change_note"] = (f"השינוי בשער הממוצע של כל מטבע בשקלים, {ly} לעומת {py}. "
                                 "ערך שלילי: המטבע הוזל והשקל התחזק מולו.")
        labels["change_aria"] = f"שינוי בשער הממוצע של מטבעות החוץ בשקלים, {ly} לעומת {py}"
        down = [k for k, c in ch if c <= -FLAT]
        up = [k for k, c in ch if c >= FLAT]
        n = len(ch)
        if s_usd is not None:
            word = "התחזק" if s_usd > 0 else "נחלש"
            usd_c = _chg(a_last[usd], a_prev[usd])
            if abs(s_usd) < FLAT:
                head = (f"ב-{ly} כמעט לא השתנה השער הממוצע של הדולר: {_rate(a_last[usd])} ש\"ח, "
                        f"לעומת {_rate(a_prev[usd])} ב-{py}")
            else:
                head = (f"ב-{ly} {word} השקל ב-{fmt.pct(abs(s_usd))} מול הדולר: השער הממוצע "
                        f"{'ירד' if usd_c < 0 else 'עלה'} מ-{_rate(a_prev[usd])} ל-{_rate(a_last[usd])} ש\"ח")
            if len(down) == n:
                tail = f", והשקל התחזק מול כל {n} המטבעות שבלוח"
            elif len(up) == n:
                tail = f", והשקל נחלש מול כל {n} המטבעות שבלוח"
            elif down and up:
                tail = f". מול {len(down)} מתוך {n} המטבעות שבלוח השקל התחזק, ומול {len(up)} נחלש"
            else:
                tail = ""
            add("usd", head + tail + ".")
        lo_k, lo_c = ch[0]
        hi_k, hi_c = ch[-1]
        if lo_k != hi_k and lo_c < hi_c and (lo_c <= -FLAT or hi_c >= FLAT):
            add("movers", f"השינויים בשער הממוצע ב-{ly} לפי מטבע נעו בין {fmt.signed_pct(lo_c)} "
                          f"({cur[lo_k][0]}) ל-{fmt.signed_pct(hi_c)} ({cur[hi_k][0]}).")

    # ── annual averages, all currencies, indexed ─────────────────────────
    base_y = years[0]
    idx_keys = [k for k in cur if k in avg["year"].get(base_y, {})]
    charts["index"] = {
        "x": [str(y) for y in years],
        "series": [{"name": _label(cur, k),
                    "data": [None if avg["year"][y].get(k) is None
                             else round(avg["year"][y][k] / avg["year"][base_y][k] * 100, 2)
                             for y in years]} for k in idx_keys],
    }
    labels["index_note"] = (f"השער הממוצע השנתי של כל מטבע בשקלים, כמדד: {base_y} = 100. "
                            "הקו עולה כשהמטבע מתייקר מול השקל.")
    labels["index_aria"] = f"שערי החליפין הממוצעים השנתיים כמדד, {base_y} עד {ly}"
    labels["index_base"] = str(base_y)
    labels["index_cols"] = ["מטבע"] + [str(y) for y in years]
    tables["index"] = [[_label(cur, k)] + ["" if avg["year"][y].get(k) is None else f"{avg['year'][y][k]:.4f}"
                                          for y in years] for k in cur]
    fy = years[0]
    if len(years) >= 3:
        c = _chg(a_last[usd], avg["year"][fy][usd])
        hi = max(years, key=lambda y: (avg["year"][y][usd], y))
        lo = min(years, key=lambda y: (avg["year"][y][usd], y))
        if c is not None and abs(c) >= FLAT:
            extra = ""
            if hi not in (fy, ly):
                extra = f". השיא בתקופה היה ב-{hi}, {_rate(avg['year'][hi][usd])} ש\"ח בממוצע"
            elif lo not in (fy, ly):
                extra = f". השפל בתקופה היה ב-{lo}, {_rate(avg['year'][lo][usd])} ש\"ח בממוצע"
            add("long", f"השער הממוצע של הדולר {'עלה' if c > 0 else 'ירד'} מ-{_rate(avg['year'][fy][usd])} "
                        f"ש\"ח ב-{fy} ל-{_rate(a_last[usd])} ב-{ly} ({fmt.signed_pct(c)}){extra}.")

    # ── year-end: USD and EUR by year ────────────────────────────────────
    flags["yearend"] = len(eyears) >= 2
    if flags["yearend"]:
        def ye(y, k):
            return end["year"].get(y, {}).get(k)
        rows, xs, u_ch, e_ch = [], [], [], []
        for i, y in enumerate(eyears):
            pu = ye(eyears[i - 1], usd) if i and eyears[i - 1] == y - 1 else None
            cu = _chg(ye(y, usd), pu)
            ce = _chg(ye(y, eur), ye(eyears[i - 1], eur) if i and eyears[i - 1] == y - 1 else None) if eur else None
            if i:
                xs.append(str(y))
                u_ch.append(_pc(cu, 2))
                e_ch.append(_pc(ce, 2))
            rows.append([str(y), _rate(ye(y, usd)), "" if cu is None else fmt.signed_pct(cu),
                         "" if ye(y, eur) is None else _rate(ye(y, eur)),
                         "" if ce is None else fmt.signed_pct(ce)])
        charts["yearend"] = {"x": [str(y) for y in eyears],
                             "usd": [_r4(ye(y, usd)) for y in eyears],
                             "eur": [_r4(ye(y, eur)) if eur else None for y in eyears]}
        tables["yearend"] = list(reversed(rows))
        labels["yearend_note"] = ("השער היציג של הדולר והאירו ביום המסחר האחרון של כל שנה. "
                                  "השינוי מחושב לעומת סוף השנה הקודמת.")
        labels["yearend_aria"] = f"שער הדולר והאירו בסוף כל שנה, {eyears[0]} עד {eyears[-1]}"
        cu = _chg(ye(ey, usd), ye(ey - 1, usd))
        if cu is not None:
            lowest = min(eyears, key=lambda y: (ye(y, usd), y))
            highest = max(eyears, key=lambda y: (ye(y, usd), y))
            rank = ""
            if lowest == ey:
                rank = f", הנמוך ביותר בסופי השנים {eyears[0]}-{ey}"
            elif highest == ey:
                rank = f", הגבוה ביותר בסופי השנים {eyears[0]}-{ey}"
            if abs(cu) < FLAT:
                add("yearend", f"בסוף {ey} עמד שער הדולר על {_rate(ye(ey, usd))} ש\"ח, כמעט ללא שינוי "
                               f"לעומת סוף {ey - 1}{rank}.")
            else:
                add("yearend", f"בסוף {ey} עמד שער הדולר על {_rate(ye(ey, usd))} ש\"ח{rank}: "
                               f"{'ירידה' if cu < 0 else 'עלייה'} של {fmt.pct(abs(cu))} מסוף {ey - 1} "
                               f"({_rate(ye(ey - 1, usd))} ש\"ח).")

    # ── monthly averages: USD and EUR ────────────────────────────────────
    months = sorted(p for p, v in avg["month"].items() if usd in v)
    charts["monthly"] = {"x": [_mlabel(y, m) for y, m in months],
                         "usd": [_r4(avg["month"][p].get(usd)) for p in months],
                         "eur": [_r4(avg["month"][p].get(eur)) if eur else None for p in months]}
    tables["monthly"] = [[_mlabel(y, m), _rate(avg["month"][(y, m)][usd]),
                          "" if not eur or avg["month"][(y, m)].get(eur) is None
                          else _rate(avg["month"][(y, m)][eur])] for y, m in reversed(months)]
    labels["monthly_note"] = (f"השער הממוצע של הדולר והאירו בשקלים בכל חודש, "
                              f"{_mlabel(*months[0])} עד {_mlabel(*months[-1])}.")
    labels["monthly_aria"] = f"שער הדולר והאירו הממוצע בכל חודש, {_mlabel(*months[0])} עד {_mlabel(*months[-1])}"
    in_year = [(m, avg["month"][(ly, m)][usd]) for (y, m) in months if y == ly]
    if len(in_year) >= 6:
        hi = max(in_year, key=lambda mv: (mv[1], -mv[0]))
        lo = min(in_year, key=lambda mv: (mv[1], mv[0]))
        spread = hi[1] / lo[1] - 1
        if spread >= FLAT:
            add("range", f"במהלך {ly} נע השער הממוצע החודשי של הדולר בין {_rate(lo[1])} ש\"ח "
                         f"ב{fmt.MONTHS_HE[lo[0] - 1]} ל-{_rate(hi[1])} ש\"ח ב{fmt.MONTHS_HE[hi[0] - 1]}: "
                         f"פער של {fmt.pct(spread)}.")

    # ── month-on-month change of the average, latest year ────────────────
    mom = []
    for y, m in months:
        if y != ly:
            continue
        prev = (y, m - 1) if m > 1 else (y - 1, 12)
        if prev not in avg["month"]:
            continue
        cu = _chg(avg["month"][(y, m)].get(usd), avg["month"][prev].get(usd))
        ce = _chg(avg["month"][(y, m)].get(eur), avg["month"][prev].get(eur)) if eur else None
        if cu is not None:
            mom.append((m, cu, ce))
    flags["mom"] = len(mom) >= 3
    if flags["mom"]:
        charts["mom"] = {"x": [fmt.MONTHS_SHORT_HE[m - 1] for m, _, _ in mom],
                         "usd": [_pc(cu, 2) for _, cu, _ in mom],
                         "eur": [_pc(ce, 2) for _, _, ce in mom]}
        tables["mom"] = [[fmt.MONTHS_HE[m - 1], fmt.signed_pct(cu), "" if ce is None else fmt.signed_pct(ce)]
                         for m, cu, ce in mom]
        labels["mom_note"] = f"השינוי בשער הממוצע החודשי לעומת החודש הקודם, {ly}."
        labels["mom_aria"] = f"שינוי חודשי בשער הדולר והאירו הממוצע, {ly}"
        big = max(mom, key=lambda t: (abs(t[1]), -t[0]))
        if abs(big[1]) >= 0.02:
            add("mom", f"התנודה החודשית החדה ביותר בשער הדולר ב-{ly} הייתה ב{fmt.MONTHS_HE[big[0] - 1]}: "
                       f"{'עלייה' if big[1] > 0 else 'ירידה'} של {fmt.pct(abs(big[1]))} בשער הממוצע לעומת "
                       "החודש הקודם.")

    # ── the dollar against other currencies (usd_fx) ─────────────────────
    flags["dollar"] = False
    if "usd_fx" in tabs:
        dcur, davg, _dend = _parse(tabs["usd_fx"], "usd_fx")
        dy = sorted(davg["year"])
        if ly in davg["year"] and py in davg["year"]:
            dl, dp = davg["year"][ly], davg["year"][py]
            dch = []
            for k in dcur:
                c = _chg(dl.get(k), dp.get(k))
                if c is not None:
                    # Units of currency per dollar: a rise means the dollar strengthened.
                    dch.append((k, c))
            dch.sort(key=lambda kc: (kc[1], kc[0]))
            if len(dch) >= 2 and dy:
                flags["dollar"] = True
                charts["dollar"] = {"names": [_dname(dcur, k) for k, _ in dch],
                                    "values": [_pc(c, 2) for _, c in dch],
                                    "nis": [_is_nis(k) for k, _ in dch]}
                tables["dollar"] = [[_dname(dcur, k), fmt.signed_pct(c)] for k, c in dch]
                labels["dollar_note"] = (f"השינוי בשער הממוצע של הדולר האמריקני ביחס לכל מטבע, {ly} לעומת "
                                         f"{py}. ערך שלילי: הדולר נחלש מול המטבע.")
                labels["dollar_aria"] = f"שינוי בשער הדולר מול מטבעות נבחרים, {ly} לעומת {py}"
                d_eur = next((c for k, c in dch if _is_eur(k)), None)
                d_nis = next((c for k, c in dch if _is_nis(k)), None)
                if d_eur is not None and d_nis is not None and eur and abs(d_eur) >= FLAT:
                    s_eur = _chg(a_prev.get(eur), a_last.get(eur))
                    if d_eur < 0 and d_nis < d_eur and s_eur is not None:
                        add("dollar", f"חלק מהתחזקות השקל מול הדולר ב-{ly} משקף היחלשות עולמית של הדולר: "
                                      f"גם מול האירו הוא נחלש ב-{fmt.pct(abs(d_eur))}. מול האירו עצמו "
                                      + (f"השקל התחזק ב-{fmt.pct(s_eur)}." if s_eur >= FLAT else
                                         f"השקל נחלש ב-{fmt.pct(abs(s_eur))}." if s_eur <= -FLAT else
                                         "השקל כמעט לא השתנה."))
                    elif d_eur > 0 and d_nis > d_eur:
                        add("dollar", f"ב-{ly} התחזק הדולר בעולם (ב-{fmt.pct(d_eur)} מול האירו), "
                                      f"ומול השקל התחזק יותר: ב-{fmt.pct(d_nis)}.")

    # ── release card + text ──────────────────────────────────────────────
    headline = str(rel.get("HEADLINE") or "").strip()
    release = {"title": str(rel.get("TITLE") or "").strip(), "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"])),
               "headline": headline, "url": str(rel.get("PAGE_URL") or "").strip(),
               "pdf": str(rel.get("REPORT_PDF_URL") or "").strip()}

    span = f"{years[0]}-{ly}"
    eur_txt = (f" והאירו {_rate(end['year'][ey][eur])}"
               if ey is not None and eur and eur in end["year"][ey] else "")
    usd_end_txt = (f"בסוף {ey} עמד שער הדולר על {_rate(end['year'][ey][usd])} ש\"ח{eur_txt}. "
                   if ey is not None else "")
    labels["lede"] = (f"שערי החליפין של {len(cur)} מטבעות חוץ מול השקל, לפי ההודעה השנתית של הלשכה המרכזית "
                      f"לסטטיסטיקה (הלמ\"ס) על בסיס השערים היציגים של בנק ישראל: ממוצעים שנתיים וחודשיים "
                      f"ושערי סוף שנה, {span}. {usd_end_txt}"
                      f"השער הממוצע של הדולר ב-{ly} היה {_rate(a_last[usd])} ש\"ח.")
    summary = (f"שערי החליפין של הדולר, האירו ו-{len(cur) - 2} מטבעות נוספים מול השקל, {span}: "
               f"{usd_end_txt}"
               f"השער הממוצע של הדולר ב-{ly}: {_rate(a_last[usd])} ש\"ח.")
    desc = (f"שער הדולר והאירו בסוף כל שנה ושערים ממוצעים מול השקל, {span}. "
            + (f"בסוף {ey}: דולר {_rate(end['year'][ey][usd])} ש\"ח{eur_txt}." if ey is not None
               else f"ממוצע {ly}: דולר {_rate(a_last[usd])} ש\"ח."))

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0]}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "שער הדולר והאירו בסוף השנה | שערי מטבעות החוץ",
                "description": desc,
                "name": "שערי מטבעות החוץ בסוף השנה",
                "alternate_names": ["שער הדולר בסוף השנה", "שער היציג של הדולר", "שערי חליפין שנתיים",
                                    "שער האירו בסוף השנה", "שער מטבע חוץ ממוצע"],
            },
        },
        "kpis": kpis,
        "labels": labels,
        "charts": charts,
        "tables": tables,
        "flags": flags,
        "insights": insights,
        "release": release,
    }
