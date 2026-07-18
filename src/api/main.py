"""RecoMart FastAPI application exposing generated source datasets."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, status

from src.api.popularity_service import (
    PopularityDataError,
    PopularityService,
)
from src.api.schemas import PopularityResponse

app = FastAPI(
    title="RecoMart Source API",
    version="1.0.0",
    description="HTTP source endpoints used by the RecoMart ingestion layer.",
)


def get_popularity_service() -> PopularityService:
    """Create the popularity service using external path configuration."""
    project_root = Path(__file__).resolve().parents[2]
    configured = Path(
        os.environ.get("RECOMART_INCOMING_PATH", "data/incoming")
    )
    incoming = (
        configured
        if configured.is_absolute()
        else project_root / configured
    )
    return PopularityService(incoming)


@app.get(
    "/api/v1/popularity",
    response_model=list[PopularityResponse],
    summary="List product popularity",
    description=(
        "Returns generated product popularity joined with aggregate ratings. "
        "This endpoint is the HTTP source for raw API ingestion."
    ),
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "description": "Generated popularity data is unavailable or invalid."
        }
    },
)
def list_popularity(
    limit: int = Query(default=10000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    updated_after: datetime | None = Query(default=None),
    service: PopularityService = Depends(get_popularity_service),
) -> list[dict[str, object]]:
    """Return paginated product popularity without ingestion business logic."""
    try:
        return service.list_popularity(
            limit=limit,
            offset=offset,
            updated_after=updated_after,
        )
    except PopularityDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Generated popularity data is unavailable.",
        ) from exc
