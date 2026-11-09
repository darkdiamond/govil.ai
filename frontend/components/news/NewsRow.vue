<script setup lang="ts">
// One story in the /news/ list: date column, headline + dek, and the story's
// key number with its series line.
import type { NewsIndexEntry } from "~/types/news";

const props = defineProps<{ article: NewsIndexEntry }>();

const DAY = new Intl.DateTimeFormat("he-IL", {
  day: "numeric",
  timeZone: "Asia/Jerusalem",
});
const WEEKDAY = new Intl.DateTimeFormat("he-IL", {
  weekday: "short",
  timeZone: "Asia/Jerusalem",
});
const when = computed(() => {
  const d = new Date(props.article.published_at);
  if (Number.isNaN(d.getTime())) return null;
  return { day: DAY.format(d), weekday: WEEKDAY.format(d) };
});
</script>

<template>
  <article
    class="group relative grid grid-cols-[3rem_1fr] sm:grid-cols-[3.5rem_1fr_auto] gap-x-4 gap-y-2 py-5 border-b border-rule"
  >
    <time
      v-if="when"
      :datetime="article.published_at"
      class="row-span-2 sm:row-span-1 text-center leading-none pt-1"
    >
      <span class="block text-2xl font-medium text-ink-deep tabular-nums">{{
        when.day
      }}</span>
      <span class="block text-xs text-subtle mt-1">{{ when.weekday }}</span>
    </time>
    <span v-else class="row-span-2 sm:row-span-1" />

    <div class="min-w-0">
      <h3 class="m-0 text-lg sm:text-xl font-display text-ink leading-snug">
        <!-- The stretched link makes the whole row clickable. -->
        <NuxtLink
          :to="`/news/${article.slug}/`"
          class="text-ink no-underline group-hover:underline after:absolute after:inset-0"
          >{{ article.headline }}</NuxtLink
        >
      </h3>
      <p class="m-0 mt-1 text-subtle line-clamp-2">{{ article.dek }}</p>
      <p
        v-if="article.topic || article.minutes"
        class="m-0 mt-2 text-xs text-subtle flex flex-wrap gap-x-3"
      >
        <span v-if="article.topic" class="text-brand-700 font-medium">{{
          article.topic.label
        }}</span>
        <span v-if="article.minutes">קריאה של {{ article.minutes }} דק׳</span>
      </p>
    </div>

    <div
      v-if="article.stat || article.spark"
      class="col-start-2 sm:col-start-3 sm:row-start-1 flex sm:flex-col items-center sm:items-end gap-3 sm:gap-1 sm:w-40 sm:text-end"
    >
      <div v-if="article.stat" class="min-w-0">
        <div
          class="text-2xl font-medium text-ink-deep tabular-nums leading-none"
        >
          <bdi>{{ article.stat.value }}</bdi>
        </div>
        <div class="text-xs text-subtle mt-1 line-clamp-2">
          {{ article.stat.label }}
        </div>
      </div>
      <Sparkline v-if="article.spark" :values="article.spark" />
    </div>
  </article>
</template>
