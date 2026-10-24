"""Endpoint único de registro manual."""

from fastapi import APIRouter, HTTPException, Request

from app.records.models import RecordCreateRequest, StoredRecord

router = APIRouter(prefix="/api/v1", tags=["Records"])


@router.post(
    "/records",
    response_model=StoredRecord,
    status_code=201,
    summary="Registrar un partido con tu pick",
)
async def create_record(
    payload: RecordCreateRequest,
    request: Request,
) -> StoredRecord:
    try:
        return await request.app.state.record_service.register(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
