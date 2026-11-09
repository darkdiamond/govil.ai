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

export interface NewsArticle {
  slug: string;
  status: "published" | "corrected";
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
}

export interface NewsIndexEntry {
  slug: string;
  headline: string;
  dek: string;
  published_at: string;
  updated_at: string;
  tags: string[];
  status: string;
  hero?: string | null;
  hero_alt?: string | null;
  dataset_ids: string[];
}
