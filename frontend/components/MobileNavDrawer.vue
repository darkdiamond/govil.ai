<script setup lang="ts">
const route = useRoute()
const open = ref(false)
const triggerEl = ref<HTMLElement | null>(null)
const drawerEl = ref<HTMLElement | null>(null)

const links = [
  { to: '/', label: 'ראשי' },
  { to: '/datasets/', label: 'מאגרים' },
  { to: '/ministries/', label: 'משרדים' },
  { to: '/tags/', label: 'נושאים' },
  { to: '/how-it-works/', label: 'איך זה עובד' },
  { to: '/about/', label: 'אודות' },
  { to: '/faq/', label: 'שאלות נפוצות' },
  { to: '/disclaimer/', label: 'הבהרה משפטית' },
  { to: '/contact/', label: 'צרו קשר' },
]

function setOpen(v: boolean) {
  open.value = v
  if (typeof document !== 'undefined') {
    document.body.style.overflow = v ? 'hidden' : ''
  }
  if (v) {
    nextTick(() => {
      const first = drawerEl.value?.querySelector<HTMLElement>('[data-drawer-link]')
      first?.focus()
    })
  } else {
    triggerEl.value?.focus()
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) {
    e.preventDefault()
    setOpen(false)
  }
}

watch(() => route.fullPath, () => {
  if (open.value) setOpen(false)
})

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <div class="md:hidden">
    <button
      ref="triggerEl"
      type="button"
      aria-label="פתיחת תפריט ראשי"
      :aria-expanded="open"
      aria-controls="mobile-nav-drawer"
      class="w-9 h-9 grid place-items-center rounded-gov-pill hover:bg-white/10 transition-colors"
      @click="setOpen(true)"
    >
      <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-white opacity-90">
        <line x1="3" y1="6" x2="21" y2="6" />
        <line x1="3" y1="12" x2="21" y2="12" />
        <line x1="3" y1="18" x2="21" y2="18" />
      </svg>
    </button>

    <Teleport to="body">
      <Transition
        enter-active-class="transition-opacity duration-200"
        leave-active-class="transition-opacity duration-150"
        enter-from-class="opacity-0"
        leave-to-class="opacity-0"
      >
        <div
          v-if="open"
          class="fixed inset-0 z-[60] bg-ink-deep/60 md:hidden"
          aria-hidden="true"
          @click="setOpen(false)"
        />
      </Transition>

      <Transition
        enter-active-class="transition-transform duration-200"
        leave-active-class="transition-transform duration-150"
        enter-from-class="translate-x-full"
        leave-to-class="translate-x-full"
      >
        <aside
          v-if="open"
          id="mobile-nav-drawer"
          ref="drawerEl"
          role="dialog"
          aria-modal="true"
          aria-label="תפריט ראשי"
          class="fixed inset-y-0 start-0 z-[61] w-[80%] max-w-xs bg-white shadow-2xl flex flex-col md:hidden"
        >
          <div class="flex items-center justify-between gap-3 px-4 py-3 bg-ink-deep text-white">
            <span class="font-display text-base">תפריט</span>
            <button
              type="button"
              aria-label="סגירת תפריט"
              class="w-9 h-9 grid place-items-center rounded-gov-pill hover:bg-white/10 transition-colors"
              @click="setOpen(false)"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          <nav class="flex-1 overflow-y-auto py-2">
            <ul class="list-none m-0 p-0">
              <li v-for="l in links" :key="l.to">
                <NuxtLink
                  :to="l.to"
                  data-drawer-link
                  class="block px-4 py-3 text-base text-ink no-underline hover:bg-brand-50 hover:no-underline border-b border-rule/60"
                  :class="{ 'bg-brand-50 text-brand-700 font-medium': route.path === l.to }"
                >
                  {{ l.label }}
                </NuxtLink>
              </li>
            </ul>
          </nav>

          <div class="border-t border-rule p-4 text-xs text-subtle leading-relaxed">
            האתר אינו אתר ממשלתי רשמי אלא מיזם אזרחי עצמאי למחקר והנגשת מאגרי המידע הממשלתיים הפתוחים של ישראל. התוכן מבוסס על נתוני data.gov.il ומונגש באמצעות ניתוח נתונים וויזואליזציות.
          </div>
        </aside>
      </Transition>
    </Teleport>
  </div>
</template>
