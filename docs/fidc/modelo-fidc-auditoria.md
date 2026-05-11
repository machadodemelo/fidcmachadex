# Auditoria da aba Modelo FIDC

Data da auditoria: 28/04/2026.

## Escopo

Esta auditoria compara a mecânica atual da aba `Modelo FIDC` do Streamlit com a planilha de referência `Modelo_Publico.xlsm`, com foco em cálculo, memória, KPIs e gráficos. A prioridade não foi redesenhar a interface.

Observação importante: no momento da auditoria, o arquivo local `Modelo_Publico.xlsm` estava modificado em relação ao Git e havia um lock `~$Modelo_Publico.xlsm`. Os valores cacheados da planilha local não estavam com o cenário informado pelo usuário: `C6 = 4,00% a.m.`, `C9 = R$ 750.000.000,00` e `C13 = 0,00%`. Por isso, a comparação linha a linha foi feita de duas formas:

- validação de paridade contra os valores cacheados atuais da planilha, usando as premissas atuais dela;
- reprodução do cenário informado pelo usuário no motor Python, usando a mesma lógica de fórmulas do Excel e também a configuração padrão do app com B3.

## Onde fica a lógica

| Tema | Local no repo |
|---|---|
| Inputs, labels, parsing pt-BR, montagem de gráficos e exportação | `tabs/tab_modelo_fidc.py` |
| Contratos de premissas, resultados por período e KPIs | `services/fidc_model/contracts.py` |
| Motor de fluxo, juros, custos, perdas de crédito, amortização, residual SUB e KPIs-base | `services/fidc_model/engine.py` |
| XIRR, duration e lookup de Pre DI na duration | `services/fidc_model/metrics.py` |
| Interpolação spline e Flat Forward 252 | `services/fidc_model/curves.py` |
| Dias úteis, feriados B3 e calendário projetado | `services/fidc_model/calendar.py` |
| Consulta e parsing da curva TaxaSwap B3 | `services/fidc_model/b3_curves.py` |
| Snapshot local de datas, feriados, curva e premissas históricas | `model_data.json` |
| Testes de paridade e UI da aba | `tests/test_fidc_model.py`, `tests/test_tab_modelo_fidc.py` |

## Mecânica da planilha

Abas relevantes:

- `Fluxo Base`: premissas, fluxo econômico, amortização, juros, saldos, XIRR, duration e subordinação.
- `BMF`: curva DI x Pré, com fórmulas históricas para URL `TxRef1.asp`.
- `Holidays`: feriados usados por `NETWORKDAYS`.
- `Vencimentário`: cronograma mensal auxiliar de vencimentos.

Fórmulas centrais observadas:

| Item | Fórmula da planilha |
|---|---|
| Taxa de cessão | `Q = carteira * ((1 + C6) ^ (delta_DU / 21) - 1)` |
| Custo adm/gestão | `T = max(carteira * C11 / 12, C12)` |
| Inadimplência histórica | `U = carteira * (C13 * delta_DC / 100)` |
| Taxa SEN pós | `J = (1 + PreDI) * (1 + C16) - 1` |
| Taxa MEZZ pós | `L = (1 + PreDI) * (1 + C20) - 1` |
| FRA SEN/MEZZ | composição entre taxas anuais em base 252 DU |
| Saldo FIDC | `R_t = R_t-1 + fluxo - custos - perda da carteira - PMT SEN - PMT MEZZ` |
| SUB residual corrente | `R - PL SEN - PL MEZZ` |
| SUB no workbook | a partir da segunda linha calculada, `AO` passa a referenciar o residual da linha seguinte |
| XIRR SEN/MEZZ | `XIRR(PMT, datas)` |
| XIRR SUB | `XIRR(AN, datas)`, mas `AN = 0`; usualmente resulta `#NUM!` |
| Duration SEN | média ponderada dos PMTs SEN descontados por DU/252 |
| Pre DI na duration | `VLOOKUP(ROUNDDOWN(duration * 12, 0), E:I, 5, FALSE)` |

## Paridade com a planilha local

Usando as premissas atualmente salvas na planilha local (`C6 = 4,00% a.m.`, volume `R$ 750MM`, inadimplência `0,00%`), o motor Python bateu com os valores cacheados do Excel com erro apenas numérico de ponto flutuante.

| Campo comparado | Maior diferença absoluta |
|---|---:|
| PL FIDC | `0,000001` |
| Fluxo carteira | `0,00000004` |
| Perda de crédito | `0,000000` |
| PMT SEN | `0,00000013` |
| PMT MEZZ | `0,00000001` |
| PL SEN/MEZZ | `0,000000` |
| SUB deslocada do workbook | `0,000001` |
| Subordinação deslocada do workbook | `0,000000` |

Conclusão: a divergência observada no cenário informado não vem de uma falha genérica do motor em replicar a planilha. Ela vem principalmente de diferenças de fonte/metodologia, da interpretação econômica de algumas fórmulas e da forma como o gráfico estava usando a coluna deslocada de SUB.

## Cenário informado pelo usuário

Premissas: volume `R$ 1.000.000.000,00`, taxa de cessão `1,00% a.m.`, custo `0,35% a.a.`, custo mínimo `R$ 20.000,00/mês`, inadimplência `10,00%`, SEN `75,0%`, MEZZ `15,0%`, SUB `10,0%`, spread SEN `1,35% a.a.`, spread MEZZ `5,00% a.a.`, SUB residual.

| Configuração | Retorno SEN | Retorno MEZZ | Duration SEN | Pre DI duration |
|---|---:|---:|---:|---:|
| Fórmula Excel-equivalente com curva local/model_data, spline e feriados do snapshot | `15,81%` | `19,96%` | `2,56 anos` | `14,35%` |
| Configuração padrão do app em 28/04/2026: B3 latest, Flat Forward 252 e calendário B3 oficial/projetado | `14,90%` | `18,97%` | `2,56 anos` | `13,60%` |

Esses números reproduzem os KPIs observados no Streamlit. A diferença de retorno SEN/MEZZ e Pre DI vem da curva/metodologia/calendário selecionados, não da taxa de cessão ou inadimplência. No modelo atual, os pagamentos SEN/MEZZ são programados e não são limitados por caixa disponível.

## Divergências e causas

| Campo/fórmula | Streamlit observado | Excel-equivalente | Provável causa | Recomendação |
|---|---:|---:|---|---|
| Fonte da curva | B3 TaxaSwap latest em 28/04/2026 | Curva local/model_data equivalente ao workbook salvo em 27/04/2026 | Fontes e datas diferentes | Manter seleção explícita e, para auditoria, usar snapshot/spline/calendário snapshot |
| Interpolação | Flat Forward 252 | Spline da planilha | Metodologia diferente por decisão de modelo | Correto manter Flat Forward 252 para B3, mas identificar claramente quando a comparação é com Excel |
| Calendário de DU | B3 oficial 2025-2026 + projeção 2027-2028 | `Holidays` da planilha, terminando em 2018 | Feriados futuros não existem no snapshot da planilha | Manter calendário B3/projeção explícita; usar snapshot só para auditoria |
| Perda de crédito | Antes: perda de `18,40%` no primeiro semestre para input `10,00%`; agora: Perda Esperada + Perda Inesperada mensal | Fórmula nova no Streamlit; fórmula histórica preservada quando não há campos novos | O modelo online ficou mais explícito que a coluna histórica de inadimplência da planilha | Usar PE/PI para simulação econômica e manter a planilha histórica como referência |
| PMT SEN/MEZZ | Pago mesmo com PL/carteira negativa | Mesma fórmula | Não há trava de caixa nem waterfall de insuficiência | Implementar waterfall real em etapa estrutural posterior |
| XIRR SEN/MEZZ | Independe da inadimplência enquanto PMTs programados existem | Mesma fórmula | PMTs não são afetados por default/cash shortfall | Só mudará com waterfall de caixa |
| XIRR SUB | `N/D` | `#NUM!` | A SUB tem `PMT = 0` na planilha; não há série com sinais válidos | Correto mostrar `N/D`, mas explicar que SUB residual não tem fluxo programado |
| SUB no gráfico de saldos | Área negativa próxima de `-R$ 700MM` | Residual pode ficar negativo | O residual está representando déficit econômico, não saldo de investidor | Separar SUB disponível de déficit econômico |
| Subordinação | Chega a cerca de `-8.000%` | A coluna deslocada do workbook também explode quando dividida por PL próximo de zero | Denominador próximo de zero e uso de residual deslocado `pl_sub_jr_modelo` | Gráfico deve usar SUB corrente positiva sobre PL positivo; manter coluna deslocada só na timeline |
| Título “Perda máxima” | Plota inadimplência acumulada e subordinação | Não há cálculo robusto de perda máxima por waterfall | O título é mais forte que a memória atual | Criar métrica de perda máxima quando waterfall for modelado |

## Bug corrigido nesta auditoria

O gráfico usava `pl_sub_jr_modelo`, que preserva a lógica deslocada da coluna `AO` do Excel. Essa coluna é útil para paridade da tabela, mas é ruim para visualização econômica porque mistura residual da próxima linha com PL da linha corrente.

Correção aplicada:

- o gráfico de saldos usa o residual corrente `pl_sub_jr`;
- SUB disponível é exibida como `max(pl_sub_jr, 0)`;
- quando o residual fica negativo, o valor aparece como `Déficit econômico`;
- o gráfico de subordinação usa `max(pl_sub_jr, 0) / pl_fidc` apenas quando `pl_fidc > 0`;
- a timeline detalhada continua preservando as colunas brutas e a coluna deslocada do workbook para auditoria.

## Simplificações que permanecem

- O modelo ainda não implementa waterfall real com insuficiência de caixa.
- A amortização SEN/MEZZ segue o cronograma já existente em `model_data.json`/planilha; não há input avançado para frequência, carência e amortização customizada.
- A SUB continua residual e sem fluxo programado; por isso não há retorno anualizado SUB.
- A aba agora separa Perda Esperada e Perda Inesperada como taxas mensais sobre a carteira; a fórmula histórica de inadimplência fica apenas como compatibilidade do motor.
- A métrica de “perda máxima” ainda precisa de uma definição estrutural mais precisa quando houver waterfall.

## Estrutura recomendada para próxima etapa

Adicionar uma seção avançada com:

- frequência de amortização SEN/MEZZ;
- início de amortização SEN/MEZZ;
- tipo de amortização: linear, bullet ou customizada;
- carência de juros SEN/MEZZ;
- início do pagamento de juros SEN/MEZZ;
- trava de caixa disponível;
- prioridade de waterfall;
- regra de residual da SUB;
- modo avançado de NPL over 90, LGD, recuperação e write-off.

## Atualização implementada: prazo, revolvência e perda máxima

A aba passou a incluir premissas avançadas para:

- prazo total do FIDC;
- prazo médio dos recebíveis;
- modo de originação: carteira revolvente ou carteira estática;
- prazo das cotas SEN, MEZZ e SUB;
- amortização de principal SEN/MEZZ: cronograma padrão, linear após carência, bullet ou sem amortização programada;
- pagamento de juros SEN/MEZZ: em todo período, após carência ou bullet no vencimento.

A taxa econômica da carteira também pode ser ajustada por ágio e por piso de spread:

```text
agio_aquisicao = volume_inicial * agio_aquisicao_pct
tx_cessao_am_aplicada = max(tx_cessao_am_informada, remuneracao_SEN + excesso_spread)
```

O ágio reduz a SUB econômica inicial, pois representa prêmio pago na aquisição dos recebíveis. O piso de spread garante que a carteira remunere, no mínimo, a SEN mais o excesso informado.

Para carteira revolvente, o saldo em aberto usado para juros e perdas evolui com principal reciclado e excesso de caixa reinvestido. Essa nova originação só ocorre enquanto o prazo médio dos recebíveis ainda cabe no prazo restante do FIDC; perto do vencimento, a carteira entra em runoff e o caixa não reinvestido não recebe SELIC no modelo.

A principal métrica adicionada é a perda máxima suportada sobre a carteira originada:

```text
giro_estimado = prazo_total_fidc_anos * 12 / prazo_medio_recebiveis_meses
mes_limite_reinvestimento = prazo_total_fidc_meses - prazo_medio_recebiveis_meses
principal_recebido = carteira_inicio * meses_periodo / prazo_medio_recebiveis_meses
nova_originacao_economica = principal_recebido + max(fluxo_remanescente_apos_MEZZ, 0)
nova_originacao_denominador = volume_inicial * max(prazo_total_meses - prazo_medio_recebiveis_meses, 0) / prazo_medio_recebiveis_meses
carteira_originada_revolvente = volume_inicial + nova_originacao_denominador
carteira_originada_estatica = volume_inicial
perda_maxima = max(SUB_final_sem_perdas, 0) / carteira_originada
```

Essa métrica usa uma simulação paralela com Perda Esperada e Perda Inesperada iguais a `0%`, preservando as demais premissas selecionadas. Assim, ela mede quanto colchão subordinado econômico seria acumulado antes de perdas e compara esse colchão ao total estimado de recebíveis originados ao longo do prazo do FIDC.

A aba também calcula a proteção ao longo do tempo:

```text
nova_originacao_acumulada = volume_inicial * min(mes_fidc, mes_limite_reinvestimento) / prazo_medio_recebiveis_meses
denominador_no_mes = volume_inicial + nova_originacao_acumulada
perda_maxima_no_mes = SUB_disponivel_no_mes / denominador_no_mes
```

Com prazo médio de recebíveis de `6 meses`, a carteira revolvente recicla aproximadamente `1/6` do volume inicial por mês para o denominador, e a carteira inicial já conta como primeiro ciclo. Em uma estrutura de `R$ 750MM`, prazo de `36 meses` e PM de `6 meses`, a carteira total originada do denominador é `6 x R$ 750MM = R$ 4,5 bi`, não `R$ 5,25 bi`. Eventual excesso de caixa reinvestido afeta a simulação econômica e a SUB, mas não cria um ciclo adicional no denominador padrão da perda máxima.

Premissa de caixa: o modelo presume que não há excesso de caixa aplicado à SELIC. Enquanto a revolvência é elegível, todo caixa disponível é reinvestido na compra de nova carteira revolvente. Depois que o prazo médio dos recebíveis já não cabe no prazo restante, o caixa deixa de ser reinvestido e também não é remunerado por SELIC. Essa simplificação pode superestimar rentabilidade quando a carteira é boa e ampliar perda quando a carteira é ruim, mas muitos FIDCs não carregam caixa relevante em excesso por longos períodos.

## Validação manual

Para reproduzir a auditoria no app:

1. Abra a aba `Modelo FIDC`.
2. Informe as premissas do cenário do usuário.
3. Para reproduzir os KPIs observados, use `B3 - último pregão disponível`, `Flat Forward 252` e calendário `B3 oficial + projeção explícita`.
4. Para uma comparação histórica local, use `Curva local salva`, `Spline` e `Feriados locais salvos`.
5. Verifique se a timeline detalhada mostra `pl_sub_jr`, `pl_sub_jr_modelo`, `subordinacao_pct` e `subordinacao_pct_modelo`.
6. Confirme que o gráfico não usa mais a coluna deslocada como saldo da SUB e que o déficit econômico aparece separado quando o residual fica negativo.
