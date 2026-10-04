"""Command-line entry point: ``python -m identity_etl.discover_organizations``.

Finds every ROR-identified organization already asserted somewhere in the
merged knowledge graph (via a live SPARQL endpoint) that isn't yet in
identities.yaml, looks each one up on Wikidata by its ROR id (an
unambiguous reverse lookup, not name-matching), and prints ready-to-paste
YAML entries -- never writes to identities.yaml itself.

The suggested name is the ROR URI's *own* sdo:name (both orcid-etl and
dataverse-etl correctly mint a proper sdo:Organization node for every ROR
they use -- confirmed live, 50/50), falling back to Wikidata's label only
on the rare organization with no local name at all.

(An earlier version of this query got this wrong -- it looked for
sdo:name on whatever subject merely *pointed at* a ROR, e.g. a dataset's
creator, rather than the ROR URI itself as subject. That surfaced
believable-looking but wrong names like "Baten, Joerg" for what was
actually a university, and was mistakenly first written up as a
dataverse-etl data bug before this fix -- it was a bug in this query.)

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

# Split into two cheap, selective queries rather than one query with an
# unbound "?ror ?p ?o" scan -- that shape forces a full triple-store scan
# (measured live: 4.7 billion estimated cost units, 30s timeout, killed)
# since nothing anchors it to a small result set up front. Each query
# below starts from something selective instead: a ror.org-prefixed
# *object* (affiliations etc. point at one), or the (comparatively rare)
# sdo:Organization type (measured live: ~300ms).
ROR_OBJECTS_QUERY = """
SELECT DISTINCT ?ror WHERE {
  GRAPH ?g { ?s ?p ?ror . FILTER(STRSTARTS(STR(?ror), "https://ror.org/")) FILTER(!CONTAINS(STR(?ror), "#")) }
}
"""
ROR_NAMES_QUERY = """
SELECT ?ror ?name WHERE {
  GRAPH ?g { ?ror a <https://schema.org/Organization> ; <https://schema.org/name> ?name .
             FILTER(STRSTARTS(STR(?ror), "https://ror.org/")) }
}
"""


def _query(endpoint: str, sparql: str) -> list[dict]:
    response = requests.get(
        endpoint,
        params={"query": sparql},
        headers={"Accept": "application/sparql-results+json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["results"]["bindings"]


def fetch_known_rors(endpoint: str) -> dict[str, str]:
    """ror_id (bare, e.g. "05dq4pp56") -> its own sdo:name from the graph,
    or its bare id if (rare -- not observed in this project's own data)
    nothing anywhere asserts one."""
    names = {
        row["ror"]["value"].rsplit("/", 1)[-1]: row["name"]["value"]
        for row in _query(endpoint, ROR_NAMES_QUERY)
    }
    result = {}
    for row in _query(endpoint, ROR_OBJECTS_QUERY):
        ror_id = row["ror"]["value"].rsplit("/", 1)[-1]
        result[ror_id] = names.get(ror_id, ror_id)
    return result


def format_entry(entry_id: int, fallback_name: str, ror_id: str, wikidata_match: dict[str, str] | None) -> str:
    wikidata_match = wikidata_match or {}
    wikidata_label = wikidata_match.get("_label")
    # fetch_known_rors falls back to the bare id itself when the ROR has
    # no sdo:name anywhere in the graph -- treat that as "no local name",
    # not a real one.
    has_local_name = fallback_name != ror_id
    name = fallback_name if has_local_name else (wikidata_label or fallback_name)
    identifier_fields = {k: v for k, v in wikidata_match.items() if k not in ("_label", "ror")}

    lines = [
        f"- id: {entry_id}",
        f'  name: "{name}"',
        '  type: "Organization"',
        f'  ror: "https://ror.org/{ror_id}"',
    ]
    for field, value in identifier_fields.items():
        lines.append(f'  {field}: "{value}"')
    if not has_local_name and not wikidata_label:
        lines.append(
            "  # no sdo:name found for this ROR anywhere in the graph, and no usable "
            "Wikidata label either -- verify the ROR id and add a name by hand."
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
        local_name = new_rors[ror_id]
        if local_name != ror_id:
            return local_name.lower()
        match = matches.get(ror_id) or {}
        return (match.get("_label") or local_name).lower()

    next_id = next_free_id(entries)
    for ror_id in sorted(new_rors, key=sort_key):
        print(format_entry(next_id, new_rors[ror_id], ror_id, matches.get(ror_id)))
        print()
        next_id += 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
