# identity-etl

A hand-curated crosswalk of per-person identifiers across the other IISG
pipelines, mapped to `sdo:sameAs` RDF -- alongside
[biblio-etl](https://github.com/knaw-iisg/biblio-etl),
[archive-etl](https://github.com/knaw-iisg/archive-etl),
[findingaid-etl](https://github.com/knaw-iisg/findingaid-etl),
[authorities-etl](https://github.com/knaw-iisg/authorities-etl),
[dataverse-etl](https://github.com/knaw-iisg/dataverse-etl),
[orcid-etl](https://github.com/knaw-iisg/orcid-etl) and
[events-etl](https://github.com/knaw-iisg/events-etl).

## Why this exists

Each pipeline mints its own identifier for the same real person, and
nothing links them. Concretely: `authorities-etl` mints
`iisg.amsterdam/authority/person/<n>` from the library catalogue's own
authority file; `orcid-etl` mints `orcid.org/<orcid-id>` from a person's
public ORCID record; `dataverse-etl` sometimes reuses a real ORCID URI and
sometimes mints its own. These are genuinely different identifier spaces
with no shared key -- IISG's authority file predates ORCID adoption and
was never built to carry it, so there's no reliable automatic join.

The practical effect: in the merged knowledge graph
([iisg-kb-viewer](https://github.com/knaw-iisg/iisg-kb-viewer)), a
person's library-catalogued works and their ORCID-sourced works
(papers, presentations, employment, funding) sit on two disconnected
nodes. Landing on either one only shows that one's own data.

This repo doesn't try to resolve that automatically. It's a small,
explicit, human-verified list: a person's name, and whichever of their
identifiers a human has actually checked and confirmed refer to the same
individual. **It is deliberately never complete** -- the same honest
caveat [orcid-etl's colleagues.yaml](https://github.com/knaw-iisg/orcid-etl)
carries. Growing it is a manual curation task, not something this
pipeline automates.

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## The identities.yaml format

Personally-identifying curation data, not code -- same boundary as
orcid-etl's `colleagues.yaml`, so it lives outside this repo entirely, in
a data directory (default `~/identity-etl-data`; override with
`--data-dir` or `$IDENTITY_ETL_DATA_DIR`), not merely gitignored inside
it.

One entry per person, `name` for maintainers' own legibility only (never
written to the output RDF -- every identifier below already resolves to a
node that asserts its own `sdo:name` elsewhere in the graph), then any
number of identifier fields. There's no fixed set of identifier-system
keys -- anything other than `name` is treated as one:

```yaml
- name: "Richard Zijdeman"
  authority: "https://iisg.amsterdam/authority/person/2011604"
  orcid: "https://orcid.org/0000-0003-3902-3720"
  # wikidata: "https://www.wikidata.org/wiki/Q..."   # add as discovered
  # dataverse: "..."                                  # only if dataverse-etl
  #   ever mints its own URI for this person rather than reusing their ORCID
```

An entry with only one identifier is harmless (produces no triples) --
useful as a placeholder while you track down a second one.

## Usage

```
python3 -m identity_etl.cli
```

Reads `<data-dir>/identities.yaml`, writes `<data-dir>/identity-etl.ttl`.
Pass `--out PATH` to write elsewhere instead -- e.g. straight into a local
triplestore's `sources/` directory, without moving `identities.yaml` out
of `--data-dir`.

## What it emits

For each entry, a full clique of `sdo:sameAs` over its identifiers: every
pair, both directions. For `n` identifiers that's `n * (n-1)` triples --
quadratic, but `n` is a handful of systems per person at most, so this
is a non-issue in practice. The payoff: from *any* one of a person's
identifiers, every other one is one `sdo:sameAs` hop away -- no
transitive-closure query needed downstream. `sdo:sameAs` is schema.org's
own term for exactly this ("URL of a reference Web page that
unambiguously indicates the item's identity"); no need for `owl:sameAs`.

## What still needs to change for this to actually fix the viewer

This repo only produces the links. Two more pieces, not yet done:

1. **Wire it into `triplestore`**: add `sources/identity.ttl` as another
   `MULTI_INPUT_JSON` entry in `triplestore`'s `Qleverfile`, in its own
   named graph (`https://iisg.amsterdam/graph/identity`).
2. **Teach `iisg-kb-viewer` to follow `sdo:sameAs`**: right now, e.g.
   `fetchMoreByCreator` queries works pointing at exactly one URI. It
   would need to also expand to any `sdo:sameAs`-linked URIs first (one
   hop, per the full-clique shape above) so a person's "Creations" list
   -- and incoming-statement counts generally -- merge across all their
   known identities, not just whichever one the viewer currently has
   dereferenced.

## Tests

```
pip install -e ".[test]"
pytest
```

Runs against hand-built, entirely synthetic entries -- no real person
data, no network access.
