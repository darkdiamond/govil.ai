#!/usr/bin/env node
// Generates sitemap.xml from public/data/manifest.json after `nuxt generate`
// completes. Always writes public/sitemap.xml (gitignored; keeps the dev
// server serving a current sitemap) and, when the build output exists,
// .output/public/sitemap.xml — the copy that actually ships. Listed URLs: the
// static routes, every /ministries/<slug>/, /tags/<encoded-tag>/,
// /kinds/<kind>/, and every agent-authored /datasets/<page_slug>/. Each URL
// gets <priority>, <changefreq>, and (where known) <lastmod>.

import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..')
const SITE = 'https://govil.ai'

const manifestPath = resolve(ROOT, 'public/data/manifest.json')
const publicSitemapPath = resolve(ROOT, 'public/sitemap.xml')
const outPath = resolve(ROOT, '.output/public/sitemap.xml')

let manifest = { datasets: [], generated_at: undefined }
try {
  manifest = JSON.parse(readFileSync(manifestPath, 'utf-8'))
} catch {
  console.warn('[build-sitemap] no manifest.json, emitting static-only sitemap')
}

const today = new Date().toISOString().slice(0, 10)
const manifestLastmod = (manifest.generated_at ?? '').slice(0, 10) || today

/** @type {Map<string, { priority: string, changefreq: string, lastmod?: string }>} */
const urls = new Map()

function add(path, priority, changefreq, lastmod) {
  if (!urls.has(path)) urls.set(path, { priority, changefreq, lastmod })
}

// Static / hub routes
add('/', '1.0', 'daily', manifestLastmod)
add('/datasets/', '0.9', 'daily', manifestLastmod)
add('/ministries/', '0.7', 'weekly', manifestLastmod)
add('/tags/', '0.7', 'weekly', manifestLastmod)
add('/about/', '0.5', 'monthly')
add('/how-it-works/', '0.5', 'monthly')
add('/faq/', '0.5', 'monthly')
add('/contact/', '0.5', 'monthly')
add('/disclaimer/', '0.4', 'monthly')
add('/accessibility/', '0.3', 'monthly')
add('/privacy/', '0.3', 'monthly')
add('/terms/', '0.3', 'monthly')

// Dynamic dataset + category routes
const tagSlugs = manifest.tag_slugs ?? {}
for (const d of manifest.datasets ?? []) {
  const pageSlug = d.page_slug || d.id
  if (pageSlug) {
    const lastmod = (d.last_analyzed_at ?? d.metadata_modified ?? '').slice(0, 10) || undefined
    add(`/datasets/${encodeURI(pageSlug)}/`, '0.8', 'weekly', lastmod)
  }
  if (d.organization_slug) {
    add(`/ministries/${d.organization_slug}/`, '0.6', 'weekly', manifestLastmod)
  }
  for (const t of d.tags_he ?? []) {
    const slug = tagSlugs[t]
    if (slug) add(`/tags/${encodeURI(slug)}/`, '0.5', 'weekly', manifestLastmod)
  }
  if (d.dataset_kind) {
    add(`/kinds/${d.dataset_kind}/`, '0.5', 'weekly', manifestLastmod)
  }
}

const sorted = [...urls.entries()].sort(([a], [b]) => a.localeCompare(b))

const body = sorted
  .map(([path, { priority, changefreq, lastmod }]) => {
    const lines = [`    <loc>${SITE}${path}</loc>`]
    if (lastmod) lines.push(`    <lastmod>${lastmod}</lastmod>`)
    lines.push(`    <changefreq>${changefreq}</changefreq>`)
    lines.push(`    <priority>${priority}</priority>`)
    return `  <url>\n${lines.join('\n')}\n  </url>`
  })
  .join('\n')

const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${body}
</urlset>
`

writeFileSync(publicSitemapPath, xml, 'utf-8')
console.log(`[build-sitemap] wrote ${urls.size} URLs to ${publicSitemapPath}`)

if (existsSync(dirname(outPath))) {
  writeFileSync(outPath, xml, 'utf-8')
  console.log(`[build-sitemap] wrote ${urls.size} URLs to ${outPath}`)
}
