from __future__ import annotations

import unittest
from datetime import date
from io import BytesIO
from zipfile import ZipFile

from services.fidc_model.b3_curves import (
    B3CurveError,
    fetch_latest_taxaswap_curve,
    parse_taxaswap_archive,
    parse_taxaswap_text,
    taxaswap_download_url,
    taxaswap_filename,
)


def _taxaswap_line(
    *,
    curve_code: str = "PRE",
    generated_at: str = "20250225",
    dc: int,
    du: int,
    rate_percent: float,
    description: str = "DIxPRE",
) -> str:
    sign = "-" if rate_percent < 0 else "+"
    raw_rate = int(round(abs(rate_percent) * 10_000_000))
    return (
        f"{'TSWAPS':<6}"
        f"{'001':<3}"
        f"{'01':<2}"
        f"{generated_at}"
        f"{'T1':<2}"
        f"{curve_code:<5}"
        f"{description:<15}"
        f"{dc:05d}"
        f"{du:05d}"
        f"{sign}"
        f"{raw_rate:014d}"
        f"{'N':<1}"
        f"{du:05d}"
    )


def _nested_taxaswap_zip(text: str) -> bytes:
    inner_buffer = BytesIO()
    with ZipFile(inner_buffer, "w") as inner_zip:
        inner_zip.writestr("TaxaSwap.txt", text)

    outer_buffer = BytesIO()
    with ZipFile(outer_buffer, "w") as outer_zip:
        outer_zip.writestr("TS250225.ex_", inner_buffer.getvalue())
    return outer_buffer.getvalue()


class B3CurvesTest(unittest.TestCase):
    def test_builds_taxaswap_filename_and_url(self):
        self.assertEqual("TS250225.ex_", taxaswap_filename(date(2025, 2, 25)))
        self.assertIn("TS250225.ex_", taxaswap_download_url(date(2025, 2, 25)))

    def test_parse_taxaswap_text_filters_curve_and_converts_rates(self):
        text = "\n".join(
            [
                _taxaswap_line(curve_code="APR", dc=1, du=1, rate_percent=13.0),
                _taxaswap_line(curve_code="PRE", dc=1, du=1, rate_percent=13.15),
                _taxaswap_line(curve_code="PRE", dc=14, du=8, rate_percent=13.365),
            ]
        )

        snapshot = parse_taxaswap_text(text, requested_date=date(2025, 2, 25))

        self.assertEqual("PRE", snapshot.curve_code)
        self.assertEqual(date(2025, 2, 25), snapshot.generated_at)
        self.assertEqual([1.0, 8.0], snapshot.curva_du)
        self.assertAlmostEqual(0.1315, snapshot.curva_taxa_aa[0])
        self.assertAlmostEqual(0.13365, snapshot.curva_taxa_aa[1])
        self.assertEqual(3, snapshot.raw_line_count)

    def test_parse_taxaswap_archive_extracts_nested_exe_zip(self):
        text = "\n".join(
            [
                _taxaswap_line(dc=1, du=1, rate_percent=13.15),
                _taxaswap_line(dc=14, du=8, rate_percent=13.365),
            ]
        )

        snapshot = parse_taxaswap_archive(_nested_taxaswap_zip(text), requested_date=date(2025, 2, 25))

        self.assertEqual(2, len(snapshot.points))
        self.assertEqual(1, snapshot.first_du)
        self.assertEqual(8, snapshot.last_du)
        self.assertEqual(64, len(snapshot.content_sha256))

    def test_parse_taxaswap_archive_rejects_html_response(self):
        with self.assertRaisesRegex(B3CurveError, "não é ZIP"):
            parse_taxaswap_archive(b"<html>erro</html>", requested_date=date(2025, 2, 25))

    def test_parse_taxaswap_text_rejects_wrong_exact_date(self):
        text = "\n".join(
            [
                _taxaswap_line(generated_at="20250224", dc=1, du=1, rate_percent=13.15),
                _taxaswap_line(generated_at="20250224", dc=14, du=8, rate_percent=13.365),
            ]
        )

        with self.assertRaisesRegex(B3CurveError, "data solicitada"):
            parse_taxaswap_text(text, requested_date=date(2025, 2, 25))

    def test_latest_curve_tries_previous_dates_until_success(self):
        calls: list[date] = []

        def fake_fetcher(base_date: date, **_kwargs):
            calls.append(base_date)
            if base_date == date(2025, 2, 23):
                text = "\n".join(
                    [
                        _taxaswap_line(generated_at="20250223", dc=1, du=1, rate_percent=13.15),
                        _taxaswap_line(generated_at="20250223", dc=14, du=8, rate_percent=13.365),
                    ]
                )
                return parse_taxaswap_text(text, requested_date=base_date)
            raise B3CurveError("indisponível")

        snapshot = fetch_latest_taxaswap_curve(
            start_date=date(2025, 2, 25),
            lookback_days=3,
            fetcher=fake_fetcher,
        )

        self.assertEqual(date(2025, 2, 23), snapshot.generated_at)
        self.assertEqual([date(2025, 2, 25), date(2025, 2, 24), date(2025, 2, 23)], calls)


if __name__ == "__main__":
    unittest.main()
