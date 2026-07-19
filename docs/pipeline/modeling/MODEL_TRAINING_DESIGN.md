# Model Training Design

## Purpose

The modeling stage consumes immutable feature-store data and the chronological
prepared splits referenced by the feature manifest. It never reads raw,
quarantined, or unvalidated data. The command `python -m src.modeling.cli`
executes one reproducible training run.

## Architecture

`loaders` resolves the latest successful feature batch and its preparation
manifest. `collaborative` and `content_based` contain independent estimators.
`evaluation` computes common recommendation metrics. `persistence` writes
versioned model bundles, `tracking` records experiments in MLflow, and
`reporting` creates JSON and PDF artifacts. `TrainingRunner` coordinates these
components; orchestration layers contain no modeling logic.

## Input and leakage controls

Feature Store tables supply user, item, user-item, co-occurrence, and
similarity features. The exact `train.parquet`, `validation.parquet`, and
`test.parquet` files referenced by `preparation_manifest.json` preserve the
established chronological split. Models fit only the training split.
Validation is available for tuning; final reported metrics use test. No random
resplitting occurs.

## Collaborative model

The implementation is deterministic biased Funk SVD, a matrix-factorization
form of collaborative filtering:

`rating(u,i) = global_mean + user_bias + item_bias + user_factors · item_factors`

Stochastic gradient descent optimizes squared error with L2 regularization.
Only valid, observed explicit ratings are used; absent interactions are not
converted to negative ratings. Unknown users or items fall back to known
biases and the global mean.

## Content-based model

Product category and brand are one-hot encoded. Price and average rating are
standardized. Rows are L2-normalized and compared with cosine similarity.
User recommendations use the centroid of products in the user's training
history and exclude already-observed products. `similar_items` compares one
catalog item to all other items and excludes self-pairs.

Feature importance is reported as the proportion of transformed dimensions
assigned to category, brand, price, and rating. This describes representation
capacity rather than causal importance.

## Reproducibility and metadata

Configuration is external in `configs/modeling.yaml`. Every run records a
model-run ID, source and feature batch IDs, preparation-run ID, UTC timestamps,
configuration SHA-256, random seed, Git commit when available, algorithm,
parameters, metrics, paths, and MLflow identifiers. Model bundles contain
`model.joblib`, `metadata.json`, `training_config.yaml`, and
`evaluation.json`.

## Persistence and failure behavior

Models are stored in immutable `model_run_id=<id>` directories under
`models/collaborative` and `models/content_based`. Reports use the same run
partition. Existing run destinations are not silently overwritten. A failure
raises a typed exception, is logged with context, and does not present partial
artifacts as a successful run.

## Operational boundaries

The runner performs one batch and exits. Airflow may invoke it after feature
generation, but DAGs must contain only orchestration. The notebook imports the
production modules rather than reimplementing algorithms.
