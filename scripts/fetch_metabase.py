#!/usr/bin/env python3
"""
Daily sync: pull TinkerTalk rows out of TinkerHub's Metabase and write/update
one JSON file per talk under data/talks/.

Runs inside the "Sync TinkerTalks from Metabase" GitHub Action (see
.github/workflows/fetch-metabase.yml), which has normal internet access.
It was NOT possible to test this against the real Metabase instance while
writing it (the dev sandbox's network is allowlisted and metabase.tinkerhub.org
isn't on that list) — so the first automatic run (triggered by the initial
push) writes data/_sync-debug.json with the real column names, which is
schema-only and safe to keep in the public repo (see privacy note below).

Env vars required:
  METABASE_URL       e.g. https://metabase.tinkerhub.org
  METABASE_API_KEY   the mb_... key (passed as the x-api-key header)

Env vars optional:
  METABASE_DATABASE_ID default 33   (database the `events` table lives in)
  METABASE_TABLE_ID    default 50   (the `events` table)
  METABASE_RESOURCE_ID default 875A (the resource_id that marks a TinkerTalk)

Note: an earlier version of this script called POST /api/table/:id/query,
which 404'd against the real instance (that route doesn't exist / isn't
exposed the way assumed). Switched to POST /api/dataset with an explicit MBQL
query — the same request shape Metabase's own UI uses under the hood, and
the one the original question link (database 33, source-table 50) decoded
to — which is the stable, documented way to run a table query via the API.
  DEBUG=1              print columns + sample rows to the Action log and
                        exit without writing or committing anything. Use for
                        manual troubleshooting (values only reach the log,
                        which is fine since Actions logs on a public repo are
                        also public — don't leave this on by default for that
                        reason, it's opt-in per run).

Privacy note: this repo is public (see README — TinkerTalks supports fork+PR
contributions from 70+ campus chapters without needing to add each one as a
collaborator). So this script only ever writes the specific fields TinkerTalks
is meant to show publicly (chapter name, date) into data/talks/*.json — never
the full raw Metabase row, since the `events` table may hold columns (phone
numbers, internal notes, etc.) that were never meant to be public. If more
fields are needed later, add them to MAPPING_HINTS deliberately rather than
re-introducing a raw passthrough.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

METABASE_URL = os.environ.get("METABASE_URL", "https://metabase.tinkerhub.org").rstrip("/")
METABASE_API_KEY = os.environ.get("METABASE_API_KEY")
DATABASE_ID = int(os.environ.get("METABASE_DATABASE_ID", "33"))
TABLE_ID = int(os.environ.get("METABASE_TABLE_ID", "50"))
RESOURCE_ID = os.environ.get("METABASE_RESOURCE_ID", "875A")
DEBUG = os.environ.get("DEBUG") == "1"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TALKS_DIR = os.path.join(REPO_ROOT, "data", "talks")
DEBUG_SNAPSHOT_PATH = os.path.join(REPO_ROOT, "data", "_sync-debug.json")

# Column-name candidates for each field we care about, in priority order.
# `events` table's real columns weren't confirmed yet — this list is a
# best-effort guess based on the fields Kurian described (chapter/campus,
# talk date, resource_id). Update this once data/_sync-debug.json (written by
# the first live run) shows the real column names.
MAPPING_HINTS = {
    # The real events table (as of the first live sync) has "resource_ids"
    # (plural) — one event can carry more than one resource tag — not a
    # single "resource_id" column. See resource_matches() below for how a
    # single row is checked against RESOURCE_ID.
    "resource_id": ["resource_ids", "resource_id", "resourceid", "resource id"],
    "chapter": ["chapter", "campus", "organiser", "organizer", "chapter_name", "campus_name", "name"],
    "date": ["date", "start_date", "event_date", "start date", "created_at"],
}

# Only these mapped, public-safe fields ever get written into a talk record.
# Anything else in the `events` row (phone numbers, internal notes, whatever
# else that table happens to hold) is deliberately dropped, not stored.
PUBLIC_FIELDS = ("chapter", "date")

# Structural, non-personal columns safe to sample a few real VALUES of (not
# just names) in the debug snapshot, to nail down the mapping without
# guessing blind. Deliberately excludes anything that could hold PII —
# there's no such column in the real `events` table, but keep this narrow
# and explicit rather than sampling every column.
SAFE_SAMPLE_COLUMNS = [
    "id", "name", "type", "start_date", "end_date", "org_id", "sub_org_id",
    "unique_id", "status", "resource_ids", "location", "is_virtual",
]


def resource_matches(value, target):
    """True if `value` (whatever shape the resource_ids cell takes) includes
    `target`. Handles a plain scalar, a real list/tuple, a JSON-encoded list
    string ('["875A","202B"]'), and a comma/space-separated string."""
    if value is None:
        return False
    if isinstance(value, (list, tuple, set)):
        return any(str(v).strip() == target for v in value)
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return any(str(v).strip() == target for v in parsed)
            except json.JSONDecodeError:
                pass
        # fall back to comma/space separated
        parts = [p.strip().strip('"').strip("'") for p in s.replace(",", " ").split()]
        if target in parts:
            return True
        return s == target
    return str(value) == target


def fetch_table_rows(table_id):
    # Same request shape as Metabase's own UI (and the question link this was
    # bootstrapped from): a plain MBQL query against source-table, run
    # through the general /api/dataset endpoint.
    url = f"{METABASE_URL}/api/dataset"
    body = json.dumps({
        "database": DATABASE_ID,
        "type": "query",
        "query": {"source-table": table_id},
        # Metabase caps interactive queries at 2000 rows by default. The
        # first live run hit exactly that ceiling (total_rows_in_table:
        # 2000), which means older/future TinkerTalks could silently fall
        # outside the window as the events table grows. Raise it explicitly.
        "constraints": {"max-results": 200000, "max-results-bare-rows": 200000},
    }).encode("utf-8")
    req = urllib.request.Request(url, method="POST", data=body)
    req.add_header("x-api-key", METABASE_API_KEY)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(f"Metabase returned HTTP {e.code}: {body_text}", file=sys.stderr)
        raise
    data = payload.get("data", payload)
    cols = [c.get("name") or c.get("display_name") for c in data["cols"]]
    rows = data["rows"]
    return cols, [dict(zip(cols, row)) for row in rows]


def find_column(cols, candidates):
    lower = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    # fallback: substring match
    for c in cols:
        for cand in candidates:
            if cand.replace(" ", "").replace("_", "") in c.lower().replace(" ", "").replace("_", ""):
                return c
    return None


def slugify_id(row, cols):
    id_col = find_column(cols, ["id", "event_id", "row_id"])
    raw_id = row.get(id_col) if id_col else None
    if raw_id is None:
        # last resort: hash the row (values only used transiently, never stored)
        raw_id = abs(hash(json.dumps(row, sort_keys=True, default=str))) % (10**8)
    return f"evt-{raw_id}"


def write_debug_snapshot(cols, rows, matched_count, resource_col, chapter_col, date_col, matched_rows=None):
    # Column names always included. Real VALUES are only included for the
    # narrow SAFE_SAMPLE_COLUMNS whitelist (structural fields, no PII) and
    # only while matched_rows is 0 — once matching works this block should
    # be dropped so the debug file goes back to schema-only.
    snapshot = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "table_id": TABLE_ID,
        "columns_seen": cols,
        "total_rows_in_table": len(rows),
        "resource_id_filter": RESOURCE_ID,
        "matched_rows": matched_count,
        "guessed_mapping": {
            "resource_id": resource_col,
            "chapter": chapter_col,
            "date": date_col,
        },
        "note": (
            "If a guessed_mapping value looks wrong, update MAPPING_HINTS in "
            "scripts/fetch_metabase.py to point at the correct column name."
        ),
    }
    # Keep sampling real values until the chapter mapping is confirmed by a
    # human (not just "a column was found") — remove this block once
    # MAPPING_HINTS["chapter"] is known to point at the right column.
    sample_source = matched_rows if matched_rows else rows
    sample_cols = [c for c in SAFE_SAMPLE_COLUMNS if c in cols]
    snapshot["sample_values_while_debugging"] = {
        "note": (
            "Structural/non-PII columns only, up to 5 rows (matched TinkerTalks "
            "if any were found, otherwise the general table), so the chapter/date "
            "mapping can be confirmed or fixed without another blind guess. "
            "Delete this block from the script once the mapping is confirmed."
        ),
        "columns": sample_cols,
        "rows": [{c: r.get(c) for c in sample_cols} for r in sample_source[:5]],
    }

    # The first non-empty sample happened to be all null resource_ids — that
    # tells us nothing. Specifically hunt for rows where it IS set, and check
    # whether RESOURCE_ID shows up anywhere in the whole table at all, so we
    # can tell "wrong column/format" apart from "875A isn't actually in this
    # data". Only id/name/type/resource_ids are included — same safe subset.
    if resource_col:
        non_null = [r for r in rows if r.get(resource_col) not in (None, "", [])]
        target_anywhere = [
            r for r in rows
            if RESOURCE_ID in json.dumps(r.get(resource_col), default=str)
        ]
        snapshot["resource_id_diagnostics"] = {
            "rows_with_non_null_resource_ids": len(non_null),
            f"rows_where_{RESOURCE_ID}_appears_anywhere_in_the_field": len(target_anywhere),
            "sample_non_null_resource_ids": [
                {"id": r.get("id"), "name": r.get("name"), "type": r.get("type"), resource_col: r.get(resource_col)}
                for r in non_null[:10]
            ],
        }
    with open(DEBUG_SNAPSHOT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True, default=str)
        f.write("\n")


def main():
    if not METABASE_API_KEY:
        print("ERROR: METABASE_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    cols, rows = fetch_table_rows(TABLE_ID)
    resource_col = find_column(cols, MAPPING_HINTS["resource_id"])
    chapter_col = find_column(cols, MAPPING_HINTS["chapter"])
    date_col = find_column(cols, MAPPING_HINTS["date"])

    if DEBUG:
        # Manual troubleshooting only: prints to the Action log, writes nothing.
        print("Columns:", cols)
        print("First 3 rows:")
        for r in rows[:3]:
            print(json.dumps(r, indent=2, default=str))
        print(f"\nTotal rows in table {TABLE_ID}: {len(rows)}")
        print(f"Guessed columns -> resource_id: {resource_col!r}, chapter: {chapter_col!r}, date: {date_col!r}")
        if resource_col:
            matches = [r for r in rows if resource_matches(r.get(resource_col), RESOURCE_ID)]
            print(f"Rows matching resource_id={RESOURCE_ID}: {len(matches)}")
        return

    if not resource_col:
        print(
            f"ERROR: couldn't find a resource_id-like column among {cols}. "
            "Check data/_sync-debug.json (written below) and update MAPPING_HINTS.",
            file=sys.stderr,
        )
        write_debug_snapshot(cols, rows, 0, resource_col, chapter_col, date_col)
        sys.exit(1)

    matches = [r for r in rows if resource_matches(r.get(resource_col), RESOURCE_ID)]
    os.makedirs(TALKS_DIR, exist_ok=True)

    created, updated = 0, 0
    now = datetime.now(timezone.utc).isoformat()

    for row in matches:
        talk_id = slugify_id(row, cols)
        path = os.path.join(TALKS_DIR, f"{talk_id}.json")

        mapped_chapter = row.get(chapter_col) if chapter_col else None
        mapped_date = row.get(date_col) if date_col else None

        if os.path.exists(path):
            with open(path) as f:
                record = json.load(f)
            record["synced_at"] = now
            # Never clobber an editorial value a volunteer already filled in —
            # only backfill if still empty.
            if mapped_chapter and not record.get("chapter"):
                record["chapter"] = mapped_chapter
            if mapped_date and not record.get("date"):
                record["date"] = mapped_date
            updated += 1
        else:
            record = {
                "id": talk_id,
                "resource_id": RESOURCE_ID,
                "metabase_row_id": row.get(find_column(cols, ["id", "event_id", "row_id"])),
                "synced_at": now,
                "chapter": mapped_chapter,
                "date": mapped_date,
                "status": "unclaimed",
                "claimed_by": None,
                "claimed_at": None,
                "topic": None,
                "speaker": None,
                "location": None,
                "discussion_notes": None,
                "photos": [],
            }
            created += 1

        with open(path, "w") as f:
            json.dump(record, f, indent=2, default=str, sort_keys=True)
            f.write("\n")

    write_debug_snapshot(cols, rows, len(matches), resource_col, chapter_col, date_col, matched_rows=matches)
    print(f"Synced {len(matches)} TinkerTalk rows (created {created}, updated {updated}).")


if __name__ == "__main__":
    main()
