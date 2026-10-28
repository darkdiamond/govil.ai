"""רשימת ישובים בישראל — the Population and Immigration Authority's localities list.

One row per locality (~1.3k): locality code, Hebrew and Latin name, sub-district
(נפה) code and name, the Authority bureau (לשכת מנא) that serves its residents,
and the regional council it belongs to (code 0 / empty = none: cities, local
councils and unaffiliated places such as Bedouin tribes). The whole list is
republished on each update, so the page is a snapshot of the current list.

Inputs
- `main`: the updating list with Hebrew headers (5c78e9fa). Its English-header
  twin (8f714b6f) carries the identical rows and is not read.
- `snapshot`: the older list published in the same dataset, in two near-identical
  copies (d4901968, ef1c8e7f — same codes, two names differ). Matched by the
  `טבלה` column that only the old layout has, and pooled: a code counts as
  "in the earlier list" if any copy has it, and a name is a rename only if no
  copy carries the current name. The old files have padded fields and
  mirrored parentheses (")שבט("); both are normalised before comparing.

Districts (מחוז) are derived from the first digit of the sub-district code, the
standard CBS/Population Registry coding (1 Jerusalem … 7 Judea and Samaria);
an unknown digit falls into "אחר".

Each bureau's "home district" is the district most of its localities sit in
(ties → lower district code); a locality served by a bureau whose home district
differs from its own counts as served across district lines.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
TOP_COUNCILS = 15
TOP_BUREAUS = 15
TOP_WORDS = 15
MIN_WORD = 3
TOP_RENAMES = 15
CROSS_MIN_SHARE = 0.3
CROSS_MIN_N = 20

DISTRICTS = {
    "1": "ירושלים",
    "2": "הצפון",
    "3": "חיפה",
    "4": "המרכז",
    "5": "תל אביב",
    "6": "הדרום",
    "7": "יהודה והשומרון",
}
OTHER_DISTRICT = "אחר"
NO_COUNCIL = "ללא מועצה אזורית"
_FLIP = str.maketrans("()", ")(")
TRIBE_TAG = "(שבט)"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def share(a, b, digits=1):
    return pct(a / b * 100, digits) if b else pct(0, digits)


def _clean(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    # The old layout (and some sub-district names) mirror parentheses:
    # "אבו ג'ווייעד )שבט(". Flip them only when the first one is ")".
    m = re.search(r"[()]", s)
    if m and m.group(0) == ")":
        s = s.translate(_FLIP)
    return s


def _code(s):
    v = pd.to_numeric(s.str.strip(), errors="coerce")
    return v


def _ranked(s):
    """Counts sorted descending, ties broken by label."""
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _district_of(nafa_code):
    c = str(nafa_code).strip()
    return DISTRICTS.get(c[:1], OTHER_DISTRICT) if c and c != "0" else OTHER_DISTRICT


def _district_order():
    return list(DISTRICTS.values()) + [OTHER_DISTRICT]


def _prepare(raw):
    code = _code(raw["סמל_ישוב"])
    df = pd.DataFrame({
        "code": code.values,
        "name": raw["שם_ישוב"].map(_clean).values,
        "latin": raw["שם_ישוב_לועזי"].map(_clean).values,
        "nafa_code": raw["סמל_נפה"].str.strip().values,
        "nafa": raw["שם_נפה"].map(_clean).values,
        "bureau_code": raw["סמל_לשכת_מנא"].str.strip().values,
        "bureau": raw["לשכה"].map(_clean).values,
        "council_code": raw["סמל_מועצה_איזורית"].str.strip().values,
        "council": raw["שם_מועצה"].map(_clean).values,
    })
    df = df[df["code"].notna() & (df["code"] > 0) & (df["name"] != "")].copy()
    df["code"] = df["code"].astype(int)
    df = df.sort_values("code", kind="stable").drop_duplicates("code").reset_index(drop=True)
    df["district"] = df["nafa_code"].map(_district_of)
    df.loc[df["nafa"] == "", "nafa"] = "לא ידוע"
    df.loc[df["bureau"] == "", "bureau"] = "לא ידוע"
    in_c = (df["council"] != "") & (pd.to_numeric(df["council_code"], errors="coerce").fillna(0) > 0)
    df["in_council"] = in_c
    df.loc[~in_c, "council"] = NO_COUNCIL
    df["tribe"] = df["name"].str.contains(TRIBE_TAG, regex=False)
    df["word"] = df["name"].str.replace(r"\([^)]*\)", "", regex=True).str.strip().str.split(" ").str[0]
    return df


def _prepare_old(raw):
    code = _code(raw["סמל_ישוב"])
    old = pd.DataFrame({
        "code": code.values,
        "name": raw["שם_ישוב"].map(_clean).values,
        "nafa_code": raw["סמל_נפה"].str.strip().values,
    })
    placeholder = int((old["code"].fillna(0) <= 0).sum())
    old = old[old["code"].notna() & (old["code"] > 0) & (old["name"] != "")].copy()
    old["code"] = old["code"].astype(int)
    old["district"] = old["nafa_code"].map(_district_of)
    return old, placeholder


# ---------------------------------------------------------------- insights

def insight_nafa(nafa_counts, total):
    if len(nafa_counts) < 3:
        return None
    (a, va), (b, vb), (c, vc) = list(nafa_counts.items())[:3]
    if va <= vb:
        return None
    return (f"נפת {a} מרכזת את מספר הישובים הגדול ביותר — {n(va)} ישובים "
            f"({share(va, total)} מהרשימה), ואחריה נפות {b} ({n(vb)}) ו{c} ({n(vc)}).")


def insight_councils(df, council_counts):
    total = len(df)
    k = int(df["in_council"].sum())
    if not len(council_counts) or k == 0:
        return None
    no = total - k
    tribes_no = int((df["tribe"] & ~df["in_council"]).sum())
    (a, va) = list(council_counts.items())[0]
    lead = ""
    if len(council_counts) > 1:
        b, vb = list(council_counts.items())[1]
        if va > vb:
            lead = f" הגדולה שבהן היא {a}, עם {n(va)} ישובים, לפני {b} ({n(vb)})."
    tail = ""
    if tribes_no:
        tail = f" מתוך {n(no)} הישובים שאינם במועצה אזורית, {n(tribes_no)} הם שבטים בדואיים."
    return (f"{n(k)} ישובים ({share(k, total)}) משויכים לאחת מ-{n(len(council_counts))} "
            f"מועצות אזוריות.{lead}{tail}")


def insight_cross(cross_rows):
    cand = [r for r in cross_rows if r["n"] >= CROSS_MIN_N and r["cross"] / r["n"] >= CROSS_MIN_SHARE]
    if not cand:
        return None
    r = sorted(cand, key=lambda x: (-x["cross"] / x["n"], x["order"]))[0]
    tb = r["top_bureau"]
    tail = f"; לשכת {tb[0]} לבדה משרתת {n(tb[1])} מהם" if tb else ""
    return (f"מתוך {n(r['n'])} הישובים במחוז {r['district']}, {n(r['cross'])} ({share(r['cross'], r['n'])}) "
            f"משויכים ללשכה של רשות האוכלוסין שנמצאת במחוז אחר{tail}.")


def insight_changes(ch):
    if ch is None or (ch["added"] == 0 and ch["removed"] == 0):
        return None
    a, r = ch["added"], ch["removed"]
    net = a - r
    if net > 0:
        net_t = f"גידול נטו של {n(net)}"
    elif net < 0:
        net_t = f"ירידה נטו של {n(-net)}"
    else:
        net_t = "ללא שינוי נטו"
    lead = ""
    if a and ch["top_added"]:
        d, v = ch["top_added"]
        if v / a >= 0.5:
            lead = f" {n(v)} מהישובים שנוספו ({share(v, a, 0)}) נמצאים במחוז {d}."
    return (f"לעומת הקובץ הקודם שפורסם במאגר ({n(ch['old_total'])} ישובים), ברשימה הנוכחית "
            f"נוספו {n(a)} סמלי ישוב והוסרו {n(r)} — {net_t}.{lead}")


def insight_renames(renames):
    if not renames:
        return None
    ex = renames[:2]
    ex_t = " ו".join(f"{x['old']} ← {x['new']}" for x in ex)
    word = "ישוב אחד שינה את שמו" if len(renames) == 1 else f"{n(len(renames))} ישובים שינו את שמם"
    return f"{word} מאז הקובץ הקודם, כשסמל הישוב נשמר — למשל {ex_t}."


def insight_words(word_counts, total):
    if len(word_counts) < 3:
        return None
    (a, va), (b, vb), (c, vc) = list(word_counts.items())[:3]
    if va <= vb or va < MIN_WORD:
        return None
    return (f"״{a}״ היא המילה הפותחת הנפוצה ביותר בשמות הישובים — {n(va)} שמות "
            f"({share(va, total)}), לפני ״{b}״ ({n(vb)}) ו״{c}״ ({n(vc)}).")


def insight_latin(df):
    miss = int((df["latin"] == "").sum())
    lat = df[df["latin"] != ""]
    dup_names = lat.groupby("latin").size()
    dup = int((dup_names > 1).sum())
    if miss == 0 and dup == 0:
        return None
    parts = []
    if miss:
        parts.append(f"{n(miss)} ישובים מופיעים ללא שם לועזי")
    if dup:
        parts.append(f"{n(dup)} שמות לועזיים משותפים לשני ישובים או יותר")
    return "באיכות הנתונים: " + "; ".join(parts) + " — סמל הישוב הוא המזהה החד-ערכי."


def insight_tribes(df):
    t = df[df["tribe"]]
    if len(t) < 5:
        return None
    by = _ranked(t.groupby("nafa").size())
    a, va = by.index[0], int(by.iloc[0])
    where = (f"כולם בנפת {a}" if va == len(t)
             else f"{n(va)} מהם בנפת {a}")
    return f"ברשימה {n(len(t))} ישובים המסומנים כשבט — {where}."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    order = [d for d in _district_order() if d in set(df["district"])]
    order_idx = {d: i for i, d in enumerate(_district_order())}

    # Districts, split by regional-council membership.
    dist_in = df[df["in_council"]].groupby("district").size()
    dist_out = df[~df["in_council"]].groupby("district").size()
    dist_rows = []
    for d in order:
        a, b = int(dist_in.get(d, 0)), int(dist_out.get(d, 0))
        dist_rows.append({"name": d, "in": a, "out": b, "total": a + b,
                          "share": share(a + b, total)})
    districts_chart = {
        "names": order,
        "in": [r["in"] for r in dist_rows],
        "out": [r["out"] for r in dist_rows],
    }

    # Sub-districts.
    nafa_counts = _ranked(df.groupby("nafa").size())
    nafa_dist = df.groupby("nafa")["district"].first()
    n_in = df[df["in_council"]].groupby("nafa").size()
    nafa_rows = []
    for nm, v in nafa_counts.items():
        a = int(n_in.get(nm, 0))
        nafa_rows.append({"name": nm, "district": nafa_dist[nm], "total": int(v),
                          "in": a, "out": int(v) - a})
    nafot_chart = {
        "names": [r["name"] for r in nafa_rows],
        "in": [r["in"] for r in nafa_rows],
        "out": [r["out"] for r in nafa_rows],
    }

    # Regional councils.
    council_counts = _ranked(df[df["in_council"]].groupby("council").size())
    council_dist = (df[df["in_council"]].groupby(["council", "district"]).size()
                    .reset_index(name="k")
                    .sort_values(["council", "k", "district"], ascending=[True, False, True], kind="stable")
                    .drop_duplicates("council").set_index("council")["district"])
    council_nafot = df[df["in_council"]].groupby("council")["nafa"].nunique()
    top_c = council_counts.head(TOP_COUNCILS)
    councils_chart = {
        "names": list(top_c.index),
        "values": [int(v) for v in top_c.values],
    }
    council_rows = [{"name": c, "district": council_dist[c], "count": int(v),
                     "nafot": int(council_nafot[c])} for c, v in top_c.items()]
    multi_nafa = int((council_nafot > 1).sum())

    # Treemap: district → sub-district → regional council (or none).
    tree = []
    g3 = df.groupby(["district", "nafa", "council"]).size()
    for d in order:
        kids = []
        sub = g3.loc[d]
        for nf in _ranked(sub.groupby(level=0).sum()).index:
            leaves = _ranked(sub.loc[nf])
            kids.append({"name": nf, "children": [
                {"name": c, "value": int(v)} for c, v in leaves.items()]})
        tree.append({"name": d, "children": kids})

    # Bureaus: count by district; home district = modal district.
    bd = df.groupby(["bureau", "district"]).size().reset_index(name="k")
    bd["o"] = bd["district"].map(order_idx)
    modal = (bd.sort_values(["bureau", "k", "o"], ascending=[True, False, True], kind="stable")
             .drop_duplicates("bureau").set_index("bureau")["district"])
    # A bureau named after a locality sits in that locality's district.
    by_name = df.drop_duplicates("name").set_index("name")["district"]
    home = pd.Series({b: by_name.get(b, modal[b]) for b in modal.index})
    n_namesake = int(sum(1 for b in modal.index if b in by_name.index))
    bureau_counts = _ranked(df.groupby("bureau").size())
    top_b = list(bureau_counts.index[:TOP_BUREAUS])
    rest_b = list(bureau_counts.index[TOP_BUREAUS:])
    bmat = bd.pivot_table(index="bureau", columns="district", values="k", fill_value=0, aggfunc="sum")
    names_b = top_b + (["אחר"] if rest_b else [])
    series_b = []
    for d in order:
        col = bmat[d] if d in bmat.columns else pd.Series(dtype=int)
        vals = [int(col.get(b, 0)) for b in top_b]
        if rest_b:
            vals.append(int(sum(int(col.get(b, 0)) for b in rest_b)))
        series_b.append({"name": d, "data": vals, "ci": order_idx[d]})
    bureau_rows = []
    for b in top_b:
        bureau_rows.append({"name": b, "count": int(bureau_counts[b]), "home": home[b],
                            "districts": int((bmat.loc[b] > 0).sum())})
    if rest_b:
        bureau_rows.append({"name": f"אחר ({n(len(rest_b))} לשכות)",
                            "count": int(bureau_counts[rest_b].sum()), "home": "—",
                            "districts": int((bmat.loc[rest_b].sum() > 0).sum())})
    bureaus_chart = {"names": names_b, "series": series_b}

    df["home"] = df["bureau"].map(home)
    df["cross"] = df["home"] != df["district"]
    cross_rows = []
    for d in order:
        sub = df[df["district"] == d]
        cs = sub[sub["cross"]]
        tb = None
        if len(cs):
            bc = _ranked(cs.groupby("bureau").size())
            tb = (bc.index[0], int(bc.iloc[0]))
        cross_rows.append({"district": d, "n": len(sub), "cross": int(len(cs)),
                           "order": order_idx[d], "top_bureau": tb})
    n_cross = int(df["cross"].sum())

    # Name words.
    wc = _ranked(df.groupby("word").size())
    wc = wc[wc >= MIN_WORD].head(TOP_WORDS)
    words_chart = {"names": list(wc.index), "values": [int(v) for v in wc.values]}
    word_rows = [{"name": w, "count": int(v), "share": share(int(v), total)} for w, v in wc.items()]

    # Comparison with the earlier list.
    old, placeholder = _prepare_old(frames["snapshot"])
    ch = None
    renames = []
    if len(old):
        old_codes = set(old["code"])
        cur_codes = set(df["code"])
        added = df[~df["code"].isin(old_codes)]
        removed = (old[~old["code"].isin(cur_codes)]
                   .sort_values(["code", "district"], kind="stable").drop_duplicates("code"))
        ad = added.groupby("district").size()
        rd = removed.groupby("district").size()
        ch_order = [d for d in _district_order() if d in set(ad.index) | set(rd.index)]
        ch_rows = [{"name": d, "added": int(ad.get(d, 0)), "removed": int(rd.get(d, 0))}
                   for d in ch_order]
        top_added = None
        if len(ad):
            ar = _ranked(ad)
            top_added = (ar.index[0], int(ar.iloc[0]))
        old_names = old.groupby("code")["name"].agg(lambda s: sorted(set(s)))
        both = df[df["code"].isin(old_codes)]
        for code, nm in zip(both["code"], both["name"]):
            prev = old_names[code]
            if nm not in prev and nm.replace(" ", "") not in [p.replace(" ", "") for p in prev]:
                renames.append({"code": int(code), "old": " / ".join(prev), "new": nm})
        renames.sort(key=lambda x: x["code"])
        ch = {
            "old_total": int(old["code"].nunique()),
            "added": int(len(added)), "removed": int(len(removed)),
            "top_added": top_added, "rows": ch_rows,
            "added_councils": [{"name": c, "count": int(v)} for c, v in
                               _ranked(added.groupby("council").size()).head(10).items()],
        }
    changes_chart = None
    if ch and ch["rows"]:
        changes_chart = {
            "names": [r["name"] for r in ch["rows"]],
            "added": [r["added"] for r in ch["rows"]],
            "removed": [-r["removed"] for r in ch["rows"]],
        }

    # KPIs.
    k_in = int(df["in_council"].sum())
    net = (ch["added"] - ch["removed"]) if ch else 0
    if net > 0:
        net_disp, net_tone = f"+{n(net)}", "info"
    elif net < 0:
        net_disp, net_tone = f"−{n(-net)}", "info"
    else:
        net_disp, net_tone = "0", "brand"
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "council_share": {"value": round(k_in / total * 100, 1) if total else 0,
                          "display": f"{k_in / total * 100:.1f}%" if total else "0%",
                          "tone": "info"},
        "councils": {"value": int(len(council_counts)), "display": n(len(council_counts)),
                     "tone": "brand"},
        "net": {"value": net, "display": net_disp, "tone": net_tone},
    }

    insights = []
    for iid, txt in [
        ("nafa", insight_nafa(nafa_counts, total)),
        ("councils", insight_councils(df, council_counts)),
        ("cross", insight_cross(cross_rows)),
        ("changes", insight_changes(ch)),
        ("renames", insight_renames(renames)),
        ("tribes", insight_tribes(df)),
        ("words", insight_words(wc, total)),
        ("latin", insight_latin(df)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    # Labels.
    top_nafa = nafa_rows[0] if nafa_rows else {"name": "", "total": 0}
    top_dist = sorted(dist_rows, key=lambda r: (-r["total"], order_idx[r["name"]]))[0]
    labels = {
        "lede": (f"רשות האוכלוסין וההגירה מפרסמת את רשימת הישובים המוכרים במרשם האוכלוסין: "
                 f"{n(total)} ישובים, כל אחד עם סמל ישוב ייחודי, שם בעברית ובלועזית, ושיוך "
                 f"ל-{n(len(nafa_counts))} נפות, ל-{n(df['bureau'].nunique())} לשכות של הרשות "
                 f"ול-{n(len(council_counts))} מועצות אזוריות. העמוד מציג את פריסת הישובים, "
                 f"את מבנה השיוך המנהלי שלהם ואת השינויים לעומת הקובץ הקודם שפורסם במאגר."),
        "total_kpi": "ישובים ברשימה",
        "share_kpi": "שיעור הישובים במועצה אזורית",
        "councils_kpi": "מועצות אזוריות",
        "net_kpi": "שינוי נטו לעומת הקובץ הקודם במאגר",
        "districts_note": (f"המחוז נגזר מסמל הנפה. מחוז {top_dist['name']} מוביל עם "
                           f"{n(top_dist['total'])} ישובים ({top_dist['share']}); בכל מחוז מוצג "
                           f"הפיצול בין ישובים שבמועצה אזורית לבין ישובים שאינם במועצה אזורית."),
        "districts_aria": (f"גרף עמודות מוערמות: מספר הישובים לפי מחוז. מחוז {top_dist['name']} מוביל עם "
                           f"{n(top_dist['total'])} ישובים."),
        "districts_caption": "מספר הישובים לפי מחוז ושיוך למועצה אזורית",
        "nafot_note": (f"{n(len(nafa_counts))} נפות, מהגדולה לקטנה. נפת {top_nafa['name']} מובילה עם "
                       f"{n(top_nafa['total'])} ישובים; בנפות העירוניות רוב הישובים אינם במועצה אזורית."),
        "nafot_aria": (f"גרף עמודות אופקי מוערם: מספר הישובים בכל אחת מ-{n(len(nafa_counts))} הנפות. "
                       f"נפת {top_nafa['name']} מובילה עם {n(top_nafa['total'])} ישובים."),
        "nafot_caption": "מספר הישובים לפי נפה ושיוך למועצה אזורית",
        "councils_note": (f"{n(len(top_c))} המועצות האזוריות עם מספר הישובים הגדול ביותר, מתוך "
                          f"{n(len(council_counts))}. "
                          f"{n(multi_nafa)} מועצות משתרעות על פני יותר מנפה אחת."),
        "councils_aria": (f"גרף עמודות אופקי: {n(len(top_c))} המועצות האזוריות הגדולות לפי מספר ישובים. "
                          + (f"{top_c.index[0]} מובילה עם {n(top_c.iloc[0])} ישובים." if len(top_c) else "")),
        "councils_caption": "המועצות האזוריות הגדולות לפי מספר ישובים",
        "tree_note": ("מבנה השיוך המלא: מחוז, נפה ומועצה אזורית (או ״ללא מועצה אזורית״). גודל כל "
                      "מלבן הוא מספר הישובים; לחיצה על מלבן מתמקדת בו."),
        "tree_aria": (f"מפת עץ: {n(total)} ישובים לפי מחוז, נפה ומועצה אזורית. "
                      f"מחוז {top_dist['name']} הוא הגדול ביותר."),
        "bureaus_note": (f"הלשכה של רשות האוכלוסין וההגירה שמשרתת את תושבי כל ישוב, צבועה לפי מחוז "
                         f"הישוב. מחוז הלשכה הוא מחוז הישוב שעל שמו היא קרויה ({n(n_namesake)} "
                         f"מתוך {n(len(modal))} לשכות), ואם אין ישוב כזה — המחוז שבו רוב ישוביה. "
                         f"{n(n_cross)} ישובים ({share(n_cross, total)}) משויכים ללשכה במחוז אחר."),
        "bureaus_aria": (f"גרף עמודות אופקי מוערם: מספר הישובים לפי לשכת רשות האוכלוסין ומחוז הישוב. "
                         f"לשכת {bureau_counts.index[0]} משרתת את המספר הגדול ביותר, {n(bureau_counts.iloc[0])} ישובים."),
        "bureaus_caption": "מספר הישובים לפי לשכת רשות האוכלוסין",
        "words_note": (f"המילה הראשונה בשם הישוב (ללא תוספות בסוגריים), למילים שמופיעות "
                       f"ב-{n(MIN_WORD)} שמות לפחות."),
        "words_aria": ("גרף עמודות אופקי: המילים הנפוצות בפתיחת שמות הישובים. "
                       + (f"״{wc.index[0]}״ מובילה עם {n(wc.iloc[0])} שמות." if len(wc) else "")),
        "words_caption": "המילים הנפוצות בפתיחת שמות הישובים",
    }
    if ch:
        excl = (f" רשומת מציין-מקום ללא סמל ישוב בקובץ הקודם אינה נספרת." if placeholder else "")
        labels.update({
            "changes_note": (f"סמלי ישוב שמופיעים רק ברשימה הנוכחית (נוספו) או רק בקובץ הקודם "
                             f"({n(ch['old_total'])} ישובים, הוסרו), לפי מחוז.{excl}"),
            "changes_aria": (f"גרף עמודות: ישובים שנוספו ({n(ch['added'])}) ושהוסרו ({n(ch['removed'])}) "
                             f"לעומת הקובץ הקודם, לפי מחוז."),
            "changes_caption": "ישובים שנוספו והוסרו לעומת הקובץ הקודם, לפי מחוז",
            "added_caption": "המועצות האזוריות שאליהן נוספו הכי הרבה ישובים",
            "renames_note": (f"ישובים שסמלם נשמר אך שמם שונה מהשם בקובץ הקודם ({n(len(renames))})."
                             + (f" מוצגים {n(TOP_RENAMES)} הראשונים לפי סמל ישוב." if len(renames) > TOP_RENAMES else "")),
            "renames_caption": "ישובים ששמם שונה לעומת הקובץ הקודם",
        })

    temporal = None
    agent_data = {
        "summary_he": (f"רשימת {n(total)} הישובים במרשם האוכלוסין, עם סמל ישוב, נפה, לשכת רשות "
                       f"האוכלוסין ומועצה אזורית: {share(k_in, total)} מהישובים במועצה אזורית, "
                       f"ונפת {top_nafa['name']} הגדולה ביותר ({n(top_nafa['total'])} ישובים)."),
        "dataset_kind": "registry",
        "suggested_tags": ["ישובים", "מרשם אוכלוסין", "נפות", "מועצות אזוריות",
                           "לשכות רשות האוכלוסין", "שמות ישובים"],
        "related_ids": [
            "d2581732-eca4-4988-b986-df8e791a1d60",
            "00172ee8-4433-4d5d-8fd4-11f0f08ce5c4",
            "9d86c8a9-9240-4fc4-86a3-834c539f9488",
            "785ad9fb-6da6-426d-b5ea-b8e36febbc8a",
            "7c27e23b-86f1-44ee-9d9b-4f8880ca0973",
        ],
        "spatial_coverage": "ישראל ויהודה והשומרון",
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "districts": districts_chart,
            "nafot": nafot_chart,
            "councils": councils_chart,
            "tree": tree,
            "bureaus": bureaus_chart,
            "words": words_chart,
            "changes": changes_chart,
        },
        "insights": insights,
        "labels": labels,
        "tables": {
            "districts": dist_rows,
            "nafot": nafa_rows,
            "councils": council_rows,
            "bureaus": bureau_rows,
            "words": word_rows,
            "changes": ch["rows"] if ch else [],
            "added_councils": ch["added_councils"] if ch else [],
            "renames": renames[:TOP_RENAMES],
        },
        "flags": {"changes": bool(changes_chart), "renames": bool(renames)},
    }
