import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'

// --- publicResourceUrl: only http(s) links reach an href -------------------

const tsSource = readFileSync(new URL('../utils/resource-url.ts', import.meta.url), 'utf8')
const { code: resourceUrlJs } = transformSync(tsSource, { loader: 'ts', format: 'cjs' })
const resourceUrlModule = { exports: {} }
new Function('module', 'exports', resourceUrlJs)(resourceUrlModule, resourceUrlModule.exports)
const { publicResourceUrl } = resourceUrlModule.exports

test('publicResourceUrl rejects non-http(s) schemes', () => {
  for (const bad of ['javascript:alert(1)', ' JavaScript:alert(1)', 'data:text/html,<script>', 'vbscript:x', '//evil.example/x', 'ftp://x/y']) {
    assert.equal(publicResourceUrl(bad), '', bad)
  }
  assert.equal(publicResourceUrl(undefined), '')
  assert.equal(publicResourceUrl(''), '')
})

test('publicResourceUrl keeps the gated-host and locale rewrites', () => {
  assert.equal(
    publicResourceUrl('https://e.data.gov.il/dataset/x/resource/y/download/z.csv'),
    'https://data.gov.il/dataset/x/resource/y/download/z.csv',
  )
  assert.equal(
    publicResourceUrl('https://data.gov.il/he/dataset/x/resource/y'),
    'https://data.gov.il/dataset/x/resource/y',
  )
  assert.equal(publicResourceUrl('http://example.org/a.csv'), 'http://example.org/a.csv')
})

// --- gov-echarts.js: tooltip formatters see escaped dataset strings --------

function loadGovEcharts() {
  const captured = []
  const echarts = {
    init: () => ({ setOption: (opt) => captured.push(opt) }),
    format: {
      formatTpl: (tpl, p) => tpl.replace('{b}', p.name).replace('{a}', p.seriesName).replace('{c}', p.value),
    },
  }
  const window = { echarts }
  vm.runInNewContext(readFileSync(new URL('../scripts/gov-echarts.js', import.meta.url), 'utf8'), { window })
  return { window, captured }
}

const evil = '<img src=x onerror=alert(1)>'

test('GovEcharts.option escapes params for function tooltip formatters', () => {
  const { window } = loadGovEcharts()
  const o = window.GovEcharts.option({
    tooltip: { formatter: (p) => '<b>' + p.name + '</b>: ' + p.value },
    series: [{ type: 'bar', data: [1] }],
  })
  const html = o.tooltip.formatter({ name: evil, value: 3 })
  assert.ok(!html.includes('<img'), html)
  assert.ok(html.startsWith('<b>&lt;img'), 'agent markup kept, data escaped')
})

test('axis-trigger params arrays and string templates are escaped', () => {
  const { window } = loadGovEcharts()
  const o = window.GovEcharts.option({
    tooltip: { trigger: 'axis', formatter: (ps) => ps.map((p) => p.seriesName + p.axisValue).join('') },
    series: [{ type: 'line', tooltip: { formatter: '{b}: {c}' } }],
  })
  assert.ok(!o.tooltip.formatter([{ seriesName: evil, axisValue: evil }]).includes('<'))
  assert.equal(o.series[0].tooltip.formatter({ name: evil, value: 5 }), '&lt;img src=x onerror=alert(1)&gt;: 5')
})

test('Hebrew labels with quotes stay comparable (only < and > change)', () => {
  const { window } = loadGovEcharts()
  const o = window.GovEcharts.option({ tooltip: { formatter: (p) => (p.name === 'ת"א-יפו' ? 'match' : 'miss') } })
  assert.equal(o.tooltip.formatter({ name: 'ת"א-יפו' }), 'match')
})

test('direct chart.setOption without GovEcharts.option is also covered', () => {
  const { window, captured } = loadGovEcharts()
  const chart = window.echarts.init({})
  chart.setOption({ tooltip: { formatter: (p) => p.name } })
  assert.equal(captured[0].tooltip.formatter({ name: evil }), '&lt;img src=x onerror=alert(1)&gt;')
  // Idempotent: re-wrapping an already-safe formatter does not double-escape.
  chart.setOption(captured[0])
  assert.equal(captured[1].tooltip.formatter({ name: '<b>' }), '&lt;b&gt;')
})
