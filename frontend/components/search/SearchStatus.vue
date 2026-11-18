<script setup lang="ts">
// The search panels' loading and failed lines (home/HomeSpotlight.vue,
// SearchSuggestions.vue). `pad` is the padding, which differs per panel.
defineProps<{
  state: "loading" | "failed";
  pad: string;
}>();

const emit = defineEmits<{ retry: [] }>();
</script>

<template>
  <div
    v-if="state === 'loading'"
    class="text-sm text-subtle text-center"
    :class="pad"
  >
    טוען את רשימת המאגרים…
  </div>
  <div v-else class="text-sm text-subtle text-center" :class="pad" role="alert">
    טעינת החיפוש נכשלה.
    <button
      type="button"
      class="text-brand-700 hover:underline bg-transparent border-0 p-0 cursor-pointer"
      @click="emit('retry')"
    >
      נסו שוב
    </button>
  </div>
</template>
