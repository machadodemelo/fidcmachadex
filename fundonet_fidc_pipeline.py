from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import shutil

from services.fundonet_errors import FundosNetError
from services.fundonet_service import InformeMensalService


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def parse_period_label(label: str) -> datetime:
    """Aceita Jan-25, 01/2025, 2025-01 etc e converte para primeiro dia do mês."""
    s = (label or "").strip()
    for fmt in ("%b-%y", "%m/%Y", "%Y-%m", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return datetime(dt.year, dt.month, 1)
        except ValueError:
            continue
    raise ValueError(f"Período inválido: {label!r}")


def run_pipeline(cnpj_fundo: str, periodo_inicio: str, periodo_fim: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    inicio = parse_period_label(periodo_inicio).date()
    fim = parse_period_label(periodo_fim).date()

    if inicio > fim:
        raise ValueError("periodo_inicio deve ser <= periodo_fim")

    service = InformeMensalService()
    result = service.run(cnpj_fundo=cnpj_fundo, data_inicial=inicio, data_final=fim)

    shutil.copyfile(result.docs_csv_path, output_dir / "documentos_filtrados.csv")
    shutil.copyfile(result.contas_csv_path, output_dir / "informes_tidy.csv")
    shutil.copyfile(result.listas_csv_path, output_dir / "estruturas_lista.csv")
    shutil.copyfile(result.audit_json_path, output_dir / "audit_log.json")

    xlsx_path = output_dir / "informes_wide.xlsx"
    shutil.copyfile(result.excel_path, xlsx_path)

    run_metadata = {
        "run_id": datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%S%fZ"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "cnpj_fundo": only_digits(cnpj_fundo),
        "data_inicial": inicio.isoformat(),
        "data_final": fim.isoformat(),
        "source_selected": "fundonet",
        "documents_found": int(len(result.docs_df)),
        "documents_processed": int(
            result.audit_df[
                (result.audit_df["etapa"] == "processar_documento") & (result.audit_df["status"] == "ok")
            ].shape[0]
        ),
        "documents_failed": int(
            result.audit_df[
                (result.audit_df["etapa"] == "processar_documento") & (result.audit_df["status"] == "erro")
            ].shape[0]
        ),
        "parser_version": "fundonet_parser.flatten_xml_contas.v1",
        "app_version": "fundonet_fidc_pipeline.wrapper.v1",
        "outputs": {
            "docs_csv": "documentos_filtrados.csv",
            "tidy_csv": "informes_tidy.csv",
            "list_csv": "estruturas_lista.csv",
            "wide_xlsx": "informes_wide.xlsx",
            "audit_json": "audit_log.json",
        },
    }

    with (output_dir / "run_metadata.json").open("w", encoding="utf-8") as fp:
        json.dump(run_metadata, fp, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Pipeline Fundos.NET (wrapper do InformeMensalService): lista documentos, "
            "baixa XML de Informes Mensais Estruturados e gera artefatos tidy/wide/auditoria."
        )
    )
    parser.add_argument("--cnpj-fundo", required=True, help="CNPJ do fundo (com ou sem máscara)")
    parser.add_argument("--periodo-inicio", required=True, help="Ex: Jan-25, 01/2025 ou 2025-01")
    parser.add_argument("--periodo-fim", required=True, help="Ex: Jan-26, 01/2026 ou 2026-01")
    parser.add_argument("--output-dir", default="saida_fundonet", help="Diretório de saída")
    args = parser.parse_args()

    try:
        run_pipeline(
            cnpj_fundo=args.cnpj_fundo,
            periodo_inicio=args.periodo_inicio,
            periodo_fim=args.periodo_fim,
            output_dir=Path(args.output_dir),
        )
    except FundosNetError as exc:
        raise SystemExit(f"Falha na integração Fundos.NET: {exc}") from exc


if __name__ == "__main__":
    main()
