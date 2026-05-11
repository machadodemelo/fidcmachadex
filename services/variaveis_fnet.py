from __future__ import annotations

import re
from collections.abc import Iterable

import pandas as pd


COMPETENCIA_COLUMN_RE = re.compile(r"^\d{2}/\d{4}$")


VARIAVEIS_FNET: list[tuple[str, str, str]] = [
    ("APLIC_ATIVO/VL_SOM_APLIC_ATIVO", "1 - Ativo (R$)", "ATIVO"),
    ("APLIC_ATIVO/VL_DISPONIB", "1 - Disponibilidades", "ATIVO"),
    ("APLIC_ATIVO/VL_CARTEIRA", "2 - Carteira", "ATIVO"),
    ("CRED_EXISTE/VL_SOM_DICRED_AQUIS", "a) Direitos Creditórios com Aquisição Substancial dos Riscos e Benefícios", "ATIVO"),
    ("CRED_EXISTE/VL_CRED_EXISTE_VENC_ADIMPL", "a.1) Créditos Existentes a Vencer e Adimplentes", "ATIVO"),
    ("CRED_EXISTE/VL_CRED_EXISTE_VENC_INAD", "a.2) Créditos Existentes a Vencer com Parcelas Inadimplentes", "ATIVO"),
    ("CRED_EXISTE/VL_CRED_TOTAL_VENC_INAD", "a.2.1) Valor Total das Parcelas Inadimplentes", "ATIVO"),
    ("CRED_EXISTE/VL_CRED_EXISTE_INAD", "a.3) Créditos Existentes Inadimplentes", "ATIVO"),
    ("CRED_EXISTE/VL_CRED_REFER_DICRED_PERFO", "a.4) Créditos Referentes a Direitos Creditórios a Performar", "ATIVO"),
    ("CRED_EXISTE/VL_CRED_VENC_PEND", "a.5) Créditos vencidos e pendentes na cessão", "ATIVO"),
    ("CRED_EXISTE/VL_CRED_ORIGEM_EMP_PROC_RECUP", "a.6) Créditos de Empresas em Recuperação Judicial/Extrajudicial", "ATIVO"),
    ("CRED_EXISTE/VL_DECOR_RECEIT_PUBLIC", "a.7) Créditos de receitas públicas (União/Estados/DF/Municípios)", "ATIVO"),
    ("CRED_EXISTE/VL_CRED_ACAO_JUDIC", "a.8) Créditos de ações judiciais em curso", "ATIVO"),
    ("CRED_EXISTE/VL_CRED_CONST_JUR_FATRISC", "a.9) Créditos com fator preponderante de risco jurídico", "ATIVO"),
    ("CRED_EXISTE/VL_OUTROS_CRED", "a.10) Outros créditos (não enquadráveis ICVM 356, art. 2º, I)", "ATIVO"),
    ("CRED_EXISTE/VL_PROVIS_REDUC_RECUP", "a.11) Provisão para Redução no Valor de Recuperação (-)", "ATIVO"),
    ("DICRED/VL_DICRED", "b) Direitos Creditórios sem Aquisição Substancial dos Riscos e Benefícios", "ATIVO"),
    ("DICRED/VL_DICRED_CEDENT", "b.1) Créditos Existentes a Vencer e Adimplentes", "ATIVO"),
    ("DICRED/VL_DICRED_EXISTE_VENC_INAD", "b.2) Créditos Existentes a Vencer com Parcelas Inadimplentes", "ATIVO"),
    ("DICRED/VL_DICRED_TOTAL_VENC_INAD", "b.2.1) Valor total das parcelas Inadimplentes", "ATIVO"),
    ("DICRED/VL_DICRED_EXISTE_INAD", "b.3) Créditos Existentes Inadimplentes", "ATIVO"),
    ("DICRED/VL_DICRED_REFER_DICRED_PERFO", "b.4) Créditos a Performar", "ATIVO"),
    ("DICRED/VL_DICRED_VENC_PEND", "b.5) Créditos vencidos e pendentes na cessão", "ATIVO"),
    ("DICRED/VL_DICRED_ORIGEM_EMP_PROC_RECUP", "b.6) Créditos de Empresas em Recuperação Judicial/Extrajudicial", "ATIVO"),
    ("DICRED/VL_DICRED_RECEIT_PUBLIC", "b.7) Créditos de receitas públicas", "ATIVO"),
    ("DICRED/VL_DICRED_ACAO_JUDIC", "b.8) Créditos de ações judiciais", "ATIVO"),
    ("DICRED/VL_DICRED_CONST_JUR_FATRISC", "b.9) Créditos com fator preponderante de risco jurídico", "ATIVO"),
    ("DICRED/VL_DICRED_OUTROS_CRED", "b.10) Outros créditos (não enquadráveis ICVM 356)", "ATIVO"),
    ("DICRED/VL_DICRED_PROVIS_REDUC_RECUP", "b.11) Provisão para Redução no Valor de Recuperação (-)", "ATIVO"),
    ("VALORES_MOB/VL_SOM_VALORES_MOB", "c) Valores Mobiliários", "ATIVO"),
    ("VALORES_MOB/VL_DEBT", "c.1) Debêntures", "ATIVO"),
    ("VALORES_MOB/VL_CRI", "c.2) CRI", "ATIVO"),
    ("VALORES_MOB/VL_NP_COMERC", "c.3) Notas Promissórias Comerciais", "ATIVO"),
    ("VALORES_MOB/VL_LETRA_FINANC", "c.4) Letras Financeiras", "ATIVO"),
    ("VALORES_MOB/VL_COTA_FDO_ICVM409", "c.5) Cotas de Fundos da ICVM 409", "ATIVO"),
    ("VALORES_MOB/VL_OUTRO_DICRED", "c.6) Outros", "ATIVO"),
    ("APLIC_ATIVO/VL_TITPUB_FED", "d) Títulos Públicos Federais", "ATIVO"),
    ("APLIC_ATIVO/VL_CDB", "e) Certificados de Depósitos Bancários", "ATIVO"),
    ("APLIC_ATIVO/VL_APLIC_OPER_COMPSS", "f) Aplicações em Operações Compromissadas", "ATIVO"),
    ("APLIC_ATIVO/VL_ATIV_FINANC_RF", "g) Outros Ativos Financeiros de Renda Fixa", "ATIVO"),
    ("APLIC_ATIVO/VL_COTA_FIDC", "h) Cotas de FIDC", "ATIVO"),
    ("APLIC_ATIVO/VL_COTA_FIDC_NAO_PADRAO", "i) Cotas de FIDC Não Padronizados", "ATIVO"),
    ("APLIC_ATIVO/VL_CONTR_COMPRA_VENDA_PRESTC_FUTURA", "j) Warrants e Contratos de Compra/Venda Futura", "ATIVO"),
    ("APLIC_ATIVO/VL_PVS_DBT_CRI_NTA_PMS", "(-) Provisões sobre Debêntures, CRI, NP e Letras Financeiras", "ATIVO"),
    ("APLIC_ATIVO/VL_PVS_CTA_FND_INV", "(-) Provisões sobre Cotas de FIDC", "ATIVO"),
    ("APLIC_ATIVO/VL_PVS_OTR_ATV", "(-) Provisões sobre outros ativos", "ATIVO"),
    ("MERC_DERIVATIVO/VL_SOM_MERC_DERIVATIVO", "3 - Posições Mantidas em Mercados de Derivativos", "ATIVO"),
    ("MERC_DERIVATIVO/VL_MERC_TERMO_POS_COMPRD", "a) Mercado a Termo - Posições Compradas", "ATIVO"),
    ("MERC_DERIVATIVO/VL_MERC_OP_POS_TITUL", "b) Mercado de Opções - Posições Titulares", "ATIVO"),
    ("MERC_DERIVATIVO/VL_MERC_FUT_AJUST_POSIT", "c) Mercado Futuro - Ajustes Positivos", "ATIVO"),
    ("MERC_DERIVATIVO/VL_DIFER_SWAP_RECEB", "d) Diferencial de Swap a Receber", "ATIVO"),
    ("MERC_DERIVATIVO/VL_COBERT_PREST", "e) Coberturas Prestadas", "ATIVO"),
    ("MERC_DERIVATIVO/VL_DEPOS_MARGEM", "f) Depósitos de Margem", "ATIVO"),
    ("OUTROS_ATIVOS/VL_SOM_OUTROS_ATIVOS", "4 - Outros Ativos", "ATIVO"),
    ("OUTROS_ATIVOS/VL_OUTRO_VL_RECEB_CURPRZ", "a) Curto Prazo (<= 12 meses)", "ATIVO"),
    ("OUTROS_ATIVOS/VL_OUTRO_VL_RECEB_LPRAZO", "b) Longo Prazo (> 12 meses)", "ATIVO"),
    ("CART_SEGMT/VL_SOM_CART_SEGMT", "II - Carteira por Segmento", "SEGMENTO"),
    ("CART_SEGMT/VL_IND", "a) Industrial", "SEGMENTO"),
    ("CART_SEGMT/VL_MERC_IMOBIL", "b) Mercado Imobiliário (não financeiro)", "SEGMENTO"),
    ("SEGMT_COMERC/VL_SOM_SEGMT_COMERC", "c) Comercial", "SEGMENTO"),
    ("SEGMT_COMERC/VL_COMERC", "c.1) Comercial", "SEGMENTO"),
    ("SEGMT_COMERC/VL_COMERC_VARJ", "c.2) Comercial - Varejo", "SEGMENTO"),
    ("SEGMT_COMERC/VL_ARREND_MERCNT", "c.3) Arrendamento Mercantil", "SEGMENTO"),
    ("SEGMT_SERV/VL_SOM_SEGMT_SERV", "d) Serviços", "SEGMENTO"),
    ("SEGMT_SERV/VL_SERV", "d.1) Serviços", "SEGMENTO"),
    ("SEGMT_SERV/VL_SERV_PUBLIC", "d.2) Serviços Públicos", "SEGMENTO"),
    ("SEGMT_SERV/VL_SERV_EDUC", "d.3) Serviços Educacionais", "SEGMENTO"),
    ("SEGMT_SERV/VL_SERV_ENTRETEN", "d.4) Entretenimento", "SEGMENTO"),
    ("CART_SEGMT/VL_AGRONEG", "e) Agronegócio", "SEGMENTO"),
    ("SEGMT_FINANC/VL_SOM_SEGMT_FINANC", "f) Financeiro", "SEGMENTO"),
    ("SEGMT_FINANC/VL_FINANC_CRED_PESSOA", "f.1) Crédito Pessoal", "SEGMENTO"),
    ("SEGMT_FINANC/VL_FINANC_CRED_PESSOA_CONSIG", "f.2) Crédito Pessoal Consignado", "SEGMENTO"),
    ("SEGMT_FINANC/VL_FINANC_CRED_CORPOR", "f.3) Crédito Corporativo", "SEGMENTO"),
    ("SEGMT_FINANC/VL_FINANC_MMARKET", "f.4) Middle Market", "SEGMENTO"),
    ("SEGMT_FINANC/VL_FINANC_VEICL", "f.5) Veículos", "SEGMENTO"),
    ("SEGMT_FINANC/VL_FINANC_IMOBIL_EMPSRL", "f.6) Carteira Imobiliária - Empresarial", "SEGMENTO"),
    ("SEGMT_FINANC/VL_FINANC_IMOBIL_RESID", "f.7) Carteira Imobiliária - Residencial", "SEGMENTO"),
    ("SEGMT_FINANC/VL_FINANC_OUTRO", "f.8) Outros (Financeiro)", "SEGMENTO"),
    ("CART_SEGMT/VL_CART_CRED", "g) Cartão de Crédito", "SEGMENTO"),
    ("SEGMT_FACT/VL_SOM_SEGMT_FACT", "h) Factoring", "SEGMENTO"),
    ("SEGMT_FACT/VL_FACT_PESSOA", "h.1) Factoring - Pessoal", "SEGMENTO"),
    ("SEGMT_FACT/VL_FACT_CORPOR", "h.2) Factoring - Corporativo", "SEGMENTO"),
    ("SEGMT_SETOR_PUBLIC/VL_SOM_SEGMT_SETOR_PUBLIC", "i) Setor Público (ICVM 444)", "SEGMENTO"),
    ("SEGMT_SETOR_PUBLIC/VL_SETOR_PUBLIC_PRECAT", "i.1) Precatórios", "SEGMENTO"),
    ("SEGMT_SETOR_PUBLIC/VL_SETOR_PUBLIC_CRED_TRIBUT", "i.2) Créditos Tributários", "SEGMENTO"),
    ("SEGMT_SETOR_PUBLIC/VL_SETOR_PUBLIC_ROYA", "i.3) Royalties", "SEGMENTO"),
    ("SEGMT_SETOR_PUBLIC/VL_SETOR_PUBLIC_OUTRO", "i.4) Outros (Setor Público)", "SEGMENTO"),
    ("CART_SEGMT/VL_ACAO_JUDIC", "j) Ações Judiciais (ICVM 444)", "SEGMENTO"),
    ("CART_SEGMT/VL_PROPRD_MARCA_PATENT", "k) Propriedade Intelectual e Marcas & Patentes", "SEGMENTO"),
    ("PASSIV/VL_SOM_PASSIV", "III - Passivo", "PASSIVO"),
    ("PASSIV_VALORES/VL_SOM_PASSIV_VALORES", "a) Valores a pagar", "PASSIVO"),
    ("PASSIV_VALORES/VL_PGTO_CURPRZ", "a.1) Curto Prazo", "PASSIVO"),
    ("PASSIV_VALORES/VL_PGTO_LPRAZO", "a.2) Longo Prazo", "PASSIVO"),
    ("PASSIV_POSICOES/VL_SOM_PASSIV_POSICOES", "b) Posições Mantidas em Mercado de Derivativos", "PASSIVO"),
    ("PASSIV_POSICOES/VL_POS_MANT_VEND", "b.1) Mercado a termo (Posições vendidas)", "PASSIVO"),
    ("PASSIV_POSICOES/VL_POS_MANT_LANC", "b.2) Mercado de Opções (Posições Lançadas)", "PASSIVO"),
    ("PASSIV_POSICOES/VL_POS_MANT_AJT_FUT", "b.3) Mercado Futuro (Ajustes Negativos)", "PASSIVO"),
    ("PASSIV_POSICOES/VL_POS_MANT_SWAP_PAGAR", "b.4) Diferencial de Swap a Pagar", "PASSIVO"),
    ("PATRLIQ/VL_SOM_PATRLIQ", "IV - Patrimônio Líquido", "PL"),
    ("PATRLIQ/VL_PATRIM_LIQ", "a) Valor do Patrimônio Líquido", "PL"),
    ("PATRLIQ/VL_PATRIM_LIQ_MEDIO", "b) Valor do PL Médio (últimos 3 meses)", "PL"),
    ("COMPMT_DICRED_AQUIS/VL_SOM_PRAZO_VENC", "V.a) Por Prazo de Vencimento (R$)", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_30", "V.a.1) Até 30 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_31_60", "V.a.2) De 31 a 60 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_61_90", "V.a.3) De 61 a 90 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_91_120", "V.a.4) De 91 a 120 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_121_150", "V.a.5) De 121 a 150 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_151_180", "V.a.6) De 151 a 180 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_181_360", "V.a.7) De 181 a 360 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_361_720", "V.a.8) De 361 a 720 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_721_1080", "V.a.9) De 721 a 1080 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_1080", "V.a.10) Acima de 1080 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_SOM_INAD_VENC", "V.b) Inadimplentes (Parcelas Inadimplentes, R$)", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_INAD_VENC_30", "V.b.1) Vencidos 1 a 30 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_INAD_VENC_31_60", "V.b.2) Vencidos 31 a 60 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_INAD_VENC_61_90", "V.b.3) Vencidos 61 a 90 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_INAD_VENC_91_120", "V.b.4) Vencidos 91 a 120 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_INAD_VENC_121_150", "V.b.5) Vencidos 121 a 150 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_INAD_VENC_151_180", "V.b.6) Vencidos 151 a 180 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_INAD_VENC_181_360", "V.b.7) Vencidos 181 a 360 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_INAD_VENC_361_720", "V.b.8) Vencidos 361 a 720 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_INAD_VENC_721_1080", "V.b.9) Vencidos 721 a 1080 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_INAD_VENC_1080", "V.b.10) Vencidos acima de 1080 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_SOM_PAGO_ANTCP", "V.c) Pagos Antecipadamente (R$)", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PAGO_ANTCP_30", "V.c.1) Pagos Antecipadamente 1 a 30 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PAGO_ANTCP_31_60", "V.c.2) 31 a 60 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PAGO_ANTCP_61_90", "V.c.3) 61 a 90 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PAGO_ANTCP_91_120", "V.c.4) 91 a 120 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PAGO_ANTCP_121_150", "V.c.5) 121 a 150 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PAGO_ANTCP_151_180", "V.c.6) 151 a 180 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PAGO_ANTCP_181_360", "V.c.7) 181 a 360 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PAGO_ANTCP_361_720", "V.c.8) 361 a 720 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PAGO_ANTCP_721_1080", "V.c.9) 721 a 1080 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_AQUIS/VL_PAGO_ANTCP_1080", "V.c.10) acima de 1080 dias", "COMPORTAMENTO_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_SOM_PRAZO_VENC", "VI.a) Por Prazo de Vencimento (R$)", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PRAZO_VENC_30", "VI.a.1) Até 30 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PRAZO_VENC_31_60", "VI.a.2) De 31 a 60 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PRAZO_VENC_61_90", "VI.a.3) De 61 a 90 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PRAZO_VENC_91_120", "VI.a.4) De 91 a 120 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PRAZO_VENC_121_150", "VI.a.5) De 121 a 150 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PRAZO_VENC_151_180", "VI.a.6) De 151 a 180 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PRAZO_VENC_181_360", "VI.a.7) De 181 a 360 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PRAZO_VENC_361_720", "VI.a.8) De 361 a 720 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PRAZO_VENC_721_1080", "VI.a.9) De 721 a 1080 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PRAZO_VENC_1080", "VI.a.10) Acima de 1080 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_SOM_INAD_VENC", "VI.b) Inadimplentes (R$)", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_INAD_VENC_30", "VI.b.1) 1 a 30 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_INAD_VENC_31_60", "VI.b.2) 31 a 60 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_INAD_VENC_61_90", "VI.b.3) 61 a 90 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_INAD_VENC_91_120", "VI.b.4) 91 a 120 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_INAD_VENC_121_150", "VI.b.5) 121 a 150 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_INAD_VENC_151_180", "VI.b.6) 151 a 180 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_INAD_VENC_181_360", "VI.b.7) 181 a 360 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_INAD_VENC_361_720", "VI.b.8) 361 a 720 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_INAD_VENC_721_1080", "VI.b.9) 721 a 1080 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_INAD_VENC_1080", "VI.b.10) acima de 1080 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_SOM_PAGO_ANTCP", "VI.c) Pagos Antecipadamente (R$)", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PAGO_ANTCP_30", "VI.c.1) 1 a 30 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PAGO_ANTCP_31_60", "VI.c.2) 31 a 60 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PAGO_ANTCP_61_90", "VI.c.3) 61 a 90 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PAGO_ANTCP_91_120", "VI.c.4) 91 a 120 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PAGO_ANTCP_121_150", "VI.c.5) 121 a 150 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PAGO_ANTCP_151_180", "VI.c.6) 151 a 180 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PAGO_ANTCP_181_360", "VI.c.7) 181 a 360 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PAGO_ANTCP_361_720", "VI.c.8) 361 a 720 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PAGO_ANTCP_721_1080", "VI.c.9) 721 a 1080 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("COMPMT_DICRED_SEM_AQUIS/VL_PAGO_ANTCP_1080", "VI.c.10) acima de 1080 dias", "COMPORTAMENTO_SEM_AQUIS"),
    ("AQUISICOES/QT_DICRED_AQUIS", "VII.a) Aquisições - Quantidade Total", "NEGOCIOS_MES"),
    ("AQUISICOES/VL_DICRED_AQUIS", "VII.a) Aquisições - Valor total", "NEGOCIOS_MES"),
    ("NEGOC_DICRED_MES_AQUIS/QT_DICRED_AQUIS", "VII.a.1.1) DC com Aquisição - Quantidade", "NEGOCIOS_MES"),
    ("NEGOC_DICRED_MES_AQUIS/VL_DICRED_AQUIS", "VII.a.1.2) DC com Aquisição - Valor", "NEGOCIOS_MES"),
    ("NEGOC_DICRED_MES_SEM_AQUIS/QT_DICRED_AQUIS", "VII.a.2.1) DC sem Aquisição - Quantidade", "NEGOCIOS_MES"),
    ("NEGOC_DICRED_MES_SEM_AQUIS/VL_DICRED_AQUIS", "VII.a.2.2) DC sem Aquisição - Valor", "NEGOCIOS_MES"),
    ("DICRED_MES_ALIEN/QT_DICRED_ALIEN", "VII.b) Alienações - Quantidade Total", "NEGOCIOS_MES"),
    ("DICRED_MES_ALIEN/VL_DICRED_ALIEN", "VII.b) Alienações - Valor total", "NEGOCIOS_MES"),
    ("DICRED_MES_ALIEN/VL_DICRED_ALIEN_CONTAB", "VII.b) Alienações - Valor Contábil Total", "NEGOCIOS_MES"),
    ("DICRED_MES_ALIEN_RECOMP/QT_DICRED_ALIEN", "VII.d.1) Recompras - Qtd", "NEGOCIOS_MES"),
    ("DICRED_MES_ALIEN_RECOMP/VL_DICRED_ALIEN", "VII.d.2) Recompras - Valor", "NEGOCIOS_MES"),
    ("DICRED_MES_ALIEN_RECOMP/VL_DICRED_ALIEN_CONTAB", "VII.d.3) Recompras - Valor Contábil", "NEGOCIOS_MES"),
    ("RENT_CLASSE_SENIOR/PR_APURADA", "Rentabilidade Sênior apurada (% a.m.)", "COTAS"),
    ("RENT_CLASSE_SUBORD/PR_APURADA", "Rentabilidade Subordinada apurada (% a.m.)", "COTAS"),
    ("CLASSE_SENIOR/QT_COTAS", "Classe Sênior - Qtd Cotas", "COTAS"),
    ("CLASSE_SENIOR/VL_COTAS", "Classe Sênior - Valor Cotas", "COTAS"),
    ("CLASSE_SUBORD/QT_COTAS", "Classe Subordinada - Qtd Cotas", "COTAS"),
    ("CLASSE_SUBORD/VL_COTAS", "Classe Subordinada - Valor Cotas", "COTAS"),
    ("CLASSE_SENIOR/VL_COTA", "Classe Sênior - Valor por Cota", "COTAS"),
    ("CLASSE_SENIOR/VL_TOTAL", "Classe Sênior - Valor Total", "COTAS"),
    ("CLASSE_SUBORD/VL_COTA", "Classe Subordinada - Valor por Cota", "COTAS"),
    ("CLASSE_SUBORD/VL_TOTAL", "Classe Subordinada - Valor Total", "COTAS"),
]


def competencia_columns(frame: pd.DataFrame) -> list[str]:
    return sorted(
        [str(column) for column in frame.columns if COMPETENCIA_COLUMN_RE.fullmatch(str(column))],
        key=lambda value: (int(value.split("/")[1]), int(value.split("/")[0])),
    )


def resolve_tag_path(short_id: str, wide_df_or_index: pd.DataFrame | pd.Index | Iterable[str]) -> str | None:
    if isinstance(wide_df_or_index, pd.DataFrame):
        if "tag_path" in wide_df_or_index.columns:
            candidates = wide_df_or_index["tag_path"].dropna().astype(str).tolist()
        else:
            candidates = [str(value) for value in wide_df_or_index.index]
    elif isinstance(wide_df_or_index, pd.Index):
        candidates = [str(value) for value in wide_df_or_index]
    else:
        candidates = [str(value) for value in wide_df_or_index]
    target = str(short_id or "").strip().strip("/")
    if not target:
        return None
    if target in candidates:
        return target
    suffix = f"/{target}"
    matches = [candidate for candidate in candidates if candidate.endswith(suffix)]
    if not matches:
        return None
    return sorted(matches, key=lambda value: (len(value), value))[0]


def variaveis_fnet_df(wide_df: pd.DataFrame | None = None) -> pd.DataFrame:
    rows = []
    source = wide_df if wide_df is not None else pd.Index([])
    for ordem, (id_cvm, label, secao) in enumerate(VARIAVEIS_FNET, start=1):
        rows.append(
            {
                "ordem": ordem,
                "id_cvm": id_cvm,
                "label": label,
                "secao": secao,
                "tag_path": resolve_tag_path(id_cvm, source) if wide_df is not None else None,
            }
        )
    return pd.DataFrame(rows)
