"""סיווגי CPC — the Cooperative Patent Classification scheme itself.

One row per CPC group code (the subgroups; main groups "…/00" appear only
as parents): its English heading, its parent code, the parallel IPC code
(14-char packed form, empty when CPC has no IPC counterpart) and its
subclass. This is a code table, not usage data — the sibling dataset
6e207fff holds the codes assigned to Israeli applications. The page shows
the shape of the scheme: where it is large, how deep it nests, how far it
goes beyond IPC (subdivisions, 2000-series indexing codes, the Y section).

Hierarchy level = number of parent hops up to the main group (CPC "dots").
The scheme is revised a few times a year; codes come and go, new
subclasses appear — everything is derived from the code strings, Hebrew
names are a lookup with a code fallback.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"

SECTIONS = ["A", "B", "C", "D", "E", "F", "G", "H", "Y"]
SECTION_HE = {
    "A": "צרכי אנוש",
    "B": "פעולות ביצוע ותובלה",
    "C": "כימיה ומטלורגיה",
    "D": "טקסטיל ונייר",
    "E": "מבנים קבועים",
    "F": "הנדסת מכונות, תאורה, חימום ונשק",
    "G": "פיזיקה",
    "H": "חשמל",
    "Y": "תיוג רוחבי וטכנולוגיות חדשות",
}
# Shared with recipes/6e207fff (CPC per application), extended for the
# classes that are large in the scheme itself.
CLASS_HE = {
    "A01": "חקלאות", "A23": "מזון", "A24": "טבק ועישון", "A45": "חפצים אישיים ותיקים",
    "A47": "ריהוט וציוד ביתי", "A61": "רפואה והיגיינה", "A63": "ספורט ומשחקים",
    "B01": "תהליכים פיזיקליים וכימיים", "B05": "ריסוס וציפוי", "B23": "עיבוד מתכות",
    "B29": "עיבוד פלסטיק", "B32": "מוצרים שכבתיים", "B33": "ייצור תוספתי", "B41": "דפוס",
    "B60": "כלי רכב", "B64": "תעופה וחלל", "B65": "הובלה ואריזה", "B82": "ננוטכנולוגיה",
    "C01": "כימיה אי-אורגנית", "C02": "טיפול במים", "C04": "מלט וקרמיקה",
    "C07": "כימיה אורגנית", "C08": "פולימרים", "C09": "צבעים ודבקים", "C10": "דלקים ושמנים",
    "C12": "ביוכימיה ומיקרוביולוגיה", "C23": "ציפוי מתכות",
    "D01": "סיבים וחוטים", "D03": "אריגה", "D04": "קליעה, סריגה ולבד", "D06": "טיפול בטקסטיל וכביסה",
    "D07": "חבלים וכבלים", "D21": "ייצור נייר",
    "E01": "כבישים ומסילות", "E02": "הנדסה הידראולית ויסודות", "E04": "בנייה",
    "E05": "מנעולים ופרזול", "E06": "דלתות וחלונות", "E21": "קידוח וכרייה",
    "F01": "מכונות ומנועים", "F02": "מנועי בעירה", "F04": "משאבות", "F16": "רכיבי מכונות",
    "F23": "מבערים ובעירה", "F24": "חימום ואוורור", "F41": "נשק", "F42": "תחמושת ופיצוץ",
    "G01": "מדידה ובדיקה", "G02": "אופטיקה", "G03": "צילום והקרנה",
    "G05": "בקרה וויסות", "G06": "מחשוב", "G08": "איתות", "G09": "הוראה ותצוגה",
    "G10": "אקוסטיקה", "G11": "אחסון מידע", "G16": "מידע ותקשוב ייעודיים",
    "H01": "רכיבים חשמליים", "H02": "הפקת חשמל והמרתו", "H03": "מעגלים אלקטרוניים",
    "H04": "תקשורת", "H05": "טכניקות חשמל", "H10": "התקני מוליכים למחצה",
    "Y02": "טכנולוגיות אקלים", "Y04": "תקשוב לרשת החשמל", "Y10": "תיוג טכני רוחבי",
}
SUBCLASS_HE = {
    "A01G": "גידול צמחים וגננות", "A01K": "גידול בעלי חיים ודגה",
    "A01N": "קוטלי מזיקים ומווסתי צמחים", "A01P": "פעילות ביולוגית של חומרים לחקלאות",
    "A23L": "מזון ותוספי מזון", "A23V": "מפתח אינדקס למזון", "A24B": "טבק",
    "A24F": "מוצרי עישון ואידוי", "A61B": "אבחון וכירורגיה",
    "A61F": "תותבים, חבישות ועזרים רפואיים", "A61J": "מכלים ואמצעים למתן תרופות",
    "A61K": "תכשירים רפואיים וקוסמטיים", "A61L": "חיטוי, עיקור וחומרים לשתלים",
    "A61M": "התקנים להחדרת חומרים לגוף", "A61N": "טיפול בקרינה, חשמל ואור",
    "A61P": "פעילות טיפולית של תרכובות", "A61Q": "תכשירי קוסמטיקה וטיפוח",
    "B01D": "הפרדה וסינון", "B01J": "תהליכים כימיים וזרזים", "B01L": "ציוד מעבדה",
    "B29C": "עיבוד פלסטיק", "B32B": "מוצרים שכבתיים", "B33Y": "ייצור תוספתי (הדפסה בתלת-ממד)",
    "B64C": "כלי טיס", "B64D": "ציוד לכלי טיס", "B65D": "אריזה ומכלים",
    "B65H": "טיפול בנייר, בחוטים ובחומר גמיש",
    "B82Y": "ננוטכנולוגיה", "C01B": "יסודות לא-מתכתיים ותרכובותיהם",
    "C02F": "טיפול במים ושפכים", "C04B": "מלט, קרמיקה וחומרי בנייה",
    "C07B": "שיטות כלליות בכימיה אורגנית",
    "C07C": "תרכובות אציקליות וקרבוציקליות", "C07D": "תרכובות הטרוציקליות",
    "C07F": "תרכובות אורגנו-מתכתיות ואחרות", "C07H": "סוכרים ונוקלאוזידים",
    "C07K": "פפטידים וחלבונים", "C08G": "פולימרים — תגובות עיבוי",
    "C08J": "עיבוד פולימרים", "C08K": "תוספים לפולימרים", "C08L": "הרכבים של פולימרים",
    "C09D": "ציפויים וצבעים", "C12M": "ציוד למיקרוביולוגיה",
    "C12N": "מיקרואורגניזמים, אנזימים והנדסה גנטית", "C12P": "תסיסה וסינתזה אנזימטית",
    "C12Q": "בדיקות באנזימים ובחומצות גרעין", "C12Y": "אנזימים",
    "F41H": "שריון ואמצעי הגנה", "G01B": "מדידת אורך ועובי", "G01N": "בדיקה וניתוח חומרים",
    "G01S": "מכ״ם, ניווט ואיכון", "G02B": "אופטיקה", "G03F": "פוטוליתוגרפיה",
    "G05B": "מערכות בקרה וויסות", "G06F": "עיבוד נתונים דיגיטלי",
    "G06N": "בינה מלאכותית ומודלים חישוביים",
    "G06Q": "מערכות מידע לניהול ומסחר", "G06T": "עיבוד וניתוח תמונה",
    "G06V": "זיהוי תמונה ווידאו", "G11B": "אחסון מידע מבוסס תנועה", "G16B": "ביואינפורמטיקה",
    "G16H": "מידע רפואי ובריאות דיגיטלית", "H01H": "מתגים וממסרים", "H01J": "שפופרות פריקה חשמלית",
    "H01L": "התקני מוליכים למחצה", "H01M": "סוללות ותאי דלק", "H01Q": "אנטנות",
    "H04B": "שידור ותקשורת", "H04L": "העברת מידע דיגיטלי", "H04N": "תקשורת תמונה ווידאו",
    "H04W": "רשתות תקשורת אלחוטיות", "H05B": "חימום ותאורה חשמליים",
    "Y02A": "הסתגלות לשינויי אקלים", "Y02B": "בניינים ומכשירים חסכוניים",
    "Y02C": "לכידה ואחסון של גזי חממה", "Y02D": "תקשוב חסכוני באנרגיה",
    "Y02E": "הפחתת פליטות באנרגיה", "Y02P": "הפחתת פליטות בייצור ובחקלאות",
    "Y02T": "הפחתת פליטות בתחבורה", "Y02W": "פסולת ושפכים",
    "Y04S": "רשתות חשמל חכמות",
    "Y10S": "אוספי אמנות מהסיווג האמריקאי לשעבר",
    "Y10T": "תיוג טכני מהסיווג האמריקאי לשעבר",
}
REL = [
    ("same", "זהה לקוד IPC"),
    ("anc", "פירוט של קוד IPC"),
    ("other", "ממופה לקבוצת IPC אחרת"),
    ("none", "ללא מקביל IPC"),
]
DEPTH_BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 6), (7, None)]
FAN_BUCKETS = [(1, 1), (2, 2), (3, 4), (5, 9), (10, 19), (20, 49), (50, 99), (100, None)]
INDEX_GROUP = 2000          # CPC 2000-series groups are indexing schemes
TOP_SUB = 15
TOP_GROUPS = 15
TOP_CLASSES_PER_SECTION = 6
TOP_CLASS_TABLE = 15
MAX_DEPTH_BARS = 15
CODE_RE = re.compile(r"^([A-HY])(\d\d)([A-Z])\s*(\d+)/(\d+)$")
IPC_RE = re.compile(r"^([A-HY]\d\d[A-Z])(\d{4})(\d{6})$")


def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def code_ltr(c):
    return f"{LRI}{c}{PDI}"


def sub_label(code):
    name = SUBCLASS_HE.get(code)
    return f"{code} · {name}" if name else code


def class_label(code):
    name = CLASS_HE.get(code)
    return f"{code} {name}" if name else code


def sec_label(s):
    return f"{SECTION_HE.get(s, s)} ({s})"


def _norm(s):
    return s.str.strip().str.upper().str.replace(r"\s+", " ", regex=True)


def _ipc_code(s):
    m = IPC_RE.match(s)
    if not m:
        return None
    sg = m.group(3).rstrip("0").ljust(2, "0")
    return f"{m.group(1)} {int(m.group(2))}/{sg}"


def _bucket_label(a, b):
    if b is None:
        return f"{LRI}{a}+{PDI}"
    return f"{a}" if a == b else f"{LRI}{a}–{b}{PDI}"


def _top(counts, k):
    return counts.sort_index().sort_values(ascending=False, kind="stable").head(k)


def _prepare(raw):
    df = pd.DataFrame({
        "code": _norm(raw["סיווג"]),
        "parent": _norm(raw["סיווג אב"]),
        "ipc": raw["מקביל IPC סיווג"].str.strip().str.upper(),
        "desc": raw["תיאור"].str.strip(),
    })
    parts = df["code"].str.extract(CODE_RE)
    df = df[parts[0].notna()].copy()
    parts = parts[parts[0].notna()]
    df["sec"] = parts[0]
    df["cls"] = parts[0] + parts[1]
    df["sub"] = parts[0] + parts[1] + parts[2]
    df["grp"] = parts[3].astype("int64")
    # Duplicate code rows (none today): keep one, deterministically.
    df = df.sort_values(["code", "parent", "ipc", "desc"]).drop_duplicates("code", keep="first")
    return df.reset_index(drop=True)


def _tree(df):
    """Hops from each code up to its main group, and that main group. A
    parent that is not itself a row (the main groups, or a gap) ends the
    chain at level 1. Indexing codes can hang under a regular main group,
    so the root is taken from the chain, not from the code's own number."""
    pmap = df.set_index("code")["parent"]
    codes = pd.Index(df["code"].values)
    dep = pd.Series(pd.NA, index=codes, dtype="Int64")
    root = pd.Series(None, index=codes, dtype="object")
    top = ~df["parent"].isin(pmap.index).values
    dep[top] = 1
    root[top] = df["parent"].values[top]
    for _ in range(60):
        miss = dep.isna()
        if not miss.any():
            break
        par = pmap[miss.values].values
        pd_ = pd.Series(dep.reindex(par).values, index=codes[miss.values], dtype="Int64")
        pr = pd.Series(root.reindex(par).values, index=codes[miss.values])
        ok = pd_.notna()
        dep.loc[pd_.index[ok]] = pd_[ok] + 1
        root.loc[pr.index[ok]] = pr[ok]
    return dep.values, root.values


def _ipc_relation(df):
    """same / anc (IPC code is an ancestor) / other / none."""
    ipc = df["ipc"].map(lambda s: _ipc_code(s) if s else "")
    ipc = ipc.fillna("?")
    pmap = df.set_index("code")["parent"]
    hit = pd.Series(False, index=df.index)
    cur = df["parent"].copy()
    for _ in range(60):
        hit |= (cur == ipc) & (ipc != "")
        nxt = cur.map(pmap)
        if nxt.isna().all():
            break
        cur = nxt.where(nxt.notna(), "")
    rel = pd.Series("other", index=df.index)
    rel[hit] = "anc"
    rel[ipc == df["code"]] = "same"
    rel[df["ipc"] == ""] = "none"
    return rel


# ---------------------------------------------------------------- insights

def ins_lead(sec_counts, total):
    if len(sec_counts) < 3 or total == 0:
        return None
    s = _top(sec_counts, len(sec_counts))
    a, b, z = s.index[0], s.index[1], s.index[-1]
    return (f"הסעיף הגדול ביותר בשיטה הוא {sec_label(a)} עם {n(s.iloc[0])} קודים "
            f"({pct(s.iloc[0] / total * 100)}), ואחריו {sec_label(b)} ({pct(s.iloc[1] / total * 100)}); "
            f"הקטן ביותר הוא {sec_label(z)} עם {n(s.iloc[-1])} קודים בלבד.")


def ins_ipc(rel_counts, total):
    none = int(rel_counts.get("none", 0))
    same = int(rel_counts.get("same", 0))
    anc = int(rel_counts.get("anc", 0))
    with_ipc = total - none
    if total == 0 or with_ipc == 0 or none / total < 0.1:
        return None
    return (f"ל-{n(none)} קודים ({pct(none / total * 100)}) אין מקביל בסיווג הבינלאומי IPC — הם קיימים "
            f"רק ב-CPC. מבין הקודים שיש להם מקביל, רק {pct(same / with_ipc * 100)} זהים לקוד IPC, "
            f"ו-{pct(anc / with_ipc * 100)} הם פירוט עדין יותר של קוד IPC רחב.")


def ins_indexing(df, full_index_subs):
    idx = df["grp"] >= INDEX_GROUP
    share = idx.mean() if len(df) else 0
    if share < 0.1:
        return None
    no_ipc = (df.loc[idx, "ipc"] == "").mean()
    tail = (f" {n(full_index_subs)} תתי-סעיפים בנויים כולם מקודי מפתוח בלבד." if full_index_subs else "")
    return (f"{pct(share * 100)} מהקודים ({n(idx.sum())}) הם קודי מפתוח (קבוצות {n(INDEX_GROUP)} ומעלה), "
            f"שמשמשים לתיוג היבטים נוספים של ההמצאה ולא לסיווגה העיקרי; ל-{pct(no_ipc * 100)} מהם "
            f"אין מקביל IPC.{tail}")


def ins_biggest(grp_counts, sec_counts, total):
    if grp_counts.empty or total == 0:
        return None
    g, v = grp_counts.index[0], int(grp_counts.iloc[0])
    if v / total < 0.01:
        return None
    sub = g[:4]
    tags = [SUBCLASS_HE[sub]] if sub in SUBCLASS_HE else []
    m = re.search(r" (\d+)/", g)
    if m and int(m.group(1)) >= INDEX_GROUP:
        tags.insert(0, "תכנית מפתוח")
    name = f" ({', '.join(tags)})" if tags else ""
    smaller = _top(sec_counts, len(sec_counts))
    smaller = smaller[smaller < v]
    tail = (f" — יותר מכל הסעיף {sec_label(smaller.index[-1])}" if len(smaller) and smaller.index[-1] != g[0]
            else "")
    return (f"קבוצה ראשית אחת, {code_ltr(g)}{name}, מכילה {n(v)} קבוצות-משנה, "
            f"{pct(v / total * 100)} מכל קודי השיטה{tail}.")


def ins_depth(dep_sec, max_dep, deepest_sub):
    if len(dep_sec) < 3:
        return None
    s = dep_sec.sort_index().sort_values(ascending=False, kind="stable")
    hi, lo = s.index[0], s.index[-1]
    if s.iloc[0] - s.iloc[-1] < 0.5:
        return None
    return (f"העץ עמוק במיוחד בסעיף {sec_label(hi)}: בממוצע {s.iloc[0]:.1f} רמות מתחת לקבוצה הראשית, "
            f"לעומת {s.iloc[-1]:.1f} בסעיף {sec_label(lo)}. הענף העמוק ביותר מגיע ל-{n(max_dep)} רמות, "
            f"בתת-הסעיף {deepest_sub}.")


def ins_leaves(leaf_share, kids, total):
    if total == 0 or leaf_share < 0.5 or kids.empty:
        return None
    top_p, top_v = kids.index[0], int(kids.iloc[0])
    return (f"{pct(leaf_share * 100)} מהקודים הם עלים — קצה הענף, ללא קודים מתחתיהם. לקוד אב טיפוסי "
            f"יש {n(kids.median())} קודי-משנה ישירים, אבל לקוד {code_ltr(top_p)} יש {n(top_v)}.")


def ins_fragments(df):
    if df.empty:
        return None
    lc = df["desc"].str.match(r"^[a-z]")
    share = lc.mean()
    if share < 0.25:
        return None
    return (f"{pct(share * 100)} מכותרות הקודים פותחות באות קטנה — המשך של כותרת קוד האב (כמו "
            f"\"for\" או \"by\"), שמובן רק יחד עם הרמות שמעליו.")


def ins_concentration(sub_counts, total):
    if len(sub_counts) < 20 or total == 0:
        return None
    top10 = int(sub_counts.head(10).sum())
    if top10 / total < 0.2:
        return None
    return (f"עשרת תתי-הסעיפים הגדולים מחזיקים {pct(top10 / total * 100)} מהקודים, מתוך "
            f"{n(len(sub_counts))} תתי-סעיפים; בתת-סעיף חציוני יש {n(sub_counts.median())} קודים בלבד.")


def ins_y(df):
    y = df[df["sec"] == "Y"]
    if len(y) < 50:
        return None
    legacy = y["cls"] == "Y10"
    share = legacy.mean()
    if share < 0.5:
        return None
    rest = y[~legacy]
    no_ipc = (y["ipc"] == "").mean()
    tail = (f" שאר {n(len(rest))} הקודים מתייגים טכנולוגיות להפחתת פליטות והסתגלות לאקלים ורשתות חכמות."
            if len(rest) else "")
    ipc_txt = ("ולאף אחד מהם אין מקביל IPC" if no_ipc >= 0.9995
               else f"ול-{pct(no_ipc * 100)} מהם אין מקביל IPC")
    return (f"בסעיף Y, הייחודי ל-CPC, יש {n(len(y))} קודים, {ipc_txt}. "
            f"{pct(share * 100)} מהם שייכים ל-Y10, שמשמר את הסיווג האמריקאי הישן.{tail}")


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["cpc"]
    rows_total = len(raw)
    df = _prepare(raw)
    total = len(df)
    df["dep"], df["main"] = _tree(df)
    df = df[df["dep"].notna()].copy()
    df["dep"] = df["dep"].astype("int64")
    df["rel"] = _ipc_relation(df).values
    is_parent = df["code"].isin(set(df["parent"]))
    df["leaf"] = ~is_parent
    total = len(df)

    sec_counts = df["sec"].value_counts()
    secs = [s for s in SECTIONS if s in sec_counts.index] + sorted(set(sec_counts.index) - set(SECTIONS))
    rel_counts = df["rel"].value_counts()

    # sections × IPC relation
    ct = pd.crosstab(df["sec"], df["rel"]).reindex(index=secs, columns=[k for k, _ in REL], fill_value=0)
    sections = {
        "names": [sec_label(s) for s in secs],
        "series": [{"name": nm, "data": [int(v) for v in ct[k]]} for k, nm in REL],
    }
    sec_table = [{"name": sec_label(s), "total": n(sec_counts[s]),
                  "cells": [n(ct.loc[s, k]) for k, _ in REL],
                  "none_share": f"{ct.loc[s, 'none'] / max(sec_counts[s], 1) * 100:.1f}%"} for s in secs]

    # treemap: section -> top classes
    cls_counts = df.groupby(["sec", "cls"]).size().reset_index(name="n")
    cls_counts = cls_counts.sort_values(["n", "cls"], ascending=[False, True])
    tree = []
    for s in secs:
        sub = cls_counts[cls_counts["sec"] == s]
        kids = [{"name": class_label(r.cls), "value": int(r.n)}
                for r in sub.head(TOP_CLASSES_PER_SECTION).itertuples()]
        rest = int(sub["n"].iloc[TOP_CLASSES_PER_SECTION:].sum())
        if rest:
            kids.append({"name": f"אחר ({s})", "value": rest})
        tree.append({"name": sec_label(s), "value": int(sub["n"].sum()), "children": kids})
    class_table = [{"code": r.cls, "name": CLASS_HE.get(r.cls, "—"), "section": SECTION_HE.get(r.sec, r.sec),
                    "count": n(r.n), "share": f"{r.n / total * 100:.1f}%"}
                   for r in cls_counts.head(TOP_CLASS_TABLE).itertuples()]

    # subclasses: regular vs indexing codes
    df["idx"] = df["grp"] >= INDEX_GROUP
    sub_counts = _top(df["sub"].value_counts(), len(df))
    sub_idx = df[df["idx"]]["sub"].value_counts()
    top_sub = sub_counts.head(TOP_SUB)
    subclasses = {
        "names": [sub_label(s) for s in top_sub.index],
        "regular": [int(top_sub[s] - sub_idx.get(s, 0)) for s in top_sub.index],
        "index": [int(sub_idx.get(s, 0)) for s in top_sub.index],
    }
    sub_table = [{"name": sub_label(s), "count": n(top_sub[s]), "index": n(sub_idx.get(s, 0)),
                  "share": f"{top_sub[s] / total * 100:.1f}%"} for s in top_sub.index]
    full_index_subs = int(sum(1 for s, v in sub_counts.items() if sub_idx.get(s, 0) == v))

    # scatter: every subclass — size vs share without IPC
    sub_none = df[df["rel"] == "none"]["sub"].value_counts()
    sub_sec = {s: s[0] for s in sub_counts.index}
    scatter = []
    for s in secs:
        pts = []
        for code in sorted(c for c in sub_counts.index if sub_sec[c] == s):
            v = int(sub_counts[code])
            pts.append([v, round(float(sub_none.get(code, 0)) / v * 100, 1), code])
        scatter.append({"name": sec_label(s), "data": pts})

    # hierarchy depth
    max_dep = int(df["dep"].max())
    cap = min(max_dep, MAX_DEPTH_BARS)
    dlev = df["dep"].clip(upper=cap)
    dep_counts = dlev.value_counts().reindex(range(1, cap + 1), fill_value=0)
    leaf_by_dep = df.groupby(dlev)["leaf"].mean().reindex(range(1, cap + 1)).fillna(0)
    dep_names = [str(i) if (i < cap or cap == max_dep) else f"{LRI}{i}+{PDI}" for i in range(1, cap + 1)]
    depth = {"names": dep_names, "values": [int(v) for v in dep_counts],
             "leaf": [round(float(v) * 100, 1) for v in leaf_by_dep]}
    dep_sec = df.groupby("sec")["dep"].mean().round(2)
    deepest = df[df["dep"] == max_dep]["sub"].value_counts()
    deepest_sub = sub_label(_top(deepest, 1).index[0])

    # depth mix per section
    def dbucket(d):
        for a, b in DEPTH_BUCKETS:
            if d >= a and (b is None or d <= b):
                return _bucket_label(a, b)
        return _bucket_label(*DEPTH_BUCKETS[-1])
    dnames = [_bucket_label(a, b) for a, b in DEPTH_BUCKETS]
    df["dbk"] = df["dep"].map(dbucket)
    dct = pd.crosstab(df["sec"], df["dbk"]).reindex(index=secs, columns=dnames, fill_value=0)
    dtot = dct.sum(axis=1).replace(0, 1)
    depth_sec = {"names": [sec_label(s) for s in secs],
                 "series": [{"name": f"רמה {b}", "data": [round(float(v), 1) for v in dct[b] / dtot * 100]}
                            for b in dnames],
                 "mean": [float(dep_sec.get(s, 0)) for s in secs]}
    depth_sec_table = [{"name": sec_label(s), "mean": f"{dep_sec.get(s, 0):.1f}",
                        "cells": [f"{dct.loc[s, b] / dtot[s] * 100:.1f}%" for b in dnames]} for s in secs]

    # largest main groups
    grp_counts = _top(df["main"].value_counts(), len(df))
    top_g = grp_counts.head(TOP_GROUPS)
    groups = {"names": [f"{g} · {SUBCLASS_HE[g[:4]]}" if g[:4] in SUBCLASS_HE else g for g in top_g.index],
              "values": [int(v) for v in top_g.values]}
    groups_table = [{"code": g, "name": SUBCLASS_HE.get(g[:4], "—"), "count": n(v),
                     "share": f"{v / total * 100:.1f}%"} for g, v in top_g.items()]

    # fan-out: direct children per parent code (main groups included)
    kids = _top(df["parent"].value_counts(), len(df))
    fan = []
    for a, b in FAN_BUCKETS:
        m = kids >= a
        if b is not None:
            m &= kids <= b
        fan.append((_bucket_label(a, b), int(m.sum())))
    leaf_share = float(df["leaf"].mean())

    # Y section
    y = df[df["sec"] == "Y"]
    y_counts = _top(y["sub"].value_counts(), len(y)) if len(y) else pd.Series(dtype="int64")
    ychart = {"names": [sub_label(s) for s in y_counts.index], "values": [int(v) for v in y_counts.values]}
    y_table = [{"name": sub_label(s), "count": n(v)} for s, v in y_counts.items()]

    n_main = int(df["main"].nunique())
    n_sub = int(df["sub"].nunique())
    none_share = float(rel_counts.get("none", 0)) / total * 100

    rules = [
        ("lead", ins_lead(sec_counts, total)),
        ("ipc", ins_ipc(rel_counts, total)),
        ("indexing", ins_indexing(df, full_index_subs)),
        ("biggest", ins_biggest(grp_counts, sec_counts, total)),
        ("concentration", ins_concentration(sub_counts, total)),
        ("depth", ins_depth(dep_sec, max_dep, deepest_sub)),
        ("leaves", ins_leaves(leaf_share, kids, total)),
        ("y", ins_y(df)),
        ("fragments", ins_fragments(df)),
    ]
    insights = [{"id": i, "text_he": s} for i, s in rules if s]

    kpis = {
        "codes": {"value": rows_total, "display": n(rows_total), "tone": "brand"},
        "main": {"value": n_main, "display": n(n_main), "tone": "brand"},
        "subclasses": {"value": n_sub, "display": n(n_sub), "tone": "brand"},
        "none": {"value": round(none_share, 1), "display": f"{none_share:.1f}%", "tone": "info"},
    }

    lead_sec = _top(sec_counts, 1).index[0]
    labels = {
        "lede": (f"מערכת הסיווג הפטנטי המשותפת CPC, שבה רשות הפטנטים מסווגת בקשות פטנט לפי תחום טכנולוגי: "
                 f"{n(total)} קודי סיווג תחת {n(n_main)} קבוצות ראשיות, ב-{n(n_sub)} תתי-סעיפים ו-{len(secs)} "
                 f"סעיפים. לכל קוד כותרת באנגלית, קוד אב שמעליו בעץ והמקביל שלו בסיווג הבינלאומי IPC, אם יש. "
                 f"העץ מגיע לעומק של {n(max_dep)} רמות. זו טבלת הקודים עצמה — השימוש בהם בבקשות הישראליות "
                 f"מוצג במאגר סיווגי CPC לבקשות פטנט."),
        "sections_note": ("מספר הקודים בכל סעיף, לפי היחס לסיווג הבינלאומי IPC: קוד זהה, פירוט של קוד IPC רחב "
                          "יותר (קוד ה-IPC הוא אחד מאבותיו בעץ), מיפוי לקבוצת IPC אחרת, או קוד שאין לו מקביל."),
        "sections_aria": (f"תרשים עמודות מוערם: קודי CPC לפי סעיף ולפי היחס ל-IPC. הסעיף הגדול: "
                          f"{sec_label(lead_sec)}."),
        "sections_caption": "קודי CPC לפי סעיף ולפי היחס לסיווג IPC.",
        "tree_note": (f"כל הקודים לפי סעיף ומחלקה ({TOP_CLASSES_PER_SECTION} המחלקות הגדולות בכל סעיף, "
                      f"השאר תחת אחר)."),
        "tree_aria": "מפת עצים: קודי CPC לפי סעיף ומחלקה.",
        "classes_caption": f"{len(class_table)} המחלקות הגדולות לפי מספר קודים.",
        "sub_note": (f"{len(top_sub)} תתי-הסעיפים הגדולים מתוך {n(n_sub)}, בהפרדה בין קבוצות סיווג רגילות "
                     f"לקודי מפתוח (קבוצות {n(INDEX_GROUP)} ומעלה)."),
        "sub_aria": f"תרשים עמודות אופקי מוערם: {len(top_sub)} תתי-הסעיפים הגדולים. במקום הראשון {top_sub.index[0]}.",
        "sub_caption": "תתי-הסעיפים הגדולים, מספר קודים ומתוכם קודי מפתוח.",
        "scatter_note": (f"כל נקודה היא תת-סעיף ({n(n_sub)} בסך הכול): גודלו במספר קודים (ציר לוגריתמי) "
                         f"ושיעור הקודים בו שאין להם מקביל IPC. בראש הציר — תתי-סעיפים שקיימים כמעט רק ב-CPC."),
        "scatter_aria": "תרשים פיזור: תתי-סעיפים לפי מספר קודים ושיעור הקודים ללא מקביל IPC.",
        "depth_note": ("רמה היא מספר הצעדים מהקוד עד הקבוצה הראשית שמעליו (\"נקודות\" בסימון CPC). "
                       "עמודות: מספר הקודים בכל רמה. קו: שיעור העלים — קודים שאין מתחתיהם קודים נוספים."),
        "depth_aria": f"תרשים משולב: קודים ושיעור עלים לפי רמה בעץ, עד רמה {n(max_dep)}.",
        "depth_caption": "קודים ושיעור עלים לפי רמה בעץ הסיווג.",
        "depth_sec_note": "התפלגות הקודים בכל סעיף לפי רמת העומק, ועומק ממוצע.",
        "depth_sec_aria": (f"תרשים עמודות מוערם באחוזים: עומק הקודים בכל סעיף. העמוק ביותר: "
                           f"{sec_label(dep_sec.sort_index().sort_values(ascending=False, kind='stable').index[0])}."),
        "depth_sec_caption": "שיעור הקודים בכל רמת עומק ועומק ממוצע, לפי סעיף.",
        "groups_note": (f"{len(top_g)} הקבוצות הראשיות עם הכי הרבה קבוצות-משנה, מתוך {n(n_main)}. "
                        f"קבוצות ראשיות של {n(INDEX_GROUP)} ומעלה הן תכניות מפתוח."),
        "groups_aria": f"תרשים עמודות אופקי: {len(top_g)} הקבוצות הראשיות הגדולות. במקום הראשון {top_g.index[0]}.",
        "groups_caption": "הקבוצות הראשיות הגדולות לפי מספר קבוצות-משנה.",
        "fan_note": (f"מספר קודי האב (כולל קבוצות ראשיות) לפי מספר קודי-המשנה הישירים שלהם. "
                     f"{pct(leaf_share * 100)} מהקודים הם עלים."),
        "fan_aria": f"תרשים עמודות: קודי אב לפי מספר קודי-משנה ישירים. החציון {n(kids.median())}.",
        "fan_caption": "קודי אב לפי מספר קודי-המשנה הישירים.",
        "y_note": ("סעיף Y קיים רק ב-CPC: Y02 ו-Y04 מתייגים טכנולוגיות אקלים ורשתות חכמות, ו-Y10 משמר את "
                   "הסיווג האמריקאי הישן. ציר לוגריתמי."),
        "y_aria": "תרשים עמודות אופקי: קודים בכל תת-סעיף של סעיף Y, בציר לוגריתמי.",
        "y_caption": "קודים בכל תת-סעיף של סעיף Y.",
    }

    tables = {
        "rel_names": [nm for _, nm in REL],
        "sections": sec_table,
        "classes": class_table,
        "subclasses": sub_table,
        "depth": [{"level": dep_names[i], "count": n(depth["values"][i]), "leaf": f"{depth['leaf'][i]:.1f}%"}
                  for i in range(cap)],
        "depth_sec_names": dnames,
        "depth_sec": depth_sec_table,
        "groups": groups_table,
        "fan": [{"bucket": k, "count": n(v)} for k, v in fan],
        "y": y_table,
    }

    charts = {
        "sections": sections,
        "tree": tree,
        "subclasses": subclasses,
        "scatter": scatter,
        "depth": depth,
        "depth_sec": depth_sec,
        "groups": groups,
        "fan": {"names": [k for k, _ in fan], "values": [v for _, v in fan]},
        "y": ychart,
    }

    return {
        "agent_data": {
            "summary_he": (f"שיטת הסיווג הפטנטי CPC: {n(total)} קודים ב-{n(n_sub)} תתי-סעיפים, עד {n(max_dep)} "
                           f"רמות עומק; {none_share:.1f}% מהקודים קיימים רק ב-CPC וללא מקביל IPC."),
            "dataset_kind": "registry",
            "suggested_tags": ["פטנטים", "סיווגי CPC", "קניין רוחני", "רשות הפטנטים", "סיווג בינלאומי",
                               "טכנולוגיה"],
            "related_ids": ["6e207fff-abef-4f4d-aac7-61e669ba9ad5",
                            "029b6747-551b-47ad-9a05-ef7f7868fcd0",
                            "247efc75-31f2-4b19-bd4e-e670b1bf2783",
                            "1806c96c-9cc4-47bf-98b3-80a18f061f98"],
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"has_y": len(y_counts) >= 2},
    }
