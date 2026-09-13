<script setup lang="ts">
import { buildInsightPool, sampleInsights } from '~/utils/insights'
import type { DatasetKind, SlimEntry } from '~/types/manifest'
import { loadSearchIndex } from '~/utils/search-index'

useSeo({
  title: 'מאגרי המידע הממשלתיים של ישראל — מוסברים בעברית פשוטה · govil.ai',
  description: 'כל מאגר מידע ממשלתי חדש מוסבר בעברית פשוטה בעמוד אחד — תקציר, תובנות, גרפים ומפות אינטראקטיביות. בלי הורדות ובלי Excel.',
  path: '/',
  keywords: [
    'מאגרי מידע ממשלתיים',
    'מידע ממשלתי פתוח',
    'נתונים פתוחים',
    'open data Israel',
  ],
})

interface MinistryRow {
  slug: string
  title: string
  count: number
}

// One fetcher bakes everything the home sections render into the page
// payload — the slim index itself never ships to the client from here.
const { data } = await useAsyncData('home', async () => {
  const index = await loadSearchIndex()
  const datasets = index.datasets

  const latest = [...datasets]
    .sort((a, b) => {
      const ta = a.last_analyzed_at ? Date.parse(a.last_analyzed_at) : 0
      const tb = b.last_analyzed_at ? Date.parse(b.last_analyzed_at) : 0
      return tb - ta
    })
    .slice(0, 6)

  const byMinistry = new Map<string, MinistryRow>()
  for (const d of datasets) {
    if (!d.organization_slug || !d.organization) continue
    const r = byMinistry.get(d.organization_slug)
    if (r) r.count++
    else byMinistry.set(d.organization_slug, { slug: d.organization_slug, title: d.organization, count: 1 })
  }
  const ministries = [...byMinistry.values()].sort((a, b) => b.count - a.count).slice(0, 6)

  const kindCounts: Partial<Record<DatasetKind, number>> = {}
  for (const d of datasets) {
    if (!d.dataset_kind) continue
    kindCounts[d.dataset_kind] = (kindCounts[d.dataset_kind] ?? 0) + 1
  }

  // The carousel only ever renders a handful of slides at a time, but it
  // randomly resamples on mount so the pool itself has to reach the client.
  // Shipping all ~400 qualifying engagements blew the hydration payload up to
  // ~195 KB (the bulk of the homepage document), which dominated LCP. Cap the
  // build-time pool at a bounded sample — enough variety for a fresh random
  // draw each visit, small enough to keep the inline payload out of the
  // critical path.
  return {
    insightPool: sampleInsights(buildInsightPool(datasets), 48),
    latest,
    ministries,
    kindCounts,
    generatedAt: index.generated_at,
  }
})

const insightPool = computed(() => data.value?.insightPool ?? [])
const latest = computed<SlimEntry[]>(() => data.value?.latest ?? [])
const ministries = computed<MinistryRow[]>(() => data.value?.ministries ?? [])
const kindCounts = computed(() => data.value?.kindCounts ?? {})
const generatedAt = computed(() => data.value?.generatedAt)
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8 space-y-16">
    <Hero :generated-at="generatedAt" />
    <InsightCarousel :pool="insightPool" />
    <WhatYouGet />
    <HowItWorks />
    <BrowseByMinistry :ministries="ministries" />
    <BrowseByKind :kind-counts="kindCounts" />
    <LatestDatasets :latest="latest" />
    <CallToAction />
  </div>
</template>
