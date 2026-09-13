<script setup lang="ts">
import type { InsightSlide } from '~/utils/insights'
import { chunkBy, sampleInsights } from '~/utils/insights'

const props = defineProps<{ pool: InsightSlide[]; sampleSize?: number }>()

const SAMPLE = computed(() => props.sampleSize ?? 6)
const ROTATE_MS = 5_500
const LG_QUERY = '(min-width: 1024px)'
const INTENT_PX = 6
const FLIP_RATIO = 0.15
const FLIP_MIN_PX = 40
const TILE_PERCENT = 100 / 3
const COMMIT_DURATION_MS = 280

const slides = ref<InsightSlide[]>(props.pool.slice(0, SAMPLE.value))
const cardsPerSlide = ref(1)
const idx = ref(0)
const paused = ref(false)
const reducedMotion = ref(false)

const containerEl = ref<HTMLElement | null>(null)
const trackEl = ref<HTMLElement | null>(null)
const rawDelta = ref(0)
const committingPercent = ref(0)
const transitioning = ref(false)
const dragging = ref(false)

let pointerStartX = 0
let pointerId: number | null = null
let suppressNextClick = false
let transitionTimeout: ReturnType<typeof setTimeout> | null = null

const chunks = computed(() => chunkBy(slides.value, cardsPerSlide.value))

const windowChunks = computed(() => {
  const n = chunks.value.length
  if (n === 0) return []
  const i = idx.value
  return [
    chunks.value[(i - 1 + n) % n],
    chunks.value[i],
    chunks.value[(i + 1) % n],
  ]
})

const trackStyle = computed(() => ({
  transform: `translate3d(calc(${-TILE_PERCENT + committingPercent.value}% + ${rawDelta.value}px), 0, 0)`,
  transition: transitioning.value && !reducedMotion.value
    ? `transform ${COMMIT_DURATION_MS}ms cubic-bezier(.2,.8,.2,1)`
    : 'none',
  willChange: 'transform',
}))

let timer: ReturnType<typeof setInterval> | null = null
let mql: MediaQueryList | null = null

function flipThresholdPx(): number {
  const w = containerEl.value?.clientWidth ?? 0
  return Math.max(w * FLIP_RATIO, FLIP_MIN_PX)
}

function startTransition() {
  transitioning.value = true
  if (transitionTimeout) clearTimeout(transitionTimeout)
  transitionTimeout = setTimeout(finalizeTransition, COMMIT_DURATION_MS + 80)
}

function finalizeTransition() {
  if (transitionTimeout) {
    clearTimeout(transitionTimeout)
    transitionTimeout = null
  }
  if (!transitioning.value) return
  transitioning.value = false
  if (committingPercent.value !== 0) {
    const direction = committingPercent.value < 0 ? 1 : -1
    const n = chunks.value.length
    if (n > 0) idx.value = (idx.value + direction + n) % n
    committingPercent.value = 0
  }
}

function onTrackTransitionEnd(e: TransitionEvent) {
  if (e.propertyName !== 'transform') return
  if (e.target !== e.currentTarget) return
  finalizeTransition()
}

function commit(direction: 1 | -1) {
  const n = chunks.value.length
  if (n < 2) return
  if (transitioning.value) return
  rawDelta.value = 0
  committingPercent.value = direction === 1 ? -TILE_PERCENT : TILE_PERCENT
  if (reducedMotion.value) {
    idx.value = (idx.value + direction + n) % n
    committingPercent.value = 0
    return
  }
  startTransition()
}

function advance(delta: number) {
  if (delta === 0) return
  if (transitioning.value) return
  commit(delta > 0 ? 1 : -1)
}

function snapBack() {
  if (rawDelta.value === 0) return
  if (reducedMotion.value) {
    rawDelta.value = 0
    return
  }
  rawDelta.value = 0
  startTransition()
}

function onPointerDown(e: PointerEvent) {
  if (chunks.value.length < 2) return
  if (transitioning.value) return
  if (e.pointerType === 'mouse' && e.button !== 0) return
  if (pointerId !== null) {
    rawDelta.value = 0
    dragging.value = false
    pointerId = null
    return
  }
  pointerId = e.pointerId
  pointerStartX = e.clientX
  rawDelta.value = 0
  dragging.value = false
  suppressNextClick = false
}

function onPointerMove(e: PointerEvent) {
  if (pointerId === null || e.pointerId !== pointerId) return
  const delta = e.clientX - pointerStartX
  if (!dragging.value) {
    if (Math.abs(delta) < INTENT_PX) return
    dragging.value = true
    suppressNextClick = true
    try {
      ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    } catch {}
  }
  rawDelta.value = delta
}

function onPointerUp(e: PointerEvent) {
  if (pointerId === null || e.pointerId !== pointerId) return
  const delta = rawDelta.value
  const wasDragging = dragging.value
  try {
    ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  } catch {}
  pointerId = null
  dragging.value = false

  if (!wasDragging) {
    rawDelta.value = 0
    return
  }

  const flipPx = flipThresholdPx()
  if (Math.abs(delta) > flipPx) {
    commit(delta < 0 ? 1 : -1)
  } else {
    snapBack()
  }
}

function onPointerCancel(e: PointerEvent) {
  if (pointerId === null || e.pointerId !== pointerId) return
  try {
    ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  } catch {}
  dragging.value = false
  pointerId = null
  snapBack()
}

function onClickCapture(e: MouseEvent) {
  if (suppressNextClick) {
    e.preventDefault()
    e.stopPropagation()
    suppressNextClick = false
  }
}

function start() {
  stop()
  if (reducedMotion.value || chunks.value.length < 2) return
  timer = setInterval(() => {
    if (paused.value || dragging.value || transitioning.value || document.hidden) return
    advance(1)
  }, ROTATE_MS)
}

function stop() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function syncCardsPerSlide() {
  const next = mql?.matches ? 2 : 1
  if (next === cardsPerSlide.value) return
  cardsPerSlide.value = next
  idx.value = 0
  rawDelta.value = 0
  committingPercent.value = 0
  transitioning.value = false
  if (transitionTimeout) {
    clearTimeout(transitionTimeout)
    transitionTimeout = null
  }
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowLeft') { advance(1); e.preventDefault() }
  else if (e.key === 'ArrowRight') { advance(-1); e.preventDefault() }
}

function jumpTo(i: number) {
  if (i === idx.value) return
  if (transitioning.value) return
  idx.value = i
  rawDelta.value = 0
  committingPercent.value = 0
}

onMounted(() => {
  reducedMotion.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  mql = window.matchMedia(LG_QUERY)
  cardsPerSlide.value = mql.matches ? 2 : 1
  mql.addEventListener('change', syncCardsPerSlide)
  slides.value = sampleInsights(props.pool, SAMPLE.value)
  idx.value = 0
  start()
  document.addEventListener('visibilitychange', start)
})

onBeforeUnmount(() => {
  stop()
  if (transitionTimeout) {
    clearTimeout(transitionTimeout)
    transitionTimeout = null
  }
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', start)
  }
  if (mql) mql.removeEventListener('change', syncCardsPerSlide)
})
</script>

<template>
  <section
    v-if="slides.length"
    class="not-prose -mt-10 md:-mt-14 overflow-x-clip"
    aria-roledescription="carousel"
    aria-label="תובנות מתוך מאגרי המידע"
    @mouseenter="paused = true"
    @mouseleave="paused = false"
    @focusin="paused = true"
    @focusout="paused = false"
    @keydown="onKey"
  >
    <div class="flex items-baseline justify-between mb-3">
      <h2 class="font-display m-0 text-lg md:text-xl text-ink">מומלצים להתחלה</h2>
      <span class="text-xs text-ink/70">דוגמיות אקראיות מתוך מאגרי המידע</span>
    </div>

    <div
      ref="containerEl"
      class="overflow-hidden touch-pan-y select-none"
      :class="chunks.length > 1 ? 'cursor-grab active:cursor-grabbing' : ''"
      dir="ltr"
      aria-live="polite"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
      @click.capture="onClickCapture"
    >
      <div
        ref="trackEl"
        class="flex w-[300%]"
        :style="trackStyle"
        @transitionend="onTrackTransitionEnd"
      >
        <div
          v-for="(tile, ti) in windowChunks"
          :key="ti"
          class="shrink-0 w-1/3 px-1.5"
          dir="rtl"
          :aria-hidden="ti === 1 ? undefined : 'true'"
        >
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <a
              v-for="card in tile"
              :key="card.id"
              :href="card.href"
              :tabindex="ti === 1 ? 0 : -1"
              class="card card-hover p-5 md:p-6 flex flex-col no-underline group"
            >
              <div class="flex items-center justify-between gap-2 mb-3 text-xs">
                <span class="badge bg-brand-50 text-brand-700 border-brand-100">{{ card.kind_label_he }}</span>
                <span v-if="card.is_fresh" class="inline-flex items-center gap-1.5 text-ok font-medium">
                  <span class="h-1.5 w-1.5 rounded-full bg-ok" aria-hidden="true" />
                  עודכן השבוע
                </span>
              </div>

              <div class="flex-1">
                <h3
                  class="font-display text-ink text-xl md:text-2xl leading-snug line-clamp-2 m-0
                         group-hover:text-brand-700 transition-colors"
                >
                  {{ card.title }}
                </h3>
                <div v-if="card.organization" class="text-sm text-subtle mt-1 truncate">
                  {{ card.organization }}
                </div>

                <div v-if="card.stat" class="mt-4 flex items-baseline gap-2">
                  <span class="font-display text-3xl md:text-4xl text-ink tabular-nums leading-none">
                    {{ card.stat.value }}
                  </span>
                  <span class="text-sm text-subtle">{{ card.stat.unit }}</span>
                </div>
              </div>

              <div class="mt-4 flex items-center justify-between gap-2 pt-3 border-t border-rule/60">
                <span v-if="card.primary_tag" class="tag-chip">{{ card.primary_tag }}</span>
                <span v-else aria-hidden="true" />
                <span class="inline-flex items-center gap-1 text-sm font-medium text-brand-700">
                  פתח
                  <img
                    src="/icons/arrow-left.svg"
                    alt=""
                    class="w-4 h-4 transition-transform group-hover:-translate-x-1"
                  />
                </span>
              </div>
            </a>
          </div>
        </div>
      </div>
    </div>

    <div v-if="chunks.length > 1" class="mt-3 flex items-center justify-center gap-2">
      <!-- 40px buttons / 24px dot hit-areas: visual dots stay small, the
           clickable surface meets WCAG 2.5.8 target-size minimums. -->
      <button
        type="button"
        class="p-3 rounded-gov-sm text-subtle hover:text-ink hover:bg-brand-50 transition"
        aria-label="הקבוצה הקודמת"
        @click.stop.prevent="advance(-1)"
      >
        <img src="/icons/chevron-right.svg" alt="" class="w-4 h-4" />
      </button>

      <div class="flex items-center" role="tablist">
        <button
          v-for="(_, i) in chunks"
          :key="i"
          type="button"
          role="tab"
          :aria-label="`מעבר לקבוצה ${i + 1}`"
          :aria-current="i === idx ? 'true' : undefined"
          class="group/dot flex items-center justify-center h-6 min-w-6 px-0.5"
          @click.stop.prevent="jumpTo(i)"
        >
          <span
            class="h-1.5 rounded-full transition-all"
            :class="i === idx ? 'w-5 bg-brand-600' : 'w-1.5 bg-rule group-hover/dot:bg-brand-200'"
            aria-hidden="true"
          />
        </button>
      </div>

      <button
        type="button"
        class="p-3 rounded-gov-sm text-subtle hover:text-ink hover:bg-brand-50 transition"
        aria-label="הקבוצה הבאה"
        @click.stop.prevent="advance(1)"
      >
        <img src="/icons/chevron-left.svg" alt="" class="w-4 h-4" />
      </button>
    </div>
  </section>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
