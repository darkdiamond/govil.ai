<script setup lang="ts">
// "Recent news" on a dataset page: the latest articles that drew on it.
import type { NewsIndexEntry } from "~/types/news";

defineProps<{ articles: NewsIndexEntry[] }>();
</script>

<template>
  <section
    v-if="articles.length"
    class="mt-10"
    aria-labelledby="related-news-h"
  >
    <h2 id="related-news-h" class="text-xl font-display text-ink mb-3">
      חדשות על המאגר
    </h2>
    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <NewsCard v-for="a in articles" :key="a.slug" :article="a" />
    </div>
  </section>
</template>
