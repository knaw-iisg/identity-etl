"""Command-line entry point: ``python -m identity_etl.discover_organizations``.

Finds every ROR-identified organization already asserted somewhere in the
merged knowledge graph (via a live SPARQL endpoint) that isn't yet in
identities.yaml, looks each one up on Wikidata by its ROR id (an
unambiguous reverse lookup, not name-matching), and prints ready-to-paste
YAML entries -- never writes to identities.yaml itself.

A ROR here doesn't always come from a proper sdo:Organization node:
orcid-etl mints one (name, address, the works), but dataverse-etl was
found (live) to sometimes point a dataset creator's sdo:affiliation
straight at a bare ROR URI, with no local node describing the
organization at all. So the suggested name always prefers Wikidata's own
label over anything pulled from the local graph -- see fetch_known_rors
and bulk_lookup_by_ror's "_label".

Safe to re-run: organizations already present (by ror: value) are skipped.
"""
from __future__ import annotations

import argparse

import requests
import yaml

from .cli import resolve_data_dir
from .pipeline import next_free_id
from .wikidata import bulk_lookup_by_ror

DEFAULT_ENDPOINT = "http://localhost:7878"

# Every ror.org URI anywhere in the store, plus -- only as a last-resort
# fallback when Wikidata has no match at all -- a name pulled from
# whichever node happens to assert sdo:name near that ROR. That fallback
# is NOT reliable: confirmed live that dataverse-etl's bare-ROR-as-
# affiliation pattern means this can be the *person's* name (a dataset
# creator), not the organization's. Flagged in the output, not silently
# trusted.
KNOWN_RORS_QUERY = """
SELECT ?ror (SAMPLE(?name) AS ?label) WHERE {
  GRAPH ?g {
    ?s ?p ?ror .
    FILTER(STRSTARTS(STR(?ror), "https://ror.org/"))
    FILTER(!CONTAINS(STR(?ror), "#"))
    OPTIONAL { ?s <http://schema.org/name> ?n1 }
    OPTIONAL { ?s <https://schema.org/name> ?n2 }
    BIND(COALESCE(?n1, ?n2) AS ?name)
  }
} GROUP BY ?ror
"""


def fetch_known_rors(endpoint: str) -> dict[str, str]:
    """ror_id (bare, e.g. "05dq4pp56") -> a *fallback* name for it, from
    the graph itself -- see the module docstring for why this alone isn't
    trustworthy. A ROR with no sdo:name anywhere nearby falls back to its
    own id as the "name"."""
    response = requests.get(
        endpoint,
        params={"query": KNOWN_RORS_QUERY},
        headers={"Accept": "application/sparql-results+json"},
        timeout=30,
    )
    response.raise_for_status()
    result = {}
    for row in response.json()["results"]["bindings"]:
        ror_id = row["ror"]["value"].rsplit("/", 1)[-1]
        result[ror_id] = row.get("label", {}).get("value") or ror_id
    return result


def format_entry(entry_id: int, fallback_name: str, ror_id: str, wikidata_match: dict[str, str] | None) -> str:
    wikidata_match = wikidata_match or {}
    wikidata_label = wikidata_match.get("_label")
    name = wikidata_label or fallback_name
    identifier_fields = {k: v for k, v in wikidata_match.items() if k not in ("_label", "ror")}

    lines = [
        f"- id: {entry_id}",
        f'  name: "{name}"',
        '  type: "Organization"',
        f'  ror: "https://ror.org/{ror_id}"',
    ]
    for field, value in identifier_fields.items():
        lines.append(f'  {field}: "{value}"')
    if not wikidata_label:
        reason = (
            "no Wikidata match found" if not wikidata_match
            else "matched on Wikidata, but that item has no label in any language"
        )
        lines.append(
            f"  # {reason} -- this name is a local-graph fallback and may be WRONG "
            "(e.g. a co-occurring person's name, not the organization's). Verify."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Suggest identity-etl entries for ROR-identified organizations already in the graph"
    )
    parser.add_argument("--data-dir", help="same --data-dir as python -m identity_etl.cli")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"SPARQL endpoint (default: {DEFAULT_ENDPOINT})")
    args = parser.parse_args(argv)

    data_dir = resolve_data_dir(args.data_dir)
    identities_file = data_dir / "identities.yaml"
    entries = yaml.safe_load(identities_file.read_text()) if identities_file.exists() else []
    entries = entries or []

    known_rors = {v.rsplit("/", 1)[-1] for e in entries for k, v in e.items() if k == "ror" and v}

    all_rors = fetch_known_rors(args.endpoint)
    new_rors = {r: name for r, name in all_rors.items() if r not in known_rors}

    print(
        f"{len(all_rors)} ROR-identified organization(s) in the graph, "
        f"{len(new_rors)} not already in identities.yaml",
        end="",
    )
    if not new_rors:
        print(".")
        return 0
    print(" -- looking each up on Wikidata...\n")

    matches = bulk_lookup_by_ror(list(new_rors))
    print(f"{len(matches)}/{len(new_rors)} matched on Wikidata. Suggested entries (verify, then paste into identities.yaml):\n")

    def sort_key(ror_id: str) -> str:
        match = matches.get(ror_id) or {}
        return (match.get("_label") or new_rors[ror_id]).lower()

    next_id = next_free_id(entries)
    for ror_id in sorted(new_rors, key=sort_key):
        print(format_entry(next_id, new_rors[ror_id], ror_id, matches.get(ror_id)))
        print()
        next_id += 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
