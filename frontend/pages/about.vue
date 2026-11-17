<script setup lang="ts">
import { SITE_URL } from "~/utils/paths";

useSeo({
  title: "אודות govil.ai — מיזם אזרחי להנגשת מאגרי המידע הממשלתיים הפתוחים",
  description:
    "govil.ai הוא מיזם אזרחי עצמאי המנגיש ומנתח את מאגרי המידע הממשלתיים הפתוחים של ישראל. הכירו את החזון, איך האתר עובד, בקרת האיכות והצוות שמאחורי הפרויקט.",
  path: "/about/",
  keywords: [
    "אודות הפרויקט",
    "איך זה עובד",
    "מידע ממשלתי פתוח",
    "שקיפות שלטונית",
    "ניתוח נתונים אזרחי",
    "data.gov.il",
    "E-E-A-T",
  ],
  breadcrumbs: [
    { name: "ראשי", url: `${SITE_URL}/` },
    { name: "אודות", url: `${SITE_URL}/about/` },
  ],
});
const pipeline = [
  {
    title: "איתור עדכונים במקור",
    body: "סורק בודק כל שעה בימי חול, משעות הבוקר עד הערב, את פורטל המידע הממשלתי data.gov.il, את בנק ישראל ואת הלשכה המרכזית לסטטיסטיקה, ומזהה מאגרים חדשים ועדכוני נתונים במאגרים קיימים.",
  },
  {
    title: "מתכון חישוב לכל מאגר",
    body: "לכל מאגר נכתב פעם אחת מתכון חישוב: קוד שקובע אילו מדדים, גרפים, מפות וטבלאות יוצגו. המתכון נכתב בעזרת כלי בינה מלאכותית אחרי בחינה של הנתונים המלאים, ועובר בדיקות אוטומטיות לפני שהוא עולה לאתר.",
  },
  {
    title: "חישוב מחדש בכל עדכון",
    body: "כשהנתונים במקור מתעדכנים, המתכון רץ מחדש על הקובץ המלא, בלי מודל בינה מלאכותית. כל מספר, גרף ותובנה בעמוד מחושבים מהנתונים עצמם, ולכן העמוד משקף את הגרסה העדכנית.",
  },
  {
    title: "בקרה ופרסום",
    body: "כל עמוד עובר בדיקת מבנה ובדיקת תקינות אוטומטית לפני פרסום. עמוד שלא עבר את הבדיקה לא מתפרסם: העמוד הקודם נשאר, והתקלה נרשמת לטיפול.",
  },
];

const trust = [
  {
    title: "עיגון בנתונים",
    body: "כל מספר, גרף ותובנה על הנתונים נגזרים ישירות מרשומות המקור, ולא נכתבים ביד.",
  },
  {
    title: "קישור ישיר למקור",
    body: "כל עמוד מאגר מקשר להורדת הקובץ המקורי ממקור הנתונים, כדי שכל אחד יוכל לאמת ולהצליב.",
  },
  {
    title: "מאגרים קשורים",
    body: "אלגוריתם קבוע משווה את התוכן והנושאים של המאגרים ומציע בכל עמוד מאגרים משלימים, מאותו משרד או מתחומים משיקים.",
  },
];
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <div class="text-xs text-subtle mb-2">
      <NuxtLink to="/">ראשי</NuxtLink> › אודות
    </div>

    <article class="max-w-3xl prose-gov">
      <h1 class="font-display">אודות govil.ai</h1>
      <p class="text-subtle text-sm">עודכן לאחרונה: 17 בנובמבר 2026</p>
      <p class="mt-4 text-lg text-ink/80 leading-relaxed">
        govil.ai הוא מיזם אזרחי-טכנולוגי עצמאי שמטרתו לפתוח, להסביר ולהנגיש את
        מאגרי המידע הממשלתיים של ישראל לכל אזרח, חוקרת, עיתונאי ובעל עסק — בשפה
        ברורה, עם גרפים אינטראקטיביים ותובנות מעשיות.
      </p>

      <div class="card p-5 my-6 bg-brand-50/50 border-brand-100">
        <h2 class="font-display text-base text-ink m-0 mb-1">
          החזון שלנו: דמוקרטיזציה של המידע הציבורי
        </h2>
        <p class="text-ink/85 leading-relaxed m-0 text-sm">
          מידע ממשלתי נאסף וממומן מכספי הציבור ושייך לציבור. כדי שמידע פתוח באמת
          ישרת את החברה, הוא חייב להיות מובן, מחובר וזמין בלחיצת כפתור — לא קבור
          בקובצי נתונים מורכבים.
        </p>
      </div>

      <h2 class="font-display mt-10">הפער שאנחנו מגשרים עליו</h2>
      <p class="text-ink/85 leading-relaxed">
        ממשלת ישראל מפרסמת אלפי מאגרי מידע בפורטל הממשלתי הרשמי data.gov.il. עם
        זאת, מרבית המאגרים מועלים בפורמטים גולמיים (כגון קובצי CSV, XML, JSON
        ומערכות API) — ללא הסבר נלווה, עם שמות עמודות טכניים, וללא הקשר תמטי או
        ויזואליזציה בסיסית.
      </p>
      <p class="text-ink/85 leading-relaxed">
        כתוצאה מכך, המידע אמנם <strong>פתוח להורדה</strong> אך אינו
        <strong>נגיש להבנה</strong>. רק מי ששולטים בכלים אנליטיים מתקדמים או
        בתכנות יכלו להפיק ממנו ערך. govil.ai הופך כל מאגר לעמוד נחיתה עשיר, מובן
        ומאומת — מוכן לקריאה, לחקירה ולשיתוף.
      </p>

      <h2 id="how-it-works" class="font-display mt-10">איך זה עובד</h2>
      <p class="text-ink/85 leading-relaxed">
        עמודי המאגרים נבנים מחישוב קבוע שרץ מחדש על הנתונים הרשמיים בכל פעם שהם
        מתעדכנים. כך זה נראה, שלב אחר שלב:
      </p>
      <ol class="list-none p-0 m-0 space-y-3 mt-4">
        <li v-for="(step, i) in pipeline" :key="i" class="card p-5 flex gap-4">
          <div
            class="flex-none w-10 h-10 rounded-gov-pill bg-brand-50 text-brand-700 font-display grid place-items-center"
          >
            {{ i + 1 }}
          </div>
          <div class="flex-1">
            <h3 class="font-display text-ink m-0 mb-1 text-base">
              {{ step.title }}
            </h3>
            <p class="text-ink/85 leading-relaxed m-0 text-sm">
              {{ step.body }}
            </p>
          </div>
        </li>
      </ol>

      <h2 class="font-display mt-10">עקרונות המהימנות</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
        <div v-for="(t, i) in trust" :key="i" class="card p-5">
          <h3 class="font-display text-ink m-0 mb-1 text-base">
            <img
              src="/icons/circle-check.svg"
              alt=""
              class="inline w-4 h-4 ms-1 align-middle opacity-80"
            />
            {{ t.title }}
          </h3>
          <p class="text-sm text-ink/80 m-0 leading-relaxed">{{ t.body }}</p>
        </div>
        <div class="card p-5">
          <h3 class="font-display text-ink m-0 mb-1 text-base">
            <img
              src="/icons/circle-check.svg"
              alt=""
              class="inline w-4 h-4 ms-1 align-middle opacity-80"
            />
            שקיפות ופרטיות
          </h3>
          <p class="text-sm text-ink/80 m-0 leading-relaxed">
            האתר פתוח לעיון ללא הרשמה. פירוט ב<NuxtLink
              to="/privacy/"
              class="text-brand-700 underline"
              >מדיניות הפרטיות</NuxtLink
            >
            ובעמוד
            <NuxtLink to="/faq/" class="text-brand-700 underline"
              >שאלות נפוצות</NuxtLink
            >. מצאתם טעות?
            <NuxtLink to="/contact/" class="text-brand-700 underline"
              >דווחו לנו</NuxtLink
            >
            ונתקן.
          </p>
        </div>
      </div>

      <h2 class="font-display mt-10">מגבלות</h2>
      <ul class="list-disc ps-6 space-y-2 text-ink/85 leading-relaxed">
        <li>
          בין עדכון קובץ במקור לבין עדכון העמוד באתר עשויות לעבור כמה שעות,
          ובסוף השבוע עד יום וחצי.
        </li>
        <li>
          כשהחישוב נכשל (למשל כי מבנה הנתונים במקור השתנה), העמוד הקודם נשאר
          באוויר עד שהחישוב מתוקן, ולכן הוא עשוי לפגר אחרי המקור.
        </li>
        <li>
          התוכן נועד להנגשת מידע ולמחקר אזרחי. לשימוש רשמי או משפטי יש להצליב עם
          קובץ המקור.
        </li>
      </ul>

      <h2 class="font-display mt-10">חדשות מהנתונים</h2>
      <p class="text-ink/85 leading-relaxed">
        מדור
        <NuxtLink to="/news/" class="text-brand-700 underline font-medium"
          >החדשות</NuxtLink
        >
        מספר מה השתנה במאגרים: שיא חדש, ירידה חדה או מדד שפורסם זה עתה. כל מספר
        בכתבה נשלף מהנתונים הרשמיים, וכל כתבה מקשרת לעמוד המאגר שעליו היא נשענת.
        איך נבחר סיפור, איך נבדקת כתבה ואיך מתקנים טעות מוסבר בעמוד
        <NuxtLink to="/news/about/" class="text-brand-700 underline font-medium"
          >איך נכתבות החדשות</NuxtLink
        >.
      </p>

      <h2 class="font-display mt-10">קהלי היעד של האתר</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
        <div class="card p-5">
          <h3 class="font-display text-ink m-0 mb-1 text-base">
            אזרחים ומקבלי החלטות
          </h3>
          <p class="text-sm text-ink/80 m-0 leading-relaxed">
            להבין תהליכים ממשלתיים, הקצאת משאבים ונתוני שירות ציבורי בנושאים
            שנוגעים לחיי היומיום — בריאות, חינוך, תחבורה וסביבה.
          </p>
        </div>
        <div class="card p-5">
          <h3 class="font-display text-ink m-0 mb-1 text-base">
            עיתונאים ואנשי תקשורת
          </h3>
          <p class="text-sm text-ink/80 m-0 leading-relaxed">
            תובנות מעובדות, זוויות לסיפורים עיתונאיים, הפקת גרפים וקישור ישיר
            למקור הממשלתי לצורך הצלבה ואימות עובדתי.
          </p>
        </div>
        <div class="card p-5">
          <h3 class="font-display text-ink m-0 mb-1 text-base">
            חוקרים, אקדמיה וסטודנטים
          </h3>
          <p class="text-sm text-ink/80 m-0 leading-relaxed">
            סקירה מהירה של מבנה הנתונים, היקף הרשומות, כיסוי זמני וגיאוגרפי,
            וזיהוי מאגרים קשורים למחקר אמפירי.
          </p>
        </div>
        <div class="card p-5">
          <h3 class="font-display text-ink m-0 mb-1 text-base">
            יזמים ומפתחים
          </h3>
          <p class="text-sm text-ink/80 m-0 leading-relaxed">
            הבנת הפוטנציאל היישומי של מאגרי מידע פתוחים לצורך בניית שירותים,
            מוצרים דיגיטליים ופתרונות מבוססי נתונים.
          </p>
        </div>
      </div>

      <h2 class="font-display mt-10">עצמאות משפטית והבהרה מוסדית</h2>
      <div class="card p-5 bg-surface-alt border-rule">
        <p class="text-ink/85 leading-relaxed m-0 text-sm">
          <strong
            >govil.ai אינו אתר ממשלתי רשמי ואינו פועל מטעם ממשלת ישראל</strong
          >
          או מי ממשרדיה ומוסדותיה. הנתונים המקוריים הם רכוש המדינה והופקו
          מהמקורות הממשלתיים הרשמיים. העיבודים, התובנות והגרפים באתר מהווים כלי
          עזר אזרחי ומחקרי. לעיון מפורט, קראו את עמוד ה-<NuxtLink
            to="/disclaimer/"
            class="text-brand-700 underline font-medium"
            >הבהרה המשפטית</NuxtLink
          >
          ואת
          <NuxtLink to="/terms/" class="text-brand-700 underline font-medium"
            >תנאי השימוש</NuxtLink
          >.
        </p>
      </div>

      <h2 class="font-display mt-10">מי עומד מאחורי הפרויקט?</h2>
      <p class="text-ink/85 leading-relaxed">
        govil.ai מפותח ומתוחזק על ידי אנשי פיתוח, מדעני נתונים ופעילי שקיפות
        אזרחית בישראל, מתוך אמונה כי מידע ציבורי נגיש הוא אבן יסוד בחברה
        דמוקרטית מודרנית ומתקדמת.
      </p>

      <h2 class="font-display mt-10">יצירת קשר ומשוב</h2>
      <p class="text-ink/85 leading-relaxed">
        מצאתם אי-דיוק בנתונים? יש לכם רעיון לשיפור או מאגר שתרצו שננגיש? נשמח
        לשמוע מכם!
      </p>
      <div class="flex flex-wrap items-center gap-4 mt-4">
        <NuxtLink to="/contact/" class="btn-primary">
          לטופס יצירת קשר
        </NuxtLink>
        <a
          href="mailto:contact@govil.ai"
          class="text-brand-700 font-mono text-sm underline"
        >
          contact@govil.ai
        </a>
      </div>
    </article>
  </div>
</template>
