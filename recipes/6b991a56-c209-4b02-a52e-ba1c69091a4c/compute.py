"""דרגת זיהום אוויר של כלי צמ"ה — air-pollution grade of active heavy equipment.

One row per active machine (~185k): type, maker, manufacture year, engine
power (kW), fuel, the Ministry of Environment's pollution grade, whether a
particulate filter is fitted, and whether the machine is authorised to
operate. Machine and chassis numbers are lookup identifiers and never reach
the page — everything here is aggregated.

The register carries no registration date, so "now" is the latest
manufacture year in the data (its vintage), never the wall clock. The
sibling recipe 0219b34f (the Transport Ministry's equipment register) covers
fleet size, registrations, weight and lift; this page is about emissions.
"""
import pandas as pd

YEAR_FROM = 1990
TOP_TYPES = 12
TOP_MAKERS = 12
MIN_TYPE = 1000          # machines, for the "most restricted type" insight
MIN_BAND = 100           # machines, for power-band comparisons
POLLUTING = "מזהם"
UNRANKABLE = "לא ניתן לדרג"
REDUCED = "מופחת זיהום"
ELECTRIC_GRADE = "כלי חשמלי"
UNAUTH = "לא מורשה פעילות"
AUTH = "מורשה פעילות"
DIESEL = "סולר"
# Ordinal grade order (most polluting first) and colours: red marks the
# polluting grade (its meaning), the rest run dark→light blue as emissions
# fall; grey for "cannot be graded". Unknown future grades get palette tones.
GRADE_ORDER = [POLLUTING, "רגיל", REDUCED, "נקי", ELECTRIC_GRADE, UNRANKABLE]
GRADE_COLOR = {POLLUTING: "#dc3545", "רגיל": "#0c3058", REDUCED: "#2658a0",
               "נקי": "#6c9fd8", ELECTRIC_GRADE: "#b7d2f7", UNRANKABLE: "#6c757d"}
EXTRA_COLORS = ["#0068f5", "#3d70b0", "#0053c4", "#dbe8fb", "#0b3668"]
# EU non-road engine power categories (kW) — the bands emission stages use.
POWER_BANDS = [(0, 19), (19, 37), (37, 56), (56, 75), (75, 130), (130, 560), (560, None)]
SMALL_MAX = 37
LARGE_MAX = 560
AGE_BUCKETS = [(0, 4), (5, 9), (10, 14), (15, 19), (20, 29), (30, None)]
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    """Percent with bidi isolates; never rounds a partial share to 0 or 100."""
    step = 10 ** -digits
    if 0 < v < step:
        return f"פחות מ-{LRI}{step:.{digits}f}%{PDI}"
    if 100 - step < v < 100:
        v = 100 - step
    return f"{LRI}{v:.{digits}f}%{PDI}"


def pct_plain(v):
    """Table percent (one decimal) that never rounds a partial share to 0 or 100."""
    if 0 < v < 0.1:
        v = 0.1
    elif 99.9 < v < 100:
        v = 99.9
    return f"{v:.1f}%"


def band_label(lo, hi):
    return f"{lo}+" if hi is None else f"\u2066{lo}–{hi}\u2069"


def _prepare(df):
    out = pd.DataFrame({
        "type": df["sug_tzama_nm"].str.split().str.join(" "),
        "maker": df["yatzran"].str.strip(),
        "fuel": df["hanaa_nm"].str.strip(),
        "grade": df["dargat_zihum_avir"].str.strip(),
        "dpf": df["hutkan_mesanen_helkikim"].str.strip() == "כן",
        "auth": df["murshe_peelut"].str.strip(),
        "year": pd.to_numeric(df["shnat_yitzur"], errors="coerce"),
        "kw": pd.to_numeric(df["power_engine_kilowalt"], errors="coerce"),
    })
    for c, unk in (("type", "לא ידוע"), ("maker", "לא ידוע"),
                   ("fuel", "הנעה לא ידועה"), ("grade", "ללא דרגה"),
                   ("auth", "סטטוס לא ידוע")):
        out[c] = out[c].replace("", unk)
    out["unauth"] = out["auth"] == UNAUTH
    return out


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _grade_order(grades):
    counts = _sorted_counts(grades)
    known = [g for g in GRADE_ORDER if g in counts.index]
    return known + [g for g in counts.index if g not in GRADE_ORDER]


def _colors(order):
    extra = iter(EXTRA_COLORS * (len(order) // len(EXTRA_COLORS) + 1))
    return [GRADE_COLOR[g] if g in GRADE_COLOR else next(extra) for g in order]


def _band(kw):
    for lo, hi in POWER_BANDS:
        if kw >= lo and (hi is None or kw < hi):
            return band_label(lo, hi)
    return None


def _mix(df, key, keys, order):
    """Per-key grade shares (%) for a 100% stacked bar, plus counts."""
    sub = df[df[key].isin(keys)]
    ct = pd.crosstab(sub[key], sub["grade"]).reindex(index=keys, columns=order, fill_value=0)
    tot = ct.sum(axis=1)
    series = [{"name": g, "data": [round(float(v) / t * 100, 1) if t else 0
                                    for v, t in zip(ct[g], tot)]} for g in order]
    unauth = sub.groupby(key)["unauth"].mean().reindex(keys)
    return ct, tot, series, unauth


def insight_polluting(grades, total, n_unauth):
    p = int(grades.get(POLLUTING, 0))
    if total == 0 or p / total < 0.05:
        return None
    s = f"{n(p)} כלים ({pct(p / total * 100)}) מדורגים \"{POLLUTING}\" — הדרגה הגבוהה ביותר."
    if p and n_unauth:
        s += f" {pct(n_unauth / p * 100)} מהם ({n(n_unauth)}) אינם מורשים לפעול."
    return s


def insight_unauth(df, n_unauth):
    if n_unauth == 0:
        return None
    pol = int((df["unauth"] & (df["grade"] == POLLUTING)).sum())
    share = pol / n_unauth
    if share == 1:
        lead = f"כל {n(n_unauth)} הכלים שאינם מורשים לפעול מדורגים \"{POLLUTING}\""
    elif share >= 0.95:
        lead = (f"{pct(share * 100)} מ-{n(n_unauth)} הכלים שאינם מורשים לפעול "
                f"מדורגים \"{POLLUTING}\"")
    else:
        return None
    others = df[df["grade"] != POLLUTING]
    tail = (" — אין אף כלי בדרגה אחרת שנמנעה ממנו פעילות."
            if not others["unauth"].any() else ".")
    return lead + tail


def insight_power(band_rows):
    by = {r["band"]: r for r in band_rows}
    small = [r for r in band_rows if r["hi"] is not None and r["hi"] <= SMALL_MAX]
    mid = [r for r in band_rows if r["lo"] >= SMALL_MAX and r["hi"] is not None
           and r["hi"] <= LARGE_MAX]
    big = by.get(band_label(LARGE_MAX, None))

    def rate(rows):
        p = sum(r["pol"] for r in rows)
        return (sum(r["pol_unauth"] for r in rows) / p, p) if p else (None, 0)

    rs, ps = rate(small)
    rm, pm = rate(mid)
    if rs is None or rm is None or ps < MIN_BAND or pm < MIN_BAND or rm < 0.8 or rs > 0.2:
        return None
    s = (f"בקרב הכלים המזהמים, {pct(rm * 100)} מהכלים בהספק \u2066{SMALL_MAX}–{LARGE_MAX}\u2069 קילוואט "
         f"אינם מורשים לפעול, לעומת {pct(rs * 100)} בלבד מהכלים הקטנים מ-{SMALL_MAX} קילוואט")
    if big and big["pol"] >= 50 and big["pol_unauth"] / big["pol"] <= 0.2:
        s += (f" ואף לא אחד מ-{n(big['pol'])} הכלים המזהמים של {LARGE_MAX} קילוואט ומעלה"
              if big["pol_unauth"] == 0 else
              f" ו-{pct(big['pol_unauth'] / big['pol'] * 100)} מהכלים של {LARGE_MAX} "
              f"קילוואט ומעלה")
    return s + " — ההגבלה חלה בפועל על טווח ההספק הבינוני."


def insight_last_polluting(df, max_year):
    pol_years = df.loc[df["grade"] == POLLUTING, "year"].dropna()
    if pol_years.empty:
        return None
    last = int(pol_years.max())
    if last >= max_year - 1:
        return None
    later = df[(df["year"] > last) & (df["fuel"] == DIESEL) & (df["grade"] != UNRANKABLE)]
    s = f"אף כלי שיוצר אחרי {last} אינו מדורג \"{POLLUTING}\""
    if len(later) >= MIN_BAND:
        red = (later["grade"] == REDUCED).mean()
        s += (f"; {pct(red * 100)} מכלי הדיזל שיוצרו מ-{last + 1} ואילך מדורגים "
              f"\"{REDUCED}\"")
    return s + "."


def insight_age(df, max_year):
    ages = (max_year - df["year"]).where(df["year"].between(1900, max_year))
    a_all = ages.dropna()
    a_un = ages[df["unauth"]].dropna()
    if len(a_un) < MIN_BAND or a_all.empty:
        return None
    m_all, m_un = int(a_all.median()), int(a_un.median())
    if m_un - m_all < 3:
        return None
    return (f"הגיל החציוני של כלי שאינו מורשה לפעול הוא {m_un} שנים, לעומת {m_all} שנים "
            f"בכלל הכלים (לפי שנת ייצור, ביחס ל-{max_year}).")


def insight_type(type_stats):
    big = type_stats[type_stats["n"] >= MIN_TYPE]
    if big.empty:
        return None
    big = big.sort_index().sort_values("un", ascending=False, kind="stable")
    name, row = big.index[0], big.iloc[0]
    if row["un"] < 0.2:
        return None
    return (f"מבין סוגי הכלים עם {n(MIN_TYPE)} כלים ומעלה, השיעור הגבוה ביותר של כלים שאינם "
            f"מורשים לפעול הוא ב{name}: {pct(row['un'] * 100)} מתוך {n(row['n'])} כלים.")


def insight_maker(df, makers):
    top = [m for m in makers.index if m != "לא ידוע"][:10]
    if len(top) < 3:
        return None
    sh = (df[df["maker"].isin(top)].groupby("maker")["grade"]
          .apply(lambda s: (s == POLLUTING).mean()).reindex(top))
    sh = sh.sort_index().sort_values(ascending=False, kind="stable")
    hi_m, lo_m = sh.index[0], sh.index[-1]
    if sh.iloc[0] - sh.iloc[-1] < 0.2:
        return None
    return (f"בין {len(top)} היצרנים הנפוצים, שיעור הכלים המזהמים נע בין {pct(sh.iloc[-1] * 100)} "
            f"ב-{lo_m} ל-{pct(sh.iloc[0] * 100)} ב-{hi_m}.")


def insight_filter(df, total):
    k = int(df["dpf"].sum())
    if total == 0 or k / total >= 0.01:
        return None
    if k == 0:
        return "אף כלי במאגר אינו רשום עם מסנן חלקיקים מותקן."
    s = f"רק {n(k)} כלים במאגר רשומים עם מסנן חלקיקים מותקן"
    pol = df[df["dpf"] & (df["grade"] == POLLUTING)]
    if len(pol) and not pol["unauth"].any():
        s += f"; כל {n(len(pol))} הכלים המזהמים שבהם הותקן מסנן מורשים לפעול"
    return s + "."


def unrankable_note(df):
    u = df[df["grade"] == UNRANKABLE]
    if u.empty:
        return ""
    no_kw = (u["kw"].fillna(0) == 0).mean()
    who = "כולם" if no_kw == 1 else f"{pct(no_kw * 100)} מהם"
    return f" {n(len(u))} כלים מסווגים \"{UNRANKABLE}\"; {who} רשומים ללא הספק מנוע."


def compute(frames):
    df = _prepare(frames["grades"])
    total = len(df)
    max_year = int(df["year"].max())
    grades = _sorted_counts(df["grade"])
    order = _grade_order(df["grade"])
    colors = _colors(order)
    n_unauth = int(df["unauth"].sum())
    n_pol = int(grades.get(POLLUTING, 0))
    low = int(df["grade"].isin([REDUCED, "נקי", ELECTRIC_GRADE]).sum())
    n_dpf = int(df["dpf"].sum())

    # 1. grade distribution
    grade_rows = [{"name": g, "count": int(grades[g]),
                   "share": round(float(grades[g]) / total * 100, 1),
                   "unauth": int(df.loc[df["grade"] == g, "unauth"].sum())} for g in order]

    # 2. flow: fuel → grade → authorisation
    # Sankey only: fuels under 1% of the fleet share one node (the table keeps them apart).
    fuel_counts = _sorted_counts(df["fuel"])
    minor = set(fuel_counts.index[fuel_counts / total < 0.01])
    flow_fuel = df["fuel"].where(~df["fuel"].isin(minor), "הנעה אחרת או לא ידועה") \
        if len(minor) > 1 else df["fuel"]
    fuels = list(_sorted_counts(flow_fuel).index)
    auths = list(_sorted_counts(df["auth"]).index)
    used = set()

    def node(name, suffix):
        out = name if name not in used else f"{name} ({suffix})"
        used.add(out)
        return out
    fuel_n = {f: node(f, "הנעה") for f in fuels}
    grade_n = {g: node(g, "דרגה") for g in order}
    auth_n = {a: node(a, "סטטוס") for a in auths}
    auth_col = {UNAUTH: "#dc3545", AUTH: "#0068f5"}
    nodes = ([{"name": fuel_n[f], "itemStyle": {"color": "#0b3668"}} for f in fuels]
             + [{"name": grade_n[g], "itemStyle": {"color": c}} for g, c in zip(order, colors)]
             + [{"name": auth_n[a], "itemStyle": {"color": auth_col.get(a, "#6c757d")}}
                for a in auths])
    fg = df.groupby([flow_fuel, df["grade"]]).size()
    fg_detail = df.groupby(["fuel", "grade"]).size()
    ga = df.groupby(["grade", "auth"]).size()
    links = ([{"source": fuel_n[f], "target": grade_n[g], "value": int(v)}
              for (f, g), v in fg.items()]
             + [{"source": grade_n[g], "target": auth_n[a], "value": int(v)}
                for (g, a), v in ga.items()])
    links.sort(key=lambda l: (l["source"], l["target"]))
    flow_rows = [{"fuel": f, "grade": g, "count": n(v)}
                 for (f, g), v in sorted(fg_detail.items(), key=lambda kv: (-kv[1], kv[0]))]

    # 3+4. by manufacture year (pre-YEAR_FROM grouped)
    yrs = df.dropna(subset=["year"]).copy()
    yrs["ylab"] = yrs["year"].astype(int).map(
        lambda y: f"לפני {YEAR_FROM}" if y < YEAR_FROM else str(y))
    year_keys = ([f"לפני {YEAR_FROM}"] if (yrs["year"] < YEAR_FROM).any() else []) + \
        [str(y) for y in range(YEAR_FROM, max_year + 1)]
    gy = pd.crosstab(yrs["ylab"], yrs["grade"]).reindex(index=year_keys, columns=order, fill_value=0)
    gy_tot = gy.sum(axis=1)
    grade_year = {"x": year_keys,
                  "series": [{"name": g, "data": [round(float(v) / t * 100, 1) if t else 0
                                                  for v, t in zip(gy[g], gy_tot)]}
                             for g in order],
                  "totals": [int(t) for t in gy_tot],
                  "colors": colors}
    yrs["cls"] = "אחר"
    yrs.loc[yrs["grade"] == POLLUTING, "cls"] = "מזהם מורשה"
    yrs.loc[yrs["unauth"], "cls"] = "לא מורשה פעילות"
    cls_order = ["לא מורשה פעילות", "מזהם מורשה", "אחר"]
    ay = pd.crosstab(yrs["ylab"], yrs["cls"]).reindex(index=year_keys, columns=cls_order,
                                                      fill_value=0)
    auth_year = {"x": year_keys,
                 "series": [{"name": c if c != "אחר" else "דרגות אחרות",
                             "data": [int(v) for v in ay[c]]} for c in cls_order],
                 "colors": ["#dc3545", "#f1a7ae", "#b7d2f7"]}
    last_unauth_year = int(yrs.loc[yrs["unauth"], "year"].max()) if n_unauth else None

    # 5. power bands (machines with a recorded power only)
    pw = df[df["kw"] > 0].copy()
    pw["band"] = pw["kw"].map(_band)
    band_keys = [band_label(lo, hi) for lo, hi in POWER_BANDS]
    bg = pd.crosstab(pw["band"], pw["grade"]).reindex(index=band_keys, columns=order,
                                                      fill_value=0)
    keep_grades = [g for g in order if bg[g].sum() > 0]
    band_rows = []
    for (lo, hi), b in zip(POWER_BANDS, band_keys):
        sub = pw[pw["band"] == b]
        pol = sub[sub["grade"] == POLLUTING]
        band_rows.append({"band": b, "lo": lo, "hi": hi, "n": len(sub), "pol": len(pol),
                          "pol_unauth": int(pol["unauth"].sum())})
    power = {"x": [f"{LRI}{b}{PDI}" for b in band_keys],   # isolates: keep "\u20660–19\u2069" LTR on canvas
             "series": [{"name": g, "data": [int(v) for v in bg[g]]} for g in keep_grades],
             "colors": [colors[order.index(g)] for g in keep_grades],
             "rate": [round(r["pol_unauth"] / r["pol"] * 100, 1) if r["pol"] else None
                      for r in band_rows]}
    no_kw = int((~(df["kw"] > 0)).sum())

    # 6. types, 7. makers — 100% grade mix
    types = _sorted_counts(df["type"])
    type_keys = list(types.index[:TOP_TYPES])
    t_ct, t_tot, t_series, t_un = _mix(df, "type", type_keys, order)
    makers = _sorted_counts(df["maker"])
    maker_keys = list(makers.index[:TOP_MAKERS])
    m_ct, m_tot, m_series, m_un = _mix(df, "maker", maker_keys, order)
    type_stats = df.groupby("type").agg(n=("unauth", "size"), un=("unauth", "mean"))

    # 8. age by authorisation
    ages = (max_year - df["year"]).where(df["year"].between(1900, max_year))
    age_rows = []
    for lo, hi in AGE_BUCKETS:
        m = ages >= lo
        if hi is not None:
            m &= ages <= hi
        age_rows.append({"bucket": band_label(lo, hi),
                         "auth": int((m & ~df["unauth"]).sum()),
                         "unauth": int((m & df["unauth"]).sum())})

    rules = [
        ("polluting", insight_polluting(grades, total, n_unauth)),
        ("unauth", insight_unauth(df, n_unauth)),
        ("power", insight_power(band_rows)),
        ("last_polluting", insight_last_polluting(df, max_year)),
        ("age", insight_age(df, max_year)),
        ("type", insight_type(type_stats)),
        ("maker", insight_maker(df, makers)),
        ("filter", insight_filter(df, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    pol_share = n_pol / total * 100
    un_share = n_unauth / total * 100
    low_share = low / total * 100
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "polluting": {"value": round(pol_share, 1), "display": f"{pol_share:.1f}%",
                      "tone": "danger" if pol_share >= 25 else ("warn" if pol_share >= 10 else "ok")},
        "unauth": {"value": n_unauth, "display": n(n_unauth),
                   "tone": "danger" if un_share >= 10 else ("warn" if n_unauth else "ok")},
        "low": {"value": round(low_share, 1), "display": f"{low_share:.1f}%",
                "tone": "ok" if low_share >= 50 else "info"},
    }

    mix_caption = "התפלגות דרגות הזיהום (באחוזים) ושיעור הכלים שאינם מורשים לפעול"
    labels = {
        "lede": (f"דרגת זיהום האוויר של {n(total)} כלי צמ״ה (ציוד מכני הנדסי) הפעילים בישראל, "
                 f"כפי שקבע המשרד להגנת הסביבה לפי סוג ההנעה, שנת הייצור והספק המנוע. "
                 f"{pct(pol_share)} מהכלים מדורגים \"{POLLUTING}\", ו-{n(n_unauth)} כלים "
                 f"({pct(un_share)}) אינם מורשים לפעול. שנת הייצור האחרונה במאגר: {max_year}."),
        "pol_kpi": f"מדורגים \"{POLLUTING}\" ({n(n_pol)} כלים)",
        "unauth_kpi": f"כלים שאינם מורשים לפעול ({un_share:.1f}%)",
        "low_kpi": f"בדרגת \"{REDUCED}\", \"נקי\" או \"{ELECTRIC_GRADE}\"",
        "grades_note": (f"מספר הכלים בכל דרגת זיהום. {n(n_dpf)} כלים בלבד רשומים עם מסנן "
                        f"חלקיקים מותקן.{unrankable_note(df)}"),
        "grades_aria": f"תרשים עמודות: {n(total)} כלים לפי דרגת זיהום אוויר.",
        "grades_caption": "מספר כלים, שיעור ומספר הכלים שאינם מורשים לפעול, לפי דרגת זיהום.",
        "flow_aria": "תרשים זרימה: כלים לפי סוג הנעה, דרגת זיהום והרשאת פעילות.",
        "flow_caption": "מספר כלים לפי סוג הנעה ודרגת זיהום.",
        "gy_note": (f"שיעור כל דרגה מבין הכלים הפעילים שיוצרו בכל שנה, מ-{YEAR_FROM} "
                    f"(כלים מוקדמים יותר מקובצים יחד). המאגר כולל רק כלים פעילים, ולכן שנים "
                    f"מוקדמות מיוצגות חסר; השנה {max_year} עשויה להיות חלקית."),
        "gy_aria": f"תרשים שטח מוערם: הרכב דרגות הזיהום לפי שנת ייצור, {YEAR_FROM} עד {max_year}.",
        "ay_note": ((f"מספר הכלים לפי שנת ייצור והרשאת פעילות. הכלי הצעיר ביותר שאינו מורשה "
                     f"לפעול יוצר ב-{last_unauth_year}.") if last_unauth_year else
                    "מספר הכלים לפי שנת ייצור והרשאת פעילות."),
        "ay_aria": "תרשים עמודות מוערמות: כלים לפי שנת ייצור — לא מורשים, מזהמים מורשים ואחרים.",
        "power_note": (f"כלים לפי טווח הספק המנוע ודרגת הזיהום, והקו — שיעור הכלים שאינם מורשים "
                       f"לפעול מבין הכלים המזהמים בכל טווח. {n(no_kw)} כלים ללא הספק רשום "
                       f"(בעיקר חשמליים) אינם נכללים."),
        "power_aria": "תרשים עמודות מוערמות וקו: כלים לפי טווח הספק בקילוואט ודרגת זיהום.",
        "power_caption": "מספר כלים, מספר מזהמים ושיעור הלא-מורשים מביניהם, לפי טווח הספק.",
        "types_note": f"הרכב דרגות הזיהום ב-{TOP_TYPES} סוגי הכלים הנפוצים.",
        "types_aria": f"תרשים עמודות מוערמות: הרכב דרגות הזיהום ב-{TOP_TYPES} סוגי הצמ״ה הנפוצים.",
        "types_caption": f"{mix_caption}, לפי סוג כלי.",
        "makers_note": f"הרכב דרגות הזיהום אצל {TOP_MAKERS} היצרנים הנפוצים.",
        "makers_aria": f"תרשים עמודות מוערמות: הרכב דרגות הזיהום אצל {TOP_MAKERS} היצרנים הנפוצים.",
        "makers_caption": f"{mix_caption}, לפי יצרן.",
        "age_note": f"מספר הכלים לפי גיל (שנים מאז שנת הייצור, ביחס ל-{max_year}) והרשאת פעילות.",
        "age_aria": "תרשים עמודות: כלים מורשים ושאינם מורשים לפעול לפי קבוצת גיל.",
        "age_caption": "מספר כלים מורשים ושאינם מורשים לפעול לפי קבוצת גיל.",
    }

    def mix_table(keys, ct, tot, un):
        return [{"name": k, "count": n(tot[k]),
                 "pol": pct_plain(ct.loc[k, POLLUTING] / tot[k] * 100) if POLLUTING in ct.columns and tot[k] else "0.0%",
                 "low": pct_plain(ct.loc[k, [g for g in (REDUCED, 'נקי', ELECTRIC_GRADE) if g in ct.columns]].sum() / tot[k] * 100) if tot[k] else "0.0%",
                 "un": pct_plain(un[k] * 100)} for k in keys]

    tables = {
        "grades": [{"name": r["name"], "count": n(r["count"]), "share": pct_plain(r["count"] / total * 100),
                    "unauth": n(r["unauth"])} for r in grade_rows],
        "flow": flow_rows,
        "power": [{"band": r["band"], "n": n(r["n"]), "pol": n(r["pol"]),
                   "rate": pct_plain(r["pol_unauth"] / r["pol"] * 100) if r["pol"] else "—"}
                  for r in band_rows],
        "types": mix_table(type_keys, t_ct, t_tot, t_un),
        "makers": mix_table(maker_keys, m_ct, m_tot, m_un),
        "age": [{"bucket": r["bucket"], "auth": n(r["auth"]), "unauth": n(r["unauth"])}
                for r in age_rows],
    }

    charts = {
        "grades": {"names": order, "values": [r["count"] for r in grade_rows], "colors": colors},
        "flow": {"nodes": nodes, "links": links, "total": total},
        "grade_year": grade_year,
        "auth_year": auth_year,
        "power": power,
        "types": {"names": type_keys, "series": t_series, "colors": colors},
        "makers": {"names": maker_keys, "series": m_series, "colors": colors},
        "age": {"names": [f"{LRI}{r['bucket']}{PDI}" for r in age_rows],
                "auth": [r["auth"] for r in age_rows],
                "unauth": [r["unauth"] for r in age_rows]},
    }

    min_year = int(df["year"].min())
    return {
        "agent_data": {
            "summary_he": (f"דרגת זיהום האוויר של {n(total)} כלי צמ״ה פעילים בישראל: "
                           f"{pct(pol_share)} מדורגים \"{POLLUTING}\" ו-{n(n_unauth)} אינם "
                           f"מורשים לפעול — לפי סוג, יצרן, שנת ייצור, הספק והנעה."),
            "dataset_kind": "registry",
            "related_ids": ["0219b34f-43c7-435b-bdfe-e65e944cde50",
                            "5fc5c912-4fa5-4474-93c1-326e505e22cf",
                            "04931a88-336c-4d95-8a13-9dc631c3e2d1"],
            "suggested_tags": ["זיהום אוויר", "ציוד מכני הנדסי", "צמ״ה", "פליטות",
                               "מסנן חלקיקים", "הגנת הסביבה"],
            "temporal_coverage": f"{min_year}/{max_year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
