"""Builds RDF from a hand-curated crosswalk of per-entity identifiers
across the other IISG pipelines (and external registries like Wikidata) --
see README.md for the file format and why this exists.

Each entry mints one hub node, iisg.amsterdam/id/<id> -- a real, typed,
named record in its own right (not just plumbing), sdo:sameAs-linked to
every known external identifier (hub-and-spoke, not a full clique among
the externals: O(n) triples instead of O(n^2), and "give me everything in
one pass" only needs one hop from any external straight to the hub).

Deliberately dumb: no fetching, no validation beyond structural sanity,
no guessing. Every link here was asserted by a human who checked the
identifiers really do refer to the same entity.
"""
from __future__ import annotations

from pathlib import Path

from rdflib import RDF, Graph, Literal, URIRef

from .prefixes import DEFAULT_GRAPH, ID, NAMESPACE_BINDINGS, SDO

RESERVED_KEYS = {"id", "name", "type"}

TYPE_MAP = {
    "Person": SDO.Person,
    "Organization": SDO.Organization,
}


def identifiers(entry: dict) -> list[str]:
    """Every non-empty value in the entry except the reserved keys (id,
    name, type -- metadata about the hub itself, not external identifiers
    to link to it)."""
    return [v for k, v in entry.items() if k not in RESERVED_KEYS and v]


def validate_entry(entry: dict) -> None:
    missing = RESERVED_KEYS - entry.keys()
    if missing:
        raise ValueError(f"entry {entry.get('name', entry)!r} is missing required field(s): {sorted(missing)}")
    if entry["type"] not in TYPE_MAP:
        raise ValueError(
            f"entry {entry['name']!r} has type {entry['type']!r}, expected one of {sorted(TYPE_MAP)}"
        )


def validate_entries(entries: list[dict]) -> None:
    seen_ids: dict[int, str] = {}
    for entry in entries:
        validate_entry(entry)
        entry_id = entry["id"]
        if entry_id in seen_ids:
            raise ValueError(
                f"id {entry_id} is used by both {seen_ids[entry_id]!r} and {entry['name']!r} -- "
                f"ids must be unique and stable, never reassigned"
            )
        seen_ids[entry_id] = entry["name"]


def hub_uri(entry: dict) -> URIRef:
    return ID[str(entry["id"])]


def next_free_id(entries: list[dict]) -> int:
    """For whoever is hand-editing identities.yaml and adding a new entry:
    the next id that isn't already taken. ids are never reused even if an
    entry is later removed -- always one more than the current max, not
    "the first gap"."""
    existing = [entry["id"] for entry in entries if "id" in entry]
    return max(existing, default=0) + 1


def add_entry(g: Graph, entry: dict) -> URIRef:
    hub = hub_uri(entry)
    g.add((hub, RDF.type, TYPE_MAP[entry["type"]]))
    g.add((hub, SDO.name, Literal(entry["name"])))
    for value in identifiers(entry):
        external = URIRef(value)
        g.add((hub, SDO.sameAs, external))
        g.add((external, SDO.sameAs, hub))
    return hub


class IdentifierIndex:
    """Maps every identifier value already in use to the entry that owns
    it. This is what makes cross-pass co-occurrence detection possible: a
    discovery script seeded on one identifier type (say, ROR) often finds
    others for free (VIAF, ISNI, ...) via the same Wikidata item. If one
    of those already belongs to an entry some *other* pass created (say,
    a VIAF-seeded authority-matching pass), that's not a new entity --
    it's the same one reached a second way, and should be merged into the
    existing entry, not given a second hub.

    Built once from identities.yaml, then kept current as a run proceeds
    (merge/add update it immediately) so a later candidate in the same
    run can still find an entry that was only just enriched or created.
    """

    def __init__(self, entries: list[dict]):
        self._by_value: dict[str, dict] = {}
        for entry in entries:
            self.add(entry)

    def __contains__(self, value: str) -> bool:
        return value in self._by_value

    def find(self, candidate_identifiers: dict[str, str]) -> dict | None:
        """candidate_identifiers: field -> value, e.g. a Wikidata lookup's
        result dict (ror/viaf/isni/gnd/lcauth/orcid/wikidata, plus
        "_label") -- or any other dict shaped like a partial entry.
        Returns the existing entry that already owns any one of these
        values, or None if this looks like a genuinely new entity."""
        for key, value in candidate_identifiers.items():
            if key in RESERVED_KEYS or key == "_label" or not value:
                continue
            if value in self._by_value:
                return self._by_value[value]
        return None

    def merge(self, entry: dict, candidate_identifiers: dict[str, str]) -> dict[str, str]:
        """Adds whichever fields from candidate_identifiers aren't
        already present on entry (never overwrites an existing value --
        the first-written identifier for a field wins). Returns just the
        fields that were actually added (empty if nothing was new), so a
        caller can e.g. patch only those into an on-disk file rather than
        rewriting the whole entry.

        Also refuses to add a value that already belongs to a *different*
        entry -- without this check, two already-separately-minted
        entries that turn out to share one external identifier (e.g. two
        authority records both carrying the same VIAF cluster, each
        bare-minted by mint_all_entities.py before the overlap was known)
        could each independently be "found" via their own distinct field
        and have the shared value written onto both, corrupting the
        one-value-one-entry invariant this whole index exists to protect
        (hit live: 96 duplicate values from exactly this scenario, before
        this check existed). That situation means the two entries are
        probably the same real entity -- out of scope to actually merge
        here (see README's bare-name entity resolution gap) -- so the
        conflicting field is just skipped, not added to either further."""
        added = {}
        for key, value in candidate_identifiers.items():
            if key in RESERVED_KEYS or key == "_label" or not value:
                continue
            if key in entry:
                continue
            owner = self._by_value.get(value)
            if owner is not None and owner is not entry:
                continue
            entry[key] = value
            self._by_value[value] = entry
            added[key] = value
        return added

    def add(self, entry: dict) -> None:
        """Registers a (typically brand-new) entry's identifiers."""
        for value in identifiers(entry):
            self._by_value[value] = entry


def build_graph(entries: list[dict]) -> Graph:
    validate_entries(entries)
    g = Graph(identifier=DEFAULT_GRAPH)
    for prefix, ns in NAMESPACE_BINDINGS.items():
        g.bind(prefix, ns)
    for entry in entries:
        add_entry(g, entry)
    return g


# Field order used when writing identities.yaml by hand (not through
# yaml.dump -- see yaml_quote/append_entries below for why).
FIELD_ORDER = ("authority", "viaf", "wikidata", "isni", "gnd", "lcauth", "orcid", "ror")


def yaml_quote(value: str) -> str:
    """Minimal, correct escaping for a YAML double-quoted scalar.
    Real catalog data (hundreds of thousands of names, at the scale this
    is used for) will contain quotes, backslashes, and the occasional
    stray control character -- naive f'"{value}"' formatting breaks (or
    silently corrupts) on any of those. YAML double-quoted scalars use
    the same core escapes as JSON strings; these five cover what's
    actually been observed in this project's source data."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    return f'"{escaped}"'


def format_entry_yaml(entry: dict) -> str:
    """One entry, in identities.yaml's hand-written style: plain
    unquoted int id, double-quoted (properly escaped) strings, fields in
    FIELD_ORDER."""
    lines = [
        f"- id: {entry['id']}",
        f"  name: {yaml_quote(entry['name'])}",
        f"  type: {yaml_quote(entry['type'])}",
    ]
    for key in FIELD_ORDER:
        if key in entry:
            lines.append(f"  {key}: {yaml_quote(entry[key])}")
    return "\n".join(lines)


def append_entries(identities_file, new_entries: list[dict]) -> None:
    """Appends in identities.yaml's existing hand-written style (each
    entry's lines, then one blank line -- matching the blank line that
    already trails the file's last existing entry) rather than
    re-serializing the whole file through yaml.dump, which would
    reformat every existing entry too and bury a real change in an
    unreviewable diff."""
    if not new_entries:
        return
    text = "".join(format_entry_yaml(e) + "\n\n" for e in new_entries)
    with open(identities_file, "a") as f:
        f.write(text)


def merge_fields_in_file(identities_file, entry_id: int, added_fields: dict[str, str]) -> None:
    """Patches newly-merged fields into one *existing* entry's block
    in-place (located by its "- id: {entry_id}" line), rather than
    rewriting the whole file -- same reasoning as append_entries: keep
    the diff to exactly what changed, not a full reformat.

    O(file_size) per call (a linear scan to find the block) -- fine for
    a handful of merges, but calling this once per merge in a loop costs
    O(merges x file_size) overall. At thousands of merges against a
    multi-megabyte file that's the dominant cost by far (confirmed live:
    an attempted 7,184-merge run was still running after several minutes
    and was killed) -- use apply_merges for more than a few merges at
    once."""
    apply_merges(identities_file, {entry_id: added_fields})


def apply_merges(identities_file, merges: dict[int, dict[str, str]]) -> None:
    """Same effect as calling merge_fields_in_file once per (entry_id,
    added_fields) pair in merges, but a single read-scan-write pass
    (O(file_size), not O(merges x file_size)) -- the only way this stays
    practical once merges number in the thousands. Entries not mentioned
    in merges are passed through untouched."""
    merges = {entry_id: fields for entry_id, fields in merges.items() if fields}
    if not merges:
        return
    path = Path(identities_file)
    lines = path.read_text().split("\n")
    output = []
    pending: dict[str, str] | None = None  # fields queued for insertion at the end of the current block
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- id: "):
            pending = merges.get(int(stripped[len("- id: "):]))
        if pending is not None and stripped == "":
            output.extend(f"  {key}: {yaml_quote(value)}" for key, value in pending.items() if key in FIELD_ORDER)
            pending = None
        output.append(line)
    if pending is not None:  # file didn't end with a trailing blank line after the last entry
        output.extend(f"  {key}: {yaml_quote(value)}" for key, value in pending.items() if key in FIELD_ORDER)
    path.write_text("\n".join(output))
