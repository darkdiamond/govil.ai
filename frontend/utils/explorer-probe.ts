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

/** Aborts `ctrl` with a TimeoutError reason after `ms`; returns the function
 *  that cancels the timer (call it in a `finally`). Not AbortSignal.timeout:
 *  Safari/iOS < 16 and Chrome < 103 don't have it. */
export function abortAfter(ctrl: AbortController, ms: number): () => void {
  const timer = setTimeout(
    () => ctrl.abort(new DOMException("timed out", "TimeoutError")),
    ms
  );
  return () => clearTimeout(timer);
}
