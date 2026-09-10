<script setup lang="ts">
import { buildDatasetLd, datasetDescription } from '~/composables/useDatasetLd'
import { formatBytes, formatNumber } from '~/composables/useRelativeTime'
import type { AgentData, DatasetMeta, ManifestEntry } from '~/types/manifest'
import { buildDatasetLibTags, detectDatasetLibs, type DatasetLibNeeds } from '~/utils/dataset-libs'
import { loadFullManifestServer } from '~/utils/search-index'
import { normalizeAgentBody } from '~/utils/normalize-agent-body'

const route = useRoute()
const slug = String(route.params.slug)

interface RelatedEntry {
  id: string
  page_slug?: string
  title: string
  organization?: string
  summary_he?: string
}

const { data } = await useAsyncData(`dataset-${slug}`, async () => {
  // Guard the node imports so Vite's client bundler can tree-shake
  // them out — they're SSR/prerender-only. Without the guard Vite
  // emits a "Module 'node:fs/promises' has been externalized for
  // browser compatibility" warning per build. On the client useAsyncData
  // hydrates from the prerendered payload, never re-runs this fetcher.
  if (!import.meta.server) return null
  const fs = await import('node:fs/promises')
  const path = await import('node:path')

  // The URL carries the page_slug; on-disk artifacts are keyed by the CKAN
  // id (single writer per file — see CLAUDE.md). Resolve slug → id via the
  // manifest, which this page loads anyway for related/tag data below. An
  // unknown slug (or a checkout with no manifest) falls through to 404.
  const manifest = await loadFullManifestServer()
  const me = manifest.datasets.find((d) => (d.page_slug || d.id) === slug)
  if (!me) return null
  const id = me.id
  const dir = path.resolve(process.cwd(), 'public/datasets', id)

  // Three artifacts, two writers:
  //   - content.html      : agent body, synced from GCS staging
  //   - data.json         : DatasetMeta, written by the publisher from Firestore
  //   - agent_data.json   : AgentData,   written by the publisher from Firestore.
  //                         Optional — a scanned-but-never-analyzed source has none.
  const [rawBody, metaRaw, agentRaw] = await Promise.all([
    fs.readFile(path.join(dir, 'content.html'), 'utf-8'),
    fs.readFile(path.join(dir, 'data.json'), 'utf-8'),
    fs.readFile(path.join(dir, 'agent_data.json'), 'utf-8').catch(() => null),
  ])

  const meta = JSON.parse(metaRaw) as DatasetMeta
  const agent = (agentRaw ? JSON.parse(agentRaw) : null) as AgentData | null

  // Merge into a ManifestEntry-shaped object so existing template paths
  // (entry.summary_he, entry.dataset_kind, …) keep working. related_ids is
  // sourced from the manifest in the `related` computed below — that's the
  // publisher's deterministic top-K (ministry + tags + cosine + agent),
  // not the agent's raw suggestions.
  const entry: ManifestEntry = {
    ...meta,
    summary_he: agent?.summary_he,
    dataset_kind: agent?.dataset_kind,
    temporal_coverage: agent?.temporal_coverage as string | undefined,
    spatial_coverage: agent?.spatial_coverage as string | undefined,
    suggested_tags: (agent?.suggested_tags as string[] | undefined) ?? [],
    related_ids: [],
  }

  // Resolve everything this page needs from the full manifest HERE, at
  // prerender time, so the client never ships or fetches manifest data:
  // the publisher's deterministic related_ids → 5 sidebar snippets, plus
  // the tag→slug map for just this page's chips. Both land in the inlined
  // payload alongside entry/rawBody.
  let related: RelatedEntry[] = []
  let tagSlugs: Record<string, string> = {}
  try {
    const byId = new Map(manifest.datasets.map((d) => [d.id, d]))
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
      }))
    const slugMap = manifest.tag_slugs ?? {}
    for (const t of [...(entry.suggested_tags ?? []), ...(entry.tags_he ?? [])]) {
      if (t && slugMap[t]) tagSlugs[t] = slugMap[t]
    }
  } catch {
    // Defensive — manifest is already loaded above, so this rarely trips.
  }

  // Detect which viz libs the agent body actually references so the page
  // loads only those (the raw body is the honest signal — a script can't
  // call a global without naming it).
  const libs = detectDatasetLibs(rawBody)

  return { entry, rawBody, related, tagSlugs, libs }
})

if (!data.value) {
  throw createError({ statusCode: 404, statusMessage: 'Dataset not found', fatal: true })
}

const entry = computed(() => data.value!.entry)

// Per-page conditional lib tags, derived from the payload's `libs` flags —
// identical server/client, so unhead dedupes by src on hydration. These
// head tags are the only external resources a dataset page loads.
useHead(buildDatasetLibTags(data.value.libs))

const related = computed<RelatedEntry[]>(() => data.value!.related ?? [])

const tagSlugs = computed(() => data.value!.tagSlugs ?? {})
function tagHref(t: string): string {
  const slug = tagSlugs.value[t] ?? t
  return `/tags/${encodeURI(slug)}/`
}

// Title-row chips: prefer the agent's curated suggested_tags. If a page
// hasn't been backfilled yet (no suggested_tags), fall back to the
// official CKAN tags_he so something still renders. Each chip resolves
// to a real /tags/<slug>/ link via the manifest's tag_slugs map.
// Union of agent-curated `suggested_tags` and CKAN-official `tags_he`,
// preserving order with the agent's labels first (they're the editorial
// pick) and dropping duplicates. Used both for the title-row chips
// injected into the body and the sidebar "תגיות" list.
const allTags = computed<string[]>(() => {
  const seen = new Set<string>()
  const out: string[] = []
  for (const t of [
    ...(entry.value.suggested_tags ?? []),
    ...(entry.value.tags_he ?? []),
  ]) {
    if (!t || seen.has(t)) continue
    seen.add(t)
    out.push(t)
  }
  return out
})

const titleChips = computed(() =>
  allTags.value.map((label) => ({ label, href: tagHref(label) })),
)

// Single ingress point for every agent body — see normalizeAgentBody().
// Strips the legacy chip wrapper (so old pages don't render two rows)
// and injects the new clickable chip row right after the H1.
const body = computed(() =>
  normalizeAgentBody(data.value!.rawBody, { titleChips: titleChips.value }),
)

const KIND_LABELS_HE: Record<string, string> = {
  map: 'גיאוגרפי',
  timeseries: 'סדרת זמן',
  registry: 'רשימת ישויות',
  rankings: 'דירוגים',
  misc: 'אחר',
}
const kindLabel = computed(() =>
  entry.value.dataset_kind ? KIND_LABELS_HE[entry.value.dataset_kind] ?? 'אחר' : '',
)

const hasMeta = computed(() =>
  Boolean(
    entry.value.organization ||
      entry.value.license ||
      entry.value.last_analyzed_at ||
      entry.value.analyzed_metadata_modified ||
      entry.value.record_count != null,
  ),
)

// "המידע נכון ל-" displays the data vintage. For sources analyzed after
// the pipeline started snapshotting metadata_modified at analysis time,
// that's the authoritative snapshot. For legacy sources (analyzed_metadata_modified
// is null), fall back to last_analyzed_at so the row still renders.
const dataVintage = computed<string | null>(() =>
  entry.value.analyzed_metadata_modified ?? entry.value.last_analyzed_at ?? null,
)

// Show the "updated since analysis" info icon when CKAN's live
// metadata_modified has moved to a later UTC calendar day than the
// authoritative snapshot. Suppressed for legacy sources without a
// snapshot — we don't know what version the agent saw, so we can't
// honestly claim the source has been updated since.
const sourceUpdatedSinceAnalysis = computed<boolean>(() => {
  const live = entry.value.metadata_modified
  const snap = entry.value.analyzed_metadata_modified
  if (!live || !snap) return false
  const dayUTC = (iso: string) => {
    const d = new Date(iso)
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())
  }
  return dayUTC(live) > dayUTC(snap)
})

const HE_DATE = new Intl.DateTimeFormat('he-IL', { dateStyle: 'long' })
function formatDateHe(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : HE_DATE.format(d)
}
function publicResourceUrl(url: string): string {
  return url.replace('https://e.data.gov.il', 'https://data.gov.il')
}
function formatClass(fmt?: string | null): string {
  switch ((fmt || '').toUpperCase()) {
    case 'CSV':  return 'fmt-csv'
    case 'PDF':  return 'fmt-pdf'
    case 'XLSX':
    case 'XLS':  return 'fmt-xlsx'
    case 'JSON': return 'fmt-json'
    default:     return 'fmt-default'
  }
}

const SITE_URL = 'https://govil.ai'
// page_slug is the URL segment (Hebrew title slug + id slice); encode for the
// wire since it contains Hebrew. Fall back to id for any legacy entry missing it.
const pagePath = `/datasets/${encodeURI(entry.value.page_slug || entry.value.id)}/`
const datasetUrl = `${SITE_URL}${pagePath}`

// Archive banner date — reuses formatDateHe (defined above, alongside
// dataVintage/last_analyzed_at) so the "as of" phrasing matches the rest of
// this page's date formatting. Empty when the source has no stamped
// unavailable_since (legacy/edge case) — the banner still renders its main
// sentence without the trailing clause.
const unavailableSinceHe = computed(() => formatDateHe(entry.value.unavailable_since))

const seoDescription = datasetDescription(entry.value)

const breadcrumbs = [
  { name: 'ראשי', url: `${SITE_URL}/` },
  { name: 'מאגרים', url: `${SITE_URL}/datasets/` },
  ...(entry.value.organization && entry.value.organization_slug
    ? [{ name: entry.value.organization, url: `${SITE_URL}/ministries/${entry.value.organization_slug}/` }]
    : []),
  { name: entry.value.title, url: datasetUrl },
]

const datasetLd = buildDatasetLd(entry.value, { canonical: datasetUrl })

// Google truncates titles around 60 chars in Hebrew SERPs. useSeo no longer
// auto-appends " — govil.ai" (the brand goes through og:site_name instead),
// so the full 60 are ours. Append the ministry with a thin separator only
// when the combined string still fits — long CKAN titles stand on their own.
const seoTitle = (() => {
  const t = entry.value.title
  const org = entry.value.organization
  const withOrg = org ? `${t} · ${org}` : t
  return withOrg.length <= 60 ? withOrg : t
})()

useSeo({
  title: seoTitle,
  description: seoDescription,
  path: pagePath,
  author: entry.value.organization,
  breadcrumbs,
  extraJsonLd: datasetLd,
})

// Agent-generated content.html has inline <script> tags (ECharts, Leaflet).
// On SSR/refresh they execute natively as the browser parses the document,
// but v-html sets innerHTML, and innerHTML-inserted scripts never run — so
// on client-side navigation the charts silently fail to initialize. Rebuild
// each <script> as a real element so the browser executes it, awaiting
// external src= loads so inline init scripts see their globals. Inline
// classic scripts get wrapped in an IIFE because top-level `const`/`let`
// bind into the page's shared script-level scope, which persists across
// SPA navs and would SyntaxError on re-entry to a previously-visited page.
const bodyEl = ref<HTMLElement | null>(null)

async function executeBodyScripts(container: HTMLElement): Promise<void> {
  // If any previous ECharts or Leaflet instances exist on elements in this
  // container, clean them up so re-executing scripts doesn't collide or throw.
  const w = window as unknown as {
    echarts?: { getInstanceByDom: (el: Element) => { dispose: () => void } | undefined }
  }
  if (w.echarts?.getInstanceByDom) {
    for (const el of container.querySelectorAll('[id^=chart]')) {
      try {
        w.echarts.getInstanceByDom(el)?.dispose()
      } catch {
        // Ignore dispose errors
      }
    }
  }
  for (const el of container.querySelectorAll<HTMLElement>('[id^=map], #map, .leaflet-container')) {
    const raw = el as unknown as { _leaflet_id?: number | null }
    if (raw._leaflet_id) {
      raw._leaflet_id = null
      el.innerHTML = ''
    }
  }

  const scripts = Array.from(container.querySelectorAll('script'))
  // content.html often gates init on DOMContentLoaded / window load, but those
  // events fired once on the original page load and never fire again. Intercept
  // addEventListener while our scripts run, collect handlers registered for
  // those events, and invoke them immediately after — without touching
  // listeners registered earlier (which would double-init prior visits).
  type Deferred = [EventTarget, string, EventListenerOrEventListenerObject]
  const deferred: Deferred[] = []
  // Capture pre-bound to dodge a Window/WorkerGlobalScope overload clash:
  // the Nuxt-generated tsconfig has `lib: [..., "webworker"]`, which makes
  // unbound `addEventListener.call(window, …)` ambiguous between
  // WindowEventMap and DedicatedWorkerGlobalScopeEventMap. `.bind()` resolves
  // to a plain `(…args) => …` and side-steps the ambiguity.
  const origDocAdd = document.addEventListener.bind(document)
  const origWinAdd = window.addEventListener.bind(window)
  const docReady = () => document.readyState !== 'loading'
  const winLoaded = () => document.readyState === 'complete'
  document.addEventListener = function (type: string, listener: EventListenerOrEventListenerObject, opts?: unknown) {
    if (listener && (type === 'DOMContentLoaded' || type === 'readystatechange') && docReady()) {
      deferred.push([document, type, listener])
      return
    }
    return origDocAdd(type, listener as EventListener, opts as AddEventListenerOptions)
  } as typeof document.addEventListener
  window.addEventListener = function (type: string, listener: EventListenerOrEventListenerObject, opts?: unknown) {
    if (listener && type === 'load' && winLoaded()) {
      deferred.push([window, type, listener])
      return
    }
    return origWinAdd(type, listener as EventListener, opts as AddEventListenerOptions)
  } as typeof window.addEventListener
  try {
    for (const old of scripts) {
      const parent = old.parentNode
      if (!parent) continue
      const s = document.createElement('script')
      for (const { name, value } of Array.from(old.attributes)) s.setAttribute(name, value)
      if (s.src) {
        await new Promise<void>((resolve) => {
          s.onload = () => resolve()
          s.onerror = () => resolve()
          parent.replaceChild(s, old)
        })
      } else {
        const source = old.textContent ?? ''
        s.text = s.type === 'module' ? source : `(()=>{\n${source}\n})();`
        parent.replaceChild(s, old)
      }
    }
  } finally {
    document.addEventListener = origDocAdd
    window.addEventListener = origWinAdd
  }
  for (const [target, type, listener] of deferred) {
    try {
      const ev = new Event(type)
      if (typeof listener === 'function') listener.call(target, ev)
      else listener.handleEvent(ev)
    } catch (err) {
      console.error('[dataset body] deferred listener failed', err)
    }
  }
}

// Wait for conditional head libs before running body scripts. On SSR/SSG
// load they are synchronous in <head> and resolve immediately; on SPA nav
// useHead appends them dynamically, so we poll until window.* globals are set.
async function awaitDatasetLibs(needs: DatasetLibNeeds, timeoutMs = 5000): Promise<void> {
  if (!needs.charts && !needs.map && !needs.explorer) return
  const start = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const w = window as unknown as {
      L?: { markerClusterGroup?: unknown }
      echarts?: unknown
      GovEcharts?: { option?: unknown }
      GovExplorer?: { create?: unknown }
      GovMap?: { create?: unknown }
    }
    const ready =
      (!needs.charts ||
        (typeof w.echarts !== 'undefined' && typeof w.GovEcharts?.option === 'function')) &&
      (!needs.map ||
        (typeof w.L?.markerClusterGroup === 'function' && typeof w.GovMap?.create === 'function')) &&
      (!needs.explorer || typeof w.GovExplorer?.create === 'function')
    if (ready) return
    if (Date.now() - start > timeoutMs) {
      console.warn('[dataset libs] timed out waiting for this page\'s viz globals after SPA nav', needs)
      return
    }
    await new Promise((r) => setTimeout(r, 30))
  }
}

onMounted(async () => {
  await awaitDatasetLibs(data.value!.libs)
  if (!bodyEl.value) return
  void executeBodyScripts(bodyEl.value)
  // Bridge container-width changes (orientation, sidebar reflow at lg) into
  // a window resize so ECharts re-fits via the agent's existing
  // `chart.resize()` listeners. rAF-debounced to coalesce smooth resizes.
  let raf = 0
  const ro = new ResizeObserver(() => {
    cancelAnimationFrame(raf)
    raf = requestAnimationFrame(() => window.dispatchEvent(new Event('resize')))
  })
  ro.observe(bodyEl.value)
  onBeforeUnmount(() => { cancelAnimationFrame(raf); ro.disconnect() })
})
</script>

<template>
  <div>
    <nav aria-label="breadcrumb" class="border-b border-rule bg-white">
      <div class="max-w-gov mx-auto px-4 py-2 text-xs text-subtle">
        <NuxtLink to="/">ראשי</NuxtLink>
        <template v-if="entry.organization && entry.organization_slug">
          <span class="mx-1">›</span>
          <NuxtLink :to="`/ministries/${entry.organization_slug}/`">{{ entry.organization }}</NuxtLink>
        </template>
        <span class="mx-1">›</span>
        <span>{{ entry.title }}</span>
      </div>
    </nav>

    <div class="max-w-gov mx-auto px-4 py-8 grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-8">
      <!-- min-w-0 keeps the explorer's wide table from blowing out the 1fr track -->
      <div class="min-w-0">
        <div
          v-if="entry.source_status === 'unavailable'"
          class="unavailable-banner"
          role="note"
        >
          <strong>מאגר זה הוסר ממקור הנתונים (data.gov.il).</strong>
          הנתונים המוצגים הם תמונת מצב מהסריקה האחרונה שלנו<template v-if="unavailableSinceHe">, שנערכה עד {{ unavailableSinceHe }}</template>.
        </div>
        <article ref="bodyEl" class="dataset-body" v-html="body" />
        <!-- AdSense responsive slot between the agent's analysis and the
             data explorer — see components/AdSlot.vue (no-op unless
             NUXT_PUBLIC_ADSENSE_ID is set). -->
        <AdSlot />
        <DatasetExplorer
          :resources="entry.resources ?? []"
          :primary-resource-id="entry.primary_resource_id"
          :record-count="entry.record_count"
          :source-unavailable="entry.source_status === 'unavailable'"
        />
      </div>

      <aside class="space-y-4 lg:pt-20">
        <section v-if="hasMeta" class="card p-4">
          <h3 class="m-0 mb-3 text-sm font-display text-subtle">פרטים</h3>
          <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm m-0">
            <template v-if="entry.organization">
              <dt class="text-subtle">משרד</dt>
              <dd class="m-0">
                <NuxtLink
                  v-if="entry.organization_slug"
                  :to="`/ministries/${entry.organization_slug}/`"
                >{{ entry.organization }}</NuxtLink>
                <template v-else>{{ entry.organization }}</template>
              </dd>
            </template>
            <template v-if="entry.license">
              <dt class="text-subtle">רישיון</dt>
              <dd class="m-0">{{ entry.license }}</dd>
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

        <section v-if="entry.resources?.length" class="card p-4">
          <h3 class="m-0 mb-3 text-sm font-display text-subtle">קבצים להורדה</h3>
          <div>
            <div v-for="r in entry.resources" :key="r.url" class="res-row">
              <span :class="['fmt-badge', formatClass(r.format)]">{{ (r.format || 'FILE').toUpperCase() }}</span>
              <div class="flex-1 min-w-0">
                <div class="text-sm text-ink truncate">{{ r.name || r.format || 'קובץ' }}</div>
                <div v-if="r.size_bytes" class="text-xs text-subtle">{{ formatBytes(r.size_bytes) }}</div>
              </div>
              <a
                :href="publicResourceUrl(r.url)"
                class="btn-ghost text-xs px-3 py-1.5"
                target="_blank"
                rel="noopener"
                download
              >הורדה</a>
            </div>
          </div>
        </section>

        <section v-if="related.length" class="card p-4">
          <h3 class="m-0 mb-3 text-sm text-subtle font-display">מאגרים קשורים</h3>
          <ul class="list-none m-0 p-0 space-y-2">
            <li v-for="r in related" :key="r.id">
              <a
                :href="`/datasets/${encodeURI(r.page_slug || r.id)}/`"
                class="block card-hover p-2 rounded-gov-md hover:bg-brand-50 no-underline hover:no-underline"
              >
                <div class="text-sm font-medium text-ink">{{ r.title }}</div>
                <div v-if="r.organization" class="text-xs text-subtle mt-0.5">{{ r.organization }}</div>
                <div v-if="r.summary_he" class="text-xs text-subtle mt-1 line-clamp-2">{{ r.summary_he }}</div>
              </a>
            </li>
          </ul>
        </section>

        <section v-if="allTags.length" class="card p-4">
          <h3 class="m-0 mb-2 text-sm text-subtle font-display">תגיות</h3>
          <div class="flex flex-wrap gap-1">
            <NuxtLink
              v-for="t in allTags"
              :key="t"
              :to="tagHref(t)"
              class="tag-chip hover:bg-brand-100"
            >{{ t }}</NuxtLink>
          </div>
        </section>

        <section v-if="entry.dataset_kind" class="card p-4 text-xs text-subtle">
          סוג מאגר:
          <NuxtLink :to="`/kinds/${entry.dataset_kind}/`" class="badge hover:bg-brand-50">{{ kindLabel }}</NuxtLink>
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
