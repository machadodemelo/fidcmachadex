from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from html import escape
import json
import math
from pathlib import Path
import re
import time
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from services.fundonet_dashboard import build_dashboard_data
from services.ime_loader import load_or_extract_informe
from services.ime_period import (
    ImePeriodSelection,
    build_custom_period,
    build_preset_period,
    current_default_end_month,
    display_month_count_for_period,
    parse_competencia_label,
    select_competencia_labels_for_period,
    shift_month,
)
from services.monitoring_metrics import (
    MonitoringTables,
    build_monitoring_tables,
    load_manual_overrides,
    read_wide_csv,
    save_manual_overrides,
)
from services.portfolio_store import PortfolioRecord
from services.regulatory_knowledge import (
    common_criteria_summary,
    document_inventory_rows,
    emission_rows,
    extracted_criteria_rows,
    knowledge_summary_rows,
    load_regulatory_knowledge,
    normalize_cnpj,
)
from services.regulatory_profiles import (
    CuratedRegulatoryProfile,
    load_regulatory_profile,
    payment_calendar_rows,
)
from services.variaveis_fnet import competencia_columns, resolve_tag_path
from tabs.ime_portfolio_support import (
    build_portfolio_record_label_lookup,
    format_portfolio_cnpj,
    list_saved_portfolios,
    normalize_portfolio_fund_name,
)


_CACHE_MONTH_OPTIONS = (12, 15, 18, 24, 36, 48, 60, 72)
_MONITORING_DERIVED_CACHE_VERSION = 2
_MONITORING_DERIVED_CACHE_ROOT = Path(".cache/fundonet-monitoring")
_CORE_AVAILABILITY_IDS = (
    "PATRLIQ/VL_SOM_PATRLIQ",
    "PATRLIQ/VL_PATRIM_LIQ",
    "APLIC_ATIVO/VL_SOM_APLIC_ATIVO",
    "APLIC_ATIVO/VL_CARTEIRA",
)
_AGING_ABSOLUTE_BUCKETS = [
    "1-30d",
    "31-60d",
    "61-90d",
    "91-120d",
    "121-150d",
    "151-180d",
    "181-360d",
    "361d+",
]


@dataclass(frozen=True)
class CockpitMetric:
    section: str
    label: str
    indicator: str
    unit: str
    aggregate: str


_COCKPIT_METRICS: tuple[CockpitMetric, ...] = (
    CockpitMetric("Tamanho e alocação", "PL", "PL (R$)", "R$ bruto", "sum"),
    CockpitMetric("Tamanho e alocação", "Direitos creditórios", "Dir Cred (R$ MM)", "R$ MM", "sum"),
    CockpitMetric("Tamanho e alocação", "Direitos creditórios / PL", "Dir Cred / PL", "ratio", "dircred_pl"),
    CockpitMetric("Inadimplência", "Over 30d / Crédito", "Vencidos Over 30 d / Crédito", "ratio", "over30_credito"),
    CockpitMetric("Inadimplência", "Over 60d / Crédito", "Vencidos Over 60 d / Crédito", "ratio", "over60_credito"),
    CockpitMetric("Inadimplência", "Over 90d / Crédito", "Vencidos Over 90 d / Crédito", "ratio", "over90_credito"),
    CockpitMetric("Inadimplência", "Over 180d / Crédito", "Vencidos Over 180 d / Crédito", "ratio", "over180_credito"),
    CockpitMetric("Inadimplência", "Over 360d / Crédito", "Vencidos Over 360 d / Crédito", "ratio", "over360_credito"),
    CockpitMetric("PDD e recompras", "PDD", "PDD (R$ MM)", "R$ MM", "sum"),
    CockpitMetric("PDD e recompras", "PDD / Crédito", "PDD / Crédito", "ratio", "pdd_credito"),
    CockpitMetric("PDD e recompras", "PDD / Over 90d", "PDD / Venc > 90 d", "ratio", "pdd_over90"),
    CockpitMetric("PDD e recompras", "Recompras / Crédito", "Recompras / Crédito", "ratio", "recompras_credito"),
    CockpitMetric("Cotas e retorno", "Cotas SR / PL", "Cotas SR / PL %", "%", "weighted_pl"),
    CockpitMetric("Cotas e retorno", "Cotas MZ / PL", "Cotas MZ / PL %", "%", "weighted_pl"),
    CockpitMetric("Cotas e retorno", "Cotas Sub / PL", "Cotas Sub / PL %", "%", "weighted_pl"),
    CockpitMetric("Cotas e retorno", "Rentabilidade SR a.m.", "Rentabilidade SR % a.m.", "%", "none"),
    CockpitMetric("Cotas e retorno", "Rentabilidade MZ a.m.", "Rentabilidade MZ % a.m.", "%", "none"),
    CockpitMetric("Cotas e retorno", "Rentabilidade Sub a.m.", "Rentabilidade Sub % a.m.", "%", "none"),
)


_CSS = """
<style>
.monitor-card-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 0.35rem 0 0.7rem 0;
}
.monitor-chip {
    align-items: center;
    background: #f8f9fa;
    border: 1px solid #eceff3;
    border-radius: 999px;
    color: #5a5a5a;
    display: inline-flex;
    font-size: 0.74rem;
    gap: 5px;
    line-height: 1.2;
    padding: 5px 9px;
}
.monitor-chip strong {
    color: #212529;
    font-weight: 600;
}
.monitor-card-grid {
    display: grid;
    gap: 8px;
    grid-template-columns: repeat(6, minmax(110px, 1fr));
    margin: 0.55rem 0 0.75rem 0;
}
.monitor-kpi-card {
    background: #F7F7F7;
    border: 1px solid #E5E5E5;
    border-radius: 6px;
    min-height: 64px;
    padding: 8px 10px;
}
.monitor-kpi-label {
    color: #6B6B6B;
    font-size: 0.67rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    line-height: 1.15;
    text-transform: uppercase;
}
.monitor-kpi-value {
    color: #1F1F1F;
    font-size: 1.05rem;
    font-weight: 700;
    line-height: 1.25;
    margin-top: 6px;
}
.monitor-kpi-note {
    color: #8C8C8C;
    font-size: 0.68rem;
    line-height: 1.2;
    margin-top: 2px;
}
.monitor-wide-wrapper {
    overflow-x: auto;
    overflow-y: visible;
    max-width: 100%;
    padding-bottom: 5px;
    margin-bottom: 12px;
}
.monitor-wide-section {
    margin: 0 0 8px 0;
}
.monitor-wide-section summary {
    background: #000000;
    color: #FFFFFF;
    cursor: pointer;
    font-size: 13px;
    font-weight: 700;
    line-height: 1.25;
    list-style-position: inside;
    padding: 7px 9px;
    white-space: normal;
}
.monitor-wide-table {
    border-collapse: collapse;
    font-family: inherit;
    font-size: 12px;
    table-layout: fixed;
    width: 100%;
}
.monitor-wide-table th {
    background: #FFFFFF;
    border-bottom: 1px solid #3F3F3F;
    color: #000000;
    font-weight: 600;
    line-height: 1.15;
    overflow-wrap: anywhere;
    padding: 6px 8px;
    position: sticky;
    text-align: right;
    top: 0;
    white-space: normal;
    word-break: normal;
    z-index: 2;
}
.monitor-wide-table th.label-col,
.monitor-wide-table td.label {
    text-align: left;
}
.monitor-wide-table td {
    border-bottom: 1px solid #E5E5E5;
    color: #3F3F3F;
    line-height: 1.22;
    overflow-wrap: anywhere;
    padding: 4px 8px;
    text-align: right;
    vertical-align: top;
    white-space: normal;
    word-break: normal;
}
.monitor-wide-table td.label {
    color: #000000;
    font-weight: 500;
    padding-left: 14px;
}
.monitor-wide-table tr.destaque td {
    color: #000000;
    font-weight: 700;
}
.monitor-wide-table tr:hover td {
    background: #F4F1EA;
}
.monitor-fund-title {
    color: #1f1f1f;
    font-size: 1.02rem;
    font-weight: 700;
    line-height: 1.25;
    margin: 0.35rem 0 0.1rem 0;
}
.monitor-caption {
    color: #6f7a87;
    font-size: 0.78rem;
    line-height: 1.35;
    margin-bottom: 0.45rem;
}
@media (max-width: 1100px) {
    .monitor-card-grid {
        grid-template-columns: repeat(3, minmax(110px, 1fr));
    }
}
</style>
"""

_PT_MONTH_ABBR = {
    "01": "jan",
    "02": "fev",
    "03": "mar",
    "04": "abr",
    "05": "mai",
    "06": "jun",
    "07": "jul",
    "08": "ago",
    "09": "set",
    "10": "out",
    "11": "nov",
    "12": "dez",
}


def render_tab_fidc_monitoring(period: ImePeriodSelection | None = None) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown("## Monitoramento FIDCs")

    if period is None:
        period = build_preset_period(end_month=current_default_end_month(), months=12)

    portfolios = list_saved_portfolios()
    if not portfolios:
        st.info("Crie uma carteira salva nas abas de carteira/Soma de FIDCs para usar o monitoramento.")
        return

    selected_portfolio = _render_portfolio_selector(portfolios)
    if selected_portfolio is None:
        return

    cache_months = _render_cache_horizon_control(selected_portfolio=selected_portfolio, period=period)
    load_period = _build_cache_load_period(period=period, cache_months=cache_months)

    _render_requested_load_chips(period=period, load_period=load_period, cache_months=cache_months, fund_count=len(selected_portfolio.funds))

    session_key = _session_key(selected_portfolio, period, cache_months)
    if st.button("Carregar monitoramento", type="primary", key=f"{session_key}::load"):
        st.session_state[session_key] = _load_portfolio_monitoring(selected_portfolio, period, cache_months)
        st.rerun()

    outputs = st.session_state.get(session_key)
    if not outputs:
        st.info("Carregue a carteira para começar.")
        return

    success_outputs = [item for item in outputs if item.get("tables") is not None]
    error_outputs = [item for item in outputs if item.get("error")]
    if error_outputs:
        with st.expander("Fundos com falha de carga", expanded=False):
            for item in error_outputs:
                st.caption(f"**{item['display_name']}** · {item['cnpj']} — {item['error']}")
    if not success_outputs:
        st.warning("Nenhum fundo carregou dados suficientes para montar o monitoramento.")
        return

    _render_loaded_period_status(success_outputs, requested_period=period, load_period=load_period, cache_months=cache_months)

    cockpit_tab, regulatory_tab, fund_tab = st.tabs(["Cockpit", "Base regulatória", "Tabela por Fundo"])
    with cockpit_tab:
        _render_cockpit_tab(success_outputs)
    with regulatory_tab:
        _render_regulatory_base_tab(success_outputs)
    with fund_tab:
        _render_fund_boards_tab(success_outputs)


def _render_portfolio_selector(portfolios: list[PortfolioRecord]) -> PortfolioRecord | None:
    labels = build_portfolio_record_label_lookup(portfolios)
    portfolio_id = st.selectbox(
        "Carteira",
        options=[portfolio.id for portfolio in portfolios],
        format_func=lambda value: labels.get(value, value),
        key="monitoring_portfolio_id",
    )
    return next((portfolio for portfolio in portfolios if portfolio.id == portfolio_id), None)


def _render_cache_horizon_control(*, selected_portfolio: PortfolioRecord, period: ImePeriodSelection) -> int:
    target_months = display_month_count_for_period(period)
    recommended = max(target_months + 3, 15)
    options = sorted({*_CACHE_MONTH_OPTIONS, recommended, target_months})
    default_index = options.index(recommended)
    key = f"monitoring_cache_months::{selected_portfolio.id}"
    return int(
        st.selectbox(
            "Histórico do cache",
            options=options,
            index=default_index,
            format_func=lambda value: f"{value} meses",
            key=key,
            help="Meses lidos do cache local.",
        )
    )


def _build_cache_load_period(*, period: ImePeriodSelection, cache_months: int) -> ImePeriodSelection:
    cache_months = max(int(cache_months), display_month_count_for_period(period))
    return build_custom_period(
        start_month=shift_month(period.end_month, -(cache_months - 1)),
        end_month=period.end_month,
    )


def _render_requested_load_chips(*, period: ImePeriodSelection, load_period: ImePeriodSelection, cache_months: int, fund_count: int) -> None:
    _ = load_period
    st.markdown(
        f"""
<div class="monitor-card-row">
  <span class="monitor-chip"><strong>Janela:</strong> {escape(_format_period_label(period))}</span>
  <span class="monitor-chip"><strong>Histórico:</strong> {cache_months} meses</span>
  <span class="monitor-chip"><strong>Fundos:</strong> {fund_count}</span>
</div>
""",
        unsafe_allow_html=True,
    )


def _load_portfolio_monitoring(portfolio: PortfolioRecord, period: ImePeriodSelection, cache_months: int) -> list[dict[str, Any]]:
    progress = st.progress(0.0, text="Preparando monitoramento...")
    outputs: list[dict[str, Any]] = []
    total = len(portfolio.funds)
    load_period = _build_cache_load_period(period=period, cache_months=cache_months)
    for index, fund in enumerate(portfolio.funds, start=1):
        fund_started = time.perf_counter()
        progress.progress(index / max(total, 1), text=f"{index}/{total} · {fund.display_name}")
        try:
            cached = load_or_extract_informe(
                cnpj_fundo=fund.cnpj,
                data_inicial=load_period.start_month,
                data_final=load_period.end_month,
            )
            wide_df = read_wide_csv(cached.result.wide_csv_path)
            all_competencias = _available_competencias_from_wide(wide_df)
            competencias = select_competencia_labels_for_period(all_competencias, period) or all_competencias
            overrides = load_manual_overrides(fund.cnpj)
            tables, metric_source, dashboard_error, derived_cache_status = _load_or_build_monitoring_tables(
                wide_df=wide_df,
                cnpj=fund.cnpj,
                competencias=competencias,
                overrides=overrides,
                ime_cache_key=cached.cache_key,
                wide_csv_path=cached.result.wide_csv_path,
                listas_csv_path=cached.result.listas_csv_path,
                docs_csv_path=cached.result.docs_csv_path,
            )
            elapsed = time.perf_counter() - fund_started
            outputs.append(
                {
                    "cnpj": fund.cnpj,
                    "display_name": normalize_portfolio_fund_name(fund.display_name, fund.cnpj),
                    "competencias": competencias,
                    "all_competencias": all_competencias,
                    "tables": tables,
                    "cache_status": cached.cache_status,
                    "derived_cache_status": derived_cache_status,
                    "cache_dir": str(cached.cache_dir),
                    "load_period_label": _format_period_label(load_period),
                    "metric_source": metric_source,
                    "dashboard_error": dashboard_error,
                    "load_seconds": round(elapsed, 3),
                }
            )
        except Exception as exc:  # noqa: BLE001
            outputs.append(
                {
                    "cnpj": fund.cnpj,
                    "display_name": normalize_portfolio_fund_name(fund.display_name, fund.cnpj),
                    "error": f"{type(exc).__name__}: {exc}",
                    "load_seconds": round(time.perf_counter() - fund_started, 3),
                }
            )
    progress.empty()
    return outputs


def _load_or_build_monitoring_tables(
    *,
    wide_df: pd.DataFrame,
    cnpj: str,
    competencias: list[str],
    overrides: dict[str, Any],
    ime_cache_key: str,
    wide_csv_path: Path,
    listas_csv_path: Path,
    docs_csv_path: Path,
) -> tuple[MonitoringTables, str, str, str]:
    cache_key = _monitoring_derived_cache_key(
        cnpj=cnpj,
        ime_cache_key=ime_cache_key,
        competencias=competencias,
        overrides=overrides,
    )
    cached = _read_monitoring_derived_cache(cache_key)
    if cached is not None:
        return cached

    dashboard_data = None
    dashboard_error = ""
    try:
        dashboard_data = build_dashboard_data(
            wide_csv_path=wide_csv_path,
            listas_csv_path=listas_csv_path,
            docs_csv_path=docs_csv_path,
        )
    except Exception as dashboard_exc:  # noqa: BLE001
        dashboard_error = f"{type(dashboard_exc).__name__}: {dashboard_exc}"
    tables = build_monitoring_tables(
        wide_df,
        competencias,
        cnpj=cnpj,
        overrides=overrides,
        dashboard_data=dashboard_data,
    )
    metric_source = "Visão Executiva canônica" if dashboard_data is not None else "Campos escalares IME"
    _write_monitoring_derived_cache(
        cache_key=cache_key,
        tables=tables,
        metric_source=metric_source,
        dashboard_error=dashboard_error,
    )
    return tables, metric_source, dashboard_error, "miss"


def _monitoring_derived_cache_key(
    *,
    cnpj: str,
    ime_cache_key: str,
    competencias: list[str],
    overrides: dict[str, Any],
) -> str:
    payload = {
        "schema_version": _MONITORING_DERIVED_CACHE_VERSION,
        "cnpj": "".join(ch for ch in str(cnpj) if ch.isdigit()),
        "ime_cache_key": ime_cache_key,
        "competencias": list(competencias),
        "overrides": overrides or {},
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _read_monitoring_derived_cache(cache_key: str) -> tuple[MonitoringTables, str, str, str] | None:
    cache_dir = _MONITORING_DERIVED_CACHE_ROOT / cache_key
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if int(manifest.get("schema_version") or 0) != _MONITORING_DERIVED_CACHE_VERSION:
        return None
    files = manifest.get("files") or {}
    required = {"raw_variables_df", "indicators_df", "aging_df", "audit_df"}
    if not required.issubset(files):
        return None
    paths = {key: cache_dir / str(value) for key, value in files.items()}
    if not all(paths[key].exists() for key in required):
        return None
    try:
        tables = MonitoringTables(
            raw_variables_df=pd.read_csv(paths["raw_variables_df"], dtype=str, keep_default_na=False),
            indicators_df=pd.read_csv(paths["indicators_df"], dtype=str, keep_default_na=False),
            aging_df=pd.read_csv(paths["aging_df"], dtype=str, keep_default_na=False),
            audit_df=pd.read_csv(paths["audit_df"], dtype=str, keep_default_na=False),
        )
    except (OSError, pd.errors.ParserError):
        return None
    return (
        tables,
        str(manifest.get("metric_source") or "cache derivado"),
        str(manifest.get("dashboard_error") or ""),
        "hit",
    )


def _write_monitoring_derived_cache(
    *,
    cache_key: str,
    tables: MonitoringTables,
    metric_source: str,
    dashboard_error: str,
) -> None:
    cache_dir = _MONITORING_DERIVED_CACHE_ROOT / cache_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_map = {
        "raw_variables_df": "raw_variables.csv",
        "indicators_df": "indicators.csv",
        "aging_df": "aging.csv",
        "audit_df": "audit.csv",
    }
    tables.raw_variables_df.to_csv(cache_dir / file_map["raw_variables_df"], index=False)
    tables.indicators_df.to_csv(cache_dir / file_map["indicators_df"], index=False)
    tables.aging_df.to_csv(cache_dir / file_map["aging_df"], index=False)
    tables.audit_df.to_csv(cache_dir / file_map["audit_df"], index=False)
    manifest = {
        "schema_version": _MONITORING_DERIVED_CACHE_VERSION,
        "metric_source": metric_source,
        "dashboard_error": dashboard_error,
        "files": file_map,
    }
    (cache_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _available_competencias_from_wide(wide_df: pd.DataFrame) -> list[str]:
    competencias = competencia_columns(wide_df)
    if not competencias:
        return []
    core_paths = [resolve_tag_path(short_id, wide_df) for short_id in _CORE_AVAILABILITY_IDS]
    core_paths = [path for path in core_paths if path and path in wide_df.index]
    if not core_paths:
        return competencias

    available: list[str] = []
    for competencia in competencias:
        values = []
        for path in core_paths:
            row = wide_df.loc[path]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            values.append(row.get(competencia))
        numeric = pd.to_numeric(pd.Series(values), errors="coerce")
        if numeric.notna().any():
            available.append(competencia)
    return available or competencias


def _render_loaded_period_status(
    outputs: list[dict[str, Any]],
    *,
    requested_period: ImePeriodSelection,
    load_period: ImePeriodSelection,
    cache_months: int,
) -> None:
    reference, reference_count, reference_total = _portfolio_reference_competencia(outputs)
    display_span = _portfolio_display_span(outputs)
    reference_label = _format_competencia_label(reference) if reference else "-"
    display_label = display_span or "-"
    total_load_seconds = sum(float(item.get("load_seconds") or 0.0) for item in outputs)
    _ = requested_period, load_period, cache_months
    st.markdown(
        f"""
<div class="monitor-card-row">
  <span class="monitor-chip"><strong>{escape(display_label)}</strong></span>
  <span class="monitor-chip"><strong>Cockpit:</strong> {escape(reference_label)}</span>
  <span class="monitor-chip"><strong>{reference_count}/{reference_total}</strong> fundos</span>
  <span class="monitor-chip"><strong>{_format_decimal(total_load_seconds, 1)}s</strong></span>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_cockpit_tab(outputs: list[dict[str, Any]]) -> None:
    reference, reference_count, reference_total = _portfolio_reference_competencia(outputs)
    if not reference:
        st.info("Não há competência disponível para montar o cockpit.")
        return
    st.markdown("### Cockpit da carteira")
    _render_cockpit_cards(outputs, reference, eligible_count=reference_count, total_count=reference_total)
    st.markdown(_render_cockpit_table_html(outputs, reference), unsafe_allow_html=True)
    with st.expander("Carga e cache", expanded=False):
        st.caption("`hit` = cache; `miss` = recalculado.")
        st.dataframe(_build_cache_diagnostics_df(outputs), hide_index=True, use_container_width=True)


def _render_regulatory_base_tab(outputs: list[dict[str, Any]]) -> None:
    loaded = []
    missing = []
    profiles: dict[str, CuratedRegulatoryProfile] = {}
    for item in outputs:
        cnpj = str(item.get("cnpj") or "")
        knowledge = load_regulatory_knowledge(cnpj)
        if knowledge is None:
            missing.append(item)
        else:
            loaded.append(knowledge)
        profile = load_regulatory_profile(cnpj)
        if profile is not None and profile.available:
            profiles[profile.cnpj] = profile

    if not loaded and not profiles:
        st.info("Base regulatória ainda não gerada para esta carteira.")
        st.code("python3 scripts/build_regulatory_knowledge.py", language="bash")
        return

    st.markdown("### Base regulatória")
    if loaded:
        st.dataframe(pd.DataFrame(knowledge_summary_rows(loaded)), hide_index=True, use_container_width=True)
    else:
        st.caption("Esta carteira só possui perfis regulatórios curados locais.")

    common = common_criteria_summary(loaded)
    if common:
        with st.expander("Critérios recorrentes na carteira", expanded=False):
            st.dataframe(pd.DataFrame(common), hide_index=True, use_container_width=True)

    options = sorted(
        {item.cnpj for item in loaded} | set(profiles),
        key=lambda cnpj: _regulatory_fund_label(cnpj, loaded, outputs),
    )
    by_cnpj = {item.cnpj: item for item in loaded}
    by_output = {normalize_cnpj(str(item.get("cnpj") or "")): item for item in outputs}
    selected_cnpj = st.selectbox(
        "Fundo",
        options=options,
        format_func=lambda cnpj: _regulatory_fund_label(cnpj, loaded, outputs),
        key="monitoring_regulatory_fund",
    )
    selected = by_cnpj.get(selected_cnpj)
    selected_output = by_output.get(selected_cnpj)
    profile = profiles.get(selected_cnpj)

    criteria_df = _selected_criteria_df(selected, profile)
    emissions_df = _selected_emissions_df(selected, profile)
    inventory_df = pd.DataFrame(document_inventory_rows(selected)) if selected is not None else pd.DataFrame()
    timeline_df = (
        inventory_df[inventory_df["Tipo"].isin(["regulamento", "assembleia", "emissao", "evento"])]
        if not inventory_df.empty and "Tipo" in inventory_df
        else pd.DataFrame()
    )

    _render_regulatory_profile_chips(selected, profile)

    if selected_output is not None and profile is not None and not profile.criteria_df.empty:
        st.markdown("#### Monitoramento IME")
        checks_df = _build_regulatory_monitoring_checks(selected_output, profile.criteria_df)
        if checks_df.empty:
            st.caption("Sem critério curado com proxy IME para a competência carregada.")
        else:
            st.dataframe(checks_df, hide_index=True, use_container_width=True)

    st.markdown("#### Emissões e calendário de pagamentos")
    calendar_df = pd.DataFrame(payment_calendar_rows(profile.emissions_df)) if profile is not None else pd.DataFrame()
    if emissions_df.empty and calendar_df.empty:
        st.caption("Nenhum evento de emissão, juros ou amortização extraído dos documentos processados.")
    else:
        if not emissions_df.empty:
            st.dataframe(_drop_selected_fund_columns(emissions_df), hide_index=True, use_container_width=True)
        if not calendar_df.empty:
            with st.expander("Calendário operacional extraído", expanded=True):
                st.dataframe(calendar_df, hide_index=True, use_container_width=True)

    st.markdown("#### Critérios monitoráveis e qualitativos")
    extraction_errors = selected.payload.get("extraction_errors") if selected is not None else []
    if extraction_errors:
        st.warning(f"{len(extraction_errors)} documento(s) ainda sem extração estruturada.")
    if criteria_df.empty:
        st.caption("Nenhum threshold extraído para este fundo até agora.")
    else:
        st.dataframe(_drop_selected_fund_columns(criteria_df), hide_index=True, use_container_width=True)

    st.markdown("#### Timeline documental CVM")
    if timeline_df.empty:
        st.caption("Sem documentos institucionais classificados para este fundo.")
    else:
        st.dataframe(timeline_df, hide_index=True, use_container_width=True)

    with st.expander("Documentos CVM inventariados", expanded=False):
        st.dataframe(inventory_df, hide_index=True, use_container_width=True)

    if missing:
        with st.expander("Fundos sem base gerada", expanded=False):
            for item in missing:
                st.caption(str(item.get("display_name") or item.get("cnpj") or "-"))


def _regulatory_fund_label(cnpj: str, loaded: list[Any], outputs: list[dict[str, Any]]) -> str:
    digits = normalize_cnpj(cnpj)
    for item in loaded:
        if item.cnpj == digits:
            return item.fund_name
    for item in outputs:
        if normalize_cnpj(str(item.get("cnpj") or "")) == digits:
            return str(item.get("display_name") or cnpj)
    return cnpj


def _selected_criteria_df(selected: Any | None, profile: CuratedRegulatoryProfile | None) -> pd.DataFrame:
    if profile is not None and not profile.criteria_df.empty:
        return profile.criteria_df.copy()
    return pd.DataFrame(extracted_criteria_rows(selected)) if selected is not None else pd.DataFrame()


def _selected_emissions_df(selected: Any | None, profile: CuratedRegulatoryProfile | None) -> pd.DataFrame:
    if profile is not None and not profile.emissions_df.empty:
        return profile.emissions_df.copy()
    return pd.DataFrame(emission_rows(selected)) if selected is not None else pd.DataFrame()


def _render_regulatory_profile_chips(selected: Any | None, profile: CuratedRegulatoryProfile | None) -> None:
    if selected is None and profile is None:
        return
    doc_count = len(selected.payload.get("documents") or []) if selected is not None else 0
    criteria_count = len(profile.criteria_df) if profile is not None else 0
    emission_count = len(profile.emissions_df) if profile is not None else 0
    profile_type = profile.profile_type if profile is not None else "heurístico"
    st.markdown(
        f"""
<div class="monitor-card-row">
  <span class="monitor-chip"><strong>Perfil:</strong> {escape(profile_type)}</span>
  <span class="monitor-chip"><strong>Documentos:</strong> {doc_count}</span>
  <span class="monitor-chip"><strong>Emissões:</strong> {emission_count}</span>
  <span class="monitor-chip"><strong>Critérios:</strong> {criteria_count}</span>
</div>
""",
        unsafe_allow_html=True,
    )


def _drop_selected_fund_columns(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.drop(columns=[column for column in ("Fundo", "CNPJ") if column in frame.columns]).copy()


def _build_regulatory_monitoring_checks(item: dict[str, Any], criteria_df: pd.DataFrame) -> pd.DataFrame:
    latest = _latest_competencia(item)
    if not latest or criteria_df.empty:
        return pd.DataFrame()

    rows = []
    for _, criterion in criteria_df.iterrows():
        evaluated = _evaluate_regulatory_criterion(item, latest, criterion)
        if evaluated:
            rows.append(evaluated)
    return pd.DataFrame(rows)


def _evaluate_regulatory_criterion(item: dict[str, Any], competencia: str, criterion: pd.Series) -> dict[str, str] | None:
    name = str(criterion.get("Critério") or "").strip()
    key = str(criterion.get("Chave") or "").strip()
    monitorability = str(criterion.get("Monitorabilidade IME") or criterion.get("Monitoramento") or "").strip()
    rule = str(criterion.get("Limite/regra") or criterion.get("Limite") or "").strip()
    proxy = str(criterion.get("Métrica IME / proxy") or criterion.get("Métrica IME sugerida") or "").strip()
    alert = str(criterion.get("Condição de alerta sugerida") or "").strip()
    note = str(criterion.get("Observação técnica") or criterion.get("Comentário") or "").strip()

    status = "Referência"
    current_value = "-"

    lowered_name = name.lower()
    if _is_senior_coverage_rule(name, rule):
        senior_pct = _metric_numeric(item, "Cotas SR / PL %", competencia)
        value = (10_000.0 / senior_pct) if senior_pct and senior_pct > 0 else None
        limit = _parse_percent_limit(rule)
        current_value = _format_metric_value(value, "%")
        status = _limit_status(value, limit, higher_is_better=True)
    elif key == "subordination_ratio_min" or "subordinação" in lowered_name or "relação mínima" in lowered_name:
        value = _metric_numeric(item, "Cotas Sub / PL %", competencia)
        limit = _parse_percent_limit(rule)
        current_value = _format_metric_value(value, "%")
        status = _limit_status(value, limit, higher_is_better=True)
    elif key == "credit_rights_allocation_min" or "alocação mínima" in lowered_name:
        value = _metric_numeric(item, "Dir Cred / PL", competencia)
        limit = _parse_percent_limit(rule)
        current_value = _format_metric_value(value, "ratio")
        status = _limit_status((value * 100.0) if value is not None else None, limit, higher_is_better=True)
    elif key in {"default_rate_evaluation_event", "default_rate_early_maturity"}:
        indicator = _default_rate_indicator_for_rule(" ".join([name, rule, proxy, note]))
        if indicator:
            value = _metric_numeric(item, indicator, competencia)
            limit = _parse_percent_limit(rule)
            current_value = _format_metric_value(value, "ratio")
            status = _limit_status((value * 100.0) if value is not None else None, limit, higher_is_better=False)
        else:
            status = "Qualitativo"
    elif key == "pdd_coverage_min" or "pdd" in lowered_name:
        value = _metric_numeric(item, "PDD / Venc Total", competencia)
        limit = _parse_percent_limit(rule)
        current_value = _format_metric_value(value, "ratio")
        status = _limit_status((value * 100.0) if value is not None else None, limit, higher_is_better=True)
    elif key == "recompras_max" or "recompra" in lowered_name:
        value = _metric_numeric(item, "Recompras / Crédito", competencia)
        limit = _parse_percent_limit(rule)
        current_value = _format_metric_value(value, "ratio")
        status = _limit_status((value * 100.0) if value is not None else None, limit, higher_is_better=False)
    elif key == "permitted_hedges" or "derivativo" in lowered_name or "hedge" in lowered_name:
        value = _raw_variable_numeric(item, "MERC_DERIVATIVO/VL_SOM_MERC_DERIVATIVO", competencia)
        current_value = _format_metric_value(value, "R$ bruto")
        if re.search(r"\b(vedad|proibid|não\s+poder|nao\s+poder)\w*", rule.lower()):
            status = "OK" if value is not None and abs(value) <= 1.0 else ("Sem dado" if value is None else "Alerta")
        else:
            status = "Qualitativo"
    elif "pl mínimo" in lowered_name:
        value = _metric_numeric(item, "PL (R$)", competencia)
        current_value = _format_metric_value(value, "R$ bruto")
        status = "OK" if value is not None and value >= 1_000_000 else ("Sem dado" if value is None else "Alerta")
    elif key == "minimum_cash_ratio":
        caixa = _raw_variable_numeric(item, "APLIC_ATIVO/VL_DISPONIB", competencia)
        pl = _metric_numeric(item, "PL (R$)", competencia)
        current_value = _format_metric_value(_safe_ratio(caixa, pl), "ratio")
        status = "Qualitativo"
    elif "direto" not in monitorability.lower():
        status = "Qualitativo"

    return {
        "Critério": name,
        "Regra": rule,
        "Monitorabilidade": monitorability,
        "Proxy IME": proxy,
        "Competência": _format_competencia_label(competencia),
        "Valor IME": current_value,
        "Status": status,
        "Alerta sugerido": alert,
        "Observação": note,
    }


def _is_senior_coverage_rule(name: str, rule: str) -> bool:
    text = f"{name} {rule}".lower()
    return bool(
        ("pl / cotas sênior" in text)
        or ("pl / cotas senior" in text)
        or ("pl/cotas sênior" in text)
        or ("pl/cotas senior" in text)
        or ("patrimônio líquido / cotas seniores" in text)
        or ("patrimonio liquido / cotas seniores" in text)
    )


def _raw_variable_numeric(item: dict[str, Any], id_cvm: str, competencia: str) -> float | None:
    tables: MonitoringTables = item["tables"]
    raw_df = tables.raw_variables_df
    if competencia not in raw_df.columns:
        return None
    match = raw_df[raw_df["id_cvm"] == id_cvm]
    if match.empty:
        return None
    value = pd.to_numeric(pd.Series([match.iloc[0].get(competencia)]), errors="coerce").iloc[0]
    if pd.isna(value):
        return None
    return float(value)


def _parse_percent_limit(value: str) -> float | None:
    match = re.search(r"(\d+(?:[,.]\d+)?)\s*%", str(value or ""))
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _default_rate_indicator_for_rule(value: str) -> str | None:
    text = str(value or "").lower()
    if re.search(r"(over|acima|superior|maior|vencid\w*)\s*(?:a|de)?\s*360|360\s*d", text):
        return "Vencidos Over 360 d / Crédito"
    if re.search(r"(over|acima|superior|maior|vencid\w*)\s*(?:a|de)?\s*180|180\s*d", text):
        return "Vencidos Over 180 d / Crédito"
    if re.search(r"(over|acima|superior|maior|vencid\w*)\s*(?:a|de)?\s*90|90\s*d", text):
        return "Vencidos Over 90 d / Crédito"
    if re.search(r"(over|acima|superior|maior|vencid\w*)\s*(?:a|de)?\s*60|60\s*d", text):
        return "Vencidos Over 60 d / Crédito"
    if re.search(r"(over|acima|superior|maior|vencid\w*)\s*(?:a|de)?\s*30|30\s*d", text):
        return "Vencidos Over 30 d / Crédito"
    return None


def _limit_status(value: float | None, limit: float | None, *, higher_is_better: bool) -> str:
    if value is None or limit is None:
        return "Sem dado"
    if higher_is_better:
        return "OK" if value >= limit else "Alerta"
    return "OK" if value <= limit else "Alerta"


def _render_cockpit_cards(outputs: list[dict[str, Any]], latest: str, *, eligible_count: int, total_count: int) -> None:
    cards = [
        ("Competência", _format_competencia_label(latest), "referência do cockpit"),
        ("Fundos na competência", f"{eligible_count}/{total_count}", "com dado no mês"),
        ("PL total", _format_metric_value(_aggregate_metric(CockpitMetric("", "", "PL (R$)", "R$ bruto", "sum"), outputs, latest), "R$ bruto"), "soma dos fundos"),
        ("DC / PL", _format_metric_value(_aggregate_metric(CockpitMetric("", "", "Dir Cred / PL", "ratio", "dircred_pl"), outputs, latest), "ratio"), "recalculado"),
        ("Over 90d", _format_metric_value(_aggregate_metric(CockpitMetric("", "", "Vencidos Over 90 d / Crédito", "ratio", "over90_credito"), outputs, latest), "ratio"), "sobre crédito"),
        ("PDD / Over 90d", _format_metric_value(_aggregate_metric(CockpitMetric("", "", "PDD / Venc > 90 d", "ratio", "pdd_over90"), outputs, latest), "ratio"), "cobertura"),
    ]
    html = ["<div class='monitor-card-grid'>"]
    for label, value, note in cards:
        html.append(
            "<div class='monitor-kpi-card'>"
            f"<div class='monitor-kpi-label'>{escape(label)}</div>"
            f"<div class='monitor-kpi-value'>{escape(value)}</div>"
            f"<div class='monitor-kpi-note'>{escape(note)}</div>"
            "</div>"
        )
    html.append("</div>")
    st.markdown("\n".join(html), unsafe_allow_html=True)


def _render_cockpit_table_html(outputs: list[dict[str, Any]], latest: str) -> str:
    fund_width = 172
    min_width = max(460 + fund_width * (len(outputs) + 1), 980)
    html = [f"<div class='monitor-wide-wrapper' style='min-width: 100%; --monitor-table-min-width: {min_width}px;'>"]
    by_section: dict[str, list[CockpitMetric]] = {}
    for metric in _COCKPIT_METRICS:
        by_section.setdefault(metric.section, []).append(metric)

    for section, metrics in by_section.items():
        html.append(f"<details class='monitor-wide-section' open style='min-width: {min_width}px;'>")
        html.append(f"<summary>{escape(section)}</summary>")
        html.append(f"<table class='monitor-wide-table' style='min-width: {min_width}px;'>")
        html.append("<colgroup><col style='width: 230px;'><col style='width: 120px;'>")
        html.extend(f"<col style='width: {fund_width}px;'>" for _ in outputs)
        html.append("</colgroup><thead><tr><th class='label-col'>Nome</th><th>Consolidado</th>")
        for item in outputs:
            html.append(f"<th>{escape(str(item['display_name']))}</th>")
        html.append("</tr></thead><tbody>")
        for metric in metrics:
            row_class = "destaque" if metric.indicator in {"PL (R$)", "Vencidos Over 90 d / Crédito", "PDD / Venc > 90 d"} else ""
            html.append(f"<tr class='{row_class}'>")
            html.append(f"<td class='label'>{escape(metric.label)}</td>")
            html.append(f"<td>{escape(_format_metric_value(_aggregate_metric(metric, outputs, latest), metric.unit))}</td>")
            for item in outputs:
                value = _metric_numeric(item, metric.indicator, latest)
                html.append(f"<td>{escape(_format_metric_value(value, metric.unit))}</td>")
            html.append("</tr>")
        html.append("</tbody></table></details>")
    html.append("</div>")
    return "\n".join(html)


def _render_consolidado_tab(outputs: list[dict[str, Any]]) -> None:
    competencias = _ordered_union_competencias(outputs)
    if not competencias:
        st.info("Sem competências disponíveis para consolidar.")
        return
    st.markdown(
        f"""
<div class="monitor-card-row">
  <span class="monitor-chip"><strong>Fundos:</strong> {len(outputs)}</span>
  <span class="monitor-chip"><strong>Janela:</strong> {escape(_format_competencia_span(competencias))}</span>
</div>
""",
        unsafe_allow_html=True,
    )
    rows = []
    for item in outputs:
        row = {"Fundo": str(item.get("display_name") or item.get("cnpj") or "-")}
        for competencia in competencias:
            row[_format_competencia_label(competencia)] = _metric_numeric(item, "PL (R$ MM)", competencia)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("Fundo") if rows else pd.DataFrame()
    st.dataframe(df, use_container_width=True)


def _render_comparison_tab(outputs: list[dict[str, Any]]) -> None:
    selected = _select_output(outputs, key="monitoring_trend_fund")
    if selected is None:
        return
    st.altair_chart(
        _dual_axis_indicator_chart(
            selected,
            title="Evolução PL e Subordinação",
            bar_indicator="PL (R$ MM)",
            bar_title="PL (R$ MM)",
            bar_color="#C0392B",
            line_indicators=[("Cotas Sub / PL %", "Cotas Sub / PL %", "#1a1a1a", [])],
            line_title="Cotas Sub / PL %",
            line_value_transform=lambda value: value,
            line_value_formatter=_format_chart_percent,
        ),
        use_container_width=True,
    )
    st.altair_chart(
        _dual_axis_indicator_chart(
            selected,
            title="Evolução Dir Cred e Vencidos",
            bar_indicator="Dir Cred (R$ MM)",
            bar_title="Dir Cred (R$ MM)",
            bar_color="#C0392B",
            line_indicators=[
                ("Vencidos <= 90 d / Crédito", "Vencidos ≤90d/Créd", "#555555", []),
                ("Vencidos > 90 d / Crédito", "Vencidos >90d/Créd", "#1a1a1a", [4, 2]),
            ],
            line_title="Vencidos / Crédito (%)",
            line_value_transform=lambda value: value * 100.0,
            line_value_formatter=_format_chart_percent,
        ),
        use_container_width=True,
    )
    st.altair_chart(
        _dual_axis_indicator_chart(
            selected,
            title="Provisão e Cobertura",
            bar_indicator="PDD (R$ MM)",
            bar_title="PDD (R$ MM)",
            bar_color="#C0392B",
            line_indicators=[("PDD / Venc Total", "PDD / Venc Total", "#1a1a1a", [])],
            line_title="PDD / Venc Total (%)",
            line_value_transform=lambda value: value * 100.0,
            line_value_formatter=_format_chart_percent,
        ),
        use_container_width=True,
    )
    st.altair_chart(_return_lines_chart(selected), use_container_width=True)


def _ordered_union_competencias(outputs: list[dict[str, Any]]) -> list[str]:
    values = {
        str(competencia)
        for item in outputs
        for competencia in (item.get("competencias") or [])
        if str(competencia or "").strip()
    }
    return sorted(values, key=lambda value: parse_competencia_label(value))


def _indicator_series_for_fund(item: dict[str, Any], indicator: str) -> list[dict[str, object]]:
    """Retorna [{comp_label: str, valor: float}, ...] para o indicador dado."""
    rows: list[dict[str, object]] = []
    for competencia in item.get("competencias") or []:
        value = _metric_numeric(item, indicator, competencia)
        if value is None:
            continue
        rows.append(
            {
                "competencia": competencia,
                "comp_label": _format_competencia_label(competencia),
                "valor": float(value),
            }
        )
    return rows


def _dual_axis_indicator_chart(
    item: dict[str, Any],
    *,
    title: str,
    bar_indicator: str,
    bar_title: str,
    bar_color: str,
    line_indicators: list[tuple[str, str, str, list[int]]],
    line_title: str,
    line_value_transform,
    line_value_formatter,
) -> alt.Chart:
    comp_list = [_format_competencia_label(competencia) for competencia in item.get("competencias") or []]
    bar_df = pd.DataFrame(_indicator_series_for_fund(item, bar_indicator))
    if not bar_df.empty:
        bar_df["valor_fmt"] = bar_df["valor"].map(_format_chart_money_mm)
    line_rows: list[dict[str, object]] = []
    for indicator, label, color, dash in line_indicators:
        for row in _indicator_series_for_fund(item, indicator):
            plot_value = line_value_transform(float(row["valor"]))
            line_rows.append(
                {
                    "comp_label": row["comp_label"],
                    "valor": plot_value,
                    "valor_fmt": line_value_formatter(plot_value),
                    "serie": label,
                    "color": color,
                    "dash": str(dash),
                }
            )
    line_df = pd.DataFrame(line_rows)
    if bar_df.empty and line_df.empty:
        return _empty_monitoring_chart(title)

    base = alt.Chart(pd.DataFrame({"comp_label": comp_list})).encode(
        x=alt.X("comp_label:N", sort=comp_list, title=None)
    )
    bars = (
        alt.Chart(bar_df)
        .mark_bar(color=bar_color)
        .encode(
            x=alt.X("comp_label:N", sort=comp_list, title=None),
            y=alt.Y("valor:Q", title=bar_title, axis=alt.Axis(titleColor=bar_color)),
            tooltip=[
                alt.Tooltip("comp_label:N", title="Competência"),
                alt.Tooltip("valor_fmt:N", title=bar_title),
            ],
        )
        if not bar_df.empty
        else base.mark_bar(opacity=0)
    )
    series_domain = [label for _, label, _, _ in line_indicators]
    color_range = [color for _, _, color, _ in line_indicators]
    dash_range = [dash for _, _, _, dash in line_indicators]
    lines = (
        alt.Chart(line_df)
        .mark_line(point=True, strokeWidth=2.4)
        .encode(
            x=alt.X("comp_label:N", sort=comp_list, title=None),
            y=alt.Y("valor:Q", title=line_title, axis=alt.Axis(titleColor="#1a1a1a"), scale=alt.Scale()),
            color=alt.Color("serie:N", title=None, scale=alt.Scale(domain=series_domain, range=color_range)),
            strokeDash=alt.StrokeDash("serie:N", legend=None, scale=alt.Scale(domain=series_domain, range=dash_range)),
            tooltip=[
                alt.Tooltip("comp_label:N", title="Competência"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("valor_fmt:N", title=line_title),
            ],
        )
        if not line_df.empty
        else base.mark_line(opacity=0)
    )
    return (
        alt.layer(bars, lines)
        .resolve_scale(y="independent")
        .properties(height=260, title=title)
        .configure_axis(labelFontSize=11, titleFontSize=12)
        .configure_legend(labelFontSize=11, titleFontSize=11, orient="bottom")
    )


def _return_lines_chart(item: dict[str, Any]) -> alt.Chart:
    comp_list = [_format_competencia_label(competencia) for competencia in item.get("competencias") or []]
    series_specs = [
        ("Rentabilidade SR % a.m.", "SR", "#2980B9"),
        ("Rentabilidade Sub % a.m.", "Sub", "#1a1a1a"),
        ("Rentabilidade MZ % a.m.", "MZ", "#8E44AD"),
    ]
    rows: list[dict[str, object]] = []
    present_labels: list[str] = []
    present_colors: list[str] = []
    for indicator, label, color in series_specs:
        series_rows = _indicator_series_for_fund(item, indicator)
        if not series_rows:
            continue
        present_labels.append(label)
        present_colors.append(color)
        for row in series_rows:
            value = float(row["valor"])
            rows.append(
                {
                    "comp_label": row["comp_label"],
                    "valor": value,
                    "valor_fmt": _format_chart_percent(value),
                    "serie": label,
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return _empty_monitoring_chart("Rentabilidade das Cotas")
    return (
        alt.Chart(df)
        .mark_line(point=True, strokeWidth=2.4)
        .encode(
            x=alt.X("comp_label:N", sort=comp_list, title=None),
            y=alt.Y("valor:Q", title="% a.m.", scale=alt.Scale()),
            color=alt.Color("serie:N", title=None, scale=alt.Scale(domain=present_labels, range=present_colors)),
            tooltip=[
                alt.Tooltip("comp_label:N", title="Competência"),
                alt.Tooltip("serie:N", title="Cota"),
                alt.Tooltip("valor_fmt:N", title="% a.m."),
            ],
        )
        .properties(height=260, title="Rentabilidade das Cotas")
        .configure_axis(labelFontSize=11, titleFontSize=12)
        .configure_legend(labelFontSize=11, titleFontSize=11, orient="bottom")
    )


def _empty_monitoring_chart(title: str) -> alt.Chart:
    return alt.Chart(pd.DataFrame({"comp_label": [], "valor": []})).mark_line().properties(height=260, title=title)


def _format_chart_money_mm(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "-"
    return f"R$ {_format_decimal(float(numeric), 1)} MM"


def _format_chart_percent(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "-"
    return f"{_format_decimal(float(numeric), 1)}%"


def _render_fund_boards_tab(outputs: list[dict[str, Any]]) -> None:
    selected = _select_output(outputs, key="monitoring_fund_table")
    if selected is None:
        return
    tables: MonitoringTables = selected["tables"]
    cnpj = str(selected["cnpj"])
    fnet_url = f"https://fnet.bmfbovespa.com.br/fnet/publico/abrirGerenciadorDocumentosCVM?cnpjFundo={cnpj}"
    st.markdown(
        f'<div class="monitor-caption"><a href="{escape(fnet_url)}" target="_blank">Abrir FNET</a></div>',
        unsafe_allow_html=True,
    )
    latest = _latest_competencia(selected)
    _render_single_fund_cards(selected, latest)
    st.markdown("### Tabela Completa do fundo")
    st.markdown(_render_fund_time_table_html(selected), unsafe_allow_html=True)
    with st.expander("Auditoria de fórmulas", expanded=False):
        st.caption("Fórmula, fonte e status de cada linha.")
        st.dataframe(tables.audit_df, hide_index=True, use_container_width=True)
    with st.expander("Dados brutos (variáveis IME)", expanded=False):
        _render_raw_data_panel(selected, key_suffix=str(selected.get("cnpj") or "fundo"))


def _aging_stacked_bar(aging_df: pd.DataFrame, competencias: list[str]) -> alt.Chart:
    rows: list[dict[str, object]] = []
    comp_labels = [_format_competencia_label(competencia) for competencia in competencias]
    for bucket_order, bucket in enumerate(_AGING_ABSOLUTE_BUCKETS):
        match = aging_df[(aging_df["bucket"] == bucket) & (aging_df["unidade"] == "R$ MM")]
        if match.empty:
            continue
        source = match.iloc[0]
        for competencia in competencias:
            value = pd.to_numeric(pd.Series([source.get(competencia)]), errors="coerce").iloc[0]
            if pd.isna(value):
                continue
            rows.append(
                {
                    "comp_label": _format_competencia_label(competencia),
                    "bucket": bucket,
                    "bucket_order": bucket_order,
                    "valor": float(value),
                    "valor_fmt": f"{_format_decimal(float(value), 1)} MM",
                }
            )
    data = pd.DataFrame(rows)
    if data.empty:
        return alt.Chart(pd.DataFrame({"comp_label": [], "valor": []})).mark_bar().properties(
            height=240,
            title="Aging — Vencidos por Bucket (R$ MM)",
        )
    return (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X("comp_label:N", sort=comp_labels, title=None),
            y=alt.Y("valor:Q", title="R$ MM"),
            color=alt.Color(
                "bucket:N",
                title="Bucket",
                scale=alt.Scale(domain=_AGING_ABSOLUTE_BUCKETS, scheme="reds"),
                sort=_AGING_ABSOLUTE_BUCKETS,
            ),
            order=alt.Order("bucket_order:Q"),
            tooltip=[
                alt.Tooltip("comp_label:N", title="Competência"),
                alt.Tooltip("bucket:N", title="Bucket"),
                alt.Tooltip("valor_fmt:N", title="Valor"),
            ],
        )
        .properties(height=240, title="Aging — Vencidos por Bucket (R$ MM)")
        .configure_axis(labelFontSize=11, titleFontSize=12)
        .configure_legend(labelFontSize=11, titleFontSize=11, orient="bottom")
    )


def _render_single_fund_cards(item: dict[str, Any], latest: str | None) -> None:
    if not latest:
        return
    cards = [
        ("Última competência", _format_competencia_label(latest), "fundo selecionado"),
        ("PL", _format_metric_value(_metric_numeric(item, "PL (R$)", latest), "R$ bruto"), "Informe Mensal"),
        ("DC / PL", _format_metric_value(_metric_numeric(item, "Dir Cred / PL", latest), "ratio"), "alocação"),
        ("Over 90d", _format_metric_value(_metric_numeric(item, "Vencidos Over 90 d / Crédito", latest), "ratio"), "sobre crédito"),
        ("PDD / Over 90d", _format_metric_value(_metric_numeric(item, "PDD / Venc > 90 d", latest), "ratio"), "cobertura"),
    ]
    html = ["<div class='monitor-card-grid'>"]
    for label, value, note in cards:
        html.append(
            "<div class='monitor-kpi-card'>"
            f"<div class='monitor-kpi-label'>{escape(label)}</div>"
            f"<div class='monitor-kpi-value'>{escape(value)}</div>"
            f"<div class='monitor-kpi-note'>{escape(note)}</div>"
            "</div>"
        )
    html.append("</div>")
    st.markdown("\n".join(html), unsafe_allow_html=True)


def _render_fund_time_table_html(item: dict[str, Any]) -> str:
    tables: MonitoringTables = item["tables"]
    competencias = _competencias_desc(item.get("competencias") or [])
    if not competencias:
        return "<p class='monitor-caption'>Sem competências disponíveis.</p>"
    min_width = max(620 + 104 * len(competencias), 980)
    sections = _fund_time_table_sections(tables)
    html = [f"<div class='monitor-wide-wrapper' style='min-width: 100%; --monitor-table-min-width: {min_width}px;'>"]
    for section, rows in sections.items():
        html.append(f"<details class='monitor-wide-section' open style='min-width: {min_width}px;'>")
        html.append(f"<summary>{escape(section)}</summary>")
        html.append(f"<table class='monitor-wide-table' style='min-width: {min_width}px;'>")
        html.append("<colgroup><col style='width: 280px;'>")
        html.extend("<col style='width: 104px;'>" for _ in competencias)
        html.append("</colgroup><thead><tr><th class='label-col'>Nome</th>")
        for competencia in competencias:
            html.append(f"<th>{escape(_format_competencia_label(competencia))}</th>")
        html.append("</tr></thead><tbody>")
        for row in rows:
            row_class = "destaque" if row["metric"] in {"PL (R$)", "Vencidos Over 90 d / Crédito", "PDD / Venc > 90 d"} else ""
            html.append(f"<tr class='{row_class}'>")
            html.append(f"<td class='label'>{escape(str(row['label']))}</td>")
            for competencia in competencias:
                html.append(f"<td>{escape(_format_metric_value(row.get(competencia), str(row.get('unit') or '')))}</td>")
            html.append("</tr>")
        html.append("</tbody></table></details>")
    html.append("</div>")
    return "\n".join(html)


def _fund_time_table_sections(tables: MonitoringTables) -> dict[str, list[dict[str, object]]]:
    wanted = {
        "Tamanho e alocação": ["PL (R$)", "Dir Cred (R$ MM)", "Dir Cred / PL"],
        "Inadimplência": [
            "Vencidos <= 90 d (R$ MM)",
            "Vencidos > 90 d (R$ MM)",
            "Vencidos Total (R$ MM)",
            "Vencidos Over 30 d / Crédito",
            "Vencidos Over 60 d / Crédito",
            "Vencidos Over 90 d / Crédito",
            "Vencidos Over 180 d / Crédito",
            "Vencidos Over 360 d / Crédito",
        ],
        "PDD e recompras": ["PDD (R$ MM)", "PDD / Crédito", "PDD / Venc > 90 d", "PDD / Venc Total", "Recompras (R$ MM)", "Recompras / Crédito"],
        "Cotas e retorno": ["Cotas SR / PL %", "Cotas MZ / PL %", "Cotas Sub / PL %", "Rentabilidade SR % a.m.", "Rentabilidade MZ % a.m.", "Rentabilidade Sub % a.m."],
    }
    sections: dict[str, list[dict[str, object]]] = {}
    for section, labels in wanted.items():
        rows = []
        for label in labels:
            match = tables.indicators_df[tables.indicators_df["indicador"] == label]
            if match.empty:
                continue
            source = match.iloc[0].to_dict()
            source["label"] = _friendly_indicator_label(label)
            source["metric"] = label
            source["unit"] = source.get("unidade")
            rows.append(source)
        if rows:
            sections[section] = rows
    aging_rows = []
    for _, row in tables.aging_df.iterrows():
        if row.get("unidade") != "R$ MM":
            continue
        payload = row.to_dict()
        payload["label"] = payload.get("bucket")
        payload["metric"] = payload.get("bucket")
        payload["unit"] = payload.get("unidade")
        aging_rows.append(payload)
    if aging_rows:
        sections["Aging"] = aging_rows
    return sections


def _render_raw_data_tab(outputs: list[dict[str, Any]]) -> None:
    selected = _select_output(outputs, key="monitoring_raw_fund")
    if selected is None:
        return
    _render_raw_data_panel(selected, key_suffix="tab")


def _render_raw_data_panel(selected: dict[str, Any], *, key_suffix: str) -> None:
    raw_df = selected["tables"].raw_variables_df.copy()
    sections = raw_df["secao"].dropna().astype(str).drop_duplicates().tolist()
    selected_sections = st.multiselect(
        "Seções",
        options=sections,
        default=sections,
        key=f"monitoring_raw_sections::{key_suffix}",
    )
    if selected_sections:
        raw_df = raw_df[raw_df["secao"].isin(selected_sections)].copy()
    st.dataframe(_format_raw_frame(raw_df), hide_index=True, use_container_width=True)


def _render_overrides_tab(outputs: list[dict[str, Any]]) -> None:
    selected = _select_output(outputs, key="monitoring_override_fund")
    if selected is None:
        return
    cnpj = str(selected["cnpj"])
    competencias = list(selected.get("competencias") or [])
    payload = load_manual_overrides(cnpj)
    editor_df = pd.DataFrame(
        [
            {
                "competencia": competencia,
                "vl_total_mz": (payload.get("competencias") or {}).get(competencia, {}).get("vl_total_mz"),
                "rent_mz": (payload.get("competencias") or {}).get(competencia, {}).get("rent_mz"),
            }
            for competencia in competencias
        ]
    )
    st.caption("Preencha apenas fundos/competências com classe mezanino não capturada diretamente pelo IME.")
    edited = st.data_editor(
        editor_df,
        key=f"monitoring_overrides_editor::{cnpj}",
        hide_index=True,
        use_container_width=True,
        column_config={
            "competencia": st.column_config.TextColumn("Competência", disabled=True),
            "vl_total_mz": st.column_config.NumberColumn("Valor total MZ (R$)", format="%.2f"),
            "rent_mz": st.column_config.NumberColumn("Rentabilidade MZ (% a.m.)", format="%.2f"),
        },
    )
    if st.button("Salvar overrides", key=f"monitoring_save_overrides::{cnpj}"):
        save_manual_overrides(cnpj, {"competencias": _editor_to_override_payload(edited)})
        st.success("Overrides salvos. Recarregue o monitoramento para recalcular os quadros.")


def _comparison_long_df(outputs: list[dict[str, Any]], selected_id: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    unit = _unit_for_raw_variable(selected_id)
    for item in outputs:
        raw_df = item["tables"].raw_variables_df
        match = raw_df[raw_df["id_cvm"] == selected_id]
        if match.empty:
            continue
        row = match.iloc[0]
        for competencia in item.get("competencias") or []:
            value = pd.to_numeric(pd.Series([row.get(competencia)]), errors="coerce").iloc[0]
            if pd.isna(value):
                continue
            value_plot = float(value) / 1_000_000.0 if unit == "money" else float(value)
            rows.append(
                {
                    "fundo": item["display_name"],
                    "competencia": competencia,
                    "competencia_label": _format_competencia_label(competencia),
                    "valor_plot": value_plot,
                    "valor_fmt": _format_raw_value(value, selected_id),
                }
            )
    return pd.DataFrame(rows)


def _comparison_table(outputs: list[dict[str, Any]], selected_id: str) -> pd.DataFrame:
    rows = []
    for item in outputs:
        raw_df = item["tables"].raw_variables_df
        match = raw_df[raw_df["id_cvm"] == selected_id]
        if match.empty:
            continue
        source = match.iloc[0]
        row = {"Fundo": item["display_name"]}
        for competencia in item.get("competencias") or []:
            row[_format_competencia_label(competencia)] = _format_raw_value(source.get(competencia), selected_id)
        rows.append(row)
    return pd.DataFrame(rows)


def _format_raw_frame(frame: pd.DataFrame) -> pd.DataFrame:
    competencias = [column for column in frame.columns if isinstance(column, str) and column[:2].isdigit() and "/" in column]
    output = frame[["secao", "label", "id_cvm", "status"]].rename(
        columns={"secao": "Seção", "label": "Variável", "id_cvm": "ID CVM", "status": "Status"}
    ).copy()
    for competencia in competencias:
        output[_format_competencia_label(competencia)] = [
            _format_raw_value(value, id_cvm)
            for value, id_cvm in zip(frame[competencia].tolist(), frame["id_cvm"].tolist(), strict=False)
        ]
    return output


def _sparkline_from_indicator(frame: pd.DataFrame, indicator: str, title: str) -> alt.Chart:
    match = frame[frame["indicador"] == indicator]
    if match.empty:
        return alt.Chart(pd.DataFrame({"x": [], "y": []})).mark_line().properties(title=title, height=140)
    row = match.iloc[0]
    competencias = [column for column in frame.columns if isinstance(column, str) and column[:2].isdigit() and "/" in column]
    data = pd.DataFrame(
        {
            "competencia": [_format_competencia_label(competencia) for competencia in competencias],
            "valor": [pd.to_numeric(pd.Series([row.get(competencia)]), errors="coerce").iloc[0] for competencia in competencias],
        }
    ).dropna()
    if data.empty:
        return alt.Chart(pd.DataFrame({"competencia": [], "valor": []})).mark_line().properties(title=title, height=140)
    return (
        alt.Chart(data)
        .mark_line(point=True, color="#EC7000", strokeWidth=2.2)
        .encode(
            x=alt.X("competencia:N", title=None, sort=data["competencia"].tolist()),
            y=alt.Y("valor:Q", title=None),
            tooltip=["competencia:N", alt.Tooltip("valor:Q", title="Valor", format=",.2f")],
        )
        .properties(title=title, height=140)
    )


def _select_output(outputs: list[dict[str, Any]], *, key: str) -> dict[str, Any] | None:
    options = [item["cnpj"] for item in outputs]
    labels = {
        item["cnpj"]: str(item["display_name"])
        for item in outputs
    }
    selected = st.selectbox("Fundo", options=options, key=key, format_func=lambda value: labels.get(value, value))
    return next((item for item in outputs if item["cnpj"] == selected), None)


def _editor_to_override_payload(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    payload: dict[str, dict[str, float]] = {}
    for _, row in frame.iterrows():
        competencia = str(row.get("competencia") or "").strip()
        if not competencia:
            continue
        values = {}
        for key in ("vl_total_mz", "rent_mz"):
            parsed = pd.to_numeric(pd.Series([row.get(key)]), errors="coerce").iloc[0]
            if pd.notna(parsed):
                values[key] = float(parsed)
        if values:
            payload[competencia] = values
    return payload


def _build_cache_diagnostics_df(outputs: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for item in outputs:
        all_competencias = list(item.get("all_competencias") or [])
        display_competencias = list(item.get("competencias") or [])
        rows.append(
            {
                "Fundo": item.get("display_name"),
                "CNPJ": format_portfolio_cnpj(str(item.get("cnpj") or "")),
                "Cache IME": item.get("cache_status"),
                "Cache Monitoramento": item.get("derived_cache_status"),
                "Tempo (s)": item.get("load_seconds"),
                "Última comp.": _format_competencia_label(all_competencias[-1]) if all_competencias else "-",
                "Janela exibida": _format_competencia_span(display_competencias),
                "Fonte": item.get("metric_source") or "-",
                "Aviso": item.get("dashboard_error") or "-",
            }
        )
    return pd.DataFrame(rows)


def _aggregate_metric(metric: CockpitMetric, outputs: list[dict[str, Any]], competencia: str) -> object:
    if metric.aggregate == "none":
        return pd.NA
    if metric.aggregate == "sum":
        values = [_metric_numeric(item, metric.indicator, competencia) for item in outputs]
        total = _sum_numbers(values)
        return pd.NA if total is None else total
    if metric.aggregate == "dircred_pl":
        dircred = _sum_numbers([_metric_numeric(item, "Dir Cred (R$ MM)", competencia) for item in outputs])
        pl = _sum_numbers([_metric_numeric(item, "PL (R$)", competencia) for item in outputs])
        return _safe_ratio(dircred, (pl / 1_000_000.0) if pl is not None else None)
    if metric.aggregate.startswith("over") and metric.aggregate.endswith("_credito"):
        prefix = metric.aggregate.removesuffix("_credito").replace("over", "Vencidos Over ") + " d (R$ MM)"
        vencidos = _sum_numbers([_metric_numeric(item, prefix, competencia) for item in outputs])
        dircred = _sum_numbers([_metric_numeric(item, "Dir Cred (R$ MM)", competencia) for item in outputs])
        return _safe_ratio(vencidos, dircred)
    if metric.aggregate == "pdd_credito":
        pdd = _sum_numbers([_metric_numeric(item, "PDD (R$ MM)", competencia) for item in outputs])
        dircred = _sum_numbers([_metric_numeric(item, "Dir Cred (R$ MM)", competencia) for item in outputs])
        return _safe_ratio(pdd, dircred)
    if metric.aggregate == "pdd_over90":
        pdd = _sum_numbers([_metric_numeric(item, "PDD (R$ MM)", competencia) for item in outputs])
        over90 = _sum_numbers([_metric_numeric(item, "Vencidos Over 90 d (R$ MM)", competencia) for item in outputs])
        return _safe_ratio(pdd, over90)
    if metric.aggregate == "recompras_credito":
        recomp = _sum_numbers([_metric_numeric(item, "Recompras (R$ MM)", competencia) for item in outputs])
        dircred = _sum_numbers([_metric_numeric(item, "Dir Cred (R$ MM)", competencia) for item in outputs])
        return _safe_ratio(recomp, dircred)
    if metric.aggregate == "weighted_pl":
        weighted = 0.0
        weight_sum = 0.0
        for item in outputs:
            value = _metric_numeric(item, metric.indicator, competencia)
            pl = _metric_numeric(item, "PL (R$)", competencia)
            if value is None or pl is None:
                continue
            weighted += value * pl
            weight_sum += pl
        return pd.NA if weight_sum <= 0 else weighted / weight_sum
    return pd.NA


def _metric_numeric(item: dict[str, Any], indicator: str, competencia: str | None) -> float | None:
    if not competencia:
        return None
    tables: MonitoringTables = item["tables"]
    frame = tables.indicators_df
    if competencia not in frame.columns:
        return None
    match = frame[frame["indicador"] == indicator]
    if match.empty:
        return None
    value = pd.to_numeric(pd.Series([match.iloc[0].get(competencia)]), errors="coerce").iloc[0]
    if pd.isna(value):
        return None
    return float(value)


def _sum_numbers(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and pd.notna(value)]
    if not clean:
        return None
    return float(sum(clean))


def _safe_ratio(numerator: float | None, denominator: float | None) -> object:
    if numerator is None or denominator is None or denominator <= 0:
        return pd.NA
    return float(numerator) / float(denominator)


def _format_metric_value(value: object, unit: str) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "-"
    if unit == "R$ bruto":
        return _format_brl(float(numeric))
    if unit == "R$ MM":
        return f"R$ {_format_decimal(float(numeric), 1)} MM"
    if unit == "ratio":
        return f"{_format_decimal(float(numeric) * 100.0, 2)}%"
    if unit == "%":
        return f"{_format_decimal(float(numeric), 2)}%"
    return _format_decimal(float(numeric), 2)


def _format_raw_value(value: object, id_cvm: str) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "-"
    unit = _unit_for_raw_variable(id_cvm)
    if unit == "money":
        return f"R$ {_format_decimal(float(numeric) / 1_000_000.0, 1)} MM"
    if unit == "percent":
        return f"{_format_decimal(float(numeric), 2)}%"
    if unit == "count":
        return _format_decimal(float(numeric), 0)
    return _format_decimal(float(numeric), 2)


def _unit_for_raw_variable(id_cvm: str) -> str:
    if "/QT_" in id_cvm or id_cvm.startswith("QT_"):
        return "count"
    if "PR_" in id_cvm or "%" in id_cvm:
        return "percent"
    if "/VL_" in id_cvm or id_cvm.startswith("VL_"):
        return "money"
    return "number"


def _format_brl(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000_000:
        return f"R$ {_format_decimal(value / 1_000_000_000_000, 1)} bi"
    if abs_value >= 1_000_000:
        return f"R$ {_format_decimal(value / 1_000_000, 1)} MM"
    if abs_value >= 1_000:
        return f"R$ {_format_decimal(value / 1_000, 1)} mil"
    return f"R$ {_format_decimal(value, 0)}"


def _format_decimal(value: float, decimals: int) -> str:
    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_competencia_label(value: object) -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text[2] == "/":
        return f"{_PT_MONTH_ABBR.get(text[:2], text[:2])}/{text[-2:]}"
    return text


def _format_month_date_label(value: date) -> str:
    return f"{_PT_MONTH_ABBR.get(f'{value.month:02d}', f'{value.month:02d}')}/{str(value.year)[-2:]}"


def _format_period_label(period: ImePeriodSelection) -> str:
    return f"{_format_month_date_label(period.start_month)} → {_format_month_date_label(period.end_month)}"


def _format_competencia_span(competencias: list[str]) -> str:
    if not competencias:
        return "-"
    return f"{_format_competencia_label(competencias[0])} → {_format_competencia_label(competencias[-1])}"


def _portfolio_display_span(outputs: list[dict[str, Any]]) -> str:
    starts = []
    ends = []
    for item in outputs:
        competencias = list(item.get("competencias") or [])
        if not competencias:
            continue
        starts.append(parse_competencia_label(competencias[0]))
        ends.append(parse_competencia_label(competencias[-1]))
    if not starts or not ends:
        return "-"
    return f"{_format_month_date_label(min(starts))} → {_format_month_date_label(max(ends))}"


def _portfolio_latest_competencia(outputs: list[dict[str, Any]]) -> str | None:
    latest: tuple[date, str] | None = None
    for item in outputs:
        for competencia in item.get("competencias") or []:
            try:
                parsed = parse_competencia_label(competencia)
            except Exception:  # noqa: BLE001
                continue
            if latest is None or parsed > latest[0]:
                latest = (parsed, competencia)
    return latest[1] if latest else None


def _portfolio_reference_competencia(
    outputs: list[dict[str, Any]],
    *,
    min_coverage_pct: float = 0.8,
) -> tuple[str | None, int, int]:
    total = len([item for item in outputs if item.get("tables") is not None])
    if total <= 0:
        return None, 0, 0
    coverage: dict[str, int] = {}
    for item in outputs:
        competencias = {str(value) for value in (item.get("competencias") or []) if str(value or "").strip()}
        for competencia in competencias:
            coverage[competencia] = coverage.get(competencia, 0) + 1
    if not coverage:
        return None, 0, total
    required = max(1, math.ceil(total * min_coverage_pct))
    ordered = sorted(coverage, key=lambda value: parse_competencia_label(value), reverse=True)
    for competencia in ordered:
        if coverage.get(competencia, 0) >= required:
            return competencia, coverage.get(competencia, 0), total
    latest = ordered[0]
    return latest, coverage.get(latest, 0), total


def _latest_competencia(item: dict[str, Any]) -> str | None:
    competencias = list(item.get("competencias") or [])
    return competencias[-1] if competencias else None


def _competencias_desc(competencias: list[str]) -> list[str]:
    return sorted(competencias, key=lambda value: parse_competencia_label(value), reverse=True)


def _friendly_indicator_label(value: str) -> str:
    return {
        "Dir Cred (R$ MM)": "Direitos creditórios",
        "Dir Cred / PL": "Direitos creditórios / PL",
        "Vencidos <= 90 d / Crédito": "Vencidos <=90d / Crédito",
        "Vencidos > 90 d / Crédito": "Vencidos >90d / Crédito",
        "Vencidos Over 30 d / Crédito": "Over 30d / Crédito",
        "Vencidos Over 60 d / Crédito": "Over 60d / Crédito",
        "Vencidos Over 90 d / Crédito": "Over 90d / Crédito",
        "Vencidos Over 180 d / Crédito": "Over 180d / Crédito",
        "Vencidos Over 360 d / Crédito": "Over 360d / Crédito",
        "PDD / Venc > 90 d": "PDD / Over 90d",
        "PDD / Venc Total": "PDD / vencidos totais",
    }.get(value, value)


def _session_key(portfolio: PortfolioRecord, period: ImePeriodSelection, cache_months: int) -> str:
    return f"fidc_monitoring::{portfolio.id}::{period.cache_key}::{cache_months}"
