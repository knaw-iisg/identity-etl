"""Looks up a Wikidata item from a known seed identifier (an ORCID or ROR,
or a name as a last resort for organizations), and reads back whichever
other identifiers Wikidata already knows for it -- a candidate source for
new identities.yaml entries/fields, never written automatically. See
README.md: "Growing the crosswalk".

Coverage is lopsided by design, not a bug here: Wikidata is strong for
institutions (confirmed live -- every one of the 50 distinct ROR-identified
organizations already in this project's own merged graph matched, a 100%
hit rate via bulk_lookup_by_ror) and much weaker for individual researchers
(confirmed live -- no item at all for this project's own primary
maintainer's ORCID, at least initially). Use it as one more source to
check, not a replacement for the authority/staff-page matching this
crosswalk otherwise relies on for people.
"""
from __future__ import annotations

import requests

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "identity-etl/0.1 (https://github.com/knaw-iisg/identity-etl)"

# Wikidata property -> (our field name, URI template). Verified against
# Wikidata's own property labels -- see the repo's commit history for the
# verification query, not just trusted from memory.
PROPERTY_MAP = {
    "P214": ("viaf", "https://viaf.org/viaf/{}"),
    "P213": ("isni", "https://isni.org/isni/{}"),
    "P244": ("lcauth", "https://id.loc.gov/authorities/names/{}"),
    "P227": ("gnd", "https://d-nb.info/gnd/{}"),
    "P6782": ("ror", "https://ror.org/{}"),
}


def _run(query: str) -> list[dict]:
    response = requests.get(
        SPARQL_ENDPOINT,
        params={"query": query},
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["results"]["bindings"]


def _item_identifiers(qid: str) -> dict[str, str]:
    """All known PROPERTY_MAP identifiers plus "wikidata" itself, for one
    already-found Wikidata item id (e.g. "Q1667757")."""
    props = ", ".join(f"wdt:{p}" for p in PROPERTY_MAP)
    query = f"""
    SELECT ?prop ?value WHERE {{
      wd:{qid} ?p ?value .
      ?propEntity wikibase:directClaim ?p .
      BIND(STRAFTER(STR(?propEntity), "http://www.wikidata.org/entity/") AS ?prop)
      FILTER(?p IN ({props}))
    }}
    """
    result = {"wikidata": f"https://www.wikidata.org/wiki/{qid}"}
    for row in _run(query):
        pid = row["prop"]["value"]
        field, template = PROPERTY_MAP[pid]
        result[field] = template.format(row["value"]["value"])
    return result


def lookup_by_orcid(orcid_id: str) -> dict[str, str] | None:
    """orcid_id: bare id, e.g. "0000-0003-3902-3720". None if no Wikidata
    item claims this ORCID."""
    query = f'SELECT ?item WHERE {{ ?item wdt:P496 "{orcid_id}" . }} LIMIT 1'
    rows = _run(query)
    if not rows:
        return None
    qid = rows[0]["item"]["value"].rsplit("/", 1)[-1]
    return _item_identifiers(qid)


def lookup_by_ror(ror_id: str) -> dict[str, str] | None:
    """ror_id: bare id, e.g. "05dq4pp56". None if no Wikidata item claims
    this ROR. Prefer this (or bulk_lookup_by_ror) over lookup_by_name for
    organizations whenever a ROR is already known -- it's an unambiguous
    reverse lookup, not fuzzy label matching, and measured 100% hit rate
    against every ROR-identified organization already in this project's
    own merged graph (see the repo's commit history for that check)."""
    query = f'SELECT ?item WHERE {{ ?item wdt:P6782 "{ror_id}" . }} LIMIT 1'
    rows = _run(query)
    if not rows:
        return None
    qid = rows[0]["item"]["value"].rsplit("/", 1)[-1]
    return _item_identifiers(qid)


def bulk_lookup_by_ror(ror_ids: list[str]) -> dict[str, dict[str, str]]:
    """ror_id -> identifiers dict, only for ids that matched -- plus the
    item's own English label under "_label" (underscore-prefixed: it's
    Wikidata's name for the entity, offered as a naming suggestion, not
    an identifier to write into identities.yaml verbatim). Fetched in the
    same batched query, not a separate per-item one: an organization
    found this way (via a bare ROR URI used as e.g. a dataset creator's
    sdo:affiliation, with no sdo:Organization node of its own anywhere in
    the graph) has no reliable local name to fall back on -- see
    discover_organizations.py.

    One batched query to find which ids match at all (measured: 50 ids in
    well under a second, vs. ~50 separate round trips), though each
    match's own full identifier set still costs one more query
    (_item_identifiers) -- not worth the extra complexity of a single
    mega-query for the scale this is actually used at (dozens of
    organizations, not thousands)."""
    if not ror_ids:
        return {}
    values = " ".join(f'"{r}"' for r in ror_ids)
    query = f"""
    SELECT ?ror ?item ?label WHERE {{
      VALUES ?ror {{ {values} }}
      ?item wdt:P6782 ?ror .
      OPTIONAL {{ ?item rdfs:label ?label . FILTER(LANG(?label) = "en") }}
    }}
    """
    matches = {}
    for row in _run(query):
        ror_id = row["ror"]["value"]
        qid = row["item"]["value"].rsplit("/", 1)[-1]
        identifiers = _item_identifiers(qid)
        if "label" in row:
            identifiers["_label"] = row["label"]["value"]
        matches[ror_id] = identifiers
    return matches


def lookup_by_name(name: str, instance_of_qid: str = "Q43229") -> list[dict[str, str]]:
    """name: exact label match (Wikidata labels are precise, not
    free-text search -- this is for organizations, where a human will
    still eyeball candidates before using one, same as everywhere else in
    this repo). instance_of_qid: restricts to this type and its
    subclasses via wdt:P31/wdt:P279* -- default Q43229 "organization".
    Returns every match verbatim; ambiguous names (there's often more than
    one) are the caller's problem to resolve by hand."""
    query = f"""
    SELECT DISTINCT ?item WHERE {{
      ?item rdfs:label "{name}"@en .
      ?item wdt:P31/wdt:P279* wd:{instance_of_qid} .
    }}
    """
    return [_item_identifiers(uri.rsplit("/", 1)[-1]) for uri in _run_and_dedupe(query)]


def _run_and_dedupe(query: str) -> list[str]:
    """Multiple wdt:P31/wdt:P279* paths to the same ancestor type (common
    -- e.g. IISG is both an "archive" and a "research institute", both
    under "organization") produce duplicate ?item rows even with SELECT
    DISTINCT, since Blazegraph's property-path evaluation isn't itself
    deduplicated before the projection. Dedupe explicitly."""
    seen = []
    for row in _run(query):
        uri = row["item"]["value"]
        if uri not in seen:
            seen.append(uri)
    return seen
