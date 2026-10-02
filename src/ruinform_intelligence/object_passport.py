from __future__ import annotations

import html
import os
import sqlite3
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .future_models import ReviewedFuture
from .run_store import SessionNotFound, SqliteRunStore, TransformationSession, utc_now_iso


router = APIRouter(tags=["object-passport"])


class PassportMaterial(BaseModel):
    item_id: str
    display_name: str
    decision: Literal["used", "omitted", "unassigned"]
    role: str | None = None
    note: str | None = None


class ObjectPassport(BaseModel):
    version: Literal["object-passport-v0.1"] = "object-passport-v0.1"
    object_id: str
    source_session_id: str
    project_id: str
    candidate_id: str
    title: str
    one_line: str
    transformation_logic: str
    artist_meaning: str
    materials: list[PassportMaterial]
    source_image_count: int
    render_image_url: str | None = None
    build_status: Literal["IDEA", "BUILDING", "PHYSICAL", "VERIFIED"] = "IDEA"
    verification_status: Literal["UNVERIFIED", "VERIFIED", "NEEDS_REVIEW"] = "UNVERIFIED"
    owner_wallet: str | None = None
    created_at_iso: str


class ObjectPassportEnvelope(BaseModel):
    object: ObjectPassport
    public_path: str
    api_path: str


class ObjectPassportNotFound(KeyError):
    pass


def _find_future(session: TransformationSession, candidate_id: str) -> ReviewedFuture:
    if session.futures is None:
        raise HTTPException(status_code=409, detail="No Future exists for this project yet")
    future = next(
        (item for item in session.futures.selected_futures if item.candidate.candidate_id == candidate_id),
        None,
    )
    if future is None:
        raise HTTPException(status_code=404, detail="Future is unavailable")
    if session.selected_candidate_id != candidate_id:
        raise HTTPException(
            status_code=409,
            detail="Object Passport can only be created from the currently selected Future",
        )
    return future


def _render_image_for(session: TransformationSession, candidate_id: str) -> str | None:
    result = session.render_result
    if (
        result is None
        or result.candidate_id != candidate_id
        or result.status != "pass"
        or not result.accepted_image_url
    ):
        return None
    image = str(result.accepted_image_url)
    # V0 keeps the durable passport compact. Provider-hosted HTTPS images are safe to
    # snapshot; base64 renders remain in the transformation session until media storage
    # is introduced in the next passport/media iteration.
    return image if image.startswith(("https://", "http://")) else None


def build_passport_snapshot(
    *,
    session: TransformationSession,
    future: ReviewedFuture,
    object_id: str,
    created_at_iso: str,
) -> ObjectPassport:
    candidate = future.candidate
    used = {item.material_item_id: item for item in candidate.material_uses}
    omitted = {item.material_item_id: item for item in candidate.omitted_materials}
    materials: list[PassportMaterial] = []

    for source in session.project_state.materials:
        use = used.get(source.item_id)
        omission = omitted.get(source.item_id)
        if use is not None:
            materials.append(
                PassportMaterial(
                    item_id=source.item_id,
                    display_name=source.display_name,
                    decision="used",
                    role=use.role,
                    note=use.note,
                )
            )
        elif omission is not None:
            materials.append(
                PassportMaterial(
                    item_id=source.item_id,
                    display_name=source.display_name,
                    decision="omitted",
                    note=omission.reason,
                )
            )
        else:
            # Archived Futures can predate explicit omission accounting. Keep that gap
            # visible instead of inventing a material role after the fact.
            materials.append(
                PassportMaterial(
                    item_id=source.item_id,
                    display_name=source.display_name,
                    decision="unassigned",
                    note="No explicit material decision was stored in this Future.",
                )
            )

    return ObjectPassport(
        object_id=object_id,
        source_session_id=session.session_id,
        project_id=session.project_id,
        candidate_id=candidate.candidate_id,
        title=candidate.name,
        one_line=candidate.one_line,
        transformation_logic=candidate.transformation_logic,
        artist_meaning=candidate.artistic_thesis,
        materials=materials,
        source_image_count=sum(1 for item in session.project_state.evidence if item.source_type == "image"),
        render_image_url=_render_image_for(session, candidate.candidate_id),
        created_at_iso=created_at_iso,
    )


class SqliteObjectPassportStore:
    backend_name = "sqlite"

    def __new__(cls, path: str | None = None):
        if cls is SqliteObjectPassportStore and (
            os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
        ):
            return PostgresObjectPassportStore()
        return super().__new__(cls)

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ruinform_objects (
                    internal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    object_id TEXT NOT NULL UNIQUE,
                    source_session_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at_iso TEXT NOT NULL,
                    UNIQUE(source_session_id, candidate_id)
                )
                """
            )

    def get(self, object_id: str) -> ObjectPassport:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM ruinform_objects WHERE object_id = ?",
                (object_id,),
            ).fetchone()
        if row is None:
            raise ObjectPassportNotFound(object_id)
        return ObjectPassport.model_validate_json(row[0])

    def find_for_future(self, source_session_id: str, candidate_id: str) -> ObjectPassport | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM ruinform_objects WHERE source_session_id = ? AND candidate_id = ?",
                (source_session_id, candidate_id),
            ).fetchone()
        if row is None:
            return None
        return ObjectPassport.model_validate_json(row[0])

    def create(self, *, session: TransformationSession, future: ReviewedFuture) -> ObjectPassport:
        existing = self.find_for_future(session.session_id, future.candidate.candidate_id)
        if existing is not None:
            return existing

        created = utc_now_iso()
        pending_id = f"PENDING-{uuid4()}"
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO ruinform_objects(object_id, source_session_id, candidate_id, payload_json, created_at_iso)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (pending_id, session.session_id, future.candidate.candidate_id, "{}", created),
                )
                internal_id = int(cursor.lastrowid)
                object_id = f"RF-{internal_id:04d}"
                passport = build_passport_snapshot(
                    session=session,
                    future=future,
                    object_id=object_id,
                    created_at_iso=created,
                )
                conn.execute(
                    "UPDATE ruinform_objects SET object_id = ?, payload_json = ? WHERE internal_id = ?",
                    (object_id, passport.model_dump_json(), internal_id),
                )
                return passport
        except sqlite3.IntegrityError:
            existing = self.find_for_future(session.session_id, future.candidate.candidate_id)
            if existing is not None:
                return existing
            raise


class PostgresObjectPassportStore:
    backend_name = "postgres"

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for PostgresObjectPassportStore")
        self._initialized = False

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for PostgresObjectPassportStore") from exc
        return psycopg.connect(self.database_url)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ruinform_objects (
                        internal_id BIGSERIAL PRIMARY KEY,
                        object_id TEXT NOT NULL UNIQUE,
                        source_session_id TEXT NOT NULL,
                        candidate_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at_iso TEXT NOT NULL,
                        UNIQUE(source_session_id, candidate_id)
                    )
                    """
                )
            conn.commit()
        self._initialized = True

    def get(self, object_id: str) -> ObjectPassport:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload_json FROM ruinform_objects WHERE object_id = %s", (object_id,))
                row = cur.fetchone()
        if row is None:
            raise ObjectPassportNotFound(object_id)
        return ObjectPassport.model_validate_json(row[0])

    def find_for_future(self, source_session_id: str, candidate_id: str) -> ObjectPassport | None:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload_json FROM ruinform_objects WHERE source_session_id = %s AND candidate_id = %s",
                    (source_session_id, candidate_id),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return ObjectPassport.model_validate_json(row[0])

    def create(self, *, session: TransformationSession, future: ReviewedFuture) -> ObjectPassport:
        self._ensure_initialized()
        existing = self.find_for_future(session.session_id, future.candidate.candidate_id)
        if existing is not None:
            return existing

        created = utc_now_iso()
        pending_id = f"PENDING-{uuid4()}"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ruinform_objects(object_id, source_session_id, candidate_id, payload_json, created_at_iso)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(source_session_id, candidate_id) DO NOTHING
                    RETURNING internal_id
                    """,
                    (pending_id, session.session_id, future.candidate.candidate_id, "{}", created),
                )
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        "SELECT payload_json FROM ruinform_objects WHERE source_session_id = %s AND candidate_id = %s",
                        (session.session_id, future.candidate.candidate_id),
                    )
                    existing_row = cur.fetchone()
                    if existing_row is None:
                        raise RuntimeError("Could not resolve concurrent Object Passport creation")
                    return ObjectPassport.model_validate_json(existing_row[0])

                internal_id = int(row[0])
                object_id = f"RF-{internal_id:04d}"
                passport = build_passport_snapshot(
                    session=session,
                    future=future,
                    object_id=object_id,
                    created_at_iso=created,
                )
                cur.execute(
                    "UPDATE ruinform_objects SET object_id = %s, payload_json = %s WHERE internal_id = %s",
                    (object_id, passport.model_dump_json(), internal_id),
                )
            conn.commit()
        return passport


def object_store() -> SqliteObjectPassportStore | PostgresObjectPassportStore:
    return SqliteObjectPassportStore()


def _load_session(session_id: str) -> TransformationSession:
    try:
        return SqliteRunStore().get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Transformation session not found") from exc


def _envelope(passport: ObjectPassport) -> ObjectPassportEnvelope:
    return ObjectPassportEnvelope(
        object=passport,
        public_path=f"/object/{passport.object_id}",
        api_path=f"/v1/objects/{passport.object_id}",
    )


@router.post(
    "/v1/live-transformations/{session_id}/objects/{candidate_id}",
    response_model=ObjectPassportEnvelope,
)
async def create_object_passport(session_id: str, candidate_id: str) -> ObjectPassportEnvelope:
    session = _load_session(session_id)
    future = _find_future(session, candidate_id)
    passport = object_store().create(session=session, future=future)
    return _envelope(passport)


@router.get("/v1/objects/{object_id}", response_model=ObjectPassportEnvelope)
async def read_object_passport(object_id: str) -> ObjectPassportEnvelope:
    try:
        passport = object_store().get(object_id.upper())
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc
    return _envelope(passport)


def _passport_page(passport: ObjectPassport) -> str:
    image = (
        f"<img class='hero' src='{html.escape(passport.render_image_url, quote=True)}' alt='{html.escape(passport.title, quote=True)}'/>"
        if passport.render_image_url
        else "<div class='empty'>NO APPROVED RENDER LOCKED<br><span>The Future exists; visual verification is still pending.</span></div>"
    )
    material_rows = []
    for item in passport.materials:
        role = f" / {item.role.upper()}" if item.role else ""
        note = f"<p>{html.escape(item.note)}</p>" if item.note else ""
        material_rows.append(
            f"<article><div class='k'>{html.escape(item.decision.upper())}{html.escape(role)}</div>"
            f"<h3>{html.escape(item.display_name)}</h3>{note}</article>"
        )
    owner = passport.owner_wallet or "NO OWNER LOCKED"
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/>
<title>{html.escape(passport.object_id)} / {html.escape(passport.title)} / RUINFORM</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#070707;color:#ece9e2;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}main{{max-width:1180px;margin:0 auto;padding:34px 22px 90px}}header{{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;border-bottom:1px solid #322f2a;padding-bottom:24px}}.brand{{letter-spacing:.22em;font-size:13px}}.id{{font-size:clamp(50px,11vw,140px);line-height:.82;letter-spacing:-.075em;margin:70px 0 18px}}h2{{font-size:clamp(28px,4vw,54px);letter-spacing:-.04em;margin:0 0 16px}}h3{{margin:6px 0 8px;font-size:18px}}p{{color:#aaa296;line-height:1.6;max-width:850px}}.badges{{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0 40px}}.badge{{border:1px solid #665744;padding:8px 10px;font-size:11px;letter-spacing:.12em}}.grid{{display:grid;grid-template-columns:1.15fr .85fr;gap:18px}}.panel{{border:1px solid #322f2a;background:#0d0d0c;padding:22px;margin:18px 0}}.k{{font-size:11px;letter-spacing:.18em;color:#a57d47}}.hero{{width:100%;display:block;max-height:780px;object-fit:contain;background:#050505}}.empty{{min-height:420px;display:flex;flex-direction:column;justify-content:center;align-items:center;border:1px dashed #403a32;color:#a57d47;text-align:center;line-height:1.8}}.empty span{{font-size:12px;color:#777168}}article{{border-top:1px solid #28251f;padding:17px 0}}article:first-child{{border-top:0}}.mono{{word-break:break-all;color:#777168;font-size:12px}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}header{{display:block}}}}
</style></head><body><main>
<header><div class='brand'>RUINFORM / OBJECT PASSPORT</div><div class='k'>PUBLIC RECORD / {html.escape(passport.version.upper())}</div></header>
<div class='id'>{html.escape(passport.object_id)}</div>
<h2>{html.escape(passport.title)}</h2><p>{html.escape(passport.one_line)}</p>
<div class='badges'><span class='badge'>{html.escape(passport.build_status)}</span><span class='badge'>{html.escape(passport.verification_status)}</span><span class='badge'>{html.escape(owner)}</span></div>
<div class='grid'><section>{image}</section><section>
<div class='panel'><div class='k'>AI FUTURE</div><p>{html.escape(passport.transformation_logic)}</p></div>
<div class='panel'><div class='k'>ARTIST MEANING</div><p>{html.escape(passport.artist_meaning)}</p></div>
</section></div>
<div class='panel'><div class='k'>SOURCE MATTER / {passport.source_image_count} IMAGE(S)</div>{''.join(material_rows) or '<p>No material records stored.</p>'}</div>
<div class='panel'><div class='k'>PROVENANCE</div><p class='mono'>PROJECT {html.escape(passport.project_id)}<br>SESSION {html.escape(passport.source_session_id)}<br>FUTURE {html.escape(passport.candidate_id)}<br>CREATED {html.escape(passport.created_at_iso)}</p></div>
</main></body></html>"""


@router.get("/object/{object_id}", response_class=HTMLResponse)
async def public_object_passport(object_id: str) -> str:
    try:
        passport = object_store().get(object_id.upper())
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc
    return _passport_page(passport)
