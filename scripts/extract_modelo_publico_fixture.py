from __future__ import annotations

import json
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = ROOT / "Modelo_Publico (1).xlsm"
OUTPUT_PATH = ROOT / "tests" / "fixtures" / "modelo_publico_fixture.json"


def _float_or_none(value):
    if value in (None, ""):
        return None
    if isinstance(value, str) and value.startswith("#"):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    workbook = load_workbook(WORKBOOK_PATH, data_only=True, keep_vba=True)
    sheet = workbook["Fluxo Base"]

    timeline = []
    for row in range(4, 21):
        timeline.append(
            {
                "indice": int(sheet[f"E{row}"].value),
                "data": sheet[f"F{row}"].value.date().isoformat(),
                "dc": int(sheet[f"G{row}"].value),
                "du": int(sheet[f"H{row}"].value),
                "pre_di": _float_or_none(sheet[f"I{row}"].value),
                "taxa_senior": _float_or_none(sheet[f"J{row}"].value),
                "fra_senior": _float_or_none(sheet[f"K{row}"].value),
                "taxa_mezz": _float_or_none(sheet[f"L{row}"].value),
                "fra_mezz": _float_or_none(sheet[f"M{row}"].value),
                "carteira": _float_or_none(sheet[f"O{row}"].value),
                "fluxo_carteira": _float_or_none(sheet[f"Q{row}"].value),
                "pl_fidc": _float_or_none(sheet[f"R{row}"].value),
                "custos_adm": _float_or_none(sheet[f"T{row}"].value),
                "inadimplencia_despesa": _float_or_none(sheet[f"U{row}"].value),
                "pmt_senior": _float_or_none(sheet[f"Y{row}"].value),
                "vp_pmt_senior": _float_or_none(sheet[f"Z{row}"].value),
                "pl_senior": _float_or_none(sheet[f"AA{row}"].value),
                "pmt_mezz": _float_or_none(sheet[f"AG{row}"].value),
                "pl_mezz": _float_or_none(sheet[f"AH{row}"].value),
                "pmt_sub_jr": _float_or_none(sheet[f"AN{row}"].value),
                "pl_sub_jr": _float_or_none(sheet[f"AO{row}"].value),
                "subordinacao_pct": _float_or_none(sheet[f"AW{row}"].value),
            }
        )

    payload = {
        "workbook": WORKBOOK_PATH.name,
        "sheet": "Fluxo Base",
        "kpis": {
            "xirr_senior": _float_or_none(sheet["C17"].value),
            "xirr_mezz": _float_or_none(sheet["C21"].value),
            "xirr_sub_jr": _float_or_none(sheet["C24"].value),
            "taxa_retorno_sub_jr_cdi": _float_or_none(sheet["C25"].value),
            "duration_senior_anos": _float_or_none(sheet["C27"].value),
            "pre_di_duration": _float_or_none(sheet["C28"].value),
        },
        "timeline": timeline,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    workbook.close()


if __name__ == "__main__":
    main()
