# TinkerTalks — how this project works

This is the reference doc for the whole system: what it is, how data moves
through it, what runs on a schedule, and how to operate it day to day. For
setup steps see `README.md`; for the exact shape of a TinkerTalk record see
`data/schema.md`.

## What a TinkerTalk is

TinkerHub runs 70+ campus chapters across Kerala. Every chapter runs a
**TinkerTalk** — a weekly community talk session — picking topics from a
**bimonthly theme** set centrally (the current cycle's theme is shown on the
homepage; see "The theme banner" below). This site is where every TinkerTalk,
across every chapter, gets tracked, documented, and shown — both as an
internal record and as a public showcase for potential sponsors and partners.

## The three systems involved

1. **Metabase** (`metabase.tinkerhub.org`) — TinkerHub's existing operational
   database, fronted by Metabase for querying. This is the source of truth
   for which events happened, where, and who ran them. TinkerTalks doesn't
   own this data; it reads it.
2. **GitHub** (`appukurian/tinkertalks`) — the "backend." Every TinkerTalk is
   a JSON file in `data/talks/`, committed to this repo. Both the automated
   sync and the human claim/write-up flow work by committing to this repo.
3. **Netlify** — hosts the static site, rebuilding automatically on every
   push to `main`. Also brokers the GitHub login used by the claim form
   (Site settings → Access control → OAuth on the Netlify side; a GitHub
   OAuth App on the GitHub side).

Nothing here needs a traditional server — no database to run, no backend
process beyond a script that runs once a day.

## The daily data pipeline

`.github/workflows/fetch-metabase.yml` runs `scripts/fetch_metabase.py`:

- **On a schedule** — `33 2 * * *` (02:33 UTC, ≈08:03 IST), daily.
- **On every push to `main`** — set up during initial development so pushes
  would trigger an immediate sync while the Metabase connection was being
  debugged. Harmless to leave on (idempotent, commits nothing if nothing
  changed) but easy to remove if the extra runs aren't wanted — just delete
  the `push:` block from the workflow's `on:` section.
- **Manually** — GitHub repo → Actions tab → "Sync TinkerTalks from
  Metabase" in the sidebar → "Run workflow" button → Run. A `debug` checkbox
  is available for a dry run that only prints to the Action log and commits
  nothing.

What the script does:

1. Queries the `events` table (Metabase database id `33`, table id `50`) via
   `POST /api/dataset`, and keeps only rows where `resource_ids` contains the
   TinkerTalk resource `875A`. **As of this writing, no historical event has
   ever actually been tagged with that resource** — the mechanism is correct
   and deliberate (not every `Talk_Session`-type event is a TinkerTalk), but
   it means the dashboard stays empty of real data until whoever creates
   these events starts tagging new ones with `875A` going forward. This
   isn't a code problem; it's a process one, on the event-creation side.
2. For every matched event, joins in from five more tables — one full-table
   fetch each, joined in Python by event id:
   - `sub_orgs` (table `41`) → chapter name + district. Only `name` and
     `district` are ever pulled; this table also holds faculty/principal
     emails and phone numbers that must never become public.
   - `speaker` (table `82`) → speaker name, tagline, avatar.
   - `event_venue` (table `76`) → venue name, address, map link, seat count.
   - `event_report` (table `79`) → the report a chapter already files after
     running a session: photos, materials/resource links, a
     worth-organizing flag, and five 1–5 ratings.
   - `attendees` (table `47`) → participant count and check-in count.
   - `attendee_feedback` (table `65`) → aggregated only (averages + a
     count) — individual free-text comments (`liked_most`,
     `how_to_improve`) are never stored, since those come from named
     attendees who didn't sign up to have their comment made public.
3. Writes/updates `data/talks/evt-<id>.json`. Every sync-owned field
   (chapter, district, date, speakers, venue, photos, materials, ratings,
   participation numbers) is refreshed on every run. The only fields a sync
   never touches are the ones a human filled in: `status`, `claimed_by`,
   `claimed_at`, `discussion_notes`.
4. Writes `data/_sync-debug.json` — column names and aggregate counts only
   (never row values, except a small safe-columns sample while the mapping
   is still being confirmed) — so the mapping can be checked without ever
   risking a data leak into a public repo.

`scripts/explore_schema.py` is a separate, one-shot script riding along in
the same workflow run. It calls Metabase's `/api/database/33/metadata`
endpoint and writes `data/_schema-explore.json` — every table and column
name (not values) in the whole database. This is how all six tables above
were found; useful again if TinkerTalks ever needs another data point that
turns out to live somewhere new.

## The claim flow

1. A chapter volunteer visits `/claim/`, sees TinkerTalks with `status:
   "unclaimed"`, and clicks through to `/admin/#/collections/talks/entries/<id>`.
2. Decap CMS (`admin/config.yml`, loaded from a CDN — no build step) asks
   them to log in with GitHub, then shows exactly **one** editable field:
   "What exactly did you discuss?" Every other field (chapter, date,
   speaker, venue, photos, participant count, ratings) is present in the
   file but hidden from the form, because all of that already exists in
   Metabase/the event report — asking a volunteer to retype it would just be
   duplicate data entry with a chance to go stale.
3. Saving doesn't commit to `main`. Because `open_authoring: true` +
   `publish_mode: editorial_workflow` are set, Decap forks the repo under
   the volunteer's account and opens a pull request back to
   `appukurian/tinkertalks`. This only works because the repo is public —
   fork-based contribution is what lets 70+ people submit without each one
   needing to be added as a GitHub collaborator.
4. A repo collaborator reviews and merges the PR on GitHub. Netlify rebuilds
   automatically once it's merged.
5. The site itself never trusts a stored `status` value for whether
   something counts as "documented" — `site/build.js`'s `effectiveStatus()`
   derives it from whether `discussion_notes` is actually filled in, so a
   volunteer never has to also remember to flip a dropdown.

Note: if you (the repo owner) test the claim flow yourself, Decap will let
you publish straight through with no review pause, since you already have
merge rights on your own repo. That shortcut doesn't exist for anyone else —
their PR sits until a collaborator merges it.

## The theme banner

The homepage's "This cycle's theme" section is **not** pulled from Metabase
— it's hand-maintained from a Google Doc in Drive (title pattern:
"TinkerTalks — `<Theme>` (Cycle N: `<months>`)"). The site build has no way
to authenticate into Google Drive, so `data/theme.json` is the source of
truth for this one section — update it once per cycle when a new theme doc
is published. Missing the file just means the banner doesn't render;
nothing else depends on it.

## The impact dashboard

The homepage leads with reach numbers meant for sponsors/partners as much as
for internal tracking: TinkerTalks run, campus chapters, districts reached,
total participants, and an average attendee rating — plus a by-district bar
chart and a month-over-month trend chart (`site/build.js`, using a single
accent hue for magnitude per the project's dataviz conventions — no
categorical palette needed since these are one-series charts). Reach numbers
count every synced TinkerTalk regardless of claim status (a session happened
whether or not it's been written up yet); the average-rating figure only
counts talks that actually have feedback data.

## The static site itself

`site/build.js` is a dependency-free Node script — no framework, no npm
install required to build it. It reads every file in `data/talks/`, plus
`data/theme.json`, and writes plain HTML into `site/dist/`:

- `/` — landing page: definition, theme banner, impact dashboard, recently
  held TinkerTalks.
- `/talks/` — every documented TinkerTalk, with chapter and district filters
  (plain client-side JS, no reload, no framework).
- `/talks/<id>/` — one detail page per talk: title, chapter/district/date,
  speaker, venue, participation + rating stats, the write-up, photos, and
  any materials/resource links.
- `/claim/` — unclaimed and in-progress TinkerTalks, each linking straight
  into its Decap CMS entry.
- `/admin/` — the Decap CMS itself (just `config.yml` + an `index.html` that
  loads Decap from a CDN).

`netlify.toml` tells Netlify to run `node site/build.js` and publish
`site/dist`.

## Privacy design

This repo is public by necessity (fork-based contribution needs a public
repo). Every join in `fetch_metabase.py` is a deliberate, narrow field pick
— never a raw row passthrough — specifically because some of the tables
involved (`sub_orgs`, `attendee_feedback`) hold information that was never
meant to be public. If a future change needs a new field from Metabase, add
it deliberately to the relevant lookup builder rather than widening a query
to pull a whole row.

## Secrets — where METABASE_API_KEY can and can't go

The Metabase key lives only as an encrypted GitHub Actions secret (Settings
→ Secrets and variables → Actions). It is never written into any file in
this repo — `data/_sync-debug.json` and `data/_schema-explore.json` are
deliberately schema/aggregate-only for exactly this reason. Inside the
workflow it's injected as an environment variable for that one run and used
exactly once, as the outgoing `x-api-key` header on the request to
Metabase; the script never prints it, and GitHub additionally auto-redacts
any exact match to a registered secret value in Action logs as a backstop.

Netlify has no access to it at all — it isn't needed there, since Netlify
only builds the already-committed static files and never talks to Metabase.

The fork-based claim flow (see above) can't be used to exfiltrate it either:
`fetch-metabase.yml` only triggers on `schedule`, `workflow_dispatch`, or a
push to `main` — never on `pull_request` — so an unmerged PR from someone's
fork never runs with secrets access, no matter what it contains. The only
time a change to that workflow file would ever run with the secret present
is after a collaborator has already reviewed and merged it into `main`.
Ordinary good practice from there: read changes to `.github/workflows/*`
a little more carefully than a content PR before merging.

## Known open items

- **Resource tagging isn't happening yet.** See "The daily data pipeline"
  above — this is the main blocker to the dashboard showing real data.
- **`type_value_counts` in `data/_sync-debug.json`** shows how many events
  exist per `type` value (e.g. `Talk_Session`, `Meetup`) as a diagnostic —
  useful context, but `resource_ids = 875A` remains the correct filter,
  confirmed deliberately (not every `Talk_Session` is a TinkerTalk).
- **`description` and `banner` columns on `events`** were flagged as
  possibly useful (an event write-up and cover image that might already
  exist) but haven't been sampled or wired in yet.
- Dummy data (`data/talks/dummy-*.json`) exists to exercise the site's UI
  while real tagged data doesn't exist yet — delete these once real
  TinkerTalks start flowing in.
