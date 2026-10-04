"""Command-line entry point: ``python -m identity_etl.add_viaf_persons``.

Unlike discover_organizations.py, this one writes directly to
identities.yaml rather than only suggesting -- VIAF-id matching via
Wikidata's P214 is an unambiguous reverse lookup (same reasoning as ROR),
and the name used is always the authority record's own sdo:name (never
Wikidata's label), so there's nothing here that needs a human eyeballing
each entry before it's trustworthy.

Finds every authority record of the given --type (Person by default, or
Organization) that already carries a VIAF sdo:sameAs (authorities-etl's
own MARC-035-derived link), looks each VIAF id up on Wikidata in batches,
and for every one that matched:

- if none of the identifiers found (the VIAF itself, or anything else
  Wikidata returned alongside it -- ISNI, GND, ORCID, ...) belong to an
  existing entry already, appends a brand-new one;
- if one of them *does* -- most commonly now: mint_all_entities.py
  already bare-minted this exact authority record with nothing but its
  authority: field, and this is the first pass to find it a VIAF too --
  merges the new fields into that existing entry rather than creating a
  second hub. See pipeline.IdentifierIndex.

Safe to re-run: skips only by the VIAF *value* already being known (we've
already looked this one up), not by the authority URI being known --
after mint_all_entities.py, every authority record's URI is already
known from the moment it's bare-minted, so filtering on that would skip
every candidate before ever attempting the enrichment merge.
"""
from __future__ import annotations

import argparse

import requests
import yaml

from .cli import resolve_data_dir
from .pipeline import IdentifierIndex, append_entries, merge_fields_in_file, next_free_id, validate_entries
from .wikidata import bulk_lookup_by_viaf

DEFAULT_ENDPOINT = "http://localhost:7878"

TYPE_SDO = {"Person": "https://schema.org/Person", "Organization": "https://schema.org/Organization"}

# Selective by construction -- anchored on sdo:sameAs existing at all,
# which narrows ~430K authority Person records down to ~18K before the
# VIAF-prefix filter even runs. An earlier, differently-shaped query
# elsewhere in this project (an unbound "?s ?p ?o" scan) timed out at 30s;
# this one (measured live) returns all ~18,195 Person rows in well under
# a second.
AUTHORITY_VIAF_QUERY = """
SELECT ?s ?name ?viaf WHERE {{
  GRAPH <https://iisg.amsterdam/graph/authority> {{
    ?s a <{sdo_type}> ; <https://schema.org/sameAs> ?viaf ; <https://schema.org/name> ?name .
    FILTER(STRSTARTS(STR(?viaf), "http://viaf.org/"))
  }}
}}
"""


def fetch_viaf_linked_authorities(endpoint: str, entity_type: str) -> list[dict]:
    """[{"authority": uri, "name": str, "viaf_id": bare id}, ...]. A
    handful of authority records carry more than one VIAF sameAs (rare);
    each becomes its own row here, deduplicated by authority URI
    downstream (first one wins) since an identities.yaml entry has a
    single viaf: field."""
    response = requests.get(
        endpoint,
        params={"query": AUTHORITY_VIAF_QUERY.format(sdo_type=TYPE_SDO[entity_type])},
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


def format_entry(entry_id: int, name: str, entity_type: str, authority_uri: str, wikidata_match: dict[str, str]) -> dict:
    entry = {"id": entry_id, "name": name, "type": entity_type, "authority": authority_uri}
    for field, value in wikidata_match.items():
        if field != "_label":
            entry[field] = value
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Match VIAF-linked authority records against Wikidata and add them directly "
                     "to identities.yaml (new entries, or merged into existing ones)"
    )
    parser.add_argument("--data-dir", help="same --data-dir as python -m identity_etl.cli")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"SPARQL endpoint (default: {DEFAULT_ENDPOINT})")
    parser.add_argument("--type", choices=["Person", "Organization"], default="Person")
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

    print(f"Fetching VIAF-linked authority {args.type} records...")
    authority_rows = fetch_viaf_linked_authorities(args.endpoint, args.type)
    by_authority = {row["authority"]: row for row in authority_rows}  # first VIAF wins on duplicates
    # Filtered on the VIAF *value*, not the authority URI -- see module
    # docstring for why that distinction matters now.
    new_rows = [
        row for row in by_authority.values()
        if f"https://viaf.org/viaf/{row['viaf_id']}" not in index
    ]

    print(
        f"{len(by_authority)} VIAF-linked authority {args.type} record(s) in the graph, "
        f"{len(new_rows)} with a VIAF not already looked up"
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

        entry = format_entry(next_id, row["name"], args.type, row["authority"], match)
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
