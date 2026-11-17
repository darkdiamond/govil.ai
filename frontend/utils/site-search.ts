// The search-as-you-type logic shared by the header popover
// (components/HeaderSearch.vue) and the homepage box (components/home/
// HomeSearch.vue), through composables/useSiteSearch.ts. Pure (no Vue, no
// Fuse import), so tests/site-search.test.mjs can run it under node. Imports
// are relative for the same reason: the test bundles this file with esbuild,
// which knows no `~/` alias.
import type FuseT from "fuse.js";
import type { SlimEntry, TagIndexEntry } from "../types/manifest";
import { PLACE_TAGS } from "./home";
import {
  normalizeSearchText,
  queryVariants,
  searchHaystack,
} from "./search-text";

/** Datasets shown per query. */
export const DATASET_LIMIT = 6;
/** Topic (tag page) suggestions shown per query. */
export const TAG_LIMIT = 3;
/** Shorter queries show the prompt, not results. */
export const MIN_QUERY_CHARS = 2;

/** Normalized copy of an entry's searchable fields (see search-text.ts). */
export interface SearchDoc {
  entry: SlimEntry;
  title: string;
  summary_he: string;
  organization: string;
  tags: string[];
  /** All of the above in one string, for the converted-query substring test. */
  hay: string;
}

export function buildSearchDocs(datasets: SlimEntry[]): SearchDoc[] {
  return datasets.map((entry) => ({
    entry,
    title: normalizeSearchText(entry.title),
    summary_he: normalizeSearchText(entry.summary_he ?? ""),
    organization: normalizeSearchText(entry.organization ?? ""),
    tags: (entry.tags ?? []).map(normalizeSearchText),
    hay: searchHaystack(entry),
  }));
}

/** Fuse options for SearchDoc (the header search's, unchanged). */
export const FUSE_OPTIONS = {
  keys: [
    { name: "title", weight: 0.5 },
    { name: "summary_he", weight: 0.25 },
    { name: "organization", weight: 0.15 },
    { name: "tags", weight: 0.2 },
  ],
  threshold: 0.4,
  distance: 100,
  includeScore: true,
  minMatchCharLength: 2,
  ignoreLocation: true,
};

export interface DatasetResults {
  items: SlimEntry[];
  /** The converted query text, when a shown result matched only through it. */
  convertedText: string | null;
  /** Some shown results also matched the query as typed. */
  rawHits: boolean;
}

export const NO_DATASETS: DatasetResults = {
  items: [],
  convertedText: null,
  rawHits: false,
};

/** Fuse search over every query variant, best score per dataset. */
export function searchDatasets(
  fuse: Pick<FuseT<SearchDoc>, "search">,
  query: string,
  limit = DATASET_LIMIT
): DatasetResults {
  const q = query.trim();
  if (q.length < MIN_QUERY_CHARS) return NO_DATASETS;
  const best = new Map<
    string,
    { entry: SlimEntry; score: number; via: string | null }
  >();
  for (const v of queryVariants(q)) {
    if (v.text.length < MIN_QUERY_CHARS) continue;
    // A re-read of the query on the other keyboard layout counts only where
    // its text literally appears (as on /datasets/), so a Hebrew word re-read
    // as Latin gibberish doesn't pull in Fuse's fuzzy noise. Filter before
    // capping: fuzzy near-misses can outrank every literal match.
    const hits = v.converted
      ? fuse.search(v.text).filter((r) => r.item.hay.includes(v.text))
      : fuse.search(v.text, { limit });
    for (const r of hits.slice(0, limit)) {
      const score = r.score ?? 1;
      const prev = best.get(r.item.entry.id);
      if (!prev || score < prev.score) {
        best.set(r.item.entry.id, {
          entry: r.item.entry,
          score,
          via: v.converted ? v.display : null,
        });
      }
    }
  }
  const top = [...best.values()]
    .sort((a, b) => a.score - b.score)
    .slice(0, limit);
  return {
    items: top.map((t) => t.entry),
    convertedText: top.find((t) => t.via)?.via ?? null,
    rawHits: top.some((t) => !t.via),
  };
}

export type TagHit = NamedHit;

/** A named page (a topic or a ministry) and how many datasets it holds. */
export interface NamedHit {
  name: string;
  slug: string;
  count: number;
}

/** Names that contain the query (or its keyboard-layout re-read): names that
 * start with it, or have a word that does, first; then the bigger page; then
 * by name. */
export function matchNames(
  items: Iterable<NamedHit>,
  query: string,
  limit: number
): NamedHit[] {
  const q = query.trim();
  if (q.length < MIN_QUERY_CHARS) return [];
  const variants = queryVariants(q).filter(
    (v) => v.text.length >= MIN_QUERY_CHARS
  );
  const hits: (NamedHit & { prefix: boolean })[] = [];
  for (const it of items) {
    const norm = normalizeSearchText(it.name);
    let prefix: boolean | null = null;
    for (const v of variants) {
      const at = norm.indexOf(v.text);
      if (at < 0) continue;
      // A match at the start of the name or of one of its words.
      const p = at === 0 || norm[at - 1] === " ";
      prefix = prefix === null ? p : prefix || p;
    }
    if (prefix === null) continue;
    hits.push({ ...it, prefix });
  }
  return hits
    .sort(
      (a, b) =>
        Number(b.prefix) - Number(a.prefix) ||
        b.count - a.count ||
        a.name.localeCompare(b.name, "he")
    )
    .slice(0, limit)
    .map(({ name, slug, count }) => ({ name, slug, count }));
}

/** Paged tags as NamedHits, count DESC. City tags included: someone who
 * types a city's name is looking for it. */
export function tagList(
  tagIndex: Record<string, TagIndexEntry> | undefined
): NamedHit[] {
  return Object.entries(tagIndex ?? {})
    .map(([name, t]) => ({ name, slug: t.slug, count: t.count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "he"));
}

/** The biggest topics, offered before anything is typed. City tags are left
 * out, as on the masthead tiles: one city is no subject for every visitor. */
export function idleTags(tags: NamedHit[], n: number): NamedHit[] {
  return tags.filter((t) => !PLACE_TAGS.has(t.name)).slice(0, n);
}

/** Tag pages matching the query (see matchNames). */
export function matchTags(
  tagIndex: Record<string, TagIndexEntry> | undefined,
  query: string,
  limit = TAG_LIMIT
): TagHit[] {
  return matchNames(tagList(tagIndex), query, limit);
}

/** Every publishing body with its dataset count, count DESC. */
export function ministryList(datasets: SlimEntry[]): NamedHit[] {
  const by = new Map<string, NamedHit>();
  for (const d of datasets) {
    if (!d.organization_slug || !d.organization) continue;
    const r = by.get(d.organization_slug);
    if (r) r.count++;
    else
      by.set(d.organization_slug, {
        name: d.organization,
        slug: d.organization_slug,
        count: 1,
      });
  }
  return [...by.values()].sort(
    (a, b) => b.count - a.count || a.name.localeCompare(b.name, "he")
  );
}

/** How many datasets /datasets/?q= will list for this query: the same test
 * it runs (any query variant as a substring of the normalized haystack). */
export function countMatches(docs: SearchDoc[], query: string): number {
  const variants = queryVariants(query.trim());
  if (!variants.length) return 0;
  let n = 0;
  for (const d of docs) if (variants.some((v) => d.hay.includes(v.text))) n++;
  return n;
}

/** Up to `max` characters of `text` around the query's first literal match,
 * cut at word boundaries with "…" where cut, so the match a preview bolds
 * is in view. No match: the start of the text. */
export function snippetAround(text: string, query: string, max = 220): string {
  const t = text.trim();
  if (t.length <= max) return t;
  // Where the first marked run starts (-1: no literal match).
  let at = -1;
  let pos = 0;
  for (const seg of highlightSegments(t, query)) {
    if (seg.match) {
      at = pos;
      break;
    }
    pos += seg.text.length;
  }
  let start = at > 0 ? Math.max(0, at - Math.floor(max / 3)) : 0;
  if (start > 0) {
    // Begin at a word: the first space after the cut, if it's before the match.
    const sp = t.indexOf(" ", start);
    start = sp >= 0 && sp < at ? sp + 1 : start;
  }
  let end = Math.min(t.length, start + max);
  if (end < t.length) {
    const sp = t.lastIndexOf(" ", end);
    if (sp > start) end = sp;
  }
  return `${start > 0 ? "…" : ""}${t.slice(start, end)}${end < t.length ? "…" : ""}`;
}

export interface Segment {
  text: string;
  match: boolean;
}

/** One character folded as normalizeSearchText folds it: separators
 * (spaces, hyphens, maqaf) to a space, niqqud and quotes to "", final letters
 * and case folded. */
function foldChar(ch: string): string {
  return /\s|[-_‐-―־]/.test(ch) ? " " : normalizeSearchText(ch);
}

/** `text` split into runs, the ones matching a query variant marked, for
 * bolding the matched part of a suggestion. Matching runs on the folded text
 * (final letters, niqqud, quotes, case: as normalizeSearchText) and maps back
 * to the original characters. A fuzzy hit with no literal match comes back as
 * one plain run. */
export function highlightSegments(text: string, query: string): Segment[] {
  const variants = queryVariants(query.trim()).filter(
    (v) => v.text.length >= MIN_QUERY_CHARS
  );
  if (!text || !variants.length) return text ? [{ text, match: false }] : [];
  // folded[i] came from original character pos[i].
  const chars = Array.from(text);
  let folded = "";
  const pos: number[] = [];
  chars.forEach((ch, i) => {
    const f = foldChar(ch);
    for (const c of f) {
      // Collapse runs of spaces, as normalizeSearchText does.
      if (c === " " && (folded === "" || folded.endsWith(" "))) continue;
      folded += c;
      pos.push(i);
    }
  });
  const marked = new Array<boolean>(chars.length).fill(false);
  for (const v of variants) {
    let from = 0;
    for (;;) {
      const at = folded.indexOf(v.text, from);
      if (at < 0) break;
      const start = pos[at]!;
      const end = pos[at + v.text.length - 1]!;
      for (let i = start; i <= end; i++) marked[i] = true;
      from = at + v.text.length;
    }
  }
  const out: Segment[] = [];
  chars.forEach((ch, i) => {
    const last = out[out.length - 1];
    if (last && last.match === marked[i]) last.text += ch;
    else out.push({ text: ch, match: marked[i]! });
  });
  return out;
}

export type SearchOption =
  | { kind: "dataset"; entry: SlimEntry }
  | { kind: "tag"; tag: NamedHit }
  | { kind: "ministry"; ministry: NamedHit };

/** One list for the arrow keys, in the order they render: topics, then
 * ministries (a short row of chips above the datasets, so it never scrolls
 * out of view), then datasets. */
export function flattenOptions(
  datasets: SlimEntry[],
  tags: NamedHit[],
  ministries: NamedHit[] = []
): SearchOption[] {
  return [
    ...tags.map((tag) => ({ kind: "tag" as const, tag })),
    ...ministries.map((ministry) => ({ kind: "ministry" as const, ministry })),
    ...datasets.map((entry) => ({ kind: "dataset" as const, entry })),
  ];
}

/** The dataset the preview card shows: the highlighted one, else (a chip or
 * nothing highlighted) the first dataset. */
export function previewEntry(
  options: SearchOption[],
  highlight: number
): SlimEntry | null {
  const h = options[highlight];
  if (h?.kind === "dataset") return h.entry;
  const first = options.find((o) => o.kind === "dataset");
  return first?.kind === "dataset" ? first.entry : null;
}

/** The sr-only live line: how many suggestions are showing. */
export function resultsAnnouncement(
  panel: string,
  datasets: number,
  tags: number,
  ministries = 0
): string {
  if (panel === "loading") return "טוען את רשימת המאגרים";
  if (panel === "empty") return "אין תוצאות";
  if (panel !== "results") return "";
  const parts: string[] = [];
  if (datasets) parts.push(datasets === 1 ? "מאגר אחד" : `${datasets} מאגרים`);
  if (tags) parts.push(tags === 1 ? "נושא אחד" : `${tags} נושאים`);
  if (ministries)
    parts.push(ministries === 1 ? "גוף אחד" : `${ministries} גופים`);
  return parts.join(", ");
}
