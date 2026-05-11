from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import tempfile
from typing import Callable, Iterable

import pandas as pd

from services.fundonet_client import FundosNetClient, only_digits
from services.fundonet_errors import (
    DocumentDownloadError,
    DocumentParseError,
    FundosNetError,
    InvalidCnpjError,
    NoDocumentsFoundError,
)
from services.fundonet_export import (
    append_dataframe_to_csv,
    build_excel_from_csvs,
    build_wide_csv_from_period_csvs,
)
from services.fundonet_models import DocumentoFundo
from services.fundonet_parser import ParsedInformeXml, parse_informe_mensal_xml


ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class InformeMensalResult:
    docs_df: pd.DataFrame
    audit_df: pd.DataFrame
    competencias: list[str]
    workspace_dir: Path
    docs_csv_path: Path
    contas_csv_path: Path
    listas_csv_path: Path
    wide_csv_path: Path
    excel_path: Path
    audit_json_path: Path
    contas_row_count: int
    listas_row_count: int
    wide_row_count: int


class InformeMensalService:
    def __init__(self, client: FundosNetClient | None = None) -> None:
        self.client = client or FundosNetClient()

    def run(
        self,
        cnpj_fundo: str,
        data_inicial: date,
        data_final: date,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> InformeMensalResult:
        audit_rows: list[dict] = []
        workspace_dir = Path(tempfile.mkdtemp(prefix="fundonet-ime-"))
        docs_csv_path = workspace_dir / "documentos_filtrados.csv"
        contas_csv_path = workspace_dir / "informes_tidy.csv"
        listas_csv_path = workspace_dir / "estruturas_lista.csv"
        wide_csv_path = workspace_dir / "informes_wide.csv"
        excel_path = workspace_dir / "informes_wide.xlsx"
        audit_csv_path = workspace_dir / "audit_log.csv"
        audit_json_path = workspace_dir / "audit_log.json"

        def add_audit(etapa: str, status: str, detalhe: str, **extra: object) -> None:
            audit_rows.append({"etapa": etapa, "status": status, "detalhe": detalhe, **extra})

        cnpj = only_digits(cnpj_fundo)
        if not re.fullmatch(r"\d{14}", cnpj):
            raise InvalidCnpjError("CNPJ inválido: informe 14 dígitos.")

        competencia_inicial = _to_competencia(data_inicial)
        competencia_final = _to_competencia(data_final)
        if competencia_inicial > competencia_final:
            raise ValueError("Competência inicial deve ser menor ou igual à competência final.")

        add_audit(
            "validacao_entrada",
            "ok",
            "Entrada validada.",
            cnpj_fundo=cnpj,
            competencia_inicial=competencia_inicial.strftime("%m/%Y"),
            competencia_final=competencia_final.strftime("%m/%Y"),
        )
        _report_progress(progress_callback, 0, 1, "Listando Informes Mensais Estruturados no Fundos.NET...")

        try:
            raw_documentos = self.client.listar_documentos_ime(cnpj, fast_fail=True)
            nome_fundo_resolvido = next((doc.nome_fundo for doc in raw_documentos if doc.nome_fundo), "")
            add_audit(
                "listar_documentos",
                "ok",
                "Listagem pública direta de IMEs concluída por CNPJ.",
                qtd_documentos_brutos=len(raw_documentos),
            )
            add_audit(
                "resolve_fundo",
                "ignorado",
                "Contexto público do fundo não foi aberto porque a listagem direta por CNPJ é suficiente e evita travamentos no endpoint abrirGerenciadorDocumentosCVM.",
                id_fundo="",
                nome_fundo=nome_fundo_resolvido or "",
            )
        except (InvalidCnpjError, ValueError):
            raise
        except FundosNetError as exc:
            current_trace = list(exc.trace)
            current_trace.extend(audit_rows)
            raise exc.__class__(str(exc), details=exc.details, trace=current_trace) from exc

        if not raw_documentos:
            raise NoDocumentsFoundError(
                "Nenhum Informe Mensal Estruturado encontrado para o CNPJ informado.",
                trace=audit_rows,
            )

        documentos_no_intervalo = [
            doc
            for doc in raw_documentos
            if doc.competencia is not None and competencia_inicial <= doc.competencia <= competencia_final
        ]
        add_audit(
            "filtrar_intervalo_competencia",
            "ok",
            "Filtro local por competência aplicado.",
            qtd_documentos_intervalo=len(documentos_no_intervalo),
        )
        if not documentos_no_intervalo:
            raise NoDocumentsFoundError(
                "Nenhum Informe Mensal Estruturado encontrado no intervalo de competências informado.",
                trace=audit_rows,
            )

        documentos_selecionados = select_latest_documents(documentos_no_intervalo)
        documentos_selecionados = sorted(
            documentos_selecionados,
            key=lambda doc: (doc.competencia or date.min, doc.data_entrega_dt or datetime.min, doc.id),
        )
        competencias_processadas = [doc.competencia_label for doc in documentos_selecionados if doc.competencia_label]
        competencias_ordenadas = sorted(
            _dedupe_preserve_order([c for c in competencias_processadas if c]),
            key=_competencia_label_sort_key,
            reverse=True,
        )
        add_audit(
            "deduplicar_retificacoes",
            "ok",
            "Documentos definitivos por competência selecionados.",
            qtd_competencias=len(documentos_selecionados),
        )

        docs_status_rows: list[dict[str, object]] = []
        period_scalar_paths: dict[str, Path] = {}
        contas_row_count = 0
        listas_row_count = 0

        total_docs = len(documentos_selecionados)
        total_steps = total_docs + 2
        for index, doc in enumerate(documentos_selecionados, start=1):
            competencia = doc.competencia_label or doc.data_referencia or ""
            _report_progress(
                progress_callback,
                index - 1,
                total_steps,
                f"Processando {competencia} ({index}/{total_docs})...",
            )
            add_audit(
                "processar_documento",
                "iniciado",
                "Iniciando download e parse do documento.",
                documento_id=doc.id,
                competencia=competencia,
                versao=doc.versao,
                data_entrega=doc.data_entrega or "",
                status_documento=doc.status,
            )
            try:
                xml_bytes = self.client.download_documento(doc.id)
                parsed = parse_informe_mensal_xml(xml_bytes, doc_id=doc.id)
                scalar_df, list_df = self._decorate_parsed_frames(parsed, doc)
                tidy_scalar_df = self._build_tidy_contract(contas_base_df=scalar_df, cnpj_fundo=cnpj)
                period_scalar_path = workspace_dir / f"periodo_{_slugify_period_label(competencia)}_{doc.id}.csv"
                append_dataframe_to_csv(tidy_scalar_df, period_scalar_path, columns=tidy_scalar_df.columns.tolist())
                contas_row_count += append_dataframe_to_csv(
                    tidy_scalar_df,
                    contas_csv_path,
                    columns=tidy_scalar_df.columns.tolist(),
                )
                listas_row_count += append_dataframe_to_csv(
                    list_df,
                    listas_csv_path,
                    columns=list_df.columns.tolist(),
                )
                period_scalar_paths[competencia] = period_scalar_path
                docs_status_rows.append(
                    self._build_doc_status_row(
                        doc,
                        processamento="ok",
                        erro="",
                        competencia_xml=parsed.metadata.get("competencia_xml"),
                        xml_version=parsed.metadata.get("xml_version"),
                    )
                )
                if parsed.metadata.get("competencia_xml") and parsed.metadata.get("competencia_xml") != competencia:
                    add_audit(
                        "validar_competencia_xml",
                        "aviso",
                        "Competência do XML diverge da listagem.",
                        documento_id=doc.id,
                        competencia_listagem=competencia,
                        competencia_xml=parsed.metadata.get("competencia_xml"),
                    )
                add_audit(
                    "processar_documento",
                    "ok",
                    "Documento processado com sucesso.",
                    documento_id=doc.id,
                    competencia=competencia,
                    linhas_escalares=len(tidy_scalar_df),
                    linhas_lista=len(list_df),
                )
            except Exception as exc:  # noqa: BLE001
                docs_status_rows.append(
                    self._build_doc_status_row(
                        doc,
                        processamento="erro",
                        erro=str(exc),
                        competencia_xml=None,
                        xml_version=None,
                    )
                )
                add_audit(
                    "processar_documento",
                    "erro",
                    f"Falha ao processar documento {doc.id}: {exc}",
                    documento_id=doc.id,
                    competencia=competencia,
                )
                continue

        docs_df = pd.DataFrame(docs_status_rows)
        docs_df.to_csv(docs_csv_path, index=False)

        if contas_row_count == 0:
            raise DocumentParseError(
                "Todos os documentos selecionados falharam no download ou parse.",
                trace=audit_rows,
            )

        _report_progress(progress_callback, total_docs, total_steps, "Montando Tabela Completa final em disco...")
        wide_row_count = build_wide_csv_from_period_csvs(
            period_scalar_paths=period_scalar_paths,
            competencias_ordenadas=competencias_ordenadas,
            output_path=wide_csv_path,
            workspace_dir=workspace_dir,
        )
        add_audit(
            "montagem_dataset",
            "ok",
            "CSVs temporários e Tabela Completa final gerados em disco.",
            linhas_escalares=contas_row_count,
            linhas_lista=listas_row_count,
            linhas_wide=wide_row_count,
        )
        audit_df = pd.DataFrame(audit_rows)
        audit_df.to_csv(audit_csv_path, index=False)
        audit_json_path.write_text(
            json.dumps(audit_df.to_dict(orient="records"), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        _report_progress(progress_callback, total_docs + 1, total_steps, "Finalizando workbook Excel em disco...")
        build_excel_from_csvs(
            wide_csv_path=wide_csv_path,
            listas_csv_path=listas_csv_path,
            docs_csv_path=docs_csv_path,
            audit_csv_path=audit_csv_path,
            output_path=excel_path,
        )
        _report_progress(progress_callback, total_steps, total_steps, "Concluído.")
        return InformeMensalResult(
            docs_df=docs_df,
            audit_df=audit_df,
            competencias=competencias_ordenadas,
            workspace_dir=workspace_dir,
            docs_csv_path=docs_csv_path,
            contas_csv_path=contas_csv_path,
            listas_csv_path=listas_csv_path,
            wide_csv_path=wide_csv_path,
            excel_path=excel_path,
            audit_json_path=audit_json_path,
            contas_row_count=contas_row_count,
            listas_row_count=listas_row_count,
            wide_row_count=wide_row_count,
        )

    @staticmethod
    def _decorate_parsed_frames(parsed: ParsedInformeXml, doc: DocumentoFundo) -> tuple[pd.DataFrame, pd.DataFrame]:
        competencia = doc.competencia_label or parsed.metadata.get("competencia_xml") or doc.data_referencia

        scalar_df = parsed.scalar_df.copy()
        if scalar_df.empty:
            scalar_df = pd.DataFrame(columns=parsed.scalar_df.columns.tolist())
        scalar_df["competencia"] = competencia
        scalar_df["data_entrega"] = doc.data_entrega
        scalar_df["versao_documento"] = doc.versao
        scalar_df["status_documento"] = doc.status

        list_df = parsed.list_df.copy()
        if list_df.empty:
            list_df = pd.DataFrame(columns=parsed.list_df.columns.tolist())
        list_df["competencia"] = competencia
        list_df["data_entrega"] = doc.data_entrega
        list_df["versao_documento"] = doc.versao
        list_df["status_documento"] = doc.status
        return scalar_df, list_df

    @staticmethod
    def _build_doc_status_row(
        doc: DocumentoFundo,
        *,
        processamento: str,
        erro: str,
        competencia_xml: str | None,
        xml_version: str | None,
    ) -> dict[str, object]:
        return {
            "documento_id": doc.id,
            "competencia": doc.competencia_label or doc.data_referencia,
            "data_referencia": doc.data_referencia,
            "competencia_xml": competencia_xml,
            "data_entrega": doc.data_entrega,
            "versao": doc.versao,
            "status_documento": doc.status,
            "categoria": doc.categoria,
            "tipo": doc.tipo,
            "especie": doc.especie,
            "fundo_ou_classe": doc.fundo_ou_classe,
            "nome_fundo": doc.nome_fundo,
            "nome_administrador": doc.nome_administrador,
            "nome_custodiante": doc.nome_custodiante,
            "nome_gestor": doc.nome_gestor,
            "xml_version": xml_version,
            "processamento": processamento,
            "erro_processamento": erro,
        }

    @staticmethod
    def _build_tidy_contract(contas_base_df: pd.DataFrame, cnpj_fundo: str) -> pd.DataFrame:
        base_columns = [
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
        if contas_base_df.empty:
            return pd.DataFrame(columns=base_columns)

        required_columns = [
            "documento_id",
            "competencia",
            "bloco",
            "sub_bloco",
            "tag",
            "tag_path",
            "descricao",
            "valor_raw",
            "valor_num",
            "ordem_xml",
            "valor_excel",
        ]
        missing_columns = [column for column in required_columns if column not in contas_base_df.columns]
        if missing_columns:
            missing = ", ".join(missing_columns)
            raise ValueError(f"Contrato inválido do parser: colunas ausentes em contas_base_df: {missing}")

        tidy_df = contas_base_df.copy()
        tidy_df["cnpj_fundo"] = cnpj_fundo
        tidy_df["fonte"] = "fundonet"
        extra_columns = [column for column in tidy_df.columns if column not in base_columns]
        return tidy_df[base_columns + extra_columns]


def select_latest_documents(documentos: Iterable[DocumentoFundo]) -> list[DocumentoFundo]:
    grouped: dict[str, list[DocumentoFundo]] = {}
    for doc in documentos:
        if not doc.competencia_label:
            continue
        grouped.setdefault(doc.competencia_label, []).append(doc)

    selected: list[DocumentoFundo] = []
    for competencia, docs in grouped.items():
        best = max(
            docs,
            key=lambda doc: (
                1 if doc.is_active else 0,
                doc.versao,
                doc.data_entrega_dt or datetime.min,
                doc.id,
            ),
        )
        selected.append(best)
    return selected


def is_informe_mensal_estruturado(doc: DocumentoFundo) -> bool:
    text = " ".join([doc.categoria, doc.tipo, doc.especie, doc.nome_arquivo or ""]).upper()
    return "INFORME" in text and "MENSAL" in text and "ESTRUTUR" in text


def _to_competencia(raw_date: date) -> date:
    return date(raw_date.year, raw_date.month, 1)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _competencia_label_sort_key(value: str) -> tuple[int, int]:
    month, year = str(value).split("/", 1)
    return int(year), int(month)


def _report_progress(callback: ProgressCallback | None, current: int, total: int, message: str) -> None:
    if callback is None:
        return
    callback(current, total, message)


def _slugify_period_label(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return normalized.strip("._") or "periodo"
