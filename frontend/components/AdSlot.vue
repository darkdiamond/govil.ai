<script setup lang="ts">
// Manual AdSense display slot ("govil-ai-responsive"). The adsbygoogle.js
// loader itself is injected post-hydration by plugins/adsense.client.ts
// (Auto Ads) — this component only renders the <ins> markup and queues a
// fill request. Rendering is gated on NUXT_PUBLIC_ADSENSE_ID so local/fork
// builds ship no ad markup at all, matching the site's opt-in-ads rule
// (see nuxt.config.ts).
const adsenseId = useRuntimeConfig().public.adsenseId as string

// Push AFTER mount: the <ins> must already be in the DOM, and the
// (window.adsbygoogle = …)[] queue is drained by the library whenever it
// finishes loading — so ordering against the app:mounted script injection
// in plugins/adsense.client.ts doesn't matter. Queuing here (post-hydration,
// per component instance) is what keeps Auto Ads' DOM mutations from racing
// Vue — the exact mismatch the loader plugin defers to avoid.
onMounted(() => {
  if (!adsenseId) return
  const w = window as unknown as { adsbygoogle?: unknown[] }
  ;(w.adsbygoogle = w.adsbygoogle || []).push({})
})
</script>

<template>
  <div v-if="adsenseId" class="ad-slot my-6 md:my-8">
    <ins
      class="adsbygoogle"
      style="display: block"
      :data-ad-client="adsenseId"
      data-ad-slot="5838563269"
      data-ad-format="auto"
      data-full-width-responsive="true"
    />
  </div>
</template>
