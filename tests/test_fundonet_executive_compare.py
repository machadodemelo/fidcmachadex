from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
import unittest
import zipfile

import pandas as pd

from services.fundonet_executive_compare import (
    available_comparison_metric_labels,
    build_executive_comparison_df,
    dashboard_column_labels,
    default_comparison_metric_labels,
)


def _dashboard(
    *,
    name: str,
    cnpj: str,
    gestor: str | None = None,
    ativo_total: float | None = 1_500_000_000,
    over90: float | None = 2.35,
) -> SimpleNamespace:
    over_rows = []
    for serie, percentual in {
        "Over 30": 4.2,
        "Over 60": 3.1,
        "Over 90": over90,
        "Over 180": 1.2,
        "Over 360": 0.0,
    }.items():
        over_rows.append(
            {
                "competencia": "03/2026",
                "competencia_dt": pd.Timestamp("2026-03-01"),
                "serie": serie,
                "percentual": percentual,
            }
        )
    return SimpleNamespace(
        latest_competencia="03/2026",
        fund_info={
            "nome_fundo": name,
            "cnpj_fundo": cnpj,
            "nome_administrador": "Administrador Teste",
            "nome_gestor": gestor,
            "nome_custodiante": "",
            "total_cotistas": "42",
        },
        summary={
            "ativos_totais": ativo_total,
            "carteira": 1_420_000_000,
            "direitos_creditorios": 1_380_000_000,
            "pl_total": 1_500_000_000,
            "pl_senior": 1_100_000_000,
            "pl_mezzanino": 120_000_000,
            "pl_subordinada": 400_000_000,
            "subordinacao_pct": 26.666,
            "inadimplencia_total": 57_000_000,
            "provisao_total": 70_000_000,
            "cobertura_pct": 122.8,
            "alocacao_pct": 92.0,
            "liquidez_imediata": None,
            "liquidez_30": None,
            "emissao_mes": None,
            "resgate_mes": None,
            "amortizacao_mes": None,
            "resgate_solicitado_mes": None,
        },
        default_over_history_df=pd.DataFrame(over_rows),
        duration_history_df=pd.DataFrame(
            [
                {
                    "competencia": "03/2026",
                    "competencia_dt": pd.Timestamp("2026-03-01"),
                    "duration_days": 365.25,
                }
            ]
        ),
        return_summary_df=pd.DataFrame(
            [
                {
                    "class_kind": "senior",
                    "retorno_mes_pct": 1.25,
                }
            ]
        ),
        event_summary_latest_df=pd.DataFrame(),
    )


class FundonetExecutiveCompareTests(unittest.TestCase):
    def test_builds_comparison_only_from_loaded_dashboards_with_missing_marker(self) -> None:
        dash_a = _dashboard(
            name="FIDC Alfa Fundo de Investimento em Direitos Creditórios Responsabilidade Limitada",
            cnpj="12345678000190",
            gestor=None,
        )
        dash_b = _dashboard(name="FIDC Beta", cnpj="98765432000110", gestor="Gestora Beta")

        frame = build_executive_comparison_df(
            [dash_a, dash_b],
            selected_metric_labels=["CNPJ", "Gestor", "Ativo total", "NPL Over 90", "NPL Over 360"],
        )

        self.assertEqual(["Métrica", "FIDC Alfa", "FIDC Beta"], frame.columns.tolist())
        self.assertEqual("—", frame.loc[frame["Métrica"] == "Gestor", "FIDC Alfa"].iloc[0])
        self.assertEqual("Gestora Beta", frame.loc[frame["Métrica"] == "Gestor", "FIDC Beta"].iloc[0])
        self.assertEqual("R$ 1.500 mm", frame.loc[frame["Métrica"] == "Ativo total", "FIDC Alfa"].iloc[0])
        self.assertEqual("2,4%", frame.loc[frame["Métrica"] == "NPL Over 90", "FIDC Alfa"].iloc[0])
        self.assertEqual("0,0%", frame.loc[frame["Métrica"] == "NPL Over 360", "FIDC Alfa"].iloc[0])

    def test_metric_options_drop_rows_unavailable_for_all_funds(self) -> None:
        dash_a = _dashboard(name="FIDC Alfa", cnpj="12345678000190", gestor=None)
        dash_b = _dashboard(name="FIDC Beta", cnpj="98765432000110", gestor=None)

        available = available_comparison_metric_labels([dash_a, dash_b])
        defaults = default_comparison_metric_labels([dash_a, dash_b])

        self.assertNotIn("Gestor", available)
        self.assertIn("PL total", available)
        self.assertIn("PL total", defaults)

    def test_column_labels_remain_unique_for_duplicate_names(self) -> None:
        dash_a = _dashboard(name="FIDC Alfa", cnpj="12345678000190")
        dash_b = _dashboard(name="FIDC Alfa", cnpj="98765432000110")

        self.assertEqual(["FIDC Alfa · 0190", "FIDC Alfa · 0110"], dashboard_column_labels([dash_a, dash_b]))

    def test_pptx_export_uses_dataframe_as_source(self) -> None:
        try:
            from services.fundonet_executive_compare_ppt import build_executive_comparison_pptx_bytes
        except RuntimeError as exc:
            self.skipTest(str(exc))

        frame = pd.DataFrame(
            {
                "Métrica": ["PL total", "NPL Over 90"],
                "FIDC Alfa": ["R$ 1.500 mm", "2,4%"],
                "FIDC Beta": ["R$ 900 mm", "1,1%"],
            }
        )
        pptx_bytes = build_executive_comparison_pptx_bytes(frame, highlighted_column="FIDC Beta")

        self.assertGreater(len(pptx_bytes), 1000)
        with zipfile.ZipFile(BytesIO(pptx_bytes)) as archive:
            self.assertIn("ppt/presentation.xml", archive.namelist())
            slide_text = archive.read("ppt/slides/slide1.xml").decode("utf-8")
        self.assertIn("Comparativo Executivo de FIDCs", slide_text)
        self.assertIn("NPL Over 90", slide_text)


if __name__ == "__main__":
    unittest.main()
