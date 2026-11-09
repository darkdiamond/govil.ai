<script setup lang="ts">
import type FuseT from "fuse.js";
import type { SlimEntry } from "~/types/manifest";
import { loadSearchIndex } from "~/utils/search-index";
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
const highlight = ref(-1);
const buttonEl = ref<HTMLElement | null>(null);
const inputEl = ref<HTMLInputElement | null>(null);
const panelEl = ref<HTMLElement | null>(null);

// Fuse.js (~24KB min+gz) and the slim search index (~60KB gz) only fire when
// the user opens the search popover, so both load on first toggle rather than
// being bundled into the layout chunk. This runs client-side only — the
// popover is never part of prerendered HTML.
const fuse = shallowRef<FuseT<SearchDoc> | null>(null);
let fusePromise: Promise<void> | null = null;

function ensureFuse(): Promise<void> {
  if (fusePromise) return fusePromise;
  fusePromise = Promise.all([import("fuse.js"), loadSearchIndex()]).then(
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
  );
  return fusePromise;
}

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
  return `/datasets/${encodeURI(entry.page_slug || entry.id)}/`;
}

watch(results, () => {
  highlight.value = results.value.length > 0 ? 0 : -1;
});

function toggle() {
  open.value = !open.value;
  if (open.value) {
    ensureFuse();
    nextTick(() => inputEl.value?.focus());
  }
}

function close() {
  open.value = false;
  highlight.value = -1;
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
  const q = query.value.trim();
  const hit = highlight.value >= 0 ? results.value[highlight.value] : undefined;
  if (hit) {
    go(hit);
    return;
  }
  if (q) {
    open.value = false;
    query.value = "";
    router.push({ path: "/datasets/", query: { q } });
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    e.preventDefault();
    close();
    return;
  }
  if (!results.value.length) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    highlight.value = (highlight.value + 1) % results.value.length;
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    highlight.value =
      highlight.value <= 0 ? results.value.length - 1 : highlight.value - 1;
  }
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
          placeholder="חיפוש מאגר, נושא או משרד…"
          class="flex-1 bg-transparent border-0 text-sm placeholder:text-subtle"
          @keydown="onKeydown"
          @keydown.enter.prevent="submit"
        />
      </label>

      <p
        v-if="results.length && search.convertedText"
        class="m-0 px-3 pt-2 text-xs text-subtle"
      >
        {{ search.rawHits ? "מוצגות גם " : "" }}תוצאות עבור „<bdi>{{
          search.convertedText
        }}</bdi
        >”
      </p>
      <ul
        v-if="results.length"
        class="list-none m-0 p-0 max-h-80 overflow-y-auto"
      >
        <li v-for="(r, i) in results" :key="r.id">
          <a
            :href="datasetHref(r)"
            class="w-full text-start px-3 py-2 flex flex-col gap-0.5 no-underline hover:no-underline hover:bg-brand-50 focus:bg-brand-50 transition-colors"
            :class="{ 'bg-brand-50': i === highlight }"
            @mouseenter="highlight = i"
          >
            <span class="text-sm text-ink truncate">{{ r.title }}</span>
            <span v-if="r.organization" class="text-xs text-subtle truncate">{{
              r.organization
            }}</span>
          </a>
        </li>
      </ul>

      <div
        v-else-if="query.trim().length >= 2"
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
        <span>הקשה על Enter תפתח את כל התוצאות</span>
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
