<script setup lang="ts">
import type { NewsIndexEntry } from "~/types/news";
import { loadNewsIndex, newsDate } from "~/utils/news";

// Prerender and client-side navigation both (utils/news.ts).
const { data } = await useAsyncData("news-index", async () => ({
  articles: await loadNewsIndex(),
}));
const articles = computed<NewsIndexEntry[]>(() => data.value?.articles ?? []);

const PAGE = 30;
const TZ = "Asia/Jerusalem";
const MONTH_KEY = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  timeZone: TZ,
});
const MONTH_LABEL = new Intl.DateTimeFormat("he-IL", {
  month: "long",
  year: "numeric",
  timeZone: TZ,
});
const monthKey = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : MONTH_KEY.format(d).slice(0, 7);
};
const monthLabel = (key: string) =>
  key ? MONTH_LABEL.format(new Date(`${key}-15T12:00:00Z`)) : "ללא תאריך";

// Filters live in the query string (?topic=, ?month=) so a filtered view can
// be shared. The page is prerendered unfiltered: read the query only after
// mount, or a deep link would hydrate against different markup.
const route = useRoute();
const mounted = ref(false);
onMounted(() => (mounted.value = true));
const queryValue = (k: string) => {
  const v = route.query[k];
  return mounted.value && typeof v === "string" && v ? v : null;
};
const activeTopic = computed(() => queryValue("topic"));
const activeMonth = computed(() => queryValue("month"));
const filtered = computed(
  () => activeTopic.value !== null || activeMonth.value !== null
);

const topics = computed(() => {
  const by = new Map<string, { id: string; label: string; count: number }>();
  for (const a of articles.value) {
    if (!a.topic) continue;
    const t = by.get(a.topic.id) ?? { ...a.topic, count: 0 };
    t.count++;
    by.set(a.topic.id, t);
  }
  return [...by.values()].sort(
    (x, y) => y.count - x.count || x.label.localeCompare(y.label, "he")
  );
});
const activeTopicLabel = computed(
  () => topics.value.find((t) => t.id === activeTopic.value)?.label ?? null
);

const months = computed(() => {
  const by = new Map<string, number>();
  for (const a of articles.value) {
    const k = monthKey(a.published_at);
    by.set(k, (by.get(k) ?? 0) + 1);
  }
  return [...by.entries()].map(([key, count]) => ({
    key,
    label: monthLabel(key),
    count,
  }));
});

// The datasets the stories drew on, most-covered first.
const sources = computed(() => {
  const by = new Map<
    string,
    { id: string; title: string; href: string; count: number }
  >();
  for (const a of articles.value) {
    for (const d of a.datasets ?? []) {
      if (!d.href || !d.title) continue;
      const s = by.get(d.id) ?? {
        id: d.id,
        title: d.title,
        href: d.href,
        count: 0,
      };
      s.count++;
      by.set(d.id, s);
    }
  }
  return [...by.values()]
    .sort((x, y) => y.count - x.count || x.title.localeCompare(y.title, "he"))
    .slice(0, 8);
});

// The newest story leads the unfiltered page; the list is everything else.
const lead = computed(() =>
  filtered.value ? null : (articles.value[0] ?? null)
);
const listed = computed(() =>
  articles.value.filter(
    (a) =>
      a !== lead.value &&
      (!activeTopic.value || a.topic?.id === activeTopic.value) &&
      (!activeMonth.value || monthKey(a.published_at) === activeMonth.value)
  )
);

const shown = ref(PAGE);
watch([activeTopic, activeMonth], () => (shown.value = PAGE));
const groups = computed(() => {
  const out: { key: string; label: string; items: NewsIndexEntry[] }[] = [];
  for (const a of listed.value.slice(0, shown.value)) {
    const key = monthKey(a.published_at);
    let g = out[out.length - 1];
    if (!g || g.key !== key) {
      g = { key, label: monthLabel(key), items: [] };
      out.push(g);
    }
    g.items.push(a);
  }
  return out;
});
const remaining = computed(() =>
  Math.max(0, listed.value.length - shown.value)
);

const filterTo = (patch: Record<string, string | null>) => {
  const query: Record<string, string> = {};
  const next = {
    topic: activeTopic.value,
    month: activeMonth.value,
    ...patch,
  };
  for (const [k, v] of Object.entries(next)) if (v) query[k] = v;
  return { path: "/news/", query };
};

const SITE_URL = "https://govil.ai";
useSeo({
  title: "חדשות מהנתונים | govil.ai",
  description:
    "כתבות קצרות על מה שהשתנה במאגרי המידע הממשלתיים: שיאים, ירידות, מגמות ושנה מול שנה, ישר מהנתונים הרשמיים.",
  path: "/news/",
  breadcrumbs: [
    { name: "ראשי", url: `${SITE_URL}/` },
    { name: "חדשות", url: `${SITE_URL}/news/` },
  ],
  extraJsonLd: {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "חדשות מהנתונים",
    url: `${SITE_URL}/news/`,
    hasPart: articles.value.slice(0, PAGE).map((a) => ({
      "@type": "NewsArticle",
      headline: a.headline,
      url: `${SITE_URL}/news/${a.slug}/`,
      datePublished: a.published_at,
    })),
  },
});
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8 sm:py-12">
    <header class="mb-8 max-w-3xl">
      <h1 class="text-3xl sm:text-4xl font-display text-ink-deep m-0">
        חדשות מהנתונים
      </h1>
      <p class="text-lg text-subtle mt-2 mb-0">
        מה השתנה במאגרי המידע הממשלתיים, ולמה זה חשוב. כל מספר בכתבות מגיע
        מהנתונים הרשמיים.
        <NuxtLink to="/news/about/">איך אנחנו עובדים</NuxtLink>
      </p>
    </header>

    <p v-if="!articles.length" class="text-subtle">
      עוד לא פורסמו כתבות. הכתבה הראשונה תופיע כאן.
    </p>

    <!-- Lead story: the picture, then the number that made it news. -->
    <article
      v-if="lead"
      class="card card-hover relative grid md:grid-cols-[3fr_2fr] overflow-hidden mb-10"
    >
      <picture v-if="lead.hero" class="block">
        <img
          :src="lead.hero"
          :alt="lead.hero_alt || ''"
          width="1600"
          height="900"
          fetchpriority="high"
          class="block w-full h-full aspect-[16/9] object-cover"
        />
      </picture>
      <div class="p-5 sm:p-8 flex flex-col justify-center gap-4">
        <div class="text-sm text-subtle flex flex-wrap gap-x-3">
          <span v-if="lead.topic" class="text-brand-700 font-medium">{{
            lead.topic.label
          }}</span>
          <time :datetime="lead.published_at">{{
            newsDate(lead.published_at)
          }}</time>
        </div>
        <h2
          class="m-0 text-2xl sm:text-3xl font-display text-ink leading-tight"
        >
          <NuxtLink
            :to="`/news/${lead.slug}/`"
            class="text-ink no-underline hover:underline after:absolute after:inset-0"
            >{{ lead.headline }}</NuxtLink
          >
        </h2>
        <p class="m-0 text-subtle">{{ lead.dek }}</p>
        <div
          v-if="lead.stat"
          class="flex items-end justify-between gap-4 border-t border-rule pt-4"
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
            :width="140"
            :height="44"
          />
        </div>
      </div>
    </article>

    <div
      v-if="articles.length > 1 || filtered"
      class="grid gap-10 lg:grid-cols-[1fr_18rem]"
    >
      <section aria-labelledby="news-list-h" class="min-w-0">
        <h2 id="news-list-h" class="sr-only">כל הכתבות</h2>

        <nav
          v-if="topics.length > 1"
          aria-label="סינון לפי נושא"
          class="flex flex-wrap gap-2 mb-2"
        >
          <NuxtLink
            :to="filterTo({ topic: null })"
            class="tag-chip no-underline"
            :class="!activeTopic && 'bg-brand text-white border-brand'"
            :aria-current="!activeTopic ? 'true' : undefined"
            >הכול</NuxtLink
          >
          <NuxtLink
            v-for="t in topics"
            :key="t.id"
            :to="filterTo({ topic: t.id })"
            class="tag-chip no-underline"
            :class="activeTopic === t.id && 'bg-brand text-white border-brand'"
            :aria-current="activeTopic === t.id ? 'true' : undefined"
            >{{ t.label }}</NuxtLink
          >
        </nav>

        <p
          v-if="filtered"
          class="text-sm text-subtle mt-4 mb-0 flex flex-wrap items-center gap-x-3"
          role="status"
        >
          <span>
            {{ listed.length }} כתבות
            <template v-if="activeTopicLabel">
              בנושא {{ activeTopicLabel }}</template
            >
            <template v-if="activeMonth">
              ב{{ monthLabel(activeMonth) }}</template
            >
          </span>
          <NuxtLink to="/news/">ניקוי הסינון</NuxtLink>
        </p>

        <section
          v-for="g in groups"
          :key="g.key"
          :aria-labelledby="`m-${g.key}`"
          class="mt-6"
        >
          <h3
            :id="`m-${g.key}`"
            class="m-0 pb-2 border-b-2 border-ink-deep text-base font-medium text-ink-deep"
          >
            {{ g.label }}
          </h3>
          <NewsRow v-for="a in g.items" :key="a.slug" :article="a" />
        </section>

        <p v-if="filtered && !listed.length" class="text-subtle mt-6">
          אין כתבות שמתאימות לסינון הזה.
        </p>

        <div v-if="remaining" class="mt-8 text-center">
          <button type="button" class="btn-ghost" @click="shown += PAGE">
            עוד {{ Math.min(PAGE, remaining) }} כתבות
          </button>
        </div>
      </section>

      <aside class="space-y-8 text-sm" aria-label="ניווט בחדשות">
        <section v-if="sources.length" aria-labelledby="news-sources-h">
          <h2
            id="news-sources-h"
            class="m-0 pb-2 border-b-2 border-ink-deep text-base font-medium text-ink-deep"
          >
            הנתונים מאחורי החדשות
          </h2>
          <ul class="list-none m-0 p-0">
            <li
              v-for="s in sources"
              :key="s.id"
              class="flex justify-between gap-3 py-2 border-b border-rule"
            >
              <!-- <a>, not NuxtLink: dataset pages are prerender-only. -->
              <a :href="s.href" class="min-w-0">{{ s.title }}</a>
              <span
                class="text-subtle tabular-nums shrink-0"
                :aria-label="`${s.count} כתבות`"
                >{{ s.count }}</span
              >
            </li>
          </ul>
        </section>

        <section v-if="months.length > 1" aria-labelledby="news-archive-h">
          <h2
            id="news-archive-h"
            class="m-0 pb-2 border-b-2 border-ink-deep text-base font-medium text-ink-deep"
          >
            ארכיון
          </h2>
          <ul class="list-none m-0 p-0">
            <li
              v-for="m in months"
              :key="m.key"
              class="flex justify-between gap-3 py-2 border-b border-rule"
            >
              <NuxtLink
                :to="filterTo({ month: m.key })"
                :aria-current="activeMonth === m.key ? 'true' : undefined"
                :class="activeMonth === m.key && 'font-medium'"
                >{{ m.label }}</NuxtLink
              >
              <span class="text-subtle tabular-nums">{{ m.count }}</span>
            </li>
          </ul>
        </section>

        <p class="m-0 text-subtle">
          הכתבות נכתבות אוטומטית מהנתונים הרשמיים ועוברות בדיקות אוטומטיות לפני
          פרסום. <NuxtLink to="/news/about/">על מערכת החדשות</NuxtLink>
        </p>
        <p class="m-0">
          <a href="/news/feed.xml">עדכונים ב-RSS</a>
        </p>
      </aside>
    </div>
  </div>
</template>
