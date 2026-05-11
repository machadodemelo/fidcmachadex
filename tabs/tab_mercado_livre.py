from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from html import escape
import uuid
from typing import Any

import pandas as pd
import streamlit as st

from services.ime_period import (
    ImePeriodSelection,
    build_custom_period,
    build_preset_period,
    current_default_end_month,
    display_month_count_for_period,
    month_options,
    select_decembers_plus_current_year_months,
    shift_month,
)
from services.mercado_livre_dashboard import (
    build_consolidated_snapshot_excel_bytes,
    build_mercado_livre_outputs,
    build_validation_table,
    build_wide_table,
    cache_dir_for_outputs,
    extract_official_pl_history_from_wide_csv,
    load_outputs_from_cache,
    order_period_columns_desc,
    portfolio_identity_key,
    save_outputs_to_cache,
)
from services.meli_credit_monitor import MeliMonitorOutputs, build_meli_monitor_outputs
from services.meli_credit_research import build_meli_research_outputs
from services.meli_credit_research_verification import verify_meli_research_outputs
from services.somatorio_fidcs_ppt_export import build_somatorio_fidcs_pptx_bytes
from services.mercado_livre_visuals import npl_coverage_chart, pl_subordination_chart
from services.portfolio_store import PortfolioFund, PortfolioRecord, portfolio_basket_signature, portfolio_name_key
from tabs import tab_fidc_ime as ime_tab
from tabs.tab_dashboard_meli import _DASHBOARD_MELI_CSS, render_dashboard_meli_analysis
from tabs.ime_portfolio_support import (
    build_catalog_option_lookup,
    build_portfolio_record_label_lookup,
    build_portfolio_funds_from_cnpjs,
    delete_portfolio_record,
    enrich_portfolio_funds_with_catalog,
    get_portfolio_status_caption,
    list_saved_portfolios,
    load_fidc_catalog_cached,
    render_saved_portfolio_delete_manager,
    save_portfolio_record,
)
from tabs.tab_fidc_ime_carteira import (
    _build_loaded_dashboards_by_cnpj,
    _clear_portfolio_runtime_states,
    _execute_portfolio_load_for_funds,
    _get_portfolio_runtime_state,
)


SOMATORIO_FIDCS_TITLE = "Soma de FIDCs"
DISPLAY_WINDOW_FULL_OPTION = "Todo período carregado"
DISPLAY_WINDOW_DECEMBERS_OPTION = "Dezembros + Ano Atual"
DISPLAY_WINDOW_OPTIONS = (DISPLAY_WINDOW_FULL_OPTION, "6M", "12M", "24M", "36M", "YTD", DISPLAY_WINDOW_DECEMBERS_OPTION, "Customizado")
YOY_LOOKBACK_MONTHS = 12

_SOMATORIO_FIDCS_UI_CSS = """
<style>
.chart-title {
    color: #000000;
    font-size: clamp(16px, 1.45vw, 18px);
    font-weight: 600;
    line-height: 1.25;
    margin: 8px 0 4px 0;
}
.chart-subtitle {
    color: #8C8C8C;
    font-size: 12px;
    line-height: 1.25;
    margin: 0 0 8px 0;
}
.chart-note-list {
    color: #6f7a87;
    font-size: 12px;
    line-height: 1.35;
    margin: 0.1rem 0 0.7rem 0;
    padding-left: 1.05rem;
}
.chart-note-list li {
    margin: 0.08rem 0;
}
.somatorio-fidcs-period-bar {
    display: flex;
    flex-wrap: nowrap;
    gap: 6px;
    overflow-x: auto;
    padding-bottom: 4px;
    margin: 0 0 0.45rem 0;
    scrollbar-width: thin;
}
.somatorio-fidcs-period-bar span {
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
.somatorio-fidcs-period-bar strong {
    color: #212529;
    font-weight: 500;
}
.wide-table-wrapper {
    overflow-x: auto;
    overflow-y: visible;
    max-width: 100%;
    padding-bottom: 4px;
    margin-bottom: 10px;
}
.wide-section {
    margin: 0 0 8px 0;
}
.wide-section summary {
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
.wide-section summary::marker {
    color: #FFFFFF;
}
.wide-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    font-family: inherit;
    table-layout: fixed;
}
.wide-table th {
    text-align: right;
    padding: 6px 8px;
    border-bottom: 1px solid #3F3F3F;
    font-weight: 600;
    color: #000000;
    background: #FFFFFF;
    position: sticky;
    top: 0;
    z-index: 2;
    white-space: nowrap;
}
.wide-table th.label-col {
    text-align: left;
}
.wide-table th.formula-col {
    text-align: left;
    color: #8C8C8C;
}
.wide-table td {
    padding: 4px 8px;
    text-align: right;
    border-bottom: 1px solid #E5E5E5;
    color: #3F3F3F;
    line-height: 1.25;
    overflow-wrap: anywhere;
    vertical-align: top;
    white-space: normal;
    word-break: normal;
}
.wide-table td.label,
.wide-table td.formula {
    text-align: left;
}
.wide-table td.label {
    color: #000000;
    padding-left: 18px;
}
.wide-table td.formula {
    color: #8C8C8C;
    font-size: 11px;
}
.wide-table tr.destaque td {
    font-weight: 700;
    color: #000000;
}
.wide-table tr.variacao td {
    font-style: italic;
    color: #8C8C8C;
    font-size: 11px;
}
.wide-table tr:hover td {
    background: #F4F1EA;
}
</style>
"""


_MERCADO_LIVRE_UI_CSS = _SOMATORIO_FIDCS_UI_CSS + _DASHBOARD_MELI_CSS


def render_tab_somatorio_fidcs(period: ImePeriodSelection | None = None) -> None:
    st.markdown(ime_tab._FIDC_REPORT_CSS, unsafe_allow_html=True)
    st.markdown(_SOMATORIO_FIDCS_UI_CSS, unsafe_allow_html=True)
    st.markdown(_DASHBOARD_MELI_CSS, unsafe_allow_html=True)
    _apply_pending_selection()

    portfolios = list_saved_portfolios()
    catalog_df = load_fidc_catalog_cached()
    period = _render_somatorio_period_panel(period)
    calculation_period = _period_with_yoy_lookback(period)

    selected_portfolio = _render_selection_controls(portfolios=portfolios, catalog_df=catalog_df)
    if selected_portfolio is None:
        st.info(f"Crie ou selecione uma carteira para iniciar a auditoria {SOMATORIO_FIDCS_TITLE}.")
        return
    selected_portfolio = _enrich_portfolio_record(selected_portfolio=selected_portfolio, catalog_df=catalog_df)
    runtime_state = _get_portfolio_runtime_state(selected_portfolio=selected_portfolio, period=calculation_period)
    results = runtime_state.get("results") or {}
    cache_session_key = _outputs_session_key(selected_portfolio=selected_portfolio, period=calculation_period)

    if st.session_state.pop("_ml_load_requested", False):
        cached_outputs = load_outputs_from_cache(
            portfolio_id=selected_portfolio.id,
            period_key=calculation_period.cache_key,
            portfolio_funds=selected_portfolio.funds,
        )
        if cached_outputs is not None:
            cached_outputs = _tag_outputs_requested_period(
                cached_outputs,
                requested_period=period,
                calculation_period=calculation_period,
            )
            st.session_state[cache_session_key] = cached_outputs
            st.session_state[f"{cache_session_key}::source"] = "cache"
            st.toast("Base reutilizada do cache.")
            st.rerun()
        _execute_portfolio_load_for_funds(
            selected_portfolio=selected_portfolio,
            period=calculation_period,
            funds=tuple(selected_portfolio.funds),
            existing_results=None,
        )
        st.rerun()

    cached_session_outputs = st.session_state.get(cache_session_key)
    if cached_session_outputs is not None:
        cached_session_outputs = _tag_outputs_requested_period(
            cached_session_outputs,
            requested_period=period,
            calculation_period=calculation_period,
        )
        cache_dir = cache_dir_for_outputs(
            portfolio_id=selected_portfolio.id,
            period_key=calculation_period.cache_key,
            portfolio_funds=selected_portfolio.funds,
        )
        _render_outputs(
            outputs=cached_session_outputs,
            selected_portfolio=selected_portfolio,
            cache_dir=cache_dir,
            storage_source=str(st.session_state.get(f"{cache_session_key}::source") or "cache"),
        )
        return
    if not results:
        _render_status_bar(selected_portfolio=selected_portfolio, period=period, results=results)
        st.info("Carregue a carteira para começar.")
        return

    dashboards_by_cnpj, dashboard_errors = _build_loaded_dashboards_by_cnpj(
        selected_portfolio=selected_portfolio,
        results=results,
    )
    if dashboard_errors:
        with st.expander("Fundos sem dashboard base", expanded=False):
            for cnpj, message in dashboard_errors.items():
                st.caption(f"**{cnpj}** — {message}")
    if not dashboards_by_cnpj:
        _render_status_bar(selected_portfolio=selected_portfolio, period=period, results=results)
        st.warning(f"Nenhum fundo carregado com sucesso para montar a aba {SOMATORIO_FIDCS_TITLE}.")
        return
    official_pl_by_cnpj = _build_official_pl_by_cnpj(results=results, cnpjs=list(dashboards_by_cnpj))

    outputs = build_mercado_livre_outputs(
        portfolio_id=selected_portfolio.id,
        portfolio_name=selected_portfolio.name,
        dashboards_by_cnpj=dashboards_by_cnpj,
        period_label=period.label,
        official_pl_by_cnpj=official_pl_by_cnpj,
    )
    outputs = _tag_outputs_requested_period(
        outputs,
        requested_period=period,
        calculation_period=calculation_period,
    )
    cache_dir = save_outputs_to_cache(
        outputs,
        portfolio_id=selected_portfolio.id,
        period_key=calculation_period.cache_key,
        portfolio_funds=selected_portfolio.funds,
    )
    st.session_state[cache_session_key] = outputs
    st.session_state[f"{cache_session_key}::source"] = "recalculado"
    _render_outputs(
        outputs=outputs,
        selected_portfolio=selected_portfolio,
        cache_dir=cache_dir,
        storage_source="recalculado",
    )


render_tab_mercado_livre = render_tab_somatorio_fidcs


def _render_somatorio_period_panel(global_period: ImePeriodSelection | None = None) -> ImePeriodSelection:
    end_month = current_default_end_month()
    options = ("6M", "12M", "24M", "36M", "YTD", "Customizado")
    selected = st.radio(
        "Janela da Soma de FIDCs",
        options=options,
        index=options.index("12M"),
        horizontal=True,
        key="somatorio_fidcs_load_window",
        help="Use 24M/36M para YoY, roll rates e cohorts.",
    )
    if selected == "Customizado":
        max_options = month_options(end_month, months_back=119)
        default_start = global_period.start_month if global_period is not None else shift_month(end_month, -11)
        default_end = global_period.end_month if global_period is not None else end_month
        if default_start not in max_options:
            default_start = shift_month(end_month, -11)
        if default_end not in max_options:
            default_end = end_month
        start_index = max_options.index(default_start)
        end_candidates = [value for value in max_options if value >= default_start]
        if default_end not in end_candidates:
            default_end = end_candidates[-1]
        left, right = st.columns(2)
        with left:
            start_month = st.selectbox(
                "Competência inicial",
                options=max_options,
                index=start_index,
                key="somatorio_fidcs_period_start",
                format_func=_format_month_option_label,
            )
        end_candidates = [value for value in max_options if value >= start_month]
        with right:
            end_month_selected = st.selectbox(
                "Competência final",
                options=end_candidates,
                index=end_candidates.index(default_end) if default_end in end_candidates else len(end_candidates) - 1,
                key="somatorio_fidcs_period_end",
                format_func=_format_month_option_label,
            )
        period = build_custom_period(start_month=start_month, end_month=end_month_selected)
    elif selected == "YTD":
        period = build_custom_period(start_month=date(end_month.year, 1, 1), end_month=end_month)
    else:
        months = int(selected.removesuffix("M"))
        period = build_preset_period(end_month=end_month, months=months)
    st.caption(f"{_format_month_option_label(period.start_month)} → {_format_month_option_label(period.end_month)}")
    return period


def _period_with_yoy_lookback(period: ImePeriodSelection) -> ImePeriodSelection:
    return build_custom_period(
        start_month=shift_month(period.start_month, -YOY_LOOKBACK_MONTHS),
        end_month=period.end_month,
    )


def _tag_outputs_requested_period(outputs, *, requested_period: ImePeriodSelection, calculation_period: ImePeriodSelection):  # noqa: ANN001
    metadata = dict(getattr(outputs, "metadata", {}) or {})
    metadata.update(
        {
            "period_label": requested_period.label,
            "requested_period_label": requested_period.label,
            "requested_period_start": requested_period.start_month.isoformat(),
            "requested_period_end": requested_period.end_month.isoformat(),
            "requested_period_months": [
                value.isoformat()
                for value in _continuous_months(requested_period.start_month, requested_period.end_month)
            ],
            "requested_window_option": _window_option_for_period(requested_period),
            "calculation_period_label": calculation_period.label,
            "calculation_period_start": calculation_period.start_month.isoformat(),
            "calculation_period_end": calculation_period.end_month.isoformat(),
            "calculation_lookback_months": YOY_LOOKBACK_MONTHS,
        }
    )
    return replace(outputs, metadata=metadata)


def _window_option_for_period(period: ImePeriodSelection) -> str:
    if period.start_month == date(period.end_month.year, 1, 1):
        return "YTD"
    month_count = _month_count(period.start_month, period.end_month)
    option = f"{month_count}M"
    return option if option in DISPLAY_WINDOW_OPTIONS else "Customizado"


def _render_selection_controls(
    *,
    portfolios: list[PortfolioRecord],
    catalog_df: pd.DataFrame,
) -> PortfolioRecord | None:
    if not portfolios:
        st.session_state["ml_editor_open"] = True
        st.session_state["ml_editor_mode"] = "create"
        selected_portfolio = None
    else:
        try:
            sel_col, new_col, edit_col, load_col = st.columns([4.0, 1.45, 1.45, 1.35], vertical_alignment="bottom")
        except TypeError:
            sel_col, new_col, edit_col, load_col = st.columns([4.0, 1.45, 1.45, 1.35])
        with sel_col:
            selected_portfolio = _render_portfolio_selector(portfolios)
        with new_col:
            if st.button("Criar nova seleção", key="ml_portfolio_new_button", use_container_width=True):
                _reset_editor_state()
                st.session_state["ml_editor_mode"] = "create"
                st.session_state["ml_editor_open"] = True
                st.rerun()
        with edit_col:
            if st.button("Editar seleção atual", key="ml_portfolio_edit_button", use_container_width=True):
                st.session_state["ml_editor_mode"] = "edit"
                st.session_state["ml_editor_open"] = True
                st.rerun()
        with load_col:
            if st.button("Carregar carteira", key="ml_portfolio_load_button", type="secondary", use_container_width=True):
                st.session_state["_ml_load_requested"] = True
                st.rerun()

    st.caption(get_portfolio_status_caption())
    render_saved_portfolio_delete_manager(
        portfolios=portfolios,
        key_prefix="ml",
        selected_portfolio_id=selected_portfolio.id if selected_portfolio is not None else None,
        on_delete=_handle_deleted_portfolio,
    )
    if st.session_state.get("ml_editor_open", False):
        _render_portfolio_editor(
            portfolios=portfolios,
            catalog_df=catalog_df,
            selected_portfolio=selected_portfolio,
            editor_mode=str(st.session_state.get("ml_editor_mode") or "edit"),
        )
    return selected_portfolio


def _render_portfolio_selector(portfolios: list[PortfolioRecord]) -> PortfolioRecord | None:
    if not portfolios:
        return None
    options = [portfolio.id for portfolio in portfolios]
    labels = build_portfolio_record_label_lookup(portfolios)
    default_id = st.session_state.get("ml_portfolio_active_id")
    if default_id not in options:
        mercado = next((portfolio.id for portfolio in portfolios if portfolio.name.strip().lower() == "mercado livre"), None)
        default_id = mercado or options[0]
        st.session_state["ml_portfolio_active_id"] = default_id
    selected_id = st.selectbox(
        "Carteira salva",
        options=options,
        index=options.index(default_id),
        key="ml_portfolio_active_id",
        label_visibility="collapsed",
        format_func=lambda value: labels.get(value, value),
    )
    return next((portfolio for portfolio in portfolios if portfolio.id == selected_id), None)


def _render_portfolio_editor(
    *,
    portfolios: list[PortfolioRecord],
    catalog_df: pd.DataFrame,
    selected_portfolio: PortfolioRecord | None,
    editor_mode: str,
) -> None:
    target = selected_portfolio if editor_mode == "edit" and selected_portfolio is not None else None
    suffix = target.id if target is not None else "new"
    option_labels, option_lookup = build_catalog_option_lookup(catalog_df)
    catalog_cnpjs = {fund.cnpj for fund in option_lookup.values()}
    default_labels = [
        next((label for label, fund in option_lookup.items() if fund.cnpj == portfolio_fund.cnpj), portfolio_fund.display_name)
        for portfolio_fund in (target.funds if target is not None else ())
    ]
    st.markdown(f"**{'Criar nova seleção' if target is None else 'Editar seleção atual'}**")
    with st.form(f"ml_portfolio_editor_form::{suffix}", clear_on_submit=False):
        name = st.text_input(
            "Nome da seleção",
            value=target.name if target is not None else "",
            placeholder="Ex.: Soma de FIDCs",
            key=f"ml_portfolio_name::{suffix}",
        ).strip()
        selected_labels = st.multiselect(
            "Fundos",
            options=option_labels,
            default=default_labels,
            help="Até 20 FIDCs. Busca usa o cadastro público da CVM.",
            key=f"ml_portfolio_funds::{suffix}",
        ) if option_labels else []
        manual_cnpjs = st.text_area(
            "CNPJs adicionais",
            value="\n".join(
                fund.cnpj
                for fund in (target.funds if target is not None else ())
                if fund.cnpj not in catalog_cnpjs
            )
            if target is not None
            else "",
            placeholder="00.000.000/0000-00 (um por linha)",
            height=90,
            key=f"ml_portfolio_cnpjs::{suffix}",
        )
        cols = st.columns([1.2, 1.2, 3])
        save_clicked = cols[0].form_submit_button("Atualizar seleção" if target is not None else "Salvar nova seleção", type="primary")
        cancel_clicked = cols[1].form_submit_button("Cancelar")

    if cancel_clicked:
        st.session_state["ml_editor_open"] = False if portfolios else True
        _reset_editor_state()
        st.rerun()

    if save_clicked:
        if not name:
            st.warning("Informe um nome para a seleção.")
            return
        funds = [option_lookup[label] for label in selected_labels]
        funds.extend(build_portfolio_funds_from_cnpjs(manual_cnpjs.splitlines(), catalog_df))
        funds = enrich_portfolio_funds_with_catalog(funds, catalog_df)
        if not funds:
            st.warning("Selecione ao menos um fundo.")
            return
        existing = _resolve_existing_portfolio_for_save(
            portfolios=portfolios,
            target=target,
            name=name,
            funds=funds,
        )
        if existing.get("action") == "reuse":
            reused = existing["portfolio"]
            _queue_selection(reused.id)
            st.session_state["ml_editor_open"] = False
            _reset_editor_state()
            st.toast(f"A seleção '{reused.name}' já estava salva com a mesma composição. Reaproveitei a carteira existente.")
            st.rerun()
            return
        if existing.get("action") == "rename":
            conflict = existing["portfolio"]
            st.warning(
                f"Já existe uma seleção chamada '{conflict.name}', mas com outra composição. "
                "Use outro nome antes de salvar."
            )
            return
        try:
            stored = save_portfolio_record(
                PortfolioRecord(
                    id=target.id if target is not None else uuid.uuid4().hex,
                    name=name,
                    funds=tuple(funds),
                    created_at=target.created_at if target is not None else _utc_now_iso(),
                    updated_at=target.updated_at if target is not None else _utc_now_iso(),
                    notes=target.notes if target is not None else "",
                )
            )
        except ValueError as exc:
            st.warning(str(exc))
            return
        _queue_selection(stored.id)
        st.session_state["ml_editor_open"] = False
        _reset_editor_state()
        st.toast(f"Seleção '{stored.name}' salva ({len(stored.funds)} fundo(s)).")
        st.rerun()

    if target is not None:
        if st.button("Excluir seleção", key=f"ml_portfolio_delete_button::{target.id}"):
            delete_portfolio_record(target.id)
            st.session_state.pop("ml_portfolio_active_id", None)
            st.session_state["ml_editor_open"] = False if len(portfolios) > 1 else True
            _reset_editor_state()
            st.rerun()


def _render_status_bar(
    *,
    selected_portfolio: PortfolioRecord,
    period: ImePeriodSelection,
    results: dict[str, dict[str, Any]],
) -> None:
    ok = sum(1 for payload in results.values() if payload.get("result") is not None)
    total = len(selected_portfolio.funds)
    st.markdown(
        f"""
<div class="somatorio-fidcs-period-bar">
  <span><strong>Carteira:</strong> {escape(selected_portfolio.name)}</span>
  <span><strong>Período solicitado:</strong> {escape(period.label)}</span>
  <span><strong>Fundos carregados:</strong> {ok}/{total}</span>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_outputs(
    *,
    outputs,
    selected_portfolio: PortfolioRecord,
    cache_dir,
    storage_source: str,
) -> None:
    ok = len(outputs.fund_monthly)
    total = len(selected_portfolio.funds)
    requested_period = str(outputs.metadata.get("period_label") or _loaded_period_label(outputs))
    st.markdown(
        f"""
<div class="somatorio-fidcs-period-bar">
  <span><strong>{escape(selected_portfolio.name)}</strong></span>
  <span>{escape(requested_period)}</span>
  <span>{ok}/{total} fundos</span>
  <span>{escape(_loaded_period_label(outputs))}</span>
</div>
""",
        unsafe_allow_html=True,
    )
    _ = storage_source

    _render_somatorio_fidcs_guide()
    display_outputs = _render_loaded_period_window(outputs)
    monitor_outputs = _build_credit_monitor_for_display(outputs=outputs, display_outputs=display_outputs)
    research_outputs = build_meli_research_outputs(monitor_outputs)
    verification_report = verify_meli_research_outputs(monitor_outputs, research_outputs)
    file_token = _safe_file_token(selected_portfolio.name)

    base_tab, credit_tab = st.tabs(["Tabela Completa", "Análise Crédito"])

    with base_tab:
        snapshot_bytes = build_consolidated_snapshot_excel_bytes(display_outputs)
        pptx_bytes = build_somatorio_fidcs_pptx_bytes(
            outputs=display_outputs,
            monitor_outputs=monitor_outputs,
            research_outputs=research_outputs,
        )
        btn_left, btn_right = st.columns([1.65, 1.45])
        with btn_left:
            st.download_button(
                "Baixar resumo exibido + gráficos consolidados",
                data=snapshot_bytes,
                file_name=f"somatorio_fidcs_resumo_exibido_{_safe_file_token(selected_portfolio.name)}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"ml_snapshot_excel_download::{selected_portfolio.id}",
                use_container_width=True,
            )
        with btn_right:
            st.download_button(
                "Baixar PPT completo",
                data=pptx_bytes,
                file_name=f"somatorio_fidcs_completo_{file_token}.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key=f"ml_pptx_completo_download::{selected_portfolio.id}",
                use_container_width=True,
            )

        st.markdown("### Dados Consolidados – Soma de FIDCs")
        st.markdown(_render_wide_table_html(display_outputs.consolidated_wide), unsafe_allow_html=True)

        st.markdown("### Gráficos consolidados")
        _render_graph_definitions()
        left, right = st.columns(2)
        with left:
            _render_chart(
                "Evolução de PL e Subordinação",
                "PL consolidado em escala dinâmica; subordinação ex-360 no eixo direito.",
                pl_subordination_chart(display_outputs.consolidated_monthly),
            )
        with right:
            _render_chart(
                "NPL e Cobertura Ex-Vencidos > 360d",
                "Índices consolidados recalculados a partir das somas absolutas.",
                npl_coverage_chart(display_outputs.consolidated_monthly),
            )

        st.markdown("### Fundo individual")
        selected_fund_cnpj = _render_fund_selectbox(
            display_outputs,
            key=f"somatorio_fidcs_base_fund::{selected_portfolio.id}",
            label="Selecionar fundo",
        )
        selected_fund_cnpjs = [selected_fund_cnpj] if selected_fund_cnpj else []
        if not selected_fund_cnpjs:
            st.caption("Selecione um fundo para exibir tabela e gráficos individuais.")

        for cnpj in selected_fund_cnpjs:
            st.markdown(_render_wide_table_html(display_outputs.fund_wide[cnpj]), unsafe_allow_html=True)

        st.markdown("#### Gráficos do fundo selecionado")
        for cnpj in selected_fund_cnpjs:
            monthly_df = display_outputs.fund_monthly[cnpj]
            left, right = st.columns(2)
            with left:
                _render_chart(
                    "Evolução de PL e Subordinação",
                    "PL em escala dinâmica; subordinação ex-360 no eixo direito.",
                    pl_subordination_chart(monthly_df),
                )
            with right:
                _render_chart(
                    "NPL e Cobertura Ex-Vencidos > 360d",
                    "NPL Over 90d ex-360 e cobertura PDD ex-360 / NPL Over 90d ex-360.",
                    npl_coverage_chart(monthly_df),
                )

        _render_base_audit(display_outputs=display_outputs, cache_dir=cache_dir)

    with credit_tab:
        render_dashboard_meli_analysis(
            outputs=display_outputs,
            selected_portfolio=selected_portfolio,
            monitor_outputs=monitor_outputs,
            research_outputs=research_outputs,
            verification_report=verification_report,
            pptx_bytes=pptx_bytes,
            pptx_label="Baixar PPT completo",
            pptx_file_name=f"somatorio_fidcs_completo_{file_token}.pptx",
            excel_file_name=f"analise_credito_research_{file_token}.xlsx",
            download_key_prefix="somatorio_fidcs_credito",
            pptx_file_token=file_token,
        )


def _render_base_audit(*, display_outputs, cache_dir) -> None:  # noqa: ANN001
    with st.expander("Auditoria da base do Somatório", expanded=False):
        validation_df = build_validation_table(display_outputs)
        st.caption("Memória dos valores absolutos e percentuais derivados.")
        st.dataframe(_format_validation_for_display(validation_df), width="stretch", hide_index=True)
        _ = cache_dir
        if not display_outputs.warnings_df.empty:
            st.markdown("**Warnings da base**")
            st.dataframe(display_outputs.warnings_df, width="stretch", hide_index=True)


def _render_chart(title: str, subtitle: str, chart) -> None:
    st.markdown(f"<h4 class='chart-title'>{escape(title)}</h4>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f"<p class='chart-subtitle'>{escape(subtitle)}</p>", unsafe_allow_html=True)
    st.altair_chart(chart, width="stretch")


def _render_fund_selectbox(outputs, *, key: str, label: str) -> str | None:  # noqa: ANN001
    options = list(getattr(outputs, "fund_monthly", {}).keys())
    if not options:
        return None
    labels = {
        cnpj: f"{_fund_name_from_frame(frame, fallback=cnpj)} · {cnpj}"
        for cnpj, frame in outputs.fund_monthly.items()
    }
    selected = st.selectbox(
        label,
        options=options,
        index=0,
        key=key,
        format_func=lambda value: labels.get(value, str(value)),
        help="Selecione um fundo individual por vez. O consolidado permanece sempre visível.",
    )
    return selected if selected in outputs.fund_monthly else None


def _render_loaded_period_window(outputs):
    available = _available_competencia_months(outputs.consolidated_monthly)
    if not available:
        st.caption("Sem competências disponíveis.")
        return outputs

    loaded_start = available[0]
    loaded_end = available[-1]
    _reset_display_window_if_loaded_range_changed(
        outputs,
        loaded_start=loaded_start,
        loaded_end=loaded_end,
    )
    selected = st.radio(
        "Filtro visual (sem recarregar)",
        options=DISPLAY_WINDOW_OPTIONS,
        index=DISPLAY_WINDOW_OPTIONS.index(DISPLAY_WINDOW_FULL_OPTION),
        horizontal=True,
        key="somatorio_fidcs_display_window",
        help="Filtra a base já carregada.",
    )

    display_months = _display_window_months(
        selected=str(selected),
        available=available,
    )

    if selected == "Customizado":
        default_start = _clamp_month(shift_month(loaded_end, -11), loaded_start, loaded_end)
        left, right = st.columns(2)
        with left:
            start_month = st.selectbox(
                "Competência inicial exibida",
                options=available,
                index=available.index(default_start),
                key="somatorio_fidcs_display_start",
                format_func=_format_month_option_label,
            )
        end_candidates = [value for value in available if value >= start_month]
        with right:
            end_month = st.selectbox(
                "Competência final exibida",
                options=end_candidates,
                index=len(end_candidates) - 1,
                key="somatorio_fidcs_display_end",
                format_func=_format_month_option_label,
            )
        display_months = _continuous_months(start_month, end_month)

    if selected == DISPLAY_WINDOW_DECEMBERS_OPTION:
        missing_years = _missing_previous_decembers(available)
        if missing_years:
            missing = ", ".join(f"dez/{str(year)[-2:]}" for year in missing_years)
            st.caption(f"Sem dados para {missing}.")

    label = _display_months_label(display_months) if selected == DISPLAY_WINDOW_DECEMBERS_OPTION else _display_month_range_label(display_months)
    st.caption(f"{label} · {len(display_months)} competência(s)")
    return _filter_outputs_by_competencia_months(outputs, months=display_months, label=label, mode=str(selected))


def _reset_display_window_if_loaded_range_changed(outputs, *, loaded_start: date, loaded_end: date) -> None:  # noqa: ANN001
    range_key = f"{loaded_start.isoformat()}::{loaded_end.isoformat()}"
    state_key = "somatorio_fidcs_display_loaded_range"
    if st.session_state.get(state_key) == range_key:
        return
    st.session_state[state_key] = range_key
    default_window = _default_display_window_for_outputs(outputs)
    st.session_state["somatorio_fidcs_display_window"] = default_window
    if default_window == "Customizado":
        requested_start = _metadata_month(outputs, "requested_period_start")
        requested_end = _metadata_month(outputs, "requested_period_end")
        if requested_start is not None and requested_end is not None:
            st.session_state["somatorio_fidcs_display_start"] = requested_start
            st.session_state["somatorio_fidcs_display_end"] = requested_end


def _default_display_window_for_outputs(outputs) -> str:  # noqa: ANN001
    try:
        option = str(outputs.metadata.get("requested_window_option") or "")
    except AttributeError:
        return DISPLAY_WINDOW_FULL_OPTION
    return option if option in DISPLAY_WINDOW_OPTIONS else DISPLAY_WINDOW_FULL_OPTION


def _display_window_bounds(
    *,
    selected: str,
    loaded_start: date,
    loaded_end: date,
) -> tuple[date, date]:
    if selected == "YTD":
        return _clamp_month(date(loaded_end.year, 1, 1), loaded_start, loaded_end), loaded_end
    if selected in {DISPLAY_WINDOW_FULL_OPTION, "Customizado"}:
        return loaded_start, loaded_end
    months = int(selected.removesuffix("M"))
    display_months = display_month_count_for_period(build_preset_period(end_month=loaded_end, months=months))
    start_month = _clamp_month(shift_month(loaded_end, -(display_months - 1)), loaded_start, loaded_end)
    return start_month, loaded_end


def _display_window_months(*, selected: str, available: list[date]) -> list[date]:
    if not available:
        return []
    loaded_start = available[0]
    loaded_end = available[-1]
    if selected == DISPLAY_WINDOW_DECEMBERS_OPTION:
        return select_decembers_plus_current_year_months(available)
    start_month, end_month = _display_window_bounds(
        selected=selected,
        loaded_start=loaded_start,
        loaded_end=loaded_end,
    )
    return _continuous_months(start_month, end_month)


def _continuous_months(start_month: date, end_month: date) -> list[date]:
    values: list[date] = []
    current = start_month
    while current <= end_month:
        values.append(current)
        current = shift_month(current, 1)
    return values


def _display_months_label(months: list[date]) -> str:
    if not months:
        return "sem competências"
    if len(months) <= 4:
        return ", ".join(_format_month_option_label(value) for value in months)
    first_current_year_idx = next((idx for idx, value in enumerate(months) if value.year == months[-1].year), len(months))
    previous = ", ".join(_format_month_option_label(value) for value in months[:first_current_year_idx])
    current = f"{_format_month_option_label(months[first_current_year_idx])} → {_format_month_option_label(months[-1])}" if first_current_year_idx < len(months) else ""
    return " + ".join(part for part in [previous, current] if part)


def _display_month_range_label(months: list[date]) -> str:
    if not months:
        return "sem competências"
    return f"{_format_month_option_label(months[0])} → {_format_month_option_label(months[-1])}"


def _missing_previous_decembers(available: list[date]) -> list[int]:
    if not available:
        return []
    available_set = set(available)
    reference_year = available[-1].year
    return [
        year
        for year in range(available[0].year, reference_year)
        if any(value.year == year for value in available)
        and date(year, 12, 1) not in available_set
    ]


def _available_competencia_months(monthly_df: pd.DataFrame) -> list[date]:
    if monthly_df is None or monthly_df.empty:
        return []
    source = monthly_df.get("competencia_dt")
    if source is None:
        source = monthly_df.get("competencia")
    if source is None:
        return []
    parsed = _parse_month_series(source)
    values = sorted(
        {
            date(int(item.year), int(item.month), 1)
            for item in parsed.dropna()
        }
    )
    return values


def _filter_outputs_by_competencia(outputs, *, start_month: date, end_month: date):
    months = _continuous_months(start_month, end_month)
    return _filter_outputs_by_competencia_months(
        outputs,
        months=months,
        label=f"{_format_month_option_label(start_month)} a {_format_month_option_label(end_month)}",
        mode="intervalo",
    )


def _filter_outputs_by_competencia_months(outputs, *, months: list[date], label: str, mode: str):
    normalized_months = sorted({date(value.year, value.month, 1) for value in months})
    filtered_fund_monthly: dict[str, pd.DataFrame] = {}
    filtered_fund_wide: dict[str, pd.DataFrame] = {}
    for cnpj, frame in outputs.fund_monthly.items():
        filtered = _filter_monthly_frame_by_months(frame, months=normalized_months)
        filtered_fund_monthly[cnpj] = filtered
        filtered_fund_wide[cnpj] = build_wide_table(filtered, scope_name=_fund_name_from_frame(filtered, fallback=cnpj))

    consolidated = _filter_monthly_frame_by_months(outputs.consolidated_monthly, months=normalized_months)
    metadata = dict(outputs.metadata)
    start_month = normalized_months[0] if normalized_months else None
    end_month = normalized_months[-1] if normalized_months else None
    metadata.update(
        {
            "display_period_label": label,
            "display_period_mode": mode,
            "display_period_months": [value.isoformat() for value in normalized_months],
            "display_period_start": start_month.isoformat() if start_month else "",
            "display_period_end": end_month.isoformat() if end_month else "",
        }
    )
    return replace(
        outputs,
        fund_monthly=filtered_fund_monthly,
        fund_wide=filtered_fund_wide,
        consolidated_monthly=consolidated,
        consolidated_wide=build_wide_table(consolidated, scope_name=str(metadata.get("portfolio_name") or "Consolidado")),
        metadata=metadata,
    )


def _build_credit_monitor_for_display(*, outputs, display_outputs) -> MeliMonitorOutputs:  # noqa: ANN001
    full_monitor = build_meli_monitor_outputs(outputs)
    display_months = _metadata_months(display_outputs, "display_period_months")
    if display_months:
        return MeliMonitorOutputs(
            consolidated_monitor=_filter_monthly_frame_by_months(
                full_monitor.consolidated_monitor,
                months=display_months,
            ),
            fund_monitor={
                cnpj: _filter_monthly_frame_by_months(frame, months=display_months)
                for cnpj, frame in full_monitor.fund_monitor.items()
            },
            consolidated_cohorts=_filter_cohort_frame_by_months(
                full_monitor.consolidated_cohorts,
                months=display_months,
            ),
            fund_cohorts={
                cnpj: _filter_cohort_frame_by_months(frame, months=display_months)
                for cnpj, frame in full_monitor.fund_cohorts.items()
            },
            audit_table=_filter_monthly_frame_by_months(full_monitor.audit_table, months=display_months),
            pdf_reconciliation=full_monitor.pdf_reconciliation,
            warnings=full_monitor.warnings,
        )
    start_month = _metadata_month(display_outputs, "display_period_start")
    end_month = _metadata_month(display_outputs, "display_period_end")
    if start_month is None or end_month is None:
        return full_monitor
    return MeliMonitorOutputs(
        consolidated_monitor=_filter_monthly_frame(
            full_monitor.consolidated_monitor,
            start_month=start_month,
            end_month=end_month,
        ),
        fund_monitor={
            cnpj: _filter_monthly_frame(frame, start_month=start_month, end_month=end_month)
            for cnpj, frame in full_monitor.fund_monitor.items()
        },
        consolidated_cohorts=_filter_cohort_frame(
            full_monitor.consolidated_cohorts,
            start_month=start_month,
            end_month=end_month,
        ),
        fund_cohorts={
            cnpj: _filter_cohort_frame(frame, start_month=start_month, end_month=end_month)
            for cnpj, frame in full_monitor.fund_cohorts.items()
        },
        audit_table=_filter_monthly_frame(full_monitor.audit_table, start_month=start_month, end_month=end_month),
        pdf_reconciliation=full_monitor.pdf_reconciliation,
        warnings=full_monitor.warnings,
    )


def _metadata_month(outputs, key: str) -> date | None:  # noqa: ANN001
    try:
        value = outputs.metadata.get(key)
    except AttributeError:
        return None
    if not value:
        return None
    parsed = pd.to_datetime(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return date(int(parsed.year), int(parsed.month), 1)


def _metadata_months(outputs, key: str) -> list[date]:  # noqa: ANN001
    try:
        values = outputs.metadata.get(key) or []
    except AttributeError:
        return []
    if not isinstance(values, list):
        return []
    months: list[date] = []
    for value in values:
        parsed = pd.to_datetime(pd.Series([value]), errors="coerce").iloc[0]
        if pd.notna(parsed):
            months.append(date(int(parsed.year), int(parsed.month), 1))
    return sorted(set(months))


def _filter_cohort_frame(frame: pd.DataFrame, *, start_month: date, end_month: date) -> pd.DataFrame:
    return _filter_cohort_frame_by_months(frame, months=_continuous_months(start_month, end_month))


def _filter_cohort_frame_by_months(frame: pd.DataFrame, *, months: list[date]) -> pd.DataFrame:
    if frame is None or frame.empty or "cohort_dt" not in frame.columns:
        return pd.DataFrame() if frame is None else frame.copy()
    if not months:
        return frame.iloc[0:0].copy().reset_index(drop=True)
    output = frame.copy()
    parsed = _parse_month_series(output["cohort_dt"]).dt.to_period("M").dt.to_timestamp()
    allowed = {pd.Timestamp(value) for value in months}
    mask = parsed.isin(allowed)
    return output.loc[mask].reset_index(drop=True)


def _filter_monthly_frame(monthly_df: pd.DataFrame, *, start_month: date, end_month: date) -> pd.DataFrame:
    return _filter_monthly_frame_by_months(monthly_df, months=_continuous_months(start_month, end_month))


def _filter_monthly_frame_by_months(monthly_df: pd.DataFrame, *, months: list[date]) -> pd.DataFrame:
    if monthly_df is None or monthly_df.empty:
        return pd.DataFrame() if monthly_df is None else monthly_df.copy()
    if not months:
        return monthly_df.iloc[0:0].copy().reset_index(drop=True)
    output = monthly_df.copy()
    source = output.get("competencia_dt")
    if source is None:
        source = output.get("competencia")
    if source is None:
        return output
    parsed = _parse_month_series(source).dt.to_period("M").dt.to_timestamp()
    allowed = {pd.Timestamp(value) for value in months}
    mask = parsed.isin(allowed)
    return output.loc[mask].reset_index(drop=True)


def _parse_month_series(source) -> pd.Series:  # noqa: ANN001
    series = pd.Series(source)
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    parsed = pd.to_datetime(series.astype(str), format="%m/%Y", errors="coerce")
    missing = parsed.isna()
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(series.loc[missing], errors="coerce")
    return parsed


def _fund_name_from_frame(monthly_df: pd.DataFrame, *, fallback: str) -> str:
    if monthly_df is not None and not monthly_df.empty and "fund_name" in monthly_df.columns:
        value = str(monthly_df["fund_name"].iloc[0] or "").strip()
        if value:
            return value
    return fallback


def _clamp_month(value: date, minimum: date, maximum: date) -> date:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _month_count(start_month: date, end_month: date) -> int:
    return ((end_month.year - start_month.year) * 12) + (end_month.month - start_month.month) + 1


def _format_month_option_label(value: date) -> str:
    return ime_tab._format_month_option_label(value)


def _render_somatorio_fidcs_guide() -> None:
    with st.expander("Passo a passo de utilização e mecânica da aba", expanded=False):
        st.markdown(_build_somatorio_fidcs_guide_markdown())


def _build_somatorio_fidcs_guide_markdown() -> str:
    return """
### Como usar

1. Selecione ou crie uma carteira, escolha a janela e carregue a base.
2. Use **Tabela Completa** para conferir os dados consolidados e individuais.
3. Use **Análise Crédito** para carteira ex-360, crescimento, NPL, roll rates, cohorts e duration.
4. Use o filtro visual apenas para recortar a base já carregada.

### Mecânica essencial

- O consolidado soma valores absolutos por competência e recalcula percentuais; não há média simples de percentuais.
- Para YoY, a carga inclui meses anteriores necessários ao cálculo; o filtro visual decide o que aparece.
- NPL Over é acumulado: Over 90d soma todos os vencidos acima de 90 dias.
- A visão ex-360 remove vencidos acima de 360 dias da carteira, da PDD disponível e, se necessário, do PL.
- Warnings indicam limitações relevantes, como PL não reconciliado ou denominador indisponível.
"""


def _render_mercado_livre_guide() -> None:
    _render_somatorio_fidcs_guide()


def _build_mercado_livre_guide_markdown() -> str:
    return _build_somatorio_fidcs_guide_markdown()


def _render_wide_table_html(df_wide: pd.DataFrame) -> str:
    if df_wide.empty:
        return "<p class='chart-subtitle'>Sem dados para a Tabela Completa consolidada.</p>"
    period_columns = order_period_columns_desc(df_wide.columns)
    table_min_width = max(620 + 96 * len(period_columns), 920)
    colgroup = _wide_table_colgroup(period_columns)
    html: list[str] = []
    html.append(f"<div class='wide-table-wrapper' style='min-width: 100%; --wide-table-min-width: {table_min_width}px;'>")
    current_block = ""
    section_rows: list[pd.Series] = []

    def flush_section() -> None:
        if not current_block:
            return
        html.append(f"<details class='wide-section' style='min-width: {table_min_width}px;'>")
        html.append(f"<summary>{escape(_section_label(current_block))}</summary>")
        html.append(f"<table class='wide-table' style='min-width: {table_min_width}px;'>")
        html.append(colgroup)
        html.append("<thead><tr>")
        html.append("<th class='label-col'>Métrica</th>")
        for column in period_columns:
            html.append(f"<th>{escape(column)}</th>")
        html.append("<th class='formula-col'>Memória / fórmula</th>")
        html.append("</tr></thead><tbody>")
        for item in section_rows:
            metric = str(item.get("Métrica") or "").strip()
            formula = str(item.get("Memória / fórmula") or "").strip()
            row_class = _wide_table_metric_class(metric)
            html.append(f"<tr class='{row_class}'>")
            html.append(f"<td class='label'>{escape(metric)}</td>")
            for column in period_columns:
                html.append(f"<td>{escape(_dense_wide_value(item.get(column)))}</td>")
            html.append(f"<td class='formula'>{escape(_dense_wide_value(formula))}</td>")
            html.append("</tr>")
        html.append("</tbody></table></details>")

    for _, row in df_wide.iterrows():
        block = str(row.get("Bloco") or "").strip()
        if block and block != current_block:
            flush_section()
            current_block = block
            section_rows = []
        section_rows.append(row)
    flush_section()
    html.append("</div>")
    return "\n".join(html)


def _wide_table_colgroup(period_columns: list[str]) -> str:
    columns = ["<colgroup>", "<col class='label-col-width' style='width: 280px;'>"]
    columns.extend("<col class='period-col-width' style='width: 96px;'>" for _ in period_columns)
    columns.append("<col class='formula-col-width' style='width: 340px;'>")
    columns.append("</colgroup>")
    return "".join(columns)


def _section_label(block: str) -> str:
    parts = block.split(".", 1)
    if len(parts) == 2 and parts[0].strip().isdigit():
        return parts[1].strip()
    return block


def _wide_table_metric_class(metric: str) -> str:
    normalized = metric.lower()
    destaque_terms = (
        "pl fidc total",
        "carteira bruta total",
        "carteira líquida",
        "npl over 90d / carteira",
        "npl over 90d ex 360 / carteira ex 360",
        "pdd / npl over 90d",
        "pdd / npl over 90d ex 360",
        "% subordinação total",
        "% subordinação total ex over 360d",
        "carteira ex over 360d",
        "carteira líquida ex over 360d",
        "pl ex over 360d",
        "pdd ex over 360d",
    )
    if any(term in normalized for term in destaque_terms):
        return "destaque"
    if "(%)" in metric or " / " in metric or metric.startswith("%") or "reconciliação" in normalized:
        return "variacao"
    return "normal"


def _dense_wide_value(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.upper() == "N/D":
        return ""
    for prefix, suffix, decimals in (
        ("R$ bi ", " bi", 1),
        ("R$ mm ", " MM", 1),
        ("R$ mil ", " mil", 1),
    ):
        if text.startswith(prefix):
            parsed = _parse_br_number(text.removeprefix(prefix))
            return _format_br_number(parsed, decimals=decimals) + suffix if parsed is not None else text
    if text.startswith("R$ "):
        parsed = _parse_br_number(text.removeprefix("R$ "))
        if parsed is None:
            return text
        decimals = 0 if float(parsed).is_integer() else 1
        return _format_br_number(parsed, decimals=decimals)
    if text.endswith("%"):
        parsed = _parse_br_number(text[:-1])
        return f"{_format_br_number(parsed, decimals=1)}%" if parsed is not None else text
    return text


def _parse_br_number(value: str) -> float | None:
    try:
        normalized = value.strip().replace(".", "").replace(",", ".")
        return float(normalized)
    except (TypeError, ValueError):
        return None


def _format_br_number(value: float, *, decimals: int) -> str:
    formatted = f"{float(value):,.{decimals}f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def _render_graph_definitions() -> None:
    st.markdown(
        """
<ul class="chart-note-list">
  <li><strong>Evolução de PL e Subordinação:</strong> barras empilhadas mostram PL Sênior e Subordinada + Mez ex-360 em R$; a linha mostra subordinação ex-360.</li>
  <li><strong>Base ex-360:</strong> considera eventual baixa residual de Over 360 não coberta por PDD.</li>
  <li><strong>NPL e Cobertura:</strong> NPL usa Over 90d sem vencidos acima de 360 dias; cobertura usa PDD Ex Over 360d / NPL Over 90d Ex 360.</li>
</ul>
""",
        unsafe_allow_html=True,
    )


def _resolve_existing_portfolio_for_save(
    *,
    portfolios: list[PortfolioRecord],
    target: PortfolioRecord | None,
    name: str,
    funds: list[PortfolioFund],
) -> dict[str, Any]:
    target_id = target.id if target is not None else None
    requested_name_key = portfolio_name_key(name)
    requested_basket = portfolio_basket_signature(funds)
    same_basket = next(
        (
            portfolio
            for portfolio in portfolios
            if portfolio.id != target_id and portfolio_basket_signature(portfolio.funds) == requested_basket
        ),
        None,
    )
    if same_basket is not None:
        return {"action": "reuse", "portfolio": same_basket}
    same_name = next(
        (
            portfolio
            for portfolio in portfolios
            if portfolio.id != target_id and portfolio_name_key(portfolio.name) == requested_name_key
        ),
        None,
    )
    if same_name is not None:
        return {"action": "rename", "portfolio": same_name}
    return {"action": "save"}


def _outputs_session_key(*, selected_portfolio: PortfolioRecord, period: ImePeriodSelection) -> str:
    identity = portfolio_identity_key(selected_portfolio.funds, fallback=selected_portfolio.id)
    return f"ml_outputs::{identity}::{period.cache_key}"


def _build_official_pl_by_cnpj(
    *,
    results: dict[str, dict[str, Any]],
    cnpjs: list[str],
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for cnpj in cnpjs:
        payload = results.get(cnpj) or {}
        result = payload.get("result")
        wide_csv_path = getattr(result, "wide_csv_path", None)
        if wide_csv_path is None:
            continue
        frames[cnpj] = extract_official_pl_history_from_wide_csv(wide_csv_path)
    return frames


def _loaded_period_label(outputs) -> str:
    frame = outputs.consolidated_monthly
    if frame is None or frame.empty or "competencia" not in frame.columns:
        return "N/D"
    competencias = frame["competencia"].astype(str).tolist()
    return f"{ime_tab._format_competencia_label(competencias[0])} a {ime_tab._format_competencia_label(competencias[-1])}"


def _format_validation_for_display(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    output = df.copy()
    rename = {
        "fund_name": "Fundo",
        "cnpj": "CNPJ",
        "competencia": "Competência",
        "pl_total": "PL total",
        "pl_total_oficial": "PL oficial",
        "pl_total_classes": "PL soma classes",
        "pl_reconciliacao_delta": "Delta PL",
        "pl_senior": "PL sênior",
        "pl_subordinada_mezz": "Subordinada + Mez",
        "subordinacao_total_pct": "% Subordinação",
        "carteira_bruta": "Carteira",
        "pdd_total": "PDD",
        "npl_over90": "NPL Over 90d",
        "npl_over360": "Over 360d",
        "baixa_over360_carteira": "Baixa carteira >360",
        "baixa_over360_pdd": "Baixa PDD >360",
        "baixa_over360_pl": "Baixa PL >360",
        "npl_over90_ex360": "NPL 90 ex-360",
        "carteira_ex360": "Carteira ex-360",
        "pdd_ex360": "PDD ex-360",
        "pl_total_ex360": "PL ex-360",
        "pl_subordinada_mezz_ex360": "Sub+Mez ex-360",
        "subordinacao_total_ex360_pct": "% Subordinação ex-360",
        "pdd_npl_over90_pct": "PDD/NPL90",
        "pdd_npl_over90_ex360_pct": "PDD/NPL90 ex-360",
        "warnings": "Warnings",
    }
    for column in [
        "pl_total",
        "pl_total_oficial",
        "pl_total_classes",
        "pl_reconciliacao_delta",
        "pl_senior",
        "pl_subordinada_mezz",
        "carteira_bruta",
        "pdd_total",
        "npl_over90",
        "npl_over360",
        "baixa_over360_carteira",
        "baixa_over360_pdd",
        "baixa_over360_pl",
        "npl_over90_ex360",
        "carteira_ex360",
        "pdd_ex360",
        "pl_total_ex360",
        "pl_subordinada_mezz_ex360",
    ]:
        if column in output.columns:
            output[column] = output[column].map(_format_brl_compact)
    for column in [
        "subordinacao_total_pct",
        "subordinacao_total_ex360_pct",
        "pdd_npl_over90_pct",
        "pdd_npl_over90_ex360_pct",
    ]:
        if column in output.columns:
            output[column] = output[column].map(_format_percent)
    return output.rename(columns=rename)


def _format_brl_compact(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "N/D"
    if abs(float(numeric)) >= 1_000_000_000_000:
        return f"R$ {_format_decimal(float(numeric) / 1_000_000_000, 2)} bi"
    if abs(float(numeric)) >= 1_000_000:
        return f"R$ {_format_decimal(float(numeric) / 1_000_000, 1)} mm"
    if abs(float(numeric)) >= 1_000:
        return f"R$ {_format_decimal(float(numeric) / 1_000, 1)} mil"
    return f"R$ {_format_decimal(float(numeric), 2)}"


def _format_percent(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "N/D"
    return f"{_format_decimal(float(numeric), 2)}%"


def _format_decimal(value: float, decimals: int) -> str:
    return f"{value:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _enrich_portfolio_record(*, selected_portfolio: PortfolioRecord, catalog_df: pd.DataFrame) -> PortfolioRecord:
    return PortfolioRecord(
        id=selected_portfolio.id,
        name=selected_portfolio.name,
        funds=tuple(enrich_portfolio_funds_with_catalog(selected_portfolio.funds, catalog_df)),
        created_at=selected_portfolio.created_at,
        updated_at=selected_portfolio.updated_at,
        notes=selected_portfolio.notes,
    )


def _apply_pending_selection() -> None:
    pending = st.session_state.pop("_ml_portfolio_active_id_pending", None)
    if pending:
        st.session_state["ml_portfolio_active_id"] = pending


def _queue_selection(portfolio_id: str) -> None:
    st.session_state["_ml_portfolio_active_id_pending"] = portfolio_id


def _reset_editor_state() -> None:
    for key in ("ml_portfolio_name::new", "ml_portfolio_funds::new", "ml_portfolio_cnpjs::new"):
        st.session_state.pop(key, None)


def _handle_deleted_portfolio(portfolio_id: str) -> None:
    if st.session_state.get("ml_portfolio_active_id") == portfolio_id:
        st.session_state.pop("ml_portfolio_active_id", None)
    if st.session_state.get("_ml_portfolio_active_id_pending") == portfolio_id:
        st.session_state.pop("_ml_portfolio_active_id_pending", None)
    st.session_state["ml_editor_open"] = False
    _clear_portfolio_runtime_states(portfolio_id)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_file_token(value: object) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value or "").strip().lower()).strip("_") or "carteira"
