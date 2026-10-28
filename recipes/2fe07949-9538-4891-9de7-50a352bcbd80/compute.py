"""אתרי בניה שנסגרו — construction sites closed by the Ministry of Labour's
safety administration (one row per closure: site name, executor, date).

A log that grows by appending closures. "Now" is the latest closure date in
the data: trailing-12-month windows end there, and a first or last calendar
year that the data covers only partly is labelled partial and kept out of the
peak-year rule (judged by the months the data covers, never today's date).

Exact duplicate rows (same site, executor and date) are counted once; the
page says how many were merged.

Three columns only, so two dimensions are derived from the free-text site
name, both disclosed on the page as automatic:
  * locality — matched against the ministry's locality→district table
    (TOWNS) plus a few spelling aliases; the rightmost, longest match wins
    (site names usually end with the town). No match → UNKNOWN_CITY.
  * project kind — a keyword classifier (KINDS, first match wins); names that
    are a bare street address land in ADDRESS_ONLY.
Executors are classed as company / private permit holder / other. Rankings
name only executors identifiable as corporate; private individuals (and the
personal names inside site names) are never put on the page.
"""
import re

import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
# pandas dayofweek: Monday=0 … Sunday=6; shown Sunday-first.
WEEKDAYS = [(6, "ראשון"), (0, "שני"), (1, "שלישי"), (2, "רביעי"), (3, "חמישי"),
            (4, "שישי"), (5, "שבת")]

CORPORATE_RE = re.compile(
    r'בע"מ|בע״מ|בעמ|בע\'\'מ|בע"ם|ע"ר|ע״ר|עמותה|עמותת|\bLTD\b|Ltd|L\.P|לימיטד|אל טי די|'
    r'שותפות|חברה|חברת|קבוצת|מיזם משותף|קונסטרוקשן|קונסטרקשן|קומפני|גרופ|תאגיד|'
    r'מועצה|עיריית|רשות'
)
PRIVATE_RE = re.compile(r"^פרטי$|בעל(?:ת|י)? (?:ה)?היתר|בעל הנכס|בעלים |יזם הבנייה")
EXEC_TYPES = ["חברה או תאגיד", "בעל היתר פרטי", "אדם או עסק ללא סימון תאגיד"]

UNKNOWN_CITY = "לא זוהה"
ADDRESS_ONLY = "כתובת בלבד / לא סווג"
TOP_CITIES = 15
TOP_EXEC = 12
TREND_GAP = 0.15        # 12-month change below this is called stable
MIN_FOR_SHARE = 30      # closures needed before a share-based rule speaks
GAP_DAYS = 30           # a re-closure within this many days counts as a quick repeat


def _w(terms):
    """Whole-word alternation; a leading Hebrew prefix letter (ו/ב/ל/ה/מ/ש/כ)
    is allowed, a term ending in '*' is a stem (open on the right)."""
    parts = []
    for t in terms:
        stem = t.endswith("*")
        t = re.escape(t.rstrip("*"))
        parts.append(t if stem else t + r"(?![֐-׿])")
    return re.compile(r"(?<![֐-׿])(?:[ובלהמשכ]{0,2})(?:" + "|".join(parts) + ")")


# Ordered: first match wins.
KINDS = [
    ("בית פרטי", _w(["בית פרטי", "בתים פרטיים", "בית מגורים פרטי", "בית קרקע",
                     "צמוד קרקע", "וילה", "משפחת", "משפ'", "דו משפחתי", "בית דירות"])),
    ("מבני ציבור וחינוך", _w(['בי"ס', 'ביה"ס', "בית ספר", "בית הספר", "גן ילדים", "גני ילדים",
                              "בית חולים", 'בי"ח', "מעון*", "מרכז קהילתי", "אולם ספורט",
                              'מתנ"ס', "בית כנסת", "מסגד", "כנסי*", "קמפוס", "אוניברסיט*",
                              "מכללה", "ישיבה", "בסיס", "משרד הביטחון", "עירי*", "מועצה",
                              "ספרי*", "מרכז רפואי", "מרפאה", "שדה תעופה", "סטודנטים",
                              "כיתות", "מגרש ספורט"])),
    ("תשתיות וכבישים", _w(["כביש*", "ביוב", "צנרת", "מחלף", "גשר", "מנהר*", "מינהור", "רכבת",
                           "מסילת", "מסילה", "סלילה", "תשתי*", "ניקוז", "קו", "קווי", "סיב",
                           'נת"צ', "תחנת שאיבה", "חשמל", "תחנת משנה", "מים", "הנתיבים",
                           "מקטע", "פיר", "חציב*", "עבודות עפר", "פיתוח"])),
    ("תעשייה, מסחר ותעסוקה", _w(["מפעל*", "מחסן*", 'מרלו"ג', "מרלוג", "לוגיסט*", "תעשי*",
                                 "מסחר*", "קניון", "מלון", "משרדים", "בית אריזה", "חנות",
                                 "סופר", "מרקט", 'בע"מ', "חקלאי*", "רפת", "לול", "מכון",
                                 "קירור", "מחצב*", "סולארי", "סולאר", "תחנת דלק", "מוסך",
                                 "אולם אירועים", "ממגורה", "חוות", "סככה"])),
    ('שיפוץ, תוספת ותמ"א', _w(["שיפוץ*", "תוספת", "הוספת", 'תמ"א', "תמא", "הרחבת", "איטום",
                               "חיזוק", "חזית*", "הריס*", "פירוק", "גג", "גגות", "פרגולה"])),
    ("מגורים ופרויקטי בנייה", _w(["מגורים", 'יח"ד', "דירות", "בניין", "בנין", "בניינים",
                                  "בנייני", "בינייני", "בניני", "מגדל", "מגדלי", "פרויקט",
                                  "פרוייקט", "מתחם", "מגרש", "מגרשים", "גוש", "שכונ*",
                                  "רובע", "מחיר למשתכן", "דירה"])),
]

# Spellings in site names → the table's canonical locality name.
CITY_ALIASES = {
    "תל אביב": "תל-אביב", "תל אביב יפו": "תל-אביב", 'ת"א': "תל-אביב", 'ת"א יפו': "תל-אביב",
    "יפו": "תל-אביב", 'ראשל"צ': "ראשון לציון", 'פ"ת': "פתח תקוה", "פתח תקווה": "פתח תקוה",
    'כ"ס': "כפר סבא", 'ב"ש': "באר שבע", "נצרת עילית": "נוף הגליל", "פרדס חנה": "פרדס חנה-כרכור",
    "כרכור": "פרדס חנה-כרכור", "מעלות": "מעלות-תרשיחא", "טירת כרמל": "טירת הכרמל",
    "יוקנעם": "יקנעם עילית", "יוקנעם עילית": "יקנעם עילית", "גני תיקווה": "גני תקווה",
}
# Localities missing from the table, with their district.
EXTRA_TOWNS = {"בנימינה": "חיפה", "כפר יסיף": "חיפה", "בוקעאתא": "חיפה"}
# Locality names that are also everyday words / street names in site names.
CITY_STOP = {"רחוב", "מגדל", "כרמל", "רמות", "אזור", "מעון", "יובל", "דקל", "גזית", "ספיר",
             "שפיר", "עלי", "שמיר", "עידן", "אייל", "גשר", "ברק", "דן", "נטע", "גפן", "שחר",
             "מגן", "ארז", "חבר", "עזר", "יעל", "מתן", "להב", "שני", "זמר", "יהל", "עדי", "מטע",
             "מסד", "שקף", "חדיד", "נוה", "אורות", "תקומה", "אמונים", "הדר", "נופים", "עומר",
             "שדה", "גבע"}
CITY_DISPLAY = {"תל-אביב": "תל אביב-יפו"}
# Ministry-of-Labour locality → district table (dataset 3768866d "איתור מחוז לפי
# יישוב", snapshot 2026-10). Used only to recognise the locality in the free-text
# site name; a site whose name matches nothing lands in UNKNOWN_CITY.
TOWNS = {
    "באר שבע": (
        ".א.ת. פארק ת.מ.ד|א סייד|א. ת. מישור רותם|א.ת. מפעלי כנות|אבו ג'ווייעד|אבו סריחאן|"
        "אבו עבדון|אבו עמאר|אבו עמרה|אבו רוקייק|אבו תלול|אבן שמואל|אבשלום|אוהד|"
        "אום כף אום בטין|אופקים|אור הנר|אורות|אורים|אחוזם|אטרש|איבים|אילות|אילת|איתן|"
        "אל-עזי|אלומה|אלי סיני|אליאב|אליפז|אסד|אעצם|אפא. ת. מחסום ארז|אפיניש|ארז|אשבול|"
        "אשל הנשיא|אשלים|אשקלון|באר אורה|באר גנים|באר מילכה|באר שבע|בארי|בדולח|בטחה|"
        "בית הגדי|בית קמה|בית שקמה|בני נצרים|בני עצמון|ברור חיל|ברוש|בת הדר|בת חצור|"
        "ג'נאביב|גבולות|גבים|גבעולים|גבעות בר|גבעתי|גברעם|גדיד|גיאה|גילת|גן אור|גני טל|"
        "גרופית|דבירה|דוגית|דורות|דימונה|דקל|דריג'את|הודיה|הוואשלה|הוזייל|הר עמשא|ורדון|"
        "זבארגה|זבדיאל|זוהר|זיקים|זמרת|זרועה|זרחיה|חולית|חורה|חלץ|חצב|חצבה|חצור-אשדוד|"
        "חצרים|טללים|יבול|יד מרדכי|יד נתן|יהל|יושיביה|יטבתה|יכיני|ים המלח בתי מלון|ינון|"
        "יעלון|ירוחם|ישובי חבל מעון|ישע|יתד|כוכב מיכאל|כחלה|כיסופים|כמהין|כסיפה|כפר אחים|"
        "כפר דרום|כפר הרי\"ף|כפר ורבורג|כפר מימון|כפר מנחם|כפר סילבר|כפר עזה|כרם שלום|"
        "כרמיה|כרמים|להב|להבים|לוטן|לכיש|לקיה|מ.א. אשכול|מ.א. באר טוביה|מ.א. בני שמעון|"
        "מ.א. חבל אילות|מ.א. חוף אשקלון|מ.א. חוף עזה|מ.א. יואב|מ.א. לכיש|מ.א. מרחבים|"
        "מ.א. משוש|מ.א. ערבה תיכונה|מ.א. רמת נגב|מ.א. שדות נגב|מ.א. שוקת|מ.א. שער הנגב|"
        "מ.א. שפיר|מ.א. תמר|מ.מ.ת. רמת חובב|מבועים|מבטחים|מבקיעים|מגן|מדרשת בן גוריון|"
        "מולדה|מורג|מחנה טלי|מחנה יתיר|מיתר|מכחול|מלילות|מנוחה|מסלול|מסעודין אל-עזאזמה|"
        "מעגלים|מפלסים|מפעלי אבשלום|מפעלי ים המלח|מפעלי כנות|מפעלי מעון|מפעלי צומת מלאכי|"
        "מפעלי צין - ערבה|מפעלי רותם|מצפה רמון|מרחב עם|מרכז שפירא|משאבי שדה|משואות יצחק|"
        "משמר הנגב|משען|נאות הכיכר|נאות סמדר|נבטים|נגבה|נהורה|נוגה|נוה|נווה דקלים|"
        "נווה זוהר|נווה חריף|נווה מבטח|נועם|נח\"ל אמתי|נח\"ל יתיר|נח\"ל סנסנה|נחל עוז|נחלה|"
        "נטע|ניסנית|ניצני סיני|ניצנים|ניר בנים|ניר ח\"ן|ניר יצחק|ניר ישראל|ניר משה|ניר עוז|"
        "ניר עם|ניר עקיבא|נירים|נצאצרה|נצר חזני|נצרים|נתיב העשרה|נתיבות|סגולה|סדום|סופה|"
        "סייד|סמר|סנסנה|סעד|ספיר|עד הלום|עוזה|עומר|עוצם|עזוז|עזר|עזריקם|עטאוונה|עידן|"
        "עין גדי|עין הבשור|עין השלושה|עין חצבה|עין יהב|עין תמר|עיר אובות|עלומים|עמיעוז|"
        "ערד|ערוגות|ערערה-בנגב|פארן|פאת שדה|פדויים|פטיש|פעמי תש\"ז|פרי גן|צאלים|צוחר|צופר|"
        "צוקים|קאצר א-סר|קבועה|קדמה|קודייראת א-צאנע|קוואעין|קוממיות|קטורה|קטיף|קלחים|"
        "קרית חינוך מרחבים|קרית חינוך עזתה|רביבים|רהט|רווחה|רוחמה|רמת חובב|רנן|רעים|רפיח|"
        "רפיח ים|רתמים|שגב שלום|שדה בוקר|שדה דוד|שדה יואב|שדה משה|שדה ניצן|שדה עוזיהו|"
        "שדה צבי|שדי אברהם|שדרות|שובה|שובל|שומריה|שוקדה|שחר|שחרות|שיבולים|שיטים|שלווה|"
        "שלומית|שליו|שני|שפיר|שקף|שרשרת|שתולים|תאשור|תדהר|תושיה|תימורים|תל שבע|תלמי אליהו|"
        "תלמי ביל\"ו|תלמי יוסף|תלמי יחיאל|תלמי יפה|תלמים|תעשיון חוף יבנה|תעשיון מבצע|"
        "תעשיון ראם|תעשיות ספירים|תפרח|תקומה|תראבין א-צאנע"
    ),
    "חיפה": (
        "א. ת. מילואות|אבו סנאן|אבטליון|אביאל|אביבים|אביטל|אבירים|אבן מנחם|אבני איתן|"
        "אדירים|אדמית|אודם|אוהלן|אום אל - גנם|אום אל-פחם|אום אל-קוטוף|אומן|אור הגנוז|"
        "אור עקיבא|אורטל|אורנים|אושה|אזור תעשייה אכזיב|אזור תעשייה נעמן|אחוזת ברק|אחיהוד|"
        "איבטין|איילת השחר|אילון|אילניה|אכסאל|אל-עריאן|אל-רום|אלומות|אלון הגליל|אלון תבור|"
        "אלוני אבא|אלוני הבשן|אלוני יצחק|אלונים|אלי על|אליפלט|אליקים|אלמגור|אלקוש|אמירים|"
        "אמנון|אניעם|אעבלין|אפיק|אפיקים|אפק|ארבל|אשבל|אשחר|אשרת|אתגר|באקה אל-גרביה|"
        "בוסתן הגליל|בועיינה-נוג'ידאת|בוקעאתה|ביידה|בינימינה|ביר אל-מכסור|ביריה|בית אורן|"
        "בית אלפא|בית ג'ן|בית הלל|בית העמק|בית השיטה|בית זייד|בית זרע|בית חולים פוריה|"
        "בית חנניה|בית יוסף|בית לחם הגלילית|בית צבי|בית קשת|בית רימון|בית שאן|בית שעריים|"
        "בלפוריה|בן עמי|בני יהודה|בסמ\"ה|בסמת טבעון|בענה|בצת|בר יוחאי|ברטעה|ברעם|ברק|ברקאי|"
        "בת שלמה|בתי זיקוק קישון|ג'דיידה-מכר|ג'ולס|ג'סר א-זרקא|ג'ת|גבע|גבע כרמל|גבעת אבני|"
        "גבעת אלה|גבעת יואב|גבעת ניל\"י|גבעת עדה|גבעת עוז|גבת|גדות|גדיש|גדעונה|גונן|גורן|"
        "גורנות הגליל|גזית|גילון|גינוסר|גיניגר|גיתה|גן השומרון|גן נר|גן שמואל|געתון|גשור|"
        "גשר|גשר הזיו|גת בגליל|דאלית אל-כרמל|דאלית אל-כרמל - עספיא|דבורה|דבוריה|דברת|"
        "דוב\"ב|דור|דחי|דיר אל-אסד|דיר חנא|דישון|דליה|דלתון|דמיידה|דן|דפנה|האון|הבונים|"
        "הגושרים|הודיות|הושעיה|הזורע|הזורעים|החותרים|היוגב|הילה|הסוללים|הרדוף|הררית|"
        "זובידאת|זכרון יעקב|זלפה|זרזיר|ח'ואלד|חבר|חג'אג'רה|חד-נס|חדרה|חולתה|חוסן|חוסנייה|"
        "חוקוק|חורפיש|חזון|חיפה|חלוץ|חמאם|חמדיה|חניתה|חנתון|חספין|חפצי-בה|חצור הגלילית|"
        "חצרות יסף|חריש|חרשים|טבריה|טובא - זנגריה|טורעאן|טירת הכרמל|טירת צבי|טל-אל|טמרה|"
        "טפחות|יאנוח-ג'ת|יבנאל|יגור|יובל|יובלים|יודפת|יונתן|יזראעל|יחיעם|יסוד המעלה|יסעור|"
        "יעד|יעל|יערה|יפיע|יפעת|יפתח|יקנעם עילית|יראון|ירדנה|ירכא|כאבול|כאוכב אבו אל-היגא|"
        "כברי|כדורי|כדיתה|כורזים|כחל|כישור|כליל|כלנית|כמאנה|כמון|כנף|כסרא-סמיע|כעביה-טבאש|"
        "כפר ביאליק|כפר בלום|כפר ברוך|כפר גדעון|כפר גלים|כפר גליקסון|כפר גלעדי|כפר החורש|"
        "כפר המכבי|כפר הנוער הדתי|כפר הנשיא|כפר ורדים|כפר זיתים|כפר חיטים|כפר חנניה|"
        "כפר חרוב|כפר יאסיף|כפר יהושע|כפר יחזקאל|כפר כמא|כפר כנא|כפר מנדא|כפר מסריק|"
        "כפר מצר|כפר סאלד|כפר פינס|כפר קיש|כפר קרע|כפר רוזנואלד|כפר רופין|כפר שמאי|"
        "כפר תבור|כרי דשא|כרכום|כרם בן זמרה|כרם מהר\"ל|כרמיאל|לבון|לביא|לבנים|להבות הבשן|"
        "להבות חביבה|לוחמי הגיטאות|לוטם|לימן|לפידות|מ.א. אלונה|מ.א. בקעת בית שאן|"
        "מ.א. גולן|מ.א. הגלבוע|מ.א. הגליל העליון|מ.א. הגליל התחתון|מ.א. זבולון|"
        "מ.א. חוף הכרמל|מ.א. מבואות החרמון|מ.א. מגידו|מ.א. מטה אשר|מ.א. מנשה|"
        "מ.א. מעלה יוסף|מ.א. מרום הגליל|מ.א. משגב|מ.א. נוף הגליל|מ.א. נחל עירון|"
        "מ.א. עמק הירדן|מ.א. עמק יזרעאל|מ.מ.ת. מגדל תפן|מאור|מאיר שפיה|מבוא חמה|"
        "מג'ד אל-כרום|מג'דל שמס|מגאר|מגדים|מגדל|מגדל העמק|מגדל תפן|מגידו|מגל|מגן שאול|"
        "מדרך עוז|מולדת|מועאוויה|מוצמוץ|מוקייבלה|מורן|מורשת|מושיירפה|מזרע|מזרעה|מחנה יבור|"
        "מחניים|מטולה|מי עמי|מיטב|מייסר|מיצר|מירב|מירון|מכמנים|מלאה|מלכיה|מלכישוע|מנוף|"
        "מנות|מנחמיה|מנרה|מנשית זברה|מסד|מסדה|מסילות|מסעדה|מעגן|מעגן מיכאל|מעוז חיים|"
        "מעונה|מעיליא|מעין ברוך|מעין צבי|מעלה גלבוע|מעלה גמלא|מעלה עירון|מעלות-תרשיחא|"
        "מענית|מפעלי גליל עליון|מפעלי גרנות|מפעלי צמח|מפעלי שאן|מצובה|מצפה|מצפה אבי\"ב|"
        "מצפה אילן|מצפה נטופה|מצר|מרגליות|מרום גולן|מרכז אזורי גרנות|מרכז אזורי כדורי|"
        "מרכז אזורי מרום הגליל|מרכז אזורי משגב|מרכז אזורי צמח|מרכז אזורי שח\"ק|מרכז כ\"ח|"
        "משגב עם|משהד|משמר הירדן|משמר העמק|משמרות|מתת|נאות גולן|נאות מרדכי|נאעורה|נהלל|"
        "נהריה|נוב|נוג'ידאת|נווה אבות|נווה אור|נווה אטי\"ב|נווה איתן|נווה זיו|נווה ים|"
        "נוף הגליל|נופית|נורית|נח\"ל נימרוד|נחף|נחשולים|נטועה|נטור|ניין|ניר יפה|ניר עציון|"
        "נמרוד|נס עמים|נצרת|נשר|נתיב השיירה|סאג'ור|סאלם|סאסא|סולם|סח'נין|סלמה|סער|ספסופה|"
        "ע'ג'ר|עבדון|עברון|עדי|עוזייר|עופר|עיילבון|עילוט|עין א-סהלה|עין איילה|עין אל-אסד|"
        "עין גב|עין דור|עין הוד|עין המפרץ|עין הנצי\"ב|עין העמק|עין השופט|עין זיוון|עין חוד|"
        "עין יעקב|עין כרמל|עין מאהל|עין עירון|עין קנייא|עין שמר|עכו|עלמה|עמוקה|עמיעד|"
        "עמיקם|עמיר|עמקה|עספיא|עפולה|עראבה|עראמשה|ערב אל נעים|ערערה|עתלית|"
        "פוריה - כפר עבודה|פוריה - נווה עובד|פוריה עילית|פוריידיס|פלך|פסוטה|פקיעין חדשה|"
        "פרדס חנה-כרכור|פרוד|פרזון|צביה|צבעון|צוריאל|צורית|ציפורי|צנדלה|צפת|צרופה|"
        "קדמת צבי|קדרים|קורנית|קיסריה|קלע|קציר|קצרין|קריית שמואל|קרית אתא|קרית ביאליק|"
        "קרית חיים|קרית טבעון|קרית ים|קרית מוצקין|קרית שמונה|קשת|ראמה|ראס אל-עין|ראס עלי|"
        "ראש הנקרה|ראש פינה|רביד|רגבה|רגבים|רוויה|רומאנה|רומת הייב|ריחאניה|ריינה|רכסים|"
        "רם-און|רמות|רמות מנשה|רמות נפתלי|רמת דוד|רמת השופט|רמת טראמפ|רמת יוחנן|רמת ישי|"
        "רמת מגשימים|רמת צבי|רקפת|רשפים|שאר ישוב|שבי ציון|שגב|שדה אילן|שדה אליהו|"
        "שדה אליעזר|שדה יעקב|שדה יצחק|שדה נחום|שדה נחמיה|שדות ים|שדי תרומות|שדמות דבורה|"
        "שומרה|שורשים|שזור|שיבלי|שיח' דנון|שכניה|שלוחות|שלומי|שמיר|שמרת|שמשית|שניר|שעב|"
        "שעורים|שעל|שער הגולן|שער העמקים|שער מנשה|שפר|שפרעם|שרונה|שריד|שתולה|תובל|תל חי|"
        "תל יוסף|תל עדשים|תל קציר|תל תאומים|תלמי אלעזר|תמרת|תעשיון בר-לב|"
        "תעשיון גליל תחתון|תעשיון דלתון|תרדיון"
    ),
    "ירושלים": (
        "אבו גוש|אבו דיס|אביגדור|אביעזר|אבן ספיר|אדורה|אדרת|אורה|אחווה|איתנים|אלבירה|"
        "אלון שבות|אלחדר|אלמוג|אלעזר|אלראם|אמונים|אמציה|אספר|אפרתה|ארגמן|אשדוד|אשכולות|"
        "אשתאול|באר טוביה|ביצרון|בית איכסא|בית אל|בית אריה|בית ג'אלא|בית גוברין|בית הערבה|"
        "בית זית|בית חורון|בית חנינה|בית מאיר|בית ניר|בית נקופה|בית עזרא|בית ענאן|בית רבן|"
        "בית שמש|ביתר עילית|בני דקלים|בני דרום|בני עייש|בני ראם|בקוע|בקעות|בר גיורא|ברכיה|"
        "בת עין|בתיר|גבע בנימין|גבעון החדשה|גבעת זאב|גבעת יערים|גבעת ישעיהו|גבעת עדן|"
        "גבעת שמש|גיזו|גיתית|גלאון|גלגל|גני מודיעין|גפן|גרמי קטיף|דולב|דיר ראפאת|הר אדר|"
        "הר גילה|הראל|ורד יריחו|זכריה|זנוח|חברון|חגי|חלמיש|חמרה|חשמונאים|טל שחר|טלמון|טנא|"
        "יד בנימין|יד השמונה|ידידה|ייט\"ב|יפית|ירושלים|ישעי|כוכב השחר|כוכב יעקב|כנות|כסלון|"
        "כפר אדומים|כפר אוריה|כפר זוהרים|כפר עציון|כפר עקב|כרמי צור|כרמל|לוזית|"
        "מ.א. גוש עציון|מ.א. הר חברון|מ.א. מגילות|מ.א. מטה בנימין|מ.א. מטה יהודה|"
        "מ.א. ערבות הירדן|מבוא ביתר|מבוא חורון|מבשרת ציון|מגדל עוז|מודיעין|מודיעין עילית|"
        "מוצא|מוצא עילית|מחולה|מחסיה|מטע|מכורה|מנורה|מסילת ציון|מעון|מעלה אדומים|"
        "מעלה אפרים|מעלה החמישה|מעלה לבונה|מעלה מכמש|מעלה עמוס|מפעלי נחם הר טוב|"
        "מצדות יהודה|מצפה יריחו|מצפה שלם|משואה|מתתיהו|נגוהות|נווה אילן|נווה דניאל|"
        "נווה מיכאל|נווה שלום|נוקדים|נח\"ל אבנת|נח\"ל אלישע|נח\"ל גבעות|נח\"ל חמדת|"
        "נח\"ל משכיות|נח\"ל עין חגלה|נח\"ל רותם|נחושה|נחליאל|נחם|נחשון|נטף|ניל\"י|ניצן|נירן|"
        "נס הרים|נעלה|נעמי|נתיב הגדוד|נתיב הל\"ה|סוסיה|עגור|עופרה|עופרים|עטרת|"
        "עין כרם - ביס חקלאי|עין נקובא|עין צורים|עין ראפה|עלמון|עמינדב|ענאתא|עתניאל|"
        "פני חבר|פסגות|פצאל|צובה|צור הדסה|צלפון|צפרירים|צרעה|קבוצת יבנה|קדר|קליה|קלנדיה|"
        "קרית ארבע|קרית גת|קרית יערים|קרית מלאכי|קרית ענבים|ראש צורים|רבדים|רועי|רימונים|"
        "רמאללה|רמת רזיאל|רמת רחל|רנתיס|שדות מיכה|שדמות מחולה|שואבה|שוקבא|שורש|שילה|שמעה|"
        "תומר|תורמוס עייא|תירוש|תל ציון|תלם|תעוז|תקוע|תרום|תרקומיא"
    ),
    "תל אביב": (
        "אביחיל|אבן יהודה|אבני חפץ|אודים|אומץ|אור יהודה|אורנית|אזור|אחיטוב|אחיסמך|אחיעזר|"
        "אייל|אירוס|איתמר|אלון מורה|אליכין|אלישיב|אלישמע|אלעד|אלפי מנשה|אלקנה|אפעל סמינר|"
        "אריאל|ארסוף|באר יעקב|בארות יצחק|בארותיים|בורגתה|בחן|בית אלעזרי|בית ברל|"
        "בית גמליאל|בית דגן|בית הלוי|בית חלקיה|בית חנן|בית חרות|בית חשמונאי|בית יהושע|"
        "בית ינאי|בית יצחק-שער חפר|בית נחמיה|בית עובד|בית עוזיאל|בית עריף|ביתן אהרון|"
        "בן זכאי|בני ברק|בני דרור|בני עטרות|בני ציון|בניה|בצרה|ברוכין|ברכה|ברקן|ברקת|"
        "בת חן|בת חפר|בת ים|ג'לג'וליה|גאולי תימן|גאולים|גאליה|גבעת ברנר|גבעת השלושה|"
        "גבעת ח\"ן|גבעת כ\"ח|גבעת שמואל|גבעת שפירא|גבעתיים|גדרה|גזר|גיבתון|גינתון|גליל ים|"
        "גמזו|גן הדרום|גן חיים|גן יאשיה|גן יבנה|גן שורק|גן שלמה|גנות|גנות הדר|גני הדר|"
        "גני יהודה|גני יוחנן|גני עם|גני תקווה|גנים|געש|גת רימון|הדר עם|הוד השרון|המעפיל|"
        "המרכז למחקר גרעיני נחל שורק|העוגן|הרצליה|זיתן|זמר|חבצלת השרון|חגור|חדיד|חוגלה|"
        "חולדה|חולון|חומש|חופית|חורשים|חיבת ציון|חיננית|חמד|חניאל|חפץ חיים|חצר בארותיים|"
        "חצרות חולדה|חצרות חפר|חצרות כ\"ח|חרב לאת|חרוצים|חרות|חרמש|טייבה|טירה|טירת יהודה|"
        "יבנה|יגל|יד חנה|יד רמב\"ם|ידידיה|יהוד|ינוב|יסודות|יעף|יצהר|יציץ|יקום|יקיר|ירחיב|"
        "ירקונה|ישרש|כדים|כוכב יאיר|כפר אביב|כפר אז\"ר|כפר ביל\"ו|כפר בן נון|כפר ברא|"
        "כפר דניאל|כפר הנגיד|כפר הס|כפר הרא\"ה|כפר ויתקין|כפר חב\"ד|כפר חיים|כפר טרומן|"
        "כפר יבנה|כפר יונה|כפר יעבץ|כפר מונש|כפר מל\"ל|כפר מרדכי|כפר נטר|כפר סבא|"
        "כפר סירקין|כפר עבודה|כפר קאסם|כפר רות|כפר שמואל|כפר שמריהו|כפר תפוח|כרם בן שמן|"
        "כרמי יוסף|לוד|לפיד|מ.א. אפעל|מ.א. ברנר|מ.א. גדרות|מ.א. גזר|מ.א. גן רוה|"
        "מ.א. דרום השרון|מ.א. חבל יבנה|מ.א. חבל מודיעין|מ.א. חוף השרון|מ.א. לב השרון|"
        "מ.א. נחל שורק|מ.א. עמק חפר|מ.א. עמק לוד|מ.א. שומרון|מבוא דותן|מבוא מודיעים|"
        "מבואות ים|מגדלים|מגשימים|מדרשת רופין|מזור|מזכרת בתיה|מחנה תל-נוף|מישר|מכבים-רעות|"
        "מכמורת|מעברות|מעלה שומרון|מעש|מפעלי ברקן|מפעלי חפר|מצליח|מקווה ישראל|מרכז שוהם|"
        "משגב דב|משמר איילון|משמר דוד|משמר השבעה|משמר השרון|משמרת|מתן|נווה אפרים|"
        "נווה ימין|נווה ירק|נוף איילון|נופים|נופך|נורדיה|נחלים|נחשונים|נטעים|ניצני עוז|"
        "ניר אליהו|ניר גלים|ניר צבי|נירית|נמל תעופה בן גוריון|נס ציונה|נעורים|נען|"
        "נצר סרני|נתניה|סביון|סלעית|סתריה|עדנים|עולש|עזריאל|עזריה|עיזריה|עיינות|עין החורש|"
        "עין ורד|עין שריד|עינת|עלי|עלי זהב|עמנואל|ענב|עץ אפרים|עשרת|"
        "פארק תעשיה חבל מודיעים|פדואל|פדיה|פורת|פלמחים|פרדסיה|פתח תקוה|פתחיה|צופיה|צופין|"
        "צופית|צוקי ים|צור יגאל|צור יצחק|צור משה|צור נתן|צורן|צפריה|קדומים|קדימה-צורן|"
        "קדרון|קלנסווה|קרית אונו|קרית נטפים|קרית עקרון|קרית שלמה|קרני שומרון|ראבא|"
        "ראש העין|ראשון לציון|רבבה|רוג'ייב|רחוב|רחובות|רחלים|ריחן|רינתיה|רמות השבים|"
        "רמות מאיר|רמלה|רמת אפעל|רמת גן|רמת הדר|רמת הכובש|רמת השרון|רמת פנקס|רעננה|רפידא|"
        "רשפון|שא-נור|שבות עם|שבי שומרון|שדה ורבורג|שדי חמד|שדמה|שוהם|שוויכה|שופה|"
        "שושנת העמקים|שילת|שכם|שלומציון|שעלבים|שער אפרים|שער שומרון|שערי אברהם|שערי תקוה|"
        "שפיים|שקד|תיאסיר|תל יצחק|תל מונד|תל-אביב|תלפית|תנובות|תעשיון בנימין|תעשיון חצב|"
        "תעשיון צריפין|תעשיון שח\"ק|תעשיות השרון"
    ),
}


def _norm_place(s):
    s = s.replace("קריית", "קרית").replace("־", "-").replace("״", '"').replace("׳", "'")
    return re.sub(r"\s+", " ", re.sub(r"\s*-\s*", " ", s)).strip()


def _build_city_index():
    district, keys = {}, {}
    for d in sorted(TOWNS):
        for name in TOWNS[d].split("|"):
            district[name] = d
    for name, d in sorted(EXTRA_TOWNS.items()):
        district.setdefault(name, d)
    for name in sorted(district):
        if name not in CITY_STOP:
            keys[_norm_place(name)] = name
    for alias, name in sorted(CITY_ALIASES.items()):
        keys[_norm_place(alias)] = name
    letters = r"[֐-׿A-Za-z0-9\"']"
    alt = "|".join(re.escape(k) for k in sorted(keys, key=lambda k: (-len(k), k)))
    pat = re.compile(r"(?<!" + letters + r")(" + alt + r")(?!" + letters + r")")
    return pat, keys, district


CITY_PAT, CITY_KEYS, CITY_DISTRICT = _build_city_index()


def city_of(name):
    """Rightmost (then longest) locality mentioned in the site name."""
    s = _norm_place(name)
    best, pos = None, 0
    while True:
        m = CITY_PAT.search(s, pos)
        if not m:
            break
        key = (m.end(), len(m.group(1)))
        if best is None or key > best[0]:
            best = (key, m.group(1))
        pos = m.start() + 1
    return CITY_KEYS[best[1]] if best else ""


def kind_of(name):
    for label, rx in KINDS:
        if rx.search(name):
            return label
    return ADDRESS_ONLY


def exec_type(name):
    if PRIVATE_RE.search(name):
        return EXEC_TYPES[1]
    if CORPORATE_RE.search(name):
        return EXEC_TYPES[0]
    return EXEC_TYPES[2]


def exec_key(name):
    """Grouping key for one company across spellings."""
    s = re.sub(r"בע['\"״]{1,2}[מם]|בעמ", 'בע"מ', name)
    s = s.replace("בנייה", "בניה").replace("בניין", "בנין")
    return re.sub(r"[\s.,\-–]+", " ", s).strip()


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x):
    return f"{x * 100:.0f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def d_dot(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def _prepare(df):
    raw = pd.DataFrame({
        "site": df["workName"].str.strip(),
        "executor": df["executorName"].str.strip().map(lambda s: re.sub(r"\s+", " ", s)),
        "d": pd.to_datetime(df["fromDate"].str.strip(), format="%d/%m/%Y", errors="coerce"),
    })
    raw = raw[raw["d"].notna() & ((raw["site"] != "") | (raw["executor"] != ""))]
    n_raw = len(raw)
    out = raw.drop_duplicates(["site", "executor", "d"]).copy()
    out["city"] = out["site"].map(city_of)
    out["district"] = out["city"].map(lambda c: CITY_DISTRICT.get(c, UNKNOWN_CITY) if c else UNKNOWN_CITY)
    out["kind"] = out["site"].map(kind_of)
    out["etype"] = out["executor"].map(exec_type)
    out["ekey"] = out["executor"].map(exec_key)
    out["site_key"] = out["site"].map(_norm_place)
    out = out.sort_values(["d", "site", "executor"], kind="stable").reset_index(drop=True)
    return out, n_raw - len(out)


def _top(series, n):
    counts = series.value_counts()
    return counts.sort_index().sort_values(ascending=False, kind="stable").head(n)


def _city_label(c):
    return CITY_DISPLAY.get(c, c)


# ---------------------------------------------------------------- insights

def insight_trend(t12, p12, last):
    if p12 < 10:
        return None
    ch = (t12 - p12) / p12
    if abs(ch) < TREND_GAP:
        return (f"ב-12 החודשים שעד {d_he(last)} נסגרו {_int(t12)} אתרי בנייה, לעומת "
                f"{_int(p12)} ב-12 החודשים שלפניהם — שינוי של פחות מ-{TREND_GAP * 100:.0f}%.")
    word = "עלייה" if ch > 0 else "ירידה"
    return (f"ב-12 החודשים שעד {d_he(last)} נסגרו {_int(t12)} אתרי בנייה — {word} של "
            f"{abs(ch) * 100:.0f}% לעומת 12 החודשים שלפניהם ({_int(p12)}).")


def insight_peak_year(yearly, full_years, last_year, last_partial):
    full = yearly[yearly.index.isin(full_years)]
    if len(full) < 3:
        return None
    y = int(full.sort_index().idxmax())
    lo = int(full.sort_index().idxmin())
    tail = (f"; {last_year} חלקית — {_int(yearly.get(last_year, 0))} סגירות עד כה"
            if last_partial else "")
    return (f"השנה המלאה עם מספר הסגירות הגבוה ביותר היא {y} ({_int(full[y])}), "
            f"והנמוכה ביותר {lo} ({_int(full[lo])}){tail}.")


def insight_exec_type(df):
    n = len(df)
    if n < MIN_FOR_SHARE:
        return None
    vc = df["etype"].value_counts()
    corp, priv = int(vc.get(EXEC_TYPES[0], 0)), int(vc.get(EXEC_TYPES[1], 0))
    other = n - corp - priv
    return (f"{_pct(corp / n)} מהסגירות ({_int(corp)}) היו באתרים שמבצע בהם חברה או תאגיד; "
            f"{_int(priv)} סגירות ({_pct(priv / n)}) באתרים של בעלי היתר פרטיים, "
            f"ו-{_int(other)} אצל מבצעים ללא סימון תאגיד.")


def insight_top_exec(ex):
    if not ex["names"] or ex["values"][0] < 3:
        return None
    top = ex["values"][0]
    leaders = [n for n, v in zip(ex["names"], ex["values"]) if v == top]
    if len(leaders) > 3:
        return None
    if len(leaders) == 1:
        nxt = [f"{n} ({_int(v)})" for n, v in zip(ex["names"][1:3], ex["values"][1:3])]
        return (f"החברה עם מספר האתרים שנסגרו הגבוה ביותר: {leaders[0]} ({_int(top)} סגירות)"
                + (f", ואחריה {', '.join(nxt)}." if nxt else "."))
    return (f"בראש החברות שאתריהן נסגרו: {' ו'.join(leaders)} — {_int(top)} סגירות לכל אחת.")


def insight_city(df):
    known = df[df["city"] != ""]
    if len(known) < MIN_FOR_SHARE:
        return None
    top = _top(known["city"], 3)
    share = top.iloc[0] / len(known)
    if share < 0.05:
        return None
    rest = ", ".join(f"{_city_label(c)} ({_int(v)})" for c, v in top.iloc[1:].items())
    return (f"{_city_label(top.index[0])} מובילה עם {_int(top.iloc[0])} סגירות "
            f"({_pct(share)} מהסגירות שבהן זוהה היישוב)" + (f", ואחריה {rest}." if rest else ".")
            + f" היישוב זוהה אוטומטית מתוך שם האתר ב-{_pct(len(known) / len(df))} מהסגירות.")


def insight_weekday(wd_counts, n):
    if n < MIN_FOR_SHARE:
        return None
    weekend = int(wd_counts.get(4, 0) + wd_counts.get(5, 0))
    lead = max(WEEKDAYS, key=lambda w: (int(wd_counts.get(w[0], 0)), -WEEKDAYS.index(w)))
    return (f"רוב הסגירות נעשות בימי חול: {_pct((n - weekend) / n)} בימים ראשון עד חמישי, "
            f"והיום העמוס ביותר הוא יום {lead[1]} ({_int(wd_counts.get(lead[0], 0))} סגירות); "
            f"בשישי ובשבת יחד — {_int(weekend)}.")


def insight_kind(kinds, n):
    spec = kinds.drop(ADDRESS_ONLY, errors="ignore")
    if spec.empty or n < MIN_FOR_SHARE:
        return None
    unk = int(kinds.get(ADDRESS_ONLY, 0))
    priv = int(kinds.get("בית פרטי", 0))
    lead = spec.index[0]
    tail = (f"; בתים פרטיים — {_int(priv)} סגירות ({_pct(priv / n)})"
            if lead != "בית פרטי" and priv > 0 else "")
    return (f"לפי מילות המפתח בשם האתר, הסוג הנפוץ ביותר הוא {lead} — {_int(spec.iloc[0])} "
            f"סגירות ({_pct(spec.iloc[0] / n)}){tail}. ב-{_pct(unk / n)} מהסגירות שם האתר "
            f"הוא כתובת בלבד ולא סווג.")


def insight_repeat(rep_sites, rep_closures, quick, gap_days):
    if rep_sites < 3:
        return None
    q = (f"; ב-{_int(quick)} מהם הסגירה החוזרת באה בתוך {gap_days} יום"
         if quick > 0 else "")
    return (f"{_int(rep_sites)} אתרים נסגרו יותר מפעם אחת, ביחד {_int(rep_closures)} סגירות{q}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df, n_dupes = _prepare(frames["closures"])
    n = len(df)
    first, last = df["d"].min(), df["d"].max()

    # Years; first/last partial when the data starts after January / ends before December.
    yearly = df.groupby(df["d"].dt.year).size().sort_index()
    years = [int(y) for y in yearly.index]
    first_partial = first.month > 1 or first.day > 7
    last_partial = last.month < 12
    full_years = [y for y in years
                  if not (y == first.year and first_partial) and not (y == last.year and last_partial)]
    year_labels = [f"{y} (חלקית)" if (y == first.year and first_partial) or
                   (y == last.year and last_partial) else str(y) for y in years]

    # Monthly series with a 12-month moving average.
    per = df["d"].dt.to_period("M")
    rng = pd.period_range(per.min(), per.max(), freq="M")
    monthly = per.value_counts().reindex(rng, fill_value=0)
    ma = monthly.rolling(12, min_periods=12).mean()
    mchart = {"x": [f"{MONTHS_SHORT[p.month - 1]} {p.year}" for p in rng],
              "y": [int(v) for v in monthly],
              "ma": [None if pd.isna(v) else round(float(v), 1) for v in ma]}
    busiest = monthly.sort_index().sort_values(ascending=False, kind="stable")
    peak_month = busiest.index[0]

    # Month × year heatmap.
    hm_cells = []
    counts_ym = df.groupby([df["d"].dt.year, df["d"].dt.month]).size()
    for yi, y in enumerate(years):
        for m in range(1, 13):
            p = pd.Period(year=y, month=m, freq="M")
            if p < rng[0] or p > rng[-1]:
                continue
            hm_cells.append([m - 1, yi, int(counts_ym.get((y, m), 0))])
    heat = {"years": [str(y) for y in years], "months": MONTHS_SHORT, "cells": hm_cells,
            "max": max([c[2] for c in hm_cells] + [1])}
    by_cal_month = df.groupby(df["d"].dt.month).size().reindex(range(1, 13), fill_value=0)

    # Trailing 12 months vs the 12 before, ending at the latest closure.
    t12 = int((df["d"] > last - pd.Timedelta(days=365)).sum())
    p12 = int(((df["d"] <= last - pd.Timedelta(days=365)) &
               (df["d"] > last - pd.Timedelta(days=730))).sum())
    span_ok = (last - first).days >= 730

    # Weekday.
    wd_counts = df["d"].dt.dayofweek.value_counts()
    weekday = {"names": [w[1] for w in WEEKDAYS],
               "values": [int(wd_counts.get(w[0], 0)) for w in WEEKDAYS]}

    # Executor type overall and by year.
    et_year = {t: [int(((df["d"].dt.year == y) & (df["etype"] == t)).sum()) for y in years]
               for t in EXEC_TYPES}
    et_share = {t: [round(v / yearly[y] * 100, 1) if yearly[y] else 0
                    for v, y in zip(et_year[t], years)] for t in EXEC_TYPES}

    # Companies (corporate only), grouped across spellings.
    corp = df[df["etype"] == EXEC_TYPES[0]]
    spell = corp.groupby(["ekey", "executor"]).size().reset_index(name="c")
    spell = spell.sort_values(["ekey", "c", "executor"], ascending=[True, False, True])
    disp = spell.drop_duplicates("ekey").set_index("ekey")["executor"]
    agg = corp.groupby("ekey").agg(c=("d", "size"), last=("d", "max"))
    agg["name"] = disp.reindex(agg.index)
    agg = agg.sort_values(["c", "name"], ascending=[False, True], kind="stable")
    ex_top = agg[agg["c"] >= 2].head(TOP_EXEC)
    executors = {"names": list(ex_top["name"]), "values": [int(v) for v in ex_top["c"]],
                 "last": [d_dot(v) for v in ex_top["last"]]}
    n_companies = int(agg.shape[0])
    multi_companies = int((agg["c"] >= 2).sum())

    # Localities and districts.
    known = df[df["city"] != ""]
    cities = _top(known["city"], TOP_CITIES)
    city_chart = {"names": [_city_label(c) for c in cities.index], "values": [int(v) for v in cities]}
    dist_order = sorted(TOWNS) + [UNKNOWN_CITY]
    dist_counts = df["district"].value_counts().reindex(dist_order, fill_value=0)
    dist_known = dist_counts.drop(UNKNOWN_CITY)
    dist_known = dist_known.sort_index().sort_values(ascending=False, kind="stable")
    districts = {"names": [f"מחוז {d}" for d in dist_known.index] + [UNKNOWN_CITY],
                 "values": [int(v) for v in dist_known] + [int(dist_counts[UNKNOWN_CITY])]}

    # Project kinds, and kind × executor type.
    kind_order = [k for k, _ in KINDS] + [ADDRESS_ONLY]
    kinds_all = df["kind"].value_counts().reindex(kind_order, fill_value=0)
    kinds_sorted = kinds_all.drop(ADDRESS_ONLY).sort_values(ascending=False, kind="stable")
    kinds_sorted = pd.concat([kinds_sorted, kinds_all[[ADDRESS_ONLY]]])
    kinds = {"names": list(kinds_sorted.index), "values": [int(v) for v in kinds_sorted]}
    kind_exec = {t: [int(((df["kind"] == k) & (df["etype"] == t)).sum()) for k in kinds["names"]]
                 for t in EXEC_TYPES}

    # Repeat closures of the same site (same normalised site name, different dates).
    named = df[df["site_key"] != ""]
    per_site = named.groupby("site_key")["d"].agg(["nunique", "min", "max"])
    rep = per_site[per_site["nunique"] >= 2]
    rep_sites = int(len(rep))
    rep_rows = (named[named["site_key"].isin(rep.index)].drop_duplicates(["site_key", "d"])
                .sort_values(["site_key", "d"], kind="stable"))
    rep_closures = int(len(rep_rows))
    gaps = rep_rows.groupby("site_key")["d"].diff().dt.days
    quick = int(gaps.groupby(rep_rows["site_key"]).min().le(GAP_DAYS).sum())

    rules = [
        ("trend", insight_trend(t12, p12, last) if span_ok else None),
        ("peak_year", insight_peak_year(yearly, full_years, last.year, last_partial)),
        ("exec_type", insight_exec_type(df)),
        ("top_exec", insight_top_exec(executors)),
        ("city", insight_city(df)),
        ("kind", insight_kind(kinds_all.sort_values(ascending=False, kind="stable"), n)),
        ("weekday", insight_weekday(wd_counts, n)),
        ("repeat", insight_repeat(rep_sites, rep_closures, quick, GAP_DAYS)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # KPI tones: more closures in the last 12 months than the 12 before is a
    # caution signal (more sites found unsafe), fewer is good, else neutral.
    if span_ok and p12 >= 10:
        ch = (t12 - p12) / p12
        t12_tone = "warn" if ch >= TREND_GAP else "ok" if ch <= -TREND_GAP else "brand"
    else:
        t12_tone = "brand"
    corp_n = int(len(corp))
    kpis = {
        "total": {"value": n, "display": _int(n), "tone": "brand"},
        "last12": {"value": t12, "display": _int(t12), "tone": t12_tone},
        "companies": {"value": n_companies, "display": _int(n_companies), "tone": "brand"},
        "repeat": {"value": rep_sites, "display": _int(rep_sites),
                   "tone": "info" if rep_sites else "brand"},
    }

    dupe_txt = (f" {_int(n_dupes)} רשומות כפולות (אותו אתר, מבצע ותאריך) נספרו פעם אחת."
                if n_dupes else "")
    labels = {
        "lede": (f"{_int(n)} סגירות של אתרי בנייה בידי מינהל הבטיחות במשרד העבודה, "
                 f"מ-{d_he(first)} עד {d_he(last)}. כל רשומה היא אתר שנסגר, המבצע שלו "
                 f"ותאריך הסגירה.{dupe_txt}"),
        "years_range": f"{first.year}–{last.year}",
        "last12_kpi": f"סגירות ב-12 החודשים שעד {d_dot(last)}",
        "total_kpi": f"אתרים שנסגרו ({first.year}–{last.year})",
        "companies_kpi": f"חברות שאתריהן נסגרו ({_int(multi_companies)} יותר מפעם אחת)",
        "repeat_kpi": "אתרים שנסגרו יותר מפעם אחת",
        "years_note": (("עמודה בהירה היא שנה שהנתונים מכסים רק בחלקה. ") +
                       f"השנה המלאה העמוסה ביותר: "
                       + (f"{int(yearly[full_years].sort_index().idxmax())}." if full_years else "—")),
        "years_aria": f"תרשים עמודות: מספר אתרי הבנייה שנסגרו בכל שנה, {first.year}–{last.year}.",
        "monthly_note": (f"סגירות בכל חודש, וקו ממוצע נע של 12 חודשים. החודש העמוס ביותר: "
                         f"{MONTHS_HE[peak_month.month - 1]} {peak_month.year} "
                         f"({_int(busiest.iloc[0])} סגירות)."),
        "monthly_aria": "תרשים עמודות וקו: סגירות אתרי בנייה לפי חודש, עם ממוצע נע של 12 חודשים.",
        "heat_note": (f"כל תא הוא חודש בשנה; ככל שהצבע כהה יותר נסגרו יותר אתרים. "
                      f"בסיכום כל השנים, החודש העמוס ביותר הוא "
                      f"{MONTHS_HE[int(by_cal_month.sort_index().sort_values(ascending=False, kind='stable').index[0]) - 1]}."),
        "heat_aria": "מפת חום: סגירות אתרי בנייה לפי חודש ושנה.",
        "weekday_note": "באיזה יום בשבוע נסגרו האתרים.",
        "weekday_aria": "תרשים עמודות: סגירות אתרי בנייה לפי יום בשבוע.",
        "etype_note": ("חלוקת הסגירות בכל שנה לפי סוג המבצע. הסיווג אוטומטי לפי שם המבצע: "
                       "חברה או תאגיד (בע\"מ, שותפות, עמותה וכדומה), בעל היתר פרטי, "
                       "או אדם או עסק ללא סימון תאגיד."),
        "etype_aria": "תרשים עמודות מוערמות: שיעור הסגירות לפי סוג המבצע בכל שנה.",
        "exec_note": (f"חברות ותאגידים עם שתי סגירות לפחות, מתוך {_int(n_companies)} חברות "
                      f"שאתריהן נסגרו ({_int(corp_n)} סגירות). מבצעים שהם אנשים פרטיים "
                      f"אינם מדורגים."),
        "exec_aria": f"תרשים עמודות אופקי: {len(executors['names'])} החברות עם מספר האתרים שנסגרו הגבוה ביותר.",
        "city_note": (f"היישוב זוהה אוטומטית מתוך שם האתר ב-{_int(len(known))} מתוך {_int(n)} "
                      f"הסגירות ({_pct(len(known) / n) if n else '—'})."),
        "city_aria": f"תרשים עמודות אופקי: {len(city_chart['names'])} היישובים עם מספר הסגירות הגבוה ביותר.",
        "dist_note": "לפי חלוקת המחוזות של משרד העבודה, על פי היישוב שזוהה בשם האתר.",
        "dist_aria": "תרשים עמודות: סגירות אתרי בנייה לפי מחוז.",
        "kind_note": ("סיווג אוטומטי לפי מילות מפתח בשם האתר; שם שהוא כתובת בלבד אינו מסווג."),
        "kind_aria": "תרשים עמודות אופקי מוערמות: סגירות לפי סוג הפרויקט וסוג המבצע.",
    }

    n_cities = int(known["city"].nunique())
    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} אתרי בנייה שנסגרו בידי מינהל הבטיחות במשרד העבודה, "
                           f"{first.year}–{last.year} — לפי שנה וחודש, יישוב ומחוז, סוג הפרויקט "
                           f"וחברות הבנייה."),
            "dataset_kind": "timeseries",
            "suggested_tags": ["אתרי בנייה", "בטיחות בעבודה", "צווי סגירה", "בנייה", "פיקוח",
                               "משרד העבודה"],
            "related_ids": ["bddf37d6-5300-4179-bc0b-f2577fbc3a30",
                            "c0beab05-9061-4dad-868c-40142260d35f",
                            "053b5233-bf3c-4d43-95ee-44ccf3e99e5f"],
            "temporal_coverage": f"{first.year}/{last.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "years": {"x": [str(y) for y in years], "y": [int(v) for v in yearly],
                      "partial": [lbl != str(y) for lbl, y in zip(year_labels, years)]},
            "monthly": mchart,
            "heat": heat,
            "weekday": weekday,
            "etype": {"years": [str(y) for y in years], "types": EXEC_TYPES,
                      "share": [et_share[t] for t in EXEC_TYPES],
                      "counts": [et_year[t] for t in EXEC_TYPES]},
            "executors": executors,
            "cities": city_chart,
            "districts": districts,
            "kinds": {"names": kinds["names"], "types": EXEC_TYPES,
                      "series": [kind_exec[t] for t in EXEC_TYPES]},
        },
        "tables": {
            "years": [{"name": x, "v": _int(v)} for x, v in zip(year_labels, yearly)],
            "weekday": [{"name": a, "v": _int(b)} for a, b in zip(weekday["names"], weekday["values"])],
            "etype": [{"name": str(y), "c": [_int(et_year[t][i]) for t in EXEC_TYPES]}
                      for i, y in enumerate(years)],
            "executors": [{"name": a, "v": _int(b), "last": c}
                          for a, b, c in zip(executors["names"], executors["values"], executors["last"])],
            "cities": [{"name": a, "v": _int(b)} for a, b in zip(city_chart["names"], city_chart["values"])],
            "districts": [{"name": a, "v": _int(b)} for a, b in zip(districts["names"], districts["values"])],
            "kinds": [{"name": k, "c": [_int(kind_exec[t][i]) for t in EXEC_TYPES]}
                      for i, k in enumerate(kinds["names"])],
        },
        "flags": {"executors": len(executors["names"]) > 0, "cities": len(city_chart["names"]) > 0},
        "insights": insights,
        "labels": labels,
        "meta": {"n_cities": n_cities},
    }
