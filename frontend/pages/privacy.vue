<script setup lang="ts">
const lastUpdated = '3 בספטמבר 2026'

// Deployment-specific analytics IDs (empty in forks/local builds — the
// services aren't loaded then either; see plugins/*.client.ts).
const { gtag, adsenseId } = useRuntimeConfig().public
const gtagId = gtag?.id || ''

useSeo({
  title: 'מדיניות פרטיות באתר govil.ai',
  description: 'מדיניות הפרטיות של govil.ai — אילו נתונים אנו אוספים, באילו שירותי צד שלישי אנו משתמשים (Google Analytics, Google AdSense), ואילו זכויות עומדות לכם.',
  path: '/privacy/',
  keywords: ['מדיניות פרטיות', 'cookies', 'Google Analytics', 'Google AdSense', 'חוק הגנת הפרטיות'],
  breadcrumbs: [
    { name: 'ראשי', url: 'https://govil.ai/' },
    { name: 'מדיניות פרטיות', url: 'https://govil.ai/privacy/' },
  ],
})
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <div class="text-xs text-subtle mb-2">
      <NuxtLink to="/">ראשי</NuxtLink> › מדיניות פרטיות
    </div>

    <article class="max-w-3xl prose-gov">
      <h1 class="font-display">מדיניות פרטיות</h1>
      <p class="text-subtle text-sm">עודכן לאחרונה: {{ lastUpdated }}</p>

      <h2 class="font-display mt-8">1. מי אנחנו</h2>
      <p class="text-ink/85 leading-relaxed">
        govil.ai הוא פרויקט עצמאי שמנגיש את מאגרי המידע הציבוריים של ממשלת ישראל
        (data.gov.il) באמצעות תקצירים, תובנות וויזואליזציות שנכתבו על ידי בינה
        מלאכותית. <strong>האתר אינו אתר ממשלתי רשמי</strong>, ואינו פועל מטעם ממשלת ישראל,
        משרדיה או רשויותיה. בכל שאלה הנוגעת למדיניות זו ניתן לפנות אלינו דרך
        <NuxtLink to="/contact/" class="text-brand-700 underline">טופס יצירת הקשר</NuxtLink>.
      </p>

      <h2 class="font-display mt-8">2. אילו נתונים אנו אוספים</h2>
      <p class="text-ink/85 leading-relaxed">
        האתר מתארח על Firebase Hosting של Google. כמו אצל כל ספק אירוח ענן, יומני
        השרת כוללים לכל בקשה את כתובת ה-IP של המבקר, סוג הדפדפן ומערכת ההפעלה
        (User-Agent), עמוד ההפניה (Referer) וזמן הגישה. נתונים אלה נשמרים לצורך
        אבטחה ותפעול בלבד.
      </p>
      <p class="text-ink/85 leading-relaxed">
        בנוסף אנו משתמשים בשני שירותי צד שלישי של Google שמציבים cookies בדפדפן:
      </p>
      <ul class="text-ink/85 leading-relaxed list-disc ps-6 space-y-2">
        <li>
          <strong>Google Analytics 4</strong><template v-if="gtagId"> (מזהה <code>{{ gtagId }}</code>)</template> — לצורך
          הבנת דפוסי שימוש מצרפיים: כמה מבקרים, אילו עמודים נצפים, ממה הם הגיעו
          לאתר. הנתונים מצרפיים ואינם משויכים לשם.
        </li>
        <li>
          <strong>Google AdSense</strong><template v-if="adsenseId"> (מזהה <code>{{ adsenseId }}</code>)</template> —
          להצגת פרסומות שמממנות את התפעול של האתר. AdSense עשוי להציג פרסומות
          מותאמות אישית בהתאם לעדפות המבקר אצל Google.
        </li>
      </ul>
      <p class="text-ink/85 leading-relaxed">
        <strong>איננו</strong> מפעילים מערכת חברים, אינך נדרש להירשם, ואיננו אוספים פרטים
        אישיים מזהים (שם, טלפון, מספר תעודת זהות) דרך גלישה רגילה. הפרט היחיד
        שאנו עשויים לקבל ישירות הוא דוא״ל שאתם שולחים מיוזמתכם דרך טופס
        <NuxtLink to="/contact/" class="text-brand-700 underline">״צור קשר״</NuxtLink> —
        ובמקרה זה הוא משמש אך ורק לצורך מענה לפנייה. הטופס מופעל באמצעות שירות
        Formspree, וחל עליו גם
        <a href="https://formspree.io/legal/privacy-policy/" target="_blank" rel="noopener" class="text-brand-700 underline">מדיניות הפרטיות של Formspree</a>.
      </p>

      <h2 class="font-display mt-8">3. Cookies וטכנולוגיות דומות</h2>
      <p class="text-ink/85 leading-relaxed">
        כתוצאה משירותי הצד השלישי שלעיל מוצבות בדפדפן שלכם cookies מהמשפחות
        הבאות:
      </p>
      <ul class="text-ink/85 leading-relaxed list-disc ps-6 space-y-2">
        <li><code>_ga</code>, <code>_ga_*</code> — Google Analytics, מזהה ביקורים מצרפי.</li>
        <li><code>__gads</code>, <code>__gpi</code>, <code>IDE</code>, <code>NID</code> — Google AdSense / DoubleClick, התאמת פרסומות ומדידת ביצועים.</li>
      </ul>
      <p class="text-ink/85 leading-relaxed">
        ניתן לשלוט במידת ההתאמה האישית של פרסומות Google דרך
        <a href="https://adssettings.google.com" target="_blank" rel="noopener" class="text-brand-700 underline">הגדרות הפרסום של Google</a>,
        ולהפסיק לחלוטין את שליחת הנתונים ל-Google Analytics באמצעות
        <a href="https://tools.google.com/dlpage/gaoptout" target="_blank" rel="noopener" class="text-brand-700 underline">תוסף ביטול ההסכמה ל-GA</a>.
        בנוסף, רוב הדפדפנים מאפשרים חסימה כללית של cookies של צד שלישי דרך
        ההגדרות.
      </p>

      <h2 class="font-display mt-8">4. שירותי צד שלישי</h2>
      <p class="text-ink/85 leading-relaxed">
        השימוש בשירותי צד שלישי כפוף למדיניות הפרטיות שלהם:
      </p>
      <ul class="text-ink/85 leading-relaxed list-disc ps-6 space-y-2">
        <li>
          <a href="https://policies.google.com/privacy" target="_blank" rel="noopener" class="text-brand-700 underline">Google</a>
          — חל על Firebase Hosting, Google Analytics ו-Google AdSense.
        </li>
        <li>
          <a href="https://formspree.io/legal/privacy-policy/" target="_blank" rel="noopener" class="text-brand-700 underline">Formspree</a>
          — שירות עיבוד טפסי דוא״ל המפעיל את עמוד ״צור קשר״.
        </li>
      </ul>

      <h2 class="font-display mt-8">5. בסיס חוקי לעיבוד</h2>
      <p class="text-ink/85 leading-relaxed">
        עיבוד הנתונים נעשה במסגרת חוק הגנת הפרטיות, התשמ״א-1981, ובהתאם להוראות
        רשם מאגרי המידע. למבקרים מהאיחוד האירופי או מהממלכה המאוחדת, הבסיס המשפטי
        לעיבוד הוא הסכמה (סעיף 6(1)(a) ל-GDPR) לעיבוד הקשור בפרסום מותאם אישית,
        ואינטרס לגיטימי (סעיף 6(1)(f)) למדידת שימוש כללית באתר.
      </p>

      <h2 class="font-display mt-8">6. זכויות המשתמש</h2>
      <p class="text-ink/85 leading-relaxed">
        עומדות לכם הזכויות הבאות בנוגע למידע שייתכן שעבר עיבוד מהביקור באתר:
      </p>
      <ul class="text-ink/85 leading-relaxed list-disc ps-6 space-y-2">
        <li>זכות עיון במידע שנשמר.</li>
        <li>זכות לתיקון מידע שגוי.</li>
        <li>זכות למחיקת מידע ולביטול הסכמה לעיבוד עתידי.</li>
        <li>זכות הגשת תלונה לרשות להגנת הפרטיות (israel.gov.il/he/departments/the_privacy_protection_authority).</li>
      </ul>
      <p class="text-ink/85 leading-relaxed">
        למימוש זכות כלשהי השאירו לנו פנייה דרך
        <NuxtLink to="/contact/" class="text-brand-700 underline">טופס יצירת הקשר</NuxtLink>.
        אנו נשיב תוך 30 יום.
      </p>

      <h2 class="font-display mt-8">7. אבטחת מידע</h2>
      <p class="text-ink/85 leading-relaxed">
        כל התעבורה לאתר מאובטחת ב-HTTPS. האתר עצמו הוא סטטי — אין לנו מסד נתונים
        משלנו, אין שמירה של פרופילי משתמשים, ואין חשבונות. הנתונים היחידים שאנו
        רואים בעצמנו הם פניות שהגעת אלינו באופן יזום בדוא״ל.
      </p>

      <h2 class="font-display mt-8">8. שינויים במדיניות</h2>
      <p class="text-ink/85 leading-relaxed">
        אנו עשויים לעדכן את המדיניות הזו מעת לעת. התאריך בראש הדף יעודכן בהתאם.
        שימוש מתמשך באתר לאחר מועד העדכון יראה כהסכמה לגרסה המעודכנת.
      </p>

      <h2 class="font-display mt-8">9. יצירת קשר</h2>
      <p class="text-ink/85 leading-relaxed">
        בכל שאלה, בקשה או תלונה הקשורה למדיניות זו ניתן לפנות אלינו דרך
        <NuxtLink to="/contact/" class="text-brand-700 underline">טופס יצירת הקשר</NuxtLink>.
      </p>
    </article>
  </div>
</template>
