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

import time

import requests

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "identity-etl/0.1 (https://github.com/knaw-iisg/identity-etl)"
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2

# Wikidata property -> (our field name, URI template). Verified against
# Wikidata's own property labels -- see the repo's commit history for the
# verification query, not just trusted from memory.
PROPERTY_MAP = {
    "P214": ("viaf", "https://viaf.org/viaf/{}"),
    "P213": ("isni", "https://isni.org/isni/{}"),
    "P244": ("lcauth", "https://id.loc.gov/authorities/names/{}"),
    "P227": ("gnd", "https://d-nb.info/gnd/{}"),
    "P6782": ("ror", "https://ror.org/{}"),
    "P496": ("orcid", "https://orcid.org/{}"),
}


def _run(query: str) -> list[dict]:
    """A single wedged request (timeout, connection reset, Wikidata
    momentarily 5xx-ing) shouldn't kill a run that's otherwise making many
    of these -- e.g. add_viaf_persons.py's ~91 sequential batches against
    a free public service. Retries with backoff; gives up and raises
    after MAX_ATTEMPTS."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                SPARQL_ENDPOINT,
                params={"query": query},
                headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()["results"]["bindings"]
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise last_error


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


def bulk_lookup_by_viaf(viaf_ids: list[str], batch_size: int = 200) -> dict[str, dict[str, str]]:
    """viaf_id (bare, e.g. "159839532") -> identifiers dict (plus
    "_label"), only for ids that matched.

    Unlike bulk_lookup_by_ror, this fetches each match's full identifier
    set in the *same* query as the matching itself, not a follow-up query
    per match -- necessary at this function's actual scale (thousands of
    authority records, not dozens of organizations): one-query-per-match
    would mean thousands of sequential round trips, tens of minutes to
    hours. Batched in groups of batch_size (default 200 -- the size
    measured live to resolve in well under a second per batch)."""
    results: dict[str, dict[str, str]] = {}
    props = ", ".join(f"wdt:{p}" for p in PROPERTY_MAP)
    for i in range(0, len(viaf_ids), batch_size):
        batch = viaf_ids[i:i + batch_size]
        values = " ".join(f'"{v}"' for v in batch)
        query = f"""
        SELECT ?viaf ?item ?label ?prop ?value WHERE {{
          VALUES ?viaf {{ {values} }}
          ?item wdt:P214 ?viaf .
          OPTIONAL {{ ?item rdfs:label ?label . FILTER(LANG(?label) = "en") }}
          OPTIONAL {{
            ?item ?p ?value .
            ?propEntity wikibase:directClaim ?p .
            BIND(STRAFTER(STR(?propEntity), "http://www.wikidata.org/entity/") AS ?prop)
            FILTER(?p IN ({props}))
          }}
        }}
        """
        for row in _run(query):
            viaf_id = row["viaf"]["value"]
            qid = row["item"]["value"].rsplit("/", 1)[-1]
            entry = results.setdefault(viaf_id, {"wikidata": f"https://www.wikidata.org/wiki/{qid}"})
            if "label" in row:
                entry["_label"] = row["label"]["value"]
            if "prop" in row:
                field, template = PROPERTY_MAP[row["prop"]["value"]]
                entry[field] = template.format(row["value"]["value"])
        if i + batch_size < len(viaf_ids):
            time.sleep(0.5)  # polite pacing over ~90 consecutive batches against a free public service
    return results


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
