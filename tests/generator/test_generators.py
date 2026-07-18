"""Unit tests for deterministic synthetic data generation."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.generator.batch_generator import BatchGenerator
from src.generator.generator_config import GeneratorConfig


def _write_fixture(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "u.genre").write_text(
        "unknown|0\nAction|1\nComedy|2\n", encoding="latin-1"
    )
    (directory / "u.user").write_text(
        "1|24|M|technician|85711\n"
        "2|35|F|writer|94043\n",
        encoding="latin-1",
    )
    (directory / "u.item").write_text(
        "1|Widget One|01-Jan-1995||http://example/1|0|1|0\n"
        "2|Widget Two|02-Feb-1996||http://example/2|0|0|1\n",
        encoding="latin-1",
    )
    (directory / "u.data").write_text(
        "1\t1\t5\t881250949\n"
        "2\t1\t3\t881250950\n"
        "1\t2\t4\t881250951\n",
        encoding="ascii",
    )


def _config(source: Path, output: Path) -> GeneratorConfig:
    return GeneratorConfig(
        project_root=source.parent,
        source_directory=source,
        nested_directory_name="ml-100k",
        output_directory=output,
        overwrite_existing=False,
        random_seed=17,
        reference_time=datetime(
            2026, 7, 19, 12, 30, tzinfo=timezone.utc
        ),
        registration_lookback_years=5,
        clickstream_lookback_hours=24,
        purchase_delay_min_minutes=5,
        purchase_delay_max_minutes=180,
        session_inactivity_minutes=30,
        minimum_price=100.0,
        maximum_price=3000.0,
        customer_segments=("Premium", "Gold", "Silver", "Standard"),
        brands=("NovaCart", "UrbanNest"),
    )


def test_batch_generator_creates_expected_datasets(tmp_path: Path) -> None:
    """Generated files satisfy schemas and core business mappings."""
    source = tmp_path / "source"
    output = tmp_path / "incoming"
    _write_fixture(source)

    result = BatchGenerator(_config(source, output)).generate()

    assert result.users_count == 2
    assert result.products_count == 2
    assert result.purchases_count == 2
    assert {path.name for path in output.iterdir()} == {
        "users.csv",
        "products.json",
        "clickstream.csv",
        "purchasehistory.csv",
        "popularity.json",
    }
    users = pd.read_csv(output / "users.csv")
    clicks = pd.read_csv(output / "clickstream.csv")
    purchases = pd.read_csv(output / "purchasehistory.csv")
    products = json.loads((output / "products.json").read_text("utf-8"))
    popularity = json.loads(
        (output / "popularity.json").read_text("utf-8")
    )

    assert users["user_id"].tolist() == [1, 2]
    assert products[0]["category"] == "Action"
    assert products[0]["average_rating"] == 4.0
    assert products[0]["total_ratings"] == 2
    assert clicks["timestamp"].is_monotonic_increasing
    assert clicks["event_id"].is_unique
    assert set(
        clicks.loc[clicks["product_id"] == 2, "event_type"]
    ) == {"View", "AddToCart"}
    assert set(purchases["rating"]) == {4, 5}
    assert purchases["order_id"].is_unique
    assert all(0 <= row["popularity_score"] <= 100 for row in popularity)
    assert {row["trend"] for row in popularity} <= {"UP", "DOWN"}


def test_seeded_generation_is_byte_deterministic(tmp_path: Path) -> None:
    """The same seed and reference time produce byte-identical files."""
    source = tmp_path / "source"
    first_output = tmp_path / "incoming-one"
    second_output = tmp_path / "incoming-two"
    _write_fixture(source)
    first_config = _config(source, first_output)
    second_config = replace(first_config, output_directory=second_output)

    BatchGenerator(first_config).generate()
    BatchGenerator(second_config).generate()

    for first_file in first_output.iterdir():
        assert first_file.read_bytes() == (
            second_output / first_file.name
        ).read_bytes()
