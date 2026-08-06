# TinkerTalk record schema

Each TinkerTalk is one JSON file at `data/talks/<id>.json`. `<id>` is a stable
slug derived from the Metabase row id (e.g. `evt-4821.json`), so the daily
sync can always find and update the same file rather than creating
duplicates.

```jsonc
{
  // Identity — owned by the daily Metabase sync. Don't hand-edit these.
  "id": "evt-4821",                 // stable id, derived from the metabase row id
  "resource_id": "875A",            // the metabase resource_id that marks this as a TinkerTalk
  "metabase_row_id": 4821,          // raw id from the events table, for re-sync matching
  "synced_at": "2026-08-05T02:30:00Z",

  // Best-guess fields mapped from the events table by the sync script.
  // Column names in Metabase weren't confirmed yet (see scripts/fetch_metabase.py
  // MAPPING_HINTS) — until confirmed, "source" below is the ground truth and
  // these may be null or wrong.
  "chapter": "TKM College of Engineering",
  "date": "2026-08-04",

  // Raw row from Metabase, untouched, so nothing is lost if the guessed
  // mapping above is wrong. Keys are whatever column names the events table
  // actually uses.
  "source": { "...": "..." },

  // Editorial fields — owned by whoever claims + documents the talk via the
  // CMS. The daily sync never overwrites this block once it exists.
  "status": "unclaimed",            // unclaimed -> claimed -> documented
  "claimed_by": null,                // GitHub username
  "claimed_at": null,
  "topic": null,                     // what was actually discussed (may differ from the theme)
  "speaker": null,
  "location": null,
  "discussion_notes": null,
  "photos": []                       // paths under /admin/uploads/, added via the CMS media picker
}
```

## Status lifecycle

1. **unclaimed** — created/updated by the daily sync from Metabase. Shows up
   on the "Claim a TinkerTalk" page.
2. **claimed** — a chapter volunteer opened the entry in the CMS and saved a
   first draft (editorial workflow opens this as a PR in "draft" status).
3. **documented** — the PR was merged. The talk now has a full write-up and
   shows up on its own detail page with photos, location, time, and notes.

## Why `source` is kept verbatim

The sandbox this project was scaffolded in couldn't reach
`metabase.tinkerhub.org` directly (network egress is allowlisted there), so
the exact column names in the `events` table (database id 33, table id 50)
weren't confirmed before writing the first version of the sync script. Every
synced row keeps its raw form under `source` so re-running the sync with a
corrected mapping never loses data — it just repopulates `chapter`/`date`
from the right columns.
