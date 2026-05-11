from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class ModelInputs:
    premissas: Dict[str, float]
    datas: List[datetime]
    feriados: List[datetime]
    curva_du: List[float]
    curva_cdi: List[float]


def load_model_inputs(path: str) -> ModelInputs:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    premissas = {k: float(v) for k, v in data.get("premissas", {}).items()}
    datas = [datetime.fromisoformat(value) for value in data.get("datas", [])]
    feriados = [datetime.fromisoformat(value) for value in data.get("feriados", [])]
    curva_du = [float(v) for v in data.get("curva_du", [])]
    curva_cdi = [float(v) for v in data.get("curva_cdi", [])]
    return ModelInputs(
        premissas=premissas,
        datas=datas,
        feriados=feriados,
        curva_du=curva_du,
        curva_cdi=curva_cdi,
    )
