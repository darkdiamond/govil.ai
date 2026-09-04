<script setup lang="ts">
useSeo({
  title: 'אודות govil.ai — מיזם אזרחי להנגשת מאגרי המידע הממשלתיים הפתוחים',
  description: 'govil.ai הוא מיזם אזרחי עצמאי המנגיש ומנתח את מאגרי המידע הממשלתיים הפתוחים של ישראל. הכירו את החזון, מתודולוגיית ניתוח הנתונים, בקרת האיכות והצוות שמאחורי הפרויקט.',
  path: '/about/',
  keywords: ['אודות הפרויקט', 'מידע ממשלתי פתוח', 'שקיפות שלטונית', 'ניתוח נתונים אזרחי', 'data.gov.il', 'E-E-A-T'],
  breadcrumbs: [
    { name: 'ראשי', url: 'https://govil.ai/' },
    { name: 'אודות', url: 'https://govil.ai/about/' },
  ],
})
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <div class="text-xs text-subtle mb-2">
      <NuxtLink to="/">ראשי</NuxtLink> › אודות
    </div>

    <article class="max-w-3xl prose-gov">
      <h1 class="font-display">אודות govil.ai</h1>
      <p class="text-subtle text-sm">עודכן לאחרונה: 3 בספטמבר 2026</p>
      <p class="mt-4 text-lg text-ink/80 leading-relaxed">
        govil.ai הוא מיזם אזרחי-טכנולוגי עצמאי שמטרתו לפתוח, להסביר ולהנגיש את מאגרי המידע הממשלתיים של ישראל לכל אזרח, חוקרת, עיתונאי ובעל עסק — בשפה ברורה, עם גרפים אינטראקטיביים ותובנות מעשיות.
      </p>

      <div class="card p-5 my-6 bg-brand-50/50 border-brand-100">
        <h2 class="font-display text-base text-ink m-0 mb-1">החזון שלנו: דמוקרטיזציה של המידע הציבורי</h2>
        <p class="text-ink/85 leading-relaxed m-0 text-sm">
          מידע ממשלתי נאסף וממומן מכספי הציבור ושייך לציבור. כדי שמידע פתוח באמת ישרת את החברה, הוא חייב להיות מובן, מחובר וזמין בלחיצת כפתור — לא קבור בקובצי נתונים מורכבים.
        </p>
      </div>

      <h2 class="font-display mt-10">הפער שאנחנו מגשרים עליו</h2>
      <p class="text-ink/85 leading-relaxed">
        ממשלת ישראל מפרסמת אלפי מאגרי מידע בפורטל הממשלתי הרשמי data.gov.il. עם זאת, מרבית המאגרים מועלים בפורמטים גולמיים (כגון קובצי CSV, XML, JSON ומערכות API) — ללא הסבר נלווה, עם שמות עמודות טכניים, וללא הקשר תמטי או ויזואליזציה בסיסית.
      </p>
      <p class="text-ink/85 leading-relaxed">
        כתוצאה מכך, המידע אמנם <strong>פתוח להורדה</strong> אך אינו <strong>נגיש להבנה</strong>. רק מי ששולטים בכלים אנליטיים מתקדמים או בתכנות יכלו להפיק ממנו ערך. govil.ai הופך כל מאגר לעמוד נחיתה עשיר, מובן ומאומת — מוכן לקריאה, לחקירה ולשיתוף.
      </p>

      <h2 class="font-display mt-10">מתודולוגיית הניתוח ובקרת האיכות</h2>
      <p class="text-ink/85 leading-relaxed">
        על מנת לספק ערך מהימן ומעמיק, המערכת שלנו פועלת על פי פרוטוקול אנליטי רב-שלבי:
      </p>
      <ul class="list-disc ps-6 space-y-2 text-ink/85 leading-relaxed">
        <li>
          <strong>סריקה מובנית ואימות מקור:</strong> דגימה שוטפת של ה-CKAN API הממשלתי, זיהוי מאגרים חדשים ועדכונים, ואימות תקינות הקבצים והרישיונות.
        </li>
        <li>
          <strong>ניתוח סטטיסטי מעמיק:</strong> חילוץ מדדי מפתח (KPIs), זיהוי חלוקות גיאוגרפיות, מגמות זמניות (Time-series) ופילוח לפי משתנים מרכזיים.
        </li>
        <li>
          <strong>ויזואליזציה מותאמת:</strong> הפקת מפות אינטראקטיביות מבוססות קואורדינטות, גרפים מותאמים (עמודות, עוגות, סדרות זמן) וטבלאות סינון ייעודיות באמצעות ספריות מתקדמות (ECharts, Leaflet).
        </li>
        <li>
          <strong>הצלבה וקישוריות תמטית:</strong> אלגוריתם קישוריות תוכן מזהה מאגרים משלימים מאותו משרד או בנושאים משיקים, ומחבר ביניהם כדי לספק תמונה רחבה.
        </li>
        <li>
          <strong>פיקוח ובקרה מתמדת:</strong> התקצירים מעוגנים תמיד ברשומות המקור. קיים מנגנון דיווח קהילתי לבדיקה ותיקון מיידי של אי-דיוקים.
        </li>
      </ul>

      <h2 class="font-display mt-10">קהלי היעד של האתר</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
        <div class="card p-5">
          <h3 class="font-display text-ink m-0 mb-1 text-base">אזרחים ומקבלי החלטות</h3>
          <p class="text-sm text-ink/80 m-0 leading-relaxed">
            להבין תהליכים ממשלתיים, הקצאת משאבים ונתוני שירות ציבורי בנושאים שנוגעים לחיי היומיום — בריאות, חינוך, תחבורה וסביבה.
          </p>
        </div>
        <div class="card p-5">
          <h3 class="font-display text-ink m-0 mb-1 text-base">עיתונאים ואנשי תקשורת</h3>
          <p class="text-sm text-ink/80 m-0 leading-relaxed">
            תובנות מעובדות, זוויות לסיפורים עיתונאיים, הפקת גרפים וקישור ישיר למקור הממשלתי לצורך הצלבה ואימות עובדתי.
          </p>
        </div>
        <div class="card p-5">
          <h3 class="font-display text-ink m-0 mb-1 text-base">חוקרים, אקדמיה וסטודנטים</h3>
          <p class="text-sm text-ink/80 m-0 leading-relaxed">
            סקירה מהירה של מבנה הנתונים, היקף הרשומות, כיסוי זמני וגיאוגרפי, וזיהוי מאגרים קשורים למחקר אמפירי.
          </p>
        </div>
        <div class="card p-5">
          <h3 class="font-display text-ink m-0 mb-1 text-base">יזמים ומפתחים</h3>
          <p class="text-sm text-ink/80 m-0 leading-relaxed">
            הבנת הפוטנציאל היישומי של מאגרי מידע פתוחים לצורך בניית שירותים, מוצרים דיגיטליים ופתרונות מבוססי נתונים.
          </p>
        </div>
      </div>

      <h2 class="font-display mt-10">עצמאות משפטית והבהרה מוסדית</h2>
      <div class="card p-5 bg-surface-alt border-rule">
        <p class="text-ink/85 leading-relaxed m-0 text-sm">
          <strong>govil.ai אינו אתר ממשלתי רשמי ואינו פועל מטעם ממשלת ישראל</strong> או מי ממשרדיה ומוסדותיה.
          הנתונים המקוריים הם רכוש המדינה והופקו מהמקורות הממשלתיים הרשמיים.
          העיבודים, התובנות והגרפים באתר מהווים כלי עזר אזרחי ומחקרי.
          לעיון מפורט, קראו את עמוד ה-<NuxtLink to="/disclaimer/" class="text-brand-700 underline font-medium">הבהרה המשפטית</NuxtLink> ואת <NuxtLink to="/terms/" class="text-brand-700 underline font-medium">תנאי השימוש</NuxtLink>.
        </p>
      </div>

      <h2 class="font-display mt-10">מי עומד מאחורי הפרויקט?</h2>
      <p class="text-ink/85 leading-relaxed">
        govil.ai מפותח ומתוחזק על ידי אנשי פיתוח, מדעני נתונים ופעילי שקיפות אזרחית בישראל, מתוך אמונה כי מידע ציבורי נגיש הוא אבן יסוד בחברה דמוקרטית מודרנית ומתקדמת.
      </p>

      <h2 class="font-display mt-10">יצירת קשר ומשוב</h2>
      <p class="text-ink/85 leading-relaxed">
        מצאתם אי-דיוק בנתונים? יש לכם רעיון לשיפור או מאגר שתרצו שננגיש? נשמח לשמוע מכם!
      </p>
      <div class="flex flex-wrap items-center gap-4 mt-4">
        <NuxtLink to="/contact/" class="btn-primary">
          לטופס יצירת קשר
        </NuxtLink>
        <a href="mailto:contact@govil.ai" class="text-brand-700 font-mono text-sm underline">
          contact@govil.ai
        </a>
      </div>
    </article>
  </div>
</template>
