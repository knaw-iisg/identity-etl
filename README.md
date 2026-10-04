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

## The two-phase model: mint, then enrich

Every entity across *every* IISG resource -- archive, biblio, dataverse,
findingaid, authorities, orcid, events -- gets an IISG id, unconditionally,
whether or not it already has an external identifier or is just a bare
name with a locally-minted, pipeline-internal URI. That's phase one:
`mint_all_entities.py`, no network calls, no matching, just "does this
entity have a hub yet? If not, give it one." **Most entities end up with
only their IISG id and nothing else -- that's the normal, expected
outcome, not a gap to fill.** Measured live: 555,609 distinct entities
across the whole merged graph; 16,283 of them have no recognized external
identifier scheme at all.

Phase two is external-identifier *enrichment*, run separately, per
identifier system: `discover_organizations.py` (ROR, via Wikidata),
`add_viaf_persons.py` (authority-linked VIAF, via Wikidata), and whatever
comes after (ORCID, direct Wikidata matching, ...). Each one takes
entities that *already* have an id and checks whether they also match
something external -- this is strictly additive to phase one, never a
replacement for it.

**What phase one deliberately does not do**: resolve the same real entity
appearing as *different bare-name nodes* across pipelines with no shared
identifier at all -- e.g. the library authority's "Zijdeman, Richard" and
a Dataverse dataset's "Richard Zijdeman" currently get two separate IISG
ids, not one. That's a real, open problem (name-variant entity
resolution, not identifier-crosswalk matching), deliberately deferred
rather than solved badly -- see "What's still unsolved" near the bottom.

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

## Minting: every entity, identified or not

```
python3 -m identity_etl.mint_all_entities
```

Phase one (see "The two-phase model" above). Finds every distinct
`sdo:Person`/`sdo:Organization` node across *every* named graph (one
query, selective by construction -- `?s a ?type` with `?type` restricted
to exactly those two values, not an unbound scan; measured live: 555,609
rows in ~2.6s) and, for every one not already covered by an existing
entry (via `IdentifierIndex`, so a ROR- or VIAF-matched entity from an
earlier enrichment pass gets no redundant second hub), mints a new one.

The entity's own URI is classified by scheme (`URI_SCHEME_FIELDS`):
`authority/person/`+`authority/organization/` -> `authority:`,
`orcid.org/` -> `orcid:`, `ror.org/` -> `ror:`, `viaf.org/` -> `viaf:`,
`isni.org/` -> `isni:`, `d-nb.info/gnd/` -> `gnd:`, `id.loc.gov/` ->
`lcauth:`. Anything else -- a `dataverse-etl` `#creator-<hash>`/
`#org-<hash>` fragment, an `orcid-etl` `urn:orcidgraph:org:` fallback for
an organization with no ROR -- gets an id and a name, nothing else; that
URI isn't a real external identifier, just the pipeline's own internal
plumbing for an entity it couldn't otherwise identify.

No network calls (pure local SPARQL + file write), so safe to re-run
often as upstream pipelines add new entities -- already-known ones are
skipped, matching this repo's usual idempotency.

Measured live (one run, on top of the 11,165 entries phase-two tools had
already created): 555,609 distinct entities total, 544,433 newly minted
-- 528,150 with a recognized scheme, 16,283 with only their IISG id.
`identities.yaml` grew from ~500KB to ~71MB; the full RDF build
(`identity_etl.cli`) takes ~3.5 minutes at this scale (2,293,870 triples)
and `yaml.safe_load`-ing the whole file takes ~100s -- both fine for an
occasional batch job, but worth knowing before reaching for this inside
something latency-sensitive.

## Growing the crosswalk: VIAF-linked authority records

```
python3 -m identity_etl.add_viaf_persons              # Person (default)
python3 -m identity_etl.add_viaf_persons --type Organization
```

Unlike `discover_organizations.py`, **this one writes directly** --
finds every authority record of `--type` that already carries a VIAF
`sdo:sameAs` (`authorities-etl`'s own MARC-035-derived link) and hasn't
already been looked up, looks each VIAF id up on Wikidata in batches
(properly batched: each request resolves *and* fetches full identifiers
for up to 200 ids at once, not one follow-up query per match -- necessary
at this scale, see below), and for each match either appends a new entry
or merges into an existing one via `IdentifierIndex`. The name used is
always the authority record's own `sdo:name`, never Wikidata's label --
unlike ROR-identified organizations that sometimes have no local
`sdo:Organization` node at all, authority records reliably have one, so
there's nothing to fall back on.

**Filters on the VIAF value, not the authority URI** -- a consequence of
`mint_all_entities.py` existing: since every authority record already
gets bare-minted (id + name + `authority:`, nothing else) in phase one,
checking "is this authority URI already known" would be true for nearly
everything and skip it before ever attempting the enrichment merge. The
filter instead skips only VIAF ids this script has already resolved in a
previous run.

Measured live, Person (before `mint_all_entities.py` existed, so this run
created new entries rather than merging): **18,172** VIAF-linked
authority Person records, **11,116** matched on Wikidata, **11,113** new
entries (a handful of authority records turned out to be catalogue
duplicates of each other -- same VIAF cluster, correctly collapsed onto
one hub instead of two). ~8 minutes, one HTTP request per ~200 ids rather
than per match -- a naive per-match approach would have meant over 11,000
sequential round trips, tens of minutes to hours instead.

Measured live, Organization (**after** `mint_all_entities.py`, so every
match merged into an already-bare-minted entry instead of creating a new
one -- confirming the VIAF-value filter fix above): **175** VIAF-linked
authority Organization records, **97** matched on Wikidata, **0** new
entries / **97** merges. Also surfaced **22** ROR ids for organizations
that had none before, arriving as a Wikidata bonus field alongside VIAF
-- `discover_organizations.py`'s earlier ROR pass only ever saw ROR ids
*already asserted in the merged graph*, which these weren't.

**Known performance limit, not yet fixed**: `merge_fields_in_file`
re-reads and rewrites the *entire* `identities.yaml` once per merge. Fine
at hundreds of merges against a multi-megabyte file (the 97 Organization
merges above took a few minutes); would be a real bottleneck at tens of
thousands of merges against a much larger file. Worth batching into a
single rewrite pass before running any VIAF/ORCID-type pass again after
`identities.yaml` has grown substantially.

Safe to re-run either `--type`: already-resolved VIAF ids are skipped.

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

## What's still unsolved: bare-name entity resolution

`mint_all_entities.py` gives every entity an id, but deliberately does
**not** try to figure out that two *differently-spelled, identifier-less*
mentions are the same real person or organization -- e.g. the library
authority's "Zijdeman, Richard" and a Dataverse dataset's "Richard
Zijdeman" currently mint two separate IISG ids, with nothing connecting
them. `IdentifierIndex` only catches overlap when two entities share an
*actual identifier value* (a ROR, a VIAF, ...); two bare names, however
obviously the same person to a human, share nothing it can compare.

Closing that gap needs genuine name-variant matching (title-case vs.
"Last, First" ordering, middle names, transliteration, ...) with a real
risk of false positives at this entity count -- explicitly out of scope
for now, deferred rather than solved badly. Worth knowing before relying
on `identities.yaml` to mean "one entry per real entity" -- today it
means "one entry per *distinct identified node*," which for bare-name
entities can still be more than one per real entity.

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
