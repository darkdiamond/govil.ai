<template>
  <section
    aria-labelledby="home-about-h"
    class="py-6 border-t border-rule grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center"
  >
    <div class="max-w-3xl">
      <h2 id="home-about-h" class="m-0 text-lg font-display text-ink-deep">
        איך זה עובד
      </h2>
      <p class="m-0 mt-1 text-base text-subtle">
        כל עמוד מאגר מחושב מחדש מהנתונים הרשמיים בכל עדכון שלהם. הכתבות נכתבות
        בעזרת AI מאותם נתונים, וכל מספר בהן נבדק מול הנתונים לפני פרסום.
      </p>
    </div>
    <nav aria-label="על האתר">
      <ul class="list-none m-0 p-0 flex flex-wrap gap-x-5 gap-y-2 text-sm">
        <li><NuxtLink to="/about/#how-it-works">איך זה עובד</NuxtLink></li>
        <li><NuxtLink to="/news/about/">איך נכתבות החדשות</NuxtLink></li>
        <li><NuxtLink to="/faq/">שאלות נפוצות</NuxtLink></li>
      </ul>
    </nav>
  </section>
</template>
