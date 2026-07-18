"""Preparation-domain exceptions."""


class PreparationError(Exception):
    """Base preparation failure."""


class ValidatedBatchNotFoundError(PreparationError):
    """A complete validation manifest or validated dataset is unavailable."""


class PreparationConfigurationError(PreparationError):
    """Preparation configuration is invalid."""


class DatasetPreparationError(PreparationError):
    """Validated data cannot be cleaned or transformed."""


class EncodingError(PreparationError):
    """Categorical encoding failed."""


class NormalizationError(PreparationError):
    """Numerical normalization failed."""


class MatrixConstructionError(PreparationError):
    """User-item matrix construction failed."""


class DataSplitError(PreparationError):
    """Chronological data splitting failed."""


class EdaGenerationError(PreparationError):
    """EDA summary or plot generation failed."""


class PreparationStorageError(PreparationError):
    """An immutable prepared artifact cannot be published."""


class PreparationConflictError(PreparationStorageError):
    """An existing output has incompatible lineage."""
