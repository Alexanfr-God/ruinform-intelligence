from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


router = APIRouter()

_SOLANA_DEVNET_RPC = "https://api.devnet.solana.com"
_ALLOWED_METHODS = {
    "getAccountInfo",
    "getMultipleAccounts",
    "getTransaction",
    "getSignaturesForAddress",
    "getSignatureStatuses",
    "getSlot",
    "getBlockTime",
    "getLatestBlockhash",
    "getMinimumBalanceForRentExemption",
}


@router.post("/v1/solana/devnet-rpc")
async def solana_devnet_rpc(request: Request) -> JSONResponse:
    """Authenticated read-only relay for Cloudflare Workers blocked by Solana public RPC.

    The app-level API key dependency protects this route. Only explicitly
    whitelisted read methods are forwarded; transaction submission and
    simulation are intentionally impossible through this bridge.
    """
    raw = await request.body()
    if len(raw) > 64_000:
        raise HTTPException(status_code=413, detail="RPC request too large")
    try:
        payload: Any = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC payload") from exc

    calls = payload if isinstance(payload, list) else [payload]
    if not calls or len(calls) > 20:
        raise HTTPException(status_code=400, detail="Invalid RPC batch")
    for call in calls:
        if not isinstance(call, dict) or str(call.get("method") or "") not in _ALLOWED_METHODS:
            raise HTTPException(status_code=403, detail="RPC method is not allowed")

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            upstream = await client.post(
                _SOLANA_DEVNET_RPC,
                content=raw,
                headers={"content-type": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Solana Devnet RPC unavailable") from exc

    try:
        body = upstream.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid Solana RPC response") from exc
    return JSONResponse(content=body, status_code=upstream.status_code)
