from __future__ import annotations

import sqlite3

from . import nft_devnet


_original_postgres_schema = nft_devnet._ensure_postgres_schema
_original_sqlite_schema = nft_devnet._ensure_sqlite_schema


def _base_nft_table_postgres(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_nft_passports (
                object_id TEXT PRIMARY KEY,
                chain TEXT NOT NULL,
                status TEXT NOT NULL,
                mint_address TEXT UNIQUE,
                royalty_bps INTEGER NOT NULL,
                terms_hash TEXT NOT NULL,
                minted_at_iso TEXT
            )
            """
        )
    conn.commit()


def _base_nft_table_sqlite(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_nft_passports (
            object_id TEXT PRIMARY KEY,
            chain TEXT NOT NULL,
            status TEXT NOT NULL,
            mint_address TEXT UNIQUE,
            royalty_bps INTEGER NOT NULL,
            terms_hash TEXT NOT NULL,
            minted_at_iso TEXT
        )
        """
    )


def ensure_postgres_schema(conn) -> None:
    _base_nft_table_postgres(conn)
    _original_postgres_schema(conn)


def ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    _base_nft_table_sqlite(conn)
    _original_sqlite_schema(conn)


# nft_devnet resolves these helpers by module globals at request time.
nft_devnet._ensure_postgres_schema = ensure_postgres_schema
nft_devnet._ensure_sqlite_schema = ensure_sqlite_schema
