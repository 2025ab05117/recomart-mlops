"""FastAPI response contracts for RecoMart data-source endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PopularityResponse(BaseModel):
    """One product popularity record returned to ingestion clients."""

    product_id: int = Field(description="Stable MovieLens-derived product ID.")
    average_rating: float = Field(ge=0, le=5)
    total_ratings: int = Field(ge=0)
    popularity_score: float = Field(ge=0, le=100)
    trend: Literal["UP", "DOWN"]
    updated_at: datetime
