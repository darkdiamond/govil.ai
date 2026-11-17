"""החקלאות בישראל: CBS's yearly release on Israel's agriculture account.

Each edition (one a year, about June) holds the agriculture account for the
newest year and the two before it, in NIS millions at current prices, with
the price and quantity change of each line against the year before:

  account  לוח: חשבון ענף החקלאות      output, input, depreciation, domestic
                                         product, compensation and receipts,
                                         income from agriculture, wages
  output   לוח: ערך התפוקה החקלאית     output value by branch (field crops,
                                         vegetables, citrus, plantations, ...
                                         poultry, cattle, sheep and goats ...)
  input    לוח: תשומה בחקלאות          purchased input by type (fodder, water,
                                         fertilizers ...) and depreciation
  change   תרשים: אחוז השינוי בערך      yearly % change of output value since
           התפוקה החקלאית               2007 (total, crops, livestock)

The other chart sheets (account in billions, output and input shares) repeat
those tables and are not read. CBS renumbers tables between editions, so
every table input (t1..t10, three of them spare, all optional) is recognised
per edition by its title, never by its stem. With history_releases = 3 the
grids stack three editions: years are merged across them, the newest edition
winning on overlap, and each year's price/quantity change is taken from the
edition in which that year is the newest (a later edition's columns for
earlier years are revisions we don't need).

A recognised table whose header ("Price change") is gone while it still has
data rows raises; an edition cut off above its header (verify's 70% run)
adds nothing. The account's output row is the one figure the page can't do
without.
"""
import re

import pandas as pd
from govlib import cbs, fmt

YEAR_CELL = re.compile(r"^R?((?:19|20)\d\d)$")
REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
TABLE_KINDS = (
    ("account", "לוח", "חשבון ענף החקלאות"),
    ("output", "לוח", "ערך התפוקה החקלאית"),
    ("input", "לוח", "תשומה בחקלאות"),
    ("change", "תרשים", "אחוז השינוי בערך התפוקה"),
)
INPUTS = [f"t{i}" for i in range(1, 11)]
# Account lines: key → (Hebrew label, match mode). "in" = label contains.
ACCOUNT = {
    "out": ("תפוקה", "eq"),
    "crops": ("גידולים צמחיים", "eq"),
    "live": ("בעלי חיים ותוצרתם", "eq"),
    "input": ("לא כולל תמורה", "in"),
    "purchased": ("קנויה", "in"),
    "dep": ("בלאי", "eq"),
    "gross": ("גולמי", "eq"),
    "net": ("נקי", "eq"),
    "comp": ("פיצויים ותקבולים נוספים", "eq"),
    "comp_tax": ("פיצויים מס רכוש", "eq"),
    "comp_ins": ("פיצויים מביטוח", "eq"),
    "comp_drought": ("פיצויי בצורת", "eq"),
    "comp_water": ("פיצויי קיצוץ במים", "eq"),
    "comp_other": ("תקבולים אחרים", "eq"),
    "income": ("הכנסה שמקורה בחקלאות", "eq"),
    "wages": ("מזה: תמורה למשרות", "in"),
    "balance": ("יתרה", "eq"),
}
COMP_PARTS = [("comp_tax", "פיצויי מס רכוש"), ("comp_ins", "פיצויים מביטוח"),
              ("comp_drought", "פיצויי בצורת"), ("comp_water", "פיצויי קיצוץ במים"),
              ("comp_other", "תקבולים אחרים")]
OUT_TOTAL, OUT_CROPS, OUT_LIVE = "סך הכל", "גידולים צמחיים", "בעלי חיים ותוצרתם"
IN_TOTAL, IN_PURCHASED, IN_DEP = "סך הכל", "סך הכל תשומה קנויה", "בלאי"
MIN_BRANCH = 300.0  # NIS millions: a branch smaller than this is too small for a "mover" insight
PRIORITY = ("headline", "drivers", "leader", "mover", "split", "fodder", "inputs", "income",
            "comp", "long")
MAX_TOP = 8


# ── reading the grids ────────────────────────────────────────────────────


def _ed_key(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _editions(df):
    """[(edition key, rows)] oldest first; rows are cleaned cell lists."""
    if df.empty:
        return []
    cols = sorted((c for c in df.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))
    out = []
    for no in sorted(df["RELEASE_NO"].unique(), key=lambda n: (_ed_key(n), str(n))):
        sub = df[df["RELEASE_NO"] == no].sort_values(["SHEET_NO", "ROW"], kind="stable")
        rows = [[cbs.clean(v) for v in r] for r in sub[cols].itertuples(index=False)]
        out.append((_ed_key(no), rows))
    return out


def _kind(rows):
    for r in rows[:12]:
        for c in r:
            for kind, prefix, key in TABLE_KINDS:
                if c.startswith(prefix) and key in c:
                    return kind
    return None


def _label(r):
    for c in reversed(r):
        if c:
            return c
    return ""


def _numeric_rows(rows):
    return sum(1 for r in rows if sum(cbs.num(c) is not None for c in r) >= 3)


def _year_table(rows, name):
    """{label: {"v": {year: value}}}, newest year, {label: (price %, qty %)}
    for the newest year; None when the edition is cut off above its header."""
    try:
        h = cbs.row_with(rows, "Price change", contains=True, name=name)
    except ValueError:
        if _numeric_rows(rows):
            raise
        return None
    head = rows[h]
    vcols = [(j, int(YEAR_CELL.match(c).group(1))) for j, c in enumerate(head) if YEAR_CELL.match(c)]
    if not vcols:
        raise ValueError(f"{name}: no year columns in the value header")
    cbs.col_after(head, "Quantitative change", contains=True)
    # The row under the header holds the change blocks' years: the price
    # block first, then the quantity block, as many years each.
    sub = rows[h + 1] if h + 1 < len(rows) else []
    ycells = [(j, int(YEAR_CELL.match(c).group(1))) for j, c in enumerate(sub) if YEAR_CELL.match(c)]
    half = len(ycells) // 2 if len(ycells) % 2 == 0 else 0
    newest = max(y for _, y in vcols)
    pcol = next((j for j, y in ycells[:half] if y == newest), None)
    qcol = next((j for j, y in ycells[half:] if y == newest), None) if half else None
    vals, chg, order = {}, {}, []
    for r in rows[h + 2:]:
        lab = _label(r)
        v = {y: cbs.val(r, j) for j, y in vcols}
        v = {y: x for y, x in v.items() if x is not None}
        if not lab or not v or lab in vals:
            continue
        vals[lab] = v
        order.append(lab)
        chg[lab] = (cbs.val(r, pcol) if pcol is not None else None,
                    cbs.val(r, qcol) if qcol is not None else None)
    return {"vals": vals, "newest": newest, "chg": chg, "order": order}


def _merge(parsed):
    """Merge per-edition year tables (oldest first): newest edition wins."""
    vals, chg, order = {}, {}, []
    for t in parsed:
        for lab, v in t["vals"].items():
            vals.setdefault(lab, {}).update(v)
            chg.setdefault(lab, {})[t["newest"]] = t["chg"][lab]
        order = t["order"]
    return vals, chg, order


def _tables(frames):
    found = {}
    for name in INPUTS:
        df = frames.get(name)
        if df is None:
            continue
        for key, rows in _editions(df):
            kind = _kind(rows)
            if kind:
                found.setdefault(kind, []).append((key, name, rows))
    for lst in found.values():
        lst.sort(key=lambda t: (t[0], t[1]))
    return found


def _find(vals, label, mode="eq"):
    for lab, v in vals.items():
        if (lab == label) if mode == "eq" else (label in lab):
            return v
    return None


# ── formatting ───────────────────────────────────────────────────────────


def _bn(m):
    """NIS millions → billions, one decimal."""
    return fmt.num_he(m / 1000.0, 1)


def _prose(lab):
    """A CBS branch label for a sentence: "מטעים, ללא פרי הדר" → "מטעים (ללא פרי הדר)"."""
    return re.sub(r",\s*(ללא .+)$", r" (\1)", lab)


def _chg(a, b):
    return (a / b - 1) * 100 if a is not None and b else None


def _r1(v):
    return None if v is None else round(v, 1)


def _r2(v):
    return None if v is None else round(v, 2)


def _ud(v, up="עלייה", down="ירידה"):
    return up if v > 0 else down


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    T = _tables(frames)
    rel = cbs.latest_release(frames["releases"])
    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(key, text):
        if text:
            insights.append({"id": key, "text_he": text})

    # ── account ──────────────────────────────────────────────────────────
    acc_p = [p for p in (_year_table(r, n) for _, n, r in T.get("account", [])) if p]
    acc_vals, acc_chg, _ = _merge(acc_p)
    A, AC = {}, {}
    for key, (lab, mode) in ACCOUNT.items():
        v = _find(acc_vals, lab, mode)
        if v is not None:
            A[key] = v
            AC[key] = next((acc_chg[x] for x in acc_vals if acc_vals[x] is v), {})
    if "out" not in A or len(A["out"]) < 2:
        raise ValueError("account: output row (תפוקה) not found for two years")
    ys = sorted(A["out"])
    ly, py = ys[-1], ys[-2]
    out_l, out_p = A["out"][ly], A["out"].get(py)
    out_chg = _chg(out_l, out_p)
    pc, qc = AC["out"].get(ly, (None, None))

    def g(key, y=ly):
        return A.get(key, {}).get(y)

    kpis["out"] = {"value": round(out_l / 1000, 2), "display": _bn(out_l), "tone": "brand"}
    labels["out_kpi"] = f"ערך התפוקה החקלאית ב-{ly} (מיליארד ש\"ח)"
    if out_chg is not None:
        kpis["outchg"] = {"value": round(out_chg, 2), "display": fmt.signed_pct(out_chg / 100),
                          "tone": "ok" if out_chg > 0 else "warn"}
        labels["outchg_kpi"] = f"שינוי בערך התפוקה לעומת {py}"
    if qc is not None:
        kpis["qty"] = {"value": round(qc, 2), "display": fmt.signed_pct(qc / 100),
                       "tone": "ok" if qc > 0 else "warn"}
        labels["qty_kpi"] = f"שינוי בכמות התפוקה ב-{ly} (ללא השפעת המחירים)"
    if g("income") is not None:
        kpis["income"] = {"value": round(g("income") / 1000, 2), "display": _bn(g("income")),
                          "tone": "brand"}
        labels["income_kpi"] = f"הכנסה שמקורה בחקלאות ב-{ly} (מיליארד ש\"ח)"
    if g("comp") is not None:
        kpis["comp"] = {"value": round(g("comp") / 1000, 2), "display": _bn(g("comp")),
                        "tone": "info"}
        labels["comp_kpi"] = f"פיצויים ותקבולים נוספים ב-{ly} (מיליארד ש\"ח)"

    # headline insight
    if out_chg is not None:
        t = (f"ערך התפוקה החקלאית בישראל הגיע ב-{ly} ל-{_bn(out_l)} מיליארד ש\"ח, "
             f"{_ud(out_chg)} של {fmt.pct_of(abs(out_chg))} לעומת {py}")
        if g("crops") is not None and g("live") is not None:
            t += (f" (גידולים צמחיים {_bn(g('crops'))} מיליארד ש\"ח, בעלי חיים ותוצרתם "
                  f"{_bn(g('live'))} מיליארד ש\"ח)")
        add("headline", t + ".")
    if pc is not None and qc is not None and abs(pc) + abs(qc) >= 0.5:
        if (pc > 0) == (qc > 0):
            t = (f"ב-{ly} עלו גם המחירים ({fmt.signed_pct(pc / 100)}) וגם הכמויות "
                 f"({fmt.signed_pct(qc / 100)}) של התוצרת החקלאית" if pc > 0 else
                 f"ב-{ly} ירדו גם המחירים ({fmt.signed_pct(pc / 100)}) וגם הכמויות "
                 f"({fmt.signed_pct(qc / 100)}) של התוצרת החקלאית")
        else:
            lead = "המחירים" if abs(pc) > abs(qc) else "הכמויות"
            t = (f"השינוי בערך התפוקה ב-{ly} מורכב משינוי מחירים של {fmt.signed_pct(pc / 100)} "
                 f"ושינוי כמויות של {fmt.signed_pct(qc / 100)}: {lead} הכריעו את הכיוון")
        add("drivers", t + ".")

    # account chart (latest year)
    acc_items = [("out", "תפוקה"), ("purchased", "תשומה קנויה"), ("dep", "בלאי"),
                 ("net", "תוצר מקומי נקי"), ("comp", "פיצויים ותקבולים"),
                 ("income", "הכנסה שמקורה בחקלאות"), ("wages", "מזה: תמורה למשרות שכיר"),
                 ("balance", "יתרה")]
    acc_items = [(k, n) for k, n in acc_items if g(k) is not None]
    charts["account"] = {"names": [n for _, n in acc_items],
                         "values": [_r2(g(k) / 1000) for k, _ in acc_items],
                         "kind": [("in" if k in ("out", "comp") else "out" if k in ("purchased", "dep")
                                   else "sum") for k, _ in acc_items]}
    labels["account_aria"] = f"חשבון ענף החקלאות בשנת {ly}, במיליארדי ש\"ח"
    labels["account_note"] = (f"מהתפוקה מנכים את התשומות הקנויות ואת הבלאי ומקבלים את התוצר המקומי הנקי. "
                              f"בתוספת פיצויים ותקבולים מתקבלת ההכנסה שמקורה בחקלאות, וממנה משולמת "
                              f"התמורה לשכירים. נתוני {ly}, מיליארדי ש\"ח במחירים שוטפים.")
    prev_y = {k: g(k, py) for k, _ in acc_items}
    tables["account"] = [[n, _bn(g(k)), _bn(prev_y[k]) if prev_y[k] is not None else "–",
                          fmt.signed_pct(_chg(g(k), prev_y[k]) / 100)
                          if prev_y[k] and _chg(g(k), prev_y[k]) is not None else "–"]
                         for k, n in acc_items]
    labels["account_cols"] = ["סעיף", f"{ly} (מיליארד ש\"ח)", f"{py} (מיליארד ש\"ח)", "שינוי"]

    # trend chart: output, input, income over the merged years
    tr_keys = [("out", "תפוקה"), ("input", "תשומה (ללא תמורה לשכירים)"),
               ("income", "הכנסה שמקורה בחקלאות")]
    tr_keys = [(k, n) for k, n in tr_keys if k in A]
    charts["trend"] = {"x": [str(y) for y in ys],
                       "series": [{"name": n, "data": [_r2(A[k][y] / 1000) if A[k].get(y) is not None
                                                       else None for y in ys]} for k, n in tr_keys]}
    labels["trend_aria"] = f"תפוקה, תשומה והכנסה מחקלאות {ys[0]}-{ly}, במיליארדי ש\"ח"
    labels["trend_cols"] = ["שנה"] + [n for _, n in tr_keys]
    tables["trend"] = [[str(y)] + [(_bn(A[k][y]) if A[k].get(y) is not None else "–")
                                   for k, _ in tr_keys] for y in ys]
    labels["trend_note"] = (f"השנים {ys[0]}-{ly}, מיליארדי ש\"ח במחירים שוטפים (לא מנוכה האינפלציה). "
                            f"כל הודעה מעדכנת את שתי השנים שלפני השנה האחרונה, ומוצג הנתון העדכני ביותר.")
    if g("income") is not None and g("income", py):
        ich = _chg(g("income"), g("income", py))
        t = (f"ההכנסה שמקורה בחקלאות (תוצר נקי בתוספת פיצויים ותקבולים) הסתכמה ב-{ly} ב-"
             f"{_bn(g('income'))} מיליארד ש\"ח, {_ud(ich)} של {fmt.pct_of(abs(ich))} לעומת {py}")
        if g("wages") is not None and g("income"):
            t += (f". {fmt.pct(g('wages') / g('income'))} ממנה ({_bn(g('wages'))} מיליארד ש\"ח) "
                  f"הייתה תמורה למשרות שכיר")
        add("income", t + ".")

    # compensation chart
    comp_parts = [(k, n) for k, n in COMP_PARTS if k in A and any(A[k].get(y) for y in ys)]
    flags["comp"] = bool(comp_parts)
    if comp_parts:
        charts["comp"] = {"x": [str(y) for y in ys],
                          "series": [{"name": n, "data": [_r2((A[k].get(y) or 0) / 1000)
                                                          if A[k].get(y) is not None else None
                                                          for y in ys]} for k, n in comp_parts]}
        labels["comp_aria"] = f"פיצויים ותקבולים לחקלאים לפי סוג {ys[0]}-{ly}, במיליארדי ש\"ח"
        labels["comp_cols"] = ["סוג"] + [str(y) for y in ys]
        tables["comp"] = [[n] + [(fmt.int_he(A[k][y]) if A[k].get(y) is not None else "–")
                                 for y in ys] for k, n in comp_parts]
        labels["comp_note"] = ("תשלומים לחקלאים מעבר למכירת התוצרת, מיליארדי ש\"ח בתרשים ומיליוני ש\"ח "
                               "בטבלה. לא כולל תמיכות ופיצויים ששולמו עבור מחקר ושיווק.")
        tax = A.get("comp_tax", {})
        y0 = ys[0]
        if tax.get(ly) and tax.get(y0) and tax[ly] / tax[y0] >= 2:
            add("comp", f"פיצויי מס רכוש לחקלאים הגיעו ב-{ly} ל-{fmt.int_he(tax[ly])} מיליון ש\"ח, "
                        f"פי {fmt.num_he(tax[ly] / tax[y0], 1)} מ-{y0} "
                        f"({fmt.int_he(tax[y0])} מיליון ש\"ח).")
        elif g("comp") and g("comp", y0):
            cc = _chg(g("comp"), g("comp", y0))
            if abs(cc) >= 20:
                add("comp", f"הפיצויים והתקבולים הנוספים לחקלאים הסתכמו ב-{ly} ב-"
                            f"{fmt.int_he(g('comp'))} מיליון ש\"ח, {_ud(cc)} של "
                            f"{fmt.pct_of(abs(cc))} לעומת {y0}.")

    # ── output by branch ─────────────────────────────────────────────────
    op = [p for p in (_year_table(r, n) for _, n, r in T.get("output", [])) if p]
    flags["branches"] = False
    if op:
        ov, ochg, order = _merge(op)
        oys = sorted({y for lab in ov for y in ov[lab]})
        oly = oys[-1]
        opy = oys[-2] if len(oys) > 1 else None
        group, branches = None, []
        for lab in order:
            if lab == OUT_TOTAL:
                continue
            if lab == OUT_CROPS:
                group = "crops"
                continue
            if lab == OUT_LIVE:
                group = "live"
                continue
            if group and ov[lab].get(oly) is not None:
                branches.append((lab, group))
        if branches:
            flags["branches"] = True
            tot = ov.get(OUT_TOTAL, {}).get(oly) or sum(ov[b][oly] for b, _ in branches)
            srt = sorted(branches, key=lambda b: (-ov[b[0]][oly], b[0]))
            charts["branches"] = {"names": [b for b, _ in srt],
                                  "values": [_r1(ov[b][oly]) for b, _ in srt],
                                  "group": [gp for _, gp in srt]}
            labels["branches_aria"] = f"ערך התפוקה החקלאית לפי ענף בשנת {oly}, במיליוני ש\"ח"
            labels["branches_note"] = (f"ערך התפוקה של כל ענף בשנת {oly}, מיליוני ש\"ח במחירים שוטפים. "
                                       f"כחול: גידולים צמחיים, כחול כהה: בעלי חיים ותוצרתם.")
            tables["branches"] = []
            for b, gp in srt:
                v = ov[b][oly]
                pv = ov[b].get(opy) if opy else None
                c = _chg(v, pv)
                tables["branches"].append([b, fmt.int_he(v), fmt.pct(v / tot) if tot else "–",
                                           fmt.signed_pct(c / 100) if c is not None else "–"])
            labels["branches_cols"] = ["ענף", f"{oly} (מיליון ש\"ח)", "חלק מהתפוקה",
                                       f"שינוי לעומת {opy}" if opy else "שינוי"]
            # leader
            top_b = srt[0][0]
            if tot:
                sh = ov[top_b][oly] / tot
                if sh >= 0.15:
                    second = srt[1][0] if len(srt) > 1 else None
                    t = (f"הענף הגדול בחקלאות הישראלית ב-{oly} היה {_prose(top_b)}, עם "
                         f"{fmt.int_he(ov[top_b][oly])} מיליון ש\"ח ({fmt.pct(sh)} מערך התפוקה)")
                    if second:
                        t += (f", ואחריו {_prose(second)} ({fmt.pct(ov[second][oly] / tot)})")
                    add("leader", t + ".")
                cs = ov.get(OUT_CROPS, {}).get(oly)
                if cs is not None:
                    add("split", f"גידולים צמחיים היוו ב-{oly} {fmt.pct(cs / tot)} מערך התפוקה החקלאית, "
                                 f"ובעלי חיים ותוצרתם {fmt.pct(1 - cs / tot)}.")
            # mover
            if opy:
                movers = [(b, _chg(ov[b][oly], ov[b].get(opy))) for b, _ in branches
                          if ov[b][oly] >= MIN_BRANCH and ov[b].get(opy)]
                movers = [m for m in movers if m[1] is not None and abs(m[1]) >= 5]
                if movers:
                    b, c = max(movers, key=lambda m: (abs(m[1]), m[0]))
                    t = (f"השינוי החד ביותר בין הענפים הגדולים: ערך התפוקה של {_prose(b)} "
                         f"{'עלה' if c > 0 else 'ירד'} ב-{fmt.pct_of(abs(c))} ב-{oly}, ל-"
                         f"{fmt.int_he(ov[b][oly])} מיליון ש\"ח")
                    bp, bq = ochg.get(b, {}).get(oly, (None, None))
                    if bp is not None and bq is not None:
                        t += (f" (מחירים {fmt.signed_pct(bp / 100)}, כמויות {fmt.signed_pct(bq / 100)})")
                    add("mover", t + ".")
            # branch trend (stacked)
            charts["btrend"] = {"x": [str(y) for y in oys],
                                "series": [{"name": b, "group": gp,
                                            "data": [_r1(ov[b].get(y)) for y in oys]}
                                           for b, gp in srt]}
            labels["btrend_aria"] = f"ערך התפוקה לפי ענף {oys[0]}-{oly}, במיליוני ש\"ח"
            labels["btrend_cols"] = ["ענף"] + [str(y) for y in oys]
            tables["btrend"] = [[b] + [(fmt.int_he(ov[b][y]) if ov[b].get(y) is not None else "–")
                                       for y in oys] for b, _ in srt]
            # price vs quantity per branch, newest year
            pq = [(b, ochg.get(b, {}).get(oly, (None, None))) for b, _ in srt]
            pq = [(b, p, q) for b, (p, q) in pq if p is not None and q is not None]
            flags["pq"] = bool(pq)
            if pq:
                charts["pq"] = {"names": [b for b, _, _ in pq], "price": [_r1(p) for _, p, _ in pq],
                                "qty": [_r1(q) for _, _, q in pq]}
                labels["pq_aria"] = f"שינוי המחירים והכמויות לפי ענף בשנת {oly}, באחוזים"
                labels["pq_note"] = (f"כמה מהשינוי בערך התפוקה של כל ענף ב-{oly} בא ממחירים וכמה מכמויות, "
                                     f"באחוזים לעומת {opy or 'השנה הקודמת'}.")
                tables["pq"] = [[b, fmt.signed_pct(p / 100), fmt.signed_pct(q / 100)] for b, p, q in pq]
                labels["pq_cols"] = ["ענף", "שינוי במחיר", "שינוי בכמות"]
    if not flags["branches"]:
        flags["pq"] = False

    # ── inputs by type ───────────────────────────────────────────────────
    ip = [p for p in (_year_table(r, n) for _, n, r in T.get("input", [])) if p]
    flags["inputs"] = False
    if ip:
        iv, ichg, iorder = _merge(ip)
        iys = sorted({y for lab in iv for y in iv[lab]})
        ily = iys[-1]
        ipy = iys[-2] if len(iys) > 1 else None
        types = [lab for lab in iorder if lab not in (IN_TOTAL, IN_PURCHASED, IN_DEP)
                 and iv[lab].get(ily) is not None]
        if types:
            flags["inputs"] = True
            purch = iv.get(IN_PURCHASED, {}).get(ily) or sum(iv[t][ily] for t in types)
            srt = sorted(types, key=lambda t: (-iv[t][ily], t))
            charts["inputs"] = {"names": srt, "values": [_r1(iv[t][ily]) for t in srt]}
            labels["inputs_aria"] = f"התשומה הקנויה בחקלאות לפי סוג בשנת {ily}, במיליוני ש\"ח"
            labels["inputs_note"] = (f"על מה הוציאו החקלאים בשנת {ily}: תשומה קנויה ומתוצרת ביניים "
                                     f"לפי סוג, מיליוני ש\"ח במחירים שוטפים, ללא בלאי וללא תמורה לשכירים.")
            tables["inputs"] = []
            for t in srt:
                p, q = ichg.get(t, {}).get(ily, (None, None))
                tables["inputs"].append([t, fmt.int_he(iv[t][ily]), fmt.pct(iv[t][ily] / purch),
                                         fmt.signed_pct(p / 100) if p is not None else "–",
                                         fmt.signed_pct(q / 100) if q is not None else "–"])
            labels["inputs_cols"] = ["סוג תשומה", f"{ily} (מיליון ש\"ח)", "חלק מהתשומה הקנויה",
                                     "שינוי במחיר", "שינוי בכמות"]
            top = srt[0]
            sh = iv[top][ily] / purch
            if sh >= 0.2:
                add("fodder", f"התשומה הגדולה בחקלאות היא {top}: {fmt.int_he(iv[top][ily])} מיליון ש\"ח "
                              f"ב-{ily}, {fmt.pct(sh)} מכל התשומה הקנויה.")
            tp = iv.get(IN_PURCHASED, {})
            if ipy and tp.get(ily) and tp.get(ipy):
                c = _chg(tp[ily], tp[ipy])
                p, q = ichg.get(IN_PURCHASED, {}).get(ily, (None, None))
                t = (f"התשומה הקנויה בחקלאות הסתכמה ב-{ily} ב-{_bn(tp[ily])} מיליארד ש\"ח, "
                     f"{_ud(c)} של {fmt.pct_of(abs(c))} לעומת {ipy}")
                if p is not None and q is not None:
                    t += f" (מחירים {fmt.signed_pct(p / 100)}, כמויות {fmt.signed_pct(q / 100)})"
                add("inputs", t + ".")

    # ── long-run yearly change ───────────────────────────────────────────
    flags["long"] = False
    ch = [r for _, _, r in T.get("change", [])]
    if ch:
        rows = ch[-1]
        yr = None
        for i, r in enumerate(rows):
            yc = [(j, int(c)) for j, c in enumerate(r) if cbs.YEAR.match(c)]
            if len(yc) >= 5:
                yr = (i, yc)
                break
        if yr is not None:
            i0, yc = yr
            series = {}
            for r in rows[i0 + 1:]:
                lab = next((c for c in r if c and cbs.num(c) is None), "")
                if lab in ("סך הכל", "גידולים צמחיים", "בעלי חיים"):
                    series[lab] = [_r2(cbs.val(r, j)) for j, _ in yc]
            if "סך הכל" in series:
                flags["long"] = True
                lx = [y for _, y in yc]
                names = {"סך הכל": "סך הכל", "גידולים צמחיים": "גידולים צמחיים",
                         "בעלי חיים": "בעלי חיים ותוצרתם"}
                keys = [k for k in ("סך הכל", "גידולים צמחיים", "בעלי חיים") if k in series]
                charts["long"] = {"x": [str(y) for y in lx],
                                  "series": [{"name": names[k], "data": series[k]} for k in keys]}
                labels["long_aria"] = f"אחוז השינוי השנתי בערך התפוקה החקלאית {lx[0]}-{lx[-1]}"
                labels["long_cols"] = ["שנה"] + [names[k] for k in keys]
                tables["long"] = [[str(y)] + [(fmt.signed_pct(series[k][n] / 100)
                                               if series[k][n] is not None else "–") for k in keys]
                                  for n, y in enumerate(lx)]
                tot = [v for v in series["סך הכל"] if v is not None]
                if len(tot) >= 5:
                    idx = 1.0
                    for v in tot:
                        idx *= 1 + v / 100
                    neg = sum(1 for v in tot if v < 0)
                    labels["long_note"] = (f"אחוז השינוי בערך התפוקה (במחירים שוטפים) בכל שנה לעומת "
                                           f"קודמתה, {lx[0]}-{lx[-1]}.")
                    if abs(idx - 1) >= 0.05:
                        add("long", f"בין {lx[0] - 1} ל-{lx[-1]} {'עלה' if idx > 1 else 'ירד'} ערך "
                                    f"התפוקה החקלאית (במחירים שוטפים) בכ-"
                                    f"{fmt.pct_of(abs(idx - 1) * 100, 0)} במצטבר. ב-{neg} מתוך "
                                    f"{len(tot)} השנים נרשמה ירידה לעומת השנה הקודמת.")
                else:
                    labels["long_note"] = "אחוז השינוי בערך התפוקה בכל שנה לעומת קודמתה."

    # ── insight card + callouts ──────────────────────────────────────────
    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    chg_txt = (f", {_ud(out_chg)} של {fmt.pct_of(abs(out_chg))} לעומת {py}"
               if out_chg is not None else "")
    labels["lede"] = (f"כמה מייצרת החקלאות בישראל, באילו ענפים, על מה מוציאים החקלאים וכמה הם מרוויחים. "
                      f"הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על החקלאות "
                      f"בישראל, ומתעדכנים עם כל הודעה חדשה. ערך התפוקה החקלאית ב-{ly} היה "
                      f"{_bn(out_l)} מיליארד ש\"ח{chg_txt}.")
    summary = (f"החקלאות בישראל לפי הלמ\"ס: ערך תפוקה של {_bn(out_l)} מיליארד ש\"ח ב-{ly}{chg_txt}. "
               f"תפוקה לפי ענף, תשומות, הכנסה מחקלאות ופיצויים.")
    desc = (f"ערך התפוקה החקלאית בישראל ב-{ly}: {_bn(out_l)} מיליארד ש\"ח{chg_txt}. "
            f"פירוט לפי ענף (ירקות, מטעים, עופות, בקר), תשומות והכנסה.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{min(ys[0], int(charts['long']['x'][0]) if flags['long'] else ys[0])}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "החקלאות בישראל: ערך התפוקה לפי ענף | נתוני הלמ\"ס",
                "description": desc,
                "name": "החקלאות בישראל",
                "alternate_names": ["ערך התפוקה החקלאית", "חשבון ענף החקלאות",
                                    "תפוקה חקלאית בישראל", "הכנסה מחקלאות"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top,
        "callouts": callouts,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
