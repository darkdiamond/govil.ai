<script setup lang="ts">
import { SITE_URL, tagPath } from "~/utils/paths";
import type { NewsArticle, NewsIndexEntry } from "~/types/news";
import { buildDatasetLibTags } from "~/utils/dataset-libs";
import { loadArticle, loadNewsIndex, newsDate, safeHref } from "~/utils/news";

const route = useRoute();
const slug = String(route.params.slug);

// Runs at prerender AND in the browser on client-side navigation (see
// utils/news.ts): every loader here must work in both. Tag slugs ship in
// article.json (publish_news), so no search-index download is needed.
const { data, error } = await useAsyncData(`news-${slug}`, async () => {
  const [article, index] = await Promise.all([
    loadArticle(slug),
    loadNewsIndex(),
  ]);
  if (!article) return null;
  // More from the same topic first, then the latest.
  const self = index.find((a) => a.slug === slug);
  const others = index.filter((a) => a.slug !== slug);
  const sameTopic = self?.topic
    ? others.filter((a) => a.topic?.id === self.topic!.id)
    : [];
  const more = [
    ...sameTopic,
    ...others.filter((a) => !sameTopic.includes(a)),
  ].slice(0, 3);
  return { article, more, tagSlugs: article.tag_slugs ?? {} };
});

// A failed fetch on client-side navigation (offline, 5xx) is not a 404.
if (error.value) {
  throw createError({
    statusCode: 503,
    statusMessage: "Article unavailable",
    fatal: true,
  });
}
if (!data.value) {
  throw createError({
    statusCode: 404,
    statusMessage: "Article not found",
    fatal: true,
  });
}

const article = computed<NewsArticle>(() => data.value!.article);
const more = computed<NewsIndexEntry[]>(() => data.value!.more ?? []);
const tagSlugs = computed<Record<string, string>>(
  () => data.value!.tagSlugs ?? {}
);

useHead(
  buildDatasetLibTags({
    charts: article.value.charts.length > 0,
    map: false,
    explorer: false,
  })
);

const path = `/news/${slug}/`;
const url = `${SITE_URL}${path}`;
const hero = article.value.hero;
const abs = (p?: string) => (p ? `${SITE_URL}${p}` : undefined);
const images = [hero.sizes["16x9"], hero.sizes["4x3"], hero.sizes["1x1"]]
  .map(abs)
  .filter(Boolean) as string[];
const updated = article.value.updated_at !== article.value.published_at;
// Plain URLs, not typed Dataset nodes: Google validates every Dataset node it
// finds and requires description/license/creator, which article.json doesn't
// carry. The dataset page itself has the full Dataset. encodeURI matches
// buildDatasetLdSummary's form of the same URLs.
const basedOn = article.value.datasets
  .filter((d) => d.href)
  .map((d) => encodeURI(`${SITE_URL}${d.href}`));

useSeo({
  title: article.value.headline,
  description: article.value.dek,
  path,
  ogImage: hero.sizes["16x9"],
  ogType: "article",
  publishedTime: article.value.published_at,
  modifiedTime: article.value.updated_at,
  section: "חדשות",
  author: article.value.byline,
  keywords: article.value.tags,
  breadcrumbs: [
    { name: "ראשי", url: `${SITE_URL}/` },
    { name: "חדשות", url: `${SITE_URL}/news/` },
    { name: article.value.headline, url },
  ],
  extraJsonLd: {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    headline: article.value.headline,
    description: article.value.dek,
    image: images,
    datePublished: article.value.published_at,
    dateModified: article.value.updated_at,
    inLanguage: "he-IL",
    mainEntityOfPage: { "@type": "WebPage", "@id": url },
    articleSection: "חדשות",
    keywords: article.value.tags.join(", "),
    author: {
      "@type": "Organization",
      name: article.value.byline,
      url: `${SITE_URL}/news/about/`,
    },
    publisher: {
      "@type": "Organization",
      name: "govil.ai",
      url: SITE_URL,
      logo: {
        "@type": "ImageObject",
        url: `${SITE_URL}/web-app-manifest-512x512.png`,
      },
    },
    ...(basedOn.length ? { isBasedOn: basedOn } : {}),
  },
});
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-6 sm:py-10">
    <nav class="text-sm text-subtle mb-4" aria-label="פירורי לחם">
      <NuxtLink to="/">ראשי</NuxtLink>
      <span class="mx-1">/</span>
      <NuxtLink to="/news/">חדשות</NuxtLink>
    </nav>

    <article class="max-w-3xl mx-auto">
      <header>
        <NewsKindBadge :kind="article.kind" class="mb-2" />
        <h1
          class="text-3xl sm:text-4xl font-display text-ink-deep leading-tight m-0"
        >
          {{ article.headline }}
        </h1>
        <p class="text-lg sm:text-xl text-subtle mt-3 mb-4 leading-snug">
          {{ article.dek }}
        </p>
        <div
          class="text-sm text-subtle flex flex-wrap items-center gap-x-3 gap-y-1"
        >
          <NuxtLink to="/news/about/" class="text-ink font-medium">{{
            article.byline
          }}</NuxtLink>
          <time :datetime="article.published_at">{{
            newsDate(article.published_at, true)
          }}</time>
          <span v-if="updated">
            עודכן:
            <time :datetime="article.updated_at">{{
              newsDate(article.updated_at, true)
            }}</time>
          </span>
          <ShareButton
            class="ms-auto"
            :url="url"
            :title="article.headline"
            :text="article.dek"
            content-type="article"
            :item-id="slug"
          />
        </div>
      </header>

      <figure v-if="hero.sizes['16x9']" class="my-6">
        <picture>
          <source
            v-if="hero.sizes.webp"
            :srcset="hero.sizes.webp"
            type="image/webp"
          />
          <img
            :src="hero.sizes['16x9']"
            :alt="hero.alt || ''"
            width="1600"
            height="900"
            fetchpriority="high"
            class="block w-full h-auto rounded-gov"
          />
        </picture>
        <figcaption v-if="hero.caption" class="text-xs text-subtle mt-1">
          {{ hero.caption }}
        </figcaption>
      </figure>

      <div
        v-if="article.correction"
        class="border border-warn/60 bg-warn/10 rounded-gov p-3 my-4 text-sm"
        role="note"
      >
        <strong>תיקון:</strong> {{ article.correction }}
      </div>

      <ArticleBody :blocks="article.blocks" :charts="article.charts" />

      <section v-if="article.datasets.length" class="mt-10 card p-4">
        <h2 class="m-0 mb-3 text-base font-display text-subtle">
          הנתונים בכתבה
        </h2>
        <ul class="list-none m-0 p-0 space-y-2">
          <li v-for="d in article.datasets" :key="d.id">
            <!-- <a>, not NuxtLink: dataset pages are prerender-only. -->
            <a v-if="d.href" :href="d.href" class="font-medium">{{
              d.title
            }}</a>
            <span v-else>{{ d.title }}</span>
            <span v-if="d.organization" class="text-sm text-subtle">
              · {{ d.organization }}</span
            >
          </li>
        </ul>
      </section>

      <section v-if="article.sources.length" class="mt-4 text-sm text-subtle">
        <h2 class="m-0 mb-1 text-sm font-display">מקורות רשמיים</h2>
        <ul class="m-0 ps-5">
          <li v-for="s in article.sources" :key="s.url">
            <!-- Model-chosen URLs: only http(s) becomes a link, as in ArticleBody. -->
            <a
              v-if="safeHref(s.url)"
              :href="safeHref(s.url)!"
              target="_blank"
              rel="noopener"
              >{{ s.title || s.url }}</a
            >
            <span v-else>{{ s.title || s.url }}</span>
          </li>
        </ul>
      </section>

      <div v-if="article.tags.length" class="mt-6 flex flex-wrap gap-1">
        <template v-for="t in article.tags" :key="t">
          <NuxtLink
            v-if="tagSlugs[t]"
            :to="tagPath(tagSlugs[t]!)"
            class="tag-chip"
            >{{ t }}</NuxtLink
          >
          <span v-else class="tag-chip">{{ t }}</span>
        </template>
      </div>

      <div class="mt-8 pt-4 border-t border-rule flex items-center gap-3">
        <span class="text-sm text-subtle">מצאתם עניין בכתבה?</span>
        <ShareButton
          :url="url"
          :title="article.headline"
          :text="article.dek"
          content-type="article"
          :item-id="slug"
          label="שתפו את הכתבה"
          variant="ghost"
        />
      </div>
    </article>

    <section v-if="more.length" class="max-w-gov mx-auto mt-14">
      <h2 class="text-xl font-display text-ink mb-3">עוד מהחדשות</h2>
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <NewsCard v-for="a in more" :key="a.slug" :article="a" />
      </div>
    </section>
  </div>
</template>
