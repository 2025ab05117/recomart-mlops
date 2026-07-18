"""Dataset-specific and cross-dataset Pandas validation coordinators."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from src.validation.config import ValidationConfig
from src.validation.errors import DatasetReadError
from src.validation.models import DatasetValidationResult, RawDatasetAsset, Severity
from src.validation.profiler import calculate_quality_score, profile_dataset
from src.validation.rules import (
    RuleAccumulator,
    blank_mask,
    integer_invalid_mask,
    numeric_values,
    parse_timestamps,
    uuid_invalid_mask,
)
from src.validation.schema import SCHEMAS, DatasetSchema


def read_raw_dataset(asset: RawDatasetAsset) -> pd.DataFrame:
    """Read one manifest-verified CSV or JSON array into a RangeIndex frame."""
    try:
        if asset.file_type == "csv":
            frame = pd.read_csv(asset.local_path)
        elif asset.file_type == "json":
            with asset.local_path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if not isinstance(payload, list) or not all(
                isinstance(record, dict) for record in payload
            ):
                raise DatasetReadError(
                    f"{asset.dataset_type} JSON must be an object array."
                )
            frame = pd.DataFrame(payload)
        else:
            raise DatasetReadError(
                f"Unsupported raw format for {asset.dataset_type}: "
                f"{asset.file_type}"
            )
    except DatasetReadError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        raise DatasetReadError(
            f"Unable to read raw {asset.dataset_type} dataset."
        ) from exc
    return frame.reset_index(drop=True)


class DatasetValidator:
    """Apply reusable schema, record, relationship, and consistency rules."""

    def __init__(self, config: ValidationConfig) -> None:
        """Initialize with externally validated rule settings."""
        self._config = config

    def validate(
        self,
        *,
        dataset_type: str,
        frame: pd.DataFrame,
        asset: RawDatasetAsset,
        reference_frames: dict[str, pd.DataFrame],
        batch_id: str,
        validation_run_id: str,
        validation_time: datetime,
    ) -> DatasetValidationResult:
        """Validate one dataset independently using injected reference frames."""
        schema = SCHEMAS[dataset_type]
        accumulator = RuleAccumulator(
            dataset_type=dataset_type,
            frame=frame,
            sample_count=self._config.sample_error_count,
        )
        missing_columns = self._common_rules(
            accumulator=accumulator,
            frame=frame,
            schema=schema,
        )
        if dataset_type == "users":
            self._users_rules(accumulator, frame, missing_columns, validation_time)
        elif dataset_type == "products":
            self._products_rules(
                accumulator, frame, missing_columns, validation_time
            )
        elif dataset_type == "clickstream":
            self._clickstream_rules(
                accumulator,
                frame,
                missing_columns,
                validation_time,
                reference_frames,
            )
        elif dataset_type == "purchasehistory":
            self._purchase_rules(
                accumulator,
                frame,
                missing_columns,
                validation_time,
                reference_frames,
            )
        elif dataset_type == "popularity":
            self._popularity_rules(
                accumulator,
                frame,
                missing_columns,
                validation_time,
                reference_frames,
            )
        else:
            raise DatasetReadError(f"Unsupported dataset: {dataset_type}")

        quarantined_at = _format_utc(validation_time)
        valid, invalid = accumulator.split(
            validation_run_id=validation_run_id,
            batch_id=batch_id,
            quarantined_at=quarantined_at,
        )
        quality, components = calculate_quality_score(
            frame=frame,
            schema=schema,
            rules=accumulator.rules,
            weights=self._config.quality_weights,
        )
        profile = profile_dataset(
            frame=frame,
            dataset_type=dataset_type,
            source_path=asset.source_path,
            batch_id=batch_id,
            file_type=asset.file_type,
            file_size=asset.size_bytes,
            checksum=asset.sha256,
            schema=schema,
            reference_time=pd.Timestamp(validation_time),
            future_tolerance_minutes=(
                self._config.future_timestamp_tolerance_minutes
            ),
            valid_count=len(valid),
            invalid_count=len(invalid),
            quality_score=quality,
        )
        critical = bool(missing_columns) or frame.empty
        return DatasetValidationResult(
            dataset_type=dataset_type,
            source_path=asset.source_path,
            source_sha256=asset.sha256,
            file_type=asset.file_type,
            frame=frame,
            valid_frame=valid,
            invalid_frame=invalid,
            rules=accumulator.rules,
            profile=profile,
            quality_score=quality,
            component_scores=components,
            critical_schema_failure=critical,
        )

    def _common_rules(
        self,
        *,
        accumulator: RuleAccumulator,
        frame: pd.DataFrame,
        schema: DatasetSchema,
    ) -> set[str]:
        missing = set(schema.columns).difference(frame.columns)
        unexpected = set(frame.columns).difference(schema.columns)
        accumulator.add_dataset_rule(
            rule_id=f"{schema.dataset_type.upper()}_SCHEMA_REQUIRED_COLUMNS",
            rule_name="Required columns present",
            category="Schema",
            severity=Severity.ERROR,
            message=(
                "All configured required columns must be present."
                if not missing
                else "Missing columns: " + ", ".join(sorted(missing))
            ),
            failure_count=len(missing),
            records_checked=len(schema.columns),
            quarantine_all=True,
            samples=sorted(missing),
        )
        accumulator.add_dataset_rule(
            rule_id=f"{schema.dataset_type.upper()}_SCHEMA_UNEXPECTED_COLUMNS",
            rule_name="Unexpected columns reported",
            category="Schema",
            severity=Severity.WARNING,
            message=(
                "No unexpected columns found."
                if not unexpected
                else "Unexpected columns: " + ", ".join(sorted(unexpected))
            ),
            failure_count=len(unexpected),
            records_checked=len(frame.columns),
            samples=sorted(unexpected),
        )
        accumulator.add_dataset_rule(
            rule_id=f"{schema.dataset_type.upper()}_NON_EMPTY",
            rule_name="Dataset is not empty",
            category="Schema",
            severity=Severity.ERROR,
            message="Dataset must contain at least one record.",
            failure_count=int(frame.empty),
            records_checked=max(1, len(frame)),
            quarantine_all=False,
        )
        if not frame.empty:
            accumulator.add(
                rule_id=f"{schema.dataset_type.upper()}_DUPLICATE_ROWS",
                rule_name="Entire duplicate records",
                category="Uniqueness",
                severity=Severity.ERROR,
                message="Entire duplicate records are not allowed.",
                failed_mask=frame.duplicated(keep=False),
                sample_series=(
                    frame.astype("string")
                    .fillna("<NULL>")
                    .agg("|".join, axis=1)
                ),
            )
        for column in schema.required_value_columns:
            if column not in frame.columns:
                accumulator.skip(
                    rule_id=(
                        f"{schema.dataset_type.upper()}_{column.upper()}_REQUIRED"
                    ),
                    rule_name="Required value present",
                    category="Completeness",
                    column_name=column,
                    message=f"Skipped because {column} is missing.",
                )
                continue
            accumulator.add(
                rule_id=(
                    f"{schema.dataset_type.upper()}_{column.upper()}_REQUIRED"
                ),
                rule_name="Required value present",
                category="Completeness",
                severity=Severity.ERROR,
                column_name=column,
                message=f"{column} must not be null or blank.",
                failed_mask=blank_mask(frame[column]),
                sample_series=frame[column],
            )
        if schema.business_key in frame.columns:
            accumulator.add(
                rule_id=(
                    f"{schema.dataset_type.upper()}_"
                    f"{schema.business_key.upper()}_UNIQUE"
                ),
                rule_name="Business key is unique",
                category="Uniqueness",
                severity=Severity.ERROR,
                column_name=schema.business_key,
                message=f"Duplicate {schema.business_key} values are invalid.",
                failed_mask=frame[schema.business_key].duplicated(keep=False),
                sample_series=frame[schema.business_key],
            )
        else:
            accumulator.skip(
                rule_id=(
                    f"{schema.dataset_type.upper()}_"
                    f"{schema.business_key.upper()}_UNIQUE"
                ),
                rule_name="Business key is unique",
                category="Uniqueness",
                column_name=schema.business_key,
                message="Skipped because the business key column is missing.",
            )
        return missing

    def _users_rules(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        now: datetime,
    ) -> None:
        self._positive_integer(acc, frame, missing, "user_id", "USERS")
        self._numeric_range(
            acc,
            frame,
            missing,
            "age",
            self._config.users_age.minimum,
            self._config.users_age.maximum,
            "USERS_AGE_RANGE",
        )
        self._allowed(
            acc,
            frame,
            missing,
            "gender",
            self._config.allowed_genders,
            "USERS_GENDER_ALLOWED",
        )
        self._allowed(
            acc,
            frame,
            missing,
            "customer_segment",
            self._config.allowed_segments,
            "USERS_SEGMENT_ALLOWED",
        )
        self._timestamp(
            acc,
            frame,
            missing,
            "registration_date",
            now,
            "USERS_REGISTRATION_DATE",
        )

    def _products_rules(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        now: datetime,
    ) -> None:
        self._positive_integer(acc, frame, missing, "product_id", "PRODUCTS")
        for column in ("product_name", "category", "brand"):
            if column in missing:
                continue
            acc.add(
                rule_id=f"PRODUCTS_{column.upper()}_NOT_BLANK",
                rule_name="Product text is present",
                category="Completeness",
                severity=Severity.ERROR,
                column_name=column,
                message=f"{column} must not be blank.",
                failed_mask=blank_mask(frame[column]),
                sample_series=frame[column],
            )
        self._numeric_range(
            acc,
            frame,
            missing,
            "price",
            self._config.minimum_product_price,
            float("inf"),
            "PRODUCTS_PRICE_POSITIVE",
        )
        self._rating_with_unrated(
            acc,
            frame,
            missing,
            rating_column="average_rating",
            count_column="total_ratings",
            minimum=self._config.product_rating.minimum,
            maximum=self._config.product_rating.maximum,
            unrated=self._config.product_rating.unrated_value,
            rule_id="PRODUCTS_AVERAGE_RATING_RANGE",
        )
        self._nonnegative_integer(
            acc,
            frame,
            missing,
            "total_ratings",
            "PRODUCTS_TOTAL_RATINGS_NONNEGATIVE",
        )
        if "release_date" not in missing:
            blank = blank_mask(frame["release_date"])
            parsed = parse_timestamps(frame["release_date"])
            acc.add(
                rule_id="PRODUCTS_RELEASE_DATE_FORMAT",
                rule_name="Optional release date is valid",
                category="Format",
                severity=Severity.ERROR,
                column_name="release_date",
                message="Nonblank release_date values must be valid dates.",
                failed_mask=~blank & parsed.isna(),
                sample_series=frame["release_date"],
            )
            cutoff = pd.Timestamp(now) + pd.Timedelta(
                self._config.future_timestamp_tolerance_minutes, unit="min"
            )
            acc.add(
                rule_id="PRODUCTS_RELEASE_DATE_NOT_FUTURE",
                rule_name="Release date is not in the future",
                category="Range",
                severity=Severity.ERROR,
                column_name="release_date",
                message="release_date cannot be in the future.",
                failed_mask=parsed > cutoff,
                sample_series=frame["release_date"],
            )

    def _clickstream_rules(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        now: datetime,
        references: dict[str, pd.DataFrame],
    ) -> None:
        self._uuid(acc, frame, missing, "event_id", "CLICKSTREAM_EVENT_UUID")
        self._uuid(
            acc, frame, missing, "session_id", "CLICKSTREAM_SESSION_UUID"
        )
        self._positive_integer(
            acc, frame, missing, "user_id", "CLICKSTREAM"
        )
        self._positive_integer(
            acc, frame, missing, "product_id", "CLICKSTREAM"
        )
        self._allowed(
            acc,
            frame,
            missing,
            "event_type",
            self._config.allowed_event_types,
            "CLICKSTREAM_EVENT_TYPE_ALLOWED",
        )
        self._timestamp(
            acc,
            frame,
            missing,
            "timestamp",
            now,
            "CLICKSTREAM_TIMESTAMP",
        )
        self._foreign_key(
            acc,
            frame,
            missing,
            references,
            column="user_id",
            reference_dataset="users",
            reference_column="user_id",
            rule_id="CLICKSTREAM_USER_REFERENCE",
        )
        self._foreign_key(
            acc,
            frame,
            missing,
            references,
            column="product_id",
            reference_dataset="products",
            reference_column="product_id",
            rule_id="CLICKSTREAM_PRODUCT_REFERENCE",
        )
        required = {"session_id", "timestamp"}
        if required.intersection(missing):
            acc.skip(
                rule_id="CLICKSTREAM_SESSION_CHRONOLOGY",
                rule_name="Session events are chronological",
                category="Consistency",
                severity=Severity.WARNING,
                message="Skipped because session or timestamp is missing.",
            )
        else:
            parsed = parse_timestamps(frame["timestamp"])
            backwards = parsed.groupby(frame["session_id"]).diff() < pd.Timedelta(0, unit="ns")
            acc.add(
                rule_id="CLICKSTREAM_SESSION_CHRONOLOGY",
                rule_name="Session events are chronological",
                category="Consistency",
                severity=Severity.WARNING,
                column_name="timestamp",
                message="Events should remain chronological within a session.",
                failed_mask=backwards,
                sample_series=frame["timestamp"],
            )
        sequence_columns = {"session_id", "product_id", "event_type"}
        if sequence_columns.intersection(missing):
            acc.skip(
                rule_id="CLICKSTREAM_SESSION_SEQUENCE",
                rule_name="Session interaction sequence",
                category="Business Rules",
                severity=Severity.WARNING,
                message="Skipped because sequence columns are missing.",
            )
        else:
            first_types = frame.groupby(
                ["session_id", "product_id"], sort=False
            )["event_type"].transform("first")
            malformed = first_types.ne("View")
            acc.add(
                rule_id="CLICKSTREAM_SESSION_SEQUENCE",
                rule_name="Session interaction starts with View",
                category="Business Rules",
                severity=Severity.WARNING,
                column_name="event_type",
                message="A product interaction should begin with View.",
                failed_mask=malformed,
                sample_series=frame["event_type"],
            )

    def _purchase_rules(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        now: datetime,
        references: dict[str, pd.DataFrame],
    ) -> None:
        self._uuid(
            acc, frame, missing, "order_id", "PURCHASE_ORDER_UUID"
        )
        self._positive_integer(acc, frame, missing, "user_id", "PURCHASE")
        self._positive_integer(
            acc, frame, missing, "product_id", "PURCHASE"
        )
        self._numeric_range(
            acc,
            frame,
            missing,
            "quantity",
            self._config.purchase_quantity.minimum,
            self._config.purchase_quantity.maximum,
            "PURCHASE_QUANTITY_RANGE",
            require_integer=True,
        )
        self._numeric_range(
            acc,
            frame,
            missing,
            "amount",
            0.0000001,
            float("inf"),
            "PURCHASE_AMOUNT_POSITIVE",
        )
        self._numeric_range(
            acc,
            frame,
            missing,
            "rating",
            self._config.purchase_rating.minimum,
            self._config.purchase_rating.maximum,
            "PURCHASE_RATING_RANGE",
        )
        minimum_rating = self._config.purchase_rating.purchase_minimum_rating
        if "rating" not in missing and minimum_rating is not None:
            rating = numeric_values(frame["rating"])
            acc.add(
                rule_id="PURCHASE_MINIMUM_RATING",
                rule_name="Purchase rating follows generator contract",
                category="Business Rules",
                severity=Severity.ERROR,
                column_name="rating",
                message=(
                    f"Purchases require rating >= {minimum_rating:g}."
                ),
                failed_mask=rating.notna() & (rating < minimum_rating),
                sample_series=frame["rating"],
            )
        self._timestamp(
            acc,
            frame,
            missing,
            "purchase_timestamp",
            now,
            "PURCHASE_TIMESTAMP",
        )
        self._foreign_key(
            acc,
            frame,
            missing,
            references,
            column="user_id",
            reference_dataset="users",
            reference_column="user_id",
            rule_id="PURCHASE_USER_REFERENCE",
        )
        self._foreign_key(
            acc,
            frame,
            missing,
            references,
            column="product_id",
            reference_dataset="products",
            reference_column="product_id",
            rule_id="PURCHASE_PRODUCT_REFERENCE",
        )
        amount_columns = {"product_id", "quantity", "amount"}
        products = references.get("products")
        if amount_columns.intersection(missing) or products is None or not {
            "product_id",
            "price",
        }.issubset(products.columns):
            acc.skip(
                rule_id="PURCHASE_AMOUNT_CONSISTENCY",
                rule_name="Amount equals quantity times product price",
                category="Consistency",
                message="Skipped because price consistency inputs are missing.",
            )
        else:
            prices = products.set_index("product_id")["price"]
            expected = numeric_values(frame["quantity"]) * numeric_values(
                frame["product_id"].map(prices)
            )
            actual = numeric_values(frame["amount"])
            mismatch = expected.notna() & actual.notna() & (
                (actual - expected).abs() > self._config.amount_tolerance
            )
            acc.add(
                rule_id="PURCHASE_AMOUNT_CONSISTENCY",
                rule_name="Amount equals quantity times product price",
                category="Consistency",
                severity=Severity.ERROR,
                column_name="amount",
                message=(
                    "amount must match quantity Ã— product price within "
                    f"{self._config.amount_tolerance:g}."
                ),
                failed_mask=mismatch,
                sample_series=frame["amount"],
            )
        self._purchase_click_consistency(
            acc, frame, missing, references
        )

    def _popularity_rules(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        now: datetime,
        references: dict[str, pd.DataFrame],
    ) -> None:
        self._positive_integer(
            acc, frame, missing, "product_id", "POPULARITY"
        )
        self._rating_with_unrated(
            acc,
            frame,
            missing,
            rating_column="average_rating",
            count_column="total_ratings",
            minimum=self._config.popularity_rating.minimum,
            maximum=self._config.popularity_rating.maximum,
            unrated=self._config.popularity_rating.unrated_value,
            rule_id="POPULARITY_AVERAGE_RATING_RANGE",
        )
        self._nonnegative_integer(
            acc,
            frame,
            missing,
            "total_ratings",
            "POPULARITY_TOTAL_RATINGS_NONNEGATIVE",
        )
        self._numeric_range(
            acc,
            frame,
            missing,
            "popularity_score",
            self._config.popularity_score.minimum,
            self._config.popularity_score.maximum,
            "POPULARITY_SCORE_RANGE",
        )
        self._allowed(
            acc,
            frame,
            missing,
            "trend",
            self._config.allowed_trends,
            "POPULARITY_TREND_ALLOWED",
        )
        self._timestamp(
            acc,
            frame,
            missing,
            "updated_at",
            now,
            "POPULARITY_UPDATED_AT",
        )
        if "updated_at" not in missing:
            parsed = parse_timestamps(frame["updated_at"])
            stale_cutoff = pd.Timestamp(now) - pd.Timedelta(
                self._config.popularity_max_age_hours, unit="h"
            )
            acc.add(
                rule_id="POPULARITY_FRESHNESS",
                rule_name="Popularity timestamp is reasonably fresh",
                category="Range",
                severity=Severity.WARNING,
                column_name="updated_at",
                message=(
                    "updated_at should be within the configured freshness window."
                ),
                failed_mask=parsed.notna() & (parsed < stale_cutoff),
                sample_series=frame["updated_at"],
            )
        self._foreign_key(
            acc,
            frame,
            missing,
            references,
            column="product_id",
            reference_dataset="products",
            reference_column="product_id",
            rule_id="POPULARITY_PRODUCT_REFERENCE",
        )
        products = references.get("products")
        required = {"product_id", "average_rating", "total_ratings"}
        if required.intersection(missing) or products is None or not required.issubset(
            products.columns
        ):
            acc.skip(
                rule_id="POPULARITY_PRODUCT_STATISTICS",
                rule_name="Popularity statistics match products",
                category="Consistency",
                message="Skipped because product statistics are unavailable.",
            )
        else:
            product_stats = products.set_index("product_id")[
                ["average_rating", "total_ratings"]
            ]
            joined = frame[["product_id"]].join(
                product_stats,
                on="product_id",
                rsuffix="_product",
            )
            rating_difference = (
                numeric_values(frame["average_rating"])
                - numeric_values(joined["average_rating"])
            ).abs()
            count_difference = (
                numeric_values(frame["total_ratings"])
                - numeric_values(joined["total_ratings"])
            ).abs()
            mismatch = (
                (
                    rating_difference
                    > self._config.popularity_rating_tolerance
                )
                | (
                    count_difference
                    > self._config.total_ratings_tolerance
                )
            ) & joined["average_rating"].notna()
            acc.add(
                rule_id="POPULARITY_PRODUCT_STATISTICS",
                rule_name="Popularity statistics match products",
                category="Consistency",
                severity=Severity.ERROR,
                column_name="average_rating,total_ratings",
                message=(
                    "Popularity rating/count must match product aggregates "
                    "within configured tolerances."
                ),
                failed_mask=mismatch,
                sample_series=frame["product_id"],
            )

    def _positive_integer(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        column: str,
        prefix: str,
    ) -> None:
        if column in missing:
            acc.skip(
                rule_id=f"{prefix}_{column.upper()}_POSITIVE_INTEGER",
                rule_name="Identifier is a positive integer",
                category="Format",
                column_name=column,
                message=f"Skipped because {column} is missing.",
            )
            return
        numeric = numeric_values(frame[column])
        acc.add(
            rule_id=f"{prefix}_{column.upper()}_POSITIVE_INTEGER",
            rule_name="Identifier is a positive integer",
            category="Format",
            severity=Severity.ERROR,
            column_name=column,
            message=f"{column} must be a positive integer.",
            failed_mask=integer_invalid_mask(frame[column])
            | numeric.le(0).fillna(False),
            sample_series=frame[column],
        )

    def _nonnegative_integer(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        column: str,
        rule_id: str,
    ) -> None:
        if column in missing:
            acc.skip(
                rule_id=rule_id,
                rule_name="Value is a nonnegative integer",
                category="Format",
                column_name=column,
                message=f"Skipped because {column} is missing.",
            )
            return
        numeric = numeric_values(frame[column])
        acc.add(
            rule_id=rule_id,
            rule_name="Value is a nonnegative integer",
            category="Range",
            severity=Severity.ERROR,
            column_name=column,
            message=f"{column} must be an integer >= 0.",
            failed_mask=integer_invalid_mask(frame[column])
            | numeric.lt(0).fillna(False),
            sample_series=frame[column],
        )

    def _numeric_range(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        column: str,
        minimum: float,
        maximum: float,
        rule_id: str,
        *,
        require_integer: bool = False,
    ) -> None:
        if column in missing:
            acc.skip(
                rule_id=rule_id,
                rule_name="Numeric range",
                category="Range",
                column_name=column,
                message=f"Skipped because {column} is missing.",
            )
            return
        numeric = numeric_values(frame[column])
        invalid = numeric.isna() | numeric.lt(minimum) | numeric.gt(maximum)
        if require_integer:
            invalid |= numeric.mod(1).ne(0)
        acc.add(
            rule_id=rule_id,
            rule_name="Numeric value is within configured range",
            category="Range",
            severity=Severity.ERROR,
            column_name=column,
            message=f"{column} must be between {minimum:g} and {maximum:g}.",
            failed_mask=invalid,
            sample_series=frame[column],
        )

    def _rating_with_unrated(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        *,
        rating_column: str,
        count_column: str,
        minimum: float,
        maximum: float,
        unrated: float | None,
        rule_id: str,
    ) -> None:
        if rating_column in missing or count_column in missing:
            acc.skip(
                rule_id=rule_id,
                rule_name="Average rating scale",
                category="Range",
                column_name=rating_column,
                message="Skipped because rating inputs are missing.",
            )
            return
        rating = numeric_values(frame[rating_column])
        count = numeric_values(frame[count_column])
        rated_invalid = count.gt(0) & (
            rating.isna() | rating.lt(minimum) | rating.gt(maximum)
        )
        if unrated is None:
            unrated_invalid = count.eq(0) & rating.notna()
        else:
            unrated_invalid = count.eq(0) & rating.ne(unrated)
        invalid = count.isna() | rated_invalid | unrated_invalid
        acc.add(
            rule_id=rule_id,
            rule_name="Average rating follows the 1â€“5 scale",
            category="Range",
            severity=Severity.ERROR,
            column_name=rating_column,
            message=(
                f"Rated records require {minimum:g}â€“{maximum:g}; "
                f"unrated records use {unrated}."
            ),
            failed_mask=invalid,
            sample_series=frame[rating_column],
        )

    def _allowed(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        column: str,
        allowed: tuple[str, ...],
        rule_id: str,
    ) -> None:
        if column in missing:
            acc.skip(
                rule_id=rule_id,
                rule_name="Allowed categorical values",
                category="Format",
                column_name=column,
                message=f"Skipped because {column} is missing.",
            )
            return
        acc.add(
            rule_id=rule_id,
            rule_name="Categorical value is allowed",
            category="Format",
            severity=Severity.ERROR,
            column_name=column,
            message=f"{column} must be one of: {', '.join(allowed)}.",
            failed_mask=~frame[column].isin(allowed),
            sample_series=frame[column],
        )

    def _uuid(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        column: str,
        rule_id: str,
    ) -> None:
        if column in missing:
            acc.skip(
                rule_id=rule_id,
                rule_name="UUID format",
                category="Format",
                column_name=column,
                message=f"Skipped because {column} is missing.",
            )
            return
        acc.add(
            rule_id=rule_id,
            rule_name="Identifier has UUID format",
            category="Format",
            severity=Severity.ERROR,
            column_name=column,
            message=f"{column} must use canonical UUID format.",
            failed_mask=uuid_invalid_mask(frame[column]),
            sample_series=frame[column],
        )

    def _timestamp(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        column: str,
        now: datetime,
        prefix: str,
    ) -> None:
        if column in missing:
            for suffix in ("FORMAT", "NOT_FUTURE"):
                acc.skip(
                    rule_id=f"{prefix}_{suffix}",
                    rule_name="Timestamp validation",
                    category="Format" if suffix == "FORMAT" else "Range",
                    column_name=column,
                    message=f"Skipped because {column} is missing.",
                )
            return
        parsed = parse_timestamps(frame[column])
        nonblank = ~blank_mask(frame[column])
        acc.add(
            rule_id=f"{prefix}_FORMAT",
            rule_name="Timestamp is valid",
            category="Format",
            severity=Severity.ERROR,
            column_name=column,
            message=f"{column} must use a supported date/time format.",
            failed_mask=nonblank & parsed.isna(),
            sample_series=frame[column],
        )
        cutoff = pd.Timestamp(now) + pd.Timedelta(
                self._config.future_timestamp_tolerance_minutes, unit="min"
            )
        acc.add(
            rule_id=f"{prefix}_NOT_FUTURE",
            rule_name="Timestamp is not beyond future tolerance",
            category="Range",
            severity=Severity.ERROR,
            column_name=column,
            message=(
                f"{column} must not exceed validation time by more than "
                f"{self._config.future_timestamp_tolerance_minutes} minutes."
            ),
            failed_mask=parsed > cutoff,
            sample_series=frame[column],
        )

    def _foreign_key(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        references: dict[str, pd.DataFrame],
        *,
        column: str,
        reference_dataset: str,
        reference_column: str,
        rule_id: str,
    ) -> None:
        reference = references.get(reference_dataset)
        if (
            column in missing
            or reference is None
            or reference_column not in reference.columns
        ):
            acc.skip(
                rule_id=rule_id,
                rule_name="Referential integrity",
                category="Referential Integrity",
                column_name=column,
                message="Skipped because reference data is unavailable.",
            )
            return
        valid_values = set(reference[reference_column].dropna())
        acc.add(
            rule_id=rule_id,
            rule_name="Foreign key exists in parent dataset",
            category="Referential Integrity",
            severity=Severity.ERROR,
            column_name=column,
            message=(
                f"{column} must exist in "
                f"{reference_dataset}.{reference_column}."
            ),
            failed_mask=~frame[column].isin(valid_values),
            sample_series=frame[column],
        )

    def _purchase_click_consistency(
        self,
        acc: RuleAccumulator,
        frame: pd.DataFrame,
        missing: set[str],
        references: dict[str, pd.DataFrame],
    ) -> None:
        needed = {"user_id", "product_id", "purchase_timestamp"}
        clicks = references.get("clickstream")
        click_needed = {"user_id", "product_id", "timestamp"}
        if (
            needed.intersection(missing)
            or clicks is None
            or not click_needed.issubset(clicks.columns)
        ):
            acc.skip(
                rule_id="PURCHASE_CLICK_CHRONOLOGY",
                rule_name="Purchase follows related interaction",
                category="Consistency",
                message="Skipped because interaction correlation inputs are missing.",
            )
            return
        click_copy = clicks[list(click_needed)].copy()
        click_copy["_parsed_click"] = parse_timestamps(click_copy["timestamp"])
        latest_click = click_copy.groupby(
            ["user_id", "product_id"], dropna=False
        )["_parsed_click"].max()
        keys = pd.MultiIndex.from_frame(frame[["user_id", "product_id"]])
        matched = pd.Series(
            latest_click.reindex(keys).to_numpy(), index=frame.index
        )
        purchases = parse_timestamps(frame["purchase_timestamp"])
        earlier = matched.notna() & purchases.notna() & (purchases < matched)
        acc.add(
            rule_id="PURCHASE_CLICK_CHRONOLOGY",
            rule_name="Purchase follows related interaction",
            category="Consistency",
            severity=Severity.ERROR,
            column_name="purchase_timestamp",
            message=(
                "Purchase must not precede the latest matching user-product "
                "interaction. Exact event-to-order IDs are unavailable."
            ),
            failed_mask=earlier,
            sample_series=frame["purchase_timestamp"],
        )
        acc.add(
            rule_id="PURCHASE_CLICK_CORRELATION_AVAILABLE",
            rule_name="Related user-product interaction exists",
            category="Consistency",
            severity=Severity.WARNING,
            column_name="product_id",
            message=(
                "No exact event-to-order key exists; user-product matching "
                "is the strongest available correlation."
            ),
            failed_mask=matched.isna(),
            sample_series=frame["product_id"],
        )


def _format_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )




