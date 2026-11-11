<script setup lang="ts">
import { SITE_URL } from "~/utils/paths";
import { loadSearchIndex } from "~/utils/search-index";

useSeo({
  title: "מאגרי מידע לפי משרד ממשלתי — סקירה מלאה",
  description:
    "משרדי הממשלה והרשויות שמפרסמים מאגרי מידע ציבוריים. לחצו על משרד כדי לראות את כל המאגרים שלו עם תקצירים ותובנות.",
  path: "/ministries/",
  breadcrumbs: [
    { name: "ראשי", url: `${SITE_URL}/` },
    { name: "משרדים", url: `${SITE_URL}/ministries/` },
  ],
});

interface MinistryRow {
  slug: string;
  title: string;
  count: number;
}

// Bake only the aggregated rows into the payload — not the index itself.
const { data } = await useAsyncData("ministries-index", async () => {
  const index = await loadSearchIndex();
  const by = new Map<string, MinistryRow>();
  for (const d of index.datasets) {
    if (!d.organization_slug || !d.organization) continue;
    const row = by.get(d.organization_slug);
    if (row) row.count++;
    else
      by.set(d.organization_slug, {
        slug: d.organization_slug,
        title: d.organization,
        count: 1,
      });
  }
  return [...by.values()].sort((a, b) => b.count - a.count);
});

const ministries = computed<MinistryRow[]>(() => data.value ?? []);
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <section class="mb-6">
      <div class="text-xs text-subtle mb-2">
        <NuxtLink to="/">ראשי</NuxtLink> › משרדים
      </div>
      <h1 class="font-display">משרדים ממשלתיים</h1>
      <p class="text-subtle mt-2 max-w-2xl">
        {{ ministries.length }} ארגונים מפרסמים מאגרי מידע ציבורי.
      </p>
    </section>

    <section class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      <NuxtLink
        v-for="m in ministries"
        :key="m.slug"
        :to="`/ministries/${m.slug}/`"
        class="card card-hover p-4 no-underline hover:no-underline block flex items-start gap-3"
      >
        <img
          src="/icons/building-2.svg"
          alt=""
          class="w-5 h-5 mt-0.5 text-brand opacity-80"
        />
        <div>
          <div class="font-display text-ink">{{ m.title }}</div>
          <div class="text-xs text-subtle mt-1">{{ m.count }} מאגרים</div>
        </div>
      </NuxtLink>
    </section>
  </div>
</template>
