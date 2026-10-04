"""Exercises format_entry against hand-built data -- no real person data,
no network access. append_entries/merge_fields_in_file moved to
test_pipeline.py along with the rest of pipeline.py's shared utilities."""
from __future__ import annotations

from identity_etl.add_viaf_persons import format_entry


def test_format_entry_uses_authority_name_not_wikidata_label():
    entry = format_entry(
        entry_id=53,
        name="Testperson, Ada",
        authority_uri="https://iisg.amsterdam/authority/person/999",
        wikidata_match={
            "wikidata": "https://www.wikidata.org/wiki/Q1",
            "viaf": "https://viaf.org/viaf/123",
            "isni": "https://isni.org/isni/456",
            "_label": "A Different Spelling",
        },
    )
    assert entry["name"] == "Testperson, Ada"
    assert entry["type"] == "Person"
    assert entry["authority"] == "https://iisg.amsterdam/authority/person/999"
    assert entry["viaf"] == "https://viaf.org/viaf/123"
    assert "_label" not in entry
