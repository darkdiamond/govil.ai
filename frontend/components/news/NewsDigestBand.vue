<script setup lang="ts">
// The weekly digest gets the one dark band on /news/: it is the week's
// roundup, not one more story in the flow.
import type { NewsIndexEntry } from "~/types/news";
import { newsDate } from "~/utils/news";

defineProps<{ article: NewsIndexEntry }>();
</script>

<template>
  <article
    class="group relative grid overflow-hidden rounded-gov bg-ink text-white"
    :class="article.hero && 'md:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]'"
  >
    <img
      v-if="article.hero"
      :src="article.hero"
      :alt="article.hero_alt || ''"
      width="1600"
      height="900"
      loading="lazy"
      class="block w-full h-full aspect-[16/9] md:aspect-auto object-cover"
    />
    <div class="p-6 sm:p-8 flex flex-col justify-center">
      <p class="m-0 text-sm text-brand-100">
        הסיכום השבועי,
        <time :datetime="article.published_at">{{
          newsDate(article.published_at)
        }}</time>
      </p>
      <h3
        class="m-0 mt-2 text-2xl sm:text-3xl leading-tight font-display font-medium"
      >
        <NuxtLink
          :to="`/news/${article.slug}/`"
          class="text-white no-underline group-hover:underline after:absolute after:inset-0 focus-visible:outline-white"
          >{{ article.headline }}</NuxtLink
        >
      </h3>
      <p class="m-0 mt-3 text-brand-100 max-w-[60ch]">{{ article.dek }}</p>
    </div>
  </article>
</template>
