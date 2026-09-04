<script setup lang="ts">
useSeo({
  title: 'מתודולוגיית העבודה — מחקר וניתוח מאגרי data.gov.il',
  description: 'כיצד פועלת פלטפורמת govil.ai: איסוף נתונים ממאגרי data.gov.il, ניתוח סטטיסטי, הפקת גרפים ומפות אינטראקטיביות, ובקרת איכות קפדנית להנגשת מידע ציבורי.',
  path: '/how-it-works/',
  keywords: ['מתודולוגיית מחקר נתונים', 'ניתוח מאגרי מידע', 'data.gov.il', 'ויזואליזציה אינטראקטיבית', 'שקיפות ציבורית'],
  breadcrumbs: [
    { name: 'ראשי', url: 'https://govil.ai/' },
    { name: 'איך זה עובד', url: 'https://govil.ai/how-it-works/' },
  ],
})

const pipeline = [
  {
    title: 'איתור וקליטת המאגר (Data Ingestion)',
    body: 'סורק ייעודי מנטר את עדכוני ה-CKAN API של פורטל המידע הממשלתי data.gov.il באופן שוטף, מאתר קבצים חדשים ועדכונים במאגרים קיימים, ומבצע ולידציה של מבנה הנתונים והרישיונות.',
  },
  {
    title: 'מחקר מעמיק וניתוח סטטיסטי (Statistical Analysis)',
    body: 'מערכת הניתוח קוראת את קובצי הנתונים המלאים (CSV, JSON, XML), מבצעת אגרגציות כמותיות, מזהה שדות מפתח, מגמות כרונולוגיות, פילוחים דמוגרפיים או גיאוגרפיים, והקשר רגולטורי ציבורי.',
  },
  {
    title: 'ניסוח תקציר והפקת ויזואליזציה מותאמת (Data Synthesis & Visualization)',
    body: 'המערכת מפיקה כרטיסי מדדים (KPIs), תקציר בשפה בהירה ותובנות מרכזיות. במקביל מופקים רכיבים גרפיים אינטראקטיביים — מפות מבוססות Leaflet, גרפי ECharts וטבלאות סינון ייעודיות.',
  },
  {
    title: 'בקרת איכות ופרסום שקוף (Quality Assurance & Attribution)',
    body: 'כל עמוד נבדק לוולידציה מבנית, קישוריות למקור הרשמי ותאימות תקני נגישות (IS 5568 / WCAG 2.0 AA). המידע מתעדכן בהתאם לגרסאות הממשלתיות החדשות.',
  },
]

const trust = [
  {
    title: 'עיגון עובדתי מלא',
    body: 'כל מספר, תובנה או גרף מעוגנים ישירות ברשומות המקור של המאגר הממשלתי. אין מקום להשערות שאינן מבוססות בנתונים הרשמיים.',
  },
  {
    title: 'קישור ישיר לקובץ המקור',
    body: 'כל עמוד מאגר כולל קישור ישיר להורדת הקובץ המקורי מ-data.gov.il, ומאפשר לכל אזרח, עיתונאי או חוקר לאמת ולהצליב את הנתונים.',
  },
  {
    title: 'סנכרון מתמשך',
    body: 'כל עדכון של נתונים במקור הממשלתי מפעיל סריקה וניתוח מחודש, כך שהתצוגות משקפות תמיד את הסטטוס העדכני ביותר של המידע הממשלתי.',
  },
  {
    title: 'שקיפות ופרטיות',
    body: 'האתר פתוח לעיון חופשי ללא חומת הרשמה וללא איסוף מידע אישי מזהה בעת הגלישה. פירוט מלא מופיע בעמודי המדיניות המשפטית והפרטיות.',
  },
]
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <div class="text-xs text-subtle mb-2">
      <NuxtLink to="/">ראשי</NuxtLink> › איך זה עובד
    </div>

    <article class="max-w-4xl">
      <h1 class="font-display">איך govil.ai עובד</h1>
      <p class="text-subtle text-sm">עודכן לאחרונה: 3 בספטמבר 2026</p>
      <p class="mt-4 text-lg text-ink/80 leading-relaxed max-w-3xl">
        המערכת של govil.ai משלבת כלים מתקדמים לעיבוד נתונים, אלגוריתמיקה אנליטית וסיוע של בינה מלאכותית, הפועלים תחת מתודולוגיית עבודה מוגדרת ובקרת איכות מתמדת כדי להפוך קובצי מידע ממשלתיים גולמיים לתובנות ברורות ונגישות לציבור.
      </p>

      <!-- Pipeline steps -->
      <section class="mt-10">
        <h2 class="font-display">ארבעת שלבי המתודולוגיה</h2>
        <ol class="list-none p-0 m-0 space-y-3 mt-4">
          <li
            v-for="(step, i) in pipeline"
            :key="i"
            class="card p-5 flex gap-4"
          >
            <div class="flex-none w-10 h-10 rounded-gov-pill bg-brand-50 text-brand-700 font-display grid place-items-center">
              {{ i + 1 }}
            </div>
            <div class="flex-1">
              <h3 class="font-display text-ink m-0 mb-1">{{ step.title }}</h3>
              <p class="text-ink/85 leading-relaxed m-0">{{ step.body }}</p>
            </div>
          </li>
        </ol>
      </section>

      <!-- Trust principles -->
      <section class="mt-12">
        <h2 class="font-display">עקרונות המהימנות והאחריות</h2>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
          <div v-for="(t, i) in trust" :key="i" class="card p-5">
            <h3 class="font-display text-ink m-0 mb-2 text-base">
              <img src="/icons/circle-check.svg" alt="" class="inline w-4 h-4 ms-1 align-middle opacity-80" />
              {{ t.title }}
            </h3>
            <p class="text-ink/80 leading-relaxed m-0 text-sm">{{ t.body }}</p>
          </div>
        </div>
      </section>

      <!-- Limits -->
      <section class="mt-12">
        <h2 class="font-display">מגבלות והבהרות מקצועיות</h2>
        <ul class="space-y-2 text-ink/85 leading-relaxed list-disc ps-6">
          <li>מאגרים ללא מבנה נתונים מוגדר (כגון קובצי PDF סרוקים ללא OCR תקין במקור הממשלתי) יוצגו עם פירוט תיאורי בלבד.</li>
          <li>ייתכן פער זמנים בין רגע עדכון קובץ ב-data.gov.il לבין השלמת הסריקה והאינדוקס באתר.</li>
          <li>התוכן מיועד להנגשת מידע ולמחקר אזרחי — לכל שימוש פורמלי או משפטי יש לעיין ולהצליב עם קובץ המקור הרשמי.</li>
        </ul>
      </section>

      <div class="mt-12 flex flex-wrap gap-3">
        <NuxtLink to="/datasets/" class="btn-primary">
          <img src="/icons/database.svg" alt="" class="w-4 h-4 invert opacity-90" />
          עיון במאגרים
        </NuxtLink>
        <NuxtLink to="/faq/" class="btn-ghost">
          שאלות נפוצות
        </NuxtLink>
        <NuxtLink to="/disclaimer/" class="btn-ghost">
          הבהרה משפטית
        </NuxtLink>
      </div>
    </article>
  </div>
</template>
