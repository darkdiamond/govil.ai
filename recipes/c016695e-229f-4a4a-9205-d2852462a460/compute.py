"""רשימת תאגידי חוקרים פרטיים (Ministry of Justice): one row per licensed
private-investigation corporation, with only two columns: licence number and
corporation name.

There is no city, date or licence-type column, so the page is a lookup page
first (the explorer searches every record) with a few honest views:
licence-number series (the number without its last four digits, which groups
the two numbering formats in use), the service fields the corporations name
themselves after (keyword scan of the name), and how many names combine
investigations with another field.

No individual licence number is written to the page; series prefixes are
aggregates. Growth: new prefixes and names flow through; the theme list is a
fixed keyword mapping with a "no field keyword" bucket for everything else;
the series axis gets a dataZoom when it grows long.
"""
import re

import pandas as pd

SERIES_ZOOM_AT = 24
SUMMARY_MAX = 155

# (key, Hebrew label, regex on the corporation name). Order is the tie-break.
THEMES = [
    ("inv", "חקירות", r"חקיר|חוקר"),
    ("info", "מידע", r"מידע"),
    ("intel", "מודיעין", r"מודיעין"),
    ("sec", "ביטחון", r"בי?טחו"),
    ("consult", "ייעוץ", r"יי?עוץ"),
    ("track", "מעקבים", r"מעקב"),
]
MIX_LABELS = {
    "inv_only": "חקירות בלבד",
    "inv_plus": "חקירות ותחום נוסף",
    "other_only": "תחום אחר בלבד",
    "none": "ללא מילת תחום בשם",
}
MIX_ORDER = ["inv_only", "inv_plus", "other_only", "none"]


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _n(v):
    return f"{v:,}"


def _pct(part, whole):
    return f"{part / whole * 100:.1f}%" if whole else "0%"


def _corps(n):
    return "תאגיד אחד" if n == 1 else f"{_n(n)} תאגידים"


def _licences(n):
    return "רישיון אחד" if n == 1 else f"{_n(n)} רישיונות"


def compute(frames):
    df = frames["main"].copy()
    df["name"] = df["שם תאגיד"].map(_clean)
    df["lic"] = df["מספר רישיון"].map(lambda s: re.sub(r"\D", "", str(s)))
    df = df[(df["name"] != "") | (df["lic"] != "")].copy()
    total = len(df)

    # --- licence numbers ---
    lic = df.loc[df["lic"].str.len() >= 5, "lic"]
    n_unique_lic = int(lic.nunique())
    dup_lic = int(lic.duplicated().sum())
    n_bad = total - len(lic)
    lens = lic.str.len()
    len_rows = sorted(((int(k), int(v)) for k, v in lens.value_counts().items()),
                      key=lambda t: (-t[1], -t[0]))

    ser = pd.DataFrame({"key": lic.str[:-4], "len": lens})
    sc = ser.groupby(["len", "key"]).size().reset_index(name="n")
    sc["k"] = pd.to_numeric(sc["key"], errors="coerce").fillna(0)
    sc = sc.sort_values(["len", "k", "key"], ascending=[False, True, True], kind="mergesort")
    series_labels = [f"{k}…" for k in sc["key"]]
    series_vals = [int(v) for v in sc["n"]]
    series_lens = [int(v) for v in sc["len"]]
    big = sc.sort_values(["n", "len", "k"], ascending=[False, False, True], kind="mergesort").head(1)
    n_groups = len(sc)

    # --- name themes ---
    names = df["name"]
    hits = {k: names.str.contains(rx, regex=True) for k, _, rx in THEMES}
    theme_rows = []
    for i, (k, lab, _) in enumerate(THEMES):
        theme_rows.append((k, lab, int(hits[k].sum()), i))
    theme_rows = [r for r in theme_rows if r[2] > 0]
    theme_rows.sort(key=lambda r: (-r[2], r[3]))

    inv = hits["inv"]
    other_cols = [hits[k] for k, _, _ in THEMES if k != "inv"]
    other = pd.concat(other_cols, axis=1).any(axis=1) if other_cols else inv & False
    mix_counts = {
        "inv_only": int((inv & ~other).sum()),
        "inv_plus": int((inv & other).sum()),
        "other_only": int((~inv & other).sum()),
        "none": int((~inv & ~other).sum()),
    }
    n_inv = int(inv.sum())
    n_multi = mix_counts["inv_plus"]
    # which other field most often accompanies investigations
    partner = []
    for i, (k, lab, _) in enumerate(THEMES):
        if k == "inv":
            continue
        c = int((inv & hits[k]).sum())
        if c:
            partner.append((lab, c, i))
    partner.sort(key=lambda r: (-r[1], r[2]))

    # --- insights ---
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if total:
        t = ("ברשימה תאגיד חוקרים פרטיים אחד בעל רישיון" if total == 1
             else f"ברשימה {_n(total)} תאגידי חוקרים פרטיים בעלי רישיון")
        if dup_lic == 0 and n_bad == 0:
            t += ", ולכל אחד מספר רישיון ייחודי."
        else:
            t += f", עם {_n(n_unique_lic)} מספרי רישיון שונים."
        add("total", t)

    if theme_rows and theme_rows[0][2] >= 3 and total:
        lead = theme_rows[0]
        t = f"התחום \"{lead[1]}\" מופיע בשמם של {_corps(lead[2])} ({_pct(lead[2], total)} מהרשימה)"
        if len(theme_rows) >= 2:
            nx = theme_rows[1]
            t += f", ואחריו \"{nx[1]}\" ({_n(nx[2])})"
        add("themes", t + ".")

    if n_multi >= 2 and partner:
        p = partner[0]
        add("mix", f"{_corps(n_multi)} משלבים בשם חקירות עם תחום נוסף; השילוב הנפוץ הוא חקירות ו{p[0]} ({_n(p[1])}).")

    if mix_counts["none"] >= 1 and total:
        nn = mix_counts["none"]
        verb = "אינו מציין" if nn == 1 else "אינם מציינים"
        add("noinv", f"{_corps(nn)} ({_pct(nn, total)}) {verb} תחום פעילות בשמם, כך שאת התאגיד מאתרים לפי שמו המסחרי או מספר הרישיון.")

    if len(len_rows) >= 2:
        parts = [f"{_licences(v)} במספור בן {k} ספרות" for k, v in len_rows]
        add("formats", ("מספרי הרישיון מופיעים בשני פורמטים: " if len(len_rows) == 2
                        else "מספרי הרישיון מופיעים בכמה פורמטים: ") + ", ".join(parts)
            + ". בחיפוש לפי מספר רישיון יש להקליד את המספר המלא.")

    if len(big) and n_groups >= 3 and total:
        b = big.iloc[0]
        if int(b["n"]) / total >= 0.10:
            add("series", f"קבוצת המספור הגדולה היא רישיונות שמספרם מתחיל ב-{b['key']}: "
                f"{_licences(int(b['n']))}, {_pct(int(b['n']), total)} מהרשימה.")

    # --- KPIs ---
    inv_share = n_inv / total if total else 0
    kpis = {
        "total": {"value": total, "display": _n(total), "tone": "brand"},
        "investig": {"value": round(inv_share * 100, 1), "display": _pct(n_inv, total),
                     "tone": "info"},
        "multi": {"value": n_multi, "display": _n(n_multi), "tone": "brand"},
        "groups": {"value": n_groups, "display": _n(n_groups), "tone": "brand"},
    }
    kpi_order = ["total", "investig", "multi", "groups"]

    summary = (f"איתור תאגיד חוקרים פרטיים מורשה לפי שם התאגיד או מספר רישיון: "
               f"{_n(total)} משרדי חקירות בעלי רישיון ברשימת משרד המשפטים.")
    if len(summary) > SUMMARY_MAX:
        summary = f"איתור תאגיד חוקרים פרטיים לפי שם או מספר רישיון: {_n(total)} תאגידים."

    lede = (f"רשימת תאגידי החוקרים הפרטיים שמפרסם משרד המשפטים כוללת {_corps(total)} "
            "בעלי רישיון: חברות ומשרדי חקירות פרטיות. לכל רשומה שם התאגיד ומספר הרישיון, "
            "כך שאפשר לבדוק אם משרד חקירות מחזיק ברישיון לפני ששוכרים אותו. "
            "הרשימה אינה כוללת כתובת, יישוב או תאריכים.")

    labels = {
        "lede": lede,
        "kpi_total": "תאגידי חוקרים ברשימה",
        "kpi_investig": "שיעור השמות שמציינים חקירות",
        "kpi_multi": "שמות שמשלבים חקירות ותחום נוסף",
        "kpi_groups": "קבוצות מספור רישיון",
        "themes_note": (f"כמה תאגידים מציינים כל תחום בשמם, מתוך {_corps(total)}. "
                        "התחום מזוהה לפי מילים בשם (למשל חקירות, חוקרים או חקירת). שם אחד יכול לציין כמה תחומים, ולכן הסכום גדול ממספר התאגידים."),
        "themes_aria": f"מספר התאגידים שבשמם מופיע כל תחום, מתוך {_corps(total)}",
        "themes_cap": "תחומים בשמות התאגידים",
        "mix_note": (f"חלוקת {_corps(total)} לפי מה ששמם מציין: חקירות בלבד, חקירות ותחום נוסף "
                     "(מידע, מודיעין, ביטחון, ייעוץ או מעקבים), תחום אחר בלבד, או שם ללא מילת תחום."),
        "mix_aria": f"חלוקת {_corps(total)} לפי התחומים ששמם מציין",
        "mix_cap": "שילובי תחומים בשמות התאגידים",
        "series_note": ("כל עמודה מקבצת רישיונות לפי תחילת המספר (המספר בלי ארבע הספרות האחרונות)."
                        + ((" הרשימה משתמשת ב" + " ו".join(
                            f"מספור בן {k} ספרות" for k, _ in sorted(len_rows, key=lambda t: -t[0])) + ".")
                           if len(len_rows) >= 2 else "")
                        + (f" הקבוצה הגדולה: {big.iloc[0]['key']}… עם {_licences(int(big.iloc[0]['n']))}."
                           if len(big) else "")),
        "series_aria": f"מספר הרישיונות בכל אחת מ-{_n(n_groups)} קבוצות המספור",
        "series_cap": "רישיונות לפי תחילת מספר הרישיון",
    }

    mix_keys = [k for k in MIX_ORDER if mix_counts[k] > 0]
    charts = {
        "themes": {"names": [r[1] for r in theme_rows], "values": [r[2] for r in theme_rows],
                   "total": total},
        "mix": {"names": [MIX_LABELS[k] for k in mix_keys],
                "values": [mix_counts[k] for k in mix_keys]},
        "series": {"labels": [str(k) for k in sc["key"]], "values": series_vals,
                   "lens": series_lens, "zoom": len(series_labels) > SERIES_ZOOM_AT},
    }

    def tab(head, names_, vals):
        return {"head": head, "rows": [[nm, _n(v), _pct(v, total)] for nm, v in zip(names_, vals)]}

    tables = {
        "themes": tab(["תחום בשם", "תאגידים", "שיעור"], charts["themes"]["names"], charts["themes"]["values"]),
        "mix": tab(["שילוב", "תאגידים", "שיעור"], charts["mix"]["names"], charts["mix"]["values"]),
        "series": tab(["תחילת המספר", "רישיונות", "שיעור"], series_labels, series_vals),
    }
    flags = {
        "themes": len(theme_rows) >= 2,
        "mix": len(mix_keys) >= 2,
        "series": n_groups >= 2,
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["חוקרים פרטיים", "משרדי חקירות", "רישוי", "בדיקת רישיון", "משרד המשפטים"],
            "related_ids": [
                "c6b1c0b7-6d94-4191-acf1-b572eb6a6b79",
                "246d949c-a253-4811-8a11-41a137d3d613",
                "669b2652-f75b-4de3-8e6b-0dfa17accef5",
                "1806c96c-9cc4-47bf-98b3-80a18f061f98",
                "176f2727-476e-440e-bc8d-5d3461ea0e76",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": charts,
        "tables": tables,
        "flags": flags,
        "labels": labels,
        "insights": insights,
    }
