"""Exercises classify_uri against hand-built data -- no real entity data,
no network access."""
from __future__ import annotations

from identity_etl.mint_all_entities import classify_uri


def test_classify_known_schemes():
    assert classify_uri("https://iisg.amsterdam/authority/person/123") == "authority"
    assert classify_uri("https://iisg.amsterdam/authority/organization/456") == "authority"
    assert classify_uri("https://orcid.org/0000-0003-3902-3720") == "orcid"
    assert classify_uri("https://ror.org/05dq4pp56") == "ror"
    assert classify_uri("https://viaf.org/viaf/159839532") == "viaf"
    assert classify_uri("https://isni.org/isni/0000000403695151") == "isni"
    assert classify_uri("https://d-nb.info/gnd/1004926-5") == "gnd"
    assert classify_uri("https://id.loc.gov/authorities/names/no88006177") == "lcauth"


def test_classify_unrecognized_scheme_is_none():
    # dataverse-etl's own locally-minted fragment/fallback URIs, and
    # orcid-etl's urn: fallback for organizations with no ROR -- neither
    # means anything to an external system.
    assert classify_uri("https://iisg.amsterdam/id/dataset/10.34894/X#creator-abc123") is None
    assert classify_uri("urn:orcidgraph:org:some-institute") is None
    assert classify_uri("https://iisg.amsterdam/dataverse/knaw#org-abc123") is None
