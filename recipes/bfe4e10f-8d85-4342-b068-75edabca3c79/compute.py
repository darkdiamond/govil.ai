"""עיצומים כספיים — Ministry of Environmental Protection administrative fines.

One row per financial sanction (~430): violated law, violation details,
violator name and occupation, demand date, original amount, reduction rate
and reasons, final (updated) amount, publication end date and the legal
(appeal) status with a free-text summary naming the court.

"Now" is the latest demand date in the data (never the wall clock); that
year is partial unless the date reaches late December.

Naming: fined businesses may be named and ranked. A violator is withheld
from every named list when the source publishes a number instead of a
name, when the publication period is short (about two years — the track
the data uses for non-corporate violators), or when the occupation marks a
private person ("כל אדם", "מדביר"). Those fines still count in every total.
Court case numbers inside the legal-status summary are never shown — only
the court name is extracted.

The reduction is computed from the two amounts (1 − final/original), not
from the free-text rate column, which carries values like "1,00%". All
money sums use math.fsum so the result is independent of row order.
"""
import math
import re

import pandas as pd

TOP_LAWS_STACK = 5
TOP_LAWS = 10
TOP_OCC = 8
TOP_VIOLATORS = 10
TOP_DETAILS = 8
TOP_COURTS = 8
SCATTER_MAX = 1200
MIN_LAW_APPEAL = 10
CORP_MIN_YEARS = 3.0
PRIVATE_OCC = {"כל אדם", "מדביר"}
MISSING = {"", "(חסר)"}
OTHER = "אחר"
OTHER_LAWS = "חוקים אחרים"
STATUS_LABEL = {"(חסר)": "ללא הליך משפטי", "": "ללא הליך משפטי",
                "פתוח": "הליך פתוח", "סגור": "הליך סגור"}
STATUS_ORDER = ["הליך פתוח", "הליך סגור", "ללא הליך משפטי"]
STATUS_COLOR = {"הליך פתוח": "#9a6700", "הליך סגור": "#0068f5", "ללא הליך משפטי": "#c3cfe7"}
DED_BUCKETS = [("ללא הפחתה", 0, 0), ("1% עד 19%", 1, 19), ("20% עד 29%", 20, 29),
               ("30% עד 39%", 30, 39), ("40% עד 49%", 40, 49), ("50% עד 99%", 50, 99),
               ("הפחתה מלאה", 100, 100)]
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def n(v):
    return f"{int(round(v)):,}"


def fines(c):
    return "עיצום אחד" if int(c) == 1 else f"{n(c)} עיצומים"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def mil(v, digits=1):
    return f"{v / 1e6:,.{digits}f}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def fsum(values):
    return math.fsum(float(v) for v in values)


def _num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce")


def _clean(s):
    s = s.replace("״", '"').replace("׳", "'")
    return re.sub(r"\s+", " ", s).strip()


def _key(s):
    return re.sub(r"[\s\"'.\-]", "", s)


def _counts(s):
    """Counts sorted by count desc, then label asc (total, stable order)."""
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _court(summary):
    m = re.search(r"בית משפט:\s*([^,]*)", summary)
    if not m:
        return ""
    c = m.group(1).strip()
    return "" if c in ("", "()") else c


def _prepare(df):
    out = pd.DataFrame({
        "id": df["FinancialSanctionId"].str.strip(),
        "law": df["violated_law"].map(_clean).replace("", "לא צוין"),
        "detail": df["violation_details"].map(_clean),
        "name": df["violator_name"].map(_clean),
        "occ": df["violator_occupation"].map(_clean).replace("", "לא צוין"),
        "date": pd.to_datetime(df["debt_demand_date"].str.strip(), format="%d/%m/%Y",
                               errors="coerce"),
        "end": pd.to_datetime(df["publication_end_date"].str.strip(), format="%d/%m/%Y",
                              errors="coerce"),
        "orig": _num(df["original_sunction_sum"]),
        "final": _num(df["updated_sunction_sum"]),
        "reason": df["deduction_reason"].map(_clean),
        "status": df["appeal_status"].map(_clean).map(lambda s: STATUS_LABEL.get(s, s)),
        "court": df["appeal_status_summary"].map(_court),
    })
    out["final"] = out["final"].fillna(out["orig"])
    out = out.dropna(subset=["orig", "final"])
    out["pub_years"] = (out["end"] - out["date"]).dt.days / 365.25
    numeric = out["name"].str.fullmatch(r"\d+") | (out["name"] == "")
    out["withheld"] = numeric
    out["public"] = (~numeric & (out["pub_years"] >= CORP_MIN_YEARS)
                     & ~out["occ"].isin(PRIVATE_OCC))
    out["key"] = out["name"].map(_key)
    out["ded"] = (1 - out["final"] / out["orig"]).where(out["orig"] > 0)
    out = out.sort_values(["date", "id"], kind="stable").reset_index(drop=True)
    return out


def _display_names(pub):
    """Canonical display per normalized key: most frequent spelling, ties by text."""
    v = (pub.groupby(["key", "name"]).size().reset_index(name="c")
         .sort_values(["key", "c", "name"], ascending=[True, False, True]))
    return v.drop_duplicates("key").set_index("key")["name"]


def _sum_by(df, col, val="final"):
    return {k: fsum(g[val].tolist()) for k, g in df.groupby(col)}


# ---------------------------------------------------------------- insights

def insight_trend(per_year, last_full, amt_year):
    prev = last_full - 1
    c, p = int(per_year.get(last_full, 0)), int(per_year.get(prev, 0))
    if p < 5 or c == 0:
        return None
    chg = c / p - 1
    a_c, a_p = amt_year.get(last_full, 0.0), amt_year.get(prev, 0.0)
    if abs(chg) < 0.1:
        head = f"מספר העיצומים יציב: {n(c)} ב-{last_full} לעומת {n(p)} ב-{prev}"
    elif chg > 0:
        head = (f"מספר העיצומים עלה ב-{pct(chg * 100, 0)}: {n(c)} ב-{last_full} לעומת "
                f"{n(p)} ב-{prev}")
    else:
        head = (f"מספר העיצומים ירד ב-{pct(-chg * 100, 0)}: {n(c)} ב-{last_full} לעומת "
                f"{n(p)} ב-{prev}")
    if a_p > 0 and abs(a_c / a_p - 1) >= 0.1:
        dir_ = "עלה" if a_c > a_p else "ירד"
        tail = f"; הסכום הכולל {dir_} מ-{mil(a_p)} ל-{mil(a_c)} מיליון ₪"
        if chg >= 0.1 and a_c < a_p:
            tail += " — יותר עיצומים, אך בסכומים קטנים יותר"
    else:
        tail = f"; הסכום הכולל {mil(a_c)} מיליון ₪"
    return head + tail + "."


def insight_ytd(df, ref, partial):
    if not partial:
        return None
    y = ref.year
    md = df["date"].dt.month * 100 + df["date"].dt.day
    cur = df[df["date"].dt.year == y]
    prev = df[(df["date"].dt.year == y - 1) & (md <= ref.month * 100 + ref.day)]
    if len(prev) < 5:
        return None
    c, p = len(cur), len(prev)
    chg = c / p - 1
    if abs(chg) < 0.1:
        trend = f"בדומה לתקופה המקבילה ב-{y - 1} ({n(p)})"
    else:
        trend = (f"{pct(abs(chg) * 100, 0)} {'יותר' if chg > 0 else 'פחות'} מבתקופה המקבילה "
                 f"ב-{y - 1} ({n(p)})")
    return (f"מתחילת {y} ועד {d_he(ref)} הוטלו {n(c)} עיצומים בסך {mil(fsum(cur['final']))} "
            f"מיליון ₪ — {trend}.")


def insight_batch(df):
    days = _counts(df["date"].dt.strftime("%Y-%m-%d"))
    if days.empty:
        return None
    day, c = days.index[0], int(days.iloc[0])
    if c < 10 or c / len(df) < 0.05:
        return None
    sub = df[df["date"].dt.strftime("%Y-%m-%d") == day]
    laws = _counts(sub["law"])
    ts = pd.Timestamp(day)
    s = f"העיצומים מוטלים במקבצים: ב-{d_he(ts)} לבדו הוטלו {n(c)} עיצומים"
    if int(laws.iloc[0]) == c:
        s += f", כולם לפי {laws.index[0]}"
    elif int(laws.iloc[0]) / c >= 0.6:
        s += f", {n(laws.iloc[0])} מהם לפי {laws.index[0]}"
    multi = int((days >= 5).sum())
    if multi > 1:
        return s + f"; ב-{n(multi)} ימים שונים הוטלו חמישה עיצומים ויותר."
    return s + "."


def insight_law_mix(law_n, law_amt, total, total_amt):
    if law_n.empty or total_amt <= 0:
        return None
    lead_n = law_n.index[0]
    lead_a = max(sorted(law_amt), key=lambda k: law_amt[k])
    if lead_n == lead_a:
        return (f"{lead_n} מוביל הן במספר העיצומים ({n(law_n[lead_n])}, "
                f"{pct(law_n[lead_n] / total * 100)}) והן בסכום ({mil(law_amt[lead_n])} מיליון ₪).")
    return (f"{lead_n} מוביל במספר העיצומים — {n(law_n[lead_n])} ({pct(law_n[lead_n] / total * 100)}), "
            f"אך רק {pct(law_amt[lead_n] / total_amt * 100)} מהסכום; {lead_a} אחראי ל-"
            f"{pct(law_amt[lead_a] / total_amt * 100)} מהסכום ({mil(law_amt[lead_a])} מיליון ₪) "
            f"מ-{n(law_n[lead_a])} עיצומים בלבד.")


def insight_concentration(df, names, total_amt):
    if total_amt <= 0 or len(df) < 10:
        return None
    top = df.sort_values(["final", "id"], ascending=[False, True], kind="stable").iloc[0]
    share = top["final"] / total_amt
    if share < 0.1:
        return None
    who = names.get(top["key"], top["name"]) if top["public"] else "מפר שאינו מוצג בשמו"
    top10 = fsum(df.sort_values(["final", "id"], ascending=[False, True]).head(10)["final"])
    return (f"העיצום הגבוה ביותר — {mil(top['final'])} מיליון ₪ ל{who} לפי {top['law']} "
            f"({d_he(top['date'])}) — הוא {pct(share * 100)} מסכום כל העיצומים; עשרת העיצומים "
            f"הגבוהים מרכזים {pct(top10 / total_amt * 100)} מהסכום.")


def insight_deduction(df, reasons):
    base = df[df["orig"] > 0]
    if len(base) < 10:
        return None
    red = base[base["ded"] > 0.0005]
    if red.empty:
        return None
    cut = fsum(base["orig"]) - fsum(base["final"])
    s = (f"{pct(len(red) / len(base) * 100, 0)} מהעיצומים ({n(len(red))}) הופחתו, ובסך הכול "
         f"נגרעו {mil(cut)} מיליון ₪ ({pct(cut / fsum(base['orig']) * 100)} מהסכום המקורי)")
    if not reasons.empty:
        s += (f"; הנימוק השכיח: {reasons.index[0]} ({n(reasons.iloc[0])} עיצומים)")
    return s + "."


def insight_appeals(df, law_n):
    total = len(df)
    st = df["status"].value_counts()
    k = total - int(st.get("ללא הליך משפטי", 0))
    if total < 10 or k == 0:
        return None
    op, cl = int(st.get("הליך פתוח", 0)), int(st.get("הליך סגור", 0))
    s = (f"ב-{n(k)} עיצומים ({pct(k / total * 100)}) מתנהל או התנהל הליך משפטי — "
         f"{n(op)} פתוחים ו-{n(cl)} סגורים")
    elig = [law for law in law_n.index if law_n[law] >= MIN_LAW_APPEAL]
    rates = []
    for law in elig:
        sub = df[df["law"] == law]
        rates.append((-(sub["status"] != "ללא הליך משפטי").mean(), law))
    if len(rates) >= 2:
        rates.sort()
        r, law = -rates[0][0], rates[0][1]
        if r * total / k > 1.3 and r > 0:
            s += (f"; השיעור הגבוה ביותר ב{law} — {pct(r * 100, 0)} מעיצומיו "
                  f"(מבין חוקים עם {MIN_LAW_APPEAL} עיצומים לפחות)")
    return s + "."


def insight_repeat(pub, names):
    vc = _counts(pub["key"])
    multi = vc[vc >= 2]
    if multi.empty:
        return None
    mx = int(vc.iloc[0])
    leaders = sorted(names.get(k, k) for k in vc[vc == mx].index)
    s = f"{n(len(multi))} מפרים הנקובים בשמם קיבלו יותר מעיצום אחד"
    if mx >= 3 and len(leaders) == 1:
        s += f"; המרבה ביותר — {leaders[0]} — עם {n(mx)} עיצומים"
    elif mx >= 3 and len(leaders) <= 3:
        s += f"; המרבים ביותר — {', '.join(leaders[:-1])} ו{leaders[-1]} — עם {n(mx)} עיצומים כל אחד"
    else:
        s += f"; המרבים קיבלו {n(mx)} עיצומים כל אחד"
    return s + "."


def insight_withheld(df):
    w = int(df["withheld"].sum())
    hidden = int((~df["public"]).sum())
    if hidden == 0:
        return None
    short = df["pub_years"] < CORP_MIN_YEARS
    s_n = int(short.sum())
    long_years = df.loc[~short, "pub_years"].round().mode()
    s = ""
    if w:
        s = f"ב-{n(w)} עיצומים שם המפר אינו מפורסם — במקומו מופיע מספר"
    if s_n:
        yrs = int(round(df.loc[short, "pub_years"].median()))
        part = (f"{n(s_n)} עיצומים מתפרסמים ל-{n(yrs)} שנים בלבד"
                + (f", לעומת {n(long_years.iloc[0])} שנים ברוב המאגר" if not long_years.empty else ""))
        s = (s + "; " + part) if s else part
    if not s:
        return None
    return s + ". עיצומים אלה נספרים בכל הסיכומים, אך אינם מוצגים בדירוגי המפרים."


# ----------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    dated = df.dropna(subset=["date"])
    ref = dated["date"].max()
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = ref_year - 1 if partial else ref_year
    first = dated["date"].min()
    years = list(range(int(first.year), ref_year + 1))

    total_orig = fsum(df["orig"])
    total_final = fsum(df["final"])
    cut = total_orig - total_final

    # Yearly.
    yr = dated["date"].dt.year
    per_year = yr.value_counts().reindex(years, fill_value=0)
    amt_year = _sum_by(dated.assign(y=yr), "y")
    year_labels = [f"{y} (חלקית)" if (y == ref_year and partial) else str(y) for y in years]

    # Laws.
    law_n = _counts(df["law"])
    law_amt = _sum_by(df, "law")
    law_orig = _sum_by(df, "law", "orig")
    # Cap at TOP_LAWS + "אחר", but never bucket a single leftover law.
    cap = TOP_LAWS if len(law_n) > TOP_LAWS + 1 else len(law_n)
    laws_top = list(law_n.index[:cap])
    rest_laws = list(law_n.index[cap:])

    def law_row(names_):
        sub = df[df["law"].isin(names_)]
        return (len(sub), fsum(sub["orig"]), fsum(sub["final"]),
                float(sub["final"].median()) if len(sub) else 0.0)

    law_rows = [(lw,) + law_row([lw]) for lw in laws_top]
    if rest_laws:
        law_rows.append((f"{OTHER} ({n(len(rest_laws))} חוקים)",) + law_row(rest_laws))

    # Quarterly stacked by top laws.
    stack_laws = list(law_n.index[:TOP_LAWS_STACK])
    q = dated["date"].dt.to_period("Q")
    q_all = pd.period_range(q.min(), q.max(), freq="Q")
    q_labels = [f"{p.year} ר{p.quarter}" for p in q_all]
    law_stack = dated["law"].where(dated["law"].isin(stack_laws), OTHER_LAWS)
    qc = pd.crosstab(q, law_stack).reindex(index=q_all, fill_value=0)
    q_series = [{"name": lw, "data": [int(v) for v in qc[lw]]}
                for lw in stack_laws + ([OTHER_LAWS] if OTHER_LAWS in qc.columns else [])
                if lw in qc.columns]
    q_amt = {p: fsum(g["final"]) for p, g in dated.groupby(q)}
    q_amt_series = [round(q_amt.get(p, 0.0) / 1e6, 3) for p in q_all]

    # Scatter: each fine's final amount over time (log axis; zero amounts dropped).
    sc = dated[dated["final"] > 0]
    sc_capped = len(sc) > SCATTER_MAX
    sc = sc.tail(SCATTER_MAX)
    sc_zero = int((dated["final"] <= 0).sum())
    sc_law = sc["law"].where(sc["law"].isin(stack_laws), OTHER_LAWS)
    sc_series = []
    for lw in stack_laws + [OTHER_LAWS]:
        sub = sc[sc_law == lw]
        if sub.empty:
            continue
        sc_series.append({"name": lw, "data": [[d.strftime("%Y-%m-%d"), round(float(v), 1)]
                                               for d, v in zip(sub["date"], sub["final"])]})

    # Occupations.
    occ = _counts(df["occ"])
    occ_top = list(occ.index[:TOP_OCC])
    occ_rest = int(occ.iloc[TOP_OCC:].sum())
    occ_names = occ_top + ([f"{OTHER} ({n(len(occ) - TOP_OCC)} סוגים)"] if occ_rest else [])
    occ_vals = [int(occ[o]) for o in occ_top] + ([occ_rest] if occ_rest else [])
    occ_amt = [fsum(df.loc[df["occ"] == o, "final"]) for o in occ_top]
    if occ_rest:
        occ_amt.append(fsum(df.loc[~df["occ"].isin(occ_top), "final"]))

    # Deductions.
    base = df[df["orig"] > 0]
    r = (base["ded"] * 100 + 1e-9).apply(math.floor)
    ded_vals = [int(((r >= lo) & (r <= hi)).sum()) for _, lo, hi in DED_BUCKETS]
    reasons = _counts(df.loc[~df["reason"].isin(MISSING), "reason"]
                      .str.split(r",\s*").explode().map(_clean)
                      .loc[lambda s: s != ""])
    no_orig = total - len(base)

    # Violators (public only).
    pub = df[df["public"]]
    names = _display_names(pub)
    v_amt = _sum_by(pub, "key")
    v_n = pub["key"].value_counts()
    v_rank = sorted(v_amt, key=lambda k: (-v_amt[k], k))[:TOP_VIOLATORS]
    v_law = {k: _counts(g["law"]) for k, g in pub[pub["key"].isin(v_rank)].groupby("key")}
    hidden = total - len(pub)
    top_rows = []
    for k in v_rank:
        lc = v_law[k]
        more = len(lc) - 1
        law_txt = (lc.index[0] if more == 0 else f"{lc.index[0]} ועוד חוק אחד" if more == 1
                   else f"{lc.index[0]} ועוד {n(more)} חוקים")
        top_rows.append({"name": names[k], "law": law_txt,
                         "count": n(v_n[k]), "amount": n(v_amt[k])})
    rep = pub["key"].value_counts()
    rep_buckets = [("עיצום אחד", int((rep == 1).sum())), ("שניים", int((rep == 2).sum())),
                   ("שלושה", int((rep == 3).sum())), ("ארבעה ויותר", int((rep >= 4).sum()))]

    # Violation details.
    det = df[df["detail"] != ""]
    det_n = _counts(det["law"] + "\u0001" + det["detail"])
    det_rows = []
    for k, c in det_n.head(TOP_DETAILS).items():
        lw, txt = k.split("\u0001", 1)
        det_rows.append({"law": lw, "detail": txt, "count": int(c),
                         "short": (txt[:42].rstrip() + "…") if len(txt) > 44 else txt})
    det_missing = total - len(det)

    # Legal status.
    st_present = list(df["status"].unique())
    st_order = [s for s in STATUS_ORDER if s in st_present] + sorted(set(st_present) - set(STATUS_ORDER))
    st_counts = df["status"].value_counts()
    ap_laws = [lw for lw in law_n.index if law_n[lw] >= MIN_LAW_APPEAL]
    ap_ct = pd.crosstab(df["law"], df["status"]).reindex(index=ap_laws, columns=st_order, fill_value=0)
    ap_series = [{"name": s, "color": STATUS_COLOR.get(s),
                  "data": [round(float(ap_ct.loc[lw, s] / ap_ct.loc[lw].sum() * 100), 1) for lw in ap_laws]}
                 for s in st_order]
    in_court = df[df["status"] != "ללא הליך משפטי"]
    courts = _counts(in_court["court"].replace("", "לא צוין"))
    c_top = list(courts.index[:TOP_COURTS])
    c_rest = int(courts.iloc[TOP_COURTS:].sum())
    court_names = c_top + ([OTHER] if c_rest else [])
    court_vals = [int(courts[c]) for c in c_top] + ([c_rest] if c_rest else [])

    # ---------------------------------------------------------- outputs
    open_n = int(st_counts.get("הליך פתוח", 0))
    ded_share = cut / total_orig * 100 if total_orig else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "final": {"value": round(total_final, 2), "display": mil(total_final), "tone": "brand"},
        "cut": {"value": round(ded_share, 2), "display": f"{ded_share:.1f}%", "tone": "info"},
        "open": {"value": open_n, "display": n(open_n), "tone": "warn" if open_n else "ok"},
    }

    rules = [
        ("trend", insight_trend(per_year, last_full, amt_year)),
        ("ytd", insight_ytd(dated, ref, partial)),
        ("law_mix", insight_law_mix(law_n, law_amt, total, total_final)),
        ("concentration", insight_concentration(df, names, total_final)),
        ("deduction", insight_deduction(df, reasons)),
        ("batch", insight_batch(dated)),
        ("appeals", insight_appeals(df, law_n)),
        ("repeat", insight_repeat(pub, names)),
        ("withheld", insight_withheld(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    peak_y = int(per_year.idxmax())
    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    lead_a = max(sorted(law_amt), key=lambda k: law_amt[k])
    labels = {
        "lede": (f"העיצומים הכספיים שהטיל המשרד להגנת הסביבה: {n(total)} עיצומים מ-{d_he(first)} "
                 f"ועד {d_he(ref)}, לפי {n(len(law_n))} חוקים. הסכום המקורי הכולל "
                 f"{mil(total_orig)} מיליון ₪, ולאחר הפחתות {mil(total_final)} מיליון ₪."),
        "final_kpi": "סך העיצומים לאחר הפחתה (מיליון ₪)",
        "cut_kpi": f"שיעור ההפחתה מהסכום המקורי ({mil(cut)} מיליון ₪)",
        "years_note": f"מספר העיצומים (עמודות) והסכום לאחר הפחתה (קו) לפי שנת הטלת העיצום.{partial_note}",
        "years_aria": (f"גרף עמודות וקו: עיצומים לפי שנה, {years[0]} עד {ref_year}; "
                       f"השיא ב-{peak_y} עם {n(per_year[peak_y])} עיצומים."),
        "years_caption": "מספר עיצומים וסכום לאחר הפחתה לפי שנה.",
        "q_note": (f"מספר העיצומים בכל רבעון לפי החוק שהופר ({TOP_LAWS_STACK} החוקים השכיחים, "
                   f"השאר תחת \"{OTHER_LAWS}\"), והסכום הרבעוני לאחר הפחתה (קו).{partial_note}"),
        "q_aria": (f"גרף עמודות מוערמות: עיצומים לפי רבעון וחוק, {q_labels[0]} עד {q_labels[-1]}."),
        "law_note": (f"מספר העיצומים והסכום לפי החוק שהופר. בתרשים הסכום, החלק הבהיר הוא ההפחתה "
                     f"מהסכום המקורי."
                     + (f" {n(len(rest_laws))} חוקים נוספים מקובצים תחת \"{OTHER}\"." if rest_laws else "")),
        "law_count_aria": (f"תרשים עמודות אופקי: עיצומים לפי חוק — {law_n.index[0]} בראש עם "
                           f"{n(law_n.iloc[0])} עיצומים."),
        "law_amt_aria": (f"תרשים עמודות אופקי מוערם: סכום לאחר הפחתה והפחתה לפי חוק — {lead_a} "
                         f"בראש עם {mil(law_amt[lead_a])} מיליון ₪."),
        "law_caption": "עיצומים, סכום מקורי, סכום לאחר הפחתה ושיעור הפחתה לפי חוק.",
        "sc_note": ("כל נקודה היא עיצום אחד: מועד ההטלה והסכום לאחר הפחתה, בציר לוגריתמי. "
                    "השורות האופקיות הן תעריפים קבועים שחוזרים על עצמם."
                    + (f" {fines(sc_zero)} בסכום אפס {'אינו מוצג' if sc_zero == 1 else 'אינם מוצגים'}." if sc_zero else "")
                    + (f" מוצגים {n(SCATTER_MAX)} העיצומים האחרונים." if sc_capped else "")),
        "sc_aria": (f"תרשים פיזור: {n(len(sc))} עיצומים לפי מועד וסכום, בציר לוגריתמי; "
                    f"הגבוה {mil(sc['final'].max())} מיליון ₪."),
        "occ_note": "סוג העיסוק של המפר כפי שנרשם בעיצום.",
        "occ_aria": f"תרשים עמודות אופקי: עיצומים לפי סוג עיסוק — {occ.index[0]} בראש עם {n(occ.iloc[0])}.",
        "occ_caption": "מספר עיצומים וסכום לאחר הפחתה לפי סוג עיסוק המפר.",
        "ded_note": ("שיעור ההפחתה בכל עיצום, מחושב מהסכום המקורי ומהסכום לאחר הפחתה."
                     + (f" {fines(no_orig)} {'שסכומו' if no_orig == 1 else 'שסכומם'} המקורי אפס {'אינו נכלל' if no_orig == 1 else 'אינם נכללים'}." if no_orig else "")),
        "ded_aria": (f"תרשים עמודות: עיצומים לפי שיעור הפחתה — {n(ded_vals[0])} ללא הפחתה."),
        "ded_caption": "מספר עיצומים לפי שיעור ההפחתה.",
        "reasons_note": "נימוקי ההפחתה; עיצום אחד יכול לשאת כמה נימוקים.",
        "reasons_aria": (f"תרשים עמודות אופקי: נימוקי הפחתה — {reasons.index[0]} בראש."
                         if not reasons.empty else "תרשים עמודות אופקי: נימוקי הפחתה."),
        "reasons_caption": "מספר עיצומים לפי נימוק ההפחתה.",
        "top_note": (f"{TOP_VIOLATORS} המפרים בסכום המצטבר הגבוה ביותר (לאחר הפחתה). "
                     f"{n(hidden)} עיצומים שבהם שם המפר לא פורסם, או שהוטלו על יחידים, "
                     f"אינם נכללים בדירוג."),
        "top_aria": (f"תרשים עמודות אופקי: {TOP_VIOLATORS} המפרים בסכום הגבוה ביותר — "
                     f"{top_rows[0]['name']} בראש." if top_rows else "תרשים עמודות אופקי: המפרים המובילים."),
        "top_caption": "המפרים בסכום העיצומים המצטבר הגבוה ביותר.",
        "rep_note": "כמה עיצומים קיבל כל מפר הנקוב בשמו.",
        "rep_aria": (f"תרשים עמודות: מפרים לפי מספר העיצומים — {n(rep_buckets[0][1])} קיבלו עיצום אחד."),
        "rep_caption": "מספר המפרים לפי מספר העיצומים שקיבלו.",
        "det_note": (f"{TOP_DETAILS} תיאורי ההפרה השכיחים."
                     + (f" ב{'עיצום אחד' if det_missing == 1 else '-' + n(det_missing) + ' עיצומים'} התיאור ריק." if det_missing else "")),
        "det_aria": (f"תרשים עמודות אופקי: תיאורי ההפרה השכיחים — הראשון עם {n(det_rows[0]['count'])} עיצומים."
                     if det_rows else "תרשים עמודות אופקי: תיאורי ההפרה השכיחים."),
        "det_caption": "מספר עיצומים לפי תיאור ההפרה והחוק.",
        "ap_note": (f"התפלגות הסטטוס המשפטי בכל חוק (חוקים עם {MIN_LAW_APPEAL} עיצומים לפחות), באחוזים."),
        "ap_aria": (f"תרשים עמודות מוערמות באחוזים: סטטוס משפטי לפי חוק — {n(open_n)} הליכים פתוחים."),
        "ap_caption": "שיעור כל סטטוס משפטי לפי חוק.",
        "court_note": (f"בתי המשפט שבהם מתנהלים או התנהלו {n(len(in_court))} ההליכים, "
                       f"כפי שנרשמו בסיכום המצב המשפטי."),
        "court_aria": (f"תרשים עמודות אופקי: הליכים משפטיים לפי בית משפט — {courts.index[0]} בראש."
                       if not courts.empty else "תרשים עמודות אופקי: הליכים לפי בית משפט."),
        "court_caption": "מספר הליכים משפטיים לפי בית משפט.",
    }

    charts = {
        "years": {"x": year_labels, "count": [int(per_year[y]) for y in years],
                  "amount": [round(amt_year.get(y, 0.0) / 1e6, 3) for y in years]},
        "quarters": {"x": q_labels, "series": q_series, "amount": q_amt_series,
                     "zoom_from": max(0, len(q_labels) - 16)},
        "law": {"names": [r_[0] for r_ in law_rows], "count": [r_[1] for r_ in law_rows],
                "final": [round(r_[3] / 1e6, 3) for r_ in law_rows],
                "cut": [round((r_[2] - r_[3]) / 1e6, 3) for r_ in law_rows]},
        "scatter": {"series": sc_series},
        "occ": {"names": occ_names, "values": occ_vals},
        "ded": {"names": [b[0] for b in DED_BUCKETS], "values": ded_vals},
        "reasons": {"names": list(reasons.index), "values": [int(v) for v in reasons.values]},
        "top": {"names": [t["name"] for t in top_rows],
                "values": [round(v_amt[k] / 1e6, 3) for k in v_rank]},
        "repeat": {"names": [b[0] for b in rep_buckets], "values": [b[1] for b in rep_buckets]},
        "details": {"names": [d["short"] for d in det_rows], "full": [d["detail"] for d in det_rows],
                    "laws": [d["law"] for d in det_rows], "values": [d["count"] for d in det_rows]},
        "appeal": {"names": ap_laws, "series": ap_series},
        "courts": {"names": court_names, "values": court_vals},
    }

    tables = {
        "years": [{"year": lab, "count": n(per_year[y]), "amount": n(amt_year.get(y, 0.0))}
                  for lab, y in zip(year_labels, years)],
        "law": [{"name": r_[0], "count": n(r_[1]), "orig": n(r_[2]), "final": n(r_[3]),
                 "cut": f"{(1 - r_[3] / r_[2]) * 100:.1f}%" if r_[2] else "—"} for r_ in law_rows],
        "occ": [{"name": nm, "count": n(v), "amount": n(a)}
                for nm, v, a in zip(occ_names, occ_vals, occ_amt)],
        "ded": [{"name": b[0], "count": n(v)} for b, v in zip(DED_BUCKETS, ded_vals)],
        "reasons": [{"name": k, "count": n(v)} for k, v in reasons.items()],
        "top": top_rows,
        "repeat": [{"name": b[0], "count": n(b[1])} for b in rep_buckets],
        "details": [{"law": d["law"], "detail": d["detail"], "count": n(d["count"])} for d in det_rows],
        "appeal": [{"name": lw, "total": n(ap_ct.loc[lw].sum()),
                    "shares": [f"{ap_ct.loc[lw, s] / ap_ct.loc[lw].sum() * 100:.1f}%" for s in st_order]}
                   for lw in ap_laws],
        "status_cols": st_order,
        "courts": [{"name": c, "count": n(v)} for c, v in zip(court_names, court_vals)],
    }

    return {
        "agent_data": {
            "summary_he": (f"העיצומים הכספיים של המשרד להגנת הסביבה: {n(total)} עיצומים בסך "
                           f"{mil(total_final)} מיליון ₪ לאחר הפחתות ({mil(total_orig)} מיליון ₪ "
                           f"במקור), לפי חוק, מפר, סוג עיסוק, הפחתה וסטטוס משפטי, "
                           f"{first.year}–{ref_year}."),
            "dataset_kind": "rankings",
            "related_ids": ["04931a88-336c-4d95-8a13-9dc631c3e2d1",
                            "5fc5c912-4fa5-4474-93c1-326e505e22cf",
                            "422ff747-a1ee-4e8d-b515-43417f0d80d8",
                            "005fe7c5-be59-42de-91ea-0ce3cdece35c",
                            "6b991a56-c209-4b02-a52e-ba1c69091a4c"],
            "suggested_tags": ["עיצומים כספיים", "אכיפה סביבתית", "קנסות", "רגולציה",
                               "אריזות ומחזור", "המשרד להגנת הסביבה"],
            "temporal_coverage": f"{first.strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
