import { isDatasetPagePath, isSamePagePath } from "~/utils/dataset-route";

// A dataset page can only render from a document load (its fetcher reads
// node:fs; see utils/dataset-route.ts). Forward links to it are plain
// <a href>, but browser Back/Forward into a dataset entry that this document
// left by a NuxtLink is a client-side navigation, and rendered the 404 page.
// Any client-side navigation to a dataset page becomes a document load here.
export default defineNuxtRouteMiddleware((to, from) => {
  if (import.meta.server) return;
  // The initial hydration of a dataset page renders from its payload.
  if (useNuxtApp().isHydrating) return;
  if (!isDatasetPagePath(to.path) || isSamePagePath(to.path, from.path)) return;

  if (isSamePagePath(window.location.pathname, to.path)) {
    // popstate: the browser already moved to the dataset's history entry,
    // so reload that entry (not location.replace: with an unchanged #hash
    // that is a same-document jump, not a load).
    window.location.reload();
  } else {
    window.location.assign(to.fullPath);
  }
  // Leave the navigation pending until the document unloads. navigateTo's
  // external mode returns false here, and vue-router answers an aborted
  // popstate with history.go(-delta), which undoes the Back and races the
  // load.
  return new Promise<void>(() => {});
});
