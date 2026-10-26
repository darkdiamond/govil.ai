"""מוסכים ומכוני רישוי — Ministry of Transport register of licensed garages,
licensing garages and vehicle-testing stations (מכוני רישוי).

One row per (facility, licensed specialty). Facility-level attributes (name,
type, settlement, operator number) repeat on every row of a facility, so the
frame is first reduced to one row per `mispar_mosah`. The register is a
snapshot: facilities appear and disappear between versions, new specialties
and facility types can appear; nothing is a time series.

Geography: the data carries a settlement name only (no coordinates), so
settlements are mapped to the seven ministry districts (plus Judea and
Samaria) through a static gazetteer built from the CBS settlement list. The
gazetteer is geography, not data from another dataset; settlements it does
not know (and blank/unknown values) go to "לא משויך", and the page says how
many.

Naming: facilities and operating companies are businesses and are named.
Operator registry numbers (`rasham_havarot`) are used only to group a chain's
branches — never shown — and only corporate numbers (9 digits, prefix 5) are
grouped, so sole traders' personal ID numbers never form a "chain". Phone,
street address and postcode are not used. Profession managers
(`menahel_miktzoa`) are counted, never named.
"""
import math
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
UNASSIGNED = "לא משויך"
DIST_ORDER = ["תל אביב", "מרכז", "חיפה", "צפון", "ירושלים", "דרום", "יהודה ושומרון"]
TOP_SETTLEMENTS = 15
TOP_SPECIALTIES = 15
TOP_CHAINS = 10
COOC_N = 10
BREADTH_CAP = 9          # "9+" bucket
MIN_DIST_GARAGES = 100   # districts smaller than this are not compared in insights
STATIONS_CAP = 150

# Facility type codes -> group (fallback: any other non-zero code is a licensing garage).
TYPE_GROUP = {"6": "מוסך מורשה", "1": "מכון רישוי"}
GROUP_ORDER = ["מוסך מורשה", "מוסך רישוי", "מכון רישוי", "סוג לא ידוע"]

# Specialty code -> family (labels of the specialties themselves come from the data).
FAMILY_CODES = {
    "מכונאות": "10 15 20 21 22 25 33 140 145 160 206",
    "חשמל, מיזוג ומערכות": "23 30 111 122 142 144 205 207",
    "מרכב, פחחות וצבע": "60 70 80 81 90 100 175 177",
    "צמיגים, בלמים ומתלים": "91 130 135 143 195",
    "דו-גלגלי וטרקטורונים": "150 155 191",
    "חקלאי, צמ״ה ומלגזות": "172 173 190 192 194",
    "רישוי ובדיקות": "170 171 180 181 182 187 188 300 301",
}
FAMILY_OTHER = "אחר"
FAMILY_ORDER = list(FAMILY_CODES) + [FAMILY_OTHER]
CODE_FAMILY = {c: f for f, cs in FAMILY_CODES.items() for c in cs.split()}
EV_CODE, PETROL_CODE, DIESEL_CODE = "23", "10", "20"

# Spellings in this register that the CBS list writes differently, or places
# (industrial zones, councils, neighbourhoods) it lists under another name.
ALIASES = {
    "מישור אדומים": "מעלה אדומים", "עמק חפר": "בת חפר", "מכר": "ג'דיידה-מכר",
    "גדידה": "ג'דיידה-מכר", "פרדס חנה": "פרדס חנה-כרכור", "גבעת עדה": "בנימינה-גבעת עדה",
    "תל חנן": "נשר", "לוד נמל תעופה": "לוד", "צריפין": "באר יעקב", "זלפה": "ערערה",
    "מוסמוס": "ערערה", "סאלם": "ערערה", "ברטעה": "ערערה", "עארה": "ערערה",
    "יאנוח": "יאנוח-ג'ת", "גת בגליל": "יאנוח-ג'ת", "צור יגאל": "כוכב יאיר-צור יגאל",
    "כסרא": "כסרא-סמיע", "מעוז ציון ב": "מבשרת ציון", "תענכ": "עפולה",
    "נווה נאמן": "הוד השרון", "עין קיניא": "עין קניא", "ימא": "זמר", "מסמיה": "קרית מלאכי",
    "תפוח": "כפר תפוח", "עפרה": "בית אל", "מעלה שומרון": "קרני שומרון",
    "בית אריה-עופרים": "בית אריה", "אליעד": "קצרין", "מבואות החרמון": "קרית שמונה",
    "חילף": "קרית טבעון", "חגאגרה": "כעביה-טבאש-חג'אג'רה",
}

GAZETTEER = {
    "דרום": (
        "אבו ג'וויעד שבט|אבו סריחאן שבט|אבו עבדון שבט|אבו עמאר שבט|אבו עמרה שבט|"
        "אבו קורינאת שבט|אבו קרינאת ישוב|אבו רוביעה שבט|אבו רוקיק שבט|אבו תלול|אביגדור|"
        "אבן שמואל|אבשלום|אוהד|אום בטין|אופקים|אור הנר|אורות|אורים|אחווה|אחוזם|אטרש שבט|"
        "איבים|אילות|אילת|איתן|אל סיד|אל-עזי|אלומה|אליאב|אליפז|אמונים|אמציה|אסד שבט|"
        "אעצם שבט|אפיניש שבט|ארז|אשבול|אשדוד|אשל הנשיא|אשלים|אשקלון|באר אורה|באר גנים|"
        "באר טוביה|באר מילכה|באר שבע|בארי|בטחה|ביצרון|ביר הדאג'|בית גוברין|בית הגדי|"
        "בית ניר|בית עזרא|בית קמה|בית שקמה|בני דקלים|בני נצרים|ברור חיל|ברוש|ברכיה|"
        "בת הדר|ג'נאביב שבט|גבולות|גבים|גבעולים|גבעות בר|גבעתי|גברעם|גיאה|גילת|גלאון|"
        "גרופית|גת קיבוץ|דביר|דורות|דימונה|דקל|דריג'את|הודיה|הוואשלה שבט|הוזיל שבט|"
        "הר עמשא|ורדון|זבארגה שבט|זבדיאל|זוהר|זיקים|זמרת|זרועה|זרחיה|חולית|חורה|חלץ|חצב|"
        "חצבה|חצור-אשדוד|חצרים|טללים|יבול|יד מרדכי|יד נתן|יהל|יושיביה|יטבתה|יכיני|ינון|"
        "ירוחם|ישע|יתד|כוכב מיכאל|כחלה|כיסופים|כמהין|כנות|כסיפה|כפר אחים|כפר הרי ף|"
        "כפר ורבורג|כפר מימון|כפר מנחם|כפר סילבר|כפר עזה|כרם שלום|כרמי קטיף|כרמיה|כרמים|"
        "להב|להבים|לוטן|לכיש|לקיה|מבועים|מבטחים|מבקיעים|מגן|מדרשת בן גוריון|מחנה טלי|"
        "מחנה יוכבד|מחנה יפה|מחנה יתיר|מחנה מרים|מיתר|מכחול|מלילות|מנוחה|מסלול|"
        "מסעודין אל-עזאזמה|מעגלים|מפלסים|מצפה רמון|מרחב עם|מרכז שפירא|משאבי שדה|"
        "משואות יצחק|משמר הנגב|משען|נאות הכיכר|נאות סמדר|נבטים|נגבה|נהורה|נוגה|נווה|"
        "נווה זוהר|נווה חריף|נווה מבטח|נועם|נחל עוז|נחלה|נטע|ניצן|ניצן ב'|"
        "ניצנה קהילת חינוך|ניצני סיני|ניצנים|ניר בנים|ניר ח ן|ניר יצחק|ניר ישראל|ניר משה|"
        "ניר עוז|ניר עם|ניר עקיבא|נירים|נצאצרה שבט|נתיב העשרה|נתיבות|סגולה|סופה|סיד שבט|"
        "סמר|סעד|סעוה|ספיר|עוזה|עומר|עוצם|עוקבי בנו עוקבה|עזוז|עזר|עזריקם|עטאוונה שבט|"
        "עידן|עין גדי|עין הבשור|עין השלושה|עין חצבה|עין יהב|עין צורים|עין תמר|עיר אובות|"
        "עלומים|עמיעוז|ערד|ערוגות|ערערה-בנגב|פארן|פדוים|פטיש|פעמי תש ז|פרי גן|צאלים|צוחר|"
        "צופר|צוקים|קבועה שבט|קדמה|קודיראת א-צאנע שבט|קוואעין שבט|קוממיות|קטורה|קלחים|"
        "קצר א-סר|קרית גת|קרית מלאכי|רבדים|רביבים|רהט|רווחה|רוח מדבר|רוחמה|רנן|רעים|"
        "רתמים|שבי דרום|שגב-שלום|שדה בוקר|שדה דוד|שדה יואב|שדה משה|שדה ניצן|שדה עוזיהו|"
        "שדה צבי|שדי אברהם|שדרות|שובה|שובל|שומריה|שוקדה|שחר|שחרות|שיבולים|שיזף|שיטים|"
        "שלווה|שלווה במדבר|שלומית|שני|שפיר|שקף|שרשרת|שתולים|תאשור|תדהר|תושיה|תימורים|"
        "תל שבע|תלמי אליהו|תלמי ביל ו|תלמי יוסף|תלמי יחיאל|תלמי יפה|תלמים|תפרח|תקומה|"
        "תראבין א-צאנע ישוב|תראבין א-צאנע שבט"
    ),
    "חיפה": (
        "אבטין|אביאל|אום אל-פחם|אום אל-קוטוף|אור עקיבא|אורנים|אושה|אל-עריאן|אלוני יצחק|"
        "באקה אל-גרביה|בית אורן|בית חנניה|בית צבי|בנימינה-גבעת עדה|בסמ ה|ברקאי|בת שלמה|"
        "ג'סר א-זרקא|ג'ת|גבע כרמל|גבעת ניל י|גן השומרון|גן שמואל|דאלית אל-כרמל|דור|"
        "הבונים|החותרים|זכרון יעקב|ח'ואלד|חדרה|חיפה|חריש|טירת כרמל|יגור|כפר ביאליק|"
        "כפר גלים|כפר גליקסון|כפר המכבי|כפר הנוער הדתי|כפר חסידים א'|כפר חסידים ב'|"
        "כפר פינס|כפר קרע|כרם מהר ל|להבות חביבה|מאור|מאיר שפיה|מגדים|מגל|מי עמי|מיסר|"
        "מעגן מיכאל|מעין צבי|מעלה עירון|מענית|מצפה אילן|מצר|משמרות|נווה אבות|נווה ים|"
        "נופית|נחשולים|ניר עציון|נשר|עופר|עין אילה|עין הוד|עין חוד|עין כרמל|עין עירון|"
        "עין שמר|עמיקם|עספיא|ערערה|עתלית|פורידיס|פרדס חנה-כרכור|צרופה|קיסריה|קציר|"
        "קרית אתא|קרית ביאליק|קרית טבעון|קרית ים|קרית מוצקין|ראס עלי|רגבים|רכסים|"
        "רמת יוחנן|שדה יצחק|שדות ים|שער העמקים|שער מנשה|תלמי אלעזר"
    ),
    "יהודה ושומרון": (
        "אביגיל|אביה|אבני חפץ|אדורה|אדורים|אובנת|אורנית|אחיה|איבי הנחל|איתמר|אלון|"
        "אלון מורה|אלון שבות|אלמוג|אלעזר|אלפי מנשה|אלקנה|אסיף|אספר|אפרת|ארגמן|אריאל|"
        "אשכולות|בית אל|בית אריה|בית הערבה|בית חוגלה|בית חורון|בית יתיר|ביתר עילית|בקעות|"
        "בר כוכבא|ברוכין|ברוש הבקעה|ברכה|ברקן|בת עין|בתרון|גבע בנימין|גבעון החדשה|גבעות|"
        "גבעות הרואה|גבעת זאב|גודר|גיתית|גלגל|גני מודיעין|גנים|דולב|הר אדר|הר בזק|"
        "הר גילה|ורד יריחו|חברון|חגי|חומש|חיננית|חמדת|חמרה|חרמש|חרשה|חשמונאים|טל מנשה|"
        "טלמון|טנא|יונדב|יט ב|יפית|יצהר|יקיר|כדים|כוכב השחר|כוכב יעקב|כנפי שחר|"
        "כפר אדומים|כפר האורנים|כפר עציון|כפר תפוח|כרם רעים|כרמי עוז|כרמי צור|כרמל|לח י|"
        "לשם|מבוא דותן|מבוא חורון|מבואות יריחו|מגדל עוז|מגדלים|מגרון|מודיעין עילית|מחולה|"
        "מכורה|מלאכי השלום|מעוז|מעון|מעלה אדומים|מעלה אפרים|מעלה לבונה|מעלה מכמש|"
        "מעלה עמוס|מצוקי ארץ|מצפה זיף|מצפה יריחו|מצפה שלם|משואה|משכיות|משמר יהודה|מתתיהו|"
        "נגוהות|נוה צוף|נווה גדיד|נווה דניאל|נופי פרת|נופים|נוקדים|נזר שומרון|נחליאל|"
        "ניל י|נעלה|נעמ ה|נערן|נריה|נתיב הגדוד|סוסיה|סחלב|סלעית|סנסנה|עדי עד|עופרה|עטרת|"
        "עיבל|עין יט ב|עלי|עלי זהב|עלמון|עמיחי|עמנואל|ענב|עשהאל|עתניאל|פדואל|פני חבר|"
        "פני קדם|פסגות|פצאל|פרשים|צופים|קדומים|קדם ערבה|קדר|קליה|קרית ארבע|קרית נטפים|"
        "קרן יער|קרני שומרון|ראש צורים|רבבה|רועי|רותם|רחלים|ריחן|רימונים|שא-נור|שבות רחל|"
        "שבי שומרון|שדמות מחולה|שחרית|שילה|שירה|שמעה|שער שומרון|שקד|תומר|תל ציון|תלם|"
        "תמרה|תקוע"
    ),
    "ירושלים": (
        "אבו גוש|אביעזר|אבן ספיר|אדרת|אורה|איתנים|אשתאול|בית זית|בית מאיר|בית נקופה|"
        "בית שמש|בקוע|בר גיורא|גבעות עדן|גבעת יערים|גבעת ישעיהו|גבעת שמש|גיזו|גפן|"
        "דיר ראפאת|הראל|זכריה|זנוח|טל שחר|יד השמונה|ידידה|ירושלים|ישעי|כסלון|כפר אוריה|"
        "כפר זוהרים|לוזית|מבוא ביתר|מבשרת ציון|מוצא עילית|מחסיה|מטע|מסילת ציון|"
        "מעלה החמישה|נווה אילן|נווה מיכאל|נווה שלום|נחושה|נחם|נחשון|נטף|נס הרים|"
        "נתיב הל ה|עגור|עין כרם-בי ס חקלאי|עין נקובא|עין ראפה|עמינדב|צובה|צור הדסה|צלפון|"
        "צפרירים|צרעה|קרית יערים|קרית יערים מוסד|קרית ענבים|רמת רזיאל|רמת רחל|שדות מיכה|"
        "שואבה|שורש|שריגים לי-און|תירוש|תעוז|תרום"
    ),
    "מרכז": (
        "אביחיל|אבן יהודה|אודים|אומץ|אחיטוב|אחיסמך|אחיעזר|איל|אירוס|אליכין|אלישיב|אלישמע|"
        "אלעד|ארסוף|באר יעקב|בארות יצחק|בארותים|בורגתה|בחן|בית אלעזרי|בית ברל|בית גמליאל|"
        "בית דגן|בית הלוי|בית חירות|בית חלקיה|בית חנן|בית חשמונאי|בית יהושע|בית ינאי|"
        "בית יצחק-שער חפר|בית נחמיה|בית עובד|בית עוזיאל|בית עריף|בית רבן|ביתן אהרן|"
        "בן זכאי|בן שמן כפר נוער|בן שמן מושב|בני דרום|בני דרור|בני עטרות|בני עי ש|"
        "בני ציון|בני ראם|בניה|בצרה|ברקת|בת חן|בת חפר|ג'לג'וליה|גאולי תימן|גאולים|גאליה|"
        "גבעת ברנר|גבעת השלושה|גבעת ח ן|גבעת חים איחוד|גבעת חים מאוחד|גבעת כ ח|"
        "גבעת שמואל|גבעת שפירא|גדרה|גזר|גיבתון|גינתון|גמזו|גן הדרום|גן חים|גן יאשיה|"
        "גן יבנה|גן שורק|גן שלמה|גנות|גנות הדר|גני הדר|גני טל|גני יוחנן|גני עם|גני תקווה|"
        "געש|גת רימון|הדר עם|הוד השרון|המעפיל|העוגן|זיתן|זמר|חבצלת השרון|חגור|חגלה|חדיד|"
        "חולדה|חופית|חורשים|חיבת ציון|חירות|חמד|חניאל|חפץ חים|חרב לאת|חרוצים|טיבה|טירה|"
        "טירת יהודה|יבנה|יגל|יד בנימין|יד חנה|יד רמב ם|יהוד-מונוסון|ינוב|יסודות|יעף|יציץ|"
        "יקום|ירחיב|ירקונה|ישרש|כוכב יאיר-צור יגאל|כפר אביב|כפר ביל ו|כפר בן נון|כפר ברא|"
        "כפר דניאל|כפר הנגיד|כפר הס|כפר הרא ה|כפר ויתקין|כפר חב ד|כפר חים|כפר טרומן|"
        "כפר ידידיה|כפר יונה|כפר יעבץ|כפר מונש|כפר מל ל|כפר מרדכי|כפר נטר|כפר סבא|"
        "כפר סירקין|כפר עבודה|כפר קאסם|כפר רות|כפר שמואל|כרם ביבנה ישיבה|כרם בן שמן|"
        "כרמי יוסף|לוד|לפיד|מבוא מודיעים|מבואות ים|מגשימים|מדרשת רופין|"
        "מודיעין-מכבים-רעות|מזור|מזכרת בתיה|מחנה הילה|מחנה תל נוף|מישר|מכמורת|מעברות|מעש|"
        "מצליח|משגב דב|משמר אילון|משמר דוד|משמר השבעה|משמר השרון|משמרת|מתן|נווה ימין|"
        "נווה ירק|נוף אילון|נופך|נורדיה|נחלים|נחשונים|נטעים|ניצני עוז|ניר אליהו|ניר גלים|"
        "ניר צבי|נירית|נס ציונה|נעורים|נען|נצר חזני|נצר סרני|נתניה|סביון|סתריה|עדנים|"
        "עולש|עזריאל|עזריה|עין החורש|עין ורד|עין שריד|עינות|עינת|עשרת|פדיה|פורת|פלמחים|"
        "פרדסיה|פתח תקווה|פתחיה|צופיה|צופית|צוקי ים|צור יצחק|צור משה|צור נתן|צפריה|"
        "קבוצת יבנה|קדימה-צורן|קדרון|קלנסווה|קרית עקרון|קרית שלמה|ראש העין|ראשון לציון|"
        "רחובות|רינתיה|רמות השבים|רמות מאיר|רמלה|רמת הכובש|רעננה|רשפון|שדה ורבורג|"
        "שדי חמד|שדמה|שוהם|שושנת העמקים|שילת|שעלבים|שער אפרים|שפים|תל יצחק|תל מונד|"
        "תנובות"
    ),
    "צפון": (
        "אבו סנאן|אבטליון|אביבים|אביטל|אבירים|אבן מנחם|אבני איתן|אדירים|אדמית|אודם|אומן|"
        "אור הגנוז|אורטל|אחוזת ברק|אחיהוד|אילון|אילניה|אילת השחר|אכסאל|אל-רום|אלומות|"
        "אלון הגליל|אלוני אבא|אלוני הבשן|אלונים|אלי-עד|אליפלט|אליקים|אלמגור|אלקוש|אמירים|"
        "אמנון|אניעם|אעבלין|אפיק|אפיקים|אפק|ארבל|אשבל|אשדות יעקב איחוד|אשדות יעקב מאוחד|"
        "אשחר|אשרת|אתגר|בוסתן הגליל|בועינה-נוג'ידאת|בוקעאתא|ביר אל-מכסור|ביריה|בית אלפא|"
        "בית ג'ן|בית הלל|בית העמק|בית השיטה|בית זיד|בית זרע|בית יוסף|בית לחם הגלילית|"
        "בית קשת|בית רימון|בית שאן|בית שערים|בלפוריה|בן עמי|בני יהודה|בסמת טבעון|בענה|"
        "בצת|בר יוחאי|ברעם|ברק|ג'דידה-מכר|ג'ולס|ג'ש גוש חלב|גבע|גבעת אבני|גבעת אלה|"
        "גבעת יואב|גבעת עוז|גבת|גדות|גדיש|גדעונה|גונן|גורן|גורנות הגליל|גזית|גילון|"
        "גינוסר|גיניגר|גיתה|גלעד אבן יצחק|גן נר|געתון|גשור|גשר|גשר הזיו|דבורה|דבוריה|"
        "דברת|דגניה א'|דגניה ב'|דוב ב|דחי|דיר אל-אסד|דיר חנא|דישון|דליה|דלתון|דמידה|דן|"
        "דפנה|האון|הגושרים|הודיות|הושעיה|הזורע|הזורעים|היוגב|הילה|הסוללים|הרדוף|הררית|"
        "זרזיר|ח'ואלד שבט|חבר|חד-נס|חוג'יראת ד'הרה|חולתה|חוסן|חוסניה|חוקוק|חורפיש|חזון|"
        "חלוץ|חמאם|חמדיה|חניתה|חנתון|חספין|חפצי-בה|חצור הגלילית|חרשים|טבריה|טובא-זנגריה|"
        "טורעאן|טיבה בעמק|טירת צבי|טל-אל|טמרה|טמרה יזרעאל|טפחות|יאנוח-ג'ת|יבנאל|יובל|"
        "יובלים|יודפת|יונתן|יזרעאל|יחיעם|יסוד המעלה|יסעור|יעד|יעל|יערה|יפיע|יפעת|יפתח|"
        "יקנעם מושבה|יקנעם עילית|יראון|ירדנה|ירכא|כאבול|כאוכב אבו אל-היג'א|כברי|כדורי|"
        "כדיתה|כורזים|כחל|כישור|כליל|כלנית|כמאנה|כמון|כנף|כנרת מושבה|כנרת קבוצה|"
        "כסרא-סמיע|כעביה-טבאש-חג'אג'רה|כפר בלום|כפר ברוך|כפר גדעון|כפר גלעדי|כפר החורש|"
        "כפר הנשיא|כפר ורדים|כפר זיתים|כפר חושן|כפר חיטים|כפר חנניה|כפר חרוב|כפר יאסיף|"
        "כפר יהושע|כפר יחזקאל|כפר כמא|כפר כנא|כפר מנדא|כפר מסריק|כפר מצר|כפר סאלד|"
        "כפר קיש|כפר ראש הנקרה|כפר רוזנואלד זרעית|כפר רופין|כפר שמאי|כפר תבור|כרכום|"
        "כרם בן זמרה|כרמיאל|לבון|לביא|לבנים|להבות הבשן|לוחמי הגיטאות|לוטם|לימן|לפידות|"
        "מבוא חמה|מג'ד אל-כרום|מג'דל שמס|מגאר|מגדל|מגדל העמק|מגידו|מגן שאול|מדרך עוז|"
        "מולדת|מוקיבלה|מורן|מורשת|מזרע|מזרעה|מחנה יהודית|מחנים|מטולה|מיטב|מיטל|מיצר|מירב|"
        "מירון|מכמנים|מלאה|מלכיה|מנוף|מנות|מנחמיה|מנרה|מנשית זבדה|מסד|מסדה|מסילות|מסעדה|"
        "מעגן|מעוז חים|מעונה|מעיליא|מעין ברוך|מעלה גלבוע|מעלה גמלא|מעלות-תרשיחא|מצובה|"
        "מצפה|מצפה אבי ב|מצפה נטופה|מרגליות|מרום גולן|מרחביה מושב|מרחביה קיבוץ|משגב עם|"
        "משהד|משמר הירדן|משמר העמק|מתת|נאות גולן|נאות מרדכי|נאעורה|נהלל|נהריה|נוב|"
        "נווה אור|נווה אטי ב|נווה איתן|נווה זיו|נוף הגליל|נורית|נחף|נטועה|נטור|נין|"
        "ניר דוד תל עמל|ניר יפה|נמרוד|נס עמים|נצרת|נתיב השירה|סאג'ור|סאסא|סואעד חמירה|"
        "סואעד כמאנה שבט|סולם|סח'נין|סלמה|סער|ע'ג'ר|עבדון|עברון|עדי|עוזיר|עילבון|עילוט|"
        "עין אל-אסד|עין גב|עין דור|עין המפרץ|עין הנצי ב|עין העמק|עין השופט|עין זיוון|"
        "עין חרוד איחוד|עין חרוד מאוחד|עין יעקב|עין מאהל|עין קניא|עכו|עלמה|עמוקה|עמיעד|"
        "עמיר|עמקה|עפולה|עצמון שגב|עראבה|עראמשה|ערב אל נעים|פוריה עילית|פוריה-כפר עבודה|"
        "פוריה-נווה עובד|פלך|פסוטה|פקיעין בוקיעה|פקיעין חדשה|פרוד|פרזון|צביה|צבעון|"
        "צוריאל|צורית|ציפורי|צנדלה|צפת|קדמת צבי|קדרים|קורנית|קלע|קצרין|קרית שמונה|קשת|"
        "ראמה|ראס אל-עין|ראש פינה|רביד|רגבה|רוויה|רומאנה|רומת היב|רחוב|ריחאניה|רינה|"
        "רם-און|רמות|רמות מנשה|רמות נפתלי|רמת דוד|רמת הנשיא טראמפ|רמת השופט|רמת ישי|"
        "רמת מגשימים|רמת צבי|רקפת|רשפים|שאר ישוב|שבי ציון|שבלי-אום אל-גנם|שדה אילן|"
        "שדה אליהו|שדה אליעזר|שדה יעקב|שדה נחום|שדה נחמיה|שדי תרומות|שדמות דבורה|שומרה|"
        "שורשים|שזור|שיח' דנון|שכניה|שלוחות|שלומי|שמיר|שמרת|שמשית|שניר|שעב|שעל|שער הגולן|"
        "שפר|שפרעם|שרונה|שריד|שתולה|תובל|תל יוסף|תל עדשים|תל קציר|תל תאומים|תמרת"
    ),
    "תל אביב": (
        "אור יהודה|אזור|בני ברק|בת ים|גבעתים|גליל ים|הרצליה|חולון|כפר שמריהו|מקווה ישראל|"
        "קרית אונו|רמת גן|רמת השרון|תל אביב-יפו"
    ),
}


def norm_place(x):
    x = (x.replace("׳", "'").replace("״", " ").replace('"', " ")
         .replace("*", " ").replace("(", " ").replace(")", " "))
    x = re.sub(r"\s*-\s*", "-", x)
    x = re.sub(r"\s+", " ", x).strip().rstrip(".").strip()
    return x.replace("קריית", "קרית").replace("יי", "י")


PLACE_DISTRICT = {}
for _dist, _names in GAZETTEER.items():
    for _nm in _names.split("|"):
        PLACE_DISTRICT[_nm] = _dist
for _a, _b in ALIASES.items():
    _d = PLACE_DISTRICT.get(norm_place(_b))
    if _d:
        PLACE_DISTRICT.setdefault(norm_place(_a), _d)


def district_of(place):
    return PLACE_DISTRICT.get(norm_place(place), UNASSIGNED) if place else UNASSIGNED


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def pnum(v, digits=1):
    return round(float(v), digits)


def clean_place(p):
    p = re.sub(r"\s+", " ", p).strip().rstrip(".*").strip()
    return p


def fix_parens(s):
    """The register stores some parentheses mirrored (")אי.טי.אי("); restore them."""
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\)([^()]+)[()]", r"(\1)", s)


def _facilities(df):
    d = pd.DataFrame({
        "id": df["mispar_mosah"].str.strip(),
        "name": df["shem_mosah"].map(fix_parens),
        "tcode": df["cod_sug_mosah"].str.strip(),
        "tname": df["sug_mosah"].map(lambda s: re.sub(r"\s+", " ", s).strip()),
        "place": df["yishuv"].map(clean_place),
        "code": df["cod_miktzoa"].str.strip(),
        "spec": df["miktzoa"].map(fix_parens),
        "mgr": df["menahel_miktzoa"].map(lambda s: re.sub(r"\s+", " ", s).strip()),
        "reg": df["rasham_havarot"].str.strip(),
    })
    d = d[d["id"] != ""]
    d["idn"] = pd.to_numeric(d["id"], errors="coerce")
    d = d.sort_values(["idn", "id", "code", "spec", "mgr", "name", "place", "tcode", "tname", "reg"],
                      kind="mergesort").reset_index(drop=True)
    lic = d.drop_duplicates(["id", "code"]).copy()
    fac = d.drop_duplicates("id")[["id", "idn", "name", "tcode", "tname", "place", "reg"]].copy()
    unknown_place = fac["place"].isin(["", "לא ידוע קוד 0"]) | fac["place"].str.startswith("לא ידוע")
    fac.loc[unknown_place, "place"] = ""
    fac["district"] = fac["place"].map(district_of)
    # one display spelling per settlement (most common raw spelling; tie: alphabetical)
    fac["pkey"] = fac["place"].map(norm_place)
    sp_ = fac[fac["place"] != ""].groupby(["pkey", "place"]).size().reset_index(name="k")
    sp_ = sp_.sort_values(["pkey", "k", "place"], ascending=[True, False, True], kind="mergesort")
    disp = dict(zip(sp_.drop_duplicates("pkey")["pkey"], sp_.drop_duplicates("pkey")["place"]))
    fac["place"] = fac["pkey"].map(lambda k: disp.get(k, ""))

    def grp(row):
        if row["tcode"] in TYPE_GROUP:
            return TYPE_GROUP[row["tcode"]]
        if row["tcode"] in ("", "0") or row["tname"].startswith("לא ידוע"):
            return "סוג לא ידוע"
        return "מוסך רישוי"
    fac["group"] = fac.apply(grp, axis=1)
    fac["tname"] = fac["tname"].where(~fac["tname"].str.startswith("לא ידוע"), "סוג לא ידוע")
    lic["family"] = lic["code"].map(lambda c: CODE_FAMILY.get(c, FAMILY_OTHER))
    return d, lic, fac


def _vmax(cells):
    """Colour-scale ceiling: the largest cell rounded up to a multiple of ten."""
    m = max((c[2] for c in cells), default=0)
    return int(min(100, max(10, math.ceil(m / 10) * 10)))


def _spec_labels(lic):
    """Most common label per specialty code (tie: alphabetical)."""
    t = lic.groupby(["code", "spec"]).size().reset_index(name="k")
    t = t.sort_values(["code", "k", "spec"], ascending=[True, False, True], kind="mergesort")
    return dict(zip(t.drop_duplicates("code")["code"], t.drop_duplicates("code")["spec"]))


def compute(frames):
    raw = frames["main"]
    d, lic, fac = _facilities(raw)
    total = len(fac)
    labels_by_code = _spec_labels(lic)
    lic["label"] = lic["code"].map(labels_by_code)
    insights = []

    # ── facility types ────────────────────────────────────────────────
    tcount = fac.groupby("tname").size().reset_index(name="k")
    tcount = tcount.sort_values(["k", "tname"], ascending=[False, True], kind="mergesort")
    types_chart = {"names": tcount["tname"].tolist(), "values": [int(v) for v in tcount["k"]]}
    gcount = fac["group"].value_counts()
    auth = int(gcount.get("מוסך מורשה", 0))
    stations = int(gcount.get("מכון רישוי", 0))
    licg = int(gcount.get("מוסך רישוי", 0))
    if total and auth / total >= 0.5:
        insights.append({"id": "type_mix", "text_he": (
            f"{n(auth)} מתוך {n(total)} המתקנים במאגר ({pct(auth / total * 100)}) הם מוסכים מורשים "
            f"לתיקון ותחזוקה; לצדם {n(licg)} מוסכי רישוי (רכב חדש, ציוד חקלאי, שירות עצמי ועוד) "
            f"ו-{n(stations)} מכוני רישוי שבהם עוברים כלי הרכב את המבחן השנתי.")})

    # ── geography ─────────────────────────────────────────────────────
    present_d = [x for x in DIST_ORDER if (fac["district"] == x).any()]
    extra_d = sorted(set(fac["district"]) - set(DIST_ORDER) - {UNASSIGNED})
    dists = present_d + extra_d
    unassigned = int((fac["district"] == UNASSIGNED).sum())
    groups_present = [g for g in GROUP_ORDER if (fac["group"] == g).any()]
    ct = fac.groupby(["district", "group"]).size()
    dist_tot = fac.groupby("district").size()
    dist_order = sorted(dists, key=lambda x: (-int(dist_tot.get(x, 0)), x))
    districts_chart = {
        "names": dist_order,
        "series": [{"name": g, "data": [int(ct.get((x, g), 0)) for x in dist_order]} for g in groups_present],
    }
    districts_table = [{"name": x, "total": n(dist_tot.get(x, 0)),
                        "auth": n(ct.get((x, "מוסך מורשה"), 0)),
                        "lic": n(ct.get((x, "מוסך רישוי"), 0)),
                        "st": n(ct.get((x, "מכון רישוי"), 0))} for x in dist_order]

    pl = fac[fac["place"] != ""].groupby("place").size().reset_index(name="k")
    pl = pl.sort_values(["k", "place"], ascending=[False, True], kind="mergesort")
    n_places = len(pl)
    top_pl = pl.head(TOP_SETTLEMENTS)
    settlements_chart = {"names": top_pl["place"].tolist(), "values": [int(v) for v in top_pl["k"]]}
    if n_places >= 10 and total:
        top3 = pl.head(3)
        top10 = int(pl.head(10)["k"].sum())
        insights.append({"id": "concentration", "text_he": (
            f"המתקנים פרוסים ב-{n(n_places)} יישובים, אך עשרת הגדולים מרכזים {pct(top10 / total * 100)} "
            f"מהם; בראש: {top3.iloc[0]['place']} ({n(top3.iloc[0]['k'])}), {top3.iloc[1]['place']} "
            f"({n(top3.iloc[1]['k'])}) ו{top3.iloc[2]['place']} ({n(top3.iloc[2]['k'])}).")})

    # ── specialties ───────────────────────────────────────────────────
    sp = lic.groupby("code").size().reset_index(name="k")
    sp["label"] = sp["code"].map(labels_by_code)
    sp = sp.sort_values(["k", "label", "code"], ascending=[False, True, True], kind="mergesort")
    top_sp = sp.head(TOP_SPECIALTIES)
    rest = sp.iloc[TOP_SPECIALTIES:]
    spec_names = top_sp["label"].tolist()
    spec_vals = [int(v) for v in top_sp["k"]]
    if len(rest):
        spec_names.append(f"אחר ({n(len(rest))} תחומים)")
        spec_vals.append(int(rest["k"].sum()))
    specialties_chart = {"names": spec_names, "values": spec_vals}

    # family sunburst
    fam_fac = lic.drop_duplicates(["id", "family"]).groupby("family").size()
    sun = []
    fam_table = []
    for f in FAMILY_ORDER:
        sub = sp[sp["code"].map(lambda c: CODE_FAMILY.get(c, FAMILY_OTHER)) == f]
        if not len(sub):
            continue
        sun.append({"name": f, "children": [{"name": r["label"], "value": int(r["k"])}
                                             for _, r in sub.iterrows()]})
        fam_table.append({"name": f, "garages": n(fam_fac.get(f, 0)), "specs": n(len(sub)),
                          "lic": n(sub["k"].sum())})

    # breadth
    per = lic.groupby("id").size()
    br = per.clip(upper=BREADTH_CAP).value_counts()
    b_x = [str(i) if i < BREADTH_CAP else f"{BREADTH_CAP}+" for i in range(1, BREADTH_CAP + 1)]
    b_y = [int(br.get(i, 0)) for i in range(1, BREADTH_CAP + 1)]
    breadth_chart = {"x": b_x, "y": b_y}
    single = per[per == 1].index
    if total:
        sole = lic[lic["id"].isin(single)].groupby("label").size().reset_index(name="k")
        sole = sole.sort_values(["k", "label"], ascending=[False, True], kind="mergesort")
        if len(sole):
            insights.append({"id": "breadth", "text_he": (
                f"רוב המתקנים רב-תחומיים: {pct((per >= 2).sum() / total * 100)} מורשים ליותר מתחום אחד "
                f"(בממוצע {LRI}{per.mean():.1f}{PDI} תחומים למתקן, ועד {n(per.max())}). מבין {n(len(single))} "
                f"המתקנים בעלי תחום יחיד, הנפוץ הוא {sole.iloc[0]['label']} ({n(sole.iloc[0]['k'])}).")})

    # petrol vs diesel vs EV
    has = {c: set(lic.loc[lic["code"] == c, "id"]) for c in (EV_CODE, PETROL_CODE, DIESEL_CODE)}
    ev_n, pet_n, die_n = (len(has[EV_CODE]), len(has[PETROL_CODE]), len(has[DIESEL_CODE]))
    ev_label = labels_by_code.get(EV_CODE, "")
    if pet_n and ev_n:
        insights.append({"id": "ev", "text_he": (
            f"{n(ev_n)} מתקנים ({pct(ev_n / total * 100)}) מורשים ל{ev_label}, לעומת {n(pet_n)} "
            f"המורשים ל{labels_by_code.get(PETROL_CODE, '')} — כ-{n(round(ev_n / pet_n * 100))} "
            f"על כל מאה.")})
    if pet_n and die_n:
        diff = (die_n - pet_n) / pet_n
        if abs(diff) < 0.03:
            txt = (f"מכונאות דיזל ובנזין כמעט שקולות: {n(die_n)} מתקנים מורשים ל{labels_by_code[DIESEL_CODE]} "
                   f"ו-{n(pet_n)} ל{labels_by_code[PETROL_CODE]}")
        else:
            lead, lag = ((DIESEL_CODE, PETROL_CODE) if die_n > pet_n else (PETROL_CODE, DIESEL_CODE))
            ln, gn = max(die_n, pet_n), min(die_n, pet_n)
            txt = (f"{labels_by_code[lead]} נפוצה מ{labels_by_code[lag]}: {n(ln)} מתקנים לעומת {n(gn)}")
        both = len(has[DIESEL_CODE] & has[PETROL_CODE])
        insights.append({"id": "fuel", "text_he": (
            f"{txt}; {n(both)} מתקנים מורשים לשתיהן.")})

    # EV share by district
    fac["ev"] = fac["id"].isin(has[EV_CODE])
    ev_rows = []
    for x in dist_order:
        if x == UNASSIGNED:
            continue
        sub = fac[fac["district"] == x]
        ev_rows.append((x, len(sub), int(sub["ev"].sum())))
    ev_rows.sort(key=lambda r: (-(r[2] / r[1] if r[1] else 0), r[0]))
    ev_chart = {"names": [r[0] for r in ev_rows],
                "values": [pnum(r[2] / r[1] * 100) if r[1] else 0 for r in ev_rows],
                "counts": [r[2] for r in ev_rows], "totals": [r[1] for r in ev_rows],
                "national": pnum(ev_n / total * 100) if total else 0}
    ev_table = [{"name": r[0], "share": pct(r[2] / r[1] * 100) if r[1] else "—",
                 "ev": n(r[2]), "total": n(r[1])} for r in ev_rows]
    big = [r for r in ev_rows if r[1] >= MIN_DIST_GARAGES]
    if len(big) >= 3:
        hi, lo = big[0], big[-1]
        gap = (hi[2] / hi[1] - lo[2] / lo[1]) * 100
        if gap >= 5:
            insights.append({"id": "ev_gap", "text_he": (
                f"ההסמכה לרכב חשמלי והיברידי אינה אחידה: במחוז {hi[0]} {pct(hi[2] / hi[1] * 100)} מהמתקנים "
                f"מורשים לכך, ובמחוז {lo[0]} רק {pct(lo[2] / lo[1] * 100)} (מחוזות עם {n(MIN_DIST_GARAGES)} "
                f"מתקנים לפחות).")})

    # district x family heatmap (share of the district's facilities offering the family)
    fam_by = lic.drop_duplicates(["id", "family"]).merge(fac[["id", "district"]], on="id")
    fam_ct = fam_by.groupby(["district", "family"]).size()
    fams = [f for f in FAMILY_ORDER if f in set(lic["family"])]
    hm_d = [x for x in dist_order if x != UNASSIGNED]
    cells = []
    heat_table = []
    for yi, x in enumerate(hm_d):
        tot = int(dist_tot.get(x, 0))
        row = []
        for xi, f in enumerate(fams):
            c = int(fam_ct.get((x, f), 0))
            v = pnum(c / tot * 100) if tot else 0
            cells.append([xi, yi, v, c])
            row.append(pct(c / tot * 100, 0) if tot else "—")
        heat_table.append({"name": x, "cells": row})
    heat_chart = {"x": fams, "y": hm_d, "cells": cells, "max": _vmax(cells)}

    # co-occurrence (top specialties)
    top_codes = sp.head(COOC_N)["code"].tolist()
    sets = {c: set(lic.loc[lic["code"] == c, "id"]) for c in top_codes}
    co_cells, co_table, best = [], [], None
    for yi, a in enumerate(top_codes):
        row = []
        for xi, b in enumerate(top_codes):
            inter = len(sets[a] & sets[b])
            v = pnum(inter / len(sets[a]) * 100) if sets[a] else 0
            if a != b:
                co_cells.append([xi, yi, v, inter])
            row.append("—" if a == b else pct(inter / len(sets[a]) * 100, 0))
            if a != b and len(sets[a]) >= 100 and {a, b} != {PETROL_CODE, DIESEL_CODE}:
                key = (inter / len(sets[a]), inter, labels_by_code[a], labels_by_code[b])
                if best is None or key > best[0]:
                    best = (key, a, b, inter)
        co_table.append({"name": labels_by_code[a], "cells": row})
    cooc_chart = {"x": [labels_by_code[c] for c in top_codes], "y": [labels_by_code[c] for c in top_codes],
                  "cells": co_cells, "max": _vmax(co_cells)}
    if best and best[0][0] >= 0.5:
        _, a, b, inter = best
        insights.append({"id": "cooc", "text_he": (
            f"הצירוף ההדוק ביותר: {pct(inter / len(sets[a]) * 100)} מהמתקנים המורשים ל{labels_by_code[a]} "
            f"מורשים גם ל{labels_by_code[b]} ({n(inter)} מתוך {n(len(sets[a]))}).")})

    # ── chains (corporate operators only) ─────────────────────────────
    corp = fac[fac["reg"].str.fullmatch(r"5\d{8}")]
    ch = corp.groupby("reg").size()
    ch = ch[ch >= 2]
    nm = corp[corp["reg"].isin(ch.index)].groupby(["reg", "name"]).size().reset_index(name="k")
    nm = nm.sort_values(["reg", "k", "name"], ascending=[True, False, True], kind="mergesort")
    disp = dict(zip(nm.drop_duplicates("reg")["reg"], nm.drop_duplicates("reg")["name"]))
    chains = pd.DataFrame({"reg": ch.index, "k": ch.values})
    chains["name"] = chains["reg"].map(disp)
    chains = chains.sort_values(["k", "name", "reg"], ascending=[False, True, True], kind="mergesort")
    top_ch = chains.head(TOP_CHAINS)
    chains_chart = {"names": top_ch["name"].tolist(), "values": [int(v) for v in top_ch["k"]]}
    multi_fac = int(chains["k"].sum())
    n_chains = len(chains)
    if len(top_ch) and int(top_ch.iloc[0]["k"]) >= 5 and total:
        lead_ = "השוק מבוזר: " if multi_fac / total < 0.25 else ""
        insights.append({"id": "chains", "text_he": (
            f"{lead_}{n(n_chains)} חברות מפעילות יותר ממתקן אחד, ויחד {n(multi_fac)} מתקנים "
            f"({pct(multi_fac / total * 100)}). המפעילה הגדולה היא {top_ch.iloc[0]['name']} עם "
            f"{n(top_ch.iloc[0]['k'])} מתקנים.")})

    # ── testing stations ──────────────────────────────────────────────
    st = fac[fac["group"] == "מכון רישוי"]
    st_ct = st.groupby("district").size()
    st_rows = []
    for x in dist_order:
        if x == UNASSIGNED and not st_ct.get(x, 0):
            continue
        s, g = int(st_ct.get(x, 0)), int(dist_tot.get(x, 0))
        st_rows.append({"name": x, "st": s, "g": g, "ratio": round(g / s) if s else None})
    stations_chart = {"names": [r["name"] for r in st_rows], "values": [r["st"] for r in st_rows],
                      "ratio": [r["ratio"] for r in st_rows]}
    stations_table = [{"name": r["name"], "st": n(r["st"]), "g": n(r["g"]),
                       "ratio": n(r["ratio"]) if r["ratio"] is not None else "—"} for r in st_rows]
    cmp_ = [r for r in st_rows if r["ratio"] is not None and r["g"] >= MIN_DIST_GARAGES and r["name"] != UNASSIGNED]
    cmp_.sort(key=lambda r: (r["ratio"], r["name"]))
    if len(cmp_) >= 3 and cmp_[-1]["ratio"] >= 1.5 * cmp_[0]["ratio"]:
        insights.append({"id": "stations", "text_he": (
            f"ב-{n(len(st))} מכוני הרישוי עוברים כלי הרכב מבחן שנתי. היחס למוסכים משתנה בין המחוזות: "
            f"במחוז {cmp_[0]['name']} מכון אחד לכל {n(cmp_[0]['ratio'])} מתקנים, ובמחוז {cmp_[-1]['name']} "
            f"אחד לכל {n(cmp_[-1]['ratio'])}.")})
    st_list = st.sort_values(["district", "place", "name", "id"], kind="mergesort")
    station_list = [{"name": r["name"], "place": r["place"] or "—", "district": r["district"]}
                    for _, r in st_list.head(STATIONS_CAP).iterrows()]

    # ── managers (counted, never named) ───────────────────────────────
    mg = d[d["mgr"] != ""].drop_duplicates(["id", "mgr"])
    mgr_per = mg.groupby("id").size()
    n_mgr = mg["mgr"].nunique()
    one_mgr = int((mgr_per == 1).sum())
    multi_mgr = int((mgr_per >= 3).sum())
    if len(mgr_per):
        insights.append({"id": "managers", "text_he": (
            f"לכל תחום במתקן נרשם מנהל מקצועי. ב-{pct(one_mgr / len(mgr_per) * 100)} מהמתקנים שיש להם "
            f"מנהל רשום, מנהל אחד אחראי לכל התחומים; ב-{n(multi_mgr)} מתקנים רשומים שלושה מנהלים או יותר.")})

    # ── KPIs ──────────────────────────────────────────────────────────
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "places": {"value": n_places, "display": n(n_places), "tone": "brand"},
        "stations": {"value": stations, "display": n(stations), "tone": "brand"},
        "ev": {"value": pnum(ev_n / total * 100) if total else 0,
               "display": f"{ev_n / total * 100:.1f}%" if total else "0%", "tone": "info"},
        "licences": {"value": len(lic), "display": n(len(lic)), "tone": "brand"},
        "specs": {"value": len(sp), "display": n(len(sp)), "tone": "brand"},
        "chains": {"value": n_chains, "display": n(n_chains), "tone": "brand"},
        "managers": {"value": n_mgr, "display": n(n_mgr), "tone": "brand"},
    }

    top_spec = sp.iloc[0]
    labels = {
        "lede": (f"מאגר משרד התחבורה של מפעלי שירותי התחזוקה לרכב: {n(total)} מתקנים — מוסכים מורשים, "
                 f"מוסכי רישוי ומכוני רישוי — ב-{n(n_places)} יישובים, עם {n(len(lic))} הרשאות ב-{n(len(sp))} "
                 f"תחומי מקצוע. העמוד מציג את סוגי המתקנים, פריסתם במחוזות וביישובים, את תחומי ההתמחות "
                 f"והצירופים ביניהם, את רשתות המוסכים ואת מכוני הרישוי."),
        "types_note": (f"כל מתקן נספר פעם אחת לפי סוג הרישיון שלו. {n(auth)} מוסכים מורשים הם "
                       f"{pct(auth / total * 100 if total else 0)} מהמאגר."),
        "types_aria": "תרשים עמודות אופקי: מספר המתקנים לפי סוג מתקן.",
        "districts_note": (f"מחוז לפי שם היישוב הרשום."
                           + (f" {n(unassigned)} מתקנים ללא יישוב מזוהה נספרים תחת „{UNASSIGNED}”."
                              if unassigned else "")),
        "districts_aria": "תרשים עמודות מוערמות: מתקנים לפי מחוז וסוג מתקן.",
        "settlements_note": (f"{n(len(top_pl))} היישובים עם מספר המתקנים הגדול ביותר, "
                             f"מתוך {n(n_places)} יישובים."),
        "settlements_aria": "תרשים עמודות אופקי: היישובים עם מספר המתקנים הגדול ביותר.",
        "specialties_note": (f"מספר המתקנים המורשים לכל תחום. מתקן מורשה לכמה תחומים נספר בכל אחד מהם; "
                             f"התחום הנפוץ: {top_spec['label']} ({n(top_spec['k'])} מתקנים)."),
        "specialties_aria": "תרשים עמודות אופקי: מספר המתקנים המורשים לפי תחום מקצוע.",
        "families_note": "תחומי המקצוע מקובצים למשפחות; גודל כל פלח הוא מספר ההרשאות בתחום. לחיצה על משפחה מתמקדת בה.",
        "families_aria": "תרשים שמש: הרשאות לפי משפחת תחומים ותחום מקצוע.",
        "breadth_note": (f"בכמה תחומי מקצוע מורשה כל מתקן. {n(int((per >= 2).sum()))} מתקנים מורשים "
                         f"ליותר מתחום אחד."),
        "breadth_aria": "תרשים עמודות: מספר המתקנים לפי מספר תחומי המקצוע שלהם.",
        "ev_note": (f"שיעור המתקנים המורשים ל{ev_label} מכלל המתקנים בכל מחוז; הקו המקווקו הוא "
                    f"השיעור הארצי ({pct(ev_n / total * 100 if total else 0)}).") if ev_label else "",
        "ev_aria": "תרשים עמודות: שיעור המתקנים המורשים לרכב חשמלי והיברידי לפי מחוז.",
        "heat_note": "איזה חלק מהמתקנים בכל מחוז מורשה לכל משפחת תחומים — מבט על אופי שירותי הרכב באזור.",
        "heat_aria": "מפת חום: שיעור המתקנים המורשים לכל משפחת תחומים, לפי מחוז.",
        "cooc_note": (f"בין {n(len(top_codes))} התחומים הנפוצים: איזה חלק מהמתקנים המורשים לתחום שבשורה "
                      f"מורשים גם לתחום שבעמודה."),
        "cooc_aria": "מפת חום: שיעור המתקנים המורשים לתחום אחד שמורשים גם לתחום אחר.",
        "chains_note": (f"חברות (לפי מספר תאגיד) שמפעילות יותר ממתקן אחד: {n(n_chains)} חברות, "
                        f"{n(multi_fac)} מתקנים. השם המוצג הוא השם הנפוץ בסניפי החברה."),
        "chains_aria": "תרשים עמודות אופקי: החברות המפעילות את מספר המתקנים הגדול ביותר.",
        "stations_note": (f"{n(stations)} מכוני רישוי לפי מחוז, ויחס המוסכים והמתקנים האחרים לכל מכון."),
        "stations_aria": "תרשים עמודות: מספר מכוני הרישוי לפי מחוז.",
        "station_list_note": (f"רשימת {n(len(station_list))} מכוני הרישוי במאגר, לפי מחוז ויישוב."
                              + (f" מוצגים {n(STATIONS_CAP)} הראשונים." if len(st) > STATIONS_CAP else "")),
        "station_list_caption": "מכוני הרישוי במאגר: שם, יישוב ומחוז.",
    }
    tables = {
        "types": [{"name": a, "count": n(b)} for a, b in zip(types_chart["names"], types_chart["values"])],
        "districts": districts_table,
        "settlements": [{"name": a, "count": n(b)} for a, b in zip(settlements_chart["names"], settlements_chart["values"])],
        "specialties": [{"name": a, "count": n(b)} for a, b in zip(spec_names, spec_vals)],
        "families": fam_table,
        "breadth": [{"name": a, "count": n(b)} for a, b in zip(b_x, b_y)],
        "ev": ev_table,
        "heat": heat_table,
        "cooc": co_table,
        "chains": [{"name": a, "count": n(b)} for a, b in zip(chains_chart["names"], chains_chart["values"])],
        "stations": stations_table,
        "station_list": station_list,
    }
    charts = {
        "types": types_chart, "districts": districts_chart, "settlements": settlements_chart,
        "specialties": specialties_chart, "families": sun, "breadth": breadth_chart,
        "ev": ev_chart, "heat": heat_chart, "cooc": cooc_chart, "chains": chains_chart,
        "stations": stations_chart,
    }
    flags = {"ev": bool(ev_label and ev_n), "chains": bool(len(top_ch)), "stations": bool(len(st)),
             "cooc": len(top_codes) >= 3}

    return {
        "agent_data": {
            "summary_he": (f"מאגר משרד התחבורה של {n(total)} מוסכים מורשים, מוסכי רישוי ומכוני רישוי ב-{n(n_places)} "
                           f"יישובים — סוג המתקן, היישוב ותחומי המקצוע שבהם הוא מורשה לטפל ברכב."),
            "dataset_kind": "registry",
            "suggested_tags": ["מוסכים", "מכוני רישוי", "תחזוקת רכב", "רכב חשמלי", "משרד התחבורה"],
            "related_ids": ["392abd0a-64f6-4c18-9d56-0111001411e6",
                            "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                            "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                            "0219b34f-43c7-435b-bdfe-e65e944cde50"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
