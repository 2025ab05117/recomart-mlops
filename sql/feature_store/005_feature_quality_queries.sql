SELECT feature_batch_id, COUNT(*) AS duplicate_users
FROM recomart_features.user_features
GROUP BY feature_batch_id, user_id HAVING COUNT(*) > 1;

SELECT COUNT(*) AS invalid_similarity_rows
FROM recomart_features.item_similarity_features
WHERE product_id = similar_product_id
   OR combined_similarity_score < 0
   OR combined_similarity_score > 1;

SELECT COUNT(*) AS invalid_cooccurrence_rows
FROM recomart_features.item_cooccurrence_features
WHERE item_id_a >= item_id_b OR support < 0 OR support > 1;

SELECT feature_batch_id, status, user_feature_count, item_feature_count,
       user_item_feature_count, cooccurrence_feature_count,
       similarity_feature_count
FROM recomart_features.feature_batch
ORDER BY completed_at DESC;
