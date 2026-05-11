from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.fundonet_client import FundosNetClient  # noqa: E402
from services.fundonet_documents import build_document_filename  # noqa: E402
from services.fundonet_models import DocumentoFundo  # noqa: E402
from services.regulatory_knowledge import (  # noqa: E402
    FundConfig,
    REGULATORY_KNOWLEDGE_DIR,
    REGULATORY_RAW_DIR,
    classify_document,
    common_criteria_summary,
    document_inventory_rows,
    emission_rows,
    extracted_criteria_rows,
    format_cnpj,
    knowledge_summary_rows,
    load_regulatory_knowledge,
    load_funds_config,
    monitoring_hint_for_key,
    normalize_cnpj,
    should_download_document,
    utc_now_iso,
)


EXTRACTION_SCHEMA_VERSION = 1

logging.getLogger("pypdf").setLevel(logging.ERROR)


def main() -> None:
    args = _parse_args()
    if args.skip_llm:
        args.extractor = "none"
    funds = _select_funds(load_funds_config(args.config), only_cnpjs=args.only_cnpj, limit=args.limit_funds)
    if not funds:
        raise SystemExit(f"Nenhum fundo encontrado em {args.config}.")

    client = FundosNetClient(timeout_seconds=args.timeout_seconds)
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.extractions_dir.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.reports_dir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    for fund_index, fund in enumerate(funds, start=1):
        print(f"[{fund_index}/{len(funds)}] {fund.cnpj} · {fund.name}")
        documents = client.listar_documentos(fund.cnpj, error_stage="listar_documentos_regulatory_knowledge")
        selected_documents = _prepare_documents(
            documents,
            include_ime=args.include_ime,
            limit_docs=args.limit_docs,
        )
        downloaded = _download_selected_documents(
            client=client,
            fund=fund,
            documents=selected_documents,
            raw_dir=args.raw_dir,
            include_ime=args.include_ime,
        )
        extractions = []
        if args.extractor != "none":
            for doc, pdf_path, classification in downloaded:
                extraction = _extract_or_read_document_local(
                    fund=fund,
                    document=doc,
                    pdf_path=pdf_path,
                    classification=classification,
                    extractions_dir=args.extractions_dir,
                    force=args.force,
                    max_pages=args.max_pages,
                )
                extractions.append(extraction)
        knowledge_path = _write_fund_knowledge(
            fund=fund,
            documents=selected_documents,
            downloaded=downloaded,
            extractions=extractions,
            out_dir=args.out_dir,
        )
        generated.append(knowledge_path)

    _write_reports(args.out_dir, reports_dir=args.reports_dir)
    print(f"Conhecimento regulatório gerado para {len(generated)} fundo(s).")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Baixa documentos CVM/FNET e monta base regulatória histórica por FIDC.")
    parser.add_argument("--config", type=Path, default=Path("config/funds.yaml"))
    parser.add_argument("--raw-dir", type=Path, default=REGULATORY_RAW_DIR)
    parser.add_argument("--extractions-dir", type=Path, default=Path("data/regulatory_extractions"))
    parser.add_argument("--out-dir", type=Path, default=REGULATORY_KNOWLEDGE_DIR)
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument(
        "--extractor",
        choices=("local", "none"),
        default="local",
        help="Modo de extração. local usa texto/regex auditável; none só inventaria.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--max-pages", type=int, default=80, help="Máximo de páginas extraídas por PDF no modo local.")
    parser.add_argument("--skip-llm", action="store_true", help="Alias legado para --extractor none.")
    parser.add_argument("--include-ime", action="store_true", help="Também baixa Informes Mensais; por padrão eles ficam só no inventário.")
    parser.add_argument("--force", action="store_true", help="Reprocessa extrações existentes.")
    parser.add_argument("--limit-funds", type=int, default=0)
    parser.add_argument("--limit-docs", type=int, default=0)
    parser.add_argument("--only-cnpj", action="append", default=[])
    return parser.parse_args()


def _select_funds(funds: list[FundConfig], *, only_cnpjs: list[str], limit: int) -> list[FundConfig]:
    wanted = {normalize_cnpj(item) for item in only_cnpjs if normalize_cnpj(item)}
    selected = [fund for fund in funds if not wanted or fund.cnpj in wanted]
    if limit and limit > 0:
        selected = selected[:limit]
    return selected


def _prepare_documents(
    documents: list[DocumentoFundo],
    *,
    include_ime: bool,
    limit_docs: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc in documents:
        classification = classify_document(
            categoria=doc.categoria,
            tipo=doc.tipo,
            especie=doc.especie,
            nome_arquivo=doc.nome_arquivo or "",
        )
        if classification == "informe_mensal" and not include_ime:
            continue
        download = should_download_document(classification, include_ime=include_ime)
        rows.append(
            {
                "document": doc,
                "classification": classification,
                "download": download,
                "download_error": "",
            }
        )
    rows = sorted(
        rows,
        key=lambda row: (
            _date_sort_key(row["document"].data_referencia_dt),
            _datetime_sort_key(row["document"].data_entrega_dt),
            row["document"].id,
        ),
    )
    if limit_docs and limit_docs > 0:
        rows = rows[:limit_docs]
    return rows


def _download_selected_documents(
    *,
    client: FundosNetClient,
    fund: FundConfig,
    documents: list[dict[str, Any]],
    raw_dir: Path,
    include_ime: bool,
) -> list[tuple[DocumentoFundo, Path, str]]:
    fund_dir = raw_dir / fund.cnpj
    fund_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[tuple[DocumentoFundo, Path, str]] = []
    for item in documents:
        if not item["download"]:
            continue
        doc: DocumentoFundo = item["document"]
        classification = str(item["classification"])
        if classification == "informe_mensal" and not include_ime:
            continue
        path = fund_dir / _document_storage_name(doc, classification=classification)
        if not path.exists():
            print(f"  download {classification}: {path.name}")
            try:
                path.write_bytes(client.download_documento(doc.id))
            except Exception as exc:  # noqa: BLE001
                item["download_error"] = f"{type(exc).__name__}: {exc}"
                print(f"  erro download {doc.id}: {item['download_error']}")
                continue
        else:
            print(f"  cache {classification}: {path.name}")
        downloaded.append((doc, path, classification))
    return downloaded


def _extract_or_read_document_local(
    *,
    fund: FundConfig,
    document: DocumentoFundo,
    pdf_path: Path,
    classification: str,
    extractions_dir: Path,
    force: bool,
    max_pages: int,
) -> dict[str, Any]:
    out_dir = extractions_dir / fund.cnpj
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{document.id}.local.json"
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"  local {classification}: {pdf_path.name}")
    try:
        text, method = _extract_pdf_text(pdf_path, max_pages=max_pages)
        normalized = _normalize_extraction(
            _extract_local_structured_payload(text, method=method, classification=classification),
            fund=fund,
            document=document,
            pdf_path=pdf_path,
            classification=classification,
        )
    except Exception as exc:  # noqa: BLE001
        normalized = _error_extraction(
            fund=fund,
            document=document,
            pdf_path=pdf_path,
            classification=classification,
            error=f"{type(exc).__name__}: {exc}",
        )
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def _extract_pdf_text(pdf_path: Path, *, max_pages: int) -> tuple[str, str]:
    max_pages = max(int(max_pages or 0), 1)
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]

        reader = PdfReader(str(pdf_path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:max_pages]).strip()
        if text:
            return text, f"pypdf_primeiras_{min(len(reader.pages), max_pages)}_paginas"
    except Exception:
        pass

    try:
        import pdfplumber  # type: ignore[import-not-found]

        parts = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:max_pages]:
                parts.append(page.extract_text(x_tolerance=1, y_tolerance=3) or "")
        text = "\n".join(parts).strip()
        if text:
            return text, f"pdfplumber_primeiras_{max_pages}_paginas"
    except Exception as exc:
        raise RuntimeError(f"Não foi possível extrair texto do PDF {pdf_path.name}: {exc}") from exc

    raise RuntimeError(f"PDF sem texto extraível: {pdf_path.name}")


LOCAL_RULES: tuple[dict[str, Any], ...] = (
    {
        "canonical_key": "subordination_ratio_min",
        "name": "Subordinação mínima",
        "event_type": "enquadramento",
        "keywords": ("subordinação", "subordinacao", "índice de subordinação", "indice de subordinacao"),
        "context": ("mínim", "minim", "inferior", "relação", "razao", "razão"),
        "comparison": ">=",
    },
    {
        "canonical_key": "default_rate_early_maturity",
        "name": "Atraso/Inadimplência - vencimento antecipado",
        "event_type": "vencimento_antecipado",
        "keywords": ("vencimento antecipado",),
        "context": ("inadimpl", "atras", "vencid", "over"),
        "comparison": "<=",
    },
    {
        "canonical_key": "default_rate_evaluation_event",
        "name": "Atraso/Inadimplência - evento de avaliação",
        "event_type": "avaliação",
        "keywords": ("evento de avaliação", "evento de avaliacao"),
        "context": ("inadimpl", "atras", "vencid", "over"),
        "comparison": "<=",
    },
    {
        "canonical_key": "pdd_coverage_min",
        "name": "Cobertura mínima de PDD/provisão",
        "event_type": "enquadramento",
        "keywords": ("pdd", "provisão", "provisao", "cobertura"),
        "context": ("mínim", "minim", "inadimpl", "vencid", "over"),
        "comparison": ">=",
    },
    {
        "canonical_key": "credit_rights_allocation_min",
        "name": "Alocação mínima em direitos creditórios",
        "event_type": "enquadramento",
        "keywords": ("alocação mínima", "alocacao minima", "direitos creditórios", "direitos creditorios"),
        "context": ("mínim", "minim", "patrimônio líquido", "patrimonio liquido", "pl"),
        "comparison": ">=",
    },
    {
        "canonical_key": "recompras_max",
        "name": "Limite de recompra",
        "event_type": "enquadramento",
        "keywords": ("recompra", "recompras"),
        "context": ("máxim", "maxim", "limite", "percentual"),
        "comparison": "<=",
    },
    {
        "canonical_key": "minimum_cash_ratio",
        "name": "Reserva ou caixa mínimo",
        "event_type": "enquadramento",
        "keywords": ("reserva de liquidez", "caixa mínimo", "caixa minimo", "disponibilidades"),
        "context": ("mínim", "minim", "amortização", "amortizacao", "despesas"),
        "comparison": ">=",
    },
    {
        "canonical_key": "dilution_rate_max",
        "name": "Diluição máxima",
        "event_type": "enquadramento",
        "keywords": ("diluição", "diluicao"),
        "context": ("máxim", "maxim", "limite", "percentual"),
        "comparison": "<=",
    },
    {
        "canonical_key": "chargeback_rate_max",
        "name": "Chargeback/contestação máxima",
        "event_type": "enquadramento",
        "keywords": ("chargeback", "contestação", "contestacao"),
        "context": ("máxim", "maxim", "limite", "percentual"),
        "comparison": "<=",
    },
    {
        "canonical_key": "concentration_limits",
        "name": "Limite de concentração",
        "event_type": "elegibilidade",
        "keywords": ("concentração", "concentracao"),
        "context": ("cedente", "sacado", "grupo econômico", "grupo economico", "devedor"),
        "comparison": "<=",
    },
    {
        "canonical_key": "permitted_hedges",
        "name": "Hedges/derivativos permitidos",
        "event_type": "enquadramento",
        "keywords": ("hedge", "swap", "derivativo", "derivativos", "ndf"),
        "context": ("permitid", "vedad", "proteção", "protecao"),
        "comparison": "texto",
    },
)


def _extract_local_structured_payload(text: str, *, method: str, classification: str) -> dict[str, Any]:
    normalized_text = _normalize_pdf_text(text)
    return {
        "document_summary": f"Extração local por {method}; classificação {classification}.",
        "effective_date": None,
        "criteria": _extract_local_criteria(normalized_text),
        "eligibility_criteria": _extract_local_eligibility(normalized_text),
        "emissions": _extract_local_emissions(normalized_text, classification=classification),
    }


def _extract_local_criteria(text: str) -> list[dict[str, Any]]:
    criteria: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    lowered = text.lower()
    for rule in LOCAL_RULES:
        snippets: list[str] = []
        for keyword in rule["keywords"]:
            snippets.extend(_keyword_snippets(text, lowered, str(keyword).lower(), window=850, limit=8))
        for snippet in snippets:
            snippet_l = snippet.lower()
            if rule.get("context") and not any(str(token).lower() in snippet_l for token in rule["context"]):
                continue
            percent_values = _percent_values(snippet)
            if not percent_values and rule["canonical_key"] != "permitted_hedges":
                continue
            threshold_value = percent_values[0] if percent_values else None
            compact = _compact_excerpt(snippet)
            key = (str(rule["canonical_key"]), compact[:220])
            if key in seen:
                continue
            seen.add(key)
            criteria.append(
                {
                    "name": rule["name"],
                    "canonical_key": rule["canonical_key"],
                    "event_type": rule["event_type"],
                    "threshold_value": threshold_value,
                    "threshold_unit": "ratio" if threshold_value is not None else "texto",
                    "threshold_display": _first_percent_display(snippet) if threshold_value is not None else "",
                    "comparison": _infer_comparison(snippet, default=str(rule["comparison"])),
                    "formula_text": _infer_formula_text(snippet),
                    "source_excerpt": compact,
                    "confidence": "média" if threshold_value is not None else "baixa",
                    "notes": "Extração local heurística; validar manualmente antes de ativar alerta.",
                }
            )
            if len([item for item in criteria if item["canonical_key"] == rule["canonical_key"]]) >= 5:
                break
    return criteria


def _extract_local_eligibility(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for keyword in ("critério de elegibilidade", "criterio de elegibilidade", "direitos creditórios elegíveis", "direitos creditorios elegiveis", "condições de cessão", "condicoes de cessao"):
        for snippet in _keyword_snippets(text, text.lower(), keyword, window=900, limit=5):
            excerpt = _compact_excerpt(snippet)
            if excerpt[:180] in seen:
                continue
            seen.add(excerpt[:180])
            items.append(
                {
                    "name": "Critério de elegibilidade",
                    "description": excerpt,
                    "source_excerpt": excerpt,
                }
            )
    return items[:12]


def _extract_local_emissions(text: str, *, classification: str) -> list[dict[str, Any]]:
    if classification != "emissao" and not any(token in text.lower() for token in ("emissão", "emissao", "suplemento", "série", "serie")):
        return []
    base_snippet = _first_relevant_snippet(
        text,
        ("emissão", "emissao", "suplemento", "série", "serie", "cotas seniores", "cotas subordinadas"),
        window=1200,
    )
    if not base_snippet:
        return []
    remuneration = _first_relevant_snippet(text, ("remuneração", "remuneracao", "rentabilidade", "benchmark", "cdi"), window=650)
    amortization = _first_relevant_snippet(text, ("amortização", "amortizacao", "resgate"), window=650)
    maturity = _first_relevant_snippet(text, ("vencimento", "prazo", "data de vencimento"), window=650)
    amount_display = _first_money_display(base_snippet) or _first_money_display(text[:8000])
    return [
        {
            "date": None,
            "event": "emissão" if classification == "emissao" else "evento de cota",
            "series_or_class": _infer_series_or_class(base_snippet),
            "amount": _parse_money(amount_display),
            "amount_display": amount_display,
            "currency": "R$" if amount_display else None,
            "remuneration": _compact_excerpt(remuneration) if remuneration else "",
            "amortization_schedule": _compact_excerpt(amortization) if amortization else "",
            "maturity": _compact_excerpt(maturity) if maturity else "",
            "source_excerpt": _compact_excerpt(base_snippet),
        }
    ]


def _normalize_pdf_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _keyword_snippets(text: str, lowered: str, keyword: str, *, window: int, limit: int) -> list[str]:
    snippets = []
    start = 0
    while len(snippets) < limit:
        idx = lowered.find(keyword, start)
        if idx < 0:
            break
        begin = max(0, idx - window // 2)
        end = min(len(text), idx + window)
        snippets.append(text[begin:end])
        start = idx + len(keyword)
    return snippets


def _percent_values(text: str) -> list[float]:
    values = []
    for match in re.finditer(r"(?<!\d)(\d{1,3}(?:[.,]\d{1,4})?)\s*%", text):
        raw = match.group(1).replace(".", "").replace(",", ".")
        try:
            values.append(float(raw) / 100.0)
        except ValueError:
            continue
    return values


def _first_percent_display(text: str) -> str:
    match = re.search(r"(?<!\d)(\d{1,3}(?:[.,]\d{1,4})?)\s*%", text)
    return match.group(0) if match else ""


def _first_money_display(text: str) -> str:
    match = re.search(r"R\$\s*\d[\d.\s]*(?:,\d{2})?", text)
    return re.sub(r"\s+", " ", match.group(0)).strip() if match else ""


def _parse_money(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = re.sub(r"[^\d,.-]", "", value).replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _infer_comparison(text: str, *, default: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("não inferior", "nao inferior", "mínim", "minim", "maior ou igual")):
        return ">="
    if any(token in lowered for token in ("não superior", "nao superior", "máxim", "maxim", "menor ou igual")):
        return "<="
    return default


def _infer_formula_text(text: str) -> str:
    lowered = text.lower()
    for token in ("dividido", "razão", "razao", "relação", "relacao", "quociente", "sobre"):
        if token in lowered:
            return _compact_excerpt(text)
    return ""


def _first_relevant_snippet(text: str, keywords: tuple[str, ...], *, window: int) -> str:
    lowered = text.lower()
    for keyword in keywords:
        snippets = _keyword_snippets(text, lowered, keyword.lower(), window=window, limit=1)
        if snippets:
            return snippets[0]
    return ""


def _infer_series_or_class(text: str) -> str:
    patterns = (
        r"\b\d{1,3}[ªa]?\s*s[ée]rie\b",
        r"\bs[ée]rie\s*\d{1,3}\b",
        r"\bclasse\s+(?:s[êe]nior|subordinada|mezanino|j[uú]nior)[^.;,\n]{0,50}",
        r"\bcotas?\s+(?:s[êe]niores|subordinadas|mezanino|j[uú]niores)[^.;,\n]{0,50}",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _compact_excerpt(match.group(0))
    return ""


def _compact_excerpt(text: str, *, limit: int = 420) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _normalize_extraction(
    raw: dict[str, Any],
    *,
    fund: FundConfig,
    document: DocumentoFundo,
    pdf_path: Path,
    classification: str,
) -> dict[str, Any]:
    criteria = []
    for criterion in raw.get("criteria") or []:
        if not isinstance(criterion, dict):
            continue
        name = str(criterion.get("name") or "").strip()
        key = str(criterion.get("canonical_key") or "other").strip() or "other"
        if not name and key == "other":
            continue
        hint = monitoring_hint_for_key(key)
        normalized = {
            "name": name or key,
            "canonical_key": key,
            "event_type": str(criterion.get("event_type") or "").strip(),
            "threshold_value": _nullable_float(criterion.get("threshold_value")),
            "threshold_unit": criterion.get("threshold_unit"),
            "threshold_display": str(criterion.get("threshold_display") or "").strip(),
            "comparison": str(criterion.get("comparison") or "").strip(),
            "formula_text": str(criterion.get("formula_text") or "").strip(),
            "source_excerpt": str(criterion.get("source_excerpt") or "").strip(),
            "confidence": str(criterion.get("confidence") or "").strip(),
            "notes": str(criterion.get("notes") or "").strip(),
            "source_document": pdf_path.name,
            "source_document_id": document.id,
            "monitoring_mapping": hint,
        }
        criteria.append(normalized)
    emissions = []
    for emission in raw.get("emissions") or []:
        if not isinstance(emission, dict):
            continue
        if not any(emission.get(field) for field in ("event", "series_or_class", "amount_display", "remuneration", "amortization_schedule", "maturity")):
            continue
        normalized_emission = {
            "date": emission.get("date"),
            "event": emission.get("event"),
            "series_or_class": emission.get("series_or_class"),
            "amount": _nullable_float(emission.get("amount")),
            "amount_display": emission.get("amount_display"),
            "currency": emission.get("currency"),
            "remuneration": emission.get("remuneration"),
            "amortization_schedule": emission.get("amortization_schedule"),
            "maturity": emission.get("maturity"),
            "source_excerpt": emission.get("source_excerpt"),
            "source_document": pdf_path.name,
            "source_document_id": document.id,
        }
        emissions.append(normalized_emission)
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "fund_name": fund.name,
        "fund_cnpj": format_cnpj(fund.cnpj),
        "document_id": document.id,
        "classification": classification,
        "source_file": str(pdf_path),
        "effective_date": raw.get("effective_date") or _fallback_effective_date(document),
        "document_summary": raw.get("document_summary") or "",
        "criteria": criteria,
        "eligibility_criteria": raw.get("eligibility_criteria") if isinstance(raw.get("eligibility_criteria"), list) else [],
        "emissions": emissions,
        "extracted_at": utc_now_iso(),
    }


def _error_extraction(
    *,
    fund: FundConfig,
    document: DocumentoFundo,
    pdf_path: Path,
    classification: str,
    error: str,
) -> dict[str, Any]:
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "fund_name": fund.name,
        "fund_cnpj": format_cnpj(fund.cnpj),
        "document_id": document.id,
        "classification": classification,
        "source_file": str(pdf_path),
        "effective_date": _fallback_effective_date(document),
        "document_summary": "",
        "criteria": [],
        "eligibility_criteria": [],
        "emissions": [],
        "extraction_error": error,
        "extracted_at": utc_now_iso(),
    }


def _write_fund_knowledge(
    *,
    fund: FundConfig,
    documents: list[dict[str, Any]],
    downloaded: list[tuple[DocumentoFundo, Path, str]],
    extractions: list[dict[str, Any]],
    out_dir: Path,
) -> Path:
    downloaded_by_id = {doc.id: path for doc, path, _classification in downloaded}
    document_rows = []
    for item in documents:
        doc: DocumentoFundo = item["document"]
        document_rows.append(
            {
                "id": doc.id,
                "categoria": doc.categoria,
                "tipo": doc.tipo,
                "especie": doc.especie,
                "classification": item["classification"],
                "data_referencia": doc.data_referencia,
                "data_entrega": doc.data_entrega,
                "nome_arquivo": doc.nome_arquivo,
                "status": doc.status,
                "downloaded": doc.id in downloaded_by_id,
                "download_error": item.get("download_error") or "",
                "source_file": str(downloaded_by_id[doc.id]) if doc.id in downloaded_by_id else "",
            }
        )
    criteria = []
    emissions = []
    eligibility = []
    extraction_errors = []
    for extraction in extractions:
        criteria.extend(extraction.get("criteria") or [])
        emissions.extend(extraction.get("emissions") or [])
        eligibility.extend(extraction.get("eligibility_criteria") or [])
        if extraction.get("extraction_error"):
            extraction_errors.append(
                {
                    "document_id": extraction.get("document_id"),
                    "source_file": extraction.get("source_file"),
                    "error": extraction.get("extraction_error"),
                }
            )
    payload = {
        "schema_version": 1,
        "fund_name": fund.name,
        "fund_cnpj": format_cnpj(fund.cnpj),
        "generated_at": utc_now_iso(),
        "documents": document_rows,
        "criteria": criteria,
        "eligibility_criteria": eligibility,
        "emissions": sorted(emissions, key=lambda item: str(item.get("date") or "")),
        "extraction_count": len(extractions),
        "extraction_errors": extraction_errors,
    }
    path = out_dir / f"{fund.cnpj}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  knowledge: {path}")
    return path


def _write_reports(knowledge_dir: Path, *, reports_dir: Path) -> None:
    items = []
    for path in sorted(knowledge_dir.glob("*.json")):
        item = load_regulatory_knowledge(path.stem, base_dir=knowledge_dir)
        if item is not None:
            items.append(item)

    inventory_rows = []
    criteria_rows = []
    emission_report_rows = []
    for item in items:
        for row in document_inventory_rows(item):
            inventory_rows.append({"Fundo": item.fund_name, "CNPJ": format_cnpj(item.cnpj), **row})
        for row in extracted_criteria_rows(item):
            criteria_rows.append({"Fundo": item.fund_name, "CNPJ": format_cnpj(item.cnpj), **row})
        for row in emission_rows(item):
            emission_report_rows.append({"Fundo": item.fund_name, "CNPJ": format_cnpj(item.cnpj), **row})

    _write_csv(reports_dir / "regulatory_document_inventory.csv", inventory_rows)
    _write_csv(reports_dir / "regulatory_criteria_matrix.csv", criteria_rows)
    _write_csv(reports_dir / "regulatory_emissions_timeline.csv", emission_report_rows)
    (reports_dir / "regulatory_monitoring_study.md").write_text(_render_markdown_report(items), encoding="utf-8")


def _render_markdown_report(items: list[Any]) -> str:
    summary = knowledge_summary_rows(items)
    common = common_criteria_summary(items)
    lines = [
        "# Estudo regulatório dos FIDCs monitorados",
        "",
        f"Gerado em: {utc_now_iso()}",
        "",
        "## Resumo executivo",
        "",
        f"- Fundos com base gerada: {len(items)}",
        f"- Documentos inventariados: {sum(int(row['Documentos']) for row in summary)}",
        f"- Documentos com extração estruturada: {sum(int(item.payload.get('extraction_count') or 0) for item in items)}",
        f"- Critérios extraídos: {sum(int(row['Critérios']) for row in summary)}",
        f"- Critérios classificados como monitoráveis pelo IME: {sum(int(row['Monitoráveis']) for row in summary)}",
        f"- Documentos com erro de extração estruturada: {sum(len(item.payload.get('extraction_errors') or []) for item in items)}",
        "",
        "A base separa documentos, critérios regulatórios e eventos de emissão/amortização. O app deve monitorar apenas critérios explicitamente encontrados e com mapeamento viável para o Informe Mensal; os demais ficam como referência para análise manual.",
        "",
        "A extração estruturada desta entrega foi feita localmente, sem chamada externa de LLM: o script extrai texto dos PDFs e aplica regras heurísticas auditáveis. Cada critério candidato preserva trecho-fonte e deve ser validado pelo analista antes de virar alerta automático.",
    ]
    if not any(int(item.payload.get("extraction_count") or 0) for item in items):
        lines.extend(
            [
                "",
                "**Atenção:** esta versão contém inventário documental completo, mas ainda não contém thresholds extraídos. Para preencher critérios, emissões e cronogramas, rode o script no modo local padrão, sem `--skip-llm`.",
            ]
        )
    lines.extend(["", "## Critérios mais recorrentes e monitorabilidade", ""])
    lines.extend(_markdown_table(common[:30]))
    lines.extend(["", "## Cobertura por fundo", ""])
    lines.extend(_markdown_table(summary))
    lines.extend(
        [
            "",
            "## Regras de interpretação",
            "",
            "- Subordinação mínima, NPL Over por faixa, PDD/cobertura e alocação em direitos creditórios tendem a ser monitoráveis pelo IME quando a fórmula do documento usa os mesmos denominadores.",
            "- Diluição, chargeback, concentração por cedente/sacado e critérios de elegibilidade granular normalmente não são monitoráveis pelo IME público.",
            "- Reservas de liquidez e amortização são parcialmente monitoráveis: caixa existe no IME, mas cronogramas futuros costumam depender de suplemento, ata ou documento operacional.",
            "- A presença de uma métrica no estudo não significa alerta automático; significa que o analista tem uma candidata a threshold manual para validação.",
        ]
    )
    return "\n".join(lines) + "\n"


def _markdown_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["_Sem dados extraídos._"]
    columns = list(rows[0].keys())
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_clean_md_cell(row.get(column)) for column in columns) + " |")
    return lines


def _clean_md_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _document_storage_name(document: DocumentoFundo, *, classification: str) -> str:
    name = build_document_filename(document, default_stem=f"{classification}_{document.id}")
    stem = Path(name).stem
    suffix = Path(name).suffix or ".pdf"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or f"{classification}_{document.id}"
    return f"{document.id}_{classification}_{safe_stem}{suffix.lower()}"


def _nullable_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fallback_effective_date(document: DocumentoFundo) -> str | None:
    value = document.data_referencia_dt or (document.data_entrega_dt.date() if document.data_entrega_dt else None)
    return value.isoformat() if value else None


def _date_sort_key(value: date | None) -> date:
    return value or date.min


def _datetime_sort_key(value: datetime | None) -> datetime:
    return value or datetime.min


if __name__ == "__main__":
    main()
