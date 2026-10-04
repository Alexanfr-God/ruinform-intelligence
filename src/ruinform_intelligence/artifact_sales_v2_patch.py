from __future__ import annotations

import base64

from fastapi import HTTPException

from . import artifact_sales as sales

DEPLOYED_SALE_PROGRAM_ID = "RtcEaWSqDLej5FBWTkwGNraSEeb3zPGHmXg9FfVqNce"

sales.SALE_PROGRAM_ID = DEPLOYED_SALE_PROGRAM_ID
sales._CHAIN_STATUS = {
    1: "LISTED",
    2: "FUNDED",
    3: "FUNDED",  # legacy shipped endpoint expects FUNDED after the on-chain SHIPPED transition
    4: "RECEIPT_CONFIRMED",
    5: "SETTLED",
    6: "CANCELLED",
}


async def _escrow_state_v2(pda: str) -> dict:
    body = await sales._rpc("getAccountInfo", [pda, {"encoding": "base64", "commitment": "confirmed"}])
    value = (body.get("result") or {}).get("value")
    if not value or str(value.get("owner")) != DEPLOYED_SALE_PROGRAM_ID:
        raise HTTPException(status_code=409, detail="RUINFORM Sale V0 escrow PDA is not active on Devnet")
    encoded = (value.get("data") or [None])[0]
    try:
        raw = base64.b64decode(encoded)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Sale escrow state could not be decoded") from exc
    if len(raw) < 200 or raw[:8] != b"RUFSALE1" or raw[8] != 2:
        raise HTTPException(status_code=409, detail="Sale escrow state has an unknown version")
    buyer_raw = raw[72:104]
    chain_status = int(raw[10])
    return {
        "status": sales._CHAIN_STATUS.get(chain_status, "UNKNOWN"),
        "chain_status": chain_status,
        "nonce": int.from_bytes(raw[16:24], "little"),
        "price_lamports": int.from_bytes(raw[24:32], "little"),
        "expires_at_unix": int.from_bytes(raw[32:40], "little", signed=True),
        "seller": sales._b58encode(raw[40:72]),
        "buyer": None if buyer_raw == bytes(32) else sales._b58encode(buyer_raw),
        "asset": sales._b58encode(raw[104:136]),
        "treasury": sales._b58encode(raw[136:168]),
        "object_hash": raw[168:200].hex(),
        "lamports": int(value.get("lamports") or 0),
    }


sales._escrow_state = _escrow_state_v2
