"""Builds an sdo:sameAs graph from a hand-curated crosswalk of per-person
identifiers across the other IISG pipelines (and external registries like
Wikidata) -- see README.md for the file format and why this exists.

Deliberately dumb: no fetching, no validation beyond "is this a URI",
no guessing. Every link here was asserted by a human who checked both
identifiers really are the same person.
"""
from __future__ import annotations

from rdflib import Graph, URIRef

from .prefixes import DEFAULT_GRAPH, NAMESPACE_BINDINGS, SDO


def identifiers(entry: dict) -> list[str]:
    """Every non-empty value in the entry except "name" (a human-readable
    label for maintainers, not an identifier)."""
    return [v for k, v in entry.items() if k != "name" and v]


def add_entry(g: Graph, entry: dict) -> None:
    """Emits a full clique of sdo:sameAs pairs among this entry's
    identifiers. A full clique (every pair, both directions) rather than a
    hub-and-spoke star means any one of a person's identifiers resolves
    all the others in a single SPARQL hop -- no transitive-closure query
    needed downstream (e.g. in the viewer), at the cost of O(n^2) triples
    for an entry with n identifiers. n is small here (handful of systems
    per person), so that's a non-issue."""
    uris = [URIRef(v) for v in identifiers(entry)]
    for a in uris:
        for b in uris:
            if a != b:
                g.add((a, SDO.sameAs, b))


def build_graph(entries: list[dict]) -> Graph:
    g = Graph(identifier=DEFAULT_GRAPH)
    for prefix, ns in NAMESPACE_BINDINGS.items():
        g.bind(prefix, ns)
    for entry in entries:
        add_entry(g, entry)
    return g
