<script setup lang="ts">
// The top of /news/: the newest story large, the next few beside it as
// thumbnail rows. The lead has no card frame: the picture and the type carry it.
import type { NewsIndexEntry } from "~/types/news";
import { newsDate } from "~/utils/news";
import { thumbOf } from "~/utils/news-front";

defineProps<{ lead: NewsIndexEntry; side: NewsIndexEntry[] }>();
</script>

<template>
  <div
    class="grid gap-8 lg:gap-10 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]"
  >
    <article class="group relative min-w-0">
      <img
        v-if="lead.hero"
        :src="lead.hero"
        :alt="lead.hero_alt || ''"
        width="1600"
        height="900"
        fetchpriority="high"
        class="block w-full aspect-[16/9] lg:aspect-[2/1] object-cover rounded-gov bg-surface"
      />
      <div class="mt-5 text-sm text-subtle flex flex-wrap items-center gap-x-3">
        <NewsKindBadge :kind="lead.kind" />
        <span v-if="lead.topic" class="text-brand-700 font-medium">{{
          lead.topic.label
        }}</span>
        <time :datetime="lead.published_at">{{
          newsDate(lead.published_at)
        }}</time>
      </div>
      <h3
        class="m-0 mt-2 text-[1.75rem] sm:text-[2.25rem] leading-[1.15] font-display font-medium text-ink-deep"
      >
        <!-- The stretched link makes the whole lead clickable. -->
        <NuxtLink
          :to="`/news/${lead.slug}/`"
          class="text-ink-deep no-underline group-hover:underline after:absolute after:inset-0"
          >{{ lead.headline }}</NuxtLink
        >
      </h3>
      <p class="m-0 mt-3 text-lg text-subtle max-w-[65ch]">{{ lead.dek }}</p>
      <div
        v-if="lead.stat"
        class="mt-5 pt-4 border-t border-rule flex items-end justify-between gap-6 max-w-xl"
      >
        <div class="min-w-0">
          <div
            class="text-4xl font-medium text-ink-deep tabular-nums leading-none"
          >
            <bdi>{{ lead.stat.value }}</bdi>
          </div>
          <div class="text-sm text-subtle mt-1">{{ lead.stat.label }}</div>
        </div>
        <Sparkline
          v-if="lead.spark"
          :values="lead.spark"
          :width="160"
          :height="48"
        />
      </div>
    </article>

    <ul v-if="side.length" class="list-none m-0 p-0 min-w-0">
      <li
        v-for="a in side"
        :key="a.slug"
        class="group relative grid grid-cols-[minmax(0,1fr)_6.5rem] sm:grid-cols-[minmax(0,1fr)_9.5rem] gap-4 py-4 first:pt-0 border-b border-rule last:border-b-0"
      >
        <div class="min-w-0">
          <div class="text-xs text-subtle flex flex-wrap items-center gap-x-2">
            <NewsKindBadge :kind="a.kind" />
            <span v-if="a.topic" class="text-brand-700 font-medium">{{
              a.topic.label
            }}</span>
            <time :datetime="a.published_at">{{
              newsDate(a.published_at)
            }}</time>
          </div>
          <h3
            class="m-0 mt-1 text-base sm:text-lg leading-snug font-display text-ink"
          >
            <NuxtLink
              :to="`/news/${a.slug}/`"
              class="text-ink no-underline group-hover:underline after:absolute after:inset-0"
              >{{ a.headline }}</NuxtLink
            >
          </h3>
          <p v-if="a.stat" class="m-0 mt-1 text-sm text-subtle">
            <bdi class="font-medium text-ink-deep tabular-nums">{{
              a.stat.value
            }}</bdi>
            {{ a.stat.label }}
          </p>
        </div>
        <img
          v-if="thumbOf(a)"
          :src="thumbOf(a)!"
          alt=""
          width="480"
          height="360"
          loading="lazy"
          class="block w-full aspect-[4/3] object-cover rounded-gov-md bg-surface"
        />
      </li>
    </ul>
  </div>
</template>
