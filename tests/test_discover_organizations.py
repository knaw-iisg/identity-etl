"""Exercises format_entry's name-preference logic against hand-built data
-- no network access."""
from __future__ import annotations

from identity_etl.discover_organizations import format_entry


def test_prefers_wikidata_label_over_local_fallback():
    text = format_entry(
        entry_id=4,
        fallback_name="Baten, Joerg",  # the wrong, locally-sourced name
        ror_id="03a1kwz48",
        wikidata_match={"wikidata": "https://www.wikidata.org/wiki/Q153978", "_label": "University of Tübingen"},
    )
    assert 'name: "University of Tübingen"' in text
    assert "Baten, Joerg" not in text
    assert "_label" not in text  # metadata, not a real identifier field


def test_falls_back_to_local_name_and_flags_it_when_no_wikidata_match():
    text = format_entry(entry_id=5, fallback_name="Some Local Name", ror_id="00000000x", wikidata_match=None)
    assert 'name: "Some Local Name"' in text
    assert "no Wikidata match found" in text
    assert "may be" in text and "WRONG" in text


def test_flags_fallback_name_even_when_wikidata_matched_but_has_no_label():
    # real case hit live: Q2242095 matches via ROR but has zero labels in
    # any language -- still a match, still needs the warning.
    text = format_entry(
        entry_id=8,
        fallback_name="Depuydt, Katrien",
        ror_id="04m5bjk54",
        wikidata_match={"wikidata": "https://www.wikidata.org/wiki/Q2242095", "viaf": "https://viaf.org/viaf/126828545"},
    )
    assert 'name: "Depuydt, Katrien"' in text
    assert "no label in any language" in text
    assert "may be WRONG" in text


def test_includes_identifier_fields_but_not_ror_twice():
    text = format_entry(
        entry_id=1,
        fallback_name="IISG",
        ror_id="05dq4pp56",
        wikidata_match={"wikidata": "https://www.wikidata.org/wiki/Q1667757", "viaf": "https://viaf.org/viaf/138745303",
                         "_label": "International Institute of Social History"},
    )
    assert text.count('ror: "https://ror.org/05dq4pp56"') == 1
    assert 'viaf: "https://viaf.org/viaf/138745303"' in text
    assert 'wikidata: "https://www.wikidata.org/wiki/Q1667757"' in text
