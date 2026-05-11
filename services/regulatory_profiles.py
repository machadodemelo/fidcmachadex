from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import pandas as pd

from services.regulatory_knowledge import (
    REGULATORY_KNOWLEDGE_DIR,
    emission_rows,
    extracted_criteria_rows,
    load_regulatory_knowledge,
    normalize_cnpj,
)


REGULATORY_PROFILES_DIR = Path("data/regulatory_profiles")


@dataclass(frozen=True)
class CuratedRegulatoryProfile:
    cnpj: str
    emissions_df: pd.DataFrame
    criteria_df: pd.DataFrame
    source_files: tuple[Path, ...]
    profile_type: str = "curado"

    @property
    def available(self) -> bool:
        return not self.emissions_df.empty or not self.criteria_df.empty


def load_curated_regulatory_profile(
    cnpj: str,
    *,
    base_dir: Path = REGULATORY_PROFILES_DIR,
) -> CuratedRegulatoryProfile | None:
    digits = normalize_cnpj(cnpj)
    if len(digits) != 14 or not base_dir.exists():
        return None

    manual_emissions_frames: list[pd.DataFrame] = []
    manual_criteria_frames: list[pd.DataFrame] = []
    manual_sources: list[Path] = []
    triage_emissions_frames: list[pd.DataFrame] = []
    triage_criteria_frames: list[pd.DataFrame] = []
    triage_sources: list[Path] = []

    for path in sorted(base_dir.glob("*.csv")):
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        except (OSError, pd.errors.ParserError):
            continue
        if "CNPJ" not in frame.columns:
            continue
        frame = frame[frame["CNPJ"].map(normalize_cnpj) == digits].copy()
        if frame.empty:
            continue
        is_triage = path.name.startswith("all_fidcs_")
        sources = triage_sources if is_triage else manual_sources
        emissions_frames = triage_emissions_frames if is_triage else manual_emissions_frames
        criteria_frames = triage_criteria_frames if is_triage else manual_criteria_frames
        sources.append(path)
        if {"Cota/Classe", "Amortização principal"}.issubset(frame.columns):
            emissions_frames.append(frame)
        elif {"Critério", "Monitorabilidade IME"}.issubset(frame.columns):
            criteria_frames.append(frame)

    emissions_frames = manual_emissions_frames or triage_emissions_frames
    criteria_frames = manual_criteria_frames or triage_criteria_frames
    sources = manual_sources or triage_sources
    emissions_df = _concat_or_empty(emissions_frames)
    criteria_df = _concat_or_empty(criteria_frames)
    if emissions_df.empty and criteria_df.empty:
        return None
    return CuratedRegulatoryProfile(
        cnpj=digits,
        emissions_df=emissions_df,
        criteria_df=criteria_df,
        source_files=tuple(dict.fromkeys(sources)),
        profile_type=_profile_type_from_sources(sources),
    )


def load_regulatory_profile(
    cnpj: str,
    *,
    curated_dir: Path = REGULATORY_PROFILES_DIR,
    knowledge_dir: Path = REGULATORY_KNOWLEDGE_DIR,
) -> CuratedRegulatoryProfile | None:
    curated = load_curated_regulatory_profile(cnpj, base_dir=curated_dir)
    if curated is not None and curated.available:
        return curated

    digits = normalize_cnpj(cnpj)
    knowledge = load_regulatory_knowledge(digits, base_dir=knowledge_dir)
    if knowledge is None:
        return None

    emissions_df = _normalize_knowledge_emissions(pd.DataFrame(emission_rows(knowledge)), knowledge.fund_name, digits)
    criteria_df = _normalize_knowledge_criteria(pd.DataFrame(extracted_criteria_rows(knowledge)), knowledge.fund_name, digits)
    if emissions_df.empty and criteria_df.empty:
        return None
    return CuratedRegulatoryProfile(
        cnpj=digits,
        emissions_df=emissions_df,
        criteria_df=criteria_df,
        source_files=(knowledge.path,) if knowledge.path is not None else (),
        profile_type="heurístico",
    )


def payment_calendar_rows(emissions_df: pd.DataFrame) -> list[dict[str, str]]:
    if emissions_df.empty:
        return []

    rows: list[dict[str, str]] = []
    for _, item in emissions_df.iterrows():
        cota = str(item.get("Cota/Classe") or "").strip()
        tipo = str(item.get("Tipo") or "").strip()
        source = str(item.get("Fonte") or "").strip()

        juros = str(item.get("Juros/remuneração") or "").strip()
        if _has_calendar_info(juros):
            rows.append(
                {
                    "Data/janela": "Recorrente",
                    "Cota/Classe": cota,
                    "Tipo": tipo,
                    "Evento": "Juros/remuneração",
                    "Detalhe": juros,
                    "Fonte": source,
                }
            )

        amortizacao = str(item.get("Amortização principal") or "").strip()
        if not _has_calendar_info(amortizacao):
            continue

        dated = _dated_payment_entries(amortizacao)
        if dated:
            for date_label, detail in dated:
                rows.append(
                    {
                        "Data/janela": date_label,
                        "Cota/Classe": cota,
                        "Tipo": tipo,
                        "Evento": "Amortização principal",
                        "Detalhe": detail,
                        "Fonte": source,
                    }
                )
            continue

        rows.append(
            {
                "Data/janela": _payment_window_label(amortizacao),
                "Cota/Classe": cota,
                "Tipo": tipo,
                "Evento": "Amortização principal",
                "Detalhe": amortizacao,
                "Fonte": source,
            }
        )
    return rows


def _normalize_knowledge_emissions(frame: pd.DataFrame, fund_name: str, cnpj: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    rows: list[dict[str, str]] = []
    for _, item in frame.iterrows():
        cota = str(item.get("Classe/Série") or "").strip()
        event = str(item.get("Evento") or "").strip()
        remuneration = str(item.get("Remuneração") or "").strip()
        amortization = str(item.get("Amortização/Vencimento") or "").strip()
        rows.append(
            {
                "Fundo": fund_name,
                "CNPJ": _format_cnpj(cnpj),
                "Cota/Classe": cota,
                "Tipo": _infer_quota_type(cota),
                "Data deliberação": "",
                "Data emissão / 1ª integralização": str(item.get("Data") or "").strip(),
                "Data encerramento/oferta": "",
                "Quantidade": "",
                "Volume": str(item.get("Volume") or "").strip(),
                "VNU": "",
                "Remuneração": remuneration,
                "Juros/remuneração": remuneration,
                "Amortização principal": amortization,
                "Status/evidência": event,
                "Fonte": str(item.get("Fonte") or "").strip(),
            }
        )
    return pd.DataFrame(rows)


def _normalize_knowledge_criteria(frame: pd.DataFrame, fund_name: str, cnpj: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    rows: list[dict[str, str]] = []
    for _, item in frame.iterrows():
        rows.append(
            {
                "Fundo": fund_name,
                "CNPJ": _format_cnpj(cnpj),
                "Critério": str(item.get("Critério") or "").strip(),
                "Chave": str(item.get("Chave") or "").strip(),
                "Limite/regra": str(item.get("Limite") or "").strip(),
                "Monitorabilidade IME": str(item.get("Monitoramento") or "").strip(),
                "Métrica IME / proxy": str(item.get("Métrica IME sugerida") or "").strip(),
                "Condição de alerta sugerida": _alert_text_for_criterion(item),
                "Observação técnica": str(item.get("Comentário") or "").strip(),
                "Fonte": str(item.get("Fonte") or "").strip(),
            }
        )
    return pd.DataFrame(rows)


def _alert_text_for_criterion(item: pd.Series) -> str:
    comparison = str(item.get("Comparação") or "").strip()
    limit = str(item.get("Limite") or "").strip()
    if not comparison or not limit:
        return ""
    if comparison in {">=", ">"}:
        return f"Alerta se valor IME ficar abaixo de {limit}"
    if comparison in {"<=", "<"}:
        return f"Alerta se valor IME ficar acima de {limit}"
    return f"Validar {comparison} {limit}"


def _infer_quota_type(value: str) -> str:
    lowered = str(value or "").lower()
    if "senior" in lowered or "sênior" in lowered:
        return "Sênior"
    if "mezan" in lowered:
        return "Mezanino"
    if "sub" in lowered or "junior" in lowered or "júnior" in lowered:
        return "Subordinada"
    return ""


def _format_cnpj(cnpj: str) -> str:
    digits = normalize_cnpj(cnpj)
    if len(digits) != 14:
        return cnpj
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _concat_or_empty(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)


def _profile_type_from_sources(sources: list[Path]) -> str:
    names = {path.name for path in sources}
    if any(name.startswith("pravaler_") for name in names):
        return "curado parcial"
    if any(name.startswith("all_fidcs_") for name in names):
        return "triagem estruturada"
    return "curado"


def _has_calendar_info(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return lowered not in {
        "não identificado",
        "não identificada",
        "não identificado nos pdfs baixados",
        "sem calendário fixo identificado",
    }


def _dated_payment_entries(value: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for match in re.finditer(r"(\d{2}/\d{2}/\d{4})\s*:\s*([^;]+)", value):
        entries.append((match.group(1), match.group(2).strip()))
    return entries


def _payment_window_label(value: str) -> str:
    match = re.search(r"(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})", value)
    if match:
        return f"{match.group(1)} → {match.group(2)}"
    return "Conforme regra"
