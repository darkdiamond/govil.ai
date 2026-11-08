// Curated viz libraries pre-loaded in <head> on dataset pages — but only
// the ones a page's agent body actually references. Files come from
// public/lib/, populated by scripts/copy-libs.mjs (keep the list there in
// sync). Agent-emitted content.html may NOT include <script src=> or
// <link rel=stylesheet> — these tags are the only external resources a
// dataset page loads.

export interface DatasetLibNeeds {
  charts: boolean;
  map: boolean;
  explorer: boolean;
}

// Detection runs server-side at prerender on the RAW body (pre-
// normalizeAgentBody) and is deliberately generous: a body cannot call a
// global without containing its identifier, so false negatives are
// implausible under the agent contract; a false positive just reproduces
// the old load-everything behavior for that page.
//   charts   → echarts + the gov-echarts wrapper
//   map      → Leaflet + MarkerCluster (+CSS) + the gov-map wrapper
//   explorer → legacy GovExplorer shim. Modern pages use the Vue
//              DatasetExplorer component instead, but ~350 published
//              bodies still call GovExplorer.create() inline — removing
//              the global there would throw and kill any chart init in
//              the same script block.
export function detectDatasetLibs(rawBody: string): DatasetLibNeeds {
  return {
    charts: /echarts|GovEcharts|GOVIL_PALETTE|id="chart/i.test(rawBody),
    map: /\bGovMap\b|\bL\.[a-zA-Z]+\(|leaflet|id="map/i.test(rawBody),
    explorer: /\bGovExplorer\b/.test(rawBody),
  };
}

export function buildDatasetLibTags(needs: DatasetLibNeeds): {
  link: { rel: "stylesheet"; href: string }[];
  script: { src: string }[];
} {
  const link = needs.map
    ? [
        { rel: "stylesheet" as const, href: "/lib/leaflet.css" },
        { rel: "stylesheet" as const, href: "/lib/MarkerCluster.css" },
        { rel: "stylesheet" as const, href: "/lib/MarkerCluster.Default.css" },
      ]
    : [];
  // Order matters: Leaflet -> MarkerCluster (mutates L) -> ECharts.
  // Plain <script> tags (no defer/async): head-blocking so window.L /
  // window.echarts / window.GovExplorer exist before the body's inline
  // init runs during initial parse. On SPA nav useHead appends the same
  // tags to <head>; executeBodyScripts() in pages/datasets/[slug].vue
  // waits on the page's needed globals before re-running body scripts.
  //
  // Hand-written browser libs (sourced from frontend/scripts/, copied
  // into public/lib/ by scripts/copy-libs.mjs):
  //   gov-echarts.js   → window.GOVIL_PALETTE + window.GovEcharts.{base,option}
  //   gov-explorer.js  → window.GovExplorer.create (legacy bodies only)
  //   gov-map.js       → window.GovMap.create
  const script = [
    ...(needs.map
      ? [{ src: "/lib/leaflet.js" }, { src: "/lib/leaflet.markercluster.js" }]
      : []),
    ...(needs.charts
      ? [{ src: "/lib/echarts.min.js" }, { src: "/lib/gov-echarts.js" }]
      : []),
    ...(needs.explorer ? [{ src: "/lib/gov-explorer.js" }] : []),
    ...(needs.map ? [{ src: "/lib/gov-map.js" }] : []),
  ];
  return { link, script };
}
