"""Reusable rule result construction and invalid-record accumulation."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import pandas as pd

from src.validation.models import RuleResult, RuleStatus, Severity


class RuleAccumulator:
    """Collect rule outcomes and record-level ERROR failure metadata."""

    def __init__(
        self,
        *,
        dataset_type: str,
        frame: pd.DataFrame,
        sample_count: int,
    ) -> None:
        """Initialize for one RangeIndex-normalized dataset."""
        self.dataset_type = dataset_type
        self.frame = frame
        self.sample_count = sample_count
        self.rules: list[RuleResult] = []
        self.invalid_mask = pd.Series(False, index=frame.index, dtype=bool)
        self.error_codes: dict[int, list[str]] = defaultdict(list)
        self.error_messages: dict[int, list[str]] = defaultdict(list)

    def add(
        self,
        *,
        rule_id: str,
        rule_name: str,
        category: str,
        severity: Severity,
        message: str,
        failed_mask: pd.Series,
        column_name: str | None = None,
        sample_series: pd.Series | None = None,
        records_checked: int | None = None,
    ) -> RuleResult:
        """Add a row-level rule and update quarantine metadata."""
        mask = failed_mask.reindex(self.frame.index, fill_value=False)
        mask = mask.fillna(False).astype(bool)
        failed_indices = [int(index) for index in self.frame.index[mask]]
        failed_count = len(failed_indices)
        checked = len(self.frame) if records_checked is None else records_checked
        status = _status(severity, failed_count)
        samples = _samples(
            sample_series if sample_series is not None else self.frame.index.to_series(),
            mask,
            self.sample_count,
        )
        result = RuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            dataset_type=self.dataset_type,
            column_name=column_name,
            category=category,
            severity=severity.value,
            status=status.value,
            records_checked=checked,
            failed_record_count=failed_count,
            failure_percentage=(
                round(failed_count / checked * 100, 4) if checked else 0.0
            ),
            message=message,
            sample_failed_values=samples,
            failed_indices=failed_indices,
        )
        self.rules.append(result)
        if severity is Severity.ERROR and failed_count:
            self.invalid_mask |= mask
            for index in failed_indices:
                self.error_codes[index].append(rule_id)
                self.error_messages[index].append(message)
        return result

    def add_dataset_rule(
        self,
        *,
        rule_id: str,
        rule_name: str,
        category: str,
        severity: Severity,
        message: str,
        failure_count: int,
        records_checked: int,
        quarantine_all: bool = False,
        samples: list[Any] | None = None,
    ) -> RuleResult:
        """Add a schema/dataset-level outcome."""
        status = _status(severity, failure_count)
        failed_indices = (
            [int(index) for index in self.frame.index]
            if quarantine_all and failure_count
            else []
        )
        result = RuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            dataset_type=self.dataset_type,
            column_name=None,
            category=category,
            severity=severity.value,
            status=status.value,
            records_checked=records_checked,
            failed_record_count=failure_count,
            failure_percentage=(
                round(failure_count / records_checked * 100, 4)
                if records_checked
                else (100.0 if failure_count else 0.0)
            ),
            message=message,
            sample_failed_values=(samples or [])[: self.sample_count],
            failed_indices=failed_indices,
        )
        self.rules.append(result)
        if severity is Severity.ERROR and failed_indices:
            self.invalid_mask.loc[failed_indices] = True
            for index in failed_indices:
                self.error_codes[index].append(rule_id)
                self.error_messages[index].append(message)
        return result

    def skip(
        self,
        *,
        rule_id: str,
        rule_name: str,
        category: str,
        message: str,
        column_name: str | None = None,
        severity: Severity = Severity.ERROR,
    ) -> RuleResult:
        """Record a dependent rule as skipped."""
        result = RuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            dataset_type=self.dataset_type,
            column_name=column_name,
            category=category,
            severity=severity.value,
            status=RuleStatus.SKIPPED.value,
            records_checked=0,
            failed_record_count=0,
            failure_percentage=0.0,
            message=message,
        )
        self.rules.append(result)
        return result

    def split(
        self,
        *,
        validation_run_id: str,
        batch_id: str,
        quarantined_at: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return valid and annotated invalid record frames."""
        valid = self.frame.loc[~self.invalid_mask].copy()
        invalid = self.frame.loc[self.invalid_mask].copy()
        if not invalid.empty:
            invalid["validation_error_codes"] = [
                self.error_codes[int(index)] for index in invalid.index
            ]
            invalid["validation_error_messages"] = [
                self.error_messages[int(index)] for index in invalid.index
            ]
            invalid["validation_run_id"] = validation_run_id
            invalid["batch_id"] = batch_id
            invalid["quarantined_at"] = quarantined_at
        return valid.reset_index(drop=True), invalid.reset_index(drop=True)


def blank_mask(series: pd.Series) -> pd.Series:
    """Return true for null or whitespace-only values."""
    return series.isna() | series.astype("string").str.strip().eq("")


def numeric_values(series: pd.Series) -> pd.Series:
    """Coerce values to numeric for validation without mutating source data."""
    return pd.to_numeric(series, errors="coerce")


def integer_invalid_mask(series: pd.Series) -> pd.Series:
    """Return true for values that are not parseable whole numbers."""
    numeric = numeric_values(series)
    return numeric.isna() | (numeric % 1 != 0)


def uuid_invalid_mask(series: pd.Series) -> pd.Series:
    """Return true for values outside the canonical UUID representation."""
    pattern = (
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-"
        r"[0-9a-fA-F]{12}$"
    )
    return blank_mask(series) | ~series.astype("string").str.fullmatch(
        pattern, na=False
    )


def parse_timestamps(series: pd.Series) -> pd.Series:
    """Parse mixed ISO or supported source dates as timezone-aware values."""
    return pd.to_datetime(series, errors="coerce", utc=True, format="mixed")


def _status(severity: Severity, failed_count: int) -> RuleStatus:
    if not failed_count:
        return RuleStatus.PASSED
    if severity is Severity.ERROR:
        return RuleStatus.FAILED
    return RuleStatus.WARNING


def _samples(
    values: pd.Series,
    failed_mask: pd.Series,
    count: int,
) -> list[Any]:
    selected = values.reindex(failed_mask.index)[failed_mask].head(count)
    return [_json_value(value) for value in selected.tolist()]


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value) if not isinstance(value, (str, int, float, bool)) else value
