"""רשימת חוקרים פרטיים (Ministry of Justice): one row per licensed private
investigator with only three columns, surname, first name and licence number.

There is no city, licence type, agency or date column, so the page is a
lookup page first (the explorer searches every record) with honest, few
charts: licence-number series (the number with its last four digits
dropped, which groups the two numbering formats the registry uses), the most
common surnames and first names, plus lookup-relevant facts (duplicate full
names mean a licence number, not a name, identifies an investigator).

No individual's licence number is ever written to the page; series prefixes
are aggregates. Growth: new prefixes and names flow through; name charts are
top-N; the series axis gets a dataZoom when it grows long.
"""
import re

import pandas as pd

TOP_N = 12
SERIES_ZOOM_AT = 24
SUMMARY_MAX = 155


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _n(v):
    return f"{v:,}"


def _pct(part, whole):
    return f"{part / whole * 100:.1f}%" if whole else "0%"


def _people(n):
    return "חוקר אחד" if n == 1 else f"{_n(n)} חוקרים"


def _licences(n):
    return "רישיון אחד" if n == 1 else f"{_n(n)} רישיונות"


def _top(series, n):
    vc = series[series != ""].value_counts()
    df = pd.DataFrame({"name": vc.index, "n": vc.values})
    df = df.sort_values(["n", "name"], ascending=[False, True], kind="mergesort")
    return df.head(n).reset_index(drop=True), len(vc)


def compute(frames):
    df = frames["main"].copy()
    df["last"] = df["שם משפחה"].map(_clean)
    df["first"] = df["שם פרטי"].map(_clean)
    df["lic"] = df["מספר רישיון"].map(lambda s: re.sub(r"\D", "", str(s)))
    df = df[(df["last"] != "") | (df["first"] != "") | (df["lic"] != "")]
    total = len(df)

    lic = df.loc[df["lic"].str.len() >= 5, "lic"]
    n_unique_lic = int(lic.nunique())
    dup_lic = int(lic.duplicated().sum())
    n_bad = total - len(lic)
    lens = lic.str.len()
    by_len = lens.value_counts()
    len_rows = sorted(((int(k), int(v)) for k, v in by_len.items()), key=lambda t: (-t[1], -t[0]))

    # --- licence-number series: the number without its last four digits ---
    ser = pd.DataFrame({"key": lic.str[:-4], "len": lens})
    sc = ser.groupby(["len", "key"]).size().reset_index(name="n")
    sc["k"] = pd.to_numeric(sc["key"], errors="coerce").fillna(0)
    sc = sc.sort_values(["len", "k", "key"], ascending=[False, True, True], kind="mergesort")
    series_labels = [f"{k}…" for k in sc["key"]]
    series_vals = [int(v) for v in sc["n"]]
    series_lens = [int(v) for v in sc["len"]]
    big = sc.sort_values(["n", "k"], ascending=[False, True], kind="mergesort").head(1)

    # --- names ---
    top_last, n_last = _top(df["last"], TOP_N)
    top_first, n_first = _top(df["first"], TOP_N)
    full = (df["first"] + " " + df["last"]).str.strip()
    fvc = full[full != ""].value_counts()
    dup_names = int((fvc > 1).sum())
    dup_people = int(fvc[fvc > 1].sum())
    multi_first = int((df["first"].str.split(" ").str.len() > 1).sum())
    multi_last = int((df["last"].str.split(" ").str.len() > 1).sum())

    # --- insights ---
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if total:
        t = ("ברשימה חוקר פרטי אחד בעל רישיון" if total == 1
             else f"ברשימה {_n(total)} חוקרים פרטיים בעלי רישיון")
        if dup_lic == 0 and n_bad == 0:
            t += ", ולכל אחד מספר רישיון ייחודי."
        else:
            t += f", עם {_n(n_unique_lic)} מספרי רישיון שונים."
        add("total", t)

    if len(len_rows) >= 2:
        parts = [f"{_licences(v)} במספור בן {k} ספרות" for k, v in len_rows]
        add("formats", ("מספרי הרישיון מופיעים בשני פורמטים: " if len(len_rows) == 2 else "מספרי הרישיון מופיעים בכמה פורמטים: ") + ", ".join(parts)
            + ". בחיפוש לפי מספר רישיון יש להקליד את המספר המלא כפי שמופיע ברישיון.")

    if len(big):
        b = big.iloc[0]
        share = int(b["n"]) / total if total else 0
        if share >= 0.10 and len(sc) >= 3:
            add("series", f"קבוצת המספור הגדולה ביותר היא רישיונות שמספרם מתחיל ב-{b['key']}: "
                f"{_licences(int(b['n']))}, {_pct(int(b['n']), total)} מהרשימה.")

    if len(top_last) >= 2 and int(top_last.loc[0, "n"]) >= 3:
        a, b2 = top_last.loc[0], top_last.loc[1]
        both = int(a["n"]) + int(b2["n"])
        add("surnames", f"שמות המשפחה הנפוצים ביותר הם {a['name']} ({_n(int(a['n']))}) ו{b2['name']} "
            f"({_n(int(b2['n']))}), יחד {_pct(both, total)} מהחוקרים. ברשימה {_n(n_last)} שמות משפחה שונים.")

    if dup_names > 0:
        lead = "שם מלא אחד מופיע" if dup_names == 1 else f"{_n(dup_names)} שמות מלאים מופיעים"
        add("dups", f"{lead} אצל יותר מחוקר אחד ({_n(dup_people)} רשומות), "
            "ולכן כדאי לאמת חוקר לפי מספר הרישיון ולא לפי השם בלבד.")

    if len(top_first) >= 2 and int(top_first.loc[0, "n"]) >= 3:
        a, b2 = top_first.loc[0], top_first.loc[1]
        add("first", f"השם הפרטי הנפוץ ביותר הוא {a['name']} ({_n(int(a['n']))} חוקרים), ואחריו "
            f"{b2['name']} ({_n(int(b2['n']))}).")

    if total and multi_first / total >= 0.05:
        verb = "רשום" if multi_first == 1 else "רשומים"
        add("compound", f"{_people(multi_first)} ({_pct(multi_first, total)}) {verb} עם יותר משם פרטי אחד, "
            f"ו-{_n(multi_last)} עם שם משפחה כפול; בחיפוש כדאי להקליד חלק מהשם.")

    # --- KPIs ---
    kpis = {
        "total": {"value": total, "display": _n(total), "tone": "brand"},
        "surnames": {"value": n_last, "display": _n(n_last), "tone": "brand"},
    }
    kpi_order = ["total", "surnames"]
    labels = {
        "kpi_total": "חוקרים פרטיים ברשימה",
        "kpi_surnames": "שמות משפחה שונים",
    }
    for i, (k, v) in enumerate(len_rows[:2]):
        key = f"fmt{i}"
        kpis[key] = {"value": v, "display": _n(v), "tone": "info" if i else "brand"}
        kpi_order.append(key)
        labels[f"kpi_{key}"] = f"מספרי רישיון בני {k} ספרות"
    if len(kpi_order) < 4:
        kpis["first"] = {"value": n_first, "display": _n(n_first), "tone": "brand"}
        kpi_order.append("first")
        labels["kpi_first"] = "שמות פרטיים שונים"

    summary = (f"איתור חוקר פרטי מורשה לפי שם פרטי, שם משפחה או מספר רישיון: "
               f"{_n(total)} בעלי רישיון חוקר פרטי ברשימת משרד המשפטים.")
    if len(summary) > SUMMARY_MAX:
        summary = f"איתור חוקר פרטי מורשה לפי שם או מספר רישיון: {_n(total)} בעלי רישיון."

    lede = (f"רשימת בעלי רישיון חוקר פרטי שמפרסם משרד המשפטים כוללת {_people(total)}. "
            "לכל רשומה שם משפחה, שם פרטי ומספר רישיון, כך שאפשר לבדוק אם חוקר פרטי מחזיק ברישיון "
            "לפני שמתקשרים עם משרד חקירות. הרשימה אינה כוללת כתובת, יישוב, סוג רישיון או תאריכים.")

    fmt_note = ""
    if len(len_rows) >= 2:
        fmt_note = " הרשימה משתמשת ב" + " ו".join(
            f"מספור בן {k} ספרות" for k, _ in sorted(len_rows, key=lambda t: -t[0])) + "."
    labels.update({
        "lede": lede,
        "series_note": "כל עמודה מקבצת רישיונות לפי תחילת המספר (המספר בלי ארבע הספרות האחרונות)."
                       + fmt_note + (f" הקבוצה הגדולה: {big.iloc[0]['key']}… עם {_licences(int(big.iloc[0]['n']))}." if len(big) else ""),
        "series_aria": f"מספר הרישיונות בכל אחת מ-{_n(len(sc))} קבוצות המספור",
        "series_cap": "רישיונות לפי תחילת מספר הרישיון",
        "last_note": f"{TOP_N if len(top_last) >= TOP_N else len(top_last)} שמות המשפחה הנפוצים מתוך {_n(n_last)} שמות משפחה שונים ברשימה.",
        "last_aria": f"שמות המשפחה הנפוצים בקרב {_people(total)} בעלי רישיון",
        "last_cap": "שמות המשפחה הנפוצים",
        "first_note": f"{TOP_N if len(top_first) >= TOP_N else len(top_first)} השמות הפרטיים הנפוצים מתוך {_n(n_first)} שמות שונים.",
        "first_aria": "השמות הפרטיים הנפוצים בקרב בעלי רישיון חוקר פרטי",
        "first_cap": "השמות הפרטיים הנפוצים",
    })

    def tab(head, names, vals):
        return {"head": head, "rows": [[nm, _n(v), _pct(v, total)] for nm, v in zip(names, vals)]}

    charts = {
        "series": {"labels": [str(k) for k in sc["key"]], "values": series_vals, "lens": series_lens,
                   "zoom": len(series_labels) > SERIES_ZOOM_AT},
        "last": {"names": top_last["name"].tolist(), "values": [int(v) for v in top_last["n"]]},
        "first": {"names": top_first["name"].tolist(), "values": [int(v) for v in top_first["n"]]},
    }
    tables = {
        "series": tab(["תחילת המספר", "רישיונות", "שיעור"], series_labels, series_vals),
        "last": tab(["שם משפחה", "חוקרים", "שיעור"], charts["last"]["names"], charts["last"]["values"]),
        "first": tab(["שם פרטי", "חוקרים", "שיעור"], charts["first"]["names"], charts["first"]["values"]),
    }
    flags = {
        "series": len(sc) >= 2,
        "last": len(top_last) >= 3,
        "first": len(top_first) >= 3,
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["חוקרים פרטיים", "רישוי", "בדיקת רישיון", "משרד המשפטים"],
            "related_ids": [
                "634bf1ca-344e-4038-a139-9553bd0805a6",
                "c016695e-229f-4a4a-9205-d2852462a460",
                "713440a1-9963-4548-a7d9-9d9c9da54f62",
                "1806c96c-9cc4-47bf-98b3-80a18f061f98",
                "83372c35-23ce-4ddf-829f-1067b5ef3409",
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
