"""Registro de dominios na tabela ``domains``.

A conversa so e gravada para dominios que existem nessa tabela. A ingestao no
pgvector registra o dominio que ingere; a instalacao (``scripts.post_install``)
registra todos os dominios do pacote do cliente sem exigir chave de embedding.
"""

from __future__ import annotations

from typing import Any


UPSERT_DOMAIN_SQL = """
    INSERT INTO domains (name, display_name)
    VALUES (%s, %s)
    ON CONFLICT (name) DO UPDATE
    SET display_name = EXCLUDED.display_name,
        updated_at = now()
    RETURNING id
"""


def upsert_domain(cursor: Any, *, name: str, display_name: str) -> str:
    """Create or refresh one domain row and return its id."""

    cursor.execute(UPSERT_DOMAIN_SQL, (name, display_name))
    return str(cursor.fetchone()[0])
