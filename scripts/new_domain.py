"""Create a new domain plugin skeleton.

Usage (from the repository root):

    python -m scripts.new_domain <name> --display-name "Nome Exibido" --owner "Time"
    python -m scripts.new_domain <name> --display-name "..." --owner "..." --dry-run

The generated domain starts with ``provider: mock``, empty knowledge folders and
the confinement eval suites. Next steps are in
``docs/runbooks/fde-engagement-playbook.md``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.domain_engine.scaffold import (
    EVAL_FILES,
    DomainScaffoldSpec,
    ScaffoldError,
    create_domain,
    render_domain_files,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a new domain skeleton.")
    parser.add_argument("name", help="Domain folder/name in kebab-case, e.g. acme-suporte")
    parser.add_argument("--display-name", required=True, help="Human-readable name")
    parser.add_argument("--owner", required=True, help="Team or person that owns the domain")
    parser.add_argument("--description", default="", help="One-line description")
    parser.add_argument(
        "--domains-path",
        default="domains",
        help="Folder that holds the domains (default: domains)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the files that would be created without writing anything",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec = DomainScaffoldSpec(
        name=args.name,
        display_name=args.display_name,
        owner=args.owner,
        description=args.description,
    )
    domains_path = Path(args.domains_path)

    try:
        if args.dry_run:
            files = render_domain_files(spec)
            target = domains_path / spec.name.strip()
            if target.exists():
                raise ScaffoldError(f"domain folder already exists: {target}")
            print(f"dry-run: would create {target}")
            for relative in sorted(files):
                print(f"  {relative}")
            return 0

        target = create_domain(spec, domains_path)
    except ScaffoldError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"created {target}")
    print("next steps:")
    print("  1. resolve the TODO(FDE) items in domain.yaml")
    for relative in EVAL_FILES:
        print(f"  - python -m app.evals.run_domain_eval {spec.name.strip()} --file {relative}")
    print("  see docs/runbooks/fde-engagement-playbook.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
