<script setup lang="ts">
// The top of the homepage: what the site is, how much is in it, and a search
// box. The search is a plain GET form to /datasets/?q=, which reads the query
// on load, so it works before hydration and without JS.
import type { TagRow } from "~/utils/home";
import { tagPath } from "~/utils/paths";

defineProps<{
  datasetCount: number;
  ministryCount: number;
  chips: TagRow[];
}>();

const fmt = (n: number) => n.toLocaleString("he-IL");
</script>

<template>
  <section class="pt-6 sm:pt-10 pb-8 border-b-2 border-ink-deep">
    <h1
      class="m-0 max-w-4xl font-display font-semibold text-ink-deep tracking-tight leading-[1.1] text-[clamp(2rem,1.4rem+2.4vw,3.25rem)]"
    >
      מאגרי המידע הממשלתיים של ישראל, מוסברים ומחוברים
    </h1>
    <p v-if="datasetCount" class="m-0 mt-3 text-lg text-subtle">
      {{ fmt(datasetCount) }} מאגרים מ-{{ fmt(ministryCount) }} גופים, מתעדכנים
      מהנתונים הרשמיים.
    </p>

    <form
      role="search"
      action="/datasets/"
      method="get"
      class="mt-6 flex flex-col sm:flex-row gap-2 max-w-3xl"
    >
      <label for="home-search" class="sr-only">חיפוש מאגר מידע</label>
      <input
        id="home-search"
        type="search"
        name="q"
        autocomplete="off"
        enterkeyhint="search"
        placeholder="חיפוש מאגר: רכב, רופאים, מים, בתי ספר…"
        class="w-full sm:flex-1 min-w-0 h-14 shrink-0 px-4 text-lg bg-white text-ink placeholder:text-subtle border-2 border-ink-deep rounded-gov focus:outline-none focus-visible:ring-4 focus-visible:ring-brand-200 focus-visible:border-brand"
      />
      <button type="submit" class="btn-primary h-14 px-7 text-lg font-medium">
        חיפוש
      </button>
    </form>

    <nav
      v-if="chips.length"
      aria-label="נושאים מבוקשים"
      class="mt-4 -mx-4 px-4 sm:mx-0 sm:px-0 overflow-x-auto"
    >
      <ul class="list-none m-0 p-0 flex sm:flex-wrap gap-2 w-max sm:w-auto">
        <li v-for="c in chips" :key="c.slug">
          <NuxtLink
            :to="tagPath(c.slug)"
            class="tag-chip text-sm whitespace-nowrap no-underline hover:bg-brand-100"
            >{{ c.name }}</NuxtLink
          >
        </li>
      </ul>
    </nav>
  </section>
</template>
