// Helpers for the mobile navigation drawer (components/MobileNavDrawer.vue).

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface FocusContainer {
  querySelectorAll(selector: string): ArrayLike<{ focus(): void }>;
  contains(el: unknown): boolean;
}

/** Keep Tab / Shift+Tab inside `container`: wrap at either end, and pull focus
 * back in if it has left. Other keys are ignored. */
export function trapTabKey(
  e: Pick<KeyboardEvent, "key" | "shiftKey" | "preventDefault">,
  container: FocusContainer | null | undefined,
  doc: { activeElement: unknown } = document
): void {
  if (e.key !== "Tab" || !container) return;
  const items = Array.from(container.querySelectorAll(FOCUSABLE));
  const first = items[0];
  const last = items[items.length - 1];
  if (!first || !last) return;
  const active = doc.activeElement;
  const inside = container.contains(active);
  if (e.shiftKey && (!inside || active === first)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (!inside || active === last)) {
    e.preventDefault();
    first.focus();
  }
}

// Tailwind's md breakpoint: the drawer and its trigger are md:hidden.
const DESKTOP_QUERY = "(min-width: 768px)";

/** Call `cb` whenever the viewport widens past md. Returns the cleanup. */
export function onDesktopWidth(
  win: Pick<Window, "matchMedia">,
  cb: () => void
): () => void {
  const mql = win.matchMedia(DESKTOP_QUERY);
  const listener = (e: { matches: boolean }) => {
    if (e.matches) cb();
  };
  mql.addEventListener("change", listener);
  return () => mql.removeEventListener("change", listener);
}
