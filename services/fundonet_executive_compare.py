from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Sequence

import pandas as pd

from services.fundonet_dashboard import FundonetDashboardData
from services.identifier_utils import format_cnpj


MISSING_DISPLAY = "—"


Extractor = Callable[[FundonetDashboardData], object]


@dataclass(frozen=True)
class ExecutiveComparisonMetric:
    key: str
    label: str
    group: str
    default_visible: bool
    extractor: Extractor
    formatter: Callable[[object], str]


def build_executive_comparison_df(
    dashboards: Sequence[FundonetDashboardData],
    *,
    selected_metric_labels: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Build the executive comparison matrix from already-loaded dashboards.

    This function is presentation-only: it receives FundonetDashboardData objects
    that already exist in the Informe Mensal Estruturado / Visao Executiva flow
    and never reads files, calls Fundos.NET, or derives information from a new
    source.
    """
    selected_set = set(selected_metric_labels or [])
    active_metrics = [
        spec
        for spec in EXECUTIVE_COMPARISON_METRICS
        if not selected_set or spec.label in selected_set
    ]
    column_labels = dashboard_column_labels(dashboards)
    rows: list[dict[str, str]] = []
    for spec in active_metrics:
        row = {"Métrica": spec.label}
        values: list[str] = []
        for dashboard, column_label in zip(dashboards, column_labels):
            value = spec.formatter(spec.extractor(dashboard))
            row[column_label] = value
            values.append(value)
        if all(value == MISSING_DISPLAY for value in values):
            continue
        rows.append(row)
    return pd.DataFrame(rows, columns=["Métrica", *column_labels])


def available_comparison_metric_labels(dashboards: Sequence[FundonetDashboardData]) -> list[str]:
    labels: list[str] = []
    for spec in EXECUTIVE_COMPARISON_METRICS:
        values = [spec.formatter(spec.extractor(dashboard)) for dashboard in dashboards]
        if any(value != MISSING_DISPLAY for value in values):
            labels.append(spec.label)
    return labels


def default_comparison_metric_labels(dashboards: Sequence[FundonetDashboardData]) -> list[str]:
    available = set(available_comparison_metric_labels(dashboards))
    return [
        spec.label
        for spec in EXECUTIVE_COMPARISON_METRICS
        if spec.default_visible and spec.label in available
    ]


def dashboard_column_labels(dashboards: Sequence[FundonetDashboardData]) -> list[str]:
    base_labels = [_short_fund_name(dashboard.fund_info.get("nome_fundo")) for dashboard in dashboards]
    counts: dict[str, int] = {}
    output: list[str] = []
    for dashboard, label in zip(dashboards, base_labels):
        counts[label] = counts.get(label, 0) + 1
        if counts[label] == 1 and base_labels.count(label) == 1:
            output.append(label)
            continue
        cnpj = str(dashboard.fund_info.get("cnpj_fundo") or "").strip()
        suffix = cnpj[-4:] if cnpj else str(counts[label])
        output.append(f"{label} · {suffix}")
    return output


def _summary_value(key: str) -> Extractor:
    return lambda dashboard: dashboard.summary.get(key)


def _fund_info_value(key: str) -> Extractor:
    return lambda dashboard: dashboard.fund_info.get(key)


def _latest_over(series_name: str) -> Extractor:
    def extractor(dashboard: FundonetDashboardData) -> object:
        frame = dashboard.default_over_history_df
        if frame.empty:
            return None
        subset = frame[
            (frame["competencia"].astype(str) == str(dashboard.latest_competencia))
            & (frame["serie"].astype(str) == series_name)
        ].copy()
        if subset.empty:
            return None
        return subset.iloc[-1].get("percentual")

    return extractor


def _latest_duration_months(dashboard: FundonetDashboardData) -> object:
    frame = dashboard.duration_history_df
    if frame.empty:
        return None
    subset = frame[frame["competencia"].astype(str) == str(dashboard.latest_competencia)].copy()
    row = subset.iloc[-1] if not subset.empty else frame.sort_values("competencia_dt").iloc[-1]
    days = _to_float(row.get("duration_days"))
    if days is None:
        return None
    return days / 30.4375


def _pl_senior_pct(dashboard: FundonetDashboardData) -> object:
    senior = _to_float(dashboard.summary.get("pl_senior"))
    total = _to_float(dashboard.summary.get("pl_total"))
    if senior is None or total is None or total <= 0:
        return None
    return senior / total * 100.0


def _senior_return_month(dashboard: FundonetDashboardData) -> object:
    frame = dashboard.return_summary_df
    if frame.empty:
        return None
    class_kind = frame.get("class_kind", pd.Series(dtype="object")).astype(str).str.lower()
    subset = frame[class_kind == "senior"].copy()
    if subset.empty:
        return None
    return subset.iloc[0].get("retorno_mes_pct")


def _latest_event_pct_pl(event_type: str) -> Extractor:
    def extractor(dashboard: FundonetDashboardData) -> object:
        frame = dashboard.event_summary_latest_df
        if frame.empty:
            return None
        subset = frame[frame["event_type"].astype(str) == event_type].copy()
        if subset.empty:
            return None
        return subset.iloc[-1].get("valor_total_pct_pl")

    return extractor


def _format_text(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"N/D", "NONE", "NAN", "<NA>"}:
        return MISSING_DISPLAY
    return text


def _format_cnpj(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return MISSING_DISPLAY
    formatted = format_cnpj(text)
    return formatted if formatted != "N/D" else MISSING_DISPLAY


def _format_integer(value: object) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return MISSING_DISPLAY
    return _format_decimal(numeric, decimals=0)


def _format_money(value: object) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return MISSING_DISPLAY
    magnitude = abs(numeric)
    if magnitude >= 1_000_000_000_000:
        return f"R$ {_format_decimal(numeric / 1_000_000_000_000, decimals=1)} bi"
    if magnitude >= 1_000_000:
        return f"R$ {_format_decimal(numeric / 1_000_000, decimals=0)} mm"
    if magnitude >= 1_000:
        return f"R$ {_format_decimal(numeric / 1_000, decimals=0)} mil"
    return f"R$ {_format_decimal(numeric, decimals=0)}"


def _format_percent(value: object) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return MISSING_DISPLAY
    return f"{_format_decimal(numeric, decimals=1)}%"


def _format_months(value: object) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return MISSING_DISPLAY
    return f"{_format_decimal(numeric, decimals=1)} meses"


def _format_competencia(value: object) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{2})/(\d{4})", text)
    if not match:
        return _format_text(text)
    month_map = {
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
    month, year = match.groups()
    return f"{month_map.get(month, month)}-{year[-2:]}"


def _format_decimal(value: float, *, decimals: int) -> str:
    if value == 0:
        value = 0.0
    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _short_fund_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        return "FIDC"
    replacements = [
        r"\bFUNDO DE INVESTIMENTO EM DIREITOS\s+CREDIT[ÓO]RIOS\b",
        r"\bFUNDO DE INVESTIMENTO EM COTAS DE FUNDOS DE INVESTIMENTO EM DIREITOS\s+CREDIT[ÓO]RIOS\b",
        r"\bRESPONSABILIDADE LIMITADA\b",
        r"\bRESP\.?\s*LIMITADA\b",
        r"\bLIMITADA\b",
    ]
    short = name
    for pattern in replacements:
        short = re.sub(pattern, "", short, flags=re.IGNORECASE)
    short = re.sub(r"\s*[-–;|]\s*$", "", short)
    short = re.sub(r"\s+", " ", short).strip(" -;|")
    short = short or name
    if len(short) > 42:
        short = short[:39].rstrip() + "..."
    return short


EXECUTIVE_COMPARISON_METRICS: tuple[ExecutiveComparisonMetric, ...] = (
    ExecutiveComparisonMetric("competencia", "Competência", "Identificação", True, lambda d: d.latest_competencia, _format_competencia),
    ExecutiveComparisonMetric("cnpj", "CNPJ", "Identificação", True, _fund_info_value("cnpj_fundo"), _format_cnpj),
    ExecutiveComparisonMetric("administrador", "Administrador", "Identificação", True, _fund_info_value("nome_administrador"), _format_text),
    ExecutiveComparisonMetric("gestor", "Gestor", "Identificação", False, _fund_info_value("nome_gestor"), _format_text),
    ExecutiveComparisonMetric("custodiante", "Custodiante", "Identificação", False, _fund_info_value("nome_custodiante"), _format_text),
    ExecutiveComparisonMetric("cotistas", "Cotistas", "Identificação", False, _fund_info_value("total_cotistas"), _format_integer),
    ExecutiveComparisonMetric("ativo_total", "Ativo total", "Escala", True, _summary_value("ativos_totais"), _format_money),
    ExecutiveComparisonMetric("carteira", "Carteira", "Escala", True, _summary_value("carteira"), _format_money),
    ExecutiveComparisonMetric("dcs_totais", "Direitos creditórios", "Escala", True, _summary_value("direitos_creditorios"), _format_money),
    ExecutiveComparisonMetric("pl_total", "PL total", "Capital", True, _summary_value("pl_total"), _format_money),
    ExecutiveComparisonMetric("pl_senior", "PL sênior", "Capital", True, _summary_value("pl_senior"), _format_money),
    ExecutiveComparisonMetric("pl_senior_pct", "PL sênior / PL", "Capital", True, _pl_senior_pct, _format_percent),
    ExecutiveComparisonMetric("pl_mezzanino", "PL mezzanino", "Capital", True, _summary_value("pl_mezzanino"), _format_money),
    ExecutiveComparisonMetric("pl_subordinada", "PL subordinada + mezanino", "Capital", True, _summary_value("pl_subordinada"), _format_money),
    ExecutiveComparisonMetric("subordinacao", "Subordinação reportada", "Capital", True, _summary_value("subordinacao_pct"), _format_percent),
    ExecutiveComparisonMetric("vencidos", "Vencidos", "Crédito", True, _summary_value("inadimplencia_total"), _format_money),
    ExecutiveComparisonMetric("pdd", "PDD", "Crédito", True, _summary_value("provisao_total"), _format_money),
    ExecutiveComparisonMetric("cobertura", "Cobertura PDD / vencidos", "Crédito", True, _summary_value("cobertura_pct"), _format_percent),
    ExecutiveComparisonMetric("over30", "NPL Over 30", "Crédito", True, _latest_over("Over 30"), _format_percent),
    ExecutiveComparisonMetric("over60", "NPL Over 60", "Crédito", True, _latest_over("Over 60"), _format_percent),
    ExecutiveComparisonMetric("over90", "NPL Over 90", "Crédito", True, _latest_over("Over 90"), _format_percent),
    ExecutiveComparisonMetric("over180", "NPL Over 180", "Crédito", True, _latest_over("Over 180"), _format_percent),
    ExecutiveComparisonMetric("over360", "NPL Over 360", "Crédito", True, _latest_over("Over 360"), _format_percent),
    ExecutiveComparisonMetric("alocacao", "Alocação em DCs", "Prazo e liquidez", True, _summary_value("alocacao_pct"), _format_percent),
    ExecutiveComparisonMetric("liquidez_imediata", "Liquidez imediata", "Prazo e liquidez", False, _summary_value("liquidez_imediata"), _format_money),
    ExecutiveComparisonMetric("liquidez_30", "Liquidez até 30 dias", "Prazo e liquidez", False, _summary_value("liquidez_30"), _format_money),
    ExecutiveComparisonMetric("duration", "Duration proxy", "Prazo e liquidez", True, _latest_duration_months, _format_months),
    ExecutiveComparisonMetric("emissao_mes", "Emissão no mês", "Eventos", False, _summary_value("emissao_mes"), _format_money),
    ExecutiveComparisonMetric("resgate_mes", "Resgate no mês", "Eventos", False, _summary_value("resgate_mes"), _format_money),
    ExecutiveComparisonMetric("amortizacao_mes", "Amortização no mês", "Eventos", False, _summary_value("amortizacao_mes"), _format_money),
    ExecutiveComparisonMetric("resgate_solicitado_mes", "Resgate solicitado", "Eventos", False, _summary_value("resgate_solicitado_mes"), _format_money),
    ExecutiveComparisonMetric("emissao_pct_pl", "Emissão / PL", "Eventos", False, _latest_event_pct_pl("emissao"), _format_percent),
    ExecutiveComparisonMetric("retorno_senior_mes", "Retorno mês sênior disponível", "Rentabilidade", False, _senior_return_month, _format_percent),
)
