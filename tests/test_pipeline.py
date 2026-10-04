"""Exercises the crosswalk -> hub RDF mapping against hand-built, entirely
synthetic entries -- no real person/organization data, no network access."""
from __future__ import annotations

import pytest
from rdflib import RDF, Literal, URIRef

import yaml

from identity_etl.pipeline import (
    IdentifierIndex,
    append_entries,
    build_graph,
    hub_uri,
    identifiers,
    merge_fields_in_file,
    next_free_id,
    validate_entries,
    yaml_quote,
)
from identity_etl.prefixes import SDO

A = "https://iisg.amsterdam/authority/person/1"
B = "https://orcid.org/0000-0000-0000-0001"
C = "https://www.wikidata.org/wiki/Q1"


def person(id_, name, **ids):
    return {"id": id_, "name": name, "type": "Person", **ids}


def org(id_, name, **ids):
    return {"id": id_, "name": name, "type": "Organization", **ids}


def test_identifiers_drops_reserved_keys_and_empty_values():
    entry = person(1, "Ada Testperson", authority=A, orcid="", wikidata=None)
    assert identifiers(entry) == [A]


def test_hub_uri_is_flat_no_type_segment():
    assert hub_uri(person(1, "Ada")) == URIRef("https://iisg.amsterdam/id/1")
    assert hub_uri(org(2, "Test Institute")) == URIRef("https://iisg.amsterdam/id/2")


def test_hub_gets_type_and_name():
    g = build_graph([person(1, "Ada Testperson", orcid=B)])
    hub = URIRef("https://iisg.amsterdam/id/1")
    assert (hub, RDF.type, SDO.Person) in g
    assert (hub, SDO.name, Literal("Ada Testperson")) in g


def test_hub_and_spoke_not_full_clique():
    g = build_graph([person(1, "Ada Testperson", authority=A, orcid=B, wikidata=C)])
    hub = URIRef("https://iisg.amsterdam/id/1")
    # every external <-> hub, both directions
    for external in (A, B, C):
        assert (hub, SDO.sameAs, URIRef(external)) in g
        assert (URIRef(external), SDO.sameAs, hub) in g
    # NOT external <-> external directly -- that's the whole point of the hub
    assert (URIRef(A), SDO.sameAs, URIRef(B)) not in g
    assert (URIRef(B), SDO.sameAs, URIRef(A)) not in g
    # type + name (2) + 3 externals * 2 directions = 8
    assert len(g) == 8


def test_entry_with_no_external_ids_still_gets_a_hub():
    g = build_graph([person(1, "Ada Testperson")])
    hub = URIRef("https://iisg.amsterdam/id/1")
    assert (hub, RDF.type, SDO.Person) in g
    assert len(g) == 2  # just type + name, no sameAs


def test_duplicate_id_rejected():
    with pytest.raises(ValueError, match="id 1 is used by both"):
        validate_entries([person(1, "Ada Testperson"), person(1, "Bob Testperson")])


def test_missing_required_field_rejected():
    with pytest.raises(ValueError, match="missing required field"):
        validate_entries([{"name": "Ada Testperson", "type": "Person"}])  # no id


def test_unknown_type_rejected():
    with pytest.raises(ValueError, match="expected one of"):
        validate_entries([{"id": 1, "name": "Ada Testperson", "type": "Alien"}])


def test_next_free_id_is_max_plus_one_not_first_gap():
    entries = [person(1, "Ada"), person(5, "Bob"), org(3, "Test Institute")]
    assert next_free_id(entries) == 6


def test_next_free_id_on_empty_list():
    assert next_free_id([]) == 1


def test_identifier_index_finds_entry_by_any_shared_value():
    existing = person(1, "Ada Testperson", authority=A, viaf=B)
    index = IdentifierIndex([existing])
    # a new candidate that shares the viaf value but not the authority --
    # still the same entity, found via the shared field.
    found = index.find({"viaf": B, "ror": "https://ror.org/new"})
    assert found is existing


def test_identifier_index_no_match_for_unrelated_candidate():
    index = IdentifierIndex([person(1, "Ada Testperson", authority=A)])
    assert index.find({"viaf": B}) is None


def test_identifier_index_merge_adds_only_new_fields_never_overwrites():
    existing = person(1, "Ada Testperson", authority=A)
    index = IdentifierIndex([existing])
    added = index.merge(existing, {"authority": "https://different", "viaf": B, "wikidata": C})
    assert added == {"viaf": B, "wikidata": C}  # authority already present -> not touched/overwritten
    assert existing["authority"] == A  # unchanged
    assert existing["viaf"] == B
    assert B in index  # newly merged value is now findable too


def test_identifier_index_add_registers_new_entry_for_later_lookups():
    index = IdentifierIndex([])
    new_entry = person(1, "Ada Testperson", orcid=B)
    index.add(new_entry)
    assert index.find({"orcid": B}) is new_entry


def test_yaml_quote_escapes_quotes_backslashes_and_control_chars():
    cases = [
        'Smith, John "Jack"',
        "O'Brien\\Test",
        "Line1\nLine2",
        "Tab\tHere",
        "Normal Name",
        "Müller, Hans",
    ]
    for value in cases:
        line = f"name: {yaml_quote(value)}"
        assert yaml.safe_load(line)["name"] == value


def test_append_entries_preserves_existing_file_and_is_valid_yaml(tmp_path):
    identities_file = tmp_path / "identities.yaml"
    identities_file.write_text(
        '# a header comment\n\n- id: 1\n  name: "Existing Org"\n  type: "Organization"\n  ror: "https://ror.org/x"\n\n'
    )
    append_entries(identities_file, [
        {"id": 2, "name": "Testperson, Ada", "type": "Person",
         "authority": "https://iisg.amsterdam/authority/person/999",
         "viaf": "https://viaf.org/viaf/123", "wikidata": "https://www.wikidata.org/wiki/Q1"},
    ])

    text = identities_file.read_text()
    assert "# a header comment" in text  # existing content untouched
    assert 'name: "Existing Org"' in text

    parsed = yaml.safe_load(text)
    assert len(parsed) == 2
    assert parsed[1]["id"] == 2
    assert parsed[1]["authority"] == "https://iisg.amsterdam/authority/person/999"


def test_append_entries_handles_names_with_quotes_safely(tmp_path):
    identities_file = tmp_path / "identities.yaml"
    identities_file.write_text("")
    append_entries(identities_file, [
        {"id": 1, "name": 'Smith, John "Jack"', "type": "Person", "authority": "https://a"},
    ])
    parsed = yaml.safe_load(identities_file.read_text())
    assert parsed[0]["name"] == 'Smith, John "Jack"'


def test_append_entries_field_order_is_stable(tmp_path):
    identities_file = tmp_path / "identities.yaml"
    identities_file.write_text("")
    append_entries(identities_file, [
        {"id": 1, "name": "Ada", "type": "Person", "authority": "https://a", "orcid": "https://o",
         "wikidata": "https://w", "viaf": "https://v"},
    ])
    lines = identities_file.read_text().splitlines()
    keys = [line.strip().split(":")[0] for line in lines if line.strip() and not line.startswith("#")]
    assert keys == ["- id", "name", "type", "authority", "viaf", "wikidata", "orcid"]


def test_append_entries_noop_on_empty_list(tmp_path):
    identities_file = tmp_path / "identities.yaml"
    identities_file.write_text("original content\n")
    append_entries(identities_file, [])
    assert identities_file.read_text() == "original content\n"


def test_merge_fields_in_file_inserts_into_the_right_block_only(tmp_path):
    identities_file = tmp_path / "identities.yaml"
    identities_file.write_text(
        '- id: 1\n  name: "First"\n  type: "Person"\n  authority: "https://a1"\n\n'
        '- id: 2\n  name: "Second"\n  type: "Person"\n  authority: "https://a2"\n\n'
    )
    merge_fields_in_file(identities_file, entry_id=2, added_fields={"viaf": "https://viaf.org/viaf/999"})

    parsed = yaml.safe_load(identities_file.read_text())
    assert len(parsed) == 2  # no new entry created
    assert "viaf" not in parsed[0]  # entry 1 untouched
    assert parsed[1]["viaf"] == "https://viaf.org/viaf/999"
    assert parsed[1]["authority"] == "https://a2"  # existing fields preserved


def test_merge_fields_in_file_noop_when_nothing_added(tmp_path):
    identities_file = tmp_path / "identities.yaml"
    original = '- id: 1\n  name: "First"\n  type: "Person"\n  authority: "https://a1"\n\n'
    identities_file.write_text(original)
    merge_fields_in_file(identities_file, entry_id=1, added_fields={})
    assert identities_file.read_text() == original
