"""מעבדות אסבסט: the Ministry of Environmental Protection's list of labs
licensed to sample and/or analyse asbestos.

One row per licence (8 at authoring time): licence number, lab (company)
name, the licensed samplers/analysts (comma-separated names), licence type
(דיגום / אנליזה / אנליזה לדגימות אוויר בלבד), business address, phone, fax,
email, licence expiry and a free-text disciplinary history. One lab can hold
several licences (a sampling licence and an analysis licence). The whole list
is republished on each update and holds only licences in force, so the page
is a snapshot; there is no "today" in it, so time views are by expiry date.

Labs are businesses and are named. Staff are counted, never listed on the
page (the explorer below the page holds every row). Disciplinary records are
aggregated by kind and year; nobody is named.
"""
import re

import pandas as pd

TOP_LICENCES = 20
LRI, PDI = "⁦", "⁩"
KIND_SUSP, KIND_REPRIMAND, KIND_OTHER = "התליה", "נזיפה", "אחר"
DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
GROUP_SAMPLING, GROUP_ANALYSIS = "דיגום", "אנליזה"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def norm(s):
    return re.sub(r"\s+", " ", str(s).strip())


def _ranked(s):
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _group(t):
    """Broad family of a licence type: sampling vs analysis (any variant)."""
    if t.startswith(GROUP_ANALYSIS):
        return GROUP_ANALYSIS
    if t.startswith(GROUP_SAMPLING):
        return GROUP_SAMPLING
    return t


def _staff(s):
    return [x for x in (norm(p) for p in re.split(r"[,،;\n]", str(s))) if x]


def _events(text):
    out = []
    for line in re.split(r"[\n\r]+", str(text)):
        line = norm(line).rstrip(".")
        if not line:
            continue
        if KIND_SUSP in line or "התלי" in line:
            kind = KIND_SUSP
        elif "נזיפ" in line:
            kind = KIND_REPRIMAND
        else:
            kind = KIND_OTHER
        m = DATE_RE.search(line)
        year = int(m.group(3)) if m else None
        out.append({"kind": kind, "year": year, "text": line})
    return out


def _list_he(items):
    items = list(items)
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " ו" + items[-1]


def cnt(v, one, many):
    """Hebrew count phrase: 'רישיון אחד' for 1, else '<n> <plural>'."""
    return one if int(v) == 1 else f"{n(v)} {many}"


def _fmt_date(d):
    return d.strftime("%d/%m/%Y")


# ---------------------------------------------------------------- insights

def insight_types(type_counts, total, group_counts):
    if type_counts.empty or total == 0:
        return None
    s_n = int(group_counts.get(GROUP_SAMPLING, 0))
    a_n = int(group_counts.get(GROUP_ANALYSIS, 0))
    if s_n and a_n:
        a_txt = cnt(a_n, "רישיון אנליזה אחד", "רישיונות אנליזה")
        s = (f"ברשימה {n(total)} רישיונות: {cnt(s_n, 'רישיון דיגום אחד', 'רישיונות דיגום')} "
             f"(איסוף דגימות בשטח) ו{'' if a_n == 1 else '-'}{a_txt} (בדיקת הדגימות במעבדה)")
        narrow = int(sum(v for t, v in type_counts.items() if _group(t) == GROUP_ANALYSIS and t != GROUP_ANALYSIS))
        if narrow:
            s += ("; אחד מרישיונות האנליזה מוגבל לדגימות אוויר בלבד" if narrow == 1 and a_n > 1 else
                  "; רישיון האנליזה מוגבל לדגימות אוויר בלבד" if narrow == a_n == 1 else
                  f"; {n(narrow)} מרישיונות האנליזה מוגבלים לדגימות אוויר בלבד")
        return s + "."
    lead, lv = type_counts.index[0], int(type_counts.iloc[0])
    if len(type_counts) > 1 and int(type_counts.iloc[1]) == lv:
        return None
    return f"סוג הרישיון הנפוץ ברשימה הוא {lead}: {n(lv)} מתוך {n(total)} רישיונות."


def insight_both(lab_groups, n_labs):
    if n_labs < 2:
        return None
    both = sorted(l for l, g in lab_groups.items() if GROUP_SAMPLING in g and GROUP_ANALYSIS in g)
    if not both:
        return None
    if len(both) == n_labs:
        return f"כל {n(n_labs)} המעבדות ברשימה מחזיקות גם רישיון דיגום וגם רישיון אנליזה."
    s = (f"{n(len(both))} מתוך {n(n_labs)} המעבדות מחזיקות גם רישיון דיגום וגם רישיון אנליזה, "
         f"כך שהן יכולות לבצע את התהליך כולו מהשטח ועד תוצאת הבדיקה")
    if len(both) <= 4:
        s += f": {_list_he(both)}"
    return s + "."


def insight_staff(staff_per, total_staff, distinct_staff):
    if staff_per.empty or total_staff == 0:
        return None
    top_lab, top_type, top_v = staff_per.iloc[0][["lab", "type", "staff"]]
    singles = int((staff_per["staff"] == 1).sum())
    s = f"ברישיונות רשומים {n(distinct_staff)} דוגמים ואנליטיקאים מורשים"
    if len(staff_per) == 1 or int(staff_per.iloc[1]["staff"]) < int(top_v):
        s += (f"; הצוות הגדול ביותר הוא ברישיון ה{top_type} של {top_lab} עם "
              f"{'אדם אחד' if int(top_v) == 1 else f'{n(top_v)} אנשים'}")
    if singles:
        s += (f", ואילו {n(singles)} רישיונות נשענים על אדם מורשה אחד בלבד"
              if singles > 1 else ", ואילו רישיון אחד נשען על אדם מורשה אחד בלבד")
    return s + "."


def insight_expiry(lic):
    exp = lic.dropna(subset=["exp"])
    if len(exp) < 2:
        return None
    first = exp.iloc[0]
    last = exp.iloc[-1]
    fy = int(first["exp"].year)
    same_year = int((exp["exp"].dt.year == fy).sum())
    s = (f"תאריך התוקף הרשום המוקדם ביותר הוא של רישיון ה{first['type']} של {first['lab']}: "
         f"{_fmt_date(first['exp'])}")
    if same_year > 1:
        s += f" ({n(same_year)} רישיונות שתוקפם הרשום מסתיים בשנת {fy})"
    s += f"; תאריך התוקף הרשום המאוחר ביותר הוא {_fmt_date(last['exp'])}."
    return s


def insight_disc(n_disc, total, kind_counts, ev_years, n_disc_labs, n_undated=0):
    if total == 0:
        return None
    if n_disc == 0:
        return f"לאף אחד מ-{n(total)} הרישיונות ברשימה לא רשום היבט משמעתי."
    parts = [f"{n(v)} {'התליות' if k == KIND_SUSP else 'נזיפות' if k == KIND_REPRIMAND else 'רישומים אחרים'}"
             if v > 1 else f"{'התליה אחת' if k == KIND_SUSP else 'נזיפה אחת' if k == KIND_REPRIMAND else 'רישום אחר'}"
             for k, v in kind_counts.items() if v]
    who = "לרישיון אחד" if n_disc == 1 else f"ל-{n(n_disc)}"
    labs_txt = "של מעבדה אחת" if n_disc_labs == 1 else f"של {n(n_disc_labs)} מעבדות"
    s = (f"{who} מתוך {n(total)} הרישיונות ({pct(n_disc / total * 100)}), "
         f"{labs_txt}, רשום היבט משמעתי: {_list_he(parts)}")
    if len(ev_years):
        y0, y1 = int(min(ev_years)), int(max(ev_years))
        dated = "" if not n_undated else " (האירועים שתאריכם מצוין)"
        if y0 == y1:
            s += f", {'כולם' if not n_undated else 'כל האירועים שתאריכם מצוין'} משנת {y0}"
        else:
            s += f", בין השנים {y0} ל-{y1}{dated}"
        if n_undated:
            s += f"; ל{'אירוע אחד' if n_undated == 1 else f'-{n(n_undated)} אירועים'} לא מצוין תאריך"
    return s + "."


def insight_validity(lic):
    exp = lic.dropna(subset=["exp"])
    if len(exp) < 3:
        return None
    by_group = {}
    for g, sub in exp.groupby("group", sort=True):
        by_group[g] = sub["exp"].max()
    if GROUP_SAMPLING not in by_group or GROUP_ANALYSIS not in by_group:
        return None
    s_last, a_last = by_group[GROUP_SAMPLING], by_group[GROUP_ANALYSIS]
    if s_last.year == a_last.year:
        return None
    later, earlier = (("אנליזה", "דיגום") if a_last > s_last else ("דיגום", "אנליזה"))
    lv, ev = (a_last, s_last) if a_last > s_last else (s_last, a_last)
    return (f"רישיון ה{later} האחרון לפקיעה ברשימה תקף עד {lv.year}, בעוד שרישיון ה{earlier} "
            f"האחרון לפקיעה תקף רק עד {ev.year}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = frames["main"].copy()
    for c in ["LicenseNumber", "LabName", "SampleOrLabWorker", "LabType",
              "LicenseExpiration", "DisciplinaryMeasures"]:
        df[c] = df[c].map(norm) if c != "DisciplinaryMeasures" else df[c].astype(str)
    df = df[(df["LabName"] != "") | (df["LicenseNumber"] != "")].copy()
    df["LabName"] = df["LabName"].where(df["LabName"] != "", "לא צוין")
    df["LabType"] = df["LabType"].where(df["LabType"] != "", "לא צוין")
    df["exp"] = pd.to_datetime(df["LicenseExpiration"].str.slice(0, 10), errors="coerce", format="%Y-%m-%d")
    alt = pd.to_datetime(df["LicenseExpiration"], errors="coerce", format="%d/%m/%Y")
    df["exp"] = df["exp"].fillna(alt)
    df["staff_list"] = df["SampleOrLabWorker"].map(_staff)
    df["staff"] = df["staff_list"].map(len)
    df["group"] = df["LabType"].map(_group)
    df["events"] = df["DisciplinaryMeasures"].map(_events)
    df["has_disc"] = df["events"].map(bool)
    df = df.sort_values(["exp", "LabName", "LabType", "LicenseNumber"], kind="stable",
                        na_position="last").reset_index(drop=True)

    total = len(df)
    labs = sorted(df["LabName"].unique())
    n_labs = len(labs)
    type_counts = _ranked(df["LabType"].value_counts())
    types = list(type_counts.index)
    group_counts = df["group"].value_counts()
    distinct_staff = len({p for lst in df["staff_list"] for p in lst})
    total_staff = int(df["staff"].sum())

    # labs x types
    lt = df.groupby(["LabName", "LabType"]).size()
    lab_tot = _ranked(df["LabName"].value_counts())
    lab_order = list(lab_tot.index)
    lab_groups = {l: set(df.loc[df["LabName"] == l, "group"]) for l in labs}
    lab_staff = {l: len({p for lst in df.loc[df["LabName"] == l, "staff_list"] for p in lst}) for l in labs}

    # staff per licence
    lic = pd.DataFrame({"lab": df["LabName"], "type": df["LabType"], "staff": df["staff"],
                        "num": df["LicenseNumber"], "exp": df["exp"], "group": df["group"],
                        "disc": df["has_disc"]})
    staff_per = lic.sort_values(["staff", "lab", "type", "num"], ascending=[False, True, True, True],
                                kind="stable").reset_index(drop=True)
    staff_top = staff_per.head(TOP_LICENCES)

    # expiry by year x type
    exp_ok = df.dropna(subset=["exp"])
    years = sorted(int(y) for y in exp_ok["exp"].dt.year.unique())
    yt = exp_ok.groupby([exp_ok["exp"].dt.year, "LabType"]).size()
    n_no_exp = int(df["exp"].isna().sum())

    # disciplinary events (dedup per lab + text: a lab's two licences may repeat them)
    ev_rows = []
    seen = set()
    for lab, evs in zip(df["LabName"], df["events"]):
        for e in evs:
            key = (lab, e["text"])
            if key in seen:
                continue
            seen.add(key)
            ev_rows.append({"lab": lab, **e})
    ev = pd.DataFrame(ev_rows, columns=["lab", "kind", "year", "text"])
    kind_order = [k for k in (KIND_SUSP, KIND_REPRIMAND, KIND_OTHER) if (ev["kind"] == k).any()]
    kind_counts = {k: int((ev["kind"] == k).sum()) for k in kind_order}
    ev_years_s = pd.to_numeric(ev["year"], errors="coerce").dropna().astype(int)
    ev_years = sorted(ev_years_s.unique().tolist())
    evd = ev.dropna(subset=["year"]).copy()
    evd["year"] = evd["year"].astype(int)
    ky = evd.groupby(["year", "kind"]).size() if len(evd) else {}
    n_undated = int(ev["year"].isna().sum())
    n_disc = int(df["has_disc"].sum())
    n_disc_labs = int(df.loc[df["has_disc"], "LabName"].nunique())

    # ---------------------------------------------------------------- insights
    insights = []
    for iid, txt in [
        ("types", insight_types(type_counts, total, group_counts)),
        ("both", insight_both(lab_groups, n_labs)),
        ("staff", insight_staff(staff_per, total_staff, distinct_staff)),
        ("expiry", insight_expiry(lic)),
        ("validity", insight_validity(lic)),
        ("disc", insight_disc(n_disc, total, kind_counts, ev_years, n_disc_labs,
                              int(pd.to_numeric(ev["year"], errors="coerce").isna().sum()))),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    # ---------------------------------------------------------------- kpis
    first_exp = exp_ok["exp"].min() if len(exp_ok) else None
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "labs": {"value": n_labs, "display": n(n_labs), "tone": "brand"},
        "staff": {"value": distinct_staff, "display": n(distinct_staff), "tone": "info"},
        "disc": {"value": n_disc, "display": n(n_disc), "tone": "warn" if n_disc else "ok"},
    }

    # ---------------------------------------------------------------- charts
    charts = {
        "types": {"x": types, "y": [int(type_counts[t]) for t in types]},
        "labs": {"labs": lab_order, "series": [
            {"name": t, "data": [int(lt.get((l, t), 0)) for l in lab_order]} for t in types]},
        "staff": {"labels": [f"{r.lab} · {r.type}" for r in staff_top.itertuples()],
                  "y": [int(v) for v in staff_top["staff"]]},
        "expiry": {"years": [str(y) for y in years], "series": [
            {"name": t, "data": [int(yt.get((y, t), 0)) for y in years]} for t in types]},
        "disc": {"years": [str(y) for y in ev_years], "series": [
            {"name": k, "data": [int(ky.get((y, k), 0)) for y in ev_years]} for k in kind_order]},
    }

    staff_max = int(staff_per["staff"].max()) if total else 0
    staff_med = float(staff_per["staff"].median()) if total else 0.0
    exp_first_txt = _fmt_date(first_exp) if first_exp is not None else ""
    labels = {
        "lede": (f"רשימת המעבדות שקיבלו מהמשרד להגנת הסביבה רישיון לדיגום אסבסט או לאנליזה של דגימות אסבסט: "
                 f"{n(total)} רישיונות של {n(n_labs)} מעבדות, עם שמות הדוגמים והאנליטיקאים המורשים, "
                 f"מועד פקיעת כל רישיון והיבטים משמעתיים. בדיקת מעבדה מורשית נדרשת למשל לפני פירוק "
                 f"גג או לוחות אסבסט ולאחריו, לאישור שהאוויר באתר נקי מסיבים."),
        "total_kpi": "רישיונות מעבדה ברשימה",
        "labs_kpi": "מעבדות מורשות",
        "staff_kpi": "דוגמים ואנליטיקאים מורשים",
        "disc_kpi": "רישיונות עם היבט משמעתי",
        "types_note": (f"כמה רישיונות מכל סוג: דיגום הוא איסוף הדגימות בשטח, ואנליזה היא בדיקתן במעבדה. "
                       f"{n(len(types))} סוגי רישיון ברשימה."),
        "types_aria": (f"תרשים עמודות: רישיונות לפי סוג; {types[0]} בראש עם {n(type_counts.iloc[0])}."
                       if types else "תרשים עמודות: רישיונות לפי סוג."),
        "types_caption": "רישיונות לפי סוג רישיון.",
        "labs_note": (f"אילו רישיונות מחזיקה כל אחת מ-{n(n_labs)} המעבדות. מעבדה עם רישיון דיגום ורישיון "
                      f"אנליזה יכולה לטפל בבדיקה מתחילתה ועד סופה."),
        "labs_aria": f"תרשים עמודות מוערם: {n(n_labs)} מעבדות לפי סוגי הרישיונות שבידיהן.",
        "labs_caption": "מעבדות לפי סוג רישיון ומספר אנשי צוות מורשים.",
        "staff_note": (f"מספר האנשים המורשים הרשומים בכל רישיון (חציון {staff_med:g}, מקסימום {n(staff_max)})."
                       + (f" מוצגים {n(TOP_LICENCES)} הרישיונות עם הצוות הגדול ביותר." if total > TOP_LICENCES else "")),
        "staff_aria": (f"תרשים עמודות אופקי: אנשי צוות מורשים לכל רישיון; הגדול ביותר {n(staff_max)}."),
        "staff_caption": "מספר אנשי הצוות המורשים בכל רישיון.",
        "expiry_note": (f"בכל שנה, כמה רישיונות מגיעים לסוף תוקפם. תאריך התוקף הרשום המוקדם ביותר: {exp_first_txt}."
                        + (f" ל-{n(n_no_exp)} רישיונות לא צוין תאריך תוקף והם אינם בתרשים." if n_no_exp else "")),
        "expiry_aria": (f"תרשים עמודות מוערם: פקיעת רישיונות לפי שנה, {years[0]} עד {years[-1]}."
                        if years else "תרשים עמודות: פקיעת רישיונות לפי שנה."),
        "expiry_caption": "רישיונות לפי שנת פקיעת התוקף וסוג רישיון.",
        "disc_note": (f"אירועים משמעתיים (התליה, נזיפה) הרשומים ברישיונות, לפי השנה שבה ניתנו. "
                      f"אירוע שחוזר בשני רישיונות של אותה מעבדה נספר פעם אחת. שמות אינם מוצגים."
                      + (f" {n(n_undated)} אירועים ללא תאריך אינם בתרשים." if n_undated else "")),
        "disc_aria": (f"תרשים עמודות: {n(len(ev))} אירועים משמעתיים לפי שנה וסוג."),
        "disc_caption": "אירועים משמעתיים לפי שנה וסוג.",
        "list_note": "כל הרישיונות ברשימה, לפי מועד פקיעת התוקף. פרטי הקשר המלאים ושמות הצוות נמצאים בטבלת הנתונים שלמטה.",
        "list_caption": "רישיונות מעבדות אסבסט.",
        "list_more": (f"מוצגים {n(TOP_LICENCES)} מתוך {n(total)} רישיונות; השאר בטבלת הנתונים שלמטה."
                      if total > TOP_LICENCES * 2 else ""),
    }

    list_rows = lic if total <= TOP_LICENCES * 2 else lic.head(TOP_LICENCES)
    tables = {
        "types": [{"type": t, "count": n(type_counts[t]), "share": f"{type_counts[t] / total * 100:.0f}%"}
                  for t in types],
        "type_cols": types,
        "labs": [{"name": l, "vals": [n(lt.get((l, t), 0)) for t in types], "staff": n(lab_staff[l])}
                 for l in lab_order],
        "staff": [{"lab": r.lab, "type": r.type, "staff": n(r.staff)} for r in staff_top.itertuples()],
        "expiry": [{"year": str(y), "vals": [n(yt.get((y, t), 0)) for t in types],
                    "total": n(sum(int(yt.get((y, t), 0)) for t in types))} for y in years],
        "kind_cols": kind_order,
        "disc": [{"year": str(y), "vals": [n(ky.get((y, k), 0)) for k in kind_order],
                  "total": n(sum(int(ky.get((y, k), 0)) for k in kind_order))} for y in ev_years],
        "list": [{"num": r.num, "lab": r.lab, "type": r.type,
                  "exp": _fmt_date(r.exp) if pd.notna(r.exp) else "לא צוין",
                  "staff": n(r.staff), "disc": "כן" if r.disc else "לא"}
                 for r in list_rows.itertuples()],
    }

    summary = (f"איתור מעבדה מורשית לדיגום ובדיקת אסבסט: {n(n_labs)} מעבדות, {n(total)} רישיונות, "
               f"לפי סוג רישיון, צוות מורשה ותוקף.")
    agent = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "related_ids": ["19c40947-95f1-4ea0-8a04-ad56526726af",
                        "005fe7c5-be59-42de-91ea-0ce3cdece35c",
                        "7f1a7496-c3d9-498f-ade2-2ebb8e602916"],
        "suggested_tags": ["אסבסט", "מעבדות", "רישוי סביבתי", "דיגום", "אנליזה", "המשרד להגנת הסביבה"],
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"has_disc": bool(ev_years), "has_expiry": bool(years)},
    }
