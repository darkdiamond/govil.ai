// Search-as-you-type state for the header popover (HeaderSearch.vue) and the
// homepage spotlight (home/HomeSearch.vue). The logic is in
// utils/site-search.ts and utils/header-search.ts (pure, node-tested); this
// wires it to Vue.
import type FuseT from "fuse.js";
import type { SlimEntry } from "~/types/manifest";
import {
  type LoadState,
  moveHighlight,
  NO_HIGHLIGHT,
  type PanelState,
  panelState,
  submitTarget,
} from "~/utils/header-search";
import { recentDatasets } from "~/utils/home";
import { datasetPath, ministryPath, tagPath } from "~/utils/paths";
import { loadSearchIndex, memoRetry } from "~/utils/search-index";
import {
  buildSearchDocs,
  countMatches,
  FUSE_OPTIONS,
  flattenOptions,
  IDLE_TAGS_WIDE,
  idleTagCount,
  idleTags,
  matchNames,
  MIN_QUERY_CHARS,
  ministryList,
  type NamedHit,
  NO_DATASETS,
  previewEntry,
  type SearchDoc,
  type SearchOption,
  searchDatasets,
  TAG_LIMIT,
  tagList,
  WIDE_QUERY,
} from "~/utils/site-search";

/** Ministry chips shown per query (homepage). */
const MINISTRY_LIMIT = 2;
/** Before anything is typed (homepage): newest renders and biggest topics. */
const IDLE_DATASETS = 6;

// Fuse.js (~24KB min+gz) and the slim search index (~60KB gz) load only when
// someone reaches for a search box, never with the page. Module-level, so the
// header popover and the homepage box share one download and one index.
// A failed load is not memoized (memoRetry), so the next try fetches again.
interface Loaded {
  fuse: FuseT<SearchDoc>;
  docs: SearchDoc[];
  tags: NamedHit[];
  idleTags: NamedHit[];
  ministries: NamedHit[];
  recent: SlimEntry[];
}
const loaded = shallowRef<Loaded | null>(null);

const ensureIndex = memoRetry((): Promise<void> =>
  Promise.all([import("fuse.js"), loadSearchIndex()]).then(
    ([{ default: Fuse }, index]) => {
      const docs = buildSearchDocs(index.datasets);
      const tags = tagList(index.tag_index);
      loaded.value = {
        fuse: new Fuse<SearchDoc>(docs, FUSE_OPTIONS),
        docs,
        tags,
        idleTags: idleTags(tags, IDLE_TAGS_WIDE),
        ministries: ministryList(index.datasets),
        recent: recentDatasets(index.datasets, IDLE_DATASETS),
      };
    }
  )
);

/** Where an option leads. Dataset pages are SSG documents that read their
 * files with node:fs in useAsyncData, which can't run in the browser (payload
 * extraction is off for the Hebrew tag routes), so they always take a full
 * page load; tag and ministry pages are ordinary routes. */
export function optionHref(o: SearchOption): string {
  if (o.kind === "dataset") return datasetPath(o.entry);
  if (o.kind === "tag") return tagPath(o.tag.slug);
  return ministryPath(o.ministry.slug);
}

export interface SiteSearchOptions {
  /** Also suggest ministries (chips beside the topics). */
  ministries?: boolean;
  /** Before 2 characters are typed, offer the newest datasets and the
   * biggest topics instead of a prompt. */
  idle?: boolean;
}

export type SpotlightPanel = PanelState | "idle";

export function useSiteSearch(idPrefix: string, opts: SiteSearchOptions = {}) {
  const router = useRouter();
  const query = ref("");
  // -1 (NO_HIGHLIGHT): Enter opens the full list; the arrows pick one option.
  const highlight = ref(NO_HIGHLIGHT);
  const loadState = ref<LoadState>(loaded.value ? "ready" : "idle");
  // How many idle topic chips fit (3 on a phone, 6 from sm up), followed
  // live. The idle panel opens only after mount, so the server's guess (wide)
  // is never rendered.
  const wide = ref(true);
  if (opts.idle && import.meta.client) {
    const mq = window.matchMedia(WIDE_QUERY);
    const sync = () => {
      wide.value = mq.matches;
    };
    sync();
    mq.addEventListener("change", sync);
    onScopeDispose(() => mq.removeEventListener("change", sync));
  }

  /** Long enough to search; shorter shows the idle lists (or the prompt). */
  const active = computed(() => query.value.trim().length >= MIN_QUERY_CHARS);

  const datasets = computed(() => {
    const l = loaded.value;
    if (!l) return NO_DATASETS;
    if (!active.value)
      return opts.idle ? { ...NO_DATASETS, items: l.recent } : NO_DATASETS;
    return searchDatasets(l.fuse, query.value);
  });
  const tags = computed(() => {
    const l = loaded.value;
    if (!l) return [];
    if (!active.value)
      return opts.idle ? l.idleTags.slice(0, idleTagCount(wide.value)) : [];
    return matchNames(l.tags, query.value, TAG_LIMIT);
  });
  const ministries = computed(() => {
    const l = loaded.value;
    if (!l || !opts.ministries || !active.value) return [];
    return matchNames(l.ministries, query.value, MINISTRY_LIMIT);
  });
  /** What /datasets/?q= will list for the query. */
  const total = computed(() =>
    loaded.value && active.value
      ? countMatches(loaded.value.docs, query.value)
      : 0
  );
  const options = computed(() =>
    flattenOptions(datasets.value.items, tags.value, ministries.value)
  );
  const panel = computed<SpotlightPanel>(() => {
    if (!active.value && opts.idle) {
      if (loadState.value === "failed") return "failed";
      return loaded.value ? "idle" : "loading";
    }
    return panelState(query.value, loadState.value, options.value.length);
  });
  const preview = computed(() => previewEntry(options.value, highlight.value));

  const listboxId = `${idPrefix}-results`;
  const optionId = (i: number) => `${idPrefix}-option-${i}`;
  const activeDescendant = computed(() =>
    highlight.value >= 0 && options.value[highlight.value]
      ? optionId(highlight.value)
      : undefined
  );

  // New results drop the highlight: Enter means "all results" until an arrow
  // key (or a pointer moving over an option) picks one.
  watch(options, () => {
    highlight.value = NO_HIGHLIGHT;
  });

  function load() {
    if (loaded.value) {
      loadState.value = "ready";
      return;
    }
    loadState.value = "loading";
    ensureIndex().then(
      () => {
        loadState.value = "ready";
      },
      () => {
        loadState.value = "failed";
      }
    );
  }

  function reset() {
    query.value = "";
    highlight.value = NO_HIGHLIGHT;
  }

  /** Follow an option. */
  function go(o: SearchOption) {
    if (o.kind === "dataset") window.location.assign(optionHref(o));
    else router.push(optionHref(o));
  }

  /** Enter: the highlighted option, else the full list for the query.
   * Returns whether it navigated (the host then closes its panel). */
  function submit(): boolean {
    const target = submitTarget(
      query.value,
      highlight.value,
      options.value.length
    );
    if (target?.kind === "hit") {
      go(options.value[target.index]!);
      return true;
    }
    if (target?.kind === "list") {
      router.push({ path: "/datasets/", query: { q: target.q } });
      return true;
    }
    return false;
  }

  /** Up/Down move the highlight. Returns true when it handled the key. */
  function onArrow(e: KeyboardEvent): boolean {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return false;
    if (!options.value.length) return false;
    e.preventDefault();
    highlight.value = moveHighlight(
      e.key,
      highlight.value,
      options.value.length
    );
    return true;
  }

  return {
    query,
    highlight,
    loadState,
    active,
    datasets,
    tags,
    ministries,
    total,
    options,
    panel,
    preview,
    listboxId,
    optionId,
    activeDescendant,
    load,
    reset,
    submit,
    onArrow,
  };
}

export type SiteSearch = ReturnType<typeof useSiteSearch>;

/** A suggestion list scrolls past its max height: keep the highlighted
 * option in view. For the panels that render useSiteSearch's options. */
export function useHighlightInView(
  highlight: () => number,
  optionId: () => (i: number) => string
) {
  watch(highlight, (h) => {
    if (h < 0) return;
    nextTick(() =>
      document
        .getElementById(optionId()(h))
        ?.scrollIntoView({ block: "nearest" })
    );
  });
}
