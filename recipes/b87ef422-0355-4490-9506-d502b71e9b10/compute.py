"""יבואני מזון בעלי תעודות רישום יבואן בתוקף — Ministry of Health food-importer registry.

One row per valid importer-registration certificate (~3.1k, refreshed
several times a day: certificates are added and expire). A business can hold
several certificates of different types (regular / alcoholic beverages /
veterinary / "from the region"), so the registry is analysed at two levels:
certificates (rows) and holders (distinct `tz` — the company / dealer number).

`tz` is used ONLY as a grouping key and for an aggregate legal-form split by
its corporate-number prefix; it is never shown (for sole traders it is a
personal ID). Business names may appear (commercial capacity); only
corporations are listed by name. Street addresses are never shown — the
settlement is extracted from the free-text address for city aggregates.

`Regnum` is a running registration number, used as a proxy for how long ago
a holder was first registered (low = older). `naut` / `trust` are yes/no
flags whose meaning the dataset does not document; they are not used.
"""
import re
from collections import Counter

import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"
TOP_CITIES = 15
MIX_CITIES = 10
TOP_MULTI = 15
MAX_BANDS = 20

LEGAL = [("אגודה שיתופית", r'אגודה|אגש"ח|אגש״ח|אגשח'),
         ("חברה בע״מ", r'בע"מ|בעמ|בע״מ|בע\'\'מ|\bltd\b'),
         ("שותפות", r'שותפות|ש"מ\b'),
         ("עמותה / חל״צ", r'עמותה|ע"ר|חל"צ|חל״צ')]
# Israeli corporate-number prefixes (fallback when the name carries no suffix).
LEGAL_PREFIX = {"51": "חברה בע״מ", "52": "חברה בע״מ", "55": "שותפות",
                "57": "אגודה שיתופית", "58": "עמותה / חל״צ"}
LEGAL_NONE = "ללא ציון צורה משפטית"
CORP_FORMS = {"חברה בע״מ", "אגודה שיתופית", "שותפות", "עמותה / חל״צ"}

NAME_THEMES = [
    ("יבוא", r"יבוא|ייבוא|אימפורט|אימפורטס|יבואן"),
    ("שיווק, סחר והפצה", r"שיווק|שווק|סחר|מסחר|הפצה|טרייד|טריידינג|סחורות|ממכר"),
    ("מזון", r"מזון|פוד|פודס|מעדנ"),
    ("בינלאומי / גלובלי", r"בינלאומי|אינטרנשיונל|אינטרנשונל|גלובל|עולמי|אירופ"),
    ("תעשייה וייצור", r"תעשיות|תעשייה|תעשיה|מפעל|ייצור|יצור"),
    ("פירות, ירקות ותוצרת חקלאית", r"פירות|פרי|ירקות|ירק|חקלא|תוצרת|גידולי"),
    ("משקאות ויין", r"משקא|יין|יינות|וויין|בירה|ליקר|אלכוהול|ספיריט|מים"),
    ("קפה ותה", r"קפה|קופי|תה\b|טי\b"),
    ("לוגיסטיקה", r"לוגיסטיק|הובלה|שילוח|מחסנ"),
]

# Spelling variants of the same settlement.
CITY_CANON = {
    "תל אביב": "תל אביב-יפו", "תל אביב -יפו": "תל אביב-יפו", "תל אביב יפו": "תל אביב-יפו",
    "תל-אביב": "תל אביב-יפו", "פתח תקווה": "פתח תקוה", "נצרת עילית": "נצרת עלית",
    "אם אל-פחם": "אום אל-פחם", "מעלה אדמים": "מעלה אדומים", "קרית אתא": "קריית אתא",
    "קרית גת": "קריית גת", "קרית מלאכי": "קריית מלאכי", "קרית שמונה": "קריית שמונה",
    "קרית ביאליק": "קריית ביאליק", "קרית ים": "קריית ים", "קרית אונו": "קריית אונו",
    "קרית מוצקין": "קריית מוצקין", "קרית עקרון": "קריית עקרון", "הרצלייה": "הרצליה",
}
NO_CITY = "לא זוהה"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _legal(name, tz):
    for label, pat in LEGAL:
        if re.search(pat, name, flags=re.I):
            return label
    return LEGAL_PREFIX.get(tz[:2], LEGAL_NONE)


# ---------- settlement from free-text address ----------
_PO = re.compile(r"ת\s*\.?\s*ד\s*\.?\s*\d*")
_ZIP = re.compile(r"\d{5,7}")


def _addr_tokens(a):
    a = _PO.sub(" ", a)
    a = _ZIP.sub(" ", a)
    a = a.replace(",", " ").replace("-יפו", " -יפו")
    t = a.split()
    while t and re.fullmatch(r"[\d\-/.]+", t[-1]):
        t.pop()
    return t


def _city_vocab(tok_lists):
    """Settlement names learned from the data itself.

    `dup`: a trailing phrase written twice ("רהט רהט" — the registry's
    street-city-city pattern) — authoritative. `tail`: counts of trailing
    phrases with no digits, used when no doubled phrase matches."""
    dup = set()
    tail = Counter()
    for t in tok_lists:
        for k in (3, 2, 1):
            if len(t) >= 2 * k and t[-2 * k:-k] == t[-k:]:
                dup.add(" ".join(t[-k:]))
                break
        for k in (1, 2, 3):
            if len(t) >= k:
                w = t[-k:]
                if k > 1 and w[0] == w[-1]:
                    continue                      # "גן רמת גן", "יבנה יבנה"
                s = " ".join(w)
                if not re.search(r"\d", s):
                    tail[s] += 1
    return dup, tail


def _city(t, vocab):
    dup, tail = vocab
    pick = None
    for k in (3, 2, 1):
        if len(t) >= k and " ".join(t[-k:]) in dup:
            pick = " ".join(t[-k:])
            break
    if pick is None:
        for k in (3, 2, 1):
            if len(t) < k:
                continue
            s = " ".join(t[-k:])
            c = tail.get(s, 0)
            if c < 4:
                continue
            shorter = " ".join(t[-(k - 1):]) if k > 1 else None
            if shorter and tail.get(shorter, 0) > 2 * c:
                continue                          # "חולדה בית שמש" → "בית שמש"
            pick = s
            break
    if pick is None:
        return NO_CITY
    return CITY_CANON.get(pick, pick)


# ---------- preparation ----------
def _prepare(df):
    out = pd.DataFrame({
        "regnum": pd.to_numeric(df["Regnum"].str.strip(), errors="coerce"),
        "name": df["importer_name"].str.strip().str.replace(r"\s+", " ", regex=True),
        "type": df["importer_type_name"].str.strip().replace("", "לא צוין"),
        "tz": df["tz"].str.strip().str.replace(r"\D", "", regex=True),
    })
    out["tz"] = out["tz"].where(out["tz"] == "", out["tz"].str.zfill(9))
    # Holder key: the dealer / company number; name when it is missing.
    out["holder"] = out["tz"].where(out["tz"] != "", "name:" + out["name"])
    toks = [_addr_tokens(a) for a in df["Address"].tolist()]
    vocab = _city_vocab(toks)
    out["city"] = [_city(t, vocab) for t in toks]
    out["legal"] = [_legal(a, b) for a, b in zip(out["name"], out["tz"])]
    return out


def _band_width(max_reg):
    w = 1000
    while (max_reg // w) + 1 > MAX_BANDS:
        w *= 2
    return w


# ---------- insights ----------
def insight_types(types, total):
    lead, c = types.index[0], int(types.iloc[0])
    share = c / total
    if share < 0.4:
        return None
    rest = [f"{t} ({n(v)})" for t, v in types.iloc[1:].items()]
    return (f"רוב התעודות בתוקף הן מסוג «{lead}» — {n(c)} מתוך {n(total)} ({pct(share * 100)}); "
            f"שאר התעודות מתחלקות בין " + ", ".join(rest) + ".")


def insight_multi(holders_n, multi_n, combo_top, combo_top_n):
    if holders_n == 0 or multi_n / holders_n < 0.03 or combo_top is None:
        return None
    return (f"{n(holders_n)} מחזיקים שונים רשומים במרשם, ו־{n(multi_n)} מהם ({pct(multi_n / holders_n * 100)}) "
            f"מחזיקים ביותר מתעודה אחת. הצירוף השכיח ביותר: {combo_top} ({n(combo_top_n)} מחזיקים).")


def insight_new_track(t, total_regs):
    """A specialised type whose numbers cluster at the top of the range."""
    if t is None:
        return None
    return (f"תעודות «{t['type']}» הן מסלול חדש יחסית: {pct(t['share_t'] * 100)} מהן "
            f"נושאות מספר רישום {n(t['floor'])} ומעלה, לעומת {pct(t['share_reg'] * 100)} "
            f"מתעודות «{t['ref']}».")


def insight_cities(cities, known, total):
    if known < total * 0.5 or len(cities) < 3:
        return None
    top = cities.iloc[:3]
    share = top.sum() / known
    names = ", ".join(f"{c} ({n(v)})" for c, v in top.items())
    return (f"שלושת היישובים המובילים — {names} — מרכזים יחד {pct(share * 100)} מהתעודות "
            f"שהיישוב שלהן זוהה מתוך הכתובת ({n(known)} מתוך {n(total)}); השאר פזורות "
            f"ב־{n(len(cities) - 3)} יישובים נוספים.")


def insight_type_city(mix_c, ct, cities, types, total):
    """Cities whose type mix departs most from the registry-wide mix.

    Lift = a type's share of a city's certificates / its share overall; only
    types holding ≥3% of all certificates, cells of ≥10 certificates, and a
    lift of ≥1.8. Reports the strongest city, plus the strongest for a second
    type when it also qualifies."""
    cand = []
    for t in types.index:
        base = types[t] / total
        if base < 0.03:
            continue
        for c in mix_c:
            v = int(ct.get((c, t), 0))
            if v < 10:
                continue
            share = v / int(cities[c])
            lift = share / base
            if lift >= 1.8:
                cand.append((-lift, t, c, share, base))
    if not cand:
        return None
    cand.sort()
    first = cand[0]
    second = next((x for x in cand[1:] if x[1] != first[1] and x[2] != first[2]), None)

    def part(x):
        return (f"ב{x[2]} {pct(x[3] * 100)} מהתעודות הן «{x[1]}», "
                f"פי {-x[0]:.1f} משיעורן בכלל המרשם ({pct(x[4] * 100)})")
    txt = "התמהיל משתנה בין היישובים: " + part(first)
    if second:
        txt += "; " + part(second)
    return txt + "."


def insight_legal(legal, holders_n):
    if holders_n == 0:
        return None
    top, c = legal.index[0], int(legal.iloc[0])
    if c / holders_n < 0.5:
        return None
    none = int(legal.get(LEGAL_NONE, 0))
    tail = (f"; {n(none)} ({pct(none / holders_n * 100)}) רשומים ללא צורה משפטית מזוהה — "
            f"ככל הנראה עוסקים יחידים." if none else ".")
    return f"{pct(c / holders_n * 100)} ממחזיקי התעודות ({n(c)}) הם בצורת «{top}»{tail}"


# ---------- compute ----------
def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    reg = df.dropna(subset=["regnum"]).copy()
    reg["regnum"] = reg["regnum"].astype(int)

    # Types
    types = _sorted_counts(df["type"])
    type_order = list(types.index)
    ref_type = type_order[0]

    # Holders
    hold = (df.sort_values(["holder", "type", "regnum"], kind="stable")
              .groupby("holder", sort=True)
              .agg(types=("type", lambda s: " + ".join(sorted(s.unique()))),
                   n=("type", "size"), name=("name", "first"), legal=("legal", "first")))
    holders_n = len(hold)
    multi = hold[hold["n"] > 1]
    combos = _sorted_counts(multi["types"]) if len(multi) else pd.Series(dtype=int)
    legal = _sorted_counts(hold["legal"])

    # Bands of registration numbers
    max_reg = int(reg["regnum"].max()) if len(reg) else 0
    width = _band_width(max_reg)
    reg["band"] = (reg["regnum"] // width) * width
    bands = sorted(reg["band"].unique().tolist())
    band_lbl = [f"{n(b)}–{n(b + width - 1)}" for b in bands]
    band_start = [n(b) for b in bands]     # axis labels (a range label flips under RTL)
    bt = reg.groupby(["band", "type"]).size()
    band_series = [{"name": t, "data": [int(bt.get((b, t), 0)) for b in bands]} for t in type_order]
    band_tot = reg.groupby("band").size()

    rr = reg[reg["type"] == ref_type]

    # A newer specialised track: ≥80% of its numbers above a band floor that
    # holds ≤50% of the reference type.
    new_track = None
    for t in type_order[1:]:
        g = reg[reg["type"] == t]["regnum"]
        if len(g) < 30:
            continue
        p10 = int(g.quantile(0.10, interpolation="lower"))
        floor = (p10 // 1000) * 1000
        share_t = float((g >= floor).mean())
        share_reg = float((rr["regnum"] >= floor).mean()) if len(rr) else 1.0
        if share_t >= 0.8 and share_reg <= 0.5:
            cand = {"type": t, "floor": floor, "share_t": share_t, "share_reg": share_reg, "ref": ref_type}
            if new_track is None or share_t - share_reg > new_track["share_t"] - new_track["share_reg"]:
                new_track = cand

    # Cities
    known = df[df["city"] != NO_CITY]
    cities = _sorted_counts(known["city"])
    top_c = list(cities.index[:TOP_CITIES])
    ct = known.groupby(["city", "type"]).size()
    city_series = [{"name": t, "data": [int(ct.get((c, t), 0)) for c in top_c]} for t in type_order]
    rest_c = int(cities.iloc[TOP_CITIES:].sum())
    mix_c = list(cities.index[:MIX_CITIES])
    mix_series = []
    for t in type_order:
        row = []
        for c in mix_c:
            tot_c = int(cities[c])
            row.append(round(int(ct.get((c, t), 0)) / tot_c * 100, 1) if tot_c else 0)
        mix_series.append({"name": t, "data": row})
    allmix = [round(int(types[t]) / total * 100, 1) for t in type_order]
    unknown_city = total - len(known)

    # Name themes (per holder, multi-label)
    themes = []
    for label, pat in NAME_THEMES:
        c = int(hold["name"].str.contains(pat, regex=True).sum())
        themes.append((label, c))
    themes.sort(key=lambda x: (-x[1], x[0]))
    themes = [t for t in themes if t[1] > 0]
    any_theme = int(hold["name"].apply(lambda s: any(re.search(p, s) for _, p in NAME_THEMES)).sum())

    # Holders with the most certificates — corporations only
    corp = hold[hold["legal"].isin(CORP_FORMS) & (hold["n"] > 1)]
    corp = corp.reset_index().sort_values(["n", "name", "holder"], ascending=[False, True, True], kind="stable")
    top_multi = corp.head(TOP_MULTI)
    max_n = int(hold["n"].max()) if holders_n else 0
    n_at_max = int((hold["n"] == max_n).sum())

    # ---------- KPIs ----------
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "holders": {"value": holders_n, "display": n(holders_n), "tone": "brand"},
        "cities": {"value": int(len(cities)), "display": n(len(cities)), "tone": "brand"},
        "multi": {"value": int(len(multi)), "display": n(len(multi)), "tone": "brand"},
    }

    # ---------- charts ----------
    charts = {
        "types": {"names": type_order, "values": [int(types[t]) for t in type_order]},
        "bands": {"x": band_start, "series": band_series},
        "combos": {"names": list(combos.index), "values": [int(v) for v in combos.values]},
        "legal": {"names": list(legal.index), "values": [int(v) for v in legal.values]},
        "cities": {"names": top_c, "series": city_series},
        "mix": {"names": ["כלל התעודות"] + mix_c,
                "series": [{"name": s["name"], "data": [allmix[i]] + s["data"]}
                           for i, s in enumerate(mix_series)]},
        "themes": {"names": [t[0] for t in themes], "values": [t[1] for t in themes]},
    }

    tables = {
        "types": [{"name": t, "count": n(types[t]), "share": pct(types[t] / total * 100)} for t in type_order],
        "type_names": type_order,
        "bands": [{"band": band_lbl[i], "cells": [n(s["data"][i]) for s in band_series],
                   "total": n(band_tot.get(b, 0))} for i, b in enumerate(bands)],
        "combos": [{"name": k, "count": n(v)} for k, v in combos.items()],
        "legal": [{"name": k, "count": n(v), "share": pct(v / holders_n * 100)} for k, v in legal.items()],
        "cities": [{"name": c, "cells": [n(s["data"][i]) for s in city_series], "total": n(cities[c])}
                   for i, c in enumerate(top_c)],
        "mix": [{"name": nm, "cells": [pct(s["data"][i]) for s in charts["mix"]["series"]]}
                for i, nm in enumerate(charts["mix"]["names"])],
        "themes": [{"name": t[0], "count": n(t[1]), "share": pct(t[1] / holders_n * 100)} for t in themes],
        "multi": [{"name": r["name"], "n": n(r["n"]), "types": r["types"].replace(" + ", " · ")} for _, r in top_multi.iterrows()],
    }

    # ---------- insights ----------
    insights = [
        ("types", insight_types(types, total)),
        ("multi", insight_multi(holders_n, len(multi),
                                combos.index[0] if len(combos) else None,
                                int(combos.iloc[0]) if len(combos) else 0)),
        ("new_track", insight_new_track(new_track, total)),
        ("cities", insight_cities(cities, len(known), total)),
        ("type_city", insight_type_city(mix_c, ct, cities, types, total)),
        ("legal", insight_legal(legal, holders_n)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in insights if t]

    # ---------- labels ----------
    lead_city = cities.index[0] if len(cities) else ""
    labels = {
        "lede": (f"מרשם תעודות רישום היבואן של שירות המזון הארצי במשרד הבריאות: {n(total)} תעודות בתוקף, "
                 f"המוחזקות בידי {n(holders_n)} יבואנים ומשווקים. התעודה היא תנאי מקדים ליבוא מזון לישראל, "
                 f"והיא ניתנת ב־{n(len(type_order))} מסלולים — {', '.join(type_order)}. הדף מציג את חלוקת המסלולים, "
                 f"את ותק הרישומים לפי מספר הרישום, את מחזיקי התעודות המרובות ואת פריסתם לפי יישוב."),
        "total_kpi": "תעודות רישום בתוקף",
        "holders_kpi": "יבואנים ומשווקים (מחזיקים ייחודיים)",
        "cities_kpi": "יישובים שזוהו בכתובות",
        "multi_kpi": "מחזיקים ביותר מתעודה אחת",
        "types_note": (f"«{ref_type}» הוא המסלול הכללי ({pct(types[ref_type] / total * 100)} מהתעודות)."
                       + (" «מהאזור» הוא מרשם המשווקים המורשים להביא מזון מהרשות הפלסטינית."
                        if "מהאזור" in type_order else "")),
        "types_aria": f"תעודות רישום לפי סוג יבואן; הסוג המוביל {ref_type} עם {n(types[ref_type])} תעודות",
        "bands_note": (f"מספרי הרישום ניתנים ברצף, ולכן מספר נמוך מעיד בדרך כלל על יבואן שנרשם מזמן. "
                       f"כל עמודה היא טווח של {n(width)} מספרים, המסומן במספר הפותח אותו; הגובה הוא מספר התעודות מהטווח שעדיין בתוקף. "
                       f"{n(int(band_tot.iloc[-1]) if len(band_tot) else 0)} תעודות בטווח העליון "
                       f"({band_lbl[-1] if band_lbl else ''}), שעדיין מתמלא."),
        "bands_aria": f"תעודות בתוקף לפי טווחי מספר רישום של {n(width)}, מוערמות לפי סוג יבואן",
        "combos_note": (f"{n(len(multi))} מחזיקים (לפי מספר עוסק או חברה) מחזיקים בכמה תעודות מסוגים שונים; "
                        f"המרבי הוא {n(max_n)} תעודות ({n(n_at_max)} מחזיקים)."),
        "combos_aria": "מחזיקי תעודות מרובות לפי צירוף סוגי התעודות",
        "legal_note": (f"לפי סיומת השם (בע״מ, אגודה שיתופית וכו׳) או קידומת מספר התאגיד, ברמת מחזיק "
                       f"({n(holders_n)} מחזיקים)."),
        "legal_aria": f"מחזיקי תעודות לפי צורה משפטית; המובילה {legal.index[0] if len(legal) else ''}",
        "cities_note": (f"היישוב חולץ מכתובת הטקסט החופשי של כל תעודה; ל־{n(unknown_city)} תעודות לא זוהה יישוב "
                        f"והן אינן נכללות. {n(len(top_c))} היישובים המובילים מוצגים; עוד {n(rest_c)} תעודות "
                        f"פזורות ב־{n(max(len(cities) - len(top_c), 0))} יישובים נוספים."),
        "cities_aria": f"היישובים עם מספר התעודות הגבוה ביותר; המוביל {lead_city}",
        "mix_note": (f"שיעור כל סוג תעודה ב־{n(len(mix_c))} היישובים המובילים, לעומת כלל התעודות "
                     f"(השורה העליונה)."),
        "mix_aria": "תמהיל סוגי התעודות לפי יישוב, באחוזים",
        "themes_note": (f"מילים שמופיעות בשמות {n(holders_n)} המחזיקים (שם אחד יכול להתאים לכמה נושאים); "
                        f"{n(any_theme)} שמות ({pct(any_theme / holders_n * 100 if holders_n else 0)}) "
                        f"מתאימים לפחות לנושא אחד."),
        "themes_aria": "נושאים נפוצים בשמות היבואנים",
        "multi_note": (f"תאגידים (חברות, אגודות ושותפויות) המחזיקים ביותר מתעודה אחת, לפי מספר התעודות ובסדר "
                       f"אלפביתי; מוצגים {n(len(top_multi))} מתוך {n(len(corp))}."),
    }

    return {
        "agent_data": {
            "summary_he": (f"מרשם יבואני המזון של משרד הבריאות: {n(total)} תעודות רישום יבואן בתוקף בידי "
                           f"{n(holders_n)} יבואנים ומשווקים, לפי סוג תעודה ({', '.join(type_order)}), "
                           f"ותק הרישום, צורה משפטית ויישוב."),
            "dataset_kind": "registry",
            "related_ids": ["5a5aa50a-58b4-40e7-98d7-4630d76947d5",
                            "246d949c-a253-4811-8a11-41a137d3d613",
                            "9f0ea3dc-2e25-43f0-9b8f-10f53e23c335"],
            "suggested_tags": ["יבוא מזון", "יבואני מזון", "רישום יבואן", "שירות המזון הארצי",
                               "עסקי מזון", "משקאות משכרים"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
