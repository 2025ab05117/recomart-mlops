CREATE INDEX IF NOT EXISTS idx_user_features_user ON recomart_features.user_features(user_id);
CREATE INDEX IF NOT EXISTS idx_item_features_product ON recomart_features.item_features(product_id);
CREATE INDEX IF NOT EXISTS idx_user_item_user ON recomart_features.user_item_features(user_id);
CREATE INDEX IF NOT EXISTS idx_user_item_product ON recomart_features.user_item_features(product_id);
CREATE INDEX IF NOT EXISTS idx_cooccurrence_a ON recomart_features.item_cooccurrence_features(item_id_a);
CREATE INDEX IF NOT EXISTS idx_cooccurrence_b ON recomart_features.item_cooccurrence_features(item_id_b);
CREATE INDEX IF NOT EXISTS idx_similarity_rank ON recomart_features.item_similarity_features(product_id, similarity_rank);
CREATE INDEX IF NOT EXISTS idx_lineage_batch ON recomart_features.feature_lineage(feature_batch_id);
