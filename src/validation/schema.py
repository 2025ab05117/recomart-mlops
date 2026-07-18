"""Actual generated dataset schema contracts used by validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSchema:
    """Logical schema, business key, and semantic column groups."""

    dataset_type: str
    columns: tuple[str, ...]
    expected_types: dict[str, str]
    business_key: str
    required_value_columns: tuple[str, ...]
    numeric_columns: tuple[str, ...]
    timestamp_columns: tuple[str, ...]
    optional_value_columns: tuple[str, ...] = ()


SCHEMAS: dict[str, DatasetSchema] = {
    "users": DatasetSchema(
        dataset_type="users",
        columns=(
            "user_id",
            "age",
            "gender",
            "occupation",
            "zipcode",
            "registration_date",
            "customer_segment",
        ),
        expected_types={
            "user_id": "integer",
            "age": "integer",
            "gender": "string",
            "occupation": "string",
            "zipcode": "string",
            "registration_date": "date",
            "customer_segment": "string",
        },
        business_key="user_id",
        required_value_columns=(
            "user_id",
            "age",
            "gender",
            "occupation",
            "zipcode",
            "registration_date",
            "customer_segment",
        ),
        numeric_columns=("user_id", "age"),
        timestamp_columns=("registration_date",),
    ),
    "products": DatasetSchema(
        dataset_type="products",
        columns=(
            "product_id",
            "product_name",
            "category",
            "release_date",
            "price",
            "brand",
            "average_rating",
            "total_ratings",
        ),
        expected_types={
            "product_id": "integer",
            "product_name": "string",
            "category": "string",
            "release_date": "date",
            "price": "number",
            "brand": "string",
            "average_rating": "number",
            "total_ratings": "integer",
        },
        business_key="product_id",
        required_value_columns=(
            "product_id",
            "product_name",
            "category",
            "price",
            "brand",
            "average_rating",
            "total_ratings",
        ),
        optional_value_columns=("release_date",),
        numeric_columns=(
            "product_id",
            "price",
            "average_rating",
            "total_ratings",
        ),
        timestamp_columns=("release_date",),
    ),
    "clickstream": DatasetSchema(
        dataset_type="clickstream",
        columns=(
            "event_id",
            "user_id",
            "product_id",
            "event_type",
            "timestamp",
            "session_id",
        ),
        expected_types={
            "event_id": "uuid",
            "user_id": "integer",
            "product_id": "integer",
            "event_type": "string",
            "timestamp": "timestamp",
            "session_id": "uuid",
        },
        business_key="event_id",
        required_value_columns=(
            "event_id",
            "user_id",
            "product_id",
            "event_type",
            "timestamp",
            "session_id",
        ),
        numeric_columns=("user_id", "product_id"),
        timestamp_columns=("timestamp",),
    ),
    "purchasehistory": DatasetSchema(
        dataset_type="purchasehistory",
        columns=(
            "order_id",
            "user_id",
            "product_id",
            "quantity",
            "amount",
            "rating",
            "purchase_timestamp",
        ),
        expected_types={
            "order_id": "uuid",
            "user_id": "integer",
            "product_id": "integer",
            "quantity": "integer",
            "amount": "number",
            "rating": "number",
            "purchase_timestamp": "timestamp",
        },
        business_key="order_id",
        required_value_columns=(
            "order_id",
            "user_id",
            "product_id",
            "quantity",
            "amount",
            "rating",
            "purchase_timestamp",
        ),
        numeric_columns=(
            "user_id",
            "product_id",
            "quantity",
            "amount",
            "rating",
        ),
        timestamp_columns=("purchase_timestamp",),
    ),
    "popularity": DatasetSchema(
        dataset_type="popularity",
        columns=(
            "product_id",
            "average_rating",
            "total_ratings",
            "popularity_score",
            "trend",
            "updated_at",
        ),
        expected_types={
            "product_id": "integer",
            "average_rating": "number",
            "total_ratings": "integer",
            "popularity_score": "number",
            "trend": "string",
            "updated_at": "timestamp",
        },
        business_key="product_id",
        required_value_columns=(
            "product_id",
            "average_rating",
            "total_ratings",
            "popularity_score",
            "trend",
            "updated_at",
        ),
        numeric_columns=(
            "product_id",
            "average_rating",
            "total_ratings",
            "popularity_score",
        ),
        timestamp_columns=("updated_at",),
    ),
}
