from __future__ import annotations

from dataclasses import dataclass
from datetime import date


DEFAULT_PRESET_MONTHS = 12
PERIOD_PRESET_OPTIONS = (3, 6, 9, 12, 24, 36)
PRESET_AVAILABILITY_BACKFILL_MONTHS = 3


def month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def shift_month(base: date, offset_months: int) -> date:
    month_index = (base.year * 12 + (base.month - 1)) + offset_months
    year = month_index // 12
    month = (month_index % 12) + 1
    return date(year, month, 1)


def current_default_end_month(today: date | None = None) -> date:
    reference = today or date.today()
    # Informes mensais do mês corrente normalmente ainda não estão disponíveis.
    # Use o último mês fechado como fim padrão da janela móvel.
    return shift_month(month_start(reference), -1)


def month_options(end_month: date, *, months_back: int) -> list[date]:
    start_month = shift_month(end_month, -months_back)
    values: list[date] = []
    current = start_month
    while current <= end_month:
        values.append(current)
        current = shift_month(current, 1)
    return values


def select_decembers_plus_current_year_months(available_months: list[date]) -> list[date]:
    """Return previous Decembers plus all months from the latest available year."""
    normalized = sorted({month_start(value) for value in available_months})
    if not normalized:
        return []
    available = set(normalized)
    reference_year = normalized[-1].year
    previous_decembers = [
        date(year, 12, 1)
        for year in sorted({value.year for value in normalized if value.year < reference_year})
        if date(year, 12, 1) in available
    ]
    current_year_months = [value for value in normalized if value.year == reference_year]
    return previous_decembers + current_year_months


def display_month_count_for_period(period: "ImePeriodSelection") -> int:
    """Return the intended number of displayed months for a period selection."""
    if period.mode == "preset" and period.preset_months is not None:
        months = int(period.preset_months)
        # Annual presets include the same month in the prior year as an anchor
        # for YoY/12M reads. Example: latest mar/26 -> mar/25...mar/26.
        return months + 1 if months >= 12 and months % 12 == 0 else months
    return period.month_count


def load_period_for_available_data(
    period: "ImePeriodSelection",
    *,
    backfill_months: int = PRESET_AVAILABILITY_BACKFILL_MONTHS,
) -> "ImePeriodSelection":
    """Expand preset loads backwards so display windows can anchor to latest available data.

    If the requested end month is not yet published, a strict 12M load such as
    mai/25-abr/26 would only contain 11 valid months through mar/26. Loading a
    small older buffer lets the presentation layer display abr/25-mar/26 while
    keeping the user's requested window unchanged.
    """
    if period.mode != "preset" or backfill_months <= 0:
        return period
    return build_custom_period(
        start_month=shift_month(period.start_month, -int(backfill_months)),
        end_month=period.end_month,
    )


def select_available_months_for_period(
    available_months: list[date],
    period: "ImePeriodSelection",
) -> list[date]:
    """Select display months from available data using the requested period semantics.

    Presets are anchored on the latest available month up to the requested end.
    Custom intervals preserve the explicit start/end boundaries selected by the
    user.
    """
    normalized = sorted({month_start(value) for value in available_months})
    if not normalized:
        return []
    if period.mode == "custom":
        return [value for value in normalized if period.start_month <= value <= period.end_month]
    bounded = [value for value in normalized if value <= period.end_month]
    target = display_month_count_for_period(period)
    return bounded[-target:] if target > 0 else []


def select_competencia_labels_for_period(
    competencias: list[str],
    period: "ImePeriodSelection",
) -> list[str]:
    """Return competencia labels in chronological order for the display window."""
    label_by_month: dict[date, str] = {}
    for label in competencias:
        try:
            parsed = parse_competencia_label(label)
        except Exception:  # noqa: BLE001
            continue
        label_by_month[parsed] = str(label)
    selected_months = select_available_months_for_period(list(label_by_month), period)
    return [label_by_month[month] for month in selected_months if month in label_by_month]


def parse_competencia_label(value: str) -> date:
    month, year = str(value).strip().split("/", 1)
    return date(int(year), int(month), 1)


@dataclass(frozen=True)
class ImePeriodSelection:
    mode: str
    start_month: date
    end_month: date
    preset_months: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_month", month_start(self.start_month))
        object.__setattr__(self, "end_month", month_start(self.end_month))
        if self.start_month > self.end_month:
            raise ValueError("Competência inicial deve ser menor ou igual à competência final.")
        if self.mode not in {"preset", "custom"}:
            raise ValueError("Modo de período inválido.")
        if self.mode == "preset" and self.preset_months not in PERIOD_PRESET_OPTIONS:
            raise ValueError("Preset inválido para o período.")

    @property
    def label(self) -> str:
        return f"{self.start_month.strftime('%m/%Y')} a {self.end_month.strftime('%m/%Y')}"

    @property
    def cache_key(self) -> str:
        return f"{self.start_month.isoformat()}::{self.end_month.isoformat()}"

    @property
    def month_count(self) -> int:
        return ((self.end_month.year - self.start_month.year) * 12) + (self.end_month.month - self.start_month.month) + 1


def build_preset_period(*, end_month: date, months: int) -> ImePeriodSelection:
    if months not in PERIOD_PRESET_OPTIONS:
        raise ValueError("Preset inválido.")
    normalized_end = month_start(end_month)
    start_month = shift_month(normalized_end, -(months - 1))
    return ImePeriodSelection(
        mode="preset",
        start_month=start_month,
        end_month=normalized_end,
        preset_months=months,
    )


def build_custom_period(*, start_month: date, end_month: date) -> ImePeriodSelection:
    return ImePeriodSelection(
        mode="custom",
        start_month=month_start(start_month),
        end_month=month_start(end_month),
        preset_months=None,
    )
