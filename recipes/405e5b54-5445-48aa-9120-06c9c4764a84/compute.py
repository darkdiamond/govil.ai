"""חגים בישראל (Ministry of Tourism) — a short list of the main Jewish holidays
and national memorial days, one row each: name, Hebrew date, Gregorian start
and end, and a description. Two XLSX twins (Hebrew and English, same rows and
dates); the Hebrew file drives the page, the English one is only a fallback
for parsing the Hebrew date when the Hebrew cell can't be read.

The core content is the lookup table ("when is holiday X"). The file covers
one holiday cycle (about a year) and the ministry rewrites it in place, so
"this year" is whatever the file says: nothing here reads the clock.

Data check: every row states both a Hebrew date and a Gregorian start date.
compute converts the stated Hebrew date to the Gregorian calendar (a pure
arithmetic Hebrew calendar, Dershowitz & Reingold) and flags rows whose
Gregorian start is far from it, allowing for the eve-of-holiday convention and
the official weekday shifts of the national days. The flag sentence is built
from the data; when every checked row matches, it says so instead.
"""
import re
from datetime import date, timedelta

import pandas as pd

SUMMARY_MAX = 155

# ── Hebrew calendar (Calendrical Calculations; R.D. == date.toordinal()) ──
# Months: 1 Nisan … 6 Elul, 7 Tishrei … 12 Adar (Adar I in a leap year),
# 13 Adar II.
HEBREW_EPOCH = -1373427


def _leap(y):
    return (7 * y + 1) % 19 < 7


def _last_month(y):
    return 13 if _leap(y) else 12


def _elapsed(y):
    months = (235 * y - 234) // 19
    parts = 12084 + 13753 * months
    day = 29 * months + parts // 25920
    return day + 1 if (3 * (day + 1)) % 7 < 3 else day


def _correction(y):
    ny0, ny1, ny2 = _elapsed(y - 1), _elapsed(y), _elapsed(y + 1)
    if ny2 - ny1 == 356:
        return 2
    if ny1 - ny0 == 382:
        return 1
    return 0


def _new_year(y):
    return HEBREW_EPOCH + _elapsed(y) + _correction(y)


def _days_in_year(y):
    return _new_year(y + 1) - _new_year(y)


def _month_len(m, y):
    n = _days_in_year(y)
    if m in (2, 4, 6, 10, 13):
        return 29
    if m == 12 and not _leap(y):
        return 29
    if m == 8 and n % 10 != 5:          # Heshvan long only in 355/385-day years
        return 29
    if m == 9 and n % 10 == 3:          # Kislev short in 353/383-day years
        return 29
    return 30


def _fixed_from_hebrew(y, m, d):
    total = _new_year(y) + d - 1
    if m < 7:
        for mm in range(7, _last_month(y) + 1):
            total += _month_len(mm, y)
        for mm in range(1, m):
            total += _month_len(mm, y)
    else:
        for mm in range(7, m):
            total += _month_len(mm, y)
    return total


def _hebrew_year_of(fixed):
    approx = (fixed - HEBREW_EPOCH) * 98496 // 35975351 + 1
    y = approx - 1
    while _new_year(y + 1) <= fixed:
        y += 1
    return y


HE_MONTH_NAMES = {1: "ניסן", 2: "אייר", 3: "סיוון", 4: "תמוז", 5: "אב",
                  6: "אלול", 7: "תשרי", 8: "חשוון", 9: "כסלו", 10: "טבת",
                  11: "שבט", 12: "אדר", 13: "אדר ב'"}

# Spellings seen in Hebrew-date cells → month number (longest first).
HE_MONTH_WORDS = [("מרחשוון", 8), ("מרחשון", 8), ("חשוון", 8), ("חשון", 8),
                  ("כסליו", 9), ("כסלו", 9), ("טבת", 10), ("שבט", 11),
                  ("אדר ב", 13), ("אדר א", 12), ("אדר", 12), ("ניסן", 1),
                  ("אייר", 2), ("סיוון", 3), ("סיון", 3), ("תמוז", 4),
                  ("אלול", 6), ("תשרי", 7), ("אב", 5)]
EN_MONTH_WORDS = [("marcheshvan", 8), ("cheshvan", 8), ("heshvan", 8),
                  ("kislev", 9), ("tevet", 10), ("teves", 10), ("shevat", 11),
                  ("shvat", 11), ("sh'vat", 11), ("adar ii", 13), ("adar i", 12),
                  ("adar", 12), ("nisan", 1), ("nissan", 1), ("iyyar", 2),
                  ("iyar", 2), ("sivan", 3), ("tammuz", 4), ("tamuz", 4),
                  ("elul", 6), ("tishrei", 7), ("tishri", 7), ("av", 5)]

GEM = {"א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9,
       "י": 10, "כ": 20, "ל": 30, "מ": 40, "נ": 50, "ס": 60, "ע": 70, "פ": 80,
       "צ": 90, "ק": 100, "ר": 200, "ש": 300, "ת": 400}

HE_MONTH_RE = re.compile(
    "ב(" + "|".join(re.escape(w) for w, _ in HE_MONTH_WORDS) + ")(?![א-ת])")
EN_MONTH_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w, _ in EN_MONTH_WORDS) + r")\b")
HE_DAY_RE = re.compile("([א-ת]{1,2})[\"']([א-ת]?)")


def _norm_quotes(s):
    return (str(s).replace("״", '"').replace("׳", "'").replace("“", '"')
            .replace("”", '"').replace("’", "'").replace("‘", "'"))


def _parse_he(s):
    s = _norm_quotes(s)
    mm = HE_MONTH_RE.search(s)
    dm = HE_DAY_RE.search(s)
    if not mm or not dm:
        return None
    letters = dm.group(1) + dm.group(2)
    if any(ch not in GEM for ch in letters):
        return None
    day = sum(GEM[ch] for ch in letters)
    if not 1 <= day <= 30:
        return None
    month = dict(HE_MONTH_WORDS)[mm.group(1)]
    return month, day


def _parse_en(s):
    s = _norm_quotes(s).lower()
    mm = EN_MONTH_RE.search(s)
    dm = re.search(r"(\d{1,2})", s)
    if not mm or not dm:
        return None
    day = int(dm.group(1))
    if not 1 <= day <= 30:
        return None
    return dict(EN_MONTH_WORDS)[mm.group(1)], day


def _gematria(n):
    """1..999 → Hebrew numerals with geresh/gershayim (15 → ט"ו)."""
    out = ""
    while n >= 400:
        out += "ת"
        n -= 400
    for v, ch in ((300, "ש"), (200, "ר"), (100, "ק")):
        if n >= v:
            out += ch
            n -= v
    if n in (15, 16):
        out += "ט" + ("ו" if n == 15 else "ז")
        n = 0
    for v, ch in ((90, "צ"), (80, "פ"), (70, "ע"), (60, "ס"), (50, "נ"),
                  (40, "מ"), (30, "ל"), (20, "כ"), (10, "י")):
        if n >= v:
            out += ch
            n -= v
    for v, ch in ((9, "ט"), (8, "ח"), (7, "ז"), (6, "ו"), (5, "ה"),
                  (4, "ד"), (3, "ג"), (2, "ב"), (1, "א")):
        if n >= v:
            out += ch
            n -= v
    if len(out) == 1:
        return out + "'"
    return out[:-1] + '"' + out[-1]


def _year_he(y):
    return _gematria(y % 1000)


def _month_name(m, y):
    if m == 12 and _leap(y):
        return "אדר א'"
    return HE_MONTH_NAMES[m]


def _expected(md, start):
    """Gregorian date of the stated Hebrew (month, day) nearest to `start`."""
    month, day = md
    s = start.toordinal()
    hy = _hebrew_year_of(s)
    best = None
    for y in (hy - 1, hy, hy + 1):
        months = [month]
        if month == 12 and _leap(y):
            months = [13, 12]           # plain "אדר" in a leap year = Adar II
        if month == 13 and not _leap(y):
            months = [12]
        for m in months:
            if day > _month_len(m, y):
                continue
            e = _fixed_from_hebrew(y, m, day)
            key = (abs(s - e), y, m)
            if best is None or key < best[0]:
                best = (key, y, m, e)
    if best is None:
        return None
    _, y, m, e = best
    return y, m, day, date.fromordinal(e)


# Start may be the eve (−1) or the day itself; national days move up to
# −2/+1 days for Shabbat. Anything beyond this window is flagged.
DIFF_MIN, DIFF_MAX = -3, 2

WEEKDAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
GREG_MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
               "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _weekday(x):
    w = WEEKDAYS[x.weekday()]
    return w if w == "שבת" else "יום " + w


def _clean(s):
    return re.sub(r"\s+", " ", str(s).replace("\xa0", " ")).strip()


def _d(x):
    return f"{x.day}.{x.month}.{x.year}"


def _parse_date(s):
    s = _clean(s)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        v = pd.to_datetime(s, format=fmt, errors="coerce")
        if not pd.isna(v):
            return v.date()
    return None


def _join_he(names):
    names = list(names)
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " " + _and(names[-1])


def _and(word):
    return ("ו-" + word) if word[:1].isdigit() else ("ו" + word)


def _days_word(n):
    return "יום אחד" if n == 1 else f"{n} ימים"


def _occ_word(n):
    return "מועד אחד" if n == 1 else f"{n} מועדים"


def _rows(he, en):
    en_by_key = {}
    if en is not None and len(en):
        e = en.copy()
        e["_k"] = e["HolidayStart"].map(_clean) + "|" + e["HolidayEnds"].map(_clean)
        e["_hd"] = e["Hebrew_Date"].map(_clean)
        for k, hd in sorted(zip(e["_k"], e["_hd"])):
            en_by_key.setdefault(k, hd)
    rows = []
    for _, r in he.iterrows():
        name = _clean(r["Name"])
        if not name:
            continue
        start = _parse_date(r["HolidayStart"])
        end = _parse_date(r["HolidayEnds"])
        if start is not None and end is not None and end < start:
            end = None
        hd = _clean(r["HebrewDate"])
        md = _parse_he(hd)
        k = _clean(r["HolidayStart"]) + "|" + _clean(r["HolidayEnds"])
        if md is None and k in en_by_key:
            md = _parse_en(en_by_key[k])
        desc = _clean(r["FullDescription"]) or _clean(r["ShortDescription"])
        rows.append({"name": name, "hd": hd, "md": md, "start": start,
                     "end": end, "desc": desc})
    for row in rows:
        row["status"] = "unchecked"
        row["expected"] = None
        if row["md"] is not None and row["start"] is not None:
            ex = _expected(row["md"], row["start"])
            if ex is not None:
                y, m, d, e = ex
                diff = (row["start"] - e).days
                row["hyear"] = y
                row["expected"] = {"date": e, "he": f"{_gematria(d)} ב{_month_name(m, y)} {_year_he(y)}"}
                row["status"] = "ok" if DIFF_MIN <= diff <= DIFF_MAX else "mismatch"
        row["days"] = ((row["end"] - row["start"]).days
                       if row["start"] is not None and row["end"] is not None else None)
        if row["days"] == 0:
            row["days"] = 1
    far = date(9999, 12, 31)
    rows.sort(key=lambda r: (r["start"] or far, r["end"] or far, r["name"], r["hd"], r["desc"]))
    return rows


def compute(frames):
    rows = _rows(frames["he"], frames.get("en"))
    n = len(rows)
    dated = [r for r in rows if r["start"] is not None]
    nd = len(dated)
    checked = [r for r in rows if r["status"] != "unchecked"]
    bad = [r for r in rows if r["status"] == "mismatch"]

    first, last = (dated[0], dated[-1]) if dated else (None, None)
    greg_years = sorted({r["start"].year for r in dated})
    hyears = sorted({r["hyear"] for r in rows if r.get("hyear")})
    years_disp = (f"{greg_years[0]}–{greg_years[-1]}" if len(greg_years) > 1
                  else (str(greg_years[0]) if greg_years else "0"))
    years_txt = (f"{greg_years[0]}-{greg_years[-1]}" if len(greg_years) > 1
                 else (str(greg_years[0]) if greg_years else ""))
    hyears_txt = "-".join(_year_he(y) for y in ([hyears[0], hyears[-1]] if len(hyears) > 1 else hyears))

    # Distinct calendar days covered by [start, end) of each dated row.
    covered = set()
    for r in dated:
        span = r["days"] or 1
        for i in range(span):
            covered.add(r["start"] + timedelta(days=i))
    by_month = {}
    for dd in covered:
        by_month[(dd.year, dd.month)] = by_month.get((dd.year, dd.month), 0) + 1
    month_names = {}
    for r in dated:
        span = r["days"] or 1
        for i in range(span):
            dd = r["start"] + timedelta(days=i)
            month_names.setdefault((dd.year, dd.month), [])
            if r["name"] not in month_names[(dd.year, dd.month)]:
                month_names[(dd.year, dd.month)].append(r["name"])
    months_axis = []
    if dated:
        y, m = dated[0]["start"].year, dated[0]["start"].month
        endkey = max(by_month) if by_month else (y, m)
        while (y, m) <= endkey:
            months_axis.append((y, m))
            m += 1
            if m == 13:
                y, m = y + 1, 1
    chart_months = {
        "labels": [f"{GREG_MONTHS[m - 1]} {y}" for y, m in months_axis],
        "days": [by_month.get(k, 0) for k in months_axis],
        "names": [", ".join(month_names.get(k, [])) for k in months_axis],
    }

    # ── table rows ──
    table = []
    for r in rows:
        note = ""
        if r["status"] == "ok":
            check = "תואם"
        elif r["status"] == "mismatch":
            check = "לא תואם"
            note = f"לפי הלוח העברי {r['expected']['he']} חל ב-{_d(r['expected']['date'])}"
        else:
            check = "לא נבדק"
        sub = []
        if r["start"]:
            sub.append(_weekday(r["start"]))
        if r["days"] is not None:
            sub.append(_days_word(r["days"]))
        multi = r["end"] is not None and (r["days"] or 1) > 1
        table.append({
            "name": r["name"],
            "hd": r["hd"] or "תאריך עברי לא צוין",
            "start": _d(r["start"]) if r["start"] else "לא צוין",
            "end": _d(r["end"]) if r["end"] else "",
            "days": r["days"] if r["days"] is not None else "",
            "multi": multi,
            "sub": ", ".join(sub),
            "check": check,
            "check_note": note,
            "ok": r["status"] == "ok",
            "bad": r["status"] == "mismatch",
        })
    descs = [{"name": r["name"], "hd": r["hd"], "when": (_d(r["start"]) if r["start"] else ""),
              "text": r["desc"]} for r in rows if r["desc"]]

    timeline = {
        "names": [r["name"] for r in dated],
        "start": [r["start"].isoformat() for r in dated],
        "end": [(r["end"] or (r["start"] + timedelta(days=1))).isoformat() for r in dated],
        "days": [r["days"] or 1 for r in dated],
        "bad": [r["status"] == "mismatch" for r in dated],
    }

    # ── insights ──
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if nd >= 2:
        t = (f"בקובץ {n} חגים ומועדים, מ{first['name']} ב-{_d(first['start'])} "
             f"ועד {last['name']} ב-{_d(last['start'])}")
        if hyears_txt:
            t += f" (שנה עברית {hyears_txt})" if len(hyears) == 1 else f" (השנים העבריות {hyears_txt})"
        t += "."
        if len(greg_years) == 2:
            c0 = sum(1 for r in dated if r["start"].year == greg_years[0])
            c1 = nd - c0
            lead = ("זהו מחזור חגים אחד, וכל חג מופיע בו פעם אחת: "
                    if len({r["name"] for r in dated}) == nd else "")
            t += (f" {lead}{_occ_word(c0)} בשנת {greg_years[0]} "
                  f"{_and(_occ_word(c1))} בשנת {greg_years[1]}.")
        add("span", t)

    multi = [r for r in dated if (r["days"] or 1) > 1]
    if multi:
        mx = max(r["days"] for r in multi)
        top = [r for r in multi if r["days"] == mx]
        rest = sorted({r["days"] for r in multi if r["days"] < mx}, reverse=True)
        t = (f"{_join_he([r['name'] for r in top])} "
             f"{'הוא המועד הארוך' if len(top) == 1 else 'הם המועדים הארוכים'} ביותר בקובץ: "
             f"{_days_word(mx)} ({_d(top[0]['start'])} עד {_d(top[0]['end'])}).")
        if rest:
            nxt = rest[0]
            names2 = [r["name"] for r in multi if r["days"] == nxt]
            t += (f" אחריו {_join_he(names2)}, {_days_word(nxt)}"
                  f"{' כל אחד' if len(names2) > 1 else ''}.")
        if len(multi) == 1:
            t += f" זהו המועד היחיד מתוך {nd} שנמשך יותר מיום אחד."
        else:
            t += f" בסך הכול {len(multi)} מתוך {nd} המועדים נמשכים יותר מיום אחד."
        add("longest", t)

    if by_month:
        vals = sorted(by_month.values(), reverse=True)
        if len(vals) == 1 or vals[0] > vals[1]:
            k = max(by_month, key=lambda kk: (by_month[kk], -kk[0], -kk[1]))
            nm = month_names.get(k, [])
            add("busiest",
                f"{GREG_MONTHS[k[1] - 1]} {k[0]} הוא החודש העמוס ביותר: {_days_word(by_month[k])} "
                f"של חג ומועד ({_join_he(nm)}), מתוך {len(covered)} ימים שמכוסים בקובץ כולו.")

    if bad:
        parts = []
        for r in bad[:2]:
            parts.append(f"ב{r['name']} התאריך הלועזי {_d(r['start'])} אינו מתאים לתאריך "
                         f"העברי שבקובץ ({r['hd']}): לפי הלוח העברי {r['expected']['he']} "
                         f"חל ב-{_d(r['expected']['date'])}")
        t = "; ".join(parts) + "."
        if len(bad) > 2:
            t += f" כך גם ב-{len(bad) - 2} שורות נוספות, המסומנות בטבלה."
        t += " כדאי לבדוק את המועד הזה מול לוח שנה עברי."
        add("mismatch", t)
    elif len(checked) >= 2:
        t = f"כל {len(checked)} התאריכים הלועזיים שנבדקו מתאימים לתאריך העברי שלצידם בלוח העברי"
        if len(checked) < n:
            t += f" ({n - len(checked)} שורות לא נבדקו כי התאריך העברי שלהן לא פוענח)"
        add("allok", t + ".")

    if nd >= 2:
        latest_ok = [r for r in dated if r["status"] != "mismatch"]
        if latest_ok:
            lo = latest_ok[-1]
            later_bad = [r for r in dated if r["status"] == "mismatch" and r["start"] > lo["start"]]
            note = (f" (לא כולל {_join_he([r['name'] for r in later_bad])}, שתאריכו אינו תואם)"
                    if later_bad else "")
            add("latest",
                f"החג האחרון בקובץ הוא {lo['name']} ב-{_d(lo['start'])}{note}. "
                f"הקובץ מכסה את התאריכים עד מועד זה בלבד, ולכל חג מופיע בו תאריך אחד.")

    # ── KPIs ──
    kpis = {
        "count": {"value": n, "display": f"{n:,}", "tone": "brand"},
        "years": {"value": len(greg_years), "display": years_disp, "tone": "brand"},
        "covered": {"value": len(covered), "display": f"{len(covered):,}", "tone": "info"},
        "mismatch": {"value": len(bad), "display": f"{len(bad):,}",
                     "tone": "danger" if bad else "ok"},
    }

    summary = (f"מתי חל כל חג בישראל: תאריכי {n} חגים וימי זיכרון בלוח העברי והלועזי"
               f"{' ל-' + years_txt if years_txt else ''}, כמה ימים נמשך כל חג והסבר קצר. נתוני משרד התיירות.")
    if len(summary) > SUMMARY_MAX:
        summary = f"מתי חל כל חג בישראל: תאריכי {n} חגים וימי זיכרון בלוח העברי והלועזי, עם הסבר על כל חג."

    lede = (f"רשימת {n} החגים והמועדים המרכזיים בישראל, כפי שמפרסם משרד התיירות: "
            f"לכל מועד התאריך העברי, תאריך ההתחלה והסיום בלוח הלועזי ומספר הימים.")
    if first and last:
        lede += f" התאריכים בקובץ מתפרסים מ-{_d(first['start'])} עד {_d(last['start'])}."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["חגים", "לוח עברי", "חגי ישראל", "ימי זיכרון", "תיירות"],
            "related_ids": ["a416609e-f68a-4fea-b278-657f92bfbe73",
                            "aa55c19d-afdd-4ff4-8b1e-1cb0d59d2b26",
                            "0914a18b-b2c9-4e2f-bc25-0a8dfc912acf"],
            **({"temporal_coverage": (f"{first['start'].isoformat()}/{last['start'].isoformat()}")}
               if first else {}),
            "spatial_coverage": "ישראל",
        },
        "kpi_order": ["count", "years", "covered", "mismatch"],
        "kpis": kpis,
        "charts": {"timeline": timeline, "months": chart_months},
        "tables": {"holidays": table, "descs": descs,
                   "months": [{"label": l, "days": v, "names": nm}
                              for l, v, nm in zip(chart_months["labels"], chart_months["days"],
                                                  chart_months["names"])]},
        "flags": {"has_timeline": nd >= 2, "has_months": len(months_axis) >= 2,
                  "timeline_small": nd <= 20, "months_small": len(months_axis) <= 20,
                  "has_bad": bool(bad), "has_descs": bool(descs)},
        "labels": {
            "lede": lede,
            "kpi_count": "חגים ומועדים בקובץ",
            "kpi_years": "השנים הלועזיות שבקובץ",
            "kpi_covered": "ימי חג ומועד בסך הכול",
            "kpi_mismatch": "שורות שהתאריך הלועזי בהן אינו תואם לתאריך העברי",
            "table_lede": (f"{n} המועדים לפי סדר כרונולוגי. תאריך ההתחלה הוא לרוב ערב החג; "
                           f"עמודת הבדיקה משווה כל תאריך לועזי לתאריך העברי שלצידו."),
            "table_caption": f"תאריכי {n} החגים והמועדים בקובץ",
            "timeline_lede": (f"{nd} המועדים על ציר הזמן, מ-{_d(first['start'])} עד {_d(last['end'] or last['start'])}. "
                              f"אורך כל פס הוא משך המועד בימים." if first else ""),
            "timeline_aria": (f"ציר זמן של {nd} חגים ומועדים בין {_d(first['start'])} ל-{_d(last['start'])}"
                              if first else ""),
            "months_lede": (f"מספר ימי החג והמועד בכל חודש לועזי, מ{chart_months['labels'][0]} עד {chart_months['labels'][-1]}."
                            if months_axis else ""),
            "months_aria": (f"ימי חג ומועד לפי חודש לועזי, {len(months_axis)} חודשים" if months_axis else ""),
        },
        "insights": insights,
    }
