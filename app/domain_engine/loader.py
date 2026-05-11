from pathlib import Path

from pydantic import ValidationError
import yaml

from app.domain_engine.models import DomainConfig


class DomainLoader:
    def __init__(self, domains_path: Path) -> None:
        self.domains_path = domains_path

    def list_domains(self) -> list[str]:
        if not self.domains_path.exists():
            return []

        return sorted(
            item.name
            for item in self.domains_path.iterdir()
            if item.is_dir() and self.load(item.name) is not None
        )

    def load(self, domain_name: str) -> DomainConfig | None:
        domain_root = self.domains_path / domain_name
        config_path = domain_root / "domain.yaml"
        if not config_path.exists():
            return None

        try:
            with config_path.open("r", encoding="utf-8") as file:
                raw = yaml.safe_load(file) or {}
        except (OSError, yaml.YAMLError):
            return None

        if not isinstance(raw, dict):
            return None

        if raw.get("name") != domain_name:
            return None

        raw["root_path"] = domain_root
        try:
            return DomainConfig.model_validate(raw)
        except ValidationError:
            return None
