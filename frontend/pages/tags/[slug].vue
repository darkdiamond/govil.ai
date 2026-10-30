<script setup lang="ts">
import { buildDatasetLdSummary } from "~/composables/useDatasetLd";
import { loadSearchIndex } from "~/utils/search-index";

const route = useRoute();
const slug = computed(() => String(route.params.slug));

interface Chip {
  label: string;
  href: string;
  count: number;
}

// Resolve the URL slug to its canonical tag via the publisher's tag_index
// (paged tags only), then bake only this tag's data into the page payload
// (the key must include the slug — colliding keys would cross-pollinate).
// Built from the slim index, not the server-only manifest: tag chips are
// NuxtLinks, and with payloadExtraction off a client-side navigation
// re-runs this fetcher in the browser.
const { data } = await useAsyncData(`tag-${slug.value}`, async () => {
  const m = await loadSearchIndex();
  const index = m.tag_index ?? {};
  const found = Object.entries(index).find(([, t]) => t.slug === slug.value);
  if (!found) return null;
  const [tag, info] = found;
  const topic = (m.topics ?? []).find((t) => t.id === info.topic);
  const entries = m.datasets.filter((d) => (d.tags ?? []).includes(tag));
  const orgTitles = new Map(
    m.datasets.map((d) => [d.organization_slug, d.organization])
  );
  const ministries: Chip[] = Object.entries(info.ministries).map(([s, n]) => ({
    label: orgTitles.get(s) ?? s,
    href: `/ministries/${s}/`,
    count: n,
  }));
  const relatedTags: Chip[] = info.related
    .filter((t) => index[t])
    .map((t) => ({
      label: t,
      href: `/tags/${encodeURI(index[t]!.slug)}/`,
      count: index[t]!.count,
    }));
  return {
    tag,
    intro: info.intro_he || topic?.intro_he || "",
    topic: topic ? { id: topic.id, label: topic.label_he } : null,
    entries,
    ministries,
    relatedTags,
  };
});

if (!data.value || data.value.entries.length === 0) {
  throw createError({
    statusCode: 404,
    statusMessage: "Tag not found",
    fatal: true,
  });
}

const page = computed(() => data.value!);
const tag = computed(() => page.value.tag);
const entries = computed(() => page.value.entries);

const SITE_URL = "https://govil.ai";
const tagDescription = computed(() => {
  const lead = `${entries.value.length} מאגרי מידע ציבוריים בנושא ${tag.value}`;
  const firstSentence = page.value.intro.split(".")[0];
  return firstSentence
    ? `${lead}. ${firstSentence}.`
    : `${lead}, עם תקצירים ותובנות בעברית.`;
});
const encodedSlug = computed(() => encodeURI(slug.value));
const canonicalUrl = computed(() => `${SITE_URL}/tags/${encodedSlug.value}/`);

useSeo({
  title: `מאגרי מידע ממשלתיים בנושא ${tag.value}`,
  description: tagDescription.value,
  path: `/tags/${encodedSlug.value}/`,
  keywords: [tag.value],
  breadcrumbs: [
    { name: "ראשי", url: `${SITE_URL}/` },
    { name: "נושאים", url: `${SITE_URL}/tags/` },
    { name: tag.value, url: canonicalUrl.value },
  ],
  extraJsonLd: {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: `מאגרי מידע בנושא ${tag.value}`,
    inLanguage: "he-IL",
    url: canonicalUrl.value,
    hasPart: entries.value.slice(0, 25).map(buildDatasetLdSummary),
  },
});
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <section class="mb-6">
      <div class="text-xs text-subtle mb-2">
        <NuxtLink to="/">ראשי</NuxtLink> ›
        <NuxtLink to="/tags/">נושאים</NuxtLink> ›
        <template v-if="page.topic">
          <NuxtLink :to="`/tags/#${page.topic.id}`">{{
            page.topic.label
          }}</NuxtLink>
          ›
        </template>
        {{ tag }}
      </div>
      <h1 class="font-display">{{ tag }}</h1>
      <p class="text-subtle mt-2">{{ entries.length }} מאגרים</p>
      <p v-if="page.intro" class="mt-4 max-w-3xl leading-relaxed text-ink">
        {{ page.intro }}
      </p>
    </section>

    <section
      v-if="page.ministries.length > 1 || page.relatedTags.length"
      class="mb-6 space-y-3"
    >
      <div v-if="page.ministries.length > 1">
        <h2 class="text-sm text-subtle font-display mb-2">לפי גוף מפרסם</h2>
        <div class="flex flex-wrap gap-2">
          <NuxtLink
            v-for="m in page.ministries"
            :key="m.href"
            :to="m.href"
            class="badge hover:bg-brand-50 no-underline hover:no-underline"
            >{{ m.label }}
            <span class="text-subtle ms-1">· {{ m.count }}</span></NuxtLink
          >
        </div>
      </div>
      <div v-if="page.relatedTags.length">
        <h2 class="text-sm text-subtle font-display mb-2">נושאים קרובים</h2>
        <div class="flex flex-wrap gap-2">
          <NuxtLink
            v-for="t in page.relatedTags"
            :key="t.href"
            :to="t.href"
            class="tag-chip hover:bg-brand-100 no-underline hover:no-underline"
            >{{ t.label }}
            <span class="text-subtle ms-1">· {{ t.count }}</span></NuxtLink
          >
        </div>
      </div>
    </section>

    <section class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <DatasetCard v-for="e in entries" :key="e.id" :entry="e" />
    </section>
  </div>
</template>
