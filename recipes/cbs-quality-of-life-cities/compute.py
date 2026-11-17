"""מדדי איכות חיים בערים הגדולות: CBS's yearly release comparing Israel's
large cities (100,000+ residents) with the national average on ~56
well-being indicators.

Each table is the chart-data sheet of ONE city's profile ("תרשים N - מדדי
איכות חיים ב<עיר> בהשוואה לממוצע הארצי, <שנה>"): a header row
`<year> | <city> | ממוצע ארצי`, then one row per indicator with the city's
RATIO to the national average (the average is 1). CBS orients every ratio
so that above 1 means the city is better off than the average, also for
indicators where less is better (it divides the average by the city's
value for unemployment, crowding, road deaths, loneliness, noise ...): the
2024 report's "better in 39 of 49 indicators" for Kfar Saba is exactly the
count of its ratios above 1.

Table numbers MOVE between editions (t1 was Kfar Saba in the 2022 edition
and Herzliya since), and t13's workbook also carries stale working sheets
(older years, ranking sheets without a city header). So every table input
(t1..t21, the last three spare, all optional) is split by edition and sheet,
and a city block is recognised by its header row and kept only when its
year is the edition's year. Each edition holds ONE year, so the source
reads three editions (`history_releases: 3`) and older editions add only
the year-over-year comparison.

Indicator labels drift in spelling between cities and editions ("שימוש
בe-Gov" / "שימוש ב e-Gov", "ש\"ר מניקיון" / "ש\"ר מהניקיון באזור
המגורים"): they are matched by a spacing-free key plus a small alias map,
and grouped into CBS's eleven domains by a known-label map (an unknown label
goes to "אחר", so a new indicator still flows through).
"""
import math
import re

import pandas as pd
from govlib import cbs, fmt

REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
STEM = re.compile(r"t\d+")
YEAR = re.compile(r"^(?:19|20)\d\d$")
CITY_TITLE = "בהשוואה לממוצע"
# Spacing-free key → canonical key (spellings that differ between sheets).
ALIASES = {
    "נשיגותהדיור": "דיורברהשגה",
    "מועסקיםבמשרהחלקיתשלאמרצון": "מועסקיםבמשרהחלקית",
    "שיעוראבטלהממושכת": "אבטלהממושכת",
    'ש"רמניקיון': 'ש"רמהניקיוןבאזורהמגורים',
    "רעשחיצוניהמפריעבדירה": "רעשחיצוניבאזורהמגורים",
    "יכולתלהשפיעעלמדיניותהממשלה": "יכולתהשפעהעלמדיניותהממשלה",
    "השפעהעלמדיניותהממשלה": "יכולתהשפעהעלמדיניותהממשלה",
    'חוסרש"רממשךזמןהגעהלעבודה': 'ש"רמזמןהגעהלעבודה',
}
DOMAINS = (
    ("תעסוקה", ("שיעורהתעסוקה", "מועסקיםבמשרהחלקית", "הכנסהחציונית", 'ש"רמעבודה', 'ש"רמהכנסה',
                "תפקידמאפשרקידום", "תפקידתואםאתתחוםלימודיהם", "אבטלהממושכת")),
    ("ביטחון אישי", ("תחושתביטחוןבחושך", "הרוגיםבתאונותדרכים")),
    ("בריאות", ("תמותתתינוקות", "תוחלתחיים", "עודףמשקל(כיתהא)", "עודףמשקל(כיתהז)", "סרטןגברים",
                "סרטןנשים", "תחושתדיכאון", "אמוןבמערכתהבריאות", "הערכהעצמיתשלבריאות")),
    ("דיור ותשתיות", ("הוצאהעלדיור30%ויותר", "צפיפותדיור", 'ש"רמאזורהמגורים', 'ש"רמהדירה',
                      'ש"רמהתחבורההציבורית', 'ש"רמזמןהגעהלעבודה', "דיורברהשגה", "עלותשירותידיור")),
    ("חינוך", ("זכאותלבגרות", "שיעורילמידה1715", "השכלהעלתיכוניתוגבוהה")),
    ("מעורבות אזרחית", ("מעורבותאזרחית", "הצבעה", "אמוןבממשלה", "אמוןבמערכתהמשפט",
                        "יכולתהשפעהעלמדיניותהממשלה", "נשיםבניהולבמגזרהציבורי")),
    ("סביבה", ("מחזור", 'ש"רמהניקיוןבאזורהמגורים', 'ש"רמשטחיםירוקים', "רעשחיצוניבאזורהמגורים",
               "איכותמיהשתייה")),
    ("רווחה אישית וחברתית", ('ש"רמהחיים', "ציפיותביחסלעתיד", "יכולתלהתמודדעםבעיות", "תחושתבדידות",
                             "אמוןכללי", "הערכהמבניהמשפחה", "תחושתאפליה")),
    ("רמת חיים חומרית", ('ש"רמהמצבהכלכלי', "הכנסהכלכלית", "הכנסהכספית")),
    ("פנאי, תרבות וקהילה", ('ש"רמהאיזוןעבודהתחומיחיים', "התנדבות")),
    ("טכנולוגיות המידע", ("נגישותלמחשב", "שימושבאינטרנט", "שימושבeGov", "ביטחוןבסביבהמקוונת")),
)
OTHER = "אחר"
# Clearer names for CBS's terse chart labels (by key); others keep CBS's label.
DISPLAY = {
    "מועסקיםבמשרהחלקית": "מועסקים במשרה חלקית שלא מרצון",
    'ש"רמהאיזוןעבודהתחומיחיים': "שביעות רצון מהאיזון בין עבודה לתחומי חיים אחרים",
    "שימושבeGov": "שימוש בשירותי ממשל מקוונים (e-Gov)",
    'ש"רמהניקיוןבאזורהמגורים': "שביעות רצון מהניקיון באזור המגורים",
    "רעשחיצוניבאזורהמגורים": "רעש חיצוני המפריע בדירה",
    "הוצאהעלדיור30%ויותר": "הוצאה על דיור של 30% מההכנסה ויותר",
    "סרטןגברים": "סרטן, מקרים חדשים (גברים)",
    "סרטןנשים": "סרטן, מקרים חדשים (נשים)",
    'ש"רמשטחיםירוקים': "שביעות רצון מפארקים ושטחים ירוקים",
    "דיורברהשגה": "דיור בר השגה",
}
DOMAIN_OF = {k: d for d, keys in DOMAINS for k in keys}
DOMAIN_ORDER = [d for d, _ in DOMAINS] + [OTHER]
# A share change (percentage points) between editions worth a sentence.
MOVE_PP = 8.0
# Fewest shared indicators for an edition-to-edition sentence.
MIN_COMMON = 20
MAX_INSIGHTS = 8


# ── parsing ─────────────────────────────────────────────────────────────


def _rel_key(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _int(v):
    try:
        return int(str(v).strip())
    except ValueError:
        return 0


def _ind_key(label):
    k = re.sub(r"[\s\-–]", "", label)
    if k.startswith("הצבעהלכנסת"):
        return "הצבעה"
    return ALIASES.get(k, k)


def _city_key(name):
    # "הרצליה" / "הרצלייה", "תל אביב-יפו" / "תל אביב יפו".
    return re.sub(r"[\s\-–]", "", name).replace("יי", "י")


def _display(label):
    return re.sub(r'^ש"ר\s+', "שביעות רצון ", label).replace("( ", "(")


def _blocks(frames):
    """[(release key, year, city, {ind key: (label, ratio, starred)}, titled, stem, sheet)]
    for every sheet with a city header row."""
    out = []
    names = sorted((n for n in frames if STEM.fullmatch(n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        cols = sorted((c for c in df.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))
        if len(cols) < 3:
            continue
        df = df.assign(_s=df["SHEET_NO"].map(_int), _r=df["ROW"].map(_int))
        for (no, sh), g in df.groupby(["RELEASE_NO", "_s"], sort=True):
            g = g.sort_values("_r", kind="stable")
            raw = [list(r) for r in g[cols].itertuples(index=False)]
            rows = [[cbs.clean(v) for v in r] for r in raw]
            h = next((i for i, r in enumerate(rows)
                      if YEAR.match(r[0]) and r[1] and "ממוצע" in r[2]), None)
            if h is None:
                continue
            titled = any(CITY_TITLE in c for r in rows[:h] for c in r)
            vals = {}
            for r, rr in zip(rows[h + 1:], raw[h + 1:]):
                label, v = r[0], cbs.num(r[1])
                if not label or YEAR.match(label) or v is None or v < 0:
                    continue
                k = _ind_key(label)
                if k not in vals:
                    vals[k] = (label, v, "*" in str(rr[0]))
            if vals:
                out.append((_rel_key(no), int(rows[h][0]), rows[h][1], vals, titled, int(n[1:]), sh, no))
    return out


def _editions(frames):
    """{release key: {"year", "no", "cities": {city key: {"name", "vals"}}}}: per
    edition, only blocks of the edition's own year; a city found twice keeps
    the titled sheet, then the lowest table and sheet number."""
    blocks = _blocks(frames)
    years = {}
    for b in blocks:
        years[b[0]] = max(years.get(b[0], 0), b[1])
    eds = {}
    for rk, y, city, vals, titled, stem, sh, no in sorted(
            blocks, key=lambda b: (b[0], not b[4], b[5], b[6])):
        if y != years[rk]:
            continue
        ed = eds.setdefault(rk, {"year": y, "no": no, "cities": {}})
        ck = _city_key(city)
        if ck not in ed["cities"]:
            ed["cities"][ck] = {"name": city, "vals": vals}
    return eds


# ── helpers ─────────────────────────────────────────────────────────────


def _r2(v):
    return round(v + 0.0, 2)


def _pct(v):
    return f"{v:.1f}%"


def _ratio_he(v):
    return f"{v:.2f}"


def _counts(vals):
    better = sum(1 for _, v, _s in vals.values() if v > 1)
    worse = sum(1 for _, v, _s in vals.values() if v < 1)
    return better, worse, len(vals) - better - worse


# ── compute ─────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    eds = _editions(frames)
    if not eds:
        raise ValueError("no city profile sheet recognised in any table")
    keys = sorted(eds)
    latest = eds[keys[-1]]
    ly = latest["year"]
    cities = latest["cities"]
    if len(cities) < 3:
        raise ValueError(f"only {len(cities)} city sheets in the newest edition")

    # Indicator set (latest edition), in domain order then first-seen order.
    seen = {}
    labels_by_key = {}
    for ck in sorted(cities):
        for k, (label, _v, _s) in cities[ck]["vals"].items():
            seen.setdefault(k, len(seen))
            labels_by_key.setdefault(k, {})
            labels_by_key[k][label] = labels_by_key[k].get(label, 0) + 1
    # first-seen order over sorted city keys is deterministic; order by domain, then that.
    ind_keys = sorted(seen, key=lambda k: (DOMAIN_ORDER.index(DOMAIN_OF.get(k, OTHER)), seen[k]))
    ind_label = {k: DISPLAY.get(k) or _display(min(labels_by_key[k],
                                                   key=lambda lab: (-labels_by_key[k][lab], lab)))
                 for k in ind_keys}
    ind_domain = {k: DOMAIN_OF.get(k, OTHER) for k in ind_keys}

    # Per-city counts, ranked by share better.
    stats = []
    for ck, c in cities.items():
        b, w, e = _counts(c["vals"])
        n = len(c["vals"])
        stats.append({"key": ck, "name": c["name"], "n": n, "better": b, "worse": w, "equal": e,
                      "share": b / n * 100})
    stats.sort(key=lambda s: (-s["share"], -s["better"], s["name"]))
    order = [s["key"] for s in stats]
    name = {s["key"]: s["name"] for s in stats}

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    cands = {}

    # ── rank ──
    charts["rank"] = {"x": [s["name"] for s in stats], "better": [s["better"] for s in stats],
                      "worse": [s["worse"] for s in stats], "equal": [s["equal"] for s in stats],
                      "share": [round(s["share"], 1) for s in stats]}
    flags["rank_equal"] = any(s["equal"] for s in stats)
    tables["rank"] = [[s["name"], f"{s['n']:,}", f"{s['better']:,}", f"{s['worse']:,}",
                       _pct(s["share"])] for s in stats]
    top, bottom = stats[0], stats[-1]
    tops = [s for s in stats if s["share"] == top["share"]]
    bots = [s for s in stats if s["share"] == bottom["share"]]
    if len(tops) == 1:
        cands["top"] = (f"{top['name']} מובילה בין {len(stats)} הערים הגדולות: מצבה טוב מהממוצע הארצי "
                        f"ב-{top['better']} מתוך {top['n']} המדדים הזמינים עבורה ({_pct(top['share'])}).")
    elif len(tops) <= 3 and len(tops) < len(stats):
        cands["top"] = (f"{fmt.join_he([s['name'] for s in tops])} מובילות בין {len(stats)} הערים הגדולות: "
                        f"בכל אחת מהן המצב טוב מהממוצע הארצי ב-{_pct(top['share'])} מהמדדים הזמינים.")
    if len(bots) == 1:
        cands["bottom"] = (f"ב{bottom['name']} שיעור המדדים שבהם המצב טוב מהממוצע הארצי הוא הנמוך בין הערים: "
                           f"{bottom['better']} מתוך {bottom['n']} ({_pct(bottom['share'])}).")
    elif len(bots) <= 3 and len(bots) < len(stats) and bottom["share"] < top["share"]:
        cands["bottom"] = (f"שיעור המדדים שבהם המצב טוב מהממוצע הארצי נמוך ביותר ב{fmt.join_he([s['name'] for s in bots])}: "
                           f"{_pct(bottom['share'])} בכל אחת מהן.")
    above = [s for s in stats if s["share"] > 50]
    cands["majority"] = (f"ב-{len(above)} מתוך {len(stats)} הערים הגדולות המצב טוב מהממוצע הארצי ביותר "
                         f"ממחצית המדדים, ובשאר {len(stats) - len(above)} הערים המצב טוב מהממוצע במחצית המדדים "
                         "או פחות.") if 0 < len(above) < len(stats) else None

    kpis["cities"] = {"value": len(stats), "display": f"{len(stats):,}", "tone": "brand"}
    kpis["indicators"] = {"value": len(ind_keys), "display": f"{len(ind_keys):,}", "tone": "brand"}
    kpis["top_share"] = {"value": round(top["share"], 1), "display": _pct(top["share"]), "tone": "ok"}
    kpis["above_half"] = {"value": len(above), "display": f"{len(above):,}",
                          "tone": "ok" if len(above) * 2 > len(stats) else "warn"}
    labels["top_city"] = top["name"]

    # ── domains: % of each domain's indicators above average, per city ──
    doms = [d for d in DOMAIN_ORDER if any(ind_domain[k] == d for k in ind_keys)]
    cells, dom_rows = [], []
    dom_city_share = {d: [] for d in doms}
    for yi, ck in enumerate(order):
        vals = cities[ck]["vals"]
        row = [name[ck]]
        for xi, d in enumerate(doms):
            vs = [vals[k][1] for k in ind_keys if ind_domain[k] == d and k in vals]
            if not vs:
                row.append("–")
                continue
            sh = sum(1 for v in vs if v > 1) / len(vs) * 100
            dom_city_share[d].append(sh)
            cells.append([xi, yi, round(sh, 1), len(vs)])
            row.append(f"{sh:.0f}%")
        dom_rows.append(row)
    charts["domains"] = {"x": doms, "y": [name[ck] for ck in order], "cells": cells}
    tables["domains"] = dom_rows
    labels["domain_cols"] = ["עיר"] + doms
    dom_size = {d: sum(1 for k in ind_keys if ind_domain[k] == d) for d in doms}
    dom_rank = sorted(((sum(1 for v in dom_city_share[d] if v > 50), d) for d in doms
                       if len(dom_city_share[d]) >= 3 and dom_size[d] >= 3 and d != OTHER), key=lambda t: (-t[0] / max(1, len(dom_city_share[t[1]])), t[1]))
    if dom_rank:
        n_hi, d_hi = dom_rank[0]
        n_lo, d_lo = dom_rank[-1]
        m_hi, m_lo = len(dom_city_share[d_hi]), len(dom_city_share[d_lo])
        if d_hi != d_lo and n_hi / m_hi > n_lo / m_lo:
            cands["domain"] = (f"בתחום {d_hi} ב-{n_hi} מתוך {m_hi} הערים רוב המדדים טובים מהממוצע הארצי, "
                               f"ואילו בתחום {d_lo} כך רק ב-{n_lo} מתוך {m_lo} ערים.")

    # ── matrix: every indicator x city ratio ──
    mcells = []
    for yi, k in enumerate(ind_keys):
        for xi, ck in enumerate(order):
            v = cities[ck]["vals"].get(k)
            if v is not None:
                lv = math.log2(v[1]) if v[1] > 0 else -3.0
                mcells.append([xi, yi, round(max(-1.5, min(1.5, lv)), 3), _r2(v[1])])
    charts["matrix"] = {"x": [name[ck] for ck in order], "y": [ind_label[k] for k in ind_keys],
                        "cells": mcells}
    tables["matrix"] = [[ind_label[k], ind_domain[k]]
                        + [(_ratio_he(cities[ck]["vals"][k][1]) if k in cities[ck]["vals"] else "–")
                           for ck in order] for k in ind_keys]
    labels["matrix_cols"] = ["מדד", "תחום"] + [name[ck] for ck in order]

    # ── profile: one city at a time (select) ──
    # [label index, % deviation] pairs; labels are the matrix's, sent once.
    charts["profile"] = {"cities": [name[ck] for ck in order], "labels": [ind_label[k] for k in ind_keys],
                         "data": [[[i, round((cities[ck]["vals"][k][1] - 1) * 100, 1)]
                                   for i, k in enumerate(ind_keys) if k in cities[ck]["vals"]]
                                  for ck in order]}
    prof_rows = []
    for ck in order:
        vals = cities[ck]["vals"]
        ks = [k for k in ind_keys if k in vals]
        best = sorted(ks, key=lambda k: (-vals[k][1], ind_label[k]))[:3]
        worst = sorted(ks, key=lambda k: (vals[k][1], ind_label[k]))[:3]
        prof_rows.append([name[ck], ", ".join(ind_label[k] for k in best if vals[k][1] > 1) or "–",
                          ", ".join(ind_label[k] for k in worst if vals[k][1] < 1) or "–"])
    tables["profile"] = prof_rows

    # ── spread: where the cities differ most (starred, capped values left out) ──
    spread = []
    for k in ind_keys:
        pts = sorted(((cities[ck]["vals"][k][1], name[ck]) for ck in order
                      if k in cities[ck]["vals"] and not cities[ck]["vals"][k][2]
                      and cities[ck]["vals"][k][1] > 0),
                     key=lambda t: (t[0], t[1]))
        if len(pts) < max(3, len(order) // 2):
            continue
        spread.append({"key": k, "lo": pts[0], "hi": pts[-1], "gap": pts[-1][0] / pts[0][0],
                       "n": len(pts)})
    spread.sort(key=lambda s: (-s["gap"], ind_label[s["key"]]))
    spread = spread[:12]
    flags["spread"] = len(spread) >= 3
    if flags["spread"]:
        charts["spread"] = {"y": [ind_label[s["key"]] for s in spread],
                            "lo": [_r2(s["lo"][0]) for s in spread], "hi": [_r2(s["hi"][0]) for s in spread],
                            "lo_city": [s["lo"][1] for s in spread], "hi_city": [s["hi"][1] for s in spread]}
        tables["spread"] = [[ind_label[s["key"]], f"{s['hi'][1]} ({_ratio_he(s['hi'][0])})",
                             f"{s['lo'][1]} ({_ratio_he(s['lo'][0])})", f"{s['gap']:.1f}"] for s in spread]
        s0 = spread[0]
        cands["spread"] = (f"הפער הגדול ביותר בין הערים הוא במדד {ind_label[s0['key']]}: היחס לממוצע הארצי "
                           f"נע בין {_ratio_he(s0['lo'][0])} ב{s0['lo'][1]} ל-{_ratio_he(s0['hi'][0])} "
                           f"ב{s0['hi'][1]}.")

    # ── leaders: how many indicators each city ranks first in ──
    firsts = {ck: 0 for ck in order}
    for k in ind_keys:
        vs = [(cities[ck]["vals"][k][1], ck) for ck in order if k in cities[ck]["vals"]]
        if len(vs) < 3:
            continue
        mx = max(v for v, _ in vs)
        for v, ck in vs:
            if v == mx:
                firsts[ck] += 1
    lead = sorted(((firsts[ck], name[ck]) for ck in order if firsts[ck] > 0), key=lambda t: (-t[0], t[1]))
    flags["leaders"] = len(lead) >= 3
    if flags["leaders"]:
        charts["leaders"] = {"x": [n for _, n in lead], "y": [c for c, _ in lead]}
        tables["leaders"] = [[n, f"{c:,}"] for c, n in lead]
        if lead[0][0] > lead[1][0]:
            cands["leaders"] = (f"{lead[0][1]} במקום הראשון בין הערים הגדולות ב-{lead[0][0]} מדדים, יותר מכל "
                                f"עיר אחרת (אחריה {lead[1][1]} עם {lead[1][0]}).")

    # ── universal: an indicator where (almost) every city beats the average ──
    uni = []
    for k in ind_keys:
        vs = [cities[ck]["vals"][k][1] for ck in order if k in cities[ck]["vals"]]
        if len(vs) >= max(5, len(order) * 2 // 3):
            uni.append((sum(1 for v in vs if v > 1) / len(vs), sum(1 for v in vs if v > 1), len(vs), k))
    uni.sort(key=lambda t: (-t[0], ind_label[t[3]]))
    if uni and uni[0][0] >= 0.8:
        _f, b, n, k = uni[0]
        cands["universal"] = (f"במדד {ind_label[k]} {b} מתוך {n} הערים הגדולות טובות מהממוצע הארצי.")
    uni.sort(key=lambda t: (t[0], ind_label[t[3]]))
    if uni and uni[0][0] <= 0.2:
        _f, b, n, k = uni[0]
        cands["universal_low"] = (f"במדד {ind_label[k]} רק {b} מתוך {n} הערים הגדולות טובות מהממוצע הארצי.")

    # ── trend: share above average, per edition ──
    yrs = [eds[k]["year"] for k in keys]
    flags["trend"] = len(keys) >= 2
    if flags["trend"]:
        series = {}
        for rk in keys:
            for ck, c in eds[rk]["cities"].items():
                if ck in cities:
                    b, _w, _e = _counts(c["vals"])
                    series.setdefault(ck, {})[eds[rk]["year"]] = round(b / len(c["vals"]) * 100, 1)
        prev_y = yrs[-2]
        charts["trend"] = {"years": yrs, "x": [name[ck] for ck in order],
                           "series": [{"name": str(y), "data": [series.get(ck, {}).get(y) for ck in order]}
                                      for y in yrs]}
        tables["trend"] = [[name[ck]] + [(_pct(series[ck][y]) if y in series.get(ck, {}) else "–") for y in yrs]
                           for ck in order]
        labels["trend_cols"] = ["עיר"] + [str(y) for y in yrs]
        # The sentences compare each city on the indicators both editions carry
        # for it, and only when those are most of its indicators.
        prev_c = eds[keys[-2]]["cities"]
        moves = []
        for ck in order:
            if ck not in prev_c:
                continue
            cur, old = cities[ck]["vals"], prev_c[ck]["vals"]
            common = [k for k in cur if k in old]
            if len(common) < max(MIN_COMMON, len(cur) * 2 // 3):
                continue
            a = sum(1 for k in common if old[k][1] > 1) / len(common) * 100
            b = sum(1 for k in common if cur[k][1] > 1) / len(common) * 100
            moves.append((b - a, name[ck], a, b, len(common)))
        moves.sort(key=lambda t: (t[0], t[1]))
        if moves and moves[-1][0] >= MOVE_PP:
            _d, n, a, b, m = moves[-1]
            cands["rise"] = (f"{n} רשמה את השיפור הגדול ביותר בין {prev_y} ל-{ly}: באותם {m} מדדים, שיעור המדדים "
                             f"שבהם מצבה טוב מהממוצע הארצי עלה מ-{_pct(a)} ל-{_pct(b)}.")
        if moves and moves[0][0] <= -MOVE_PP:
            _d, n, a, b, m = moves[0]
            cands["fall"] = (f"ב{n} שיעור המדדים שבהם המצב טוב מהממוצע הארצי ירד הכי הרבה בין {prev_y} ל-{ly}: "
                             f"באותם {m} מדדים, מ-{_pct(a)} ל-{_pct(b)}.")
        labels["trend_prev"] = str(prev_y)

    ins_order = ("top", "bottom", "majority", "leaders", "domain", "spread", "rise", "fall",
                 "universal", "universal_low")
    insights = [{"id": i, "text_he": cands[i]} for i in ins_order if cands.get(i)][:MAX_INSIGHTS]

    # ── labels ──
    labels["year"] = str(ly)
    labels["years"] = fmt.join_he([str(y) for y in yrs])
    labels["rank_aria"] = (f"מספר המדדים שבהם כל עיר טובה או פחות טובה מהממוצע הארצי, {ly}. "
                           f"מובילה: {top['name']} ({_pct(top['share'])}).")
    labels["rank_note"] = (f"לכל עיר: בכמה מהמדדים הזמינים עבורה מצבה טוב מהממוצע הארצי ובכמה פחות טוב, {ly}. "
                           "הערים ממוינות לפי שיעור המדדים הטובים מהממוצע. לא כל המדדים זמינים לכל עיר.")
    labels["domains_aria"] = f"מפת חום: אחוז המדדים הטובים מהממוצע הארצי בכל תחום ובכל עיר, {ly}."
    labels["matrix_aria"] = f"מפת חום: היחס לממוצע הארצי בכל מדד ובכל עיר, {ly}."
    labels["profile_aria"] = f"פרופיל עיר: הסטייה מהממוצע הארצי בכל מדד, {ly}. ברירת מחדל: {top['name']}."
    if flags["spread"]:
        labels["spread_aria"] = (f"טווח היחס לממוצע הארצי בין הערים ב-{len(spread)} המדדים עם הפער הגדול ביותר, "
                                 f"{ly}.")
    if flags["leaders"]:
        labels["leaders_aria"] = f"מספר המדדים שבהם כל עיר במקום הראשון בין הערים הגדולות, {ly}."
    if flags["trend"]:
        labels["trend_aria"] = f"אחוז המדדים הטובים מהממוצע הארצי בכל עיר, {labels['years']}."
    labels["release_year_title"] = rel["TITLE"]

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "url": rel["PAGE_URL"],
               "pdf": rel["REPORT_PDF_URL"], "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}

    labels["lede"] = (f"איך חיים בערים הגדולות בישראל לעומת הממוצע הארצי? הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) משווה "
                      f"{len(stats)} ערים של 100 אלף תושבים ומעלה בכ-{len(ind_keys)} מדדי איכות חיים: תעסוקה, "
                      "בריאות, דיור, חינוך, ביטחון אישי, סביבה, שביעות רצון ועוד. "
                      f"בשנת {ly} {top['name']} מובילה, עם מצב טוב מהממוצע ב-{_pct(top['share'])} מהמדדים.")
    summary = (f"מדדי איכות חיים בערים הגדולות ({ly}, הלמ\"ס): השוואת {len(stats)} ערים לממוצע הארצי ב-{len(ind_keys)} "
               f"מדדים. {top['name']} מובילה ({top['better']} מתוך {top['n']} מדדים טובים מהממוצע), "
               f"וב-{len(above)} ערים המצב טוב מהממוצע ברוב המדדים.")
    desc = (f"השוואת איכות החיים ב-{len(stats)} הערים הגדולות בישראל לממוצע הארצי, {ly}: "
            f"{top['name']} מובילה ב-{_pct(top['share'])} מהמדדים. דיור, תעסוקה, בריאות וחינוך לפי עיר.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "rankings",
        "temporal_coverage": f"{yrs[0]}/{yrs[-1]}" if len(yrs) > 1 else str(ly),
        "spatial_coverage": "הערים הגדולות בישראל",
        "seo": {
            "title": "איכות חיים בערים הגדולות: השוואה בין הערים",
            "description": desc,
            "name": "מדדי איכות חיים בערים הגדולות",
            "alternate_names": ["איכות חיים בערים בישראל", "דירוג ערים לפי איכות חיים",
                                "מדדי איכות חיים לפי עיר", "השוואת ערים בישראל",
                                "Well-Being Indicators in the Big Cities"],
        },
    }
    return {"agent_data": agent_data, "kpis": kpis, "charts": charts, "insights": insights,
            "labels": labels, "tables": tables, "flags": flags, "release": release}
