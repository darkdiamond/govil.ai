<script setup lang="ts">
const lastUpdated = '3 בספטמבר 2026'

useSeo({
  title: 'הצהרת נגישות — govil.ai',
  description: 'הצהרת הנגישות של govil.ai — האתר עומד בתקן ישראלי ת"י 5568 ברמה AA. פרטי אחראי הנגישות וערוצי הפנייה.',
  path: '/accessibility/',
  keywords: ['נגישות', 'הצהרת נגישות', 'ת"י 5568', 'WCAG', 'תקנות שוויון זכויות'],
  breadcrumbs: [
    { name: 'ראשי', url: 'https://govil.ai/' },
    { name: 'הצהרת נגישות', url: 'https://govil.ai/accessibility/' },
  ],
})
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <div class="text-xs text-subtle mb-2">
      <NuxtLink to="/">ראשי</NuxtLink> › הצהרת נגישות
    </div>

    <article class="max-w-3xl prose-gov">
      <h1 class="font-display">הצהרת נגישות</h1>
      <p class="text-subtle text-sm">עודכן לאחרונה: {{ lastUpdated }}</p>

      <h2 class="font-display mt-8">1. על האתר</h2>
      <p class="text-ink/85 leading-relaxed">
        govil.ai הוא פרויקט עצמאי שמטרתו להנגיש לציבור הרחב את מאגרי המידע הציבוריים
        של ממשלת ישראל (data.gov.il) באמצעות תקצירים, תובנות וויזואליזציות הנכתבים
        אוטומטית על ידי בינה מלאכותית. <strong>האתר אינו אתר ממשלתי רשמי</strong>,
        ואינו פועל מטעם ממשלת ישראל, משרדיה או רשויותיה.
      </p>
      <p class="text-ink/85 leading-relaxed">
        אנו רואים בנגישות ערך מרכזי ופועלים להפיכת האתר לשמיש עבור כל אדם, ללא קשר
        ליכולותיו הפיזיות, החושיות או הקוגניטיביות, ובהתאם לחוק שוויון זכויות לאנשים
        עם מוגבלות, התשנ"ח-1998 ולתקנות שוויון זכויות לאנשים עם מוגבלות (התאמות
        נגישות לשירות), התשע"ג-2013.
      </p>

      <h2 class="font-display mt-8">2. רמת הנגישות</h2>
      <p class="text-ink/85 leading-relaxed">
        האתר נבנה ונבדק על מנת לעמוד בדרישות
        <strong>תקן ישראלי ת"י 5568 ברמת התאמה AA</strong>, התואם את הנחיות
        <a href="https://www.w3.org/TR/WCAG20/" target="_blank" rel="noopener" class="text-brand-700 underline">WCAG 2.0</a>
        של ארגון התקינה הבינלאומי W3C ברמת AA.
      </p>
      <p class="text-ink/85 leading-relaxed">
        תאריך הביקורת האחרונה: {{ lastUpdated }}.
      </p>

      <h2 class="font-display mt-8">3. מה הונגש באתר</h2>
      <ul class="text-ink/85 leading-relaxed list-disc ps-6 space-y-2">
        <li>
          <strong>ניווט מקלדת מלא</strong> — ניתן לתפעל את כל הקישורים, הכפתורים,
          הטפסים והתפריטים באמצעות מקשי Tab / Shift+Tab / Enter / Esc / חיצים, ללא צורך
          בעכבר.
        </li>
        <li>
          <strong>קישור "דלג לתוכן"</strong> — מופיע בראש כל עמוד עם המעבר למקש Tab,
          ומאפשר לדלג מעל הניווט ישירות לתוכן העמוד.
        </li>
        <li>
          <strong>סימון מיקוד גלוי</strong> (focus ring) על כל רכיב אינטראקטיבי
          בעת ניווט מקלדת.
        </li>
        <li>
          <strong>יחס ניגודיות תקני</strong> — לפחות 4.5:1 לטקסט רגיל ו-3:1 לטקסט גדול,
          כנדרש בקריטריון 1.4.3 של WCAG 2.0 AA.
        </li>
        <li>
          <strong>תמיכה בהעדפת תנועה מופחתת</strong> (<code>prefers-reduced-motion</code>) —
          אנימציות וגלילה אוטומטית מבוטלות אוטומטית אצל משתמשים שהגדירו זאת במערכת
          ההפעלה שלהם.
        </li>
        <li>
          <strong>תמיכה בהגדלת תצוגה (zoom)</strong> עד 200% ללא אובדן תוכן או
          פונקציונליות.
        </li>
        <li>
          <strong>תוויות ARIA</strong> ותגיות סמנטיות עבור רכיבים אינטראקטיביים —
          תפריטים, חיפוש, חלוניות (dialog), קרוסלות וטפסים.
        </li>
        <li>
          <strong>היררכיית כותרות עקבית</strong> (h1 → h2 → h3) על כל עמוד, ללא דילוג
          על רמות.
        </li>
        <li>
          <strong>ניווט סמנטי</strong> — שימוש בלמרק־הולמים HTML5
          (<code>&lt;header&gt;</code>, <code>&lt;nav&gt;</code>, <code>&lt;main&gt;</code>,
          <code>&lt;footer&gt;</code>).
        </li>
        <li>
          <strong>טפסים נגישים</strong> — כל שדה כולל תווית מפורשת, וזיהוי שגיאות
          באמצעות <code>role="alert"</code> והודעות סטטוס באמצעות <code>aria-live</code>.
        </li>
        <li>
          <strong>תוכן עברי-RTL מלא</strong> — המסמכים מוגדרים עם
          <code>lang="he" dir="rtl"</code> ברמת ה-HTML הראשי, לתמיכה טובה בקוראי
          מסך בעברית (NVDA, VoiceOver, ChromeVox).
        </li>
        <li>
          <strong>תוויות חלופיות (alt)</strong> על כל תמונה מהותית; תמונות דקורטיביות
          מסומנות <code>alt=""</code> כדי שלא יוכרזו על ידי קוראי מסך.
        </li>
        <li>
          <strong>תיאור ARIA על גרפים</strong> — כל גרף ECharts באתר כולל
          <code>role="img"</code> ו-<code>aria-label</code> בעברית המתאר את הגרף ואת
          הממצא העיקרי. כאשר היקף הנתונים מאפשר זאת, נספחת גם גרסת טבלה לקריאת
          מסך.
        </li>
      </ul>

      <h2 class="font-display mt-8">4. חריגים ידועים</h2>
      <p class="text-ink/85 leading-relaxed">
        על אף המאמצים, ישנם כמה תחומים שטרם הונגשו במלואם:
      </p>
      <ul class="text-ink/85 leading-relaxed list-disc ps-6 space-y-2">
        <li>
          <strong>מפות אינטראקטיביות (Leaflet)</strong> — לחיצה על סמני מפה זמינה
          באמצעות עכבר ובקוראי מסך, אך הניווט בין סמני המפה במקלדת מוגבל בשל מגבלות
          ספריית הצד-השלישי. בכל מאגר מבוסס-מפה מוצגת חלופה נגישה (טבלת הנתונים
          המלאה וקישור להורדת קובץ CSV ישירות מ-data.gov.il).
        </li>
        <li>
          <strong>תוכן שנוצר אוטומטית על ידי בינה מלאכותית</strong> — ייתכנו אי-עקביות
          בעמודי מאגרים שנוצרו לפני מועד עדכון מדיניות הנגישות ({{ lastUpdated }}).
          התקן מוחל אוטומטית על כל הרצת סוכן חדשה, ועמודי המאגרים מתעדכנים בהדרגה
          ככל שהמאגרים מתחדשים במקור.
        </li>
        <li>
          <strong>תוכן צד שלישי</strong> (פרסומות Google AdSense) — כפוף למדיניות
          הנגישות של Google ואינו בשליטתנו הישירה.
        </li>
      </ul>

      <h2 class="font-display mt-8">5. אחראי נגישות ופנייה</h2>
      <p class="text-ink/85 leading-relaxed">
        אם נתקלתם בקושי נגישות כלשהו באתר, או שיש לכם הצעה לשיפור, נשמח לשמוע.
      </p>
      <ul class="text-ink/85 leading-relaxed list-disc ps-6 space-y-2">
        <li><strong>אחראי הנגישות:</strong> צוות govil.ai</li>
        <li><strong>דוא"ל:</strong> <a href="mailto:accessibility@govil.ai" class="text-brand-700 underline">accessibility@govil.ai</a></li>
        <li>
          <strong>ערוץ פנייה ראשי:</strong>
          <NuxtLink to="/contact/?topic=נגישות" class="text-brand-700 underline">טופס יצירת קשר — נושא "נגישות"</NuxtLink>
        </li>
        <li><strong>זמן מענה משוער:</strong> עד 14 ימי עסקים.</li>
      </ul>
      <p class="text-ink/85 leading-relaxed">
        ככל הניתן, נשמח אם תכללו בפנייה: תיאור הבעיה, כתובת העמוד שבו נתקלתם בה,
        סוג הדפדפן וטכנולוגיית הסיוע (אם רלוונטי). מידע זה מסייע לנו לאתר ולתקן את
        הבעיה במהירות.
      </p>

      <h2 class="font-display mt-8">6. פנייה לנציבות שוויון זכויות</h2>
      <p class="text-ink/85 leading-relaxed">
        אם פנייתכם לא נענתה תוך 30 יום או שלא קיבלתם מענה מספק, ניתן לפנות
        ל<a href="https://www.gov.il/he/departments/equal_rights_commission" target="_blank" rel="noopener" class="text-brand-700 underline">נציבות שוויון זכויות לאנשים עם מוגבלות במשרד המשפטים</a>.
      </p>

      <h2 class="font-display mt-8">7. עדכון אחרון</h2>
      <p class="text-ink/85 leading-relaxed">
        הצהרה זו עודכנה לאחרונה ב-{{ lastUpdated }} ותעודכן שוב בעקבות כל שינוי
        מהותי במדיניות הנגישות של האתר.
      </p>
    </article>
  </div>
</template>
