# RecoMart EDA Guide

The EDA directory contains nine 150-DPI static plots plus
`eda_summary.json`.

- `interaction_type_distribution.png`: event imbalance by View, Wishlist,
  AddToCart, and Purchase.
- `user_interaction_distribution.png`: histogram of activity per user; the
  log-frequency axis exposes heavy users and the long tail.
- `item_popularity_distribution.png`: ranked, log-scale interaction curve for
  popularity concentration and long-tail behavior.
- `rating_distribution.png`: explicit purchase ratings, which must remain 1–5.
- `category_distribution.png`: top configured product categories by catalog
  count without unreadable high-cardinality labels.
- `price_distribution.png`: catalog price shape and potential outliers.
- `interactions_over_time.png`: hourly UTC interaction volume.
- `user_item_sparsity_heatmap.png`: sampled top-50 active users and top-50
  popular products; it is not the full matrix.
- `numerical_correlation_heatmap.png`: meaningful measures only; arbitrary IDs
  are excluded.

Sparsity is calculated as:

```text
possible = users × products
density = unique observed user-product pairs / possible
sparsity = 1 - density
```

High sparsity favors collaborative filtering or implicit-feedback methods that
operate efficiently on sparse matrices. A steep ranked-popularity curve
indicates a long tail. Cold-start counts in later chronological splits identify
users/products unseen in training. The JSON summary is authoritative for exact
counts, distributions, top entities, split sizes, and density.

