"""תלונות חופש המידע — complaints to the Freedom of Information Unit.

Two files with different schemas: the live register (complaints received
from 25-04-2021) and a closed archive (2019 to 25-04-2021). Both are mapped
onto one frame. Respondents are public bodies and complainant names appear
only for organisations (citizens are blank), so both are named. "Now" = the
latest complaint date in the data; its year is partial.
"""
import re

import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
DECISIONS = ["מוצדק", "מוצדק חלקית", "בלתי מוצדק", "הטיפול הופסק", "ללא החלטה"]
JUSTIFIED = {"מוצדק", "מוצדק חלקית"}
RULED = {"מוצדק", "מוצדק חלקית", "בלתי מוצדק"}
TOP_BODIES = 15
MIN_RULED_FOR_RATE = 25
TOP_ORGS = 10
DAY_BUCKETS = [(0, 15, "עד שבועיים"), (15, 31, "עד חודש"), (31, 61, "עד חודשיים"),
               (61, 91, "עד שלושה חודשים"), (91, 181, "עד חצי שנה"), (181, 100000, "מעל חצי שנה")]
WAIT_BUCKETS = [(0, 31, "עד חודש"), (31, 61, "חודש–חודשיים"), (61, 91, "חודשיים–שלושה"),
                (91, 181, "שלושה–שישה חודשים"), (181, 366, "חצי שנה–שנה"), (366, 100000, "מעל שנה")]
BODY_FIX = {"צהל": "צה\"ל"}


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _clean(v):
    """Undo the CSV-quoting damage in respondent names: 'X",Y' → X, a stray
    quote after a closing paren, and צהל" → צה"ל. Other quotes are part of
    an abbreviation and stay."""
    v = (v or "").strip()
    m = re.match(r'^(.*?)",', v)
    if m:
        v = m.group(1).strip()
    if v.endswith(')"'):
        v = v[:-1]
    return BODY_FIX.get(v.rstrip('"'), v)


def _status(v):
    v = (v or "").strip()
    if '",' in v:
        v = v.split('",')[-1]
    return v.strip()


def _frame(new, old):
    a = pd.DataFrame({
        "received": pd.to_datetime(new["תאריך קבלת תלונה"], format="%d/%m/%Y", errors="coerce"),
        "requested": pd.to_datetime(new["תאריך הגשת הבקשה למידע"], format="%d/%m/%Y", errors="coerce"),
        "closed": pd.to_datetime(new["תאריך סיום טיפול"], format="%d/%m/%Y", errors="coerce"),
        "channel": new["ערוץ קבלת תלונה"].str.strip().replace({"דואר אלקטרוני": "דוא\"ל"}),
        "ctype": new["סוג המתלונן"].str.strip(),
        "org": new["שם המתלונן"].str.strip(),
        "topic": new["נושא התלונה"].str.strip(),
        "body": new["שם הנילון"].map(_clean),
        "decision": new["החלטה"].str.strip().replace({"": "ללא החלטה"}),
        "open": new["סטטוס"].map(_status).eq("בטיפול"),
        "file": "new",
    })
    b = pd.DataFrame({
        "received": pd.to_datetime(old["תאריך קבלת תלונה"], errors="coerce"),
        "requested": pd.to_datetime(old["תאריך בקשה ראשונית ל מידע"], errors="coerce"),
        "closed": pd.to_datetime(old["תאריך הסגירה"], errors="coerce").dt.normalize(),
        "channel": old["ערוץ קבלה"].str.strip(),
        "ctype": "",
        "org": "",
        "topic": old["נושא  התלונה"].str.strip().replace({"הנחיות מנהליות": "פרסום הנחיות מנהליות", "": "לא צוין"}),
        "body": old["שם הנילון"].map(_clean),
        "decision": old["תיאור החלטה"].str.strip().replace({"": "ללא החלטה"}),
        "open": False,
        "file": "old",
    })
    df = pd.concat([a, b], ignore_index=True).dropna(subset=["received"])
    df["received"] = df["received"].dt.normalize()
    # Placeholder request dates (1900) and requests "after" the complaint are unknown.
    bad = (df["requested"] < pd.Timestamp(2000, 1, 1)) | (df["requested"] > df["received"])
    df.loc[bad, "requested"] = pd.NaT
    df = df.sort_values(["received", "body", "topic", "decision", "file", "channel", "org"], kind="stable")
    return df.reset_index(drop=True)


def _buckets(days, spec):
    return [int(((days >= lo) & (days < hi)).sum()) for lo, hi, _ in spec]


def compute(frames):
    df = _frame(frames["complaints"], frames["archive"])
    n = len(df)
    anchor = df["received"].max()
    cur = int(anchor.year)
    last_full = cur - 1
    y = df["received"].dt.year
    years = list(range(int(y.min()), cur + 1))

    # Volume per quarter + per year
    q = df.groupby(df["received"].dt.to_period("Q")).size()
    qidx = pd.period_range(q.index.min(), q.index.max(), freq="Q")
    volume = {"x": [f"{p.year}-Q{p.quarter}" for p in qidx], "y": [int(q.get(p, 0)) for p in qidx]}
    per_year = df.groupby(y).size()
    year_rows = [{"year": str(yy), "n": _int(per_year.get(yy, 0))} for yy in years]

    # Respondent bodies
    bodies = df["body"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    top_b = bodies.head(TOP_BODIES)
    rest_b = int(bodies.iloc[TOP_BODIES:].sum())
    bodies_chart = {"names": list(top_b.index) + (["גופים אחרים"] if rest_b else []),
                    "values": [int(v) for v in top_b] + ([rest_b] if rest_b else [])}

    ruled = df[df["decision"].isin(RULED)]
    rate_b = ruled.groupby("body")["decision"].agg(lambda s: s.isin(JUSTIFIED).mean())
    cnt_b = ruled.groupby("body").size()
    rate_b = rate_b[cnt_b >= MIN_RULED_FOR_RATE].sort_index().sort_values(ascending=False, kind="stable")
    just_body = {"names": list(rate_b.index), "values": [round(float(v) * 100, 1) for v in rate_b],
                 "n": [int(cnt_b[b]) for b in rate_b.index]}
    body_rows = [{"name": b, "n": _int(top_b[b]),
                  "rate": f"{rate_b[b] * 100:.0f}" if b in rate_b.index else "—"} for b in top_b.index]

    # Decisions by year (% of the year's complaints)
    dec_year = {"x": [str(yy) for yy in years], "series": []}
    for d in DECISIONS:
        vals = []
        for yy in years:
            tot = int(per_year.get(yy, 0))
            vals.append(round(float(((y == yy) & (df["decision"] == d)).sum() / tot * 100), 1) if tot else 0)
        dec_year["series"].append({"name": d, "data": vals})
    dec_rows = [{"year": str(yy), **{f"d{i}": f"{dec_year['series'][i]['data'][j]:.0f}" for i in range(len(DECISIONS))}}
                for j, yy in enumerate(years)]

    # Topics, complainant types, organisations
    topics = df["topic"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    topics_chart = {"names": list(topics.index), "values": [int(v) for v in topics]}
    new = df[df["file"] == "new"]
    ctype = new["ctype"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    ctype_chart = {"names": list(ctype.index), "values": [int(v) for v in ctype]}
    orgs = new[new["org"] != ""]["org"].value_counts().sort_index().sort_values(ascending=False, kind="stable").head(TOP_ORGS)
    orgs_chart = {"names": list(orgs.index), "values": [int(v) for v in orgs]}

    # Handling time
    done = df[df["closed"].notna() & (df["closed"] >= df["received"])].copy()
    done["days"] = (done["closed"] - done["received"]).dt.days
    handling = {"names": [b[2] for b in DAY_BUCKETS], "values": _buckets(done["days"], DAY_BUCKETS)}
    med_year = done.groupby(done["received"].dt.year)["days"].median()
    handling_year = {"x": [str(int(k)) for k in med_year.index], "y": [round(float(v), 1) for v in med_year]}

    # Wait between the information request and the complaint
    w = df[df["requested"].notna()]
    wait_days = (w["received"] - w["requested"]).dt.days
    wait = {"names": [b[2] for b in WAIT_BUCKETS], "values": _buckets(wait_days, WAIT_BUCKETS)}

    # Insights ------------------------------------------------------------
    def ins_volume():
        a, b = int(per_year.get(last_full, 0)), int(per_year.get(last_full - 1, 0))
        if not b:
            return None
        ch = (a - b) / b
        peak = max((int(per_year.get(yy, 0)), yy) for yy in years if yy <= last_full)
        rec = " — השנה עם הכי הרבה תלונות במאגר" if peak[1] == last_full else ""
        if abs(ch) < 0.05:
            return f"ב-{last_full} התקבלו {_int(a)} תלונות, בדומה ל-{last_full - 1} ({_int(b)}){rec}."
        word = "עלייה" if ch > 0 else "ירידה"
        return f"ב-{last_full} התקבלו {_int(a)} תלונות — {word} של {abs(ch) * 100:.0f}% לעומת {last_full - 1} ({_int(b)}){rec}."

    def ins_ytd():
        if anchor.month < 3:
            return None
        a = int(((df["received"] >= pd.Timestamp(cur, 1, 1)) & (df["received"] <= anchor)).sum())
        prev_end = anchor - pd.DateOffset(years=1)
        b = int(((df["received"] >= pd.Timestamp(cur - 1, 1, 1)) & (df["received"] <= prev_end)).sum())
        if b < 20:
            return None
        ch = (a - b) / b
        if abs(ch) < 0.05:
            return f"מתחילת {cur} ועד {d_he(anchor)} התקבלו {_int(a)} תלונות — קצב דומה לתקופה המקבילה אשתקד."
        word = "יותר" if ch > 0 else "פחות"
        return (f"מתחילת {cur} ועד {d_he(anchor)} התקבלו {_int(a)} תלונות — {abs(ch) * 100:.0f}% {word} "
                f"מבתקופה המקבילה ב-{cur - 1} ({_int(b)}).")

    def ins_body():
        if bodies.empty:
            return None
        top = bodies.index[0]
        return (f"{top} הוא הגוף שנגדו הוגשו הכי הרבה תלונות — {_int(bodies.iloc[0])} "
                f"({_pct(bodies.iloc[0] / n)} מכלל התלונות), ואחריו {bodies.index[1]} ({_int(bodies.iloc[1])}).")

    def ins_justified():
        if len(ruled) < 50:
            return None
        rate = ruled["decision"].isin(JUSTIFIED).mean()
        r_last = ruled[ruled["received"].dt.year == last_full]
        tail = ""
        if len(r_last) >= 30:
            tail = f"; ב-{last_full} השיעור עמד על {_pct(r_last['decision'].isin(JUSTIFIED).mean())}"
        return (f"ב-{_pct(rate)} מהתלונות שהוכרעו נמצא שהתלונה מוצדקת, במלואה או בחלקה{tail}.")

    def ins_topic():
        if topics.empty:
            return None
        share = topics.iloc[0] / n
        if share < 0.4:
            return None
        why = " — הרשות לא השיבה לבקשת המידע" if topics.index[0] == "אי מתן מענה" else ""
        return f"{_pct(share)} מהתלונות עוסקות ב{topics.index[0]}{why}."

    def ins_rate_body():
        if len(rate_b) < 3:
            return None
        hi, lo = rate_b.index[0], rate_b.index[-1]
        if rate_b.iloc[0] - rate_b.iloc[-1] < 0.15:
            return None
        return (f"בין הגופים עם {MIN_RULED_FOR_RATE} הכרעות לפחות, שיעור התלונות המוצדקות הגבוה ביותר הוא נגד "
                f"{hi} ({_pct(rate_b.iloc[0])}) והנמוך ביותר נגד {lo} ({_pct(rate_b.iloc[-1])}).")

    def ins_handling():
        if last_full not in med_year.index or (last_full - 1) not in med_year.index:
            return None
        a, b = float(med_year[last_full]), float(med_year[last_full - 1])
        if abs(a - b) < 3:
            return f"חציון משך הטיפול בתלונה שהוגשה ב-{last_full} היה {a:.0f} ימים, בדומה לשנה שלפני."
        word = "התקצר" if a < b else "התארך"
        return f"חציון משך הטיפול בתלונה {word} מ-{b:.0f} ימים ב-{last_full - 1} ל-{a:.0f} ימים ב-{last_full}."

    def ins_orgs():
        if orgs.empty or len(new) < 100:
            return None
        org_share = (new["ctype"] == "עמותה").mean()
        return (f"{_pct(org_share)} מהתלונות מאז {new['received'].min().year} הוגשו על ידי עמותות; "
                f"המתלוננת הפעילה ביותר: {orgs.index[0]} ({_int(orgs.iloc[0])} תלונות).")

    rules = [("volume", ins_volume()), ("ytd", ins_ytd()), ("body", ins_body()),
             ("justified", ins_justified()), ("topic", ins_topic()), ("rate_body", ins_rate_body()),
             ("handling", ins_handling()), ("orgs", ins_orgs())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    just_rate = float(ruled["decision"].isin(JUSTIFIED).mean()) if len(ruled) else None
    med_last = float(med_year[last_full]) if last_full in med_year.index else None
    open_now = int(df["open"].sum())

    def rows(names, values, total):
        return [{"name": a, "n": _int(b), "share": f"{b / total * 100:.1f}" if total else "0"}
                for a, b in zip(names, values)]

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} תלונות שהוגשו ליחידה הממשלתית לחופש המידע מ-{years[0]} ועד "
                           f"{d_he(anchor)}: נגד אילו גופים, על מה, ואיך הוכרעו."),
            "dataset_kind": "timeseries",
            "suggested_tags": ["חופש המידע", "שקיפות", "תלונות", "שירות ציבורי"],
            "temporal_coverage": f"{df['received'].min().strftime('%Y-%m-%d')}/{anchor.strftime('%Y-%m-%d')}",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n)},
            "last_full": {"value": int(per_year.get(last_full, 0)), "display": _int(per_year.get(last_full, 0))},
            "justified": {"value": just_rate, "display": "—" if just_rate is None else _pct(just_rate)},
            "median_days": {"value": med_last, "display": "—" if med_last is None else f"{med_last:.0f} ימים"},
        },
        "charts": {"volume": volume, "bodies": bodies_chart, "just_body": just_body, "decisions": dec_year,
                   "topics": topics_chart, "ctype": ctype_chart, "orgs": orgs_chart,
                   "handling": handling, "handling_year": handling_year, "wait": wait},
        "tables": {
            "years": year_rows, "bodies": body_rows, "decisions": dec_rows, "decision_names": DECISIONS,
            "just_body": [{"name": a, "rate": f"{b:.0f}", "n": _int(c)} for a, b, c in
                          zip(just_body["names"], just_body["values"], just_body["n"])],
            "topics": rows(topics_chart["names"], topics_chart["values"], n),
            "ctype": rows(ctype_chart["names"], ctype_chart["values"], len(new)),
            "orgs": [{"name": a, "n": _int(b)} for a, b in zip(orgs_chart["names"], orgs_chart["values"])],
            "handling": rows(handling["names"], handling["values"], len(done)),
            "handling_year": [{"year": a, "n": f"{b:.0f}"} for a, b in zip(handling_year["x"], handling_year["y"])],
            "wait": rows(wait["names"], wait["values"], int(sum(wait["values"]))),
        },
        "insights": insights,
        "labels": {
            "last_full_label": f"תלונות ב-{last_full}",
            "median_label": f"חציון משך טיפול ({last_full})",
            "lede": (f"{_int(n)} תלונות מ-{d_he(df['received'].min())} ועד {d_he(anchor)}, משני קבצים: "
                     f"ארכיון עד אפריל 2021 ומאגר שוטף מאז. {_int(open_now)} תלונות עדיין בטיפול."),
            "volume_note": f"תלונות לפי רבעון קבלה. {cur} חלקית — עד {d_he(anchor)}.",
            "bodies_note": "הגופים שנגדם הוגשו הכי הרבה תלונות, וכמה מהן נמצאו מוצדקות.",
            "just_note": f"שיעור התלונות שנמצאו מוצדקות (במלואן או בחלקן) מתוך אלה שהוכרעו, לגופים עם {MIN_RULED_FOR_RATE} הכרעות לפחות.",
            "decisions_note": "התפלגות ההחלטות לפי שנת קבלת התלונה. בשנה האחרונה חלק מהתלונות עדיין בטיפול.",
            "ctype_note": f"מי מגיש את התלונות (רק במאגר השוטף, {_int(len(new))} תלונות).",
            "orgs_note": "שמות מתלוננים מופיעים במאגר רק לגבי ארגונים; תלונות של אזרחים אינן מזוהות.",
            "handling_note": f"ימים מקבלת התלונה ועד סיום הטיפול ({_int(len(done))} תלונות שהטיפול בהן הסתיים).",
            "wait_note": f"כמה זמן חלף מהבקשה המקורית למידע ועד שהוגשה תלונה ({_int(len(w))} תלונות עם תאריך בקשה תקין).",
            "volume_aria": f"עמודות: תלונות לפי רבעון, {years[0]} עד {cur}.",
            "bodies_aria": f"עמודות אופקיות: {TOP_BODIES} הגופים שנגדם הוגשו הכי הרבה תלונות.",
            "just_aria": "עמודות אופקיות: שיעור התלונות המוצדקות לפי גוף.",
            "decisions_aria": "עמודות מוערמות באחוזים: החלטות לפי שנת קבלת התלונה.",
            "topics_aria": "עמודות אופקיות: תלונות לפי נושא.",
            "ctype_aria": "עמודות: תלונות לפי סוג המתלונן.",
            "orgs_aria": f"עמודות אופקיות: {TOP_ORGS} הארגונים שהגישו הכי הרבה תלונות.",
            "handling_aria": "עמודות: תלונות לפי משך הטיפול.",
            "handling_year_aria": "קו: חציון משך הטיפול לפי שנת קבלת התלונה.",
            "wait_aria": "עמודות: הזמן שחלף מהבקשה למידע ועד התלונה.",
        },
    }
