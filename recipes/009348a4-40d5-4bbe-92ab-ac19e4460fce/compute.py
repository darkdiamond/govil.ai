"""Israel's local authorities (municipal list, unified): type, district, codes.

A registry of every local authority: its type (city / local council /
regional council), CBS-style authority code, tax-authority company number
(ח"פ), long name and district. Every number on the page is computed here;
insight rules return None when their premise doesn't hold.
"""
import pandas as pd

# Known types: ordering + plural labels. Unknown types flow through after
# these, alphabetically, labelled with their raw value.
TYPE_ORDER = ["עירייה", "מועצה מקומית", "מועצה אזורית"]
TYPE_PLURAL = {
    "עירייה": "עיריות",
    "מועצה מקומית": "מועצות מקומיות",
    "מועצה אזורית": "מועצות אזוריות",
}
# Expected first word of the long name per type (for a consistency check).
TYPE_PREFIX = {
    "עירייה": "עריית",
    "מועצה מקומית": "מועצה מקומית",
    "מועצה אזורית": "מועצה אזורית",
}
NO_DISTRICT = "ללא שיוך מחוזי"


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _plural(t):
    return TYPE_PLURAL.get(t, t)


def _district_label(d):
    """'מחוז הצפון', but 'אזור יהודה והשומרון' stays as is."""
    if d == NO_DISTRICT or d.startswith("אזור") or d.startswith("מחוז"):
        return d
    return f"מחוז {d}"


def _type_key(t):
    return (TYPE_ORDER.index(t) if t in TYPE_ORDER else len(TYPE_ORDER), t)


def _hp_valid(s):
    """Israeli 9-digit company-number check digit (Luhn-style, weights 1,2)."""
    if len(s) != 9 or not s.isdigit():
        return False
    total = 0
    for i, ch in enumerate(s):
        v = int(ch) * (1 if i % 2 == 0 else 2)
        total += v // 10 + v % 10
    return total % 10 == 0


def _prepare(df):
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    df["type"] = df["LocalAuthorityType"].str.replace(r"\s+", " ", regex=True)
    df["name"] = df["LocalAuthorityName"].str.replace(r"\s+", " ", regex=True)
    df["long"] = df["LocalAuthorityLongName"].str.replace(r"\s+", " ", regex=True)
    df["district"] = df["LocalAuthorityDistrict"].str.replace(r"\s+", " ", regex=True)
    df.loc[df["district"] == "", "district"] = NO_DISTRICT
    df["code"] = pd.to_numeric(df["LocalAuthorityCode"].str.replace(",", ""), errors="coerce")
    df["hp"] = df["LocalAuthorityHPNumber"].str.replace(r"[^0-9]", "", regex=True)
    df = df[(df["name"] != "") & (df["type"] != "")]
    df = df.sort_values(["type", "district", "name", "LocalAuthorityCode", "hp"], kind="stable")
    df = df.reset_index(drop=True)
    df["hp_ok"] = df["hp"].map(_hp_valid)

    def _embeds(row):
        if pd.isna(row["code"]) or len(row["hp"]) != 9:
            return False
        return row["hp"][:4] == "5002" and row["hp"][4:8] == f"{int(row['code']):04d}"

    df["hp_embeds"] = df.apply(_embeds, axis=1) if len(df) else []

    def _prefix_ok(row):
        p = TYPE_PREFIX.get(row["type"])
        if p is None:
            return True
        return row["long"].startswith(p)

    df["prefix_ok"] = df.apply(_prefix_ok, axis=1) if len(df) else []
    return df


# ── insight rules ────────────────────────────────────────────────────────


def insight_type_mix(by_type, total):
    if by_type.empty or total == 0:
        return None
    top_t, top_v = by_type.idxmax(), int(by_type.max())
    if (by_type == top_v).sum() > 1:
        return None  # tie: no single most common type
    others = [f"{_int(v)} {_plural(t)}" for t, v in by_type.items() if t != top_t and v > 0]
    tail = ""
    if len(others) == 1:
        tail = f"; לצדן {others[0]}"
    elif len(others) > 1:
        tail = "; לצדן " + ", ".join(others[:-1]) + " ו-" + others[-1]
    return (f"{_plural(top_t)} הן הסוג הנפוץ ביותר: {_int(top_v)} מתוך {_int(total)} "
            f"הרשויות ({_pct(top_v / total)}){tail}.")


def insight_top_district(by_district, xt, total):
    real = by_district.drop(NO_DISTRICT, errors="ignore")
    if real.empty or total == 0:
        return None
    name, v = real.index[0], int(real.iloc[0])
    if len(real) > 1 and int(real.iloc[1]) == v:
        return None
    share = v / total
    if share < 0.2:
        return None
    s = (f"ב{_district_label(name)} נמצא המספר הגדול ביותר של רשויות: {_int(v)} "
         f"({_pct(share)} מכלל הרשויות)")
    row = xt.loc[name]
    dom_t, dom_v = row.idxmax(), int(row.max())
    if (row == dom_v).sum() == 1 and dom_v / v >= 0.5:
        s += f", ורובן {_plural(dom_t)} ({_int(dom_v)})"
    return s + "."


def insight_city_share(xt):
    if "עירייה" not in xt.columns:
        return None
    tot = xt.sum(axis=1)
    elig = xt[(tot >= 5) & (xt.index != NO_DISTRICT)]
    if len(elig) < 2:
        return None
    share = (elig["עירייה"] / elig.sum(axis=1)).sort_index()
    hi = share.sort_values(ascending=False, kind="stable")
    lo = share.sort_values(ascending=True, kind="stable")
    h, l = hi.index[0], lo.index[0]
    if hi.iloc[0] - lo.iloc[0] < 0.2:
        return None
    hc, ht = int(elig.loc[h, "עירייה"]), int(elig.loc[h].sum())
    lc, lt = int(elig.loc[l, "עירייה"]), int(elig.loc[l].sum())
    return (f"שיעור העיריות משתנה מאוד בין המחוזות: ב{_district_label(h)} {_int(hc)} מתוך "
            f"{_int(ht)} הרשויות הן עיריות ({_pct(hi.iloc[0])}), ואילו ב{_district_label(l)} "
            f"רק {_int(lc)} מתוך {_int(lt)} ({_pct(lo.iloc[0])}), "
            f"בהשוואה בין מחוזות עם חמש רשויות לפחות.")


def insight_regional(xt):
    if "מועצה אזורית" not in xt.columns:
        return None
    col = xt["מועצה אזורית"].drop(NO_DISTRICT, errors="ignore")
    col = col.sort_index().sort_values(ascending=False, kind="stable")
    n = int(col.sum())
    if n < 5:
        return None
    top, v = col.index[0], int(col.iloc[0])
    if len(col) > 1 and int(col.iloc[1]) == v:
        return None
    if v / n < 0.25:
        return None
    return (f"{_district_label(top)} מוביל במועצות האזוריות עם {_int(v)} מתוך {_int(n)} "
            f"({_pct(v / n)}).")


def insight_hp(df):
    n = len(df)
    if n == 0:
        return None
    valid = int(df["hp_ok"].sum())
    if valid == n:
        return (f"כל {_int(n)} מספרי הח״פ במאגר תקינים: בני תשע ספרות, וספרת הביקורת "
                f"של כולם מתאימה.")
    bad = n - valid
    one = "מספר ח״פ אחד אינו תקין" if bad == 1 else f"{_int(bad)} מספרי ח״פ אינם תקינים"
    return f"{one} (אורך שגוי או ספרת ביקורת שאינה מתאימה), מתוך {_int(n)} רשויות."


def insight_hp_code(df):
    n = len(df)
    if n < 10:
        return None
    m = int(df["hp_embeds"].sum())
    if m / n < 0.3:
        return None
    s = (f"ב-{_int(m)} מתוך {_int(n)} הרשויות ({_pct(m / n)}) מספר הח״פ בנוי מסמל הרשות: "
         f"הקידומת 5002, אחריה סמל הרשות בארבע ספרות ולבסוף ספרת ביקורת")
    none_types = []
    for t, g in df.groupby("type", sort=False):
        if len(g) >= 5 and int(g["hp_embeds"].sum()) == 0:
            none_types.append((t, len(g)))
    none_types.sort(key=lambda x: _type_key(x[0]))
    if none_types:
        t, k = none_types[0]
        s += f". אצל אף אחת מ-{_int(k)} הרשויות מסוג {t} אין התאמה כזו"
    return s + "."


def insight_gaps(df):
    parts = []
    nd = df[df["district"] == NO_DISTRICT]
    if len(nd) == 1:
        parts.append(f"לרשומה אחת ({nd['name'].iloc[0]}) חסר שיוך מחוזי")
    elif len(nd) > 1:
        parts.append(f"ל-{_int(len(nd))} רשומות חסר שיוך מחוזי")
    bad = df[~df["prefix_ok"]]
    if len(bad) == 1:
        r = bad.iloc[0]
        parts.append(f"ברשומה אחת ({r['name']}) השם המלא, \"{r['long']}\", אינו תואם את "
                     f"הסיווג \"{r['type']}\"")
    elif len(bad) > 1:
        parts.append(f"ב-{_int(len(bad))} רשומות השם המלא אינו תואם את סוג הרשות")
    if not parts:
        return None
    return "פערים קטנים בנתונים: " + "; ".join(parts) + "."


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["authorities"])
    total = int(len(df))
    types = sorted(df["type"].unique().tolist(), key=_type_key)
    by_type = df["type"].value_counts().reindex(types).fillna(0).astype(int)

    by_district = (df["district"].value_counts().sort_index()
                   .sort_values(ascending=False, kind="stable"))
    # Unassigned bucket always last.
    if NO_DISTRICT in by_district.index:
        by_district = pd.concat([by_district.drop(NO_DISTRICT),
                                 by_district.loc[[NO_DISTRICT]]])
    districts = list(by_district.index)
    n_districts = int(sum(1 for d in districts if d != NO_DISTRICT))

    xt = (pd.crosstab(df["district"], df["type"])
          .reindex(index=districts, columns=types).fillna(0).astype(int))

    # ── charts ──
    type_names = [_plural(t) for t in types]
    ch_types = {"names": type_names, "values": [int(v) for v in by_type]}
    ch_districts = {"names": districts, "values": [int(v) for v in by_district]}
    ch_mix = {
        "districts": districts,
        "series": [{"name": _plural(t), "values": [int(v) for v in xt[t]]} for t in types],
        "totals": [int(v) for v in xt.sum(axis=1)],
    }
    shares = []
    for t in types:
        vals = []
        for d in districts:
            s = int(xt.loc[d].sum())
            vals.append(round(float(xt.loc[d, t]) / s * 100, 1) if s else 0.0)
        shares.append({"name": _plural(t), "values": vals})
    ch_share = {"districts": districts, "series": shares}

    tree = []
    for d in districts:
        sub = df[df["district"] == d]
        kids = []
        for t in types:
            g = sub[sub["type"] == t].sort_values(["name", "hp"], kind="stable")
            if len(g) == 0:
                continue
            kids.append({
                "name": _plural(t),
                "children": [{"name": r["name"], "value": 1,
                              "code": "" if pd.isna(r["code"]) else str(int(r["code"]))}
                             for _, r in g.iterrows()],
            })
        tree.append({"name": d, "children": kids})

    # Code ranges per type.
    code_rows = []
    for t in types:
        c = df.loc[df["type"] == t, "code"].dropna()
        if len(c):
            code_rows.append([_plural(t), _int(len(c)), str(int(c.min())), str(int(c.max()))])

    # Quality checks.
    hp_valid = int(df["hp_ok"].sum())
    hp_embeds = int(df["hp_embeds"].sum())
    prefix_ok = int(df["prefix_ok"].sum())
    with_district = int((df["district"] != NO_DISTRICT).sum())
    dup_code = int(df["code"].dropna().duplicated().sum())
    dup_hp = int(df.loc[df["hp"] != "", "hp"].duplicated().sum())
    quality_rows = [
        ["מספר ח״פ תקין (תשע ספרות וספרת ביקורת מתאימה)", _int(hp_valid), _pct(hp_valid / total) if total else "0.0%"],
        ["מספר ח״פ הבנוי מסמל הרשות", _int(hp_embeds), _pct(hp_embeds / total) if total else "0.0%"],
        ["שם מלא התואם את סוג הרשות", _int(prefix_ok), _pct(prefix_ok / total) if total else "0.0%"],
        ["רשומה עם שיוך מחוזי", _int(with_district), _pct(with_district / total) if total else "0.0%"],
    ]
    hp_share = hp_valid / total if total else 0.0

    # Per-district name lists.
    lists = []
    for d in districts:
        sub = df[df["district"] == d]
        groups = []
        for t in types:
            names = sorted(sub.loc[sub["type"] == t, "name"].tolist())
            if names:
                groups.append({"type": _plural(t), "count": _int(len(names)), "names": names})
        lists.append({"district": _district_label(d), "count": _int(len(sub)), "groups": groups})

    # ── insights ──
    rules = [
        ("type_mix", insight_type_mix(by_type, total)),
        ("top_district", insight_top_district(by_district, xt, total)),
        ("city_share", insight_city_share(xt)),
        ("regional", insight_regional(xt)),
        ("hp_code", insight_hp_code(df)),
        ("hp", insight_hp(df)),
        ("gaps", insight_gaps(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    def cnt(t):
        return int(by_type.get(t, 0))

    # ── text ──
    type_phrase = ", ".join(f"{_int(v)} {_plural(t)}" for t, v in by_type.items())
    summary = (f"איתור רשות מקומית לפי שם, סמל רשות או מספר ח״פ: {_int(total)} רשויות "
               f"({type_phrase}) ב-{_int(n_districts)} מחוזות.")
    lede = (f"רשימת השלטון המקומי בישראל מאגדת {_int(total)} רשויות מקומיות: {type_phrase}. "
            f"לכל רשות מופיעים סמל רשות, מספר ח״פ ברשות המסים, השם המלא והמחוז שאליו היא משויכת.")

    top_d = districts[0] if districts else ""
    types_table = {"headers": ["סוג רשות", "מספר רשויות", "שיעור"],
                   "rows": [[_plural(t), _int(v), _pct(v / total) if total else "0.0%"]
                            for t, v in by_type.items()]}
    districts_table = {"headers": ["מחוז", "מספר רשויות", "שיעור"],
                       "rows": [[d, _int(v), _pct(v / total) if total else "0.0%"]
                                for d, v in by_district.items()]}
    mix_table = {"headers": ["מחוז"] + type_names + ["סה״כ"],
                 "rows": [[d] + [_int(v) for v in xt.loc[d]] + [_int(xt.loc[d].sum())]
                          for d in districts]}
    share_table = {"headers": ["מחוז"] + type_names,
                   "rows": [[d] + [f"{s['values'][i]:.1f}%" for s in shares]
                            for i, d in enumerate(districts)]}

    labels = {
        "lede": lede,
        "kpi_total": "רשויות מקומיות ברשימה",
        "kpi_city": "עיריות",
        "kpi_local": "מועצות מקומיות",
        "kpi_regional": "מועצות אזוריות",
        "kpi_districts": "מחוזות",
        "kpi_hp": "מספרי ח״פ תקינים",
        "types_note": (f"התפלגות {_int(total)} הרשויות לפי סוג."
                       + (f" הסוג הנפוץ: {_plural(by_type.idxmax())} ({_int(by_type.max())})."
                          if (by_type == by_type.max()).sum() == 1 else "")
                       if total else ""),
        "types_aria": (f"תרשים טבעת: רשויות מקומיות לפי סוג. {type_phrase}."),
        "districts_note": (f"מספר הרשויות בכל מחוז. {_district_label(top_d)} מוביל עם "
                           f"{_int(by_district.iloc[0])} רשויות."
                           + (f" רשומות ללא מחוז מוצגות בנפרד ({NO_DISTRICT})."
                              if NO_DISTRICT in districts else "")) if districts else "",
        "districts_aria": (f"תרשים עמודות אופקי: מספר הרשויות לפי מחוז. "
                           f"המוביל: {top_d} עם {_int(by_district.iloc[0])}.") if districts else "",
        "mix_note": "כמה עיריות, מועצות מקומיות ומועצות אזוריות יש בכל מחוז. לחיצה על המקרא מסתירה או מציגה סוג.",
        "mix_aria": (f"תרשים עמודות מוערמות: מספר הרשויות בכל אחד מ-{_int(len(districts))} "
                     f"המחוזות, מפולח לפי סוג רשות."),
        "share_note": "אותם נתונים כשיעור מתוך רשויות המחוז: מחוזות עירוניים לעומת מחוזות שבהם רוב הרשויות הן מועצות.",
        "share_aria": "תרשים עמודות מוערמות של מאה אחוז: הרכב סוגי הרשויות בכל מחוז.",
        "tree_note": (f"כל {_int(total)} הרשויות לפי מחוז וסוג. לחיצה על מלבן מתמקדת בו "
                      f"ומציגה את שמות הרשויות; לחיצה על \"כל הרשויות\" בשורת הניווט שמתחת מחזירה לתצוגה המלאה."),
        "tree_aria": (f"מפת עץ: {_int(total)} רשויות מקומיות מקובצות לפי מחוז ולפי סוג רשות."),
        "codes_note": "הסמל הנמוך והגבוה בכל סוג רשות, ומספר הרשויות שלהן סמל במאגר.",
        "codes_cap": "טווח סמלי הרשות לפי סוג רשות",
        "quality_note": (f"בדיקות עקביות שחושבו על {_int(total)} הרשומות."
                         + (f" נמצאו {_int(dup_code)} סמלים כפולים." if dup_code else " אין סמלי רשות כפולים.")
                         + (f" נמצאו {_int(dup_hp)} מספרי ח״פ כפולים." if dup_hp else " אין מספרי ח״פ כפולים.")),
        "quality_cap": "בדיקות עקביות נתוני הרשויות",
        "lists_note": "שמות כל הרשויות, לפי מחוז וסוג. לחיצה על מחוז פותחת את הרשימה.",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל ואזור יהודה והשומרון",
        },
        "kpis": {
            "total": {"value": total, "display": _int(total), "tone": "brand"},
            "city": {"value": cnt("עירייה"), "display": _int(cnt("עירייה")), "tone": "brand"},
            "local": {"value": cnt("מועצה מקומית"), "display": _int(cnt("מועצה מקומית")), "tone": "brand"},
            "regional": {"value": cnt("מועצה אזורית"), "display": _int(cnt("מועצה אזורית")), "tone": "brand"},
            "districts": {"value": n_districts, "display": _int(n_districts), "tone": "info"},
            "hp": {"value": round(hp_share, 4), "display": _pct(hp_share),
                   "tone": "ok" if hp_share >= 0.999 else ("warn" if hp_share >= 0.95 else "danger")},
        },
        "charts": {
            "types": ch_types,
            "districts": ch_districts,
            "mix": ch_mix,
            "share": ch_share,
            "tree": tree,
        },
        "tables": {
            "types": types_table,
            "districts": districts_table,
            "mix": mix_table,
            "share": share_table,
            "codes": {"headers": ["סוג רשות", "רשויות עם סמל", "סמל נמוך", "סמל גבוה"],
                      "rows": code_rows},
            "quality": {"headers": ["בדיקה", "רשומות", "שיעור"], "rows": quality_rows},
        },
        "lists": lists,
        "insights": insights,
        "labels": labels,
    }
