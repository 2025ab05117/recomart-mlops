"""Retrying HTTP ingestion of external product popularity data."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

from src.ingestion.checksums import sha256_bytes
from src.ingestion.config import RequestConfig
from src.ingestion.errors import ApiIngestionError
from src.ingestion.models import ManifestFileRecord, RunContext
from src.ingestion.storage import RawStorage

LOGGER = logging.getLogger(__name__)
REQUIRED_FIELDS = {
    "product_id",
    "average_rating",
    "total_ratings",
    "popularity_score",
    "trend",
    "updated_at",
}
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
SleepFunction = Callable[[float], None]
Clock = Callable[[], float]


@dataclass(frozen=True)
class ApiFetchResult:
    """Validated API response bytes and transport metadata."""

    payload: bytes
    record_count: int
    status_code: int
    request_url: str
    retry_count: int
    sha256: str


class PopularityApiIngestionService:
    """Fetch, validate, and publish popularity data strictly through HTTP."""

    def __init__(
        self,
        *,
        api_url: str,
        request_config: RequestConfig,
        storage: RawStorage,
        context: RunContext,
        client: httpx.Client | None = None,
        sleeper: SleepFunction = time.sleep,
        clock: Clock = time.perf_counter,
    ) -> None:
        """Initialize the API client and retry dependencies."""
        self._api_url = _safe_http_url(api_url)
        self._request_config = request_config
        self._storage = storage
        self._context = context
        self._client = client
        self._sleeper = sleeper
        self._clock = clock

    def ingest(self) -> ManifestFileRecord:
        """Fetch and store one complete popularity API response."""
        started = self._clock()
        fetched = self.fetch()
        destination = self._storage.build_destination(
            source_type="api",
            dataset_type="popularity",
            ingestion_date=self._context.ingestion_date,
            ingestion_hour=self._context.ingestion_hour,
            batch_id=self._context.batch_id,
            filename="popularity.json",
        )
        result = self._storage.write_bytes(
            fetched.payload,
            destination,
            sha256=fetched.sha256,
        )
        LOGGER.info(
            "Popularity API response stored",
            extra=self._log_fields(
                "write_api_response",
                result.status.value,
                fetched.retry_count,
                started,
            ),
        )
        return ManifestFileRecord(
            source_type="api",
            dataset_type="popularity",
            source_name="popularity_api",
            destination_path=result.destination_path,
            record_count=fetched.record_count,
            size_bytes=result.size_bytes,
            sha256=fetched.sha256,
            status=result.status.value,
            http_status_code=fetched.status_code,
            request_url=fetched.request_url,
            retry_count=fetched.retry_count,
        )

    def fetch(self) -> ApiFetchResult:
        """Call the API with bounded retries and validate the response schema."""
        timeout = httpx.Timeout(
            connect=self._request_config.connect_timeout_seconds,
            read=self._request_config.read_timeout_seconds,
            write=self._request_config.read_timeout_seconds,
            pool=self._request_config.connect_timeout_seconds,
        )
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=timeout)
        try:
            for attempt in range(1, self._request_config.max_attempts + 1):
                started = self._clock()
                try:
                    response = client.get(self._api_url, timeout=timeout)
                except httpx.RequestError as exc:
                    if attempt >= self._request_config.max_attempts:
                        raise ApiIngestionError(
                            "Popularity API request failed after retries.",
                            retry_count=attempt - 1,
                        ) from exc
                    self._schedule_retry(attempt, started)
                    continue

                if response.status_code in TRANSIENT_STATUS_CODES:
                    if attempt >= self._request_config.max_attempts:
                        raise ApiIngestionError(
                            "Popularity API remained temporarily unavailable.",
                            status_code=response.status_code,
                            retry_count=attempt - 1,
                        )
                    self._schedule_retry(attempt, started)
                    continue
                if response.is_error:
                    raise ApiIngestionError(
                        f"Popularity API returned permanent HTTP "
                        f"{response.status_code}.",
                        status_code=response.status_code,
                        retry_count=attempt - 1,
                    )

                payload = response.content
                records = _validate_response(payload)
                checksum = sha256_bytes(payload)
                LOGGER.info(
                    "Popularity API response validated",
                    extra=self._log_fields(
                        "fetch_api",
                        "SUCCESS",
                        attempt - 1,
                        started,
                    ),
                )
                return ApiFetchResult(
                    payload=payload,
                    record_count=len(records),
                    status_code=response.status_code,
                    request_url=_safe_http_url(str(response.request.url)),
                    retry_count=attempt - 1,
                    sha256=checksum,
                )
        finally:
            if owns_client:
                client.close()
        raise ApiIngestionError("Popularity API fetch ended unexpectedly.")

    def _schedule_retry(self, attempt: int, started: float) -> None:
        delay = _backoff(self._request_config.backoff_seconds, attempt)
        LOGGER.warning(
            "Popularity API retry scheduled",
            extra=self._log_fields(
                "fetch_api", "RETRY", attempt, started
            ),
        )
        self._sleeper(delay)

    def _log_fields(
        self,
        operation: str,
        status: str,
        retry_attempt: int,
        started: float,
    ) -> dict[str, object]:
        return {
            "batch_id": self._context.batch_id,
            "run_id": self._context.run_id,
            "correlation_id": self._context.correlation_id,
            "source_type": "api",
            "dataset_type": "popularity",
            "operation": operation,
            "status": status,
            "retry_attempt": retry_attempt,
            "duration_ms": round((self._clock() - started) * 1000, 2),
        }


def _validate_response(payload: bytes) -> list[dict[str, Any]]:
    try:
        decoded: Any = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiIngestionError(
            "Popularity API response is not valid JSON."
        ) from exc
    if not isinstance(decoded, list):
        raise ApiIngestionError(
            "Popularity API response must be a JSON array."
        )
    for index, record in enumerate(decoded):
        if not isinstance(record, dict):
            raise ApiIngestionError(
                f"Popularity API record {index} must be an object."
            )
        missing = REQUIRED_FIELDS.difference(record)
        if missing:
            raise ApiIngestionError(
                f"Popularity API record {index} is missing required fields: "
                + ", ".join(sorted(missing))
            )
        if record["trend"] not in {"UP", "DOWN"}:
            raise ApiIngestionError(
                f"Popularity API record {index} has an invalid trend."
            )
    return decoded


def _safe_http_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ApiIngestionError("Popularity API URL must use HTTP or HTTPS.")
    if parsed.username or parsed.password:
        raise ApiIngestionError(
            "Popularity API URL must not embed credentials."
        )
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
    )


def _backoff(backoffs: tuple[float, ...], attempt: int) -> float:
    if not backoffs:
        return 0.0
    return backoffs[min(attempt - 1, len(backoffs) - 1)]
