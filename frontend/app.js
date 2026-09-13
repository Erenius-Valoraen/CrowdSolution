/* Legit Check web app: sends text to /api/verify and renders the report by evidence type. See docs/FRONTEND_GUIDE.md. */
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
  'HIGH RISK': { tone: 'tone-red', title: 'High risk', icon: '!' },
  'BE CAREFUL': { tone: 'tone-yellow', title: 'Be careful', icon: '?' },
  'NO RED FLAGS FOUND': { tone: 'tone-green', title: 'No red flags found', icon: '✓' },
  "COULDN'T VERIFY": { tone: 'tone-gray', title: "Couldn't verify", icon: '–' },
  'NOTHING TO CHECK': { tone: 'tone-gray', title: 'Nothing to check', icon: '–' },
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
const SERIES = ['tone-series-0', 'tone-series-1', 'tone-series-2', 'tone-series-3'];

const els = {
  form: $('#check-form'), text: $('#text'), count: $('#char-count'), web: $('#web'), submit: $('#submit'),
  examples: $('#examples'), loading: $('#loading'), loadingText: $('#loading-text'), loadingHint: $('#loading-hint'), error: $('#error'),
  results: $('#results'), historyBtn: $('#history-btn'), drawer: $('#history'), historyList: $('#history-list'),
  closeHistory: $('#close-history'), scrim: $('#scrim'),
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
    h('header', { class: 'card-head' }, badge(f.status), h('h3', { class: 'card-title' }, title || f.title)),
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

function hero(data, text) {
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
    h('div', { class: 'hero-main' },
      h('div', { class: 'hero-kicker' }, 'Verdict'),
      h('h2', { class: 'hero-title' }, h('span', { class: 'hero-icon', 'aria-hidden': 'true' }, meta.icon), meta.title),
      h('p', { class: 'hero-message' }, data.overall_badge?.message || ''),
      data.summary && h('p', { class: 'hero-summary' }, data.summary),
      h('div', { class: 'tiles' }, tiles.map(([v, l, tone]) => stat(fmt.num(v), l, tone)))),
    h('div', { class: 'hero-chart' },
      Charts.donut(segments, { centerValue: String(counts.total || 0), centerLabel: counts.total === 1 ? 'finding' : 'findings' }),
      h('div', { class: 'legend legend-stack' }, segments.filter((s) => s.value).map((s) =>
        h('span', { class: 'legend-item' }, h('i', { class: 'legend-dot', style: { background: s.color } }), `${s.label}`, h('strong', {}, s.value))))),
    text ? h('details', { class: 'pasted' }, h('summary', {}, 'What you pasted'), h('p', {}, text)) : null);
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
    return card(f, {}, sourceLinks(d.sources));
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
    if (f.checker === 'web') { checked = 'Online sources'; }
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
      }))),
      changed ? h('p', { class: 'callout tone-yellow' }, `Revised from ${figs.when_said.value} to ${figs.revised.value} after it was said.`) : null,
      h('p', { class: 'card-summary' }, f.summary));
  });
  return section('stats', 'Official numbers', 'What the government had published when it was said, and what it says now', h('div', { class: 'grid' }, cards));
}

function webSection(fs) {
  if (!fs.length) return null;
  return section('web', 'Other claims', 'Checked against sources found online',
    h('div', { class: 'grid' }, fs.map((f) => card(f, { title: f.title.replace(/^Web check:\s*/, '') }, sourceLinks(f.data?.sources)))));
}

function unconfirmedSection(fs) {
  if (!fs.length) return null;
  return section('unconfirmed', "Couldn't confirm", 'We found no reliable record of these, so check them yourself',
    h('ul', { class: 'plain-list' }, fs.map((f) => h('li', {}, badge(f.status), h('span', { class: 'quote-inline' }, `“${f.quote || f.title}”`)))));
}

function checklistSection(items) {
  if (!items?.length) return null;
  return section('checklist', 'What to do next', null,
    h('ul', { class: 'checklist' }, items.map((item, i) => h('li', {},
      h('input', { type: 'checkbox', id: `todo-${i}` }), h('label', { for: `todo-${i}` }, item)))));
}

function renderReport(data, text) {
  const findings = data.findings || [];
  const by = (...names) => findings.filter((f) => names.includes(f.checker));
  const web = (...kinds) => findings.filter((f) => f.checker === 'web' && kinds.includes(f.kind));
  const nav = [
    ['community', 'Student reports', by('community')], ['patterns', 'Warning signs', by('patterns')],
    ['orgs', "Who's behind it", [...by('registry', 'reputation'), ...web('entity')]], ['prices', 'Prices', [...by('benchmark'), ...web('price')]],
    ['schools', 'Schools', [...by('college'), ...web('school')]], ['stats', 'Official numbers', by('statistic')],
    ['web', 'Other claims', web('claim', 'statistic')], ['unconfirmed', 'Unconfirmed', by('router')],
  ].filter(([, , list]) => list.length);

  els.results.replaceChildren(...[
    hero(data, text),
    notices(data),
    nav.length > 1 ? h('nav', { class: 'jump', 'aria-label': 'Jump to section' }, nav.map(([id, label, list]) =>
      h('a', { href: `#section-${id}` }, label, h('span', { class: 'count' }, list.length)))) : null,
    communitySection(by('community')),
    patternsSection(by('patterns')),
    orgsSection([...by('registry', 'reputation'), ...web('entity')]),
    pricesSection([...by('benchmark'), ...web('price')]),
    schoolsSection([...by('college'), ...web('school')]),
    statsSection(by('statistic')),
    webSection(web('claim', 'statistic')),
    unconfirmedSection(by('router')),
    checklistSection(data.action_checklist),
  ].filter(Boolean));
  els.results.hidden = false;
  els.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ---------- API ----------

let loadingTimers = [];

function setLoading(on) {
  loadingTimers.forEach(clearTimeout);
  loadingTimers = [];
  els.loading.hidden = !on;
  els.submit.disabled = on || !els.text.value.trim();
  els.form.setAttribute('aria-busy', on ? 'true' : 'false');
  if (on) {
    els.loadingHint.hidden = !els.web.checked;
    const steps = els.web.checked ? LOADING_STEPS : LOADING_STEPS.slice(0, 3);
    for (const [delay, message] of steps) loadingTimers.push(setTimeout(() => { els.loadingText.textContent = message; }, delay));
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
  setLoading(true);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000);
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
    els.examples.replaceChildren(...examples.map((ex) => h('button', {
      type: 'button', class: 'chip chip-button', title: ex.text,
      onclick: () => { els.text.value = ex.text; onInput(); els.text.focus(); },
    }, ex.title)));
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

// ---------- UI wiring ----------

function onInput() {
  const n = els.text.value.length;
  els.count.textContent = `${n.toLocaleString('en-US')} character${n === 1 ? '' : 's'}`;
  els.submit.disabled = !els.text.value.trim() || !els.loading.hidden;
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
const initialScan = new URLSearchParams(location.search).get('scan');
if (initialScan) loadScan(initialScan);
