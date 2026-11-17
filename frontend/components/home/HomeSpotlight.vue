<script setup lang="ts">
// The homepage search's panel: topic and ministry chips, the dataset list,
// and (md and up) a preview of the highlighted dataset. Before anything is
// typed it offers the biggest topics and the newest renders. State and keys
// live in home/HomeSearch.vue (composables/useSiteSearch.ts); this renders.
import type { SlimEntry } from "~/types/manifest";
import type { SpotlightPanel } from "~/composables/useSiteSearch";
import { KIND_INFO } from "~/composables/useKindLabels";
import {
  formatNumber as fmt,
  relativeTimeHe,
} from "~/composables/useRelativeTime";
import { datasetPath, ministryPath, tagPath } from "~/utils/paths";
import {
  type DatasetResults,
  highlightSegments,
  type NamedHit,
  resultsAnnouncement,
  snippetAround,
} from "~/utils/site-search";

const props = defineProps<{
  query: string;
  active: boolean;
  panel: SpotlightPanel;
  datasets: DatasetResults;
  tags: NamedHit[];
  ministries: NamedHit[];
  total: number;
  highlight: number;
  preview: SlimEntry | null;
  listboxId: string;
  optionId: (i: number) => string;
}>();

const emit = defineEmits<{
  hover: [i: number];
  retry: [];
  /** "route": an in-app route (the host closes the panel); "page": a full
   * page load (left as is; back from the bfcache resets it). */
  navigate: [kind: "page" | "route"];
}>();

const q = computed(() => props.query.trim());
const showList = computed(
  () => props.panel === "results" || props.panel === "idle"
);
const ministryOffset = computed(() => props.tags.length);
const datasetOffset = computed(
  () => props.tags.length + props.ministries.length
);
const announcement = computed(() =>
  resultsAnnouncement(
    props.panel === "idle" ? "" : props.panel,
    props.datasets.items.length,
    props.tags.length,
    props.ministries.length
  )
);
const listHref = computed(() =>
  q.value ? `/datasets/?q=${encodeURIComponent(q.value)}` : "/datasets/"
);

const kindOf = (d: SlimEntry) =>
  d.dataset_kind ? KIND_INFO[d.dataset_kind] : null;
const seg = (text: string) =>
  props.active
    ? highlightSegments(text, props.query)
    : [{ text, match: false }];

const CHIP =
  "inline-flex items-center gap-1.5 max-w-full ps-2.5 pe-3 py-1.5 text-sm border rounded-gov-pill no-underline hover:no-underline motion-safe:transition-colors";

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
  <div class="spotlight">
    <p class="sr-only" aria-live="polite" aria-atomic="true">
      {{ announcement }}
    </p>

    <div
      v-if="showList"
      :id="listboxId"
      role="listbox"
      aria-label="הצעות חיפוש"
    >
      <!-- Chips: topics, then ministries. Always in view above the list. -->
      <div
        v-if="tags.length || ministries.length"
        class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 sm:px-5 pt-4 pb-3 border-b border-rule"
      >
        <div
          v-if="tags.length"
          role="group"
          :aria-labelledby="`${listboxId}-tags`"
          class="flex flex-wrap items-center gap-1.5"
        >
          <span
            :id="`${listboxId}-tags`"
            role="presentation"
            class="text-xs font-medium text-subtle me-1"
            >{{ active ? "נושאים" : "נושאים מרכזיים" }}</span
          >
          <NuxtLink
            v-for="(t, j) in tags"
            :id="optionId(j)"
            :key="t.slug"
            role="option"
            :aria-selected="j === highlight"
            :to="tagPath(t.slug)"
            :class="[
              CHIP,
              j === highlight
                ? 'bg-brand-100 border-brand text-ink-deep'
                : 'bg-white border-rule text-ink hover:border-brand',
              // Before typing, a phone shows only the 3 biggest topics.
              { 'max-sm:hidden': !active && j >= 3 },
            ]"
            @mousemove="emit('hover', j)"
            @click="emit('navigate', 'route')"
          >
            <img src="/icons/tag.svg" alt="" class="w-3.5 h-3.5 opacity-60" />
            <span class="truncate"
              ><template v-for="(s, k) in seg(t.name)" :key="k"
                ><strong v-if="s.match" class="font-semibold text-ink-deep">{{
                  s.text
                }}</strong
                ><template v-else>{{ s.text }}</template></template
              ></span
            >
            <span class="text-xs text-subtle tabular-nums"
              >{{ fmt(t.count) }}<span class="sr-only"> מאגרים</span></span
            >
          </NuxtLink>
        </div>
        <div
          v-if="ministries.length"
          role="group"
          :aria-labelledby="`${listboxId}-ministries`"
          class="flex flex-wrap items-center gap-1.5"
        >
          <span
            :id="`${listboxId}-ministries`"
            role="presentation"
            class="text-xs font-medium text-subtle me-1"
            >גופים</span
          >
          <NuxtLink
            v-for="(m, j) in ministries"
            :id="optionId(ministryOffset + j)"
            :key="m.slug"
            role="option"
            :aria-selected="ministryOffset + j === highlight"
            :to="ministryPath(m.slug)"
            :class="[
              CHIP,
              ministryOffset + j === highlight
                ? 'bg-brand-100 border-brand text-ink-deep'
                : 'bg-white border-rule text-ink hover:border-brand',
            ]"
            @mousemove="emit('hover', ministryOffset + j)"
            @click="emit('navigate', 'route')"
          >
            <img
              src="/icons/building-2.svg"
              alt=""
              class="w-3.5 h-3.5 opacity-60"
            />
            <span class="truncate"
              ><template v-for="(s, k) in seg(m.name)" :key="k"
                ><strong v-if="s.match" class="font-semibold text-ink-deep">{{
                  s.text
                }}</strong
                ><template v-else>{{ s.text }}</template></template
              ></span
            >
            <span class="text-xs text-subtle tabular-nums"
              >{{ fmt(m.count) }}<span class="sr-only"> מאגרים</span></span
            >
          </NuxtLink>
        </div>
      </div>

      <p
        v-if="active && datasets.convertedText"
        class="m-0 px-4 sm:px-5 pt-3 text-xs text-subtle"
      >
        {{ datasets.rawHits ? "מוצגות גם " : "" }}תוצאות עבור „<bdi>{{
          datasets.convertedText
        }}</bdi
        >”
      </p>

      <div class="md:grid md:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
        <!-- The dataset list. -->
        <div
          v-if="datasets.items.length"
          role="group"
          :aria-labelledby="`${listboxId}-datasets`"
          class="max-h-[min(26rem,52vh)] overflow-y-auto overscroll-contain py-2"
        >
          <div
            :id="`${listboxId}-datasets`"
            role="presentation"
            class="px-4 sm:px-5 pt-1 pb-1.5 text-xs font-medium text-subtle"
          >
            {{ active ? "מאגרים" : "עודכנו לאחרונה" }}
          </div>
          <a
            v-for="(d, i) in datasets.items"
            :id="optionId(datasetOffset + i)"
            :key="d.id"
            role="option"
            :aria-selected="datasetOffset + i === highlight"
            :href="datasetPath(d)"
            class="flex items-start gap-3 ps-4 sm:ps-5 pe-4 py-2.5 border-s-[3px] no-underline hover:no-underline motion-safe:transition-colors"
            :class="
              datasetOffset + i === highlight
                ? 'bg-brand-100 border-brand'
                : 'border-transparent'
            "
            @mousemove="emit('hover', datasetOffset + i)"
            @click="emit('navigate', 'page')"
          >
            <img
              :src="kindOf(d)?.icon ?? '/icons/database.svg'"
              alt=""
              class="mt-0.5 w-4 h-4 shrink-0 opacity-50"
            />
            <span class="min-w-0 flex flex-col gap-0.5">
              <span class="text-[0.95rem] text-ink leading-snug line-clamp-2"
                ><template v-for="(s, k) in seg(d.title)" :key="k"
                  ><strong v-if="s.match" class="font-semibold text-ink-deep">{{
                    s.text
                  }}</strong
                  ><template v-else>{{ s.text }}</template></template
                ></span
              >
              <span
                v-if="d.summary_he && active"
                class="md:hidden text-xs text-subtle line-clamp-1"
                >{{ snippetAround(d.summary_he, query, 90) }}</span
              >
              <span class="text-xs text-subtle truncate">
                {{ d.organization }}
                <template v-if="active && d.record_count">
                  <span aria-hidden="true" class="mx-1 text-rule">|</span>
                  {{ fmt(d.record_count) }} רשומות
                </template>
                <template v-else-if="!active && d.last_analyzed_at">
                  <span aria-hidden="true" class="mx-1 text-rule">|</span>
                  עודכן {{ relativeTimeHe(d.last_analyzed_at) }}
                </template>
              </span>
            </span>
          </a>
        </div>

        <!-- Preview of the highlighted (else first) dataset. Visual: the same
             link is the option itself, so screen readers skip this. -->
        <aside
          v-if="preview"
          aria-hidden="true"
          class="hidden md:flex flex-col bg-surface border-s border-rule p-5 min-h-full"
        >
          <div :key="preview.id" class="preview flex flex-col gap-3 h-full">
            <div class="flex flex-wrap items-center gap-2 text-xs">
              <span
                v-if="kindOf(preview)"
                class="inline-flex items-center gap-1 px-2 py-0.5 bg-white border border-rule rounded-gov-sm text-ink"
              >
                <img :src="kindOf(preview)!.icon" alt="" class="w-3 h-3" />
                {{ kindOf(preview)!.label }}
              </span>
              <span
                v-if="preview.source_status === 'unavailable'"
                class="px-2 py-0.5 rounded-gov-sm bg-white border border-danger text-danger"
                >הוסר מהמקור</span
              >
              <span v-else-if="preview.last_analyzed_at" class="text-subtle"
                >עודכן {{ relativeTimeHe(preview.last_analyzed_at) }}</span
              >
            </div>
            <div>
              <p
                class="m-0 text-lg font-semibold text-ink-deep leading-snug text-balance"
              >
                <template v-for="(s, k) in seg(preview.title)" :key="k"
                  ><mark v-if="s.match" class="hl">{{ s.text }}</mark
                  ><template v-else>{{ s.text }}</template></template
                >
              </p>
              <p
                v-if="preview.organization"
                class="m-0 mt-1 text-sm text-subtle"
              >
                {{ preview.organization }}
              </p>
            </div>
            <p
              v-if="preview.summary_he"
              class="m-0 text-sm text-ink leading-relaxed line-clamp-6"
            >
              <template
                v-for="(s, k) in seg(snippetAround(preview.summary_he, query))"
                :key="k"
                ><mark v-if="s.match" class="hl">{{ s.text }}</mark
                ><template v-else>{{ s.text }}</template></template
              >
            </p>
            <dl
              class="m-0 grid grid-cols-2 gap-px bg-rule border border-rule rounded-gov overflow-hidden text-sm"
            >
              <div v-if="preview.record_count" class="bg-white px-3 py-2">
                <dt class="text-xs text-subtle">רשומות</dt>
                <dd class="m-0 font-semibold text-ink-deep tabular-nums">
                  {{ fmt(preview.record_count) }}
                </dd>
              </div>
              <div v-if="preview.metadata_modified" class="bg-white px-3 py-2">
                <dt class="text-xs text-subtle">עדכון במקור</dt>
                <dd class="m-0 font-semibold text-ink-deep">
                  {{ relativeTimeHe(preview.metadata_modified) }}
                </dd>
              </div>
              <div v-if="preview.spatial_coverage" class="bg-white px-3 py-2">
                <dt class="text-xs text-subtle">כיסוי</dt>
                <dd class="m-0 font-semibold text-ink-deep truncate">
                  {{ preview.spatial_coverage }}
                </dd>
              </div>
              <div v-if="preview.formats?.length" class="bg-white px-3 py-2">
                <dt class="text-xs text-subtle">קבצים</dt>
                <dd class="m-0 font-semibold text-ink-deep truncate">
                  {{ preview.formats.slice(0, 3).join(", ") }}
                </dd>
              </div>
            </dl>
            <div
              v-if="preview.tags?.length"
              class="flex flex-wrap gap-1.5 text-xs"
            >
              <span
                v-for="t in preview.tags.slice(0, 4)"
                :key="t"
                class="px-2 py-0.5 rounded-gov-pill bg-white border border-rule text-ink"
                >{{ t }}</span
              >
            </div>
            <a
              :href="datasetPath(preview)"
              tabindex="-1"
              class="btn-primary mt-auto self-start px-4 py-2 text-sm font-medium no-underline hover:no-underline"
              @click="emit('navigate', 'page')"
              >לעמוד המאגר</a
            >
          </div>
        </aside>
      </div>
    </div>

    <div
      v-else-if="panel === 'loading'"
      class="px-5 py-8 text-sm text-subtle text-center"
    >
      טוען את רשימת המאגרים…
    </div>

    <div
      v-else-if="panel === 'failed'"
      class="px-5 py-8 text-sm text-subtle text-center"
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

    <div v-else-if="panel === 'empty'" class="px-5 py-6">
      <p class="m-0 text-base text-ink">
        אין הצעות עבור „<bdi>{{ q }}</bdi
        >”.
      </p>
      <p class="m-0 mt-1 text-sm text-subtle">
        אפשר
        <a
          :href="listHref"
          class="text-brand-700"
          @click="emit('navigate', 'page')"
          >לחפש את המילים בתקצירי כל המאגרים</a
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

    <!-- Footer: the keys, and the full results page. -->
    <div
      v-if="panel !== 'loading' && panel !== 'failed'"
      class="flex items-center justify-between gap-3 px-4 sm:px-5 py-2.5 border-t border-rule bg-surface-alt text-xs text-subtle"
    >
      <span class="hidden md:flex items-center gap-3">
        <span><kbd>↑</kbd><kbd>↓</kbd> בחירה</span>
        <span><kbd>Enter</kbd> פתיחה</span>
        <span><kbd>Esc</kbd> סגירה</span>
      </span>
      <a
        :href="listHref"
        class="ms-auto text-sm font-medium text-brand-700 no-underline hover:underline"
        @click="emit('navigate', 'page')"
      >
        <template v-if="active && total">
          לכל {{ fmt(total) }} התוצאות עבור „<bdi>{{ q }}</bdi
          >”
        </template>
        <template v-else>לכל המאגרים</template>
      </a>
    </div>
  </div>
</template>

<style scoped>
/* The panel opens with a short drop; a new preview fades in. Both answer the
   user's action, and both are off under reduced motion. */
@media (prefers-reduced-motion: no-preference) {
  .spotlight {
    animation: spotlight-in 160ms ease-out;
  }
  .preview {
    animation: preview-in 140ms ease-out;
  }
}
@keyframes spotlight-in {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
}
@keyframes preview-in {
  from {
    opacity: 0;
  }
}
.hl {
  background: #fff3bf;
  color: inherit;
  border-radius: 0.15rem;
  padding: 0 0.1em;
}
kbd {
  display: inline-block;
  min-width: 1.4em;
  margin-inline-end: 0.2em;
  padding: 0 0.35em;
  font: inherit;
  font-size: 0.7rem;
  line-height: 1.5;
  text-align: center;
  color: #0c3058;
  background: #fff;
  border: 1px solid #c3cfe7;
  border-bottom-width: 2px;
  border-radius: 0.2rem;
}
</style>
