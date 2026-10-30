"""בתי המשפט לתביעות קטנות בחלוקה למחוזות: one row per locality with the
judicial district (numeric code + name) whose small-claims courts have local
jurisdiction over it, plus an HTML anchor to the gov.il list of that
district's small-claims courts.

Searchers want "where do I file a small claim for my town", so the page leads
with the explorer lookup and an in-page directory of every locality per
district, each with its gov.il court-list link. Numbers and sentences are
computed from the rows.

The link is parsed from the anchor's href and kept only when it is an https
URL on a gov.il host; anything else is dropped (the directory then shows no
link for that district).

Data quirks handled: exact duplicate rows (counted once, disclosed), a name
listed under two districts (an ambiguous name, disclosed), stray whitespace.

Counting: the locality KPI and every total quoted in prose are UNIQUE names.
Per-district counts are distinct (name, district) pairs, so an ambiguous name
counts once in each of its districts; district shares use the pair total as
denominator (they sum to 100%) but that total itself is never printed, so the
page never shows two different "number of localities".

Growth: the list is a snapshot that is overwritten. New districts or codes
flow through (no hardcoded district list); districts sort by size with a
name tie-break; the name-word chart keeps a fixed top-N.
"""
import re

import pandas as pd

TOP_WORDS = 8
MIN_WORD_COUNT = 5
SUMMARY_MAX = 155
LEAD_SHARE = 0.20       # largest district must hold >= this share to be a "leader"
GAP_RATIO = 1.5         # largest vs second largest for the "clearly largest" wording


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _pct(x):
    return f"{x * 100:.1f}%"


def _n_loc(n):
    return "יישוב אחד" if n == 1 else f"{n:,} יישובים"


def _n_dist(n):
    return "מחוז אחד" if n == 1 else f"{n:,} מחוזות"


def _pre(prefix, text):
    """Hebrew one-letter prefix before a number takes a hyphen: ב-6, but במחוז."""
    return f"{prefix}-{text}" if text[:1].isdigit() else f"{prefix}{text}"


_HREF = re.compile(r"""href\s*=\s*["']([^"'<>\s]+)["']""", re.I)


# https on gov.il or a subdomain of it, no userinfo/port, then a path.
_GOVIL_URL = re.compile(r"^https://(?:[a-z0-9-]+\.)*gov\.il/[^\s\"'<>\\]*$", re.I)


def _link(cell):
    m = _HREF.search(str(cell))
    if not m:
        return ""
    url = m.group(1).replace("&amp;", "&")
    return url if _GOVIL_URL.match(url) else ""


def _prepare(df):
    d = pd.DataFrame({
        "name": df["city_name"].map(_clean),
        "code": df["court_district"].map(_clean),
        "district": df["מחוז"].map(_clean),
        "link": df["regional_courts"].map(_link),
    })
    raw_rows = int(len(d))
    d = d[(d["name"] != "") & (d["district"] != "")]
    dup_rows = int(d.duplicated().sum())
    d = d.drop_duplicates().sort_values(["district", "name", "code", "link"], kind="stable")
    return d.reset_index(drop=True), raw_rows, dup_rows


def _district_table(d):
    g = d.drop_duplicates(["name", "district"]).groupby("district")
    rows = []
    for dist, grp in g:
        codes = sorted({c for c in grp["code"] if c})
        links = grp[grp["link"] != ""]["link"].value_counts()
        link = ""
        if len(links):
            top = links.max()
            link = sorted(k for k, v in links.items() if v == top)[0]
        rows.append({"district": dist, "n": int(grp["name"].nunique()),
                     "code": ", ".join(codes), "link": link})
    rows.sort(key=lambda r: (-r["n"], r["district"]))
    total = sum(r["n"] for r in rows)
    for r in rows:
        r["share"] = r["n"] / total if total else 0.0
        r["share_display"] = _pct(r["share"])
        r["n_display"] = f"{r['n']:,}"
    return rows, total


def _tied(rows, i):
    """Districts sharing rows[i]'s count (rows are sorted by count)."""
    return [r["district"] for r in rows if r["n"] == rows[i]["n"]]


def _dists(names):
    return " ו".join(f"מחוז {x}" for x in names)


def _first_word(name):
    parts = name.split(" ")
    return parts[0] if len(parts) > 1 else None


# ---------------------------------------------------------------- insights

def insight_leader(rows, total):
    if len(rows) < 2 or total == 0:
        return None
    a, b = rows[0], rows[1]
    if a["share"] < LEAD_SHARE or a["n"] == b["n"]:
        return None
    s = (f"מחוז {a['district']} הוא מחוז השיפוט עם מספר היישובים הגדול ביותר: "
         f"{_n_loc(a['n'])}, {_pct(a['share'])} מהרשימה")
    if a["n"] >= GAP_RATIO * b["n"]:
        s += f", פי {a['n'] / b['n']:.1f} ממחוז {b['district']} שאחריו ({b['n']:,})"
    else:
        s += f", ואחריו מחוז {b['district']} ({_n_loc(b['n'])}, {_pct(b['share'])})"
    return s + "."


def insight_top2(rows, total):
    if len(rows) < 4 or total == 0:
        return None
    a, b = rows[0], rows[1]
    share = (a["n"] + b["n"]) / total
    if share < 0.4:
        return None
    return (f"שני המחוזות הגדולים, {a['district']} ו{b['district']}, מרכזים יחד "
            f"{_pct(share)} מהיישובים ברשימה ({_n_loc(a['n'] + b['n'])}).")


def insight_smallest(rows):
    if len(rows) < 3:
        return None
    small = rows[-1]
    big = rows[0]
    if small["n"] == rows[-2]["n"] or small["n"] == 0:
        return None
    s = (f"מחוז {small['district']} הוא הקטן ביותר ברשימה: {_n_loc(small['n'])} בלבד "
         f"({_pct(small['share'])})")
    if big["n"] >= 3 * small["n"]:
        s += f", לעומת {big['n']:,} במחוז {big['district']}"
    s += ". מספר היישובים במחוז אינו מעיד על היקף האוכלוסייה או מספר התביעות בו"
    return s + "."


def insight_ambiguous(amb):
    if not amb:
        return None
    if len(amb) == 1:
        nm, dists = amb[0]
        return (f"השם \"{nm}\" מופיע ברשימה תחת {_n_dist(len(dists))}: "
                f"{' ו'.join(dists)}. לפני הגשת תביעה כדאי לוודא באיזה יישוב מדובר.")
    shown = "; ".join(f"{nm} ({', '.join(ds)})" for nm, ds in amb[:4])
    more = f" ועוד {len(amb) - 4:,}" if len(amb) > 4 else ""
    return (f"{len(amb):,} שמות יישוב מופיעים ברשימה תחת יותר ממחוז שיפוט אחד: "
            f"{shown}{more}. לפני הגשת תביעה כדאי לוודא באיזה יישוב מדובר.")


def insight_dups(dup_rows, raw_rows):
    if dup_rows == 0:
        return None
    head = "שורה אחת ברשימה כפולה" if dup_rows == 1 else f"{dup_rows:,} שורות ברשימה כפולות"
    return (f"{head} (אותו יישוב ואותו מחוז פעמיים) מתוך {raw_rows:,} שורות; "
            "בספירות בעמוד כל יישוב נספר פעם אחת.")


def insight_word(words, rows):
    if not words:
        return None
    w = words[0]
    if w["total"] < MIN_WORD_COUNT:
        return None
    best = max(w["by"].values())
    leaders = sorted([k for k, v in w["by"].items() if v == best])
    where = " ו".join(f"מחוז {x}" for x in leaders)
    tail = (f"רובם במחוז {leaders[0]} ({best:,})" if len(leaders) == 1 and best * 2 > w["total"]
            else f"הכי הרבה ב{where} ({best:,}{' בכל אחד' if len(leaders) > 1 else ''})")
    return (f"\"{w['word']}\" היא המילה הנפוצה ביותר בפתיחת שם יישוב: "
            f"{_n_loc(w['total'])} ברשימה, {tail}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    d, raw_rows, dup_rows = _prepare(frames["main"])
    rows, total = _district_table(d)
    names_unique = int(d["name"].nunique())
    n_dist = len(rows)

    # names that sit under more than one district
    nd = d.drop_duplicates(["name", "district"]).groupby("name")["district"].apply(
        lambda s: sorted(set(s)))
    amb = [(nm, ds) for nm, ds in nd.items() if len(ds) > 1]
    amb.sort(key=lambda x: x[0])

    # first word of multi-word names, by district
    pairs = d.drop_duplicates(["name", "district"]).copy()
    pairs["word"] = pairs["name"].map(_first_word)
    pw = pairs[pairs["word"].notna()]
    wc = pw.groupby("word").size().reset_index(name="n")
    wc = wc.sort_values(["n", "word"], ascending=[False, True], kind="stable")
    wc = wc[wc["n"] >= MIN_WORD_COUNT].head(TOP_WORDS)
    dist_order = [r["district"] for r in rows]
    words = []
    for w, n in zip(wc["word"], wc["n"]):
        sub = pw[pw["word"] == w].groupby("district").size()
        by = {k: int(sub.get(k, 0)) for k in dist_order}
        words.append({"word": w, "total": int(n), "by": by})

    rules = [
        ("leader", insight_leader(rows, total)),
        ("top2", insight_top2(rows, total)),
        ("smallest", insight_smallest(rows)),
        ("name_word", insight_word(words, rows)),
        ("ambiguous", insight_ambiguous(amb)),
        ("duplicates", insight_dups(dup_rows, raw_rows)),
    ]
    linked = sum(1 for r in rows if r["link"])
    if rows and linked < len(rows):
        missing = [r["district"] for r in rows if not r["link"]]
        rules.append(("links", "ברשימה אין קישור לרשימת בתי המשפט עבור "
                      + (f"מחוז {missing[0]}" if len(missing) == 1
                         else f"{len(missing):,} מחוזות ({', '.join(missing)})") + "."))
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    kpis, kl, order = {}, {}, []

    def add(key, value, display, label, tone="brand"):
        kpis[key] = {"value": value, "display": display, "tone": tone}
        kl[key] = label
        order.append(key)

    add("localities", names_unique, f"{names_unique:,}", "יישובים ברשימה")
    add("districts", n_dist, f"{n_dist:,}", "מחוזות שיפוט")
    if rows:
        big = _tied(rows, 0)
        add("largest", rows[0]["n"], rows[0]["n_display"],
            (f"יישובים במחוז {big[0]}, הגדול ברשימה" if len(big) == 1
             else f"יישובים בכל אחד מהמחוזות הגדולים ({', '.join(big)})"), "info")
    if len(rows) > 1 and rows[-1]["n"] != rows[0]["n"]:
        small = _tied(rows, -1)
        add("smallest", rows[-1]["n"], rows[-1]["n_display"],
            (f"יישובים במחוז {small[0]}, הקטן ברשימה" if len(small) == 1
             else f"יישובים בכל אחד מהמחוזות הקטנים ({', '.join(small)})"))
    add("ambiguous", len(amb), f"{len(amb):,}",
        "שמות יישוב המופיעים ביותר ממחוז אחד", "warn" if amb else "ok")

    # ---- charts (horizontal bars: ascending so the largest sits on top)
    asc = rows[::-1]
    chart_dist = {
        "labels": [r["district"] for r in asc],
        "values": [r["n"] for r in asc],
        "shares": [round(r["share"] * 100, 1) for r in asc],
    }
    wasc = words[::-1]
    chart_words = {
        "words": [w["word"] for w in wasc],
        "districts": dist_order,
        "series": [[w["by"][k] for w in wasc] for k in dist_order],
    }
    word_rows = []
    for w in words:
        best = max(w["by"].values())
        leaders = sorted([k for k, v in w["by"].items() if v == best])
        word_rows.append({"word": w["word"], "n": f"{w['total']:,}",
                          "lead": f"{', '.join(leaders)} ({best:,})"})

    # ---- directory: every locality per district, alphabetical
    directory = []
    for r in rows:
        nm = sorted(d[d["district"] == r["district"]]["name"].unique())
        directory.append({"district": r["district"], "code": r["code"],
                          "n": r["n_display"], "names": nm, "link": r["link"],
                          "link_text": f"בתי המשפט לתביעות קטנות במחוז {r['district']} ←",
                          "summary": f"מחוז {r['district']}: {_n_loc(r['n'])}"})

    # ---- summary_he (meta description): the lookup task first
    parts = ["איתור בית המשפט לתביעות קטנות המוסמך לפי שם היישוב."]
    if rows:
        top = ", ".join(f"{r['district']} {r['n']:,}" for r in rows[:3])
        parts.append(f"{names_unique:,} יישובים {_pre('ב', _n_dist(n_dist))}: {top}.")
    summary = " ".join(parts)
    if len(summary) > SUMMARY_MAX:
        summary = (f"איתור בית המשפט לתביעות קטנות המוסמך לפי שם היישוב: "
                   f"{names_unique:,} יישובים {_pre('ב', _n_dist(n_dist))}.")

    lede = (f"הרשימה של הרשות השופטת משייכת {_n_loc(names_unique)} {_pre('ל', _n_dist(n_dist))} "
            "שיפוט, לפי כללי הסמכות המקומית בתביעות קטנות. מצאו את היישוב שלכם, "
            "בדקו לאיזה מחוז הוא שייך, ועברו לרשימת בתי המשפט לתביעות קטנות באותו מחוז "
            "באתר הרשות השופטת.")

    dist_aria = (f"תרשים עמודות אופקי: מספר היישובים {_pre('ב', _n_dist(n_dist))} השיפוט. "
                 + (f"הגדול: {', '.join(_tied(rows, 0))} ({rows[0]['n']:,}); "
                    f"הקטן: {', '.join(_tied(rows, -1))} ({rows[-1]['n']:,})."
                    if len(rows) > 1 and rows[-1]["n"] != rows[0]["n"] else ""))
    words_aria = (f"תרשים עמודות אופקי מוערם: {len(words):,} המילים הנפוצות בפתיחת שם יישוב, "
                  "לפי מחוז שיפוט." + (f" הנפוצה: {words[0]['word']} ({words[0]['total']:,})."
                                       if words else ""))
    dist_lede = ""
    if rows:
        big, small = _tied(rows, 0), _tied(rows, -1)
        if len(big) == 1:
            head = f"מחוז {big[0]} מוביל עם {_pct(rows[0]['share'])} מהיישובים"
        else:
            head = f"{_dists(big)} מובילים יחד, עם {_pct(rows[0]['share'])} מהיישובים כל אחד"
        if len(rows) == 1 or rows[-1]["n"] == rows[0]["n"]:
            tail = "."
        elif len(small) == 1:
            tail = f", ומחוז {small[0]} מסיים עם {_pct(rows[-1]['share'])}."
        else:
            tail = f", ו{_dists(small)} מסיימים עם {_pct(rows[-1]['share'])} כל אחד."
        dist_lede = "מספר היישובים בכל מחוז שיפוט, מהגדול לקטן. " + head + tail
    words_lede = ""
    if words:
        words_lede = (f"המילים הנפוצות בפתיחת שמות יישובים (כמו {words[0]['word']}"
                      + (f", {words[1]['word']}" if len(words) > 1 else "")
                      + "), וכיצד הן מתחלקות בין מחוזות השיפוט. כל מילה שמופיעה בלפחות "
                      f"{MIN_WORD_COUNT:,} שמות.")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["תביעות קטנות", "בתי משפט", "מחוזות שיפוט", "סמכות מקומית",
                           "יישובים", "הרשות השופטת"],
        "related_ids": [
            "a064c8f9-2e71-4f3a-b468-dd5e9298537c",
            "3c2be3d7-1924-4208-8eef-07e2cfb4b747",
            "80189fff-17da-4ee5-994d-be68ce8ce2b1",
            "7571aa64-9970-44d1-be04-190ba9fc386c",
            "b71257cf-d117-47b0-a800-06fd6e53f2d8",
        ],
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": order,
        "charts": {"districts": chart_dist, "words": chart_words},
        "insights": insights,
        "tables": {"districts": rows, "words": word_rows, "ambiguous": [
            {"name": nm, "districts": ", ".join(ds)} for nm, ds in amb]},
        "directory": directory,
        "flags": {"has_words": len(words) >= 3, "has_districts": len(rows) >= 2,
                  "has_ambiguous": bool(amb)},
        "labels": {
            **{f"kpi_{k}": v for k, v in kl.items()},
            "lede": lede,
            "dist_lede": dist_lede,
            "dist_aria": dist_aria,
            "dist_caption": f"מספר היישובים ושיעורם {_pre('ב', _n_dist(n_dist))} השיפוט.",
            "words_lede": words_lede,
            "words_aria": words_aria,
            "words_caption": "המילים הנפוצות בפתיחת שם יישוב והמחוז שבו הן נפוצות ביותר.",
            "dir_lede": (f"כל {_n_loc(names_unique)} ברשימה, לפי מחוז שיפוט ובסדר אלפביתי. "
                         "פתחו את המחוז כדי לראות את היישובים בו ואת הקישור לרשימת בתי המשפט "
                         "לתביעות קטנות שלו, או חפשו יישוב בחיפוש שבתחתית העמוד."),
            "amb_caption": "שמות יישוב המשויכים ליותר ממחוז שיפוט אחד.",
        },
    }
