// The og:image / twitter:image tags, as data. Pure (no Vue), so
// tests/seo-og.test.mjs can run it under node.
import { SITE_URL } from "~/utils/paths";

export const DEFAULT_OG = "/og-default.png";
// public/og-default.png. Keep in step with the file.
export const DEFAULT_OG_SIZE = { width: 1200, height: 630 };

export interface OgImageInput {
  /** Site path ("/news/x/hero-16x9-….jpg"); the site default when omitted. */
  path?: string | null;
  width?: number;
  height?: number;
  alt?: string | null;
}

type Meta = { property?: string; name?: string; content: string };

/** The image's absolute URL plus its meta tags. Width and height only when
 *  known: a wrong size is worse than none. */
export function ogImageMeta(input: OgImageInput): {
  url: string;
  meta: Meta[];
} {
  const own = !!input.path;
  const url = `${SITE_URL}${own ? input.path : DEFAULT_OG}`;
  const size = own
    ? input.width && input.height
      ? { width: input.width, height: input.height }
      : null
    : DEFAULT_OG_SIZE;
  const alt = own ? input.alt?.trim() : "";
  const meta: Meta[] = [{ property: "og:image", content: url }];
  if (size) {
    meta.push(
      { property: "og:image:width", content: String(size.width) },
      { property: "og:image:height", content: String(size.height) }
    );
  }
  if (alt) meta.push({ property: "og:image:alt", content: alt });
  meta.push({ name: "twitter:image", content: url });
  if (alt) meta.push({ name: "twitter:image:alt", content: alt });
  return { url, meta };
}
