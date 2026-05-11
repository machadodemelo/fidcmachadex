from __future__ import annotations

from datetime import date
import unittest

from services.ime_period import (
    DEFAULT_PRESET_MONTHS,
    build_custom_period,
    build_preset_period,
    current_default_end_month,
    display_month_count_for_period,
    load_period_for_available_data,
    month_options,
    select_available_months_for_period,
    select_competencia_labels_for_period,
    select_decembers_plus_current_year_months,
)


class ImePeriodTests(unittest.TestCase):
    def test_build_preset_period_is_inclusive(self) -> None:
        period = build_preset_period(end_month=date(2026, 4, 1), months=DEFAULT_PRESET_MONTHS)

        self.assertEqual(date(2025, 5, 1), period.start_month)
        self.assertEqual(date(2026, 4, 1), period.end_month)
        self.assertEqual(12, period.month_count)
        self.assertEqual("05/2025 a 04/2026", period.label)

    def test_build_six_month_preset_keeps_six_competencies(self) -> None:
        period = build_preset_period(end_month=date(2026, 3, 1), months=6)

        self.assertEqual(date(2025, 10, 1), period.start_month)
        self.assertEqual(date(2026, 3, 1), period.end_month)
        self.assertEqual(6, period.month_count)
        self.assertEqual("10/2025 a 03/2026", period.label)

    def test_build_thirty_six_month_preset_is_supported(self) -> None:
        period = build_preset_period(end_month=date(2026, 4, 1), months=36)

        self.assertEqual(date(2023, 5, 1), period.start_month)
        self.assertEqual(date(2026, 4, 1), period.end_month)
        self.assertEqual(36, period.month_count)
        self.assertEqual(37, display_month_count_for_period(period))

    def test_build_custom_period_rejects_inverted_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "Competência inicial"):
            build_custom_period(start_month=date(2026, 5, 1), end_month=date(2026, 4, 1))

    def test_month_options_returns_contiguous_months(self) -> None:
        options = month_options(date(2026, 4, 1), months_back=5)

        self.assertEqual(
            [
                date(2025, 11, 1),
                date(2025, 12, 1),
                date(2026, 1, 1),
                date(2026, 2, 1),
                date(2026, 3, 1),
                date(2026, 4, 1),
            ],
            options,
        )

    def test_current_default_end_month_normalizes_to_first_day(self) -> None:
        self.assertEqual(date(2026, 3, 1), current_default_end_month(date(2026, 4, 14)))

    def test_select_decembers_plus_current_year_months(self) -> None:
        available = month_options(date(2026, 4, 1), months_back=40)

        selected = select_decembers_plus_current_year_months(available)

        self.assertEqual(
            [
                date(2022, 12, 1),
                date(2023, 12, 1),
                date(2024, 12, 1),
                date(2025, 12, 1),
                date(2026, 1, 1),
                date(2026, 2, 1),
                date(2026, 3, 1),
                date(2026, 4, 1),
            ],
            selected,
        )

    def test_select_decembers_plus_current_year_skips_missing_december(self) -> None:
        available = [
            date(2024, 11, 1),
            date(2025, 12, 1),
            date(2026, 1, 1),
            date(2026, 2, 1),
        ]

        selected = select_decembers_plus_current_year_months(available)

        self.assertEqual([date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)], selected)

    def test_load_period_for_available_data_backfills_presets_only(self) -> None:
        preset = build_preset_period(end_month=date(2026, 4, 1), months=12)
        load_period = load_period_for_available_data(preset)

        self.assertEqual(date(2025, 2, 1), load_period.start_month)
        self.assertEqual(date(2026, 4, 1), load_period.end_month)

        custom = build_custom_period(start_month=date(2025, 5, 1), end_month=date(2026, 4, 1))
        self.assertEqual(custom, load_period_for_available_data(custom))

    def test_select_available_months_anchors_presets_to_latest_available(self) -> None:
        period = build_preset_period(end_month=date(2026, 4, 1), months=12)
        available = month_options(date(2026, 3, 1), months_back=15)

        selected = select_available_months_for_period(available, period)

        self.assertEqual(date(2025, 3, 1), selected[0])
        self.assertEqual(date(2026, 3, 1), selected[-1])
        self.assertEqual(13, len(selected))

    def test_select_available_months_anchors_short_presets_to_latest_available(self) -> None:
        period = build_preset_period(end_month=date(2026, 4, 1), months=6)
        available = month_options(date(2026, 3, 1), months_back=8)

        selected = select_available_months_for_period(available, period)

        self.assertEqual(
            [
                date(2025, 10, 1),
                date(2025, 11, 1),
                date(2025, 12, 1),
                date(2026, 1, 1),
                date(2026, 2, 1),
                date(2026, 3, 1),
            ],
            selected,
        )

    def test_select_available_months_keeps_custom_boundaries(self) -> None:
        period = build_custom_period(start_month=date(2025, 5, 1), end_month=date(2026, 4, 1))
        available = month_options(date(2026, 3, 1), months_back=15)

        selected = select_available_months_for_period(available, period)

        self.assertEqual(date(2025, 5, 1), selected[0])
        self.assertEqual(date(2026, 3, 1), selected[-1])
        self.assertEqual(11, len(selected))

    def test_select_competencia_labels_for_period_preserves_chronological_labels(self) -> None:
        period = build_preset_period(end_month=date(2026, 4, 1), months=12)
        labels = [value.strftime("%m/%Y") for value in month_options(date(2026, 3, 1), months_back=15)]

        selected = select_competencia_labels_for_period(labels, period)

        self.assertEqual("03/2025", selected[0])
        self.assertEqual("03/2026", selected[-1])
        self.assertEqual(13, len(selected))


if __name__ == "__main__":
    unittest.main()
