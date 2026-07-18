"""Feature-engineering domain exceptions."""


class FeatureEngineeringError(Exception):
    """Base feature-engineering failure."""


class PreparedBatchNotFoundError(FeatureEngineeringError):
    """A complete prepared batch cannot be resolved."""


class FeatureConfigurationError(FeatureEngineeringError):
    """Feature configuration is invalid."""


class FeatureComputationError(FeatureEngineeringError):
    """A feature group cannot be computed."""


class SimilarityComputationError(FeatureComputationError):
    """Sparse similarity computation failed."""


class DatabaseInitializationError(FeatureEngineeringError):
    """Feature database schema initialization failed."""


class FeaturePersistenceError(FeatureEngineeringError):
    """Transactional feature persistence failed."""


class FeatureLineageError(FeatureEngineeringError):
    """Feature lineage generation failed."""


class FeatureConflictError(FeatureEngineeringError):
    """A feature batch conflicts with immutable existing metadata."""
