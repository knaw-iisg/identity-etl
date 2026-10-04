"""Exercises format_entry's name-preference logic against hand-built data
-- no network access.

fallback_name here means "the ROR URI's own sdo:name from the graph" (see
fetch_known_rors) -- reliable, since both orcid-etl and dataverse-etl mint
a proper sdo:Organization node for every ROR they use (confirmed live,
50/50). It equals ror_id itself only when fetch_known_rors found no local
name at all, which is the one case Wikidata's label should be preferred."""
from __future__ import annotations

from identity_etl.discover_organizations import format_entry


def test_prefers_local_name_over_wikidata_label():
    # the local name is the graph's own authoritative sdo:name -- prefer
    # it even when Wikidata also has a (same or different) label.
    text = format_entry(
        entry_id=1,
        fallback_name="International Institute of Social History",
        ror_id="05dq4pp56",
        wikidata_match={"wikidata": "https://www.wikidata.org/wiki/Q1667757", "_label": "IISH"},
    )
    assert 'name: "International Institute of Social History"' in text
    assert "_label" not in text  # metadata, not a real identifier field


def test_falls_back_to_wikidata_label_when_no_local_name():
    # fetch_known_rors returns the bare ror_id itself when nothing in the
    # graph asserts a name for it -- that's the signal "no local name".
    text = format_entry(
        entry_id=2,
        fallback_name="00000000x",
        ror_id="00000000x",
        wikidata_match={"wikidata": "https://www.wikidata.org/wiki/Q1", "_label": "Some University"},
    )
    assert 'name: "Some University"' in text
    assert "no sdo:name found" not in text  # Wikidata covered it, no warning needed


def test_warns_when_neither_local_name_nor_wikidata_label_exists():
    text = format_entry(entry_id=3, fallback_name="00000000x", ror_id="00000000x", wikidata_match=None)
    assert 'name: "00000000x"' in text
    assert "no sdo:name found" in text


def test_includes_identifier_fields_but_not_ror_twice():
    text = format_entry(
        entry_id=1,
        fallback_name="International Institute of Social History",
        ror_id="05dq4pp56",
        wikidata_match={"wikidata": "https://www.wikidata.org/wiki/Q1667757", "viaf": "https://viaf.org/viaf/138745303",
                         "_label": "IISH"},
    )
    assert text.count('ror: "https://ror.org/05dq4pp56"') == 1
    assert 'viaf: "https://viaf.org/viaf/138745303"' in text
    assert 'wikidata: "https://www.wikidata.org/wiki/Q1667757"' in text
