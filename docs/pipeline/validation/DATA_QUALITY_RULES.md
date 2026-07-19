# RecoMart Data Quality Rules

## Rule Contract

Every rule produces ID, name, dataset, column, category, severity, status,
records checked, failed count/percentage, message, and bounded examples.
ERROR row failures quarantine records; WARNING results remain reportable but
do not quarantine; dependent rules are SKIPPED when required inputs are absent.
Required fields are errors, optional nulls are profiled, and no imputation is
performed.

All datasets receive `<DATASET>_SCHEMA_REQUIRED_COLUMNS` (ERROR),
`<DATASET>_SCHEMA_UNEXPECTED_COLUMNS` (WARNING), `<DATASET>_NON_EMPTY`
(ERROR), `<DATASET>_DUPLICATE_ROWS` (ERROR), required-value rules (ERROR), and
business-key uniqueness (ERROR). Required columns come from
`configs/validation_rules.yaml`.

## Users

| Rule ID | Column | Description | Severity | Failure behavior / configuration |
|---|---|---|---|---|
| USERS_USER_ID_REQUIRED | user_id | ID is present | ERROR | Quarantine; required column/value |
| USERS_USER_ID_UNIQUE | user_id | Business key is unique | ERROR | Quarantine all copies |
| USERS_USER_ID_POSITIVE_INTEGER | user_id | Positive integer ID | ERROR | Quarantine |
| USERS_AGE_RANGE | age | Numeric configured age range | ERROR | Quarantine; default 1–120 |
| USERS_GENDER_ALLOWED | gender | Generated-contract gender | ERROR | Quarantine; configured enum |
| USERS_OCCUPATION_REQUIRED | occupation | Nonblank occupation | ERROR | Quarantine |
| USERS_ZIPCODE_REQUIRED | zipcode | Nonblank ZIP code | ERROR | Quarantine |
| USERS_REGISTRATION_DATE_FORMAT | registration_date | Parseable date | ERROR | Quarantine |
| USERS_REGISTRATION_DATE_NOT_FUTURE | registration_date | Not beyond tolerance | ERROR | Quarantine |
| USERS_SEGMENT_ALLOWED | customer_segment | Premium/Gold/Silver/Standard | ERROR | Quarantine; configured enum |

## Products

| Rule ID | Column | Description | Severity | Failure behavior / configuration |
|---|---|---|---|---|
| PRODUCTS_PRODUCT_ID_REQUIRED | product_id | ID is present | ERROR | Quarantine |
| PRODUCTS_PRODUCT_ID_UNIQUE | product_id | Unique business key | ERROR | Quarantine all copies |
| PRODUCTS_PRODUCT_ID_POSITIVE_INTEGER | product_id | Positive integer ID | ERROR | Quarantine |
| PRODUCTS_PRODUCT_NAME_NOT_BLANK | product_name | Name is nonblank | ERROR | Quarantine |
| PRODUCTS_CATEGORY_NOT_BLANK | category | Category is nonblank | ERROR | Quarantine |
| PRODUCTS_BRAND_NOT_BLANK | brand | Brand is nonblank | ERROR | Quarantine |
| PRODUCTS_PRICE_POSITIVE | price | Numeric and at least minimum | ERROR | Quarantine; default 0.01 |
| PRODUCTS_AVERAGE_RATING_RANGE | average_rating | Aggregate rating is 1–5, or configured unrated value when count is zero | ERROR | Quarantine |
| PRODUCTS_TOTAL_RATINGS_NONNEGATIVE | total_ratings | Nonnegative integer | ERROR | Quarantine |
| PRODUCTS_RELEASE_DATE_FORMAT | release_date | Nonblank optional date parses | ERROR | Quarantine |
| PRODUCTS_RELEASE_DATE_NOT_FUTURE | release_date | Date is not future | ERROR | Quarantine |

## Clickstream

| Rule ID | Column | Description | Severity | Failure behavior / configuration |
|---|---|---|---|---|
| CLICKSTREAM_EVENT_ID_REQUIRED | event_id | Event ID present | ERROR | Quarantine |
| CLICKSTREAM_EVENT_ID_UNIQUE | event_id | Unique business key | ERROR | Quarantine all copies |
| CLICKSTREAM_EVENT_UUID | event_id | UUID format | ERROR | Quarantine |
| CLICKSTREAM_SESSION_UUID | session_id | UUID format | ERROR | Quarantine |
| CLICKSTREAM_USER_ID_POSITIVE_INTEGER | user_id | Positive integer | ERROR | Quarantine |
| CLICKSTREAM_PRODUCT_ID_POSITIVE_INTEGER | product_id | Positive integer | ERROR | Quarantine |
| CLICKSTREAM_EVENT_TYPE_ALLOWED | event_type | View/Wishlist/AddToCart | ERROR | Quarantine; configured enum |
| CLICKSTREAM_TIMESTAMP_FORMAT | timestamp | Valid timestamp | ERROR | Quarantine |
| CLICKSTREAM_TIMESTAMP_NOT_FUTURE | timestamp | Not beyond tolerance | ERROR | Quarantine |
| CLICKSTREAM_USER_REFERENCE | user_id | Exists in raw users | ERROR | Quarantine orphan |
| CLICKSTREAM_PRODUCT_REFERENCE | product_id | Exists in raw products | ERROR | Quarantine orphan |
| CLICKSTREAM_SESSION_CHRONOLOGY | timestamp | Source order is chronological per session | WARNING | Report |
| CLICKSTREAM_SESSION_SEQUENCE | event_type | Product interaction starts with View | WARNING | Report |

## Purchase History

| Rule ID | Column | Description | Severity | Failure behavior / configuration |
|---|---|---|---|---|
| PURCHASEHISTORY_ORDER_ID_UNIQUE | order_id | Unique business key | ERROR | Quarantine all copies |
| PURCHASE_ORDER_UUID | order_id | UUID format | ERROR | Quarantine |
| PURCHASE_USER_ID_POSITIVE_INTEGER | user_id | Positive integer | ERROR | Quarantine |
| PURCHASE_PRODUCT_ID_POSITIVE_INTEGER | product_id | Positive integer | ERROR | Quarantine |
| PURCHASE_QUANTITY_RANGE | quantity | Integer within configured range | ERROR | Quarantine; default 1–100 |
| PURCHASE_AMOUNT_POSITIVE | amount | Numeric and positive | ERROR | Quarantine |
| PURCHASE_RATING_RANGE | rating | Explicit rating within 1–5 | ERROR | Quarantine |
| PURCHASE_MINIMUM_RATING | rating | Generator purchases require rating ≥ 4 | ERROR | Quarantine |
| PURCHASE_TIMESTAMP_FORMAT | purchase_timestamp | Valid timestamp | ERROR | Quarantine |
| PURCHASE_TIMESTAMP_NOT_FUTURE | purchase_timestamp | Not beyond tolerance | ERROR | Quarantine |
| PURCHASE_USER_REFERENCE | user_id | Exists in raw users | ERROR | Quarantine orphan |
| PURCHASE_PRODUCT_REFERENCE | product_id | Exists in raw products | ERROR | Quarantine orphan |
| PURCHASE_AMOUNT_CONSISTENCY | amount | Equals quantity × product price within tolerance | ERROR | Quarantine; default tolerance 0.01 |
| PURCHASE_CLICK_CHRONOLOGY | purchase_timestamp | Not earlier than latest matching user-product click | ERROR | Quarantine when comparable |
| PURCHASE_CLICK_CORRELATION_AVAILABLE | user_id/product_id | Matching interaction exists | WARNING | Report; exact event/order ID is unavailable |

## Popularity

| Rule ID | Column | Description | Severity | Failure behavior / configuration |
|---|---|---|---|---|
| POPULARITY_PRODUCT_ID_UNIQUE | product_id | Unique business key | ERROR | Quarantine all copies |
| POPULARITY_PRODUCT_ID_POSITIVE_INTEGER | product_id | Positive integer | ERROR | Quarantine |
| POPULARITY_AVERAGE_RATING_RANGE | average_rating | Aggregate rating is 1–5 or allowed unrated value | ERROR | Quarantine |
| POPULARITY_TOTAL_RATINGS_NONNEGATIVE | total_ratings | Nonnegative integer | ERROR | Quarantine |
| POPULARITY_SCORE_RANGE | popularity_score | Numeric 0–100 | ERROR | Quarantine; configured |
| POPULARITY_TREND_ALLOWED | trend | UP or DOWN | ERROR | Quarantine; actual API contract |
| POPULARITY_UPDATED_AT_FORMAT | updated_at | Valid UTC-capable timestamp | ERROR | Quarantine |
| POPULARITY_UPDATED_AT_NOT_FUTURE | updated_at | Not beyond tolerance | ERROR | Quarantine |
| POPULARITY_FRESHNESS | updated_at | Within configured age window | WARNING | Report; default 168 hours |
| POPULARITY_PRODUCT_REFERENCE | product_id | Exists in raw products | ERROR | Quarantine orphan |
| POPULARITY_PRODUCT_STATISTICS | average_rating/total_ratings | Matches product aggregates within tolerances | ERROR | Quarantine; rating 0.01/count 0 defaults |

The full generated rule inventory, including common required-value IDs and
SKIPPED outcomes, is preserved in each machine-readable summary.

