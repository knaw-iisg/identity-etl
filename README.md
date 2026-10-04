# identity-etl

A hand-curated crosswalk of per-entity identifiers (people and
organizations) across the other IISG pipelines and external registries
(Wikidata, VIAF, ISNI, GND, ROR, ...), mapped to `sdo:sameAs` RDF --
alongside
[biblio-etl](https://github.com/knaw-iisg/biblio-etl),
[archive-etl](https://github.com/knaw-iisg/archive-etl),
[findingaid-etl](https://github.com/knaw-iisg/findingaid-etl),
[authorities-etl](https://github.com/knaw-iisg/authorities-etl),
[dataverse-etl](https://github.com/knaw-iisg/dataverse-etl),
[orcid-etl](https://github.com/knaw-iisg/orcid-etl) and
[events-etl](https://github.com/knaw-iisg/events-etl).

## Why this exists

Each pipeline mints its own identifier for the same real entity, and
nothing links them. Concretely: `authorities-etl` mints
`iisg.amsterdam/authority/person/<n>` (and `.../organization/<n>`) from
the library catalogue's own authority file; `orcid-etl` mints
`orcid.org/<orcid-id>` from a person's public ORCID record; `dataverse-etl`
sometimes reuses a real ORCID URI and sometimes mints its own. These are
genuinely different identifier spaces with no shared key -- IISG's
authority file predates ORCID adoption and was never built to carry it,
so there's no reliable automatic join.

The practical effect: in the merged knowledge graph
([iisg-kb-viewer](https://github.com/knaw-iisg/iisg-kb-viewer)), a
person's library-catalogued works and their ORCID-sourced works
(papers, presentations, employment, funding) sit on two disconnected
nodes. Landing on either one only shows that one's own data.

This repo doesn't try to resolve that automatically. It's a small,
explicit, human-verified list: an entity's name, and whichever of its
identifiers a human has actually checked and confirmed refer to the same
real person or organization. **It is deliberately never complete** -- the
same honest caveat
[orcid-etl's colleagues.yaml](https://github.com/knaw-iisg/orcid-etl)
carries. Growing it is a manual curation task; `identity_etl.wikidata`
(below) helps find candidates, but nothing writes to `identities.yaml`
on its own.

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## The hub design

Each entry mints one new, IISG-owned identifier --
`https://iisg.amsterdam/id/<n>` -- and every known external identifier
(authority record, ORCID, Wikidata, VIAF, ...) gets an `sdo:sameAs` link
to *that*, not to each other directly. This is a hub, not a clique: `n`
identifiers cost `2n` triples (each external <-> hub, both directions),
not `n * (n-1)`. The hub itself is a real record, not just plumbing --
it carries its own `rdf:type` (`sdo:Person`/`sdo:Organization`) and
`sdo:name`, so it's independently meaningful if someone lands on it
directly, e.g. via search.

**Why `id/<n>`, flat, no type segment and no letter prefix** (unlike
`authority/person/`, `authority/organization/`, `id/dataset/`,
`id/collection/` elsewhere in this graph, and unlike Wikidata's
`Q`/`P`/`L`/`E`):
- Every one of those other namespaces reuses an *external* system's own
  existing number (a MARC control number, a DOI, an archive collection
  code). This is the first thing in the graph minting brand-new
  sequential IDs from scratch, with nothing to inherit -- so it follows
  Wikidata/VIAF's precedent instead (one flat space across every entity
  type), not theirs.
- `rdf:type` already carries the type, asserted on every hub. Repeating
  it in the URI is pure duplication of something SPARQL can always ask
  anyway -- and it sidesteps classification-boundary arguments (is this
  a "collection" or a "dataset"? a "book" or a "poster"?) entirely, since
  the counter doesn't care what's being minted.
- Wikidata's letters don't subtype entities either -- `Q` already covers
  people, organizations, and works uniformly. They separate categorically
  *different kinds of record* (entities vs. property definitions vs.
  lexemes vs. schema constraints) that this namespace has no equivalent
  of: it only ever mints one kind of thing.

## Cross-pass deduplication: `IdentifierIndex`

Different discovery scripts seed from different identifier types (ROR,
VIAF, ORCID, ...), but often pull back *other* identifiers for free --
e.g. a ROR lookup via Wikidata routinely also returns that organization's
VIAF id. If that VIAF id already belongs to an entry some *other* pass
created, that's not a new entity -- it's the same one, reached a second
way, and must be merged into the existing entry rather than given a
second hub.

`pipeline.IdentifierIndex` is what makes this possible: a value -> entry
map built from every identifier already in `identities.yaml`, kept
current as a run proceeds. Before creating a new entry, a script should
call `index.find(candidate_identifiers)` -- if it returns an existing
entry, `index.merge(existing, candidate_identifiers)` adds only the
genuinely new fields (never overwrites) and returns what was added; only
when `find` returns `None` should a brand-new entry be created (then
registered with `index.add(entry)` so later candidates in the same run
can find it too). `add_viaf_persons.py` is the reference implementation;
any future discovery script that writes directly to `identities.yaml`
should use the same pattern.

## Growing the crosswalk: VIAF-linked authority persons

```
python3 -m identity_etl.add_viaf_persons
```

Unlike `discover_organizations.py`, **this one writes directly** --
finds every authority Person record that already carries a VIAF
`sdo:sameAs` (`authorities-etl`'s own MARC-035-derived link) and isn't
yet known, looks each VIAF id up on Wikidata in batches (properly
batched: each request resolves *and* fetches full identifiers for up to
200 ids at once, not one follow-up query per match -- necessary at this
scale, see below), and for each match either appends a new entry or
merges into an existing one via `IdentifierIndex`. The name used is
always the authority record's own `sdo:name`, never Wikidata's label --
unlike ROR-identified organizations, authority Person records reliably
have one, so there's nothing to fall back on.

Measured live on this project's own graph: **18,172** VIAF-linked
authority Person records, **11,116** matched on Wikidata (a lower hit
rate than ROR's 100% -- expected, Wikidata's institutional coverage is
far more complete than its coverage of individual researchers), yielding
**11,113** new entries (a handful of authority records turned out to be
catalogue duplicates of each other -- same VIAF cluster, correctly
collapsed onto one hub instead of two). The whole run: ~8 minutes
(batched Wikidata queries, politely paced), one HTTP request per ~200
ids rather than per match -- a naive per-match approach would have meant
over 11,000 sequential round trips, tens of minutes to hours instead.

Safe to re-run: records already known (by `authority:` URI, or by any
identifier already attached via a merge) are skipped.

## The identities.yaml format

Personally-identifying curation data, not code -- same boundary as
orcid-etl's `colleagues.yaml`, so it lives outside this repo entirely, in
a data directory (default `~/identity-etl-data`; override with
`--data-dir` or `$IDENTITY_ETL_DATA_DIR`), not merely gitignored inside
it.

One entry per entity. Three required fields -- `id` (int, permanent once
assigned: see "Assigning ids" below), `name` (for maintainers' own
legibility only -- never written to the output RDF beyond the hub's own
`sdo:name`), `type` (`Person` or `Organization`) -- then any number of
identifier fields. There's no fixed set of identifier-system keys;
anything other than the three reserved ones is treated as one:

```yaml
- id: 1
  name: "Richard Zijdeman"
  type: "Person"
  authority: "https://iisg.amsterdam/authority/person/2011604"
  orcid: "https://orcid.org/0000-0003-3902-3720"
  wikidata: "https://www.wikidata.org/wiki/Q58282714"
  viaf: "https://viaf.org/viaf/159839532"
  isni: "https://isni.org/isni/000000010711579X"
  gnd: "https://d-nb.info/gnd/142916110"

- id: 2
  name: "International Institute of Social History"
  type: "Organization"
  ror: "https://ror.org/05dq4pp56"
  wikidata: "https://www.wikidata.org/wiki/Q1667757"
```

An entry with zero or one external identifier is harmless -- still gets
a valid hub (useful as a placeholder while you track down the rest).

### Assigning ids

```
python3 -m identity_etl.cli --next-id
```

Prints the next free id (current max + 1) and exits -- never "the first
gap," since a removed entry's id should never be handed to someone else
later. Building that list is always a `max()` over the current file, so
there's deliberately no separate registry/counter file to keep in sync.

## Usage

```
python3 -m identity_etl.cli
```

Reads `<data-dir>/identities.yaml`, writes `<data-dir>/identity-etl.ttl`.
Pass `--out PATH` to write elsewhere instead -- e.g. straight into a local
triplestore's `sources/` directory, without moving `identities.yaml` out
of `--data-dir`. Validates before writing anything: every entry needs
`id`/`name`/`type`, every `id` must be unique, `type` must be `Person` or
`Organization`.

## Growing the crosswalk: Wikidata lookups

```python
from identity_etl import wikidata

wikidata.lookup_by_orcid("0000-0003-3902-3720")
# -> {"wikidata": "...", "viaf": "...", "isni": "...", "gnd": "..."}  (or None)

wikidata.lookup_by_ror("05dq4pp56")
# -> {"wikidata": "...", "viaf": "...", "isni": "...", "gnd": "..."}  (or None)
# prefer this (or bulk_lookup_by_ror) over lookup_by_name whenever a ROR
# is already known: unambiguous reverse lookup, not fuzzy label matching

wikidata.lookup_by_name("International Institute of Social History")
# -> list of candidate identifier dicts (there can be more than one
#    same-named item; eyeball before using)
```

Looks up a Wikidata item from a known seed (an ORCID, or an exact name
for organizations) and reads back whichever `PROPERTY_MAP` identifiers
(currently VIAF, ISNI, Library of Congress, GND, ROR) Wikidata already
has for it. **Coverage is lopsided by design, not a bug**: confirmed live
-- Wikidata is strong for institutions (IISG's own item already had a ROR
ID before this repo existed) and much weaker for individual researchers
(no item at all for this project's primary maintainer, until one was
apparently added to Wikidata independently partway through this repo's
own development -- Wikidata is a live, constantly-edited wiki, not a
static dataset). Use it as one more source to check per `identities.yaml`
entry, not an automatic resolver -- it only ever returns candidates; nothing
here writes to `identities.yaml`.

## Growing the crosswalk: organizations already in the graph

```
python3 -m identity_etl.discover_organizations
```

Finds every ROR-identified organization already asserted somewhere in the
merged knowledge graph (default endpoint: `http://localhost:7878`;
override with `--endpoint`) that isn't yet in `identities.yaml`, looks
each up via `bulk_lookup_by_ror` (one batched query, not one per
organization -- measured live: **50 ROR ids resolved in well under a
second**, 100% hit rate against every ROR-identified organization this
project's own graphs currently assert), and prints ready-to-paste YAML
entries. Never writes to `identities.yaml` itself.

**The suggested name is the ROR URI's own `sdo:name`** -- both
`orcid-etl` and `dataverse-etl` correctly mint a proper
`sdo:Organization` node (name, address, everything) for every ROR they
use, confirmed live across all 50 ROR-identified organizations this
project's own graphs currently assert. Wikidata's label is only used as
a fallback on the rare organization with no local name at all (not
observed yet in this project's own data, but handled). Entries with
neither a local name nor a usable Wikidata label are explicitly flagged
in the output rather than silently guessing.

(An earlier version of this tool got the name query wrong -- it grabbed
`sdo:name` from whatever subject merely *pointed at* a ROR, e.g. a
dataset's creator node, rather than the ROR URI's own name. That
produced believable-looking but wrong names like "Baten, Joerg" for what
was actually a university, and was briefly mistaken for a data error in
`dataverse-etl` before the real cause -- a bug in this query -- was
found.)

## What still needs to change for this to actually fix the viewer

This repo only produces the links. Two more pieces, not yet done:

1. **Wire it into `triplestore`**: add `sources/identity.ttl` as another
   `MULTI_INPUT_JSON` entry in `triplestore`'s `Qleverfile`, in its own
   named graph (`https://iisg.amsterdam/graph/identity`).
2. **Teach `iisg-kb-viewer` to follow `sdo:sameAs`**: right now, e.g.
   `fetchMoreByCreator` queries works pointing at exactly one URI. It
   would need to also expand to the hub (one `sdo:sameAs` hop) and then
   to every other identifier sharing that hub (one more hop) so a
   person's "Creations" list -- and incoming-statement counts generally
   -- merge across all their known identities, not just whichever one
   the viewer currently has dereferenced.

## Tests

```
pip install -e ".[test]"
pytest
```

Runs against hand-built, entirely synthetic entries -- no real
person/organization data. `test_wikidata.py` mocks the network layer
(canned SPARQL-JSON responses); the real endpoint and property IDs were
verified manually against Wikidata (see `wikidata.py`'s docstring), not
re-verified on every test run.
