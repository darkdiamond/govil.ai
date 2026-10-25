"""סיווגי IPC לבקשות פטנט — IPC codes assigned to Israeli patent applications.

One row per (application, IPC code); an application carries 1..100+ codes,
at most one flagged "ראשי". Unlike the sibling CPC dataset (whose
applications start in the 230,000s), IPC reaches back decades of filings, so
the page's spine is the long view: how the record itself changed (main-flag
coverage, codes per application) and how the technology mix — above all the
drug modalities (small molecules vs. biologics) — shifted.

The data has no dates; Israeli application numbers are issued in ascending
order, so ranges of application numbers ("bands") stand in for filing order.
Band width is chosen from the span so the series stays short as numbers grow;
the newest band is partial while numbers are still issued in it, labelled and
kept out of trend rules. Codes recorded at subclass level only (no group,
e.g. "A01B") are counted and disclosed but left out of the classification
analysis — many are evident placeholders.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"

SECTIONS = ["A", "B", "C", "D", "E", "F", "G", "H"]
SECTION_HE = {
    "A": "צרכי אנוש",
    "B": "פעולות ביצוע ותובלה",
    "C": "כימיה ומטלורגיה",
    "D": "טקסטיל ונייר",
    "E": "מבנים קבועים",
    "F": "הנדסת מכונות, תאורה, חימום ונשק",
    "G": "פיזיקה",
    "H": "חשמל",
}
SUBCLASS_HE = {
    "A01B": "עיבוד קרקע", "A01G": "גידול צמחים וגננות", "A01K": "גידול בעלי חיים ודגה",
    "A01N": "קוטלי מזיקים ומווסתי צמחים", "A01P": "פעילות ביולוגית של חומרים לחקלאות",
    "A23L": "מזון ותוספי מזון", "A24B": "טבק", "A24F": "מוצרי עישון ואידוי",
    "A61B": "אבחון וכירורגיה", "A61F": "תותבים, חבישות ועזרים רפואיים",
    "A61J": "מכלים ואמצעים למתן תרופות", "A61K": "תכשירים רפואיים וקוסמטיים",
    "A61L": "חיטוי, עיקור וחומרים לשתלים", "A61M": "התקנים להחדרת חומרים לגוף",
    "A61N": "טיפול בקרינה, חשמל ואור", "A61P": "פעילות טיפולית של תרכובות",
    "A61Q": "תכשירי קוסמטיקה וטיפוח", "B01D": "הפרדה וסינון", "B01J": "תהליכים כימיים וזרזים",
    "B01L": "ציוד מעבדה", "B29C": "עיבוד פלסטיק", "B32B": "מוצרים שכבתיים",
    "B33Y": "ייצור תוספתי (הדפסה בתלת-ממד)", "B64C": "כלי טיס", "B64D": "ציוד לכלי טיס",
    "B65D": "אריזה ומכלים", "B82Y": "ננוטכנולוגיה", "C01B": "יסודות לא-מתכתיים ותרכובותיהם",
    "C02F": "טיפול במים ושפכים", "C07B": "שיטות כלליות בכימיה אורגנית",
    "C07C": "תרכובות אציקליות וקרבוציקליות", "C07D": "תרכובות הטרוציקליות",
    "C07F": "תרכובות אורגנו-מתכתיות ואחרות", "C07H": "סוכרים ונוקלאוזידים",
    "C07K": "פפטידים וחלבונים", "C08G": "פולימרים — תגובות עיבוי", "C08J": "עיבוד פולימרים",
    "C08K": "תוספים לפולימרים", "C08L": "הרכבים של פולימרים", "C09D": "ציפויים וצבעים",
    "C12M": "ציוד למיקרוביולוגיה", "C12N": "מיקרואורגניזמים, אנזימים והנדסה גנטית",
    "C12P": "תסיסה וסינתזה אנזימטית", "C12Q": "בדיקות באנזימים ובחומצות גרעין",
    "F41H": "שריון ואמצעי הגנה", "F42B": "תחמושת ומטעני נפץ", "G01B": "מדידת אורך ועובי",
    "G01N": "בדיקה וניתוח חומרים", "G01S": "מכ״ם, ניווט ואיכון", "G02B": "אופטיקה",
    "G03F": "פוטוליתוגרפיה", "G06F": "עיבוד נתונים דיגיטלי",
    "G06K": "זיהוי ונשאי נתונים", "G06N": "בינה מלאכותית ומודלים חישוביים",
    "G06Q": "מערכות מידע לניהול ומסחר", "G06T": "עיבוד וניתוח תמונה",
    "G06V": "זיהוי תמונה ווידאו", "G16B": "ביואינפורמטיקה",
    "G16H": "מידע רפואי ובריאות דיגיטלית", "H01L": "התקני מוליכים למחצה",
    "H01M": "סוללות ותאי דלק", "H01Q": "אנטנות", "H04B": "שידור ותקשורת",
    "H04L": "העברת מידע דיגיטלי", "H04M": "תקשורת טלפונית", "H04N": "תקשורת תמונה ווידאו",
    "H04Q": "מיתוג ובחירה בתקשורת", "H04W": "רשתות תקשורת אלחוטיות",
    "H05B": "חימום ותאורה חשמליים",
}
GROUP_HE = {
    "A61K31": "מולקולות קטנות (חומר פעיל אורגני)",
    "A61K39": "אנטיגנים ונוגדנים בתכשיר",
    "A61K9": "צורות מינון של תרופות",
    "A61K47": "נשאים וחומרי עזר בתכשיר",
    "A61K38": "פפטידים וחלבונים בתכשיר",
    "A61K45": "חומרים פעילים אחרים",
    "A61K35": "חומר ביולוגי ותאים",
    "A61K48": "ריפוי גני",
    "A61K8": "תכשירי קוסמטיקה",
    "A61P35": "תרופות נגד סרטן",
    "A61P25": "מערכת העצבים",
    "A61P31": "נגד זיהומים",
    "A61P37": "מערכת החיסון ואלרגיה",
    "A61P29": "משככי כאב ונוגדי דלקת",
    "A61P3": "מטבוליזם וסוכרת",
    "A61P43": "שימושים טיפוליים ייעודיים אחרים",
    "A61P9": "לב וכלי דם",
    "A61P1": "מערכת העיכול",
    "A61P11": "מערכת הנשימה",
    "A61P17": "עור",
    "A61P19": "שלד ומפרקים",
    "A61P27": "חושים (עין ואוזן)",
    "A61P13": "מערכת השתן",
    "A61P7": "דם ונוזלי גוף",
    "A61P21": "שרירים ועצב-שריר",
    "A61P15": "מערכת המין והרבייה",
    "A61P5": "מערכת ההורמונים",
    "A61P33": "נגד טפילים",
    "A61P39": "הגנה כללית ונוגדי רעלים",
    "A61P23": "הרדמה",
    "A61P41": "תרופות לשימוש בניתוח",
    "C07K16": "נוגדנים",
    "C07K14": "פפטידים וחלבונים ברצף מוגדר",
    "C12N15": "הנדסה גנטית (DNA ו-RNA)",
    "C12N5": "תאים ורקמות בתרבית",
    "C12Q1": "בדיקות באנזימים ובחומצות גרעין",
    "A61B5": "מדידה לצורכי אבחון",
    "G01N33": "ניתוח חומרים ביולוגיים",
    "H04N19": "דחיסת וידאו",
    "A01N43": "קוטלי מזיקים הטרוציקליים",
    "G06F3": "קלט ופלט למחשב",
    "G06F17": "עיבוד נתונים ייעודי",
    "H04L29": "פרוטוקולי תקשורת",
    "H04L9": "הצפנה ואבטחת תקשורת",
    "A61M5": "מזרקים והזרקה",
    "A61F2": "שתלים ותותבים",
    "A61B17": "מכשירים כירורגיים",
}
# Drug modalities tracked across bands (IPC main-group definitions, not data).
MODALITIES = [
    ("small", "מולקולות קטנות", "A61K31"),
    ("pep", "פפטידים וחלבונים", "A61K38"),
    ("ag", "אנטיגנים ונוגדנים", "A61K39"),
    ("bio", "חומר ביולוגי ותאים", "A61K35"),
    ("gene", "ריפוי גני", "A61K48"),
]
WIDTHS = [5000, 10000, 20000, 25000, 50000, 100000, 200000, 500000]
MAX_BANDS = 14
TOP_GROUPS = 15
TOP_TARGETS = 12
TOP_HEAT = 12
MINOR_SECTION_SHARE = 0.02
CODE_RE = re.compile(r"^([A-H])(\d\d)([A-Z])(\d+)/(\d+)$")
BARE_RE = re.compile(r"^[A-H]\d\d[A-Z]$")


def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def sec_label(s):
    return f"{SECTION_HE.get(s, s)} ({s})"


def sub_label(code):
    name = SUBCLASS_HE.get(code)
    return f"{code} · {name}" if name else code


def grp_label(code):
    name = GROUP_HE.get(code) or SUBCLASS_HE.get(code[:4])
    return f"{code} · {name}" if name else code


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
    return counts.sort_index().sort_values(ascending=False, kind="stable").head(k)


# ---------------------------------------------------------------- insights

def ins_lead(main_sec, n_main):
    if n_main == 0 or len(main_sec) < 2:
        return None
    s = _top(main_sec, 2)
    a, b = s.index[0], s.index[1]
    sa, sb = s.iloc[0] / n_main, s.iloc[1] / n_main
    if sa < 0.25:
        return None
    return (f"לפי הסיווג הראשי, {sec_label(a)} מוביל עם {pct(sa * 100)} מהבקשות, ואחריו "
            f"{sec_label(b)} ({pct(sb * 100)}) — יחד {pct((sa + sb) * 100)} מהבקשות.")


def ins_biologics(mod, full_idx, labels):
    if len(full_idx) < 3:
        return None
    first = next((i for i in full_idx if mod["ag"][i] > 0 and mod["small"][i] > 0), None)
    last = full_idx[-1]
    if first is None or first == last or mod["ag"][last] <= 0:
        return None
    r0 = mod["small"][first] / mod["ag"][first]
    r1 = mod["small"][last] / mod["ag"][last]
    if r1 <= 0 or r0 / r1 < 2:
        return None
    return (f"מעבר לתרופות ביולוגיות: בטווח {labels[first]} נשאו {pct(mod['small'][first])} מהבקשות "
            f"סיווג של מולקולות קטנות (A61K31) ורק {pct(mod['ag'][first])} סיווג של אנטיגנים ונוגדנים "
            f"(A61K39) — פי {r0:.1f}; בטווח {labels[last]} היחס הצטמצם לפי {r1:.1f} "
            f"({pct(mod['small'][last])} לעומת {pct(mod['ag'][last])}).")


def ins_target(targets, pharma_apps):
    if pharma_apps == 0 or targets.empty:
        return None
    top = targets.index[0]
    share = targets.iloc[0] / pharma_apps
    if share < 0.2:
        return None
    second = targets.index[1] if len(targets) > 1 else None
    tail = (f", ואחריו {GROUP_HE.get(second, second)} ({pct(targets.iloc[1] / pharma_apps * 100)})"
            if second else "")
    return (f"מבין {n(pharma_apps)} הבקשות שמציינות פעילות טיפולית (A61P), {pct(share * 100)} מכוונות "
            f"ל{GROUP_HE.get(top, top)} ({top}){tail}.")


def ins_depth(stats, full_idx, labels):
    if len(full_idx) < 3:
        return None
    best = None
    for a, b in zip(full_idx, full_idx[1:]):
        d = stats["mean"][b] - stats["mean"][a]
        if best is None or d > best[0] + 1e-9:
            best = (d, a, b)
    d, a, b = best
    if d < 1 or stats["mean"][b] < 1.3 * stats["mean"][a]:
        return None
    return (f"קפיצה בעומק הסיווג: בין הטווח {labels[a]} לטווח {labels[b]} עלה מספר הסיווגים הממוצע "
            f"לבקשה מ-{stats['mean'][a]:.1f} ל-{stats['mean'][b]:.1f}, והחציון מ-{n(stats['p50'][a])} "
            f"ל-{n(stats['p50'][b])}.")


def ins_main_cov(base, early_end, cov, full_idx, labels):
    if len(full_idx) < 4 or base is None:
        return None
    last = full_idx[-1]
    if cov[last] - base < 5:
        return None
    return (f"סימון הסיווג הראשי שלם יותר בבקשות החדשות: בבקשות הוותיקות (מספר בקשה עד {LRI}{early_end:,}{PDI}) "
            f"רק {pct(base)} מהבקשות מסומנות בסיווג ראשי, לעומת {pct(cov[last])} בטווח {labels[last]}.")


def ins_rise(heat_share, full_idx, labels):
    if len(full_idx) < 5:
        return None
    last, ref = full_idx[-1], full_idx[-5]
    moves = sorted(((v[last] - v[ref], s) for s, v in heat_share.items()), key=lambda m: (-m[0], m[1]))
    moves = [m for m in moves if m[0] >= 2]
    if not moves:
        return None
    parts = [f"{sub_label(s)} מ-{pct(heat_share[s][ref])} ל-{pct(heat_share[s][last])}" for _, s in moves[:2]]
    return (f"תתי-הסעיפים שצמחו יותר מכל בין הטווח {labels[ref]} לטווח {labels[last]} (בשיעור "
            f"מהבקשות): {'; '.join(parts)}.")


def ins_bare(bare_rows, rows_total, top_bare):
    if bare_rows == 0:
        return None
    lead = (f"; הנפוץ שבהם הוא {sub_label(top_bare[0])} ({n(top_bare[1])} שיוכים)"
            if top_bare and top_bare[1] / bare_rows >= 0.1 else "")
    return (f"{n(bare_rows)} שיוכים ({pct(bare_rows / rows_total * 100)}) רשומים ברמת תת-סעיף בלבד, "
            f"ללא קבוצה{lead}. שיוכים אלה אינם נכללים בניתוח הסיווגים.")


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["ipc"]
    rows_total = len(raw)
    df = pd.DataFrame({
        "app": pd.to_numeric(raw["מספר בקשה"].str.strip(), errors="coerce"),
        "code": raw["IPC סיווג"].str.strip().str.upper().str.replace(r"\s+", "", regex=True),
        "main": raw["ראשי"].str.strip() == "ראשי",
    })
    df = df[df["app"].notna()].copy()
    df["app"] = df["app"].astype("int64")
    all_apps = pd.Index(sorted(df["app"].unique()))
    n_apps = len(all_apps)
    app_has_main = df.groupby("app")["main"].any()

    bare = df[df["code"].str.match(BARE_RE)]
    bare_rows = len(bare)
    bc = _top(bare["code"].value_counts(), 1)
    top_bare = (bc.index[0], int(bc.iloc[0])) if len(bc) else None

    v = df[df["code"].str.match(CODE_RE)]
    v = v.groupby(["app", "code"], sort=True)["main"].max().reset_index()
    v["sec"] = v["code"].str[0]
    v["sub"] = v["code"].str[:4]
    v["grp"] = v["code"].str.split("/").str[0]
    v["mg"] = v["code"].str.endswith("/00")
    n_codes = len(v)

    per_app = v.groupby("app").size()
    mains = v[v["main"]].sort_values(["app", "code"]).drop_duplicates("app")
    n_main = len(mains)
    main_sec = mains["sec"].value_counts()

    # sections: % of apps by main section and with any code in the section
    n_cls = int(per_app.size)
    sec_any = v.drop_duplicates(["app", "sec"])["sec"].value_counts()
    secs = [s for s in SECTIONS if s in sec_any.index] + sorted(set(sec_any.index) - set(SECTIONS))
    sections = {
        "names": [sec_label(s) for s in secs],
        "main": [round(float(main_sec.get(s, 0)) / max(n_main, 1) * 100, 1) for s in secs],
        "any": [round(float(sec_any.get(s, 0)) / max(n_cls, 1) * 100, 1) for s in secs],
    }

    # top main groups (IPC group level) by applications
    grp_apps = v.drop_duplicates(["app", "grp"])["grp"].value_counts()
    top_g = _top(grp_apps, TOP_GROUPS)
    groups = {"names": [grp_label(g) for g in top_g.index], "codes": list(top_g.index),
              "values": [int(x) for x in top_g.values],
              "share": [round(float(x) / max(n_cls, 1) * 100, 1) for x in top_g.values]}

    # therapeutic targets (A61P groups) among apps citing any A61P code
    p = v[v["sub"] == "A61P"]
    pharma_apps = int(p["app"].nunique())
    tg = _top(p.drop_duplicates(["app", "grp"])["grp"].value_counts(), len(p) + 1)
    top_t = tg.head(TOP_TARGETS)
    targets = {"names": [f"{GROUP_HE.get(g, g)} ({g})" for g in top_t.index],
               "values": [int(x) for x in top_t.values],
               "share": [round(float(x) / max(pharma_apps, 1) * 100, 1) for x in top_t.values]}

    # application-number bands
    lo, w = _bands(pd.Series(all_apps))
    band_of = pd.Series(((all_apps.values // w) * w).clip(min=lo), index=all_apps)
    band_starts = sorted(band_of.unique())
    labels = [_band_label(b, w, i == 0 and int(all_apps.min()) < b) for i, b in enumerate(band_starts)]
    band_apps = band_of.value_counts().reindex(band_starts, fill_value=0)
    med = float(band_apps.median())
    full = [bool(band_apps.iloc[i] >= 0.5 * med) for i in range(len(band_starts))]
    # the newest band is still being issued: it counts as full only once it
    # holds most of a typical band's applications
    if len(band_starts) > 1 and band_apps.iloc[-1] < 0.75 * float(band_apps.iloc[:-1].median()):
        full[-1] = False
    partial_last = not full[-1]
    full_idx = [i for i, f in enumerate(full) if f]
    last_i = len(band_starts) - 1
    disp = [lb + ("" if full[i] else (" (חלקי)" if i == last_i else " (מעט בקשות)"))
            for i, lb in enumerate(labels)]

    cov = (app_has_main.groupby(band_of).mean().reindex(band_starts) * 100).round(1)
    cov = [float(x) for x in cov]

    pa_band = per_app.groupby(band_of.reindex(per_app.index))
    stats = {
        "mean": [round(float(x), 2) for x in pa_band.mean().reindex(band_starts).fillna(0)],
        "p50": [float(x) for x in pa_band.quantile(0.5).reindex(band_starts).fillna(0)],
        "p75": [float(x) for x in pa_band.quantile(0.75).reindex(band_starts).fillna(0)],
        "p90": [float(x) for x in pa_band.quantile(0.9).reindex(band_starts).fillna(0)],
    }

    # section mix of main classification per band
    mb = mains.assign(band=mains["app"].map(band_of))
    overall = main_sec / max(n_main, 1)
    minor = sorted(s for s in secs if overall.get(s, 0) < MINOR_SECTION_SHARE)
    major = [s for s in secs if s not in minor]
    other_name = f"אחר ({', '.join(minor)})" if minor else None
    mb["g"] = mb["sec"].map(lambda s: other_name if s in minor else sec_label(s))
    mix_groups = [sec_label(s) for s in major] + ([other_name] if minor else [])
    ct = pd.crosstab(mb["band"], mb["g"]).reindex(index=band_starts, columns=mix_groups, fill_value=0)
    tot = ct.sum(axis=1).replace(0, 1)
    mix = {g: [round(float(x), 1) for x in (ct[g] / tot * 100)] for g in mix_groups}

    # drug modalities: % of all apps in the band with a code in the group
    mod = {}
    for key, _, g in MODALITIES:
        hit = v.loc[v["grp"] == g, "app"].unique()
        cnt = band_of[band_of.index.isin(hit)].value_counts().reindex(band_starts, fill_value=0)
        mod[key] = [round(float(c) / max(int(t), 1) * 100, 1) for c, t in zip(cnt, band_apps)]

    # subclass × band heatmap (% of the band's apps)
    sub_apps = v.drop_duplicates(["app", "sub"])
    top_s = list(_top(sub_apps["sub"].value_counts(), TOP_HEAT).index)
    sct = pd.crosstab(sub_apps["sub"], sub_apps["app"].map(band_of)).reindex(columns=band_starts, fill_value=0)
    heat_share = {s: [round(float(c) / max(int(t), 1) * 100, 1) for c, t in zip(sct.loc[s], band_apps)]
                  for s in sct.index}
    cells, hmax = [], 0.0
    for yi, s in enumerate(top_s):
        for xi in range(len(band_starts)):
            val = heat_share[s][xi]
            hmax = max(hmax, val)
            cells.append([xi, yi, val])
    # risers considered among subclasses carried by at least 1% of apps overall
    sub_cnt = sub_apps["sub"].value_counts()
    rise_pool = {s: heat_share[s] for s in sorted(sub_cnt.index) if sub_cnt[s] >= 0.01 * n_cls}

    mg_share = float(v["mg"].mean() * 100) if n_codes else 0.0

    charts = {
        "sections": sections,
        "groups": groups,
        "targets": targets,
        "volume": {"x": disp, "apps": [int(x) for x in band_apps], "cov": cov},
        "mix": {"x": disp, "series": [{"name": g, "data": mix[g]} for g in mix_groups]},
        "modality": {"x": disp, "series": [{"name": nm, "data": mod[k]} for k, nm, _ in MODALITIES]},
        "depth": {"x": disp, **stats},
        "heat": {"x": disp, "y": [sub_label(s) for s in top_s], "codes": top_s, "cells": cells, "max": hmax},
    }

    tables = {
        "sections": [{"name": nm, "main": f"{a:.1f}%", "any": f"{b:.1f}%"}
                     for nm, a, b in zip(sections["names"], sections["main"], sections["any"])],
        "groups": [{"name": nm, "count": n(x), "share": f"{s:.1f}%"}
                   for nm, x, s in zip(groups["names"], groups["values"], groups["share"])],
        "targets": [{"name": nm, "count": n(x), "share": f"{s:.1f}%"}
                    for nm, x, s in zip(targets["names"], targets["values"], targets["share"])],
        "volume": [{"band": disp[i], "apps": n(band_apps.iloc[i]), "cov": f"{cov[i]:.1f}%"}
                   for i in range(len(band_starts))],
        "mix_groups": mix_groups,
        "mix": [{"band": disp[i], "cells": [f"{mix[g][i]:.1f}%" for g in mix_groups]}
                for i in range(len(band_starts))],
        "mod_names": [f"{nm} ({g})" for _, nm, g in MODALITIES],
        "modality": [{"band": disp[i], "cells": [f"{mod[k][i]:.1f}%" for k, _, _ in MODALITIES]}
                     for i in range(len(band_starts))],
        "depth": [{"band": disp[i], "mean": f"{stats['mean'][i]:.1f}", "p50": n(stats["p50"][i]),
                   "p75": n(stats["p75"][i]), "p90": n(stats["p90"][i])}
                  for i in range(len(band_starts))],
    }

    # main-flag coverage among the oldest applications (through the third full band)
    early_end = int(band_starts[full_idx[2]]) + w - 1 if len(full_idx) >= 3 else None
    early_cov = (float(app_has_main[app_has_main.index <= early_end].mean() * 100)
                 if early_end is not None else None)

    rules = [
        ("lead", ins_lead(main_sec, n_main)),
        ("biologics", ins_biologics(mod, full_idx, disp)),
        ("target", ins_target(tg, pharma_apps)),
        ("rise", ins_rise(rise_pool, full_idx, disp)),
        ("depth", ins_depth(stats, full_idx, disp)),
        ("main_cov", ins_main_cov(early_cov, early_end, cov, full_idx, disp)),
        ("bare", ins_bare(bare_rows, rows_total, top_bare)),
    ]
    insights = [{"id": i, "text_he": s} for i, s in rules if s]

    main_share = float(app_has_main.mean() * 100)
    last_mean = stats["mean"][full_idx[-1]] if full_idx else stats["mean"][-1]
    kpis = {
        "apps": {"value": n_apps, "display": n(n_apps), "tone": "brand"},
        "codes": {"value": rows_total, "display": n(rows_total), "tone": "brand"},
        "groups": {"value": int(v["grp"].nunique()), "display": n(v["grp"].nunique()), "tone": "brand"},
        "main": {"value": round(main_share, 1), "display": f"{main_share:.1f}%",
                 "tone": "ok" if main_share >= 95 else "warn"},
    }

    lead_sec = _top(main_sec, 1).index[0] if len(main_sec) else None
    partial_note = (f" הטווח האחרון ({labels[-1]}) חלקי — מספרים בו עדיין מוקצים — ואינו נכלל בהשוואות."
                    if partial_last else "")
    band_note = (f"מספרי הבקשה ניתנים בסדר עולה, ולכן טווחי מספרים (ברוחב {w:,}) משקפים בקירוב את "
                 f"סדר ההגשה. הטווח הראשון כולל גם את הבקשות הוותיקות שמתחתיו.{partial_note}")
    labels_out = {
        "lede": (f"סיווגי IPC (הסיווג הפטנטי הבין-לאומי) של {n(n_apps)} בקשות פטנט שהוגשו בישראל — "
                 f"מספרי בקשה מ-{LRI}{int(all_apps.min()):,}{PDI} עד {LRI}{int(all_apps.max()):,}{PDI}: "
                 f"{n(rows_total)} שיוכי סיווג ב-{n(v['grp'].nunique())} קבוצות IPC שונות. "
                 f"לכל בקשה כמה סיווגים, ובדרך כלל אחד מהם מסומן כראשי; בממוצע "
                 f"{per_app.mean():.1f} סיווגים לבקשה. בניגוד לסיווגי CPC, המכסים בעיקר בקשות חדשות יותר, "
                 f"סיווגי IPC משתרעים על פני עשורים של בקשות, ולכן העמוד מתמקד בשינוי לאורך סדר ההגשה."),
        "main_kpi": "מהבקשות עם סיווג ראשי מסומן",
        "groups_kpi": "קבוצות IPC בשימוש",
        "sections_note": (f"שיעור הבקשות שהסיווג הראשי שלהן בסעיף (מתוך {n(n_main)} בקשות עם סיווג ראשי) "
                          f"ושיעור הבקשות שיש להן סיווג כלשהו בסעיף."),
        "sections_aria": (f"תרשים עמודות: שיעור הבקשות לפי סעיף IPC — לפי סיווג ראשי ולפי סיווג כלשהו. "
                          f"המוביל: {sec_label(lead_sec) if lead_sec else ''}."),
        "groups_note": (f"{len(top_g)} הקבוצות הראשיות (רמת הקבוצה, למשל A61K31) הנפוצות מתוך "
                        f"{n(grp_apps.size)}, לפי מספר הבקשות שיש להן סיווג אחד לפחות בקבוצה."),
        "groups_aria": (f"תרשים עמודות אופקי: {len(top_g)} קבוצות IPC הנפוצות לפי מספר בקשות. "
                        f"במקום הראשון {top_g.index[0] if len(top_g) else ''}."),
        "targets_note": (f"קבוצות A61P מתארות את הפעילות הטיפולית של התרופה. מתוך {n(pharma_apps)} בקשות "
                         f"עם סיווג A61P — שיעור הבקשות לפי יעד טיפולי ({len(top_t)} היעדים הנפוצים; "
                         f"בקשה יכולה לציין כמה יעדים)."),
        "targets_aria": (f"תרשים עמודות אופקי: יעדים טיפוליים (A61P) לפי שיעור הבקשות. המוביל: "
                         f"{GROUP_HE.get(top_t.index[0], top_t.index[0]) if len(top_t) else ''}."),
        "targets_share_col": "מהבקשות עם A61P",
        "targets_unit": " מהבקשות עם A61P",
        "band_note": band_note,
        "volume_note": "עמודות: מספר הבקשות בכל טווח. קו: שיעור הבקשות שיש בהן סיווג המסומן כראשי.",
        "volume_aria": "תרשים משולב: מספר הבקשות ושיעור הבקשות עם סיווג ראשי לפי טווח מספרי בקשה.",
        "mix_aria": "תרשים שטח מוערם: תמהיל הסעיפים בסיווג הראשי לפי טווח מספרי בקשה.",
        "mix_minor": (f"סעיפים שחלקם הכולל נמוך מ-{MINOR_SECTION_SHARE * 100:.0f}% מקובצים תחת {other_name}."
                      if other_name else ""),
        "modality_note": ("שיעור הבקשות בכל טווח (מכלל הבקשות בטווח) שיש להן סיווג אחד לפחות בכל קבוצת "
                          "תכשירים רפואיים — מולקולות קטנות לעומת תרופות ביולוגיות."),
        "modality_aria": "גרף קווים: שיעור הבקשות לפי סוג התכשיר הרפואי (A61K) לאורך טווחי מספרי הבקשה.",
        "depth_note": (f"מספר הסיווגים לבקשה בכל טווח: ממוצע, חציון, רבעון עליון ועשירון עליון. "
                       f"{mg_share:.1f}% מהשיוכים הם ברמת קבוצה ראשית (/00) והשאר בתת-קבוצות מפורטות."),
        "depth_aria": (f"גרף קווים: מספר הסיווגים לבקשה (ממוצע ואחוזונים) לפי טווח מספרי בקשה. "
                       f"בטווח המלא האחרון ממוצע של {last_mean:.1f}."),
        "heat_note": (f"שיעור הבקשות בכל טווח שיש להן סיווג בכל אחד מ-{len(top_s)} תתי-הסעיפים "
                      f"הנפוצים. צבע כהה יותר — שיעור גבוה יותר; הקשה על תא מציגה את הערך."),
        "heat_aria": f"מפת חום: {len(top_s)} תתי-סעיפי IPC הנפוצים לפי טווח מספרי בקשה, בשיעור מהבקשות.",
    }

    return {
        "agent_data": {
            "summary_he": (f"סיווגי IPC של {n(n_apps)} בקשות פטנט בישראל ({n(rows_total)} שיוכים) על פני "
                           f"עשורים של הגשות: תחומי הטכנולוגיה, המעבר מתרופות כימיות לביולוגיות, יעדים "
                           f"טיפוליים והשינוי בפרקטיקת הסיווג."),
            "dataset_kind": "rankings",
            "suggested_tags": ["פטנטים", "סיווגי IPC", "קניין רוחני", "רשות הפטנטים", "תרופות", "טכנולוגיה"],
            "related_ids": ["6e207fff-abef-4f4d-aac7-61e669ba9ad5",
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
        "flags": {"has_bands": len(band_starts) >= 3, "has_targets": len(top_t) > 0},
    }
