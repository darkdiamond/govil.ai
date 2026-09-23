// Normalizes agent-authored content.html before it hits v-html in
// pages/datasets/[slug].vue. Single ingress point so every dataset page
// gets the same defenses regardless of which day the agent ran.
//
// Five transforms:
//   1. e.data.gov.il / aws-e.data.gov.il (OAuth-gated) -> data.gov.il
//      (public CKAN host).
//   2. Backslash-escaped script-end tag -> real script-end tag. HTML5 only
//      recognizes the unescaped form; a single backslash form inside an
//      external script tag silently swallows everything until the next
//      real end tag, hiding the init code from the parser.
//   3. Drop duplicate viz-lib script and stylesheet tags. The page shell
//      already preloads Leaflet + MarkerCluster + ECharts via
//      useHead(DATASET_LIB_TAGS) from /lib/ on the same origin; the
//      agent occasionally re-includes the same libs from public CDNs
//      with stale SRI hashes, which fails integrity and noises up the
//      console.
//   4. Strip the legacy tag-chip row that older agent runs emit just
//      under the H1. The chip taxonomy moved to AgentData.suggested_tags;
//      the shell now injects the row from there as <a> links.
//   5. Inject the new chip row from `opts.titleChips` immediately after
//      the first <h1>. Each chip is a real <a href="/tags/<slug>/">
//      so it ships in the static HTML (works without JS, indexes for SEO).
//   6. Strip agent-built GovExplorer sections. The shell now owns the
//      data explorer (components/DatasetExplorer.vue, server-side search
//      over the full resource); legacy pages baked a client-side-search
//      section into content.html. The GovExplorer.create() calls inside
//      larger inline scripts are left alone — create() silently no-ops
//      when its container is missing.

const ESCAPED_SCRIPT_END = /<\\\/script>/g;
const IAP_HOST = /https:\/\/(?:aws-)?e\.data\.gov\.il/g;

const LIB_SCRIPT_RE = new RegExp(
  "<script\\b[^>]*\\bsrc=[\"\\'][^\"\\']*" +
    "(?:leaflet[^\"\\']*\\.js|MarkerCluster[^\"\\']*\\.js|echarts[^\"\\']*\\.js)" +
    "[\"\\'][^>]*>\\s*<\\\\?\\/script>",
  "gi"
);

const LIB_STYLE_RE = new RegExp(
  "<link\\b[^>]*\\bhref=[\"\\'][^\"\\']*" +
    "(?:leaflet[^\"\\']*\\.css|MarkerCluster[^\"\\']*\\.css)" +
    "[\"\\'][^>]*\\/?>",
  "gi"
);

// A wrapper <div> whose children are exclusively `<span class="tag-chip">`
// nodes (and whitespace). Structural — agnostic to the wrapper's
// attributes — because a few legacy pages used inline `style="display:flex"`
// instead of Tailwind utilities, and the `class="flex flex-wrap …"` family
// itself varies (gap-2/4/5/6, optional `mb-N`).
const LEGACY_CHIP_BLOCK_RE =
  /<div\b[^>]*>\s*(?:<span\s+class="tag-chip"\s*>[^<]*<\/span>\s*)+<\/div>/g;

const FIRST_H1_RE = /<h1\b[^>]*>[\s\S]*?<\/h1>/;

// Any flat <section> whose contents include id="explorer…" — covers
// id="explorer", id="explorer-search", and the multi-explorer variants
// (id="explorer-companies" etc.). The tempered token (?:(?!<\/?section\b)…)
// forbids crossing a nested <section> boundary, so only the innermost
// section is eaten; explorer sections in the published corpus are flat.
const EXPLORER_SECTION_RE =
  /<section\b[^>]*>(?:(?!<\/?section\b)[\s\S])*?\bid="explorer[^"]*"(?:(?!<\/?section\b)[\s\S])*?<\/section>\s*/g;

const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]!);
}

export interface TitleChip {
  label: string;
  href: string;
}

export interface NormalizeOptions {
  titleChips?: TitleChip[];
}

function buildChipRow(chips: TitleChip[]): string {
  const parts = chips.map(
    (c) =>
      `<a href="${escapeHtml(c.href)}" class="tag-chip hover:bg-brand-100 no-underline hover:no-underline">${escapeHtml(c.label)}</a>`
  );
  return `<div class="flex flex-wrap gap-2 mb-6">${parts.join("")}</div>`;
}

export function normalizeAgentBody(
  raw: string,
  opts: NormalizeOptions = {}
): string {
  let out = raw
    .replace(IAP_HOST, "https://data.gov.il")
    .replace(ESCAPED_SCRIPT_END, "</" + "script>")
    .replace(LIB_SCRIPT_RE, "")
    .replace(LIB_STYLE_RE, "")
    .replace(LEGACY_CHIP_BLOCK_RE, "")
    .replace(EXPLORER_SECTION_RE, "");

  const chips = opts.titleChips ?? [];
  if (chips.length > 0) {
    const chipRow = buildChipRow(chips);
    out = out.replace(FIRST_H1_RE, (h1) => `${h1}\n${chipRow}`);
  }

  return out;
}
