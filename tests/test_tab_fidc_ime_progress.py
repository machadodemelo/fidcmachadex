from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd


def _make_streamlit_stub():
    """Return a minimal streamlit stub that exercises the legacy-compat paths."""

    class _DummyStatusBox:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def caption(self, message: str) -> None:
            self.messages.append(message)

    class _DummyProgress:
        def __init__(self) -> None:
            self.values: list[object] = []

        def progress(self, value):  # noqa: ANN001
            self.values.append(value)

    class _LegacyStreamlitStub:
        """Simulates old Streamlit that does not accept the `text` kwarg in progress()."""

        def __init__(self) -> None:
            self.status_box = _DummyStatusBox()
            self._DummyProgress = _DummyProgress

        def empty(self) -> _DummyStatusBox:
            return self.status_box

        def progress(self, value):  # noqa: ANN001
            bar = _DummyProgress()
            bar.values.append(value)
            return bar

    return _LegacyStreamlitStub()


# Inject a minimal stub for the `streamlit` module so the tab can be imported
# in test environments where Streamlit is not installed.
if "streamlit" not in sys.modules:
    _stub_module = types.ModuleType("streamlit")
    def _cache_data(*_args, **_kwargs):  # noqa: ANN001
        def _decorator(func):  # noqa: ANN001
            return func

        return _decorator

    _stub_module.progress = lambda *a, **kw: None  # type: ignore[attr-defined]
    _stub_module.empty = lambda: None  # type: ignore[attr-defined]
    _stub_module.caption = lambda *a, **kw: None  # type: ignore[attr-defined]
    _stub_module.cache_data = _cache_data  # type: ignore[attr-defined]
    _stub_module.session_state = {}  # type: ignore[attr-defined]
    sys.modules["streamlit"] = _stub_module

from tabs import tab_fidc_ime  # noqa: E402  (import after stub injection)


class TabFidcImeProgressTests(unittest.TestCase):
    def test_init_progress_bar_accepts_legacy_two_arg_call(self) -> None:
        stub = _make_streamlit_stub()
        with patch.object(tab_fidc_ime, "st", stub):
            bar = tab_fidc_ime._init_progress_bar(0.0, "Preparando execução...")

        self.assertIsInstance(bar, stub._DummyProgress)
        self.assertEqual([0.0], bar.values)
        self.assertEqual(["Preparando execução..."], stub.status_box.messages)

    def test_build_failure_report_includes_context(self) -> None:
        context = {"cnpj_informado": "00.000.000/0000-00"}
        report = tab_fidc_ime._build_failure_report(ValueError("entrada inválida"), "tb", context)

        self.assertEqual("Erro de validação de entrada", report["categoria"])
        self.assertEqual(context, report["contexto_execucao"])
        self.assertEqual("tb", report["traceback"])

    def test_safe_json_bytes_handles_non_serializable_values(self) -> None:
        payload = {"quando": datetime(2026, 4, 9, 12, 30)}

        encoded = tab_fidc_ime._safe_json_bytes(payload)

        self.assertIn(b'"quando"', encoded)
        self.assertIn(b"2026-04-09 12:30:00", encoded)

    def test_line_history_chart_accepts_over_chart_frame_without_duplicate_columns(self) -> None:
        chart_df = pd.DataFrame(
            {
                "competencia": ["03/2026", "03/2026", "04/2026", "04/2026"],
                "competencia_dt": pd.to_datetime(["2026-03-01", "2026-03-01", "2026-04-01", "2026-04-01"]),
                "serie": ["Até 30d", "Over 30", "Até 30d", "Over 30"],
                "valor": [4.2, 7.8, 4.5, 8.1],
            }
        )

        chart = tab_fidc_ime._line_history_chart(
            chart_df,
            title=None,
            y_title="%",
            color_range=tab_fidc_ime.OVER_AGING_CHART_COLORS,
            show_point_labels=False,
        )

        spec = chart.to_dict()
        self.assertEqual("line", spec["mark"]["type"])
        self.assertEqual("valor", spec["encoding"]["y"]["field"])

    def test_competencia_axis_sort_uses_real_dates_oldest_first(self) -> None:
        frame = pd.DataFrame(
            {
                "competencia": ["jan-26", "fev-26", "mar-26", "nov-25", "dez-25"],
                "competencia_dt": pd.to_datetime(
                    ["2026-01-01", "2026-02-01", "2026-03-01", "2025-11-01", "2025-12-01"]
                ),
            }
        )

        ordered = tab_fidc_ime._competencia_axis_sort(frame)

        self.assertEqual(["nov-25", "dez-25", "jan-26", "fev-26", "mar-26"], ordered)

    def test_competencia_axis_sort_parses_raw_labels_without_date_column(self) -> None:
        frame = pd.DataFrame({"competencia": ["01/2026", "02/2026", "03/2026", "11/2025", "12/2025"]})

        ordered = tab_fidc_ime._competencia_axis_sort(frame)

        self.assertEqual(["11/2025", "12/2025", "01/2026", "02/2026", "03/2026"], ordered)

    def test_line_history_chart_uses_oldest_first_axis_order(self) -> None:
        chart_df = pd.DataFrame(
            {
                "competencia": ["01/2026", "02/2026", "03/2026", "11/2025", "12/2025"],
                "competencia_dt": pd.to_datetime(
                    ["2026-01-01", "2026-02-01", "2026-03-01", "2025-11-01", "2025-12-01"]
                ),
                "serie": ["Série"] * 5,
                "valor": [1.0, 2.0, 3.0, 4.0, 5.0],
            }
        )

        chart = tab_fidc_ime._line_history_chart(
            chart_df,
            title=None,
            y_title="%",
            show_point_labels=False,
        )

        spec = chart.to_dict()
        self.assertEqual(["nov-25", "dez-25", "jan-26", "fev-26", "mar-26"], spec["encoding"]["x"]["sort"])

    def test_altair_compatible_df_ignores_duplicate_column_slices(self) -> None:
        duplicate_df = pd.DataFrame([["A", "B"], ["C", "D"]], columns=["valor", "valor"])

        converted = tab_fidc_ime._altair_compatible_df(duplicate_df)

        self.assertEqual(["valor", "valor"], list(converted.columns))
        self.assertEqual((2, 2), converted.shape)

    def test_altair_compatible_df_handles_single_row_string_columns(self) -> None:
        frame = pd.DataFrame(
            {
                "competencia": pd.Series(["01/2026"], dtype="string"),
                "serie": pd.Series(["Cobertura"], dtype="string"),
                "valor": [500.0],
            }
        )

        converted = tab_fidc_ime._altair_compatible_df(frame)

        self.assertEqual("object", str(converted["competencia"].dtype))
        self.assertEqual("object", str(converted["serie"].dtype))
        self.assertEqual("01/2026", converted.iloc[0]["competencia"])

    def test_grouped_bar_with_rhs_line_chart_preserves_high_coverage_scale(self) -> None:
        bar_df = pd.DataFrame(
            {
                "competencia": ["01/2026", "01/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "serie": ["Inadimplência", "Provisão"],
                "valor": [10.0, 50.0],
            }
        )
        line_df = pd.DataFrame(
            {
                "competencia": ["01/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01"]),
                "serie": ["Cobertura"],
                "valor": [500.0],
            }
        )

        chart = tab_fidc_ime._grouped_bar_with_rhs_line_chart(
            bar_df,
            line_df,
            title=None,
            bar_y_title="% dos DCs",
            line_y_title="Cobertura (%)",
            reference_value=100.0,
            reference_label="100% (paridade)",
        )

        spec = chart.to_dict()
        rhs_scale = spec["layer"][1]["layer"][1]["encoding"]["y"]["scale"]["domain"]

        line_encoding = spec["layer"][1]["layer"][1]["encoding"]
        self.assertEqual("right", line_encoding["y"]["axis"]["orient"])
        self.assertGreaterEqual(rhs_scale[1], 500.0)
        self.assertEqual("#EC7000", spec["layer"][1]["layer"][1]["mark"]["point"]["fill"])

    def test_grouped_bar_with_rhs_line_chart_supports_full_bar_and_line_labels(self) -> None:
        bar_df = pd.DataFrame(
            {
                "competencia": ["01/2026", "01/2026", "02/2026", "02/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-02-01", "2026-02-01"]),
                "serie": ["Inadimplência", "Provisão", "Inadimplência", "Provisão"],
                "valor": [10.0, 50.0, 12.0, 48.0],
            }
        )
        line_df = pd.DataFrame(
            {
                "competencia": ["01/2026", "02/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-02-01"]),
                "serie": ["Cobertura", "Cobertura"],
                "valor": [500.0, 420.0],
            }
        )

        chart = tab_fidc_ime._grouped_bar_with_rhs_line_chart(
            bar_df,
            line_df,
            title=None,
            bar_y_title="% dos DCs",
            line_y_title="Cobertura (%)",
            reference_value=100.0,
            reference_label="100% (paridade)",
            show_line_end_label=False,
            show_bar_labels=True,
            show_all_line_labels=True,
            bar_label_formatter=tab_fidc_ime._format_percent,
            line_label_formatter=tab_fidc_ime._format_percent,
        )

        spec = chart.to_dict()
        self.assertEqual("text", spec["layer"][0]["layer"][1]["mark"]["type"])
        self.assertEqual("text", spec["layer"][1]["layer"][2]["mark"]["type"])
        self.assertEqual("#EC7000", spec["layer"][1]["layer"][2]["mark"]["color"])

    def test_build_line_series_end_labels_df_uses_value_only_labels(self) -> None:
        chart_df = pd.DataFrame(
            {
                "competencia": ["03/2026", "03/2026"],
                "competencia_dt": pd.to_datetime(["2026-03-01", "2026-03-01"]),
                "serie": ["Over 30", "Over 60"],
                "valor": [12.4, 8.1],
                "label_fmt": ["12,4%", "8,1%"],
            }
        )

        labels_df = tab_fidc_ime._build_line_series_end_labels_df(chart_df, y_title="%")

        self.assertEqual(["8,1%", "12,4%"], labels_df["end_label"].tolist())

    def test_maturity_waterfall_chart_frame_builds_compounding_total(self) -> None:
        maturity_df = pd.DataFrame(
            {
                "ordem": [1, 2, 3],
                "faixa": ["Vencidos", "Em 30 dias", "31 a 60 dias"],
                "valor": [10.0, 20.0, 30.0],
            }
        )

        waterfall_df = tab_fidc_ime._maturity_waterfall_chart_frame(maturity_df)

        self.assertEqual(["Em 30 dias", "31 a 60 dias", "Total"], waterfall_df["etapa"].tolist())
        self.assertEqual([0.0, 20.0, 0.0], waterfall_df["bar_start"].tolist())
        self.assertEqual([20.0, 50.0, 50.0], waterfall_df["bar_end"].tolist())
        self.assertEqual("total", waterfall_df.iloc[-1]["tipo"])

    def test_quota_pl_chart_frame_uses_compact_rounded_labels(self) -> None:
        frame = pd.DataFrame(
            {
                "competencia": ["01/2026", "01/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "label": ["Senior", "Subordinada"],
                "pl": [2_450_000_000.0, 18_400_000.0],
            }
        )

        chart_df = tab_fidc_ime._quota_pl_chart_frame(frame)

        self.assertEqual(["2 bi", "18 mm"], chart_df["label_fmt"].tolist())

    def test_duration_line_chart_renders_labels_for_all_points(self) -> None:
        frame = pd.DataFrame(
            {
                "competencia": ["01/2026", "02/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-02-01"]),
                "duration_days": [80.0, 95.0],
                "total_saldo": [1_000.0, 1_100.0],
                "data_quality": ["ok", "ok"],
            }
        )

        chart = tab_fidc_ime._duration_line_chart(frame)
        spec = chart.to_dict()
        mark_types = [layer["mark"]["type"] for layer in spec["layer"]]

        self.assertEqual(["line", "point", "text"], mark_types)

    def test_stacked_history_bar_chart_can_push_labels_outside_with_visible_legend(self) -> None:
        frame = pd.DataFrame(
            {
                "competencia": ["01/2026", "01/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "serie": ["Até 30", "31-60"],
                "ordem": [1, 2],
                "percentual": [3.2, 0.4],
                "label_fmt": ["3%", "0%"],
            }
        )

        chart = tab_fidc_ime._stacked_history_bar_chart(
            frame,
            title=None,
            y_title="% dos recebíveis",
            value_column="percentual",
            allow_outside_labels=True,
            smart_label_placement=True,
            inner_label_threshold=10_000.0,
            outer_label_threshold=0.05,
        )

        spec = chart.to_dict()

        self.assertEqual(180, spec["padding"]["right"])
        self.assertEqual(
            "Faixas / séries",
            spec["layer"][0]["encoding"]["color"]["legend"]["title"],
        )

    def test_prepare_aging_history_chart_frame_accepts_legacy_percent_column(self) -> None:
        frame = pd.DataFrame(
            {
                "competencia": ["01/2026", "01/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "faixa": ["Até 30 dias", "31 a 60 dias"],
                "ordem": [1, 2],
                "percentual_inadimplencia": [70.0, 30.0],
            }
        )

        prepared = tab_fidc_ime._prepare_aging_history_chart_frame(frame)
        chart = tab_fidc_ime._stacked_history_bar_chart(
            prepared,
            title=None,
            y_title="% da inadimplência",
            value_column="percentual",
            show_segment_labels=False,
        )

        self.assertIn("serie", prepared.columns)
        self.assertIn("percentual", prepared.columns)
        spec = chart.to_dict()
        self.assertEqual("percentual", spec["encoding"]["y"]["field"])

    def test_aging_history_callout_chart_adds_connectors_and_external_latest_labels(self) -> None:
        frame = pd.DataFrame(
            {
                "competencia": ["01/2026", "01/2026", "02/2026", "02/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-02-01", "2026-02-01"]),
                "faixa": ["Até 30 dias", "31 a 60 dias", "Até 30 dias", "31 a 60 dias"],
                "ordem": [1, 2, 1, 2],
                "valor": [70.0, 30.0, 65.0, 35.0],
                "percentual_inadimplencia": [70.0, 30.0, 65.0, 35.0],
                "percentual_direitos_creditorios": [7.0, 3.0, 6.5, 3.5],
            }
        )

        prepared = tab_fidc_ime._prepare_aging_history_chart_frame(frame)
        chart = tab_fidc_ime._aging_history_callout_chart(prepared, title=None, height=420, bar_size=80)
        spec = chart.to_dict()

        self.assertEqual(4, len(spec["layer"]))
        self.assertEqual("bar", spec["layer"][0]["mark"]["type"])
        self.assertEqual("line", spec["layer"][1]["mark"]["type"])
        self.assertEqual("text", spec["layer"][3]["mark"]["type"])
        self.assertEqual("label_slot", spec["layer"][3]["encoding"]["x"]["field"])
        self.assertEqual(14, spec["layer"][3]["mark"]["fontSize"])
        self.assertEqual(248, spec["padding"]["right"])
        x_domain = spec["layer"][0]["encoding"]["x"]["scale"]["domain"]
        self.assertEqual(["jan-26", "fev-26", ""], x_domain)
        datasets = spec.get("datasets", {})
        connector_dataset = spec["layer"][1]["data"]["name"]
        connector_points = datasets[connector_dataset]
        self.assertEqual({"fev-26", ""}, {row["competencia_plot"] for row in connector_points})

    def test_stacked_history_bar_chart_can_hide_segment_labels_and_keep_totals(self) -> None:
        frame = pd.DataFrame(
            {
                "competencia": ["01/2026", "01/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "serie": ["Senior", "Subordinada"],
                "ordem": [1, 2],
                "valor": [700.0, 100.0],
            }
        )

        chart = tab_fidc_ime._stacked_history_bar_chart(
            frame,
            title=None,
            y_title="R$",
            value_column="valor",
            show_total_labels=True,
            show_segment_labels=False,
        )
        spec = chart.to_dict()

        self.assertEqual(2, len(spec["layer"]))
        self.assertEqual("bar", spec["layer"][0]["mark"]["type"])
        self.assertEqual("text", spec["layer"][1]["mark"]["type"])

    def test_format_aging_latest_table_exposes_value_and_percent_columns(self) -> None:
        frame = pd.DataFrame(
            {
                "ordem": [1, 2],
                "faixa": ["Até 30 dias", "31 a 60 dias"],
                "valor": [150.0, 50.0],
                "percentual_inadimplencia": [75.0, 25.0],
                "percentual_direitos_creditorios": [3.5, 1.2],
            }
        )

        formatted = tab_fidc_ime._format_aging_latest_table(frame)

        self.assertEqual(["Faixa", "Valor", "% da inadimplência", "% dos DCs"], formatted.columns.tolist())
        self.assertEqual("Até 30 dias", formatted.iloc[0]["Faixa"])
        self.assertTrue(formatted.iloc[0]["Valor"].startswith("R$"))
        self.assertEqual("75,00%", formatted.iloc[0]["% da inadimplência"])
        self.assertEqual("3,50%", formatted.iloc[0]["% dos DCs"])

    def test_return_base100_chart_frame_starts_first_month_at_100(self) -> None:
        frame = pd.DataFrame(
            {
                "competencia": ["01/2026", "02/2026", "03/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
                "class_label": ["Sênior", "Sênior", "Sênior"],
                "retorno_mensal_pct": [5.0, 10.0, -5.0],
            }
        )

        chart_df = tab_fidc_ime._return_base100_chart_frame(frame, selected_labels=["Sênior"], months=12)

        self.assertEqual([100.0, 110.0, 104.5], [round(value, 1) for value in chart_df["valor"].tolist()])

    def test_format_return_inline_matrix_frame_compacts_last_12_months_ytd_and_12m(self) -> None:
        history = pd.DataFrame(
            {
                "competencia": ["01/2026", "02/2026", "01/2026", "02/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-01-01", "2026-02-01"]),
                "class_label": ["Sênior", "Sênior", "Subordinada", "Subordinada"],
                "retorno_mensal_pct": [1.25, 1.50, 2.0, 2.5],
            }
        )
        summary = pd.DataFrame(
            {
                "class_label": ["Sênior", "Subordinada"],
                "retorno_mes_pct": [1.50, 2.5],
                "retorno_ano_pct": [2.75, 4.5],
                "retorno_12m_pct": [14.0, 21.0],
            }
        )

        formatted = tab_fidc_ime._format_return_inline_matrix_frame(history, summary, months=12)

        self.assertEqual(["Classe", "fev-26", "jan-26", "YTD", "12 meses"], formatted.columns.tolist())
        senior_row = formatted[formatted["Classe"] == "Sênior"].iloc[0]
        subordinada_row = formatted[formatted["Classe"] == "Subordinada"].iloc[0]
        self.assertEqual("1,25%", senior_row["jan-26"])
        self.assertEqual("1,50%", senior_row["fev-26"])
        self.assertEqual("2,75%", senior_row["YTD"])
        self.assertEqual("21,00%", subordinada_row["12 meses"])

    def test_build_dashboard_context_items_keeps_only_competencia_and_janela(self) -> None:
        dashboard = SimpleNamespace(
            fund_info={
                "ultima_competencia": "02/2026",
                "periodo_analisado": "01/2026 a 02/2026",
                "ultima_entrega": "2026-03-14",
            },
            competencias=["01/2026", "02/2026"],
        )

        items = tab_fidc_ime._build_dashboard_context_items(dashboard)

        self.assertEqual(
            [("Últ. competência", "fev-26"), ("Janela", "jan-26 a fev-26")],
            items,
        )

    def test_format_cnpj_recovers_decimalized_identifier(self) -> None:
        self.assertEqual("36.113.876/0001-91", tab_fidc_ime._format_cnpj("36113876000191.0"))
        self.assertEqual("08.417.544/0001-65", tab_fidc_ime._format_cnpj("8417544000165.0"))

    def test_stacked_history_bar_chart_can_limit_labels_per_competencia(self) -> None:
        frame = pd.DataFrame(
            {
                "competencia": ["01/2026", "01/2026", "01/2026"],
                "competencia_dt": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-01"]),
                "serie": ["A", "B", "C"],
                "ordem": [1, 2, 3],
                "percentual": [10.0, 7.0, 1.0],
                "label_fmt": ["10%", "7%", "1%"],
            }
        )

        chart = tab_fidc_ime._stacked_history_bar_chart(
            frame,
            title=None,
            y_title="% da inadimplência",
            value_column="percentual",
            show_segment_labels=True,
            smart_label_placement=True,
            max_segment_labels_per_competencia=2,
        )

        spec = chart.to_dict()
        label_dataset_name = spec["layer"][1]["data"]["name"]
        label_rows = spec["datasets"][label_dataset_name]
        label_values = [row["label_fmt"] for row in label_rows]

        self.assertEqual(["10%", "7%"], label_values)


if __name__ == "__main__":
    unittest.main()
