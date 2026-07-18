# RecoMart Feature Catalog

Version: `1.0`. Every row also carries feature/source batch IDs, reference time,
and creation time. The database `feature_definition` table is the authoritative
machine-readable registry.

## User Features

| Features | Type | Logic / source | Null/default |
|---|---|---|---|
| total_interactions, unique_products_interacted | integer | Count events/distinct products | 0 |
| view_count, wishlist_count, add_to_cart_count, purchase_count | integer | Event-type counts | 0 |
| interaction_frequency_per_day | float | total / max(1, observation days) | 0 |
| interaction_frequency_last_7d, interaction_frequency_last_30d | float | Window count / window days | 0 |
| active_days, session_count, average_events_per_session | numeric | Distinct UTC dates/sessions and safe ratio | Ratio null if no sessions |
| average_rating_given, rating_count, rating_stddev, minimum_rating_given, maximum_rating_given | numeric | Valid non-null explicit ratings only | Statistics null without ratings; count 0 |
| total_quantity_purchased, total_spend | float | Purchase sums | 0 |
| average_order_value, maximum_order_value | float | Purchase amounts | Null without purchase |
| days_since_last_interaction, days_since_last_purchase | float | Reference minus latest UTC event | Purchase recency null without purchase |
| user_tenure_days | float | Reference minus registration | Null if registration unavailable |
| preferred_category, preferred_brand | string | Highest implicit-weight total | Null without events |
| preferred_interaction_type | string | Highest event count | Null without events |
| view_to_cart_ratio, cart_to_purchase_ratio, purchase_conversion_rate | float | Safe directional ratios | Null on zero denominator |
| user_activity_level | string | LOW < q33; HIGH > q66; else MEDIUM | Thresholds persisted |
| cold_start_user_flag | boolean | total interactions < configured 5 | False/true |

## Item Features

Activity/type/unique-user counts, rating statistics, quantity/revenue/order
amount, three separate popularity scores, conversion ratios, 7/30-day counts,
growth rate, category/brand/price/scaled price/product age, overall/category
rank, long-tail flag, and cold-start flag are materialized. Ratings remain null
without explicit feedback. Long tail means interaction count below the 80th
percentile boundary. Cold start means unique users below 3 or interactions
below 5.

## User-Item Features

Observed-pair interaction/type counts, implicit score, explicit/latest/average
rating, quantity/spend, first/last interaction and purchase timestamps,
reference-time recencies, average interval, sessions, safe conversion ratios,
category affinity, brand affinity, price preference distance, and
`1/(1+distance)` similarity are materialized. Affinity is category/brand
implicit weight divided by the user's total implicit weight.

## Co-occurrence Features

Canonical `item_id_a < item_id_b`; distinct shared-user count, shared-session
count, co-purchase count, item user counts, support, both confidences, and lift.
Pairs require configured count ≥2 and support ≥0.001, with at most 100 retained
neighbors per endpoint.

## Similarity Features

Cosine implicit-vector similarity, Jaccard user-set similarity, binary
category/brand matches, price similarity, rating similarity, weighted combined
score, and per-product rank. Combined weights are 0.45/0.20/0.15/0.05/0.10/0.05.
Self-pairs and scores below 0.01 are excluded; top 50 per product remain.

