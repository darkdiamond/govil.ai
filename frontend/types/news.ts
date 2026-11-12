// News articles — written by services/news/publish_news.py into
// public/news/index.json and public/news/<slug>/article.json.

export interface NewsRun {
  t: "text" | "link";
  v: string;
  href?: string | null;
  kind?: "source" | "dataset";
  id?: string;
}

export type NewsBlock =
  | { type: "p"; runs: NewsRun[] }
  | { type: "h2"; text: string }
  | { type: "chart"; chart: string }
  | { type: "stat"; value: string; label: string };

export interface NewsChart {
  id: string;
  type: "line" | "bar";
  title: string;
  unit: string;
  option: Record<string, unknown>;
  table: (string | number | null)[][];
  dataset_ids: string[];
}

export interface NewsHero {
  sizes: Partial<Record<"16x9" | "4x3" | "1x1" | "webp", string>>;
  alt?: string | null;
  caption?: string | null;
  kind?: "illustration" | "chart";
}

export interface NewsDatasetCard {
  id: string;
  href: string | null;
  title?: string;
  organization?: string;
}

/** news = a fresh data move; feature = an explainer; digest = the weekly roundup. */
export type NewsKind = "news" | "feature" | "digest";

export interface NewsArticle {
  slug: string;
  status: "published" | "corrected";
  kind?: NewsKind;
  headline: string;
  dek: string;
  published_at: string;
  updated_at: string;
  byline: string;
  tags: string[];
  correction?: string | null;
  hero: NewsHero;
  blocks: NewsBlock[];
  charts: NewsChart[];
  sources: { url: string; title: string }[];
  datasets: NewsDatasetCard[];
  /** Tags that have a /tags/ page → their slug. */
  tag_slugs?: Record<string, string>;
}

export interface NewsIndexEntry {
  slug: string;
  headline: string;
  dek: string;
  published_at: string;
  updated_at: string;
  tags: string[];
  status: string;
  kind?: NewsKind;
  hero?: string | null;
  hero_alt?: string | null;
  /** 480×360 (or 4:3) image for small tiles; older index files omit it. */
  hero_thumb?: string | null;
  dataset_ids: string[];
  // Card data (services/news/publish_news.py). All optional: older index
  // files and articles without a stat block or line chart omit them.
  datasets?: { id: string; title?: string; href: string | null }[];
  topic?: { id: string; label: string } | null;
  stat?: { value: string; label: string } | null;
  spark?: number[] | null;
  minutes?: number | null;
}
