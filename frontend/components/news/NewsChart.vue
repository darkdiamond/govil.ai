<script setup lang="ts">
// One article chart. The option comes from services/news/charts.py (data
// filled from our datasets, never from the model); styling comes from the
// shared GovEcharts preset (palette, Rubik, RTL tooltip), preloaded in
// <head> by pages/news/[slug].vue.
import type { NewsChart } from "~/types/news";

const props = defineProps<{ chart: NewsChart }>();
const el = ref<HTMLElement | null>(null);
let inst: {
  setOption: (o: unknown) => void;
  resize: () => void;
  dispose: () => void;
} | null = null;
let ro: ResizeObserver | null = null;

type EchartsWindow = Window & {
  echarts?: {
    init: (el: HTMLElement, theme?: unknown, opts?: unknown) => typeof inst;
  };
  GovEcharts?: { option: (o: unknown) => unknown };
};

async function libs(timeoutMs = 6000): Promise<EchartsWindow | null> {
  const start = Date.now();
  const w = window as EchartsWindow;
  while (!(w.echarts && w.GovEcharts?.option)) {
    if (Date.now() - start > timeoutMs) return null;
    await new Promise((r) => setTimeout(r, 30));
  }
  return w;
}

onMounted(async () => {
  const w = await libs();
  if (!w || !el.value) return;
  // Canvas, as on recipe pages: the SVG renderer inherits the page's dir="rtl",
  // which draws legend labels back over their markers.
  inst = w.echarts!.init(el.value);
  inst!.setOption(w.GovEcharts!.option(props.chart.option));
  ro = new ResizeObserver(() => inst?.resize());
  ro.observe(el.value);
});

onBeforeUnmount(() => {
  ro?.disconnect();
  inst?.dispose();
});

const header = computed(() => props.chart.table[0] ?? []);
const rows = computed(() => props.chart.table.slice(1));
function cell(v: string | number | null): string {
  if (v == null) return "";
  return typeof v === "number"
    ? v.toLocaleString("he-IL", { maximumFractionDigits: 2 })
    : v;
}
</script>

<template>
  <figure class="news-chart my-8">
    <figcaption class="font-display text-base text-ink mb-2">
      {{ chart.title }}
      <span v-if="chart.unit" class="text-subtle text-sm font-sans"
        >({{ chart.unit }})</span
      >
    </figcaption>
    <div
      ref="el"
      class="w-full h-[280px] sm:h-[360px]"
      role="img"
      :aria-label="chart.title"
    />
    <details class="mt-2 text-sm text-subtle">
      <summary class="cursor-pointer">הנתונים בטבלה</summary>
      <div class="overflow-x-auto max-h-80 mt-2">
        <table class="w-full text-sm">
          <thead>
            <tr>
              <th
                v-for="(h, i) in header"
                :key="i"
                class="text-start font-medium px-2 py-1"
              >
                {{ h }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in rows" :key="i" class="border-t border-rule">
              <td v-for="(c, j) in r" :key="j" class="px-2 py-1 tabular-nums">
                {{ cell(c) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  </figure>
</template>
