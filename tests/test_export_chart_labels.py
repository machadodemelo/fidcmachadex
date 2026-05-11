import unittest

from services.export_chart_labels import choose_export_label_policy, format_export_label


class ExportChartLabelsTest(unittest.TestCase):
    def test_bar_policy_uses_all_labels_only_when_sparse(self) -> None:
        sparse = choose_export_label_policy([[1, 2, 3]], chart_kind="bar", metric_kind="money")
        self.assertEqual(sparse.mode, "all")
        self.assertEqual(sparse.indices_by_series, ((0, 1, 2),))

        medium = choose_export_label_policy([list(range(12))], chart_kind="bar", metric_kind="money")
        self.assertEqual(medium.mode, "selected")
        self.assertEqual(medium.indices_by_series, ((0, 11),))

    def test_multi_line_policy_uses_last_label_for_dense_series(self) -> None:
        policy = choose_export_label_policy(
            [[0.01, 0.02, 0.03, 0.04], [0.011, 0.021, 0.031, 0.041]],
            chart_kind="multi_line",
            metric_kind="npl_pct",
        )
        self.assertEqual(policy.mode, "last")
        self.assertEqual(policy.indices_by_series, ((3,), (3,)))

    def test_metric_formatting_uses_br_numbers_and_metric_decimals(self) -> None:
        self.assertEqual(format_export_label(0.1184, metric_kind="npl_pct", percent_value=True), "11,8%")
        self.assertEqual(format_export_label(1.78, metric_kind="coverage_pct", percent_value=True), "178%")
        self.assertEqual(format_export_label(7674.9, metric_kind="money"), "7.675")


if __name__ == "__main__":
    unittest.main()

