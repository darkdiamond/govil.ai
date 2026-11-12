<script setup lang="ts">
// "Found a mistake?" on a news article: the stories are written by an
// automated system, so readers get a small link that opens a short form. It
// posts to the same Formspree form as the dataset pages' ReportIssue, tagged
// with the article's slug so a report maps to `services.news.admin correct`.
import { useFormspreeSubmit } from "~/composables/useFormspreeSubmit";

const props = defineProps<{ slug: string; headline: string; url: string }>();

const open = ref(false);
const message = ref<HTMLTextAreaElement | null>(null);
const { status, errorMsg, onSubmit } = useFormspreeSubmit();

async function show() {
  open.value = true;
  await nextTick();
  message.value?.focus();
}

const formId = computed(() => `news-report-${props.slug}`);
</script>

<template>
  <div class="text-sm">
    <p
      v-if="status === 'sent'"
      role="status"
      aria-live="polite"
      class="m-0 text-ink"
    >
      תודה, הדיווח התקבל. נבדוק את הכתבה ונתקן אם צריך.
    </p>

    <template v-else>
      <p class="m-0 text-subtle">
        <button
          type="button"
          class="inline p-0 bg-transparent border-0 text-brand underline-offset-2 hover:underline cursor-pointer"
          :aria-expanded="open"
          :aria-controls="formId"
          @click="open ? (open = false) : show()"
        >
          מצאתם טעות? ספרו לנו
        </button>
      </p>

      <form
        v-if="open"
        :id="formId"
        action="https://formspree.io/f/xojrvowr"
        method="POST"
        class="mt-3 space-y-3 max-w-xl"
        @submit.prevent="onSubmit"
      >
        <input
          type="hidden"
          name="_subject"
          :value="`טעות בכתבה: ${headline}`"
        />
        <input type="hidden" name="topic" value="דיווח על טעות בכתבה" />
        <input type="hidden" name="article_slug" :value="slug" />
        <input type="hidden" name="page_url" :value="url" />
        <input
          type="text"
          name="_gotcha"
          tabindex="-1"
          autocomplete="off"
          aria-hidden="true"
          class="hidden"
        />

        <div>
          <label :for="`${formId}-message`" class="block text-ink mb-1">
            מה לא נכון? <span class="text-danger" aria-hidden="true">*</span>
          </label>
          <textarea
            :id="`${formId}-message`"
            ref="message"
            name="message"
            required
            rows="3"
            placeholder="למשל: המספר בפסקה השנייה לא תואם את המאגר"
            class="w-full border border-rule rounded-gov px-3 py-2 bg-white resize-y"
          ></textarea>
        </div>

        <div>
          <label :for="`${formId}-email`" class="block text-ink mb-1">
            דוא"ל
            <span class="text-subtle">(לא חובה, אם תרצו שנחזור אליכם)</span>
          </label>
          <input
            :id="`${formId}-email`"
            name="email"
            type="email"
            autocomplete="email"
            class="w-full border border-rule rounded-gov px-3 py-2 bg-white"
          />
        </div>

        <p v-if="status === 'error'" class="m-0 text-danger" role="alert">
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
  </div>
</template>
