import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import { parse } from '@vue/compiler-sfc'
import { compile } from '@vue/compiler-ssr'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'

// Render the actual page template (not a copied condition), with a minimal
// payload so this regression stays offline and independent of generated data.
const filename = new URL('../pages/datasets/[slug].vue', import.meta.url)
const { descriptor } = parse(readFileSync(filename, 'utf8'))
const { code } = compile(descriptor.template.content)
const ssrRender = new Function('require', code)(createRequire(import.meta.url))
const resource = {
  url: 'https://data.gov.il/dataset/a698417e-e51d-43cd-b82f-356d8cf9de0e/resource/example/download/example.csv',
  format: 'CSV', name: 'example.csv',
}

async function renderPage(source_status, resources = [resource]) {
  const app = createSSRApp({
    ssrRender,
    setup: () => ({
      entry: { id: 'a698417e-e51d-43cd-b82f-356d8cf9de0e', title: 'מאגר', source_status, resources },
      body: '<h1>Archived analysis</h1>', unavailableSinceHe: '',
      datasetUrl: 'https://govil.ai/datasets/example/',
      hasMeta: false, related: [], allTags: [],
      publicResourceUrl: (url) => url, formatClass: () => 'fmt-csv',
      formatBytes: String,
    }),
  })
  for (const name of ['NuxtLink', 'AdSlot', 'DatasetExplorer', 'ReportIssue']) {
    app.component(name, { render: () => null })
  }
  return renderToString(app)
}

test('unavailable dataset preserves archive but does not offer broken downloads', async () => {
  const html = await renderPage('unavailable')
  assert.match(html, /unavailable-banner/)
  assert.match(html, /Archived analysis/)
  assert.doesNotMatch(html, /קבצים להורדה/)
  assert.doesNotMatch(html, /<a\b[^>]*\bdownload\b/)
  assert.ok(!html.includes(resource.url))
})

for (const status of ['available', undefined]) {
  test(`available or legacy dataset (${status}) retains downloads`, async () => {
    const html = await renderPage(status)
    assert.match(html, /קבצים להורדה/)
    assert.match(html, /<a\b[^>]*\bdownload\b/)
    assert.ok(html.includes(resource.url))
    assert.doesNotMatch(html, /unavailable-banner/)
  })
}

test('dataset without resources has no download section', async () => {
  const html = await renderPage('available', [])
  assert.doesNotMatch(html, /קבצים להורדה/)
  assert.doesNotMatch(html, /<a\b[^>]*\bdownload\b/)
})
