"""Command-line entry point: ``python -m identity_etl.add_viaf_persons``.

Unlike discover_organizations.py, this one writes directly to
identities.yaml rather than only suggesting -- VIAF-id matching via
Wikidata's P214 is an unambiguous reverse lookup (same reasoning as ROR),
and the name used is always the authority record's own sdo:name (never
Wikidata's label), so there's nothing here that needs a human eyeballing
each entry before it's trustworthy.

Finds every authority Person record in the merged graph that already
carries a VIAF sdo:sameAs (authorities-etl's own MARC-035-derived link),
looks each VIAF id up on Wikidata in batches, and for every one that
matched:

- if none of the identifiers found (the VIAF itself, or anything else
  Wikidata returned alongside it -- ISNI, GND, ORCID, ...) belong to an
  existing entry already, appends a brand-new one;
- if one of them *does* -- e.g. this VIAF's Wikidata item also carries an
  ORCID that's already on an entry some other discovery pass created --
  merges the new fields into that existing entry instead of creating a
  second hub for the same real person. See pipeline.IdentifierIndex.

Safe to re-run: authority records already known (by their authority: URI,
or by any identifier already attached to some other entry) are skipped.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import requests
import yaml

from .cli import resolve_data_dir
from .pipeline import IdentifierIndex, next_free_id, validate_entries
from .wikidata import bulk_lookup_by_viaf

DEFAULT_ENDPOINT = "http://localhost:7878"

# Selective by construction -- anchored on sdo:sameAs existing at all,
# which narrows ~430K authority Person records down to ~18K before the
# VIAF-prefix filter even runs. An earlier, differently-shaped query
# elsewhere in this project (an unbound "?s ?p ?o" scan) timed out at 30s;
# this one (measured live) returns all ~18,195 rows in well under a
# second.
AUTHORITY_VIAF_QUERY = """
SELECT ?s ?name ?viaf WHERE {
  GRAPH <https://iisg.amsterdam/graph/authority> {
    ?s a <https://schema.org/Person> ; <https://schema.org/sameAs> ?viaf ; <https://schema.org/name> ?name .
    FILTER(STRSTARTS(STR(?viaf), "http://viaf.org/"))
  }
}
"""


def fetch_viaf_linked_authorities(endpoint: str) -> list[dict]:
    """[{"authority": uri, "name": str, "viaf_id": bare id}, ...]. A
    handful of authority records carry more than one VIAF sameAs (rare);
    each becomes its own row here, deduplicated by authority URI
    downstream (first one wins) since an identities.yaml entry has a
    single viaf: field."""
    response = requests.get(
        endpoint,
        params={"query": AUTHORITY_VIAF_QUERY},
        headers={"Accept": "application/sparql-results+json"},
        timeout=30,
    )
    response.raise_for_status()
    rows = []
    for row in response.json()["results"]["bindings"]:
        rows.append({
            "authority": row["s"]["value"],
            "name": row["name"]["value"],
            "viaf_id": row["viaf"]["value"].rsplit("/", 1)[-1],
        })
    return rows


def format_entry(entry_id: int, name: str, authority_uri: str, wikidata_match: dict[str, str]) -> dict:
    entry = {"id": entry_id, "name": name, "type": "Person", "authority": authority_uri}
    for field, value in wikidata_match.items():
        if field != "_label":
            entry[field] = value
    return entry


FIELD_ORDER = ("authority", "viaf", "wikidata", "isni", "gnd", "lcauth", "orcid", "ror")


def append_entries(identities_file, new_entries: list[dict]) -> None:
    """Appends in identities.yaml's existing hand-written style (quoted
    scalars, one blank line between entries) rather than re-serializing
    the whole file through yaml.dump, which would reformat every existing
    entry too and bury this change in an unreviewable diff."""
    lines = []
    for entry in new_entries:
        lines.append(f"- id: {entry['id']}")
        lines.append(f'  name: "{entry["name"]}"')
        lines.append(f'  type: "{entry["type"]}"')
        for key in FIELD_ORDER:
            if key in entry:
                lines.append(f'  {key}: "{entry[key]}"')
        lines.append("")
    with open(identities_file, "a") as f:
        f.write("\n".join(lines) + "\n")


def merge_fields_in_file(identities_file, entry_id: int, added_fields: dict[str, str]) -> None:
    """Patches newly-merged fields into an *existing* entry's block
    in-place (located by its "- id: {entry_id}" line), rather than
    rewriting the whole file -- same reasoning as append_entries: keep
    the diff to exactly what changed, not a full reformat."""
    if not added_fields:
        return
    path = Path(identities_file)
    lines = path.read_text().split("\n")
    start = next(i for i, line in enumerate(lines) if line.strip() == f"- id: {entry_id}")
    end = start + 1
    while end < len(lines) and lines[end].strip():
        end += 1
    insert = [f'  {key}: "{value}"' for key, value in added_fields.items() if key in FIELD_ORDER]
    lines[end:end] = insert
    path.write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Match VIAF-linked authority Person records against Wikidata and add them "
                     "directly to identities.yaml (new entries, or merged into existing ones)"
    )
    parser.add_argument("--data-dir", help="same --data-dir as python -m identity_etl.cli")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"SPARQL endpoint (default: {DEFAULT_ENDPOINT})")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print what would be added/merged without writing to identities.yaml",
    )
    args = parser.parse_args(argv)

    data_dir = resolve_data_dir(args.data_dir)
    identities_file = data_dir / "identities.yaml"
    entries = yaml.safe_load(identities_file.read_text()) if identities_file.exists() else []
    entries = entries or []
    index = IdentifierIndex(entries)

    print("Fetching VIAF-linked authority Person records...")
    authority_rows = fetch_viaf_linked_authorities(args.endpoint)
    by_authority = {row["authority"]: row for row in authority_rows}  # first VIAF wins on duplicates
    new_rows = [row for uri, row in by_authority.items() if uri not in index]

    print(
        f"{len(by_authority)} VIAF-linked authority Person record(s) in the graph, "
        f"{len(new_rows)} not already known"
    )
    if not new_rows:
        return 0
    print(f"Looking up {len(new_rows)} VIAF ids on Wikidata (batched, ~{len(new_rows) // 200 + 1} requests)...")

    viaf_ids = [row["viaf_id"] for row in new_rows]
    matches = bulk_lookup_by_viaf(viaf_ids)
    print(f"{len(matches)}/{len(new_rows)} matched on Wikidata.")

    next_id = next_free_id(entries)
    new_entries = []
    merges: list[tuple[int, dict]] = []  # (existing entry's id, fields that were added to it)
    for row in new_rows:
        match = matches.get(row["viaf_id"])
        if not match:
            continue
        candidate = dict(match)
        candidate["authority"] = row["authority"]

        existing = index.find(candidate)
        if existing:
            added = index.merge(existing, candidate)
            if added:
                merges.append((existing["id"], added))
            continue

        entry = format_entry(next_id, row["name"], row["authority"], match)
        index.add(entry)
        new_entries.append(entry)
        next_id += 1

    print(f"{len(new_entries)} new entries, {len(merges)} merged into existing entries (co-occurring identifiers).")

    if args.dry_run:
        print("--dry-run: not writing anything.")
        return 0

    validate_entries(entries + new_entries)  # fail before writing anything, not partway through
    append_entries(identities_file, new_entries)
    for entry_id, added_fields in merges:
        merge_fields_in_file(identities_file, entry_id, added_fields)
    print(f"Appended {len(new_entries)} entries and applied {len(merges)} merges to {identities_file}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
