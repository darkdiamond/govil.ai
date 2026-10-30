"""ריבית בנק ישראל: the policy rate since 1994, its decisions, cycles and corridor.

Input: the whole BoI `BR` dataflow (one row per series per day). Series:
  MNT_RIB_BOI_D   the BoI (policy) rate, % per year
  MNT_RIB_EFYB_D  the policy rate as an effective annual yield (compounded)
  MNT_WIN_DEP_D   deposit window (the corridor's floor)
  MNT_WIN_LN_D    lending window (the corridor's ceiling)
  MNT_SHIR_D      SHIR, the shekel overnight rate (equal to the policy rate on
                  every common business day so far; blank on non-business days)

A "decision" is a day the policy rate differs from the day before (the date
the new rate took effect). Every number is derived from the rows; a series
missing from the data drops its views instead of failing the page.
"""
import pandas as pd

POLICY = "MNT_RIB_BOI_D"
EFFECTIVE = "MNT_RIB_EFYB_D"
DEP = "MNT_WIN_DEP_D"
LOAN = "MNT_WIN_LN_D"
SHIR = "MNT_SHIR_D"
# Israeli banks' prime rate is the BoI rate plus a fixed 1.5 percentage
# points (a banking convention, not a series in this dataflow).
PRIME_SPREAD = 1.5
RECENT_DECISIONS = 12
TOP_HOLDS = 10
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _pct(v):
    """3.25 → '3.25%', 0.1 → '0.10%': rates are quoted to two decimals."""
    return f"{v:.2f}%"


def _pp(v):
    """A change in percentage points, unsigned, trimmed: 0.25, 0.5, 1."""
    s = f"{abs(v):.2f}".rstrip("0").rstrip(".")
    return s


def _signed(v):
    return ("+" if v > 0 else "−") + _pp(v)


def _date(t):
    return f"{t.day}.{t.month}.{t.year}"


def _month(t):
    return f"{MONTHS_HE[t.month - 1]} {t.year}"


def _plural(n, one, many):
    return one if n == 1 else f"{n:,} {many}"


def _series(df, code):
    s = df[df["code"] == code][["t", "v"]].dropna()
    s = s.drop_duplicates("t", keep="last").sort_values("t", kind="stable")
    return s.set_index("t")["v"]


def _prepare(df):
    df = df.copy()
    df["code"] = df["SERIES_CODE"].str.strip()
    df["t"] = pd.to_datetime(df["TIME_PERIOD"].str.strip(), errors="coerce", format="%Y-%m-%d")
    df["v"] = pd.to_numeric(df["OBS_VALUE"].str.strip(), errors="coerce")
    df = df.dropna(subset=["t"])
    # A same-day duplicate keeps one deterministic value whatever the row order.
    return df.sort_values(["code", "t", "v"], kind="stable")


def _decisions(rate):
    """Change points: (date in effect, new rate, change) for every move."""
    prev = rate.shift(1)
    moved = rate[(prev.notna()) & (rate != prev)]
    return [(t, float(v), float(v - prev[t])) for t, v in moved.items()]


def _runs(decisions):
    """Consecutive decisions in the same direction = one cycle."""
    runs = []
    for t, v, d in decisions:
        sign = 1 if d > 0 else -1
        if runs and runs[-1]["sign"] == sign:
            r = runs[-1]
            r.update(end=t, to=v, n=r["n"] + 1)
        else:
            runs.append({"sign": sign, "start": t, "end": t, "from": v - d, "to": v, "n": 1})
    return runs


def _holds(rate, decisions):
    """Periods at one rate: from a decision (or the series start) to the next."""
    starts = [(rate.index[0], float(rate.iloc[0]))] + [(t, v) for t, v, _ in decisions]
    last = rate.index[-1]
    out = []
    for i, (t, v) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else last
        ongoing = i + 1 == len(starts)
        out.append({"start": t, "end": end, "rate": v,
                    "days": int((end - t).days), "ongoing": ongoing})
    return out


# ── insights ─────────────────────────────────────────────────────────────


def insight_latest(decisions, current, last_date):
    if not decisions:
        return None
    t, v, d = decisions[-1]
    word = "העלה" if d > 0 else "הוריד"
    streak = 1
    for _, _, dd in reversed(decisions[:-1]):
        if (dd > 0) == (d > 0):
            streak += 1
        else:
            break
    tail = ""
    if streak >= 2:
        kind = "העלאה" if d > 0 else "הורדה"
        tail = f" זו ה{kind} ה-{streak} ברציפות."
    return (f"בנק ישראל {word} את הריבית ב-{_pp(d)} נקודת אחוז ל-{_pct(v)}, "
            f"בתוקף מ-{_date(t)}.{tail} נכון ל-{_date(last_date)} הריבית {_pct(current)}.")


def insight_cycle(runs):
    """The cycle now under way, against the one before it."""
    if len(runs) < 2:
        return None
    cur, prev = runs[-1], runs[-2]
    if cur["n"] < 2:
        return None
    cur_w = "הורדות" if cur["sign"] < 0 else "העלאות"
    prev_w = "העלאות" if prev["sign"] > 0 else "הורדות"
    return (f"מחזור ה{cur_w} הנוכחי החל ב{_month(cur['start'])}: {cur['n']:,} {cur_w} "
            f"מ-{_pct(cur['from'])} ל-{_pct(cur['to'])}. קדם לו מחזור של {prev['n']:,} {prev_w} "
            f"מ-{_pct(prev['from'])} ל-{_pct(prev['to'])} ({_month(prev['start'])} עד {_month(prev['end'])}).")


def insight_fastest_hike(runs):
    hikes = [r for r in runs if r["sign"] > 0 and r["n"] >= 2]
    if not hikes:
        return None
    # Steepest = largest total rise; ties go to the earlier cycle.
    best = sorted(hikes, key=lambda r: (-(r["to"] - r["from"]), r["start"]))[0]
    months = (best["end"].year - best["start"].year) * 12 + best["end"].month - best["start"].month
    if months <= 0:
        return None
    return (f"מחזור ההעלאות החד ביותר מאז ראשית הנתונים: {_pp(best['to'] - best['from'])} נקודות אחוז "
            f"ב-{best['n']:,} החלטות בתוך {months:,} חודשים, מ-{_pct(best['from'])} ל-{_pct(best['to'])} "
            f"({_month(best['start'])} עד {_month(best['end'])}).")


def insight_longest_hold(holds, min_days=180):
    if not holds:
        return None
    h = sorted(holds, key=lambda x: (-x["days"], x["start"]))[0]
    if h["days"] < min_days:
        return None
    still = ", ונמשכת עד היום" if h["ongoing"] else f" ועד {_date(h['end'])}"
    return (f"התקופה הארוכה ביותר ללא שינוי: {h['days']:,} ימים בריבית {_pct(h['rate'])}, "
            f"מ-{_date(h['start'])}{still}.")


def insight_range(rate):
    if rate.empty or rate.max() == rate.min():
        return None
    hi_t, lo_v = rate.idxmax(), rate.min()
    lo_first = rate[rate == lo_v].index[0]
    return (f"מאז {rate.index[0].year} נעה הריבית בין {_pct(rate.max())} "
            f"({_month(hi_t)}) לבין {_pct(lo_v)} (לראשונה ב{_month(lo_first)}).")


def insight_this_year(decisions, last_date):
    """Decisions this calendar year so far, against the per-year average."""
    if not decisions:
        return None
    first_year = decisions[0][0].year
    years = last_date.year - first_year
    if years < 3:
        return None
    this = [d for t, _, d in decisions if t.year == last_date.year]
    past = [d for t, _, d in decisions if t.year < last_date.year]
    avg = len(past) / years
    if not this:
        return f"בשנת {last_date.year} (עד {_date(last_date)}) לא שונתה הריבית."
    hikes = sum(1 for d in this if d > 0)
    cuts = len(this) - hikes
    parts = []
    if cuts:
        parts.append(_plural(cuts, "הורדה אחת", "הורדות"))
    if hikes:
        parts.append(_plural(hikes, "העלאה אחת", "העלאות"))
    net = sum(this)
    return (f"בשנת {last_date.year} (עד {_date(last_date)}): {' ו'.join(parts)}, "
            f"שינוי מצטבר של {_signed(net)} נקודות אחוז. "
            f"הממוצע ב-{first_year} עד {last_date.year - 1}: {avg:.1f} החלטות שינוי בשנה.")


def insight_corridor(dep, loan, rate):
    if dep.empty or loan.empty:
        return None
    t = min(dep.index[-1], loan.index[-1], rate.index[-1])
    if t not in rate.index or t not in dep.index or t not in loan.index:
        return None
    lo, hi, p = float(dep[t]), float(loan[t]), float(rate[t])
    return (f"מסדרון הריבית: חלון הפיקדונות {_pct(lo)} וחלון ההלוואות {_pct(hi)}, "
            f"{_pp(p - lo)} נקודת אחוז מתחת לריבית ו-{_pp(hi - p)} מעליה.")


# ── charts ───────────────────────────────────────────────────────────────


def _step_points(s):
    """A step series as its change points plus the last day: [[date, v], …]."""
    if s.empty:
        return []
    keep = s[(s != s.shift(1))]
    pts = [[t.strftime("%Y-%m-%d"), round(float(v), 4)] for t, v in keep.items()]
    if pts[-1][0] != s.index[-1].strftime("%Y-%m-%d"):
        pts.append([s.index[-1].strftime("%Y-%m-%d"), round(float(s.iloc[-1]), 4)])
    return pts


def compute(frames):
    df = _prepare(frames["rates"])
    rate = _series(df, POLICY)
    if rate.empty:
        raise ValueError("no BoI policy-rate observations (MNT_RIB_BOI_D)")
    eff = _series(df, EFFECTIVE)
    dep, loan = _series(df, DEP), _series(df, LOAN)
    shir = _series(df, SHIR)

    last_date = rate.index[-1]
    current = float(rate.iloc[-1])
    decisions = _decisions(rate)
    runs = _runs(decisions)
    holds = _holds(rate, decisions)
    y0, y1 = rate.index[0].year, last_date.year

    rules = [
        ("latest", insight_latest(decisions, current, last_date)),
        ("cycle", insight_cycle(runs)),
        ("fastest_hike", insight_fastest_hike(runs)),
        ("longest_hold", insight_longest_hold(holds)),
        ("this_year", insight_this_year(decisions, last_date)),
        ("range", insight_range(rate)),
        ("corridor", insight_corridor(dep, loan, rate)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # KPIs. Tone: a cut eases credit (ok), a hike tightens it (warn).
    last_t, _, last_d = decisions[-1] if decisions else (rate.index[0], current, 0.0)
    tone = "ok" if last_d < 0 else "warn" if last_d > 0 else "brand"
    days_since = int((last_date - last_t).days)
    kpis = {
        "rate": {"value": current, "display": _pct(current), "tone": tone},
        "last_change": {"value": last_d, "display": _signed(last_d) if last_d else "0",
                        "tone": tone},
        "prime": {"value": round(current + PRIME_SPREAD, 4),
                  "display": _pct(current + PRIME_SPREAD), "tone": "brand"},
        "days": {"value": days_since, "display": f"{days_since:,}", "tone": "brand"},
    }
    if not eff.empty:
        kpis["effective"] = {"value": round(float(eff.iloc[-1]), 4),
                             "display": _pct(float(eff.iloc[-1])), "tone": "brand"}

    # 1. the policy rate since the start, as steps.
    history = _step_points(rate)
    year_end = rate.groupby(rate.index.year).last()
    year_table = [{"year": int(y), "rate": _pct(v),
                   "n": sum(1 for t, _, _ in decisions if t.year == y)}
                  for y, v in year_end.items()]
    year_table.reverse()

    # 2. the latest decisions.
    recent = decisions[-RECENT_DECISIONS:]
    recent_chart = {
        "x": [_date(t) for t, _, _ in recent],
        "y": [round(d, 4) for _, _, d in recent],
        "to": [round(v, 4) for _, v, _ in recent],
    }
    recent_table = [{"date": _date(t), "from": _pct(v - d), "to": _pct(v), "change": _signed(d)}
                    for t, v, d in reversed(recent)]

    # 3. hikes and cuts per year (every year in the span, zeros included).
    years = list(range(y0, y1 + 1))
    per_year = {
        "x": [str(y) for y in years],
        "hikes": [sum(1 for t, _, d in decisions if t.year == y and d > 0) for y in years],
        "cuts": [sum(1 for t, _, d in decisions if t.year == y and d < 0) for y in years],
        "net": [round(sum(d for t, _, d in decisions if t.year == y), 4) for y in years],
    }

    # 4. cycles (runs of same-direction decisions, two or more).
    cycles = [r for r in runs if r["n"] >= 2]
    cycle_chart = {
        "x": [_month(r["start"]) for r in cycles],
        "y": [round(r["to"] - r["from"], 4) for r in cycles],
        "n": [r["n"] for r in cycles],
        "span": [f"{_pct(r['from'])} ← {_pct(r['to'])}" for r in cycles],
    }
    cycle_table = [{"start": _month(r["start"]), "end": _month(r["end"]),
                    "kind": "העלאות" if r["sign"] > 0 else "הורדות", "n": r["n"],
                    "from": _pct(r["from"]), "to": _pct(r["to"]),
                    "change": _signed(r["to"] - r["from"])} for r in reversed(cycles)]

    # 5. longest holds.
    top = sorted(holds, key=lambda h: (-h["days"], h["start"]))[:TOP_HOLDS]
    holds_chart = {
        # Year span only: a full date next to a percent reorders under bidi.
        "names": [f"{_pct(h['rate'])} ({h['start'].year}-{h['end'].year})" for h in top],
        "days": [h["days"] for h in top],
        "ongoing": [h["ongoing"] for h in top],
    }
    holds_table = [{"rate": _pct(h["rate"]), "start": _date(h["start"]),
                    "end": "נמשכת" if h["ongoing"] else _date(h["end"]),
                    "days": f"{h['days']:,}"} for h in top]
    gaps = [h["days"] for h in holds if not h["ongoing"]]
    median_gap = int(pd.Series(gaps).median()) if gaps else None

    # 6. the corridor (windows) around the rate, from when it exists.
    corridor = None
    if not dep.empty and not loan.empty:
        start = max(dep.index[0], loan.index[0])
        window = pd.concat({"dep": dep, "rate": rate, "loan": loan}, axis=1).loc[start:].dropna()
        if not window.empty:
            width = (window["loan"] - window["rate"]).round(4)
            spells = width[width != width.shift(1)]
            corridor = {
                "dep": _step_points(window["dep"]),
                "rate": _step_points(window["rate"]),
                "loan": _step_points(window["loan"]),
                "table": [{"from": _date(t), "width": _pp(w)} for t, w in reversed(list(spells.items()))],
                "start_year": window.index[0].year,
                "width_now": _pp(float(width.iloc[-1])),
            }

    # 7. SHIR vs the policy rate (where both exist).
    shir_note = None
    if not shir.empty:
        both = pd.concat({"shir": shir, "rate": rate}, axis=1).dropna()
        if not both.empty:
            diff = (both["shir"] - both["rate"]).abs()
            shir_note = {
                "since": _month(shir.index[0]),
                "days": int(len(both)),
                "equal_days": int((diff < 1e-9).sum()),
                "last": _pct(float(shir.iloc[-1])),
                "last_date": _date(shir.index[-1]),
            }

    n_hikes = sum(1 for _, _, d in decisions if d > 0)
    n_cuts = len(decisions) - n_hikes
    move = ("הורדה" if last_d < 0 else "העלאה") if last_d else ""
    summary = (f"ריבית בנק ישראל היום: {_pct(current)} (פריים {_pct(current + PRIME_SPREAD)}). "
               + (f"ה{move} האחרונה ({_pp(last_d)} נקודת אחוז) בתוקף מ-{_date(last_t)}. " if move else "")
               + f"בעמוד: כל {len(decisions):,} שינויי הריבית מאז {y0}, מחזורים ותקופות ללא שינוי.")
    lede = (f"הריבית שקובע בנק ישראל (הריבית המוניטרית) מ-{_date(rate.index[0])} ועד {_date(last_date)}: "
            f"{len(decisions):,} שינויים, {n_hikes:,} העלאות ו-{n_cuts:,} הורדות. "
            "הנתונים מתוך המאגר הסטטיסטי של בנק ישראל ומתעדכנים מדי יום.")

    hi_t = rate.idxmax()
    labels = {
        "lede": lede,
        "rate_kpi": f"ריבית בנק ישראל ({_date(last_date)})",
        "last_change_kpi": f"השינוי האחרון בנקודות אחוז ({_date(last_t)})",
        "prime_kpi": f"ריבית הפריים (ריבית בנק ישראל ועוד {_pp(PRIME_SPREAD)})",
        "days_kpi": "ימים מאז השינוי האחרון",
        "effective_kpi": "הריבית בתשואה שנתית אפקטיבית",
        "history_note": (f"כל שינוי בריבית מ-{y0} עד {y1}. השיא: {_pct(rate.max())} ב{_month(hi_t)}; "
                         f"השפל: {_pct(rate.min())}. אפשר לגרור את פס הזמן כדי להתמקד בתקופה."),
        "history_aria": (f"גרף מדרגות: ריבית בנק ישראל מ-{y0} עד {y1}, {len(decisions):,} שינויים. "
                         f"שיא {_pct(rate.max())} ב{_month(hi_t)}, כיום {_pct(current)}."),
        "year_caption": f"ריבית בנק ישראל בסוף כל שנה ומספר השינויים בשנה, {y0} עד {y1}",
        "recent_note": (f"{len(recent):,} ההחלטות האחרונות ששינו את הריבית: גובה העמודה הוא השינוי "
                        "בנקודות אחוז (מעל הקו העלאה, מתחתיו הורדה)."),
        "recent_aria": (f"תרשים עמודות: {len(recent):,} שינויי הריבית האחרונים, "
                        f"האחרון {_signed(last_d)} נקודות אחוז ב-{_date(last_t)}."),
        "recent_caption": f"{len(recent):,} שינויי הריבית האחרונים",
        "per_year_note": (f"מספר ההעלאות וההורדות בכל שנה. {n_hikes:,} העלאות ו-{n_cuts:,} הורדות מאז {y0}"
                          + (f"; השנה {y1} חלקית (עד {_date(last_date)})." if last_date.month < 12 or last_date.day < 31 else ".")),
        "per_year_aria": (f"תרשים עמודות מוערמות: העלאות והורדות של ריבית בנק ישראל לפי שנה, "
                          f"{y0} עד {y1}."),
        "per_year_caption": f"העלאות, הורדות והשינוי המצטבר לפי שנה, {y0} עד {y1}",
        "cycles_note": (f"מחזור הוא רצף של שתי החלטות או יותר באותו כיוון. {len(cycles):,} מחזורים מאז {y0}; "
                        "העמודה מציגה את השינוי המצטבר בנקודות אחוז."),
        "cycles_aria": f"תרשים עמודות: {len(cycles):,} מחזורי העלאה והורדה של הריבית מאז {y0}.",
        "cycles_caption": f"מחזורי העלאה והורדה של ריבית בנק ישראל מאז {y0}",
        "holds_note": (f"{len(top):,} התקופות הארוכות ביותר שבהן הריבית לא השתנתה"
                       + (f". משך חציוני בין שתי החלטות: {median_gap:,} ימים." if median_gap is not None else ".")),
        "holds_aria": (f"תרשים עמודות אופקי: {len(top):,} התקופות הארוכות ביותר ללא שינוי ריבית, "
                       f"הארוכה {top[0]['days']:,} ימים." if top else "תרשים עמודות אופקי: תקופות ללא שינוי ריבית."),
        "holds_caption": f"{len(top):,} התקופות הארוכות ביותר ללא שינוי בריבית",
    }
    if corridor:
        labels.update(
            corridor_note=(f"חלון הפיקדונות וחלון ההלוואות של בנק ישראל תוחמים את הריבית מלמטה ומלמעלה "
                           f"(נתונים מ-{corridor['start_year']}). כיום המרווח {corridor['width_now']} "
                           "נקודת אחוז לכל צד."),
            corridor_aria=(f"גרף מדרגות: חלון הפיקדונות, ריבית בנק ישראל וחלון ההלוואות מ-{corridor['start_year']} "
                           f"עד {y1}; המרווח כיום {corridor['width_now']} נקודת אחוז."),
            corridor_caption="רוחב מסדרון הריבית (נקודות אחוז מעל ומתחת לריבית) לפי תקופה",
        )
    if shir_note:
        same = shir_note["equal_days"] == shir_note["days"]
        labels["shir_note"] = (
            f"שי\"ר (ריבית השקל ללילה) מתפרסמת מ{shir_note['since']}. "
            + (f"בכל {shir_note['days']:,} ימי העסקים שבהם פורסמו שתיהן היא הייתה זהה לריבית בנק ישראל"
               if same else
               f"ב-{shir_note['equal_days']:,} מתוך {shir_note['days']:,} ימי העסקים שבהם פורסמו שתיהן היא הייתה זהה לריבית בנק ישראל")
            + f"; האחרונה: {shir_note['last']} ({shir_note['last_date']}).")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["ריבית", "מדיניות מוניטרית", "ריבית פריים", "בנק ישראל", "משכנתאות"],
            "temporal_coverage": f"{rate.index[0].strftime('%Y-%m-%d')}/{last_date.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "history": history,
            "recent": recent_chart,
            "per_year": per_year,
            "cycles": cycle_chart,
            "holds": holds_chart,
            "corridor": corridor and {k: corridor[k] for k in ("dep", "rate", "loan")},
        },
        "tables": {
            "years": year_table,
            "recent": recent_table,
            "per_year": [{"year": x, "hikes": h, "cuts": c, "net": _signed(n) if n else "0"}
                         for x, h, c, n in zip(per_year["x"], per_year["hikes"],
                                               per_year["cuts"], per_year["net"], strict=True)][::-1],
            "cycles": cycle_table,
            "holds": holds_table,
            "corridor": corridor["table"] if corridor else [],
        },
        "flags": {"corridor": bool(corridor), "effective": not eff.empty, "shir": bool(shir_note)},
        "insights": insights,
        "labels": labels,
    }
