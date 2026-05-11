from __future__ import annotations

import unittest
from datetime import date, datetime

from services.fidc_model.calendar import (
    build_b3_calendar_snapshot,
    b3_market_holidays_for_dates,
    b3_market_holidays_for_year,
    build_day_counts,
    merge_with_b3_market_holidays,
    networkdays,
    parse_b3_trading_calendar_holidays,
)


HTML_FIXTURE = """
<h2>Market Calendar 2026</h2>
<a href="#jan">January</a>
<tr>
  <td>01</td><td>New Year Day</td><td><img alt="Português"></td>
  <td><p><strong>Listed B3</strong></p><li>There will be no trading on the equity markets.</li></td>
</tr>
<a href="#feb">February</a>
<tr>
  <td>16</td><td>Birthday (President's Day)</td><td><img alt="icon-eua.png"></td>
  <td><p><strong>B3 Foreign Exchange Clearinghouse</strong></p></td>
</tr>
<tr>
  <td>16</td><td>Carnival</td><td><img alt="Português"></td>
  <td><p><strong>Listed B3</strong></p><li>There will be no trading on the equity markets.</li></td>
</tr>
<tr>
  <td>18</td><td>Ash Wednesday - Special trading hours</td><td><img alt="Português"></td>
  <td><p><strong>B3 Listed</strong></p><li>Trading and registration will start at 1:00 p.m.</li></td>
</tr>
<a href="#dec">December</a>
<tr>
  <td>31</td><td>Banks not open to the public but working internally (with no trading session)</td><td>&nbsp;</td>
  <td><p><strong>Listed B3</strong></p><li>There will be no trading on the equity markets.</li></td>
</tr>
"""


class B3CalendarTest(unittest.TestCase):
    def test_parse_b3_trading_calendar_uses_official_rows_only(self):
        parsed = parse_b3_trading_calendar_holidays(HTML_FIXTURE, [2026])

        self.assertEqual(
            {date(2026, 1, 1), date(2026, 2, 16), date(2026, 12, 31)},
            parsed[2026],
        )

    def test_build_calendar_snapshot_projects_unpublished_years(self):
        snapshot = build_b3_calendar_snapshot([date(2026, 1, 1), date(2027, 12, 31)], HTML_FIXTURE)

        self.assertEqual((2026,), snapshot.official_years)
        self.assertEqual((2027,), snapshot.projected_years)
        self.assertIn(date(2026, 2, 16), snapshot.holidays)
        self.assertIn(date(2027, 2, 8), snapshot.holidays)

    def test_projected_2026_market_holidays_include_b3_non_trading_days(self):
        holidays = b3_market_holidays_for_year(2026)

        self.assertIn(date(2026, 2, 16), holidays)
        self.assertIn(date(2026, 2, 17), holidays)
        self.assertIn(date(2026, 4, 3), holidays)
        self.assertIn(date(2026, 6, 4), holidays)
        self.assertIn(date(2026, 11, 20), holidays)
        self.assertIn(date(2026, 12, 24), holidays)
        self.assertIn(date(2026, 12, 31), holidays)
        self.assertNotIn(date(2026, 7, 9), holidays)

    def test_market_holidays_are_generated_for_flow_years(self):
        holidays = b3_market_holidays_for_dates([datetime(2025, 3, 1), datetime(2028, 11, 1)])

        self.assertIn(date(2025, 4, 18), holidays)
        self.assertIn(date(2028, 2, 28), holidays)

    def test_merge_with_b3_market_holidays_keeps_static_and_projects_future(self):
        merged = merge_with_b3_market_holidays([datetime(2018, 12, 31)], [datetime(2026, 1, 1)])

        self.assertIn(date(2018, 12, 31), merged)
        self.assertIn(date(2026, 1, 1), merged)

    def test_build_day_counts_accepts_date_holidays(self):
        datas = [datetime(2026, 4, 1), datetime(2026, 4, 6)]
        _, du = build_day_counts(datas, [date(2026, 4, 3)])

        self.assertEqual([0, 2], du)
        self.assertEqual(3, networkdays(date(2026, 4, 1), date(2026, 4, 6), [date(2026, 4, 3)]))


if __name__ == "__main__":
    unittest.main()
