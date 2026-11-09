<script setup lang="ts">
import type { NewsIndexEntry } from "~/types/news";
import { newsDate } from "~/utils/news";

defineProps<{ article: NewsIndexEntry; compact?: boolean }>();
</script>

<template>
  <NuxtLink
    :to="`/news/${article.slug}/`"
    class="card card-hover block overflow-hidden no-underline hover:no-underline"
  >
    <img
      v-if="article.hero && !compact"
      :src="article.hero"
      :alt="article.hero_alt || ''"
      width="1600"
      height="900"
      loading="lazy"
      class="block w-full aspect-[16/9] object-cover"
    />
    <div class="p-4">
      <time :datetime="article.published_at" class="text-xs text-subtle">
        {{ newsDate(article.published_at) }}
      </time>
      <h3 class="m-0 mt-1 text-lg font-display text-ink leading-snug">
        {{ article.headline }}
      </h3>
      <p v-if="!compact" class="m-0 mt-2 text-sm text-subtle line-clamp-3">
        {{ article.dek }}
      </p>
      <div
        v-if="article.stat && !compact"
        class="mt-3 pt-3 border-t border-rule flex items-end justify-between gap-3"
      >
        <div class="min-w-0">
          <div
            class="text-xl font-medium text-ink-deep tabular-nums leading-none"
          >
            <bdi>{{ article.stat.value }}</bdi>
          </div>
          <div class="text-xs text-subtle mt-1 line-clamp-1">
            {{ article.stat.label }}
          </div>
        </div>
        <Sparkline v-if="article.spark" :values="article.spark" />
      </div>
    </div>
  </NuxtLink>
</template>
