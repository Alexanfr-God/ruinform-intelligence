from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .object_passport import object_store
from .wallet_identity import _identity_row


router = APIRouter(prefix="/v1/registry", tags=["generation-registry"])


class RegistryRef(BaseModel):
    session_id: str = Field(min_length=1, max_length=160)
    candidate_id: str = Field(min_length=1, max_length=160)


class RegistryBatchRequest(BaseModel):
    items: list[RegistryRef] = Field(max_length=60)


class RegistryStatus(BaseModel):
    session_id: str
    candidate_id: str
    object_id: str | None = None
    passport_status: Literal["NONE", "PASSPORT"] = "NONE"
    registration_status: Literal["UNREGISTERED", "REGISTERED"] = "UNREGISTERED"
    verification_status: str | None = None
    ownership_status: Literal["NO_OWNER", "OWNED"] = "NO_OWNER"


@router.post("/status-batch")
async def registry_status_batch(payload: RegistryBatchRequest) -> dict[str, object]:
    statuses: list[RegistryStatus] = []
    store = object_store()
    seen: set[tuple[str, str]] = set()
    for ref in payload.items:
        key = (ref.session_id, ref.candidate_id)
        if key in seen:
            continue
        seen.add(key)
        passport = store.find_for_future(ref.session_id, ref.candidate_id)
        if passport is None:
            statuses.append(RegistryStatus(session_id=ref.session_id, candidate_id=ref.candidate_id))
            continue
        identity = _identity_row(passport.object_id)
        statuses.append(
            RegistryStatus(
                session_id=ref.session_id,
                candidate_id=ref.candidate_id,
                object_id=passport.object_id,
                passport_status="PASSPORT",
                registration_status=identity.registration_status,
                verification_status=passport.verification_status,
                ownership_status=identity.ownership_status,
            )
        )
    return {"ok": True, "items": [status.model_dump() for status in statuses]}
