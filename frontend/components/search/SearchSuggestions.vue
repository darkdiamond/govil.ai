<script setup lang="ts">
// The body of a search dropdown: grouped suggestions (topics, then datasets)
// with the matched text in bold, or the loading / failed / empty / prompt
// line. Shared by HeaderSearch.vue and home/HomeSearch.vue, which own the
// input, the keys and the open state (composables/useSiteSearch.ts).
import type { SpotlightPanel } from "~/composables/useSiteSearch";
import { datasetPath, tagPath } from "~/utils/paths";
import {
  type DatasetResults,
  highlightSegments,
  resultsAnnouncement,
  type TagHit,
} from "~/utils/site-search";
import { formatNumber as fmt } from "~/composables/useRelativeTime";

const props = defineProps<{
  query: string;
  panel: SpotlightPanel;
  datasets: DatasetResults;
  tags: TagHit[];
  highlight: number;
  listboxId: string;
  optionId: (i: number) => string;
}>();

const emit = defineEmits<{
  /** A pointer moved over option `i`. */
  hover: [i: number];
  retry: [];
  /** A link inside the panel was clicked. "page" = a full page load (a
   * dataset or the full list); "route" = an in-app route (a topic, /tags/). */
  navigate: [kind: "page" | "route"];
}>();

const q = computed(() => props.query.trim());
const listHref = computed(() => `/datasets/?q=${encodeURIComponent(q.value)}`);
const announcement = computed(() =>
  resultsAnnouncement(
    props.panel,
    props.datasets.items.length,
    props.tags.length
  )
);
// Topics render first (a compact row of chips that stays in view above the
// datasets), so the flattened option list starts with them.
const datasetOffset = computed(() => props.tags.length);

// The list scrolls past its max height: keep the highlighted option in view.
watch(
  () => props.highlight,
  (h) => {
    if (h < 0) return;
    nextTick(() =>
      document
        .getElementById(props.optionId(h))
        ?.scrollIntoView({ block: "nearest" })
    );
  }
);
</script>

<template>
  <div>
    <p class="sr-only" aria-live="polite" aria-atomic="true">
      {{ announcement }}
    </p>

    <template v-if="panel === 'results'">
      <p
        v-if="datasets.convertedText"
        class="m-0 px-3 pt-2 text-xs text-subtle"
      >
        {{ datasets.rawHits ? "מוצגות גם " : "" }}תוצאות עבור „<bdi>{{
          datasets.convertedText
        }}</bdi
        >”
      </p>
      <div
        :id="listboxId"
        role="listbox"
        aria-label="תוצאות חיפוש"
        class="max-h-[min(24rem,55vh)] overflow-y-auto overscroll-contain py-1"
      >
        <div
          v-if="tags.length"
          role="group"
          :aria-labelledby="`${listboxId}-tags`"
          class="px-3 pt-1.5 pb-2"
          :class="{ 'border-b border-rule mb-1': datasets.items.length }"
        >
          <div
            :id="`${listboxId}-tags`"
            role="presentation"
            class="pb-1.5 text-xs font-medium text-subtle"
          >
            נושאים
          </div>
          <div class="flex flex-wrap gap-1.5">
            <NuxtLink
              v-for="(t, j) in tags"
              :id="optionId(j)"
              :key="t.slug"
              role="option"
              :aria-selected="j === highlight"
              :to="tagPath(t.slug)"
              class="inline-flex items-center gap-1.5 max-w-full ps-2 pe-2.5 py-1 text-sm text-ink border rounded-gov-pill no-underline hover:no-underline transition-colors"
              :class="
                j === highlight
                  ? 'bg-brand-100 border-brand'
                  : 'bg-white border-rule'
              "
              @mousemove="emit('hover', j)"
              @click="emit('navigate', 'route')"
            >
              <img
                src="/icons/tag.svg"
                alt=""
                class="w-3.5 h-3.5 shrink-0 opacity-60"
              />
              <span class="truncate"
                ><template
                  v-for="(s, k) in highlightSegments(t.name, query)"
                  :key="k"
                  ><strong v-if="s.match" class="font-semibold text-ink-deep">{{
                    s.text
                  }}</strong
                  ><template v-else>{{ s.text }}</template></template
                ></span
              >
              <span class="shrink-0 text-xs text-subtle tabular-nums"
                >{{ fmt(t.count) }}<span class="sr-only"> מאגרים</span></span
              >
            </NuxtLink>
          </div>
        </div>

        <div
          v-if="datasets.items.length"
          role="group"
          :aria-labelledby="`${listboxId}-datasets`"
        >
          <div
            :id="`${listboxId}-datasets`"
            role="presentation"
            class="px-3 pt-1.5 pb-1 text-xs font-medium text-subtle"
          >
            מאגרים
          </div>
          <a
            v-for="(r, i) in datasets.items"
            :id="optionId(datasetOffset + i)"
            :key="r.id"
            role="option"
            :aria-selected="datasetOffset + i === highlight"
            :href="datasetPath(r)"
            class="px-3 py-2 flex flex-col gap-0.5 no-underline hover:no-underline transition-colors"
            :class="datasetOffset + i === highlight ? 'bg-brand-100' : ''"
            @mousemove="emit('hover', datasetOffset + i)"
            @click="emit('navigate', 'page')"
          >
            <span class="text-sm text-ink truncate"
              ><template
                v-for="(s, k) in highlightSegments(r.title, query)"
                :key="k"
                ><strong v-if="s.match" class="font-semibold text-ink-deep">{{
                  s.text
                }}</strong
                ><template v-else>{{ s.text }}</template></template
              ></span
            >
            <span v-if="r.organization" class="text-xs text-subtle truncate">{{
              r.organization
            }}</span>
          </a>
        </div>
      </div>
    </template>

    <div
      v-else-if="panel === 'loading'"
      class="px-3 py-4 text-sm text-subtle text-center"
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
        @click="emit('retry')"
      >
        נסו שוב
      </button>
    </div>

    <div v-else-if="panel === 'empty'" class="px-3 py-4 text-sm">
      <p class="m-0 text-ink">
        אין הצעות עבור „<bdi>{{ q }}</bdi
        >”.
      </p>
      <p class="m-0 mt-1 text-subtle">
        אפשר
        <a
          :href="listHref"
          class="text-brand-700"
          @click="emit('navigate', 'page')"
          >לחפש את המילים בכל המאגרים</a
        >
        או
        <NuxtLink
          to="/tags/"
          class="text-brand-700"
          @click="emit('navigate', 'route')"
          >לעבור על הנושאים</NuxtLink
        >.
      </p>
    </div>

    <div v-else class="px-3 py-3 text-xs text-subtle">
      התחילו להקליד שם מאגר, נושא או משרד.
    </div>
  </div>
</template>
