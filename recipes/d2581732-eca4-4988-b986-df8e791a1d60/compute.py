"""רשימת רחובות ישראל — the Population and Immigration Authority's street list.

One row per (locality, street) pair (~64k): locality code and name, street code
and street name. The whole list is republished on each update, so the page is a
snapshot of the current list, compared with the older files kept in the dataset.

Inputs
- `main`: the updating list (9ad3862c).
- `snapshot`: the older lists published in the same dataset (a7296d1a and its
  twin fbaa54f1 from 2019, 72bd89da from 2020), matched by the `טבלה` column
  only the old layout has, and pooled: a (locality, street) key is "in the
  earlier files" if any of them has it, and a street counts as renamed only when
  none of them carries its current name. Old fields are padded with spaces and
  some mirror parentheses; both are normalised before comparing.

Street code 9000 is not a street: every locality has one row with code 9000
named after the locality itself — the address used where there are no streets.
It is excluded from street counts; a locality whose only row is 9000 has no
registered streets.

Street types come from the first word of the name (שד = שדרות, סמ = סמטה, ש =
שיכון, שכ = שכונה, …); a name with no type word is a plain street. "Numbered"
streets are names that are only a number, optionally after רח/שכ/סמ.

Themes and people are fixed word lists (plants, birds, gems; a set of widely
commemorated figures, each with the spellings the registry uses). A street
matches after its type word is removed (and, for themes, a leading ה). Counts
are computed; the lists only decide what is looked for, and the page says so.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
PLACEHOLDER = 9000
TOP_SETTLEMENTS = 20
TOP_NAMES = 20
TOP_PEOPLE = 20
TOP_NUMBERED = 15
TOP_GROWTH = 15
TOP_RENAMES = 15
NUMBERED_MIN = 20
UNIQUE_SHARE_MIN = 0.5

BUCKETS = [  # (lo, hi) street counts, inclusive; hi None = open
    (0, 0), (1, 5), (6, 10), (11, 25), (26, 50), (51, 100), (101, 250),
    (251, 500), (501, None),
]

# first word → street type
TYPE_WORDS = {
    "דרך": "דרך", "שד": "שדרות", "שדרות": "שדרות", "שדרת": "שדרות",
    "סמ": "סמטה", "סמטת": "סמטה", "סמטה": "סמטה",
    "משעול": "משעול", "שביל": "שביל", "ככר": "כיכר", "כיכר": "כיכר",
    "מעלה": "מעלה", "מעלות": "מעלה", "מבוא": "מבוא", "רחבת": "רחבה",
    "טיילת": "טיילת", "שכ": "שכונה", "שכונת": "שכונה", "ש": "שיכון",
    "שיכון": "שיכון", "שכון": "שיכון", "קרית": "קריה", "קריית": "קריה",
    "אזור": "אזור", "רח": "רחוב", "רחוב": "רחוב",
}
PLAIN = "רחוב (ללא תחילית)"
NUMBERED = "רחוב ממוספר"
TYPE_PREFIXES = set(TYPE_WORDS) | {"גן"}
NUM_RE = re.compile(r"^(?:(?:רח|רחוב|שכ|סמ)\s?)?\d+$")

PLANTS = set("""
זית גפן תאנה רימון תמר שקד אלה דקל ברוש אלון חרוב אורן הדס ערבה שיטה כלנית
רקפת יסמין נרקיס ארז חצב סביון רותם נורית אשל רדוף שקמה דולב תומר אגוז תפוח
אתרוג לימון אקליפטוס צאלון אירוס סחלב חבצלת שושן ורד צבעוני מורן
ער אלונים אורנים ברושים זיתים גפנים תאנים רימונים תמרים שקדים דקלים ארזים
אלות שקמים חרובים ערבות כרמים כרם פרדס הדרים אשכולית תות משמש שזיף אפרסק
אגס דובדבן לוטם קורנית מרווה זעתר נענע ריחן לבונה מור קטלב שיזף רתם
לילך יערה פרג חרצית סיגלית אדמונית חמנית ציפורן כרכום חיטה
שעורה שבולת זוטה אזוב קידה קנמון הרדוף דפנה מימוזה פיקוס
ערמון צפצפה אקציה בוגנביליה תלתן אשחר אטד סנה
""".split()) | {"כליל החורש", "אלון התבור", "שבעת המינים"}
BIRDS = set("""
דוכיפת אנפה עפרוני זמיר נחליאלי שחף סנונית חסידה צופית פשוש
סלעית שלדג ינשוף נשר עיט בז דיה חוחית אנקור תמירון סיס כחל שרשיר
חגלה שליו עגור שקנאי פלמינגו קיכלי ירגזי בולבול נקר צוצלת אנפית לבנית
ברבור טווס תוכי זהבן חנקן סבכי פרוש
""".split())
GEMS = set("""
ברקת אודם ספיר יהלום שוהם לשם טופז אחלמה תרשיש פטדה נופך ישפה
 אקוומרין אזמרגד בהט
""".split())
RABBI_WORDS = {"הרב", "רבי", "רבנו", "הרבנית", "האדמו\"ר"}

# display name → spellings the registry uses (after the type word is removed)
PEOPLE = {
    "בנימין זאב הרצל": ["הרצל", "תיאודור הרצל", "הרצל תיאודור", "בנימין זאב הרצל",
                        "הרצל בנימין זאב", "חוזה המדינה הרצל"],
    "דוד בן גוריון": ["בן גוריון", "בן גוריון דוד", "דוד בן גוריון", "בן-גוריון"],
    "זאב ז'בוטינסקי": ["ז'בוטינסקי", "ז'בוטינסקי זאב", "זאב ז'בוטינסקי", "זבוטינסקי",
                       "זאב (זבוטינסקי)", "ז'בוטינסקי ז'"],
    "יצחק רבין": ["רבין", "רבין יצחק", "יצחק רבין"],
    "מנחם בגין": ["בגין", "בגין מנחם", "מנחם בגין"],
    "חיים ויצמן": ["ויצמן", "חיים ויצמן", "ויצמן חיים", "הנשיא ויצמן", "הנשיא חיים ויצמן"],
    "חיים נחמן ביאליק": ["ביאליק", "חיים נחמן ביאליק", "ביאליק חיים נחמן", "ח נ ביאליק"],
    "רש\"י": ["רש\"י", "רשי"],
    "הרמב\"ם": ["רמב\"ם", "הרמב\"ם", "רמבם"],
    "הרב קוק": ["הרב קוק", "קוק", "הרב קוק אברהם יצחק", "הרב אברהם יצחק הכהן קוק", "הראי\"ה קוק"],
    "יוסף טרומפלדור": ["טרומפלדור", "יוסף טרומפלדור", "טרומפלדור יוסף"],
    "אחד העם": ["אחד העם"],
    "חנה סנש": ["סנש", "סנש חנה", "חנה סנש"],
    "שלום שבזי": ["שבזי", "שבזי שלום", "שלום שבזי", "הרב שבזי", "רבי שבזי שלום",
                  "רבי שלום שבזי", "הרב שלום שבזי"],
    "רבי יהודה הלוי": ["יהודה הלוי", "רבי יהודה הלוי", "ריה\"ל"],
    "גולדה מאיר": ["גולדה מאיר", "מאיר גולדה", "גולדה"],
    "משה שרת": ["שרת", "שרת משה", "משה שרת"],
    "לוי אשכול": ["לוי אשכול", "אשכול לוי"],
    "יצחק בן צבי": ["בן צבי", "בן צבי יצחק", "יצחק בן צבי", "הנשיא בן צבי"],
    "רחל המשוררת": ["רחל המשוררת", "המשוררת רחל"],
    "הרב עובדיה יוסף": ["הרב עובדיה יוסף", "עובדיה יוסף", "רבנו עובדיה יוסף"],
    "עלי בן אבי טאלב": ["עלי בן אבי טאלב", "עלי אבן אבי טאלב", "עלי בן אבו טאלב"],
    "עומר בן אל-ח'טאב": ["עומר בן אלח'טאב", "עומר בן אל-ח'טאב", "עומר בן אל ח'טאב",
                         "עומר אבן אלח'טאב", "עומר אבן אל-ח'טאב", "עומר בן אלחטאב"],
    "אבו בכר א-סדיק": ["אבו בכר", "אבו בכר אלסדיק", "אבו בכר אלצדיק", "אבו בכר א-ס'דיק",
                       "אבו בכר אל סדיק", "אבו בכר א-סדיק", "אבו בכר א-צדיק"],
    "מקס נורדאו": ["נורדאו", "נורדאו מקס", "מקס נורדאו", "נורדאו מכס"],
    "חיים ארלוזורוב": ["ארלוזורוב", "חיים ארלוזורוב", "ארלוזורוב חיים"],
    "א\"ד גורדון": ["גורדון", "גורדון א ד", "א ד גורדון", "א\"ד גורדון", "אהרון דוד גורדון"],
    "יוסף חיים ברנר": ["ברנר", "יוסף חיים ברנר", "ברנר יוסף חיים", "ברנר י ח"],
    "נתן אלתרמן": ["אלתרמן", "אלתרמן נתן", "נתן אלתרמן"],
    "שלום עליכם": ["שלום עליכם"],
    "הבעל שם טוב": ["הבעל שם טוב", "בעל שם טוב", "הבעש\"ט"],
    "בר כוכבא": ["בר כוכבא"],
    "רבי יהודה הנשיא": ["רבי יהודה הנשיא", "יהודה הנשיא"],
    "רבי עקיבא": ["רבי עקיבא", "עקיבא"],
    "ברל כצנלסון": ["כצנלסון ברל", "ברל כצנלסון"],
    "אליעזר בן יהודה": ["בן יהודה", "אליעזר בן יהודה", "בן יהודה אליעזר"],
    "יהודה המכבי": ["יהודה המכבי"],
    "ישעיהו ליבוביץ": ["ליבוביץ ישעיהו", "ישעיהו ליבוביץ"],
}
SUB_ALLEY = re.compile(r"\s+סמ\s?\d+$")
_SPELL = re.compile(r"[\s'\"\-־׳״.()אוי]")


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def share(a, b, digits=1):
    return pct(a / b * 100, digits) if b else pct(0, digits)


_FLIP = str.maketrans("()", ")(")


def _clean(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    m = re.search(r"[()]", s)
    if m and m.group(0) == ")":
        s = s.translate(_FLIP)
    return s


def _ranked(s):
    """Counts sorted descending, ties broken by label."""
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _frame(raw):
    df = pd.DataFrame({
        "loc": pd.to_numeric(raw["סמל_ישוב"].str.strip(), errors="coerce").values,
        "loc_name": raw["שם_ישוב"].map(_clean).values,
        "code": pd.to_numeric(raw["סמל_רחוב"].str.strip(), errors="coerce").values,
        "name": raw["שם_רחוב"].map(_clean).values,
    })
    df = df[df["loc"].notna() & (df["loc"] > 0) & df["code"].notna()].copy()
    df["loc"] = df["loc"].astype(int)
    df["code"] = df["code"].astype(int)
    return df


def _strip_type(name):
    """Remove a leading street-type word and a trailing numbered-alley suffix."""
    s = SUB_ALLEY.sub("", name)
    parts = s.split(" ", 1)
    if len(parts) == 2 and parts[0] in TYPE_PREFIXES:
        s = parts[1]
    return s.strip()


def _spelling_key(name):
    """A name reduced so that spelling variants compare equal (type word, punctuation,
    spaces and the vowel letters א/ו/י removed)."""
    words = [w[1:] if w.startswith("ה") and len(w) > 2 else w for w in _strip_type(name).split(" ")]
    return _SPELL.sub("", "".join(words))


def _type_of(name):
    if NUM_RE.match(name):
        return NUMBERED
    first = name.split(" ", 1)[0]
    if first in TYPE_WORDS and " " in name:
        return TYPE_WORDS[first]
    return PLAIN


def _theme_of(name):
    base = _strip_type(name)
    first = base.split(" ", 1)[0]
    if first == "מבצע":
        return "מבצעים צבאיים"
    if first in RABBI_WORDS and " " in base:
        return "רבנים וחכמים"
    if first == "נחל" and " " in base:
        return "נחלים"
    if first in {"הר", "הרי"} and " " in base:
        return "הרים"
    cands = [base]
    if base.startswith("ה") and len(base) > 2:
        cands.append(base[1:])
    for c in cands:
        if c in PLANTS:
            return "עצים וצמחים"
        if c in BIRDS:
            return "ציפורים"
        if c in GEMS:
            return "אבני חן"
    return None


def _theme_key(name):
    """The lexicon word a themed street matches (leading ה dropped), else the bare name."""
    base = _strip_type(name)
    if base.startswith("ה") and base[1:] in LEXICON and base not in LEXICON:
        return base[1:]
    return base


LEXICON = PLANTS | BIRDS | GEMS
THEME_ORDER = ["עצים וצמחים", "ציפורים", "אבני חן", "רבנים וחכמים", "מבצעים צבאיים",
               "נחלים", "הרים"]
_PERSON_OF = {v: k for k, vs in PEOPLE.items() for v in vs}


# ---------------------------------------------------------------- insights

def insight_concentration(top_rows, n_streets, n_locs):
    if len(top_rows) < 10 or not n_streets:
        return None
    s10 = sum(r["count"] for r in top_rows[:10])
    a, b = top_rows[0], top_rows[1]
    if a["count"] <= b["count"]:
        return None
    return (f"עשרת הישובים עם מספר הרחובות הגדול ביותר מרכזים {n(s10)} רחובות — "
            f"{share(s10, n_streets)} מכלל הרחובות ב-{n(n_locs)} הישובים. {a['name']} מובילה עם "
            f"{n(a['count'])} רחובות, פי {LRI}{a['count'] / b['count']:.1f}{PDI} מ{b['name']} ({n(b['count'])}).")


def insight_no_streets(counts, n_locs):
    zero = int((counts == 0).sum())
    if zero == 0 or not n_locs:
        return None
    med = float(counts.median())
    return (f"{n(zero)} ישובים ({share(zero, n_locs)}) רשומים בלי אף רחוב — הכתובת בהם היא שם הישוב "
            f"בלבד. החציון הוא {n(round(med))} רחובות לישוב, לעומת ממוצע של "
            f"{n(round(counts.mean()))}, שהערים הגדולות מושכות כלפי מעלה.")


def insight_top_names(name_rows, theme_of_key):
    if len(name_rows) < 5:
        return None
    top5 = name_rows[:5]
    plant5 = [r for r in top5 if theme_of_key(r["key"]) == "עצים וצמחים"]
    names = ", ".join(r["name"] for r in top5[:4]) + " ו" + top5[4]["name"]
    if len(plant5) == 5:
        return (f"חמשת שמות הרחובות הנפוצים ביותר הם כולם עצים: {names}. "
                f"{top5[0]['name']} לבדו מופיע ב-{n(top5[0]['locs'])} ישובים.")
    return (f"שם הרחוב הנפוץ ביותר הוא {top5[0]['name']}, שמופיע ב-{n(top5[0]['locs'])} ישובים; "
            f"אחריו {names.split(', ', 1)[1]}.")


def insight_themes(theme_rows, n_streets):
    if not theme_rows:
        return None
    t = {r["name"]: r for r in theme_rows}
    pl = t.get("עצים וצמחים")
    if not pl or pl["streets"] < 100:
        return None
    tail = ""
    ops = t.get("מבצעים צבאיים")
    if ops and ops["streets"] >= 20 and ops.get("top"):
        tail = (f" {n(ops['streets'])} רחובות ב-{n(ops['locs'])} ישובים נקראים על שם מבצע צבאי, "
                f"והנפוץ בהם הוא {ops['top']} ({n(ops['top_n'])} ישובים).")
    return (f"{n(pl['streets'])} רחובות ({share(pl['streets'], n_streets)}) נקראים על שם עץ או צמח, "
            f"ב-{n(pl['locs'])} ישובים.{tail}")


def insight_people(people_rows):
    if len(people_rows) < 3:
        return None
    a, b, c = people_rows[:3]
    if a["locs"] < 10:
        return None
    if a["locs"] > b["locs"]:
        lead = (f"מבין האישים שנבדקו, {a['name']} זוכה לרחוב בהכי הרבה ישובים — {n(a['locs'])}, "
                f"לפני {b['name']} ({n(b['locs'])}) ו{c['name']} ({n(c['locs'])})")
    else:
        lead = (f"מבין האישים שנבדקו, {a['name']} ו{b['name']} מובילים יחד עם רחוב ב-{n(a['locs'])} "
                f"ישובים, ואחריהם {c['name']} ({n(c['locs'])})")
    return lead + "."


def insight_numbered(num_rows, n_numbered, n_streets):
    if not num_rows or n_numbered < NUMBERED_MIN:
        return None
    a = num_rows[0]
    return (f"{n(n_numbered)} רחובות ({share(n_numbered, n_streets)}) נושאים מספר במקום שם. "
            f"ב{a['name']} {n(a['numbered'])} מתוך {n(a['total'])} הרחובות ממוספרים "
            f"({share(a['numbered'], a['total'], 0)}).")


def insight_unique(name_locs):
    if len(name_locs) < 10:
        return None
    one = int((name_locs == 1).sum())
    if one / len(name_locs) < UNIQUE_SHARE_MIN:
        return None
    many = int((name_locs >= 50).sum())
    tail = f", ורק {n(many)} שמות חוזרים ב-{n(50)} ישובים ומעלה" if many else ""
    return (f"{n(one)} מתוך {n(len(name_locs))} שמות הרחובות ({share(one, len(name_locs))}) "
            f"מופיעים בישוב אחד בלבד{tail}.")


def insight_growth(ch):
    if not ch or ch["added"] == 0:
        return None
    rows = ch["growth"]
    lead = ""
    if len(rows) >= 3:
        a, b, c = rows[:3]
        lead = (f" הגידול הגדול ביותר ב{a['name']} ({LRI}+{n(a['added'])}{PDI}), "
                f"ב{b['name']} ({LRI}+{n(b['added'])}{PDI}) וב{c['name']} ({LRI}+{n(c['added'])}{PDI}).")
    rem = f" ו-{n(ch['removed'])} הוסרו" if ch["removed"] else ""
    return (f"לעומת הקבצים הקודמים שפורסמו במאגר ({n(ch['old_streets'])} רחובות), נוספו "
            f"{n(ch['added'])} רחובות{rem}.{lead}")


def insight_renames(ren):
    if not ren or ren["total"] == 0:
        return None
    t = ren["total"]
    k = ren["from_number"]
    if k >= 5:
        ex = ren["number_examples"][:1]
        ex_t = f" — למשל {ex[0]['old']} ב{ex[0]['loc']} הוא היום {ex[0]['new']}" if ex else ""
        return (f"{n(t)} רחובות שינו את שמם מאז הקבצים הקודמים כשסמל הרחוב נשמר (לא כולל שינויי כתיב); {n(k)} מהם "
                f"היו רחובות ממוספרים שקיבלו שם{ex_t}.")
    return f"{n(t)} רחובות שינו את שמם מאז הקבצים הקודמים כשסמל הרחוב נשמר (לא כולל שינויי כתיב)."


# ---------------------------------------------------------------- compute

def compute(frames):
    full = _frame(frames["main"])
    full = full.sort_values(["loc", "code", "name"], kind="stable").drop_duplicates(["loc", "code"])
    # One name per locality: the placeholder row's locality name, else the first.
    loc_names = (full.sort_values(["loc", "code"], kind="stable")
                 .drop_duplicates("loc").set_index("loc")["loc_name"])
    locs = sorted(full["loc"].unique())
    n_locs = len(locs)
    st = full[(full["code"] != PLACEHOLDER) & (full["name"] != "")].copy()
    st["loc_name"] = st["loc"].map(loc_names)
    n_streets = len(st)

    # Streets per locality.
    counts = st.groupby("loc").size().reindex(locs, fill_value=0)
    named = pd.Series(counts.values, index=[loc_names[l] for l in locs])
    named = named.groupby(level=0).sum()
    top = _ranked(named).head(TOP_SETTLEMENTS)
    top_rows = [{"name": k, "count": int(v), "share": share(int(v), n_streets)} for k, v in top.items()]
    top_chart = {"names": [r["name"] for r in top_rows], "values": [r["count"] for r in top_rows]}

    bucket_rows = []
    for lo, hi in BUCKETS:
        m = (counts >= lo) if hi is None else ((counts >= lo) & (counts <= hi))
        label = (f"{n(lo)} ומעלה" if hi is None else (n(lo) if lo == hi else f"{n(lo)} עד {n(hi)}"))
        if lo == 0 and hi == 0:
            label = "ללא רחובות"
        bucket_rows.append({"name": label, "count": int(m.sum()),
                            "share": share(int(m.sum()), n_locs)})
    dist_chart = {"names": [r["name"] for r in bucket_rows], "values": [r["count"] for r in bucket_rows]}

    # Street types.
    st["type"] = st["name"].map(_type_of)
    tc = _ranked(st.groupby("type").size())
    tl = st.groupby("type")["loc"].nunique()
    type_rows = [{"name": k, "count": int(v), "locs": int(tl[k]), "share": share(int(v), n_streets)}
                 for k, v in tc.items()]
    typed = [r for r in type_rows if r["name"] != PLAIN]
    types_chart = {"names": [r["name"] for r in typed], "values": [r["count"] for r in typed]}

    # Most widespread names (merging a single-word name with its ה-form).
    pairs = st[["name", "loc"]].drop_duplicates()
    uniq_names = set(pairs["name"])

    def key_of(nm):
        if " " not in nm and nm.startswith("ה") and len(nm) > 2 and nm[1:] in uniq_names:
            return nm[1:]
        return nm
    key_map = {nm: key_of(nm) for nm in sorted(uniq_names)}
    pairs = pairs.assign(key=pairs["name"].map(key_map))
    key_locs = pairs.groupby("key")["loc"].nunique()
    form_locs = pairs.groupby(["key", "name"])["loc"].nunique().reset_index(name="k")
    form_locs["has_h"] = form_locs["name"].str.startswith("ה").astype(int)
    disp = (form_locs.sort_values(["key", "k", "has_h", "name"], ascending=[True, False, False, True],
                                  kind="stable")
            .drop_duplicates("key").set_index("key")["name"])
    themes_of_key = {k: _theme_of(disp[k]) for k in key_locs.index}
    top_names = _ranked(key_locs).head(TOP_NAMES)
    name_rows = [{"key": k, "name": disp[k], "locs": int(v),
                  "theme": themes_of_key[k] or "אחר"} for k, v in top_names.items()]
    theme_ci = {t: i for i, t in enumerate(THEME_ORDER)}
    names_chart = {"names": [r["name"] for r in name_rows], "values": [r["locs"] for r in name_rows],
                   "ci": [theme_ci.get(r["theme"], len(THEME_ORDER)) for r in name_rows],
                   "themes": [r["theme"] for r in name_rows]}
    name_locs_raw = pairs.groupby("name")["loc"].nunique()

    # Themes.
    st["theme"] = st["name"].map(_theme_of)
    th = st[st["theme"].notna()]
    theme_rows = []
    for t in THEME_ORDER:
        sub = th[th["theme"] == t]
        if not len(sub):
            continue
        base = sub["name"].map(_theme_key)
        bl = _ranked(sub.assign(b=base.values).groupby("b")["loc"].nunique())
        tk = bl.index[0]
        theme_rows.append({"name": t, "streets": int(len(sub)), "locs": int(sub["loc"].nunique()),
                           "top": disp[tk] if tk in disp.index else tk, "top_n": int(bl.iloc[0])})
    themes_chart = {"names": [r["name"] for r in theme_rows],
                    "values": [r["streets"] for r in theme_rows],
                    "locs": [r["locs"] for r in theme_rows]}

    # People.
    st["person"] = st["name"].map(lambda x: _PERSON_OF.get(_strip_type(x)))
    pp = st[st["person"].notna()]
    pl = _ranked(pp.groupby("person")["loc"].nunique())
    ps = pp.groupby("person").size()
    people_rows = [{"name": k, "locs": int(v), "streets": int(ps[k])} for k, v in pl.head(TOP_PEOPLE).items()]
    people_chart = {"names": [r["name"] for r in people_rows], "values": [r["locs"] for r in people_rows]}

    # Numbered streets.
    num = st[st["type"] == NUMBERED]
    n_numbered = int(len(num))
    nb = _ranked(num.groupby("loc_name").size()).head(TOP_NUMBERED)
    num_rows = [{"name": k, "numbered": int(v), "total": int(named[k]),
                 "share": share(int(v), int(named[k]), 0)} for k, v in nb.items()]
    numbered_chart = {"names": [r["name"] for r in num_rows],
                      "numbered": [r["numbered"] for r in num_rows],
                      "named": [r["total"] - r["numbered"] for r in num_rows],
                      "numbered_pct": [round(r["numbered"] / r["total"] * 100, 1) for r in num_rows],
                      "named_pct": [round(100 - r["numbered"] / r["total"] * 100, 1) for r in num_rows]}
    n_num_locs = int(num["loc"].nunique())

    # Comparison with the earlier files.
    old = _frame(frames["snapshot"])
    old = old[(old["code"] != PLACEHOLDER) & (old["name"] != "")]
    ch = None
    ren = None
    if len(old):
        old_names = (old.groupby(["loc", "code"])["name"]
                     .agg(lambda s: tuple(sorted(set(s)))))
        old_keys = set(old_names.index)
        cur_keys = list(zip(st["loc"], st["code"]))
        is_old = [k in old_keys for k in cur_keys]
        st["is_old"] = is_old
        added = st[~st["is_old"]]
        cur_set = set(cur_keys)
        removed_keys = [k for k in old_names.index if k not in cur_set]
        old_per_loc = pd.Series([k[0] for k in old_names.index]).value_counts()
        rem_per_loc = pd.Series([k[0] for k in removed_keys], dtype="int64").value_counts()
        add_per_loc = added.groupby("loc").size()
        gr = []
        for loc, a in add_per_loc.items():
            gr.append({"name": loc_names.get(loc, str(loc)), "loc": int(loc), "added": int(a),
                       "removed": int(rem_per_loc.get(loc, 0)), "old": int(old_per_loc.get(loc, 0)),
                       "now": int(counts.get(loc, 0))})
        gr.sort(key=lambda r: (-r["added"], r["name"], r["loc"]))
        new_locs = sorted(set(add_per_loc.index) - set(old_per_loc.index))
        ch = {"added": int(len(added)), "removed": int(len(removed_keys)),
              "old_streets": int(len(old_names)), "growth": gr[:TOP_GROWTH],
              "grew_locs": int(len(add_per_loc)), "new_locs": int(len(new_locs))}

        both = st[st["is_old"]]
        renames = []
        spelling = 0
        for loc, code, nm, ln in zip(both["loc"], both["code"], both["name"], both["loc_name"]):
            prev = old_names[(loc, code)]
            flat = nm.replace(" ", "")
            if any(p.replace(" ", "") == flat for p in prev):
                continue
            if any(_spelling_key(p) == _spelling_key(nm) for p in prev):
                spelling += 1
                continue
            renames.append({"loc": ln, "loc_code": int(loc), "code": int(code),
                            "old": " / ".join(prev), "new": nm,
                            "from_number": all(NUM_RE.match(p) for p in prev)
                            and not NUM_RE.match(nm)})
        renames.sort(key=lambda r: (r["loc"], r["loc_code"], r["code"]))
        fromnum = [r for r in renames if r["from_number"]]
        # One example per locality (the most renames first), named-from-number first.
        per_loc = {}
        for r in renames:
            per_loc.setdefault((r["loc"], r["loc_code"]), []).append(r)
        loc_order = sorted(per_loc, key=lambda k: (-len(per_loc[k]), k))
        rows = []
        for k in loc_order[:TOP_RENAMES]:
            lst = sorted(per_loc[k], key=lambda r: (not r["from_number"], r["code"]))
            rows.append({**lst[0], "n": len(lst)})
        num_locs = sorted({(r["loc"], r["loc_code"]) for r in fromnum},
                          key=lambda k: (-sum(1 for r in per_loc[k] if r["from_number"]), k))
        ex = [next(r for r in per_loc[k] if r["from_number"]) for k in num_locs[:1]]
        ren = {"total": len(renames), "from_number": len(fromnum), "locs": len(per_loc),
               "spelling": spelling,
               "number_examples": ex, "rows": rows}
    growth_chart = None
    if ch and ch["growth"]:
        g = ch["growth"]
        growth_chart = {"names": [r["name"] for r in g],
                        "kept": [r["now"] - r["added"] for r in g],
                        "added": [r["added"] for r in g]}

    # KPIs.
    zero = int((counts == 0).sum())
    kpis = {
        "streets": {"value": n_streets, "display": n(n_streets), "tone": "brand"},
        "locs": {"value": n_locs, "display": n(n_locs), "tone": "brand"},
        "no_streets": {"value": zero, "display": f"{zero / n_locs * 100:.1f}%" if n_locs else "0%",
                       "tone": "info"},
        "added": ({"value": ch["added"], "display": f"+{n(ch['added'])}" if ch["added"] else "0",
                   "tone": "ok" if ch["added"] > ch["removed"] else "brand"}
                  if ch else {"value": 0, "display": "0", "tone": "brand"}),
    }

    insights = []
    for iid, txt in [
        ("concentration", insight_concentration(top_rows, n_streets, n_locs)),
        ("no_streets", insight_no_streets(counts, n_locs)),
        ("top_names", insight_top_names(name_rows, lambda k: themes_of_key.get(k))),
        ("themes", insight_themes(theme_rows, n_streets)),
        ("people", insight_people(people_rows)),
        ("numbered", insight_numbered(num_rows, n_numbered, n_streets)),
        ("growth", insight_growth(ch)),
        ("renames", insight_renames(ren)),
        ("unique", insight_unique(name_locs_raw)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    a0 = top_rows[0] if top_rows else {"name": "", "count": 0}
    t_plain = next((r for r in type_rows if r["name"] == PLAIN), None)
    labels = {
        "lede": (f"רשות האוכלוסין וההגירה מפרסמת את רשימת הרחובות שבמרשם האוכלוסין: "
                 f"{n(n_streets)} רחובות, שכונות וכיכרות ב-{n(n_locs)} ישובים, כל אחד עם סמל ישוב "
                 f"וסמל רחוב. העמוד מראה היכן יש הכי הרבה רחובות, איך הם נקראים ועל שם מה ומי, "
                 f"ומה השתנה לעומת הקבצים הקודמים שפורסמו במאגר."),
        "streets_kpi": "רחובות ברשימה",
        "locs_kpi": "ישובים",
        "no_streets_kpi": "שיעור הישובים ללא רחובות רשומים",
        "added_kpi": "רחובות שנוספו לעומת הקבצים הקודמים",
        "top_note": (f"{n(len(top_rows))} הישובים עם מספר הרחובות הגדול ביותר. {a0['name']} מובילה "
                     f"עם {n(a0['count'])} רחובות ({a0.get('share', '')} מכלל הרחובות)."),
        "top_aria": (f"גרף עמודות אופקי: {n(len(top_rows))} הישובים עם הכי הרבה רחובות. "
                     f"{a0['name']} מובילה עם {n(a0['count'])}."),
        "top_caption": "הישובים עם מספר הרחובות הגדול ביותר",
        "dist_note": (f"כמה רחובות יש בכל ישוב. {n(zero)} ישובים ללא רחובות כלל (כתובת לפי שם הישוב), "
                      f"וחציון של {n(round(float(counts.median())))} רחובות לישוב."),
        "dist_aria": f"גרף עמודות: התפלגות {n(n_locs)} הישובים לפי מספר הרחובות בהם.",
        "dist_caption": "ישובים לפי מספר רחובות",
        "types_note": ("סוג הרחוב לפי המילה הראשונה בשם (דרך, שדרות, סמטה, כיכר, שכונה וכו׳). "
                       + (f"{share(t_plain['count'], n_streets)} מהשמות הם רחוב ללא תחילית ואינם מוצגים בגרף; הם מופיעים בטבלה." if t_plain else "")),
        "types_aria": f"גרף עמודות אופקי: {n(n_streets)} הרחובות לפי סוג.",
        "types_caption": "רחובות לפי סוג",
        "names_note": (f"{n(len(name_rows))} שמות הרחובות שמופיעים בהכי הרבה ישובים. שם עם ה׳ הידיעה "
                       f"ובלעדיה (הזית / זית) נספר כשם אחד; הצבע מסמן את הנושא."),
        "names_aria": ("גרף עמודות אופקי: שמות הרחובות הנפוצים לפי מספר ישובים. "
                       + (f"{name_rows[0]['name']} מוביל עם {n(name_rows[0]['locs'])} ישובים." if name_rows else "")),
        "names_caption": "שמות הרחובות הנפוצים לפי מספר ישובים",
        "themes_note": ("על שם מה נקראים הרחובות: התאמה לרשימות מילים של עצים וצמחים, ציפורים ואבני חן, "
                        "ושמות שפותחים ב״הרב״/״רבי״, ״מבצע״, ״נחל״ או ״הר״. רחוב שלא התאים לאף רשימה "
                        "אינו נספר."),
        "themes_aria": "גרף עמודות אופקי: מספר הרחובות לפי נושא השם.",
        "themes_caption": "רחובות לפי נושא השם",
        "people_note": (f"בכמה ישובים יש רחוב, כיכר או שכונה על שם כל אחת מ-{n(len(PEOPLE))} אישויות "
                        f"שנבדקו, לפי הכתיבים שבמרשם (למשל ״בגין מנחם״ ו״מנחם בגין״)."),
        "people_aria": ("גרף עמודות אופקי: אישים לפי מספר הישובים עם רחוב על שמם. "
                        + (f"{people_rows[0]['name']} מוביל עם {n(people_rows[0]['locs'])}." if people_rows else "")),
        "people_caption": "אישים לפי מספר ישובים עם רחוב על שמם",
        "numbered_note": (f"{n(n_numbered)} רחובות ב-{n(n_num_locs)} ישובים נושאים מספר בלבד (״רח 12״). "
                          f"מוצגים {n(len(num_rows))} הישובים עם הכי הרבה רחובות ממוספרים, וחלקם מכלל הרחובות בישוב."),
        "numbered_aria": ("גרף עמודות אופקי מוערם: שיעור הרחובות הממוספרים בישובים עם הכי הרבה רחובות ממוספרים. "
                          + (f"{num_rows[0]['name']} מובילה עם {n(num_rows[0]['numbered'])}." if num_rows else "")),
        "numbered_caption": "הישובים עם הכי הרבה רחובות ממוספרים",
    }
    if ch:
        labels.update({
            "growth_note": (f"סמלי רחוב שמופיעים ברשימה הנוכחית ולא באף אחד מהקבצים הקודמים במאגר. "
                            f"רחובות נוספו ב-{n(ch['grew_locs'])} ישובים"
                            + (f", מהם {n(ch['new_locs'])} שלא היו בהם רחובות קודם" if ch["new_locs"] else "")
                            + f"; מוצגים {n(len(ch['growth']))} הישובים שבהם נוספו הכי הרבה."),
            "growth_aria": ("גרף עמודות אופקי מוערם: רחובות שנוספו ורחובות קיימים בישובים עם הגידול הגדול ביותר. "
                            + (f"{ch['growth'][0]['name']} מובילה עם {n(ch['growth'][0]['added'])} רחובות חדשים." if ch["growth"] else "")),
            "growth_caption": "הישובים שבהם נוספו הכי הרבה רחובות",
        })
    if ren:
        labels.update({
            "renames_note": (f"{n(ren['total'])} רחובות ששמם שונה מהשם בקבצים הקודמים, כשסמל הרחוב נשמר"
                             + (f" (לא כולל {n(ren['spelling'])} שינויי כתיב בלבד)" if ren["spelling"] else "")
                             + (f"; {n(ren['from_number'])} מהם היו ממוספרים וקיבלו שם" if ren["from_number"] else "")
                             + f". מוצגת דוגמה אחת מכל אחד מ-{n(len(ren['rows']))} הישובים עם הכי הרבה שינויים."),
            "renames_caption": "רחובות ששמם שונה לעומת הקבצים הקודמים",
        })

    top_person = people_rows[0]["name"] if people_rows else ""
    agent_data = {
        "summary_he": (f"{n(n_streets)} רחובות ב-{n(n_locs)} ישובים לפי מרשם האוכלוסין: {a0['name']} "
                       f"עם הכי הרבה רחובות ({n(a0['count'])}), "
                       + (f"{name_rows[0]['name']} השם הנפוץ ביותר ({n(name_rows[0]['locs'])} ישובים)"
                          if name_rows else "")
                       + (f", ו-{n(ch['added'])} רחובות חדשים לעומת הקבצים הקודמים." if ch else ".")),
        "dataset_kind": "registry",
        "suggested_tags": ["רחובות", "שמות רחובות", "כתובות", "ישובים", "מרשם אוכלוסין", "הנצחה"],
        "related_ids": [
            "3fc54b81-25b3-4ac7-87db-248c3e1602de",
            "785ad9fb-6da6-426d-b5ea-b8e36febbc8a",
            "00172ee8-4433-4d5d-8fd4-11f0f08ce5c4",
            "9d86c8a9-9240-4fc4-86a3-834c539f9488",
            "7c27e23b-86f1-44ee-9d9b-4f8880ca0973",
        ],
        "spatial_coverage": "ישראל ויהודה והשומרון",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "top": top_chart, "dist": dist_chart, "types": types_chart, "names": names_chart,
            "themes": themes_chart, "people": people_chart, "numbered": numbered_chart,
            "growth": growth_chart, "theme_order": THEME_ORDER + ["אחר"],
        },
        "insights": insights,
        "labels": labels,
        "tables": {
            "top": top_rows, "dist": bucket_rows, "types": type_rows,
            "names": [{k: v for k, v in r.items() if k != "key"} for r in name_rows],
            "themes": theme_rows, "people": people_rows, "numbered": num_rows,
            "growth": ch["growth"] if ch else [], "renames": ren["rows"] if ren else [],
        },
        "flags": {"growth": bool(growth_chart), "renames": bool(ren and ren["rows"]),
                  "people": bool(people_rows), "themes": bool(theme_rows),
                  "numbered": bool(num_rows)},
        "top_person": top_person,
    }
