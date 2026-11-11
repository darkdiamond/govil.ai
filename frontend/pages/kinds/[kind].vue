<script setup lang="ts">
import { SITE_URL } from "~/utils/paths";
import { buildDatasetLdSummary } from "~/composables/useDatasetLd";
import { loadSearchIndex } from "~/utils/search-index";
import hubIntros from "~/content/hub-intros.json";
import { KIND_INFO } from "~/composables/useKindLabels";
import type { DatasetKind } from "~/types/manifest";

const route = useRoute();
const kind = computed(() => String(route.params.kind));

// Bake only this kind's slim entries into the page payload.
const { data, error } = await useAsyncData(`kind-${kind.value}`, async () => {
  const index = await loadSearchIndex();
  return index.datasets.filter((d) => d.dataset_kind === kind.value);
});

const entries = computed(() => data.value ?? []);
const label = computed(
  () => KIND_INFO[kind.value as DatasetKind]?.label ?? kind.value
);

// A failed fetch on client-side navigation (offline, 5xx) is not a 404.
if (error.value) {
  throw createError({
    statusCode: 503,
    statusMessage: "Kind unavailable",
    fatal: true,
  });
}
if (entries.value.length === 0) {
  throw createError({
    statusCode: 404,
    statusMessage: "Kind not found",
    fatal: true,
  });
}

const intro = computed(
  () => (hubIntros.kinds as Record<string, string>)[kind.value] ?? ""
);
const kindDescription = computed(() => {
  const firstSentence = intro.value.split(".")[0];
  return firstSentence
    ? `${firstSentence}. ${entries.value.length} מאגרים בקטגוריה זו.`
    : `${entries.value.length} מאגרי מידע ציבוריים מסוג ${label.value} — עם ויזואליזציות מתאימות.`;
});

useSeo({
  title: `מאגרי ${label.value} — מידע ממשלתי פתוח בעברית פשוטה`,
  description: kindDescription.value,
  path: `/kinds/${kind.value}/`,
  keywords: [label.value],
  breadcrumbs: [
    { name: "ראשי", url: `${SITE_URL}/` },
    { name: "סוגי מידע", url: `${SITE_URL}/kinds/` },
    { name: label.value, url: `${SITE_URL}/kinds/${kind.value}/` },
  ],
  extraJsonLd: {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: `מאגרים מסוג ${label.value}`,
    inLanguage: "he-IL",
    url: `${SITE_URL}/kinds/${kind.value}/`,
    hasPart: entries.value.slice(0, 25).map(buildDatasetLdSummary),
  },
});
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <section class="mb-6">
      <div class="text-xs text-subtle mb-2">
        <NuxtLink to="/">ראשי</NuxtLink> ›
        <NuxtLink to="/kinds/">סוגי מידע</NuxtLink> › {{ label }}
      </div>
      <h1 class="font-display">{{ label }}</h1>
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
