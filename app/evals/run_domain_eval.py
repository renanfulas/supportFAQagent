import argparse
import json
from pathlib import Path
import sys

from app.core.config import get_settings
from app.domain_engine.loader import DomainLoader
from app.evals.loader import EvalSuiteLoader
from app.evals.runner import DomainEvalRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local domain evals.")
    parser.add_argument("domain", help="Domain name, for example suporte-vps-whatsapp")
    parser.add_argument(
        "--file",
        default="evals/cases.yaml",
        help="Eval file path relative to the domain root.",
    )
    args = parser.parse_args()

    settings = get_settings()
    domain = DomainLoader(settings.domains_path).load(args.domain)
    if domain is None:
        print(json.dumps({"error": "domain_not_found", "domain": args.domain}))
        return 1

    suite_path = domain.root_path / Path(args.file)
    suite = EvalSuiteLoader().load(suite_path)
    if suite is None:
        print(json.dumps({"error": "eval_suite_not_found_or_invalid", "path": str(suite_path)}))
        return 1

    if suite.domain != domain.name:
        print(
            json.dumps(
                {
                    "error": "eval_suite_domain_mismatch",
                    "domain": domain.name,
                    "suite_domain": suite.domain,
                }
            )
        )
        return 1

    result = DomainEvalRunner().run(domain=domain, suite=suite)
    print(result.model_dump_json(indent=2))
    return 0 if result.failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
