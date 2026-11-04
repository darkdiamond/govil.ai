"""Economic attachés of the Ministry of Economy and Industry: a directory of
missions abroad (country, flag image, link to the mission's gov.il page).

The data has no region column, so the region comes from a fixed mapping
keyed on the gov.il page slug (stable English) with the Hebrew name as a
second key; anything unmapped lands in "אחר" and the page says so.
"""

import re

from govlib import fmt
from govlib.frame import clean

EUROPE = "אירופה"
ASIA = "אסיה"
LATAM = "אמריקה הלטינית"
NAM = "צפון אמריקה"
AFRICA = "אפריקה"
OCEANIA = "אוקיאניה"
MULTI = "ארגונים בין-לאומיים"
OTHER = "אחר"

# Continents in a fixed display order for ties; multilateral and unmapped last.
REGION_ORDER = [ASIA, EUROPE, LATAM, AFRICA, NAM, OCEANIA, MULTI, OTHER]

SLUG_REGION = {
    # Europe
    "italy": EUROPE, "uk": EUROPE, "germany": EUROPE, "denmark": EUROPE,
    "netherlands": EUROPE, "spain": EUROPE, "poland": EUROPE, "france": EUROPE,
    "romania": EUROPE, "sweden": EUROPE, "belgium": EUROPE, "switzerland": EUROPE,
    "austria": EUROPE, "greece": EUROPE, "cyprus": EUROPE, "czech": EUROPE,
    "czech-republic": EUROPE, "hungary": EUROPE, "portugal": EUROPE,
    "ireland": EUROPE, "norway": EUROPE, "finland": EUROPE, "ukraine": EUROPE,
    "russia": EUROPE, "turkey": EUROPE, "serbia": EUROPE, "bulgaria": EUROPE,
    "croatia": EUROPE, "slovakia": EUROPE,
    # Asia
    "uae": ASIA, "indonesia": ASIA, "south-korea": ASIA, "india": ASIA,
    "vietnam": ASIA, "taiwan": ASIA, "japan": ASIA, "china": ASIA,
    "hong-kong": ASIA, "singapore": ASIA, "philippines": ASIA, "thailand": ASIA,
    "kazakhstan": ASIA, "bahrain": ASIA, "malaysia": ASIA, "uzbekistan": ASIA,
    "azerbaijan": ASIA, "saudi-arabia": ASIA, "jordan": ASIA, "egypt": AFRICA,
    # Americas
    "usa": NAM, "us": NAM, "canada": NAM,
    "argentina": LATAM, "brazil": LATAM, "mexico": LATAM, "peru": LATAM,
    "chile": LATAM, "colombia": LATAM, "panama": LATAM, "uruguay": LATAM,
    "ecuador": LATAM, "guatemala": LATAM, "costa-rica": LATAM,
    # Africa
    "ghana": AFRICA, "south-africa": AFRICA, "morocco": AFRICA, "kenya": AFRICA,
    "nigeria": AFRICA, "ethiopia": AFRICA, "rwanda": AFRICA, "ivory-coast": AFRICA,
    # Oceania
    "australia": OCEANIA, "new-zealand": OCEANIA,
}

NAME_REGION = {
    "אוסטרליה": OCEANIA, "ניו זילנד": OCEANIA,
    "איחוד האמירויות הערביות": ASIA, "אינדונזיה": ASIA, "דרום קוריאה": ASIA,
    "הודו": ASIA, "וייטנאם": ASIA, "טאיפיי": ASIA, "טייוואן": ASIA, "יפן": ASIA,
    "סין": ASIA, "סין - הונג קונג": ASIA, "הונג קונג": ASIA, "סינגפור": ASIA,
    "פיליפינים": ASIA, "תאילנד": ASIA, "קזחסטן": ASIA, "בחריין": ASIA,
    "איטליה": EUROPE, "בריטניה": EUROPE, "גרמניה": EUROPE, "דנמרק": EUROPE,
    "הולנד": EUROPE, "ספרד": EUROPE, "פולין": EUROPE, "צרפת": EUROPE,
    "רומניה": EUROPE, "שוודיה": EUROPE, "בלגיה": EUROPE, "שווייץ": EUROPE,
    "אוסטריה": EUROPE, "יוון": EUROPE, "קפריסין": EUROPE, "צ'כיה": EUROPE,
    "הונגריה": EUROPE, "פורטוגל": EUROPE, "אוקראינה": EUROPE, "טורקיה": EUROPE,
    "ארצות הברית": NAM, "קנדה": NAM,
    "ארגנטינה": LATAM, "ברזיל": LATAM, "מקסיקו": LATAM, "פרו": LATAM,
    "צ'ילה": LATAM, "קולומביה": LATAM, "פנמה": LATAM,
    "גאנה": AFRICA, "דרום אפריקה": AFRICA, "מרוקו": AFRICA, "קניה": AFRICA,
    "ניגריה": AFRICA, "אתיופיה": AFRICA, "רואנדה": AFRICA, "מצרים": AFRICA,
}

KIND_LOCAL = "נספחות במדינה"
KIND_SERVED = "מכוסה מנספחות שכנה"
KIND_MULTI = "נציגות בארגון בין-לאומי"
KINDS = [KIND_LOCAL, KIND_SERVED, KIND_MULTI]

_PAREN_RE = re.compile(r"\s*\(([^()]*)\)\s*$")


_URL_RE = re.compile(r"https://([a-z0-9.-]+)(/[^\s\\@?#]*)?(?:[?#][^\s\\@]*)?", re.IGNORECASE)
_IMG_RE = re.compile(r"\.(?:jpe?g|png|gif|webp|svg)$", re.IGNORECASE)


def _url_parts(u: str):
    """(host, path) of a plain https URL with no userinfo or port, else None."""
    m = _URL_RE.fullmatch(u)
    if not m:
        return None
    return m.group(1).lower().rstrip("."), m.group(2) or ""


def _safe_url(u: str, page: bool) -> str:
    """Only plain https links/images on gov.il hosts reach the page."""
    u = clean(u)
    parts = _url_parts(u) if u else None
    if not parts:
        return ""
    host, path = parts
    if not (host == "gov.il" or host.endswith(".gov.il")):
        return ""
    if host == "data.gov.il" or host.endswith(".data.gov.il"):
        return ""
    if not page and not _IMG_RE.search(path):
        return ""
    return u


def _slug(link: str) -> str:
    parts = _url_parts(link) if link else None
    if not parts:
        return ""
    seg = parts[1].rstrip("/").rsplit("/", 1)[-1].lower()
    for p in ("export-to-", "export-"):
        if seg.startswith(p):
            return seg[len(p):]
    return seg


def _parse(name: str, link: str):
    """→ (base name, hub or '', kind)."""
    base, hub = name, ""
    m = _PAREN_RE.search(name)
    if m:
        inner = m.group(1).strip()
        base = name[: m.start()].strip()
        if inner.startswith("מ") and len(inner) > 2:
            hub = inner[1:].strip()
    slug = _slug(link)
    if "נציגות" in name or "economy-attache" in slug:
        return base, "", KIND_MULTI
    return base, hub, (KIND_SERVED if hub else KIND_LOCAL)


def _region(base: str, slug: str, kind: str) -> str:
    if kind == KIND_MULTI:
        return MULTI
    if slug in SLUG_REGION:
        return SLUG_REGION[slug]
    return NAME_REGION.get(base, OTHER)


def compute(frames):
    df = frames["main"]
    rows = []
    seen = set()
    for flag, country, link in zip(df["flag"], df["country"], df["link"]):
        name = clean(country)
        if not name:
            continue
        link_ok = _safe_url(link, page=True)
        flag_ok = _safe_url(flag, page=False)
        key = (name, link_ok)
        if key in seen:
            continue
        seen.add(key)
        base, hub, kind = _parse(name, link_ok)
        region = _region(base, _slug(link_ok), kind)
        rows.append({"name": name, "base": base, "hub": hub, "kind": kind,
                     "region": region, "flag": flag_ok, "link": link_ok})
    rows.sort(key=lambda r: (r["name"], r["link"], r["flag"]))

    n = len(rows)
    n_multi = sum(r["kind"] == KIND_MULTI for r in rows)
    n_served = sum(r["kind"] == KIND_SERVED for r in rows)
    n_local = sum(r["kind"] == KIND_LOCAL for r in rows)
    n_countries = n - n_multi
    n_unmapped = sum(r["region"] == OTHER for r in rows)

    # ---- regions ------------------------------------------------------
    reg_count = {}
    reg_kind = {}
    for r in rows:
        reg_count[r["region"]] = reg_count.get(r["region"], 0) + 1
        reg_kind.setdefault(r["region"], {k: 0 for k in KINDS})[r["kind"]] += 1

    def reg_key(g):
        tail = 1 if g in (MULTI, OTHER) else 0
        return (tail, -reg_count[g], REGION_ORDER.index(g) if g in REGION_ORDER else 99, g)

    regions = sorted(reg_count, key=reg_key)
    continents = [g for g in regions if g not in (MULTI, OTHER)]

    charts = {
        "regions": {
            "names": regions,
            "series": [
                {"name": k, "values": [reg_kind[g][k] for g in regions]}
                for k in KINDS if any(reg_kind[g][k] for g in regions)
            ],
        },
        "kinds": {
            "names": [k for k in KINDS if any(r["kind"] == k for r in rows)],
            "values": [c for c in (n_local, n_served, n_multi) if c],
        },
    }

    region_table = [
        [g, fmt.int_he(reg_kind[g][KIND_LOCAL]), fmt.int_he(reg_kind[g][KIND_SERVED]),
         fmt.int_he(reg_kind[g][KIND_MULTI]), fmt.int_he(reg_count[g])]
        for g in regions
    ]
    kinds_table = [
        [k, fmt.int_he(v), fmt.pct(v / n) if n else "0%"]
        for k, v in zip(charts["kinds"]["names"], charts["kinds"]["values"])
    ]

    # ---- directory grouped by region ----------------------------------
    directory = []
    for g in regions:
        items = [r for r in rows if r["region"] == g]
        directory.append({
            "region": g,
            "count": len(items),
            "entries": [{
                "name": r["name"], "flag": r["flag"], "link": r["link"],
                "note": (f"מכוסה מנספחות {r['hub']}" if r["hub"] else ""),
            } for r in items],
        })

    # ---- hubs (one mission serving another country) --------------------
    hubs = {}
    for r in rows:
        if r["kind"] == KIND_SERVED:
            hubs.setdefault(r["hub"], []).append(r["base"])
    hub_rows = [[h, fmt.join_he(sorted(v))] for h, v in
                sorted(hubs.items(), key=lambda kv: (-len(kv[1]), kv[0]))]

    # ---- insights ------------------------------------------------------
    insights = []

    if len(continents) >= 2:
        a, b = continents[0], continents[1]
        if reg_count[a] > reg_count[b] and n_countries:
            insights.append({"id": "leader", "text_he": (
                f"{a} מובילה במספר הנספחויות: {fmt.int_he(reg_count[a])} מתוך "
                f"{fmt.int_he(n_countries)} המדינות ברשימה ({fmt.pct(reg_count[a] / n_countries)}), "
                f"לפני {b} עם {fmt.int_he(reg_count[b])}.")})

    trad = reg_count.get(EUROPE, 0) + reg_count.get(NAM, 0)
    mapped = n_countries - n_unmapped
    if mapped >= 5:
        outside = mapped - trad
        if outside > trad:
            insights.append({"id": "outside", "text_he": (
                f"רוב הנספחויות במדינות ({fmt.int_he(outside)} מתוך {fmt.int_he(mapped)}, "
                f"{fmt.pct(outside / mapped)}) נמצאות מחוץ לאירופה ולצפון אמריקה: "
                + fmt.join_he(["ב" + g for g in continents if g not in (EUROPE, NAM)]) + ".")})
        elif trad > outside:
            insights.append({"id": "outside", "text_he": (
                f"רוב הנספחויות במדינות ({fmt.int_he(trad)} מתוך {fmt.int_he(mapped)}, "
                f"{fmt.pct(trad / mapped)}) נמצאות באירופה ובצפון אמריקה.")})

    if n_served:
        pairs = [f"{r['base']} (מ{r['hub']})" for r in rows if r["kind"] == KIND_SERVED]
        one = n_served == 1
        insights.append({"id": "served", "text_he": (
            f"מדינה אחת ברשימה אינה מחזיקה נספחות משלה ומכוסה מנספחות שכנה: {pairs[0]}."
             if one else
             f"{fmt.int_he(n_served)} מדינות ברשימה אינן מחזיקות נספחות משלהן ומכוסות "
             f"מנספחות שכנה: {fmt.join_he(pairs)}.")})

    if n_multi:
        multi_names = [r["name"] for r in rows if r["kind"] == KIND_MULTI]
        insights.append({"id": "multi", "text_he": (
            f"מלבד {fmt.int_he(n_countries)} המדינות, הרשימה כוללת "
            + ("נציגות כלכלית אחת בארגון בין-לאומי: " if n_multi == 1 else
               f"{fmt.int_he(n_multi)} נציגויות כלכליות בארגונים בין-לאומיים: ")
            + fmt.join_he(multi_names) + ".")})

    singles = [g for g in continents if reg_count[g] == 1]
    if singles and len(continents) >= 3:
        who = [f"ב{g} ({next(r['base'] for r in rows if r['region'] == g)})" for g in singles]
        insights.append({"id": "single", "text_he": (
            "נספחות יחידה בלבד " + fmt.join_he(who) + ".")})

    # ---- KPIs ------------------------------------------------------------
    kpis = {
        "total": {"value": n, "display": fmt.int_he(n), "tone": "brand"},
        "countries": {"value": n_countries, "display": fmt.int_he(n_countries), "tone": "brand"},
        "served": {"value": n_served, "display": fmt.int_he(n_served),
                   "tone": "info" if n_served else "brand"},
        "multi": {"value": n_multi, "display": fmt.int_he(n_multi), "tone": "brand"},
        "regions": {"value": len(continents), "display": fmt.int_he(len(continents)), "tone": "brand"},
    }

    # ---- text ----------------------------------------------------------
    # Name a leading region only when it is strictly ahead of the next one.
    lead = continents[0] if continents and (
        len(continents) == 1 or reg_count[continents[0]] > reg_count[continents[1]]) else ""
    summary = (
        f"רשימת הנספחים הכלכליים של משרד הכלכלה והתעשייה בעולם: {fmt.int_he(n)} נציגויות, "
        f"מהן {fmt.int_he(n_countries)} במדינות ב-{fmt.int_he(len(continents))} אזורים בעולם"
        + (f" ו-{fmt.int_he(n_multi)} בארגונים בין-לאומיים" if n_multi else "")
        + ", עם קישור לעמוד כל נספחות ולפרטי הקשר שלה."
    )
    lede = summary + (
        f" הנספחים מסייעים ליצואנים ישראלים לפתח קשרי סחר במדינת היעד. {lead} מובילה עם "
        f"{fmt.int_he(reg_count[lead])} נספחויות." if lead else "")
    if n_unmapped:
        lede += f" {fmt.int_he(n_unmapped)} רשומות לא שויכו לאזור ומופיעות תחת \"{OTHER}\"."

    description = (
        f"איתור הנספח הכלכלי של ישראל לפי מדינה: {fmt.int_he(n_countries)} מדינות"
        + (f" ו-{fmt.int_he(n_multi)} ארגונים בין-לאומיים" if n_multi else "")
        + ", עם קישור לעמוד הנספחות ולפרטי הקשר."
    )

    labels = {
        "lede": lede,
        "kpi_total": "נציגויות כלכליות ברשימה",
        "kpi_countries": "מדינות עם נספחות",
        "kpi_served": "מדינות המכוסות מנספחות שכנה",
        "kpi_multi": "נציגויות בארגונים בין-לאומיים",
        "kpi_regions": "אזורים בעולם",
        "regions_note": (
            f"{fmt.int_he(n)} הנציגויות לפי אזור. מדינה שמכוסה מנספחות במדינה שכנה מסומנת בנפרד."
        ),
        "regions_aria": "מספר הנספחויות הכלכליות לפי אזור וסוג",
        "kinds_note": (
            f"{fmt.int_he(n_local)} נספחויות פועלות במדינה עצמה"
            + (f", {fmt.int_he(n_served)} מדינות מכוסות מנספחות שכנה" if n_served else "")
            + (f" ו-{fmt.int_he(n_multi)} נציגויות יושבות בארגונים בין-לאומיים" if n_multi else "")
            + "."
        ),
        "kinds_aria": "התפלגות הנציגויות לפי סוג",
        "directory_note": (
            "כל הנספחויות לפי אזור, מסודרות לפי שם. הקישור מוביל לעמוד הנספחות באתר gov.il, "
            "שם מופיעים שם הנספח ודרכי יצירת הקשר."
        ),
        "hubs_note": "נספחויות שמשרתות גם מדינה שכנה שאין בה נספחות משלה.",
        "hubs_cap": "נספחויות המשרתות מדינות נוספות",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "עולמי",
            "seo": {
                "title": "נספחים כלכליים של ישראל בעולם: רשימה ופרטי קשר",
                "description": description,
                "name": "הנספחים הכלכליים של ישראל בעולם",
                "alternate_names": [
                    "רשימת נספחויות כלכליות",
                    "נספחות כלכלית",
                    "נספח כלכלי",
                    "נספחי סחר ישראלים",
                    "הנספחות הכלכלית של משרד הכלכלה",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "labels": labels,
        "tables": {
            "regions": {"headers": ["אזור", KIND_LOCAL, KIND_SERVED, KIND_MULTI, "סה\"כ"],
                        "rows": region_table},
            "kinds": {"headers": ["סוג", "נציגויות", "שיעור"], "rows": kinds_table},
            "hubs": {"headers": ["נספחות", "משרתת גם את"], "rows": hub_rows},
        },
        "directory": directory,
    }
