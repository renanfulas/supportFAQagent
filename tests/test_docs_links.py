"""Guarda de integridade dos links de documentação.

Estes testes existem para que a reorganização dos docs em pastas
(`architecture/`, `setup/`, `MVP/`, ...) não deixe links quebrados e para
**isolar falhas de documentação do resto da suíte**: se algo aqui falhar, o
problema foi doc, não código.

Dois testes:

- ``test_all_markdown_doc_links_resolve`` — todo link markdown ``[..](alvo.md)``
  e todo caminho literal ``docs/...md`` (em ``.md``, ``.py``, ``.yaml``, ``.sql``)
  precisa resolver para um arquivo existente.
- ``test_references_legacy_mapping`` — o índice de redirecionamento
  ``docs/references-legacy.md`` precisa estar coerente: todo caminho *novo*
  existe e todo caminho *antigo* não existe mais (migração completa).

Docs em ``docs/archive/`` são registros históricos congelados (podem citar
tecnologia removida, ex.: n8n) e ficam fora da checagem — exceto o índice
``docs/archive/README.md``, que é ativo e deve resolver.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

SCAN_EXTENSIONS = {".md", ".py", ".yaml", ".yml", ".sql"}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "build",
    "dist",
}

ARCHIVE_DIR = REPO_ROOT / "docs" / "archive"
ARCHIVE_README = ARCHIVE_DIR / "README.md"
REFERENCES_LEGACY = REPO_ROOT / "docs" / "references-legacy.md"

# Link markdown inline: [texto](alvo) — captura o alvo.
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# Caminho literal de doc a partir da raiz do repo.
DOCS_PATH_RE = re.compile(r"docs/[A-Za-z0-9_][A-Za-z0-9_./-]*\.md")


def _iter_scanned_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(REPO_ROOT).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        if path.suffix.lower() in SCAN_EXTENSIONS:
            files.append(path)
    return files


def _is_frozen_archive(path: Path) -> bool:
    """True para docs arquivados congelados (todo o archive, menos seu README)."""
    try:
        path.relative_to(ARCHIVE_DIR)
    except ValueError:
        return False
    return path != ARCHIVE_README


def _clean_link_target(raw: str) -> str | None:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target:
        return None
    # Remove o título opcional: [x](alvo.md "Título").
    if " " in target:
        target = target.split(" ", 1)[0]
    # Ignora externos, âncoras puras e placeholders (ex.: <domain>).
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    if "<" in target or ">" in target:
        return None
    # Remove âncora de seção: arquivo.md#secao.
    target = target.split("#", 1)[0]
    return target or None


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def test_all_markdown_doc_links_resolve() -> None:
    broken: list[str] = []

    for path in _iter_scanned_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")

        # (A) Links markdown que apontam para .md, relativos ao próprio arquivo.
        if path.suffix.lower() == ".md":
            for match in MD_LINK_RE.finditer(text):
                target = _clean_link_target(match.group(1))
                if not target or not target.endswith(".md"):
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    broken.append(f"{rel}:{_line_of(text, match.start())} -> {target}")

        # (B) Caminhos literais docs/...md, relativos à raiz do repo.
        if _is_frozen_archive(path) or path == REFERENCES_LEGACY:
            continue
        for match in DOCS_PATH_RE.finditer(text):
            docs_path = match.group(0)
            if not (REPO_ROOT / docs_path).exists():
                broken.append(f"{rel}:{_line_of(text, match.start())} -> {docs_path}")

    assert not broken, (
        "Links de documentação quebrados (corrija o caminho ou registre em "
        "docs/references-legacy.md):\n  " + "\n  ".join(sorted(set(broken)))
    )


def test_references_legacy_mapping() -> None:
    if not REFERENCES_LEGACY.exists():
        pytest.skip("docs/references-legacy.md ainda não foi criado")

    text = REFERENCES_LEGACY.read_text(encoding="utf-8", errors="replace")
    redirects = 0
    problems: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        paths = DOCS_PATH_RE.findall(line)
        # Cada linha de redirecionamento tem exatamente: antigo, novo.
        if len(paths) != 2:
            continue
        old_path, new_path = paths
        redirects += 1
        if not (REPO_ROOT / new_path).exists():
            problems.append(f"caminho novo não existe: {new_path}")
        if (REPO_ROOT / old_path).exists():
            problems.append(f"caminho antigo ainda existe (migração incompleta): {old_path}")

    assert redirects > 0, "Nenhuma linha de redirecionamento encontrada em references-legacy.md"
    assert not problems, "Mapa de transição inconsistente:\n  " + "\n  ".join(problems)
