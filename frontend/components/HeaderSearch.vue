<script setup lang="ts">
// The header's search popover: a toggle button and a dialog holding the input
// and SearchSuggestions. The search itself is composables/useSiteSearch.ts,
// shared with the homepage box (home/HomeSearch.vue). Client-side only — the
// popover is never part of prerendered HTML, and the index loads on first open.
import { NO_HIGHLIGHT } from "~/utils/header-search";

const s = useSiteSearch("header-search");
const { query, highlight, datasets, tags, options, panel } = s;
const open = ref(false);
const buttonEl = ref<HTMLElement | null>(null);
const inputEl = ref<HTMLInputElement | null>(null);
const panelEl = ref<HTMLElement | null>(null);

function retry() {
  s.load();
  inputEl.value?.focus();
}

function toggle() {
  open.value = !open.value;
  if (open.value) {
    s.load();
    nextTick(() => inputEl.value?.focus());
  }
}

function close() {
  open.value = false;
  highlight.value = NO_HIGHLIGHT;
  buttonEl.value?.focus();
}

function submit() {
  if (!s.submit()) return;
  open.value = false;
  s.reset();
}

// Bound on the whole dialog, so Escape and the arrows also work while focus is
// on a result link (Tab) rather than in the input. The arrows move the
// highlight (exposed as the input's aria-activedescendant) and bring focus
// back to the input, where Enter opens the highlighted option (or, with
// nothing highlighted, the full list). The cycle passes through "nothing
// highlighted", so the arrows can return to the full-list Enter.
function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    e.preventDefault();
    close();
    return;
  }
  if (s.onArrow(e) && document.activeElement !== inputEl.value)
    inputEl.value?.focus();
}

// A topic link is an in-app route: close the popover behind it. A dataset
// link is a full page load: left open (pageshow below resets it on back).
function onNavigate(kind: "page" | "route") {
  if (kind === "page") return;
  open.value = false;
  s.reset();
}

function onDocumentClick(e: MouseEvent) {
  if (!open.value) return;
  const t = e.target as Node;
  if (panelEl.value?.contains(t) || buttonEl.value?.contains(t)) return;
  open.value = false;
}

// A result link leaves the page with the popover still open. Back navigation
// restores the page from the bfcache as it was left, so reset it there instead
// of on click, which would unmount the link mid-click.
function onPageShow(e: PageTransitionEvent) {
  if (!e.persisted) return;
  open.value = false;
  s.reset();
}

onMounted(() => {
  document.addEventListener("mousedown", onDocumentClick);
  window.addEventListener("pageshow", onPageShow);
});
onBeforeUnmount(() => {
  document.removeEventListener("mousedown", onDocumentClick);
  window.removeEventListener("pageshow", onPageShow);
});
</script>

<template>
  <div class="relative">
    <button
      ref="buttonEl"
      type="button"
      :aria-label="open ? 'סגירת חיפוש' : 'פתיחת חיפוש'"
      :aria-expanded="open"
      aria-haspopup="dialog"
      class="inline-flex items-center justify-center gap-2 px-2.5 sm:ps-3 sm:pe-4 h-9 min-w-9 rounded-gov-pill bg-white/10 hover:bg-white/20 border border-white/20 text-white text-sm transition-colors"
      @click="toggle"
    >
      <img src="/icons/search.svg" alt="" class="w-4 h-4 invert opacity-90" />
      <span class="hidden sm:inline">חיפוש</span>
    </button>

    <div
      v-if="open"
      ref="panelEl"
      role="dialog"
      aria-label="חיפוש מאגרים ונושאים"
      class="absolute top-full mt-2 end-0 w-[min(24rem,calc(100vw-2rem))] bg-white text-ink rounded-gov shadow-card border border-rule overflow-hidden z-50"
      @keydown="onKeydown"
    >
      <label
        for="header-search-input"
        class="flex items-center gap-2 border-b border-rule px-3 py-2"
      >
        <img src="/icons/search.svg" alt="" class="w-5 h-5 opacity-70" />
        <span class="sr-only">חיפוש מאגרים, נושאים ומשרדים</span>
        <input
          id="header-search-input"
          ref="inputEl"
          v-model="query"
          type="search"
          role="combobox"
          aria-autocomplete="list"
          :aria-controls="s.listboxId"
          :aria-expanded="options.length > 0"
          :aria-activedescendant="s.activeDescendant.value"
          placeholder="חיפוש מאגר, נושא או משרד…"
          class="flex-1 bg-transparent border-0 text-sm placeholder:text-subtle"
          @keydown.enter.prevent="submit"
        />
      </label>

      <SearchSuggestions
        :query="query"
        :panel="panel"
        :datasets="datasets"
        :tags="tags"
        :highlight="highlight"
        :listbox-id="s.listboxId"
        :option-id="s.optionId"
        @hover="highlight = $event"
        @retry="retry"
        @navigate="onNavigate"
      />

      <div
        class="border-t border-rule px-3 py-2 text-xs text-subtle bg-surface flex items-center justify-between gap-2"
      >
        <span>{{
          options[highlight]
            ? "הקשה על Enter תפתח את התוצאה המסומנת"
            : "הקשה על Enter תפתח את כל התוצאות"
        }}</span>
        <NuxtLink
          to="/datasets/"
          class="text-brand-700 hover:underline no-underline"
          @click="open = false"
        >
          לכל המאגרים
        </NuxtLink>
      </div>
    </div>
  </div>
</template>
