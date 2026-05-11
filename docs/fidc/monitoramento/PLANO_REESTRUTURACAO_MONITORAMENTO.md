# Plano de Reestruturação do Monitoramento FIDC

Data: 11/04/2026

## Objetivo

Transformar a aba de IME em um painel de monitoramento de risco utilizável por comprador de cotas seniores, com reconciliação explícita entre dado bruto, transformação, output e limitação.

## Estrutura-alvo da aba

### 1. Contexto do fundo

- identificação do fundo/classe
- CNPJ do fundo e do administrador
- última competência
- janela analisada
- quantidade de IMEs processados

### 2. Radar de risco

Cards de leitura rápida para:

- subordinação
- inadimplência relativa
- alocação em direitos creditórios
- liquidez até 30 dias
- liquidez imediata
- resgate solicitado
- quantidade de camadas críticas fora do IME

### 3. Risco de crédito

- tabela curta com métrica, fonte, leitura e limitação
- concentração setorial proxy
- histórico de inadimplência, provisão e pendências
- aging da inadimplência

### 4. Risco estrutural

- subordinação
- alocação
- PL subordinado
- histórico de subordinação
- PL por classe
- benchmark x realizado das cotas

### 5. Risco de liquidez e funding

- liquidez imediata
- liquidez até 30 dias
- resgate solicitado
- amortização, resgate pago e emissão como `% PL`
- vencimento dos direitos creditórios
- fluxo de aquisições e alienações
- eventos de cotas com sinal econômico preservado

### 6. Risco operacional e contratual

- tabela de gaps do IME
- mini-glossário contextual
- aviso explícito do que exige regulamento, rating, relatório mensal ou documento de oferta

### 7. Memória de cálculo e evidência

- tabela de memória de cálculo das métricas exibidas
- inventário do dashboard
- base CVM normalizada

## Camada canônica de monitoramento

Arquivo: `services/fidc_monitoring.py`

Responsabilidades:

- organizar métricas por bloco de risco
- registrar fonte, transformação e fórmula
- registrar interpretação e limitação
- expor gaps críticos fora do IME
- expor glossário curto contextual
- expor inventário auditável do dashboard

## Decisões de modelagem

### Métricas que permanecem explícitas como proxy

- inadimplência relativa
- provisão relativa
- concentração setorial
- liquidez do IME

### Métricas que não devem ser inferidas do IME

- cobertura
- relação mínima
- excesso de spread
- gatilhos contratuais
- coobrigação
- rating
- qualidade do lastro

### Regra de ausência

- UI: `N/D`
- memória de cálculo: estado explícito
- pipeline: preservar `NaN` antes da borda de apresentação
- proibido converter ausência em zero por conveniência analítica

## Arquivos alterados

- `app.py`
- `services/fundonet_dashboard.py`
- `services/fidc_monitoring.py`
- `tabs/tab_fidc_ime.py`
- `tests/test_fundonet_dashboard.py`

## Arquivos documentais criados

- `docs/fidc/monitoramento/DIAGNOSTICO_DASHBOARD_ATUAL.md`
- `docs/fidc/monitoramento/PLANO_REESTRUTURACAO_MONITORAMENTO.md`
- `docs/fidc/monitoramento/CHANGELOG_MONITORAMENTO_FIDC.md`

## Critérios de aceite

- a aba de monitoramento é a primeira aba do app
- o nome visível da aba é `tomaconta FIDCs`
- a leitura principal está organizada por blocos de risco
- cada métrica relevante tem memória de cálculo explícita
- ausência de dado não vira zero silencioso no histórico principal
- o usuário consegue distinguir IME, cálculo interno e gap documental
- o app continua com exportação PDF e testes passando
