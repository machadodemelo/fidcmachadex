# Changelog do Monitoramento FIDC

## 2026-04-11

### Adicionados

- `services/fidc_monitoring.py` como camada canônica de monitoramento por risco.
- `risk_metrics_df` com memória de cálculo explícita por métrica.
- `coverage_gap_df` para registrar camadas críticas fora do IME.
- `mini_glossary_df` para explicações curtas dentro da aba.
- `current_dashboard_inventory_df` para inventário auditável do dashboard.
- documentação em `docs/fidc/monitoramento/`.

### Atualizados

- `app.py`: a aba de monitoramento passou para a primeira posição e foi renomeada para `tomaconta FIDCs`.
- `tabs/tab_fidc_ime.py`: a UI foi reorganizada por blocos de risco, com paleta laranja/preto/cinza e toggle de data labels.
- `services/fundonet_dashboard.py`: a montagem do dashboard passou a alimentar a nova camada de monitoramento por risco.
- `tabs/tab_fidc_ime.py`: a camada visual foi aproximada da linguagem do Snapshot do `tomaconta`, com cards mais ricos, callouts analíticos por bloco e liquidez histórica na leitura de funding.
- `services/fidc_monitoring.py`: o bloco de liquidez ganhou métricas adicionais de aquisições, alienações e fluxo líquido sobre direitos creditórios.
- `services/fundonet_dashboard.py`: foi adicionada série histórica de liquidez para suportar leitura temporal e cards analíticos com sparkline.

### Correções de causa raiz

- remoção do padrão de colapsar ausência em zero nas séries históricas mais sensíveis antes da camada de apresentação;
- separação explícita entre dado IME, transformação de código, output e limitação;
- explicitação das camadas críticas que não podem ser inferidas do IME.

### Testes de regressão

- validação dos novos artefatos de monitoramento por risco;
- validação de preservação de `NaN` em histórico com ausência real de dado;
- suíte `unittest` integral mantendo `OK`.
