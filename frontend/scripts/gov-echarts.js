// gov-echarts.js — shared ECharts palette + base config for dataset
// pages. Pre-loaded by the Nuxt dataset shell (see
// frontend/utils/dataset-libs.ts) so agent-emitted content.html can
// reference `window.GOVIL_PALETTE` / `window.GovEcharts.base` without
// redefining either in every <script> block.
//
// Mirrors the design tokens documented in the agent system prompt
// (govdata-agent.yaml). If the palette or base config changes there,
// change it here too — they're the single source of truth at runtime
// and the prompt is the contract.
;(function () {
  'use strict';

  var GOVIL_PALETTE = [
    '#0068f5', '#0b3668', '#6c9fd8', '#0053c4', '#0c3058',
    '#3d70b0', '#b7d2f7', '#2658a0', '#dbe8fb', '#0c1f3d',
  ];

  var base = {
    color: GOVIL_PALETTE,
    textStyle: { fontFamily: 'Rubik, sans-serif', color: '#0c3058' },
    tooltip: {
      textStyle: { fontFamily: 'Rubik', color: '#0c3058' },
      backgroundColor: '#fff',
      borderColor: '#c3cfe7',
      extraCssText: 'direction: rtl; box-shadow: 0 6px 24px -8px rgba(0,104,245,.18);',
    },
    grid: { left: 48, right: 64, top: 40, bottom: 48, containLabel: true },
  };

  // Belt for agent-emitted horizontal bars: ECharts label positions are
  // geometric even on RTL pages, so `position: 'left'` on a
  // category-yAxis bar chart lands the value label on top of the axis
  // category names. Already-published pages carrying that mistake are
  // corrected here at render time; new pages are blocked at build time
  // by the agent self-check (HBAR-LABEL rule in check.py).
  function fixHbarLabels(o) {
    try {
      var ys = Array.isArray(o.yAxis) ? o.yAxis : o.yAxis ? [o.yAxis] : [];
      var horizontal = ys.some(function (a) { return a && a.type === 'category'; });
      if (!horizontal || !o.series) return o;
      var ss = Array.isArray(o.series) ? o.series : [o.series];
      ss.forEach(function (s) {
        if (s && s.type === 'bar' && s.label && s.label.position === 'left') {
          s.label.position = 'right';
        }
      });
    } catch (e) { /* never break a page over a label position */ }
    return o;
  }

  // Belt #2 for agent-emitted label formatters written for raw values:
  // ECharts calls label formatters with a params OBJECT, so helpers
  // like `function numFmt(v){ return v.toLocaleString('he-IL') }`
  // passed directly render "[object Object]" on every bar. When a
  // function formatter stringifies the params object, re-call it with
  // params.value; last resort is the bare value.
  function fixLabelFormatters(o) {
    try {
      if (!o.series) return o;
      var ss = Array.isArray(o.series) ? o.series : [o.series];
      ss.forEach(function (s) {
        if (!s || !s.label || typeof s.label.formatter !== 'function') return;
        var f = s.label.formatter;
        s.label.formatter = function (p) {
          var r;
          try { r = f(p); } catch (e) { r = null; }
          if (typeof r === 'string' && r.indexOf('[object') === -1) return r;
          try {
            var r2 = f(p && p.value !== undefined ? p.value : p);
            if (typeof r2 === 'string' && r2.indexOf('[object') === -1) return r2;
          } catch (e2) { /* fall through */ }
          return p && p.value != null ? String(p.value) : '';
        };
      });
    } catch (e) { /* never break a page over a label */ }
    return o;
  }

  // Belt #3 for agent-emitted value axes pinned to a zero baseline:
  // ECharts' default for a `type: 'value'` axis forces 0 into the axis
  // extent, so series living far from zero (water levels at −210 m,
  // rates near 2.4, counters around 80 000) get ~95%+ dead space and
  // the actual variation is unreadable. When a value axis has no
  // explicit `scale`/`min`/`max` and zero sits ≥4 data-spans away from
  // the series extent, inject `scale: true` so the axis fits the data.
  // Charts whose data brackets zero (or nearly) keep the zero baseline.
  // Already-published pages are corrected here at render time; new
  // pages are steered at generation time by the VAXIS-BASELINE rule in
  // agent/system-prompt.md.
  function fixValueAxisScale(o) {
    try {
      var axes = Array.isArray(o.yAxis) ? o.yAxis : o.yAxis ? [o.yAxis] : [];
      if (!axes.length || !o.series) return o;
      var ss = Array.isArray(o.series) ? o.series : [o.series];
      axes.forEach(function (ax, i) {
        if (!ax || ax.type !== 'value') return;
        if (ax.scale === true || ax.min != null || ax.max != null) return;
        var vals = [];
        ss.forEach(function (s) {
          if (!s) return;
          var idx = s.yAxisIndex || 0;
          if (idx !== i) return;
          if (Array.isArray(s.data)) {
            s.data.forEach(function (v) {
              var n = typeof v === 'number' ? v : (v && typeof v === 'object' ? Number(v.value) : NaN);
              if (isFinite(n)) vals.push(n);
            });
          }
          // markLine thresholds also constrain the axis extent
          if (s.markLine && Array.isArray(s.markLine.data)) {
            s.markLine.data.forEach(function (ml) {
              var n = ml && typeof ml === 'object' ? Number(ml.yAxis) : NaN;
              if (isFinite(n)) vals.push(n);
            });
          }
        });
        if (vals.length < 2) return;
        var dmin = Math.min.apply(null, vals);
        var dmax = Math.max.apply(null, vals);
        var span = dmax - dmin;
        if (!(span > 0)) return;
        var dist = dmin > 0 ? dmin : (dmax < 0 ? -dmax : 0);
        if (dist >= 4 * span) ax.scale = true;
      });
    } catch (e) { /* never break a page over an axis extent */ }
    return o;
  }

  // Shallow-merge helper for the common pattern. Equivalent to
  // `Object.assign({}, base, override)` but reads better at the call
  // site: `chart.setOption(GovEcharts.option({xAxis, yAxis, series}))`.
  function option(override) {
    return Object.assign({}, base, fixValueAxisScale(fixLabelFormatters(fixHbarLabels(override || {}))));
  }

  window.GOVIL_PALETTE = GOVIL_PALETTE;
  window.GovEcharts = { base: base, option: option };
})();
