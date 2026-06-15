"""Run a sanitized readiness gate against the configured PostgreSQL runtime."""

from __future__ import annotations

import json
import sys

from app.core.config import get_settings
from app.db.runtime import DatabaseRuntime
from app.health.service import HealthService


def main() -> int:
    try:
        settings = get_settings()
        runtime = DatabaseRuntime(settings)
        runtime.open()
        snapshot = HealthService(runtime).readiness()
    except Exception:
        print("readiness check failed; inspect private runtime logs", file=sys.stderr)
        return 1
    finally:
        if "runtime" in locals():
            runtime.close()

    print(json.dumps(snapshot, sort_keys=True))
    return 0 if snapshot["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
