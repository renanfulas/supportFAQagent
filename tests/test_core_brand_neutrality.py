"""Guard: the core (``app/``) never carries a customer's brand.

Customer copy lives in the client pack (``domains/``, including
``domains/installation.yaml``). If this test fails, move the text to the
installation or domain config instead of adding it to the core.
"""

from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parents[1] / "app"
SCANNED_SUFFIXES = {".py", ".html", ".js", ".css"}

# Customer brands this installation has served. Add a new customer here when it
# is onboarded so its name can never leak into the core.
CUSTOMER_BRANDS = ("hostgator",)


def _core_files() -> list[Path]:
    return sorted(
        path
        for path in APP_DIR.rglob("*")
        if path.is_file()
        and path.suffix in SCANNED_SUFFIXES
        and "__pycache__" not in path.parts
    )


def test_core_files_exist() -> None:
    assert _core_files(), "no core files found; the guard would be vacuous"


@pytest.mark.parametrize("brand", CUSTOMER_BRANDS)
def test_core_has_no_customer_brand(brand: str) -> None:
    offenders = [
        f"{path.relative_to(APP_DIR.parent).as_posix()}:{number}"
        for path in _core_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if brand in line.casefold()
    ]

    assert offenders == [], f"customer brand {brand!r} found in the core: {offenders}"
