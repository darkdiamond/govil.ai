<script setup lang="ts">
// Article blocks as Vue nodes. Nothing here is v-html: the writer's text
// arrives as runs (text / link) and renders as text nodes, so no
// model-written markup can reach the page.
import type { NewsBlock, NewsChart } from "~/types/news";
import { safeHref } from "~/utils/news";

const props = defineProps<{ blocks: NewsBlock[]; charts: NewsChart[] }>();
const chartById = computed(() =>
  Object.fromEntries(props.charts.map((c) => [c.id, c]))
);
</script>

<template>
  <div class="article-body">
    <template v-for="(b, i) in blocks" :key="i">
      <p v-if="b.type === 'p'">
        <template v-for="(r, j) in b.runs" :key="j">
          <template v-if="r.t === 'link' && safeHref(r.href)">
            <NuxtLink v-if="r.kind === 'dataset'" :to="safeHref(r.href)!">{{
              r.v
            }}</NuxtLink>
            <a
              v-else
              :href="safeHref(r.href)!"
              target="_blank"
              rel="noopener"
              >{{ r.v }}</a
            >
          </template>
          <template v-else>{{ r.v }}</template>
        </template>
      </p>
      <h2 v-else-if="b.type === 'h2'">{{ b.text }}</h2>
      <NewsChart
        v-else-if="b.type === 'chart' && chartById[b.chart]"
        :chart="chartById[b.chart]!"
      />
      <div v-else-if="b.type === 'stat'" class="news-stat">
        <div class="news-stat-value">{{ b.value }}</div>
        <div class="news-stat-label">{{ b.label }}</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.article-body p {
  font-size: 1.125rem;
  line-height: 1.75;
  margin: 0 0 1.1rem;
  color: #0c3058;
}
.article-body h2 {
  font-size: 1.35rem;
  margin: 2rem 0 0.75rem;
  color: #0b3668;
}
.article-body a {
  color: #0068f5;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.news-stat {
  border-inline-start: 4px solid #0068f5;
  padding: 0.25rem 1rem;
  margin: 1.5rem 0;
}
.news-stat-value {
  font-size: 2.5rem;
  font-weight: 600;
  color: #0b3668;
  line-height: 1.1;
}
.news-stat-label {
  color: #6c757d;
  margin-top: 0.25rem;
}
</style>
