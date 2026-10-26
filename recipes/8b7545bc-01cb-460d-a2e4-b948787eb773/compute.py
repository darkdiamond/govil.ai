"""סיווגי IPC — the International Patent Classification scheme itself.

One row per IPC group in the current edition: the main groups ("…/00",
whose parent is their subclass) and every subgroup below them, each with
its English heading, its parent code, its subclass and the edition date.
This is a code table, not usage data — the sibling dataset a5b7e889 holds
the IPC codes assigned to Israeli applications, and 8687fefe is the CPC
scheme (which extends IPC). This page shows the shape of the IPC tree:
where it is large, how wide or deep each area is, and how the headings
are written.

Level = number of parent hops from a code up to its main group (level 0 =
the main group, level 1 = one dot, …). The main group is read from the
code string (an IPC subgroup always sits under its own group number), so a
missing intermediate row only shortens one chain. WIPO revises IPC every
January: codes come and go, new subclasses appear and the edition date
changes — everything is derived from the code strings and the data, and
Hebrew names are a lookup with a code fallback.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"

SECTIONS = ["A", "B", "C", "D", "E", "F", "G", "H"]
SECTION_HE = {
    "A": "צרכי אנוש",
    "B": "פעולות ביצוע ותובלה",
    "C": "כימיה ומטלורגיה",
    "D": "טקסטיל ונייר",
    "E": "מבנים קבועים",
    "F": "הנדסת מכונות, תאורה, חימום ונשק",
    "G": "פיזיקה",
    "H": "חשמל",
}
# IPC class titles, abridged into Hebrew (scheme definitions, not data).
CLASS_HE = {
    "A01": "חקלאות", "A21": "אפייה", "A22": "שחיטה ועיבוד בשר", "A23": "מזון ומשקאות",
    "A24": "טבק ועישון", "A41": "ביגוד", "A42": "כובעים", "A43": "הנעלה",
    "A44": "סדקית ותכשיטים", "A45": "חפצים אישיים ותיקים", "A46": "מברשות",
    "A47": "ריהוט וציוד ביתי", "A61": "רפואה והיגיינה", "A62": "הצלה וכיבוי אש",
    "A63": "ספורט ומשחקים",
    "B01": "תהליכים פיזיקליים וכימיים", "B02": "גריסה וטחינה", "B03": "הפרדה רטובה ומגנטית",
    "B04": "צנטריפוגות", "B05": "ריסוס וציפוי", "B06": "תנודות מכניות", "B07": "מיון והפרדת מוצקים",
    "B08": "ניקוי", "B09": "סילוק פסולת מוצקה", "B21": "עיבוד מתכת ללא הסרת חומר",
    "B22": "יציקה ומטלורגיית אבקות", "B23": "מכונות כלים ועיבוד מתכות", "B24": "ליטוש והשחזה",
    "B25": "כלי עבודה ידניים ורובוטים", "B26": "כלי חיתוך", "B27": "עיבוד עץ",
    "B28": "עיבוד מלט ואבן", "B29": "עיבוד פלסטיק", "B30": "מכבשים", "B31": "מוצרי נייר וקרטון",
    "B32": "מוצרים שכבתיים", "B33": "ייצור תוספתי", "B41": "דפוס", "B42": "כריכה ותיוק",
    "B43": "כלי כתיבה ושרטוט", "B44": "אמנות דקורטיבית", "B60": "כלי רכב", "B61": "רכבות",
    "B62": "רכב יבשתי ללא מסילה", "B63": "כלי שיט", "B64": "תעופה וחלל", "B65": "הובלה ואריזה",
    "B66": "הרמה ומעליות", "B67": "מילוי ופתיחה של מכלים", "B68": "ריפוד ואוכפים",
    "B81": "מיקרו-מבנים", "B82": "ננוטכנולוגיה",
    "C01": "כימיה אי-אורגנית", "C02": "טיפול במים", "C03": "זכוכית", "C04": "מלט וקרמיקה",
    "C05": "דשנים", "C06": "חומרי נפץ", "C07": "כימיה אורגנית", "C08": "פולימרים",
    "C09": "צבעים ודבקים", "C10": "דלקים ושמנים", "C11": "שומנים, סבון ודטרגנטים",
    "C12": "ביוכימיה ומיקרוביולוגיה", "C13": "תעשיית הסוכר", "C14": "עורות ופרוות",
    "C21": "ברזל ופלדה", "C22": "מטלורגיה וסגסוגות", "C23": "ציפוי מתכות",
    "C25": "תהליכים אלקטרוליטיים", "C30": "גידול גבישים", "C40": "כימיה צירופית",
    "D01": "סיבים וחוטים", "D02": "עיבוד חוטים", "D03": "אריגה", "D04": "קליעה, סריגה ולבד",
    "D05": "תפירה ורקמה", "D06": "טיפול בטקסטיל וכביסה", "D07": "חבלים וכבלים", "D21": "ייצור נייר",
    "E01": "כבישים ומסילות", "E02": "הנדסה הידראולית ויסודות", "E03": "מים וביוב", "E04": "בנייה",
    "E05": "מנעולים ופרזול", "E06": "דלתות וחלונות", "E21": "קידוח וכרייה",
    "F01": "מכונות ומנועים", "F02": "מנועי בעירה", "F03": "מנועי נוזל ורוח", "F04": "משאבות",
    "F15": "הידראוליקה ופנאומטיקה", "F16": "רכיבי מכונות", "F17": "אחסון והולכת גזים",
    "F21": "תאורה", "F22": "הפקת קיטור", "F23": "מבערים ובעירה", "F24": "חימום ואוורור",
    "F25": "קירור", "F26": "ייבוש", "F27": "תנורים וכבשנים", "F28": "מחלפי חום",
    "F41": "נשק", "F42": "תחמושת ופיצוץ",
    "G01": "מדידה ובדיקה", "G02": "אופטיקה", "G03": "צילום והקרנה", "G04": "מדידת זמן",
    "G05": "בקרה וויסות", "G06": "מחשוב", "G07": "מכונות אוטומטיות ובקרת גישה", "G08": "איתות",
    "G09": "הוראה ותצוגה", "G10": "אקוסטיקה", "G11": "אחסון מידע", "G12": "פרטי מכשירים",
    "G16": "מידע ותקשוב ייעודיים", "G21": "פיזיקה גרעינית",
    "H01": "רכיבים חשמליים", "H02": "הפקת חשמל והמרתו", "H03": "מעגלים אלקטרוניים",
    "H04": "תקשורת", "H05": "טכניקות חשמל", "H10": "התקני מוליכים למחצה",
}
SUBCLASS_HE = {
    "A01B": "עיבוד קרקע", "A01G": "גידול צמחים וגננות", "A01K": "גידול בעלי חיים ודגה",
    "A01N": "קוטלי מזיקים ומווסתי צמחים", "A23L": "מזון ותוספי מזון",
    "A61B": "אבחון וכירורגיה", "A61F": "תותבים, חבישות ועזרים רפואיים",
    "A61K": "תכשירים רפואיים וקוסמטיים", "A61M": "התקנים להחדרת חומרים לגוף",
    "A61P": "פעילות טיפולית של תרכובות", "A63B": "מכשירי ספורט ואימון", "A63F": "משחקים",
    "B01D": "הפרדה וסינון", "B01J": "תהליכים כימיים וזרזים", "B21D": "עיבוד פחים ומתכת",
    "B23K": "הלחמה וריתוך", "B29C": "עיבוד פלסטיק", "B29K": "מפתוח: חומרים בעיבוד פלסטיק",
    "B29L": "מפתוח: מוצרים מפלסטיק", "C12R": "מפתוח: מיקרואורגניזמים", "B41J": "מדפסות", "B60R": "ציוד לכלי רכב",
    "B65D": "אריזה ומכלים", "B65G": "הובלה ושינוע", "B65H": "טיפול בנייר, בחוטים ובחומר גמיש",
    "C01B": "יסודות לא-מתכתיים ותרכובותיהם", "C07C": "תרכובות אציקליות וקרבוציקליות",
    "C07D": "תרכובות הטרוציקליות", "C07F": "תרכובות אורגנו-מתכתיות ואחרות",
    "C07K": "פפטידים וחלבונים", "C08F": "פולימרים — תגובות פילמור", "C08G": "פולימרים — תגובות עיבוי",
    "C08L": "הרכבים של פולימרים", "C09B": "צבענים אורגניים", "C09D": "ציפויים וצבעים",
    "C09K": "חומרים לשימושים מיוחדים", "C10G": "זיקוק נפט", "C12N": "מיקרואורגניזמים, אנזימים והנדסה גנטית",
    "C12P": "תסיסה וסינתזה אנזימטית", "C22C": "סגסוגות", "C23C": "ציפוי מתכות",
    "D06P": "צביעת טקסטיל", "E04B": "מבנים ובנייה כללית", "E05B": "מנעולים",
    "F02M": "אספקת דלק ותערובת למנועים", "F16H": "תמסורות", "F16D": "צימודים, מצמדים ובלמים",
    "F16K": "שסתומים", "G01N": "בדיקה וניתוח חומרים", "G01R": "מדידת גדלים חשמליים",
    "G01S": "מכ״ם, ניווט ואיכון", "G02B": "אופטיקה", "G03G": "אלקטרוגרפיה",
    "G06F": "עיבוד נתונים דיגיטלי", "G06Q": "מערכות מידע לניהול ומסחר", "G06T": "עיבוד וניתוח תמונה",
    "G09G": "בקרת תצוגות", "G11B": "אחסון מידע מבוסס תנועה", "H01F": "מגנטים ושנאים",
    "H01H": "מתגים וממסרים", "H01J": "שפופרות פריקה חשמלית", "H01L": "התקני מוליכים למחצה",
    "H01M": "סוללות ותאי דלק", "H01R": "מחברים חשמליים", "H02K": "מנועים וגנרטורים חשמליים",
    "H02M": "ממירי מתח וזרם", "H03K": "מעגלי פולסים", "H04B": "שידור ותקשורת",
    "H04L": "העברת מידע דיגיטלי", "H04N": "תקשורת תמונה ווידאו", "H04W": "רשתות תקשורת אלחוטיות",
    "H05K": "מעגלים מודפסים ומארזים",
}
LEVEL_BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 4), (5, None)]
FAN_BUCKETS = [(1, 1), (2, 2), (3, 4), (5, 9), (10, 19), (20, 49), (50, None)]
MAX_LEVEL_BARS = 12
TOP_SUB = 15
TOP_GROUPS = 15
TOP_CLASSES_PER_SECTION = 6
TOP_CLASS_TABLE = 15
RESIDUAL_CLASS = 99          # X99: "subject matter not otherwise provided for"
CODE_RE = re.compile(r"^([A-H])(\d\d)([A-Z]) (\d+)/(\d+)$")
RESIDUAL_RE = r"(?i)not provided for in other groups"


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
    name = CLASS_HE.get(code) or ("נושאים שלא סווגו במקום אחר" if code[1:] == str(RESIDUAL_CLASS) else None)
    return f"{code} {name}" if name else code


def sec_label(s):
    return f"{SECTION_HE.get(s, s)} ({s})"


def level_label(lv):
    return "קבוצה ראשית" if lv == 0 else f"רמה {lv}"


def _bucket_label(a, b):
    if b is None:
        return f"{LRI}{a}+{PDI}"
    return f"{a}" if a == b else f"{LRI}{a}–{b}{PDI}"


def _top(counts, k):
    return counts.sort_index().sort_values(ascending=False, kind="stable").head(k)


def _norm(s):
    return s.str.strip().str.upper().str.replace(r"\s+", " ", regex=True)


def _prepare(raw):
    df = pd.DataFrame({
        "code": _norm(raw["סיווג"]),
        "parent": _norm(raw["סיווג אב"]),
        "desc": raw["תיאור הסיווג"].str.strip(),
        "ver": raw["תאריך גרסה"].str.strip(),
    })
    parts = df["code"].str.extract(CODE_RE)
    ok = parts[0].notna()
    df, parts = df[ok].copy(), parts[ok]
    df["sec"] = parts[0]
    df["cls"] = parts[0] + parts[1]
    df["sub"] = parts[0] + parts[1] + parts[2]
    df["grp_no"] = parts[3].astype("int64")
    df["main"] = df["sub"] + " " + parts[3] + "/00"
    df["is_main"] = parts[4].str.fullmatch(r"0+")
    df = df.sort_values(["code", "parent", "desc", "ver"]).drop_duplicates("code", keep="first")
    return df.reset_index(drop=True), int((~ok).sum())


def _levels(df):
    """Hops from each code up to its main group. Main groups are level 0; a
    subgroup whose parent row is absent is placed directly under its main
    group (level 1)."""
    pmap = df.set_index("code")["parent"]
    codes = pd.Index(df["code"].values)
    dep = pd.Series(pd.NA, index=codes, dtype="Int64")
    is_main = df["is_main"].values
    dep[is_main] = 0
    orphan = (~is_main) & ~df["parent"].isin(pmap.index).values
    dep[orphan] = 1
    for _ in range(60):
        miss = dep.isna()
        if not miss.any():
            break
        par = pmap[miss.values].values
        pd_ = pd.Series(dep.reindex(par).values, index=codes[miss.values], dtype="Int64")
        ok = pd_.notna()
        if not ok.any():
            dep[miss.values] = 1      # a cycle or broken chain: treat as one dot
            break
        dep.loc[pd_.index[ok]] = pd_[ok] + 1
    return dep.astype("int64").values


# ---------------------------------------------------------------- insights

def ins_lead(sec_counts, total):
    if len(sec_counts) < 3 or total == 0:
        return None
    s = _top(sec_counts, len(sec_counts))
    a, b, z = s.index[0], s.index[1], s.index[-1]
    if s.iloc[0] / total < 0.15:
        return None
    return (f"הסעיף הגדול ביותר בשיטה הוא {sec_label(a)} עם {n(s.iloc[0])} קודים "
            f"({pct(s.iloc[0] / total * 100)}), ואחריו {sec_label(b)} ({pct(s.iloc[1] / total * 100)}); "
            f"הקטן ביותר הוא {sec_label(z)} עם {n(s.iloc[-1])} קודים בלבד.")


def ins_class(cls_counts, sec_counts, total, n_cls):
    if cls_counts.empty or total == 0:
        return None
    c, v = cls_counts.index[0], int(cls_counts.iloc[0])
    if v / total < 0.03:
        return None
    smaller = sorted((s for s in sec_counts.index if sec_counts[s] < v and s != c[0]),
                     key=lambda s: (-sec_counts[s], s))
    tail = ""
    if len(smaller) == 1:
        tail = f" — יותר מכל הסעיף {sec_label(smaller[0])}"
    elif 2 <= len(smaller) <= 3:
        names = ", ".join(sec_label(s) for s in smaller[:-1]) + " ו" + sec_label(smaller[-1])
        tail = f" — יותר מכל אחד מהסעיפים {names}"
    return (f"מחלקה אחת מתוך {n(n_cls)}, {class_label(c)}, מכילה {n(v)} קודים, "
            f"{pct(v / total * 100)} מהשיטה כולה{tail}.")


def ins_concentration(sub_counts, total):
    if len(sub_counts) < 20 or total == 0:
        return None
    top10 = int(sub_counts.head(10).sum())
    if top10 / total < 0.1:
        return None
    small = int((sub_counts <= 10).sum())
    return (f"עשרת תתי-הסעיפים הגדולים מחזיקים {pct(top10 / total * 100)} מהקודים, מתוך "
            f"{n(len(sub_counts))} תתי-סעיפים; בתת-סעיף חציוני יש {n(sub_counts.median())} קודים, "
            f"ו-{n(small)} תתי-סעיפים מונים עשרה קודים או פחות.")


def ins_biggest(grp_counts, total):
    if grp_counts.empty or total == 0:
        return None
    g, v = grp_counts.index[0], int(grp_counts.iloc[0])
    if v < 50:
        return None
    sub = g[:4]
    name = f" ({SUBCLASS_HE[sub]})" if sub in SUBCLASS_HE else ""
    second = (f"; השנייה, {code_ltr(grp_counts.index[1])}, מונה {n(grp_counts.iloc[1])}"
              if len(grp_counts) > 1 else "")
    return (f"הקבוצה הראשית הגדולה ביותר, {code_ltr(g)}{name}, מתפצלת ל-{n(v)} קבוצות-משנה"
            f"{second}. לקבוצה ראשית חציונית יש {n(grp_counts.median())} קבוצות-משנה בלבד.")


def ins_depth(dep_sec, max_dep, deepest_sub, n_deep):
    if len(dep_sec) < 3:
        return None
    s = dep_sec.sort_index().sort_values(ascending=False, kind="stable")
    hi, lo = s.index[0], s.index[-1]
    if s.iloc[0] - s.iloc[-1] < 0.2:
        return None
    return (f"קבוצות-המשנה בסעיף {sec_label(hi)} יושבות בממוצע {s.iloc[0]:.1f} רמות מתחת לקבוצה הראשית, "
            f"לעומת {s.iloc[-1]:.1f} בסעיף {sec_label(lo)}. הענף העמוק ביותר מגיע ל-{n(max_dep)} רמות, "
            f"בתת-הסעיף {deepest_sub}" + (f" ({n(n_deep)} קודים ברמה זו)." if n_deep > 1 else "."))


def ins_leaves(leaf_share, kids):
    if leaf_share < 0.5 or kids.empty:
        return None
    one = float((kids == 1).mean())
    return (f"{pct(leaf_share * 100)} מהקודים הם עלים — קצה הענף, ללא קודים מתחתיהם. לקוד אב חציוני "
            f"יש {n(kids.median())} קודי-משנה ישירים; {pct(one * 100)} מקודי האב מתפצלים לקוד אחד בלבד, "
            f"ולקוד {code_ltr(kids.index[0])} יש {n(kids.iloc[0])}.")


def ins_fragments(df):
    sub = df[df["lvl"] > 0]
    if sub.empty:
        return None
    lc = sub["desc"].str.match(r"^[a-z]")
    share = float(lc.mean())
    if share < 0.25:
        return None
    by = sub.groupby(sub["lvl"].clip(upper=4))["desc"].apply(lambda s: s.str.match(r"^[a-z]").mean())
    if len(by) < 2:
        return None
    first, last = float(by.iloc[0]), float(by.iloc[-1])
    trend = ""
    if last - first >= 0.1:
        trend = (f" השיעור עולה עם העומק: {pct(first * 100)} ברמה הראשונה לעומת {pct(last * 100)} "
                 f"ברמה {n(by.index[-1])} ומטה.")
    return (f"{pct(share * 100)} מכותרות קבוצות-המשנה פותחות באות קטנה — המשך של כותרת קוד האב "
            f"(כמו \"for\" או \"using\"), שמובן רק יחד עם הרמות שמעליו.{trend}")


def ins_residual(df):
    res = df["desc"].str.contains(RESIDUAL_RE, regex=True)
    n_res = int(res.sum())
    x99 = sorted(df.loc[df["cls"].str[1:] == str(RESIDUAL_CLASS), "cls"].unique())
    if n_res < 20:
        return None
    every = len(x99) == df["sec"].nunique()
    tail = (f" בנוסף, {n(len(x99))} מחלקות {code_ltr(str(RESIDUAL_CLASS))}" + (" — אחת בכל סעיף —" if every else "")
            + " שמורות לנושאים שאין להם מקום אחר בשיטה." if len(x99) >= 3 else "")
    subs = df.loc[res, "sub"].nunique()
    return (f"{n(n_res)} קבוצות, ב-{n(subs)} תתי-סעיפים, הן קבוצות שארית לנושאים שלא נכללו בקבוצות "
            f"האחרות של אותו תת-סעיף.{tail}")


def ins_version(ver_counts, total):
    if ver_counts.empty or total == 0:
        return None
    v = ver_counts.index[0]
    if not re.fullmatch(r"\d{8}", v):
        return None
    d = f"{int(v[6:])}.{int(v[4:6])}.{v[:4]}"
    if len(ver_counts) == 1:
        return (f"כל {n(total)} הקודים שייכים למהדורה אחת של השיטה, {code_ltr(v[:4] + '.' + v[4:6])} "
                f"(בתוקף מ-{d}); המאגר משקף את המהדורה הנוכחית ואינו שומר היסטוריית גרסאות.")
    share = ver_counts.iloc[0] / total
    return (f"הקודים מתחלקים בין {n(len(ver_counts))} תאריכי גרסה; הנפוץ שבהם, {d}, חל על "
            f"{pct(share * 100)} מהם.")


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["ipc"]
    rows_total = len(raw)
    df, n_bad = _prepare(raw)
    df["lvl"] = _levels(df)
    is_parent = df["code"].isin(set(df["parent"]))
    df["leaf"] = ~is_parent
    df["frag"] = df["desc"].str.match(r"^[a-z]")
    total = len(df)

    sec_counts = df["sec"].value_counts()
    secs = [s for s in SECTIONS if s in sec_counts.index] + sorted(set(sec_counts.index) - set(SECTIONS))
    mains = df[df["is_main"]]
    n_main = len(mains)
    n_sub = int(df["sub"].nunique())
    n_cls = int(df["cls"].nunique())

    # sections: main groups vs subgroups, subclasses per section
    main_sec = mains["sec"].value_counts()
    sub_per_sec = df.groupby("sec")["sub"].nunique()
    sections = {
        "names": [sec_label(s) for s in secs],
        "main": [int(main_sec.get(s, 0)) for s in secs],
        "subgroups": [int(sec_counts[s] - main_sec.get(s, 0)) for s in secs],
    }
    sec_table = [{"name": sec_label(s), "subs": n(sub_per_sec.get(s, 0)), "main": n(main_sec.get(s, 0)),
                  "subgroups": n(sec_counts[s] - main_sec.get(s, 0)), "total": n(sec_counts[s]),
                  "share": f"{sec_counts[s] / total * 100:.1f}%"} for s in secs]

    # treemap: section -> top classes
    cc = df.groupby(["sec", "cls"]).size().reset_index(name="n")
    cc = cc.sort_values(["n", "cls"], ascending=[False, True])
    tree = []
    for s in secs:
        sub = cc[cc["sec"] == s]
        kids = [{"name": class_label(r.cls), "value": int(r.n)} for r in sub.head(TOP_CLASSES_PER_SECTION).itertuples()]
        rest = int(sub["n"].iloc[TOP_CLASSES_PER_SECTION:].sum())
        if rest:
            kids.append({"name": f"אחר ({s})", "value": rest})
        tree.append({"name": sec_label(s), "value": int(sub["n"].sum()), "children": kids})
    cls_counts = pd.Series(cc["n"].values, index=cc["cls"].values)
    cls_sub = df.groupby("cls")["sub"].nunique()
    class_table = [{"code": r.cls, "name": CLASS_HE.get(r.cls, "—"), "section": SECTION_HE.get(r.sec, r.sec),
                    "subs": n(cls_sub[r.cls]), "count": n(r.n), "share": f"{r.n / total * 100:.1f}%"}
                   for r in cc.head(TOP_CLASS_TABLE).itertuples()]

    # subclasses: main groups vs subgroups
    sub_counts = _top(df["sub"].value_counts(), len(df))
    sub_main = mains["sub"].value_counts()
    top_sub = sub_counts.head(TOP_SUB)
    subclasses = {
        "names": [sub_label(s) for s in top_sub.index],
        "main": [int(sub_main.get(s, 0)) for s in top_sub.index],
        "subgroups": [int(top_sub[s] - sub_main.get(s, 0)) for s in top_sub.index],
    }
    sub_table = [{"name": sub_label(s), "main": n(sub_main.get(s, 0)), "count": n(top_sub[s]),
                  "share": f"{top_sub[s] / total * 100:.1f}%"} for s in top_sub.index]

    # scatter: every subclass — width (main groups) vs subgroups per main group
    scatter = []
    ratios = {}
    for s in secs:
        pts = []
        for code in sorted(c for c in sub_counts.index if c[0] == s):
            m = int(sub_main.get(code, 0))
            if m == 0:
                continue
            r = round((int(sub_counts[code]) - m) / m, 1)
            ratios[code] = (m, r)
            pts.append([m, r, code])
        scatter.append({"name": sec_label(s), "data": pts})
    widest = sorted(ratios.items(), key=lambda kv: (-kv[1][0], kv[0]))
    deepest_r = sorted(((k, v) for k, v in ratios.items() if v[0] >= 5), key=lambda kv: (-kv[1][1], kv[0]))

    # levels
    max_dep = int(df["lvl"].max())
    cap = min(max_dep, MAX_LEVEL_BARS)
    lv = df["lvl"].clip(upper=cap)
    lv_counts = lv.value_counts().reindex(range(0, cap + 1), fill_value=0)
    leaf_by = df.groupby(lv)["leaf"].mean().reindex(range(0, cap + 1)).fillna(0)
    frag_by = df.groupby(lv)["frag"].mean().reindex(range(0, cap + 1)).fillna(0)
    lv_names = [level_label(i) if (i < cap or cap == max_dep) else f"רמה {LRI}{i}+{PDI}" for i in range(0, cap + 1)]
    depth = {"names": lv_names, "values": [int(v) for v in lv_counts],
             "leaf": [round(float(v) * 100, 1) for v in leaf_by],
             "frag": [round(float(v) * 100, 1) for v in frag_by]}
    subg = df[~df["is_main"]]
    dep_sec = subg.groupby("sec")["lvl"].mean().round(2)
    deepest = df[df["lvl"] == max_dep]["sub"].value_counts()
    deepest_top = _top(deepest, 1)
    deepest_sub = sub_label(deepest_top.index[0])
    n_deep = int(deepest_top.iloc[0])

    # level mix per section (subgroups only)
    def bucket(d):
        for a, b in LEVEL_BUCKETS:
            if d >= a and (b is None or d <= b):
                return _bucket_label(a, b)
        return _bucket_label(*LEVEL_BUCKETS[-1])
    bnames = [_bucket_label(a, b) for a, b in LEVEL_BUCKETS]
    sb = subg.assign(bk=subg["lvl"].map(bucket))
    dct = pd.crosstab(sb["sec"], sb["bk"]).reindex(index=secs, columns=bnames, fill_value=0)
    dtot = dct.sum(axis=1).replace(0, 1)
    depth_sec = {"names": [sec_label(s) for s in secs],
                 "series": [{"name": f"רמה {b}", "data": [round(float(v), 1) for v in dct[b] / dtot * 100]}
                            for b in bnames]}
    depth_sec_table = [{"name": sec_label(s), "mean": f"{dep_sec.get(s, 0):.1f}",
                        "cells": [f"{dct.loc[s, b] / dtot[s] * 100:.1f}%" for b in bnames]} for s in secs]

    # largest main groups by number of subgroups
    grp_all = subg["main"].value_counts().reindex(mains["code"].values, fill_value=0)
    grp_counts = _top(grp_all, len(grp_all))
    top_g = grp_counts.head(TOP_GROUPS)
    groups = {"names": [f"{g} · {SUBCLASS_HE[g[:4]]}" if g[:4] in SUBCLASS_HE else g for g in top_g.index],
              "values": [int(v) for v in top_g.values]}
    groups_table = [{"code": g, "name": SUBCLASS_HE.get(g[:4], "—"), "count": n(v)} for g, v in top_g.items()]
    no_sub_main = int((grp_all == 0).sum())

    # fan-out: direct children per parent code that is itself a group row
    kids = _top(df.loc[df["parent"].isin(set(df["code"])), "parent"].value_counts(), len(df))
    fan = []
    for a, b in FAN_BUCKETS:
        m = kids >= a
        if b is not None:
            m &= kids <= b
        fan.append((_bucket_label(a, b), int(m.sum())))
    leaf_share = float(df["leaf"].mean())

    ver_counts = _top(df["ver"].value_counts(), len(df))
    ver = ver_counts.index[0] if len(ver_counts) else ""
    ver_disp = f"{ver[:4]}.{ver[4:6]}" if re.fullmatch(r"\d{8}", ver) else "—"

    rules = [
        ("lead", ins_lead(sec_counts, total)),
        ("class", ins_class(cls_counts, sec_counts, total, n_cls)),
        ("concentration", ins_concentration(sub_counts, total)),
        ("biggest", ins_biggest(grp_counts, total)),
        ("depth", ins_depth(dep_sec, max_dep, deepest_sub, n_deep)),
        ("leaves", ins_leaves(leaf_share, kids)),
        ("fragments", ins_fragments(df)),
        ("residual", ins_residual(df)),
        ("version", ins_version(ver_counts, total)),
    ]
    insights = [{"id": i, "text_he": s} for i, s in rules if s]

    kpis = {
        "codes": {"value": rows_total, "display": n(rows_total), "tone": "brand"},
        "main": {"value": n_main, "display": n(n_main), "tone": "brand"},
        "subclasses": {"value": n_sub, "display": n(n_sub), "tone": "brand"},
        "version": {"value": ver_disp, "display": ver_disp, "tone": "info" if len(ver_counts) == 1 else "warn"},
    }

    lead_sec = _top(sec_counts, 1).index[0]
    wide_txt = (f" הרחב ביותר הוא {sub_label(widest[0][0])} עם {n(widest[0][1][0])} קבוצות ראשיות"
                if widest else "")
    deep_txt = (f"; הצפוף ביותר הוא {sub_label(deepest_r[0][0])}, עם {deepest_r[0][1][1]:.1f} קבוצות-משנה "
                f"בממוצע לכל קבוצה ראשית" if deepest_r else "")
    labels = {
        "lede": (f"שיטת הסיווג הבינלאומית לפטנטים (IPC) של הארגון העולמי לקניין רוחני, שבה מסווגות בקשות פטנט "
                 f"לפי תחום טכנולוגי: {n(total)} קודי סיווג — {n(n_main)} קבוצות ראשיות ו-{n(total - n_main)} "
                 f"קבוצות-משנה — ב-{n(n_sub)} תתי-סעיפים, {n(n_cls)} מחלקות ו-{len(secs)} סעיפים, לפי מהדורת "
                 f"{code_ltr(ver_disp)}. לכל קוד כותרת באנגלית וקוד אב שמעליו בעץ, ועץ הקבוצות מגיע לעומק של "
                 f"{n(max_dep)} רמות מתחת לקבוצה הראשית."),
        "sections_note": (f"מספר הקודים בכל סעיף, בהפרדה בין קבוצות ראשיות לקבוצות-המשנה שמתחתן. הסעיף הגדול: "
                          f"{sec_label(lead_sec)}."),
        "sections_aria": f"תרשים עמודות מוערם: קודי IPC לפי סעיף, קבוצות ראשיות וקבוצות-משנה. הגדול: {sec_label(lead_sec)}.",
        "sections_caption": "קודי IPC לפי סעיף: תתי-סעיפים, קבוצות ראשיות וקבוצות-משנה.",
        "tree_note": (f"כל הקודים לפי סעיף ומחלקה ({TOP_CLASSES_PER_SECTION} המחלקות הגדולות בכל סעיף, "
                      f"השאר תחת אחר). המחלקה הגדולה: {class_label(cls_counts.index[0])}."),
        "tree_aria": "מפת עצים: קודי IPC לפי סעיף ומחלקה.",
        "classes_caption": f"{len(class_table)} המחלקות הגדולות לפי מספר קודים.",
        "sub_note": (f"{len(top_sub)} תתי-הסעיפים הגדולים מתוך {n(n_sub)}, לפי מספר הקבוצות הראשיות "
                     f"וקבוצות-המשנה שבהם."),
        "sub_aria": f"תרשים עמודות אופקי מוערם: {len(top_sub)} תתי-הסעיפים הגדולים. במקום הראשון {top_sub.index[0]}.",
        "sub_caption": "תתי-הסעיפים הגדולים: קבוצות ראשיות, סך קודים ושיעור מהשיטה.",
        "scatter_note": (f"כל נקודה היא תת-סעיף: מספר הקבוצות הראשיות בו (רוחב, ציר לוגריתמי) ומספר קבוצות-המשנה "
                         f"הממוצע לכל קבוצה ראשית (פירוט).{wide_txt}{deep_txt}."),
        "scatter_aria": "תרשים פיזור: תתי-סעיפים לפי מספר קבוצות ראשיות ומספר קבוצות-משנה לקבוצה.",
        "depth_note": ("רמה היא מספר הצעדים מהקוד עד הקבוצה הראשית שלו (\"נקודות\" בסימון IPC). עמודות: מספר הקודים "
                       "בכל רמה. קווים: שיעור העלים (קודים ללא קודים מתחתיהם) ושיעור הכותרות שהן המשך של כותרת האב."),
        "depth_aria": f"תרשים משולב: קודים, שיעור עלים ושיעור כותרות-המשך לפי רמה בעץ, עד רמה {n(max_dep)}.",
        "depth_caption": "קודים, שיעור עלים ושיעור כותרות-המשך לפי רמה בעץ.",
        "depth_sec_note": "התפלגות קבוצות-המשנה בכל סעיף לפי רמת העומק, ועומק ממוצע.",
        "depth_sec_aria": (f"תרשים עמודות מוערם באחוזים: עומק קבוצות-המשנה בכל סעיף. העמוק ביותר: "
                           f"{sec_label(dep_sec.sort_index().sort_values(ascending=False, kind='stable').index[0])}."),
        "depth_sec_caption": "שיעור קבוצות-המשנה בכל רמת עומק ועומק ממוצע, לפי סעיף.",
        "groups_note": (f"{len(top_g)} הקבוצות הראשיות עם הכי הרבה קבוצות-משנה, מתוך {n(n_main)}. "
                        f"{n(no_sub_main)} קבוצות ראשיות אינן מתפצלות כלל."),
        "groups_aria": f"תרשים עמודות אופקי: {len(top_g)} הקבוצות הראשיות הגדולות. במקום הראשון {top_g.index[0]}.",
        "groups_caption": "הקבוצות הראשיות הגדולות לפי מספר קבוצות-משנה.",
        "fan_note": (f"מספר קודי האב (קבוצות ראשיות וקבוצות-משנה שיש מתחתן קודים) לפי מספר קודי-המשנה הישירים "
                     f"שלהם. {pct(leaf_share * 100)} מהקודים הם עלים."),
        "fan_aria": f"תרשים עמודות: קודי אב לפי מספר קודי-משנה ישירים. החציון {n(kids.median())}.",
        "fan_caption": "קודי אב לפי מספר קודי-המשנה הישירים.",
    }

    tables = {
        "sections": sec_table,
        "classes": class_table,
        "subclasses": sub_table,
        "depth": [{"level": lv_names[i], "count": n(depth["values"][i]), "leaf": f"{depth['leaf'][i]:.1f}%",
                   "frag": f"{depth['frag'][i]:.1f}%"} for i in range(cap + 1)],
        "depth_sec_names": bnames,
        "depth_sec": depth_sec_table,
        "groups": groups_table,
        "fan": [{"bucket": k, "count": n(v)} for k, v in fan],
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
    }

    return {
        "agent_data": {
            "summary_he": (f"שיטת הסיווג הבינלאומית לפטנטים IPC, מהדורת {ver_disp}: {n(total)} קודים — "
                           f"{n(n_main)} קבוצות ראשיות ב-{n(n_sub)} תתי-סעיפים ו-{len(secs)} סעיפים, עד "
                           f"{n(max_dep)} רמות מתחת לקבוצה הראשית."),
            "dataset_kind": "registry",
            "suggested_tags": ["פטנטים", "סיווגי IPC", "קניין רוחני", "רשות הפטנטים", "סיווג בינלאומי",
                               "טכנולוגיה"],
            "related_ids": ["a5b7e889-de77-4062-85e1-cf427bfbf9d1",
                            "8687fefe-51af-4e0b-af54-701929c40102",
                            "6e207fff-abef-4f4d-aac7-61e669ba9ad5",
                            "247efc75-31f2-4b19-bd4e-e670b1bf2783",
                            "1806c96c-9cc4-47bf-98b3-80a18f061f98"],
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"bad_rows": n_bad},
    }
