"""Multilingual glossary of health-unit names (Ministry of Health).

One row per unit name: the Hebrew name, its unit type (code + name, plus a
second free type column "סוג"), and its Arabic, English and Russian
renderings. The page profiles the vocabulary (types, opening words,
children's units, names reused across types, lettered series, translation
length and the words each language uses for each type) and audits its
consistency (duplicates, disagreeing type columns, wrong-script cells).
"""
import re

import pandas as pd
from govlib import fmt, frame

NO_TYPE = "ללא סוג"
EMPTY_SOG = "ריק"
LANGS = [("unit_name", "עברית"), ("arb", "ערבית"), ("eng", "אנגלית"), ("rus", "רוסית")]

HEB = re.compile(r"[א-ת]")
ARB = re.compile(r"[؀-ۿ]")
CYR = re.compile(r"[Ѐ-ӿ]")
LETTER = re.compile(r"[^\W\d_]")
KID = re.compile(r"^[והל]*ילד(?:ים)?$")
LETTERED = re.compile(r"^(.*\S)\s+([א-ת])['׳]?$")
TOKEN = re.compile(r"[^\s,()\-/\"'.:;׳״]+")

STOP = {
    "eng": {"and", "of", "the", "for", "with", "in", "to"},
    "arb": {"عند", "في", "من", "مع", "على", "إلى"},
    "rus": {"для", "при", "под", "над", "без"},
}


def _type_order(df):
    """Type names by entry count desc (ties by name); no-type bucket last."""
    counts = frame.ranked(df["type"])
    named = [t for t in counts.index if t != NO_TYPE]
    return named + ([NO_TYPE] if NO_TYPE in counts.index else []), counts


def _family(names):
    """Opening word of each name; a construct-state form ending in ת is merged
    into its ה form when that form also opens a name (מרפאת -> מרפאה)."""
    first = names.str.split().str[0].fillna("")
    vocab = set(first)
    merge = {w: w[:-1] + "ה" for w in vocab if w.endswith("ת") and len(w) > 2 and (w[:-1] + "ה") in vocab}
    return first.map(lambda w: merge.get(w, w))


AR_MARKS = re.compile(r"[\u064b-\u0652\u0670\u0640]")
AR_PREFIXES = ("وال", "بال", "فال", "كال", "لل", "ال")
AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})
MIN_TERM_SHARE = 0.25


def _surface(tok, lang):
    """A token as displayed: for Arabic, without diacritics, tatweel and the
    definite article with its clitics (وال، بال، لل…)."""
    if lang != "arb":
        return tok
    t = AR_MARKS.sub("", tok)
    for pre in AR_PREFIXES:
        if t.startswith(pre) and len(t) - len(pre) >= 3:
            return t[len(pre):]
    return t


def _word_key(tok, lang):
    """Comparison key for a token: case-folded; for Arabic, diacritics and
    tatweel removed, the definite article with its clitics (وال، بال، لل…)
    stripped, and alef/ta-marbuta/ya forms folded."""
    if lang != "arb":
        return tok.lower()
    return _surface(tok, lang).translate(AR_FOLD)


def _top_word(series, lang):
    """Most common word (by number of entries containing it, after
    normalisation) in a column, shown in its most common spelling, and its
    share of the entries. None when the column is empty."""
    stop = STOP.get(lang, set())
    docs, spell = [], []
    for v in series:
        keys = set()
        for t in TOKEN.findall(v):
            k = _word_key(t, lang)
            if len(k) < 3 or k in stop:
                continue
            keys.add(k)
            spell.append((k, _surface(t, lang)))
        docs.append(keys)
    if not docs:
        return None
    cnt = pd.Series([t for d in docs for t in sorted(d)], dtype=object)
    if cnt.empty:
        return None
    r = frame.ranked(cnt)
    word = str(r.index[0])
    forms = frame.ranked(pd.Series([f for k, f in spell if k == word], dtype=object))
    return str(forms.index[0]), int(r.iloc[0]) / len(docs)


def _wrong_script(row):
    """True when a translation cell holds letters of another language's
    script (Hebrew in the Arabic column, Cyrillic in the English, ...).
    Latin acronyms such as PET-CT are accepted in every column."""
    a, e, r = row["arb"], row["eng"], row["rus"]
    if HEB.search(a) or CYR.search(a):
        return True
    if HEB.search(e) or CYR.search(e) or ARB.search(e):
        return True
    return bool(HEB.search(r) or ARB.search(r))


def _quartiles(lens):
    q = lens.quantile([0, 0.25, 0.5, 0.75, 1.0], interpolation="linear")
    return [round(float(v), 1) for v in q]


def compute(frames):
    raw = frames["main"]
    linebreak_rows = int(
        raw[["unit_name", "arb", "eng", "rus"]].apply(lambda c: c.astype(str).str.contains(r"[\r\n]", regex=True)).any(axis=1).sum()
    )
    df = pd.DataFrame({c: frame.clean_series(raw[c]) for c in ["unit_name", "unit_type", "unit_type_name", "arb", "eng", "rus", "סוג"]})
    df = df[df["unit_name"] != ""].copy()
    if df.empty:
        raise ValueError("no unit names")
    df["type"] = df["unit_type_name"].where(df["unit_type_name"] != "", NO_TYPE)
    df["sog"] = df["סוג"].where(df["סוג"] != "", EMPTY_SOG)
    n = len(df)
    order, type_counts = _type_order(df)
    named_types = [t for t in order if t != NO_TYPE]

    # ---- by type
    by_type = {"labels": order, "values": [int(type_counts[t]) for t in order]}

    # ---- type code consistency: main code per type name
    main_code = {}
    for t in named_types:
        codes = frame.ranked(df.loc[(df["type"] == t) & (df["unit_type"] != ""), "unit_type"])
        main_code[t] = str(codes.index[0]) if len(codes) else ""
    code_mismatch = int(
        sum(1 for t, c in zip(df["type"], df["unit_type"]) if t != NO_TYPE and c and main_code.get(t) and c != main_code[t])
    )
    no_type = int((df["type"] == NO_TYPE).sum())

    # ---- agreement of the two type columns (heatmap)
    sog_counts = frame.ranked(df["sog"])
    # x follows the y order (type names) so agreeing cells sit on the diagonal;
    # סוג-only values follow by count, the empty bucket last.
    sog_vals = set(sog_counts.index)
    # every type, even one no סוג value names (an empty column), keeps (i, i).
    sog_order = [t for t in order if t != NO_TYPE]
    sog_order += [s for s in sog_counts.index if s not in sog_order and s != EMPTY_SOG]
    sog_order += [EMPTY_SOG] if EMPTY_SOG in sog_vals else []
    xt = pd.crosstab(df["type"], df["sog"])
    cells = []
    for yi, t in enumerate(order):
        for xi, s in enumerate(sog_order):
            v = int(xt.at[t, s]) if (t in xt.index and s in xt.columns) else 0
            if v:
                cells.append([xi, yi, v])
    both = df[(df["type"] != NO_TYPE) & (df["sog"] != EMPTY_SOG)]
    agree_n = int((both["type"] == both["sog"]).sum())
    agree_share = agree_n / len(both) if len(both) else None
    mism = both[both["type"] != both["sog"]]
    mism_pairs = frame.ranked(mism["type"] + "\u0001" + mism["sog"])
    top_mism = None
    if len(mism_pairs):
        a, b = mism_pairs.index[0].split("\u0001")
        top_mism = (a, b, int(mism_pairs.iloc[0]))
    sog_empty = int((df["sog"] == EMPTY_SOG).sum())

    # ---- opening-word families
    df["family"] = _family(df["unit_name"])
    name_fam = df.drop_duplicates("unit_name")
    fam = frame.ranked(name_fam["family"])
    fam_n = min(15, len(fam))
    families = {"labels": [str(k) for k in fam.index[:fam_n]], "values": [int(v) for v in fam.iloc[:fam_n]]}

    # ---- children's units per type
    df["kid"] = df["unit_name"].map(lambda s: any(KID.match(w) for w in s.split()))
    kids_total = int(df["kid"].sum())
    kids_by_type = []
    for t in order:
        sub = df[df["type"] == t]
        k = int(sub["kid"].sum())
        kids_by_type.append({"type": t, "kids": k, "other": int(len(sub) - k), "share": k / len(sub) if len(sub) else 0.0})
    kids = {
        "labels": [r["type"] for r in kids_by_type],
        "kids": [r["kids"] for r in kids_by_type],
        "other": [r["other"] for r in kids_by_type],
    }
    kid_lead = sorted(
        [r for r in kids_by_type if r["type"] != NO_TYPE and r["kids"] + r["other"] >= 20],
        key=lambda r: (-r["share"], -r["kids"], r["type"]),
    )

    # ---- names reused across types
    per_name = df[df["type"] != NO_TYPE].groupby("unit_name")["type"].nunique()
    names_total = int(df["unit_name"].nunique())
    dist = per_name.value_counts().sort_index()
    reuse = {"labels": [str(int(k)) for k in dist.index], "values": [int(v) for v in dist]}
    multi = int((per_name > 1).sum())
    max_types = int(per_name.max()) if len(per_name) else 0
    rows_per_name = df.groupby("unit_name").size()
    top_names = sorted(per_name[per_name > 1].index, key=lambda nm: (-int(per_name[nm]), -int(rows_per_name[nm]), nm))[:10]
    reuse_rows = []
    for nm in top_names:
        ts = sorted(set(df.loc[(df["unit_name"] == nm) & (df["type"] != NO_TYPE), "type"]), key=lambda t: (order.index(t), t))
        reuse_rows.append([nm, fmt.int_he(per_name[nm]), ", ".join(ts)])
    n_at_max = int((per_name == max_types).sum()) if max_types else 0

    # ---- lettered series (פנימית א', פנימית ב', ...)
    m = df["unit_name"].str.extract(LETTERED)
    lettered = m.dropna()
    if len(lettered):
        letters = lettered.groupby(0)[1].nunique()
        letters = letters[letters >= 2]
        stems = letters.sort_index().sort_values(ascending=False, kind="stable")
    else:
        stems = pd.Series(dtype=int)
    lettered_rows = int(lettered[0].isin(set(stems.index)).sum()) if len(stems) else 0
    series_n = min(12, len(stems))
    series = {"labels": [str(k) for k in stems.index[:series_n]], "values": [int(v) for v in stems.iloc[:series_n]]}

    # ---- translation lengths
    lengths = []
    for col, label in LANGS:
        ln = df.loc[df[col] != "", col].str.len()
        lengths.append({"lang": label, "q": _quartiles(ln) if len(ln) else [0, 0, 0, 0, 0]})
    heb_med = lengths[0]["q"][2]
    longest = max(lengths[1:], key=lambda r: (r["q"][2], r["lang"]))

    # ---- full translation coverage
    has = {c: df[c].map(lambda v: bool(LETTER.search(v))) for c in ["arb", "eng", "rus"]}
    full = int((has["arb"] & has["eng"] & has["rus"]).sum())
    full_share = full / n

    # ---- type words per language
    term_rows = []
    for t in named_types:
        sub = df[df["type"] == t]
        if len(sub) < 5:
            continue
        cells_ = [t, fmt.int_he(len(sub))]
        for col in ["eng", "arb", "rus"]:
            tw = _top_word(sub.loc[sub[col] != "", col], col)
            cells_.append(f"{tw[0]} ({fmt.pct(tw[1], 0)})" if tw and tw[1] >= MIN_TERM_SHARE else "אין מונח עקבי")
        term_rows.append(cells_)

    # ---- quality audit
    dup_groups = df.groupby(["unit_name", "type"])
    dup_sizes = dup_groups.size()
    dup_keys = dup_sizes[dup_sizes > 1].index
    dup_pairs = len(dup_keys)
    dup_diff = 0
    if dup_pairs:
        nun = dup_groups[["arb", "eng", "rus"]].nunique()
        dup_diff = int((nun.loc[dup_keys].max(axis=1) > 1).sum())
    exact_dups = int(df.duplicated(["unit_name", "unit_type", "unit_type_name", "arb", "eng", "rus", "סוג"]).sum())
    wrong = int(df.apply(_wrong_script, axis=1).sum())
    missing_tr = int(n - full)
    eng_coll = df[df["eng"] != ""].groupby("eng")["unit_name"].nunique()
    eng_coll_n = int((eng_coll > 1).sum())
    sog_disagree = len(mism)
    quality = [
        ["רשומות ללא שם סוג יחידה", fmt.int_he(no_type)],
        ["רשומות שהעמודה \"סוג\" בהן ריקה", fmt.int_he(sog_empty)],
        ["רשומות שבהן \"סוג\" שונה משם סוג היחידה", fmt.int_he(sog_disagree)],
        ["רשומות שקוד הסוג שלהן שונה מהקוד הרגיל לאותו סוג", fmt.int_he(code_mismatch)],
        ["צירופי שם וסוג שמופיעים יותר מפעם אחת", fmt.int_he(dup_pairs)],
        ["מתוכם עם תרגום שונה בין העותקים", fmt.int_he(dup_diff)],
        ["שורות כפולות זהות לחלוטין", fmt.int_he(exact_dups)],
        ["תרגומים לאנגלית המשותפים לשני שמות עבריים שונים או יותר", fmt.int_he(eng_coll_n)],
        ["רשומות עם תא תרגום שאינו בכתב השפה שלו", fmt.int_he(wrong)],
        ["רשומות עם ירידת שורה בתוך תא", fmt.int_he(linebreak_rows)],
        ["רשומות שבהן תרגום חסר או ללא אותיות (למשל פסיק בלבד)", fmt.int_he(missing_tr)],
    ]

    # ---- insights
    insights = []
    lead = named_types[0] if named_types else None
    if lead:
        ls = type_counts[lead] / n
        if ls >= 0.2:
            txt = f"הסוג הנפוץ במונחון הוא {lead}: {fmt.int_he(type_counts[lead])} רשומות, {fmt.pct(ls)} מכלל {fmt.int_he(n)} הרשומות."
            if len(named_types) > 1:
                second = named_types[1]
                txt += f" אחריו {second} עם {fmt.int_he(type_counts[second])} רשומות."
            insights.append({"id": "lead_type", "text_he": txt})
    if len(fam) and fam.iloc[0] / names_total >= 0.05:
        w, c = str(fam.index[0]), int(fam.iloc[0])
        insights.append({"id": "family", "text_he": f"המילה הפותחת הנפוצה ביותר בשמות היחידות היא \"{w}\": {fmt.int_he(c)} מתוך {fmt.int_he(names_total)} השמות העבריים השונים ({fmt.pct(c / names_total)}) מתחילים בה."})
    if multi and max_types >= 2:
        ex = top_names[0] if top_names else None
        txt = f"{fmt.int_he(multi)} מתוך {fmt.int_he(names_total)} השמות העבריים מופיעים ביותר מסוג יחידה אחד (למשל גם כמחלקה וגם כמרפאה), עם תרגום נפרד לכל סוג."
        if ex and n_at_max:
            txt += f" {fmt.int_he(n_at_max)} שמות מופיעים ב-{fmt.int_he(max_types)} סוגים, ביניהם \"{ex}\"."
        insights.append({"id": "reuse", "text_he": txt})
    if kids_total and kids_total / n >= 0.03:
        txt = f"{fmt.int_he(kids_total)} רשומות ({fmt.pct(kids_total / n)}) הן יחידות לילדים, לפי המילה \"ילדים\" או \"ילד\" בשם."
        if kid_lead and kid_lead[0]["share"] > 0:
            k = kid_lead[0]
            txt += f" שיעורן הגבוה ביותר בסוג {k['type']}: {fmt.pct(k['share'])} מהרשומות (מבין סוגים עם עשרים רשומות לפחות)."
        insights.append({"id": "kids", "text_he": txt})
    if agree_share is not None and sog_disagree:
        txt = f"העמודה \"סוג\" תואמת את שם סוג היחידה ב-{fmt.pct(agree_share)} מהרשומות שבהן שתיהן מלאות; ב-{fmt.int_he(sog_disagree)} רשומות הן סותרות"
        if top_mism and top_mism[2] >= 2:
            txt += f", הנפוץ הוא {top_mism[0]} שסומן \"{top_mism[1]}\" ({fmt.int_he(top_mism[2])} רשומות)"
        txt += f". ב-{fmt.int_he(sog_empty)} רשומות העמודה ריקה."
        insights.append({"id": "agree", "text_he": txt})
    if dup_pairs:
        txt = f"{fmt.int_he(dup_pairs)} צירופים של שם וסוג יחידה מופיעים יותר מפעם אחת"
        txt += f", וב-{fmt.int_he(dup_diff)} מהם התרגום שונה בין העותקים, כך שלאותה יחידה יש יותר מנוסח מוצע אחד." if dup_diff else ", כולם עם תרגום זהה."
        insights.append({"id": "dups", "text_he": txt})
    if heb_med and longest["q"][2] / heb_med >= 1.3:
        insights.append({
            "id": "length",
            "text_he": f"התרגומים ארוכים מהמקור: חציון האורך בעברית הוא {fmt.int_he(heb_med)} תווים, ובשפה הארוכה ביותר, {longest['lang']}, {fmt.int_he(longest['q'][2])} תווים. כדאי לתכנן שילוט רב-לשוני עם מקום לכך.",
        })
    if wrong:
        insights.append({"id": "script", "text_he": f"ב-{fmt.int_he(wrong)} רשומות תא תרגום כתוב בכתב של שפה אחרת (למשל עברית או רוסית בעמודת הערבית או האנגלית), ויש לבדוק אותן לפני שימוש."})
    if lettered_rows and len(stems):
        stem0 = str(stems.index[0])
        ex = df.loc[m[0] == stem0, ["unit_name"]].assign(letter=m.loc[m[0] == stem0, 1])
        ex = ex.sort_values(["letter", "unit_name"], kind="stable").drop_duplicates("letter")
        ex_names = list(ex["unit_name"])[:2]
        insights.append({
            "id": "series",
            "text_he": f"{fmt.int_he(lettered_rows)} רשומות שייכות ל-{fmt.int_he(len(stems))} סדרות של יחידות ממוספרות באותיות (כמו {' ו'.join('"' + x + '"' for x in ex_names)}); הסדרה הארוכה ביותר, \"{stem0}\", כוללת {fmt.int_he(stems.iloc[0])} אותיות שונות.",
        })

    # ---- labels
    kpis = {
        "entries": {"value": n, "display": fmt.int_he(n), "tone": "brand"},
        "names": {"value": names_total, "display": fmt.int_he(names_total), "tone": "brand"},
        "types": {"value": len(named_types), "display": fmt.int_he(len(named_types)), "tone": "brand"},
        "kids": {"value": kids_total, "display": fmt.int_he(kids_total), "tone": "info"},
        "full": {"value": round(full_share * 100, 1), "display": fmt.pct(full_share), "tone": "ok" if full_share >= 0.99 else "warn"},
        "agree": {
            "value": round((agree_share or 0) * 100, 1),
            "display": fmt.pct(agree_share) if agree_share is not None else "–",
            "tone": "ok" if (agree_share or 0) >= 0.97 else "warn",
        },
    }
    lead_txt = f"הנפוץ הוא {lead} ({fmt.int_he(type_counts[lead])} רשומות)" if lead else ""
    fam_lead = str(fam.index[0]) if len(fam) else ""
    labels = {
        "lede": (
            f"מונחון של משרד הבריאות המציע תרגום אחיד לשמות של יחידות בריאות (מחלקות אשפוז, מרפאות, מכונים, מעבדות ויחידות מינהל) "
            f"לערבית, לאנגלית ולרוסית, לשילוט ולמסמכים בבתי החולים ובקהילה. המונחון כולל {fmt.int_he(n)} רשומות של {fmt.int_he(names_total)} שמות עבריים שונים "
            f"ב-{fmt.int_he(len(named_types))} סוגי יחידות."
        ),
        "entries_kpi": "רשומות במונחון",
        "names_kpi": "שמות עבריים שונים",
        "types_kpi": "סוגי יחידות",
        "kids_kpi": "רשומות של יחידות לילדים",
        "full_kpi": "רשומות מתורגמות לשלוש השפות",
        "agree_kpi": "התאמה בין שתי עמודות הסוג",
        "type_lede": f"כל רשומה משויכת לסוג יחידה; {lead_txt}." + (f" {fmt.int_he(no_type)} רשומות אינן משויכות לסוג." if no_type else ""),
        "type_aria": f"גרף עמודות: מספר הרשומות לפי סוג יחידה. {lead_txt}.",
        "agree_lede": (
            "לצד שם סוג היחידה יש במאגר עמודה נוספת בשם \"סוג\". השורות והעמודות מסודרות באותו סדר, כך שהתאים על האלכסון (אותו שם בשורה ובעמודה) הם רשומות שבהן שתי העמודות מסכימות"
            + (f" ({fmt.pct(agree_share)} מהרשומות שבהן שתיהן מלאות)" if agree_share is not None else "")
            + f". ערכים שמופיעים רק בעמודה \"סוג\" באים אחרי סוגי היחידות, ועמודת \"{EMPTY_SOG}\" מרכזת רשומות שבהן העמודה ריקה. מלבד עמודה זו ושורת \"{NO_TYPE}\", כל תא מחוץ לאלכסון הוא סתירה."
        ),
        "agree_aria": "מפת חום: שם סוג היחידה מול העמודה סוג, מספר הרשומות בכל צירוף." + (f" התאמה של {fmt.pct(agree_share)}." if agree_share is not None else ""),
        "family_lede": f"המילה הראשונה בשם מסמנת לרוב את התחום הרפואי או את סוג המקום. \"{fam_lead}\" פותחת {fmt.int_he(fam.iloc[0]) if len(fam) else ''} שמות עבריים שונים (כל שם נספר פעם אחת, גם אם הוא מופיע בכמה סוגים). צורות סמיכות אוחדו עם צורת הנפרד (מרפאת עם מרפאה).",
        "family_aria": f"גרף עמודות: {fmt.int_he(fam_n)} המילים הפותחות הנפוצות בשמות היחידות. המובילה: {fam_lead}.",
        "kids_lede": f"{fmt.int_he(kids_total)} רשומות הן יחידות לילדים (המילה \"ילדים\" או \"ילד\" בשם). הגרף מראה את חלקן בכל סוג יחידה.",
        "kids_aria": f"גרף עמודות מוערמות: רשומות של יחידות לילדים ושל יחידות אחרות בכל סוג. סך הכול {fmt.int_he(kids_total)} רשומות לילדים.",
        "reuse_lede": f"שם עברי אחד יכול לשמש כמה סוגי יחידות, ולכל סוג תרגום משלו (למשל מחלקה מול מרפאה). {fmt.int_he(multi)} שמות מופיעים ביותר מסוג אחד.",
        "reuse_aria": f"גרף עמודות: מספר השמות העבריים לפי מספר סוגי היחידות שבהם הם מופיעים. {fmt.int_he(multi)} שמות ביותר מסוג אחד.",
        "reuse_table": "השמות המופיעים במספר הסוגים הגדול ביותר",
        "series_lede": f"{fmt.int_he(lettered_rows)} רשומות שייכות ל-{fmt.int_he(len(stems))} סדרות של יחידות ממוספרות באותיות (א', ב', ג'), לבתי חולים שבהם כמה מחלקות באותו תחום. הגרף מראה כמה אותיות שונות יש בכל סדרה (סדרה היא שם עם שתי אותיות שונות לפחות).",
        "series_aria": "גרף עמודות: הסדרות הממוספרות באותיות הארוכות ביותר, לפי מספר האותיות השונות." + (f" הארוכה: {stems.index[0]}." if len(stems) else ""),
        "length_lede": f"אורך השם בתווים בכל שפה: חציון של {fmt.int_he(heb_med)} תווים בעברית מול {fmt.int_he(longest['q'][2])} ב{longest['lang']}. הקופסה מסמנת את הרבעון התחתון והעליון, והקווים את הקצר והארוך ביותר.",
        "length_aria": f"תרשים קופסה: אורך השם בתווים בעברית, ערבית, אנגלית ורוסית. החציון הגבוה ביותר ב{longest['lang']}.",
        "terms_lede": f"לכל סוג יחידה: המילה הנפוצה ביותר בתרגומים שלו לכל שפה, ובאיזה שיעור מהרשומות של הסוג היא מופיעה. כשהשיעור גבוה, זה המונח שבו המונחון מתרגם את סוג היחידה עצמו (מחלקה, מרפאה, מכון). כשאף מילה לא מופיעה בלפחות {fmt.pct(MIN_TERM_SHARE, 0)} מהרשומות, כתוב \"אין מונח עקבי\": התרגומים בשפה זו לא חוזרים על מילה אחת, ולרוב נותנים רק את התחום. בערבית המילים נספרות בלי ניקוד ובלי ה\"ال\" המיודעת. סוגים עם פחות מחמש רשומות לא נכללו.",
        "quality_lede": "בדיקות עקביות שחושבו מתוך המאגר. רשומה שמופיעה כאן איננה בהכרח שגויה, אבל כדאי לבדוק אותה לפני העתקת התרגום לשילוט.",
    }

    summary = (
        f"מונחון משרד הבריאות לשמות יחידות בריאות בעברית, ערבית, אנגלית ורוסית: {fmt.int_he(n)} רשומות של {fmt.int_he(names_total)} שמות "
        f"ב-{fmt.int_he(len(named_types))} סוגי יחידות" + (f", בראשם {lead} עם {fmt.int_he(type_counts[lead])} רשומות." if lead else ".")
    )
    desc = (
        f"תרגום שמות מחלקות, מרפאות ומכונים בבתי חולים לערבית, אנגלית ורוסית: {fmt.int_he(names_total)} שמות ב-{fmt.int_he(len(named_types))} סוגי יחידות, עם חיפוש לפי שם."
    )

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "seo": {
                "title": "מילון שמות יחידות בריאות: ערבית, אנגלית ורוסית",
                "description": desc,
                "name": "מונחון רב-לשוני לשמות יחידות בריאות",
                "alternate_names": [
                    "מינוח רב לשוני של יחידות בריאות",
                    "תרגום שמות מחלקות בבית חולים",
                    "מילון מונחים רפואי עברית ערבית אנגלית רוסית",
                    "שמות מחלקות ומרפאות בערבית",
                ],
            },
        },
        "kpis": kpis,
        "charts": {
            "by_type": by_type,
            "agree": {"x": sog_order, "y": order, "cells": cells, "max": max([c[2] for c in cells] or [1])},
            "families": families,
            "kids": kids,
            "reuse": reuse,
            "series": series,
            "lengths": {"langs": [r["lang"] for r in lengths], "box": [r["q"] for r in lengths]},
        },
        "tables": {
            "by_type": [[t, fmt.int_he(v), fmt.pct(v / n)] for t, v in zip(by_type["labels"], by_type["values"])],
            "families": [[w, fmt.int_he(v)] for w, v in zip(families["labels"], families["values"])],
            "kids": [[r["type"], fmt.int_he(r["kids"]), fmt.int_he(r["kids"] + r["other"]), fmt.pct(r["share"])] for r in kids_by_type],
            "reuse": [[k, fmt.int_he(v)] for k, v in zip(reuse["labels"], reuse["values"])],
            "reuse_top": reuse_rows,
            "series": [[w, fmt.int_he(v)] for w, v in zip(series["labels"], series["values"])],
            "lengths": [[r["lang"]] + [fmt.int_he(v) for v in r["q"]] for r in lengths],
            "terms": term_rows,
            "quality": quality,
        },
        "flags": {"series": bool(series["labels"]), "reuse_top": bool(reuse_rows), "terms": bool(term_rows)},
        "insights": insights,
        "labels": labels,
    }
