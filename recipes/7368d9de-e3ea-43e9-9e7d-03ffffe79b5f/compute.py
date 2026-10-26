"""בתי הדין הדרוזים — case files and marriage contracts.

Two tables:
  * cases     — one row per case file (~17k, from mid-2013): court (Acre,
                Buq'ata, the appeals court), topic, case type, opening date,
                status, final decision and the qadi (or the secretary, for an
                administrative decision) who gave it.
  * contracts — one row per marriage contract (~45k): court, contract date,
                date the marriage file was opened in the system, contract and
                ledger numbers and the marriage registrar. Historical contracts
                (back to 1949) were keyed in retroactively — their file date is
                years after the contract and they carry no contract number or
                registrar. Those rows are frequently identical to each other
                (same court, same day) and are real, separate contracts, so
                only rows WITH a contract number are de-duplicated.

Personal-status data: nothing about any party is shown — only aggregates by
year, month, weekday, court, topic, type and outcome. Cells under five that
cross several dimensions are suppressed ("<5" / not drawn). Qadis act in a
public capacity and are named in the decisions view; marriage registrars are
counted, not ranked.

"Now" is the latest date in the data (its vintage), never the wall clock.
"""
import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
WEEKDAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]  # pandas 0=Mon
WEEK_ORDER = [6, 0, 1, 2, 3, 4, 5]   # Sunday → Saturday

SMALL = 5               # cross-tab cells below this are suppressed
TOP_TOPICS = 7
MIN_TOPIC = 50          # topics smaller than this (in the window) go to "אחר"
TREE_TYPES = 6
TOP_TYPES = 15
TYPE_YEARS = 5
TOP_DECIDERS = 7
OUTCOME_MIN = 100
COURT_YEARS = 15
APPEAL_YEARS = 15
DECADE_MIN = 500        # contracts per decade to enter the season/weekday views
LIVE_LAG = 365          # |file date − contract date| ≤ this → entered in real time
LEAD_MIN = 100
REG_TOP = 10
NEW_TYPE_SHARE = 0.05
SEASON_LINES = 4

DIVORCE_TOPIC = "גירושין"
INHERIT_TOPIC = "צוואות וירושות"
TEST_TOPIC = "תיקי בדיקה לאתר"
CONSENT_KEY = "בהסכמה"
CONTESTED_TYPE = "גירושין"
CLOSED = {"סגור", "הועבר"}
OUTCOMES = ["התקבלה", "ניתן פסק דין", "פשרה", "נמחקה", "נדחתה", "אחר"]
DECIDER_ALIASES = {"מואפק טריף": "מוופק טריף"}   # spelling variants of one name
ADMIN_LABEL = "החלטה מנהלתית"
COURT_AREA = {"עכו": "הגליל והכרמל", "בוקעתא": "רמת הגולן"}


def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def d_short(ts):
    return f"{ts.day}.{ts.month}"


def rng(a, b):
    return f"{a} עד {b}" if a != b else f"{a}"


def mask(v):
    v = int(v)
    return None if 0 < v < SMALL else v


def mdisp(v):
    v = int(v)
    return "<5" if 0 < v < SMALL else n(v)


def _dates(s):
    u = pd.Series(sorted(s.unique()))
    parsed = pd.to_datetime(u, format="%d/%m/%Y", errors="coerce")
    return s.map(dict(zip(u, parsed)))


def _sorted_counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def court_short(c):
    c = c.strip()
    if "ערעור" in c:
        return "ערעורים"
    return c.replace("הדרוזי ", "", 1).strip() if c.startswith("הדרוזי ") else (c or "לא צוין")


def court_phrase(c):
    return "בית הדין לערעורים" if c == "ערעורים" else f"בית הדין ב{c}"


def clean_label(s):
    return s.replace("~", "״").strip() or "לא צוין"


def decider(s):
    s = s.strip()
    if not s:
        return ""
    if "מנהלתית" in s:
        return ADMIN_LABEL
    return DECIDER_ALIASES.get(s, s)


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


def signed(v):
    r = round(v, 1)
    if r == 0:
        return "0.0%"
    return f"+{r:.1f}%" if r > 0 else f"{MINUS}{abs(r):.1f}%"


def decade_label(d, last_year):
    return rng(d, min(d + 9, last_year))


# ── preparation ─────────────────────────────────────────────────────────

def _prep_cases(df):
    raw_n = len(df)
    df = df.drop_duplicates()
    out = pd.DataFrame({
        "court": df["בית דין"].map(court_short),
        "topic": df["נושא תיק"].str.strip().replace("", "לא צוין"),
        "type": df["סוג תיק"].map(clean_label),
        "d": _dates(df["תאריך פתיחת תיק"].str.strip()),
        "status": df["סטטוס תיק"].str.strip(),
        "decision": df["החלטה"].str.strip(),
        "decider": df["נותן החלטה"].map(decider),
    })
    test = int((out["topic"] == TEST_TOPIC).sum())
    out = out[out["topic"] != TEST_TOPIC]
    out["y"] = out["d"].dt.year
    return out, raw_n - len(df), test


def _prep_contracts(df):
    raw_n = len(df)
    num = df["מספר חוזה"].str.strip()
    numbered = (num != "") & (num != "0")
    # Only numbered contracts can be told apart; identical number-less rows are separate contracts.
    dup = df.duplicated() & numbered
    df = df[~dup]
    out = pd.DataFrame({
        "court": df["בית דין"].map(court_short),
        "d": _dates(df["תאריך עריכת חוזה"].str.strip()),
        "f": _dates(df["תאריך יצירת תיק"].str.strip()),
        "registrar": df["רשם נישואין"].str.strip(),
    })
    undated = int(out["d"].isna().sum())
    out = out[out["d"].notna()].copy()
    out["y"] = out["d"].dt.year.astype(int)
    lag = (out["f"] - out["d"]).dt.days
    out["lead"] = -lag                                   # days the file was opened before the contract
    out["live"] = lag.abs() <= LIVE_LAG
    out["retro"] = lag > LIVE_LAG
    return out, raw_n - len(df), undated


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


def insight_inherit(share, k, last_full):
    if share is None or share < 0.3:
        return None
    lead = "רוב התיקים" if share > 0.5 else "הנושא הנפוץ ביותר"
    return (f"{lead} בבתי הדין הדרוזים עוסקים בצוואות ובירושות: ב-{last_full} נפתחו "
            f"{n(k)} תיקים כאלה — {pct(share * 100, 0)} מכלל התיקים.")


def insight_new_type(new_type):
    if not new_type:
        return None
    t, y0, k, share, last_full, jump = new_type
    s = (f"מ-{y0} נפתחים תיקי \"{t}\", שלא הופיעו קודם לכן: ב-{last_full} נפתחו {n(k)} "
         f"כאלה — {pct(share * 100, 0)} מכל התיקים.")
    if jump is not None and jump > 0.3:
        s += f" בשנה שבה הופיעו גדל מספר התיקים שנפתחו ב-{pct(jump * 100, 0)}."
    return s


def insight_admin(admin):
    if not admin:
        return None
    y0, share, last_full = admin
    if share < 0.1:
        return None
    return (f"מ-{y0} חלק גדול מההחלטות ניתן כהחלטה מנהלתית של מזכירות בית הדין ולא בידי "
            f"קאדי: ב-{last_full} — {pct(share * 100, 0)} מההחלטות.")


def insight_consent(rows):
    rows = [r for r in rows if r["consent"] + r["contested"] >= 50]
    if len(rows) < 4:
        return None
    first, last = rows[0], rows[-1]
    s0 = first["consent"] / (first["consent"] + first["contested"]) * 100
    s1 = last["consent"] / (last["consent"] + last["contested"]) * 100
    if abs(s1 - s0) < 5:
        trend = f"בדומה ל-{first['year']} ({pct(s0, 0)})"
    else:
        trend = f"לעומת {pct(s0, 0)} ב-{first['year']}"
    return (f"ב-{last['year']} {pct(s1, 0)} מתביעות הגירושין הוגשו בהסכמת שני בני הזוג, "
            f"{trend}.")


def insight_divorce(rows):
    rows = [r for r in rows if r["contracts"] >= 100]
    if len(rows) < 2:
        return None
    first, last = rows[0], rows[-1]
    r1 = last["divorce"] / last["contracts"] * 100
    r0 = first["divorce"] / first["contracts"] * 100
    trend = (f"בדומה ל-{first['year']} ({r0:.0f})" if abs(r1 - r0) < 3
             else f"לעומת {r0:.0f} ב-{first['year']}")
    return (f"ב-{last['year']} נפתחו {n(last['divorce'])} תיקי גירושין מול {n(last['contracts'])} "
            f"חוזי נישואין — כ-{r1:.0f} תיקי גירושין לכל 100 חוזים, {trend}.")


def insight_season(season_rows, labels):
    if len(season_rows) < 2:
        return None
    first, last = season_rows[0], season_rows[-1]
    peak = max(range(12), key=lambda i: (last["shares"][i], -i))
    w0 = sum(first["shares"][i] for i in (11, 0, 1))
    w1 = sum(last["shares"][i] for i in (11, 0, 1))
    s = (f"החתונות נחתמות בעיקר בקיץ: בשנים {labels[-1]} נערכו {pct(last['shares'][peak], 0)} "
         f"מחוזי הנישואין ב{MONTHS_HE[peak]}")
    if w0 - w1 >= 3:
        s += (f", ורק {pct(w1, 0)} בדצמבר עד פברואר — לעומת {pct(w0, 0)} "
              f"בשנים {labels[0]}")
    return s + "."


def insight_weekday(wd_rows, labels):
    if len(wd_rows) < 2:
        return None
    first, last = wd_rows[0], wd_rows[-1]
    top = max(range(7), key=lambda i: (last["shares"][i], -i))
    s1, s0 = last["shares"][top], first["shares"][top]
    if s1 < 100 * 1.5 / 7:
        return None
    s = f"יום {WEEKDAYS_HE[WEEK_ORDER[top]]} הוא יום עריכת החוזים המועדף: {pct(s1, 0)} מהחוזים בשנים {labels[-1]}"
    if s1 - s0 >= 5:
        s += f", לעומת {pct(s0, 0)} בשנים {labels[0]}"
    return s + "."


def insight_lead(lead_rows):
    if len(lead_rows) < 4:
        return None
    first, last = lead_rows[0], lead_rows[-1]
    if last["lead"] <= 0:
        return None
    trend = (f", לעומת {first['lead']} ימים ב-{first['year']}"
             if abs(last["lead"] - first["lead"]) >= 3 else "")
    return (f"תיק הנישואין נפתח לרוב לפני החתונה: ב-{last['year']} נפתח התיק בחציון {last['lead']} "
            f"ימים לפני עריכת החוזה{trend}.")


def insight_backfill(retro, total, first_y, entry_year, y_to):
    if retro < 1000 or total == 0:
        return None
    return (f"{n(retro)} חוזי נישואין ({pct(retro / total * 100, 0)} מהמאגר), שנערכו בין {first_y} "
            f"ל-{y_to}, הוזנו למערכת בדיעבד — רובם ב-{entry_year}. לחוזים אלה לא נרשמו מספר "
            f"חוזה ושם רשם.")


def insight_judges(top):
    if not top:
        return None
    name, share, last_full, court = top
    if share < 0.3:
        return None
    return (f"הקאדי {name} נתן ב-{last_full} {pct(share * 100, 0)} מההחלטות השיפוטיות "
            f"(ללא החלטות מנהלתיות), רובן ב{court_phrase(court)}.")


def insight_appeals(app_out):
    decided = sum(v for k, v in app_out if k in ("התקבל", "נדחה", "נמחק"))
    if decided < 100:
        return None
    d = dict(app_out)
    acc = d.get("התקבל", 0) / decided
    rej = d.get("נדחה", 0) / decided
    return (f"בבית הדין הדרוזי לערעורים, מבין {n(decided)} ערעורים שהוכרעו (התקבלו, נדחו או "
            f"נמחקו), {pct(acc * 100, 0)} התקבלו — כולל החזרה לבית הדין האזורי — ו-"
            f"{pct(rej * 100, 0)} נדחו.")


# ── compute ─────────────────────────────────────────────────────────────

def compute(frames):
    cases, dup_cases, test_rows = _prep_cases(frames["cases"])
    con, dup_con, undated = _prep_contracts(frames["contracts"])
    total_cases = len(cases)
    total_con = len(con)

    dated = cases[cases["d"].notna()]
    ref = dated["d"].max()
    first_d = dated["d"].min()
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = int(ref.year) - 1 if partial else int(ref.year)
    first_full = int(first_d.year) + (0 if (first_d.month == 1 and first_d.day <= 7) else 1)
    years_all = list(range(int(first_d.year), int(ref.year) + 1))
    full_years = [y for y in years_all if first_full <= y <= last_full]
    ref_cd = con["d"].max()
    regional = dated[dated["court"] != "ערעורים"]

    # ── cases by year and topic ──
    tcount = _sorted_counts(dated["topic"])
    top_topics = [t for t in tcount.index if t != "לא צוין" and tcount[t] >= MIN_TOPIC][:TOP_TOPICS]
    tg = dated["topic"].where(dated["topic"].isin(top_topics), "אחר")
    gy = dated.assign(g=tg).groupby(["y", "g"]).size().unstack(fill_value=0).reindex(years_all, fill_value=0)
    snames = top_topics + (["אחר"] if "אחר" in gy.columns else [])
    cases_year = {"x": [str(y) for y in years_all],
                  "series": [{"name": g, "data": [mask(v) for v in gy[g]]} for g in snames]}
    per_year = dated.groupby("y").size().reindex(years_all, fill_value=0)

    # YTD
    prev_year = int(ref.year) - 1
    ytd = int(((dated["y"] == ref.year) & (dated["d"] <= ref)).sum())
    try:
        prev_cut = ref.replace(year=prev_year)
    except ValueError:
        prev_cut = ref.replace(year=prev_year, day=28)
    ytd_prev = int(((dated["y"] == prev_year) & (dated["d"] <= prev_cut)).sum())
    ytd_ok = prev_year >= first_full and ytd_prev > 0

    # share of inheritance cases
    last_n = int(per_year.get(last_full, 0))
    inh_k = int(((dated["y"] == last_full) & (dated["topic"] == INHERIT_TOPIC)).sum())
    inh_share = inh_k / last_n if last_n else None

    # new case type that appeared mid-series
    ty_first = dated.groupby("type")["y"].min()
    last_types = _sorted_counts(dated[dated["y"] == last_full]["type"])
    new_type = None
    for t, k in last_types.items():
        y0 = int(ty_first[t])
        if y0 > first_full and last_n and k / last_n >= NEW_TYPE_SHARE:
            before = int(per_year.get(y0 - 1, 0))
            jump = (int(per_year.get(y0, 0)) / before - 1) if before else None
            new_type = (t, y0, int(k), k / last_n, last_full, jump)
            break

    # ── case types treemap (last N full years) ──
    t0 = max(first_full, last_full - TYPE_YEARS + 1)
    tw = dated[(dated["y"] >= t0) & (dated["y"] <= last_full)]
    twg = _sorted_counts(tw["topic"])
    tree = []
    for g in [x for x in twg.index if x != "לא צוין" and twg[x] >= MIN_TOPIC]:
        tc = _sorted_counts(tw[tw["topic"] == g]["type"])
        kids = [{"name": k, "value": int(v)} for k, v in tc.head(TREE_TYPES).items() if v >= SMALL]
        rest = int(tc.sum()) - sum(c["value"] for c in kids)
        if rest >= SMALL:
            kids.append({"name": "אחר", "value": rest})
        tree.append({"name": g, "value": int(twg[g]), "children": kids})
    tt = (tw.groupby(["type", "topic"]).size().reset_index(name="k")
            .sort_values(["k", "type", "topic"], ascending=[False, True, True]).head(TOP_TYPES))
    type_rows = [{"type": r["type"], "group": r["topic"], "count": mdisp(r["k"])} for _, r in tt.iterrows()]
    n_types = int(tw["type"].nunique())

    # ── topic mix per regional court ──
    rw = regional[(regional["y"] >= t0) & (regional["y"] <= last_full)]
    rcourts = sorted(rw["court"].unique(), key=lambda c: (-int((rw["court"] == c).sum()), c))
    mix_topics = [t for t in top_topics if t in set(rw["topic"])]
    rtg = rw["topic"].where(rw["topic"].isin(mix_topics), "אחר")
    ct = rw.assign(g=rtg).groupby(["court", "g"]).size()
    mix_names = mix_topics + (["אחר"] if (rtg == "אחר").any() else [])
    ctot = rw.groupby("court").size()
    court_mix = {"names": rcourts,
                 "series": [{"name": g, "data": [
                     (None if mask(ct.get((c, g), 0)) is None else
                      round(int(ct.get((c, g), 0)) / int(ctot[c]) * 100, 1)) for c in rcourts]}
                     for g in mix_names]}
    mix_table = [{"court": c, "total": n(ctot[c]),
                  "cells": [mdisp(ct.get((c, g), 0)) for g in mix_names]} for c in rcourts]
    div_by_court = {c: int(ct.get((c, DIVORCE_TOPIC), 0)) / int(ctot[c]) for c in rcourts}
    inh_by_court = {c: int(ct.get((c, INHERIT_TOPIC), 0)) / int(ctot[c]) for c in rcourts}

    # ── cases and contracts by court and year ──
    cy0 = max(first_full, last_full - COURT_YEARS + 1)
    cyears = list(range(cy0, last_full + 1))
    cc_cases = regional.groupby(["court", "y"]).size()
    cc_con = con.groupby(["court", "y"]).size()
    court_list = sorted(set(rcourts) | set(con["court"].unique()),
                        key=lambda c: (-int((con["court"] == c).sum()), c))
    court_series = []
    for c in court_list:
        court_series.append({"name": f"תיקים · {c}", "data": [int(cc_cases.get((c, y), 0)) for y in cyears]})
    for c in court_list:
        court_series.append({"name": f"חוזים · {c}", "data": [int(cc_con.get((c, y), 0)) for y in cyears]})
    courts_year = {"x": [str(y) for y in cyears], "series": court_series}
    court_table = [{"year": str(y), "cells": [n(cc_cases.get((c, y), 0)) for c in court_list]
                    + [n(cc_con.get((c, y), 0)) for c in court_list]} for y in cyears]
    court_cols = [f"תיקים · {c}" for c in court_list] + [f"חוזים · {c}" for c in court_list]
    con_share = {}
    if cyears:
        ly = con[con["y"] == last_full]
        for c in court_list:
            con_share[c] = (int((ly["court"] == c).sum()) / len(ly)) if len(ly) else 0

    # ── divorce: consent vs contested ──
    dv = dated[dated["topic"] == DIVORCE_TOPIC]
    consent = dv["type"].str.contains(CONSENT_KEY, regex=False)
    contested = dv["type"] == CONTESTED_TYPE
    dcy = dv[consent].groupby("y").size()
    dsy = dv[contested].groupby("y").size()
    doy = dv[~consent & ~contested].groupby("y").size()
    div_rows = [{"year": y, "consent": int(dcy.get(y, 0)), "contested": int(dsy.get(y, 0)),
                 "other": int(doy.get(y, 0))} for y in full_years]
    for r in div_rows:
        b = r["consent"] + r["contested"]
        r["share"] = round(r["consent"] / b * 100, 1) if b >= 20 else None
    divorce_chart = {"x": [str(r["year"]) for r in div_rows],
                     "consent": [mask(r["consent"]) for r in div_rows],
                     "contested": [mask(r["contested"]) for r in div_rows],
                     "other": [mask(r["other"]) for r in div_rows],
                     "share": [r["share"] for r in div_rows]}
    last_div = div_rows[-1] if div_rows else None

    # ── marriage vs divorce ──
    cy = con.groupby("y").size()
    div_year = dv.groupby("y").size()
    md_rows = [{"year": y, "contracts": int(cy.get(y, 0)), "divorce": int(div_year.get(y, 0))}
               for y in full_years]
    for r in md_rows:
        r["ratio"] = round(r["divorce"] / r["contracts"] * 100) if r["contracts"] >= 100 else None
    marriage_divorce = {"x": [str(r["year"]) for r in md_rows],
                        "contracts": [r["contracts"] for r in md_rows],
                        "divorce": [r["divorce"] for r in md_rows]}

    # ── outcomes by topic (regional courts) ──
    od = regional[regional["decision"] != ""]
    od = od.assign(o=od["decision"].map(outcome))
    og = _sorted_counts(od["topic"])
    otopics = [g for g in og.index if g != "לא צוין" and og[g] >= OUTCOME_MIN]
    otab = od.groupby(["topic", "o"]).size()
    out_rows = []
    for g in otopics:
        tot = int(og[g])
        shares = {o: round(int(otab.get((g, o), 0)) / tot * 100, 1) for o in OUTCOMES}
        out_rows.append({"name": g, "n": tot, "shares": shares,
                         "small": {o: 0 < int(otab.get((g, o), 0)) < SMALL for o in OUTCOMES}})
    used_out = [o for o in OUTCOMES if any(r["shares"][o] for r in out_rows)]
    outcomes_chart = {"names": [r["name"] for r in out_rows],
                      "series": [{"name": o, "data": [r["shares"][o] for r in out_rows]} for o in used_out]}
    status_rows = [(k, int(v)) for k, v in _sorted_counts(cases["status"].replace("", "לא צוין")).items()]
    closed_share = cases["status"].isin(CLOSED).mean() * 100 if total_cases else 0

    # ── who decides ──
    dd = dated[dated["decider"] != ""]
    dtot = _sorted_counts(dd["decider"])
    named = [x for x in dtot.index if x != ADMIN_LABEL][:TOP_DECIDERS]
    dorder = named + ([ADMIN_LABEL] if ADMIN_LABEL in dtot.index else [])
    dg = dd["decider"].where(dd["decider"].isin(dorder), "אחר")
    dy = dd.assign(g=dg).groupby(["y", "g"]).size().unstack(fill_value=0).reindex(years_all, fill_value=0)
    dnames = dorder + (["אחר"] if "אחר" in dy.columns else [])
    deciders_chart = {"x": [str(y) for y in years_all],
                      "series": [{"name": g, "data": [int(v) for v in dy[g]]} for g in dnames]}
    dmain = (dd.groupby(["decider", "court"]).size().reset_index(name="k")
               .sort_values(["decider", "k", "court"], ascending=[True, False, True])
               .drop_duplicates("decider").set_index("decider"))
    dyears = dd.groupby("decider")["y"].agg(["min", "max"])
    decider_rows = []
    for x in dorder:
        decider_rows.append({"name": x, "count": n(dtot[x]),
                             "years": rng(int(dyears.loc[x, "min"]), int(dyears.loc[x, "max"])),
                             "court": dmain.loc[x, "court"]})
    adm = dd[dd["decider"] == ADMIN_LABEL].groupby("y").size()
    tot_y = dd.groupby("y").size()
    admin_share_y = {int(y): int(adm.get(y, 0)) / int(tot_y[y]) for y in tot_y.index}
    admin = None
    if last_full in admin_share_y:
        big = [y for y in full_years if admin_share_y.get(y, 0) >= 0.1]
        if big:
            admin = (min(big), admin_share_y[last_full], last_full)
    jl = dd[(dd["y"] == last_full) & (dd["decider"] != ADMIN_LABEL)]
    top_judge = None
    if len(jl) >= 100:
        jc = _sorted_counts(jl["decider"])
        j = jc.index[0]
        jcourt = _sorted_counts(jl[jl["decider"] == j]["court"]).index[0]
        top_judge = (j, int(jc.iloc[0]) / len(jl), last_full, jcourt)

    # ── appeals court ──
    ap = dated[dated["court"] == "ערעורים"]
    a0 = max(int(first_d.year), int(ref.year) - APPEAL_YEARS + 1)
    ap_years = list(range(a0, int(ref.year) + 1))
    ap_y = ap.groupby("y").size()
    appeals_year = {"x": [str(y) for y in ap_years], "y": [mask(ap_y.get(y, 0)) for y in ap_years]}
    ap_out = [(k, int(v)) for k, v in _sorted_counts(ap[ap["decision"] != ""]["decision"].map(appeal_outcome)).items()]
    appeals_out = {"names": [k for k, _ in ap_out], "values": [mask(v) for _, v in ap_out]}
    appeals_total = len(ap)

    # ── marriage contracts: long series by entry route ──
    cyc = con.groupby("y").size().sort_index()
    peak = int(cyc.max()) if len(cyc) else 0
    con_start = int(cyc[cyc >= max(peak * 0.03, SMALL)].index.min()) if peak else int(ref_cd.year)
    early = int((con["y"] < con_start).sum())
    lyears = list(range(con_start, int(ref_cd.year) + 1))
    cr = con[con["y"] >= con_start]
    rt = cr.groupby(["y", "retro"]).size()
    con_year = {"x": [str(y) for y in lyears],
                "live": [int(rt.get((y, False), 0)) for y in lyears],
                "retro": [int(rt.get((y, True), 0)) for y in lyears],
                "zoom_start": str(max(con_start, int(ref_cd.year) - 39))}
    retro_n = int(con["retro"].sum())
    retro_entry = (int(_sorted_counts(con.loc[con["retro"], "f"].dt.year).index[0])
                   if retro_n else None)
    retro_to = int(con.loc[con["retro"], "y"].max()) if retro_n else None
    first_con = int(con["y"].min())

    # ── seasonality and weekday by decade ──
    decs = sorted(set((cr["y"] // 10 * 10).astype(int)))
    season_rows, wd_rows, dlabels = [], [], []
    for d0 in decs:
        sub = cr[(cr["y"] >= d0) & (cr["y"] < d0 + 10)]
        if len(sub) < DECADE_MIN:
            continue
        mcount = sub["d"].dt.month.value_counts()
        wcount = sub["d"].dt.dayofweek.value_counts()
        k = len(sub)
        season_rows.append({"n": k, "shares": [round(int(mcount.get(m, 0)) / k * 100, 1) for m in range(1, 13)]})
        wd_rows.append({"n": k, "shares": [round(int(wcount.get(i, 0)) / k * 100, 1) for i in WEEK_ORDER]})
        dlabels.append(decade_label(d0, int(ref_cd.year)))
    # Chart: up to SEASON_LINES decades spread evenly (always first and latest); the table keeps all.
    k_d = len(season_rows)
    if k_d <= SEASON_LINES:
        pick = list(range(k_d))
    else:
        pick = sorted({round(i * (k_d - 1) / (SEASON_LINES - 1)) for i in range(SEASON_LINES)})
    season = {"x": MONTHS_SHORT,
              "series": [{"name": dlabels[i], "data": season_rows[i]["shares"]} for i in pick]}
    weekday = {"names": dlabels, "days": [WEEKDAYS_HE[i] for i in WEEK_ORDER],
               "series": [{"name": WEEKDAYS_HE[WEEK_ORDER[i]], "data": [r["shares"][i] for r in wd_rows]}
                          for i in range(7)]}

    # ── month × year heatmap (live-era years) ──
    live_years = [y for y in range(con_start, int(ref_cd.year) + 1)
                  if int(((cr["y"] == y) & cr["live"]).sum()) >= LEAD_MIN]
    h0 = live_years[0] if live_years else int(ref_cd.year)
    hm = cr[cr["y"] >= h0]
    mc = hm.groupby([hm["y"], hm["d"].dt.month]).size()
    hyears = list(range(h0, int(ref_cd.year) + 1))
    cells = []
    for yi, y in enumerate(hyears):
        for mi in range(12):
            if y == ref_cd.year and mi + 1 > ref_cd.month:
                continue
            v = int(mc.get((y, mi + 1), 0))
            cells.append([mi, yi, "-" if mask(v) is None else v])
    con_heat = {"x": MONTHS_SHORT, "y": [str(y) for y in hyears], "cells": cells,
                "max": max([c[2] for c in cells if c[2] != "-"] or [1])}

    # ── lead time and registrars (real-time entries, full years) ──
    lv = con[con["live"] & (con["y"] <= last_full)]
    lead_med = lv.groupby("y")["lead"].median()
    lead_month = (lv["lead"] >= 30).groupby(lv["y"]).mean()
    lcount = lv.groupby("y").size()
    regf = lv[lv["registrar"] != ""]
    regs = regf.groupby("y")["registrar"].nunique()
    reg_fill = (lv["registrar"] != "").groupby(lv["y"]).mean()
    lead_rows = []
    lmax = int(lcount.max()) if len(lcount) else 0
    for y in sorted(int(v) for v in lcount.index):
        # Skip the system's start-up year(s): too few real-time entries to compare.
        if int(lcount[y]) < max(LEAD_MIN, lmax * 0.5):
            continue
        sub = regf[regf["y"] == y]
        top_share = (_sorted_counts(sub["registrar"]).head(REG_TOP).sum() / len(sub) * 100) if len(sub) else 0
        lead_rows.append({"year": y, "n": int(lcount[y]), "lead": int(round(float(lead_med[y]))),
                          "month": round(float(lead_month[y]) * 100, 1),
                          "registrars": int(regs.get(y, 0)), "fill": round(float(reg_fill[y]) * 100, 1),
                          "top": round(float(top_share), 1)})
    lead_chart = {"x": [str(r["year"]) for r in lead_rows], "lead": [r["lead"] for r in lead_rows],
                  "month": [r["month"] for r in lead_rows]}
    reg_chart = {"x": [str(r["year"]) for r in lead_rows], "registrars": [r["registrars"] for r in lead_rows],
                 "top": [r["top"] for r in lead_rows]}
    last_lead = lead_rows[-1] if lead_rows else None

    # ── insights ──
    rules = [
        ("ytd", insight_ytd(ytd, ytd_prev, ref, prev_year) if ytd_ok else None),
        ("inherit", insight_inherit(inh_share, inh_k, last_full)),
        ("new_type", insight_new_type(new_type)),
        ("admin", insight_admin(admin)),
        ("consent", insight_consent(div_rows)),
        ("divorce", insight_divorce(md_rows)),
        ("season", insight_season(season_rows, dlabels)),
        ("weekday", insight_weekday(wd_rows, dlabels)),
        ("lead", insight_lead(lead_rows)),
        ("backfill", insight_backfill(retro_n, total_con, first_con, retro_entry, retro_to)),
        ("judges", insight_judges(top_judge)),
        ("appeals", insight_appeals(ap_out)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── KPIs ──
    if ytd_ok:
        chg = (ytd / ytd_prev - 1) * 100
        ytd_tone = "brand" if abs(chg) < 3 else "info"
        ytd_disp = signed(chg)
    else:
        chg, ytd_disp, ytd_tone = None, "—", "brand"
    cons_share = last_div["share"] if last_div else None
    kpis = {
        "cases": {"value": total_cases, "display": n(total_cases), "tone": "brand"},
        "contracts": {"value": total_con, "display": n(total_con), "tone": "brand"},
        "ytd": {"value": ytd, "display": n(ytd), "tone": "brand"},
        "ytd_change": {"value": None if chg is None else round(chg, 1), "display": ytd_disp, "tone": ytd_tone},
        "inherit": {"value": None if inh_share is None else round(inh_share * 100, 1),
                    "display": "—" if inh_share is None else f"{inh_share * 100:.0f}%", "tone": "info"},
        "consent": {"value": cons_share, "display": "—" if cons_share is None else f"{cons_share:.0f}%",
                    "tone": "info" if cons_share is not None else "brand"},
        "lead": {"value": last_lead["lead"] if last_lead else None,
                 "display": n(last_lead["lead"]) if last_lead else "—", "tone": "brand"},
        "registrars": {"value": last_lead["registrars"] if last_lead else None,
                       "display": n(last_lead["registrars"]) if last_lead else "—", "tone": "brand"},
    }

    partial_note = f" {ref.year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    first_partial = first_full > int(first_d.year)
    nreg = len(rcourts)
    area_txt = "; ".join(f"{court_phrase(c)} — {COURT_AREA[c]}" for c in court_list if c in COURT_AREA)
    labels = {
        "lede": (f"{n(total_cases)} תיקים שנפתחו בבתי הדין הדתיים הדרוזים מאז {d_he(first_d)} — "
                 f"{nreg} בתי דין אזוריים ובית הדין לערעורים — ו-{n(total_con)} חוזי נישואין שנרשמו "
                 f"בהם, רובם מ-{con_start} ואילך. התיקים עוסקים בענייני המעמד האישי של בני העדה "
                 f"הדרוזית: צוואות וירושות, גירושין, אפוטרופסות, ילדים ונישואין. הנתונים מעודכנים עד "
                 f"{d_he(ref)}; הדף מציג סיכומים בלבד, ללא פרטים על הצדדים, ותאים של פחות מחמישה "
                 f"תיקים בחיתוך משולב אינם מוצגים במספרם."),
        "notes": " ".join(x for x in [
            (f"{n(dup_cases + dup_con)} שורות כפולות זהות (עם מספר חוזה) הוסרו." if dup_cases + dup_con else ""),
            (f"{n(test_rows)} תיקי בדיקה של המערכת הוצאו." if test_rows else ""),
            (f"{n(undated)} רשומות חוזה ללא תאריך עריכה אינן נספרות." if undated else ""),
        ] if x),
        "ytd_kpi": f"תיקים שנפתחו ב-{ref.year} (עד {d_short(ref)})",
        "ytd_change_kpi": f"לעומת התקופה המקבילה ב-{prev_year}",
        "inherit_kpi": f"תיקי צוואות וירושות מכלל התיקים ({last_full})",
        "consent_kpi": (f"תביעות גירושין בהסכמה ({last_div['year']})" if last_div else "תביעות גירושין בהסכמה"),
        "lead_kpi": (f"ימים מפתיחת תיק הנישואין ועד החוזה, חציון ({last_lead['year']})" if last_lead
                     else "ימים מפתיחת תיק הנישואין ועד החוזה"),
        "registrars_kpi": (f"רשמי נישואין פעילים ({last_lead['year']})" if last_lead else "רשמי נישואין פעילים"),
        "cases_year_note": (f"תיקים לפי שנת פתיחה ונושא, {rng(int(first_d.year), int(ref.year))}."
                            + (f" {first_d.year} — שנה חלקית, מ-{d_he(first_d)}." if first_partial else "")
                            + partial_note + " נושאים קטנים מאוחדים ב\"אחר\"."),
        "cases_year_aria": f"גרף עמודות מוערמות: תיקים שנפתחו בכל שנה לפי נושא, {rng(int(first_d.year), int(ref.year))}.",
        "tree_note": (f"נושאי התיקים וסוגי התיקים שבתוכם, {rng(t0, last_full)} — {n(len(tw))} תיקים "
                      f"ב-{n(n_types)} סוגים. לחיצה על נושא מתמקדת בו."),
        "tree_aria": f"מפת עץ: תיקים לפי נושא וסוג תיק, {rng(t0, last_full)}.",
        "types_caption": f"סוגי התיקים הנפוצים, {rng(t0, last_full)}.",
        "mix_note": (f"חלקו של כל נושא מהתיקים בכל בית דין אזורי, {rng(t0, last_full)}. {area_txt}."),
        "mix_aria": f"גרף עמודות מוערמות: התפלגות נושאי התיקים בכל בית דין אזורי, באחוזים, {rng(t0, last_full)}.",
        "mix_caption": f"תיקים לפי בית דין ונושא, {rng(t0, last_full)}.",
        "courts_note": (f"תיקים שנפתחו וחוזי נישואין שנערכו בכל בית דין אזורי, {rng(cy0, last_full)}. "
                        f"לחיצה על שם סדרה במקרא מסתירה אותה."),
        "courts_aria": f"גרף קווים: תיקים וחוזי נישואין לפי בית דין ושנה, {rng(cy0, last_full)}.",
        "courts_caption": f"תיקים וחוזי נישואין לפי בית דין ושנה, {rng(cy0, last_full)}.",
        "divorce_note": (f"תביעות גירושין לפי סוג, {rng(full_years[0], last_full) if full_years else ''}: "
                         f"בהסכמת שני בני הזוג, תביעת גירושין רגילה ותיקים אחרים בנושא (פיצויי גירושין, "
                         f"שלום בית, התרת חוזה ועוד). הקו — שיעור התביעות בהסכמה."),
        "divorce_aria": "גרף עמודות מוערמות: תיקי גירושין לפי סוג ושנה, וקו של שיעור הגירושין בהסכמה.",
        "divorce_caption": "תיקי גירושין לפי סוג ושנה.",
        "md_note": (f"חוזי נישואין ותיקי גירושין שנפתחו בכל שנה מלאה. תיקי גירושין לכל מאה חוזים הוא "
                    f"יחס גס בין שני רישומים — לא שיעור גירושין."),
        "md_aria": "גרף קווים: חוזי נישואין ותיקי גירושין לפי שנה.",
        "md_caption": "חוזי נישואין, תיקי גירושין והיחס ביניהם לפי שנה.",
        "outcomes_note": (f"התפלגות ההחלטות בתיקי בתי הדין האזוריים, בנושאים שבהם הוכרעו לפחות "
                          f"{OUTCOME_MIN} תיקים. {pct(closed_share, 1)} מכלל התיקים סגורים או הועברו."),
        "outcomes_aria": "גרף עמודות אופקיות מוערמות: התפלגות ההחלטות לפי נושא התיק, באחוזים.",
        "outcomes_caption": "התפלגות ההחלטות לפי נושא התיק, באחוזים.",
        "deciders_note": (f"מספר ההחלטות לפי שנת פתיחת התיק ונותן ההחלטה — הקאדים (בתפקידם הציבורי) "
                          f"והחלטות מנהלתיות של המזכירות.{partial_note}"),
        "deciders_aria": "גרף עמודות מוערמות: החלטות לפי שנה ונותן ההחלטה.",
        "deciders_caption": "החלטות לפי נותן ההחלטה, שנות הפעילות ובית הדין העיקרי.",
        "appeals_note": (f"{n(appeals_total)} תיקים נפתחו בבית הדין הדרוזי לערעורים — לפי שנה "
                         f"({rng(a0, int(ref.year))}) ולפי ההחלטה שנרשמה בהם.{partial_note}"),
        "appeals_year_aria": f"גרף עמודות: תיקים בבית הדין לערעורים לפי שנה, {rng(a0, int(ref.year))}.",
        "appeals_year_caption": "תיקים בבית הדין לערעורים לפי שנה.",
        "appeals_out_aria": "גרף עמודות: החלטות בבית הדין לערעורים לפי תוצאה.",
        "appeals_out_caption": "החלטות בבית הדין לערעורים לפי תוצאה.",
        "con_year_note": (f"חוזי נישואין לפי שנת עריכת החוזה, {rng(con_start, int(ref_cd.year))}"
                          + (f" ({n(early)} חוזים מוקדמים יותר אינם מוצגים)" if early else "")
                          + f". חוזים שהוזנו למערכת יותר משנה אחרי עריכתם מסומנים בנפרד"
                          + (f" — רובם הוזנו ב-{retro_entry}" if retro_entry else "")
                          + ". שנים עם מעט חוזים עשויות לשקף רישום היסטורי חסר, לא ירידה בנישואין."),
        "con_year_aria": f"גרף עמודות מוערמות: חוזי נישואין לפי שנה ואופן הרישום, {rng(con_start, int(ref_cd.year))}.",
        "season_note": "חלקו של כל חודש מחוזי הנישואין בעשורים נבחרים (באחוזים); הטבלה מציגה את כל העשורים.",
        "season_aria": "גרף קווים: התפלגות חוזי הנישואין לפי חודש, לכל עשור.",
        "season_caption": "חוזי נישואין לפי חודש ועשור, באחוזים.",
        "weekday_note": "חלקו של כל יום בשבוע מחוזי הנישואין בכל עשור (באחוזים).",
        "weekday_aria": "גרף עמודות מוערמות: התפלגות חוזי הנישואין לפי יום בשבוע, לכל עשור.",
        "weekday_caption": "חוזי נישואין לפי יום בשבוע ועשור, באחוזים.",
        "heat_note": (f"חוזי נישואין לפי חודש ושנה, {rng(h0, int(ref_cd.year))}. חוזים מהשבועות "
                      f"האחרונים עשויים עדיין שלא להופיע."),
        "heat_aria": f"מפת חום: חוזי נישואין לפי חודש ושנה, {rng(h0, int(ref_cd.year))}.",
        "lead_note": (f"חוזים שנרשמו בזמן אמת (תיק הנישואין נפתח עד שנה לפני או אחרי החוזה), שנים מלאות: "
                      f"כמה ימים לפני עריכת החוזה נפתח התיק (חציון) ושיעור התיקים שנפתחו חודש ומעלה מראש; "
                      f"מספר רשמי הנישואין שערכו חוזים וחלקם של {REG_TOP} הרשמים הפעילים ביותר."),
        "lead_aria": "גרף קווים: ימים חציוניים מפתיחת תיק הנישואין ועד עריכת החוזה, לפי שנה.",
        "reg_aria": "גרף עמודות וקו: רשמי נישואין פעילים וחלקם של הרשמים הפעילים ביותר, לפי שנה.",
        "lead_caption": "זמן מפתיחת התיק ועד החוזה ורשמי הנישואין, לפי שנה.",
        "reg_top_col": f"חלק {REG_TOP} הרשמים המובילים",
    }

    tables = {
        "types": type_rows,
        "mix": mix_table,
        "mix_cols": mix_names,
        "courts": court_table,
        "court_cols": court_cols,
        "divorce": [{"year": str(r["year"]), "consent": mdisp(r["consent"]), "contested": mdisp(r["contested"]),
                     "other": mdisp(r["other"]),
                     "share": "—" if r["share"] is None else f"{r['share']:.1f}%"} for r in div_rows],
        "md": [{"year": str(r["year"]), "contracts": n(r["contracts"]), "divorce": n(r["divorce"]),
                "ratio": "—" if r["ratio"] is None else str(r["ratio"])} for r in md_rows],
        "outcomes": [{"name": r["name"], "n": n(r["n"]),
                      "cells": [("<5" if r["small"][o] else f"{r['shares'][o]:.1f}%") for o in used_out]}
                     for r in out_rows],
        "outcome_cols": used_out,
        "status": [{"name": k, "count": mdisp(v)} for k, v in status_rows],
        "deciders": decider_rows,
        "appeals_year": [{"year": a, "count": mdisp(ap_y.get(int(a), 0))} for a in appeals_year["x"]],
        "appeals_out": [{"name": k, "count": mdisp(v)} for k, v in ap_out],
        "season": [{"month": MONTHS_HE[m], "cells": [f"{r['shares'][m]:.1f}%" for r in season_rows]}
                   for m in range(12)],
        "weekday": [{"day": WEEKDAYS_HE[WEEK_ORDER[i]], "cells": [f"{r['shares'][i]:.1f}%" for r in wd_rows]}
                    for i in range(7)],
        "decades": dlabels,
        "lead": [{"year": str(r["year"]), "n": n(r["n"]), "lead": str(r["lead"]), "month": f"{r['month']:.1f}%",
                  "registrars": n(r["registrars"]), "top": f"{r['top']:.1f}%"} for r in lead_rows],
    }

    charts = {
        "cases_year": cases_year,
        "tree": tree,
        "court_mix": court_mix,
        "courts_year": courts_year,
        "divorce": divorce_chart,
        "marriage_divorce": marriage_divorce,
        "outcomes": outcomes_chart,
        "deciders": deciders_chart,
        "appeals_year": appeals_year,
        "appeals_out": appeals_out,
        "con_year": con_year,
        "season": season,
        "weekday": weekday,
        "con_heat": con_heat,
        "lead": lead_chart,
        "registrars": reg_chart,
    }

    return {
        "agent_data": {
            "summary_he": (f"פעילות בתי הדין הדתיים הדרוזים: {n(total_cases)} תיקים בענייני מעמד אישי "
                           f"מאז {first_d.year} ו-{n(total_con)} חוזי נישואין — לפי שנה, בית דין, נושא, "
                           f"החלטה וקאדי, ועונתיות החתונות לאורך העשורים."),
            "dataset_kind": "timeseries",
            "related_ids": ["3b05b6ac-53f6-44e7-afd8-141831cf398b",
                            "da374239-7f83-43bc-a60f-36fc8380a093",
                            "cdf9391c-e51d-48d7-aacc-2dade6e63c09",
                            "13449cdd-9d02-44cf-b298-82f598369cd7",
                            "eda6d5e4-b6ed-478e-a92b-71e0baab84b6"],
            "suggested_tags": ["בתי דין דרוזיים", "מעמד אישי", "נישואין", "גירושין",
                               "ירושה וצוואות", "דרוזים", "משרד המשפטים"],
            "temporal_coverage": f"{first_con}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"outcomes": bool(out_rows), "appeals": appeals_total > 0,
                  "divorce": any((r["consent"] + r["contested"]) for r in div_rows),
                  "lead": bool(lead_rows), "mix": bool(rcourts)},
    }
