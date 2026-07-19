# RecoMart Feature Storage Schema

PostgreSQL uses schema `recomart_features`; SQLite omits qualification. Tables
are `feature_batch`, `feature_definition`, `feature_lineage`, `user_features`,
`item_features`, `user_item_features`, `item_cooccurrence_features`, and
`item_similarity_features`.

Primary keys pair feature batch with entity key(s). Pair tables enforce
canonical/no-self uniqueness. Index scripts cover user/product lookup,
co-occurrence endpoints, ranked similarity, and lineage batch lookup. Views
provide latest user/item/user-item features, top similar items, popular items,
and active users. PostgreSQL uses JSONB/TIMESTAMPTZ/UUID in versioned SQL;
SQLite application tables use compatible TEXT/timestamp values.

SQL assets are under `sql/feature_store/`.

```sql
SELECT user_id, total_interactions, interaction_frequency_per_day
FROM recomart_features.latest_user_features
ORDER BY total_interactions DESC LIMIT 20;
```

```sql
SELECT product_id, average_rating, rating_count
FROM recomart_features.latest_item_features
WHERE rating_count > 0
ORDER BY average_rating DESC, rating_count DESC LIMIT 20;
```

```sql
SELECT product_id, similar_product_id, combined_similarity_score,
       similarity_rank
FROM recomart_features.top_similar_items
WHERE product_id = :product_id ORDER BY similarity_rank;
```

```sql
SELECT item_id_a, item_id_b, cooccurrence_count, lift
FROM recomart_features.item_cooccurrence_features
WHERE feature_batch_id = :feature_batch_id
ORDER BY lift DESC LIMIT 20;
```

All feature tables relate to `feature_batch_id`; lineage relates each registered
feature and prepared checksum to its output table.

