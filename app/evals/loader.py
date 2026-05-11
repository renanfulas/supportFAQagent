from pathlib import Path

from pydantic import ValidationError
import yaml

from app.evals.models import EvalSuite


class EvalSuiteLoader:
    def load(self, eval_path: Path) -> EvalSuite | None:
        if not eval_path.exists():
            return None

        try:
            with eval_path.open("r", encoding="utf-8") as file:
                raw = yaml.safe_load(file) or {}
        except (OSError, yaml.YAMLError):
            return None

        if not isinstance(raw, dict):
            return None

        try:
            return EvalSuite.model_validate(raw)
        except ValidationError:
            return None
