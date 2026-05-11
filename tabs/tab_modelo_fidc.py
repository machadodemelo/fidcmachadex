from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from html import escape
from io import BytesIO

import altair as alt
import pandas as pd
import streamlit as st

from data_loader import load_model_inputs
from services.fidc_model import (
    AMORTIZATION_MODE_BULLET,
    AMORTIZATION_MODE_LINEAR,
    AMORTIZATION_MODE_NONE,
    AMORTIZATION_MODE_WORKBOOK,
    CREDIT_MODEL_MIGRATION,
    CREDIT_MODEL_NPL90,
    INTEREST_PAYMENT_MODE_AFTER_GRACE,
    INTEREST_PAYMENT_MODE_BULLET,
    INTEREST_PAYMENT_MODE_PERIODIC,
    INTERPOLATION_METHOD_FLAT_FORWARD_252,
    INTERPOLATION_METHOD_SPLINE,
    RATE_MODE_POST_CDI,
    RATE_MODE_PRE,
    Premissas,
    annual_252_to_monthly_rate,
    build_flow,
    build_kpis,
    cession_discount_to_monthly_rate,
    monthly_to_annual_252_rate,
    monthly_rate_to_cession_discount,
)
from services.fidc_model.b3_curves import (
    B3CurveError,
    B3CurveSnapshot,
    DEFAULT_TAXASWAP_CURVE_CODE,
    fetch_latest_taxaswap_curve,
    fetch_taxaswap_curve,
)
from services.fidc_model.calendar import (
    B3CalendarError,
    B3CalendarSnapshot,
    build_b3_calendar_snapshot,
    fetch_b3_trading_calendar_html,
    merge_with_b3_market_holidays,
)


SNAPSHOT_CURVE_DATE = date(2025, 2, 25)
CURVE_SOURCE_B3_LATEST = "B3 - último pregão disponível"
CURVE_SOURCE_B3_DATE = "B3 - data escolhida"
CURVE_SOURCE_SNAPSHOT = "Curva local salva"
CURVE_SOURCE_OPTIONS = [CURVE_SOURCE_B3_LATEST, CURVE_SOURCE_B3_DATE, CURVE_SOURCE_SNAPSHOT]
INTERPOLATION_LABEL_B3 = "Flat Forward 252 (metodologia B3)"
INTERPOLATION_LABEL_SPLINE = "Spline"
INTERPOLATION_OPTIONS = [INTERPOLATION_LABEL_B3, INTERPOLATION_LABEL_SPLINE]
CALENDAR_SOURCE_B3_OFFICIAL = "B3 oficial + projeção explícita"
CALENDAR_SOURCE_B3_PROJECTED = "Calendário B3 projetado"
CALENDAR_SOURCE_SNAPSHOT = "Feriados locais salvos"
CALENDAR_SOURCE_OPTIONS = [CALENDAR_SOURCE_B3_OFFICIAL, CALENDAR_SOURCE_B3_PROJECTED, CALENDAR_SOURCE_SNAPSHOT]
DATE_SCHEDULE_WORKBOOK = "Grade semestral padrão"
DATE_SCHEDULE_MONTHLY = "Mensal pelo prazo informado"
PORTFOLIO_MODE_REVOLVING = "Revolvente"
PORTFOLIO_MODE_STATIC = "Carteira estática"
CESSION_INPUT_DISCOUNT = "Taxa de Cessão"
CESSION_INPUT_MONTHLY = "Taxa Mensal (%)"
CREDIT_LABEL_NPL90 = "NPL 90 + cobertura de provisão"
CREDIT_LABEL_MIGRATION = "Migração por faixas de atraso"
CREDIT_MODEL_LABELS = {
    CREDIT_LABEL_NPL90: CREDIT_MODEL_NPL90,
    CREDIT_LABEL_MIGRATION: CREDIT_MODEL_MIGRATION,
}
DEFAULT_VOLUME_CARTEIRA = 750_000_000.0
DEFAULT_TX_CESSAO_AM = 0.04
DEFAULT_CUSTO_ADM_AA = 0.0035
DEFAULT_CUSTO_MIN_MENSAL = 20_000.0
DEFAULT_PERDA_ESPERADA_AM = 0.0
DEFAULT_PERDA_INESPERADA_AM = 0.0
DEFAULT_PERDA_CICLO = 0.0
DEFAULT_NPL90_LAG_MESES = 3
DEFAULT_COBERTURA_NPL90 = 1.0
DEFAULT_LGD = 1.0
DEFAULT_ROLAGEM_ADIMPLENTE_1_30 = 0.0
DEFAULT_ROLAGEM_1_30_31_60 = 0.0
DEFAULT_ROLAGEM_31_60_61_90 = 0.0
DEFAULT_ROLAGEM_61_90_90_PLUS = 0.0
DEFAULT_RECUPERACAO_90_PLUS = 0.0
DEFAULT_WRITEOFF_90_PLUS = 0.0
DEFAULT_AGIO_AQUISICAO = 0.0
DEFAULT_EXCESSO_SPREAD_SENIOR_AM = 0.0
DEFAULT_PROP_SENIOR = 0.75
DEFAULT_PROP_MEZZ = 0.15
DEFAULT_PROP_SUB = 0.10
DEFAULT_TAXA_SENIOR = 0.0135
DEFAULT_TAXA_MEZZ = 0.05
DEFAULT_PRAZO_ANOS = 3.0
DEFAULT_PRAZO_RECEBIVEIS_MESES = 6.0
DEFAULT_CARENCIA_PRINCIPAL_MESES = 30.0
DEFAULT_CURVE_START_YEAR = 2026
DEFAULT_SELIC_PERPETUAL_YEAR = 2028
DEFAULT_SELIC_AA_2026 = 0.13
DEFAULT_SELIC_AA_2027_ONWARD = 0.12
LABELS_COTAS = {
    "sen": "Cota sênior",
    "mezz": "Cota mezzanino",
    "sub": "Cota subordinada",
}
LABELS_COTAS_ABBR = {
    "sen": "SEN",
    "mezz": "MEZZ",
    "sub": "SUB",
}
HELP_CUSTO_ADM_GESTAO = (
    "Custo anual sobre o PL econômico do fundo no início do período; aplica-se o maior entre "
    "o valor mensal composto e o custo mínimo mensal."
)
HELP_CUSTO_MINIMO = (
    "Piso em R$/mês comparado ao custo percentual sobre o PL econômico; o motor usa o maior valor a cada período."
)
AMORTIZATION_LABELS = {
    "Cronograma padrão": AMORTIZATION_MODE_WORKBOOK,
    "Linear após carência": AMORTIZATION_MODE_LINEAR,
    "Bullet no vencimento": AMORTIZATION_MODE_BULLET,
    "Sem amortização programada": AMORTIZATION_MODE_NONE,
}
INTEREST_LABELS = {
    "Pago em todo período": INTEREST_PAYMENT_MODE_PERIODIC,
    "Pago após carência": INTEREST_PAYMENT_MODE_AFTER_GRACE,
    "Bullet no vencimento": INTEREST_PAYMENT_MODE_BULLET,
}


_MODEL_CSS = """
<style>
.fidc-model-header {
    border-bottom: 1px solid #dde3ea;
    margin: 0.15rem 0 1.05rem 0;
    padding-bottom: 1rem;
}

.fidc-model-kicker {
    color: #ff5a00;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    line-height: 1.2;
    margin-bottom: 0.35rem;
    text-transform: uppercase;
}

.fidc-model-title {
    color: #283241;
    font-size: 1.65rem;
    font-weight: 700;
    letter-spacing: 0;
    line-height: 1.16;
    margin: 0;
}

.fidc-model-copy {
    color: #6f7a87;
    font-size: 0.96rem;
    line-height: 1.58;
    margin-top: 0.55rem;
    max-width: 58rem;
}

.fidc-model-section-title {
    color: #283241;
    font-size: 1.02rem;
    font-weight: 700;
    margin: 1.15rem 0 0.55rem 0;
}

.fidc-model-kpi-grid {
    display: grid;
    gap: 0.65rem;
    grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
    margin: 0.4rem 0 0.55rem 0;
}

.fidc-model-kpi-card {
    background: #ffffff;
    border: 1px solid #dde3ea;
    border-radius: 8px;
    border-top: 3px solid #1f77b4;
    min-height: 6.1rem;
    padding: 0.75rem 0.8rem;
}

.fidc-model-kpi-card:nth-child(2n) {
    border-top-color: #ff5a00;
}

.fidc-model-kpi-label {
    align-items: center;
    color: #6f7a87;
    display: flex;
    font-size: 0.72rem;
    font-weight: 700;
    gap: 0.35rem;
    justify-content: space-between;
    letter-spacing: 0.05em;
    line-height: 1.25;
    margin-bottom: 0.35rem;
    text-transform: uppercase;
}

.fidc-model-tooltip {
    align-items: center;
    background: #eef3f8;
    border: 1px solid #cbd6e2;
    border-radius: 999px;
    color: #425166;
    cursor: help;
    display: inline-flex;
    flex: 0 0 auto;
    font-size: 0.68rem;
    font-weight: 700;
    height: 1rem;
    justify-content: center;
    letter-spacing: 0;
    line-height: 1;
    position: relative;
    text-transform: none;
    width: 1rem;
}

.fidc-model-tooltip::after {
    background: #202a36;
    border-radius: 6px;
    box-shadow: 0 8px 22px rgba(32, 42, 54, 0.18);
    color: #ffffff;
    content: attr(data-tooltip);
    font-size: 0.75rem;
    font-weight: 500;
    left: 50%;
    line-height: 1.35;
    max-width: 17rem;
    min-width: 13rem;
    opacity: 0;
    padding: 0.55rem 0.65rem;
    pointer-events: none;
    position: absolute;
    text-align: left;
    text-transform: none;
    top: calc(100% + 0.45rem);
    transform: translate(-50%, -0.15rem);
    transition: opacity 0.12s ease, transform 0.12s ease, visibility 0.12s ease;
    visibility: hidden;
    white-space: normal;
    z-index: 1000;
}

.fidc-model-tooltip:hover::after,
.fidc-model-tooltip:focus::after {
    opacity: 1;
    transform: translate(-50%, 0);
    visibility: visible;
}

.fidc-model-kpi-value {
    color: #202a36;
    font-size: 1.18rem;
    font-weight: 700;
    line-height: 1.18;
}

.fidc-model-kpi-context {
    color: #6f7a87;
    font-size: 0.78rem;
    line-height: 1.35;
    margin-top: 0.35rem;
}

[data-testid="stFormSubmitButton"] button,
[data-testid="stButton"] button[kind="primary"],
[data-testid="stDownloadButton"] button[kind="primary"] {
    background: #1f77b4 !important;
    border-color: #1f77b4 !important;
    color: #ffffff !important;
}

[data-testid="stFormSubmitButton"] button p,
[data-testid="stButton"] button[kind="primary"] p,
[data-testid="stDownloadButton"] button[kind="primary"] p {
    color: #ffffff !important;
}

@media (max-width: 760px) {
    .fidc-model-title {
        font-size: 1.4rem;
    }
}
</style>
"""


@st.cache_data
def _load_inputs(path: str):
    return load_model_inputs(path)


@dataclass(frozen=True)
class _SelectedCurve:
    source_label: str
    curve_code: str
    base_date: date
    curva_du: tuple[float, ...]
    curva_taxa_aa: tuple[float, ...]
    source_url: str
    retrieved_label: str
    content_sha256: str
    point_count: int
    first_du: int | None
    last_du: int | None
    raw_line_count: int | None = None

    @property
    def cache_key(self) -> tuple[str, str, str, str]:
        return (
            self.source_label,
            self.curve_code,
            self.base_date.isoformat(),
            self.content_sha256[:16],
        )


@dataclass(frozen=True)
class _SelectedCalendar:
    source_label: str
    feriados: tuple[date, ...]
    holiday_count: int
    first_holiday: date | None
    last_holiday: date | None
    official_years: tuple[int, ...] = ()
    projected_years: tuple[int, ...] = ()
    source_url: str = ""
    retrieved_label: str = ""
    content_sha256: str = ""

    @property
    def cache_key(self) -> tuple[str, int, str, str, str, str]:
        return (
            self.source_label,
            self.holiday_count,
            self.first_holiday.isoformat() if self.first_holiday else "",
            self.last_holiday.isoformat() if self.last_holiday else "",
            ",".join(str(year) for year in self.official_years),
            ",".join(str(year) for year in self.projected_years),
        )


@dataclass(frozen=True)
class _RevolvencyMetrics:
    portfolio_mode: str
    prazo_total_anos: float
    prazo_medio_recebiveis_meses: float
    giro_estimado: float
    carteira_originada_programatica: float
    reinvestimento_principal_total: float
    reinvestimento_excesso_total: float
    nova_originacao_total: float
    carteira_total_originada: float
    ead_maximo: float
    ead_medio_ponderado: float
    sub_final_sem_inadimplencia: float
    colchao_sem_perdas_sobre_originacao: float | None
    perda_ciclo_calibrada: float | None
    perda_ciclo_calibrada_anual_equivalente: float | None
    perda_ciclo_calibrada_pos_lgd: float | None
    perda_ciclo_calibrada_excede_limite: bool


@st.cache_data(show_spinner=False, ttl=24 * 60 * 60)
def _load_b3_calendar_snapshot(start_year: int, end_year: int) -> B3CalendarSnapshot:
    html_text, content_hash = fetch_b3_trading_calendar_html()
    datas = [date(start_year, 1, 1), date(end_year, 12, 31)]
    return build_b3_calendar_snapshot(datas, html_text, content_hash=content_hash)


@st.cache_data(show_spinner=False, ttl=6 * 60 * 60)
def _load_b3_curve_for_date(date_iso: str, curve_code: str) -> B3CurveSnapshot:
    return fetch_taxaswap_curve(date.fromisoformat(date_iso), curve_code=curve_code)


@st.cache_data(show_spinner=False, ttl=6 * 60 * 60)
def _load_latest_b3_curve(start_date_iso: str, curve_code: str) -> B3CurveSnapshot:
    return fetch_latest_taxaswap_curve(start_date=date.fromisoformat(start_date_iso), curve_code=curve_code)


def _selected_curve_from_snapshot(inputs) -> _SelectedCurve:
    return _SelectedCurve(
        source_label=CURVE_SOURCE_SNAPSHOT,
        curve_code="PRE",
        base_date=SNAPSHOT_CURVE_DATE,
        curva_du=tuple(float(value) for value in inputs.curva_du),
        curva_taxa_aa=tuple(float(value) for value in inputs.curva_cdi),
        source_url="model_data.json",
        retrieved_label="curva local sem consulta externa",
        content_sha256="local-snapshot",
        point_count=len(inputs.curva_du),
        first_du=int(inputs.curva_du[0]) if inputs.curva_du else None,
        last_du=int(inputs.curva_du[-1]) if inputs.curva_du else None,
        raw_line_count=None,
    )


def _selected_curve_from_b3(snapshot: B3CurveSnapshot, source_label: str) -> _SelectedCurve:
    return _SelectedCurve(
        source_label=source_label,
        curve_code=snapshot.curve_code,
        base_date=snapshot.generated_at,
        curva_du=tuple(snapshot.curva_du),
        curva_taxa_aa=tuple(snapshot.curva_taxa_aa),
        source_url=snapshot.source_url,
        retrieved_label=snapshot.retrieved_at.strftime("%d/%m/%Y %H:%M:%S UTC"),
        content_sha256=snapshot.content_sha256,
        point_count=len(snapshot.points),
        first_du=snapshot.first_du,
        last_du=snapshot.last_du,
        raw_line_count=snapshot.raw_line_count,
    )


def _default_selic_rate_for_year(year: int) -> float:
    return DEFAULT_SELIC_AA_2026 if int(year) == DEFAULT_CURVE_START_YEAR else DEFAULT_SELIC_AA_2027_ONWARD


def _effective_selic_projection_for_dates(
    user_projection: tuple[tuple[int, float], ...],
    simulation_dates: list[datetime],
) -> tuple[tuple[int, float], ...]:
    projection = dict(user_projection)
    if not projection:
        raise ValueError("A curva de SELIC média para caixa precisa ter pelo menos um ano informado.")
    required_years = sorted({dt.year for dt in simulation_dates[1:]})
    effective = dict(projection)
    for year in required_years:
        if year < min(projection):
            effective[year] = projection[min(projection)]
        elif year not in projection:
            previous_years = [projection_year for projection_year in projection if projection_year <= year]
            if not previous_years:
                raise ValueError(f"Curva de SELIC média para caixa sem taxa para {year}.")
            effective[year] = projection[max(previous_years)]
    return tuple(sorted(effective.items()))


def _selic_year_label(year: int, projection_years: list[int] | tuple[int, ...]) -> str:
    if int(year) == max(projection_years):
        return f"{year} em diante"
    return str(year)


def _build_workbook_dates_from_start(template_dates: list[datetime], start: datetime) -> list[datetime]:
    if not template_dates:
        return [start]
    template_start = template_dates[0]
    return [
        _add_months(start, (dt.year - template_start.year) * 12 + (dt.month - template_start.month))
        for dt in template_dates
    ]


def _selected_calendar(
    inputs,
    source_label: str,
    b3_snapshot: B3CalendarSnapshot | None = None,
    datas: list[datetime] | None = None,
) -> _SelectedCalendar:
    flow_dates = datas or inputs.datas
    if source_label == CALENDAR_SOURCE_B3_OFFICIAL:
        if b3_snapshot is None:
            raise B3CalendarError("Snapshot de calendário B3 não foi carregado.")
        holidays = tuple(b3_snapshot.holidays)
        return _SelectedCalendar(
            source_label=source_label,
            feriados=holidays,
            holiday_count=len(holidays),
            first_holiday=holidays[0] if holidays else None,
            last_holiday=holidays[-1] if holidays else None,
            official_years=b3_snapshot.official_years,
            projected_years=b3_snapshot.projected_years,
            source_url=b3_snapshot.source_url,
            retrieved_label=b3_snapshot.retrieved_at.strftime("%d/%m/%Y %H:%M:%S UTC"),
            content_sha256=b3_snapshot.content_sha256,
        )
    if source_label == CALENDAR_SOURCE_B3_PROJECTED:
        holidays = tuple(merge_with_b3_market_holidays(inputs.feriados, flow_dates))
        projected_years = tuple(range(flow_dates[0].year, flow_dates[-1].year + 1)) if flow_dates else ()
    else:
        holidays = tuple(holiday.date() for holiday in inputs.feriados)
        projected_years = ()
    return _SelectedCalendar(
        source_label=source_label,
        feriados=holidays,
        holiday_count=len(holidays),
        first_holiday=holidays[0] if holidays else None,
        last_holiday=holidays[-1] if holidays else None,
        projected_years=projected_years,
    )


def _interpolation_method_from_label(label: str) -> str:
    return INTERPOLATION_METHOD_FLAT_FORWARD_252 if label == INTERPOLATION_LABEL_B3 else INTERPOLATION_METHOD_SPLINE


def _format_number_br(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/D"
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _format_percent(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/D"
    return f"{_format_number_br(value * 100.0, decimals)}%"


def _format_brl(value: float | None) -> str:
    if value is None:
        return "N/D"
    return f"R$ {_format_number_br(value, 2)}"


def _format_input_value(value: float, decimals: int = 2) -> str:
    return _format_number_br(value, decimals)


def _format_brl_input_value(value: float, decimals: int = 2) -> str:
    return f"R$ {_format_input_value(value, decimals)}"


def _format_percent_input_value(value: float, decimals: int = 2) -> str:
    return f"{_format_input_value(value, decimals)}%"


def _parse_br_number(value: str, *, field_name: str) -> float:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Informe {field_name}.")
    normalized = text.replace("R$", "").replace("%", "").replace(" ", "")
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError as exc:
        raise ValueError(f"Valor inválido em {field_name}: {value}") from exc


def _parse_percent_for_visibility(value: str, *, default: float) -> float:
    try:
        return _parse_br_number(value, field_name="percentual") / 100.0
    except ValueError:
        return default


def _format_raw_input_text(value: str, *, decimals: int, kind: str) -> str:
    parsed = _parse_br_number(value, field_name="valor")
    if kind == "brl":
        return _format_brl_input_value(parsed, decimals)
    if kind == "percent":
        return _format_percent_input_value(parsed, decimals)
    if kind == "number":
        return _format_input_value(parsed, decimals)
    raise ValueError(f"Tipo de input inválido: {kind}")


_INPUT_NORMALIZATION_SPECS = {
    "modelo_volume": (2, "brl"),
    "modelo_tx_cessao_desagio": (2, "percent"),
    "modelo_tx_cessao_mensal": (2, "percent"),
    "modelo_custo_adm_pct": (2, "percent"),
    "modelo_custo_min": (2, "brl"),
    "modelo_perda_esperada_pct": (2, "percent"),
    "modelo_perda_inesperada_pct": (2, "percent"),
    "modelo_perda_ciclo_pct": (2, "percent"),
    "modelo_npl90_lag_meses": (0, "number"),
    "modelo_cobertura_npl90_pct": (1, "percent"),
    "modelo_lgd_pct": (1, "percent"),
    "modelo_roll_adimplente_1_30_pct": (2, "percent"),
    "modelo_roll_1_30_31_60_pct": (2, "percent"),
    "modelo_roll_31_60_61_90_pct": (2, "percent"),
    "modelo_roll_61_90_90_plus_pct": (2, "percent"),
    "modelo_recuperacao_90_plus_pct": (2, "percent"),
    "modelo_writeoff_90_plus_pct": (2, "percent"),
    "modelo_agio_aquisicao_pct": (2, "percent"),
    "modelo_excesso_spread_senior": (2, "percent"),
    "modelo_prop_senior": (1, "percent"),
    "modelo_prop_mezz": (1, "percent"),
    "modelo_prop_sub": (1, "percent"),
    "modelo_taxa_senior": (2, "percent"),
    "modelo_taxa_mezz": (2, "percent"),
    "modelo_taxa_sub": (2, "percent"),
    "modelo_prazo_fidc_anos": (1, "number"),
    "modelo_prazo_recebiveis_meses": (1, "number"),
    "modelo_prazo_senior_anos": (1, "number"),
    "modelo_prazo_mezz_anos": (1, "number"),
    "modelo_prazo_sub_anos": (1, "number"),
    "modelo_inicio_amort_senior": (0, "number"),
    "modelo_inicio_amort_mezz": (0, "number"),
}


def _normalize_model_input_values() -> None:
    for key, (decimals, kind) in _INPUT_NORMALIZATION_SPECS.items():
        if key not in st.session_state:
            continue
        try:
            st.session_state[key] = _format_raw_input_text(st.session_state[key], decimals=decimals, kind=kind)
        except ValueError:
            continue
    for key in list(st.session_state):
        if not str(key).startswith("modelo_selic_aa_"):
            continue
        try:
            st.session_state[key] = _format_raw_input_text(st.session_state[key], decimals=2, kind="percent")
        except ValueError:
            continue


def _add_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    month_lengths = (31, 29 if _is_leap_year(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    day = min(dt.day, month_lengths[month - 1])
    return dt.replace(year=year, month=month, day=day)


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _build_monthly_dates(start: datetime, prazo_total_anos: float) -> list[datetime]:
    total_months = max(1, round(prazo_total_anos * 12.0))
    return [_add_months(start, month) for month in range(total_months + 1)]


def _build_simulation_dates(
    inputs,
    schedule_label: str,
    prazo_total_anos: float,
    data_inicial: datetime | None = None,
) -> list[datetime]:
    start = data_inicial or inputs.datas[0]
    if schedule_label == DATE_SCHEDULE_MONTHLY:
        return _build_monthly_dates(start, prazo_total_anos)
    return _build_workbook_dates_from_start(list(inputs.datas), start)


def _effective_cession_discount_after_premium(nominal_discount: float, acquisition_premium: float) -> float:
    return float(nominal_discount) - max(float(acquisition_premium), 0.0)


def _projection_years_for_term(start: datetime, prazo_total_anos: float) -> list[int]:
    return list(range(DEFAULT_CURVE_START_YEAR, DEFAULT_SELIC_PERPETUAL_YEAR + 1))


def _safe_term_years_from_text(value: str, fallback: float = DEFAULT_PRAZO_ANOS) -> float:
    try:
        parsed = _parse_br_number(value, field_name="Prazo total do FIDC (anos)")
    except ValueError:
        return fallback
    return parsed if parsed > 0 else fallback


def _label_for_value(mapping: dict[str, str], value: str) -> str:
    for label, mapped_value in mapping.items():
        if mapped_value == value:
            return label
    return next(iter(mapping))


def _ensure_session_option(key: str, options: list[str], default_index: int = 0) -> str:
    value = st.session_state.get(key)
    if value not in options:
        value = options[default_index]
        st.session_state[key] = value
    return value


def _ensure_session_date(key: str, default_value: date) -> date:
    value = st.session_state.get(key)
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        value = default_value
        st.session_state[key] = value
    return value


def _build_revolvency_metrics(
    *,
    premissas: Premissas,
    zero_default_results,
    portfolio_mode: str,
    calibrated_loss_cycle: float | None = None,
    calibrated_loss_exceeds_limit: bool = False,
) -> _RevolvencyMetrics:
    prazo_total_anos = float(premissas.prazo_fidc_anos or 0.0)
    prazo_medio_meses = max(float(premissas.prazo_medio_recebiveis_meses), 0.01)
    giro_estimado = prazo_total_anos * 12.0 / prazo_medio_meses
    if portfolio_mode == PORTFOLIO_MODE_STATIC:
        carteira_originada_programatica = premissas.volume
    else:
        eligible_months = max(prazo_total_anos * 12.0 - prazo_medio_meses, 0.0)
        carteira_originada_programatica = premissas.volume + premissas.volume * (eligible_months / prazo_medio_meses)
    reinvestimento_principal_total = sum(
        max(float(getattr(period, "reinvestimento_principal", 0.0)), 0.0) for period in zero_default_results[1:]
    )
    reinvestimento_excesso_total = sum(
        max(float(getattr(period, "reinvestimento_excesso", 0.0)), 0.0) for period in zero_default_results[1:]
    )
    nova_originacao_total = sum(
        max(float(getattr(period, "nova_originacao", 0.0)), 0.0) for period in zero_default_results[1:]
    )
    has_motor_origination = any(hasattr(period, "nova_originacao") for period in zero_default_results[1:])
    if zero_default_results and has_motor_origination:
        carteira_total_originada = max(float(premissas.volume), 0.0) + nova_originacao_total
    else:
        carteira_total_originada = carteira_originada_programatica
    sub_final = max(float(zero_default_results[-1].pl_sub_jr), 0.0) if zero_default_results else 0.0
    colchao_sem_perdas = sub_final / carteira_total_originada if carteira_total_originada > 0 else None
    ead_values = [float(getattr(period, "carteira", premissas.volume)) for period in zero_default_results]
    ead_maximo = max(ead_values, default=float(premissas.volume))
    weighted_days = sum(max(float(getattr(period, "delta_dc", 0.0)), 0.0) for period in zero_default_results[1:])
    if weighted_days > 0.0:
        ead_medio = (
            sum(
                float(getattr(period, "carteira", premissas.volume)) * max(float(getattr(period, "delta_dc", 0.0)), 0.0)
                for period in zero_default_results[1:]
            )
            / weighted_days
        )
    else:
        ead_medio = float(premissas.volume)
    calibrated_loss_annual = (
        (1.0 + calibrated_loss_cycle) ** (12.0 / prazo_medio_meses) - 1.0
        if calibrated_loss_cycle is not None and prazo_medio_meses > 0.0
        else None
    )
    calibrated_loss_post_lgd = (
        calibrated_loss_cycle * max(float(getattr(premissas, "lgd", 1.0)), 0.0)
        if calibrated_loss_cycle is not None
        else None
    )
    return _RevolvencyMetrics(
        portfolio_mode=portfolio_mode,
        prazo_total_anos=prazo_total_anos,
        prazo_medio_recebiveis_meses=prazo_medio_meses,
        giro_estimado=giro_estimado,
        carteira_originada_programatica=carteira_originada_programatica,
        reinvestimento_principal_total=reinvestimento_principal_total,
        reinvestimento_excesso_total=reinvestimento_excesso_total,
        nova_originacao_total=nova_originacao_total,
        carteira_total_originada=carteira_total_originada,
        ead_maximo=ead_maximo,
        ead_medio_ponderado=ead_medio,
        sub_final_sem_inadimplencia=sub_final,
        colchao_sem_perdas_sobre_originacao=colchao_sem_perdas,
        perda_ciclo_calibrada=calibrated_loss_cycle,
        perda_ciclo_calibrada_anual_equivalente=calibrated_loss_annual,
        perda_ciclo_calibrada_pos_lgd=calibrated_loss_post_lgd,
        perda_ciclo_calibrada_excede_limite=calibrated_loss_exceeds_limit,
    )


def _premissas_sem_perdas(premissas: Premissas) -> Premissas:
    return replace(
        premissas,
        inadimplencia=0.0,
        perda_esperada_am=0.0,
        perda_inesperada_am=0.0,
        perda_ciclo=0.0,
        rolagem_adimplente_1_30=0.0,
        rolagem_1_30_31_60=0.0,
        rolagem_31_60_61_90=0.0,
        rolagem_61_90_90_plus=0.0,
        recuperacao_90_plus=0.0,
        writeoff_90_plus=0.0,
    )


def _premissas_perda_ciclo_calibrada(premissas: Premissas, perda_ciclo: float) -> Premissas:
    return replace(
        _premissas_sem_perdas(premissas),
        modelo_credito=CREDIT_MODEL_NPL90,
        perda_ciclo=max(float(perda_ciclo), 0.0),
        recuperacao_90_plus=0.0,
        writeoff_90_plus=0.0,
    )


def _final_sub_for_loss_cycle(
    *,
    datas: list[datetime],
    feriados,
    curva_du,
    curva_taxa_aa,
    premissas: Premissas,
    interpolation_method: str,
    perda_ciclo: float,
) -> float:
    periods = build_flow(
        datas,
        feriados,
        curva_du,
        curva_taxa_aa,
        _premissas_perda_ciclo_calibrada(premissas, perda_ciclo),
        interpolation_method=interpolation_method,
    )
    return float(periods[-1].pl_sub_jr) if periods else 0.0


def _solve_calibrated_loss_cycle(
    *,
    datas: list[datetime],
    feriados,
    curva_du,
    curva_taxa_aa,
    premissas: Premissas,
    interpolation_method: str,
    max_loss_cycle: float = 1.0,
    tolerance: float = 1e-5,
    iterations: int = 36,
) -> tuple[float | None, bool]:
    if not datas:
        return None, False
    base_sub = _final_sub_for_loss_cycle(
        datas=datas,
        feriados=feriados,
        curva_du=curva_du,
        curva_taxa_aa=curva_taxa_aa,
        premissas=premissas,
        interpolation_method=interpolation_method,
        perda_ciclo=0.0,
    )
    if base_sub <= 0.0:
        return 0.0, False

    high_sub = _final_sub_for_loss_cycle(
        datas=datas,
        feriados=feriados,
        curva_du=curva_du,
        curva_taxa_aa=curva_taxa_aa,
        premissas=premissas,
        interpolation_method=interpolation_method,
        perda_ciclo=max_loss_cycle,
    )
    if high_sub > 0.0:
        return None, True

    low = 0.0
    high = max_loss_cycle
    for _ in range(iterations):
        mid = (low + high) / 2.0
        mid_sub = _final_sub_for_loss_cycle(
            datas=datas,
            feriados=feriados,
            curva_du=curva_du,
            curva_taxa_aa=curva_taxa_aa,
            premissas=premissas,
            interpolation_method=interpolation_method,
            perda_ciclo=mid,
        )
        if abs(mid_sub) <= max(abs(base_sub) * tolerance, 1.0):
            return mid, False
        if mid_sub > 0.0:
            low = mid
        else:
            high = mid
    return high, False


def _scheduled_origination_components(
    month_index: float,
    previous_month_index: float,
    premissas: Premissas,
    portfolio_mode: str,
) -> tuple[float, float, float, float]:
    initial_portfolio = max(float(premissas.volume), 0.0)
    if portfolio_mode == PORTFOLIO_MODE_STATIC:
        return initial_portfolio, 0.0, 0.0, initial_portfolio

    prazo_medio_meses = max(float(premissas.prazo_medio_recebiveis_meses), 0.01)
    prazo_total_anos = float(premissas.prazo_fidc_anos or 0.0)
    cutoff_month = max(prazo_total_anos * 12.0 - prazo_medio_meses, 0.0)
    current_capped_month = min(max(float(month_index), 0.0), cutoff_month)
    previous_capped_month = min(max(float(previous_month_index), 0.0), cutoff_month)
    new_origination_period = premissas.volume * max(current_capped_month - previous_capped_month, 0.0) / prazo_medio_meses
    new_origination_cumulative = premissas.volume * current_capped_month / prazo_medio_meses
    return initial_portfolio, new_origination_period, new_origination_cumulative, initial_portfolio + new_origination_cumulative


def _build_time_protection_frame(
    frame: pd.DataFrame,
    *,
    premissas: Premissas,
    portfolio_mode: str,
    scenario_label: str,
) -> pd.DataFrame:
    columns = ["indice", "data", "pl_sub_jr"]
    if "fluxo_remanescente_mezz" in frame.columns:
        columns.append("fluxo_remanescente_mezz")
    if "nova_originacao" in frame.columns:
        columns.append("nova_originacao")
    protection = frame[columns].copy()
    protection["carteira_inicial_considerada"] = max(float(premissas.volume), 0.0)
    previous_indices = protection["indice"].shift(1).fillna(0.0)
    components = [
        _scheduled_origination_components(month_index, previous_month_index, premissas, portfolio_mode)
        for month_index, previous_month_index in zip(protection["indice"], previous_indices)
    ]
    protection["nova_originacao_programatica"] = [values[1] for values in components]
    protection["nova_originacao_programatica_acumulada"] = [values[2] for values in components]
    if "nova_originacao" in protection.columns:
        protection["nova_originacao_motor"] = protection["nova_originacao"].clip(lower=0.0)
        protection["nova_originacao_estimada"] = protection["nova_originacao_motor"]
        protection["nova_originacao_acumulada"] = protection["nova_originacao_motor"].cumsum()
        protection["carteira_originada_acumulada"] = protection["carteira_inicial_considerada"] + protection[
            "nova_originacao_acumulada"
        ]
    else:
        protection["nova_originacao_motor"] = None
        protection["nova_originacao_estimada"] = protection["nova_originacao_programatica"]
        protection["nova_originacao_acumulada"] = protection["nova_originacao_programatica_acumulada"]
        protection["carteira_originada_acumulada"] = [values[3] for values in components]
    protection["prazo_medio_recebiveis_meses"] = float(premissas.prazo_medio_recebiveis_meses)
    if "fluxo_remanescente_mezz" in protection.columns:
        protection["residual_economico_fluxo"] = protection["fluxo_remanescente_mezz"]
    else:
        protection["residual_economico_fluxo"] = protection["pl_sub_jr"].diff().fillna(protection["pl_sub_jr"])
    protection["sub_disponivel"] = protection["pl_sub_jr"].clip(lower=0.0)
    protection["perda_maxima_suportada"] = protection.apply(
        lambda row: (
            row["sub_disponivel"] / row["carteira_originada_acumulada"]
            if row["indice"] > 0 and row["carteira_originada_acumulada"] > 0.0
            else None
        ),
        axis=1,
    )
    protection["serie"] = scenario_label
    protection["valor_pct"] = protection["perda_maxima_suportada"] * 100.0
    protection["valor_formatado"] = protection["perda_maxima_suportada"].map(_format_percent)
    protection["sub_formatada"] = protection["sub_disponivel"].map(_format_brl)
    protection["originada_formatada"] = protection["carteira_originada_acumulada"].map(_format_brl)
    protection["carteira_inicial_formatada"] = protection["carteira_inicial_considerada"].map(_format_brl)
    protection["nova_originacao_formatada"] = protection["nova_originacao_estimada"].map(_format_brl)
    protection["nova_originacao_acumulada_formatada"] = protection["nova_originacao_acumulada"].map(_format_brl)
    protection["nova_originacao_motor_formatada"] = protection["nova_originacao_motor"].map(_format_brl)
    protection["residual_fluxo_formatado"] = protection["residual_economico_fluxo"].map(_format_brl)
    protection["periodo"] = protection["data"].dt.strftime("%d/%m/%Y")
    protection["mes_fidc"] = protection["indice"].map(lambda value: f"Mês {int(value)}")
    return protection.dropna(subset=["perda_maxima_suportada"])


def _text_number_input(
    label: str,
    *,
    default: float,
    key: str,
    decimals: int = 2,
    help_text: str | None = None,
) -> str:
    return st.text_input(label, value=_format_input_value(default, decimals), key=key, help=help_text)


def _text_brl_input(
    label: str,
    *,
    default: float,
    key: str,
    decimals: int = 2,
    help_text: str | None = None,
) -> str:
    return st.text_input(label, value=_format_brl_input_value(default, decimals), key=key, help=help_text)


def _text_percent_input(
    label: str,
    *,
    default: float,
    key: str,
    decimals: int = 2,
    help_text: str | None = None,
) -> str:
    return st.text_input(label, value=_format_percent_input_value(default, decimals), key=key, help=help_text)


def _build_dataframe(results) -> pd.DataFrame:
    frame = pd.DataFrame([result.__dict__ for result in results])
    frame["data"] = pd.to_datetime(frame["data"])
    return frame


def _build_export_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    export = frame.copy()
    export["data"] = export["data"].dt.strftime("%d/%m/%Y")
    if "perda_carteira_despesa" in export.columns and "inadimplencia_despesa" in export.columns:
        export = export.drop(columns=["inadimplencia_despesa"])
    return export.rename(
        columns={
            "indice": "Índice",
            "data": "Data",
            "dc": "Dias corridos",
            "du": "Dias úteis",
            "delta_dc": "Delta dias corridos",
            "delta_du": "Delta dias úteis",
            "pre_di": "Pre DI",
            "taxa_senior": "Taxa sênior",
            "fra_senior": "FRA sênior",
            "taxa_mezz": "Taxa MEZZ",
            "fra_mezz": "FRA MEZZ",
            "carteira": "Carteira de recebíveis (início do período)",
            "ead_carteira": "EAD / saldo em risco (preço pago)",
            "fluxo_carteira": "Fluxo econômico da carteira",
            "taxa_selic_aa": "Taxa SELIC projetada (% a.a.)",
            "taxa_selic_periodo": "Taxa SELIC do período",
            "saldo_caixa_selic_inicio": "Saldo de caixa aplicado SELIC (início)",
            "principal_para_caixa_selic": "Principal direcionado para caixa SELIC",
            "rendimento_caixa_selic": "Rendimento do caixa SELIC",
            "fluxo_ativos_total": "Fluxo econômico total dos ativos",
            "pl_fidc": "PL econômico do veículo",
            "custos_adm": "Custos administrativos",
            "perda_esperada_despesa": "Provisão prospectiva do ciclo",
            "perda_inesperada_despesa": "Reforço de cobertura ou write-off descoberto",
            "perda_carteira_despesa": "Despesa de provisão/perda",
            "carteira_vencendo": "Carteira vencendo no período",
            "ead_vencendo": "EAD vencendo no período",
            "principal_inadimplente": "Principal inadimplente não recebido",
            "entrada_npl90": "Entrada em NPL 90+",
            "npl90_estoque_inicio": "Estoque NPL 90+ (início)",
            "npl90_estoque_fim": "Estoque NPL 90+ (fim)",
            "provisao_saldo_inicio": "Saldo de provisão (início)",
            "provisao_requerida": "Provisão requerida",
            "despesa_provisao": "Despesa de provisão",
            "provisao_saldo_fim": "Saldo de provisão (fim)",
            "cobertura_npl90": "Cobertura NPL 90+",
            "baixa_credito": "Baixa de crédito/write-off",
            "writeoff_descoberto": "Write-off descoberto pela provisão",
            "recuperacao_credito": "Recuperação de crédito",
            "bucket_adimplente": "Bucket adimplente",
            "bucket_1_30": "Bucket 1-30",
            "bucket_31_60": "Bucket 31-60",
            "bucket_61_90": "Bucket 61-90",
            "bucket_90_plus": "Bucket NPL 90+",
            "resultado_carteira_liquido": "Resultado líquido da carteira",
            "prazo_restante_reinvestimento_meses": "Prazo restante para reinvestimento (meses)",
            "reinvestimento_elegivel": "Reinvestimento elegível",
            "principal_recebido_carteira": "Principal recebido da carteira",
            "reinvestimento_principal": "Reinvestimento de principal",
            "reinvestimento_excesso": "Reinvestimento de excesso de caixa",
            "nova_originacao": "Nova originação",
            "carteira_fim": "Carteira ao fim do período",
            "caixa_nao_reinvestido": "Caixa não reinvestido",
            "saldo_caixa_selic_fim": "Saldo de caixa aplicado SELIC (fim)",
            "agio_aquisicao_despesa": "Ágio sobre face informado",
            "preco_pago_fator": "Preço pago / face",
            "tx_cessao_am_input": "Taxa mensal informada",
            "tx_cessao_am_piso": "Piso mensal CDI + spread SEN + excesso",
            "tx_cessao_am_aplicada": "Taxa mensal aplicada",
            "principal_senior": "Principal sênior",
            "juros_senior": "Juros sênior",
            "pmt_senior": "PMT sênior",
            "vp_pmt_senior": "VP PMT sênior",
            "pl_senior": "PL sênior",
            "fluxo_remanescente": "Fluxo remanescente após sênior",
            "principal_mezz": "Principal MEZZ",
            "juros_mezz": "Juros MEZZ",
            "pmt_mezz": "PMT MEZZ",
            "pl_mezz": "PL MEZZ",
            "fluxo_remanescente_mezz": "Fluxo remanescente após MEZZ",
            "principal_sub_jr": "Principal subordinada",
            "juros_sub_jr": "Juros subordinada",
            "pmt_sub_jr": "PMT subordinada",
            "pl_sub_jr": "Saldo residual júnior econômico",
            "subordinacao_pct": "Subordinação econômica",
            "pl_sub_jr_modelo": "Saldo júnior histórico",
            "subordinacao_pct_modelo": "Subordinação histórica",
        }
    )


def _build_display_dataframe(export_frame: pd.DataFrame) -> pd.DataFrame:
    display = export_frame.copy()
    money_tokens = (
        "Carteira",
        "Fluxo",
        "PL",
        "Custos",
        "Perda",
        "Provisão",
        "NPL",
        "Bucket",
        "Baixa",
        "Recuperação",
        "Principal",
        "Juros",
        "PMT",
        "VP",
        "Saldo",
        "Resultado",
        "Reinvestimento",
        "Originação",
        "Caixa",
        "Rendimento",
        "EAD",
        "Ágio",
    )
    percent_tokens = ("Pre DI", "Taxa", "FRA", "Subordinação", "Cobertura", "Preço pago / face")
    for column in display.columns:
        if column in {"Índice", "Dias corridos", "Dias úteis", "Delta dias corridos", "Delta dias úteis"}:
            display[column] = display[column].map(lambda value: _format_number_br(float(value), 0) if pd.notna(value) else "N/D")
        elif any(token in column for token in percent_tokens):
            display[column] = display[column].map(lambda value: _format_percent(float(value)) if pd.notna(value) else "N/D")
        elif any(token in column for token in money_tokens):
            display[column] = display[column].map(lambda value: _format_brl(float(value)) if pd.notna(value) else "N/D")
    return display


def _build_kpi_export_dataframe(kpis) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Indicador": "Retorno anualizado da classe sênior (econômico)",
                "Valor": kpis.xirr_senior,
                "Definicao": "Taxa interna anual de retorno dos pagamentos projetados da classe sênior.",
            },
            {
                "Indicador": "Retorno anualizado da classe MEZZ (econômico)",
                "Valor": kpis.xirr_mezz,
                "Definicao": "Taxa interna anual de retorno dos pagamentos projetados da classe MEZZ.",
            },
            {
                "Indicador": "Retorno anualizado da júnior residual (econômico)",
                "Valor": kpis.xirr_sub_jr,
                "Definicao": "Não aplicável quando a série de pagamentos da subordinada não tem sinais válidos para calcular retorno interno.",
            },
            {
                "Indicador": "Duration econômica da sênior",
                "Valor": kpis.duration_senior_anos,
                "Definicao": "Prazo médio ponderado, em anos, dos pagamentos descontados da classe sênior.",
            },
            {
                "Indicador": "Pre DI equivalente na duration",
                "Valor": kpis.pre_di_duration,
                "Definicao": "Taxa Pre DI da curva interpolada no ponto correspondente ao duration da sênior.",
            },
            {
                "Indicador": "Excesso de retorno da júnior sobre o Pre DI",
                "Valor": kpis.taxa_retorno_sub_jr_cdi,
                "Definicao": "Excesso de retorno da subordinada sobre a taxa Pre DI no duration, quando a série permite o cálculo.",
            },
        ]
    )


def _build_curve_source_dataframe(
    selected_curve: _SelectedCurve,
    selected_calendar: _SelectedCalendar,
    interpolation_label: str,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Campo": "Fonte", "Valor": selected_curve.source_label},
            {"Campo": "Curva", "Valor": selected_curve.curve_code},
            {"Campo": "Interpolação", "Valor": interpolation_label},
            {"Campo": "Data-base", "Valor": selected_curve.base_date.strftime("%d/%m/%Y")},
            {"Campo": "Pontos", "Valor": _format_number_br(selected_curve.point_count, 0)},
            {"Campo": "DU inicial", "Valor": selected_curve.first_du if selected_curve.first_du is not None else "N/D"},
            {"Campo": "DU final", "Valor": selected_curve.last_du if selected_curve.last_du is not None else "N/D"},
            {"Campo": "Calendário de dias úteis", "Valor": selected_calendar.source_label},
            {"Campo": "Feriados considerados", "Valor": _format_number_br(selected_calendar.holiday_count, 0)},
            {
                "Campo": "Anos oficiais B3",
                "Valor": ", ".join(str(year) for year in selected_calendar.official_years) or "N/D",
            },
            {
                "Campo": "Anos projetados",
                "Valor": ", ".join(str(year) for year in selected_calendar.projected_years) or "N/D",
            },
            {
                "Campo": "Primeiro feriado",
                "Valor": selected_calendar.first_holiday.strftime("%d/%m/%Y") if selected_calendar.first_holiday else "N/D",
            },
            {
                "Campo": "Último feriado",
                "Valor": selected_calendar.last_holiday.strftime("%d/%m/%Y") if selected_calendar.last_holiday else "N/D",
            },
            {"Campo": "URL calendário", "Valor": selected_calendar.source_url or "N/D"},
            {"Campo": "Calendário baixado em", "Valor": selected_calendar.retrieved_label or "N/D"},
            {"Campo": "SHA-256 calendário", "Valor": selected_calendar.content_sha256 or "N/D"},
            {"Campo": "URL/Origem", "Valor": selected_curve.source_url},
            {"Campo": "Baixado em", "Valor": selected_curve.retrieved_label},
            {"Campo": "SHA-256", "Valor": selected_curve.content_sha256},
        ]
    )


def _build_revolvency_export_dataframe(metrics: _RevolvencyMetrics) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Indicador": "Prazo total do FIDC (anos)", "Valor": metrics.prazo_total_anos},
            {"Indicador": "Prazo médio dos recebíveis (meses)", "Valor": metrics.prazo_medio_recebiveis_meses},
            {"Indicador": "Carteira originada programática", "Valor": metrics.carteira_originada_programatica},
            {"Indicador": "Reinvestimento de principal", "Valor": metrics.reinvestimento_principal_total},
            {"Indicador": "Reinvestimento de excesso de spread", "Valor": metrics.reinvestimento_excesso_total},
            {"Indicador": "Nova originação efetiva do motor", "Valor": metrics.nova_originacao_total},
            {"Indicador": "Carteira originada efetiva", "Valor": metrics.carteira_total_originada},
            {"Indicador": "SUB final sem perdas", "Valor": metrics.sub_final_sem_inadimplencia},
            {"Indicador": "Colchão sobre carteira originada", "Valor": metrics.colchao_sem_perdas_sobre_originacao},
        ]
    )


def _build_time_protection_export_dataframe(protection_frame: pd.DataFrame) -> pd.DataFrame:
    export = protection_frame.copy()
    export["data"] = export["data"].dt.strftime("%d/%m/%Y")
    return export.rename(
        columns={
            "indice": "Mês do FIDC",
            "data": "Data",
            "pl_sub_jr": "SUB residual",
            "carteira_inicial_considerada": "Carteira inicial considerada",
            "nova_originacao_estimada": "Nova originação estimada",
            "nova_originacao_acumulada": "Nova originação acumulada",
            "nova_originacao_motor": "Nova originação econômica do motor",
            "prazo_medio_recebiveis_meses": "Prazo médio usado (meses)",
            "carteira_originada_acumulada": "Carteira originada acumulada",
            "residual_economico_fluxo": "Residual econômico do fluxo",
            "sub_disponivel": "SUB disponível",
            "perda_maxima_suportada": "Colchão de proteção sobre carteira originada",
            "serie": "Cenário",
        }
    )[
        [
            "Mês do FIDC",
            "Data",
            "Cenário",
            "Carteira inicial considerada",
            "Nova originação estimada",
            "Nova originação acumulada",
            "Nova originação econômica do motor",
            "Prazo médio usado (meses)",
            "Carteira originada acumulada",
            "SUB residual",
            "SUB disponível",
            "Residual econômico do fluxo",
            "Colchão de proteção sobre carteira originada",
        ]
    ]


def _build_workbook_mechanics_markdown(
    *,
    selected_curve: _SelectedCurve,
    selected_calendar: _SelectedCalendar,
    interpolation_label: str,
    taxa_cessao_input_mode: str,
    data_inicial: date | None = None,
    credit_model_label: str = CREDIT_LABEL_NPL90,
) -> str:
    start_label = data_inicial.strftime("%d/%m/%Y") if data_inicial else "data inicial selecionada"
    return "\n".join(
        [
            "Esta seção descreve a mecânica completa da aba e a base de cálculo usada na simulação.",
            "",
            "### 1. Datas, dias corridos e dias úteis",
            "",
            f"- A data inicial padrão é a data-base da curva carregada. Nesta simulação, a data inicial é `{start_label}`.",
            "- O usuário pode sobrescrever a data inicial; nesse caso, a timeline é deslocada, mas a curva DI/Pré selecionada continua sendo a fonte dos juros.",
            "- Se a data sobrescrita estiver distante da data-base da curva, os resultados devem ser lidos como simulação prospectiva com a estrutura de curva selecionada.",
            "- A simulação roda em grade mensal pelo prazo informado ou na grade padrão deslocada a partir da data inicial.",
            "- `DC` é a quantidade de dias corridos desde a data inicial do fluxo.",
            "- `DU` é a quantidade de dias úteis desde a data inicial, descontando fins de semana e feriados.",
            f"- Calendário usado nesta simulação: `{selected_calendar.source_label}`.",
            f"- Curva usada nesta simulação: `{selected_curve.source_label}`, data-base `{selected_curve.base_date:%d/%m/%Y}`, interpolação `{interpolation_label}`.",
            "- Bases temporais atuais por componente: carteira em `delta_DU / 21`, cotas em `delta_DU / 252`, custos em taxa mensal composta, crédito pelo período mensal da simulação e SELIC projetada em `21 DU` médios por mês.",
            "- A carteira ainda usa 21 dias úteis médios como mês financeiro; cotas e curva DI usam DU efetivos em base 252.",
            "",
            "### 2. Taxa da carteira",
            "",
            "- O usuário pode informar a taxa bruta de duas formas:",
            "- `Taxa de Cessão`: deságio nominal sobre o valor futuro no prazo médio dos recebíveis. Ex.: comprar R$ 100 por R$ 95 significa taxa de cessão nominal de `5,00%` no prazo do recebível.",
            "- `Taxa Mensal (%)`: taxa efetiva bruta cobrada ao mês; o motor converte para o deságio nominal equivalente no prazo médio.",
            "- Se houver ágio sobre face, o FIDC paga mais pelo recebível. O ágio reduz a taxa de cessão efetiva e aumenta o EAD econômico.",
            "",
            "```text",
            "taxa_cessao_efetiva = taxa_cessao_nominal - agio_sobre_face",
            "preco_pago = face * (1 - taxa_cessao_efetiva)",
            "taxa_mensal_efetiva = (1 / (1 - taxa_cessao_efetiva)) ^ (1 / prazo_medio_recebiveis_meses) - 1",
            "taxa_cessao_nominal = 1 - 1 / ((1 + taxa_mensal_bruta) ^ prazo_medio_recebiveis_meses)",
            "```",
            "",
            "- Exemplo: face de `R$ 100`, taxa de cessão nominal de `5,00%`, ágio de `1,00%` e prazo de `1 mês` geram preço pago de `R$ 96`, taxa efetiva de cessão de `4,00%` e taxa mensal efetiva de `4,17% a.m.`.",
            "- Sem ágio, o mesmo recebível comprado por `R$ 95` teria taxa mensal efetiva de `5,26% a.m.`.",
            "- A carteira gera retorno econômico por composição da taxa mensal aplicada no período:",
            "",
            "```text",
            "fluxo_carteira = carteira * ((1 + taxa_cessao_am_aplicada) ^ (delta_DU / 21) - 1)",
            "```",
            "",
            "- Em carteira revolvente, `carteira` é o saldo em aberto usado para juros e perda; ele cresce com principal reciclado e excesso de caixa reinvestido enquanto a nova carteira couber no prazo do FIDC.",
            "- A timeline preserva carteira pelo valor de face e mostra EAD/saldo em risco pelo preço pago. A provisão e o NPL usam EAD ajustado quando há ágio sobre face.",
            "",
            f"- Entrada informada pelo usuário nesta simulação: `{taxa_cessao_input_mode}`.",
            "- Em ambos os casos, a aba também calcula o de-para anual em base 252 dias úteis:",
            "",
            "```text",
            "taxa_cessao_aa_252 = (1 + taxa_cessao_am) ^ (252 / 21) - 1",
            "```",
            "",
            "- Se houver excesso de spread sobre a SEN, a taxa mensal aplicada usa um piso:",
            "",
            "```text",
            "taxa_cessao_am_aplicada = max(taxa_informada, CDI + spread_SEN + excesso_spread)",
            "```",
            "",
            "### 3. Custos de administração e gestão",
            "",
            "- O custo percentual é anual, mas o motor calcula uma parcela mensal composta sobre o PL econômico do início do período, com piso mínimo:",
            "",
            "```text",
            "custos_adm = max(PL_inicio * ((1 + custo_adm_aa) ^ (1/12) - 1), custo_minimo_mensal)",
            "```",
            "",
            "- Exemplo: `0,35` na interface significa `0,35% a.a.`; internamente vira `0,0035`.",
            "",
            "### 4. Metodologias de crédito, NPL e provisão",
            "",
            f"- Metodologia selecionada nesta simulação: `{credit_model_label}`.",
            "- Esta seção é a principal para reconciliar a contabilidade econômica do fluxo projetado.",
            "- O motor separa quatro coisas que não devem ser misturadas:",
            "  1. **principal programado para vencer**: parcela da carteira que deveria virar caixa no mês;",
            "  2. **principal inadimplente projetado**: parcela do principal vencendo que não vira caixa e não pode ser reinvestida;",
            "  3. **provisão/despesa de perda**: rubrica que reduz o PL econômico;",
            "  4. **baixa/write-off**: retirada do crédito da carteira, consumindo provisão já formada quando houver saldo.",
            "- Na metodologia `NPL 90 + cobertura de provisão`, o usuário informa quanto do principal que vence no ciclo deve virar NPL 90+ depois do lag. O motor provisiona prospectivamente e baixa o crédito quando ele entra em NPL 90+.",
            "",
            "```text",
            "carteira_vencendo = carteira_inicio * meses_periodo / prazo_medio_recebiveis",
            "npl90_futuro = carteira_vencendo * npl90_esperado_por_ciclo",
            "principal_recebido_liquido = max(carteira_vencendo - npl90_futuro, 0)",
            "entrada_npl90_t = npl90_futuro_de_periodos_anteriores_apos_lag",
            "baixa_credito_t = entrada_npl90_t * LGD",
            "estoque_npl90_t = max(estoque_npl90_t-1 + entrada_npl90_t - baixa_credito_t, 0)",
            "provisao_minima = estoque_npl90_t * cobertura_minima * LGD",
            "provisao_prospectiva = npl90_futuro * LGD",
            "provisao_pos_writeoff = max(provisao_anterior - baixa_credito_t, 0)",
            "provisao_requerida = max(provisao_pos_writeoff + provisao_prospectiva, provisao_minima)",
            "despesa_provisao = writeoff_descoberto + max(provisao_requerida - provisao_pos_writeoff, 0)",
            "```",
            "",
            "- Leitura prática: se `R$ 100` vencem no mês e `20%` devem virar NPL, o motor reconhece `R$ 20` como principal inadimplente projetado e só trata `R$ 80` como principal recebido líquido.",
            "- Esses `R$ 20` não compram nova carteira. Depois do lag, entram em NPL 90+; com `LGD = 100%`, são baixados integralmente contra a provisão disponível.",
            "- Se a provisão anterior for suficiente, o write-off consome provisão e não gera despesa adicional além do reforço necessário para manter a provisão requerida.",
            "- Se a provisão anterior for insuficiente, a parte não coberta aparece como `writeoff_descoberto`, aumentando a despesa de provisão/perda do mês.",
            "- A baixa é imediata no mês em que o crédito entra em NPL 90+. Assim, com `LGD = 100%`, a entrada em NPL 90+ deixa de compor carteira performing no mesmo período.",
            "- A provisão modelada é prospectiva, no estilo `ECL forward-looking`: ela antecipa a perda esperada de ciclo antes do write-off e nunca deixa a provisão abaixo da cobertura mínima do NPL 90+ observado.",
            "- Esta é uma aproximação econômica para simulação e não deve ser lida como regra contábil/regulatória estrita. O objetivo é evitar que a projeção trate principal inadimplente como caixa disponível.",
            "- A implementação atual não reconhece reversão negativa de provisão quando o estoque NPL 90+ cai. Isso é conservador e pode reduzir a SUB final; a revisão com reversão explícita depende de decisão metodológica posterior.",
            "- Na metodologia `Migração por faixas de atraso`, o usuário informa taxas mensais de rolagem entre buckets:",
            "",
            "```text",
            "adimplente -> 1-30 -> 31-60 -> 61-90 -> NPL 90+",
            "recuperacao_90+ entra como caixa",
            "writeoff_90+ baixa a carteira contra provisao",
            "```",
            "",
            "- A provisão requerida continua sendo função de `estoque NPL 90+ * cobertura mínima * LGD`.",
            "- Esta versão avançada usa rolagens agregadas simples. Curvas MOB por safra podem ser adicionadas depois como refinamento, sem mudar a lógica de cobertura.",
            "- Se a taxa mensal da carteira é `11,00%` e a despesa de provisão do mês é `1,00%` da carteira, a despesa consome cerca de `1 / 11` da receita bruta do mês, mas representa `1,00%` do principal em aberto.",
            "",
            "### 5. Taxas SEN e MEZZ",
            "",
            "- Para cotas pós-fixadas, o motor usa `CDI + spread` em convenção aditiva: o spread informado é somado ao CDI, não multiplicado por ele.",
            "",
            "```text",
            "taxa_classe_aa = CDI/PreDI_interpolado + spread_classe_aa",
            "```",
            "",
            "- Para cotas pré-fixadas, o app usa diretamente a taxa anual informada.",
            "- A taxa de cada período é transformada em FRA pela composição entre o ponto atual e o ponto anterior da curva, em base 252 dias úteis.",
            "- Os juros de cada classe são calculados sobre o PL da classe no início do período:",
            "",
            "```text",
            "juros_classe = pl_classe_inicial * ((1 + fra_classe) ^ (delta_DU / 252) - 1)",
            "```",
            "",
            "### 6. Principal, PMT e waterfall atual",
            "",
            "- O motor tem pagamentos programados de SEN e MEZZ. O pagamento de cada classe é:",
            "",
            "```text",
            "PMT SEN = juros SEN + principal SEN programado",
            "PMT MEZZ = juros MEZZ + principal MEZZ programado",
            "```",
            "",
            "- A SUB é residual: não há principal nem juros programados para SUB nesta versão.",
            "- Os PMTs programados de SEN/MEZZ são calculados mesmo quando o fluxo líquido da carteira fica insuficiente.",
            "- Portanto, a trava de caixa está desligada nesta etapa.",
            "",
            "### 7. O que seria a trava de caixa",
            "",
            "- Com trava de caixa ligada, o modelo não pagaria mais aos cotistas do que o caixa disponível no período.",
            "- A ordem econômica esperada seria:",
            "",
            "```text",
            "1. custos e despesas",
            "2. juros SEN",
            "3. principal SEN",
            "4. juros MEZZ",
            "5. principal MEZZ",
            "6. residual SUB",
            "```",
            "",
            "- Se o caixa acabasse no item 3, por exemplo, MEZZ e SUB não receberiam naquele período.",
            "- Essa trava ainda não está implementada; quando for implementada, deve ficar em premissas avançadas.",
            "",
            "### 8. PL econômico e SUB residual",
            "",
            "- Esta seção mostra como o motor fecha o PL econômico mês a mês.",
            "- A receita da carteira e o rendimento de caixa aumentam o PL. Custos, despesa de provisão/perda e PMTs de SEN/MEZZ reduzem o PL.",
            "- O write-off não é subtraído de novo diretamente do PL quando já foi coberto pela provisão. A baixa reduz o ativo carteira; o efeito de resultado passa pela despesa de provisão/perda e pelo eventual `writeoff_descoberto`.",
            "- Depois de retorno da carteira, rendimento do caixa SELIC, custos, perdas e PMTs, o PL econômico do veículo é:",
            "",
            "```text",
            "fluxo_ativos_total = fluxo_carteira + rendimento_caixa_selic + recuperacao_credito",
            "PL FIDC_t = PL FIDC_t-1 + fluxo_ativos_total - custos - despesa_provisao/perda - PMT SEN - PMT MEZZ",
            "```",
            "",
            "- O saldo econômico de SEN e MEZZ cai conforme o principal programado é amortizado.",
            "- A carteira, por sua vez, evolui pelo saldo inicial, nova originação, principal recebido, principal inadimplente, baixas e runoff. Por isso a timeline mostra separadamente `Principal inadimplente não recebido`, `Baixa de crédito/write-off`, `Reinvestimento de principal` e `Reinvestimento de excesso de caixa`.",
            "- A SUB residual corrente é:",
            "",
            "```text",
            "SUB residual = PL FIDC - PL SEN - PL MEZZ",
            "```",
            "",
            "- Se a SUB residual fica positiva, ela representa colchão subordinado disponível.",
            "- Se fica negativa, ela não é um saldo de cota para receber; é déficit econômico depois de consumir toda a SUB.",
            "- A timeline detalhada preserva também a coluna residual histórica para conferência, mas os gráficos usam o residual corrente para evitar distorções como percentuais extremos.",
            "",
            "### 9. Revolvência, denominadores e capacidade de perda",
            "",
            "- Quando a carteira é revolvente, o modelo recicla principal recebido e excesso de caixa enquanto o prazo médio dos recebíveis ainda cabe no prazo restante do FIDC:",
            "",
            "```text",
            "giro_estimado = prazo_total_fidc_anos * 12 / prazo_medio_recebiveis_meses",
            "mes_limite_reinvestimento = prazo_total_fidc_meses - prazo_medio_recebiveis_meses",
            "principal_programado = carteira_inicio * meses_periodo / prazo_medio_recebiveis_meses",
            "principal_recebido_liquido = max(principal_programado - principal_inadimplente, 0)",
            "nova_originacao_economica = principal_recebido_liquido + max(fluxo_remanescente_apos_MEZZ, 0)",
            "```",
            "",
            "- Se o mês do FIDC fica depois do mês limite de reinvestimento, a nova originação econômica vira `0` e a carteira começa a amortizar por runoff.",
            "- A partir desse ponto, o principal dos recebíveis que vence deixa de comprar nova carteira e passa a compor caixa aplicado à SELIC.",
            "- O denominador principal de carteira originada usa a originação efetiva do motor. Portanto, se o modelo reinveste excesso de spread durante a revolvência, esse excesso entra no denominador e na memória de cálculo.",
            "- Essa regra é importante para análise de capacidade de perda: se o fundo comprou mais carteira porque reinvestiu spread, a comparação da SUB final contra a carteira comprada precisa usar essa compra efetiva, não apenas o giro teórico do volume inicial.",
            "",
            "```text",
            "carteira_originada_efetiva = volume_inicial + soma(nova_originacao_economica_t)",
            "nova_originacao_economica_t = reinvestimento_principal_t + reinvestimento_excesso_t",
            "```",
            "",
            "- Exemplo: se o volume inicial é `R$ 750MM` e o motor origina mais `R$ 4,0 bi` entre principal reciclado e excesso de spread, a carteira originada efetiva é `R$ 4,75 bi`. É essa base que deve ser usada para ler o colchão econômico.",
            "- O giro programático continua sendo exibido como referência operacional, mas não substitui o denominador econômico quando a carteira efetivamente cresce por reinvestimento de spread.",
            "- Quando a carteira é estática, a carteira originada é apenas a compra inicial:",
            "",
            "```text",
            "carteira_originada = volume_inicial",
            "```",
            "",
            "- O colchão econômico sem perdas roda uma simulação paralela com crédito zerado e compara o colchão final positivo da SUB com a carteira total originada:",
            "",
            "```text",
            "colchao_sem_perdas = max(SUB_final_sem_perdas, 0) / carteira_originada",
            "```",
            "",
            "- Ao longo do tempo, a carteira originada acumulada é calculada mês a mês:",
            "",
            "```text",
            "nova_originacao_acumulada = volume_inicial * min(mes_fidc, mes_limite_reinvestimento) / prazo_medio_recebiveis_meses",
            "denominador_mes = volume_inicial + nova_originacao_acumulada",
            "protecao_disponivel_no_mes = SUB_disponivel_no_mes / denominador_mes",
            "```",
            "",
            "- Exemplo: com prazo médio de recebíveis de `6 meses`, o mês 1 considera a carteira inicial mais o principal reciclado de cerca de `1/6` do volume inicial.",
            "- Exemplo: em FIDC de `36 meses` com recebíveis de `12 meses`, a originação nova para quando o fluxo chega perto do mês `24`, porque novos recebíveis de 12 meses já não caberiam no prazo da estrutura.",
            "",
            "### 10. Caixa pós-revolvência e SELIC projetada",
            "",
            "- Enquanto a revolvência é elegível, o modelo reinveste principal recebido e excesso de caixa em novos recebíveis.",
            "- Quando o prazo médio dos recebíveis já não cabe no prazo restante do FIDC, o principal recebido deixa de ser reinvestido e entra no saldo de caixa SELIC.",
            "- A taxa SELIC média é uma projeção digitada pelo usuário por ano calendário; nesta etapa ela não vem de fonte externa.",
            "- Esta curva manual remunera apenas o caixa excedente depois que a carteira entra em runoff.",
            "- O CDI implícito das cotas pós-fixadas e o Pre DI na duration continuam usando a curva DI/Pré selecionada na fonte B3/local.",
            "- O default é `13,00% a.a.` para 2026, `12,00% a.a.` para 2027 e `12,00% a.a.` para 2028 em diante; o usuário pode sobrescrever os campos exibidos.",
            "- O motor transforma a taxa anual em taxa do período com matemática financeira exponencial e 21 dias úteis médios por mês:",
            "",
            "```text",
            "taxa_selic_periodo = (1 + selic_aa_do_ano) ^ (21 * meses_periodo / 252) - 1",
            "rendimento_caixa_selic = (caixa_selic_inicio + principal_para_caixa_selic) * taxa_selic_periodo",
            "saldo_caixa_selic_fim = caixa_selic_inicio + principal_para_caixa_selic + fluxo_remanescente_apos_MEZZ - reinvestimento_excesso",
            "```",
            "",
            "- Exemplo: se o prazo médio é `6 meses`, cerca de `1/6` da carteira em aberto vence a cada mês.",
            "- Antes do mês limite de reinvestimento, esse `1/6` recompra recebíveis; depois do mês limite, esse `1/6` vai para caixa SELIC.",
            "- O rendimento do caixa SELIC entra no fluxo econômico total dos ativos antes de custos, perdas e pagamentos das cotas.",
            "- O modelo ainda não usa SELIC observada nem curva de mercado para essa projeção; a premissa é manual para manter rastreabilidade.",
            "",
            "### 11. Indicadores do resumo econômico",
            "",
            "- Retorno anualizado SEN: XIRR dos PMTs SEN contra a data de cada fluxo.",
            "- Retorno anualizado MEZZ: XIRR dos PMTs MEZZ contra a data de cada fluxo.",
            "- Retorno anualizado SUB: só aparece nos cards quando a SUB tem série de caixa válida.",
            "- Duration SEN: média ponderada dos pagamentos SEN descontados, usando `DU / 252`.",
            "- Pre DI na duration: taxa interpolada entre os pontos simulados da curva no DU equivalente à duration da SEN.",
            "- SUB inicial: volume inicial multiplicado pela proporção subordinada.",
            "",
            "### 12. Como interpretar os gráficos",
            "",
            "- `Evolução do saldo das cotas`: mostra SEN, MEZZ, SUB disponível e, quando existir, déficit econômico separado.",
            "- `Perda da carteira`: mostra somente perda do período e perda acumulada.",
            "- `Proteção da estrutura`: mostra subordinação econômica e colchão de proteção.",
            "- `Colchão de proteção` é `SUB disponível / carteira originada acumulada`; ele mede o colchão econômico naquele mês.",
            "- Se a perda acumulada sobe enquanto a subordinação disponível cai para zero, a estrutura está consumindo o colchão subordinado.",
            "- Se aparece déficit econômico, o cenário já ultrapassou a proteção da SUB dentro da mecânica atual.",
            "",
            "### 13. Limitações atuais",
            "",
            "- Ainda não há trava de caixa ligada no waterfall.",
            "- A migração de crédito é agregada por buckets; ainda não há upload de MOB por safra nem capitalização de juros em atraso.",
            "- Ainda não há amortização customizada por classe via interface avançada.",
            "- Ainda não há fluxo programado para SUB; ela permanece residual nesta versão.",
            "",
            "### 14. Limitações conhecidas em backlog",
            "",
            "- Backlog Fase 2 e Fase 3: itens abaixo estão declarados como fila priorizada, não como comportamento escondido.",
            "- Fase 2: a carteira ainda usa `delta_DU / 21`; uma versão futura pode converter a taxa mensal para taxa anual equivalente e aplicar `delta_DU / 252` explicitamente.",
            "- Fase 2: perda e provisão continuam em lógica mensal agregada; uma versão futura pode desdobrar por DU efetivo ou por safra.",
            "- Fase 2: o Pre DI na duration ainda é interpolado a partir dos pontos simulados; pode evoluir para interpolação direta na curva completa.",
            "- Fase 3: a trava de caixa e gatilhos de avaliação/liquidação ainda não limitam PMTs programados.",
            "- Fase 3: a SELIC de caixa pode sair de input manual para fonte/curva de mercado auditável.",
            "- Direção de viés: sem trava de caixa, cenários de stress podem superestimar pagamentos às cotas; sem safra/MOB, a perda é mais simples e menos granular que um motor de crédito completo.",
        ]
    )


def _build_step_by_step_markdown() -> str:
    return "\n".join(
        [
            "Use esta aba como um livro-caixa econômico simplificado do FIDC. A pergunta principal é: depois de juros da carteira, custos, perdas, pagamentos de SEN/MEZZ e reinvestimentos, quanto sobra de colchão econômico para a SUB?",
            "",
            "### 1. Defina o ativo que o fundo compra",
            "",
            "- **Volume da carteira** é o valor de face dos recebíveis comprados no início da simulação.",
            "- **Taxa de Cessão** é o deságio no prazo médio do recebível. **Taxa Mensal** é a taxa efetiva usada pelo motor. A aba mostra a equivalência entre as duas e a taxa anual em base 252.",
            "- **Ágio sobre face** significa pagar mais pelo recebível. Isso reduz a taxa efetiva da carteira e aumenta o EAD econômico; não aparece como despesa separada no mês zero.",
            "- **Prazo médio dos recebíveis** define quanto da carteira vence por mês. Ex.: prazo médio de 6 meses implica, de forma simplificada, cerca de 1/6 da carteira vencendo a cada mês.",
            "",
            "### 2. Defina a estrutura de capital",
            "",
            "- **SEN** recebe antes, **MEZZ** recebe depois da SEN, e **SUB** recebe apenas o residual econômico.",
            "- A SUB absorve o impacto econômico das perdas primeiro: se o PL do fundo cai depois de custos, perdas e pagamentos, a sobra residual da SUB diminui.",
            "- As regras de juros e amortização determinam os PMTs de SEN/MEZZ. A SUB não tem pagamento programado nesta etapa.",
            "",
            "### 3. Entenda a contabilidade mensal do fluxo",
            "",
            "- Em cada mês, o motor começa com a carteira e o PL econômico do mês anterior.",
            "- A carteira gera **juros/receita econômica** pela taxa da carteira.",
            "- Uma parte do principal vence. Se esse principal paga normalmente, ele vira caixa e pode ser reinvestido durante a revolvência.",
            "- Se parte desse principal está projetada para virar NPL 90+, ela **não** é tratada como caixa recebido e **não** é reinvestida automaticamente.",
            "- Depois entram custos, despesa de provisão/perda e PMTs de SEN/MEZZ. O que sobra no PL depois de SEN e MEZZ é a SUB residual.",
            "",
            "### 4. Como ler NPL, provisão e write-off",
            "",
            "- Na metodologia **NPL 90 + cobertura**, o usuário informa o percentual dos recebíveis que vencem no ciclo e devem virar NPL 90+ após o lag.",
            "- O modelo provisiona essa perda de forma prospectiva antes de ela aparecer como estoque NPL 90+. É uma visão econômica tipo ECL, não uma regra contábil/regulatória completa.",
            "- Quando o crédito entra em NPL 90+, o motor aplica a LGD. Com LGD de 100%, a entrada em NPL 90+ é baixada integralmente.",
            "- A baixa consome a provisão já formada. Se a provisão for insuficiente, a diferença vira **write-off descoberto** e aumenta a despesa de perda do mês.",
            "- Importante: o write-off reduz o saldo da carteira; ele não é debitado de novo no PL fora da linha de provisão/perda. Isso evita dupla contagem.",
            "",
            "Exemplo simples: se R$ 100 vencem no mês e 20% devem virar NPL, o caixa de principal recebido é R$ 80. Os R$ 20 são principal inadimplente projetado: não viram reinvestimento. Depois do lag, esses R$ 20 entram em NPL 90+ e, com LGD 100%, são baixados contra provisão.",
            "",
            "### 5. Entenda a revolvência",
            "",
            "- Enquanto ainda há prazo suficiente para comprar novos recebíveis, o motor reinveste dois componentes: principal recebido líquido e excesso de caixa depois dos PMTs de SEN/MEZZ.",
            "- **Principal recebido líquido** é o principal que venceu e pagou, já descontado do principal que vai virar NPL.",
            "- **Excesso de spread reinvestido** é o caixa positivo remanescente após custos, perdas e pagamentos de SEN/MEZZ, quando a carteira ainda é elegível para revolvência.",
            "- Quando o prazo médio dos recebíveis não cabe mais no prazo restante do FIDC, a carteira entra em runoff: o principal recebido deixa de comprar nova carteira e passa a render pela SELIC média informada.",
            "",
            "### 6. Entenda os denominadores",
            "",
            "- **Carteira originada programática** é apenas uma referência teórica de giro do volume inicial.",
            "- **Carteira originada efetiva** é a base reconciliada com o motor: volume inicial + toda nova originação econômica efetiva.",
            "- Se o modelo reinveste excesso de spread, esse reinvestimento aumenta a carteira originada efetiva. Por isso, o colchão sobre carteira originada usa essa base, não apenas o giro teórico.",
            "- **Colchão sobre carteira originada** compara a SUB final sem perdas com a carteira originada efetiva; é uma leitura de quanto excess spread/subordinação foi gerado para cada real efetivamente comprado pelo motor.",
            "",
            "### 7. Como ler os gráficos e a timeline",
            "",
            "- O gráfico de saldos mostra SEN, MEZZ, SUB residual e déficit econômico ao longo do tempo.",
            "- O gráfico de perda mostra despesa de provisão/perda do período e acumulada; não é write-off acumulado nem estoque NPL acumulado.",
            "- O gráfico de proteção compara a subordinação econômica com o colchão de proteção sobre a carteira originada acumulada.",
            "- A timeline detalhada é a memória de cálculo: use as colunas de principal inadimplente, provisão, baixa, reinvestimento e carteira originada para reconciliar cada mês.",
        ]
    )


def _validate_model_inputs(inputs) -> list[str]:
    errors: list[str] = []
    if not inputs.datas:
        errors.append("datas do fluxo ausentes em model_data.json")
    if not inputs.feriados:
        errors.append("lista de feriados vazia em model_data.json")
    return errors


def _validate_snapshot_curve(inputs) -> list[str]:
    errors: list[str] = []
    if not inputs.curva_du or not inputs.curva_cdi:
        errors.append("curva DI/Pre ausente em model_data.json")
    if len(inputs.curva_du) != len(inputs.curva_cdi):
        errors.append("curva_du e curva_cdi têm tamanhos diferentes")
    return errors


def _curve_comparison_metrics(inputs, selected_curve: _SelectedCurve) -> dict[str, float] | None:
    if inputs is None or selected_curve.source_label == CURVE_SOURCE_SNAPSHOT:
        return None
    if selected_curve.base_date != SNAPSHOT_CURVE_DATE:
        return None

    snapshot_by_du = {int(du): float(rate) for du, rate in zip(inputs.curva_du, inputs.curva_cdi)}
    b3_by_du = {int(du): float(rate) for du, rate in zip(selected_curve.curva_du, selected_curve.curva_taxa_aa)}
    common_du = sorted(set(snapshot_by_du) & set(b3_by_du))
    if not common_du:
        return None

    diffs = [b3_by_du[du] - snapshot_by_du[du] for du in common_du]
    abs_diffs = [abs(value) for value in diffs]
    return {
        "pontos_comuns": float(len(common_du)),
        "diferenca_media_bps": sum(abs_diffs) / len(abs_diffs) * 10_000.0,
        "diferenca_max_bps": max(abs_diffs) * 10_000.0,
    }


def _render_curve_source_info(inputs, selected_curve: _SelectedCurve) -> None:
    st.info(
        "\n".join(
            [
                f"Fonte da curva: {selected_curve.source_label}.",
                f"Curva {selected_curve.curve_code} em % a.a., base 252 dias úteis.",
                f"Data-base: {selected_curve.base_date:%d/%m/%Y}; pontos: {_format_number_br(selected_curve.point_count, 0)}; "
                f"DU inicial/final: {selected_curve.first_du or 'N/D'} / {selected_curve.last_du or 'N/D'}.",
            ]
        )
    )
    if selected_curve.source_label != CURVE_SOURCE_SNAPSHOT:
        st.caption(
            f"Arquivo B3: `{selected_curve.source_url}` | baixado em {selected_curve.retrieved_label} | "
            f"SHA-256: `{selected_curve.content_sha256[:12]}`"
        )
    else:
        st.caption(
            "Curva local usada apenas como referência histórica: dados salvos no repositório "
            f"com data-base {SNAPSHOT_CURVE_DATE:%d/%m/%Y}."
        )

    metrics = _curve_comparison_metrics(inputs, selected_curve)
    if metrics is not None:
        st.caption(
            "Comparação B3 x curva local na mesma data: "
            f"{_format_number_br(metrics['pontos_comuns'], 0)} DUs comuns; "
            f"diferença média absoluta {_format_number_br(metrics['diferenca_media_bps'], 2)} bps; "
            f"diferença máxima absoluta {_format_number_br(metrics['diferenca_max_bps'], 2)} bps."
        )
    elif selected_curve.source_label != CURVE_SOURCE_SNAPSHOT:
        st.caption(
            f"A curva local salva é de {SNAPSHOT_CURVE_DATE:%d/%m/%Y}; por isso a comparação ponto a ponto só é exibida "
            "quando a data B3 selecionada é a mesma."
        )


def _render_calendar_source_info(selected_calendar: _SelectedCalendar) -> None:
    official_years = ", ".join(str(year) for year in selected_calendar.official_years) or "N/D"
    projected_years = ", ".join(str(year) for year in selected_calendar.projected_years) or "N/D"
    st.info(
        "\n".join(
            [
                f"Calendário de dias úteis: {selected_calendar.source_label}.",
                f"Feriados considerados: {_format_number_br(selected_calendar.holiday_count, 0)}.",
                f"Anos oficiais B3: {official_years}; anos projetados: {projected_years}.",
                "Os DUs dos fluxos mensais são recalculados com esse calendário antes da interpolação da curva.",
            ]
        )
    )
    if selected_calendar.source_label == CALENDAR_SOURCE_B3_OFFICIAL:
        st.caption(
            f"Calendário B3 consultado em {selected_calendar.retrieved_label}; "
            f"SHA-256 `{selected_calendar.content_sha256[:12]}`. "
            "Anos ainda não publicados pela B3 são preenchidos por projeção explícita."
        )
    elif selected_calendar.source_label == CALENDAR_SOURCE_B3_PROJECTED:
        st.caption(
            "O calendário projetado combina os feriados locais salvos com regras de mercado para anos futuros "
            "do fluxo, incluindo feriados nacionais, Carnaval, Sexta-feira Santa, Corpus Christi e datas sem pregão "
            "como 24/12 e 31/12."
        )
    else:
        last_holiday = selected_calendar.last_holiday.strftime("%d/%m/%Y") if selected_calendar.last_holiday else "N/D"
        st.warning(
            "O calendário local salvo é útil para comparação histórica, mas a lista termina em "
            f"{last_holiday}."
        )


def _render_curve_source_controls(
    inputs,
    selected_curve: _SelectedCurve | None = None,
    selected_calendar: _SelectedCalendar | None = None,
) -> None:
    with st.expander("Fonte da curva DI/Pré", expanded=False):
        st.selectbox(
            "Origem da curva de juros",
            CURVE_SOURCE_OPTIONS,
            key="modelo_curve_source",
            help=(
                "A curva DI/Pré remunera cotas pós-fixadas e calcula o Pre DI na duration. "
                "Use B3 para dados de mercado ou curva local apenas para comparação histórica."
            ),
        )
        if st.session_state.get("modelo_curve_source") == CURVE_SOURCE_B3_DATE:
            st.date_input(
                "Data-base B3",
                key="modelo_b3_date",
                min_value=date(2000, 1, 1),
                max_value=date.today(),
                help="Data exata; sem fallback silencioso.",
            )
        st.selectbox(
            "Metodologia de interpolação",
            INTERPOLATION_OPTIONS,
            key="modelo_interpolation_label",
            help=(
                "Flat Forward 252 preserva a composição financeira em dias úteis entre vértices. "
                "Spline fica disponível como metodologia alternativa."
            ),
        )
        st.selectbox(
            "Calendário de dias úteis",
            CALENDAR_SOURCE_OPTIONS,
            key="modelo_calendar_source",
            help=(
                "O calendário oficial usa a página pública da B3 para anos publicados e projeção explícita para anos futuros. "
                "Os feriados locais salvos ficam disponíveis para comparação histórica."
            ),
        )
        if selected_curve is not None and selected_calendar is not None:
            st.markdown("##### Detalhes da fonte selecionada")
            _render_curve_source_info(inputs, selected_curve)
            _render_calendar_source_info(selected_calendar)


def _render_selic_projection_info(
    *,
    selic_aa_por_ano: tuple[tuple[int, float], ...],
) -> None:
    with st.expander("SELIC média para caixa em runoff", expanded=False):
        st.caption(
            "Esta premissa remunera apenas o caixa excedente depois que a carteira entra em runoff. "
            "Cotas pós-fixadas e Pre DI na duration continuam usando a curva DI/Pré da B3 ou a fonte selecionada."
        )
        curve_df = pd.DataFrame(
            [
                {
                    "Ano": _selic_year_label(year, [projection_year for projection_year, _ in selic_aa_por_ano]),
                    "SELIC média para caixa (% a.a.)": _format_percent(rate),
                }
                for year, rate in selic_aa_por_ano
            ]
        )
        st.dataframe(curve_df, width="stretch", hide_index=True)


def _rate_mode_from_label(label: str) -> str:
    return RATE_MODE_PRE if label.startswith("Pré") else RATE_MODE_POST_CDI


def _build_balance_area_frame(frame: pd.DataFrame) -> pd.DataFrame:
    chart_frame = frame[["indice", "data", "pl_senior", "pl_mezz", "pl_sub_jr"]].copy()
    chart_frame["pl_sub_available"] = chart_frame["pl_sub_jr"].clip(lower=0.0)
    chart_frame["deficit_economico"] = chart_frame["pl_sub_jr"].where(chart_frame["pl_sub_jr"] < 0.0, 0.0)
    stack_items = [
        ("pl_senior", LABELS_COTAS["sen"], 1),
        ("pl_mezz", LABELS_COTAS["mezz"], 2),
        ("pl_sub_available", LABELS_COTAS["sub"], 3),
    ]
    rows: list[dict[str, object]] = []
    for row in chart_frame.itertuples(index=False):
        base = 0.0
        for column, label, order in stack_items:
            value = max(float(getattr(row, column)), 0.0)
            top = base + value
            rows.append(
                {
                    "indice": row.indice,
                    "data": row.data,
                    "classe": label,
                    "ordem": order,
                    "valor": value,
                    "stack_base": base,
                    "stack_top": top,
                }
            )
            base = top
        deficit = min(float(row.deficit_economico), 0.0)
        rows.append(
            {
                "indice": row.indice,
                "data": row.data,
                "classe": "Déficit econômico",
                "ordem": 4,
                "valor": deficit,
                "stack_base": 0.0,
                "stack_top": deficit,
            }
        )
    long_df = pd.DataFrame(rows)
    long_df["valor_milhoes"] = long_df["valor"] / 1_000_000.0
    long_df["stack_base_milhoes"] = long_df["stack_base"] / 1_000_000.0
    long_df["stack_top_milhoes"] = long_df["stack_top"] / 1_000_000.0
    long_df["valor_formatado"] = long_df["valor"].map(_format_brl)
    long_df["periodo"] = long_df["data"].dt.strftime("%d/%m/%Y")
    long_df["mes_fidc"] = long_df["indice"].map(lambda value: f"Mês {int(value)}")
    return long_df


def _available_subordination_pct(row: pd.Series) -> float | None:
    pl_fidc = row.get("pl_fidc")
    pl_sub_jr = row.get("pl_sub_jr")
    if pd.isna(pl_fidc) or pd.isna(pl_sub_jr) or pl_fidc <= 0:
        return None
    return max(float(pl_sub_jr), 0.0) / float(pl_fidc)


def _build_loss_area_frame(
    frame: pd.DataFrame,
    volume: float,
) -> pd.DataFrame:
    loss_column = "perda_carteira_despesa" if "perda_carteira_despesa" in frame.columns else "inadimplencia_despesa"
    chart_frame = frame[["indice", "data", "carteira", loss_column]].copy()
    chart_frame = chart_frame.rename(columns={loss_column: "perda_carteira_despesa"})
    chart_frame["perda_carteira_acumulada"] = chart_frame["perda_carteira_despesa"].fillna(0.0).cumsum()
    chart_frame["perda_periodo_pct"] = chart_frame.apply(
        lambda row: row["perda_carteira_despesa"] / row["carteira"] if row["carteira"] else None,
        axis=1,
    )
    denominator = volume if volume else 1.0
    chart_frame["perda_acumulada_pct"] = chart_frame["perda_carteira_acumulada"] / denominator
    long_df = chart_frame.melt(
        id_vars=["indice", "data"],
        value_vars=["perda_acumulada_pct", "perda_periodo_pct"],
        var_name="serie",
        value_name="valor",
    ).dropna(subset=["valor"])
    label_map = {
        "perda_acumulada_pct": "Perda acumulada",
        "perda_periodo_pct": "Perda do período",
    }
    long_df["serie"] = long_df["serie"].map(label_map)
    formula_map = {
        "Perda acumulada": "Soma das despesas de provisão desde o mês 1",
        "Perda do período": "Despesa de provisão reconhecida no mês",
    }
    long_df["formula_tooltip"] = long_df["serie"].map(formula_map)
    long_df["valor_pct"] = long_df["valor"] * 100.0
    long_df["valor_formatado"] = long_df["valor"].map(_format_percent)
    long_df["periodo"] = long_df["data"].dt.strftime("%d/%m/%Y")
    long_df["mes_fidc"] = long_df["indice"].map(lambda value: f"Mês {int(value)}")
    return long_df


def _build_protection_area_frame(
    frame: pd.DataFrame,
    protection_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    chart_frame = frame[["indice", "data", "pl_fidc", "pl_sub_jr"]].copy()
    chart_frame["subordinacao_display"] = chart_frame.apply(_available_subordination_pct, axis=1)
    long_df = chart_frame.melt(
        id_vars=["indice", "data"],
        value_vars=["subordinacao_display"],
        var_name="serie",
        value_name="valor",
    ).dropna(subset=["valor"])
    long_df["serie"] = "Subordinação econômica"
    long_df["formula_tooltip"] = "max(PL FIDC - PL SEN - PL MEZZ, 0) / PL FIDC"
    long_df["valor_pct"] = long_df["valor"] * 100.0
    long_df["valor_formatado"] = long_df["valor"].map(_format_percent)
    long_df["periodo"] = long_df["data"].dt.strftime("%d/%m/%Y")
    long_df["mes_fidc"] = long_df["indice"].map(lambda value: f"Mês {int(value)}")
    if protection_frame is not None and not protection_frame.empty:
        protection_series = protection_frame[
            ["indice", "data", "perda_maxima_suportada", "valor_pct", "valor_formatado", "periodo", "mes_fidc"]
        ].copy()
        protection_series = protection_series.rename(columns={"perda_maxima_suportada": "valor"})
        protection_series["serie"] = "Colchão de proteção"
        protection_series["formula_tooltip"] = "SUB disponível / carteira originada acumulada"
        long_df = pd.concat([long_df, protection_series[long_df.columns]], ignore_index=True)
    return long_df


def _protection_ratio_chart(chart_df: pd.DataFrame) -> alt.Chart:
    base = alt.Chart(chart_df).encode(
        x=alt.X("indice:Q", title="Mês do FIDC", axis=alt.Axis(tickMinStep=1)),
        y=alt.Y(
            "valor_pct:Q",
            title="% do denominador",
            axis=alt.Axis(labelExpr="replace(format(datum.value, '.1f'), '.', ',') + '%'"),
        ),
        color=alt.Color(
            "serie:N",
            title="Cenário",
            scale=alt.Scale(range=["#2f6f9f", "#59a14f"]),
        ),
        tooltip=[
            alt.Tooltip("mes_fidc:N", title="Mês"),
            alt.Tooltip("periodo:N", title="Período"),
            alt.Tooltip("serie:N", title="Cenário"),
            alt.Tooltip("carteira_inicial_formatada:N", title="Carteira inicial"),
            alt.Tooltip("nova_originacao_formatada:N", title="Nova originação"),
            alt.Tooltip("nova_originacao_acumulada_formatada:N", title="Nova originação acumulada"),
            alt.Tooltip("nova_originacao_motor_formatada:N", title="Originação econômica do motor"),
            alt.Tooltip("residual_fluxo_formatado:N", title="Residual do fluxo"),
            alt.Tooltip("sub_formatada:N", title="SUB disponível"),
            alt.Tooltip("originada_formatada:N", title="Denominador"),
            alt.Tooltip("valor_formatado:N", title="Colchão de proteção"),
        ],
    )
    return (base.mark_line(size=2.4, interpolate="monotone") + base.mark_point(size=42)).properties(height=320)


def _area_money_chart(chart_df: pd.DataFrame) -> alt.Chart:
    color_domain = [LABELS_COTAS["sen"], LABELS_COTAS["mezz"], LABELS_COTAS["sub"], "Déficit econômico"]
    color_range = ["#2f6f9f", "#f28e2b", "#59a14f", "#b23b3b"]
    x_encoding = alt.X("indice:Q", title="Mês do FIDC", axis=alt.Axis(tickMinStep=1))
    color_encoding = alt.Color(
        "classe:N",
        title="Classe",
        scale=alt.Scale(domain=color_domain, range=color_range),
    )
    tooltip = [
        alt.Tooltip("mes_fidc:N", title="Mês"),
        alt.Tooltip("periodo:N", title="Período"),
        alt.Tooltip("classe:N", title="Classe"),
        alt.Tooltip("valor_formatado:N", title="Valor"),
    ]
    area_base = alt.Chart(chart_df).encode(
        x=x_encoding,
        y=alt.Y(
            "stack_top_milhoes:Q",
            title="R$ milhões",
            axis=alt.Axis(labelExpr="replace(format(datum.value, '.1f'), '.', ',')"),
        ),
        y2=alt.Y2("stack_base_milhoes:Q"),
        color=color_encoding,
        order=alt.Order("ordem:Q", sort="ascending"),
        tooltip=tooltip,
    )
    boundary_base = alt.Chart(chart_df).encode(
        x=x_encoding,
        y=alt.Y(
            "stack_top_milhoes:Q",
            title="R$ milhões",
            axis=alt.Axis(labelExpr="replace(format(datum.value, '.1f'), '.', ',')"),
        ),
        color=color_encoding,
        order=alt.Order("ordem:Q", sort="ascending"),
        tooltip=tooltip,
    )
    area = area_base.mark_area(opacity=0.86, interpolate="monotone")
    boundary = boundary_base.mark_line(size=0.9, opacity=0.72, interpolate="monotone")
    return (area + boundary).properties(height=320)


def _area_percent_chart(
    chart_df: pd.DataFrame,
    *,
    y_title: str,
    color_domain: list[str],
    color_range: list[str],
) -> alt.Chart:
    x_encoding = alt.X("indice:Q", title="Mês do FIDC", axis=alt.Axis(tickMinStep=1))
    tooltip = [
        alt.Tooltip("mes_fidc:N", title="Mês"),
        alt.Tooltip("periodo:N", title="Período"),
        alt.Tooltip("serie:N", title="Série"),
        alt.Tooltip("valor_formatado:N", title="Valor"),
    ]
    if "formula_tooltip" in chart_df.columns:
        tooltip.append(alt.Tooltip("formula_tooltip:N", title="Cálculo"))

    base = alt.Chart(chart_df).encode(
        x=x_encoding,
        y=alt.Y(
            "valor_pct:Q",
            title=y_title,
            axis=alt.Axis(labelExpr="replace(format(datum.value, '.1f'), '.', ',') + '%'"),
        ),
        color=alt.Color(
            "serie:N",
            title="Série",
            scale=alt.Scale(domain=color_domain, range=color_range),
        ),
        tooltip=tooltip,
    )
    return (
        base.mark_area(opacity=0.18, interpolate="monotone")
        + base.mark_line(size=2.2, interpolate="monotone")
    ).properties(height=320)


def _chart_definition_caption(kind: str) -> str:
    if kind == "loss":
        return (
            "Perda do período = despesa de provisão reconhecida no mês. "
            "Perda acumulada = soma das despesas de provisão desde o início; não é write-off acumulado nem NPL 90+ acumulado. "
            "A SUB econômica já reflete o efeito líquido de perda, fluxo da carteira, custos e PMTs."
        )
    if kind == "protection":
        return (
            "Subordinação econômica = SUB disponível no mês, isto é, max(PL FIDC - PL SEN - PL MEZZ, 0), exibida como % do PL econômico. "
            "Colchão de proteção = SUB disponível dividida pela carteira originada acumulada até o mês."
        )
    raise ValueError(f"Tipo de legenda de gráfico inválido: {kind}")


def _render_model_header() -> None:
    st.markdown(_MODEL_CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="fidc-model-header">
          <div class="fidc-model-kicker">Simulação econômica</div>
          <h2 class="fidc-model-title">Modelagem</h2>
          <div class="fidc-model-copy">
            Este é um modelo econômico-financeiro para simular cenários de perda máxima em uma
            carteira de FIDC, considerando diferentes níveis de rentabilidade, subordinação e
            perdas de crédito.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _model_tooltip_html(tooltip: str) -> str:
    safe_tooltip = escape(tooltip, quote=True)
    return (
        f'<span class="fidc-model-tooltip" title="{safe_tooltip}" '
        f'data-tooltip="{safe_tooltip}" aria-label="{safe_tooltip}" tabindex="0">?</span>'
    )


def _render_model_kpi_cards(kpis, results, *, has_mezz: bool) -> None:
    cards = [
        (
            "Retorno anualizado",
            _format_percent(kpis.xirr_senior),
            LABELS_COTAS["sen"],
            "Taxa interna de retorno anual dos fluxos da SEN, considerando juros, amortizações e datas do fluxo.",
        ),
        (
            "Retorno anualizado",
            _format_percent(kpis.xirr_sub_jr),
            "Júnior residual",
            "TIR anual do residual da SUB; fica N/D quando os fluxos não permitem uma TIR válida.",
        ),
        (
            "Duration econômica",
            f"{_format_number_br(kpis.duration_senior_anos, 2)} anos" if kpis.duration_senior_anos is not None else "N/D",
            LABELS_COTAS["sen"],
            "Prazo médio ponderado dos pagamentos da SEN; fica menor que o prazo final quando há juros ou amortização antes do vencimento.",
        ),
        (
            "Pre DI na duration",
            _format_percent(kpis.pre_di_duration),
            "Curva interpolada",
            "Taxa DI/Pré interpolada no prazo da duration da SEN, usada como referência de mercado.",
        ),
        (
            "SUB inicial",
            _format_brl(results[0].pl_sub_jr),
            "Colchão subordinado",
            "Valor inicial do colchão subordinado que absorve perdas antes de MEZZ e SEN.",
        ),
    ]
    if has_mezz:
        cards.insert(
            1,
            (
                "Retorno anualizado",
                _format_percent(kpis.xirr_mezz),
                LABELS_COTAS["mezz"],
                "Taxa interna de retorno anual dos fluxos da MEZZ, considerando sua posição no waterfall.",
            ),
        )
    if kpis.xirr_sub_jr is not None:
        cards.insert(
            1 + int(has_mezz),
            (
                "Retorno anualizado",
                _format_percent(kpis.xirr_sub_jr),
                "Júnior residual",
                "TIR anual do residual da SUB quando os fluxos permitem uma TIR válida.",
            ),
        )
    cards_html = "".join(
        (
            '<div class="fidc-model-kpi-card">'
            f'<div class="fidc-model-kpi-label"><span>{escape(label)}</span>'
            f'{_model_tooltip_html(tooltip)}</div>'
            f'<div class="fidc-model-kpi-value">{escape(value)}</div>'
            f'<div class="fidc-model-kpi-context">{escape(context)}</div>'
            "</div>"
        )
        for label, value, context, tooltip in cards
    )
    st.markdown(f'<div class="fidc-model-kpi-grid">{cards_html}</div>', unsafe_allow_html=True)


def _render_revolvency_cards(metrics: _RevolvencyMetrics) -> None:
    cards = [
        (
            "Prazo médio recebíveis",
            f"{_format_number_br(metrics.prazo_medio_recebiveis_meses, 1)} meses",
            "Prazo de giro",
            "Indica em quantos meses, em média, os recebíveis viram caixa para giro da carteira.",
        ),
        (
            "Carteira originada efetiva",
            _format_brl(metrics.carteira_total_originada),
            "Base de comparação",
            "Volume comprado no motor, somando carteira inicial, reinvestimento de principal e reinvestimento de excesso de spread.",
        ),
        (
            "SUB final sem perdas",
            _format_brl(metrics.sub_final_sem_inadimplencia),
            "Colchão acumulado",
            "Valor econômico residual da SUB no fim do prazo em cenário sem perdas de crédito.",
        ),
        (
            "Colchão sobre carteira originada",
            _format_percent(metrics.colchao_sem_perdas_sobre_originacao),
            "SUB final sem perdas / carteira originada",
            "Mede excess spread acumulado sem perdas dividido pela carteira originada efetiva pelo motor.",
        ),
    ]
    cards_html = "".join(
        (
            '<div class="fidc-model-kpi-card">'
            f'<div class="fidc-model-kpi-label"><span>{escape(label)}</span>'
            f'{_model_tooltip_html(tooltip)}</div>'
            f'<div class="fidc-model-kpi-value">{escape(value)}</div>'
            f'<div class="fidc-model-kpi-context">{escape(context)}</div>'
            "</div>"
        )
        for label, value, context, tooltip in cards
    )
    st.markdown(f'<div class="fidc-model-kpi-grid">{cards_html}</div>', unsafe_allow_html=True)


def render_tab_modelo_fidc() -> None:
    inputs = _load_inputs("model_data.json")

    _render_model_header()
    source_errors = _validate_model_inputs(inputs)
    if source_errors:
        st.error("Fonte local do modelo incompleta: " + "; ".join(source_errors) + ".")
        return

    curve_source_label = _ensure_session_option("modelo_curve_source", CURVE_SOURCE_OPTIONS)
    selected_b3_date = _ensure_session_date("modelo_b3_date", date.today() - timedelta(days=1))
    calendar_source_label = _ensure_session_option("modelo_calendar_source", CALENDAR_SOURCE_OPTIONS, default_index=1)
    interpolation_label = _ensure_session_option("modelo_interpolation_label", INTERPOLATION_OPTIONS)
    interpolation_method = _interpolation_method_from_label(interpolation_label)

    try:
        if curve_source_label == CURVE_SOURCE_SNAPSHOT:
            snapshot_errors = _validate_snapshot_curve(inputs)
            if snapshot_errors:
                st.error("Curva local salva incompleta: " + "; ".join(snapshot_errors) + ".")
                _render_curve_source_controls(inputs)
                return
            selected_curve = _selected_curve_from_snapshot(inputs)
        elif curve_source_label == CURVE_SOURCE_B3_DATE:
            with st.spinner("Consultando curva TaxaSwap na B3..."):
                b3_snapshot = _load_b3_curve_for_date(selected_b3_date.isoformat(), DEFAULT_TAXASWAP_CURVE_CODE)
            selected_curve = _selected_curve_from_b3(b3_snapshot, curve_source_label)
        else:
            with st.spinner("Localizando último pregão TaxaSwap disponível na B3..."):
                b3_snapshot = _load_latest_b3_curve(date.today().isoformat(), DEFAULT_TAXASWAP_CURVE_CODE)
            selected_curve = _selected_curve_from_b3(b3_snapshot, curve_source_label)
    except B3CurveError as exc:
        st.error(f"Não foi possível carregar a curva B3: {exc}")
        st.warning("Selecione a curva local salva apenas se quiser rodar uma comparação histórica sem fonte externa.")
        _render_curve_source_controls(inputs)
        return

    default_tx_cessao_am = DEFAULT_TX_CESSAO_AM
    default_tx_cessao_desagio = monthly_rate_to_cession_discount(
        default_tx_cessao_am,
        DEFAULT_PRAZO_RECEBIVEIS_MESES,
    )
    default_senior_pct = DEFAULT_PROP_SENIOR * 100.0
    default_mezz_pct = DEFAULT_PROP_MEZZ * 100.0
    default_sub_pct = DEFAULT_PROP_SUB * 100.0

    left = st.container()
    with left:
        with st.form("modelo-fidc-premissas"):
            st.markdown("##### Premissas da carteira")
            volume_text = _text_brl_input(
                "Volume da carteira (R$)",
                default=DEFAULT_VOLUME_CARTEIRA,
                key="modelo_volume",
                decimals=2,
                help_text="Valor nominal inicial da carteira em reais, sem escala implícita em milhões ou bilhões.",
            )
            taxa_cessao_input_mode = st.radio(
                "Entrada da taxa da carteira",
                [CESSION_INPUT_DISCOUNT, CESSION_INPUT_MONTHLY],
                index=1,
                horizontal=True,
                help="Escolha entre informar deságio no prazo médio ou taxa efetiva mensal da carteira.",
            )
            if taxa_cessao_input_mode == CESSION_INPUT_DISCOUNT:
                tx_cessao_desagio_text = _text_percent_input(
                    "Taxa de Cessão (%)",
                    default=default_tx_cessao_desagio * 100.0,
                    key="modelo_tx_cessao_desagio",
                    decimals=2,
                    help_text="Deságio sobre o valor futuro no prazo médio dos recebíveis; o motor converte para taxa mensal equivalente.",
                )
                tx_cessao_mensal_text = ""
            else:
                tx_cessao_mensal_text = _text_percent_input(
                    "Taxa Mensal (%)",
                    default=default_tx_cessao_am * 100.0,
                    key="modelo_tx_cessao_mensal",
                    decimals=2,
                    help_text="Taxa efetiva mensal bruta aplicada ao saldo da carteira de recebíveis.",
                )
                tx_cessao_desagio_text = ""

            costs_a, costs_b = st.columns(2)
            with costs_a:
                custo_adm_text = _text_percent_input(
                    "Custo de administração e gestão (% a.a. sobre PL)",
                    default=DEFAULT_CUSTO_ADM_AA * 100.0,
                    key="modelo_custo_adm_pct",
                    decimals=2,
                    help_text=HELP_CUSTO_ADM_GESTAO,
                )
            with costs_b:
                custo_min_text = _text_brl_input(
                    "Custo mínimo de administração e gestão (R$/mês)",
                    default=DEFAULT_CUSTO_MIN_MENSAL,
                    key="modelo_custo_min",
                    decimals=2,
                    help_text=HELP_CUSTO_MINIMO,
                )
            st.markdown("##### Crédito e provisão")
            credit_model_label = st.selectbox(
                "Metodologia de crédito",
                list(CREDIT_MODEL_LABELS),
                help="Define se a perda vem de NPL 90+ por ciclo ou de migração mensal entre faixas de atraso.",
            )
            common_credit_a, common_credit_b, common_credit_c = st.columns(3)
            with common_credit_a:
                npl90_lag_text = _text_number_input(
                    "Lag até NPL 90+ (meses)",
                    default=DEFAULT_NPL90_LAG_MESES,
                    key="modelo_npl90_lag_meses",
                    decimals=0,
                    help_text="Meses entre a perda esperada do ciclo e sua entrada no estoque NPL 90+.",
                )
            with common_credit_b:
                cobertura_npl90_text = _text_percent_input(
                    "Cobertura mínima NPL 90+ (%)",
                    default=DEFAULT_COBERTURA_NPL90 * 100.0,
                    key="modelo_cobertura_npl90_pct",
                    decimals=1,
                    help_text="Percentual mínimo do estoque NPL 90+ coberto por provisão, multiplicado pela LGD no cálculo.",
                )
            with common_credit_c:
                lgd_text = _text_percent_input(
                    "LGD econômica (%)",
                    default=DEFAULT_LGD * 100.0,
                    key="modelo_lgd_pct",
                    decimals=1,
                    help_text="Percentual do NPL 90+ não recuperado e tratado como perda econômica.",
                )
            if credit_model_label == CREDIT_LABEL_NPL90:
                perda_ciclo_text = _text_percent_input(
                    "NPL 90+ esperado por ciclo (% dos recebíveis que vencem)",
                    default=DEFAULT_PERDA_CICLO * 100.0,
                    key="modelo_perda_ciclo_pct",
                    decimals=2,
                    help_text="Percentual do principal que vence no período e migra para NPL 90+ após o lag.",
                )
                roll_adimplente_text = roll_1_30_text = roll_31_60_text = roll_61_90_text = "0,00%"
                recuperacao_90_text = writeoff_90_text = "0,00%"
            else:
                perda_ciclo_text = "0,00%"
                roll_a, roll_b = st.columns(2)
                with roll_a:
                    roll_adimplente_text = _text_percent_input(
                        "Rolagem atual → 1-30 (% a.m.)",
                        default=DEFAULT_ROLAGEM_ADIMPLENTE_1_30 * 100.0,
                        key="modelo_roll_adimplente_1_30_pct",
                        decimals=2,
                        help_text="Percentual mensal da carteira adimplente que entra em atraso de 1 a 30 dias.",
                    )
                    roll_31_60_text = _text_percent_input(
                        "Rolagem 31-60 → 61-90 (% a.m.)",
                        default=DEFAULT_ROLAGEM_31_60_61_90 * 100.0,
                        key="modelo_roll_31_60_61_90_pct",
                        decimals=2,
                        help_text="Percentual mensal do bucket 31-60 que migra para atraso de 61 a 90 dias.",
                    )
                    recuperacao_90_text = _text_percent_input(
                        "Recuperação 90+ (% a.m.)",
                        default=DEFAULT_RECUPERACAO_90_PLUS * 100.0,
                        key="modelo_recuperacao_90_plus_pct",
                        decimals=2,
                        help_text="Percentual mensal do estoque 90+ que é recuperado em caixa.",
                    )
                with roll_b:
                    roll_1_30_text = _text_percent_input(
                        "Rolagem 1-30 → 31-60 (% a.m.)",
                        default=DEFAULT_ROLAGEM_1_30_31_60 * 100.0,
                        key="modelo_roll_1_30_31_60_pct",
                        decimals=2,
                        help_text="Percentual mensal do bucket 1-30 que migra para atraso de 31 a 60 dias.",
                    )
                    roll_61_90_text = _text_percent_input(
                        "Rolagem 61-90 → 90+ (% a.m.)",
                        default=DEFAULT_ROLAGEM_61_90_90_PLUS * 100.0,
                        key="modelo_roll_61_90_90_plus_pct",
                        decimals=2,
                        help_text="Percentual mensal do bucket 61-90 que migra para NPL 90+.",
                    )
                    writeoff_90_text = _text_percent_input(
                        "Write-off 90+ (% a.m.)",
                        default=DEFAULT_WRITEOFF_90_PLUS * 100.0,
                        key="modelo_writeoff_90_plus_pct",
                        decimals=2,
                        help_text="Percentual mensal do estoque 90+ baixado contra provisão.",
                    )
            enhancement_a, enhancement_b = st.columns(2)
            with enhancement_a:
                agio_aquisicao_text = _text_percent_input(
                    "Ágio (% sobre face)",
                    default=DEFAULT_AGIO_AQUISICAO * 100.0,
                    key="modelo_agio_aquisicao_pct",
                    decimals=2,
                    help_text="Prêmio pago sobre o valor de face; reduz a taxa de cessão efetiva e aumenta o EAD.",
                )
            with enhancement_b:
                excesso_spread_base = st.radio(
                    "Base do excesso de spread",
                    ["% a.m.", "% a.a. base 252 dias úteis"],
                    horizontal=True,
                    help="Escolha a periodicidade do piso adicional exigido sobre a remuneração da SEN.",
                )
                excesso_spread_text = _text_percent_input(
                    "Excesso de spread sobre SEN",
                    default=DEFAULT_EXCESSO_SPREAD_SENIOR_AM * 100.0,
                    key="modelo_excesso_spread_senior",
                    decimals=2,
                    help_text="Piso adicional ao CDI + spread da SEN; a taxa da carteira não fica abaixo desse CDI+.",
                )

            st.markdown("##### Estrutura de PL")
            prop_a, prop_b, prop_c = st.columns(3)
            with prop_a:
                senior_pct_text = _text_percent_input(
                    "PL sênior/SEN (%)",
                    default=default_senior_pct,
                    key="modelo_prop_senior",
                    decimals=1,
                    help_text="Percentual do PL total alocado à cota SEN; SEN, MEZZ e SUB devem somar 100%.",
                )
            with prop_b:
                mezz_pct_text = _text_percent_input(
                    "PL mezanino/MEZZ (%)",
                    default=default_mezz_pct,
                    key="modelo_prop_mezz",
                    decimals=1,
                    help_text="Percentual do PL total alocado à cota MEZZ; use 0,0% se não houver mezanino.",
                )
            with prop_c:
                sub_pct_text = _text_percent_input(
                    "PL subordinado/SUB (%)",
                    default=default_sub_pct,
                    key="modelo_prop_sub",
                    decimals=1,
                    help_text="Percentual do PL total alocado à SUB, que absorve perdas antes das demais cotas.",
                )
            has_mezz = _parse_percent_for_visibility(mezz_pct_text, default=DEFAULT_PROP_MEZZ) > 0.000001
            st.caption("As proporções SEN, MEZZ e SUB devem somar 100,00%.")

            st.markdown("##### Remuneração das cotas")
            senior_mode_label = st.selectbox(
                "Remuneração cota sênior/SEN",
                ["Pós-fixada: CDI + spread aditivo", "Pré-fixada: taxa % a.a."],
                help=(
                    "Pós-fixada soma o spread ao CDI; por exemplo, 1,35% significa CDI + 1,35% a.a., "
                    "não 101,35% do CDI."
                ),
            )
            senior_rate_label = (
                "Spread aditivo CDI+ da cota SEN (% a.a.)"
                if _rate_mode_from_label(senior_mode_label) == RATE_MODE_POST_CDI
                else "Taxa pré-fixada cota SEN (% a.a.)"
            )
            senior_rate_text = _text_percent_input(
                senior_rate_label,
                default=DEFAULT_TAXA_SENIOR * 100.0,
                key="modelo_taxa_senior",
                decimals=2,
                help_text=(
                    "Spread somado ao CDI: 1,35% significa CDI + 1,35% a.a., não 101,35% do CDI."
                    if _rate_mode_from_label(senior_mode_label) == RATE_MODE_POST_CDI
                    else "Informe a taxa anual pré-fixada da cota SEN."
                ),
            )

            if has_mezz:
                mezz_mode_label = st.selectbox(
                    "Remuneração cota mezanino/MEZZ",
                    ["Pós-fixada: CDI + spread aditivo", "Pré-fixada: taxa % a.a."],
                    help=(
                        "Pós-fixada soma o spread ao CDI; por exemplo, 5,00% significa CDI + 5,00% a.a., "
                        "não 105,00% do CDI."
                    ),
                )
                mezz_rate_label = (
                    "Spread aditivo CDI+ da cota MEZZ (% a.a.)"
                    if _rate_mode_from_label(mezz_mode_label) == RATE_MODE_POST_CDI
                    else "Taxa pré-fixada cota MEZZ (% a.a.)"
                )
                mezz_rate_text = _text_percent_input(
                    mezz_rate_label,
                    default=DEFAULT_TAXA_MEZZ * 100.0,
                    key="modelo_taxa_mezz",
                    decimals=2,
                    help_text=(
                        "Spread somado ao CDI: 5,00% significa CDI + 5,00% a.a., não 105,00% do CDI."
                        if _rate_mode_from_label(mezz_mode_label) == RATE_MODE_POST_CDI
                        else "Informe a taxa anual pré-fixada da cota MEZZ."
                    ),
                )
            else:
                st.caption("Sem cota MEZZ: remuneração, prazo, amortização e juros da MEZZ serão ignorados.")
                mezz_mode_label = "Pré-fixada: taxa % a.a."
                mezz_rate_label = "Taxa pré-fixada cota MEZZ (% a.a.)"
                mezz_rate_text = "0,00"

            sub_mode_label = st.selectbox(
                "Remuneração cota subordinada/SUB",
                [
                    "Residual",
                    "Pós-fixada: CDI + spread aditivo (taxa-alvo)",
                    "Pré-fixada: taxa % a.a. (taxa-alvo)",
                ],
                help="A SUB absorve o residual econômico; taxas-alvo ficam explícitas sem criar pagamento programado.",
            )
            sub_rate_text = "0,00"
            if not sub_mode_label.startswith("Residual"):
                sub_rate_text = _text_percent_input(
                        (
                            "Spread aditivo CDI+ alvo da cota SUB (% a.a.)"
                            if sub_mode_label.startswith("Pós")
                            else "Taxa-alvo pré-fixada cota SUB (% a.a.)"
                        ),
                    default=0.0,
                    key="modelo_taxa_sub",
                    decimals=2,
                    help_text=(
                        "Spread-alvo somado ao CDI: 1,35% significa CDI + 1,35% a.a., não 101,35% do CDI."
                        if sub_mode_label.startswith("Pós")
                        else "Informe a taxa-alvo anual pré-fixada da SUB."
                    ),
                )

            with st.expander("Premissas avançadas de prazo, revolvência e waterfall", expanded=False):
                st.markdown("##### Prazo e originação")
                data_inicial_fidc = st.date_input(
                    "Data inicial do FIDC",
                    value=selected_curve.base_date,
                    key="modelo_data_inicial",
                    help=(
                        "Por padrão usa o último pregão da curva carregada; sobrescrever mantém a curva selecionada "
                        "e desloca a timeline do fluxo."
                    ),
                )
                date_schedule_label = st.selectbox(
                    "Cronograma do fluxo",
                    [DATE_SCHEDULE_WORKBOOK, DATE_SCHEDULE_MONTHLY],
                    index=1,
                    help=(
                        "A grade semestral padrão mantém datas espaçadas por semestre. "
                        "O modo mensal gera novas competências até o prazo total informado."
                    ),
                )
                term_a, term_b, term_c = st.columns(3)
                with term_a:
                    prazo_fidc_text = _text_number_input(
                        "Prazo total do FIDC (anos)",
                        default=DEFAULT_PRAZO_ANOS,
                        key="modelo_prazo_fidc_anos",
                        decimals=1,
                        help_text="Prazo total da simulação em anos, usado para definir o último mês do fluxo.",
                    )
                with term_b:
                    prazo_recebiveis_text = _text_number_input(
                        "Prazo médio dos recebíveis (meses)",
                        default=DEFAULT_PRAZO_RECEBIVEIS_MESES,
                        key="modelo_prazo_recebiveis_meses",
                        decimals=1,
                        help_text="Prazo médio de vencimento da carteira, em meses, usado no giro e no runoff.",
                    )
                with term_c:
                    portfolio_mode_label = st.selectbox(
                        "Originação da carteira",
                        [PORTFOLIO_MODE_REVOLVING, PORTFOLIO_MODE_STATIC],
                        help=(
                            "No modo revolvente, o principal recebido e o excesso de caixa recompram recebíveis "
                            "enquanto o prazo médio couber no prazo restante do FIDC."
                        ),
                    )

                st.markdown("##### Caixa pós-revolvência")
                st.caption(
                    "Quando a carteira deixa de comprar novos recebíveis, o principal recebido entra em caixa "
                    "e passa a render pela SELIC média anual informada abaixo."
                )
                selic_years = _projection_years_for_term(
                    datetime.combine(data_inicial_fidc, datetime.min.time()),
                    _safe_term_years_from_text(prazo_fidc_text),
                )
                selic_text_by_year: dict[int, str] = {}
                for row_start in range(0, len(selic_years), 3):
                    selic_columns = st.columns(min(3, len(selic_years) - row_start))
                    for column, year in zip(selic_columns, selic_years[row_start : row_start + 3]):
                        with column:
                            selic_text_by_year[year] = _text_percent_input(
                                f"SELIC média {_selic_year_label(year, selic_years)} (% a.a.)",
                                default=_default_selic_rate_for_year(year) * 100.0,
                                key=f"modelo_selic_aa_{year}",
                                decimals=2,
                                help_text=(
                                    "Informe a SELIC média anual usada apenas para remunerar caixa em runoff; "
                                    "a última taxa é perpetuada para anos posteriores."
                                ),
                            )

                st.markdown("##### Cotas SEN e MEZZ")
                st.caption(
                    "O cronograma padrão preserva a regra semestral original do motor. "
                    "Os demais modos alteram os pagamentos programados no motor."
                )
                if has_mezz:
                    senior_cfg_a, senior_cfg_b = st.columns(2)
                else:
                    senior_cfg_a = st.container()
                    senior_cfg_b = None
                with senior_cfg_a:
                    prazo_senior_text = _text_number_input(
                        "Prazo cota SEN (anos)",
                        default=DEFAULT_PRAZO_ANOS,
                        key="modelo_prazo_senior_anos",
                        decimals=1,
                        help_text="Prazo legal/econômico da cota SEN, em anos, usado no cronograma de principal.",
                    )
                    senior_amort_label = st.selectbox(
                        "Amortização principal SEN",
                        list(AMORTIZATION_LABELS),
                        index=1,
                        key="modelo_amort_senior",
                        help="Define quando e como o principal da SEN é amortizado no waterfall.",
                    )
                    senior_start_text = _text_number_input(
                        "Carência principal SEN (meses)",
                        default=DEFAULT_CARENCIA_PRINCIPAL_MESES,
                        key="modelo_inicio_amort_senior",
                        decimals=0,
                        help_text="Número de meses antes do início da amortização de principal da SEN.",
                    )
                if has_mezz and senior_cfg_b is not None:
                    with senior_cfg_b:
                        prazo_mezz_text = _text_number_input(
                            "Prazo cota MEZZ (anos)",
                            default=DEFAULT_PRAZO_ANOS,
                            key="modelo_prazo_mezz_anos",
                            decimals=1,
                            help_text="Prazo legal/econômico da cota MEZZ, em anos, usado no cronograma de principal.",
                        )
                        mezz_amort_label = st.selectbox(
                            "Amortização principal MEZZ",
                            list(AMORTIZATION_LABELS),
                            index=1,
                            key="modelo_amort_mezz",
                            help="Define quando e como o principal da MEZZ é amortizado no waterfall.",
                        )
                        mezz_start_text = _text_number_input(
                            "Carência principal MEZZ (meses)",
                            default=DEFAULT_CARENCIA_PRINCIPAL_MESES,
                            key="modelo_inicio_amort_mezz",
                            decimals=0,
                            help_text="Número de meses antes do início da amortização de principal da MEZZ.",
                        )
                else:
                    prazo_mezz_text = prazo_fidc_text
                    mezz_amort_label = "Sem amortização programada"
                    mezz_start_text = "0"

                interest_columns = st.columns(3 if has_mezz else 2)
                interest_a = interest_columns[0]
                interest_b = interest_columns[1] if has_mezz else None
                interest_c = interest_columns[2] if has_mezz else interest_columns[1]
                with interest_a:
                    senior_interest_label = st.selectbox(
                        "Pagamento de juros SEN",
                        list(INTEREST_LABELS),
                        key="modelo_juros_senior",
                        help="Define se os juros da SEN são pagos periodicamente, após carência ou no vencimento.",
                    )
                if has_mezz and interest_b is not None:
                    with interest_b:
                        mezz_interest_label = st.selectbox(
                            "Pagamento de juros MEZZ",
                            list(INTEREST_LABELS),
                            key="modelo_juros_mezz",
                            help="Define se os juros da MEZZ são pagos periodicamente, após carência ou no vencimento.",
                        )
                else:
                    mezz_interest_label = "Pago em todo período"
                with interest_c:
                    prazo_sub_text = _text_number_input(
                        "Prazo cota SUB (anos)",
                        default=DEFAULT_PRAZO_ANOS,
                        key="modelo_prazo_sub_anos",
                        decimals=1,
                        help_text="Prazo informativo da SUB; nesta versão a SUB segue como residual econômico.",
                    )
                st.caption("A SUB segue residual nesta etapa; o prazo da SUB entra na documentação e na análise econômica.")
            submitted = st.form_submit_button(
                "Rodar simulação",
                width="stretch",
                on_click=_normalize_model_input_values,
            )

    try:
        volume = _parse_br_number(volume_text, field_name="Volume da carteira (R$)")
        prazo_fidc_anos = _parse_br_number(prazo_fidc_text, field_name="Prazo total do FIDC (anos)")
        prazo_medio_recebiveis_meses = _parse_br_number(
            prazo_recebiveis_text,
            field_name="Prazo médio dos recebíveis (meses)",
        )
        agio_aquisicao = _parse_br_number(
            agio_aquisicao_text,
            field_name="Ágio (% sobre face)",
        ) / 100.0
        if taxa_cessao_input_mode == CESSION_INPUT_DISCOUNT:
            tx_cessao_desagio_nominal = _parse_br_number(tx_cessao_desagio_text, field_name="Taxa de Cessão (%)") / 100.0
        else:
            tx_cessao_am_nominal = _parse_br_number(tx_cessao_mensal_text, field_name="Taxa Mensal (%)") / 100.0
            tx_cessao_desagio_nominal = monthly_rate_to_cession_discount(
                tx_cessao_am_nominal,
                prazo_medio_recebiveis_meses,
            )
        tx_cessao_desagio = _effective_cession_discount_after_premium(tx_cessao_desagio_nominal, agio_aquisicao)
        tx_cessao_am = cession_discount_to_monthly_rate(tx_cessao_desagio, prazo_medio_recebiveis_meses)
        tx_cessao_aa_equivalente = monthly_to_annual_252_rate(tx_cessao_am)
        custo_adm_aa = _parse_br_number(custo_adm_text, field_name="Custo de administração e gestão (% a.a. sobre PL)") / 100.0
        custo_min = _parse_br_number(custo_min_text, field_name="Custo mínimo de administração e gestão (R$/mês)")
        modelo_credito = CREDIT_MODEL_LABELS[credit_model_label]
        perda_ciclo = _parse_br_number(
            perda_ciclo_text,
            field_name="NPL 90+ esperado por ciclo (% dos recebíveis que vencem)",
        ) / 100.0
        npl90_lag_meses = int(round(_parse_br_number(npl90_lag_text, field_name="Lag até NPL 90+ (meses)")))
        cobertura_minima_npl90 = _parse_br_number(
            cobertura_npl90_text,
            field_name="Cobertura mínima NPL 90+ (%)",
        ) / 100.0
        lgd = _parse_br_number(lgd_text, field_name="LGD econômica (%)") / 100.0
        rolagem_adimplente_1_30 = _parse_br_number(
            roll_adimplente_text,
            field_name="Rolagem atual → 1-30 (% a.m.)",
        ) / 100.0
        rolagem_1_30_31_60 = _parse_br_number(
            roll_1_30_text,
            field_name="Rolagem 1-30 → 31-60 (% a.m.)",
        ) / 100.0
        rolagem_31_60_61_90 = _parse_br_number(
            roll_31_60_text,
            field_name="Rolagem 31-60 → 61-90 (% a.m.)",
        ) / 100.0
        rolagem_61_90_90_plus = _parse_br_number(
            roll_61_90_text,
            field_name="Rolagem 61-90 → 90+ (% a.m.)",
        ) / 100.0
        recuperacao_90_plus = _parse_br_number(
            recuperacao_90_text,
            field_name="Recuperação 90+ (% a.m.)",
        ) / 100.0
        writeoff_90_plus = _parse_br_number(
            writeoff_90_text,
            field_name="Write-off 90+ (% a.m.)",
        ) / 100.0
        if excesso_spread_base == "% a.m.":
            excesso_spread_senior_am = _parse_br_number(
                excesso_spread_text,
                field_name="Excesso de spread sobre SEN (% a.m.)",
            ) / 100.0
            excesso_spread_senior_aa = monthly_to_annual_252_rate(excesso_spread_senior_am)
        else:
            excesso_spread_senior_aa = _parse_br_number(
                excesso_spread_text,
                field_name="Excesso de spread sobre SEN (% a.a. base 252)",
            ) / 100.0
            excesso_spread_senior_am = annual_252_to_monthly_rate(excesso_spread_senior_aa)
        proporcao_senior = _parse_br_number(senior_pct_text, field_name="PL sênior/SEN (%)") / 100.0
        proporcao_mezz = _parse_br_number(mezz_pct_text, field_name="PL mezanino/MEZZ (%)") / 100.0
        proporcao_sub = _parse_br_number(sub_pct_text, field_name="PL subordinado/SUB (%)") / 100.0
        taxa_senior = _parse_br_number(senior_rate_text, field_name=senior_rate_label) / 100.0
        taxa_mezz = _parse_br_number(mezz_rate_text, field_name=mezz_rate_label) / 100.0
        taxa_sub = _parse_br_number(sub_rate_text, field_name="Taxa-alvo cota SUB (% a.a.)") / 100.0
        user_selic_aa_por_ano = tuple(
            (
                year,
                _parse_br_number(
                    text,
                    field_name=f"SELIC média {_selic_year_label(year, list(selic_text_by_year))} (% a.a.)",
                )
                / 100.0,
            )
            for year, text in sorted(selic_text_by_year.items())
        )
        prazo_senior_anos = _parse_br_number(prazo_senior_text, field_name="Prazo cota SEN (anos)")
        prazo_mezz_anos = _parse_br_number(prazo_mezz_text, field_name="Prazo cota MEZZ (anos)")
        prazo_sub_anos = _parse_br_number(prazo_sub_text, field_name="Prazo cota SUB (anos)")
        inicio_amortizacao_senior_meses = int(
            round(_parse_br_number(senior_start_text, field_name="Carência principal SEN (meses)"))
        )
        inicio_amortizacao_mezz_meses = int(
            round(_parse_br_number(mezz_start_text, field_name="Carência principal MEZZ (meses)"))
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    if volume <= 0:
        st.error("O volume da carteira deve ser maior que zero.")
        return
    if prazo_fidc_anos <= 0 or prazo_medio_recebiveis_meses <= 0:
        st.error("O prazo total do FIDC e o prazo médio dos recebíveis devem ser maiores que zero.")
        return
    if min(prazo_senior_anos, prazo_mezz_anos, prazo_sub_anos) <= 0:
        st.error("Os prazos das cotas devem ser maiores que zero.")
        return
    if min(inicio_amortizacao_senior_meses, inicio_amortizacao_mezz_meses) < 0:
        st.error("A carência de principal não pode ser negativa.")
        return
    credit_percent_values = [
        perda_ciclo,
        cobertura_minima_npl90,
        lgd,
        rolagem_adimplente_1_30,
        rolagem_1_30_31_60,
        rolagem_31_60_61_90,
        rolagem_61_90_90_plus,
        recuperacao_90_plus,
        writeoff_90_plus,
    ]
    if min(credit_percent_values) < 0 or npl90_lag_meses < 0:
        st.error("Premissas de crédito, provisão, LGD e rolagem não podem ser negativas.")
        return
    if max(perda_ciclo, lgd, rolagem_adimplente_1_30, rolagem_1_30_31_60, rolagem_31_60_61_90, rolagem_61_90_90_plus, recuperacao_90_plus, writeoff_90_plus) > 1.0:
        st.error("Percentuais de perda, LGD, rolagem, recuperação e write-off devem ficar entre 0,00% e 100,00%.")
        return
    if agio_aquisicao < 0 or excesso_spread_senior_am < 0:
        st.error("Ágio sobre face e excesso de spread não podem ser negativos.")
        return
    if any(rate < 0 for _, rate in user_selic_aa_por_ano):
        st.error("As taxas SELIC projetadas não podem ser negativas.")
        return

    prop_total = proporcao_senior + proporcao_mezz + proporcao_sub
    if abs(prop_total - 1.0) > 0.0001:
        st.error(f"As proporções de PL precisam somar 100,00%. Soma atual: {_format_percent(prop_total)}.")
        return

    if isinstance(data_inicial_fidc, datetime):
        data_inicial_date = data_inicial_fidc.date()
    else:
        data_inicial_date = data_inicial_fidc
    data_inicial_dt = datetime.combine(data_inicial_date, datetime.min.time())
    simulation_dates = _build_simulation_dates(inputs, date_schedule_label, prazo_fidc_anos, data_inicial_dt)
    if data_inicial_date != selected_curve.base_date:
        st.warning(
            "A data inicial do FIDC foi sobrescrita para "
            f"{data_inicial_date:%d/%m/%Y}, mas a curva DI/Pré carregada tem data-base "
            f"{selected_curve.base_date:%d/%m/%Y}. A simulação segue com essa curva e desloca a timeline."
        )
    try:
        effective_selic_aa_por_ano = _effective_selic_projection_for_dates(user_selic_aa_por_ano, simulation_dates)
    except ValueError as exc:
        st.error(str(exc))
        return

    premissas = Premissas(
        volume=volume,
        tx_cessao_am=tx_cessao_am,
        tx_cessao_cdi_aa=inputs.premissas.get("Tx Cessão (CDI+ %aa)"),
        custo_adm_aa=custo_adm_aa,
        custo_min=custo_min,
        inadimplencia=0.0,
        proporcao_senior=proporcao_senior,
        taxa_senior=taxa_senior,
        proporcao_mezz=proporcao_mezz,
        taxa_mezz=taxa_mezz,
        proporcao_subordinada=proporcao_sub,
        taxa_sub_jr=taxa_sub,
        tipo_taxa_senior=_rate_mode_from_label(senior_mode_label),
        tipo_taxa_mezz=_rate_mode_from_label(mezz_mode_label),
        tipo_taxa_sub_jr=(
            "residual"
            if sub_mode_label.startswith("Residual")
            else RATE_MODE_PRE
            if sub_mode_label.startswith("Pré")
            else RATE_MODE_POST_CDI
        ),
        prazo_fidc_anos=prazo_fidc_anos,
        prazo_medio_recebiveis_meses=prazo_medio_recebiveis_meses,
        carteira_revolvente=portfolio_mode_label == PORTFOLIO_MODE_REVOLVING,
        prazo_senior_anos=prazo_senior_anos,
        prazo_mezz_anos=prazo_mezz_anos,
        prazo_sub_jr_anos=prazo_sub_anos,
        amortizacao_senior=AMORTIZATION_LABELS[senior_amort_label],
        amortizacao_mezz=AMORTIZATION_LABELS[mezz_amort_label],
        juros_senior=INTEREST_LABELS[senior_interest_label],
        juros_mezz=INTEREST_LABELS[mezz_interest_label],
        inicio_amortizacao_senior_meses=inicio_amortizacao_senior_meses,
        inicio_amortizacao_mezz_meses=inicio_amortizacao_mezz_meses,
        perda_esperada_am=0.0,
        perda_inesperada_am=0.0,
        modelo_credito=modelo_credito,
        perda_ciclo=perda_ciclo,
        npl90_lag_meses=npl90_lag_meses,
        cobertura_minima_npl90=cobertura_minima_npl90,
        lgd=lgd,
        rolagem_adimplente_1_30=rolagem_adimplente_1_30,
        rolagem_1_30_31_60=rolagem_1_30_31_60,
        rolagem_31_60_61_90=rolagem_31_60_61_90,
        rolagem_61_90_90_plus=rolagem_61_90_90_plus,
        recuperacao_90_plus=recuperacao_90_plus,
        writeoff_90_plus=writeoff_90_plus,
        agio_aquisicao=agio_aquisicao,
        excesso_spread_senior_am=excesso_spread_senior_am,
        selic_aa_por_ano=effective_selic_aa_por_ano,
    )

    if agio_aquisicao > 0.0:
        st.caption(
            "Equivalência da taxa da carteira: "
            f"Taxa de Cessão nominal {_format_percent(tx_cessao_desagio_nominal)} menos ágio "
            f"{_format_percent(agio_aquisicao)} = taxa efetiva {_format_percent(tx_cessao_desagio)} "
            f"no prazo médio de {_format_number_br(prazo_medio_recebiveis_meses, 1)} meses | "
            f"Taxa Mensal efetiva {_format_percent(tx_cessao_am)} | "
            f"Taxa anual base 252 {_format_percent(tx_cessao_aa_equivalente)}."
        )
    else:
        st.caption(
            "Equivalência da taxa da carteira: "
            f"Taxa de Cessão {_format_percent(tx_cessao_desagio)} no prazo médio de "
            f"{_format_number_br(prazo_medio_recebiveis_meses, 1)} meses | "
            f"Taxa Mensal {_format_percent(tx_cessao_am)} | "
            f"Taxa anual base 252 {_format_percent(tx_cessao_aa_equivalente)}."
        )
    if modelo_credito == CREDIT_MODEL_NPL90:
        st.caption(
            "Crédito e provisão: "
            f"NPL 90+ esperado {_format_percent(perda_ciclo)} dos recebíveis que vencem; "
            f"lag {npl90_lag_meses} meses; cobertura mínima {_format_percent(cobertura_minima_npl90)} "
            f"do NPL 90+ com LGD {_format_percent(lgd)}."
        )
    else:
        st.caption(
            "Crédito e provisão: migração mensal por faixas de atraso até NPL 90+, "
            f"cobertura mínima {_format_percent(cobertura_minima_npl90)} e LGD {_format_percent(lgd)}. "
            "Recuperações entram como caixa; write-offs baixam a carteira contra provisão."
        )
    st.caption(
        "Sofisticações da carteira: "
        f"ágio sobre face {_format_percent(agio_aquisicao)}; "
        f"excesso de spread SEN {_format_percent(excesso_spread_senior_am)} a.m. "
        f"({_format_percent(excesso_spread_senior_aa)} a.a. base 252). "
        "Por ser um piso, a taxa aplicada usa o maior valor entre a taxa informada e CDI + spread da SEN + excesso."
    )
    st.caption(
        "Caixa pós-revolvência: "
        + "; ".join(
            f"{_selic_year_label(year, [projection_year for projection_year, _ in user_selic_aa_por_ano])}: {_format_percent(rate)} a.a."
            for year, rate in user_selic_aa_por_ano
        )
        + ". Esta curva remunera apenas o caixa excedente quando a carteira entra em runoff."
    )

    try:
        if calendar_source_label == CALENDAR_SOURCE_B3_OFFICIAL:
            with st.spinner("Consultando calendário de negociação da B3..."):
                b3_calendar_snapshot = _load_b3_calendar_snapshot(simulation_dates[0].year, simulation_dates[-1].year)
            selected_calendar = _selected_calendar(
                inputs,
                calendar_source_label,
                b3_calendar_snapshot,
                datas=simulation_dates,
            )
        else:
            selected_calendar = _selected_calendar(inputs, calendar_source_label, datas=simulation_dates)
    except B3CalendarError as exc:
        st.error(f"Não foi possível carregar o calendário B3: {exc}")
        st.warning("Selecione o calendário projetado se quiser rodar a simulação sem consultar a página pública da B3.")
        _render_curve_source_controls(inputs, selected_curve)
        return

    if not sub_mode_label.startswith("Residual"):
        st.warning(
            "A taxa da SUB está registrada como taxa-alvo informativa. A versão atual não possui pagamento "
            "programado da SUB; por isso, o waterfall mantém a SUB como residual."
        )

    simulation_signature = (
        selected_curve.cache_key,
        selected_calendar.cache_key,
        interpolation_method,
        tuple(dt.isoformat() for dt in simulation_dates),
        premissas,
    )
    if (
        not submitted
        and st.session_state.get("modelo_fidc_signature") == simulation_signature
        and "modelo_fidc_periods" in st.session_state
    ):
        results = st.session_state["modelo_fidc_periods"]
        kpis = st.session_state["modelo_fidc_kpis"]
    else:
        results = build_flow(
            simulation_dates,
            selected_calendar.feriados,
            selected_curve.curva_du,
            selected_curve.curva_taxa_aa,
            premissas,
            interpolation_method=interpolation_method,
        )
        kpis = build_kpis(results)
        st.session_state["modelo_fidc_signature"] = simulation_signature
        st.session_state["modelo_fidc_periods"] = results
        st.session_state["modelo_fidc_kpis"] = kpis

    if not results:
        st.info("Sem datas suficientes para montar o fluxo.")
        return

    zero_default_results = build_flow(
        simulation_dates,
        selected_calendar.feriados,
        selected_curve.curva_du,
        selected_curve.curva_taxa_aa,
        _premissas_sem_perdas(premissas),
        interpolation_method=interpolation_method,
    )
    revolvency_metrics = _build_revolvency_metrics(
        premissas=premissas,
        zero_default_results=zero_default_results,
        portfolio_mode=portfolio_mode_label,
    )

    frame = _build_dataframe(results)
    zero_default_frame = _build_dataframe(zero_default_results)
    protection_frame = _build_time_protection_frame(
        frame,
        premissas=premissas,
        portfolio_mode=portfolio_mode_label,
        scenario_label="Cenário com perdas",
    )
    zero_protection_frame = _build_time_protection_frame(
        zero_default_frame,
        premissas=premissas,
        portfolio_mode=portfolio_mode_label,
        scenario_label="Cenário sem perdas",
    )
    protection_chart_frame = pd.concat([protection_frame, zero_protection_frame], ignore_index=True)
    export_frame = _build_export_dataframe(frame)
    display_frame = _build_display_dataframe(export_frame)

    st.markdown('<div class="fidc-model-section-title">Resumo econômico</div>', unsafe_allow_html=True)
    _render_model_kpi_cards(kpis, results, has_mezz=proporcao_mezz > 0.000001)

    st.markdown('<div class="fidc-model-section-title">Capacidade de perda e denominadores</div>', unsafe_allow_html=True)
    _render_revolvency_cards(revolvency_metrics)

    st.markdown('<div class="fidc-model-section-title">Evolução do saldo das cotas</div>', unsafe_allow_html=True)
    st.altair_chart(_area_money_chart(_build_balance_area_frame(frame)), width="stretch")

    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.markdown('<div class="fidc-model-section-title">Perda da carteira</div>', unsafe_allow_html=True)
        st.caption(_chart_definition_caption("loss"))
        st.altair_chart(
            _area_percent_chart(
                _build_loss_area_frame(frame, premissas.volume),
                y_title="Perda da carteira (%)",
                color_domain=["Perda acumulada", "Perda do período"],
                color_range=["#d62728", "#f28e2b"],
            ),
            width="stretch",
        )
    with chart_right:
        st.markdown('<div class="fidc-model-section-title">Proteção da estrutura</div>', unsafe_allow_html=True)
        st.caption(_chart_definition_caption("protection"))
        st.altair_chart(
            _area_percent_chart(
                _build_protection_area_frame(frame, protection_frame),
                y_title="Proteção da estrutura (%)",
                color_domain=["Subordinação econômica", "Colchão de proteção"],
                color_range=["#2f6f9f", "#59a14f"],
            ),
            width="stretch",
        )

    memory_df = pd.DataFrame(
        [
            {
                "Indicador": "Data inicial do FIDC",
                "Fórmula": "default = data-base da curva carregada; usuário pode sobrescrever",
                "Observação": f"Data inicial selecionada: {data_inicial_date:%d/%m/%Y}; curva DI/Pré data-base: {selected_curve.base_date:%d/%m/%Y}.",
            },
            {
                "Indicador": "Fluxo econômico da carteira",
                "Fórmula": "carteira * ((1 + tx_cessao_am_aplicada) ^ (delta_du / 21) - 1)",
                "Observação": "Em carteira revolvente, a base de carteira evolui com principal reciclado e excesso de caixa reinvestido enquanto houver prazo para nova originação.",
            },
            {
                "Indicador": "Rendimento do caixa SELIC",
                "Fórmula": "rendimento_selic = (caixa_selic_inicio + principal_para_caixa_selic) * ((1 + selic_aa) ^ (21 * meses_periodo / 252) - 1)",
                "Observação": "Quando a carteira não pode mais comprar recebíveis, o principal que vence passa a render pela SELIC média anual informada pelo usuário.",
            },
            {
                "Indicador": "Fluxo econômico total dos ativos",
                "Fórmula": "fluxo_ativos_total = fluxo_carteira + rendimento_caixa_selic + recuperacao_credito",
                "Observação": "Este é o fluxo usado antes de custos, provisão/perda e pagamentos das cotas; a SELIC só entra sobre caixa fora da janela de reinvestimento.",
            },
            {
                "Indicador": "De-para da Taxa de Cessão",
                "Fórmula": "tx_cessao_efetiva = tx_cessao_nominal - agio; tx_am = (1 / (1 - tx_cessao_efetiva)) ^ (1 / prazo_medio_recebiveis_meses) - 1",
                "Observação": "Ex.: face R$ 100, deságio 5,00% e ágio 1,00% implicam preço pago R$ 96, taxa efetiva de cessão 4,00% e taxa mensal menor.",
            },
            {
                "Indicador": "Conversão anual base 252",
                "Fórmula": "tx_cessao_aa_252 = (1 + tx_cessao_am) ^ (252 / 21) - 1",
                "Observação": "Conversão financeira efetiva, com 21 dias úteis médios por mês e 252 dias úteis por ano.",
            },
            {
                "Indicador": "Ágio sobre face",
                "Fórmula": "preço pago / face = 1 - taxa_cessao_efetiva; EAD = carteira_face * preço_pago_face",
                "Observação": "O ágio não é debitado como despesa inicial; ele reduz a taxa efetiva da carteira e aumenta a base de exposição em caso de perda.",
            },
            {
                "Indicador": "Piso de taxa da carteira",
                "Fórmula": "tx_cessao_am_aplicada = max(tx_informada, CDI + spread_SEN + excesso_spread)",
                "Observação": "O spread da SEN é aditivo: ele é somado ao CDI antes de comparar o piso com a taxa informada.",
            },
            {
                "Indicador": "Custo adm/gestão",
                "Fórmula": "max(PL_inicio * ((1 + custo_adm_aa) ^ (1/12) - 1), custo_min)",
                "Observação": "O usuário informa percentual em base 100. Ex.: 0,35 significa 0,35% a.a.; custo mínimo é R$/mês.",
            },
            {
                "Indicador": "Metodologia de crédito",
                "Fórmula": credit_model_label,
                "Observação": "A provisão é ECL-style/prospectiva: a aba separa principal recebido, principal inadimplente, despesa de provisão, estoque NPL 90+, recuperação e write-off para não misturar caixa com estoque.",
            },
            {
                "Indicador": "Carteira vencendo no período",
                "Fórmula": "carteira_inicio * meses_periodo / prazo_medio_recebiveis",
                "Observação": "É a parcela programada para vencer; o principal inadimplente projetado é deduzido do caixa recebido e do reinvestimento.",
            },
            {
                "Indicador": "Principal inadimplente não recebido",
                "Fórmula": "npl90_futuro = carteira_vencendo * perda_ciclo",
                "Observação": "É a parcela do principal vencendo que o motor não trata como caixa. Ela não é reinvestida e, depois do lag, entra em NPL 90+.",
            },
            {
                "Indicador": "Entrada e estoque NPL 90+",
                "Fórmula": "npl90_futuro = carteira_vencendo * perda_ciclo; estoque_npl90_t = max(estoque_t-1 + entrada_npl90_t - baixa_credito_t, 0)",
                "Observação": "Na metodologia NPL 90 + cobertura, a entrada usa a perda de ciclo depois do lag e é baixada imediatamente pelo LGD informado.",
            },
            {
                "Indicador": "Provisão requerida",
                "Fórmula": "max(max(provisao_anterior - baixa_credito, 0) + provisao_prospectiva, estoque_npl90 * cobertura_minima * LGD)",
                "Observação": "A baixa consome provisão já constituída; reforços adicionais só entram quando a provisão prospectiva ou mínima exige.",
            },
            {
                "Indicador": "Despesa de provisão/perda",
                "Fórmula": "writeoff_descoberto + max(provisao_requerida - max(provisao_anterior - baixa_credito, 0), 0)",
                "Observação": "A despesa reduz o PL econômico; a baixa reduz carteira e impede que principal inadimplente seja tratado como principal recebido.",
            },
            {
                "Indicador": "Resultado líquido da carteira",
                "Fórmula": "fluxo_carteira + recuperacao_credito - despesa_provisao",
                "Observação": "A despesa de provisão/perda passa pelo resultado; o write-off coberto pela provisão reduz a carteira, mas não é debitado de novo no PL.",
            },
            {
                "Indicador": "Elegibilidade de reinvestimento",
                "Fórmula": "mês_fidc <= prazo_total_fidc_meses - prazo_medio_recebiveis_meses",
                "Observação": "Quando o prazo médio já não cabe no prazo restante do FIDC, nova originação fica zerada e a carteira entra em runoff.",
            },
            {
                "Indicador": "Nova originação",
                "Fórmula": "se elegível: principal_recebido_líquido + max(fluxo_remanescente_apos_MEZZ, 0); se não elegível: 0",
                "Observação": "Captura reinvestimento do principal reciclado e do excesso de caixa; fora da janela elegível, o principal recebido vai para caixa SELIC.",
            },
            {
                "Indicador": "Juros sênior/MEZZ",
                "Fórmula": "pós: CDI/PreDI + spread aditivo; pré: taxa anual informada",
                "Observação": (
                    "Spread aditivo significa CDI + spread, não percentual do CDI. "
                    f"O FRA de cada período usa base 252 DU. Fonte selecionada: {selected_curve.source_label} "
                    f"({selected_curve.base_date:%d/%m/%Y}); interpolação: {interpolation_label}."
                ),
            },
            {
                "Indicador": "Dias úteis do fluxo",
                "Fórmula": "DU = dias úteis entre a data inicial e a data do fluxo, descontando fins de semana e feriados",
                "Observação": f"Calendário selecionado: {selected_calendar.source_label}.",
            },
            {
                "Indicador": "Proporções de PL",
                "Fórmula": "PL sênior + PL MEZZ + PL SUB = 100%",
                "Observação": "A SUB agora é uma premissa explícita na interface; o motor bloqueia soma diferente de 100%.",
            },
            {
                "Indicador": "Carteira originada programática",
                "Fórmula": "revolvente: volume + volume * max(prazo_total_meses - prazo_medio_meses, 0) / prazo_medio_meses; estática: volume",
                "Observação": "Referência de giro teórico do volume inicial; não é usada como denominador principal quando o motor reinveste excesso de spread.",
            },
            {
                "Indicador": "Carteira originada efetiva",
                "Fórmula": "volume_inicial + soma(nova_originacao_economica_t)",
                "Observação": "Denominador reconciliado com o motor; inclui reinvestimento de principal e de excesso de spread enquanto a revolvência é elegível.",
            },
            {
                "Indicador": "Colchão de proteção no tempo",
                "Fórmula": "SUB disponível no mês / (carteira inicial + nova originação acumulada)",
                "Observação": "A tabela de proteção detalha carteira inicial, nova originação, prazo médio, denominador, SUB e residual do fluxo por mês.",
            },
            {
                "Indicador": "Colchão sem perdas sobre originado",
                "Fórmula": "max(SUB final com perdas 0%, 0) / carteira originada efetiva",
                "Observação": "Esta é uma simulação paralela sem perda de crédito para medir excess spread e colchão econômico antes das perdas, reconciliada com as originações do motor.",
            },
            {
                "Indicador": "Júnior residual / subordinação econômica",
                "Fórmula": "Residual econômico = PL econômico do veículo - PL sênior - PL MEZZ; subordinação disponível = max(residual, 0) / PL positivo",
                "Observação": (
                    "A versão atual não remunera a SUB programaticamente; taxas da SUB ficam como premissa-alvo informativa. "
                    "A timeline preserva a coluna histórica para conferência, mas os gráficos usam o residual corrente."
                ),
            },
        ]
    )
    with st.expander("Memória de cálculo", expanded=False):
        st.dataframe(memory_df, width="stretch", hide_index=True)

    st.markdown('<div class="fidc-model-section-title">Timeline detalhada</div>', unsafe_allow_html=True)
    st.dataframe(display_frame, width="stretch", hide_index=True)

    csv = export_frame.to_csv(index=False).encode("utf-8")
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export_frame.to_excel(writer, index=False, sheet_name="timeline")
        _build_kpi_export_dataframe(kpis).to_excel(writer, index=False, sheet_name="kpis")
        _build_curve_source_dataframe(selected_curve, selected_calendar, interpolation_label).to_excel(
            writer,
            index=False,
            sheet_name="fonte_curva",
        )
        _build_revolvency_export_dataframe(revolvency_metrics).to_excel(
            writer,
            index=False,
            sheet_name="capacidade_perda",
        )
        _build_time_protection_export_dataframe(protection_chart_frame).to_excel(
            writer,
            index=False,
            sheet_name="protecao_tempo",
        )
    download_left, download_right = st.columns(2)
    download_left.download_button(
        "Baixar CSV",
        data=csv,
        file_name="modelo_fidc_timeline.csv",
        mime="text/csv",
        width="stretch",
    )
    download_right.download_button(
        "Baixar Excel",
        data=output.getvalue(),
        file_name="modelo_fidc_resultados.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

    st.markdown('<div class="fidc-model-section-title">Fontes de juros</div>', unsafe_allow_html=True)
    _render_curve_source_controls(inputs, selected_curve, selected_calendar)
    _render_selic_projection_info(selic_aa_por_ano=user_selic_aa_por_ano)

    guide_left, guide_right = st.columns(2)
    with guide_left:
        with st.expander("Passo a passo", expanded=False):
            st.markdown(_build_step_by_step_markdown())
    with guide_right:
        with st.expander("Mecânica completa da aba", expanded=False):
            st.markdown(
                _build_workbook_mechanics_markdown(
                    selected_curve=selected_curve,
                    selected_calendar=selected_calendar,
                    interpolation_label=interpolation_label,
                    taxa_cessao_input_mode=taxa_cessao_input_mode,
                    data_inicial=data_inicial_date,
                    credit_model_label=credit_model_label,
                )
            )
