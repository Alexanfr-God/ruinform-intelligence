from __future__ import annotations

import base64
import hashlib

from fastapi import APIRouter, File, HTTPException, UploadFile

from .live_api import get_session
from .verification import VerificationError, VerificationOutput, verify_physical_build
from .verification_state import apply_verification_result


router = APIRouter(prefix="/v1/live-transformations", tags=["live-verification"])
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


async def _upload_to_data_url(upload: UploadFile, *, index: int) -> tuple[str, str]:
    media_type = upload.content_type or ""
    if media_type not in _ALLOWED_IMAGE_TYPES:
        raise ValueError(f"Unsupported verification image type for image {index}: {media_type or 'unknown'}")
    raw = await upload.read(_MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise ValueError(f"Verification image {index} is empty")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise ValueError(f"Verification image {index} exceeds 8 MB")
    digest = hashlib.sha256(raw).hexdigest()
    return f"data:{media_type};base64,{base64.b64encode(raw).decode('ascii')}", digest


def _reference_digest(reference_image_url: str) -> str | None:
    if not reference_image_url.startswith("data:image/") or ";base64," not in reference_image_url:
        return None
    try:
        raw = base64.b64decode(reference_image_url.split(",", 1)[1], validate=True)
    except (ValueError, TypeError):
        return None
    return hashlib.sha256(raw).hexdigest()


def _reference_image_url(session) -> str | None:
    """Use the accepted render when available; otherwise use the last AI target.

    A rejected render can still be the build's visual target. Treating it as a
    comparison reference does not promote it to accepted proof or change the
    immutable Future contract.
    """

    render_result = session.render_result
    if render_result is None:
        return None
    if render_result.accepted_image_url:
        return str(render_result.accepted_image_url)
    if render_result.attempts:
        return str(render_result.attempts[-1].render.image_url)
    return None


@router.post("/{session_id}/verify-upload", response_model=VerificationOutput)
async def verify_upload(
    session_id: str,
    images: list[UploadFile] = File(...),
) -> VerificationOutput:
    if not 2 <= len(images) <= 3:
        raise HTTPException(status_code=400, detail="Upload 2 or 3 photos of the physical build")

    session = get_session(session_id)
    reference_image_url = _reference_image_url(session)
    if not reference_image_url:
        raise HTTPException(status_code=409, detail="Render the selected future before verification")

    future = None
    if session.futures is not None and session.selected_candidate_id:
        future = next(
            (
                item
                for item in session.futures.selected_futures
                if item.candidate.candidate_id == session.selected_candidate_id
            ),
            None,
        )

    try:
        encoded = [
            await _upload_to_data_url(image, index=index)
            for index, image in enumerate(images, start=1)
        ]
        build_image_urls = [item[0] for item in encoded]
        build_digests = [item[1] for item in encoded]
        if len(set(build_digests)) != len(build_digests):
            raise HTTPException(
                status_code=400,
                detail="Duplicate verification photos detected. Add different camera views of the physical build.",
            )
        reference_digest = _reference_digest(reference_image_url)
        if reference_digest and reference_digest in build_digests:
            raise HTTPException(
                status_code=400,
                detail="The generated reference cannot be submitted as physical-build evidence. Photograph the real object.",
            )
        result = await verify_physical_build(
            reference_image_url=reference_image_url,
            build_image_urls=build_image_urls,
            concept_name=future.candidate.name if future is not None else None,
            concept_description=(
                future.candidate.one_line or future.candidate.transformation_logic
                if future is not None
                else None
            ),
        )
        candidate_id = (
            future.candidate.candidate_id
            if future is not None
            else session.selected_candidate_id
        )
        if candidate_id:
            apply_verification_result(
                source_session_id=session_id,
                candidate_id=candidate_id,
                result=result,
            )
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VerificationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
