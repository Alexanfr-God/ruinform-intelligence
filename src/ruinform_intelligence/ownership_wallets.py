from __future__ import annotations

import sqlite3

from pydantic import BaseModel

from .ownership_core import _database_url, _sqlite_path, router
from .object_transfers import _public_object_id
from .wallet_identity import _validated_wallet


class OwnedArtifact(BaseModel):
    object_id: str
    network: str = "devnet"
    asset_address: str
    owner_wallet: str
    minted_at_iso: str | None = None


class OwnedArtifactsResponse(BaseModel):
    wallet_address: str
    network: str = "devnet"
    items: list[OwnedArtifact]


def _wallet_rows(wallet_address: str) -> list[tuple]:
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT object_id, mint_address, owner_wallet, minted_at_iso
                    FROM ruinform_nft_passports
                    WHERE owner_wallet=%s
                      AND status='MINTED'
                      AND COALESCE(network,'devnet')='devnet'
                    ORDER BY minted_at_iso DESC NULLS LAST, object_id DESC
                    """,
                    (wallet_address,),
                )
                return list(cur.fetchall())
    with sqlite3.connect(_sqlite_path()) as conn:
        try:
            return list(
                conn.execute(
                    """
                    SELECT object_id, mint_address, owner_wallet, minted_at_iso
                    FROM ruinform_nft_passports
                    WHERE owner_wallet=? AND status='MINTED'
                    ORDER BY minted_at_iso DESC, object_id DESC
                    """,
                    (wallet_address,),
                ).fetchall()
            )
        except sqlite3.OperationalError:
            return []


@router.get("/wallet/{wallet_address}/devnet", response_model=OwnedArtifactsResponse)
async def wallet_owned_artifacts(wallet_address: str) -> OwnedArtifactsResponse:
    wallet, _ = _validated_wallet(wallet_address)
    items = [
        OwnedArtifact(
            object_id=_public_object_id(str(row[0])),
            asset_address=str(row[1]),
            owner_wallet=str(row[2]),
            minted_at_iso=str(row[3]) if row[3] else None,
        )
        for row in _wallet_rows(wallet)
        if row[1]
    ]
    return OwnedArtifactsResponse(wallet_address=wallet, items=items)
