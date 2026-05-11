from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


REGULATORY_KNOWLEDGE_DIR = Path("data/regulatory_knowledge")
REGULATORY_RAW_DIR = Path("data/raw")

MONITORING_SOURCE_HINTS: dict[str, dict[str, str]] = {
    "subordination_ratio_min": {
        "status": "monitoravel",
        "ime_metric": "Cotas Sub / PL %, Cotas MZ / PL % e Cotas SR / PL %",
        "rationale": "O Informe Mensal traz PL e classes/cotas; a subordinação pode ser recalculada por classe quando as cotas reconciliam.",
    },
    "default_rate_early_maturity": {
        "status": "monitoravel",
        "ime_metric": "Vencidos Over 30/60/90/180/360 d / Crédito",
        "rationale": "Os buckets de atraso do Informe Mensal permitem recompor NPL Over acumulado por faixa.",
    },
    "default_rate_evaluation_event": {
        "status": "monitoravel",
        "ime_metric": "Vencidos Over 30/60/90/180/360 d / Crédito",
        "rationale": "Os buckets de atraso do Informe Mensal permitem recompor NPL Over acumulado por faixa.",
    },
    "pdd_coverage_min": {
        "status": "monitoravel",
        "ime_metric": "PDD / Venc Total ou PDD / Venc > 90 d",
        "rationale": "O Informe Mensal traz provisão e buckets de atraso; a aderência depende da definição exata do regulamento.",
    },
    "credit_rights_allocation_min": {
        "status": "monitoravel",
        "ime_metric": "Dir Cred / PL",
        "rationale": "O Informe Mensal traz direitos creditórios e PL.",
    },
    "recompras_max": {
        "status": "monitoravel",
        "ime_metric": "Recompras / Crédito ou Recompras / PL",
        "rationale": "O Informe Mensal traz recompras mensais; thresholds acumulados exigem janela definida no documento.",
    },
    "minimum_cash_ratio": {
        "status": "parcial",
        "ime_metric": "Disponibilidades / PL ou Disponibilidades / amortização estimada",
        "rationale": "O Informe Mensal traz caixa, mas cronogramas futuros e reservas regulatórias nem sempre são campos padronizados.",
    },
    "dilution_rate_max": {
        "status": "nao_monitoravel",
        "ime_metric": "",
        "rationale": "Diluição costuma depender de eventos operacionais do cedente/sacado e não aparece de forma padronizada no IME.",
    },
    "chargeback_rate_max": {
        "status": "nao_monitoravel",
        "ime_metric": "",
        "rationale": "Chargeback geralmente não é campo padronizado no IME; só é monitorável se o fundo reportar proxy explícita em documento/arquivo externo.",
    },
    "concentration_limits": {
        "status": "nao_monitoravel",
        "ime_metric": "",
        "rationale": "Limites por sacado, cedente ou grupo econômico exigem granularidade não disponível no IME público.",
    },
    "permitted_hedges": {
        "status": "parcial",
        "ime_metric": "Posições mantidas em derivativos",
        "rationale": "O IME mostra posições agregadas em derivativos, mas não valida integralmente elegibilidade contratual da proteção.",
    },
}


@dataclass(frozen=True)
class RegulatoryKnowledge:
    cnpj: str
    fund_name: str
    payload: dict[str, Any]
    path: Path | None = None


@dataclass(frozen=True)
class FundConfig:
    cnpj: str
    name: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_cnpj(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def format_cnpj(cnpj: str) -> str:
    digits = normalize_cnpj(cnpj)
    if len(digits) != 14:
        return str(cnpj or "")
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def load_funds_config(path: str | Path) -> list[FundConfig]:
    """Load the saved fund list used by offline regulatory scripts."""
    config_path = Path(path)
    if not config_path.exists():
        return []
    text = config_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        payload = yaml.safe_load(text) or {}
        rows = payload.get("funds") if isinstance(payload, dict) else []
        return _funds_from_rows(rows or [])
    except Exception:  # noqa: BLE001
        return _load_simple_funds_yaml(text)


def _load_simple_funds_yaml(text: str) -> list[FundConfig]:
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "funds:":
            continue
        if line.startswith("- "):
            if current:
                rows.append(current)
            current = {}
            line = line[2:].strip()
        if ":" in line and current is not None:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip().strip('"').strip("'")
    if current:
        rows.append(current)
    return _funds_from_rows(rows)


def _funds_from_rows(rows: list[dict[str, Any]]) -> list[FundConfig]:
    funds: list[FundConfig] = []
    seen: set[str] = set()
    for row in rows:
        cnpj = normalize_cnpj(str(row.get("cnpj") or ""))
        if len(cnpj) != 14 or cnpj in seen:
            continue
        seen.add(cnpj)
        name = str(row.get("name") or row.get("display_name") or cnpj).strip() or cnpj
        funds.append(FundConfig(cnpj=cnpj, name=name))
    return funds


def classify_document(*, categoria: str = "", tipo: str = "", especie: str = "", nome_arquivo: str = "") -> str:
    text = " ".join(str(part or "") for part in (categoria, tipo, especie, nome_arquivo)).lower()
    if any(token in text for token in ("informe mensal", "informe estruturado", "mensal estruturado")):
        return "informe_mensal"
    if any(token in text for token in ("regulamento", "aditamento", "alteração de regulamento", "alteracao de regulamento")):
        return "regulamento"
    if any(token in text for token in ("assembleia", "assembléia", "ata", "deliberação", "deliberacao")):
        return "assembleia"
    if any(
        token in text
        for token in (
            "emissão",
            "emissao",
            "suplemento",
            "série",
            "serie",
            "oferta",
            "anúncio",
            "anuncio",
            "encerramento",
            "distribuição",
            "distribuicao",
        )
    ):
        return "emissao"
    if any(token in text for token in ("fato relevante", "comunicado", "aviso")):
        return "evento"
    return "outro"


def should_download_document(classification: str, *, include_ime: bool = False) -> bool:
    if classification == "informe_mensal":
        return include_ime
    return classification in {"regulamento", "assembleia", "emissao", "evento"}


def monitoring_hint_for_key(key: str | None) -> dict[str, str]:
    if not key:
        return {"status": "nao_monitoravel", "ime_metric": "", "rationale": "Sem chave canônica extraída."}
    return MONITORING_SOURCE_HINTS.get(
        key,
        {
            "status": "parcial",
            "ime_metric": "",
            "rationale": "Critério extraído sem mapeamento canônico para o IME; requer validação manual.",
        },
    )


def load_regulatory_knowledge(cnpj: str, *, base_dir: Path = REGULATORY_KNOWLEDGE_DIR) -> RegulatoryKnowledge | None:
    digits = normalize_cnpj(cnpj)
    path = base_dir / f"{digits}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return RegulatoryKnowledge(
        cnpj=digits,
        fund_name=str(payload.get("fund_name") or digits),
        payload=payload,
        path=path,
    )


def document_inventory_rows(knowledge: RegulatoryKnowledge) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc in knowledge.payload.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        rows.append(
            {
                "Data": doc.get("data_referencia") or doc.get("data_entrega") or "",
                "Tipo": doc.get("classification") or "",
                "Documento": doc.get("tipo") or doc.get("categoria") or "",
                "Espécie": doc.get("especie") or "",
                "Arquivo": doc.get("source_file") or doc.get("nome_arquivo") or "",
                "ID CVM": doc.get("id") or "",
            }
        )
    return rows


def extracted_criteria_rows(knowledge: RegulatoryKnowledge) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in knowledge.payload.get("criteria") or []:
        if not isinstance(item, dict):
            continue
        mapping = item.get("monitoring_mapping") if isinstance(item.get("monitoring_mapping"), dict) else {}
        rows.append(
            {
                "Critério": item.get("name") or "",
                "Chave": item.get("canonical_key") or "",
                "Evento": item.get("event_type") or "",
                "Comparação": item.get("comparison") or "",
                "Limite": item.get("threshold_display") or _format_threshold(item.get("threshold_value"), item.get("threshold_unit")),
                "Monitoramento": mapping.get("status") or "",
                "Métrica IME sugerida": mapping.get("ime_metric") or "",
                "Fonte": item.get("source_document") or "",
                "Comentário": mapping.get("rationale") or item.get("notes") or "",
            }
        )
    return rows


def emission_rows(knowledge: RegulatoryKnowledge) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in knowledge.payload.get("emissions") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "Data": item.get("date") or "",
                "Classe/Série": item.get("series_or_class") or "",
                "Evento": item.get("event") or "",
                "Volume": item.get("amount_display") or _format_threshold(item.get("amount"), item.get("currency") or "R$"),
                "Remuneração": item.get("remuneration") or "",
                "Amortização/Vencimento": item.get("amortization_schedule") or item.get("maturity") or "",
                "Fonte": item.get("source_document") or "",
            }
        )
    return rows


def knowledge_summary_rows(items: list[RegulatoryKnowledge]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        documents = [doc for doc in item.payload.get("documents") or [] if isinstance(doc, dict)]
        criteria = [row for row in extracted_criteria_rows(item)]
        monitorable = sum(1 for row in criteria if row.get("Monitoramento") == "monitoravel")
        partial = sum(1 for row in criteria if row.get("Monitoramento") == "parcial")
        latest_doc_date = max((str(doc.get("data_referencia") or doc.get("data_entrega") or "") for doc in documents), default="")
        rows.append(
            {
                "Fundo": item.fund_name,
                "CNPJ": format_cnpj(item.cnpj),
                "Documentos": len(documents),
                "Regulamentos": sum(1 for doc in documents if doc.get("classification") == "regulamento"),
                "Assembleias": sum(1 for doc in documents if doc.get("classification") == "assembleia"),
                "Emissões": sum(1 for doc in documents if doc.get("classification") == "emissao"),
                "Critérios": len(criteria),
                "Monitoráveis": monitorable,
                "Parciais": partial,
                "Último doc.": latest_doc_date,
            }
        )
    return rows


def common_criteria_summary(items: list[RegulatoryKnowledge]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        for criterion in item.payload.get("criteria") or []:
            if not isinstance(criterion, dict):
                continue
            key = str(criterion.get("canonical_key") or criterion.get("name") or "outro")
            hint = criterion.get("monitoring_mapping") if isinstance(criterion.get("monitoring_mapping"), dict) else {}
            bucket = grouped.setdefault(
                key,
                {
                    "Critério": key,
                    "Ocorrências": 0,
                    "Fundos": set(),
                    "Monitoramento": hint.get("status") or monitoring_hint_for_key(key).get("status"),
                    "Métrica IME": hint.get("ime_metric") or monitoring_hint_for_key(key).get("ime_metric"),
                },
            )
            bucket["Ocorrências"] += 1
            bucket["Fundos"].add(item.cnpj)
    rows = []
    for bucket in grouped.values():
        rows.append(
            {
                "Critério": bucket["Critério"],
                "Ocorrências": bucket["Ocorrências"],
                "Fundos": len(bucket["Fundos"]),
                "Monitoramento": bucket["Monitoramento"],
                "Métrica IME": bucket["Métrica IME"],
            }
        )
    return sorted(rows, key=lambda row: (-int(row["Fundos"]), str(row["Critério"])))


def _format_threshold(value: Any, unit: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    unit_text = str(unit or "")
    if unit_text in {"%", "percent", "ratio"} or abs(numeric) <= 1:
        return f"{numeric * 100:.2f}%".replace(".", ",")
    if unit_text.upper() == "R$":
        return f"R$ {numeric:,.0f}".replace(",", ".")
    return f"{numeric:g} {unit_text}".strip()
