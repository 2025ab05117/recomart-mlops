# RecoMart Data Preparation Design

## Architecture

The preparation stage reads only paths declared by an eligible
`validation_manifest.json`. It never scans raw storage or reads quarantine.
`src/preparation/loader.py` resolves lineage, `transformations.py` performs
cleaning/encoding/scaling/interactions/matrices/splitting, `eda.py` creates
analysis, and `runner.py` publishes immutable Parquet and metadata artifacts.
The CLI and notebook are thin clients of these reusable services.

## Cleaning

Column names and whitespace are standardized, configured categorical casing is
normalized, numerical types are enforced, and dates/timestamps are parsed as
UTC. IDs are preserved. Events and purchases are sorted chronologically.
Escaped exact duplicates are removed and counted; no removal is silent.
Required values are not imputed. Optional product release dates remain null.
Unavailable validated popularity enrichment leaves `popularity_score` null and
uses the configured `Unknown` trend, with a manifest warning.

## Missing Interactions

An absent user-product pair is normal recommendation sparsity, not a quality
failure. No fake event, purchase, or rating is generated. The implicit matrix
defines absence as zero; the explicit matrix defines absence as `NaN` because
zero is outside the 1–5 rating contract. Persistence is long-form Parquet,
while in-memory implicit construction uses SciPy CSR.

## Encoding and Normalization

Gender, occupation, customer segment, category, and trend use one-hot encoding
with an explicit future-safe Unknown category. Brand uses frequency encoding
because its meaning is nominal and its cardinality may grow. Original fields
are retained. Metadata JSON records categories, frequencies, and unknown
behavior.

StandardScaler is used for continuous fields. Skewed nonnegative counts and
spend/implicit aggregates use `log1p` then StandardScaler. Missing optional
numeric values remain null and are excluded from fitting. Metadata records
method, fitted count, mean, and scale.

## Time Features and Splitting

UTC interaction timestamps derive hour, day-of-week, day, month, weekend,
recency, and sine/cosine cyclical features. User registration and product age
are derived relative to the UTC run start. Interactions are globally ordered by
timestamp and stable interaction ID. Earliest 70% is training, next 15%
validation, and latest 15% test; integer rounding assigns the remainder to
training. Tiny valid fixtures reserve at least one validation and test row.
Split boundaries and cold-start entity counts are recorded.

## Idempotency and Downstream Use

Identity combines batch ID, validated-file checksums, configuration SHA-256,
and transformation version. Matching outputs are reused; incompatible identity
at the same batch destination fails. Prepared Parquet is the input contract for
feature engineering and modeling. The event table supports sequential/time
models, aggregation supports implicit recommenders, and explicit ratings remain
separate for rating-aware objectives.

