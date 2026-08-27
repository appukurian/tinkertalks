#!/usr/bin/env node
// Zero-dependency static site builder for TinkerTalks.
// Reads every JSON file in data/talks/, writes plain HTML into site/dist/.
// Run with: node site/build.js  (from the repo root, or anywhere — paths are
// resolved relative to this file).

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const TALKS_DIR = path.join(ROOT, 'data', 'talks');
const THEME_PATH = path.join(ROOT, 'data', 'theme.json');
const DIST_DIR = path.join(ROOT, 'site', 'dist');
const ASSETS_SRC = path.join(ROOT, 'site', 'assets');

// The current cycle's theme lives in a Google Doc, not Metabase — the build
// has no way to log into Drive, so this is hand-maintained (see the comment
// inside data/theme.json). Missing file just means no theme section shows.
function loadTheme() {
	if (!fs.existsSync(THEME_PATH)) return null;
	try {
		return JSON.parse(fs.readFileSync(THEME_PATH, 'utf8'));
	} catch {
		return null;
	}
}

// The CMS claim form only ever asks for one thing (discussion_notes) — a
// volunteer never manually flips a status dropdown, since that'd be one more
// thing to forget. So "documented" is derived from data, not trusted from
// whatever the `status` field happened to say last: the daily Metabase sync
// writes "unclaimed", and this is the only place that ever changes it.
function effectiveStatus(t) {
	if (t.discussion_notes && String(t.discussion_notes).trim())
		return 'documented';
	if (t.claimed_by) return 'claimed';
	return t.status || 'unclaimed';
}

function loadTalks() {
	if (!fs.existsSync(TALKS_DIR)) return [];
	return fs
		.readdirSync(TALKS_DIR)
		.filter((f) => f.endsWith('.json'))
		.map((f) => JSON.parse(fs.readFileSync(path.join(TALKS_DIR, f), 'utf8')))
		.map((t) => ({ ...t, status: effectiveStatus(t) }))
		.sort((a, b) => (b.date || '').localeCompare(a.date || ''));
}

function esc(s) {
	if (s === null || s === undefined) return '';
	return String(s)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');
}

function layout({ title, active, body }) {
	const nav = [
		['/', 'Home'],
		['/talks/', 'All TinkerTalks'],
		['/claim/', 'Claim a TinkerTalk'],
	];
	return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)} · TinkerTalks</title>
<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
<header class="site-header">
  <a class="brand" href="/">TinkerTalks</a>
  <nav>
    ${nav
			.map(
				([href, label]) =>
					`<a href="${href}" class="${active === href ? 'active' : ''}">${label}</a>`,
			)
			.join('\n    ')}
  </nav>
</header>
<main>
${body}
</main>
<footer class="site-footer">
  <p>A TinkerHub Campus initiative. Data synced daily from the TinkerHub events database. Chapters document their own sessions via <a href="/admin/">the CMS</a>.</p>
</footer>
</body>
</html>`;
}

function statCard(value, label) {
	return `<div class="stat"><div class="stat-value">${esc(value)}</div><div class="stat-label">${esc(label)}</div></div>`;
}

// Reach numbers (chapters/districts/participants run) reflect every synced
// TinkerTalk regardless of claim status — a session happened whether or not
// anyone's written it up yet. Quality numbers (ratings, "recently
// documented") only make sense for talks someone actually documented.
function districtBreakdown(talks) {
	const counts = new Map();
	for (const t of talks) {
		if (!t.district) continue;
		counts.set(t.district, (counts.get(t.district) || 0) + 1);
	}
	return [...counts.entries()]
		.sort((a, b) => b[1] - a[1])
		.map(([district, count]) => ({ district, count }));
}

function monthlyTrend(talks) {
	const counts = new Map();
	for (const t of talks) {
		if (!t.date) continue;
		const month = String(t.date).slice(0, 7); // "YYYY-MM"
		counts.set(month, (counts.get(month) || 0) + 1);
	}
	return [...counts.entries()]
		.sort(([a], [b]) => a.localeCompare(b))
		.map(([month, count]) => ({ month, count }));
}

function monthLabel(ym) {
	const [y, m] = ym.split('-').map(Number);
	return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'short' });
}

// Single-hue magnitude bars — one series, so no legend and no categorical
// palette needed (see dataviz skill: sequential/one-hue is the safe default
// for "compare magnitude"; a legend only earns its place at 2+ series).
function barChart(rows, { labelKey, valueKey, unit = '' }) {
	const max = Math.max(1, ...rows.map((r) => r[valueKey]));
	return rows
		.map(
			(r) => `<div class="bar-row">
    <div class="bar-label">${esc(r[labelKey])}</div>
    <div class="bar-track"><div class="bar-fill" style="width:${Math.round((r[valueKey] / max) * 100)}%"></div></div>
    <div class="bar-value">${esc(r[valueKey])}${unit}</div>
  </div>`,
		)
		.join('\n  ');
}

function trendChart(rows) {
	const max = Math.max(1, ...rows.map((r) => r.count));
	return `<div class="trend-chart">
  ${rows
		.map(
			(r) => `<div class="trend-col">
    <div class="trend-value">${esc(r.count)}</div>
    <div class="trend-bar" style="height:${Math.round((r.count / max) * 100)}%"></div>
    <div class="trend-label">${esc(monthLabel(r.month))}</div>
  </div>`,
		)
		.join('\n  ')}
</div>`;
}

// The claim form no longer asks for a "topic" title — it only asks what was
// discussed. Most talks won't have `topic` set, so fall back to a snippet of
// the discussion itself rather than showing "Untitled" on every card.
function talkTitle(t) {
	// Previously fell back to a truncated snippet of discussion_notes — but
	// that meant the same sentence showed twice on a detail page (once cut
	// short as the heading, once in full under "What was discussed"). Since
	// there's no separate topic field, build the heading from chapter + date
	// instead, which is always available and never duplicates the write-up.
	if (t.topic) return t.topic;
	// Date isn't repeated here — it's already the first line of the meta row
	// directly below the heading.
	if (t.chapter) return `TinkerTalk at ${t.chapter}`;
	return 'TinkerTalk — details pending';
}

// Card teaser: a snippet of what was discussed is a fine preview here, since
// the full text only appears on the detail page (a different page) — unlike
// talkTitle() on the detail page itself, this never duplicates against the
// full body shown right below it.
function talkPreview(t) {
	if (t.topic) return t.topic;
	if (t.discussion_notes) {
		const s = String(t.discussion_notes).trim();
		return s.length > 70 ? s.slice(0, 70).trimEnd() + '…' : s;
	}
	return 'TinkerTalk — details pending';
}

function talkCardDocumented(t) {
	// The same first photo from the event report doubles as this card's
	// thumbnail and the cover shown at the top of the detail page's photo
	// gallery — one image, two places, no separate upload.
	const cover =
		t.photos && t.photos[0]
			? `<img class="thumb" src="${esc(t.photos[0])}" alt="">`
			: `<div class="thumb thumb-placeholder"></div>`;
	return `<a class="talk-card" href="/talks/${esc(t.id)}/" data-chapter="${esc(t.chapter || '')}" data-district="${esc(t.district || '')}">
  ${cover}
  <div class="talk-card-body">
    <div class="talk-chapter">${esc(t.chapter || 'Unknown chapter')}</div>
    <div class="talk-topic">${esc(talkPreview(t))}</div>
    <div class="talk-date">${esc(t.date || '')}</div>
  </div>
</a>`;
}

function talkCardUnclaimed(t) {
	return `<div class="talk-card claim-card">
  <div class="talk-card-body">
    <div class="talk-chapter">${esc(t.chapter || 'Unknown chapter')}</div>
    <div class="talk-topic">${esc(t.topic || 'TinkerTalk — details pending')}</div>
    <div class="talk-date">${esc(t.date || '')}</div>
  </div>
  <a class="claim-btn" href="/admin/#/collections/talks/entries/${esc(t.id)}">Claim this TinkerTalk</a>
</div>`;
}

function buildIndex(talks, theme) {
	const documented = talks.filter((t) => t.status === 'documented');
	const chapters = new Set(talks.map((t) => t.chapter).filter(Boolean));
	const districts = new Set(talks.map((t) => t.district).filter(Boolean));
	const unclaimedCount = talks.filter((t) => t.status === 'unclaimed').length;
	const totalParticipants = talks.reduce(
		(sum, t) => sum + (t.participant_count || 0),
		0,
	);

	const ratedTalks = talks.filter(
		(t) => t.feedback && typeof t.feedback.avg_overall_experience === 'number',
	);
	const avgRating = ratedTalks.length
		? (
				ratedTalks.reduce(
					(sum, t) => sum + t.feedback.avg_overall_experience,
					0,
				) / ratedTalks.length
			).toFixed(1)
		: null;

	const themeSection = theme
		? `<section class="theme-banner">
  <div class="theme-label">${esc(theme.cycle)}${theme.period ? ` · ${esc(theme.period)}` : ''}</div>
  <h2>This cycle's theme: ${esc(theme.theme)}</h2>
  ${theme.blurb ? `<p>${esc(theme.blurb)}</p>` : ''}
  ${
		Array.isArray(theme.sample_topics) && theme.sample_topics.length
			? `<ul class="theme-topics">${theme.sample_topics.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>`
			: ''
	}
</section>`
		: '';

	const districts_rows = districtBreakdown(talks);
	const trend_rows = monthlyTrend(talks);

	const impactSection = `
<section class="impact">
  <h2>Reach across Kerala</h2>
  <p class="section-lede">TinkerTalks run every week, in campuses across the state — this is the scale of that, updated automatically from TinkerHub's own event records.</p>
  <div class="stats">
    ${statCard(talks.length, 'TinkerTalks run')}
    ${statCard(chapters.size, 'Campus chapters')}
    ${statCard(districts.size, 'Districts reached')}
    ${statCard(totalParticipants.toLocaleString('en-IN'), 'Total participants')}
    ${avgRating ? statCard(avgRating + ' / 10', 'Avg. attendee rating') : ''}
  </div>
  ${
		districts_rows.length
			? `<div class="impact-charts">
    <div class="chart-card">
      <h3>TinkerTalks by district</h3>
      ${barChart(districts_rows, { labelKey: 'district', valueKey: 'count' })}
    </div>
    ${
			trend_rows.length > 1
				? `<div class="chart-card">
      <h3>Momentum, month over month</h3>
      ${trendChart(trend_rows)}
    </div>`
				: ''
		}
  </div>`
			: ''
	}
</section>`;

	const body = `
<section class="hero">
  <h1>TinkerTalks, all in one place</h1>
  <p>TinkerTalks are community talk sessions run every week by TinkerHub's campus chapters, all across Kerala. Each bimonthly cycle sets a theme, and every chapter picks topics within it to run as a session on their own campus — this is where all of those come together.</p>
</section>
${themeSection}
${impactSection}
<section>
  <h2>Recently held TinkerTalks</h2>
  <div class="talk-grid">
    ${documented.slice(0, 9).map(talkCardDocumented).join('\n    ') || '<p>Nothing to show yet — be the first to <a href="/claim/">write up a TinkerTalk</a>.</p>'}
  </div>
</section>`;
	return layout({ title: 'Home', active: '/', body });
}

function filterSelect(id, label, allLabel, options) {
	return `<label class="filter-field">
  ${esc(label)}
  <select id="${id}">
    <option value="">${esc(allLabel)}</option>
    ${options.map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join('\n    ')}
  </select>
</label>`;
}

// Plain vanilla JS, no build step or framework — matches the rest of the
// site. Filters by chapter and/or district together (AND), reading the
// data-chapter/data-district attributes written onto each card above.
const FILTER_SCRIPT = `
<script>
(function () {
  var chapterSel = document.getElementById("chapterFilter");
  var districtSel = document.getElementById("districtFilter");
  var cards = document.querySelectorAll("#talk-grid .talk-card");
  var emptyMsg = document.getElementById("filter-empty");
  function apply() {
    var chapter = chapterSel.value, district = districtSel.value;
    var visible = 0;
    cards.forEach(function (c) {
      var match = (!chapter || c.dataset.chapter === chapter) && (!district || c.dataset.district === district);
      c.style.display = match ? "" : "none";
      if (match) visible++;
    });
    if (emptyMsg) emptyMsg.style.display = visible === 0 ? "" : "none";
  }
  chapterSel.addEventListener("change", apply);
  districtSel.addEventListener("change", apply);
})();
</script>`;

function buildAllTalks(talks) {
	const documented = talks.filter((t) => t.status === 'documented');
	const chapters = [
		...new Set(documented.map((t) => t.chapter).filter(Boolean)),
	].sort();
	const districts = [
		...new Set(documented.map((t) => t.district).filter(Boolean)),
	].sort();

	const filters = documented.length
		? `<div class="filter-row">
  ${filterSelect('chapterFilter', 'Chapter', 'All chapters', chapters)}
  ${filterSelect('districtFilter', 'District', 'All districts', districts)}
</div>`
		: '';

	const body = `
<h1>All TinkerTalks</h1>
<p>Every TinkerTalk that's happened, with its write-up, across every campus chapter.</p>
${filters}
<div class="talk-grid" id="talk-grid">
  ${documented.map(talkCardDocumented).join('\n  ') || '<p>Nothing to show yet.</p>'}
</div>
${documented.length ? `<p id="filter-empty" style="display:none; color: var(--muted);">No TinkerTalks match that filter yet.</p>` : ''}
${documented.length ? FILTER_SCRIPT : ''}`;
	return layout({ title: 'All TinkerTalks', active: '/talks/', body });
}

function buildClaimPage(talks) {
	const unclaimed = talks.filter((t) => t.status === 'unclaimed');
	const claimed = talks.filter((t) => t.status === 'claimed');
	const body = `
<h1>Claim a TinkerTalk</h1>
<p>These TinkerTalks have already happened, but no one's added the write-up yet. Log in with your GitHub account to claim one and say what was discussed.</p>
<div class="talk-grid">
  ${unclaimed.map(talkCardUnclaimed).join('\n  ') || '<p>Nothing waiting to be claimed right now — check back after the next sync.</p>'}
</div>
${
	claimed.length
		? `<h2>In progress</h2><div class="talk-grid">${claimed.map(talkCardUnclaimed).join('\n')}</div>`
		: ''
}`;
	return layout({ title: 'Claim a TinkerTalk', active: '/claim/', body });
}

function buildDetail(t) {
	const photos = (t.photos || [])
		.map((p) => `<img src="${esc(p)}" alt="Photo from ${esc(talkTitle(t))}">`)
		.join('\n');

	const speakerNames = (t.speakers || [])
		.map((s) => s.name)
		.filter(Boolean)
		.join(', ');
	const speakerTaglines = (t.speakers || [])
		.map((s) => s.tagline)
		.filter(Boolean)
		.join(' · ');

	// Chapter/date/district always shown when present (sync-owned). Speaker and
	// venue only show when the linked speaker/event_venue/event_report tables
	// actually had a row for this event — an empty row would read as broken
	// rather than "not filed yet".
	const metaRows = [
		['Chapter', t.chapter],
		['District', t.district],
		['Date', t.date],
		['Speaker', speakerNames || null],
		['Venue', t.venue ? t.venue.name : null],
	]
		.filter(([, value]) => value)
		.map(
			([label, value]) =>
				`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`,
		)
		.join('\n    ');

	const participationSection =
		t.participant_count || (t.feedback && t.feedback.count)
			? `<section class="participation">
    ${t.participant_count ? statCard(t.participant_count, 'Attended') : ''}
    ${
			t.feedback && typeof t.feedback.avg_overall_experience === 'number'
				? statCard(
						t.feedback.avg_overall_experience + ' / 10',
						'Avg. rating (' + t.feedback.count + ' responses)',
					)
				: ''
		}
  </section>`
			: '';

	const materialsSection =
		t.materials && t.materials.length
			? `<h2>Materials</h2><ul class="materials-list">${t.materials
					.map(
						(m) =>
							`<li><a href="${esc(m)}" target="_blank" rel="noopener">${esc(m)}</a></li>`,
					)
					.join('')}</ul>`
			: '';

	const venueSection =
		t.venue && (t.venue.address || t.venue.map_url)
			? `<p class="venue-detail">${esc(t.venue.address || '')}${
					t.venue.map_url
						? ` — <a href="${esc(t.venue.map_url)}" target="_blank" rel="noopener">map</a>`
						: ''
				}</p>`
			: '';

	const body = `
<article class="talk-detail">
  <h1>${esc(talkTitle(t))}</h1>
  ${speakerTaglines ? `<p class="speaker-tagline">${esc(speakerTaglines)}</p>` : ''}
  <dl class="talk-meta">
    ${metaRows}
  </dl>
  ${venueSection}
  ${participationSection}
  ${t.discussion_notes ? `<h2>What was discussed</h2><p>${esc(t.discussion_notes)}</p>` : ''}
  ${photos ? `<h2>Photos</h2><div class="photo-grid">${photos}</div>` : ''}
  ${materialsSection}
</article>`;
	return layout({ title: talkTitle(t), active: '/talks/', body });
}

function write(filePath, content) {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	fs.writeFileSync(filePath, content);
}

function copyDir(src, dest) {
	if (!fs.existsSync(src)) return;
	fs.mkdirSync(dest, { recursive: true });
	for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
		const s = path.join(src, entry.name);
		const d = path.join(dest, entry.name);
		if (entry.isDirectory()) copyDir(s, d);
		else fs.copyFileSync(s, d);
	}
}

function main() {
	fs.rmSync(DIST_DIR, { recursive: true, force: true });
	const talks = loadTalks();
	const theme = loadTheme();

	write(path.join(DIST_DIR, 'index.html'), buildIndex(talks, theme));
	write(path.join(DIST_DIR, 'talks', 'index.html'), buildAllTalks(talks));
	write(path.join(DIST_DIR, 'claim', 'index.html'), buildClaimPage(talks));

	for (const t of talks) {
		write(path.join(DIST_DIR, 'talks', t.id, 'index.html'), buildDetail(t));
	}

	copyDir(ASSETS_SRC, path.join(DIST_DIR, 'assets'));
	copyDir(path.join(ROOT, 'admin'), path.join(DIST_DIR, 'admin'));

	console.log(
		`Built ${talks.length} TinkerTalk page(s) into ${path.relative(ROOT, DIST_DIR)}/`,
	);
}

main();
