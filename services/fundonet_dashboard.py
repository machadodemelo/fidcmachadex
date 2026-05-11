from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
import re
import unicodedata

import pandas as pd

from services.cvm_cadastro import fetch_fidc_participantes
from services.fidc_monitoring import (
    build_current_dashboard_inventory_df,
    build_coverage_gap_df,
    build_mini_glossary_df,
    build_risk_metrics_df,
)
from services.identifier_utils import normalize_cnpj_digits


COMPETENCIA_COLUMN_RE = re.compile(r"^\d{2}/\d{4}$")
EVENT_SIGN = {
    "emissao": 1.0,
    "resgate": -1.0,
    "amortizacao": -1.0,
}
EVENT_LABEL = {
    "emissao": "Emissão",
    "resgate": "Resgate pago",
    "resgate_solicitado": "Resgate solicitado",
    "amortizacao": "Amortização",
}
EVENT_INTERPRETATION = {
    "emissao": "Entrada de capital no fundo; sinal econômico positivo para PL/caixa.",
    "resgate": "Saída de caixa paga a cotistas; sinal econômico negativo.",
    "resgate_solicitado": "Resgate solicitado a pagar; acompanha pressão futura de liquidez.",
    "amortizacao": "Devolução de capital aos cotistas; sinal econômico negativo.",
}
CLASS_DISPLAY_ORDER = {
    "senior": 1,
    "mezzanino": 2,
    "subordinada": 3,
    "nao_reconciliado": 98,
}

_MALHA_BASES = ["COMPMT_DICRED_AQUIS", "COMPMT_DICRED_SEM_AQUIS"]
_MALHA_FUTURE_SUFFIXES = [
    "VL_PRAZO_VENC_30",
    "VL_PRAZO_VENC_31_60",
    "VL_PRAZO_VENC_61_90",
    "VL_PRAZO_VENC_91_120",
    "VL_PRAZO_VENC_121_150",
    "VL_PRAZO_VENC_151_180",
    "VL_PRAZO_VENC_181_360",
    "VL_PRAZO_VENC_361_720",
    "VL_PRAZO_VENC_721_1080",
    "VL_PRAZO_VENC_1080",
]
_AGING_SUFFIXES = [
    "VL_INAD_VENC_30",
    "VL_INAD_VENC_31_60",
    "VL_INAD_VENC_61_90",
    "VL_INAD_VENC_91_120",
    "VL_INAD_VENC_121_150",
    "VL_INAD_VENC_151_180",
    "VL_INAD_VENC_181_360",
    "VL_INAD_VENC_361_720",
    "VL_INAD_VENC_721_1080",
    "VL_INAD_VENC_1080",
]
_OVER_BUCKET_SPECS: list[tuple[str, int, int | None]] = [
    ("Over 1", 1, None),
    ("Over 30", 2, None),
    ("Over 60", 3, None),
    ("Over 90", 4, None),
    ("Over 180", 7, None),
    ("Over 360", 8, None),
]
_GRANULAR_DC_TOTAL_PATHS = [
    "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_EXISTE_VENC_ADIMPL",
    "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_EXISTE_VENC_INAD",
    "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_EXISTE_INAD",
    "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_CEDENT",
    "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_EXISTE_VENC_INAD",
    "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_EXISTE_INAD",
]
_AGGREGATE_DC_TOTAL_PATHS = [
    "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_SOM_DICRED_AQUIS",
    "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED",
]
_AGGREGATE_OVERDUE_TOTAL_PATHS = [
    "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_TOTAL_VENC_INAD",
    "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_TOTAL_VENC_INAD",
]
_MEZZANINE_TOKEN_RE = re.compile(r"(mezz|mezan|mezanino|mezzanine)", re.IGNORECASE)
OFFICIAL_PL_PATH = "DOC_ARQ/LISTA_INFORM/PATRLIQ/VL_PATRIM_LIQ"
PL_RECONCILIATION_WARNING_PCT = 0.5


@dataclass(frozen=True)
class FundonetDashboardData:
    competencias: list[str]
    latest_competencia: str
    fund_info: dict[str, str]
    summary: dict[str, float | str | None]
    asset_history_df: pd.DataFrame
    composition_latest_df: pd.DataFrame
    segment_latest_df: pd.DataFrame
    liquidity_history_df: pd.DataFrame
    liquidity_latest_df: pd.DataFrame
    maturity_latest_df: pd.DataFrame
    maturity_history_df: pd.DataFrame
    duration_history_df: pd.DataFrame
    quota_pl_history_df: pd.DataFrame
    subordination_history_df: pd.DataFrame
    return_history_df: pd.DataFrame
    return_summary_df: pd.DataFrame
    performance_vs_benchmark_latest_df: pd.DataFrame
    event_history_df: pd.DataFrame
    dc_canonical_history_df: pd.DataFrame
    default_history_df: pd.DataFrame
    default_buckets_latest_df: pd.DataFrame
    default_buckets_history_df: pd.DataFrame
    default_aging_history_df: pd.DataFrame
    default_over_history_df: pd.DataFrame
    holder_latest_df: pd.DataFrame
    rate_negotiation_latest_df: pd.DataFrame
    tracking_latest_df: pd.DataFrame
    event_summary_latest_df: pd.DataFrame
    risk_metrics_df: pd.DataFrame
    coverage_gap_df: pd.DataFrame
    mini_glossary_df: pd.DataFrame
    current_dashboard_inventory_df: pd.DataFrame
    executive_memory_df: pd.DataFrame
    consistency_audit_df: pd.DataFrame
    methodology_notes: list[str]


def filter_dashboard_to_competencias(
    dashboard: FundonetDashboardData,
    competencias: list[str],
) -> FundonetDashboardData:
    """Return a presentation-scoped dashboard without recalculating metrics.

    The dashboard builder may load a small older buffer to tolerate unavailable
    end-month documents. This helper trims every competencia-indexed frame to
    the display window while keeping the already computed latest metrics and
    methodology intact.
    """
    selected = [str(value) for value in dashboard.competencias if str(value) in {str(item) for item in competencias}]
    if not selected:
        return dashboard
    latest_competencia = selected[-1]
    selected_set = set(selected)
    replacements: dict[str, object] = {
        "competencias": selected,
        "latest_competencia": latest_competencia,
        "fund_info": {
            **dict(dashboard.fund_info),
            "periodo_analisado": f"{selected[0]} a {latest_competencia}",
            "ultima_competencia": latest_competencia,
        },
    }
    for data_field in fields(FundonetDashboardData):
        value = getattr(dashboard, data_field.name)
        if isinstance(value, pd.DataFrame) and "competencia" in value.columns:
            filtered = value[value["competencia"].astype(str).isin(selected_set)].copy()
            replacements[data_field.name] = filtered.reset_index(drop=True)
    return replace(dashboard, **replacements)


def build_dashboard_data(
    *,
    wide_csv_path: Path,
    listas_csv_path: Path,
    docs_csv_path: Path,
) -> FundonetDashboardData:
    wide_df = pd.read_csv(wide_csv_path, dtype=str, keep_default_na=False)
    listas_df = pd.read_csv(listas_csv_path, dtype=str, keep_default_na=False)
    docs_df = pd.read_csv(docs_csv_path, dtype=str, keep_default_na=False)

    competencias = _extract_competencias(wide_df)
    if not competencias:
        raise ValueError("O CSV wide não possui colunas de competência para montar o dashboard.")

    latest_competencia = competencias[-1]
    wide_lookup = wide_df.set_index("tag_path", drop=False)

    quota_pl_history_df = _build_quota_pl_history(
        wide_lookup=wide_lookup,
        listas_df=listas_df,
        competencias=competencias,
    )
    subordination_history_df = _build_subordination_history(
        quota_pl_history_df,
        wide_lookup=wide_lookup,
        competencias=competencias,
    )
    return_history_df = _build_return_history(
        wide_lookup=wide_lookup,
        listas_df=listas_df,
        competencias=competencias,
    )
    return_summary_df = _build_return_summary(
        return_history_df=return_history_df,
        latest_competencia=latest_competencia,
    )
    performance_vs_benchmark_latest_df = _build_performance_vs_benchmark_latest_df(
        wide_lookup=wide_lookup,
        listas_df=listas_df,
        competencias=competencias,
        latest_competencia=latest_competencia,
    )
    raw_event_history_df = _build_event_history(
        wide_lookup=wide_lookup,
        listas_df=listas_df,
        competencias=competencias,
    )
    dc_canonical_history_df = _build_dc_canonical_history_df(
        wide_lookup=wide_lookup,
        competencias=competencias,
    )
    asset_history_df = _build_asset_history(
        wide_lookup=wide_lookup,
        competencias=competencias,
        dc_canonical_history_df=dc_canonical_history_df,
    )
    default_history_df = _build_default_history(
        wide_lookup=wide_lookup,
        competencias=competencias,
        dc_canonical_history_df=dc_canonical_history_df,
    )
    event_history_df = _decorate_event_history(
        event_history_df=raw_event_history_df,
        subordination_history_df=subordination_history_df,
    )

    composition_latest_df = _build_composition_latest_df(asset_history_df)
    segment_latest_df = _build_segment_latest_df(
        wide_lookup=wide_lookup,
        latest_competencia=latest_competencia,
    )
    liquidity_history_df = _build_liquidity_history_df(
        wide_lookup=wide_lookup,
        competencias=competencias,
    )
    liquidity_latest_df = _build_liquidity_latest_df(
        wide_lookup=wide_lookup,
        latest_competencia=latest_competencia,
    )
    maturity_latest_df = _build_maturity_latest_df(
        wide_lookup=wide_lookup,
        latest_competencia=latest_competencia,
    )
    maturity_history_df = _build_maturity_history_df(
        wide_lookup=wide_lookup,
        competencias=competencias,
    )
    duration_history_df = _build_duration_history_df(maturity_history_df)
    default_buckets_latest_df = _build_default_buckets_latest_df(
        wide_lookup=wide_lookup,
        latest_competencia=latest_competencia,
        dc_canonical_history_df=dc_canonical_history_df,
    )
    default_buckets_history_df = _build_default_buckets_history_df(
        wide_lookup=wide_lookup,
        competencias=competencias,
    )
    default_aging_history_df = _build_default_aging_history_df(
        default_buckets_history_df=default_buckets_history_df,
        dc_canonical_history_df=dc_canonical_history_df,
    )
    default_over_history_df = _build_default_over_history_df(
        default_buckets_history_df=default_buckets_history_df,
        dc_canonical_history_df=dc_canonical_history_df,
    )
    holder_latest_df = _build_holder_latest_df(
        wide_lookup=wide_lookup,
        listas_df=listas_df,
        latest_competencia=latest_competencia,
    )
    rate_negotiation_latest_df = _build_rate_negotiation_latest_df(
        wide_lookup=wide_lookup,
        latest_competencia=latest_competencia,
    )
    fund_info = _build_fund_info(
        wide_lookup=wide_lookup,
        docs_df=docs_df,
        competencias=competencias,
        latest_competencia=latest_competencia,
    )
    summary = _build_summary(
        latest_competencia=latest_competencia,
        wide_lookup=wide_lookup,
        asset_history_df=asset_history_df,
        subordination_history_df=subordination_history_df,
        default_history_df=default_history_df,
        event_history_df=event_history_df,
        dc_canonical_history_df=dc_canonical_history_df,
    )
    tracking_latest_df = _build_tracking_latest_df(
        summary=summary,
        asset_history_df=asset_history_df,
        wide_lookup=wide_lookup,
        latest_competencia=latest_competencia,
    )
    event_summary_latest_df = _build_event_summary_latest_df(
        wide_lookup=wide_lookup,
        latest_competencia=latest_competencia,
        pl_total=summary.get("pl_total"),
    )
    risk_metrics_df = build_risk_metrics_df(
        latest_competencia=latest_competencia,
        summary=summary,
        asset_history_df=asset_history_df,
        segment_latest_df=segment_latest_df,
        subordination_history_df=subordination_history_df,
        default_history_df=default_history_df,
        event_summary_latest_df=event_summary_latest_df,
    )
    coverage_gap_df = build_coverage_gap_df()
    mini_glossary_df = build_mini_glossary_df()
    current_dashboard_inventory_df = build_current_dashboard_inventory_df()
    executive_memory_df = _build_executive_memory_df(
        latest_competencia=latest_competencia,
        summary=summary,
        dc_canonical_history_df=dc_canonical_history_df,
        default_buckets_latest_df=default_buckets_latest_df,
        risk_metrics_df=risk_metrics_df,
    )
    consistency_audit_df = _build_consistency_audit_df(
        latest_competencia=latest_competencia,
        summary=summary,
        current_dashboard_inventory_df=current_dashboard_inventory_df,
        dc_canonical_history_df=dc_canonical_history_df,
        default_history_df=default_history_df,
        default_aging_history_df=default_aging_history_df,
        default_over_history_df=default_over_history_df,
        risk_metrics_df=risk_metrics_df,
    )

    methodology_notes = [
        "Direitos creditórios totais usam uma base canônica única: 1) malha de vencimento (vencidos + a vencer), 2) estoque granular em APLIC_ATIVO, 3) agregados VL_SOM_DICRED_AQUIS + VL_DICRED.",
        "Subordinação reportada (IME) usa a mesma regra das memórias de cálculo: (PL mezzanino + PL subordinada residual) / PL total.",
        "Aging da inadimplência mostra a distribuição do estoque vencido por faixa (% da inadimplência); Inadimplência Over mostra cortes cumulativos sobre os direitos creditórios totais.",
        "Cobertura de provisão usa apenas vencidos canônicos como denominador e fica segregada no eixo direito.",
        "Resgate solicitado usa os campos RESG_SOLIC do Informe Mensal e aceita tanto VL_PAGO quanto VL_COTAS, pois há divergência observada entre schema e XML real.",
        "Indicadores como cobertura, relação mínima, reservas, rating, coobrigação e eventos contratuais exigem documentação complementar.",
    ]

    return FundonetDashboardData(
        competencias=competencias,
        latest_competencia=latest_competencia,
        fund_info=fund_info,
        summary=summary,
        asset_history_df=asset_history_df,
        composition_latest_df=composition_latest_df,
        segment_latest_df=segment_latest_df,
        liquidity_history_df=liquidity_history_df,
        liquidity_latest_df=liquidity_latest_df,
        maturity_latest_df=maturity_latest_df,
        maturity_history_df=maturity_history_df,
        duration_history_df=duration_history_df,
        quota_pl_history_df=quota_pl_history_df,
        subordination_history_df=subordination_history_df,
        return_history_df=return_history_df,
        return_summary_df=return_summary_df,
        performance_vs_benchmark_latest_df=performance_vs_benchmark_latest_df,
        event_history_df=event_history_df,
        dc_canonical_history_df=dc_canonical_history_df,
        default_history_df=default_history_df,
        default_buckets_latest_df=default_buckets_latest_df,
        default_buckets_history_df=default_buckets_history_df,
        default_aging_history_df=default_aging_history_df,
        default_over_history_df=default_over_history_df,
        holder_latest_df=holder_latest_df,
        rate_negotiation_latest_df=rate_negotiation_latest_df,
        tracking_latest_df=tracking_latest_df,
        event_summary_latest_df=event_summary_latest_df,
        risk_metrics_df=risk_metrics_df,
        coverage_gap_df=coverage_gap_df,
        mini_glossary_df=mini_glossary_df,
        current_dashboard_inventory_df=current_dashboard_inventory_df,
        executive_memory_df=executive_memory_df,
        consistency_audit_df=consistency_audit_df,
        methodology_notes=methodology_notes,
    )


def _extract_competencias(wide_df: pd.DataFrame) -> list[str]:
    competencias = [column for column in wide_df.columns if COMPETENCIA_COLUMN_RE.fullmatch(str(column))]
    return sorted(competencias, key=_competencia_sort_key)


def _competencia_sort_key(label: str) -> tuple[int, int]:
    month, year = label.split("/")
    return int(year), int(month)


def _competencia_to_timestamp(label: str) -> pd.Timestamp:
    return pd.to_datetime(f"01/{label}", format="%d/%m/%Y")


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    return str(value).strip() in {"", "nan", "None", "<NA>"}


def _display_value(value: object) -> str:
    return "" if _is_blank(value) else str(value).strip()


def _to_numeric(value: object) -> float | None:
    if _is_blank(value):
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _get_wide_series(wide_lookup: pd.DataFrame, competencias: list[str], tag_path: str) -> pd.Series:
    if tag_path not in wide_lookup.index:
        return pd.Series([pd.NA] * len(competencias), index=competencias, dtype="object")
    row = wide_lookup.loc[tag_path]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    return pd.Series([row.get(competencia, pd.NA) for competencia in competencias], index=competencias, dtype="object")


def _numeric_series(wide_lookup: pd.DataFrame, competencias: list[str], tag_path: str) -> pd.Series:
    return _numeric_series_nullable(wide_lookup, competencias, tag_path).fillna(0.0)


def _numeric_series_nullable(wide_lookup: pd.DataFrame, competencias: list[str], tag_path: str) -> pd.Series:
    raw_series = _get_wide_series(wide_lookup, competencias, tag_path)
    numeric = pd.to_numeric(raw_series, errors="coerce")
    numeric.index = competencias
    return numeric.astype("float64")


def _latest_path_value(
    wide_lookup: pd.DataFrame,
    competencia: str,
    tag_path: str,
) -> tuple[float | None, str]:
    if tag_path not in wide_lookup.index:
        return None, "missing_field"
    raw = _get_wide_series(wide_lookup, [competencia], tag_path).iloc[0]
    if _is_blank(raw):
        return None, "not_reported"
    value = _to_numeric(raw)
    if value is None:
        return None, "not_numeric"
    if value == 0:
        return 0.0, "reported_zero"
    return value, "reported_value"


def _combine_source_status(statuses: list[str], total: float | None) -> str:
    if total is not None and total != 0:
        return "reported_value"
    if any(status == "reported_zero" for status in statuses):
        return "reported_zero"
    if any(status == "not_numeric" for status in statuses):
        return "not_numeric"
    if any(status == "not_reported" for status in statuses):
        return "not_reported"
    if statuses and all(status == "missing_field" for status in statuses):
        return "missing_field"
    return "not_available"


def _sum_latest_paths_with_status(
    wide_lookup: pd.DataFrame,
    competencia: str,
    tag_paths: list[str],
) -> dict[str, object]:
    values: list[float] = []
    statuses: list[str] = []
    present_paths = 0
    for tag_path in tag_paths:
        value, status = _latest_path_value(wide_lookup, competencia, tag_path)
        statuses.append(status)
        if status != "missing_field":
            present_paths += 1
        if value is not None:
            values.append(value)
    total = float(sum(values)) if values else None
    return {
        "valor": total if total is not None else 0.0,
        "valor_raw": total,
        "source_status": _combine_source_status(statuses, total),
        "source_paths": len(tag_paths),
        "present_source_paths": present_paths,
    }


def _first_available_latest_paths_with_status(
    wide_lookup: pd.DataFrame,
    competencia: str,
    tag_paths: list[str],
) -> dict[str, object]:
    statuses: list[str] = []
    present_paths = 0
    zero_reported = False
    for tag_path in tag_paths:
        value, status = _latest_path_value(wide_lookup, competencia, tag_path)
        statuses.append(status)
        if status != "missing_field":
            present_paths += 1
        if status == "reported_value":
            return {
                "valor": float(value or 0.0),
                "valor_raw": value,
                "source_status": status,
                "source_paths": len(tag_paths),
                "present_source_paths": present_paths,
            }
        if status == "reported_zero":
            zero_reported = True
    final_status = "reported_zero" if zero_reported else _combine_source_status(statuses, None)
    return {
        "valor": 0.0,
        "valor_raw": 0.0 if zero_reported else None,
        "source_status": final_status,
        "source_paths": len(tag_paths),
        "present_source_paths": present_paths,
    }


def _sum_latest_path_groups_with_status(
    wide_lookup: pd.DataFrame,
    competencia: str,
    tag_path_groups: list[list[str]],
) -> dict[str, object]:
    group_infos = [
        _first_available_latest_paths_with_status(wide_lookup, competencia, tag_paths)
        for tag_paths in tag_path_groups
    ]
    values = [float(info["valor_raw"]) for info in group_infos if info.get("valor_raw") is not None]
    total = float(sum(values)) if values else None
    return {
        "valor": total if total is not None else 0.0,
        "valor_raw": total,
        "source_status": _combine_source_status([str(info["source_status"]) for info in group_infos], total),
        "source_paths": sum(int(info["source_paths"]) for info in group_infos),
        "present_source_paths": sum(int(info["present_source_paths"]) for info in group_infos),
    }


def _sum_paths_history_with_status(
    wide_lookup: pd.DataFrame,
    competencias: list[str],
    tag_paths: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for competencia in competencias:
        rows.append(
            {
                "competencia": competencia,
                "competencia_dt": _competencia_to_timestamp(competencia),
                **_sum_latest_paths_with_status(wide_lookup, competencia, tag_paths),
            }
        )
    return pd.DataFrame(rows)


def _accepted_info(info: dict[str, object], *, min_present_paths: int = 1) -> bool:
    status = str(info.get("source_status") or "")
    present_paths = int(info.get("present_source_paths") or 0)
    return (
        status in {"reported_value", "reported_zero"}
        and info.get("valor_raw") is not None
        and present_paths >= min_present_paths
    )


def _compose_info(
    parts: list[dict[str, object]],
    *,
    require_all_parts: bool = True,
) -> dict[str, object]:
    statuses = [str(info.get("source_status") or "not_available") for info in parts]
    source_paths = sum(int(info.get("source_paths") or 0) for info in parts)
    present_source_paths = sum(int(info.get("present_source_paths") or 0) for info in parts)
    values: list[float] = []
    missing_part = False
    for info in parts:
        raw = info.get("valor_raw")
        if raw is None:
            missing_part = True
            continue
        values.append(float(raw))
    total = None
    if values and (not require_all_parts or not missing_part):
        total = float(sum(values))
    return {
        "valor": total if total is not None else 0.0,
        "valor_raw": total,
        "source_status": _combine_source_status(statuses, total),
        "source_paths": source_paths,
        "present_source_paths": present_source_paths,
    }


def _select_canonical_info(
    candidates: list[tuple[str, dict[str, object], int]],
) -> dict[str, object]:
    for source_kind, info, min_present_paths in candidates:
        if _accepted_info(info, min_present_paths=min_present_paths):
            return {
                **info,
                "source_kind": source_kind,
            }
    return {
        "valor": 0.0,
        "valor_raw": None,
        "source_status": "not_available",
        "source_paths": 0,
        "present_source_paths": 0,
        "source_kind": "not_available",
    }


def _canonical_dc_total_path_labels() -> str:
    return (
        "1) COMPMT_DICRED_AQUIS + COMPMT_DICRED_SEM_AQUIS (vencidos + a vencer); "
        "2) estoque granular em APLIC_ATIVO; "
        "3) agregados VL_SOM_DICRED_AQUIS + VL_DICRED."
    )


def _reconciliation_status(base_value: float | None, compare_value: float | None) -> tuple[str, float | None]:
    if base_value is None or compare_value is None or base_value <= 0 or compare_value <= 0:
        return "sem_base", None
    gap_pct = abs(base_value - compare_value) / max(abs(base_value), abs(compare_value)) * 100.0
    if gap_pct <= 1.0:
        return "conciliado", gap_pct
    return "divergente", gap_pct


def _materialize_status_value(value: object, status: object) -> float | None:
    if str(status) not in {"reported_value", "reported_zero"}:
        return None
    numeric = _to_numeric(value)
    if numeric is not None:
        return numeric
    return 0.0 if str(status) == "reported_zero" else None


def _numeric_series_first_available(
    wide_lookup: pd.DataFrame,
    competencias: list[str],
    tag_paths: list[str],
) -> pd.Series:
    output = pd.Series([float("nan")] * len(competencias), index=competencias, dtype="float64")
    for tag_path in tag_paths:
        candidate = _numeric_series_nullable(wide_lookup, competencias, tag_path)
        output = output.combine_first(candidate)
    return output


def _direitos_creditorios_series(wide_lookup: pd.DataFrame, competencias: list[str]) -> pd.Series:
    primary = _numeric_series_first_available(
        wide_lookup,
        competencias,
        [
            "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED",
            "DOC_ARQ/LISTA_INFORM/CART_SEGMT/VL_SOM_CART_SEGMT",
        ],
    )
    legacy_parts = [
        _numeric_series_nullable(wide_lookup, competencias, "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_EXISTE_VENC_ADIMPL"),
        _numeric_series_nullable(wide_lookup, competencias, "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_EXISTE_VENC_INAD"),
        _numeric_series_nullable(wide_lookup, competencias, "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_EXISTE_INAD"),
        _numeric_series_nullable(wide_lookup, competencias, "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_EXISTE_VENC_INAD"),
        _numeric_series_nullable(wide_lookup, competencias, "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_EXISTE_INAD"),
    ]
    legacy = pd.concat(legacy_parts, axis=1).sum(axis=1, min_count=1)
    return primary.combine_first(legacy)


def _sum_paths_series_nullable(
    wide_lookup: pd.DataFrame,
    competencias: list[str],
    tag_paths: list[str],
) -> pd.Series:
    if not tag_paths:
        return pd.Series([float("nan")] * len(competencias), index=competencias, dtype="float64")
    parts = [_numeric_series_nullable(wide_lookup, competencias, tag_path) for tag_path in tag_paths]
    return pd.concat(parts, axis=1).sum(axis=1, min_count=1)


def _prefer_nonzero_series(*series_list: pd.Series) -> pd.Series:
    if not series_list:
        return pd.Series(dtype="float64")
    normalized = [pd.to_numeric(series, errors="coerce") for series in series_list]
    index = normalized[0].index
    output = pd.Series(index=index, dtype="float64")
    for key in index:
        chosen = float("nan")
        values = [series.loc[key] for series in normalized]
        for value in values:
            if pd.notna(value) and float(value) > 0:
                chosen = float(value)
                break
        if pd.isna(chosen):
            for value in values:
                if pd.notna(value):
                    chosen = float(value)
                    break
        output.loc[key] = chosen
    return output


def _maturity_future_series(wide_lookup: pd.DataFrame, competencias: list[str]) -> pd.Series:
    future_suffixes = [
        "VL_PRAZO_VENC_30",
        "VL_PRAZO_VENC_31_60",
        "VL_PRAZO_VENC_61_90",
        "VL_PRAZO_VENC_91_120",
        "VL_PRAZO_VENC_121_150",
        "VL_PRAZO_VENC_151_180",
        "VL_PRAZO_VENC_181_360",
        "VL_PRAZO_VENC_361_720",
        "VL_PRAZO_VENC_721_1080",
        "VL_PRAZO_VENC_1080",
    ]
    paths = [
        f"DOC_ARQ/LISTA_INFORM/{base}/{suffix}"
        for suffix in future_suffixes
        for base in ["COMPMT_DICRED_AQUIS", "COMPMT_DICRED_SEM_AQUIS"]
    ]
    return _sum_paths_series_nullable(wide_lookup, competencias, paths)


def _maturity_overdue_series(wide_lookup: pd.DataFrame, competencias: list[str]) -> pd.Series:
    paths = [
        f"DOC_ARQ/LISTA_INFORM/{base}/VL_SOM_INAD_VENC"
        for base in ["COMPMT_DICRED_AQUIS", "COMPMT_DICRED_SEM_AQUIS"]
    ]
    return _sum_paths_series_nullable(wide_lookup, competencias, paths)


def _default_aging_total_series(wide_lookup: pd.DataFrame, competencias: list[str]) -> pd.Series:
    suffixes = [
        "VL_INAD_VENC_30",
        "VL_INAD_VENC_31_60",
        "VL_INAD_VENC_61_90",
        "VL_INAD_VENC_91_120",
        "VL_INAD_VENC_121_150",
        "VL_INAD_VENC_151_180",
        "VL_INAD_VENC_181_360",
        "VL_INAD_VENC_361_720",
        "VL_INAD_VENC_721_1080",
        "VL_INAD_VENC_1080",
    ]
    paths = [
        f"DOC_ARQ/LISTA_INFORM/{base}/{suffix}"
        for suffix in suffixes
        for base in ["COMPMT_DICRED_AQUIS", "COMPMT_DICRED_SEM_AQUIS"]
    ]
    return _sum_paths_series_nullable(wide_lookup, competencias, paths)


def _build_fund_info(
    *,
    wide_lookup: pd.DataFrame,
    docs_df: pd.DataFrame,
    competencias: list[str],
    latest_competencia: str,
) -> dict[str, str]:
    docs_ok_df = docs_df
    if "processamento" in docs_df.columns:
        docs_ok_df = docs_df[docs_df["processamento"] == "ok"].copy()
        if docs_ok_df.empty:
            docs_ok_df = docs_df.copy()
    docs_ok_df["competencia_ord"] = docs_ok_df["competencia"].map(_competencia_to_timestamp)
    latest_doc = docs_ok_df.sort_values("competencia_ord").iloc[-1]

    def wide_value(tag_path: str) -> str:
        return _display_value(_get_wide_series(wide_lookup, [latest_competencia], tag_path).iloc[0])

    def doc_value(*columns: str) -> str:
        for column in columns:
            value = _display_value(latest_doc.get(column, ""))
            if value != "N/D":
                return value
        return "N/D"

    def wide_first_matching(patterns: list[str]) -> str:
        if "tag_path" not in wide_lookup.columns:
            return "N/D"
        index_values = [str(value) for value in wide_lookup.index.tolist()]
        for pattern in patterns:
            regex = re.compile(pattern, re.IGNORECASE)
            for tag_path in index_values:
                if regex.search(tag_path):
                    return wide_value(tag_path)
        return "N/D"

    cnpj_fundo = normalize_cnpj_digits(wide_value("DOC_ARQ/CAB_INFORM/NR_CNPJ_FUNDO"))
    cnpj_classe = normalize_cnpj_digits(wide_value("DOC_ARQ/CAB_INFORM/NR_CNPJ_CLASSE"))
    participantes = fetch_fidc_participantes(
        cnpj_fundo,
        cnpj_classe=cnpj_classe,
        allow_network=False,
    )
    doc_admin = doc_value("nome_administrador", "administrador", "nomeAdministrador")
    doc_custodiante = doc_value("nome_custodiante", "custodiante", "nomeCustodiante")
    doc_gestor = doc_value("nome_gestor", "gestor", "nomeGestor")
    wide_admin = wide_first_matching([r"/NM_.*ADM", r"/NOME_.*ADM", r"/DENOM.*ADM", r"/RAZAO.*ADM"])
    wide_custodiante = wide_first_matching([r"/NM_.*CUST", r"/NOME_.*CUST", r"/DENOM.*CUST", r"/RAZAO.*CUST"])
    wide_gestor = wide_first_matching([r"/NM_.*GEST", r"/NOME_.*GEST", r"/DENOM.*GEST", r"/RAZAO.*GEST"])

    return {
        "nome_fundo": _display_value(latest_doc.get("nome_fundo", "")),
        "fundo_ou_classe": _display_value(latest_doc.get("fundo_ou_classe", "")),
        "cnpj_fundo": cnpj_fundo,
        "cnpj_classe": cnpj_classe,
        "cnpj_administrador": normalize_cnpj_digits(wide_value("DOC_ARQ/CAB_INFORM/NR_CNPJ_ADM"))
        or normalize_cnpj_digits(participantes["cnpj_admin"]),
        "nm_admin": participantes["nm_admin"] or None,
        "nm_gestor": participantes["nm_gestor"] or None,
        "nm_custodiante": participantes["nm_custodiante"] or None,
        "cnpj_admin_cadastro": normalize_cnpj_digits(participantes["cnpj_admin"]),
        "cnpj_gestor": normalize_cnpj_digits(participantes["cnpj_gestor"]),
        "cnpj_custodiante": normalize_cnpj_digits(participantes["cnpj_custodiante"]),
        "fonte_nome_administrador": participantes["fonte_admin"],
        "fonte_nome_gestor": participantes["fonte_gestor"],
        "fonte_nome_custodiante": participantes["fonte_custodiante"],
        "nome_administrador": doc_admin if doc_admin != "N/D" else participantes["nm_admin"] or wide_admin,
        "nome_custodiante": doc_custodiante if doc_custodiante != "N/D" else participantes["nm_custodiante"] or wide_custodiante,
        "nome_gestor": doc_gestor if doc_gestor != "N/D" else participantes["nm_gestor"] or wide_gestor,
        "nome_classe": wide_value("DOC_ARQ/CAB_INFORM/NM_CLASSE"),
        "condominio": wide_value("DOC_ARQ/CAB_INFORM/TP_CONDOMINIO"),
        "classe_unica": wide_value("DOC_ARQ/CAB_INFORM/CLASS_UNICA"),
        "estrutura_subordinada": wide_value("DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/NUM_COTISTAS/EXISTE_ESTRU_SUBORD"),
        "total_cotistas": wide_value("DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/NUM_COTISTAS/QT_TOTAL_COTISTAS"),
        "periodo_analisado": f"{competencias[0]} a {latest_competencia}",
        "ultima_competencia": latest_competencia,
        "ultima_entrega": _display_value(latest_doc.get("data_entrega", "")),
    }


def _build_dc_canonical_history_df(
    *,
    wide_lookup: pd.DataFrame,
    competencias: list[str],
) -> pd.DataFrame:
    future_paths = [
        f"DOC_ARQ/LISTA_INFORM/{base}/{suffix}"
        for suffix in _MALHA_FUTURE_SUFFIXES
        for base in _MALHA_BASES
    ]
    overdue_maturity_paths = [
        f"DOC_ARQ/LISTA_INFORM/{base}/VL_SOM_INAD_VENC"
        for base in _MALHA_BASES
    ]
    aging_paths = [
        f"DOC_ARQ/LISTA_INFORM/{base}/{suffix}"
        for suffix in _AGING_SUFFIXES
        for base in _MALHA_BASES
    ]
    rows: list[dict[str, object]] = []
    for competencia in competencias:
        future_info = _sum_latest_paths_with_status(wide_lookup, competencia, future_paths)
        overdue_maturity_info = _sum_latest_paths_with_status(wide_lookup, competencia, overdue_maturity_paths)
        overdue_aging_info = _sum_latest_paths_with_status(wide_lookup, competencia, aging_paths)
        overdue_aggregate_info = _sum_latest_paths_with_status(wide_lookup, competencia, _AGGREGATE_OVERDUE_TOTAL_PATHS)
        overdue_effective = _select_canonical_info(
            [
                ("malha_vencimento", overdue_maturity_info, 1),
                ("aging_inadimplencia", overdue_aging_info, 4),
                ("agregado_vencidos_aplic_ativo", overdue_aggregate_info, 1),
            ]
        )
        maturity_total_info = _compose_info([future_info, overdue_effective], require_all_parts=True)
        maturity_min_present_paths = 2 if overdue_effective.get("source_kind") == "malha_vencimento" else 6
        granular_total_info = _sum_latest_paths_with_status(wide_lookup, competencia, _GRANULAR_DC_TOTAL_PATHS)
        aggregate_total_info = _sum_latest_paths_with_status(wide_lookup, competencia, _AGGREGATE_DC_TOTAL_PATHS)
        total_effective = _select_canonical_info(
            [
                ("malha_vencimento", maturity_total_info, maturity_min_present_paths),
                ("estoque_granular_aplic_ativo", granular_total_info, 2),
                ("agregado_direitos_creditorios_item3", aggregate_total_info, 1),
            ]
        )
        recon_malha_granular_status, recon_malha_granular_gap = _reconciliation_status(
            _to_numeric(maturity_total_info.get("valor_raw")),
            _to_numeric(granular_total_info.get("valor_raw")),
        )
        recon_malha_agregado_status, recon_malha_agregado_gap = _reconciliation_status(
            _to_numeric(maturity_total_info.get("valor_raw")),
            _to_numeric(aggregate_total_info.get("valor_raw")),
        )
        rows.append(
            {
                "competencia": competencia,
                "competencia_dt": _competencia_to_timestamp(competencia),
                "dc_total_canonico": _to_numeric(total_effective.get("valor_raw")),
                "dc_total_fonte_efetiva": total_effective.get("source_kind"),
                "dc_total_source_status": total_effective.get("source_status"),
                "dc_total_malha_vencimento": _to_numeric(maturity_total_info.get("valor_raw")),
                "dc_total_estoque_granular": _to_numeric(granular_total_info.get("valor_raw")),
                "dc_total_agregado_item3": _to_numeric(aggregate_total_info.get("valor_raw")),
                "dc_total_present_source_paths": total_effective.get("present_source_paths"),
                "dc_total_source_paths": total_effective.get("source_paths"),
                "dc_vencidos_canonico": _to_numeric(overdue_effective.get("valor_raw")),
                "dc_vencidos_fonte_efetiva": overdue_effective.get("source_kind"),
                "dc_vencidos_source_status": overdue_effective.get("source_status"),
                "dc_vencidos_malha_vencimento": _to_numeric(overdue_maturity_info.get("valor_raw")),
                "dc_vencidos_aging": _to_numeric(overdue_aging_info.get("valor_raw")),
                "dc_vencidos_agregado_aplic_ativo": _to_numeric(overdue_aggregate_info.get("valor_raw")),
                "dc_a_vencer_canonico": _to_numeric(future_info.get("valor_raw")),
                "dc_a_vencer_source_status": future_info.get("source_status"),
                "reconciliacao_malha_vs_estoque_status": recon_malha_granular_status,
                "reconciliacao_malha_vs_estoque_gap_pct": recon_malha_granular_gap,
                "reconciliacao_malha_vs_agregado_status": recon_malha_agregado_status,
                "reconciliacao_malha_vs_agregado_gap_pct": recon_malha_agregado_gap,
            }
        )
    return pd.DataFrame(rows)


def _build_default_aging_history_df(
    *,
    default_buckets_history_df: pd.DataFrame,
    dc_canonical_history_df: pd.DataFrame,
) -> pd.DataFrame:
    if default_buckets_history_df.empty or dc_canonical_history_df.empty:
        return pd.DataFrame(
            columns=[
                "competencia",
                "competencia_dt",
                "ordem",
                "faixa",
                "valor",
                "percentual_inadimplencia",
                "percentual_direitos_creditorios",
                "source_status",
            ]
        )
    df = default_buckets_history_df.copy()
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
    overdue_totals = df.groupby("competencia", dropna=False)["valor"].sum().rename("inadimplencia_total_aging")
    df = df.merge(overdue_totals, on="competencia", how="left")
    df["percentual_inadimplencia"] = (
        df["valor"] / pd.to_numeric(df["inadimplencia_total_aging"], errors="coerce")
    ).where(pd.to_numeric(df["inadimplencia_total_aging"], errors="coerce") > 0).mul(100.0)
    denominator_df = dc_canonical_history_df[["competencia", "dc_total_canonico", "dc_total_fonte_efetiva"]].copy()
    df = df.merge(denominator_df, on="competencia", how="left")
    df["percentual_direitos_creditorios"] = (
        df["valor"] / pd.to_numeric(df["dc_total_canonico"], errors="coerce")
    ).where(pd.to_numeric(df["dc_total_canonico"], errors="coerce") > 0).mul(100.0)
    return df


def _build_default_over_history_df(
    *,
    default_buckets_history_df: pd.DataFrame,
    dc_canonical_history_df: pd.DataFrame,
) -> pd.DataFrame:
    # DIVERGÊNCIA CONHECIDA com a lâmina (guardrail — não alterar sem evidência):
    # Este cálculo usa `dc_total_canonico` como denominador (campo granular agregado
    # a partir dos XMLs de informe). A lâmina do FIDC exibe `inadimplencia_pct`
    # calculada em `_build_default_history` com denominador `direitos_creditorios`
    # (campo APLIC_ATIVO/CRED_EXISTE ou equivalente). As duas séries podem divergir
    # quando o FIDC reporta os campos de forma incompleta ou quando a carteira inclui
    # recebíveis sem detalhamento de aging (e.g. créditos com `source_status !=
    # "reported_value"`). Para reconciliar: comparar `dc_total_canonico` vs
    # `direitos_creditorios` em `dc_canonical_history_df` para o período divergente.
    if default_buckets_history_df.empty or dc_canonical_history_df.empty:
        return pd.DataFrame(
            columns=[
                "competencia",
                "competencia_dt",
                "ordem",
                "serie",
                "valor",
                "percentual",
                "calculo_status",
                "denominador_fonte",
            ]
        )
    source_df = default_buckets_history_df.copy()
    source_df["valor"] = pd.to_numeric(source_df["valor"], errors="coerce").fillna(0.0)
    denominator_lookup = dc_canonical_history_df.set_index("competencia", drop=False)
    rows: list[dict[str, object]] = []
    for ordem, (serie, ordem_min, ordem_max) in enumerate(_OVER_BUCKET_SPECS, start=1):
        subset = source_df[source_df["ordem"] >= ordem_min].copy()
        if ordem_max is not None:
            subset = subset[subset["ordem"] <= ordem_max].copy()
        for competencia, group_df in subset.groupby("competencia", dropna=False):
            if competencia not in denominator_lookup.index:
                continue
            denom_row = denominator_lookup.loc[competencia]
            denominator = _to_numeric(denom_row.get("dc_total_canonico"))
            statuses = {str(value or "") for value in group_df.get("source_status", pd.Series(dtype="object")).tolist()}
            # "missing_field" means the XML path is absent from the informe — treat as zero
            # (the valor sum already fills these as 0.0 via fillna). Only truly uncertain
            # statuses (not_reported, not_numeric) should suppress the calculation.
            uncertain = statuses - {"reported_value", "reported_zero", "missing_field"}
            has_missing_fields = bool(statuses & {"missing_field"})
            valor = float(group_df["valor"].sum())
            percentual = None
            calculo_status = "calculado"
            if denominator is None or denominator <= 0:
                calculo_status = "sem_denominador"
            elif uncertain:
                calculo_status = "bucket_incompleto"
            else:
                percentual = valor / denominator * 100.0
                if has_missing_fields:
                    calculo_status = "calculado_parcial"
            rows.append(
                {
                    "competencia": competencia,
                    "competencia_dt": group_df["competencia_dt"].iloc[0],
                    "ordem": ordem,
                    "serie": serie,
                    "valor": valor,
                    "percentual": percentual,
                    "calculo_status": calculo_status,
                    "denominador_fonte": denom_row.get("dc_total_fonte_efetiva"),
                }
            )
    return pd.DataFrame(rows).sort_values(["competencia_dt", "ordem"]).reset_index(drop=True)


def _build_summary(
    *,
    latest_competencia: str,
    wide_lookup: pd.DataFrame,
    asset_history_df: pd.DataFrame,
    subordination_history_df: pd.DataFrame,
    default_history_df: pd.DataFrame,
    event_history_df: pd.DataFrame,
    dc_canonical_history_df: pd.DataFrame,
) -> dict[str, float | str | None]:
    asset_row = _latest_row(asset_history_df, latest_competencia)
    subordination_row = _latest_row(subordination_history_df, latest_competencia)
    default_row = _latest_row(default_history_df, latest_competencia)
    dc_row = _latest_row(dc_canonical_history_df, latest_competencia)
    latest_events_df = event_history_df[event_history_df["competencia"] == latest_competencia].copy()
    direitos_creditorios = _float_or_none(dc_row.get("dc_total_canonico"))
    carteira = _float_or_none(asset_row.get("carteira"))
    outros_ativos = _float_or_none(asset_row.get("outros_ativos_carteira"))
    alocacao_pct = _float_or_none(asset_row.get("alocacao_pct"))
    liquidez_imediata_value, liquidez_imediata_status = _latest_path_value(
        wide_lookup,
        latest_competencia,
        "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ",
    )
    liquidez_30_value, liquidez_30_status = _latest_path_value(
        wide_lookup,
        latest_competencia,
        "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_30",
    )
    resgate_solicitado_info = _sum_latest_path_groups_with_status(
        wide_lookup,
        latest_competencia,
        [
            [
                "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/RESG_SOLIC/CLASSE_SENIOR/VL_PAGO",
                "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/RESG_SOLIC/CLASSE_SENIOR/VL_COTAS",
            ],
            [
                "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/RESG_SOLIC/CLASSE_SUBORD/VL_PAGO",
                "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/RESG_SOLIC/CLASSE_SUBORD/VL_COTAS",
            ],
        ],
    )
    if direitos_creditorios is not None and direitos_creditorios <= 0:
        direitos_creditorios = None
    if carteira and carteira > 0 and (direitos_creditorios is None or direitos_creditorios <= 0):
        direitos_creditorios = None
        outros_ativos = None
        alocacao_pct = None

    return {
        "pl_total": _float_or_none(subordination_row.get("pl_total")),
        "pl_total_oficial": _float_or_none(subordination_row.get("pl_total_oficial")),
        "pl_total_classes": _float_or_none(subordination_row.get("pl_total_classes")),
        "pl_nao_reconciliado": _float_or_none(subordination_row.get("pl_nao_reconciliado")),
        "pl_reconciliacao_delta": _float_or_none(subordination_row.get("pl_reconciliacao_delta")),
        "pl_reconciliacao_delta_pct": _float_or_none(subordination_row.get("pl_reconciliacao_delta_pct")),
        "pl_reconciliacao_warning": bool(subordination_row.get("pl_reconciliacao_warning"))
        if "pl_reconciliacao_warning" in subordination_row.index
        else False,
        "subordinacao_status": subordination_row.get("subordinacao_status"),
        "pl_senior": _float_or_none(subordination_row.get("pl_senior")),
        "pl_mezzanino": _float_or_none(subordination_row.get("pl_mezzanino")),
        "pl_subordinada_strict": _float_or_none(subordination_row.get("pl_subordinada_strict")),
        "pl_subordinada": _float_or_none(subordination_row.get("pl_subordinada")),
        "ativos_totais": _float_or_none(asset_row.get("ativos_totais")),
        "carteira": carteira,
        "direitos_creditorios": direitos_creditorios,
        "direitos_creditorios_fonte": dc_row.get("dc_total_fonte_efetiva"),
        "outros_ativos_carteira": outros_ativos,
        "alocacao_pct": alocacao_pct,
        "liquidez_imediata": _materialize_status_value(liquidez_imediata_value, liquidez_imediata_status),
        "liquidez_30": _materialize_status_value(liquidez_30_value, liquidez_30_status),
        "subordinacao_pct": _float_or_none(subordination_row.get("subordinacao_pct")),
        "inadimplencia_total": _float_or_none(default_row.get("inadimplencia_total")),
        "inadimplencia_denominador": _float_or_none(default_row.get("direitos_creditorios_vencimento_total"))
        or _float_or_none(default_row.get("direitos_creditorios")),
        "inadimplencia_pct": _float_or_none(default_row.get("inadimplencia_pct")),
        "provisao_total": _float_or_none(default_row.get("provisao_total")),
        "provisao_pct_direitos": _float_or_none(default_row.get("provisao_pct_direitos")),
        "cobertura_pct": _float_or_none(default_row.get("cobertura_pct")),
        "direitos_creditorios_vencidos": _float_or_none(default_row.get("direitos_creditorios_vencidos")),
        "direitos_creditorios_vencimento_total": _float_or_none(default_row.get("direitos_creditorios_vencimento_total")),
        "emissao_mes": _sum_event_metric(latest_events_df, "emissao", "valor_total"),
        "resgate_mes": _sum_event_metric(latest_events_df, "resgate", "valor_total"),
        "resgate_solicitado_mes": _materialize_status_value(
            resgate_solicitado_info.get("valor_raw"),
            resgate_solicitado_info.get("source_status"),
        ),
        "amortizacao_mes": _sum_event_metric(latest_events_df, "amortizacao", "valor_total"),
    }


def _decorate_event_history(
    *,
    event_history_df: pd.DataFrame,
    subordination_history_df: pd.DataFrame,
) -> pd.DataFrame:
    expected_columns = [
        "competencia",
        "competencia_dt",
        "class_kind",
        "label",
        "event_type",
        "qt_cotas",
        "valor_total",
        "valor_cota",
        "event_label",
        "event_sign",
        "valor_total_assinado",
        "pl_total",
        "valor_total_pct_pl",
    ]
    if event_history_df.empty:
        return pd.DataFrame(columns=expected_columns)

    output = event_history_df.copy()
    output["event_label"] = output["event_type"].map(EVENT_LABEL).fillna(output["event_type"])
    output["event_sign"] = output["event_type"].map(EVENT_SIGN).fillna(1.0)
    output["valor_total"] = pd.to_numeric(output["valor_total"], errors="coerce").fillna(0.0)
    output["valor_total_assinado"] = output["valor_total"] * output["event_sign"]

    if subordination_history_df.empty:
        output["pl_total"] = pd.NA
    else:
        pl_lookup = subordination_history_df.set_index("competencia")["pl_total"].to_dict()
        output["pl_total"] = output["competencia"].map(pl_lookup)
    output["pl_total"] = pd.to_numeric(output["pl_total"], errors="coerce")
    output["valor_total_pct_pl"] = (
        output["valor_total_assinado"] / output["pl_total"]
    ).where(output["pl_total"] > 0).mul(100.0)
    return output


def _build_event_summary_latest_df(
    *,
    wide_lookup: pd.DataFrame,
    latest_competencia: str,
    pl_total: float | str | None,
) -> pd.DataFrame:
    prefix = "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI"
    specs = [
        (
            "emissao",
            [
                f"{prefix}/CAPT_MES/CLASSE_SENIOR/VL_TOTAL",
                f"{prefix}/CAPT_MES/CLASSE_SUBORD/VL_TOTAL",
            ],
        ),
        (
            "resgate",
            [
                f"{prefix}/RESG_MES/CLASSE_SENIOR/VL_TOTAL",
                f"{prefix}/RESG_MES/CLASSE_SUBORD/VL_TOTAL",
            ],
        ),
        (
            "resgate_solicitado",
            [
                f"{prefix}/RESG_SOLIC/CLASSE_SENIOR/VL_PAGO",
                f"{prefix}/RESG_SOLIC/CLASSE_SUBORD/VL_PAGO",
                f"{prefix}/RESG_SOLIC/CLASSE_SENIOR/VL_COTAS",
                f"{prefix}/RESG_SOLIC/CLASSE_SUBORD/VL_COTAS",
            ],
        ),
        (
            "amortizacao",
            [
                f"{prefix}/AMORT/CLASSE_SENIOR/VL_TOTAL",
                f"{prefix}/AMORT/CLASSE_SUBORD/VL_TOTAL",
            ],
        ),
    ]
    pl_value = _float_or_none(pl_total)
    rows: list[dict[str, object]] = []
    for ordem, (event_type, paths) in enumerate(specs, start=1):
        if event_type == "resgate_solicitado":
            value_info = _sum_latest_path_groups_with_status(
                wide_lookup,
                latest_competencia,
                [
                    [
                        f"{prefix}/RESG_SOLIC/CLASSE_SENIOR/VL_PAGO",
                        f"{prefix}/RESG_SOLIC/CLASSE_SENIOR/VL_COTAS",
                    ],
                    [
                        f"{prefix}/RESG_SOLIC/CLASSE_SUBORD/VL_PAGO",
                        f"{prefix}/RESG_SOLIC/CLASSE_SUBORD/VL_COTAS",
                    ],
                ],
            )
        else:
            value_info = _sum_latest_paths_with_status(wide_lookup, latest_competencia, paths)
        valor = float(value_info["valor"])
        sign = -1.0 if event_type in {"resgate", "resgate_solicitado", "amortizacao"} else 1.0
        valor_assinado = 0.0 if valor == 0 else valor * sign
        rows.append(
            {
                "ordem": ordem,
                "event_type": event_type,
                "evento": EVENT_LABEL[event_type],
                "valor_total": valor,
                "valor_total_assinado": valor_assinado,
                "valor_total_pct_pl": (valor_assinado / pl_value * 100.0) if pl_value and pl_value > 0 else pd.NA,
                "source_status": value_info["source_status"],
                "source_paths": value_info["source_paths"],
                "present_source_paths": value_info["present_source_paths"],
                "interpretação": EVENT_INTERPRETATION[event_type],
            }
        )
    return pd.DataFrame(rows)


def _latest_row(df: pd.DataFrame, competencia: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype="object")
    matches = df[df["competencia"] == competencia]
    if matches.empty:
        return df.sort_values("competencia_dt").iloc[-1]
    return matches.sort_values("competencia_dt").iloc[-1]


def _float_or_none(value: object) -> float | None:
    if _is_blank(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum_event_metric(event_df: pd.DataFrame, event_type: str, field: str) -> float:
    if event_df.empty or field not in event_df.columns:
        return 0.0
    subset = event_df[event_df["event_type"] == event_type]
    if subset.empty:
        return 0.0
    return float(pd.to_numeric(subset[field], errors="coerce").fillna(0.0).sum())


def _build_asset_history(
    *,
    wide_lookup: pd.DataFrame,
    competencias: list[str],
    dc_canonical_history_df: pd.DataFrame,
) -> pd.DataFrame:
    ativos_totais = _numeric_series_nullable(
        wide_lookup,
        competencias,
        "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/VL_SOM_APLIC_ATIVO",
    )
    carteira = _numeric_series_nullable(
        wide_lookup,
        competencias,
        "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/VL_CARTEIRA",
    )
    liquidez_total = _numeric_series_nullable(
        wide_lookup,
        competencias,
        "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ",
    )
    direitos_creditorios = (
        pd.to_numeric(dc_canonical_history_df["dc_total_canonico"], errors="coerce")
        if not dc_canonical_history_df.empty and "dc_total_canonico" in dc_canonical_history_df.columns
        else _direitos_creditorios_series(wide_lookup, competencias)
    )
    disponibilidades = _numeric_series_nullable(
        wide_lookup,
        competencias,
        "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/VL_DISPONIB",
    )
    valores_mobiliarios = _numeric_series_nullable(
        wide_lookup,
        competencias,
        "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/VALORES_MOB/VL_SOM_VALORES_MOB",
    )
    titulos_publicos = _numeric_series_nullable(
        wide_lookup,
        competencias,
        "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/VL_TITPUB_FED",
    )
    outros_ativos_reportados = _numeric_series_nullable(
        wide_lookup,
        competencias,
        "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/OUTROS_ATIVOS/VL_SOM_OUTROS_ATIVOS",
    )
    aquisicoes = _numeric_series_nullable(
        wide_lookup,
        competencias,
        "DOC_ARQ/LISTA_INFORM/NEGOC_DICRED_MES/AQUISICOES/VL_DICRED_AQUIS",
    )
    alienacoes = _numeric_series_nullable(
        wide_lookup,
        competencias,
        "DOC_ARQ/LISTA_INFORM/NEGOC_DICRED_MES/DICRED_MES_ALIEN/VL_DICRED_ALIEN",
    )

    df = pd.DataFrame(
        {
            "competencia": competencias,
            "competencia_dt": [_competencia_to_timestamp(competencia) for competencia in competencias],
            "ativos_totais": ativos_totais.values,
            "carteira": carteira.values,
            "direitos_creditorios": direitos_creditorios.values,
            "direitos_creditorios_fonte": (
                dc_canonical_history_df["dc_total_fonte_efetiva"].tolist()
                if not dc_canonical_history_df.empty and "dc_total_fonte_efetiva" in dc_canonical_history_df.columns
                else [pd.NA] * len(competencias)
            ),
            "disponibilidades": disponibilidades.values,
            "valores_mobiliarios": valores_mobiliarios.values,
            "titulos_publicos": titulos_publicos.values,
            "outros_ativos_reportados": outros_ativos_reportados.values,
            "liquidez_total": liquidez_total.values,
            "aquisicoes": aquisicoes.values,
            "alienacoes": alienacoes.values,
        }
    )
    df["outros_ativos_carteira"] = (df["carteira"] - df["direitos_creditorios"]).clip(lower=0.0)
    df["alocacao_pct"] = (df["direitos_creditorios"] / df["carteira"]).where(df["carteira"] > 0).mul(100.0)
    return df


def _build_composition_latest_df(asset_history_df: pd.DataFrame) -> pd.DataFrame:
    eligible_rows = asset_history_df[
        (asset_history_df["carteira"] > 0) & (asset_history_df["direitos_creditorios"] > 0)
    ].copy()
    if eligible_rows.empty:
        latest_row = asset_history_df.sort_values("competencia_dt").iloc[-1]
    else:
        latest_row = eligible_rows.sort_values("competencia_dt").iloc[-1]
    rows = [
        ("Direitos creditórios", latest_row.get("direitos_creditorios")),
        ("Valores mobiliários", latest_row.get("valores_mobiliarios")),
        ("Títulos públicos federais", latest_row.get("titulos_publicos")),
        ("Outros ativos", latest_row.get("outros_ativos_reportados")),
        ("Disponibilidades", latest_row.get("disponibilidades")),
    ]
    output_rows = [
        {"competencia": latest_row["competencia"], "categoria": label, "valor": float(value)}
        for label, value in rows
        if _float_or_none(value) is not None and float(value) > 0
    ]
    known_other = sum(row["valor"] for row in output_rows if row["categoria"] != "Direitos creditórios")
    residual_other = _float_or_none(latest_row.get("outros_ativos_carteira")) or 0.0
    if residual_other > 0 and known_other <= 0:
        output_rows.append(
            {
                "competencia": latest_row["competencia"],
                "categoria": "Outros ativos da carteira",
                "valor": residual_other,
            }
        )
    if not output_rows:
        output_rows.append(
            {
                "competencia": latest_row["competencia"],
                "categoria": "Carteira",
                "valor": float(latest_row.get("carteira") or 0.0),
            }
        )
    total = sum(row["valor"] for row in output_rows)
    for row in output_rows:
        row["percentual"] = (row["valor"] / total * 100.0) if total > 0 else pd.NA
    return pd.DataFrame(output_rows)


def _build_segment_latest_df(*, wide_lookup: pd.DataFrame, latest_competencia: str) -> pd.DataFrame:
    competencias = [latest_competencia]
    rows = [
        ("Indústria", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/VL_IND"),
        ("Mercado imobiliário", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/VL_MERC_IMOBIL"),
        ("Comércio", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/SEGMT_COMERC/VL_SOM_SEGMT_COMERC"),
        ("Serviços", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/SEGMT_SERV/VL_SOM_SEGMT_SERV"),
        ("Agronegócio", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/VL_AGRONEG"),
        ("Financeiro", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/SEGMT_FINANC/VL_SOM_SEGMT_FINANC"),
        ("Cartão de crédito", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/VL_CART_CRED"),
        ("Factoring", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/SEGMT_FACT/VL_SOM_SEGMT_FACT"),
        ("Setor público", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/SEGMT_SETOR_PUBLIC/VL_SOM_SEGMT_SETOR_PUBLIC"),
        ("Ações judiciais", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/VL_ACAO_JUDIC"),
        ("Propriedade intelectual", "DOC_ARQ/LISTA_INFORM/CART_SEGMT/VL_PROPRD_MARCA_PATENT"),
    ]
    output = []
    for segmento, tag_path in rows:
        valor = float(_numeric_series(wide_lookup, competencias, tag_path).iloc[0])
        output.append({"segmento": segmento, "valor": valor})
    frame = pd.DataFrame(output)
    total = float(frame["valor"].sum()) if not frame.empty else 0.0
    frame["percentual"] = (frame["valor"] / total * 100.0) if total > 0 else pd.NA
    positive = frame[frame["valor"] > 0].copy()
    return positive.reset_index(drop=True) if not positive.empty else frame


def _build_liquidity_latest_df(*, wide_lookup: pd.DataFrame, latest_competencia: str) -> pd.DataFrame:
    buckets = [
        ("Liquidez imediata", "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ"),
        ("Até 30 dias", "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_30"),
        ("Até 60 dias", "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_60"),
        ("Até 90 dias", "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_90"),
        ("Até 180 dias", "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_180"),
        ("Até 360 dias", "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_360"),
        ("Acima de 360 dias", "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_MAIS_360"),
    ]
    rows = []
    for ordem, (horizonte, tag_path) in enumerate(buckets, start=1):
        valor, status = _latest_path_value(wide_lookup, latest_competencia, tag_path)
        rows.append(
            {
                "ordem": ordem,
                "horizonte": horizonte,
                "valor": 0.0 if valor is None else float(valor),
                "valor_raw": valor,
                "source_status": status,
            }
        )
    return pd.DataFrame(rows)


def _build_liquidity_history_df(
    *,
    wide_lookup: pd.DataFrame,
    competencias: list[str],
) -> pd.DataFrame:
    rows = {
        "liquidez_imediata": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ",
        "liquidez_30": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_30",
        "liquidez_60": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_60",
        "liquidez_90": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_90",
        "liquidez_180": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_180",
        "liquidez_360": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_360",
        "liquidez_mais_360": "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_MAIS_360",
    }
    data = {
        "competencia": competencias,
        "competencia_dt": [_competencia_to_timestamp(competencia) for competencia in competencias],
    }
    for column_name, tag_path in rows.items():
        data[column_name] = _numeric_series_nullable(wide_lookup, competencias, tag_path).values
    return pd.DataFrame(data)


def _build_maturity_latest_df(*, wide_lookup: pd.DataFrame, latest_competencia: str) -> pd.DataFrame:
    bucket_specs = [
        ("Vencidos", ["VL_SOM_INAD_VENC"]),
        ("Em 30 dias", ["VL_PRAZO_VENC_30"]),
        ("31 a 60 dias", ["VL_PRAZO_VENC_31_60"]),
        ("61 a 90 dias", ["VL_PRAZO_VENC_61_90"]),
        ("91 a 120 dias", ["VL_PRAZO_VENC_91_120"]),
        ("121 a 150 dias", ["VL_PRAZO_VENC_121_150"]),
        ("151 a 180 dias", ["VL_PRAZO_VENC_151_180"]),
        ("181 a 360 dias", ["VL_PRAZO_VENC_181_360"]),
        ("361 a 720 dias", ["VL_PRAZO_VENC_361_720"]),
        ("721 a 1080 dias", ["VL_PRAZO_VENC_721_1080"]),
        ("Acima de 1080 dias", ["VL_PRAZO_VENC_1080"]),
    ]
    rows = []
    for ordem, (faixa, suffixes) in enumerate(bucket_specs, start=1):
        paths = [
            f"DOC_ARQ/LISTA_INFORM/{base}/{suffix}"
            for suffix in suffixes
            for base in ["COMPMT_DICRED_AQUIS", "COMPMT_DICRED_SEM_AQUIS"]
        ]
        row = {
            "ordem": ordem,
            "faixa": faixa,
            **_sum_latest_paths_with_status(wide_lookup, latest_competencia, paths),
        }
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Maturity history + Duration estimation
# ---------------------------------------------------------------------------

# Each tuple: (faixa_label, CVM_suffix_list, prazo_proxy_dias)
# prazo_proxy rules:
#   "Vencidos"          → 0 (overdue, no remaining term)
#   "Em 30 dias"        → 30 (bucket upper bound used as proxy)
#   Interval buckets    → midpoint of [lower, upper]
#   "Acima de 1080 dias"→ 1440 (assumed = 1080 + 360; only used when this
#                         open bucket is not dominant enough to invalidate
#                         the point estimate)
OPEN_MATURITY_BUCKET_LABEL = "Acima de 1080 dias"
OPEN_MATURITY_BUCKET_DOMINANCE_PCT = 80.0
_MATURITY_BUCKET_SPECS: list[tuple[str, list[str], float]] = [
    ("Vencidos",           ["VL_SOM_INAD_VENC"],        0.0),
    ("Em 30 dias",         ["VL_PRAZO_VENC_30"],         30.0),
    ("31 a 60 dias",       ["VL_PRAZO_VENC_31_60"],      45.5),
    ("61 a 90 dias",       ["VL_PRAZO_VENC_61_90"],      75.5),
    ("91 a 120 dias",      ["VL_PRAZO_VENC_91_120"],     105.5),
    ("121 a 150 dias",     ["VL_PRAZO_VENC_121_150"],    135.5),
    ("151 a 180 dias",     ["VL_PRAZO_VENC_151_180"],    165.5),
    ("181 a 360 dias",     ["VL_PRAZO_VENC_181_360"],    270.5),
    ("361 a 720 dias",     ["VL_PRAZO_VENC_361_720"],    540.5),
    ("721 a 1080 dias",    ["VL_PRAZO_VENC_721_1080"],   900.5),
    (OPEN_MATURITY_BUCKET_LABEL, ["VL_PRAZO_VENC_1080"],       1440.0),
]


def _build_maturity_history_df(
    *,
    wide_lookup: pd.DataFrame,
    competencias: list[str],
) -> pd.DataFrame:
    """Long-format maturity bucket saldos for every competência (used for duration time series)."""
    rows = []
    for competencia in competencias:
        for ordem, (faixa, suffixes, prazo_proxy) in enumerate(_MATURITY_BUCKET_SPECS, start=1):
            paths = [
                f"DOC_ARQ/LISTA_INFORM/{base}/{suffix}"
                for suffix in suffixes
                for base in ["COMPMT_DICRED_AQUIS", "COMPMT_DICRED_SEM_AQUIS"]
            ]
            info = _sum_latest_paths_with_status(wide_lookup, competencia, paths)
            rows.append(
                {
                    "competencia": competencia,
                    "competencia_dt": _competencia_to_timestamp(competencia),
                    "ordem": ordem,
                    "faixa": faixa,
                    "prazo_proxy": prazo_proxy,
                    "valor": float(info["valor"]),
                    "source_status": info["source_status"],
                }
            )
    return pd.DataFrame(rows)


def _build_duration_history_df(maturity_history_df: pd.DataFrame) -> pd.DataFrame:
    """Computes weighted-average duration (days) per competência.

    Formula:
        Duration_t = Σ(saldo_bucket_i,t × prazo_proxy_i) / Σ(saldo_bucket_i,t)

    Bucket proxy assumptions (documented here for traceability):
        - "Vencidos"           → 0 d  (overdue; no remaining term)
        - "Em 30 dias"         → 30 d
        - Interval [A, B]      → (A + B) / 2  (midpoint of the range)
        - "Acima de 1080 dias" → 1440 d (assumed 1080 + 360; upper bound is open)

    When the open-ended bucket ">1080d" dominates the balance, the point
    estimate is not reliable: the XML gives no upper bound for that bucket. In
    that case duration_days is left missing and data_quality explains the
    limitation explicitly.

    Returns a DataFrame with columns:
        competencia, competencia_dt, duration_days, total_saldo,
        open_bucket_saldo, open_bucket_share_pct, data_quality
    """
    if maturity_history_df.empty:
        return pd.DataFrame(
            columns=[
                "competencia",
                "competencia_dt",
                "duration_days",
                "total_saldo",
                "open_bucket_saldo",
                "open_bucket_share_pct",
                "data_quality",
            ]
        )
    df = maturity_history_df.copy()
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
    df["prazo_proxy"] = pd.to_numeric(df["prazo_proxy"], errors="coerce").fillna(0.0)
    df["weighted"] = df["valor"] * df["prazo_proxy"]
    df["open_bucket_value"] = df["valor"].where(df["faixa"].astype(str).eq(OPEN_MATURITY_BUCKET_LABEL), 0.0)

    grouped = df.groupby(["competencia", "competencia_dt"], sort=False).agg(
        total_saldo=("valor", "sum"),
        total_weighted=("weighted", "sum"),
        open_bucket_saldo=("open_bucket_value", "sum"),
    ).reset_index()
    grouped["open_bucket_share_pct"] = (
        grouped["open_bucket_saldo"] / grouped["total_saldo"]
    ).where(grouped["total_saldo"] > 0).mul(100.0)

    has_balance = grouped["total_saldo"].gt(0)
    open_bucket_dominant = pd.to_numeric(grouped["open_bucket_share_pct"], errors="coerce").ge(
        OPEN_MATURITY_BUCKET_DOMINANCE_PCT
    )
    grouped["duration_days"] = (grouped["total_weighted"] / grouped["total_saldo"]).where(
        has_balance & ~open_bucket_dominant
    )
    grouped["data_quality"] = "ok"
    grouped.loc[~has_balance, "data_quality"] = "sem_dados"
    grouped.loc[has_balance & open_bucket_dominant, "data_quality"] = "nao_calculavel_bucket_aberto_dominante"
    # Sort chronologically
    grouped = grouped.sort_values("competencia_dt").reset_index(drop=True)
    return grouped[
        [
            "competencia",
            "competencia_dt",
            "duration_days",
            "total_saldo",
            "open_bucket_saldo",
            "open_bucket_share_pct",
            "data_quality",
        ]
    ]


def _sum_latest_paths(wide_lookup: pd.DataFrame, competencias: list[str], tag_paths: list[str]) -> float:
    total = 0.0
    for tag_path in tag_paths:
        total += float(_numeric_series(wide_lookup, competencias, tag_path).iloc[0])
    return total


def _build_default_history(
    *,
    wide_lookup: pd.DataFrame,
    competencias: list[str],
    dc_canonical_history_df: pd.DataFrame,
) -> pd.DataFrame:
    parcelas_inadimplentes_total = pd.concat(
        [
            _numeric_series_nullable(
                wide_lookup,
                competencias,
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_TOTAL_VENC_INAD",
            ),
            _numeric_series_nullable(
                wide_lookup,
                competencias,
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_TOTAL_VENC_INAD",
            ),
        ],
        axis=1,
    ).sum(axis=1, min_count=1)
    creditos_existentes_inadimplentes = pd.concat(
        [
            _numeric_series_nullable(
                wide_lookup,
                competencias,
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_EXISTE_INAD",
            ),
            _numeric_series_nullable(
                wide_lookup,
                competencias,
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_EXISTE_INAD",
            ),
        ],
        axis=1,
    ).sum(axis=1, min_count=1)
    creditos_vencidos_pendentes_cessao = pd.concat(
        [
            _numeric_series_nullable(
                wide_lookup,
                competencias,
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_VENC_PEND",
            ),
            _numeric_series_nullable(
                wide_lookup,
                competencias,
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_VENC_PEND",
            ),
        ],
        axis=1,
    ).sum(axis=1, min_count=1)
    somatorio_inadimplentes_aux_validacao = pd.concat(
        [
            parcelas_inadimplentes_total,
            creditos_existentes_inadimplentes,
            creditos_vencidos_pendentes_cessao,
        ],
        axis=1,
    ).sum(axis=1, min_count=1)

    inadimplencia_total_base = pd.concat(
        [
            _numeric_series_nullable(
                wide_lookup,
                competencias,
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_TOTAL_VENC_INAD",
            ),
            _numeric_series_nullable(
                wide_lookup,
                competencias,
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_TOTAL_VENC_INAD",
            ),
        ],
        axis=1,
    ).sum(axis=1, min_count=1)
    inadimplencia_total_prazo = _maturity_overdue_series(wide_lookup, competencias)
    inadimplencia_total_aging = _default_aging_total_series(wide_lookup, competencias)
    inadimplencia_total = _prefer_nonzero_series(
        inadimplencia_total_prazo,
        inadimplencia_total_aging,
        inadimplencia_total_base,
    )
    direitos_creditorios_futuro = (
        pd.to_numeric(dc_canonical_history_df["dc_a_vencer_canonico"], errors="coerce")
        if not dc_canonical_history_df.empty and "dc_a_vencer_canonico" in dc_canonical_history_df.columns
        else _maturity_future_series(wide_lookup, competencias)
    )
    direitos_creditorios_vencidos = (
        pd.to_numeric(dc_canonical_history_df["dc_vencidos_canonico"], errors="coerce")
        if not dc_canonical_history_df.empty and "dc_vencidos_canonico" in dc_canonical_history_df.columns
        else _prefer_nonzero_series(
            inadimplencia_total_prazo,
            inadimplencia_total_aging,
            inadimplencia_total_base,
        )
    )
    direitos_creditorios_total = (
        pd.to_numeric(dc_canonical_history_df["dc_total_canonico"], errors="coerce")
        if not dc_canonical_history_df.empty and "dc_total_canonico" in dc_canonical_history_df.columns
        else pd.concat([direitos_creditorios_vencidos, direitos_creditorios_futuro], axis=1).sum(axis=1, min_count=1)
    )
    direitos_creditorios = direitos_creditorios_total.copy()
    inadimplencia_total = direitos_creditorios_vencidos.copy()
    provisao_total = pd.concat(
        [
            _numeric_series_nullable(
                wide_lookup,
                competencias,
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_PROVIS_REDUC_RECUP",
            ),
            _numeric_series_nullable(
                wide_lookup,
                competencias,
                "DOC_ARQ/LISTA_INFORM/APLIC_ATIVO/DICRED/VL_DICRED_PROVIS_REDUC_RECUP",
            ),
        ],
        axis=1,
    ).sum(axis=1, min_count=1)
    pendencia_total = creditos_vencidos_pendentes_cessao

    df = pd.DataFrame(
        {
            "competencia": competencias,
            "competencia_dt": [_competencia_to_timestamp(competencia) for competencia in competencias],
            "direitos_creditorios_ativo": direitos_creditorios_total.values,
            "direitos_creditorios_vencidos": direitos_creditorios_vencidos.values,
            "direitos_creditorios_vencimento_total": direitos_creditorios_total.values,
            "direitos_creditorios": direitos_creditorios.values,
            "direitos_creditorios_fonte": (
                dc_canonical_history_df["dc_total_fonte_efetiva"].tolist()
                if not dc_canonical_history_df.empty and "dc_total_fonte_efetiva" in dc_canonical_history_df.columns
                else [pd.NA] * len(competencias)
            ),
            "inadimplencia_fonte": (
                dc_canonical_history_df["dc_vencidos_fonte_efetiva"].tolist()
                if not dc_canonical_history_df.empty and "dc_vencidos_fonte_efetiva" in dc_canonical_history_df.columns
                else [pd.NA] * len(competencias)
            ),
            "inadimplencia_total": inadimplencia_total.values,
            "parcelas_inadimplentes_total": parcelas_inadimplentes_total.values,
            "creditos_existentes_inadimplentes": creditos_existentes_inadimplentes.values,
            "creditos_vencidos_pendentes_cessao": creditos_vencidos_pendentes_cessao.values,
            "somatorio_inadimplentes_aux_validacao": somatorio_inadimplentes_aux_validacao.values,
            "provisao_total": provisao_total.values,
            "pendencia_total": pendencia_total.values,
        }
    )
    df["inadimplencia_pct"] = (
        df["inadimplencia_total"] / df["direitos_creditorios"]
    ).where(df["direitos_creditorios"] > 0).mul(100.0)
    df["provisao_pct_direitos"] = (
        df["provisao_total"] / df["direitos_creditorios"]
    ).where(df["direitos_creditorios"] > 0).mul(100.0)
    df["cobertura_pct"] = (
        df["provisao_total"] / df["inadimplencia_total"]
    ).where(df["inadimplencia_total"] > 0).mul(100.0)
    df["somatorio_inadimplentes_aux_validacao_pct_dcs"] = (
        df["somatorio_inadimplentes_aux_validacao"] / df["direitos_creditorios"]
    ).where(df["direitos_creditorios"] > 0).mul(100.0)
    return df


def _build_default_buckets_latest_df(
    *,
    wide_lookup: pd.DataFrame,
    latest_competencia: str,
    dc_canonical_history_df: pd.DataFrame,
) -> pd.DataFrame:
    bucket_specs = [
        ("Até 30 dias", ["VL_INAD_VENC_30"]),
        ("31 a 60 dias", ["VL_INAD_VENC_31_60"]),
        ("61 a 90 dias", ["VL_INAD_VENC_61_90"]),
        ("91 a 120 dias", ["VL_INAD_VENC_91_120"]),
        ("121 a 150 dias", ["VL_INAD_VENC_121_150"]),
        ("151 a 180 dias", ["VL_INAD_VENC_151_180"]),
        ("181 a 360 dias", ["VL_INAD_VENC_181_360"]),
        ("361 a 720 dias", ["VL_INAD_VENC_361_720"]),
        ("721 a 1080 dias", ["VL_INAD_VENC_721_1080"]),
        ("Acima de 1080 dias", ["VL_INAD_VENC_1080"]),
    ]
    rows = []
    for ordem, (faixa, suffixes) in enumerate(bucket_specs, start=1):
        paths = [
            f"DOC_ARQ/LISTA_INFORM/{base}/{suffix}"
            for suffix in suffixes
            for base in ["COMPMT_DICRED_AQUIS", "COMPMT_DICRED_SEM_AQUIS"]
        ]
        row = {
            "ordem": ordem,
            "faixa": faixa,
            **_sum_latest_paths_with_status(wide_lookup, latest_competencia, paths),
        }
        rows.append(row)
    frame = pd.DataFrame(rows)
    total = float(frame["valor"].sum()) if not frame.empty else 0.0
    frame["percentual"] = (frame["valor"] / total * 100.0) if total > 0 else pd.NA
    denominator = None
    if not dc_canonical_history_df.empty:
        latest_dc = dc_canonical_history_df[dc_canonical_history_df["competencia"] == latest_competencia].copy()
        if not latest_dc.empty:
            denominator = _to_numeric(latest_dc.iloc[-1].get("dc_total_canonico"))
    frame["percentual_direitos_creditorios"] = (
        frame["valor"] / denominator * 100.0 if denominator and denominator > 0 else pd.NA
    )
    return frame


def _build_default_buckets_history_df(
    *, wide_lookup: pd.DataFrame, competencias: list[str]
) -> pd.DataFrame:
    """Aging breakdown (VL_INAD_VENC_*) for all competências, long format."""
    bucket_specs = [
        ("Até 30 dias", ["VL_INAD_VENC_30"]),
        ("31 a 60 dias", ["VL_INAD_VENC_31_60"]),
        ("61 a 90 dias", ["VL_INAD_VENC_61_90"]),
        ("91 a 120 dias", ["VL_INAD_VENC_91_120"]),
        ("121 a 150 dias", ["VL_INAD_VENC_121_150"]),
        ("151 a 180 dias", ["VL_INAD_VENC_151_180"]),
        ("181 a 360 dias", ["VL_INAD_VENC_181_360"]),
        ("361 a 720 dias", ["VL_INAD_VENC_361_720"]),
        ("721 a 1080 dias", ["VL_INAD_VENC_721_1080"]),
        ("Acima de 1080 dias", ["VL_INAD_VENC_1080"]),
    ]
    rows = []
    for ordem, (faixa, suffixes) in enumerate(bucket_specs, start=1):
        paths = [
            f"DOC_ARQ/LISTA_INFORM/{base}/{suffix}"
            for suffix in suffixes
            for base in _MALHA_BASES
        ]
        history_info_df = _sum_paths_history_with_status(wide_lookup, competencias, paths)
        for _, history_row in history_info_df.iterrows():
            rows.append({
                "competencia": history_row["competencia"],
                "competencia_dt": history_row["competencia_dt"],
                "ordem": ordem,
                "faixa": faixa,
                "valor": float(history_row["valor"]),
                "valor_raw": history_row["valor_raw"],
                "source_status": history_row["source_status"],
                "source_paths": history_row["source_paths"],
                "present_source_paths": history_row["present_source_paths"],
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=[
            "competencia",
            "competencia_dt",
            "ordem",
            "faixa",
            "valor",
            "valor_raw",
            "source_status",
            "source_paths",
            "present_source_paths",
        ]
    )


def _build_holder_latest_df(
    *,
    wide_lookup: pd.DataFrame,
    listas_df: pd.DataFrame,
    latest_competencia: str,
) -> pd.DataFrame:
    competencias = [latest_competencia]
    rows: list[dict[str, object]] = []
    total_fields = [
        ("Resumo", "Total de cotistas", "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/NUM_COTISTAS/QT_TOTAL_COTISTAS"),
        ("Resumo", "Cotistas sênior", "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/NUM_COTISTAS/QT_TOTAL_COTISTAS_SENIOR"),
        ("Resumo", "Cotistas subordinada", "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/NUM_COTISTAS/QT_TOTAL_COTISTAS_SUBORD"),
    ]
    for grupo, categoria, tag_path in total_fields:
        rows.append(
            {
                "grupo": grupo,
                "categoria": categoria,
                "quantidade": float(_numeric_series(wide_lookup, competencias, tag_path).iloc[0]),
            }
        )

    rows.extend(
        _build_holder_series_rows(
            listas_df=listas_df,
            latest_competencia=latest_competencia,
            list_token="NUM_COTISTAS/CLASSE_SENIOR",
            grupo="Sênior",
            label_fields=("SERIE",),
        )
    )
    rows.extend(
        _build_holder_series_rows(
            listas_df=listas_df,
            latest_competencia=latest_competencia,
            list_token="NUM_COTISTAS/CLASSE_SUBORD",
            grupo="Subordinada",
            label_fields=("TIPO", "SERIE"),
        )
    )

    holder_desc_labels = {
        "QNT_PSS_FSC": "Pessoa física",
        "QNT_PSS_JRD": "Pessoa jurídica",
        "BNC_CMR": "Banco comercial",
        "CRT_DTR": "Corretora/distribuidora",
        "OTR_PSS_JRD": "Outras pessoas jurídicas",
        "INV_RSD": "Investidor residente",
        "ENT_ABR_PRD_CMP": "Entidade aberta de previdência",
        "ENT_FCH_PRD": "Entidade fechada de previdência",
        "RGM_PRP_PRD_SRV_PBL": "Regime próprio de previdência",
        "SCD_SGR_RSG": "Sociedade seguradora/resseguradora",
        "SCD_CPT_ARD_MER": "Sociedade de capitalização/arrendamento",
        "FND_INV_CTS": "Fundo de investimento em cotas",
        "FND_INV_IMB": "Fundo imobiliário",
        "OTR_FND_INV": "Outros fundos de investimento",
        "CLB_INV": "Clube de investimento",
        "CAMOTR": "Outros",
    }
    for xml_group, grupo in [
        ("CLS_SENIOR", "Perfil sênior"),
        ("CLS_SUBORDINADA", "Perfil subordinada"),
    ]:
        for tag, label in holder_desc_labels.items():
            valor = float(
                _numeric_series(
                    wide_lookup,
                    competencias,
                    f"DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/NUM_COTISTAS_DESC/{xml_group}/{tag}",
                ).iloc[0]
            )
            if valor > 0:
                rows.append({"grupo": grupo, "categoria": label, "quantidade": valor})

    frame = pd.DataFrame(rows, columns=["grupo", "categoria", "quantidade"])
    if frame.empty:
        return frame
    return frame[frame["quantidade"].fillna(0.0) > 0].reset_index(drop=True)


def _build_holder_series_rows(
    *,
    listas_df: pd.DataFrame,
    latest_competencia: str,
    list_token: str,
    grupo: str,
    label_fields: tuple[str, ...],
) -> list[dict[str, object]]:
    if listas_df.empty:
        return []
    subset = listas_df[
        (listas_df["competencia"] == latest_competencia)
        & (listas_df["list_group_path"].str.contains(list_token, regex=False, na=False))
    ].copy()
    if subset.empty:
        return []
    pivot = (
        subset.pivot_table(
            index=["list_group_path", "list_index"],
            columns="tag",
            values="valor_excel",
            aggfunc="first",
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    rows = []
    for _, row in pivot.iterrows():
        label = _resolve_class_label(
            row=row,
            class_kind="senior" if grupo == "Sênior" else "subordinada",
            default_label=grupo,
            label_fields=label_fields,
        )
        quantidade = _to_numeric(row.get("QT_COTISTAS")) or 0.0
        if quantidade > 0:
            rows.append({"grupo": grupo, "categoria": label, "quantidade": quantidade})
    return rows


def _build_rate_negotiation_latest_df(*, wide_lookup: pd.DataFrame, latest_competencia: str) -> pd.DataFrame:
    if "tag_path" not in wide_lookup.columns or latest_competencia not in wide_lookup.columns:
        return pd.DataFrame(columns=["grupo", "operacao", "taxa_min", "taxa_media", "taxa_max"])
    subset = wide_lookup[
        wide_lookup["tag_path"].astype(str).str.startswith("DOC_ARQ/LISTA_INFORM/TAXA_NEGOC_DICRED_MES/")
        & wide_lookup["tag"].isin(["TX_MIN", "TX_MEDIO", "TX_MAX", "TX_MAXIMO"])
    ].copy()
    if subset.empty:
        return pd.DataFrame(columns=["grupo", "operacao", "taxa_min", "taxa_media", "taxa_max"])
    subset["valor"] = pd.to_numeric(subset[latest_competencia], errors="coerce").fillna(0.0)
    subset["contexto"] = subset["sub_bloco"].map(_humanize_rate_context)
    pivot = (
        subset.pivot_table(index="contexto", columns="tag", values="valor", aggfunc="first")
        .reset_index()
        .rename_axis(None, axis=1)
    )
    if "TX_MAXIMO" in pivot.columns:
        if "TX_MAX" in pivot.columns:
            pivot["TX_MAX"] = pivot["TX_MAX"].where(pivot["TX_MAX"].abs() > 0, pivot["TX_MAXIMO"])
        else:
            pivot["TX_MAX"] = pivot["TX_MAXIMO"]
    for column in ["TX_MIN", "TX_MEDIO", "TX_MAX"]:
        if column not in pivot.columns:
            pivot[column] = 0.0
    pivot["grupo"] = pivot["contexto"].map(lambda value: str(value).split(" / ", 1)[0])
    pivot["operacao"] = pivot["contexto"].map(lambda value: str(value).split(" / ", 1)[1] if " / " in str(value) else str(value))
    output = pivot.rename(columns={"TX_MIN": "taxa_min", "TX_MEDIO": "taxa_media", "TX_MAX": "taxa_max"})
    output = output[["grupo", "operacao", "taxa_min", "taxa_media", "taxa_max"]].copy()
    positive = output[(output[["taxa_min", "taxa_media", "taxa_max"]].abs().sum(axis=1) > 0)].copy()
    return positive.reset_index(drop=True) if not positive.empty else output.reset_index(drop=True)


def _build_tracking_latest_df(
    *,
    summary: dict[str, float | str | None],
    asset_history_df: pd.DataFrame,
    wide_lookup: pd.DataFrame,
    latest_competencia: str,
) -> pd.DataFrame:
    asset_row = _latest_row(asset_history_df, latest_competencia)
    aquisicoes = _float_or_none(asset_row.get("aquisicoes")) or 0.0
    alienacoes = _float_or_none(asset_row.get("alienacoes")) or 0.0
    direitos_creditorios = _float_or_none(summary.get("inadimplencia_denominador"))
    if direitos_creditorios is None or direitos_creditorios <= 0:
        direitos_creditorios = _float_or_none(summary.get("direitos_creditorios"))
    provisao_total = _float_or_none(summary.get("provisao_total")) or 0.0
    inadimplencia_total = _float_or_none(summary.get("inadimplencia_total")) or 0.0
    pl_total = _float_or_none(summary.get("pl_total"))
    liquidez_imediata = _materialize_status_value(*_latest_path_value(
        wide_lookup,
        latest_competencia,
        "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ",
    ))
    liquidez_30 = _materialize_status_value(*_latest_path_value(
        wide_lookup,
        latest_competencia,
        "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/LIQUIDEZ/VL_ATIV_LIQDEZ_30",
    ))
    resgate_solicitado_info = _sum_latest_path_groups_with_status(
        wide_lookup,
        latest_competencia,
        [
            [
                "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/RESG_SOLIC/CLASSE_SENIOR/VL_PAGO",
                "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/RESG_SOLIC/CLASSE_SENIOR/VL_COTAS",
            ],
            [
                "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/RESG_SOLIC/CLASSE_SUBORD/VL_PAGO",
                "DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/RESG_SOLIC/CLASSE_SUBORD/VL_COTAS",
            ],
        ],
    )
    resgate_solicitado = _materialize_status_value(
        resgate_solicitado_info.get("valor_raw"),
        resgate_solicitado_info.get("source_status"),
    )
    rows = [
        {
            "indicador": "Alocação em direitos creditórios",
            "valor": summary.get("alocacao_pct"),
            "unidade": "%",
            "fonte": "APLIC_ATIVO/DICRED",
            "interpretação": "Participação dos direitos creditórios na carteira.",
            "estado_dado": "calculado" if summary.get("alocacao_pct") is not None else "nao_calculavel",
        },
        {
            "indicador": "Subordinação reportada (IME)",
            "valor": summary.get("subordinacao_pct"),
            "unidade": "%",
            "fonte": "OUTRAS_INFORM/DESC_SERIE_CLASSE",
            "interpretação": "PL mezzanino + PL subordinado residual divididos pelo PL total das cotas.",
            "estado_dado": "calculado" if summary.get("subordinacao_pct") is not None else "nao_calculavel",
        },
        {
            "indicador": "Inadimplência observada (IME) / DCs",
            "valor": summary.get("inadimplencia_pct"),
            "unidade": "%",
            "fonte": "APLIC_ATIVO + COMPMT_DICRED",
            "interpretação": "Saldos vencidos inadimplentes sobre direitos creditórios.",
            "estado_dado": "calculado" if summary.get("inadimplencia_pct") is not None else "nao_calculavel",
        },
        {
            "indicador": "Provisão / direitos creditórios",
            "valor": (provisao_total / direitos_creditorios * 100.0) if direitos_creditorios else None,
            "unidade": "%",
            "fonte": "APLIC_ATIVO",
            "interpretação": "Provisão reportada sobre direitos creditórios.",
            "estado_dado": "calculado" if direitos_creditorios else "nao_calculavel",
        },
        {
            "indicador": "Provisão / vencidos totais",
            "valor": (provisao_total / inadimplencia_total * 100.0) if inadimplencia_total else None,
            "unidade": "%",
            "fonte": "APLIC_ATIVO",
            "interpretação": "Cobertura contábil dos saldos inadimplentes.",
            "estado_dado": "calculado" if inadimplencia_total else "nao_aplicavel_sem_inadimplencia",
        },
        {
            "indicador": "Aquisições / direitos creditórios",
            "valor": (aquisicoes / direitos_creditorios * 100.0) if direitos_creditorios else None,
            "unidade": "%",
            "fonte": "NEGOC_DICRED_MES",
            "interpretação": "Originação/aquisição no mês sobre a carteira de direitos creditórios.",
            "estado_dado": "calculado" if direitos_creditorios else "nao_calculavel",
        },
        {
            "indicador": "Alienações / direitos creditórios",
            "valor": (alienacoes / direitos_creditorios * 100.0) if direitos_creditorios else None,
            "unidade": "%",
            "fonte": "NEGOC_DICRED_MES",
            "interpretação": "Alienações no mês sobre a carteira de direitos creditórios.",
            "estado_dado": "calculado" if direitos_creditorios else "nao_calculavel",
        },
        {
            "indicador": "Liquidez imediata / PL total",
            "valor": (liquidez_imediata / pl_total * 100.0) if pl_total and liquidez_imediata is not None else None,
            "unidade": "%",
            "fonte": "OUTRAS_INFORM/LIQUIDEZ",
            "interpretação": "Ativos com liquidez imediata sobre o PL reportado.",
            "estado_dado": (
                "calculado"
                if pl_total and liquidez_imediata is not None
                else ("nao_disponivel_na_fonte" if liquidez_imediata is None else "nao_calculavel_sem_pl")
            ),
        },
        {
            "indicador": "Liquidez até 30 dias / PL total",
            "valor": (liquidez_30 / pl_total * 100.0) if pl_total and liquidez_30 is not None else None,
            "unidade": "%",
            "fonte": "OUTRAS_INFORM/LIQUIDEZ",
            "interpretação": "Ativos com liquidez em até 30 dias sobre o PL reportado.",
            "estado_dado": (
                "calculado"
                if pl_total and liquidez_30 is not None
                else ("nao_disponivel_na_fonte" if liquidez_30 is None else "nao_calculavel_sem_pl")
            ),
        },
        {
            "indicador": "Resgate solicitado / PL total",
            "valor": (resgate_solicitado / pl_total * 100.0) if pl_total and resgate_solicitado is not None else None,
            "unidade": "%",
            "fonte": "CAPTA_RESGA_AMORTI/RESG_SOLIC",
            "interpretação": "Pedidos de resgate ainda a pagar em relação ao PL reportado.",
            "estado_dado": (
                "calculado"
                if pl_total and resgate_solicitado is not None
                else ("nao_disponivel_na_fonte" if resgate_solicitado is None else "nao_calculavel_sem_pl")
            ),
        },
    ]
    return pd.DataFrame(rows)


def _build_executive_memory_df(
    *,
    latest_competencia: str,
    summary: dict[str, float | str | None],
    dc_canonical_history_df: pd.DataFrame,
    default_buckets_latest_df: pd.DataFrame,
    risk_metrics_df: pd.DataFrame,
) -> pd.DataFrame:
    latest_dc_row = _latest_row(dc_canonical_history_df, latest_competencia)
    aging_percent_col = (
        "percentual_inadimplencia"
        if "percentual_inadimplencia" in default_buckets_latest_df.columns
        else "percentual"
    )
    dc_total_source = latest_dc_row.get("dc_total_fonte_efetiva")
    dc_vencidos_source = latest_dc_row.get("dc_vencidos_fonte_efetiva")
    rows = [
        {
            "tipo_variavel": "Monetária",
            "bloco_executivo": "Topo da página",
            "componente": "Ativo total",
            "variavel_final": "summary['ativos_totais']",
            "numerador": "VL_SOM_APLIC_ATIVO",
            "denominador": "Não se aplica",
            "fonte_cvm": "APLIC_ATIVO/VL_SOM_APLIC_ATIVO",
            "fonte_efetiva": "APLIC_ATIVO/VL_SOM_APLIC_ATIVO",
            "formula": "Leitura direta do ativo total reportado",
            "observacao": "Card monetário de contexto; não entra nos indicadores relativos de crédito.",
        },
        {
            "tipo_variavel": "Base canônica",
            "bloco_executivo": "Base comum",
            "componente": "Direitos creditórios totais",
            "variavel_final": "summary['direitos_creditorios']",
            "numerador": "Estoque total de direitos creditórios",
            "denominador": "Não se aplica",
            "fonte_cvm": _canonical_dc_total_path_labels(),
            "fonte_efetiva": dc_total_source,
            "formula": "Escolha canônica em cascata: malha de vencimento -> estoque granular -> agregado item 3",
            "observacao": "Todas as métricas percentuais sobre DCs passam a usar esta mesma base.",
        },
        {
            "tipo_variavel": "Monetária",
            "bloco_executivo": "Topo da página / Estrutura",
            "componente": "PL total",
            "variavel_final": "summary['pl_total']",
            "numerador": "PATRLIQ/VL_PATRIM_LIQ quando disponível; classes ficam reconciliadas à parte",
            "denominador": "Não se aplica",
            "fonte_cvm": "PATRLIQ/VL_PATRIM_LIQ + OUTRAS_INFORM/DESC_SERIE_CLASSE",
            "fonte_efetiva": "PL oficial; qt_cotas * valor_cota apenas para decomposição por classe",
            "formula": "PL oficial; se ausente, Σ PL das classes reportadas com warning implícito",
            "observacao": "Quando PL oficial diverge da soma das classes, a subordinação fica não calculável e o PL não reconciliado aparece separado.",
        },
        {
            "tipo_variavel": "Monetária",
            "bloco_executivo": "Topo da página / Estrutura",
            "componente": "PL subordinado",
            "variavel_final": "summary['pl_subordinada']",
            "numerador": "Σ(PL mezzanino + PL subordinado residual)",
            "denominador": "Não se aplica",
            "fonte_cvm": "OUTRAS_INFORM/DESC_SERIE_CLASSE",
            "fonte_efetiva": "qt_cotas * valor_cota por macroclasse",
            "formula": "pl_mezzanino + pl_subordinada_strict",
            "observacao": "Insumo direto do índice de subordinação; mezanino fica segregado nas tabelas e gráficos de PL.",
        },
        {
            "tipo_variavel": "Monetária",
            "bloco_executivo": "Topo da página / Estrutura",
            "componente": "PL mezzanino",
            "variavel_final": "summary['pl_mezzanino']",
            "numerador": "Σ(qt_cotas_mezzanino × valor_cota_mezzanino)",
            "denominador": "Não se aplica",
            "fonte_cvm": "OUTRAS_INFORM/DESC_SERIE_CLASSE",
            "fonte_efetiva": "qt_cotas * valor_cota",
            "formula": "Σ PL das classes identificadas como mezzanino",
            "observacao": "Macroclasse econômica exibida separadamente em qualquer visão do painel.",
        },
        {
            "tipo_variavel": "Monetária",
            "bloco_executivo": "Topo da página",
            "componente": "Liquidez imediata e liquidez até 30 dias",
            "variavel_final": "summary['liquidez_imediata'] + summary['liquidez_30']",
            "numerador": "VL_ATIV_LIQDEZ e VL_ATIV_LIQDEZ_30",
            "denominador": "Não se aplica",
            "fonte_cvm": "OUTRAS_INFORM/LIQUIDEZ",
            "fonte_efetiva": "Leitura direta por tag de liquidez",
            "formula": "Leitura direta dos campos de liquidez reportados",
            "observacao": "Cards de contexto. Não devem ser confundidos com caixa disponível nem com cronograma contratual completo.",
        },
        {
            "tipo_variavel": "Percentual",
            "bloco_executivo": "Radar de risco / Crédito",
            "componente": "Inadimplência observada (IME) / DCs",
            "variavel_final": "summary['inadimplencia_pct']",
            "numerador": "dc_vencidos_canonico",
            "denominador": "dc_total_canonico",
            "fonte_cvm": "VL_SOM_INAD_VENC com fallback para VL_INAD_VENC_*; denominador canônico de DC total.",
            "fonte_efetiva": f"numerador={dc_vencidos_source} | denominador={dc_total_source}",
            "formula": "dc_vencidos_canonico / dc_total_canonico * 100",
            "observacao": "Mesma base usada no card de inadimplência e nos gráficos relativos de crédito.",
        },
        {
            "tipo_variavel": "Percentual",
            "bloco_executivo": "Crédito",
            "componente": "Inadimplência + provisão (% dos DCs)",
            "variavel_final": "default_history_df.[inadimplencia_pct, provisao_total/dc_total_canonico]",
            "numerador": "inadimplencia_total e provisao_total",
            "denominador": "dc_total_canonico",
            "fonte_cvm": "Inadimplência: COMPMT_DICRED/aging. Provisão: APLIC_ATIVO. Denominador: base canônica.",
            "fonte_efetiva": f"inadimplência={dc_vencidos_source} | provisão=APLIC_ATIVO | denominador={dc_total_source}",
            "formula": "inadimplencia_total / dc_total_canonico; provisao_total / dc_total_canonico",
            "observacao": "Barras agrupadas no eixo esquerdo. Ambas usam a mesma base canônica de DC total.",
        },
        {
            "tipo_variavel": "Percentual",
            "bloco_executivo": "Crédito",
            "componente": "Cobertura de provisão / vencidos totais (linha RHS)",
            "variavel_final": "provisao_total / direitos_creditorios_vencidos",
            "numerador": "provisao_total",
            "denominador": "direitos_creditorios_vencidos",
            "fonte_cvm": "APLIC_ATIVO + base canônica de vencidos",
            "fonte_efetiva": f"provisão=APLIC_ATIVO | vencidos={dc_vencidos_source}",
            "formula": "provisao_total / direitos_creditorios_vencidos * 100",
            "observacao": "Linha grossa no eixo direito com referência pontilhada em 100%. Não usa DC total.",
        },
        {
            "tipo_variavel": "Bucket / distribuição",
            "bloco_executivo": "Crédito",
            "componente": "Aging da inadimplência",
            "variavel_final": f"default_buckets_latest_df.valor + {aging_percent_col}",
            "numerador": "Cada bucket VL_INAD_VENC_* por faixa",
            "denominador": "inadimplencia_total_aging",
            "fonte_cvm": "COMPMT_DICRED_AQUIS + COMPMT_DICRED_SEM_AQUIS",
            "fonte_efetiva": "buckets=COMPMT_DICRED_* | denominador=Σ buckets vencidos por competência",
            "formula": "bucket / inadimplencia_total_aging * 100",
            "observacao": "Gráfico não cumulativo por faixa do estoque vencido. O % dos DCs permanece disponível na base auditável.",
        },
        {
            "tipo_variavel": "Bucket / distribuição",
            "bloco_executivo": "Crédito",
            "componente": "Inadimplência Over",
            "variavel_final": "default_over_history_df.percentual",
            "numerador": "Soma cumulativa dos buckets vencidos acima do threshold",
            "denominador": "dc_total_canonico",
            "fonte_cvm": "Buckets VL_INAD_VENC_30 até VL_INAD_VENC_1080",
            "fonte_efetiva": f"buckets=COMPMT_DICRED_* | denominador={dc_total_source}",
            "formula": "Over X = Σ(buckets vencidos acima de X) / dc_total_canonico * 100",
            "observacao": "Inclui Over 1 como soma de todos os atrasos a partir de 1 dia; os demais cortes permanecem cumulativos.",
        },
        {
            "tipo_variavel": "Percentual",
            "bloco_executivo": "Estrutura",
            "componente": "Subordinação reportada (IME) — linha",
            "variavel_final": "summary['subordinacao_pct']",
            "numerador": "pl_mezzanino + pl_subordinada_strict",
            "denominador": "pl_total",
            "fonte_cvm": "OUTRAS_INFORM/DESC_SERIE_CLASSE",
            "fonte_efetiva": "qt_cotas * valor_cota por macroclasse",
            "formula": "(pl_mezzanino + pl_subordinada_strict) / pl_total * 100",
            "observacao": "Card e gráfico usam exatamente a mesma série histórica; mezzanino permanece visível separadamente no PL.",
        },
        {
            "tipo_variavel": "Classe / PL",
            "bloco_executivo": "Estrutura",
            "componente": "PL por tipo de cota e tabela da última competência",
            "variavel_final": "quota_pl_history_df",
            "numerador": "qt_cotas * valor_cota por classe/série",
            "denominador": "pl_total quando a visualização é percentual",
            "fonte_cvm": "OUTRAS_INFORM/DESC_SERIE_CLASSE",
            "fonte_efetiva": "qt_cotas * valor_cota com macroclasse derivada",
            "formula": "pl_macroclasse; share = pl_macroclasse / Σ pl_macroclasse",
            "observacao": "O gráfico principal usa macroclasses econômicas (Sênior, Mezzanino, Subordinada) e a tabela preserva o detalhe da classe.",
        },
        {
            "tipo_variavel": "Fluxo / evento",
            "bloco_executivo": "Eventos de cotas",
            "componente": "Resumo de emissões, resgates e amortizações",
            "variavel_final": "event_summary_latest_df",
            "numerador": "Σ eventos por tipo",
            "denominador": "pl_total para a coluna % do PL",
            "fonte_cvm": "OUTRAS_INFORM/CAPTA_RESGA_AMORTI",
            "fonte_efetiva": "VL_TOTAL; em RESG_SOLIC aceita VL_PAGO e VL_COTAS",
            "formula": "valor_total_assinado / pl_total * 100",
            "observacao": "Mantém o sinal econômico separado do valor bruto.",
        },
        {
            "tipo_variavel": "Bucket / distribuição",
            "bloco_executivo": "Vencimento",
            "componente": "Prazo de vencimento dos direitos creditórios",
            "variavel_final": "maturity_latest_df",
            "numerador": "Buckets VL_PRAZO_VENC_* + VL_SOM_INAD_VENC",
            "denominador": "Não se aplica",
            "fonte_cvm": "COMPMT_DICRED_AQUIS + COMPMT_DICRED_SEM_AQUIS",
            "fonte_efetiva": "malha_vencimento",
            "formula": "Soma por bucket de vencimento",
            "observacao": "É a mesma malha usada como fonte primária do DC total canônico.",
        },
        {
            "tipo_variavel": "Prazo / duration",
            "bloco_executivo": "Vencimento",
            "componente": "Prazo médio proxy dos recebíveis (IME)",
            "variavel_final": "duration_history_df.duration_days",
            "numerador": "Σ(saldo_bucket * prazo_proxy)",
            "denominador": "Σ(saldo_bucket)",
            "fonte_cvm": "maturity_history_df",
            "fonte_efetiva": "malha_vencimento",
            "formula": "Σ(saldo_bucket × prazo_proxy) / Σ(saldo_bucket)",
            "observacao": "Proxies de prazo ficam documentados no gráfico e na tabela técnica.",
        },
        {
            "tipo_variavel": "Metadado / referência",
            "bloco_executivo": "Cabeçalho / contexto",
            "componente": "Nome do fundo, competência, janela, cotistas e participantes",
            "variavel_final": "fund_info",
            "numerador": "Metadados do cabeçalho do informe + cadastro CVM complementar",
            "denominador": "Não se aplica",
            "fonte_cvm": "CAB_INFORM + cadastro CVM complementar para participantes",
            "fonte_efetiva": "fund_info",
            "formula": "Leitura direta dos metadados mais recentes",
            "observacao": "Informação de referência; não participa dos cálculos financeiros.",
        },
    ]
    if not risk_metrics_df.empty:
        metric_specs = {
            "inadimplencia_pct": ("dc_vencidos_canonico", "dc_total_canonico", f"numerador={dc_vencidos_source} | denominador={dc_total_source}"),
            "provisao_pct_direitos": ("provisao_total", "dc_total_canonico", f"provisão=APLIC_ATIVO | denominador={dc_total_source}"),
            "provisao_pct_inadimplencia": ("provisao_total", "dc_vencidos_canonico", f"provisão=APLIC_ATIVO | denominador={dc_vencidos_source}"),
            "concentracao_segmento_proxy": ("Maior saldo setorial reportado", "Σ saldos setoriais reportados", "CART_SEGMT"),
            "subordinacao_pct": ("pl_mezzanino + pl_subordinada_strict", "pl_total", "qt_cotas * valor_cota"),
            "pl_subordinada": ("Σ(PL mezzanino + PL subordinado residual)", "Não se aplica", "qt_cotas * valor_cota"),
        }
        for _, metric_row in risk_metrics_df.iterrows():
            metric_id = str(metric_row.get("metric_id") or "")
            numerador, denominador, fonte_efetiva = metric_specs.get(
                metric_id,
                (
                    metric_row.get("transformation"),
                    "Não se aplica",
                    metric_row.get("source_data"),
                ),
            )
            rows.append(
                {
                    "tipo_variavel": "Métrica de risco",
                    "bloco_executivo": metric_row.get("risk_block"),
                    "componente": metric_row.get("label"),
                    "variavel_final": metric_row.get("final_variable"),
                    "numerador": numerador,
                    "denominador": denominador,
                    "fonte_cvm": metric_row.get("source_data"),
                    "fonte_efetiva": fonte_efetiva,
                    "formula": metric_row.get("formula"),
                    "observacao": metric_row.get("limitation"),
                }
            )
    return pd.DataFrame(rows)


def _build_consistency_audit_df(
    *,
    latest_competencia: str,
    summary: dict[str, float | str | None],
    current_dashboard_inventory_df: pd.DataFrame,
    dc_canonical_history_df: pd.DataFrame,
    default_history_df: pd.DataFrame,
    default_aging_history_df: pd.DataFrame,
    default_over_history_df: pd.DataFrame,
    risk_metrics_df: pd.DataFrame,
) -> pd.DataFrame:
    latest_dc_row = _latest_row(dc_canonical_history_df, latest_competencia) if latest_competencia else pd.Series(dtype="object")
    dc_total_source = latest_dc_row.get("dc_total_fonte_efetiva")
    dc_vencidos_source = latest_dc_row.get("dc_vencidos_fonte_efetiva")
    coverage_uses_vencidos = bool(
        not default_history_df.empty
        and "direitos_creditorios_vencidos" in default_history_df.columns
        and "provisao_total" in default_history_df.columns
    )
    aging_uses_inad_total = bool(
        not default_aging_history_df.empty
        and "percentual_inadimplencia" in default_aging_history_df.columns
    )
    over_is_cumulative = bool(
        not default_over_history_df.empty
        and set(default_over_history_df.get("serie", pd.Series(dtype="object")).dropna().tolist())
        <= {"Over 1", "Over 30", "Over 60", "Over 90", "Over 180", "Over 360"}
    )
    subordination_metric_exists = bool(
        not risk_metrics_df.empty
        and "subordinacao_pct" in risk_metrics_df.get("metric_id", pd.Series(dtype="object")).tolist()
    )
    inventory_labels = set(current_dashboard_inventory_df.get("nome_exibido", pd.Series(dtype="object")).tolist())
    rows = [
        {
            "tema": "Direitos creditórios totais",
            "status": "Alinhado" if dc_total_source else "Sem base",
            "checagem": "Cards, métricas de crédito, aging e over",
            "resultado": f"Base canônica única = {dc_total_source or 'N/D'}",
            "acao": "Todos os percentuais sobre DCs permanecem ancorados em dc_total_canonico.",
        },
        {
            "tema": "Aging x Over",
            "status": "Alinhado" if aging_uses_inad_total and over_is_cumulative else "Revisar",
            "checagem": "Separação semântica entre distribuição e curva cumulativa",
            "resultado": (
                "Aging permanece não cumulativo por faixa do estoque vencido; Inadimplência Over usa somatório cumulativo sobre DC total."
                if aging_uses_inad_total and over_is_cumulative
                else "Há indício de mistura entre bucket de aging e curva Over."
            ),
            "acao": "Manter aging como distribuição por faixa e Over como soma cumulativa com legenda explícita.",
        },
        {
            "tema": "Cobertura de provisão",
            "status": "Alinhado" if coverage_uses_vencidos else "Revisar",
            "checagem": "Denominador da linha de cobertura",
            "resultado": (
                f"Cobertura usa vencidos canônicos ({dc_vencidos_source or 'N/D'}) no eixo direito, sem reaproveitar DC total."
                if coverage_uses_vencidos
                else "Cobertura não está claramente amarrada ao estoque vencido."
            ),
            "acao": "Segregar visualmente a cobertura no eixo RHS com referência pontilhada em 100%.",
        },
        {
            "tema": "Subordinação",
            "status": "Alinhado" if subordination_metric_exists else "Revisar",
            "checagem": "Consistência entre card, gráfico e tabela estrutural",
            "resultado": "Card, métrica e gráfico usam a mesma série pl_subordinada / pl_total.",
            "acao": "Preservar a mesma série histórica em todos os outputs estruturais.",
        },
        {
            "tema": "Vencimento x Duration",
            "status": "Alinhado",
            "checagem": "Mesma malha regulatória para buckets e duration",
            "resultado": "O gráfico de vencimento e a duration estimada nascem da mesma malha COMPMT_DICRED_*.",
            "acao": "Documentar proxies de prazo e evitar trocar a base por agregados de ativo.",
        },
        {
            "tema": "Inventário da aba executiva",
            "status": "Alinhado" if "Inadimplência, provisão e cobertura" in inventory_labels else "Revisar",
            "checagem": "Cobertura dos outputs ativos da aba",
            "resultado": (
                "O inventário auditável foi atualizado para a aba executiva atual."
                if "Inadimplência, provisão e cobertura" in inventory_labels
                else "O inventário ainda não reflete integralmente os outputs ativos da aba."
            ),
            "acao": "Manter o inventário sincronizado com a UI efetivamente renderizada.",
        },
    ]
    return pd.DataFrame(rows)


def _build_quota_pl_history(
    *,
    wide_lookup: pd.DataFrame,
    listas_df: pd.DataFrame,
    competencias: list[str],
) -> pd.DataFrame:
    frames = [
        _build_scalar_class_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="senior",
            default_label="Senior",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SENIOR/",
            label_fields=("SERIE",),
            value_fields=("QT_COTAS", "VL_COTAS"),
        ),
        _build_scalar_class_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="subordinada",
            default_label="Subordinada",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SUBORD/",
            label_fields=("TIPO", "SERIE"),
            value_fields=("QT_COTAS", "VL_COTAS"),
        ),
        _build_list_class_frame(
            listas_df=listas_df,
            class_kind="senior",
            default_label="Senior",
            list_token="DESC_SERIE_CLASSE_SENIOR",
            label_fields=("SERIE",),
            value_fields=("QT_COTAS", "VL_COTAS"),
        ),
        _build_list_class_frame(
            listas_df=listas_df,
            class_kind="subordinada",
            default_label="Subordinada",
            list_token="DESC_SERIE_CLASSE_SUBORD",
            label_fields=("TIPO", "SERIE"),
            value_fields=("QT_COTAS", "VL_COTAS"),
        ),
    ]
    base_df = _finalize_class_frame(
        frames=frames,
        competencias=competencias,
        numeric_fields=("QT_COTAS", "VL_COTAS"),
    )
    if base_df.empty:
        return pd.DataFrame(
            columns=[
                "competencia",
                "competencia_dt",
                "class_kind",
                "class_key",
                "class_label",
                "label",
                "qt_cotas",
                "vl_cota",
                "pl",
            ]
        )
    base_df = base_df.rename(columns={"QT_COTAS": "qt_cotas", "VL_COTAS": "vl_cota"})
    base_df["pl"] = base_df["qt_cotas"].fillna(0.0) * base_df["vl_cota"].fillna(0.0)
    base_df["pl_reconciliacao_role"] = "classe_reportada"
    base_df = _append_unreconciled_pl_rows(
        quota_pl_history_df=base_df,
        wide_lookup=wide_lookup,
        competencias=competencias,
    )
    totals = base_df.groupby("competencia", dropna=False)["pl"].transform("sum")
    base_df["pl_share_pct"] = (base_df["pl"] / totals).where(totals > 0).mul(100.0)
    return base_df


def _build_subordination_history(
    quota_pl_history_df: pd.DataFrame,
    *,
    wide_lookup: pd.DataFrame,
    competencias: list[str],
) -> pd.DataFrame:
    if quota_pl_history_df.empty:
        return pd.DataFrame(
            columns=[
                "competencia",
                "competencia_dt",
                "pl_total",
                "pl_total_oficial",
                "pl_total_classes",
                "pl_nao_reconciliado",
                "pl_reconciliacao_delta",
                "pl_reconciliacao_delta_pct",
                "pl_reconciliacao_warning",
                "subordinacao_status",
                "pl_senior",
                "pl_mezzanino",
                "pl_subordinada_strict",
                "pl_subordinada",
                "subordinacao_pct",
            ]
        )

    reported_df = quota_pl_history_df[
        quota_pl_history_df.get("pl_reconciliacao_role", pd.Series("classe_reportada", index=quota_pl_history_df.index))
        != "pl_nao_reconciliado"
    ].copy()
    grouped = (
        reported_df.groupby(["competencia", "competencia_dt", "class_macro"], dropna=False)["pl"]
        .sum()
        .unstack(fill_value=0.0)
        .reset_index()
    )
    grouped["pl_senior"] = grouped.get("senior", 0.0)
    grouped["pl_mezzanino"] = grouped.get("mezzanino", 0.0)
    grouped["pl_subordinada_strict"] = grouped.get("subordinada", 0.0)
    # A métrica canônica de subordinação preserva a lógica econômica de
    # proteção abaixo do sênior: mezzanino + subordinadas residuais.
    grouped["pl_subordinada"] = grouped["pl_mezzanino"] + grouped["pl_subordinada_strict"]
    grouped["pl_total_classes"] = grouped["pl_senior"] + grouped["pl_subordinada"]
    official_pl = _official_pl_series(wide_lookup=wide_lookup, competencias=competencias)
    grouped["pl_total_oficial"] = grouped["competencia"].map(official_pl)
    grouped["pl_total"] = grouped["pl_total_oficial"].where(
        pd.to_numeric(grouped["pl_total_oficial"], errors="coerce").gt(0),
        grouped["pl_total_classes"],
    )
    grouped["pl_reconciliacao_delta"] = grouped["pl_total"] - grouped["pl_total_classes"]
    grouped["pl_nao_reconciliado"] = grouped["pl_reconciliacao_delta"].where(
        pd.to_numeric(grouped["pl_reconciliacao_delta"], errors="coerce").gt(0),
        0.0,
    )
    grouped["pl_reconciliacao_delta_pct"] = (
        grouped["pl_reconciliacao_delta"].abs() / grouped["pl_total"]
    ).where(grouped["pl_total"] > 0).mul(100.0)
    grouped["pl_reconciliacao_warning"] = (
        pd.to_numeric(grouped["pl_reconciliacao_delta_pct"], errors="coerce")
        > PL_RECONCILIATION_WARNING_PCT
    ).fillna(False)
    grouped["subordinacao_pct"] = (
        grouped["pl_subordinada"] / grouped["pl_total"]
    ).where(grouped["pl_total"] > 0).mul(100.0)
    grouped.loc[grouped["pl_reconciliacao_warning"], "subordinacao_pct"] = pd.NA
    grouped["subordinacao_status"] = grouped["pl_reconciliacao_warning"].map(
        lambda warning: (
            "nao_calculavel_pl_oficial_diverge_classes"
            if warning
            else "calculado_com_classes_reportadas"
        )
    )
    return grouped[
        [
            "competencia",
            "competencia_dt",
            "pl_total",
            "pl_total_oficial",
            "pl_total_classes",
            "pl_nao_reconciliado",
            "pl_reconciliacao_delta",
            "pl_reconciliacao_delta_pct",
            "pl_reconciliacao_warning",
            "subordinacao_status",
            "pl_senior",
            "pl_mezzanino",
            "pl_subordinada_strict",
            "pl_subordinada",
            "subordinacao_pct",
        ]
    ]


def _official_pl_series(*, wide_lookup: pd.DataFrame, competencias: list[str]) -> dict[str, float | None]:
    if OFFICIAL_PL_PATH not in wide_lookup.index:
        return {competencia: None for competencia in competencias}
    row = wide_lookup.loc[OFFICIAL_PL_PATH]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    return {competencia: _float_or_none(row.get(competencia)) for competencia in competencias}


def _append_unreconciled_pl_rows(
    *,
    quota_pl_history_df: pd.DataFrame,
    wide_lookup: pd.DataFrame,
    competencias: list[str],
) -> pd.DataFrame:
    if quota_pl_history_df.empty:
        return quota_pl_history_df
    official_pl = _official_pl_series(wide_lookup=wide_lookup, competencias=competencias)
    class_totals = quota_pl_history_df.groupby("competencia", dropna=False)["pl"].sum().to_dict()
    rows: list[dict[str, object]] = []
    for competencia in competencias:
        official_value = _float_or_none(official_pl.get(competencia))
        class_total = _float_or_none(class_totals.get(competencia)) or 0.0
        if official_value is None or official_value <= 0:
            continue
        delta = official_value - class_total
        delta_pct = abs(delta) / official_value * 100.0
        if delta <= 0 or delta_pct <= PL_RECONCILIATION_WARNING_PCT:
            continue
        rows.append(
            {
                "competencia": competencia,
                "competencia_dt": _competencia_to_timestamp(competencia),
                "class_kind": "nao_reconciliado",
                "class_key": "nao_reconciliado",
                "class_label": "PL não reconciliado",
                "label": "PL não reconciliado",
                "legacy_label": "PL não reconciliado",
                "identity_confidence": "high",
                "class_macro": "nao_reconciliado",
                "class_macro_label": "PL não reconciliado",
                "qt_cotas": pd.NA,
                "vl_cota": pd.NA,
                "pl": delta,
                "pl_reconciliacao_role": "pl_nao_reconciliado",
                "pl_reconciliacao_fonte": OFFICIAL_PL_PATH,
                "pl_reconciliacao_observacao": (
                    "Fallback explícito: PL oficial preservado como total; diferença não alocada "
                    "a cotas porque QT_COTAS × VL_COTAS não reconcilia com o PL oficial."
                ),
            }
        )
    if not rows:
        return quota_pl_history_df
    return pd.concat([quota_pl_history_df, pd.DataFrame(rows)], ignore_index=True, sort=False)


def _build_return_history(
    *,
    wide_lookup: pd.DataFrame,
    listas_df: pd.DataFrame,
    competencias: list[str],
) -> pd.DataFrame:
    frames = [
        _build_scalar_class_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="senior",
            default_label="Senior",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/RENT_MES/RENT_CLASSE_SENIOR/",
            label_fields=("SERIE",),
            value_fields=("PR_APURADA",),
        ),
        _build_scalar_class_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="subordinada",
            default_label="Subordinada",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/RENT_MES/RENT_CLASSE_SUBORD/",
            label_fields=("TIPO", "SERIE"),
            value_fields=("PR_APURADA",),
        ),
        _build_list_class_frame(
            listas_df=listas_df,
            class_kind="senior",
            default_label="Senior",
            list_token="RENT_CLASSE_SENIOR",
            label_fields=("SERIE",),
            value_fields=("PR_APURADA",),
        ),
        _build_list_class_frame(
            listas_df=listas_df,
            class_kind="subordinada",
            default_label="Subordinada",
            list_token="RENT_CLASSE_SUBORD",
            label_fields=("TIPO", "SERIE"),
            value_fields=("PR_APURADA",),
        ),
    ]
    base_df = _finalize_class_frame(
        frames=frames,
        competencias=competencias,
        numeric_fields=("PR_APURADA",),
    )
    if base_df.empty:
        return pd.DataFrame(
            columns=[
                "competencia",
                "competencia_dt",
                "class_kind",
                "class_key",
                "class_label",
                "label",
                "retorno_mensal_pct",
                "return_source",
            ]
        )
    base_df = base_df.rename(columns={"PR_APURADA": "retorno_mensal_pct"})
    base_df["return_source"] = "RENT_MES.PR_APURADA"
    return base_df


def _build_return_summary(return_history_df: pd.DataFrame, latest_competencia: str) -> pd.DataFrame:
    if return_history_df.empty:
        return pd.DataFrame(
            columns=[
                "class_kind",
                "class_key",
                "class_label",
                "label",
                "retorno_mes_pct",
                "retorno_ano_pct",
                "retorno_12m_pct",
            ]
        )

    latest_year = _competencia_sort_key(latest_competencia)[0]
    rows: list[dict[str, object]] = []
    for (class_kind, class_key, class_label), group in return_history_df.groupby(
        ["class_kind", "class_key", "class_label"],
        dropna=False,
    ):
        ordered = group.sort_values("competencia_dt").copy()
        monthly = pd.to_numeric(ordered["retorno_mensal_pct"], errors="coerce")
        if monthly.dropna().empty:
            continue
        latest_return = float(monthly.dropna().iloc[-1])
        year_mask = ordered["competencia_dt"].dt.year == latest_year
        rows.append(
            {
                "class_kind": class_kind,
                "class_key": class_key,
                "class_label": class_label,
                "label": class_label,
                "retorno_mes_pct": latest_return,
                "retorno_ano_pct": _compound_percent(monthly[year_mask]),
                "retorno_12m_pct": _compound_percent(monthly.tail(12)),
            }
        )
    return sort_class_display_frame(pd.DataFrame(rows), label_column="class_label")


def _build_performance_vs_benchmark_latest_df(
    *,
    wide_lookup: pd.DataFrame,
    listas_df: pd.DataFrame,
    competencias: list[str],
    latest_competencia: str,
) -> pd.DataFrame:
    frames = [
        _build_scalar_class_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="senior",
            default_label="Senior",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESEMP/CLASSE_SENIOR/",
            label_fields=("SERIE",),
            value_fields=("DESEMP_ESP", "DESEMP_REAL"),
        ),
        _build_scalar_class_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="subordinada",
            default_label="Subordinada",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/DESEMP/CLASSE_SUBORD/",
            label_fields=("TIPO", "SERIE"),
            value_fields=("DESEMP_ESP", "DESEMP_REAL"),
        ),
        _build_list_class_frame(
            listas_df=listas_df,
            class_kind="senior",
            default_label="Senior",
            list_token="DESEMP/CLASSE_SENIOR",
            label_fields=("SERIE",),
            value_fields=("DESEMP_ESP", "DESEMP_REAL"),
        ),
        _build_list_class_frame(
            listas_df=listas_df,
            class_kind="subordinada",
            default_label="Subordinada",
            list_token="DESEMP/CLASSE_SUBORD",
            label_fields=("TIPO", "SERIE"),
            value_fields=("DESEMP_ESP", "DESEMP_REAL"),
        ),
    ]
    base_df = _finalize_class_frame(
        frames=frames,
        competencias=competencias,
        numeric_fields=("DESEMP_ESP", "DESEMP_REAL"),
    )
    if base_df.empty:
        return pd.DataFrame(
            columns=[
                "competencia",
                "competencia_dt",
                "class_kind",
                "class_key",
                "class_label",
                "label",
                "desempenho_esperado_pct",
                "desempenho_real_pct",
                "gap_bps",
            ]
        )
    latest_df = base_df[base_df["competencia"] == latest_competencia].copy()
    if latest_df.empty:
        return pd.DataFrame(
            columns=[
                "competencia",
                "competencia_dt",
                "class_kind",
                "class_key",
                "class_label",
                "label",
                "desempenho_esperado_pct",
                "desempenho_real_pct",
                "gap_bps",
            ]
        )
    latest_df = latest_df.rename(
        columns={
            "DESEMP_ESP": "desempenho_esperado_pct",
            "DESEMP_REAL": "desempenho_real_pct",
        }
    )
    latest_df["gap_bps"] = (
        (pd.to_numeric(latest_df["desempenho_real_pct"], errors="coerce") - pd.to_numeric(latest_df["desempenho_esperado_pct"], errors="coerce"))
        * 100.0
    )
    return sort_class_display_frame(latest_df, label_column="class_label")


def _compound_percent(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    compounded = (1.0 + (numeric / 100.0)).prod() - 1.0
    return float(compounded * 100.0)


def _build_event_history(
    *,
    wide_lookup: pd.DataFrame,
    listas_df: pd.DataFrame,
    competencias: list[str],
) -> pd.DataFrame:
    frames = [
        _build_scalar_event_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="senior",
            default_label="Senior",
            event_type="emissao",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/CAPT_MES/CLASSE_SENIOR/",
            label_fields=("SERIE",),
            value_fields=("QT_COTAS", "VL_TOTAL"),
        ),
        _build_scalar_event_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="subordinada",
            default_label="Subordinada",
            event_type="emissao",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/CAPT_MES/CLASSE_SUBORD/",
            label_fields=("TIPO", "SERIE"),
            value_fields=("QT_COTAS", "VL_TOTAL"),
        ),
        _build_scalar_event_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="senior",
            default_label="Senior",
            event_type="resgate",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/RESG_MES/CLASSE_SENIOR/",
            label_fields=("SERIE",),
            value_fields=("QT_COTAS", "VL_TOTAL"),
        ),
        _build_scalar_event_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="subordinada",
            default_label="Subordinada",
            event_type="resgate",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/RESG_MES/CLASSE_SUBORD/",
            label_fields=("TIPO", "SERIE"),
            value_fields=("QT_COTAS", "VL_TOTAL"),
        ),
        _build_scalar_event_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="senior",
            default_label="Senior",
            event_type="amortizacao",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/AMORT/CLASSE_SENIOR/",
            label_fields=("SERIE",),
            value_fields=("VL_COTA", "VL_TOTAL"),
        ),
        _build_scalar_event_frame(
            wide_lookup=wide_lookup,
            competencias=competencias,
            class_kind="subordinada",
            default_label="Subordinada",
            event_type="amortizacao",
            base_path="DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/CAPTA_RESGA_AMORTI/AMORT/CLASSE_SUBORD/",
            label_fields=("TIPO", "SERIE"),
            value_fields=("VL_COTA", "VL_TOTAL"),
        ),
        _build_list_event_frame(
            listas_df=listas_df,
            class_kind="senior",
            default_label="Senior",
            event_type="emissao",
            list_token="CAPT_MES/CLASSE_SENIOR",
            label_fields=("SERIE",),
            value_fields=("QT_COTAS", "VL_TOTAL"),
        ),
        _build_list_event_frame(
            listas_df=listas_df,
            class_kind="subordinada",
            default_label="Subordinada",
            event_type="emissao",
            list_token="CAPT_MES/CLASSE_SUBORD",
            label_fields=("TIPO", "SERIE"),
            value_fields=("QT_COTAS", "VL_TOTAL"),
        ),
        _build_list_event_frame(
            listas_df=listas_df,
            class_kind="senior",
            default_label="Senior",
            event_type="resgate",
            list_token="RESG_MES/CLASSE_SENIOR",
            label_fields=("SERIE",),
            value_fields=("QT_COTAS", "VL_TOTAL"),
        ),
        _build_list_event_frame(
            listas_df=listas_df,
            class_kind="subordinada",
            default_label="Subordinada",
            event_type="resgate",
            list_token="RESG_MES/CLASSE_SUBORD",
            label_fields=("TIPO", "SERIE"),
            value_fields=("QT_COTAS", "VL_TOTAL"),
        ),
        _build_list_event_frame(
            listas_df=listas_df,
            class_kind="senior",
            default_label="Senior",
            event_type="amortizacao",
            list_token="AMORT/CLASSE_SENIOR",
            label_fields=("SERIE",),
            value_fields=("VL_COTA", "VL_TOTAL"),
        ),
        _build_list_event_frame(
            listas_df=listas_df,
            class_kind="subordinada",
            default_label="Subordinada",
            event_type="amortizacao",
            list_token="AMORT/CLASSE_SUBORD",
            label_fields=("TIPO", "SERIE"),
            value_fields=("VL_COTA", "VL_TOTAL"),
        ),
    ]
    base_df = _finalize_class_frame(
        frames=frames,
        competencias=competencias,
        numeric_fields=("QT_COTAS", "VL_TOTAL", "VL_COTA"),
    )
    if base_df.empty:
        return pd.DataFrame(
            columns=[
                "competencia",
                "competencia_dt",
                "class_kind",
                "label",
                "event_type",
                "qt_cotas",
                "valor_total",
                "valor_cota",
            ]
        )
    rename_map = {"QT_COTAS": "qt_cotas", "VL_TOTAL": "valor_total", "VL_COTA": "valor_cota"}
    base_df = base_df.rename(columns=rename_map)
    numeric_columns = [column for column in ["qt_cotas", "valor_total", "valor_cota"] if column in base_df.columns]
    if numeric_columns:
        numeric_frame = base_df[numeric_columns].fillna(0.0)
        base_df = base_df[(numeric_frame.abs().sum(axis=1) > 0)].copy()
    return base_df


def _build_scalar_class_frame(
    *,
    wide_lookup: pd.DataFrame,
    competencias: list[str],
    class_kind: str,
    default_label: str,
    base_path: str,
    label_fields: tuple[str, ...],
    value_fields: tuple[str, ...],
) -> pd.DataFrame:
    all_fields = tuple(dict.fromkeys((*label_fields, *value_fields)))
    extracted = {
        field: _get_wide_series(wide_lookup, competencias, f"{base_path}{field}")
        for field in all_fields
    }
    if not any(_has_any_value(extracted[field]) for field in value_fields):
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for competencia in competencias:
        row: dict[str, object] = {"competencia": competencia, "class_kind": class_kind}
        for field in all_fields:
            row[field] = extracted[field].loc[competencia]
        rows.append(row)
    frame = pd.DataFrame(rows)
    frame["label"] = frame.apply(
        lambda row: _resolve_class_label(
            row=row,
            class_kind=class_kind,
            default_label=default_label,
            label_fields=label_fields,
        ),
        axis=1,
    )
    return _attach_class_identity(
        frame=frame,
        class_kind=class_kind,
        default_label=default_label,
    )


def _build_list_class_frame(
    *,
    listas_df: pd.DataFrame,
    class_kind: str,
    default_label: str,
    list_token: str,
    label_fields: tuple[str, ...],
    value_fields: tuple[str, ...],
) -> pd.DataFrame:
    if listas_df.empty:
        return pd.DataFrame()
    subset = listas_df[listas_df["list_group_path"].str.contains(list_token, regex=False, na=False)].copy()
    if subset.empty:
        return pd.DataFrame()
    pivot = (
        subset.pivot_table(
            index=["competencia", "list_group_path", "list_index"],
            columns="tag",
            values="valor_excel",
            aggfunc="first",
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    if pivot.empty:
        return pd.DataFrame()
    pivot["class_kind"] = class_kind
    pivot["label"] = pivot.apply(
        lambda row: _resolve_class_label(
            row=row,
            class_kind=class_kind,
            default_label=default_label,
            label_fields=label_fields,
        ),
        axis=1,
    )
    return _attach_class_identity(
        frame=pivot,
        class_kind=class_kind,
        default_label=default_label,
    )


def _build_scalar_event_frame(
    *,
    wide_lookup: pd.DataFrame,
    competencias: list[str],
    class_kind: str,
    default_label: str,
    event_type: str,
    base_path: str,
    label_fields: tuple[str, ...],
    value_fields: tuple[str, ...],
) -> pd.DataFrame:
    frame = _build_scalar_class_frame(
        wide_lookup=wide_lookup,
        competencias=competencias,
        class_kind=class_kind,
        default_label=default_label,
        base_path=base_path,
        label_fields=label_fields,
        value_fields=value_fields,
    )
    if frame.empty:
        return frame
    frame["event_type"] = event_type
    return frame


def _build_list_event_frame(
    *,
    listas_df: pd.DataFrame,
    class_kind: str,
    default_label: str,
    event_type: str,
    list_token: str,
    label_fields: tuple[str, ...],
    value_fields: tuple[str, ...],
) -> pd.DataFrame:
    frame = _build_list_class_frame(
        listas_df=listas_df,
        class_kind=class_kind,
        default_label=default_label,
        list_token=list_token,
        label_fields=label_fields,
        value_fields=value_fields,
    )
    if frame.empty:
        return frame
    frame["event_type"] = event_type
    return frame


def _resolve_class_label(
    *,
    row: pd.Series,
    class_kind: str,
    default_label: str,
    label_fields: tuple[str, ...],
) -> str:
    for field in label_fields:
        raw_value = row.get(field)
        if not _is_blank(raw_value):
            return str(raw_value).strip()
    list_index = _to_numeric(row.get("list_index"))
    if list_index is not None and class_kind == "senior":
        return f"{default_label} {int(list_index)}"
    if list_index is not None and int(list_index) > 1:
        return f"{default_label} {int(list_index)}"
    return default_label


def _resolve_class_macro(*, row: pd.Series, class_kind: str) -> tuple[str, str]:
    if class_kind == "senior":
        return "senior", "Sênior"
    tokens = " ".join(
        value
        for value in [
            _display_value(row.get("TIPO")),
            _display_value(row.get("SERIE")),
            _display_value(row.get("label")),
        ]
        if value
    )
    if _MEZZANINE_TOKEN_RE.search(tokens):
        return "mezzanino", "Mezzanino"
    return "subordinada", "Subordinada"


def class_display_sort_key(label: object, row: pd.Series | dict[str, object] | None = None) -> tuple[object, ...]:
    """Deterministic display order for quota/return classes.

    The analytical order is always class -> series -> item. The parser accepts
    imperfect labels from the CVM XML, including labels like "Subordinada 1",
    "Subordinada 1 - item 2", "Sênior · Série 3" and "Mezanino II - A".
    """

    row_lookup = row if row is not None else {}

    def _row_value(name: str) -> object:
        try:
            return row_lookup.get(name)  # type: ignore[union-attr]
        except AttributeError:
            return None

    raw_label = str(label or _row_value("class_label") or _row_value("label") or "").strip()
    class_macro = _normalize_sort_text(_row_value("class_macro"))
    class_kind = _normalize_sort_text(_row_value("class_kind"))
    class_order = CLASS_DISPLAY_ORDER.get(class_macro)
    if class_order is None:
        class_order = CLASS_DISPLAY_ORDER.get(class_kind)
    if class_order is None:
        class_order = _class_order_from_text(raw_label)

    series_source = next(
        (
            value
            for value in (
                _row_value("serie_raw"),
                _row_value("SERIE"),
                _row_value("tipo_raw"),
                _row_value("TIPO"),
                raw_label,
            )
            if not _is_blank(value)
        ),
        raw_label,
    )
    series_number, series_text = _series_sort_components(series_source, raw_label)
    item_number = _item_sort_number(raw_label, _row_value("list_index"))
    fallback = _natural_sort_tuple(_normalize_sort_text(raw_label))
    return (class_order, series_number, series_text, item_number, fallback)


def sort_class_display_frame(
    frame: pd.DataFrame,
    *,
    label_column: str | None = None,
    extra_columns: list[str] | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    output = frame.copy()
    resolved_label_column = label_column or ("class_label" if "class_label" in output.columns else "label")
    if resolved_label_column not in output.columns:
        return output.reset_index(drop=True)
    sort_values = output.apply(
        lambda row: class_display_sort_key(row.get(resolved_label_column), row),
        axis=1,
    )
    sort_frame = pd.DataFrame(
        sort_values.tolist(),
        index=output.index,
        columns=["__class_order", "__series_number", "__series_text", "__item_number", "__fallback"],
    )
    output = pd.concat([output, sort_frame], axis=1)
    sort_columns = [column for column in (extra_columns or []) if column in output.columns]
    sort_columns.extend(["__class_order", "__series_number", "__series_text", "__item_number", "__fallback"])
    output = output.sort_values(sort_columns, kind="stable").drop(
        columns=["__class_order", "__series_number", "__series_text", "__item_number", "__fallback"],
    )
    return output.reset_index(drop=True)


def ordered_class_labels(labels: list[str] | pd.Series, reference_frame: pd.DataFrame | None = None) -> list[str]:
    raw_labels = pd.Series(labels, dtype="object").dropna().astype(str).drop_duplicates().tolist()
    if not raw_labels:
        return []
    if reference_frame is None or reference_frame.empty:
        return sorted(raw_labels, key=class_display_sort_key)
    label_column = "class_label" if "class_label" in reference_frame.columns else "label"
    if label_column not in reference_frame.columns:
        return sorted(raw_labels, key=class_display_sort_key)
    ref = reference_frame[reference_frame[label_column].astype(str).isin(raw_labels)].copy()
    ref = ref.drop_duplicates(subset=[label_column], keep="first")
    ref = sort_class_display_frame(ref, label_column=label_column)
    ordered = ref[label_column].dropna().astype(str).tolist()
    remaining = [label for label in raw_labels if label not in set(ordered)]
    return ordered + sorted(remaining, key=class_display_sort_key)


def _attach_class_identity(
    *,
    frame: pd.DataFrame,
    class_kind: str,
    default_label: str,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    output = frame.copy()
    output["legacy_label"] = output.get("label", default_label)
    identity_df = output.apply(
        lambda row: pd.Series(
            _build_class_identity(
                row=row,
                class_kind=class_kind,
                default_label=default_label,
            )
        ),
        axis=1,
    )
    output = pd.concat([output, identity_df], axis=1)
    output["label"] = output["class_label"]
    return output


def _build_class_identity(
    *,
    row: pd.Series,
    class_kind: str,
    default_label: str,
) -> dict[str, object]:
    tipo_raw = _display_value(row.get("TIPO"))
    serie_raw = _display_value(row.get("SERIE"))
    tipo_norm = _normalize_class_token(tipo_raw)
    serie_norm = _normalize_class_token(serie_raw)
    list_index = _safe_int(row.get("list_index"))

    if class_kind == "senior":
        if serie_raw:
            class_label = f"Sênior · {serie_raw}"
        elif list_index is not None:
            class_label = f"Sênior · item {list_index}"
        else:
            class_label = "Sênior"
        identity_confidence = "high" if serie_norm else "low"
    else:
        if tipo_raw and serie_raw and tipo_norm != serie_norm:
            class_label = f"{tipo_raw} · {serie_raw}"
            identity_confidence = "high"
        elif tipo_raw:
            class_label = f"{tipo_raw} · item {list_index}" if list_index is not None and not serie_raw else tipo_raw
            identity_confidence = "medium" if list_index is not None else "high"
        elif serie_raw:
            class_label = f"Subordinada · {serie_raw}"
            identity_confidence = "medium"
        else:
            suffix = f" · item {list_index}" if list_index is not None else ""
            class_label = f"{default_label}{suffix}"
            identity_confidence = "low"

    key_parts = [
        class_kind.strip().lower() or "classe",
        tipo_norm or "_",
        serie_norm or "_",
        str(list_index) if list_index is not None and not (tipo_norm or serie_norm) else "_",
    ]
    class_key = "|".join(key_parts)
    class_macro, class_macro_label = _resolve_class_macro(row=row, class_kind=class_kind)
    return {
        "tipo_raw": tipo_raw or pd.NA,
        "serie_raw": serie_raw or pd.NA,
        "tipo_norm": tipo_norm or pd.NA,
        "serie_norm": serie_norm or pd.NA,
        "class_key": class_key,
        "class_label": class_label,
        "class_macro": class_macro,
        "class_macro_label": class_macro_label,
        "identity_confidence": identity_confidence,
    }


def _normalize_class_token(value: object) -> str:
    text = _display_value(value)
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().casefold()


def _normalize_sort_text(value: object) -> str:
    text = _display_value(value)
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = ascii_text.casefold().replace("·", " ").replace("|", " ")
    return re.sub(r"\s+", " ", ascii_text).strip()


def _class_order_from_text(value: object) -> int:
    normalized = _normalize_sort_text(value)
    if re.search(r"\bsenior\b", normalized):
        return CLASS_DISPLAY_ORDER["senior"]
    if re.search(r"\bmezz?\b|\bmezzanino\b|\bmezanino\b|\bmz\b", normalized):
        return CLASS_DISPLAY_ORDER["mezzanino"]
    if re.search(r"\bsubordinad[ao]?\b|\bsub\b", normalized):
        return CLASS_DISPLAY_ORDER["subordinada"]
    return 99


def _series_sort_components(primary_value: object, label: object) -> tuple[int, str]:
    for candidate in (primary_value, label):
        normalized = _normalize_sort_text(candidate)
        if not normalized:
            continue
        cleaned = re.sub(r"\bitem\s*\d+\b", " ", normalized)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        number_match = re.search(
            r"(?:serie|senior|subordinad[ao]?|mezzanino|mezanino|mezz?|mz)\D*(\d+)",
            cleaned,
        )
        if number_match:
            return int(number_match.group(1)), cleaned
        ordinal_match = re.search(r"\b(\d+)\s*(?:a|o)?\s*serie\b", cleaned)
        if ordinal_match:
            return int(ordinal_match.group(1)), cleaned
        generic_number = re.search(r"\b(\d+)\b", cleaned)
        if generic_number:
            return int(generic_number.group(1)), cleaned
        roman_match = re.search(
            r"(?:mezzanino|mezanino|mezz?|mz)\s+([ivxlcdm]+)\b",
            cleaned,
        )
        if roman_match:
            roman_value = _roman_to_int(roman_match.group(1))
            if roman_value is not None:
                return roman_value, cleaned
    return 999_999, _normalize_sort_text(label)


def _item_sort_number(label: object, list_index: object = None) -> int:
    normalized = _normalize_sort_text(label)
    item_match = re.search(r"\bitem\s*(\d+)\b", normalized)
    if item_match:
        return int(item_match.group(1))
    return 0


def _roman_to_int(value: str) -> int | None:
    roman = str(value or "").upper()
    if not roman or not re.fullmatch(r"[IVXLCDM]+", roman):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(roman):
        current = values[char]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total


def _natural_sort_tuple(value: str) -> tuple[object, ...]:
    parts = re.split(r"(\d+)", value)
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part != "")


def _safe_int(value: object) -> int | None:
    numeric = _to_numeric(value)
    if numeric is None:
        return None
    return int(numeric)


def _humanize_rate_context(sub_bloco: object) -> str:
    raw = str(sub_bloco or "").strip()
    if not raw:
        return "Taxas / Não identificado"
    parts = raw.split("/")
    if len(parts) >= 2:
        grupo = _humanize_rate_token(parts[-2])
        operacao = _humanize_rate_token(parts[-1])
        return f"{grupo} / {operacao}"
    return _humanize_rate_token(parts[-1])


def _humanize_rate_token(token: str) -> str:
    normalized = token.upper().replace("TAXA_NEGOC_DICRED_MES_", "")
    replacements = {
        "AQUIS": "Com aquisição",
        "SEM_AQUIS": "Sem aquisição",
        "VALOR_MOBILI": "Valores mobiliários",
        "TITPUB_FED": "Títulos públicos federais",
        "CDB": "CDB",
        "ATIV_RF": "Ativos de renda fixa",
        "DESC_COMPRA": "Desconto compra",
        "DESC_VENDA": "Desconto venda",
        "JUROS_COMPRA": "Juros compra",
        "JUROS_VENDA": "Juros venda",
    }
    if normalized in replacements:
        return replacements[normalized]
    for suffix in ["DESC_COMPRA", "DESC_VENDA", "JUROS_COMPRA", "JUROS_VENDA"]:
        if normalized.endswith(suffix):
            return replacements[suffix]
    return normalized.replace("_", " ").title()


def _has_any_value(series: pd.Series) -> bool:
    return any(not _is_blank(value) for value in series.tolist())


def _finalize_class_frame(
    *,
    frames: list[pd.DataFrame],
    competencias: list[str],
    numeric_fields: tuple[str, ...],
) -> pd.DataFrame:
    usable_frames = [frame for frame in frames if not frame.empty]
    if not usable_frames:
        return pd.DataFrame()

    combined = pd.concat(usable_frames, ignore_index=True, sort=False)
    combined = combined[combined["competencia"].isin(competencias)].copy()
    combined["competencia_dt"] = combined["competencia"].map(_competencia_to_timestamp)
    for field in numeric_fields:
        if field in combined.columns:
            combined[field] = pd.to_numeric(combined[field], errors="coerce")

    existing_numeric = [field for field in numeric_fields if field in combined.columns]
    if existing_numeric:
        combined = combined.dropna(subset=existing_numeric, how="all")

    dedupe_columns = [
        column
        for column in ["competencia", "class_kind", "class_key", "label", "event_type"]
        if column in combined.columns
    ]
    combined = sort_class_display_frame(combined, extra_columns=["competencia_dt"])
    combined = combined.drop_duplicates(subset=dedupe_columns, keep="last")

    return combined.reset_index(drop=True)
