import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { transformSync } from "esbuild";

// --- publicResourceUrl: only http(s) links reach an href -------------------

const tsSource = readFileSync(
  new URL("../utils/resource-url.ts", import.meta.url),
  "utf8"
);
const { code: resourceUrlJs } = transformSync(tsSource, {
  loader: "ts",
  format: "cjs",
});
const resourceUrlModule = { exports: {} };
new Function("module", "exports", resourceUrlJs)(
  resourceUrlModule,
  resourceUrlModule.exports
);
const { publicResourceUrl } = resourceUrlModule.exports;

// Shared with services/scanner/tests/test_models.py (the Python original).
const { vectors: resourceUrlVectors } = JSON.parse(
  readFileSync(
    new URL("./fixtures/resource-url-vectors.json", import.meta.url),
    "utf8"
  )
);

test("publicResourceUrl matches the shared vectors", () => {
  assert.ok(resourceUrlVectors.length > 10);
  for (const [input, expected] of resourceUrlVectors) {
    assert.equal(publicResourceUrl(input), expected, JSON.stringify(input));
  }
});

test("publicResourceUrl rejects missing input", () => {
  assert.equal(publicResourceUrl(undefined), "");
  assert.equal(publicResourceUrl(null), "");
});

// --- gov-echarts.js: tooltip formatters see escaped dataset strings --------

function loadGovEcharts() {
  const captured = [];
  const echarts = {
    init: () => ({ setOption: (opt) => captured.push(opt) }),
    format: {
      formatTpl: (tpl, p) =>
        tpl
          .replace("{b}", p.name)
          .replace("{a}", p.seriesName)
          .replace("{c}", p.value),
    },
  };
  const window = { echarts };
  vm.runInNewContext(
    readFileSync(new URL("../scripts/gov-echarts.js", import.meta.url), "utf8"),
    { window }
  );
  return { window, captured };
}

const evil = "<img src=x onerror=alert(1)>";

test("GovEcharts.option escapes params for function tooltip formatters", () => {
  const { window } = loadGovEcharts();
  const o = window.GovEcharts.option({
    tooltip: { formatter: (p) => "<b>" + p.name + "</b>: " + p.value },
    series: [{ type: "bar", data: [1] }],
  });
  const html = o.tooltip.formatter({ name: evil, value: 3 });
  assert.ok(!html.includes("<img"), html);
  assert.ok(html.startsWith("<b>&lt;img"), "agent markup kept, data escaped");
});

test("axis-trigger params arrays and string templates are escaped", () => {
  const { window } = loadGovEcharts();
  const o = window.GovEcharts.option({
    tooltip: {
      trigger: "axis",
      formatter: (ps) => ps.map((p) => p.seriesName + p.axisValue).join(""),
    },
    series: [{ type: "line", tooltip: { formatter: "{b}: {c}" } }],
  });
  assert.ok(
    !o.tooltip.formatter([{ seriesName: evil, axisValue: evil }]).includes("<")
  );
  assert.equal(
    o.series[0].tooltip.formatter({ name: evil, value: 5 }),
    "&lt;img src=x onerror=alert(1)&gt;: 5"
  );
});

test("Hebrew labels with quotes stay comparable (only < and > change)", () => {
  const { window } = loadGovEcharts();
  const o = window.GovEcharts.option({
    tooltip: { formatter: (p) => (p.name === 'ת"א-יפו' ? "match" : "miss") },
  });
  assert.equal(o.tooltip.formatter({ name: 'ת"א-יפו' }), "match");
});

test("direct chart.setOption without GovEcharts.option is also covered", () => {
  const { window, captured } = loadGovEcharts();
  const chart = window.echarts.init({});
  chart.setOption({ tooltip: { formatter: (p) => p.name } });
  assert.equal(
    captured[0].tooltip.formatter({ name: evil }),
    "&lt;img src=x onerror=alert(1)&gt;"
  );
  // Idempotent: re-wrapping an already-safe formatter does not double-escape.
  chart.setOption(captured[0]);
  assert.equal(captured[1].tooltip.formatter({ name: "<b>" }), "&lt;b&gt;");
});

test("other p.data fields are escaped (treemap gloss)", () => {
  const { window } = loadGovEcharts();
  const o = window.GovEcharts.option({
    series: [
      {
        type: "treemap",
        tooltip: { formatter: (p) => p.name + " · " + p.data.gloss },
      },
    ],
  });
  const html = o.series[0].tooltip.formatter({
    name: evil,
    data: { name: evil, gloss: evil, value: 3 },
  });
  assert.ok(!html.includes("<img"), html);
});

test("strings inside a p.value array are escaped", () => {
  const { window } = loadGovEcharts();
  const o = window.GovEcharts.option({
    tooltip: { formatter: (p) => String(p.value[2]) + p.data[2] },
  });
  const html = o.tooltip.formatter({ value: [1, 2, evil], data: [1, 2, evil] });
  assert.ok(!html.includes("<img"), html);
});

test("sankey edge source/target are escaped", () => {
  const { window } = loadGovEcharts();
  const o = window.GovEcharts.option({
    series: [
      {
        type: "sankey",
        tooltip: {
          formatter: (p) => p.data.source + " ← " + p.data.target,
        },
      },
    ],
  });
  const html = o.series[0].tooltip.formatter({
    dataType: "edge",
    data: { source: evil, target: evil, value: 4 },
  });
  assert.ok(!html.includes("<img"), html);
});

test("formatters under baseOption, options[], media and markPoint are wrapped", () => {
  const { window, captured } = loadGovEcharts();
  const chart = window.echarts.init({});
  const f = (p) => p.name;
  chart.setOption({
    baseOption: {
      tooltip: { formatter: f },
      series: [{ type: "bar", markPoint: { tooltip: { formatter: f } } }],
    },
    options: [{ tooltip: { formatter: f } }],
    media: [{ query: {}, option: { tooltip: { formatter: f } } }],
    legend: { tooltip: { show: true, formatter: f } },
  });
  const o = captured[0];
  for (const fn of [
    o.baseOption.tooltip.formatter,
    o.baseOption.series[0].markPoint.tooltip.formatter,
    o.options[0].tooltip.formatter,
    o.media[0].option.tooltip.formatter,
    o.legend.tooltip.formatter,
  ]) {
    assert.ok(!fn({ name: evil }).includes("<img"));
  }
});

test("deep escape keeps quoted Hebrew labels comparable", () => {
  const { window } = loadGovEcharts();
  const o = window.GovEcharts.option({
    tooltip: {
      formatter: (p) =>
        p.name === 'ת"א' && p.data.city === 'ת"א' && p.value[0] === 'ת"א'
          ? "match"
          : "miss",
    },
  });
  assert.equal(
    o.tooltip.formatter({
      name: 'ת"א',
      data: { city: 'ת"א' },
      value: ['ת"א', 1],
    }),
    "match"
  );
});

test("escaping never mutates the chart's own data objects", () => {
  const { window } = loadGovEcharts();
  const o = window.GovEcharts.option({
    tooltip: {
      formatter: (p) => p.data.gloss + p.data.nested.label + p.value[1],
    },
  });
  const item = {
    name: evil,
    gloss: evil,
    nested: { label: evil },
    when: new Date(0),
  };
  const value = [1, evil];
  const params = { name: evil, data: item, value };
  o.tooltip.formatter(params);
  assert.equal(params.name, evil);
  assert.equal(params.data, item);
  assert.equal(item.name, evil);
  assert.equal(item.gloss, evil);
  assert.equal(item.nested.label, evil);
  assert.equal(params.value, value);
  assert.equal(value[1], evil);
  assert.ok(item.when instanceof Date);
});

test("treemap/sunburst treePathInfo and treeAncestors names are escaped", () => {
  const { window } = loadGovEcharts();
  const o = window.GovEcharts.option({
    tooltip: {
      formatter: (p) =>
        p.marker +
        p.treePathInfo.map((t) => t.name).join(" / ") +
        p.treeAncestors.map((t) => t.name).join(" / "),
    },
  });
  const path = [{ name: "root" }, { name: evil, value: 3 }];
  const marker = '<span style="background:#0068f5"></span>';
  const html = o.tooltip.formatter({
    marker,
    treePathInfo: path,
    treeAncestors: path,
  });
  assert.ok(!html.includes("<img"), html);
  assert.ok(html.startsWith(marker), "ECharts marker HTML untouched");
  assert.equal(path[1].name, evil);
});
