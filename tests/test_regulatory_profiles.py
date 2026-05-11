from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
import json

import pandas as pd

from services.regulatory_profiles import load_curated_regulatory_profile, load_regulatory_profile, payment_calendar_rows


class RegulatoryProfilesTests(unittest.TestCase):
    def test_load_curated_profile_filters_by_cnpj(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pd.DataFrame(
                [
                    {
                        "Fundo": "A",
                        "CNPJ": "50.473.039/0001-02",
                        "Cota/Classe": "Sênior 1",
                        "Amortização principal": "15/12/2025: 25,00%",
                    },
                    {
                        "Fundo": "B",
                        "CNPJ": "00.000.000/0001-00",
                        "Cota/Classe": "Sênior X",
                        "Amortização principal": "",
                    },
                ]
            ).to_csv(base / "seller_cotas_emissoes_pagamentos.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "Fundo": "A",
                        "CNPJ": "50.473.039/0001-02",
                        "Critério": "Índice de Subordinação",
                        "Monitorabilidade IME": "direto com validação",
                    }
                ]
            ).to_csv(base / "seller_criteria_monitoraveis_ime.csv", index=False)

            profile = load_curated_regulatory_profile("50473039000102", base_dir=base)

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(1, len(profile.emissions_df))
        self.assertEqual(1, len(profile.criteria_df))
        self.assertEqual("Sênior 1", profile.emissions_df.iloc[0]["Cota/Classe"])

    def test_manual_profile_takes_precedence_over_structured_triage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pd.DataFrame(
                [
                    {
                        "Fundo": "A",
                        "CNPJ": "08.417.544/0001-65",
                        "Cota/Classe": "Sênior triagem",
                        "Amortização principal": "",
                    }
                ]
            ).to_csv(base / "all_fidcs_cotas_emissoes_pagamentos.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "Fundo": "A",
                        "CNPJ": "08.417.544/0001-65",
                        "Cota/Classe": "Sênior curada",
                        "Amortização principal": "Conforme suplemento validado",
                    }
                ]
            ).to_csv(base / "pravaler_cotas_emissoes_pagamentos.csv", index=False)

            profile = load_curated_regulatory_profile("08417544000165", base_dir=base)

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual("curado parcial", profile.profile_type)
        self.assertEqual(1, len(profile.emissions_df))
        self.assertEqual("Sênior curada", profile.emissions_df.iloc[0]["Cota/Classe"])

    def test_payment_calendar_rows_extracts_dated_amortizations_and_recurring_interest(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "Cota/Classe": "Sênior 1",
                    "Tipo": "Sênior",
                    "Juros/remuneração": "Semestral, a cada 6 meses",
                    "Amortização principal": "15/12/2025: 25,00%; 15/01/2026: 33,33%",
                    "Fonte": "doc p.1",
                }
            ]
        )

        rows = payment_calendar_rows(frame)

        self.assertEqual(3, len(rows))
        self.assertEqual("Juros/remuneração", rows[0]["Evento"])
        self.assertEqual("15/12/2025", rows[1]["Data/janela"])
        self.assertEqual("25,00%", rows[1]["Detalhe"])
        self.assertEqual("15/01/2026", rows[2]["Data/janela"])

    def test_load_regulatory_profile_falls_back_to_offline_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            knowledge_dir = Path(tmp) / "knowledge"
            curated_dir = Path(tmp) / "curated"
            knowledge_dir.mkdir()
            payload = {
                "fund_name": "FIDC Teste",
                "fund_cnpj": "11.111.111/0001-11",
                "documents": [],
                "criteria": [
                    {
                        "name": "Subordinação mínima",
                        "canonical_key": "subordination_ratio_min",
                        "comparison": ">=",
                        "threshold_display": "10%",
                        "source_document": "regulamento.pdf",
                        "monitoring_mapping": {
                            "status": "monitoravel",
                            "ime_metric": "Cotas Sub / PL %",
                            "rationale": "Teste",
                        },
                    }
                ],
                "emissions": [
                    {
                        "date": "2026-01-01",
                        "event": "emissão",
                        "series_or_class": "Sênior 1",
                        "amount_display": "R$ 100.000.000",
                        "remuneration": "DI + 1%",
                        "amortization_schedule": "15/01/2028: 100%",
                        "source_document": "emissao.pdf",
                    }
                ],
            }
            (knowledge_dir / "11111111000111.json").write_text(json.dumps(payload), encoding="utf-8")

            profile = load_regulatory_profile("11.111.111/0001-11", curated_dir=curated_dir, knowledge_dir=knowledge_dir)

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual("heurístico", profile.profile_type)
        self.assertEqual("Subordinação mínima", profile.criteria_df.iloc[0]["Critério"])
        self.assertEqual("Sênior 1", profile.emissions_df.iloc[0]["Cota/Classe"])


if __name__ == "__main__":
    unittest.main()
