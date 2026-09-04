<script setup lang="ts">
const SITE_URL = 'https://govil.ai'

useSeo({
  title: 'יצירת קשר עם צוות govil.ai',
  description: 'יצירת קשר עם צוות govil.ai — שאלות, פידבק, דיווח על אי-דיוקים בנתונים ובקשות למאגרים נוספים. מענה מהיר בדוא״ל או בטופס מקוון.',
  path: '/contact/',
  keywords: ['יצירת קשר', 'פידבק', 'דיווח באגים', 'govil.ai', 'פניות הציבור'],
  breadcrumbs: [
    { name: 'ראשי', url: `${SITE_URL}/` },
    { name: 'יצירת קשר', url: `${SITE_URL}/contact/` },
  ],
  extraJsonLd: {
    '@context': 'https://schema.org',
    '@type': 'ContactPage',
    name: 'יצירת קשר עם govil.ai',
    url: `${SITE_URL}/contact/`,
    inLanguage: 'he-IL',
    mainEntity: {
      '@type': 'Organization',
      name: 'govil.ai',
      url: SITE_URL,
      email: 'contact@govil.ai',
      contactPoint: [
        {
          '@type': 'ContactPoint',
          contactType: 'customer support',
          email: 'contact@govil.ai',
          availableLanguage: ['Hebrew', 'English'],
        },
        {
          '@type': 'ContactPoint',
          contactType: 'accessibility',
          email: 'accessibility@govil.ai',
          availableLanguage: ['Hebrew', 'English'],
        },
      ],
    },
  },
})

const route = useRoute()
const initialTopic = String(route.query.topic || '')

type Status = 'idle' | 'sending' | 'sent' | 'error'
const status = ref<Status>('idle')
const errorMsg = ref('')

async function onSubmit(e: Event) {
  const form = e.target as HTMLFormElement
  status.value = 'sending'
  errorMsg.value = ''
  try {
    const res = await fetch(form.action, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      body: new FormData(form),
    })
    if (res.ok) {
      status.value = 'sent'
      form.reset()
      return
    }
    const data = await res.json().catch(() => null) as { errors?: { message?: string }[] } | null
    errorMsg.value = data?.errors?.[0]?.message || 'שליחה נכשלה. נסו שוב מאוחר יותר.'
    status.value = 'error'
  } catch {
    errorMsg.value = 'בעיית חיבור. נסו שוב מאוחר יותר.'
    status.value = 'error'
  }
}
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <div class="text-xs text-subtle mb-2">
      <NuxtLink to="/">ראשי</NuxtLink> › יצירת קשר
    </div>

    <article class="max-w-3xl">
      <h1 class="font-display">יצירת קשר</h1>
      <p class="text-subtle text-sm">עודכן לאחרונה: 3 בספטמבר 2026</p>
      <p class="mt-4 text-lg text-ink/80 leading-relaxed">
        שאלה לגבי נתונים, דיווח על טעות או אי-דיוק, הצעה למאגר חדש או שיתוף פעולה — נשמח לשמוע מכם ולסייע.
      </p>

      <!-- Direct Contact Channels & Operational Details -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 my-6">
        <div class="card p-5">
          <div class="text-xs font-semibold text-subtle uppercase tracking-wider mb-1">פניות כלליות ומידע</div>
          <div class="font-mono text-sm font-medium text-brand-700">
            <a href="mailto:contact@govil.ai" class="hover:underline">contact@govil.ai</a>
          </div>
          <p class="text-xs text-subtle mt-2 m-0">שאלות, הצעות ופניות בנושאי נתונים</p>
        </div>

        <div class="card p-5">
          <div class="text-xs font-semibold text-subtle uppercase tracking-wider mb-1">רכז נגישות</div>
          <div class="font-mono text-sm font-medium text-brand-700">
            <a href="mailto:accessibility@govil.ai" class="hover:underline">accessibility@govil.ai</a>
          </div>
          <p class="text-xs text-subtle mt-2 m-0">פניות והתאמות נגישות לפי תקן IS 5568</p>
        </div>

        <div class="card p-5">
          <div class="text-xs font-semibold text-subtle uppercase tracking-wider mb-1">פניות הציבור</div>
          <div class="text-sm font-medium text-ink">מענה אנושי</div>
          <p class="text-xs text-subtle mt-2 m-0">אנו קוראים כל פנייה ומשתדלים להשיב בהקדם האפשרי</p>
        </div>
      </div>

      <div
        v-if="status === 'sent'"
        class="card p-6 mt-6 border-r-4 border-r-ok"
        role="status"
        aria-live="polite"
      >
        <h2 class="font-display mt-0 mb-2">תודה!</h2>
        <p class="text-ink/85 m-0 leading-relaxed">
          ההודעה התקבלה בהצלחה. נחזור אליכם בהקדם האפשרי.
        </p>
      </div>

      <form
        v-else
        action="https://formspree.io/f/xojrvowr"
        method="POST"
        class="card p-6 mt-6 space-y-4"
        novalidate
        @submit.prevent="onSubmit"
      >
        <input type="hidden" name="_subject" value="פנייה חדשה מ-govil.ai" />
        <input
          type="text"
          name="_gotcha"
          tabindex="-1"
          autocomplete="off"
          aria-hidden="true"
          class="hidden"
        />

        <div>
          <label for="name" class="block text-sm text-ink/85 mb-1">שם מלא <span class="text-subtle">(אופציונלי)</span></label>
          <input
            id="name"
            name="name"
            type="text"
            autocomplete="name"
            class="w-full border border-rule rounded-gov px-3 py-2 bg-white text-ink"
            placeholder="ישראל ישראלי"
          />
        </div>

        <div>
          <label for="email" class="block text-sm text-ink/85 mb-1">כתובת דוא"ל <span class="text-danger" aria-hidden="true">*</span></label>
          <input
            id="email"
            name="email"
            type="email"
            required
            autocomplete="email"
            class="w-full border border-rule rounded-gov px-3 py-2 bg-white text-ink"
            placeholder="your@email.com"
          />
        </div>

        <div>
          <label for="topic" class="block text-sm text-ink/85 mb-1">נושא הפנייה <span class="text-subtle">(אופציונלי)</span></label>
          <select
            id="topic"
            name="topic"
            :value="initialTopic"
            class="w-full border border-rule rounded-gov px-3 py-2 bg-white text-ink"
          >
            <option value="">בחרו נושא…</option>
            <option>תיקון שגיאה / אי-דיוק בנתונים</option>
            <option>בקשת הוספת מאגר מ-data.gov.il</option>
            <option>נגישות האתר</option>
            <option>שאלה כללית</option>
            <option>שיתוף פעולה או תקשורת</option>
            <option>אחר</option>
          </select>
        </div>

        <div>
          <label for="message" class="block text-sm text-ink/85 mb-1">תוכן ההודעה <span class="text-danger" aria-hidden="true">*</span></label>
          <textarea
            id="message"
            name="message"
            required
            rows="6"
            class="w-full border border-rule rounded-gov px-3 py-2 bg-white text-ink resize-y"
            placeholder="פרטו את שאלתכם, הקישור למאגר הרלוונטי או הצעתכם…"
          ></textarea>
        </div>

        <p
          v-if="status === 'error'"
          class="text-sm text-danger m-0"
          role="alert"
        >
          {{ errorMsg }}
        </p>

        <div class="flex flex-wrap items-center justify-between gap-3 pt-2">
          <div class="flex items-center gap-3">
            <button
              type="submit"
              :disabled="status === 'sending'"
              class="btn-primary disabled:opacity-60 disabled:cursor-wait"
            >
              {{ status === 'sending' ? 'שולח…' : 'שליחת הודעה' }}
            </button>
            <span class="text-xs text-subtle">
              פרטי הקשר משמשים אך ורק לצורך מענה לפנייתכם.
            </span>
          </div>
          <NuxtLink to="/privacy/" class="text-xs text-subtle hover:underline">
            מדיניות פרטיות
          </NuxtLink>
        </div>
      </form>
    </article>
  </div>
</template>
