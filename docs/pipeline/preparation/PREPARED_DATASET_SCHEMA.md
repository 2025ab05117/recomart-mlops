# Prepared Dataset Schemas

All analytical tables are Parquet and carry original entity/source identifiers
plus `batch_id`.

## users_prepared

| Field | Type | Description |
|---|---|---|
| user_id | int64 | Preserved user key |
| age | float64 | Validated age |
| gender, occupation, zipcode, customer_segment | string | Cleaned originals |
| registration_date | UTC timestamp | Parsed registration date |
| user_registration_age_days | float | Age at preparation reference time |
| `<category>__<value>` | int8 | Reproducible one-hot indicators |
| `*_scaled` | float | Configured standardized values |
| batch_id | string | Source validation batch |

## products_prepared

Preserves product ID/name/category/release date/price/brand/average rating and
total ratings. Adds optional popularity score and trend, product age, category
and trend one-hot fields, brand frequency, scaled continuous/count fields, and
batch ID.

## interactions_prepared

Contains interaction ID, user/product IDs, interaction type/weight, separate
explicit rating, quantity, amount, event timestamp, session, source dataset,
batch ID, hour/day/month/weekend, recency, and cyclical hour/day fields.

## user_product_interactions

One row per observed user-product pair with event-type counts, interaction
count, quantity, spend, latest time, explicit rating, implicit score, scaled
aggregate fields, and batch ID.

## user_item_implicit

| Field | Type | Description |
|---|---|---|
| user_id, product_id | int64 | Observed pair |
| implicit_score | float | Configured weighted sum |
| batch_id | string | Lineage |

Omitted pairs logically equal zero.

## user_item_ratings

Contains user/product IDs, explicit rating (1–5), and batch ID for observed
ratings only. Omitted pairs are analytically `NaN`.

## train, validation, test

These share `interactions_prepared` schema. They are chronological, mutually
exclusive slices: earliest 70%, next 15%, and latest 15%, with boundaries
recorded in the preparation manifest.

