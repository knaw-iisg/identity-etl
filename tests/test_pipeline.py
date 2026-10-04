"""Exercises the crosswalk -> sdo:sameAs mapping against hand-built,
entirely synthetic entries -- no real person data, no network access."""
from __future__ import annotations

from rdflib import Literal, URIRef

from identity_etl.pipeline import build_graph, identifiers
from identity_etl.prefixes import SDO

A = "https://iisg.amsterdam/authority/person/1"
B = "https://orcid.org/0000-0000-0000-0001"
C = "https://www.wikidata.org/wiki/Q1"


def test_identifiers_drops_name_and_empty_values():
    entry = {"name": "Ada Testperson", "authority": A, "orcid": "", "wikidata": None}
    assert identifiers(entry) == [A]


def test_two_identifiers_produce_a_bidirectional_pair():
    g = build_graph([{"name": "Ada Testperson", "authority": A, "orcid": B}])
    assert (URIRef(A), SDO.sameAs, URIRef(B)) in g
    assert (URIRef(B), SDO.sameAs, URIRef(A)) in g
    assert len(g) == 2


def test_three_identifiers_produce_a_full_clique():
    g = build_graph([{"name": "Ada Testperson", "authority": A, "orcid": B, "wikidata": C}])
    # every ordered pair among 3 identifiers -- 3 * 2 = 6 triples, each
    # resolvable from any single starting URI in one SPARQL hop.
    assert len(g) == 6
    for x in (A, B, C):
        for y in (A, B, C):
            if x != y:
                assert (URIRef(x), SDO.sameAs, URIRef(y)) in g


def test_single_identifier_produces_nothing():
    g = build_graph([{"name": "Ada Testperson", "authority": A}])
    assert len(g) == 0


def test_multiple_entries_are_independent():
    g = build_graph([
        {"name": "Ada Testperson", "authority": A, "orcid": B},
        {"name": "Bob Testperson", "authority": "https://iisg.amsterdam/authority/person/2",
         "orcid": "https://orcid.org/0000-0000-0000-0002"},
    ])
    assert len(g) == 4


def test_no_literals_only_uri_identifiers():
    g = build_graph([{"name": "Ada Testperson", "authority": A, "orcid": B}])
    for s, p, o in g:
        assert not isinstance(s, Literal)
        assert not isinstance(o, Literal)
