"""Command-line entry point for axial."""

import argparse
import sys

import axial
from axial.schema import SchemaError, load_schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axial")
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the axial version and exit",
    )

    subparsers = parser.add_subparsers(dest="command")

    schema_parser = subparsers.add_parser("schema", help="domain schema operations")
    schema_subparsers = schema_parser.add_subparsers(dest="schema_command")

    show_parser = schema_subparsers.add_parser(
        "show", help="show a domain schema's axes, cardinality, counts, and version"
    )
    show_parser.add_argument("domain_dir", help="path to a domain directory containing schema.yaml")

    return parser


def _schema_show(domain_dir: str) -> int:
    try:
        schema = load_schema(domain_dir)
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"schema version: {schema.version}")
    for axis_name, axis in schema.axes.items():
        print(f"{axis_name}: cardinality={axis.cardinality} count={axis.value_count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"axial {axial.__version__}")
        return 0

    if args.command == "schema" and args.schema_command == "show":
        return _schema_show(args.domain_dir)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
