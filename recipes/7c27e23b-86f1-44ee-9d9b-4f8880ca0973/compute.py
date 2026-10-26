"""רשימת ארצות מוכרות ע"י מדינת ישראל — the Population and Immigration
Authority's country-code table.

One row per code (~260): a numeric country code (סמל_ארץ), the Hebrew name and
the English name. It is the code table the population registry uses for
country of birth, citizenship and the like, so besides today's states it keeps
codes for entities that no longer exist (the USSR, Yugoslavia, the two
Germanys …) and "general" codes (an unknown country per continent, "rest of
Asia", "on the way to Israel", "at sea").

Inputs
- `main`: the updating list (c84082e9).
- `snapshot`: the older list published in the same dataset — four byte-identical
  copies (65cc0bc5, efbf54ae, a876fc51, 34021591), matched by the `טבלה`
  column only the old layout has, and pooled by code. Old fields are padded
  with spaces; whitespace is collapsed before comparing.

Code blocks. The codes are allocated in hundreds-blocks by region (0xx west
Asia, 1xx south and east Asia, 2xx Africa, 3xx former USSR, 4xx the Balkans,
5xx–6xx Europe, 700–859 America, 860–899 Oceania, 9xx Israel and special
codes). The region shown is the block the code falls in; a code outside the
known blocks lands in "אחר".

General codes are detected from the name (unknown / rest-of / status
keywords, a continent name on its own, or an empty/"-" name). Historical
entities are a fixed list of codes, each tagged only while the English name
still matches, with the successor codes that exist in the current list.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"

BLOCKS = [  # (lo, hi, name) — inclusive code ranges
    (1, 99, "מערב אסיה"),
    (100, 199, "דרום ומזרח אסיה"),
    (200, 299, "אפריקה"),
    (300, 399, "ברית המועצות לשעבר"),
    (400, 499, "הבלקן"),
    (500, 699, "מרכז ומערב אירופה"),
    (700, 859, "אמריקה"),
    (860, 899, "אוקיאניה"),
    (900, 999, "ישראל וקודים מיוחדים"),
]
ZERO_BLOCK = "סמל אפס"
OTHER_BLOCK = "אחר"

GENERAL_KEYS = ["לא ידוע", "לא רשום", "שאר ארצות", "בדרך לארץ", "בלב ים"]
CONTINENTS = {"אסיה", "אפריקה", "אירופה", "אמריקה", "מרכז אמריקה", "דרום אמריקה",
              "צפון אמריקה", "אוקיאניה"}

# code: (English-name token that must still match, what happened, successor codes)
DISSOLVED, MERGED, SPLIT, RENAMED = "התפרקה", "צורפה", "חולקה", "שם קודם"
HISTORICAL = {
    71: ("PEOPLE'S DEMO", MERGED, [70]),
    80: ("ADEN", MERGED, [70]),
    113: ("SIKKIM", MERGED, [110]),
    126: ("SOUTH VIETNAM", MERGED, [125]),
    132: ("PORTUGUESE TIMOR", RENAMED, [136]),
    151: ("KOREA", SPLIT, [152, 153]),
    201: ("TANGIER", MERGED, [200]),
    202: ("SPANISH MOROCCO", MERGED, [200]),
    260: ("RODESIA", RENAMED, [259]),
    273: ("SWAZILAND", RENAMED, [291]),
    300: ("USSR", DISSOLVED, [9, 301, 302, 303, 304, 305, 306, 307, 308, 309,
                              311, 312, 313, 314, 315, 316]),
    410: ("YUGOSLAVIA", DISSOLVED, [411, 412, 413, 415, 416, 418]),
    414: ("FYROM", RENAMED, [418]),
    501: ("W GERMANY", MERGED, [500]),
    502: ("E GERMANY", MERGED, [500]),
    530: ("CZECHOSLOVAKIA", DISSOLVED, [531, 532]),
    741: ("CANAL ZONE", MERGED, [740]),
    762: ("ANTILLES", DISSOLVED, []),
    863: ("HEBRIDES", RENAMED, [871]),
    883: ("WESTERN SAMOA", RENAMED, [882]),
    885: ("GILBERT", DISSOLVED, [873, 872]),
}
KIND_ORDER = [DISSOLVED, SPLIT, MERGED, RENAMED]
_FLIP = str.maketrans("()", ")(")
MIN_ISLANDS = 5


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def share(a, b, digits=1):
    return pct(a / b * 100, digits) if b else pct(0, digits)


def _clean(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    m = re.search(r"[()]", s)
    if m and m.group(0) == ")":
        s = s.translate(_FLIP)
    return s


def _block(code):
    if code == 0:
        return ZERO_BLOCK
    for lo, hi, nm in BLOCKS:
        if lo <= code <= hi:
            return nm
    return OTHER_BLOCK


def _block_order():
    return [ZERO_BLOCK] + [b[2] for b in BLOCKS] + [OTHER_BLOCK]


def _is_general(name):
    if name in ("", "-") or name in CONTINENTS:
        return True
    return any(k in name for k in GENERAL_KEYS)


def _frame(raw):
    df = pd.DataFrame({
        "code": pd.to_numeric(raw["סמל_ארץ"].str.strip(), errors="coerce").values,
        "name": raw["שם_ארץ"].map(_clean).values,
        "eng": raw["ארץ_באנגלית"].map(_clean).values,
    })
    df = df[df["code"].notna() & (df["code"] >= 0)].copy()
    df["code"] = df["code"].astype(int)
    df = (df.sort_values(["code", "name", "eng"], kind="stable")
          .drop_duplicates("code").reset_index(drop=True))
    return df


def _ranked(s):
    return s.sort_index().sort_values(ascending=False, kind="stable")


# ---------------------------------------------------------------- insights

def insight_blocks(block_rows, total):
    rows = [r for r in block_rows if r["block"] not in (ZERO_BLOCK, OTHER_BLOCK)]
    rows = sorted(rows, key=lambda r: (-r["total"], r["order"]))
    if len(rows) < 3 or rows[0]["total"] <= rows[1]["total"]:
        return None
    a, b, c = rows[:3]
    return (f"גוש {a['block']} (סמלים {a['range']}) מחזיק את מספר הסמלים הגדול ביותר — "
            f"{n(a['total'])} ({share(a['total'], total)} מהרשימה), לפני {b['block']} "
            f"({n(b['total'])}) ו{c['block']} ({n(c['total'])}).")


def insight_historical(hist_rows, total):
    if len(hist_rows) < 3:
        return None
    big = sorted(hist_rows, key=lambda r: (-r["n_succ"], r["code"]))[0]
    tail = ""
    if big["n_succ"] >= 3:
        tail = (f" הבולטת שבהן: {big['name']} (סמל {big['code']}), שמופיעה לצד "
                f"{n(big['n_succ'])} המדינות שקמו במקומה.")
    return (f"{n(len(hist_rows))} סמלים ({share(len(hist_rows), total)}) שייכים לישויות שכבר אינן "
            f"קיימות או לשמות קודמים של מדינות, והם נשמרים ברשימה לצד המדינות שבאו "
            f"במקומן.{tail}")


def insight_changes(ch):
    if ch is None or (ch["added"] == 0 and ch["removed"] == 0):
        return None
    a, r = ch["added"], ch["removed"]
    ex = ""
    if ch["added_rows"]:
        names = [x["name"] for x in ch["added_rows"][:3]]
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " ו" + names[-1]
        ex = (" — ביניהם " if a > len(names) else ": ") + joined
    rem = f"; הוסרו {n(r)}" if r else "; לא הוסר אף סמל"
    return (f"לעומת הקובץ הקודם שפורסם במאגר ({n(ch['old_total'])} סמלים), ברשימה הנוכחית "
            f"נוספו {n(a)} סמלים{ex}{rem}.")


def insight_general(gen, total):
    if len(gen) < 3:
        return None
    unk = int(gen["name"].str.contains("לא ידוע", regex=False).sum())
    rest = int(gen["name"].str.contains("שאר ארצות", regex=False).sum())
    parts = []
    if unk:
        parts.append(f"{n(unk)} סמלי ״לא ידוע״")
    if rest:
        parts.append(f"{n(rest)} סמלי ״שאר ארצות״")
    status = [k for k in ("בדרך לארץ", "בלב ים") if (gen["name"] == k).any()]
    if status:
        parts.append("מצבים כמו " + " ו".join(f"״{k}״" for k in status))
    detail = (" — " + ", ".join(parts[:-1]) + (" ו" if len(parts) > 1 else "") + parts[-1]) if parts else ""
    return (f"{n(len(gen))} סמלים ({share(len(gen), total)}) אינם ארץ מסוימת אלא קודים כלליים"
            f"{detail}.")


def insight_shared_eng(df):
    lat = df[(df["eng"] != "") & (df["eng"] != "-")]
    g = lat.groupby("eng")["code"].apply(lambda s: sorted(s))
    dup = g[g.map(len) > 1].sort_index()
    miss = df[df["eng"] == ""]
    if not len(dup) and not len(miss):
        return None
    parts = []
    if len(dup):
        ex = []
        for eng, codes in list(dup.items())[:2]:
            nm = df.set_index("code").loc[codes, "name"].tolist()
            ex.append(f"{eng} משמש גם ל{nm[0]} ({codes[0]}) וגם ל{nm[1]} ({codes[1]})")
        parts.append(f"{n(len(dup))} שמות לועזיים משותפים ליותר מסמל אחד ({'; '.join(ex)})")
    if len(miss):
        r = miss.iloc[0]
        one = f"{r['name']} ({r['code']})" if len(miss) == 1 else f"{n(len(miss))} סמלים"
        parts.append(f"ל{one} אין שם לועזי")
    return "באיכות הנתונים: " + "; ".join(parts) + " — הסמל המספרי הוא המזהה החד-ערכי."


def insight_islands(df):
    isl = df[df["name"].str.startswith("איי ")]
    if len(isl) < MIN_ISLANDS:
        return None
    by = _ranked(isl.groupby("block").size())
    a, va = by.index[0], int(by.iloc[0])
    if len(by) > 1 and va <= int(by.iloc[1]):
        return None
    return (f"{n(len(isl))} שמות ברשימה פותחים במילה ״איי״ — ארכיפלגים וטריטוריות "
            f"איים; {n(va)} מהם בגוש {a}.")


def insight_former_names(df):
    m = df[df["name"].str.contains(r"\(", regex=True)]
    if len(m) < 2:
        return None
    ex = [f"{r['name']}" for _, r in m.head(3).iterrows()]
    return (f"{n(len(m))} שמות עבריים נושאים בסוגריים את שמה הקודם של המדינה — "
            + ", ".join(ex) + ".")


def insight_codes(cell_rows, total):
    if not cell_rows:
        return None
    full = [c for c in cell_rows if c["count"] == 10]
    used = len(cell_rows)
    tail = ""
    if full:
        f0 = full[0]
        tail = (f" {n(len(full))} עשרות מלאות לגמרי, למשל {f0['lo']} עד {f0['hi']}." if len(full) > 1
                else f" העשרת {f0['lo']} עד {f0['hi']} מלאה לגמרי.")
    return (f"הרשימה משתמשת ב-{n(total)} סמלים מתוך טווח של אלף, ב-{n(used)} עשרות שונות — "
            f"ובכל גוש נותרו סמלים פנויים להוספת ארצות.{tail}")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _frame(frames["main"])
    total = len(df)
    order = _block_order()
    order_idx = {b: i for i, b in enumerate(order)}
    df["block"] = df["code"].map(_block)
    df["general"] = df["name"].map(_is_general)
    by_code = df.set_index("code")

    # Historical entities still present (English name must still match).
    hist_rows = []
    for code in sorted(HISTORICAL):
        token, kind, succ = HISTORICAL[code]
        if code not in by_code.index or token not in by_code.at[code, "eng"].upper():
            continue
        present = [c for c in succ if c in by_code.index]
        hist_rows.append({
            "code": code, "name": by_code.at[code, "name"], "eng": by_code.at[code, "eng"],
            "kind": kind, "succ_codes": present,
            "n_succ": len({by_code.at[c, "eng"] or by_code.at[c, "name"] for c in present}),
            "succ": ", ".join(by_code.at[c, "name"] for c in present) if present else "—",
        })
    hist_rows.sort(key=lambda r: (KIND_ORDER.index(r["kind"]), r["code"]))
    hist_codes = {r["code"] for r in hist_rows}
    df["historical"] = df["code"].isin(hist_codes)
    df["kind"] = "country"
    df.loc[df["historical"], "kind"] = "historical"
    df.loc[df["general"], "kind"] = "general"

    # Blocks.
    blocks_present = [b for b in order if b in set(df["block"])]
    g = df.groupby(["block", "kind"]).size()
    block_rows = []
    for b in blocks_present:
        sub = df[df["block"] == b]
        cnt = {k: int(g.get((b, k), 0)) for k in ("country", "historical", "general")}
        rng = f"{int(sub['code'].min())} עד {int(sub['code'].max())}"
        block_rows.append({"block": b, "order": order_idx[b], "range": rng,
                           "total": int(len(sub)), **cnt,
                           "share": share(len(sub), total)})
    blocks_chart = {
        "names": [r["block"] for r in block_rows],
        "country": [r["country"] for r in block_rows],
        "historical": [r["historical"] for r in block_rows],
        "general": [r["general"] for r in block_rows],
    }

    # Code-space heatmap: hundreds × tens.
    df["h"] = df["code"] // 100
    df["t"] = (df["code"] % 100) // 10
    cells = []
    info = []
    cell_rows = []
    for (h, t), sub in df[df["code"] <= 999].groupby(["h", "t"]):
        sub = sub.sort_values("code", kind="stable")
        names = ", ".join(f"{c} {nm or '—'}" for c, nm in zip(sub["code"], sub["name"]))
        lo = int(h) * 100 + int(t) * 10
        cells.append([int(t), int(h), int(len(sub))])
        info.append({"range": f"{lo} עד {lo + 9}", "names": names})
        cell_rows.append({"lo": lo, "hi": lo + 9, "count": int(len(sub))})
    cell_rows.sort(key=lambda r: r["lo"])
    codes_chart = {
        "x": [str(t * 10) for t in range(10)],
        "y": [str(h * 100) for h in range(10)],
        "cells": cells,
        "info": info,
        "max": max([c[2] for c in cells] or [1]),
    }
    densest = sorted(cell_rows, key=lambda r: (-r["count"], r["lo"]))[0] if cell_rows else None

    # Comparison with the earlier list.
    old = _frame(frames["snapshot"])
    ch = None
    if len(old):
        old_i = old.set_index("code")
        added = df[~df["code"].isin(set(old["code"]))]
        removed = old[~old["code"].isin(set(df["code"]))]
        both = df[df["code"].isin(set(old["code"]))]
        renamed, eng_changed = [], []
        for code, nm, eng in zip(both["code"], both["name"], both["eng"]):
            on, oe = old_i.at[code, "name"], old_i.at[code, "eng"]
            if nm != on:
                renamed.append({"code": int(code), "old": on or "—", "new": nm or "—"})
            if eng != oe:
                eng_changed.append({"code": int(code), "name": nm, "old": oe or "—", "new": eng or "—"})
        # Whitespace-only fixes: raw strings differ but the cleaned ones match.
        raw_old = (frames["snapshot"].assign(code=pd.to_numeric(frames["snapshot"]["סמל_ארץ"].str.strip(), errors="coerce"))
                   .dropna(subset=["code"]))
        raw_old["code"] = raw_old["code"].astype(int)
        raw_old = raw_old.sort_values(["code", "ארץ_באנגלית"], kind="stable").drop_duplicates("code").set_index("code")
        raw_cur = frames["main"].assign(code=pd.to_numeric(frames["main"]["סמל_ארץ"].str.strip(), errors="coerce")).dropna(subset=["code"])
        raw_cur["code"] = raw_cur["code"].astype(int)
        raw_cur = raw_cur.sort_values(["code", "ארץ_באנגלית"], kind="stable").drop_duplicates("code").set_index("code")
        ws_fix = 0
        changed_codes = {r["code"] for r in eng_changed}
        for code in sorted(both["code"]):
            if code in changed_codes:
                continue
            if raw_old.at[code, "ארץ_באנגלית"].strip() != raw_cur.at[code, "ארץ_באנגלית"].strip():
                ws_fix += 1
        ch = {
            "old_total": int(len(old)), "added": int(len(added)), "removed": int(len(removed)),
            "added_rows": [{"code": int(c), "name": nm or "—", "eng": e or "—", "block": b}
                           for c, nm, e, b in zip(added["code"], added["name"], added["eng"], added["block"])],
            "removed_rows": [{"code": int(c), "name": nm or "—", "eng": e or "—"}
                             for c, nm, e in zip(removed["code"], removed["name"], removed["eng"])],
            "renamed": renamed, "eng_changed": eng_changed, "ws_fix": ws_fix,
        }

    gen = df[df["general"]].sort_values("code", kind="stable")
    general_rows = [{"code": int(c), "name": nm or "—", "eng": e or "—", "block": b}
                    for c, nm, e, b in zip(gen["code"], gen["name"], gen["eng"], gen["block"])]

    # KPIs.
    n_country = int((df["kind"] == "country").sum())
    n_hist = len(hist_rows)
    net = (ch["added"] - ch["removed"]) if ch else 0
    if net > 0:
        net_disp, net_tone = f"+{n(net)}", "ok"
    elif net < 0:
        net_disp, net_tone = f"−{n(-net)}", "warn"
    else:
        net_disp, net_tone = "0", "brand"
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "countries": {"value": n_country, "display": n(n_country), "tone": "brand"},
        "historical": {"value": n_hist, "display": n(n_hist), "tone": "info" if n_hist else "brand"},
        "net": {"value": net, "display": net_disp, "tone": net_tone},
    }

    insights = []
    for iid, txt in [
        ("blocks", insight_blocks(block_rows, total)),
        ("historical", insight_historical(hist_rows, total)),
        ("changes", insight_changes(ch)),
        ("general", insight_general(gen, total)),
        ("islands", insight_islands(df)),
        ("former", insight_former_names(df)),
        ("codes", insight_codes(cell_rows, total)),
        ("eng", insight_shared_eng(df)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    top_block = sorted([r for r in block_rows if r["block"] not in (ZERO_BLOCK, OTHER_BLOCK)] or block_rows,
                       key=lambda r: (-r["total"], r["order"]))[0]
    labels = {
        "lede": (f"טבלת הסמלים של רשות האוכלוסין וההגירה לארצות: {n(total)} סמלים, כל אחד עם "
                 f"שם בעברית ובאנגלית. לצד {n(n_country)} ארצות וטריטוריות היא כוללת {n(n_hist)} סמלים של ישויות "
                 f"היסטוריות ו-{n(len(gen))} קודים כלליים. העמוד מציג את מבנה המספור לפי אזורים, "
                 f"את הישויות ההיסטוריות ואת השינויים לעומת הקובץ הקודם שפורסם במאגר."),
        "total_kpi": "סמלי ארץ ברשימה",
        "countries_kpi": "ארצות וטריטוריות",
        "historical_kpi": "ישויות ושמות היסטוריים",
        "net_kpi": "שינוי נטו לעומת הקובץ הקודם במאגר",
        "blocks_note": (f"הסמלים מוקצים בגושים לפי אזור; האזור נגזר מטווח הסמל, כך שמדינה שסומנה "
                        f"בגוש של אזור אחר נספרת בו. גוש {top_block['block']} הגדול ביותר, עם "
                        f"{n(top_block['total'])} סמלים. כל עמודה מפוצלת לארצות פעילות, ישויות "
                        f"היסטוריות וקודים כלליים."),
        "blocks_aria": (f"גרף עמודות אופקי מוערם: מספר סמלי הארץ בכל גוש אזורי. גוש {top_block['block']} "
                        f"מוביל עם {n(top_block['total'])} סמלים."),
        "blocks_caption": "סמלי ארץ לפי גוש אזורי וסוג",
        "codes_note": (f"כל משבצת היא עשרה סמלים רצופים (השורה היא המאה, והעמודה היא העשרת שבתוכה); הצבע הוא מספר הסמלים "
                       f"שבשימוש. {n(len(cell_rows))} עשרות בשימוש"
                       + (f"; הצפופה ביותר היא {densest['lo']} עד {densest['hi']} עם {n(densest['count'])} סמלים"
                          if densest else "")
                       + ". מעבר עם העכבר מציג את הארצות שבמשבצת."),
        "codes_aria": (f"מפת חום: {n(total)} סמלי ארץ לפי מאות ועשרות, {n(len(cell_rows))} עשרות בשימוש."),
        "hist_note": (f"{n(n_hist)} סמלים של מדינות שהתפרקו, צורפו למדינה אחרת, חולקו או שינו את שמן, ולצדם הסמלים "
                      f"של המדינות שבאו במקומן כפי שהם מופיעים ברשימה."),
        "hist_caption": "ישויות היסטוריות ברשימה והמדינות שבאו במקומן",
        "general_note": (f"{n(len(gen))} סמלים שאינם ארץ מסוימת: ארץ לא ידועה לפי יבשת, ״שאר ארצות״, "
                         f"ומצבים מיוחדים."),
        "general_caption": "קודים כלליים ברשימה",
    }
    if ch:
        ws = (f" בנוסף, {n(ch['ws_fix'])} שמות לועזיים תוקנו רק ברווחים." if ch["ws_fix"] else "")
        labels.update({
            "changes_note": (f"הקובץ הקודם במאגר כלל {n(ch['old_total'])} סמלים; ברשימה המתעדכנת נוספו "
                             f"{n(ch['added'])} והוסרו {n(ch['removed'])}.{ws}"),
            "added_caption": "סמלים שנוספו לעומת הקובץ הקודם",
            "removed_caption": "סמלים שהוסרו לעומת הקובץ הקודם",
            "eng_caption": "שמות ששונו לעומת הקובץ הקודם",
        })

    agent_data = {
        "summary_he": (f"טבלת {n(total)} סמלי הארץ של רשות האוכלוסין וההגירה, עם שם בעברית ובאנגלית: "
                       f"{n(n_country)} ארצות וטריטוריות, {n(n_hist)} ישויות היסטוריות ו-{n(len(gen))} "
                       f"קודים כלליים, מסודרים בגושי מספור לפי אזור."),
        "dataset_kind": "registry",
        "suggested_tags": ["ארצות", "מדינות", "סמלי ארץ", "מרשם אוכלוסין", "טבלאות קוד"],
        "related_ids": [
            "3fc54b81-25b3-4ac7-87db-248c3e1602de",
            "d5f1e517-4b47-4611-b8ec-bb261bb363f7",
            "00172ee8-4433-4d5d-8fd4-11f0f08ce5c4",
            "d2581732-eca4-4988-b986-df8e791a1d60",
        ],
        "spatial_coverage": "עולם",
    }

    eng_rows = []
    if ch:
        for r in ch["renamed"]:
            eng_rows.append({"code": r["code"], "field": "עברית", "old": r["old"], "new": r["new"]})
        for r in ch["eng_changed"]:
            eng_rows.append({"code": r["code"], "field": "אנגלית", "old": r["old"], "new": r["new"]})
        eng_rows.sort(key=lambda r: (r["code"], r["field"]))

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"blocks": blocks_chart, "codes": codes_chart},
        "insights": insights,
        "labels": labels,
        "tables": {
            "blocks": block_rows,
            "historical": [{k: v for k, v in r.items() if k not in ("succ_codes", "n_succ")} for r in hist_rows],
            "general": general_rows,
            "added": ch["added_rows"] if ch else [],
            "removed": ch["removed_rows"] if ch else [],
            "changed": eng_rows,
        },
        "flags": {
            "changes": bool(ch and (ch["added"] or ch["removed"] or eng_rows)),
            "historical": bool(hist_rows),
            "general": bool(general_rows),
        },
    }
