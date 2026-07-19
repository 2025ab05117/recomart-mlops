"""Transactional PostgreSQL/SQLite feature warehouse persistence."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from src.feature_engineering.config import FeatureConfig
from src.feature_engineering.errors import (
    DatabaseInitializationError,
    FeatureConflictError,
    FeaturePersistenceError,
)
from src.feature_engineering.features import FeatureFrames

TABLES = {
    "users": "user_features",
    "items": "item_features",
    "user_items": "user_item_features",
    "cooccurrence": "item_cooccurrence_features",
    "similarity": "item_similarity_features",
}


def masked_database_url(url: str) -> str:
    """Render a database URL without exposing credentials."""
    parsed = make_url(url)
    return parsed.render_as_string(hide_password=True)


class FeatureWarehouse:
    """Initialize and transactionally persist feature groups and metadata."""

    def __init__(self, config: FeatureConfig) -> None:
        """Create a SQLAlchemy engine from secret-safe configuration."""
        self.config = config
        try:
            self.engine: Engine = create_engine(config.database_url, future=True)
        except Exception as exc:
            raise DatabaseInitializationError(
                "Unable to create feature database engine."
            ) from exc
        self.sqlite = self.engine.dialect.name == "sqlite"
        self.schema = None if self.sqlite else config.database_schema

    def initialize(self) -> None:
        """Create metadata tables and views idempotently."""
        schema_prefix = "" if self.sqlite else f"{self.config.database_schema}."
        try:
            with self.engine.begin() as connection:
                if not self.sqlite:
                    connection.execute(text(
                        f"CREATE SCHEMA IF NOT EXISTS "
                        f"{self.config.database_schema}"
                    ))
                connection.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {schema_prefix}feature_batch (
                      feature_batch_id VARCHAR(80) PRIMARY KEY,
                      source_batch_id VARCHAR(100) NOT NULL,
                      preparation_run_id VARCHAR(80) NOT NULL,
                      feature_reference_timestamp TIMESTAMP NOT NULL,
                      feature_source_split VARCHAR(10) NOT NULL,
                      started_at TIMESTAMP NOT NULL,
                      completed_at TIMESTAMP,
                      status VARCHAR(30) NOT NULL,
                      user_feature_count BIGINT DEFAULT 0,
                      item_feature_count BIGINT DEFAULT 0,
                      user_item_feature_count BIGINT DEFAULT 0,
                      cooccurrence_feature_count BIGINT DEFAULT 0,
                      similarity_feature_count BIGINT DEFAULT 0,
                      configuration_hash VARCHAR(64) NOT NULL,
                      source_checksum VARCHAR(64) NOT NULL,
                      identity_hash VARCHAR(64) NOT NULL UNIQUE,
                      error_message TEXT,
                      created_at TIMESTAMP NOT NULL
                    )
                """))
                connection.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {schema_prefix}feature_definition (
                      feature_name VARCHAR(150) NOT NULL,
                      feature_group VARCHAR(50) NOT NULL,
                      entity_type VARCHAR(50) NOT NULL,
                      data_type VARCHAR(50) NOT NULL,
                      description TEXT NOT NULL,
                      calculation_logic TEXT NOT NULL,
                      source_columns TEXT NOT NULL,
                      default_value TEXT,
                      null_handling TEXT NOT NULL,
                      feature_version VARCHAR(30) NOT NULL,
                      owner VARCHAR(80) NOT NULL,
                      is_active BOOLEAN NOT NULL,
                      created_at TIMESTAMP NOT NULL,
                      updated_at TIMESTAMP NOT NULL,
                      PRIMARY KEY (feature_name, feature_version)
                    )
                """))
                connection.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {schema_prefix}feature_lineage (
                      lineage_id VARCHAR(80) PRIMARY KEY,
                      feature_batch_id VARCHAR(80) NOT NULL,
                      feature_name VARCHAR(150) NOT NULL,
                      source_dataset VARCHAR(150) NOT NULL,
                      source_columns TEXT NOT NULL,
                      transformation_name VARCHAR(150) NOT NULL,
                      transformation_version VARCHAR(30) NOT NULL,
                      transformation_parameters TEXT NOT NULL,
                      source_checksum VARCHAR(64) NOT NULL,
                      output_table VARCHAR(100) NOT NULL,
                      generated_at TIMESTAMP NOT NULL
                    )
                """))
                self._create_views(connection)
        except Exception as exc:
            raise DatabaseInitializationError(
                "Unable to initialize feature database schema."
            ) from exc

    def find_identity(self, identity_hash: str) -> dict[str, Any] | None:
        """Find an existing successful feature batch by immutable identity."""
        prefix = "" if self.sqlite else f"{self.config.database_schema}."
        with self.engine.connect() as connection:
            row = connection.execute(text(
                f"SELECT * FROM {prefix}feature_batch "
                "WHERE identity_hash=:identity AND "
                "status IN ('SUCCESS','IDEMPOTENT_SUCCESS')"
            ), {"identity": identity_hash}).mappings().first()
        return dict(row) if row else None

    def persist(
        self,
        frames: FeatureFrames,
        *,
        batch_record: dict[str, Any],
        definitions: pd.DataFrame,
        lineage: pd.DataFrame,
    ) -> None:
        """Bulk-write all feature groups and metadata in one transaction."""
        prefix = "" if self.sqlite else f"{self.config.database_schema}."
        try:
            with self.engine.begin() as connection:
                conflict = connection.execute(text(
                    f"SELECT identity_hash FROM {prefix}feature_batch "
                    "WHERE feature_batch_id=:batch"
                ), {"batch": batch_record["feature_batch_id"]}).scalar()
                if conflict and conflict != batch_record["identity_hash"]:
                    raise FeatureConflictError(
                        "feature_batch_id already has incompatible metadata."
                    )
                pd.DataFrame([batch_record]).to_sql(
                    "feature_batch", connection, schema=self.schema,
                    if_exists="append", index=False,
                )
                for attribute, table in TABLES.items():
                    getattr(frames, attribute).to_sql(
                        table, connection, schema=self.schema,
                        if_exists="append", index=False,
                        chunksize=self.config.batch_size, method="multi",
                    )
                self._upsert_definitions(connection, definitions)
                lineage.to_sql(
                    "feature_lineage", connection, schema=self.schema,
                    if_exists="append", index=False,
                    chunksize=self.config.batch_size, method="multi",
                )
        except FeatureConflictError:
            raise
        except Exception as exc:
            raise FeaturePersistenceError(
                "Feature database transaction rolled back."
            ) from exc

    def table_inventory(self) -> dict[str, list[str]]:
        """Return created table and view names for operational inspection."""
        inspector = inspect(self.engine)
        return {
            "tables": inspector.get_table_names(schema=self.schema),
            "views": inspector.get_view_names(schema=self.schema),
        }

    def _upsert_definitions(
        self, connection: Any, definitions: pd.DataFrame
    ) -> None:
        prefix = "" if self.sqlite else f"{self.config.database_schema}."
        for row in definitions.to_dict(orient="records"):
            exists = connection.execute(text(
                f"SELECT 1 FROM {prefix}feature_definition "
                "WHERE feature_name=:feature_name "
                "AND feature_version=:feature_version"
            ), row).scalar()
            if not exists:
                pd.DataFrame([row]).to_sql(
                    "feature_definition", connection, schema=self.schema,
                    if_exists="append", index=False,
                )

    def _create_views(self, connection: Any) -> None:
        prefix = "" if self.sqlite else f"{self.config.database_schema}."
        for view, table in (
            ("latest_user_features", "user_features"),
            ("latest_item_features", "item_features"),
            ("latest_user_item_features", "user_item_features"),
        ):
            if self.sqlite:
                connection.execute(text(f"DROP VIEW IF EXISTS {view}"))
            connection.execute(text(f"""
                CREATE VIEW {"IF NOT EXISTS " if self.sqlite else
                "IF NOT EXISTS "}{prefix}{view} AS
                SELECT source.*
                FROM {prefix}{table} source
                WHERE source.feature_batch_id = (
                  SELECT feature_batch_id FROM {prefix}feature_batch
                  WHERE status IN ('SUCCESS','IDEMPOTENT_SUCCESS')
                  ORDER BY completed_at DESC LIMIT 1
                )
            """))
        connection.execute(text(f"""
            CREATE VIEW IF NOT EXISTS {prefix}top_similar_items AS
            SELECT * FROM {prefix}item_similarity_features
            WHERE similarity_rank <= 50
        """))
        connection.execute(text(f"""
            CREATE VIEW IF NOT EXISTS {prefix}popular_items AS
            SELECT * FROM {prefix}latest_item_features
            ORDER BY total_interactions DESC
        """))
        connection.execute(text(f"""
            CREATE VIEW IF NOT EXISTS {prefix}active_users AS
            SELECT * FROM {prefix}latest_user_features
            ORDER BY total_interactions DESC
        """))


