// Share targets for dataset and news pages (components/ShareButton.vue).
// Plain intent links only: no third-party scripts, nothing loads until the
// visitor clicks. Pure functions so tests/share.test.mjs can exercise them.

export type ShareNetwork =
  "whatsapp" | "telegram" | "x" | "facebook" | "linkedin" | "email";

export interface ShareTarget {
  network: ShareNetwork;
  /** Visible label (Hebrew). */
  label: string;
  /** Accessible name: destination + action. */
  ariaLabel: string;
  href: string;
}

export interface ShareInput {
  /** Canonical absolute URL. Already percent-encoded where it needs to be. */
  url: string;
  title: string;
  /** Optional one-line description (used in the email body). */
  text?: string;
}

const enc = encodeURIComponent;

/**
 * The URL a network link carries: canonical + utm tags, so GA can tell
 * shared visits apart. Copy-link uses the clean canonical URL instead.
 */
export function withUtm(url: string, network: ShareNetwork): string {
  const u = new URL(url);
  u.searchParams.set("utm_source", "share");
  u.searchParams.set("utm_medium", network);
  return u.toString();
}

export function buildShareLinks({
  url,
  title,
  text,
}: ShareInput): ShareTarget[] {
  const link = (n: ShareNetwork) => enc(withUtm(url, n));
  const t = enc(title);
  const emailBody = [text, withUtm(url, "email")].filter(Boolean).join("\n\n");
  return [
    {
      network: "whatsapp",
      label: "וואטסאפ",
      ariaLabel: "שיתוף בוואטסאפ",
      href: `https://wa.me/?text=${enc(`${title}\n${withUtm(url, "whatsapp")}`)}`,
    },
    {
      network: "telegram",
      label: "טלגרם",
      ariaLabel: "שיתוף בטלגרם",
      href: `https://t.me/share/url?url=${link("telegram")}&text=${t}`,
    },
    {
      network: "x",
      label: "X",
      ariaLabel: "שיתוף ב-X",
      href: `https://x.com/intent/post?url=${link("x")}&text=${t}`,
    },
    {
      network: "facebook",
      label: "פייסבוק",
      ariaLabel: "שיתוף בפייסבוק",
      href: `https://www.facebook.com/sharer/sharer.php?u=${link("facebook")}`,
    },
    {
      network: "linkedin",
      label: "לינקדאין",
      ariaLabel: "שיתוף בלינקדאין",
      href: `https://www.linkedin.com/sharing/share-offsite/?url=${link("linkedin")}`,
    },
    {
      network: "email",
      label: "אימייל",
      ariaLabel: "שיתוף באימייל",
      href: `mailto:?subject=${t}&body=${enc(emailBody)}`,
    },
  ];
}
