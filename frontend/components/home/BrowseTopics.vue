<script setup lang="ts">
// Ways into the catalog besides search: topics (with their biggest tags) and
// the publishing bodies with the most datasets.
import type { HomeTopic, MinistryRow } from "~/utils/home";
import { formatNumber as fmt } from "~/composables/useRelativeTime";
import { tagPath } from "~/utils/paths";

defineProps<{ topics: HomeTopic[]; ministries: MinistryRow[] }>();
</script>

<template>
  <section
    v-if="topics.length || ministries.length"
    aria-labelledby="home-browse-h"
    class="min-w-0"
  >
    <div
      class="flex items-baseline justify-between gap-4 pb-2 mb-4 border-b-2 border-ink-deep"
    >
      <h2 id="home-browse-h" class="m-0 text-2xl font-display text-ink-deep">
        עיון לפי נושא
      </h2>
      <NuxtLink to="/tags/" class="text-sm shrink-0">כל הנושאים</NuxtLink>
    </div>

    <ul
      v-if="topics.length"
      class="list-none m-0 p-0 grid grid-cols-1 sm:grid-cols-2 gap-x-6"
    >
      <li v-for="t in topics" :key="t.id" class="py-3 border-b border-rule">
        <h3 class="m-0 text-base font-display text-ink">
          <NuxtLink :to="`/tags/#${t.id}`" class="text-ink">{{
            t.label
          }}</NuxtLink>
          <span class="ms-1.5 text-sm font-normal text-subtle tabular-nums"
            >{{ fmt(t.count) }} מאגרים</span
          >
        </h3>
        <p class="m-0 mt-1 text-sm leading-relaxed">
          <template v-for="(tag, i) in t.tags" :key="tag.slug">
            <NuxtLink :to="tagPath(tag.slug)">{{ tag.name }}</NuxtLink
            ><span v-if="i < t.tags.length - 1" class="text-subtle">, </span>
          </template>
        </p>
      </li>
    </ul>

    <div v-if="ministries.length" class="mt-6">
      <h3 class="m-0 text-base font-display text-ink">
        הגופים עם הכי הרבה מאגרים
      </h3>
      <ul
        class="list-none m-0 p-0 mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-sm"
      >
        <li v-for="m in ministries" :key="m.slug">
          <NuxtLink :to="`/ministries/${m.slug}/`">{{ m.title }}</NuxtLink>
          <span class="text-subtle tabular-nums"> ({{ fmt(m.count) }})</span>
        </li>
      </ul>
      <p class="m-0 mt-3 text-sm">
        <NuxtLink to="/ministries/">כל הגופים</NuxtLink>
        <span class="text-subtle" aria-hidden="true"> | </span>
        <NuxtLink to="/kinds/">לפי סוג מידע: מפות, סדרות זמן, רשימות</NuxtLink>
      </p>
    </div>
  </section>
</template>
