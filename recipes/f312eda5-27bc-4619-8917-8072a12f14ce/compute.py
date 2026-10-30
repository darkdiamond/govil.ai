"""רשימת רבנים מוסמכים לעריכת חופות וקידושין: הרבנות הראשית לישראל.

One row per rabbi the Chief Rabbinate authorised to conduct weddings
(lastname, firstname, city, street). There is no licence date, district or
authorising-rabbinate column, so the honest story is geographic spread
(which localities have authorised rabbis and how concentrated they are),
rabbis listed abroad, and the name distribution that matters for lookup.

Privacy: rabbis are licensed office holders, so names may appear in
aggregates (common surnames / first names). The street column is a home
address: the page only counts how many rows carry one and never shows it.

City spelling is messy (תל אביב / תל-אביב, פתח תקוה / פתח תקווה, postal codes,
"ד.נ." prefixes). `city_key` folds the variants; the page says so. Places
written in Latin letters or naming a known foreign country/city are counted
as abroad (keyword list, disclosed as "שזוהו").

Growth: the file is a snapshot CKAN replaces in place. All category axes are
top-N + "אחר"; new localities and names flow through; nothing is hardcoded
except the spelling folds and the abroad keyword list.
"""
import re

import pandas as pd

TOP_CITIES = 15
TOP_NAMES = 15
ABROAD_LIST_MAX = 40
LEADER_SHARE = 0.10        # a "leading locality" holds at least this share
RANKS = [1, 3, 5, 10, 20, 50, 100, 200]
BUCKETS = [(1, 1, "רב אחד"), (2, 4, "2-4 רבנים"), (5, 9, "5-9 רבנים"),
           (10, 49, "10-49 רבנים"), (50, None, "50 רבנים ומעלה")]
LRI, PDI = "⁦", "⁩"

ABROAD_WORDS = [
    'ארה"ב', "ארצות הברית", "צרפת", "פריז", "לונדון", "אנגליה", "הולנד",
    "אמסטרדם", "שטרסבורג", "קנדה", "טורונטו", "מונטריאול", "ארגנטינה",
    "רוסיה", "מוסקבה", "רומא", "איטליה", "מילאנו", "מקסיקו", "אנטוורפן",
    "בלגיה", "ברזיל", "גרמניה", "שוויץ", "ציריך", "אוקראינה", "קייב",
    "אוסטריה", "אוסטרליה", "ספרד", "פנמה", "ניו יורק", "ברוקלין",
    "דרום אפריקה", "יוהנסבורג", "הונגריה", "פולין", "מונקו", "סרביה",
]
COHEN = {"כהן", "הכהן", 'כ"ץ', "כץ"}
LEVI = {"לוי", "הלוי"}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def pct_bare(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def clean(s):
    s = str(s).replace(" ", " ").replace("״", '"').replace("׳", "'")
    return " ".join(s.split())


def is_abroad(s):
    if re.search(r"[A-Za-z]", s):
        return True
    return any(w in s for w in ABROAD_WORDS)


def city_key(s):
    """Fold spelling variants of an Israeli locality to one key."""
    s = clean(s)
    s = re.sub(r"\d+", " ", s)
    s = re.sub(r"^\s*ד\.?\s*נ\.?\s*", "", s)          # leading "ד.נ." prefix
    s = re.sub(r"\s+ד\.?\s*נ\.?(\s.*)?$", "", s)       # trailing "ד.נ. <region>"
    s = re.sub(r"^(מושב|קבוץ|קיבוץ|ישוב|יישוב|מ\.א\.|מועצה אזורית)\s+", "", s)
    s = re.sub(r"[-–־/,]", " ", s)
    s = " ".join(s.split()).strip(" .,")
    s = s.replace("קריית", "קרית").replace("תקווה", "תקוה").replace("עלית", "עילית")
    s = s.replace("חבד", 'חב"ד')
    if s in ("תל אביב יפו", "תל אביב"):
        s = "תל אביב-יפו"
    return s


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = " ו-" if last[:1].isdigit() else " ו"
    return ", ".join(items[:-1]) + conj + last


def _prepare(df):
    out = pd.DataFrame({
        "last": df["lastname"].map(clean),
        "first": df["firstname"].map(clean),
        "city_raw": df["city"].map(clean),
        "has_street": df["street"].map(clean) != "",
    })
    out["abroad"] = out["city_raw"].map(lambda c: c != "" and is_abroad(c))
    out["key"] = [("" if a else city_key(c)) for c, a in zip(out["city_raw"], out["abroad"])]
    return out


def _top(counts, k, other_label):
    """counts: Series indexed by label. Sorted by count desc, label asc."""
    items = sorted(((str(i), int(v)) for i, v in counts.items()), key=lambda kv: (-kv[1], kv[0]))
    top = items[:k]
    rest = items[k:]
    names = [a for a, _ in top]
    vals = [b for _, b in top]
    if rest:
        names.append(other_label.format(n=n(len(rest))))
        vals.append(sum(b for _, b in rest))
    return items, names, vals


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)

    il = df[(~df["abroad"]) & (df["key"] != "")]
    abroad = df[df["abroad"]]
    no_city = int(((df["city_raw"] == "") | ((~df["abroad"]) & (df["key"] == ""))).sum())
    n_il = len(il)
    n_abroad = len(abroad)

    # ---- localities ------------------------------------------------------
    city_counts = il.groupby("key").size()
    n_loc = int(len(city_counts))
    city_items, c_names, c_vals = _top(city_counts, TOP_CITIES, "אחר ({n} יישובים)")
    leader, leader_n = city_items[0]
    second, second_n = city_items[1] if len(city_items) > 1 else ("", 0)
    leader_share = leader_n / n_il
    raw_variants = il.groupby("key")["city_raw"].nunique()
    multi_spelled = int((raw_variants > 1).sum())
    spell_example = ""
    if multi_spelled:
        top_var = sorted(((k, int(raw_variants[k]), int(city_counts[k])) for k in raw_variants.index
                          if raw_variants[k] > 1), key=lambda t: (-t[2], t[0]))[0][0]
        vs = il[il["key"] == top_var]["city_raw"].value_counts()
        vs = sorted(vs.items(), key=lambda kv: (-kv[1], kv[0]))
        spell_example = f"{vs[0][0]} ו{vs[1][0]}"
    chart_cities = {"names": c_names, "values": c_vals}
    tbl_cities = [{"name": a, "count": n(b), "share": pct(b / n_il)}
                  for a, b in zip(c_names, c_vals)]

    # ---- spread: localities by number of rabbis -------------------------
    sp_names, sp_loc, sp_rab = [], [], []
    for lo, hi, label in BUCKETS:
        m = (city_counts >= lo) & ((city_counts <= hi) if hi is not None else True)
        sp_names.append(label)
        sp_loc.append(int(m.sum()))
        sp_rab.append(int(city_counts[m].sum()))
    chart_spread = {"names": sp_names, "localities": sp_loc, "rabbis": sp_rab}
    tbl_spread = [{"name": a, "loc": n(b), "rab": n(c), "share": pct(c / n_il)}
                  for a, b, c in zip(sp_names, sp_loc, sp_rab)]
    singles = sp_loc[0]

    # ---- concentration: cumulative share by locality rank ---------------
    vals_sorted = [b for _, b in city_items]
    cum = []
    acc = 0
    for v in vals_sorted:
        acc += v
        cum.append(acc)
    ranks = [r for r in RANKS if r < n_loc] + [n_loc]
    conc_x = [n(r) for r in ranks]
    conc_y = [round(cum[r - 1] / n_il * 100, 1) for r in ranks]
    tbl_conc = [{"rank": n(r), "rabbis": n(cum[r - 1]), "share": pct(cum[r - 1] / n_il)}
                for r in ranks]
    top10 = min(10, n_loc)
    top10_share = cum[top10 - 1] / n_il
    half_rank = next(i + 1 for i, c in enumerate(cum) if c >= n_il / 2)

    # ---- surnames --------------------------------------------------------
    named_last = df[df["last"] != ""]
    sur_counts = named_last.groupby("last").size()
    sur_items, s_names, s_vals = _top(sur_counts, TOP_NAMES, "")
    s_names, s_vals = s_names[:TOP_NAMES], s_vals[:TOP_NAMES]
    chart_surnames = {"names": s_names, "values": s_vals}
    tbl_surnames = [{"name": a, "count": n(b)} for a, b in zip(s_names, s_vals)]
    n_surnames = int(len(sur_counts))
    n_cohen = int(named_last["last"].isin(COHEN).sum())
    n_levi = int(named_last["last"].isin(LEVI).sum())
    unique_sur = int((sur_counts == 1).sum())

    # ---- first names -----------------------------------------------------
    named_first = df[df["first"] != ""]
    fn_counts = named_first.groupby("first").size()
    fn_items, f_names, f_vals = _top(fn_counts, TOP_NAMES, "")
    f_names, f_vals = f_names[:TOP_NAMES], f_vals[:TOP_NAMES]
    chart_first = {"names": f_names, "values": f_vals}
    tbl_first = [{"name": a, "count": n(b)} for a, b in zip(f_names, f_vals)]
    n_double = int(named_first["first"].str.contains(" ").sum())

    # ---- abroad ------------------------------------------------------------
    ab_counts = abroad.groupby("city_raw").size()
    ab_items = sorted(((str(i), int(v)) for i, v in ab_counts.items()), key=lambda kv: (-kv[1], kv[0]))
    # Page text is Hebrew-only: list the places written in Hebrew, count the rest.
    ab_he = [(a, b) for a, b in ab_items if not re.search(r"[A-Za-z]", a)]
    ab_latin = sum(b for a, b in ab_items if re.search(r"[A-Za-z]", a))
    abroad_list = [{"name": a, "count": b} for a, b in ab_he[:ABROAD_LIST_MAX]]
    abroad_more = max(len(ab_he) - ABROAD_LIST_MAX, 0)

    # ---- data quality ------------------------------------------------------
    no_street = int((~df["has_street"]).sum())
    full_name = df[(df["last"] != "") & (df["first"] != "")]
    dup_names = full_name.groupby(["last", "first"]).size()
    n_dup_names = int((dup_names > 1).sum())
    n_dup_rows = int(dup_names[dup_names > 1].sum())
    dup_keys = set(dup_names[dup_names > 1].index)
    dup_frame = full_name[[k in dup_keys for k in zip(full_name["last"], full_name["first"])]]
    dup_cities = dup_frame.assign(c=dup_frame["key"].where(dup_frame["key"] != "", dup_frame["city_raw"])) \
        .groupby(["last", "first"])["c"].nunique()
    dup_multi_city = int((dup_cities > 1).sum())

    # ---- insights ----------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_leader():
        if leader_share < LEADER_SHARE:
            return None
        t = (f"{leader} מובילה עם {n(leader_n)} רבנים מוסמכים, {pct(leader_share)} מהרבנים "
             f"הרשומים ביישובים בישראל")
        if second_n:
            ratio = leader_n / second_n
            t += f", פי {ratio:.1f} מ{second} שבמקום השני ({n(second_n)})" if ratio >= 1.5 else \
                 f". אחריה {second} עם {n(second_n)}"
        return t + "."

    def ins_concentration():
        if n_loc < 20:
            return None
        return (f"הרשימה מרוכזת: עשרת היישובים המובילים מחזיקים {pct(top10_share)} מהרבנים, "
                f"ומחצית מכלל הרבנים רשומים ב-{n(half_rank)} יישובים בלבד מתוך {n(n_loc)}.")

    def ins_singles():
        if n_loc < 10 or singles / n_loc < 0.3:
            return None
        lead = "מנגד, ב" if n_loc >= 20 else "ב"
        return (f"{lead}-{n(singles)} יישובים ({pct(singles / n_loc)} מהיישובים ברשימה) רשום רב "
                f"מוסמך אחד בלבד.")

    def ins_abroad():
        if n_abroad == 0:
            return None
        return (f"{n(n_abroad)} רבנים ברשימה רשומים בכתובת מחוץ לישראל, ב-{n(len(ab_items))} "
                f"מקומות שזוהו" + (f" (למשל {join_he([a for a, _ in ab_he[:3]])})." if ab_he else "."))

    def ins_surnames():
        if not sur_items:
            return None
        top_s, top_n = sur_items[0]
        t = f"שם המשפחה הנפוץ ביותר ברשימה הוא {top_s} ({n(top_n)} רבנים)"
        if len(sur_items) > 1:
            t += f", ואחריו {sur_items[1][0]} ({n(sur_items[1][1])})"
        if n_cohen + n_levi >= 10:
            t += (f". {n(n_cohen + n_levi)} רבנים ({pct((n_cohen + n_levi) / len(named_last))}) נושאים "
                  f"את אחד משמות המשפחה כהן, הכהן, כ\"ץ, לוי או הלוי")
        return t + "."

    def ins_first():
        if len(fn_items) < 3:
            return None
        t = (f"השמות הפרטיים הנפוצים: {fn_items[0][0]} ({n(fn_items[0][1])}), "
             f"{fn_items[1][0]} ({n(fn_items[1][1])}) ו{fn_items[2][0]} ({n(fn_items[2][1])})")
        doubles = [a for a, _ in fn_items if " " in a][:2]
        if n_double >= 10 and len(doubles) == 2:
            t += f". ל-{n(n_double)} רבנים שם פרטי כפול, כמו {doubles[0]} או {doubles[1]}"
        return t + "."

    def ins_namesakes():
        if n_dup_names < 5:
            return None
        where = ", לרוב ביישובים שונים" if dup_multi_city / n_dup_names > 0.5 else ""
        return (f"{n(n_dup_names)} צירופים של שם פרטי ושם משפחה מופיעים יותר מפעם אחת "
                f"({n(n_dup_rows)} רשומות){where}. כשמחפשים רב לפי שם, כדאי "
                f"לוודא גם את היישוב.")

    def ins_quality():
        parts = []
        if no_city:
            parts.append(f"ב-{n(no_city)} רשומות לא צוין יישוב")
        if no_street:
            parts.append(f"ב-{n(no_street)} לא צוינה כתובת")
        if not parts and not multi_spelled:
            return None
        t = join_he(parts) if parts else ""
        if multi_spelled:
            sep = ". " if t else ""
            t += (f"{sep}שמות של {n(multi_spelled)} יישובים נכתבו ביותר מצורה אחת "
                  f"(למשל {spell_example}) ואוחדו בניתוח")
        return t + "."

    add("leader", ins_leader())
    add("concentration", ins_concentration())
    add("singles", ins_singles())
    add("abroad", ins_abroad())
    add("surnames", ins_surnames())
    add("first", ins_first())
    add("namesakes", ins_namesakes())
    add("quality", ins_quality())

    # ---- KPIs ----------------------------------------------------------------
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "loc": {"value": n_loc, "display": n(n_loc), "tone": "brand"},
        "leader": {"value": round(leader_share * 100, 1), "display": pct_bare(leader_share),
                   "tone": "info"},
        "abroad": {"value": n_abroad, "display": n(n_abroad), "tone": "info" if n_abroad else "brand"},
    }

    # ---- text ----------------------------------------------------------------
    abroad_clause = f" ועוד {n(n_abroad)} בחו\"ל" if n_abroad else ""
    summary = (f"איתור רב מוסמך לחופה וקידושין לפי שם או יישוב: {n(total)} רבנים שאישרה "
               f"הרבנות הראשית, ב-{n(n_loc)} יישובים{abroad_clause}.")
    if len(summary) > 155:
        summary = (f"איתור רב מוסמך לחופה וקידושין לפי שם או יישוב: {n(total)} רבנים שאישרה "
                   f"הרבנות הראשית.")

    lede = (f"הרשימה הרשמית של הרבנים שהרבנות הראשית לישראל הסמיכה לערוך חופה וקידושין "
            f"(רבנים מסדרי קידושין): {n(total)} רבנים, ב-{n(n_loc)} יישובים בישראל"
            f"{abroad_clause}. לכל רב מופיעים שם משפחה, שם פרטי, יישוב וכתובת. "
            f"הרשימה אינה כוללת תאריך הסמכה או את הרבנות המקומית המאשרת, ולכן הניתוח "
            f"שלהלן עוסק בפריסה הגאוגרפית ובשמות.")

    labels = {
        "lede": lede,
        "total_kpi": "רבנים מוסמכים ברשימה",
        "loc_kpi": "יישובים בישראל עם רב מוסמך",
        "leader_kpi": f"מהרבנים רשומים ב{leader}",
        "abroad_kpi": "רבנים בכתובת בחו\"ל",
        "cities_note": (f"מספר הרבנים המוסמכים לפי יישוב, {n(TOP_CITIES)} היישובים המובילים "
                        f"והשאר מקובצים תחת \"אחר\". שמות יישוב שנכתבו בכמה צורות אוחדו; "
                        f"{n(no_city)} רשומות ללא יישוב ו-{n(n_abroad)} בחו\"ל אינן בגרף."),
        "cities_aria": (f"גרף עמודות: רבנים מוסמכים לפי יישוב. {leader} מובילה עם "
                        f"{n(leader_n)} רבנים."),
        "spread_note": (f"כמה יישובים יש בכל קבוצת גודל, וכמה רבנים בסך הכול בכל קבוצה. "
                        f"{n(singles)} יישובים עם רב אחד בלבד."),
        "spread_aria": (f"גרף עמודות: יישובים לפי מספר הרבנים המוסמכים בהם. "
                        f"{n(singles)} יישובים עם רב אחד."),
        "conc_note": (f"איזה חלק מהרבנים רשום ב-N היישובים הגדולים. עשרת היישובים המובילים "
                      f"מחזיקים {pct(top10_share)}, ומחצית הרבנים נמצאים ב-{n(half_rank)} יישובים."),
        "conc_aria": (f"גרף קו: שיעור מצטבר של רבנים לפי דירוג היישוב. עשרת היישובים המובילים "
                      f"מחזיקים {pct(top10_share)} מהרבנים."),
        "surnames_note": (f"{n(TOP_NAMES)} שמות המשפחה הנפוצים מתוך {n(n_surnames)} שמות שונים; "
                          f"{n(unique_sur)} שמות משפחה מופיעים פעם אחת בלבד."),
        "surnames_aria": (f"גרף עמודות: שמות המשפחה הנפוצים בין הרבנים המוסמכים. "
                          f"{sur_items[0][0]} מוביל עם {n(sur_items[0][1])}." if sur_items else
                          "גרף עמודות: שמות המשפחה הנפוצים בין הרבנים המוסמכים."),
        "first_note": (f"{n(TOP_NAMES)} השמות הפרטיים הנפוצים מתוך {n(len(fn_counts))} שמות שונים."),
        "first_aria": (f"גרף עמודות: השמות הפרטיים הנפוצים בין הרבנים המוסמכים. "
                       f"{fn_items[0][0]} מוביל עם {n(fn_items[0][1])}." if fn_items else
                       "גרף עמודות: השמות הפרטיים הנפוצים בין הרבנים המוסמכים."),
        "abroad_note": (f"{n(n_abroad)} רבנים ברשימה רשומים בכתובת מחוץ לישראל. המקומות זוהו לפי "
                        f"כתב לטיני או שם של מדינה או עיר בחו\"ל, כפי שנכתבו ברשימה."),
        "abroad_more": f"ועוד {n(abroad_more)} מקומות" if abroad_more else "",
        "abroad_latin": (f"ועוד {n(ab_latin)} רבנים שמקומם נכתב באותיות לטיניות." if ab_latin else ""),
    }

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["רבנות", "חופה וקידושין", "נישואין", "רבנים", "חתונה"],
        "related_ids": ["b72acc9a-6512-4849-9529-3ce73370bff2",
                        "6a8f3548-f991-4f8b-ab52-80240324ab4d"],
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "cities": chart_cities,
            "spread": chart_spread,
            "conc": {"x": conc_x, "y": conc_y},
            "surnames": chart_surnames,
            "first": chart_first,
        },
        "tables": {
            "cities": tbl_cities,
            "spread": tbl_spread,
            "conc": tbl_conc,
            "surnames": tbl_surnames,
            "first": tbl_first,
        },
        "abroad": abroad_list,
        "flags": {"abroad": n_abroad > 0, "abroad_list": bool(abroad_list), "surnames": bool(sur_items), "first": bool(fn_items)},
        "insights": insights,
        "labels": labels,
    }
