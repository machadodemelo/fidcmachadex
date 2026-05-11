"""Gera somatorio_fidcs_v3_comite.pptx usando dados de exemplo.

Uso:
    cd /home/user/fidc
    python scripts/generate_v3_comite.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.somatorio_fidcs_ppt_export import build_somatorio_fidcs_pptx_bytes


# ---------------------------------------------------------------------------
# Parâmetros
# ---------------------------------------------------------------------------
OUTPUT = Path("/mnt/user-data/outputs/somatorio_fidcs_v3_comite.pptx")

FUND_NAMES = [
    "MERCADO CRÉDITO FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS RESPONSABILIDADE LIMITADA",
    "MERCADO CRÉDITO I BRASIL FIDC SEGMENTO FINANCEIRO DE RESPONSABILIDADE LIMITADA",
    "MERCADO CRÉDITO II BRASIL FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS DE RESPONSABILIDADE LIMITADA",
]
FUND_CNPJS = ["11.111.111/0001-11", "22.222.222/0001-22", "33.333.333/0001-33"]

# 12 meses: abr/25 a mar/26
MONTHS = pd.date_range("2025-04-01", periods=12, freq="MS")


# ---------------------------------------------------------------------------
# Fábricas de dados de exemplo
# ---------------------------------------------------------------------------
rng = np.random.default_rng(42)


def _monthly_base(fund_name: str, cnpj: str, scale: float = 1.0) -> pd.DataFrame:
    n = len(MONTHS)
    trend = np.linspace(0, 0.15, n)
    pl_s = (800 + rng.normal(0, 20, n) + trend * 200) * scale * 1_000_000
    pl_sub = (120 + rng.normal(0, 8, n) + trend * 30) * scale * 1_000_000
    subord_pct = np.where(
        np.arange(n) == 1,  # mai/25: outlier em 0% só para o primeiro fundo
        0.01 if scale < 1.1 else 88.0,
        88 + rng.normal(0, 1, n),
    )
    npl90 = np.clip(2.5 + rng.normal(0, 0.3, n) + trend * 0.5, 1.0, 8.0)
    pdd_cov = np.clip(150 + rng.normal(0, 10, n), 100, 250)

    return pd.DataFrame({
        "competencia_dt": MONTHS,
        "competencia": [f"{d.month:02d}/{d.year}" for d in MONTHS],
        "fund_name": fund_name,
        "cnpj": cnpj,
        "pl_senior": pl_s,
        "pl_subordinada_mezz_ex360": pl_sub,
        "subordinacao_total_ex360_pct": subord_pct,
        "npl_over90_ex360_pct": npl90,
        "pdd_npl_over90_ex360_pct": pdd_cov,
    })


def _consolidated_monthly(fund_frames: list[pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for ts in MONTHS:
        row = {"competencia_dt": ts, "competencia": f"{ts.month:02d}/{ts.year}"}
        for col in ["pl_senior", "pl_subordinada_mezz_ex360"]:
            row[col] = sum(
                f.loc[f["competencia_dt"] == ts, col].sum()
                for f in fund_frames
            )
        for col in ["subordinacao_total_ex360_pct", "npl_over90_ex360_pct",
                    "pdd_npl_over90_ex360_pct"]:
            vals = [f.loc[f["competencia_dt"] == ts, col].mean() for f in fund_frames]
            row[col] = float(np.nanmean([v for v in vals if not np.isnan(v)]))
        rows.append(row)
    return pd.DataFrame(rows)


def _monitor_base(fund_name: str, cnpj: str, scale: float = 1.0) -> pd.DataFrame:
    n = len(MONTHS)
    trend = np.linspace(0, 0.12, n)
    cart = (750 + rng.normal(0, 15, n) + trend * 150) * scale * 1_000_000
    yoy = np.clip(20 + rng.normal(0, 5, n), 5, 60)
    npl1 = np.clip(8 + rng.normal(0, 0.5, n), 3, 20)
    npl30 = np.clip(5 + rng.normal(0, 0.4, n), 2, 15)
    npl60 = np.clip(3.5 + rng.normal(0, 0.3, n), 1, 10)
    npl90 = np.clip(2.5 + rng.normal(0, 0.3, n), 0.5, 8)
    dur = np.clip(6 + rng.normal(0, 0.5, n), 3, 12)
    npl_1_90 = np.clip(3 + rng.normal(0, 0.3, n), 1, 8)
    npl_91_360 = np.clip(1.5 + rng.normal(0, 0.2, n), 0.3, 5)
    roll61 = np.clip(2.5 + rng.normal(0, 0.3, n), 0.5, 7)
    roll91 = np.clip(2.0 + rng.normal(0, 0.2, n), 0.5, 6)
    roll121 = np.clip(1.8 + rng.normal(0, 0.2, n), 0.5, 5)
    roll151 = np.clip(1.6 + rng.normal(0, 0.2, n), 0.5, 5)

    return pd.DataFrame({
        "competencia_dt": MONTHS,
        "competencia": [f"{d.month:02d}/{d.year}" for d in MONTHS],
        "fund_name": fund_name,
        "cnpj": cnpj,
        "carteira_ex360": cart,
        "carteira_ex360_yoy_pct": yoy,
        "npl_over1_ex360_pct": npl1,
        "npl_over30_ex360_pct": npl30,
        "npl_over60_ex360_pct": npl60,
        "npl_over90_ex360_pct": npl90,
        "duration_months": dur,
        "npl_1_90_pct": npl_1_90,
        "npl_91_360_pct": npl_91_360,
        "roll_61_90_m3_pct": roll61,
        "roll_91_120_m4_pct": roll91,
        "roll_121_150_m5_pct": roll121,
        "roll_151_180_m6_pct": roll151,
    })


def _consolidated_monitor(fund_monitors: list[pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for ts in MONTHS:
        row = {"competencia_dt": ts, "competencia": f"{ts.month:02d}/{ts.year}"}
        for col in ["carteira_ex360", "carteira_ex360_yoy_pct",
                    "npl_over1_ex360_pct", "npl_over30_ex360_pct",
                    "npl_over60_ex360_pct", "npl_over90_ex360_pct",
                    "duration_months", "npl_1_90_pct", "npl_91_360_pct",
                    "roll_61_90_m3_pct", "roll_91_120_m4_pct",
                    "roll_121_150_m5_pct", "roll_151_180_m6_pct"]:
            vals = [f.loc[f["competencia_dt"] == ts, col].sum()
                    if col in ["carteira_ex360"] else
                    f.loc[f["competencia_dt"] == ts, col].mean()
                    for f in fund_monitors if col in f.columns]
            row[col] = float(np.nanmean([v for v in vals if not np.isnan(float(v))]))
        rows.append(row)
    return pd.DataFrame(rows)


def _cohort_data(fund_name: str, cnpj: str) -> pd.DataFrame:
    rows = []
    cohort_months = MONTHS[-8:]
    for i, ts in enumerate(cohort_months):
        cohort_lbl = f"{ts.strftime('%b-%y').capitalize()}"
        for j, mc in enumerate(["M1", "M2", "M3", "M4", "M5", "M6"]):
            rows.append({
                "cohort": cohort_lbl,
                "cohort_dt": ts,
                "mes_ciclo": mc,
                "fund_name": fund_name,
                "cnpj": cnpj,
                "valor_pct": float(np.clip(1.0 + j * 1.5 + rng.normal(0, 0.2), 0, 20)),
            })
    return pd.DataFrame(rows)


def _roll_seasonality() -> pd.DataFrame:
    rows = []
    month_labels = ["jan", "fev", "mar", "abr", "mai", "jun",
                    "jul", "ago", "set", "out", "nov", "dez"]
    for metric_id in ["roll_61_90_m3", "roll_91_120_m4",
                      "roll_121_150_m5", "roll_151_180_m6"]:
        for yr in [2024, 2025]:
            for m, lbl in enumerate(month_labels, 1):
                rows.append({
                    "scope": "consolidado",
                    "metric_id": metric_id,
                    "month": m,
                    "month_label": lbl,
                    "series_name": str(yr),
                    "value_pct": float(np.clip(
                        2.0 + rng.normal(0, 0.4) + 0.5 * np.sin(m * np.pi / 6),
                        0.5, 8,
                    )),
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Montar outputs mock
# ---------------------------------------------------------------------------
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MockOutputs:
    consolidated_monthly: pd.DataFrame = field(default_factory=pd.DataFrame)
    fund_monthly: dict[str, pd.DataFrame] = field(default_factory=dict)
    consolidated_wide: pd.DataFrame = field(default_factory=pd.DataFrame)
    fund_wide: dict[str, pd.DataFrame] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class MockMonitorOutputs:
    consolidated_monitor: pd.DataFrame = field(default_factory=pd.DataFrame)
    fund_monitor: dict[str, pd.DataFrame] = field(default_factory=dict)
    consolidated_cohorts: pd.DataFrame = field(default_factory=pd.DataFrame)
    fund_cohorts: dict[str, pd.DataFrame] = field(default_factory=dict)


@dataclass
class MockResearchOutputs:
    roll_seasonality: pd.DataFrame = field(default_factory=pd.DataFrame)


def build_mock_data() -> tuple[MockOutputs, MockMonitorOutputs, MockResearchOutputs]:
    scales = [1.0, 0.65, 0.42]
    fund_monthlies = [_monthly_base(n, c, s)
                      for n, c, s in zip(FUND_NAMES, FUND_CNPJS, scales)]
    fund_monitors = [_monitor_base(n, c, s)
                     for n, c, s in zip(FUND_NAMES, FUND_CNPJS, scales)]
    fund_cohorts = {c: _cohort_data(n, c)
                    for n, c in zip(FUND_NAMES, FUND_CNPJS)}

    outputs = MockOutputs(
        consolidated_monthly=_consolidated_monthly(fund_monthlies),
        fund_monthly={c: f for c, f in zip(FUND_CNPJS, fund_monthlies)},
    )
    monitor_outputs = MockMonitorOutputs(
        consolidated_monitor=_consolidated_monitor(fund_monitors),
        fund_monitor={c: f for c, f in zip(FUND_CNPJS, fund_monitors)},
        consolidated_cohorts=_cohort_data("Consolidado", "00.000.000/0001-00"),
        fund_cohorts=fund_cohorts,
    )
    research_outputs = MockResearchOutputs(
        roll_seasonality=_roll_seasonality(),
    )
    return outputs, monitor_outputs, research_outputs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Gerando dados de exemplo...")
    outputs, monitor_outputs, research_outputs = build_mock_data()

    print("Construindo deck v3...")
    pptx_bytes = build_somatorio_fidcs_pptx_bytes(
        outputs=outputs,
        monitor_outputs=monitor_outputs,
        research_outputs=research_outputs,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(pptx_bytes)
    print(f"✓ Arquivo gerado: {OUTPUT}")

    # Verificação rápida
    from pptx import Presentation
    from io import BytesIO
    prs = Presentation(BytesIO(pptx_bytes))
    n = len(prs.slides)
    status = "✓" if n == 19 else "✗"
    print(f"{status} Total de slides: {n} (esperado: 19)")


if __name__ == "__main__":
    main()
