from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from services import cvm_cadastro


class CvmCadastroTests(unittest.TestCase):
    def setUp(self) -> None:
        cvm_cadastro._load_fi_cad_legacy.cache_clear()
        cvm_cadastro._load_registro_fundo_classe.cache_clear()

    def tearDown(self) -> None:
        cvm_cadastro._load_fi_cad_legacy.cache_clear()
        cvm_cadastro._load_registro_fundo_classe.cache_clear()

    def test_fetch_fidc_participantes_prefers_registro_fundo_and_registro_classe(self) -> None:
        fundo_df = pd.DataFrame(
            [
                {
                    "CNPJ_Fundo": "12.345.678/0001-90",
                    "Tipo_Fundo": "FIDC",
                    "Situacao": "Em Funcionamento Normal",
                    "Administrador": "Administrador Atual",
                    "CNPJ_Administrador": "11.111.111/0001-11",
                    "Gestor": "Gestor Atual",
                    "CPF_CNPJ_Gestor": "22.222.222/0001-22",
                    "Data_Inicio_Situacao": "2026-01-01",
                    "Data_Registro": "2025-01-01",
                    "Data_Adaptacao_RCVM175": "2025-10-01",
                }
            ]
        )
        classe_df = pd.DataFrame(
            [
                {
                    "CNPJ_Classe": "98.765.432/0001-09",
                    "Tipo_Classe": "FIDC",
                    "Situacao": "Em Funcionamento Normal",
                    "Custodiante": "Custodiante Classe",
                    "CNPJ_Custodiante": "33.333.333/0001-33",
                    "Data_Inicio_Situacao": "2026-01-01",
                    "Data_Registro": "2025-01-01",
                    "Data_Constituicao": "2025-01-01",
                }
            ]
        )
        legacy_df = pd.DataFrame(
            [
                {
                    "CNPJ_FUNDO": "12.345.678/0001-90",
                    "TP_FUNDO": "FIDC",
                    "SIT": "EM FUNCIONAMENTO NORMAL",
                    "ADMIN": "Administrador Legado",
                    "CNPJ_ADMIN": "44.444.444/0001-44",
                    "GESTOR": "Gestor Legado",
                    "CPF_CNPJ_GESTOR": "55.555.555/0001-55",
                    "CUSTODIANTE": "Custodiante Legado",
                    "CNPJ_CUSTODIANTE": "66.666.666/0001-66",
                    "DT_PATRIM_LIQ": "2026-01-31",
                    "DT_INI_SIT": "2025-01-01",
                    "DT_REG": "2024-01-01",
                }
            ]
        )

        with (
            patch.object(cvm_cadastro, "_load_registro_fundo_classe", return_value=(fundo_df, classe_df)),
            patch.object(cvm_cadastro, "_load_fi_cad_legacy", return_value=legacy_df),
        ):
            participantes = cvm_cadastro.fetch_fidc_participantes(
                "12.345.678/0001-90",
                cnpj_classe="98.765.432/0001-09",
            )

        self.assertEqual("Administrador Atual", participantes["nm_admin"])
        self.assertEqual("11111111000111", participantes["cnpj_admin"])
        self.assertEqual("fi_cad_registro_fundo", participantes["fonte_admin"])
        self.assertEqual("Gestor Atual", participantes["nm_gestor"])
        self.assertEqual("22222222000122", participantes["cnpj_gestor"])
        self.assertEqual("fi_cad_registro_fundo", participantes["fonte_gestor"])
        self.assertEqual("Custodiante Classe", participantes["nm_custodiante"])
        self.assertEqual("33333333000133", participantes["cnpj_custodiante"])
        self.assertEqual("fi_cad_registro_classe", participantes["fonte_custodiante"])

    def test_fetch_fidc_participantes_falls_back_to_legacy_when_class_not_available(self) -> None:
        fundo_df = pd.DataFrame(
            [
                {
                    "CNPJ_Fundo": "12.345.678/0001-90",
                    "Tipo_Fundo": "FIDC",
                    "Situacao": "Em Funcionamento Normal",
                    "Administrador": "",
                    "CNPJ_Administrador": "",
                    "Gestor": "",
                    "CPF_CNPJ_Gestor": "",
                    "Data_Inicio_Situacao": "2026-01-01",
                    "Data_Registro": "2025-01-01",
                    "Data_Adaptacao_RCVM175": "2025-10-01",
                }
            ]
        )
        classe_df = pd.DataFrame(columns=["CNPJ_Classe", "Tipo_Classe", "Situacao"])
        legacy_df = pd.DataFrame(
            [
                {
                    "CNPJ_FUNDO": "12.345.678/0001-90",
                    "TP_FUNDO": "FIDC",
                    "SIT": "EM FUNCIONAMENTO NORMAL",
                    "ADMIN": "Administrador Legado",
                    "CNPJ_ADMIN": "44.444.444/0001-44",
                    "GESTOR": "Gestor Legado",
                    "CPF_CNPJ_GESTOR": "55.555.555/0001-55",
                    "CUSTODIANTE": "Custodiante Legado",
                    "CNPJ_CUSTODIANTE": "66.666.666/0001-66",
                    "DT_PATRIM_LIQ": "2026-01-31",
                    "DT_INI_SIT": "2025-01-01",
                    "DT_REG": "2024-01-01",
                }
            ]
        )

        with (
            patch.object(cvm_cadastro, "_load_registro_fundo_classe", return_value=(fundo_df, classe_df)),
            patch.object(cvm_cadastro, "_load_fi_cad_legacy", return_value=legacy_df),
        ):
            participantes = cvm_cadastro.fetch_fidc_participantes(
                "12.345.678/0001-90",
                cnpj_classe="98.765.432/0001-09",
            )

        self.assertEqual("Administrador Legado", participantes["nm_admin"])
        self.assertEqual("fi_cad_legado_fundo", participantes["fonte_admin"])
        self.assertEqual("Gestor Legado", participantes["nm_gestor"])
        self.assertEqual("fi_cad_legado_fundo", participantes["fonte_gestor"])
        self.assertEqual("Custodiante Legado", participantes["nm_custodiante"])
        self.assertEqual("fi_cad_legado_fundo", participantes["fonte_custodiante"])

    def test_fetch_fidc_participantes_can_skip_network_on_first_dashboard_render(self) -> None:
        with (
            patch.object(cvm_cadastro, "_read_cached_bytes", return_value=None),
            patch.object(cvm_cadastro.urllib.request, "urlopen") as urlopen_mock,
        ):
            participantes = cvm_cadastro.fetch_fidc_participantes(
                "12.345.678/0001-90",
                cnpj_classe="98.765.432/0001-09",
                allow_network=False,
            )

        urlopen_mock.assert_not_called()
        self.assertEqual("", participantes["nm_admin"])
        self.assertEqual("", participantes["nm_gestor"])
        self.assertEqual("", participantes["nm_custodiante"])

    def test_list_fidc_catalog_prefers_active_and_longer_name(self) -> None:
        fundo_df = pd.DataFrame(
            [
                {
                    "CNPJ_Fundo": "12.345.678/0001-90",
                    "Tipo_Fundo": "FIDC",
                    "Situacao": "Em Funcionamento Normal",
                    "Denominacao_Social": "FIDC Registro Completo",
                },
                {
                    "CNPJ_Fundo": "98.765.432/0001-09",
                    "Tipo_Fundo": "FIDC",
                    "Situacao": "Cancelado",
                    "Denominacao_Social": "FIDC Inativo",
                },
            ]
        )
        classe_df = pd.DataFrame(columns=["CNPJ_Classe", "Tipo_Classe", "Situacao"])
        legacy_df = pd.DataFrame(
            [
                {
                    "CNPJ_FUNDO": "12.345.678/0001-90",
                    "TP_FUNDO": "FIDC",
                    "SIT": "EM FUNCIONAMENTO NORMAL",
                    "DENOM_SOCIAL": "FIDC Curto",
                },
                {
                    "CNPJ_FUNDO": "98.765.432/0001-09",
                    "TP_FUNDO": "FIDC",
                    "SIT": "EM FUNCIONAMENTO NORMAL",
                    "DENOM_SOCIAL": "FIDC Ativo Legado",
                },
            ]
        )

        with (
            patch.object(cvm_cadastro, "_load_registro_fundo_classe", return_value=(fundo_df, classe_df)),
            patch.object(cvm_cadastro, "_load_fi_cad_legacy", return_value=legacy_df),
        ):
            catalog = cvm_cadastro.list_fidc_catalog()

        self.assertEqual({"12345678000190", "98765432000109"}, set(catalog["cnpj_fundo"].tolist()))
        lookup = catalog.set_index("cnpj_fundo")
        self.assertEqual("FIDC Registro Completo", lookup.loc["12345678000190", "nome_fundo"])
        self.assertEqual("FIDC Ativo Legado", lookup.loc["98765432000109", "nome_fundo"])
