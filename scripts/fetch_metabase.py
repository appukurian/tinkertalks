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
  METABASE_TABLE_ID    default 50   (the `events` table)
  METABASE_RESOURCE_ID default 875A (the resource_id that marks a TinkerTalk)
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
import urllib.request
from datetime import datetime, timezone

METABASE_URL = os.environ.get("METABASE_URL", "https://metabase.tinkerhub.org").rstrip("/")
METABASE_API_KEY = os.environ.get("METABASE_API_KEY")
TABLE_ID = os.environ.get("METABASE_TABLE_ID", "50")
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
    "resource_id": ["resource_id", "resourceid", "resource id"],
    "chapter": ["chapter", "campus", "organiser", "organizer", "chapter_name", "campus_name", "name"],
    "date": ["date", "start_date", "event_date", "start date", "created_at"],
}

# Only these mapped, public-safe fields ever get written into a talk record.
# Anything else in the `events` row (phone numbers, internal notes, whatever
# else that table happens to hold) is deliberately dropped, not stored.
PUBLIC_FIELDS = ("chapter", "date")


def fetch_table_rows(table_id):
    url = f"{METABASE_URL}/api/table/{table_id}/query"
    req = urllib.request.Request(url, method="POST")
    req.add_header("x-api-key", METABASE_API_KEY)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=b"{}", timeout=30) as resp:
        payload = json.loads(resp.read())
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


def write_debug_snapshot(cols, total_rows, matched_count, resource_col, chapter_col, date_col):
    # Column NAMES only — no cell values — so this is safe to commit to a
    # public repo even before we've confirmed what's actually inside them.
    snapshot = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "table_id": TABLE_ID,
        "columns_seen": cols,
        "total_rows_in_table": total_rows,
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
    with open(DEBUG_SNAPSHOT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True)
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
            matches = [r for r in rows if str(r.get(resource_col)) == str(RESOURCE_ID)]
            print(f"Rows matching resource_id={RESOURCE_ID}: {len(matches)}")
        return

    if not resource_col:
        print(
            f"ERROR: couldn't find a resource_id-like column among {cols}. "
            "Check data/_sync-debug.json (written below) and update MAPPING_HINTS.",
            file=sys.stderr,
        )
        write_debug_snapshot(cols, len(rows), 0, resource_col, chapter_col, date_col)
        sys.exit(1)

    matches = [r for r in rows if str(r.get(resource_col)) == str(RESOURCE_ID)]
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

    write_debug_snapshot(cols, len(rows), len(matches), resource_col, chapter_col, date_col)
    print(f"Synced {len(matches)} TinkerTalk rows (created {created}, updated {updated}).")


if __name__ == "__main__":
    main()
