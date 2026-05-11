# Auditoria Técnica do Dashboard FIDC

Data: 2026-04-23  
Escopo: dashboard online, modo carteira, consolidação multi-FIDC, UX analítica e exportação PPT.

## 1. Escopo auditado

Arquivos e camadas revisados nesta passada:

- `app.py`
- `tabs/tab_fidc_ime.py`
- `tabs/tab_fidc_ime_carteira.py`
- `tabs/ime_portfolio_support.py`
- `services/ime_loader.py`
- `services/fundonet_service.py`
- `services/fundonet_dashboard.py`
- `services/fundonet_portfolio_dashboard.py`
- `services/portfolio_store.py`
- `services/fundonet_export.py`
- `services/fundonet_pdf_export.py`
- `services/fundonet_ppt_export.py`
- `tests/test_fundonet_dashboard.py`
- `tests/test_fundonet_portfolio_dashboard.py`
- `tests/test_tab_fidc_ime_carteira.py`
- `tests/test_portfolio_store.py`

## 2. Mapeamento estrutural consolidado

### 2.1 Fluxo de dados do Informe Mensal Estruturado

1. `services/fundonet_service.py`
   - lista documentos no Fundos.NET
   - deduplica retificações
   - baixa XMLs e normaliza a base
   - gera `informes_wide.csv`, `estruturas_lista.csv`, `documentos_filtrados.csv`

2. `services/ime_loader.py`
   - persiste e reabre extrações em cache por chave de período + CNPJ

3. `services/fundonet_dashboard.py`
   - constrói o contrato analítico single-fund (`FundonetDashboardData`)
   - monta cards, históricos, buckets, bases canônicas, memória e auditoria

4. `tabs/tab_fidc_ime.py`
   - renderiza a visão individual
   - separa visão executiva e auditoria técnica

5. `services/fundonet_portfolio_dashboard.py`
   - monta a visão agregada multi-CNPJ
   - usa interseção estrita de competências
   - soma bases monetárias homogêneas
   - recalcula percentuais a partir de numeradores/denominadores agregados

6. `tabs/tab_fidc_ime_carteira.py`
   - persiste seleção de fundos
   - carrega resultados já extraídos
   - alterna entre `Carteira agregada` e `Fundo individual`

### 2.2 Regras metodológicas relevantes

- Visão carteira usa interseção estrita das competências comuns.
- Volumes monetários homogêneos são somados.
- Percentuais não são somados; são reconstruídos.
- `Mezzanino` permanece separado visualmente em PL, mas entra no numerador da subordinação reportada.
- `Prazo médio` da carteira usa apenas buckets a vencer.
- Eventos de cotas são desabilitados quando a última competência comum diverge da última competência individual de qualquer fundo.

## 3. Achados principais da auditoria

### 3.1 Persistência e seleção de carteiras

Achado confirmado na base salva (`portfolios.json`):

- existem duas seleções salvas com o mesmo nome `Mercado Credito Soma`
- ambas possuem a mesma cesta de CNPJs:
  - `33254370000104`
  - `37511828000114`
  - `41970012000126`
- os ids duplicados são:
  - `57f3418c1e9341e79edeef6086b8c25d`
  - `4220dda141ea442abd86a6ee11ed249f`

Risco:

- seletor ambíguo
- falsa percepção de quebra na troca da seleção ativa
- chance de o usuário salvar a mesma cesta repetidas vezes sem perceber

### 3.2 Consolidação multi-FIDC

Pontos validados:

- `PL total`, `PL mezzanino`, `PL subordinado`, `ativos`, `carteira`, `direitos creditórios`, `inadimplência`, `provisão`, `liquidez` e buckets monetários são agregados por soma.
- `subordinação`, `inadimplência %`, `provisão/DC`, `cobertura` e `Over` são recalculados.
- a malha já era estrita em relação à competência, mas faltava um quadro explícito de reconciliação entre:
  - valor base esperado
  - valor efetivamente renderizado em `summary`
  - reconciliação da malha de vencimento com `dc_a_vencer_canonico`
  - reconciliação dos buckets de aging com `inadimplência_total`

Risco original:

- a carteira já era metodologicamente melhor do que uma soma simples, mas a rastreabilidade do número final ainda dependia demais de leitura manual de dataframes internos.

### 3.2.1 Validação operacional da cesta `Mercado Credito Soma`

Depois do reforço do motor, a cesta salva foi executada no próprio pipeline do projeto com os três CNPJs:

- `33254370000104`
- `37511828000114`
- `41970012000126`

Resultado observado na execução:

- `11` competências carregadas por fundo
- última competência comum: `03/2026`
- `coverage_df` sem blocos incompletos
- `reconciliation_df` totalmente alinhado nas métricas críticas

Resumo da competência comum mais recente validada:

- ativo total agregado: `R$ 5.181.672.636,38`
- carteira agregada: `R$ 5.088.830.620,53`
- direitos creditórios agregados: `R$ 7.676.589.879,34`
- PL total agregado: `R$ 5.116.580.554,34`
- subordinação reportada: `56,60%`
- inadimplência total: `R$ 1.472.341.466,99`
- inadimplência %: `19,18%`
- provisão total: `R$ 2.702.368.565,08`
- cobertura: `183,54%`

Conclusão operacional:

- o consolidado real da cesta `Mercado Credito Soma` fechou consistente na competência comum mais recente no ambiente desta auditoria
- os checks críticos de reconciliação ficaram todos com status `Alinhado`

### 3.3 Redundâncias de UX

Achado:

- a visão executiva tinha memória de cálculo e, dentro dela, um expander de auditoria complementar que repetia consistência, base canônica e inventário já presentes na aba técnica.

Risco:

- repetição informacional
- sensação de painel “mais pesado” do que o necessário
- maior custo de leitura sem ganho analítico proporcional

### 3.4 PPT export

Achado desta passada:

- o export atual ainda usa múltiplos gráficos por slide em alguns casos, por escolha de densidade narrativa.
- havia uso excessivo de legenda manual em text boxes mesmo em gráficos que suportam legenda nativa do Office.

Risco:

- pior editabilidade para analistas
- maior sensação de “montagem” visual em vez de gráfico Office-native

## 4. Correções implementadas

### 4.1 Persistência / seleção

Arquivos:

- `services/portfolio_store.py`
- `tabs/tab_fidc_ime_carteira.py`
- `tests/test_portfolio_store.py`
- `tests/test_tab_fidc_ime_carteira.py`

Mudanças:

- criada assinatura canônica da cesta (`portfolio_basket_signature`)
- criada chave normalizada de nome (`portfolio_name_key`)
- bloqueio de novas duplicatas exatas: mesmo nome + mesma cesta
- seletor da carteira agora desambigua colisões:
  - quando houver duplicata exata: `Nome · N fundos · idcurto`
  - quando houver apenas colisão de nome: `Nome · N fundos`

Resultado:

- o caso `Mercado Credito Soma` deixa de ficar indistinguível no seletor
- novas duplicatas exatas deixam de ser persistidas

### 4.2 Reconciliação formal do consolidado

Arquivos:

- `services/fundonet_portfolio_dashboard.py`
- `tabs/tab_fidc_ime_carteira.py`
- `tests/test_fundonet_portfolio_dashboard.py`

Mudanças:

- `PortfolioDashboardBundle` passou a expor `reconciliation_df`
- a carteira agora produz uma tabela formal de reconciliação com:
  - componente
  - unidade
  - esperado
  - renderizado
  - delta
  - origem
  - fórmula
  - status

Coberturas implementadas:

- ativo total
- carteira
- direitos creditórios
- PL total
- PL mezzanino
- PL subordinado reportado
- subordinação %
- inadimplência total
- provisão total
- inadimplência %
- provisão / DC
- cobertura %
- liquidez imediata
- liquidez 30 dias
- buckets a vencer vs `dc_a_vencer_canonico`
- aging vs inadimplência total

Resultado:

- a auditoria técnica da carteira passou a mostrar explicitamente o número esperado contra o número renderizado
- divergências reais deixaram de ficar implícitas

### 4.3 Consistência adicional do bloco carteira

Arquivo:

- `services/fundonet_portfolio_dashboard.py`

Mudanças:

- `consistency_audit_df` da carteira passou a incluir reconciliação explícita de:
  - malha de vencimento vs `dc_a_vencer_canonico`
  - malha de aging vs `inadimplência_total`

### 4.4 Simplificação da visão online

Arquivo:

- `tabs/tab_fidc_ime.py`

Mudança:

- removido o expander `Auditoria complementar da aba` de dentro da memória de cálculo da visão executiva

Racional:

- a aba técnica já concentrava consistência, inventário e base canônica
- a repetição na visão executiva aumentava ruído sem acrescentar rastreabilidade

### 4.5 PPT export

Arquivo:

- `services/fundonet_ppt_export.py`

Mudanças:

- onde o gráfico suporta legenda nativa do Office, a exportação passou a privilegiar essa legenda em vez de legenda manual:
  - `PL por tipo de cota`
  - `Índice acumulado base 100`
  - `Inadimplência Over`
- estilização da legenda nativa alinhada à tipografia do deck
- redistribuição de altura útil dos gráficos após remoção da legenda manual nesses casos

Resultado:

- melhora de editabilidade e leitura
- menor dependência de text boxes manuais para explicar séries já conhecidas pelo próprio chart

## 5. Testes criados ou ampliados

### 5.1 Persistência / duplicidade

- `test_portfolio_basket_signature_is_order_insensitive`
- `test_local_store_rejects_duplicate_name_and_same_basket`

### 5.2 Seletor da carteira

- `test_build_portfolio_selector_label_lookup_disambiguates_duplicate_name_and_basket`

### 5.3 Consolidação / reconciliação

- `test_build_portfolio_dashboard_bundle_recalculates_subordination_duration_and_over`
  - expandido para validar `reconciliation_df`
- `test_build_portfolio_dashboard_bundle_handles_missing_long_frame_columns`
  - expandido para validar estado `Sem base` na reconciliação

## 6. Resultado dos testes nesta passada

Bateria validada:

- `tests.test_fundonet_dashboard`
- `tests.test_portfolio_store`
- `tests.test_tab_fidc_ime_carteira`
- `tests.test_fundonet_portfolio_dashboard`

Resultado:

- `28 tests OK`

## 7. Riscos remanescentes

1. A base salva ainda contém as duas seleções duplicadas históricas de `Mercado Credito Soma`.
   - a UI agora diferencia
   - novas duplicatas exatas são bloqueadas
   - mas a limpeza histórica do arquivo não foi feita automaticamente para evitar intervenção silenciosa sobre dados do usuário

2. A auditoria da cesta `Mercado Credito Soma` fechou bem na competência comum mais recente, mas continua dependendo de ambiente com acesso às extrações para reexecutar essa validação no futuro.
   - o motor agora está mais explícito e testado
   - a repetição futura da validação segue possível, mas não foi transformada nesta passada em teste automatizado de rede

3. O PPT ainda não foi convertido para uma arquitetura estritamente “um gráfico por slide”.
   - esta passada focou em reduzir legibilidade frágil sem descaracterizar a narrativa atual do deck
   - a exportação continua editável e mais Office-native do que antes, mas ainda pode evoluir mais nessa direção

## 8. Sugestões futuras deliberadamente não implementadas agora

1. Deduplicação automática do `portfolios.json`
   - não implementei para não apagar ou fundir seleções salvas silenciosamente

2. Redesenho completo do PPT com um gráfico por slide em todos os casos
   - possível, mas seria uma mudança mais drástica de narrativa do material exportado

3. Validador de consistência cruzada online x PPT x Excel em tempo de execução
   - útil, mas pesado demais para o caminho de renderização
   - melhor como suíte de teste offline / CI

4. Teste automatizado de integração online para a cesta `Mercado Credito Soma`
   - não implementei como teste de CI porque dependeria de rede e de fonte externa viva

## 9. Conclusão

Esta passada atacou a parte mais crítica sem descaracterizar a plataforma:

- reforçou a integridade do consolidado multi-FIDC
- tornou a carteira auditável com reconciliação explícita
- resolveu a ambiguidade operacional das seleções duplicadas
- reduziu redundância real da visão online
- deixou o PPT um pouco mais aderente ao comportamento nativo do Office

O resultado é uma base mais robusta, mais rastreável e menos sujeita a erro silencioso, preservando a experiência geral do dashboard.
