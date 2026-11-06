"""Bus trips, planned vs actual, one row per planned trip (Ministry of Transport).

Each row is one scheduled bus trip: operator, planned date + minute
(`trip_dt`, `trip_time`), the recorded actual start and end
(`bitzua_history_start_dt` / `_end_dt`, "NULL"/"null" when not recorded) and
`erua_hachraga_ind` (1 = the trip was flagged as part of an exceptional
event). One resource per calendar year; the recipe reads the newest one.

The page answers the rider's question: does the bus leave on time, at which
hours and days does it not, which operators do better, and how long a trip
takes. The monthly per-line picture across years lives on the sibling
aggregate dataset's page (e4a5e2d7), so this page stays on what only
trip-level rows can show: minutes of delay, hour of day, weekday, single
days and trip duration.

Status of a planned trip (seconds of actual start minus planned minute):
  not executed  no recorded start
  early         left more than EARLY_MIN minutes before the planned time
  late          left LATE_MIN or more minutes after it
  on time       everything else
"""

import numpy as np
import pandas as pd
from govlib import fmt
from govlib.frame import OTHER

LATE_MIN = 5          # minutes after the planned time = late
EARLY_MIN = 3         # minutes before it = early
DUR_MAX_MIN = 300     # a recorded trip longer than this is a recording fault
MIN_HOUR_TRIPS = 300  # an hour/weekday cell with fewer planned trips gets no rate
TOP_OPS = 18          # at most this many operators by name; the rest fold into "אחר"
MIN_OP_SHARE = 0.01   # operators shown by name and compared carry >= 1% of trips
EVENT_DAY_SHARE = 0.05  # a day where >= 5% of trips were flagged is an event day

DAYS_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]

# Delay buckets in seconds: [lo, hi) and their labels.
DELAY_EDGES = [-10**9, -EARLY_MIN * 60, -60, 0, 60, 120, 180, LATE_MIN * 60, 600, 1200, 1800, 10**9]
DELAY_LABELS = [
    f"יותר מ-{EARLY_MIN} דק׳ לפני",
    f"1-{EARLY_MIN} דק׳ לפני",
    "עד דקה לפני",
    "עד דקה אחרי",
    "1-2 דק׳ אחרי",
    "2-3 דק׳ אחרי",
    f"3-{LATE_MIN} דק׳ אחרי",
    f"{LATE_MIN}-10 דק׳ אחרי",
    "10-20 דק׳ אחרי",
    "20-30 דק׳ אחרי",
    "30 דק׳ ומעלה אחרי",
]
DUR_EDGES = [0, 15, 30, 45, 60, 90, 120, 180, DUR_MAX_MIN + 1e-9]
DUR_LABELS = ["עד 15 דק׳", "15-30 דק׳", "30-45 דק׳", "45-60 דק׳", "60-90 דק׳",
              "90-120 דק׳", "120-180 דק׳", f"180-{DUR_MAX_MIN} דק׳"]

S_ONTIME, S_LATE, S_EARLY, S_MISS = 0, 1, 2, 3


def _p(v) -> float:
    return round(float(v) * 100, 2)


def _rates(g: pd.DataFrame) -> pd.DataFrame:
    """Per-group planned count and status shares (0-100)."""
    out = pd.DataFrame({"n": g["n"]})
    for col in ("ontime", "late", "early", "miss"):
        out[col] = g[col] / g["n"] * 100
    return out


def _status_counts(df: pd.DataFrame, keys) -> pd.DataFrame:
    s = df["status"]
    g = pd.DataFrame({
        "n": 1,
        "ontime": (s == S_ONTIME).astype(np.int32),
        "late": (s == S_LATE).astype(np.int32),
        "early": (s == S_EARLY).astype(np.int32),
        "miss": (s == S_MISS).astype(np.int32),
    })
    for k in keys:
        g[k] = df[k].array
    return g.groupby(keys, sort=True, observed=True).sum()


def _r1(v):
    return None if v is None or pd.isna(v) else round(float(v), 1)


def _min_he(v: float) -> str:
    return fmt.num_he(v, 1)


def _period(first: pd.Timestamp, last: pd.Timestamp) -> str:
    if (first.year, first.month) == (last.year, last.month):
        return fmt.month_he(first)
    if first.year == last.year:
        return f"{fmt.MONTHS_HE[first.month - 1]} עד {fmt.month_he(last)}"
    return f"{fmt.month_he(first)} עד {fmt.month_he(last)}"


def _hour_label(h: int) -> str:
    return f"{h:02d}:00"


def _parsed(col: pd.Series, how) -> tuple[np.ndarray, np.ndarray]:
    """Parse a string column through its distinct values (5M rows, a few
    thousand to two million distinct): (codes, parsed uniques). Code -1 is
    impossible here (no NA in str frames); unparseable values parse to NaT."""
    codes, uniq = pd.factorize(col, sort=False)
    return codes, how(pd.Series(uniq, dtype=object).astype(str).str.strip())


def _ts(fmt_: str):
    return lambda u: pd.to_datetime(u, format=fmt_, errors="coerce").to_numpy(dtype="datetime64[s]")


def compute(frames):
    # Pop the input so each string column is freed once parsed: the raw frame
    # is most of the memory this recipe uses (5M+ rows of str).
    raw = frames.pop("trips")
    n_raw = len(raw)

    c, u = _parsed(raw.pop("trip_dt"), _ts("%Y-%m-%d"))
    date = u[c]
    c, u = _parsed(raw.pop("trip_time"), _ts("%H:%M"))
    tod_u = u
    c_tod = c
    c, u = _parsed(raw.pop("bitzua_history_start_dt"), _ts("%Y-%m-%d %H:%M:%S"))
    start = u[c]
    c, u = _parsed(raw.pop("bitzua_history_end_dt"), _ts("%Y-%m-%d %H:%M:%S"))
    end = u[c]
    c, u = _parsed(raw.pop("erua_hachraga_ind"), lambda x: (x == "1").to_numpy())
    event = u[c]
    c, u = _parsed(raw.pop("operator_nm"), lambda x: x.to_numpy())
    op_codes, op_names = c, u
    del raw, c, u

    tod_min = pd.Series(tod_u).dt.hour.to_numpy() * 60 + pd.Series(tod_u).dt.minute.to_numpy()
    tod_ok = ~np.isnat(tod_u)
    ok = ~np.isnat(date) & tod_ok[c_tod]
    n_bad_plan = int((~ok).sum())
    tod_minutes = np.where(tod_ok, tod_min, 0).astype(np.int64)[c_tod]
    del tod_min

    plan = date.astype(np.int64) + tod_minutes * 60  # seconds
    delay_s = np.where(np.isnat(start), np.nan, start.astype(np.int64) - plan).astype(np.float64)
    del plan
    dur_s = end.astype(np.int64) - start.astype(np.int64)
    bad_end = np.isnat(end) | np.isnat(start) | (end < np.datetime64("2000-01-01"))
    dur_min = np.where(bad_end | (dur_s <= 0) | (dur_s > DUR_MAX_MIN * 60), np.nan, dur_s / 60).astype(np.float32)
    del dur_s, bad_end, start, end

    # Names were stripped per distinct value, so " דן" and "דן" are one category.
    op_cat = pd.Categorical(op_names[op_codes])
    del op_codes, op_names

    df = pd.DataFrame({
        "op": op_cat,
        "date": pd.to_datetime(date).astype("datetime64[s]"),
        "hour": (tod_minutes // 60).astype(np.int8),
        "delay": delay_s,
        "dur": dur_min,
        "event": event,
    })
    del op_cat, date, tod_minutes, delay_s, dur_min, event
    if n_bad_plan:
        df = df[ok]
    del ok
    df["dow"] = ((df["date"].dt.dayofweek + 1) % 7).astype(np.int8)  # 0 = Sunday
    st = np.full(len(df), S_ONTIME, dtype=np.int8)
    d = df["delay"].to_numpy()
    st[d >= LATE_MIN * 60] = S_LATE
    st[d < -EARLY_MIN * 60] = S_EARLY
    st[np.isnan(d)] = S_MISS
    df["status"] = st
    del d

    n = len(df)
    if n == 0:
        raise ValueError("no trips with a valid planned date and time")
    cnt = np.bincount(df["status"].to_numpy(), minlength=4)
    n_ontime, n_late, n_early, n_miss = (int(cnt[i]) for i in (S_ONTIME, S_LATE, S_EARLY, S_MISS))
    executed = df["delay"].dropna()
    if executed.empty:  # every start time missing: an export fault, not a page
        raise ValueError("no trip has a recorded start time")
    med_delay = float(executed.median())
    p90_delay = float(executed.quantile(0.9)) / 60
    med_delay_min = med_delay / 60
    durs = df["dur"].dropna()
    med_dur = float(durs.median()) if len(durs) else None
    n_event = int(df["event"].sum())
    ev_miss = int(((df["status"] == S_MISS) & df["event"]).sum())

    first, last = df["date"].min(), df["date"].max()
    period = _period(first, last)
    n_days = int(df["date"].nunique())

    # ---- months (with a partial-month flag from the data's own calendar)
    mon = df["date"].dt.to_period("M")
    df["month"] = mon.dt.year.astype(np.int32) * 100 + mon.dt.month.astype(np.int32)
    del mon
    mstat = _rates(_status_counts(df, ["month"]))
    mdays = df.groupby("month")["date"].nunique()
    months_rows = []
    partial_last = False
    for i, (m, r) in enumerate(mstat.iterrows()):
        y, mo = divmod(int(m), 100)
        cal_days = pd.Timestamp(year=y, month=mo, day=1).days_in_month
        partial = int(mdays[m]) < cal_days
        if i == len(mstat) - 1:
            partial_last = partial
        label = fmt.MONTHS_HE[mo - 1] + f" {y}" + (" (חלקי)" if partial else "")
        months_rows.append([label, fmt.int_he(r["n"]), fmt.pct_of(r["ontime"]), fmt.pct_of(r["late"]),
                            fmt.pct_of(r["early"]), fmt.pct_of(r["miss"])])

    # ---- delay distribution
    delay_counts = np.histogram(executed.to_numpy(), bins=DELAY_EDGES)[0]
    delay_chart = {
        "x": DELAY_LABELS + ["לא בוצעה"],
        "y": [int(v) for v in delay_counts] + [n_miss],
        "share": [round(int(v) / n * 100, 2) for v in delay_counts] + [round(n_miss / n * 100, 2)],
        "kind": ["early" if lo == DELAY_EDGES[0] else "late" if lo >= LATE_MIN * 60 else "ok"
                 for lo in DELAY_EDGES[:-1]] + ["miss"],
    }
    delay_rows = [[x, fmt.int_he(y), fmt.pct_of(s, 2)] for x, y, s in
                  zip(delay_chart["x"], delay_chart["y"], delay_chart["share"])]

    # ---- patterns (hour, weekday, operator, duration) leave out trips flagged
    # as an exceptional event: one flagged day would otherwise drive a
    # weekday's or an operator's rate. Disclosed in every such section.
    base = df[~df["event"]] if n_event < n else df

    # ---- by hour
    hstat = _rates(_status_counts(base, ["hour"]))
    hdelay = base.groupby("hour")["delay"].quantile(0.9) / 60
    hdur = base.groupby("hour")["dur"]
    hdur_q = pd.DataFrame({"p25": hdur.quantile(0.25), "p50": hdur.median(), "p75": hdur.quantile(0.75),
                           "cnt": hdur.count()})
    hours = list(range(24))
    hour_chart = {"x": [_hour_label(h) for h in hours], "n": [], "late": [], "miss": [], "notok": []}
    hour_rows = []
    dur_hour = {"x": [_hour_label(h) for h in hours], "p25": [], "p50": [], "p75": []}
    dur_rows = []
    for h in hours:
        if h in hstat.index:
            r = hstat.loc[h]
            nn = int(r["n"])
        else:
            r, nn = None, 0
        rated = nn >= MIN_HOUR_TRIPS
        hour_chart["n"].append(nn)
        hour_chart["late"].append(_r1(r["late"]) if rated else None)
        hour_chart["miss"].append(_r1(r["miss"]) if rated else None)
        hour_chart["notok"].append(_r1(100 - r["ontime"]) if rated else None)
        if nn:
            hour_rows.append([_hour_label(h), fmt.int_he(nn),
                              fmt.pct_of(r["late"]) if rated else "–",
                              fmt.pct_of(r["miss"]) if rated else "–",
                              fmt.num_he(hdelay.get(h), 1) if rated and pd.notna(hdelay.get(h)) else "–"])
        q = hdur_q.loc[h] if h in hdur_q.index else None
        if q is not None and q["cnt"] >= MIN_HOUR_TRIPS:
            dur_hour["p25"].append(_r1(q["p25"]))
            dur_hour["p50"].append(_r1(q["p50"]))
            dur_hour["p75"].append(_r1(q["p75"]))
            dur_rows.append([_hour_label(h), fmt.int_he(q["cnt"]), fmt.num_he(q["p50"], 0),
                             fmt.num_he(q["p25"], 0), fmt.num_he(q["p75"], 0)])
        else:
            dur_hour["p25"].append(None)
            dur_hour["p50"].append(None)
            dur_hour["p75"].append(None)

    # ---- weekday x hour heat (share not on time)
    wh = _rates(_status_counts(base, ["dow", "hour"]))
    cells = []
    for (dw, h), r in wh.iterrows():
        if r["n"] >= MIN_HOUR_TRIPS:
            cells.append([int(h), int(dw), round(100 - float(r["ontime"]), 1), int(r["n"])])
    heat_vals = [c[2] for c in cells]
    heat = {"x": [_hour_label(h) for h in hours], "y": DAYS_HE, "cells": cells,
            "min": 0, "max": float(np.ceil(max(heat_vals))) if heat_vals else 1}

    # ---- weekday
    wstat = _rates(_status_counts(base, ["dow"]))
    wdays = base.groupby("dow")["date"].nunique()
    week_chart = {"x": [], "avg": [], "notok": [], "miss": [], "late": []}
    week_rows = []
    for dw in range(7):
        if dw not in wstat.index:
            continue
        r = wstat.loc[dw]
        avg = r["n"] / int(wdays[dw])
        week_chart["x"].append(DAYS_HE[dw])
        week_chart["avg"].append(int(np.floor(avg + 0.5)))
        week_chart["notok"].append(_r1(100 - r["ontime"]))
        week_chart["miss"].append(_r1(r["miss"]))
        week_chart["late"].append(_r1(r["late"]))
        week_rows.append([DAYS_HE[dw], fmt.int_he(avg), fmt.pct_of(r["ontime"]), fmt.pct_of(r["late"]),
                          fmt.pct_of(r["miss"])])

    # ---- daily series
    dstat = _rates(_status_counts(df, ["date"]))
    dev = df.groupby("date")["event"].sum()
    daily = {"x": [], "n": [], "miss": [], "late": [], "event": [], "label": []}
    for dt, r in dstat.iterrows():
        daily["x"].append(dt.strftime("%d.%m.%Y"))
        daily["label"].append(f"יום {DAYS_HE[(dt.dayofweek + 1) % 7]}, {fmt.d_he(dt)}")
        daily["n"].append(int(r["n"]))
        daily["miss"].append(_r1(r["miss"]))
        daily["late"].append(_r1(r["late"]))
        daily["event"].append(int(dev[dt]))

    # ---- operators
    ostat = _rates(_status_counts(base, ["op"]))
    ostat = ostat.loc[sorted(ostat.index, key=lambda k: (-int(ostat.loc[k, "n"]), str(k)))]
    odelay = base.dropna(subset=["delay"]).groupby("op", observed=True)["delay"]
    op_p90 = odelay.quantile(0.9) / 60
    op_dur = base.groupby("op", observed=True)["dur"].median()
    names = [str(k) for k in ostat.index]
    n_base = int(ostat["n"].sum())
    shown = [k for k in names if ostat.loc[k, "n"] >= n_base * MIN_OP_SHARE][:TOP_OPS]
    if len(names) - len(shown) <= 1:
        shown = names
    rest = [k for k in names if k not in shown]
    op_rows = []
    op_chart = {"x": [], "ontime": [], "late": [], "early": [], "miss": [], "n": []}

    def _op_row(label, sub):
        tot = sub["n"].sum()
        vals = {c: (sub[c] * sub["n"]).sum() / tot for c in ("ontime", "late", "early", "miss")}
        return tot, vals

    for k in shown + ([OTHER] if rest else []):
        if k == OTHER:
            tot, vals = _op_row(k, ostat.loc[rest])
            p90 = dmed = None
        else:
            r = ostat.loc[k]
            tot = r["n"]
            vals = {c: r[c] for c in ("ontime", "late", "early", "miss")}
            p90, dmed = op_p90.get(k), op_dur.get(k)
        op_chart["x"].append(k)
        op_chart["n"].append(int(tot))
        for c in ("ontime", "late", "early", "miss"):
            op_chart[c].append(round(float(vals[c]), 2))
        op_rows.append([k, fmt.int_he(tot), fmt.pct_of(vals["ontime"]), fmt.pct_of(vals["late"]),
                        fmt.pct_of(vals["early"]), fmt.pct_of(vals["miss"]),
                        fmt.num_he(p90, 1) if p90 is not None and pd.notna(p90) else "–",
                        fmt.num_he(dmed, 0) if dmed is not None and pd.notna(dmed) else "–"])
    # chart order: best on-time share first (ties by name), "אחר" last
    order = sorted(range(len(op_chart["x"])),
                   key=lambda i: (op_chart["x"][i] == OTHER, -op_chart["ontime"][i], op_chart["x"][i]))
    op_chart = {c: [v[i] for i in order] for c, v in op_chart.items()}
    # The on-time share dominates every bar; start the axis below the lowest
    # one (a multiple of 10) so the late / not-run segments stay readable.
    op_chart["axis_min"] = int(max(0, np.floor((min(op_chart["ontime"]) - 2) / 10) * 10))

    # ---- trip duration distribution
    bdurs = base["dur"].dropna()
    n_dur_bad = int((base["status"] != S_MISS).sum() - len(bdurs))
    dur_counts = (np.histogram(bdurs.to_numpy(), bins=DUR_EDGES)[0] if len(bdurs)
                  else np.zeros(len(DUR_LABELS), dtype=int))
    dtot = max(int(dur_counts.sum()), 1)
    dur_chart = {"x": DUR_LABELS, "y": [int(v) for v in dur_counts],
                 "share": [round(int(v) / dtot * 100, 2) for v in dur_counts]}
    dur_dist_rows = [[x, fmt.int_he(y), fmt.pct_of(s)] for x, y, s in
                     zip(dur_chart["x"], dur_chart["y"], dur_chart["share"])]

    # ---- exceptional-event days
    ev_days = []
    if n_event:
        evd = df[df["event"]].groupby("date").agg(ev=("event", "size"),
                                                  miss=("status", lambda s: int((s == S_MISS).sum())))
        evd["tot"] = dstat["n"].reindex(evd.index)
        evd = evd.reset_index()
        evd = evd.sort_values(["ev", "date"], ascending=[False, True], kind="stable").head(10)
        for _, r in evd.iterrows():
            ev_days.append([f"{r['date'].strftime('%d.%m.%Y')} ({DAYS_HE[(r['date'].dayofweek + 1) % 7]})",
                            fmt.int_he(r["ev"]), fmt.pct(r["ev"] / r["tot"]), fmt.pct(r["miss"] / r["ev"])])
    n_event_days = int((dev / dstat["n"] >= EVENT_DAY_SHARE).sum())
    normal = ~df["event"]
    miss_normal = float((df.loc[normal, "status"] == S_MISS).mean()) if normal.any() else None

    # ---------------- insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    add("overall",
        f"ב{period} תוכננו {fmt.int_he(n)} נסיעות אוטובוס. {fmt.pct(n_ontime / n)} מהן יצאו בזמן, "
        f"{fmt.pct(n_late / n)} יצאו באיחור של {LATE_MIN} דקות ומעלה ו-{fmt.pct(n_miss / n)} לא בוצעו כלל.")

    rated_h = [(h, hour_chart["notok"][h], hour_chart["n"][h]) for h in hours if hour_chart["notok"][h] is not None]
    busy = [x for x in rated_h if x[2] >= n / 24 / 2]
    if len(busy) >= 4:
        worst = max(busy, key=lambda x: (x[1], -x[0]))
        best = min(busy, key=lambda x: (x[1], x[0]))
        if worst[1] >= best[1] * 1.5 and worst[1] - best[1] >= 1:
            add("hour",
                f"השעה הבעייתית ביותר היא {_hour_label(worst[0])}: {fmt.pct_of(worst[1])} מהנסיעות שתוכננו "
                f"לצאת בה לא יצאו בזמן או לא בוצעו, לעומת {fmt.pct_of(best[1])} בשעה {_hour_label(best[0])} "
                f"(ללא אירועים חריגים).")

    if len(week_chart["x"]) >= 5:
        wi = max(range(len(week_chart["x"])), key=lambda i: (week_chart["notok"][i], -i))
        bi = min(range(len(week_chart["x"])), key=lambda i: (week_chart["notok"][i], i))
        if week_chart["notok"][wi] - week_chart["notok"][bi] >= 1:
            add("weekday",
                f"יום {week_chart['x'][wi]} הוא היום החלש בשבוע: {fmt.pct_of(week_chart['notok'][wi])} מהנסיעות "
                f"לא יצאו בזמן או לא בוצעו, לעומת {fmt.pct_of(week_chart['notok'][bi])} ביום "
                f"{week_chart['x'][bi]} (ללא אירועים חריגים).")

    big = ostat[ostat["n"] >= n_base * MIN_OP_SHARE]
    if len(big) >= 3:
        bk = sorted(big.index, key=lambda k: (-float(big.loc[k, "ontime"]), str(k)))
        hi_k, lo_k = bk[0], bk[-1]
        gap = float(big.loc[hi_k, "ontime"] - big.loc[lo_k, "ontime"])
        if gap >= 2:
            add("operators",
                f"בין המפעילים הגדולים ({fmt.pct(MIN_OP_SHARE, 0)} מהנסיעות ומעלה), אצל {hi_k} יצאו בזמן "
                f"{fmt.pct_of(big.loc[hi_k, 'ontime'])} מהנסיעות ואצל {lo_k} רק {fmt.pct_of(big.loc[lo_k, 'ontime'])}, "
                f"ו-{fmt.pct_of(big.loc[lo_k, 'miss'])} מהנסיעות של {lo_k} לא בוצעו (ללא אירועים חריגים).")

    if n_event and miss_normal is not None and n_miss:
        ev_rate = ev_miss / n_event
        if ev_rate >= miss_normal * 2:
            add("events",
                f"{fmt.int_he(n_event)} נסיעות ({fmt.pct(n_event / n)}) סומנו במאגר כחלק מאירוע חריג. "
                f"{fmt.pct(ev_rate, 0)} מהן לא בוצעו, לעומת {fmt.pct(miss_normal)} משאר הנסיעות, "
                f"והן מהוות {fmt.pct(ev_miss / n_miss, 0)} מכל הנסיעות שלא בוצעו.")

    if len(dstat) >= 7:
        di = dstat["miss"].idxmax()
        med_miss = float(dstat["miss"].median())
        top = float(dstat.loc[di, "miss"])
        if med_miss > 0 and top >= med_miss * 3 and top >= 5:
            ev_share = float(dev[di] / dstat.loc[di, "n"])
            tail = (f", ו-{fmt.pct(ev_share, 0)} מנסיעות היום סומנו כאירוע חריג" if ev_share >= EVENT_DAY_SHARE
                    else "")
            add("worst_day",
                f"היום עם שיעור הביטולים הגבוה ביותר היה יום {DAYS_HE[(di.dayofweek + 1) % 7]}, {fmt.d_he(di)}: "
                f"{fmt.pct_of(top)} מהנסיעות לא בוצעו, פי {fmt.num_he(top / med_miss, 0)} מיום רגיל{tail}.")

    if dur_rows:
        dvals = [(h, dur_hour["p50"][h]) for h in hours if dur_hour["p50"][h] is not None
                 and hour_chart["n"][h] >= n / 24 / 2]
        if len(dvals) >= 4:
            lo_h = min(dvals, key=lambda x: (x[1], x[0]))
            hi_h = max(dvals, key=lambda x: (x[1], -x[0]))
            if hi_h[1] >= lo_h[1] * 1.15:
                add("duration",
                    f"נסיעה שיוצאת ב-{_hour_label(hi_h[0])} נמשכת בחציון {fmt.num_he(hi_h[1], 0)} דקות, "
                    f"לעומת {fmt.num_he(lo_h[1], 0)} דקות בנסיעה שיוצאת ב-{_hour_label(lo_h[0])}.")

    if n_early and n_early / n >= 0.001:
        add("early",
            f"{fmt.int_he(n_early)} נסיעות ({fmt.pct(n_early / n, 2)}) יצאו יותר מ-{EARLY_MIN} דקות לפני "
            f"השעה שבלוח הזמנים, כך שנוסע שהגיע לתחנה בזמן החמיץ אותן.")

    if p90_delay >= LATE_MIN:
        add("tail",
            f"בחציון יצא האוטובוס {_min_he(med_delay_min)} דקות אחרי השעה המתוכננת, "
            f"אבל אחת מכל עשר נסיעות שבוצעו יצאה באיחור של {_min_he(p90_delay)} דקות או יותר.")
    elif n_miss > n_late:
        add("tail",
            f"האיחור הטיפוסי קטן: בחציון {_min_he(med_delay_min)} דקות, ו-90% מהנסיעות שבוצעו יצאו עד "
            f"{_min_he(p90_delay)} דקות אחרי השעה שבלוח. הבעיה הגדולה יותר היא נסיעות שלא בוצעו כלל: "
            f"{fmt.int_he(n_miss)}, לעומת {fmt.int_he(n_late)} שאיחרו {LATE_MIN} דקות ומעלה.")
    else:
        add("tail",
            f"האיחור הטיפוסי קטן: בחציון {_min_he(med_delay_min)} דקות, ו-90% מהנסיעות שבוצעו יצאו עד "
            f"{_min_he(p90_delay)} דקות אחרי השעה שבלוח.")

    # ---------------- KPIs
    ontime_share = n_ontime / n
    miss_share = n_miss / n
    late_share = n_late / n

    def tone_good(v, ok_at, warn_at):
        return "ok" if v >= ok_at else "warn" if v >= warn_at else "danger"

    def tone_bad(v, ok_below, warn_below):
        return "ok" if v < ok_below else "warn" if v < warn_below else "danger"

    span = (f"{first.month:02d}.{first.year}" if (first.year, first.month) == (last.year, last.month)
            else f"{first.month:02d}.{first.year}–{last.month:02d}.{last.year}")
    kpis = {
        "planned": {"value": n, "display": fmt.int_he(n), "tone": "brand"},
        "ontime": {"value": round(ontime_share * 100, 1), "display": fmt.pct(ontime_share),
                   "tone": tone_good(ontime_share, 0.95, 0.9)},
        "miss": {"value": round(miss_share * 100, 2), "display": fmt.pct(miss_share),
                 "tone": tone_bad(miss_share, 0.01, 0.03)},
        "late": {"value": round(late_share * 100, 2), "display": fmt.pct(late_share),
                 "tone": tone_bad(late_share, 0.02, 0.05)},
        "med_delay": {"value": round(med_delay_min, 1), "display": fmt.num_he(med_delay_min, 1),
                      "tone": "info"},
        "p90_delay": {"value": round(p90_delay, 1), "display": fmt.num_he(p90_delay, 1),
                      "tone": "warn" if p90_delay >= LATE_MIN else "brand"},
        "med_dur": {"value": round(med_dur or 0, 0), "display": fmt.num_he(med_dur or 0, 0), "tone": "brand"},
        "span": {"value": n_days, "display": span, "tone": "brand"},
    }

    # ---------------- labels
    ontime_def = (f"בזמן: יציאה עד {LATE_MIN} דקות אחרי השעה שבלוח הזמנים ולא יותר מ-{EARLY_MIN} דקות לפניה. "
                  f"לא בוצעה: לא נרשמה יציאה בפועל.")
    lede = (f"המאגר מתעד כל נסיעת אוטובוס מתוכננת בתחבורה הציבורית לצד שעת היציאה והסיום בפועל. "
            f"ב{period} ({fmt.int_he(n_days)} ימים) תוכננו {fmt.int_he(n)} נסיעות: "
            f"{fmt.pct(ontime_share)} יצאו בזמן, {fmt.pct(late_share)} באיחור של {LATE_MIN} דקות ומעלה, "
            f"{fmt.pct(n_early / n)} הקדימו ו-{fmt.pct(miss_share)} לא בוצעו. "
            f"בחציון יצא האוטובוס {_min_he(med_delay_min)} דקות אחרי השעה שבלוח"
            + (f", ונסיעה נמשכה {fmt.num_he(med_dur, 0)} דקות." if med_dur else ".")
            ).strip()
    excluded = []
    if n_bad_plan:
        excluded.append(f"{fmt.int_he(n_bad_plan)} שורות ללא תאריך או שעה מתוכננים תקינים לא נכללו.")
    ex_note = (f" לא כולל {fmt.int_he(n_event)} נסיעות שסומנו כאירוע חריג." if base is not df else "")
    labels = {
        "lede": lede + (" " + " ".join(excluded) if excluded else ""),
        "definition": ontime_def,
        "kpi_planned": f"נסיעות מתוכננות ({period})",
        "kpi_ontime": "יצאו בזמן",
        "kpi_miss": "לא בוצעו",
        "kpi_late": f"איחור של {LATE_MIN} דקות ומעלה",
        "kpi_med_delay": "איחור חציוני ביציאה (דקות)",
        "kpi_p90_delay": "איחור בעשירון העליון (דקות)",
        "kpi_med_dur": "משך נסיעה חציוני (דקות)",
        "kpi_span": f"תקופת הנתונים ({fmt.int_he(n_days)} ימים)",
        "delay_note": (f"כמה דקות אחרי (או לפני) השעה שבלוח הזמנים יצאה כל נסיעה. אדום: איחור של {LATE_MIN} "
                       f"דקות ומעלה או נסיעה שלא בוצעה; צהוב: יציאה של יותר מ-{EARLY_MIN} דקות לפני הזמן."),
        "delay_aria": (f"גרף עמודות: התפלגות האיחור ביציאה של {fmt.int_he(n)} נסיעות. "
                       f"{fmt.pct(ontime_share)} יצאו בזמן ו-{fmt.pct(miss_share)} לא בוצעו."),
        "delay_caption": "התפלגות האיחור ביציאת הנסיעות",
        "hour_note": (f"לפי שעת היציאה המתוכננת: כמה נסיעות תוכננו בכל שעה, ואיזה חלק מהן יצא באיחור או לא בוצע. "
                      f"שעות עם פחות מ-{fmt.int_he(MIN_HOUR_TRIPS)} נסיעות מוצגות ללא שיעורים." + ex_note),
        "hour_aria": "גרף משולב: נסיעות מתוכננות ושיעור האיחורים והביטולים לפי שעת יציאה"
                     + (f". השעה הבעייתית ביותר: {_hour_label(worst[0])}." if len(busy) >= 4 else "."),
        "hour_caption": "נסיעות, איחורים וביטולים לפי שעת היציאה",
        "heat_note": (f"שיעור הנסיעות שלא יצאו בזמן (איחור, הקדמה או ביטול) בכל יום בשבוע ובכל שעה. "
                      f"משבצת עם פחות מ-{fmt.int_he(MIN_HOUR_TRIPS)} נסיעות נשארת ריקה." + ex_note),
        "heat_aria": "מפת חום: שיעור הנסיעות שלא יצאו בזמן לפי יום בשבוע ושעה",
        "week_note": "ממוצע הנסיעות המתוכננות ביום, ושיעור הנסיעות שלא יצאו בזמן, לפי יום בשבוע." + ex_note,
        "week_aria": "גרף משולב: נסיעות ביום ושיעור הנסיעות שלא יצאו בזמן לפי יום בשבוע",
        "week_caption": "נסיעות ועמידה בזמנים לפי יום בשבוע",
        "daily_note": ("כל יום בתקופה: הנסיעות המתוכננות, ושיעור הנסיעות שלא בוצעו או יצאו באיחור. "
                       "ימים שבהם חלק ניכר מהנסיעות סומן כאירוע חריג מסומנים בחלון המידע."),
        "daily_aria": f"גרף יומי: נסיעות מתוכננות ושיעור הביטולים והאיחורים, {period}",
        "month_caption": "עמידה בזמנים לפי חודש",
        "op_note": ("חלוקת הנסיעות של כל מפעיל לפי אופן הביצוע, מהמפעיל עם השיעור הגבוה ביותר של יציאה בזמן. "
                    + (f"{fmt.int_he(len(rest))} המפעילים הקטנים מקובצים תחת \"{OTHER}\". " if rest else "")
                    + (f"הציר מתחיל ב-{op_chart['axis_min']}% כדי שהאיחורים והביטולים ייראו. " if op_chart["axis_min"] else "")
                    + "העשירון העליון של האיחור: אחת מכל עשר נסיעות של המפעיל יצאה באיחור כזה או גדול ממנו." + ex_note),
        "op_aria": "גרף עמודות מוערמות: אחוז הנסיעות בזמן, באיחור, בהקדמה ושלא בוצעו לפי מפעיל",
        "op_caption": "עמידה בזמנים לפי מפעיל",
        "dur_note": (f"משך הנסיעה מהיציאה בפועל ועד סיומה, לפי שעת היציאה: הקו המרכזי הוא החציון, והרצועה "
                     f"היא הטווח שבו נמצאות מחצית הנסיעות. "
                     f"{fmt.int_he(n_dur_bad)} נסיעות שבוצעו בלי זמן סיום תקין (חסר, שלילי או מעל "
                     f"{fmt.int_he(DUR_MAX_MIN)} דקות) לא נכללו." + ex_note),
        "dur_aria": (f"גרף קווים: משך נסיעה חציוני לפי שעת היציאה. משך חציוני כולל: "
                     f"{fmt.num_he(med_dur or 0, 0)} דקות."),
        "dur_caption": "משך נסיעה לפי שעת היציאה",
        "durdist_aria": "גרף עמודות: התפלגות משך הנסיעות",
        "durdist_caption": "התפלגות משך הנסיעות",
        "event_note": (f"נסיעות שסומנו במאגר כחלק מאירוע חריג: {fmt.int_he(n_event)} נסיעות "
                       f"({fmt.pct(n_event / n)}). {fmt.int_he(n_event_days)} ימים שבהם "
                       f"{fmt.pct(EVENT_DAY_SHARE, 0)} מהנסיעות ומעלה סומנו כך. הטבלה מציגה את הימים עם הכי הרבה "
                       f"נסיעות כאלה."),
        "event_caption": "הימים עם הכי הרבה נסיעות שסומנו כאירוע חריג",
    }

    desc = (f"האם האוטובוס יצא בזמן? {fmt.int_he(n)} נסיעות ב{period}: {fmt.pct(ontime_share)} בזמן, "
            f"{fmt.pct(miss_share)} לא בוצעו. איחורים לפי שעה, יום ומפעיל.")
    if len(desc) > 150:
        desc = (f"האם האוטובוס יצא בזמן? {fmt.pct(ontime_share)} מנסיעות האוטובוס יצאו בזמן ו-"
                f"{fmt.pct(miss_share)} לא בוצעו. איחורים לפי שעה, יום ומפעיל.")
    summary = (f"כל נסיעת אוטובוס מתוכננת מול היציאה בפועל, {period}: {fmt.pct(ontime_share)} מ-"
               f"{fmt.int_he(n)} הנסיעות יצאו בזמן ו-{fmt.pct(miss_share)} לא בוצעו.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first.year}-{first.month:02d}/{last.year}-{last.month:02d}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "האם האוטובוס יצא בזמן? איחורים וביטולים לפי שעה ויום",
                "description": desc,
                "name": "תכנון מול ביצוע נסיעות אוטובוסים: כל נסיעה מול לוח הזמנים",
                "alternate_names": [
                    "תכנון מול ביצוע נסיעות אוטובוסים ברמת נסיעה בודדת",
                    "איחורי אוטובוסים לפי שעה",
                    "נסיעות אוטובוס שלא בוצעו",
                    "דיוק האוטובוסים בתחבורה הציבורית",
                    "משך נסיעה באוטובוס",
                ],
            },
        },
        "kpis": kpis,
        "charts": {
            "delay": delay_chart,
            "hour": hour_chart,
            "heat": heat,
            "week": week_chart,
            "daily": daily,
            "ops": op_chart,
            "dur_hour": dur_hour,
            "dur_dist": dur_chart,
        },
        "tables": {
            "delay": delay_rows,
            "hours": hour_rows,
            "week": week_rows,
            "months": months_rows,
            "ops": op_rows,
            "dur_hours": dur_rows,
            "dur_dist": dur_dist_rows,
            "events": ev_days,
        },
        "flags": {"events": bool(ev_days), "duration": bool(dur_rows), "partial_last": partial_last},
        "insights": insights,
        "labels": labels,
        "meta": {"rows": n_raw},
    }
