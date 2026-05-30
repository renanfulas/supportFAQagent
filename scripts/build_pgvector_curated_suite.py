from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml


DOMAIN = "suporte-vps-whatsapp"
INTAKE_DIR = Path("domains") / DOMAIN / "evals" / "intake"
OUTPUT_PATH = Path("domains") / DOMAIN / "evals" / "pgvector_curated.yaml"

QUOTAS = {
    "acesso_ssh": 28,
    "automacoes_n8n": 28,
    "backup_restore": 1,
    "banco_dados": 23,
    "dns_dominios": 17,
    "email_smtp": 1,
    "indisponibilidade_incidente": 28,
    "orientacao_iniciantes": 28,
    "painel_whm_cpanel": 16,
    "performance_recursos": 28,
    "seguranca_escalonamento": 18,
    "webserver_ssl": 24,
}

HEADER = [
    "# Curated pgvector calibration suite.",
    "#",
    "# Built from the synthetic VPS intake, selecting only cases with explicit",
    "# expected_references so we can evaluate retrieval quality with stronger",
    "# signal. This file is opt-in and should be used in the private environment",
    "# prepared for pgvector plus provider-real validation.",
    "",
]


def load_intake_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for path in sorted(INTAKE_DIR.glob("vps_support_faq_*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        for case in payload["cases"]:
            if case["expectation"].get("expected_references"):
                cases.append(case)
    return cases


def build_curated_cases() -> list[dict[str, object]]:
    available = defaultdict(list)
    for case in load_intake_cases():
        available[case["category"]].append(case)

    curated: list[dict[str, object]] = []
    for category, quota in QUOTAS.items():
        selected = available[category][:quota]
        if len(selected) != quota:
            raise RuntimeError(
                f"category {category} expected {quota} cases, found {len(selected)}"
            )
        curated.extend(selected)

    return curated


def write_output(cases: list[dict[str, object]]) -> None:
    payload = {
        "domain": DOMAIN,
        "cases": cases,
    }
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    OUTPUT_PATH.write_text("\n".join(HEADER) + text, encoding="utf-8")


def main() -> None:
    cases = build_curated_cases()
    write_output(cases)
    print(f"wrote {OUTPUT_PATH} with {len(cases)} cases")


if __name__ == "__main__":
    main()
