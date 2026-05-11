from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from data_loader import load_model_inputs
from services.fidc_model import (
    AMORTIZATION_MODE_BULLET,
    AMORTIZATION_MODE_LINEAR,
    AMORTIZATION_MODE_WORKBOOK,
    CREDIT_MODEL_MIGRATION,
    CREDIT_MODEL_NPL90,
    INTEREST_PAYMENT_MODE_AFTER_GRACE,
    INTEREST_PAYMENT_MODE_PERIODIC,
    RATE_MODE_POST_CDI,
    RATE_MODE_PRE,
    Premissas,
    annual_252_to_monthly_rate,
    build_flow,
    build_kpis,
    cession_discount_to_monthly_rate,
    monthly_to_annual_252_rate,
    monthly_rate_to_cession_discount,
)
from services.fidc_model.engine import _admin_cost_period_amount, _class_annual_rate
from services.fidc_model.metrics import lookup_pre_di_duration


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "modelo_publico_fixture.json"


def _build_default_premissas() -> Premissas:
    inputs = load_model_inputs("model_data.json")
    return Premissas(
        volume=inputs.premissas["Volume"],
        tx_cessao_am=inputs.premissas["Tx Cessão (%am)"],
        tx_cessao_cdi_aa=inputs.premissas["Tx Cessão (CDI+ %aa)"],
        custo_adm_aa=inputs.premissas["Custo Adm/Gestão (a.a.)"],
        custo_min=inputs.premissas["Custo Adm/Gestão (mín)"],
        inadimplencia=inputs.premissas["Inadimplência"],
        proporcao_senior=inputs.premissas["Proporção PL Sr."],
        taxa_senior=inputs.premissas["Taxa Sênior"],
        proporcao_mezz=inputs.premissas["Proporção PL Mezz"],
        taxa_mezz=inputs.premissas["Taxa Mezz"],
        carteira_revolvente=False,
    )


class FidcModelParityTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.inputs = load_model_inputs("model_data.json")
        cls.periods = build_flow(
            cls.inputs.datas,
            cls.inputs.feriados,
            cls.inputs.curva_du,
            cls.inputs.curva_cdi,
            _build_default_premissas(),
        )
        cls.kpis = build_kpis(cls.periods)

    def assertAlmostOptional(self, actual, expected, delta=1e-7):
        if expected is None:
            self.assertIsNone(actual)
            return
        self.assertIsNotNone(actual)
        self.assertAlmostEqual(actual, expected, delta=delta)

    def test_first_period_contract(self):
        first = self.periods[0]
        self.assertEqual(first.indice, 0)
        self.assertEqual(first.dc, 0)
        self.assertEqual(first.du, 0)
        self.assertIsNone(first.pre_di)
        self.assertEqual(first.pmt_senior, -900000.0)
        self.assertEqual(first.pmt_mezz, -50000.0)
        self.assertEqual(first.pl_sub_jr, 50000.0)
        self.assertIsNone(first.pl_sub_jr_modelo)

    def test_periods_match_fluxo_base_fixture(self):
        comparable_fields = [
            "indice",
            "dc",
            "du",
            "pre_di",
            "taxa_senior",
            "fra_senior",
            "taxa_mezz",
            "fra_mezz",
            "carteira",
            "fluxo_carteira",
            "pl_fidc",
            "custos_adm",
            "inadimplencia_despesa",
            "pmt_senior",
            "vp_pmt_senior",
            "pl_senior",
            "pmt_mezz",
            "pl_mezz",
        ]
        for actual, expected in zip(self.periods[1:], self.fixture["timeline"][1:]):
            self.assertEqual(actual.data.date().isoformat(), expected["data"])
            for field in comparable_fields:
                self.assertAlmostOptional(getattr(actual, field), expected[field])
            self.assertAlmostOptional(actual.pl_sub_jr_modelo, expected["pl_sub_jr"])
            self.assertAlmostOptional(actual.subordinacao_pct_modelo, expected["subordinacao_pct"])

    def test_kpis_match_fixture_and_junior_is_not_fabricated(self):
        self.assertAlmostOptional(self.kpis.xirr_senior, self.fixture["kpis"]["xirr_senior"])
        self.assertAlmostOptional(self.kpis.xirr_mezz, self.fixture["kpis"]["xirr_mezz"])
        self.assertIsNone(self.kpis.xirr_sub_jr)
        self.assertIsNone(self.kpis.taxa_retorno_sub_jr_cdi)
        self.assertAlmostOptional(self.kpis.duration_senior_anos, self.fixture["kpis"]["duration_senior_anos"])
        self.assertAlmostOptional(self.kpis.pre_di_duration, self.fixture["kpis"]["pre_di_duration"])

    def test_annual_252_monthly_conversion_roundtrip(self):
        monthly_rate = 0.02
        annual_rate = monthly_to_annual_252_rate(monthly_rate)

        self.assertAlmostEqual(monthly_rate, annual_252_to_monthly_rate(annual_rate), delta=1e-12)

    def test_cession_discount_converts_to_monthly_rate(self):
        discount_rate = 0.05
        monthly_rate = cession_discount_to_monthly_rate(discount_rate)

        self.assertAlmostEqual((100.0 / 95.0) - 1.0, monthly_rate, delta=1e-12)
        self.assertAlmostEqual(discount_rate, monthly_rate_to_cession_discount(monthly_rate), delta=1e-12)

    def test_cession_discount_uses_receivable_average_term_when_provided(self):
        discount_rate = 0.05
        monthly_rate = cession_discount_to_monthly_rate(discount_rate, term_months=6.0)

        self.assertAlmostEqual(((100.0 / 95.0) ** (1.0 / 6.0)) - 1.0, monthly_rate, delta=1e-12)
        self.assertAlmostEqual(discount_rate, monthly_rate_to_cession_discount(monthly_rate, term_months=6.0), delta=1e-12)

    def test_admin_cost_uses_compounded_monthly_rate_over_starting_pl(self):
        expected = 100_000_000.0 * ((1.0 + 0.0035) ** (1.0 / 12.0) - 1.0)

        self.assertAlmostEqual(expected, _admin_cost_period_amount(100_000_000.0, 0.0035, 20_000.0))
        self.assertEqual(20_000.0, _admin_cost_period_amount(1_000_000.0, 0.0035, 20_000.0))

    def test_post_fixed_quota_rate_uses_additive_cdi_spread_convention(self):
        self.assertAlmostEqual(0.1625, _class_annual_rate(0.1490, 0.0135, RATE_MODE_POST_CDI), delta=1e-12)

    def test_prefixed_quota_rate_helper_uses_informed_annual_rate(self):
        self.assertAlmostEqual(0.12, _class_annual_rate(0.1490, 0.12, RATE_MODE_PRE), delta=1e-12)

    def test_pre_di_duration_is_interpolated_by_target_du(self):
        periods = [
            SimpleNamespace(du=126, pre_di=0.12),
            SimpleNamespace(du=252, pre_di=0.14),
        ]

        self.assertAlmostEqual(0.13, lookup_pre_di_duration(periods, 0.75))

    def test_prefixed_quota_rate_uses_informed_annual_rate(self):
        premissas = _build_default_premissas()
        premissas = Premissas(
            **{
                **premissas.__dict__,
                "tipo_taxa_senior": RATE_MODE_PRE,
                "taxa_senior": 0.12,
                "tipo_taxa_mezz": RATE_MODE_PRE,
                "taxa_mezz": 0.15,
            }
        )

        periods = build_flow(
            self.inputs.datas,
            self.inputs.feriados,
            self.inputs.curva_du,
            self.inputs.curva_cdi,
            premissas,
        )

        self.assertAlmostEqual(0.12, periods[1].taxa_senior)
        self.assertAlmostEqual(0.15, periods[1].taxa_mezz)

    def test_explicit_subordinated_pl_proportion_is_used(self):
        premissas = _build_default_premissas()
        premissas = Premissas(
            **{
                **premissas.__dict__,
                "proporcao_senior": 0.7,
                "proporcao_mezz": 0.2,
                "proporcao_subordinada": 0.1,
            }
        )

        periods = build_flow(
            self.inputs.datas,
            self.inputs.feriados,
            self.inputs.curva_du,
            self.inputs.curva_cdi,
            premissas,
        )

        self.assertAlmostEqual(100000.0, periods[0].pl_sub_jr)

    def test_expected_and_unexpected_losses_drive_portfolio_loss(self):
        monthly_dates = [datetime(2025, 1, 1), datetime(2025, 1, 31)]
        premissas = Premissas(
            volume=1_000_000.0,
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
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            perda_esperada_am=0.01,
            perda_inesperada_am=0.02,
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertAlmostEqual(10_000.0, periods[1].perda_esperada_despesa)
        self.assertAlmostEqual(20_000.0, periods[1].perda_inesperada_despesa)
        self.assertAlmostEqual(30_000.0, periods[1].perda_carteira_despesa)
        self.assertAlmostEqual(periods[1].perda_carteira_despesa, periods[1].inadimplencia_despesa)
        self.assertAlmostEqual(periods[1].fluxo_carteira - 30_000.0, periods[1].resultado_carteira_liquido)

    def test_npl90_model_provisions_before_delayed_npl_stock_appears(self):
        monthly_dates = [datetime(2025 + (month // 12), (month % 12) + 1, 1) for month in range(5)]
        premissas = Premissas(
            volume=600.0,
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
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            carteira_revolvente=True,
            prazo_fidc_anos=1.0,
            prazo_medio_recebiveis_meses=6.0,
            modelo_credito=CREDIT_MODEL_NPL90,
            perda_ciclo=0.06,
            npl90_lag_meses=3,
            cobertura_minima_npl90=1.0,
            lgd=1.0,
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertAlmostEqual(100.0, periods[1].carteira_vencendo)
        self.assertAlmostEqual(6.0, periods[1].principal_inadimplente)
        self.assertAlmostEqual(94.0, periods[1].principal_recebido_carteira)
        self.assertAlmostEqual(94.0, periods[1].reinvestimento_principal)
        self.assertAlmostEqual(6.0, periods[1].perda_esperada_despesa)
        self.assertAlmostEqual(6.0, periods[1].despesa_provisao)
        self.assertAlmostEqual(0.0, periods[1].entrada_npl90)
        self.assertAlmostEqual(0.0, periods[1].npl90_estoque_fim)
        self.assertAlmostEqual(600.0, periods[1].carteira_fim)
        self.assertAlmostEqual(6.0, periods[4].entrada_npl90)
        self.assertAlmostEqual(6.0, periods[4].baixa_credito)
        self.assertAlmostEqual(0.0, periods[4].npl90_estoque_fim)
        self.assertLess(periods[4].carteira_fim, periods[4].carteira)
        self.assertGreaterEqual(periods[4].provisao_saldo_fim, periods[4].npl90_estoque_fim)

    def test_npl90_zero_loss_keeps_credit_columns_zero(self):
        monthly_dates = [datetime(2025 + (month // 12), (month % 12) + 1, 1) for month in range(5)]
        premissas = Premissas(
            volume=600.0,
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
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            carteira_revolvente=True,
            prazo_fidc_anos=1.0,
            prazo_medio_recebiveis_meses=6.0,
            modelo_credito=CREDIT_MODEL_NPL90,
            perda_ciclo=0.0,
            npl90_lag_meses=3,
            cobertura_minima_npl90=1.0,
            lgd=1.0,
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        for period in periods[1:]:
            self.assertAlmostEqual(0.0, period.principal_inadimplente)
            self.assertAlmostEqual(0.0, period.entrada_npl90)
            self.assertAlmostEqual(0.0, period.baixa_credito)
            self.assertAlmostEqual(0.0, period.despesa_provisao)
            self.assertAlmostEqual(period.carteira_vencendo, period.principal_recebido_carteira)

    def test_migration_model_moves_buckets_to_npl_and_requires_provision(self):
        monthly_dates = [datetime(2025 + (month // 12), (month % 12) + 1, 1) for month in range(5)]
        premissas = Premissas(
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
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            carteira_revolvente=False,
            modelo_credito=CREDIT_MODEL_MIGRATION,
            lgd=1.0,
            cobertura_minima_npl90=1.0,
            rolagem_adimplente_1_30=1.0,
            rolagem_1_30_31_60=1.0,
            rolagem_31_60_61_90=1.0,
            rolagem_61_90_90_plus=1.0,
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertAlmostEqual(1_000.0, periods[1].bucket_1_30)
        self.assertAlmostEqual(1_000.0, periods[2].bucket_31_60)
        self.assertAlmostEqual(1_000.0, periods[3].bucket_61_90)
        self.assertAlmostEqual(1_000.0, periods[4].entrada_npl90)
        self.assertAlmostEqual(1_000.0, periods[4].bucket_90_plus)
        self.assertAlmostEqual(1_000.0, periods[4].despesa_provisao)
        self.assertAlmostEqual(1.0, periods[4].cobertura_npl90)

    def test_npl90_writeoff_reduces_portfolio_and_subordination(self):
        monthly_dates = [datetime(2025 + (month // 12), (month % 12) + 1, 1) for month in range(6)]
        premissas = Premissas(
            volume=600.0,
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
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            carteira_revolvente=True,
            prazo_fidc_anos=1.0,
            prazo_medio_recebiveis_meses=6.0,
            modelo_credito=CREDIT_MODEL_NPL90,
            perda_ciclo=0.06,
            npl90_lag_meses=0,
            cobertura_minima_npl90=1.0,
            lgd=1.0,
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertAlmostEqual(6.0, periods[1].principal_inadimplente)
        self.assertAlmostEqual(94.0, periods[1].principal_recebido_carteira)
        self.assertAlmostEqual(6.0, periods[1].entrada_npl90)
        self.assertAlmostEqual(6.0, periods[1].baixa_credito)
        self.assertAlmostEqual(0.0, periods[1].npl90_estoque_fim)
        self.assertLess(periods[1].carteira_fim, periods[1].carteira)
        self.assertLess(periods[1].pl_sub_jr, periods[0].pl_sub_jr)

    def test_migration_writeoff_reduces_portfolio(self):
        monthly_dates = [datetime(2025 + (month // 12), (month % 12) + 1, 1) for month in range(6)]
        premissas = Premissas(
            volume=600.0,
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
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            carteira_revolvente=True,
            prazo_fidc_anos=1.0,
            prazo_medio_recebiveis_meses=6.0,
            modelo_credito=CREDIT_MODEL_MIGRATION,
            rolagem_adimplente_1_30=1.0,
            rolagem_1_30_31_60=1.0,
            rolagem_31_60_61_90=1.0,
            rolagem_61_90_90_plus=1.0,
            writeoff_90_plus=1.0,
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertGreater(periods[5].baixa_credito, 0.0)
        self.assertLess(periods[5].carteira_fim, periods[5].carteira)

    def test_revolving_portfolio_reinvests_principal_and_excess_cash_while_eligible(self):
        monthly_dates = [datetime(2025, 1, 1), datetime(2025, 2, 1), datetime(2025, 3, 1)]
        premissas = Premissas(
            volume=1_000_000.0,
            tx_cessao_am=0.10,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=0.0,
            taxa_senior=0.0,
            proporcao_mezz=0.0,
            taxa_mezz=0.0,
            proporcao_subordinada=1.0,
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            carteira_revolvente=True,
            prazo_fidc_anos=1.0,
            prazo_medio_recebiveis_meses=6.0,
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertAlmostEqual(1_000_000.0, periods[1].carteira)
        self.assertGreater(periods[1].principal_recebido_carteira, 0.0)
        self.assertGreater(periods[1].reinvestimento_excesso, 0.0)
        self.assertAlmostEqual(
            periods[1].principal_recebido_carteira + periods[1].reinvestimento_excesso,
            periods[1].nova_originacao,
        )
        self.assertGreater(periods[2].carteira, 1_000_000.0)
        self.assertGreater(periods[2].pl_fidc, periods[1].pl_fidc)

    def test_revolving_portfolio_stops_new_origination_when_average_term_no_longer_fits(self):
        monthly_dates = [datetime(2025 + (month // 12), (month % 12) + 1, 1) for month in range(37)]
        premissas = Premissas(
            volume=1_000_000.0,
            tx_cessao_am=0.10,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=0.0,
            taxa_senior=0.0,
            proporcao_mezz=0.0,
            taxa_mezz=0.0,
            proporcao_subordinada=1.0,
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            carteira_revolvente=True,
            prazo_fidc_anos=3.0,
            prazo_medio_recebiveis_meses=12.0,
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertTrue(periods[24].reinvestimento_elegivel)
        self.assertGreater(periods[24].nova_originacao, 0.0)
        self.assertFalse(periods[25].reinvestimento_elegivel)
        self.assertEqual(0.0, periods[25].nova_originacao)
        self.assertGreater(periods[25].principal_recebido_carteira, 0.0)
        self.assertLess(periods[25].carteira_fim, periods[25].carteira)

    def test_runoff_cash_earns_projected_selic_after_reinvestment_window(self):
        monthly_dates = [datetime(2025 + (month // 12), (month % 12) + 1, 1) for month in range(7)]
        premissas = Premissas(
            volume=1_000_000.0,
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
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            carteira_revolvente=True,
            prazo_fidc_anos=0.5,
            prazo_medio_recebiveis_meses=3.0,
            selic_aa_por_ano=((2025, 0.12),),
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)
        runoff_period = periods[4]
        expected_monthly_selic = annual_252_to_monthly_rate(0.12)
        expected_principal_to_cash = 1_000_000.0 / 3.0

        self.assertFalse(runoff_period.reinvestimento_elegivel)
        self.assertAlmostEqual(expected_principal_to_cash, runoff_period.principal_para_caixa_selic)
        self.assertAlmostEqual(expected_monthly_selic, runoff_period.taxa_selic_periodo)
        self.assertAlmostEqual(
            expected_principal_to_cash * expected_monthly_selic,
            runoff_period.rendimento_caixa_selic,
        )
        self.assertAlmostEqual(runoff_period.fluxo_carteira + runoff_period.rendimento_caixa_selic, runoff_period.fluxo_ativos_total)
        self.assertGreater(runoff_period.saldo_caixa_selic_fim, runoff_period.principal_para_caixa_selic)

    def test_projected_selic_perpetuates_last_available_year(self):
        monthly_dates = [datetime(2026, 12, 1), datetime(2027, 1, 1)]
        premissas = Premissas(
            volume=1_000_000.0,
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
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            selic_aa_por_ano=((2026, 0.13),),
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertAlmostEqual(0.13, periods[1].taxa_selic_aa)

    def test_acquisition_premium_is_informational_not_initial_expense(self):
        premissas = Premissas(
            volume=1_000_000.0,
            tx_cessao_am=0.01,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=0.75,
            taxa_senior=0.0,
            proporcao_mezz=0.15,
            taxa_mezz=0.0,
            proporcao_subordinada=0.10,
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            agio_aquisicao=0.02,
        )

        periods = build_flow([datetime(2025, 1, 1), datetime(2025, 2, 1)], [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertAlmostEqual(20_000.0, periods[0].agio_aquisicao_despesa)
        self.assertAlmostEqual(1_000_000.0, periods[0].pl_fidc)
        self.assertAlmostEqual(100_000.0, periods[0].pl_sub_jr)
        self.assertLess(periods[1].preco_pago_fator, 1.0)
        self.assertAlmostEqual(periods[1].ead_carteira, periods[1].carteira * periods[1].preco_pago_fator)

    def test_cession_rate_floor_uses_senior_remuneration_plus_excess_spread(self):
        premissas = Premissas(
            volume=1_000_000.0,
            tx_cessao_am=0.0,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=1.0,
            taxa_senior=0.12,
            proporcao_mezz=0.0,
            taxa_mezz=0.0,
            proporcao_subordinada=0.0,
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            excesso_spread_senior_am=0.01,
        )
        expected_floor = annual_252_to_monthly_rate(
            0.12 + monthly_to_annual_252_rate(0.01)
        )

        periods = build_flow([datetime(2025, 1, 1), datetime(2025, 2, 1)], [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertAlmostEqual(expected_floor, periods[1].tx_cessao_am_piso)
        self.assertAlmostEqual(expected_floor, periods[1].tx_cessao_am_aplicada)

    def test_workbook_principal_schedule_is_capped_for_longer_terms(self):
        monthly_dates = [datetime(2025 + (month // 12), (month % 12) + 1, 1) for month in range(61)]
        premissas = Premissas(
            volume=1_000_000.0,
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
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            amortizacao_senior=AMORTIZATION_MODE_WORKBOOK,
            amortizacao_mezz=AMORTIZATION_MODE_WORKBOOK,
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertAlmostEqual(0.0, periods[-1].pl_senior)
        self.assertAlmostEqual(0.0, periods[-1].pl_mezz)
        self.assertGreaterEqual(min(period.pl_senior for period in periods), 0.0)
        self.assertGreaterEqual(min(period.pl_mezz for period in periods), 0.0)

    def test_custom_linear_and_bullet_amortization_modes_change_principal_schedule(self):
        monthly_dates = [datetime(2025 + (month // 12), (month % 12) + 1, 1) for month in range(13)]
        premissas = Premissas(
            volume=1_000_000.0,
            tx_cessao_am=0.0,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=0.60,
            taxa_senior=0.0,
            proporcao_mezz=0.20,
            taxa_mezz=0.0,
            proporcao_subordinada=0.20,
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            prazo_senior_anos=1.0,
            prazo_mezz_anos=1.0,
            amortizacao_senior=AMORTIZATION_MODE_LINEAR,
            amortizacao_mezz=AMORTIZATION_MODE_BULLET,
            inicio_amortizacao_senior_meses=6,
        )

        periods = build_flow(monthly_dates, [], [1.0, 2000.0], [0.0, 0.0], premissas)

        self.assertEqual(0.0, periods[6].principal_senior)
        self.assertAlmostEqual(600_000.0 / 6.0, periods[7].principal_senior)
        self.assertAlmostEqual(200_000.0, periods[12].principal_mezz)
        self.assertAlmostEqual(0.0, periods[-1].pl_senior)
        self.assertAlmostEqual(0.0, periods[-1].pl_mezz)

    def test_interest_after_grace_defers_payment_until_amortization_start(self):
        monthly_dates = [datetime(2025 + (month // 12), (month % 12) + 1, 1) for month in range(8)]
        base_kwargs = dict(
            volume=1_000_000.0,
            tx_cessao_am=0.0,
            tx_cessao_cdi_aa=None,
            custo_adm_aa=0.0,
            custo_min=0.0,
            inadimplencia=0.0,
            proporcao_senior=1.0,
            taxa_senior=0.12,
            proporcao_mezz=0.0,
            taxa_mezz=0.0,
            proporcao_subordinada=0.0,
            tipo_taxa_senior=RATE_MODE_PRE,
            tipo_taxa_mezz=RATE_MODE_PRE,
            amortizacao_senior=AMORTIZATION_MODE_LINEAR,
            amortizacao_mezz=AMORTIZATION_MODE_LINEAR,
            inicio_amortizacao_senior_meses=7,
        )
        periodic = build_flow(
            monthly_dates,
            [],
            [1.0, 2000.0],
            [0.0, 0.0],
            Premissas(**base_kwargs, juros_senior=INTEREST_PAYMENT_MODE_PERIODIC),
        )
        deferred = build_flow(
            monthly_dates,
            [],
            [1.0, 2000.0],
            [0.0, 0.0],
            Premissas(**base_kwargs, juros_senior=INTEREST_PAYMENT_MODE_AFTER_GRACE),
        )

        self.assertGreater(periodic[1].juros_senior, 0.0)
        self.assertEqual(0.0, deferred[1].juros_senior)
        self.assertGreater(deferred[7].juros_senior, periodic[7].juros_senior)


if __name__ == "__main__":
    unittest.main()
