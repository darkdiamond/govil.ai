// The /news/ front page, as data: which story goes in which section. Pure (no
// Vue), so tests/news-front.test.mjs can run it under node.
//
// Order of the page: the edition (the newest stories), the weekly digest band,
// news from the data, data analyses, topic desks, then the archive. A story
// appears once above the archive, and the archive holds what the front didn't
// show. A section too small to read as one hands its stories to the archive.
import type { NewsIndexEntry } from "~/types/news";

export const EDITION_SIZE = 4;
export const NEWS_CAP = 6;
export const ANALYSES_CAP = 4;
export const SECTION_MIN = 2;
export const DESK_MIN = 3;
export const DESK_CAP = 4;
export const DESKS_MAX = 4;
/** A digest leaves the band once it is this much older than the newest story. */
export const DIGEST_FRESH_DAYS = 8;

export interface Desk {
  topic: { id: string; label: string };
  items: NewsIndexEntry[];
}

export interface FrontPage {
  lead: NewsIndexEntry | null;
  side: NewsIndexEntry[];
  digest: NewsIndexEntry | null;
  news: NewsIndexEntry[];
  analyses: NewsIndexEntry[];
  desks: Desk[];
  archive: NewsIndexEntry[];
}

const TZ = "Asia/Jerusalem";

const dated = (a: NewsIndexEntry) =>
  !Number.isNaN(new Date(a.published_at).getTime());

/** Older articles have no kind: they are news. */
const kindOf = (a: NewsIndexEntry) => a.kind ?? "news";

export function buildFront(articles: NewsIndexEntry[]): FrontPage {
  const used = new Set<string>();
  const take = (items: NewsIndexEntry[]) => {
    for (const a of items) used.add(a.slug);
    return items;
  };
  // Undated stories (a malformed date) only reach the archive.
  const pool = () => articles.filter((a) => dated(a) && !used.has(a.slug));
  const section = (items: NewsIndexEntry[], min: number) =>
    items.length >= min ? take(items) : [];

  // The digest has its own band, so the edition skips it. Measured against
  // the newest story, not the clock, so the prerender is deterministic.
  const newest = pool()[0];
  const fresh = (a: NewsIndexEntry) =>
    !!newest &&
    Date.parse(newest.published_at) - Date.parse(a.published_at) <=
      DIGEST_FRESH_DAYS * 86_400_000;
  const digest = pool().find((a) => kindOf(a) === "digest" && fresh(a)) ?? null;
  if (digest) take([digest]);
  const edition = take(pool().slice(0, EDITION_SIZE));
  // News fills rows of three cards; two stories (too few for a row) show
  // as wide tiles instead.
  const newsPool = pool()
    .filter((a) => kindOf(a) === "news")
    .slice(0, NEWS_CAP);
  const news = section(
    newsPool.length >= 3
      ? newsPool.slice(0, newsPool.length - (newsPool.length % 3))
      : newsPool,
    SECTION_MIN
  );
  const analyses = section(
    pool()
      .filter((a) => kindOf(a) === "feature")
      .slice(0, ANALYSES_CAP),
    SECTION_MIN
  );

  const byTopic = new Map<string, Desk>();
  for (const a of pool()) {
    if (!a.topic) continue;
    const d = byTopic.get(a.topic.id) ?? { topic: a.topic, items: [] };
    d.items.push(a);
    byTopic.set(a.topic.id, d);
  }
  const desks = [...byTopic.values()]
    .filter((d) => d.items.length >= DESK_MIN)
    .sort(
      (x, y) =>
        y.items.length - x.items.length ||
        x.topic.label.localeCompare(y.topic.label, "he")
    )
    .slice(0, DESKS_MAX)
    .map((d) => ({ topic: d.topic, items: take(d.items.slice(0, DESK_CAP)) }));

  return {
    lead: edition[0] ?? null,
    side: edition.slice(1),
    digest,
    news,
    analyses,
    desks,
    archive: articles.filter((a) => !used.has(a.slug)),
  };
}

/** The small image for a tile: the publisher's thumb, else the full hero. */
export const thumbOf = (a: NewsIndexEntry) => a.hero_thumb || a.hero || null;

// ── dates ───────────────────────────────────────────────────────────────

const DAY_KEY = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: TZ,
});
const EDITION_DATE = new Intl.DateTimeFormat("he-IL", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: TZ,
});

/** YYYY-MM-DD in Israel time, "" for an invalid date. */
export function ilDateKey(iso: string | Date): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : DAY_KEY.format(d);
}

/** The edition line: the lead's Israel date, and whether that is today.
 *  `now` is passed in: the page computes it after mount, so the prerender
 *  never freezes "today" into the HTML. */
export function editionLine(
  leadIso: string | undefined,
  now: Date | null
): { date: string; today: boolean } | null {
  if (!leadIso) return null;
  const d = new Date(leadIso);
  if (Number.isNaN(d.getTime())) return null;
  return {
    date: EDITION_DATE.format(d),
    today: now !== null && ilDateKey(d) === ilDateKey(now),
  };
}

const MONTH_KEY = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  timeZone: TZ,
});
const MONTH_LABEL = new Intl.DateTimeFormat("he-IL", {
  month: "long",
  year: "numeric",
  timeZone: TZ,
});

// "" = undated. Only a real YYYY-MM is formatted: Intl throws a RangeError on
// an invalid Date, and ?month= comes from the URL.
export const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
export const monthKey = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : MONTH_KEY.format(d).slice(0, 7);
};
export const monthLabel = (key: string) =>
  MONTH_RE.test(key)
    ? MONTH_LABEL.format(new Date(`${key}-15T12:00:00Z`))
    : "ללא תאריך";
