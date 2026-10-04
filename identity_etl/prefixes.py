"""Namespace/prefix declarations used throughout the pipeline."""

from rdflib import Namespace

# schema.org: https://, as SCHEMA-AP-NDE requires ("publishers MUST use the
# https://schema.org/ namespace for newly published datasets" --
# https://docs.nde.nl/schema-profile/).
SDO = Namespace("https://schema.org/")

DEFAULT_GRAPH = "https://iisg.amsterdam/graph/identity"

NAMESPACE_BINDINGS = {
    "sdo": SDO,
}
