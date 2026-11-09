<script setup lang="ts">
// A tiny line of the story's series (index.json `spark`, publish_news._spark).
// Decorative: the number next to it carries the meaning, so aria-hidden.
const props = withDefaults(
  defineProps<{ values: number[]; width?: number; height?: number }>(),
  { width: 96, height: 28 }
);

const PAD = 3;
const geom = computed(() => {
  const v = props.values.filter((x) => Number.isFinite(x));
  if (v.length < 2) return null;
  const min = Math.min(...v);
  const max = Math.max(...v);
  const span = max - min || 1;
  const w = props.width - PAD * 2;
  const h = props.height - PAD * 2;
  // Time runs left to right even on an RTL page, like every chart on the site.
  const pts = v.map((y, i) => [
    PAD + (i / (v.length - 1)) * w,
    PAD + h - ((y - min) / span) * h,
  ]);
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [lx, ly] = pts[pts.length - 1];
  const area = `${PAD},${PAD + h} ${line} ${lx.toFixed(1)},${PAD + h}`;
  return { line, area, lx, ly };
});
</script>

<template>
  <svg
    v-if="geom"
    :width="width"
    :height="height"
    :viewBox="`0 0 ${width} ${height}`"
    aria-hidden="true"
    focusable="false"
    class="block shrink-0 overflow-visible"
  >
    <polygon :points="geom.area" fill="#0068f5" fill-opacity="0.08" />
    <polyline
      :points="geom.line"
      fill="none"
      stroke="#0068f5"
      stroke-width="1.5"
      stroke-linejoin="round"
      stroke-linecap="round"
    />
    <circle :cx="geom.lx" :cy="geom.ly" r="2.5" fill="#0b3668" />
  </svg>
</template>
