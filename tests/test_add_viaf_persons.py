"""Exercises format_entry, append_entries and merge_fields_in_file against
hand-built data -- no real person data, no network access."""
from __future__ import annotations

import yaml

from identity_etl.add_viaf_persons import append_entries, format_entry, merge_fields_in_file


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


def test_append_entries_preserves_existing_file_and_is_valid_yaml(tmp_path):
    identities_file = tmp_path / "identities.yaml"
    identities_file.write_text(
        '# a header comment\n\n- id: 1\n  name: "Existing Org"\n  type: "Organization"\n  ror: "https://ror.org/x"\n\n'
    )
    new_entries = [
        {"id": 2, "name": "Testperson, Ada", "type": "Person",
         "authority": "https://iisg.amsterdam/authority/person/999",
         "viaf": "https://viaf.org/viaf/123", "wikidata": "https://www.wikidata.org/wiki/Q1"},
    ]
    append_entries(identities_file, new_entries)

    text = identities_file.read_text()
    assert "# a header comment" in text  # existing content untouched
    assert 'name: "Existing Org"' in text

    parsed = yaml.safe_load(text)
    assert len(parsed) == 2
    assert parsed[1]["id"] == 2
    assert parsed[1]["authority"] == "https://iisg.amsterdam/authority/person/999"


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
