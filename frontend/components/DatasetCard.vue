<script setup lang="ts">
import type { SlimEntry } from '~/types/manifest'

defineProps<{ entry: SlimEntry }>()
</script>

<template>
  <a
    :href="`/datasets/${encodeURI(entry.page_slug || entry.id)}/`"
    class="card card-hover p-4 no-underline hover:no-underline block"
  >
    <div class="flex gap-2 flex-wrap mb-2 text-xs">
      <span v-if="entry.source_status === 'unavailable'" class="badge bg-[#fff9e6] text-[#8a6d00] border-[#ffc107]">ארכיון</span>
      <span v-if="entry.organization" class="badge">{{ entry.organization }}</span>
      <span v-for="f in entry.formats.slice(0, 3)" :key="f" class="badge">{{ f }}</span>
    </div>
    <h3 class="font-display text-ink m-0 mb-2">{{ entry.title }}</h3>
    <p v-if="entry.summary_he" class="text-sm text-subtle leading-relaxed line-clamp-2 m-0">
      {{ entry.summary_he }}
    </p>
    <div class="flex items-center justify-between mt-2">
      <div v-if="entry.last_analyzed_at || entry.metadata_modified" class="text-xs text-subtle">עודכן {{ relativeTimeHe(entry.last_analyzed_at || entry.metadata_modified) }}</div>
      <div v-if="entry.tags_he.length" class="flex gap-1">
        <span v-for="t in entry.tags_he.slice(0, 2)" :key="t" class="tag-chip">{{ t }}</span>
      </div>
    </div>
    <div class="text-[11px] text-subtle mt-2 flex items-center gap-1">
      <span aria-hidden="true">✨</span>
      <span>נכתב ע״י סוכן AI</span>
    </div>
  </a>
</template>
