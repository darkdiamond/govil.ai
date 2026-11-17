"""מורשעים בדין במשפטים פליליים: CBS's yearly release on Israeli residents
convicted in criminal trials, by verdict year.

The release is a set of chart-data sheets ("תרשים N - ..."). Two of them
carry a series of selected verdict years (defendants / convicted /
recidivists since 2000, and the conviction rate by age group); the rest show
ONE verdict year. The source reads two editions (`history_releases: 2`), so
each grid stacks this year's and last year's release. CBS renumbers and
re-lays the charts between editions (the age-group chart flipped from years
down to years across), so every table input (t1..t16, the last three spare,
all optional) is split by edition and each chart is found by its TITLE:

  trend        העומדים לדין ... לפי הרשעה ומועדות         defendants, convicted, recidivists (thousands)
  age_trend    אחוז המורשעים ... קבוצת גיל אחריות פלילית   % convicted: total, adults, minors
  comp         מורשעים בדין ... לפי מין, מועדות ...        % of the convicted by sex, record, group
  minor_off    בקרב קטינים ... לפי קבוצת עבירה             % convicted, minors, by offence group
  minor_pop    בקרב קטינים ... קבוצת אוכלוסייה וקבוצת עבירה
  adult_off    בקרב מבוגרים ... לפי קבוצת עבירה
  adult_pop    בקרב מבוגרים ... קבוצת אוכלוסייה וקבוצת עבירה
  adult_sexpop בקרב מבוגרים ... לפי מין וקבוצת אוכלוסייה
  court        ... לפי סוג בית משפט
  cluster      ... אשכול חברתי-כלכלי של יישוב המגורים
  oecd / oecd_m / oecd_f   convicted per 100,000 in OECD countries (UNODC)

The page shows the newest edition; the older one fills series years the
newest lacks (the newest wins on overlap) and adds last year's offence-group
rates. A chart missing from the newest edition drops its section. A
recognised chart with data rows but no header row raises.
"""
import itertools
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^תרשים\s*\d+[א-ת]?\s*-\s*")
VERDICT = re.compile(r"שנת פסק דין\s+((?:19|20)\d\d)")
REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
HEB = re.compile("[א-ת]")
STEM = re.compile(r"t\d+")
YEAR = re.compile(r"^((?:19|20)\d\d)\s*\*?$")
POINTS = re.compile("[֑-ׇֽֿׁׂׅׄ]")
POP = ("יהודים ואחרים", "ערבים")
TOTAL = "סך הכל"
ISRAEL = "ישראל"
OECD_AVG = "ממוצע OECD"
# Two rates closer than this (percentage points) are "about the same".
FLAT_PP = 1.0
MAX_INSIGHTS = 8


# ── editions and tables ─────────────────────────────────────────────────


def _rel_key(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _int(v):
    try:
        return int(str(v).strip())
    except ValueError:
        return 0


def _cells(df):
    return sorted((c for c in df.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    t = POINTS.sub("", t)
    body = TITLE.sub("", t).strip()
    if "OECD" in t:
        if body.startswith("גברים"):
            return "oecd_m"
        if body.startswith("נשים"):
            return "oecd_f"
        return "oecd"
    if "לפי הרשעה" in t and "העומדים לדין" in t:
        return "trend"
    if "גיל אחריות פלילית" in t and "אחוז המורשעים" in t:
        return "age_trend"
    if body.startswith("מורשעים בדין") and "לפי מין" in t:
        return "comp"
    if "סוג בית משפט" in t:
        return "court"
    if "אשכול חברתי" in t:
        return "cluster"
    for word, who in (("בקרב קטינים", "minor"), ("בקרב מבוגרים", "adult")):
        if word not in t:
            continue
        if "קבוצת אוכלוסייה וקבוצת עבירה" in t:
            return f"{who}_pop"
        if "קבוצת עבירה" in t:
            return f"{who}_off"
        if who == "adult" and "לפי מין וקבוצת אוכלוסייה" in t:
            return "adult_sexpop"
    return None


def _editions(frames):
    """{release key: {"no", "year" (verdict year or None), "tables": {kind: (rows, raw)}}}
    over every non-empty table input; the first stem (by number) to hold a
    kind in an edition wins. `raw` keeps the provisional-year stars."""
    out = {}
    names = sorted((n for n in frames if STEM.fullmatch(n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        cols = _cells(df)
        for no in sorted(df["RELEASE_NO"].unique(), key=lambda x: (_rel_key(x), str(x))):
            g = df[df["RELEASE_NO"] == no]
            g = g.assign(_s=g["SHEET_NO"].map(_int), _r=g["ROW"].map(_int))
            g = g.sort_values(["_s", "_r"], kind="stable")
            raw = [[re.sub(r"\s+", " ", str(v)).strip() for v in r] for r in g[cols].itertuples(index=False)]
            rows = [[cbs.clean(v) for v in r] for r in raw]
            t = _title(rows)
            k = _kind(t)
            if not k:
                continue
            ed = out.setdefault(_rel_key(no), {"no": no, "year": None, "tables": {}})
            m = VERDICT.search(t)
            if m and ed["year"] is None:
                ed["year"] = int(m.group(1))
            if k not in ed["tables"]:
                ed["tables"][k] = (rows, raw)
    return out


# ── parsing ─────────────────────────────────────────────────────────────


def _is_num(c):
    return cbs.num(c) is not None


def _is_label(c):
    return bool(c) and bool(HEB.search(c)) and not _is_num(c) and not c.startswith(("(", "מקור"))


def _clean_label(c):
    return re.sub(r"\s+", " ", POINTS.sub("", c)).strip()


def _series(rows, raw, name):
    """{label: {year: value}}, sorted years, provisional years. Years run
    across a row (labels down column 0) or down a column (labels across a
    header row). None when the sheet holds no year block."""
    stars = set()
    for r in raw:
        for c in r:
            m = YEAR.match(c)
            if m and "*" in c:
                stars.add(int(m.group(1)))
    # years across a row
    for i, r in enumerate(rows):
        ycols = [(j, int(c)) for j, c in enumerate(r) if YEAR.match(c)]
        if len(ycols) >= 3:
            out = {}
            for r2 in rows[i + 1:]:
                lab = _clean_label(cbs.cell(r2, 0))
                if not _is_label(lab):
                    continue
                vals = {y: cbs.val(r2, j) for j, y in ycols}
                if any(v is not None for v in vals.values()):
                    out[lab] = vals
            if not out:
                return None
            return out, sorted(y for _, y in ycols), stars
    # years down a column
    yc = cbs.best_col(rows, lambda c: bool(YEAR.match(c)))
    if yc is None:
        return None
    yrows = [i for i, r in enumerate(rows) if YEAR.match(cbs.cell(r, yc))]
    if len(yrows) < 3:
        return None
    head = None
    for i in range(yrows[0] - 1, -1, -1):
        cells = [(j, _clean_label(c)) for j, c in enumerate(rows[i]) if j != yc and _is_label(c)]
        if any(TITLE.match(c) for c in rows[i] if c):
            break
        if cells:
            head = cells
            break
    if head is None:
        raise ValueError(f"{name}: series header row not found")
    out = {lab: {} for _, lab in head}
    years = []
    for i in yrows:
        y = int(rows[i][yc])
        years.append(y)
        for j, lab in head:
            out[lab][y] = cbs.val(rows[i], j)
    return out, sorted(years), stars


def _matrix(rows, name):
    """{row label: {column label: value}} for a sheet with one header row of
    column labels and data rows below it. A data row whose first cell is a
    number (the total column of a one-row sheet) is labelled סך הכל and that
    cell becomes its סך הכל value. None when there are no data rows."""
    data = [i for i, r in enumerate(rows) if sum(_is_num(c) for c in r) >= 2]
    if not data:
        return None
    first = data[0]
    head = None
    for i in range(first - 1, -1, -1):
        r = rows[i]
        if any(TITLE.match(c) for c in r if c):
            break
        cells = [(j, _clean_label(c)) for j, c in enumerate(r) if c and not c.startswith("(")]
        if len(cells) >= 2 and not any(_is_num(c) for _, c in cells):
            head = cells
            break
    if head is None:
        raise ValueError(f"{name}: header row not found")
    out = {}
    for i in data:
        r = rows[i]
        c0 = cbs.cell(r, 0)
        vals = {lab: cbs.val(r, j) for j, lab in head if j != 0 or not _is_num(c0)}
        if _is_num(c0):
            vals[TOTAL] = cbs.num(c0)
            lab = TOTAL
        else:
            lab = _clean_label(c0)
            vals.pop(lab, None)
        if lab and lab not in out:
            out[lab] = vals
    return out


def _comp(rows, name):
    """{(group, item): {column: value}} for the composition sheet (shares of
    the convicted by sex, record and population group; columns סך הכל,
    מבוגרים, קטינים). None without data rows."""
    data = [i for i, r in enumerate(rows)
            if any(_is_num(c) for c in r) and (_is_label(cbs.cell(r, 0)) or _is_label(cbs.cell(r, 1)))]
    if not data:
        return None
    head = None
    for i in range(data[0] - 1, -1, -1):
        r = rows[i]
        if TOTAL in r and "מבוגרים" in r:
            head = [(j, c) for j, c in enumerate(r) if c in (TOTAL, "מבוגרים", "קטינים")]
            break
    if head is None:
        raise ValueError(f"{name}: header row not found")
    out = {}
    group = ""
    for i in data:
        r = rows[i]
        g = _clean_label(cbs.cell(r, 0))
        if g:
            group = g
        item = _clean_label(cbs.cell(r, 1)) or group
        if item == "מועדות":
            item = "מועדים"
        vals = {c: cbs.val(r, j) for j, c in head}
        if any(v is not None for v in vals.values()):
            out[(group, item)] = vals
    return out


def _countries(rows):
    """[(country, value)] for an OECD sheet, in sheet order."""
    out = []
    for r in rows:
        lab = _clean_label(cbs.cell(r, 0))
        v = cbs.val(r, 1)
        if v is None or not _is_label(lab) or lab == "מדינה":
            continue
        if sum(1 for c in r if c) != 2:
            continue
        out.append((lab, v))
    return out


# ── formatting ──────────────────────────────────────────────────────────


def _r(v, d=1):
    return None if v is None else round(v, d)


def _p(v):
    return "–" if v is None else fmt.pct_of(v)


def _k(v):
    """Thousands as printed: 19.5 → '19.5'."""
    return "–" if v is None else fmt.num_he(v, 1)


def _short(off):
    s = off.replace("עבירות ", "", 1) if off.startswith("עבירות ") else off
    return s


# ── compute ─────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    eds = _editions(frames)
    if not eds:
        raise ValueError("no conviction chart recognised in any table")
    keys = sorted(eds)
    latest = eds[keys[-1]]
    prev = eds[keys[-2]] if len(keys) > 1 else None
    tb = latest["tables"]

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    cands = []

    def add(iid, text):
        if text:
            cands.append({"id": iid, "text_he": text})

    # ── 1. long trend: defendants, convicted, recidivists (thousands) ──
    merged, stars = {}, set()
    for k in keys:  # oldest first, so the newest edition wins on overlap
        t = eds[k]["tables"].get("trend")
        if not t:
            continue
        s = _series(t[0], t[1], "trend")
        if not s:
            continue
        ser, _, st = s
        stars = st
        for lab, vals in ser.items():
            for y, v in vals.items():
                if v is not None:
                    merged.setdefault(lab, {})[y] = v
    want = {"def": "עומדים לדין", "conv": "מורשעים בדין", "rec": "מועדים"}
    if "מורשעים בדין" not in merged:
        raise ValueError("trend: no 'מורשעים בדין' series in any edition")
    tr = {key: merged.get(lab, {}) for key, lab in want.items()}
    tyears = sorted(tr["conv"])
    ly = tyears[-1]
    year = latest["year"] or ly
    conv = tr["conv"][ly]
    dfd = tr["def"].get(ly)
    rec = tr["rec"].get(ly)
    prov = ly in stars
    labels["year"] = str(year)
    labels["prov_note"] = f"נתוני {ly} זמניים." if prov else ""

    flags["trend"] = True
    charts["trend"] = {"x": [str(y) for y in tyears],
                       "series": [{"name": want[key], "data": [_r(tr[key].get(y), 3) for y in tyears]}
                                  for key in ("def", "conv", "rec") if tr[key]]}
    tables["trend"] = [[str(y) + (" (זמני)" if y in stars else ""), _k(tr["def"].get(y)),
                        _k(tr["conv"].get(y)), _k(tr["rec"].get(y))] for y in tyears]
    labels["trend_aria"] = (f"תרשים עמודות: עומדים לדין, מורשעים בדין ומועדים (אלפים), שנות פסק דין נבחרות "
                            f"{tyears[0]}-{ly}")
    labels["trend_note"] = (f"תושבי ישראל שעמדו לדין במשפטים פליליים, מי מהם הורשע ומי מהמורשעים הורשע גם בעבר "
                            f"(מועדים), באלפים, בשנות פסק דין נבחרות {tyears[0]}-{ly}. "
                            "המרווח בין השנים אינו אחיד."
                            if any(b - a > 1 for a, b in itertools.pairwise(tyears)) else
                            f"תושבי ישראל שעמדו לדין, הורשעו והורשעו גם בעבר (מועדים), באלפים, {tyears[0]}-{ly}.")
    kpis["conv"] = {"value": round(conv, 3), "display": _k(conv), "tone": "brand"}
    if dfd is not None:
        kpis["def"] = {"value": round(dfd, 3), "display": _k(dfd), "tone": "brand"}

    py = ly - 1
    pc = tr["conv"].get(py)
    if pc:
        ch = (conv - pc) / pc
        if abs(ch) >= 0.02:
            word = "עלה" if ch > 0 else "ירד"
            add("change", f"מספר המורשעים בדין {word} ל-{_k(conv)} אלף בשנת פסק דין {ly}, "
                f"לעומת {_k(pc)} אלף ב-{py} ({fmt.signed_pct(ch)}).")
        else:
            add("change", f"מספר המורשעים בדין בשנת פסק דין {ly}, {_k(conv)} אלף, דומה לזה של {py} ({_k(pc)} אלף).")
    peak_y = max(tyears, key=lambda y: (tr["conv"][y], -y))
    if peak_y != ly and tr["conv"][peak_y] > 0:
        drop = 1 - conv / tr["conv"][peak_y]
        if drop >= 0.1:
            add("long", f"בשנות פסק הדין שבתרשים, השיא היה ב-{peak_y} עם {_k(tr['conv'][peak_y])} אלף מורשעים. "
                f"ב-{ly} המספר נמוך ממנו ב-{fmt.pct(drop)}.")

    # ── 2. conviction rate by age group, over the years ──
    rate_m = {}
    for k in keys:
        t = eds[k]["tables"].get("age_trend")
        if not t:
            continue
        s = _series(t[0], t[1], "age_trend")
        if not s:
            continue
        ser = s[0]
        # rows may be years (labels across) or groups (years across): normalise to {group: {year: v}}
        for lab, vals in ser.items():
            for y, v in vals.items():
                if v is not None:
                    rate_m.setdefault(lab, {})[y] = v
    total_rate = None
    if rate_m:
        groups = [g for g in (TOTAL, "מבוגרים", "קטינים") if g in rate_m] + \
                 sorted(g for g in rate_m if g not in (TOTAL, "מבוגרים", "קטינים"))
        ryears = sorted({y for g in groups for y in rate_m[g]})
        flags["age_trend"] = True
        charts["age_trend"] = {"x": [str(y) for y in ryears],
                               "series": [{"name": g, "data": [_r(rate_m[g].get(y)) for y in ryears]}
                                          for g in groups]}
        labels["age_cols"] = ["שנת פסק דין"] + groups
        tables["age_trend"] = [[str(y) + (" (זמני)" if y in stars else "")] + [_p(rate_m[g].get(y)) for g in groups]
                               for y in ryears]
        labels["age_aria"] = f"תרשים קווים: אחוז המורשעים מבין העומדים לדין לפי גיל, {ryears[0]}-{ryears[-1]}"
        total_rate = rate_m.get(TOTAL, {}).get(ly)
        ad, mi = rate_m.get("מבוגרים", {}), rate_m.get("קטינים", {})
        if ly in ad and ly in mi:
            kpis["minor_rate"] = {"value": _r(mi[ly]), "display": _p(mi[ly]), "tone": "brand"}
            add("age", f"בשנת פסק דין {ly} הורשעו {_p(ad[ly])} מהמבוגרים שעמדו לדין, לעומת {_p(mi[ly])} מהקטינים.")
            y0 = min(mi)
            if y0 < ly and mi[ly] - mi[y0] >= 5:
                add("minors_trend", f"אחוז ההרשעה בקרב קטינים שעמדו לדין עלה מ-{_p(mi[y0])} ב-{y0} "
                    f"ל-{_p(mi[ly])} ב-{ly}.")
        labels["age_note"] = ("אחוז המורשעים בדין מבין תושבי ישראל שעמדו לדין, לפי גיל האחריות הפלילית "
                              "(קטינים: מתחת לגיל 18 בעת ביצוע העבירה). בקטינים, תיק יכול להסתיים גם בלי הרשעה, "
                              "למשל בהחלטה שהקטין ביצע את העבירה בלי שהורשע.")
    if total_rate is None and dfd:
        total_rate = conv / dfd * 100
    if total_rate is not None:
        kpis["rate"] = {"value": _r(total_rate), "display": _p(total_rate), "tone": "brand"}
        if dfd is not None:
            add("rate", f"בשנת פסק דין {ly} עמדו לדין {_k(dfd)} אלף תושבי ישראל, ו-{_k(conv)} אלף מהם "
                f"הורשעו ({_p(total_rate)}).")

    # ── 3. composition of the convicted ──
    t = tb.get("comp")
    cp = _comp(t[0], "comp") if t else None
    if cp:
        items = list(cp)
        cols = [c for c in (TOTAL, "מבוגרים", "קטינים") if any(cp[i].get(c) is not None for i in items)]
        disp = {"מועדים": "מועדים (הורשעו בעבר)", "חדשים": "חדשים (ללא הרשעה קודמת)"}
        flags["comp"] = True
        charts["comp"] = {"x": [disp.get(i[1], i[1]) for i in items],
                          "series": [{"name": c if c != TOTAL else "כלל המורשעים",
                                      "data": [_r(cp[i].get(c)) for i in items]} for c in cols]}
        labels["comp_cols"] = ["קבוצה"] + [c if c != TOTAL else "כלל המורשעים" for c in cols]
        tables["comp"] = [[f"{i[0]}: {disp.get(i[1], i[1])}" if i[0] != i[1] else disp.get(i[1], i[1])]
                          + [_p(cp[i].get(c)) for c in cols] for i in items]
        labels["comp_aria"] = f"תרשים עמודות: התפלגות המורשעים בדין לפי מין, מועדות וקבוצת אוכלוסייה, {year}"
        bymap = {i[1]: cp[i] for i in items}
        men = bymap.get("גברים", {}).get(TOTAL)
        recp = bymap.get("מועדים", {}).get(TOTAL)
        if recp is not None:
            kpis["rec"] = {"value": _r(recp), "display": _p(recp), "tone": "brand"}
        if men is not None:
            add("men", f"{_p(men)} מהמורשעים בדין בשנת {year} הם גברים."
                + (f" {_p(recp)} מכלל המורשעים הורשעו גם בעבר (מועדים)." if recp is not None else ""))
        parts = [f"{disp.get(i[1], i[1])} {_p(cp[i].get(TOTAL))}" for i in items if cp[i].get(TOTAL) is not None]
        labels["comp_note"] = (f"התפלגות תושבי ישראל שהורשעו בדין בשנת פסק דין {year}, באחוזים מכלל המורשעים "
                               f"בכל קבוצת גיל: {', '.join(parts)}. "
                               "מועדים הם מי שהורשעו גם לפני כן.")
    if "rec" not in kpis and rec is not None and conv:
        kpis["rec"] = {"value": _r(rec / conv * 100), "display": _p(rec / conv * 100), "tone": "brand"}

    # ── 4-5. conviction rate by offence group (adults, minors) ──
    def offence(kind):
        t = tb.get(kind)
        m = _matrix(t[0], kind) if t else None
        if not m or TOTAL not in m:
            return None
        row = m[TOTAL]
        tot = row.get(TOTAL)
        offs = [o for o, v in row.items() if o != TOTAL and v is not None and o.startswith("עבירות")]
        offs.sort(key=lambda o: (-row[o], o))
        if not offs:
            return None
        pm = None
        if prev and kind in prev["tables"]:
            pmm = _matrix(prev["tables"][kind][0], kind)
            pm = pmm.get(TOTAL) if pmm else None
        pyear = prev["year"] if prev else None
        return row, tot, offs, pm, pyear

    for kind, word in (("adult_off", "מבוגרים"), ("minor_off", "קטינים")):
        res = offence(kind)
        if not res:
            continue
        row, tot, offs, pm, pyear = res
        flags[kind] = True
        series = [{"name": f"שנת {year}", "data": [_r(row[o]) for o in offs]}]
        cols = ["קבוצת עבירה", f"שנת {year}"]
        if pm and pyear and pyear != year and any(pm.get(o) is not None for o in offs):
            series.append({"name": f"שנת {pyear}", "data": [_r(pm.get(o)) for o in offs]})
            cols.append(f"שנת {pyear}")
        charts[kind] = {"x": [_short(o) for o in offs], "series": series, "total": _r(tot)}
        labels[f"{kind}_cols"] = cols
        tables[kind] = ([[TOTAL, _p(tot)] + ([_p(pm.get(TOTAL))] if len(cols) > 2 else [])]
                        + [[o, _p(row[o])] + ([_p(pm.get(o))] if len(cols) > 2 else []) for o in offs])
        labels[f"{kind}_aria"] = f"תרשים עמודות: אחוז המורשעים מבין {word} שעמדו לדין לפי קבוצת עבירה, {year}"
        labels[f"{kind}_note"] = (f"אחוז המורשעים בדין מבין ה{word} תושבי ישראל שעמדו לדין בשנת פסק דין {year}, "
                                  f"בקבוצות העבירה שהלמ\"ס בחרה להציג. סך הכל: {_p(tot)}"
                                  + (f" (הקו המקווקו). העמודות הבהירות: שנת {pyear}." if len(series) > 1
                                     else " (הקו המקווקו)."))
        hi, lo = offs[0], offs[-1]
        if row[hi] - row[lo] >= 5:
            add(kind, f"בקרב ה{word} שעמדו לדין ב-{year}, אחוז ההרשעה הגבוה ביותר היה ב{hi} ({_p(row[hi])}) "
                f"והנמוך ביותר ב{lo} ({_p(row[lo])}).")

    # ── 6-7. by population group and offence group ──
    for kind, word in (("adult_pop", "מבוגרים"), ("minor_pop", "קטינים")):
        t = tb.get(kind)
        m = _matrix(t[0], kind) if t else None
        if not m:
            continue
        grp = [g for g in POP if g in m] + sorted(g for g in m if g not in POP and g != TOTAL)
        if not grp:
            continue
        offs = []
        for g in grp:
            for o in m[g]:
                if o not in offs and o != TOTAL:
                    offs.append(o)
        base = m[grp[0]]
        offs.sort(key=lambda o: (-(base.get(o) if base.get(o) is not None else -1), o))
        cats = [TOTAL] + offs
        flags[kind] = True
        charts[kind] = {"x": [_short(o) for o in cats],
                        "series": [{"name": g, "data": [_r(m[g].get(o)) for o in cats]} for g in grp]}
        labels[f"{kind}_cols"] = ["קבוצת עבירה"] + grp
        tables[kind] = [[o] + [_p(m[g].get(o)) for g in grp] for o in cats]
        labels[f"{kind}_aria"] = (f"תרשים עמודות: אחוז המורשעים מבין {word} שעמדו לדין לפי קבוצת אוכלוסייה "
                                  f"וקבוצת עבירה, {year}")
        labels[f"{kind}_note"] = (f"אחוז המורשעים בדין מבין ה{word} שעמדו לדין בשנת פסק דין {year}, בכל קבוצת "
                                  "אוכלוסייה ובקבוצות העבירה שהלמ\"ס בחרה להציג. האחוז מתאר את תוצאות ההליכים "
                                  "בבית המשפט, ואינו מלמד על היקף העבירות בכל קבוצה. תא ריק: הנתון אינו מתפרסם.")

    # ── 8. adults by sex and population group ──
    t = tb.get("adult_sexpop")
    m = _matrix(t[0], "adult_sexpop") if t else None
    if m and TOTAL in m:
        row = m[TOTAL]
        cats = [c for c in row if row[c] is not None]
        cats = [TOTAL] + [c for c in cats if c != TOTAL] if TOTAL in cats else cats
        flags["sexpop"] = True
        charts["sexpop"] = {"x": cats, "y": [_r(row[c]) for c in cats]}
        tables["sexpop"] = [[c, _p(row[c])] for c in cats]
        labels["sexpop_aria"] = f"תרשים עמודות: אחוז המורשעים מבין המבוגרים שעמדו לדין לפי מין וקבוצת אוכלוסייה, {year}"
        mm, ww = row.get("גברים"), row.get("נשים")
        if mm is not None and ww is not None and abs(mm - ww) >= FLAT_PP:
            add("sex", f"בקרב המבוגרים שעמדו לדין ב-{year} הורשעו {_p(mm)} מהגברים ו-{_p(ww)} מהנשים.")

    # ── 9. adults by court type ──
    t = tb.get("court")
    m = _matrix(t[0], "court") if t else None
    if m and TOTAL in m:
        row = m[TOTAL]
        courts = [c for c in row if c != TOTAL and row[c] is not None]
        courts.sort(key=lambda c: (-row[c], c))
        if courts:
            cats = ([TOTAL] if row.get(TOTAL) is not None else []) + courts
            flags["court"] = True
            charts["court"] = {"x": cats, "y": [_r(row[c]) for c in cats]}
            tables["court"] = [[c, _p(row[c])] for c in cats]
            labels["court_aria"] = f"תרשים עמודות: אחוז המורשעים מבין המבוגרים שעמדו לדין לפי סוג בית משפט, {year}"
            hi, lo = courts[0], courts[-1]
            if row[hi] - row[lo] >= 5:
                add("court", f"אחוז ההרשעה של מבוגרים משתנה לפי סוג בית המשפט: {_p(row[hi])} ב{hi}, "
                    f"לעומת {_p(row[lo])} ב{lo} ({year}).")

    # ── 10. adults by socio-economic cluster of the home locality ──
    t = tb.get("cluster")
    m = _matrix(t[0], "cluster") if t else None
    if m and TOTAL in m:
        row = m[TOTAL]
        cl = [c for c in row if c != TOTAL and row[c] is not None and re.match(r"^\d", c)]
        cl.sort(key=lambda c: (_int(re.match(r"\d+", c).group(0)), c))
        if len(cl) >= 2:
            flags["cluster"] = True
            charts["cluster"] = {"x": [f"אשכול {c}" for c in cl], "y": [_r(row[c]) for c in cl],
                                 "total": _r(row.get(TOTAL))}
            tables["cluster"] = ([[TOTAL, _p(row.get(TOTAL))]] if row.get(TOTAL) is not None else []) + \
                                [[f"אשכול {c}", _p(row[c])] for c in cl]
            labels["cluster_aria"] = (f"תרשים עמודות: אחוז המורשעים מבין המבוגרים שעמדו לדין לפי אשכול "
                                      f"חברתי-כלכלי של יישוב המגורים, {year}")
            lo_c, hi_c = cl[0], cl[-1]
            if abs(row[lo_c] - row[hi_c]) >= 3:
                word = "גבוה" if row[lo_c] > row[hi_c] else "נמוך"
                add("cluster", f"בקרב מבוגרים שגרים ביישובים באשכולות {lo_c} (הנמוכים) אחוז ההרשעה {word} יותר: "
                    f"{_p(row[lo_c])}, לעומת {_p(row[hi_c])} באשכולות {hi_c} (הגבוהים), {year}.")

    # ── 11-12. OECD comparison ──
    t = tb.get("oecd")
    oe = _countries(t[0]) if t else []
    if len(oe) >= 3:
        oe.sort(key=lambda kv: (-kv[1], kv[0]))
        flags["oecd"] = True
        charts["oecd"] = {"x": [c for c, _ in oe], "y": [_r(v) for _, v in oe], "israel": ISRAEL, "avg": OECD_AVG}
        tables["oecd"] = [[c, fmt.num_he(v, 1)] for c, v in oe]
        labels["oecd_aria"] = "תרשים עמודות: מורשעים בדין לכל 100,000 נפש במדינות OECD"
        d = dict(oe)
        countries = [c for c, _ in oe if c != OECD_AVG]
        if ISRAEL in d and OECD_AVG in d:
            rank = countries.index(ISRAEL) + 1
            add("oecd", f"בהשוואה בין-לאומית של הלמ\"ס, בישראל הורשעו {fmt.num_he(d[ISRAEL], 1)} איש לכל 100,000 "
                f"נפש, לעומת ממוצע של {fmt.num_he(d[OECD_AVG], 1)} ב-{len(countries)} מדינות OECD שיש עליהן נתון "
                f"(ישראל במקום ה-{rank} מתוכן, מהגבוה לנמוך).")
    om = _countries(tb["oecd_m"][0]) if "oecd_m" in tb else []
    of = _countries(tb["oecd_f"][0]) if "oecd_f" in tb else []
    if len(om) >= 3 and len(of) >= 3:
        dm, dw = dict(om), dict(of)
        both = [c for c in dm if c in dw]
        both.sort(key=lambda c: (-dm[c], c))
        if len(both) >= 3:
            flags["oecd_sex"] = True
            charts["oecd_sex"] = {"x": both, "series": [{"name": "גברים", "data": [_r(dm[c]) for c in both]},
                                                        {"name": "נשים", "data": [_r(dw[c]) for c in both]}]}
            tables["oecd_sex"] = [[c, fmt.num_he(dm[c], 1), fmt.num_he(dw[c], 1)] for c in both]
            labels["oecd_sex_aria"] = "תרשים עמודות: גברים ונשים מורשעים בדין לכל 100,000 נפש במדינות OECD"

    # ── insights, release card, lede, SEO ──
    order = ("change", "rate", "age", "minors_trend", "men", "adult_off", "court", "oecd", "cluster",
             "long", "minor_off", "sex")
    insights = sorted(cands, key=lambda i: order.index(i["id"]) if i["id"] in order else len(order))
    insights = insights[:MAX_INSIGHTS]

    headline = str(rel.get("HEADLINE") or "").strip()
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": headline,
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["lede"] = ("כמה תושבי ישראל עומדים לדין במשפטים פליליים וכמה מהם מורשעים, בקרב מבוגרים וקטינים, "
                      "לפי קבוצת עבירה, סוג בית משפט, מין, קבוצת אוכלוסייה ואשכול חברתי-כלכלי, והשוואה למדינות "
                      "OECD. הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על מורשעים בדין, "
                      f"שנת פסק דין {year}: {_k(conv)} אלף מורשעים"
                      + (f" מתוך {_k(dfd)} אלף שעמדו לדין." if dfd is not None else "."))
    rate_txt = f" ({_p(total_rate)} מהעומדים לדין)" if total_rate is not None else ""
    summary = (f"מורשעים בדין במשפטים פליליים לפי נתוני הלמ\"ס: בשנת פסק דין {ly} הורשעו {_k(conv)} אלף תושבי "
               f"ישראל{rate_txt}. מגמה מאז {tyears[0]}, אחוזי הרשעה לפי גיל, קבוצת עבירה, סוג בית משפט "
               "ואשכול חברתי-כלכלי, והשוואה למדינות OECD.")
    desc = (f"מורשעים בדין בישראל, שנת פסק דין {ly}: {_k(conv)} אלף מורשעים{rate_txt}. "
            "אחוזי הרשעה לפי גיל, עבירה ובית משפט, מגמה והשוואה ל-OECD.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "misc",
        "temporal_coverage": f"{tyears[0]}/{ly}",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "מורשעים בדין במשפטים פליליים: נתוני הלמ\"ס",
            "description": desc,
            "name": "מורשעים בדין במשפטים פליליים",
            "alternate_names": ["מורשעים בדין", "הרשעות פליליות בישראל", "אחוז הרשעה בישראל",
                                "עומדים לדין במשפטים פליליים", "סטטיסטיקה פלילית"],
        },
    }
    return {"agent_data": agent_data, "kpis": kpis, "charts": charts, "insights": insights,
            "labels": labels, "tables": tables, "flags": flags, "release": release}
