<script setup lang="ts">
import { loadSearchIndex } from "~/utils/search-index";
import { useKindLabels } from "~/composables/useKindLabels";
import hubIntros from "~/content/hub-intros.json";
import type { DatasetKind } from "~/types/manifest";

// Index of the /kinds/<kind>/ hubs, so a visitor who trims a kind URL
// lands on a page instead of the 404.

useSeo({
  title: "מאגרי מידע לפי סוג — מפות, סדרות זמן, רשימות ודירוגים",
  description:
    "מאגרי המידע הציבוריים מחולקים לפי אופי הנתונים: מפות, סדרות זמן, רשימות ישויות ודירוגים. בחרו סוג כדי לראות את כל המאגרים שלו.",
  path: "/kinds/",
  breadcrumbs: [
    { name: "ראשי", url: "https://govil.ai/" },
    { name: "סוגי מידע", url: "https://govil.ai/kinds/" },
  ],
});

const { KIND_INFO, KIND_ORDER } = useKindLabels();
const intros = hubIntros.kinds as Record<string, string>;

// Bake only the per-kind counts into the payload, not the index itself.
const { data } = await useAsyncData("kinds-index", async () => {
  const index = await loadSearchIndex();
  const counts: Partial<Record<DatasetKind, number>> = {};
  for (const d of index.datasets) {
    const k = d.dataset_kind;
    if (k && k in KIND_INFO) counts[k] = (counts[k] ?? 0) + 1;
  }
  return counts;
});

// Same set [kind].vue renders: a kind with no datasets has no page.
const kinds = computed(() =>
  KIND_ORDER.map((k) => ({
    kind: k,
    info: KIND_INFO[k],
    count: data.value?.[k] ?? 0,
    intro: intros[k] ?? "",
  })).filter((t) => t.count > 0)
);
</script>

<template>
  <div class="max-w-gov mx-auto px-4 py-8">
    <section class="mb-6">
      <div class="text-xs text-subtle mb-2">
        <NuxtLink to="/">ראשי</NuxtLink> › סוגי מידע
      </div>
      <h1 class="font-display">מאגרים לפי סוג מידע</h1>
      <p class="text-subtle mt-2 max-w-2xl">
        כל מאגר מסווג לפי אופי הנתונים שבו, והדף שלו בנוי בהתאם.
      </p>
    </section>

    <section class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <NuxtLink
        v-for="t in kinds"
        :key="t.kind"
        :to="`/kinds/${t.kind}/`"
        :aria-label="`${t.info.label}, ${t.count} מאגרים`"
        class="card card-hover p-4 no-underline hover:no-underline flex items-start gap-3"
      >
        <img :src="t.info.icon" alt="" class="w-6 h-6 mt-0.5 opacity-75" />
        <div>
          <div class="font-display text-ink">{{ t.info.label }}</div>
          <div class="text-xs text-subtle mt-1">{{ t.count }} מאגרים</div>
          <p
            v-if="t.intro"
            class="text-sm text-ink/85 leading-relaxed mt-2 mb-0"
          >
            {{ t.intro }}
          </p>
        </div>
      </NuxtLink>
    </section>
  </div>
</template>
