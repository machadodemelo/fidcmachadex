from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable, Sequence

from .calendar import build_day_counts, build_period_indexes
from .contracts import ModelKpis, PeriodResult, Premissas
from .curves import INTERPOLATION_METHOD_SPLINE, interpolate_curve
from .metrics import calculate_duration_years, lookup_pre_di_duration, xirr


RATE_MODE_POST_CDI = "pos_cdi"
RATE_MODE_PRE = "pre"
AMORTIZATION_MODE_WORKBOOK = "workbook"
AMORTIZATION_MODE_LINEAR = "linear"
AMORTIZATION_MODE_BULLET = "bullet"
AMORTIZATION_MODE_NONE = "none"
INTEREST_PAYMENT_MODE_PERIODIC = "periodic"
INTEREST_PAYMENT_MODE_AFTER_GRACE = "after_grace"
INTEREST_PAYMENT_MODE_BULLET = "bullet"
CREDIT_MODEL_LEGACY_PERCENT = "legacy_percent"
CREDIT_MODEL_NPL90 = "npl90_provision"
CREDIT_MODEL_MIGRATION = "migration_matrix"


def annual_252_to_monthly_rate(rate_aa: float) -> float:
    """Convert an annual effective rate on a 252-business-day basis to 21 DU/month."""

    return (1.0 + rate_aa) ** (21.0 / 252.0) - 1.0


def _annual_252_to_period_rate(rate_aa: float, month_fraction: float) -> float:
    """Convert an annual effective rate to a period using 21 business days per month."""

    return (1.0 + rate_aa) ** ((21.0 * max(month_fraction, 0.0)) / 252.0) - 1.0


def monthly_to_annual_252_rate(rate_am: float) -> float:
    """Convert an effective monthly rate, using 21 DU/month, to annual 252 DU."""

    return (1.0 + rate_am) ** (252.0 / 21.0) - 1.0


def cession_discount_to_monthly_rate(discount_rate: float, term_months: float = 1.0) -> float:
    """Convert a cession discount over face value into the monthly yield used by the model."""

    if discount_rate >= 1.0:
        raise ValueError("Taxa de cessão deve ser menor que 100%.")
    term = max(float(term_months), 0.01)
    return (1.0 / (1.0 - discount_rate)) ** (1.0 / term) - 1.0


def monthly_rate_to_cession_discount(rate_am: float, term_months: float = 1.0) -> float:
    """Convert a monthly yield into the equivalent cession discount over face value."""

    if rate_am <= -1.0:
        raise ValueError("Taxa mensal deve ser maior que -100%.")
    term = max(float(term_months), 0.01)
    return 1.0 - (1.0 / (1.0 + rate_am) ** term)


def _price_paid_factor_from_monthly_rate(rate_am: float, term_months: float) -> float:
    """Return paid price / face implied by the effective monthly portfolio yield."""

    effective_discount = monthly_rate_to_cession_discount(rate_am, term_months)
    return max(1.0 - effective_discount, 0.0)


def _ead_factor_for_premissas(premissas: Premissas, rate_am: float, term_months: float) -> float:
    if premissas.agio_aquisicao <= 0.0:
        return 1.0
    return _price_paid_factor_from_monthly_rate(rate_am, term_months)


def _cession_floor_monthly_rate(senior_annual_rate: float, excess_spread_am: float) -> float:
    excess_annual_rate = monthly_to_annual_252_rate(max(excess_spread_am, 0.0))
    floor_annual_rate = max(senior_annual_rate, -0.999999) + excess_annual_rate
    return annual_252_to_monthly_rate(floor_annual_rate)


def _class_annual_rate(base_rate: float, class_rate: float, mode: str) -> float:
    if mode == RATE_MODE_PRE:
        return class_rate
    if mode == RATE_MODE_POST_CDI:
        return base_rate + class_rate
    raise ValueError(f"Tipo de taxa de cota inválido: {mode}")


def _admin_cost_period_amount(pl_start: float, cost_aa: float, cost_min_monthly: float) -> float:
    monthly_cost_rate = (1.0 + max(float(cost_aa), -0.999999)) ** (1.0 / 12.0) - 1.0
    return max(max(float(pl_start), 0.0) * monthly_cost_rate, float(cost_min_monthly))


def _months_between(start: datetime, current: datetime) -> int:
    return (current.year - start.year) * 12 + (current.month - start.month)


def _term_months(term_years: float | None, fallback_months: int) -> int:
    if term_years is None:
        return fallback_months
    return max(1, round(float(term_years) * 12.0))


def _principal_schedule(
    datas: Sequence[datetime],
    initial_pl: float,
    *,
    mode: str = AMORTIZATION_MODE_WORKBOOK,
    start_month: int = 25,
    term_months: int | None = None,
) -> list[float]:
    period_count = len(datas)
    schedule = [0.0] * period_count
    if period_count:
        schedule[0] = -initial_pl
    if period_count <= 1 or initial_pl <= 0:
        return schedule

    if mode == AMORTIZATION_MODE_NONE:
        return schedule

    month_deltas = [_months_between(datas[0], dt) for dt in datas]
    last_month = month_deltas[-1]
    final_month = term_months if term_months is not None else last_month

    if mode == AMORTIZATION_MODE_WORKBOOK:
        remaining = initial_pl
        workbook_indexes = [index for index, month_delta in enumerate(month_deltas) if index > 0 and month_delta > 24]
        for index in workbook_indexes[:12]:
            amount = min(initial_pl / 12.0, remaining)
            schedule[index] = amount
            remaining -= amount
            if remaining <= 1e-9:
                break
        return schedule

    if mode == AMORTIZATION_MODE_BULLET:
        payment_index = _first_index_at_or_after(month_deltas, final_month)
        schedule[payment_index] = initial_pl
        return schedule

    if mode == AMORTIZATION_MODE_LINEAR:
        eligible_indexes = [
            index
            for index, month_delta in enumerate(month_deltas)
            if index > 0 and month_delta > start_month and month_delta <= final_month
        ]
        if not eligible_indexes:
            eligible_indexes = [_first_index_at_or_after(month_deltas, min(start_month, final_month))]
        amount = initial_pl / len(eligible_indexes)
        for index in eligible_indexes:
            schedule[index] = amount
        return schedule

    raise ValueError(f"Modo de amortização inválido: {mode}")


def _first_index_at_or_after(month_deltas: Sequence[int], target_month: int) -> int:
    for index, month_delta in enumerate(month_deltas):
        if index > 0 and month_delta >= target_month:
            return index
    return len(month_deltas) - 1


def _interest_payment(
    interest: float,
    accrued_interest: float,
    *,
    mode: str,
    month_delta: int,
    start_month: int,
    term_month: int,
    is_last_period: bool,
) -> tuple[float, float]:
    if mode == INTEREST_PAYMENT_MODE_PERIODIC:
        return interest, accrued_interest
    if mode == INTEREST_PAYMENT_MODE_AFTER_GRACE:
        if month_delta < start_month and not is_last_period:
            return 0.0, accrued_interest + interest
        return accrued_interest + interest, 0.0
    if mode == INTEREST_PAYMENT_MODE_BULLET:
        if month_delta >= term_month or is_last_period:
            return accrued_interest + interest, 0.0
        return 0.0, accrued_interest + interest
    raise ValueError(f"Modo de pagamento de juros inválido: {mode}")


def _credit_loss_expenses(carteira: float, premissas: Premissas, delta_dc: int) -> tuple[float, float, float]:
    if premissas.perda_esperada_am is None and premissas.perda_inesperada_am is None:
        total = carteira * (premissas.inadimplencia * (delta_dc / 100.0))
        return total, 0.0, total

    month_fraction = delta_dc / 30.0
    expected_loss = carteira * float(premissas.perda_esperada_am or 0.0) * month_fraction
    unexpected_loss = carteira * float(premissas.perda_inesperada_am or 0.0) * month_fraction
    return expected_loss, unexpected_loss, expected_loss + unexpected_loss


@dataclass
class _CreditState:
    provisao_saldo: float = 0.0
    npl90_estoque: float = 0.0
    npl90_pipeline: list[tuple[float, float]] | None = None
    bucket_1_30: float = 0.0
    bucket_31_60: float = 0.0
    bucket_61_90: float = 0.0
    bucket_90_plus: float = 0.0

    def __post_init__(self) -> None:
        if self.npl90_pipeline is None:
            self.npl90_pipeline = []


@dataclass(frozen=True)
class _CreditPeriod:
    perda_esperada_despesa: float
    perda_inesperada_despesa: float
    perda_carteira_despesa: float
    carteira_vencendo: float
    principal_inadimplente: float
    entrada_npl90: float
    npl90_estoque_inicio: float
    npl90_estoque_fim: float
    provisao_saldo_inicio: float
    provisao_requerida: float
    despesa_provisao: float
    provisao_saldo_fim: float
    cobertura_npl90: float | None
    baixa_credito: float
    writeoff_descoberto: float
    recuperacao_credito: float
    bucket_adimplente: float
    bucket_1_30: float
    bucket_31_60: float
    bucket_61_90: float
    bucket_90_plus: float


def _scale_period_probability(monthly_probability: float, period_months: float) -> float:
    probability = min(max(monthly_probability, 0.0), 1.0)
    if period_months <= 0.0:
        return 0.0
    return min(1.0 - (1.0 - probability) ** period_months, 1.0)


def _age_npl90_pipeline(state: _CreditState, period_months: float) -> float:
    matured = 0.0
    remaining_pipeline: list[tuple[float, float]] = []
    for remaining_months, amount in state.npl90_pipeline or []:
        remaining_after_period = remaining_months - period_months
        if remaining_after_period <= 1e-9:
            matured += amount
        else:
            remaining_pipeline.append((remaining_after_period, amount))
    state.npl90_pipeline = remaining_pipeline
    return matured


def _legacy_credit_period(carteira: float, premissas: Premissas, delta_dc: int) -> _CreditPeriod:
    expected_loss, unexpected_loss, total_loss = _credit_loss_expenses(carteira, premissas, delta_dc)
    return _CreditPeriod(
        perda_esperada_despesa=expected_loss,
        perda_inesperada_despesa=unexpected_loss,
        perda_carteira_despesa=total_loss,
        carteira_vencendo=0.0,
        principal_inadimplente=0.0,
        entrada_npl90=0.0,
        npl90_estoque_inicio=0.0,
        npl90_estoque_fim=0.0,
        provisao_saldo_inicio=0.0,
        provisao_requerida=0.0,
        despesa_provisao=0.0,
        provisao_saldo_fim=0.0,
        cobertura_npl90=None,
        baixa_credito=total_loss,
        writeoff_descoberto=total_loss,
        recuperacao_credito=0.0,
        bucket_adimplente=max(carteira, 0.0),
        bucket_1_30=0.0,
        bucket_31_60=0.0,
        bucket_61_90=0.0,
        bucket_90_plus=0.0,
    )


def _npl90_credit_period(
    *,
    carteira: float,
    carteira_vencendo: float,
    premissas: Premissas,
    period_months: float,
    state: _CreditState,
) -> _CreditPeriod:
    npl90_start = state.npl90_estoque
    provisao_start = state.provisao_saldo
    entrada_npl90 = _age_npl90_pipeline(state, period_months)
    perda_ciclo = max(float(premissas.perda_ciclo), 0.0)
    lgd = min(max(float(premissas.lgd), 0.0), 1.0)
    cobertura_minima = max(float(premissas.cobertura_minima_npl90), 0.0)
    npl90_futuro = max(carteira_vencendo, 0.0) * perda_ciclo
    lag = max(float(premissas.npl90_lag_meses), 0.0)
    if npl90_futuro > 0.0:
        if lag <= 1e-9:
            entrada_npl90 += npl90_futuro
        else:
            assert state.npl90_pipeline is not None
            state.npl90_pipeline.append((lag, npl90_futuro))

    npl90_end = npl90_start + entrada_npl90
    writeoff_loss = entrada_npl90 * lgd
    provisao_after_writeoff = max(provisao_start - writeoff_loss, 0.0)
    uncovered_writeoff = max(writeoff_loss - provisao_start, 0.0)
    npl90_end = max(npl90_end - writeoff_loss, 0.0)
    provisao_base = npl90_futuro * lgd
    provisao_minima = npl90_end * cobertura_minima * lgd
    provisao_requerida = max(provisao_after_writeoff + provisao_base, provisao_minima)
    despesa_provisao = uncovered_writeoff + max(provisao_requerida - provisao_after_writeoff, 0.0)
    reforco_cobertura = max(despesa_provisao - provisao_base - uncovered_writeoff, 0.0)
    cobertura_npl90 = provisao_requerida / (npl90_end * lgd) if npl90_end > 0.0 and lgd > 0.0 else None

    state.provisao_saldo = provisao_requerida
    state.npl90_estoque = npl90_end

    return _CreditPeriod(
        perda_esperada_despesa=provisao_base,
        perda_inesperada_despesa=reforco_cobertura,
        perda_carteira_despesa=despesa_provisao,
        carteira_vencendo=carteira_vencendo,
        principal_inadimplente=npl90_futuro,
        entrada_npl90=entrada_npl90,
        npl90_estoque_inicio=npl90_start,
        npl90_estoque_fim=npl90_end,
        provisao_saldo_inicio=provisao_start,
        provisao_requerida=provisao_requerida,
        despesa_provisao=despesa_provisao,
        provisao_saldo_fim=provisao_requerida,
        cobertura_npl90=cobertura_npl90,
        baixa_credito=writeoff_loss,
        writeoff_descoberto=uncovered_writeoff,
        recuperacao_credito=0.0,
        bucket_adimplente=max(carteira - npl90_end - writeoff_loss, 0.0),
        bucket_1_30=0.0,
        bucket_31_60=0.0,
        bucket_61_90=0.0,
        bucket_90_plus=npl90_end,
    )


def _migration_credit_period(
    *,
    carteira: float,
    carteira_vencendo: float,
    premissas: Premissas,
    period_months: float,
    state: _CreditState,
) -> _CreditPeriod:
    total_buckets = state.bucket_1_30 + state.bucket_31_60 + state.bucket_61_90 + state.bucket_90_plus
    if total_buckets > carteira and total_buckets > 0.0:
        scale = carteira / total_buckets
        state.bucket_1_30 *= scale
        state.bucket_31_60 *= scale
        state.bucket_61_90 *= scale
        state.bucket_90_plus *= scale

    current_start = max(carteira - state.bucket_1_30 - state.bucket_31_60 - state.bucket_61_90 - state.bucket_90_plus, 0.0)
    bucket_1_30_start = state.bucket_1_30
    bucket_31_60_start = state.bucket_31_60
    bucket_61_90_start = state.bucket_61_90
    bucket_90_start = state.bucket_90_plus
    provisao_start = state.provisao_saldo

    roll_current = _scale_period_probability(premissas.rolagem_adimplente_1_30, period_months)
    roll_1_30 = _scale_period_probability(premissas.rolagem_1_30_31_60, period_months)
    roll_31_60 = _scale_period_probability(premissas.rolagem_31_60_61_90, period_months)
    roll_61_90 = _scale_period_probability(premissas.rolagem_61_90_90_plus, period_months)
    recovery_rate = _scale_period_probability(premissas.recuperacao_90_plus, period_months)
    writeoff_rate = _scale_period_probability(premissas.writeoff_90_plus, period_months)

    to_1_30 = current_start * roll_current
    to_31_60 = bucket_1_30_start * roll_1_30
    to_61_90 = bucket_31_60_start * roll_31_60
    to_90_plus = bucket_61_90_start * roll_61_90
    recovered = bucket_90_start * recovery_rate
    writeoff = max(bucket_90_start - recovered, 0.0) * writeoff_rate

    bucket_1_30_end = max(bucket_1_30_start + to_1_30 - to_31_60, 0.0)
    bucket_31_60_end = max(bucket_31_60_start + to_31_60 - to_61_90, 0.0)
    bucket_61_90_end = max(bucket_61_90_start + to_61_90 - to_90_plus, 0.0)
    bucket_90_end = max(bucket_90_start + to_90_plus - recovered - writeoff, 0.0)
    current_end = max(carteira - bucket_1_30_end - bucket_31_60_end - bucket_61_90_end - bucket_90_end, 0.0)

    lgd = min(max(float(premissas.lgd), 0.0), 1.0)
    cobertura_minima = max(float(premissas.cobertura_minima_npl90), 0.0)
    writeoff_loss = writeoff * lgd
    provisao_after_writeoff = max(provisao_start - writeoff_loss, 0.0)
    uncovered_writeoff = max(writeoff_loss - provisao_start, 0.0)
    provisao_base = to_90_plus * lgd
    provisao_minima = bucket_90_end * cobertura_minima * lgd
    provisao_requerida = max(provisao_after_writeoff + provisao_base, provisao_minima)
    despesa_provisao = uncovered_writeoff + max(provisao_requerida - provisao_after_writeoff, 0.0)
    reforco_cobertura = max(despesa_provisao - provisao_base - uncovered_writeoff, 0.0)
    cobertura_npl90 = provisao_requerida / (bucket_90_end * lgd) if bucket_90_end > 0.0 and lgd > 0.0 else None

    state.provisao_saldo = provisao_requerida
    state.npl90_estoque = bucket_90_end
    state.bucket_1_30 = bucket_1_30_end
    state.bucket_31_60 = bucket_31_60_end
    state.bucket_61_90 = bucket_61_90_end
    state.bucket_90_plus = bucket_90_end

    return _CreditPeriod(
        perda_esperada_despesa=provisao_base,
        perda_inesperada_despesa=reforco_cobertura + uncovered_writeoff,
        perda_carteira_despesa=despesa_provisao,
        carteira_vencendo=carteira_vencendo,
        principal_inadimplente=0.0,
        entrada_npl90=to_90_plus,
        npl90_estoque_inicio=bucket_90_start,
        npl90_estoque_fim=bucket_90_end,
        provisao_saldo_inicio=provisao_start,
        provisao_requerida=provisao_requerida,
        despesa_provisao=despesa_provisao,
        provisao_saldo_fim=provisao_requerida,
        cobertura_npl90=cobertura_npl90,
        baixa_credito=writeoff,
        writeoff_descoberto=uncovered_writeoff,
        recuperacao_credito=recovered,
        bucket_adimplente=current_end,
        bucket_1_30=bucket_1_30_end,
        bucket_31_60=bucket_31_60_end,
        bucket_61_90=bucket_61_90_end,
        bucket_90_plus=bucket_90_end,
    )


def _credit_period(
    *,
    carteira: float,
    carteira_vencendo: float,
    premissas: Premissas,
    delta_dc: int,
    period_months: float,
    state: _CreditState,
) -> _CreditPeriod:
    if premissas.modelo_credito == CREDIT_MODEL_LEGACY_PERCENT:
        return _legacy_credit_period(carteira, premissas, delta_dc)
    if premissas.modelo_credito == CREDIT_MODEL_NPL90:
        return _npl90_credit_period(
            carteira=carteira,
            carteira_vencendo=carteira_vencendo,
            premissas=premissas,
            period_months=period_months,
            state=state,
        )
    if premissas.modelo_credito == CREDIT_MODEL_MIGRATION:
        return _migration_credit_period(
            carteira=carteira,
            carteira_vencendo=carteira_vencendo,
            premissas=premissas,
            period_months=period_months,
            state=state,
        )
    raise ValueError(f"Modelo de crédito inválido: {premissas.modelo_credito}")


def _selic_annual_rate_for_year(premissas: Premissas, year: int) -> float:
    projection = dict(premissas.selic_aa_por_ano)
    if not projection:
        return 0.0
    first_year = min(projection)
    if year < first_year:
        return max(float(projection[first_year]), -0.999999)
    if year not in projection:
        previous_years = [projection_year for projection_year in projection if projection_year <= year]
        if not previous_years:
            return max(float(projection[first_year]), -0.999999)
        return max(float(projection[max(previous_years)]), -0.999999)
    return max(float(projection[year]), -0.999999)


def _period_month_fraction(month_deltas: Sequence[int], index: int, delta_dc: int) -> float:
    if index > 0:
        delta_months = month_deltas[index] - month_deltas[index - 1]
        if delta_months > 0:
            return float(delta_months)
    return max(float(delta_dc) / 30.0, 0.0)


def _reinvestment_cutoff_month(premissas: Premissas, fallback_term_months: int) -> float:
    term_months = _term_months(premissas.prazo_fidc_anos, fallback_term_months)
    prazo_medio = max(float(premissas.prazo_medio_recebiveis_meses), 0.01)
    return max(float(term_months) - prazo_medio, 0.0)


def _is_reinvestment_eligible(premissas: Premissas, month_delta: int, fallback_term_months: int) -> bool:
    if not premissas.carteira_revolvente:
        return False
    return float(month_delta) <= _reinvestment_cutoff_month(premissas, fallback_term_months)


def _period_indexes_for_dates(datas: Sequence[datetime]) -> list[int]:
    month_deltas = [_months_between(datas[0], dt) for dt in datas]
    workbook_prefix = [0, 6, 12, 18, 24]
    if len(month_deltas) >= len(workbook_prefix) and month_deltas[: len(workbook_prefix)] == workbook_prefix:
        return build_period_indexes(len(datas))
    return month_deltas


def build_flow(
    datas: Sequence[datetime],
    feriados: Iterable[datetime],
    curva_du: Sequence[float],
    curva_cdi: Sequence[float],
    premissas: Premissas,
    interpolation_method: str = INTERPOLATION_METHOD_SPLINE,
) -> list[PeriodResult]:
    if not datas:
        return []
    if not curva_du or not curva_cdi:
        raise ValueError("Curva DI/Pre vazia: o modelo exige uma curva válida da fonte selecionada.")

    period_indexes = _period_indexes_for_dates(datas)
    dc, du = build_day_counts(datas, feriados)
    month_deltas = [_months_between(datas[0], dt) for dt in datas]

    zero_pre_di: list[float | None] = [None]
    for du_value in du[1:]:
        zero_pre_di.append(interpolate_curve(float(du_value), curva_du, curva_cdi, method=interpolation_method))

    taxa_senior: list[float | None] = [None]
    taxa_mezz: list[float | None] = [None]
    for index in range(1, len(datas)):
        base_rate = zero_pre_di[index]
        assert base_rate is not None
        taxa_senior.append(_class_annual_rate(base_rate, premissas.taxa_senior, premissas.tipo_taxa_senior))
        taxa_mezz.append(_class_annual_rate(base_rate, premissas.taxa_mezz, premissas.tipo_taxa_mezz))

    fra_senior: list[float | None] = [None]
    fra_mezz: list[float | None] = [None]
    for index in range(1, len(datas)):
        if index == 1:
            fra_senior.append(taxa_senior[index])
            fra_mezz.append(taxa_mezz[index])
            continue
        if du[index] == du[index - 1]:
            fra_senior.append(taxa_senior[index])
            fra_mezz.append(taxa_mezz[index])
            continue
        current_senior = taxa_senior[index]
        previous_senior = taxa_senior[index - 1]
        current_mezz = taxa_mezz[index]
        previous_mezz = taxa_mezz[index - 1]
        if previous_senior is None or previous_mezz is None or current_senior is None or current_mezz is None:
            fra_senior.append(None)
            fra_mezz.append(None)
            continue
        fra_senior.append(
            ((1.0 + current_senior) ** (du[index] / 252.0) / (1.0 + previous_senior) ** (du[index - 1] / 252.0))
            ** (252.0 / (du[index] - du[index - 1]))
            - 1.0
        )
        fra_mezz.append(
            ((1.0 + current_mezz) ** (du[index] / 252.0) / (1.0 + previous_mezz) ** (du[index - 1] / 252.0))
            ** (252.0 / (du[index] - du[index - 1]))
            - 1.0
        )

    agio_aquisicao_despesa = max(premissas.volume * max(premissas.agio_aquisicao, 0.0), 0.0)
    pl_senior_initial = premissas.volume * premissas.proporcao_senior
    pl_mezz_initial = premissas.volume * premissas.proporcao_mezz
    if premissas.proporcao_subordinada is None:
        pl_sub_initial = premissas.volume - pl_senior_initial - pl_mezz_initial
    else:
        pl_sub_initial = premissas.volume * premissas.proporcao_subordinada

    fallback_term_months = month_deltas[-1] if month_deltas else 0
    senior_term_months = _term_months(premissas.prazo_senior_anos or premissas.prazo_fidc_anos, fallback_term_months)
    mezz_term_months = _term_months(premissas.prazo_mezz_anos or premissas.prazo_fidc_anos, fallback_term_months)
    principal_senior = _principal_schedule(
        datas,
        pl_senior_initial,
        mode=premissas.amortizacao_senior,
        start_month=premissas.inicio_amortizacao_senior_meses,
        term_months=senior_term_months,
    )
    principal_mezz = _principal_schedule(
        datas,
        pl_mezz_initial,
        mode=premissas.amortizacao_mezz,
        start_month=premissas.inicio_amortizacao_mezz_meses,
        term_months=mezz_term_months,
    )

    periods: list[PeriodResult] = []
    pl_senior_atual = pl_senior_initial
    pl_mezz_atual = pl_mezz_initial
    pl_fidc_atual = premissas.volume
    pl_sub_jr_initial = pl_fidc_atual - pl_senior_atual - pl_mezz_atual
    carteira_atual = premissas.volume
    caixa_selic_atual = 0.0
    accrued_interest_senior = 0.0
    accrued_interest_mezz = 0.0
    credit_state = _CreditState()

    for index, dt in enumerate(datas):
        if index == 0:
            periods.append(
                PeriodResult(
                    indice=period_indexes[index],
                    data=dt,
                    dc=dc[index],
                    du=du[index],
                    delta_dc=0,
                    delta_du=0,
                    pre_di=None,
                    taxa_senior=None,
                    fra_senior=None,
                    taxa_mezz=None,
                    fra_mezz=None,
                    carteira=premissas.volume,
                    ead_carteira=premissas.volume
                    * _ead_factor_for_premissas(
                        premissas,
                        premissas.tx_cessao_am,
                        max(float(premissas.prazo_medio_recebiveis_meses), 0.01),
                    ),
                    fluxo_carteira=0.0,
                    taxa_selic_aa=None,
                    taxa_selic_periodo=0.0,
                    saldo_caixa_selic_inicio=0.0,
                    principal_para_caixa_selic=0.0,
                    rendimento_caixa_selic=0.0,
                    fluxo_ativos_total=0.0,
                    pl_fidc=pl_fidc_atual,
                    custos_adm=0.0,
                    inadimplencia_despesa=0.0,
                    perda_esperada_despesa=0.0,
                    perda_inesperada_despesa=0.0,
                    perda_carteira_despesa=0.0,
                    carteira_vencendo=0.0,
                    ead_vencendo=0.0,
                    principal_inadimplente=0.0,
                    entrada_npl90=0.0,
                    npl90_estoque_inicio=0.0,
                    npl90_estoque_fim=0.0,
                    provisao_saldo_inicio=0.0,
                    provisao_requerida=0.0,
                    despesa_provisao=0.0,
                    provisao_saldo_fim=0.0,
                    cobertura_npl90=None,
                    baixa_credito=0.0,
                    writeoff_descoberto=0.0,
                    recuperacao_credito=0.0,
                    bucket_adimplente=premissas.volume,
                    bucket_1_30=0.0,
                    bucket_31_60=0.0,
                    bucket_61_90=0.0,
                    bucket_90_plus=0.0,
                    resultado_carteira_liquido=0.0,
                    prazo_restante_reinvestimento_meses=float(_term_months(premissas.prazo_fidc_anos, fallback_term_months)),
                    reinvestimento_elegivel=premissas.carteira_revolvente,
                    principal_recebido_carteira=0.0,
                    reinvestimento_principal=0.0,
                    reinvestimento_excesso=0.0,
                    nova_originacao=0.0,
                    carteira_fim=carteira_atual,
                    caixa_nao_reinvestido=0.0,
                    saldo_caixa_selic_fim=0.0,
                    agio_aquisicao_despesa=agio_aquisicao_despesa,
                    preco_pago_fator=_ead_factor_for_premissas(
                        premissas,
                        premissas.tx_cessao_am,
                        max(float(premissas.prazo_medio_recebiveis_meses), 0.01),
                    ),
                    tx_cessao_am_input=premissas.tx_cessao_am,
                    tx_cessao_am_piso=0.0,
                    tx_cessao_am_aplicada=premissas.tx_cessao_am,
                    principal_senior=principal_senior[index],
                    juros_senior=0.0,
                    pmt_senior=principal_senior[index],
                    vp_pmt_senior=0.0,
                    pl_senior=pl_senior_atual,
                    fluxo_remanescente=0.0,
                    principal_mezz=principal_mezz[index],
                    juros_mezz=0.0,
                    pmt_mezz=principal_mezz[index],
                    pl_mezz=pl_mezz_atual,
                    fluxo_remanescente_mezz=0.0,
                    principal_sub_jr=0.0,
                    juros_sub_jr=0.0,
                    pmt_sub_jr=0.0,
                    pl_sub_jr=pl_sub_jr_initial,
                    subordinacao_pct=pl_sub_jr_initial / pl_fidc_atual if pl_fidc_atual else None,
                    pl_sub_jr_modelo=None,
                    subordinacao_pct_modelo=None,
                )
            )
            continue

        delta_du = du[index] - du[index - 1]
        delta_dc = dc[index] - dc[index - 1]
        carteira = max(carteira_atual if premissas.carteira_revolvente else pl_fidc_atual, 0.0)
        fra_senior_period = fra_senior[index] or 0.0
        tx_cessao_am_piso = _cession_floor_monthly_rate(
            fra_senior_period,
            premissas.excesso_spread_senior_am,
        )
        tx_cessao_am_aplicada = max(premissas.tx_cessao_am, tx_cessao_am_piso)
        period_months = _period_month_fraction(month_deltas, index, delta_dc)
        prazo_medio_recebiveis = max(float(premissas.prazo_medio_recebiveis_meses), 0.01)
        preco_pago_fator = _ead_factor_for_premissas(premissas, tx_cessao_am_aplicada, prazo_medio_recebiveis)
        ead_carteira = carteira * preco_pago_fator
        principal_programado_carteira = min(carteira, max(carteira * period_months / prazo_medio_recebiveis, 0.0))
        ead_vencendo = principal_programado_carteira * preco_pago_fator
        prazo_restante_reinvestimento = max(
            float(_term_months(premissas.prazo_fidc_anos, fallback_term_months) - month_deltas[index]),
            0.0,
        )
        reinvestimento_elegivel = _is_reinvestment_eligible(premissas, month_deltas[index], fallback_term_months)
        fluxo_carteira = carteira * ((1.0 + tx_cessao_am_aplicada) ** (delta_du / 21.0) - 1.0)
        custos_adm = _admin_cost_period_amount(pl_fidc_atual, premissas.custo_adm_aa, premissas.custo_min)
        credit = _credit_period(
            carteira=ead_carteira,
            carteira_vencendo=ead_vencendo,
            premissas=premissas,
            delta_dc=delta_dc,
            period_months=period_months,
            state=credit_state,
        )
        principal_inadimplente_face = (
            credit.principal_inadimplente / preco_pago_fator if preco_pago_fator > 1e-12 else credit.principal_inadimplente
        )
        principal_recebido_carteira = max(principal_programado_carteira - principal_inadimplente_face, 0.0)
        reinvestimento_principal = principal_recebido_carteira if reinvestimento_elegivel else 0.0
        principal_para_caixa_selic = max(principal_recebido_carteira - reinvestimento_principal, 0.0)
        taxa_selic_aa = _selic_annual_rate_for_year(premissas, dt.year)
        taxa_selic_periodo = _annual_252_to_period_rate(taxa_selic_aa, period_months)
        saldo_caixa_selic_inicio = caixa_selic_atual
        rendimento_caixa_selic = (saldo_caixa_selic_inicio + principal_para_caixa_selic) * taxa_selic_periodo
        fluxo_ativos_total = fluxo_carteira + rendimento_caixa_selic + credit.recuperacao_credito
        perda_esperada_despesa = credit.perda_esperada_despesa
        perda_inesperada_despesa = credit.perda_inesperada_despesa
        perda_carteira_despesa = credit.perda_carteira_despesa
        inadimplencia_despesa = perda_carteira_despesa
        resultado_carteira_liquido = fluxo_carteira + credit.recuperacao_credito - perda_carteira_despesa

        fra_mezz_period = fra_mezz[index] or 0.0
        juros_senior_bruto = pl_senior_atual * ((1.0 + fra_senior_period) ** (delta_du / 252.0) - 1.0)
        juros_mezz_bruto = pl_mezz_atual * ((1.0 + fra_mezz_period) ** (delta_du / 252.0) - 1.0)
        juros_senior, accrued_interest_senior = _interest_payment(
            juros_senior_bruto,
            accrued_interest_senior,
            mode=premissas.juros_senior,
            month_delta=month_deltas[index],
            start_month=premissas.inicio_amortizacao_senior_meses,
            term_month=senior_term_months,
            is_last_period=index == len(datas) - 1,
        )
        juros_mezz, accrued_interest_mezz = _interest_payment(
            juros_mezz_bruto,
            accrued_interest_mezz,
            mode=premissas.juros_mezz,
            month_delta=month_deltas[index],
            start_month=premissas.inicio_amortizacao_mezz_meses,
            term_month=mezz_term_months,
            is_last_period=index == len(datas) - 1,
        )

        principal_senior_period = max(principal_senior[index], 0.0)
        principal_mezz_period = max(principal_mezz[index], 0.0)
        pmt_senior = juros_senior + principal_senior_period
        pmt_mezz = juros_mezz + principal_mezz_period

        pl_senior_atual -= principal_senior_period
        pl_mezz_atual -= principal_mezz_period

        fluxo_remanescente = fluxo_ativos_total - custos_adm - inadimplencia_despesa - pmt_senior
        fluxo_remanescente_mezz = fluxo_remanescente - pmt_mezz
        pl_fidc_atual = pl_fidc_atual + fluxo_ativos_total - custos_adm - inadimplencia_despesa - pmt_senior - pmt_mezz
        pl_sub_jr = pl_fidc_atual - pl_senior_atual - pl_mezz_atual
        reinvestimento_excesso = max(fluxo_remanescente_mezz, 0.0) if reinvestimento_elegivel else 0.0
        nova_originacao = reinvestimento_principal + reinvestimento_excesso
        baixa_credito_face = credit.baixa_credito / preco_pago_fator if preco_pago_fator > 1e-12 else credit.baixa_credito
        carteira_fim = max(carteira - principal_recebido_carteira - baixa_credito_face + nova_originacao, 0.0)
        caixa_nao_reinvestido = (
            principal_para_caixa_selic
            + max(max(fluxo_remanescente_mezz, 0.0) - reinvestimento_excesso, 0.0)
        )
        saldo_caixa_selic_fim = max(
            saldo_caixa_selic_inicio + principal_para_caixa_selic + fluxo_remanescente_mezz - reinvestimento_excesso,
            0.0,
        )
        carteira_atual = carteira_fim
        caixa_selic_atual = saldo_caixa_selic_fim

        taxa_senior_period = taxa_senior[index]
        vp_pmt_senior = 0.0
        if taxa_senior_period is not None:
            vp_pmt_senior = pmt_senior / ((1.0 + taxa_senior_period) ** (du[index] / 252.0))

        periods.append(
            PeriodResult(
                indice=period_indexes[index],
                data=dt,
                dc=dc[index],
                du=du[index],
                delta_dc=delta_dc,
                delta_du=delta_du,
                pre_di=zero_pre_di[index],
                taxa_senior=taxa_senior[index],
                fra_senior=fra_senior[index],
                taxa_mezz=taxa_mezz[index],
                fra_mezz=fra_mezz[index],
                carteira=carteira,
                ead_carteira=ead_carteira,
                fluxo_carteira=fluxo_carteira,
                taxa_selic_aa=taxa_selic_aa,
                taxa_selic_periodo=taxa_selic_periodo,
                saldo_caixa_selic_inicio=saldo_caixa_selic_inicio,
                principal_para_caixa_selic=principal_para_caixa_selic,
                rendimento_caixa_selic=rendimento_caixa_selic,
                fluxo_ativos_total=fluxo_ativos_total,
                pl_fidc=pl_fidc_atual,
                custos_adm=custos_adm,
                inadimplencia_despesa=inadimplencia_despesa,
                perda_esperada_despesa=perda_esperada_despesa,
                perda_inesperada_despesa=perda_inesperada_despesa,
                perda_carteira_despesa=perda_carteira_despesa,
                carteira_vencendo=credit.carteira_vencendo,
                ead_vencendo=ead_vencendo,
                principal_inadimplente=credit.principal_inadimplente,
                entrada_npl90=credit.entrada_npl90,
                npl90_estoque_inicio=credit.npl90_estoque_inicio,
                npl90_estoque_fim=credit.npl90_estoque_fim,
                provisao_saldo_inicio=credit.provisao_saldo_inicio,
                provisao_requerida=credit.provisao_requerida,
                despesa_provisao=credit.despesa_provisao,
                provisao_saldo_fim=credit.provisao_saldo_fim,
                cobertura_npl90=credit.cobertura_npl90,
                baixa_credito=credit.baixa_credito,
                writeoff_descoberto=credit.writeoff_descoberto,
                recuperacao_credito=credit.recuperacao_credito,
                bucket_adimplente=credit.bucket_adimplente,
                bucket_1_30=credit.bucket_1_30,
                bucket_31_60=credit.bucket_31_60,
                bucket_61_90=credit.bucket_61_90,
                bucket_90_plus=credit.bucket_90_plus,
                resultado_carteira_liquido=resultado_carteira_liquido,
                prazo_restante_reinvestimento_meses=prazo_restante_reinvestimento,
                reinvestimento_elegivel=reinvestimento_elegivel,
                principal_recebido_carteira=principal_recebido_carteira,
                reinvestimento_principal=reinvestimento_principal,
                reinvestimento_excesso=reinvestimento_excesso,
                nova_originacao=nova_originacao,
                carteira_fim=carteira_fim,
                caixa_nao_reinvestido=caixa_nao_reinvestido,
                saldo_caixa_selic_fim=saldo_caixa_selic_fim,
                agio_aquisicao_despesa=0.0,
                preco_pago_fator=preco_pago_fator,
                tx_cessao_am_input=premissas.tx_cessao_am,
                tx_cessao_am_piso=tx_cessao_am_piso,
                tx_cessao_am_aplicada=tx_cessao_am_aplicada,
                principal_senior=principal_senior_period,
                juros_senior=juros_senior,
                pmt_senior=pmt_senior,
                vp_pmt_senior=vp_pmt_senior,
                pl_senior=pl_senior_atual,
                fluxo_remanescente=fluxo_remanescente,
                principal_mezz=principal_mezz_period,
                juros_mezz=juros_mezz,
                pmt_mezz=pmt_mezz,
                pl_mezz=pl_mezz_atual,
                fluxo_remanescente_mezz=fluxo_remanescente_mezz,
                principal_sub_jr=0.0,
                juros_sub_jr=0.0,
                pmt_sub_jr=0.0,
                pl_sub_jr=pl_sub_jr,
                subordinacao_pct=(pl_sub_jr / pl_fidc_atual) if pl_fidc_atual else None,
                pl_sub_jr_modelo=None,
                subordinacao_pct_modelo=None,
            )
        )

    residual_modelo: list[float | None] = [None] * len(periods)
    for index, period in enumerate(periods):
        if index == 0:
            residual_modelo[index] = None
            continue
        if index == 1:
            residual_modelo[index] = period.pl_sub_jr
            continue
        if index == len(periods) - 1:
            residual_modelo[index] = 0.0
            continue
        residual_modelo[index] = periods[index + 1].pl_sub_jr

    periodos_ajustados: list[PeriodResult] = []
    for index, period in enumerate(periods):
        residual_exibido = residual_modelo[index]
        subordinacao_modelo = None
        if residual_exibido is not None and period.pl_fidc:
            subordinacao_modelo = residual_exibido / period.pl_fidc
        periodos_ajustados.append(
            replace(
                period,
                pl_sub_jr_modelo=residual_exibido,
                subordinacao_pct_modelo=subordinacao_modelo,
            )
        )

    return periodos_ajustados


def build_kpis(periods: Sequence[PeriodResult]) -> ModelKpis:
    if not periods:
        return ModelKpis(
            xirr_senior=None,
            xirr_mezz=None,
            xirr_sub_jr=None,
            taxa_retorno_sub_jr_cdi=None,
            duration_senior_anos=None,
            pre_di_duration=None,
        )

    xirr_senior = xirr([(period.data, period.pmt_senior) for period in periods])
    xirr_mezz = xirr([(period.data, period.pmt_mezz) for period in periods])
    xirr_sub_jr = xirr([(period.data, period.pmt_sub_jr) for period in periods])
    duration_senior_anos = calculate_duration_years(periods)
    pre_di_duration = lookup_pre_di_duration(periods, duration_senior_anos)
    taxa_retorno_sub_jr_cdi = None
    if xirr_sub_jr is not None and pre_di_duration is not None:
        taxa_retorno_sub_jr_cdi = ((1.0 + xirr_sub_jr) / (1.0 + pre_di_duration)) - 1.0

    return ModelKpis(
        xirr_senior=xirr_senior,
        xirr_mezz=xirr_mezz,
        xirr_sub_jr=xirr_sub_jr,
        taxa_retorno_sub_jr_cdi=taxa_retorno_sub_jr_cdi,
        duration_senior_anos=duration_senior_anos,
        pre_di_duration=pre_di_duration,
    )
