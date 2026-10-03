from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import nft_devnet
from .nft_reconciliation import _confirmed_signature, _finalize_recovered, _pending_intents
from .wallet_identity import _identity_row


router = APIRouter(prefix="/v1/nft-passports", tags=["nft-passport-reconciliation"])


@router.post("/{object_id}/devnet/reconcile-system", response_model=nft_devnet.DevnetNftStatusResponse)
async def reconcile_devnet_mint_system(object_id: str) -> nft_devnet.DevnetNftStatusResponse:
    """Reconcile already-confirmed Devnet assets without creating a new transaction.

    This route is still protected by the service-wide RUINFORM API key. It may only
    record an on-chain Core asset whose reserved mint intent belongs to the wallet
    already registered as the object's immutable creator.
    """
    backend_id = nft_devnet._backend_object_id(object_id)
    identity = _identity_row(backend_id)
    wallet = identity.creator_wallet
    if not wallet:
        raise HTTPException(status_code=409, detail="Creator identity is not registered for this object")

    current = nft_devnet._mint_status(backend_id)
    if current.status == "MINTED":
        return current

    found: list[tuple[int, str, str, str]] = []
    for intent_id, asset_address, _created_at in _pending_intents(backend_id, wallet):
        confirmed = await _confirmed_signature(asset_address, wallet)
        if confirmed:
            signature, slot = confirmed
            found.append((slot, intent_id, asset_address, signature))

    if not found:
        return current

    found.sort(key=lambda item: item[0])
    _slot, canonical_intent, canonical_asset, canonical_signature = found[0]
    duplicates = [(intent_id, asset, signature) for _slot, intent_id, asset, signature in found[1:]]
    return _finalize_recovered(
        object_id=backend_id,
        wallet=wallet,
        intent_id=canonical_intent,
        asset_address=canonical_asset,
        transaction_signature=canonical_signature,
        duplicates=duplicates,
    )
