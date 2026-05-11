from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.regulatory_knowledge import (  # noqa: E402
    REGULATORY_KNOWLEDGE_DIR,
    normalize_cnpj,
)


SELLER_CURATED_CNPJS = {"50473039000102", "55471753000177", "63572282000111"}

CRITERIA_COLUMNS = [
    "Fundo",
    "CNPJ",
    "Critério",
    "Chave",
    "Limite/regra",
    "Monitorabilidade IME",
    "Métrica IME / proxy",
    "Condição de alerta sugerida",
    "Observação técnica",
    "Fonte",
    "Status curadoria",
]

EMISSION_COLUMNS = [
    "Fundo",
    "CNPJ",
    "Cota/Classe",
    "Tipo",
    "Data deliberação",
    "Data emissão / 1ª integralização",
    "Data encerramento/oferta",
    "Quantidade",
    "Volume",
    "VNU",
    "Remuneração",
    "Juros/remuneração",
    "Amortização principal",
    "Status/evidência",
    "Fonte",
    "Status curadoria",
]


def main() -> None:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    criteria_rows: list[dict[str, str]] = []
    emission_rows: list[dict[str, str]] = []
    status_rows: list[dict[str, str]] = []

    for path in sorted(args.knowledge_dir.glob("*.json")):
        cnpj = normalize_cnpj(path.stem)
        if args.exclude_sellers and cnpj in SELLER_CURATED_CNPJS:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        document_index = _document_index(payload)
        fund_name = str(payload.get("fund_name") or cnpj)
        formatted_cnpj = _format_cnpj(cnpj)
        fund_criteria = _curate_criteria(payload, document_index=document_index)
        fund_emissions = _curate_emissions(payload, document_index=document_index)
        criteria_rows.extend(_criteria_output_rows(fund_criteria, fund_name=fund_name, cnpj=formatted_cnpj))
        emission_rows.extend(_emission_output_rows(fund_emissions, fund_name=fund_name, cnpj=formatted_cnpj))
        status_rows.append(
            {
                "Fundo": fund_name,
                "CNPJ": formatted_cnpj,
                "Documentos inventariados": str(len(payload.get("documents") or [])),
                "Critérios curados": str(len(fund_criteria)),
                "Emissões/eventos curados": str(len(fund_emissions)),
                "Status curadoria": "triagem estruturada por evidências offline; requer revisão fina antes de alerta contratual duro",
            }
        )

    _write_csv(args.output_dir / "all_fidcs_criteria_monitoraveis_ime.csv", CRITERIA_COLUMNS, criteria_rows)
    _write_csv(args.output_dir / "all_fidcs_cotas_emissoes_pagamentos.csv", EMISSION_COLUMNS, emission_rows)
    _write_csv(
        args.reports_dir / "all_fidcs_regulatory_curation_status.csv",
        ["Fundo", "CNPJ", "Documentos inventariados", "Critérios curados", "Emissões/eventos curados", "Status curadoria"],
        status_rows,
    )
    print(f"Perfis curados gerados: {len(status_rows)} fundo(s), {len(criteria_rows)} critério(s), {len(emission_rows)} emissão(ões)/evento(s).")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promove a base regulatória offline a perfis curados auditáveis por FIDC.")
    parser.add_argument("--knowledge-dir", type=Path, default=REGULATORY_KNOWLEDGE_DIR)
    parser.add_argument("--output-dir", type=Path, default=Path("data/regulatory_profiles"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--include-sellers", action="store_true", help="Inclui Sellers; por padrão eles ficam nos CSVs manuais existentes.")
    args = parser.parse_args()
    args.exclude_sellers = not args.include_sellers
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    return args


def _document_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for doc in payload.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        keys = {
            str(doc.get("id") or ""),
            Path(str(doc.get("source_file") or "")).name,
            str(doc.get("nome_arquivo") or ""),
        }
        for key in keys:
            if key:
                rows[key] = doc
    return rows


def _curate_criteria(payload: dict[str, Any], *, document_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [item for item in payload.get("criteria") or [] if isinstance(item, dict)]
    if not candidates:
        return []
    enriched = [_with_doc_meta(item, document_index=document_index) for item in candidates]
    enriched = [item for item in enriched if _has_material_criterion(item)]
    enriched = _latest_regulation_criteria(enriched)
    if not enriched:
        return []

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in sorted(enriched, key=_criteria_sort_key, reverse=True):
        key = str(item.get("canonical_key") or "")
        threshold = str(item.get("threshold_display") or "")
        dedupe = (key, threshold or _normalize_excerpt_key(str(item.get("formula_text") or item.get("source_excerpt") or "")))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        if sum(1 for row in rows if row.get("canonical_key") == key) >= _max_rows_for_key(key):
            continue
        rows.append(item)
    return sorted(rows, key=lambda item: (_criterion_display_order(str(item.get("canonical_key") or "")), str(item.get("threshold_display") or ""), str(item.get("source_document") or "")))


def _curate_emissions(payload: dict[str, Any], *, document_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [item for item in payload.get("emissions") or [] if isinstance(item, dict)]
    enriched = [_with_doc_meta(item, document_index=document_index) for item in candidates]
    enriched = [item for item in enriched if _has_material_emission(item)]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in sorted(enriched, key=_emission_sort_key, reverse=True):
        series = str(item.get("series_or_class") or "")
        amount = str(item.get("amount_display") or "")
        amortization = _normalize_excerpt_key(str(item.get("amortization_schedule") or item.get("maturity") or ""))
        remuneration = _normalize_excerpt_key(str(item.get("remuneration") or ""))
        dedupe = (series, amount, amortization, remuneration)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        rows.append(item)
    return sorted(rows, key=lambda item: (_date_sort(str(item.get("_doc_date") or "")), str(item.get("series_or_class") or ""), str(item.get("source_document") or "")))


def _criteria_output_rows(rows: list[dict[str, Any]], *, fund_name: str, cnpj: str) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for item in rows:
        mapping = item.get("monitoring_mapping") if isinstance(item.get("monitoring_mapping"), dict) else {}
        limit = _validated_limit_for_item(item)
        if not limit:
            continue
        output.append(
            {
                "Fundo": fund_name,
                "CNPJ": cnpj,
                "Critério": str(item.get("name") or "").strip(),
                "Chave": str(item.get("canonical_key") or "").strip(),
                "Limite/regra": limit or _short_rule_text(item),
                "Monitorabilidade IME": str(mapping.get("status") or "").strip(),
                "Métrica IME / proxy": str(mapping.get("ime_metric") or "").strip(),
                "Condição de alerta sugerida": _alert_text(item),
                "Observação técnica": _criterion_note(item),
                "Fonte": _source_label(item),
                "Status curadoria": "triagem estruturada por evidência documental offline; revisar antes de alerta contratual duro",
            }
        )
    return output


def _emission_output_rows(rows: list[dict[str, Any]], *, fund_name: str, cnpj: str) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for item in rows:
        series = str(item.get("series_or_class") or "").strip()
        output.append(
            {
                "Fundo": fund_name,
                "CNPJ": cnpj,
                "Cota/Classe": series,
                "Tipo": _infer_quota_type(series),
                "Data deliberação": _doc_date(item),
                "Data emissão / 1ª integralização": str(item.get("date") or "").strip() or "Não identificada na extração offline",
                "Data encerramento/oferta": "",
                "Quantidade": "",
                "Volume": str(item.get("amount_display") or "").strip(),
                "VNU": "",
                "Remuneração": _clean_text(item.get("remuneration")),
                "Juros/remuneração": _clean_text(item.get("remuneration")),
                "Amortização principal": _clean_text(item.get("amortization_schedule") or item.get("maturity")),
                "Status/evidência": _clean_text(item.get("event") or item.get("source_excerpt")),
                "Fonte": _source_label(item),
                "Status curadoria": "triagem estruturada por evidência documental offline; campos vazios indicam ausência na extração",
            }
        )
    return output


def _with_doc_meta(item: dict[str, Any], *, document_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    output = dict(item)
    doc = document_index.get(str(item.get("source_document_id") or "")) or document_index.get(Path(str(item.get("source_document") or "")).name) or {}
    output["_doc_classification"] = str(doc.get("classification") or "")
    output["_doc_date"] = str(doc.get("data_referencia") or doc.get("data_entrega") or "")
    return output


def _has_material_criterion(item: dict[str, Any]) -> bool:
    key = str(item.get("canonical_key") or "")
    classification = str(item.get("_doc_classification") or "")
    if classification and classification != "regulamento":
        return False
    if not _criterion_matches_key_context(item):
        return False
    if key == "permitted_hedges":
        return bool(str(item.get("source_excerpt") or "").strip())
    return bool(str(item.get("threshold_display") or "").strip())


def _criterion_matches_key_context(item: dict[str, Any]) -> bool:
    key = str(item.get("canonical_key") or "")
    text = _clean_text(" ".join(str(item.get(field) or "") for field in ("formula_text", "source_excerpt"))).lower()
    if key == "credit_rights_allocation_min":
        return "alocação mínima" in text or "alocacao minima" in text
    if key == "subordination_ratio_min":
        return any(token in text for token in ("subordinação", "subordinacao", "relação mínima", "relacao minima", "razão de subordinação", "razao de subordinacao"))
    if key in {"default_rate_evaluation_event", "default_rate_early_maturity"}:
        return any(token in text for token in ("inadimpl", "atras", "vencid", "over"))
    if key == "pdd_coverage_min":
        return any(token in text for token in ("pdd", "provis", "cobertura"))
    if key == "minimum_cash_ratio":
        return any(token in text for token in ("reserva", "caixa", "disponibilidades"))
    if key == "permitted_hedges":
        return any(token in text for token in ("derivativo", "derivativos", "hedge", "swap", "ndf"))
    if key == "concentration_limits":
        return "concentra" in text
    if key == "recompras_max":
        return "recompra" in text
    if key == "dilution_rate_max":
        return "dilui" in text
    if key == "chargeback_rate_max":
        return "chargeback" in text or "contesta" in text
    return True


def _has_material_emission(item: dict[str, Any]) -> bool:
    source = str(item.get("source_document") or "").lower()
    classification = str(item.get("_doc_classification") or "").lower()
    if classification not in {"emissao", "assembleia", "regulamento"}:
        return False
    if not source and not classification:
        return False
    series = str(item.get("series_or_class") or "").strip()
    amount = str(item.get("amount_display") or "").strip()
    remuneration = str(item.get("remuneration") or "").strip()
    amortization = str(item.get("amortization_schedule") or item.get("maturity") or "").strip()
    if classification == "regulamento" and not series:
        return False
    return bool(series or amount) and bool(amount or remuneration or amortization)


def _latest_regulation_criteria(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regulation_items = [item for item in items if str(item.get("_doc_classification") or "") == "regulamento"]
    if not regulation_items:
        return items
    latest_date = max(_date_sort(str(item.get("_doc_date") or "")) for item in regulation_items)
    latest = [item for item in regulation_items if _date_sort(str(item.get("_doc_date") or "")) == latest_date]
    return latest or regulation_items


def _criteria_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    classification = str(item.get("_doc_classification") or "")
    class_score = {"regulamento": 4, "assembleia": 3, "emissao": 2, "evento": 1}.get(classification, 0)
    has_threshold = 1 if str(item.get("threshold_display") or "").strip() else 0
    return (class_score, has_threshold, str(item.get("_doc_date") or ""))


def _emission_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    classification = str(item.get("_doc_classification") or "")
    class_score = {"emissao": 4, "assembleia": 3, "regulamento": 2, "evento": 1}.get(classification, 0)
    return (class_score, str(item.get("_doc_date") or ""))


def _max_rows_for_key(key: str) -> int:
    return {
        "subordination_ratio_min": 4,
        "credit_rights_allocation_min": 3,
        "default_rate_evaluation_event": 4,
        "default_rate_early_maturity": 4,
        "pdd_coverage_min": 3,
        "minimum_cash_ratio": 3,
        "permitted_hedges": 2,
        "concentration_limits": 4,
    }.get(key, 2)


def _criterion_display_order(key: str) -> int:
    order = {
        "subordination_ratio_min": 10,
        "credit_rights_allocation_min": 20,
        "default_rate_evaluation_event": 30,
        "default_rate_early_maturity": 40,
        "pdd_coverage_min": 50,
        "minimum_cash_ratio": 60,
        "recompras_max": 70,
        "permitted_hedges": 80,
        "dilution_rate_max": 90,
        "chargeback_rate_max": 100,
        "concentration_limits": 110,
    }
    return order.get(key, 999)


def _alert_text(item: dict[str, Any]) -> str:
    comparison = str(item.get("comparison") or "").strip()
    limit = _validated_limit_for_item(item)
    key = str(item.get("canonical_key") or "")
    if key == "permitted_hedges":
        return "Alerta se posição agregada em derivativos contrariar a regra textual"
    if not limit:
        return ""
    if comparison == ">=":
        return f"Alerta se proxy IME ficar abaixo de {limit}"
    if comparison == "<=":
        return f"Alerta se proxy IME ficar acima de {limit}"
    return f"Validar {comparison} {limit}".strip()


def _criterion_note(item: dict[str, Any]) -> str:
    mapping = item.get("monitoring_mapping") if isinstance(item.get("monitoring_mapping"), dict) else {}
    pieces = [
        str(mapping.get("rationale") or "").strip(),
        str(item.get("notes") or "").strip(),
        _clean_text(item.get("source_excerpt")),
    ]
    return " | ".join(piece for piece in pieces if piece)


def _short_rule_text(item: dict[str, Any]) -> str:
    if str(item.get("canonical_key") or "") == "permitted_hedges":
        return "Regra textual de derivativos/hedge; verificar observação e fonte."
    text = _clean_text(item.get("formula_text") or item.get("source_excerpt"))
    if not text:
        return ""
    return text[:220].rstrip() + ("…" if len(text) > 220 else "")


def _validated_limit_for_item(item: dict[str, Any]) -> str:
    key = str(item.get("canonical_key") or "")
    text = _clean_text(" ".join(str(item.get(field) or "") for field in ("formula_text", "source_excerpt")))
    lowered = text.lower()

    if key == "permitted_hedges":
        return "Regra textual de derivativos/hedge; verificar observação e fonte."

    if key == "credit_rights_allocation_min":
        match = re.search(r"(?:mínimo|minimo|alocação mínima|alocacao minima)[^%]{0,120}?(\d{1,3}(?:[,.]\d{1,4})?)\s*%", lowered)
        return _percent_match_text(match) if match else ""

    if key == "subordination_ratio_min":
        match = re.search(r"(?:subordina\w+|relação mínima|relacao minima|razão de subordinação|razao de subordinacao)[^%]{0,160}?(\d{1,3}(?:[,.]\d{1,4})?)\s*%", lowered)
        return _percent_match_text(match) if match else str(item.get("threshold_display") or "").strip()

    if key == "minimum_cash_ratio":
        if not any(token in lowered for token in ("reserva", "caixa", "disponibilidades")):
            return ""
        match = re.search(r"(?:reserva|caixa|disponibilidades)[^%]{0,180}?(\d{1,3}(?:[,.]\d{1,4})?)\s*%", lowered)
        return _percent_match_text(match) if match else str(item.get("threshold_display") or "").strip()

    if key in {"default_rate_evaluation_event", "default_rate_early_maturity"}:
        if not any(token in lowered for token in ("inadimpl", "atras", "vencid", "over")):
            return ""
        return str(item.get("threshold_display") or "").strip()

    if key == "pdd_coverage_min":
        if not any(token in lowered for token in ("pdd", "provis", "cobertura")):
            return ""
        return str(item.get("threshold_display") or "").strip()

    return str(item.get("threshold_display") or "").strip()


def _percent_match_text(match: re.Match[str] | None) -> str:
    if not match:
        return ""
    return f"{match.group(1).replace('.', ',')}%"


def _source_label(item: dict[str, Any]) -> str:
    source = Path(str(item.get("source_document") or "")).name
    doc_id = str(item.get("source_document_id") or "").strip()
    date = str(item.get("_doc_date") or "").strip()
    parts = [source]
    if doc_id:
        parts.append(f"ID {doc_id}")
    if date:
        parts.append(date)
    return " · ".join(part for part in parts if part)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_excerpt_key(value: str) -> str:
    return _clean_text(value).lower()[:180]


def _infer_quota_type(value: str) -> str:
    lowered = str(value or "").lower()
    if "senior" in lowered or "sênior" in lowered:
        return "Sênior"
    if "mezan" in lowered:
        return "Mezanino"
    if "sub" in lowered or "junior" in lowered or "júnior" in lowered:
        return "Subordinada"
    return ""


def _doc_date(item: dict[str, Any]) -> str:
    return str(item.get("_doc_date") or "").strip()


def _date_sort(value: str) -> str:
    text = str(value or "")
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
        day, month, year = text.split("/")
        return f"{year}-{month}-{day}"
    if re.fullmatch(r"\d{2}/\d{4}", text):
        month, year = text.split("/")
        return f"{year}-{month}-01"
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    return text


def _format_cnpj(cnpj: str) -> str:
    digits = normalize_cnpj(cnpj)
    if len(digits) != 14:
        return cnpj
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
