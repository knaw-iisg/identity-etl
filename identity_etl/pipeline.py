"""Builds RDF from a hand-curated crosswalk of per-entity identifiers
across the other IISG pipelines (and external registries like Wikidata) --
see README.md for the file format and why this exists.

Each entry mints one hub node, iisg.amsterdam/id/<id> -- a real, typed,
named record in its own right (not just plumbing), sdo:sameAs-linked to
every known external identifier (hub-and-spoke, not a full clique among
the externals: O(n) triples instead of O(n^2), and "give me everything in
one pass" only needs one hop from any external straight to the hub).

Deliberately dumb: no fetching, no validation beyond structural sanity,
no guessing. Every link here was asserted by a human who checked the
identifiers really do refer to the same entity.
"""
from __future__ import annotations

from rdflib import RDF, Graph, Literal, URIRef

from .prefixes import DEFAULT_GRAPH, ID, NAMESPACE_BINDINGS, SDO

RESERVED_KEYS = {"id", "name", "type"}

TYPE_MAP = {
    "Person": SDO.Person,
    "Organization": SDO.Organization,
}


def identifiers(entry: dict) -> list[str]:
    """Every non-empty value in the entry except the reserved keys (id,
    name, type -- metadata about the hub itself, not external identifiers
    to link to it)."""
    return [v for k, v in entry.items() if k not in RESERVED_KEYS and v]


def validate_entry(entry: dict) -> None:
    missing = RESERVED_KEYS - entry.keys()
    if missing:
        raise ValueError(f"entry {entry.get('name', entry)!r} is missing required field(s): {sorted(missing)}")
    if entry["type"] not in TYPE_MAP:
        raise ValueError(
            f"entry {entry['name']!r} has type {entry['type']!r}, expected one of {sorted(TYPE_MAP)}"
        )


def validate_entries(entries: list[dict]) -> None:
    seen_ids: dict[int, str] = {}
    for entry in entries:
        validate_entry(entry)
        entry_id = entry["id"]
        if entry_id in seen_ids:
            raise ValueError(
                f"id {entry_id} is used by both {seen_ids[entry_id]!r} and {entry['name']!r} -- "
                f"ids must be unique and stable, never reassigned"
            )
        seen_ids[entry_id] = entry["name"]


def hub_uri(entry: dict) -> URIRef:
    return ID[str(entry["id"])]


def next_free_id(entries: list[dict]) -> int:
    """For whoever is hand-editing identities.yaml and adding a new entry:
    the next id that isn't already taken. ids are never reused even if an
    entry is later removed -- always one more than the current max, not
    "the first gap"."""
    existing = [entry["id"] for entry in entries if "id" in entry]
    return max(existing, default=0) + 1


def add_entry(g: Graph, entry: dict) -> URIRef:
    hub = hub_uri(entry)
    g.add((hub, RDF.type, TYPE_MAP[entry["type"]]))
    g.add((hub, SDO.name, Literal(entry["name"])))
    for value in identifiers(entry):
        external = URIRef(value)
        g.add((hub, SDO.sameAs, external))
        g.add((external, SDO.sameAs, hub))
    return hub


def build_graph(entries: list[dict]) -> Graph:
    validate_entries(entries)
    g = Graph(identifier=DEFAULT_GRAPH)
    for prefix, ns in NAMESPACE_BINDINGS.items():
        g.bind(prefix, ns)
    for entry in entries:
        add_entry(g, entry)
    return g
