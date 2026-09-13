/* DOM helper and small dependency-free charts: HTML/CSS bars and columns, SVG donut. */
'use strict';

/** Create an element. Text children are always inserted as text, never as HTML. */
function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'style' && typeof value === 'object') Object.assign(el.style, value);
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false || child === '') continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** Inline SVG icons on a 24px grid, drawn with currentColor so they follow the text color. No emoji or symbol glyphs. */
const ICONS = {
  play: '<path d="M8 5.2v13.6L19 12z" fill="currentColor" stroke="none"/>',
  pause: '<rect x="6.5" y="5" width="3.6" height="14" rx="1" fill="currentColor" stroke="none"/><rect x="13.9" y="5" width="3.6" height="14" rx="1" fill="currentColor" stroke="none"/>',
  replay: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v4h4"/>',
  volume: '<path d="M4 9.5h3.2L12 5.5v13l-4.8-4H4z"/><path d="M15.5 9.2a4 4 0 0 1 0 5.6"/><path d="M18.2 6.6a7.6 7.6 0 0 1 0 10.8"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4.2"/><path d="M12 17.3v.2"/>',
  question: '<circle cx="12" cy="12" r="8.5"/><path d="M9.7 9.6a2.4 2.4 0 1 1 3.4 2.2c-.7.3-1.1.9-1.1 1.6v.4"/><path d="M12 16.9v.2"/>',
  minus: '<circle cx="12" cy="12" r="8.5"/><path d="M8 12h8"/>',
  external: '<path d="M9 7h8v8"/><path d="M17 7L7 17"/>',
};

function icon(name, className = '') {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  el.setAttribute('viewBox', '0 0 24 24');
  el.setAttribute('class', `icon ${className}`.trim());
  el.setAttribute('aria-hidden', 'true');
  el.setAttribute('focusable', 'false');
  el.setAttribute('fill', 'none');
  el.setAttribute('stroke', 'currentColor');
  el.setAttribute('stroke-width', '2');
  el.setAttribute('stroke-linecap', 'round');
  el.setAttribute('stroke-linejoin', 'round');
  el.innerHTML = ICONS[name] || '';  // fixed markup from ICONS above, never user text
  return el;
}

const Charts = (() => {
  const SVG_NS = 'http://www.w3.org/2000/svg';

  function svg(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
    return el;
  }

  /** segments: [{label, value, color}] */
  function donut(segments, { size = 176, thickness = 24, centerValue = '', centerLabel = '' } = {}) {
    const r = (size - thickness) / 2;
    const circumference = 2 * Math.PI * r;
    const total = segments.reduce((sum, s) => sum + (s.value || 0), 0);
    const shown = segments.filter((s) => s.value);
    const root = svg('svg', {
      viewBox: `0 0 ${size} ${size}`, class: 'donut', role: 'img',
      'aria-label': shown.map((s) => `${s.label}: ${s.value}`).join(', ') || 'No findings',
    });
    root.append(svg('circle', { cx: size / 2, cy: size / 2, r, fill: 'none', class: 'donut-track', 'stroke-width': thickness }));
    let offset = 0;
    const gap = shown.length > 1 ? 3 : 0;
    for (const s of shown) {
      const length = (circumference * s.value) / total;
      const arc = svg('circle', {
        cx: size / 2, cy: size / 2, r, fill: 'none', stroke: s.color, 'stroke-width': thickness,
        'stroke-dasharray': `${Math.max(length - gap, 0.5)} ${circumference}`, 'stroke-dashoffset': -offset,
        transform: `rotate(-90 ${size / 2} ${size / 2})`, class: 'donut-arc',
      });
      const title = svg('title');
      title.textContent = `${s.label}: ${s.value}`;
      arc.append(title);
      root.append(arc);
      offset += length;
    }
    const value = svg('text', { x: size / 2, y: size / 2 + 2, 'text-anchor': 'middle', class: 'donut-value' });
    value.textContent = centerValue;
    const label = svg('text', { x: size / 2, y: size / 2 + 24, 'text-anchor': 'middle', class: 'donut-label' });
    label.textContent = centerLabel;
    root.append(value, label);
    return root;
  }

  /** rows: [{label, value, display, tone, highlight}] */
  /** stacked: put each label on its own line above the bar, for long labels in narrow cards. */
  function hbars(rows, { max, stacked = false } = {}) {
    const top = max ?? (Math.max(0, ...rows.map((r) => Math.abs(r.value || 0))) || 1);
    return h('div', { class: `hbars${stacked ? ' hbars-stacked' : ''}` }, rows.map((r) => {
      const empty = r.value == null;
      const width = empty ? 0 : Math.max(2, (100 * Math.abs(r.value)) / top);
      return h('div', { class: `hbar-row${r.highlight ? ' is-highlight' : ''}` },
        h('div', { class: 'hbar-label', title: r.label }, r.label),
        h('div', { class: 'hbar-track' },
          h('div', { class: `hbar-fill ${r.tone || 'tone-neutral'}`, style: { width: `${width}%` } })),
        h('div', { class: `hbar-value${empty ? ' muted' : ''}` }, r.display ?? (empty ? 'not reported' : String(r.value))));
    }));
  }

  /** groups: [{label, values: {key: number|null}}], series: [{key, label, tone}] */
  function columns(groups, series, { format = String } = {}) {
    const top = Math.max(0, ...groups.flatMap((g) => series.map((s) => g.values[s.key] || 0))) || 1;
    return h('div', { class: 'columns-chart' },
      h('div', { class: 'legend' }, series.map((s) => h('span', { class: 'legend-item' }, h('i', { class: `legend-swatch ${s.tone}` }), s.label))),
      h('div', { class: 'column-groups' }, groups.map((g) => h('div', { class: 'column-group' },
        h('div', { class: 'column-bars' }, series.map((s) => {
          const v = g.values[s.key];
          const missing = v == null;
          return h('div', { class: 'column-slot', title: `${s.label}: ${missing ? 'not reported' : format(v)}` },
            h('span', { class: 'column-value' }, missing ? '–' : format(v)),
            h('div', { class: `column-bar ${s.tone}${missing ? ' is-empty' : ''}`, style: { height: `${missing ? 2 : Math.max(3, (100 * v) / top)}%` } }));
        })),
        h('div', { class: 'column-label', title: g.label }, g.label)))));
  }

  function progress(percent, tone) {
    const p = Math.max(0, Math.min(100, percent || 0));
    return h('div', { class: 'progress', role: 'progressbar', 'aria-valuenow': Math.round(p), 'aria-valuemin': 0, 'aria-valuemax': 100 },
      h('div', { class: `progress-fill ${tone}`, style: { width: `${p}%` } }));
  }

  return { donut, hbars, columns, progress };
})();
