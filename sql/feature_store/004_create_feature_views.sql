CREATE OR REPLACE VIEW recomart_features.latest_user_features AS
SELECT u.* FROM recomart_features.user_features u
WHERE u.feature_batch_id = (
  SELECT feature_batch_id FROM recomart_features.feature_batch
  WHERE status IN ('SUCCESS','IDEMPOTENT_SUCCESS')
  ORDER BY completed_at DESC LIMIT 1
);

CREATE OR REPLACE VIEW recomart_features.latest_item_features AS
SELECT i.* FROM recomart_features.item_features i
WHERE i.feature_batch_id = (
  SELECT feature_batch_id FROM recomart_features.feature_batch
  WHERE status IN ('SUCCESS','IDEMPOTENT_SUCCESS')
  ORDER BY completed_at DESC LIMIT 1
);

CREATE OR REPLACE VIEW recomart_features.latest_user_item_features AS
SELECT ui.* FROM recomart_features.user_item_features ui
WHERE ui.feature_batch_id = (
  SELECT feature_batch_id FROM recomart_features.feature_batch
  WHERE status IN ('SUCCESS','IDEMPOTENT_SUCCESS')
  ORDER BY completed_at DESC LIMIT 1
);

CREATE OR REPLACE VIEW recomart_features.top_similar_items AS
SELECT * FROM recomart_features.item_similarity_features
WHERE similarity_rank <= 50;

CREATE OR REPLACE VIEW recomart_features.popular_items AS
SELECT * FROM recomart_features.latest_item_features
ORDER BY total_interactions DESC;

CREATE OR REPLACE VIEW recomart_features.active_users AS
SELECT * FROM recomart_features.latest_user_features
ORDER BY total_interactions DESC;
