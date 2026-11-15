"""רשימת מומחים לבתי משפט, the Arabic edition: the family-court expert
list of the welfare ministry's assistance units (יחידות הסיוע), published in
Arabic.

One row per listing (~135): district(s) served, employing institute, expert
name, address, local authority, phones, profession, whether they give
opinions, fee text, free-text notes and languages. The whole list is
republished on each update, so the page is a snapshot. The Hebrew edition is
dataset 63445be8; this page follows its structure so the two read alike.

The source is Arabic and the page Hebrew: districts, professions, cities,
institutes and languages go through the lookup tables below after spelling
normalisation (diacritics, hamza forms, hyphen spacing). An unknown value is
never printed in Arabic: it falls into an "other" bucket and is counted.

Privacy: phones, addresses and the free-text notes (which carry private
e-mails) never reach the page. Notes feed only a fixed keyword tagging of
focus areas (counts). Experts are not named on the page; everything is
aggregated by profession, district, city, language, institute and fee.

Data quality handled here (disclosed in the copy):
- rows without an expert name are excluded, and so are rows whose expert
  cell holds an organisation (מרכז/מכון/עמותה … in Arabic) rather than a
  person: a shifted row;
- a profession cell that holds a phone note or an e-mail is "not stated";
  an Arabic profession not in the lookup is counted as "another field", and
  a mapped profession wins over an unmapped one in the same cell;
- an expert listed several times (name + profession) counts once: their
  districts, languages, institutes and note topics are united, and each fee
  class (rate, opinion) is the mean of the amounts their listings state;
  the city view counts listings;
- fee text is free-form: amounts are classified as an hourly/session rate or
  an opinion fee by the nearest keyword in the same clause, else by size
  (under 1,000 → rate); a range counts at its midpoint.
- one rounding rule everywhere: govlib.fmt.int_he (half up).
"""
import math
import re

import pandas as pd
from govlib import fmt, frame

TOP_CITIES = 12
TOP_INST = 10
MIN_BOX = 3
MIN_PROF = 3
AR_LOW_SHARE = 0.15
PROF_COLORS = ["#0068f5", "#0b3668", "#6c9fd8", "#3d70b0", "#b7d2f7", "#2658a0"]
OTHER_COLOR = "#6c757d"
OTHER_PROF = "תחומים אחרים"
UNMAPPED_PROF = "תחום אחר"
NATIONAL = "ארצי"
OTHER = "אחר"
OTHER_DIST = "מחוז אחר"
OTHER_INST = "מכונים אחרים"
OTHER_LANG = "שפה אחרת"
UNKNOWN = "לא צוין"
HEBREW, ARABIC = "עברית", "ערבית"

_DIACRITICS = re.compile("[\u064B-\u065F\u0670\u0640]")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def nz(s):
    """Normalise Arabic text for lookups: no diacritics or tatweel, one alef
    form, hyphens without spaces, no quotes, single spaces, no final period."""
    s = _DIACRITICS.sub("", str(s)).translate(_ARABIC_DIGITS)
    s = re.sub("[أإآ]", "ا", s)
    s = re.sub(r"[\"'״׳]", "", s)
    s = re.sub(r"\s*[-–]\s*", "-", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip(".").strip()


def _table(pairs):
    return {nz(k): v for k, v in pairs.items()}


DISTRICTS = _table({
    "قطري": NATIONAL,
    "الشمال": "צפון",
    "حيفا والشمال": "חיפה והצפון",
    "حيفا": "חיפה",
    "تل أبيب والمركز": "תל אביב והמרכז",
    "المركز": "מרכז",
    "القدس": "ירושלים",
    "بئر السبع والجنوب": "באר שבע והדרום",
    "الجنوب": "דרום",
})

PROFESSIONS = _table({
    "العلاج النفسي": "פסיכולוגיה",
    "علاج نفسي": "פסיכולוגיה",
    "علم النفس": "פסיכולוגיה",
    "أخصائي نفسي سريري": "פסיכולוגיה",
    "أخصائي نفسي": "פסיכולוגיה",
    "أخصائية نفسية": "פסיכולוגיה",
    "طب نفسي": "פסיכיאטריה",
    "الطب النفسي": "פסיכיאטריה",
    "طبيب نفسي": "פסיכיאטריה",
    "العمل الاجتماعي": "עבודה סוציאלית",
    "عمل اجتماعي": "עבודה סוציאלית",
    "عاملة اجتماعية": "עבודה סוציאלית",
    "عامل اجتماعي": "עבודה סוציאלית",
    "الطب": "רפואה",
    "طب": "רפואה",
    "طب الأطفال": "רפואת ילדים",
})

CITIES = _table({
    "تل أبيب - يافا": "תל אביב-יפו", "تل أبيب يافا": "תל אביב-יפו", "تل أبيب": "תל אביב-יפו",
    "القدس": "ירושלים", "حيفا": "חיפה", "أشدود": "אשדוד", "بيتح تكفا": "פתח תקווה",
    "كفار سابا": "כפר סבא", "ريشون لتسيون": "ראשון לציון", "بئر السبع": "באר שבע",
    "جفعتايم": "גבעתיים", "رمات هشارون": "רמת השרון", "روش بينا": "ראש פינה",
    "هود هشارون": "הוד השרון", "يوكنعام عيليت": "יקנעם עילית", "أم الفحم": "אום אל-פחם",
    "يفني": "יבנה", "يفنيه": "יבנה", "يافنه": "יבנה", "يبنه": "יבנה",
    "جافيم": "גבים", "كفار يونا": "כפר יונה", "موديعين": "מודיעין",
    "بيت حورون": "בית חורון", "إيال": "אייל", "مكابيم - رعوت": "מכבים-רעות",
    "جديرا": "גדרה", "أور يهودا": "אור יהודה", "رمات جان": "רמת גן", "جليل يام": "גליל ים",
    "الخضيرة": "חדרה", "كريات شمونه": "קריית שמונה", "كريات شمونة": "קריית שמונה",
    "زخرون يعكوف": "זכרון יעקב", "زيخرون يعكوف": "זכרון יעקב", "كفر تافور": "כפר תבור",
    "عفولة": "עפולה", "العفولة": "עפולה", "برديس حانا كركور": "פרדס חנה-כרכור",
    "تل موند": "תל מונד", "كفر أزار": "כפר אז\"ר", "معانيت": "מענית", "ريجبا": "רגבה",
    "كيبوتس نير عام": "ניר עם", "جفعات شموئيل": "גבעת שמואל",
    "كريات موتسكين": "קריית מוצקין", "موتسا عيليت": "מוצא עילית", "رحوفوت": "רחובות",
    "كريات بيالك": "קריית ביאליק", "كريات بياليك": "קריית ביאליק",
    "كنيرت (مجموعة)": "כנרת (קבוצה)", "نس تسيونا": "נס ציונה",
    "بنيامينا – جفعات عادا": "בנימינה-גבעת עדה", "البعينة - نجيدات": "בועיינה-נוג'ידאת",
    "رملة": "רמלה", "الرملة": "רמלה", "اللد": "לוד", "نتانيا": "נתניה", "هرتسليا": "הרצליה",
    "رعنانا": "רעננה", "حولون": "חולון", "بات يام": "בת ים", "الناصرة": "נצרת",
    "عكا": "עכו", "نهاريا": "נהריה", "بني براك": "בני ברק", "أشكلون": "אשקלון",
    "عسقلان": "אשקלון", "إيلات": "אילת", "طبريا": "טבריה", "كرميئيل": "כרמיאל",
    "موديعين مكابيم رعوت": "מודיעין-מכבים-רעות",
})
# A district name in the city column is not a city.
NOT_CITY = {nz(k) for k in ("الشمال", "الجنوب", "المركز", "قطري")}

INSTITUTES = _table({
    "مركز ديكل": "מרכז דקל", "معهد ديكل": "מרכז דקל", "معهد شاليم": "מכון שלם",
    "معهد ميماديم": "מכון ממדים", "بيت طالي": "בית טלי", "معهد رجفيم": "מכון רגעים",
    "مركز ديعا": "מרכז דעה", "معهد بساجوت": "מכון פסגות", "معهد نوف": "מכון נוף",
    "معهد شينوي": "מכון שינוי", "معهد أدار": "מכון אדר",
    "مؤسّسة أفيكيم (قنوات)": "מכון אפיקים", "مركز \"حوف هجليل\"": "מרכז חוף הגליל",
    "شاعريه تسيدك (خدمات طبية خاصة)": "שערי צדק (שר\"פ)",
    "معهد مينا للرعاية الاسرية": "מכון מינא לטיפול משפחתי",
    "معهد مركز تخيلِت": "מכון מרכז תכלת",
})

LANGUAGES = _table({
    "العبرية": HEBREW, "العبري": HEBREW, "العربية": ARABIC, "الإنجليزية": "אנגלית",
    "الانكليزية": "אנגלית", "الروسية": "רוסית", "الإسبانية": "ספרדית",
    "البرتغالية": "פורטוגזית", "الإيطالية": "איטלקית", "الألمانية": "גרמנית",
    "الدنماركية": "דנית", "الفرنسية": "צרפתית", "الأمهرية": "אמהרית",
    "اليديشية": "יידיש", "الرومانية": "רומנית", "الهنغارية": "הונגרית",
    "البولندية": "פולנית", "التركية": "טורקית", "الفارسية": "פרסית",
})
LANG_TOKEN = re.compile(r"^ال\S+ية$")
YES = nz("نعم")

# Note topics. Each stem must start a word: only a clitic (و ب ل ف ك) and/or
# the article may precede it, so "وصية" (a will) never matches inside
# "خصوصية" (privacy). "جنسية" alone can mean nationality, so it counts as
# "sexual" only after a noun it qualifies (اعتداء/خطورة/معالجة …).
_WORD_START = r"(?<![^\s\-():،,./])(?:[وبلفك])?(?:ال|ل)?"


def _w(*stems):
    return re.compile("|".join(_WORD_START + st for st in stems))


TOPICS = [
    ("מסוגלות הורית", _w(r"قدر\S* (?:ال)?والدي", r"قدرات (?:ال)?ابوية", r"كفاءة (?:ال)?والدية",
                         r"اداء (?:ال)?والدي")),
    ("ניכור הורי וחידוש קשר", _w(r"تنكر (?:ال)?والدي", r"اغتراب (?:ال)?والدي", r"تغريب (?:ال)?والدي",
                                 r"انكار (?:ال)?والدي", r"رفض (?:ال)?علاقة", r"تجديد (?:ال)?علاقة")),
    ("תיאום הורי", _w(r"تنسيق")),
    ("משמורת וזמני שהות", _w(r"حضانة", r"اوقات (?:ال)?(?:اقامة|مكوث)", r"مسؤولية (?:ال)?والدية",
                             r"ترتيبات (?:ال)?مبيت")),
    ("אימוץ", _w(r"تبني")),
    ("אפוטרופסות וכשירות", _w(r"وصاي", r"وصية", r"اهلية (?:ال)?قضائية", r"كفاءة (?:ال)?معرفية",
                              r"دعم (?:ال)?قرار")),
    ("מסוכנות ואלימות", _w(r"خطورة", r"عنف", r"مخاطر")),
    ("פגיעה מינית והתעללות", _w(r"جنسي(?!ة)",
                                r"(?:اعتداء|خطور|معالج|علاج|اصاب|فحوص)\S* (?:ال)?جنسية",
                                r"اعتداء", r"تنكيل", r"اهمال")),
    ("אבחונים", _w(r"تشخيص", r"تقييمات نفسية")),
    ("הדרכת הורים", _w(r"ارشاد\S* (?:للاهل|الاهل|للوالدين|الوالدي)")),
    ("טיפול זוגי ומשפחתי", _w(r"زوجي", r"(?:رعاي|رعائ|معالج|علاج)\S* (?:عائلي|اسري)")),
    ("התמכרויות", _w(r"ادمان")),
    ("ילדים ונוער", _w(r"اطفال", r"طفل", r"شبيبة", r"مراهق", r"شبان", r"شباب")),
]

# A person's name never starts with these; an expert cell that does is an
# organisation in the wrong column (a shifted row).
ORG_RE = re.compile(r"^(?:مركز|معهد|مؤسسة|عيادة|جمعية|شركة)(?:\s|$)")
# A profession token with a digit, an e-mail or a phone word is a note.
NOT_PROF_RE = re.compile(r"\d|@|هاتف|تلفون|بريد")

# Fee parsing. "ش.ج" (new shekel) carries periods that would end a clause,
# so it becomes "₪" first.
CURRENCY = re.compile(r"ش\s*[.،,]\s*ج\s*\.?|شيكل(?: جديد)?")
OP_KW = ("وجهة النظر", "وجهة نظر", "لوجهة", "للراي", "الراي", "راي", "تقرير")
HR_KW = ("للساعة", "الساعة", "لساعة", "ساعة", "للعلاج", "العلاجية", "جلسة")
NUM_RE = re.compile(r"\d{1,3}(?:[,،.]\d{3})+|\d+")
RANGE_JOIN = re.compile(r"^\s*(?:₪)?\s*(?:-|–|الى|حتى)\s*(?:₪)?\s*$")
OP_BUCKETS = [(0, 2000), (2000, 5000), (5000, 10000), (10000, 15000), (15000, None)]
K = 1000

n = fmt.int_he


def pct(v):
    """A 0-100 value as a rounded, bidi-isolated percent."""
    return fmt.isolate(f"{fmt.int_he(v)}%")


def ils(v):
    return f"{fmt.int_he(v)} ₪"


def _split(s):
    return [t for t in (nz(x) for x in re.split(r"[,،]", str(s))) if t]


def _first_kw(text, kws):
    pos = [text.find(k) for k in kws if k in text]
    return min(pos) if pos else None


def _num(tok):
    return int(re.sub(r"[,،.]", "", tok))


def parse_fee(raw):
    """Return (rate, opinion): the first amount of each class, or None."""
    s = CURRENCY.sub(" ₪ ", nz(raw))
    ms = [m for m in NUM_RE.finditer(s) if _num(m.group()) >= 100]
    groups = []
    for m in ms:
        v = _num(m.group())
        if groups and RANGE_JOIN.match(s[groups[-1]["end"]:m.start()]):
            groups[-1]["vals"].append(v)
            groups[-1]["end"] = m.end()
        else:
            groups.append({"start": m.start(), "end": m.end(), "vals": [v]})
    rate = opinion = None
    for i, g in enumerate(groups):
        after = s[g["end"]:groups[i + 1]["start"] if i + 1 < len(groups) else len(s)]
        before = s[groups[i - 1]["end"] if i else 0:g["start"]]
        val = (min(g["vals"]) + max(g["vals"])) / 2
        # Keywords count only within the number's own clause.
        after = re.split(r"[,،.;:]", after, maxsplit=1)[0]
        before = re.split(r"[,،.;]", before)[-1]
        kind = None
        for ctx in (after, before):
            po, ph = _first_kw(ctx, OP_KW), _first_kw(ctx, HR_KW)
            if po is None and ph is None:
                continue
            if po is None or ph is None:
                kind = "hr" if po is None else "op"
            elif ctx is after:
                kind = "op" if po < ph else "hr"
            else:
                kind = "op" if po > ph else "hr"
            break
        if kind is None:
            kind = "hr" if val < 1000 else "op"
        if kind == "hr" and rate is None:
            rate = val
        elif kind == "op" and opinion is None:
            opinion = val
    return rate, opinion


def _quant(vals, q):
    v = sorted(vals)
    if not v:
        return 0.0
    pos = (len(v) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def _median(vals):
    return _quant(vals, 0.5)


def _langs(s):
    out = []
    for tok in _split(s):
        for part in re.split(r"\s+و(?=ال)", tok):
            part = part.strip(" .")
            if not part:
                continue
            he = LANGUAGES.get(part)
            if he is None and LANG_TOKEN.match(part):
                he = OTHER_LANG
            if he and he not in out:
                out.append(he)
    return out


def _prof(cell):
    """(profession, distinct mapped fields, unmapped tokens) of one cell."""
    toks = [t for t in _split(cell) if not NOT_PROF_RE.search(t)]
    mapped = [PROFESSIONS[t] for t in toks if t in PROFESSIONS]
    unmapped = [t for t in toks if t not in PROFESSIONS]
    if mapped:
        prof = mapped[0]
    elif unmapped:
        prof = UNMAPPED_PROF
    else:
        prof = UNKNOWN
    return prof, list(dict.fromkeys(mapped)), unmapped


def _institute(cell):
    k = nz(cell)
    if not k or LANG_TOKEN.match(k):
        return None
    return INSTITUTES.get(k, OTHER_INST)


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _prepare(raw):
    df = pd.DataFrame({c: raw[c].map(lambda v: str(v).strip()).values for c in
                       ("expert", "district", "employer", "authority", "profession",
                        "opinion", "payment", "notes", "languages")})
    n_broken = int((df["expert"] == "").sum())
    df = df[df["expert"] != ""].copy()
    df["expert_k"] = df["expert"].map(nz)
    is_org = df["expert_k"].map(lambda s: bool(ORG_RE.match(s)))
    n_org = int(is_org.sum())
    df = df[~is_org].copy()
    parsed = df["profession"].map(_prof)
    df["prof"] = parsed.map(lambda t: t[0])
    df["n_mapped"] = parsed.map(lambda t: len(t[1]))
    mapped_fields = {f for t in parsed for f in t[1]}
    unmapped_tokens = {u for t in parsed for u in t[2]}
    fees = df["payment"].map(parse_fee)
    df["rate"] = fees.map(lambda f: f[0])
    df["op"] = fees.map(lambda f: f[1])
    df = df.sort_values(["expert_k", "prof", "authority", "district", "employer", "payment",
                         "languages", "notes", "opinion"], kind="stable").reset_index(drop=True)
    return df, n_broken, n_org, len(mapped_fields) + len(unmapped_tokens)


def _experts(df):
    """One row per (expert, profession), merging all of its listings."""
    rows = []
    for (ek, prof), g in df.groupby(["expert_k", "prof"], sort=True):
        dists, langs, insts, topics = set(), [], set(), set()
        for d, lg, emp, note in zip(g["district"], g["languages"], g["employer"], g["notes"]):
            dists.update(DISTRICTS.get(t, OTHER_DIST) for t in _split(d))
            langs.extend(x for x in _langs(lg) if x not in langs)
            inst = _institute(emp)
            if inst:
                insts.add(inst)
            t = nz(note)
            topics.update(name for name, rx in TOPICS if rx.search(t))
        rows.append({
            "expert_k": ek, "prof": prof, "listings": len(g),
            "dists": frozenset(dists), "langs": langs, "insts": frozenset(insts),
            "topics": frozenset(topics), "multi_prof": bool((g["n_mapped"] > 1).any()),
            "rate": _mean(g["rate"].tolist()), "op": _mean(g["op"].tolist()),
            "fee_spread": len({v for v in g["rate"] if v is not None}) > 1
            or len({v for v in g["op"] if v is not None}) > 1,
            "opinion": bool((g["opinion"].map(nz) == YES).any()),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- insights

def _in(names):
    """'בא ובב': the preposition ב on every name of a list."""
    return fmt.join_he([f"ב{x}" for x in names])


def _extreme_names(rows, pick):
    v = pick(r["med"] for r in rows)
    return [r["name"] for r in rows if r["med"] == v], v


def insight_prof(prof_counts, total):
    if len(prof_counts) < 2:
        return None
    a, b = prof_counts.index[0], prof_counts.index[1]
    va, vb = int(prof_counts.iloc[0]), int(prof_counts.iloc[1])
    if va == vb:
        return f"{a} ו{b} מובילות יחד ברשימה, עם {n(va)} מומחים כל אחת."
    rest = ""
    if len(prof_counts) > 2:
        rest = f" ו{prof_counts.index[2]} ({n(prof_counts.iloc[2])})"
    return (f"{a} הוא התחום הגדול ברשימה: {n(va)} מתוך {n(total)} המומחים "
            f"({pct(va / total * 100)}), ואחריו {b} ({n(vb)}){rest}.")


def insight_arabic(arabic, total, hebrew_only):
    if total == 0:
        return None
    share = arabic / total
    if arabic == 0:
        return (f"אף אחד מ-{n(total)} המומחים ברשימה אינו מציין ערבית כשפת עבודה, "
                f"אף שהרשימה מתפרסמת גם בערבית; {n(hebrew_only)} מציינים עברית בלבד.")
    if share >= AR_LOW_SHARE:
        return (f"{n(arabic)} מתוך {n(total)} המומחים ({pct(share * 100)}) מציינים ערבית "
                f"כשפת עבודה.")
    return (f"רק {n(arabic)} מתוך {n(total)} המומחים ({pct(share * 100)}) מציינים ערבית "
            f"כשפת עבודה, אף שהרשימה מתפרסמת גם בערבית; {n(hebrew_only)} מציינים עברית בלבד.")


def insight_national(n_nat, total, district_counts):
    if total == 0 or n_nat == 0:
        return None
    regional = district_counts[~district_counts.index.isin([NATIONAL, UNKNOWN, OTHER_DIST])]
    if regional.empty:
        return None
    if len(regional) > 1 and regional.iloc[1] == regional.iloc[0]:
        return None
    return (f"{n(n_nat)} מומחים ({pct(n_nat / total * 100)}) רשומים כארציים וזמינים לכל המחוזות; "
            f"מבין המחוזות, {regional.index[0]} מוביל עם {n(regional.iloc[0])} מומחים שרשומים לו במפורש.")


def insight_thin(district_counts, n_nat):
    regional = district_counts[~district_counts.index.isin([NATIONAL, UNKNOWN, OTHER_DIST])]
    if len(regional) < 2:
        return None
    vlo, vhi = int(regional.iloc[-1]), int(regional.iloc[0])
    if vlo * 2 > vhi:
        return None
    los = [d for d, v in regional.items() if v == vlo]
    his = [d for d, v in regional.items() if v == vhi]
    lo_txt = f"במחוז {los[0]}" if len(los) == 1 else f"במחוזות {fmt.join_he(los)}"
    tail = (f" מעבר ל-{n(n_nat)} הארציים, ההיצע הייעודי למחוז מצומצם." if n_nat else "")
    return f"{lo_txt} רשומים במפורש רק {n(vlo)} מומחים, לעומת {n(vhi)} {_in(his)}.{tail}"


def insight_cities(known, n_with_city):
    if len(known) < 3 or n_with_city == 0:
        return None
    a, b = known.index[0], known.index[1]
    top2 = int(known.iloc[0]) + int(known.iloc[1])
    share = top2 / n_with_city
    if share < 0.15 or known.iloc[2] == known.iloc[1]:
        return None
    return (f"{a} ({n(known.iloc[0])}) ו{b} ({n(known.iloc[1])}) מרכזות {pct(share * 100)} "
            f"מהרישומים שבהם צוין יישוב; הרישומים פרושים על פני {n(len(known))} יישובים לפחות.")


def insight_langs(lang_counts, hebrew_only, n_other):
    total = hebrew_only + n_other
    if total == 0 or n_other / total < 0.05:
        return None
    nonheb = [x for x in lang_counts.index if x not in (HEBREW, ARABIC, UNKNOWN, OTHER_LANG)]
    lead = f", בעיקר {nonheb[0]} ({n(lang_counts[nonheb[0]])})" if nonheb else ""
    return (f"מבין {n(total)} המומחים שציינו שפה, {n(hebrew_only)} ({pct(hebrew_only / total * 100)}) "
            f"מציינים עברית בלבד ו-{n(n_other)} מציינים שפה נוספת או אחרת{lead}.")


def insight_rates(box_rows):
    rows = [r for r in box_rows if r["n"] >= MIN_BOX]
    if len(rows) < 2:
        return None
    his, vhi = _extreme_names(rows, max)
    los, vlo = _extreme_names(rows, min)
    if vlo <= 0 or vhi / vlo < 1.1 or len(his) > 1:
        return None
    hi = next(r for r in rows if r["name"] == his[0])
    lo_n = sum(r["n"] for r in rows if r["name"] in los)
    lo_txt = (f"{ils(vlo)} ב{los[0]} ({n(lo_n)})" if len(los) == 1
              else f"{ils(vlo)} {_in(los)} ({n(lo_n)} יחד)")
    return (f"התעריף החציוני לשעה או לפגישה גבוה ביותר ב{his[0]}: {ils(vhi)} "
            f"({n(hi['n'])} מומחים שציינו תעריף), לעומת {lo_txt}.")


def insight_opinion(ops):
    if len(ops) < 5:
        return None
    return (f"{n(len(ops))} מומחים ציינו מחיר לחוות דעת: החציון {ils(_median(ops))}, ומחצית "
            f"המחירים נעים בין {ils(_quant(ops, 0.25))} ל-{ils(_quant(ops, 0.75))}. הזול ביותר "
            f"{ils(min(ops))} והיקר ביותר {ils(max(ops))}.")


def insight_op_prof(op_rows):
    rows = [r for r in op_rows if r["n"] >= 5]
    if len(rows) < 2:
        return None
    his, vhi = _extreme_names(rows, max)
    los, vlo = _extreme_names(rows, min)
    if vlo <= 0 or vhi / vlo < 1.15 or len(his) > 1:
        return None
    hi = next(r for r in rows if r["name"] == his[0])
    lo_n = sum(r["n"] for r in rows if r["name"] in los)
    lo_txt = (f"ב{los[0]} ({ils(vlo)}, {n(lo_n)})" if len(los) == 1
              else f"{_in(los)} ({ils(vlo)} בכל אחד, {n(lo_n)} מומחים יחד)")
    return (f"המחיר החציוני לחוות דעת גבוה ביותר ב{his[0]} ({ils(vhi)}, "
            f"{n(hi['n'])} מומחים), ונמוך ביותר {lo_txt}.")


def insight_inst(n_inst, total, named_inst):
    if total == 0 or named_inst.empty or int(named_inst.iloc[0]) < 2:
        return None
    if len(named_inst) > 1 and named_inst.iloc[1] == named_inst.iloc[0]:
        top = f"הגדולים שבהם {fmt.join_he([k for k, v in named_inst.items() if v == named_inst.iloc[0]])}"
    else:
        top = f"הגדול שבהם {named_inst.index[0]}"
    return (f"{n(total - n_inst)} מהמומחים ({pct((total - n_inst) / total * 100)}) רשומים ללא מכון; "
            f"{n(n_inst)} פועלים דרך מכון או מרכז, {top} ({n(named_inst.iloc[0])} מומחים).")


def insight_topics(topic_counts, n_tagged):
    if n_tagged < 10 or topic_counts.empty:
        return None
    a, va = topic_counts.index[0], int(topic_counts.iloc[0])
    if va / n_tagged < 0.2 or (len(topic_counts) > 1 and topic_counts.iloc[1] == va):
        return None
    second = ""
    if len(topic_counts) > 1:
        second = f", ואחריו {topic_counts.index[1]} ({n(topic_counts.iloc[1])})"
    return (f"התחום הנזכר הכי הרבה בתיאורי המומחים הוא {a}: {n(va)} מתוך {n(n_tagged)} "
            f"שתיאורם מזכיר תחום מוכר{second}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df, n_broken, n_org, n_fields = _prepare(frames["experts"])
    n_listings = len(df)
    ex = _experts(df)
    total = len(ex)

    # professions: fields under MIN_PROF experts, unmapped and unstated ones
    # share the "other" bucket (a lone small named field keeps its name)
    raw_counts = frame.ranked(ex["prof"])
    small = [p for p, v in raw_counts.items()
             if p in (UNKNOWN, UNMAPPED_PROF) or v < MIN_PROF]
    if len(small) == 1 and small[0] not in (UNKNOWN, UNMAPPED_PROF):
        small = []
    small_set = set(small)
    small_named = [p for p in small if p not in (UNKNOWN, UNMAPPED_PROF)]
    n_unmapped_prof = int(raw_counts.get(UNMAPPED_PROF, 0))
    n_unknown_prof = int(raw_counts.get(UNKNOWN, 0))
    for fr in (df, ex):
        fr["prof"] = fr["prof"].map(lambda p: OTHER_PROF if p in small_set else p)
    prof_counts = frame.ranked(ex["prof"])
    profs = [p for p in prof_counts.index if p != OTHER_PROF] + \
        ([OTHER_PROF] if OTHER_PROF in prof_counts.index else [])
    prof_counts = prof_counts[profs]
    color = {p: (OTHER_COLOR if p == OTHER_PROF else PROF_COLORS[i % len(PROF_COLORS)])
             for i, p in enumerate(profs)}
    n_multi_prof = int(ex["multi_prof"].sum())

    # districts (expert level, union over listings)
    ex["national"] = ex["dists"].map(lambda d: NATIONAL in d)
    n_nat = int(ex["national"].sum())
    drows = []
    for prof, ds, nat in zip(ex["prof"], ex["dists"], ex["national"]):
        if nat:
            drows.append((NATIONAL, prof))
        elif not ds:
            drows.append((UNKNOWN, prof))
        else:
            drows.extend((d, prof) for d in sorted(ds))
    dd = pd.DataFrame(drows, columns=["d", "p"])
    district_counts = frame.ranked(dd["d"])
    regional = [d for d in district_counts.index if d not in (NATIONAL, UNKNOWN, OTHER_DIST)]
    dorder = [NATIONAL] * (NATIONAL in district_counts.index) + regional + \
        [OTHER_DIST] * (OTHER_DIST in district_counts.index) + \
        [UNKNOWN] * (UNKNOWN in district_counts.index)
    dx = dd.groupby(["d", "p"]).size()

    # cities (listings); an unmapped Arabic name goes to "אחר", never printed
    city_rows = []
    n_unknown_city = 0
    n_unmapped_city = 0
    for s, p in zip(df["authority"], df["prof"]):
        toks = [t for t in _split(s) if t not in NOT_CITY]
        if not toks:
            n_unknown_city += 1
            continue
        for t in toks:
            he = CITIES.get(t)
            if he is None:
                n_unmapped_city += 1
            city_rows.append((he or OTHER, p))
    cdf = pd.DataFrame(city_rows, columns=["c", "p"])
    n_with_city = n_listings - n_unknown_city
    known = frame.ranked(cdf.loc[cdf["c"] != OTHER, "c"]) if len(cdf) else pd.Series(dtype=int)
    c_labels, _ = frame.top_other(known, TOP_CITIES)
    top_c = [c for c in c_labels if c in known.index]
    n_rest_c = len(known) - len(top_c)
    cdf["c2"] = cdf["c"].map(lambda c: c if c in top_c else OTHER)
    cp = cdf.groupby(["c2", "p"]).size() if len(cdf) else pd.Series(dtype=int)
    c_names = top_c + ([OTHER] if (n_rest_c or n_unmapped_city) else [])

    # languages (union over an expert's listings)
    lang_lists = ex["langs"]
    lang_counts = frame.ranked(pd.Series([t for ls in lang_lists for t in ls], dtype=str))
    n_no_lang = int(sum(1 for ls in lang_lists if not ls))
    if n_no_lang:
        lang_counts = pd.concat([lang_counts, pd.Series({UNKNOWN: n_no_lang})])
    hebrew_only = int(sum(1 for ls in lang_lists if ls == [HEBREW]))
    n_other_lang = total - hebrew_only - n_no_lang
    arabic = int(sum(1 for ls in lang_lists if ARABIC in ls))
    n_multi_lang = int(sum(1 for ls in lang_lists if len(ls) >= 2))
    ar_prof = frame.ranked(ex.loc[[ARABIC in ls for ls in lang_lists], "prof"])

    # institutes (an expert counts once under each institute they list)
    n_inst = int(sum(1 for s in ex["insts"] if s))
    inst_flat = pd.Series([i for s in ex["insts"] for i in sorted(s)], dtype=str)
    named_inst = frame.ranked(inst_flat[inst_flat != OTHER_INST])
    n_unmapped_inst = int((inst_flat == OTHER_INST).sum())
    i_labels, i_values = frame.top_other(named_inst, TOP_INST, OTHER_INST)
    if n_unmapped_inst:
        if i_labels and i_labels[-1] == OTHER_INST:
            i_values[-1] += n_unmapped_inst
        else:
            i_labels.append(OTHER_INST)
            i_values.append(n_unmapped_inst)
    top_i = [i for i in i_labels if i != OTHER_INST]
    rest_i = OTHER_INST in i_labels

    # fees (one value per expert per class: the mean over their listings)
    rates = sorted(float(x) for x in ex["rate"].dropna())
    ops = sorted(float(x) for x in ex["op"].dropna())
    n_fee_spread = int(ex["fee_spread"].sum())
    box_rows, op_rows = [], []
    for p in profs:
        v = sorted(float(x) for x in ex.loc[ex["prof"] == p, "rate"].dropna())
        if v:
            q1, q3 = _quant(v, .25), _quant(v, .75)
            iqr = q3 - q1
            lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            inside = [x for x in v if lo_f <= x <= hi_f]
            box_rows.append({"name": p, "n": len(v), "min": v[0], "q1": q1, "med": _median(v),
                             "q3": q3, "max": v[-1], "wlo": inside[0], "whi": inside[-1],
                             "out": [x for x in v if x < lo_f or x > hi_f]})
        o = sorted(float(x) for x in ex.loc[ex["prof"] == p, "op"].dropna())
        if o:
            op_rows.append({"name": p, "n": len(o), "med": _median(o)})
    box_shown = [r for r in box_rows if r["n"] >= MIN_BOX]
    box_hidden = [r for r in box_rows if r["n"] < MIN_BOX]
    op_labels = []
    for lo, hi in OP_BUCKETS:
        if lo == 0:
            op_labels.append(f"עד {hi // K} אלף")
        elif hi is None:
            op_labels.append(f"{lo // K} אלף ומעלה")
        else:
            op_labels.append(f"{lo // K} עד {hi // K} אלף")

    def _bucket(v):
        for i, (lo, hi) in enumerate(OP_BUCKETS):
            if v >= lo and (hi is None or v < hi):
                return i
        return len(OP_BUCKETS) - 1
    op_pairs = [(_bucket(v), p) for p, v in zip(ex["prof"], ex["op"]) if not pd.isna(v)]
    op_df = pd.DataFrame(op_pairs, columns=["b", "p"])
    op_x = op_df.groupby(["b", "p"]).size() if len(op_df) else pd.Series(dtype=int)
    op_profs = [p for p in profs if len(op_df) and (op_df["p"] == p).any()]

    # topics from notes (keyword tagging; the notes themselves never reach the page)
    n_tagged = int(sum(1 for t in ex["topics"] if t))
    tflat = pd.DataFrame([(t, p) for p, ts in zip(ex["prof"], ex["topics"]) for t in sorted(ts)],
                         columns=["t", "p"])
    topic_counts = frame.ranked(tflat["t"]) if len(tflat) else pd.Series(dtype=int)
    tx = tflat.groupby(["t", "p"]).size() if len(tflat) else pd.Series(dtype=int)
    t_names = list(topic_counts.index)
    t_profs = [p for p in profs if len(tflat) and (tflat["p"] == p).any()]

    n_opinion = int(ex["opinion"].sum())

    def stack(index_names, profs_list, lookup):
        return [{"name": p, "color": color[p],
                 "data": [int(lookup.get((k, p), 0)) for k in index_names]} for p in profs_list]

    charts = {
        "prof": {"names": profs, "values": [int(v) for v in prof_counts.values],
                 "colors": [color[p] for p in profs]},
        "districts": {"x": dorder, "series": stack(dorder, profs, dx)},
        "cities": {"names": c_names, "series": stack(c_names, profs, cp)},
        "topics": {"names": t_names, "series": stack(t_names, t_profs, tx)},
        "rates": {"names": [r["name"] for r in box_shown],
                  "boxes": [[r["wlo"], r["q1"], r["med"], r["q3"], r["whi"]] for r in box_shown],
                  "outliers": [[i, x] for i, r in enumerate(box_shown) for x in r["out"]]},
        "opinion": {"x": op_labels,
                    "series": [{"name": p, "color": color[p],
                                "data": [int(op_x.get((i, p), 0)) for i in range(len(OP_BUCKETS))]}
                               for p in op_profs]},
        "langs": {"names": list(lang_counts.index), "values": [int(v) for v in lang_counts.values]},
        "inst": {"names": i_labels, "values": [int(v) for v in i_values]},
    }

    rules = [
        ("prof", insight_prof(prof_counts, total)),
        ("arabic", insight_arabic(arabic, total, hebrew_only)),
        ("national", insight_national(n_nat, total, district_counts)),
        ("thin", insight_thin(district_counts, n_nat)),
        ("cities", insight_cities(known, n_with_city)),
        ("langs", insight_langs(lang_counts, hebrew_only, n_other_lang)),
        ("rates", insight_rates(box_rows)),
        ("opinion", insight_opinion(ops)),
        ("op_prof", insight_op_prof(op_rows)),
        ("inst", insight_inst(n_inst, total, named_inst)),
        ("topics", insight_topics(topic_counts, n_tagged)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    med_rate = _median(rates) if rates else 0
    med_op = _median(ops) if ops else 0
    ar_share = arabic / total if total else 0
    kpis = {
        "experts": {"value": total, "display": n(total), "tone": "brand"},
        "arabic": {"value": arabic, "display": n(arabic),
                   "tone": "warn" if ar_share < AR_LOW_SHARE else "ok"},
        "rate": {"value": med_rate, "display": n(med_rate), "tone": "brand"},
        "opinion": {"value": med_op, "display": n(med_op), "tone": "brand"},
    }

    dup_listings = n_listings - total
    excl = []
    if n_broken:
        excl.append("שורה אחת ללא שם מומחה הושמטה" if n_broken == 1 else
                    f"{n(n_broken)} שורות ללא שם מומחה הושמטו")
    if n_org:
        excl.append("רישום אחד שבו מופיע שם של מרכז או מכון במקום שם המומחה הושמט" if n_org == 1 else
                    f"{n(n_org)} רישומים שבהם מופיע שם של מרכז או מכון במקום שם המומחה הושמטו")
    if dup_listings:
        excl.append(f"מומחה הרשום כמה פעמים נספר פעם אחת ({n(dup_listings)} רישומים נוספים), "
                    f"עם כל המחוזות, השפות והמכונים שברישומיו")
    excl_txt = (" " + "; ".join(excl) + ".") if excl else ""
    opinion_txt = (" כל המומחים ברשימה מסומנים כנותני חוות דעת." if n_opinion == total
                   else f" {n(n_opinion)} מהם מסומנים כנותני חוות דעת.")
    ar_profs_txt = ", ".join(f"{p} {n(v)}" for p, v in ar_prof.items())
    prof_extra = []
    if n_unmapped_prof:
        prof_extra.append(f"{n(n_unmapped_prof)} בתחום שלא זוהה")
    if n_unknown_prof:
        prof_extra.append(f"{n(n_unknown_prof)} שלא צוין תחומם")
    other_parts = small_named + prof_extra
    fee_merge_txt = (" מומחה הרשום כמה פעמים עם סכומים שונים נספר לפי ממוצע הסכומים שברישומיו."
                     if n_fee_spread else "")
    labels = {
        "lede": (f"זהו הנוסח הערבי של רשימת המומחים שיחידות הסיוע של משרד הרווחה מעמידות לרשות "
                 f"בתי המשפט לענייני משפחה: {n(total)} מומחים ב-{n(n_fields)} תחומים, "
                 f"ב-{n(n_listings)} רישומים.{opinion_txt} העמוד מציג את התמונה המצרפית בעברית: "
                 f"תחום, מחוז, יישוב, שפה, מכון ושכר טרחה; פרטי הקשר של כל מומחה, בערבית, מופיעים "
                 f"בטבלת הנתונים שבתחתית העמוד.{excl_txt}"),
        "lookup_title": "איתור מומחה לבית המשפט לענייני משפחה ←",
        "lookup_sub": "חיפוש חי בכל רשומות הרשימה (בערבית): שם המומחה, תחום, מחוז, יישוב, מכון ושפות",
        "experts_kpi": "מומחים ברשימה",
        "arabic_kpi": f"מומחים המציינים ערבית ({pct(ar_share * 100)} מהרשימה)",
        "rate_kpi": f"תעריף חציוני לשעה או לפגישה (₪, {n(len(rates))} מומחים)",
        "opinion_kpi": f"מחיר חציוני לחוות דעת (₪, {n(len(ops))} מומחים)",
        "prof_note": ("מספר המומחים בכל תחום מקצועי."
                      + (f" {OTHER_PROF} ({', '.join(other_parts)}) מקובצים יחד, כאן ובכל התרשימים."
                         if other_parts and OTHER_PROF in profs else "")
                      + ((" מומחה אחד שציין שני תחומים נספר לפי הראשון." if n_multi_prof == 1 else
                          f" {n(n_multi_prof)} מומחים שציינו שני תחומים נספרים לפי הראשון.") if n_multi_prof else "")),
        "prof_aria": (f"תרשים טבעת: מומחים לפי תחום, {profs[0]} בראש עם {n(prof_counts.iloc[0])} "
                      f"מתוך {n(total)}." if profs else "תרשים טבעת: מומחים לפי תחום."),
        "prof_caption": "מספר המומחים לפי תחום מקצועי.",
        "districts_note": (f"מספר המומחים הרשומים לכל מחוז, לפי תחום. {n(n_nat)} המומחים הארציים מוצגים בשורה "
                           f"נפרדת וזמינים בכל המחוזות; מומחה הרשום בכמה מחוזות נספר בכל אחד מהם."),
        "districts_aria": (f"גרף עמודות אופקיות מוערמות: מומחים לפי מחוז ותחום, {n(n_nat)} ארציים, "
                           f"והמחוז המוביל {regional[0]}." if regional
                           else "גרף עמודות אופקיות מוערמות: מומחים לפי מחוז."),
        "districts_caption": "מספר המומחים לפי מחוז ותחום.",
        "cities_note": (f"{len(top_c)} היישובים עם הכי הרבה רישומים, לפי תחום (כל כתובת נספרת)"
                        + (f"; {n(n_rest_c)} יישובים נוספים מקובצים ב\"אחר\"" if n_rest_c else "")
                        + (f"; {n(n_unmapped_city)} רישומים ביישוב ששמו בערבית לא זוהה נספרים ב\"אחר\""
                           if n_unmapped_city else "")
                        + (f". ב-{n(n_unknown_city)} רישומים לא צוין יישוב והם אינם בתרשים." if n_unknown_city else ".")),
        "cities_aria": (f"תרשים עמודות אופקי: רישומים לפי יישוב, {top_c[0]} בראש עם "
                        f"{n(known[top_c[0]])}." if top_c else "תרשים עמודות אופקי: רישומים לפי יישוב."),
        "cities_caption": "מספר הרישומים לפי יישוב ותחום.",
        "topics_note": (f"כמה מומחים מזכירים כל תחום עיסוק בתיאור החופשי שלהם (בערבית), לפי מילות מפתח "
                        f"({n(n_tagged)} מתוך {n(total)} מומחים מזכירים תחום אחד לפחות; מומחה יכול להופיע בכמה תחומים)."),
        "topics_aria": (f"תרשים עמודות אופקי: תחומי עיסוק, {t_names[0]} בראש עם {n(topic_counts.iloc[0])} "
                        f"מומחים." if t_names else "תרשים עמודות אופקי: תחומי עיסוק."),
        "topics_caption": "מספר המומחים המזכירים כל תחום עיסוק.",
        "rates_note": (f"פיזור התעריף לשעה או לפגישה בכל תחום ({n(len(rates))} מומחים שציינו תעריף): "
                       f"הקופסה מסמנת את המחצית האמצעית והקו את החציון, בסולם לוגריתמי. סכומים בטקסט החופשי סווגו לפי "
                       f"המילה הסמוכה (לשעה, לטיפול, לחוות דעת), ובהיעדרה לפי גודל: "
                       f"סכום מתחת ל-{n(K)} ₪ נחשב תעריף; טווח נספר לפי אמצעו. נקודות מסמנות ערכים חריגים."
                       + fee_merge_txt
                       + (f" תחומים עם פחות מ-{MIN_BOX} תעריפים אינם מוצגים." if box_hidden else "")),
        "rates_aria": f"תרשים קופסה בסולם לוגריתמי: תעריף לשעה לפי תחום, חציון כללי {ils(med_rate)}.",
        "rates_caption": "תעריף לשעה או לפגישה לפי תחום (₪).",
        "opinion_note": (f"מחיר חוות דעת שציינו {n(len(ops))} מומחים, לפי טווח מחיר ותחום (אלפי ₪; כל טווח "
                         f"כולל את גבולו התחתון בלבד). טווח מחירים שציין מומחה נספר לפי אמצעו."
                         + fee_merge_txt),
        "opinion_aria": f"גרף עמודות אופקיות מוערמות: מחיר חוות דעת לפי טווח ותחום, חציון {ils(med_op)}.",
        "opinion_caption": "מספר המומחים לפי טווח מחיר חוות דעת ותחום.",
        "langs_note": (f"מספר המומחים המציינים כל שפה ({n(n_multi_lang)} מציינים שתי שפות או יותר)."
                       + (f" מבין המציינים ערבית: {ar_profs_txt}." if arabic else "")),
        "langs_aria": (f"תרשים עמודות אופקי: מומחים לפי שפה, {lang_counts.index[0]} בראש עם "
                       f"{n(lang_counts.iloc[0])}." if len(lang_counts) else "תרשים עמודות אופקי: מומחים לפי שפה."),
        "langs_caption": "מספר המומחים לפי שפה.",
        "inst_note": (f"{n(n_inst)} מומחים פועלים דרך מכון או מרכז; {n(total - n_inst)} רשומים ללא מכון. "
                      f"מומחה הרשום בכמה מכונים נספר בכל אחד מהם."
                      + (f" מוצגים {len(top_i)} המכונים הגדולים; השאר מקובצים ב\"{OTHER_INST}\"." if rest_i else "")),
        "inst_aria": (f"תרשים עמודות אופקי: מומחים לפי מכון, {top_i[0]} בראש עם "
                      f"{n(named_inst.iloc[0])}." if top_i else "תרשים עמודות אופקי: מומחים לפי מכון."),
        "inst_caption": "מספר המומחים לפי מכון.",
    }

    tables = {
        "prof": [[p, n(v), fmt.pct(v / total)] for p, v in prof_counts.items()],
        "prof_cols": profs,
        "districts": [{"name": d, "vals": [n(dx.get((d, p), 0)) for p in profs],
                       "total": n(sum(int(dx.get((d, p), 0)) for p in profs))} for d in dorder],
        "cities": [{"name": c, "vals": [n(cp.get((c, p), 0)) for p in profs],
                    "total": n(sum(int(cp.get((c, p), 0)) for p in profs))} for c in c_names],
        "topics": [[t, n(topic_counts[t]), fmt.pct(topic_counts[t] / n_tagged, 0)] for t in t_names],
        "rates": [[r["name"], n(r["n"]), n(r["min"]), n(r["med"]), n(r["max"])] for r in box_rows],
        "opinion": [[lab, n(sum(int(op_x.get((i, p), 0)) for p in op_profs))]
                    for i, lab in enumerate(op_labels)],
        "langs": [[k, n(v)] for k, v in lang_counts.items()],
        "inst": [[k, n(v)] for k, v in zip(i_labels, i_values)],
    }

    top3 = ", ".join(profs[:3])
    return {
        "agent_data": {
            "summary_he": (f"הנוסח הערבי של רשימת {n(total)} המומחים שיחידות הסיוע מעמידות לבתי המשפט "
                           f"לענייני משפחה, לפי תחום ({top3}), מחוז, יישוב, שפה ושכר טרחה."),
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מומחים לבית המשפט לענייני משפחה | הרשימה בערבית",
                "description": (f"איתור מומחה לבית המשפט לענייני משפחה בנוסח הערבי: "
                                f"{n(total)} מומחים ({top3}), מתוכם {n(arabic)} דוברי ערבית, "
                                f"ושכר טרחה חציוני."),
                "name": "רשימת מומחים לבית המשפט לענייני משפחה (נוסח ערבי)",
                "alternate_names": [
                    "רשימת מומחים לבתי משפט בערבית",
                    "מומחים לבית משפט לענייני משפחה",
                    "רשימת מומחים יחידות הסיוע",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"rates": len(box_shown) > 0, "opinion": len(ops) > 0, "topics": len(t_names) > 0,
                  "inst": len(top_i) > 0, "cities": len(top_c) > 0},
    }
