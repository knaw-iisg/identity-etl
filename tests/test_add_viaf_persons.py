"""Exercises format_entry against hand-built data -- no real person data,
no network access. append_entries/merge_fields_in_file moved to
test_pipeline.py along with the rest of pipeline.py's shared utilities."""
from __future__ import annotations

from identity_etl.add_viaf_persons import format_entry


def test_format_entry_uses_authority_name_not_wikidata_label():
    entry = format_entry(
        entry_id=53,
        name="Testperson, Ada",
        entity_type="Person",
        authority_uri="https://iisg.amsterdam/authority/person/999",
        viaf_uri="https://viaf.org/viaf/123",
        wikidata_match={
            "wikidata": "https://www.wikidata.org/wiki/Q1",
            "isni": "https://isni.org/isni/456",
            "_label": "A Different Spelling",
        },
    )
    assert entry["name"] == "Testperson, Ada"
    assert entry["type"] == "Person"
    assert entry["authority"] == "https://iisg.amsterdam/authority/person/999"
    assert entry["viaf"] == "https://viaf.org/viaf/123"
    assert entry["isni"] == "https://isni.org/isni/456"
    assert "_label" not in entry


def test_format_entry_organization_type():
    entry = format_entry(
        entry_id=54,
        name="Test Institute",
        entity_type="Organization",
        authority_uri="https://iisg.amsterdam/authority/organization/999",
        viaf_uri="https://viaf.org/viaf/456",
        wikidata_match={"wikidata": "https://www.wikidata.org/wiki/Q2"},
    )
    assert entry["type"] == "Organization"
    assert entry["viaf"] == "https://viaf.org/viaf/456"
    assert entry["wikidata"] == "https://www.wikidata.org/wiki/Q2"


def test_format_entry_records_viaf_even_with_no_wikidata_match():
    """The core fix: a VIAF known locally must be recorded even when the
    Wikidata lookup finds nothing at all (wikidata_match=None)."""
    entry = format_entry(
        entry_id=55,
        name="Testperson, Bob",
        entity_type="Person",
        authority_uri="https://iisg.amsterdam/authority/person/1000",
        viaf_uri="https://viaf.org/viaf/789",
        wikidata_match=None,
    )
    assert entry["viaf"] == "https://viaf.org/viaf/789"
    assert "wikidata" not in entry
