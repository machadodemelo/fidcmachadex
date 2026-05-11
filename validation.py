from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, List

from data_loader import load_model_inputs
from model import Premissas, build_flow


@dataclass(frozen=True)
class ValidationResult:
    label: str
    excel_value: float
    model_value: float
    diff: float


def _read_expected_samples(path: str) -> List[Dict[str, float]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("expected", {}).get("timeline_samples", [])


def validate_base(path: str, tolerance: float = 1e-2) -> List[ValidationResult]:
    inputs = load_model_inputs(path)
    premissas = Premissas(
        volume=inputs.premissas.get("Volume", 1_000_000.0),
        tx_cessao_am=inputs.premissas.get("Tx Cessão (%am)", 0.1),
        tx_cessao_cdi_aa=inputs.premissas.get("Tx Cessão (CDI+ %aa)", 0.1),
        custo_adm_aa=inputs.premissas.get("Custo Adm/Gestão (a.a.)", 0.0035),
        custo_min=inputs.premissas.get("Custo Adm/Gestão (mín)", 20000.0),
        inadimplencia=inputs.premissas.get("Inadimplência", 0.1),
        proporcao_senior=inputs.premissas.get("Proporção PL Sr.", 0.9),
        taxa_senior=inputs.premissas.get("Taxa Sênior", 0.02),
        proporcao_mezz=inputs.premissas.get("Proporção PL Mezz", 0.05),
        taxa_mezz=inputs.premissas.get("Taxa Mezz", 0.05),
    )
    results = build_flow(inputs.datas, inputs.feriados, inputs.curva_du, inputs.curva_cdi, premissas)
    if not results:
        return []

    expected_samples = _read_expected_samples(path)

    comparisons: List[ValidationResult] = []
    for expected in expected_samples:
        indice = int(expected.get("indice", 0))
        try:
            model_index = next(i for i, r in enumerate(results) if r.indice == indice)
        except StopIteration:
            continue
        result = results[model_index]
        for key, model_value in [
            ("pl_fidc", result.pl_fidc),
            ("pl_senior", result.pl_senior),
            ("pl_mezz", result.pl_mezz),
            ("pl_sub_jr", result.pl_sub_jr),
            ("pmt_senior", result.pmt_senior),
            ("pmt_mezz", result.pmt_mezz),
            ("pmt_sub_jr", result.pmt_sub_jr),
        ]:
            expected_value = expected.get(key)
            if expected_value is None:
                continue
            diff = abs(float(expected_value) - float(model_value))
            if diff > tolerance:
                comparisons.append(
                    ValidationResult(
                        label=f"Indice {indice} {key}",
                        excel_value=float(expected_value),
                        model_value=float(model_value),
                        diff=diff,
                    )
                )
    return comparisons


if __name__ == "__main__":
    diffs = validate_base("model_data.json")
    if diffs:
        raise SystemExit(f"Divergências encontradas: {diffs}")
    print("Validação concluída sem divergências acima da tolerância.")
