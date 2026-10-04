"""Command-line entry point: ``python -m identity_etl.cli``.

identities.yaml names real people and lists their identifiers across
systems -- personally-identifying curation data, not code, so (same
boundary as orcid-etl's colleagues.yaml) it lives outside this repo
entirely, in --data-dir (default: $IDENTITY_ETL_DATA_DIR or
~/identity-etl-data), not merely gitignored inside it.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

from .pipeline import build_graph, next_free_id

DEFAULT_DATA_DIR = Path.home() / "identity-etl-data"


def resolve_data_dir(cli_value: str | None) -> Path:
    if cli_value:
        return Path(cli_value).expanduser()
    if os.environ.get("IDENTITY_ETL_DATA_DIR"):
        return Path(os.environ["IDENTITY_ETL_DATA_DIR"]).expanduser()
    return DEFAULT_DATA_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cross-pipeline per-person identifier crosswalk -> sdo:sameAs RDF"
    )
    parser.add_argument(
        "--data-dir",
        help="where identities.yaml lives (default: $IDENTITY_ETL_DATA_DIR or ~/identity-etl-data)",
    )
    parser.add_argument(
        "--out", type=Path,
        help="output Turtle path (default: <data-dir>/identity-etl.ttl). Point this at, "
             "e.g., a local triplestore's sources/ directory to load this pipeline's "
             "output alongside the others, without moving identities.yaml out of --data-dir.",
    )
    parser.add_argument(
        "--next-id", action="store_true",
        help="print the next free id for a new identities.yaml entry, and exit "
             "(doesn't write anything)",
    )
    args = parser.parse_args(argv)

    data_dir = resolve_data_dir(args.data_dir)
    identities_file = data_dir / "identities.yaml"
    output_path = args.out or (data_dir / "identity-etl.ttl")

    if not identities_file.exists():
        sys.exit(
            f"No identities.yaml found at {identities_file}\n"
            f"Create it there (see README.md for the format), or pass --data-dir / "
            f"set $IDENTITY_ETL_DATA_DIR to point elsewhere."
        )

    entries = yaml.safe_load(identities_file.read_text()) or []

    if args.next_id:
        print(next_free_id(entries))
        return 0

    g = build_graph(entries)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(output_path), format="turtle")
    print(f"Wrote {len(g)} triples ({len(entries)} entities) to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
