<script setup lang="ts">
import type FuseT from "fuse.js";
import type { SlimEntry } from "~/types/manifest";
import {
  type LoadState,
  moveHighlight,
  NO_HIGHLIGHT,
  panelState,
  submitTarget,
} from "~/utils/header-search";
import { datasetPath } from "~/utils/paths";
import { loadSearchIndex, memoRetry } from "~/utils/search-index";
import {
  normalizeSearchText,
  queryVariants,
  searchHaystack,
} from "~/utils/search-text";

/** Normalized copy of an entry's searchable fields (see search-text.ts). */
interface SearchDoc {
  entry: SlimEntry;
  title: string;
  summary_he: string;
  organization: string;
  tags: string[];
  /** All of the above in one string, for the converted-query substring test. */
  hay: string;
}

const LIMIT = 6;

const router = useRouter();
const open = ref(false);
const query = ref("");
// -1 (NO_HIGHLIGHT): Enter opens the full list; the arrows pick one hit.
const highlight = ref(NO_HIGHLIGHT);
const loadState = ref<LoadState>("idle");
const buttonEl = ref<HTMLElement | null>(null);
const inputEl = ref<HTMLInputElement | null>(null);
const panelEl = ref<HTMLElement | null>(null);

// Fuse.js (~24KB min+gz) and the slim search index (~60KB gz) only fire when
// the user opens the search popover, so both load on first toggle rather than
// being bundled into the layout chunk. This runs client-side only — the
// popover is never part of prerendered HTML.
// A failed load is not memoized (memoRetry), so the next open retries.
const fuse = shallowRef<FuseT<SearchDoc> | null>(null);

const ensureFuse = memoRetry((): Promise<void> =>
  Promise.all([import("fuse.js"), loadSearchIndex()]).then(
    ([{ default: Fuse }, index]) => {
      const docs: SearchDoc[] = index.datasets.map((entry) => ({
        entry,
        title: normalizeSearchText(entry.title),
        summary_he: normalizeSearchText(entry.summary_he ?? ""),
        organization: normalizeSearchText(entry.organization ?? ""),
        tags: (entry.tags ?? []).map(normalizeSearchText),
        hay: searchHaystack(entry),
      }));
      fuse.value = new Fuse<SearchDoc>(docs, {
        keys: [
          { name: "title", weight: 0.5 },
          { name: "summary_he", weight: 0.25 },
          { name: "organization", weight: 0.15 },
          { name: "tags", weight: 0.2 },
        ],
        threshold: 0.4,
        distance: 100,
        includeScore: true,
        minMatchCharLength: 2,
        ignoreLocation: true,
      });
    }
  )
);

interface SearchResults {
  items: SlimEntry[];
  /** The converted query text, when a shown result matched only through it. */
  convertedText: string | null;
  /** Some shown results also matched the query as typed. */
  rawHits: boolean;
}

const search = computed<SearchResults>(() => {
  const q = query.value.trim();
  const f = fuse.value;
  if (q.length < 2 || !f)
    return { items: [], convertedText: null, rawHits: false };
  const best = new Map<
    string,
    { entry: SlimEntry; score: number; via: string | null }
  >();
  for (const v of queryVariants(q)) {
    if (v.text.length < 2) continue;
    // A re-read of the query on the other keyboard layout counts only where
    // its text literally appears (as on /datasets/), so a Hebrew word re-read
    // as Latin gibberish doesn't pull in Fuse's fuzzy noise. Filter before
    // capping: fuzzy near-misses can outrank every literal match.
    const hits = v.converted
      ? f.search(v.text).filter((r) => r.item.hay.includes(v.text))
      : f.search(v.text, { limit: LIMIT });
    for (const r of hits.slice(0, LIMIT)) {
      const score = r.score ?? 1;
      const prev = best.get(r.item.entry.id);
      if (!prev || score < prev.score) {
        best.set(r.item.entry.id, {
          entry: r.item.entry,
          score,
          via: v.converted ? v.display : null,
        });
      }
    }
  }
  const top = [...best.values()]
    .sort((a, b) => a.score - b.score)
    .slice(0, LIMIT);
  return {
    items: top.map((t) => t.entry),
    convertedText: top.find((t) => t.via)?.via ?? null,
    rawHits: top.some((t) => !t.via),
  };
});
const results = computed(() => search.value.items);

function datasetHref(entry: SlimEntry): string {
  return datasetPath(entry);
}

const panel = computed(() =>
  panelState(query.value, loadState.value, results.value.length)
);

// New results drop the highlight: Enter means "all results" until an arrow
// key (or a pointer moving over a result) picks one. The links highlight on
// mousemove, not mouseenter: results rendered under a resting cursor would
// otherwise highlight a hit the user never pointed at, and Enter would open it.
watch(results, () => {
  highlight.value = NO_HIGHLIGHT;
});

// A failed load shows a "try again" line; reopening the popover retries too.
function load() {
  if (fuse.value) return;
  loadState.value = "loading";
  ensureFuse().then(
    () => {
      loadState.value = "ready";
    },
    () => {
      loadState.value = "failed";
    }
  );
}

function retry() {
  load();
  inputEl.value?.focus();
}

function toggle() {
  open.value = !open.value;
  if (open.value) {
    load();
    nextTick(() => inputEl.value?.focus());
  }
}

function close() {
  open.value = false;
  highlight.value = NO_HIGHLIGHT;
  buttonEl.value?.focus();
}

function go(entry: SlimEntry) {
  open.value = false;
  query.value = "";
  // Full-page nav (not router.push) — dataset pages are SSG documents that
  // read content.html / data.json / agent_data.json via node:fs in their
  // useAsyncData callback. With payloadExtraction disabled (Hebrew tag
  // prerender fix), Nuxt re-runs the callback on SPA nav and node:fs throws
  // in the browser. DatasetCard uses <a href> for the same reason.
  // Results render as <a href> for the same reason, which also gives
  // middle-click / Ctrl-click "open in a new tab" for free.
  window.location.assign(datasetHref(entry));
}

function submit() {
  const target = submitTarget(
    query.value,
    highlight.value,
    results.value.length
  );
  if (target?.kind === "hit") {
    go(results.value[target.index]!);
  } else if (target?.kind === "list") {
    open.value = false;
    query.value = "";
    highlight.value = NO_HIGHLIGHT;
    router.push({ path: "/datasets/", query: { q: target.q } });
  }
}

// Bound on the whole dialog, so Escape and the arrows also work while focus is
// on a result link (Tab) rather than in the input. The arrows move the
// highlight (exposed as the input's aria-activedescendant) and bring focus
// back to the input, where Enter opens the highlighted result (or, with
// nothing highlighted, the full list). The cycle passes through "nothing
// highlighted", so the arrows can return to the full-list Enter.
function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    e.preventDefault();
    close();
    return;
  }
  if (!results.value.length) return;
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  e.preventDefault();
  if (document.activeElement !== inputEl.value) inputEl.value?.focus();
  highlight.value = moveHighlight(e.key, highlight.value, results.value.length);
}

function onDocumentClick(e: MouseEvent) {
  if (!open.value) return;
  const t = e.target as Node;
  if (panelEl.value?.contains(t) || buttonEl.value?.contains(t)) return;
  open.value = false;
}

// A result link leaves the page with the popover still open (go() used to
// close and clear it first). Back navigation restores the page from the
// bfcache as it was left, so reset it there instead of on click, which would
// unmount the link mid-click.
function onPageShow(e: PageTransitionEvent) {
  if (!e.persisted) return;
  open.value = false;
  query.value = "";
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
      aria-label="חיפוש מאגרים"
      class="absolute top-full mt-2 end-0 w-[min(22rem,calc(100vw-2rem))] bg-white text-ink rounded-gov shadow-card border border-rule overflow-hidden z-50"
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
          aria-controls="header-search-results"
          :aria-expanded="results.length > 0"
          :aria-activedescendant="
            highlight >= 0 && results[highlight]
              ? `header-search-option-${highlight}`
              : undefined
          "
          placeholder="חיפוש מאגר, נושא או משרד…"
          class="flex-1 bg-transparent border-0 text-sm placeholder:text-subtle"
          @keydown.enter.prevent="submit"
        />
      </label>

      <p
        v-if="panel === 'results' && search.convertedText"
        class="m-0 px-3 pt-2 text-xs text-subtle"
      >
        {{ search.rawHits ? "מוצגות גם " : "" }}תוצאות עבור „<bdi>{{
          search.convertedText
        }}</bdi
        >”
      </p>
      <ul
        v-if="panel === 'results'"
        id="header-search-results"
        role="listbox"
        aria-label="תוצאות חיפוש"
        class="list-none m-0 p-0 max-h-80 overflow-y-auto"
      >
        <li
          v-for="(r, i) in results"
          :id="`header-search-option-${i}`"
          :key="r.id"
          role="option"
          :aria-selected="i === highlight"
        >
          <a
            :href="datasetHref(r)"
            class="w-full text-start px-3 py-2 flex flex-col gap-0.5 no-underline hover:no-underline hover:bg-brand-50 focus:bg-brand-50 transition-colors"
            :class="{ 'bg-brand-50': i === highlight }"
            @mousemove="highlight = i"
          >
            <span class="text-sm text-ink truncate">{{ r.title }}</span>
            <span v-if="r.organization" class="text-xs text-subtle truncate">{{
              r.organization
            }}</span>
          </a>
        </li>
      </ul>

      <div
        v-else-if="panel === 'loading'"
        class="px-3 py-4 text-sm text-subtle text-center"
        role="status"
      >
        טוען את רשימת המאגרים…
      </div>

      <div
        v-else-if="panel === 'failed'"
        class="px-3 py-4 text-sm text-subtle text-center"
        role="alert"
      >
        טעינת החיפוש נכשלה.
        <button
          type="button"
          class="text-brand-700 hover:underline bg-transparent border-0 p-0 cursor-pointer"
          @click="retry"
        >
          נסו שוב
        </button>
      </div>

      <div
        v-else-if="panel === 'empty'"
        class="px-3 py-4 text-sm text-subtle text-center"
      >
        אין תוצאות
      </div>

      <div v-else class="px-3 py-3 text-xs text-subtle">
        התחילו להקליד שם מאגר, נושא או משרד.
      </div>

      <div
        class="border-t border-rule px-3 py-2 text-xs text-subtle bg-surface flex items-center justify-between gap-2"
      >
        <span>{{
          highlight >= 0 && results[highlight]
            ? "הקשה על Enter תפתח את המאגר המסומן"
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
