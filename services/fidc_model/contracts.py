from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Premissas:
    volume: float
    tx_cessao_am: float
    tx_cessao_cdi_aa: Optional[float]
    custo_adm_aa: float
    custo_min: float
    inadimplencia: float
    proporcao_senior: float
    taxa_senior: float
    proporcao_mezz: float
    taxa_mezz: float
    proporcao_subordinada: Optional[float] = None
    taxa_sub_jr: float = 0.0
    tipo_taxa_senior: str = "pos_cdi"
    tipo_taxa_mezz: str = "pos_cdi"
    tipo_taxa_sub_jr: str = "residual"
    prazo_fidc_anos: Optional[float] = None
    prazo_medio_recebiveis_meses: float = 6.0
    carteira_revolvente: bool = True
    prazo_senior_anos: Optional[float] = None
    prazo_mezz_anos: Optional[float] = None
    prazo_sub_jr_anos: Optional[float] = None
    amortizacao_senior: str = "workbook"
    amortizacao_mezz: str = "workbook"
    juros_senior: str = "periodic"
    juros_mezz: str = "periodic"
    inicio_amortizacao_senior_meses: int = 25
    inicio_amortizacao_mezz_meses: int = 25
    perda_esperada_am: Optional[float] = None
    perda_inesperada_am: Optional[float] = None
    modelo_credito: str = "legacy_percent"
    perda_ciclo: float = 0.0
    npl90_lag_meses: int = 3
    cobertura_minima_npl90: float = 1.0
    lgd: float = 1.0
    rolagem_adimplente_1_30: float = 0.0
    rolagem_1_30_31_60: float = 0.0
    rolagem_31_60_61_90: float = 0.0
    rolagem_61_90_90_plus: float = 0.0
    recuperacao_90_plus: float = 0.0
    writeoff_90_plus: float = 0.0
    agio_aquisicao: float = 0.0
    excesso_spread_senior_am: float = 0.0
    selic_aa_por_ano: tuple[tuple[int, float], ...] = ()

    @property
    def proporcao_sub_jr(self) -> float:
        if self.proporcao_subordinada is not None:
            return self.proporcao_subordinada
        return 1.0 - self.proporcao_senior - self.proporcao_mezz


@dataclass(frozen=True)
class PeriodResult:
    indice: int
    data: datetime
    dc: int
    du: int
    delta_dc: int
    delta_du: int
    pre_di: Optional[float]
    taxa_senior: Optional[float]
    fra_senior: Optional[float]
    taxa_mezz: Optional[float]
    fra_mezz: Optional[float]
    carteira: float
    ead_carteira: float
    fluxo_carteira: float
    taxa_selic_aa: Optional[float]
    taxa_selic_periodo: float
    saldo_caixa_selic_inicio: float
    principal_para_caixa_selic: float
    rendimento_caixa_selic: float
    fluxo_ativos_total: float
    pl_fidc: float
    custos_adm: float
    inadimplencia_despesa: float
    perda_esperada_despesa: float
    perda_inesperada_despesa: float
    perda_carteira_despesa: float
    carteira_vencendo: float
    ead_vencendo: float
    principal_inadimplente: float
    entrada_npl90: float
    npl90_estoque_inicio: float
    npl90_estoque_fim: float
    provisao_saldo_inicio: float
    provisao_requerida: float
    despesa_provisao: float
    provisao_saldo_fim: float
    cobertura_npl90: Optional[float]
    baixa_credito: float
    writeoff_descoberto: float
    recuperacao_credito: float
    bucket_adimplente: float
    bucket_1_30: float
    bucket_31_60: float
    bucket_61_90: float
    bucket_90_plus: float
    resultado_carteira_liquido: float
    prazo_restante_reinvestimento_meses: float
    reinvestimento_elegivel: bool
    principal_recebido_carteira: float
    reinvestimento_principal: float
    reinvestimento_excesso: float
    nova_originacao: float
    carteira_fim: float
    caixa_nao_reinvestido: float
    saldo_caixa_selic_fim: float
    agio_aquisicao_despesa: float
    preco_pago_fator: float
    tx_cessao_am_input: float
    tx_cessao_am_piso: float
    tx_cessao_am_aplicada: float
    principal_senior: float
    juros_senior: float
    pmt_senior: float
    vp_pmt_senior: float
    pl_senior: float
    fluxo_remanescente: float
    principal_mezz: float
    juros_mezz: float
    pmt_mezz: float
    pl_mezz: float
    fluxo_remanescente_mezz: float
    principal_sub_jr: float
    juros_sub_jr: float
    pmt_sub_jr: float
    pl_sub_jr: float
    subordinacao_pct: Optional[float]
    pl_sub_jr_modelo: Optional[float] = field(default=None)
    subordinacao_pct_modelo: Optional[float] = field(default=None)


@dataclass(frozen=True)
class ModelKpis:
    xirr_senior: Optional[float]
    xirr_mezz: Optional[float]
    xirr_sub_jr: Optional[float]
    taxa_retorno_sub_jr_cdi: Optional[float]
    duration_senior_anos: Optional[float]
    pre_di_duration: Optional[float]
