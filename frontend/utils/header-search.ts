// Pure state helpers for components/HeaderSearch.vue, kept out of the SFC so
// the node --test suite can reach them (tests/header-search.test.mjs).

/** -1 = nothing highlighted: Enter opens the full results list. */
export const NO_HIGHLIGHT = -1;

/** The highlight after an arrow key. The cycle runs through "nothing
 *  highlighted" (-1), so the arrows can go back to the full-list Enter:
 *  Down: -1 → 0 → … → last → -1; Up: -1 → last → … → 0 → -1. */
export function moveHighlight(
  key: "ArrowDown" | "ArrowUp",
  current: number,
  count: number
): number {
  if (count <= 0) return NO_HIGHLIGHT;
  const cur = current >= 0 && current < count ? current : NO_HIGHLIGHT;
  if (key === "ArrowDown") return cur === count - 1 ? NO_HIGHLIGHT : cur + 1;
  return cur === NO_HIGHLIGHT ? count - 1 : cur - 1;
}

export type SubmitTarget =
  { kind: "hit"; index: number } | { kind: "list"; q: string } | null;

/** What Enter does: a highlighted hit opens that dataset, otherwise a
 *  non-empty query opens the full list (/datasets/?q=…). */
export function submitTarget(
  query: string,
  highlight: number,
  count: number
): SubmitTarget {
  if (highlight >= 0 && highlight < count)
    return { kind: "hit", index: highlight };
  const q = query.trim();
  return q ? { kind: "list", q } : null;
}

export type LoadState = "idle" | "loading" | "ready" | "failed";
export type PanelState = "results" | "loading" | "failed" | "empty" | "prompt";

/** Which body the popover shows. Too short a query shows the prompt; past
 *  that, an index that is still loading or failed to load says so instead
 *  of claiming there are no results. */
export function panelState(
  query: string,
  load: LoadState,
  count: number
): PanelState {
  if (count > 0) return "results";
  if (query.trim().length < 2) return "prompt";
  if (load === "failed") return "failed";
  if (load !== "ready") return "loading";
  return "empty";
}
