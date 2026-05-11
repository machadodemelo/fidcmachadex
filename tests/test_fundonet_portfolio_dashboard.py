from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from services.fundonet_dashboard import FundonetDashboardData, build_dashboard_data
from services.fundonet_portfolio_dashboard import build_portfolio_dashboard_bundle


_MATURITY_ORDER = {
    "Vencidos": (1, 0.0),
    "Em 30 dias": (2, 30.0),
    "31 a 60 dias": (3, 45.5),
}
_AGING_ORDER = {
    "Até 30 dias": 1,
    "31 a 60 dias": 2,
    "61 a 90 dias": 3,
    "361 a 720 dias": 8,
}


class FundonetPortfolioDashboardTests(unittest.TestCase):
    def test_build_dashboard_data_separates_mezzanino_from_subordinada_in_single_fund(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            self._write_single_fund_mezz_fixture(workspace)

            dashboard = build_dashboard_data(
                wide_csv_path=workspace / "informes_wide.csv",
                listas_csv_path=workspace / "estruturas_lista.csv",
                docs_csv_path=workspace / "documentos_filtrados.csv",
            )

        self.assertAlmostEqual(10_000.0, dashboard.summary["pl_senior"] or 0.0)
        self.assertAlmostEqual(1_000.0, dashboard.summary["pl_mezzanino"] or 0.0)
        self.assertAlmostEqual(500.0, dashboard.summary["pl_subordinada_strict"] or 0.0)
        self.assertAlmostEqual(1_500.0, dashboard.summary["pl_subordinada"] or 0.0)
        self.assertAlmostEqual(11_500.0, dashboard.summary["pl_total"] or 0.0)
        self.assertAlmostEqual(1_500.0 / 11_500.0 * 100.0, dashboard.summary["subordinacao_pct"] or 0.0, places=6)

        quota_lookup = dashboard.quota_pl_history_df.set_index("class_label")
        self.assertEqual("Mezzanino", quota_lookup.loc["Mezz · Série A", "class_macro_label"])
        subordinate_rows = dashboard.quota_pl_history_df[
            dashboard.quota_pl_history_df["class_macro_label"] == "Subordinada"
        ].copy()
        self.assertEqual(1, len(subordinate_rows))
        self.assertEqual({"Sênior", "Mezzanino", "Subordinada"}, set(dashboard.quota_pl_history_df["class_macro_label"]))

    def test_build_portfolio_dashboard_bundle_recalculates_subordination_duration_and_over(self) -> None:
        dashboard_a = self._make_manual_dashboard(
            fund_name="Fundo A",
            competencias=["01/2026", "02/2026"],
            latest_competencia="02/2026",
            pl_series={
                "01/2026": {"senior": 10_000.0, "mezzanino": 0.0, "subordinada": 5_000.0},
                "02/2026": {"senior": 10_000.0, "mezzanino": 0.0, "subordinada": 5_000.0},
            },
            dc_total={"01/2026": 16_000.0, "02/2026": 16_000.0},
            dc_vencidos={"01/2026": 700.0, "02/2026": 700.0},
            provisao={"01/2026": 100.0, "02/2026": 100.0},
            ativos_totais={"01/2026": 21_000.0, "02/2026": 21_000.0},
            carteira={"01/2026": 20_000.0, "02/2026": 20_000.0},
            liquidity={"01/2026": {"liquidez_imediata": 2_000.0, "liquidez_30": 3_500.0}, "02/2026": {"liquidez_imediata": 2_000.0, "liquidez_30": 3_500.0}},
            maturity_buckets={
                "01/2026": {"Vencidos": 500.0, "Em 30 dias": 1_500.0, "31 a 60 dias": 0.0},
                "02/2026": {"Vencidos": 500.0, "Em 30 dias": 1_500.0, "31 a 60 dias": 0.0},
            },
            aging_buckets={
                "01/2026": {"Até 30 dias": 200.0, "31 a 60 dias": 100.0, "61 a 90 dias": 200.0, "361 a 720 dias": 200.0},
                "02/2026": {"Até 30 dias": 200.0, "31 a 60 dias": 100.0, "61 a 90 dias": 200.0, "361 a 720 dias": 200.0},
            },
            event_summary_latest_df=pd.DataFrame(
                [
                    {
                        "ordem": 1,
                        "event_type": "emissao",
                        "evento": "Emissão",
                        "valor_total": 500.0,
                        "valor_total_assinado": 500.0,
                        "valor_total_pct_pl": 500.0 / 15_000.0 * 100.0,
                        "source_status": "reported_value",
                        "source_paths": pd.NA,
                        "present_source_paths": pd.NA,
                        "interpretação": "",
                    }
                ]
            ),
        )
        dashboard_b = self._make_manual_dashboard(
            fund_name="Fundo B",
            competencias=["01/2026"],
            latest_competencia="01/2026",
            pl_series={"01/2026": {"senior": 9_000.0, "mezzanino": 1_000.0, "subordinada": 500.0}},
            dc_total={"01/2026": 10_000.0},
            dc_vencidos={"01/2026": 600.0},
            provisao={"01/2026": 150.0},
            ativos_totais={"01/2026": 13_000.0},
            carteira={"01/2026": 11_000.0},
            liquidity={"01/2026": {"liquidez_imediata": 1_000.0, "liquidez_30": 1_500.0}},
            maturity_buckets={"01/2026": {"Vencidos": 100.0, "Em 30 dias": 3_000.0, "31 a 60 dias": 2_000.0}},
            aging_buckets={"01/2026": {"Até 30 dias": 100.0, "31 a 60 dias": 0.0, "61 a 90 dias": 200.0, "361 a 720 dias": 300.0}},
            event_summary_latest_df=pd.DataFrame(
                [
                    {
                        "ordem": 1,
                        "event_type": "emissao",
                        "evento": "Emissão",
                        "valor_total": 300.0,
                        "valor_total_assinado": 300.0,
                        "valor_total_pct_pl": 300.0 / 10_500.0 * 100.0,
                        "source_status": "reported_value",
                        "source_paths": pd.NA,
                        "present_source_paths": pd.NA,
                        "interpretação": "",
                    }
                ]
            ),
        )

        bundle = build_portfolio_dashboard_bundle(
            portfolio_name="Carteira Teste",
            dashboards_by_cnpj={
                "11111111000111": ("Fundo A", dashboard_a),
                "22222222000122": ("Fundo B", dashboard_b),
            },
        )

        self.assertEqual(["01/2026"], bundle.dashboard.competencias)
        self.assertEqual("01/2026", bundle.dashboard.latest_competencia)
        self.assertAlmostEqual(25_500.0, bundle.dashboard.summary["pl_total"] or 0.0)
        self.assertAlmostEqual(1_000.0, bundle.dashboard.summary["pl_mezzanino"] or 0.0)
        self.assertAlmostEqual(5_500.0, bundle.dashboard.summary["pl_subordinada_strict"] or 0.0)
        self.assertAlmostEqual(6_500.0, bundle.dashboard.summary["pl_subordinada"] or 0.0)
        self.assertAlmostEqual(6_500.0 / 25_500.0 * 100.0, bundle.dashboard.summary["subordinacao_pct"] or 0.0, places=6)

        latest_duration = bundle.dashboard.duration_history_df.iloc[-1]
        self.assertAlmostEqual(226_000.0 / 6_500.0, latest_duration["duration_days"], places=6)

        over_lookup = bundle.dashboard.default_over_history_df.set_index("serie")
        self.assertAlmostEqual(1_300.0 / 26_000.0 * 100.0, over_lookup.loc["Over 1", "percentual"], places=6)
        self.assertAlmostEqual(900.0 / 26_000.0 * 100.0, over_lookup.loc["Over 60", "percentual"], places=6)
        self.assertAlmostEqual(500.0 / 26_000.0 * 100.0, over_lookup.loc["Over 360", "percentual"], places=6)

        quota_latest = bundle.dashboard.quota_pl_history_df[
            bundle.dashboard.quota_pl_history_df["competencia"] == "01/2026"
        ].copy()
        self.assertEqual({"Sênior", "Mezzanino", "Subordinada"}, set(quota_latest["class_macro_label"]))
        self.assertIn("percentual_direitos_creditorios", bundle.dashboard.default_buckets_latest_df.columns)
        latest_aging_bucket = bundle.dashboard.default_buckets_latest_df[
            bundle.dashboard.default_buckets_latest_df["faixa"] == "361 a 720 dias"
        ].iloc[0]
        self.assertAlmostEqual(500.0 / 26_000.0 * 100.0, latest_aging_bucket["percentual_direitos_creditorios"], places=6)

        self.assertTrue(bundle.dashboard.event_summary_latest_df.empty)
        coverage_event = bundle.coverage_df[bundle.coverage_df["block_id"] == "eventos_cotas"].iloc[-1]
        self.assertEqual("Incompleto", coverage_event["status"])
        self.assertEqual(
            "ultima_competencia_comum_diferente_da_ultima_individual",
            coverage_event["observacao"],
        )

        reconciliation_lookup = bundle.reconciliation_df.set_index("metric_id")
        self.assertEqual("Alinhado", reconciliation_lookup.loc["pl_total", "status"])
        self.assertEqual("Alinhado", reconciliation_lookup.loc["subordinacao_pct", "status"])
        self.assertEqual("Divergente", reconciliation_lookup.loc["maturity_vs_dc_a_vencer", "status"])
        self.assertEqual("Alinhado", reconciliation_lookup.loc["aging_vs_inadimplencia", "status"])

    def test_build_portfolio_dashboard_bundle_handles_missing_long_frame_columns(self) -> None:
        dashboard_a = self._make_manual_dashboard(
            fund_name="Fundo A",
            competencias=["01/2026"],
            latest_competencia="01/2026",
            pl_series={"01/2026": {"senior": 10_000.0, "mezzanino": 0.0, "subordinada": 2_000.0}},
            dc_total={"01/2026": 12_000.0},
            dc_vencidos={"01/2026": 300.0},
            provisao={"01/2026": 50.0},
            ativos_totais={"01/2026": 13_000.0},
            carteira={"01/2026": 12_500.0},
            liquidity={"01/2026": {"liquidez_imediata": 500.0, "liquidez_30": 700.0}},
            maturity_buckets={"01/2026": {"Vencidos": 100.0, "Em 30 dias": 2_000.0, "31 a 60 dias": 1_000.0}},
            aging_buckets={"01/2026": {"Até 30 dias": 100.0, "31 a 60 dias": 100.0, "61 a 90 dias": 100.0, "361 a 720 dias": 0.0}},
            event_summary_latest_df=pd.DataFrame(),
        )
        dashboard_b_base = self._make_manual_dashboard(
            fund_name="Fundo B",
            competencias=["01/2026"],
            latest_competencia="01/2026",
            pl_series={"01/2026": {"senior": 8_000.0, "mezzanino": 500.0, "subordinada": 1_000.0}},
            dc_total={"01/2026": 10_000.0},
            dc_vencidos={"01/2026": 200.0},
            provisao={"01/2026": 30.0},
            ativos_totais={"01/2026": 11_000.0},
            carteira={"01/2026": 10_500.0},
            liquidity={"01/2026": {"liquidez_imediata": 400.0, "liquidez_30": 600.0}},
            maturity_buckets={"01/2026": {"Vencidos": 50.0, "Em 30 dias": 1_500.0, "31 a 60 dias": 500.0}},
            aging_buckets={"01/2026": {"Até 30 dias": 50.0, "31 a 60 dias": 50.0, "61 a 90 dias": 100.0, "361 a 720 dias": 0.0}},
            event_summary_latest_df=pd.DataFrame(),
        )
        dashboard_b = replace(
            dashboard_b_base,
            maturity_history_df=pd.DataFrame(columns=["competencia", "competencia_dt", "faixa", "valor", "source_status"]),
            default_buckets_history_df=pd.DataFrame(columns=["competencia", "competencia_dt", "faixa", "valor", "source_status"]),
            maturity_latest_df=pd.DataFrame(columns=["competencia", "competencia_dt", "faixa", "valor", "source_status"]),
            default_buckets_latest_df=pd.DataFrame(columns=["competencia", "competencia_dt", "faixa", "valor", "source_status"]),
        )

        bundle = build_portfolio_dashboard_bundle(
            portfolio_name="Carteira Robusta",
            dashboards_by_cnpj={
                "11111111000111": ("Fundo A", dashboard_a),
                "22222222000122": ("Fundo B", dashboard_b),
            },
        )

        self.assertFalse(bundle.coverage_df.empty)
        vencimento_rows = bundle.coverage_df[bundle.coverage_df["block_id"] == "vencimento"].copy()
        self.assertFalse(vencimento_rows.empty)
        self.assertIn("Incompleto", set(vencimento_rows["status"]))
        self.assertIn(
            "Sem base",
            set(bundle.reconciliation_df["status"]),
        )

    @staticmethod
    def _write_single_fund_mezz_fixture(workspace: Path) -> None:
        competencia = "02/2026"

        def row(bloco: str, sub_bloco: str, tag: str, tag_path: str, value: object) -> dict[str, object]:
            return {
                "bloco": bloco,
                "sub_bloco": sub_bloco,
                "tag": tag,
                "tag_path": tag_path,
                "descricao": tag,
                competencia: value,
            }

        wide_rows = [
            row("CAB_INFORM", "", "NR_CNPJ_FUNDO", "DOC_ARQ/CAB_INFORM/NR_CNPJ_FUNDO", "12345678000190"),
            row("CAB_INFORM", "", "NR_CNPJ_CLASSE", "DOC_ARQ/CAB_INFORM/NR_CNPJ_CLASSE", "12345678000190"),
            row("CAB_INFORM", "", "NR_CNPJ_ADM", "DOC_ARQ/CAB_INFORM/NR_CNPJ_ADM", "99887766000155"),
            row("CAB_INFORM", "", "NM_CLASSE", "DOC_ARQ/CAB_INFORM/NM_CLASSE", "FIDC Mezz Teste"),
            row("CAB_INFORM", "", "TP_CONDOMINIO", "DOC_ARQ/CAB_INFORM/TP_CONDOMINIO", "FECHADO"),
            row("CAB_INFORM", "", "CLASS_UNICA", "DOC_ARQ/CAB_INFORM/CLASS_UNICA", "NAO"),
            row("APLIC_ATIVO", "", "VL_SOM_APLIC_ATIVO", "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/VL_SOM_APLIC_ATIVO", 15_000),
            row("APLIC_ATIVO", "", "VL_CARTEIRA", "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/VL_CARTEIRA", 12_000),
            row("APLIC_ATIVO", "DICRED", "VL_DICRED", "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED", 10_000),
            row(
                "APLIC_ATIVO",
                "DICRED",
                "VL_DICRED_TOTAL_VENC_INAD",
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_TOTAL_VENC_INAD",
                400,
            ),
            row(
                "APLIC_ATIVO",
                "DICRED",
                "VL_DICRED_PROVIS_REDUC_RECUP",
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_PROVIS_REDUC_RECUP",
                100,
            ),
            row(
                "OUTRAS_INFORM",
                "LIQUIDEZ",
                "VL_ATIV_LIQDEZ",
                "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ",
                2_000,
            ),
            row(
                "OUTRAS_INFORM",
                "LIQUIDEZ",
                "VL_ATIV_LIQDEZ_30",
                "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_30",
                3_000,
            ),
            row(
                "COMPMT_DICRED_AQUIS",
                "",
                "VL_SOM_INAD_VENC",
                "DOC_ARQ/LISTA_INFORM/COMPMT_DICRED_AQUIS/VL_SOM_INAD_VENC",
                400,
            ),
            row(
                "COMPMT_DICRED_AQUIS",
                "",
                "VL_PRAZO_VENC_30",
                "DOC_ARQ/LISTA_INFORM/COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_30",
                6_000,
            ),
            row(
                "COMPMT_DICRED_AQUIS",
                "",
                "VL_INAD_VENC_30",
                "DOC_ARQ/LISTA_INFORM/COMPMT_DICRED_AQUIS/VL_INAD_VENC_30",
                100,
            ),
            row(
                "COMPMT_DICRED_AQUIS",
                "",
                "VL_INAD_VENC_61_90",
                "DOC_ARQ/LISTA_INFORM/COMPMT_DICRED_AQUIS/VL_INAD_VENC_61_90",
                300,
            ),
        ]
        pd.DataFrame(wide_rows).to_csv(workspace / "informes_wide.csv", index=False)

        listas_rows = [
            {
                "competencia": competencia,
                "list_group_path": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SENIOR",
                "list_index": 1,
                "tag": "SERIE",
                "valor_excel": "Série 1",
            },
            {
                "competencia": competencia,
                "list_group_path": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SENIOR",
                "list_index": 1,
                "tag": "QT_COTAS",
                "valor_excel": 100,
            },
            {
                "competencia": competencia,
                "list_group_path": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SENIOR",
                "list_index": 1,
                "tag": "VL_COTAS",
                "valor_excel": 100,
            },
            {
                "competencia": competencia,
                "list_group_path": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SUBORD",
                "list_index": 1,
                "tag": "TIPO",
                "valor_excel": "Mezz",
            },
            {
                "competencia": competencia,
                "list_group_path": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SUBORD",
                "list_index": 1,
                "tag": "SERIE",
                "valor_excel": "Série A",
            },
            {
                "competencia": competencia,
                "list_group_path": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SUBORD",
                "list_index": 1,
                "tag": "QT_COTAS",
                "valor_excel": 50,
            },
            {
                "competencia": competencia,
                "list_group_path": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SUBORD",
                "list_index": 1,
                "tag": "VL_COTAS",
                "valor_excel": 20,
            },
            {
                "competencia": competencia,
                "list_group_path": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SUBORD",
                "list_index": 2,
                "tag": "TIPO",
                "valor_excel": "Subordinada",
            },
            {
                "competencia": competencia,
                "list_group_path": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SUBORD",
                "list_index": 2,
                "tag": "QT_COTAS",
                "valor_excel": 25,
            },
            {
                "competencia": competencia,
                "list_group_path": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SUBORD",
                "list_index": 2,
                "tag": "VL_COTAS",
                "valor_excel": 20,
            },
        ]
        pd.DataFrame(listas_rows).to_csv(workspace / "estruturas_lista.csv", index=False)
        pd.DataFrame(
            [
                {
                    "documento_id": "1",
                    "competencia": competencia,
                    "data_entrega": "20/03/2026 09:00",
                    "fundo_ou_classe": "Classe",
                    "nome_fundo": "FIDC Mezz Teste",
                    "nome_administrador": "Administrador Teste",
                    "nome_custodiante": "Custodiante Teste",
                    "nome_gestor": "Gestor Teste",
                    "processamento": "ok",
                }
            ]
        ).to_csv(workspace / "documentos_filtrados.csv", index=False)

    @staticmethod
    def _make_manual_dashboard(
        *,
        fund_name: str,
        competencias: list[str],
        latest_competencia: str,
        pl_series: dict[str, dict[str, float]],
        dc_total: dict[str, float],
        dc_vencidos: dict[str, float],
        provisao: dict[str, float],
        ativos_totais: dict[str, float],
        carteira: dict[str, float],
        liquidity: dict[str, dict[str, float]],
        maturity_buckets: dict[str, dict[str, float]],
        aging_buckets: dict[str, dict[str, float]],
        event_summary_latest_df: pd.DataFrame,
    ) -> FundonetDashboardData:
        def ts(competencia: str) -> pd.Timestamp:
            month, year = competencia.split("/")
            return pd.Timestamp(year=int(year), month=int(month), day=1)

        subordination_rows: list[dict[str, object]] = []
        quota_rows: list[dict[str, object]] = []
        asset_rows: list[dict[str, object]] = []
        dc_rows: list[dict[str, object]] = []
        default_rows: list[dict[str, object]] = []
        liquidity_rows: list[dict[str, object]] = []
        maturity_rows: list[dict[str, object]] = []
        aging_rows: list[dict[str, object]] = []

        for competencia in competencias:
            comp_ts = ts(competencia)
            pl_senior = pl_series[competencia]["senior"]
            pl_mezz = pl_series[competencia]["mezzanino"]
            pl_sub = pl_series[competencia]["subordinada"]
            pl_total = pl_senior + pl_mezz + pl_sub
            subordinated = pl_mezz + pl_sub
            subordination_rows.append(
                {
                    "competencia": competencia,
                    "competencia_dt": comp_ts,
                    "pl_total": pl_total,
                    "pl_senior": pl_senior,
                    "pl_mezzanino": pl_mezz,
                    "pl_subordinada_strict": pl_sub,
                    "pl_subordinada": subordinated,
                    "subordinacao_pct": subordinated / pl_total * 100.0 if pl_total > 0 else pd.NA,
                }
            )
            for ordem, (macro, label, value) in enumerate(
                [
                    ("senior", "Sênior", pl_senior),
                    ("mezzanino", "Mezzanino", pl_mezz),
                    ("subordinada", "Subordinada", pl_sub),
                ],
                start=1,
            ):
                quota_rows.append(
                    {
                        "competencia": competencia,
                        "competencia_dt": comp_ts,
                        "class_kind": macro,
                        "class_macro": macro,
                        "class_macro_label": label,
                        "class_key": f"{fund_name}|{macro}",
                        "class_label": label,
                        "label": label,
                        "qt_cotas": pd.NA,
                        "vl_cota": pd.NA,
                        "pl": value,
                        "pl_share_pct": value / pl_total * 100.0 if pl_total > 0 else pd.NA,
                        "ordem": ordem,
                    }
                )
            dc_total_value = dc_total[competencia]
            dc_vencidos_value = dc_vencidos[competencia]
            provisao_value = provisao[competencia]
            asset_rows.append(
                {
                    "competencia": competencia,
                    "competencia_dt": comp_ts,
                    "ativos_totais": ativos_totais[competencia],
                    "carteira": carteira[competencia],
                    "direitos_creditorios": dc_total_value,
                    "direitos_creditorios_fonte": "agregado_direitos_creditorios_item3",
                    "disponibilidades": pd.NA,
                    "valores_mobiliarios": pd.NA,
                    "titulos_publicos": pd.NA,
                    "outros_ativos_reportados": pd.NA,
                    "liquidez_total": liquidity[competencia]["liquidez_imediata"],
                    "aquisicoes": pd.NA,
                    "alienacoes": pd.NA,
                    "outros_ativos_carteira": max(carteira[competencia] - dc_total_value, 0.0),
                    "alocacao_pct": dc_total_value / carteira[competencia] * 100.0 if carteira[competencia] > 0 else pd.NA,
                }
            )
            dc_rows.append(
                {
                    "competencia": competencia,
                    "competencia_dt": comp_ts,
                    "dc_total_canonico": dc_total_value,
                    "dc_total_fonte_efetiva": "agregado_direitos_creditorios_item3",
                    "dc_total_source_status": "reported_value",
                    "dc_total_malha_vencimento": pd.NA,
                    "dc_total_estoque_granular": pd.NA,
                    "dc_total_agregado_item3": dc_total_value,
                    "dc_total_present_source_paths": pd.NA,
                    "dc_total_source_paths": pd.NA,
                    "dc_vencidos_canonico": dc_vencidos_value,
                    "dc_vencidos_fonte_efetiva": "agregado_vencidos_item3",
                    "dc_vencidos_source_status": "reported_value",
                    "dc_vencidos_malha_vencimento": pd.NA,
                    "dc_vencidos_aging": pd.NA,
                    "dc_vencidos_agregado_aplic_ativo": dc_vencidos_value,
                    "dc_a_vencer_canonico": dc_total_value - dc_vencidos_value,
                    "dc_a_vencer_source_status": "reported_value",
                    "reconciliacao_malha_vs_estoque_status": "ok",
                    "reconciliacao_malha_vs_estoque_gap_pct": 0.0,
                    "reconciliacao_malha_vs_agregado_status": "ok",
                    "reconciliacao_malha_vs_agregado_gap_pct": 0.0,
                }
            )
            default_rows.append(
                {
                    "competencia": competencia,
                    "competencia_dt": comp_ts,
                    "direitos_creditorios_ativo": dc_total_value,
                    "direitos_creditorios_vencidos": dc_vencidos_value,
                    "direitos_creditorios_vencimento_total": dc_total_value,
                    "direitos_creditorios": dc_total_value,
                    "direitos_creditorios_fonte": "agregado_direitos_creditorios_item3",
                    "inadimplencia_fonte": "agregado_vencidos_item3",
                    "inadimplencia_total": dc_vencidos_value,
                    "parcelas_inadimplentes_total": dc_vencidos_value,
                    "creditos_existentes_inadimplentes": dc_vencidos_value,
                    "creditos_vencidos_pendentes_cessao": 0.0,
                    "somatorio_inadimplentes_aux_validacao": dc_vencidos_value,
                    "provisao_total": provisao_value,
                    "pendencia_total": 0.0,
                    "inadimplencia_pct": dc_vencidos_value / dc_total_value * 100.0 if dc_total_value > 0 else pd.NA,
                    "provisao_pct_direitos": provisao_value / dc_total_value * 100.0 if dc_total_value > 0 else pd.NA,
                    "cobertura_pct": provisao_value / dc_vencidos_value * 100.0 if dc_vencidos_value > 0 else pd.NA,
                    "somatorio_inadimplentes_aux_validacao_pct_dcs": dc_vencidos_value / dc_total_value * 100.0 if dc_total_value > 0 else pd.NA,
                }
            )
            liquidity_rows.append(
                {
                    "competencia": competencia,
                    "competencia_dt": comp_ts,
                    "liquidez_imediata": liquidity[competencia].get("liquidez_imediata"),
                    "liquidez_30": liquidity[competencia].get("liquidez_30"),
                    "liquidez_60": pd.NA,
                    "liquidez_90": pd.NA,
                    "liquidez_180": pd.NA,
                    "liquidez_360": pd.NA,
                    "liquidez_mais_360": pd.NA,
                }
            )
            for faixa, valor in maturity_buckets[competencia].items():
                ordem, prazo_proxy = _MATURITY_ORDER[faixa]
                maturity_rows.append(
                    {
                        "competencia": competencia,
                        "competencia_dt": comp_ts,
                        "ordem": ordem,
                        "faixa": faixa,
                        "prazo_proxy": prazo_proxy,
                        "valor": valor,
                        "valor_raw": valor,
                        "source_status": "reported_value",
                        "source_paths": pd.NA,
                        "present_source_paths": pd.NA,
                    }
                )
            inad_total = sum(aging_buckets[competencia].values())
            for faixa, valor in aging_buckets[competencia].items():
                aging_rows.append(
                    {
                        "competencia": competencia,
                        "competencia_dt": comp_ts,
                        "ordem": _AGING_ORDER[faixa],
                        "faixa": faixa,
                        "valor": valor,
                        "valor_raw": valor,
                        "percentual": valor / inad_total * 100.0 if inad_total > 0 else pd.NA,
                        "percentual_direitos_creditorios": valor / dc_total_value * 100.0 if dc_total_value > 0 else pd.NA,
                        "source_status": "reported_value",
                        "source_paths": pd.NA,
                        "present_source_paths": pd.NA,
                    }
                )

        subordination_history_df = pd.DataFrame(subordination_rows)
        liquidity_history_df = pd.DataFrame(liquidity_rows)
        maturity_history_df = pd.DataFrame(maturity_rows)
        default_buckets_history_df = pd.DataFrame(aging_rows)
        latest_maturity = maturity_history_df[maturity_history_df["competencia"] == latest_competencia].copy()
        latest_default_buckets = default_buckets_history_df[default_buckets_history_df["competencia"] == latest_competencia].copy()

        summary_row = subordination_history_df[subordination_history_df["competencia"] == latest_competencia].iloc[-1]
        latest_default = pd.DataFrame(default_rows)
        latest_default_row = latest_default[latest_default["competencia"] == latest_competencia].iloc[-1]
        latest_asset_row = pd.DataFrame(asset_rows)[pd.DataFrame(asset_rows)["competencia"] == latest_competencia].iloc[-1]
        latest_liquidity_row = liquidity_history_df[liquidity_history_df["competencia"] == latest_competencia].iloc[-1]

        return FundonetDashboardData(
            competencias=competencias,
            latest_competencia=latest_competencia,
            fund_info={
                "nome_fundo": fund_name,
                "ultima_competencia": latest_competencia,
                "periodo_analisado": f"{competencias[0]} a {competencias[-1]}",
            },
            summary={
                "pl_total": float(summary_row["pl_total"]),
                "pl_senior": float(summary_row["pl_senior"]),
                "pl_mezzanino": float(summary_row["pl_mezzanino"]),
                "pl_subordinada_strict": float(summary_row["pl_subordinada_strict"]),
                "pl_subordinada": float(summary_row["pl_subordinada"]),
                "ativos_totais": float(latest_asset_row["ativos_totais"]),
                "carteira": float(latest_asset_row["carteira"]),
                "direitos_creditorios": float(latest_default_row["direitos_creditorios"]),
                "alocacao_pct": float(latest_asset_row["alocacao_pct"]),
                "liquidez_imediata": float(latest_liquidity_row["liquidez_imediata"]),
                "liquidez_30": float(latest_liquidity_row["liquidez_30"]),
                "subordinacao_pct": float(summary_row["subordinacao_pct"]),
                "inadimplencia_total": float(latest_default_row["inadimplencia_total"]),
                "inadimplencia_denominador": float(latest_default_row["direitos_creditorios_vencimento_total"]),
                "inadimplencia_pct": float(latest_default_row["inadimplencia_pct"]),
                "provisao_total": float(latest_default_row["provisao_total"]),
                "provisao_pct_direitos": float(latest_default_row["provisao_pct_direitos"]),
                "cobertura_pct": float(latest_default_row["cobertura_pct"]),
                "direitos_creditorios_vencidos": float(latest_default_row["direitos_creditorios_vencidos"]),
                "direitos_creditorios_vencimento_total": float(latest_default_row["direitos_creditorios_vencimento_total"]),
            },
            asset_history_df=pd.DataFrame(asset_rows),
            composition_latest_df=pd.DataFrame(),
            segment_latest_df=pd.DataFrame(),
            liquidity_history_df=liquidity_history_df,
            liquidity_latest_df=pd.DataFrame(),
            maturity_latest_df=latest_maturity,
            maturity_history_df=maturity_history_df,
            duration_history_df=pd.DataFrame(),
            quota_pl_history_df=pd.DataFrame(quota_rows),
            subordination_history_df=subordination_history_df,
            return_history_df=pd.DataFrame(),
            return_summary_df=pd.DataFrame(),
            performance_vs_benchmark_latest_df=pd.DataFrame(),
            event_history_df=pd.DataFrame(),
            dc_canonical_history_df=pd.DataFrame(dc_rows),
            default_history_df=pd.DataFrame(default_rows),
            default_buckets_latest_df=latest_default_buckets,
            default_buckets_history_df=default_buckets_history_df,
            default_aging_history_df=pd.DataFrame(),
            default_over_history_df=pd.DataFrame(),
            holder_latest_df=pd.DataFrame(),
            rate_negotiation_latest_df=pd.DataFrame(),
            tracking_latest_df=pd.DataFrame(),
            event_summary_latest_df=event_summary_latest_df,
            risk_metrics_df=pd.DataFrame(),
            coverage_gap_df=pd.DataFrame(),
            mini_glossary_df=pd.DataFrame(),
            current_dashboard_inventory_df=pd.DataFrame(),
            executive_memory_df=pd.DataFrame(),
            consistency_audit_df=pd.DataFrame(),
            methodology_notes=[],
        )


if __name__ == "__main__":
    unittest.main()
