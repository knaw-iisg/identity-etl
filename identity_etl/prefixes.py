"""Namespace/prefix declarations used throughout the pipeline."""

from rdflib import Namespace

# schema.org: https://, as SCHEMA-AP-NDE requires ("publishers MUST use the
# https://schema.org/ namespace for newly published datasets" --
# https://docs.nde.nl/schema-profile/).
SDO = Namespace("https://schema.org/")

# The hub namespace this pipeline mints into: flat, cross-type (id/1, id/2,
# ... regardless of whether it's a person or organization), unlike
# authority/person/, authority/organization/, id/dataset/, id/collection/
# elsewhere in this graph -- those all reuse an *external* system's own
# existing number (a MARC control number, a DOI, an archive collection
# code). This is the first thing in the graph minting brand-new sequential
# IDs from scratch, so it follows Wikidata/VIAF's precedent (one flat space
# for every entity type) rather than those type-segmented ones. No letter
# prefix either (contrast Wikidata's Q/P/L/E) -- those separate different
# *kinds* of record (entities vs. property definitions vs. lexemes); this
# namespace only ever mints one kind, so there's nothing to disambiguate.
ID = Namespace("https://iisg.amsterdam/id/")

DEFAULT_GRAPH = "https://iisg.amsterdam/graph/identity"

NAMESPACE_BINDINGS = {
    "sdo": SDO,
    "id": ID,
}
