<script setup lang="ts">
import { SITE_URL } from "~/utils/paths";
import { buildDatasetLdSummary } from "~/composables/useDatasetLd";
import { loadSearchIndex } from "~/utils/search-index";
import hubIntros from "~/content/hub-intros.json";

const route = useRoute();
const slug = computed(() => String(route.params.slug));

// Bake only this ministry's slim entries into the page payload.
const { data, error } = await useAsyncData(
  `ministry-${slug.value}`,
  async () => {
    const index = await loadSearchIndex();
    return index.datasets.filter((d) => d.organization_slug === slug.value);
  }
);

const entries = computed(() => data.value ?? []);
const ministryTitle = computed(
  () => entries.value[0]?.organization ?? slug.value
);

// A failed fetch on client-side navigation (offline, 5xx) is not a 404.
if (error.value) {
  throw createError({
    statusCode: 503,
    statusMessage: "Ministry unavailable",
    fatal: true,
  });
}
if (entries.value.length === 0) {
  throw createError({
    statusCode: 404,
    statusMessage: "Ministry not found",
    fatal: true,
  });
}

const intro = computed(
  () => (hubIntros.ministries as Record<string, string>)[slug.value] ?? ""
);
const ministryDescription = computed(() => {
  const firstSentence = intro.value.split(".")[0];
  return firstSentence
    ? `${firstSentence}. ${entries.value.length} מאגרי מידע ציבוריים עם תקצירים ותובנות בעברית.`
    : `${entries.value.length} מאגרי מידע ציבוריים שמפרסם ${ministryTitle.value}, עם תקצירים ותובנות בעברית.`;
});

useSeo({
  title: `מאגרי המידע של ${ministryTitle.value} — תקצירים ותובנות`,
  description: ministryDescription.value,
  path: `/ministries/${slug.value}/`,
  keywords: [ministryTitle.value],
  breadcrumbs: [
    { name: "ראשי", url: `${SITE_URL}/` },
    { name: "משרדים", url: `${SITE_URL}/ministries/` },
    { name: ministryTitle.value, url: `${SITE_URL}/ministries/${slug.value}/` },
  ],
  extraJsonLd: [
    {
      "@context": "https://schema.org",
      "@type": "GovernmentOrganization",
      name: ministryTitle.value,
      url: `${SITE_URL}/ministries/${slug.value}/`,
      sameAs: "https://www.gov.il",
    },
    {
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: `מאגרי מידע של ${ministryTitle.value}`,
      inLanguage: "he-IL",
      url: `${SITE_URL}/ministries/${slug.value}/`,
      hasPart: entries.value.slice(0, 25).map(buildDatasetLdSummary),
    },
  ],
});
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <section class="mb-6">
      <div class="text-xs text-subtle mb-2">
        <NuxtLink to="/">ראשי</NuxtLink> ›
        <NuxtLink to="/ministries/">משרדים</NuxtLink> ›
        {{ ministryTitle }}
      </div>
      <h1 class="font-display">{{ ministryTitle }}</h1>
      <p class="text-subtle mt-2">{{ entries.length }} מאגרים</p>
      <p v-if="intro" class="mt-4 max-w-3xl leading-relaxed text-ink">
        {{ intro }}
      </p>
    </section>

    <section class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <DatasetCard v-for="e in entries" :key="e.id" :entry="e" />
    </section>
  </div>
</template>
