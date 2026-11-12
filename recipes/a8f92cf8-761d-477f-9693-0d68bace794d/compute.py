"""Producer-code registry for pre-packed food: validity, code length, premises type.

Every number comes from the frame; each insight rule returns a sentence or
None when its premise does not hold.
"""
import re

from govlib import fmt, frame

PREMISES = [
    # Industrial first: it wins when both words appear (e.g. a rural industrial park).
    # "כפר" is left out on purpose: it also starts town names (כפר סבא, כפר יונה).
    ("industrial", "אזור תעשייה", re.compile(r"א\.\s?ת|אזור\s+ה?תעשי|פארק")),
    ("rural", "קיבוץ או מושב", re.compile(r"קיבוץ|קבוץ|מושב")),
]
OTHER_LABEL = "רחוב או כתובת אחרת"


def _premises(addr):
    for _, label, rx in PREMISES:
        if rx.search(addr):
            return label
    return OTHER_LABEL


def _pct(n, total):
    return f"{n / total * 100:.1f}%"


def _prepare(df):
    df = df.copy()
    for c in ["producer_code", "factory_name", "company_number", "address", "is_code_valid"]:
        df[c] = frame.clean_series(df[c])
    df = df[df["producer_code"] != ""].copy()
    unknown = set(df["is_code_valid"]) - {"כן", "לא", ""}
    if unknown:
        raise ValueError(f"is_code_valid has unexpected values: {sorted(unknown)}")
    df["valid"] = df["is_code_valid"].eq("כן")
    df["code_len"] = df["producer_code"].str.replace(r"\s+", "", regex=True).str.len()
    df["premises"] = df["address"].map(_premises)
    df["is_ltd"] = df["factory_name"].str.contains(r'בע"מ|בע״מ|בע”מ', regex=True)
    df = df.sort_values(["producer_code", "factory_name", "company_number", "address"], kind="stable")
    return df.reset_index(drop=True)


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    if total == 0:
        raise ValueError("no rows")
    n_codes = int(df["producer_code"].str.upper().nunique())
    comp = df[df["company_number"] != ""]
    n_comp = int(comp["company_number"].nunique())
    per_comp = comp.groupby("company_number").size().sort_index()
    multi = per_comp[per_comp > 1]
    n_valid = int(df["valid"].sum())
    n_invalid = total - n_valid

    lens = df.groupby("code_len").size().sort_index()
    len_x = [f"{int(k)}" for k in lens.index]
    len_y = [int(v) for v in lens.values]
    top_len = int(lens.idxmax())
    top_len_n = int(lens[top_len])

    prem = df.groupby("premises").size().sort_index().sort_values(ascending=False, kind="stable")
    prem_names = list(prem.index)
    prem_vals = [int(v) for v in prem.values]

    n_ltd = int(df["is_ltd"].sum())

    insights = []
    # valid share
    if total >= 10:
        share = n_valid / total
        if share < 0.5:
            t = (f"רק {fmt.int_he(n_valid)} מתוך {fmt.int_he(total)} הקודים ({_pct(n_valid, total)}) מסומנים כתקפים, "
                 f"ולשאר {fmt.int_he(n_invalid)} הקודים מסומן שהם אינם תקפים.")
        elif share > 0.8:
            t = (f"{fmt.int_he(n_valid)} מתוך {fmt.int_he(total)} הקודים ({_pct(n_valid, total)}) מסומנים כתקפים.")
        else:
            t = (f"{fmt.int_he(n_valid)} קודים ({_pct(n_valid, total)}) מסומנים כתקפים, "
                 f"ו-{fmt.int_he(n_invalid)} אינם תקפים.")
        insights.append({"id": "valid", "text_he": t})
    # code length
    if len(lens) >= 2 and top_len_n / total >= 0.3:
        insights.append({"id": "length", "text_he": (
            f"הקוד הנפוץ הוא באורך {fmt.int_he(top_len)} תווים: {fmt.int_he(top_len_n)} קודים ({_pct(top_len_n, total)}) "
            f"ואילו הקוד הארוך ביותר מכיל {fmt.int_he(int(lens.index.max()))} תווים.")})
    # premises
    specific = [(n, v) for n, v in zip(prem_names, prem_vals) if n != OTHER_LABEL]
    if total >= 10 and specific and specific[0][1] / total >= 0.15:
        n0, v0 = specific[0]
        insights.append({"id": "premises", "text_he": (
            f"לפי מילות מפתח בכתובת, {fmt.int_he(v0)} יצרנים ({_pct(v0, total)}) "
            f"ממוקמים ב{n0}.")})
    # multiple codes per company
    if len(multi) > 0:
        extra = int(multi.sum())
        insights.append({"id": "multi", "text_he": (
            f"{fmt.int_he(len(multi))} חברות רשומות עם יותר מקוד אחד, ובסך הכול {fmt.int_he(extra)} קודים "
            f"מתוך {fmt.int_he(n_comp)} חברות שונות עם מספר חברה.")})
    # legal form
    if total >= 10 and n_ltd / total >= 0.5:
        insights.append({"id": "ltd", "text_he": (
            f"בשמות {fmt.int_he(n_ltd)} מתוך {fmt.int_he(total)} היצרנים ({_pct(n_ltd, total)}) מופיע \"בע\"מ\".")})

    ad = {
        "summary_he": (f"רשימת {fmt.int_he(total)} יצרנים שקיבלו אישור לסמן מזון ארוז מראש בקוד יצרן במקום שם היצרן, "
                       f"{fmt.int_he(n_valid)} מהם עם קוד תקף כעת."),
        "dataset_kind": "registry",
        "seo": {
            "title": "קוד יצרן על מזון ארוז: איתור יצרן לפי קוד | משרד הכלכלה",
            "description": (f"איתור יצרן מזון ארוז לפי קוד יצרן, שם או מספר חברה. "
                            f"{fmt.int_he(total)} יצרנים רשומים, {fmt.int_he(n_valid)} עם קוד תקף."),
            "name": "רשימת יצרנים מאושרים לסימון מזון בקוד יצרן",
            "alternate_names": [
                "קוד יצרן על אריזת מזון",
                "סימון מזון ארוז מראש בקוד יצרן",
                "מי היצרן לפי הקוד שעל האריזה",
            ],
        },
    }
    kpis = {
        "total": {"value": total, "display": fmt.int_he(total), "tone": "brand"},
        "companies": {"value": n_comp, "display": fmt.int_he(n_comp), "tone": "brand"},
        "valid": {"value": n_valid, "display": fmt.int_he(n_valid), "tone": "ok" if n_valid else "warn"},
        "codes": {"value": n_codes, "display": fmt.int_he(n_codes), "tone": "info"},
    }
    return {
        "agent_data": ad,
        "kpis": kpis,
        "charts": {
            "valid": {"names": ["קוד תקף", "קוד שאינו תקף"], "values": [n_valid, n_invalid]},
            "length": {"x": len_x, "y": len_y},
            "premises": {"names": prem_names, "values": prem_vals},
        },
        "insights": insights,
        "tables": {
            "valid": [["קוד תקף", fmt.int_he(n_valid)], ["קוד שאינו תקף", fmt.int_he(n_invalid)]],
            "length": [[x, fmt.int_he(y)] for x, y in zip(len_x, len_y)],
            "premises": [[n, fmt.int_he(v)] for n, v in zip(prem_names, prem_vals)],
        },
        "labels": {
            "valid_aria": "התפלגות הקודים לפי תקפות",
            "length_aria": "מספר הקודים לפי אורך הקוד בתווים",
            "premises_aria": "מספר היצרנים לפי סוג הכתובת",
        },
    }
