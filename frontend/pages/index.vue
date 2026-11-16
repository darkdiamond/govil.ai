<script setup lang="ts">
import { buildHome } from "~/utils/home";
import { buildFront } from "~/utils/news-front";
import { loadSearchIndex } from "~/utils/search-index";

useSeo({
  title:
    "מאגרי המידע הממשלתיים של ישראל: מוסברים, מחוברים ומתעדכנים · govil.ai",
  description:
    "כל מאגר מידע ממשלתי מוסבר בעמוד אחד: תקציר, גרפים ומפות שמתעדכנים מהנתונים הרשמיים, וחדשות מהנתונים. בלי הורדות ובלי Excel.",
  path: "/",
  keywords: [
    "מאגרי מידע ממשלתיים",
    "מידע ממשלתי פתוח",
    "נתונים פתוחים",
    "open data Israel",
  ],
});

// Both fetchers run at prerender and bake only what the page renders into the
// payload (the full search index and news index never ship from here). With
// payloadExtraction off, a client-side navigation re-runs them in the browser.
const { data: home } = await useAsyncData("home", async () =>
  buildHome(await loadSearchIndex())
);

// The same front /news/ builds: its newest stories and this week's digest.
const { data: news } = await useAsyncData("home-news", async () => {
  const { loadNewsIndex } = await import("~/utils/news");
  const front = buildFront(await loadNewsIndex());
  return {
    lead: front.lead,
    side: front.side.slice(0, 4),
    digest: front.digest,
  };
});
</script>

<template>
  <div class="max-w-gov mx-auto px-4 pb-12">
    <Masthead
      :dataset-count="home?.datasetCount ?? 0"
      :ministry-count="home?.ministryCount ?? 0"
      :chips="home?.chips ?? []"
    />

    <section v-if="news?.lead" aria-labelledby="home-news-h" class="mt-8">
      <!-- Same section head as the blocks below: title over a rule. -->
      <div
        class="flex items-baseline justify-between gap-4 pb-2 mb-5 border-b-2 border-ink-deep"
      >
        <h2 id="home-news-h" class="m-0 text-2xl font-display text-ink-deep">
          חדשות
        </h2>
        <NuxtLink to="/news/" class="text-sm shrink-0">לכל החדשות</NuxtLink>
      </div>
      <NewsEdition :lead="news.lead" :side="news.side" show-source />
    </section>

    <div class="mt-14 grid gap-x-12 gap-y-14 lg:grid-cols-2">
      <RecentlyUpdated :rows="home?.updated ?? []" />
      <BrowseTopics
        :topics="home?.topics ?? []"
        :ministries="home?.ministries ?? []"
      />
    </div>

    <section v-if="news?.digest" aria-labelledby="home-digest-h" class="mt-14">
      <h2 id="home-digest-h" class="sr-only">הסיכום השבועי</h2>
      <NewsDigestBand :article="news.digest" />
    </section>

    <AboutStrip class="mt-14" />
  </div>
</template>
