"""דו"ח מהירות השחרור (customs release-speed report, Israel Tax Authority).

One table, one row per (year, month, customs house, declaration process):
number of declarations, min / max / mean release time in minutes, and how
many of those declarations went through the mandatory queue ("תור חובה").

Volume is wildly skewed: personal courier imports ("יבוא אישי-בלדרים") are
~95% of all declarations, so every time figure is a declaration-weighted
mean (sum(n * mean) / sum(n)) and personal vs commercial imports are always
shown apart. "Now" is the latest (year, month) in the data; the trend window
is the latest 12 months present vs the 12 before them.
"""
import math

import pandas as pd

MINUS = "−"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]

WINDOW = 12            # months in the "latest year" window
MONTHLY_MAX = 96       # months on the monthly charts before switching to quarters
TOP_HOUSES = 9         # customs houses shown separately (rest -> "אחר")
TOP_PROCESSES = 12     # processes on the per-process chart
MIX_TOP = 6            # processes in the volume-mix chart (rest -> "אחר")
MIN_COMM_HOUSE = 500   # commercial declarations in the window for a house's time bar
MIN_QUEUE_HOUSE = 500  # declarations in the window for a house's queue-share bar
MIN_AUTO_N = 500       # declarations per autonomy group for the autonomy comparison
TREND_VOL = 0.03       # +-3% = "stable" volume
TREND_TIME = 0.05      # +-5% = "stable" release time
DIP_RATIO = 0.70       # a month below 70% of the median month is a dip
COURIER_KEY = "בלדר"   # process names of courier imports contain this

TYPE_PERSONAL = "אישי"
TYPE_COMMERCIAL = "מסחרי"


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")


def _fmt_int(v):
    return f"{int(round(v)):,}"


def _fmt1(v):
    return f"{v:,.1f}"


def _pct(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def _signed_pct(v):
    s = f"{abs(v) * 100:.1f}%"
    return ("+" if v >= 0 else MINUS) + s


def _mlabel(ym):
    y, m = divmod(int(ym), 100)
    return f"{MONTHS_HE[m - 1]} {y}"


def _whours(g):
    """Declaration-weighted mean release time in hours, or None."""
    n = g["n_t"].sum()
    if n <= 0:
        return None
    return float(g["tot"].sum() / n / 60.0)


def _htext(h):
    """Hours as prose: minutes below one hour."""
    if h < 1:
        return f"{h * 60:.0f} דקות"
    return f"{h:,.1f} שעות"


def _r1(v):
    return None if v is None else round(v, 1)


def compute(frames):
    df = frames["main"].copy()
    df["year"] = _num(df["שנה"])
    df["month"] = _num(df["חודש"])
    df["n"] = _num(df["כמות הצהרות"])
    df["avg"] = _num(df["זמן ממוצע בדקות"])
    df["mx"] = _num(df["זמן מקסימלי בדקות"])
    df["q"] = _num(df["מספר הצהרות שהיו בתור חובה"])
    df["house"] = df["בית מכס"].astype(str).str.strip()
    df["proc"] = df["תהליך להצהרה"].astype(str).str.strip()
    df["ptype"] = df["סוג תהליך"].astype(str).str.strip()
    df["auto"] = _num(df["האם אוטונומיה"])
    df = df[df["year"].notna() & df["month"].between(1, 12) & (df["n"] > 0)].copy()
    df["house"] = df["house"].where(df["house"] != "", "לא צוין")
    df["proc"] = df["proc"].where(df["proc"] != "", "לא צוין")
    df["ym"] = (df["year"] * 100 + df["month"]).astype(int)
    df["q"] = df["q"].fillna(0).clip(lower=0)
    df["q"] = df[["q", "n"]].min(axis=1)
    # time is weighted by declarations; a row without a mean time adds no weight
    df["n_t"] = df["n"].where(df["avg"].notna(), 0)
    df["tot"] = (df["n_t"] * df["avg"].fillna(0))

    periods = sorted(df["ym"].unique().tolist())
    last = periods[-1]
    win = periods[-WINDOW:]
    prev = periods[-2 * WINDOW:-WINDOW] if len(periods) >= 2 * WINDOW else []
    w = df[df["ym"].isin(win)]
    p = df[df["ym"].isin(prev)]
    win_label = f"{_mlabel(win[0])} עד {_mlabel(win[-1])}"

    comm = df[df["ptype"] == TYPE_COMMERCIAL]
    pers = df[df["ptype"] == TYPE_PERSONAL]
    wc, wp = w[w["ptype"] == TYPE_COMMERCIAL], w[w["ptype"] == TYPE_PERSONAL]
    pc, pp = p[p["ptype"] == TYPE_COMMERCIAL], p[p["ptype"] == TYPE_PERSONAL]

    # ---------------- monthly / quarterly series ----------------
    quarterly = len(periods) > MONTHLY_MAX
    if quarterly:
        df["bucket"] = (df["year"] * 10 + (df["month"] - 1) // 3 + 1).astype(int)
    else:
        df["bucket"] = df["ym"]
    buckets = sorted(df["bucket"].unique().tolist())

    def blabel(b):
        if quarterly:
            y, qn = divmod(int(b), 10)
            return f"רבעון {qn} {y}"
        y, m = divmod(int(b), 100)
        return f"{MONTHS_SHORT[m - 1]} {y}"

    xs = [blabel(b) for b in buckets]
    vol_p, vol_c, hrs_p, hrs_c = [], [], [], []
    for b in buckets:
        g = df[df["bucket"] == b]
        gp, gc = g[g["ptype"] == TYPE_PERSONAL], g[g["ptype"] == TYPE_COMMERCIAL]
        vol_p.append(int(gp["n"].sum()))
        vol_c.append(int(gc["n"].sum()))
        hrs_p.append(_r1(_whours(gp)))
        hrs_c.append(_r1(_whours(gc)))
    zoom_start = xs[max(0, len(xs) - 36)]

    # ---------------- yearly table ----------------
    years = sorted(df["year"].astype(int).unique().tolist())
    yearly_rows = []
    y_hc, y_hp, y_labels = [], [], []
    for y in years:
        g = df[df["year"] == y]
        nm = int(g["month"].nunique())
        gc, gp = g[g["ptype"] == TYPE_COMMERCIAL], g[g["ptype"] == TYPE_PERSONAL]
        hc, hp = _whours(gc), _whours(gp)
        lab = str(y) if nm >= 12 else f"{y} (חודשים: {nm})"
        y_labels.append(lab)
        y_hc.append(_r1(hc))
        y_hp.append(_r1(hp))
        yearly_rows.append({
            "year": lab,
            "total": _fmt_int(g["n"].sum()),
            "comm": _fmt_int(gc["n"].sum()),
            "hc": "" if hc is None else _fmt1(hc),
            "hp": "" if hp is None else _fmt1(hp),
            "qc": _pct(gc["q"].sum() / gc["n"].sum()) if gc["n"].sum() > 0 else "",
        })

    # ---------------- heatmap: commercial hours, month x year ----------------
    heat_cells, heat_max = [], 0.0
    for yi, y in enumerate(years):
        for m in range(1, 13):
            g = comm[(comm["year"] == y) & (comm["month"] == m)]
            h = _whours(g)
            if h is None:
                continue
            heat_cells.append([m - 1, yi, round(h, 1), int(g["n"].sum())])
            heat_max = max(heat_max, h)
    heat = {"x": MONTHS_SHORT, "y": [str(y) for y in years], "cells": heat_cells,
            "max": math.ceil(heat_max / 10.0) * 10 if heat_max > 0 else 10}

    # ---------------- customs houses (window) ----------------
    hs = []
    for house, g in w.groupby("house", sort=True):
        gc = g[g["ptype"] == TYPE_COMMERCIAL]
        hs.append({
            "house": house, "n": int(g["n"].sum()), "nc": int(gc["n"].sum()),
            "q": int(g["q"].sum()), "hc": _whours(gc), "h": _whours(g),
        })
    hs.sort(key=lambda r: (-r["n"], r["house"]))
    top_h = hs[:TOP_HOUSES]
    rest_h = hs[TOP_HOUSES:]
    vol_names = [r["house"] for r in top_h]
    vol_vals = [r["n"] for r in top_h]
    if rest_h:
        vol_names.append("אחר")
        vol_vals.append(int(sum(r["n"] for r in rest_h)))
    w_total = int(w["n"].sum())
    houses_table = [{"house": r["house"], "n": _fmt_int(r["n"]),
                     "share": _pct(r["n"] / w_total) if w_total else "",
                     "nc": _fmt_int(r["nc"]),
                     "hc": "" if (r["hc"] is None or r["nc"] < MIN_COMM_HOUSE) else _fmt1(r["hc"]),
                     "qs": _pct(r["q"] / r["n"]) if r["n"] >= MIN_QUEUE_HOUSE else ""}
                    for r in top_h]
    if rest_h:
        rn = sum(r["n"] for r in rest_h)
        houses_table.append({"house": "אחר (" + ", ".join(r["house"] for r in rest_h) + ")",
                             "n": _fmt_int(rn), "share": _pct(rn / w_total) if w_total else "",
                             "nc": _fmt_int(sum(r["nc"] for r in rest_h)), "hc": "", "qs": ""})

    ht = sorted([r for r in hs if r["nc"] >= MIN_COMM_HOUSE and r["hc"] is not None],
                key=lambda r: (-r["hc"], r["house"]))
    house_time = {"names": [r["house"] for r in ht], "values": [round(r["hc"], 1) for r in ht],
                  "n": [r["nc"] for r in ht]}
    qt = sorted([r for r in hs if r["n"] >= MIN_QUEUE_HOUSE],
                key=lambda r: (-(r["q"] / r["n"]), r["house"]))
    house_queue = {"names": [r["house"] for r in qt],
                   "values": [round(r["q"] / r["n"] * 100, 1) for r in qt],
                   "n": [r["n"] for r in qt]}

    # ---------------- processes (window) ----------------
    ps = []
    for (proc, ptype), g in w.groupby(["proc", "ptype"], sort=True):
        mins = _num(g["זמן מינימלי בדקות"]).dropna()
        maxs = g["mx"].dropna()
        ps.append({"proc": proc, "ptype": ptype, "n": int(g["n"].sum()), "h": _whours(g),
                   "q": int(g["q"].sum()),
                   "mn": float(mins.median()) if len(mins) else None,
                   "mx": float(maxs.median()) / 60 / 24 if len(maxs) else None})
    ps.sort(key=lambda r: (-r["n"], r["proc"], r["ptype"]))
    top_p = [r for r in ps if r["h"] is not None][:TOP_PROCESSES]
    top_p_sorted = sorted(top_p, key=lambda r: (-r["h"], r["proc"]))
    proc_time = {"names": [r["proc"] for r in top_p_sorted],
                 "values": [max(round(r["h"], 2), 0.01) for r in top_p_sorted],
                 "types": [r["ptype"] for r in top_p_sorted],
                 "n": [r["n"] for r in top_p_sorted]}
    proc_table = [{"proc": r["proc"], "ptype": r["ptype"], "n": _fmt_int(r["n"]),
                   "h": _fmt1(r["h"]), "d": _fmt1(r["h"] / 24),
                   "qs": _pct(r["q"] / r["n"]) if r["n"] else "",
                   "mn": "" if r["mn"] is None else _fmt_int(r["mn"]),
                   "mx": "" if r["mx"] is None else _fmt1(r["mx"])} for r in top_p_sorted]

    mix_names, mix_vals = [], []
    for r in ps[:MIX_TOP]:
        mix_names.append(r["proc"])
        mix_vals.append(r["n"])
    if len(ps) > MIX_TOP:
        mix_names.append("שאר התהליכים")
        mix_vals.append(int(sum(r["n"] for r in ps[MIX_TOP:])))
    mix_table = [{"name": nm, "n": _fmt_int(v), "share": _pct(v / w_total) if w_total else ""}
                 for nm, v in zip(mix_names, mix_vals)]

    # ---------------- autonomy (commercial, by year) ----------------
    auto_rows, auto_reg, auto_aut = [], [], []
    for y in years:
        g = comm[comm["year"] == y]
        reg, aut = g[g["auto"] == 0], g[g["auto"] == 1]
        hr, ha = _whours(reg), _whours(aut)
        auto_reg.append(_r1(hr))
        auto_aut.append(_r1(ha))
        auto_rows.append({
            "year": y_labels[years.index(y)],
            "nr": _fmt_int(reg["n"].sum()), "hr": "" if hr is None else _fmt1(hr),
            "qr": _pct(reg["q"].sum() / reg["n"].sum()) if reg["n"].sum() > 0 else "",
            "na": _fmt_int(aut["n"].sum()), "ha": "" if ha is None else _fmt1(ha),
            "qa": _pct(aut["q"].sum() / aut["n"].sum()) if aut["n"].sum() > 0 else "",
        })
    show_auto = any(v is not None for v in auto_aut) and any(v is not None for v in auto_reg)

    # ---------------- KPIs ----------------
    hc_w, hp_w = _whours(wc), _whours(wp)
    hc_p, hp_p = (_whours(pc), _whours(pp)) if prev else (None, None)

    def time_tone(cur, old):
        if cur is None or old is None or old <= 0:
            return "brand"
        ch = cur / old - 1
        if ch <= -TREND_TIME:
            return "ok"
        if ch >= 0.20:
            return "danger"
        if ch >= TREND_TIME:
            return "warn"
        return "brand"

    wc_n = int(wc["n"].sum())
    qshare_c = float(wc["q"].sum() / wc_n) if wc_n else 0.0
    kpis = {
        "total": {"value": w_total, "display": _fmt1(w_total / 1e6), "tone": "brand"},
        "comm_n": {"value": wc_n, "display": _fmt_int(wc_n / 1000), "tone": "brand"},
        "hc": {"value": _r1(hc_w), "display": "" if hc_w is None else _fmt1(hc_w),
               "tone": time_tone(hc_w, hc_p)},
        "hp": {"value": _r1(hp_w), "display": "" if hp_w is None else _fmt1(hp_w),
               "tone": time_tone(hp_w, hp_p)},
        "queue": {"value": round(qshare_c, 4), "display": _pct(qshare_c), "tone": "info"},
        "span": {"value": len(periods),
                 "display": f"{years[0]}–{years[-1]}" if years[0] != years[-1] else str(years[0]),
                 "tone": "brand"},
    }

    # ---------------- insights ----------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_volume():
        if not prev:
            return None
        a, b = w_total, int(p["n"].sum())
        if b <= 0:
            return None
        ch = a / b - 1
        if abs(ch) < TREND_VOL:
            return (f"היקף ההצהרות יציב: {_fmt1(a / 1e6)} מיליון הצהרות ב-12 החודשים האחרונים "
                    f"({win_label}), לעומת {_fmt1(b / 1e6)} מיליון ב-12 החודשים שקדמו להם.")
        word = "עלייה" if ch > 0 else "ירידה"
        return (f"{word} של {_pct(abs(ch))} בהיקף ההצהרות: {_fmt1(a / 1e6)} מיליון ב-12 החודשים "
                f"האחרונים ({win_label}), לעומת {_fmt1(b / 1e6)} מיליון ב-12 החודשים שקדמו להם.")

    def ins_courier():
        cur = w[w["proc"].str.contains(COURIER_KEY, regex=False)]
        if w_total <= 0 or cur.empty:
            return None
        sh = cur["n"].sum() / w_total
        if sh < 0.5:
            return None
        hc = _whours(cur)
        tail = f", וזמן השחרור הממוצע שלהן {_fmt1(hc)} שעות" if hc is not None else ""
        return (f"משלוחי בלדרים (יבוא אישי ומסחרי) הם {_pct(sh)} מכל ההצהרות ב-12 החודשים "
                f"האחרונים: {_fmt1(cur['n'].sum() / 1e6)} מיליון הצהרות{tail}.")

    def ins_time(label, cur, old):
        if cur is None or old is None or old <= 0:
            return None
        ch = cur / old - 1
        if abs(ch) < TREND_TIME:
            return (f"זמן השחרור הממוצע ב{label} יציב: {_fmt1(cur)} שעות ב-12 החודשים האחרונים, "
                    f"לעומת {_fmt1(old)} שעות ב-12 החודשים שקדמו להם.")
        word = "התארך" if ch > 0 else "התקצר"
        return (f"זמן השחרור הממוצע ב{label} {word} ב-{_pct(abs(ch))}: {_fmt1(cur)} שעות "
                f"({_fmt1(cur / 24)} ימים) ב-12 החודשים האחרונים, לעומת {_fmt1(old)} שעות "
                f"ב-12 החודשים שקדמו להם.")

    def ins_house_gap():
        if len(ht) < 3:
            return None
        slow, fast = ht[0], ht[-1]
        if fast["hc"] <= 0 or slow["hc"] / fast["hc"] < 1.5:
            return None
        return (f"ביבוא מסחרי, בית המכס {slow['house']} איטי במיוחד: {_htext(slow['hc'])} "
                f"({_fmt1(slow['hc'] / 24)} ימים) בממוצע להצהרה ב-12 החודשים האחרונים, לעומת "
                f"{_htext(fast['hc'])} ב{fast['house']}, המהיר ביותר (בתי מכס עם "
                f"{_fmt_int(MIN_COMM_HOUSE)} הצהרות מסחריות לפחות).")

    def ins_queue():
        full = [r for r in qt if r["q"] / r["n"] >= 0.9]
        low = sorted([r for r in qt if r["q"] / r["n"] < 0.05], key=lambda r: (-r["n"], r["house"]))
        if not full or not low:
            return None
        names = ", ".join(r["house"] for r in full)
        big = low[0]
        return (f"בבתי המכס {names} עברו {_pct(sum(r['q'] for r in full) / sum(r['n'] for r in full))} "
                f"מההצהרות בתור חובה ב-12 החודשים האחרונים, ואילו ב{big['house']} "
                f"({_fmt_int(big['n'])} הצהרות) רק {_pct(big['q'] / big['n'], 2)}.")

    def ins_dip():
        tot = df.groupby("ym")["n"].sum().sort_index()
        if len(tot) < 12:
            return None
        med = float(tot.median())
        dips = tot[tot < med * DIP_RATIO]
        if dips.empty:
            return None
        ym = int(dips.index[-1])
        v = float(dips.iloc[-1])
        extra = ""
        if len(dips) > 1:
            others = [_mlabel(int(x)) for x in dips.index[:-1]][-5:]
            extra = f" חודשים חלשים נוספים בסדרה: {', '.join(others)}."
        return (f"ב{_mlabel(ym)} נרשמו רק {_fmt1(v / 1e6)} מיליון הצהרות, {_pct(1 - v / med)} "
                f"פחות מהחודש החציוני בסדרה ({_fmt1(med / 1e6)} מיליון).{extra}")

    def ins_autonomy():
        reg, aut = wc[wc["auto"] == 0], wc[wc["auto"] == 1]
        if reg["n"].sum() < MIN_AUTO_N or aut["n"].sum() < MIN_AUTO_N:
            return None
        qr, qa = reg["q"].sum() / reg["n"].sum(), aut["q"].sum() / aut["n"].sum()
        hr, ha = _whours(reg), _whours(aut)
        if hr is None or ha is None:
            return None
        cmp = "ארוך" if ha > hr else "קצר"
        return (f"ביבוא מסחרי במסלולי אוטונומיה עברו {_pct(qa)} מההצהרות בתור חובה ב-12 החודשים "
                f"האחרונים, לעומת {_pct(qr)} במסלולים הרגילים, וזמן השחרור הממוצע בהם {cmp} יותר: "
                f"{_fmt1(ha)} שעות לעומת {_fmt1(hr)}.")

    add("volume", ins_volume())
    add("courier", ins_courier())
    add("comm_time", ins_time("יבוא מסחרי", hc_w, hc_p))
    add("pers_time", ins_time("יבוא אישי", hp_w, hp_p))
    add("house_gap", ins_house_gap())
    add("queue", ins_queue())
    add("dip", ins_dip())
    add("autonomy", ins_autonomy())

    # ---------------- labels ----------------
    last_label = _mlabel(last)
    summary = (f"זמני שחרור טובין מהמכס לפי בית מכס ותהליך: {_fmt1(w_total / 1e6)} מיליון הצהרות "
               f"ב-12 החודשים האחרונים")
    if hc_w is not None:
        summary += f"; יבוא מסחרי משתחרר בממוצע תוך {_fmt1(hc_w)} שעות."
    else:
        summary += "."

    lede = (f"דו\"ח מהירות השחרור של רשות המסים (מינהל המכס) מפרט, לכל חודש, בית מכס ותהליך "
            f"הצהרה, כמה הצהרות יבוא הוגשו, כמה זמן לקח לשחרר את הטובין (מינימום, ממוצע ומקסימום) "
            f"וכמה מהן עברו בתור חובה. הנתונים מכסים {len(periods)} חודשים, מ{_mlabel(periods[0])} "
            f"ועד {last_label}. כל זמני השחרור בעמוד הם ממוצע משוקלל לפי מספר ההצהרות, בשעות.")

    gran = "רבעון" if quarterly else "חודש"
    labels = {
        "lede": lede,
        "total_kpi": f"הצהרות ב-12 החודשים האחרונים (מיליונים)",
        "comm_n_kpi": "הצהרות יבוא מסחרי ב-12 החודשים האחרונים (אלפים)",
        "hc_kpi": "זמן שחרור ממוצע ביבוא מסחרי (שעות)",
        "hp_kpi": "זמן שחרור ממוצע ביבוא אישי (שעות)",
        "queue_kpi": "שיעור ההצהרות המסחריות שעברו בתור חובה",
        "span_kpi": f"תקופת הנתונים (עד {last_label})",
        "window": win_label,
        "vol_note": (f"מספר ההצהרות בכל {gran}, יבוא אישי (ציר ימני) ויבוא מסחרי (ציר שמאלי). "
                     f"היבוא האישי גדול פי {_fmt_int(sum(vol_p) / max(sum(vol_c), 1))} בערך, "
                     f"ולכן לכל סוג ציר משלו."),
        "vol_aria": (f"גרף קווים: מספר הצהרות היבוא לפי {gran}, אישי ומסחרי. ב{last_label} "
                     f"{_fmt_int(vol_p[-1])} הצהרות אישיות ו-{_fmt_int(vol_c[-1])} מסחריות."),
        "time_note": (f"זמן השחרור הממוצע המשוקלל בכל {gran}, בשעות. ב{last_label}: "
                      f"{'' if hrs_c[-1] is None else _fmt1(hrs_c[-1])} שעות ביבוא מסחרי, "
                      f"{'' if hrs_p[-1] is None else _fmt1(hrs_p[-1])} ביבוא אישי."),
        "time_aria": (f"גרף קווים: זמן שחרור ממוצע בשעות לפי {gran}, יבוא מסחרי ויבוא אישי, "
                      f"מ{_mlabel(periods[0])} עד {last_label}."),
        "yearly_note": "סיכום שנתי. שנה שאינה מלאה מסומנת במספר החודשים שיש לה בנתונים.",
        "yearly_aria": (f"גרף עמודות: זמן שחרור ממוצע בשעות לפי שנה, יבוא מסחרי ויבוא אישי, "
                        f"{years[0]} עד {years[-1]}."),
        "heat_note": ("זמן השחרור הממוצע ביבוא מסחרי (שעות) בכל חודש ושנה. "
                      "צבע כהה יותר הוא שחרור איטי יותר."),
        "heat_aria": (f"מפת חום: זמן שחרור ממוצע ביבוא מסחרי לפי חודש ושנה, "
                      f"שיא של {_fmt1(heat_max)} שעות."),
        "houses_note": (f"מספר ההצהרות בכל בית מכס ב-12 החודשים האחרונים ({win_label}). "
                        f"הציר לוגריתמי, כי נתב\"ג ומרכז מטפלים במיליוני הצהרות והמעברים היבשתיים באלפים."),
        "houses_aria": (f"גרף עמודות אופקי בציר לוגריתמי: הצהרות לפי בית מכס, 12 החודשים האחרונים. "
                        f"המוביל: {vol_names[0]} עם {_fmt_int(vol_vals[0])} הצהרות."),
        "house_time_note": (f"זמן שחרור ממוצע של הצהרות יבוא מסחרי בכל בית מכס, 12 החודשים האחרונים "
                            f"(בתי מכס עם {_fmt_int(MIN_COMM_HOUSE)} הצהרות מסחריות לפחות)."),
        "house_time_aria": ("גרף עמודות אופקי: זמן שחרור ממוצע ביבוא מסחרי לפי בית מכס. "
                            + (f"האיטי ביותר {ht[0]['house']} עם {_fmt1(ht[0]['hc'])} שעות." if ht else "")),
        "queue_note": (f"איזה חלק מההצהרות בכל בית מכס עבר בתור חובה, 12 החודשים האחרונים "
                       f"(בתי מכס עם {_fmt_int(MIN_QUEUE_HOUSE)} הצהרות לפחות)."),
        "queue_aria": ("גרף עמודות אופקי: שיעור ההצהרות בתור חובה לפי בית מכס. "
                       + (f"הגבוה ביותר {qt[0]['house']} עם {_fmt1(qt[0]['q'] / qt[0]['n'] * 100)}%." if qt else "")),
        "proc_note": (f"זמן השחרור הממוצע ב-{len(top_p_sorted)} תהליכי ההצהרה הנפוצים, 12 החודשים "
                      f"האחרונים. הציר לוגריתמי: הטווח הוא משעה ועד חודשים."),
        "proc_aria": ("גרף עמודות אופקי בציר לוגריתמי: זמן שחרור ממוצע לפי תהליך הצהרה. "
                      + (f"האיטי ביותר {top_p_sorted[0]['proc']} עם {_fmt1(top_p_sorted[0]['h'])} שעות."
                         if top_p_sorted else "")),
        "mix_note": f"חלוקת כל ההצהרות ב-12 החודשים האחרונים לפי תהליך ההצהרה ({len(ps)} תהליכים).",
        "mix_aria": (f"תרשים טבעת: הצהרות לפי תהליך, 12 החודשים האחרונים. המוביל {mix_names[0]} "
                     f"עם {_pct(mix_vals[0] / w_total) if w_total else ''}."),
        "auto_note": ("יבוא מסחרי בלבד: זמן שחרור ממוצע בשעות במסלולי אוטונומיה לעומת המסלולים "
                      "הרגילים, לפי שנה."),
        "auto_aria": "גרף עמודות: זמן שחרור ממוצע ביבוא מסחרי, אוטונומיה לעומת מסלול רגיל, לפי שנה.",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["מכס", "שחרור טובין", "יבוא", "זמני שחרור", "בתי מכס"],
            "related_ids": [
                "3b1e6441-83c5-47de-a1e2-1d35063bab3d",
                "3de0e7f0-03e1-4665-b078-da6e87543ed7",
                "15fd7d7f-da3a-461e-94dd-1dfbbec52a22",
                "3e4e79f7-643b-4be6-94c2-e47667d42916",
            ],
            "temporal_coverage": f"{years[0]}/{years[-1]}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "volume": {"x": xs, "personal": vol_p, "commercial": vol_c, "zoom_start": zoom_start},
            "time": {"x": xs, "personal": hrs_p, "commercial": hrs_c, "zoom_start": zoom_start},
            "yearly": {"x": y_labels, "commercial": y_hc, "personal": y_hp},
            "heat": heat,
            "houses": {"names": vol_names, "values": vol_vals},
            "house_time": house_time,
            "house_queue": house_queue,
            "proc_time": proc_time,
            "mix": {"names": mix_names, "values": mix_vals},
            "autonomy": {"x": y_labels, "regular": auto_reg, "autonomy": auto_aut},
        },
        "tables": {
            "yearly": yearly_rows,
            "houses": houses_table,
            "house_time": [{"house": n, "h": _fmt1(v), "d": _fmt1(v / 24), "n": _fmt_int(c)}
                           for n, v, c in zip(house_time["names"], house_time["values"], house_time["n"])],
            "house_queue": [{"house": n, "s": f"{v:.1f}%", "n": _fmt_int(c)}
                            for n, v, c in zip(house_queue["names"], house_queue["values"], house_queue["n"])],
            "processes": proc_table,
            "mix": mix_table,
            "autonomy": auto_rows,
        },
        "flags": {"autonomy": show_auto, "house_time": len(ht) > 0, "house_queue": len(qt) > 0},
        "insights": insights,
        "labels": labels,
    }
