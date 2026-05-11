from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Optional, Sequence

from .contracts import PeriodResult


def xirr(cashflows: Sequence[tuple[datetime, float]], guess: float = 0.1) -> Optional[float]:
    if not cashflows:
        return None

    values = [value for _, value in cashflows]
    has_positive = any(value > 0 for value in values)
    has_negative = any(value < 0 for value in values)
    if not (has_positive and has_negative):
        return None

    start = cashflows[0][0]

    def npv(rate: float) -> float:
        return sum(
            value / (1.0 + rate) ** ((dt - start).days / 365.0)
            for dt, value in cashflows
        )

    rate = guess
    for _ in range(100):
        base = 1.0 + rate
        if base <= 0:
            return None
        f_value = npv(rate)
        if abs(f_value) < 1e-9:
            return rate
        derivative = 0.0
        for dt, value in cashflows:
            years = (dt - start).days / 365.0
            derivative -= years * value / (base ** (years + 1.0))
        if derivative == 0:
            return None
        rate -= f_value / derivative
        if not isfinite(rate):
            return None
    return rate if isfinite(rate) else None


def calculate_duration_years(periods: Sequence[PeriodResult]) -> Optional[float]:
    discounted_pmts = [period.vp_pmt_senior for period in periods[1:] if period.vp_pmt_senior]
    if not discounted_pmts:
        return None

    total_discounted = sum(discounted_pmts)
    if total_discounted == 0:
        return None

    weighted_days = sum(
        period.vp_pmt_senior * period.du / total_discounted / 252.0
        for period in periods[1:]
        if period.vp_pmt_senior
    )
    return weighted_days


def lookup_pre_di_duration(periods: Sequence[PeriodResult], duration_years: Optional[float]) -> Optional[float]:
    if duration_years is None:
        return None

    target_du = duration_years * 252.0
    curve_points = [
        (float(period.du), float(period.pre_di))
        for period in periods
        if period.pre_di is not None
    ]
    if not curve_points:
        return None
    curve_points.sort(key=lambda item: item[0])
    first_du, first_rate = curve_points[0]
    if target_du <= first_du:
        return first_rate
    last_du, last_rate = curve_points[-1]
    if target_du >= last_du:
        return last_rate
    for (left_du, left_rate), (right_du, right_rate) in zip(curve_points, curve_points[1:]):
        if left_du <= target_du <= right_du:
            if right_du == left_du:
                return right_rate
            weight = (target_du - left_du) / (right_du - left_du)
            return left_rate + (right_rate - left_rate) * weight
    return None
