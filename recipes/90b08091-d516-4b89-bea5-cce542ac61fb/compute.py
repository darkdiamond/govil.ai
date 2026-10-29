"""מאגר קבלני כוח אדם, שירותי אבטחה וניקיון, לשכות פרטיות ועגורנאים (Ministry of Labor).

One row per licence/permit (~8.2k): manpower contractors, service contractors
(cleaning / guarding & security), private employment bureaus (Israeli workers
only) and special crane-operator permits. A holder (corporate registration
number) can hold several licences — one row each.

Data quirks handled here:
- Rows with status "לא בתוקף" carry only the holder id/name, licence type and
  number — no address, town, owner, CEO or expiry date. Geography, expiry and
  completeness therefore describe valid licences only (disclosed on the page).
- `fieldfactivity` is meaningful only for valid service-contractor licences
  (cleaning / guarding & security); for other rows it holds a constant or a
  mismatched value, so it is read for that subset only.
- Holder legal form is inferred from the registration-number prefix (51/52 =
  company, 54–56 = partnership, 57 = cooperative, 58 = non-profit, 50 = public
  body, anything else = an individual's ID — a sole trader). The numbers
  themselves never reach the page; individuals' owner/CEO names are only
  counted (field fill rates), never shown.

There is no snapshot date; "now" is the earliest expiry month among valid
licences (expired licences flip to "לא בתוקף" upstream as the file updates).
"""
import pandas as pd

LRI, PDI = "⁦", "⁩"
VALID = "בתוקף"
TYPE_SHORT = {
    "קבלן שירות": "קבלן שירות",
    "קבלן כח אדם": "קבלן כוח אדם",
    "לשכה פרטית לתיווך עובדים ישראלים בלבד": "לשכה פרטית לתיווך עובדים",
    "היתר מיוחד לפעול כקבלן כח אדם המעסיק עגורנאי צריח": "היתר עגורנאי צריח",
}
SERVICE = "קבלן שירות"
MANPOWER = "קבלן כוח אדם"
BUREAU = "לשכה פרטית לתיווך עובדים"
FORM_ORDER = ["חברה", "יחיד (עוסק)", "שותפות", "עמותה / חל״צ", "אגודה שיתופית", "גוף ציבורי"]
FIELD_ORDER = ["ניקיון בלבד", "שמירה ואבטחה בלבד", "ניקיון וגם שמירה ואבטחה", "לא צוין"]
FILL_FIELDS = [("companyowner", "בעלים"), ("companyceo", "מנכ״ל"), ("address", "כתובת"),
               ("town", "יישוב")]
TOP_TOWNS = 15
MIX_TOWNS = 10
TOP_COMBOS = 8
PARETO_MARKS = [1, 5, 10, 20, 50]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def pct_bare(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def month_he(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def _form(idn):
    s = idn.strip().zfill(9)
    p = s[:2]
    if p in ("51", "52"):
        return "חברה"
    if p in ("54", "55", "56"):
        return "שותפות"
    if p == "57":
        return "אגודה שיתופית"
    if p == "58":
        return "עמותה / חל״צ"
    if p == "50":
        return "גוף ציבורי"
    return "יחיד (עוסק)"


def _field(s):
    clean = "ניקיון" in s
    sec = ("שמירה" in s) or ("אבטחה" in s)
    if clean and sec:
        return "ניקיון וגם שמירה ואבטחה"
    if clean:
        return "ניקיון בלבד"
    if sec:
        return "שמירה ואבטחה בלבד"
    return "לא צוין"


def _ordered(keys, order):
    known = [k for k in order if k in keys]
    rest = sorted(k for k in keys if k not in order)
    return known + rest


def _sorted_counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    raw_type = df["sugrishayon"].str.strip()
    out = pd.DataFrame({
        "holder": df["identitynumber"].str.strip(),
        "type": raw_type.map(lambda t: TYPE_SHORT.get(t, t)).replace("", "לא צוין"),
        "valid": df["status"].str.strip() == VALID,
        "field_raw": df["fieldfactivity"].str.strip(),
        "town": df["town"].str.strip(),
        "until": pd.to_datetime(df["validuntil"].str.strip(), errors="coerce", format="%Y-%m-%d"),
    })
    for col, _ in FILL_FIELDS:
        out["has_" + col] = df[col].str.strip() != ""
    out["form"] = out["holder"].map(_form)
    return out


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    act = df[df["valid"]].copy()
    n_act = len(act)
    n_inact = total - n_act

    # ---- licence types × status
    type_counts = _sorted_counts(df["type"])
    types = list(type_counts.index)
    act_by_type = act["type"].value_counts()
    type_valid = [int(act_by_type.get(t, 0)) for t in types]
    type_invalid = [int(type_counts[t]) - v for t, v in zip(types, type_valid)]
    type_share = {t: (v / int(type_counts[t]) if type_counts[t] else 0.0)
                  for t, v in zip(types, type_valid)}
    act_types = [t for t in types if act_by_type.get(t, 0) > 0]

    # ---- holders and their licence combinations (valid licences)
    holders_all = df["holder"].nunique()
    holder_types = act.groupby("holder")["type"].agg(lambda s: tuple(t for t in types if t in set(s)))
    n_holders = len(holder_types)
    combo = _sorted_counts(holder_types.map(lambda ts: " + ".join(ts)))
    combo_top = combo.head(TOP_COMBOS)
    combo_names = list(combo_top.index)
    combo_vals = [int(v) for v in combo_top.values]
    if len(combo) > TOP_COMBOS:
        combo_names.append("צירוף אחר")
        combo_vals.append(int(combo.iloc[TOP_COMBOS:].sum()))
    multi_holders = int((holder_types.map(len) > 1).sum())
    all_status = df.groupby("holder")["valid"].agg(["any", "all"])
    lapsed_holders = int((~all_status["any"]).sum())

    # ---- service contractors' fields (valid only)
    svc = act[act["type"] == SERVICE]
    fields = svc["field_raw"].map(_field).value_counts()
    field_names = [f for f in _ordered(set(fields.index), FIELD_ORDER) if fields.get(f, 0) > 0]
    field_vals = [int(fields[f]) for f in field_names]
    n_svc = len(svc)

    # ---- legal form by type (valid)
    form_ct = pd.crosstab(act["form"], act["type"])
    forms = [f for f in _ordered(set(form_ct.index), FORM_ORDER)]
    form_series = []
    form_table = []
    for f in forms:
        row = []
        for t in act_types:
            cnt = int(form_ct.at[f, t]) if (f in form_ct.index and t in form_ct.columns) else 0
            den = int(act_by_type.get(t, 0))
            row.append(round(cnt / den * 100, 1) if den else 0)
        form_series.append({"name": f, "data": row})
    for t in act_types:
        den = int(act_by_type.get(t, 0))
        cells = []
        for f in forms:
            cnt = int(form_ct.at[f, t]) if (f in form_ct.index and t in form_ct.columns) else 0
            cells.append(f"{n(cnt)} ({pct_bare(cnt / den) if den else '0%'})")
        form_table.append({"type": t, "cells": cells})
    indiv = act["form"] == "יחיד (עוסק)"
    indiv_share_by_type = {t: float(indiv[act["type"] == t].mean()) for t in act_types}

    # ---- expiry schedule (valid)
    exp = act.dropna(subset=["until"]).copy()
    bad_until = n_act - len(exp)
    exp["m"] = exp["until"].dt.to_period("M")
    expiry_chart = None
    expiry_year_rows = []
    exp_facts = None
    if len(exp):
        m0, m1 = exp["m"].min(), exp["m"].max()
        span = (m1 - m0).n + 1
        quarterly = span > 48
        exp["bucket"] = exp["until"].dt.to_period("Q") if quarterly else exp["m"]
        b0, b1 = exp["bucket"].min(), exp["bucket"].max()
        buckets = list(pd.period_range(b0, b1, freq=b0.freq))
        ct = exp.groupby(["bucket", "type"]).size()
        series = []
        for t in act_types:
            series.append({"name": t, "data": [int(ct.get((b, t), 0)) for b in buckets]})
        per_bucket = [sum(s["data"][i] for s in series) for i in range(len(buckets))]
        cum, run = [], 0
        for v in per_bucket:
            run += v
            cum.append(round(run / len(exp) * 100, 1))
        lab = (lambda p: f"{p.year} Q{p.quarter}") if quarterly else (lambda p: f"{p.month:02d}/{p.year}")
        expiry_chart = {"x": [lab(b) for b in buckets], "series": series, "cum": cum}
        exp["y"] = exp["until"].dt.year
        yct = exp.groupby(["y", "type"]).size()
        for y in sorted(exp["y"].unique()):
            cells = [n(yct.get((y, t), 0)) for t in act_types]
            expiry_year_rows.append({"year": str(int(y)), "cells": cells,
                                     "total": n(int((exp["y"] == y).sum()))})
        next3 = int((exp["m"] <= m0 + 2).sum())
        next12 = int((exp["m"] <= m0 + 11).sum())
        q = exp["until"].dt.to_period("Q")
        qc = _sorted_counts(q)
        peak_q = qc.index[0]
        exp_facts = {"m0": m0, "m1": m1, "next3": next3, "next12": next12,
                     "peak_q": peak_q, "peak_n": int(qc.iloc[0]), "n": len(exp),
                     "first_n": int((exp["m"] == m0).sum())}

    # ---- towns (valid, town known)
    tw = act[act["town"] != ""]
    n_tw = len(tw)
    town_counts = _sorted_counts(tw["town"])
    n_towns = len(town_counts)
    top_towns = list(town_counts.head(TOP_TOWNS).index)
    tct = tw.groupby(["town", "type"]).size()
    towns_chart = {"names": top_towns,
                   "series": [{"name": t, "data": [int(tct.get((c, t), 0)) for c in top_towns]}
                              for t in act_types]}
    towns_table = [{"name": c, "cells": [n(tct.get((c, t), 0)) for t in act_types],
                    "total": n(town_counts[c])} for c in top_towns]
    mix_towns = top_towns[:MIX_TOWNS]
    mix_series = []
    for t in act_types:
        mix_series.append({"name": t, "data": [
            round(int(tct.get((c, t), 0)) / int(town_counts[c]) * 100, 1) for c in mix_towns]})
    mix_table = [{"name": c, "cells": [pct_bare(int(tct.get((c, t), 0)) / int(town_counts[c]))
                                        for t in act_types]} for c in mix_towns]
    bureau_share_all = (int(tw["type"].eq(BUREAU).sum()) / n_tw) if n_tw else 0.0
    # pareto
    cum_t, run = [], 0
    for v in town_counts.values:
        run += int(v)
        cum_t.append(round(run / n_tw * 100, 1) if n_tw else 0)
    pareto_chart = {"x": list(range(1, n_towns + 1)), "y": cum_t}
    pareto_rows = []
    for k in PARETO_MARKS:
        if k <= n_towns:
            pareto_rows.append({"k": n(k), "share": f"{cum_t[k - 1]:.1f}%",
                                "count": n(int(town_counts.head(k).sum()))})
    top5_share = (int(town_counts.head(5).sum()) / n_tw) if n_tw else 0.0
    half_k = next((i + 1 for i, v in enumerate(cum_t) if v >= 50), None)

    # ---- data completeness (valid)
    fill_series = []
    fill_table = []
    fill = {}
    for col, name in FILL_FIELDS:
        data = []
        for t in act_types:
            sub = act[act["type"] == t]
            s = float(sub["has_" + col].mean()) if len(sub) else 0.0
            fill[(col, t)] = s
            data.append(round(s * 100, 1))
        fill_series.append({"name": name, "data": data})
    for t in act_types:
        fill_table.append({"type": t, "cells": [pct_bare(fill[(c, t)]) for c, _ in FILL_FIELDS]})

    # ---------------- insights
    def ins_inactive():
        if not total or n_inact / total < 0.1:
            return None
        head = f"{n(n_inact)} מתוך {n(total)} הרישיונות במאגר ({pct(n_inact / total)}) אינם בתוקף."
        inact = df[~df["valid"]]
        bare = float(((inact["town"] == "") & inact["until"].isna()).mean())
        if bare < 0.99:
            return head
        return (f"{head} ברשומות אלה אין יישוב ואין תאריך תוקף, ולכן הפילוח הגאוגרפי ולוח "
                f"הפקיעות מתייחסים לרישיונות בתוקף בלבד.")

    def ins_type_gap():
        big = [t for t in types if type_counts[t] >= 50]
        if len(big) < 2:
            return None
        hi = max(big, key=lambda t: (type_share[t], t))
        lo = min(big, key=lambda t: (type_share[t], t))
        if type_share[hi] - type_share[lo] < 0.2:
            return None
        lead = (f"כל {n(type_counts[hi])} הרישיונות מסוג {hi} רשומים כבתוקף"
                if type_share[hi] >= 1 else
                f"מבין רישיונות מסוג {hi} {pct(type_share[hi])} בתוקף")
        return (f"{lead}, לעומת {pct(type_share[lo])} בלבד מרישיונות {lo} — "
                f"רישיונות שפקעו נשארים במאגר וממשיכים להופיע בו.")

    def ins_dual():
        mp = holder_types[holder_types.map(lambda ts: MANPOWER in ts)]
        if len(mp) < 30:
            return None
        both = int(mp.map(lambda ts: SERVICE in ts).sum())
        s = both / len(mp)
        if s < 0.5:
            return None
        return (f"{n(both)} מתוך {n(len(mp))} בעלי רישיון בתוקף כקבלן כוח אדם ({pct(s)}) מחזיקים "
                f"גם ברישיון קבלן שירות בתוקף. בסך הכול {n(multi_holders)} מתוך {n(n_holders)} "
                f"בעלי הרישיונות הפעילים מחזיקים ביותר מסוג רישיון אחד.")

    def ins_fields():
        if n_svc < 30 or not field_names:
            return None
        lead = field_names[int(max(range(len(field_vals)), key=lambda i: (field_vals[i], -i)))]
        s = int(fields[lead]) / n_svc
        if s < 0.5:
            return None
        only_sec = int(fields.get("שמירה ואבטחה בלבד", 0))
        both = int(fields.get("ניקיון וגם שמירה ואבטחה", 0))
        sec = only_sec + both
        if not sec:
            return f"כל {n(n_svc)} קבלני השירות בתוקף רשומים בתחום \"{lead}\"."
        mix = (f"{n(both)} מהם יחד עם ניקיון" if both else "כולם ללא ניקיון")
        return (f"בקרב {n(n_svc)} קבלני השירות בתוקף, {pct(s)} רשומים בתחום \"{lead}\"; "
                f"שמירה ואבטחה מופיעה ב-{n(sec)} רישיונות ({pct(sec / n_svc)}), {mix}.")

    def ins_form():
        if len(act_types) < 2:
            return None
        hi = max(act_types, key=lambda t: (indiv_share_by_type[t], t))
        rest = act[act["type"] != hi]
        if not len(rest):
            return None
        rest_s = float((rest["form"] == "יחיד (עוסק)").mean())
        hs = indiv_share_by_type[hi]
        if hs - rest_s < 0.1:
            return None
        return (f"{pct(hs)} מהרישיונות בתוקף מסוג {hi} רשומים על שם אדם פרטי (עוסק יחיד) ולא על "
                f"תאגיד, לעומת {pct(rest_s)} בשאר סוגי הרישיונות — לפי סוג מספר הזיהוי של בעל הרישיון.")

    def ins_towns():
        if n_tw < 100 or n_towns < 10 or top5_share < 0.2:
            return None
        tail = f"; מחצית מהרישיונות מרוכזים ב-{n(half_k)} יישובים בלבד" if half_k else ""
        return (f"הרישיונות בתוקף פזורים ב-{n(n_towns)} יישובים, אך חמשת המובילים — "
                f"{', '.join(top_towns[:5])} — מרכזים {pct(top5_share)} מהם{tail}. "
                f"בראש {top_towns[0]} עם {n(town_counts.iloc[0])} רישיונות.")

    def ins_expiry():
        if not exp_facts or exp_facts["n"] < 50:
            return None
        f = exp_facts
        q = f["peak_q"]
        return (f"גל החידושים: {n(f['next12'])} רישיונות ({pct(f['next12'] / f['n'])}) פוקעים בשנים־עשר "
                f"החודשים החל מ{month_he(f['m0'])}, ו-{n(f['next3'])} כבר בשלושת החודשים הראשונים. "
                f"הרבעון העמוס ביותר הוא רבעון {q.quarter} של {q.year}, עם {n(f['peak_n'])} פקיעות.")

    def ins_fill():
        cands = [(t, fill[("companyceo", t)]) for t in act_types if act_by_type.get(t, 0) >= 30]
        if len(cands) < 2:
            return None
        lo_t, lo = min(cands, key=lambda x: (x[1], x[0]))
        hi_t, hi = max(cands, key=lambda x: (x[1], x[0]))
        if lo > 0.1 or hi < 0.5:
            return None
        no_owner = fill[("companyowner", lo_t)] == 0
        lead = (f"ברישיונות {lo_t} לא מופיעים שם בעלים ושם מנכ״ל באף רשומה" if lo == 0 and no_owner else
                f"ברישיונות {lo_t} לא מופיע שם מנכ״ל באף רשומה"
                if lo == 0 else f"ברישיונות {lo_t} שם המנכ״ל מופיע רק ב-{pct(lo)} מהרשומות")
        return f"{lead}, לעומת {pct(hi)} ברישיונות {hi_t}."

    rules = [
        ("inactive", ins_inactive()),
        ("type_gap", ins_type_gap()),
        ("dual", ins_dual()),
        ("fields", ins_fields()),
        ("expiry", ins_expiry()),
        ("towns", ins_towns()),
        ("form", ins_form()),
        ("fill", ins_fill()),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---------------- KPIs
    act_share = n_act / total if total else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "active": {"value": n_act, "display": n(n_act),
                   "tone": "ok" if act_share >= 0.8 else ("warn" if act_share < 0.5 else "brand")},
        "holders": {"value": n_holders, "display": n(n_holders), "tone": "brand"},
    }
    if exp_facts:
        s3 = exp_facts["next3"] / exp_facts["n"]
        kpis["next3"] = {"value": exp_facts["next3"], "display": n(exp_facts["next3"]),
                         "tone": "warn" if s3 >= 0.1 else "info"}
    else:
        kpis["next3"] = {"value": 0, "display": "0", "tone": "brand"}

    # ---------------- labels
    type_list = ", ".join(f"{t} ({n(type_counts[t])})" for t in types)
    m0_txt = month_he(exp_facts["m0"]) if exp_facts else ""
    m1_txt = month_he(exp_facts["m1"]) if exp_facts else ""
    exp_unit = "רבעון" if (expiry_chart and expiry_chart["x"] and "Q" in expiry_chart["x"][0]) else "חודש"
    labels = {
        "lede": (f"רישיונות והיתרים שמשרד העבודה מעניק לקבלני כוח אדם, לקבלני שירות בתחומי הניקיון, "
                 f"השמירה והאבטחה, ללשכות פרטיות לתיווך עובדים ישראלים ולקבלני כוח אדם המעסיקים "
                 f"עגורנאי צריח. המאגר כולל {n(total)} רישיונות של {n(holders_all)} בעלי רישיון; "
                 f"{n(n_act)} מהם ({pct(act_share)}) בתוקף, בידי {n(n_holders)} בעלי רישיון. "
                 f"לפי סוג: {type_list}."),
        "active_kpi": f"רישיונות בתוקף ({pct_bare(act_share)} מהמאגר)",
        "holders_kpi": "בעלי רישיון בתוקף (תאגידים ועוסקים)",
        "next3_kpi": (f"רישיונות שפוקעים בשלושת החודשים החל מ{m0_txt}" if exp_facts
                      else "רישיונות שפוקעים בקרוב"),
        "types_note": (f"מספר הרישיונות לפי סוג, ומתוכם כמה בתוקף. לשכה פרטית שרישיונה פקע אינה "
                       f"נשארת במאגר, ואילו אצל הקבלנים נשמרים גם רישיונות שאינם בתוקף."
                       if type_share.get(BUREAU, 0) >= 1 else
                       "מספר הרישיונות לפי סוג, ומתוכם כמה בתוקף."),
        "types_aria": (f"תרשים עמודות מוערמות: רישיונות לפי סוג ומצב תוקף; בראש {types[0]} "
                       f"עם {n(type_counts[types[0]])} רישיונות."),
        "types_caption": "רישיונות לפי סוג ומצב תוקף.",
        "combo_note": (f"כל בעל רישיון (לפי מספר התאגיד או העוסק) מסווג לפי צירוף סוגי הרישיונות "
                       f"שבתוקף בידיו. {n(multi_holders)} מתוך {n(n_holders)} מחזיקים ביותר מסוג אחד."
                       + (f" עוד {n(lapsed_holders)} בעלי רישיון מופיעים במאגר רק עם רישיונות שאינם בתוקף."
                          if lapsed_holders else "")),
        "combo_aria": (f"תרשים עמודות: בעלי רישיון בתוקף לפי צירוף סוגי רישיונות; הצירוף הנפוץ "
                       f"{combo_names[0] if combo_names else ''}."),
        "combo_caption": "בעלי רישיון בתוקף לפי צירוף סוגי הרישיונות.",
        "fields_note": (f"תחום הפעילות של {n(n_svc)} קבלני השירות בתוקף. התחום מדווח במאגר באופן "
                        f"עקבי רק לרישיונות אלה, ולכן אינו מוצג לסוגים האחרים."),
        "fields_aria": f"תרשים טבעת: קבלני שירות בתוקף לפי תחום פעילות, {n(n_svc)} רישיונות.",
        "fields_caption": "קבלני שירות בתוקף לפי תחום פעילות.",
        "form_note": ("הצורה המשפטית של בעל הרישיון, כפי שהיא נגזרת מסוג מספר הזיהוי (חברה, שותפות, "
                      "עמותה, אגודה שיתופית — או מספר זהות של אדם פרטי, כלומר עוסק יחיד). "
                      "שיעור מתוך הרישיונות בתוקף בכל סוג."),
        "form_aria": "תרשים עמודות מוערמות לשיעורים: הצורה המשפטית של בעלי הרישיונות בתוקף, לפי סוג רישיון.",
        "form_caption": "רישיונות בתוקף לפי סוג רישיון וצורה משפטית של בעל הרישיון.",
        "expiry_note": ((f"מספר הרישיונות בתוקף שפוקעים בכל {exp_unit}, מ{m0_txt} ועד {m1_txt}, "
                         f"והשיעור המצטבר שלהם. רישיון שיחודש יקבל תאריך תוקף חדש בעדכון הבא.")
                        + (f" ל-{n(bad_until)} רישיונות בתוקף אין תאריך תוקף תקין והם אינם נכללים."
                           if bad_until else "")),
        "expiry_aria": (f"תרשים עמודות מוערמות: רישיונות בתוקף לפי {exp_unit} פקיעה וסוג, "
                        f"{m0_txt}–{m1_txt}, עם קו שיעור מצטבר." if exp_facts else
                        "תרשים פקיעת רישיונות."),
        "expiry_caption": "רישיונות בתוקף לפי שנת פקיעה וסוג.",
        "towns_note": (f"{TOP_TOWNS} היישובים עם מספר הרישיונות בתוקף הגבוה ביותר, לפי סוג. "
                       f"הספירה מבוססת על {n(n_tw)} רישיונות בתוקף שבהם צוין יישוב."),
        "towns_aria": (f"תרשים עמודות מוערמות: {TOP_TOWNS} היישובים המובילים ברישיונות בתוקף; בראש "
                       f"{top_towns[0] if top_towns else ''}."),
        "towns_caption": f"רישיונות בתוקף ב-{TOP_TOWNS} היישובים המובילים, לפי סוג.",
        "mix_note": (f"הרכב סוגי הרישיונות ב-{MIX_TOWNS} היישובים הגדולים. בכלל הארץ "
                     f"{pct(bureau_share_all)} מהרישיונות בתוקף הם של לשכות פרטיות."),
        "mix_aria": f"תרשים עמודות מוערמות לשיעורים: הרכב סוגי הרישיונות ב-{MIX_TOWNS} היישובים המובילים.",
        "mix_caption": f"שיעור כל סוג רישיון מתוך הרישיונות בתוקף ב-{MIX_TOWNS} היישובים המובילים.",
        "pareto_note": (f"היישובים מדורגים לפי מספר הרישיונות בתוקף; הקו מראה איזה חלק מהרישיונות "
                        f"מרוכז ביישובים המובילים, מתוך {n(n_towns)} יישובים."),
        "pareto_aria": (f"גרף קו: שיעור מצטבר של רישיונות בתוקף לפי דירוג {n(n_towns)} היישובים."),
        "pareto_caption": "שיעור מצטבר של רישיונות בתוקף ביישובים המובילים.",
        "fill_note": ("איזה חלק מהרישיונות בתוקף בכל סוג כולל את שם הבעלים, שם המנכ״ל, כתובת ויישוב. "
                      "השמות עצמם מופיעים בטבלת הנתונים שבתחתית העמוד."),
        "fill_aria": "תרשים עמודות: שיעור הרישיונות בתוקף שבהם מולאו שדות הבעלים, המנכ״ל, הכתובת והיישוב, לפי סוג.",
        "fill_caption": "שיעור מילוי שדות ברישיונות בתוקף, לפי סוג רישיון.",
    }

    tables = {
        "types": [{"type": t, "valid": n(v), "invalid": n(i), "share": pct_bare(type_share[t])}
                  for t, v, i in zip(types, type_valid, type_invalid)],
        "combos": [{"name": k, "count": n(v)} for k, v in zip(combo_names, combo_vals)],
        "fields": [{"name": f, "count": n(v), "share": pct_bare(v / n_svc) if n_svc else "0%"}
                   for f, v in zip(field_names, field_vals)],
        "forms": forms,
        "form_rows": form_table,
        "act_types": act_types,
        "expiry_years": expiry_year_rows,
        "towns": towns_table,
        "mix": mix_table,
        "pareto": pareto_rows,
        "fill_names": [name for _, name in FILL_FIELDS],
        "fill": fill_table,
    }
    charts = {
        "types": {"names": types, "valid": type_valid, "invalid": type_invalid},
        "combos": {"names": combo_names, "values": combo_vals},
        "fields": [{"name": f, "value": v} for f, v in zip(field_names, field_vals)],
        "forms": {"x": act_types, "series": form_series},
        "expiry": expiry_chart,
        "towns": towns_chart,
        "mix": {"names": mix_towns, "series": mix_series},
        "pareto": pareto_chart,
        "fill": {"x": act_types, "series": fill_series},
    }
    flags = {"expiry": expiry_chart is not None, "fields": bool(field_names) and n_svc > 0}

    return {
        "agent_data": {
            "summary_he": (f"רשימת קבלני כוח אדם וקבלני שירות (שמירה, אבטחה וניקיון) מורשים — בדיקת רישיון לפי שם חברה, ח.פ. או יישוב: "
                           f"{n(n_act)} רישיונות בתוקף מתוך {n(total)}."),
            "dataset_kind": "registry",
            "related_ids": ["3ab09979-7d64-4402-ae51-5fa320a37a56",
                            "f2ce5a09-7274-4a36-809e-2cb751578c06",
                            "c0beab05-9061-4dad-868c-40142260d35f"],
            "suggested_tags": ["קבלני כוח אדם", "קבלני שירות", "ניקיון", "שמירה ואבטחה",
                               "לשכות תיווך", "עגורנאי צריח", "רישוי", "משרד העבודה"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
