"""Focused integration tests for the popularity source endpoint."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.main import app, get_popularity_service
from src.api.popularity_service import PopularityService


def test_popularity_endpoint_returns_rating_enriched_records(
    tmp_path: Path,
) -> None:
    """The HTTP source joins generated rating aggregates and popularity."""
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "products.json").write_text(
        json.dumps(
            [
                {
                    "product_id": 101,
                    "average_rating": 4.35,
                    "total_ratings": 186,
                },
                {
                    "product_id": 102,
                    "average_rating": 3.8,
                    "total_ratings": 80,
                },
            ]
        ),
        encoding="utf-8",
    )
    (incoming / "popularity.json").write_text(
        json.dumps(
            [
                {
                    "product_id": 101,
                    "popularity_score": 91.42,
                    "trend": "UP",
                    "updated_at": "2026-07-19T00:30:00Z",
                },
                {
                    "product_id": 102,
                    "popularity_score": 70.0,
                    "trend": "DOWN",
                    "updated_at": "2026-07-19T00:30:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )
    app.dependency_overrides[get_popularity_service] = lambda: PopularityService(
        incoming
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/popularity",
                params={"limit": 1, "offset": 0},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "product_id": 101,
            "average_rating": 4.35,
            "total_ratings": 186,
            "popularity_score": 91.42,
            "trend": "UP",
            "updated_at": "2026-07-19T00:30:00Z",
        }
    ]
