"""Typed errors raised by the synthetic data generator."""


class GeneratorError(Exception):
    """Base exception for synthetic data generation failures."""


class GeneratorConfigurationError(GeneratorError):
    """Raised when generator configuration is missing or invalid."""


class MovieLensDataError(GeneratorError):
    """Raised when MovieLens source files are missing or malformed."""


class OutputPublicationError(GeneratorError):
    """Raised when generated output cannot be safely published."""
