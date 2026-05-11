"""Shared policy for data labels in exported charts.

The functions in this module deliberately do not import presentation or
spreadsheet libraries. They only decide which points should receive labels and
how values should be formatted for display. Exporters remain responsible for
applying the decision to python-pptx/openpyxl chart objects.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Literal, Sequence


ChartKind = Literal["bar", "stacked_bar", "line", "multi_line", "cohort"]
MetricKind = Literal[
    "money",
    "npl_pct",
    "general_pct",
    "coverage_pct",
    "roll_pct",
    "cohort_pct",
    "duration",
    "number",
]

DEFAULT_LABEL_FONT_SIZE_PT = 10


@dataclass(frozen=True)
class ExportLabelPolicy:
    """Decision for data labels in an exported chart."""

    mode: str
    indices_by_series: tuple[tuple[int, ...], ...]
    font_size_pt: int = DEFAULT_LABEL_FONT_SIZE_PT
    reason: str = ""

    @property
    def shows_all_points(self) -> bool:
        return self.mode == "all"

    @property
    def shows_last_points(self) -> bool:
        return self.mode == "last"


def choose_export_label_policy(
    series_values: Sequence[Sequence[object]],
    *,
    chart_kind: ChartKind,
    metric_kind: MetricKind,
) -> ExportLabelPolicy:
    """Choose a label policy based on density and overlap risk.

    The rule is intentionally conservative for slide exports. Labels are shown
    everywhere only when a chart is sparse enough to remain readable at 10 pt.
    """

    values = [_coerce_series(series) for series in series_values]
    series_count = len(values)
    point_count = max((len(series) for series in values), default=0)

    if series_count == 0 or point_count == 0:
        return ExportLabelPolicy(mode="none", indices_by_series=tuple(), reason="sem pontos")

    if chart_kind in {"bar", "stacked_bar"}:
        if point_count <= 8:
            return ExportLabelPolicy(
                mode="all",
                indices_by_series=tuple(_valid_indices(series) for series in values),
                reason="barras com ate 8 periodos",
            )
        if point_count <= 14:
            return ExportLabelPolicy(
                mode="selected",
                indices_by_series=tuple(_selected_bar_indices(series) for series in values),
                reason="barras com densidade media",
            )
        return ExportLabelPolicy(
            mode="last",
            indices_by_series=tuple(_last_index_tuple(series) for series in values),
            reason="barras densas",
        )

    if chart_kind == "cohort":
        return ExportLabelPolicy(
            mode="last",
            indices_by_series=tuple(_last_index_tuple(series) for series in values),
            reason="cohorts multi-serie ficam poluidos com todos os labels",
        )

    if chart_kind in {"line", "multi_line"}:
        if series_count == 1 and point_count <= 8:
            return ExportLabelPolicy(
                mode="all",
                indices_by_series=tuple(_valid_indices(series) for series in values),
                reason="linha unica curta",
            )
        if series_count <= 2 and point_count <= 6 and _series_are_visually_separated(values):
            return ExportLabelPolicy(
                mode="all",
                indices_by_series=tuple(_valid_indices(series) for series in values),
                reason="linhas curtas e separadas",
            )
        return ExportLabelPolicy(
            mode="last",
            indices_by_series=tuple(_last_index_tuple(series) for series in values),
            reason="linha densa ou multi-serie",
        )

    return ExportLabelPolicy(
        mode="last",
        indices_by_series=tuple(_last_index_tuple(series) for series in values),
        reason=f"tipo de grafico {chart_kind}",
    )


def format_export_label(
    value: object,
    *,
    metric_kind: MetricKind,
    percent_value: bool = False,
    decimals: int | None = None,
) -> str:
    """Format one chart label using pt-BR separators.

    ``percent_value=True`` means the chart value is stored as a ratio (0.118)
    and should be shown as 11,8%.
    """

    numeric = _to_float(value)
    if numeric is None:
        return "N/D"

    if metric_kind in {"npl_pct", "general_pct", "coverage_pct", "roll_pct", "cohort_pct"} or percent_value:
        pct = numeric * 100.0 if percent_value else numeric
        places = decimals if decimals is not None else _default_percent_decimals(metric_kind, pct)
        return f"{_format_br(pct, places)}%"

    if metric_kind == "duration":
        places = 1 if decimals is None else decimals
        return _format_br(numeric, places)

    places = 0 if decimals is None else decimals
    return _format_br(numeric, places)


def should_enable_excel_data_labels(policy: ExportLabelPolicy) -> bool:
    """Whether openpyxl should enable chart-level labels.

    openpyxl reliably supports chart-level labels. Point-specific labels are
    more fragile, so dense selected/last-only policies are left without Excel
    labels instead of risking a corrupt workbook.
    """

    return policy.mode == "all"


def _coerce_series(series: Sequence[object]) -> list[float | None]:
    return [_to_float(value) for value in series]


def _valid_indices(series: Sequence[float | None]) -> tuple[int, ...]:
    return tuple(idx for idx, value in enumerate(series) if _is_finite(value))


def _last_index_tuple(series: Sequence[float | None]) -> tuple[int, ...]:
    for idx in range(len(series) - 1, -1, -1):
        if _is_finite(series[idx]):
            return (idx,)
    return tuple()


def _selected_bar_indices(series: Sequence[float | None]) -> tuple[int, ...]:
    valid = [(idx, value) for idx, value in enumerate(series) if _is_finite(value)]
    if not valid:
        return tuple()
    selected = {valid[0][0], valid[-1][0]}
    selected.add(max(valid, key=lambda item: item[1])[0])
    selected.add(min(valid, key=lambda item: item[1])[0])
    return tuple(sorted(selected))


def _series_are_visually_separated(series_values: Sequence[Sequence[float | None]]) -> bool:
    finite_values = [
        value
        for series in series_values
        for value in series
        if _is_finite(value)
    ]
    if len(finite_values) < 2:
        return True
    y_range = max(finite_values) - min(finite_values)
    if y_range <= 0:
        return False
    threshold = y_range * 0.08
    max_len = max((len(series) for series in series_values), default=0)
    for idx in range(max_len):
        point_values = [
            series[idx]
            for series in series_values
            if idx < len(series) and _is_finite(series[idx])
        ]
        if len(point_values) < 2:
            continue
        point_values = sorted(point_values)
        for left, right in zip(point_values, point_values[1:], strict=False):
            if abs(right - left) < threshold:
                return False
    return True


def _default_percent_decimals(metric_kind: MetricKind, pct: float) -> int:
    if metric_kind in {"npl_pct", "roll_pct", "cohort_pct"}:
        return 1
    if metric_kind == "coverage_pct":
        return 0 if abs(pct) >= 100 else 1
    if metric_kind == "general_pct":
        return 0 if abs(pct) >= 10 else 1
    return 1


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _is_finite(value: object) -> bool:
    return _to_float(value) is not None


def _format_br(value: float, decimals: int) -> str:
    return f"{value:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")

