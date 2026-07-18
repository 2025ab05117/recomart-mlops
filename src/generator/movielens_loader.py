"""Validated loading of MovieLens 100K source files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.generator.errors import MovieLensDataError

USER_COLUMNS = ["user_id", "age", "gender", "occupation", "zipcode"]
RATING_COLUMNS = ["user_id", "product_id", "rating", "source_timestamp"]
ITEM_BASE_COLUMNS = [
    "product_id",
    "product_name",
    "release_date",
    "video_release_date",
    "imdb_url",
]


@dataclass(frozen=True)
class MovieLensData:
    """Loaded MovieLens source tables and ordered genre names."""

    users: pd.DataFrame
    items: pd.DataFrame
    ratings: pd.DataFrame
    genres: tuple[str, ...]


def load_movielens_data(
    source_directory: Path, *, nested_directory_name: str = "ml-100k"
) -> MovieLensData:
    """Load and validate required MovieLens 100K files.

    Both the configured folder and the official nested archive layout are
    supported.
    """
    directory = _locate(source_directory, nested_directory_name)
    try:
        genres = _load_genres(directory / "u.genre")
        users = pd.read_csv(
            directory / "u.user",
            sep="|",
            names=USER_COLUMNS,
            header=None,
            encoding="latin-1",
            dtype={
                "user_id": "int64",
                "age": "int64",
                "gender": "string",
                "occupation": "string",
                "zipcode": "string",
            },
        )
        items = pd.read_csv(
            directory / "u.item",
            sep="|",
            names=ITEM_BASE_COLUMNS + list(genres),
            header=None,
            encoding="latin-1",
        )
        ratings = pd.read_csv(
            directory / "u.data",
            sep="\t",
            names=RATING_COLUMNS,
            header=None,
            dtype="int64",
        )
    except (OSError, UnicodeError, pd.errors.ParserError, ValueError) as exc:
        raise MovieLensDataError(
            f"Unable to parse MovieLens files in {directory}"
        ) from exc
    _validate(users, items, ratings)
    return MovieLensData(users, items, ratings, genres)


def _locate(source: Path, nested_name: str) -> Path:
    required = ("u.user", "u.item", "u.data", "u.genre")
    candidates = (source.resolve(), (source / nested_name).resolve())
    for candidate in candidates:
        if all((candidate / name).is_file() for name in required):
            return candidate
    raise MovieLensDataError(
        "MovieLens files not found; checked "
        + ", ".join(str(candidate) for candidate in candidates)
    )


def _load_genres(path: Path) -> tuple[str, ...]:
    try:
        frame = pd.read_csv(
            path,
            sep="|",
            names=["genre", "position"],
            header=None,
            encoding="latin-1",
        ).dropna()
        frame["position"] = frame["position"].astype(int)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise MovieLensDataError(f"Unable to read genres: {path}") from exc
    genres = tuple(frame.sort_values("position")["genre"].astype(str))
    if not genres:
        raise MovieLensDataError("MovieLens genres are empty.")
    return genres


def _validate(
    users: pd.DataFrame,
    items: pd.DataFrame,
    ratings: pd.DataFrame,
) -> None:
    if users.empty or items.empty or ratings.empty:
        raise MovieLensDataError("MovieLens source tables must not be empty.")
    if users["user_id"].duplicated().any():
        raise MovieLensDataError("Duplicate user identifiers found.")
    if items["product_id"].duplicated().any():
        raise MovieLensDataError("Duplicate product identifiers found.")
    if not ratings["rating"].between(1, 5).all():
        raise MovieLensDataError("Ratings must be between one and five.")
    if not set(ratings["user_id"]).issubset(set(users["user_id"])):
        raise MovieLensDataError("Ratings reference unknown users.")
    if not set(ratings["product_id"]).issubset(set(items["product_id"])):
        raise MovieLensDataError("Ratings reference unknown products.")
