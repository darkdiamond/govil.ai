// How DatasetExplorer reads a failed datastore_search call. Only a definite
// answer from CKAN may remove a tab for the session; a hiccup on the way
// (data.gov.il timing out or erroring under load) gets an error with a retry.
//   gone      — 403: the source was made private or removed upstream.
//   absent    — CKAN answered that there is no such table: 404, another
//               non-retryable 4xx (CKAN's success:false error replies), or
//               a 200 carrying success:false.
//   transient — anything else: network error, timeout, a non-JSON reply
//               (WAF page), 408, 429, 5xx.
export type ExplorerFailure = "gone" | "absent" | "transient";

/** Thrown by the explorer's fetch for a reply it can't use: `status` for an
 *  HTTP error, `rejected` for a 200 with success:false. */
export interface DatastoreError {
  status?: number;
  rejected?: boolean;
}

export function explorerFailureKind(err: unknown): ExplorerFailure {
  if (typeof err !== "object" || err === null) return "transient";
  const { status, rejected } = err as DatastoreError;
  if (typeof status === "number") {
    if (status === 403) return "gone";
    if (status === 408 || status === 429) return "transient";
    if (status >= 400 && status < 500) return "absent";
    return "transient";
  }
  return rejected === true ? "absent" : "transient";
}

/** The schema probe's verdict for one candidate. As `explorerFailureKind`,
 *  except for a fetch the browser refused to show the page (a TypeError: no
 *  status, no body). A real network failure looks like that, and so does a
 *  missing table: data.gov.il's edge answers CKAN's 404 (and its other error
 *  replies) with an HTML page that carries no CORS header (checked
 *  2026-11-11), so the status never reaches this code. For a resource CKAN
 *  flagged datastore-backed (`verified`) that is read as a hiccup. For one
 *  nothing vouches for (legacy data.json without flags) it is read as absent,
 *  or the section would show an error whose retry can never succeed. */
export function probeFailureKind(
  err: unknown,
  verified: boolean
): ExplorerFailure {
  const kind = explorerFailureKind(err);
  return kind === "transient" && !verified && err instanceof TypeError
    ? "absent"
    : kind;
}

/** Aborts `ctrl` with a TimeoutError reason after `ms`; returns the function
 *  that cancels the timer (call it in a `finally`). Not AbortSignal.timeout:
 *  Safari/iOS < 16 and Chrome < 103 don't have it. `onTimeout` runs just
 *  before the abort: Safari < 15.4 and Chrome < 98 ignore abort's reason and
 *  reject the fetch with a plain AbortError, so a caller that must tell a
 *  timeout from its own abort() can't rely on the error alone. */
export function abortAfter(
  ctrl: AbortController,
  ms: number,
  onTimeout?: () => void
): () => void {
  const timer = setTimeout(() => {
    onTimeout?.();
    ctrl.abort(new DOMException("timed out", "TimeoutError"));
  }, ms);
  return () => clearTimeout(timer);
}
