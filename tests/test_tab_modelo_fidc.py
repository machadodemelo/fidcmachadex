from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest

import pandas as pd

from data_loader import load_model_inputs
from tabs import tab_modelo_fidc


class TabModeloFidcTests(unittest.TestCase):
    def test_brl_input_value_uses_brazilian_currency_format(self) -> None:
        self.assertEqual("R$ 125.000.000,00", tab_modelo_fidc._format_brl_input_value(125_000_000.0))

    def test_percent_input_value_uses_visible_percent_suffix(self) -> None:
        self.assertEqual("70,0%", tab_modelo_fidc._format_percent_input_value(70.0, decimals=1))
        self.assertEqual("15,22%", tab_modelo_fidc._format_percent_input_value(15.22, decimals=2))

    def test_parse_br_number_accepts_currency_and_percent_suffixes(self) -> None:
        self.assertEqual(1_234_567.89, tab_modelo_fidc._parse_br_number("R$ 1.234.567,89", field_name="x"))
        self.assertEqual(15.22, tab_modelo_fidc._parse_br_number("15,22%", field_name="x"))

    def test_raw_inputs_are_formatted_after_submit_callback(self) -> None:
        self.assertEqual("4,00%", tab_modelo_fidc._format_raw_input_text("4", decimals=2, kind="percent"))
        self.assertEqual("R$ 4,00", tab_modelo_fidc._format_raw_input_text("4", decimals=2, kind="brl"))
        self.assertEqual("30", tab_modelo_fidc._format_raw_input_text("30", decimals=0, kind="number"))

    def test_model_tooltip_html_exposes_explanation_for_css_and_accessibility(self) -> None:
        html = tab_modelo_fidc._model_tooltip_html('Duration "econômica" da SEN')

        self.assertIn('data-tooltip="Duration &quot;econômica&quot; da SEN"', html)
        self.assertIn('title="Duration &quot;econômica&quot; da SEN"', html)
        self.assertIn('aria-label="Duration &quot;econômica&quot; da SEN"', html)
        self.assertIn('tabindex="0"', html)

    def test_requested_page_defaults_are_encoded(self) -> None:
        self.assertEqual(750_000_000.0, tab_modelo_fidc.DEFAULT_VOLUME_CARTEIRA)
        self.assertEqual(0.04, tab_modelo_fidc.DEFAULT_TX_CESSAO_AM)
        self.assertEqual(0.0, tab_modelo_fidc.DEFAULT_PERDA_ESPERADA_AM)
        self.assertEqual(0.0, tab_modelo_fidc.DEFAULT_PERDA_INESPERADA_AM)
        self.assertEqual(0.0, tab_modelo_fidc.DEFAULT_AGIO_AQUISICAO)
        self.assertEqual(0.0, tab_modelo_fidc.DEFAULT_EXCESSO_SPREAD_SENIOR_AM)
        self.assertEqual(0.75, tab_modelo_fidc.DEFAULT_PROP_SENIOR)
        self.assertEqual(0.15, tab_modelo_fidc.DEFAULT_PROP_MEZZ)
        self.assertEqual(0.10, tab_modelo_fidc.DEFAULT_PROP_SUB)
        self.assertEqual(0.0135, tab_modelo_fidc.DEFAULT_TAXA_SENIOR)
        self.assertEqual(0.05, tab_modelo_fidc.DEFAULT_TAXA_MEZZ)
        self.assertEqual(30.0, tab_modelo_fidc.DEFAULT_CARENCIA_PRINCIPAL_MESES)
        self.assertEqual(0.13, tab_modelo_fidc.DEFAULT_SELIC_AA_2026)
        self.assertEqual(0.12, tab_modelo_fidc.DEFAULT_SELIC_AA_2027_ONWARD)
        self.assertEqual(2028, tab_modelo_fidc.DEFAULT_SELIC_PERPETUAL_YEAR)

    def test_admin_cost_help_text_matches_backend_basis(self) -> None:
        self.assertIn("PL econômico", tab_modelo_fidc.HELP_CUSTO_ADM_GESTAO)
        self.assertIn("início do período", tab_modelo_fidc.HELP_CUSTO_ADM_GESTAO)
        self.assertIn("custo mínimo mensal", tab_modelo_fidc.HELP_CUSTO_ADM_GESTAO)
        self.assertIn("R$/mês", tab_modelo_fidc.HELP_CUSTO_MINIMO)
        self.assertIn("maior valor", tab_modelo_fidc.HELP_CUSTO_MINIMO)

    def test_projection_years_start_at_2026_and_exclude_2025(self) -> None:
        years = tab_modelo_fidc._projection_years_for_term(pd.Timestamp("2025-03-01").to_pydatetime(), 10.0)

        self.assertNotIn(2025, years)
        self.assertEqual([2026, 2027, 2028], years)
        self.assertEqual("2028 em diante", tab_modelo_fidc._selic_year_label(2028, years))

    def test_effective_selic_projection_perpetuates_last_year_after_2028(self) -> None:
        projection = ((2026, 0.13), (2027, 0.12), (2028, 0.12))
        simulation_dates = [
            pd.Timestamp("2026-04-28").to_pydatetime(),
            pd.Timestamp("2029-04-28").to_pydatetime(),
            pd.Timestamp("2031-04-28").to_pydatetime(),
        ]

        effective = dict(tab_modelo_fidc._effective_selic_projection_for_dates(projection, simulation_dates))

        self.assertEqual(0.12, effective[2029])
        self.assertEqual(0.12, effective[2031])

    def test_workbook_schedule_shifts_to_dynamic_start_date(self) -> None:
        inputs = load_model_inputs("model_data.json")
        shifted = tab_modelo_fidc._build_simulation_dates(
            inputs,
            tab_modelo_fidc.DATE_SCHEDULE_WORKBOOK,
            3.0,
            pd.Timestamp("2026-04-28").to_pydatetime(),
        )

        self.assertEqual(pd.Timestamp("2026-04-28").to_pydatetime(), shifted[0])
        self.assertEqual(pd.Timestamp("2026-10-28").to_pydatetime(), shifted[1])
        self.assertEqual(pd.Timestamp("2029-12-28").to_pydatetime(), shifted[-1])

    def test_acquisition_premium_reduces_effective_cession_discount(self) -> None:
        effective = tab_modelo_fidc._effective_cession_discount_after_premium(0.05, 0.01)
        monthly = tab_modelo_fidc.cession_discount_to_monthly_rate(effective, 1.0)

        self.assertAlmostEqual(0.04, effective)
        self.assertAlmostEqual((1.0 / 0.96) - 1.0, monthly)

    def test_workbook_mechanics_expander_explains_cash_lock_and_sheet_formulas(self) -> None:
        selected_curve = tab_modelo_fidc._SelectedCurve(
            source_label=tab_modelo_fidc.CURVE_SOURCE_B3_LATEST,
            curve_code="PRE",
            base_date=date(2026, 4, 27),
            curva_du=(1.0, 21.0),
            curva_taxa_aa=(0.13, 0.14),
            source_url="https://example.test/TS260427.ex_",
            retrieved_label="28/04/2026 19:00:00 UTC",
            content_sha256="abc123",
            point_count=2,
            first_du=1,
            last_du=21,
        )
        selected_calendar = tab_modelo_fidc._SelectedCalendar(
            source_label=tab_modelo_fidc.CALENDAR_SOURCE_B3_OFFICIAL,
            feriados=(date(2026, 1, 1),),
            holiday_count=1,
            first_holiday=date(2026, 1, 1),
            last_holiday=date(2026, 1, 1),
            official_years=(2026,),
            projected_years=(2027,),
        )

        markdown = tab_modelo_fidc._build_workbook_mechanics_markdown(
            selected_curve=selected_curve,
            selected_calendar=selected_calendar,
            interpolation_label=tab_modelo_fidc.INTERPOLATION_LABEL_B3,
            taxa_cessao_input_mode=tab_modelo_fidc.CESSION_INPUT_MONTHLY,
        )

        self.assertIn("trava de caixa está desligada", markdown)
        self.assertIn("Metodologias de crédito, NPL e provisão", markdown)
        self.assertIn("provisao_minima = estoque_npl90_t", markdown)
        self.assertIn("principal inadimplente projetado", markdown)
        self.assertIn("writeoff_descoberto", markdown)
        self.assertIn("carteira_originada_efetiva = volume_inicial", markdown)
        self.assertIn("Migração por faixas de atraso", markdown)
        self.assertIn("ECL forward-looking", markdown)
        self.assertIn("13,00% a.a.", markdown)
        self.assertIn("12,00% a.a.", markdown)
        self.assertIn("Backlog Fase 2", markdown)
        self.assertIn("PMT SEN = juros SEN + principal SEN programado", markdown)
        self.assertIn("SUB residual = PL FIDC - PL SEN - PL MEZZ", markdown)
        self.assertIn("taxa_selic_periodo = (1 + selic_aa_do_ano)", markdown)
        self.assertIn("rendimento_caixa_selic", markdown)

    def test_step_by_step_explains_projected_cash_accounting(self) -> None:
        markdown = tab_modelo_fidc._build_step_by_step_markdown()

        self.assertIn("livro-caixa econômico simplificado", markdown)
        self.assertIn("principal inadimplente projetado", markdown)
        self.assertIn("não** é reinvestida", markdown)
        self.assertIn("Carteira originada efetiva", markdown)
        self.assertIn("timeline detalhada é a memória de cálculo", markdown)

    def test_revolvency_metrics_compare_sub_final_to_originated_portfolio(self) -> None:
        class Result:
            pl_sub_jr = 2_400_000_000.0

        premissas = tab_modelo_fidc.Premissas(
            volume=750_000_000.0,
            tx_cessao_am=0.0,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=0.75,
            taxa_senior=0.0,
            proporcao_mezz=0.15,
            taxa_mezz=0.0,
            proporcao_subordinada=0.10,
            prazo_fidc_anos=3.0,
            prazo_medio_recebiveis_meses=6.0,
            lgd=0.8,
        )

        metrics = tab_modelo_fidc._build_revolvency_metrics(
            premissas=premissas,
            zero_default_results=[Result()],
            portfolio_mode=tab_modelo_fidc.PORTFOLIO_MODE_REVOLVING,
            calibrated_loss_cycle=0.05,
        )

        self.assertEqual(6.0, metrics.giro_estimado)
        self.assertEqual(4_500_000_000.0, metrics.carteira_total_originada)
        self.assertAlmostEqual(2_400_000_000.0 / 4_500_000_000.0, metrics.colchao_sem_perdas_sobre_originacao)
        self.assertEqual(750_000_000.0, metrics.ead_maximo)
        self.assertEqual(750_000_000.0, metrics.ead_medio_ponderado)
        self.assertAlmostEqual((1.05**2) - 1.0, metrics.perda_ciclo_calibrada_anual_equivalente)
        self.assertAlmostEqual(0.04, metrics.perda_ciclo_calibrada_pos_lgd)

    def test_revolvency_metrics_reconcile_with_effective_motor_origination(self) -> None:
        premissas = tab_modelo_fidc.Premissas(
            volume=1_000.0,
            tx_cessao_am=0.0,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=0.75,
            taxa_senior=0.0,
            proporcao_mezz=0.15,
            taxa_mezz=0.0,
            proporcao_subordinada=0.10,
            prazo_fidc_anos=3.0,
            prazo_medio_recebiveis_meses=6.0,
            lgd=1.0,
        )
        periods = [
            SimpleNamespace(pl_sub_jr=100.0, carteira=1_000.0, delta_dc=0.0),
            SimpleNamespace(
                pl_sub_jr=120.0,
                carteira=1_000.0,
                delta_dc=30.0,
                reinvestimento_principal=100.0,
                reinvestimento_excesso=50.0,
                nova_originacao=150.0,
            ),
            SimpleNamespace(
                pl_sub_jr=140.0,
                carteira=1_150.0,
                delta_dc=30.0,
                reinvestimento_principal=110.0,
                reinvestimento_excesso=60.0,
                nova_originacao=170.0,
            ),
        ]

        metrics = tab_modelo_fidc._build_revolvency_metrics(
            premissas=premissas,
            zero_default_results=periods,
            portfolio_mode=tab_modelo_fidc.PORTFOLIO_MODE_REVOLVING,
        )

        self.assertAlmostEqual(6_000.0, metrics.carteira_originada_programatica)
        self.assertAlmostEqual(210.0, metrics.reinvestimento_principal_total)
        self.assertAlmostEqual(110.0, metrics.reinvestimento_excesso_total)
        self.assertAlmostEqual(320.0, metrics.nova_originacao_total)
        self.assertAlmostEqual(1_320.0, metrics.carteira_total_originada)
        self.assertAlmostEqual(140.0 / 1_320.0, metrics.colchao_sem_perdas_sobre_originacao)

        export = tab_modelo_fidc._build_revolvency_export_dataframe(metrics)
        exported_values = dict(zip(export["Indicador"], export["Valor"]))
        self.assertAlmostEqual(metrics.carteira_total_originada, exported_values["Carteira originada efetiva"])
        self.assertAlmostEqual(metrics.reinvestimento_excesso_total, exported_values["Reinvestimento de excesso de spread"])

    def test_calibrated_loss_cycle_solver_finds_loss_that_exhausts_sub(self) -> None:
        dates = [pd.Timestamp(2026, 1, 1) + pd.DateOffset(months=month) for month in range(13)]
        datas = [date.to_pydatetime() for date in dates]
        premissas = tab_modelo_fidc.Premissas(
            volume=1_000.0,
            tx_cessao_am=0.0,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=0.0,
            taxa_senior=0.0,
            proporcao_mezz=0.0,
            taxa_mezz=0.0,
            proporcao_subordinada=1.0,
            tipo_taxa_senior=tab_modelo_fidc.RATE_MODE_PRE,
            tipo_taxa_mezz=tab_modelo_fidc.RATE_MODE_PRE,
            prazo_fidc_anos=1.0,
            prazo_medio_recebiveis_meses=6.0,
            carteira_revolvente=True,
            modelo_credito=tab_modelo_fidc.CREDIT_MODEL_NPL90,
            npl90_lag_meses=0,
            cobertura_minima_npl90=1.0,
            lgd=1.0,
        )

        perda_ciclo, exceeded = tab_modelo_fidc._solve_calibrated_loss_cycle(
            datas=datas,
            feriados=[],
            curva_du=[1.0, 2000.0],
            curva_taxa_aa=[0.0, 0.0],
            premissas=premissas,
            interpolation_method=tab_modelo_fidc.INTERPOLATION_METHOD_FLAT_FORWARD_252,
        )

        self.assertFalse(exceeded)
        self.assertIsNotNone(perda_ciclo)
        self.assertGreater(perda_ciclo, 0.0)
        self.assertLess(perda_ciclo, 1.0)
        final_sub = tab_modelo_fidc._final_sub_for_loss_cycle(
            datas=datas,
            feriados=[],
            curva_du=[1.0, 2000.0],
            curva_taxa_aa=[0.0, 0.0],
            premissas=premissas,
            interpolation_method=tab_modelo_fidc.INTERPOLATION_METHOD_FLAT_FORWARD_252,
            perda_ciclo=perda_ciclo,
        )
        self.assertAlmostEqual(0.0, final_sub, delta=1.0)

    def test_reference_monthly_scenario_uses_additive_cdi_spread_outputs(self) -> None:
        inputs = load_model_inputs("model_data.json")
        datas = tab_modelo_fidc._build_monthly_dates(inputs.datas[0], 3.0)
        selected_calendar = tab_modelo_fidc._selected_calendar(
            inputs,
            tab_modelo_fidc.CALENDAR_SOURCE_B3_PROJECTED,
            datas=datas,
        )
        selected_curve = tab_modelo_fidc._selected_curve_from_snapshot(inputs)
        premissas = tab_modelo_fidc.Premissas(
            volume=750_000_000.0,
            tx_cessao_am=0.04,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0035,
            custo_min=20_000.0,
            inadimplencia=0.0,
            proporcao_senior=0.75,
            taxa_senior=0.0135,
            proporcao_mezz=0.15,
            taxa_mezz=0.05,
            proporcao_subordinada=0.10,
            tipo_taxa_senior=tab_modelo_fidc.RATE_MODE_POST_CDI,
            tipo_taxa_mezz=tab_modelo_fidc.RATE_MODE_POST_CDI,
            carteira_revolvente=True,
            prazo_fidc_anos=3.0,
            prazo_medio_recebiveis_meses=6.0,
            prazo_senior_anos=3.0,
            prazo_mezz_anos=3.0,
            amortizacao_senior=tab_modelo_fidc.AMORTIZATION_MODE_LINEAR,
            amortizacao_mezz=tab_modelo_fidc.AMORTIZATION_MODE_LINEAR,
            juros_senior=tab_modelo_fidc.INTEREST_PAYMENT_MODE_PERIODIC,
            juros_mezz=tab_modelo_fidc.INTEREST_PAYMENT_MODE_PERIODIC,
            inicio_amortizacao_senior_meses=30,
            inicio_amortizacao_mezz_meses=30,
            modelo_credito=tab_modelo_fidc.CREDIT_MODEL_NPL90,
            perda_ciclo=0.0,
            npl90_lag_meses=3,
            cobertura_minima_npl90=1.0,
            lgd=1.0,
        )

        periods = tab_modelo_fidc.build_flow(
            datas,
            selected_calendar.feriados,
            selected_curve.curva_du,
            selected_curve.curva_taxa_aa,
            premissas,
            interpolation_method=tab_modelo_fidc.INTERPOLATION_METHOD_FLAT_FORWARD_252,
        )
        kpis = tab_modelo_fidc.build_kpis(periods)
        loss_cycle, exceeded = tab_modelo_fidc._solve_calibrated_loss_cycle(
            datas=datas,
            feriados=selected_calendar.feriados,
            curva_du=selected_curve.curva_du,
            curva_taxa_aa=selected_curve.curva_taxa_aa,
            premissas=premissas,
            interpolation_method=tab_modelo_fidc.INTERPOLATION_METHOD_FLAT_FORWARD_252,
        )

        self.assertAlmostEqual(0.1481403471878306, periods[1].taxa_senior)
        self.assertAlmostEqual(0.18464034718783057, periods[1].taxa_mezz)
        self.assertAlmostEqual(0.15463403302424067, kpis.xirr_senior)
        self.assertAlmostEqual(0.19047218455885997, kpis.xirr_mezz)
        self.assertAlmostEqual(1_495_454_499.5443125, periods[-1].pl_sub_jr, delta=1.0)
        self.assertFalse(exceeded)
        self.assertAlmostEqual(0.16382598876953125, loss_cycle)

    def test_time_protection_uses_monthly_revolving_origination(self) -> None:
        premissas = tab_modelo_fidc.Premissas(
            volume=750_000_000.0,
            tx_cessao_am=0.0,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=0.75,
            taxa_senior=0.0,
            proporcao_mezz=0.15,
            taxa_mezz=0.0,
            proporcao_subordinada=0.10,
            prazo_fidc_anos=3.0,
            prazo_medio_recebiveis_meses=6.0,
        )
        frame = pd.DataFrame(
            {
                "indice": [0, 1, 6, 36],
                "data": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-07-01", "2029-01-01"]),
                "pl_sub_jr": [75_000_000.0, 75_000_000.0, 75_000_000.0, 75_000_000.0],
                "fluxo_remanescente_mezz": [0.0, 10_000_000.0, 20_000_000.0, 30_000_000.0],
            }
        )

        protection = tab_modelo_fidc._build_time_protection_frame(
            frame,
            premissas=premissas,
            portfolio_mode=tab_modelo_fidc.PORTFOLIO_MODE_REVOLVING,
            scenario_label="Cenário",
        )

        self.assertEqual([1, 6, 36], protection["indice"].tolist())
        self.assertAlmostEqual(750_000_000.0, protection.iloc[0]["carteira_inicial_considerada"])
        self.assertAlmostEqual(125_000_000.0, protection.iloc[0]["nova_originacao_estimada"])
        self.assertAlmostEqual(875_000_000.0, protection.iloc[0]["carteira_originada_acumulada"])
        self.assertAlmostEqual(1_500_000_000.0, protection.iloc[1]["carteira_originada_acumulada"])
        self.assertAlmostEqual(4_500_000_000.0, protection.iloc[2]["carteira_originada_acumulada"])
        self.assertAlmostEqual(10_000_000.0, protection.iloc[0]["residual_economico_fluxo"])
        self.assertAlmostEqual(75_000_000.0 / 875_000_000.0, protection.iloc[0]["perda_maxima_suportada"])
        self.assertAlmostEqual(0.05, protection.iloc[1]["perda_maxima_suportada"])

    def test_time_protection_denominator_includes_initial_portfolio_in_first_month(self) -> None:
        premissas = tab_modelo_fidc.Premissas(
            volume=1_000_000_000.0,
            tx_cessao_am=0.0,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=0.90,
            taxa_senior=0.0,
            proporcao_mezz=0.0,
            taxa_mezz=0.0,
            proporcao_subordinada=0.10,
            prazo_fidc_anos=3.0,
            prazo_medio_recebiveis_meses=6.0,
        )
        frame = pd.DataFrame(
            {
                "indice": [1],
                "data": pd.to_datetime(["2026-02-01"]),
                "pl_sub_jr": [100_000_000.0],
                "fluxo_remanescente_mezz": [0.0],
            }
        )

        protection = tab_modelo_fidc._build_time_protection_frame(
            frame,
            premissas=premissas,
            portfolio_mode=tab_modelo_fidc.PORTFOLIO_MODE_REVOLVING,
            scenario_label="Cenário",
        )

        self.assertAlmostEqual(1_000_000_000.0, protection.iloc[0]["carteira_inicial_considerada"])
        self.assertAlmostEqual(166_666_666.66666666, protection.iloc[0]["nova_originacao_estimada"])
        self.assertAlmostEqual(1_166_666_666.6666667, protection.iloc[0]["carteira_originada_acumulada"])
        self.assertAlmostEqual(100_000_000.0 / 1_166_666_666.6666667, protection.iloc[0]["perda_maxima_suportada"])

    def test_time_protection_uses_actual_motor_origination_when_available(self) -> None:
        premissas = tab_modelo_fidc.Premissas(
            volume=1_000.0,
            tx_cessao_am=0.0,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=0.90,
            taxa_senior=0.0,
            proporcao_mezz=0.0,
            taxa_mezz=0.0,
            proporcao_subordinada=0.10,
            prazo_fidc_anos=3.0,
            prazo_medio_recebiveis_meses=6.0,
        )
        frame = pd.DataFrame(
            {
                "indice": [0, 1, 2],
                "data": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
                "pl_sub_jr": [100.0, 120.0, 150.0],
                "nova_originacao": [0.0, 220.0, 330.0],
                "fluxo_remanescente_mezz": [0.0, 20.0, 30.0],
            }
        )

        protection = tab_modelo_fidc._build_time_protection_frame(
            frame,
            premissas=premissas,
            portfolio_mode=tab_modelo_fidc.PORTFOLIO_MODE_REVOLVING,
            scenario_label="Cenário",
        )

        self.assertEqual([1, 2], protection["indice"].tolist())
        self.assertAlmostEqual(220.0, protection.iloc[0]["nova_originacao_estimada"])
        self.assertAlmostEqual(220.0, protection.iloc[0]["nova_originacao_acumulada"])
        self.assertAlmostEqual(1_220.0, protection.iloc[0]["carteira_originada_acumulada"])
        self.assertAlmostEqual(220.0, protection.iloc[0]["nova_originacao_motor"])
        self.assertAlmostEqual(550.0, protection.iloc[1]["nova_originacao_acumulada"])
        self.assertAlmostEqual(1_550.0, protection.iloc[1]["carteira_originada_acumulada"])
        self.assertAlmostEqual(330.0, protection.iloc[1]["nova_originacao_motor"])

    def test_model_charts_are_filled_area_charts(self) -> None:
        frame = pd.DataFrame(
            {
                "indice": [0, 1],
                "data": pd.to_datetime(["2026-01-01", "2026-02-01"]),
                "pl_senior": [75.0, 65.0],
                "pl_mezz": [15.0, 10.0],
                "pl_sub_jr": [10.0, 25.0],
            }
        )
        chart_df = tab_modelo_fidc._build_balance_area_frame(frame)

        chart = tab_modelo_fidc._area_money_chart(chart_df)
        spec = chart.to_dict()

        self.assertEqual("area", spec["layer"][0]["mark"]["type"])
        self.assertEqual("line", spec["layer"][1]["mark"]["type"])
        self.assertEqual("Mês do FIDC", spec["layer"][0]["encoding"]["x"]["title"])
        self.assertEqual("stack_top_milhoes", spec["layer"][0]["encoding"]["y"]["field"])
        self.assertEqual("stack_base_milhoes", spec["layer"][0]["encoding"]["y2"]["field"])

    def test_balance_chart_uses_current_sub_residual_and_separates_deficit(self) -> None:
        frame = pd.DataFrame(
            {
                "indice": [0],
                "data": pd.to_datetime(["2026-01-01"]),
                "pl_senior": [75.0],
                "pl_mezz": [15.0],
                "pl_sub_jr": [-12.0],
                "pl_sub_jr_modelo": [-80.0],
            }
        )

        chart_df = tab_modelo_fidc._build_balance_area_frame(frame)
        values = dict(zip(chart_df["classe"], chart_df["valor"]))

        self.assertEqual(0.0, values[tab_modelo_fidc.LABELS_COTAS["sub"]])
        self.assertEqual(-12.0, values["Déficit econômico"])
        self.assertNotIn(-80.0, values.values())

    def test_balance_chart_uses_explicit_stacked_area_coordinates(self) -> None:
        frame = pd.DataFrame(
            {
                "indice": [0],
                "data": pd.to_datetime(["2026-01-01"]),
                "pl_senior": [75.0],
                "pl_mezz": [15.0],
                "pl_sub_jr": [10.0],
            }
        )

        chart_df = tab_modelo_fidc._build_balance_area_frame(frame)
        stacks = {
            row["classe"]: (row["stack_base"], row["stack_top"])
            for _, row in chart_df.iterrows()
        }

        self.assertEqual((0.0, 75.0), stacks[tab_modelo_fidc.LABELS_COTAS["sen"]])
        self.assertEqual((75.0, 90.0), stacks[tab_modelo_fidc.LABELS_COTAS["mezz"]])
        self.assertEqual((90.0, 100.0), stacks[tab_modelo_fidc.LABELS_COTAS["sub"]])

    def test_protection_chart_uses_available_subordination_not_shifted_workbook_ratio(self) -> None:
        frame = pd.DataFrame(
            {
                "indice": [0, 1],
                "data": pd.to_datetime(["2026-01-01", "2026-02-01"]),
                "carteira": [100.0, 100.0],
                "pl_fidc": [100.0, 1.0],
                "pl_sub_jr": [10.0, -80.0],
                "perda_carteira_despesa": [0.0, 10.0],
                "subordinacao_pct": [0.1, -80.0],
                "subordinacao_pct_modelo": [0.1, -8000.0],
            }
        )

        chart_df = tab_modelo_fidc._build_protection_area_frame(frame)
        sub_series = chart_df[chart_df["serie"] == "Subordinação econômica"]

        self.assertEqual([10.0, 0.0], sub_series["valor_pct"].tolist())
        self.assertGreaterEqual(sub_series["valor_pct"].min(), 0.0)

    def test_protection_chart_can_include_time_protection_series(self) -> None:
        frame = pd.DataFrame(
            {
                "indice": [0, 1],
                "data": pd.to_datetime(["2026-01-01", "2026-02-01"]),
                "carteira": [100.0, 100.0],
                "pl_fidc": [100.0, 100.0],
                "pl_sub_jr": [10.0, 10.0],
                "perda_carteira_despesa": [0.0, 1.0],
            }
        )
        protection = pd.DataFrame(
            {
                "indice": [1],
                "data": pd.to_datetime(["2026-02-01"]),
                "perda_maxima_suportada": [0.2],
                "valor_pct": [20.0],
                "valor_formatado": ["20,00%"],
                "periodo": ["01/02/2026"],
                "mes_fidc": ["Mês 1"],
            }
        )

        chart_df = tab_modelo_fidc._build_protection_area_frame(frame, protection)

        self.assertIn("Colchão de proteção", chart_df["serie"].tolist())
        self.assertIn("Subordinação econômica", chart_df["serie"].tolist())

    def test_loss_and_protection_charts_are_split_without_independent_axes(self) -> None:
        frame = pd.DataFrame(
            {
                "indice": [0, 1],
                "data": pd.to_datetime(["2026-01-01", "2026-02-01"]),
                "carteira": [100.0, 100.0],
                "pl_fidc": [100.0, 100.0],
                "pl_sub_jr": [20.0, 18.0],
                "perda_carteira_despesa": [0.0, 2.0],
            }
        )
        loss_df = tab_modelo_fidc._build_loss_area_frame(frame, volume=100.0)
        protection_df = tab_modelo_fidc._build_protection_area_frame(frame)

        self.assertEqual({"Perda acumulada", "Perda do período"}, set(loss_df["serie"]))
        self.assertEqual({"Subordinação econômica"}, set(protection_df["serie"]))
        spec = tab_modelo_fidc._area_percent_chart(
            loss_df,
            y_title="Perda da carteira (%)",
            color_domain=["Perda acumulada", "Perda do período"],
            color_range=["#d62728", "#f28e2b"],
        ).to_dict()
        self.assertNotIn("resolve", spec)
        self.assertIn("despesa de provisão", tab_modelo_fidc._chart_definition_caption("loss"))
        self.assertIn("SUB disponível", tab_modelo_fidc._chart_definition_caption("protection"))

    def test_time_protection_chart_is_line_chart(self) -> None:
        chart_df = pd.DataFrame(
            {
                "indice": [1],
                "data": pd.to_datetime(["2026-02-01"]),
                "serie": ["Cenário"],
                "valor_pct": [20.0],
                "valor_formatado": ["20,00%"],
                "carteira_inicial_formatada": ["R$ 40,00"],
                "nova_originacao_formatada": ["R$ 10,00"],
                "nova_originacao_acumulada_formatada": ["R$ 10,00"],
                "nova_originacao_motor_formatada": ["R$ 11,00"],
                "sub_formatada": ["R$ 10,00"],
                "originada_formatada": ["R$ 50,00"],
                "residual_fluxo_formatado": ["R$ 1,00"],
                "periodo": ["01/02/2026"],
                "mes_fidc": ["Mês 1"],
            }
        )

        spec = tab_modelo_fidc._protection_ratio_chart(chart_df).to_dict()

        self.assertEqual("line", spec["layer"][0]["mark"]["type"])


if __name__ == "__main__":
    unittest.main()
