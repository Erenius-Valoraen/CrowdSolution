/* Trustify for YouTube: fact-checks videos about universities, jobs, housing and the cost of living, government policy,
   and official data, and shows what was said next to what the data says, just above the comments. It only talks to the
   Trustify API; no keys live here. */
'use strict';

const API = 'https://trustifyapp.vercel.app';
const CACHE_MS = 24 * 60 * 60 * 1000;
const CACHE_VERSION = 'v2';
const PANEL_ID = 'trustify-panel';
const ROWS_SHOWN = 5;

// Never check these, whatever the title says.
const BLOCKED_CATEGORIES = new Set(['Gaming', 'Music', 'Sports', 'Comedy', 'Film & Animation', 'Pets & Animals',
  'Autos & Vehicles', 'Travel & Events', 'Howto & Style']);
// Specific phrases only: a lone "major", "degrees", or "budget" shows up in too many unrelated videos.
const TOPICS = [
  ['universities', /\b(universit(?:y|ies)|colleges?|campus|tuition|admissions?|acceptance rates?|college majors?|majors in|choosing a major|(?:college|university|bachelor'?s|master'?s) degrees?|degree programs?|student loans?|student debt|scholarships?|grad(?:uate)? school|ivy league|fafsa|osap|co-?op|internships?|computer science|engineering school|med(?:ical)? school|law school|uoft|uwaterloo|ubc|mcgill|harvard|stanford|massachusetts institute of technology|ucla|berkeley|ut austin)\b/gi],
  ['jobs', /\b(jobs? reports?|employment|unemployment|job market|hiring|layoffs?|salar(?:y|ies)|wages?|payrolls?|careers?|recruit(?:er|ers|ing|ment)|labou?r market|minimum wage|job offers?|six figures|entry[- ]level jobs?|paychecks?)\b/gi],
  ['housing', /\b(rent(?:al|als|ing|s)?|housing|landlords?|tenants?|apartments?|mortgages?|home prices?|house prices?|real estate|evictions?|sublets?|roommates?|home ?owners?hip)\b/gi],
  ['cost of living', /\b(cost of living|groceries|grocery (?:prices?|bills?|stores?)|food prices?|gas prices?|inflation|cpi|consumer price index|affordab(?:le|ility)|price increases?|prices (?:are|went|keep) (?:up|rising|higher)|shrinkflation|recession|the economy|economic|gdp|interest rates?|mortgage rates?|living paycheck to paycheck)\b/gi],
  ['official data', /\b(statistics canada|statcan|bureau of labor statistics|\bbls\b|census|government data|official (?:data|numbers|statistics|figures)|federal reserve|bank of canada|jobs report|cpi report|labou?r force survey|new data|data (?:shows?|released)|according to (?:the )?(?:government|data|statistics))\b/gi],
  ['policy', /\b(government|public policy|housing policy|immigration|study permits?|student visas?|legislation|federal budget|carbon tax|tax (?:credits?|cuts?|hikes?|brackets?)|student loan forgiveness|welfare|social security|benefits? cuts?)\b/gi],
];
const NEWS_CATEGORIES = new Set(['News & Politics', 'Education', 'Nonprofits & Activism']);

const SEVERITY = { red_flag: 4, caution: 3, unverified: 2, info: 1, ok: 0 };
const STATUS = {
  red_flag: ['Red flag', 'red'], caution: ['Doesn’t match', 'yellow'], ok: ['Checks out', 'green'],
  info: ['Related data', 'blue'], unverified: ['Unconfirmed', 'gray'],
};
const VERDICT = {
  'HIGH RISK': ['High risk', 'red'], 'BE CAREFUL': ['Be careful', 'yellow'], 'NO RED FLAGS FOUND': ['No red flags', 'green'],
  "COULDN'T VERIFY": ["Couldn't verify", 'gray'], 'NOTHING TO CHECK': ['Nothing to check', 'gray'],
};
const LOGO = '<svg viewBox="0 0 32 32" aria-hidden="true"><g transform="rotate(-8 16 16)"><path fill="currentColor" d="M8.5 3.5h15a2 2 0 0 1 2 2V27l-2.9 2.4-2.9-2.4-2.9 2.4-2.9-2.4-2.9 2.4-2.9-2.4V5.5a2 2 0 0 1 2-2z"/><path d="M11 15.5l3.6 3.6 6.9-7.6" fill="none" stroke="var(--trustify-check)" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/></g></svg>';

const CSS = `
:host { display: block; margin: 12px 0 24px; --trustify-check: var(--yt-spec-base-background, #fff); }
.card { font-family: "Roboto", "Arial", sans-serif; font-size: 14px; line-height: 20px; color: var(--yt-spec-text-primary, #0f0f0f);
  background: var(--yt-spec-badge-chip-background, rgba(0, 0, 0, 0.05)); border-radius: 12px; padding: 12px 16px 8px; }
.head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 8px; font-size: 16px; line-height: 22px; font-weight: 500; }
.brand svg { width: 20px; height: 20px; flex: none; }
.kicker { color: var(--yt-spec-text-secondary, #606060); font-weight: 400; }
.pill { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: 8px; font-size: 12px; font-weight: 500; line-height: 18px; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.muted { color: var(--yt-spec-text-secondary, #606060); }
.meta { color: var(--yt-spec-text-secondary, #606060); margin-top: 4px; }
.bar { display: flex; gap: 2px; height: 4px; border-radius: 2px; overflow: hidden; margin: 10px 0; }
.bar span { height: 100%; }
.stats { display: flex; flex-wrap: wrap; gap: 8px 20px; margin: 8px 0 4px; }
.stat b { display: block; font-size: 20px; line-height: 26px; font-weight: 500; }
.stat span { font-size: 12px; color: var(--yt-spec-text-secondary, #606060); }
.message { margin: 6px 0 2px; }
.rows { list-style: none; margin: 8px 0 0; padding: 0; }
.row { display: grid; grid-template-columns: 52px minmax(0, 1fr); gap: 2px 12px; padding: 12px 0; border-top: 1px solid var(--yt-spec-10-percent-layer, rgba(0, 0, 0, 0.1)); }
.time { align-self: start; justify-self: start; font: 500 12px/20px "Roboto", "Arial", sans-serif; color: var(--yt-spec-call-to-action, #065fd4); background: none; border: 0; padding: 0; cursor: pointer; }
.time:hover { text-decoration: underline; }
.status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--yt-spec-text-secondary, #606060); }
.title { font-weight: 500; overflow-wrap: anywhere; }
.quote { font-style: italic; color: var(--yt-spec-text-secondary, #606060); overflow-wrap: anywhere; margin-top: 2px; }
.cmp { display: grid; gap: 6px; margin: 8px 0 6px; max-width: 560px; }
.cmp-row { display: grid; grid-template-columns: minmax(96px, 30%) minmax(60px, 1fr) auto; gap: 10px; align-items: center; font-size: 12px; line-height: 16px; }
.cmp-label { color: var(--yt-spec-text-secondary, #606060); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cmp-track { height: 8px; border-radius: 4px; overflow: hidden; background: var(--yt-spec-10-percent-layer, rgba(0, 0, 0, 0.1)); }
.cmp-fill { height: 100%; border-radius: 4px; background: var(--tone); }
.cmp-value { font-weight: 500; font-variant-numeric: tabular-nums; white-space: nowrap; }
.cmp-note { font-size: 12px; color: var(--yt-spec-text-secondary, #606060); }
.pair { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 2px 10px; margin: 8px 0 6px; font-size: 13px; max-width: 640px; }
.pair dt { color: var(--yt-spec-text-secondary, #606060); }
.pair dd { margin: 0; overflow-wrap: anywhere; }
.pair dd.strong { font-weight: 500; }
.detail { color: var(--yt-spec-text-secondary, #606060); overflow-wrap: anywhere; }
.sources { color: var(--yt-spec-text-secondary, #606060); font-size: 12px; margin-top: 2px; }
.button { font: 500 14px/36px "Roboto", "Arial", sans-serif; height: 36px; padding: 0 16px; margin: 8px 8px 4px 0; border: 0; border-radius: 18px; cursor: pointer;
  color: var(--yt-spec-text-primary, #0f0f0f); background: var(--yt-spec-10-percent-layer, rgba(0, 0, 0, 0.05)); }
.button:hover { background: var(--yt-spec-20-percent-layer, rgba(0, 0, 0, 0.1)); }
.foot { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; padding: 6px 0 4px; font-size: 12px; color: var(--yt-spec-text-secondary, #606060); }
a { color: var(--yt-spec-call-to-action, #065fd4); text-decoration: none; }
a:hover { text-decoration: underline; }
.loading { height: 4px; border-radius: 2px; margin: 10px 0 6px; position: relative; overflow: hidden; background: var(--yt-spec-10-percent-layer, rgba(0, 0, 0, 0.1)); }
.loading::after { content: ""; position: absolute; inset: 0; width: 30%; border-radius: 2px; background: var(--yt-spec-call-to-action, #065fd4); animation: slide 1.4s ease-in-out infinite; }
@keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(340%); } }
@media (prefers-reduced-motion: reduce) { .loading::after { animation: none; width: 100%; opacity: 0.4; } }
.red { --tone: #e5484d; } .yellow { --tone: #f2a100; } .green { --tone: #2bb673; } .blue { --tone: #3e8ed0; } .gray { --tone: #909090; }
.pill { background: color-mix(in srgb, var(--tone) 18%, transparent); }
.dot, .bar span { background: var(--tone); }
`;

let run = null;       // { videoId, controller, timer }

// ---------- helpers ----------

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {  // nested arrays, e.g. [dt, dd] pairs, must become nodes, not text
    if (child == null || child === false || child === '') continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const log = (...args) => console.debug('[Trustify]', ...args);
const sentences = (text, count = 2) => String(text || '').split(/(?<=[.!?])\s+/).slice(0, count).join(' ').slice(0, 280);

function currentVideoId() {
  return location.pathname === '/watch' ? new URLSearchParams(location.search).get('v') : null;
}

/** First number in a figure like "+172,000 jobs", "4.3%", or "158.8 million jobs". */
function parseNumber(text) {
  const s = String(text || '');
  const m = s.replace(/,/g, '').match(/[-+]?\d*\.?\d+/);
  if (!m) return null;
  let n = parseFloat(m[0]);
  if (/trillion/i.test(s)) n *= 1e12;
  else if (/billion/i.test(s)) n *= 1e9;
  else if (/million/i.test(s)) n *= 1e6;
  else if (/\d\s*k\b/i.test(s)) n *= 1e3;
  return n;
}

function formatValue(value, unit) {
  const u = String(unit || '').toLowerCase();
  const n = Math.abs(value) >= 1000 ? Math.round(value).toLocaleString('en-US') : value.toLocaleString('en-US', { maximumFractionDigits: 2 });
  if (u.includes('percent') || u === '%') return `${n}%`;
  if (['usd', 'cad', 'dollars', '$', 'usd_month', 'usd_hour'].includes(u)) return `$${n}${u === 'usd_month' ? '/mo' : u === 'usd_hour' ? '/hr' : ''}`;
  return `${n}${u ? ` ${unit}` : ''}`;
}

// ---------- is this video worth checking? ----------

async function readVideoDetails(videoId, signal) {
  const res = await fetch(`/watch?v=${encodeURIComponent(videoId)}`, { signal, credentials: 'same-origin' });
  const html = await res.text();
  const marker = 'ytInitialPlayerResponse = ';
  let player = null;
  const start = html.indexOf(marker);
  if (start >= 0) {
    const from = start + marker.length;
    try { player = JSON.parse(html.slice(from, html.indexOf(';</script>', from))); } catch { player = null; }
  }
  const details = player?.videoDetails || {};
  return {
    title: details.title || document.title.replace(/ - YouTube$/, ''),
    description: details.shortDescription || '',
    keywords: details.keywords || [],
    category: player?.microformat?.playerMicroformatRenderer?.category || '',
  };
}

function relevance({ title, description, keywords, category }) {
  if (BLOCKED_CATEGORIES.has(category)) return { relevant: false, category };
  const topics = new Map();
  const score = (text, weight) => {
    for (const [topic, pattern] of TOPICS) {
      const matches = String(text).match(pattern);
      if (matches) topics.set(topic, (topics.get(topic) || 0) + new Set(matches.map((m) => m.toLowerCase())).size * weight);
    }
  };
  score(title, 4);
  score(keywords.join(' '), 2);
  score(description.slice(0, 2000), 1);
  let total = [...topics.values()].reduce((a, b) => a + b, 0);
  if (total && NEWS_CATEGORIES.has(category)) total += 1;
  return { relevant: total >= 4, category, score: total, topics: [...topics.keys()] };
}

// ---------- API and cache ----------

async function verifyVideo(videoId, signal) {
  const limit = AbortSignal.any ? AbortSignal.any([signal, AbortSignal.timeout(300000)]) : signal;
  const res = await fetch(`${API}/api/verify`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: limit,
    body: JSON.stringify({ text: `https://www.youtube.com/watch?v=${videoId}`, offline: false }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail ? String(body.detail) : `The check failed (${res.status}).`);
  if (body.video) body.video.transcript = [];  // not shown here, and it keeps the cache small
  return body;
}

async function readCache(videoId) {
  const key = `check:${CACHE_VERSION}:${videoId}`;
  const saved = (await chrome.storage.local.get(key))[key];
  return saved && Date.now() - saved.at < CACHE_MS ? saved.data : null;
}

const writeCache = (videoId, data) => chrome.storage.local.set({ [`check:${CACHE_VERSION}:${videoId}`]: { at: Date.now(), data } });

// ---------- said vs actual ----------

function bars(rows, note) {
  const top = Math.max(...rows.map((r) => Math.abs(r.value)), 0) || 1;
  return el('div', { class: 'cmp' },
    rows.map((r) => el('div', { class: 'cmp-row' },
      el('span', { class: 'cmp-label', title: r.label }, r.label),
      el('span', { class: 'cmp-track' }, el('span', { class: `cmp-fill ${r.tone}`, style: `display:block;width:${Math.max(3, (100 * Math.abs(r.value)) / top)}%` })),
      el('span', { class: 'cmp-value' }, r.display))),
    note ? el('div', { class: 'cmp-note' }, note) : null);
}

function pair(rows) {
  const items = rows.filter(([, value]) => value);
  if (!items.length) return null;
  return el('dl', { class: 'pair' }, items.map(([label, value, strong]) => [el('dt', {}, label), el('dd', { class: strong ? 'strong' : '' }, value)]));
}

/** What the video said next to what the data says: bars when the numbers are comparable, otherwise two lines. */
function comparison(f) {
  const d = f.data || {};
  const tone = (STATUS[f.status] || STATUS.unverified)[1];

  if (d.claimed_value != null && d.found_value != null) {
    const diff = d.claimed_value && d.found_value ? ((d.claimed_value - d.found_value) / Math.abs(d.found_value)) * 100 : null;
    const note = diff != null && Math.abs(diff) >= 1 ? `Said is ${Math.abs(diff).toFixed(Math.abs(diff) < 10 ? 1 : 0)}% ${diff > 0 ? 'higher' : 'lower'} than the sources.` : null;
    return bars([
      { label: 'Said in the video', value: d.claimed_value, display: formatValue(d.claimed_value, d.unit), tone: 'gray' },
      { label: `Sources${d.as_of ? ` (${d.as_of})` : ''}`, value: d.found_value, display: formatValue(d.found_value, d.unit), tone },
    ], note);
  }

  if (d.type === 'statistic' && d.figures) {
    const figs = d.figures;
    const rows = [['when_said', 'Official when said'], ['revised', 'Revised since'], ['latest', 'Latest']]
      .filter(([key]) => figs[key] && parseNumber(figs[key].value) != null)
      .map(([key, label]) => ({ label: `${label} (${figs[key].period})`, value: parseNumber(figs[key].value), display: figs[key].value, tone: key === 'when_said' ? tone : 'blue' }));
    const said = parseNumber(f.quote);
    const reference = rows[0]?.value;
    if (said != null && reference && Math.abs(said) / Math.abs(reference) > 0.2 && Math.abs(said) / Math.abs(reference) < 5) {
      rows.unshift({ label: 'Said in the video', value: said, display: String(f.quote).match(/[-+$]?\d[\d,.]*\s*(?:%|percent|million|billion|k\b)?/i)?.[0] || String(said), tone: 'gray' });
    }
    if (rows.length) return bars(rows, `${d.label} · ${d.agency}`);
  }

  if (['rent', 'wage', 'savings_rate', 'loan_rate', 'credit_card_rate'].includes(d.type) && d.amount != null && d.benchmark != null) {
    return bars([
      { label: d.type === 'rent' ? 'This listing' : 'Said', value: d.amount, display: formatValue(d.amount, d.unit), tone },
      { label: d.benchmark_label || 'Typical', value: d.benchmark, display: formatValue(d.benchmark, d.unit), tone: 'gray' },
    ]);
  }

  if (d.claim?.claimed || d.claim?.official) return pair([['Said', d.claim.claimed], [d.claim.label ? `Official (${d.claim.label})` : 'Official', d.claim.official, true]]);
  if (d.claimed || d.found) return pair([['Said', d.claimed], [`Sources say${d.as_of ? ` (${d.as_of})` : ''}`, d.found, true]]);
  return null;
}

// ---------- panel ----------

function createPanel(anchor) {
  document.getElementById(PANEL_ID)?.remove();
  const host = el('div', { id: PANEL_ID });
  const root = host.attachShadow({ mode: 'open' });
  root.append(el('style', {}, CSS));
  const card = el('section', { class: 'card', 'aria-label': 'Trustify fact check', 'aria-live': 'polite' });
  root.append(card);
  if (anchor.id === 'below') anchor.append(host);
  else anchor.parentElement.insertBefore(host, anchor);
  return card;
}

function header(extra) {
  const brand = el('div', { class: 'brand' });
  brand.innerHTML = LOGO;  // fixed markup above, never page or API text
  brand.append('Trustify', el('span', { class: 'kicker' }, '· Fact check'));
  return el('div', { class: 'head' }, brand, extra);
}

function renderLoading(card) {
  const started = Date.now();
  const meta = el('div', { class: 'meta' });
  const tick = () => { meta.textContent = `Checking every claim in this video against official data and the web. This takes about a minute (${Math.round((Date.now() - started) / 1000)}s).`; };
  tick();
  run.timer = setInterval(tick, 1000);
  card.replaceChildren(header(), meta, el('div', { class: 'loading', role: 'progressbar', 'aria-label': 'Checking' }));
}

function renderError(card, message, retry) {
  card.replaceChildren(header(), el('div', { class: 'meta' }, `Couldn't check this video: ${message}`),
    el('button', { class: 'button', type: 'button', onclick: retry }, 'Try again'));
}

function seek(seconds) {
  const video = document.querySelector('video.html5-main-video') || document.querySelector('video');
  if (!video) return;
  video.currentTime = seconds;
  video.play?.();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function row(f) {
  const [label, tone] = STATUS[f.status] || STATUS.unverified;
  const d = f.data || {};
  const sites = [...new Set((d.sources || []).map((s) => s.site).filter(Boolean)
    .concat((f.evidence || []).filter((e) => e.kind === 'official').map((e) => e.source.split(' (')[0])))].slice(0, 3);
  const explanation = d.type === 'web' ? sentences(f.summary, 2) : sentences(f.summary, 1);
  return el('li', { class: 'row' },
    f.seconds != null ? el('button', { class: 'time', type: 'button', title: 'Jump to this moment', onclick: () => seek(f.seconds) }, f.timestamp) : el('span'),
    el('div', {},
      el('div', { class: 'status' }, el('span', { class: `dot ${tone}` }), label, d.search_rounds === 2 ? ' · searched twice' : ''),
      el('div', { class: 'title' }, f.title.replace(/^Web check:\s*/, '')),
      f.quote ? el('div', { class: 'quote' }, `“${f.quote}”`) : null,
      comparison(f),
      explanation ? el('div', { class: 'detail' }, explanation) : null,
      sites.length ? el('div', { class: 'sources' }, `Sources: ${sites.join(' · ')}`) : null));
}

function renderResult(card, data) {
  const [label, tone] = VERDICT[data.overall] || VERDICT["COULDN'T VERIFY"];
  const counts = data.counts || {};
  const findings = [...(data.findings || [])].sort((a, b) =>
    SEVERITY[b.status] - SEVERITY[a.status] || (a.seconds ?? 1e9) - (b.seconds ?? 1e9));
  const compared = findings.filter((f) => comparison(f)).length;
  const webSources = new Set(findings.flatMap((f) => (f.data?.sources || []).map((s) => s.site)).filter(Boolean)).size;
  const bar = el('div', { class: 'bar', 'aria-hidden': 'true' }, ['red_flag', 'caution', 'ok', 'info', 'unverified']
    .filter((key) => counts[key]).map((key) => el('span', { class: STATUS[key][1], style: `flex: ${counts[key]}` })));
  const stat = (value, words, toneClass) => el('div', { class: 'stat' }, el('b', {}, toneClass ? [el('span', { class: `dot ${toneClass}`, style: 'display:inline-block;margin-right:6px;vertical-align:middle' }), value] : value), el('span', {}, words));
  const list = el('ul', { class: 'rows' });
  let expanded = false;
  const toggle = el('button', { class: 'button', type: 'button' });
  const draw = () => {
    list.replaceChildren(...(expanded ? findings : findings.slice(0, ROWS_SHOWN)).map(row));
    toggle.textContent = expanded ? 'Show fewer' : `Show all ${findings.length} claims`;
    toggle.hidden = findings.length <= ROWS_SHOWN;
  };
  toggle.addEventListener('click', () => { expanded = !expanded; draw(); });
  draw();
  const published = data.video?.upload_date ? ` as of when it was published (${data.video.upload_date})` : '';
  card.replaceChildren(
    header(el('span', { class: `pill ${tone}` }, el('span', { class: `dot ${tone}` }), label)),
    el('div', { class: 'stats' },
      stat(counts.total || 0, 'claims checked'),
      counts.ok ? stat(counts.ok, 'check out', 'green') : null,
      counts.caution || counts.red_flag ? stat((counts.caution || 0) + (counts.red_flag || 0), "don't match", counts.red_flag ? 'red' : 'yellow') : null,
      counts.info ? stat(counts.info, 'related data', 'blue') : null,
      counts.unverified ? stat(counts.unverified, 'unconfirmed', 'gray') : null,
      stat(compared, 'compared with data'),
      webSources ? stat(webSources, 'web sources') : null),
    bar,
    el('div', { class: 'message' }, data.overall_badge?.message || ''),
    list,
    toggle,
    el('div', { class: 'foot' }, el('span', {}, `Checked against official data and web sources${published}.`),
      el('a', { href: API, target: '_blank', rel: 'noopener noreferrer' }, 'Open Trustify')));
}

// ---------- flow ----------

function cleanup() {
  if (run) {
    run.controller.abort();
    clearInterval(run.timer);
  }
  run = null;
  document.getElementById(PANEL_ID)?.remove();
}

async function waitForAnchor(signal) {
  for (let i = 0; i < 60 && !signal.aborted; i += 1) {
    const comments = document.querySelector('ytd-watch-flexy #below ytd-comments#comments');
    if (comments?.parentElement) return comments;
    await sleep(500);
  }
  return document.querySelector('ytd-watch-flexy #below');
}

async function check(force = false) {
  const videoId = currentVideoId();
  if (!videoId) { cleanup(); return; }
  if (!force && run?.videoId === videoId) return;
  cleanup();
  const controller = new AbortController();
  const { signal } = controller;
  run = { videoId, controller, timer: 0 };
  try {
    const { enabled = true } = await chrome.storage.local.get('enabled');
    if (!force && !enabled) return;
    if (!force) {
      const verdict = relevance(await readVideoDetails(videoId, signal));
      log('relevance', verdict);
      if (!verdict.relevant) return;
    }
    const anchor = await waitForAnchor(signal);
    if (signal.aborted || !anchor) return;
    const card = createPanel(anchor);
    const cached = force ? null : await readCache(videoId);
    if (cached) { renderResult(card, cached); return; }
    renderLoading(card);
    const data = await verifyVideo(videoId, signal);
    clearInterval(run?.timer);
    if (signal.aborted) return;
    await writeCache(videoId, data);
    renderResult(card, data);
  } catch (err) {
    if (signal.aborted || err.name === 'AbortError') return;
    clearInterval(run?.timer);
    const card = document.getElementById(PANEL_ID)?.shadowRoot?.querySelector('.card');
    if (card) renderError(card, err.name === 'TimeoutError' ? 'it took too long. Try again.' : err.message, () => check(true));
  }
}

document.addEventListener('yt-navigate-finish', () => check());
chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message?.type === 'trustify:check-now') { check(true); reply({ started: Boolean(currentVideoId()) }); }
});
check();
