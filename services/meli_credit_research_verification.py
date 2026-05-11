from __future__ import annotations

from typing import Any

import pandas as pd


RELATIVE_TOLERANCE_PCT = 0.1


def verify_meli_research_outputs(monitor_outputs: Any, research_outputs: Any) -> pd.DataFrame:
    """Independently rebuild key research indicators and compare against production outputs."""
    rows: list[dict[str, object]] = []
    rows.extend(_verify_roll_outputs(research_outputs))
    rows.extend(_verify_cohort_outputs(research_outputs))
    rows.extend(_verify_npl_outputs(research_outputs))
    rows.extend(_verify_portfolio_duration_outputs(monitor_outputs, research_outputs))
    return pd.DataFrame(rows)


def _verify_roll_outputs(research_outputs: Any) -> list[dict[str, object]]:
    df = getattr(research_outputs, "roll_seasonality", pd.DataFrame())
    rows: list[dict[str, object]] = []
    if df is None or df.empty:
        return rows
    for _, row in df.iterrows():
        numerator = _num(row.get("numerator"))
        denominator = _num(row.get("denominator"))
        verified = _safe_div_pct(numerator, denominator)
        rows.append(
            _comparison_row(
                row,
                metric_id=str(row.get("metric_id") or ""),
                calculated=row.get("value_pct"),
                verified=verified,
                unit="%",
                observation="Reconstruído por numerador/denominador persistidos.",
            )
        )
    return rows


def _verify_cohort_outputs(research_outputs: Any) -> list[dict[str, object]]:
    df = getattr(research_outputs, "cohort_research", pd.DataFrame())
    rows: list[dict[str, object]] = []
    if df is None or df.empty:
        return rows
    for _, row in df.iterrows():
        numerator = _num(row.get("numerator"))
        denominator = _num(row.get("denominator"))
        verified = _safe_div_pct(numerator, denominator)
        rows.append(
            _comparison_row(
                row,
                metric_id=f"cohort::{row.get('series_name')}::{row.get('mes_ciclo')}",
                calculated=row.get("value_pct"),
                verified=verified,
                unit="%",
                observation="Reconstruído por numerador/denominador da safra.",
            )
        )
    return rows


def _verify_npl_outputs(research_outputs: Any) -> list[dict[str, object]]:
    df = getattr(research_outputs, "npl_research_table", pd.DataFrame())
    rows: list[dict[str, object]] = []
    if df is None or df.empty:
        return rows
    for _, row in df.iterrows():
        unit = str(row.get("unit") or "")
        if unit == "%":
            verified = _safe_div_pct(_num(row.get("numerator")), _num(row.get("denominator")))
        else:
            verified = _num(row.get("numerator"))
        rows.append(
            _comparison_row(
                row,
                metric_id=str(row.get("metric_id") or ""),
                calculated=row.get("value"),
                verified=verified,
                unit=unit,
                observation="Reconstruído pela identidade de NPL/tabela research.",
            )
        )
    return rows


def _verify_portfolio_duration_outputs(monitor_outputs: Any, research_outputs: Any) -> list[dict[str, object]]:
    df = getattr(research_outputs, "portfolio_duration_table", pd.DataFrame())
    rows: list[dict[str, object]] = []
    if df is None or df.empty:
        return rows
    duration_lookup = _duration_lookup(monitor_outputs)
    for _, row in df.iterrows():
        metric_id = str(row.get("metric_id") or "")
        if metric_id == "duration_months":
            key = (str(row.get("scope") or ""), str(row.get("cnpj") or ""), str(row.get("competencia") or ""))
            raw = duration_lookup.get(key, {})
            numerator = _num(raw.get("duration_weighted_days"))
            denominator = _num(raw.get("duration_total_saldo"))
            verified = (numerator / denominator / 30.4375) if numerator is not None and denominator is not None and denominator > 0 else _num(row.get("value"))
            observation = "Reconstruído por duration_weighted_days / duration_total_saldo quando disponível."
        else:
            verified = _num(row.get("numerator"))
            observation = "Reconstruído por carteira_ex360 persistida."
        rows.append(
            _comparison_row(
                row,
                metric_id=metric_id,
                calculated=row.get("value"),
                verified=verified,
                unit=str(row.get("unit") or ""),
                observation=observation,
            )
        )
    return rows


def _duration_lookup(monitor_outputs: Any) -> dict[tuple[str, str, str], dict[str, object]]:
    lookup: dict[tuple[str, str, str], dict[str, object]] = {}
    frames = [("consolidado", "", getattr(monitor_outputs, "consolidated_monitor", pd.DataFrame()))]
    frames.extend((("fundo", str(cnpj), frame) for cnpj, frame in getattr(monitor_outputs, "fund_monitor", {}).items()))
    for scope, cnpj, frame in frames:
        if frame is None or frame.empty:
            continue
        for _, row in frame.iterrows():
            key = (scope, cnpj, str(row.get("competencia") or ""))
            lookup[key] = row.to_dict()
    return lookup


def _comparison_row(
    row: pd.Series,
    *,
    metric_id: str,
    calculated: object,
    verified: object,
    unit: str,
    observation: str,
) -> dict[str, object]:
    calc = _num(calculated)
    ver = _num(verified)
    abs_diff = None if calc is None or ver is None else calc - ver
    rel_diff = None
    if abs_diff is not None and ver not in (None, 0):
        rel_diff = abs(abs_diff / ver) * 100.0
    status = _status(calc, ver, abs_diff, rel_diff, unit=unit)
    return {
        "scope": row.get("scope"),
        "fund_name": row.get("fund_name"),
        "cnpj": row.get("cnpj"),
        "competencia": row.get("competencia") or row.get("mes_ciclo"),
        "metric_id": metric_id,
        "calculated_value": calc,
        "verified_value": ver,
        "abs_diff": abs_diff,
        "rel_diff_pct": rel_diff,
        "unit": unit,
        "status": status,
        "observacao": observation,
    }


def _status(
    calculated: float | None,
    verified: float | None,
    abs_diff: float | None,
    rel_diff_pct: float | None,
    *,
    unit: str,
) -> str:
    if calculated is None and verified is None:
        return "OK"
    if calculated is None or verified is None:
        return "ALERTA"
    tolerance_abs = 0.000001 if unit in {"%", "meses"} else 0.01
    if abs_diff is not None and abs(abs_diff) <= tolerance_abs:
        return "OK"
    if rel_diff_pct is not None and rel_diff_pct <= RELATIVE_TOLERANCE_PCT:
        return "OK"
    return "ERRO"


def _safe_div_pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return float(numerator / denominator * 100.0)


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)
