<script setup lang="ts">
// A small label for articles that aren't breaking news: explainers (the daily
// floor's fill) and the weekly digest. News (or no kind: older articles) shows
// nothing.
import type { NewsKind } from "~/types/news";

const props = defineProps<{ kind?: NewsKind | null }>();

const LABELS: Partial<Record<NewsKind, string>> = {
  feature: "ניתוח נתונים",
  digest: "סיכום שבועי",
};
const label = computed(() => (props.kind ? LABELS[props.kind] : undefined));
</script>

<template>
  <span
    v-if="label"
    class="inline-block px-1.5 py-0.5 rounded-gov-sm bg-surface-alt text-ink text-xs font-medium leading-tight"
    >{{ label }}</span
  >
</template>
