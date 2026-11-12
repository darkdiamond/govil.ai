<script setup lang="ts">
// A horizontal story tile: picture beside the text. Framed as a card on the
// analyses band; `plain` (a topic desk's first story) drops the frame.
import type { NewsIndexEntry } from "~/types/news";
import { newsDate } from "~/utils/news";
import { thumbOf } from "~/utils/news-front";

defineProps<{
  article: NewsIndexEntry;
  showTopic?: boolean;
  plain?: boolean;
}>();
</script>

<template>
  <article
    class="group relative grid grid-cols-[minmax(0,1fr)_6.5rem] sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-4 sm:gap-5"
    :class="
      !plain &&
      'bg-white rounded-gov p-3 sm:p-4 shadow-card hover:shadow-card-hover transition-shadow'
    "
  >
    <img
      v-if="thumbOf(article)"
      :src="thumbOf(article)!"
      :alt="article.hero_alt || ''"
      width="480"
      height="360"
      loading="lazy"
      class="order-last sm:order-first block w-full aspect-[4/3] object-cover rounded-gov-md bg-surface"
    />
    <div class="min-w-0 flex flex-col">
      <div class="text-xs text-subtle flex flex-wrap items-center gap-x-2">
        <span
          v-if="showTopic && article.topic"
          class="text-brand-700 font-medium"
          >{{ article.topic.label }}</span
        >
        <time :datetime="article.published_at">{{
          newsDate(article.published_at)
        }}</time>
      </div>
      <h3
        class="m-0 mt-1 text-base sm:text-lg leading-snug font-display text-ink"
      >
        <NuxtLink
          :to="`/news/${article.slug}/`"
          class="text-ink no-underline group-hover:underline after:absolute after:inset-0"
          >{{ article.headline }}</NuxtLink
        >
      </h3>
      <!-- On a phone the tile is a compact row: no dek. -->
      <p class="hidden sm:block m-0 mt-2 text-sm text-subtle line-clamp-3">
        {{ article.dek }}
      </p>
      <p
        v-if="article.stat"
        class="m-0 mt-auto pt-2 sm:pt-3 text-sm text-subtle"
      >
        <bdi
          class="block text-lg sm:text-2xl font-medium text-ink-deep tabular-nums leading-none"
          >{{ article.stat.value }}</bdi
        >
        <span class="line-clamp-1 mt-1">{{ article.stat.label }}</span>
      </p>
    </div>
  </article>
</template>
