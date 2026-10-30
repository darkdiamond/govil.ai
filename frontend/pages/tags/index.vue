<script setup lang="ts">
import { loadFullManifestServer } from "~/utils/search-index";

useSeo({
  title: "מאגרי מידע ממשלתיים לפי נושא",
  description:
    "כל הנושאים שמופיעים במאגרי המידע של ממשלת ישראל, מקובצים לפי תחום: תחבורה, מים, סביבה, בריאות, רווחה, משפט, כלכלה ועוד.",
  path: "/tags/",
  breadcrumbs: [
    { name: "ראשי", url: "https://govil.ai/" },
    { name: "נושאים", url: "https://govil.ai/tags/" },
  ],
});

interface TagRow {
  name: string;
  slug: string;
  count: number;
}
interface TopicGroup {
  id: string;
  label: string;
  intro: string;
  tags: TagRow[];
}

// Bake only the grouped [tag, slug, count] rows into the payload. Topics keep
// the vocabulary's order; tags within a topic are count DESC (tag_index order).
const { data } = await useAsyncData("tags-index", async () => {
  if (!import.meta.server) return null;
  const m = await loadFullManifestServer();
  const groups = new Map<string, TopicGroup>(
    (m.topics ?? []).map((t) => [
      t.id,
      { id: t.id, label: t.label_he, intro: t.intro_he ?? "", tags: [] },
    ])
  );
  const other: TopicGroup = {
    id: "other",
    label: "נושאים נוספים",
    intro: "",
    tags: [],
  };
  for (const [name, t] of Object.entries(m.tag_index ?? {})) {
    const g = (t.topic && groups.get(t.topic)) || other;
    g.tags.push({ name, slug: t.slug, count: t.count });
  }
  return [...groups.values(), other].filter((g) => g.tags.length);
});

const groups = computed(() => data.value ?? []);
const tagCount = computed(() =>
  groups.value.reduce((n, g) => n + g.tags.length, 0)
);

function tagHref(slug: string): string {
  return `/tags/${encodeURI(slug)}/`;
}
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <section class="mb-6">
      <div class="text-xs text-subtle mb-2">
        <NuxtLink to="/">ראשי</NuxtLink> › נושאים
      </div>
      <h1 class="font-display">נושאים</h1>
      <p class="text-subtle mt-2">
        {{ tagCount }} נושאים ב-{{ groups.length }} תחומים.
      </p>
      <nav class="flex flex-wrap gap-2 mt-4" aria-label="תחומים">
        <a
          v-for="g in groups"
          :key="g.id"
          :href="`#${g.id}`"
          class="badge hover:bg-brand-50"
          >{{ g.label }}</a
        >
      </nav>
    </section>

    <section
      v-for="g in groups"
      :id="g.id"
      :key="g.id"
      class="mb-8 scroll-mt-20"
    >
      <h2 class="font-display text-lg mb-1">{{ g.label }}</h2>
      <p
        v-if="g.intro"
        class="text-sm text-subtle mb-3 max-w-3xl leading-relaxed"
      >
        {{ g.intro }}
      </p>
      <div class="flex flex-wrap gap-2">
        <NuxtLink
          v-for="t in g.tags"
          :key="t.name"
          :to="tagHref(t.slug)"
          class="tag-chip hover:bg-brand-100 no-underline hover:no-underline inline-flex items-center gap-1.5"
        >
          <img src="/icons/tag.svg" alt="" class="w-3.5 h-3.5 opacity-80" />
          {{ t.name }} <span class="text-subtle ms-1">· {{ t.count }}</span>
        </NuxtLink>
      </div>
    </section>
  </div>
</template>
