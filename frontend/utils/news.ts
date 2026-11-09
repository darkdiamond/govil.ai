// Server-only readers for the news artifacts (prerender time). Pages call
// them inside `if (import.meta.server)` so node:fs never reaches the client
// bundle; the result is inlined into the page payload.
import type { NewsArticle, NewsIndexEntry } from "~/types/news";

async function readJson<T>(rel: string): Promise<T | null> {
  const fs = await import("node:fs/promises");
  const path = await import("node:path");
  try {
    return JSON.parse(
      await fs.readFile(path.resolve(process.cwd(), "public", rel), "utf-8")
    ) as T;
  } catch {
    return null;
  }
}

export async function loadNewsIndexServer(): Promise<NewsIndexEntry[]> {
  const doc = await readJson<{ articles?: NewsIndexEntry[] }>(
    "news/index.json"
  );
  return doc?.articles ?? [];
}

export async function loadArticleServer(
  slug: string
): Promise<NewsArticle | null> {
  // Slugs are [a-z0-9-] (services/news/gates.slugify); refuse anything else
  // before it reaches a filesystem path.
  if (!/^[a-z0-9-]{1,120}$/.test(slug)) return null;
  return readJson<NewsArticle>(`news/${slug}/article.json`);
}

// Universal loaders. With payloadExtraction off (nuxt.config.ts), a page's
// useAsyncData fetcher runs again in the browser on client-side navigation;
// a server-only loader returned null there and every news page reached by a
// click rendered as a 404 (2026-11-09). In the browser these fetch the same
// public JSON the prerender read from disk.
export async function loadNewsIndex(): Promise<NewsIndexEntry[]> {
  if (import.meta.server) return loadNewsIndexServer();
  try {
    const doc = await $fetch<{ articles?: NewsIndexEntry[] }>(
      "/news/index.json"
    );
    return doc?.articles ?? [];
  } catch {
    return [];
  }
}

export async function loadArticle(slug: string): Promise<NewsArticle | null> {
  if (import.meta.server) return loadArticleServer(slug);
  if (!/^[a-z0-9-]{1,120}$/.test(slug)) return null;
  try {
    return await $fetch<NewsArticle>(`/news/${slug}/article.json`);
  } catch {
    return null;
  }
}

const HE_DATE = new Intl.DateTimeFormat("he-IL", {
  dateStyle: "long",
  timeZone: "Asia/Jerusalem",
});
const HE_DATE_TIME = new Intl.DateTimeFormat("he-IL", {
  dateStyle: "long",
  timeStyle: "short",
  timeZone: "Asia/Jerusalem",
});

export function newsDate(iso?: string | null, withTime = false): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return (withTime ? HE_DATE_TIME : HE_DATE).format(d);
}

// Only http(s) links reach an href (defense in depth: the writer's gate and
// the publisher already allow only official https pages and our own paths).
export function safeHref(href?: string | null): string | null {
  if (!href) return null;
  if (href.startsWith("/") && !href.startsWith("//")) return href;
  try {
    const u = new URL(href);
    return u.protocol === "https:" || u.protocol === "http:"
      ? u.toString()
      : null;
  } catch {
    return null;
  }
}
