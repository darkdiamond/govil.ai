"""ספרייה מקצועית של משרד התיירות: catalog of the ministry's professional library.

One row per catalogued item (book, report, journal issue, article, survey),
with title, shelf sticker number, publication year, publisher, place of
publication, page count, author/editor and a free-text remark.

The data is hand-entered and messy, so every field is normalised here:
* language: a title with any Hebrew letter is "עברית", otherwise "לועזית";
* year: a 4-digit year in [YEAR_MIN, YEAR_MAX]; anything else is "no valid year";
* publisher / author: case-folded, whitespace-collapsed, known typos merged;
* place: mapped to a country (Hebrew-script places are Israeli unless they name
  a known foreign place; Latin places by a keyword table; the rest unclassified).

Insight rules return a Hebrew sentence or None; wording follows the data.
"""
import re

import pandas as pd

YEAR_MIN = 1900
YEAR_MAX = 2099
MIN_DECADE_ITEMS = 100      # a decade must hold this many items to be compared
MIN_BAND_ITEMS = 30         # a sticker band must hold this many dated items
STICKER_BAND = 1000
TOP_PUBLISHERS = 12
TOP_AUTHORS = 12
TOP_COUNTRIES = 10
RECENT_WINDOW = 5           # years in the "recent" and "peak" windows
MIN_PAGES_GROUP = 30        # items with a page count per language to compare

HEB = "עברית"
FOR = "לועזית"
LANGS = [HEB, FOR]
HEB_RE = re.compile("[֐-׿]")

UNKNOWN_MARKERS = {"", "?", "(?)", "-", "&", "חסר", "חסר מקום", "המקום", "ללא",
                   "חמו\"ל", "חמו״ל", "חמול", "לא ידוע"}

PUBLISHER_ALIASES = {
    "ESLSEVIER": "ELSEVIER",
    "WILEY-BLACKWELL": "WILEY BLACKWELL",
    "WILEY - BLACKWELL": "WILEY BLACKWELL",
    "משרד התיריות": "משרד התיירות",
    "ישראל משרד התיירות": "משרד התיירות",
    "ישראל. משרד התיירות": "משרד התיירות",
    "ERNEST YOUNG": "ERNST & YOUNG",
}

ISRAEL = "ישראל"
UNCLASSIFIED = "מקום לועזי שלא סווג"
NO_PLACE = "לא צוין מקום"

# Latin keyword (word-bounded, upper case) -> country, checked in order.
LATIN_PLACES = [
    (r"JERUSALEM|TEL[\s-]*AVIV|ISRAEL|HAIFA|BEER[\s-]*SHEVA|NAZARETH|EILAT", ISRAEL),
    (r"UNITED KINGDOM|UK|LONDON|OXFORD|ENGLAND|BELFAST|SURREY|CAMBRIDGE|WALLINGFORD|"
     r"EDINBURGH|SCOTLAND|GLASGOW|MANCHESTER|BRIGHTON", "בריטניה"),
    (r"USA|US|UNITED STATES|NEW YORK|NY|WASHINGTON|EVANSTON|FLORIDA|BOSTON|NEVADA|"
     r"CA|CHICAGO|CALIFORNIA", "ארה״ב"),
    (r"SPAIN|MADRID|ELCHE|MALAGA|BARCELONA", "ספרד"),
    (r"HAGUE|NETHERLANDS|AMSTERDAM|ROTTERDAM|HOLLAND", "הולנד"),
    (r"CROATIA|ZAGREB", "קרואטיה"),
    (r"GERMANY|GERM|MUNICH|MUNCHEN|BERLIN|WIESBADEN|STARNBERG|FRANKFURT|HAMBURG", "גרמניה"),
    (r"FRANCE|FRANC|PARIS|NANTERRE|LYON", "צרפת"),
    (r"SWITZERLAND|SWITZ|SCHWEIZ|SCHWEI|GENEVA|GENEVE|BERN|BERNE|ZURICH|ST[\s.-]*GALL|"
     r"ST[\s.-]*GALLEN|GALLEN", "שווייץ"),
    (r"CANADA|MONTREAL|OTTAWA|TORONTO", "קנדה"),
    (r"AUSTRALIA|AUSTR|CANBERRA|SYDNEY|MELBOURNE", "אוסטרליה"),
    (r"ITALY|VENEZIA|ROMA|ROME|MILAN|BRECSIA", "איטליה"),
    (r"BELGIUM|BRUSSELS|BRUXELLES", "בלגיה"),
    (r"LUXEMBOURG|LUXENBOURG|LUXEMBURG", "לוקסמבורג"),
    (r"SWEDEN|SWEEDEN|STOCKHOLM", "שוודיה"),
    (r"AUSTRIA|WIEN|VIENNA", "אוסטריה"),
    (r"KOREA|SEOUL", "קוריאה הדרומית"),
    (r"TAIWAN|TAIPEI", "טאיוואן"),
    (r"HONG KONG", "הונג קונג"),
    (r"SINGAPORE", "סינגפור"),
    (r"JAPAN|TOKYO", "יפן"),
    (r"NEW ZEALAND|WELLINGTON|NZ", "ניו זילנד"),
    (r"SOUTH AFRICA|PRETORIA", "דרום אפריקה"),
    (r"GREECE|ATHENS", "יוון"),
    (r"HUNGARY|BUDAPEST", "הונגריה"),
    (r"FINLAND|HELSINKI", "פינלנד"),
    (r"CYPRUS", "קפריסין"),
]
LATIN_PLACES = [(re.compile(r"\b(?:" + p + r")\b"), c) for p, c in LATIN_PLACES]

# Hebrew-script place names abroad (substring match); everything else Hebrew is Israel.
HEBREW_FOREIGN = [
    ("ספרד", "ספרד"), ("מדריד", "ספרד"), ("ארה\"ב", "ארה״ב"), ("ארה״ב", "ארה״ב"),
    ("ניו יורק", "ארה״ב"), ("ניו-יורק", "ארה״ב"), ("שיקגו", "ארה״ב"),
    ("לונדון", "בריטניה"), ("בריטניה", "בריטניה"), ("הולנד", "הולנד"),
    ("שוויץ", "שווייץ"), ("רומא", "איטליה"), ("לוקסמבורג", "לוקסמבורג"),
    ("ניו זילנד", "ניו זילנד"), ("תורכיה", "טורקיה"), ("טורקיה", "טורקיה"),
]

# Title themes: (key, Hebrew label, regex over the upper-cased title).
THEMES = [
    ("plan", "תכנון ופיתוח", r"תכנון|פיתוח|תוכנית|תכנית|PLANNING|DEVELOPMENT|MASTER PLAN"),
    ("research", "סקרים ומחקר", r"סקר|מחקר|\bSURVEY|RESEARCH"),
    ("econ", "כלכלה והשקעות", r"כלכל|השקע|ECONOM|INVEST|FINANC"),
    ("hotel", "מלונאות ואירוח", r"מלון|מלונא|אירוח|HOTEL|HOSPITALITY|ACCOMMODATION|LODGING"),
    ("stat", "סטטיסטיקה ונתונים", r"סטטיסט|נתונים|STATISTIC|\bDATA\b"),
    ("marketing", "שיווק ופרסום", r"שיווק|פרסום|MARKETING|ADVERTIS|\bBRAND"),
    ("events", "כנסים ואירועים", r"כנס |כנסים|כינוס|\bCONFERENCE|\bEVENTS?\b|CONGRESS|\bMICE\b"),
    ("env", "סביבה וקיימות", r"סביבה|סביבתי|אקולוג|קיימות|ENVIRONMENT|SUSTAINAB|\bECO|ECOLOG"),
    ("culture", "מורשת ותרבות", r"מורשת|תרבות|ארכיאולוג|HERITAGE|CULTUR|MUSEUM"),
    ("health", "תיירות מרפא ובריאות", r"מרפא|בריאות|HEALTH|MEDICAL|\bSPA\b|WELLNESS"),
    ("religion", "תיירות דתית וצליינות", r"נוצרי|צליינ|קדושים|מקומות קדושים|PILGRIM|RELIGIO|CHRISTIAN|HOLY LAND"),
    ("transport", "תעופה ותחבורה", r"תעופה|טיסות|תחבורה|AVIATION|AIRLINE|AIRPORT|TRANSPORT"),
    ("rural", "תיירות כפרית", r"כפרי|\bRURAL|AGRITOUR"),
    ("security", "ביטחון, טרור וסיכונים", r"בטחון|ביטחון|טרור|SECURITY|TERROR|\bRISK|CRISIS"),
    ("jerusalem", "ירושלים", r"ירושלים|JERUSALEM"),
    ("guides", "מורי דרך והדרכה", r"מורי דרך|מורה דרך|מדריך|\bGUIDE"),
    ("deadsea", "ים המלח", r"ים המלח|DEAD SEA"),
    ("negev", "הנגב", r"נגב|NEGEV"),
    ("galilee", "הגליל והכנרת", r"גליל|כנרת|GALILEE"),
    ("eilat", "אילת", r"אילת|EILAT"),
]
THEMES = [(k, lab, re.compile(rx)) for k, lab, rx in THEMES]

# Remark categories (multi-label), in display order.
REMARKS = [
    ("עותק דיגיטלי", r"דיגיטל|DIGITAL"),
    ("מדף כתבי עת וחוברות", r"כתבי עת|כתב עת|כתבי-עת|חוברת|JOURNAL"),
    ("מפות, תצלומים ותשריטים", r"מפ|תצלומ|צלומ|תשריט|איור|תחריט"),
    ("מצגת", r"מצגת|מצגות"),
    ("עותקים נוספים", r"\d+\s*עותקים|שני עותקים|עותק נוסף|COPIES"),
    ("קלסר, קופסה או מיקום מדף", r"קלסר|קופס|מדף|FOLDER|\bב-\d"),
    ("הפניה לפריט אחר", r"ראה|נספח|בתוך|חלק מ"),
]
REMARKS = [(lab, re.compile(rx)) for lab, rx in REMARKS]
REMARK_OTHER = "הערה אחרת"

PAGE_BINS = [(1, 20, "1-20"), (21, 50, "21-50"), (51, 100, "51-100"),
             (101, 200, "101-200"), (201, 500, "201-500")]
PAGE_TOP_LOW = 501
PAGE_TOP_LABEL = "501 ומעלה"

RELATED = [
    "a416609e-f68a-4fea-b278-657f92bfbe73",
    "0d51bcd2-aa52-4c7c-8e5f-96d0d193a1fb",
    "aa55c19d-afdd-4ff4-8b1e-1cb0d59d2b26",
    "405e5b54-5445-48aa-9120-06c9c4764a84",
    "a5a6874a-47c5-4035-823f-053b27204f78",
]


# ── helpers ────────────────────────────────────────────────────────────────

def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _share(a, b):
    return (a / b) if b else 0.0


def _decade_label(d):
    d = int(d)
    return f"שנות ה-{d % 100:02d}" if d < 2000 else f"שנות ה-{d}"


def _norm_text(s):
    s = re.sub(r"\s+", " ", s.strip())
    s = s.strip("[]{}").strip()
    return s.upper()


def _norm_publisher(s):
    s = _norm_text(s)
    s = re.sub(r"\s*-\s*", "-", s) if re.search(r"[A-Z]", s) else s
    if s in UNKNOWN_MARKERS or s.replace("[", "").replace("]", "") in UNKNOWN_MARKERS:
        return ""
    return PUBLISHER_ALIASES.get(s, s)


def _place_country(raw):
    s = _norm_text(raw)
    if s in UNKNOWN_MARKERS:
        return NO_PLACE
    if HEB_RE.search(s):
        for key, country in HEBREW_FOREIGN:
            if key in s:
                return country
        if len(HEB_RE.findall(s)) < 3:
            return NO_PLACE
        return ISRAEL
    if not re.search(r"[A-Z]", s):
        return NO_PLACE
    for rx, country in LATIN_PLACES:
        if rx.search(s):
            return country
    return UNCLASSIFIED


def _prepare(df):
    title = df["item_name"].str.strip()
    lang = title.map(lambda t: HEB if HEB_RE.search(t) else FOR)
    yr = pd.to_numeric(df["pub_year"].str.strip(), errors="coerce")
    yr = yr.where((yr >= YEAR_MIN) & (yr <= YEAR_MAX))
    pages = pd.to_numeric(df["pages"].str.replace(",", "").str.strip(), errors="coerce")
    pages = pages.where(pages > 0)
    sticker = pd.to_numeric(df["item_sticker"].str.replace(",", "").str.strip(), errors="coerce")
    return pd.DataFrame({
        "title": title,
        "title_up": title.str.upper(),
        "lang": lang,
        "year": yr,
        "pages": pages,
        "sticker": sticker,
        "publisher": df["publishing_house"].map(_norm_publisher),
        "country": df["pub_place"].map(_place_country),
        "author": df["author_name"].fillna(""),
        "remarks": df["remarks"].str.strip(),
    })


def _top_counts(series, n):
    """Top-n value counts with a total, stable order (count desc, name asc)."""
    vc = series.value_counts()
    items = sorted(((int(v), k) for k, v in vc.items()), key=lambda t: (-t[0], t[1]))
    top = items[:n]
    rest = sum(v for v, _ in items[n:])
    return [k for _, k in top], [v for v, _ in top], rest, len(items)


# ── insight rules ──────────────────────────────────────────────────────────

def insight_lang_shift(dec):
    elig = [r for r in dec if r["total"] >= MIN_DECADE_ITEMS]
    if len(elig) < 2:
        return None
    a, b = elig[0], elig[-1]
    sa, sb = _share(a["foreign"], a["total"]), _share(b["foreign"], b["total"])
    diff = sb - sa
    if abs(diff) < 0.10:
        return None
    verb = "עלה" if diff > 0 else "ירד"
    return (f"שיעור הפריטים בלועזית {verb} מ-{_pct(sa, 0)} מהפריטים שפורסמו ב{_decade_label(a['decade'])} "
            f"ל-{_pct(sb, 0)} ב{_decade_label(b['decade'])}: "
            + ("הקטלוג עבר מספרות מקצועית ישראלית בעיקרה לספרות מחקר בינלאומית."
               if diff > 0 and sb > 0.5 and sa < 0.5 else
               "המשקל של הספרות בעברית השתנה במידה ניכרת לאורך השנים."))


def insight_peak(dec, n_dated, years, counts):
    if n_dated == 0 or not dec:
        return None
    top = sorted(dec, key=lambda r: (-r["total"], r["decade"]))[0]
    share = _share(top["total"], n_dated)
    if share < 0.25:
        return None
    i = max(range(len(counts)), key=lambda k: (counts[k], -years[k]))
    return (f"{_pct(share, 0)} מהפריטים שיש להם שנת פרסום ({_int(top['total'])} מתוך {_int(n_dated)}) "
            f"פורסמו ב{_decade_label(top['decade'])}; שנת השיא היא {years[i]} עם {_int(counts[i])} פריטים.")


def insight_recent(years, counts):
    if len(years) < 3 * RECENT_WINDOW:
        return None
    sums = [sum(counts[i:i + RECENT_WINDOW]) for i in range(len(counts) - RECENT_WINDOW + 1)]
    pk = max(range(len(sums)), key=lambda k: (sums[k], -k))
    recent = sums[-1]
    peak = sums[pk]
    if pk == len(sums) - 1 or peak == 0:
        return None
    ratio = recent / peak
    r0, r1 = years[-RECENT_WINDOW], years[-1]
    p0, p1 = years[pk], years[pk + RECENT_WINDOW - 1]
    if ratio < 0.25:
        return (f"מעט פרסומים חדשים: רק {_int(recent)} פריטים בקטלוג פורסמו בשנים {r0}-{r1}, "
                f"לעומת {_int(peak)} שפורסמו בשנים {p0}-{p1}, החלון של {RECENT_WINDOW} השנים העמוס ביותר.")
    if ratio >= 0.75:
        return (f"הקטלוג ממשיך להתעדכן: {_int(recent)} פריטים פורסמו בשנים {r0}-{r1}, "
                f"קרוב לשיא של {_int(peak)} בשנים {p0}-{p1}.")
    return None


def insight_publisher(pub_names, pub_counts, n_known):
    if not pub_names or n_known == 0:
        return None
    share = _share(pub_counts[0], n_known)
    if share < 0.08:
        return None
    second = ""
    if len(pub_names) > 1:
        second = f", ואחריה {pub_names[1]} עם {_int(pub_counts[1])}"
    return (f"ההוצאה הנפוצה ביותר בקטלוג היא {pub_names[0]}: {_int(pub_counts[0])} פריטים, "
            f"{_pct(share)} מהפריטים שצוינה בהם הוצאה{second}.")


def insight_origin(orig, n_placed, c_names, c_counts, n_abroad):
    if n_placed == 0:
        return None
    il = orig.get(ISRAEL, 0)
    abroad = sum(v for k, v in orig.items() if k not in (ISRAEL, UNCLASSIFIED, NO_PLACE))
    sa = _share(abroad, n_placed)
    si = _share(il, n_placed)
    if abs(sa - si) < 0.05:
        return None
    lead = "בחו״ל" if sa > si else "בישראל"
    text = (f"רוב הפריטים שזוהה בהם מקום פרסום יצאו לאור {lead}: {_pct(sa, 0)} בחו״ל לעומת "
            f"{_pct(si, 0)} בישראל (מתוך {_int(n_placed)} פריטים).")
    if c_names and n_abroad and _share(c_counts[0], n_abroad) >= 0.3:
        text += (f" בחו״ל מובילה {c_names[0]} עם {_int(c_counts[0])} פריטים, "
                 f"{_pct(_share(c_counts[0], n_abroad), 0)} מהפריטים שפורסמו מחוץ לישראל.")
    return text


def insight_pages(med):
    h, f = med.get(HEB), med.get(FOR)
    if not h or not f or h["n"] < MIN_PAGES_GROUP or f["n"] < MIN_PAGES_GROUP:
        return None
    hi, lo = (HEB, FOR) if h["median"] > f["median"] else (FOR, HEB)
    a, b = med[hi]["median"], med[lo]["median"]
    if b == 0 or a / b < 1.25:
        return None
    return (f"פריטים ב{hi} ארוכים יותר: חציון של {_int(a)} עמודים לעומת {_int(b)} בפריטים ב{lo} "
            f"(על בסיס {_int(med[HEB]['n'] + med[FOR]['n'])} פריטים שצוין בהם מספר עמודים).")


def insight_theme_shift(heat):
    decs = heat["decades"]
    if len(decs) < 2:
        return None
    best = None
    for j, lab in enumerate(heat["themes"]):
        a = heat["shares"][j][0]
        b = heat["shares"][j][-1]
        d = b - a
        key = (-abs(d), lab)
        if best is None or key < best[0]:
            best = (key, lab, a, b, d)
    _, lab, a, b, d = best
    if abs(d) < 3.0:
        return None
    verb = "זינק" if d > 0 else "צנח"
    return (f"השינוי הבולט בנושאים: משקל הכותרות בנושא {lab} {verb} מ-{a:.1f}% ב{decs[0]} "
            f"ל-{b:.1f}% ב{decs[-1]}.")


def insight_sticker(bands):
    if len(bands["labels"]) < 3:
        return None
    a, b = bands["median"][0], bands["median"][-1]
    if b - a < 10:
        return None
    return (f"מספרי המדבקה עוקבים ככל הנראה אחר סדר הקליטה לספרייה: חציון שנת הפרסום עולה מ-{a} "
            f"בטווח {bands['labels'][0]} ל-{b} בטווח {bands['labels'][-1]}.")


def insight_gaps(no_year, no_pages, total):
    if total == 0:
        return None
    sy, sp = _share(no_year, total), _share(no_pages, total)
    if max(sy, sp) < 0.10:
        return None
    return (f"איכות הרישום אינה אחידה: ל-{_pct(sp, 0)} מהפריטים לא צוין מספר עמודים, "
            f"ול-{_pct(sy, 0)} אין שנת פרסום תקינה ({_int(no_year)} פריטים), ולכן הם אינם נכללים בגרפים לפי שנה.")


# ── main ───────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])
    total = int(len(df))

    # language
    n_for = int((df["lang"] == FOR).sum())
    n_heb = total - n_for

    # years
    dated = df[df["year"].notna()].copy()
    dated["year"] = dated["year"].astype(int)
    n_dated = int(len(dated))
    no_year = total - n_dated
    if n_dated:
        y0, y1 = int(dated["year"].min()), int(dated["year"].max())
        ylist = list(range(y0, y1 + 1))
        ct = dated.groupby(["year", "lang"]).size()
        yheb = [int(ct.get((y, HEB), 0)) for y in ylist]
        yfor = [int(ct.get((y, FOR), 0)) for y in ylist]
        ytot = [a + b for a, b in zip(yheb, yfor)]
    else:
        y0 = y1 = None
        ylist, yheb, yfor, ytot = [], [], [], []

    # decades
    dated["decade"] = (dated["year"] // 10) * 10
    dec = []
    for d in sorted(dated["decade"].unique()):
        sub = dated[dated["decade"] == d]
        f = int((sub["lang"] == FOR).sum())
        dec.append({"decade": int(d), "total": int(len(sub)), "foreign": f,
                    "hebrew": int(len(sub)) - f})
    lang_dec = {
        "labels": [_decade_label(r["decade"]) for r in dec],
        "hebrew": [r["hebrew"] for r in dec],
        "foreign": [r["foreign"] for r in dec],
        "foreign_share": [round(_share(r["foreign"], r["total"]) * 100, 1) for r in dec],
        "totals": [r["total"] for r in dec],
    }

    # themes (multi-label)
    theme_hits = {k: df["title_up"].str.contains(rx) for k, _, rx in THEMES}
    th = sorted(((int(theme_hits[k].sum()), lab, k) for k, lab, _ in THEMES),
                key=lambda t: (-t[0], t[1]))
    th = [t for t in th if t[0] > 0]
    themes_chart = {
        "names": [lab for _, lab, _ in th],
        "counts": [c for c, _, _ in th],
        "shares": [round(_share(c, total) * 100, 1) for c, _, _ in th],
    }
    n_any_theme = int(pd.concat(list(theme_hits.values()), axis=1).any(axis=1).sum()) if total else 0

    # theme x decade heatmap (eligible decades only)
    elig = [r["decade"] for r in dec if r["total"] >= MIN_DECADE_ITEMS]
    heat_themes = [lab for _, lab, _ in th]
    heat_keys = [k for _, _, k in th]
    cells, shares = [], []
    for j, k in enumerate(heat_keys):
        row = []
        hit = theme_hits[k]
        for i, d in enumerate(elig):
            mask = (df["year"] >= d) & (df["year"] < d + 10)
            n = int(mask.sum())
            c = int((hit & mask).sum())
            s = round(_share(c, n) * 100, 1)
            row.append(s)
            cells.append([i, j, s, c])
        shares.append(row)
    heat = {"decades": [_decade_label(d) for d in elig], "themes": heat_themes,
            "cells": cells, "shares": shares,
            "max": max([c[2] for c in cells], default=0)}

    # publishers
    pubs = df["publisher"][df["publisher"] != ""]
    n_pub_known = int(len(pubs))
    pnames, pcounts, prest, n_publishers = _top_counts(pubs, TOP_PUBLISHERS)
    publishers = {"names": pnames, "counts": pcounts,
                  "shares": [round(_share(c, n_pub_known) * 100, 1) for c in pcounts],
                  "rest": prest}

    # place / country
    orig = df["country"].value_counts().to_dict()
    orig = {k: int(v) for k, v in orig.items()}
    n_noplace = orig.get(NO_PLACE, 0)
    n_placed = total - n_noplace - orig.get(UNCLASSIFIED, 0)
    abroad = df["country"][~df["country"].isin([ISRAEL, UNCLASSIFIED, NO_PLACE])]
    n_abroad = int(len(abroad))
    n_il = orig.get(ISRAEL, 0)
    origin = {"names": ["ישראל", "חו״ל", UNCLASSIFIED, NO_PLACE],
              "counts": [n_il, n_abroad, orig.get(UNCLASSIFIED, 0), n_noplace]}
    origin["shares"] = [round(_share(c, total) * 100, 1) for c in origin["counts"]]
    cnames, ccounts, crest, n_countries = _top_counts(abroad, TOP_COUNTRIES)
    countries = {"names": cnames, "counts": ccounts, "rest": crest,
                 "shares": [round(_share(c, n_abroad) * 100, 1) for c in ccounts]}

    # pages
    pg = df[df["pages"].notna()]
    n_pages = int(len(pg))
    no_pages = total - n_pages
    bins = [lab for _, _, lab in PAGE_BINS] + [PAGE_TOP_LABEL]

    def _bin(p):
        for lo, hi, lab in PAGE_BINS:
            if lo <= p <= hi:
                return lab
        return PAGE_TOP_LABEL
    pb = pg.assign(bin=pg["pages"].map(_bin)).groupby(["bin", "lang"]).size()
    pages_chart = {"bins": bins,
                   "hebrew": [int(pb.get((b, HEB), 0)) for b in bins],
                   "foreign": [int(pb.get((b, FOR), 0)) for b in bins]}
    med = {}
    for lg in LANGS:
        s = pg["pages"][pg["lang"] == lg]
        if len(s):
            med[lg] = {"n": int(len(s)), "median": int(round(float(s.median())))}
    median_all = int(round(float(pg["pages"].median()))) if n_pages else 0

    # authors (split co-authors on "/")
    au = df["author"].str.split("/").explode().map(_norm_text)
    au = au[(au != "") & (~au.isin(UNKNOWN_MARKERS))]
    n_author_items = int((df["author"].map(_norm_text) != "").sum())
    anames, acounts, arest, n_authors = _top_counts(au, TOP_AUTHORS)
    authors = {"names": anames, "counts": acounts}

    # remarks
    rm = df["remarks"][df["remarks"] != ""]
    n_remarks = int(len(rm))
    rnames, rcounts = [], []
    matched_any = pd.Series(False, index=rm.index)
    for lab, rx in REMARKS:
        hit = rm.str.upper().str.contains(rx)
        matched_any |= hit
        rnames.append(lab)
        rcounts.append(int(hit.sum()))
    rnames.append(REMARK_OTHER)
    rcounts.append(int((~matched_any).sum()))
    remarks = {"names": rnames, "counts": rcounts}
    n_digital = rcounts[0]

    # sticker bands -> median publication year
    sb = df[df["sticker"].notna() & df["year"].notna()].copy()
    sb["band"] = (sb["sticker"] // STICKER_BAND).astype(int)
    bands = {"labels": [], "median": [], "counts": []}
    dropped_band_items = 0
    for b in sorted(sb["band"].unique()):
        sub = sb[sb["band"] == b]
        if len(sub) < MIN_BAND_ITEMS:
            dropped_band_items += int(len(sub))
            continue
        lo = int(b) * STICKER_BAND
        bands["labels"].append(f"{lo:,}-{lo + STICKER_BAND - 1:,}")
        bands["median"].append(int(round(float(sub["year"].median()))))
        bands["counts"].append(int(len(sub)))

    # ── insights ──
    rules = [
        ("lang_shift", insight_lang_shift(dec)),
        ("peak", insight_peak(dec, n_dated, ylist, ytot)),
        ("recent", insight_recent(ylist, ytot)),
        ("publisher", insight_publisher(pnames, pcounts, n_pub_known)),
        ("origin", insight_origin(orig, n_placed, cnames, ccounts, n_abroad)),
        ("theme_shift", insight_theme_shift(heat)),
        ("pages", insight_pages(med)),
        ("sticker", insight_sticker(bands)),
        ("gaps", insight_gaps(no_year, no_pages, total)),
    ]
    insights = [{"id": k, "text_he": t} for k, t in rules if t]

    # ── KPIs ──
    for_share = _share(n_for, total)
    gap_share = _share(no_year, total)
    peak_i = max(range(len(ytot)), key=lambda k: (ytot[k], -ylist[k])) if ytot else None
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand"},
        "foreign": {"value": round(for_share * 100, 1), "display": _pct(for_share, 0), "tone": "info"},
        "span": {"value": f"{y0}-{y1}" if y0 else "",
                 "display": f"{y0}–{y1}" if y0 else "אין", "tone": "brand"},
        "peak": {"value": ylist[peak_i] if peak_i is not None else 0,
                 "display": str(ylist[peak_i]) if peak_i is not None else "אין", "tone": "brand"},
        "publishers": {"value": n_publishers, "display": _int(n_publishers), "tone": "brand"},
        "median_pages": {"value": median_all, "display": _int(median_all), "tone": "brand"},
        "digital": {"value": n_digital, "display": _int(n_digital), "tone": "brand"},
        "no_year": {"value": no_year, "display": _int(no_year),
                    "tone": "warn" if gap_share >= 0.10 else "brand"},
    }

    # ── labels / ledes ──
    top_dec = sorted(dec, key=lambda r: (-r["total"], r["decade"]))[0] if dec else None
    labels = {
        "peak_kpi": (f"שנת השיא בפרסומים ({_int(ytot[peak_i])} פריטים)" if peak_i is not None
                     else "שנת השיא בפרסומים"),
        "no_year_kpi": f"פריטים ללא שנת פרסום תקינה ({_pct(gap_share, 0)})",
        "median_pages_kpi": f"חציון עמודים לפריט (מתוך {_int(n_pages)} פריטים עם מספר עמודים)",
        "years_lede": (f"{_int(n_dated)} פריטים עם שנת פרסום בין {y0} ל-{y1}, מחולקים לפי שפת הכותר. "
                       f"{_int(no_year)} פריטים ללא שנה תקינה (ריקה, חלקית או מחוץ לטווח {YEAR_MIN}-{YEAR_MAX}) אינם מוצגים."
                       if n_dated else "אין פריטים עם שנת פרסום תקינה."),
        "years_aria": (f"גרף עמודות מוערם: מספר הפריטים בקטלוג לפי שנת פרסום ושפה, {y0}-{y1}. "
                       f"שיא בשנת {ylist[peak_i]} עם {_int(ytot[peak_i])} פריטים."
                       if peak_i is not None else "גרף עמודות: פריטים לפי שנת פרסום."),
        "lang_lede": (f"בסך הכול {_int(n_heb)} פריטים בעברית ו-{_int(n_for)} בלועזית. "
                      "הקו מראה את שיעור הפריטים בלועזית בכל עשור (לפי שנת הפרסום)."),
        "lang_aria": (f"גרף עמודות וקו: פריטים בעברית ובלועזית לפי עשור הפרסום. "
                      f"העשור העמוס ביותר: {_decade_label(top_dec['decade'])} עם {_int(top_dec['total'])} פריטים."
                      if top_dec else "גרף עמודות: פריטים לפי עשור."),
        "themes_lede": (f"{_int(n_any_theme)} פריטים ({_pct(_share(n_any_theme, total), 0)}) תואמים לפחות נושא אחד. "
                        "הסיווג לפי מילות מפתח בכותר, בעברית ובאנגלית; פריט יכול להשתייך לכמה נושאים."),
        "themes_aria": (f"גרף עמודות אופקי: מספר הפריטים לפי נושא בכותר. המוביל: {themes_chart['names'][0]} "
                        f"עם {_int(themes_chart['counts'][0])} פריטים." if themes_chart["names"]
                        else "גרף עמודות: פריטים לפי נושא."),
        "heat_lede": (f"שיעור הכותרות בכל נושא מתוך כלל הפריטים שפורסמו באותו עשור. מוצגים רק עשורים עם "
                      f"{_int(MIN_DECADE_ITEMS)} פריטים לפחות."),
        "heat_aria": "מפת חום: שיעור הכותרות בכל נושא לפי עשור הפרסום.",
        "pub_lede": (f"{_int(n_pub_known)} פריטים שצוינה בהם הוצאה לאור, מתוך {_int(n_publishers)} הוצאות שונות "
                     f"(אחרי איחוד כתיב). {_int(total - n_pub_known)} פריטים ללא הוצאה או עם \"חמו״ל\" אינם מוצגים."),
        "pub_aria": (f"גרף עמודות אופקי: {len(pnames)} ההוצאות לאור עם הכי הרבה פריטים. "
                     f"המובילה: {pnames[0]} עם {_int(pcounts[0])} פריטים." if pnames
                     else "גרף עמודות: הוצאות לאור."),
        "origin_lede": (f"מקום הפרסום מסווג למדינה לפי שם העיר או המדינה שנרשם. מקומות בכתב עברי נספרים כישראל, "
                        f"אלא אם הם שם של מקום בחו״ל. {_int(orig.get(UNCLASSIFIED, 0))} פריטים עם מקום לועזי שלא זוהה "
                        f"ו-{_int(n_noplace)} ללא מקום מוצגים בנפרד."),
        "origin_aria": (f"גרף טבעת: מקום הפרסום של הפריטים. ישראל {_int(n_il)}, חו״ל {_int(n_abroad)}."),
        "country_aria": (f"גרף עמודות אופקי: מדינות הפרסום בחו״ל. המובילה: {cnames[0]} עם {_int(ccounts[0])} פריטים."
                         if cnames else "גרף עמודות: מדינות פרסום בחו״ל."),
        "pages_lede": (f"התפלגות מספר העמודים ב-{_int(n_pages)} פריטים שצוין בהם מספר עמודים "
                       f"({_int(no_pages)} פריטים ללא מספר עמודים אינם מוצגים)."),
        "pages_aria": f"גרף עמודות מקובצות: פריטים לפי טווח מספר עמודים ושפה. חציון כולל: {_int(median_all)} עמודים.",
        "auth_lede": (f"{_int(n_author_items)} פריטים שצוין בהם מחבר או עורך; פריט עם כמה מחברים נספר אצל כל אחד מהם. "
                      "ברשימה גם גופים שנרשמו בשדה המחבר, כמו הוצאות לאור וארגונים."),
        "auth_aria": (f"גרף עמודות אופקי: מחברים ועורכים מובילים. המוביל: {anames[0]} עם {_int(acounts[0])} פריטים."
                      if anames else "גרף עמודות: מחברים."),
        "rem_lede": (f"ל-{_int(n_remarks)} פריטים ({_pct(_share(n_remarks, total), 0)}) נרשמה הערה. "
                     "ההערות מסווגות לפי מילות מפתח; הערה אחת יכולה להיכלל בכמה סוגים."),
        "rem_aria": f"גרף עמודות אופקי: סוגי ההערות בקטלוג. עותק דיגיטלי צוין ב-{_int(n_digital)} פריטים.",
        "band_lede": (f"חציון שנת הפרסום בכל טווח של {_int(STICKER_BAND)} מספרי מדבקה (מספר המדף בספרייה). "
                      f"מוצגים טווחים עם {_int(MIN_BAND_ITEMS)} פריטים מתוארכים לפחות"
                      + (f"; {_int(dropped_band_items)} פריטים בטווחים קטנים יותר אינם מוצגים." if dropped_band_items
                         else ".")),
        "band_aria": (f"גרף קו: חציון שנת הפרסום לפי טווח מספרי מדבקה, מ-{bands['median'][0]} "
                      f"ל-{bands['median'][-1]}." if bands["labels"] else "גרף קו: שנת פרסום לפי מספר מדבקה."),
    }

    summary = (f"קטלוג הספרייה המקצועית של משרד התיירות: איתור ספרים, דוחות ומחקרי תיירות לפי כותר, מחבר או הוצאה. "
               f"{_int(total)} פריטים, {_pct(for_share, 0)} בלועזית.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["תיירות", "ספרייה", "ספרות מקצועית", "מחקר תיירות", "ביבליוגרפיה"],
            "related_ids": RELATED,
            **({"temporal_coverage": f"{y0}/{y1}"} if y0 else {}),
        },
        "kpis": kpis,
        "charts": {
            "years": {"x": [str(y) for y in ylist], "hebrew": yheb, "foreign": yfor},
            "lang": lang_dec,
            "themes": themes_chart,
            "heat": heat,
            "publishers": publishers,
            "origin": origin,
            "countries": countries,
            "pages": pages_chart,
            "authors": authors,
            "remarks": remarks,
            "bands": bands,
        },
        "flags": {
            "heat": len(heat["decades"]) >= 2 and len(heat["themes"]) > 0,
            "bands": len(bands["labels"]) >= 3,
            "countries": len(cnames) > 0,
            "authors": len(anames) > 0,
        },
        "insights": insights,
        "labels": labels,
    }
