"""Elections managers contact list (Ministry of Interior): a lookup page.

Two kinds of contact share one table: an elections manager of one local
authority (City holds one name) and a manager of a special-polling-stations
area (City holds a comma-separated list of authorities, several managers per
area). Everything below is derived from the rows; nothing is fixed.
"""

import re

import pandas as pd
from govlib import fmt, frame

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
UNKNOWN = "לא צוין"


def _split_cities(s: str) -> list[str]:
    return sorted({frame.clean(p) for p in str(s).split(",") if frame.clean(p)})


def _is_area(role: str, cities: list[str]) -> bool:
    return "קלפיות" in role or "אזור" in role or len(cities) > 1


def _mail(s: str) -> dict:
    m = re.sub(r"\s+", "", str(s))
    return {"text": m, "ok": bool(EMAIL_RE.match(m))}


def _cnt(n: int, one: str, many: str) -> str:
    return one if n == 1 else f"{fmt.int_he(n)} {many}"


def _people(rows: list[dict]) -> list[dict]:
    return [{"name": r["name"], "mail": r["mail"]} for r in rows]


def compute(frames: dict[str, pd.DataFrame]) -> dict:
    df = frames["main"].copy()
    rows = []
    for name, district, role, city, mail in zip(
        frame.clean_series(df["Family"]),
        frame.clean_series(df["District"]),
        frame.clean_series(df["Role"]),
        df["City"],
        df["Mail"],
    ):
        if not name:
            continue
        cities = _split_cities(city)
        rows.append({
            "name": name,
            "district": district or UNKNOWN,
            "role": role or UNKNOWN,
            "cities": cities,
            "area": _is_area(role, cities),
            "mail": _mail(mail),
        })
    rows.sort(key=lambda r: (r["district"], r["name"], ",".join(r["cities"]), r["mail"]["text"], r["role"]))
    n = len(rows)
    if n == 0:
        raise ValueError("no named contacts")

    local = [r for r in rows if not r["area"]]
    area_rows = [r for r in rows if r["area"]]

    # District order: most contacts first, ties by name.
    dist_counts = frame.ranked(pd.Series([r["district"] for r in rows]))
    districts = [str(d) for d in dist_counts.index]

    # --- special-polling-station areas: group by district + authority list
    groups: dict[tuple, list[dict]] = {}
    for r in area_rows:
        groups.setdefault((r["district"], tuple(r["cities"])), []).append(r)
    area_keys = sorted(groups, key=lambda k: (districts.index(k[0]), -len(k[1]), k[1]))
    per_dist: dict[str, int] = {}
    for k in area_keys:
        per_dist[k[0]] = per_dist.get(k[0], 0) + 1
    seen: dict[str, int] = {}
    areas = []
    for k in area_keys:
        seen[k[0]] = seen.get(k[0], 0) + 1
        label = k[0] if per_dist[k[0]] == 1 else f"{k[0]} ({seen[k[0]]})"
        areas.append({
            "label": label,
            "district": k[0],
            "cities": list(k[1]),
            "n_cities": len(k[1]),
            "managers": _people(groups[k]),
            "roles": sorted({r["role"] for r in groups[k]}),
        })
    area_cities = sorted({c for a in areas for c in a["cities"]})

    # --- local managers directory
    local_sorted = sorted(local, key=lambda r: (districts.index(r["district"]), ",".join(r["cities"]), r["name"]))
    local_table = [{
        "city": ", ".join(r["cities"]) if r["cities"] else UNKNOWN,
        "district": r["district"],
        "name": r["name"],
        "role": r["role"],
        "mail": r["mail"],
    } for r in local_sorted]
    local_cities = sorted({c for r in local for c in r["cities"]})

    # --- A-Z authority index
    index = {}
    for r in local:
        for c in r["cities"]:
            index.setdefault(c, {"local": [], "area": [], "districts": set()})
            index[c]["local"].append(r["name"])
            index[c]["districts"].add(r["district"])
    for a in areas:
        for c in a["cities"]:
            index.setdefault(c, {"local": [], "area": [], "districts": set()})
            index[c]["area"].extend(m["name"] for m in a["managers"])
            index[c]["districts"].add(a["district"])
    az = [{
        "city": c,
        "district": fmt.join_he(sorted(v["districts"])),
        "local": fmt.join_he(sorted(v["local"])) if v["local"] else "–",
        "area": fmt.join_he(sorted(v["area"])) if v["area"] else "–",
    } for c, v in sorted(index.items())]
    both = sorted(c for c, v in index.items() if v["local"] and v["area"])

    # --- charts
    kind_local, kind_area = "מנהלי בחירות של רשות", "מנהלי אזור קלפיות מיוחדות"
    by_dist = {
        "names": districts,
        "series": [
            {"name": kind_local, "data": [sum(1 for r in local if r["district"] == d) for d in districts]},
            {"name": kind_area, "data": [sum(1 for r in area_rows if r["district"] == d) for d in districts]},
        ],
    }
    by_dist["series"] = [s for s in by_dist["series"] if sum(s["data"]) > 0]
    dist_table = [[d, fmt.int_he(sum(1 for r in local if r["district"] == d)),
                   fmt.int_he(sum(1 for r in area_rows if r["district"] == d)),
                   fmt.int_he(int(dist_counts[d]))] for d in districts]

    areas_chart = {"names": [a["label"] for a in areas], "values": [a["n_cities"] for a in areas],
                   "managers": [len(a["managers"]) for a in areas]}
    areas_table = [[a["label"], fmt.int_he(a["n_cities"]), fmt.int_he(len(a["managers"]))] for a in areas]

    # --- insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    parts = []
    if local:
        parts.append(_cnt(len(local), "מנהל בחירות אחד של רשות מקומית", "מנהלי בחירות של רשות מקומית אחת"))
    if area_rows:
        parts.append(_cnt(len(area_rows), "מנהל אזור קלפיות מיוחדות אחד", "מנהלי אזור קלפיות מיוחדות"))
    add("mix", f"הרשימה כוללת {fmt.int_he(n)} אנשי קשר ב-{fmt.int_he(len(districts))} מחוזות: {fmt.join_he(parts)}.")

    if local:
        lc = frame.ranked(pd.Series([r["district"] for r in local]))
        listed = fmt.join_he(f"{d} ({fmt.int_he(int(v))})" for d, v in lc.items())
        text = f"מנהלי הבחירות של רשות בודדת רשומים ב-{fmt.int_he(len(lc))} מחוזות: {listed}."
        if len(lc) == 1:
            text = f"כל {fmt.int_he(len(local))} מנהלי הבחירות של רשות בודדת רשומים במחוז {lc.index[0]}."
        elif lc.iloc[0] / len(local) > 0.5 and lc.iloc[0] > lc.iloc[1]:
            text += f" רובם ({fmt.pct(lc.iloc[0] / len(local))}) במחוז {lc.index[0]}."
        add("local_districts", text)

    only_area = [d for d in districts
                 if not any(r["district"] == d for r in local) and any(r["district"] == d for r in area_rows)]
    if local and only_area:
        word = "במחוז" if len(only_area) == 1 else "במחוזות"
        add("only_area", f"{word} {fmt.join_he(only_area)} רשומים רק מנהלי אזור קלפיות מיוחדות, "
                         "ולא מנהל בחירות של רשות מסוימת.")

    if areas:
        top = max(a["n_cities"] for a in areas)
        tops = [a for a in areas if a["n_cities"] == top]
        if len(areas) > 1 and len(tops) == 1:
            a = tops[0]
            k = len(a["managers"])
            who = "ורשום בו איש קשר אחד" if k == 1 else f"ורשומים בו {fmt.int_he(k)} אנשי קשר"
            add("biggest_area", f"אזור הקלפיות המיוחדות הגדול ביותר, במחוז {a['district']}, כולל {fmt.int_he(top)} רשויות "
                                f"{who}. בסך הכול {fmt.int_he(len(areas))} האזורים מכסים "
                                f"{fmt.int_he(len(area_cities))} רשויות.")
        else:
            add("biggest_area", f"{fmt.int_he(len(areas))} אזורי הקלפיות המיוחדות מכסים יחד "
                                f"{fmt.int_he(len(area_cities))} רשויות.")

    if both:
        shown = both[:4]
        more = f" ועוד {fmt.int_he(len(both) - len(shown))}" if len(both) > len(shown) else ""
        lead = ("רשות אחת מופיעה גם עם מנהל בחירות משלה" if len(both) == 1
                else f"{fmt.int_he(len(both))} רשויות מופיעות גם עם מנהל בחירות משלהן")
        add("overlap", f"{lead} וגם בתוך אזור קלפיות מיוחדות: "
                       f"{', '.join(shown)}{more}.")

    mails = [r["mail"]["text"].lower() for r in rows if r["mail"]["text"]]
    if mails:
        gov = sum(1 for m in mails if m.split("@")[-1].endswith("gov.il"))
        add("mail_domains", f"{fmt.int_he(gov)} מתוך {fmt.int_he(len(mails))} כתובות הדוא\"ל ברשימה הן בדומיין ממשלתי (gov.il), "
                            f"והשאר כתובות בדומיינים אחרים.")
        if gov == len(mails):
            insights[-1]["text_he"] = f"כל {fmt.int_he(len(mails))} כתובות הדוא\"ל ברשימה הן בדומיין ממשלתי (gov.il)."

    # --- KPIs
    kpis = {
        "total": {"value": n, "display": fmt.int_he(n), "tone": "brand"},
        "local": {"value": len(local_cities), "display": fmt.int_he(len(local_cities)), "tone": "brand"},
        "areas": {"value": len(areas), "display": fmt.int_he(len(areas)), "tone": "info"},
        "area_cities": {"value": len(area_cities), "display": fmt.int_he(len(area_cities)), "tone": "brand"},
        "districts": {"value": len(districts), "display": fmt.int_he(len(districts)), "tone": "brand"},
    }

    summary = (f"פרטי הקשר של {fmt.int_he(n)} מנהלי בחירות ברשויות המקומיות מטעם משרד הפנים, "
               f"ב-{fmt.int_he(len(districts))} מחוזות: {fmt.int_he(len(local))} מנהלי בחירות של רשות "
               f"{fmt.vav(fmt.int_he(len(area_rows)))} מנהלי אזור קלפיות מיוחדות, עם שם, רשות, מחוז ודוא\"ל.")
    description = (f"איתור מנהל הבחירות של רשות מקומית: שם, מחוז ודוא\"ל. {fmt.int_he(n)} אנשי קשר "
                   f"ב-{fmt.int_he(len(districts))} מחוזות, כולל {fmt.int_he(len(area_rows))} מנהלי אזור קלפיות מיוחדות.")

    lede = (f"משרד הפנים מפרסם את פרטי הקשר של מנהלי הבחירות לרשויות המקומיות. ברשימה {fmt.int_he(n)} אנשי קשר: "
            f"{fmt.int_he(len(local))} מנהלי בחירות של רשות מסוימת "
            f"{fmt.vav(fmt.int_he(len(area_rows)))} מנהלי אזור קלפיות מיוחדות.")

    labels = {
        "lede": lede,
        "total_kpi": "אנשי קשר ברשימה",
        "local_kpi": "רשויות עם מנהל בחירות משלהן",
        "areas_kpi": "אזורי קלפיות מיוחדות",
        "area_cities_kpi": "רשויות באזורי הקלפיות המיוחדות",
        "districts_kpi": "מחוזות",
        "dist_aria": f"אנשי קשר לפי מחוז וסוג תפקיד, {fmt.int_he(len(districts))} מחוזות",
        "dist_note": (f"מספר אנשי הקשר בכל מחוז. המחוז עם הכי הרבה אנשי קשר: {districts[0]} "
                      f"({fmt.int_he(int(dist_counts.iloc[0]))})."),
        "areas_aria": f"מספר הרשויות בכל אזור קלפיות מיוחדות, {fmt.int_he(len(areas))} אזורים",
        "areas_note": (f"כמה רשויות כלולות בכל אזור. {fmt.int_he(len(areas))} האזורים מכסים "
                       f"{fmt.int_he(len(area_cities))} רשויות שונות."),
        "local_note": (f"{fmt.int_he(len(local_table))} מנהלי בחירות, כל אחד לרשות אחת, "
                       "ממוינים לפי מחוז ושם הרשות."),
        "area_note": (f"{fmt.int_he(len(areas))} אזורים, ולכל אזור אנשי הקשר והרשויות שבתחומו."),
        "az_note": (f"{fmt.int_he(len(az))} רשויות לפי סדר האלף-בית, עם מנהל הבחירות של הרשות "
                    "ומנהלי אזור הקלפיות המיוחדות שהיא שייכת אליו."),
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": fmt.join_he(districts),
            "seo": {
                "title": "איתור מנהל הבחירות ברשות המקומית | פרטי קשר",
                "description": description,
                "name": "פרטי קשר עם מנהלי הבחירות ברשויות המקומיות",
                "alternate_names": [
                    "פרטי קשר עם מנהלי הבחירות",
                    "מנהלי בחירות ברשויות המקומיות",
                    "מנהל אזור קלפיות מיוחדות",
                    "מנהל הבחירות בבחירות לרשויות המקומיות",
                ],
            },
        },
        "kpis": kpis,
        "charts": {"by_dist": by_dist, "areas": areas_chart},
        "insights": insights,
        "labels": labels,
        "flags": {"local": bool(local_table), "areas": bool(areas), "areas_chart": len(areas) > 1},
        "tables": {
            "dist": dist_table,
            "areas": areas_table,
            "local": local_table,
            "area_dir": areas,
            "az": az,
        },
    }
