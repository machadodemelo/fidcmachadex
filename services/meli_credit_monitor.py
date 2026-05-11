from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


PT_MONTH_ABBR_TITLE = {
    1: "Jan",
    2: "Fev",
    3: "Mar",
    4: "Abr",
    5: "Mai",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Set",
    10: "Out",
    11: "Nov",
    12: "Dez",
}

MELI_PDF_TARGET_COMPETENCIA = "11/2025"
MELI_PDF_TARGETS: tuple[dict[str, object], ...] = (
    {
        "metric": "Carteira ex-360",
        "column": "carteira_ex360",
        "target": 7_141_000_000.0,
        "unit": "R$",
        "diagnostic": "Total Credit Portfolio (<360), em BRL mn.",
    },
    {
        "metric": "NPL 1-90d",
        "column": "npl_1_90",
        "target": 600_000_000.0,
        "unit": "R$",
        "diagnostic": "Soma das faixas NPL 1-30, 30-60 e 60-90 do PDF.",
    },
    {
        "metric": "NPL 91-360d",
        "column": "npl_91_360",
        "target": 1_012_000_000.0,
        "unit": "R$",
        "diagnostic": "Soma das faixas NPL 90-180 e 180-360 do PDF.",
    },
    {
        "metric": "NPL 1-90d / carteira ex-360",
        "column": "npl_1_90_pct",
        "target": 8.4,
        "unit": "%",
        "diagnostic": "NPL 1-90 dividido pela carteira ex-360.",
    },
    {
        "metric": "NPL 91-360d / carteira ex-360",
        "column": "npl_91_360_pct",
        "target": 14.2,
        "unit": "%",
        "diagnostic": "NPL 91-360 dividido pela carteira ex-360.",
    },
    {
        "metric": "NPL 1-360d / carteira ex-360",
        "column": "npl_1_360_pct",
        "target": 22.6,
        "unit": "%",
        "diagnostic": "NPL total de 1 a 360 dias dividido pela carteira ex-360.",
    },
    {
        "metric": "Crescimento m/m carteira ex-360",
        "column": "carteira_ex360_mom_pct",
        "target": 1.0,
        "unit": "%",
        "diagnostic": "Variação mensal arredondada no Chart 8/Tabela 1.",
    },
    {
        "metric": "Crescimento YoY carteira ex-360",
        "column": "carteira_ex360_yoy_pct",
        "target": 0.0,
        "unit": "%",
        "diagnostic": "Variação anual arredondada no Chart 7/Tabela 1.",
    },
    {
        "metric": "Roll 61-90 / carteira a vencer M-3",
        "column": "roll_61_90_m3_pct",
        "target": 3.0,
        "unit": "%",
        "diagnostic": "Chart 1: 61-90 sobre carteira a vencer de três meses antes.",
    },
    {
        "metric": "Roll 151-180 / carteira a vencer M-6",
        "column": "roll_151_180_m6_pct",
        "target": 2.7,
        "unit": "%",
        "diagnostic": "Chart 2: 151-180 sobre carteira a vencer de seis meses antes.",
    },
    {
        "metric": "Duration",
        "column": "duration_months",
        "target": 7.9,
        "unit": "meses",
        "diagnostic": "Chart 9: duration consolidada em meses.",
    },
)

MELI_PDF_UNAVAILABLE_TARGETS: tuple[dict[str, object], ...] = (
    {
        "metric": "PL total",
        "column": "pl_total",
        "unit": "R$",
        "diagnostic": "O PDF de research não traz PL por competência; app mantém valor para auditoria interna.",
    },
    {
        "metric": "% Subordinação",
        "column": "subordinacao_total_pct",
        "unit": "%",
        "diagnostic": "O PDF não publica subordinação; validar contra Informe Mensal/B3, não contra o PDF.",
    },
    {
        "metric": "PDD Ex Over 360d",
        "column": "pdd_ex360",
        "unit": "R$",
        "diagnostic": "O PDF não traz PDD; app calcula PDD ex-360 como PDD total menos baixa Over 360 limitada à PDD.",
    },
    {
        "metric": "PDD Ex / NPL Over 90d Ex 360",
        "column": "pdd_npl90_ex360_pct",
        "unit": "%",
        "diagnostic": "O PDF não traz cobertura; app mantém como métrica própria de acompanhamento.",
    },
    {
        "metric": "NPL Over 360d",
        "column": "npl_over360",
        "unit": "R$",
        "diagnostic": "O PDF exclui Over 360 da carteira de comparação; app mostra o estoque original antes da baixa ex-360.",
    },
)

MELI_MONITOR_METHODOLOGY_ROWS: tuple[dict[str, str], ...] = (
    {
        "Indicador": "Carteira ex-360",
        "Definição": "Carteira de crédito após baixa conceitual dos vencidos acima de 360 dias.",
        "Numerador": "carteira_bruta - npl_over360",
        "Denominador": "Não aplicável",
        "Fórmula": "carteira_ex360 = carteira_bruta - vencidos_360",
        "Unidade": "R$",
        "Fonte / coluna": "carteira_bruta; atraso_361_720; atraso_721_1080; atraso_1080",
        "Observação": "Remove o estoque acima de 360 dias para acompanhar a carteira limpa desse acúmulo.",
    },
    {
        "Indicador": "NPL 1-90d",
        "Definição": "Estoque vencido entre 1 e 90 dias.",
        "Numerador": "atraso_ate30 + atraso_31_60 + atraso_61_90",
        "Denominador": "Não aplicável",
        "Fórmula": "npl_1_90 = atraso_ate30 + atraso_31_60 + atraso_61_90",
        "Unidade": "R$",
        "Fonte / coluna": "Faixas de atraso do Informe Mensal Estruturado",
        "Observação": "Acompanha atrasos iniciais antes de migrarem para buckets mais severos.",
    },
    {
        "Indicador": "NPL 91-360d",
        "Definição": "Estoque vencido acima de 90 e até 360 dias.",
        "Numerador": "atraso_91_120 + atraso_121_150 + atraso_151_180 + atraso_181_360",
        "Denominador": "Não aplicável",
        "Fórmula": "npl_91_360 = atraso_91_120 + atraso_121_150 + atraso_151_180 + atraso_181_360",
        "Unidade": "R$",
        "Fonte / coluna": "Faixas de atraso do Informe Mensal Estruturado",
        "Observação": "Acompanha atrasos maduros sem incluir vencidos acima de 360 dias.",
    },
    {
        "Indicador": "NPL 1-90d / carteira",
        "Definição": "Atraso inicial como percentual da carteira ex-360.",
        "Numerador": "npl_1_90",
        "Denominador": "carteira_ex360",
        "Fórmula": "npl_1_90_pct = npl_1_90 / carteira_ex360",
        "Unidade": "%",
        "Fonte / coluna": "npl_1_90; carteira_ex360",
        "Observação": "No consolidado, soma numeradores e denominadores antes de dividir.",
    },
    {
        "Indicador": "NPL 91-360d / carteira",
        "Definição": "Atraso maduro como percentual da carteira ex-360.",
        "Numerador": "npl_91_360",
        "Denominador": "carteira_ex360",
        "Fórmula": "npl_91_360_pct = npl_91_360 / carteira_ex360",
        "Unidade": "%",
        "Fonte / coluna": "npl_91_360; carteira_ex360",
        "Observação": "Não inclui vencidos acima de 360 dias.",
    },
    {
        "Indicador": "Roll 61-90 / carteira a vencer M-3",
        "Definição": "Parcela que migra para 61-90 dias vencidos contra a carteira a vencer três meses antes.",
        "Numerador": "atraso_61_90_t",
        "Denominador": "carteira_a_vencer_t-3",
        "Fórmula": "roll_61_90_m3_pct = atraso_61_90_t / carteira_a_vencer_t-3",
        "Unidade": "%",
        "Fonte / coluna": "atraso_61_90; carteira_a_vencer",
        "Observação": "Usa a carteira a vencer de três meses antes como aproximação da safra exposta ao atraso 61-90.",
    },
    {
        "Indicador": "Roll 91-120 / carteira a vencer M-4",
        "Definição": "Parcela que migra para 91-120 dias vencidos contra a carteira a vencer quatro meses antes.",
        "Numerador": "atraso_91_120_t",
        "Denominador": "carteira_a_vencer_t-4",
        "Fórmula": "roll_91_120_m4_pct = atraso_91_120_t / carteira_a_vencer_t-4",
        "Unidade": "%",
        "Fonte / coluna": "atraso_91_120; carteira_a_vencer",
        "Observação": "Usa a carteira a vencer de quatro meses antes como aproximação da safra exposta ao atraso 91-120.",
    },
    {
        "Indicador": "Roll 121-150 / carteira a vencer M-5",
        "Definição": "Parcela que migra para 121-150 dias vencidos contra a carteira a vencer cinco meses antes.",
        "Numerador": "atraso_121_150_t",
        "Denominador": "carteira_a_vencer_t-5",
        "Fórmula": "roll_121_150_m5_pct = atraso_121_150_t / carteira_a_vencer_t-5",
        "Unidade": "%",
        "Fonte / coluna": "atraso_121_150; carteira_a_vencer",
        "Observação": "Usa a carteira a vencer de cinco meses antes como aproximação da safra exposta ao atraso 121-150.",
    },
    {
        "Indicador": "Roll 151-180 / carteira a vencer M-6",
        "Definição": "Parcela que migra para 151-180 dias vencidos contra a carteira a vencer seis meses antes.",
        "Numerador": "atraso_151_180_t",
        "Denominador": "carteira_a_vencer_t-6",
        "Fórmula": "roll_151_180_m6_pct = atraso_151_180_t / carteira_a_vencer_t-6",
        "Unidade": "%",
        "Fonte / coluna": "atraso_151_180; carteira_a_vencer",
        "Observação": "Usa a carteira a vencer de seis meses antes como aproximação da safra exposta ao atraso 151-180.",
    },
    {
        "Indicador": "Cohorts M1-M6",
        "Definição": "Safra proxy mensal baseada no saldo que estava a vencer em até 30 dias no mês-base e sua migração para atraso nos meses seguintes.",
        "Numerador": "bucket futuro de atraso alinhado ao mês de maturação: M1=até 30d no mês seguinte; M2=31-60d dois meses depois; M3=61-90d três meses depois; M4=91-120d quatro meses depois; M5=121-150d cinco meses depois; M6=151-180d seis meses depois",
        "Denominador": "prazo_venc_30 da competência-base",
        "Fórmula": "cohort_m = atraso_bucket_t+m / prazo_venc_30_t",
        "Unidade": "%",
        "Fonte / coluna": "prazo_venc_30; buckets de atraso",
        "Observação": "Exemplo: se Fev-26 tinha R$ 100 milhões a vencer em até 30 dias e Mar-26 tem R$ 39,6 milhões em atraso até 30d, M1 = 39,6%.",
    },
    {
        "Indicador": "Duration",
        "Definição": "Prazo médio ponderado da carteira pela malha de vencimentos, usando proxy de prazo por bucket.",
        "Numerador": "duration_weighted_days",
        "Denominador": "duration_total_saldo",
        "Fórmula": "duration_months = (Σ saldo_bucket × prazo_proxy_bucket / Σ saldo_bucket) / 30,4375",
        "Unidade": "meses",
        "Fonte / coluna": "Malha de vencimentos do Informe Mensal Estruturado",
        "Observação": "30,4375 = 365,25 / 12. Exemplo de proxy: a faixa 61-90 dias usa 75,5 dias, ponto médio entre 61 e 90. No consolidado, a ponderação é por saldo.",
    },
    {
        "Indicador": "PDD Ex / NPL Over 90d Ex 360",
        "Definição": "Cobertura de PDD remanescente sobre NPL Over 90d após baixa ex-360.",
        "Numerador": "pdd_ex360",
        "Denominador": "npl_over90_ex360",
        "Fórmula": "pdd_npl90_ex360_pct = pdd_ex360 / npl_over90_ex360",
        "Unidade": "%",
        "Fonte / coluna": "pdd_total; npl_over90; npl_over360",
        "Observação": "PDD ex-360 não é PDD segmentada por faixa; é PDD total deduzida da baixa Over 360.",
    },
)

MELI_CHART_AXIS_ROWS: tuple[dict[str, str], ...] = (
    {
        "Gráfico": "Roll rates",
        "Eixo esquerdo": "Roll 61-90 M-3, 91-120 M-4, 121-150 M-5 e 151-180 M-6 em %",
        "Eixo direito": "Não usado",
        "Observação": "Séries têm mesma unidade e ordem de grandeza.",
    },
    {
        "Gráfico": "NPL ex-360 por severidade",
        "Eixo esquerdo": "NPL 1-90d e NPL 91-360d como % da carteira ex-360",
        "Eixo direito": "Não usado",
        "Observação": "Barras empilhadas para decompor o NPL remanescente após baixa conceitual de vencidos acima de 360 dias.",
    },
    {
        "Gráfico": "Carteira ex-360 e crescimento",
        "Eixo esquerdo": "Carteira ex-360 em R$ com escala dinâmica",
        "Eixo direito": "Crescimento YoY em %",
        "Observação": "Valores monetários e percentuais ficam em eixos independentes.",
    },
    {
        "Gráfico": "Duration por FIDC",
        "Eixo esquerdo": "Duration em meses",
        "Eixo direito": "Não usado",
        "Observação": "Consolidado é ponderado por saldo.",
    },
    {
        "Gráfico": "Cohorts recentes",
        "Eixo esquerdo": "% do saldo a vencer em 30 dias",
        "Eixo direito": "Não usado",
        "Observação": "Cada linha representa uma safra proxy; M1-M6 mostram maturação de atraso contra a mesma base inicial.",
    },
)

MATURITY_CURRENT_COLUMNS: tuple[str, ...] = (
    "prazo_venc_30",
    "prazo_venc_31_60",
    "prazo_venc_61_90",
    "prazo_venc_91_120",
    "prazo_venc_121_150",
    "prazo_venc_151_180",
    "prazo_venc_181_360",
    "prazo_venc_361_720",
    "prazo_venc_721_1080",
    "prazo_venc_1080",
)

EXPECTED_MELI_CREDIT_FUND_TYPES: tuple[str, ...] = (
    "Mercado Crédito",
    "Mercado Crédito I",
    "Mercado Crédito II",
)

COHORT_STEPS: tuple[tuple[str, str, int], ...] = (
    ("M1", "atraso_ate30", 1),
    ("M2", "atraso_31_60", 2),
    ("M3", "atraso_61_90", 3),
    ("M4", "atraso_91_120", 4),
    ("M5", "atraso_121_150", 5),
    ("M6", "atraso_151_180", 6),
)


@dataclass(frozen=True)
class MeliMonitorOutputs:
    consolidated_monitor: pd.DataFrame
    fund_monitor: dict[str, pd.DataFrame]
    consolidated_cohorts: pd.DataFrame
    fund_cohorts: dict[str, pd.DataFrame]
    audit_table: pd.DataFrame
    pdf_reconciliation: pd.DataFrame
    warnings: list[str]


def build_meli_methodology_table() -> pd.DataFrame:
    return pd.DataFrame(MELI_MONITOR_METHODOLOGY_ROWS)


def build_meli_chart_axis_table() -> pd.DataFrame:
    return pd.DataFrame(MELI_CHART_AXIS_ROWS)


def build_somatorio_dashboard_comparison(outputs: Any, monitor_outputs: MeliMonitorOutputs) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    scopes = [("Consolidado", "", getattr(outputs, "consolidated_monthly", pd.DataFrame()), monitor_outputs.consolidated_monitor)]
    for cnpj, somatorio_frame in getattr(outputs, "fund_monthly", {}).items():
        dashboard_frame = monitor_outputs.fund_monitor.get(cnpj, pd.DataFrame())
        fund_name = _frame_fund_name(dashboard_frame, fallback=str(cnpj))
        scopes.append((fund_name, str(cnpj), somatorio_frame, dashboard_frame))
    for scope_name, cnpj, somatorio_frame, dashboard_frame in scopes:
        rows.extend(_compare_somatorio_dashboard_scope(scope_name, cnpj, somatorio_frame, dashboard_frame))
    return pd.DataFrame(rows)


def build_ex360_memory_table(outputs: Any) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    consolidated = getattr(outputs, "consolidated_monthly", pd.DataFrame())
    if consolidated is not None and not consolidated.empty:
        frames.append(_ex360_memory_scope("Consolidado", "", consolidated))
    for cnpj, frame in getattr(outputs, "fund_monthly", {}).items():
        name = _frame_fund_name(frame, fallback=str(cnpj))
        frames.append(_ex360_memory_scope(name, str(cnpj), frame))
    return pd.concat([frame for frame in frames if not frame.empty], ignore_index=True, sort=False) if frames else pd.DataFrame()


def build_meli_monitor_outputs(outputs) -> MeliMonitorOutputs:  # noqa: ANN001
    fund_monitor: dict[str, pd.DataFrame] = {}
    fund_cohorts: dict[str, pd.DataFrame] = {}
    warnings: list[str] = []
    for cnpj, monthly in getattr(outputs, "fund_monthly", {}).items():
        monitor = build_monitor_base(monthly)
        fund_monitor[cnpj] = monitor
        fund_cohorts[cnpj] = build_cohort_matrix(monitor)
        warnings.extend(_monitor_warnings(monitor, scope=cnpj))

    consolidated_monitor = build_monitor_base(getattr(outputs, "consolidated_monthly", pd.DataFrame()))
    consolidated_cohorts = build_cohort_matrix(consolidated_monitor)
    warnings.extend(_monitor_warnings(consolidated_monitor, scope="CONSOLIDADO"))
    warnings.extend(_universe_warnings(fund_monitor))
    audit_table = build_monitor_audit_table(consolidated_monitor=consolidated_monitor, fund_monitor=fund_monitor)
    pdf_reconciliation = build_pdf_reconciliation_table(consolidated_monitor)
    return MeliMonitorOutputs(
        consolidated_monitor=consolidated_monitor,
        fund_monitor=fund_monitor,
        consolidated_cohorts=consolidated_cohorts,
        fund_cohorts=fund_cohorts,
        audit_table=audit_table,
        pdf_reconciliation=pdf_reconciliation,
        warnings=warnings,
    )


def build_monitor_base(monthly_df: pd.DataFrame) -> pd.DataFrame:
    if monthly_df is None or monthly_df.empty:
        return _empty_monitor_base()
    df = monthly_df.copy()
    if "competencia_dt" not in df.columns:
        df["competencia_dt"] = pd.to_datetime(df.get("competencia"), errors="coerce")
    else:
        df["competencia_dt"] = pd.to_datetime(df["competencia_dt"], errors="coerce")
    df = df.sort_values("competencia_dt").reset_index(drop=True)
    _ensure_numeric_columns(
        df,
        [
            "carteira_ex360",
            "carteira_bruta",
            "carteira_em_dia",
            "carteira_a_vencer",
            "atraso_ate30",
            "atraso_31_60",
            "atraso_61_90",
            "atraso_91_120",
            "atraso_121_150",
            "atraso_151_180",
            "atraso_181_360",
            *MATURITY_CURRENT_COLUMNS,
            "pdd_ex360",
            "npl_over90_ex360",
            "duration_months",
        ],
    )
    derived_current = df[list(MATURITY_CURRENT_COLUMNS)].sum(axis=1, min_count=1)
    df["carteira_a_vencer"] = df["carteira_a_vencer"].where(df["carteira_a_vencer"].notna(), derived_current)
    df["npl_1_90"] = df[["atraso_ate30", "atraso_31_60", "atraso_61_90"]].sum(axis=1, min_count=1)
    df["npl_91_360"] = df[["atraso_91_120", "atraso_121_150", "atraso_151_180", "atraso_181_360"]].sum(axis=1, min_count=1)
    df["npl_1_90_pct"] = _safe_div_pct(df["npl_1_90"], df["carteira_ex360"])
    df["npl_91_360_pct"] = _safe_div_pct(df["npl_91_360"], df["carteira_ex360"])
    df["npl_1_360_pct"] = _safe_div_pct(df["npl_1_90"] + df["npl_91_360"], df["carteira_ex360"])
    df["roll_61_90_m3_den"] = df["carteira_a_vencer"].shift(3)
    df["roll_91_120_m4_den"] = df["carteira_a_vencer"].shift(4)
    df["roll_121_150_m5_den"] = df["carteira_a_vencer"].shift(5)
    df["roll_151_180_m6_den"] = df["carteira_a_vencer"].shift(6)
    df["roll_61_90_m3_pct"] = _safe_div_pct(df["atraso_61_90"], df["roll_61_90_m3_den"])
    df["roll_91_120_m4_pct"] = _safe_div_pct(df["atraso_91_120"], df["roll_91_120_m4_den"])
    df["roll_121_150_m5_pct"] = _safe_div_pct(df["atraso_121_150"], df["roll_121_150_m5_den"])
    df["roll_151_180_m6_pct"] = _safe_div_pct(df["atraso_151_180"], df["roll_151_180_m6_den"])
    df["carteira_ex360_mom_pct"] = df["carteira_ex360"].pct_change(fill_method=None) * 100.0
    df["carteira_ex360_yoy_pct"] = (df["carteira_ex360"] / df["carteira_ex360"].shift(12) - 1.0) * 100.0
    df["pdd_npl90_ex360_pct"] = _safe_div_pct(df["pdd_ex360"], df["npl_over90_ex360"])
    return df


def build_cohort_matrix(monitor_df: pd.DataFrame) -> pd.DataFrame:
    if monitor_df is None or monitor_df.empty:
        return pd.DataFrame(columns=["cohort", "cohort_dt", "mes_ciclo", "ordem", "valor_pct", "numerador", "denominador"])
    df = monitor_df.sort_values("competencia_dt").reset_index(drop=True).copy()
    rows: list[dict[str, object]] = []
    for idx, row in df.iterrows():
        denominator = _num(row.get("prazo_venc_30"))
        if denominator is None or denominator <= 0:
            continue
        cohort = _format_cohort_label(row.get("competencia_dt"), row.get("competencia"))
        for order, (label, bucket_col, lag_months) in enumerate(COHORT_STEPS, start=1):
            future_idx = idx + lag_months
            if future_idx >= len(df):
                continue
            numerator = _num(df.iloc[future_idx].get(bucket_col))
            if numerator is None:
                continue
            rows.append(
                {
                    "cohort": cohort,
                    "cohort_dt": row.get("competencia_dt"),
                    "mes_ciclo": label,
                    "ordem": order,
                    "valor_pct": numerator / denominator * 100.0,
                    "numerador": numerator,
                    "denominador": denominator,
                }
            )
    return pd.DataFrame(rows)


def build_monitor_audit_table(*, consolidated_monitor: pd.DataFrame, fund_monitor: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for frame in [consolidated_monitor, *fund_monitor.values()]:
        if frame is None or frame.empty:
            continue
        cols = [
            "fund_name",
            "cnpj",
            "competencia",
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
            "npl_1_90_pct",
            "npl_91_360_pct",
            "roll_61_90_m3_pct",
            "roll_61_90_m3_den",
            "roll_91_120_m4_pct",
            "roll_91_120_m4_den",
            "roll_121_150_m5_pct",
            "roll_121_150_m5_den",
            "roll_151_180_m6_pct",
            "roll_151_180_m6_den",
            "duration_months",
            "carteira_ex360_mom_pct",
            "carteira_ex360_yoy_pct",
            "pdd_npl90_ex360_pct",
        ]
        available = [col for col in cols if col in frame.columns]
        frames.append(frame[available].copy())
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _compare_somatorio_dashboard_scope(
    scope_name: str,
    cnpj: str,
    somatorio_frame: pd.DataFrame,
    dashboard_frame: pd.DataFrame,
) -> list[dict[str, object]]:
    if somatorio_frame is None or dashboard_frame is None or somatorio_frame.empty or dashboard_frame.empty:
        return []
    somatorio = _comparison_base(somatorio_frame)
    dashboard = _comparison_base(dashboard_frame)
    merged = somatorio.merge(dashboard, on="competencia", suffixes=("_somatorio", "_dashboard"), how="inner")
    rows: list[dict[str, object]] = []
    for _, row in merged.iterrows():
        rows.extend(
            [
                _comparison_row(
                    scope_name,
                    cnpj,
                    row,
                    metric="Carteira ex-360",
                    somatorio_value=row.get("carteira_ex360_somatorio"),
                    dashboard_value=row.get("carteira_ex360_dashboard"),
                    unit="R$",
                    formula_somatorio="carteira_bruta - npl_over360",
                    formula_dashboard="carteira_ex360 herdada da Soma de FIDCs",
                ),
                _comparison_row(
                    scope_name,
                    cnpj,
                    row,
                    metric="NPL ex-360 total",
                    somatorio_value=row.get("npl_over1_ex360_somatorio"),
                    dashboard_value=_sum_values(row.get("npl_1_90_dashboard"), row.get("npl_91_360_dashboard")),
                    unit="R$",
                    formula_somatorio="npl_over1 - npl_over360",
                    formula_dashboard="npl_1_90 + npl_91_360",
                ),
                _comparison_row(
                    scope_name,
                    cnpj,
                    row,
                    metric="NPL ex-360 total / carteira ex-360",
                    somatorio_value=row.get("npl_over1_ex360_pct_somatorio"),
                    dashboard_value=row.get("npl_1_360_pct_dashboard"),
                    unit="%",
                    formula_somatorio="npl_over1_ex360 / carteira_ex360",
                    formula_dashboard="(npl_1_90 + npl_91_360) / carteira_ex360",
                ),
                _comparison_row(
                    scope_name,
                    cnpj,
                    row,
                    metric="NPL 1-90d / carteira ex-360",
                    somatorio_value=_safe_div_scalar(_subtract_values(row.get("npl_over1_ex360_somatorio"), row.get("npl_over90_ex360_somatorio")), row.get("carteira_ex360_somatorio")),
                    dashboard_value=row.get("npl_1_90_pct_dashboard"),
                    unit="%",
                    formula_somatorio="(npl_over1_ex360 - npl_over90_ex360) / carteira_ex360",
                    formula_dashboard="npl_1_90 / carteira_ex360",
                ),
                _comparison_row(
                    scope_name,
                    cnpj,
                    row,
                    metric="NPL 91-360d / carteira ex-360",
                    somatorio_value=row.get("npl_over90_ex360_pct_somatorio"),
                    dashboard_value=row.get("npl_91_360_pct_dashboard"),
                    unit="%",
                    formula_somatorio="npl_over90_ex360 / carteira_ex360",
                    formula_dashboard="npl_91_360 / carteira_ex360",
                ),
                _comparison_row(
                    scope_name,
                    cnpj,
                    row,
                    metric="Duration (dias)",
                    somatorio_value=row.get("duration_days_somatorio"),
                    dashboard_value=row.get("duration_days_dashboard"),
                    unit="dias",
                    formula_somatorio="Σ saldo_bucket × prazo_proxy_bucket / Σ saldo_bucket",
                    formula_dashboard="mesma coluna duration_days herdada do Somatório",
                ),
                _comparison_row(
                    scope_name,
                    cnpj,
                    row,
                    metric="Duration (meses)",
                    somatorio_value=row.get("duration_months_somatorio"),
                    dashboard_value=row.get("duration_months_dashboard"),
                    unit="meses",
                    formula_somatorio="duration_days / 30,4375",
                    formula_dashboard="duration_days / 30,4375",
                ),
            ]
        )
    return rows


def _comparison_base(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    keep = [
        "competencia",
        "competencia_dt",
        "carteira_bruta",
        "vencidos_360",
        "npl_over360",
        "carteira_ex360",
        "npl_over1_ex360",
        "npl_over1_ex360_pct",
        "npl_over90_ex360",
        "npl_over90_ex360_pct",
        "npl_1_90",
        "npl_91_360",
        "npl_1_90_pct",
        "npl_91_360_pct",
        "npl_1_360_pct",
        "duration_days",
        "duration_months",
    ]
    for column in keep:
        if column not in df.columns:
            df[column] = pd.NA
    return df[keep].copy()


def _comparison_row(
    scope_name: str,
    cnpj: str,
    row: pd.Series,
    *,
    metric: str,
    somatorio_value: object,
    dashboard_value: object,
    unit: str,
    formula_somatorio: str,
    formula_dashboard: str,
) -> dict[str, object]:
    somatorio = _num(somatorio_value)
    dashboard = _num(dashboard_value)
    diff = None if somatorio is None or dashboard is None else dashboard - somatorio
    rel = None if diff is None or somatorio in (None, 0) else abs(diff / somatorio) * 100.0
    tolerance = 0.000001 if unit in {"%", "meses", "dias"} else 0.01
    if somatorio is None and dashboard is None:
        status = "OK"
    elif somatorio is None or dashboard is None:
        status = "ALERTA"
    elif abs(diff or 0.0) <= tolerance or (rel is not None and rel <= 0.1):
        status = "OK"
    else:
        status = "DIVERGENTE"
    return {
        "escopo": scope_name,
        "cnpj": cnpj,
        "competencia": row.get("competencia"),
        "metrica": metric,
        "somatorio": somatorio,
        "dashboard_meli": dashboard,
        "diferenca_abs": diff,
        "diferenca_rel_pct": rel,
        "unidade": unit,
        "status": status,
        "formula_somatorio": formula_somatorio,
        "formula_dashboard": formula_dashboard,
    }


def _ex360_memory_scope(scope_name: str, cnpj: str, frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    columns = [
        "competencia",
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
    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
    out = df[columns].copy()
    out.insert(0, "escopo", scope_name)
    out.insert(1, "cnpj", cnpj)
    out["formula_carteira_ex360"] = "carteira_bruta - npl_over360"
    out["formula_pl_ex360"] = "pl_total - max(npl_over360 - baixa_over360_pdd, 0)"
    return out


def build_pdf_reconciliation_table(monitor_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["Métrica", "Competência", "Valor app", "Valor PDF", "Diferença", "Unidade", "Status", "Diagnóstico"]
    if monitor_df is None or monitor_df.empty:
        return pd.DataFrame(
            [
                {
                    "Métrica": "PDF MELI",
                    "Competência": MELI_PDF_TARGET_COMPETENCIA,
                    "Valor app": pd.NA,
                    "Valor PDF": pd.NA,
                    "Diferença": pd.NA,
                    "Unidade": "",
                    "Status": "Base consolidada vazia.",
                    "Diagnóstico": "Carregue uma carteira com dados para comparar contra o PDF.",
                }
            ],
            columns=columns,
        )
    df = monitor_df.copy()
    competencia_text = df.get("competencia", pd.Series(index=df.index, dtype="object")).astype(str)
    target_rows = df[competencia_text.eq(MELI_PDF_TARGET_COMPETENCIA)]
    if target_rows.empty:
        return pd.DataFrame(
            [
                {
                    "Métrica": "PDF MELI",
                    "Competência": MELI_PDF_TARGET_COMPETENCIA,
                    "Valor app": pd.NA,
                    "Valor PDF": pd.NA,
                    "Diferença": pd.NA,
                    "Unidade": "",
                    "Status": "Competência 11/2025 ausente na janela carregada.",
                    "Diagnóstico": "Carregue uma janela que contenha nov/25 para rodar a comparação.",
                }
            ],
            columns=columns,
        )
    row = target_rows.iloc[-1]
    rows: list[dict[str, object]] = []
    for target in MELI_PDF_TARGETS:
        app_value = _num(row.get(str(target["column"])))
        pdf_value = float(target["target"])
        diff = app_value - pdf_value if app_value is not None else pd.NA
        rows.append(
            {
                "Métrica": target["metric"],
                "Competência": MELI_PDF_TARGET_COMPETENCIA,
                "Valor app": app_value,
                "Valor PDF": pdf_value,
                "Diferença": diff,
                "Unidade": target["unit"],
                "Status": _reconciliation_status(diff, unit=str(target["unit"])),
                "Diagnóstico": target["diagnostic"],
            }
        )
    for target in MELI_PDF_UNAVAILABLE_TARGETS:
        app_value = _num(row.get(str(target["column"])))
        rows.append(
            {
                "Métrica": target["metric"],
                "Competência": MELI_PDF_TARGET_COMPETENCIA,
                "Valor app": app_value,
                "Valor PDF": pd.NA,
                "Diferença": pd.NA,
                "Unidade": target["unit"],
                "Status": "Sem alvo no PDF.",
                "Diagnóstico": target["diagnostic"],
            }
        )
    return pd.DataFrame(rows, columns=columns)


def latest_row(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype="object")
    return df.sort_values("competencia_dt").iloc[-1]


def _monitor_warnings(df: pd.DataFrame, *, scope: str) -> list[str]:
    if df is None or df.empty:
        return [f"{scope}: base vazia."]
    warnings: list[str] = []
    if "prazo_venc_30" not in df.columns or pd.to_numeric(df["prazo_venc_30"], errors="coerce").fillna(0).le(0).all():
        warnings.append(f"{scope}: cohorts não calculáveis porque a carteira a vencer em 30 dias está ausente ou zerada.")
    if "carteira_a_vencer" not in df.columns or pd.to_numeric(df["carteira_a_vencer"], errors="coerce").fillna(0).le(0).all():
        warnings.append(f"{scope}: roll rates não calculáveis porque a carteira a vencer total está ausente ou zerada.")
    if "duration_months" not in df.columns or pd.to_numeric(df["duration_months"], errors="coerce").isna().all():
        warnings.append(f"{scope}: duration não calculável pela malha de vencimentos.")
    return warnings


def _universe_warnings(fund_monitor: dict[str, pd.DataFrame]) -> list[str]:
    if not fund_monitor:
        return []
    fund_types: set[str] = set()
    unexpected: list[str] = []
    for cnpj, frame in fund_monitor.items():
        name = str(frame["fund_name"].dropna().iloc[0]) if frame is not None and not frame.empty and "fund_name" in frame.columns and frame["fund_name"].notna().any() else cnpj
        normalized = _normalize_text(name)
        fund_type = _classify_meli_credit_fund(normalized)
        if fund_type:
            fund_types.add(fund_type)
        if any(token in normalized for token in ("seller", "factoring", "antecip", "vendedor", "fornecedor")):
            unexpected.append(name)
    warnings: list[str] = []
    missing = [fund_type for fund_type in EXPECTED_MELI_CREDIT_FUND_TYPES if fund_type not in fund_types]
    if missing:
        warnings.append("Universo MELI: fundos de crédito esperados ausentes ou sem nome reconhecido: " + ", ".join(missing) + ".")
    if unexpected:
        warnings.append("Universo MELI: a carteira contém fundos com perfil possivelmente fora do universo de crédito acompanhado: " + ", ".join(unexpected) + ".")
    return warnings


def _classify_meli_credit_fund(normalized_name: str) -> str | None:
    if "mercado credito ii" in normalized_name or "mercado credito 2" in normalized_name:
        return "Mercado Crédito II"
    if "mercado credito i" in normalized_name or "mercado credito 1" in normalized_name:
        return "Mercado Crédito I"
    if "mercado credito" in normalized_name:
        return "Mercado Crédito"
    return None


def _ensure_numeric_columns(df: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
        df[column] = pd.to_numeric(df[column], errors="coerce")


def _safe_div_pct(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce")
    return (num / den).where(den > 0).mul(100.0)


def _reconciliation_status(diff: object, *, unit: str) -> str:
    numeric = _num(diff)
    if numeric is None:
        return "Não calculável no app."
    tolerance = 0.15 if unit in {"%", "meses"} else 1_000_000.0
    if abs(numeric) <= tolerance:
        return "OK dentro da tolerância."
    return "Divergente."


def _sum_values(*values: object) -> float | None:
    parsed = [_num(value) for value in values]
    valid = [value for value in parsed if value is not None]
    if not valid:
        return None
    return float(sum(valid))


def _subtract_values(left: object, right: object) -> float | None:
    left_num = _num(left)
    right_num = _num(right)
    if left_num is None or right_num is None:
        return None
    return float(left_num - right_num)


def _safe_div_scalar(numerator: object, denominator: object) -> float | None:
    num = _num(numerator)
    den = _num(denominator)
    if num is None or den is None or den <= 0:
        return None
    return float(num / den * 100.0)


def _frame_fund_name(frame: pd.DataFrame, *, fallback: str) -> str:
    if frame is not None and not frame.empty and "fund_name" in frame.columns and frame["fund_name"].notna().any():
        return str(frame["fund_name"].dropna().iloc[0])
    return fallback


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _format_competencia(competencia_dt: object, fallback: object) -> str:
    ts = pd.to_datetime(competencia_dt, errors="coerce")
    if pd.isna(ts):
        return str(fallback or "N/D")
    return f"{int(ts.month):02d}/{int(ts.year)}"


def _format_cohort_label(competencia_dt: object, fallback: object) -> str:
    ts = pd.to_datetime(competencia_dt, errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(fallback, errors="coerce")
    if pd.isna(ts):
        return str(fallback or "N/D")
    month = PT_MONTH_ABBR_TITLE.get(int(ts.month), f"{int(ts.month):02d}")
    return f"{month}-{str(int(ts.year))[-2:]}"


def _normalize_text(value: object) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.lower().replace("-", " ").replace("_", " ").split())


def _empty_monitor_base() -> pd.DataFrame:
    return pd.DataFrame(columns=["fund_name", "cnpj", "competencia", "competencia_dt"])
