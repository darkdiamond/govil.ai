"""ריביות פיקדונות "חיסכון לכל ילד" — bank rates, published every few days.

Rolling window (the banks report up to two years back): one row per
publication date × bank × product, where a product is the child's age
bracket × savings plan (with/without exit points every 5 years; a
one-time-sum plan for 18+) and three rates: fixed unlinked, fixed
CPI-linked, and a variable rate quoted as a spread from prime.

"Flagship" = a newborn (age 0–1) in the no-exit plan: the full 18-year
product every parent chooses on day one. "Now" is the latest publication
date in the data.
"""
import pandas as pd

RATES = [("FIXEDWITHOUTLINKAGEVAL", "fixed", "קבועה לא צמודה"),
         ("FIXEDLINKEDCONSUMERPRICEINDVAL", "linked", "קבועה צמודה למדד"),
         ("VARIABLESPREAD", "spread", "משתנה (מרווח מהפריים)")]
FLAG_AGE = "0 - 1"
NO_EXIT = "הפקדה ללא תחנות יציאה"
EXIT5 = "הפקדה עם אפשרות לתחנות יציאה כל 5 שנים"
ADULT = "צבירת ריבית על סכום חד פעמי"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def pct(v):
    return f"{v:.2f}%"


def pp(v):
    return f"{abs(v):.2f}"


def _age_key(a):
    head = a.split("-")[0].strip().rstrip("+")
    try:
        return int(head)
    except ValueError:
        return 99


def _prepare(df):
    out = pd.DataFrame({
        "d": pd.to_datetime(df["INTERESTSDATE"], format="%d/%m/%Y", errors="coerce"),
        "bank": df["BANK"].str.strip(),
        "age": df["AGE"].str.strip(),
        "plan": df["SAVINGSPLAN"].str.strip(),
        "period": df["SAVINGSPERIOD"].str.strip(),
    })
    for src, key, _ in RATES:
        out[key] = pd.to_numeric(df[src], errors="coerce")
    out = out.dropna(subset=["d", "fixed"])
    out = out[out["bank"] != ""]
    return out.sort_values(["d", "bank", "plan", "age", "period"], kind="stable").reset_index(drop=True)


def _flagship(df):
    f = df[(df["age"] == FLAG_AGE) & (df["plan"] == NO_EXIT)]
    # One value per date × bank (defensive against duplicated rows).
    return f.groupby(["d", "bank"], as_index=False)[["fixed", "linked", "spread"]].mean()


def insight_best(flag_now):
    if len(flag_now) < 3:
        return None
    s = flag_now.sort_values(["fixed", "bank"], ascending=[False, True])
    top, low = s.iloc[0], s.iloc[-1]
    ties = s[s["fixed"] == top["fixed"]]["bank"].tolist()
    lead = " ו".join(ties) if len(ties) > 1 else top["bank"]
    return (f"לתינוק שנולד היום (מסלול ללא תחנות יציאה, 18 שנים) הריבית הקבועה הלא צמודה "
            f"הגבוהה ביותר היא ב{lead}: {pct(top['fixed'])}, לעומת {pct(low['fixed'])} "
            f"ב{low['bank']} — פער של {pp(top['fixed'] - low['fixed'])} נקודות אחוז.")


def insight_trend(flag, d0, d1):
    a = flag[flag["d"] == d0].set_index("bank")["fixed"]
    b = flag[flag["d"] == d1].set_index("bank")["fixed"]
    both = a.index.intersection(b.index)
    if len(both) < 3 or d0 == d1:
        return None
    ma, mb = a[both].mean(), b[both].mean()
    up = int((b[both] > a[both]).sum())
    down = int((b[both] < a[both]).sum())
    if abs(mb - ma) < 0.05:
        head = f"הריבית הממוצעת במסלול הדגל כמעט לא השתנתה מאז {d_he(d0)} ({pct(mb)})"
    else:
        word = "עלתה" if mb > ma else "ירדה"
        head = (f"מאז {d_he(d0)} {word} הריבית הממוצעת במסלול הדגל מ-{pct(ma)} ל-{pct(mb)}")
    return f"{head}; {_banks_did(down, 'הוריד', 'הורידו')} {_banks_did(up, 'העלה', 'העלו', conj=True)} אותה."


def _banks_did(n, singular, plural, conj=False):
    """Hebrew count + verb agreement: 'אף בנק לא הוריד' / 'בנק אחד הוריד' / '3 בנקים הורידו'."""
    if n == 0:
        text = f"אף בנק לא {singular}"
    elif n == 1:
        text = f"בנק אחד {singular}"
    else:
        text = f"{n} בנקים {plural}"
    if conj:
        return ("ו-" if text[0].isdigit() else "ו") + text
    return text + " את הריבית"


def insight_exit(now):
    a = now[now["plan"] == NO_EXIT].groupby(["bank", "age"])["fixed"].mean()
    b = now[now["plan"] == EXIT5].groupby(["bank", "age"])["fixed"].mean()
    both = a.index.intersection(b.index)
    if len(both) < 10:
        return None
    gap = float((a[both] - b[both]).mean())
    if abs(gap) < 0.02:
        return "אפשרות למשוך את הכסף כל 5 שנים כמעט אינה פוגעת בריבית הקבועה הלא צמודה."
    worse = "נמוכה" if gap > 0 else "גבוהה"
    return (f"מסלול עם תחנות יציאה כל 5 שנים מציע ריבית קבועה לא צמודה {worse} בממוצע "
            f"ב-{pp(gap)} נקודות אחוז מהמסלול ללא תחנות יציאה, באותו גיל ובאותו בנק.")


def insight_twins(flag_now_all):
    """Banks whose entire rate table is identical today (e.g. one banking group)."""
    sig = (flag_now_all.sort_values(["plan", "age", "period"], kind="stable")
           .groupby("bank")[["fixed", "linked", "spread"]]
           .apply(lambda g: tuple(g.round(4).to_numpy().ravel())))
    groups = {}
    for bank, s in sig.items():
        groups.setdefault(s, []).append(bank)
    twins = sorted((sorted(v) for v in groups.values() if len(v) > 1), key=lambda v: (-len(v), v))
    if not twins:
        return None
    g = twins[0]
    return (f"{len(g)} בנקים מציעים היום טבלת ריביות זהה לחלוטין בכל המסלולים והגילים: "
            f"{', '.join(g)}.")


def insight_changes(changes, days):
    if not changes:
        return None
    s = sorted(changes.items(), key=lambda t: (-t[1], t[0]))
    top_bank, top_n = s[0]
    still = [b for b, n in s if n == 0]
    tail = (f"; {', '.join(still)} לא שינו אותה כלל" if still else "")
    return (f"בתקופה שבמאגר ({days} ימים) שינה {top_bank} את ריבית מסלול הדגל "
            f"{top_n} פעמים — יותר מכל בנק אחר{tail}.")


def insight_age(now):
    f = now[now["plan"] == NO_EXIT]
    med = f.groupby("age")["fixed"].median()
    ages = sorted(med.index, key=_age_key)
    if len(ages) < 5:
        return None
    young, old = ages[0], ages[-1]
    diff = med[young] - med[old]
    if abs(diff) < 0.05:
        return None
    word = "גבוהה" if diff > 0 else "נמוכה"
    return (f"ככל שהילד צעיר יותר — וההפקדה ארוכה יותר — הריבית {word} יותר: הריבית "
            f"החציונית לגיל {young} היא {pct(med[young])}, ולגיל {old} {pct(med[old])}.")


def compute(frames):
    df = _prepare(frames["rates"])
    d1, d0 = df["d"].max(), df["d"].min()
    now = df[df["d"] == d1]
    flag = _flagship(df)
    flag_now = flag[flag["d"] == d1].sort_values(["fixed", "bank"], ascending=[False, True])
    banks = sorted(df["bank"].unique())

    # Rate changes of the flagship fixed rate per bank across the window.
    changes = {}
    for b, g in flag.sort_values("d").groupby("bank"):
        changes[b] = int((g["fixed"].diff().fillna(0) != 0).sum())

    # Charts ------------------------------------------------------------
    by_bank = {
        "banks": flag_now["bank"].tolist(),
        "series": [{"name": label, "data": [round(float(v), 2) for v in flag_now[key]]}
                   for _, key, label in RATES],
    }
    dates = sorted(flag["d"].unique())
    piv = flag.pivot_table(index="d", columns="bank", values="fixed")
    trend = {
        "x": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates],
        "series": [{"name": b, "data": [None if pd.isna(v) else round(float(v), 2)
                                        for v in piv.reindex(dates)[b]]}
                   for b in piv.columns],
    }
    spread_ts = {
        "x": trend["x"],
        "max": [round(float(v), 2) for v in piv.reindex(dates).max(axis=1)],
        "mean": [round(float(v), 2) for v in piv.reindex(dates).mean(axis=1)],
        "min": [round(float(v), 2) for v in piv.reindex(dates).min(axis=1)],
    }

    noexit_now = now[now["plan"] == NO_EXIT]
    age_stats = noexit_now.groupby("age")["fixed"].agg(["min", "median", "max"])
    ages = sorted(age_stats.index, key=_age_key)
    by_age = {"x": ages,
              "min": [round(float(age_stats.loc[a, "min"]), 2) for a in ages],
              "median": [round(float(age_stats.loc[a, "median"]), 2) for a in ages],
              "max": [round(float(age_stats.loc[a, "max"]), 2) for a in ages]}

    a = now[now["plan"] == NO_EXIT].groupby(["bank", "age"])["fixed"].mean()
    b = now[now["plan"] == EXIT5].groupby(["bank", "age"])["fixed"].mean()
    both = a.index.intersection(b.index)
    gap = (a[both] - b[both]).groupby(level=0).mean().reindex(banks).dropna()
    gap = gap.sort_index().sort_values(ascending=False, kind="stable")
    exit_gap = {"x": gap.index.tolist(), "y": [round(float(v), 2) for v in gap]}

    adult = now[now["plan"] == ADULT]
    periods = sorted(adult["period"].unique(),
                     key=lambda p: (0 if p.endswith("M") else 1, _age_key(p.replace("Y", "").replace("M", ""))))
    adult_piv = adult.pivot_table(index="bank", columns="period", values="fixed").reindex(banks)
    adult_chart = {"banks": banks,
                   "series": [{"name": p, "data": [None if pd.isna(v) else round(float(v), 2)
                                                   for v in adult_piv.get(p, pd.Series(dtype=float))]}
                              for p in periods]}

    heat_banks = flag_now["bank"].tolist()
    hp = noexit_now.groupby(["bank", "age"])["fixed"].mean()
    cells = [[ages.index(ag), heat_banks.index(bk), round(float(v), 2)]
             for (bk, ag), v in hp.items() if bk in heat_banks and ag in ages]
    heat = {"ages": ages, "banks": heat_banks, "cells": cells,
            "min": round(float(hp.min()), 2), "max": round(float(hp.max()), 2)}

    ch = sorted(changes.items(), key=lambda t: (-t[1], t[0]))
    changes_chart = {"x": [b for b, _ in ch], "y": [n for _, n in ch]}

    # Insights ----------------------------------------------------------
    days = int((d1 - d0).days)
    rules = [
        ("best", insight_best(flag_now)),
        ("trend", insight_trend(flag, d0, d1)),
        ("age", insight_age(now)),
        ("exit", insight_exit(now)),
        ("twins", insight_twins(now)),
        ("changes", insight_changes(changes, days)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    best = flag_now.iloc[0] if len(flag_now) else None
    # Median flagship rate now vs at the start of the window: for savers a
    # rise is good (green), a fall of 0.05pp or more calls for caution.
    med_now = float(flag_now["fixed"].median()) if len(flag_now) else None
    start = flag[flag["d"] == d0]["fixed"]
    med_start = float(start.median()) if len(start) and d0 != d1 else None
    if med_now is None or med_start is None or abs(med_now - med_start) < 0.05:
        median_tone = "brand"
    else:
        median_tone = "ok" if med_now > med_start else "warn"
    kpis = {
        # The best available flagship rate is the good news for savers.
        "best": {"value": None if best is None else float(best["fixed"]),
                 "display": "—" if best is None else pct(best["fixed"]), "tone": "ok"},
        "best_bank": {"value": None if best is None else best["bank"],
                      "display": "—" if best is None else best["bank"]},
        "median": {"value": med_now, "display": pct(med_now) if med_now is not None else "—",
                   "tone": median_tone},
        "banks": {"value": len(banks), "display": f"{len(banks)}", "tone": "brand"},
        "as_of": {"value": d1.strftime("%Y-%m-%d"),
                  "display": f"{d1.day}.{d1.month}.{d1.year}", "tone": "brand"},
    }
    median_kpi_label = ("ריבית חציונית בין הבנקים"
                        + (f" (בתחילת התקופה: {pct(med_start)})" if med_start is not None else ""))

    labels = {
        "median_kpi": median_kpi_label,
        "lede": (f"ריביות פיקדונות \"חיסכון לכל ילד\" ב-{len(banks)} בנקים, כפי שפורסמו "
                 f"ב-{len(dates)} מועדים מ-{d_he(d0)} ועד {d_he(d1)}. מסלול הדגל בעמוד: "
                 f"תינוק בגיל {FLAG_AGE}, הפקדה ללא תחנות יציאה."),
        "banks_aria": f"תרשים עמודות: שלוש הריביות במסלול הדגל בכל אחד מ-{len(banks)} הבנקים, נכון ל-{d_he(d1)}.",
        "trend_aria": f"גרף קווים: הריבית הקבועה הלא צמודה במסלול הדגל לפי בנק, {len(dates)} מועדי פרסום.",
        "range_aria": "גרף: הריבית הגבוהה, הממוצעת והנמוכה בין הבנקים במסלול הדגל לאורך זמן.",
        "age_aria": f"גרף: הריבית הקבועה הלא צמודה לפי גיל הילד — נמוכה, חציונית וגבוהה בין הבנקים.",
        "exit_aria": "תרשים עמודות: כמה נמוכה יותר הריבית במסלול עם תחנות יציאה, לפי בנק.",
        "adult_aria": "תרשים עמודות: ריבית קבועה לא צמודה לסכום חד-פעמי מגיל 18, לפי בנק ותקופה.",
        "changes_aria": "תרשים עמודות: מספר השינויים בריבית מסלול הדגל לפי בנק בתקופה שבמאגר.",
        "heat_aria": "מפת חום: הריבית הקבועה הלא צמודה לפי בנק וגיל הילד, מסלול ללא תחנות יציאה.",
    }

    tables = {
        "banks": [{"bank": r["bank"], "fixed": f"{r['fixed']:.2f}", "linked": f"{r['linked']:.2f}",
                   "spread": f"{r['spread']:.2f}"} for _, r in flag_now.iterrows()],
        "age": [{"age": a_, "min": f"{mn:.2f}", "med": f"{md:.2f}", "max": f"{mx:.2f}"}
                for a_, mn, md, mx in zip(by_age["x"], by_age["min"], by_age["median"], by_age["max"])],
        "exit": [{"bank": b_, "gap": f"{g:.2f}"} for b_, g in zip(exit_gap["x"], exit_gap["y"])],
        "adult": [{"bank": bk, "vals": ["—" if pd.isna(adult_piv.loc[bk].get(p)) else f"{adult_piv.loc[bk].get(p):.2f}"
                                        for p in periods]} for bk in banks],
        "adult_periods": periods,
        "changes": [{"bank": b_, "n": f"{n}"} for b_, n in ch],
    }

    return {
        "agent_data": {
            "summary_he": (f"ריבית חשכ\"ל — ריביות \"חיסכון לכל ילד\" ב-{len(banks)} בנקים, עד {d_he(d1)}: "
                           f"במסלול הדגל הריבית הקבועה הלא צמודה נעה בין "
                           f"{pct(flag_now['fixed'].min())} ל-{pct(flag_now['fixed'].max())}."),
            "dataset_kind": "rankings",
            "suggested_tags": ["חיסכון לכל ילד", "ריביות", "בנקים", "ביטוח לאומי"],
            "temporal_coverage": f"{d0.strftime('%Y-%m-%d')}/{d1.strftime('%Y-%m-%d')}",
        },
        "kpis": kpis,
        "charts": {"banks": by_bank, "trend": trend, "range": spread_ts, "age": by_age,
                   "exit": exit_gap, "adult": adult_chart, "changes": changes_chart, "heat": heat},
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
