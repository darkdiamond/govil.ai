"""English abstracts of the "Society and Welfare" (חברה ורווחה) journal.

The upstream CSV was exported with broken quoting: a multi-line title or
author list spills into extra rows. Rows are therefore read without relying
on their order (verify shuffles them):

* an article record is a row whose magazine_name is "magazine <vol>/<issue>"
  and whose publication_year is a 4-digit year, or a spilled row whose
  article_name itself starts with ",magazine <vol>/<issue>,<year>," (the
  tail of a broken record: issue, year and authors survive, the title not);
* every other row is a fragment and is counted as such, not as an article.
"""

import re
from collections import Counter, defaultdict

from govlib import fmt

ISSUE_RE = re.compile(r"^\s*magazine\s+(\d{1,3})\s*/\s*(\d{1,2})\s*$", re.IGNORECASE)
SPILL_RE = re.compile(r"^\s*,\s*magazine\s+(\d{1,3})\s*/\s*(\d{1,2})\s*,\s*(\d{4})\s*,(.*)$", re.IGNORECASE | re.DOTALL)
YEAR_RE = re.compile(r"^\s*(\d{4})\s*$")
HREF_RE = re.compile(r'href="([^"]+)"')
GOV_URL_RE = re.compile(r'^https://(?:www\.)?gov\.il/[^\s"<>@\\]+$')

GENRES = [
    ("editor", "דבר העורכת", ("message from the editor",)),
    ("perspective", "מאמר פרספקטיבה", ("perspective article",)),
    ("practice", "חוכמת השדה", ("practice wisdom",)),
    ("opinion", "מאמר דעה", ("opinion article",)),
    ("review", "מאמר סקירה", ("review article", "narrative review")),
]
RESEARCH = "מאמר מחקר"
UNKNOWN = "כותרת חלקית"
GENRE_ORDER = [RESEARCH] + [g[1] for g in GENRES] + [UNKNOWN]

TEAM_BUCKETS = ["כותב יחיד", "שניים", "שלושה", "ארבעה ומעלה"]


def _clean(s):
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()


def _strip_quotes(s):
    return _clean(s).strip('"“”„').strip()


def _title_ok(raw):
    t = _clean(raw)
    if not t:
        return False
    # the last line of a spilled multi-line title: closes a quote it never opened
    if t.endswith('"') and not t.startswith('"'):
        return False
    return t.count('"') % 2 == 0 or t.startswith('"')


def _authors(raw):
    s = _strip_quotes(raw)
    if not s or s.lower() == "none":
        return []
    s = re.sub(r"\s*(?:,|&|\|)\s*", ",", s)
    s = re.sub(r"(?:^|,|\s)and\s+", ",", s)
    out = []
    for p in s.split(","):
        p = re.sub(r"\d+", "", p)
        p = _strip_quotes(p).strip(" .,-")
        p = re.sub(r"\s+-\s+", "-", p)
        if len(p) >= 3 and re.search(r"[A-Za-z]", p):
            out.append(p)
    return out


def _genre(title):
    head = title.lower()[:40]
    for _key, label, needles in GENRES:
        if any(n in head for n in needles):
            return label
    return RESEARCH


def _gov_url(cells):
    for c in cells:
        for u in HREF_RE.findall(c or ""):
            if GOV_URL_RE.match(u):
                return u
    return None


def _issue_label(vol, num):
    return f"{vol}/{num}"


def _parse(df):
    records, fragments = [], 0
    for r in df.itertuples(index=False):
        name = r.article_name or ""
        mag = r.magazine_name or ""
        year = r.publication_year or ""
        cells = [name, mag, year, r.author or "", r.publication_type or "", r.link_to_article or ""]
        m = ISSUE_RE.match(mag)
        y = YEAR_RE.match(year)
        if m and y:
            title_raw = name
            ok = _title_ok(title_raw)
            auth_raw = r.author or ""
            auth_partial = _clean(auth_raw).startswith('"') and _clean(auth_raw).count('"') == 1
            records.append({
                "vol": int(m.group(1)), "num": int(m.group(2)), "year": int(y.group(1)),
                "title": _strip_quotes(title_raw) if ok else "",
                "authors": _authors(auth_raw),
                "authors_full": not auth_partial,
                "url": _gov_url(cells),
                "spill": False,
            })
            continue
        s = SPILL_RE.match(name)
        if s:
            rest = s.group(4)
            rest = re.split(r",\s*Abstract of article|\",|<a\b", rest, maxsplit=1)[0]
            records.append({
                "vol": int(s.group(1)), "num": int(s.group(2)), "year": int(s.group(3)),
                "title": "", "authors": _authors(rest), "authors_full": False,
                "url": _gov_url(cells), "spill": True,
            })
            continue
        fragments += 1
    return records, fragments


def compute(frames):
    df = frames["main"]
    total_rows = len(df)
    recs, fragments = _parse(df)
    if not recs:
        raise ValueError("no article records parsed")
    n = len(recs)

    # ---- issues -------------------------------------------------------
    issues = defaultdict(list)
    for r in recs:
        issues[(r["vol"], r["num"])].append(r)
    issue_keys = sorted(issues)
    issue_rows = []
    for k in issue_keys:
        rs = issues[k]
        years = Counter(r["year"] for r in rs)
        year = min(years.items(), key=lambda t: (-t[1], t[0]))[0]
        urls = Counter(r["url"] for r in rs if r["url"])
        url = min(urls.items(), key=lambda t: (-t[1], t[0]))[0] if urls else None
        issue_rows.append({"key": k, "label": _issue_label(*k), "year": year, "n": len(rs), "url": url})
    n_issues = len(issue_rows)
    n_with_pdf = sum(1 for i in issue_rows if i["url"])
    vols = sorted({k[0] for k in issue_keys})
    years_all = sorted({r["year"] for r in recs})
    y0, y1 = years_all[0], years_all[-1]

    issues_per_year = Counter(i["year"] for i in issue_rows)
    full_size = max(issues_per_year.values())
    latest_year_issues = issues_per_year[y1]
    partial_year = y1 if (len(years_all) > 1 and latest_year_issues < full_size) else None

    # ---- genres -------------------------------------------------------
    genre_of = [(_genre(r["title"]) if r["title"] else UNKNOWN) for r in recs]
    genre_counts = Counter(genre_of)
    genres_present = [g for g in GENRE_ORDER if genre_counts.get(g)]
    genre_series = []
    for g in genres_present:
        genre_series.append({"name": g, "data": [sum(1 for r, gg in zip(recs, genre_of) if r["year"] == y and gg == g) for y in years_all]})
    known = n - genre_counts.get(UNKNOWN, 0)

    # ---- authors ------------------------------------------------------
    # The same article listed in two issues (same author set, same year) is
    # one work: authors and team sizes count it once.
    def work_key(i, r):
        return (r["year"], frozenset(a.lower() for a in r["authors"])) if r["authors"] else ("row", i)

    work_issues = defaultdict(set)
    for i, r in enumerate(recs):
        work_issues[work_key(i, r)].add((r["vol"], r["num"]))
    dup_works = {k: v for k, v in work_issues.items() if len(v) > 1}
    dup_pairs = Counter(tuple(sorted(v))[:2] for v in dup_works.values())

    spell = defaultdict(Counter)
    per_author = defaultdict(set)
    for i, r in enumerate(recs):
        for a in r["authors"]:
            key = a.lower()
            spell[key][a] += 1
            per_author[key].add(work_key(i, r))
    display = {k: min(c.items(), key=lambda t: (-t[1], t[0]))[0] for k, c in spell.items()}
    n_authors = len(per_author)
    ranked = sorted(per_author.items(), key=lambda t: (-len(t[1]), display[t[0]]))
    top = [(display[k], len(v), sorted({w[0] for w in v})) for k, v in ranked if len(v) >= 2][:12]
    no_author = sum(1 for r in recs if not r["authors"])

    team, seen = [], set()
    for i, r in sorted(enumerate(recs), key=lambda t: (t[1]["vol"], t[1]["num"], t[0])):
        if r["spill"] or not r["authors_full"] or not r["authors"]:
            continue
        k = work_key(i, r)
        if k not in seen:
            seen.add(k)
            team.append(r)
    team_counts = Counter(min(len(r["authors"]), 4) for r in team)
    team_vals = [team_counts.get(i, 0) for i in (1, 2, 3, 4)]
    n_team = len(team)
    co_share = (n_team - team_vals[0]) / n_team if n_team else None

    # ---- latest issue -------------------------------------------------
    last_key = issue_keys[-1]
    last = issue_rows[-1]
    last_list = []
    for r in sorted(issues[last_key], key=lambda r: (r["title"] == "", r["title"].lower(), ", ".join(r["authors"]))):
        last_list.append({
            "title": r["title"] or UNKNOWN,
            "partial": not r["title"],
            "authors": ", ".join(r["authors"]),
            "genre": _genre(r["title"]) if r["title"] else "",
        })

    # ---- KPIs ---------------------------------------------------------
    pdf_tone = "ok" if n_with_pdf == n_issues else "warn"
    kpis = {
        "articles": {"value": n, "display": fmt.int_he(n), "tone": "brand"},
        "issues": {"value": n_issues, "display": fmt.int_he(n_issues), "tone": "brand"},
        "span": {"value": y1 - y0, "display": f"{y0}–{y1}" if y0 != y1 else str(y0), "tone": "info"},
        "authors": {"value": n_authors, "display": fmt.int_he(n_authors), "tone": "brand"},
        "pdf": {"value": n_with_pdf, "display": f"{n_with_pdf}/{n_issues}", "tone": pdf_tone},
    }

    vol_range = f"{vols[0]} עד {vols[-1]}" if len(vols) > 1 else str(vols[0])
    year_range = f"{y0} עד {y1}" if y0 != y1 else str(y0)

    # ---- insights -----------------------------------------------------
    ins = []
    ins.append({"id": "scope", "text_he": (
        f"הקובץ מפרט {fmt.int_he(n)} מאמרים מ-{fmt.int_he(n_issues)} חוברות של כתב העת, "
        f"כרכים {vol_range} ({year_range}), עם שמות המאמרים והכותבים באנגלית."
    )})

    sizes = sorted(issue_rows, key=lambda i: (-i["n"], i["key"]))
    if len(sizes) >= 3 and sizes[0]["n"] > sizes[1]["n"]:
        mean = n / n_issues
        ins.append({"id": "busiest", "text_he": (
            f"החוברת הגדולה ביותר בקובץ היא {fmt.isolate(sizes[0]['label'])} ({sizes[0]['year']}) "
            f"עם {sizes[0]['n']} רשומות, לעומת ממוצע של {fmt.num_he(mean, 1)} רשומות לחוברת."
        )})

    if known >= 10:
        res = genre_counts.get(RESEARCH, 0)
        others = [(g, genre_counts[g]) for g in GENRE_ORDER if g not in (RESEARCH, UNKNOWN) and genre_counts.get(g)]
        if others:
            others.sort(key=lambda t: (-t[1], GENRE_ORDER.index(t[0])))
            parts = fmt.join_he([f"{c} מסוג {g}" for g, c in others[:3]])
            ins.append({"id": "genres", "text_he": (
                f"מתוך {fmt.int_he(known)} רשומות שכותרתן נקראת במלואה, {fmt.pct(res / known)} הן מאמרי מחקר; "
                f"לצידם {parts} (סיווג לפי פתיח הכותרת)."
            )})

    if top and top[0][1] >= 3 and (len(top) == 1 or top[0][1] > top[1][1]):
        nm, c, ys = top[0]
        ins.append({"id": "top_author", "text_he": (
            f"השם שחוזר בתדירות הגבוהה ביותר בין הכותבים הוא {fmt.isolate(nm)}, ב-{c} מאמרים "
            f"בשנים {ys[0]} עד {ys[-1]}." if ys[0] != ys[-1] else
            f"השם שחוזר בתדירות הגבוהה ביותר בין הכותבים הוא {fmt.isolate(nm)}, ב-{c} מאמרים בשנת {ys[0]}."
        )})

    if co_share is not None and n_team >= 20:
        ins.append({"id": "coauthor", "text_he": (
            f"{fmt.pct(co_share)} מתוך {fmt.int_he(n_team)} המאמרים שרשימת הכותבים שלהם שלמה נכתבו "
            f"בידי שני כותבים או יותר; {team_vals[3]} מהם בידי ארבעה כותבים ומעלה."
        )})

    if partial_year:
        ins.append({"id": "partial", "text_he": (
            f"משנת {partial_year} מופיעות בקובץ עד כה "
            f"{'חוברת אחת' if latest_year_issues == 1 else f'{latest_year_issues} חוברות'}, לעומת {full_size} "
            f"בשנה מלאה, כך שהשנה האחרונה חלקית."
        )})

    if dup_works:
        (a, b), pair_n = min(dup_pairs.items(), key=lambda t: (-t[1], t[0]))
        nd = len(dup_works)
        ins.append({"id": "duplicates", "text_he": (
            f"{nd} מאמרים רשומים בקובץ ביותר מחוברת אחת (אותם כותבים באותה שנה), "
            f"{'בעיקר' if nd > pair_n else 'כולם'} בחוברות {fmt.isolate(_issue_label(*a))} ו-{fmt.isolate(_issue_label(*b))}; "
            f"בספירת הכותבים כל מאמר כזה נספר פעם אחת."
            if nd > 1 else
            f"מאמר אחד רשום בקובץ גם בחוברת {fmt.isolate(_issue_label(*a))} וגם בחוברת {fmt.isolate(_issue_label(*b))} "
            f"(אותם כותבים באותה שנה); בספירת הכותבים הוא נספר פעם אחת."
        )})

    if fragments:
        ins.append({"id": "quality", "text_he": (
            f"{fmt.int_he(fragments)} מתוך {fmt.int_he(total_rows)} השורות בקובץ הן שברי רשומות "
            f"(כותרת או רשימת כותבים שגלשו לשורה נפרדת בייצוא), ולא נספרו כמאמרים."
        )})

    if n_with_pdf:
        ins.append({"id": "pdf", "text_he": (
            f"ל-{n_with_pdf} מתוך {n_issues} החוברות יש בקובץ קישור לקובץ התקצירים באנגלית באתר gov.il."
            if n_with_pdf < n_issues else
            f"לכל {n_issues} החוברות יש בקובץ קישור לקובץ התקצירים באנגלית באתר gov.il."
        )})

    # ---- charts + tables ----------------------------------------------
    charts = {
        "issues": {"x": [i["label"] for i in issue_rows], "y": [i["n"] for i in issue_rows],
                   "years": [i["year"] for i in issue_rows]},
        "genres": {"x": [str(y) for y in years_all], "series": genre_series,
                   "partial": str(partial_year) if partial_year else ""},
        "team": {"x": TEAM_BUCKETS, "y": team_vals},
        "authors": {"names": [t[0] for t in top], "values": [t[1] for t in top]},
    }
    tables = {
        "issues": [{"label": i["label"], "year": i["year"], "n": i["n"], "url": i["url"] or ""} for i in reversed(issue_rows)],
        "genres": [{"name": g, "count": genre_counts[g], "share": fmt.pct(genre_counts[g] / n)} for g in sorted(genres_present, key=lambda g: (-genre_counts[g], GENRE_ORDER.index(g)))],
        "team": [{"name": b, "count": v, "share": fmt.pct(v / n_team) if n_team else "–"} for b, v in zip(TEAM_BUCKETS, team_vals)],
        "authors": [{"name": t[0], "count": t[1], "span": f"{t[2][0]}-{t[2][-1]}" if t[2][0] != t[2][-1] else str(t[2][0])} for t in top],
    }

    labels = {
        "lede": (
            f"זהו המאגר באנגלית של כתב העת חברה ורווחה (Society and Welfare), רבעון של משרד הרווחה "
            f"והביטחון החברתי לעבודה סוציאלית ולמחקר חברתי, שיוצא לאור מאז 1978. הקובץ מרכז את שמות "
            f"המאמרים והכותבים באנגלית ואת קובצי התקצירים באנגלית של {fmt.int_he(n_issues)} חוברות "
            f"({year_range}). המפתח העברי המלא של כתב העת נמצא בעמוד נפרד."
        ),
        "articles_kpi": "מאמרים בקובץ",
        "issues_kpi": "חוברות",
        "span_kpi": "שנות פרסום",
        "authors_kpi": "כותבים שונים",
        "pdf_kpi": "חוברות עם קובץ תקצירים באנגלית",
        "issues_note": (
            f"מספר רשומות המאמרים בכל חוברת, כרכים {vol_range}. בטבלה: קישור לקובץ התקצירים באנגלית של כל חוברת."
        ),
        "issues_aria": f"מאמרים בכל חוברת, {fmt.int_he(n_issues)} חוברות",
        "genres_note": (
            f"סוג הפרסום לפי פתיח הכותרת (מאמר פרספקטיבה, חוכמת השדה, מאמר דעה ועוד); "
            f"{fmt.int_he(genre_counts.get(UNKNOWN, 0))} רשומות שכותרתן נחתכה בייצוא מסומנות ככותרת חלקית."
            if genre_counts.get(UNKNOWN) else
            "סוג הפרסום לפי פתיח הכותרת (מאמר פרספקטיבה, חוכמת השדה, מאמר דעה ועוד)."
        ),
        "genres_aria": f"מאמרים לפי שנה וסוג פרסום, {year_range}",
        "team_note": (
            f"מספר הכותבים במאמר, מתוך {fmt.int_he(n_team)} מאמרים שרשימת הכותבים שלהם שלמה בקובץ"
            + (f" ({fmt.int_he(no_author)} רשומות ללא שמות כותבים)." if no_author else ".")
        ),
        "team_aria": "התפלגות מספר הכותבים במאמר",
        "authors_note": (
            "כותבים שמופיעים בשני מאמרים או יותר בקובץ (השמות כפי שנכתבו באנגלית; ספרות של שיוך מוסדי הוסרו)."
        ),
        "authors_aria": f"הכותבים החוזרים, {len(top)} שמות",
        "latest_title": f"בחוברת האחרונה בקובץ: {last['label']} ({last['year']})",
        "latest_note": f"{len(last_list)} רשומות. שמות המאמרים והכותבים כפי שפורסמו באנגלית.",
    }

    summary = (
        f"כתב העת חברה ורווחה באנגלית (Society and Welfare): {fmt.int_he(n)} מאמרים מ-{fmt.int_he(n_issues)} "
        f"חוברות, {year_range}, עם שמות הכותבים וקובצי התקצירים באנגלית."
    )
    description = (
        f"תקצירי המאמרים באנגלית של כתב העת חברה ורווחה (Society and Welfare): {fmt.int_he(n)} מאמרים "
        f"מ-{fmt.int_he(n_issues)} חוברות, {year_range}, וקישור לקובץ התקצירים של כל חוברת."
    )

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "temporal_coverage": f"{y0}/{y1}",
            "seo": {
                "title": "Society and Welfare: תקצירים באנגלית | חברה ורווחה",
                "description": description,
                "name": "כתב העת חברה ורווחה באנגלית: Society and Welfare",
                "alternate_names": [
                    "כתב העת חברה ורווחה - Society and Welfare journal",
                    "Society and Welfare journal",
                    "Society and Welfare English abstracts",
                    "תקצירים באנגלית חברה ורווחה",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "latest": last_list,
        "insights": ins,
        "labels": labels,
    }
