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
const { publicResourceUrl, resourceFormat } = resourceUrlModule.exports;

// Shared with services/scanner/tests/test_models.py (the Python original).
const { vectors: resourceUrlVectors, format_vectors: formatVectors } =
  JSON.parse(
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

test("resourceFormat matches the shared vectors", () => {
  assert.ok(formatVectors.length > 10);
  for (const [format, url, expected] of formatVectors) {
    assert.equal(
      resourceFormat({ format, url }),
      expected,
      JSON.stringify([format, url])
    );
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

test("a string nested past the depth cap is escaped, not passed through", () => {
  const { window } = loadGovEcharts();
  const o = window.GovEcharts.option({
    tooltip: {
      formatter: (p) => p.data.a.b.c.d.e.f.g.label + p.data.a.b.c.d.e.f.ok,
    },
  });
  const item = {
    a: { b: { c: { d: { e: { f: { g: { label: evil }, ok: "שלום" } } } } } },
  };
  const html = o.tooltip.formatter({ data: item });
  assert.ok(!html.includes("<img"), html);
  assert.ok(html.endsWith("שלום"), "clean strings past the cap survive");
  assert.equal(item.a.b.c.d.e.f.g.label, evil, "chart data not mutated");
});

test("a clean subtree past the depth cap is returned as is", () => {
  const { window } = loadGovEcharts();
  let seen;
  const o = window.GovEcharts.option({
    tooltip: {
      formatter: (p) => {
        seen = p.data.a.b.c.d.e;
        return "";
      },
    },
  });
  const deep = { f: { g: "clean" } };
  o.tooltip.formatter({ data: { a: { b: { c: { d: { e: deep } } } } } });
  assert.equal(seen, deep);
});

test("a cyclic subtree past the cap that holds a < or > fails closed", () => {
  const { window } = loadGovEcharts();
  let seen = "unset";
  const o = window.GovEcharts.option({
    tooltip: {
      formatter: (p) => {
        seen = p.data.a.b.c.d.e;
        return "";
      },
    },
  });
  const cyc = { label: evil };
  cyc.self = cyc;
  o.tooltip.formatter({ data: { a: { b: { c: { d: { e: cyc } } } } } });
  assert.equal(seen, null);
});

test("tooltips under tree data[].children[] and series levels[] are wrapped", () => {
  const { window, captured } = loadGovEcharts();
  const chart = window.echarts.init({});
  const f = (p) => p.name;
  chart.setOption({
    series: [
      {
        type: "treemap",
        levels: [{ tooltip: { formatter: f } }, {}],
        data: [
          {
            name: "a",
            tooltip: { formatter: f },
            children: [
              {
                name: "b",
                children: [{ name: "c", tooltip: { formatter: f } }],
              },
            ],
          },
        ],
      },
    ],
  });
  const s = captured[0].series[0];
  for (const fn of [
    s.levels[0].tooltip.formatter,
    s.data[0].tooltip.formatter,
    s.data[0].children[0].children[0].tooltip.formatter,
  ]) {
    assert.equal(fn({ name: evil }), "&lt;img src=x onerror=alert(1)&gt;");
  }
});

test("a cyclic children tree does not hang the belt", () => {
  const { window, captured } = loadGovEcharts();
  const chart = window.echarts.init({});
  const node = { name: "x", tooltip: { formatter: (p) => p.name } };
  node.children = [node];
  chart.setOption({ series: [{ type: "tree", data: [node] }] });
  assert.equal(
    captured[0].series[0].data[0].tooltip.formatter({ name: "<b>" }),
    "&lt;b&gt;"
  );
});

test("a clean cyclic subtree past the cap is returned as is", () => {
  const { window } = loadGovEcharts();
  let seen;
  const o = window.GovEcharts.option({
    tooltip: {
      formatter: (p) => {
        seen = p.data.a.b.c.d.e;
        return "";
      },
    },
  });
  const cyc = { label: "נקי" };
  cyc.self = cyc;
  o.tooltip.formatter({ data: { a: { b: { c: { d: { e: cyc } } } } } });
  assert.equal(seen, cyc);
});

test("escaping past the cap keeps Dates, NaN and undefined as they are", () => {
  const { window } = loadGovEcharts();
  let seen;
  const o = window.GovEcharts.option({
    tooltip: {
      formatter: (p) => {
        seen = p.data.a.b.c.d.e;
        return "";
      },
    },
  });
  const when = new Date(0);
  const e = { label: evil, when, n: NaN, u: undefined };
  o.tooltip.formatter({ data: { a: { b: { c: { d: { e } } } } } });
  assert.ok(!seen.label.includes("<img"));
  assert.equal(seen.when, when);
  assert.ok(Number.isNaN(seen.n));
  assert.ok("u" in seen);
  assert.equal(e.label, evil, "chart data not mutated");
});

test("tooltips deeper than 20 tree levels are wrapped; a branching cycle is visited once", () => {
  const { window, captured } = loadGovEcharts();
  const chart = window.echarts.init({});
  const leaf = { name: "leaf", tooltip: { formatter: (p) => p.name } };
  let node = leaf;
  for (let i = 0; i < 30; i++) node = { name: "n" + i, children: [node] };
  const loop = { name: "loop", tooltip: { formatter: (p) => p.name } };
  loop.children = [loop, loop, loop, loop];
  chart.setOption({ series: [{ type: "tree", data: [node, loop] }] });
  assert.equal(leaf.tooltip.formatter({ name: "<b>" }), "&lt;b&gt;");
  assert.equal(
    captured[0].series[0].data[1].tooltip.formatter({ name: "<b>" }),
    "&lt;b&gt;"
  );
});
