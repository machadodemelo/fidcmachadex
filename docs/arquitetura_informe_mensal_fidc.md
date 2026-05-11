# Estudo técnico — Coleta e disposição de dados CVM FIDC para Dashboard Streamlit

## Classificação
- Tipo: 🟡 Planejado (feature nova com arquitetura de dados, cache e escalabilidade multi-anos).

Fonte oficial de referência (dataset CVM):
- https://dados.cvm.gov.br/dataset/fidc-doc-inf_mensal/resource/e44f6341-9827-4599-baf3-ac5e298e55f7

## Etapa 0 — Diagnóstico (sem implementação)

### 0.1 Fontes e fatos confirmados
1. O Portal de Dados da CVM publica informes mensais FIDC por arquivo mensal (`inf_mensal_fidc_YYYYMM.zip`).
2. Existe dicionário de dados oficial (`meta_inf_mensal_fidc_txt.zip`).
3. Cada pacote mensal pode conter múltiplas planilhas/tabelas, com volume descompactado significativamente maior que o ZIP.
4. Há padrão de URL que permite ingestão automatizada e incremental por mês.

### 0.2 Chave de identificação do fundo (decisão de modelagem)
Para seleção no dashboard, manter identificadores separados e estáveis:
- `CNPJ_FUNDO` (normalizado para 14 dígitos, sem máscara) como chave canônica.
- `DENOM_SOCIAL` (nome) apenas para exibição e busca textual.
- `COD_CVM`/outro código oficial, quando disponível, como chave secundária para conferência.

### 0.3 Fluxo de dados recomendado (origem → transformação → UI/export)
1. **Ingestão bruta**: download mensal do ZIP CVM para armazenamento imutável (raw zone).
2. **Staging padronizado**: leitura das abas/tabelas em formato tabular uniforme, acrescentando metadados de referência (`ano_mes_ref`, `arquivo_origem`, `dt_ingestao`).
3. **Modelo analítico**: consolidação em tabelas por assunto (fundo, carteira, passivo, cotas, eventos) com partição mensal.
4. **Camada de serving**: dataset pronto para Streamlit com filtros por fundo/período e métricas já validadas.
5. **Export/monitoramento**: export bruto + formatado, e trilha de auditoria de execução.

### 0.4 Confirmações explícitas solicitadas (A–D)
A. **Nomes exatos das colunas usadas**: dependem do layout oficial do mês e devem ser derivados do dicionário (`meta_inf_mensal_fidc_txt.zip`) na etapa de parser; não devem ser hardcoded sem validação de contrato.

B. **Estágio 2 e Estágio 3 agregados ou separados**: para esse projeto FIDC (informe mensal CVM), os campos de risco/qualidade devem ser verificados no dicionário e nos layouts reais antes de qualquer cálculo; assumir agregado/separado sem inspeção é risco.

C. **Risco de períodos inconsistentes**: alto se misturar meses de snapshots diferentes (ex.: atualização parcial do mês corrente). Mitigação: watermark mensal fechado (`YYYYMM`) e regra de reprocessamento idempotente.

D. **Tratamento especial da métrica atual**: qualquer regra especial existente (ex.: winsorização, exclusão de nulos, filtro de ativo) deve ser registrada em função única reutilizável; sem isso, risco de divergência entre UI e export.

## Etapa 1 — Causa raiz / riscos

### 1.1 Riscos arquiteturais principais
- **Quebra por mudança de schema**: variação de colunas/tipos entre meses.
- **Concatenação frágil**: união por nome de coluna sem mapeamento versionado.
- **Duplicidade/reprocessamento**: carga repetida do mesmo mês sem deduplicação por chave natural.
- **NaN e divisão por zero**: métricas podem gerar infinito/0 indevido se não houver política explícita.
- **Acoplamento UI↔ETL**: cálculo no Streamlit sem camada semântica central causa regressão futura.

### 1.2 Guardrails de engenharia
1. Não implementar métrica sem confirmar origem e definição no dicionário oficial.
2. Não hardcodar nomes de colunas sem camada de mapeamento/versionamento.
3. Não usar fallback silencioso para colunas ausentes; falhar com erro explicativo.
4. Não alterar fórmulas existentes sem teste de regressão comparando períodos.
5. Inserções de novas métricas devem preservar ordenação/layout/export.
6. Denominador zero ⇒ `NaN` (exibir `N/D` na UI; vazio no export), nunca `0`/`inf`.
7. Todas as métricas em função única reutilizável (evitar lógica duplicada entre abas).
8. Validar coerência mínima (ex.: relação esperada entre métricas correlatas) antes de publicar.

## Etapa 2 — Plano técnico (proposta)

### 2.1 Estrutura de armazenamento (escalável para 5+ anos)
- **Raw (imutável)**: `data/raw/cvm/fidc_inf_mensal/ano=YYYY/mes=MM/*.zip`
- **Bronze (normalizado por tabela)**: Parquet particionado por `ano_mes_ref` e `tabela`.
- **Silver (modelo analítico)**: tabelas limpas e tipadas por domínio.
- **Gold (dashboard)**: visão otimizada para consultas do Streamlit.

### 2.2 Estratégia de atualização
- Scheduler mensal (ou sob demanda) detecta novo `YYYYMM`.
- Pipeline idempotente por partição mensal.
- Reprocessamento controlado de janelas (ex.: últimos 3 meses) para capturar retificações.
- Controle de versão de schema por hash de colunas + tipos.

### 2.3 Cache/API recomendados
- **Curto prazo (MVP)**: cache local com Parquet + `st.cache_data` no Streamlit.
- **Médio prazo**: DuckDB local/objeto para analytics sobre arquivos.
- **Longo prazo**: Postgres/Supabase para entidades mestres + DuckDB/Parquet para séries volumosas.
- API opcional apenas quando houver múltiplos consumidores; evitar API prematura.

### 2.4 Contratos para evitar quebra futura
- Data contract por tabela: colunas obrigatórias, tipos, chaves, semântica.
- Testes automáticos de contrato em toda carga.
- Registro de qualidade por execução (`run_id`, linhas lidas, linhas válidas, colunas novas/faltantes).

## Etapa 3 — Implementação (planejada, não executada nesta fase)
1. Implementar módulo de ingestão mensal CVM (download + checksum + armazenamento raw).
2. Implementar parser tabular orientado por dicionário de dados.
3. Persistir Parquet particionado e camada de views para dashboard.
4. Construir seletor de fundo no Streamlit por CNPJ/nome.
5. Expor métricas com guardrails e validações de consistência.

## Etapa 4 — Validação obrigatória (definição)
- Conferir 2–3 fundos com histórico de 12 meses comparando totais contra fonte CVM.
- Testar caso com coluna ausente para garantir erro explícito (sem fallback silencioso).
- Testar denominador zero em métricas derivadas (`NaN`/`N/D`).
- Validar paridade UI↔export (mesma ordem, mesma lógica, formatação BR na UI).

## Recomendação final (primeiro passo prático)
Começar com um **MVP incremental por mês em Parquet + DuckDB**, com `CNPJ_FUNDO` como chave canônica e validação por dicionário oficial. Essa abordagem minimiza risco de quebra de atualização, escala bem para 5 anos e mantém o Streamlit responsivo sem exigir API complexa no início.
