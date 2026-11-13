// The error a hub page (tag, ministry, kind, news article) throws after its
// useAsyncData fetch, kept out of the SFCs so node --test can reach it
// (tests/hub-page.test.mjs).

export interface HubPageError {
  statusCode: 503 | 404;
  statusMessage: string;
}

/** A failed fetch (offline, 5xx on client-side navigation) is 503, not 404:
 *  the page exists, its data didn't arrive. Nothing found is 404. */
export function hubPageError(
  error: unknown,
  found: boolean,
  what: string
): HubPageError | null {
  if (error) return { statusCode: 503, statusMessage: `${what} unavailable` };
  if (!found) return { statusCode: 404, statusMessage: `${what} not found` };
  return null;
}
