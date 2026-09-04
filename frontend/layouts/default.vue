<script setup lang="ts">
const route = useRoute()
const onHome = computed(() => route.path === '/')
const year = new Date().getFullYear()
</script>

<template>
  <div class="min-h-screen flex flex-col bg-surface">
    <a
      href="#main"
      class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:start-2 focus:z-50 focus:bg-brand focus:text-white focus:px-4 focus:py-2 focus:rounded-gov focus:no-underline"
    >
      דלג לתוכן
    </a>
    <header class="gov-header">
      <div class="max-w-gov mx-auto px-4 h-header flex items-center justify-between gap-3 sm:gap-6">
        <div class="flex items-center gap-2">
          <MobileNavDrawer />
          <NuxtLink to="/" class="flex items-center gap-2.5 no-underline hover:no-underline text-white hover:text-white focus:text-white" aria-label="govil.ai — דף הבית">
            <svg class="w-9 h-9 shrink-0" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
              <rect x="2.5" y="20.5" width="18" height="1.5" rx="0.5"/>
              <rect x="4" y="14" width="3" height="6.5" rx="0.5"/>
              <rect x="8" y="11" width="3" height="9.5" rx="0.5"/>
              <rect x="12" y="8" width="3" height="12.5" rx="0.5"/>
              <rect x="16" y="13" width="3" height="7.5" rx="0.5"/>
              <path d="M13.5 2 L14.2 3.8 L16 4.5 L14.2 5.2 L13.5 7 L12.8 5.2 L11 4.5 L12.8 3.8 Z"/>
            </svg>
            <span class="flex flex-col leading-none">
              <span class="font-display text-lg leading-none">govil.ai</span>
              <span class="hidden sm:inline text-[11px] text-white/75 mt-1 leading-none">מידע ממשלתי. בעזרת AI.</span>
            </span>
          </NuxtLink>
        </div>

        <nav class="hidden md:flex items-center gap-6 text-sm">
          <NuxtLink
            to="/"
            class="py-2 text-white/85 hover:text-white no-underline hover:no-underline"
            :class="{ 'text-white font-medium': onHome }"
          >ראשי</NuxtLink>
          <NuxtLink to="/datasets/" class="py-2 text-white/85 hover:text-white no-underline hover:no-underline">מאגרים</NuxtLink>
          <NuxtLink to="/ministries/" class="py-2 text-white/85 hover:text-white no-underline hover:no-underline">משרדים</NuxtLink>
          <NuxtLink to="/tags/" class="py-2 text-white/85 hover:text-white no-underline hover:no-underline">נושאים</NuxtLink>
          <NuxtLink to="/how-it-works/" class="py-2 text-white/85 hover:text-white no-underline hover:no-underline">איך זה עובד</NuxtLink>
          <NuxtLink to="/about/" class="py-2 text-white/85 hover:text-white no-underline hover:no-underline">אודות</NuxtLink>
          <NuxtLink to="/contact/" class="py-2 text-white/85 hover:text-white no-underline hover:no-underline">צרו קשר</NuxtLink>
        </nav>

        <div class="flex items-center gap-3">
          <HeaderSearch />
        </div>
      </div>
    </header>

    <main id="main" tabindex="-1" class="flex-1">
      <slot />
    </main>

    <footer class="bg-ink-deep text-white mt-16">
      <div class="max-w-gov mx-auto px-4 py-10 grid grid-cols-3 md:grid-cols-4 gap-4 sm:gap-8 text-sm">
        <div class="col-span-3 md:col-span-1">
          <div class="font-display text-base mb-2 flex items-center gap-2">
            <svg class="w-5 h-5 shrink-0" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
              <rect x="2.5" y="20.5" width="18" height="1.5" rx="0.5"/>
              <rect x="4" y="14" width="3" height="6.5" rx="0.5"/>
              <rect x="8" y="11" width="3" height="9.5" rx="0.5"/>
              <rect x="12" y="8" width="3" height="12.5" rx="0.5"/>
              <rect x="16" y="13" width="3" height="7.5" rx="0.5"/>
              <path d="M13.5 2 L14.2 3.8 L16 4.5 L14.2 5.2 L13.5 7 L12.8 5.2 L11 4.5 L12.8 3.8 Z"/>
            </svg>
            govil.ai
          </div>
          <p class="text-white/75 leading-relaxed m-0">
            מאגרי המידע הציבוריים של ממשלת ישראל — מוסברים על ידי AI,
            פתוחים לכל אחד.
          </p>
        </div>
        <div>
          <div class="font-display text-base mb-2">עיון</div>
          <ul class="list-none p-0 m-0 space-y-1.5">
            <li><NuxtLink to="/" class="text-white/85 hover:text-white no-underline hover:no-underline">ראשי</NuxtLink></li>
            <li><NuxtLink to="/datasets/" class="text-white/85 hover:text-white no-underline hover:no-underline">כל המאגרים</NuxtLink></li>
            <li><NuxtLink to="/ministries/" class="text-white/85 hover:text-white no-underline hover:no-underline">משרדים</NuxtLink></li>
            <li><NuxtLink to="/tags/" class="text-white/85 hover:text-white no-underline hover:no-underline">נושאים</NuxtLink></li>
          </ul>
        </div>
        <div>
          <div class="font-display text-base mb-2">על האתר</div>
          <ul class="list-none p-0 m-0 space-y-1.5">
            <li><NuxtLink to="/how-it-works/" class="text-white/85 hover:text-white no-underline hover:no-underline">איך זה עובד</NuxtLink></li>
            <li><NuxtLink to="/about/" class="text-white/85 hover:text-white no-underline hover:no-underline">אודות</NuxtLink></li>
            <li><NuxtLink to="/faq/" class="text-white/85 hover:text-white no-underline hover:no-underline">שאלות נפוצות</NuxtLink></li>
            <li><NuxtLink to="/disclaimer/" class="text-white/85 hover:text-white no-underline hover:no-underline">הבהרה משפטית</NuxtLink></li>
            <li><NuxtLink to="/contact/" class="text-white/85 hover:text-white no-underline hover:no-underline">צרו קשר</NuxtLink></li>
          </ul>
        </div>
        <div>
          <div class="font-display text-base mb-2">מקורות</div>
          <ul class="list-none p-0 m-0 space-y-1.5 text-white/85">
            <li>
              <a href="https://data.gov.il" target="_blank" rel="noopener" class="inline-flex items-center gap-1.5 hover:text-white no-underline hover:no-underline">
                <img src="/icons/external-link.svg" alt="" class="w-4 h-4 invert opacity-90" />
                data.gov.il
              </a>
            </li>
            <li>
              <a href="https://www.gov.il" target="_blank" rel="noopener" class="inline-flex items-center gap-1.5 hover:text-white no-underline hover:no-underline">
                <img src="/icons/external-link.svg" alt="" class="w-4 h-4 invert opacity-90" />
                gov.il
              </a>
            </li>
          </ul>
        </div>
      </div>
      <div class="border-t border-white/10">
        <div class="max-w-gov mx-auto px-4 py-4 text-xs text-white/70 flex flex-col sm:flex-row sm:justify-between gap-2">
          <div>האתר אינו אתר ממשלתי רשמי אלא מיזם אזרחי עצמאי למחקר והנגשת מאגרי המידע הממשלתיים הפתוחים של ישראל. התוכן מבוסס על נתוני data.gov.il ומונגש באמצעות ניתוח נתונים וויזואליזציות.</div>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <NuxtLink to="/accessibility/" class="text-white/85 hover:text-white no-underline hover:no-underline">הצהרת נגישות</NuxtLink>
            <span aria-hidden="true" class="text-white/40">·</span>
            <NuxtLink to="/disclaimer/" class="text-white/85 hover:text-white no-underline hover:no-underline">הבהרה משפטית</NuxtLink>
            <span aria-hidden="true" class="text-white/40">·</span>
            <NuxtLink to="/privacy/" class="text-white/85 hover:text-white no-underline hover:no-underline">מדיניות פרטיות</NuxtLink>
            <span aria-hidden="true" class="text-white/40">·</span>
            <NuxtLink to="/terms/" class="text-white/85 hover:text-white no-underline hover:no-underline">תנאי שימוש</NuxtLink>
            <span aria-hidden="true" class="text-white/40">·</span>
            <span>© {{ year }} govil.ai</span>
          </div>
        </div>
      </div>
    </footer>
  </div>
</template>
