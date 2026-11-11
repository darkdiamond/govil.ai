// Submit handler for the site's Formspree forms (components/ReportIssue.vue,
// pages/contact.vue): POSTs the form to its action with fetch, so the page
// stays put, and tracks idle → sending → sent | error. Each form keeps its own
// fields and texts; `onSent` runs after a successful send resets the form.

export type FormspreeStatus = "idle" | "sending" | "sent" | "error";

export function useFormspreeSubmit(opts: { onSent?: () => void } = {}) {
  const status = ref<FormspreeStatus>("idle");
  const errorMsg = ref("");

  async function onSubmit(e: Event) {
    const form = e.target as HTMLFormElement;
    status.value = "sending";
    errorMsg.value = "";
    try {
      const res = await fetch(form.action, {
        method: "POST",
        headers: { Accept: "application/json" },
        body: new FormData(form),
      });
      if (res.ok) {
        status.value = "sent";
        form.reset();
        opts.onSent?.();
        return;
      }
      const data = (await res.json().catch(() => null)) as {
        errors?: { message?: string }[];
      } | null;
      errorMsg.value =
        data?.errors?.[0]?.message || "שליחה נכשלה. נסו שוב מאוחר יותר.";
      status.value = "error";
    } catch {
      errorMsg.value = "בעיית חיבור. נסו שוב מאוחר יותר.";
      status.value = "error";
    }
  }

  return { status, errorMsg, onSubmit };
}
