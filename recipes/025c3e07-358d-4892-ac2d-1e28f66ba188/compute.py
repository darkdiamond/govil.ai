"""מנהל הטובין — the trademark office's goods & services term list (Nice).

One row = one WORDING of a term in one language. A term ("מספר מונח") is a
concept that carries one or more Hebrew and/or English wordings, a Nice class
(1–34 goods, 35–45 services), a source (the international GMS list or the
Israeli trademarks department) and, per wording, an acceptability flag
(קביל / לא קביל) and an appellation-of-origin flag.

Units used on the page: "מונחים" = distinct term numbers; "נוסחים" = rows.
Acceptability is per wording (a term can hold both acceptable and
non-acceptable wordings), so rejection rates are computed over wordings.
No people appear in this data.
"""
import pandas as pd

GOODS_MAX = 34                     # Nice classes 1–34 are goods, 35–45 services
TOP_SRC = 15                       # classes in the source-mix chart
TOP_REJ = 12                       # classes in the rejection chart
TOP_LANG = 12                      # classes in the single-language chart
TOP_WORDS = 15                     # leading Hebrew words
LATEST_N = 10                      # newest term numbers table
APPELL_MAX = 20                    # appellation-of-origin table cap
MIN_CLASS_ROWS = 500               # min wordings for a class to lead a rate rule
VARIANT_BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 9), (10, None)]
LRI, PDI = "⁦", "⁩"

SRC_INTL = "GMS"
SRC_IL = "מחלקת סימני מסחר"
HE, EN = "עברית", "אנגלית"
OK, NOT_OK = "קביל", "לא קביל"

BOX_SRC = {"GMS": "GMS", "מחלקת סימני מסחר": "המחלקה"}

SRC_KIND = {
    "intl": "מקור בינלאומי (GMS) בלבד",
    "both": "GMS ונוסח של המחלקה",
    "il": "מחלקת סימני מסחר בלבד",
}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def pct_bare(v, digits=1):
    return f"{v:.{digits}f}%"


def _prepare(df):
    cls_raw = df["סיווג ניצה עברית"].str.strip()
    num = pd.to_numeric(cls_raw.str.extract(r"^(\d+)")[0], errors="coerce")
    out = pd.DataFrame({
        "term": df["מספר מונח"].str.strip(),
        "tnum": pd.to_numeric(df["מספר מונח"].str.strip(), errors="coerce"),
        "text": df["תיאור"].str.strip(),
        "src": df["מקור המונח"].str.strip(),
        "lang": df["שפה"].str.strip(),
        "cls": num,
        "cls_name": cls_raw.str.replace(r"^\d+\s*", "", regex=True),
        "ok": df["קבילות המונח"].str.strip(),
        "appell": df["האם כינוי מקור"].str.strip() == "כן",
    })
    out = out[(out["term"] != "") & out["cls"].notna()].copy()
    out["cls"] = out["cls"].astype(int)
    out["rej"] = out["ok"] == NOT_OK
    out["words"] = out["text"].str.split().str.len().fillna(0).astype(int)
    return out


def cls_label(c, names):
    return f"{c} {names.get(c, '')}".strip()


def _class_names(df):
    # most frequent Hebrew name per class number (stable tie-break by name)
    cnt = df.groupby(["cls", "cls_name"]).size().reset_index(name="k")
    cnt = cnt.sort_values(["cls", "k", "cls_name"], ascending=[True, False, True])
    return {int(r.cls): r.cls_name for r in cnt.drop_duplicates("cls").itertuples()}


def _terms(df):
    """One row per term: sources, languages, wordings, main class."""
    g = df.groupby("term")
    srcs = g["src"].agg(lambda s: frozenset(s))
    langs = g["lang"].agg(lambda s: frozenset(s))
    main_cls = (df.groupby(["term", "cls"]).size().reset_index(name="k")
                  .sort_values(["term", "k", "cls"], ascending=[True, False, True])
                  .drop_duplicates("term").set_index("term")["cls"])
    t = pd.DataFrame({
        "tnum": g["tnum"].first(),
        "rows": g.size(),
        "ncls": g["cls"].nunique(),
        "cls": main_cls,
        "he": langs.map(lambda s: HE in s),
        "en": langs.map(lambda s: EN in s),
        "appell": g["appell"].any(),
        "rej_any": g["rej"].any(),
        "rej_all": g["rej"].all(),
    })
    t["kind"] = srcs.map(lambda s: "both" if (SRC_INTL in s and SRC_IL in s)
                         else ("intl" if SRC_INTL in s else "il"))
    return t


def _top(series, k):
    s = series.sort_index().sort_values(ascending=False, kind="stable")
    return s.head(k), s.iloc[k:]


# ---------------------------------------------------------------- insights

def insight_top_class(per_cls, names, total_terms):
    s = per_cls.sort_index().sort_values(ascending=False, kind="stable")
    if len(s) < 3 or total_terms == 0:
        return None
    c0, v0 = int(s.index[0]), int(s.iloc[0])
    if v0 / total_terms < 0.05:
        return None
    top3 = [cls_label(int(c), names) for c in s.index[1:3]]
    share3 = s.iloc[:3].sum() / total_terms * 100
    return (f"הסוג העשיר ביותר במונחים הוא סוג {cls_label(c0, names)} — {n(v0)} מונחים "
            f"({pct(v0 / total_terms * 100)}). יחד עם סוגים {top3[0]} ו-{top3[1]} "
            f"שלושת הסוגים מרכזים {pct(share3)} מכלל המונחים.")


def insight_goods_services(t):
    goods = t[t["cls"] <= GOODS_MAX]
    serv = t[t["cls"] > GOODS_MAX]
    if goods.empty or serv.empty:
        return None
    ng, ns = goods["cls"].nunique(), serv["cls"].nunique()
    ag, as_ = len(goods) / ng, len(serv) / ns
    share = len(goods) / len(t) * 100
    if abs(ag - as_) / max(ag, as_) < 0.1:
        cmp = "בממוצע מספר מונחים דומה לכל סוג"
    elif as_ > ag:
        cmp = f"אך סוג שירותים ממוצע עשיר יותר: {n(as_)} מונחים לסוג לעומת {n(ag)} בסוג טובין"
    else:
        cmp = f"וגם סוג טובין ממוצע עשיר יותר: {n(ag)} מונחים לסוג לעומת {n(as_)} בסוג שירותים"
    return (f"{n(len(goods))} מונחים ({pct(share)}) מתארים טובין ב-{ng} סוגים, ו-{n(len(serv))} "
            f"מתארים שירותים ב-{ns} סוגים — {cmp}.")


def insight_reject_source(df):
    by = df.groupby("src")["rej"].agg(["mean", "size"])
    if SRC_INTL not in by.index or SRC_IL not in by.index:
        return None
    if by.loc[SRC_INTL, "size"] < 1000 or by.loc[SRC_IL, "size"] < 1000:
        return None
    ri, rl = by.loc[SRC_INTL, "mean"] * 100, by.loc[SRC_IL, "mean"] * 100
    overall = df["rej"].mean() * 100
    il_share = (df.loc[df["src"] == SRC_IL, "rej"].sum() / max(int(df["rej"].sum()), 1)) * 100
    head = (f"{n(df['rej'].sum())} נוסחים ({pct(overall)}) מסומנים כלא קבילים. ")
    if ri > 0 and rl / ri >= 2:
        return head + (f"בנוסחים של מחלקת סימני מסחר השיעור הוא {pct(rl)} — פי {rl / ri:.1f} "
                       f"מאשר במקור הבינלאומי ({pct(ri)}), ו-{pct(il_share)} מכלל הנוסחים הלא קבילים "
                       f"הם נוסחים של המחלקה.")
    if rl > 0 and ri / rl >= 2:
        return head + (f"במקור הבינלאומי השיעור הוא {pct(ri)} — פי {ri / rl:.1f} מאשר "
                       f"בנוסחים של מחלקת סימני מסחר ({pct(rl)}).")
    return head + f"השיעור דומה בשני המקורות ({pct(ri)} ו-{pct(rl)})."


def insight_reject_class(df, names):
    by = df.groupby("cls")["rej"].agg(["mean", "size", "sum"])
    by = by[by["size"] >= MIN_CLASS_ROWS]
    if by.empty:
        return None
    by = by.sort_index().sort_values("mean", ascending=False, kind="stable")
    c, r = int(by.index[0]), by.iloc[0]
    overall = df["rej"].mean()
    if overall == 0 or r["mean"] < 2 * overall:
        return None
    return (f"סוג {cls_label(c, names)} בולט בשיעור הנוסחים הלא קבילים: {pct(r['mean'] * 100)} "
            f"({n(r['sum'])} נוסחים), פי {r['mean'] / overall:.1f} מהממוצע במאגר "
            f"(בסוגים עם {n(MIN_CLASS_ROWS)} נוסחים לפחות).")


def insight_bilingual(t):
    both = int((t["he"] & t["en"]).sum())
    en_only = int((t["en"] & ~t["he"]).sum())
    he_only = int((t["he"] & ~t["en"]).sum())
    if len(t) == 0:
        return None
    s = (f"{pct(both / len(t) * 100)} מהמונחים מנוסחים גם בעברית וגם באנגלית. "
         f"{n(en_only)} מונחים קיימים באנגלית בלבד ו-{n(he_only)} בעברית בלבד")
    if en_only >= 2 * max(he_only, 1):
        s += " — פער התרגום הוא בעיקר לעברית."
    elif he_only >= 2 * max(en_only, 1):
        s += " — פער התרגום הוא בעיקר לאנגלית."
    else:
        s += "."
    return s


def insight_local(t, names, intl_max):
    il = t[t["kind"] == "il"]
    if il.empty or len(t) == 0:
        return None
    lead = il["cls"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    c, v = int(lead.index[0]), int(lead.iloc[0])
    both = int((t["kind"] == "both").sum())
    s = (f"{n(len(il))} מונחים ({pct(len(il) / len(t) * 100)}) הוגדרו על ידי מחלקת סימני מסחר "
         f"בלבד, ולעוד {n(both)} מונחים בינלאומיים הוסיפה המחלקה נוסח משלה. "
         f"הכי הרבה מונחים מקומיים יש בסוג {cls_label(c, names)} ({n(v)}).")
    return s


def insight_appellation(t, df, names):
    a = t[t["appell"]]
    if a.empty:
        return None
    rej = int(a["rej_all"].sum())
    classes = sorted(a["cls"].unique())
    where = (f"כולם בסוג {cls_label(int(classes[0]), names)}" if len(classes) == 1
             else f"ב-{len(classes)} סוגים")
    s = f"{n(len(a))} מונחים מסומנים ככינוי מקור (שם גאוגרפי מוגן של מוצר), {where}"
    if rej == len(a):
        s += " — וכולם לא קבילים כמונח כללי."
    elif rej:
        s += f"; {n(rej)} מהם מסומנים כלא קבילים בכל נוסחיהם."
    else:
        s += "."
    return s


def insight_variants(t):
    if len(t) == 0:
        return None
    many = int((t["rows"] >= 3).sum())
    if many / len(t) < 0.05:
        return None
    return (f"למונח יש בממוצע {t['rows'].mean():.1f} נוסחים; {n(many)} מונחים "
            f"({pct(many / len(t) * 100)}) מחזיקים שלושה נוסחים ומעלה — ניסוחים חלופיים "
            f"לאותה סחורה או שירות.")


def insight_lead_word(words, total_he):
    if words.empty or total_he == 0:
        return None
    serv = int(sum(v for w, v in words.items() if w.startswith("שירות")))
    if serv / total_he < 0.05:
        return None
    return (f"{pct(serv / total_he * 100)} מהנוסחים בעברית ({n(serv)}) נפתחים במילה "
            f"\"שירות\" או \"שירותי\"/\"שירותים\" — המבנה המקובל לניסוח שירות בבקשה.")


def insight_multi_class(t):
    k = int((t["ncls"] > 1).sum())
    if k == 0:
        return None
    return (f"{n(k)} מונחים משויכים ביותר מסוג ניצה אחד בנוסחים השונים שלהם — "
            f"בדף הם נספרים בכל סוג שבו הם מופיעים.")


# ---------------------------------------------------------------- compute

def _box(vals):
    s = pd.Series(vals, dtype=float)
    q = s.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).tolist()
    return [round(float(v), 1) for v in q]


def compute(frames):
    df = _prepare(frames["terms"])
    names = _class_names(df)
    t = _terms(df)
    total_terms, total_rows = len(t), len(df)
    classes = sorted(names)

    # distinct terms per class (a term listed under 2 classes counts in both)
    pairs = df.drop_duplicates(["term", "cls"])
    per_cls = pairs.groupby("cls").size()
    rows_cls = df.groupby("cls").size()
    rej_cls = df.groupby("cls")["rej"].sum()

    # ---- treemap: goods / services -> class
    def node(c):
        return {"name": cls_label(c, names), "value": int(per_cls.get(c, 0))}
    goods = [node(c) for c in classes if c <= GOODS_MAX]
    serv = [node(c) for c in classes if c > GOODS_MAX]
    treemap = [x for x in [
        {"name": "טובין", "children": goods} if goods else None,
        {"name": "שירותים", "children": serv} if serv else None,
    ] if x]

    # term-level languages per class (pairs)
    pt = pairs[["term", "cls"]].merge(t[["he", "en", "kind"]], left_on="term", right_index=True)
    class_table = []
    for c in classes:
        sub = pt[pt["cls"] == c]
        bi = (sub["he"] & sub["en"]).mean() * 100 if len(sub) else 0
        r = int(rows_cls.get(c, 0))
        class_table.append({
            "cls": cls_label(c, names),
            "kind": "טובין" if c <= GOODS_MAX else "שירותים",
            "terms": n(per_cls.get(c, 0)),
            "rows": n(r),
            "rej": pct_bare(rej_cls.get(c, 0) / r * 100) if r else "—",
            "bi": pct_bare(bi),
        })

    # ---- source mix per class (top classes by terms)
    top_src, rest_src = _top(per_cls, TOP_SRC)
    src_x = [cls_label(int(c), names) for c in top_src.index]
    has_rest = len(rest_src) > 0
    if has_rest:
        src_x.append("שאר הסוגים")
    src_series = []
    for k in ["intl", "both", "il"]:
        vals = [int(((pt["cls"] == c) & (pt["kind"] == k)).sum()) for c in top_src.index]
        if has_rest:
            vals.append(int((pt["cls"].isin(rest_src.index) & (pt["kind"] == k)).sum()))
        src_series.append({"name": SRC_KIND[k], "data": vals})
    src_tot = [sum(x["data"][i] for x in src_series) for i in range(len(src_x))]
    for x in src_series:
        x["share"] = [round(v / t_ * 100, 1) if t_ else 0 for v, t_ in zip(x["data"], src_tot)]
    src_table = [{"cls": x, "v": [n(s["data"][i]) for s in src_series]}
                 for i, x in enumerate(src_x)]

    # ---- rejection by class
    rej_rate = (rej_cls / rows_cls).fillna(0)
    elig = rej_rate[(rows_cls >= MIN_CLASS_ROWS) & (rej_cls > 0)]
    rej_top, _ = _top(elig, TOP_REJ)
    rej_x = [cls_label(int(c), names) for c in rej_top.index]
    rej_counts = [int(rej_cls[c]) for c in rej_top.index]
    rej_rates = [round(float(rej_rate[c] * 100), 1) for c in rej_top.index]
    rej_table = [{"cls": x, "count": n(v), "rate": pct_bare(r)}
                 for x, v, r in zip(rej_x, rej_counts, rej_rates)]

    # ---- rejection by source x language
    sl = df.groupby(["src", "lang"])["rej"].agg(["mean", "size", "sum"])
    srcs = [s for s in [SRC_INTL, SRC_IL] if s in df["src"].unique()]
    srcs += sorted(s for s in df["src"].unique() if s not in srcs)
    langs = [l for l in [HE, EN] if l in df["lang"].unique()]
    langs += sorted(l for l in df["lang"].unique() if l not in langs)
    src_names = {SRC_INTL: "מקור בינלאומי (GMS)", SRC_IL: "מחלקת סימני מסחר"}
    rs_series = [{"name": f"נוסחים ב{l}" if l in (HE, EN) else l,
                  "data": [round(float(sl.loc[(s, l), "mean"] * 100), 2) if (s, l) in sl.index else None
                           for s in srcs]} for l in langs]
    rs_table = []
    for s in srcs:
        for l in langs:
            if (s, l) in sl.index:
                r = sl.loc[(s, l)]
                rs_table.append({"src": src_names.get(s, s), "lang": l, "rows": n(r["size"]),
                                 "rej": n(r["sum"]), "rate": pct_bare(r["mean"] * 100, 2)})

    # ---- single-language terms per class
    pt["en_only"] = pt["en"] & ~pt["he"]
    pt["he_only"] = pt["he"] & ~pt["en"]
    single = pt.groupby("cls")[["en_only", "he_only"]].sum()
    single["tot"] = single["en_only"] + single["he_only"]
    lang_top, _ = _top(single.loc[single["tot"] > 0, "tot"], TOP_LANG)
    lang_x = [cls_label(int(c), names) for c in lang_top.index]
    lang_en = [int(single.loc[c, "en_only"]) for c in lang_top.index]
    lang_he = [int(single.loc[c, "he_only"]) for c in lang_top.index]
    lang_table = [{"cls": x, "en": n(a), "he": n(b)} for x, a, b in zip(lang_x, lang_en, lang_he)]

    # ---- wordings per term
    var_rows = []
    for lo, hi in VARIANT_BUCKETS:
        m = t["rows"] >= lo
        if hi is not None:
            m &= t["rows"] <= hi
        lab = f"{lo}+" if hi is None else (str(lo) if lo == hi else f"{lo}–{hi}")
        var_rows.append((lab, int(m.sum())))
    var_table = [{"b": b, "count": n(v), "share": pct_bare(v / total_terms * 100)}
                 for b, v in var_rows]

    # ---- wording length (words) by language x source
    box_names, box_data, box_table = [], [], []
    for l in langs:
        for s in srcs:
            w = df.loc[(df["lang"] == l) & (df["src"] == s), "words"]
            if len(w) < 20:
                continue
            q = _box(w)
            lab = f"{l} · {BOX_SRC.get(s, s)}"
            box_names.append(lab)
            box_data.append(q)
            box_table.append({"name": lab, "q": [f"{v:g}" for v in q], "count": n(len(w))})

    # ---- leading Hebrew words
    he = df[df["lang"] == HE]
    first = he["text"].str.split().str[0].fillna("")
    first = first.str.replace(r"[^\w֐-׿'\"״׳-]+", "", regex=True)
    first = first[first != ""]
    words = first.value_counts()
    words_top, _ = _top(words, TOP_WORDS)
    words_table = [{"w": w, "count": n(v), "share": pct_bare(v / len(he) * 100)}
                   for w, v in words_top.items()]

    # ---- newest term numbers
    shortest = (df.assign(L=df["text"].str.len())
                  .sort_values(["term", "lang", "L", "text"])
                  .drop_duplicates(["term", "lang"])
                  .set_index(["term", "lang"])["text"])

    def pick_text(term, lang):
        return shortest.get((term, lang), "")

    latest = t.dropna(subset=["tnum"]).sort_values(["tnum"], ascending=False).head(LATEST_N)
    latest_table = []
    for term, r in latest.iterrows():
        latest_table.append({
            "num": term,
            "he": pick_text(term, HE) or "—",
            "en": pick_text(term, EN) or "—",
            "cls": cls_label(int(r["cls"]), names),
            "src": "מחלקת סימני מסחר" if r["kind"] != "intl" else "מקור בינלאומי (GMS)",
        })

    # ---- appellations of origin
    ap = t[t["appell"]].sort_values(["cls", "tnum"])
    ap_table = []
    for term, r in ap.head(APPELL_MAX).iterrows():
        ap_table.append({
            "he": pick_text(term, HE) or "—",
            "en": pick_text(term, EN) or "—",
            "cls": cls_label(int(r["cls"]), names),
            "ok": "לא קביל" if r["rej_all"] else ("חלק מהנוסחים קבילים" if r["rej_any"] else "קביל"),
        })

    intl_max = df.loc[df["src"] == SRC_INTL, "tnum"].max()

    rules = [
        ("top_class", insight_top_class(per_cls, names, total_terms)),
        ("goods_services", insight_goods_services(t)),
        ("reject_source", insight_reject_source(df)),
        ("reject_class", insight_reject_class(df, names)),
        ("bilingual", insight_bilingual(t)),
        ("local", insight_local(t, names, intl_max)),
        ("variants", insight_variants(t)),
        ("lead_word", insight_lead_word(words, len(he))),
        ("appellation", insight_appellation(t, df, names)),
        ("multi_class", insight_multi_class(t)),
    ]
    insights = [{"id": i, "text_he": s} for i, s in rules if s]

    # ---- KPIs
    acc = (1 - df["rej"].mean()) * 100 if total_rows else 0
    bi_share = (t["he"] & t["en"]).mean() * 100 if total_terms else 0
    il_terms = int((t["kind"] != "intl").sum())
    kpis = {
        "terms": {"value": total_terms, "display": n(total_terms), "tone": "brand"},
        "rows": {"value": total_rows, "display": n(total_rows), "tone": "brand"},
        "accept": {"value": round(acc, 1), "display": pct_bare(acc),
                   "tone": "ok" if acc >= 97 else ("warn" if acc >= 90 else "danger")},
        "bilingual": {"value": round(bi_share, 1), "display": pct_bare(bi_share),
                      "tone": "ok" if bi_share >= 95 else "warn"},
    }

    n_goods = sum(1 for c in classes if c <= GOODS_MAX)
    n_serv = len(classes) - n_goods
    s0 = rej_top.index[0] if len(rej_top) else None
    labels = {
        "lede": (f"רשימת העזר של רשם סימני המסחר לניסוח רשימת הסחורות והשירותים בבקשה לרישום "
                 f"סימן מסחר: {n(total_terms)} מונחים ב-{n(total_rows)} נוסחים בעברית ובאנגלית, "
                 f"מסווגים ל-{len(classes)} סוגי ניצה ({n_goods} סוגי טובין ו-{n_serv} סוגי שירותים). "
                 f"לכל נוסח מצוין אם הוא קביל בבקשה, ולכל מונח — אם מקורו ברשימה הבינלאומית (GMS) "
                 f"או במחלקת סימני מסחר."),
        "accept_kpi": "מהנוסחים קבילים בבקשה",
        "bilingual_kpi": "מהמונחים מנוסחים בשתי השפות",
        "classes_note": (f"מספר המונחים בכל אחד מ-{len(classes)} סוגי ניצה, מחולק לטובין "
                         f"(סוגים 1 עד {GOODS_MAX}) ושירותים. גודל המלבן — מספר המונחים."),
        "classes_aria": (f"מפת עצים: מונחים לפי סוג ניצה. הגדול ביותר: סוג "
                         f"{cls_label(int(per_cls.idxmax()), names)} עם {n(per_cls.max())} מונחים."),
        "classes_caption": "מונחים, נוסחים, שיעור נוסחים לא קבילים ושיעור מונחים דו-לשוניים לפי סוג ניצה.",
        "src_note": (f"התפלגות המקור (באחוזים) ב-{TOP_SRC} הסוגים הגדולים: מונחים מהרשימה הבינלאומית בלבד, "
                     f"מונחים בינלאומיים שהמחלקה הוסיפה להם נוסח, ומונחים שהגדירה המחלקה בלבד."
                     + (" שאר הסוגים מקובצים יחד." if has_rest else "")),
        "src_aria": (f"תרשים עמודות מוערמות: שיעור המונחים לפי מקור ב-{TOP_SRC} סוגי הניצה הגדולים. "
                     f"{n(il_terms)} מונחים כוללים נוסח של מחלקת סימני מסחר."),
        "src_caption": "מונחים לפי מקור בסוגי הניצה הגדולים.",
        "rej_note": (f"{len(rej_x)} הסוגים עם השיעור הגבוה ביותר של נוסחים לא קבילים מכלל "
                     f"הנוסחים בסוג (סוגים עם {n(MIN_CLASS_ROWS)} נוסחים לפחות). הקו המקווקו — "
                     f"השיעור בכל המאגר, {pct(df['rej'].mean() * 100)}."),
        "rej_aria": (f"תרשים עמודות: שיעור נוסחים לא קבילים לפי סוג ניצה. הגבוה ביותר בסוג "
                     f"{cls_label(int(s0), names) if s0 is not None else ''}."),
        "rej_caption": "נוסחים לא קבילים ושיעורם לפי סוג ניצה.",
        "rs_note": "שיעור הנוסחים הלא קבילים לפי מקור המונח ושפת הנוסח.",
        "rs_aria": "תרשים עמודות: שיעור נוסחים לא קבילים לפי מקור ושפה.",
        "rs_caption": "נוסחים, נוסחים לא קבילים ושיעורם לפי מקור ושפה.",
        "lang_note": (f"מונחים שיש להם נוסח בשפה אחת בלבד, ב-{len(lang_x)} הסוגים שבהם הם "
                      f"הרבים ביותר."),
        "lang_aria": "תרשים עמודות מוערמות: מונחים באנגלית בלבד ובעברית בלבד לפי סוג ניצה.",
        "lang_caption": "מונחים חד-לשוניים לפי סוג ניצה.",
        "var_note": (f"כמה נוסחים (בשתי השפות יחד) יש לכל מונח. ממוצע: "
                     f"{t['rows'].mean():.1f} נוסחים למונח."),
        "var_aria": "תרשים עמודות: התפלגות מספר הנוסחים למונח.",
        "var_caption": "מונחים לפי מספר הנוסחים שלהם.",
        "box_note": ("אורך הנוסח במילים, לפי שפה ומקור (GMS — הרשימה הבינלאומית; המחלקה — מחלקת סימני מסחר). הקופסה — הרבעון התחתון עד העליון, הקו — "
                     "החציון; השפם נמתח מהאחוזון החמישי עד האחוזון התשעים וחמישה."),
        "box_aria": "תרשים קופסה: אורך הנוסחים במילים לפי שפה ומקור.",
        "box_caption": "אחוזוני אורך הנוסח במילים לפי שפה ומקור.",
        "words_note": (f"{TOP_WORDS} המילים הנפוצות ביותר בפתיחת נוסח בעברית, מתוך "
                       f"{n(len(he))} נוסחים בעברית."),
        "words_aria": (f"תרשים עמודות: המילים הפותחות הנפוצות בנוסחים בעברית. הנפוצה: "
                       f"{words_top.index[0] if len(words_top) else ''}."),
        "words_caption": "המילים הפותחות הנפוצות בנוסחים בעברית ושיעורן.",
        "latest_note": (f"{LATEST_N} המונחים בעלי המספר הגבוה ביותר במאגר — התוספות האחרונות "
                        f"לפי סדר המספור (המספור אינו כולל תאריך)."),
        "latest_caption": "המונחים בעלי המספר הגבוה ביותר, עם נוסח בעברית ובאנגלית וסוג ניצה.",
        "ap_note": (f"מונחים המסומנים ככינוי מקור — שם של אזור גאוגרפי שמשמש שם למוצר. "
                    f"{n(len(ap))} מונחים" + (f"; מוצגים {APPELL_MAX} הראשונים." if len(ap) > APPELL_MAX else ".")),
        "ap_caption": "מונחים המסומנים ככינוי מקור, סוג ניצה וקבילות.",
    }

    charts = {
        "classes": treemap,
        "src": {"x": src_x, "series": src_series},
        "rej": {"x": rej_x, "counts": rej_counts, "rates": rej_rates,
                "overall": round(float(df["rej"].mean() * 100), 2)},
        "rs": {"x": [src_names.get(s, s) for s in srcs], "series": rs_series},
        "lang": {"x": lang_x, "en": lang_en, "he": lang_he},
        "var": {"x": [b for b, _ in var_rows], "y": [v for _, v in var_rows]},
        "box": {"names": box_names, "data": box_data},
        "words": {"names": list(words_top.index), "values": [int(v) for v in words_top.values]},
    }
    tables = {
        "classes": class_table, "src": src_table, "src_heads": [s["name"] for s in src_series],
        "rej": rej_table, "rs": rs_table, "lang": lang_table, "var": var_table,
        "box": box_table, "words": words_table, "latest": latest_table, "ap": ap_table,
    }

    return {
        "agent_data": {
            "summary_he": (f"רשימת העזר של רשם סימני המסחר לסיווג ניצה: {n(total_terms)} מונחים "
                           f"לסחורות ושירותים ב-{len(classes)} סוגים, בעברית ובאנגלית, עם סימון "
                           f"קבילות לכל נוסח."),
            "dataset_kind": "registry",
            "suggested_tags": ["סימני מסחר", "סיווג ניצה", "קניין רוחני", "רשם סימני מסחר",
                               "משרד המשפטים"],
            "related_ids": ["556634fd-fcec-4bbd-8bd5-ba1390bc1c14",
                            "656f6e4c-ec04-40a5-b3bc-c556b2b127e0",
                            "6e207fff-abef-4f4d-aac7-61e669ba9ad5",
                            "029b6747-551b-47ad-9a05-ef7f7868fcd0"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"ap": bool(ap_table), "latest": bool(latest_table)},
    }
