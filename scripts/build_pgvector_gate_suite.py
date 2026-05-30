from __future__ import annotations

from pathlib import Path

import yaml


DOMAIN = "suporte-vps-whatsapp"
CURATED_PATH = Path("domains") / DOMAIN / "evals" / "pgvector_curated.yaml"
OUTPUT_PATH = Path("domains") / DOMAIN / "evals" / "pgvector_gate.yaml"

SELECTED_IDS = [
    "vps-011-ssh-timeout",
    "vps-012-ssh-connection-refused",
    "vps-013-ssh-porta-alterada",
    "vps-016-chave-ssh-nao-funciona",
    "vps-017-firewall-bloqueou-ssh",
    "vps-020-erro-permission-denied-publickey",
    "vps-176",
    "vps-177",
    "vps-178",
    "vps-179",
    "vps-180",
    "vps-181",
    "vps-182",
    "vps-183",
    "vps-057-vps-nao-pinga",
    "vps-058-servidor-reinicia-sozinho",
    "vps-059-boot-falhou",
    "vps-060-recovery-mode",
    "vps-061-aplicacoes-fora",
    "vps-063-status-node",
    "vps-064-perdi-acesso-total",
    "vps-551",
    "vps-552",
    "vps-553",
    "vps-554",
    "vps-555",
    "vps-556",
    "vps-563",
    "vps-095-n8n-nao-abre",
    "vps-096-n8n-ssl-webhook",
    "vps-097-n8n-conexao-perdida",
    "vps-098-evolution-container-nao-sobe",
    "vps-099-webhook-whatsapp-sem-resposta",
    "vps-100-qrcode-evolution-na-vps",
    "vps-926",
    "vps-927",
    "vps-929",
    "vps-930",
    "vps-932",
    "vps-933",
    "vps-941",
    "vps-944",
    "vps-945",
    "vps-947",
    "vps-075-malware-miner",
    "vps-077-ataque-bruteforce",
    "vps-731",
    "vps-732",
    "vps-733",
    "vps-734",
    "vps-735",
    "vps-736",
    "vps-737",
    "vps-738",
    "vps-740",
    "vps-761",
    "vps-047-cpu-100",
    "vps-048-ram-esgotada",
    "vps-049-disco-cheio",
    "vps-051-site-lento",
    "vps-053-container-consome-memoria",
    "vps-056-preciso-upgrade",
    "vps-476",
    "vps-477",
    "vps-479",
    "vps-480",
    "vps-001-primeiro-acesso",
    "vps-002-diferenca-vps-hospedagem",
    "vps-003-vps-sem-painel",
    "vps-004-root-o-que-significa",
    "vps-005-escolher-sistema-operacional",
    "vps-007-instalar-docker",
    "vps-084-nginx-nao-sobe",
    "vps-085-apache-porta-80",
    "vps-091-banco-consome-disco",
    "vps-092-postgres-nao-inicia",
    "vps-034-whm-nao-carrega",
    "vps-371",
]

HEADER = [
    "# Gate pgvector suite for release-oriented validation.",
    "#",
    "# This suite is a smaller, high-signal subset of pgvector_curated.yaml.",
    "# It prioritizes SSH access, incident handling, n8n and webhook flows,",
    "# QR Code and Evolution behavior, security-sensitive cases, and the domain's",
    "# strongest knowledge articles. Use it as the final release-facing signal",
    "# after broader calibration in the curated suite.",
    "",
]


def load_curated_cases() -> dict[str, dict[str, object]]:
    payload = yaml.safe_load(CURATED_PATH.read_text(encoding="utf-8"))
    return {case["id"]: case for case in payload["cases"]}


def main() -> None:
    curated = load_curated_cases()
    selected_cases: list[dict[str, object]] = []
    missing = [case_id for case_id in SELECTED_IDS if case_id not in curated]
    if missing:
        raise RuntimeError(f"missing curated ids: {missing}")

    for case_id in SELECTED_IDS:
        selected_cases.append(curated[case_id])

    payload = {
        "domain": DOMAIN,
        "cases": selected_cases,
    }
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    OUTPUT_PATH.write_text("\n".join(HEADER) + text, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH} with {len(selected_cases)} cases")


if __name__ == "__main__":
    main()
