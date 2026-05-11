from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from services.fidc_monitoring import build_risk_metrics_df
from services.fundonet_dashboard import FundonetDashboardData
from services import fundonet_dashboard as single


_VALID_SOURCE_STATUSES = {"reported_value", "reported_zero"}
_EVENT_ORDER = ["emissao", "resgate", "resgate_solicitado", "amortizacao"]
_LIQUIDITY_BUCKETS = [
    ("Liquidez imediata", "liquidez_imediata"),
    ("Até 30 dias", "liquidez_30"),
    ("Até 60 dias", "liquidez_60"),
    ("Até 90 dias", "liquidez_90"),
    ("Até 180 dias", "liquidez_180"),
    ("Até 360 dias", "liquidez_360"),
    ("Acima de 360 dias", "liquidez_mais_360"),
]
_MATURITY_BUCKET_ORDER = {
    "Vencidos": 1,
    "Em 30 dias": 2,
    "31 a 60 dias": 3,
    "61 a 90 dias": 4,
    "91 a 120 dias": 5,
    "121 a 150 dias": 6,
    "151 a 180 dias": 7,
    "181 a 360 dias": 8,
    "361 a 720 dias": 9,
    "721 a 1080 dias": 10,
    "Acima de 1080 dias": 11,
}
_AGING_BUCKET_ORDER = {
    "Até 30 dias": 1,
    "31 a 60 dias": 2,
    "61 a 90 dias": 3,
    "91 a 120 dias": 4,
    "121 a 150 dias": 5,
    "151 a 180 dias": 6,
    "181 a 360 dias": 7,
    "361 a 720 dias": 8,
    "721 a 1080 dias": 9,
    "Acima de 1080 dias": 10,
}
_QUOTA_MACRO_ORDER = {
    "Sênior": 1,
    "Mezzanino": 2,
    "Subordinada": 3,
}


@dataclass(frozen=True)
class PortfolioDashboardBundle:
    dashboard: FundonetDashboardData
    fund_scope_df: pd.DataFrame
    coverage_df: pd.DataFrame
    reconciliation_df: pd.DataFrame
    temporal_rule: str


def build_portfolio_dashboard_bundle(
    *,
    portfolio_name: str,
    dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]],
) -> PortfolioDashboardBundle:
    if not dashboards_by_cnpj:
        raise ValueError("Nenhum fundo carregado para montar a visão agregada da carteira.")

    fund_scope_df = _build_fund_scope_df(dashboards_by_cnpj)
    common_competencias = _common_competencias(dashboards_by_cnpj)
    if not common_competencias:
        raise ValueError("Os fundos carregados não compartilham nenhuma competência em comum.")

    latest_competencia = common_competencias[-1]
    coverage_rows: list[dict[str, object]] = []

    dc_canonical_history_df = _aggregate_dc_canonical_history(
        dashboards_by_cnpj=dashboards_by_cnpj,
        competencias=common_competencias,
        coverage_rows=coverage_rows,
    )
    subordination_history_df = _aggregate_subordination_history(
        dashboards_by_cnpj=dashboards_by_cnpj,
        competencias=common_competencias,
        coverage_rows=coverage_rows,
    )
    quota_pl_history_df = _build_portfolio_quota_history(subordination_history_df)
    asset_history_df = _aggregate_asset_history(
        dashboards_by_cnpj=dashboards_by_cnpj,
        competencias=common_competencias,
        dc_canonical_history_df=dc_canonical_history_df,
        coverage_rows=coverage_rows,
    )
    liquidity_history_df = _aggregate_scalar_history(
        dashboards_by_cnpj=dashboards_by_cnpj,
        competencias=common_competencias,
        attr_name="liquidity_history_df",
        value_columns=[
            "liquidez_imediata",
            "liquidez_30",
            "liquidez_60",
            "liquidez_90",
            "liquidez_180",
            "liquidez_360",
            "liquidez_mais_360",
        ],
        coverage_rows=coverage_rows,
        block_id="liquidez",
        block_label="Liquidez reportada",
    )
    maturity_history_df = _aggregate_status_long_history(
        dashboards_by_cnpj=dashboards_by_cnpj,
        competencias=common_competencias,
        attr_name="maturity_history_df",
        key_columns=["faixa", "prazo_proxy"],
        coverage_rows=coverage_rows,
        block_id="vencimento",
        block_label="Malha de vencimento dos direitos creditórios",
        order_lookup=_MATURITY_BUCKET_ORDER,
    )
    duration_history_df = _build_portfolio_duration_history(
        maturity_history_df=maturity_history_df,
        coverage_rows=coverage_rows,
        total_funds=len(dashboards_by_cnpj),
    )
    default_history_df = _aggregate_default_history(
        dashboards_by_cnpj=dashboards_by_cnpj,
        competencias=common_competencias,
        coverage_rows=coverage_rows,
    )
    default_buckets_history_df = _aggregate_status_long_history(
        dashboards_by_cnpj=dashboards_by_cnpj,
        competencias=common_competencias,
        attr_name="default_buckets_history_df",
        key_columns=["faixa"],
        coverage_rows=coverage_rows,
        block_id="aging_buckets",
        block_label="Buckets monetários da inadimplência",
        order_lookup=_AGING_BUCKET_ORDER,
    )
    default_aging_history_df = _build_portfolio_default_aging_history(
        default_buckets_history_df=default_buckets_history_df,
        dc_canonical_history_df=dc_canonical_history_df,
    )
    default_over_history_df = _build_portfolio_default_over_history(
        default_buckets_history_df=default_buckets_history_df,
        dc_canonical_history_df=dc_canonical_history_df,
    )
    event_block_supported = all(
        dashboard.latest_competencia == latest_competencia
        for _, dashboard in dashboards_by_cnpj.values()
    )
    event_summary_latest_df = _aggregate_event_summary_latest(
        dashboards_by_cnpj=dashboards_by_cnpj,
        latest_competencia=latest_competencia,
        pl_total=_latest_value(subordination_history_df, latest_competencia, "pl_total"),
        coverage_rows=coverage_rows,
        enabled=event_block_supported,
    )
    liquidity_latest_df = _build_liquidity_latest_df(
        liquidity_history_df=liquidity_history_df,
        latest_competencia=latest_competencia,
    )
    maturity_latest_df = _latest_complete_long_frame(
        history_df=maturity_history_df,
        latest_competencia=latest_competencia,
    )
    default_buckets_latest_df = _build_portfolio_default_buckets_latest_df(
        default_buckets_history_df=default_buckets_history_df,
        default_aging_history_df=default_aging_history_df,
        latest_competencia=latest_competencia,
    )
    composition_latest_df = single._build_composition_latest_df(asset_history_df)
    summary = _build_portfolio_summary(
        latest_competencia=latest_competencia,
        asset_history_df=asset_history_df,
        subordination_history_df=subordination_history_df,
        default_history_df=default_history_df,
        event_summary_latest_df=event_summary_latest_df,
        dc_canonical_history_df=dc_canonical_history_df,
        liquidity_history_df=liquidity_history_df,
    )
    risk_metrics_df = build_risk_metrics_df(
        latest_competencia=latest_competencia,
        summary=summary,
        asset_history_df=asset_history_df,
        segment_latest_df=pd.DataFrame(columns=["segmento", "valor", "percentual"]),
        subordination_history_df=subordination_history_df,
        default_history_df=default_history_df,
        event_summary_latest_df=event_summary_latest_df,
    )
    risk_metrics_df = risk_metrics_df[
        ~risk_metrics_df["metric_id"].isin({"concentracao_segmento_proxy"})
    ].reset_index(drop=True)

    coverage_df = _finalize_coverage_df(coverage_rows)
    reconciliation_df = _build_portfolio_reconciliation_df(
        latest_competencia=latest_competencia,
        summary=summary,
        asset_history_df=asset_history_df,
        subordination_history_df=subordination_history_df,
        default_history_df=default_history_df,
        liquidity_history_df=liquidity_history_df,
        maturity_history_df=maturity_history_df,
        default_buckets_history_df=default_buckets_history_df,
        dc_canonical_history_df=dc_canonical_history_df,
    )
    current_dashboard_inventory_df = _build_portfolio_inventory_df()
    executive_memory_df = _build_portfolio_memory_df()
    consistency_audit_df = _build_portfolio_consistency_df(
        coverage_df=coverage_df,
        common_competencias=common_competencias,
        total_funds=len(dashboards_by_cnpj),
        maturity_history_df=maturity_history_df,
        default_buckets_history_df=default_buckets_history_df,
        default_history_df=default_history_df,
        dc_canonical_history_df=dc_canonical_history_df,
    )
    methodology_notes = [
        "Visão carteira usa interseção estrita das competências comuns entre todos os fundos incluídos.",
        "A soma é analítica e auditável entre fundos standalone; não representa consolidação societária ou contábil formal.",
        "Todos os percentuais são recalculados a partir de numeradores e denominadores agregados; percentuais individuais não são somados.",
        "Subordinação reportada preserva a lógica econômica do projeto: numerador = mezzanino + subordinadas residuais.",
        "Rentabilidade, benchmark, cotistas agregados e taxas de negociação ficam desabilitados no modo carteira por falta de base econômica auditável comparável.",
        "Prazo médio proxy da carteira usa apenas os buckets a vencer: Σ(bucket_a_vencer × prazo_proxy) / Σ(bucket_a_vencer).",
    ]
    if not event_block_supported:
        methodology_notes.append(
            "Eventos de cotas da competência mais recente ficam desabilitados quando a última competência comum não coincide com a última competência individual de todos os fundos."
        )

    fund_info = {
        "nome_fundo": portfolio_name,
        "nome_classe": "",
        "condominio": "Múltiplos FIDCs",
        "total_cotistas": "",
        "periodo_analisado": f"{common_competencias[0]} a {latest_competencia}",
        "ultima_competencia": latest_competencia,
        "ultima_entrega": "",
        "aggregation_scope": "portfolio",
    }

    dashboard = FundonetDashboardData(
        competencias=common_competencias,
        latest_competencia=latest_competencia,
        fund_info=fund_info,
        summary=summary,
        asset_history_df=asset_history_df,
        composition_latest_df=composition_latest_df,
        segment_latest_df=pd.DataFrame(columns=["segmento", "valor", "percentual"]),
        liquidity_history_df=liquidity_history_df,
        liquidity_latest_df=liquidity_latest_df,
        maturity_latest_df=maturity_latest_df,
        maturity_history_df=maturity_history_df,
        duration_history_df=duration_history_df,
        quota_pl_history_df=quota_pl_history_df,
        subordination_history_df=subordination_history_df,
        return_history_df=pd.DataFrame(columns=["competencia", "competencia_dt", "class_label", "retorno_mensal_pct"]),
        return_summary_df=pd.DataFrame(columns=["label", "retorno_mes_pct", "retorno_ano_pct", "retorno_12m_pct"]),
        performance_vs_benchmark_latest_df=pd.DataFrame(columns=["label", "desempenho_esperado_pct", "desempenho_real_pct", "gap_bps"]),
        event_history_df=pd.DataFrame(columns=["competencia", "competencia_dt", "event_type", "valor_total_assinado"]),
        dc_canonical_history_df=dc_canonical_history_df,
        default_history_df=default_history_df,
        default_buckets_latest_df=default_buckets_latest_df,
        default_buckets_history_df=default_buckets_history_df,
        default_aging_history_df=default_aging_history_df,
        default_over_history_df=default_over_history_df,
        holder_latest_df=pd.DataFrame(columns=["grupo", "categoria", "quantidade"]),
        rate_negotiation_latest_df=pd.DataFrame(columns=["grupo", "operacao", "taxa_min", "taxa_media", "taxa_max"]),
        tracking_latest_df=pd.DataFrame(columns=["indicador", "valor", "unidade", "fonte", "interpretação", "estado_dado"]),
        event_summary_latest_df=event_summary_latest_df,
        risk_metrics_df=risk_metrics_df,
        coverage_gap_df=pd.DataFrame(columns=["tema", "status", "por_que_importa", "fonte_necessaria"]),
        mini_glossary_df=pd.DataFrame(columns=["termo", "definicao"]),
        current_dashboard_inventory_df=current_dashboard_inventory_df,
        executive_memory_df=executive_memory_df,
        consistency_audit_df=consistency_audit_df,
        methodology_notes=methodology_notes,
    )
    return PortfolioDashboardBundle(
        dashboard=dashboard,
        fund_scope_df=fund_scope_df,
        coverage_df=coverage_df,
        reconciliation_df=reconciliation_df,
        temporal_rule="intersecao_estrita_ultima_competencia_comum",
    )


def _build_fund_scope_df(dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for cnpj, (display_name, dashboard) in dashboards_by_cnpj.items():
        competencias = list(dashboard.competencias)
        rows.append(
            {
                "cnpj": cnpj,
                "fundo": display_name,
                "competencia_inicial": competencias[0] if competencias else pd.NA,
                "competencia_final": competencias[-1] if competencias else pd.NA,
                "competencias_carregadas": len(competencias),
            }
        )
    return pd.DataFrame(rows).sort_values(["fundo", "cnpj"]).reset_index(drop=True)


def _common_competencias(dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]]) -> list[str]:
    sets = [set(dashboard.competencias) for _, dashboard in dashboards_by_cnpj.values()]
    common = set.intersection(*sets) if sets else set()
    return sorted(common, key=single._competencia_sort_key)


def _aggregate_scalar_history(
    *,
    dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]],
    competencias: list[str],
    attr_name: str,
    value_columns: list[str],
    coverage_rows: list[dict[str, object]],
    block_id: str,
    block_label: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    total_funds = len(dashboards_by_cnpj)
    for competencia in competencias:
        missing_funds: set[str] = set()
        row: dict[str, object] = {
            "competencia": competencia,
            "competencia_dt": single._competencia_to_timestamp(competencia),
        }
        for column in value_columns:
            values: list[float] = []
            for fund_name, dashboard in dashboards_by_cnpj.values():
                frame = getattr(dashboard, attr_name)
                if not isinstance(frame, pd.DataFrame) or frame.empty or "competencia" not in frame.columns or column not in frame.columns:
                    missing_funds.add(fund_name)
                    continue
                match = frame[frame["competencia"] == competencia]
                value = pd.to_numeric(match[column], errors="coerce").iloc[-1] if not match.empty else pd.NA
                if pd.isna(value):
                    missing_funds.add(fund_name)
                    continue
                values.append(float(value))
            row[column] = float(sum(values)) if len(values) == total_funds else pd.NA
        coverage_rows.append(
            _coverage_row(
                competencia=competencia,
                block_id=block_id,
                block_label=block_label,
                total_funds=total_funds,
                missing_funds=missing_funds,
            )
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _aggregate_subordination_history(
    *,
    dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]],
    competencias: list[str],
    coverage_rows: list[dict[str, object]],
) -> pd.DataFrame:
    history_df = _aggregate_scalar_history(
        dashboards_by_cnpj=dashboards_by_cnpj,
        competencias=competencias,
        attr_name="subordination_history_df",
        value_columns=[
            "pl_total",
            "pl_senior",
            "pl_mezzanino",
            "pl_subordinada_strict",
            "pl_subordinada",
        ],
        coverage_rows=coverage_rows,
        block_id="estrutura_cotas",
        block_label="Estrutura de cotas e subordinação",
    )
    history_df["subordinacao_pct"] = (
        history_df["pl_subordinada"] / history_df["pl_total"]
    ).where(pd.to_numeric(history_df["pl_total"], errors="coerce") > 0).mul(100.0)
    return history_df


def _build_portfolio_quota_history(subordination_history_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in subordination_history_df.iterrows():
        competencia = row.get("competencia")
        competencia_dt = row.get("competencia_dt")
        macro_values = [
            ("senior", "Sênior", row.get("pl_senior")),
            ("mezzanino", "Mezzanino", row.get("pl_mezzanino")),
            ("subordinada", "Subordinada", row.get("pl_subordinada_strict")),
        ]
        total = pd.to_numeric(pd.Series([row.get("pl_total")]), errors="coerce").iloc[0]
        for ordem, (class_macro, class_macro_label, value) in enumerate(macro_values, start=1):
            numeric_value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
            rows.append(
                {
                    "competencia": competencia,
                    "competencia_dt": competencia_dt,
                    "class_kind": class_macro,
                    "class_macro": class_macro,
                    "class_macro_label": class_macro_label,
                    "class_key": f"portfolio|{class_macro}",
                    "class_label": class_macro_label,
                    "label": class_macro_label,
                    "qt_cotas": pd.NA,
                    "vl_cota": pd.NA,
                    "pl": numeric_value,
                    "pl_share_pct": (numeric_value / total * 100.0) if pd.notna(numeric_value) and pd.notna(total) and total > 0 else pd.NA,
                    "ordem": ordem,
                    "aggregation_scope": "portfolio",
                }
            )
    return pd.DataFrame(rows)


def _aggregate_dc_canonical_history(
    *,
    dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]],
    competencias: list[str],
    coverage_rows: list[dict[str, object]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    total_funds = len(dashboards_by_cnpj)
    for competencia in competencias:
        values = {"dc_total_canonico": [], "dc_vencidos_canonico": [], "dc_a_vencer_canonico": []}
        missing_funds: set[str] = set()
        for fund_name, dashboard in dashboards_by_cnpj.values():
            frame = dashboard.dc_canonical_history_df
            match = frame[frame["competencia"] == competencia]
            if match.empty:
                missing_funds.add(fund_name)
                continue
            latest = match.iloc[-1]
            total_status = str(latest.get("dc_total_source_status") or "")
            vencidos_status = str(latest.get("dc_vencidos_source_status") or "")
            avencer_status = str(latest.get("dc_a_vencer_source_status") or "")
            if total_status not in _VALID_SOURCE_STATUSES or vencidos_status not in _VALID_SOURCE_STATUSES or avencer_status not in _VALID_SOURCE_STATUSES:
                missing_funds.add(fund_name)
                continue
            values["dc_total_canonico"].append(float(latest.get("dc_total_canonico") or 0.0))
            values["dc_vencidos_canonico"].append(float(latest.get("dc_vencidos_canonico") or 0.0))
            values["dc_a_vencer_canonico"].append(float(latest.get("dc_a_vencer_canonico") or 0.0))
        complete = all(len(series) == total_funds for series in values.values())
        rows.append(
            {
                "competencia": competencia,
                "competencia_dt": single._competencia_to_timestamp(competencia),
                "dc_total_canonico": float(sum(values["dc_total_canonico"])) if complete else pd.NA,
                "dc_total_fonte_efetiva": "soma_multi_cnpj_base_canonica" if complete else "not_available",
                "dc_total_source_status": "reported_value" if complete else "not_available",
                "dc_total_malha_vencimento": pd.NA,
                "dc_total_estoque_granular": pd.NA,
                "dc_total_agregado_item3": pd.NA,
                "dc_total_present_source_paths": pd.NA,
                "dc_total_source_paths": pd.NA,
                "dc_vencidos_canonico": float(sum(values["dc_vencidos_canonico"])) if complete else pd.NA,
                "dc_vencidos_fonte_efetiva": "soma_multi_cnpj_vencidos_canonicos" if complete else "not_available",
                "dc_vencidos_source_status": "reported_value" if complete else "not_available",
                "dc_vencidos_malha_vencimento": pd.NA,
                "dc_vencidos_aging": pd.NA,
                "dc_vencidos_agregado_aplic_ativo": pd.NA,
                "dc_a_vencer_canonico": float(sum(values["dc_a_vencer_canonico"])) if complete else pd.NA,
                "dc_a_vencer_source_status": "reported_value" if complete else "not_available",
                "reconciliacao_malha_vs_estoque_status": "sem_base",
                "reconciliacao_malha_vs_estoque_gap_pct": pd.NA,
                "reconciliacao_malha_vs_agregado_status": "sem_base",
                "reconciliacao_malha_vs_agregado_gap_pct": pd.NA,
            }
        )
        coverage_rows.append(
            _coverage_row(
                competencia=competencia,
                block_id="base_canonica_dc",
                block_label="Base canônica de direitos creditórios",
                total_funds=total_funds,
                missing_funds=missing_funds,
            )
        )
    return pd.DataFrame(rows)


def _aggregate_asset_history(
    *,
    dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]],
    competencias: list[str],
    dc_canonical_history_df: pd.DataFrame,
    coverage_rows: list[dict[str, object]],
) -> pd.DataFrame:
    asset_history_df = _aggregate_scalar_history(
        dashboards_by_cnpj=dashboards_by_cnpj,
        competencias=competencias,
        attr_name="asset_history_df",
        value_columns=[
            "ativos_totais",
            "carteira",
            "disponibilidades",
            "valores_mobiliarios",
            "titulos_publicos",
            "outros_ativos_reportados",
            "liquidez_total",
            "aquisicoes",
            "alienacoes",
        ],
        coverage_rows=coverage_rows,
        block_id="ativo_carteira",
        block_label="Ativo, carteira e fluxo dos direitos creditórios",
    )
    dc_lookup = dc_canonical_history_df.set_index("competencia", drop=False)
    asset_history_df["direitos_creditorios"] = asset_history_df["competencia"].map(
        lambda competencia: dc_lookup.loc[competencia, "dc_total_canonico"] if competencia in dc_lookup.index else pd.NA
    )
    asset_history_df["direitos_creditorios_fonte"] = "soma_multi_cnpj_base_canonica"
    asset_history_df["outros_ativos_carteira"] = (
        pd.to_numeric(asset_history_df["carteira"], errors="coerce")
        - pd.to_numeric(asset_history_df["direitos_creditorios"], errors="coerce")
    ).clip(lower=0.0)
    asset_history_df["alocacao_pct"] = (
        pd.to_numeric(asset_history_df["direitos_creditorios"], errors="coerce")
        / pd.to_numeric(asset_history_df["carteira"], errors="coerce")
    ).where(pd.to_numeric(asset_history_df["carteira"], errors="coerce") > 0).mul(100.0)
    return asset_history_df


def _aggregate_default_history(
    *,
    dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]],
    competencias: list[str],
    coverage_rows: list[dict[str, object]],
) -> pd.DataFrame:
    df = _aggregate_scalar_history(
        dashboards_by_cnpj=dashboards_by_cnpj,
        competencias=competencias,
        attr_name="default_history_df",
        value_columns=[
            "direitos_creditorios_ativo",
            "direitos_creditorios_vencidos",
            "direitos_creditorios_vencimento_total",
            "direitos_creditorios",
            "inadimplencia_total",
            "parcelas_inadimplentes_total",
            "creditos_existentes_inadimplentes",
            "creditos_vencidos_pendentes_cessao",
            "somatorio_inadimplentes_aux_validacao",
            "provisao_total",
            "pendencia_total",
        ],
        coverage_rows=coverage_rows,
        block_id="credito_default",
        block_label="Inadimplência, provisão e base de crédito",
    )
    df["direitos_creditorios_fonte"] = "soma_multi_cnpj_base_canonica"
    df["inadimplencia_fonte"] = "soma_multi_cnpj_vencidos_canonicos"
    direitos_creditorios = pd.to_numeric(df["direitos_creditorios"], errors="coerce")
    inadimplencia_total = pd.to_numeric(df["inadimplencia_total"], errors="coerce")
    provisao_total = pd.to_numeric(df["provisao_total"], errors="coerce")
    somatorio_aux = pd.to_numeric(df["somatorio_inadimplentes_aux_validacao"], errors="coerce")
    df["inadimplencia_pct"] = (inadimplencia_total / direitos_creditorios).where(direitos_creditorios > 0).mul(100.0)
    df["provisao_pct_direitos"] = (provisao_total / direitos_creditorios).where(direitos_creditorios > 0).mul(100.0)
    df["cobertura_pct"] = (provisao_total / inadimplencia_total).where(inadimplencia_total > 0).mul(100.0)
    df["somatorio_inadimplentes_aux_validacao_pct_dcs"] = (somatorio_aux / direitos_creditorios).where(direitos_creditorios > 0).mul(100.0)
    return df


def _aggregate_status_long_history(
    *,
    dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]],
    competencias: list[str],
    attr_name: str,
    key_columns: list[str],
    coverage_rows: list[dict[str, object]],
    block_id: str,
    block_label: str,
    order_lookup: dict[str, int],
) -> pd.DataFrame:
    funds_total = len(dashboards_by_cnpj)
    specs = _build_long_specs(
        dashboards_by_cnpj=dashboards_by_cnpj,
        attr_name=attr_name,
        key_columns=key_columns,
        order_lookup=order_lookup,
    )
    rows: list[dict[str, object]] = []
    for competencia in competencias:
        missing_funds: set[str] = set()
        for spec in specs:
            values: list[float] = []
            complete = True
            for fund_name, dashboard in dashboards_by_cnpj.values():
                frame = getattr(dashboard, attr_name)
                if not isinstance(frame, pd.DataFrame) or frame.empty or "competencia" not in frame.columns:
                    complete = False
                    missing_funds.add(fund_name)
                    continue
                subset = frame[frame["competencia"] == competencia].copy()
                for key, value in spec.items():
                    if key not in subset.columns:
                        complete = False
                        missing_funds.add(fund_name)
                        subset = subset.iloc[0:0]
                        break
                    subset = subset[subset[key] == value]
                if subset.empty:
                    complete = False
                    missing_funds.add(fund_name)
                    continue
                latest = subset.iloc[-1]
                status = str(latest.get("source_status") or "")
                value = pd.to_numeric(pd.Series([latest.get("valor")]), errors="coerce").iloc[0]
                if status not in _VALID_SOURCE_STATUSES or pd.isna(value):
                    complete = False
                    missing_funds.add(fund_name)
                    continue
                values.append(float(value))
            output_row = {
                "competencia": competencia,
                "competencia_dt": single._competencia_to_timestamp(competencia),
                **spec,
                "ordem": order_lookup.get(str(spec.get("faixa") or ""), pd.NA),
                "valor": float(sum(values)) if complete and len(values) == funds_total else pd.NA,
                "valor_raw": float(sum(values)) if complete and len(values) == funds_total else pd.NA,
                "source_status": "reported_value" if complete and len(values) == funds_total else "not_available",
                "source_paths": pd.NA,
                "present_source_paths": pd.NA,
            }
            rows.append(output_row)
        coverage_rows.append(
            _coverage_row(
                competencia=competencia,
                block_id=block_id,
                block_label=block_label,
                total_funds=funds_total,
                missing_funds=missing_funds,
            )
        )
    return pd.DataFrame(rows)


def _build_long_specs(
    *,
    dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]],
    attr_name: str,
    key_columns: list[str],
    order_lookup: dict[str, int],
) -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for _, dashboard in dashboards_by_cnpj.values():
        frame = getattr(dashboard, attr_name)
        if not isinstance(frame, pd.DataFrame) or frame.empty or "competencia" not in frame.columns:
            continue
        if any(column not in frame.columns for column in key_columns):
            continue
        for _, row in frame.iterrows():
            spec = {column: row.get(column) for column in key_columns}
            key = tuple(spec[column] for column in key_columns)
            if key in seen:
                continue
            seen.add(key)
            specs.append(spec)
    def _spec_sort_key(spec: dict[str, object]) -> tuple[int, str]:
        faixa = str(spec.get("faixa") or "")
        return (order_lookup.get(faixa, 999), faixa)
    return sorted(specs, key=_spec_sort_key)


def _build_portfolio_default_aging_history(
    *,
    default_buckets_history_df: pd.DataFrame,
    dc_canonical_history_df: pd.DataFrame,
) -> pd.DataFrame:
    if default_buckets_history_df.empty or dc_canonical_history_df.empty:
        return pd.DataFrame(columns=["competencia", "competencia_dt", "ordem", "faixa", "valor", "percentual_inadimplencia", "percentual_direitos_creditorios", "source_status"])
    df = default_buckets_history_df.copy()
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    totals = df.groupby("competencia", dropna=False)["valor"].sum(min_count=1).rename("inadimplencia_total_aging")
    df = df.merge(totals, on="competencia", how="left")
    denominator_df = dc_canonical_history_df[["competencia", "dc_total_canonico", "dc_total_fonte_efetiva"]].copy()
    df = df.merge(denominator_df, on="competencia", how="left")
    df["percentual_inadimplencia"] = (
        pd.to_numeric(df["valor"], errors="coerce") / pd.to_numeric(df["inadimplencia_total_aging"], errors="coerce")
    ).where(pd.to_numeric(df["inadimplencia_total_aging"], errors="coerce") > 0).mul(100.0)
    df["percentual_direitos_creditorios"] = (
        pd.to_numeric(df["valor"], errors="coerce") / pd.to_numeric(df["dc_total_canonico"], errors="coerce")
    ).where(pd.to_numeric(df["dc_total_canonico"], errors="coerce") > 0).mul(100.0)
    return df


def _build_portfolio_default_buckets_latest_df(
    *,
    default_buckets_history_df: pd.DataFrame,
    default_aging_history_df: pd.DataFrame,
    latest_competencia: str,
) -> pd.DataFrame:
    latest_df = _latest_complete_long_frame(
        history_df=default_buckets_history_df,
        latest_competencia=latest_competencia,
    )
    if latest_df.empty:
        return latest_df
    if default_aging_history_df.empty or "competencia" not in default_aging_history_df.columns:
        return latest_df
    aging_latest_df = default_aging_history_df[
        default_aging_history_df["competencia"] == latest_competencia
    ].copy()
    if aging_latest_df.empty:
        return latest_df
    merge_columns = [column for column in ["ordem", "faixa", "percentual_inadimplencia", "percentual_direitos_creditorios"] if column in aging_latest_df.columns]
    if not {"ordem", "faixa"}.issubset(merge_columns):
        return latest_df
    output = latest_df.merge(
        aging_latest_df[merge_columns],
        on=["ordem", "faixa"],
        how="left",
    )
    if "percentual_inadimplencia" in output.columns and "percentual" not in output.columns:
        output["percentual"] = output["percentual_inadimplencia"]
    return output


def _build_portfolio_default_over_history(
    *,
    default_buckets_history_df: pd.DataFrame,
    dc_canonical_history_df: pd.DataFrame,
) -> pd.DataFrame:
    if default_buckets_history_df.empty or dc_canonical_history_df.empty:
        return pd.DataFrame(columns=["competencia", "competencia_dt", "ordem", "serie", "valor", "percentual", "calculo_status", "denominador_fonte"])
    denominator_lookup = dc_canonical_history_df.set_index("competencia", drop=False)
    rows: list[dict[str, object]] = []
    for ordem, (serie, ordem_min, ordem_max) in enumerate(single._OVER_BUCKET_SPECS, start=1):
        subset = default_buckets_history_df[default_buckets_history_df["ordem"] >= ordem_min].copy()
        if ordem_max is not None:
            subset = subset[subset["ordem"] <= ordem_max].copy()
        for competencia, group_df in subset.groupby("competencia", dropna=False):
            denominator = pd.to_numeric(pd.Series([denominator_lookup.loc[competencia, "dc_total_canonico"]]), errors="coerce").iloc[0] if competencia in denominator_lookup.index else pd.NA
            values = pd.to_numeric(group_df["valor"], errors="coerce")
            complete = not values.isna().any() and pd.notna(denominator) and denominator > 0
            total_value = float(values.sum()) if complete else pd.NA
            rows.append(
                {
                    "competencia": competencia,
                    "competencia_dt": single._competencia_to_timestamp(competencia),
                    "ordem": ordem,
                    "serie": serie,
                    "valor": total_value,
                    "percentual": (total_value / denominator * 100.0) if complete else pd.NA,
                    "calculo_status": "calculado" if complete else "bucket_incompleto",
                    "denominador_fonte": "soma_multi_cnpj_base_canonica",
                }
            )
    return pd.DataFrame(rows).sort_values(["competencia_dt", "ordem"]).reset_index(drop=True)


def _build_portfolio_duration_history(
    *,
    maturity_history_df: pd.DataFrame,
    coverage_rows: list[dict[str, object]],
    total_funds: int,
) -> pd.DataFrame:
    if maturity_history_df.empty:
        return pd.DataFrame(columns=["competencia", "competencia_dt", "duration_days", "total_saldo", "data_quality"])
    rows: list[dict[str, object]] = []
    for competencia, group_df in maturity_history_df.groupby("competencia", dropna=False):
        future_df = group_df[group_df["faixa"] != "Vencidos"].copy()
        valores = pd.to_numeric(future_df["valor"], errors="coerce")
        proxies = pd.to_numeric(future_df["prazo_proxy"], errors="coerce")
        complete = not valores.isna().any() and not proxies.isna().any() and not future_df.empty
        total_saldo = float(valores.sum()) if complete else pd.NA
        duration_days = (
            float((valores * proxies).sum() / total_saldo)
            if complete and pd.notna(total_saldo) and total_saldo > 0
            else pd.NA
        )
        rows.append(
            {
                "competencia": competencia,
                "competencia_dt": single._competencia_to_timestamp(competencia),
                "duration_days": duration_days,
                "total_saldo": total_saldo,
                "data_quality": "ok" if pd.notna(duration_days) else "sem_dados",
            }
        )
    coverage_rows.extend(
        _coverage_row(
            competencia=row["competencia"],
            block_id="prazo_medio",
            block_label="Prazo médio proxy dos direitos a vencer",
            total_funds=total_funds,
            missing_funds=set(),
            note=row["data_quality"],
            status_override="Completo" if row["data_quality"] == "ok" else "Incompleto",
        )
        for row in rows
    )
    return pd.DataFrame(rows).sort_values("competencia_dt").reset_index(drop=True)


def _aggregate_event_summary_latest(
    *,
    dashboards_by_cnpj: dict[str, tuple[str, FundonetDashboardData]],
    latest_competencia: str,
    pl_total: object,
    coverage_rows: list[dict[str, object]],
    enabled: bool,
) -> pd.DataFrame:
    total_funds = len(dashboards_by_cnpj)
    if not enabled:
        coverage_rows.append(
            _coverage_row(
                competencia=latest_competencia,
                block_id="eventos_cotas",
                block_label="Eventos de cotas na competência mais recente",
                total_funds=total_funds,
                missing_funds={fund_name for fund_name, _ in dashboards_by_cnpj.values()},
                note="ultima_competencia_comum_diferente_da_ultima_individual",
            )
        )
        return pd.DataFrame(
            columns=[
                "ordem",
                "event_type",
                "evento",
                "valor_total",
                "valor_total_assinado",
                "valor_total_pct_pl",
                "source_status",
                "source_paths",
                "present_source_paths",
                "interpretação",
            ]
        )
    rows: list[dict[str, object]] = []
    missing_funds: set[str] = set()
    pl_numeric = pd.to_numeric(pd.Series([pl_total]), errors="coerce").iloc[0]
    for ordem, event_type in enumerate(_EVENT_ORDER, start=1):
        valor_total: list[float] = []
        valor_assinado: list[float] = []
        complete = True
        for fund_name, dashboard in dashboards_by_cnpj.values():
            frame = dashboard.event_summary_latest_df
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                complete = False
                missing_funds.add(fund_name)
                continue
            required_columns = {"event_type", "source_status", "valor_total", "valor_total_assinado"}
            if any(column not in frame.columns for column in required_columns):
                complete = False
                missing_funds.add(fund_name)
                continue
            subset = frame[frame["event_type"] == event_type]
            if subset.empty:
                complete = False
                missing_funds.add(fund_name)
                continue
            latest = subset.iloc[-1]
            status = str(latest.get("source_status") or "")
            total_value = pd.to_numeric(pd.Series([latest.get("valor_total")]), errors="coerce").iloc[0]
            signed_value = pd.to_numeric(pd.Series([latest.get("valor_total_assinado")]), errors="coerce").iloc[0]
            if status not in _VALID_SOURCE_STATUSES or pd.isna(total_value) or pd.isna(signed_value):
                complete = False
                missing_funds.add(fund_name)
                continue
            valor_total.append(float(total_value))
            valor_assinado.append(float(signed_value))
        sum_total = float(sum(valor_total)) if complete and len(valor_total) == total_funds else pd.NA
        sum_signed = float(sum(valor_assinado)) if complete and len(valor_assinado) == total_funds else pd.NA
        rows.append(
            {
                "ordem": ordem,
                "event_type": event_type,
                "evento": single.EVENT_LABEL[event_type],
                "valor_total": sum_total,
                "valor_total_assinado": sum_signed,
                "valor_total_pct_pl": (sum_signed / pl_numeric * 100.0) if pd.notna(sum_signed) and pd.notna(pl_numeric) and pl_numeric > 0 else pd.NA,
                "source_status": "reported_value" if pd.notna(sum_total) else "not_available",
                "source_paths": pd.NA,
                "present_source_paths": pd.NA,
                "interpretação": single.EVENT_INTERPRETATION[event_type],
            }
        )
    coverage_rows.append(
        _coverage_row(
            competencia=latest_competencia,
            block_id="eventos_cotas",
            block_label="Eventos de cotas na competência mais recente",
            total_funds=total_funds,
            missing_funds=missing_funds,
        )
    )
    return pd.DataFrame(rows)


def _build_liquidity_latest_df(
    *,
    liquidity_history_df: pd.DataFrame,
    latest_competencia: str,
) -> pd.DataFrame:
    latest_row = liquidity_history_df[liquidity_history_df["competencia"] == latest_competencia].copy()
    if latest_row.empty:
        return pd.DataFrame(columns=["ordem", "horizonte", "valor", "valor_raw", "source_status"])
    latest = latest_row.iloc[-1]
    rows: list[dict[str, object]] = []
    for ordem, (label, column) in enumerate(_LIQUIDITY_BUCKETS, start=1):
        value = pd.to_numeric(pd.Series([latest.get(column)]), errors="coerce").iloc[0]
        rows.append(
            {
                "ordem": ordem,
                "horizonte": label,
                "valor": value,
                "valor_raw": value,
                "source_status": "reported_value" if pd.notna(value) else "not_available",
            }
        )
    frame = pd.DataFrame(rows)
    if frame["valor"].isna().any():
        return pd.DataFrame(columns=frame.columns)
    return frame


def _latest_complete_long_frame(*, history_df: pd.DataFrame, latest_competencia: str) -> pd.DataFrame:
    if history_df.empty or "competencia" not in history_df.columns or "valor" not in history_df.columns:
        return pd.DataFrame(columns=getattr(history_df, "columns", []))
    latest_df = history_df[history_df["competencia"] == latest_competencia].copy()
    if latest_df.empty:
        return latest_df
    if pd.to_numeric(latest_df["valor"], errors="coerce").isna().any():
        return pd.DataFrame(columns=latest_df.columns)
    return latest_df


def _build_portfolio_summary(
    *,
    latest_competencia: str,
    asset_history_df: pd.DataFrame,
    subordination_history_df: pd.DataFrame,
    default_history_df: pd.DataFrame,
    event_summary_latest_df: pd.DataFrame,
    dc_canonical_history_df: pd.DataFrame,
    liquidity_history_df: pd.DataFrame,
) -> dict[str, float | str | None]:
    asset_row = _exact_latest_row(asset_history_df, latest_competencia)
    sub_row = _exact_latest_row(subordination_history_df, latest_competencia)
    default_row = _exact_latest_row(default_history_df, latest_competencia)
    dc_row = _exact_latest_row(dc_canonical_history_df, latest_competencia)
    liquidity_row = _exact_latest_row(liquidity_history_df, latest_competencia)
    return {
        "pl_total": _float_or_none(sub_row.get("pl_total")),
        "pl_senior": _float_or_none(sub_row.get("pl_senior")),
        "pl_mezzanino": _float_or_none(sub_row.get("pl_mezzanino")),
        "pl_subordinada_strict": _float_or_none(sub_row.get("pl_subordinada_strict")),
        "pl_subordinada": _float_or_none(sub_row.get("pl_subordinada")),
        "ativos_totais": _float_or_none(asset_row.get("ativos_totais")),
        "carteira": _float_or_none(asset_row.get("carteira")),
        "direitos_creditorios": _float_or_none(dc_row.get("dc_total_canonico")),
        "direitos_creditorios_fonte": dc_row.get("dc_total_fonte_efetiva"),
        "outros_ativos_carteira": _float_or_none(asset_row.get("outros_ativos_carteira")),
        "alocacao_pct": _float_or_none(asset_row.get("alocacao_pct")),
        "liquidez_imediata": _float_or_none(liquidity_row.get("liquidez_imediata")),
        "liquidez_30": _float_or_none(liquidity_row.get("liquidez_30")),
        "subordinacao_pct": _float_or_none(sub_row.get("subordinacao_pct")),
        "inadimplencia_total": _float_or_none(default_row.get("inadimplencia_total")),
        "inadimplencia_denominador": _float_or_none(default_row.get("direitos_creditorios_vencimento_total")),
        "inadimplencia_pct": _float_or_none(default_row.get("inadimplencia_pct")),
        "provisao_total": _float_or_none(default_row.get("provisao_total")),
        "provisao_pct_direitos": _float_or_none(default_row.get("provisao_pct_direitos")),
        "cobertura_pct": _float_or_none(default_row.get("cobertura_pct")),
        "direitos_creditorios_vencidos": _float_or_none(default_row.get("direitos_creditorios_vencidos")),
        "direitos_creditorios_vencimento_total": _float_or_none(default_row.get("direitos_creditorios_vencimento_total")),
        "emissao_mes": _event_summary_value(event_summary_latest_df, "emissao", "valor_total"),
        "resgate_mes": _event_summary_value(event_summary_latest_df, "resgate", "valor_total"),
        "resgate_solicitado_mes": _event_summary_value(event_summary_latest_df, "resgate_solicitado", "valor_total"),
        "amortizacao_mes": _event_summary_value(event_summary_latest_df, "amortizacao", "valor_total"),
    }


def _build_portfolio_reconciliation_df(
    *,
    latest_competencia: str,
    summary: dict[str, float | str | None],
    asset_history_df: pd.DataFrame,
    subordination_history_df: pd.DataFrame,
    default_history_df: pd.DataFrame,
    liquidity_history_df: pd.DataFrame,
    maturity_history_df: pd.DataFrame,
    default_buckets_history_df: pd.DataFrame,
    dc_canonical_history_df: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    asset_row = _exact_latest_row(asset_history_df, latest_competencia)
    sub_row = _exact_latest_row(subordination_history_df, latest_competencia)
    default_row = _exact_latest_row(default_history_df, latest_competencia)
    liquidity_row = _exact_latest_row(liquidity_history_df, latest_competencia)
    dc_row = _exact_latest_row(dc_canonical_history_df, latest_competencia)
    latest_maturity = maturity_history_df[maturity_history_df["competencia"] == latest_competencia].copy()
    latest_aging = default_buckets_history_df[default_buckets_history_df["competencia"] == latest_competencia].copy()

    def _append(
        *,
        metric_id: str,
        componente: str,
        unidade: str,
        formula: str,
        origem: str,
        expected: object,
        rendered: object,
        tolerance: float = 1e-9,
    ) -> None:
        expected_numeric = _float_or_none(expected)
        rendered_numeric = _float_or_none(rendered)
        if expected_numeric is None and rendered_numeric is None:
            rows.append(
                {
                    "metric_id": metric_id,
                    "componente": componente,
                    "unidade": unidade,
                    "origem": origem,
                    "formula": formula,
                    "esperado": pd.NA,
                    "renderizado": pd.NA,
                    "delta_abs": pd.NA,
                    "status": "Sem base",
                }
            )
            return
        if expected_numeric is None or rendered_numeric is None:
            rows.append(
                {
                    "metric_id": metric_id,
                    "componente": componente,
                    "unidade": unidade,
                    "origem": origem,
                    "formula": formula,
                    "esperado": expected_numeric if expected_numeric is not None else pd.NA,
                    "renderizado": rendered_numeric if rendered_numeric is not None else pd.NA,
                    "delta_abs": pd.NA,
                    "status": "Sem base",
                }
            )
            return
        delta_abs = abs(expected_numeric - rendered_numeric)
        rows.append(
            {
                "metric_id": metric_id,
                "componente": componente,
                "unidade": unidade,
                "origem": origem,
                "formula": formula,
                "esperado": expected_numeric,
                "renderizado": rendered_numeric,
                "delta_abs": delta_abs,
                "status": "Alinhado" if delta_abs <= tolerance else "Divergente",
            }
        )

    _append(
        metric_id="ativos_totais",
        componente="Ativo total agregado",
        unidade="R$",
        formula="Σ ativo_total_f,t",
        origem="asset_history_df -> summary",
        expected=asset_row.get("ativos_totais"),
        rendered=summary.get("ativos_totais"),
    )
    _append(
        metric_id="carteira",
        componente="Carteira agregada",
        unidade="R$",
        formula="Σ carteira_f,t",
        origem="asset_history_df -> summary",
        expected=asset_row.get("carteira"),
        rendered=summary.get("carteira"),
    )
    _append(
        metric_id="direitos_creditorios",
        componente="Direitos creditórios agregados",
        unidade="R$",
        formula="Σ dc_total_canonico_f,t",
        origem="dc_canonical_history_df -> summary",
        expected=dc_row.get("dc_total_canonico"),
        rendered=summary.get("direitos_creditorios"),
    )
    _append(
        metric_id="pl_total",
        componente="PL total agregado",
        unidade="R$",
        formula="Σ pl_total_f,t",
        origem="subordination_history_df -> summary",
        expected=sub_row.get("pl_total"),
        rendered=summary.get("pl_total"),
    )
    _append(
        metric_id="pl_mezzanino",
        componente="PL mezzanino agregado",
        unidade="R$",
        formula="Σ pl_mezzanino_f,t",
        origem="subordination_history_df -> summary",
        expected=sub_row.get("pl_mezzanino"),
        rendered=summary.get("pl_mezzanino"),
    )
    _append(
        metric_id="pl_subordinada",
        componente="PL subordinado reportado agregado",
        unidade="R$",
        formula="Σ(pl_mezzanino + pl_subordinada_strict)_f,t",
        origem="subordination_history_df -> summary",
        expected=sub_row.get("pl_subordinada"),
        rendered=summary.get("pl_subordinada"),
    )
    _append(
        metric_id="subordinacao_pct",
        componente="Subordinação reportada agregada",
        unidade="%",
        formula="(Σ pl_mezzanino + Σ pl_subordinada_strict) / Σ pl_total * 100",
        origem="subordination_history_df -> summary",
        expected=(
            _float_or_none(sub_row.get("pl_subordinada")) / _float_or_none(sub_row.get("pl_total")) * 100.0
            if _float_or_none(sub_row.get("pl_subordinada")) is not None
            and _float_or_none(sub_row.get("pl_total")) not in (None, 0.0)
            else pd.NA
        ),
        rendered=summary.get("subordinacao_pct"),
        tolerance=1e-6,
    )
    _append(
        metric_id="inadimplencia_total",
        componente="Inadimplência total agregada",
        unidade="R$",
        formula="Σ dc_vencidos_canonico_f,t",
        origem="default_history_df -> summary",
        expected=default_row.get("inadimplencia_total"),
        rendered=summary.get("inadimplencia_total"),
    )
    _append(
        metric_id="provisao_total",
        componente="Provisão total agregada",
        unidade="R$",
        formula="Σ provisao_total_f,t",
        origem="default_history_df -> summary",
        expected=default_row.get("provisao_total"),
        rendered=summary.get("provisao_total"),
    )
    _append(
        metric_id="inadimplencia_pct",
        componente="Inadimplência % agregada",
        unidade="%",
        formula="Σ inadimplencia_total / Σ direitos_creditorios * 100",
        origem="default_history_df -> summary",
        expected=default_row.get("inadimplencia_pct"),
        rendered=summary.get("inadimplencia_pct"),
        tolerance=1e-6,
    )
    _append(
        metric_id="provisao_pct_direitos",
        componente="Provisão / DC agregada",
        unidade="%",
        formula="Σ provisao_total / Σ direitos_creditorios * 100",
        origem="default_history_df -> summary",
        expected=default_row.get("provisao_pct_direitos"),
        rendered=summary.get("provisao_pct_direitos"),
        tolerance=1e-6,
    )
    _append(
        metric_id="cobertura_pct",
        componente="Cobertura de provisão agregada",
        unidade="%",
        formula="Σ provisao_total / Σ inadimplencia_total * 100",
        origem="default_history_df -> summary",
        expected=default_row.get("cobertura_pct"),
        rendered=summary.get("cobertura_pct"),
        tolerance=1e-6,
    )
    _append(
        metric_id="liquidez_imediata",
        componente="Liquidez imediata agregada",
        unidade="R$",
        formula="Σ liquidez_imediata_f,t",
        origem="liquidity_history_df -> summary",
        expected=liquidity_row.get("liquidez_imediata"),
        rendered=summary.get("liquidez_imediata"),
    )
    _append(
        metric_id="liquidez_30",
        componente="Liquidez até 30 dias agregada",
        unidade="R$",
        formula="Σ liquidez_30_f,t",
        origem="liquidity_history_df -> summary",
        expected=liquidity_row.get("liquidez_30"),
        rendered=summary.get("liquidez_30"),
    )

    latest_future_buckets = pd.to_numeric(
        latest_maturity[latest_maturity["faixa"] != "Vencidos"]["valor"],
        errors="coerce",
    ).sum(min_count=1) if not latest_maturity.empty else pd.NA
    _append(
        metric_id="maturity_vs_dc_a_vencer",
        componente="Buckets a vencer vs base canônica",
        unidade="R$",
        formula="Σ buckets_a_vencer = dc_a_vencer_canonico",
        origem="maturity_history_df -> dc_canonical_history_df",
        expected=latest_future_buckets,
        rendered=dc_row.get("dc_a_vencer_canonico"),
        tolerance=0.01,
    )

    latest_aging_total = pd.to_numeric(latest_aging["valor"], errors="coerce").sum(min_count=1) if not latest_aging.empty else pd.NA
    _append(
        metric_id="aging_vs_inadimplencia",
        componente="Buckets de aging vs inadimplência total",
        unidade="R$",
        formula="Σ buckets_inadimplencia = inadimplencia_total",
        origem="default_buckets_history_df -> default_history_df",
        expected=latest_aging_total,
        rendered=default_row.get("inadimplencia_total"),
        tolerance=0.01,
    )

    if not rows:
        return pd.DataFrame(columns=["metric_id", "componente", "unidade", "origem", "formula", "esperado", "renderizado", "delta_abs", "status"])
    return pd.DataFrame(rows)


def _build_portfolio_inventory_df() -> pd.DataFrame:
    rows = [
        {
            "nome_variavel": "summary.ativos_totais|summary.direitos_creditorios|summary.pl_total",
            "nome_exibido": "Cards financeiros agregados",
            "aba_origem": "Modo carteira",
            "bloco_ui_atual": "Topo da carteira",
            "fonte_dado": "Soma analítica multi-CNPJ sobre bases homogêneas do Informe Mensal",
            "formula": "Σ saldos monetários por competência comum",
            "arquivo_py": "services/fundonet_portfolio_dashboard.py",
            "tipo": "cards_monetarios",
            "unidade": "R$",
        },
        {
            "nome_variavel": "summary.subordinacao_pct",
            "nome_exibido": "Subordinação reportada agregada",
            "aba_origem": "Modo carteira",
            "bloco_ui_atual": "Estrutura",
            "fonte_dado": "Subordination history agregado",
            "formula": "(Σ mezzanino + Σ subordinada) / Σ PL total * 100",
            "arquivo_py": "services/fundonet_portfolio_dashboard.py",
            "tipo": "percentual_recalculado",
            "unidade": "%",
        },
        {
            "nome_variavel": "default_over_history_df.percentual",
            "nome_exibido": "Inadimplência Over agregada",
            "aba_origem": "Modo carteira",
            "bloco_ui_atual": "Crédito",
            "fonte_dado": "Buckets monetários agregados de inadimplência",
            "formula": "Σ buckets acima do threshold / Σ DC total canônico * 100",
            "arquivo_py": "services/fundonet_portfolio_dashboard.py",
            "tipo": "serie_historica_cumulativa",
            "unidade": "%",
        },
        {
            "nome_variavel": "duration_history_df.duration_days",
            "nome_exibido": "Prazo médio proxy agregado",
            "aba_origem": "Modo carteira",
            "bloco_ui_atual": "Prazo",
            "fonte_dado": "Buckets agregados de direitos a vencer",
            "formula": "Σ(bucket_a_vencer × prazo_proxy) / Σ(bucket_a_vencer)",
            "arquivo_py": "services/fundonet_portfolio_dashboard.py",
            "tipo": "prazo_estimado",
            "unidade": "dias",
        },
    ]
    return pd.DataFrame(rows)


def _build_portfolio_memory_df() -> pd.DataFrame:
    rows = [
        {
            "tipo_variavel": "Monetária",
            "bloco_executivo": "Topo da carteira",
            "componente": "Ativo total agregado",
            "variavel_final": "summary['ativos_totais']",
            "numerador": "Σ ativo_total_fundo",
            "denominador": "Não se aplica",
            "fonte_cvm": "APLIC_ATIVO/VL_SOM_APLIC_ATIVO",
            "fonte_efetiva": "Soma direta multi-CNPJ na mesma competência",
            "formula": "Σ ativo_total_f,t",
            "observacao": "A visão carteira não elimina relações entre fundos; soma apenas saldos standalone reportados.",
        },
        {
            "tipo_variavel": "Base canônica",
            "bloco_executivo": "Base comum",
            "componente": "Direitos creditórios totais agregados",
            "variavel_final": "summary['direitos_creditorios']",
            "numerador": "Σ dc_total_canonico_fundo",
            "denominador": "Não se aplica",
            "fonte_cvm": "Base canônica de DC por fundo",
            "fonte_efetiva": "Soma das bases canônicas individuais válidas",
            "formula": "Σ dc_total_canonico_f,t",
            "observacao": "É o denominador comum de crédito na carteira.",
        },
        {
            "tipo_variavel": "Percentual",
            "bloco_executivo": "Estrutura",
            "componente": "Subordinação reportada agregada",
            "variavel_final": "summary['subordinacao_pct']",
            "numerador": "Σ pl_mezzanino_fundo + Σ pl_subordinada_strict_fundo",
            "denominador": "Σ pl_total_fundo",
            "fonte_cvm": "OUTRAS_INFORM/DESC_SERIE_CLASSE",
            "fonte_efetiva": "Macroclasses agregadas por competência comum",
            "formula": "(Σ pl_mezzanino + Σ pl_subordinada_strict) / Σ pl_total * 100",
            "observacao": "Mezzanino fica segregado nas tabelas e no gráfico de PL, mas entra no numerador da subordinação reportada.",
        },
        {
            "tipo_variavel": "Bucket / distribuição",
            "bloco_executivo": "Crédito",
            "componente": "Inadimplência Over agregada",
            "variavel_final": "default_over_history_df.percentual",
            "numerador": "Σ buckets vencidos agregados acima do threshold",
            "denominador": "Σ dc_total_canonico",
            "fonte_cvm": "Buckets monetários de inadimplência por fundo",
            "fonte_efetiva": "Soma bucket a bucket antes da razão",
            "formula": "Over X = Σ(buckets >= X) / Σ dc_total_canonico * 100",
            "observacao": "Inclui Over 1 e nunca soma percentuais individuais.",
        },
        {
            "tipo_variavel": "Prazo / duration",
            "bloco_executivo": "Prazo",
            "componente": "Prazo médio proxy agregado",
            "variavel_final": "duration_history_df.duration_days",
            "numerador": "Σ(bucket_a_vencer × prazo_proxy)",
            "denominador": "Σ(bucket_a_vencer)",
            "fonte_cvm": "COMPMT_DICRED_AQUIS + COMPMT_DICRED_SEM_AQUIS",
            "fonte_efetiva": "Buckets agregados de direitos a vencer",
            "formula": "Σ(bucket_a_vencer × prazo_proxy) / Σ(bucket_a_vencer)",
            "observacao": "No modo carteira os vencidos saem do denominador do prazo médio.",
        },
    ]
    return pd.DataFrame(rows)


def _build_portfolio_consistency_df(
    *,
    coverage_df: pd.DataFrame,
    common_competencias: list[str],
    total_funds: int,
    maturity_history_df: pd.DataFrame,
    default_buckets_history_df: pd.DataFrame,
    default_history_df: pd.DataFrame,
    dc_canonical_history_df: pd.DataFrame,
) -> pd.DataFrame:
    latest = common_competencias[-1] if common_competencias else "N/D"
    incomplete_blocks = coverage_df[coverage_df["status"] != "Completo"].copy() if not coverage_df.empty else pd.DataFrame()
    incomplete_count = len(incomplete_blocks)
    latest_maturity = maturity_history_df[maturity_history_df["competencia"] == latest].copy() if latest != "N/D" else pd.DataFrame()
    latest_maturity_future = pd.to_numeric(
        latest_maturity[latest_maturity["faixa"] != "Vencidos"]["valor"],
        errors="coerce",
    ).sum(min_count=1) if not latest_maturity.empty else pd.NA
    latest_aging = default_buckets_history_df[default_buckets_history_df["competencia"] == latest].copy() if latest != "N/D" else pd.DataFrame()
    latest_aging_total = pd.to_numeric(latest_aging["valor"], errors="coerce").sum(min_count=1) if not latest_aging.empty else pd.NA
    latest_default_row = _exact_latest_row(default_history_df, latest)
    latest_inadimplencia = _float_or_none(latest_default_row.get("inadimplencia_total"))
    latest_dc_row = _exact_latest_row(dc_canonical_history_df, latest)
    latest_dc_avencer = _float_or_none(latest_dc_row.get("dc_a_vencer_canonico"))
    maturity_gap_pct: float | None
    if pd.isna(latest_maturity_future) or latest_dc_avencer is None or latest_dc_avencer <= 0:
        maturity_gap_pct = None
    else:
        maturity_gap_pct = abs(float(latest_maturity_future) - latest_dc_avencer) / max(float(latest_maturity_future), latest_dc_avencer) * 100.0
    rows = [
        {
            "tema": "Regra temporal da carteira",
            "status": "Alinhado",
            "checagem": "Competências usadas na visão agregada",
            "resultado": f"Interseção estrita aplicada em {len(common_competencias)} competência(s); última competência comum = {latest}.",
            "acao": "Não misturar fundos em competências diferentes na mesma leitura agregada.",
        },
        {
            "tema": "Cobertura analítica por bloco",
            "status": "Revisar" if incomplete_count else "Alinhado",
            "checagem": "Blocos completos na competência comum",
            "resultado": f"{incomplete_count} bloco(s) com cobertura incompleta na tabela de auditoria." if incomplete_count else "Todos os blocos ativos da carteira têm cobertura homogênea.",
            "acao": "Qualquer bloco incompleto fica como N/D ou é omitido da visão executiva.",
        },
        {
            "tema": "Malha de vencimento agregada",
            "status": (
                "Alinhado"
                if maturity_gap_pct is not None and maturity_gap_pct <= 1.0
                else "Revisar"
                if maturity_gap_pct is not None
                else "Sem base"
            ),
            "checagem": "Reconciliação entre buckets a vencer e dc_a_vencer_canonico",
            "resultado": (
                f"Soma dos buckets a vencer = {float(latest_maturity_future):,.2f}; dc_a_vencer_canonico = {latest_dc_avencer:,.2f}; gap = {maturity_gap_pct:.2f}%."
                if maturity_gap_pct is not None and latest_dc_avencer is not None and not pd.isna(latest_maturity_future)
                else "Sem base suficiente para reconciliar buckets a vencer com dc_a_vencer_canonico."
            ),
            "acao": "Manter a mesma malha agregada como base do gráfico de vencimento e do prazo médio da carteira.",
        },
        {
            "tema": "Malha de aging agregada",
            "status": (
                "Alinhado"
                if latest_inadimplencia is not None and not pd.isna(latest_aging_total) and abs(float(latest_aging_total) - latest_inadimplencia) <= 0.01
                else "Revisar"
                if latest_inadimplencia is not None and not pd.isna(latest_aging_total)
                else "Sem base"
            ),
            "checagem": "Reconciliação entre buckets monetários de aging e inadimplência total",
            "resultado": (
                f"Soma dos buckets de aging = {float(latest_aging_total):,.2f}; inadimplência total = {latest_inadimplencia:,.2f}."
                if latest_inadimplencia is not None and not pd.isna(latest_aging_total)
                else "Sem base suficiente para reconciliar buckets de aging com a inadimplência total."
            ),
            "acao": "Usar a mesma malha de aging como base do gráfico empilhado e das curvas Over."
        },
        {
            "tema": "Subordinação reportada",
            "status": "Alinhado",
            "checagem": "Tratamento de mezzanino",
            "resultado": "Mezzanino fica separado nas macroclasses de PL, mas entra no numerador da subordinação reportada agregada.",
            "acao": "Preservar a regra econômica em qualquer visão do painel.",
        },
        {
            "tema": "Rentabilidade no modo carteira",
            "status": "Alinhado",
            "checagem": "Blocos desabilitados por falta de base monetária comparável",
            "resultado": "Rentabilidade, benchmark e índices base 100 foram removidos da visão agregada.",
            "acao": "Manter desabilitado até existir metodologia monetária auditável no dado-fonte.",
        },
        {
            "tema": "Escopo contábil",
            "status": "Alinhado",
            "checagem": "Natureza da visão multi-CNPJ",
            "resultado": f"Leitura agregada auditável de {total_funds} fundo(s) standalone, sem consolidação societária formal.",
            "acao": "Explicitar esse escopo na UI, exports e memórias de cálculo.",
        },
    ]
    return pd.DataFrame(rows)


def _coverage_row(
    *,
    competencia: str,
    block_id: str,
    block_label: str,
    total_funds: int,
    missing_funds: set[str],
    note: str | None = None,
    status_override: str | None = None,
) -> dict[str, object]:
    funds_ready = total_funds - len(missing_funds)
    status = status_override or ("Completo" if not missing_funds else "Incompleto")
    return {
        "competencia": competencia,
        "competencia_dt": single._competencia_to_timestamp(competencia),
        "block_id": block_id,
        "block": block_label,
        "funds_expected": total_funds,
        "funds_ready": funds_ready,
        "status": status,
        "missing_funds": ", ".join(sorted(missing_funds)) if missing_funds else "",
        "observacao": note or "",
    }


def _finalize_coverage_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["competencia", "competencia_dt", "block_id", "block", "funds_expected", "funds_ready", "status", "missing_funds", "observacao"])
    return pd.DataFrame(rows).sort_values(["competencia_dt", "block"]).reset_index(drop=True)


def _exact_latest_row(df: pd.DataFrame, competencia: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype="object")
    match = df[df["competencia"] == competencia]
    if match.empty:
        return pd.Series(dtype="object")
    return match.sort_values("competencia_dt").iloc[-1]


def _latest_value(df: pd.DataFrame, competencia: str, column: str) -> object:
    row = _exact_latest_row(df, competencia)
    return row.get(column)


def _event_summary_value(df: pd.DataFrame, event_type: str, column: str) -> float | None:
    if df.empty or column not in df.columns:
        return None
    subset = df[df["event_type"] == event_type]
    if subset.empty:
        return None
    return _float_or_none(subset.iloc[-1].get(column))


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
