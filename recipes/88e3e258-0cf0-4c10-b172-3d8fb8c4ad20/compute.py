"""בטיחות ברכבת — railway safety events by year and main classification.

One row per year × main classification (sivug_rashi) with the number of
events. A classification that has no row in a year is counted as zero (the
source omits zero rows); the page says so.

The story the page must not get wrong: the big fall in yearly totals after
the first years is carried almost entirely by two classifications — "לא ידוע"
(unknown), which stops appearing at some point, and "פריקורסר" (precursor
events), which drops by an order of magnitude in the same transition. So the
page decomposes the total into those two and the rest, and the trend insight
says how much of the fall they account for, instead of headlining a raw
"−73%".

Growth: one new year of rows per update. Year axes stay short for decades;
the category axis is capped (TOP_N + a "שאר הסיווגים" bucket). A latest year
far below the recent norm is flagged partial and kept out of comparisons.

Victims are never identified — the data holds only counts, and the page
reports counts only.
"""
import pandas as pd

UNKNOWN = "לא ידוע"
PRECURSOR = "פריקורסר"
SUICIDE = "התאבדות"
OTHER_BUCKET = "שאר הסיווגים"
TOP_N = 12          # category bars (mobile-friendly)
HEAT_N = 20         # heatmap rows
TREND_N = 5         # lines in the per-category trend chart
WINDOW = 3          # years per comparison window (recent vs previous)
PARTIAL_RATIO = 0.5
STABLE_PCT = 5.0    # |year-over-year change| below this reads as stable
MOVER_MIN_ABS = 1.5     # avg events/year difference to call a category a mover
MOVER_MIN_REL = 0.25    # and at least this relative change


def _n(v):
    return f"{int(round(v)):,}"


def _signed_pct(p):
    r = round(p)
    if r == 0:
        return "ללא שינוי"
    return ("+" if r > 0 else "−") + f"{abs(r)}%"


def _avg(v):
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _prepare(df):
    out = pd.DataFrame({
        "y": pd.to_numeric(df["shana"].str.strip(), errors="coerce"),
        "cat": df["sivug_rashi"].str.strip(),
        "n": pd.to_numeric(df["sivug_rashi_count"].str.replace(",", "").str.strip(),
                           errors="coerce"),
    }).dropna(subset=["y", "n"])
    out = out[(out["cat"] != "") & (out["n"] >= 0)]
    out["y"] = out["y"].astype(int)
    return out


def compute(frames):
    df = _prepare(frames["main"])
    piv = (df.pivot_table(index="y", columns="cat", values="n", aggfunc="sum")
             .fillna(0).sort_index())
    years_all = list(range(int(piv.index.min()), int(piv.index.max()) + 1))
    piv = piv.reindex(years_all, fill_value=0)
    piv = piv[sorted(piv.columns)]
    tot = piv.sum(axis=1)

    # Partial latest year: far below the median of the years before it.
    prior = tot.iloc[-4:-1]
    partial = bool(len(prior) >= 2 and tot.iloc[-1] < PARTIAL_RATIO * prior.median())
    cy = piv.iloc[:-1] if partial else piv   # complete years
    ctot = cy.sum(axis=1)
    y0, y1 = int(cy.index[0]), int(cy.index[-1])
    last_year = int(piv.index[-1])

    cat_tot = piv.sum(axis=0)
    cat_order = sorted(cat_tot.index, key=lambda c: (-cat_tot[c], c))
    grand = float(tot.sum())

    unk = piv[UNKNOWN] if UNKNOWN in piv.columns else pd.Series(0.0, index=piv.index)
    pre = piv[PRECURSOR] if PRECURSOR in piv.columns else pd.Series(0.0, index=piv.index)
    rest = tot - unk - pre

    # ---- charts ------------------------------------------------------
    decomp = {"x": [str(y) for y in piv.index],
              "unknown": [int(v) for v in unk], "precursor": [int(v) for v in pre],
              "rest": [int(v) for v in rest], "total": [int(v) for v in tot]}

    top = cat_order[:TOP_N + 1] if len(cat_order) == TOP_N + 1 else cat_order[:TOP_N]
    cats = {"x": top, "y": [int(cat_tot[c]) for c in top]}
    if len(cat_order) > TOP_N + 1:   # a bucket of one is just that category
        cats["x"] = cats["x"] + [OTHER_BUCKET]
        cats["y"] = cats["y"] + [int(sum(cat_tot[c] for c in cat_order[TOP_N:]))]

    heat_cats = cat_order[:HEAT_N]
    heat = {"years": [str(y) for y in piv.index], "cats": heat_cats,
            "cells": [[i, j, int(piv.loc[y, c])]
                      for i, y in enumerate(piv.index) for j, c in enumerate(heat_cats)],
            "max": int(piv[heat_cats].values.max()) if heat_cats else 1}

    # Trend lines: the biggest classifications that are real event types
    # (unknown is a reporting artefact; it gets its own series above).
    trend_cats = [c for c in cat_order if c != UNKNOWN][:TREND_N]
    trend = {"x": [str(y) for y in piv.index],
             "series": [{"name": c, "data": [int(v) for v in piv[c]]} for c in trend_cats]}

    # Recent window vs the window before it (complete years only).
    movers_rows = []
    rec = prv = None
    if len(cy) >= 2 * WINDOW:
        rec = cy.iloc[-WINDOW:]
        prv = cy.iloc[-2 * WINDOW:-WINDOW]
        for c in cat_order:
            if c == UNKNOWN:
                continue
            a, b = float(prv[c].mean()), float(rec[c].mean())
            movers_rows.append({"cat": c, "before": round(a, 2), "after": round(b, 2),
                                "delta": round(b - a, 2)})
    movers_rows = [r for r in movers_rows if r["before"] > 0 or r["after"] > 0]
    movers_rows.sort(key=lambda r: (-abs(r["delta"]), r["cat"]))
    dumb = movers_rows[:TOP_N]
    dumb.sort(key=lambda r: (-r["after"], r["cat"]))
    win_labels = None
    if rec is not None:
        win_labels = {"prev": f"{int(prv.index[0])}–{int(prv.index[-1])}",
                      "rec": f"{int(rec.index[0])}–{int(rec.index[-1])}"}
    dumbbell = {"x": [r["cat"] for r in dumb], "before": [r["before"] for r in dumb],
                "after": [r["after"] for r in dumb]}

    # Share of the year's CLASSIFIED events (unknown excluded from the
    # denominator, so the early years are not deflated by it), complete years.
    known = ctot - (cy[UNKNOWN] if UNKNOWN in cy.columns else 0)
    share = {"x": [str(y) for y in cy.index],
             "series": [{"name": c, "data": [round(float(cy.loc[y, c]) / float(known[y]) * 100, 1)
                                             if known[y] else None for y in cy.index]}
                        for c in trend_cats[:3]]}

    # ---- insights ------------------------------------------------------
    def ins_trend():
        if len(cy) < 3:
            return None
        a, b = float(ctot.iloc[0]), float(ctot.iloc[-1])
        if a <= 0:
            return None
        ch = (b - a) / a * 100
        if abs(ch) < STABLE_PCT:
            return f"סך האירועים ב-{y1} ({_n(b)}) דומה לזה של {y0} ({_n(a)})."
        s = (f"סך האירועים {'ירד' if ch < 0 else 'עלה'} מ-{_n(a)} ב-{y0} ל-{_n(b)} ב-{y1} "
             f"({_signed_pct(ch)})")
        drop = a - b
        two = (float(unk.loc[y0] + pre.loc[y0]) - float(unk.loc[y1] + pre.loc[y1]))
        if drop > 0 and two / drop >= 0.5:
            s += (f", אך {min(two / drop, 1) * 100:.0f}% מהירידה נובעים משני סיווגים בלבד — "
                  f"\"{UNKNOWN}\" ו\"{PRECURSOR}\". בשאר הסיווגים יחד נרשמו "
                  f"{_n(rest.loc[y0])} אירועים ב-{y0} ו-{_n(rest.loc[y1])} ב-{y1}.")
        else:
            s += "."
        return s

    def ins_unknown():
        if UNKNOWN not in piv.columns:
            return None
        has = piv.index[piv[UNKNOWN] > 0]
        if len(has) == 0 or int(has.max()) == last_year:
            return None
        lu = int(has.max())
        return (f"הסיווג \"{UNKNOWN}\" מופיע עד {lu} בלבד ({_n(piv[UNKNOWN].sum())} אירועים, "
                f"{float(piv.loc[has, UNKNOWN].sum() / tot.loc[has].sum()) * 100:.0f}% מהאירועים באותן שנים) "
                f"ונעלם מ-{lu + 1} — שינוי בסיווג, ולכן השוואה בין השנים שלפני ואחרי "
                f"{lu + 1} אינה השוואה של אותו דבר.")

    def ins_yoy():
        if len(cy) < 2:
            return None
        a, b = float(ctot.iloc[-2]), float(ctot.iloc[-1])
        if a <= 0:
            return None
        ch = (b - a) / a * 100
        word = ("דומה לשנה הקודמת" if abs(ch) < STABLE_PCT else
                f"{'עלייה' if ch > 0 else 'ירידה'} של {abs(ch):.0f}% לעומת {int(cy.index[-2])}")
        return f"ב-{y1} נרשמו {_n(b)} אירועים בטיחותיים — {word} ({_n(a)})."

    def ins_leader():
        row = cy.loc[y1]
        row = row[[c for c in row.index if c != UNKNOWN]]
        if row.sum() <= 0:
            return None
        order = sorted(row.index, key=lambda c: (-row[c], c))
        c1, c2 = order[0], order[1] if len(order) > 1 else None
        s = (f"ב-{y1} הסיווג הנפוץ היה \"{c1}\" — {_n(row[c1])} אירועים "
             f"({row[c1] / ctot[y1] * 100:.0f}% מהשנה)")
        if c2 and row[c2] > 0:
            s += f", ואחריו \"{c2}\" ({_n(row[c2])})"
        return s + "."

    def ins_movers():
        if not movers_rows:
            return None
        ok = [r for r in movers_rows if r["cat"] != UNKNOWN and abs(r["delta"]) >= MOVER_MIN_ABS
              and abs(r["delta"]) >= MOVER_MIN_REL * max(r["before"], r["after"])]
        up = sorted([r for r in ok if r["delta"] > 0], key=lambda r: (-r["delta"], r["cat"]))
        dn = sorted([r for r in ok if r["delta"] < 0], key=lambda r: (r["delta"], r["cat"]))
        parts = []
        if dn:
            r = dn[0]
            parts.append(f"\"{r['cat']}\" ירד מממוצע של {_avg(r['before'])} ל-{_avg(r['after'])} בשנה")
        if up:
            r = up[0]
            parts.append(f"\"{r['cat']}\" עלה מ-{_avg(r['before'])} ל-{_avg(r['after'])} בשנה")
        if not parts:
            return None
        return (f"בהשוואת {win_labels['rec']} ל-{win_labels['prev']}: " + "; ".join(parts) + ".")

    def ins_record():
        if len(cy) < 4:
            return None
        hist = cy.iloc[:-1]
        cur = cy.iloc[-1]
        hits = [c for c in cy.columns if c != UNKNOWN and cur[c] >= 3 and cur[c] > hist[c].max()]
        if not hits:
            return None
        hits.sort(key=lambda c: (-cur[c], c))
        c = hits[0]
        return (f"ב-{y1} נרשמו {_n(cur[c])} אירועים בסיווג \"{c}\" — המספר הגבוה ביותר בסיווג זה "
                f"מאז {y0} (השיא הקודם: {_n(hist[c].max())}).")

    def ins_suicide():
        if SUICIDE not in cy.columns:
            return None
        s = cy[SUICIDE]
        if s.sum() <= 0 or known[y1] <= 0 or known[y0] <= 0:
            return None
        a, b = float(s.iloc[0] / known[y0]), float(s.iloc[-1] / known[y1])
        if b - a < 0.05:
            return None
        rose = float(s.iloc[-1]) >= 1.25 * float(s.iloc[0])
        why = ("הסיבה כפולה: מספר המקרים עלה, ושאר הסיווגים הצטמצמו" if rose else
               "הסיבה העיקרית היא ששאר הסיווגים הצטמצמו, לא עלייה במספר המקרים")
        return (f"משקלם של מקרי ההתאבדות בכלל האירועים המסווגים גדל: {b * 100:.0f}% מהם ב-{y1}, "
                f"לעומת {a * 100:.0f}% ב-{y0}. {why} "
                f"({_n(s.iloc[0])} מקרים ב-{y0}, {_n(s.iloc[-1])} ב-{y1}).")

    trend_text = ins_trend()
    reclass = bool(trend_text and "נובעים משני סיווגים" in trend_text)
    rules = [("trend", trend_text), ("unknown", ins_unknown()), ("yoy", ins_yoy()),
             ("leader", ins_leader()), ("movers", ins_movers()), ("record", ins_record()),
             ("suicide_share", ins_suicide())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs ------------------------------------------------------------
    last = float(ctot.iloc[-1])
    if len(cy) >= 2 and ctot.iloc[-2] > 0:
        ch = (last - float(ctot.iloc[-2])) / float(ctot.iloc[-2]) * 100
        # Fewer safety events is good; with counts this small a rise is a
        # caution, not an alarm.
        tone = "brand" if abs(ch) < STABLE_PCT else ("warn" if ch > 0 else "ok")
        r = round(ch)
        chg_disp = "0%" if r == 0 else ("+" if r > 0 else "−") + f"{abs(r)}%"
        chg = {"value": round(ch, 1), "display": chg_disp, "tone": tone}
    else:
        chg = {"value": 0, "display": "—", "tone": "brand"}
    kpis = {
        "last": {"value": int(last), "display": _n(last), "tone": chg["tone"]},
        "change": chg,
        "total": {"value": int(grand), "display": _n(grand), "tone": "brand"},
        "cats": {"value": len(cat_order), "display": str(len(cat_order)), "tone": "brand"},
    }

    span = f"{years_all[0]}–{years_all[-1]}"
    prev_year = int(cy.index[-2]) if len(cy) >= 2 else y1
    partial_note = f" נתוני {last_year} חלקיים ואינם נכללים בהשוואות." if partial else ""
    labels = {
        "span": span, "y1": str(y1), "prev_year": str(prev_year),
        "lede": (f"אירועים בטיחותיים ברכבת לפי שנה וסיווג ראשי, {span}: {_n(grand)} אירועים "
                 f"ב-{len(cat_order)} סיווגים. שנה שבה סיווג אינו מופיע נספרת כאפס.{partial_note}"),
        "decomp_aria": f"תרשים עמודות מוערמות: אירועים בכל שנה, {span}, לפי \"{UNKNOWN}\", \"{PRECURSOR}\" ושאר הסיווגים.",
        "cats_aria": f"תרשים עמודות: סך האירועים לפי סיווג ראשי, {span}.",
        "trend_aria": f"גרף קווים: {len(trend_cats)} הסיווגים הגדולים לפי שנה, {span}.",
        "heat_aria": f"מפת חום: מספר האירועים בכל שנה ובכל סיווג, {span}.",
        "heat_note": (f" מוצגים {HEAT_N} הסיווגים הגדולים מתוך {len(cat_order)}."
                      if len(cat_order) > HEAT_N else ""),
        "dumb_aria": (f"תרשים: ממוצע אירועים בשנה לפי סיווג, {win_labels['rec']} מול {win_labels['prev']}."
                      if win_labels else ""),
        "share_aria": f"גרף קווים: חלקם של {len(share['series'])} הסיווגים הגדולים מהאירועים המסווגים בכל שנה.",
        "win_prev": win_labels["prev"] if win_labels else "",
        "win_rec": win_labels["rec"] if win_labels else "",
        "decomp_lede": (f"ב-{y0} היו \"{UNKNOWN}\" ו\"{PRECURSOR}\" יחד {_n(unk.loc[y0] + pre.loc[y0])} "
                        f"מתוך {_n(ctot.loc[y0])} אירועים; ב-{y1} — {_n(unk.loc[y1] + pre.loc[y1])} "
                        f"מתוך {_n(ctot.loc[y1])}."),
        "cats_lede": (f"\"{cat_order[0]}\" הוא הסיווג הגדול ביותר בכל התקופה: {_n(cat_tot[cat_order[0]])} "
                      f"אירועים, {cat_tot[cat_order[0]] / grand * 100:.0f}% מהסך."),
    }

    tables = {
        "decomp": [{"y": x, "unknown": a, "precursor": b, "rest": c, "total": t}
                   for x, a, b, c, t in zip(decomp["x"], decomp["unknown"], decomp["precursor"],
                                            decomp["rest"], decomp["total"])],
        "cats": [{"c": c, "n": f"{v:,}"} for c, v in zip(cats["x"], cats["y"])],
        "trend_head": trend_cats,
        "trend": [{"y": x, "v": [s["data"][i] for s in trend["series"]]}
                  for i, x in enumerate(trend["x"])],
        "dumb": [{"c": r["cat"], "before": _avg(r["before"]), "after": _avg(r["after"])} for r in dumb],
        "share_head": [s["name"] for s in share["series"]],
        "share": [{"y": x, "v": ["—" if s["data"][i] is None else f"{s['data'][i]:.1f}"
                                 for s in share["series"]]}
                  for i, x in enumerate(share["x"])],
    }

    return {
        "agent_data": {
            "summary_he": (f"אירועים בטיחותיים ברכבת לפי שנה וסיווג ראשי, {span}: {_n(grand)} אירועים; "
                           f"ב-{y1} נרשמו {_n(last)}. רוב הירידה מאז השנים הראשונות נובעת משינויי סיווג "
                           f"ומירידה באירועי \"{PRECURSOR}\"."
                           if reclass else
                           f"אירועים בטיחותיים ברכבת לפי שנה וסיווג ראשי, {span}: {_n(grand)} אירועים; "
                           f"ב-{y1} נרשמו {_n(last)}."),
            "dataset_kind": "timeseries",
            "related_ids": ["63b7bf0b-69eb-4a73-9b98-b9fd2b8a4b5b", "cdffbed6-8388-4b72-8c74-d36403cc5b83",
                            "37c93c3e-e536-4abd-aedf-2813bfc74a4c", "09cbcff5-64fc-429b-96e5-881cbcab96af"],
            "suggested_tags": ["בטיחות", "רכבת", "רכבת ישראל", "תחבורה ציבורית", "תאונות"],
            "temporal_coverage": f"{years_all[0]}/{years_all[-1]}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"decomp": decomp, "cats": cats, "trend": trend, "heat": heat,
                   "dumbbell": dumbbell, "share": share},
        "flags": {"dumbbell": bool(dumb), "share": len(share["x"]) >= 3},
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
