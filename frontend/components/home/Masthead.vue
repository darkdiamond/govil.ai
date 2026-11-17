<script setup lang="ts">
// The top of the homepage: what the site is, how much is in it, and a search
// box with suggestions as you type (HomeSearch.vue).
import type { TagRow } from "~/utils/home";
import { formatNumber as fmt } from "~/composables/useRelativeTime";
import { tagPath } from "~/utils/paths";

defineProps<{
  datasetCount: number;
  ministryCount: number;
  chips: TagRow[];
}>();

/** Topic tiles shown on a phone: 5 + "all topics" fill a 2-column grid. The
 * rest show from sm up (7 + "all topics" in 4 columns). An even grid, not
 * wrapped pills: pills wrapped raggedly and left holes in the last row. */
const MOBILE_TILES = 5;
const TILE =
  "flex items-center justify-between gap-2 h-full min-h-11 px-3 py-2 text-sm bg-white border border-rule rounded-gov no-underline transition-colors hover:border-brand hover:bg-brand-50 hover:no-underline";
</script>

<template>
  <section class="pt-6 sm:pt-10 pb-2">
    <h1
      class="m-0 max-w-4xl font-display font-semibold text-ink-deep tracking-tight leading-[1.1] text-balance text-[clamp(2rem,1.4rem+2.4vw,3.25rem)]"
    >
      מאגרי המידע הממשלתיים של ישראל, מוסברים ומחוברים
    </h1>
    <p v-if="datasetCount" class="m-0 mt-3 text-lg text-subtle text-pretty">
      {{ fmt(datasetCount) }} מאגרים מ-{{ fmt(ministryCount) }} גופים, מתעדכנים
      מהנתונים הרשמיים.
    </p>

    <HomeSearch />

    <nav
      v-if="chips.length"
      aria-labelledby="home-topics-h"
      class="mt-6 max-w-3xl"
    >
      <p id="home-topics-h" class="m-0 mb-2 text-sm text-subtle">
        או התחילו מנושא
      </p>
      <ul class="list-none m-0 p-0 grid grid-cols-2 sm:grid-cols-4 gap-2">
        <li
          v-for="(c, i) in chips"
          :key="c.slug"
          :class="{ 'max-sm:hidden': i >= MOBILE_TILES }"
        >
          <NuxtLink :to="tagPath(c.slug)" :class="TILE">
            <span class="font-medium text-ink leading-tight">{{ c.name }}</span>
            <span class="text-xs text-subtle tabular-nums"
              >{{ fmt(c.count) }}<span class="sr-only"> מאגרים</span></span
            >
          </NuxtLink>
        </li>
        <li>
          <NuxtLink to="/tags/" :class="[TILE, 'text-brand']">
            <span class="font-medium leading-tight">כל הנושאים</span>
            <span aria-hidden="true">←</span>
          </NuxtLink>
        </li>
      </ul>
    </nav>
  </section>
</template>
