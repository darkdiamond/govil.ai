"""סיווגי CPC לבקשות פטנט — CPC codes assigned to Israeli patent applications.

One row per (application, CPC code); an application carries 1..100+ codes,
one of them (usually) flagged "ראשי". The data has no dates, but Israeli
application numbers are issued in ascending order, so ranges of application
numbers stand in for filing order ("bands"). Band width is chosen from the
span so the series stays short as numbers grow; the newest band is partial
while numbers are still being issued in it and is labelled and kept out of
trend rules. Duplicate (application, code) rows are collapsed.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"

SECTIONS = ["A", "B", "C", "D", "E", "F", "G", "H", "Y"]
SECTION_HE = {
    "A": "צרכי אנוש",
    "B": "פעולות ביצוע ותובלה",
    "C": "כימיה ומטלורגיה",
    "D": "טקסטיל ונייר",
    "E": "מבנים קבועים",
    "F": "הנדסת מכונות, תאורה, חימום ונשק",
    "G": "פיזיקה",
    "H": "חשמל",
    "Y": "תיוג רוחבי וטכנולוגיות חדשות",
}
CLASS_HE = {
    "A01": "חקלאות", "A23": "מזון", "A24": "טבק ועישון", "A47": "ריהוט וציוד ביתי",
    "A61": "רפואה והיגיינה", "A63": "ספורט ומשחקים", "B01": "תהליכים פיזיקליים וכימיים",
    "B05": "ריסוס וציפוי", "B23": "עיבוד מתכות", "B29": "עיבוד פלסטיק",
    "B32": "מוצרים שכבתיים", "B33": "ייצור תוספתי", "B60": "כלי רכב",
    "B64": "תעופה וחלל", "B65": "הובלה ואריזה", "B82": "ננוטכנולוגיה",
    "C01": "כימיה אי-אורגנית", "C02": "טיפול במים", "C07": "כימיה אורגנית",
    "C08": "פולימרים", "C09": "צבעים ודבקים", "C12": "ביוכימיה ומיקרוביולוגיה",
    "C23": "ציפוי מתכות", "E04": "בנייה", "F16": "רכיבי מכונות",
    "F24": "חימום ואוורור", "F41": "נשק", "F42": "תחמושת ופיצוץ",
    "G01": "מדידה ובדיקה", "G02": "אופטיקה", "G03": "צילום והקרנה",
    "G05": "בקרה וויסות", "G06": "מחשוב", "G08": "איתות", "G09": "הוראה ותצוגה",
    "G10": "אקוסטיקה", "G16": "מידע ותקשוב ייעודיים", "H01": "רכיבים חשמליים",
    "H02": "הפקת חשמל והמרתו", "H03": "מעגלים אלקטרוניים", "H04": "תקשורת",
    "H05": "טכניקות חשמל", "H10": "התקני מוליכים למחצה",
    "Y02": "טכנולוגיות אקלים", "Y10": "תיוג טכני רוחבי",
}
SUBCLASS_HE = {
    "A01G": "גידול צמחים וגננות", "A01K": "גידול בעלי חיים ודגה",
    "A01N": "קוטלי מזיקים ומווסתי צמחים", "A01P": "פעילות ביולוגית של חומרים לחקלאות",
    "A23L": "מזון ותוספי מזון", "A23V": "מפתח אינדקס למזון", "A24B": "טבק",
    "A24F": "מוצרי עישון ואידוי", "A61B": "אבחון וכירורגיה",
    "A61F": "תותבים, חבישות ועזרים רפואיים", "A61J": "מכלים ואמצעים למתן תרופות",
    "A61K": "תכשירים רפואיים וקוסמטיים", "A61L": "חיטוי, עיקור וחומרים לשתלים",
    "A61M": "התקנים להחדרת חומרים לגוף", "A61N": "טיפול בקרינה, חשמל ואור",
    "A61P": "פעילות טיפולית של תרכובות", "A61Q": "תכשירי קוסמטיקה וטיפוח",
    "B01D": "הפרדה וסינון", "B01J": "תהליכים כימיים וזרזים", "B01L": "ציוד מעבדה",
    "B29C": "עיבוד פלסטיק", "B32B": "מוצרים שכבתיים", "B33Y": "ייצור תוספתי (הדפסה בתלת-ממד)",
    "B64C": "כלי טיס", "B64D": "ציוד לכלי טיס", "B65D": "אריזה ומכלים",
    "B82Y": "ננוטכנולוגיה", "C01B": "יסודות לא-מתכתיים ותרכובותיהם",
    "C02F": "טיפול במים ושפכים", "C07B": "שיטות כלליות בכימיה אורגנית",
    "C07C": "תרכובות אציקליות וקרבוציקליות", "C07D": "תרכובות הטרוציקליות",
    "C07F": "תרכובות אורגנו-מתכתיות ואחרות", "C07H": "סוכרים ונוקלאוזידים",
    "C07K": "פפטידים וחלבונים", "C08G": "פולימרים — תגובות עיבוי",
    "C08J": "עיבוד פולימרים", "C08K": "תוספים לפולימרים", "C08L": "הרכבים של פולימרים",
    "C09D": "ציפויים וצבעים", "C12M": "ציוד למיקרוביולוגיה",
    "C12N": "מיקרואורגניזמים, אנזימים והנדסה גנטית", "C12P": "תסיסה וסינתזה אנזימטית",
    "C12Q": "בדיקות באנזימים ובחומצות גרעין", "C12Y": "אנזימים",
    "F41H": "שריון ואמצעי הגנה", "G01B": "מדידת אורך ועובי", "G01N": "בדיקה וניתוח חומרים",
    "G01S": "מכ״ם, ניווט ואיכון", "G02B": "אופטיקה", "G03F": "פוטוליתוגרפיה",
    "G06F": "עיבוד נתונים דיגיטלי", "G06N": "בינה מלאכותית ומודלים חישוביים",
    "G06Q": "מערכות מידע לניהול ומסחר", "G06T": "עיבוד וניתוח תמונה",
    "G06V": "זיהוי תמונה ווידאו", "G16B": "ביואינפורמטיקה",
    "G16H": "מידע רפואי ובריאות דיגיטלית", "H01J": "שפופרות פריקה חשמלית",
    "H01L": "התקני מוליכים למחצה", "H01M": "סוללות ותאי דלק", "H01Q": "אנטנות",
    "H04B": "שידור ותקשורת", "H04L": "העברת מידע דיגיטלי", "H04N": "תקשורת תמונה ווידאו",
    "H04W": "רשתות תקשורת אלחוטיות", "H05B": "חימום ותאורה חשמליים",
    "Y02A": "הסתגלות לשינויי אקלים", "Y02E": "הפחתת פליטות באנרגיה",
    "Y02P": "הפחתת פליטות בייצור ובחקלאות",
}
LIFE = ["A61K", "A61P", "C07K", "C12N"]
# Technology markers tracked across application-number bands (definitions
# by CPC prefix, not data): antibodies, AI, digital health, climate tagging.
MARKERS = [
    ("ab", "נוגדנים", "C07K16/"),
    ("ai", "בינה מלאכותית", "G06N"),
    ("dh", "בריאות דיגיטלית", "G16H"),
    ("y02", "טכנולוגיות אקלים", "Y02"),
]
TITLE_KINDS = [
    ("שיטה או תהליך", r"\b(?:METHODS?|PROCESS(?:ES)?)\b"),
    ("מערכת", r"\bSYSTEMS?\b"),
    ("התקן או מתקן", r"\b(?:DEVICES?|APPARATUS(?:ES)?|ASSEMBL(?:Y|IES))\b"),
    ("תכשיר או הרכב", r"\b(?:COMPOSITIONS?|FORMULATIONS?)\b"),
    ("תרכובות", r"\b(?:COMPOUNDS?|DERIVATIVES?)\b"),
    ("נוגדנים", r"\bANTIBOD(?:Y|IES)\b"),
    ("שימוש או טיפול", r"\b(?:USES?|TREATMENT|TREATING|THERAPY)\b"),
]
PER_APP_BUCKETS = [(1, 1), (2, 2), (3, 4), (5, 6), (7, 9), (10, 14), (15, 19), (20, 29), (30, 49), (50, None)]
WIDTHS = [5000, 10000, 20000, 25000, 50000, 100000, 200000, 500000]
MAX_BANDS = 14
TOP_SUB = 15
TOP_CLASSES_PER_SECTION = 6
TOP_CLASS_TABLE = 15
MINOR_SECTION_SHARE = 0.02
CODE_RE = re.compile(r"^([A-HY])(\d\d)([A-Z])\s*(\d+)/(\d+)$")


def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def sub_label(code):
    name = SUBCLASS_HE.get(code)
    return f"{code} · {name}" if name else code


def class_label(code):
    name = CLASS_HE.get(code)
    return f"{code} {name}" if name else code


def sec_label(s):
    return f"{SECTION_HE.get(s, s)} ({s})"


def _prepare(df):
    out = pd.DataFrame({
        "app": pd.to_numeric(df["מספר בקשה"].str.strip(), errors="coerce"),
        "cpc": df["לבקשה CPC סיווג"].str.strip().str.upper().str.replace(r"\s+", "", regex=True),
        "main": df["ראשי"].str.strip() == "ראשי",
    })
    out = out[out["app"].notna() & out["cpc"].str.match(CODE_RE)].copy()
    out["app"] = out["app"].astype("int64")
    # Collapse duplicate (application, code) rows; a code counts as main if
    # any of its rows is flagged.
    out = (out.groupby(["app", "cpc"], sort=True)["main"].max().reset_index())
    out["sec"] = out["cpc"].str[0]
    out["cls"] = out["cpc"].str[:3]
    out["sub"] = out["cpc"].str[:4]
    return out


def _bands(nums):
    """Band width from the span; the low tail (below the 1st percentile)
    is folded into the first band."""
    q = int(nums.quantile(0.01))
    hi = int(nums.max())
    for w in WIDTHS:
        lo = (q // w) * w
        if (hi // w) * w - lo <= (MAX_BANDS - 1) * w:
            return lo, w
    return (q // WIDTHS[-1]) * WIDTHS[-1], WIDTHS[-1]


def _band_label(start, w, first):
    end = start + w - 1
    return f"עד {LRI}{end:,}{PDI}" if first else f"{LRI}{start:,}–{end:,}{PDI}"


def _top(counts, k):
    counts = counts.sort_index().sort_values(ascending=False, kind="stable")
    return counts.head(k)


# ---------------------------------------------------------------- insights

def ins_lead(main_sec, n_main):
    if n_main == 0:
        return None
    s = main_sec.sort_index().sort_values(ascending=False, kind="stable")
    a, b = s.index[0], s.index[1]
    sa, sb = s.iloc[0] / n_main, s.iloc[1] / n_main
    if sa < 0.25:
        return None
    return (f"לפי הסיווג הראשי, התחום המוביל הוא {sec_label(a)} עם {pct(sa * 100)} מהבקשות, "
            f"ואחריו {sec_label(b)} ({pct(sb * 100)}) — יחד {pct((sa + sb) * 100)} מהבקשות.")


def ins_life(life_apps, n_apps, sub_apps):
    if n_apps == 0 or life_apps / n_apps < 0.3:
        return None
    top = sub_apps.index[0]
    return (f"{pct(life_apps / n_apps * 100)} מהבקשות ({n(life_apps)}) נושאות לפחות סיווג אחד "
            f"במדעי החיים והתרופות ({', '.join(LIFE)}); תת-הסעיף הנפוץ ביותר הוא "
            f"{top}" + (f" ({SUBCLASS_HE[top]})" if top in SUBCLASS_HE else "") + f", המופיע ב-{pct(sub_apps.iloc[0] / n_apps * 100)} מהבקשות.")


def ins_multi(nsec, per_app):
    multi = (nsec >= 2).mean()
    if multi < 0.25:
        return None
    return (f"{pct(multi * 100)} מהבקשות מסווגות ביותר מסעיף טכנולוגי אחד. חציון הסיווגים "
            f"לבקשה הוא {n(per_app.median())}, ובבקשה המסווגת ביותר יש {n(per_app.max())} סיווגים.")


def ins_pair(cooc, nsec):
    if not cooc:
        return None
    (a, b), v = cooc[0]
    multi = int((nsec >= 2).sum())
    if multi == 0 or v / multi < 0.2:
        return None
    return (f"הצירוף הבין-תחומי הנפוץ ביותר הוא {sec_label(a)} עם {sec_label(b)}: {n(v)} בקשות, "
            f"{pct(v / multi * 100)} מהבקשות שמשלבות כמה סעיפים.")


def ins_shift(mix, full_idx, labels, groups):
    if len(full_idx) < 4:
        return None
    last = full_idx[-1]
    prev = full_idx[-4:-1]
    best = None
    for g in groups:
        now = mix[g][last]
        base = sum(mix[g][i] for i in prev) / len(prev)
        d = now - base
        if best is None or abs(d) > abs(best[1]) + 1e-9:
            best = (g, d, base, now)
    g, d, base, now = best
    if abs(d) < 3:
        return None
    word = "עלה" if d > 0 else "ירד"
    return (f"בטווח המספרים המלא האחרון ({labels[last]}) {word} חלקו של {g} בסיווג הראשי ל-"
            f"{pct(now)}, לעומת ממוצע של {pct(base)} בשלושת הטווחים שלפניו — השינוי הגדול "
            f"ביותר בתמהיל התחומים.")


def ins_markers(mk, full_idx, labels):
    if len(full_idx) < 3:
        return None
    first, last = full_idx[0], full_idx[-1]
    rising = []
    for key, name, _ in MARKERS:
        a, b = mk[key][first], mk[key][last]
        if b >= 1 and (a == 0 or b / a >= 1.5):
            rising.append((b - a, name, a, b))
    if not rising:
        return None
    rising.sort(key=lambda r: (-r[0], r[1]))
    parts = [f"{name} מ-{pct(a)} ל-{pct(b)}" for _, name, a, b in rising[:2]]
    return (f"בין הטווח {labels[first]} לטווח {labels[last]} עלה שיעור הבקשות הנושאות סיווגי "
            f"{' ו'.join(parts)}.")


def ins_depth(mean_codes, full_idx, labels):
    if len(full_idx) < 3:
        return None
    peak = max(full_idx, key=lambda i: (mean_codes[i], -i))
    last = full_idx[-1]
    if peak == last or mean_codes[peak] - mean_codes[last] < 1:
        return None
    return (f"מספר הסיווגים הממוצע לבקשה הגיע לשיא של {mean_codes[peak]:.1f} בטווח "
            f"{labels[peak]}, וירד ל-{mean_codes[last]:.1f} בטווח {labels[last]}.")


def ins_main(apps_with_main, n_apps):
    no_main = n_apps - apps_with_main
    if n_apps == 0 or no_main == 0:
        return None
    return (f"{n(no_main)} בקשות ({pct(no_main / n_apps * 100)}) רשומות ללא סיווג ראשי ואינן "
            f"נכללות בניתוחים לפי סיווג ראשי.")


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["cpc"]
    titles = (pd.DataFrame({
        "app": pd.to_numeric(raw["מספר בקשה"].str.strip(), errors="coerce"),
        "en": raw["שם האמצאה באנגלית"].str.strip().str.upper(),
    }).dropna(subset=["app"]))
    titles["app"] = titles["app"].astype("int64")
    titles = titles.sort_values(["app", "en"]).drop_duplicates("app", keep="last").set_index("app")["en"]
    rows_total = len(raw)
    df = _prepare(raw)

    per_app = df.groupby("app").size()
    nsec = df.groupby("app")["sec"].nunique()
    apps = per_app.index
    n_apps = len(apps)
    n_codes = len(df)

    # main classification: first (alphabetical) main code per application
    mains = df[df["main"]].sort_values(["app", "cpc"])
    multi_main = int((mains.groupby("app").size() > 1).sum())
    mains = mains.drop_duplicates("app")
    n_main = len(mains)
    main_sec = mains["sec"].value_counts()

    # section chart: % of apps by main section, % of apps with any code there
    sec_any = df.drop_duplicates(["app", "sec"])["sec"].value_counts()
    secs = [s for s in SECTIONS if s in sec_any.index] + sorted(set(sec_any.index) - set(SECTIONS))
    sections = {
        "names": [sec_label(s) for s in secs],
        "main": [round(float(main_sec.get(s, 0)) / max(n_main, 1) * 100, 1) for s in secs],
        "any": [round(float(sec_any.get(s, 0)) / n_apps * 100, 1) for s in secs],
    }

    # subclasses by number of applications
    sub_apps = _top(df.drop_duplicates(["app", "sub"])["sub"].value_counts(), len(df))
    top_sub = sub_apps.head(TOP_SUB)
    subclasses = {"names": [sub_label(s) for s in top_sub.index],
                  "values": [int(v) for v in top_sub.values],
                  "share": [round(float(v) / n_apps * 100, 1) for v in top_sub.values]}
    life_apps = int(df[df["sub"].isin(LIFE)]["app"].nunique())

    # treemap of main classifications: section -> top classes + other
    main_cls = mains.groupby(["sec", "cls"]).size().reset_index(name="n")
    main_cls = main_cls.sort_values(["n", "cls"], ascending=[False, True])
    tree = []
    for s in secs:
        sub = main_cls[main_cls["sec"] == s]
        if sub.empty:
            continue
        kids = [{"name": class_label(r.cls), "value": int(r.n)}
                for r in sub.head(TOP_CLASSES_PER_SECTION).itertuples()]
        rest = int(sub["n"].iloc[TOP_CLASSES_PER_SECTION:].sum())
        if rest:
            kids.append({"name": f"אחר ({s})", "value": rest})
        tree.append({"name": sec_label(s), "value": int(sub["n"].sum()), "children": kids})
    class_table = [{"code": r.cls, "name": CLASS_HE.get(r.cls, "—"), "section": SECTION_HE.get(r.sec, r.sec),
                    "count": n(r.n), "share": f"{r.n / max(n_main, 1) * 100:.1f}%"}
                   for r in main_cls.head(TOP_CLASS_TABLE).itertuples()]

    # application-number bands
    lo, w = _bands(pd.Series(apps))
    band_of = pd.Series(((apps.values // w) * w).clip(min=lo), index=apps)
    band_starts = sorted(band_of.unique())
    labels = [_band_label(b, w, i == 0 and int(apps.min()) < b) for i, b in enumerate(band_starts)]
    band_apps = band_of.value_counts().reindex(band_starts, fill_value=0)
    med = float(band_apps.median())
    full = [bool(band_apps.iloc[i] >= 0.5 * med) for i in range(len(band_starts))]
    # the newest band is partial while numbers are still being issued in it
    partial_last = not full[-1]
    full_idx = [i for i, f in enumerate(full) if f]
    last_i = len(band_starts) - 1
    disp_labels = [lb + ("" if full[i] else (" (חלקי)" if i == last_i else " (מעט בקשות)"))
                   for i, lb in enumerate(labels)]

    mean_codes = (per_app.groupby(band_of).mean().reindex(band_starts)).round(2)
    mean_codes = [float(v) for v in mean_codes]

    main_band = mains.assign(band=mains["app"].map(band_of))
    overall_share = main_sec / max(n_main, 1)
    minor = sorted(s for s in secs if overall_share.get(s, 0) < MINOR_SECTION_SHARE)
    major = [s for s in secs if s not in minor]
    other_name = f"אחר ({', '.join(minor)})" if minor else None
    main_band["grp"] = main_band["sec"].map(lambda s: other_name if s in minor else sec_label(s))
    groups = [sec_label(s) for s in major] + ([other_name] if minor else [])
    ct = pd.crosstab(main_band["band"], main_band["grp"]).reindex(index=band_starts, columns=groups, fill_value=0)
    tot = ct.sum(axis=1).replace(0, 1)
    mix = {g: [round(float(v), 1) for v in (ct[g] / tot * 100)] for g in groups}

    mk = {}
    for key, _, prefix in MARKERS:
        hit = df[df["cpc"].str.startswith(prefix)]["app"].unique()
        cnt = band_of[band_of.index.isin(hit)].value_counts().reindex(band_starts, fill_value=0)
        mk[key] = [round(float(c) / max(int(t), 1) * 100, 2) for c, t in zip(cnt, band_apps)]

    # per-app distributions
    pa_rows = []
    for a, b in PER_APP_BUCKETS:
        m = per_app >= a
        if b is not None:
            m &= per_app <= b
        lab = f"{LRI}{a}+{PDI}" if b is None else (f"{a}" if a == b else f"{LRI}{a}–{b}{PDI}")
        pa_rows.append((lab, int(m.sum())))
    ns_rows = []
    for k in [1, 2, 3]:
        ns_rows.append((str(k), int((nsec == k).sum())))
    ns_rows.append((f"{LRI}4+{PDI}", int((nsec >= 4).sum())))

    # section co-occurrence (applications carrying both sections)
    sec_sets = df.drop_duplicates(["app", "sec"])[["app", "sec"]]
    pairs = sec_sets.merge(sec_sets, on="app")
    pairs = pairs[pairs["sec_x"] < pairs["sec_y"]]
    pc = pairs.groupby(["sec_x", "sec_y"]).size()
    cooc_sorted = sorted(((k, int(v)) for k, v in pc.items()), key=lambda kv: (-kv[1], kv[0]))
    cells = []
    for yi, a in enumerate(secs):
        for xi, b in enumerate(secs):
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            cells.append([xi, yi, int(pc.get(key, 0))])
    cooc_table = [{"sec": sec_label(a),
                   "cells": ["—" if a == b else n(pc.get((a, b) if a < b else (b, a), 0)) for b in secs]}
                  for a in secs]

    # invention kind from the English title (multi-label)
    t = titles.reindex(apps).fillna("")
    kinds = []
    for name, rx in TITLE_KINDS:
        c = int(t.str.contains(rx, regex=True).sum())
        kinds.append((name, c))
    kinds.sort(key=lambda kv: (-kv[1], kv[0]))

    charts = {
        "sections": sections,
        "subclasses": subclasses,
        "tree": tree,
        "mix": {"x": disp_labels, "series": [{"name": g, "data": mix[g]} for g in groups]},
        "depth": {"x": disp_labels, "apps": [int(v) for v in band_apps], "mean": mean_codes},
        "markers": {"x": disp_labels,
                    "series": [{"name": name, "data": mk[key]} for key, name, _ in MARKERS]},
        "per_app": {"names": [k for k, _ in pa_rows], "values": [v for _, v in pa_rows]},
        "nsec": {"names": [k for k, _ in ns_rows], "values": [v for _, v in ns_rows]},
        "cooc": {"x": secs, "y": secs, "cells": cells, "max": max([c[2] for c in cells] or [1]),
                 "names": [sec_label(s) for s in secs]},
        "kinds": {"names": [k for k, _ in kinds],
                  "values": [round(v / n_apps * 100, 1) for _, v in kinds]},
    }

    tables = {
        "sections": [{"name": nm, "main": f"{a:.1f}%", "any": f"{b:.1f}%"}
                     for nm, a, b in zip(sections["names"], sections["main"], sections["any"])],
        "subclasses": [{"name": nm, "count": n(v), "share": f"{s:.1f}%"}
                       for nm, v, s in zip(subclasses["names"], subclasses["values"], subclasses["share"])],
        "classes": class_table,
        "mix_groups": groups,
        "mix": [{"band": disp_labels[i], "cells": [f"{mix[g][i]:.1f}%" for g in groups]}
                for i in range(len(band_starts))],
        "depth": [{"band": disp_labels[i], "apps": n(band_apps.iloc[i]), "mean": f"{mean_codes[i]:.1f}"}
                  for i in range(len(band_starts))],
        "markers_names": [name for _, name, _ in MARKERS],
        "markers": [{"band": disp_labels[i], "cells": [f"{mk[key][i]:.2f}%" for key, _, _ in MARKERS]}
                    for i in range(len(band_starts))],
        "per_app": [{"bucket": k, "count": n(v)} for k, v in pa_rows],
        "nsec": [{"bucket": k, "count": n(v)} for k, v in ns_rows],
        "cooc_x": secs,
        "cooc": cooc_table,
        "kinds": [{"name": k, "count": n(v), "share": f"{v / n_apps * 100:.1f}%"} for k, v in kinds],
    }

    rules = [
        ("lead", ins_lead(main_sec, n_main)),
        ("life", ins_life(life_apps, n_apps, sub_apps)),
        ("shift", ins_shift(mix, full_idx, disp_labels, groups)),
        ("markers", ins_markers(mk, full_idx, disp_labels)),
        ("multi", ins_multi(nsec, per_app)),
        ("pair", ins_pair(cooc_sorted, nsec)),
        ("depth", ins_depth(mean_codes, full_idx, disp_labels)),
        ("main", ins_main(n_main, n_apps)),
    ]
    insights = [{"id": i, "text_he": s} for i, s in rules if s]

    multi_share = float((nsec >= 2).mean() * 100)
    kpis = {
        "apps": {"value": n_apps, "display": n(n_apps), "tone": "brand"},
        "codes": {"value": rows_total, "display": n(rows_total), "tone": "brand"},
        "subclasses": {"value": int(df["sub"].nunique()), "display": n(df["sub"].nunique()), "tone": "brand"},
        "multi": {"value": round(multi_share, 1), "display": f"{multi_share:.1f}%", "tone": "info"},
    }

    last_full = full_idx[-1] if full_idx else len(band_starts) - 1
    partial_note = (f" הטווח האחרון ({labels[-1]}) חלקי — מספרים בו עדיין מוקצים — ואינו נכלל בהשוואות."
                    if partial_last else "")
    band_note = (f"מספרי הבקשה ניתנים בסדר עולה, ולכן טווחי מספרים (ברוחב {w:,}) משקפים בקירוב את "
                 f"סדר ההגשה. הטווח הראשון כולל גם את הבקשות הוותיקות שמתחתיו.{partial_note}")
    labels_out = {
        "lede": (f"סיווגי CPC (הסיווג הפטנטי המשותף) של {n(n_apps)} בקשות פטנט שהוגשו בישראל: "
                 f"{n(rows_total)} שיוכי סיווג ב-{n(df['sub'].nunique())} תתי-סעיפים. לכל בקשה כמה "
                 f"סיווגים, ובדרך כלל אחד מהם מסומן כראשי. בממוצע {per_app.mean():.1f} סיווגים לבקשה."),
        "multi_kpi": "מהבקשות משלבות כמה סעיפים",
        "sections_note": (f"שתי מדידות לכל סעיף: שיעור הבקשות שהסיווג הראשי שלהן בסעיף (מתוך {n(n_main)} "
                          f"בקשות עם סיווג ראשי) ושיעור הבקשות שיש להן סיווג כלשהו בסעיף."
                          + (f" ב-{n(multi_main)} בקשות עם יותר מסיווג ראשי אחד נלקח הראשון בסדר האלפבית."
                             if multi_main else "")),
        "sections_aria": (f"תרשים עמודות: שיעור הבקשות לפי סעיף CPC — לפי סיווג ראשי ולפי סיווג כלשהו. "
                          f"המוביל: {sec_label(main_sec.sort_index().sort_values(ascending=False, kind='stable').index[0])}."),
        "sub_note": f"מספר הבקשות שיש להן סיווג אחד לפחות בתת-הסעיף ({len(top_sub)} הנפוצים מתוך {n(sub_apps.size)}).",
        "sub_aria": f"תרשים עמודות אופקי: {len(top_sub)} תתי-הסעיפים הנפוצים לפי מספר בקשות. במקום הראשון {top_sub.index[0]}.",
        "tree_note": (f"הבקשות לפי הסיווג הראשי, בחלוקה לסעיף ולמחלקה ({TOP_CLASSES_PER_SECTION} המחלקות "
                      f"הגדולות בכל סעיף, השאר תחת אחר)."),
        "tree_aria": "מפת עצים: בקשות לפי סעיף ומחלקה של הסיווג הראשי.",
        "classes_caption": f"{len(class_table)} המחלקות הנפוצות בסיווג הראשי, מספר בקשות ושיעור.",
        "band_note": band_note,
        "mix_aria": "תרשים שטח מוערם: תמהיל הסעיפים בסיווג הראשי לפי טווח מספרי בקשה.",
        "mix_caption": "שיעור הבקשות לפי סעיף הסיווג הראשי בכל טווח מספרי בקשה.",
        "mix_minor": (f"סעיפים שחלקם הכולל נמוך מ-{MINOR_SECTION_SHARE * 100:.0f}% מקובצים תחת {other_name}."
                      if other_name else ""),
        "depth_aria": "תרשים משולב: מספר בקשות ומספר סיווגים ממוצע לבקשה לפי טווח מספרי בקשה.",
        "depth_caption": "מספר בקשות וסיווגים ממוצע לבקשה בכל טווח מספרי בקשה.",
        "markers_note": ("שיעור הבקשות בכל טווח שנושאות סיווג אחד לפחות מהקבוצות: נוגדנים (C07K16), "
                         "בינה מלאכותית (G06N), בריאות דיגיטלית (G16H) וטכנולוגיות אקלים (Y02)."),
        "markers_aria": "גרף קווים: שיעור הבקשות עם סיווגי נוגדנים, בינה מלאכותית, בריאות דיגיטלית ואקלים לפי טווח מספרי בקשה.",
        "markers_caption": "שיעור הבקשות עם סיווג מכל קבוצה, לפי טווח מספרי בקשה.",
        "per_app_aria": f"תרשים עמודות: בקשות לפי מספר הסיווגים. החציון {n(per_app.median())} סיווגים.",
        "per_app_caption": "מספר בקשות לפי מספר הסיווגים שלהן.",
        "nsec_aria": f"תרשים עמודות: בקשות לפי מספר הסעיפים השונים בסיווגיהן. {multi_share:.1f}% בשני סעיפים ומעלה.",
        "nsec_caption": "מספר בקשות לפי מספר סעיפי CPC שונים בסיווגיהן.",
        "cooc_note": ("מספר הבקשות שיש להן סיווג בשני הסעיפים גם יחד. האלכסון ריק — הצירוף של סעיף "
                      "עם עצמו אינו מוצג."),
        "cooc_aria": "מפת חום: מספר בקשות המשלבות כל זוג סעיפי CPC.",
        "cooc_caption": "מספר בקשות עם סיווג בשני הסעיפים, לכל זוג סעיפים.",
        "kinds_note": ("שיעור הבקשות ששמן באנגלית כולל מילות מפתח של כל סוג (למשל METHOD, SYSTEM, "
                       "COMPOSITION). בקשה יכולה להשתייך ליותר מסוג אחד, ויש בקשות שאינן באף סוג."),
        "kinds_aria": "תרשים עמודות אופקי: שיעור הבקשות לפי סוג ההמצאה כפי שעולה משמה.",
        "kinds_caption": "שיעור הבקשות לפי סוג ההמצאה במילות שמה.",
    }

    return {
        "agent_data": {
            "summary_he": (f"סיווגי CPC של {n(n_apps)} בקשות פטנט בישראל ({n(rows_total)} שיוכים): "
                           f"תחומי הטכנולוגיה, מדעי החיים כמוקד, בין-תחומיות ושינויים בתמהיל לאורך סדר ההגשה."),
            "dataset_kind": "rankings",
            "suggested_tags": ["פטנטים", "סיווגי CPC", "קניין רוחני", "רשות הפטנטים", "טכנולוגיה", "מדעי החיים"],
            "related_ids": ["8687fefe-51af-4e0b-af54-701929c40102",
                            "029b6747-551b-47ad-9a05-ef7f7868fcd0",
                            "247efc75-31f2-4b19-bd4e-e670b1bf2783",
                            "1806c96c-9cc4-47bf-98b3-80a18f061f98"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels_out,
        "flags": {"has_bands": len(band_starts) >= 3, "last_full": last_full},
    }
