"""Errors raised by the RecoMart orchestration integration layer."""


class OrchestrationError(RuntimeError):
    """Base error for pipeline orchestration failures."""


class RuntimeConfigurationError(OrchestrationError):
    """Raised when a DAG run configuration is invalid."""


class StageExecutionError(OrchestrationError):
    """Raised when an application stage does not complete successfully."""


class QualityGateError(OrchestrationError):
    """Raised when validation results do not satisfy the quality policy."""


class FeatureStoreGateError(OrchestrationError):
    """Raised when required feature-store assets are unavailable."""


class PipelineSummaryError(OrchestrationError):
    """Raised when durable orchestration evidence cannot be written."""
