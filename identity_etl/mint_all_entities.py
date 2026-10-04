"""Command-line entry point: ``python -m identity_etl.mint_all_entities``.

Mints an IISG id for *every* distinct sdo:Person/sdo:Organization node
anywhere in the merged knowledge graph -- archive, biblio, dataverse,
findingaid, authorities, orcid, events -- regardless of whether that node
already carries a recognized external identifier or is just a bare name
with a locally-minted, pipeline-internal URI.

This deliberately inverts this repo's earlier discovery scripts
(discover_organizations.py, add_viaf_persons.py), which only created an
entry for an entity that already matched something on Wikidata. Most
entities in the full population won't match anything external at all --
having only the IISG id is the normal, expected end state for most of
them, not a gap. External-identifier enrichment (ROR/VIAF/ORCID/Wikidata
matching) is a separate, later pass per entity, not done here.

Does NOT attempt to deduplicate bare-name entities that represent the
same real person/organization under different spellings across pipelines
(e.g. authority's "Zijdeman, Richard" vs dataverse's "Richard Zijdeman")
-- that needs its own pass, and is explicitly out of scope for this one.
What it *does* still do is skip any entity URI that's already a known
identifier value on an existing identities.yaml entry (via
IdentifierIndex) -- e.g. a ROR or VIAF-linked authority record already
covered by an earlier pass gets no second, redundant hub.

No network calls -- purely local SPARQL + file writes. All classification
is by URI scheme; nothing here invents an identifier a source doesn't
already assert.
"""
from __future__ import annotations

import argparse

import requests
import yaml

from .cli import resolve_data_dir
from .pipeline import IdentifierIndex, append_entries, next_free_id, validate_entries

DEFAULT_ENDPOINT = "http://localhost:7878"

# Every distinct Person/Organization node across every named graph, with
# its own rdf:type and (where asserted) sdo:name. Measured live: 555,609
# rows in ~2.6s -- selective by construction (?s a ?type with ?type
# restricted to exactly two values), nothing like the unbound "?s ?p ?o"
# scan that timed out elsewhere in this project.
ALL_ENTITIES_QUERY = """
SELECT ?s ?type (SAMPLE(?n) AS ?name) WHERE {
  GRAPH ?g { ?s a ?type . FILTER(?type IN (<https://schema.org/Person>, <https://schema.org/Organization>)) }
  OPTIONAL { GRAPH ?g2 { ?s <https://schema.org/name> ?n } }
} GROUP BY ?s ?type
"""

TYPE_MAP = {
    "https://schema.org/Person": "Person",
    "https://schema.org/Organization": "Organization",
}

# A node's own URI, classified by scheme -- this is what ends up in the
# matching identity-etl field when that URI isn't already covered by an
# existing entry. A URI matching none of these (a dataverse-etl
# #creator-<hash>/#org-<hash> fragment, an orcid-etl urn:orcidgraph:org:
# fallback, ...) is a locally-minted, non-dereferenceable-elsewhere id --
# it gets an IISG id and a name, nothing else; there's no external system
# it means anything to.
URI_SCHEME_FIELDS = (
    ("https://iisg.amsterdam/authority/", "authority"),
    ("https://orcid.org/", "orcid"),
    ("https://ror.org/", "ror"),
    ("https://viaf.org/", "viaf"),
    ("https://isni.org/", "isni"),
    ("https://d-nb.info/gnd/", "gnd"),
    ("https://id.loc.gov/", "lcauth"),
)


def classify_uri(uri: str) -> str | None:
    for prefix, field in URI_SCHEME_FIELDS:
        if uri.startswith(prefix):
            return field
    return None


def fetch_all_entities(endpoint: str) -> list[dict]:
    """[{"uri": str, "type": "Person"|"Organization", "name": str}, ...].
    A node missing sdo:name entirely (rare -- ~33 of 555,609 measured
    live) falls back to its own URI's last path segment."""
    response = requests.get(
        endpoint,
        params={"query": ALL_ENTITIES_QUERY},
        headers={"Accept": "application/sparql-results+json"},
        timeout=120,
    )
    response.raise_for_status()
    rows = []
    for row in response.json()["results"]["bindings"]:
        uri = row["s"]["value"]
        rows.append({
            "uri": uri,
            "type": TYPE_MAP[row["type"]["value"]],
            "name": row["name"]["value"] if "name" in row else uri.rsplit("/", 1)[-1],
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mint an IISG id for every Person/Organization entity across the whole merged "
                     "graph, identified or not"
    )
    parser.add_argument("--data-dir", help="same --data-dir as python -m identity_etl.cli")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"SPARQL endpoint (default: {DEFAULT_ENDPOINT})")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print counts without writing to identities.yaml",
    )
    args = parser.parse_args(argv)

    data_dir = resolve_data_dir(args.data_dir)
    identities_file = data_dir / "identities.yaml"
    entries = yaml.safe_load(identities_file.read_text()) if identities_file.exists() else []
    entries = entries or []
    index = IdentifierIndex(entries)

    print("Fetching every Person/Organization entity across the merged graph...")
    all_entities = fetch_all_entities(args.endpoint)
    new_rows = [row for row in all_entities if row["uri"] not in index]

    print(f"{len(all_entities)} total distinct entities, {len(new_rows)} not already known")
    if not new_rows:
        return 0

    with_field = 0
    next_id = next_free_id(entries)
    new_entries = []
    for row in new_rows:
        field = classify_uri(row["uri"])
        entry = {"id": next_id, "name": row["name"], "type": row["type"]}
        if field:
            entry[field] = row["uri"]
            with_field += 1
        index.add(entry)
        new_entries.append(entry)
        next_id += 1

    print(
        f"{len(new_entries)} new entries to mint -- {with_field} with a recognized external "
        f"identifier field (from the entity's own URI scheme), "
        f"{len(new_entries) - with_field} with only an IISG id (locally-minted source URI, "
        f"no recognized external scheme)"
    )

    if args.dry_run:
        print("--dry-run: not writing anything.")
        return 0

    validate_entries(entries + new_entries)  # fail before writing anything, not partway through
    append_entries(identities_file, new_entries)
    print(f"Appended {len(new_entries)} entries to {identities_file}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
