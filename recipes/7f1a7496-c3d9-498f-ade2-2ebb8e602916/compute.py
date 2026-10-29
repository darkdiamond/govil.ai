"""מטמנות אסבסט: the Ministry of Environmental Protection's short list of
licensed asbestos disposal sites (landfills and transfer stations), one row
per site: licence number, site name, responsible person, site type (which
asbestos it accepts), address, phone, fax, licence expiry, enforcement.

Searchers type "הטמנת אסבסט": they want to know where they may take asbestos
waste and which site accepts which kind (cement vs friable). The page is a
lookup list: a card per site plus an acceptance matrix. No chart: six rows
carry no distribution worth drawing.

Every sentence is computed from the rows; a rule whose premise doesn't hold
returns None. Site types are parsed by keyword (צמנט / פריך / מעבר); a type
that matches none is kept verbatim and counted as "other", never dropped.

Growth: the list is overwritten in place. New sites and new type wordings
flow through; the cards and matrix scale linearly (a registry of dozens of
sites still fits well under the 50KB script cap since no script carries rows).
"""
import re

import pandas as pd

SUMMARY_MAX = 155


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _date(d):
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def _types(raw):
    s = raw or ""
    return {
        "cement": "צמנט" in s,
        "friable": "פריך" in s,
        "transfer": "מעבר" in s,
    }


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " ו" + names[-1]


def _phones(raw):
    """Split a cell holding several numbers (space- or comma-separated)."""
    parts = re.split(r"[,;/]|\s+(?=0\d)", raw or "")
    return [p.strip() for p in parts if p.strip()]


def _prepare(df):
    out = pd.DataFrame({
        "lic": df["LicenseNumber"].map(_clean),
        "name": df["EnvironmentalSite"].map(_clean),
        "person": df["ResponsiblePerson"].map(_clean),
        "type": df["SiteType"].map(_clean),
        "address": df["Address"].map(_clean),
        "phone": df["PhoneNumber"].map(_clean),
        "fax": df["FaxNumber"].map(_clean),
        "expiry_raw": df["LicenseExpiryDate"].map(_clean),
        "disc": df["DisciplinaryMeasures"].map(_clean),
    })
    out = out[out["name"] != ""].copy()
    out["expiry"] = pd.to_datetime(out["expiry_raw"], format="%d.%m.%Y", errors="coerce")
    t = out["type"].map(_types)
    for k in ("cement", "friable", "transfer"):
        out[k] = t.map(lambda d, k=k: d[k])
    out["other"] = ~(out["cement"] | out["friable"] | out["transfer"])
    return out.sort_values(["name", "lic", "address", "type"], kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------- insights

def insight_friable(df):
    n = len(df)
    fr = df[df["friable"]]
    if fr.empty or len(fr) == n:
        return None
    rest = df[~df["friable"] & df["cement"]]
    head = ("רק אתר אחד" if len(fr) == 1 else f"רק {len(fr):,} אתרים") + f" מתוך {n:,}"
    verb = "קולט" if len(fr) == 1 else "קולטים"
    s = f"{head} ברשימה {verb} אסבסט פריך: {_join(fr['name'])}."
    if len(rest) == 1:
        s += " אתר אחד נוסף מורשה לאסבסט צמנט בלבד."
    elif len(rest) > 1:
        s += f" {len(rest):,} אתרים נוספים מורשים לאסבסט צמנט בלבד."
    return s


def insight_transfer(df):
    tr = df[df["transfer"]]
    if tr.empty or len(tr) == len(df):
        return None
    if len(tr) == 1:
        r = tr.iloc[0]
        return (f"{r['name']} ({r['address']}) רשום כתחנת מעבר ולא כמטמנה: "
                f"שם קולטים את הפסולת לפני העברתה להטמנה. "
                f"{len(df) - 1:,} האתרים האחרים הם אתרי הטמנה.")
    return (f"{len(tr):,} מהאתרים רשומים כתחנות מעבר ולא כמטמנות: {_join(tr['name'])}. "
            f"שם קולטים את הפסולת לפני העברתה להטמנה.")


def insight_expiry(df):
    ex = df[df["expiry"].notna()].sort_values(["expiry", "name"], kind="stable")
    if len(ex) < 2:
        return None
    first, last = ex.iloc[0], ex.iloc[-1]
    if first["expiry"] == last["expiry"]:
        return f"כל {len(ex):,} הרישיונות עם תאריך תוקף פוקעים באותו מועד, {_date(first['expiry'])}."
    s = (f"הרישיון הראשון ברשימה שתוקפו פוקע הוא של {first['name']}, ב-{_date(first['expiry'])}; "
         f"האחרון הוא של {last['name']}, בתוקף עד {_date(last['expiry'])}.")
    miss = len(df) - len(ex)
    if miss:
        s += f" ל-{miss:,} אתרים לא צוין תאריך תוקף."
    return s


def insight_enforcement(df):
    hit = df[df["disc"] != ""]
    n = len(df)
    if hit.empty:
        return f"לאף אחד מ-{n:,} האתרים לא רשומים אמצעי אכיפה במאגר."
    return (f"ל-{len(hit):,} מתוך {n:,} האתרים רשומים אמצעי אכיפה: "
            + "; ".join(f"{r['name']} ({r['disc']})" for _, r in hit.iterrows()) + ".")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["sites"])
    n = int(len(df))
    n_landfill = int((~df["transfer"]).sum())
    n_transfer = int(df["transfer"].sum())
    n_friable = int(df["friable"].sum())
    n_cement = int(df["cement"].sum())
    n_disc = int((df["disc"] != "").sum())

    rules = [
        ("friable", insight_friable(df)),
        ("transfer", insight_transfer(df)),
        ("expiry", insight_expiry(df)),
        ("enforcement", insight_enforcement(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    kpis, labels, order = {}, {}, []

    def add(key, value, display, label, tone="brand"):
        kpis[key] = {"value": value, "display": display, "tone": tone}
        labels[f"kpi_{key}"] = label
        order.append(key)

    add("sites", n, f"{n:,}", "אתרים מורשים לקליטת אסבסט")
    add("landfills", n_landfill, f"{n_landfill:,}",
        "מטמנות" + (f" (ועוד {n_transfer:,} תחנות מעבר)" if n_transfer > 1 else
                    " (ועוד תחנת מעבר אחת)" if n_transfer == 1 else ""))
    add("friable", n_friable, f"{n_friable:,}", "אתרים שקולטים אסבסט פריך",
        "warn" if 0 < n_friable * 3 <= n else "brand")
    add("cement", n_cement, f"{n_cement:,}", "אתרים שקולטים אסבסט צמנט")
    add("enforcement", n_disc, f"{n_disc:,}", "אתרים עם אמצעי אכיפה רשומים",
        "danger" if n_disc else "ok")

    sites = []
    for _, r in df.iterrows():
        accepts = []
        if r["cement"]:
            accepts.append("אסבסט צמנט")
        if r["friable"]:
            accepts.append("אסבסט פריך")
        if r["transfer"]:
            accepts.append("תחנת מעבר")
        sites.append({
            "name": r["name"],
            "kind": "תחנת מעבר" if r["transfer"] else "מטמנה",
            "accepts": accepts,
            "type_raw": r["type"] if r["other"] else "",
            "address": r["address"],
            "phones": _phones(r["phone"]),
            "fax": r["fax"],
            "person": r["person"],
            "lic": r["lic"],
            "expiry": _date(r["expiry"]) if pd.notna(r["expiry"]) else r["expiry_raw"],
            "disc": r["disc"],
        })

    matrix = [{
        "name": r["name"],
        "cement": bool(r["cement"]),
        "friable": bool(r["friable"]),
        "transfer": bool(r["transfer"]),
        "other": r["type"] if r["other"] else "",
    } for _, r in df.sort_values(
        ["friable", "transfer", "name", "lic"], ascending=[False, True, True, True],
        kind="stable").iterrows()]

    # summary_he: the meta description, the searcher's task first.
    parts = [f"איפה מטמינים אסבסט? {n:,} אתרים מורשים בישראל, עם כתובת, טלפון והסוג שכל אתר קולט."]
    if 0 < n_friable < n:
        parts.append(f"אסבסט פריך: {n_friable:,} אתרים בלבד.")
    summary = " ".join(parts)
    if len(summary) > SUMMARY_MAX:
        summary = parts[0]

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["אסבסט", "הטמנת אסבסט", "מטמנות", "פסולת מסוכנת",
                           "פינוי אסבסט", "איכות הסביבה"],
        "related_ids": [
            "005fe7c5-be59-42de-91ea-0ce3cdece35c",
            "33b03ff6-a58e-49bf-840e-a17a894c9885",
            "19c40947-95f1-4ea0-8a04-ad56526726af",
            "892135f3-cf6b-400a-8876-bfc80f3c9143",
        ],
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": order,
        "charts": {},
        "insights": insights,
        "tables": {"sites": sites, "matrix": matrix},
        "flags": {"has_matrix": n >= 2, "has_other": bool(df["other"].any())},
        "labels": {
            **labels,
            "sites_lede": (f"{n:,} האתרים שהמשרד להגנת הסביבה מפרסם, לפי שם. "
                           "לכל אתר: מה הוא קולט, כתובת, טלפון ותוקף הרישיון. "
                           "מומלץ לתאם הגעה בטלפון לפני הפינוי."),
            "matrix_lede": (f"אסבסט צמנט (לוחות, צנרת וגגות) מתקבל ב-{n_cement:,} אתרים, "
                            f"ואסבסט פריך ב-{n_friable:,} בלבד."),
            "matrix_caption": f"{n:,} האתרים לפי סוג האסבסט שהם מורשים לקלוט.",
        },
    }
