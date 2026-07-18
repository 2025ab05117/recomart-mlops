"""Modeling-domain exceptions."""


class TrainingError(Exception):
    """Model training failed."""


class EvaluationError(TrainingError):
    """Metric calculation or evaluation failed."""


class ModelPersistenceError(TrainingError):
    """A model artifact cannot be persisted."""


class FeatureStoreError(TrainingError):
    """Feature-store or chronological split data cannot be loaded."""


class MLflowTrackingError(TrainingError):
    """Experiment tracking failed."""
