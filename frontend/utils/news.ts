// Loaders for the news artifacts. The *Server readers run at prerender only
// (node:fs; pages/datasets/[slug].vue calls them under `import.meta.server`).
// loadNewsIndex / loadArticle are universal: pages call them from
// useAsyncData, which also runs in the browser on client-side navigation.
import type { NewsArticle, NewsIndexEntry } from "~/types/news";
import { readPublicJson } from "~/utils/search-index";

// Slugs are [a-z0-9-] (services/news/gates.slugify); refuse anything else
// before it reaches a filesystem path or a URL.
const SLUG_RE = /^[a-z0-9-]{1,120}$/;

function readJson<T>(rel: string): Promise<T | null> {
  return readPublicJson<T>(rel).catch(() => null);
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
  if (!SLUG_RE.test(slug)) return null;
  return readJson<NewsArticle>(`news/${slug}/article.json`);
}

// Universal loaders. With payloadExtraction off (nuxt.config.ts), a page's
// useAsyncData fetcher runs again in the browser on client-side navigation;
// a server-only loader returned null there and every news page reached by a
// click rendered as a 404 (2026-11-09). In the browser these fetch the same
// public JSON the prerender read from disk.
let newsIndexCache: Promise<NewsIndexEntry[]> | null = null;

export function loadNewsIndex(): Promise<NewsIndexEntry[]> {
  if (import.meta.server) return loadNewsIndexServer();
  // One fetch per browser session, as loadSearchIndex; a failure is not
  // cached (the next navigation retries) and degrades to "no news".
  newsIndexCache ??= $fetch<{ articles?: NewsIndexEntry[] }>("/news/index.json")
    .then((doc) => doc?.articles ?? [])
    .catch(() => {
      newsIndexCache = null;
      return [];
    });
  return newsIndexCache;
}

/** null = no such article (404). Any other fetch failure (offline, 5xx)
 *  throws, so the page reports an error instead of "not found". */
export async function loadArticle(slug: string): Promise<NewsArticle | null> {
  if (!SLUG_RE.test(slug)) return null;
  if (import.meta.server) return loadArticleServer(slug);
  try {
    return await $fetch<NewsArticle>(`/news/${slug}/article.json`);
  } catch (e) {
    if ((e as { statusCode?: number })?.statusCode === 404) return null;
    throw e;
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
