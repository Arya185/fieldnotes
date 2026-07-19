"""CSV raw-content parser."""

from __future__ import annotations

import csv
from collections import Counter

import pandas as pd

from backend.indexer.parsers import ContentSegment, DiscoveredFile, ParsedContent
from backend.models import ColumnProfile, DatasetProfile, OutlierFlag


def parse_csv(file: DiscoveredFile) -> ParsedContent:
    """Read raw CSV rows as strings."""

    with file.path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    profile = build_dataset_profile(file.relative_path, file.path)
    return ParsedContent(
        table_rows=rows,
        segments=[ContentSegment(locator="schema", text=file.relative_path)],
        dataset_profile=profile,
    )


def build_dataset_profile(file_path: str, csv_path) -> DatasetProfile:
    frame = pd.read_csv(csv_path)
    columns = [build_column_profile(frame, column_name) for column_name in frame.columns]
    notes = build_profile_notes(frame)
    return DatasetProfile(
        file_path=file_path,
        row_count=int(len(frame)),
        columns=columns,
        notes=notes,
    )


def build_column_profile(frame: pd.DataFrame, column_name: str) -> ColumnProfile:
    series = frame[column_name]
    null_count = int(series.isna().sum())
    non_null = series.dropna()

    if non_null.empty:
        return ColumnProfile(name=column_name, dtype="string", null_count=null_count)

    if pd.api.types.is_bool_dtype(series):
        return ColumnProfile(
            name=column_name,
            dtype="bool",
            null_count=null_count,
            distinct_count=int(non_null.nunique()),
            top_values=top_values(non_null),
        )

    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        return ColumnProfile(
            name=column_name,
            dtype="int" if pd.api.types.is_integer_dtype(series) else "float",
            null_count=null_count,
            min=float(numeric.min()),
            max=float(numeric.max()),
            mean=float(numeric.mean()),
            std=float(numeric.std(ddof=0)) if len(numeric) > 1 else 0.0,
            outlier_flags=detect_outlier_flags(frame, column_name) or None,
        )

    datetime_series = pd.to_datetime(non_null, errors="coerce")
    if not datetime_series.isna().all():
        return ColumnProfile(
            name=column_name,
            dtype="datetime",
            null_count=null_count,
            distinct_count=int(non_null.nunique()),
            top_values=top_values(non_null),
        )

    return ColumnProfile(
        name=column_name,
        dtype="string",
        null_count=null_count,
        distinct_count=int(non_null.nunique()),
        top_values=top_values(non_null),
    )


def build_profile_notes(frame: pd.DataFrame) -> list[str]:
    notes: list[str] = []
    for column_name in frame.columns:
        series = frame[column_name].dropna()
        if not series.empty and not pd.api.types.is_numeric_dtype(frame[column_name]):
            notes.append(f"{column_name} column has {int(series.nunique())} distinct values")
    return notes


def top_values(series: pd.Series) -> list[str]:
    counts = Counter(str(value) for value in series.tolist())
    return [value for value, _count in counts.most_common(5)]


def detect_outlier_flags(frame: pd.DataFrame, metric_column: str) -> list[OutlierFlag]:
    trial_column = next((name for name in frame.columns if name.lower() == "trial"), None)
    if trial_column is None:
        return []

    if metric_column == trial_column:
        return []

    if not pd.api.types.is_numeric_dtype(frame[metric_column]):
        return []

    grouped = frame.groupby(trial_column, dropna=True)[metric_column].mean(numeric_only=False)
    if len(grouped) < 3:
        return []

    std = float(grouped.std(ddof=0))
    if std == 0:
        return []

    mean = float(grouped.mean())
    flags: list[OutlierFlag] = []
    for group_name, group_value in grouped.items():
        z_score = (float(group_value) - mean) / std
        if abs(z_score) >= 1.5:
            flags.append(
                OutlierFlag(
                    group=f"trial={group_name}",
                    metric=metric_column,
                    z_score=round(z_score, 1),
                )
            )

    return flags
