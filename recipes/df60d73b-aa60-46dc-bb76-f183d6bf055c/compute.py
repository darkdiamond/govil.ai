"""Israel Numbering Plan: which operator holds each phone-number prefix.

Each row is one block of E.164 numbers ("+972 2 30XXXXX") allocated by the
Ministry of Communications to a licensed telephony operator. A block's size
is 10 to the power of its X count. Everything below is derived from that.
"""

import re

import pandas as pd

COL_NDC = "NDC"
COL_E164 = "E.164 Range Format"
COL_DIAL = "Dialing Within Israel"
COL_OWNER = "Allocated To"
COL_NOTES = "Notes"

# Hebrew trade names for the operators known at authoring time. Unknown
# operators fall through with their registered (English) name.
OPERATOR_HE = {
    "BEZEQ, THE ISRAELI TELECOMMUNICATIONS CORP. LTD": "בזק",
    "BEZEQ INTERNATIONAL LTD": "בזק בינלאומי",
    "CELLCOM ISRAEL LTD": "סלקום",
    "PARTNER COMMUNICATIONS COMPANY LTD": "פרטנר",
    "PELEPHONE COMMUNICATIONS LTD": "פלאפון",
    "HOT TELECOM LP": "הוט טלקום",
    "HOT MOBILE LTD": "הוט מובייל",
    "PALESTINIAN OPERATORS": "מפעילים פלסטיניים",
    "JAWWAL (PALESTINIAN MNO)": "ג׳וואל",
    "HASHIKMA N.G.N INTERNATIONAL COMMUNICATIONS 015 LTD": "השיקמה 015",
    "TELZAR 019 INTERNATIONAL TELECOMMUNICATION LTD": "טלזר 019",
    "XPHONE 018 LTD": "אקספון 018",
    "RAMI LEVY HASHIKME MARKETING COMMUNICATION LTD": "רמי לוי תקשורת",
    "WECOM MOBILE LTD": "ויקום מובייל",
    "LB ANNATEL LTD": "אנאטל",
    "CELLACT COMMUNICATION LTD": "סלאקט",
    "BINAT BUSINESS LTD": "בינת עסקים",
    "MERKAZIYA LTD": "מרכזיה",
    "PAYCALL TECHNOLOGIES LTD": "פייקול",
    "MASKYOO TELEPHONIA LTD": "מסקיו טלפוניה",
    "WIDELY MOBILE LTD": "ווידלי מובייל",
    "VOICENTER LTD": "וויסנטר",
    "YOSI COMMUNICATION LTD": "יוסי תקשורת",
    "SHAKED PROMOTION COMPANY LTD": "שקד קידום",
    "COMMUNICATION KAHALAHA LTD": "תקשורת כהלכה",
    "CLOUDONIX LTD": "קלאודוניקס",
    "KLIKOL MOBILE LTD": "קליקול מובייל",
}

NOTE_HE = {
    "PALESTINIAN AUTHORITY": "הרשות הפלסטינית",
    "M2M SERVICES": "שירותי מכונה למכונה (M2M)",
    "IOT/M2M SERVICES": "שירותי IoT ומכונה למכונה",
    "PREPAID ONLY": "כרטיס חיוב מראש בלבד",
}

# Geographic area codes (single-digit NDC). Ordering/labels only; an unknown
# NDC still flows through with a generic label.
REGION_HE = {
    "2": "ירושלים והסביבה",
    "3": "תל אביב וגוש דן",
    "4": "חיפה והצפון",
    "8": "הדרום והשפלה",
    "9": "השרון",
}

CAT_ORDER = ["mobile", "geo", "national", "iot", "other"]
CAT_HE = {
    "mobile": "נייד סלולרי",
    "geo": "נייח אזורי",
    "national": "נייח ארצי וטלפוניית אינטרנט",
    "iot": "מכשירים מחוברים ותקשורת בין מכונות",
    "other": "אחר",
}

TOP_OPS = 12
MIX_OPS = 7
NO_NOTE = "ללא ייעוד מיוחד"


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _op_he(raw):
    return OPERATOR_HE.get(raw.upper(), raw)


def _note_he(raw):
    if not raw:
        return NO_NOTE
    return NOTE_HE.get(raw.upper(), raw)


def _category(ndc):
    if len(ndc) == 1 and ndc in "23489":
        return "geo"
    if ndc.startswith("5"):
        return "mobile"
    if ndc.startswith("7"):
        return "national"
    if ndc.startswith("1"):
        return "iot"
    return "other"


def _fmt_cap(n):
    """Numbers count in Hebrew prose: 22.3 מיליון, 630,000."""
    if n >= 1_000_000:
        s = f"{n / 1_000_000:.2f}".rstrip("0").rstrip(".")
        return f"{s} מיליון"
    return f"{n:,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _pct_txt(x):
    """Share for prose: whole number when large, one decimal when small."""
    if x >= 0.995 and x < 1:
        return "99.5%"
    if x >= 0.1:
        return f"{x * 100:.0f}%"
    return f"{x * 100:.1f}%"


def _list_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    joiner = " ו-" if last[:1].isdigit() else " ו"
    return ", ".join(items[:-1]) + joiner + last


def _full_txt(labels):
    if len(labels) == 1:
        return f"הקידומת {labels[0]} מוקצית במלואה"
    return f"הקידומות {_list_he(labels)} מוקצות במלואן"


def _parse(df):
    rows = []
    bad = 0
    for ndc_raw, e164, dial, owner, note in zip(
        df[COL_NDC], df[COL_E164], df[COL_DIAL], df[COL_OWNER], df[COL_NOTES]
    ):
        ndc = re.sub(r"\D", "", str(ndc_raw))
        parts = _norm(e164).split(" ")
        sub = parts[-1] if parts else ""
        m = re.fullmatch(r"(\d*)(X+)", sub.upper())
        owner = _norm(owner)
        if not ndc or not m or not owner:
            bad += 1
            continue
        # The E.164 string carries its own NDC; trust the NDC column only
        # when they agree (or the string has no separate NDC part).
        if len(parts) >= 3 and re.sub(r"\D", "", parts[-2]) not in ("", ndc):
            bad += 1
            continue
        rest = m.group(1)
        nx = len(m.group(2))
        dial = _norm(dial)
        label = dial.split("-")[0].strip() if "-" in dial else ""
        if not re.fullmatch(r"\d+", label or ""):
            label = "0" + ndc
        rows.append(
            {
                "ndc": ndc,
                "rest": rest,
                "nx": nx,
                "sublen": len(rest) + nx,
                "cap": 10**nx,
                "owner": owner,
                "op": _op_he(owner),
                "note_raw": _norm(note),
                "note": _note_he(_norm(note)),
                "label": label,
                "cat": _category(ndc),
            }
        )
    b = pd.DataFrame(rows)
    if len(b):
        b = b.sort_values(["ndc", "rest", "nx", "owner"], kind="mergesort").reset_index(drop=True)
    return b, bad


def compute(frames):
    df = frames["plan"]
    b, bad = _parse(df)
    n_blocks = len(b)
    total_cap = int(b["cap"].sum())

    # ---- per operator ------------------------------------------------------
    ops = (
        b.groupby("owner")
        .agg(cap=("cap", "sum"), blocks=("cap", "size"), ndcs=("ndc", "nunique"))
        .reset_index()
    )
    ops["op"] = ops["owner"].map(_op_he)
    ops = ops.sort_values(["cap", "blocks", "owner"], ascending=[False, False, True], kind="mergesort").reset_index(drop=True)
    n_ops = len(ops)

    # ---- per prefix (NDC) --------------------------------------------------
    labels_by_ndc = b.groupby("ndc")["label"].agg(lambda s: sorted(s.unique())[0]).to_dict()
    space_by_ndc = b.groupby("ndc")["sublen"].max().map(lambda d: 10**int(d)).to_dict()

    def ndc_key(n):
        return (CAT_ORDER.index(_category(n)), len(n), n)

    ndcs = sorted(b["ndc"].unique(), key=ndc_key)
    pref = []
    for n in ndcs:
        g = b[b["ndc"] == n]
        oc = g.groupby("owner")["cap"].sum().reset_index()
        oc["op"] = oc["owner"].map(_op_he)
        oc = oc.sort_values(["cap", "owner"], ascending=[False, True], kind="mergesort")
        cap = int(g["cap"].sum())
        space = int(space_by_ndc[n])
        cat = _category(n)
        kind = CAT_HE[cat]
        if cat == "geo" and n in REGION_HE:
            kind = f"{kind}: {REGION_HE[n]}"
        top = list(oc["op"])
        pref.append(
            {
                "ndc": n,
                "label": labels_by_ndc[n],
                "kind": kind,
                "cat": cat,
                "blocks": int(len(g)),
                "ops": int(len(oc)),
                "cap": cap,
                "space": space,
                "util": cap / space if space else 0.0,
                "leader": top[0],
                "leader_share": float(oc["cap"].iloc[0]) / cap if cap else 0.0,
                "op_list": top,
            }
        )

    # ---- categories --------------------------------------------------------
    cat_rows = []
    for c in CAT_ORDER:
        g = b[b["cat"] == c]
        if not len(g):
            continue
        cat_rows.append(
            {
                "name": CAT_HE[c],
                "cap": int(g["cap"].sum()),
                "blocks": int(len(g)),
                "prefixes": _list_he([labels_by_ndc[n] for n in ndcs if _category(n) == c]),
                "ops": int(g["owner"].nunique()),
            }
        )

    # ---- chart: top operators ---------------------------------------------
    top_ops = ops.head(TOP_OPS)
    rest_ops = ops.iloc[TOP_OPS:]
    op_chart = {
        "names": list(top_ops["op"]),
        "values": [round(v / 1_000_000, 3) for v in top_ops["cap"]],
        "blocks": [int(v) for v in top_ops["blocks"]],
        "shares": [_pct(v / total_cap) for v in top_ops["cap"]],
    }
    op_table = [
        {"name": r.op, "cap": _fmt_cap(int(r.cap)), "blocks": int(r.blocks), "share": _pct(r.cap / total_cap)}
        for r in top_ops.itertuples()
    ]
    if len(rest_ops):
        oc = int(rest_ops["cap"].sum())
        ob = int(rest_ops["blocks"].sum())
        name = f"שאר המפעילים ({len(rest_ops):,})"
        op_chart["names"].append(name)
        op_chart["values"].append(round(oc / 1_000_000, 3))
        op_chart["blocks"].append(ob)
        op_chart["shares"].append(_pct(oc / total_cap))
        op_table.append({"name": name, "cap": _fmt_cap(oc), "blocks": ob, "share": _pct(oc / total_cap)})

    # ---- chart: operator mix per prefix (100% stacked) ---------------------
    mix_owners = list(ops.head(MIX_OPS)["owner"])
    mix_series = []
    for o in mix_owners:
        vals = []
        for p in pref:
            g = b[(b["ndc"] == p["ndc"]) & (b["owner"] == o)]
            vals.append(round(float(g["cap"].sum()) / p["cap"] * 100, 2) if p["cap"] else 0)
        mix_series.append({"name": _op_he(o), "data": vals})
    other_vals = []
    for p in pref:
        g = b[(b["ndc"] == p["ndc"]) & (~b["owner"].isin(mix_owners))]
        other_vals.append(round(float(g["cap"].sum()) / p["cap"] * 100, 2) if p["cap"] else 0)
    if any(v > 0 for v in other_vals):
        mix_series.append({"name": "מפעילים אחרים", "data": other_vals})
    mix_chart = {"prefixes": [p["label"] for p in pref], "series": mix_series}

    # ---- chart: utilisation per prefix -------------------------------------
    util_chart = {
        "prefixes": [p["label"] for p in pref],
        "util": [round(p["util"] * 100, 2) for p in pref],
        "cap": [p["cap"] for p in pref],
        "space": [p["space"] for p in pref],
        "kind": [p["kind"] for p in pref],
    }

    # ---- chart: numbering-space grid (prefix x first digit) ----------------
    cells = []
    for yi, p in enumerate(pref):
        g = b[b["ndc"] == p["ndc"]]
        bucket = p["space"] // 10
        for d in range(10):
            ds = str(d)
            alloc = 0
            owners = set()
            for r in g.itertuples():
                if r.rest == "":
                    alloc += bucket
                    owners.add(r.op)
                elif r.rest[0] == ds:
                    alloc += r.cap
                    owners.add(r.op)
            pct = round(min(alloc / bucket, 1.0) * 100, 1) if bucket else 0.0
            cells.append([d, yi, pct, " · ".join(sorted(owners)) if owners else ""])
    grid_chart = {"prefixes": [p["label"] for p in pref], "cells": cells, "digits": [str(d) for d in range(10)]}
    n_empty_cells = sum(1 for c in cells if c[2] == 0)

    # ---- chart: block sizes ------------------------------------------------
    size_rows = []
    for nx in sorted(b["nx"].unique()):
        g = b[b["nx"] == nx]
        size_rows.append(
            {
                "name": f"{10**int(nx):,} מספרים",
                "blocks": int(len(g)),
                "cap": int(g["cap"].sum()),
                "cap_share": _pct(g["cap"].sum() / total_cap),
                "block_share": _pct(len(g) / n_blocks),
            }
        )
    size_chart = {
        "names": [r["name"] for r in size_rows],
        "blocks": [r["blocks"] for r in size_rows],
        "cap_share": [round(r["cap"] / total_cap * 100, 2) for r in size_rows],
    }

    # ---- chart: special designations (Notes) -------------------------------
    note_g = (
        b.groupby("note")
        .agg(cap=("cap", "sum"), blocks=("cap", "size"), ops=("owner", "nunique"))
        .reset_index()
        .sort_values(["cap", "note"], ascending=[False, True], kind="mergesort")
    )
    note_rows = [
        {"name": r.note, "cap": int(r.cap), "cap_txt": _fmt_cap(int(r.cap)), "blocks": int(r.blocks), "ops": int(r.ops), "share": _pct(r.cap / total_cap)}
        for r in note_g.itertuples()
    ]
    special = [r for r in note_rows if r["name"] != NO_NOTE]
    note_chart = {
        "names": [r["name"] for r in special],
        "values": [round(r["cap"] / 1_000_000, 3) for r in special],
        "blocks": [r["blocks"] for r in special],
    }

    # ---- chart: operators by service category ------------------------------
    cats_present = [c for c in CAT_ORDER if (b["cat"] == c).any()]
    span_owners = list(ops.head(TOP_OPS)["owner"])
    span_series = []
    for c in cats_present:
        vals = []
        for o in span_owners:
            vals.append(round(float(b[(b["owner"] == o) & (b["cat"] == c)]["cap"].sum()) / 1_000_000, 3))
        span_series.append({"name": CAT_HE[c], "data": vals})
    span_chart = {"names": [_op_he(o) for o in span_owners], "series": span_series}
    span_table = []
    for o in span_owners:
        g = b[b["owner"] == o]
        span_table.append(
            {
                "name": _op_he(o),
                "cells": [_fmt_cap(int(g[g["cat"] == c]["cap"].sum())) if (g["cat"] == c).any() else "" for c in cats_present],
            }
        )
    multi_cat_ops = int((b.groupby("owner")["cat"].nunique() >= 2).sum())

    # ---- lookup data (chunked JSON islands) --------------------------------
    op_names = list(ops["owner"])
    op_idx = {o: i for i, o in enumerate(op_names)}
    note_names = sorted(b["note"].unique(), key=lambda s: (s != NO_NOTE, s))
    note_idx = {s: i for i, s in enumerate(note_names)}
    entries = [[r.ndc, r.rest, op_idx[r.owner], note_idx[r.note], int(r.nx)] for r in b.itertuples()]
    chunk = 800
    lookup = {
        "ops": [[_op_he(o), o if _op_he(o) != o else ""] for o in op_names],
        "notes": [s if s != NO_NOTE else "" for s in note_names],
        "labels": {p["ndc"]: p["label"] for p in pref},
        "kinds": {p["ndc"]: p["kind"] for p in pref},
        "chunks": [entries[i : i + chunk] for i in range(0, len(entries), chunk)],
    }
    biggest_ndc = sorted(pref, key=lambda p: (-p["blocks"], p["ndc"]))[0]

    # ---- prefix directory table -------------------------------------------
    directory = []
    for p in pref:
        names = p["op_list"]
        shown = names[:4]
        more = len(names) - len(shown)
        txt = ", ".join(shown) + (f" ועוד {more:,}" if more > 0 else "")
        directory.append(
            {
                "label": p["label"],
                "kind": p["kind"],
                "ops": txt,
                "n_ops": p["ops"],
                "util": _pct(p["util"], 0) if p["util"] >= 0.1 else _pct(p["util"]),
            }
        )

    # ---- insights ----------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_leader():
        if n_ops < 2:
            return None
        top = ops.iloc[0]
        share = top["cap"] / total_cap
        if share < 0.12:
            return None
        second = ops.iloc[1]
        return (
            f"{top['op']} מחזיקה בנתח הגדול ביותר של מרחב המספרים: {_fmt_cap(int(top['cap']))} מספרים "
            f"({_pct(share)} מכלל המספרים שהוקצו) ב-{int(top['blocks']):,} טווחים, "
            f"לפני {second['op']} עם {_fmt_cap(int(second['cap']))}."
        )

    def ins_concentration():
        if n_ops < 8:
            return None
        top4 = ops.head(4)
        s4 = top4["cap"].sum() / total_cap
        small = ops[ops["cap"] < 100_000]
        if len(small) < 3:
            return None
        return (
            f"ארבעת המחזיקים הגדולים ({_list_he(list(top4['op']))}) מרכזים {_pct(s4)} מהמספרים, "
            f"ואילו {len(small):,} מתוך {n_ops:,} המפעילים מחזיקים פחות מ-100,000 מספרים כל אחד."
        )

    def ins_single():
        singles = [p for p in pref if p["ops"] == 1 and p["cat"] == "mobile"]
        if len(singles) < 2:
            return None
        parts = [f"{p['label']} ({p['leader']})" for p in singles]
        return (
            f"{len(singles):,} קידומות נייד מוקצות כולן למפעיל אחד: {_list_he(parts)}. "
            f"לכן הקידומת לבדה מזהה בהן את המפעיל שקיבל את המספר במקור (מספר שהועבר בניוד ממשיך להופיע תחת המפעיל המקורי)."
        )

    def ins_shared():
        multi = sorted([p for p in pref if p["ops"] >= 5], key=lambda p: (-p["ops"], ndc_key(p["ndc"])))
        if not multi:
            return None
        top = multi[0]
        geo = [p for p in pref if p["cat"] == "geo"]
        tail = ""
        if len(geo) >= 2 and top["cat"] != "geo":
            lo = min(p["ops"] for p in geo)
            hi = max(p["ops"] for p in geo)
            rng = f"{lo:,}" if lo == hi else f"{lo:,} עד {hi:,}"
            tail = f" גם כל אחת מהקידומות האזוריות מחולקת בין {rng} מפעילים."
        elif top["cat"] == "geo":
            others = [p for p in multi if p["cat"] != "geo"]
            if others:
                o = others[0]
                tail = f" מחוץ לקידומות האזוריות, המשותפת ביותר היא {o['label']} ({o['kind']}), עם {o['ops']:,} מפעילים."
        return (
            f"הקידומת המשותפת ביותר היא {top['label']} ({top['kind']}): {top['ops']:,} מפעילים חולקים בה "
            f"{top['blocks']:,} טווחים, ולכן הקידומת לבדה לא מספיקה כדי לדעת לאיזו חברה שייך המספר.{tail}"
        )

    def ins_util():
        if len(pref) < 3:
            return None
        full = [p for p in pref if p["util"] >= 0.999]
        low = sorted(pref, key=lambda p: (p["util"], ndc_key(p["ndc"])))[0]
        if low["util"] >= 0.5:
            return None
        lead = ""
        if full:
            lead = _full_txt([p["label"] for p in full]) + ", "
        else:
            hi = sorted(pref, key=lambda p: (-p["util"], ndc_key(p["ndc"])))[0]
            lead = f"הקידומת המלאה ביותר היא {hi['label']} ({_pct_txt(hi['util'])} הוקצו), "
        return (
            f"{lead}ואילו בקידומת {low['label']} הוקצו רק {_pct_txt(low['util'])} ממרחב המספרים "
            f"({_fmt_cap(low['cap'])} מתוך {_fmt_cap(low['space'])})."
        )

    def ins_special():
        if not special:
            return None
        m2m = [r for r in special if "מכונה" in r["name"] or "IoT" in r["name"]]
        bits = []
        if m2m:
            cap = sum(r["cap"] for r in m2m)
            blk = sum(r["blocks"] for r in m2m)
            bits.append(f"{blk:,} טווחים ({_fmt_cap(cap)} מספרים) מיועדים לתקשורת בין מכשירים ולא לשיחות של בני אדם")
        pa = [r for r in special if r["name"] == NOTE_HE["PALESTINIAN AUTHORITY"]]
        if pa:
            bits.append(f"{_fmt_cap(pa[0]['cap'])} מספרים ({pa[0]['share']}) מסומנים כשייכים לרשות הפלסטינית")
        if not bits:
            r = special[0]
            bits.append(f"{r['blocks']:,} טווחים ({_fmt_cap(r['cap'])} מספרים) מסומנים בייעוד {r['name']}")
        return "בתוכנית המספור " + "; ".join(bits) + "."

    def ins_sizes():
        if len(size_rows) < 2 or n_blocks < 10:
            return None
        small = b[b["cap"] <= 10_000]
        if len(small) < 5:
            return None
        sb = len(small) / n_blocks
        sc = small["cap"].sum() / total_cap
        geo_share = (small["cat"] == "geo").mean()
        tail = "."
        if geo_share >= 0.5:
            tail = f", ו-{_pct_txt(geo_share)} מהם נמצאים בקידומות האזוריות."
        return (
            f"{len(small):,} טווחים ({_pct_txt(sb)} מהטווחים) הם קטנים, של 10,000 מספרים או פחות, "
            f"ויחד הם מהווים רק {_pct(sc, 2) if sc < 0.01 else _pct(sc)} מהמספרים{tail}"
        )

    add("leader", ins_leader())
    add("single", ins_single())
    add("shared", ins_shared())
    add("concentration", ins_concentration())
    add("util", ins_util())
    add("special", ins_special())
    add("sizes", ins_sizes())

    # ---- KPIs --------------------------------------------------------------
    full_n = sum(1 for p in pref if p["util"] >= 0.999)
    kpis = {
        "blocks": {"value": n_blocks, "display": f"{n_blocks:,}", "tone": "brand"},
        "ops": {"value": n_ops, "display": f"{n_ops:,}", "tone": "brand"},
        "cap": {"value": total_cap, "display": f"{total_cap / 1_000_000:.1f}", "tone": "brand"},
        "prefixes": {"value": len(pref), "display": f"{len(pref):,}", "tone": "info"},
    }

    # ---- labels / ledes ----------------------------------------------------
    top_op = ops.iloc[0]
    top_cat = sorted(cat_rows, key=lambda r: (-r["cap"], r["name"]))[0]
    util_full = [p["label"] for p in pref if p["util"] >= 0.999]
    util_low = sorted(pref, key=lambda p: (p["util"], ndc_key(p["ndc"])))[0]
    mix_shared = sorted(pref, key=lambda p: (-p["ops"], ndc_key(p["ndc"])))[0]
    largest_size = sorted(size_rows, key=lambda r: (-r["blocks"], r["name"]))[0]

    labels = {
        "kpi_blocks": "טווחי מספרים שהוקצו",
        "kpi_ops": "מפעילי טלפוניה מורשים",
        "kpi_cap": "מספרי טלפון בטווחים (מיליונים)",
        "kpi_prefixes": "קידומות בתוכנית",
        "lookup_placeholder": f"מספר טלפון או קידומת, למשל {biggest_ndc['label']}",
        "lookup_lede": (
            f"הקלידו מספר טלפון ישראלי (גם בפורמט בינלאומי) או רק את תחילתו, והכלי יאתר אותו בין "
            f"{n_blocks:,} טווחי המספרים של {n_ops:,} המפעילים. הקלדת קידומת בלבד מציגה את כל המפעילים שקיבלו בה מספרים."
        ),
        "lead": (
            f"תוכנית המספור הלאומית של משרד התקשורת (תכנית המספרים לפי תקן E.164) מפרטת לאיזו חברת תקשורת הוקצה כל טווח של מספרי טלפון בישראל. "
            f"היא כוללת {n_blocks:,} טווחים ב-{len(pref):,} קידומות, שהוקצו ל-{n_ops:,} מפעילים ומכסים יחד {_fmt_cap(total_cap)} מספרים."
        ),
        "lead2": (
            "כך אפשר לברר של איזו חברה קידומת הטלפון (למשל קידומות נייד, קידומות אזוריות וקידומות ארציות של טלפוניית אינטרנט), "
            "ולזהות את המפעיל שאליו הוקצה מספר במקור. מספר שעבר ניוד לחברה אחרת נשאר רשום כאן תחת המפעיל המקורי."
        ),
        "dir_lede": (
            f"כל {len(pref):,} הקידומות בתוכנית, סוג השירות והמפעילים שקיבלו בהן מספרים (לפי היקף המספרים, מהגדול לקטן), "
            f"ושיעור מרחב המספרים של הקידומת שכבר הוקצה."
        ),
        "dir_caption": "טבלת קידומות הטלפון בישראל: סוג השירות, המפעילים ושיעור ההקצאה",
        "cat_lede": (
            f"{top_cat['name']} הוא הנתח הגדול ביותר: {_fmt_cap(top_cat['cap'])} מספרים "
            f"({_pct(top_cat['cap'] / total_cap)}) ב-{top_cat['blocks']:,} טווחים."
        ),
        "cat_aria": f"גרף עמודות: מספרי טלפון שהוקצו לפי סוג שירות. {top_cat['name']}: {_fmt_cap(top_cat['cap'])} מספרים.",
        "ops_lede": (
            f"{top_op['op']} מובילה עם {_fmt_cap(int(top_op['cap']))} מספרים. "
            f"התרשים מציג את {min(TOP_OPS, n_ops):,} המחזיקים הגדולים"
            + (f", ו-{len(rest_ops):,} המפעילים האחרים מקובצים יחד." if len(rest_ops) else ".")
        ),
        "ops_aria": f"גרף עמודות אופקי: מספרי טלפון לפי מפעיל, במיליונים. {top_op['op']} מובילה עם {_fmt_cap(int(top_op['cap']))}.",
        "mix_lede": (
            f"חלוקת המספרים בכל קידומת בין המפעילים. בקידומת {mix_shared['label']} פועלים {mix_shared['ops']:,} מפעילים, "
            f"ובחלק מקידומות הנייד יש מפעיל אחד בלבד. {MIX_OPS:,} המחזיקים הגדולים מוצגים בנפרד, והשאר מקובצים."
        ),
        "mix_aria": f"גרף עמודות מוערמות: חלוקת כל קידומת בין המפעילים באחוזים. בקידומת {mix_shared['label']} פועלים {mix_shared['ops']:,} מפעילים.",
        "util_lede": (
            (_full_txt(util_full) + ". " if util_full else "")
            + f"בקידומת {util_low['label']} הוקצו רק {_pct_txt(util_low['util'])} מהמספרים האפשריים."
        ),
        "util_aria": f"גרף עמודות: שיעור מרחב המספרים שהוקצה בכל קידומת. הנמוך ביותר: {util_low['label']}, {_pct_txt(util_low['util'])}.",
        "grid_lede": (
            f"כל שורה היא קידומת, וכל עמודה היא הספרה הראשונה אחרי הקידומת. הצבע מראה איזה חלק מהטווח הוקצה, "
            f"והריחוף מציג את המפעילים. {n_empty_cells:,} מתוך {len(cells):,} המשבצות עדיין ריקות לגמרי."
        ),
        "grid_aria": f"מפת חום: שיעור ההקצאה לפי קידומת וספרה ראשונה. {n_empty_cells:,} משבצות ריקות מתוך {len(cells):,}.",
        "size_lede": (
            f"הגודל הנפוץ ביותר הוא טווח של {largest_size['name']} ({largest_size['blocks']:,} טווחים). "
            f"טווחים גדולים של מיליון מספרים ומעלה מחזיקים את רוב המספרים, וטווחים קטנים משרתים מפעילים קטנים."
        ),
        "size_aria": f"גרף עמודות: מספר הטווחים לפי גודל הטווח. הנפוץ: {largest_size['name']}, {largest_size['blocks']:,} טווחים.",
        "note_lede": (
            f"חלק מהטווחים מסומנים בייעוד מיוחד בעמודת ההערות: {len(special):,} סוגי ייעוד, "
            f"{sum(r['blocks'] for r in special):,} טווחים בסך הכול."
        ) if special else "",
        "note_aria": (
            f"גרף עמודות: מספרים בטווחים בעלי ייעוד מיוחד, במיליונים. הגדול: {special[0]['name']}, {special[0]['cap_txt']}."
        ) if special else "",
        "span_lede": (
            f"{multi_cat_ops:,} מפעילים מחזיקים מספרים ביותר מסוג שירות אחד, למשל קידומות נייד לצד קידומות נייח. "
            f"התרשים מציג את {len(span_owners):,} המחזיקים הגדולים."
        ),
        "span_aria": f"גרף עמודות מוערמות: מספרים של כל מפעיל לפי סוג שירות, במיליונים. {multi_cat_ops:,} מפעילים פועלים ביותר מסוג אחד.",
        "bad_note": f"{bad:,} שורות שלא ניתן היה לפענח את טווח המספרים שלהן לא נכללו." if bad else "",
    }

    summary = (
        f"של איזו חברה קידומת או מספר טלפון? איתור המפעיל לפי מספר או קידומת בתוכנית המספור: "
        f"{n_blocks:,} טווחים, {n_ops:,} מפעילים."
    )

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "cats": {
                "names": [r["name"] for r in cat_rows],
                "values": [round(r["cap"] / 1_000_000, 3) for r in cat_rows],
                "blocks": [r["blocks"] for r in cat_rows],
            },
            "ops": op_chart,
            "mix": mix_chart,
            "util": util_chart,
            "grid": grid_chart,
            "sizes": size_chart,
            "notes": note_chart,
            "span": span_chart,
        },
        "tables": {
            "cats": [dict(r, cap_txt=_fmt_cap(r["cap"]), share=_pct(r["cap"] / total_cap)) for r in cat_rows],
            "ops": op_table,
            "mix": [
                {"label": p["label"], "leader": p["leader"], "share": _pct(p["leader_share"]), "ops": p["ops"], "blocks": p["blocks"]}
                for p in pref
            ],
            "util": [
                {"label": p["label"], "cap": _fmt_cap(p["cap"]), "space": _fmt_cap(p["space"]), "util": _pct(p["util"])}
                for p in pref
            ],
            "sizes": size_rows,
            "notes": note_rows,
            "span_cols": [CAT_HE[c] for c in cats_present],
            "span": span_table,
            "directory": directory,
        },
        "lookup": lookup,
        "flags": {"has_notes": bool(special), "has_span": len(cats_present) >= 2},
        "insights": insights,
        "labels": labels,
    }
