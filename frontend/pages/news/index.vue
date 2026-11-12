<script setup lang="ts">
import { SITE_URL } from "~/utils/paths";
import type { NewsIndexEntry, NewsKind } from "~/types/news";
import { loadNewsIndex } from "~/utils/news";
import {
  MONTH_RE,
  buildFront,
  editionLine,
  monthKey,
  monthLabel,
} from "~/utils/news-front";

// Prerender and client-side navigation both (utils/news.ts).
const { data } = await useAsyncData("news-index", async () => ({
  articles: await loadNewsIndex(),
}));
const articles = computed<NewsIndexEntry[]>(() => data.value?.articles ?? []);

const PAGE = 30;
const KINDS: Record<NewsKind, string> = {
  news: "חדשות מהנתונים",
  feature: "ניתוחי נתונים",
  digest: "סיכומים שבועיים",
};
const isKind = (v: string | null): v is NewsKind => !!v && v in KINDS;

// Filters live in the query string (?topic=, ?month=, ?kind=) so a filtered
// view can be shared. The page is prerendered unfiltered: read the query (and
// the clock) only after mount, or a deep link would hydrate against different
// markup.
const route = useRoute();
const mounted = ref(false);
const now = ref<Date | null>(null);
onMounted(() => {
  mounted.value = true;
  now.value = new Date();
});
const queryValue = (k: string) => {
  const v = route.query[k];
  return mounted.value && typeof v === "string" && v ? v : null;
};
const activeTopic = computed(() => queryValue("topic"));
const activeMonth = computed(() => {
  const m = queryValue("month");
  return m && MONTH_RE.test(m) ? m : null;
});
const activeKind = computed(() => {
  const k = queryValue("kind");
  return isKind(k) ? k : null;
});
const filtered = computed(
  () =>
    activeTopic.value !== null ||
    activeMonth.value !== null ||
    activeKind.value !== null
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

// Undated stories have no archive entry (no ?month= value can select them).
const months = computed(() => {
  const by = new Map<string, number>();
  for (const a of articles.value) {
    const k = monthKey(a.published_at);
    if (k) by.set(k, (by.get(k) ?? 0) + 1);
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

const front = computed(() => buildFront(articles.value));
// Before mount (and in the prerender) just the date; then "today" or not.
const editionText = computed(() => {
  const e = editionLine(front.value.lead?.published_at, now.value);
  if (!e) return null;
  if (e.today) return `המהדורה של היום, ${e.date}`;
  return now.value ? `העדכון האחרון: ${e.date}` : e.date;
});

// The archive: what the front page didn't show, by month.
const archiveShown = ref(PAGE);
const archiveGroups = computed(() => {
  const out: { key: string; label: string; items: NewsIndexEntry[] }[] = [];
  for (const a of front.value.archive.slice(0, archiveShown.value)) {
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
const archiveRemaining = computed(() =>
  Math.max(0, front.value.archive.length - archiveShown.value)
);

// A filtered view is one grid of every matching story.
const matches = computed(() =>
  articles.value.filter(
    (a) =>
      (!activeTopic.value || a.topic?.id === activeTopic.value) &&
      (!activeMonth.value || monthKey(a.published_at) === activeMonth.value) &&
      (!activeKind.value || (a.kind ?? "news") === activeKind.value)
  )
);
const shown = ref(PAGE);
watch([activeTopic, activeMonth, activeKind], () => (shown.value = PAGE));
const remaining = computed(() =>
  Math.max(0, matches.value.length - shown.value)
);

const filterTo = (patch: Record<string, string | null>) => {
  const query: Record<string, string> = {};
  const next = {
    topic: activeTopic.value,
    month: activeMonth.value,
    kind: activeKind.value,
    ...patch,
  };
  for (const [k, v] of Object.entries(next)) if (v) query[k] = v;
  return { path: "/news/", query };
};

useSeo({
  title: "חדשות govil.ai",
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
    name: "חדשות govil.ai",
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
    <header
      class="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between"
    >
      <div class="max-w-3xl">
        <h1 class="text-3xl sm:text-4xl font-display text-ink-deep m-0">
          חדשות
        </h1>
        <p v-if="editionText" class="m-0 mt-2 text-lg text-ink">
          {{ editionText }}
        </p>
        <p class="m-0 mt-1 text-subtle">
          מה השתנה במאגרי המידע הממשלתיים. כל מספר בכתבות מגיע מהנתונים הרשמיים.
          <NuxtLink to="/news/about/">איך אנחנו עובדים</NuxtLink>
        </p>
      </div>
      <nav
        v-if="topics.length > 1"
        aria-label="סינון לפי נושא"
        class="flex flex-wrap gap-2 lg:justify-end lg:max-w-[50%]"
      >
        <NuxtLink
          v-for="t in topics"
          :key="t.id"
          :to="filterTo({ topic: activeTopic === t.id ? null : t.id })"
          class="tag-chip no-underline"
          :class="activeTopic === t.id && 'bg-brand text-white border-brand'"
          :aria-current="activeTopic === t.id ? 'true' : undefined"
          >{{ t.label }}</NuxtLink
        >
      </nav>
    </header>

    <p v-if="!articles.length" class="text-subtle">
      עוד לא פורסמו כתבות. הכתבה הראשונה תופיע כאן.
    </p>

    <!-- ── Filtered view: one grid of the matches ── -->
    <section v-if="filtered" aria-labelledby="news-results-h">
      <h2 id="news-results-h" class="sr-only">תוצאות הסינון</h2>
      <p
        class="text-sm text-subtle m-0 mb-6 flex flex-wrap items-center gap-x-3"
        role="status"
      >
        <span>
          {{ matches.length }}
          {{ activeKind ? KINDS[activeKind] : "כתבות" }}
          <template v-if="activeTopicLabel">
            בנושא {{ activeTopicLabel }}</template
          >
          <template v-if="activeMonth">
            ב{{ monthLabel(activeMonth) }}</template
          >
        </span>
        <NuxtLink to="/news/">חזרה לעמוד החדשות</NuxtLink>
      </p>
      <div
        v-if="matches.length"
        class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3"
      >
        <NewsCard
          v-for="a in matches.slice(0, shown)"
          :key="a.slug"
          :article="a"
        />
      </div>
      <p v-else class="text-subtle">אין כתבות שמתאימות לסינון הזה.</p>
      <div v-if="remaining" class="mt-8 text-center">
        <button type="button" class="btn-ghost" @click="shown += PAGE">
          עוד {{ Math.min(PAGE, remaining) }} כתבות
        </button>
      </div>
    </section>

    <!-- ── The front page ── -->
    <template v-else-if="front.lead">
      <section aria-labelledby="news-edition-h">
        <h2 id="news-edition-h" class="sr-only">הכתבות האחרונות</h2>
        <NewsEdition :lead="front.lead" :side="front.side" />
      </section>

      <section
        v-if="front.digest"
        aria-labelledby="news-digest-h"
        class="mt-14"
      >
        <h2 id="news-digest-h" class="sr-only">הסיכום השבועי</h2>
        <NewsDigestBand :article="front.digest" />
      </section>

      <section
        v-if="front.news.length"
        aria-labelledby="news-news-h"
        class="mt-14"
      >
        <div class="flex items-baseline justify-between gap-4 mb-5">
          <h2 id="news-news-h" class="m-0 text-2xl font-display text-ink-deep">
            {{ KINDS.news }}
          </h2>
          <NuxtLink :to="filterTo({ kind: 'news' })" class="text-sm shrink-0"
            >לכל החדשות מהנתונים</NuxtLink
          >
        </div>
        <!-- Rows of three cards (utils/news-front.ts); two stories, wide tiles. -->
        <div v-if="front.news.length === 2" class="grid gap-5 lg:grid-cols-2">
          <NewsTileWide
            v-for="a in front.news"
            :key="a.slug"
            :article="a"
            show-topic
          />
        </div>
        <div v-else class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <NewsCard v-for="a in front.news" :key="a.slug" :article="a" />
        </div>
      </section>

      <section
        v-if="front.analyses.length"
        aria-labelledby="news-analyses-h"
        class="mt-14 -mx-4 sm:mx-0 px-4 py-8 sm:p-8 bg-brand-100/60 sm:rounded-gov"
      >
        <div class="flex items-baseline justify-between gap-4 mb-5">
          <h2
            id="news-analyses-h"
            class="m-0 text-2xl font-display text-ink-deep"
          >
            {{ KINDS.feature }}
          </h2>
          <NuxtLink :to="filterTo({ kind: 'feature' })" class="text-sm shrink-0"
            >לכל הניתוחים</NuxtLink
          >
        </div>
        <div class="grid gap-5 lg:grid-cols-2">
          <NewsTileWide
            v-for="a in front.analyses"
            :key="a.slug"
            :article="a"
            show-topic
          />
        </div>
      </section>

      <div
        v-if="front.desks.length"
        class="mt-14 grid gap-x-10 gap-y-12 lg:grid-cols-2"
      >
        <section
          v-for="d in front.desks"
          :key="d.topic.id"
          :aria-labelledby="`desk-${d.topic.id}`"
          class="min-w-0"
        >
          <div
            class="flex items-baseline justify-between gap-4 pb-2 mb-4 border-b-2 border-ink-deep"
          >
            <h2
              :id="`desk-${d.topic.id}`"
              class="m-0 text-xl font-display text-ink-deep"
            >
              {{ d.topic.label }}
            </h2>
            <NuxtLink :to="filterTo({ topic: d.topic.id })" class="text-sm"
              >כל הכתבות בנושא</NuxtLink
            >
          </div>
          <NewsTileWide :article="d.items[0]!" plain />
          <ul class="list-none m-0 p-0 mt-2">
            <li
              v-for="a in d.items.slice(1)"
              :key="a.slug"
              class="py-3 border-b border-rule last:border-b-0"
            >
              <h3 class="m-0 text-base font-display leading-snug">
                <NuxtLink :to="`/news/${a.slug}/`" class="text-ink">{{
                  a.headline
                }}</NuxtLink>
              </h3>
            </li>
          </ul>
        </section>
      </div>

      <div class="mt-14 grid gap-10 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <section
          v-if="front.archive.length"
          aria-labelledby="news-archive-h"
          class="min-w-0"
        >
          <h2
            id="news-archive-h"
            class="m-0 text-2xl font-display text-ink-deep"
          >
            עוד כתבות
          </h2>
          <section
            v-for="g in archiveGroups"
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
          <div v-if="archiveRemaining" class="mt-8 text-center">
            <button
              type="button"
              class="btn-ghost"
              @click="archiveShown += PAGE"
            >
              עוד {{ Math.min(PAGE, archiveRemaining) }} כתבות
            </button>
          </div>
        </section>

        <!-- Beside the archive; with no archive yet, a row of its own. -->
        <aside
          class="text-sm"
          :class="
            front.archive.length
              ? 'space-y-8 lg:col-start-2'
              : 'lg:col-span-2 grid gap-8 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr] items-start'
          "
          aria-label="ניווט בחדשות"
        >
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

          <section v-if="months.length > 1" aria-labelledby="news-months-h">
            <h2
              id="news-months-h"
              class="m-0 pb-2 border-b-2 border-ink-deep text-base font-medium text-ink-deep"
            >
              לפי חודש
            </h2>
            <ul class="list-none m-0 p-0">
              <li
                v-for="m in months"
                :key="m.key"
                class="flex justify-between gap-3 py-2 border-b border-rule"
              >
                <NuxtLink :to="filterTo({ month: m.key })">{{
                  m.label
                }}</NuxtLink>
                <span class="text-subtle tabular-nums">{{ m.count }}</span>
              </li>
            </ul>
          </section>

          <div class="space-y-4">
            <p class="m-0 text-subtle">
              הכתבות נכתבות אוטומטית מהנתונים הרשמיים ועוברות בדיקות אוטומטיות
              לפני פרסום.
              <NuxtLink to="/news/about/">על מערכת החדשות</NuxtLink>
            </p>
            <p class="m-0">
              <a href="/news/feed.xml">עדכונים ב-RSS</a>
            </p>
          </div>
        </aside>
      </div>
    </template>
  </div>
</template>
