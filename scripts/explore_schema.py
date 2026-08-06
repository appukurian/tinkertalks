#!/usr/bin/env python3
"""
One-shot schema explorer — NOT part of the daily TinkerTalks sync. Calls
Metabase's /api/database/:id/metadata endpoint, which returns every table in
the database plus every column in each table (names and types), in a single
request. Writes data/_schema-explore.json.

Why this exists: the dev sandbox that built this project can't reach
metabase.tinkerhub.org at all (network egress is allowlisted there), so the
only way to see the real schema — including tables never referenced by
fetch_metabase.py, like whatever holds event reports, feedback, or
organizations/campuses — is to have this run for real inside the GitHub
Action (which has normal internet access) and commit the (schema-only, no
row data) result.

Safe for a public repo: this writes table names and column names/types only.
Never touches actual row data, so there's no risk of leaking anything the
`events` table (or any other table) might hold.

Env vars:
  METABASE_URL          e.g. https://metabase.tinkerhub.org
  METABASE_API_KEY      the mb_... key
  METABASE_DATABASE_ID  default 33
"""
import json
import os
import sys
import urllib.error
import urllib.request

METABASE_URL = os.environ.get("METABASE_URL", "https://metabase.tinkerhub.org").rstrip("/")
METABASE_API_KEY = os.environ.get("METABASE_API_KEY")
DATABASE_ID = int(os.environ.get("METABASE_DATABASE_ID", "33"))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO_ROOT, "data", "_schema-explore.json")


def main():
    if not METABASE_API_KEY:
        print("ERROR: METABASE_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    url = f"{METABASE_URL}/api/database/{DATABASE_ID}/metadata"
    req = urllib.request.Request(url, method="GET")
    req.add_header("x-api-key", METABASE_API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(f"Metabase returned HTTP {e.code}: {body_text}", file=sys.stderr)
        raise

    tables_out = []
    for t in payload.get("tables", []):
        tables_out.append({
            "id": t.get("id"),
            "name": t.get("name"),
            "display_name": t.get("display_name"),
            "schema": t.get("schema"),
            "description": t.get("description"),
            "estimated_row_count": t.get("estimated_row_count"),
            "fields": sorted([
                {
                    "name": f.get("name"),
                    "display_name": f.get("display_name"),
                    "base_type": f.get("base_type"),
                    "semantic_type": f.get("semantic_type"),
                    "description": f.get("description"),
                }
                for f in t.get("fields", [])
            ], key=lambda f: f["name"] or ""),
        })
    tables_out.sort(key=lambda t: t["name"] or "")

    snapshot = {
        "database_id": DATABASE_ID,
        "database_name": payload.get("name"),
        "table_count": len(tables_out),
        "tables": tables_out,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True, default=str)
        f.write("\n")

    print(f"Wrote schema for {len(tables_out)} tables to {OUT_PATH}")
    for t in tables_out:
        print(f"  - {t['name']} (id={t['id']}, {len(t['fields'])} fields)")


if __name__ == "__main__":
    main()
