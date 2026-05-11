from __future__ import annotations

from datetime import date, datetime
import unittest
from unittest.mock import patch

import pandas as pd

from services.fundonet_models import DocumentoFundo
from services.fundonet_parser import LIST_COLUMNS, ParsedInformeXml, SCALAR_COLUMNS
from services.fundonet_service import InformeMensalService, select_latest_documents


class _FakeClient:
    def __init__(self, docs: list[DocumentoFundo]) -> None:
        self._docs = docs
        self.resolve_calls = 0
        self.fast_fail_values: list[bool] = []

    def resolve_fundo(self, cnpj_fundo: str):  # noqa: ANN001
        self.resolve_calls += 1
        return type("Resolution", (), {"id_fundo": "18252", "nome_fundo": "Teste"})()

    def listar_documentos_ime(self, cnpj_fundo: str, *, fast_fail: bool = False) -> list[DocumentoFundo]:
        self.fast_fail_values.append(fast_fail)
        return list(self._docs)

    def download_documento(self, doc_id: int) -> bytes:
        return f"<documento id='{doc_id}' />".encode("utf-8")


def _build_scalar_df(doc_id: int, competencia_xml: str, rows: list[dict[str, object]]) -> pd.DataFrame:
    payload = []
    for row in rows:
        payload.append(
            {
                "documento_id": doc_id,
                "competencia_xml": competencia_xml,
                "xml_version": "1.0",
                "bloco": row["bloco"],
                "sub_bloco": row["sub_bloco"],
                "tag": row["tag"],
                "tag_path": row["tag_path"],
                "field_path": row["tag_path"],
                "schema_path_match": row["tag_path"],
                "schema_match_strategy": "exact",
                "descricao": row["descricao"],
                "valor_raw": row["valor_raw"],
                "valor_num": row["valor_num"],
                "valor_excel": row["valor_excel"],
                "ordem_xml": row["ordem_xml"],
            }
        )
    return pd.DataFrame(payload, columns=SCALAR_COLUMNS)


def _build_list_df(doc_id: int, competencia_xml: str, rows: list[dict[str, object]]) -> pd.DataFrame:
    payload = []
    for row in rows:
        payload.append(
            {
                "documento_id": doc_id,
                "competencia_xml": competencia_xml,
                "xml_version": "1.0",
                "bloco": row["bloco"],
                "sub_bloco": row["sub_bloco"],
                "list_group_path": row["list_group_path"],
                "list_item_path": row["list_item_path"],
                "list_item_tag": row["list_item_tag"],
                "list_index": row["list_index"],
                "tag": row["tag"],
                "tag_path": row["tag_path"],
                "field_path": row["tag_path"],
                "schema_path_match": row["tag_path"],
                "schema_match_strategy": "exact",
                "descricao": row["descricao"],
                "valor_raw": row["valor_raw"],
                "valor_num": row["valor_num"],
                "valor_excel": row["valor_excel"],
                "ordem_xml": row["ordem_xml"],
            }
        )
    return pd.DataFrame(payload, columns=LIST_COLUMNS)


class BuildTidyContractTests(unittest.TestCase):
    def test_keep_required_columns_and_preserve_extra_columns(self) -> None:
        contas_base_df = pd.DataFrame(
            [
                {
                    "documento_id": 10,
                    "competencia": "01/2026",
                    "bloco": "APLIC_ATIVO",
                    "sub_bloco": "CRED_EXISTE",
                    "tag": "VL_DISPONIB",
                    "tag_path": "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/VL_DISPONIB",
                    "descricao": "VALOR DAS DISPONIBILIDADES",
                    "valor_raw": "123,45",
                    "valor_num": 123.45,
                    "valor_excel": 123.45,
                    "ordem_xml": 12,
                    "schema_match_strategy": "exact",
                }
            ]
        )

        tidy_df = InformeMensalService._build_tidy_contract(contas_base_df=contas_base_df, cnpj_fundo="33254370000104")

        expected_prefix = [
            "cnpj_fundo",
            "documento_id",
            "competencia",
            "bloco",
            "sub_bloco",
            "tag",
            "tag_path",
            "descricao",
            "valor_raw",
            "valor_num",
            "fonte",
        ]
        self.assertEqual(expected_prefix, tidy_df.columns.tolist()[: len(expected_prefix)])
        self.assertIn("schema_match_strategy", tidy_df.columns.tolist())
        self.assertEqual("33254370000104", tidy_df.iloc[0]["cnpj_fundo"])
        self.assertEqual("fundonet", tidy_df.iloc[0]["fonte"])

    def test_raise_explicit_error_when_parser_contract_is_invalid(self) -> None:
        contas_base_df = pd.DataFrame(
            [
                {
                    "documento_id": 10,
                    "competencia": "01/2026",
                    "bloco": "APLIC_ATIVO",
                    "sub_bloco": "",
                    "tag": "VL_DISPONIB",
                    "tag_path": "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/VL_DISPONIB",
                    "descricao": "VALOR DAS DISPONIBILIDADES",
                    "valor_raw": "123,45",
                    "valor_num": 123.45,
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "colunas ausentes em contas_base_df: ordem_xml, valor_excel"):
            InformeMensalService._build_tidy_contract(contas_base_df=contas_base_df, cnpj_fundo="33254370000104")


class SelectLatestDocumentsTests(unittest.TestCase):
    def test_prefer_active_highest_version_latest_delivery(self) -> None:
        base = {
            "categoria": "Informes Periódicos",
            "tipo": "Informe Mensal Estruturado ",
            "especie": "",
            "nome_fundo": "Teste",
            "nome_arquivo": None,
            "fundo_ou_classe": "Fundo",
            "raw": {},
        }
        docs = [
            DocumentoFundo(
                id=973064,
                data_referencia="07/2025",
                data_entrega="15/08/2025 17:48",
                versao=1,
                status="IC",
                **base,
            ),
            DocumentoFundo(
                id=975452,
                data_referencia="07/2025",
                data_entrega="21/08/2025 09:25",
                versao=2,
                status="IC",
                **base,
            ),
            DocumentoFundo(
                id=984542,
                data_referencia="07/2025",
                data_entrega="05/09/2025 10:40",
                versao=3,
                status="AC",
                **base,
            ),
        ]

        selected = select_latest_documents(docs)

        self.assertEqual(1, len(selected))
        self.assertEqual(984542, selected[0].id)
        self.assertEqual(datetime(2025, 9, 5, 10, 40), selected[0].data_entrega_dt)


class ChunkedInformeMensalRunTests(unittest.TestCase):
    def test_run_persists_period_chunks_and_builds_outputs_from_disk(self) -> None:
        base = {
            "categoria": "Informes Periódicos",
            "tipo": "Informe Mensal Estruturado ",
            "especie": "",
            "nome_fundo": "Teste",
            "nome_arquivo": None,
            "fundo_ou_classe": "Fundo",
            "raw": {},
        }
        docs = [
            DocumentoFundo(
                id=101,
                data_referencia="01/2026",
                data_entrega="10/02/2026 09:00",
                versao=1,
                status="AC",
                **base,
            ),
            DocumentoFundo(
                id=102,
                data_referencia="02/2026",
                data_entrega="10/03/2026 09:00",
                versao=1,
                status="AC",
                **base,
            ),
        ]
        parsed_by_doc = {
            101: ParsedInformeXml(
                metadata={"competencia_xml": "01/2026", "xml_version": "1.0"},
                scalar_df=_build_scalar_df(
                    101,
                    "01/2026",
                    [
                        {
                            "bloco": "CARTEIRA",
                            "sub_bloco": "",
                            "tag": "VL_CARTEIRA",
                            "tag_path": "DOC/LISTA/CARTEIRA/VL_CARTEIRA",
                            "descricao": "Valor da carteira",
                            "valor_raw": "100.0",
                            "valor_num": 100.0,
                            "valor_excel": 100.0,
                            "ordem_xml": 1,
                        },
                        {
                            "bloco": "CARTEIRA",
                            "sub_bloco": "",
                            "tag": "NM_SERIE",
                            "tag_path": "DOC/LISTA/CARTEIRA/NM_SERIE",
                            "descricao": "Nome da série",
                            "valor_raw": "Serie A",
                            "valor_num": pd.NA,
                            "valor_excel": "Serie A",
                            "ordem_xml": 2,
                        },
                    ],
                ),
                list_df=_build_list_df(101, "01/2026", []),
            ),
            102: ParsedInformeXml(
                metadata={"competencia_xml": "02/2026", "xml_version": "1.0"},
                scalar_df=_build_scalar_df(
                    102,
                    "02/2026",
                    [
                        {
                            "bloco": "CARTEIRA",
                            "sub_bloco": "",
                            "tag": "VL_CARTEIRA",
                            "tag_path": "DOC/LISTA/CARTEIRA/VL_CARTEIRA",
                            "descricao": "Valor da carteira",
                            "valor_raw": "110.0",
                            "valor_num": 110.0,
                            "valor_excel": 110.0,
                            "ordem_xml": 1,
                        },
                        {
                            "bloco": "CARTEIRA",
                            "sub_bloco": "",
                            "tag": "NM_SERIE",
                            "tag_path": "DOC/LISTA/CARTEIRA/NM_SERIE",
                            "descricao": "Nome da série",
                            "valor_raw": "Serie B",
                            "valor_num": pd.NA,
                            "valor_excel": "Serie B",
                            "ordem_xml": 2,
                        },
                        {
                            "bloco": "PASSIVO",
                            "sub_bloco": "",
                            "tag": "VL_PASSIVO",
                            "tag_path": "DOC/LISTA/PASSIVO/VL_PASSIVO",
                            "descricao": "Valor do passivo",
                            "valor_raw": "20.0",
                            "valor_num": 20.0,
                            "valor_excel": 20.0,
                            "ordem_xml": 3,
                        },
                    ],
                ),
                list_df=_build_list_df(
                    102,
                    "02/2026",
                    [
                        {
                            "bloco": "CEDENTE",
                            "sub_bloco": "",
                            "list_group_path": "DOC/LISTA/CEDENTE",
                            "list_item_path": "DOC/LISTA/CEDENTE[1]",
                            "list_item_tag": "CEDENTE",
                            "list_index": 1,
                            "tag": "NM_CEDENTE",
                            "tag_path": "DOC/LISTA/CEDENTE/NM_CEDENTE",
                            "descricao": "Nome do cedente",
                            "valor_raw": "Cedente XPTO",
                            "valor_num": pd.NA,
                            "valor_excel": "Cedente XPTO",
                            "ordem_xml": 4,
                        }
                    ],
                ),
            ),
        }
        progress_events: list[tuple[int, int, str]] = []

        def _fake_parse(_: bytes, doc_id: int) -> ParsedInformeXml:
            return parsed_by_doc[doc_id]

        fake_client = _FakeClient(docs)
        service = InformeMensalService(client=fake_client)
        with patch("services.fundonet_service.parse_informe_mensal_xml", side_effect=_fake_parse):
            result = service.run(
                cnpj_fundo="33.254.370/0001-04",
                data_inicial=date(2026, 1, 1),
                data_final=date(2026, 2, 1),
                progress_callback=lambda current, total, message: progress_events.append((current, total, message)),
            )

        self.assertEqual(0, fake_client.resolve_calls)
        self.assertEqual([True], fake_client.fast_fail_values)
        self.assertEqual(["02/2026", "01/2026"], result.competencias)
        self.assertTrue(result.docs_csv_path.exists())
        self.assertTrue(result.contas_csv_path.exists())
        self.assertTrue(result.listas_csv_path.exists())
        self.assertTrue(result.wide_csv_path.exists())
        self.assertTrue(result.excel_path.exists())
        self.assertTrue(result.audit_json_path.exists())
        self.assertEqual(5, result.contas_row_count)
        self.assertEqual(1, result.listas_row_count)
        self.assertEqual(3, result.wide_row_count)

        wide_df = pd.read_csv(result.wide_csv_path)
        self.assertEqual(["bloco", "sub_bloco", "tag", "tag_path", "descricao", "02/2026", "01/2026"], wide_df.columns.tolist())
        self.assertEqual(3, len(wide_df))
        carteira_row = wide_df[wide_df["tag"] == "VL_CARTEIRA"].iloc[0]
        self.assertEqual("100.0", carteira_row["01/2026"])
        self.assertEqual("110.0", carteira_row["02/2026"])
        passivo_row = wide_df[wide_df["tag"] == "VL_PASSIVO"].iloc[0]
        self.assertTrue(pd.isna(passivo_row["01/2026"]))
        self.assertEqual("20.0", passivo_row["02/2026"])

        self.assertEqual((4, 4, "Concluído."), progress_events[-1])
        self.assertIn("Listando Informes Mensais Estruturados no Fundos.NET...", [event[2] for event in progress_events])
        self.assertNotIn("Abrindo contexto público do fundo...", [event[2] for event in progress_events])
        self.assertIn("Montando Tabela Completa final em disco...", [event[2] for event in progress_events])
        self.assertIn("Finalizando workbook Excel em disco...", [event[2] for event in progress_events])


if __name__ == "__main__":
    unittest.main()
