"""בתי הדין השרעיים — case files and marriage contracts.

Two tables:
  * cases     — one row per case file (~840k): court, topic, case type,
                opening date, status, final decision and the qadi who gave it.
                Opening dates before the computerised system (≈2012) carry the
                year only (stored as 1 January); daily dating is detected from
                the data, never hard-coded.
  * contracts — one row per marriage contract (~162k) registered at the courts:
                court, contract date, system-entry date and the marriage
                registrar.

Personal-status data: nothing about any party is ever shown — only aggregates
by year, court, topic and outcome. Qadis act in a public capacity and are
named in the decisions ranking.

"Now" is the latest date in the data (its vintage), never the wall clock.
"""
import numpy as np
import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
WEEKDAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]  # pandas dayofweek 0=Mon
WEEK_ORDER = [6, 0, 1, 2, 3, 4, 5]   # display Sunday→Saturday

TOP_TOPICS = 7          # stacked yearly chart
SHIFT_TOPICS = 10       # topic change chart
SHIFT_GAP = 5           # years between compared periods
OUTCOME_TOPICS = 9
TREE_GROUPS = 8
TREE_TYPES = 6
TOP_TYPES = 15
TOP_QADIS = 12
QADI_YEARS = 3
HEAT_YEARS = 20
APPEAL_YEARS = 15
OPEN_YEARS = 10
RAMADAN_YEARS = 15
ENTRY_LAG_GUARD = 60    # days: contracts dated in the last N days may not be entered yet
MIN_COURT_SHARE = 0.002

DIVORCE_TOPIC = "גירושין והפרדה"
APPEALS_COURT = "השרעי לערעורים"
CLOSED = {"סגור", "מבוטל", "הועבר לערעורים"}
OUTCOMES = ["התקבלה", "ניתן פסק דין", "פשרה", "נמחקה", "נדחתה", "אחר"]


def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def d_short(ts):
    return f"{ts.day}.{ts.month}"


def _dates(s):
    """Parse dd/mm/YYYY once per distinct string (fast on 800k rows)."""
    u = pd.Series(s.unique())
    parsed = pd.to_datetime(u, format="%d/%m/%Y", errors="coerce")
    return s.map(dict(zip(u, parsed)))


def court_short(c):
    return c.replace("השרעי ", "", 1).strip() if c.startswith("השרעי ") else c


def topic_group(t):
    t = t.strip()
    if not t:
        return "לא צוין"
    if "ערעור" in t or "עירעור" in t:
        return "ערעורים"
    if t == "מזונות אישה וילדים":
        return "מזונות"
    return t


def outcome(s):
    if not s:
        return None
    if "התקבל" in s:
        return "התקבלה"
    if "פסק דין" in s:
        return "ניתן פסק דין"
    if "התפשרו" in s:
        return "פשרה"
    if "נמחק" in s:
        return "נמחקה"
    if "נדח" in s:
        return "נדחתה"
    return "אחר"


def appeal_outcome(s):
    if not s:
        return None
    if "התקבל" in s:
        return "התקבל"
    if "נדח" in s:
        return "נדחה"
    if "נמחק" in s:
        return "נמחק"
    if "התפשרו" in s:
        return "פשרה"
    return "אחר"


def clean_label(s):
    return s.replace("~", "״").strip()


def _sorted_counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def hijri(dates):
    """Tabular (arithmetic) Islamic calendar: (year, month, day) arrays.

    Within a day or two of the observed calendar — enough to place a
    whole month like Ramadan."""
    jd = (dates.values.astype("datetime64[D]").astype("int64") + 2440588).astype("int64")
    l = jd - 1948440 + 10632
    nn = (l - 1) // 10631
    l = l - 10631 * nn + 354
    j = ((10985 - l) // 5316) * ((50 * l) // 17719) + (l // 5670) * ((43 * l) // 15238)
    l = l - ((30 - j) // 15) * ((17719 * j) // 50) - (j // 16) * ((15238 * j) // 43) + 29
    m = (24 * l) // 709
    d = l - (709 * m) // 24
    y = 30 * nn + j - 30
    return y, m, d


# ── preparation ─────────────────────────────────────────────────────────

def _prep_cases(df):
    df = df.drop_duplicates()
    out = pd.DataFrame({
        "court": df["בית דין"].str.strip(),
        "topic": df["נושא תיק"].str.strip(),
        "type": df["סוג תיק"].map(clean_label),
        "d": _dates(df["תאריך פתיחת תיק"].str.strip()),
        "status": df["סטטוס תיק"].str.strip(),
        "decision": df["החלטה"].str.strip(),
        "qadi": df["נותן החלטה"].str.strip(),
    })
    out["court"] = out["court"].replace("", "לא צוין")
    out["type"] = out["type"].replace("", "לא צוין")
    # Rows with no topic take the topic their case type most often carries
    # elsewhere in the data (ties broken by name) — e.g. "מזונות ילדים" → "מזונות".
    known = out[out["topic"] != ""]
    tm = (known.groupby(["type", "topic"]).size().reset_index(name="k")
               .sort_values(["type", "k", "topic"], ascending=[True, False, True])
               .drop_duplicates("type").set_index("type")["topic"])
    blank = out["topic"] == ""
    fill = out["type"].map(tm).fillna("")
    # Types never seen with a topic: a maintenance type is a maintenance case.
    fill = fill.where((fill != "") | ~out["type"].str.contains("מזונות", regex=False), "מזונות")
    out["topic_filled"] = out["topic"].where(~blank, fill)
    out["group"] = out["topic_filled"].map(topic_group)
    out["y"] = out["d"].dt.year
    return out, len(df)


def _prep_contracts(df):
    df = df.drop_duplicates()
    out = pd.DataFrame({
        "court": df["בית דין"].str.strip(),
        "d": _dates(df["תאריך עריכת חוזה"].str.strip()),
        "entered": _dates(df["תאריך יצירת חוזה"].str.strip()),
        "registrar": df["רשם נישואין"].str.strip(),
    })
    out["court"] = out["court"].replace("", "לא צוין")
    out = out[out["d"].notna()]
    out["y"] = out["d"].dt.year
    return out, len(df)


# ── insight rules ───────────────────────────────────────────────────────

def insight_ytd(ytd, ytd_prev, ref, prev_year):
    if ytd_prev == 0:
        return None
    chg = ytd / ytd_prev - 1
    span = f"מתחילת {ref.year} ועד {d_he(ref)}"
    if abs(chg) < 0.03:
        return (f"{span} נפתחו {n(ytd)} תיקים — בדומה לתקופה המקבילה ב-{prev_year} "
                f"({n(ytd_prev)}).")
    word = "יותר" if chg > 0 else "פחות"
    return (f"{span} נפתחו {n(ytd)} תיקים — {pct(abs(chg) * 100)} {word} מאשר בתקופה "
            f"המקבילה ב-{prev_year} ({n(ytd_prev)}).")


def insight_ramadan(pool):
    if pool is None:
        return None
    ram, before, after, years = pool
    around = (before + after) / 2
    if around <= 0 or ram / around > 0.8:
        return None
    drop = 1 - ram / around
    peak = ("שעבאן, החודש שלפני הרמדאן," if before > after else "שוואל, החודש שאחרי הרמדאן,")
    return (f"בחודש הרמדאן נערכים הרבה פחות חוזי נישואין: בממוצע {ram:.1f} חוזים ביום, לעומת "
            f"{around:.1f} בחודשים שלפניו ואחריו — ירידה של {pct(drop * 100, 0)} "
            f"(ממוצע {years} שנים). {peak} עמוס יותר ({max(before, after):.1f} ביום).")


def insight_weekday(wd_counts):
    tot = sum(wd_counts.values())
    if tot == 0:
        return None
    top = max(sorted(wd_counts), key=lambda k: wd_counts[k])
    share = wd_counts[top] / tot
    if share < 1.5 / 7:
        return None
    second = sorted(wd_counts, key=lambda k: (-wd_counts[k], k))[1]
    return (f"יום {WEEKDAYS_HE[top]} הוא היום המועדף לעריכת חוזי נישואין: {pct(share * 100)} "
            f"מהחוזים נערכים בו, ואחריו יום {WEEKDAYS_HE[second]} "
            f"({pct(wd_counts[second] / tot * 100)}).")


def insight_divorce(rows):
    if not rows:
        return None
    last = rows[-1]
    first = rows[0]
    if last["contracts"] == 0 or first["contracts"] == 0:
        return None
    r1 = last["divorce"] / last["contracts"] * 100
    r0 = first["divorce"] / first["contracts"] * 100
    if abs(r1 - r0) < 3:
        trend = f"בדומה ל-{first['year']} ({r0:.0f})"
    else:
        trend = f"לעומת {r0:.0f} ב-{first['year']}"
    return (f"ב-{last['year']} נפתחו {n(last['divorce'])} תיקי גירושין והפרדה מול "
            f"{n(last['contracts'])} חוזי נישואין — כ-{r1:.0f} תיקי גירושין לכל 100 חוזים, "
            f"{trend}.")


def insight_topic_shift(shift, base, last):
    if not shift:
        return None
    tot_b = sum(r["base"] for r in shift) or 1
    tot_l = sum(r["last"] for r in shift) or 1
    new = [r for r in shift if r["base"] == 0 and r["last"] / tot_l >= 0.02]
    if new:
        r = max(new, key=lambda x: (x["last"], x["name"]))
        return (f"נושא חדש: ב-{base} לא נפתחו תיקי \"{r['name']}\", וב-{last} נפתחו "
                f"{n(r['last'])} — {pct(r['last'] / tot_l * 100)} מהתיקים.")
    best = max(shift, key=lambda x: (abs(x["last"] / tot_l - x["base"] / tot_b), x["name"]))
    s0, s1 = best["base"] / tot_b * 100, best["last"] / tot_l * 100
    if abs(s1 - s0) < 2:
        return None
    word = "עלה" if s1 > s0 else "ירד"
    return (f"השינוי הגדול בהרכב התיקים: חלקם של תיקי \"{best['name']}\" {word} מ-{pct(s0)} "
            f"ב-{base} ל-{pct(s1)} ב-{last}.")


def insight_new_court(court_first, window_start, by_court_last, last_full):
    late = {c: y for c, y in court_first.items() if y > window_start}
    if not late:
        return None
    c = max(sorted(late), key=lambda k: late[k])
    y = late[c]
    v = by_court_last.get(c, 0)
    if v == 0:
        return None
    return (f"בית הדין השרעי ב{court_short(c)} הוא הצעיר ברשימה — התיקים הראשונים בו "
            f"נפתחו ב-{y}, וב-{last_full} נפתחו בו {n(v)} תיקים.")


def insight_outcomes(out_rows):
    big = [r for r in out_rows if r["n"] >= 1000 and r["name"] not in ("לא צוין", "אחר")]
    if len(big) < 3:
        return None
    hi = max(big, key=lambda r: (r["shares"]["נמחקה"], r["name"]))
    co = max(big, key=lambda r: (r["shares"]["פשרה"], r["name"]))
    if hi["shares"]["נמחקה"] < 20:
        return None
    s = (f"בתיקי \"{hi['name']}\" {pct(hi['shares']['נמחקה'], 0)} מהתיקים שהוכרעו הסתיימו "
         f"במחיקה")
    if co["shares"]["פשרה"] >= 5:
        s += (f"; פשרה בין הצדדים נפוצה בעיקר בתיקי \"{co['name']}\" "
              f"({pct(co['shares']['פשרה'], 0)})")
    return s + "."


def insight_appeals(app_out):
    decided = sum(v for k, v in app_out if k in ("התקבל", "נדחה", "נמחק"))
    if decided < 200:
        return None
    d = dict(app_out)
    acc = d.get("התקבל", 0) / decided
    rej = d.get("נדחה", 0) / decided
    return (f"בבית הדין השרעי לערעורים, מבין {n(decided)} תיקים שהוכרעו (התקבלו, נדחו או "
            f"נמחקו), {pct(acc * 100, 0)} התקבלו — כולל החזרה לבית הדין האזורי — "
            f"ו-{pct(rej * 100, 0)} נדחו.")


def insight_registrar(reg_rows):
    if len(reg_rows) < 4:
        return None
    first, last = reg_rows[0], reg_rows[-1]
    if last["missing"] < 15 or last["missing"] - first["missing"] < 5:
        return None
    return (f"רישום חסר: ב-{last['year']} {pct(last['missing'], 0)} מחוזי הנישואין נרשמו "
            f"במאגר ללא שם רשם הנישואין, לעומת {pct(first['missing'], 0)} ב-{first['year']}.")


# ── compute ─────────────────────────────────────────────────────────────

def compute(frames):
    cases, cases_rows = _prep_cases(frames["cases"])
    con, con_rows = _prep_contracts(frames["contracts"])
    total_cases = len(cases)
    total_con = len(con)
    dup_cases = len(frames["cases"]) - cases_rows
    dup_con = len(frames["contracts"]) - con_rows

    dated = cases[cases["d"].notna()]
    ref = dated["d"].max()
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = int(ref.year) - 1 if partial else int(ref.year)
    ref_c = con["entered"].max() if con["entered"].notna().any() else con["d"].max()
    ref_cd = con["d"].max()

    # Daily dating: from the first year after which no year is mostly 1-January dates.
    jan1 = (dated["d"].dt.month == 1) & (dated["d"].dt.day == 1)
    jan_share = jan1.groupby(dated["y"]).mean().sort_index()
    mostly = [int(y) for y, v in jan_share.items() if v > 0.5]
    daily_from = (max(mostly) + 1) if mostly else int(jan_share.index.min())

    per_year = dated.groupby("y").size().sort_index()
    per_year.index = per_year.index.astype(int)
    start_year = int(per_year[per_year >= per_year.max() * 0.01].index.min())

    # ── chart: cases by year and topic ──
    recent = dated[(dated["y"] > last_full - 10) & (dated["y"] <= last_full)]
    gcounts = _sorted_counts(recent["group"])
    top_groups = [g for g in gcounts.index if g != "לא צוין"][:TOP_TOPICS]
    win = dated[dated["y"] >= start_year]
    gy = (win.assign(g=win["group"].where(win["group"].isin(top_groups), "אחר"))
             .groupby(["y", "g"]).size().unstack(fill_value=0).sort_index())
    years = list(range(start_year, int(ref.year) + 1))
    gy = gy.reindex(years, fill_value=0)
    series_names = top_groups + (["אחר"] if "אחר" in gy.columns else [])
    cases_year = {"x": [str(y) for y in years],
                  "series": [{"name": g, "data": [int(v) for v in gy[g]]} for g in series_names],
                  "daily_from": str(daily_from),
                  "zoom_start": str(max(start_year, int(ref.year) - 29))}

    # ── YTD comparison (dates are daily from daily_from) ──
    prev_year = int(ref.year) - 1
    ytd = int(((dated["y"] == ref.year) & (dated["d"] <= ref)).sum())
    try:
        prev_cut = ref.replace(year=prev_year)
    except ValueError:
        prev_cut = ref.replace(year=prev_year, day=28)
    ytd_prev = int(((dated["y"] == prev_year) & (dated["d"] <= prev_cut)).sum())
    ytd_ok = prev_year >= daily_from and ytd_prev > 0

    # ── topic shift ──
    base = last_full - SHIFT_GAP
    lastc = dated[dated["y"] == last_full]["group"].value_counts()
    basec = dated[dated["y"] == base]["group"].value_counts()
    names = [g for g in _sorted_counts(dated[dated["y"] == last_full]["group"]).index
             if g != "לא צוין"][:SHIFT_TOPICS]
    shift = [{"name": g, "base": int(basec.get(g, 0)), "last": int(lastc.get(g, 0))} for g in names]

    # ── courts ──
    cc = _sorted_counts(cases["court"])
    courts = [c for c in cc.index if cc[c] / total_cases >= MIN_COURT_SHARE]
    last_cases = dated[dated["y"] == last_full]
    con_last = con[con["y"] == last_full]
    by_court_cases = last_cases.groupby("court").size()
    by_court_con = con_last.groupby("court").size()
    by_court_div = last_cases[last_cases["topic"] == DIVORCE_TOPIC].groupby("court").size()
    court_order = sorted(courts, key=lambda c: (-int(by_court_cases.get(c, 0)), c))
    court_rows = []
    for c in court_order:
        k, m_, dv = int(by_court_cases.get(c, 0)), int(by_court_con.get(c, 0)), int(by_court_div.get(c, 0))
        court_rows.append({"court": court_short(c), "cases": k, "contracts": m_, "divorce": dv,
                           "ratio": (round(dv / m_ * 100) if m_ >= 100 else None)})
    courts_chart = {"names": [r["court"] for r in court_rows],
                    "cases": [r["cases"] for r in court_rows],
                    "contracts": [r["contracts"] for r in court_rows]}

    # ── court × year heatmap ──
    h0 = max(start_year, int(ref.year) - HEAT_YEARS + 1)
    hy = list(range(h0, int(ref.year) + 1))
    hc = dated[(dated["y"] >= h0) & dated["court"].isin(courts)].groupby(["court", "y"]).size()
    heat_courts = sorted(courts, key=lambda c: (-int(cc[c]), c))
    cells = []
    for yi, c in enumerate(heat_courts):
        for xi, y in enumerate(hy):
            cells.append([xi, yi, int(hc.get((c, y), 0))])
    court_heat = {"x": [str(y) for y in hy], "y": [court_short(c) for c in heat_courts],
                  "cells": cells, "max": max([c[2] for c in cells] or [1])}
    court_first = {}
    for c in courts:
        s = dated[dated["court"] == c].groupby("y").size()
        s = s[s >= 100]
        if len(s):
            court_first[c] = int(s.index.min())

    # ── marriage contracts: coverage window ──
    cy = con.groupby("y").size().sort_index()
    cy.index = cy.index.astype(int)
    full_c = cy[cy.index <= last_full]
    peak_c = full_c.max() if len(full_c) else cy.max()
    # Full registration starts in the first year reaching 60% of the peak year.
    con_start = int(cy[cy >= peak_c * 0.6].index.min())
    con_years = [y for y in range(con_start, last_full + 1)]

    # marriage vs divorce
    div_year = dated[dated["topic"] == DIVORCE_TOPIC].groupby("y").size()
    md_rows = [{"year": y, "contracts": int(cy.get(y, 0)), "divorce": int(div_year.get(y, 0))}
               for y in con_years]
    for r in md_rows:
        r["ratio"] = round(r["divorce"] / r["contracts"] * 100) if r["contracts"] else None
    marriage_divorce = {"x": [str(r["year"]) for r in md_rows],
                        "contracts": [r["contracts"] for r in md_rows],
                        "divorce": [r["divorce"] for r in md_rows]}

    # month × year heatmap of contracts
    cm = con[con["y"] >= con_start]
    mc = cm.groupby([cm["y"], cm["d"].dt.month]).size()
    heat_years = list(range(con_start, int(ref_cd.year) + 1))
    mcells = []
    for yi, y in enumerate(heat_years):
        for mi in range(12):
            if y == ref_cd.year and mi + 1 > ref_cd.month:
                continue
            mcells.append([mi, yi, int(mc.get((y, mi + 1), 0))])
    con_heat = {"x": MONTHS_SHORT, "y": [str(y) for y in heat_years], "cells": mcells,
                "max": max([c[2] for c in mcells] or [1])}
    month_tot = cm[cm["y"] <= last_full].groupby(cm["d"].dt.month).size()
    top_month = int(max(range(1, 13), key=lambda m_: (int(month_tot.get(m_, 0)), -m_)))

    # Ramadan: daily average in Sha'ban (8), Ramadan (9), Shawwal (10)
    guard_end = ref_c - pd.Timedelta(days=ENTRY_LAG_GUARD)
    rng = pd.date_range(pd.Timestamp(con_start, 1, 1), guard_end, freq="D")
    ram_rows, pool = [], None
    if len(rng):
        daily = cm.groupby("d").size().reindex(rng, fill_value=0)
        hy_, hm_, _ = hijri(pd.Series(rng))
        dd = pd.DataFrame({"n": daily.values, "hy": hy_, "hm": hm_, "gy": rng.year})
        # Complete Hijri months only: drop the clipped first and last Hijri year-months.
        first_key = (int(dd["hy"].iloc[0]), int(dd["hm"].iloc[0]))
        last_key = (int(dd["hy"].iloc[-1]), int(dd["hm"].iloc[-1]))
        keys = list(zip(dd["hy"].astype(int), dd["hm"].astype(int)))
        dd = dd[[k not in (first_key, last_key) for k in keys]]
        sub = dd[dd["hm"].isin([8, 9, 10])]
        g = sub.groupby(["hy", "hm"]).agg(avg=("n", "mean"), gy=("gy", "min")).reset_index()
        for hyv in sorted(g["hy"].unique()):
            row = g[g["hy"] == hyv].set_index("hm")
            if not {8, 9, 10} <= set(row.index):
                continue
            ram_rows.append({"label": str(int(row.loc[9, "gy"])),
                             "before": round(float(row.loc[8, "avg"]), 1),
                             "ram": round(float(row.loc[9, "avg"]), 1),
                             "after": round(float(row.loc[10, "avg"]), 1)})
        ram_rows = ram_rows[-RAMADAN_YEARS:]
        if len(ram_rows) >= 3:
            k = len(ram_rows)
            pool = (sum(r["ram"] for r in ram_rows) / k, sum(r["before"] for r in ram_rows) / k,
                    sum(r["after"] for r in ram_rows) / k, k)
    ramadan = {"x": [r["label"] for r in ram_rows],
               "before": [r["before"] for r in ram_rows],
               "ram": [r["ram"] for r in ram_rows],
               "after": [r["after"] for r in ram_rows]}
    ram_drop = (1 - pool[0] / ((pool[1] + pool[2]) / 2)) * 100 if pool and (pool[1] + pool[2]) else None

    # weekday
    wd = cm["d"].dt.dayofweek.value_counts()
    wd_counts = {i: int(wd.get(i, 0)) for i in range(7)}
    wd_tot = sum(wd_counts.values()) or 1
    weekday = {"names": [WEEKDAYS_HE[i] for i in WEEK_ORDER],
               "values": [wd_counts[i] for i in WEEK_ORDER]}

    # entry lag + registrar completeness (full years, contracts not too recent)
    lag_src = cm[(cm["y"] <= last_full) & cm["entered"].notna()]
    lag_days = (lag_src["entered"] - lag_src["d"]).dt.days
    lag_med = lag_days.groupby(lag_src["y"]).median()
    lag_week = (lag_days <= 7).groupby(lag_src["y"]).mean()
    reg_src = cm[cm["y"] <= last_full]
    miss = (reg_src["registrar"] == "").groupby(reg_src["y"]).mean()
    regs = reg_src[reg_src["registrar"] != ""].groupby("y")["registrar"].nunique()
    qual_rows = []
    for y in con_years:
        if y not in lag_med.index:
            continue
        qual_rows.append({"year": y, "lag": int(round(float(lag_med[y]))),
                          "week": round(float(lag_week[y]) * 100, 1),
                          "missing": round(float(miss.get(y, 0)) * 100, 1),
                          "registrars": int(regs.get(y, 0))})
    quality = {"x": [str(r["year"]) for r in qual_rows],
               "lag": [r["lag"] for r in qual_rows],
               "week": [r["week"] for r in qual_rows],
               "missing": [r["missing"] for r in qual_rows]}

    # ── outcomes by topic (closed cases with a recorded decision) ──
    dec_share = (dated["decision"] != "").groupby(dated["y"]).mean().sort_index()
    big_years = set(int(y) for y in per_year[per_year >= per_year.max() * 0.1].index)
    good = [int(y) for y, v in dec_share.items()
            if v >= 0.8 and y <= last_full and int(y) in big_years]
    dec_from = min(good) if good else None
    out_rows = []
    if dec_from is not None:
        od = dated[(dated["y"] >= dec_from) & (dated["y"] <= last_full) & (dated["decision"] != "")
                   & (dated["court"] != APPEALS_COURT)]
        od = od.assign(o=od["decision"].map(outcome))
        og = _sorted_counts(od["group"])
        groups = [g for g in og.index if g not in ("לא צוין", "ערעורים")][:OUTCOME_TOPICS]
        tab = od[od["group"].isin(groups)].groupby(["group", "o"]).size()
        for g in groups:
            tot = int(og[g])
            shares = {o: round(int(tab.get((g, o), 0)) / tot * 100, 1) for o in OUTCOMES}
            out_rows.append({"name": g, "n": tot, "shares": shares})
    outcomes_chart = {"names": [r["name"] for r in out_rows],
                      "series": [{"name": o, "data": [r["shares"][o] for r in out_rows]}
                                 for o in OUTCOMES if any(r["shares"][o] for r in out_rows)]}

    # ── appeals court ──
    ap = dated[dated["court"] == APPEALS_COURT]
    ap_year = ap.groupby("y").size()
    a0 = int(ref.year) - APPEAL_YEARS + 1
    ap_years = [y for y in range(a0, int(ref.year) + 1)]
    appeals_year = {"x": [str(y) for y in ap_years], "y": [int(ap_year.get(y, 0)) for y in ap_years]}
    ap_dec = ap[ap["decision"] != ""]["decision"].map(appeal_outcome)
    ap_out = [(k, int(v)) for k, v in _sorted_counts(ap_dec).items()]
    ap_topics = _sorted_counts(ap["type"]).head(8)
    appeals_out = {"names": [k for k, _ in ap_out], "values": [v for _, v in ap_out]}
    appeals_total = len(ap)

    # ── case types treemap (last 5 full years) ──
    t0 = last_full - SHIFT_GAP + 1
    tw = dated[(dated["y"] >= t0) & (dated["y"] <= last_full)]
    tg = _sorted_counts(tw["group"])
    tree = []
    for g in [x for x in tg.index if x != "לא צוין"][:TREE_GROUPS]:
        tc = _sorted_counts(tw[tw["group"] == g]["type"])
        kids = [{"name": k, "value": int(v)} for k, v in tc.head(TREE_TYPES).items()]
        rest = int(tc.iloc[TREE_TYPES:].sum())
        if rest:
            kids.append({"name": "אחר", "value": rest})
        tree.append({"name": g, "value": int(tg[g]), "children": kids})
    tt = (tw.groupby(["type", "group"]).size().reset_index(name="n")
            .sort_values(["n", "type", "group"], ascending=[False, True, True]).head(TOP_TYPES))
    type_rows = [{"type": r["type"], "group": r["group"], "count": n(r["n"])} for _, r in tt.iterrows()]
    n_types = int(tw["type"].nunique())

    # ── qadis ──
    q0 = last_full - QADI_YEARS + 1
    qd = dated[(dated["y"] >= q0) & (dated["y"] <= last_full) & (dated["qadi"] != "")]
    qc = _sorted_counts(qd["qadi"])
    q_main = qd.groupby(["qadi", "court"]).size().reset_index(name="n").sort_values(
        ["qadi", "n", "court"], ascending=[True, False, True]).drop_duplicates("qadi").set_index("qadi")
    qadi_rows = []
    for q in qc.index[:TOP_QADIS]:
        qadi_rows.append({"name": q, "count": int(qc[q]),
                          "court": court_short(q_main.loc[q, "court"]),
                          "share": round(int(q_main.loc[q, "n"]) / int(qc[q]) * 100)})
    qadis_chart = {"names": [r["name"] for r in qadi_rows], "values": [r["count"] for r in qadi_rows]}
    n_qadis = int(qc.size)
    q_tot = int(qc.sum())
    top5_share = (qc.head(5).sum() / q_tot * 100) if q_tot else 0

    # ── open cases ──
    open_mask = ~cases["status"].isin(CLOSED)
    open_total = int(open_mask.sum())
    op = dated[~dated["status"].isin(CLOSED)]
    o0 = int(ref.year) - OPEN_YEARS + 1
    op_year = op.groupby("y").size()
    open_years = [y for y in range(o0, int(ref.year) + 1)]
    open_chart = {"x": [str(y) for y in open_years], "y": [int(op_year.get(y, 0)) for y in open_years]}
    open_old = int((op["y"] < ref.year).sum())
    open_status = [(k, int(v)) for k, v in _sorted_counts(cases.loc[open_mask, "status"]).items()]

    # ── insights ──
    dg = div_year
    rules = [
        ("ytd", insight_ytd(ytd, ytd_prev, ref, prev_year) if ytd_ok else None),
        ("ramadan", insight_ramadan(pool)),
        ("weekday", insight_weekday(wd_counts)),
        ("divorce", insight_divorce(md_rows)),
        ("topic_shift", insight_topic_shift(shift, base, last_full)),
        ("new_court", insight_new_court(court_first, h0, dict(by_court_cases), last_full)),
        ("outcomes", insight_outcomes(out_rows)),
        ("appeals", insight_appeals(ap_out)),
        ("registrar", insight_registrar(qual_rows)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── KPIs ──
    if ytd_ok:
        chg = (ytd / ytd_prev - 1) * 100
        ytd_disp = (f"+{chg:.1f}%" if chg >= 0 else f"{MINUS}{abs(chg):.1f}%")
        ytd_tone = "brand" if abs(chg) < 3 else "info"
    else:
        chg, ytd_disp, ytd_tone = None, "—", "brand"
    last_reg = qual_rows[-1] if qual_rows else None
    miss_tone = "brand"
    if last_reg:
        miss_tone = "danger" if last_reg["missing"] >= 50 else ("warn" if last_reg["missing"] >= 20 else "ok")
    kpis = {
        "cases": {"value": total_cases, "display": n(total_cases), "tone": "brand"},
        "contracts": {"value": total_con, "display": n(total_con), "tone": "brand"},
        "ytd": {"value": ytd, "display": n(ytd), "tone": "brand"},
        "ytd_change": {"value": None if chg is None else round(chg, 1), "display": ytd_disp,
                       "tone": ytd_tone},
        "open": {"value": open_total, "display": n(open_total), "tone": "brand"},
        "ramadan": {"value": None if ram_drop is None else round(ram_drop, 1),
                    "display": "—" if ram_drop is None else f"{MINUS}{ram_drop:.0f}%",
                    "tone": "info" if ram_drop is not None else "brand"},
        "missing": {"value": last_reg["missing"] if last_reg else None,
                    "display": f"{last_reg['missing']:.1f}%" if last_reg else "—", "tone": miss_tone},
        "qadis": {"value": n_qadis, "display": n(n_qadis), "tone": "brand"},
    }

    partial_note = (f" {ref.year} — שנה חלקית, עד {d_he(ref)}." if partial else "")
    first_y = int(per_year.index.min())
    ram_n = len(ram_rows)
    md_last = md_rows[-1] if md_rows else None
    labels = {
        "lede": (f"{n(total_cases)} תיקים שנפתחו בבתי הדין השרעיים — {len([c for c in courts if c != APPEALS_COURT])} בתי דין אזוריים "
                 f"ובית הדין לערעורים — ו-{n(total_con)} חוזי נישואין שנרשמו בהם. התיקים עוסקים "
                 f"בענייני המעמד האישי של מוסלמים בישראל: נישואין וגירושין, מזונות, משמורת, "
                 f"אפוטרופסות וירושה. הנתונים מעודכנים עד {d_he(ref)}; הדף מציג סיכומים בלבד, "
                 f"ללא פרטים על הצדדים."),
        "ytd_kpi": f"תיקים שנפתחו ב-{ref.year} (עד {d_short(ref)})",
        "ytd_change_kpi": f"לעומת התקופה המקבילה ב-{prev_year}",
        "ramadan_kpi": f"חוזי נישואין ביום ברמדאן, לעומת החודשים הסמוכים",
        "missing_kpi": (f"חוזים ללא שם רשם נישואין ({last_reg['year']})" if last_reg
                        else "חוזים ללא שם רשם נישואין"),
        "qadis_kpi": f"קאדים שנתנו החלטות ({q0}–{last_full})",
        "open_kpi": "תיקים פתוחים כעת",
        "cases_year_note": (f"תיקים לפי שנת פתיחה ונושא, מ-{start_year} (תיקים בודדים מ-{first_y} "
                            f"אינם מוצגים). עד {daily_from - 1} נרשמה לתיקים שנת הפתיחה בלבד. תיקים ללא נושא "
                            f"שויכו לנושא הנפוץ של סוג התיק. "
                            f"הירידה בתיקי הנישואין ב-{con_start} משקפת את המעבר של חוזי הנישואין "
                            f"לרישום נפרד.{partial_note}"),
        "cases_year_aria": (f"גרף עמודות מוערמות: תיקים שנפתחו בכל שנה לפי נושא, {start_year} עד "
                            f"{ref.year}."),
        "shift_note": (f"מספר התיקים שנפתחו ב-{base} וב-{last_full}, ב-{len(shift)} הנושאים הנפוצים "
                       f"ב-{last_full}."),
        "shift_aria": f"גרף עמודות: תיקים לפי נושא, {base} מול {last_full}.",
        "shift_caption": f"תיקים לפי נושא, {base} ו-{last_full}.",
        "tree_note": (f"נושאי התיקים וסוגי התיקים שבתוכם, {t0}–{last_full} — {n(len(tw))} תיקים "
                      f"ב-{n_types} סוגים. לחיצה על נושא מתמקדת בו."),
        "tree_aria": f"מפת עץ: תיקים לפי נושא וסוג תיק, {t0} עד {last_full}.",
        "types_caption": f"{TOP_TYPES} סוגי התיקים הנפוצים, {t0}–{last_full}.",
        "courts_note": (f"תיקים שנפתחו וחוזי נישואין שנרשמו ב-{last_full}, לפי בית דין. תיקי גירושין "
                        f"לכל 100 חוזים הוא יחס גס בין שני רישומים — לא שיעור גירושין."),
        "courts_aria": f"גרף עמודות: תיקים וחוזי נישואין לפי בית דין, {last_full}.",
        "courts_caption": f"תיקים, חוזי נישואין ותיקי גירושין לפי בית דין, {last_full}.",
        "court_heat_note": f"תיקים שנפתחו בכל בית דין בכל שנה, {h0}–{ref.year}.{partial_note}",
        "court_heat_aria": f"מפת חום: תיקים לפי בית דין ושנה, {h0} עד {ref.year}.",
        "md_note": (f"חוזי נישואין ותיקי גירושין והפרדה שנפתחו בכל שנה, {con_start}–{last_full} "
                    f"(שנים מלאות; רישום החוזים במאגר מלא מ-{con_start})."),
        "md_aria": (f"גרף קווים: חוזי נישואין ותיקי גירושין לפי שנה, {con_start} עד {last_full}."
                    + (f" ב-{md_last['year']}: {n(md_last['contracts'])} חוזים ו-{n(md_last['divorce'])} "
                       f"תיקי גירושין." if md_last else "")),
        "md_caption": f"חוזי נישואין, תיקי גירושין והיחס ביניהם לפי שנה, {con_start}–{last_full}.",
        "con_heat_note": (f"חוזי נישואין לפי חודש ושנת עריכת החוזה, {con_start}–{ref_cd.year}. "
                          f"החודש העמוס ביותר לאורך השנים: {MONTHS_HE[top_month - 1]}. התאים הבהירים "
                          f"שנודדים כל שנה כאחד-עשר יום אחורה הם חודש הרמדאן. חוזים מהשבועות "
                          f"האחרונים עשויים עדיין שלא להופיע."),
        "con_heat_aria": f"מפת חום: חוזי נישואין לפי חודש ושנה, {con_start} עד {ref_cd.year}.",
        "ram_note": (f"ממוצע חוזי נישואין ליום בחודשים שעבאן, רמדאן ושוואל, {ram_n} השנים האחרונות "
                     f"(לפי הלוח המוסלמי החשבוני, שעשוי לסטות ביום-יומיים מהלוח הנצפה; השנה "
                     f"היא שנת תחילת הרמדאן)."),
        "ram_aria": f"גרף עמודות: ממוצע חוזי נישואין ליום לפני הרמדאן, ברמדאן ואחריו, {ram_n} שנים.",
        "ram_caption": "ממוצע חוזי נישואין ליום בשעבאן, ברמדאן ובשוואל, לפי שנה.",
        "weekday_note": f"חוזי נישואין לפי יום בשבוע, {con_start}–{ref_cd.year}.",
        "weekday_aria": "גרף עמודות: חוזי נישואין לפי יום בשבוע.",
        "weekday_caption": "חוזי נישואין לפי יום בשבוע.",
        "outcomes_note": ((f"התפלגות ההחלטות בתיקים שנפתחו {dec_from}–{last_full} ושנרשמה בהם "
                           f"החלטה, ב-{len(out_rows)} הנושאים הנפוצים (בתי הדין האזוריים; ללא "
                           f"ערעורים). לתיקים מלפני {dec_from} לא נרשמה החלטה במאגר.")
                          if dec_from else ""),
        "outcomes_aria": "גרף עמודות אופקיות מוערמות: התפלגות ההחלטות לפי נושא התיק, באחוזים.",
        "outcomes_caption": "התפלגות ההחלטות לפי נושא התיק, באחוזים.",
        "appeals_note": (f"{n(appeals_total)} תיקים נפתחו בבית הדין השרעי לערעורים — לפי שנה "
                         f"({a0}–{ref.year}) ולפי ההחלטה שנרשמה בהם.{partial_note}"),
        "appeals_year_aria": f"גרף עמודות: תיקים בבית הדין לערעורים לפי שנה, {a0} עד {ref.year}.",
        "appeals_year_caption": f"תיקים בבית הדין לערעורים לפי שנה, {a0}–{ref.year}.",
        "appeals_out_aria": "גרף עמודות: החלטות בבית הדין לערעורים לפי תוצאה.",
        "appeals_out_caption": "החלטות בבית הדין לערעורים לפי תוצאה.",
        "qadis_note": (f"מספר ההחלטות שנתן כל קאדי בתיקים שנפתחו {q0}–{last_full}, ובית הדין שבו "
                       f"נתן את רובן. {n(n_qadis)} קאדים נתנו החלטות בתקופה; חמשת הראשונים — "
                       f"{pct(top5_share, 0)} מההחלטות."),
        "qadis_aria": f"גרף עמודות: {len(qadi_rows)} הקאדים שנתנו הכי הרבה החלטות, {q0} עד {last_full}.",
        "qadis_caption": f"החלטות לפי קאדי, {q0}–{last_full}.",
        "open_note": (f"{n(open_total)} תיקים אינם סגורים (פעילים או בטיפול המזכירות); "
                      f"{n(open_old)} מהם נפתחו לפני {ref.year}. בתרשים: לפי שנת הפתיחה, "
                      f"{o0}–{ref.year}."),
        "open_aria": f"גרף עמודות: תיקים פתוחים לפי שנת פתיחה, {o0} עד {ref.year}.",
        "open_caption": "תיקים פתוחים לפי שנת פתיחה.",
        "quality_note": (f"הזמן החציוני (בימים) מעריכת חוזה הנישואין ועד רישומו במערכת, ושיעור החוזים "
                         f"שנרשמו ללא שם רשם הנישואין, {con_start}–{last_full}."),
        "lag_aria": f"גרף קווים: ימים חציוניים מעריכת חוזה ועד רישומו, {con_start} עד {last_full}.",
        "missing_aria": f"גרף קווים: שיעור החוזים ללא שם רשם, {con_start} עד {last_full}.",
        "quality_caption": "זמן רישום חציוני, שיעור הנרשמים בתוך שבוע ושיעור החוזים ללא רשם, לפי שנה.",
        "dups": (f"{n(dup_cases + dup_con)} שורות כפולות זהות הוסרו." if dup_cases + dup_con else ""),
    }

    tables = {
        "shift": [{"name": r["name"], "base": n(r["base"]), "last": n(r["last"])} for r in shift],
        "types": type_rows,
        "courts": [{"court": r["court"], "cases": n(r["cases"]), "contracts": n(r["contracts"]),
                    "divorce": n(r["divorce"]),
                    "ratio": "—" if r["ratio"] is None else str(r["ratio"])} for r in court_rows],
        "md": [{"year": str(r["year"]), "contracts": n(r["contracts"]), "divorce": n(r["divorce"]),
                "ratio": "—" if r["ratio"] is None else str(r["ratio"])} for r in md_rows],
        "ramadan": [{"label": r["label"], "before": f"{r['before']:.1f}", "ram": f"{r['ram']:.1f}",
                     "after": f"{r['after']:.1f}"} for r in ram_rows],
        "weekday": [{"name": a, "count": n(b)} for a, b in zip(weekday["names"], weekday["values"])],
        "outcomes": [{"name": r["name"], "n": n(r["n"]),
                      "cells": [f"{r['shares'][o]:.1f}%" for o in OUTCOMES]} for r in out_rows],
        "outcome_cols": OUTCOMES,
        "appeals_year": [{"year": a, "count": n(b)} for a, b in zip(appeals_year["x"], appeals_year["y"])],
        "appeals_out": [{"name": k, "count": n(v)} for k, v in ap_out],
        "appeal_types": [{"name": k, "count": n(v)} for k, v in ap_topics.items()],
        "qadis": [{"name": r["name"], "count": n(r["count"]), "court": r["court"],
                   "share": f"{r['share']}%"} for r in qadi_rows],
        "open": [{"year": a, "count": n(b)} for a, b in zip(open_chart["x"], open_chart["y"])],
        "open_status": [{"name": k, "count": n(v)} for k, v in open_status],
        "quality": [{"year": str(r["year"]), "lag": str(r["lag"]), "week": f"{r['week']:.1f}%",
                     "missing": f"{r['missing']:.1f}%", "registrars": n(r["registrars"])}
                    for r in qual_rows],
    }

    charts = {
        "cases_year": cases_year,
        "shift": {"names": [r["name"] for r in shift], "base": [r["base"] for r in shift],
                  "last": [r["last"] for r in shift], "base_label": str(base),
                  "last_label": str(last_full)},
        "tree": tree,
        "courts": courts_chart,
        "court_heat": court_heat,
        "marriage_divorce": marriage_divorce,
        "con_heat": con_heat,
        "ramadan": ramadan,
        "weekday": weekday,
        "outcomes": outcomes_chart,
        "appeals_year": appeals_year,
        "appeals_out": appeals_out,
        "qadis": qadis_chart,
        "open": open_chart,
        "quality": quality,
    }

    return {
        "agent_data": {
            "summary_he": (f"פעילות בתי הדין השרעיים בישראל: {n(total_cases)} תיקים בענייני מעמד "
                           f"אישי מאז {first_y} ו-{n(total_con)} חוזי נישואין — לפי שנה, בית דין, "
                           f"נושא, החלטה וקאדי, ועונתיות החתונות סביב הרמדאן."),
            "dataset_kind": "timeseries",
            "related_ids": ["eda6d5e4-b6ed-478e-a92b-71e0baab84b6",
                            "7368d9de-e3ea-43e9-9e7d-03ffffe79b5f",
                            "13449cdd-9d02-44cf-b298-82f598369cd7",
                            "00044967-eda3-4942-b87c-a796b5768526",
                            "ecae900d-a67a-4a65-ad4d-7cf452e8c6a4"],
            "suggested_tags": ["בתי דין שרעיים", "מעמד אישי", "נישואין", "גירושין",
                               "מזונות", "משרד המשפטים"],
            "temporal_coverage": f"{start_year}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"outcomes": bool(out_rows), "ramadan": bool(ram_rows),
                  "appeals": appeals_total > 0, "qadis": bool(qadi_rows)},
    }
