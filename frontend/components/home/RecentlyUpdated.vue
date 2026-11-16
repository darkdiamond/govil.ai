<script setup lang="ts">
// The datasets whose pages re-rendered most recently: a page re-renders when
// its data moves, so this is "what changed in the data lately".
import type { UpdatedRow } from "~/utils/home";
import { cardDateLabel } from "~/utils/dataset-dates";
import { datasetPath } from "~/utils/paths";

defineProps<{ rows: UpdatedRow[] }>();

// Absolute date in the prerender, relative after mount (see DatasetCard).
const mounted = ref(false);
onMounted(() => {
  mounted.value = true;
});
</script>

<template>
  <section v-if="rows.length" aria-labelledby="home-updated-h" class="min-w-0">
    <div
      class="flex items-baseline justify-between gap-4 pb-2 mb-1 border-b-2 border-ink-deep"
    >
      <h2 id="home-updated-h" class="m-0 text-2xl font-display text-ink-deep">
        עודכנו לאחרונה
      </h2>
      <NuxtLink to="/datasets/" class="text-sm shrink-0">כל המאגרים</NuxtLink>
    </div>
    <ol class="list-none m-0 p-0">
      <li
        v-for="r in rows"
        :key="r.id"
        class="group relative py-3 border-b border-rule last:border-b-0"
      >
        <h3 class="m-0 text-base sm:text-lg font-display leading-snug">
          <!-- Full-page nav, like DatasetCard: dataset bodies run scripts. -->
          <a
            :href="datasetPath(r)"
            class="text-ink no-underline group-hover:underline after:absolute after:inset-0"
            >{{ r.title }}</a
          >
        </h3>
        <p class="m-0 mt-0.5 text-sm text-subtle">
          <span v-if="r.organization">{{ r.organization }}, </span>
          <span>{{ cardDateLabel(r.last_analyzed_at, mounted) }}</span>
        </p>
      </li>
    </ol>
  </section>
</template>
