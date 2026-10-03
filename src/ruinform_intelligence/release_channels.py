from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(prefix="/v1/release-channels", tags=["release-channels"])

DEVNET_RELEASE = "RF-DEV-0.3"
MAINNET_RELEASE = "RF-MAINNET-0.1"

# New mechanics land in DEVNET first. MAINNET capability changes are intentionally
# edited/promoted separately; there is no automatic sync from the lab channel.
DEVNET_CAPABILITIES = [
    "object-passport",
    "live-proof",
    "creator-agreement",
    "metadata-editor",
    "canonical-nft",
    "ownership",
]
MAINNET_CAPABILITIES = [
    "object-passport",
    "live-proof",
    "creator-agreement",
    "metadata-editor",
    "canonical-nft",
    "ownership",
]


class ReleaseChannel(BaseModel):
    id: str
    label: str
    network: str
    release: str
    mode: str
    write_enabled: bool
    capabilities: list[str]
    promotion_policy: str


class ReleaseChannelsResponse(BaseModel):
    devnet: ReleaseChannel
    mainnet: ReleaseChannel


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")


def _sqlite_path() -> Path:
    path = Path(os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_network_registry() -> None:
    """Prepare per-network canonical storage without changing the live Devnet path.

    The existing ruinform_nft_passports table remains the current Devnet source of
    truth. This registry gives Mainnet its own future row, so a Devnet certificate
    can never consume the Mainnet canonical slot for the same RuF Object ID.
    """
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ruinform_network_nft_passports (
                        object_id TEXT NOT NULL,
                        network TEXT NOT NULL,
                        status TEXT NOT NULL,
                        mint_address TEXT UNIQUE,
                        transaction_signature TEXT,
                        owner_wallet TEXT,
                        snapshot_hash TEXT,
                        metadata_uri TEXT,
                        royalty_bps INTEGER,
                        terms_hash TEXT,
                        minted_at_iso TEXT,
                        PRIMARY KEY (object_id, network)
                    )
                    """
                )
                # Mirror existing live Devnet records into the network registry.
                cur.execute(
                    """
                    INSERT INTO ruinform_network_nft_passports(
                        object_id,network,status,mint_address,transaction_signature,
                        owner_wallet,snapshot_hash,metadata_uri,royalty_bps,terms_hash,minted_at_iso
                    )
                    SELECT object_id,COALESCE(network,'devnet'),status,mint_address,
                           transaction_signature,owner_wallet,snapshot_hash,metadata_uri,
                           royalty_bps,terms_hash,minted_at_iso
                    FROM ruinform_nft_passports
                    ON CONFLICT (object_id,network) DO UPDATE SET
                        status=EXCLUDED.status,
                        mint_address=EXCLUDED.mint_address,
                        transaction_signature=EXCLUDED.transaction_signature,
                        owner_wallet=EXCLUDED.owner_wallet,
                        snapshot_hash=EXCLUDED.snapshot_hash,
                        metadata_uri=EXCLUDED.metadata_uri,
                        royalty_bps=EXCLUDED.royalty_bps,
                        terms_hash=EXCLUDED.terms_hash,
                        minted_at_iso=EXCLUDED.minted_at_iso
                    """
                )
            conn.commit()
        return

    with sqlite3.connect(_sqlite_path()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_network_nft_passports (
                object_id TEXT NOT NULL,
                network TEXT NOT NULL,
                status TEXT NOT NULL,
                mint_address TEXT UNIQUE,
                transaction_signature TEXT,
                owner_wallet TEXT,
                snapshot_hash TEXT,
                metadata_uri TEXT,
                royalty_bps INTEGER,
                terms_hash TEXT,
                minted_at_iso TEXT,
                PRIMARY KEY (object_id, network)
            )
            """
        )
        # Older local DBs may not have every optional Devnet column. The network
        # registry itself is still prepared; live mirroring will happen once the
        # Devnet schema has those columns.
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO ruinform_network_nft_passports(
                    object_id,network,status,mint_address,transaction_signature,
                    owner_wallet,snapshot_hash,metadata_uri,royalty_bps,terms_hash,minted_at_iso
                )
                SELECT object_id,COALESCE(network,'devnet'),status,mint_address,
                       transaction_signature,owner_wallet,snapshot_hash,metadata_uri,
                       royalty_bps,terms_hash,minted_at_iso
                FROM ruinform_nft_passports
                """
            )
        except sqlite3.OperationalError:
            pass


@router.get("", response_model=ReleaseChannelsResponse)
async def get_release_channels() -> ReleaseChannelsResponse:
    _ensure_network_registry()
    return ReleaseChannelsResponse(
        devnet=ReleaseChannel(
            id="devnet",
            label="DEVNET LAB",
            network="solana-devnet",
            release=DEVNET_RELEASE,
            mode="LAB",
            write_enabled=True,
            capabilities=list(DEVNET_CAPABILITIES),
            promotion_policy="manual",
        ),
        mainnet=ReleaseChannel(
            id="mainnet",
            label="MAINNET",
            network="solana-mainnet-beta",
            release=MAINNET_RELEASE,
            mode="PRODUCTION",
            write_enabled=False,
            capabilities=list(MAINNET_CAPABILITIES),
            promotion_policy="manual",
        ),
    )
