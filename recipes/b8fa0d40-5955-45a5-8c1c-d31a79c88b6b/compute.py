"""וועדת העזבונות — requests to the estates committee (Ministry of Justice).

One table, one row per funding request: the requesting institution, the
support year (שנת תמיכה) the request competes in, the amount asked per year,
the project's cost and reach, the committee's decision and the amount approved
for payment. The committee allocates estates left to the state without a
designated purpose; the sibling page (estates to the state, f2949f90) covers
the money coming in and the allocations reported to the Administrator General
— this page is the applicant side: who asks, who is approved, and for how much.

Requesters are institutions (non-profits, local authorities, public-benefit
companies, government ministries). A requester whose identifier is not a
corporate or ministry code is treated as a private individual and never named.
Amounts are summed with math.fsum (exact, row-order independent).
"""
import math

import pandas as pd

APPROVED, REJECTED, PENDING = "החלטה מאושרת", "החלטה דחויה", "החלטה בתהליך"
TOP_RECIPIENTS = 12
TOP_APPLICANTS = 12
GRANT_BUCKETS = [(0, 10_000), (10_000, 25_000), (25_000, 50_000), (50_000, 100_000),
                 (100_000, 250_000), (250_000, 1_000_000), (1_000_000, None)]
ASK_BUCKETS = [(0, 50_000), (50_000, 100_000), (100_000, 200_000), (200_000, 500_000),
               (500_000, 1_000_000), (1_000_000, None)]
PART_BUCKETS = [(0, 50), (50, 200), (200, 1_000), (1_000, 10_000), (10_000, None)]
TYPE_ORDER = ["עמותות", "רשויות מקומיות וגופים ציבוריים", "חברות", "משרדי ממשלה", "אחר"]
PRIVATE = "מבקש פרטי"


# ── formatting ─────────────────────────────────────────────────────────────
def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{v:.{digits}f}%"


def fsum(s):
    return math.fsum(float(x) for x in s)


def money_he(v):
    if v >= 1e9:
        return f"{v / 1e9:,.2f} מיליארד ₪"
    if v >= 1e6:
        return f"{v / 1e6:,.1f} מיליון ₪"
    return f"{v:,.0f} ₪"


def k_he(v):
    """Compact amount for range labels: 50 אלף / 1 מיליון."""
    if v >= 1e6:
        return f"{v / 1e6:g} מיליון"
    return f"{v / 1e3:g} אלף"


def range_label(lo, hi, unit_fn, suffix=""):
    if hi is None:
        return f"מעל {unit_fn(lo)}{suffix}"
    if lo == 0:
        return f"עד {unit_fn(hi)}{suffix}"
    return f"{unit_fn(lo)} עד {unit_fn(hi)}{suffix}"


def clean(s):
    """Upstream writes the Hebrew quote (״) as '~'."""
    return s.str.replace("~", "״", regex=False).str.replace("''", "״", regex=False).str.strip()


def num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce")


def dates(s):
    return pd.to_datetime(s.str.strip(), errors="coerce", format="%d/%m/%Y")


def _rank(series):
    """Sort a value-indexed Series by value desc, label asc (total, stable)."""
    return series.sort_index(kind="stable").sort_values(ascending=False, kind="stable")


def ministry_name(name):
    if name.startswith(("משרד", "בית", "לשכת")):
        return name
    if name.startswith(("ה", "ראש")):
        return "משרד " + name
    return "משרד ה" + name


def inst_type(code):
    if code.isdigit() and len(code) <= 3:
        return "משרדי ממשלה"
    if code.isdigit() and len(code) == 9:
        if code.startswith("58"):
            return "עמותות"
        if code.startswith("50"):
            return "רשויות מקומיות וגופים ציבוריים"
        if code.startswith(("51", "52")):
            return "חברות"
        if code.startswith("5"):
            return "אחר"
    return PRIVATE


# ── preparation ────────────────────────────────────────────────────────────
def _requests(df):
    st = df["סטטוס החלטה"].str.strip()
    status = pd.Series("לא תקין", index=df.index)
    status[st == APPROVED] = APPROVED
    status[st == REJECTED] = REJECTED
    status[st == PENDING] = PENDING
    code = df["מזהה מוסד מבקש"].str.strip()
    out = pd.DataFrame({
        "no": df["מספר בקשה"].str.strip(),
        "year": pd.to_numeric(df["שנת תמיכה"].str.strip(), errors="coerce"),
        "submitted": dates(df["תאריך הגשה"]),
        "decided": dates(df["תאריך החלטה"]),
        "status": status,
        "multi": df["האם רב שנתית?"].str.strip() == "כן",
        "proj_years": num(df["מספר שנות פרוייקט"]),
        "fee": num(df["סכום מבוקש ממשתתפים"]).fillna(0),
        "parts": num(df["מספר משתתפים"]),
        "req": num(df["סכום מבוקש לשנה"]).fillna(0).clip(lower=0),
        "cost": num(df["עלות הפרוייקט"]),
        "appr": num(df["סכום לתשלום לאחר אישור אפ~כ"]).fillna(0).clip(lower=0),
        "code": code,
        "name": clean(df["שם מוסד"]),
        "per_year": num(df["מספר בקשות למוסד לשנה"]),
    })
    out = out[out["year"].notna()].copy()
    out["year"] = out["year"].astype(int)
    out.loc[out["status"] != APPROVED, "appr"] = 0.0
    out["type"] = out["code"].map(inst_type)
    out["ok"] = out["status"] == APPROVED
    out["done"] = out["status"].isin([APPROVED, REJECTED])
    return out


def _display_names(r):
    """One display name per institution code: the name on its latest request
    (ties: alphabetical). Ministries get a 'משרד ה…' prefix; private
    requesters are never named."""
    x = r[["code", "year", "name", "type"]].sort_values(
        ["code", "year", "name"], ascending=[True, False, True], kind="stable")
    first = x.drop_duplicates("code")
    names = {}
    for code, name, typ in zip(first["code"], first["name"], first["type"]):
        if typ == PRIVATE or not name:
            names[code] = PRIVATE
        elif typ == "משרדי ממשלה":
            names[code] = ministry_name(name)
        else:
            names[code] = name
    return names


def _buckets(values, buckets):
    out = []
    for lo, hi in buckets:
        m = values > lo if lo > 0 else values >= 0
        if hi is not None:
            m &= values <= hi
        out.append(m)
    return out


# ── insight rules ──────────────────────────────────────────────────────────
def insight_trend(by_year, full_years, overall):
    if len(full_years) < 4:
        return None
    y = full_years[-1]
    r = by_year.loc[y, "rate"]
    prev = by_year.loc[full_years[:-1], :]
    base = prev["ok"].sum() / prev["done"].sum() * 100
    diff = r - base
    if abs(diff) < 5:
        return (f"שיעור האישור יציב: בשנת התמיכה {y} אושרו {pct(r)} מהבקשות שהוכרעו, "
                f"בדומה לממוצע השנים {full_years[0]} עד {full_years[-2]} ({pct(base)}).")
    word = "ירד" if diff < 0 else "עלה"
    only = " בלבד" if diff < 0 else ""
    low = _rank(by_year.loc[full_years, "rate"]).index[-1]
    s = (f"שיעור האישור {word}: בשנת התמיכה {y} אושרו {pct(r)}{only} מהבקשות שהוכרעו "
         f"({n(by_year.loc[y, 'ok'])} מתוך {n(by_year.loc[y, 'done'])}), לעומת {pct(base)} "
         f"בממוצע השנים {full_years[0]} עד {full_years[-2]}.")
    if diff < 0 and low == y:
        s += " זהו השיעור הנמוך ביותר בכל השנים במאגר."
    return s


def insight_cut(ok):
    x = ok[(ok["req"] > 0)]
    if len(x) < 50:
        return None
    ratio = (x["appr"] / x["req"]).clip(upper=1)
    med = float(ratio.median())
    full = float((x["appr"] >= x["req"]).mean())
    if med > 0.8:
        return None
    return (f"גם בקשה שאושרה מקבלת בדרך כלל רק חלק מהסכום: בחציון אושרו {pct(med * 100, 0)} "
            f"מהסכום השנתי שהתבקש, ורק {pct(full * 100)} מהבקשות המאושרות קיבלו את מלוא הסכום.")


def insight_ministries(r, appr_total):
    g = r[r["type"] == "משרדי ממשלה"]
    if appr_total <= 0 or len(g) < 5:
        return None
    share = fsum(g["appr"]) / appr_total
    cnt = len(g) / len(r)
    if share < 0.1 or share < 3 * cnt:
        return None
    rate = g.loc[g["done"], "ok"].mean() * 100
    return (f"משרדי ממשלה הגישו {pct(cnt * 100)} בלבד מהבקשות ({n(len(g))}), אך קיבלו "
            f"{pct(share * 100)} מהכסף שאושר ({money_he(fsum(g['appr']))}); "
            f"שיעור האישור שלהם {pct(rate)}.")


def insight_leader(rec, appr_total):
    if rec.empty or appr_total <= 0:
        return None
    name, v = rec.index[0], rec.iloc[0]
    if name == PRIVATE:
        return None
    share = v / appr_total
    if share < 0.05:
        return None
    top5 = rec.head(5).sum() / appr_total
    return (f"המקבל הגדול ביותר: {name}, עם {money_he(v)} שאושרו ({pct(share * 100)} מכלל "
            f"הסכומים); חמשת המקבלים הגדולים יחד קיבלו {pct(top5 * 100)}.")


def insight_size(ask_rows):
    rows = [x for x in ask_rows if x["done"] >= 100]
    if len(rows) < 4:
        return None
    rates = [x["rate"] for x in rows]
    spread = max(rates) - min(rates)
    if spread < 6:
        return (f"סיכויי האישור כמעט אינם תלויים בגודל הבקשה: בכל טווחי הסכום המבוקש שיעור "
                f"האישור נע בין {pct(min(rates))} ל-{pct(max(rates))}.")
    hi = max(rows, key=lambda x: (x["rate"], x["label"]))
    lo = min(rows, key=lambda x: (x["rate"], x["label"]))
    return (f"גודל הבקשה משפיע על הסיכוי: בטווח {hi['label']} אושרו {pct(hi['rate'])} מהבקשות, "
            f"ובטווח {lo['label']} רק {pct(lo['rate'])}.")


def insight_returning(ret_rows):
    rows = [x for x in ret_rows if x["first_done"] >= 30 and x["ret_done"] >= 30]
    if len(rows) < 3:
        return None
    f_ok = sum(x["first_ok"] for x in rows)
    f_d = sum(x["first_done"] for x in rows)
    r_ok = sum(x["ret_ok"] for x in rows)
    r_d = sum(x["ret_done"] for x in rows)
    fr, rr = f_ok / f_d * 100, r_ok / r_d * 100
    if abs(rr - fr) < 3:
        return None
    last = rows[-1]
    share = last["ret"] / (last["ret"] + last["first"]) * 100
    better = "מוסדות חוזרים מצליחים יותר" if rr > fr else "מוסדות חדשים מצליחים יותר"
    return (f"{better}: מאז {rows[0]['year']} אושרו {pct(rr)} מבקשות של מוסדות שכבר הגישו "
            f"בשנים קודמות, לעומת {pct(fr)} ממבקשים חדשים. בשנת {last['year']} "
            f"{pct(share)} מהבקשות הגיעו ממוסדות חוזרים.")


def insight_half(r):
    x = r[(r["cost"] > 0) & (r["req"] > 0)]
    if len(x) < 100:
        return None
    ratio = x["req"] / x["cost"]
    half = float(((ratio - 0.5).abs() < 0.005).mean())
    over = float((ratio > 0.505).mean())
    if half < 0.3:
        return None
    return (f"ב-{pct(half * 100)} מהבקשות הסכום המבוקש הוא בדיוק מחצית מעלות הפרויקט, "
            f"ורק {pct(over * 100)} מבקשות יותר ממחצית העלות.")


def insight_lag(lag_rows):
    rows = [x for x in lag_rows if x["n"] >= 50]
    if len(rows) < 4:
        return None
    a, b = rows[0], rows[-1]
    if a["p50"] <= 0:
        return None
    chg = b["p50"] / a["p50"] - 1
    if abs(chg) < 0.2:
        return None
    word = "התקצר" if chg < 0 else "התארך"
    return (f"זמן ההמתנה להחלטה {word}: בשנת התמיכה {a['year']} עברו בחציון {n(a['p50'])} ימים "
            f"מהגשת הבקשה ועד ההחלטה, ובשנת {b['year']} — {n(b['p50'])} ימים.")


def insight_fee(feat_rows):
    by = {x["key"]: x for x in feat_rows}
    a, b = by.get("nofee"), by.get("fee")
    if not a or not b or a["done"] < 100 or b["done"] < 100:
        return None
    if a["rate"] - b["rate"] < 5:
        return None
    return (f"פרויקטים שגובים תשלום מהמשתתפים אושרו בשיעור נמוך יותר — {pct(b['rate'])}, "
            f"לעומת {pct(a['rate'])} בפרויקטים ללא תשלום ({n(b['done'])} בקשות עם תשלום שהוכרעו).")


# ── compute ────────────────────────────────────────────────────────────────
def compute(frames):
    r = _requests(frames["main"])
    names = _display_names(r)
    r["disp"] = r["code"].map(names)
    total = len(r)
    done = r[r["done"]]
    ok = r[r["ok"]]
    appr_total = fsum(ok["appr"])
    req_total = fsum(r["req"])
    req_done_total = fsum(done["req"])
    rate_all = done["ok"].mean() * 100 if len(done) else 0.0
    other_status = int((~r["done"]).sum())

    # ── by support year ──
    years = list(range(int(r["year"].min()), int(r["year"].max()) + 1))
    g = r.groupby("year")
    by_year = pd.DataFrame({
        "n": g.size(),
        "ok": g["ok"].sum(),
        "done": g["done"].sum(),
        "req": g["req"].apply(fsum),
        "appr": g["appr"].apply(fsum),
    }).reindex(years, fill_value=0)
    by_year["rej"] = by_year["done"] - by_year["ok"]
    by_year["other"] = by_year["n"] - by_year["done"]
    by_year["rate"] = (by_year["ok"] / by_year["done"].where(by_year["done"] > 0) * 100).fillna(0)
    req_done_y = done.groupby("year")["req"].apply(fsum).reindex(years, fill_value=0)
    by_year["granted"] = (by_year["appr"] / req_done_y.where(req_done_y > 0) * 100).fillna(0)
    # a support year is complete once (almost) every request is decided
    full_years = [y for y in years if by_year.loc[y, "n"] >= 20
                  and by_year.loc[y, "other"] <= 0.05 * by_year.loc[y, "n"]]
    open_years = [y for y in years if y not in full_years and by_year.loc[y, "n"] > 0]
    last_year = years[-1]

    # ── approved grant sizes ──
    grant_rows = []
    for (lo, hi), m in zip(GRANT_BUCKETS, _buckets(ok["appr"], GRANT_BUCKETS)):
        grant_rows.append({"label": range_label(lo, hi, k_he, " ₪"), "count": int(m.sum()),
                           "sum": fsum(ok.loc[m, "appr"])})
    ok_n = max(len(ok), 1)

    # ── requested size vs approval ──
    ask_rows = []
    for (lo, hi), m in zip(ASK_BUCKETS, _buckets(done["req"], ASK_BUCKETS)):
        d = int(m.sum())
        ask_rows.append({"label": range_label(lo, hi, k_he, " ₪"), "done": d,
                         "ok": int(done.loc[m, "ok"].sum()),
                         "rate": float(done.loc[m, "ok"].mean() * 100) if d else 0.0})

    # ── participants vs approval ──
    pv = done[done["parts"].notna() & (done["parts"] > 0)]
    part_rows = []
    for (lo, hi), m in zip(PART_BUCKETS, _buckets(pv["parts"], PART_BUCKETS)):
        d = int(m.sum())
        part_rows.append({"label": range_label(lo, hi, lambda v: f"{v:,}", " משתתפים"),
                          "done": d, "rate": float(pv.loc[m, "ok"].mean() * 100) if d else 0.0,
                          "appr": fsum(pv.loc[m, "appr"])})
    parts_med = float(r.loc[r["parts"] > 0, "parts"].median()) if (r["parts"] > 0).any() else 0.0

    # ── project features vs approval ──
    def feat(key, label, mask):
        d = done[mask]
        return {"key": key, "label": label, "done": len(d),
                "rate": float(d["ok"].mean() * 100) if len(d) else 0.0}

    feat_rows = [
        feat("single", "פרויקט חד־שנתי", ~done["multi"]),
        feat("multi", "פרויקט רב־שנתי", done["multi"]),
        feat("nofee", "ללא תשלום ממשתתפים", done["fee"] <= 0),
        feat("fee", "עם תשלום ממשתתפים", done["fee"] > 0),
    ]
    multi_n = int(r["multi"].sum())
    fee_share = float((r["fee"] > 0).mean() * 100)
    yrs_dist = r.loc[r["multi"], "proj_years"].value_counts()
    multi3 = int(yrs_dist.get(3, 0))

    # ── institution types ──
    tg = r.groupby("type")
    t_n = tg.size()
    t_appr = tg["appr"].apply(fsum)
    t_rate = done.groupby("type")["ok"].mean() * 100
    types = [t for t in TYPE_ORDER + [PRIVATE] if t in t_n.index]
    type_rows = [{"name": t, "n": int(t_n[t]), "appr": float(t_appr[t]),
                  "rate": float(t_rate.get(t, 0.0)),
                  "n_share": t_n[t] / total * 100,
                  "appr_share": (t_appr[t] / appr_total * 100) if appr_total else 0.0}
                 for t in types]

    # ── recipients & applicants ──
    named = r[r["disp"] != PRIVATE]
    rec_code = _rank(named[named["ok"]].groupby("code")["appr"].apply(fsum))
    rec_code = rec_code[rec_code > 0].head(TOP_RECIPIENTS)
    rec_cnt = named[named["ok"]].groupby("code").size()
    rec = pd.Series([float(v) for v in rec_code.values], index=[names[c] for c in rec_code.index])
    app_g = named.groupby("code")
    app_n = app_g.size()
    app_ok = app_g["ok"].sum()
    app_done = app_g["done"].sum()
    app_rank = app_n.rename_axis(None).to_frame("n").assign(code=list(app_n.index)).sort_values(
        ["n", "code"], ascending=[False, True], kind="stable").head(TOP_APPLICANTS)
    app_rows = [{"name": names[c], "n": int(app_n[c]), "ok": int(app_ok[c]),
                 "rej": int(app_done[c] - app_ok[c]), "other": int(app_n[c] - app_done[c]),
                 "years": int(r.loc[r["code"] == c, "year"].nunique())}
                for c in app_rank["code"]]
    n_inst = int(r["code"].nunique())
    inst_years = r.groupby("code")["year"].nunique()
    one_timers = float((inst_years == 1).mean() * 100)
    multi_req = float((r["per_year"].fillna(1) >= 2).mean() * 100)
    n_private = int((r["type"] == PRIVATE).sum())

    # ── first-time vs returning institutions ──
    first_year = r.groupby("code")["year"].transform("min")
    r["returning"] = r["year"] > first_year
    ret_rows = []
    for y in years[1:]:
        ry = r[r["year"] == y]
        dy = ry[ry["done"]]
        fr, rt = dy[~dy["returning"]], dy[dy["returning"]]
        ret_rows.append({
            "year": y, "first": int((~ry["returning"]).sum()), "ret": int(ry["returning"].sum()),
            "first_ok": int(fr["ok"].sum()), "first_done": len(fr),
            "ret_ok": int(rt["ok"].sum()), "ret_done": len(rt),
            "first_rate": float(fr["ok"].mean() * 100) if len(fr) else 0.0,
            "ret_rate": float(rt["ok"].mean() * 100) if len(rt) else 0.0,
        })

    # ── time to decision ──
    lag = (r["decided"] - r["submitted"]).dt.days
    lv = r.assign(lag=lag)[lag.notna() & (lag >= 0) & r["done"]]
    lag_rows = []
    for y in years:
        s = lv.loc[lv["year"] == y, "lag"]
        if len(s) == 0:
            continue
        lag_rows.append({"year": y, "n": len(s), "p25": float(s.quantile(0.25)),
                         "p50": float(s.median()), "p75": float(s.quantile(0.75))})
    last_decision = r["decided"].max()

    # ── insights ──
    ins_rules = [
        ("trend", insight_trend(by_year, full_years, rate_all)),
        ("cut", insight_cut(ok)),
        ("ministries", insight_ministries(r, appr_total)),
        ("leader", insight_leader(rec, appr_total)),
        ("size", insight_size(ask_rows)),
        ("returning", insight_returning(ret_rows)),
        ("half", insight_half(r)),
        ("lag", insight_lag(lag_rows)),
        ("fee", insight_fee(feat_rows)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in ins_rules if t]

    # ── KPIs ──
    ly = full_years[-1] if full_years else last_year
    ly_rate = float(by_year.loc[ly, "rate"])
    diff = ly_rate - rate_all
    ly_tone = "info" if abs(diff) < 5 else ("ok" if diff > 0 else "warn")
    granted = appr_total / req_done_total * 100 if req_done_total else 0.0
    med_grant = float(ok["appr"].median()) if len(ok) else 0.0
    kpis = {
        "requests": {"value": total, "display": n(total), "tone": "brand"},
        "institutions": {"value": n_inst, "display": n(n_inst), "tone": "brand"},
        "rate": {"value": round(rate_all, 1), "display": pct(rate_all), "tone": "brand"},
        "last_rate": {"value": round(ly_rate, 1), "display": pct(ly_rate), "tone": ly_tone},
        "approved": {"value": round(appr_total / 1e6, 1), "display": f"{appr_total / 1e6:,.1f}",
                     "tone": "brand"},
        "requested": {"value": round(req_total / 1e6, 1), "display": f"{req_total / 1e6:,.1f}",
                      "tone": "brand"},
        "granted": {"value": round(granted, 1), "display": pct(granted),
                    "tone": "warn" if granted < 25 else "info"},
        "median_grant": {"value": round(med_grant), "display": n(med_grant), "tone": "brand"},
    }

    # ── charts ──
    charts = {
        "year": {"x": [str(y) for y in years],
                 "ok": [int(by_year.loc[y, "ok"]) for y in years],
                 "rej": [int(by_year.loc[y, "rej"]) for y in years],
                 "other": [int(by_year.loc[y, "other"]) for y in years],
                 "rate": [round(float(by_year.loc[y, "rate"]), 1) for y in years],
                 "has_other": bool(by_year["other"].sum() > 0)},
        "money": {"x": [str(y) for y in years],
                  "req": [round(float(by_year.loc[y, "req"]) / 1e6, 2) for y in years],
                  "appr": [round(float(by_year.loc[y, "appr"]) / 1e6, 2) for y in years],
                  "granted": [round(float(by_year.loc[y, "granted"]), 1) for y in years]},
        "grants": {"names": [x["label"] for x in grant_rows],
                   "count": [round(x["count"] / ok_n * 100, 1) for x in grant_rows],
                   "sum": [round(x["sum"] / appr_total * 100, 1) if appr_total else 0 for x in grant_rows]},
        "ask": {"names": [x["label"] for x in ask_rows],
                "done": [x["done"] for x in ask_rows],
                "rate": [round(x["rate"], 1) for x in ask_rows]},
        "parts": {"names": [x["label"] for x in part_rows],
                  "done": [x["done"] for x in part_rows],
                  "rate": [round(x["rate"], 1) for x in part_rows]},
        "features": {"names": [x["label"] for x in feat_rows],
                     "rate": [round(x["rate"], 1) for x in feat_rows]},
        "types": {"names": [x["name"] for x in type_rows],
                  "n_share": [round(x["n_share"], 1) for x in type_rows],
                  "appr_share": [round(x["appr_share"], 1) for x in type_rows]},
        "recipients": {"names": list(rec.index), "values": [round(v / 1e6, 2) for v in rec.values]},
        "applicants": {"names": [x["name"] for x in app_rows],
                       "ok": [x["ok"] for x in app_rows],
                       "rej": [x["rej"] for x in app_rows]},
        "returning": {"x": [str(x["year"]) for x in ret_rows],
                      "first": [x["first"] for x in ret_rows],
                      "ret": [x["ret"] for x in ret_rows],
                      "first_rate": [round(x["first_rate"], 1) for x in ret_rows],
                      "ret_rate": [round(x["ret_rate"], 1) for x in ret_rows]},
        "lag": {"x": [str(x["year"]) for x in lag_rows],
                "p25": [round(x["p25"]) for x in lag_rows],
                "band": [round(x["p75"]) - round(x["p25"]) for x in lag_rows],
                "p50": [round(x["p50"]) for x in lag_rows]},
    }

    tables = {
        "year": [{"year": str(y), "n": n(by_year.loc[y, "n"]), "ok": n(by_year.loc[y, "ok"]),
                  "rej": n(by_year.loc[y, "rej"]), "rate": pct(by_year.loc[y, "rate"])} for y in years],
        "money": [{"year": str(y), "req": f"{by_year.loc[y, 'req'] / 1e6:,.1f}",
                   "appr": f"{by_year.loc[y, 'appr'] / 1e6:,.1f}",
                   "granted": pct(by_year.loc[y, "granted"])} for y in years],
        "grants": [{"label": x["label"], "count": n(x["count"]),
                    "count_share": pct(x["count"] / ok_n * 100),
                    "sum_share": pct(x["sum"] / appr_total * 100) if appr_total else "—"}
                   for x in grant_rows],
        "ask": [{"label": x["label"], "done": n(x["done"]), "ok": n(x["ok"]), "rate": pct(x["rate"])}
                for x in ask_rows],
        "parts": [{"label": x["label"], "done": n(x["done"]), "rate": pct(x["rate"]),
                   "appr": f"{x['appr'] / 1e6:,.1f}"} for x in part_rows],
        "features": [{"label": x["label"], "done": n(x["done"]), "rate": pct(x["rate"])}
                     for x in feat_rows],
        "types": [{"name": x["name"], "n": n(x["n"]), "rate": pct(x["rate"]),
                   "appr": f"{x['appr'] / 1e6:,.1f}", "appr_share": pct(x["appr_share"])}
                  for x in type_rows],
        "recipients": [{"name": nm, "appr": f"{v / 1e6:,.2f}",
                        "count": n(rec_cnt[c])}
                       for nm, v, c in zip(rec.index, rec.values, rec_code.index)],
        "applicants": [{"name": x["name"], "n": n(x["n"]), "ok": n(x["ok"]), "rej": n(x["rej"]),
                        "years": n(x["years"])} for x in app_rows],
        "returning": [{"year": str(x["year"]), "first": n(x["first"]), "ret": n(x["ret"]),
                       "first_rate": pct(x["first_rate"]), "ret_rate": pct(x["ret_rate"])}
                      for x in ret_rows],
        "lag": [{"year": str(x["year"]), "p25": n(x["p25"]), "p50": n(x["p50"]), "p75": n(x["p75"])}
                for x in lag_rows],
    }

    open_note = ""
    if open_years:
        open_note = (" שנות תמיכה שטרם הוכרעו במלואן: "
                     + ", ".join(f"{y} ({n(by_year.loc[y, 'other'])} בקשות בלי החלטה סופית)"
                                 for y in open_years) + ".")
    other_note = (f" {n(other_status)} בקשות ללא החלטה סופית (בתהליך או סטטוס חסר) אינן נכללות "
                  f"בשיעורי האישור." if other_status else "")
    private_note = (f" {n(n_private)} בקשות של מבקשים שאינם תאגידים מוצגות במצרף בלבד."
                    if n_private else "")
    first_y = years[0]
    labels = {
        "lede": (f"ועדת העזבונות מחלקת כספי עזבונות שהורישו למדינה ללא ייעוד מסוים, כמענקים למוסדות "
                 f"ולגופים ללא כוונת רווח. במאגר {n(total)} בקשות של {n(n_inst)} מוסדות לשנות התמיכה "
                 f"{first_y} עד {last_year}: {pct(rate_all)} מהבקשות שהוכרעו אושרו, והוועדה אישרה "
                 f"לתשלום {money_he(appr_total)} מתוך {money_he(req_done_total)} שהתבקשו לשנה. "
                 f"ההחלטה האחרונה במאגר מ-{last_decision.strftime('%d/%m/%Y') if pd.notna(last_decision) else '—'}."
                 f"{other_note}"),
        "last_rate_kpi": f"שיעור האישור בשנת התמיכה {ly}",
        "granted_kpi": "מהסכום השנתי שהתבקש אושר לתשלום",
        "year_note": (f"בקשות לפי שנת התמיכה שאליה הוגשו ותוצאת ההחלטה (עמודות), ושיעור האישור מתוך "
                      f"הבקשות שהוכרעו (קו).{open_note}"),
        "year_aria": f"גרף משולב: בקשות שאושרו ונדחו ושיעור האישור לפי שנת תמיכה, {first_y} עד {last_year}.",
        "year_caption": "בקשות לפי שנת תמיכה ותוצאת ההחלטה.",
        "money_note": ("הסכום השנתי שהתבקש בכל הבקשות (כולל שנדחו) מול הסכום שאושר לתשלום, במיליוני ₪, "
                       "ושיעור הסכום שאושר מתוך הסכום שהתבקש בבקשות שהוכרעו (קו)."),
        "money_aria": f"גרף משולב: סכום מבוקש וסכום מאושר במיליוני ₪ לפי שנת תמיכה, {first_y} עד {last_year}.",
        "money_caption": "סכום מבוקש וסכום מאושר לפי שנת תמיכה (מיליוני ₪).",
        "grants_note": (f"התפלגות {n(len(ok))} המענקים שאושרו לפי גודל: איזה חלק מהמענקים ואיזה חלק "
                        f"מהכסף נופל בכל טווח. המענק החציוני: {n(med_grant)} ₪."),
        "grants_aria": "תרשים עמודות כפול: שיעור המענקים ושיעור הכסף בכל טווח גודל מענק.",
        "grants_caption": "מענקים שאושרו לפי טווח סכום.",
        "ask_note": "מספר הבקשות שהוכרעו (עמודות) ושיעור האישור (קו) לפי הסכום השנתי שהתבקש.",
        "ask_aria": "גרף משולב: בקשות ושיעור אישור לפי טווח הסכום המבוקש.",
        "ask_caption": "בקשות ושיעור אישור לפי טווח הסכום המבוקש.",
        "parts_note": (f"לפי מספר המשתתפים שהמבקש הצהיר שהפרויקט ישרת (חציון: {n(parts_med)}). "
                       f"מספרים חריגים מאוד מופיעים בקבוצה העליונה כפי שדווחו."),
        "parts_aria": "גרף משולב: בקשות ושיעור אישור לפי מספר המשתתפים בפרויקט.",
        "parts_caption": "בקשות, שיעור אישור וסכום מאושר לפי מספר המשתתפים.",
        "features_note": (f"שיעור האישור לפי מאפייני הפרויקט: {n(multi_n)} בקשות לפרויקט רב־שנתי "
                          f"({n(multi3)} מהן לשלוש שנים), ו-{pct(fee_share)} מהבקשות כוללות "
                          f"תשלום מהמשתתפים."),
        "features_aria": "תרשים עמודות: שיעור האישור לפי מאפייני הפרויקט.",
        "features_caption": "שיעור האישור לפי מאפייני הפרויקט.",
        "types_note": (f"סוג הגוף המבקש, לפי מספר התאגיד: חלקו מהבקשות מול חלקו מהכסף שאושר."
                       f"{private_note}"),
        "types_aria": "תרשים עמודות כפול: שיעור הבקשות ושיעור הכסף המאושר לפי סוג הגוף המבקש.",
        "types_caption": "בקשות, שיעור אישור וסכום מאושר לפי סוג הגוף.",
        "recipients_note": f"{TOP_RECIPIENTS} המוסדות שקיבלו את הסכומים הגדולים ביותר, במיליוני ₪.",
        "recipients_aria": f"תרשים עמודות: {TOP_RECIPIENTS} המוסדות המקבלים לפי סכום מאושר במיליוני ₪.",
        "recipients_caption": f"{TOP_RECIPIENTS} המוסדות שקיבלו את הסכומים הגדולים ביותר.",
        "applicants_note": (f"המוסדות שהגישו הכי הרבה בקשות, ותוצאתן. {pct(one_timers)} מהמוסדות הגישו "
                            f"בשנת תמיכה אחת בלבד; {pct(multi_req)} מהבקשות הוגשו ממוסד שהגיש יותר "
                            f"מבקשה אחת באותה שנה."),
        "applicants_aria": f"תרשים עמודות מוערמות: {TOP_APPLICANTS} המוסדות עם מספר הבקשות הגדול ביותר, לפי תוצאה.",
        "applicants_caption": f"{TOP_APPLICANTS} המוסדות שהגישו הכי הרבה בקשות.",
        "returning_note": (f"בקשות ממוסדות שמגישים לראשונה מול מוסדות שכבר הגישו בשנים קודמות "
                           f"(עמודות), ושיעור האישור של כל קבוצה (קווים). מוצג מ-{years[1] if len(years) > 1 else first_y}, "
                           f"כי בשנה הראשונה במאגר ({first_y}) כל המבקשים נספרים כחדשים."),
        "returning_aria": "גרף משולב: בקשות של מבקשים חדשים וחוזרים ושיעור האישור שלהם לפי שנת תמיכה.",
        "returning_caption": "מבקשים חדשים וחוזרים לפי שנת תמיכה.",
        "lag_note": ("מספר הימים מהגשת הבקשה ועד החלטת הוועדה, לפי שנת התמיכה: החציון (קו) והטווח "
                     "שבין הרבעון התחתון לעליון (רצועה)."),
        "lag_aria": "גרף רצועה: ימים מהגשה להחלטה לפי שנת תמיכה, חציון ורבעונים.",
        "lag_caption": "ימים מהגשה להחלטה לפי שנת תמיכה.",
    }

    return {
        "agent_data": {
            "summary_he": (f"בקשות לוועדת העזבונות במשרד המשפטים: {n(total)} בקשות של {n(n_inst)} מוסדות "
                           f"לשנות התמיכה {first_y} עד {last_year}, {pct(rate_all)} מהן אושרו, ו-{money_he(appr_total)} "
                           f"אושרו לתשלום ממענקי עזבונות ללא ייעוד."),
            "dataset_kind": "rankings",
            "suggested_tags": ["ועדת העזבונות", "עזבונות", "מענקים", "תמיכות", "עמותות",
                               "משרד המשפטים"],
            "related_ids": ["f2949f90-ce4d-4a0a-81ee-d3b931cb7b9b"],
            "temporal_coverage": f"{first_y}/{last_year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
