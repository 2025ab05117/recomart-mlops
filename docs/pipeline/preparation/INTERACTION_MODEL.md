# RecoMart Interaction Model

## Feedback Semantics

Explicit feedback is the purchase-history rating on the 1–5 scale. It is never
replaced by an implicit score. Implicit feedback represents observed behavior:

| Event | Weight |
|---|---:|
| View | 1.0 |
| Wishlist | 2.0 |
| AddToCart | 3.0 |
| Purchase | 5.0 |

Weights are configured in `configs/preparation.yaml`.

## Event-Level Schema

`interactions_prepared` contains interaction ID, user/product IDs, type,
weight, optional explicit rating, optional quantity/amount, UTC event
timestamp, optional session ID, source dataset, batch ID, and derived calendar,
recency, and cyclical time features. Clickstream and purchases remain separate
events and retain source identity.

## User-Product Aggregation

`user_product_interactions` contains user/product IDs; view, wishlist, cart,
purchase and total interaction counts; total quantity/spend; latest timestamp;
explicit rating; implicit score; and batch ID. The score is:

```text
views×1 + wishlists×2 + carts×3 + purchases×5
```

## Sparse Matrices

`user_item_implicit.parquet` stores only observed pairs and positive aggregated
scores. Logically, every omitted cell equals zero. `user_item_ratings.parquet`
stores only observed explicit purchase ratings; omitted cells are `NaN`, not
zero. SciPy CSR is used in memory to avoid materializing all
`users × products` combinations. This preserves natural sparsity without
inventing negative feedback.

