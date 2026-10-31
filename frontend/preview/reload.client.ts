// Local recipe preview only (`python -m services.page_builder.cli.preview`):
// mark the page as a preview and reload it whenever the CLI re-renders a
// recipe (it bumps the stamp served at /__preview/stamp). Registered by
// nuxt.config.ts only when NUXT_PREVIEW_ROOT is set; no build ships it.
export default defineNuxtPlugin(() => {
  const badge = document.createElement("div");
  badge.textContent = "תצוגה מקדימה מקומית";
  badge.setAttribute(
    "style",
    "position:fixed;bottom:12px;inset-inline-start:12px;z-index:99999;" +
      "background:#0c3058;color:#fff;font:500 12px/1.5 Rubik,system-ui,sans-serif;" +
      "padding:4px 10px;border-radius:50rem;opacity:.85;pointer-events:none"
  );
  document.body.appendChild(badge);

  let last: string | null = null;
  const poll = async () => {
    try {
      const stamp = await (
        await fetch("/__preview/stamp", { cache: "no-store" })
      ).text();
      if (last !== null && stamp !== last) location.reload();
      last = stamp;
    } catch {
      // server restarting; keep polling
    }
  };
  poll();
  setInterval(poll, 1000);
});
