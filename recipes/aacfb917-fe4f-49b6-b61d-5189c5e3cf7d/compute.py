"""Half-day air-pollution forecast (Ministry of Environmental Protection, CHIMERE model).

The resource is a single snapshot that the ministry overwrites two or three
times a day. It mixes two row kinds:

* `type == "Map"`: one row per forecast region, with the expected pollution
  level (`air_quality`, e.g. "בינונית"), the map fill colour and a link to the
  ministry's list of settlements in that region.
* `type == "Content"`: a public warning row (`name == "Warning"`, `show`
  says whether it is currently displayed) and one row per forecast day
  (`OneDay`, `TwoDay`, ...) with free-text forecasts for morning / noon /
  evening.

Every number on the page is computed here. Each insight rule returns a
sentence or None; a rule whose premise does not hold drops out.
"""
import re

import pandas as pd

# Ordinal scale of the ministry's pollution levels. Matched on word stems so
# both the feminine region labels ("בינונית") and the masculine forecast text
# ("זיהום אוויר בינוני") map to the same rank. Unknown labels keep rank None.
LEVELS = [
    (1, "נמוכה"),
    (2, "בינונית"),
    (3, "גבוהה"),
    (4, "גבוהה מאוד"),
]
LEVEL_NAME = dict(LEVELS)
LEVEL_NAME_M = {1: "נמוך", 2: "בינוני", 3: "גבוה", 4: "גבוה מאוד"}
LEVEL_COLOR = {1: "#198754", 2: "#ffc107", 3: "#dc3545", 4: "#8f1d2c"}

# Approximate centre of each forecast region (WGS84), keyed by the dataset's
# stable English `name` code. A region code not listed here is still shown in
# every table and chart, just not on the map (disclosed on the page).
REGION_CENTRES = {
    "GalileeUpperAndGolan": (33.02, 35.62),
    "GalileeLowerAndValleys": (32.68, 35.33),
    "GreaterHaifa": (32.79, 35.03),
    "Jordan": (32.15, 35.50),
    "SharonCarmel": (32.40, 34.91),
    "Shomron": (32.18, 35.22),
    "TelAviv": (32.07, 34.80),
    "InnerLowland": (31.86, 34.93),
    "GreaterJerusalem": (31.78, 35.21),
    "SouthernCoastalPlain": (31.68, 34.60),
    "Yehuda": (31.50, 35.10),
    "BeerSheva": (31.25, 34.79),
    "NegevAndArava": (30.60, 35.00),
    "Eilat": (29.56, 34.95),
}
NORTH_LAT = 32.6   # regions centred north of this count as "north"
SOUTH_LAT = 31.4   # ... and south of this as "south"

POLLUTANTS = [
    ("אוזון", "אוזון"),
    ("חלקיק", "חלקיקים נשימים"),
    ("אבק", "אבק"),
    ("תחמוצות חנקן", "תחמוצות חנקן"),
    ("חנקן דו", "חנקן דו־חמצני"),
    ("גופרית", "גופרית דו־חמצנית"),
    ("בנזן", "בנזן"),
    ("עשן", "עשן"),
]

PERIODS = [("morning", "morning_content"), ("noon", "noon_content"),
           ("evening", "evening_content")]

GOV_LINK_RE = re.compile(r"^https://www\.gov\.il/[A-Za-z0-9_./%-]+$")
RGB_RE = re.compile(r"^\[\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")


def _clean(s):
    s = (s or "").replace("_x000D_", " ").replace("\r", " ")
    s = s.strip()
    if s.lower() in ("", "null", "none", "nan"):
        return ""
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _int(n):
    return f"{int(n):,}"


def level_rank(text):
    """Rank of the first level mentioned in a label, or None."""
    t = _clean(text)
    if not t:
        return None
    if re.search(r"גבוה\S*\s+מאוד", t):
        return 4
    if "גבוה" in t:
        return 3
    if "בינונ" in t:
        return 2
    if "נמוכ" in t or "נמוך" in t:
        return 1
    return None


# A level adjective counts only where it describes the pollution itself
# ("זיהום אוויר נמוך עד בינוני", "רמת זיהום גבוהה"), never a pollutant's
# concentration ("ריכוזים גבוהים של אבק").
_LVL = r"(?:ו-?|ה)?(?:גבוה|בינונ|נמוכ|נמוך)\S*(?:\s+מאוד)?"
LEVEL_SPAN_RE = re.compile(
    r"(?:זיהום\s+(?:ה)?אוויר|רמת\s+(?:ה)?זיהום(?:\s+(?:ה)?אוויר)?)\s+"
    r"(?:ברמ(?:ה|ות)\s+)?(" + _LVL + r"(?:\s+(?:עד|או)\s+" + _LVL
    + r"|\s+" + _LVL + r")*)")


def text_ranks(text):
    """All levels a forecast sentence mentions ("נמוך עד בינוני" -> [1, 2])."""
    t = " ".join(m.group(1) for m in LEVEL_SPAN_RE.finditer(_clean(text)))
    found = set()
    for m in re.finditer(r"גבוה\S*\s+מאוד", t):
        found.add(4)
    t2 = re.sub(r"גבוה\S*\s+מאוד", " ", t)
    if "גבוה" in t2:
        found.add(3)
    if "בינונ" in t2:
        found.add(2)
    if "נמוכ" in t2 or "נמוך" in t2:
        found.add(1)
    return sorted(found)


def _hex(rgb_text):
    m = RGB_RE.match(_clean(rgb_text))
    if not m:
        return None
    r, g, b = (min(255, int(v)) for v in m.groups())
    return f"#{r:02x}{g:02x}{b:02x}"


def _date(s):
    return pd.to_datetime(_clean(s), format="%d/%m/%Y", errors="coerce")


def _order(df):
    df = df.copy()
    df["_tid"] = pd.to_numeric(df["type_id"], errors="coerce")
    return df.sort_values(["_tid", "name", "title", "date"], na_position="last",
                          kind="mergesort").reset_index(drop=True)


# ── regions ──────────────────────────────────────────────────────────────
def build_regions(df):
    rows = df[df["type"].str.strip().str.lower() == "map"]
    out = []
    for _, r in rows.iterrows():
        title = _clean(r["title"]) or _clean(r["name"])
        if not title:
            continue
        label = _clean(r["air_quality"]) or "לא צוין"
        rank = level_rank(label)
        data_color = _hex(r["fill_color"])
        color = data_color or (LEVEL_COLOR[rank] if rank is not None else "#c3cfe7")
        link = _clean(r["file_link"])
        code = _clean(r["name"])
        centre = REGION_CENTRES.get(code)
        out.append({
            "code": code,
            "title": title,
            "label": label,
            "rank": rank,
            "color": color,
            "data_color": data_color,
            "link": link if GOV_LINK_RE.match(link) else "",
            "lat": centre[0] if centre else None,
            "lng": centre[1] if centre else None,
        })
    return out


def level_counts(regions):
    """Every known level (so a zero count is visible) plus any unknown label.

    Each bar takes the ministry's own fill colour for that level when a region
    carries one (regions are pre-sorted, so the pick is stable), else a fixed
    semantic colour.
    """
    counts = {}
    data_color = {}
    for r in regions:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
        key = r["rank"] if r["rank"] is not None else r["label"]
        if r.get("data_color"):
            data_color.setdefault(key, r["data_color"])
    labels = [name for _, name in LEVELS]
    known = set(labels)
    unknown = sorted(lab for lab in counts if lab not in known
                     and level_rank(lab) is None)
    # A label with a known rank but a variant spelling folds into its rank.
    folded = {name: 0 for name in labels}
    for lab, n in counts.items():
        rk = level_rank(lab)
        if lab in known:
            folded[lab] += n
        elif rk is not None:
            folded[LEVEL_NAME[rk]] += n
    rows = [{"label": name, "rank": rk, "n": folded[name],
             "color": data_color.get(rk, LEVEL_COLOR[rk])} for rk, name in LEVELS]
    rows += [{"label": lab, "rank": None, "n": counts[lab],
              "color": data_color.get(lab, "#c3cfe7")} for lab in unknown]
    return rows


# ── forecast & warning ──────────────────────────────────────────────────
def build_forecast(df):
    rows = df[(df["type"].str.strip().str.lower() == "content")
              & (df["name"].str.strip() != "Warning")]
    days = []
    for _, r in rows.iterrows():
        d = _date(r["date"])
        periods = []
        for head_col, text_col in PERIODS:
            text = _clean(r[text_col])
            if not text:
                continue
            ranks = text_ranks(text)
            periods.append({
                "head": _clean(r[head_col]) or head_col,
                "text": text,
                "min": ranks[0] if ranks else None,
                "max": ranks[-1] if ranks else None,
            })
        if not periods:
            continue
        days.append({
            "dow": _clean(r["day_of_week"]),
            "date": _clean(r["date"]),
            "ts": d,
            "periods": periods,
        })
    days.sort(key=lambda x: (pd.Timestamp.max if pd.isna(x["ts"]) else x["ts"], x["date"]))
    return days


def build_warning(df):
    rows = df[(df["type"].str.strip().str.lower() == "content")
              & (df["name"].str.strip() == "Warning")]
    for _, r in rows.iterrows():
        text = _clean(r["content"])
        if not text:
            continue
        return {
            "active": _clean(r["show"]).lower() == "true",
            "dow": _clean(r["day_of_week"]),
            "date": _clean(r["date"]),
            "ts": _date(r["date"]),
            "text": text,
        }
    return None


def pollutant_mentions(texts):
    out = []
    for stem, name in POLLUTANTS:
        n = sum(1 for t in texts if stem in t)
        if n:
            out.append((name, n))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


# ── insights ─────────────────────────────────────────────────────────────
def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " ו" + names[-1]


def insight_distribution(regions, counts):
    n = len(regions)
    if n == 0:
        return None
    present = [c for c in counts if c["n"] > 0]
    if len(present) == 1:
        return (f"בכל {_int(n)} אזורי התחזית צפויה רמת זיהום אוויר "
                f"{present[0]['label']}.")
    top = sorted(present, key=lambda c: (-c["n"], c["rank"] or 99, c["label"]))
    if len(top) > 1 and top[0]["n"] == top[1]["n"]:
        parts = [f"{c['label']} ({_int(c['n'])})" for c in top]
        return f"האזורים מתחלקים בין כמה רמות זיהום: {_join(parts)}."
    lead = top[0]
    rest = [f"{c['label']} ({_int(c['n'])})" for c in top[1:]]
    return (f"רמת הזיהום הנפוצה בתחזית היא {lead['label']}: {_int(lead['n'])} "
            f"מתוך {_int(n)} אזורים ({lead['n'] / n * 100:.0f}%). "
            f"בשאר האזורים: {_join(rest)}.")


def insight_elevated(regions):
    ranked = [r for r in regions if r["rank"] is not None]
    if not ranked:
        return None
    high = [r for r in ranked if r["rank"] >= 3]
    worst = max(r["rank"] for r in ranked)
    if high:
        high = sorted(high, key=lambda r: (-r["rank"], r["title"]))
        names = [f"{r['title']} ({r['label']})" for r in high]
        if len(high) == 1:
            return f"אזור אחד צפוי לזיהום ברמה גבוהה ומעלה: {names[0]}."
        return (f"{_int(len(high))} אזורים צפויים לזיהום ברמה גבוהה ומעלה: "
                f"{_join(names)}.")
    lowest = [r["title"] for r in ranked if r["rank"] == worst]
    if worst == 1:
        return (f"אף אחד מ-{_int(len(ranked))} האזורים אינו צפוי לזיהום מעל "
                f"רמה נמוכה.")
    if len(lowest) == len(ranked):
        tail = f"הרמה החמורה ביותר בתחזית היא {LEVEL_NAME[worst]}."
    else:
        where = ("באזור אחד" if len(lowest) == 1
                 else f"ב-{_int(len(lowest))} אזורים")
        tail = f"הרמה החמורה ביותר בתחזית היא {LEVEL_NAME[worst]}, {where}."
    return (f"אף אחד מ-{_int(len(ranked))} האזורים אינו צפוי לזיהום ברמה "
            f"גבוהה או גבוהה מאוד. {tail}")


def insight_north_south(regions):
    north = [r for r in regions if r["rank"] and r["lat"] and r["lat"] > NORTH_LAT]
    south = [r for r in regions if r["rank"] and r["lat"] and r["lat"] < SOUTH_LAT]
    if len(north) < 2 or len(south) < 2:
        return None
    mn = sum(r["rank"] for r in north) / len(north)
    ms = sum(r["rank"] for r in south) / len(south)
    if abs(mn - ms) < 0.5:
        return None
    worse, better = ("דרום", "צפון") if ms > mn else ("צפון", "דרום")
    wl = south if ms > mn else north
    bl = north if ms > mn else south
    return (f"הזיהום הצפוי חמור יותר ב{worse} ({_join(r['title'] for r in wl)}) "
            f"מאשר ב{better} ({_join(r['title'] for r in bl)}).")


def insight_forecast(days):
    pts = [(d, p) for d in days for p in d["periods"] if p["max"] is not None]
    if len(pts) < 2:
        return None
    lo = min(p["min"] for _, p in pts)
    hi = max(p["max"] for _, p in pts)
    first, last = days[0], days[-1]
    span = (f"{first['dow']} {first['date']}" if first is last
            else f"{first['dow']} {first['date']} עד {last['dow']} {last['date']}")
    if lo == hi:
        return (f"בכל {_int(len(pts))} פרקי הזמן בתחזית ({span}) צפוי זיהום "
                f"אוויר {LEVEL_NAME_M[hi]}.")
    peaks = [f"{d['dow']}, {p['head']}" for d, p in pts if p["max"] == hi]
    if len(peaks) == 1:
        peak_txt = f"השיא ({LEVEL_NAME_M[hi]}) צפוי ב{peaks[0]}"
    else:
        peak_txt = (f"זיהום {LEVEL_NAME_M[hi]} צפוי ב-{_int(len(peaks))} מתוך "
                    f"{_int(len(pts))} פרקי הזמן")
    return (f"לאורך התחזית ({span}) הזיהום צפוי לנוע בין {LEVEL_NAME_M[lo]} "
            f"ל{LEVEL_NAME_M[hi]}; {peak_txt}.")


def insight_cause(days):
    texts = [p["text"] for d in days for p in d["periods"]]
    if not texts:
        return None
    mentions = pollutant_mentions(texts)
    if not mentions:
        return None
    name, n = mentions[0]
    if len(mentions) > 1 and mentions[1][1] == n:
        return None
    return (f"הגורם המרכזי בתחזית הוא {name}: מוזכר ב-{_int(n)} מתוך "
            f"{_int(len(texts))} פרקי הזמן.")


def insight_warning(warning, days):
    if not warning:
        return None
    when = f"{warning['dow']} {warning['date']}".strip()
    when = ("ב-" if when[:1].isdigit() else "ב") + when
    if warning["active"]:
        return f"בתוקף התראת זיהום אוויר שפורסמה {when}; נוסחה המלא מופיע בעמוד."
    if days and not pd.isna(warning["ts"]) and not pd.isna(days[0]["ts"]):
        gap = (days[0]["ts"] - warning["ts"]).days
        if gap > 0:
            return (f"אין כעת התראת זיהום אוויר פעילה. ההתראה האחרונה שבקובץ "
                    f"פורסמה {when}, {_int(gap)} ימים לפני יום התחזית הראשון.")
    return f"אין כעת התראת זיהום אוויר פעילה. ההתראה האחרונה שבקובץ פורסמה {when}."


# ── main ─────────────────────────────────────────────────────────────────
def compute(frames):
    df = _order(frames["forecast"])
    regions = build_regions(df)
    regions.sort(key=lambda r: (-(r["rank"] or 0), r["title"], r["code"]))
    counts = level_counts(regions)
    days = build_forecast(df)
    warning = build_warning(df)

    n = len(regions)
    ranked = [r for r in regions if r["rank"] is not None]
    worst = max((r["rank"] for r in ranked), default=None)
    n_high = sum(1 for r in ranked if r["rank"] >= 3)
    n_worst = sum(1 for r in ranked if r["rank"] == worst) if worst else 0
    mapped = [r for r in regions if r["lat"] is not None]
    unmapped = n - len(mapped)

    kpis = {
        "regions": {"value": n, "display": _int(n), "tone": "brand"},
        "high": {"value": n_high, "display": _int(n_high),
                 "tone": "danger" if n_high else "ok"},
    }
    labels = {}
    if worst:
        kpis["worst"] = {
            "value": n_worst, "display": _int(n_worst),
            "tone": {1: "ok", 2: "warn", 3: "danger", 4: "danger"}[worst],
        }
        labels["worst_kpi"] = f"אזורים ברמה החמורה בתחזית ({LEVEL_NAME[worst]})"
    if days:
        kpis["date"] = {"value": days[0]["date"], "display": days[0]["date"],
                        "tone": "info"}
        labels["date_kpi"] = f"יום התחזית הראשון ({days[0]['dow']})"

    # charts ------------------------------------------------------------
    dist = {"labels": [c["label"] for c in counts], "counts": [c["n"] for c in counts],
            "colors": [c["color"] for c in counts]}
    top_c = max(counts, key=lambda c: (c["n"], -(c["rank"] or 99)))
    labels["dist_aria"] = (f"גרף עמודות: מספר אזורי התחזית לפי רמת זיהום. "
                           f"הנפוצה: {top_c['label']}, {_int(top_c['n'])} מתוך {_int(n)} אזורים.")
    labels["dist_lede"] = (f"מתוך {_int(n)} אזורי התחזית: "
                           + ", ".join(f"{c['label']}: {_int(c['n'])}" for c in counts)
                           + ".")

    region_chart = {
        "points": [[r["lat"], r["lng"], r["title"], r["label"], r["color"]]
                   for r in mapped],
    }
    labels["map_aria"] = (f"מפה אינטראקטיבית של {_int(len(mapped))} אזורי התחזית, "
                          f"צבועים לפי רמת הזיהום הצפויה. גרסה נגישה: טבלת האזורים בעמוד.")
    labels["map_note"] = ("" if not unmapped else
                          "אזור אחד ללא מיקום במפה מופיע ברשימה בלבד." if unmapped == 1 else
                          f"{_int(unmapped)} אזורים ללא מיקום במפה מופיעים ברשימה בלבד.")

    timeline = None
    if days:
        x, y, base, colors, texts = [], [], [], [], []
        for d in days:
            for p in d["periods"]:
                x.append(f"{d['dow']}\n{p['head']}")
                # Floating bar spanning the levels the sentence names:
                # [min - 0.5, max + 0.5] on an axis whose ticks 1..4 are levels.
                if p["max"] is None:
                    base.append(0)
                    y.append(0)
                else:
                    base.append(p["min"] - 0.5)
                    y.append(p["max"] - p["min"] + 1)
                colors.append(LEVEL_COLOR.get(p["max"], "#c3cfe7"))
                if p["min"] is None:
                    texts.append("לא צוינה רמה")
                elif p["min"] == p["max"]:
                    texts.append(LEVEL_NAME_M[p["max"]])
                else:
                    texts.append(f"{LEVEL_NAME_M[p['min']]} עד {LEVEL_NAME_M[p['max']]}")
        timeline = {"x": x, "base": base, "span": y, "colors": colors, "texts": texts,
                    "levels": [LEVEL_NAME_M[k] for k in sorted(LEVEL_NAME_M)]}
        peak = max((p["max"] or 0) for d in days for p in d["periods"])
        labels["timeline_aria"] = (
            f"גרף עמודות: רמת הזיהום הצפויה ב-{_int(len(x))} פרקי זמן. "
            f"הרמה הגבוהה ביותר: {LEVEL_NAME_M.get(peak, 'לא צוינה')}.")
        labels["timeline_lede"] = insight_forecast(days) or ""

    mentions = pollutant_mentions([p["text"] for d in days for p in d["periods"]])

    # insights ----------------------------------------------------------
    rules = [
        ("distribution", insight_distribution(regions, counts)),
        ("elevated", insight_elevated(regions)),
        ("north_south", insight_north_south(regions)),
        ("forecast", insight_forecast(days)),
        ("cause", insight_cause(days)),
        ("warning", insight_warning(warning, days)),
    ]
    insights = [{"id": k, "text_he": v} for k, v in rules if v]

    # summary -----------------------------------------------------------
    if len(days) == 2:
        head = f"תחזית זיהום אוויר להיום ולמחר לפי אזור, מ-{days[0]['date']}: "
    elif days:
        head = f"תחזית זיהום אוויר לפי אזור, מ-{days[0]['date']}: "
    else:
        head = "תחזית זיהום אוויר לפי אזור: "
    if worst and n_worst == n:
        body = f"בכל {_int(n)} האזורים רמת זיהום {LEVEL_NAME[worst]}."
    elif worst:
        body = (f"{_int(n_high)} מתוך {_int(n)} אזורים ברמה גבוהה ומעלה; "
                f"החמורה: {LEVEL_NAME[worst]}.")
    else:
        body = f"{_int(n)} אזורי תחזית."
    summary = head + body
    if warning and warning["active"]:
        summary += " בתוקף התראת זיהום."

    dates = [d["ts"] for d in days if not pd.isna(d["ts"])]
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "map",
        "suggested_tags": ["זיהום אוויר", "איכות אוויר", "תחזית", "אוזון", "סביבה"],
        "related_ids": [
            "780f8522-db2b-4147-b2ac-554aafaf1c1a",
            "6b991a56-c209-4b02-a52e-ba1c69091a4c",
            "5fc5c912-4fa5-4474-93c1-326e505e22cf",
            "04931a88-336c-4d95-8a13-9dc631c3e2d1",
        ],
        "spatial_coverage": "ישראל",
    }
    if dates:
        agent_data["temporal_coverage"] = (f"{min(dates):%Y-%m-%d}/{max(dates):%Y-%m-%d}")

    labels["regions_lede"] = (
        f"{_int(n)} אזורי התחזית של המשרד להגנת הסביבה, מהחמור לקל. "
        f"לכל אזור קישור לרשימת היישובים הכלולים בו." if any(r["link"] for r in regions)
        else f"{_int(n)} אזורי התחזית של המשרד להגנת הסביבה, מהחמור לקל.")

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "labels": labels,
        "charts": {
            "dist": dist,
            "map": region_chart if mapped else None,
            "timeline": timeline,
        },
        "regions": [{k: r[k] for k in ("title", "label", "color", "link")}
                    for r in regions],
        "days": [{"dow": d["dow"], "date": d["date"],
                  "periods": [{"head": p["head"], "text": p["text"]} for p in d["periods"]]}
                 for d in days],
        "pollutants": [{"name": nm, "n": c} for nm, c in mentions],
        "warning": ({k: warning[k] for k in ("active", "dow", "date", "text")}
                    if warning else None),
        "insights": insights,
    }
