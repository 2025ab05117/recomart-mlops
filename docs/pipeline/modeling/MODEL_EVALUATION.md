# Model Evaluation

## Evaluation protocol

Models train on the prepared chronological training split and are evaluated
on the existing test split. A relevant item is an observed explicit rating at
or above the configured threshold (default `4`). Ranking metrics are calculated
per test user and macro-averaged. `K` defaults to 10.

## Metrics

| Metric | Meaning |
|---|---|
| RMSE | Square-root mean squared explicit-rating error; collaborative only. |
| MAE | Mean absolute explicit-rating error; collaborative only. |
| Precision@K | Relevant recommended items divided by K. |
| Recall@K | Relevant recommended items divided by relevant test items. |
| MAP@K | Mean average precision, rewarding early relevant hits. |
| NDCG@K | Position-discounted ranking quality normalized per user. |
| Hit Rate@K | Fraction of users with at least one relevant recommendation. |
| Coverage | Unique recommended products divided by catalog size. |
| Catalog Coverage | Alias reported explicitly for content evaluation. |
| Intra-list Diversity | One minus mean category/brand equality similarity. |
| Novelty | Mean `-log2(item interaction probability)` of recommendations. |
| Similarity Quality | Mean cosine score of example similar-item results. |

Undefined metrics are represented as null/NaN and are not coerced to zero.
RMSE and MAE are not applicable to the content model because it does not
predict an explicit rating.

## Comparison

`model_comparison.json` contains RMSE, Precision@10, Recall@10, MAP@10,
NDCG@10, coverage, training time, and inference time. The automatic
recommendation uses a transparent composite of precision, recall, NDCG, and
coverage. The component metrics remain visible, so catalog reach cannot hide
weak relevance or vice versa.

The best model is deployment-context dependent. Collaborative filtering
usually improves relevance for known users but has cold-start limitations.
Content recommendations provide broad catalog coverage and explanations based
on product attributes, but do not model collective preference as directly.

## Report artifacts

The authoritative machine-readable artifacts are `training_summary.json` and
`model_comparison.json`. `model_performance_report.pdf` presents the dataset,
algorithms, hyperparameters, metrics, recommendation examples, advantages,
limitations, and conclusion. MLflow receives all finite metrics plus the
configuration, evaluation JSON, metadata, and serialized model.
