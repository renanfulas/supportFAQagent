"""Gestao de operadores do console de suporte (staff_members, migration 014).

Adicionar/remover operador e um comando; nada de editar env nem reiniciar
servico na VPS:

    python scripts/manage_staff.py add "+5511999999999" --name "Renan"
    python scripts/manage_staff.py disable "+5511999999999"
    python scripts/manage_staff.py list

Usa ``DATABASE_URL`` e ``IDENTITY_HASH_SECRET`` do ambiente (mesmo HMAC de
``verified_identities``; rotacao do secret exige recadastrar cada operador).
Nunca imprime o telefone completo — apenas display_name, last4 e status.

``disable`` tambem apaga sessoes e lembretes vivos do operador; o join com
``status = 'active'`` nas rotas ja derrubaria, isto e higiene de dados.
"""

from __future__ import annotations

import argparse
import os
import sys

from app.web_auth.service import _hmac_digest, normalize_phone


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="add (or reactivate) an operator")
    add_parser.add_argument("phone", help="E.164 phone, e.g. +5511999999999")
    add_parser.add_argument("--name", required=True, help="display name shown in the queue")

    disable_parser = subparsers.add_parser("disable", help="disable an operator")
    disable_parser.add_argument("phone", help="E.164 phone, e.g. +5511999999999")

    subparsers.add_parser("list", help="list operators (display_name, last4, status)")

    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 2
    identity_hash_secret = os.getenv("IDENTITY_HASH_SECRET")
    if not identity_hash_secret and args.command != "list":
        print("IDENTITY_HASH_SECRET is required.", file=sys.stderr)
        return 2

    import psycopg

    with psycopg.connect(database_url) as connection:
        if args.command == "add":
            return _add(connection, identity_hash_secret, args.phone, args.name)
        if args.command == "disable":
            return _disable(connection, identity_hash_secret, args.phone)
        return _list(connection)


def _hash_phone(identity_hash_secret: str, phone: str) -> tuple[str, str]:
    try:
        normalized = normalize_phone(phone)
    except ValueError:
        print("phone must use E.164 format (e.g. +5511999999999).", file=sys.stderr)
        raise SystemExit(2)
    return _hmac_digest(identity_hash_secret, normalized), normalized[-4:]


def _add(connection, identity_hash_secret: str, phone: str, name: str) -> int:
    display_name = name.strip()
    if not display_name:
        print("--name cannot be empty.", file=sys.stderr)
        return 2
    phone_hash, phone_last4 = _hash_phone(identity_hash_secret, phone)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO staff_members (phone_hash, phone_last4, display_name, status)
            VALUES (%s, %s, %s, 'active')
            ON CONFLICT (phone_hash) DO UPDATE
            SET display_name = EXCLUDED.display_name,
                phone_last4 = EXCLUDED.phone_last4,
                status = 'active',
                updated_at = now()
            """,
            (phone_hash, phone_last4, display_name),
        )
    connection.commit()
    print(f"active: {display_name} (****{phone_last4})")
    return 0


def _disable(connection, identity_hash_secret: str, phone: str) -> int:
    phone_hash, phone_last4 = _hash_phone(identity_hash_secret, phone)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE staff_members
            SET status = 'disabled', updated_at = now()
            WHERE phone_hash = %s
            RETURNING id, display_name
            """,
            (phone_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            print(f"no operator found for ****{phone_last4}.", file=sys.stderr)
            connection.rollback()
            return 1
        staff_id, display_name = row
        cursor.execute("DELETE FROM staff_sessions WHERE staff_id = %s", (staff_id,))
        cursor.execute("DELETE FROM staff_login_hints WHERE staff_id = %s", (staff_id,))
    connection.commit()
    print(f"disabled: {display_name} (****{phone_last4})")
    return 0


def _list(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT display_name, phone_last4, status
            FROM staff_members
            ORDER BY display_name
            """,
        )
        rows = cursor.fetchall()
    if not rows:
        print("no operators registered.")
        return 0
    for display_name, phone_last4, status in rows:
        print(f"{display_name}\t****{phone_last4}\t{status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
