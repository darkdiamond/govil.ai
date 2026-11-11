<script setup lang="ts">
import { useFormspreeSubmit } from "~/composables/useFormspreeSubmit";

defineProps<{
  datasetId: string;
  datasetTitle: string;
  pageUrl: string;
}>();

const open = ref(false);

const { status, errorMsg, onSubmit } = useFormspreeSubmit();
</script>

<template>
  <section class="card p-4">
    <h3 class="m-0 mb-2 text-sm text-subtle font-display">
      נתקלתם בבעיה בעמוד?
    </h3>

    <div
      v-if="status === 'sent'"
      role="status"
      aria-live="polite"
      class="text-sm text-ink/85"
    >
      תודה! הדיווח התקבל ונבדוק אותו בהקדם.
    </div>

    <template v-else>
      <p class="m-0 mb-3 text-xs text-subtle leading-relaxed">
        גרף שלא נטען, נתון שגוי או תקלה אחרת — ספרו לנו ונתקן.
      </p>

      <button
        v-if="!open"
        type="button"
        class="btn-ghost text-sm"
        @click="open = true"
      >
        דיווח על תקלה
      </button>

      <form
        v-else
        action="https://formspree.io/f/xojrvowr"
        method="POST"
        class="space-y-3"
        @submit.prevent="onSubmit"
      >
        <input
          type="hidden"
          name="_subject"
          :value="`דיווח על תקלה — ${datasetTitle}`"
        />
        <input type="hidden" name="topic" value="דיווח על תקלה בעמוד" />
        <input type="hidden" name="dataset_id" :value="datasetId" />
        <input type="hidden" name="dataset_title" :value="datasetTitle" />
        <input type="hidden" name="page_url" :value="pageUrl" />
        <input
          type="text"
          name="_gotcha"
          tabindex="-1"
          autocomplete="off"
          aria-hidden="true"
          class="hidden"
        />

        <div>
          <label
            :for="`report-message-${datasetId}`"
            class="block text-xs text-ink/85 mb-1"
          >
            מה לא עובד? <span class="text-danger" aria-hidden="true">*</span>
          </label>
          <textarea
            :id="`report-message-${datasetId}`"
            name="message"
            required
            rows="3"
            placeholder="למשל: הגרף השני לא נטען, נתון שגוי בטבלה…"
            class="w-full border border-rule rounded-gov px-3 py-2 bg-white text-sm resize-y"
          ></textarea>
        </div>

        <div>
          <label
            :for="`report-email-${datasetId}`"
            class="block text-xs text-ink/85 mb-1"
          >
            דוא"ל
            <span class="text-subtle">(אופציונלי, אם תרצו שנחזור אליכם)</span>
          </label>
          <input
            :id="`report-email-${datasetId}`"
            name="email"
            type="email"
            autocomplete="email"
            class="w-full border border-rule rounded-gov px-3 py-2 bg-white text-sm"
          />
        </div>

        <p
          v-if="status === 'error'"
          class="text-xs text-danger m-0"
          role="alert"
        >
          {{ errorMsg }}
        </p>

        <div class="flex items-center gap-2">
          <button
            type="submit"
            :disabled="status === 'sending'"
            class="btn-primary text-sm disabled:opacity-60 disabled:cursor-wait"
          >
            {{ status === "sending" ? "שולח…" : "שליחת דיווח" }}
          </button>
          <button type="button" class="btn-ghost text-sm" @click="open = false">
            ביטול
          </button>
        </div>
      </form>
    </template>
  </section>
</template>
