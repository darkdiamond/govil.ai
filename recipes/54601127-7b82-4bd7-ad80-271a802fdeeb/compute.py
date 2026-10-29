"""רוקחים בעלי הרשאה אישית: משרד הבריאות.

One row per personal authorisation granted to a pharmacist under the
Pharmacists Regulations (prescription by a pharmacist with a personal
authorisation), 2014. Three columns only:

- `Serial_num`: the authorisation number, a Hebrew letter series prefix plus a
  zero-padded running number ("ר-00001", "ק-00143"). Two series exist today
  (ר, ק); the file does not say what the letters stand for, so the page names
  them by letter and never interprets them.
- `Name`: the pharmacist's name, in mixed order (surname first or last).
- `License`: the pharmacist's licence number (4 to 7 digits, a few odd ones).

There is no city, workplace, authorisation type or date in the file, so the
page says so plainly next to the lookup callout and builds only what the data
carries: series split, licence-number length by series, the length mix along
the authorisation numbering (blocks of numbers), numbering gaps, and
data-quality counts. Licence and authorisation numbers of individuals are
never printed; names are not needed for any aggregate and are not listed.

Growth: the file is replaced in place as authorisations are added. New series
letters flow through (ordered by size), length buckets are data-driven (a
length gets its own bucket once it holds a meaningful number of records), and
the numbering blocks widen (100 -> 200 -> ...) to keep the block chart under
MAX_BLOCKS bars.
"""
import re

import pandas as pd

BLOCK = 100            # authorisation numbers per block on the numbering chart
MAX_BLOCKS = 16        # widen the block size beyond this many blocks
MIN_BLOCK_ROWS = 30    # a block needs this many records to enter the trend rule
TREND_PP = 10.0        # percentage-point change that counts as a shift
BUCKET_MIN = 5         # a licence length with fewer records joins "other"
BUCKET_MIN_SHARE = 0.01
MAX_SERIES = 4         # series shown separately before folding into "אחר"
LEAD_SHARE = 0.4       # a licence length "leads" with at least this share

SERIAL_RX = re.compile(r"^\s*([^\d\s\-־]+)\s*[-־]?\s*(\d+)\s*$")
OTHER_LEN = "אורך חריג או חסר"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{v * 100:.{digits}f}%"


def count_he(k, one, many):
    """'רשומה אחת' / '12 רשומות' (feminine nouns), with a fallback for 0."""
    k = int(k)
    if k == 1:
        return one
    return f"{n(k)} {many}"


def clean(s):
    return " ".join(str(s).replace(" ", " ").split())


def name_key(s):
    s = re.sub(r"[\"'׳״\-־.,]", " ", clean(s))
    return " ".join(sorted(s.split()))


def lic_digits(s):
    s = clean(s)
    s = re.sub(r"\.0+$", "", s)
    return re.sub(r"\D", "", s)


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = " ו-" if last[:1].isdigit() else " ו"
    return ", ".join(items[:-1]) + conj + last


def _prepare(df):
    serial = df["Serial_num"].map(clean)
    parts = serial.str.extract(SERIAL_RX)
    out = pd.DataFrame({
        "serial": serial,
        "prefix": parts[0].fillna(""),
        "num": pd.to_numeric(parts[1], errors="coerce"),
        "name": df["Name"].map(clean),
        "lic": df["License"].map(lic_digits),
    })
    out["series"] = out["prefix"].where(out["prefix"] != "", "ללא סדרה")
    out["lic_len"] = out["lic"].str.len()
    out["nkey"] = out["name"].map(name_key)
    out = out.sort_values(["series", "num", "serial", "lic", "name"],
                          kind="mergesort", na_position="last").reset_index(drop=True)
    return out


def _buckets(df, total):
    vc = df.loc[df["lic_len"] > 0, "lic_len"].value_counts()
    floor = max(BUCKET_MIN, BUCKET_MIN_SHARE * total)
    lens = sorted(int(k) for k, v in vc.items() if v >= floor)
    labels = {L: f"{L} ספרות" for L in lens}
    df["bucket"] = df["lic_len"].map(lambda L: labels.get(int(L), OTHER_LEN))
    order = [labels[L] for L in lens]
    if (df["bucket"] == OTHER_LEN).any():
        order.append(OTHER_LEN)
    return order, lens


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)

    # ---- series ---------------------------------------------------------
    sc = df["series"].value_counts()
    series = sorted(sc.index, key=lambda s: (-int(sc[s]), s))
    s_counts = {s: int(sc[s]) for s in series}
    shown = series[:MAX_SERIES]
    df["series_c"] = df["series"].where(df["series"].isin(shown), "סדרות אחרות")
    series_c = list(shown) + (["סדרות אחרות"] if len(series) > MAX_SERIES else [])

    def s_label(s):
        return s if s == "סדרות אחרות" else f"סדרה {s}"

    # ---- licence-length buckets ----------------------------------------
    b_order, b_lens = _buckets(df, total)
    bc = df["bucket"].value_counts()
    ct = pd.crosstab(df["bucket"], df["series_c"]).reindex(
        index=b_order, columns=series_c, fill_value=0)
    chart_len = {
        "names": b_order,
        "series": [{"name": s_label(s), "values": [int(v) for v in ct[s]]} for s in series_c],
    }
    tbl_len = [{"name": b, "cells": [n(ct.loc[b, s]) for s in series_c],
                "total": n(bc.get(b, 0)), "share": pct(bc.get(b, 0) / total, 1)}
               for b in b_order]

    # ---- numbering blocks ----------------------------------------------
    numbered = df[df["num"].notna() & df["series"].isin(shown)].copy()
    size = BLOCK
    while True:
        nblocks = sum(int(numbered.loc[numbered["series"] == s, "num"].max() - 1) // size + 1
                      for s in shown if (numbered["series"] == s).any())
        if nblocks <= MAX_BLOCKS:
            break
        size *= 2
    numbered["blk"] = ((numbered["num"] - 1) // size).astype(int)
    blocks = []
    for s in shown:
        g = numbered[numbered["series"] == s]
        if g.empty:
            continue
        top = int(g["num"].max())
        for b in range(int(g["blk"].max()) + 1):
            gb = g[g["blk"] == b]
            lo, hi = b * size + 1, min((b + 1) * size, top)
            cnt = gb["bucket"].value_counts()
            k = len(gb)
            blocks.append({
                "series": s, "label": f"{s} {lo}-{hi}", "rows": k,
                "counts": [int(cnt.get(x, 0)) for x in b_order],
                "shares": [round(int(cnt.get(x, 0)) / k * 100, 1) if k else 0.0 for x in b_order],
            })
    chart_blocks = {
        "names": [b["label"] for b in blocks],
        "rows": [b["rows"] for b in blocks],
        "odd": bool(b_order) and b_order[-1] == OTHER_LEN,
        "series": [{"name": x, "share": [b["shares"][i] for b in blocks],
                    "count": [b["counts"][i] for b in blocks]} for i, x in enumerate(b_order)],
    }
    tbl_blocks = [{"name": b["label"], "rows": n(b["rows"]),
                   "cells": [f"{c:,} ({sh:.0f}%)" for c, sh in zip(b["counts"], b["shares"])]}
                  for b in blocks]

    # ---- gaps in numbering ---------------------------------------------
    gaps = {}
    for s in series:
        nums = df.loc[(df["series"] == s) & df["num"].notna(), "num"].astype(int)
        if nums.empty:
            continue
        gaps[s] = (int(nums.max()), int(nums.max()) - nums.nunique())
    gap_total = sum(g for _, g in gaps.values())

    # ---- data quality ---------------------------------------------------
    valid = df[df["lic"] != ""]
    lic_rows = valid.groupby("lic").size()
    rep = lic_rows[lic_rows > 1].index
    rep_df = valid[valid["lic"].isin(rep)]
    both = int((valid.groupby("lic")["series"].nunique() > 1).sum())
    same_series = int((rep_df.groupby(["lic", "series"]).size() > 1)
                      .groupby(level=0).any().sum())
    diff_names = int((rep_df.groupby("lic")["nkey"].nunique() > 1).sum())
    missing_lic = int((df["lic"] == "").sum())
    odd_len = int(((df["bucket"] == OTHER_LEN) & (df["lic"] != "")).sum())
    one_word = int((df["name"].str.split().str.len().fillna(0) <= 1).sum())
    name_multi = int((valid.groupby("nkey")["lic"].nunique() > 1).sum())
    bad_serial = int(df["num"].isna().sum())
    distinct_lic = int(valid["lic"].nunique())

    quality = [
        ("רשומות ללא מספר רישיון", missing_lic),
        ("רשומות עם מספר רישיון באורך חריג", odd_len),
        ("מספרי רישיון המופיעים ביותר מרשומה אחת", len(rep)),
        ("מתוכם: באותה סדרה יותר מפעם אחת", same_series),
        ("מתוכם: בשתי סדרות או יותר", both),
        ("מתוכם: עם שמות שונים או איות שונה של השם", diff_names),
        ("שמות זהים עם מספרי רישיון שונים", name_multi),
        ("רשומות ששמן מילה אחת בלבד", one_word),
        ("מספרי הרשאה שחסרים ברצף המספור", gap_total),
    ]
    if bad_serial:
        quality.append(("מספרי הרשאה שלא במבנה אות ומספר", bad_serial))
    tbl_quality = [{"name": k, "count": n(v)} for k, v in quality]

    # ---- KPIs -----------------------------------------------------------
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "lic": {"value": distinct_lic, "display": n(distinct_lic), "tone": "brand"},
    }
    s1 = series[0]
    kpis["s1"] = {"value": s_counts[s1], "display": n(s_counts[s1]), "tone": "brand"}
    labels_s = {"s1": f"רשומות בסדרה {s1}"}
    if len(series) == 2:
        s2 = series[1]
        kpis["s2"] = {"value": s_counts[s2], "display": n(s_counts[s2]), "tone": "brand"}
        labels_s["s2"] = f"רשומות בסדרה {s2}"
    elif len(series) > 2:
        rest = total - s_counts[s1]
        kpis["s2"] = {"value": rest, "display": n(rest), "tone": "brand"}
        labels_s["s2"] = "רשומות בסדרות האחרות"
    else:
        kpis["s2"] = {"value": gap_total, "display": n(gap_total),
                      "tone": "info" if gap_total else "brand"}
        labels_s["s2"] = "מספרי הרשאה שחסרים ברצף"

    # ---- insights -------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_series():
        if len(series) < 2:
            return None
        parts = [f"סדרה {s}: {n(s_counts[s])} ({pct(s_counts[s] / total)})" for s in series]
        return (f"מספרי ההרשאה מחולקים ל-{n(len(series))} סדרות לפי האות שבראשם. "
                f"{join_he(parts)}. הקובץ אינו מפרט במה נבדלות הסדרות.")
    add("series", ins_series())

    def ins_length():
        if not b_lens:
            return None
        lead = max(b_order, key=lambda b: (int(bc.get(b, 0)), b))
        if lead == OTHER_LEN:
            return None
        share = int(bc[lead]) / total
        if share < LEAD_SHARE:
            return None
        shortest = f"{b_lens[0]} ספרות"
        s = (f"ל-{pct(share)} מהרשומות ({n(bc[lead])}) מספר רישיון בן {lead}, "
             f"האורך הנפוץ ביותר.")
        if shortest != lead and int(bc.get(shortest, 0)):
            s += (f" מספר רישיון קצר, בן {shortest}, מופיע ב-{n(bc[shortest])} "
                  f"רשומות ({pct(int(bc[shortest]) / total)}).")
        return s
    add("length", ins_length())

    def ins_trend():
        main = series[0]
        bl = [b for b in blocks if b["series"] == main and b["rows"] >= MIN_BLOCK_ROWS]
        if len(bl) < 2 or not b_lens:
            return None
        target = f"{b_lens[-1]} ספרות"
        i = b_order.index(target)
        first, last = bl[0], bl[-1]
        a, z = first["shares"][i], last["shares"][i]
        if abs(z - a) < TREND_PP:
            return None
        verb = "עולה" if z > a else "יורד"
        return (f"בסדרה {main}, שיעור בעלי מספר רישיון בן {target} {verb} לאורך המספור: "
                f"{a:.0f}% במספרי ההרשאה {first['label'].split(' ', 1)[1]} "
                f"לעומת {z:.0f}% במספרים {last['label'].split(' ', 1)[1]}.")
    add("trend", ins_trend())

    def ins_both():
        if both < 1:
            return None
        who = "מספר רישיון אחד מופיע" if both == 1 else f"{n(both)} מספרי רישיון מופיעים"
        s = f"{who} ביותר מסדרה אחת, כלומר אותו רוקח רשום עם יותר ממספר הרשאה אחד."
        if len(rep) > both:
            s += (f" יחד עם מספרי רישיון שחוזרים באותה סדרה, {n(len(rep))} מספרי רישיון "
                  f"מופיעים יותר מפעם אחת, ולכן ברשימה {n(distinct_lic)} מספרי רישיון שונים "
                  f"לעומת {n(total)} רשומות.")
        return s
    add("both", ins_both())

    def ins_gaps():
        if gap_total < 1:
            return None
        parts = [f"סדרה {s}: {count_he(g, 'מספר אחד', 'מספרים')} מתוך {n(top)}"
                 for s, (top, g) in gaps.items() if g]
        head = "מספר הרשאה אחד חסר" if gap_total == 1 else f"{n(gap_total)} מספרי הרשאה חסרים"
        return (f"{head} ברצף המספור ({join_he(parts)}). "
                f"הרשימה אינה מציינת אם ההרשאות האלה בוטלו או לא פורסמו.")
    add("gaps", ins_gaps())

    def ins_quality():
        bits = []
        if missing_lic:
            bits.append(count_he(missing_lic, "רשומה אחת ללא מספר רישיון", "רשומות ללא מספר רישיון"))
        if odd_len:
            bits.append(count_he(odd_len, "רשומה אחת עם מספר רישיון באורך חריג",
                                 "רשומות עם מספר רישיון באורך חריג"))
        if same_series:
            bits.append(count_he(same_series, "מספר רישיון אחד שחוזר באותה סדרה",
                                 "מספרי רישיון שחוזרים באותה סדרה"))
        if not bits:
            return None
        return (f"איכות הנתונים: {join_he(bits)}. בחיפוש לפי מספר רישיון כדאי לבדוק גם לפי שם.")
    add("quality", ins_quality())

    # ---- labels ---------------------------------------------------------
    lede = (f"רשימת משרד הבריאות של רוקחים ורוקחות בעלי הרשאה אישית לתת מרשם: "
            f"מרשם לטיפול המשכי למטופלים ומרשם ל\"תרופות רוקח\", לפי תקנות הרוקחים "
            f"(מתן מרשם בידי רוקח בעל הרשאה אישית), התשע\"ד 2014. "
            f"ברשימה {n(total)} רשומות של {n(distinct_lic)} מספרי רישיון שונים, "
            f"בכל אחת שם הרוקח, מספר הרישיון ומספר ההרשאה.")
    ex_serial = f"{s1}-{1:05d}"
    lead_b = max(b_order, key=lambda b: (int(bc.get(b, 0)), b)) if b_order else ""
    labels = {
        "lede": lede,
        "lookup_sub": (f"חיפוש חי בכל {n(total)} הרשומות: שם הרוקח, מספר רישיון הרוקח "
                       f"ומספר ההרשאה (למשל {ex_serial})."),
        "missing_note": ("ברשימה אין יישוב, בית מרקחת, סוג הרשאה או תאריך מתן ההרשאה, "
                         "ולכן אי אפשר לאתר בה רוקח לפי עיר. החיפוש עובד לפי שם, מספר רישיון "
                         "או מספר הרשאה בלבד."),
        "total_kpi": "רשומות (הרשאות אישיות)",
        "lic_kpi": "מספרי רישיון שונים (רוקחים)",
        "s1_kpi": labels_s["s1"],
        "s2_kpi": labels_s["s2"],
        "len_note": (f"כמה ספרות יש במספר הרישיון של בעלי ההרשאות, לפי סדרה. "
                     f"הנפוץ ביותר: {lead_b} ({n(bc.get(lead_b, 0))} רשומות)."),
        "len_aria": (f"גרף עמודות מוערמות: מספר הרשומות לפי אורך מספר הרישיון ולפי סדרה. "
                     f"הנפוץ ביותר: {lead_b}, {n(bc.get(lead_b, 0))} רשומות."),
        "blocks_note": (f"מספרי ההרשאה מחולקים לקבוצות של {n(size)} מספרים, לפי הסדר שבו ניתנו. "
                        f"כל עמודה מראה את התפלגות אורך מספר הרישיון בקבוצה, באחוזים."),
        "blocks_aria": (f"גרף עמודות מוערמות של 100%: התפלגות אורך מספר הרישיון בכל קבוצה של "
                        f"{n(size)} מספרי הרשאה, ב-{n(len(blocks))} קבוצות."),
        "quality_note": ("ספירות בלבד: הדף אינו מציג מספרי רישיון או מספרי הרשאה של רוקחים. "
                         "את הרשומות עצמן אפשר למצוא בחיפוש שמתחת לדף."),
        "notes_year": "התשע\"ד 2014",
        "series_heads": [s_label(s) for s in series_c],
    }

    # ---- agent_data -----------------------------------------------------
    summary = (f"בדיקה אם רוקח בעל הרשאה אישית לתת מרשם, לפי שם, מספר רישיון או מספר הרשאה: "
               f"{n(total)} רשומות, {n(distinct_lic)} מספרי רישיון שונים.")
    if len(summary) > 155:
        summary = f"בדיקה אם רוקח בעל הרשאה אישית לתת מרשם, לפי שם או מספר רישיון: {n(total)} רשומות."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["רוקחים", "הרשאה אישית", "מרשמים", "רישוי מקצועות הבריאות", "בתי מרקחת"],
            "related_ids": [
                "2721d62d-d0da-45fd-93ac-5e7809849222",
                "0952e5e4-8910-477a-8ba3-cde48f4c048f",
                "5ab07db3-c8a9-4399-8247-1ae9f9455003",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"len": chart_len, "blocks": chart_blocks},
        "tables": {"len": tbl_len, "blocks": tbl_blocks, "quality": tbl_quality,
                   "bucket_heads": b_order},
        "insights": insights,
        "labels": labels,
        "flags": {"blocks": len(blocks) >= 2},
    }
