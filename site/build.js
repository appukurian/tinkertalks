#!/usr/bin/env node
// Zero-dependency static site builder for TinkerTalks.
// Reads every JSON file in data/talks/, writes plain HTML into site/dist/.
// Run with: node site/build.js  (from the repo root, or anywhere — paths are
// resolved relative to this file).

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const TALKS_DIR = path.join(ROOT, "data", "talks");
const DIST_DIR = path.join(ROOT, "site", "dist");
const ASSETS_SRC = path.join(ROOT, "site", "assets");

// The CMS claim form only ever asks for one thing (discussion_notes) — a
// volunteer never manually flips a status dropdown, since that'd be one more
// thing to forget. So "documented" is derived from data, not trusted from
// whatever the `status` field happened to say last: the daily Metabase sync
// writes "unclaimed", and this is the only place that ever changes it.
function effectiveStatus(t) {
  if (t.discussion_notes && String(t.discussion_notes).trim()) return "documented";
  if (t.claimed_by) return "claimed";
  return t.status || "unclaimed";
}

function loadTalks() {
  if (!fs.existsSync(TALKS_DIR)) return [];
  return fs
    .readdirSync(TALKS_DIR)
    .filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(fs.readFileSync(path.join(TALKS_DIR, f), "utf8")))
    .map((t) => ({ ...t, status: effectiveStatus(t) }))
    .sort((a, b) => (b.date || "").localeCompare(a.date || ""));
}

function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function layout({ title, active, body }) {
  const nav = [
    ["/", "Home"],
    ["/talks/", "All TinkerTalks"],
    ["/claim/", "Claim a TinkerTalk"],
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
          `<a href="${href}" class="${active === href ? "active" : ""}">${label}</a>`
      )
      .join("\n    ")}
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

// The claim form no longer asks for a "topic" title — it only asks what was
// discussed. Most talks won't have `topic` set, so fall back to a snippet of
// the discussion itself rather than showing "Untitled" on every card.
function talkTitle(t) {
  if (t.topic) return t.topic;
  if (t.discussion_notes) {
    const s = String(t.discussion_notes).trim();
    return s.length > 70 ? s.slice(0, 70).trimEnd() + "…" : s;
  }
  return "TinkerTalk — details pending";
}

function talkCardDocumented(t) {
  const cover = t.photos && t.photos[0] ? `<img class="thumb" src="${esc(t.photos[0])}" alt="">` : `<div class="thumb thumb-placeholder"></div>`;
  return `<a class="talk-card" href="/talks/${esc(t.id)}/">
  ${cover}
  <div class="talk-card-body">
    <div class="talk-chapter">${esc(t.chapter || "Unknown chapter")}</div>
    <div class="talk-topic">${esc(talkTitle(t))}</div>
    <div class="talk-date">${esc(t.date || "")}</div>
  </div>
</a>`;
}

function talkCardUnclaimed(t) {
  return `<div class="talk-card claim-card">
  <div class="talk-card-body">
    <div class="talk-chapter">${esc(t.chapter || "Unknown chapter")}</div>
    <div class="talk-topic">${esc(t.topic || "TinkerTalk — details pending")}</div>
    <div class="talk-date">${esc(t.date || "")}</div>
  </div>
  <a class="claim-btn" href="/admin/#/collections/talks/entries/${esc(t.id)}">Claim this TinkerTalk</a>
</div>`;
}

function buildIndex(talks) {
  const documented = talks.filter((t) => t.status === "documented");
  const chapters = new Set(talks.map((t) => t.chapter).filter(Boolean));
  const unclaimedCount = talks.filter((t) => t.status === "unclaimed").length;

  const body = `
<section class="hero">
  <h1>TinkerTalks, all in one place</h1>
  <p>Every campus chapter runs a weekly TinkerTalk. This is where they get documented and shared across all of TinkerHub.</p>
</section>
<section class="stats">
  ${statCard(talks.length, "TinkerTalks tracked")}
  ${statCard(documented.length, "Documented")}
  ${statCard(chapters.size, "Chapters represented")}
  ${statCard(unclaimedCount, "Awaiting a claim")}
</section>
<section>
  <h2>Recently documented</h2>
  <div class="talk-grid">
    ${documented.slice(0, 9).map(talkCardDocumented).join("\n    ") || "<p>Nothing documented yet — be the first to <a href=\"/claim/\">claim a TinkerTalk</a>.</p>"}
  </div>
</section>`;
  return layout({ title: "Home", active: "/", body });
}

function buildAllTalks(talks) {
  const documented = talks.filter((t) => t.status === "documented");
  const body = `
<h1>All TinkerTalks</h1>
<div class="talk-grid">
  ${documented.map(talkCardDocumented).join("\n  ") || "<p>No documented TinkerTalks yet.</p>"}
</div>`;
  return layout({ title: "All TinkerTalks", active: "/talks/", body });
}

function buildClaimPage(talks) {
  const unclaimed = talks.filter((t) => t.status === "unclaimed");
  const claimed = talks.filter((t) => t.status === "claimed");
  const body = `
<h1>Claim a TinkerTalk</h1>
<p>These TinkerTalks were picked up from the events calendar but haven't been documented yet. Log in with your GitHub account to claim one and add the write-up.</p>
<div class="talk-grid">
  ${unclaimed.map(talkCardUnclaimed).join("\n  ") || "<p>Nothing waiting to be claimed right now — check back after the next sync.</p>"}
</div>
${
  claimed.length
    ? `<h2>In progress</h2><div class="talk-grid">${claimed.map(talkCardUnclaimed).join("\n")}</div>`
    : ""
}`;
  return layout({ title: "Claim a TinkerTalk", active: "/claim/", body });
}

function buildDetail(t) {
  const photos = (t.photos || [])
    .map((p) => `<img src="${esc(p)}" alt="Photo from ${esc(talkTitle(t))}">`)
    .join("\n");
  // Chapter/date always shown (sync-owned, always present). Speaker/location
  // are shown only when set — today that's never (they're meant to come from
  // linking the event report, not yet wired in), so an empty row would just
  // read as broken rather than "not collected yet".
  const metaRows = [["Chapter", t.chapter], ["Date", t.date], ["Speaker", t.speaker], ["Location", t.location]]
    .filter(([, value]) => value)
    .map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`)
    .join("\n    ");
  const body = `
<article class="talk-detail">
  <h1>${esc(talkTitle(t))}</h1>
  <dl class="talk-meta">
    ${metaRows}
  </dl>
  ${t.discussion_notes ? `<h2>What was discussed</h2><p>${esc(t.discussion_notes)}</p>` : ""}
  ${photos ? `<h2>Photos</h2><div class="photo-grid">${photos}</div>` : ""}
</article>`;
  return layout({ title: talkTitle(t), active: "/talks/", body });
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

  write(path.join(DIST_DIR, "index.html"), buildIndex(talks));
  write(path.join(DIST_DIR, "talks", "index.html"), buildAllTalks(talks));
  write(path.join(DIST_DIR, "claim", "index.html"), buildClaimPage(talks));

  for (const t of talks) {
    write(path.join(DIST_DIR, "talks", t.id, "index.html"), buildDetail(t));
  }

  copyDir(ASSETS_SRC, path.join(DIST_DIR, "assets"));
  copyDir(path.join(ROOT, "admin"), path.join(DIST_DIR, "admin"));

  console.log(`Built ${talks.length} TinkerTalk page(s) into ${path.relative(ROOT, DIST_DIR)}/`);
}

main();
