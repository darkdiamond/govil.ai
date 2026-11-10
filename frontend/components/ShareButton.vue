<script setup lang="ts">
// One quiet "שתף" button. On touch devices with the Web Share API it opens
// the device's own share sheet (every app the visitor has). Elsewhere it opens
// a small menu: copy link + plain intent links (utils/share.ts). No
// third-party scripts; nothing loads until a click.
import { buildShareLinks, type ShareNetwork } from "~/utils/share";
import { SHARE_ICONS as ICONS } from "~/utils/share-icons";

const props = withDefaults(
  defineProps<{
    url: string;
    title: string;
    text?: string;
    contentType: "dataset" | "article";
    itemId: string;
    label?: string;
    /** "quiet" = badge-sized (breadcrumb / meta row); "ghost" = btn-ghost. */
    variant?: "quiet" | "ghost";
  }>(),
  { text: "", label: "שתף", variant: "quiet" }
);

const links = computed(() =>
  buildShareLinks({ url: props.url, title: props.title, text: props.text })
);

const uid = useId();
const menuId = `share-menu-${uid}`;
const root = ref<HTMLElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);
const urlInput = ref<HTMLInputElement | null>(null);
const open = ref(false);
type CopyState = "idle" | "copied" | "failed";
const copyState = ref<CopyState>("idle");
const status = ref("");
let statusTimer: ReturnType<typeof setTimeout> | undefined;

// Decided on the client only, so SSR and hydration render the same button.
const nativeShare = ref(false);
onMounted(() => {
  nativeShare.value =
    typeof navigator.share === "function" &&
    window.matchMedia("(pointer: coarse)").matches;
});

function track(method: ShareNetwork | "copy" | "native") {
  useTrackEvent("share", {
    method,
    content_type: props.contentType,
    item_id: props.itemId,
  });
}

function announce(msg: string) {
  status.value = msg;
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => (status.value = ""), 4000);
}

async function onTrigger() {
  if (open.value) return close(false);
  if (nativeShare.value) {
    try {
      await navigator.share({
        title: props.title,
        text: props.text || undefined,
        url: props.url,
      });
      track("native");
      return;
    } catch (e) {
      // The visitor dismissed the sheet: nothing to do.
      if ((e as DOMException)?.name === "AbortError") return;
      // Anything else (NotAllowedError, unsupported data): use the menu.
    }
  }
  copyState.value = "idle";
  open.value = true;
}

function close(restoreFocus = true) {
  open.value = false;
  if (restoreFocus) trigger.value?.focus();
}

function legacyCopy(text: string): boolean {
  // The textarea lives inside the widget, so moving focus to it doesn't
  // trip onFocusOut (which would close the menu before the result shows).
  const host = root.value ?? document.body;
  const prev = document.activeElement as HTMLElement | null;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.setAttribute("aria-hidden", "true");
  ta.tabIndex = -1;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  host.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  ta.remove();
  prev?.focus();
  return ok;
}

async function copyLink() {
  let ok = false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(props.url);
      ok = true;
    } else {
      ok = legacyCopy(props.url);
    }
  } catch {
    ok = legacyCopy(props.url);
  }
  if (ok) {
    copyState.value = "copied";
    announce("הקישור הועתק");
    track("copy");
  } else {
    // Show the URL selected so the visitor can copy it by hand.
    copyState.value = "failed";
    announce("לא הצלחנו להעתיק. הקישור מסומן להעתקה ידנית.");
    await nextTick();
    urlInput.value?.focus();
    urlInput.value?.select();
  }
}

function onLink(network: ShareNetwork) {
  track(network);
  close(false);
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && open.value) {
    e.stopPropagation();
    close();
  }
}

function onFocusOut(e: FocusEvent) {
  const next = e.relatedTarget as Node | null;
  // Focus left the widget (Tab past the last item, or a click elsewhere).
  if (open.value && next && !root.value?.contains(next)) close(false);
}

function onDocPointer(e: PointerEvent) {
  if (open.value && !root.value?.contains(e.target as Node)) close(false);
}
watch(open, (v) => {
  if (v) document.addEventListener("pointerdown", onDocPointer);
  else document.removeEventListener("pointerdown", onDocPointer);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onDocPointer);
  clearTimeout(statusTimer);
});

const itemClass =
  "group flex items-center gap-2.5 min-h-[2.25rem] px-2.5 rounded-gov-sm text-ink no-underline text-start hover:bg-surface hover:text-brand hover:no-underline focus-visible:bg-surface";
</script>

<template>
  <div
    ref="root"
    class="relative inline-block"
    @keydown="onKeydown"
    @focusout="onFocusOut"
  >
    <button
      ref="trigger"
      type="button"
      :class="
        variant === 'ghost'
          ? 'btn-ghost text-sm px-3 py-1.5'
          : 'inline-flex items-center gap-1.5 min-h-[1.625rem] px-2.5 py-0.5 text-xs bg-white border border-rule rounded-gov-sm text-subtle hover:text-brand hover:border-brand-200 transition-colors'
      "
      :aria-expanded="open ? 'true' : 'false'"
      :aria-controls="menuId"
      @click="onTrigger"
    >
      <!-- eslint-disable-next-line vue/no-v-html -- constant icon markup -->
      <svg
        class="w-3.5 h-3.5 shrink-0"
        viewBox="0 0 24 24"
        aria-hidden="true"
        v-html="ICONS.share"
      />
      <span>{{ label }}</span>
    </button>

    <div
      v-show="open"
      :id="menuId"
      role="group"
      :aria-label="`שיתוף: ${title}`"
      class="absolute end-0 top-full mt-1 z-30 w-56 max-w-[calc(100vw-2rem)] bg-white border border-rule rounded-gov shadow-lg p-1.5 text-sm text-ink"
    >
      <button type="button" :class="[itemClass, 'w-full']" @click="copyLink">
        <svg
          class="w-4 h-4 shrink-0"
          :class="copyState === 'copied' ? 'text-ok' : 'text-subtle'"
          viewBox="0 0 24 24"
          aria-hidden="true"
          v-html="copyState === 'copied' ? ICONS.check : ICONS.link"
        />
        <span>{{
          copyState === "copied" ? "הקישור הועתק" : "העתקת קישור"
        }}</span>
      </button>
      <input
        v-if="copyState === 'failed'"
        ref="urlInput"
        :value="url"
        readonly
        dir="ltr"
        aria-label="קישור לעמוד"
        class="block w-full my-1 px-2 py-1 text-xs border border-rule rounded-gov-sm bg-surface-alt"
        @focus="($event.target as HTMLInputElement).select()"
      />
      <div class="my-1 border-t border-rule" role="presentation" />
      <a
        v-for="l in links"
        :key="l.network"
        :href="l.href"
        target="_blank"
        rel="noopener noreferrer"
        :aria-label="l.ariaLabel"
        :class="itemClass"
        @click="onLink(l.network)"
      >
        <svg
          class="w-4 h-4 shrink-0 text-subtle group-hover:text-brand"
          viewBox="0 0 24 24"
          aria-hidden="true"
          v-html="ICONS[l.network]"
        />
        <span>{{ l.label }}</span>
      </a>
    </div>

    <span class="sr-only" role="status" aria-live="polite">{{ status }}</span>
  </div>
</template>
