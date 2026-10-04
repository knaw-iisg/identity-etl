"""Exercises response-parsing/dedup logic against hand-built, synthetic
SPARQL JSON responses -- no network access. The real endpoint and property
IDs are verified manually (see the module docstring and commit history),
not re-verified here on every test run."""
from __future__ import annotations

from identity_etl import wikidata


def _row(value, var="item"):
    return {var: {"value": value}}


def test_item_identifiers_maps_known_properties(monkeypatch):
    monkeypatch.setattr(wikidata, "_run", lambda query: [
        {"prop": {"value": "P214"}, "value": {"value": "159839532"}},
        {"prop": {"value": "P213"}, "value": {"value": "000000010711579X"}},
    ])
    result = wikidata._item_identifiers("Q58282714")
    assert result == {
        "wikidata": "https://www.wikidata.org/wiki/Q58282714",
        "viaf": "https://viaf.org/viaf/159839532",
        "isni": "https://isni.org/isni/000000010711579X",
    }


def test_lookup_by_orcid_returns_none_when_no_item(monkeypatch):
    monkeypatch.setattr(wikidata, "_run", lambda query: [])
    assert wikidata.lookup_by_orcid("0000-0000-0000-0001") is None


def test_lookup_by_orcid_found(monkeypatch):
    calls = []

    def fake_run(query):
        calls.append(query)
        if "wdt:P496" in query:
            return [_row("http://www.wikidata.org/entity/Q58282714")]
        return [{"prop": {"value": "P227"}, "value": {"value": "142916110"}}]

    monkeypatch.setattr(wikidata, "_run", fake_run)
    result = wikidata.lookup_by_orcid("0000-0003-3902-3720")
    assert result["wikidata"] == "https://www.wikidata.org/wiki/Q58282714"
    assert result["gnd"] == "https://d-nb.info/gnd/142916110"
    assert len(calls) == 2


def test_lookup_by_ror_returns_none_when_no_item(monkeypatch):
    monkeypatch.setattr(wikidata, "_run", lambda query: [])
    assert wikidata.lookup_by_ror("00000000x") is None


def test_lookup_by_ror_found(monkeypatch):
    def fake_run(query):
        if "wikibase:directClaim" in query:  # the follow-up _item_identifiers query
            return [{"prop": {"value": "P213"}, "value": {"value": "0000000403695151"}}]
        return [_row("http://www.wikidata.org/entity/Q1667757")]  # the ROR lookup itself

    monkeypatch.setattr(wikidata, "_run", fake_run)
    result = wikidata.lookup_by_ror("05dq4pp56")
    assert result["wikidata"] == "https://www.wikidata.org/wiki/Q1667757"
    assert result["isni"] == "https://isni.org/isni/0000000403695151"


def test_bulk_lookup_by_ror_empty_input_makes_no_query(monkeypatch):
    monkeypatch.setattr(wikidata, "_run", lambda query: (_ for _ in ()).throw(AssertionError("should not query")))
    assert wikidata.bulk_lookup_by_ror([]) == {}


def test_bulk_lookup_by_ror_maps_each_match_including_label(monkeypatch):
    def fake_run(query):
        if "VALUES" in query:
            return [
                {"ror": {"value": "05dq4pp56"}, "item": {"value": "http://www.wikidata.org/entity/Q1667757"},
                 "label": {"value": "International Institute of Social History"}},
                {"ror": {"value": "0472cxd90"}, "item": {"value": "http://www.wikidata.org/entity/Q1377836"}},
                # no "label" key at all -- OPTIONAL with no match, same as a real unlabeled item
            ]
        # per-item identifier fetch, keyed by whichever qid is in the query
        if "Q1667757" in query:
            return [{"prop": {"value": "P6782"}, "value": {"value": "05dq4pp56"}}]
        return [{"prop": {"value": "P6782"}, "value": {"value": "0472cxd90"}}]

    monkeypatch.setattr(wikidata, "_run", fake_run)
    results = wikidata.bulk_lookup_by_ror(["05dq4pp56", "0472cxd90"])
    assert set(results) == {"05dq4pp56", "0472cxd90"}
    assert results["05dq4pp56"]["_label"] == "International Institute of Social History"
    assert "_label" not in results["0472cxd90"]


def test_lookup_by_name_dedupes_duplicate_rows(monkeypatch):
    def fake_run(query):
        if "rdfs:label" in query:
            # same item twice -- multiple wdt:P31/wdt:P279* paths, as seen
            # live for IISG (both "archive" and "research institute")
            return [_row("http://www.wikidata.org/entity/Q1667757"),
                    _row("http://www.wikidata.org/entity/Q1667757")]
        return [{"prop": {"value": "P6782"}, "value": {"value": "05dq4pp56"}}]

    monkeypatch.setattr(wikidata, "_run", fake_run)
    results = wikidata.lookup_by_name("International Institute of Social History")
    assert len(results) == 1
    assert results[0]["ror"] == "https://ror.org/05dq4pp56"
