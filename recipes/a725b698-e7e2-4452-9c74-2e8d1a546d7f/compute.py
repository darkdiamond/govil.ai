"""מעבדות מוכרות לביצוע בדיקות בתחום מערכות גילוי וכיבוי אש (כבאות והצלה):
the Fire and Rescue Authority's list of labs recognised to test fire detection
and suppression systems.

One table, one row per (standard, lab) recognition: the standard's free-text
name, the lab's recognition number, its name (spelled inconsistently across
rows: trailing dots, RLM marks, "בע"מ" sometimes dropped, one lab under two
spellings), the recognition's validity date (dd/mm/yyyy) and a free-text scope
note. Every standard also lists bodies with no lab number (the Standards
Institution, and a profession for the municipal flow test); those are counted
apart from the numbered labs, disclosed on the page.

The validity dates are shown as dates only: the recipe has no clock, so it
never says a recognition has expired.
"""
import re

import pandas as pd
from govlib import fmt, frame

TOP_LABS = 24          # lab axis cap (bar chart + matrix); the table lists every lab
TOP_NOTES = 10
MAX_QUARTERS = 16      # validity chart: by quarter up to this many, else by year
SHORT_MAX = 34

_MARKS = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_TRAIL = re.compile(r"[\s.]+$")
_TI = re.compile(r'(?:ת"י|ת״י|תקן ישראלי)\s*(\d{3,5})')
_PART = re.compile(r"חלק\s*(\d+)(?![.\d])")
_PAREN = re.compile(r"\(([^)]*)\)")
QUAL_MAX = 24
_CUT = re.compile(r'\s*(?:עפ"י|עפ״י|על פי|בהתאם ל|\s[–-]\s|\()')
_LEAD = re.compile(r"^ביצוע בדיקות(?:\s+של)?\s*")


def _clean_name(s: str) -> str:
    s = frame.clean(_MARKS.sub("", s))
    return _TRAIL.sub("", s)


def _short_std(name: str, qualify: bool = False) -> str:
    """A short axis label: the standard's subject plus its number. With
    `qualify` (another standard shares the number), keep what tells them
    apart: the parenthetical qualifier and the part number."""
    cut = _CUT.split(name, maxsplit=1)[0].strip() or name
    m = _TI.search(name)
    base = _LEAD.sub("", cut).strip()
    if not base:  # "ביצוע בדיקות על פי תקן ישראלי 921": nothing but the number
        base = cut
        if m and not qualify:
            return f'{cut} לפי ת"י {m.group(1)}'
    if len(base) > SHORT_MAX:
        base = base[:SHORT_MAX - 1].rstrip() + "…"
    qual, part = "", None
    if qualify:
        pm = _PAREN.search(name)
        if pm:
            qual = frame.clean(pm.group(1))
            if len(qual) > QUAL_MAX:
                qual = qual[:QUAL_MAX - 1].rstrip() + "…"
        part = _PART.search(name)
    label = f"{base}, {qual}" if qual else base
    if m:
        label += f' (ת"י {m.group(1)}' + (f" חלק {part.group(1)}" if part else "") + ")"
    elif part:
        label += f" (חלק {part.group(1)})"
    return label


def _unique_labels(names: list[str]) -> dict:
    """Short labels for sorted full names, guaranteed distinct: standards
    sharing a number get qualifiers; any label still shared gets an ordinal
    on every member of its group."""
    nums = {}
    for s in names:
        m = _TI.search(s)
        if m:
            nums[m.group(1)] = nums.get(m.group(1), 0) + 1

    def shared(s):
        m = _TI.search(s)
        return bool(m) and nums[m.group(1)] > 1

    out = {s: _short_std(s, shared(s)) for s in names}
    groups = {}
    for s in names:
        groups.setdefault(out[s], []).append(s)
    used = {lb for lb, g in groups.items() if len(g) == 1}
    for lb, g in sorted(groups.items()):
        if len(g) == 1:
            continue
        for i, s in enumerate(g, start=1):
            cand, k = f"{lb} ({i})", i
            while cand in used:
                k += len(g)
                cand = f"{lb} ({k})"
            used.add(cand)
            out[s] = cand
    return out


def _date(ts) -> str:
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else f"{fmt.int_he(n)} {many}"


def compute(frames):
    df = frames["labs"].copy()
    df["std"] = frame.clean_series(df["certification_standard"].map(lambda s: _MARKS.sub("", s)))
    df["num"] = frame.clean_series(df["lab_number"])
    df["name"] = df["lab_name"].map(_clean_name)
    df["note"] = frame.clean_series(df["comments"].map(lambda s: _MARKS.sub("", s)))
    df["valid"] = pd.to_datetime(frame.clean_series(df["recognition_validity"]),
                                 format="%d/%m/%Y", errors="coerce")
    df = df[df["std"] != ""]
    n_rows = len(df)

    numbered = df[df["num"] != ""].copy()
    others = df[(df["num"] == "") & (df["name"] != "")].copy()

    # Standards: every distinct standard name in the table (numbered or not).
    std_names = sorted(df["std"].unique())
    shorts = _unique_labels(std_names)
    n_std = len(std_names)

    # Lab display name: most frequent cleaned spelling, then longest, then A-Z.
    def pick_name(g):
        c = g.value_counts()
        cand = sorted(c.index, key=lambda v: (-int(c[v]), -len(v), v))
        return cand[0]

    lab_name = numbered.groupby("num")["name"].agg(pick_name).to_dict()
    spellings = numbered.groupby("num")["name"].nunique()
    n_respelled = int((spellings > 1).sum())

    # One recognition per (lab, standard); keep the earliest date and any note.
    rec = numbered.groupby(["num", "std"], sort=True).agg(
        valid=("valid", "min"),
        note=("note", lambda s: " | ".join(sorted({v for v in s if v}))),
    ).reset_index()
    rec["has_note"] = rec["note"] != ""
    n_rec = len(rec)
    labs = sorted(rec["num"].unique(), key=lambda v: (int(v) if v.isdigit() else 10**9, v))
    n_labs = len(labs)

    # ── per standard ─────────────────────────────────────────────────────
    by_std = rec.groupby("std").agg(n=("num", "nunique"), notes=("has_note", "sum"))
    by_std = by_std.reindex(std_names, fill_value=0)
    by_std["n"] = by_std["n"].astype(int)
    by_std["notes"] = by_std["notes"].astype(int)
    std_order = sorted(std_names, key=lambda s: (-int(by_std.loc[s, "n"]), shorts[s]))

    # ── per lab ──────────────────────────────────────────────────────────
    by_lab = rec.groupby("num").agg(n=("std", "nunique"), notes=("has_note", "sum"),
                                    vmin=("valid", "min"), vmax=("valid", "max"))
    lab_order = sorted(labs, key=lambda v: (-int(by_lab.loc[v, "n"]), int(v) if v.isdigit() else 10**9, v))

    def lab_label(v):
        return f"{lab_name[v]} ({v})"

    # ── other bodies (no lab number) ─────────────────────────────────────
    oth = others.groupby("name")["std"].nunique()
    oth_dated = others.groupby("name")["valid"].apply(lambda s: bool(s.notna().any()))
    no_date_others = bool(len(oth_dated)) and not bool(oth_dated.any())
    oth_order = sorted(oth.index, key=lambda v: (-int(oth[v]), v))

    # ── validity buckets ─────────────────────────────────────────────────
    dated = rec.dropna(subset=["valid"]).copy()
    n_undated = n_rec - len(dated)
    validity = None
    if len(dated):
        q = dated["valid"].dt.year * 4 + (dated["valid"].dt.month - 1) // 3
        span_q = int(q.max() - q.min()) + 1
        if span_q <= MAX_QUARTERS:
            dated["bucket"] = q
            keys = list(range(int(q.min()), int(q.max()) + 1))
            labels = [f"רבעון {k % 4 + 1} {k // 4}" for k in keys]
        else:
            dated["bucket"] = dated["valid"].dt.year
            keys = list(range(int(dated["bucket"].min()), int(dated["bucket"].max()) + 1))
            labels = [str(k) for k in keys]
        cnt = dated.groupby("bucket").size().reindex(keys, fill_value=0)
        lcnt = dated.groupby("bucket")["num"].nunique().reindex(keys, fill_value=0)
        validity = {"x": labels, "rec": [int(v) for v in cnt], "labs": [int(v) for v in lcnt],
                    "by_quarter": span_q <= MAX_QUARTERS}

    # ── charts ───────────────────────────────────────────────────────────
    ch_std = {
        "names": [shorts[s] for s in std_order],
        "full": [s for s in std_order],
        "plain": [int(by_std.loc[s, "n"] - by_std.loc[s, "notes"]) for s in std_order],
        "noted": [int(by_std.loc[s, "notes"]) for s in std_order],
    }
    lab_top = lab_order[:TOP_LABS]
    ch_lab = {
        "names": [lab_label(v) for v in lab_top],
        "plain": [int(by_lab.loc[v, "n"] - by_lab.loc[v, "notes"]) for v in lab_top],
        "noted": [int(by_lab.loc[v, "notes"]) for v in lab_top],
        "total": n_std,
    }
    # Matrix: lab numbers × standards; 1 = recognised, 2 = with a scope note.
    # A 4th field indexes the cell's scope note in `notes` (−1: none).
    rec_idx = {(r.num, r.std): r.note for r in rec.itertuples()}
    m_notes = sorted({nt for nt in (rec_idx.get((v, s), "") for v in lab_top for s in std_order) if nt})
    note_ix = {n: i for i, n in enumerate(m_notes)}
    cells = []
    for xi, v in enumerate(lab_top):
        for yi, s in enumerate(std_order):
            if (v, s) in rec_idx:
                nt = rec_idx[(v, s)]
                cells.append([xi, yi, 2 if nt else 1, note_ix[nt] if nt else -1])
    ch_matrix = {
        "x": lab_top,
        "x_names": [lab_name[v] for v in lab_top],
        "y": [shorts[s] for s in std_order],
        "cells": cells,
        "notes": m_notes,
    }
    breadth = by_lab["n"].value_counts()
    breadth = breadth.reindex(range(1, int(breadth.index.max()) + 1), fill_value=0) if len(breadth) else breadth
    ch_breadth = {"x": [str(int(k)) for k in breadth.index], "y": [int(v) for v in breadth]}

    # notes
    note_rows = rec[rec["has_note"]]
    note_counts = frame.ranked(note_rows["note"]) if len(note_rows) else pd.Series(dtype=int)
    n_noted = int(rec["has_note"].sum())

    # ── KPIs ─────────────────────────────────────────────────────────────
    vmin = dated["valid"].min() if len(dated) else None
    vmax = dated["valid"].max() if len(dated) else None
    half = sum(1 for v in labs if by_lab.loc[v, "n"] * 2 >= n_std)
    kpis = {
        "labs": {"value": n_labs, "display": f"{fmt.int_he(n_labs)}", "tone": "brand"},
        "standards": {"value": n_std, "display": f"{fmt.int_he(n_std)}", "tone": "brand"},
        "recs": {"value": n_rec, "display": f"{fmt.int_he(n_rec)}", "tone": "brand"},
        "noted": {"value": round(n_noted / n_rec, 4) if n_rec else 0,
                  "display": fmt.pct(n_noted / n_rec) if n_rec else "–", "tone": "info"},
        "half": {"value": half, "display": f"{fmt.int_he(half)}", "tone": "ok" if half * 2 >= n_labs else "brand"},
        "first": {"value": _date(vmin) if vmin is not None else "",
                  "display": _date(vmin) if vmin is not None else "–", "tone": "warn"},
    }

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_leader():
        if n_labs < 2:
            return None
        top_n = int(by_lab.loc[lab_order[0], "n"])
        tied = [v for v in lab_order if int(by_lab.loc[v, "n"]) == top_n]
        second = next((int(by_lab.loc[v, "n"]) for v in lab_order if int(by_lab.loc[v, "n"]) < top_n), None)
        if len(tied) == 1:
            tail = f", לעומת {fmt.int_he(second)} בלבד במעבדה הבאה" if second is not None and top_n - second >= 2 else ""
            return (f"{lab_name[tied[0]]} (מעבדה מספר {tied[0]}) מוכרת ב-{fmt.int_he(top_n)} מתוך {fmt.int_he(n_std)} התקנים "
                    f"ברשימה, יותר מכל מעבדה אחרת{tail}.")
        if len(tied) <= 4:
            names = fmt.join_he([lab_name[v] for v in tied])
            return f"{fmt.int_he(len(tied))} מעבדות מובילות בהיקף ההכרה, כל אחת ב-{fmt.int_he(top_n)} מתוך {fmt.int_he(n_std)} התקנים: {names}."
        return f"{fmt.int_he(len(tied))} מעבדות מוכרות כל אחת ב-{fmt.int_he(top_n)} מתוך {fmt.int_he(n_std)} התקנים, ההיקף הרחב ביותר ברשימה."

    def ins_widest():
        if n_std < 2:
            return None
        s = std_order[0]
        n = int(by_std.loc[s, "n"])
        nxt = int(by_std.loc[std_order[1], "n"])
        if n < 3 or n == nxt:
            return None
        return (f"התקן עם המבחר הגדול ביותר של מעבדות הוא {shorts[s]}: {fmt.int_he(n)} מעבדות מוכרות לבדיקה לפיו, "
                f"מתוך {fmt.int_he(n_labs)} המעבדות ברשימה.")

    def ins_thin():
        single = [s for s in std_order if int(by_std.loc[s, "n"]) == 1]
        none_ = [s for s in std_order if int(by_std.loc[s, "n"]) == 0]
        parts = []
        if single:
            if len(single) == 1:
                v = rec.loc[rec["std"] == single[0], "num"].iloc[0]
                parts.append(f"בתקן {shorts[single[0]]} מוכרת מעבדה ממוספרת אחת בלבד, {lab_name[v]}")
            else:
                items = []
                for s in sorted(single, key=lambda s: shorts[s]):
                    v = rec.loc[rec["std"] == s, "num"].iloc[0]
                    items.append(f"{shorts[s]} ({lab_name[v]})")
                parts.append(f"ב-{fmt.int_he(len(single))} תקנים מוכרת מעבדה ממוספרת אחת בלבד: {fmt.join_he(items)}")
        if none_:
            word = "תקן אחד" if len(none_) == 1 else f"{fmt.int_he(len(none_))} תקנים"
            parts.append(f"ל{word} ({fmt.join_he([shorts[s] for s in none_])}) אין מעבדה ממוספרת כלל, "
                         "רק גורם ללא מספר מעבדה")
        if not parts:
            return None
        return "; ".join(parts) + "."

    def ins_conc():
        if n_labs < 6:
            return None
        cutoff = int(by_lab.loc[lab_order[2], "n"])
        top = [v for v in lab_order if int(by_lab.loc[v, "n"]) >= cutoff]
        if len(top) * 2 > n_labs:
            return None
        share = sum(int(by_lab.loc[v, "n"]) for v in top) / n_rec
        small = sum(1 for v in labs if int(by_lab.loc[v, "n"]) <= 2)
        tail = f" מנגד, {fmt.int_he(small)} מעבדות מוכרות בתקן אחד או שניים בלבד." if small >= 2 else ""
        if len(top) == 3:
            head = "שלוש המעבדות הרחבות ביותר מחזיקות"
        else:
            head = (f"{fmt.int_he(len(top))} המעבדות המוכרות ב-{fmt.int_he(cutoff)} תקנים או יותר "
                    "(שלוש המובילות ועוד מעבדות שוות להן במקום השלישי) מחזיקות")
        return f"{head} {fmt.pct(share)} מכלל {fmt.int_he(n_rec)} ההכרות של המעבדות הממוספרות.{tail}"

    def ins_valid():
        if vmin is None or n_labs < 2:
            return None
        first_labs = sorted({v for v in dated.loc[dated["valid"] == vmin, "num"]},
                            key=lambda v: (int(v) if v.isdigit() else 10**9, v))
        k = int((dated["valid"] == vmin).sum())
        yr = vmin.year
        n_yr = int((dated["valid"].dt.year == yr).sum())
        labs_yr = dated.loc[dated["valid"].dt.year == yr, "num"].nunique()
        names = fmt.join_he([lab_name[v] for v in first_labs])
        s = (f"תאריך התוקף המוקדם ביותר ברשימה הוא {_date(vmin)} ({names}, "
             f"{_plural(k, 'הכרה אחת', 'הכרות')}). ")
        s += (f"בסך הכול {fmt.int_he(n_yr)} הכרות של {_plural(int(labs_yr), 'מעבדה אחת', 'מעבדות')} "
              f"רשומות בתוקף עד סוף {yr}, והמאוחר ביותר הוא {_date(vmax)}; "
              "כדאי לוודא את תוקף ההכרה מול הרשות לפני הזמנת בדיקה.")
        return s

    def ins_notes():
        if n_noted == 0 or n_rec < 5:
            return None
        cand = [s for s in std_order if int(by_std.loc[s, "n"]) >= 2]
        best = None
        if cand:
            best = max(cand, key=lambda s: (by_std.loc[s, "notes"] / by_std.loc[s, "n"], by_std.loc[s, "n"], shorts[s]))
        s = f"{fmt.int_he(n_noted)} מתוך {fmt.int_he(n_rec)} ההכרות ({fmt.pct(n_noted / n_rec)}) מגיעות עם הערה שמגדירה את היקף ההכרה, למשל סעיפים מסוימים בלבד או סוג מערכת מסוים."
        if best is not None and by_std.loc[best, "notes"] == by_std.loc[best, "n"]:
            s += f" בתקן {shorts[best]} כל {fmt.int_he(by_std.loc[best, 'n'])} ההכרות מסויגות או מפורטות בהערה."
        return s

    def ins_others():
        if not oth_order:
            return None
        v = oth_order[0]
        k = int(oth[v])
        if k * 2 < n_std:
            return None
        cover = "בכל" if k == n_std else f"ב-{fmt.int_he(k)} מתוך"
        nodate = "" if bool(oth_dated[v]) else " וללא תאריך תוקף"
        return (f"{v} מופיע {cover} {fmt.int_he(n_std)} התקנים כגוף בודק, ללא מספר מעבדה{nodate}; "
                "הוא לא נכלל בספירת המעבדות בעמוד.")

    def ins_respell():
        if n_respelled == 0:
            return None
        word = "מעבדה אחת מופיעה" if n_respelled == 1 else f"{fmt.int_he(n_respelled)} מעבדות מופיעות"
        return (f"{word} ברשימה ביותר מכתיב אחד של שמה; העמוד מאחד את השורות לפי מספר המעבדה "
                "ומציג את הכתיב הנפוץ.")

    add("leader", ins_leader())
    add("widest", ins_widest())
    add("thin", ins_thin())
    add("conc", ins_conc())
    add("valid", ins_valid())
    add("notes", ins_notes())
    add("others", ins_others())
    add("respell", ins_respell())

    # ── tables ───────────────────────────────────────────────────────────
    def valid_cell(v):
        a, b = by_lab.loc[v, "vmin"], by_lab.loc[v, "vmax"]
        if pd.isna(a):
            return "–"
        return _date(a) if a == b else f"{_date(a)} / {_date(b)}"

    t_labs = [[lab_name[v], v, f"{fmt.int_he(by_lab.loc[v, 'n'])}", f"{fmt.int_he(by_lab.loc[v, 'notes'])}", valid_cell(v)]
              for v in lab_order]
    t_std = [[s, f"{fmt.int_he(by_std.loc[s, 'n'])}", f"{fmt.int_he(by_std.loc[s, 'notes'])}"] for s in std_order]
    t_lab_chart = [[lab_label(v), f"{fmt.int_he(by_lab.loc[v, 'n'])}", f"{fmt.int_he(by_lab.loc[v, 'notes'])}"]
                   for v in lab_top]
    t_breadth = [[k, f"{fmt.int_he(y)}"] for k, y in zip(ch_breadth["x"], ch_breadth["y"])]
    t_valid = [[x, f"{fmt.int_he(r)}", f"{fmt.int_he(lb)}"] for x, r, lb in zip(validity["x"], validity["rec"], validity["labs"])] if validity else []
    t_notes = []
    for note, c in note_counts.head(TOP_NOTES).items():
        stds = sorted({shorts[s] for s in note_rows.loc[note_rows["note"] == note, "std"]})
        t_notes.append([note, f"{fmt.int_he(c)}", fmt.join_he(stds)])
    t_oth = [[v, f"{fmt.int_he(oth[v])}"] for v in oth_order]

    # ── labels / ledes ───────────────────────────────────────────────────
    def leaders(order, count, label, max_named=3):
        top_n = int(count(order[0]))
        tied = [x for x in order if int(count(x)) == top_n]
        return ([label(x) for x in tied] if len(tied) <= max_named else []), top_n, len(tied)

    std_lead, std_top_n, std_tied = leaders(std_order, lambda x: by_std.loc[x, "n"], lambda x: shorts[x]) \
        if std_order else ([], 0, 0)
    lab_lead, lab_top_n, lab_tied = leaders(lab_order, lambda x: by_lab.loc[x, "n"], lambda x: lab_name[x]) \
        if lab_order else ([], 0, 0)
    if std_tied == 1:
        std_best = f"המבחר הגדול ביותר: {std_lead[0]} ({fmt.int_he(std_top_n)} מעבדות). "
    elif std_lead:
        std_best = f"המבחר הגדול ביותר, {fmt.int_he(std_top_n)} מעבדות בכל אחד: {fmt.join_he(std_lead)}. "
    elif std_tied:
        std_best = f"{fmt.int_he(std_tied)} תקנים חולקים את המבחר הגדול ביותר, {fmt.int_he(std_top_n)} מעבדות בכל אחד. "
    else:
        std_best = ""
    if lab_tied == 1:
        lab_best = f"{lab_lead[0]} מובילה עם {fmt.int_he(lab_top_n)} תקנים. "
    elif lab_lead:
        lab_best = f"{fmt.join_he(lab_lead)} מובילות, עם {fmt.int_he(lab_top_n)} תקנים כל אחת. "
    elif lab_tied:
        lab_best = f"{fmt.int_he(lab_tied)} מעבדות מובילות, עם {fmt.int_he(lab_top_n)} תקנים כל אחת. "
    else:
        lab_best = ""
    n_cells = len(cells)
    capped = n_labs > len(lab_top)
    labels = {
        "lede": (f"הרשות הארצית לכבאות והצלה מפרסמת את רשימת המעבדות המוכרות לבדיקת מערכות גילוי וכיבוי אש "
                 f"וציוד כיבוי אש, לפי תקן. ברשימה {fmt.int_he(n_labs)} מעבדות ממוספרות עם {fmt.int_he(n_rec)} הכרות לפי {fmt.int_he(n_std)} תקנים"
                 + (", ולכל הכרה רשום תאריך תוקף. " if n_rec and n_undated == 0
                    else f", ול-{fmt.int_he(n_rec - n_undated)} מההכרות רשום תאריך תוקף. ")
                 + "בעלי מבנים, מתכננים ויועצי בטיחות משתמשים בה כדי לבחור מעבדה "
                 "שמוסמכת לבדוק את המערכת שלהם."),
        "std_lede": ("כמה מעבדות ממוספרות מוכרות לבדיקה לפי כל תקן. " + std_best
                     + "החלק הכהה מסמן הכרות שמגיעות עם הערת היקף. גופים ללא מספר מעבדה אינם בספירה."),
        "std_aria": f"מספר המעבדות המוכרות לפי תקן, {fmt.int_he(n_std)} תקנים",
        "lab_lede": (f"בכמה תקנים מוכרת כל מעבדה, מתוך {fmt.int_he(n_std)}. "
                     + lab_best
                     + (f"מוצגות {fmt.int_he(len(lab_top))} המעבדות הרחבות ביותר מתוך {fmt.int_he(n_labs)}." if n_labs > len(lab_top) else "")),
        "lab_aria": f"מספר התקנים שבהם מוכרת כל מעבדה, {fmt.int_he(len(lab_top))} מעבדות",
        "matrix_lede": ("מפת ההכרות: כל עמודה היא מעבדה (לפי מספרה) וכל שורה תקן. "
                        + (f"מוצגות {fmt.int_he(len(lab_top))} המעבדות הרחבות ביותר מתוך {fmt.int_he(n_labs)}. " if capped else "")
                        + f"{fmt.int_he(n_cells)} משבצות מלאות מתוך {fmt.int_he(len(lab_top) * n_std)} בתרשים; "
                        "משבצת כהה היא הכרה עם הערת היקף. רחפו מעל משבצת לשם המעבדה ולנוסח ההערה."),
        "matrix_aria": f"מטריצת הכרות: {fmt.int_he(len(lab_top))} מעבדות על פני {fmt.int_he(n_std)} תקנים",
        "breadth_lede": (f"כמה מעבדות מוכרות במספר תקנים נתון. {fmt.int_he(half)} מתוך {fmt.int_he(n_labs)} המעבדות "
                         f"מוכרות לפחות במחצית התקנים."),
        "breadth_aria": "התפלגות המעבדות לפי מספר התקנים שבהם הן מוכרות",
        "valid_lede": ((f"תאריכי התוקף של ההכרות, לפי {'רבעון' if validity['by_quarter'] else 'שנה'}. "
                        f"הטווח: {_date(vmin)} עד {_date(vmax)}. "
                        + (f"{fmt.int_he(n_undated)} הכרות ללא תאריך תקין אינן בתרשים. " if n_undated else "")
                        + "ההכרה פוקעת בתאריך הרשום אלא אם חודשה; יש לבדוק את התוקף העדכני מול הרשות.")
                       if validity else ""),
        "valid_aria": "מספר ההכרות לפי מועד תום התוקף",
        "notes_lede": (f"{fmt.int_he(n_noted)} הכרות מגיעות עם הערה, ובה הגבלה או הרחבה של היקף ההכרה. "
                       f"אלה ההערות הנפוצות ביותר (מוצגות עד {fmt.int_he(TOP_NOTES)})."),
        "notes_cap": "הערות היקף נפוצות להכרות",
        "labs_lede": (f"כל {fmt.int_he(n_labs)} המעבדות הממוספרות, לפי מספר התקנים שבהם הן מוכרות. "
                      "כאשר להכרות של מעבדה יש יותר מתאריך תוקף אחד, מוצגים המוקדם והמאוחר."
                      + (f" {fmt.int_he(n_respelled)} מעבדות מופיעות ביותר מכתיב אחד; מוצג הכתיב הנפוץ." if n_respelled else "")),
        "labs_cap": "רשימת המעבדות המוכרות",
        "oth_lede": ("גופים שמופיעים ברשימה ללא מספר מעבדה" + (" וללא תאריך תוקף" if no_date_others else "")
                     + ", ומספר התקנים שבהם הם מופיעים. "
                     "הם אינם נספרים כמעבדות בעמוד."),
        "oth_cap": "גופים ללא מספר מעבדה",
    }

    # ── agent_data ───────────────────────────────────────────────────────
    lead = lab_name[lab_order[0]] if lab_order else ""
    summary = (f"רשימת המעבדות המוכרות על ידי הרשות הארצית לכבאות והצלה לבדיקת מערכות גילוי וכיבוי אש: "
               f"{fmt.int_he(n_labs)} מעבדות, {fmt.int_he(n_rec)} הכרות לפי {fmt.int_he(n_std)} תקנים"
               + (f", ותאריכי תוקף מ-{_date(vmin)} עד {_date(vmax)}." if vmin is not None else "."))
    desc = (f"איתור מעבדה מוכרת לבדיקת מערכות גילוי וכיבוי אש לפי תקן: {fmt.int_he(n_labs)} מעבדות, "
            f"{fmt.int_he(n_std)} תקנים, תוקף ההכרה של כל מעבדה"
            + (f". המובילה: {lead}." if lead else "."))
    if len(desc) > 150:
        desc = (f"איתור מעבדה מוכרת לבדיקת מערכות גילוי וכיבוי אש לפי תקן: {fmt.int_he(n_labs)} מעבדות, "
                f"{fmt.int_he(n_std)} תקנים ותוקף ההכרה של כל מעבדה.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "מעבדות מוכרות לבדיקת מערכות גילוי וכיבוי אש",
            "description": desc,
            "name": "מעבדות מוכרות לבדיקת מערכות גילוי וכיבוי אש",
            "alternate_names": [
                "מעבדות מוכרות לביצוע בדיקות בתחום מערכות גילוי וכיבוי אש וציוד כיבוי אש",
                "רשימת מעבדות מוכרות כבאות והצלה",
                "מעבדה מוסמכת לבדיקת מערכת גילוי אש",
                "בדיקת מערכת מתזים ומערכות כיבוי אש",
            ],
        },
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"std": ch_std, "lab": ch_lab, "matrix": ch_matrix, "breadth": ch_breadth,
                   "valid": validity or {"x": [], "rec": [], "labs": [], "by_quarter": True}},
        "insights": insights,
        "labels": labels,
        "tables": {"labs": t_labs, "std": t_std, "lab_chart": t_lab_chart, "breadth": t_breadth,
                   "valid": t_valid, "notes": t_notes, "others": t_oth},
        "flags": {"has_valid": validity is not None, "has_notes": bool(t_notes),
                  "has_others": bool(t_oth), "has_labs": n_labs > 0},
        "meta": {"rows": n_rows},
    }
