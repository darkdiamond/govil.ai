<script setup lang="ts">
// The top of the homepage: what the site is, how much is in it, and a search
// box. The search is a plain GET form to /datasets/?q=, which reads the query
// on load, so it works before hydration and without JS.
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

    <form
      role="search"
      action="/datasets/"
      method="get"
      class="mt-6 flex gap-2 max-w-3xl"
    >
      <label for="home-search" class="sr-only">חיפוש מאגר מידע</label>
      <input
        id="home-search"
        type="search"
        name="q"
        autocomplete="off"
        enterkeyhint="search"
        placeholder="חיפוש: רכב, רופאים, בתי ספר…"
        class="flex-1 min-w-0 h-14 px-3 sm:px-4 text-base sm:text-lg bg-white text-ink placeholder:text-subtle border-2 border-ink-deep rounded-gov focus:outline-none focus-visible:ring-4 focus-visible:ring-brand-200 focus-visible:border-brand"
      />
      <!-- A square icon button on a phone keeps the box and button on one row. -->
      <button
        type="submit"
        class="btn-primary shrink-0 h-14 w-14 sm:w-auto px-0 sm:px-7 text-lg font-medium"
      >
        <img src="/icons/search.svg" alt="" class="w-6 h-6 invert sm:hidden" />
        <span class="sr-only sm:not-sr-only">חיפוש</span>
      </button>
    </form>

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
