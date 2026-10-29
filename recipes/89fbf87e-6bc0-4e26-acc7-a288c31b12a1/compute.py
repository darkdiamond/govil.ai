"""מחירי מוצרים בפיקוח: the maximum legal prices of price-controlled consumer
goods (bread, challah, fresh milk, cheeses, cream, butter, eggs, salt), one row
per product per price update, with history back to 2007.

Searchers want the CURRENT maximum price of a product, so the page leads with
a current-price table (the latest row per product). Charts: change over the
last five years per product, the price history per product group, how many
updates raised or lowered prices each year, and the retail margin (Eilat price,
i.e. consumer price before VAT, versus the retailer price).

Every number and sentence is computed from the rows; insight rules whose
premise doesn't hold return None. "Latest" means latest in the data.

Growth: a new update round appends ~3-20 rows with a new date. New products
flow through (unknown names fall into the "מוצרים נוספים" group). Years axis
grows by one bar a year; the history charts are step lines per product
(a few dozen points each), far under the 50KB script cap.
"""
import re

import pandas as pd

COL_DATE = "update date"
COL_RET = "retailer pricre without VAT"
COL_CON = "consumers price includes VAT"
COL_EIL = "consumer price in Eilat"
COL_PROD = "product"

WINDOW_YEARS = 5
STALE_YEARS = 3          # a product not updated for this long before the latest round
GAP_MIN_MONTHS = 12      # the "longest pause" insight needs at least this
FLAT_PCT = 0.1           # |median change| below this is "no change"
SUMMARY_MAX = 155

# (group name, keyword regex) in display order; first match wins.
GROUPS = [
    ("לחם וחלה", r"לחם|חלה"),
    ("חלב טרי", r"^חלב"),
    ("גבינות", r"גבינ"),
    ("שמנת, חמאה ומשקאות חלב", r"^(?:גיל|אשל)\s|שמנת|חמאה|יוגורט"),
    ("ביצים", r"ביצ"),
    ("מלח", r"^מלח"),
]
OTHER_GROUP = "מוצרים נוספים"
GROUP_ORDER = [g for g, _ in GROUPS] + [OTHER_GROUP]


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(),
                         errors="coerce")


def _group(name):
    for g, rx in GROUPS:
        if re.search(rx, name):
            return g
    return OTHER_GROUP


def _n(k, one, many):
    """'מוצר אחד' / '3 מוצרים'."""
    return one if k == 1 else f"{k:,} {many}"


DROP_WORDS = {"שומן", "(רגיל)", "(רגילה)", "רגילה", "מאכל", "גודל", "טרי", "-"}


def _short(name):
    """Chart-axis label: drop filler words so products stay distinguishable
    at 375px ('חלב טרי בקרטון 1% שומן (רגיל)' -> 'חלב בקרטון 1%')."""
    s = name
    if s.startswith("מלח"):
        s = re.split(r",\s*|\s+ומלח\s", s)[0]
    s = s.replace("-", " - ").replace("ביצי ", "ביצים ")
    words = [w for w in s.split() if w not in DROP_WORDS]
    return " ".join(words) or name


def _shorts(names):
    """Short labels, falling back to the full name where two would collide."""
    sh = [_short(n) for n in names]
    dup = {x for x in sh if sh.count(x) > 1}
    return [n if x in dup else x for n, x in zip(names, sh)]


def _d(d):
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def _p(v):
    return f"{v:,.2f}"


def _chg_he(v):
    """Signed change for RTL prose, in words: a leading '+'/'−' would be
    displayed on the wrong side of the number in Hebrew text."""
    if round(v, 1) == 0:
        return "ללא שינוי"
    return f"{'עלייה' if v > 0 else 'ירידה'} של {abs(v):.1f}%"


def _pct(v, signed=True):
    s = f"{abs(v):.1f}%"
    if not signed:
        return s
    if round(v, 1) == 0:
        return "0.0%"
    return ("+" if v > 0 else "−") + s


def _prepare(df):
    df = df.copy()
    df["product_name"] = df[COL_PROD].map(_clean)
    df["date"] = pd.to_datetime(df[COL_DATE].astype(str).str.strip(),
                                format="%d/%m/%Y", errors="coerce")
    df["con"] = _num(df[COL_CON])
    df["eil"] = _num(df[COL_EIL])
    df["ret"] = _num(df[COL_RET])
    df = df[(df["product_name"] != "") & df["date"].notna()
            & df["con"].notna() & (df["con"] > 0)]
    df = df[["product_name", "date", "con", "eil", "ret"]]
    # One row per product per date (deterministic if the publisher ever duplicates).
    df = df.sort_values(["product_name", "date", "con", "eil", "ret"],
                        kind="stable", na_position="first")
    df = df.drop_duplicates(["product_name", "date"], keep="last")
    df["group"] = df["product_name"].map(_group)
    df["gidx"] = df["group"].map(GROUP_ORDER.index)
    return df.reset_index(drop=True)


def _with_prev(df):
    df = df.sort_values(["product_name", "date"], kind="stable").copy()
    df["prev"] = df.groupby("product_name")["con"].shift(1)
    df["chg"] = (df["con"] / df["prev"] - 1) * 100
    return df


def _latest(df):
    """Latest row per product, with the previous price and change."""
    h = _with_prev(df)
    last = h.groupby("product_name", sort=True).tail(1)
    last = last.sort_values(["gidx", "product_name"], kind="stable")
    return last.reset_index(drop=True)


def _window(df, latest_date):
    """Change from the price in effect WINDOW_YEARS before the latest update."""
    ref = latest_date - pd.DateOffset(years=WINDOW_YEARS)
    rows, no_base, stale = [], 0, 0
    for name, g in df.groupby("product_name", sort=True):
        g = g.sort_values("date")
        before = g[g["date"] <= ref]
        if before.empty:
            no_base += 1
            continue
        if g["date"].max() <= ref:
            stale += 1
            continue
        b = before.iloc[-1]
        e = g.iloc[-1]
        rows.append({
            "name": name,
            "group": e["group"],
            "base": float(b["con"]),
            "base_date": b["date"],
            "now": float(e["con"]),
            "chg": float((e["con"] / b["con"] - 1) * 100),
        })
    rows.sort(key=lambda r: (-round(r["chg"], 6), r["name"]))
    return ref, rows, no_base, stale


def _yearly(df):
    h = _with_prev(df)
    h = h[h["prev"].notna()].copy()
    h["year"] = h["date"].dt.year
    h["dir"] = 0
    h.loc[h["con"] > h["prev"], "dir"] = 1
    h.loc[h["con"] < h["prev"], "dir"] = -1
    if h.empty:
        return [], h
    y0, y1 = int(df["date"].dt.year.min()), int(df["date"].dt.year.max())
    out = []
    for y in range(y0, y1 + 1):
        s = h[h["year"] == y]
        out.append({"year": y, "up": int((s["dir"] == 1).sum()),
                    "down": int((s["dir"] == -1).sum()),
                    "same": int((s["dir"] == 0).sum())})
    return out, h


def _margins(latest):
    m = latest[latest["ret"].notna() & latest["eil"].notna()
               & (latest["ret"] > 0)].copy()
    m["margin"] = (m["eil"] / m["ret"] - 1) * 100
    m = m.sort_values(["margin", "product_name"], ascending=[False, True],
                      kind="stable")
    return m


def _gap(dates):
    ds = sorted(set(dates))
    best = None
    for a, b in zip(ds, ds[1:]):
        days = (b - a).days
        if best is None or days > best[0]:
            best = (days, a, b)
    return best


# ---------------------------------------------------------------- insights

def _ins_latest_round(latest, latest_date):
    r = latest[latest["date"] == latest_date]
    r = r[r["chg"].notna()]
    if r.empty:
        return None
    med = float(r["chg"].median())
    n = len(r)
    lo, hi = float(r["chg"].min()), float(r["chg"].max())
    if med > FLAT_PCT:
        what = f"המחיר המרבי עלה בשיעור חציוני של {_pct(med, False)}"
    elif med < -FLAT_PCT:
        what = f"המחיר המרבי ירד בשיעור חציוני של {_pct(med, False)}"
    else:
        what = "המחיר המרבי כמעט לא השתנה"
    rng = ""
    if n > 1 and round(hi - lo, 1) > 0:
        if lo >= 0 or hi <= 0:
            word = "עליות" if hi > 0 else "ירידות"
            rng = f" ({word} של {abs(lo) if lo >= 0 else abs(hi):.1f}% עד {abs(hi) if lo >= 0 else abs(lo):.1f}%)"
        else:
            rng = f" (מ{_chg_he(lo)} עד {_chg_he(hi)})"
    return (f"בעדכון האחרון במאגר, מ-{_d(latest_date)}, עודכנו {n} מוצרים: "
            f"{what} לעומת המחיר הקודם{rng}.")


def _ins_window_top(wrows, ref):
    if len(wrows) < 3:
        return None
    top, low = wrows[0], wrows[-1]
    if round(top["chg"], 1) <= 0 or round(top["chg"] - low["chg"], 1) < 1:
        return None
    med = float(pd.Series([r["chg"] for r in wrows]).median())
    if round(low["chg"], 1) >= 0:
        tail = f"העלייה המתונה ביותר: {low['name']}, {low['chg']:.1f}%."
    else:
        tail = f"הירידה החדה ביותר: {low['name']}, {abs(low['chg']):.1f}%."
    return (f"ב-{WINDOW_YEARS} השנים האחרונות (מאז {_d(ref)}) העלייה החדה ביותר "
            f"הייתה ב{top['name']}: {top['chg']:.1f}%, מ-{_p(top['base'])} "
            f"ל-{_p(top['now'])} ₪. {tail} החציון בין {len(wrows)} המוצרים: "
            f"{_chg_he(med)}.")


def _ins_gap(df):
    g = _gap(list(df["date"]))
    if g is None:
        return None
    days, a, b = g
    months = int(round(days / 30.44))
    if months < GAP_MIN_MONTHS:
        return None
    return (f"ההפסקה הארוכה ביותר בין עדכוני מחיר נמשכה כ-{months} חודשים: "
            f"מ-{_d(a)} ועד {_d(b)}, אז לא עודכן אף מחיר במאגר.")


def _ins_declines(h):
    if h.empty:
        return None
    downs = h[h["dir"] == -1]
    total = len(h)
    if len(downs) == 0:
        return (f"מתוך {total:,} שינויי מחיר במאגר אף אחד לא היה הורדה: "
                "המחיר המרבי רק עלה או נשאר במקומו.")
    by_year = downs.groupby(downs["date"].dt.year).size()
    by_year = by_year.sort_index()
    top_year = int(by_year.idxmax())
    top_n = int(by_year.max())
    share = len(downs) / total * 100
    if share < 5:
        return None
    return (f"לא כל עדכון הוא התייקרות: {len(downs):,} מתוך {total:,} שינויי "
            f"המחיר במאגר ({share:.0f}%) היו הורדות, והשנה עם מרב ההורדות "
            f"היא {top_year} ({top_n:,}).")


def _ins_eilat(latest):
    r = latest[latest["eil"].notna() & (latest["eil"] > 0)]
    if len(r) < 3:
        return None
    disc = (1 - r["eil"] / r["con"]) * 100
    med = float(disc.median())
    if med < 1:
        return None
    return (f"באילת, הפטורה ממע״מ, המחיר המרבי העדכני נמוך בכ-{med:.1f}% "
            f"(חציון על פני {len(r)} מוצרים) מהמחיר לצרכן בשאר הארץ.")


def _ins_stale(latest, latest_date):
    cut = latest_date - pd.DateOffset(years=STALE_YEARS)
    s = latest[latest["date"] < cut].sort_values(["date", "product_name"],
                                                 kind="stable")
    if s.empty:
        return None
    names = list(s["product_name"])
    shown = ", ".join(names[:3]) + (f" ועוד {len(names) - 3}" if len(names) > 3 else "")
    oldest = s["date"].min()
    if len(names) == 1:
        return (f"מחיר אחד במאגר לא עודכן יותר מ-{STALE_YEARS} שנים לפני העדכון "
                f"האחרון: {shown}, שהמחיר האחרון שלו פורסם ב-{_d(oldest)}.")
    return (f"{len(names)} מוצרים לא עודכנו יותר מ-{STALE_YEARS} שנים לפני העדכון "
            f"האחרון ({shown}); הוותיק שבהם פורסם ב-{_d(oldest)}.")


def _ins_margin(m):
    if len(m) < 3:
        return None
    top, low = m.iloc[0], m.iloc[-1]
    if round(float(top["margin"] - low["margin"]), 1) < 1:
        return None
    return (f"הפער בין המחיר לקמעונאי למחיר לצרכן לפני מע״מ הגדול ביותר הוא "
            f"ב{top['product_name']} ({top['margin']:.1f}%), והקטן ביותר "
            f"ב{low['product_name']} ({low['margin']:.1f}%).")


# ---------------------------------------------------------------- main

def compute(frames):
    df = _prepare(frames["main"])
    if df.empty:
        raise ValueError("no usable rows")
    latest_date = df["date"].max()
    first_date = df["date"].min()
    latest = _latest(df)
    n_products = len(latest)
    in_round = latest[latest["date"] == latest_date]
    round_chg = in_round["chg"].dropna()

    ref, wrows, no_base, stale_w = _window(df, latest_date)
    yearly, hist = _yearly(df)
    margins = _margins(latest)

    groups_present = [g for g in GROUP_ORDER if g in set(latest["group"])]

    # ---- KPIs
    kpis = {
        "products": {"value": n_products, "display": f"{n_products:,}",
                     "tone": "brand"},
        "last": {"value": _d(latest_date), "display": _d(latest_date),
                 "tone": "info"},
    }
    if len(round_chg):
        med = float(round_chg.median())
        tone = "warn" if med > FLAT_PCT else ("ok" if med < -FLAT_PCT else "brand")
        kpis["round"] = {"value": round(med, 2), "display": _pct(med),
                         "tone": tone}
    if wrows:
        wmed = float(pd.Series([r["chg"] for r in wrows]).median())
        tone = "warn" if wmed > FLAT_PCT else ("ok" if wmed < -FLAT_PCT else "brand")
        kpis["window"] = {"value": round(wmed, 2), "display": _pct(wmed),
                          "tone": tone}

    # ---- current price table
    price_rows = []
    for _, r in latest.iterrows():
        price_rows.append({
            "name": r["product_name"],
            "group": r["group"],
            "con": _p(r["con"]),
            "eil": _p(r["eil"]) if pd.notna(r["eil"]) else "",
            "ret": _p(r["ret"]) if pd.notna(r["ret"]) else "",
            "date": _d(r["date"]),
            "chg": _pct(r["chg"]) if pd.notna(r["chg"]) else "",
            "chg_tone": ("" if pd.isna(r["chg"]) or round(r["chg"], 1) == 0
                         else ("up" if r["chg"] > 0 else "down")),
            "stale": bool(r["date"] < latest_date - pd.DateOffset(years=STALE_YEARS)),
        })

    # ---- window chart (5-year change)
    window_chart = None
    if len(wrows) >= 2:
        window_chart = {
            "names": [r["name"] for r in wrows],
            "short": _shorts([r["name"] for r in wrows]),
            "values": [round(r["chg"], 1) for r in wrows],
            "base": [round(r["base"], 2) for r in wrows],
            "now": [round(r["now"], 2) for r in wrows],
        }
    window_table = [{"name": r["name"], "base": _p(r["base"]),
                     "base_date": _d(r["base_date"]), "now": _p(r["now"]),
                     "chg": _pct(r["chg"])} for r in wrows]

    # ---- history per group (step lines; x = ISO date)
    history = []
    for gi, g in enumerate(groups_present):
        sub = df[df["group"] == g]
        series = []
        for name, s in sub.groupby("product_name", sort=True):
            s = s.sort_values("date")
            pts = [[d.strftime("%Y-%m-%d"), round(float(v), 2)]
                   for d, v in zip(s["date"], s["con"])]
            series.append({"name": name, "data": pts})
        for sr, sh in zip(series, _shorts([x["name"] for x in series])):
            sr["short"] = sh
        last_rows = latest[latest["group"] == g]
        top = last_rows.sort_values(["con", "product_name"],
                                    ascending=[False, True], kind="stable").iloc[0]
        n_top = int((last_rows["con"].round(2) == round(float(top["con"]), 2)).sum())
        lede = (f"{_n(len(series), 'מוצר אחד', 'מוצרים')}, {len(sub):,} עדכוני מחיר מ-"
                f"{sub['date'].min().year} עד {sub['date'].max().year}. ")
        if n_top == 1 and len(last_rows) > 1:
            lede += f"היקר כעת: {top['product_name']}, {_p(top['con'])} ₪."
        else:
            lede += f"המחיר המרבי העדכני: {_p(top['con'])} ₪."
        aria = (f"גרף קווים מדורג: המחיר המרבי לצרכן של {g} לפי תאריך עדכון, "
                f"{sub['date'].min().year} עד {sub['date'].max().year}.")
        history.append({"id": f"chart-hist-{gi}", "title": g, "lede": lede,
                        "aria": aria, "series": series})

    # ---- yearly direction chart
    years_chart = None
    years_table = []
    if yearly:
        years_chart = {"years": [str(y["year"]) for y in yearly],
                       "up": [y["up"] for y in yearly],
                       "down": [y["down"] for y in yearly],
                       "same": [y["same"] for y in yearly]}
        years_table = [{"year": y["year"], "up": y["up"], "down": y["down"],
                        "same": y["same"]} for y in yearly]
    n_changes = int(len(hist))
    n_up = int((hist["dir"] == 1).sum()) if n_changes else 0
    n_down = int((hist["dir"] == -1).sum()) if n_changes else 0
    busiest = None
    if yearly:
        b = sorted(yearly, key=lambda y: (-(y["up"] + y["down"] + y["same"]), y["year"]))[0]
        busiest = b

    # ---- margin chart
    margin_chart = None
    margin_table = []
    if len(margins) >= 2:
        margin_chart = {"names": list(margins["product_name"]),
                        "short": _shorts(list(margins["product_name"])),
                        "values": [round(float(v), 1) for v in margins["margin"]],
                        "ret": [round(float(v), 2) for v in margins["ret"]],
                        "eil": [round(float(v), 2) for v in margins["eil"]]}
        margin_table = [{"name": r["product_name"], "ret": _p(r["ret"]),
                         "eil": _p(r["eil"]), "margin": f"{r['margin']:.1f}%"}
                        for _, r in margins.iterrows()]

    # ---- insights
    rules = [
        ("latest_round", _ins_latest_round(latest, latest_date)),
        ("window", _ins_window_top(wrows, ref)),
        ("declines", _ins_declines(hist)),
        ("gap", _ins_gap(df)),
        ("stale", _ins_stale(latest, latest_date)),
        ("margin", _ins_margin(margins)),
        ("eilat", _ins_eilat(latest)),
    ]
    insights = [{"id": k, "text_he": t} for k, t in rules if t]

    # ---- labels
    groups_txt = ", ".join(groups_present)
    lede = (f"המחירים המרביים שמותר לגבות על {n_products} מוצרי צריכה בסיסיים "
            f"שבפיקוח מחירים ({groups_txt}), כפי שפורסמו מ-{first_date.year} ועד "
            f"העדכון האחרון ב-{_d(latest_date)}. לכל מוצר: המחיר לצרכן כולל "
            f"מע״מ, המחיר באילת והמחיר לקמעונאי, עם היסטוריית העדכונים המלאה.")
    labels = {
        "lede": lede,
        "products_kpi": "מוצרים בפיקוח במאגר",
        "last_kpi": "תאריך העדכון האחרון",
        "round_kpi": (f"שינוי חציוני במחיר בעדכון האחרון ({len(round_chg)} מוצרים)"
                      if len(round_chg) else ""),
        "window_kpi": (f"שינוי חציוני ב-{WINDOW_YEARS} השנים האחרונות ({len(wrows)} מוצרים)"
                       if wrows else ""),
        "table_note": (f"המחיר המרבי העדכני של כל אחד מ-{n_products} המוצרים, לפי "
                       f"השורה האחרונה שלו במאגר. המחירים בשקלים ליחידת המוצר "
                       f"המפוקחת, כפי שפורסמו (המאגר אינו מציין גודל אריזה)."
                       + (f" מוצר שלא עודכן יותר מ-{STALE_YEARS} שנים מסומן."
                          if any(r["stale"] for r in price_rows) else "")),
        "table_caption": f"המחיר המרבי העדכני ל-{n_products} מוצרים בפיקוח",
        "window_note": "",
        "window_aria": "",
        "window_caption": "",
        "years_note": "",
        "years_aria": "",
        "years_caption": "",
        "margin_note": "",
        "margin_aria": "",
        "margin_caption": "",
    }
    if window_chart:
        excl = []
        if no_base:
            excl.append(f"{_n(no_base, 'מוצר אחד', 'מוצרים')} ללא מחיר מלפני {_d(ref)}")
        if stale_w:
            excl.append(f"{_n(stale_w, 'מוצר אחד', 'מוצרים')} שלא עודכן מאז")
        top = wrows[0]
        labels["window_note"] = (
            f"השינוי במחיר המרבי לצרכן מהמחיר שהיה בתוקף ב-{_d(ref)} ועד המחיר "
            f"העדכני. בראש: {top['name']}, {_chg_he(top['chg'])}."
            + (f" לא נכללו: {', '.join(excl)}." if excl else ""))
        labels["window_aria"] = (
            f"גרף עמודות אופקי: שינוי המחיר ב-{WINDOW_YEARS} השנים האחרונות לפי "
            f"מוצר. בראש: {top['name']}, {_chg_he(top['chg'])}.")
        labels["window_caption"] = f"שינוי המחיר המרבי מאז {_d(ref)} לפי מוצר"
    if years_chart:
        labels["years_note"] = (
            f"כל שינוי מחיר של מוצר לעומת העדכון הקודם שלו: {n_changes:,} שינויים, "
            f"מהם {n_up:,} התייקרויות ו-{n_down:,} הוזלות."
            + (f" השנה העמוסה ביותר: {busiest['year']}, עם "
               f"{busiest['up'] + busiest['down'] + busiest['same']:,} שינויים."
               if busiest else ""))
        labels["years_aria"] = (
            f"גרף עמודות מוערמות: מספר העלאות והורדות של מחירים מרביים בכל שנה, "
            f"{yearly[0]['year']} עד {yearly[-1]['year']}. סך הכול {n_up:,} "
            f"העלאות ו-{n_down:,} הורדות.")
        labels["years_caption"] = "עדכוני מחיר לפי שנה וכיוון השינוי"
    if margin_chart:
        t = margins.iloc[0]
        labels["margin_note"] = (
            f"המרווח בין המחיר לקמעונאי (ללא מע״מ) למחיר לצרכן באילת, שהוא המחיר "
            f"לצרכן ללא מע״מ, במחיר העדכני של {len(margins)} מוצרים שהמחיר "
            f"לקמעונאי שלהם מופיע במאגר. הגבוה ביותר: {t['product_name']}, "
            f"{t['margin']:.1f}%.")
        labels["margin_aria"] = (
            f"גרף עמודות אופקי: המרווח הקמעונאי באחוזים לפי מוצר. הגבוה ביותר: "
            f"{t['product_name']}, {t['margin']:.1f}%.")
        labels["margin_caption"] = "מחיר לקמעונאי, מחיר לצרכן ללא מע״מ ומרווח לפי מוצר"

    # ---- summary (meta description)
    summary = (f"מה המחיר המרבי המותר לחלב, לחם, ביצים וגבינות? {n_products} "
               f"מוצרים בפיקוח מחירים, עדכון אחרון {_d(latest_date)}")
    if len(round_chg):
        summary += f", {_chg_he(float(round_chg.median()))} (חציון)"
    summary += "."
    if len(summary) > SUMMARY_MAX:
        summary = (f"המחיר המרבי המותר ל-{n_products} מוצרים בפיקוח מחירים, "
                   f"עדכון אחרון {_d(latest_date)}.")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "suggested_tags": ["פיקוח מחירים", "מחירי מזון", "חלב ומוצריו", "לחם",
                           "ביצים", "יוקר המחיה"],
        "related_ids": ["013bf5b9-c7ff-4282-b402-73ed20deeacc",
                        "a7e4c07e-8898-414c-91eb-e1f9ed3eb4e6",
                        "ed8ce28e-ae7f-4588-b3f9-59485960d521"],
        "temporal_coverage": f"{first_date.year}/{latest_date.year}",
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "window": window_chart,
            "years": years_chart,
            "margin": margin_chart,
            "history": history,
        },
        "insights": insights,
        "labels": labels,
        "tables": {
            "prices": price_rows,
            "window": window_table,
            "years": years_table,
            "margin": margin_table,
        },
        "flags": {
            "stale": any(r["stale"] for r in price_rows),
        },
    }
