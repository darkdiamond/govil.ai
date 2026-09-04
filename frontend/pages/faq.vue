<script setup lang="ts">
const faqs = [
  {
    q: 'האם govil.ai הוא אתר ממשלתי רשמי?',
    a: 'לא. זהו מיזם אזרחי עצמאי. מאגרי הנתונים הגולמיים הם רכוש המדינה ומופקים מהאתרים הממשלתיים הרשמיים, אך הפלטפורמה הזו, התקצירים, הניתוחים ודפי הנחיתה מופעלים באופן פרטי. מטרתנו להנגיש את המידע הציבורי בצורה אינטראקטיבית ובהירה — ולא להחליף את המקור הממשלתי.',
  },
  {
    q: 'עד כמה הניתוחים והתקצירים באתר מדויקים?',
    a: 'התקצירים, המדדים והתובנות מעוגנים באופן קפדני ברשומות המקור של המאגרים עצמם ובמקורות ממשלתיים נלווים. עם זאת, ניתוח נתונים ממוחשב עשוי לכלול אי-דיוקים. לכל שימוש פורמלי או מקצועי (מחקר, עיתונות, רגולציה) — חובה להצליב מול המקור הרשמי המקושר בכל דף.',
  },
  {
    q: 'כל כמה זמן מתעדכנים הדפים?',
    a: 'המערכת מנטרת באופן שוטף את פורטל data.gov.il. ברגע שמתפרסמת גרסה חדשה של מאגר או מתווסף מאגר חדש, מופעל תהליך עיבוד וניתוח מעודכן, בדרך כלל תוך זמן קצר ממועד הפרסום במקור.',
  },
  {
    q: 'כיצד מיוצרים עמודי המאגרים והגרפים?',
    a: 'המערכת משלבת קריאה מובנית של קובצי הנתונים (CSV, JSON וכו׳), חישוב מדדים סטטיסטיים ואגרגציות, ובחירה אלגוריתמית של התצוגה המתאימה ביותר — מפה גיאוגרפית, גרף מגמה או טבלת פילוח. מודלים מתקדמים מסייעים בניסוח תקציר ברור תחת כללי אימות מחמירים.',
  },
  {
    q: 'האם אתם אוספים נתונים אישיים עליי בעת הגלישה?',
    a: 'האתר פתוח לעיון חופשי — אין צורך ברישום, אין מערכת מנויים ואין טפסים שחובה למלא כדי לצפות במידע. אנו משתמשים ב-Google Analytics לניתוח סטטיסטי מצרפי של תנועת הגולשים, וב-Google AdSense למימון עלויות התשתית. פירוט מלא מופיע בעמוד מדיניות הפרטיות בכתובת /privacy/.',
  },
  {
    q: 'איך מדווחים על שגיאה או מציעים מאגר חדש?',
    a: 'אנו מעודדים מעורבות קהילתית! ניתן לפנות אלינו ישירות דרך עמוד "צור קשר" או בדוא״ל contact@govil.ai עם פירוט המאגר וההערה. אנו בודקים כל פנייה ומתקנים במהירות במידת הצורך.',
  },
  {
    q: 'האם מותר לשתף, לצטט ולהשתמש במידע?',
    a: 'בהחלט! המידע הציבורי שייך לכולם. אתם מוזמנים לשתף קישורים, להשתמש בגרפים ולהציג את התובנות במחקרים או בכתבות, תוך ציון ייחוס מתאים ל-govil.ai ולמאגר המקור ב-data.gov.il.',
  },
]

useSeo({
  title: 'שאלות נפוצות — מאגרי מידע ממשלתיים ומתודולוגיית govil.ai',
  description: 'שאלות נפוצות על govil.ai — עצמאות האתר מול הממשלה, דיוק הנתונים והגרפים, תדירות העדכונים, מדיניות הפרטיות וכיצד מדווחים על אי-דיוק.',
  path: '/faq/',
  keywords: ['FAQ', 'שאלות נפוצות', 'שקיפות מידע', 'אימות נתונים', 'איך לדווח שגיאה'],
  breadcrumbs: [
    { name: 'ראשי', url: 'https://govil.ai/' },
    { name: 'שאלות ותשובות', url: 'https://govil.ai/faq/' },
  ],
  extraJsonLd: {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faqs.map((f) => ({
      '@type': 'Question',
      name: f.q,
      acceptedAnswer: { '@type': 'Answer', text: f.a },
    })),
  },
})
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <div class="text-xs text-subtle mb-2">
      <NuxtLink to="/">ראשי</NuxtLink> › שאלות ותשובות
    </div>

    <article class="max-w-3xl">
      <h1 class="font-display">שאלות ותשובות</h1>
      <p class="text-subtle text-sm">עודכן לאחרונה: 3 בספטמבר 2026</p>
      <p class="mt-4 text-ink/80 leading-relaxed">
        כל מה שחשוב לדעת על מיזם govil.ai, מקורות המידע הממשלתיים, מתודולוגיית העיבוד וההבדל בין האתר לבין המקורות הרשמיים.
      </p>

      <div class="mt-8 space-y-3">
        <details
          v-for="(f, i) in faqs"
          :key="i"
          class="card p-0 group"
        >
          <summary class="list-none cursor-pointer p-5 flex items-center justify-between gap-4 font-display text-ink hover:bg-brand-50/50 rounded-gov">
            <span>{{ f.q }}</span>
            <span aria-hidden="true" class="text-brand-700 text-xl transition-transform group-open:rotate-45 select-none">+</span>
          </summary>
          <div class="px-5 pb-5 pt-0 text-ink/85 leading-relaxed border-t border-rule">
            <p class="m-0 pt-4">{{ f.a }}</p>
          </div>
        </details>
      </div>

      <div class="mt-10 card p-5 bg-brand-50/50 border-brand-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div class="font-display text-ink mb-1 font-medium">לא מצאתם תשובה לשאלתכם?</div>
          <p class="text-sm text-ink/85 leading-relaxed m-0">
            אנו זמינים לכל פנייה, שאלה או דיווח מקצועי.
          </p>
        </div>
        <NuxtLink to="/contact/" class="btn-primary shrink-0">
          יצירת קשר
        </NuxtLink>
      </div>
    </article>
  </div>
</template>
