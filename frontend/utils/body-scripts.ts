// Re-running a dataset page's body scripts in the browser. Called on mount by
// pages/datasets/[slug].vue, unconditionally: Vue's hydration re-sets the
// v-html article after the browser already ran the body's inline scripts
// (CLAUDE.md, "Vue hydration force-patches v-html"), so they must run again.
import type { DatasetLibNeeds } from "~/utils/dataset-libs";

// Agent-generated content.html has inline <script> tags (ECharts, Leaflet).
// On SSR/refresh they execute natively as the browser parses the document,
// but v-html sets innerHTML, and innerHTML-inserted scripts never run — so
// on client-side navigation the charts silently fail to initialize. Rebuild
// each <script> as a real element so the browser executes it, awaiting
// external src= loads so inline init scripts see their globals. Inline
// classic scripts get wrapped in an IIFE because top-level `const`/`let`
// bind into the page's shared script-level scope, which persists across
// SPA navs and would SyntaxError on re-entry to a previously-visited page.

// <script type> values the browser executes: none/empty, "module", and the
// HTML spec's JavaScript MIME type essences. Anything else is a data block.
export const EXECUTABLE_SCRIPT_TYPES = new Set([
  "",
  "module",
  "application/ecmascript",
  "application/javascript",
  "application/x-ecmascript",
  "application/x-javascript",
  "text/ecmascript",
  "text/javascript",
  "text/javascript1.0",
  "text/javascript1.1",
  "text/javascript1.2",
  "text/javascript1.3",
  "text/javascript1.4",
  "text/javascript1.5",
  "text/jscript",
  "text/livescript",
  "text/x-ecmascript",
  "text/x-javascript",
]);

export async function executeBodyScripts(
  container: HTMLElement
): Promise<void> {
  // If any previous ECharts or Leaflet instances exist on elements in this
  // container, clean them up so re-executing scripts doesn't collide or throw.
  const w = window as unknown as {
    echarts?: {
      getInstanceByDom: (el: Element) => { dispose: () => void } | undefined;
    };
  };
  if (w.echarts?.getInstanceByDom) {
    for (const el of container.querySelectorAll("[id^=chart]")) {
      try {
        w.echarts.getInstanceByDom(el)?.dispose();
      } catch {
        // Ignore dispose errors
      }
    }
  }
  for (const el of container.querySelectorAll<HTMLElement>(
    "[id^=map], #map, .leaflet-container"
  )) {
    const raw = el as unknown as { _leaflet_id?: number | null };
    if (raw._leaflet_id) {
      raw._leaflet_id = null;
      el.innerHTML = "";
    }
  }

  const scripts = Array.from(container.querySelectorAll("script"));
  // content.html often gates init on DOMContentLoaded / window load, but those
  // events fired once on the original page load and never fire again. Intercept
  // addEventListener while our scripts run, collect handlers registered for
  // those events, and invoke them immediately after — without touching
  // listeners registered earlier (which would double-init prior visits).
  type Deferred = [EventTarget, string, EventListenerOrEventListenerObject];
  const deferred: Deferred[] = [];
  // Capture pre-bound to dodge a Window/WorkerGlobalScope overload clash:
  // the Nuxt-generated tsconfig has `lib: [..., "webworker"]`, which makes
  // unbound `addEventListener.call(window, …)` ambiguous between
  // WindowEventMap and DedicatedWorkerGlobalScopeEventMap. `.bind()` resolves
  // to a plain `(…args) => …` and side-steps the ambiguity.
  const origDocAdd = document.addEventListener.bind(document);
  const origWinAdd = window.addEventListener.bind(window);
  const docReady = () => document.readyState !== "loading";
  const winLoaded = () => document.readyState === "complete";
  document.addEventListener = function (
    type: string,
    listener: EventListenerOrEventListenerObject,
    opts?: unknown
  ) {
    if (
      listener &&
      (type === "DOMContentLoaded" || type === "readystatechange") &&
      docReady()
    ) {
      deferred.push([document, type, listener]);
      return;
    }
    return origDocAdd(
      type,
      listener as EventListener,
      opts as AddEventListenerOptions
    );
  } as typeof document.addEventListener;
  window.addEventListener = function (
    type: string,
    listener: EventListenerOrEventListenerObject,
    opts?: unknown
  ) {
    if (listener && type === "load" && winLoaded()) {
      deferred.push([window, type, listener]);
      return;
    }
    return origWinAdd(
      type,
      listener as EventListener,
      opts as AddEventListenerOptions
    );
  } as typeof window.addEventListener;
  try {
    for (const old of scripts) {
      const parent = old.parentNode;
      if (!parent) continue;
      // Data blocks (<script type="application/json"> etc.) never execute;
      // leave them in place untouched, or the IIFE wrapper below corrupts
      // the payload a body script later JSON.parse()s.
      if (!EXECUTABLE_SCRIPT_TYPES.has(old.type.trim().toLowerCase())) continue;
      // The agent contract forbids <script src=> in bodies (check.py blocks
      // it at build time). Belt: never (re-)inject a cross-origin script
      // from body content, so a body that slipped past the check can't pull
      // third-party code onto govil.ai through this path.
      const rawSrc = old.getAttribute("src");
      if (rawSrc !== null) {
        let sameOrigin = false;
        try {
          sameOrigin =
            new URL(rawSrc, location.href).origin === location.origin;
        } catch {
          sameOrigin = false;
        }
        if (!sameOrigin) {
          parent.removeChild(old);
          continue;
        }
      }
      const s = document.createElement("script");
      for (const { name, value } of Array.from(old.attributes))
        s.setAttribute(name, value);
      if (s.src) {
        await new Promise<void>((resolve) => {
          s.onload = () => resolve();
          s.onerror = () => resolve();
          parent.replaceChild(s, old);
        });
      } else {
        const source = old.textContent ?? "";
        s.text = s.type === "module" ? source : `(()=>{\n${source}\n})();`;
        parent.replaceChild(s, old);
      }
    }
  } finally {
    document.addEventListener = origDocAdd;
    window.addEventListener = origWinAdd;
  }
  for (const [target, type, listener] of deferred) {
    try {
      const ev = new Event(type);
      if (typeof listener === "function") listener.call(target, ev);
      else listener.handleEvent(ev);
    } catch (err) {
      console.error("[dataset body] deferred listener failed", err);
    }
  }
}

// Wait for conditional head libs before running body scripts. On SSR/SSG
// load they are synchronous in <head> and resolve immediately; on SPA nav
// useHead appends them dynamically, so we poll until window.* globals are set.
export async function awaitDatasetLibs(
  needs: DatasetLibNeeds,
  timeoutMs = 5000
): Promise<void> {
  if (!needs.charts && !needs.map && !needs.explorer) return;
  const start = Date.now();
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const w = window as unknown as {
      L?: { markerClusterGroup?: unknown };
      echarts?: unknown;
      GovEcharts?: { option?: unknown };
      GovExplorer?: { create?: unknown };
      GovMap?: { create?: unknown };
    };
    const ready =
      (!needs.charts ||
        (typeof w.echarts !== "undefined" &&
          typeof w.GovEcharts?.option === "function")) &&
      (!needs.map ||
        (typeof w.L?.markerClusterGroup === "function" &&
          typeof w.GovMap?.create === "function")) &&
      (!needs.explorer || typeof w.GovExplorer?.create === "function");
    if (ready) return;
    if (Date.now() - start > timeoutMs) {
      console.warn(
        "[dataset libs] timed out waiting for this page's viz globals after SPA nav",
        needs
      );
      return;
    }
    await new Promise((r) => setTimeout(r, 30));
  }
}
