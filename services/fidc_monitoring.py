from __future__ import annotations

import pandas as pd


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_pct(numerator: object, denominator: object) -> float | None:
    num = _float_or_none(numerator)
    den = _float_or_none(denominator)
    if num is None or den is None or den <= 0:
        return None
    return float(num / den * 100.0)


def _event_lookup_value(event_summary_latest_df: pd.DataFrame, event_type: str, field: str) -> float | None:
    if event_summary_latest_df.empty or field not in event_summary_latest_df.columns:
        return None
    matches = event_summary_latest_df[event_summary_latest_df["event_type"] == event_type]
    if matches.empty:
        return None
    return _float_or_none(matches.iloc[0].get(field))


def _latest_top_segment(segment_latest_df: pd.DataFrame) -> tuple[str | None, float | None]:
    if segment_latest_df.empty:
        return None, None
    ordered = segment_latest_df.sort_values("valor", ascending=False)
    row = ordered.iloc[0]
    return str(row.get("segmento") or "").strip() or None, _float_or_none(row.get("percentual"))


def _latest_row_value(df: pd.DataFrame, column: str) -> float | None:
    if df.empty or column not in df.columns:
        return None
    ordered = df.sort_values("competencia_dt")
    return _float_or_none(ordered.iloc[-1].get(column))


def _metric_row(
    *,
    risk_block: str,
    risk_block_order: int,
    metric_id: str,
    label: str,
    value: object,
    unit: str,
    criticality: str,
    source_data: str,
    transformation: str,
    final_variable: str,
    formula: str,
    pipeline: str,
    interpretation: str,
    limitation: str,
    state: str,
) -> dict[str, object]:
    return {
        "risk_block": risk_block,
        "risk_block_order": risk_block_order,
        "metric_id": metric_id,
        "label": label,
        "value": _float_or_none(value),
        "unit": unit,
        "criticality": criticality,
        "source_data": source_data,
        "transformation": transformation,
        "final_variable": final_variable,
        "formula": formula,
        "pipeline": pipeline,
        "interpretation": interpretation,
        "limitation": limitation,
        "state": state,
    }


def build_risk_metrics_df(
    *,
    latest_competencia: str,
    summary: dict[str, float | str | None],
    asset_history_df: pd.DataFrame,
    segment_latest_df: pd.DataFrame,
    subordination_history_df: pd.DataFrame,
    default_history_df: pd.DataFrame,
    event_summary_latest_df: pd.DataFrame,
) -> pd.DataFrame:
    del latest_competencia
    top_segment_label, top_segment_pct = _latest_top_segment(segment_latest_df)
    direitos_creditorios_monitoramento = _float_or_none(summary.get("inadimplencia_denominador"))
    if direitos_creditorios_monitoramento is None or direitos_creditorios_monitoramento <= 0:
        direitos_creditorios_monitoramento = _float_or_none(summary.get("direitos_creditorios"))
    del asset_history_df
    del subordination_history_df
    del default_history_df
    del event_summary_latest_df

    rows = [
        _metric_row(
            risk_block="Risco de crédito",
            risk_block_order=1,
            metric_id="inadimplencia_pct",
            label="Inadimplência observada (IME) / DCs",
            value=summary.get("inadimplencia_pct"),
            unit="%",
            criticality="critico",
            source_data="Base canônica de direitos creditórios + vencidos canônicos",
            transformation="Usa uma cascata única para DC total (malha de vencimento -> estoque granular -> agregado item 3) e outra para vencidos (VL_SOM_INAD_VENC -> aging -> agregados de APLIC_ATIVO).",
            final_variable="summary['inadimplencia_pct']",
            formula="inadimplencia_total / dc_total_canonico * 100",
            pipeline="Informe Mensal -> _build_dc_canonical_history_df -> _build_default_history -> _build_summary -> summary['inadimplencia_pct']",
            interpretation="Mostra o peso dos créditos vencidos dentro do total de direitos creditórios reportado na mesma malha de vencimento.",
            limitation="Depende do preenchimento consistente dos quadros de vencidos e prazo pelo administrador; não substitui perda esperada nem leitura por devedor.",
            state="calculado" if summary.get("inadimplencia_pct") is not None else "nao_calculavel",
        ),
        _metric_row(
            risk_block="Risco de crédito",
            risk_block_order=1,
            metric_id="provisao_pct_direitos",
            label="Provisão / direitos creditórios",
            value=_safe_pct(summary.get("provisao_total"), direitos_creditorios_monitoramento),
            unit="%",
            criticality="monitorar",
            source_data="APLIC_ATIVO + base canônica de direitos creditórios",
            transformation="Soma da provisão reportada em _build_default_history.",
            final_variable="tracking_latest_df['Provisão / direitos creditórios']",
            formula="provisao_total / dc_total_canonico * 100",
            pipeline="Informe Mensal -> _build_dc_canonical_history_df -> _build_default_history -> build_risk_metrics_df",
            interpretation="Mostra quanto da carteira está coberto por provisão contábil reportada.",
            limitation="Depende da política contábil do fundo e não equivale a perda econômica realizada.",
            state="calculado" if _safe_pct(summary.get('provisao_total'), direitos_creditorios_monitoramento) is not None else "nao_calculavel",
        ),
        _metric_row(
            risk_block="Risco de crédito",
            risk_block_order=1,
            metric_id="provisao_pct_inadimplencia",
            label="Provisão / vencidos totais",
            value=_safe_pct(summary.get("provisao_total"), summary.get("inadimplencia_total")),
            unit="%",
            criticality="monitorar",
            source_data="APLIC_ATIVO/CRED_EXISTE + APLIC_ATIVO/DICRED",
            transformation="Relação entre provisão reportada e saldos vencidos observáveis; usa a malha de vencimento antes dos agregados de inadimplência.",
            final_variable="tracking_latest_df['Provisão / vencidos totais']",
            formula="provisao_total / inadimplencia_total * 100",
            pipeline="Informe Mensal -> _build_default_history -> default_history_df.[provisao_total, inadimplencia_total] -> build_risk_metrics_df",
            interpretation="Mostra o quanto dos vencidos totais observáveis está provisionado.",
            limitation="Sem vencidos observáveis a métrica não se aplica; também não captura recompras ou resolução de cessão.",
            state=(
                "calculado"
                if _safe_pct(summary.get("provisao_total"), summary.get("inadimplencia_total")) is not None
                else "nao_aplicavel_sem_inadimplencia"
            ),
        ),
        _metric_row(
            risk_block="Risco de crédito",
            risk_block_order=1,
            metric_id="concentracao_segmento_proxy",
            label=f"Concentração setorial proxy ({top_segment_label or 'N/D'})",
            value=top_segment_pct,
            unit="%",
            criticality="monitorar",
            source_data="CART_SEGMT",
            transformation="Seleciona o maior percentual do quadro setorial da CVM.",
            final_variable="segment_latest_df.iloc[0]['percentual']",
            formula="max(percentual_setorial)",
            pipeline="Informe Mensal -> _build_segment_latest_df -> segment_latest_df.percentual -> build_risk_metrics_df",
            interpretation="Sinal rápido de concentração da carteira pelo maior segmento reportado.",
            limitation="Não é concentração por devedor, cedente ou sacado; serve apenas como sinal preliminar.",
            state="calculado" if top_segment_pct is not None else "nao_disponivel_na_fonte",
        ),
        _metric_row(
            risk_block="Risco estrutural",
            risk_block_order=2,
            metric_id="subordinacao_pct",
            label="Subordinação reportada (IME)",
            value=summary.get("subordinacao_pct"),
            unit="%",
            criticality="critico",
            source_data="OUTRAS_INFORM/DESC_SERIE_CLASSE",
            transformation="Calcula PL mezzanino, PL subordinado residual e PL total a partir de qt. de cotas * valor da cota.",
            final_variable="summary['subordinacao_pct']",
            formula="(pl_mezzanino + pl_subordinada_strict) / pl_total * 100",
            pipeline="Informe Mensal -> _build_quota_pl_history -> _build_subordination_history -> _build_summary",
            interpretation="Mostra o colchão subordinado disponível antes da classe sênior, preservando mezzanino separado nas demais visões estruturais.",
            limitation="Não substitui covenants contratuais de cobertura, overcollateral ou subordinação mínima documental.",
            state="calculado" if summary.get("subordinacao_pct") is not None else "nao_calculavel",
        ),
        _metric_row(
            risk_block="Risco estrutural",
            risk_block_order=2,
            metric_id="pl_mezzanino",
            label="PL mezzanino reportado",
            value=summary.get("pl_mezzanino"),
            unit="R$",
            criticality="monitorar",
            source_data="OUTRAS_INFORM/DESC_SERIE_CLASSE",
            transformation="Soma o PL das classes identificadas como mezzanino a partir de qt. de cotas * valor da cota.",
            final_variable="summary['pl_mezzanino']",
            formula="Σ(qt_cotas_mezzanino * valor_cota_mezzanino)",
            pipeline="Informe Mensal -> _build_quota_pl_history -> _build_subordination_history -> _build_summary",
            interpretation="Mostra o volume nominal da camada mezzanino, segregada da subordinada residual.",
            limitation="Depende da identificação textual consistente das classes mezzanino no Informe Mensal.",
            state="calculado" if summary.get("pl_mezzanino") is not None else "nao_calculavel",
        ),
        _metric_row(
            risk_block="Risco estrutural",
            risk_block_order=2,
            metric_id="pl_subordinada",
            label="PL subordinado reportado",
            value=summary.get("pl_subordinada"),
            unit="R$",
            criticality="monitorar",
            source_data="OUTRAS_INFORM/DESC_SERIE_CLASSE",
            transformation="Soma PL mezzanino e PL subordinado residual a partir de qt. de cotas * valor da cota.",
            final_variable="summary['pl_subordinada']",
            formula="pl_mezzanino + pl_subordinada_strict",
            pipeline="Informe Mensal -> _build_quota_pl_history -> _build_subordination_history -> _build_summary",
            interpretation="Mostra o volume nominal do colchão subordinado reportado usado na subordinação canônica.",
            limitation="Não capta sozinha reforços estruturais extras como reservas, cobertura ou spread excedente.",
            state="calculado" if summary.get("pl_subordinada") is not None else "nao_calculavel",
        ),
    ]
    return pd.DataFrame(rows).sort_values(["risk_block_order", "criticality", "label"]).reset_index(drop=True)


def build_coverage_gap_df() -> pd.DataFrame:
    rows = [
        {
            "tema": "Índice de cobertura",
            "status": "Exige fonte complementar",
            "por_que_importa": "Ajuda a avaliar proteção econômica da classe sênior além da subordinação nominal.",
            "fonte_necessaria": "Regulamento + relatório mensal/monitoramento",
        },
        {
            "tema": "Relação mínima e covenants equivalentes",
            "status": "Exige fonte complementar",
            "por_que_importa": "Pode antecipar eventos de avaliação e deterioração estrutural.",
            "fonte_necessaria": "Regulamento + relatório mensal/monitoramento",
        },
        {
            "tema": "Reservas e excesso de spread",
            "status": "Exige fonte complementar",
            "por_que_importa": "São amortecedores relevantes para cotas seniores e não aparecem de forma padronizada no Informe Mensal.",
            "fonte_necessaria": "Regulamento + relatório mensal/monitoramento",
        },
        {
            "tema": "Cedente, originador, devedor e coobrigação",
            "status": "Exige fonte complementar",
            "por_que_importa": "São determinantes do risco operacional e da leitura correta do crédito.",
            "fonte_necessaria": "Relatório mensal + regulamento + documentos de oferta",
        },
        {
            "tema": "Eventos de avaliação e liquidação antecipada",
            "status": "Exige fonte complementar",
            "por_que_importa": "O Informe Mensal não reconstrói sozinho a malha de gatilhos contratuais da estrutura.",
            "fonte_necessaria": "Regulamento + fatos relevantes + assembleias",
        },
        {
            "tema": "Rating e público-alvo",
            "status": "Exige fonte complementar",
            "por_que_importa": "Importa para a leitura da tranche e da oferta, mas não deve ser inferido do Informe Mensal.",
            "fonte_necessaria": "Documentos de oferta + relatórios de rating + regulamento",
        },
        {
            "tema": "Verificação de lastro",
            "status": "Exige fonte complementar",
            "por_que_importa": "Afeta risco operacional e qualidade da carteira além do que o Informe Mensal mostra.",
            "fonte_necessaria": "Regulamento + ofícios CVM + relatórios operacionais",
        },
    ]
    return pd.DataFrame(rows)


def build_mini_glossary_df() -> pd.DataFrame:
    rows = [
        {
            "termo": "Subordinação reportada (IME)",
            "definicao": (
                "Percentual do PL alocado no colchão subordinado reportado, calculado como "
                "(PL mezzanino + PL subordinada residual) / PL total. "
                "Essas cotas absorvem perdas de crédito antes da classe sênior, funcionando como colchão. "
                "Quanto maior, mais protegido o sênior — mas o nível adequado depende da carteira e do regulamento."
            ),
        },
        {
            "termo": "Inadimplência (IME)",
            "definicao": (
                "Saldo vencido reportado pelo administrador no campo INAD_VENC do Informe Mensal. "
                "Reflete o estoque de crédito em atraso por faixa de prazo. "
                "Não é necessariamente perda: parte pode ser recuperada ou estar em negociação."
            ),
        },
        {
            "termo": "Cobertura de provisão",
            "definicao": (
                "Relação entre a provisão constituída e o saldo inadimplente reportado. "
                "Acima de 100%: o fundo provisionou mais do que o inadimplente visível. "
                "Abaixo de 100%: parte da inadimplência ainda não está coberta por provisão. "
                "No painel executivo, essa linha usa apenas o estoque vencido como denominador, não o total de direitos creditórios."
            ),
        },
        {
            "termo": "Aging da inadimplência",
            "definicao": (
                "Distribuição não cumulativa do saldo vencido por faixa de prazo "
                "(até 30, 31–60, 61–90, 91–120, 121–150, 151–180, 181–360, 361–720, 721–1080 e acima de 1080 dias). "
                "Faixas mais longas indicam créditos com menor probabilidade de recuperação e maior pressão sobre o colchão. "
                "No painel executivo, o eixo percentual do aging usa o próprio estoque inadimplente como denominador. "
                "Esse conceito é diferente das curvas Over, que são cumulativas e usam os direitos creditórios totais."
            ),
        },
        {
            "termo": "Inadimplência Over",
            "definicao": (
                "Curvas cumulativas de atraso em relação aos direitos creditórios totais. "
                "Over 1 inclui todos os atrasos a partir de 1 dia; Over 30, Over 60, Over 90 e demais cortes "
                "somam apenas os buckets vencidos acima do respectivo threshold. "
                "É diferente do aging, que reparte o estoque vencido por faixa sem acumular."
            ),
        },
        {
            "termo": "Direitos creditórios",
            "definicao": (
                "Recebíveis que compõem a carteira do FIDC — duplicatas, CCBs, precatórios, contratos, etc. "
                "São o ativo principal do fundo. No painel, o total usa uma base canônica única em cascata "
                "(malha de vencimento -> estoque granular -> agregado item 3) e serve de denominador para os indicadores de crédito."
            ),
        },
        {
            "termo": "Informe Mensal Estruturado (IME)",
            "definicao": (
                "Documento XML entregue mensalmente pelos administradores à CVM via Fundos.NET. "
                "É a fonte primária deste painel. Cobre PL, cotas, inadimplência, provisão, amortizações e emissões. "
                "Não cobre qualidade do cedente, concentração por devedor, rating ou triggers contratuais."
            ),
        },
        {
            "termo": "Resgate solicitado",
            "definicao": (
                "Volume de resgates pedidos por cotistas no mês, ainda não necessariamente liquidados. "
                "Sinal de pressão de saída. Comparar com a liquidez da carteira para avaliar risco de liquidez."
            ),
        },
    ]
    return pd.DataFrame(rows)


def build_current_dashboard_inventory_df() -> pd.DataFrame:
    rows = [
        {
            "nome_variavel": "fund_info.*",
            "nome_exibido": "Cabeçalho e barra de contexto",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Cabeçalho / contexto",
            "fonte_dado": "CAB_INFORM + cadastro CVM complementar",
            "formula": "_build_fund_info",
            "arquivo_py": "services/fundonet_dashboard.py:_build_fund_info; tabs/tab_fidc_ime.py:_render_dashboard_header/_render_dashboard_context_bar",
            "tipo": "metadado",
            "unidade": "texto e datas",
        },
        {
            "nome_variavel": "summary.ativos_totais|summary.direitos_creditorios|summary.pl_total|summary.pl_subordinada",
            "nome_exibido": "Cards financeiros de topo",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Topo da página",
            "fonte_dado": "APLIC_ATIVO + base canônica de DC + DESC_SERIE_CLASSE",
            "formula": "_build_summary",
            "arquivo_py": "services/fundonet_dashboard.py:_build_summary; tabs/tab_fidc_ime.py:_render_financial_snapshot_cards",
            "tipo": "cards_monetarios",
            "unidade": "R$",
        },
        {
            "nome_variavel": "summary.direitos_creditorios",
            "nome_exibido": "Direitos creditórios totais",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Base comum / topo / crédito",
            "fonte_dado": "Base canônica: malha de vencimento -> estoque granular -> agregado item 3",
            "formula": "_build_dc_canonical_history_df -> _build_asset_history -> _build_summary",
            "arquivo_py": "services/fundonet_dashboard.py:_build_dc_canonical_history_df; tabs/tab_fidc_ime.py:_render_calculation_memory_section",
            "tipo": "monetaria",
            "unidade": "R$",
        },
        {
            "nome_variavel": "summary.pl_total",
            "nome_exibido": "PL total",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Topo da página / Estrutura",
            "fonte_dado": "DESC_SERIE_CLASSE",
            "formula": "_build_quota_pl_history -> _build_subordination_history -> _build_summary",
            "arquivo_py": "services/fundonet_dashboard.py:_build_subordination_history; tabs/tab_fidc_ime.py:_render_financial_snapshot_cards",
            "tipo": "monetaria",
            "unidade": "R$",
        },
        {
            "nome_variavel": "summary.subordinacao_pct",
            "nome_exibido": "Subordinação reportada (IME)",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Radar de risco / Estrutura",
            "fonte_dado": "DESC_SERIE_CLASSE",
            "formula": "(pl_mezzanino + pl_subordinada_strict) / pl_total * 100",
            "arquivo_py": "services/fundonet_dashboard.py:_build_subordination_history; tabs/tab_fidc_ime.py:_render_risk_overview/_render_structural_risk_section",
            "tipo": "percentual",
            "unidade": "%",
        },
        {
            "nome_variavel": "summary.inadimplencia_pct",
            "nome_exibido": "Inadimplência observada (IME) / DCs",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Radar de risco / Crédito",
            "fonte_dado": "Vencidos canônicos + base canônica de direitos creditórios",
            "formula": "inadimplencia_total / dc_total_canonico * 100",
            "arquivo_py": "services/fundonet_dashboard.py:_build_default_history; tabs/tab_fidc_ime.py:_render_risk_overview/_render_credit_risk_section",
            "tipo": "percentual",
            "unidade": "%",
        },
        {
            "nome_variavel": "risk_metrics_df.*",
            "nome_exibido": "Cards e tabela do radar de risco",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Radar de risco / tabelas laterais",
            "fonte_dado": "Summary + default_history + segment_latest + quota_pl_history",
            "formula": "build_risk_metrics_df",
            "arquivo_py": "services/fidc_monitoring.py:build_risk_metrics_df; tabs/tab_fidc_ime.py:_render_risk_overview/_format_risk_metrics_table",
            "tipo": "metricas_derivadas",
            "unidade": "mista",
        },
        {
            "nome_variavel": "default_history_df.[inadimplencia_pct, provisao_total/dc_total_canonico] + cobertura(provisao_total/dc_vencidos)",
            "nome_exibido": "Inadimplência, provisão e cobertura",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Crédito",
            "fonte_dado": "COMPMT_DICRED_* + APLIC_ATIVO + base canônica",
            "formula": "_build_default_history + _default_ratio_chart_frame + _default_cobertura_chart_frame",
            "arquivo_py": "services/fundonet_dashboard.py:_build_default_history; tabs/tab_fidc_ime.py:_render_credit_risk_section",
            "tipo": "grafico_combinado",
            "unidade": "% dos DCs e % de cobertura",
        },
        {
            "nome_variavel": "default_over_history_df.percentual",
            "nome_exibido": "Inadimplência Over",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Crédito",
            "fonte_dado": "Buckets VL_INAD_VENC_* + base canônica de direitos creditórios",
            "formula": "_build_default_over_history_df",
            "arquivo_py": "services/fundonet_dashboard.py:_build_default_over_history_df; tabs/tab_fidc_ime.py:_render_credit_risk_section",
            "tipo": "serie_historica_cumulativa",
            "unidade": "%",
        },
        {
            "nome_variavel": "default_aging_history_df.percentual_inadimplencia",
            "nome_exibido": "Aging da inadimplência",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Crédito",
            "fonte_dado": "COMPMT_DICRED_AQUIS + COMPMT_DICRED_SEM_AQUIS",
            "formula": "_build_default_aging_history_df",
            "arquivo_py": "services/fundonet_dashboard.py:_build_default_aging_history_df; tabs/tab_fidc_ime.py:_render_credit_risk_section",
            "tipo": "bucket_percentual",
            "unidade": "% da inadimplência",
        },
        {
            "nome_variavel": "quota_pl_history_df.*",
            "nome_exibido": "PL por tipo de cota",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Estrutura",
            "fonte_dado": "OUTRAS_INFORM/DESC_SERIE_CLASSE",
            "formula": "_build_quota_pl_history com macroclasse derivada (Sênior / Mezzanino / Subordinada)",
            "arquivo_py": "services/fundonet_dashboard.py:_build_quota_pl_history; tabs/tab_fidc_ime.py:_render_structural_risk_section",
            "tipo": "serie_historica",
            "unidade": "R$ e %",
        },
        {
            "nome_variavel": "event_summary_latest_df.*",
            "nome_exibido": "Resumo dos eventos de cotas",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Eventos de cotas",
            "fonte_dado": "CAPTA_RESGA_AMORTI",
            "formula": "_build_event_summary_latest_df",
            "arquivo_py": "services/fundonet_dashboard.py:_build_event_summary_latest_df; tabs/tab_fidc_ime.py:_render_liquidity_risk_section",
            "tipo": "tabela_evento",
            "unidade": "R$ e % do PL",
        },
        {
            "nome_variavel": "maturity_latest_df.*",
            "nome_exibido": "Prazo de vencimento dos direitos creditórios",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Vencimento dos direitos creditórios",
            "fonte_dado": "COMPMT_DICRED_AQUIS + COMPMT_DICRED_SEM_AQUIS",
            "formula": "_build_maturity_latest_df",
            "arquivo_py": "services/fundonet_dashboard.py:_build_maturity_latest_df; tabs/tab_fidc_ime.py:_render_liquidity_risk_section",
            "tipo": "bucket",
            "unidade": "R$",
        },
        {
            "nome_variavel": "duration_history_df.duration_days",
            "nome_exibido": "Prazo médio proxy dos recebíveis (IME)",
            "aba_origem": "Visão executiva",
            "bloco_ui_atual": "Prazo médio proxy dos recebíveis (IME)",
            "fonte_dado": "maturity_history_df",
            "formula": "_build_duration_history_df",
            "arquivo_py": "services/fundonet_dashboard.py:_build_duration_history_df; tabs/tab_fidc_ime.py:_render_duration_section",
            "tipo": "prazo_estimado",
            "unidade": "dias",
        },
        {
            "nome_variavel": "executive_memory_df|dc_canonical_history_df|consistency_audit_df",
            "nome_exibido": "Rodapé técnico da aba",
            "aba_origem": "Visão executiva / Auditoria técnica",
            "bloco_ui_atual": "Memória de cálculo / base auditável",
            "fonte_dado": "Builders auditáveis do dashboard",
            "formula": "_build_executive_memory_df + _build_consistency_audit_df",
            "arquivo_py": "services/fundonet_dashboard.py:_build_executive_memory_df/_build_consistency_audit_df; tabs/tab_fidc_ime.py:_render_calculation_memory_section/_render_audit_section",
            "tipo": "auditoria",
            "unidade": "tabelas",
        },
        {
            "nome_variavel": "summary.alocacao_pct",
            "nome_exibido": "Alocação em direitos creditórios",
            "aba_origem": "Auditoria técnica",
            "bloco_ui_atual": "Métricas auxiliares",
            "fonte_dado": "VL_CARTEIRA + base canônica de direitos creditórios",
            "formula": "direitos_creditorios / carteira * 100",
            "arquivo_py": "services/fundonet_dashboard.py:_build_asset_history; services/fundonet_dashboard.py:_build_tracking_latest_df",
            "tipo": "percentual",
            "unidade": "%",
        },
    ]
    return pd.DataFrame(rows)
