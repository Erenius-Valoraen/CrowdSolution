/* Trustify web app: sends text to /api/verify and renders the report by evidence type. See docs/FRONTEND_GUIDE.md. */
'use strict';

const $ = (selector) => document.querySelector(selector);

const STATUS = {
  red_flag: { label: 'Red flag', tone: 'tone-red', color: 'var(--red)' },
  caution: { label: 'Caution', tone: 'tone-yellow', color: 'var(--yellow)' },
  ok: { label: 'Checks out', tone: 'tone-green', color: 'var(--green)' },
  info: { label: 'Context', tone: 'tone-blue', color: 'var(--blue)' },
  unverified: { label: 'Unconfirmed', tone: 'tone-gray', color: 'var(--gray)' },
};
const SEVERITY = { red_flag: 4, caution: 3, unverified: 2, info: 1, ok: 0 };
const OVERALL = {
  'HIGH RISK': { tone: 'tone-red', title: 'High risk', icon: 'alert' },
  'BE CAREFUL': { tone: 'tone-yellow', title: 'Be careful', icon: 'question' },
  'NO RED FLAGS FOUND': { tone: 'tone-green', title: 'No red flags found', icon: 'check' },
  "COULDN'T VERIFY": { tone: 'tone-gray', title: "Couldn't verify", icon: 'minus' },
  'NOTHING TO CHECK': { tone: 'tone-gray', title: 'Nothing to check', icon: 'minus' },
};
const KIND_LABEL = { official: 'Official data', guidance: 'Official guidance', web: 'Web', community: 'Student reports', ai: 'AI reading' };
const DOMAIN_RESULTS = {
  official: ['tone-green', 'is one of its official domains'],
  free_email: ['tone-red', "is a free personal email, not the organization's own domain"],
  lookalike: ['tone-red', 'imitates the name but is not an official domain'],
  lookalike_unknown: ['tone-yellow', "contains the name, but we can't confirm who owns it"],
  brand_match: ['tone-yellow', "matches the name but isn't in our records (probably official, type it yourself)"],
  unrelated: ['tone-yellow', 'has no visible connection to this organization'],
  owned_by_other: ['tone-yellow', 'belongs to a different company'],
};
const LOADING_STEPS = [
  [0, 'Reading the text…'],
  [2500, 'Checking official data…'],
  [5500, 'Checking what other students reported…'],
  [8500, 'Searching the web for the rest…'],
  [25000, 'Still searching the web, almost there…'],
];
const VIDEO_LOADING_STEPS = [
  [0, 'Getting the video transcript…'],
  [3000, 'Reading what the video says…'],
  [15000, 'Checking official data…'],
  [22000, 'Checking what other students reported…'],
  [28000, 'Searching the web for the rest…'],
  [60000, 'Still working through the video, almost there…'],
];
const SERIES = ['tone-series-0', 'tone-series-1', 'tone-series-2', 'tone-series-3'];
// Same rule as the API: a message that is only a YouTube link gets its transcript checked.
const YOUTUBE_LINK = /^\s*(?:https?:\/\/)?(?:www\.|m\.|music\.)?(?:youtube\.com\/(?:watch\?\S*?v=|shorts\/|embed\/|live\/)|youtu\.be\/)[A-Za-z0-9_-]{11}\S*\s*$/i;
const isYouTubeLink = (text) => YOUTUBE_LINK.test(text || '');

let currentVideo = null;

const els = {
  form: $('#check-form'), text: $('#text'), count: $('#char-count'), web: $('#web'), submit: $('#submit'), videoHint: $('#video-hint'),
  examples: $('#examples'), loading: $('#loading'), loadingText: $('#loading-text'), loadingHint: $('#loading-hint'), error: $('#error'),
  results: $('#results'), historyBtn: $('#history-btn'), drawer: $('#history'), historyList: $('#history-list'),
  closeHistory: $('#close-history'), scrim: $('#scrim'), loadingSteps: $('#loading-steps'),
};

// ---------- formatting ----------

const fmt = {
  money: (v) => (v == null ? '–' : `$${Math.round(v).toLocaleString('en-US')}`),
  compactMoney: (v) => (v == null ? '–' : v >= 1000 ? `$${(v / 1000).toFixed(v >= 100000 ? 0 : 1)}k` : `$${Math.round(v)}`),
  pct: (v) => (v == null ? '–' : `${Math.round(v * 100)}%`),
  num: (v) => (v == null ? '–' : Math.round(v).toLocaleString('en-US')),
  unit(v, unit) {
    if (v == null) return '–';
    if (unit === 'percent') return `${v.toFixed(2)}%`;
    if (unit === 'usd_hour') return `$${v.toFixed(2)}/hr`;
    if (unit === 'usd_month') return `$${Math.round(v).toLocaleString('en-US')}/mo`;
    return fmt.money(v);
  },
};

function titleCase(text) {
  return String(text || '').toLowerCase().replace(/(^|\s)\S/g, (c) => c.toUpperCase()).replace("'S", "'s");
}

function timeAgo(iso) {
  const then = new Date(String(iso).replace(' ', 'T') + (String(iso).includes('Z') || String(iso).includes('+') ? '' : 'Z'));
  const secs = Math.max(0, (Date.now() - then.getTime()) / 1000);
  if (Number.isNaN(secs)) return '';
  if (secs < 60) return 'just now';
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)} hr ago`;
  return then.toLocaleDateString();
}

function parseFigure(text) {
  if (!text) return null;
  const s = String(text);
  const m = s.replace(/,/g, '').match(/[-+]?\d*\.?\d+/);
  if (!m) return null;
  let n = parseFloat(m[0]);
  if (/trillion/i.test(s)) n *= 1e12;
  else if (/billion/i.test(s)) n *= 1e9;
  else if (/million/i.test(s)) n *= 1e6;
  return n;
}

function shortName(name) {
  const known = {
    'Massachusetts Institute of Technology': 'MIT',
    'The University of Texas at Austin': 'UT Austin',
    'University of California-Los Angeles': 'UCLA',
    'University of California-Berkeley': 'UC Berkeley',
  };
  if (known[name]) return known[name];
  return String(name || '').replace(/^The /, '').replace(/University/g, 'U.').replace(/Institute of Technology/g, 'Inst. of Tech.');
}

function formatDate(iso) {
  const [y, m, d] = String(iso || '').split('-').map(Number);
  if (!y || !m || !d) return iso || '';
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** A play-icon "3:15" link that opens the video at the moment a finding was said. */
function timeLink(seconds, label) {
  if (!currentVideo || seconds == null) return null;
  return h('a', { class: 'time-link', href: `${currentVideo.url}?t=${Math.floor(seconds)}`, target: '_blank', rel: 'noopener noreferrer', title: 'Watch this part', 'aria-label': `Watch at ${label}` }, icon('play'), label);
}

function checkedDate(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function mainDomains(domains, limit = 3) {
  const plain = (domains || []).filter((d) => d.split('.').length === 2);
  return (plain.length ? plain : domains || []).slice(0, limit);
}

// ---------- building blocks ----------

const badge = (status) => h('span', { class: `badge ${STATUS[status]?.tone || 'tone-gray'}` }, STATUS[status]?.label || status);
const quote = (text) => (text ? h('blockquote', { class: 'quote' }, `“${text}”`) : null);
const stat = (value, label, tone) => h('div', { class: 'stat' }, h('div', { class: `stat-value ${tone || ''}` }, value), h('div', { class: 'stat-label' }, label));

function sourceLinks(sources) {
  const list = (sources || []).filter((s) => s.url);
  if (!list.length) return null;
  return h('ul', { class: 'source-links' }, list.slice(0, 4).map((s) =>
    h('li', {}, h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title && s.title !== 'Web source cited by the search' ? s.title : new URL(s.url).hostname))));
}

function evidenceList(evidence) {
  const items = (evidence || []).filter((e) => e && (e.source || e.detail));
  if (!items.length) return null;
  return h('details', { class: 'evidence' },
    h('summary', {}, `Sources (${items.length})`),
    h('ul', {}, items.map((e) => h('li', {},
      h('span', { class: `kind kind-${e.kind}` }, KIND_LABEL[e.kind] || e.kind),
      h('div', { class: 'evidence-body' },
        e.url ? h('a', { href: e.url, target: '_blank', rel: 'noopener noreferrer' }, e.source) : h('strong', {}, e.source),
        e.detail && e.detail !== 'Web source cited by the search' ? h('div', { class: 'muted small' }, e.detail) : null)))));
}

function card(f, { title, summary = true, extraEvidence = [] } = {}, ...body) {
  return h('article', { class: `card ${STATUS[f.status]?.tone || ''}` },
    h('header', { class: 'card-head' }, badge(f.status), h('h3', { class: 'card-title' }, title || f.title), timeLink(f.seconds, f.timestamp)),
    quote(f.quote),
    ...body,
    summary && f.summary ? h('p', { class: 'card-summary' }, f.summary) : null,
    evidenceList([...(f.evidence || []), ...extraEvidence]));
}

function section(id, title, subtitle, ...body) {
  const content = body.flat().filter(Boolean);
  if (!content.length) return null;
  // A wrapper with no cards inside (like an empty .grid) doesn't count as content.
  if (content.every((node) => node instanceof Element && node.classList.contains('grid') && !node.children.length)) return null;
  return h('section', { class: 'panel', id: `section-${id}`, 'aria-labelledby': `h-${id}` },
    h('div', { class: 'panel-head' }, h('h2', { id: `h-${id}` }, title), subtitle && h('p', { class: 'muted' }, subtitle)),
    ...content);
}

// ---------- sections ----------

function hero(data, text, speakerEl) {
  const meta = OVERALL[data.overall] || OVERALL["COULDN'T VERIFY"];
  const counts = data.counts || {};
  const segments = ['red_flag', 'caution', 'ok', 'info', 'unverified'].map((k) => ({ label: STATUS[k].label, value: counts[k] || 0, color: STATUS[k].color }));
  const evidence = (data.findings || []).flatMap((f) => f.evidence || []);
  const sources = new Set(evidence.map((e) => e.url || e.source));
  const official = evidence.filter((e) => e.kind === 'official').length;
  const reports = (data.findings || []).filter((f) => f.checker === 'community').reduce((sum, f) => sum + (f.data?.reports || 0), 0);
  const tiles = [
    [counts.total || 0, 'things checked'],
    [counts.red_flag || 0, 'red flags', counts.red_flag ? 'tone-red' : ''],
    [official, 'official data points'],
    [reports || sources.size, reports ? 'earlier student reports' : 'sources'],
  ];
  return h('section', { class: `hero ${meta.tone}` },
    data.video ? videoBlock(data.video) : null,
    h('div', { class: 'hero-main' },
      h('div', { class: 'hero-kicker' }, 'Verdict', checkedDate(data.created_at) ? ` · checked ${checkedDate(data.created_at)}` : ''),
      h('h2', { class: 'hero-title' }, h('span', { class: 'hero-icon' }, icon(meta.icon)), meta.title),
      h('p', { class: 'hero-message' }, data.overall_badge?.message || ''),
      data.summary && h('p', { class: 'hero-summary' }, data.summary),
      speakerEl,
      h('div', { class: 'tiles' }, tiles.map(([v, l, tone]) => stat(fmt.num(v), l, tone)))),
    h('div', { class: 'hero-chart' },
      Charts.donut(segments, { centerValue: String(counts.total || 0), centerLabel: counts.total === 1 ? 'finding' : 'findings' }),
      h('div', { class: 'legend legend-stack' }, segments.filter((s) => s.value).map((s) =>
        h('span', { class: 'legend-item' }, h('i', { class: 'legend-dot', style: { background: s.color } }), `${s.label}`, h('strong', {}, s.value))))),
    text && !data.video ? h('details', { class: 'pasted' }, h('summary', {}, 'What you pasted'), h('p', {}, text)) : null);
}

function videoBlock(v) {
  const covered = v.duration ? Math.min(100, (100 * (v.checked_until || 0)) / v.duration) : 100;
  const meta = [v.channel, v.upload_date && `published ${formatDate(v.upload_date)}`, v.duration_label,
    v.auto_captions == null ? null : v.auto_captions ? 'auto-generated captions' : 'creator captions'].filter(Boolean).join(' · ');
  return h('div', { class: 'video' },
    h('a', { class: 'video-thumb', href: v.url, target: '_blank', rel: 'noopener noreferrer', 'aria-label': 'Watch on YouTube' },
      h('img', { src: v.thumbnail, alt: '', loading: 'lazy' }), h('span', { class: 'video-play' }, icon('play'))),
    h('div', { class: 'video-meta' },
      h('div', { class: 'hero-kicker' }, 'YouTube video'),
      h('h3', { class: 'video-title' }, h('a', { href: v.url, target: '_blank', rel: 'noopener noreferrer' }, v.title || v.url)),
      h('div', { class: 'muted small' }, meta),
      h('div', { class: 'progress-line' }, Charts.progress(covered, 'tone-blue'),
        h('span', { class: 'small' }, v.fully_checked ? 'Checked the whole video' : `Checked the first ${v.checked_until_label} of ${v.duration_label}`)),
      h('div', { class: 'muted small' }, 'Claims are judged against what official data showed when the video was published.')));
}

function timelineSection(data) {
  const v = data.video;
  const timed = (data.findings || []).filter((f) => f.seconds != null).sort((a, b) => a.seconds - b.seconds || SEVERITY[b.status] - SEVERITY[a.status]);
  if (!v || !timed.length) return null;
  const duration = v.duration || Math.max(...timed.map((f) => f.seconds)) || 1;
  const at = (s) => `${Math.min(100, (100 * s) / duration)}%`;
  const ticks = [0, duration / 4, duration / 2, (3 * duration) / 4, duration];
  const fmtTime = (s) => { const t = Math.floor(s); return t >= 3600 ? `${Math.floor(t / 3600)}:${String(Math.floor(t / 60) % 60).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}` : `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
  return section('timeline', 'Timeline', 'Where each claim comes up in the video. Click a marker to watch that moment.',
    h('div', { class: 'timeline' },
      h('div', { class: 'timeline-track' },
        h('div', { class: 'timeline-checked', style: { width: at(v.checked_until || duration) }, title: 'Part of the video we checked' }),
        timed.map((f) => h('a', {
          class: `timeline-marker ${STATUS[f.status].tone}`, style: { left: at(f.seconds) }, href: `${v.url}?t=${Math.floor(f.seconds)}`,
          target: '_blank', rel: 'noopener noreferrer', title: `${f.timestamp} · ${STATUS[f.status].label}: ${f.title}`, 'aria-label': `${f.timestamp}: ${f.title}`,
        }))),
      h('div', { class: 'timeline-axis muted small' }, ticks.map((s) => h('span', { style: { left: at(s) } }, fmtTime(s))))),
    h('ol', { class: 'timeline-list' }, timed.map((f) => h('li', {},
      timeLink(f.seconds, f.timestamp), badge(f.status),
      h('div', { class: 'timeline-text' }, h('strong', {}, f.title.replace(/^Web check:\s*/, '')), f.quote ? h('div', { class: 'muted small' }, `“${f.quote}”`) : null)))));
}

function transcriptSection(data) {
  const v = data.video;
  if (!v?.transcript?.length) return null;
  const timed = (data.findings || []).filter((f) => f.seconds != null);
  const lines = v.transcript;
  const worstAt = (i) => {
    const start = lines[i].seconds;
    const end = i + 1 < lines.length ? lines[i + 1].seconds : Infinity;
    const hits = timed.filter((f) => f.seconds >= start && f.seconds < end);
    return hits.length ? hits.reduce((a, b) => (SEVERITY[b.status] > SEVERITY[a.status] ? b : a)).status : null;
  };
  const firstUnchecked = lines.findIndex((l) => !l.checked);
  const rows = lines.map((line, i) => {
    const status = worstAt(i);
    return [
      i === firstUnchecked ? h('li', { class: 'transcript-divider muted small' }, `Not checked after ${v.checked_until_label}`) : null,
      h('li', { class: `transcript-line${status ? ` is-flagged ${STATUS[status].tone}` : ''}${line.checked ? '' : ' is-unchecked'}` },
        timeLink(line.seconds, line.timestamp), h('span', {}, line.text)),
    ];
  });
  return section('transcript', 'Transcript', `${v.auto_captions ? 'Auto-generated captions' : 'Captions'} from YouTube. Highlighted lines are where claims were checked.`,
    h('details', { class: 'transcript' }, h('summary', {}, `Show transcript (${lines.length} lines)`), h('ol', { class: 'transcript-lines' }, rows)));
}

function notices(data) {
  const busy = (data.notes || []).some((n) => n.startsWith("Web search hit Groq's rate limit"));
  return busy ? h('div', { class: 'alert tone-yellow' }, "Web search is busy right now, so some claims couldn't be checked online. Official data and student reports were still checked.") : null;
}

function communitySection(fs) {
  if (!fs.length) return null;
  const matchText = { exact: 'Same contact details', same_message: 'Almost identical message', similar: 'Similar message' };
  return section('community', 'Reported by other students', 'Scams other students already checked here', h('div', { class: 'grid' }, fs.map((f) => {
    const d = f.data || {};
    return card(f, { summary: false },
      h('div', { class: 'stats' },
        stat(fmt.num(d.reports || 1), d.reports === 1 ? 'earlier report' : 'earlier reports', STATUS[f.status].tone),
        stat(matchText[d.match] || 'Match', 'match type', 'stat-value-sm'),
        d.last_seen && stat(d.last_seen, 'last reported', 'stat-value-sm')),
      d.matched?.length ? h('div', { class: 'chips' }, d.matched.map((m) => h('span', { class: `chip ${STATUS[f.status].tone}` }, `${m.kind}: ${m.value}`))) : null,
      d.summary && h('p', { class: 'muted' }, h('strong', {}, 'That report: '), d.summary),
      d.red_flags?.length ? h('div', { class: 'chips' }, d.red_flags.slice(0, 5).map((r) => h('span', { class: 'chip' }, r))) : null);
  })));
}

function patternsSection(fs) {
  if (!fs.length) return null;
  const sorted = [...fs].sort((a, b) => SEVERITY[b.status] - SEVERITY[a.status]);
  return section('patterns', 'Warning signs', 'Tactics scammers commonly use, as described by consumer protection agencies',
    h('div', { class: 'grid' }, sorted.map((f) => card(f, { summary: false }, h('p', {}, f.data?.explanation || f.summary)))));
}

function orgsSection(fs) {
  if (!fs.length) return null;
  const groups = new Map();
  for (const f of fs) {
    if (!groups.has(f.id)) groups.set(f.id, []);
    groups.get(f.id).push(f);
  }
  const cards = [...groups.values()].map((group) => {
    const top = group.reduce((a, b) => (SEVERITY[b.status] > SEVERITY[a.status] ? b : a));
    const named = group.find((f) => f.checker !== 'web') || group[0];
    const name = named.title.replace(/^Web check:\s*/, '').split(':')[0];
    const rows = [];
    const row = (label, ...content) => rows.push(h('dt', {}, label), h('dd', {}, ...content));
    for (const f of group) {
      const d = f.data || {};
      if (['bank', 'company', 'adviser', 'charity'].includes(d.type)) {
        let registered = d.registered_name || 'No matching company on record';
        if (d.type === 'bank') registered = `${d.registered_name} · ${d.entity_type} · FDIC #${d.fdic_cert || '–'} · ${d.active ? 'active' : 'no longer active'}`;
        if (d.type === 'adviser') registered = `${d.registered_name} · SEC registration: ${d.status}`;
        if (d.type === 'charity') registered = `${d.registered_name} · EIN ${d.ein} · latest filing ${d.tax_year}`;
        row('Registered as', registered);
        if (d.official_domains?.length) row('Official websites', h('div', { class: 'chips' }, mainDomains(d.official_domains).map((x) => h('span', { class: 'chip tone-green' }, x))));
        if (d.claimed_domain && DOMAIN_RESULTS[d.domain_result]) {
          const [tone, words] = DOMAIN_RESULTS[d.domain_result];
          row('This message uses', h('span', { class: `chip ${tone}` }, d.claimed_domain), ' ', h('span', { class: 'muted' }, words));
        }
      } else if (d.type === 'complaints') {
        row('Complaints', h('div', { class: 'complaints' },
          h('div', {}, h('strong', { class: 'big-inline' }, fmt.num(d.complaints)), h('span', { class: 'muted' }, ` in the year to ${d.period_end}`)),
          h('div', { class: 'progress-line' }, Charts.progress(d.timely_pct, d.timely_pct >= 90 ? 'tone-green' : 'tone-red'), h('span', { class: 'small' }, `${d.timely_pct}% answered on time`)),
          h('div', { class: 'muted small' }, `Most common issue: ${d.top_issue}`)));
      } else if (f.checker === 'web') {
        row('Online', h('div', {}, f.summary, sourceLinks(d.sources)));
      }
    }
    return h('article', { class: `card ${STATUS[top.status].tone}` },
      h('header', { class: 'card-head' }, badge(top.status), h('h3', { class: 'card-title' }, name)),
      rows.length ? h('dl', { class: 'rows' }, rows) : null,
      h('p', { class: 'card-summary' }, top.summary),
      evidenceList(group.flatMap((f) => f.evidence || [])));
  });
  return section('orgs', "Who's behind it", 'Official registries, website checks, and complaint records', h('div', { class: 'grid' }, cards));
}

function pricesSection(fs) {
  if (!fs.length) return null;
  const cards = fs.map((f) => {
    const d = f.data || {};
    const tone = STATUS[f.status].tone;
    if (['rent', 'wage', 'savings_rate', 'loan_rate', 'credit_card_rate'].includes(d.type)) {
      let headline;
      let caption;
      if (d.type === 'rent') { headline = `${Math.round(d.ratio * 100)}%`; caption = 'of the typical rent'; }
      else if (d.type === 'wage') { headline = `${d.ratio.toFixed(1)}×`; caption = 'the average hourly pay'; }
      else { const diff = d.amount - d.benchmark; headline = `${diff >= 0 ? '+' : ''}${diff.toFixed(2)} pts`; caption = 'vs the benchmark rate'; }
      return card(f, {},
        h('div', { class: 'compare' },
          stat(headline, caption, tone),
          Charts.hbars([
            { label: d.type === 'rent' ? 'This listing' : 'This offer', value: d.amount, display: fmt.unit(d.amount, d.unit), tone },
            { label: d.benchmark_label, value: d.benchmark, display: fmt.unit(d.benchmark, d.unit), tone: 'tone-neutral' },
          ], { stacked: true })));
    }
    if (d.type === 'rent_trend') {
      return card(f, { summary: false },
        h('div', { class: 'compare' }, stat(`${d.change_pct > 0 ? '+' : ''}${d.change_pct.toFixed(1)}%`, `rent change in ${d.province} over a year`, 'tone-blue'),
          h('p', { class: 'muted' }, `Statistics Canada rent index, ${d.month}. The listed price itself is checked on the web.`)));
    }
    return card(f, {}, webFigures(f), siteChips(d.sources));
  });
  return section('prices', 'Is the price normal?', 'Compared with what is typical, from official data', h('div', { class: 'grid' }, cards));
}

const SCHOOL_METRICS = [
  { key: 'admission_rate', label: 'Admission rate', fmt: fmt.pct },
  { key: 'graduation_rate', label: 'Graduation rate', fmt: fmt.pct },
  { key: 'tuition_in_state', label: 'In-state tuition', fmt: fmt.money },
  { key: 'tuition_out_of_state', label: 'Out-of-state tuition', fmt: fmt.money },
  { key: 'net_price', label: 'Average net price after aid', fmt: fmt.money },
  { key: 'earnings_10yr', label: 'Median earnings, 10 years after starting', fmt: fmt.money },
  { key: 'median_debt', label: 'Median debt at graduation', fmt: fmt.money },
  { key: 'undergrads', label: 'Undergraduates', fmt: fmt.num },
  { key: 'research_works', label: 'Research papers', fmt: fmt.num },
  { key: 'h_index', label: 'Research h-index', fmt: fmt.num },
];
const CLAIM_KEY = {
  admission_rate: 'admission_rate', tuition_in_state: 'tuition_in_state', tuition_out_of_state: 'tuition_out_of_state',
  net_price: 'net_price', graduation_rate: 'graduation_rate', median_earnings_10yr: 'earnings_10yr',
  median_debt: 'median_debt', undergrad_enrollment: 'undergrads',
};

function schoolsSection(fs) {
  if (!fs.length) return null;
  const schools = new Map();
  const programs = new Map();
  const claimed = new Map();
  for (const f of fs) {
    const d = f.data || {};
    for (const s of d.schools || []) {
      const merged = schools.get(s.name) || {};
      for (const [k, v] of Object.entries(s)) if (v != null) merged[k] = v;
      schools.set(s.name, merged);
    }
    for (const p of d.programs || []) programs.set(`${p.school}|${p.program}|${p.credential}`, p);
    if (d.claim && CLAIM_KEY[d.claim.metric]) claimed.set(CLAIM_KEY[d.claim.metric], d.claim.result);
  }
  const list = [...schools.values()];
  const metrics = SCHOOL_METRICS.filter((m) => list.some((s) => s[m.key] != null));
  const parts = [];

  if (list.length >= 2) {
    parts.push(h('div', { class: 'chart-grid' }, metrics.map((m) => h('div', { class: `mini-chart${claimed.has(m.key) ? ` is-claimed ${STATUS[claimed.get(m.key)]?.tone}` : ''}` },
      h('div', { class: 'mini-title' }, m.label, claimed.has(m.key) ? h('span', { class: `chip small ${STATUS[claimed.get(m.key)]?.tone}` }, 'mentioned') : null),
      Charts.hbars(list.map((s, i) => ({ label: shortName(s.name), value: s[m.key] ?? null, display: s[m.key] == null ? 'not reported' : m.fmt(s[m.key]), tone: SERIES[i % SERIES.length] })))))));
  } else if (list.length === 1) {
    const s = list[0];
    parts.push(h('div', { class: 'school-head' }, h('h3', {}, s.name), h('span', { class: 'muted' }, [s.city, s.state].filter(Boolean).join(', ') || (s.country ? '' : 'Research data only'))),
      h('div', { class: 'stats stats-wrap' }, metrics.map((m) => stat(m.fmt(s[m.key]), m.label, claimed.has(m.key) ? STATUS[claimed.get(m.key)]?.tone : ''))));
  }

  if (list.length >= 2) {
    parts.push(h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, h('th', {}, ''), list.map((s) => h('th', {}, s.name, h('div', { class: 'muted small' }, [s.city, s.state].filter(Boolean).join(', ')))))),
      h('tbody', {}, metrics.map((m) => h('tr', { class: claimed.has(m.key) ? `is-claimed ${STATUS[claimed.get(m.key)]?.tone}` : '' },
        h('th', { scope: 'row' }, m.label), list.map((s) => h('td', {}, m.fmt(s[m.key]))))))),
    ));
  }

  if (programs.size) {
    const progs = [...programs.values()];
    parts.push(h('div', { class: 'subpanel' },
      h('h3', {}, 'What graduates earn'),
      Charts.columns(progs.map((p) => ({ label: `${shortName(p.school)} · ${p.program}`, values: { a: p.earnings_1yr, b: p.earnings_4yr, c: p.earnings_5yr } })),
        [{ key: 'a', label: '1 year after', tone: 'tone-series-0' }, { key: 'b', label: '4 years after', tone: 'tone-series-1' }, { key: 'c', label: '5 years after', tone: 'tone-series-2' }],
        { format: fmt.compactMoney }),
      h('div', { class: 'table-wrap' }, h('table', { class: 'table table-compact' },
        h('thead', {}, h('tr', {}, ['School', 'Major', 'Degree', 'Graduates', 'Median debt'].map((c) => h('th', {}, c)))),
        h('tbody', {}, progs.map((p) => h('tr', {}, h('td', {}, p.school), h('td', {}, p.program), h('td', {}, p.credential),
          h('td', {}, p.graduates == null ? '–' : fmt.num(p.graduates)), h('td', {}, fmt.money(p.median_debt)))))))));
  }

  const rows = fs.map((f) => {
    const c = f.data?.claim;
    let checked = f.title;
    let claimedText = '–';
    let actual = f.summary;
    if (f.checker === 'web') { checked = 'Online sources'; claimedText = f.data?.claimed || '–'; actual = f.data?.found || f.summary; }
    else if (c) { checked = c.label; claimedText = c.claimed; actual = c.official; }
    else if (f.data?.opinion) { checked = 'This is an opinion'; actual = 'Compare the numbers above'; }
    else { actual = String(f.summary || '').split('. College Scorecard')[0]; }
    return h('tr', {}, h('td', {}, badge(f.status)), h('td', { class: 'quote-cell' }, f.quote ? `“${f.quote}”` : ''), h('td', {}, checked),
      h('td', { class: 'num' }, claimedText), h('td', { class: 'num strong' }, actual));
  });
  parts.push(h('div', { class: 'subpanel' }, h('h3', {}, 'What was claimed'),
    h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, ['', 'What it said', 'Checked', 'Claimed', 'Actual'].map((c) => h('th', {}, c)))),
      h('tbody', {}, rows)))));

  const webSources = fs.filter((f) => f.checker === 'web').flatMap((f) => f.evidence || []);
  const allEvidence = fs.flatMap((f) => f.evidence || []);
  const seen = new Set();
  const unique = allEvidence.filter((e) => { const k = `${e.source}|${e.detail}`; if (seen.has(k)) return false; seen.add(k); return true; });
  parts.push(evidenceList(unique.length ? unique : webSources));

  return section('schools', 'Schools and majors', 'US Department of Education College Scorecard and OpenAlex research data', parts);
}

function statsSection(fs) {
  if (!fs.length) return null;
  const cards = fs.map((f) => {
    const d = f.data || {};
    const figs = d.figures || {};
    const cols = [['when_said', 'When it was said'], ['today', "Today's data"], ['revised', 'Revised since'], ['latest', 'Latest']].filter(([k]) => figs[k]);
    const changed = figs.revised && figs.when_said && figs.revised.value !== figs.when_said.value;
    return card(f, { summary: false },
      h('div', { class: 'muted small' }, `${d.label} · ${d.agency}`),
      h('div', { class: `verdict-line ${STATUS[f.status].tone}` }, titleCase(d.verdict)),
      Charts.hbars(cols.map(([k, label]) => ({
        label: `${label} (${figs[k].period})`, value: parseFigure(figs[k].value), display: figs[k].value,
        tone: k === 'revised' && changed ? 'tone-yellow' : k === 'when_said' ? STATUS[f.status].tone : 'tone-neutral',
      })), { stacked: true }),
      changed ? h('p', { class: 'callout tone-yellow' }, `Revised from ${figs.when_said.value} to ${figs.revised.value} after it was said.`) : null,
      h('p', { class: 'card-summary' }, f.summary));
  });
  return section('stats', 'Official numbers', 'What the government had published when it was said, and what it says now', h('div', { class: 'grid' }, cards));
}

const WEB_TONE = { red_flag: 'tone-red', caution: 'tone-yellow', ok: 'tone-green', info: 'tone-blue', unverified: '' };
// Web checks that found something worth showing; the rest belong under "Couldn't confirm".
const webAnswered = (f) => f.status !== 'unverified' || Boolean(f.data?.found);

function webNumber(value, unit) {
  const u = String(unit || '').toLowerCase();
  if (u.includes('percent') || u === '%') return `${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}%`;
  if (['usd', 'cad', 'dollars', '$'].includes(u)) return `$${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  return `${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}${u ? ` ${unit}` : ''}`;
}

/** Claimed vs found online: bars when both are comparable numbers, otherwise two figure tiles. */
function webFigures(f) {
  const d = f.data || {};
  if (!d.found && !d.claimed) return null;
  const tone = WEB_TONE[f.status] || '';
  const asOf = d.as_of ? ` (${d.as_of})` : '';
  if (d.claimed_value != null && d.found_value != null) {
    return h('div', { class: 'web-figures' },
      Charts.hbars([
        { label: 'Claimed', value: d.claimed_value, display: webNumber(d.claimed_value, d.unit), tone: 'tone-neutral' },
        { label: `Found online${asOf}`, value: d.found_value, display: webNumber(d.found_value, d.unit), tone: tone || 'tone-blue' },
      ], { stacked: true }),
      d.found ? h('div', { class: 'muted small' }, d.found) : null);
  }
  if ((d.claimed || '').length > 40 || (d.found || '').length > 40) {
    // Sentences read better as labeled rows than as big figure tiles.
    return h('dl', { class: 'rows rows-stacked' },
      d.claimed ? [h('dt', {}, 'Claimed'), h('dd', {}, d.claimed)] : null,
      d.found ? [h('dt', {}, `Found online${asOf}`), h('dd', { class: 'strong' }, d.found)] : null);
  }
  return h('div', { class: 'stats' },
    d.claimed ? stat(d.claimed, 'claimed', 'stat-value-sm') : null,
    d.found ? stat(d.found, `found online${asOf}`, `stat-value-sm ${tone}`) : null);
}

function siteChips(sources) {
  const list = (sources || []).filter((s) => s.url);
  if (!list.length) return null;
  return h('div', { class: 'chips' }, list.map((s) => h('a', {
    class: 'chip chip-link', href: s.url, target: '_blank', rel: 'noopener noreferrer', title: s.title || s.url,
  }, s.site || new URL(s.url).hostname)));
}

function webSection(fs) {
  if (!fs.length) return null;
  const sorted = [...fs].sort((a, b) => SEVERITY[b.status] - SEVERITY[a.status] || (a.seconds ?? 0) - (b.seconds ?? 0));
  return section('web', 'Checked online', 'Figures from web sources, judged as of when it was said. Open the sources before you rely on them.',
    h('div', { class: 'grid' }, sorted.map((f) => card(f, { title: f.title.replace(/^Web check:\s*/, '') }, webFigures(f), siteChips(f.data?.sources)))));
}

function unconfirmedSection(fs) {
  if (!fs.length) return null;
  return section('unconfirmed', "Couldn't confirm", 'We found no reliable record of these, so check them yourself',
    h('ul', { class: 'plain-list' }, fs.map((f) => h('li', {}, timeLink(f.seconds, f.timestamp), badge(f.status), h('span', { class: 'quote-inline' }, `“${f.quote || f.title}”`)))));
}

function checklistSection(items) {
  if (!items?.length) return null;
  return section('checklist', 'What to do next', null,
    h('ul', { class: 'checklist' }, items.map((item, i) => h('li', {},
      h('input', { type: 'checkbox', id: `todo-${i}` }), h('label', { for: `todo-${i}` }, item)))));
}

function renderReport(data, text) {
  stopSpeaking();
  currentVideo = data.video || null;
  const speakerEl = speakerPanel(data);
  const findings = data.findings || [];
  const by = (...names) => findings.filter((f) => names.includes(f.checker));
  const web = (...kinds) => findings.filter((f) => f.checker === 'web' && kinds.includes(f.kind));
  const nav = [
    ['timeline', 'Timeline', currentVideo ? findings.filter((f) => f.seconds != null) : []],
    ['community', 'Student reports', by('community')], ['patterns', 'Warning signs', by('patterns')],
    ['orgs', "Who's behind it", [...by('registry', 'reputation'), ...web('entity')]], ['prices', 'Prices', [...by('benchmark'), ...web('price')]],
    ['schools', 'Schools', [...by('college'), ...web('school')]], ['stats', 'Official numbers', by('statistic')],
    ['web', 'Checked online', web('claim', 'statistic').filter(webAnswered)],
    ['unconfirmed', 'Unconfirmed', [...by('router'), ...web('claim', 'statistic').filter((f) => !webAnswered(f))]],
  ].filter(([, , list]) => list.length);

  const menu = nav.length > 1 ? h('nav', { class: 'jump', 'aria-label': 'Jump to section' }, nav.map(([id, label, list]) =>
    h('a', { href: `#section-${id}` }, label, h('span', { class: 'count' }, list.length)))) : null;
  els.results.replaceChildren(...[
    hero(data, text, speakerEl),
    notices(data),
    menu,
    timelineSection(data),
    communitySection(by('community')),
    patternsSection(by('patterns')),
    orgsSection([...by('registry', 'reputation'), ...web('entity')]),
    pricesSection([...by('benchmark'), ...web('price')]),
    schoolsSection([...by('college'), ...web('school')]),
    statsSection(by('statistic')),
    webSection(web('claim', 'statistic').filter(webAnswered)),
    unconfirmedSection([...by('router'), ...web('claim', 'statistic').filter((f) => !webAnswered(f))]),
    checklistSection(data.action_checklist),
    transcriptSection(data),
  ].filter(Boolean));
  els.results.hidden = false;
  revealOnScroll(els.results);
  trackSections(menu);
  els.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ---------- motion and navigation ----------

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
let revealObserver = null;
let sectionObserver = null;

/** Fade sections and cards in as they scroll into view, staggered within each group. */
function revealOnScroll(root) {
  if (reducedMotion.matches || !('IntersectionObserver' in window)) return;
  revealObserver?.disconnect();
  let observerAlive = false;
  revealObserver = new IntersectionObserver((entries) => {
    observerAlive = true;
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add('is-visible');
      revealObserver.unobserve(entry.target);
    }
  }, { rootMargin: '0px 0px -6% 0px' });
  root.querySelectorAll('.hero, .panel, .card, .mini-chart').forEach((el) => {
    el.classList.add('reveal');
    el.style.setProperty('--i', String([...el.parentElement.children].indexOf(el) % 6));
    revealObserver.observe(el);
  });
  // The observer reports every target right away. If it never does (some embedded or background views don't
  // render), show everything rather than leave the results invisible.
  setTimeout(() => {
    if (!observerAlive) root.querySelectorAll('.reveal').forEach((el) => el.classList.add('is-visible'));
  }, 1200);
}

/** Underline the section-menu link for whichever section is in the middle of the screen. */
function trackSections(menu) {
  sectionObserver?.disconnect();
  if (!menu || !('IntersectionObserver' in window)) return;
  const links = new Map([...menu.querySelectorAll('a')].map((a) => [a.getAttribute('href').slice(1), a]));
  sectionObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      links.forEach((a) => a.removeAttribute('aria-current'));
      const active = links.get(entry.target.id);
      if (!active) continue;
      active.setAttribute('aria-current', 'true');
      menu.scrollTo({ left: active.offsetLeft - 16, behavior: reducedMotion.matches ? 'auto' : 'smooth' });
    }
  }, { rootMargin: '-40% 0px -55% 0px' });
  links.forEach((_, id) => {
    const target = document.getElementById(id);
    if (target) sectionObserver.observe(target);
  });
}

// ---------- API ----------

let loadingTimers = [];

/** The checklist of stages under the loading headline: done, current, or still to come. */
function renderSteps(stages, current) {
  els.loadingSteps.replaceChildren(...stages.map((message, i) => {
    const state = i < current ? 'done' : i === current ? 'current' : 'pending';
    return h('li', { 'data-state': state },
      h('span', { class: 'step-mark' }, state === 'done' ? icon('check') : null),
      message.replace(/…$/, ''),
      h('span', { class: 'sr-only' }, state === 'done' ? ' (done)' : state === 'current' ? ' (in progress)' : ''));
  }));
}

function setLoading(on) {
  loadingTimers.forEach(clearTimeout);
  loadingTimers = [];
  els.loading.hidden = !on;
  els.submit.disabled = on || !els.text.value.trim();
  els.form.setAttribute('aria-busy', on ? 'true' : 'false');
  if (on) {
    const video = isYouTubeLink(els.text.value);
    els.loadingHint.textContent = video ? 'Videos take longer: up to about two minutes.' : 'Web search can take up to a minute.';
    els.loadingHint.hidden = !els.web.checked && !video;
    const all = video ? VIDEO_LOADING_STEPS : LOADING_STEPS;
    const steps = els.web.checked ? all : all.filter(([, message]) => !message.includes('web') && !message.startsWith('Still'));
    const stages = steps.map(([, message]) => message).filter((message) => !message.startsWith('Still'));
    els.loadingText.textContent = steps[0][1];
    renderSteps(stages, 0);
    steps.forEach(([delay, message]) => loadingTimers.push(setTimeout(() => {
      els.loadingText.textContent = message;
      if (!message.startsWith('Still')) renderSteps(stages, stages.indexOf(message));
    }, delay)));
    els.loading.scrollIntoView({ behavior: reducedMotion.matches ? 'auto' : 'smooth', block: 'nearest' });
  }
}

function showError(message) {
  els.error.textContent = message;
  els.error.hidden = !message;
}

async function verify() {
  const text = els.text.value.trim();
  if (!text) return;
  showError('');
  els.results.hidden = true;
  stopSpeaking();
  setLoading(true);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), isYouTubeLink(text) ? 300000 : 180000);
  try {
    const res = await fetch('/api/verify', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, offline: !els.web.checked }), signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail ? String(data.detail) : `Something went wrong (${res.status}).`);
    renderReport(data, text);
    history.replaceState(null, '', `?scan=${encodeURIComponent(data.id)}`);
    loadHistory();
  } catch (err) {
    showError(err.name === 'AbortError' ? 'That took too long. Try again, or turn off web search for a faster check.' : `Couldn't check this: ${err.message}`);
  } finally {
    clearTimeout(timeout);
    setLoading(false);
  }
}

async function loadScan(id) {
  showError('');
  try {
    const res = await fetch(`/api/scans/${encodeURIComponent(id)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Not found');
    renderReport(data, null);
    history.replaceState(null, '', `?scan=${encodeURIComponent(id)}`);
  } catch (err) {
    showError(`Couldn't open that check: ${err.message}`);
  }
}

async function loadExamples() {
  try {
    const res = await fetch('/api/examples');
    const examples = await res.json();
    const kind = { housing: 'Housing', job: 'Jobs', school: 'Schools', finance: 'Money', video: 'Video' };
    els.examples.replaceChildren(...examples.map((ex) => h('button', {
      type: 'button', class: 'chip chip-button', title: ex.text,
      onclick: () => { els.text.value = ex.text; onInput(); els.text.focus(); },
    }, h('span', { class: 'chip-kind' }, kind[ex.category] || ex.category), ex.title)));
  } catch {
    els.examples.replaceChildren();
  }
}

async function loadHistory() {
  try {
    const res = await fetch('/api/history?limit=30');
    const items = await res.json();
    if (!items.length) {
      els.historyList.replaceChildren(h('p', { class: 'muted' }, 'No checks yet.'));
      return;
    }
    const tone = { red: 'tone-red', yellow: 'tone-yellow', green: 'tone-green', gray: 'tone-gray' };
    els.historyList.replaceChildren(...items.map((item) => h('button', {
      type: 'button', class: 'history-item',
      onclick: () => { closeHistory(); loadScan(item.id); },
    },
    h('span', { class: `badge ${tone[item.overall_color] || 'tone-gray'}` }, titleCase(item.overall)),
    h('span', { class: 'history-snippet' }, item.text_snippet),
    h('span', { class: 'muted small' }, `${item.context} · ${item.findings_count} findings · ${timeAgo(item.created_at)}`))));
  } catch {
    els.historyList.replaceChildren(h('p', { class: 'muted' }, "Couldn't load history."));
  }
}

// ---------- voice typing ----------
// Record with the browser, transcribe on the server (Groq Whisper), and put the words in the textbox. Nothing is sent to be checked.

const MAX_RECORDING_MS = 120000;
const voice = { recorder: null, stream: null, chunks: [], startedAt: 0, timer: 0, hideTimer: 0, audioCtx: null, raf: 0, cancelled: false };
const voiceEls = {
  mic: $('#mic'), label: $('#mic .mic-label'), status: $('#voice-status'), text: $('#voice-text'), cancel: $('#voice-cancel'),
  bars: [...document.querySelectorAll('.voice-meter i')],
};

function setVoiceState(state, message = '') {
  clearTimeout(voice.hideTimer);
  const recording = state === 'recording';
  voiceEls.mic.dataset.state = state;
  voiceEls.mic.setAttribute('aria-pressed', String(recording));
  voiceEls.mic.setAttribute('aria-label', recording ? 'Stop and turn into text' : 'Voice type');
  voiceEls.label.textContent = recording ? 'Stop' : 'Speak';
  voiceEls.mic.disabled = state === 'transcribing';
  voiceEls.status.dataset.state = state;
  voiceEls.status.hidden = state === 'idle';
  voiceEls.cancel.hidden = !recording;
  voiceEls.text.textContent = message;
  if (state === 'error') voice.hideTimer = setTimeout(() => setVoiceState('idle'), 8000);
}

function recordingType() {
  return ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'].find((t) => MediaRecorder.isTypeSupported?.(t)) || '';
}

async function startRecording() {
  stopSpeaking();  // don't record the summary being read out
  try {
    voice.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (err) {
    setVoiceState('error', err.name === 'NotAllowedError'
      ? 'Microphone access is blocked. Allow it in your browser to voice type.'
      : "Couldn't find a microphone.");
    return;
  }
  const mimeType = recordingType();
  voice.recorder = new MediaRecorder(voice.stream, mimeType ? { mimeType } : undefined);
  voice.chunks = [];
  voice.cancelled = false;
  voice.recorder.ondataavailable = (e) => { if (e.data.size) voice.chunks.push(e.data); };
  voice.recorder.onstop = onRecordingStop;
  voice.recorder.start(250);
  voice.startedAt = Date.now();
  const tick = () => {
    const secs = Math.floor((Date.now() - voice.startedAt) / 1000);
    voiceEls.text.textContent = `Listening ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}. Click Stop when you're done.`;
    if (Date.now() - voice.startedAt >= MAX_RECORDING_MS) stopRecording();
  };
  setVoiceState('recording');
  tick();
  voice.timer = setInterval(tick, 250);
  startMeter(voice.stream);
}

/** Bars that move with your voice, so it's obvious the mic is hearing you. */
function startMeter(stream) {
  try {
    voice.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    voice.audioCtx.resume().catch(() => {});  // some browsers start it paused after the permission prompt
    const analyser = voice.audioCtx.createAnalyser();
    analyser.fftSize = 512;
    voice.audioCtx.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    const shape = [0.55, 0.85, 1, 0.8, 0.6];
    const draw = () => {
      analyser.getByteTimeDomainData(samples);
      let peak = 0;
      for (const s of samples) peak = Math.max(peak, Math.abs(s - 128));
      const level = Math.min(1, peak / 50);
      voiceEls.bars.forEach((bar, i) => { bar.style.transform = `scaleY(${0.2 + 0.8 * level * shape[i]})`; });
      voice.raf = requestAnimationFrame(draw);
    };
    draw();
  } catch {
    // The meter is only decoration; recording still works without it.
  }
}

function releaseMic() {
  clearInterval(voice.timer);
  cancelAnimationFrame(voice.raf);
  voice.stream?.getTracks().forEach((track) => track.stop());
  voice.stream = null;
  voice.audioCtx?.close().catch(() => {});
  voice.audioCtx = null;
}

function stopRecording(cancel = false) {
  if (voice.recorder?.state !== 'recording') return;
  voice.cancelled = cancel;
  voice.recorder.stop();
}

async function onRecordingStop() {
  releaseMic();
  const blob = new Blob(voice.chunks, { type: voice.recorder.mimeType || 'audio/webm' });
  voice.recorder = null;
  if (voice.cancelled) { setVoiceState('idle'); return; }
  if (Date.now() - voice.startedAt < 700 || blob.size < 1000) {
    setVoiceState('error', 'That was too short. Click Speak, say your question, then click Stop.');
    return;
  }
  await transcribe(blob);
}

async function transcribe(blob) {
  setVoiceState('transcribing', 'Turning your voice into text…');
  try {
    const res = await fetch('/api/transcribe', { method: 'POST', headers: { 'Content-Type': blob.type }, body: blob });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail ? String(data.detail) : `Something went wrong (${res.status}).`);
    insertAtCursor(data.text);
    setVoiceState('idle');
  } catch (err) {
    setVoiceState('error', err.message);
  }
}

function insertAtCursor(words) {
  const t = els.text;
  const start = t.selectionStart ?? t.value.length;
  const end = t.selectionEnd ?? t.value.length;
  const before = t.value.slice(0, start);
  const after = t.value.slice(end);
  const lead = before && !/\s$/.test(before) ? ' ' : '';
  const trail = after && !/^\s/.test(after) ? ' ' : '';
  t.value = `${before}${lead}${words}${trail}${after}`;
  const caret = (before + lead + words).length;
  t.focus();
  t.setSelectionRange(caret, caret);
  onInput();
}

async function initVoice() {
  if ('speechSynthesis' in window) speechSynthesis.getVoices();  // browsers load voices lazily
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return;  // e.g. old browsers or plain-http hosts
  try {
    const health = await (await fetch('/api/health')).json();
    voiceEls.mic.hidden = !health.voice_input;
  } catch {
    return;
  }
  voiceEls.mic.addEventListener('click', () => (voice.recorder ? stopRecording() : startRecording()));
  voiceEls.cancel.addEventListener('click', () => stopRecording(true));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && voice.recorder) stopRecording(true); });
}

// ---------- spoken results ----------
// Reads a short summary of the results aloud, sentence by sentence, with captions. Uses the server's natural voice
// (Groq text-to-speech) when it's enabled, otherwise the browser's built-in voice.

let serverVoice = 'unknown';  // 'yes' once /api/speak works, 'no' once it doesn't
const speaker = { token: 0, panel: null, sentences: [], index: 0, engine: null, clips: [], audio: null, finish: null, state: 'idle' };
const SPEAKER_LABELS = {
  idle: ['volume', 'Listen to a summary'], loading: [null, 'Preparing…'], playing: ['pause', 'Pause'], paused: ['play', 'Resume'],
  done: ['replay', 'Listen again'], blocked: ['play', 'Tap to listen'], error: ['replay', 'Try again'],
};
const speakerLabel = (state) => {
  const [name, text] = SPEAKER_LABELS[state];
  return name ? [icon(name), text] : [text];
};

function speakerPanel(data) {
  const panel = h('div', { class: 'speaker', 'data-state': 'idle' },
    h('button', { type: 'button', class: 'btn speaker-btn', onclick: () => onSpeakerButton(data, panel) }, speakerLabel('idle')),
    h('span', { class: 'speaker-bars', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'), h('i')),
    h('span', { class: 'speaker-status', 'aria-live': 'polite' }),
    h('button', { type: 'button', class: 'btn-link speaker-stop', hidden: true, onclick: () => stopSpeaking() }, 'Stop'),
    h('p', { class: 'speaker-caption', hidden: true }));
  return panel;
}

function setSpeaker(state, status = '') {
  const panel = speaker.panel;
  speaker.state = state;
  if (!panel) return;
  panel.dataset.state = state;
  const button = panel.querySelector('.speaker-btn');
  button.replaceChildren(...speakerLabel(state));
  button.disabled = state === 'loading';
  panel.querySelector('.speaker-status').textContent = status;
  panel.querySelector('.speaker-stop').hidden = !['playing', 'paused'].includes(state);
}

function onSpeakerButton(data, panel) {
  if (speaker.panel === panel && speaker.state === 'playing') return pauseSpeaking();
  if (speaker.panel === panel && ['paused', 'blocked'].includes(speaker.state)) return resumeSpeaking();
  return speakSummary(data, panel);
}

const splitSentences = (text) => String(text || '').split(/(?<=[.!?])\s+(?=["'A-Z0-9$])/).map((s) => s.trim()).filter(Boolean);

function highlightSentence(i) {
  speaker.panel?.querySelectorAll('.speaker-caption span').forEach((span, n) => span.classList.toggle('is-current', n === i));
}

async function speakSummary(data, panel, { auto = false } = {}) {
  stopSpeaking();
  speaker.panel = panel;
  const token = ++speaker.token;
  setSpeaker('loading', 'Writing a short spoken summary…');
  let text;
  try {
    // Send the report too: on serverless hosts the server instance that answers may not have this scan saved.
    const res = await fetch(`/api/scans/${encodeURIComponent(data.id)}/spoken-summary`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ report: data }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail ? String(body.detail) : `Something went wrong (${res.status}).`);
    text = body.text;
  } catch (err) {
    if (token === speaker.token) setSpeaker('error', `Couldn't prepare the summary: ${err.message}`);
    return;
  }
  if (token !== speaker.token) return;
  speaker.sentences = splitSentences(text);
  speaker.index = 0;
  speaker.clips = [];
  const caption = panel.querySelector('.speaker-caption');
  caption.replaceChildren(...speaker.sentences.map((s) => h('span', {}, `${s} `)));
  caption.hidden = false;
  setSpeaker('loading', 'Getting the voice ready…');
  speaker.engine = await chooseEngine();
  if (token !== speaker.token) return;
  if (!speaker.engine) {
    setSpeaker('error', "This browser can't read aloud, so here's the summary as text.");
    return;
  }
  if (speaker.engine === 'server') speaker.sentences.forEach((s, i) => { speaker.clips[i] ||= fetchClip(s); speaker.clips[i].catch(() => {}); });
  playFrom(token, auto);
}

async function fetchClip(sentence) {
  const res = await fetch('/api/speak', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: sentence }) });
  if (!res.ok) throw new Error(`voice unavailable (${res.status})`);
  return res.blob();
}

async function chooseEngine() {
  if (serverVoice === 'unknown' && speaker.sentences.length) {
    speaker.clips[0] = fetchClip(speaker.sentences[0]);
    try {
      await speaker.clips[0];
      serverVoice = 'yes';
    } catch {
      serverVoice = 'no';
    }
  }
  if (serverVoice === 'yes') return 'server';
  return 'speechSynthesis' in window ? 'browser' : null;
}

async function playFrom(token, auto = false) {
  setSpeaker('playing', auto ? 'Reading the results out loud' : 'Reading the summary');
  try {
    while (speaker.index < speaker.sentences.length) {
      if (token !== speaker.token) return;
      highlightSentence(speaker.index);
      await speakSentence(speaker.index, token);
      if (token !== speaker.token) return;  // paused or stopped: resume from this sentence
      speaker.index += 1;
    }
    highlightSentence(-1);
    speaker.index = 0;
    setSpeaker('done');
  } catch (err) {
    if (token !== speaker.token) return;
    if (err.name === 'NotAllowedError' || err.message === 'not-allowed') setSpeaker('blocked', 'Your browser needs a tap before it plays sound.');
    else setSpeaker('error', `Couldn't play the summary: ${err.message}`);
  }
}

async function speakSentence(i, token) {
  if (speaker.engine === 'server') {
    let blob = null;
    try {
      blob = await speaker.clips[i];
    } catch {
      // This sentence's audio failed; the browser voice reads it instead.
    }
    if (token !== speaker.token) return undefined;
    if (blob) return playClip(blob);
    if (!('speechSynthesis' in window)) return undefined;
  }
  return sayWithBrowser(speaker.sentences[i]);
}

function playClip(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    speaker.audio = audio;
    speaker.finish = () => { URL.revokeObjectURL(url); speaker.finish = null; speaker.audio = null; resolve(); };
    audio.onended = () => speaker.finish?.();
    audio.onerror = () => { URL.revokeObjectURL(url); reject(new Error('audio playback failed')); };
    audio.play().catch((err) => { URL.revokeObjectURL(url); reject(err); });
  });
}

function browserVoice() {
  const voices = speechSynthesis.getVoices().filter((v) => /^en[-_]/i.test(v.lang));
  for (const preferred of [/natural/i, /google us english/i, /samantha/i, /aria|jenny|guy/i]) {
    const match = voices.find((v) => preferred.test(v.name));
    if (match) return match;
  }
  return voices.find((v) => /^en[-_]us/i.test(v.lang)) || voices[0] || null;
}

function sayWithBrowser(sentence) {
  return new Promise((resolve, reject) => {
    const utterance = new SpeechSynthesisUtterance(sentence);
    const voiceChoice = browserVoice();
    if (voiceChoice) utterance.voice = voiceChoice;
    utterance.lang = voiceChoice?.lang || 'en-US';
    utterance.rate = 1.03;
    speaker.finish = () => { speaker.finish = null; resolve(); };
    utterance.onend = () => speaker.finish?.();
    utterance.onerror = (e) => (['interrupted', 'canceled'].includes(e.error) ? speaker.finish?.() : reject(new Error(e.error)));
    speechSynthesis.speak(utterance);
  });
}

/** Stop whatever is playing. Bumping the token makes any running playback loop exit. */
function haltSpeech() {
  speaker.token += 1;
  speaker.audio?.pause();
  speaker.audio = null;
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  speaker.finish?.();
  speaker.finish = null;
}

function pauseSpeaking() {
  haltSpeech();
  setSpeaker('paused', 'Paused');
}

function resumeSpeaking() {
  playFrom(++speaker.token);
}

function stopSpeaking() {
  const active = ['loading', 'playing', 'paused', 'blocked'].includes(speaker.state);
  haltSpeech();
  if (active && speaker.panel) {
    highlightSentence(-1);
    setSpeaker(speaker.sentences.length ? 'done' : 'idle');
  }
  speaker.index = 0;
}

// ---------- UI wiring ----------

function onInput() {
  const n = els.text.value.length;
  els.count.textContent = `${n.toLocaleString('en-US')} character${n === 1 ? '' : 's'}`;
  els.submit.disabled = !els.text.value.trim() || !els.loading.hidden;
  els.videoHint.hidden = !isYouTubeLink(els.text.value);
}

function openHistory() {
  els.drawer.hidden = false;
  els.scrim.hidden = false;
  els.historyBtn.setAttribute('aria-expanded', 'true');
  loadHistory();
}

function closeHistory() {
  els.drawer.hidden = true;
  els.scrim.hidden = true;
  els.historyBtn.setAttribute('aria-expanded', 'false');
}

els.text.addEventListener('input', onInput);
els.text.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); verify(); }
});
els.form.addEventListener('submit', (e) => { e.preventDefault(); verify(); });
els.historyBtn.addEventListener('click', openHistory);
els.closeHistory.addEventListener('click', closeHistory);
els.scrim.addEventListener('click', closeHistory);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !els.drawer.hidden) closeHistory(); });

loadExamples();
initVoice();
const initialScan = new URLSearchParams(location.search).get('scan');
if (initialScan) loadScan(initialScan);
