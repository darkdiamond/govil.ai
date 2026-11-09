<script setup lang="ts">
import type { NewsIndexEntry } from "~/types/news";
import { loadNewsIndexServer } from "~/utils/news";

const { data } = await useAsyncData("news-index", async () => {
  if (!import.meta.server) return null;
  return { articles: await loadNewsIndexServer() };
});
const articles = computed<NewsIndexEntry[]>(() => data.value?.articles ?? []);
const lead = computed(() => articles.value[0]);
const rest = computed(() => articles.value.slice(1));

const SITE_URL = "https://govil.ai";
useSeo({
  title: "חדשות מהנתונים | govil.ai",
  description:
    "כתבות קצרות על מה שהשתנה במאגרי המידע הממשלתיים: שיאים, ירידות, מגמות ושנה מול שנה, ישר מהנתונים הרשמיים.",
  path: "/news/",
  breadcrumbs: [
    { name: "ראשי", url: `${SITE_URL}/` },
    { name: "חדשות", url: `${SITE_URL}/news/` },
  ],
  extraJsonLd: {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "חדשות מהנתונים",
    url: `${SITE_URL}/news/`,
    hasPart: articles.value.slice(0, 30).map((a) => ({
      "@type": "NewsArticle",
      headline: a.headline,
      url: `${SITE_URL}/news/${a.slug}/`,
      datePublished: a.published_at,
    })),
  },
});
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8 sm:py-12">
    <header class="mb-8">
      <h1 class="text-3xl sm:text-4xl font-display text-ink-deep m-0">
        חדשות מהנתונים
      </h1>
      <p class="text-lg text-subtle mt-2 mb-0 max-w-2xl">
        מה השתנה במאגרי המידע הממשלתיים, ולמה זה חשוב. כל מספר בכתבות מגיע
        מהנתונים הרשמיים.
        <NuxtLink to="/news/about/">איך אנחנו עובדים</NuxtLink>
      </p>
    </header>

    <p v-if="!articles.length" class="text-subtle">
      עוד לא פורסמו כתבות. הכתבה הראשונה תופיע כאן.
    </p>

    <NuxtLink
      v-if="lead"
      :to="`/news/${lead.slug}/`"
      class="card card-hover grid md:grid-cols-2 overflow-hidden no-underline hover:no-underline mb-8"
    >
      <img
        v-if="lead.hero"
        :src="lead.hero"
        :alt="lead.hero_alt || ''"
        width="1600"
        height="900"
        class="block w-full h-full aspect-[16/9] object-cover"
      />
      <div class="p-5 sm:p-8 flex flex-col justify-center">
        <h2
          class="m-0 text-2xl sm:text-3xl font-display text-ink leading-tight"
        >
          {{ lead.headline }}
        </h2>
        <p class="mt-3 mb-0 text-subtle">{{ lead.dek }}</p>
      </div>
    </NuxtLink>

    <div v-if="rest.length" class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
      <NewsCard v-for="a in rest" :key="a.slug" :article="a" />
    </div>
  </div>
</template>
