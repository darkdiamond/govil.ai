"""תקציב עיריית באר שבע — line-item budget (original / updated / actual).

One row per (year, account, department). Account numbers whose first two
digits are 11-15 carry income (negative amounts), 16-19 expenses; the side is
derived from the sign of each two-digit group in the data, not hard-coded.
Blank amount = not reported (not zero). The per-year resources of this dataset
(2014-2017) are column-shifted subsets of the all-years file and are ignored;
the input matches only the all-years schema, and a new year appended to it
(or a new resource with the same schema) flows through. Rows are de-duplicated
on (year, account, department) so a re-uploaded copy cannot double-count.
"""
import math

import pandas as pd

LRI, PDI = "⁦", "⁩"
TOP_DEPTS = 12
TOP_ITEMS = 12
TOP_INCOME = 10
HEAT_YEARS = 12
SIZE_EDGES = [10_000, 100_000, 1_000_000, 10_000_000]
SIZE_LABELS = ["עד 10 אלף ₪", "10 עד 100 אלף", "100 אלף עד מיליון", "מיליון עד 10 מיליון", "מעל 10 מיליון ₪"]
PAYROLL_NAMES = ("שכר קובע", "שכר קבוע", "שעות נוספות", "הפרשות סוציאליות",
                 "תוספות שאינן בשכר קובע", "עובדים זמניים")
COMPLETE_MIN, COMPLETE_MAX = 0.85, 1.15   # actual / budget range = a "complete" actual year
ACTUAL_MIN_COVERAGE = 0.5                 # share of a year's rows that report an actual


def n(v):
    return f"{int(round(v)):,}"


def mil(v):
    """Millions of NIS from NIS, one decimal."""
    return f"{LRI}{v / 1e6:,.1f}{PDI}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def mm(v):
    return round(float(v) / 1e6, 1)


def signed_pct_display(v):
    return f"{'−' if v < 0 else ''}{abs(v):.1f}%"


def _prepare(df):
    out = pd.DataFrame({
        "year": pd.to_numeric(df["שנה"].str.strip(), errors="coerce"),
        "acct": df["חשבון"].str.strip(),
        "name": df["שם חשבון"].str.strip(),
        "dept": df["מחלקה"].str.strip(),
        "orig": pd.to_numeric(df["מקורי"].str.replace(",", "", regex=False).str.strip(), errors="coerce"),
        "upd": pd.to_numeric(df["מעודכן"].str.replace(",", "", regex=False).str.strip(), errors="coerce"),
        "act": pd.to_numeric(df["ביצוע"].str.replace(",", "", regex=False).str.strip(), errors="coerce"),
    })
    out = out.dropna(subset=["year"])
    out = out[out["acct"] != ""]
    out["year"] = out["year"].astype(int)
    # Deterministic de-dup on the natural key (order-independent).
    out = out.sort_values(["year", "acct", "dept", "name", "orig", "upd", "act"],
                          kind="mergesort", na_position="first")
    out = out.drop_duplicates(["year", "acct", "dept"], keep="last").reset_index(drop=True)
    out["grp"] = out["acct"].str[:2]
    return out


def _income_groups(df):
    tot = df.groupby("grp")[["orig", "upd", "act"]].sum().sum(axis=1)
    return set(tot[tot < 0].index)


def _yearly(df, col):
    s = df.groupby("year")[col].sum(min_count=1)
    return {int(y): float(v) for y, v in s.items() if pd.notna(v) and v != 0}


def _top(series, k):
    s = series.sort_index().sort_values(ascending=False, kind="stable")
    return s.head(k)


def _cagr(v0, v1, years):
    if v0 <= 0 or years <= 0:
        return None
    return (v1 / v0) ** (1 / years) - 1


def compute(frames):
    df = _prepare(frames["budget"])
    inc_groups = _income_groups(df)
    df["income"] = df["grp"].isin(inc_groups)
    exp = df[~df["income"]]
    inc = df[df["income"]]

    e_orig, e_upd, e_act = _yearly(exp, "orig"), _yearly(exp, "upd"), _yearly(exp, "act")
    i_act = {y: -v for y, v in _yearly(inc, "act").items()}
    i_orig = {y: -v for y, v in _yearly(inc, "orig").items()}

    rows_per_year = df.groupby("year").size()
    act_rows = df[df["act"].notna()].groupby("year").size()

    def actual_ok(y):
        if y not in e_act or y not in i_act:
            return False
        if act_rows.get(y, 0) < ACTUAL_MIN_COVERAGE * rows_per_year.get(y, 1):
            return False
        base = e_upd.get(y) or e_orig.get(y)
        if base:
            return COMPLETE_MIN <= e_act[y] / base <= COMPLETE_MAX
        return True

    budget_years = sorted(e_orig)
    act_years = sorted(y for y in e_act if actual_ok(y))
    all_years = sorted(set(budget_years) | set(e_act) | set(e_upd))
    if not budget_years:
        raise ValueError("no original budget")
    y_first, y_last = budget_years[0], budget_years[-1]
    y_act = act_years[-1] if act_years else None
    upd_years = [y for y in budget_years if y in e_upd]
    missing_upd = [y for y in budget_years if y not in e_upd and (not upd_years or y < budget_years[-1])]
    only_budget_years = [y for y in budget_years if y_act is not None and y > y_act]

    # ---- chart: budget vs actual (expenses) ----
    xs = [str(y) for y in all_years]
    c_budget = {
        "x": xs,
        "orig": [mm(e_orig[y]) if y in e_orig else None for y in all_years],
        "upd": [mm(e_upd[y]) if y in e_upd else None for y in all_years],
        "act": [mm(e_act[y]) if y in act_years else None for y in all_years],
    }
    tab_budget = [{"year": str(y),
                   "orig": f"{e_orig[y] / 1e6:,.1f}" if y in e_orig else "—",
                   "upd": f"{e_upd[y] / 1e6:,.1f}" if y in e_upd else "—",
                   "act": f"{e_act[y] / 1e6:,.1f}" if y in act_years else "—"} for y in all_years]

    # ---- chart: net (income - expense) actual ----
    net = {y: i_act[y] - e_act[y] for y in act_years}
    c_net = {"x": [str(y) for y in act_years], "y": [mm(net[y]) for y in act_years],
             "pos": [bool(net[y] >= 0) for y in act_years]}
    tab_net = [{"year": str(y), "inc": f"{i_act[y] / 1e6:,.1f}", "exp": f"{e_act[y] / 1e6:,.1f}",
                "net": f"{'−' if net[y] < 0 else ''}{abs(net[y]) / 1e6:,.1f}"} for y in act_years]

    # ---- chart: revision & execution ----
    rev_years = [y for y in upd_years]
    c_exec = {
        "x": [str(y) for y in sorted(set(rev_years) | set(act_years))],
    }
    ey = sorted(set(rev_years) | set(act_years))
    c_exec["rev"] = [round((e_upd[y] / e_orig[y] - 1) * 100, 1) if y in e_upd and y in e_orig else None for y in ey]
    c_exec["exe"] = [round(e_act[y] / (e_upd.get(y) or e_orig[y]) * 100, 1)
                     if y in act_years and (e_upd.get(y) or e_orig.get(y)) else None for y in ey]
    tab_exec = [{"year": str(y),
                 "rev": ("—" if c_exec["rev"][i] is None else f"{c_exec['rev'][i]:.1f}%"),
                 "exe": ("—" if c_exec["exe"][i] is None else f"{c_exec['exe'][i]:.1f}%")}
                for i, y in enumerate(ey)]

    # ---- chart: payroll share ----
    pay_mask = exp["name"].apply(lambda s: any(k in s for k in PAYROLL_NAMES)) & ~exp["name"].str.contains("שכר דירה")
    pay = exp[pay_mask]
    pay_y = {int(y): float(v) for y, v in pay.groupby("year")["orig"].sum().items()}
    pay_years = [y for y in budget_years if y in pay_y]
    pay_share = {y: pay_y[y] / e_orig[y] * 100 for y in pay_years}
    c_pay = {"x": [str(y) for y in pay_years],
             "pay": [mm(pay_y[y]) for y in pay_years],
             "other": [mm(e_orig[y] - pay_y[y]) for y in pay_years],
             "share": [round(pay_share[y], 1) for y in pay_years]}
    tab_pay = [{"year": str(y), "pay": f"{pay_y[y] / 1e6:,.1f}",
                "other": f"{(e_orig[y] - pay_y[y]) / 1e6:,.1f}", "share": f"{pay_share[y]:.1f}%"}
               for y in pay_years]

    # ---- departments ----
    ed = exp[exp["dept"] != ""]
    dept_cov = ed.groupby("year").size() / rows_per_year.reindex(ed.groupby("year").size().index)
    exp_rows = exp.groupby("year").size()
    dept_years = [y for y in budget_years
                  if (ed[ed["year"] == y]["orig"].notna().sum() >= 0.5 * exp_rows.get(y, 1))]
    dept_orig = ed.groupby(["dept", "year"])["orig"].sum().unstack(fill_value=0)
    d_first = dept_years[0] if dept_years else None
    d_last = dept_years[-1] if dept_years else None
    top_depts = []
    c_depts = {"names": [], "first": [], "last": []}
    tab_depts = []
    c_heat = {"x": [], "y": [], "cells": [], "max": 1}
    tab_heat = []
    dept_share_last = None
    if d_last is not None and d_last in dept_orig.columns:
        last_vals = dept_orig[d_last]
        last_vals = last_vals[last_vals > 0].sort_index().sort_values(ascending=False, kind="stable")
        top_depts = list(last_vals.head(TOP_DEPTS).index)
        dept_total_last = float(last_vals.sum())
        main_item = (ed[(ed["year"] == d_last) & ed["dept"].isin(top_depts)]
                     .groupby(["dept", "name"])["orig"].sum().reset_index()
                     .sort_values(["dept", "orig", "name"], ascending=[True, False, True], kind="mergesort")
                     .drop_duplicates("dept").set_index("dept")["name"])
        first_vals = dept_orig[d_first] if d_first in dept_orig.columns else None
        c_depts = {
            "names": top_depts,
            "main": [main_item.get(d, "") for d in top_depts],
            "first": [mm(first_vals.get(d, 0)) for d in top_depts],
            "last": [mm(last_vals[d]) for d in top_depts],
            "first_year": str(d_first), "last_year": str(d_last),
        }
        tab_depts = [{"dept": d, "main": main_item.get(d, ""),
                      "first": f"{first_vals.get(d, 0) / 1e6:,.1f}",
                      "last": f"{last_vals[d] / 1e6:,.1f}",
                      "share": f"{last_vals[d] / dept_total_last * 100:.1f}%"} for d in top_depts]
        dept_share_last = (top_depts[0], float(last_vals[top_depts[0]]) / dept_total_last, main_item.get(top_depts[0], ""))
        hy = dept_years[-HEAT_YEARS:]
        cells = []
        for yi, d in enumerate(top_depts):
            for xi, y in enumerate(hy):
                v = float(dept_orig.at[d, y]) if (y in dept_orig.columns and d in dept_orig.index) else 0.0
                cells.append([xi, yi, mm(v)])
        c_heat = {"x": [str(y) for y in hy], "y": top_depts, "cells": cells,
                  "max": max([c[2] for c in cells] or [1])}

    # ---- items by name (latest budget year) ----
    ex_last = exp[exp["year"] == y_last]
    by_name = ex_last.groupby("name")["orig"].sum()
    by_name = by_name[by_name > 0]
    items_top = _top(by_name, TOP_ITEMS)
    items_total = float(by_name.sum())
    c_items = {"names": list(items_top.index), "values": [mm(v) for v in items_top.values]}
    tab_items = [{"name": k, "val": f"{v / 1e6:,.1f}", "share": f"{v / items_total * 100:.1f}%"}
                 for k, v in items_top.items()]

    inc_last = inc[inc["year"] == y_last]
    inc_name = -inc_last.groupby("name")["orig"].sum()
    inc_name = inc_name[inc_name > 0]
    inc_top = _top(inc_name, TOP_INCOME)
    inc_total = float(inc_name.sum())
    c_income = {"names": list(inc_top.index), "values": [mm(v) for v in inc_top.values]}
    tab_income = [{"name": k, "val": f"{v / 1e6:,.1f}", "share": f"{v / inc_total * 100:.1f}%"}
                  for k, v in inc_top.items()]

    # ---- size distribution of expense line items ----
    vals = ex_last["orig"]
    pos = vals[vals > 0].sort_values(ascending=False, kind="mergesort")
    zero_items = int((vals == 0).sum())
    bucket_idx = pd.cut(pos, bins=[0] + SIZE_EDGES + [float("inf")], labels=False, right=False)
    cnt = [int((bucket_idx == i).sum()) for i in range(len(SIZE_LABELS))]
    amt = [float(pos[bucket_idx == i].sum()) for i in range(len(SIZE_LABELS))]
    tot_pos = float(pos.sum())
    c_size = {"names": SIZE_LABELS, "count": cnt,
              "share": [round(a / tot_pos * 100, 1) if tot_pos else 0 for a in amt]}
    tab_size = [{"bucket": SIZE_LABELS[i], "count": n(cnt[i]), "share": f"{c_size['share'][i]:.1f}%"}
                for i in range(len(SIZE_LABELS))]
    n_items = int(len(pos))
    n80 = None
    if n_items:
        cs = pos.cumsum() / tot_pos
        n80 = int((cs < 0.8).sum()) + 1

    # ---------------- insights ----------------
    def ins_growth():
        if len(budget_years) < 3:
            return None
        v0, v1 = e_orig[y_first], e_orig[y_last]
        chg = (v1 / v0 - 1) * 100
        cg = _cagr(v0, v1, y_last - y_first)
        tail = f", {pct(abs(cg) * 100)} בממוצע לשנה" if cg is not None else ""
        word = "עלה" if chg > 0 else "ירד"
        return (f"תקציב ההוצאות המקורי {word} מ-{mil(v0)} מיליון ₪ ב-{y_first} ל-{mil(v1)} מיליון ₪ ב-{y_last} "
                f"({pct(abs(chg))} במונחים נומינליים{tail}).")

    def ins_net():
        if y_act is None:
            return None
        v = net[y_act]
        base = e_act[y_act]
        if abs(v) / base < 0.0005:
            return f"ב-{y_act} ההכנסות וההוצאות בפועל כמעט תואמות: הפער הוא {mil(abs(v))} מיליון ₪."
        word = "עלו על ההוצאות" if v > 0 else "היו נמוכות מההוצאות"
        res = "עודף" if v > 0 else "גירעון"
        return (f"ב-{y_act} ההכנסות בפועל {word} ב-{mil(abs(v))} מיליון ₪ — {res} "
                f"של {pct(abs(v) / base * 100, 2)} מהיקף ההוצאות.")

    def ins_exec():
        if y_act is None:
            return None
        base = e_upd.get(y_act) or e_orig.get(y_act)
        if not base:
            return None
        r = e_act[y_act] / base * 100
        which = "התקציב המעודכן" if y_act in e_upd else "התקציב המקורי"
        if r > 101:
            how = f"חריגה של {pct(r - 100)}"
        elif r >= 97:
            how = "ביצוע כמעט מלא"
        else:
            how = f"אי-ניצול של {pct(100 - r)}"
        return f"ב-{y_act} בוצעו {pct(r)} מ{which} בהוצאות ({how})."

    def ins_dept():
        if dept_share_last is None or dept_share_last[1] < 0.05:
            return None
        d, s, item = dept_share_last
        extra = f"; הסעיף הגדול בה לפי שם החשבון: {item}" if item else ""
        return (f"מחלקה {d} היא הגדולה ביותר בתקציב ההוצאות של {d_last}: {pct(s * 100)} "
                f"מההוצאות שמשויכות למחלקה{extra}.")

    def ins_pay():
        if len(pay_years) < 2:
            return None
        s0, s1 = pay_share[pay_years[0]], pay_share[pay_years[-1]]
        a, b = pay_years[0], pay_years[-1]
        if abs(s1 - s0) < 1.5:
            return (f"חלקן של הוצאות השכר והנלוות (לפי שמות החשבונות) יציב: {pct(s0)} ב-{a} ו-{pct(s1)} ב-{b}.")
        word = "עלה" if s1 > s0 else "ירד"
        return (f"חלקן של הוצאות השכר והנלוות (לפי שמות החשבונות) מתקציב ההוצאות {word} מ-{pct(s0)} "
                f"ב-{a} ל-{pct(s1)} ב-{b}.")

    def ins_income():
        if inc_total <= 0 or len(inc_top) == 0:
            return None
        k, v = inc_top.index[0], float(inc_top.iloc[0])
        if v / inc_total < 0.2:
            return None
        return (f"מקור ההכנסה הגדול בתקציב {y_last} הוא \"{k}\": {mil(v)} מיליון ₪, "
                f"{pct(v / inc_total * 100)} מכלל ההכנסות המתוכננות.")

    def ins_conc():
        if n_items < 100 or n80 is None:
            return None
        return (f"ב-{y_last} {n(n80)} סעיפי הוצאה מתוך {n(n_items)} ({pct(n80 / n_items * 100)}) "
                f"מרכזים 80% מתקציב ההוצאות.")

    def ins_dept_growth():
        if d_first is None or d_first == d_last or not top_depts:
            return None
        best = None
        for d in top_depts:
            v0 = float(dept_orig.at[d, d_first]) if d_first in dept_orig.columns else 0.0
            v1 = float(dept_orig.at[d, d_last])
            if v0 < 5e6:
                continue
            g = v1 / v0 - 1
            if best is None or (g, d) > (best[0], best[1]):
                best = (g, d, v0, v1)
        if best is None or best[0] < 0.5:
            return None
        g, d, v0, v1 = best
        return (f"בין הגדולות, מחלקה {d} צמחה הכי מהר: מ-{mil(v0)} מיליון ₪ ב-{d_first} "
                f"ל-{mil(v1)} מיליון ₪ ב-{d_last} (גידול של {pct(g * 100, 0)}).")

    def ins_revision():
        ys = [y for y in upd_years if y in e_orig]
        if not ys:
            return None
        y = ys[-1]
        r = (e_upd[y] / e_orig[y] - 1) * 100
        if abs(r) < 1:
            return None
        word = "הוגדל" if r > 0 else "הוקטן"
        return (f"בשנת {y} התקציב המעודכן {word} ב-{pct(abs(r))} לעומת המקורי "
                f"({mil(abs(e_upd[y] - e_orig[y]))} מיליון ₪).")

    def ins_partial():
        if not only_budget_years:
            return None
        ys = only_budget_years
        yrs = f"{ys[0]}" if len(ys) == 1 else f"{ys[0]} עד {ys[-1]}"
        return (f"הנתונים לשנים {yrs} הם תקציב בלבד — הביצוע בפועל טרם דווח, ולכן הן אינן נכללות "
                f"בניתוח הביצוע.") if len(ys) > 1 else (f"הנתונים לשנת {yrs} הם תקציב בלבד — הביצוע בפועל "
                                                          f"טרם דווח, ולכן היא אינה נכללת בניתוח הביצוע.")

    def ins_item():
        if items_total <= 0 or len(items_top) == 0:
            return None
        k, v = items_top.index[0], float(items_top.iloc[0])
        if v / items_total < 0.05:
            return None
        return (f"הסעיף הגדול ביותר בהוצאות {y_last} לפי שם החשבון (בסיכום כל המחלקות) הוא \"{k}\": "
                f"{mil(v)} מיליון ₪, {pct(v / items_total * 100)} מההוצאות.")

    rules = [("growth", ins_growth()), ("net", ins_net()), ("execution", ins_exec()),
             ("dept", ins_dept()), ("payroll", ins_pay()), ("income", ins_income()),
             ("item", ins_item()), ("concentration", ins_conc()), ("dept_growth", ins_dept_growth()),
             ("revision", ins_revision()), ("partial", ins_partial())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---------------- KPIs ----------------
    chg = (e_orig[y_last] / e_orig[y_first] - 1) * 100 if y_first != y_last else 0.0
    kpis = {
        "total": {"value": mm(e_orig[y_last]), "display": f"{e_orig[y_last] / 1e6:,.1f}", "tone": "brand"},
        "growth": {"value": round(chg, 1), "display": signed_pct_display(chg), "tone": "info"},
    }
    if y_act is not None:
        base = e_upd.get(y_act) or e_orig.get(y_act)
        r = e_act[y_act] / base * 100 if base else None
        if r is not None:
            tone = "ok" if 97 <= r <= 101 else "warn"
            kpis["exec"] = {"value": round(r, 1), "display": f"{r:.1f}%", "tone": tone}
        v = net[y_act]
        kpis["net"] = {"value": mm(v), "display": f"{'−' if v < 0 else ''}{abs(v) / 1e6:,.1f}",
                       "tone": "ok" if v >= 0 else "danger"}
    items_n = int(ex_last["acct"].nunique())
    kpis["items"] = {"value": items_n, "display": n(items_n), "tone": "brand"}
    kpi_keys = [k for k in ("total", "growth", "exec", "net") if k in kpis]
    if len(kpi_keys) < 4:
        kpi_keys.append("items")

    # ---------------- labels ----------------
    miss_txt = ""
    if missing_upd:
        miss_txt = (f" בשנים {', '.join(str(y) for y in missing_upd)} אין תקציב מעודכן במאגר — הקו מנותק."
                    if len(missing_upd) > 1 else
                    f" בשנת {missing_upd[0]} אין תקציב מעודכן במאגר — הקו מנותק.")
    no_act = [y for y in budget_years if y not in act_years and y_act is not None and y < y_act]
    labels = {
        "lede": (f"תקציב עיריית באר שבע ברמת סעיף (חשבון ומחלקה) לשנים {all_years[0]} עד {all_years[-1]}: "
                 f"תקציב מקורי, תקציב מעודכן וביצוע בפועל. תקציב ההוצאות המקורי ל-{y_last} עומד על "
                 f"{mil(e_orig[y_last])} מיליון ₪, ב-{n(items_n)} חשבונות."
                 + (f" הביצוע בפועל מדווח עד {y_act}." if y_act else "")),
        "kpi_total": f"תקציב ההוצאות המקורי {y_last} (מיליון ₪)",
        "kpi_growth": f"שינוי נומינלי בתקציב ההוצאות המקורי, {y_first} עד {y_last}",
        "kpi_exec": (f"ביצוע ההוצאות מול התקציב ב-{y_act}" if y_act else ""),
        "kpi_net": (f"עודף (גירעון בסימן מינוס) בפועל {y_act} (מיליון ₪)" if y_act else ""),
        "kpi_items": f"חשבונות הוצאה בתקציב {y_last}",
        "budget_note": ("תקציב ההוצאות הכולל בכל שנה, במיליוני ₪ במחירים שוטפים (לא צמוד למדד). "
                        "בתקציב מאוזן ההכנסות המתוכננות שוות להוצאות. ביצוע בפועל מוצג רק בשנים עם דיווח מלא."
                        + miss_txt),
        "budget_aria": f"גרף קווים: תקציב ההוצאות המקורי, המעודכן והביצוע בפועל לפי שנה, {y_first} עד {y_last}.",
        "budget_caption": "תקציב הוצאות לפי שנה, מיליוני ₪.",
        "net_note": "ההפרש בין ההכנסות להוצאות בפועל בשנים שבהן הביצוע מדווח במלואו; מעל האפס עודף, מתחתיו גירעון.",
        "net_aria": "גרף עמודות: עודף או גירעון בפועל לפי שנה, במיליוני ₪.",
        "net_caption": "הכנסות והוצאות בפועל והפרשן, מיליוני ₪.",
        "exec_note": ("עמודות: בכמה אחוזים התקציב המעודכן שונה מהמקורי. קו: הביצוע בפועל כאחוז מהתקציב המעודכן "
                      "(במקורי, כשאין מעודכן)."),
        "exec_aria": "גרף קווים: שינוי התקציב המעודכן מהמקורי וביצוע כאחוז מהתקציב, לפי שנה.",
        "exec_caption": "שינוי מעודכן מול מקורי וביצוע מול תקציב, באחוזים.",
        "pay_note": ("הוצאות שכר ונלוות בתקציב המקורי, לפי שם החשבון: שכר קובע, תוספות, שעות נוספות, "
                     "הפרשות סוציאליות ועובדים זמניים. סיווג לפי שם בלבד, ולכן קירוב."),
        "pay_aria": "גרף עמודות מוערמות: הוצאות שכר ונלוות מול שאר ההוצאות בתקציב המקורי לפי שנה.",
        "pay_caption": "הוצאות שכר ונלוות מול שאר ההוצאות, מיליוני ₪ ושיעור השכר.",
        "dept_note": (f"המחלקות הגדולות בתקציב ההוצאות של {d_last}, מול {d_first}. המאגר מפרסם קוד מחלקה בלבד, "
                      f"ללא שם; בטבלה מוצג הסעיף הגדול בכל מחלקה. סעיפים ללא מחלקה אינם נכללים."
                      if d_last else ""),
        "dept_aria": "תרשים עמודות: תקציב ההוצאות המקורי של המחלקות הגדולות בשנה הראשונה מול האחרונה.",
        "dept_caption": f"תקציב הוצאות מקורי לפי מחלקה, מיליוני ₪.",
        "heat_note": "תקציב ההוצאות המקורי (מיליוני ₪) של המחלקות הגדולות לאורך השנים; ככל שהצבע כהה יותר הסכום גבוה יותר.",
        "heat_aria": "מפת חום: תקציב ההוצאות המקורי של המחלקות הגדולות לפי שנה.",
        "items_note": f"סעיפי ההוצאה הגדולים ב-{y_last}, לפי שם החשבון ובסיכום כל המחלקות.",
        "items_aria": f"תרשים עמודות: סעיפי ההוצאה הגדולים בתקציב {y_last}, מיליוני ₪.",
        "items_caption": f"סעיפי הוצאה גדולים {y_last}, מיליוני ₪ ושיעור מההוצאות.",
        "income_note": f"מקורות ההכנסה המתוכננים הגדולים ב-{y_last}, לפי שם החשבון.",
        "income_aria": f"תרשים עמודות: מקורות ההכנסה הגדולים בתקציב {y_last}, מיליוני ₪.",
        "income_caption": f"מקורות הכנסה {y_last}, מיליוני ₪ ושיעור מההכנסות.",
        "size_note": (f"כמה סעיפי הוצאה יש בכל טווח גודל ב-{y_last}, ואיזה שיעור מהתקציב הם מחזיקים."
                      + (f" {n(zero_items)} סעיפים עם תקציב אפס אינם נכללים." if zero_items else "")),
        "size_aria": "תרשים עמודות וקו: מספר סעיפי ההוצאה ושיעור התקציב לפי טווח גודל.",
        "size_caption": "סעיפי הוצאה לפי טווח גודל ושיעור התקציב.",
    }
    tables = {"budget": tab_budget, "net": tab_net, "exec": tab_exec, "pay": tab_pay,
              "depts": tab_depts, "lines": tab_items, "income": tab_income, "size": tab_size}
    charts = {"budget": c_budget, "net": c_net, "exec": c_exec, "pay": c_pay, "depts": c_depts,
              "heat": c_heat, "lines": c_items, "income": c_income, "size": c_size}
    flags = {"has_net": bool(act_years), "has_exec": bool(ey), "has_depts": bool(top_depts),
             "has_pay": len(pay_years) >= 2}

    return {
        "agent_data": {
            "summary_he": (f"תקציב עיריית באר שבע ברמת סעיף לשנים {all_years[0]} עד {all_years[-1]}: תקציב הוצאות מקורי של "
                           f"{e_orig[y_last] / 1e6:,.1f} מיליון ₪ ב-{y_last}, תקציב מעודכן וביצוע בפועל לפי חשבון ומחלקה."),
            "dataset_kind": "timeseries",
            "related_ids": ["f4a5cdab-82b2-48ad-9d95-424a035cfed8"],
            "suggested_tags": ["תקציב", "עירייה", "באר שבע", "רשויות מקומיות", "כספים"],
            "temporal_coverage": f"{all_years[0]}/{all_years[-1]}",
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "kpi_keys": kpi_keys,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
