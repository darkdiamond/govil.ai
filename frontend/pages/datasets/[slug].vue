<script setup lang="ts">
import {
  buildDatasetLd,
  datasetDescription,
  datasetName,
  datasetSeoTitle,
} from "~/composables/useDatasetLd";
import { KIND_INFO } from "~/composables/useKindLabels";
import { formatBytes, formatNumber } from "~/composables/useRelativeTime";
import type { AgentData, DatasetMeta, ManifestEntry } from "~/types/manifest";
import { datasetDate, laterIsraelDay } from "~/utils/dataset-dates";
import { awaitDatasetLibs, executeBodyScripts } from "~/utils/body-scripts";
import { buildDatasetLibTags, detectDatasetLibs } from "~/utils/dataset-libs";
import { loadFullManifestServer } from "~/utils/search-index";
import { loadNewsIndexServer } from "~/utils/news";
import { normalizeAgentBody } from "~/utils/normalize-agent-body";
import { datasetPath, SITE_URL, tagPath } from "~/utils/paths";
import { publicResourceUrl, resourceFormat } from "~/utils/resource-url";

const route = useRoute();
const slug = String(route.params.slug);

interface RelatedEntry {
  id: string;
  page_slug?: string;
  title: string;
  organization?: string;
  summary_he?: string;
  /** Paged tags this dataset shares with the page, most specific first. */
  shared_tags?: string[];
}

const { data } = await useAsyncData(`dataset-${slug}`, async () => {
  // Guard the node imports so Vite's client bundler can tree-shake
  // them out — they're SSR/prerender-only. Without the guard Vite
  // emits a "Module 'node:fs/promises' has been externalized for
  // browser compatibility" warning per build. On the client useAsyncData
  // hydrates from the prerendered payload. With payloadExtraction off a
  // client-side navigation would re-run this fetcher and 404, so
  // middleware/dataset-document.global.ts turns every one (Back included)
  // into a document load.
  if (!import.meta.server) return null;
  const fs = await import("node:fs/promises");
  const path = await import("node:path");

  // The URL carries the page_slug; on-disk artifacts are keyed by the CKAN
  // id (single writer per file — see CLAUDE.md). Resolve slug → id via the
  // manifest, which this page loads anyway for related/tag data below. An
  // unknown slug (or a checkout with no manifest) falls through to 404.
  const manifest = await loadFullManifestServer();
  const me = manifest.datasets.find((d) => (d.page_slug || d.id) === slug);
  if (!me) return null;
  const id = me.id;
  // A local recipe preview (nuxt.config.ts PREVIEW_ROOT) serves its staged
  // render from the overlay; everything else reads public/.
  const overlay = process.env.NUXT_PREVIEW_ROOT;
  const staged = overlay && path.join(overlay, "datasets", id);
  const dir =
    staged &&
    (await fs.stat(path.join(staged, "content.html")).catch(() => null))
      ? staged
      : path.resolve(process.cwd(), "public/datasets", id);

  // Three artifacts, two writers:
  //   - content.html      : agent body, synced from GCS staging
  //   - data.json         : DatasetMeta, written by the publisher from Firestore
  //   - agent_data.json   : AgentData,   written by the publisher from Firestore.
  //                         Optional — a scanned-but-never-analyzed source has none.
  const [rawBody, metaRaw, agentRaw] = await Promise.all([
    fs.readFile(path.join(dir, "content.html"), "utf-8"),
    fs.readFile(path.join(dir, "data.json"), "utf-8"),
    fs.readFile(path.join(dir, "agent_data.json"), "utf-8").catch(() => null),
  ]);

  const meta = JSON.parse(metaRaw) as DatasetMeta;
  const agent = (agentRaw ? JSON.parse(agentRaw) : null) as AgentData | null;

  // Merge into a ManifestEntry-shaped object so existing template paths
  // (entry.summary_he, entry.dataset_kind, …) keep working. `tags` and
  // `related_ids` are publisher-computed (canonical tags from taxonomy/,
  // content-based related picks) and come from the manifest entry, not
  // from agent_data's deprecated suggested_tags / related_ids.
  const entry: ManifestEntry = {
    ...meta,
    summary_he: agent?.summary_he,
    dataset_kind: agent?.dataset_kind,
    temporal_coverage: agent?.temporal_coverage as string | undefined,
    spatial_coverage: agent?.spatial_coverage as string | undefined,
    suggested_tags: (agent?.suggested_tags as string[] | undefined) ?? [],
    seo: agent?.seo,
    tags: me.tags ?? [],
    related_ids: [],
  };

  // Resolve everything this page needs from the full manifest HERE, at
  // prerender time, so the client never ships or fetches manifest data:
  // the publisher's deterministic related_ids → 5 sidebar snippets, plus
  // the tag→slug map for just this page's chips (paged tags only — the
  // rest render unlinked). Both land in the inlined payload alongside
  // entry/rawBody.
  let related: RelatedEntry[] = [];
  let tagSlugs: Record<string, string> = {};
  try {
    const tagIndex = manifest.tag_index ?? {};
    for (const t of entry.tags ?? []) {
      const slug = tagIndex[t]?.slug;
      if (slug) tagSlugs[t] = slug;
    }
    const byId = new Map(manifest.datasets.map((d) => [d.id, d]));
    related = (me.related_ids ?? [])
      .map((rid) => byId.get(rid))
      .filter((d): d is ManifestEntry => Boolean(d))
      .slice(0, 5)
      .map((d) => ({
        id: d.id,
        page_slug: d.page_slug,
        title: d.title,
        organization: d.organization,
        summary_he: d.summary_he,
        // The most specific shared paged tags (fewest datasets) say why
        // this one is related; the broad topic tag rarely does.
        shared_tags: (d.tags ?? [])
          .filter((t) => t in tagSlugs)
          .sort((a, b) => tagIndex[a]!.count - tagIndex[b]!.count)
          .slice(0, 2),
      }));
  } catch {
    // Defensive — manifest is already loaded above, so this rarely trips.
  }

  // Detect which viz libs the agent body actually references so the page
  // loads only those (the raw body is the honest signal — a script can't
  // call a global without naming it).
  const libs = detectDatasetLibs(rawBody);

  // The latest news articles that drew on this dataset (services/news).
  const news = (await loadNewsIndexServer())
    .filter((a) => (a.dataset_ids ?? []).includes(id))
    .slice(0, 3);

  return { entry, rawBody, related, tagSlugs, libs, news };
});

if (!data.value) {
  throw createError({
    statusCode: 404,
    statusMessage: "Dataset not found",
    fatal: true,
  });
}

const entry = computed(() => data.value!.entry);

// Per-page conditional lib tags, derived from the payload's `libs` flags —
// identical server/client, so unhead dedupes by src on hydration. These
// head tags are the only external resources a dataset page loads.
useHead(buildDatasetLibTags(data.value.libs));

const related = computed<RelatedEntry[]>(() => data.value!.related ?? []);

// Canonical tags (services/page_builder/tags.py). Only tags carried by
// enough datasets have a /tags/<slug>/ page; the rest render unlinked.
const tagSlugs = computed(() => data.value!.tagSlugs ?? {});
function tagHref(t: string): string | undefined {
  const slug = tagSlugs.value[t];
  return slug ? tagPath(slug) : undefined;
}

// Used both for the title-row chips injected into the body and the
// sidebar "תגיות" list.
const allTags = computed<string[]>(() => entry.value.tags ?? []);

const titleChips = computed(() =>
  allTags.value.map((label) => ({ label, href: tagHref(label) }))
);

// Single ingress point for every agent body — see normalizeAgentBody().
// Strips the legacy chip wrapper (so old pages don't render two rows)
// and injects the new clickable chip row right after the H1.
const body = computed(() =>
  normalizeAgentBody(data.value!.rawBody, { titleChips: titleChips.value })
);

const kindLabel = computed(() =>
  entry.value.dataset_kind
    ? (KIND_INFO[entry.value.dataset_kind]?.label ?? "אחר")
    : ""
);

const hasMeta = computed(() =>
  Boolean(
    entry.value.organization ||
    entry.value.license ||
    entry.value.last_analyzed_at ||
    entry.value.analyzed_metadata_modified ||
    entry.value.record_count != null
  )
);

// "המידע נכון ל-" displays the data vintage. For sources analyzed after
// the pipeline started snapshotting metadata_modified at analysis time,
// that's the authoritative snapshot. For legacy sources (analyzed_metadata_modified
// is null), fall back to last_analyzed_at so the row still renders.
const dataVintage = computed<string | null>(
  () =>
    entry.value.analyzed_metadata_modified ??
    entry.value.last_analyzed_at ??
    null
);

// Show the "updated since analysis" info icon when CKAN's live
// metadata_modified has moved to a later UTC calendar day than the
// authoritative snapshot. Suppressed for legacy sources without a
// snapshot — we don't know what version the agent saw, so we can't
// honestly claim the source has been updated since.
// Non-CKAN sources (services/providers) carry a credit block; data.gov.il
// datasets don't, and get the defaults: data.gov.il + the live explorer.
const sourceInfo = computed(() => entry.value.source ?? null);
const sourceName = computed(
  () => sourceInfo.value?.source_name_he ?? "data.gov.il"
);
const hasExplorer = computed(() => sourceInfo.value?.explorer ?? true);
// Same scheme filter as the download buttons: only http(s) reaches an href.
const sourceHref = computed(() =>
  publicResourceUrl(sourceInfo.value?.source_url || sourceInfo.value?.home_url)
);
const termsHref = computed(() =>
  publicResourceUrl(sourceInfo.value?.terms_url)
);

const sourceUpdatedSinceAnalysis = computed<boolean>(() => {
  // The icon points at the live explorer; without one it has nothing to offer.
  if (!hasExplorer.value) return false;
  // Israel calendar days, as the dates on the page are shown.
  return laterIsraelDay(
    entry.value.metadata_modified,
    entry.value.analyzed_metadata_modified
  );
});

function formatDateHe(iso?: string | null): string {
  return datasetDate(iso);
}
function formatClass(fmt?: string | null): string {
  switch ((fmt || "").toUpperCase()) {
    case "CSV":
      return "fmt-csv";
    case "PDF":
      return "fmt-pdf";
    case "XLSX":
    case "XLS":
      return "fmt-xlsx";
    case "JSON":
      return "fmt-json";
    default:
      return "fmt-default";
  }
}

// page_slug is the URL segment (Hebrew title slug + id slice); encode for the
// wire since it contains Hebrew. Fall back to id for any legacy entry missing it.
const pagePath = datasetPath(entry.value);
const datasetUrl = `${SITE_URL}${pagePath}`;

// Archive banner date — reuses formatDateHe (defined above, alongside
// dataVintage/last_analyzed_at) so the "as of" phrasing matches the rest of
// this page's date formatting. Empty when the source has no stamped
// unavailable_since (legacy/edge case) — the banner still renders its main
// sentence without the trailing clause.
const unavailableSinceHe = computed(() =>
  formatDateHe(entry.value.unavailable_since)
);

const seoDescription = datasetDescription(entry.value);

const breadcrumbs = [
  { name: "ראשי", url: `${SITE_URL}/` },
  { name: "מאגרים", url: `${SITE_URL}/datasets/` },
  ...(entry.value.organization && entry.value.organization_slug
    ? [
        {
          name: entry.value.organization,
          url: `${SITE_URL}/ministries/${entry.value.organization_slug}/`,
        },
      ]
    : []),
  { name: datasetName(entry.value), url: datasetUrl },
];

const datasetLd = buildDatasetLd(entry.value, { canonical: datasetUrl });

useSeo({
  title: datasetSeoTitle(entry.value),
  description: seoDescription,
  path: pagePath,
  author: entry.value.organization,
  breadcrumbs,
  extraJsonLd: datasetLd,
});

// The <article> the body is v-html'd into. Its inline <script>s are re-run on
// mount by executeBodyScripts (utils/body-scripts.ts, which explains why).
const bodyEl = ref<HTMLElement | null>(null);

// Registered here, not inside onMounted: a hook registered after an await
// is not bound to the component and never runs.
let raf = 0;
let ro: ResizeObserver | null = null;
let unmounted = false;
onBeforeUnmount(() => {
  unmounted = true;
  cancelAnimationFrame(raf);
  ro?.disconnect();
});

onMounted(async () => {
  await awaitDatasetLibs(data.value!.libs);
  if (unmounted || !bodyEl.value) return;
  void executeBodyScripts(bodyEl.value);
  // Bridge container-width changes (orientation, sidebar reflow at lg) into
  // a window resize so ECharts re-fits via the agent's existing
  // `chart.resize()` listeners. rAF-debounced to coalesce smooth resizes.
  ro = new ResizeObserver(() => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() =>
      window.dispatchEvent(new Event("resize"))
    );
  });
  ro.observe(bodyEl.value);
});
</script>

<template>
  <div>
    <div class="border-b border-rule bg-white">
      <div
        class="max-w-gov mx-auto px-4 py-1.5 text-xs text-subtle flex items-center gap-3"
      >
        <nav aria-label="breadcrumb" class="min-w-0 flex-1">
          <NuxtLink to="/">ראשי</NuxtLink>
          <template v-if="entry.organization && entry.organization_slug">
            <span class="mx-1">›</span>
            <NuxtLink :to="`/ministries/${entry.organization_slug}/`">{{
              entry.organization
            }}</NuxtLink>
          </template>
          <span class="mx-1">›</span>
          <span>{{ datasetName(entry) }}</span>
        </nav>
        <ShareButton
          class="shrink-0"
          :url="datasetUrl"
          :title="datasetName(entry)"
          :text="seoDescription"
          content-type="dataset"
          :item-id="entry.id"
        />
      </div>
    </div>

    <div
      class="max-w-gov mx-auto px-4 py-8 grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-8"
    >
      <!-- min-w-0 keeps the explorer's wide table from blowing out the 1fr track -->
      <div class="min-w-0">
        <div
          v-if="entry.source_status === 'unavailable'"
          class="unavailable-banner"
          role="note"
        >
          <strong>מאגר זה הוסר ממקור הנתונים ({{ sourceName }}).</strong>
          הנתונים המוצגים הם תמונת מצב מהסריקה האחרונה שלנו<template
            v-if="unavailableSinceHe"
            >, שנערכה עד {{ unavailableSinceHe }}</template
          >.
        </div>
        <article ref="bodyEl" class="dataset-body" v-html="body" />
        <DatasetExplorer
          v-if="hasExplorer"
          :resources="entry.resources ?? []"
          :primary-resource-id="entry.primary_resource_id"
          :record-count="entry.record_count"
          :source-unavailable="entry.source_status === 'unavailable'"
        />
        <RelatedNews :articles="data?.news ?? []" />
      </div>

      <aside class="space-y-4 lg:pt-20">
        <section v-if="hasMeta" class="card p-4">
          <h3 class="m-0 mb-3 text-sm font-display text-subtle">פרטים</h3>
          <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm m-0">
            <template v-if="entry.organization">
              <dt class="text-subtle">
                {{ sourceInfo ? "גוף מפרסם" : "משרד" }}
              </dt>
              <dd class="m-0">
                <NuxtLink
                  v-if="entry.organization_slug"
                  :to="`/ministries/${entry.organization_slug}/`"
                  >{{ entry.organization }}</NuxtLink
                >
                <template v-else>{{ entry.organization }}</template>
              </dd>
            </template>
            <template v-if="sourceInfo">
              <dt class="text-subtle">מקור</dt>
              <dd class="m-0">
                <a
                  v-if="sourceHref"
                  :href="sourceHref"
                  target="_blank"
                  rel="noopener"
                  >{{ sourceInfo.source_name_he }}</a
                >
                <template v-else>{{ sourceInfo.source_name_he }}</template>
              </dd>
            </template>
            <template v-if="entry.license">
              <dt class="text-subtle">רישיון</dt>
              <dd class="m-0">
                <a
                  v-if="termsHref"
                  :href="termsHref"
                  target="_blank"
                  rel="noopener"
                  >{{ entry.license }}</a
                >
                <template v-else>{{ entry.license }}</template>
              </dd>
            </template>
            <template v-if="dataVintage">
              <dt class="text-subtle">המידע נכון ל-</dt>
              <dd class="m-0">
                {{ formatDateHe(dataVintage) }}
                <a
                  v-if="sourceUpdatedSinceAnalysis"
                  href="#data-explorer"
                  class="inline-flex items-center gap-1 ms-1 align-middle text-subtle hover:text-brand transition-colors"
                  title="פורסמה גרסה מעודכנת של המאגר. הניתוח בעמוד מבוסס על גרסה קודמת, אך העיון בנתונים למטה מציג נתונים עדכניים בזמן אמת."
                  aria-label="פורסמה גרסה מעודכנת של המאגר. מעבר לעיון בנתונים העדכניים בזמן אמת."
                >
                  <img
                    src="/icons/info.svg"
                    alt=""
                    class="w-3.5 h-3.5 opacity-70"
                  />
                </a>
              </dd>
            </template>
            <template v-if="entry.last_analyzed_at">
              <dt class="text-subtle">הדף נוצר ב-</dt>
              <dd class="m-0">{{ formatDateHe(entry.last_analyzed_at) }}</dd>
            </template>
            <template v-if="entry.record_count != null">
              <dt class="text-subtle">רשומות</dt>
              <dd class="m-0">{{ formatNumber(entry.record_count) }}</dd>
            </template>
          </dl>
        </section>

        <section
          v-if="
            entry.source_status !== 'unavailable' && entry.resources?.length
          "
          class="card p-4"
        >
          <h3 class="m-0 mb-3 text-sm font-display text-subtle">
            קבצים להורדה
          </h3>
          <div>
            <div v-for="r in entry.resources" :key="r.url" class="res-row">
              <span :class="['fmt-badge', formatClass(resourceFormat(r))]">{{
                resourceFormat(r) || "FILE"
              }}</span>
              <div class="flex-1 min-w-0">
                <div class="text-sm text-ink truncate">
                  {{ r.name || resourceFormat(r) || "קובץ" }}
                </div>
                <div v-if="r.size_bytes" class="text-xs text-subtle">
                  {{ formatBytes(r.size_bytes) }}
                </div>
              </div>
              <a
                :href="publicResourceUrl(r.url) || undefined"
                class="btn-ghost text-xs px-3 py-1.5"
                target="_blank"
                rel="noopener"
                download
                >{{ sourceInfo?.download_label_he ?? "הורדה" }}</a
              >
            </div>
          </div>
          <p v-if="sourceInfo" class="m-0 mt-3 text-xs text-subtle">
            {{ sourceInfo.attribution_he }}
          </p>
        </section>

        <section v-if="related.length" class="card p-4">
          <h3 class="m-0 mb-3 text-sm text-subtle font-display">
            מאגרים קשורים
          </h3>
          <ul class="list-none m-0 p-0 space-y-2">
            <li v-for="r in related" :key="r.id">
              <a
                :href="datasetPath(r)"
                class="block card-hover p-2 rounded-gov-md hover:bg-brand-50 no-underline hover:no-underline"
              >
                <div class="text-sm font-medium text-ink">{{ r.title }}</div>
                <div v-if="r.organization" class="text-xs text-subtle mt-0.5">
                  {{ r.organization }}
                </div>
                <div
                  v-if="r.summary_he"
                  class="text-xs text-subtle mt-1 line-clamp-2"
                >
                  {{ r.summary_he }}
                </div>
                <div
                  v-if="r.shared_tags?.length"
                  class="mt-1.5 flex flex-wrap gap-1"
                >
                  <span
                    v-for="t in r.shared_tags"
                    :key="t"
                    class="tag-chip text-[11px]"
                    >{{ t }}</span
                  >
                </div>
              </a>
            </li>
          </ul>
        </section>

        <section v-if="allTags.length" class="card p-4">
          <h3 class="m-0 mb-2 text-sm text-subtle font-display">תגיות</h3>
          <div class="flex flex-wrap gap-1">
            <template v-for="t in allTags" :key="t">
              <NuxtLink
                v-if="tagHref(t)"
                :to="tagHref(t)"
                class="tag-chip hover:bg-brand-100"
                >{{ t }}</NuxtLink
              >
              <span v-else class="tag-chip">{{ t }}</span>
            </template>
          </div>
        </section>

        <section v-if="entry.dataset_kind" class="card p-4 text-xs text-subtle">
          סוג מאגר:
          <NuxtLink
            :to="`/kinds/${entry.dataset_kind}/`"
            class="badge hover:bg-brand-50"
            >{{ kindLabel }}</NuxtLink
          >
        </section>

        <ReportIssue
          :dataset-id="entry.id"
          :dataset-title="entry.title"
          :page-url="datasetUrl"
        />
      </aside>
    </div>
  </div>
</template>

<style scoped>
.unavailable-banner {
  border: 1px solid #ffc107;
  background: #fff9e6;
  color: #0c3058;
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  font-size: 0.9rem;
  line-height: 1.5;
}
/* Guard against agent-emitted bodies with wide tables, fixed-pixel images,
   or full-width charts pushing horizontal overflow on mobile. ECharts and
   Leaflet self-size to their container, so capping the container is enough. */
.dataset-body {
  max-width: 100%;
  overflow-x: hidden;
}
.dataset-body :deep(table) {
  display: block;
  overflow-x: auto;
  max-width: 100%;
}
.dataset-body :deep(img),
.dataset-body :deep(svg),
.dataset-body :deep(canvas),
.dataset-body :deep(iframe),
.dataset-body :deep(video) {
  max-width: 100%;
  height: auto;
}
/* Leaflet's renderer canvas / SVG extends beyond the map's visible box
   (a buffer for pan + zoom), and tile <img> elements are sized inline
   to 256px. The responsive-media reset above clamps them to the
   leaflet-overlay-pane's 0×0 bounding box — markers vanish, tiles
   shrink. Hand the sizing back to the library for everything inside
   .leaflet-container. */
.dataset-body :deep(.leaflet-container img),
.dataset-body :deep(.leaflet-container svg),
.dataset-body :deep(.leaflet-container canvas) {
  max-width: none;
  height: auto;
}
.dataset-body :deep(pre) {
  overflow-x: auto;
  max-width: 100%;
}
/* Mobile backstop for agent-emitted highlight cards and chart containers.
   Auto-fit / auto-fill grids and `auto 1fr` definition lists already
   reflow correctly and are deliberately untouched. */
@media (max-width: 640px) {
  /* Hardcoded equal-column inline grids collapse to one column. */
  .dataset-body :deep([style*="grid-template-columns"][style*="repeat(2"]),
  .dataset-body :deep([style*="grid-template-columns"][style*="repeat(3"]),
  .dataset-body :deep([style*="grid-template-columns"][style*="repeat(4"]),
  .dataset-body :deep([style*="grid-template-columns"][style*="repeat(5"]),
  .dataset-body :deep([style*="grid-template-columns: 1fr 1fr"]),
  .dataset-body :deep([style*="grid-template-columns:1fr 1fr"]) {
    grid-template-columns: minmax(0, 1fr) !important;
  }
  /* Tailwind multi-column utilities without a responsive prefix collapse.
     `grid-cols-2` is left alone — two cards across 375px is tight but
     readable, and several pages already use it deliberately. */
  .dataset-body :deep(.grid-cols-3),
  .dataset-body :deep(.grid-cols-4),
  .dataset-body :deep(.grid-cols-5) {
    grid-template-columns: minmax(0, 1fr) !important;
  }
  /* Cap chart and map container heights. */
  .dataset-body :deep([id^="chart-"][style*="height:"]),
  .dataset-body :deep([id^="map-"][style*="height:"]),
  .dataset-body :deep([id="map"][style*="height:"]) {
    height: clamp(240px, 65vw, 320px) !important;
  }
}
</style>
