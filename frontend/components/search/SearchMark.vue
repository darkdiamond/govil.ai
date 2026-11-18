<script setup lang="ts">
// Text with the parts that match the query marked: bold in a suggestion list,
// a highlighter (`variant="mark"`) in the homepage preview. One place for how
// matches look (utils/site-search.ts finds them). `active: false` prints the
// text as is (the homepage before 2 characters are typed).
import { highlightSegments } from "~/utils/site-search";

const props = withDefaults(
  defineProps<{
    text: string;
    query: string;
    active?: boolean;
    variant?: "strong" | "mark";
  }>(),
  { active: true, variant: "strong" }
);

const segments = computed(() =>
  props.active
    ? highlightSegments(props.text, props.query)
    : [{ text: props.text, match: false }]
);
</script>

<template>
  <template v-for="(s, k) in segments" :key="k"
    ><template v-if="s.match"
      ><mark v-if="variant === 'mark'" class="hl">{{ s.text }}</mark
      ><strong v-else class="font-semibold text-ink-deep">{{
        s.text
      }}</strong></template
    ><template v-else>{{ s.text }}</template></template
  >
</template>

<style scoped>
.hl {
  background: #fff3bf;
  color: inherit;
  border-radius: 0.15rem;
  padding: 0 0.1em;
}
</style>
