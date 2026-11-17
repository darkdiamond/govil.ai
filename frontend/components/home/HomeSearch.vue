<script setup lang="ts">
// The homepage's search: the site's front door. A plain GET form to
// /datasets/?q= (which reads the query on load), so before hydration or
// without JS it still works. Once mounted it becomes a spotlight: focus opens
// a panel (HomeSpotlight.vue) with the biggest topics and the newest datasets,
// typing turns it into live suggestions (topics, ministries, datasets) with a
// preview of the highlighted dataset. The search is composables/useSiteSearch.ts,
// shared with the header popover.
import { NO_HIGHLIGHT } from "~/utils/header-search";

const s = useSiteSearch("home-search", { ministries: true, idle: true });
const { query, highlight, options } = s;
const router = useRouter();

const rootEl = ref<HTMLElement | null>(null);
const inputEl = ref<HTMLInputElement | null>(null);
const mounted = ref(false);
const focused = ref(false);
// Escape closes the panel without clearing the box; typing reopens it.
const dismissed = ref(false);

const open = computed(() => mounted.value && focused.value && !dismissed.value);

// Text typed before hydration: v-model's mounted hook resets the box to the
// (empty) model on hydration, keeping typed text only for type="text". Read it
// off the server-rendered input first (client hydration only; on an in-app
// navigation to / there is no such element yet).
if (import.meta.client) {
  const ssrInput = document.getElementById("home-search");
  if (ssrInput instanceof HTMLInputElement && ssrInput.value)
    query.value = ssrInput.value;
}

watch(query, () => {
  dismissed.value = false;
});

// ---- The placeholder types out real searches while the box is idle. -------
// Pick examples that have results (nothing checks this automatically).
// Static under reduced motion, and before hydration.
const STATIC_PLACEHOLDER = "חיפוש: רכב, רופאים, בתי ספר…";
const EXAMPLES = [
  "רכב חשמלי",
  "רופאים",
  "בתי ספר",
  "מחירי דירות",
  "תחבורה ציבורית",
  "איכות אוויר",
  "ריבית",
  "תיירות",
];
const placeholder = ref(STATIC_PLACEHOLDER);
let typer: ReturnType<typeof setTimeout> | undefined;

function startTyping() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let ex = 0;
  let len = 0;
  let erasing = false;
  const tick = () => {
    if (focused.value || query.value || document.hidden) {
      placeholder.value = STATIC_PLACEHOLDER;
      typer = setTimeout(tick, 800);
      return;
    }
    const word = EXAMPLES[ex % EXAMPLES.length]!;
    if (!erasing) {
      len++;
      placeholder.value = `חיפוש: ${word.slice(0, len)}`;
      if (len >= word.length) {
        erasing = true;
        typer = setTimeout(tick, 1600);
        return;
      }
      typer = setTimeout(tick, 85);
    } else {
      len--;
      placeholder.value = `חיפוש: ${word.slice(0, len)}`;
      if (len <= 0) {
        erasing = false;
        ex++;
        typer = setTimeout(tick, 350);
        return;
      }
      typer = setTimeout(tick, 35);
    }
  };
  typer = setTimeout(tick, 1200);
}

// ---- Open / close ----------------------------------------------------------
function onFocus() {
  focused.value = true;
  dismissed.value = false;
  s.load();
  // On a phone the keyboard covers the lower half: bring the box to the top
  // so the panel under it stays in view.
  if (window.matchMedia("(max-width: 767px)").matches) {
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)")
      .matches;
    rootEl.value?.scrollIntoView({
      block: "start",
      behavior: smooth ? "smooth" : "auto",
    });
  }
}

// Focus leaving the whole box (Tab, a click elsewhere) closes the panel. A
// click inside the panel keeps focus in the input (mousedown.prevent on it).
function onFocusOut(e: FocusEvent) {
  const next = e.relatedTarget as Node | null;
  if (next && rootEl.value?.contains(next)) return;
  focused.value = false;
  highlight.value = NO_HIGHLIGHT;
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    if (open.value) {
      e.preventDefault();
      dismissed.value = true;
      highlight.value = NO_HIGHLIGHT;
    }
    // A second Escape falls through to the search input's own clearing.
    return;
  }
  if (e.key === "ArrowDown" && dismissed.value) {
    e.preventDefault();
    dismissed.value = false;
    return;
  }
  if (open.value) s.onArrow(e);
}

// Enter in the box: the highlighted suggestion, else the full list. Handled
// on keydown so the form's implicit submit (whose submitter is the button)
// never runs once mounted.
function onEnter(e: KeyboardEvent) {
  if (!mounted.value || e.isComposing) return;
  e.preventDefault();
  if (!open.value) highlight.value = NO_HIGHLIGHT;
  if (!s.submit()) router.push("/datasets/");
}

// The button always means the full list, whatever is highlighted.
function onSubmit(e: Event) {
  if (!mounted.value) return;
  e.preventDefault();
  const q = query.value.trim();
  router.push(q ? { path: "/datasets/", query: { q } } : "/datasets/");
}

// Close behind an in-app route. Dismissed, not unfocused: the input keeps
// focus (mousedown.prevent), so if the route doesn't load (a Ctrl-click opened
// a new tab) typing reopens the panel.
function onNavigate(kind: "page" | "route") {
  if (kind === "route") dismissed.value = true;
}

// "/" anywhere on the page (outside a field) jumps to the box.
function onGlobalKey(e: KeyboardEvent) {
  if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target as HTMLElement | null;
  if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))
    return;
  e.preventDefault();
  inputEl.value?.focus();
}

// A suggestion that leaves the page leaves the box as it was; back from the
// bfcache restores it open. Reset it there, and blur the input: left focused,
// no focus event would come to reopen the panel when the user types.
function onPageShow(e: PageTransitionEvent) {
  if (!e.persisted) return;
  inputEl.value?.blur();
  focused.value = false;
  s.reset();
}

onMounted(() => {
  mounted.value = true;
  window.addEventListener("pageshow", onPageShow);
  window.addEventListener("keydown", onGlobalKey);
  startTyping();
  // Focused before hydration (a fast tap): pick that up.
  if (document.activeElement === inputEl.value) onFocus();
});
onBeforeUnmount(() => {
  clearTimeout(typer);
  window.removeEventListener("pageshow", onPageShow);
  window.removeEventListener("keydown", onGlobalKey);
});
</script>

<template>
  <div
    ref="rootEl"
    class="relative mt-6 max-w-4xl scroll-mt-3"
    :class="{ 'z-40': open }"
    @focusout="onFocusOut"
  >
    <form
      role="search"
      action="/datasets/"
      method="get"
      class="flex gap-2"
      @submit="onSubmit"
      @pointerenter="mounted && s.load()"
    >
      <label for="home-search" class="sr-only"
        >חיפוש מאגר מידע, נושא או משרד</label
      >
      <div class="relative flex-1 min-w-0">
        <img
          src="/icons/search.svg"
          alt=""
          class="pointer-events-none absolute start-4 top-1/2 -translate-y-1/2 w-6 h-6 opacity-50 max-sm:hidden"
        />
        <input
          id="home-search"
          ref="inputEl"
          v-model="query"
          type="search"
          name="q"
          autocomplete="off"
          enterkeyhint="search"
          :placeholder="placeholder"
          :role="mounted ? 'combobox' : undefined"
          :aria-autocomplete="mounted ? 'list' : undefined"
          :aria-controls="mounted ? s.listboxId : undefined"
          :aria-expanded="mounted ? open && options.length > 0 : undefined"
          :aria-activedescendant="open ? s.activeDescendant.value : undefined"
          class="w-full h-14 sm:h-16 ps-3 sm:ps-14 pe-3 sm:pe-12 text-base sm:text-xl bg-white text-ink placeholder:text-subtle border-2 border-ink-deep rounded-gov focus:outline-none focus-visible:ring-4 focus-visible:ring-brand-200 focus-visible:border-brand motion-safe:transition-shadow"
          :class="{ 'shadow-[0_10px_30px_-12px_rgba(11,54,104,0.45)]': open }"
          @focus="onFocus"
          @keydown.enter="onEnter"
          @keydown="onKeydown"
        />
        <kbd
          v-if="mounted && !focused && !query"
          aria-hidden="true"
          class="pointer-events-none absolute end-4 top-1/2 -translate-y-1/2 max-md:hidden px-2 text-sm leading-6 text-subtle bg-surface border border-rule border-b-2 rounded-gov-sm font-sans"
          title="קיצור מקלדת"
          >/</kbd
        >
      </div>
      <!-- A square icon button on a phone keeps the box and button on one row. -->
      <button
        type="submit"
        class="btn-primary shrink-0 h-14 sm:h-16 w-14 sm:w-auto px-0 sm:px-8 text-lg font-medium"
      >
        <img src="/icons/search.svg" alt="" class="w-6 h-6 invert sm:hidden" />
        <span class="sr-only sm:not-sr-only">חיפוש</span>
      </button>
    </form>

    <div
      v-if="open"
      class="absolute inset-x-0 top-full mt-2 bg-white text-ink rounded-gov border border-rule overflow-hidden shadow-[0_28px_60px_-24px_rgba(11,54,104,0.45),0_2px_6px_rgba(11,54,104,0.08)]"
      @mousedown.prevent
    >
      <HomeSpotlight
        :query="query"
        :active="s.active.value"
        :panel="s.panel.value"
        :datasets="s.datasets.value"
        :tags="s.tags.value"
        :ministries="s.ministries.value"
        :total="s.total.value"
        :highlight="highlight"
        :preview="s.preview.value"
        :listbox-id="s.listboxId"
        :option-id="s.optionId"
        @hover="highlight = $event"
        @retry="s.load()"
        @navigate="onNavigate"
      />
    </div>
  </div>
</template>
