from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re

from services.fundonet_client import FundosNetClient, REGULAMENTO_CATEGORIA_ID
from services.fundonet_models import DocumentoFundo


@dataclass(frozen=True)
class LatestFundDocument:
    document: DocumentoFundo
    content: bytes
    file_name: str


def select_latest_public_document(documentos: list[DocumentoFundo]) -> DocumentoFundo | None:
    if not documentos:
        return None
    return max(
        documentos,
        key=lambda doc: (
            1 if doc.is_active else 0,
            doc.data_referencia_dt or date.min,
            doc.data_entrega_dt or datetime.min,
            doc.versao,
            doc.id,
        ),
    )


def build_document_filename(doc: DocumentoFundo, *, default_stem: str) -> str:
    raw_name = str(doc.nome_arquivo or "").strip()
    if raw_name:
        return raw_name
    suffix = ".pdf"
    stem_slug = re.sub(r"[^A-Za-z0-9._-]+", "_", default_stem.strip()).strip("._") or "documento"
    date_part = ""
    if doc.data_referencia_dt is not None:
        date_part = f"_{doc.data_referencia_dt.isoformat()}"
    return f"{stem_slug}{date_part}{suffix}"


def fetch_latest_regulamento_document(
    cnpj_fundo: str,
    *,
    client: FundosNetClient | None = None,
) -> LatestFundDocument | None:
    resolved_client = client or FundosNetClient()
    documentos = resolved_client.listar_documentos(
        cnpj_fundo,
        categoria_id=REGULAMENTO_CATEGORIA_ID,
    )
    latest = select_latest_public_document(documentos)
    if latest is None:
        return None
    content = resolved_client.download_documento(latest.id)
    return LatestFundDocument(
        document=latest,
        content=content,
        file_name=build_document_filename(latest, default_stem=f"regulamento_{cnpj_fundo}"),
    )
