#!/usr/bin/env python3
"""
Daily sync: pull TinkerTalk rows out of TinkerHub's Metabase and write/update
one JSON file per talk under data/talks/.

Runs inside the "Sync TinkerTalks from Metabase" GitHub Action (see
.github/workflows/fetch-metabase.yml), which has normal internet access. This
project's dev sandbox can't reach metabase.tinkerhub.org directly, so nothing
here was tested against live data before being pushed — data/_sync-debug.json
and data/_schema-explore.json are how the mapping got confirmed after the
fact. See scripts/explore_schema.py for the full 35-table schema survey that
found the tables joined below.

Env vars required:
  METABASE_URL       e.g. https://metabase.tinkerhub.org
  METABASE_API_KEY   the mb_... key (passed as the x-api-key header)

Env vars optional (all table/database IDs, from the schema survey):
  METABASE_DATABASE_ID       default 33   (database everything lives in)
  METABASE_TABLE_ID          default 50   (events)
  METABASE_SUBORG_TABLE_ID   default 41   (sub_orgs — campus/chapter identity)
  METABASE_SPEAKER_TABLE_ID  default 82   (speaker)
  METABASE_VENUE_TABLE_ID    default 76   (event_venue)
  METABASE_REPORT_TABLE_ID   default 79   (event_report — photos/materials/ratings)
  METABASE_ATTENDEE_TABLE_ID default 47   (attendees — participation counts)
  METABASE_FEEDBACK_TABLE_ID default 65   (attendee_feedback — ratings, aggregated only)
  METABASE_RESOURCE_ID       default 875A (the resource_id that marks a TinkerTalk)
  DEBUG=1                    print columns + sample rows to the Action log and
                             exit without writing or committing anything.

Privacy note: this repo is public (see README — TinkerTalks supports fork+PR
contributions from 70+ campus chapters without needing to add each one as a
collaborator). So every join below is a deliberate, narrow field pick, never a
raw row passthrough:
  - sub_orgs also holds faculty_email/phone and principal_email/phone — only
    `name` and `district` are ever pulled from it.
  - attendee_feedback has free-text fields (liked_most, how_to_improve) from
    named individuals — those are never stored; only aggregate numbers
    (averages, a count) are, so no one's individual comment becomes public
    without them realizing it would be.
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
SUBORG_TABLE_ID = int(os.environ.get("METABASE_SUBORG_TABLE_ID", "41"))
SPEAKER_TABLE_ID = int(os.environ.get("METABASE_SPEAKER_TABLE_ID", "82"))
VENUE_TABLE_ID = int(os.environ.get("METABASE_VENUE_TABLE_ID", "76"))
REPORT_TABLE_ID = int(os.environ.get("METABASE_REPORT_TABLE_ID", "79"))
ATTENDEE_TABLE_ID = int(os.environ.get("METABASE_ATTENDEE_TABLE_ID", "47"))
FEEDBACK_TABLE_ID = int(os.environ.get("METABASE_FEEDBACK_TABLE_ID", "65"))
RESOURCE_ID = os.environ.get("METABASE_RESOURCE_ID", "875A")
DEBUG = os.environ.get("DEBUG") == "1"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TALKS_DIR = os.path.join(REPO_ROOT, "data", "talks")
DEBUG_SNAPSHOT_PATH = os.path.join(REPO_ROOT, "data", "_sync-debug.json")

MAPPING_HINTS = {
    # events.resource_ids is plural (list) — see resource_matches() below.
    "resource_id": ["resource_ids", "resource_id", "resourceid", "resource id"],
    "date": ["date", "start_date", "event_date", "start date", "created_at"],
}

SAFE_SAMPLE_COLUMNS = [
    "id", "name", "type", "start_date", "end_date", "org_id", "sub_org_id",
    "unique_id", "status", "resource_ids", "location", "is_virtual",
    "description", "banner", "interests", "skills", "report_submitted",
    "seats_available", "number_of_seats",
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
        parts = [p.strip().strip('"').strip("'") for p in s.replace(",", " ").split()]
        if target in parts:
            return True
        return s == target
    return str(value) == target


def fetch_table_rows(table_id):
    url = f"{METABASE_URL}/api/dataset"
    body = json.dumps({
        "database": DATABASE_ID,
        "type": "query",
        "query": {"source-table": table_id},
        # Metabase caps interactive queries at 2000 rows by default — raise it
        # so nothing silently falls outside the window as tables grow.
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
    for c in cols:
        for cand in candidates:
            if cand.replace(" ", "").replace("_", "") in c.lower().replace(" ", "").replace("_", ""):
                return c
    return None


def slugify_id(row, cols):
    id_col = find_column(cols, ["id", "event_id", "row_id"])
    raw_id = row.get(id_col) if id_col else None
    if raw_id is None:
        raw_id = abs(hash(json.dumps(row, sort_keys=True, default=str))) % (10**8)
    return f"evt-{raw_id}"


def as_list(value):
    """Metabase serializes JSON columns (photos, materials) either as an
    already-parsed list/dict, or as a JSON string, or wrapped as {"data": [...]}
    depending on version — normalize all of those to a plain list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value.get("data") or []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return as_list(parsed)
        except json.JSONDecodeError:
            return []
    return []


def avg(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values), 2) if values else None


# ---- Lookup builders — each keyed by the id that joins back to `events` ----

def build_suborg_lookup(rows):
    # Only name + district ever leave this table — it also holds
    # faculty/principal emails and phone numbers that must never go public.
    return {r.get("id"): {"name": r.get("name"), "district": r.get("district")} for r in rows}


def build_org_lookup(rows):
    return {r.get("id"): {"name": r.get("name")} for r in rows}


def build_speaker_lookup(rows):
    out = {}
    for r in rows:
        eid = r.get("event_id")
        if eid is None:
            continue
        out.setdefault(eid, []).append({
            "name": r.get("name"),
            "tagline": r.get("tagline"),
            "avatar": r.get("avatar"),
        })
    return out


def build_venue_lookup(rows):
    out = {}
    for r in rows:
        eid = r.get("event_id")
        if eid is None or eid in out:
            continue  # first venue per event is good enough for display
        out[eid] = {
            "name": r.get("name"),
            "address": r.get("address"),
            "map_url": r.get("map_url"),
            "total_seats": r.get("total_seats"),
        }
    return out


def build_report_lookup(rows):
    out = {}
    for r in rows:
        eid = r.get("event_id")
        if eid is None:
            continue
        out[eid] = {
            "photos": as_list(r.get("photos")),
            "materials": as_list(r.get("materials")),
            "worth_organizing": r.get("worth_organizing"),
            "ratings": {
                "overall_experience": r.get("overall_experience"),
                "facilitator_effectiveness": r.get("facilitator_effectiveness"),
                "how_organized": r.get("how_organized"),
                "networking_opportunities": r.get("networking_opportunities"),
                "alignment_with_outcome": r.get("alignment_with_outcome"),
            },
        }
    return out


def build_attendee_stats(rows):
    out = {}
    for r in rows:
        eid = r.get("event_id")
        if eid is None:
            continue
        s = out.setdefault(eid, {"total": 0, "checked_in": 0})
        s["total"] += 1
        if r.get("check_in"):
            s["checked_in"] += 1
    return out


def build_feedback_stats(rows):
    grouped = {}
    for r in rows:
        eid = r.get("event_id")
        if eid is None:
            continue
        grouped.setdefault(eid, []).append(r)
    out = {}
    for eid, feedback_rows in grouped.items():
        out[eid] = {
            "count": len(feedback_rows),
            "avg_overall_experience": avg([f.get("overall_experience") for f in feedback_rows]),
            "avg_facilitator_effectiveness": avg([f.get("facilitator_effectiveness") for f in feedback_rows]),
            "avg_how_organized": avg([f.get("how_organized") for f in feedback_rows]),
            "avg_networking_opportunities": avg([f.get("networking_opportunities") for f in feedback_rows]),
        }
    return out


def write_debug_snapshot(cols, rows, matched_count, resource_col, date_col, matched_rows=None):
    type_col = find_column(cols, ["type"])
    type_breakdown = {}
    if type_col:
        for r in rows:
            v = r.get(type_col)
            type_breakdown[str(v)] = type_breakdown.get(str(v), 0) + 1

    snapshot = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "table_id": TABLE_ID,
        "columns_seen": cols,
        "total_rows_in_table": len(rows),
        "resource_id_filter": RESOURCE_ID,
        "matched_rows": matched_count,
        "guessed_mapping": {"resource_id": resource_col, "date": date_col},
        # Aggregate counts only (no row data) — helps decide whether
        # identifying TinkerTalks by `type` instead of the never-used
        # resource_ids tag would surface real historical data.
        "type_value_counts": dict(sorted(type_breakdown.items(), key=lambda kv: -kv[1])),
        "note": (
            "If a guessed_mapping value looks wrong, update MAPPING_HINTS in "
            "scripts/fetch_metabase.py to point at the correct column name."
        ),
    }
    sample_source = matched_rows if matched_rows else rows
    sample_cols = [c for c in SAFE_SAMPLE_COLUMNS if c in cols]
    snapshot["sample_values_while_debugging"] = {
        "note": (
            "Structural/non-PII columns only, up to 5 rows (matched TinkerTalks "
            "if any were found, otherwise the general table)."
        ),
        "columns": sample_cols,
        "rows": [{c: r.get(c) for c in sample_cols} for r in sample_source[:5]],
    }
    if resource_col:
        non_null = [r for r in rows if r.get(resource_col) not in (None, "", [])]
        target_anywhere = [r for r in rows if RESOURCE_ID in json.dumps(r.get(resource_col), default=str)]
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
    date_col = find_column(cols, MAPPING_HINTS["date"])

    if DEBUG:
        print("Columns:", cols)
        print("First 3 rows:")
        for r in rows[:3]:
            print(json.dumps(r, indent=2, default=str))
        print(f"\nTotal rows in table {TABLE_ID}: {len(rows)}")
        print(f"Guessed columns -> resource_id: {resource_col!r}, date: {date_col!r}")
        if resource_col:
            matches = [r for r in rows if resource_matches(r.get(resource_col), RESOURCE_ID)]
            print(f"Rows matching resource_id={RESOURCE_ID}: {len(matches)}")
        return

    if not resource_col:
        print(f"ERROR: couldn't find a resource_id-like column among {cols}.", file=sys.stderr)
        write_debug_snapshot(cols, rows, 0, resource_col, date_col)
        sys.exit(1)

    matches = [r for r in rows if resource_matches(r.get(resource_col), RESOURCE_ID)]

    # Enrichment joins — one full-table fetch each, joined in Python. See the
    # module docstring for why only narrow, whitelisted fields ever leave
    # sub_orgs and attendee_feedback.
    suborgs = build_suborg_lookup(fetch_table_rows(SUBORG_TABLE_ID)[1])
    speakers_by_event = build_speaker_lookup(fetch_table_rows(SPEAKER_TABLE_ID)[1])
    venues_by_event = build_venue_lookup(fetch_table_rows(VENUE_TABLE_ID)[1])
    reports_by_event = build_report_lookup(fetch_table_rows(REPORT_TABLE_ID)[1])
    attendee_stats = build_attendee_stats(fetch_table_rows(ATTENDEE_TABLE_ID)[1])
    feedback_stats = build_feedback_stats(fetch_table_rows(FEEDBACK_TABLE_ID)[1])

    os.makedirs(TALKS_DIR, exist_ok=True)
    created, updated = 0, 0
    now = datetime.now(timezone.utc).isoformat()
    id_col = find_column(cols, ["id", "event_id", "row_id"])

    for row in matches:
        talk_id = slugify_id(row, cols)
        path = os.path.join(TALKS_DIR, f"{talk_id}.json")
        event_id = row.get(id_col)

        existing = {}
        if os.path.exists(path):
            with open(path) as f:
                existing = json.load(f)

        suborg = suborgs.get(row.get("sub_org_id")) or {}
        report = reports_by_event.get(event_id) or {}
        attendance = attendee_stats.get(event_id) or {"total": 0, "checked_in": 0}
        feedback = feedback_stats.get(event_id)

        record = {
            "id": talk_id,
            "resource_id": RESOURCE_ID,
            "metabase_row_id": event_id,
            "synced_at": now,
            # Sync-owned — always refreshed from Metabase every run, since the
            # CMS no longer lets anyone hand-edit these (see admin/config.yml).
            "chapter": suborg.get("name"),
            "district": suborg.get("district"),
            "date": row.get(date_col) if date_col else None,
            "speakers": speakers_by_event.get(event_id, []),
            "venue": venues_by_event.get(event_id),
            "photos": report.get("photos", []),
            "materials": report.get("materials", []),
            "worth_organizing": report.get("worth_organizing"),
            "ratings": report.get("ratings"),
            "participant_count": attendance["total"],
            "checked_in_count": attendance["checked_in"],
            "feedback": feedback,
            # Volunteer-owned — the only things a claim can ever change.
            "status": existing.get("status", "unclaimed"),
            "claimed_by": existing.get("claimed_by"),
            "claimed_at": existing.get("claimed_at"),
            "discussion_notes": existing.get("discussion_notes"),
            "topic": existing.get("topic"),
        }

        if existing:
            updated += 1
        else:
            created += 1

        with open(path, "w") as f:
            json.dump(record, f, indent=2, default=str, sort_keys=True)
            f.write("\n")

    write_debug_snapshot(cols, rows, len(matches), resource_col, date_col, matched_rows=matches)
    print(f"Synced {len(matches)} TinkerTalk rows (created {created}, updated {updated}).")


if __name__ == "__main__":
    main()
