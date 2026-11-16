// The homepage and /tags/, as data. Pure (no Vue), so tests/home.test.mjs can
// run it under node. Everything here is computed at prerender from the slim
// search index and baked into the page payload, so keep the output small.
import type { SearchIndex, SlimEntry } from "~/types/manifest";

export const UPDATED_CAP = 8;
export const CHIPS_CAP = 8;
export const TOPIC_TAGS_CAP = 3;
export const MINISTRIES_CAP = 8;
/** The homepage lists the biggest topics; /tags/ has them all. */
export const TOPICS_CAP = 10;

export interface TagRow {
  name: string;
  slug: string;
  count: number;
}

export interface TopicGroup {
  id: string;
  label: string;
  intro: string;
  /** count DESC (tag_index order). */
  tags: TagRow[];
}

/** Paged tags grouped by topic: topics in the vocabulary's order, then the
 * tags with no (known) topic under "נושאים נוספים". Empty groups are dropped. */
export function topicGroups(
  index: Pick<SearchIndex, "tag_index" | "topics">
): TopicGroup[] {
  const groups = new Map<string, TopicGroup>(
    (index.topics ?? []).map((t) => [
      t.id,
      { id: t.id, label: t.label_he, intro: t.intro_he ?? "", tags: [] },
    ])
  );
  const other: TopicGroup = {
    id: "other",
    label: "נושאים נוספים",
    intro: "",
    tags: [],
  };
  for (const [name, t] of Object.entries(index.tag_index ?? {})) {
    const g = (t.topic && groups.get(t.topic)) || other;
    g.tags.push({ name, slug: t.slug, count: t.count });
  }
  return [...groups.values(), other].filter((g) => g.tags.length);
}

export interface UpdatedRow {
  id: string;
  page_slug?: string;
  title: string;
  organization?: string;
  last_analyzed_at: string;
}

export interface HomeTopic {
  id: string;
  label: string;
  /** Datasets carrying at least one of the topic's tags. */
  count: number;
  tags: TagRow[];
}

export interface MinistryRow {
  slug: string;
  title: string;
  count: number;
}

export interface HomeData {
  datasetCount: number;
  ministryCount: number;
  updated: UpdatedRow[];
  chips: TagRow[];
  topics: HomeTopic[];
  ministries: MinistryRow[];
}

const time = (iso?: string) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? 0 : t;
};

export function buildHome(index: SearchIndex): HomeData {
  const datasets: SlimEntry[] = index.datasets ?? [];

  // Newest render first: a page re-renders only when its data (or recipe)
  // moved, so this is "what changed lately". Ties break on id. A dataset
  // removed upstream (archived) no longer updates, so it never shows here.
  const updated = datasets
    .filter(
      (d) => time(d.last_analyzed_at) > 0 && d.source_status !== "unavailable"
    )
    .sort(
      (a, b) =>
        time(b.last_analyzed_at) - time(a.last_analyzed_at) ||
        a.id.localeCompare(b.id)
    )
    .slice(0, UPDATED_CAP)
    .map((d) => ({
      id: d.id,
      page_slug: d.page_slug,
      title: d.title,
      organization: d.organization,
      last_analyzed_at: d.last_analyzed_at!,
    }));

  const byMinistry = new Map<string, MinistryRow>();
  for (const d of datasets) {
    if (!d.organization_slug || !d.organization) continue;
    const r = byMinistry.get(d.organization_slug);
    if (r) r.count++;
    else
      byMinistry.set(d.organization_slug, {
        slug: d.organization_slug,
        title: d.organization,
        count: 1,
      });
  }
  const ministries = [...byMinistry.values()]
    .sort((a, b) => b.count - a.count || a.title.localeCompare(b.title, "he"))
    .slice(0, MINISTRIES_CAP);

  // Only tags with a page (tag_index holds exactly those), count DESC.
  const chips = Object.entries(index.tag_index ?? {})
    .map(([name, t]) => ({ name, slug: t.slug, count: t.count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "he"))
    .slice(0, CHIPS_CAP);

  // A topic's count is the datasets with any of its tags, not the sum of tag
  // counts (one dataset often carries two tags of the same topic). Biggest
  // first, capped: the full list is /tags/.
  const topics = topicGroups(index)
    .filter((g) => g.id !== "other")
    .map((g) => {
      const names = new Set(g.tags.map((t) => t.name));
      const count = datasets.filter((d) =>
        d.tags?.some((t) => names.has(t))
      ).length;
      return {
        id: g.id,
        label: g.label,
        count,
        tags: g.tags.slice(0, TOPIC_TAGS_CAP),
      };
    })
    .filter((t) => t.count > 0)
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "he"))
    .slice(0, TOPICS_CAP);

  return {
    datasetCount: datasets.length,
    ministryCount: byMinistry.size,
    updated,
    chips,
    topics,
    ministries,
  };
}
