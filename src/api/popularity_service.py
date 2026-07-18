"""Product popularity query service backed by generated incoming artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PopularityDataError(Exception):
    """Raised when generated popularity inputs cannot satisfy the API contract."""


class PopularityService:
    """Read and join generated product and popularity information."""

    def __init__(self, incoming_directory: Path) -> None:
        """Initialize the service with the authoritative incoming directory."""
        self._incoming_directory = incoming_directory.resolve()

    def list_popularity(
        self,
        *,
        limit: int,
        offset: int,
        updated_after: datetime | None,
    ) -> list[dict[str, Any]]:
        """Return a validated, paginated popularity response."""
        products = self._read_array("products.json")
        popularity = self._read_array("popularity.json")
        product_metrics = {
            int(product["product_id"]): (
                float(product["average_rating"]),
                int(product["total_ratings"]),
            )
            for product in products
        }
        records: list[dict[str, Any]] = []
        cutoff = (
            updated_after.astimezone(timezone.utc)
            if updated_after is not None and updated_after.tzinfo is not None
            else updated_after
        )
        for record in popularity:
            product_id = int(record["product_id"])
            if product_id not in product_metrics:
                raise PopularityDataError(
                    f"Popularity references unknown product ID {product_id}."
                )
            updated_at = _parse_timestamp(record["updated_at"])
            if cutoff is not None:
                normalized_cutoff = (
                    cutoff.replace(tzinfo=timezone.utc)
                    if cutoff.tzinfo is None
                    else cutoff
                )
                if updated_at <= normalized_cutoff:
                    continue
            average_rating, total_ratings = product_metrics[product_id]
            records.append(
                {
                    "product_id": product_id,
                    "average_rating": average_rating,
                    "total_ratings": total_ratings,
                    "popularity_score": float(record["popularity_score"]),
                    "trend": str(record["trend"]),
                    "updated_at": record["updated_at"],
                }
            )
        records.sort(key=lambda item: item["product_id"])
        return records[offset : offset + limit]

    def _read_array(self, filename: str) -> list[dict[str, Any]]:
        path = self._incoming_directory / filename
        try:
            with path.open("r", encoding="utf-8") as stream:
                payload: Any = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PopularityDataError(
                f"Unable to load generated {filename}."
            ) from exc
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise PopularityDataError(
                f"Generated {filename} must contain a JSON object array."
            )
        return payload


def _parse_timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise PopularityDataError(
            "Popularity updated_at must be ISO 8601."
        ) from exc
    if parsed.tzinfo is None:
        raise PopularityDataError(
            "Popularity updated_at must include a UTC offset."
        )
    return parsed.astimezone(timezone.utc)
