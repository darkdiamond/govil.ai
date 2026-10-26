"""סחר, יבוא וייצור מוצרי תעבורה — Ministry of Transport register of spare-parts
traders and importers, accessory/installation plants, vehicle-body makers and
trailer makers.

One row per (business, licensed activity). Business attributes (name, type,
settlement, address, phone) repeat on every row of a business, so the frame is
reduced to one row per `mispar_esek`. The register is a snapshot, not a time
series: businesses and activity codes come and go between versions.

Activity labels are messy upstream (reversed digits in standard references,
moved gershayim); they are shortened to the activity itself and grouped into
families by keyword, so new codes fall into a family without a code list.
Registrations numbered 99990+ are placeholder/test entries and are dropped
(the page says how many).

Geography: settlement only; mapped to districts through the static CBS
gazetteer shared with the garages recipe (35c791ca). Unknown settlements go to
"לא משויך" and the page says how many.

Naming: businesses (including sole traders named after their owner) are named
in the widest-portfolio table. Phone numbers, street addresses and business
numbers never reach the page.
"""
import math
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
UNASSIGNED = "לא משויך"

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


# This register only (spellings and regional councils).
ALIASES.update({
    "יד חנה מ": "יד חנה", "כוכב יאיר": "כוכב יאיר-צור יגאל", "צורן": "קדימה-צורן",
    "קרית-שמונה": "קרית שמונה", "קרית חיים": "חיפה", "גלגוליה": "ג׳לג׳וליה",
})
COUNCIL_DISTRICT = {"משגב": "צפון", "שער הנגב": "דרום"}


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

for _k, _v in COUNCIL_DISTRICT.items():
    PLACE_DISTRICT.setdefault(norm_place(_k), _v)


# ── activity labels ─────────────────────────────────────────────────────
# The register's activity labels carry standard references whose digits are
# stored reversed (ת"י 1334, מפמ"כ 343 ...) and gershayim moved to the word's
# end (גפמ"). Labels are shortened to the activity itself; the few whose
# substance is a number get a fixed wording by code.
LABEL_OVERRIDE = {
    "190": "חלקי חילוף לקורקינט חשמלי",
    "191": "חלקי חילוף לגלגינוע (קורקינט חשמלי)",
    "305": "חלקי חילוף ליחידות הינע לכיסאות גלגלים",
    "401": "התקנים לסגירת ארגז אחורי בטנדר",
    "661": "התקנה ועיגון חגורות בטיחות למושבים (אוטובוסים)",
    "679": "התקנה ועיגון חגורות בטיחות למושבים",
    "703": "ייצור ערכות הגבהה לטנדרים ולרכב קל",
    "704": "התקנת ערכות הגבהה לטנדרים ולרכב קל",
    "7002": "גרורים ונתמכים קלים (דגם מאושר)",
    "7003": "גרורים ונתמכים בינוניים (דגם מאושר)",
    "7004": "גרורים ונתמכים כבדים (דגם מאושר)",
    "7010": "גרורים קלים מאוד (דגם מאושר)",
}
_REF = re.compile(r"(?:^|(?<=[\s\-–(]))(?:עפ\"?י|עפ|עיפי|לפי|בהתאם|כפוף|ת\"?י\s*\d|תי\s*\d|מפמ\"?כ|"
                  r"ממ\"?ת|תקנה|נוהל|הנ \d|ר' אירופאית)(?=[\s\d\"]|$)")
ABBR = {"גפמ": "גפ״מ", "צמה": "צמ״ה", "לצמה": "לצמ״ה", "צהל": "צה״ל", "עי": "ע״י", "עג": "ע״ג",
        "חח": "ח״ח", "מע'": "מערכת"}


def _word(w):
    w = w.strip('"')
    return ABBR.get(w, w)


def short_label(code, raw):
    if code in LABEL_OVERRIDE:
        return LABEL_OVERRIDE[code]
    s = re.sub(r"\s+", " ", raw).strip()
    s = re.sub(r"\)([^()]+)\(", r"(\1)", s)
    m = _REF.search(s)
    if m and m.start() > 3:
        s = s[:m.start()]
    m = re.search(r"\S*\d", s)
    if m and m.start() > 3:
        s = s[:m.start()]
    s = " ".join(_word(w) for w in s.split())
    s = re.sub(r"[\s\-–:.,(]+$", "", s).strip()
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\s*-?\s*למעט\s.*$", "", s).strip() or s
    return s or f"קוד {code}"


# ── activity families and, for spare parts, vehicle segment + condition ─
F_NEW, F_USED, F_REFURB, F_ELEC = "ח״ח חדשים", "ח״ח משומשים", "ח״ח משופצים", "חשמל ואלקטרוניקה"
F_TYRES, F_OILS, F_ACC = "צמיגים וחישוקים", "שמנים וכימיקלים", "אביזרים וציוד"
F_BODY, F_SAFETY, F_INSTALL, F_TRAILER, F_OTHER = (
    "מרכבים ורכב משא", "בטיחות ומיגון", "התקנות, ייצור וחידוש", "גרורים (אישורי דגם)", "אחר")
FAMILY_ORDER = [F_NEW, F_USED, F_REFURB, F_ELEC, F_ACC, F_OILS, F_TYRES, F_SAFETY, F_BODY,
                F_INSTALL, F_TRAILER, F_OTHER]
PARTS_FAMILIES = {F_NEW, F_USED, F_REFURB, F_ELEC}
_PARTS = re.compile(r"חלקי|ח״ח|חלקים|ראשי מנוע|תיבות הילוכים")
_SAFETY = re.compile(r"התרעה|התראה|זיהוי הולכי|זיהוי רוכבי|ריסון|חגורות|כיבוי אש|מגני צד|תאורת צד|התזת|"
                     r"הגנה תת|נקודות עיגון|קשתות בטיחות|מסגרת בטיחות|מסגרות בטיחות|אביזרי בטיחות")
_BODY = re.compile(r"מרכב|ארגז|מיכל|דחס|מנוף|מנופי|מערבל|משאבות בטון|שלדה|דופן הרמה|מגבה")
_INSTALL = re.compile(r"התקנ|ייצור|יצור|חידוש|הטבעת|שינוי|קיצור|הגבהת|בידוד|השתלמות|שרות")


def family_of(code, label):
    if (len(code) == 4 and code.startswith("70")) or label.startswith("גרור"):
        return F_TRAILER
    if label.startswith("מנהל מקצועי") or label.startswith("קוד "):
        return F_OTHER
    if _PARTS.search(label):
        if "משומש" in label:
            return F_USED
        if "משופצ" in label or "מחודש" in label:
            return F_REFURB
        if "חשמל " in label + " " and label.startswith("חלקי חשמל"):
            return F_ELEC
        return F_NEW
    if re.search(r"צמיג|חישוק|אבוב", label):
        return F_TYRES
    if re.search(r"שמן|שמנים|סיכה|כימיק", label):
        return F_OILS
    if _SAFETY.search(label):
        return F_SAFETY
    if _BODY.search(label):
        return F_BODY
    if _INSTALL.search(label):
        return F_INSTALL
    return F_ACC


SEG_ORDER = ["רכב מנועי (כללי)", "משאיות", "אוטובוסים", "אופנועים", "אופניים וקורקינטים חשמליים",
             "שטח, חקלאות וצמ״ה", "גרורים", "קלנועיות וכיסאות גלגלים", "רכב מיוחד"]
SEG_MICRO = "אופניים וקורקינטים חשמליים"


def segment_of(label):
    if re.search(r"משאית|משאיות", label):
        return "משאיות"
    if "אוטובוס" in label:
        return "אוטובוסים"
    if re.search(r"אופנוע|רכינוע", label):
        return "אופנועים"
    if re.search(r"אופניים|קורקינט|גלגינוע", label):
        return SEG_MICRO
    if re.search(r"טרקטור|טרקטרון|רכב שטח|צמ״ה|מכונות|מנופ", label):
        return "שטח, חקלאות וצמ״ה"
    if re.search(r"גרור|נגרר", label):
        return "גרורים"
    if re.search(r"קלנוע|כסא|כסאות|כיסאות", label):
        return "קלנועיות וכיסאות גלגלים"
    if re.search(r"אספנות|תיפעולי|קרבי", label):
        return "רכב מיוחד"
    return "רכב מנועי (כללי)"


COND = {F_NEW: "חדשים", F_ELEC: "חדשים", F_USED: "משומשים", F_REFURB: "משופצים"}
COND_ORDER = ["חדשים", "משופצים", "משומשים"]

# ── business types ──────────────────────────────────────────────────────
TYPE_ORDER = ["סחר", "ייצור", "מרכבים", "גרורים"]
TYPE_LABEL = {"סחר": "בתי מסחר ויבואנים", "ייצור": "מפעלי ייצור והתקנה", "מרכבים": "יצרני מרכבים",
              "גרורים": "יצרני גרורים"}
TEST_ID_MIN = 99990       # placeholder/test registrations (e.g. "טסט ...") use 99998/99999
TOP_SETTLEMENTS = 15
TOP_ACTIVITIES = 15
TOP_BUSINESSES = 10
COOC_N = 10
BREADTH_CAP = 12
MIN_PLACE_PARTS = 25      # settlements compared on used-parts share need this many parts traders
USED_CAP = 15
MIN_DIST = 100            # districts below this many businesses are not ranked in insights


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def r1(v):
    return round(float(v), 1)


def clean_place(p):
    p = re.sub(r"\s+", " ", p).strip().rstrip(".*").strip()
    p = re.sub(r"\s+-\s*|\s*-\s+", "-", p)
    if p.startswith("לא ידוע"):
        return ""
    # gershayim moved to the end: בני עיש" -> בני עי"ש
    m = re.match(r"^(.*\S)(\S)\"$", p)
    if m and len(p.split()[-1]) >= 4:
        p = m.group(1) + '"' + m.group(2)
    return p


def fix_name(s):
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\)([^()]+)\(", r"(\1)", s)


def _vmax(cells):
    m = max((c[2] for c in cells), default=0)
    return int(min(100, max(10, math.ceil(m / 10) * 10)))


def _sorted_counts(s, key="name"):
    t = s.reset_index()
    t.columns = [key, "k"]
    return t.sort_values(["k", key], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def compute(frames):
    raw = frames["main"]
    d = pd.DataFrame({
        "id": raw["mispar_esek"].str.strip(),
        "name": raw["shem_esek"].map(fix_name),
        "type": raw["sug_esek"].map(lambda s: re.sub(r"\s+", " ", s).strip()),
        "place": raw["yishuv"].map(clean_place),
        "code": raw["cod_isuk"].str.strip(),
        "rawlabel": raw["isuk"],
    })
    d = d[d["id"] != ""].copy()
    d["idn"] = pd.to_numeric(d["id"], errors="coerce")
    n_test = int(d.loc[d["idn"] >= TEST_ID_MIN, "id"].nunique())
    d = d[~(d["idn"] >= TEST_ID_MIN)]
    d = d.sort_values(["idn", "id", "code", "rawlabel", "name", "place", "type"],
                      kind="mergesort").reset_index(drop=True)

    biz = d.drop_duplicates("id")[["id", "idn", "name", "type", "place"]].copy()
    biz["place_key"] = biz["place"].map(norm_place)
    sp_ = biz[biz["place"] != ""].groupby(["place_key", "place"]).size().reset_index(name="k")
    sp_ = sp_.sort_values(["place_key", "k", "place"], ascending=[True, False, True], kind="mergesort")
    sp_ = sp_.drop_duplicates("place_key")
    disp = dict(zip(sp_["place_key"], sp_["place"]))
    biz["place"] = biz["place_key"].map(lambda k: disp.get(k, ""))
    biz["district"] = biz["place"].map(district_of)
    total = len(biz)

    lic = d[d["code"] != ""].drop_duplicates(["id", "code"]).copy()
    lab = lic.groupby(["code", "rawlabel"]).size().reset_index(name="k")
    lab = lab.sort_values(["code", "k", "rawlabel"], ascending=[True, False, True], kind="mergesort")
    lab = lab.drop_duplicates("code")
    code_label = {c: short_label(c, r) for c, r in zip(lab["code"], lab["rawlabel"])}
    lic["label"] = lic["code"].map(code_label)
    lic["family"] = [family_of(c, l) for c, l in zip(lic["code"], lic["label"])]
    lic = lic.drop(columns=["place"]).merge(biz[["id", "place", "district"]], on="id", how="left")
    n_lic = len(lic)
    n_codes = int(lic["code"].nunique())
    insights = []

    types_present = [t for t in TYPE_ORDER if (biz["type"] == t).any()]
    types_present += sorted(set(biz["type"]) - set(TYPE_ORDER) - {""})
    tlabel = lambda t: TYPE_LABEL.get(t, t or "לא צוין")  # noqa: E731

    # ── business types ────────────────────────────────────────────────
    tb = biz.groupby("type").size()
    tl = d[d["code"] != ""].drop_duplicates(["id", "code"]).groupby("type").size()
    types_chart = {"names": [tlabel(t) for t in types_present],
                   "biz": [int(tb.get(t, 0)) for t in types_present],
                   "lic": [int(tl.get(t, 0)) for t in types_present]}
    types_table = [{"name": tlabel(t), "biz": n(tb.get(t, 0)), "lic": n(tl.get(t, 0)),
                    "avg": f"{(tl.get(t, 0) / tb.get(t, 1)):.1f}"} for t in types_present]
    n_trade = int(tb.get("סחר", 0))
    n_make = int(sum(tb.get(t, 0) for t in types_present if t != "סחר"))
    if total and n_trade / total >= 0.5 and n_make:
        parts = [f"{n(tb.get(t, 0))} {tlabel(t)}" for t in types_present if t != "סחר" and tb.get(t, 0)]
        lst = ", ".join(parts[:-1]) + (" ו-" if len(parts) > 1 else "") + parts[-1]
        big_t = [t for t in types_present if tb.get(t, 0) >= 20]
        avg = {t: tl.get(t, 0) / tb[t] for t in big_t}
        tail = ""
        if len(big_t) >= 2:
            hi = sorted(big_t, key=lambda t: (-avg[t], t))[0]
            lo = sorted(big_t, key=lambda t: (avg[t], t))[0]
            if avg[lo] > 0 and avg[hi] / avg[lo] >= 2:
                tail = (f" בממוצע, {tlabel(hi)} רשומים ל-{avg[hi]:.1f} פעילויות לעסק ו{tlabel(lo)} "
                        f"ל-{avg[lo]:.1f} בלבד.")
        insights.append({"id": "type_mix", "text_he": (
            f"{n(n_trade)} מתוך {n(total)} העסקים במאגר ({pct(n_trade / total * 100)}) הם בתי מסחר "
            f"ויבואנים של חלקים ואביזרים; לצדם {lst}.{tail}")})

    # ── breadth ───────────────────────────────────────────────────────
    per = lic.groupby("id").size()
    n_active = len(per)
    br = per.clip(upper=BREADTH_CAP).value_counts()
    b_x = [str(i) if i < BREADTH_CAP else f"{BREADTH_CAP}+" for i in range(1, BREADTH_CAP + 1)]
    b_y = [int(br.get(i, 0)) for i in range(1, BREADTH_CAP + 1)]
    breadth_chart = {"x": b_x, "y": b_y}
    avg_act = per.mean() if n_active else 0
    med = float(per.median()) if n_active else 0
    if n_active >= 20:
        mx = int(per.max())
        n_mx = int((per == mx).sum())
        n_one = int((per == 1).sum())
        insights.append({"id": "breadth", "text_he": (
            f"עסק טיפוסי רשום למספר פעילויות: החציון הוא {med:g} והממוצע {avg_act:.1f}; "
            f"{pct((per >= 2).sum() / n_active * 100)} מהעסקים רשומים ליותר מפעילות אחת, ו-{n(n_one)} "
            f"לפעילות יחידה. "
            + (f"הרחבים ביותר ({n(n_mx)} עסקים) רשומים ל-{n(mx)} פעילויות." if n_mx > 1
               else f"העסק הרחב ביותר רשום ל-{n(mx)} פעילויות."))})

    # ── activities ────────────────────────────────────────────────────
    ac = _sorted_counts(lic.groupby("label").size(), "label")
    top_ac = ac.head(TOP_ACTIVITIES)
    rest = ac.iloc[TOP_ACTIVITIES:]
    act_fam = lic.drop_duplicates("label").set_index("label")["family"].to_dict()
    act_chart = {"names": top_ac["label"].tolist(), "values": [int(v) for v in top_ac["k"]],
                 "families": [act_fam.get(x, F_OTHER) for x in top_ac["label"]]}
    act_table = [{"name": a, "fam": act_fam.get(a, F_OTHER), "count": n(b)}
                 for a, b in zip(top_ac["label"], top_ac["k"])]
    if len(rest):
        act_table.append({"name": f"אחר ({n(len(rest))} פעילויות)", "fam": "", "count": n(rest["k"].sum())})
    if len(ac) >= 3 and n_trade:
        trade_ids = set(biz.loc[biz["type"] == "סחר", "id"])
        tr = lic[lic["id"].isin(trade_ids)]
        tac = _sorted_counts(tr.groupby("label").size(), "label").head(3)
        if len(tac) == 3:
            items = [f"{r['label']} ({pct(r['k'] / n_trade * 100, 0)})" for _, r in tac.iterrows()]
            insights.append({"id": "top_activities", "text_he": (
                f"הפעילויות הנפוצות בבתי המסחר: {items[0]}, {items[1]} ו{items[2]} — האחוז הוא מתוך "
                f"{n(n_trade)} בתי המסחר. במאגר כולו רשומות {n(n_codes)} פעילויות שונות.")})

    # ── families sunburst ─────────────────────────────────────────────
    fam_biz = lic.drop_duplicates(["id", "family"]).groupby("family").size()
    fams_present = [f for f in FAMILY_ORDER if (lic["family"] == f).any()]
    ac_f = ac.copy()
    ac_f["family"] = ac_f["label"].map(lambda x: act_fam.get(x, F_OTHER))
    sun, fam_table = [], []
    for f in fams_present:
        sub = ac_f[ac_f["family"] == f]
        sun.append({"name": f, "children": [{"name": r["label"], "value": int(r["k"])} for _, r in sub.iterrows()]})
        fam_table.append({"name": f, "biz": n(fam_biz.get(f, 0)), "acts": n(len(sub)), "lic": n(sub["k"].sum())})

    # ── spare parts: segment × condition ──────────────────────────────
    parts = lic[lic["family"].isin(PARTS_FAMILIES)].copy()
    parts["seg"] = parts["label"].map(segment_of)
    parts["cond"] = parts["family"].map(COND)
    pc = parts.drop_duplicates(["id", "seg", "cond"]).groupby(["seg", "cond"]).size()
    seg_biz = parts.drop_duplicates(["id", "seg"]).groupby("seg").size()
    segs = [s for s in SEG_ORDER if s in seg_biz.index] + sorted(set(seg_biz.index) - set(SEG_ORDER))
    segs = sorted(segs, key=lambda s: (-int(seg_biz.get(s, 0)), s))
    conds = [c for c in COND_ORDER if (parts["cond"] == c).any()]
    parts_chart = {"names": segs,
                   "series": [{"name": c, "data": [int(pc.get((s, c), 0)) for s in segs]} for c in conds]}
    parts_table = [{"name": s, "total": n(seg_biz.get(s, 0)),
                    "cells": [n(pc.get((s, c), 0)) for c in conds]} for s in segs]
    n_parts = int(parts["id"].nunique())
    used_ids = set(parts.loc[parts["cond"] == "משומשים", "id"])
    n_used = len(used_ids)
    micro = parts[parts["seg"] == SEG_MICRO]
    n_micro = int(micro["id"].nunique())
    if n_micro >= 10 and n_parts:
        mp = _sorted_counts(micro.drop_duplicates("id").groupby("place").size()).query("name != ''")
        lead = f"; הריכוז הגדול ביותר ב{mp.iloc[0]['name']} ({n(mp.iloc[0]['k'])})" if len(mp) and mp.iloc[0]["k"] >= 3 else ""
        insights.append({"id": "micro", "text_he": (
            f"{n(n_micro)} עסקים רשומים לחלקי חילוף לאופניים חשמליים, לקורקינטים ולגלגינועים "
            f"({pct(n_micro / n_parts * 100)} מעסקי חלקי החילוף){lead}.")})

    # ── geography ─────────────────────────────────────────────────────
    dist_tot = biz.groupby("district").size()
    dists = sorted([x for x in dist_tot.index if x != UNASSIGNED], key=lambda x: (-int(dist_tot[x]), x))
    unassigned = int(dist_tot.get(UNASSIGNED, 0))
    ctd = biz.groupby(["district", "type"]).size()
    districts_chart = {"names": dists, "series": [
        {"name": tlabel(t), "data": [int(ctd.get((x, t), 0)) for x in dists]} for t in types_present]}
    districts_table = [{"name": x, "total": n(dist_tot[x]),
                        "cells": [n(ctd.get((x, t), 0)) for t in types_present]} for x in dists]
    big_d = [x for x in dists if dist_tot[x] >= MIN_DIST]
    if len(big_d) >= 3 and n_make:
        msh = {x: (dist_tot[x] - ctd.get((x, "סחר"), 0)) / dist_tot[x] for x in big_d}
        hi = sorted(big_d, key=lambda x: (-msh[x], x))[0]
        lo = sorted(big_d, key=lambda x: (msh[x], x))[0]
        nat = n_make / total
        if msh[hi] - msh[lo] >= 0.08:
            insights.append({"id": "make_geo", "text_he": (
                f"משקל הייצור (מפעלים, מרכבים וגרורים) שונה מאוד בין המחוזות: במחוז {hi} הוא {pct(msh[hi] * 100)} "
                f"מהעסקים, לעומת {pct(msh[lo] * 100)} במחוז {lo} ו-{pct(nat * 100)} בכלל המאגר "
                f"(מחוזות עם {n(MIN_DIST)} עסקים לפחות).")})

    pl = _sorted_counts(biz[biz["place"] != ""].groupby("place").size())
    n_places = len(pl)
    top_pl = pl.head(TOP_SETTLEMENTS)
    ctp = biz.groupby(["place", "type"]).size()
    settlements_chart = {"names": top_pl["name"].tolist(), "series": [
        {"name": tlabel(t), "data": [int(ctp.get((p, t), 0)) for p in top_pl["name"]]} for t in types_present]}
    settlements_table = [{"name": p, "total": n(k), "cells": [n(ctp.get((p, t), 0)) for t in types_present]}
                         for p, k in zip(top_pl["name"], top_pl["k"])]
    if n_places >= 10 and total:
        t3 = pl.head(3)
        top10 = int(pl.head(10)["k"].sum())
        insights.append({"id": "concentration", "text_he": (
            f"העסקים פרוסים ב-{n(n_places)} יישובים, ועשרת הגדולים מרכזים {pct(top10 / total * 100)} מהם; "
            f"בראש: {t3.iloc[0]['name']} ({n(t3.iloc[0]['k'])}), {t3.iloc[1]['name']} ({n(t3.iloc[1]['k'])}) "
            f"ו{t3.iloc[2]['name']} ({n(t3.iloc[2]['k'])}).")})

    # used-parts share by settlement
    pb = parts.drop_duplicates("id")[["id", "place"]]
    pb = pb[pb["place"] != ""]
    pb["used"] = pb["id"].isin(used_ids)
    g = pb.groupby("place").agg(k=("used", "size"), u=("used", "sum")).reset_index()
    g = g[g["k"] >= MIN_PLACE_PARTS].copy()
    g["share"] = g["u"] / g["k"]
    g = g.sort_values(["share", "k", "place"], ascending=[False, False, True], kind="mergesort").head(USED_CAP)
    nat_used = n_used / n_parts if n_parts else 0
    used_chart = {"names": g["place"].tolist(), "values": [r1(v * 100) for v in g["share"]],
                  "counts": [int(v) for v in g["u"]], "totals": [int(v) for v in g["k"]],
                  "national": r1(nat_used * 100)}
    used_table = [{"name": p, "share": f"{s * 100:.1f}%", "used": n(u), "total": n(k)}
                  for p, s, u, k in zip(g["place"], g["share"], g["u"], g["k"])]
    if len(g) >= 4 and n_parts:
        above = g[g["share"] >= nat_used + 0.15]
        if len(above) >= 2:
            big = g.sort_values(["k", "place"], ascending=[False, True], kind="mergesort").iloc[0]
            names = [f"{r['place']} ({pct(r['share'] * 100, 0)})" for _, r in above.head(4).iterrows()]
            lst = ", ".join(names[:-1]) + " ו" + names[-1]
            tail = (f", וביישוב עם מספר עסקי החלקים הגדול ביותר, {big['place']}, רק {pct(big['share'] * 100, 0)}"
                    if big["share"] < nat_used else "")
            insights.append({"id": "used_geo", "text_he": (
                f"{pct(nat_used * 100)} מעסקי חלקי החילוף במאגר רשומים גם לחלקים משומשים, אך השיעור גבוה בהרבה ב{lst}"
                f"{tail} (יישובים עם {n(MIN_PLACE_PARTS)} עסקי חלקים לפחות).")})

    # district × family heat
    lic_d = lic[lic["district"] != UNASSIGNED].drop_duplicates(["id", "family"])
    hd = lic_d.groupby(["district", "family"]).size()
    heat_f = [f for f in fams_present if f != F_OTHER]
    heat_cells, heat_table = [], []
    for yi, x in enumerate(dists):
        row = []
        for xi, f in enumerate(heat_f):
            k = int(hd.get((x, f), 0))
            v = r1(k / dist_tot[x] * 100) if dist_tot[x] else 0.0
            heat_cells.append([xi, yi, v, k])
            row.append(f"{v:.0f}%")
        heat_table.append({"name": x, "cells": row})
    heat_chart = {"x": heat_f, "y": dists, "cells": heat_cells, "max": _vmax(heat_cells)}

    # ── co-occurrence of the top activities ───────────────────────────
    top_codes_lab = ac.head(COOC_N)["label"].tolist()
    compact = [x.replace("חלקי חילוף", "ח״ח") for x in top_codes_lab]
    sets = {a: set(lic.loc[lic["label"] == a, "id"]) for a in top_codes_lab}
    co_cells, co_table = [], []
    best = None
    for yi, a in enumerate(top_codes_lab):
        row = []
        for xi, b in enumerate(top_codes_lab):
            if a == b:
                v, k = 100.0, len(sets[a])
            else:
                k = len(sets[a] & sets[b])
                v = r1(k / len(sets[a]) * 100) if sets[a] else 0.0
                if len(sets[a]) >= 100 and (best is None or (v, -yi, -xi) > (best[0], -best[3], -best[4])):
                    best = (v, a, b, yi, xi, k)
            co_cells.append([xi, yi, v, k])
            row.append(f"{v:.0f}%")
        co_table.append({"name": compact[yi], "cells": row})
    cooc_chart = {"x": compact, "y": compact, "cells": co_cells, "max": 100}
    if best and best[0] >= 50:
        insights.append({"id": "cooc", "text_he": (
            f"פעילויות נוטות לבוא בחבילה: {pct(best[0], 0)} מהעסקים הרשומים ל{best[1]} "
            f"({n(len(sets[best[1]]))}) רשומים גם ל{best[2]}.")})

    # safety tech
    adas = lic[lic["label"].str.contains("התנגשות|סטייה מנתיב|השארת ילדים|זיהוי הולכי|זיהוי רוכבי", regex=True)]
    n_adas = int(adas["id"].nunique())
    n_safety = int(fam_biz.get(F_SAFETY, 0))
    if n_adas >= 10:
        insights.append({"id": "safety", "text_he": (
            f"{n(n_safety)} עסקים רשומים להתקנות בטיחות ומיגון (מגני צד, נקודות עיגון, חגורות ועוד), "
            f"ומתוכם {n(n_adas)} מורשים להתקין מערכות התרעה אלקטרוניות — התרעת התנגשות, סטייה מנתיב "
            f"או התראה על ילד שנשכח ברכב.")})

    # ── widest portfolios (businesses, named) ─────────────────────────
    pw = per.reset_index()
    pw.columns = ["id", "k"]
    pw = pw.merge(biz[["id", "idn", "name", "type", "place"]], on="id")
    pw = pw.sort_values(["k", "name", "idn", "id"], ascending=[False, True, True, True], kind="mergesort")
    top_b = pw.head(TOP_BUSINESSES)
    fam_per = lic.drop_duplicates(["id", "family"]).groupby("id").size()
    top_table = [{"name": r["name"], "type": tlabel(r["type"]), "place": r["place"] or "לא צוין",
                  "acts": n(r["k"]), "fams": n(fam_per.get(r["id"], 0))} for _, r in top_b.iterrows()]

    # ── KPIs ──────────────────────────────────────────────────────────
    used_share = n_used / n_parts * 100 if n_parts else 0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "licences": {"value": n_lic, "display": n(n_lic), "tone": "brand"},
        "codes": {"value": n_codes, "display": n(n_codes), "tone": "brand"},
        "places": {"value": n_places, "display": n(n_places), "tone": "brand"},
        "trade": {"value": n_trade, "display": n(n_trade), "tone": "brand"},
        "make": {"value": n_make, "display": n(n_make), "tone": "info"},
        "used": {"value": r1(used_share), "display": f"{used_share:.1f}%",
                 "tone": "warn" if used_share >= 50 else "info"},
        "avg": {"value": r1(avg_act), "display": f"{avg_act:.1f}", "tone": "brand"},
    }

    test_note = f" {n(n_test)} רישומי בדיקה הושמטו." if n_test else ""
    labels = {
        "lede": (f"מרשם משרד התחבורה של {n(total)} בתי מסחר, יבואנים ומפעלים בתחום מוצרי התעבורה ב-{n(n_places)} "
                 f"יישובים: חלקי חילוף חדשים, משופצים ומשומשים, אביזרים, שמנים וצמיגים, ולצדם מפעלים להתקנות, "
                 f"יצרני מרכבים ויצרני גרורים. כל עסק רשום לפעילות אחת או יותר — {n(n_lic)} רישומי פעילות "
                 f"ב-{n(n_codes)} סוגים.{test_note}"),
        "types_note": (f"מספר העסקים ומספר רישומי הפעילות לכל סוג עסק. בתי המסחר הם {pct(n_trade / total * 100 if total else 0)} "
                       f"מהעסקים."),
        "types_aria": "תרשים עמודות: עסקים ורישומי פעילות לפי סוג עסק.",
        "breadth_note": (f"לכמה פעילויות רשום כל עסק (חציון {med:g}). העמודה האחרונה מאגדת עסקים עם "
                         f"{n(BREADTH_CAP)} פעילויות ומעלה."),
        "breadth_aria": "תרשים עמודות: מספר העסקים לפי מספר הפעילויות שלהם.",
        "activities_note": (f"{n(TOP_ACTIVITIES)} הפעילויות הנפוצות מתוך {n(n_codes)}, לפי מספר העסקים הרשומים להן; "
                            f"הצבע מציין את משפחת הפעילות."),
        "activities_aria": "תרשים עמודות אופקי: הפעילויות הנפוצות לפי מספר עסקים.",
        "families_note": ("הפעילויות מקובצות למשפחות: חלקי חילוף לפי מצבם, אביזרים, צמיגים, התקנות בטיחות, "
                          "מרכבים ועוד. הטבעת הפנימית היא המשפחה, החיצונית הפעילות; לחיצה מתמקדת במשפחה."),
        "families_aria": "תרשים שמש: רישומי פעילות לפי משפחה ופעילות.",
        "parts_note": (f"{n(n_parts)} עסקים רשומים לחלקי חילוף. לכל סוג רכב — כמה עסקים מוכרים לו חלקים חדשים, "
                       f"משופצים או משומשים (עסק יכול להופיע ביותר ממצב אחד)."),
        "parts_aria": "תרשים עמודות מוערמות: עסקי חלקי חילוף לפי סוג רכב ומצב החלקים.",
        "districts_note": (f"העסקים לפי מחוז ולפי סוג עסק. "
                           + (f"{n(unassigned)} עסקים ללא יישוב או ביישוב שלא שויך למחוז אינם מוצגים." if unassigned else "")),
        "districts_aria": "תרשים עמודות מוערמות: עסקים לפי מחוז וסוג עסק.",
        "settlements_note": f"{n(len(top_pl))} היישובים עם מספר העסקים הגדול ביותר, לפי סוג עסק.",
        "settlements_aria": "תרשים עמודות מוערמות: היישובים המובילים לפי מספר עסקים וסוג עסק.",
        "used_note": (f"שיעור עסקי חלקי החילוף הרשומים גם לחלקים משומשים, ביישובים עם {n(MIN_PLACE_PARTS)} עסקי חלקים "
                      f"לפחות; הקו המקווקו הוא השיעור הכללי ({pct(nat_used * 100)})."),
        "used_aria": "תרשים עמודות: שיעור העסקים הרשומים לחלקים משומשים לפי יישוב.",
        "heat_note": "איזה חלק מהעסקים בכל מחוז רשום לכל משפחת פעילות — מבט על אופי הענף באזור.",
        "heat_aria": "מפת חום: שיעור העסקים הרשומים לכל משפחת פעילות לפי מחוז.",
        "cooc_note": (f"בין {n(len(top_codes_lab))} הפעילויות הנפוצות: איזה חלק מהעסקים הרשומים לפעילות שבשורה "
                      f"רשומים גם לפעילות שבעמודה."),
        "cooc_aria": "מפת חום: שיעור העסקים הרשומים לפעילות אחת שרשומים גם לאחרת.",
        "top_note": (f"{n(len(top_b))} העסקים הרשומים למספר הפעילויות הגדול ביותר, ומספר משפחות הפעילות שהם "
                     f"מכסים."),
        "top_caption": "העסקים עם מגוון הפעילויות הרחב ביותר: שם, סוג, יישוב, פעילויות ומשפחות.",
        "cond_heads": conds,
        "type_heads": [tlabel(t) for t in types_present],
    }
    tables = {
        "types": types_table,
        "breadth": [{"name": a, "count": n(b)} for a, b in zip(b_x, b_y)],
        "activities": act_table,
        "families": fam_table,
        "parts": parts_table,
        "districts": districts_table,
        "settlements": settlements_table,
        "used": used_table,
        "heat": heat_table,
        "cooc": co_table,
        "top": top_table,
    }
    charts = {
        "types": types_chart, "breadth": breadth_chart, "activities": act_chart, "families": sun,
        "parts": parts_chart, "districts": districts_chart, "settlements": settlements_chart,
        "used": used_chart, "heat": heat_chart, "cooc": cooc_chart,
        "family_order": fams_present,
    }
    flags = {"used": len(g) >= 3, "cooc": len(top_codes_lab) >= 3, "parts": bool(n_parts),
             "heat": len(dists) >= 2 and len(heat_f) >= 2}

    return {
        "agent_data": {
            "summary_he": (f"מרשם משרד התחבורה של {n(total)} בתי מסחר, יבואנים, מפעלים ויצרני מרכבים וגרורים "
                           f"ב-{n(n_places)} יישובים, ו-{n(n_codes)} סוגי הפעילות שלהם — מחלקי חילוף חדשים "
                           f"ומשומשים ועד התקנות בטיחות."),
            "dataset_kind": "registry",
            "suggested_tags": ["חלקי חילוף", "יבוא", "מרכבים", "גרורים", "אביזרי רכב", "משרד התחבורה"],
            "related_ids": ["392abd0a-64f6-4c18-9d56-0111001411e6",
                            "35c791ca-8db2-4657-8c6f-eb092147a6bb",
                            "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
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
