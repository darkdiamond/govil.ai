// Shared SEO helper. Emits title, description, canonical, OG, Twitter,
// and JSON-LD blocks (WebSite always; BreadcrumbList + extras when given).
// Keywords seeded with the AI/agentic terms the site ranks on (Hebrew + English).

const SITE_URL = 'https://govil.ai'
const SITE_NAME = 'govil.ai'
const DEFAULT_OG = '/og-default.png'

const BASE_KEYWORDS = [
  'מידע ממשלתי',
  'data.gov.il',
  'בינה מלאכותית',
  'AI',
  'סוכן AI',
  'agentic',
  'אג׳נטי',
  'מאגרי מידע פתוחים',
  'ישראל',
  'open data Israel',
  'government data',
]

export interface BreadcrumbItem {
  name: string
  url: string
}

export interface SeoInput {
  title: string
  description: string
  path: string
  ogImage?: string
  keywords?: string[]
  breadcrumbs?: BreadcrumbItem[]
  extraJsonLd?: object | object[]
  /** Optional <meta name="author"> — set to the publishing ministry on
   *  dataset/ministry pages so search engines and social previews credit
   *  the source. Falls back to the site name when omitted. */
  author?: string
}

// Google routinely rewrites SERP titles when sites self-append branding;
// we let it do that instead by emitting the page title verbatim and
// declaring the brand once via og:site_name.
export function useSeo(input: SeoInput) {
  const title = input.title
  const url = `${SITE_URL}${input.path}`
  const image = input.ogImage ? `${SITE_URL}${input.ogImage}` : `${SITE_URL}${DEFAULT_OG}`
  const keywords = [...BASE_KEYWORDS, ...(input.keywords ?? [])].join(', ')

  const websiteLd = {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: SITE_NAME,
    url: SITE_URL,
    inLanguage: 'he-IL',
    description: input.description,
    image: `${SITE_URL}/web-app-manifest-512x512.png`,
  }

  const organizationLd = {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: SITE_NAME,
    url: SITE_URL,
    logo: `${SITE_URL}/web-app-manifest-512x512.png`,
    description: 'מיזם אזרחי עצמאי למחקר והנגשת מאגרי המידע הממשלתיים הפתוחים של ישראל',
    email: 'contact@govil.ai',
    contactPoint: [
      {
        '@type': 'ContactPoint',
        email: 'contact@govil.ai',
        contactType: 'customer support',
        availableLanguage: ['Hebrew', 'English'],
      },
    ],
  }

  const ldBlocks: object[] = [websiteLd, organizationLd]

  if (input.breadcrumbs && input.breadcrumbs.length > 0) {
    ldBlocks.push({
      '@context': 'https://schema.org',
      '@type': 'BreadcrumbList',
      itemListElement: input.breadcrumbs.map((b, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        name: b.name,
        item: b.url,
      })),
    })
  }

  if (input.extraJsonLd) {
    if (Array.isArray(input.extraJsonLd)) ldBlocks.push(...input.extraJsonLd)
    else ldBlocks.push(input.extraJsonLd)
  }

  useHead({
    title,
    link: [{ rel: 'canonical', href: url }],
    meta: [
      { name: 'description', content: input.description },
      { name: 'keywords', content: keywords },
      { name: 'author', content: input.author ?? SITE_NAME },
      { property: 'og:type', content: 'website' },
      { property: 'og:site_name', content: SITE_NAME },
      { property: 'og:title', content: title },
      { property: 'og:description', content: input.description },
      { property: 'og:url', content: url },
      { property: 'og:image', content: image },
      { property: 'og:locale', content: 'he_IL' },
      { name: 'twitter:card', content: 'summary_large_image' },
      { name: 'twitter:title', content: title },
      { name: 'twitter:description', content: input.description },
      { name: 'twitter:image', content: image },
    ],
    script: ldBlocks.map((ld, i) => ({
      key: `ld-${i}`,
      type: 'application/ld+json',
      innerHTML: JSON.stringify(ld),
    })),
  })
}
