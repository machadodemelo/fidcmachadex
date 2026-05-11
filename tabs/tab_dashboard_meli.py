from __future__ import annotations

from datetime import date
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from services.ime_period import ImePeriodSelection, build_custom_period, current_default_end_month, month_options, shift_month
from services.meli_credit_monitor import (
    build_ex360_memory_table,
    build_meli_chart_axis_table,
    build_meli_methodology_table,
    build_meli_monitor_outputs,
    build_somatorio_dashboard_comparison,
    latest_row,
)
from services.meli_credit_monitor_ppt_export import build_dashboard_meli_pptx_bytes
from services.meli_credit_research import build_meli_research_outputs, build_research_excel_bytes
from services.meli_credit_research_verification import verify_meli_research_outputs
from services.meli_credit_monitor_visuals import (
    cohort_chart,
    duration_chart,
    npl_severity_chart,
    portfolio_growth_chart,
    research_roll_seasonality_chart,
    roll_rates_chart,
)
from services.mercado_livre_dashboard import (
    build_mercado_livre_outputs,
    extract_official_pl_history_from_wide_csv,
    load_outputs_from_cache,
    portfolio_identity_key,
    save_outputs_to_cache,
)
from services.portfolio_store import PortfolioRecord
from tabs import tab_fidc_ime as ime_tab
from tabs.ime_portfolio_support import (
    enrich_portfolio_funds_with_catalog,
    get_portfolio_status_caption,
    list_saved_portfolios,
    load_fidc_catalog_cached,
)
from tabs.tab_fidc_ime_carteira import (
    _build_loaded_dashboards_by_cnpj,
    _execute_portfolio_load_for_funds,
    _get_portfolio_runtime_state,
)


_DASHBOARD_MELI_CSS = """
<style>
.meli-kpi-grid {
    display: grid;
    grid-template-columns: repeat(6, minmax(120px, 1fr));
    gap: 8px;
    margin: 0.35rem 0 1rem 0;
}
.meli-kpi-card {
    border: 1px solid #E5E5E5;
    border-radius: 8px;
    padding: 9px 10px;
    background: #FFFFFF;
}
.meli-kpi-label {
    color: #6f7a87;
    font-size: 0.72rem;
    line-height: 1.2;
    margin-bottom: 4px;
}
.meli-kpi-value {
    color: #000000;
    font-size: 1.02rem;
    font-weight: 700;
    line-height: 1.2;
}
.meli-period-bar {
    display: flex;
    flex-wrap: nowrap;
    gap: 6px;
    overflow-x: auto;
    padding-bottom: 4px;
    margin: 0 0 0.6rem 0;
    scrollbar-width: thin;
}
.meli-period-bar span {
    align-items: center;
    background: #f8f9fa;
    border: 1px solid #eceff3;
    border-radius: 999px;
    color: #5a5a5a;
    display: inline-flex;
    flex: 0 0 auto;
    font-size: 0.72rem;
    gap: 4px;
    line-height: 1.2;
    padding: 4px 7px;
    white-space: nowrap;
}
.meli-period-bar strong {
    color: #212529;
    font-weight: 500;
}
.meli-chart-title {
    color: #000000;
    font-size: clamp(16px, 1.45vw, 18px);
    font-weight: 600;
    line-height: 1.25;
    margin: 8px 0 3px 0;
}
.meli-chart-subtitle {
    color: #8C8C8C;
    font-size: 12px;
    line-height: 1.35;
    margin: 0 0 8px 0;
}
@media (max-width: 1180px) {
    .meli-kpi-grid {
        grid-template-columns: repeat(3, minmax(120px, 1fr));
    }
}
@media (max-width: 760px) {
    .meli-kpi-grid {
        grid-template-columns: repeat(2, minmax(120px, 1fr));
    }
}
</style>
"""

ROLL_SEASONALITY_CHARTS: tuple[dict[str, str], ...] = (
    {
        "metric_id": "roll_61_90_m3",
        "title": "Roll 61-90 por mês do ano",
        "axis": "Eixo esquerdo: Roll 61-90 M-3 em %. Sem eixo direito; cada linha representa um ano-calendário.",
        "note": "Fórmula: atraso 61-90 no mês t ÷ carteira a vencer três meses antes. O gráfico mostra sazonalidade e compara anos na mesma janela mensal.",
    },
    {
        "metric_id": "roll_91_120_m4",
        "title": "Roll 91-120 por mês do ano",
        "axis": "Eixo esquerdo: Roll 91-120 M-4 em %. Sem eixo direito; cada linha representa um ano-calendário.",
        "note": "Fórmula: atraso 91-120 no mês t ÷ carteira a vencer quatro meses antes. A defasagem acompanha a maturação para atraso acima de 90 dias.",
    },
    {
        "metric_id": "roll_121_150_m5",
        "title": "Roll 121-150 por mês do ano",
        "axis": "Eixo esquerdo: Roll 121-150 M-5 em %. Sem eixo direito; cada linha representa um ano-calendário.",
        "note": "Fórmula: atraso 121-150 no mês t ÷ carteira a vencer cinco meses antes. A série mostra a migração intermediária antes do bucket 151-180.",
    },
    {
        "metric_id": "roll_151_180_m6",
        "title": "Roll 151-180 por mês do ano",
        "axis": "Eixo esquerdo: Roll 151-180 M-6 em %. Sem eixo direito; cada linha representa um ano-calendário.",
        "note": "Fórmula: atraso 151-180 no mês t ÷ carteira a vencer seis meses antes. A defasagem acompanha a maturação até atraso severo.",
    },
)


def render_tab_dashboard_meli(period: ImePeriodSelection | None = None) -> None:
    st.markdown(ime_tab._FIDC_REPORT_CSS, unsafe_allow_html=True)
    st.markdown(_DASHBOARD_MELI_CSS, unsafe_allow_html=True)

    portfolios = list_saved_portfolios()
    catalog_df = load_fidc_catalog_cached()
    selected_period = _render_period_panel(period)
    selected_portfolio = _render_portfolio_controls(portfolios)
    if selected_portfolio is None:
        st.info("Salve uma carteira na Soma de FIDCs para usar a Análise Crédito.")
        return
    selected_portfolio = _enrich_portfolio_record(selected_portfolio=selected_portfolio, catalog_df=catalog_df)
    runtime_state = _get_portfolio_runtime_state(selected_portfolio=selected_portfolio, period=selected_period)
    results = runtime_state.get("results") or {}
    session_key = _outputs_session_key(selected_portfolio=selected_portfolio, period=selected_period)

    if st.session_state.pop("_dashboard_meli_load_requested", False):
        cached_outputs = load_outputs_from_cache(
            portfolio_id=selected_portfolio.id,
            period_key=selected_period.cache_key,
            portfolio_funds=selected_portfolio.funds,
        )
        if cached_outputs is not None:
            st.session_state[session_key] = cached_outputs
            st.session_state[f"{session_key}::source"] = "cache"
            st.toast("Base da Análise Crédito reutilizada do storage.")
            st.rerun()
        _execute_portfolio_load_for_funds(
            selected_portfolio=selected_portfolio,
            period=selected_period,
            funds=tuple(selected_portfolio.funds),
            existing_results=None,
        )
        st.rerun()

    session_outputs = st.session_state.get(session_key)
    if session_outputs is not None:
        _render_outputs(
            outputs=session_outputs,
            selected_portfolio=selected_portfolio,
            period=selected_period,
            storage_source=str(st.session_state.get(f"{session_key}::source") or "cache"),
        )
        return

    if not results:
        _render_status_bar(selected_portfolio=selected_portfolio, period=selected_period, outputs=None, storage_source="não carregado")
        st.info("Clique em **Carregar análise** para montar as visões de crédito.")
        return

    dashboards_by_cnpj, dashboard_errors = _build_loaded_dashboards_by_cnpj(
        selected_portfolio=selected_portfolio,
        results=results,
    )
    if dashboard_errors:
        with st.expander("Fundos sem dashboard base", expanded=False):
            for cnpj, message in dashboard_errors.items():
                st.caption(f"**{cnpj}** - {message}")
    if not dashboards_by_cnpj:
        _render_status_bar(selected_portfolio=selected_portfolio, period=selected_period, outputs=None, storage_source="não carregado")
        st.warning("Nenhum fundo carregado com sucesso para montar a Análise Crédito.")
        return

    outputs = build_mercado_livre_outputs(
        portfolio_id=selected_portfolio.id,
        portfolio_name=selected_portfolio.name,
        dashboards_by_cnpj=dashboards_by_cnpj,
        period_label=selected_period.label,
        official_pl_by_cnpj=_build_official_pl_by_cnpj(results=results, cnpjs=list(dashboards_by_cnpj)),
    )
    save_outputs_to_cache(
        outputs,
        portfolio_id=selected_portfolio.id,
        period_key=selected_period.cache_key,
        portfolio_funds=selected_portfolio.funds,
    )
    st.session_state[session_key] = outputs
    st.session_state[f"{session_key}::source"] = "recalculado"
    _render_outputs(outputs=outputs, selected_portfolio=selected_portfolio, period=selected_period, storage_source="recalculado")


def _render_period_panel(global_period: ImePeriodSelection | None = None) -> ImePeriodSelection:
    end_month = current_default_end_month()
    options = ("12M", "24M", "36M", "YTD", "Customizado")
    selected = st.radio(
        "Janela da Análise Crédito",
        options=options,
        index=options.index("24M"),
        horizontal=True,
        key="dashboard_meli_load_window",
        help="Use 24M ou 36M para ler variação anual, roll rates e cohorts com mais contexto.",
    )
    if selected == "Customizado":
        max_options = month_options(end_month, months_back=119)
        default_start = global_period.start_month if global_period is not None else shift_month(end_month, -23)
        default_end = global_period.end_month if global_period is not None else end_month
        if default_start not in max_options:
            default_start = shift_month(end_month, -23)
        if default_end not in max_options:
            default_end = end_month
        left, right = st.columns(2)
        with left:
            start_month = st.selectbox(
                "Competência inicial",
                options=max_options,
                index=max_options.index(default_start),
                key="dashboard_meli_period_start",
                format_func=_format_month_label,
            )
        end_candidates = [value for value in max_options if value >= start_month]
        if default_end not in end_candidates:
            default_end = end_candidates[-1]
        with right:
            end_month_selected = st.selectbox(
                "Competência final",
                options=end_candidates,
                index=end_candidates.index(default_end),
                key="dashboard_meli_period_end",
                format_func=_format_month_label,
            )
        selected_period = build_custom_period(start_month=start_month, end_month=end_month_selected)
    elif selected == "YTD":
        selected_period = build_custom_period(start_month=date(end_month.year, 1, 1), end_month=end_month)
    else:
        months = int(selected.removesuffix("M"))
        selected_period = build_custom_period(start_month=shift_month(end_month, -(months - 1)), end_month=end_month)
    st.caption(f"{_format_month_label(selected_period.start_month)} → {_format_month_label(selected_period.end_month)}")
    return selected_period


def _render_portfolio_controls(portfolios: list[PortfolioRecord]) -> PortfolioRecord | None:
    if not portfolios:
        return None
    try:
        left, right = st.columns([5.0, 1.6], vertical_alignment="bottom")
    except TypeError:
        left, right = st.columns([5.0, 1.6])
    options = [portfolio.id for portfolio in portfolios]
    labels = {portfolio.id: f"{portfolio.name} · {len(portfolio.funds)} fundo(s)" for portfolio in portfolios}
    default_id = st.session_state.get("dashboard_meli_portfolio_active_id")
    if default_id not in options:
        preferred = next(
            (
                portfolio.id
                for portfolio in portfolios
                if "mercado" in portfolio.name.strip().lower() or "meli" in portfolio.name.strip().lower()
            ),
            None,
        )
        default_id = preferred or options[0]
        st.session_state["dashboard_meli_portfolio_active_id"] = default_id
    with left:
        selected_id = st.selectbox(
            "Carteira salva",
            options=options,
            index=options.index(default_id),
            key="dashboard_meli_portfolio_active_id",
            format_func=lambda value: labels.get(value, value),
        )
    with right:
        if st.button("Carregar análise", key="dashboard_meli_load_button", type="secondary", use_container_width=True):
            st.session_state["_dashboard_meli_load_requested"] = True
            st.rerun()
    st.caption(get_portfolio_status_caption())
    return next((portfolio for portfolio in portfolios if portfolio.id == selected_id), None)


def _render_outputs(*, outputs, selected_portfolio: PortfolioRecord, period: ImePeriodSelection, storage_source: str) -> None:  # noqa: ANN001
    _render_status_bar(selected_portfolio=selected_portfolio, period=period, outputs=outputs, storage_source=storage_source)
    render_dashboard_meli_analysis(
        outputs=outputs,
        selected_portfolio=selected_portfolio,
        download_key_prefix="dashboard_meli",
        pptx_file_token=_safe_file_token(selected_portfolio.name),
    )


def render_dashboard_meli_analysis(
    *,
    outputs,
    selected_portfolio: PortfolioRecord,
    monitor_outputs=None,
    research_outputs=None,
    verification_report: pd.DataFrame | None = None,
    pptx_bytes: bytes | None = None,
    pptx_label: str = "Baixar gráficos PPTX",
    pptx_file_name: str | None = None,
    excel_label: str = "Baixar base research Excel",
    excel_file_name: str | None = None,
    download_key_prefix: str = "dashboard_meli",
    pptx_file_token: str | None = None,
) -> None:  # noqa: ANN001
    """Renderiza a visão de crédito MELI a partir da base canônica já carregada."""
    if monitor_outputs is None:
        monitor_outputs = build_meli_monitor_outputs(outputs)
    if research_outputs is None:
        research_outputs = build_meli_research_outputs(monitor_outputs)
    if verification_report is None:
        verification_report = verify_meli_research_outputs(monitor_outputs, research_outputs)
    _render_guide()
    file_token = pptx_file_token or _safe_file_token(selected_portfolio.name)
    if pptx_bytes is None:
        pptx_bytes = build_dashboard_meli_pptx_bytes(monitor_outputs, research_outputs)
    excel_bytes = build_research_excel_bytes(research_outputs, verification_report)
    ppt_col, excel_col = st.columns(2)
    with ppt_col:
        st.download_button(
            pptx_label,
            data=pptx_bytes,
            file_name=pptx_file_name or f"analise_credito_graficos_{file_token}.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            key=f"{download_key_prefix}_pptx_download::{selected_portfolio.id}",
            use_container_width=True,
        )
    with excel_col:
        st.download_button(
            excel_label,
            data=excel_bytes,
            file_name=excel_file_name or f"analise_credito_research_{file_token}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{download_key_prefix}_research_xlsx_download::{selected_portfolio.id}",
            use_container_width=True,
        )
    _render_kpis(monitor_outputs.consolidated_monitor)
    main_tab, funds_tab, audit_tab = st.tabs(["Consolidado", "Fundos individuais", "Auditoria"])
    with main_tab:
        _render_consolidated_dashboard(monitor_outputs, research_outputs)
    with funds_tab:
        _render_fund_dashboards(monitor_outputs, selected_portfolio=selected_portfolio)
    with audit_tab:
        _render_audit(outputs, monitor_outputs, research_outputs, verification_report)
    _render_methodology(research_outputs)


def _render_consolidated_dashboard(monitor_outputs, research_outputs=None) -> None:  # noqa: ANN001
    _chart_title("Carteira ex-360 e crescimento YoY", "Carteira bruta menos vencidos acima de 360 dias; YoY contra o mesmo mês do ano anterior.")
    st.altair_chart(portfolio_growth_chart(monitor_outputs.consolidated_monitor), use_container_width=True)

    _chart_title("NPL ex-360 por severidade", "Eixo esquerdo: NPL 1-90d e 91-360d como % da carteira ex-360. Sem eixo direito.")
    _chart_note(
        "A carteira ex-360 remove vencidos acima de 360 dias do denominador; as barras separam o NPL remanescente entre atraso inicial (1-90d) e atraso maduro (91-360d)."
    )
    st.altair_chart(npl_severity_chart(monitor_outputs.consolidated_monitor), use_container_width=True)

    _chart_title(
        "Roll rates",
        "Eixo esquerdo: roll rate em %. Sem eixo direito. A defasagem segue o bucket: 61-90 M-3, 91-120 M-4, 121-150 M-5 e 151-180 M-6.",
    )
    st.altair_chart(roll_rates_chart(monitor_outputs.consolidated_monitor), use_container_width=True)

    _render_consolidated_research_charts(research_outputs)

    _chart_title("Duration por FIDC", "Eixo esquerdo: duration em meses. Sem eixo direito; consolidado ponderado por saldo.")
    _duration_notes()
    st.altair_chart(duration_chart(monitor_outputs.consolidated_monitor, monitor_outputs.fund_monitor), use_container_width=True)

    _chart_title("Cohorts recentes", "Eixo esquerdo: % do saldo a vencer em 30 dias. Sem eixo direito.")
    _cohort_notes()
    st.altair_chart(cohort_chart(monitor_outputs.consolidated_cohorts), use_container_width=True)


def _render_consolidated_research_charts(research_outputs) -> None:  # noqa: ANN001
    if research_outputs is None:
        return
    roll_df = _filter_research_scope(getattr(research_outputs, "roll_seasonality", pd.DataFrame()), "consolidado::")
    if roll_df.empty:
        return
    _render_research_roll_charts(roll_df)


def _render_research_roll_charts(roll_df: pd.DataFrame) -> None:
    for spec in ROLL_SEASONALITY_CHARTS:
        if roll_df[roll_df["metric_id"].eq(spec["metric_id"])].empty:
            continue
        _chart_title(spec["title"], spec["axis"])
        _chart_note(spec["note"])
        st.altair_chart(research_roll_seasonality_chart(roll_df, metric_id=spec["metric_id"]), use_container_width=True)


def _render_fund_dashboards(monitor_outputs, *, selected_portfolio: PortfolioRecord) -> None:  # noqa: ANN001
    if not monitor_outputs.fund_monitor:
        st.info("Sem fundos individuais carregados.")
        return
    selected_cnpj = _render_monitor_fund_selectbox(
        monitor_outputs,
        key=f"dashboard_meli_fund::{selected_portfolio.id}",
    )
    selected_cnpjs = [selected_cnpj] if selected_cnpj else []
    if not selected_cnpjs:
        st.caption("Selecione um fundo para exibir a análise individual.")
        return
    for cnpj in selected_cnpjs:
        monitor = monitor_outputs.fund_monitor[cnpj]
        name = str(monitor["fund_name"].dropna().iloc[0]) if not monitor.empty and "fund_name" in monitor.columns and monitor["fund_name"].notna().any() else cnpj
        st.markdown(f"#### {escape(name)} · {escape(str(cnpj))}")
        _chart_title("Carteira ex-360 e crescimento YoY", "Carteira bruta menos vencidos acima de 360 dias; YoY contra o mesmo mês do ano anterior.")
        st.altair_chart(portfolio_growth_chart(monitor), use_container_width=True)

        _chart_title("NPL ex-360 por severidade", "Eixo esquerdo: NPL 1-90d e 91-360d como % da carteira ex-360. Sem eixo direito.")
        _chart_note(
            "A carteira ex-360 remove vencidos acima de 360 dias do denominador; as barras separam o NPL remanescente entre atraso inicial (1-90d) e atraso maduro (91-360d)."
        )
        st.altair_chart(npl_severity_chart(monitor), use_container_width=True)

        _chart_title("Roll rates", "Eixo esquerdo: roll rate em %. Sem eixo direito; denominador é carteira a vencer defasada conforme o bucket.")
        st.altair_chart(roll_rates_chart(monitor), use_container_width=True)

        _chart_title("Duration", "Eixo esquerdo: duration em meses. Sem eixo direito.")
        _duration_notes()
        st.altair_chart(duration_chart(pd.DataFrame(), {cnpj: monitor}), use_container_width=True)

        _chart_title("Cohorts recentes", "Eixo esquerdo: % do saldo a vencer em 30 dias. Sem eixo direito.")
        _cohort_notes()
        st.altair_chart(cohort_chart(monitor_outputs.fund_cohorts.get(cnpj, pd.DataFrame())), use_container_width=True)


def _render_monitor_fund_selectbox(monitor_outputs, *, key: str) -> str | None:  # noqa: ANN001
    options = list(getattr(monitor_outputs, "fund_monitor", {}).keys())
    if not options:
        return None
    labels: dict[str, str] = {}
    for cnpj, frame in getattr(monitor_outputs, "fund_monitor", {}).items():
        name = str(frame["fund_name"].dropna().iloc[0]) if not frame.empty and "fund_name" in frame.columns and frame["fund_name"].notna().any() else str(cnpj)
        labels[cnpj] = f"{name} · {cnpj}"
    selected = st.selectbox(
        "Fundo exibido na Análise Crédito",
        options=options,
        index=0,
        key=key,
        format_func=lambda value: labels.get(value, str(value)),
        help="Selecione um fundo individual por vez. O consolidado fica na subaba própria.",
    )
    return selected if selected in monitor_outputs.fund_monitor else None


def _render_research_dashboard(research_outputs, verification_report: pd.DataFrame) -> None:  # noqa: ANN001
    scopes = _research_scope_options(research_outputs)
    if not scopes:
        st.info("Sem dados suficientes para montar a visão research.")
        return
    selected_scope = st.selectbox(
        "Escopo da visão research",
        options=list(scopes),
        format_func=lambda key: scopes.get(key, key),
        key="dashboard_meli_research_scope",
    )
    roll_df = _filter_research_scope(research_outputs.roll_seasonality, selected_scope)
    npl_table = _filter_research_scope(research_outputs.npl_research_table, selected_scope)
    portfolio_table = _filter_research_scope(research_outputs.portfolio_duration_table, selected_scope)
    verification = _filter_research_scope(verification_report, selected_scope)

    _render_research_roll_charts(roll_df)

    st.markdown("**Tabela NPL e carteira ex-360**")
    st.dataframe(_format_research_table(npl_table), use_container_width=True, hide_index=True)
    st.markdown("**Tabela carteira e duration**")
    st.dataframe(_format_research_table(portfolio_table), use_container_width=True, hide_index=True)
    _render_verification_summary(verification)


def _render_kpis(monitor_df: pd.DataFrame) -> None:
    row = latest_row(monitor_df)
    cards = _dashboard_kpi_cards(row)
    html = ["<div class='meli-kpi-grid'>"]
    for label, value in cards:
        html.append(
            f"<div class='meli-kpi-card'><div class='meli-kpi-label'>{escape(label)}</div><div class='meli-kpi-value'>{escape(value)}</div></div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def _dashboard_kpi_cards(row: pd.Series) -> list[tuple[str, str]]:
    cards = [
        ("Carteira ex-360", _format_brl_compact(row.get("carteira_ex360"))),
        ("NPL Over 1d ex-360", _format_percent(row.get("npl_over1_ex360_pct"))),
        ("NPL Over 30d ex-360", _format_percent(row.get("npl_over30_ex360_pct"))),
        ("NPL Over 60d ex-360", _format_percent(row.get("npl_over60_ex360_pct"))),
        ("NPL Over 90d ex-360", _format_percent(row.get("npl_over90_ex360_pct"))),
        ("Duration", f"{_format_decimal(row.get('duration_months'), 1)} meses"),
    ]
    return cards


def _render_audit(outputs, monitor_outputs, research_outputs=None, verification_report: pd.DataFrame | None = None) -> None:  # noqa: ANN001
    if monitor_outputs.warnings:
        with st.expander("Warnings do monitor", expanded=False):
            for warning in monitor_outputs.warnings:
                st.caption(warning)
    if research_outputs is not None and getattr(research_outputs, "warnings", None):
        with st.expander("Warnings da visão research", expanded=False):
            for warning in research_outputs.warnings:
                st.caption(warning)
    audit = monitor_outputs.audit_table.copy()
    if audit.empty:
        st.info("Sem tabela de auditoria.")
        return
    display = audit.copy()
    for column in [col for col in display.columns if col.endswith("_pct")]:
        display[column] = display[column].map(_format_percent)
    for column in [
        "carteira_bruta",
        "vencidos_360",
        "npl_over360",
        "baixa_over360_carteira",
        "carteira_ex360",
        "pdd_total",
        "baixa_over360_pdd",
        "pdd_ex360",
        "baixa_over360_pl",
        "pl_total",
        "pl_total_ex360",
        "carteira_a_vencer",
        "npl_1_90",
        "npl_91_360",
        "roll_61_90_m3_den",
        "roll_91_120_m4_den",
        "roll_121_150_m5_den",
        "roll_151_180_m6_den",
    ]:
        if column in display.columns:
            display[column] = display[column].map(_format_brl_compact)
    if "duration_months" in display.columns:
        display["duration_months"] = display["duration_months"].map(lambda value: f"{_format_decimal(value, 1)} meses")
    st.dataframe(display, use_container_width=True)
    if verification_report is not None and not verification_report.empty:
        st.markdown("**Verificação independente**")
        st.dataframe(_format_verification_table(verification_report), use_container_width=True, hide_index=True)
    comparison = build_somatorio_dashboard_comparison(outputs, monitor_outputs)
    if not comparison.empty:
        st.markdown("**Conciliação base x análise de crédito**")
        st.caption("Conferência entre base do Somatório e métricas derivadas.")
        st.dataframe(_format_somatorio_dashboard_comparison(comparison), use_container_width=True, hide_index=True)
    ex360_memory = build_ex360_memory_table(outputs)
    if not ex360_memory.empty:
        st.markdown("**Memória de cálculo da carteira ex-360**")
        st.caption("Carteira ex-360 = carteira bruta - NPL Over 360.")
        st.dataframe(_format_ex360_memory_table(ex360_memory), use_container_width=True, hide_index=True)


def _research_scope_options(research_outputs) -> dict[str, str]:  # noqa: ANN001
    frames = [
        getattr(research_outputs, "roll_seasonality", pd.DataFrame()),
        getattr(research_outputs, "cohort_research", pd.DataFrame()),
        getattr(research_outputs, "npl_research_table", pd.DataFrame()),
        getattr(research_outputs, "portfolio_duration_table", pd.DataFrame()),
    ]
    options: dict[str, str] = {}
    for frame in frames:
        if frame is None or frame.empty or "scope" not in frame.columns:
            continue
        for _, row in frame[["scope", "cnpj", "fund_name"]].drop_duplicates().iterrows():
            key = _research_scope_key(row.get("scope"), row.get("cnpj"))
            options[key] = str(row.get("fund_name") or key)
    if "consolidado::" in options:
        options = {"consolidado::": options["consolidado::"], **{key: value for key, value in options.items() if key != "consolidado::"}}
    return options


def _filter_research_scope(frame: pd.DataFrame, selected_scope: str) -> pd.DataFrame:
    if frame is None or frame.empty or "scope" not in frame.columns:
        return pd.DataFrame()
    scope, cnpj = selected_scope.split("::", 1) if "::" in selected_scope else (selected_scope, "")
    out = frame[frame["scope"].astype(str).eq(scope)].copy()
    if cnpj:
        out = out[out.get("cnpj", pd.Series(dtype="object")).astype(str).eq(cnpj)].copy()
    return out


def _research_scope_key(scope: object, cnpj: object) -> str:
    scope_text = str(scope or "")
    cnpj_text = "" if pd.isna(cnpj) else str(cnpj or "")
    return f"{scope_text}::{cnpj_text}"


def _format_research_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    cols = [
        "block",
        "metric_name",
        "competencia",
        "value",
        "unit",
        "mom_value",
        "yoy_value",
        "variation_unit",
        "numerator",
        "denominator",
        "formula",
    ]
    display = frame[[col for col in cols if col in frame.columns]].copy()
    for column in ["value", "mom_value", "yoy_value", "numerator", "denominator"]:
        if column in display.columns:
            display[column] = display[column].astype("object")
    for idx, row in display.iterrows():
        unit = str(row.get("unit") or "")
        variation_unit = str(row.get("variation_unit") or "")
        display.loc[idx, "value"] = _format_research_value(row.get("value"), unit=unit)
        if "mom_value" in display.columns:
            display.loc[idx, "mom_value"] = _format_research_value(row.get("mom_value"), unit=variation_unit)
        if "yoy_value" in display.columns:
            display.loc[idx, "yoy_value"] = _format_research_value(row.get("yoy_value"), unit=variation_unit)
        if "numerator" in display.columns:
            display.loc[idx, "numerator"] = _format_research_value(row.get("numerator"), unit="R$" if unit == "R$" else "")
        if "denominator" in display.columns:
            display.loc[idx, "denominator"] = _format_research_value(row.get("denominator"), unit="R$" if unit == "%" else "")
    return display.rename(
        columns={
            "block": "Bloco",
            "metric_name": "Métrica",
            "competencia": "Competência",
            "value": "Valor",
            "unit": "Unidade",
            "mom_value": "m/m",
            "yoy_value": "YoY",
            "variation_unit": "Unidade var.",
            "numerator": "Numerador",
            "denominator": "Denominador",
            "formula": "Fórmula",
        }
    )


def _format_verification_table(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    for column in ["calculated_value", "verified_value", "abs_diff"]:
        if column in display.columns:
            display[column] = display[column].map(lambda value: _format_decimal(value, 6) if pd.notna(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]) else "N/D")
    if "rel_diff_pct" in display.columns:
        display["rel_diff_pct"] = display["rel_diff_pct"].map(_format_percent)
    return display


def _format_somatorio_dashboard_comparison(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    for column in ["somatorio", "dashboard_meli", "diferenca_abs", "diferenca_rel_pct"]:
        if column in display.columns:
            display[column] = display[column].astype("object")
    for idx, row in display.iterrows():
        unit = str(row.get("unidade") or "")
        for column in ["somatorio", "dashboard_meli", "diferenca_abs"]:
            if column in display.columns:
                display.loc[idx, column] = _format_research_value(row.get(column), unit=unit)
        if "diferenca_rel_pct" in display.columns:
            display.loc[idx, "diferenca_rel_pct"] = _format_research_value(row.get("diferenca_rel_pct"), unit="%")
    return display.rename(
        columns={
            "escopo": "Escopo",
            "cnpj": "CNPJ",
            "competencia": "Competência",
            "metrica": "Métrica",
            "somatorio": "Soma de FIDCs",
            "dashboard_meli": "Análise Crédito",
            "diferenca_abs": "Diferença abs.",
            "diferenca_rel_pct": "Diferença rel.",
            "unidade": "Unidade",
            "status": "Status",
            "formula_somatorio": "Fórmula Somatório",
            "formula_dashboard": "Fórmula Dashboard",
        }
    )


def _format_ex360_memory_table(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    money_columns = [
        "carteira_bruta",
        "vencidos_360",
        "npl_over360",
        "baixa_over360_carteira",
        "carteira_ex360",
        "pdd_total",
        "baixa_over360_pdd",
        "pdd_ex360",
        "pl_total",
        "baixa_over360_pl",
        "pl_total_ex360",
    ]
    for column in money_columns:
        if column in display.columns:
            display[column] = display[column].astype("object")
            display[column] = display[column].map(_format_brl_compact)
    return display.rename(
        columns={
            "escopo": "Escopo",
            "cnpj": "CNPJ",
            "competencia": "Competência",
            "carteira_bruta": "Carteira bruta",
            "vencidos_360": "Vencidos > 360d",
            "npl_over360": "NPL Over 360d",
            "baixa_over360_carteira": "Baixa carteira > 360d",
            "carteira_ex360": "Carteira ex-360",
            "pdd_total": "PDD total",
            "baixa_over360_pdd": "Baixa PDD > 360d",
            "pdd_ex360": "PDD ex-360",
            "pl_total": "PL total",
            "baixa_over360_pl": "Baixa PL > 360d",
            "pl_total_ex360": "PL ex-360",
            "formula_carteira_ex360": "Fórmula carteira ex-360",
            "formula_pl_ex360": "Fórmula PL ex-360",
        }
    )


def _render_verification_summary(verification: pd.DataFrame) -> None:
    if verification is None or verification.empty:
        st.info("Sem relatório de verificação independente para este escopo.")
        return
    counts = verification["status"].value_counts(dropna=False).to_dict() if "status" in verification.columns else {}
    status_text = " · ".join(f"{key}: {value}" for key, value in counts.items()) or "Sem status"
    if counts.get("ERRO", 0):
        st.error(f"Verificação independente: {status_text}")
    elif counts.get("ALERTA", 0):
        st.warning(f"Verificação independente: {status_text}")
    else:
        st.success(f"Verificação independente: {status_text}")


def _format_research_value(value: object, *, unit: str) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "N/D"
    if unit == "R$":
        return _format_brl_compact(float(numeric))
    if unit in {"%", "p.p."}:
        suffix = "p.p." if unit == "p.p." else "%"
        return f"{_format_decimal(float(numeric), 1)}{suffix}"
    if unit == "meses":
        return f"{_format_decimal(float(numeric), 1)} meses"
    return _format_decimal(float(numeric), 1)


def _render_methodology(research_outputs=None) -> None:  # noqa: ANN001
    with st.expander("Metodologia, fórmulas e fontes dos indicadores", expanded=False):
        st.markdown(
            """
O consolidado soma valores absolutos por competência e recalcula percentuais; não há média simples de percentuais.

**Ex-360:** remove vencidos acima de 360 dias da carteira. NPL por severidade usa `NPL 1-90d / carteira ex-360` e `NPL 91-360d / carteira ex-360`.

**Roll rates:** medem migração de risco. A defasagem acompanha o bucket: `61-90 M-3`, `91-120 M-4`, `121-150 M-5` e `151-180 M-6`.

**YoY:** compara a competência atual com o mesmo mês do ano anterior.

**Duration:** `duration_dias = Σ(saldo_bucket × prazo_proxy_bucket) / Σ(saldo_bucket)`. O gráfico mostra `duration_meses = duration_dias / 30,4375`. Exemplo: bucket 61-90 dias usa `75,5` dias, o ponto médio da faixa.

**Cohorts:** cada linha é uma safra proxy definida pelo saldo que estava a vencer em até 30 dias no mês-base. Esse saldo é o denominador fixo da linha.

Exemplo: se em fev/26 havia R$ 100 milhões a vencer em até 30 dias, a linha `Fev-26` usa R$ 100 milhões como base. `M1` é mar/26, `M2` é abr/26, `M3` é mai/26. Se mar/26 tem R$ 39,6 milhões em atraso até 30 dias, `M1 = 39,6 / 100 = 39,6%`.

`M1 = atraso até 30d no mês seguinte / base`; `M2 = atraso 31-60d dois meses depois / base`; `M3 = atraso 61-90d três meses depois / base`; `M4`, `M5` e `M6` seguem a mesma lógica para 91-120d, 121-150d e 151-180d.
            """
        )
        st.markdown("**Eixos dos gráficos**")
        st.dataframe(build_meli_chart_axis_table(), use_container_width=True, hide_index=True)
        st.markdown("**Fórmulas e fontes das métricas**")
        st.dataframe(build_meli_methodology_table(), use_container_width=True, hide_index=True)
        if research_outputs is not None and getattr(research_outputs, "methodology", pd.DataFrame()).empty is False:
            st.markdown("**Métricas complementares do consolidado: fórmulas e fontes**")
            st.dataframe(research_outputs.methodology, use_container_width=True, hide_index=True)


def _render_status_bar(*, selected_portfolio: PortfolioRecord, period: ImePeriodSelection, outputs, storage_source: str) -> None:  # noqa: ANN001
    if outputs is not None and getattr(outputs, "consolidated_monthly", pd.DataFrame()).empty is False:
        loaded = _loaded_period_label(outputs)
        ok = len(outputs.fund_monthly)
    else:
        loaded = "N/D"
        ok = 0
    total = len(selected_portfolio.funds)
    st.markdown(
        f"""
<div class="meli-period-bar">
  <span><strong>{escape(selected_portfolio.name)}</strong></span>
  <span>{escape(period.label)}</span>
  <span>{ok}/{total} fundos</span>
  <span>{escape(loaded)}</span>
</div>
""",
        unsafe_allow_html=True,
    )
    _ = storage_source


def _render_guide() -> None:
    with st.expander("Como usar e interpretar a Análise Crédito", expanded=False):
        st.markdown(
            """
1. Use 24M ou 36M para ler YoY, roll rates e cohorts com contexto.
2. Comece por carteira ex-360, crescimento e NPL; depois leia roll rates, duration e cohorts.
3. No consolidado, percentuais são recalculados a partir da soma dos numeradores e denominadores.
            """
        )


def _chart_title(title: str, subtitle: str) -> None:
    st.markdown(f"<div class='meli-chart-title'>{escape(title)}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='meli-chart-subtitle'>{escape(subtitle)}</div>", unsafe_allow_html=True)


def _chart_note(text: str) -> None:
    st.markdown(f"<div class='meli-chart-subtitle'>{escape(text)}</div>", unsafe_allow_html=True)


def _cohort_notes() -> None:
    notes = [
        "Cada linha é uma safra proxy: a base fixa é o saldo que estava a vencer em até 30 dias no mês-base da safra.",
        "Se a linha Fev-26 mostra 39,6% em M1, leia assim: M1 é Mar-26 e o valor é atraso até 30d em Mar-26 dividido pelo saldo que estava a vencer em até 30d em Fev-26.",
        "M1 = mês seguinte à safra, usando atraso até 30d; M2 = dois meses depois, usando atraso 31-60d; M3 = três meses depois, usando atraso 61-90d.",
        "M4 = quatro meses depois, usando atraso 91-120d; M5 = cinco meses depois, usando atraso 121-150d; M6 = seis meses depois, usando atraso 151-180d.",
        "Exemplo: se Fev-26 tinha R$ 100 milhões a vencer em até 30 dias e Mar-26 tem R$ 39,6 milhões em atraso até 30d, M1 = 39,6 / 100 = 39,6%.",
        "M1, M2, M3... são meses de maturação depois da safra, não meses fixos do calendário; compare sempre o mesmo M entre safras.",
        "Linha mais alta no mesmo M indica pior deterioração relativa daquela safra.",
    ]
    for note in notes:
        _chart_note(note)


def _duration_notes() -> None:
    notes = [
        "Fórmula: duration_dias = Σ(saldo de cada faixa de vencimento × prazo proxy da faixa) ÷ Σ(saldos das faixas).",
        "O gráfico mostra duration_meses = duration_dias ÷ 30,4375; 30,4375 = 365,25 ÷ 12, a média de dias por mês em um ano com ajuste bissexto.",
        "Exemplo: um crédito a vencer entre 61 e 90 dias usa 75,5 dias como prazo proxy, que é o ponto médio (61 + 90) ÷ 2.",
    ]
    for note in notes:
        _chart_note(note)


def _outputs_session_key(*, selected_portfolio: PortfolioRecord, period: ImePeriodSelection) -> str:
    identity = portfolio_identity_key(selected_portfolio.funds, fallback=selected_portfolio.id)
    return f"dashboard_meli_outputs::{identity}::{period.cache_key}"


def _build_official_pl_by_cnpj(*, results: dict[str, dict[str, Any]], cnpjs: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for cnpj in cnpjs:
        payload = results.get(cnpj) or {}
        result = payload.get("result")
        wide_csv_path = getattr(result, "wide_csv_path", None)
        if wide_csv_path is None:
            continue
        frames[cnpj] = extract_official_pl_history_from_wide_csv(wide_csv_path)
    return frames


def _enrich_portfolio_record(*, selected_portfolio: PortfolioRecord, catalog_df: pd.DataFrame) -> PortfolioRecord:
    return PortfolioRecord(
        id=selected_portfolio.id,
        name=selected_portfolio.name,
        funds=tuple(enrich_portfolio_funds_with_catalog(selected_portfolio.funds, catalog_df)),
        created_at=selected_portfolio.created_at,
        updated_at=selected_portfolio.updated_at,
        notes=selected_portfolio.notes,
    )


def _loaded_period_label(outputs) -> str:  # noqa: ANN001
    frame = outputs.consolidated_monthly
    if frame is None or frame.empty or "competencia" not in frame.columns:
        return "N/D"
    competencias = frame["competencia"].astype(str).tolist()
    return f"{ime_tab._format_competencia_label(competencias[0])} a {ime_tab._format_competencia_label(competencias[-1])}"


def _format_month_label(value: date) -> str:
    return ime_tab._format_competencia_label(f"{value.month:02d}/{value.year}")


def _format_brl_compact(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "N/D"
    number = float(numeric)
    if abs(number) >= 1_000_000_000_000:
        return f"R$ {_format_decimal(number / 1_000_000_000, 1)} bi"
    if abs(number) >= 1_000_000:
        return f"R$ {_format_decimal(number / 1_000_000, 1)} mm"
    if abs(number) >= 1_000:
        return f"R$ {_format_decimal(number / 1_000, 1)} mil"
    return f"R$ {_format_decimal(number, 2)}"


def _format_percent(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "N/D"
    return f"{_format_decimal(float(numeric), 1)}%"


def _safe_file_token(value: object) -> str:
    text = str(value or "analise_credito").strip().lower()
    token = "".join(char if char.isalnum() else "_" for char in text)
    token = "_".join(part for part in token.split("_") if part)
    return token or "analise_credito"


def _format_decimal(value: object, decimals: int) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "N/D"
    return f"{float(numeric):,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")
