"""סקר ביקושים לעסקים, באר שבע: which businesses residents want near home,
in the city centre or near work.

One row per (respondent, business category) answer. A respondent ("user_id")
picks one location context ("selection": בית / עיר / עבודה; a neighbourhood
only for home and work), then one or more categories, and in each ticks the
business types they miss. Demographics repeat on every row of a respondent.

The choice columns are messy, so items are rebuilt from choise_1..10:
- a "ג'ימבורי" tick is split at its apostrophe into "ג" + "ימבורי,…" with the
  rest of the ticks crammed comma-joined into the next cell: rejoin, split on
  commas;
- a form option holding two names ("פאב/בר", "בנק/כספומט") arrives as two
  ticks that always occur together. Within a category, items with at least
  MERGE_MIN ticks and the exact same set of answer rows are merged back into
  one "א / ב" item (data-driven, no hardcoded list).
Free-text answers ("בחירה חופשית") reuse the merged names when they match.
Shares are of respondents (distinct user_id), not of rows.
"""
from collections import defaultdict

import pandas as pd

CC = [f"choise_{i}" for i in range(1, 11)]
FREE = "בחירה חופשית"
NOTHING = "לא חסר לי כלום"
MERGE_MIN = 10
TOP_ITEMS = 15
TOP_CAT_ITEMS = 6
TOP_NB = 12
NB_MIN = 25          # home respondents a neighbourhood needs for the heatmap / table
FREE_MIN = 3         # respondents a free-text request needs to be listed
NEGATIVE = {"לא", "אין", "כלום", "לא יודע", "לא יודעת", "אין צורך"}
SELECTION_ORDER = ["בית", "עיר", "עבודה"]
SELECTION_HE = {"בית": "ליד הבית", "עיר": "במרכז העיר", "עבודה": "ליד העבודה"}
FAMILY_HE = {"married": "נשואים", "single": "רווקים", "divorced": "גרושים", "widow": "אלמנים"}
AGE_BANDS = [(0, 25, "עד 24"), (25, 30, "25 עד 29"), (30, 35, "30 עד 34"),
             (35, 40, "35 עד 39"), (40, 45, "40 עד 44"), (45, 55, "45 עד 54"),
             (55, 65, "55 עד 64"), (65, 200, "65 ומעלה")]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def _nb_label(n):
    """Lettered neighbourhoods ("ב", "יא") read as "שכונה ב׳"."""
    if 1 <= len(n) <= 2 and all("א" <= ch <= "ת" for ch in n):
        return f"שכונה {n}׳"
    return n


def _tokens(cells):
    raw = []
    for c in cells:
        for t in c.split(","):
            t = " ".join(t.replace("\\", " ").split())
            if t:
                raw.append(t)
    out = []
    i = 0
    while i < len(raw):
        t = raw[i]
        if t == "ג" and i + 1 < len(raw) and raw[i + 1].startswith("ימבורי"):
            t = "ג'" + raw[i + 1]
            i += 1
        if t not in out:
            out.append(t)
        i += 1
    return out


def _prepare(df):
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    df = df[(df["user_id"] != "") & (df["category_name"] != "")]
    df = df.sort_values(["user_id", "date", "category_name", "choices"] + CC, kind="mergesort")
    df = df.reset_index(drop=True)
    df["toks"] = [_tokens(r) for r in df[CC].itertuples(index=False, name=None)]
    df["ts"] = pd.to_datetime(df["date"].str.replace(r"\s+", " ", regex=True),
                              format="%d%m%Y %H:%M:%S", errors="coerce")
    return df


def _merge_map(df):
    """token -> merged label, from tokens that always co-occur in a category."""
    mapping = {}
    for cat, g in df[~df["category_name"].isin([FREE, NOTHING])].groupby("category_name", sort=True):
        rows = defaultdict(set)
        pos = defaultdict(list)
        for idx, toks in zip(g.index, g["toks"]):
            for p, t in enumerate(toks):
                rows[t].add(idx)
                pos[t].append(p)
        groups = defaultdict(list)
        for t, s in rows.items():
            if len(s) >= MERGE_MIN:
                groups[frozenset(s)].append(t)
        for members in groups.values():
            if len(members) < 2:
                continue
            members.sort(key=lambda t: (sum(pos[t]) / len(pos[t]), t))
            label = " / ".join(members)
            for t in members:
                mapping[t] = label
    return mapping


def _users(df):
    cols = ["selection", "neighborhood", "gender", "student", "children",
            "vehicle", "family_status", "age"]
    first = {}
    for c in cols:
        s = df[df[c] != ""].groupby("user_id", sort=True)[c].first()
        first[c] = s
    u = pd.DataFrame(index=sorted(df["user_id"].unique()))
    for c in cols:
        u[c] = first[c].reindex(u.index).fillna("")
    u["age_n"] = pd.to_numeric(u["age"], errors="coerce")
    u.loc[(u["age_n"] < 10) | (u["age_n"] > 110), "age_n"] = float("nan")
    return u


def _rank(counter, n_users, top):
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return [{"name": k, "n": int(v), "share": v / n_users} for k, v in items]


def compute(frames):
    df = _prepare(frames["survey"])
    mapping = _merge_map(df)
    df["items"] = [list(dict.fromkeys(mapping.get(t, t) for t in toks)) for toks in df["toks"]]
    users = _users(df)
    n_users = len(users)
    n_rows = len(df)
    struct = df[~df["category_name"].isin([FREE, NOTHING])]
    free = df[df["category_name"] == FREE]

    # user -> set of items (structured + free-text that match a structured item)
    struct_items = set(i for its in struct["items"] for i in its)
    user_items = defaultdict(set)
    for uid, its in zip(struct["user_id"], struct["items"]):
        user_items[uid].update(its)
    for uid, its in zip(free["user_id"], free["items"]):
        user_items[uid].update(i for i in its if i in struct_items)
    item_users = defaultdict(int)
    for its in user_items.values():
        for i in its:
            item_users[i] += 1
    top_items = _rank(item_users, n_users, TOP_ITEMS)
    n_mentions = int(sum(len(its) for its in df["items"]))

    # categories
    cat_users = df.groupby("category_name")["user_id"].nunique()
    cats = sorted(cat_users.items(), key=lambda kv: (-kv[1], kv[0]))
    cat_rows = [{"name": k, "n": int(v), "share": v / n_users} for k, v in cats]
    struct_cats = [r["name"] for r in cat_rows if r["name"] not in (FREE, NOTHING)]

    # per-category top items (respondents who ticked the item in that category)
    cat_items = []
    for ci, cat in enumerate(struct_cats):
        g = struct[struct["category_name"] == cat]
        cnt = defaultdict(set)
        for uid, its in zip(g["user_id"], g["items"]):
            for i in its:
                cnt[i].add(uid)
        n_cat = g["user_id"].nunique()
        ranked = sorted(((k, len(v)) for k, v in cnt.items()), key=lambda kv: (-kv[1], kv[0]))
        rows = [{"name": k, "n": int(v), "share": v / n_cat} for k, v in ranked[:TOP_CAT_ITEMS]]
        cat_items.append({
            "id": f"chart-cat-{ci}", "name": cat, "n_users": _int(n_cat), "n_items": len(ranked),
            "rows": [{"name": r["name"], "n": _int(r["n"]), "share": _pct(r["share"])} for r in rows],
            "chart": {"names": [r["name"] for r in rows], "values": [round(r["share"] * 100, 1) for r in rows]},
            "aria": f"הפריטים המבוקשים בקטגוריה {cat}: {rows[0]['name']} מוביל עם {_pct(rows[0]['share'])} מהבוחרים בקטגוריה" if rows else f"קטגוריה {cat}",
        })

    # location context
    sel_counts = users["selection"].value_counts()
    sel_order = [s for s in SELECTION_ORDER if s in sel_counts.index] + \
        sorted(s for s in sel_counts.index if s not in SELECTION_ORDER and s != "")
    sel_rows = [{"key": s, "name": SELECTION_HE.get(s, s), "n": int(sel_counts[s]),
                 "share": sel_counts[s] / n_users} for s in sel_order]

    # items by location context: shares within each context, for the top items overall
    sel_share = {}
    for s in sel_order:
        uids = set(users.index[users["selection"] == s])
        cnt = defaultdict(int)
        for uid in uids:
            for i in user_items.get(uid, ()):
                cnt[i] += 1
        sel_share[s] = (len(uids), cnt)
    ctx_names = [r["name"] for r in top_items[:10]]
    ctx_series = []
    for s in sel_order:
        n_s, cnt = sel_share[s]
        ctx_series.append({"name": SELECTION_HE.get(s, s),
                           "values": [round(cnt.get(i, 0) / n_s * 100, 1) if n_s else 0 for i in ctx_names]})

    # neighbourhoods (home + work respondents)
    nb_users = users[users["neighborhood"] != ""]
    nb_tab = pd.crosstab(nb_users["neighborhood"], nb_users["selection"])
    nb_tab["_t"] = nb_tab.sum(axis=1)
    nb_sorted = sorted(nb_tab.index, key=lambda n: (-int(nb_tab.loc[n, "_t"]), n))
    nb_top = nb_sorted[:TOP_NB]
    nb_rest = nb_sorted[TOP_NB:]
    nb_series_keys = [s for s in sel_order if s in nb_tab.columns]
    nb_names = [_nb_label(n) for n in nb_top] + (["אחר"] if nb_rest else [])
    nb_series = []
    for s in nb_series_keys:
        vals = [int(nb_tab.loc[n, s]) for n in nb_top]
        if nb_rest:
            vals.append(int(sum(nb_tab.loc[n, s] for n in nb_rest)))
        nb_series.append({"name": SELECTION_HE.get(s, s), "values": vals})
    nb_table = []
    for i, nm in enumerate(nb_names):
        nb_table.append({"name": nm, "vals": [_int(sr["values"][i]) for sr in nb_series],
                         "total": _int(sum(sr["values"][i] for sr in nb_series))})

    # heatmap: home respondents' category reach per neighbourhood
    home = users[(users["selection"] == "בית") & (users["neighborhood"] != "")]
    home_nb = home["neighborhood"].value_counts()
    heat_nbs = sorted([n for n, c in home_nb.items() if c >= NB_MIN], key=lambda n: (-int(home_nb[n]), n))
    user_cats = struct.groupby("user_id")["category_name"].apply(set)
    home_all = [u for u in home.index]
    city_avg = {c: sum(1 for u in home_all if c in user_cats.get(u, set())) / len(home_all) if home_all else 0
                for c in struct_cats}
    heat = []
    heat_cells = {}
    for xi, nb in enumerate(heat_nbs):
        uids = list(home.index[home["neighborhood"] == nb])
        for yi, c in enumerate(struct_cats):
            v = sum(1 for u in uids if c in user_cats.get(u, set())) / len(uids)
            heat.append([xi, yi, round(v * 100, 1), len(uids)])
            heat_cells[(nb, c)] = (v, len(uids))
    heat_max = max([h[2] for h in heat], default=0)

    # top 3 requested items per neighbourhood (home respondents)
    nb_top_items = []
    for nb in heat_nbs:
        uids = list(home.index[home["neighborhood"] == nb])
        cnt = defaultdict(int)
        for u in uids:
            for i in user_items.get(u, ()):
                cnt[i] += 1
        ranked = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        nb_top_items.append({"name": _nb_label(nb), "n": _int(len(uids)),
                             "items": [f"{k} ({_pct(v / len(uids))})" for k, v in ranked]})

    # demographics: category reach by group
    def reach_by(col, groups):
        out = []
        for key, label in groups:
            uids = list(users.index[users[col] == key])
            if not uids:
                continue
            vals = [round(sum(1 for u in uids if c in user_cats.get(u, set())) / len(uids) * 100, 1)
                    for c in struct_cats]
            out.append({"name": label, "n": len(uids), "values": vals})
        return out
    gender_series = reach_by("gender", [("נקבה", "נשים"), ("זכר", "גברים")])
    kids_series = reach_by("children", [("יש", "עם ילדים"), ("אין", "בלי ילדים")])

    # respondent profile (100% stacked)
    profile_defs = [
        ("gender", "מגדר", [("נקבה", "נשים"), ("זכר", "גברים")]),
        ("children", "ילדים", [("יש", "יש ילדים"), ("אין", "אין ילדים")]),
        ("vehicle", "רכב", [("יש", "יש רכב"), ("אין", "אין רכב")]),
        ("student", "סטודנטים", [("כן", "סטודנטים"), ("לא", "לא סטודנטים")]),
    ]
    profile_rows = []
    for col, title, vals in profile_defs:
        known = users[users[col] != ""]
        parts = []
        for key, label in vals:
            n = int((known[col] == key).sum())
            parts.append({"name": label, "n": n, "share": n / len(known) if len(known) else 0})
        profile_rows.append({"title": title, "known": len(known), "parts": parts,
                             "missing": int(n_users - len(known))})
    fam = users[users["family_status"] != ""]["family_status"].value_counts()
    fam_rows = [{"name": FAMILY_HE.get(k, k), "n": int(v), "share": v / int(fam.sum())}
                for k, v in sorted(fam.items(), key=lambda kv: (-kv[1], kv[0]))]

    # age
    ages = users["age_n"].dropna()
    age_rows = []
    for lo, hi, label in AGE_BANDS:
        n = int(((ages >= lo) & (ages < hi)).sum())
        age_rows.append({"name": label, "n": n, "share": n / len(ages) if len(ages) else 0})
    median_age = float(ages.median()) if len(ages) else None

    # free-text requests
    free_cnt = defaultdict(set)
    for uid, its in zip(free["user_id"], free["items"]):
        for i in its:
            if i in NEGATIVE or len(i) < 2:
                continue
            free_cnt[i].add(uid)
    free_rank = sorted(((k, len(v)) for k, v in free_cnt.items() if len(v) >= FREE_MIN),
                       key=lambda kv: (-kv[1], kv[0]))[:12]
    n_free_users = free["user_id"].nunique()
    nothing_users = int(df[df["category_name"] == NOTHING]["user_id"].nunique())

    # survey dates
    ts = df["ts"].dropna()
    d0, d1 = (ts.min(), ts.max()) if len(ts) else (None, None)
    year = d1.year if d1 is not None else None
    if d0 is not None and d0.month == d1.month and d0.year == d1.year:
        period_he = f"{d0.day} עד {d1.day} ב{MONTHS_HE[d1.month - 1]} {d1.year}"
    elif d0 is not None:
        period_he = f"{d0.day} ב{MONTHS_HE[d0.month - 1]} {d0.year} עד {d1.day} ב{MONTHS_HE[d1.month - 1]} {d1.year}"
    else:
        period_he = ""

    # ── insights ────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_top():
        if len(top_items) < 2:
            return None
        a, b = top_items[0], top_items[1]
        lead = " בפער ניכר מהמקום השני" if a["n"] >= 1.2 * b["n"] else ""
        return (f"העסק המבוקש ביותר הוא {a['name']}: {_pct(a['share'])} מהמשיבים ({_int(a['n'])} "
                f"מתוך {_int(n_users)}) סימנו אותו{lead}. אחריו {b['name']} עם {_pct(b['share'])}.")
    add("top_item", ins_top())

    def ins_indie():
        names = {r: item_users.get(r, 0) for r in item_users}
        indie = next((k for k in names if "שכונתי" in k and "בית קפה" in k), None)
        chain = next((k for k in names if "רשת" in k and "בית קפה" in k and k != indie), None)
        if not indie or not chain or names[chain] == 0:
            return None
        ratio = names[indie] / names[chain]
        if ratio >= 1.3:
            return (f"המשיבים מעדיפים בית קפה שכונתי עצמאי על פני רשת: {_int(names[indie])} ביקשו "
                    f"בית קפה שכונתי שאינו רשת, לעומת {_int(names[chain])} שביקשו בית קפה של רשת מוכרת "
                    f"(פי {ratio:.1f}).")
        if ratio <= 1 / 1.3:
            return (f"דווקא בית קפה של רשת מוכרת מבוקש יותר: {_int(names[chain])} משיבים, לעומת "
                    f"{_int(names[indie])} שביקשו בית קפה שכונתי עצמאי.")
        return None
    add("indie_cafe", ins_indie())

    def ins_cat():
        rows = [r for r in cat_rows if r["name"] not in (FREE, NOTHING)]
        if len(rows) < 3:
            return None
        a, b = rows[0], rows[1]
        low = rows[-1]
        return (f"הקטגוריה שנבחרה הכי הרבה היא {a['name']} ({_pct(a['share'])} מהמשיבים), ואחריה "
                f"{b['name']} ({_pct(b['share'])}). הנבחרת פחות מכולן: {low['name']} ({_pct(low['share'])}).")
    add("category", ins_cat())

    def ins_where():
        if len(sel_rows) < 2:
            return None
        parts = ", ".join(f"{r['name']} {_pct(r['share'])}" for r in sel_rows)
        return f"המשיבים התחלקו לפי המקום שאליו התייחסו בסקר: {parts}."
    add("where", ins_where())

    def ins_nb():
        best = None
        for (nb, c), (v, n) in heat_cells.items():
            gap = v - city_avg.get(c, 0)
            key = (gap, nb, c)
            if best is None or key > best[0]:
                best = (key, nb, c, v, n)
        if best is None or best[0][0] < 0.10:
            return None
        _, nb, c, v, n = best
        return (f"ב{_nb_label(nb)} בלט הביקוש לקטגוריה {c}: {_pct(v)} מ-{_int(n)} המשיבים שגרים בה, "
                f"לעומת {_pct(city_avg[c])} בממוצע בכל השכונות שבסקר.")
    add("neighborhood", ins_nb())

    def ins_gender():
        if len(gender_series) < 2:
            return None
        w, m = gender_series[0], gender_series[1]
        gaps = sorted(((w["values"][i] - m["values"][i], c) for i, c in enumerate(struct_cats)),
                      key=lambda g: (-abs(g[0]), g[1]))
        if not gaps or abs(gaps[0][0]) < 8:
            return None
        g, c = gaps[0]
        hi, lo = (w, m) if g > 0 else (m, w)
        i = struct_cats.index(c)
        return (f"הפער המגדרי הגדול ביותר הוא בקטגוריה {c}: {hi['values'][i]:.0f}% מה{hi['name']} "
                f"בחרו בה, לעומת {lo['values'][i]:.0f}% מה{lo['name']}.")
    add("gender", ins_gender())

    def ins_kids():
        if len(kids_series) < 2:
            return None
        k, nk = kids_series[0], kids_series[1]
        gaps = sorted(((k["values"][i] - nk["values"][i], c) for i, c in enumerate(struct_cats)),
                      key=lambda g: (-g[0], g[1]))
        if not gaps or gaps[0][0] < 8:
            return None
        g, c = gaps[0]
        i = struct_cats.index(c)
        return (f"להורים חסרים בעיקר עסקים בקטגוריה {c}: {k['values'][i]:.0f}% מהמשיבים עם ילדים "
                f"בחרו בה, לעומת {nk['values'][i]:.0f}% מהמשיבים בלי ילדים.")
    add("kids", ins_kids())

    def ins_ctx():
        if "בית" not in sel_share or "עיר" not in sel_share:
            return None
        nh, ch = sel_share["בית"]
        nc, cc = sel_share["עיר"]
        if nh < 30 or nc < 30:
            return None
        cands = [r["name"] for r in top_items]
        diffs = sorted(((cc.get(i, 0) / nc - ch.get(i, 0) / nh, i) for i in cands), key=lambda d: (-d[0], d[1]))
        if not diffs or diffs[0][0] < 0.05:
            return None
        g, i = diffs[0]
        return (f"הביקוש ל{i} גבוה הרבה יותר במרכז העיר מאשר ליד הבית: {_pct(cc.get(i, 0) / nc)} מהמשיבים "
                f"על מרכז העיר, לעומת {_pct(ch.get(i, 0) / nh)} מהמשיבים על השכונה שלהם.")
    add("context", ins_ctx())

    def ins_age():
        if median_age is None or len(ages) < 30:
            return None
        band = max(age_rows, key=lambda r: (r["n"], r["name"]))
        return (f"גיל חציוני של המשיבים: {median_age:.0f}. קבוצת הגיל הגדולה היא {band['name']} "
                f"({_pct(band['share'])} מהמשיבים שציינו גיל)"
                + (", כך שהסקר משקף בעיקר צעירים ומשפחות צעירות." if median_age < 40 else "."))
    add("age", ins_age())

    # ── KPIs, labels, agent_data ─────────────────────────────────────────
    top = top_items[0] if top_items else None
    kpis = {
        "users": {"value": n_users, "display": _int(n_users), "tone": "brand"},
        "answers": {"value": n_rows, "display": _int(n_rows), "tone": "brand"},
        "mentions": {"value": n_mentions, "display": _int(n_mentions), "tone": "info"},
        "neighborhoods": {"value": int(nb_users["neighborhood"].nunique()),
                          "display": _int(nb_users["neighborhood"].nunique()), "tone": "brand"},
    }
    if top:
        kpis["top_share"] = {"value": round(top["share"] * 100, 1), "display": _pct(top["share"]),
                             "tone": "ok"}

    year_s = str(year) if year else ""
    h1 = f"סקר ביקושים לעסקים בבאר שבע {year_s}".strip()
    summary = (f"אילו עסקים חסרים לתושבי באר שבע ליד הבית, במרכז העיר וליד העבודה: {_int(n_users)} משיבים"
               + (f", והמבוקש ביותר: {top['name']} ({_pct(top['share'])})." if top else "."))
    if len(summary) > 155:
        summary = f"אילו עסקים חסרים לתושבי באר שבע: סקר ביקושים בקרב {_int(n_users)} משיבים."

    n_cat_choices = len(struct_cats) + (1 if n_free_users else 0)
    lede = (f"הסקר נערך {('בימים ' + period_he) if period_he else ''} בקרב {_int(n_users)} משיבים, "
            f"שענו בסך הכול {_int(n_rows)} תשובות ב-{n_cat_choices} קטגוריות עסקים. כל משיב בחר אם הוא מתייחס לשכונת "
            f"המגורים, למרכז העיר או לאזור העבודה, וסימן את סוגי העסקים שחסרים לו שם. "
            f"השיעורים בעמוד הם מתוך המשיבים, לא מתוך התשובות.")
    labels = {
        "h1": h1,
        "lede": lede,
        "users_kpi": "משיבים לסקר",
        "answers_kpi": "תשובות לפי קטגוריה",
        "mentions_kpi": "סימונים של סוגי עסקים",
        "nb_kpi": "שכונות ואזורים שצוינו",
        "top_kpi": f"מהמשיבים ביקשו {top['name']}" if top else "",
        "top_items_note": (f"שיעור המשיבים שסימנו כל סוג עסק, מתוך כל {_int(n_users)} המשיבים. "
                           f"אפשרויות טופס שכללו שני שמות (למשל פאב ובר) מאוחדות לפריט אחד."),
        "top_items_aria": (f"סוגי העסקים המבוקשים ביותר. במקום הראשון {top['name']} עם {_pct(top['share'])} מהמשיבים"
                           if top else "סוגי העסקים המבוקשים ביותר"),
        "cat_aria": "שיעור המשיבים שבחרו כל קטגוריית עסקים",
        "sel_aria": "חלוקת המשיבים לפי המקום שאליו התייחסו: ליד הבית, במרכז העיר או ליד העבודה",
        "ctx_aria": "שיעור המבקשים של עשרת העסקים המובילים, לפי המקום שאליו התייחסו המשיבים",
        "nb_aria": f"מספר המשיבים לפי שכונה או אזור, {len(nb_top)} המובילים",
        "nb_note": (f"משיבים שהתייחסו לשכונת המגורים או לאזור העבודה שלהם. {len(nb_top)} השכונות הגדולות מוצגות בנפרד"
                    + (", השאר תחת אחר." if nb_rest else ".")),
        "heat_aria": "שיעור הבוחרים בכל קטגוריה בכל שכונה, בקרב משיבים שהתייחסו לשכונת המגורים",
        "heat_note": (f"משיבים שהתייחסו לשכונת המגורים שלהם, בשכונות עם {NB_MIN} משיבים לפחות. "
                      f"כל תא: שיעור המשיבים מהשכונה שבחרו בקטגוריה. גוון כהה יותר = שיעור גבוה יותר."),
        "nbtop_note": f"שלושת העסקים שסומנו הכי הרבה בכל שכונה עם {NB_MIN} משיבים לפחות שהתייחסו לשכונת המגורים.",
        "gender_aria": "שיעור הבוחרים בכל קטגוריה, נשים לעומת גברים",
        "kids_aria": "שיעור הבוחרים בכל קטגוריה, משיבים עם ילדים לעומת בלי ילדים",
        "profile_aria": "פרופיל המשיבים: מגדר, ילדים, רכב וסטודנטים",
        "profile_note": "שיעורים מתוך המשיבים שענו על כל שאלה. מספר המשיבים שלא ענו מופיע בטבלה.",
        "age_aria": (f"התפלגות גילי המשיבים, גיל חציוני {median_age:.0f}" if median_age is not None
                     else "התפלגות גילי המשיבים"),
        "age_note": (f"{_int(len(ages))} משיבים שציינו גיל. גיל חציוני: {median_age:.0f}." if median_age is not None
                     else "לא צוין גיל."),
        "fam_aria": "המצב המשפחתי של המשיבים",
        "free_aria": "הבקשות שנכתבו בבחירה חופשית ושחזרו הכי הרבה",
        "free_note": (f"{_int(n_free_users)} משיבים כתבו בקשות משלהם. מוצגות בקשות שכתבו {FREE_MIN} משיבים לפחות, "
                      f"בלי תשובות שליליות כמו לא או אין."
                      + (f" עוד {_int(nothing_users)} משיבים ענו שלא חסר להם כלום." if nothing_users else "")),
        "cats_note": f"{TOP_CAT_ITEMS} סוגי העסקים המבוקשים בכל קטגוריה, כשיעור מתוך המשיבים שבחרו בקטגוריה.",
    }

    def fmt_rows(rows):
        return [{"name": r["name"], "n": _int(r["n"]), "share": _pct(r["share"], 1)} for r in rows]

    charts = {
        "top_items": {"names": [r["name"] for r in top_items],
                      "values": [round(r["share"] * 100, 1) for r in top_items]},
        "cats": {"names": [r["name"] for r in cat_rows], "values": [round(r["share"] * 100, 1) for r in cat_rows]},
        "sel": [{"name": r["name"], "value": r["n"]} for r in sel_rows],
        "ctx": {"names": ctx_names, "series": ctx_series},
        "nb": {"names": nb_names, "series": nb_series},
        "heat": {"x": [_nb_label(n) for n in heat_nbs], "y": struct_cats, "cells": heat, "max": heat_max},
        "gender": {"names": struct_cats, "series": [{"name": s["name"], "values": s["values"]} for s in gender_series]},
        "kids": {"names": struct_cats, "series": [{"name": s["name"], "values": s["values"]} for s in kids_series]},
        "profile": {
            "names": [p["title"] for p in profile_rows],
            "series": [
                {"name": "first", "labels": [p["parts"][0]["name"] for p in profile_rows],
                 "values": [round(p["parts"][0]["share"] * 100, 1) for p in profile_rows]},
                {"name": "second", "labels": [p["parts"][1]["name"] for p in profile_rows],
                 "values": [round(p["parts"][1]["share"] * 100, 1) for p in profile_rows]},
            ],
        },
        "fam": [{"name": r["name"], "value": r["n"]} for r in fam_rows],
        "age": {"names": [r["name"] for r in age_rows], "values": [r["n"] for r in age_rows]},
        "free": {"names": [k for k, _ in free_rank], "values": [v for _, v in free_rank]},
    }

    def series_table(names, series):
        return [{"name": nm, "vals": [f"{s['values'][i]:.1f}%" for s in series]} for i, nm in enumerate(names)]

    tables = {
        "top_items": fmt_rows(top_items),
        "cats": fmt_rows(cat_rows),
        "sel": fmt_rows(sel_rows),
        "ctx": series_table(ctx_names, ctx_series),
        "ctx_heads": [s["name"] for s in ctx_series],
        "nb": nb_table,
        "nb_heads": [s["name"] for s in nb_series],
        "nb_top_items": nb_top_items,
        "gender": series_table(struct_cats, gender_series),
        "gender_heads": [f"{s['name']} (n={_int(s['n'])})" for s in gender_series],
        "kids": series_table(struct_cats, kids_series),
        "kids_heads": [f"{s['name']} (n={_int(s['n'])})" for s in kids_series],
        "profile": [{"title": p["title"],
                     "parts": ", ".join(f"{x['name']} {_pct(x['share'], 1)}" for x in p["parts"]),
                     "missing": _int(p["missing"])} for p in profile_rows],
        "fam": fmt_rows(fam_rows),
        "age": fmt_rows(age_rows),
        "free": [{"name": k, "n": _int(v)} for k, v in free_rank],
    }

    temporal = str(year) if year else None
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "rankings",
        "suggested_tags": ["עסקים", "יזמות", "סקר תושבים", "כלכלה מקומית", "באר שבע"],
        "related_ids": ["54b65747-904e-42e1-9316-0575ebbc1216",
                        "fffada0a-b021-4629-9244-bc5e301f23d5",
                        "4491ecd9-5f9c-4299-a79f-43ed979651f9",
                        "947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe"],
        "spatial_coverage": "באר שבע",
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "cat_items": cat_items,
        "labels": labels,
        "flags": {"heat": len(heat_nbs) >= 2, "free": len(free_rank) >= 3, "age": len(ages) >= 30,
                  "fam": len(fam_rows) >= 2, "top_share": top is not None,
                  "gender": len(gender_series) == 2, "kids": len(kids_series) == 2},
        "insights": insights,
    }
