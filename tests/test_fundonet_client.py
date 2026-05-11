from __future__ import annotations

import base64
from datetime import datetime
import unittest

from services.fundonet_client import FundosNetClient, _decode_download_payload
from services.fundonet_documents import build_document_filename, select_latest_public_document
from services.fundonet_models import DocumentoFundo


class FundosNetClientTests(unittest.TestCase):
    def test_timeout_and_retry_are_relaxed_for_catalog_stages(self) -> None:
        client = FundosNetClient(timeout_seconds=30, max_retries=2)

        self.assertEqual(45, client._timeout_for_stage("abrir_gerenciador"))
        self.assertEqual(45, client._timeout_for_stage("listar_documentos"))
        self.assertEqual(3, client._retry_limit_for_stage("abrir_gerenciador"))
        self.assertEqual(3, client._retry_limit_for_stage("listar_documentos"))

    def test_timeout_defaults_remain_for_other_stages(self) -> None:
        client = FundosNetClient(timeout_seconds=30, max_retries=2)

        self.assertEqual(40, client._timeout_for_stage("download_documento"))
        self.assertEqual(30, client._timeout_for_stage("qualquer_outra_etapa"))
        self.assertEqual(2, client._retry_limit_for_stage("download_documento"))

    def test_fast_listing_policy_caps_timeout_and_retries(self) -> None:
        client = FundosNetClient(timeout_seconds=30, max_retries=2)

        self.assertEqual(20, client._timeout_for_stage("listar_documentos_fast"))
        self.assertEqual(1, client._retry_limit_for_stage("listar_documentos_fast"))

    def test_decode_download_payload_accepts_quoted_base64_pdf(self) -> None:
        pdf_bytes = b"%PDF-1.7\n%mock-pdf\n"
        quoted = f'"{base64.b64encode(pdf_bytes).decode("ascii")}"'.encode("utf-8")

        decoded = _decode_download_payload(quoted)

        self.assertEqual(pdf_bytes, decoded)

    def test_select_latest_public_document_prefers_active_newer_reference_and_delivery(self) -> None:
        older = DocumentoFundo(
            id=100,
            categoria="Regulamento",
            tipo="",
            especie="",
            data_referencia="28/11/2024",
            data_entrega="28/11/2024 17:49",
            nome_fundo="Fundo Teste",
            nome_arquivo=None,
            versao=1,
            status="AC",
            fundo_ou_classe="Classe",
            raw={},
        )
        newer = DocumentoFundo(
            id=200,
            categoria="Regulamento",
            tipo="",
            especie="",
            data_referencia="19/05/2025",
            data_entrega="21/05/2025 15:50",
            nome_fundo="Fundo Teste",
            nome_arquivo=None,
            versao=1,
            status="AC",
            fundo_ou_classe="Classe",
            raw={},
        )
        inactive = DocumentoFundo(
            id=300,
            categoria="Regulamento",
            tipo="",
            especie="",
            data_referencia="20/06/2025",
            data_entrega="20/06/2025 08:00",
            nome_fundo="Fundo Teste",
            nome_arquivo=None,
            versao=1,
            status="IN",
            fundo_ou_classe="Classe",
            raw={},
        )

        selected = select_latest_public_document([older, newer, inactive])

        self.assertIsNotNone(selected)
        self.assertEqual(200, selected.id)

    def test_build_document_filename_falls_back_to_regulamento_pdf(self) -> None:
        doc = DocumentoFundo(
            id=123,
            categoria="Regulamento",
            tipo="",
            especie="",
            data_referencia="19/05/2025",
            data_entrega=datetime(2025, 5, 21, 15, 50).strftime("%d/%m/%Y %H:%M"),
            nome_fundo="Fundo Teste",
            nome_arquivo="",
            versao=1,
            status="AC",
            fundo_ou_classe="Classe",
            raw={},
        )

        file_name = build_document_filename(doc, default_stem="regulamento_50473039000102")

        self.assertEqual("regulamento_50473039000102_2025-05-19.pdf", file_name)


if __name__ == "__main__":
    unittest.main()
