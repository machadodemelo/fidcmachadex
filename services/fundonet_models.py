from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class FundoResolution:
    cnpj: str
    id_fundo: Optional[str]
    nome_fundo: Optional[str] = None


@dataclass(frozen=True)
class DocumentoFundo:
    id: int
    categoria: str
    tipo: str
    especie: str
    data_referencia: Optional[str]
    data_entrega: Optional[str]
    nome_fundo: Optional[str]
    nome_arquivo: Optional[str]
    versao: int
    status: str
    fundo_ou_classe: Optional[str]
    raw: Dict[str, Any]
    nome_administrador: Optional[str] = None
    nome_custodiante: Optional[str] = None
    nome_gestor: Optional[str] = None

    @property
    def competencia(self) -> Optional[date]:
        if not self.data_referencia:
            return None
        for fmt in ("%m/%Y", "%d/%m/%Y", "%d/%m/%Y %H:%M"):
            try:
                parsed = datetime.strptime(self.data_referencia, fmt)
                return date(parsed.year, parsed.month, 1)
            except ValueError:
                continue
        return None

    @property
    def competencia_label(self) -> Optional[str]:
        competencia = self.competencia
        if competencia is None:
            return None
        return competencia.strftime("%m/%Y")

    @property
    def data_referencia_dt(self) -> Optional[date]:
        if not self.data_referencia:
            return None
        for fmt in ("%d/%m/%Y", "%m/%Y", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(self.data_referencia[:19], fmt)
                return date(parsed.year, parsed.month, 1 if fmt == "%m/%Y" else parsed.day)
            except ValueError:
                continue
        return None

    @property
    def data_entrega_dt(self) -> Optional[datetime]:
        if not self.data_entrega:
            return None
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(self.data_entrega[:19], fmt)
            except ValueError:
                continue
        return None

    @property
    def is_active(self) -> bool:
        return (self.status or "").upper().startswith("A")
