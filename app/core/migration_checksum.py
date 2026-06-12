from __future__ import annotations

import hashlib
from pathlib import Path


def canonical_migration_bytes(path: Path) -> bytes:
    """Normalize line endings so migration identity is portable across hosts."""
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def migration_checksum(path: Path) -> str:
    return hashlib.sha256(canonical_migration_bytes(path)).hexdigest()


def migration_checksum_variants(path: Path) -> set[str]:
    canonical = canonical_migration_bytes(path)
    return {
        hashlib.sha256(canonical).hexdigest(),
        hashlib.sha256(path.read_bytes()).hexdigest(),
        hashlib.sha256(canonical.replace(b"\n", b"\r\n")).hexdigest(),
    }
