from pathlib import Path

import yaml

from app.domain_engine.models import DomainConfig


class DomainLoader:
    def __init__(self, domains_path: Path) -> None:
        self.domains_path = domains_path

    def list_domains(self) -> list[str]:
        if not self.domains_path.exists():
            return []

        return sorted(
            item.name for item in self.domains_path.iterdir() if item.is_dir()
        )

    def load(self, domain_name: str) -> DomainConfig | None:
        domain_root = self.domains_path / domain_name
        config_path = domain_root / "domain.yaml"
        if not config_path.exists():
            return None

        with config_path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}

        raw["root_path"] = domain_root
        return DomainConfig.model_validate(raw)
