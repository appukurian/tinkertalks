# TinkerTalks

A public site showcasing every TinkerTalk run by TinkerHub's 70+ campus
chapters. Data is synced daily from TinkerHub's Metabase-fronted events
database; chapter volunteers claim and document their own talks through an
in-browser CMS that opens a pull request for review.

## How it fits together

- **`data/talks/*.json`** — one file per TinkerTalk. This is the database;
  see `data/schema.md` for the field-by-field shape and status lifecycle
  (`unclaimed → claimed → documented`).
- **`scripts/fetch_metabase.py`** — pulls rows from the `events` table
  (Metabase database id `33`, table id `50`) where `resource_id = 14` (the actual TinkerTalk resource — an earlier "875A" guess never matched anything),
  and creates/updates the matching JSON file per talk. Never overwrites a
  talk once it's been claimed or documented — only fills in sync metadata.
- **`.github/workflows/fetch-metabase.yml`** — runs that script every
  morning (02:33 UTC / ~08:03 IST) via GitHub Actions, and commits whatever
  changed. Can also be run manually with a `debug` flag that just prints the
  raw Metabase columns instead of writing anything.
- **`site/build.js`** — a dependency-free static site generator. Reads
  `data/talks/*.json`, writes the landing page, the browse-all page, the
  claim page, and one detail page per documented talk into `site/dist/`.
  Run it locally with `node site/build.js`.
- **`admin/`** — [Decap CMS](https://decapcms.org), loaded straight from a
  CDN with no build step. This is the "claim" UI: a volunteer logs in with
  GitHub, opens their chapter's TinkerTalk entry, fills in the write-up and
  photos, and saving opens a pull request (Decap's "editorial workflow")
  instead of committing directly.
- **`netlify.toml`** — hosting config. Netlify builds with `node
  site/build.js` and publishes `site/dist`. Every PR (including the ones
  Decap opens) automatically gets its own preview URL.

## Setup still needed

This was scaffolded without direct access to either GitHub or the real
Metabase schema, so a few things need to happen before it's live:

1. **Create the GitHub repo** (Kurian's personal account) and push this
   scaffold to it.
2. **Fill in `admin/config.yml`** — replace `REPO_OWNER/REPO_NAME` with the
   real repo path.
3. **Connect the repo to Netlify** and enable its GitHub OAuth provider
   under Site settings → Access control, so Decap's login works without
   any custom backend.
4. **Add the `METABASE_API_KEY` repo secret** in GitHub (Settings →
   Secrets and variables → Actions) — never commit the raw key.
5. **Confirm the Metabase column mapping.** Run the sync workflow manually
   once with `debug: true` (Actions tab → "Sync TinkerTalks from Metabase" →
   Run workflow) and check the logged column names against
   `MAPPING_HINTS` in `scripts/fetch_metabase.py` — update the guesses if
   the real `events` table uses different column names for chapter/date.
6. **Do one end-to-end test claim**: pick a synced TinkerTalk, claim it
   through `/admin/`, fill in a few fields, save, confirm a PR appears,
   merge it, confirm the detail page shows the write-up after the next
   Netlify build.

## Local development

```bash
node site/build.js        # builds site/dist/
python3 -m http.server --directory site/dist 8080   # preview locally
```

To dry-run the Metabase sync without committing anything:

```bash
METABASE_API_KEY=... DEBUG=1 python3 scripts/fetch_metabase.py
```
